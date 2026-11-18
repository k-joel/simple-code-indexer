"""Vector-store router: one registry, one contract, no per-backend branches.

Every backend module implements the same module-level function set
(`STORE_CONTRACT`), so adding a fourth backend is one module plus one registry
entry. Imports stay lazy: a sqlite-vec workspace never imports faiss or
qdrant-client. `tests/test_vector_store.py` asserts every registered module
exposes the whole contract, which is what keeps the registry honest.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from simple_code_indexer.config import VECTOR_STORES, Settings
from simple_code_indexer.errors import ConfigError
from simple_code_indexer.models import Chunk, VectorHit

# Functions every backend module must expose with the shared signature
# (settings first). Read by the contract test, not at runtime.
STORE_CONTRACT = (
    "describe",
    "identity",
    "ensure_ready",
    "reset",
    "upsert_chunks",
    "delete_by_path",
    "search",
    "search_readonly",
    "reconcile",
    "flush",
    "last_ok",
    "vector_index_age_s",
)


def _sqlite_vec_store() -> Any:
    from simple_code_indexer import sqlite_vec_store

    return sqlite_vec_store


def _faiss_store() -> Any:
    from simple_code_indexer import faiss_store

    return faiss_store


def _qdrant_store() -> Any:
    from simple_code_indexer import qdrant_store

    return qdrant_store


_STORES: dict[str, Callable[[], Any]] = {
    "sqlite-vec": _sqlite_vec_store,
    "faiss": _faiss_store,
    "qdrant": _qdrant_store,
}


def backend(settings: Settings) -> str:
    value = settings.vector_store.strip().lower()
    if value not in VECTOR_STORES:
        raise ConfigError(
            f"vector_store must be one of {sorted(VECTOR_STORES)}, got "
            f"{settings.vector_store!r}"
        )
    return value


def _store(settings: Settings) -> Any:
    return _STORES[backend(settings)]()


def describe(settings: Settings) -> str:
    """Human-readable identity of the store: file path, table or collection."""
    return _store(settings).describe(settings)


def identity(settings: Settings) -> tuple[str, str]:
    """The binding stored in `meta`, shaped by the active backend."""
    return _store(settings).identity(settings)


def ensure_ready(settings: Settings) -> None:
    _store(settings).ensure_ready(settings)


def reset(settings: Settings) -> None:
    """Invalidate the stored vectors after an identity change."""
    if backend(settings) != "sqlite-vec":
        # Switching away leaves a dead vec0 table inside index.db; dropping it
        # is best-effort and must never block the new backend's reset.
        from simple_code_indexer import sqlite_vec_store

        sqlite_vec_store.discard(settings)
    _store(settings).reset(settings)


def upsert_chunks(
    settings: Settings, path: str, items: list[tuple[Chunk, list[float]]]
) -> list[str]:
    return _store(settings).upsert_chunks(settings, path, items)


def delete_by_path(settings: Settings, path: str) -> None:
    _store(settings).delete_by_path(settings, path)


def search(settings: Settings, vector: list[float], limit: int) -> list[VectorHit]:
    return _store(settings).search(settings, vector, limit)


def search_readonly(
    settings: Settings, vector: list[float], limit: int
) -> list[VectorHit]:
    """Query without creating or mutating store state (MCP reader role)."""
    return _store(settings).search_readonly(settings, vector, limit)


def reconcile(settings: Settings) -> int:
    return _store(settings).reconcile(settings)


def flush(settings: Settings) -> None:
    _store(settings).flush(settings)


def last_ok(settings: Settings) -> bool:
    return _store(settings).last_ok(settings)


def vector_index_age_s(settings: Settings) -> float | None:
    """Seconds since the store last accepted a vector, or None when unready."""
    return _store(settings).vector_index_age_s(settings)
