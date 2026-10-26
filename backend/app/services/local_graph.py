"""Local JSON graph store used when no Zep Cloud key is configured.

This is a deliberate, limited replacement for Zep Cloud, not a full
knowledge-graph engine: there is no vector/semantic search and no
asynchronous ingestion. Graphs are one JSON file per graph_id under
``Config.LOCAL_GRAPH_DIR`` (``backend/uploads/local_graphs``), created on
first use. When ``ZEP_API_KEY`` is present the original Zep Cloud path is
used unchanged and this store is never consulted.

File format (per graph)::

    {
      "graph_id": str, "name": str, "description": str,
      "ontology": {"entity_types": [...], "edge_types": [...]},
      "nodes": [{"uuid", "name", "labels", "summary", "attributes"}],
      "edges": [{"uuid", "name", "fact", "fact_type",
                 "source_node_uuid", "target_node_uuid",
                 "attributes", "episodes"}],
      "episodes": [{"uuid", "data", "type", "source_description",
                    "metadata", "created_at", "processed": true}],
      "batches": {batch_id: {"batch_id", "metadata", "graph_id",
                             "status", "progress", "items": [...]}},
    }

Nodes are deduplicated by lower-cased name; edges by
(source, target, lower-cased fact). Search is keyword-overlap scoring
over name/summary/fact, with a phrase bonus -- it is a fallback, not a
semantic ranking, and callers must not treat its order as semantic.

Optional Needle re-ranking: when Config.NEEDLE_ENABLED and
Config.NEEDLE_WEIGHTS point at a needle3.cact file, Cactus Needle
embedding cosine similarity breaks ties between keyword hits (see
backend/app/utils/needle_client.py). Needle never adds a hit keyword
search missed, never overrules a keyword-score difference, and any
Needle failure leaves keyword order unchanged.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from typing import Any

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.local_graph")

_lock = threading.RLock()


def _sanitize_graph_id(graph_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", str(graph_id or "")) or "graph"


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,，;；:：。.!?？、/\\|]+", (text or "").lower()) if t]


def _score(query: str, text: str) -> int:
    """Keyword-overlap score; 0 means no match at all."""
    if not query or not text:
        return 0
    q, t = query.lower(), text.lower()
    if q in t:
        return 100
    score = 0
    for token in _tokenize(q):
        if len(token) > 1 and token in t:
            score += 10
        elif len(token) == 1 and token in t:
            score += 1
    # Chinese / unsegmented queries: reward shared character bigrams so a
    # long query sentence still matches a relevant fact instead of nothing.
    if score == 0 and len(q) > 2:
        bigrams = {q[i : i + 2] for i in range(len(q) - 1)}
        hits = sum(1 for b in bigrams if b in t)
        score = min(hits * 2, 40)
    return score


class LocalGraphStore:
    """Thread-safe JSON-file store, one file per graph."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or Config.LOCAL_GRAPH_DIR

    # -- paths / raw IO -------------------------------------------------
    def _path(self, graph_id: str) -> str:
        return os.path.join(self.base_dir, _sanitize_graph_id(graph_id) + ".json")

    def _ensure_dir(self) -> None:
        os.makedirs(self.base_dir, exist_ok=True)

    def _load(self, graph_id: str) -> dict | None:
        path = self._path(graph_id)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, graph: dict) -> None:
        self._ensure_dir()
        path = self._path(graph["graph_id"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _all_graphs(self) -> list[dict]:
        self._ensure_dir()
        graphs = []
        for name in sorted(os.listdir(self.base_dir)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.base_dir, name), encoding="utf-8") as f:
                    graphs.append(json.load(f))
            except (OSError, ValueError):
                continue
        return graphs

    # -- graphs ---------------------------------------------------------
    def get_or_create(self, graph_id: str, name: str | None = None,
                      description: str | None = None) -> dict:
        with _lock:
            graph = self._load(graph_id)
            if graph is not None:
                return graph
            graph = {
                "graph_id": graph_id,
                "name": name or graph_id,
                "description": description or "",
                "ontology": {},
                "nodes": [],
                "edges": [],
                "episodes": [],
                "batches": {},
            }
            self._save(graph)
            return graph

    def get(self, graph_id: str) -> dict | None:
        with _lock:
            return self._load(graph_id)

    def delete(self, graph_id: str) -> bool:
        with _lock:
            path = self._path(graph_id)
            if not os.path.exists(path):
                return False
            os.remove(path)
            return True

    def set_ontology(self, graph_id: str, ontology: dict) -> dict:
        with _lock:
            graph = self.get_or_create(graph_id)
            graph["ontology"] = ontology or {}
            self._save(graph)
            return graph

    # -- episodes -------------------------------------------------------
    def add_episode(self, graph_id: str, data: str, *,
                    source_description: str | None = None,
                    metadata: dict | None = None,
                    created_at: str | None = None) -> dict:
        with _lock:
            graph = self.get_or_create(graph_id)
            episode = {
                "uuid": str(uuid.uuid4()),
                "data": data or "",
                "type": "text",
                "source_description": source_description or "",
                "metadata": metadata or {},
                "created_at": created_at,
                "processed": True,
            }
            graph["episodes"].append(episode)
            self._save(graph)
            return episode

    def get_episode(self, episode_uuid: str) -> dict | None:
        with _lock:
            for graph in self._all_graphs():
                for episode in graph.get("episodes", []):
                    if episode.get("uuid") == episode_uuid:
                        return episode
        return None

    # -- nodes / edges --------------------------------------------------
    def add_node(self, graph_id: str, name: str, *,
                 labels: list[str] | None = None,
                 summary: str | None = None,
                 attributes: dict | None = None) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("node name is required")
        with _lock:
            graph = self.get_or_create(graph_id)
            for node in graph["nodes"]:
                if node["name"].lower() == name.lower():
                    # Merge: union labels, new attributes win, keep summary.
                    merged = list(node.get("labels") or [])
                    for label in labels or []:
                        if label not in merged:
                            merged.append(label)
                    node["labels"] = merged
                    node["attributes"] = {**(node.get("attributes") or {}),
                                          **(attributes or {})}
                    if not node.get("summary") and summary:
                        node["summary"] = summary
                    self._save(graph)
                    return node
            node = {
                "uuid": str(uuid.uuid4()),
                "name": name,
                "labels": list(labels or ["Entity"]),
                "summary": summary or "",
                "attributes": attributes or {},
            }
            graph["nodes"].append(node)
            self._save(graph)
            return node

    def add_edge(self, graph_id: str, source_node_uuid: str,
                 target_node_uuid: str, *, name: str | None = None,
                 fact: str | None = None,
                 attributes: dict | None = None,
                 episodes: list[str] | None = None) -> dict:
        fact = (fact or "").strip()
        with _lock:
            graph = self.get_or_create(graph_id)
            for edge in graph["edges"]:
                if (edge["source_node_uuid"] == source_node_uuid
                        and edge["target_node_uuid"] == target_node_uuid
                        and (edge.get("fact") or "").lower() == fact.lower()):
                    return edge
            edge = {
                "uuid": str(uuid.uuid4()),
                "name": name or fact or "",
                "fact": fact,
                "fact_type": name or fact or "",
                "source_node_uuid": source_node_uuid,
                "target_node_uuid": target_node_uuid,
                "attributes": attributes or {},
                "episodes": list(episodes or []),
                "created_at": None,
                "valid_at": None,
                "invalid_at": None,
                "expired_at": None,
            }
            graph["edges"].append(edge)
            self._save(graph)
            return edge

    def list_nodes(self, graph_id: str) -> list[dict]:
        graph = self._load(graph_id)
        return list(graph["nodes"]) if graph else []

    def list_edges(self, graph_id: str) -> list[dict]:
        graph = self._load(graph_id)
        return list(graph["edges"]) if graph else []

    def get_node_by_uuid(self, node_uuid: str) -> dict | None:
        with _lock:
            for graph in self._all_graphs():
                for node in graph.get("nodes", []):
                    if node.get("uuid") == node_uuid:
                        return node
        return None

    def get_edges_for_node(self, node_uuid: str) -> list[dict]:
        edges = []
        with _lock:
            for graph in self._all_graphs():
                for edge in graph.get("edges", []):
                    if (edge.get("source_node_uuid") == node_uuid
                            or edge.get("target_node_uuid") == node_uuid):
                        edges.append(edge)
        return edges

    def find_node_by_name(self, graph_id: str, name: str) -> dict | None:
        graph = self._load(graph_id)
        if not graph:
            return None
        for node in graph["nodes"]:
            if node["name"].lower() == (name or "").strip().lower():
                return node
        return None

    # -- search ---------------------------------------------------------
    def search(self, graph_id: str, query: str, limit: int = 10,
               scope: str = "edges") -> dict[str, Any]:
        graph = self._load(graph_id)
        if not graph:
            return {"nodes": [], "edges": [], "facts": []}
        scored_nodes, scored_edges = [], []
        if scope in ("nodes", "both"):
            for node in graph["nodes"]:
                s = max(_score(query, node.get("name", "")),
                        _score(query, node.get("summary", "")))
                if s > 0:
                    scored_nodes.append((s, node))
        if scope in ("edges", "both"):
            for edge in graph["edges"]:
                s = max(_score(query, edge.get("fact", "")),
                        _score(query, edge.get("name", "")))
                if s > 0:
                    scored_edges.append((s, edge))
        scored_nodes.sort(key=lambda x: x[0], reverse=True)
        scored_edges.sort(key=lambda x: x[0], reverse=True)
        if Config.NEEDLE_ENABLED and Config.NEEDLE_WEIGHTS:
            try:
                from ..utils import needle_client
                scored_nodes = needle_client.rerank_by_embedding(
                    query, scored_nodes,
                    lambda n: f"{n.get('name', '')} {n.get('summary', '')}",
                    Config.NEEDLE_WEIGHTS)
                scored_edges = needle_client.rerank_by_embedding(
                    query, scored_edges,
                    lambda e: e.get('fact', '') or e.get('name', ''),
                    Config.NEEDLE_WEIGHTS)
            except Exception as exc:  # Never let ranking break search.
                logger.warning("Needle re-ranking skipped: %s", exc)
        nodes = [n for _, n in scored_nodes[:limit]]
        edges = [e for _, e in scored_edges[:limit]]
        facts = [e["fact"] for e in edges if e.get("fact")]
        for node in nodes:
            if node.get("summary"):
                facts.append(f"[{node['name']}]: {node['summary']}")
        return {"nodes": nodes, "edges": edges, "facts": facts}

    # -- batches (local, always synchronous) -----------------------------
    def batch_create(self, graph_id: str | None,
                     metadata: dict | None = None) -> dict:
        batch_id = f"local_{uuid.uuid4().hex[:16]}"
        batch = {
            "batch_id": batch_id,
            "metadata": metadata or {},
            "graph_id": graph_id,
            "status": "draft",
            "progress": {"percent_complete": 0, "succeeded_items": 0},
            "items": [],
        }
        if graph_id:
            with _lock:
                graph = self.get_or_create(graph_id)
                graph.setdefault("batches", {})[batch_id] = batch
                self._save(graph)
        else:
            # Graph-less batches are not used by GraphBuilder, but keep them
            # discoverable so batch.get never invents a success.
            with _lock:
                self._ensure_dir()
                sidecar = os.path.join(self.base_dir, "_batches.json")
                data = {}
                if os.path.exists(sidecar):
                    with open(sidecar, encoding="utf-8") as f:
                        data = json.load(f)
                data[batch_id] = batch
                with open(sidecar, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        return batch

    def _find_batch(self, batch_id: str) -> tuple[dict | None, dict | None]:
        """Return (graph_dict_or_None, batch_dict_or_None)."""
        with _lock:
            for graph in self._all_graphs():
                batch = (graph.get("batches") or {}).get(batch_id)
                if batch is not None:
                    return graph, batch
            sidecar = os.path.join(self.base_dir, "_batches.json")
            if os.path.exists(sidecar):
                try:
                    with open(sidecar, encoding="utf-8") as f:
                        batch = json.load(f).get(batch_id)
                    if batch is not None:
                        return None, batch
                except (OSError, ValueError):
                    pass
        return None, None

    def batch_get(self, batch_id: str) -> dict | None:
        _, batch = self._find_batch(batch_id)
        return batch

    def batch_list(self) -> list[dict]:
        batches = []
        with _lock:
            for graph in self._all_graphs():
                batches.extend((graph.get("batches") or {}).values())
        return batches

    def batch_add_items(self, batch_id: str, items: list[dict]) -> list[dict]:
        graph, batch = self._find_batch(batch_id)
        if batch is None:
            raise KeyError(f"local batch not found: {batch_id}")
        added = []
        for item in items:
            episode_uuid = str(uuid.uuid4())
            record = {
                "episode_uuid": episode_uuid,
                "source_uuid": episode_uuid,
                "sequence_index": len(batch["items"]),
                "status": "succeeded",
                "data": item.get("data") if isinstance(item, dict) else None,
            }
            batch["items"].append(record)
            added.append(record)
        if graph is not None:
            with _lock:
                # Re-load to avoid clobbering concurrent writes, then save.
                current = self._load(graph["graph_id"])
                if current is not None:
                    current.setdefault("batches", {})[batch_id] = batch
                    self._save(current)
        return added

    def batch_process(self, batch_id: str) -> dict | None:
        graph, batch = self._find_batch(batch_id)
        if batch is None:
            return None
        batch["status"] = "succeeded"
        batch["progress"] = {
            "percent_complete": 100,
            "succeeded_items": len(batch["items"]),
        }
        if graph is not None:
            with _lock:
                current = self._load(graph["graph_id"])
                if current is not None:
                    current.setdefault("batches", {})[batch_id] = batch
                    self._save(current)
        return batch

    def batch_list_items(self, batch_id: str) -> list[dict]:
        _, batch = self._find_batch(batch_id)
        return list(batch["items"]) if batch else []

    def batch_complete(self, batch_id: str,
                       episode_uuids: list[str]) -> dict | None:
        """Mark a local batch succeeded with the given episode UUIDs.

        Used by GraphBuilder's local ingestion path, which creates
        episodes directly (so batch_add_items' fresh UUIDs would not
        match) and then records the real episode UUIDs here.
        """
        graph, batch = self._find_batch(batch_id)
        if batch is None:
            return None
        batch["items"] = [
            {"episode_uuid": ep, "source_uuid": ep,
             "sequence_index": i, "status": "succeeded"}
            for i, ep in enumerate(episode_uuids)
        ]
        batch["status"] = "succeeded"
        batch["progress"] = {"percent_complete": 100,
                             "succeeded_items": len(episode_uuids)}
        if graph is not None:
            with _lock:
                current = self._load(graph["graph_id"])
                if current is not None:
                    current.setdefault("batches", {})[batch_id] = batch
                    self._save(current)
        return batch
