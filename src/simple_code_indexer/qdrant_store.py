"""Qdrant semantic index: stable point IDs, upsert, delete-by-path, search."""

from __future__ import annotations

import logging
import uuid
from typing import NamedTuple

from simple_code_indexer.config import Settings
from simple_code_indexer.errors import QdrantUnavailable
from simple_code_indexer.models import Chunk

logger = logging.getLogger(__name__)

# Outcome of the most recent Qdrant operation; read by get_status.
LAST_OK: bool | None = None

# Fixed namespace so point IDs are stable across processes (TDD §6.2).
POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "simple-code-indexer")

_ensured_urls: set[str] = set()


def point_id(path: str, chunk_index: int) -> uuid.UUID:
    return uuid.uuid5(POINT_NAMESPACE, f"{path}:{chunk_index}")


class VectorHit(NamedTuple):
    path: str
    chunk_index: int
    score: float


def _client(settings: Settings):
    """Lazy qdrant_client import (grpc is heavy); created per operation."""
    from qdrant_client import QdrantClient

    # check_compatibility=False: client/server minors differ in this env and
    # the version probe would run on every lazily-created client.
    return QdrantClient(url=settings.qdrant_url, check_compatibility=False)


def ensure_collection(settings: Settings) -> None:
    """Create the collection if missing (idempotent; cached per URL)."""
    global LAST_OK
    from qdrant_client.models import Distance, VectorParams

    if settings.qdrant_url in _ensured_urls:
        return
    try:
        client = _client(settings)
        if not client.collection_exists(settings.qdrant_collection):
            client.create_collection(
                settings.qdrant_collection,
                vectors_config=VectorParams(
                    size=settings.embed_dim, distance=Distance.COSINE
                ),
            )
        _ensured_urls.add(settings.qdrant_url)
        LAST_OK = True
    except Exception as exc:
        LAST_OK = False
        raise QdrantUnavailable(f"cannot ensure collection: {exc}") from exc


def upsert_chunks(
    settings: Settings, path: str, items: list[tuple[Chunk, list[float]]]
) -> None:
    """Idempotent upsert of chunk vectors (stable IDs replace on re-index)."""
    global LAST_OK
    from qdrant_client.models import PointStruct

    if not items:
        return
    try:
        ensure_collection(settings)
        points = [
            PointStruct(
                id=str(point_id(path, chunk.chunk_index)),
                vector=vector,
                payload={"path": path, "chunk_index": chunk.chunk_index},
            )
            for chunk, vector in items
        ]
        _client(settings).upsert(settings.qdrant_collection, points=points, wait=True)
        LAST_OK = True
    except QdrantUnavailable:
        raise
    except Exception as exc:
        LAST_OK = False
        raise QdrantUnavailable(f"upsert failed for {path}: {exc}") from exc


def delete_by_path(settings: Settings, path: str) -> None:
    """Drop every point of a deleted file (TDD §6.2)."""
    global LAST_OK
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    try:
        ensure_collection(settings)
        _client(settings).delete(
            settings.qdrant_collection,
            points_selector=Filter(
                must=[FieldCondition(key="path", match=MatchValue(value=path))]
            ),
            wait=True,
        )
        LAST_OK = True
    except QdrantUnavailable:
        raise
    except Exception as exc:
        LAST_OK = False
        raise QdrantUnavailable(f"delete failed for {path}: {exc}") from exc


def search(settings: Settings, vector: list[float], limit: int) -> list[VectorHit]:
    """Nearest-chunk search; payload maps hits back to (path, chunk_index)."""
    global LAST_OK
    try:
        ensure_collection(settings)
        response = _client(settings).query_points(
            settings.qdrant_collection,
            query=vector,
            limit=limit,
            with_payload=True,
        )
        LAST_OK = True
    except QdrantUnavailable:
        raise
    except Exception as exc:
        LAST_OK = False
        raise QdrantUnavailable(f"search failed: {exc}") from exc
    hits: list[VectorHit] = []
    for point in response.points:
        payload = point.payload or {}
        if "path" not in payload or "chunk_index" not in payload:
            continue
        hits.append(
            VectorHit(
                path=str(payload["path"]),
                chunk_index=int(payload["chunk_index"]),
                score=float(point.score),
            )
        )
    return hits
