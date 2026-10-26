"""Cactus Needle (needle3) integration for MiroFish's local-graph mode.

What Needle is — and is not — for MiroFish, verified 2026-10-25:

* Needle is a tool-call / extraction / embedding model, NOT a chat model.
  ``needle.Needle.run()`` / ``complete()`` return function calls, reasoning
  and confidence — no free-form text. It therefore CANNOT replace the
  OpenAI-compatible LLM (currently NVIDIA) used for ontology generation,
  persona/profile generation, simulation config, OASIS agents or reports.
  A drop-in LLM swap was tested and rejected: open-ended graph extraction
  via Needle returned suppressed calls at confidence 0.005-0.017, and
  ``needle.extract()`` raised groundedness validation errors on ordinary
  prose. Wiring it as the chat LLM would break those stages.
* What Needle DOES do well, locally and offline, is embeddings
  (``Needle.embed()``, 3072-dim, Needle 3). MiroFish's local graph search
  is keyword-overlap only (see local_graph.py), so Needle is wired here
  as a re-ranker: keyword search still decides recall, Needle cosine
  similarity only re-orders the keyword hits. It never invents a hit,
  never adds a candidate keyword search missed, and if Needle is
  unavailable the search silently falls back to keyword order.

Usage: set NEEDLE_WEIGHTS to a needle3.cact file (e.g.
``~/workspace/needle-test/models/needle3.cact``) and
NEEDLE_ENABLED=true in MiroFish's .env. Leave NEEDLE_ENABLED unset/false
and nothing changes. The NVIDIA LLM config is untouched.
"""

from __future__ import annotations

import math
import os
import threading
from typing import Any

from ..utils.logger import get_logger

logger = get_logger("mirofish.needle_client")

_lock = threading.Lock()
_embedder = None
_embedder_error: str | None = None


def is_available() -> bool:
    """True only if the cactus-needle package imports."""
    try:
        import needle  # noqa: F401
        return True
    except Exception:
        return False


def _load_embedder(weights: str):
    global _embedder, _embedder_error
    with _lock:
        if _embedder is not None:
            return _embedder
        if _embedder_error is not None:
            return None
        try:
            import needle
            os.environ.setdefault("NEEDLE_TELEMETRY", "0")
            os.environ.setdefault("DO_NOT_TRACK", "1")
            _embedder = needle.Needle(weights=weights, tools=[])
            logger.info("Needle embedder loaded: %s", weights)
            return _embedder
        except Exception as exc:  # package missing, bad weights, no engine
            _embedder_error = str(exc)
            logger.warning("Needle embedder unavailable: %s", exc)
            return None


def embed(text: str, weights: str) -> list[float] | None:
    """Embed one text with Needle 3, or None if unavailable."""
    agent = _load_embedder(weights)
    if agent is None:
        return None
    try:
        with _lock:
            vec = agent.embed(text or "")
        return [float(v) for v in vec] if vec else None
    except Exception as exc:
        logger.warning("Needle embed failed: %s", exc)
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def rerank_by_embedding(query: str, scored: list[tuple[int, dict]],
                        text_fn, weights: str) -> list[tuple[int, dict]]:
    """Re-order keyword hits by Needle cosine similarity.

    ``scored`` is a list of (keyword_score, item) as produced by
    LocalGraphStore.search. The keyword score is kept as the primary
    signal only in that items with score 0 never reach here; within the
    hit list, Needle similarity decides the order. On any failure the
    original order is returned unchanged.
    """
    if not scored or not query or not weights:
        return scored
    query_vec = embed(query, weights)
    if query_vec is None:
        return scored
    reranked = []
    for score, item in scored:
        vec = embed(text_fn(item), weights)
        sim = _cosine(query_vec, vec) if vec is not None else 0.0
        reranked.append((sim, score, item))
    # Keyword score stays primary: Needle's embeddings rank correctly but
    # with compressed margins (0.93-0.97 on unrelated sentences in testing),
    # so it must not overrule a clear phrase/token match. Needle only
    # breaks keyword ties — the common case, where many hits share a
    # 10-point token score — and never drops a keyword hit.
    reranked.sort(key=lambda x: (x[1], x[0]), reverse=True)
    return [(score, item) for _, score, item in reranked]
