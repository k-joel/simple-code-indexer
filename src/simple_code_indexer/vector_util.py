"""Vector validation and normalisation shared by the local stores.

Both local backends (FAISS and sqlite-vec) compare L2-normalised vectors, so the
score is cosine similarity in [-1, 1] — the same range Qdrant's COSINE distance
uses. Keeping the checks here means the two stores cannot drift apart in either
the width they accept or the error they raise.
"""

from __future__ import annotations

import numpy as np

from simple_code_indexer.errors import VectorStoreUnavailable
from simple_code_indexer.models import Chunk


def normalize_rows(
    items: list[tuple[Chunk, list[float]]], dim: int, *, path: str
) -> np.ndarray:
    """One float32 row per chunk; raises when a vector has the wrong width."""
    try:
        vectors = np.asarray([vector for _, vector in items], dtype="float32")
    except (TypeError, ValueError) as exc:
        raise VectorStoreUnavailable(
            f"vectors for {path} are malformed: {exc}"
        ) from exc
    if vectors.ndim != 2 or vectors.shape[1] != dim:
        width = vectors.shape[1] if vectors.ndim == 2 else "ragged"
        raise VectorStoreUnavailable(
            f"embedding width {width} for {path}, expected {dim}"
        )
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)


def normalize_query(vector: list[float], dim: int) -> np.ndarray:
    """One normalised float32 row for a query; raises on a width mismatch."""
    query = np.asarray([vector], dtype="float32")
    if query.ndim != 2 or query.shape[1] != dim:
        width = query.shape[1] if query.ndim == 2 else "ragged"
        raise VectorStoreUnavailable(f"query width {width}, expected {dim}")
    return query / np.maximum(np.linalg.norm(query, axis=1, keepdims=True), 1e-12)
