"""FAISS semantic index: one persisted ID-mapped flat index per workspace.

Vectors are L2-normalised and searched with inner product, so the score is
cosine similarity in [-1, 1] — the same range Qdrant's COSINE distance uses.
SQLite owns the chunk metadata and the label -> (path, chunk_index) mapping;
the FAISS file owns the vectors.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from simple_code_indexer import db
from simple_code_indexer.config import Settings, faiss_index_path
from simple_code_indexer.errors import VectorStoreUnavailable
from simple_code_indexer.models import Chunk, VectorHit
from simple_code_indexer.vector_util import normalize_query, normalize_rows

logger = logging.getLogger(__name__)

# Outcome of the most recent store operation; read by get_status.
LAST_OK: bool | None = None

# The index and the label mapping are one unit: every mutation of either must
# hold this lock, or a flush can clear a dirty flag for a vector it never wrote.
_lock = threading.Lock()
_index: Any | None = None
_index_path: Path | None = None
_index_dim: int | None = None
_dirty = False
_reset_on_load = False

# Reader-side cache: never written, reloaded when the writer replaces the file.
_read_lock = threading.Lock()
_read_index: Any | None = None
_read_path: Path | None = None
_read_dim: int | None = None
_read_signature: tuple[int, int] | None = None


def _faiss() -> Any:
    """Lazy import: the Qdrant backend must never pay for (or fail on) faiss."""
    try:
        import faiss
    except Exception as exc:  # ImportError, but also a broken DLL on Windows
        raise VectorStoreUnavailable(f"faiss is not importable: {exc}") from exc
    return faiss


def describe(settings: Settings) -> str:
    """Human-readable identity of the store: the persisted index file."""
    return str(faiss_index_path(settings))


def identity(settings: Settings) -> tuple[str, str]:
    """The binding stored in `meta`: (file path, dimension slot).

    A non-empty `embed_fingerprint` (document prompt + chunker profile) is part
    of the dimension slot, so changing how chunks are produced or formatted
    re-embeds them. Query prompts do not affect stored vectors and leave the
    identity untouched.
    """
    dim = str(settings.embed_dim)
    if settings.embed_fingerprint:
        dim = f"{dim}:{settings.embed_fingerprint}"
    return (str(faiss_index_path(settings)), dim)


def _reset_state() -> None:
    """Drop process state (tests, and a switch to another workspace's file)."""
    global _index, _index_path, _index_dim, _dirty, _reset_on_load
    _index = None
    _index_path = None
    _index_dim = None
    _dirty = False
    _reset_on_load = False


def _reset_read_state() -> None:
    """Drop the reader cache (tests, and a missing/replaced file)."""
    global _read_index, _read_path, _read_dim, _read_signature
    _read_index = None
    _read_path = None
    _read_dim = None
    _read_signature = None


def _write_locked(path: Path, index: Any) -> None:
    """Atomic persist: a crash leaves either the old file or the new one."""
    faiss = _faiss()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    faiss.write_index(index, str(temporary))
    os.replace(temporary, path)


def _ensure_locked(settings: Settings) -> None:
    """Load or build the index for this settings object (lock already held)."""
    global _index, _index_path, _index_dim, _dirty, _reset_on_load

    path = faiss_index_path(settings)
    if _index is not None and _index_path == path and _index_dim == settings.embed_dim:
        logger.debug("FAISS index cached: %d vector(s)", int(_index.ntotal))
        return
    faiss = _faiss()
    index = faiss.IndexIDMap2(faiss.IndexFlatIP(settings.embed_dim))
    reset = not path.is_file()
    if not reset:
        try:
            loaded = faiss.read_index(str(path))
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("cannot read %s (%s); rebuilding it", path, exc)
            loaded = None
        if loaded is None:
            reset = True
        elif not isinstance(loaded, faiss.IndexIDMap2):
            logger.warning("%s is not an IndexIDMap2; rebuilding it", path)
            reset = True
        elif int(loaded.d) != settings.embed_dim:
            logger.warning(
                "%s has dimension %d, expected %d; rebuilding it",
                path,
                loaded.d,
                settings.embed_dim,
            )
            reset = True
        else:
            index = loaded
            logger.info(
                "loaded FAISS index %s: %d vector(s), dim %d",
                path,
                int(index.ntotal),
                settings.embed_dim,
            )
    if reset:
        logger.debug("new FAISS index for %s (dim %d)", path, settings.embed_dim)
    _index = index
    _index_path = path
    _index_dim = settings.embed_dim
    _reset_on_load = reset
    _dirty = reset


def ensure_ready(settings: Settings) -> None:
    global LAST_OK
    with _lock:
        try:
            _ensure_locked(settings)
            LAST_OK = True
        except VectorStoreUnavailable:
            LAST_OK = False
            raise


def reset(settings: Settings) -> None:
    """Replace the file with an empty index (identity changed under our feet)."""
    global LAST_OK, _index, _index_path, _index_dim, _dirty, _reset_on_load

    faiss = _faiss()
    index = faiss.IndexIDMap2(faiss.IndexFlatIP(settings.embed_dim))
    path = faiss_index_path(settings)
    with _lock:
        try:
            _write_locked(path, index)
        except Exception:
            # The stale file must not outlive the wiped label mapping: its ids
            # would collide with the labels allocated from the restarted
            # sequence and attach old vectors to new chunks.
            logger.warning("cannot persist the reset of %s", path, exc_info=True)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception("cannot remove the stale index %s", path)
            LAST_OK = False
        else:
            LAST_OK = True
        _index = index
        _index_path = path
        _index_dim = settings.embed_dim
        _reset_on_load = False
        _dirty = False


def upsert_chunks(
    settings: Settings, path: str, items: list[tuple[Chunk, list[float]]]
) -> list[str]:
    """Replace the vectors of one file; returns the written labels as strings."""
    global LAST_OK, _dirty

    if not items:
        return []
    started = time.perf_counter()
    try:
        vectors = normalize_rows(items, settings.embed_dim, path=path)
    except VectorStoreUnavailable:
        LAST_OK = False
        raise
    chunk_indexes = [chunk.chunk_index for chunk, _ in items]

    with _lock:
        _ensure_locked(settings)
        try:
            with db.connect(settings.index_db_path) as conn, conn:
                db.ensure_schema(conn)
                labels = [
                    db.allocate_vector_label(conn, path, chunk_index)
                    for chunk_index in chunk_indexes
                ]
                rows = db.vector_label_rows(conn, path)
                keep = set(chunk_indexes)
                stale = [
                    chunk_index for _, chunk_index in rows if chunk_index not in keep
                ]
                db.delete_vector_labels(conn, path, stale)
                db.mark_vectors_dirty(conn, labels)
            assert _index is not None
            # add_with_ids appends, so an existing id must be removed first or
            # a re-index would leave two vectors for the same chunk.
            existing = [label for label, _ in rows]
            if existing:
                _index.remove_ids(np.asarray(existing, dtype="int64"))
            _index.add_with_ids(vectors, np.asarray(labels, dtype="int64"))
            _dirty = True
            logger.debug(
                "faiss upsert %s: %d vector(s), %d replaced, %d stale, %d ms",
                path,
                len(labels),
                len(existing),
                len(stale),
                int((time.perf_counter() - started) * 1000),
            )
        except VectorStoreUnavailable:
            LAST_OK = False
            raise
        except Exception as exc:
            LAST_OK = False
            raise VectorStoreUnavailable(f"upsert failed for {path}: {exc}") from exc
    LAST_OK = True
    return [str(label) for label in labels]


def delete_by_path(settings: Settings, path: str) -> None:
    """Drop every vector and mapping of one path."""
    global LAST_OK, _dirty

    with _lock:
        _ensure_locked(settings)
        try:
            with db.connect(settings.index_db_path) as conn, conn:
                db.ensure_schema(conn)
                rows = db.vector_label_rows(conn, path)
                labels = [label for label, _ in rows]
                if labels:
                    assert _index is not None
                    _index.remove_ids(np.asarray(labels, dtype="int64"))
                db.delete_vector_labels(conn, path, [index for _, index in rows])
            _dirty = _dirty or bool(labels)
            logger.debug("faiss delete %s: %d label(s)", path, len(labels))
        except VectorStoreUnavailable:
            LAST_OK = False
            raise
        except Exception as exc:
            LAST_OK = False
            raise VectorStoreUnavailable(f"delete failed for {path}: {exc}") from exc
    LAST_OK = True


def _hits_from_index(
    settings: Settings, index: Any, query: Any, limit: int
) -> tuple[list[VectorHit], int, int]:
    """Search one loaded index and map labels through the read-only SQLite view."""
    ntotal = int(index.ntotal)
    k = 0
    pairs: list[tuple[int, float]] = []
    hits: list[VectorHit] = []
    if ntotal:
        k = max(1, min(int(limit), ntotal))
        scores, labels = index.search(query, k)
        pairs = [
            (int(label), float(score))
            for label, score in zip(labels[0], scores[0], strict=True)
            if int(label) != -1
        ]
        if pairs:
            with db.try_connect_readonly(settings.index_db_path) as conn:
                mapping = (
                    db.vector_paths_for_labels(conn, [label for label, _ in pairs])
                    if conn is not None
                    else {}
                )
            for label, score in pairs:
                mapped = mapping.get(label)
                if mapped is not None:
                    hits.append(
                        VectorHit(
                            path=mapped[0],
                            chunk_index=mapped[1],
                            score=score,
                        )
                    )
    return hits, ntotal, k


def _query_vector(settings: Settings, vector: list[float]) -> Any:
    return normalize_query(vector, settings.embed_dim)


def search(settings: Settings, vector: list[float], limit: int) -> list[VectorHit]:
    """Nearest chunks by cosine similarity; orphan ids are dropped."""
    global LAST_OK

    try:
        query = _query_vector(settings, vector)
    except VectorStoreUnavailable:
        LAST_OK = False
        raise

    with _lock:
        _ensure_locked(settings)
        try:
            assert _index is not None
            started = time.perf_counter()
            hits, ntotal, k = _hits_from_index(settings, _index, query, limit)
            logger.debug(
                "faiss search: ntotal=%d k=%d hits=%d dropped=%d in %d ms",
                ntotal,
                k,
                len(hits),
                int(k) - len(hits),
                int((time.perf_counter() - started) * 1000),
            )
        except VectorStoreUnavailable:
            LAST_OK = False
            raise
        except Exception as exc:
            LAST_OK = False
            raise VectorStoreUnavailable(f"search failed: {exc}") from exc
    LAST_OK = True
    return hits


def _ensure_read_locked(settings: Settings) -> Any:
    """Load the published file without ever creating or mutating it."""
    global _read_index, _read_path, _read_dim, _read_signature

    path = faiss_index_path(settings)
    try:
        stat = path.stat()
    except OSError as exc:
        _reset_read_state()
        raise VectorStoreUnavailable(
            f"semantic index is not ready: {path} is missing"
        ) from exc
    signature = (stat.st_mtime_ns, stat.st_size)
    if (
        _read_index is not None
        and _read_path == path
        and _read_dim == settings.embed_dim
        and _read_signature == signature
    ):
        return _read_index
    faiss = _faiss()
    try:
        loaded = faiss.read_index(str(path))
    except (OSError, RuntimeError, ValueError) as exc:
        _reset_read_state()
        raise VectorStoreUnavailable(
            f"cannot read the semantic index {path}: {exc}"
        ) from exc
    if not isinstance(loaded, faiss.IndexIDMap2):
        _reset_read_state()
        raise VectorStoreUnavailable(f"{path} is not a FAISS IndexIDMap2")
    if int(loaded.d) != settings.embed_dim:
        _reset_read_state()
        raise VectorStoreUnavailable(
            f"{path} has dimension {loaded.d}, expected {settings.embed_dim}"
        )
    _read_index = loaded
    _read_path = path
    _read_dim = settings.embed_dim
    _read_signature = signature
    logger.info(
        "loaded FAISS index for reading %s: %d vector(s), dim %d",
        path,
        int(loaded.ntotal),
        settings.embed_dim,
    )
    return loaded


def search_readonly(
    settings: Settings, vector: list[float], limit: int
) -> list[VectorHit]:
    """Query the published FAISS file; reload it when the writer replaced it.

    This path is for reader processes: it never calls `_write_locked`, `flush`,
    `reset`, `reconcile`, `upsert_chunks`, or `delete_by_path`.
    """
    global LAST_OK

    try:
        query = _query_vector(settings, vector)
    except VectorStoreUnavailable:
        LAST_OK = False
        raise

    with _read_lock:
        try:
            index = _ensure_read_locked(settings)
            started = time.perf_counter()
            hits, ntotal, k = _hits_from_index(settings, index, query, limit)
            logger.debug(
                "faiss read-only search: ntotal=%d k=%d hits=%d dropped=%d in %d ms",
                ntotal,
                k,
                len(hits),
                int(k) - len(hits),
                int((time.perf_counter() - started) * 1000),
            )
        except VectorStoreUnavailable:
            LAST_OK = False
            raise
        except Exception as exc:
            LAST_OK = False
            raise VectorStoreUnavailable(f"read-only search failed: {exc}") from exc
    LAST_OK = True
    return hits


def vector_index_age_s(settings: Settings) -> float | None:
    """Seconds since the FAISS file was last written, or None when absent."""
    try:
        stat = faiss_index_path(settings).stat()
    except OSError:
        return None
    return max(0.0, time.time() - stat.st_mtime)


def reconcile(settings: Settings) -> int:
    """Flag chunks whose vector may have been lost with the last unflushed writes."""
    global _reset_on_load

    with _lock:
        _ensure_locked(settings)
        try:
            with db.connect(settings.index_db_path) as conn, conn:
                db.ensure_schema(conn)
                if _reset_on_load:
                    db.mark_all_vectors_dirty(conn)
                    _reset_on_load = False
                return db.flag_chunks_for_reembed(conn)
        except sqlite3.Error as exc:
            raise VectorStoreUnavailable(f"reconcile failed: {exc}") from exc


def flush(settings: Settings) -> None:
    """Persist the in-memory index, then clear the dirty labels.

    Writing first and clearing second means a crash in between only causes a
    harmless re-embed. Failures are logged: the dirty flags stay set, so the
    next start retries instead of silently losing vectors.
    """
    global LAST_OK, _dirty

    with _lock:
        if _index is None or not _dirty:
            return
        path = _index_path or faiss_index_path(settings)
        started = time.perf_counter()
        try:
            _write_locked(path, _index)
        except Exception:
            LAST_OK = False
            logger.warning("cannot persist %s", path, exc_info=True)
            return
        _dirty = False
        try:
            with db.connect(settings.index_db_path) as conn, conn:
                db.ensure_schema(conn)
                db.clear_vector_dirty(conn)
        except sqlite3.Error:
            LAST_OK = False
            logger.warning("cannot clear the dirty flags in %s", path, exc_info=True)
            return
        logger.info(
            "persisted %d vector(s) to %s in %d ms",
            int(_index.ntotal),
            path,
            int((time.perf_counter() - started) * 1000),
        )
    LAST_OK = True


def last_ok(settings: Settings) -> bool:
    return LAST_OK is True
