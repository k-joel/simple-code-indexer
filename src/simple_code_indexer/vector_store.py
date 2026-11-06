"""Vector-store router: FAISS by default, Qdrant when configured.

`faiss_store` is imported lazily so the Qdrant path never imports faiss, and
`qdrant_store` keeps its own lazy qdrant-client import.
"""

from __future__ import annotations

from simple_code_indexer import qdrant_store
from simple_code_indexer.config import VECTOR_STORES, Settings, faiss_index_path
from simple_code_indexer.errors import ConfigError
from simple_code_indexer.models import Chunk, VectorHit


def _faiss_store():
    from simple_code_indexer import faiss_store

    return faiss_store


def backend(settings: Settings) -> str:
    value = settings.vector_store.strip().lower()
    if value not in VECTOR_STORES:
        raise ConfigError(
            f"vector_store must be one of {sorted(VECTOR_STORES)}, got "
            f"{settings.vector_store!r}"
        )
    return value


def describe(settings: Settings) -> str:
    """Human-readable identity of the store: FAISS file path or collection."""
    if backend(settings) == "qdrant":
        return settings.qdrant_collection
    return str(faiss_index_path(settings))


def identity(settings: Settings) -> tuple[str, str]:
    """The binding stored in `meta`: (url, collection) or (path, dim).

    A non-empty `embed_fingerprint` (a document prompt) is part of the FAISS
    dimension slot, so changing how chunks are formatted re-embeds them. Query
    prompts do not affect stored vectors and leave the identity untouched.
    """
    if backend(settings) == "qdrant":
        return (settings.qdrant_url, settings.qdrant_collection)
    dim = str(settings.embed_dim)
    if settings.embed_fingerprint:
        dim = f"{dim}:{settings.embed_fingerprint}"
    return (str(faiss_index_path(settings)), dim)


def ensure_ready(settings: Settings) -> None:
    if backend(settings) == "qdrant":
        qdrant_store.ensure_collection(settings)
    else:
        _faiss_store().ensure_ready(settings)


def reset(settings: Settings) -> None:
    """Invalidate the stored vectors after an identity change (FAISS only)."""
    if backend(settings) == "qdrant":
        return
    _faiss_store().reset(settings)


def upsert_chunks(
    settings: Settings, path: str, items: list[tuple[Chunk, list[float]]]
) -> list[str]:
    if backend(settings) == "qdrant":
        return qdrant_store.upsert_chunks(settings, path, items)
    return _faiss_store().upsert_chunks(settings, path, items)


def delete_by_path(settings: Settings, path: str) -> None:
    if backend(settings) == "qdrant":
        qdrant_store.delete_by_path(settings, path)
    else:
        _faiss_store().delete_by_path(settings, path)


def search(settings: Settings, vector: list[float], limit: int) -> list[VectorHit]:
    if backend(settings) == "qdrant":
        return qdrant_store.search(settings, vector, limit)
    return _faiss_store().search(settings, vector, limit)


def reconcile(settings: Settings) -> int:
    if backend(settings) == "qdrant":
        return 0
    return _faiss_store().reconcile(settings)


def flush(settings: Settings) -> None:
    if backend(settings) == "qdrant":
        return
    _faiss_store().flush(settings)


def last_ok(settings: Settings) -> bool:
    if backend(settings) == "qdrant":
        return qdrant_store.LAST_OK is True
    return _faiss_store().last_ok(settings)
