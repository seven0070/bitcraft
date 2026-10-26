"""Local stand-in for the Zep Cloud client, backed by LocalGraphStore.

Only the surface MiroFish actually calls is implemented (see the task
spec): graph.create/get/delete/set_ontology/add/search,
graph.node.get/get_edges (+ with_raw_response.get_by_graph_id),
graph.edge.with_raw_response.get_by_graph_id, graph.episode.get, and
batch.create/add/process/get/list/list_items. Returned objects are
``types.SimpleNamespace`` instances carrying exactly the attributes
callers read (``uuid_``/``uuid``, ``name``, ``labels``, ``summary``,
``attributes``, ``fact``, ``source_node_uuid``, ``target_node_uuid``,
``processed``, ``status``, ``progress.percent_complete`` /
``progress.succeeded_items``, item ``episode_uuid``/``source_uuid`` /
``sequence_index``/``status``). Unknown keyword arguments (e.g. Zep
``reranker``) are accepted and ignored -- local search is keyword-based.

Missing graphs/nodes/episodes/batches raise the shared NotFoundError
from ``app.utils.zep`` (the real zep_cloud one when installed, otherwise
the local fallback class), so existing ``except NotFoundError`` handlers
work unchanged in both modes.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ..services.local_graph import LocalGraphStore
from .zep import NotFoundError  # noqa: F401  (re-exported for callers)

# NOTE: local_zep_client imports utils.zep only for NotFoundError, and
# utils.zep imports this module lazily inside get_zep_client(), so there
# is no import-time cycle.


def _node_ns(node: dict) -> SimpleNamespace:
    return SimpleNamespace(
        uuid_=node.get("uuid"),
        uuid=node.get("uuid"),
        name=node.get("name", ""),
        labels=list(node.get("labels") or []),
        summary=node.get("summary", ""),
        attributes=dict(node.get("attributes") or {}),
        created_at=node.get("created_at"),
    )


def _edge_ns(edge: dict) -> SimpleNamespace:
    return SimpleNamespace(
        uuid_=edge.get("uuid"),
        uuid=edge.get("uuid"),
        name=edge.get("name", ""),
        fact=edge.get("fact", ""),
        fact_type=edge.get("fact_type") or edge.get("name", ""),
        source_node_uuid=edge.get("source_node_uuid"),
        target_node_uuid=edge.get("target_node_uuid"),
        attributes=dict(edge.get("attributes") or {}),
        episodes=list(edge.get("episodes") or []),
        episode_ids=list(edge.get("episodes") or []),
        created_at=edge.get("created_at"),
        valid_at=edge.get("valid_at"),
        invalid_at=edge.get("invalid_at"),
        expired_at=edge.get("expired_at"),
    )


def _raw_page(items: list) -> SimpleNamespace:
    return SimpleNamespace(data=items, headers={})


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


class _WithRawResponse:
    def __init__(self, fetch):
        self._fetch = fetch

    def get_by_graph_id(self, graph_id: str, *, limit: int = 100,
                        cursor: Any = None, **_kwargs) -> SimpleNamespace:
        return _raw_page(self._fetch(graph_id, limit=limit))


class _NodeAPI:
    def __init__(self, client: "LocalZepClient"):
        self._client = client
        self.with_raw_response = _WithRawResponse(
            lambda graph_id, limit=100: [
                _node_ns(n) for n in client.store.list_nodes(graph_id)[:limit]
            ]
        )

    def get(self, uuid_: str | None = None, **kwargs) -> SimpleNamespace:
        node_uuid = uuid_ or kwargs.get("uuid")
        node = self._client.store.get_node_by_uuid(node_uuid)
        if node is None:
            raise NotFoundError(f"local node not found: {node_uuid}")
        return _node_ns(node)

    def get_edges(self, node_uuid: str | None = None, **kwargs) -> list:
        nid = node_uuid or kwargs.get("node_uuid")
        return [_edge_ns(e) for e in self._client.store.get_edges_for_node(nid)]


class _EdgeAPI:
    def __init__(self, client: "LocalZepClient"):
        self.with_raw_response = _WithRawResponse(
            lambda graph_id, limit=100: [
                _edge_ns(e) for e in client.store.list_edges(graph_id)[:limit]
            ]
        )


class _EpisodeAPI:
    def __init__(self, client: "LocalZepClient"):
        self._client = client

    def get(self, uuid_: str | None = None, **kwargs) -> SimpleNamespace:
        episode_uuid = uuid_ or kwargs.get("uuid")
        episode = self._client.store.get_episode(episode_uuid)
        if episode is None:
            raise NotFoundError(f"local episode not found: {episode_uuid}")
        return SimpleNamespace(
            uuid_=episode.get("uuid"),
            uuid=episode.get("uuid"),
            data=episode.get("data", ""),
            processed=episode.get("processed", True),
        )


class _GraphAPI:
    def __init__(self, client: "LocalZepClient"):
        self._client = client
        self.node = _NodeAPI(client)
        self.edge = _EdgeAPI(client)
        self.episode = _EpisodeAPI(client)

    def create(self, graph_id: str, name: str | None = None,
               description: str | None = None, **_kwargs) -> SimpleNamespace:
        graph = self._client.store.get_or_create(graph_id, name=name,
                                                 description=description)
        return SimpleNamespace(graph_id=graph["graph_id"],
                               name=graph["name"])

    def get(self, graph_id: str, **_kwargs) -> SimpleNamespace:
        graph = self._client.store.get(graph_id)
        if graph is None:
            raise NotFoundError(f"local graph not found: {graph_id}")
        return SimpleNamespace(graph_id=graph["graph_id"],
                               name=graph["name"])

    def delete(self, graph_id: str, **_kwargs) -> None:
        if not self._client.store.delete(graph_id):
            raise NotFoundError(f"local graph not found: {graph_id}")

    def set_ontology(self, graph_ids: list | None = None, *,
                     entities: Any = None, edges: Any = None,
                     ontology: dict | None = None, **_kwargs) -> None:
        if ontology is not None:
            stored = ontology
        else:
            entity_types = []
            if isinstance(entities, dict):
                for name in entities:
                    entity_types.append({"name": name})
            edge_types = []
            if isinstance(edges, dict):
                for name in edges:
                    edge_types.append({"name": name})
            stored = {"entity_types": entity_types, "edge_types": edge_types}
        for graph_id in graph_ids or []:
            self._client.store.set_ontology(graph_id, stored)

    def add(self, graph_id: str, type: str = "text", data: str = "",
            created_at: str | None = None, source_description: str | None = None,
            metadata: dict | None = None, **_kwargs) -> SimpleNamespace:
        episode = self._client.store.add_episode(
            graph_id, data, source_description=source_description,
            metadata=metadata, created_at=created_at)
        return SimpleNamespace(uuid_=episode["uuid"], uuid=episode["uuid"],
                               processed=True, data=data)

    def search(self, graph_id: str, query: str, limit: int = 10,
               scope: str = "edges", **_kwargs) -> SimpleNamespace:
        result = self._client.store.search(graph_id, query, limit=limit,
                                           scope=scope)
        return SimpleNamespace(
            nodes=[_node_ns(n) for n in result["nodes"]],
            edges=[_edge_ns(e) for e in result["edges"]],
            facts=list(result["facts"]),
        )


class _BatchAPI:
    def __init__(self, client: "LocalZepClient"):
        self._client = client

    def create(self, metadata: dict | None = None, **_kwargs) -> SimpleNamespace:
        metadata = metadata or {}
        batch = self._client.store.batch_create(
            metadata.get("graph_id"), metadata=metadata)
        return SimpleNamespace(batch_id=batch["batch_id"],
                               status=batch["status"])

    def add(self, batch_id: str, items: list | None = None,
            **_kwargs) -> list:
        normalized = []
        for item in items or []:
            normalized.append({
                "data": _field(item, "data"),
                "graph_id": _field(item, "graph_id"),
            })
        records = self._client.store.batch_add_items(batch_id, normalized)
        return [
            SimpleNamespace(episode_uuid=r["episode_uuid"],
                            source_uuid=r["source_uuid"],
                            sequence_index=r["sequence_index"],
                            status=r["status"])
            for r in records
        ]

    def process(self, batch_id: str, **_kwargs) -> SimpleNamespace:
        batch = self._client.store.batch_process(batch_id)
        if batch is None:
            raise NotFoundError(f"local batch not found: {batch_id}")
        return SimpleNamespace(batch_id=batch["batch_id"],
                               status=batch["status"])

    def get(self, batch_id: str, **_kwargs) -> SimpleNamespace:
        batch = self._client.store.batch_get(batch_id)
        if batch is None:
            raise NotFoundError(f"local batch not found: {batch_id}")
        progress = batch.get("progress") or {}
        return SimpleNamespace(
            batch_id=batch["batch_id"], status=batch["status"],
            progress=SimpleNamespace(
                percent_complete=progress.get("percent_complete", 0),
                succeeded_items=progress.get("succeeded_items", 0)),
            metadata=batch.get("metadata") or {})

    def list(self, limit: int = 100, cursor: Any = None,
             **_kwargs) -> SimpleNamespace:
        batches = self._client.store.batch_list()[:limit]
        return SimpleNamespace(
            batches=[SimpleNamespace(batch_id=b["batch_id"],
                                     status=b["status"],
                                     metadata=b.get("metadata") or {})
                     for b in batches],
            next_cursor=None)

    def list_items(self, batch_id: str, limit: int = 100,
                   cursor: Any = None, **_kwargs) -> SimpleNamespace:
        items = self._client.store.batch_list_items(batch_id)[:limit]
        return SimpleNamespace(
            items=[SimpleNamespace(episode_uuid=i["episode_uuid"],
                                   source_uuid=i["source_uuid"],
                                   sequence_index=i["sequence_index"],
                                   status=i["status"])
                   for i in items],
            next_cursor=None)


class LocalZepClient:
    """Drop-in local replacement for a Zep Cloud client."""

    is_local = True

    def __init__(self, store: LocalGraphStore | None = None):
        self.store = store or LocalGraphStore()
        self.graph = _GraphAPI(self)
        self.batch = _BatchAPI(self)

    # Helpers used by zep_paging.py without importing this module there.
    def list_nodes(self, graph_id: str) -> list:
        return [_node_ns(n) for n in self.store.list_nodes(graph_id)]

    def list_edges(self, graph_id: str) -> list:
        return [_edge_ns(e) for e in self.store.list_edges(graph_id)]
