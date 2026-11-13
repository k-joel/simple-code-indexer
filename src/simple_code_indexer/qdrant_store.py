"""Qdrant semantic index: stable point IDs, upsert, delete-by-path, search."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from simple_code_indexer.config import Settings
from simple_code_indexer.errors import QdrantUnavailable
from simple_code_indexer.models import Chunk, VectorHit

logger = logging.getLogger(__name__)

# Outcome of the most recent Qdrant operation; read by get_status.
LAST_OK: bool | None = None

# Fixed namespace so point IDs are stable across processes.
POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "simple-code-indexer")

_ensured_collections: set[tuple[str, str]] = set()
_ensure_lock = threading.Lock()


def point_id(path: str, chunk_index: int) -> uuid.UUID:
    return uuid.uuid5(POINT_NAMESPACE, f"{path}:{chunk_index}")


def _client(settings: Settings):
    """Lazy qdrant_client import (grpc is heavy); created per operation."""
    from qdrant_client import QdrantClient

    # check_compatibility=False: client/server minors differ in this env and
    # the version probe would run on every lazily-created client.
    return QdrantClient(url=settings.qdrant_url, check_compatibility=False)


def _validate_collection_config(client: Any, settings: Settings) -> None:
    """Reject a collection our single unnamed vector cannot be upserted into.

    Trusting an existing collection's name alone silently costs the workspace
    every vector when its size differs from EMBED_DIM (fail-soft indexing only
    logs), so fail loudly with the numbers instead.
    """
    vectors = client.get_collection(settings.qdrant_collection).config.params.vectors
    size = getattr(vectors, "size", None)
    if size is None:
        raise QdrantUnavailable(
            f"collection {settings.qdrant_collection} does not use a single "
            f"unnamed vector of size {settings.embed_dim}"
        )
    if int(size) != settings.embed_dim:
        raise QdrantUnavailable(
            f"collection {settings.qdrant_collection} has vector size {size}, "
            f"expected {settings.embed_dim}; delete it or align EMBED_DIM"
        )


def ensure_collection(settings: Settings) -> None:
    """Create the collection if missing (idempotent; cached per URL + name).

    Serialized, and tolerant of a lost create race: the service probe, the index
    writer, and a semantic search all hit a fresh workspace's collection at
    once, and an unguarded check-then-create answers HTTP 409 to the losers —
    which fail-soft indexing would turn into permanently missing vectors.
    """
    global LAST_OK
    from qdrant_client.models import Distance, VectorParams

    started = time.perf_counter()
    cache_key = (settings.qdrant_url, settings.qdrant_collection)
    if cache_key in _ensured_collections:
        logger.debug("qdrant collection %s already ensured", settings.qdrant_collection)
        return
    with _ensure_lock:
        if cache_key in _ensured_collections:
            return
        try:
            client = _client(settings)
            created = False
            if not client.collection_exists(settings.qdrant_collection):
                try:
                    client.create_collection(
                        settings.qdrant_collection,
                        vectors_config=VectorParams(
                            size=settings.embed_dim, distance=Distance.COSINE
                        ),
                    )
                    created = True
                except Exception as exc:
                    if not client.collection_exists(settings.qdrant_collection):
                        raise
                    logger.debug(
                        "collection %s was created concurrently (%s)",
                        settings.qdrant_collection,
                        exc,
                    )
            _validate_collection_config(client, settings)
            _ensured_collections.add(cache_key)
            LAST_OK = True
            logger.info(
                "qdrant collection %s %s (size=%d, %d ms)",
                settings.qdrant_collection,
                "created" if created else "ready",
                settings.embed_dim,
                int((time.perf_counter() - started) * 1000),
            )
        except QdrantUnavailable:
            LAST_OK = False
            raise
        except Exception as exc:
            LAST_OK = False
            raise QdrantUnavailable(f"cannot ensure collection: {exc}") from exc


def validate_collection(settings: Settings) -> None:
    """Validate an existing collection without creating it (reader role)."""
    global LAST_OK
    cache_key = (settings.qdrant_url, settings.qdrant_collection)
    if cache_key in _ensured_collections:
        return
    with _ensure_lock:
        if cache_key in _ensured_collections:
            return
        try:
            client = _client(settings)
            if not client.collection_exists(settings.qdrant_collection):
                raise QdrantUnavailable(
                    f"collection {settings.qdrant_collection} does not exist yet"
                )
            _validate_collection_config(client, settings)
            _ensured_collections.add(cache_key)
            LAST_OK = True
            logger.debug(
                "qdrant collection %s validated (size=%d)",
                settings.qdrant_collection,
                settings.embed_dim,
            )
        except QdrantUnavailable:
            LAST_OK = False
            raise
        except Exception as exc:
            LAST_OK = False
            raise QdrantUnavailable(f"cannot validate collection: {exc}") from exc


def upsert_chunks(
    settings: Settings, path: str, items: list[tuple[Chunk, list[float]]]
) -> list[str]:
    """Idempotent upsert of chunk vectors (stable IDs replace on re-index)."""
    global LAST_OK
    from qdrant_client.models import PointStruct

    if not items:
        return []
    started = time.perf_counter()
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
        logger.debug(
            "qdrant upsert %s: %d point(s) in %d ms",
            path,
            len(points),
            int((time.perf_counter() - started) * 1000),
        )
    except QdrantUnavailable:
        raise
    except Exception as exc:
        LAST_OK = False
        raise QdrantUnavailable(f"upsert failed for {path}: {exc}") from exc
    return [str(point.id) for point in points]


def delete_by_path(settings: Settings, path: str) -> None:
    """Drop every point of a deleted file."""
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
        logger.debug("qdrant delete %s", path)
    except QdrantUnavailable:
        raise
    except Exception as exc:
        LAST_OK = False
        raise QdrantUnavailable(f"delete failed for {path}: {exc}") from exc


def _query_points(
    settings: Settings, vector: list[float], limit: int
) -> list[VectorHit]:
    """Query an ensured/validated collection and map payloads to hits."""
    global LAST_OK
    started = time.perf_counter()
    response = _client(settings).query_points(
        settings.qdrant_collection,
        query=vector,
        limit=limit,
        with_payload=True,
    )
    hits: list[VectorHit] = []
    skipped = 0
    for point in response.points:
        payload = point.payload or {}
        if "path" not in payload or "chunk_index" not in payload:
            skipped += 1
            continue
        hits.append(
            VectorHit(
                path=str(payload["path"]),
                chunk_index=int(payload["chunk_index"]),
                score=float(point.score),
            )
        )
    LAST_OK = True
    logger.debug(
        "qdrant search: %d point(s), %d hit(s), %d malformed in %d ms",
        len(response.points),
        len(hits),
        skipped,
        int((time.perf_counter() - started) * 1000),
    )
    return hits


def search(settings: Settings, vector: list[float], limit: int) -> list[VectorHit]:
    """Nearest-chunk search; payload maps hits back to (path, chunk_index)."""
    global LAST_OK
    try:
        ensure_collection(settings)
        return _query_points(settings, vector, limit)
    except QdrantUnavailable:
        raise
    except Exception as exc:
        LAST_OK = False
        raise QdrantUnavailable(f"search failed: {exc}") from exc


def search_readonly(
    settings: Settings, vector: list[float], limit: int
) -> list[VectorHit]:
    """Reader-side search: validate the collection, never create it."""
    global LAST_OK
    try:
        validate_collection(settings)
        return _query_points(settings, vector, limit)
    except QdrantUnavailable:
        raise
    except Exception as exc:
        LAST_OK = False
        raise QdrantUnavailable(f"read-only search failed: {exc}") from exc
