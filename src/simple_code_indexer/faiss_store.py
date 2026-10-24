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
from pathlib import Path
from typing import Any

import numpy as np

from simple_code_indexer import db
from simple_code_indexer.config import Settings, faiss_index_path
from simple_code_indexer.errors import VectorStoreUnavailable
from simple_code_indexer.models import Chunk, VectorHit

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


def _faiss() -> Any:
    """Lazy import: the Qdrant backend must never pay for (or fail on) faiss."""
    try:
        import faiss
    except Exception as exc:  # ImportError, but also a broken DLL on Windows
        raise VectorStoreUnavailable(f"faiss is not importable: {exc}") from exc
    return faiss


def _reset_state() -> None:
    """Drop process state (tests, and a switch to another workspace's file)."""
    global _index, _index_path, _index_dim, _dirty, _reset_on_load
    _index = None
    _index_path = None
    _index_dim = None
    _dirty = False
    _reset_on_load = False


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
    try:
        vectors = np.asarray([vector for _, vector in items], dtype="float32")
    except (TypeError, ValueError) as exc:
        LAST_OK = False
        raise VectorStoreUnavailable(
            f"vectors for {path} are malformed: {exc}"
        ) from exc
    if vectors.ndim != 2 or vectors.shape[1] != settings.embed_dim:
        LAST_OK = False
        width = vectors.shape[1] if vectors.ndim == 2 else "ragged"
        raise VectorStoreUnavailable(
            f"embedding width {width} for {path}, expected {settings.embed_dim}"
        )
    vectors = vectors / np.maximum(
        np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12
    )
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
        except VectorStoreUnavailable:
            LAST_OK = False
            raise
        except Exception as exc:
            LAST_OK = False
            raise VectorStoreUnavailable(f"delete failed for {path}: {exc}") from exc
    LAST_OK = True


def search(settings: Settings, vector: list[float], limit: int) -> list[VectorHit]:
    """Nearest chunks by cosine similarity; orphan ids are dropped."""
    global LAST_OK

    query = np.asarray([vector], dtype="float32")
    if query.ndim != 2 or query.shape[1] != settings.embed_dim:
        LAST_OK = False
        width = query.shape[1] if query.ndim == 2 else "ragged"
        raise VectorStoreUnavailable(
            f"query width {width}, expected {settings.embed_dim}"
        )
    query = query / np.maximum(np.linalg.norm(query, axis=1, keepdims=True), 1e-12)

    with _lock:
        _ensure_locked(settings)
        try:
            assert _index is not None
            if _index.ntotal == 0:
                hits: list[VectorHit] = []
            else:
                k = max(1, min(int(limit), int(_index.ntotal)))
                scores, labels = _index.search(query, k)
                pairs = [
                    (int(label), float(score))
                    for label, score in zip(labels[0], scores[0], strict=True)
                    if int(label) != -1
                ]
                hits = []
                if pairs:
                    with db.connect(settings.index_db_path, readonly=True) as conn:
                        mapping = db.vector_paths_for_labels(
                            conn, [label for label, _ in pairs]
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
        except VectorStoreUnavailable:
            LAST_OK = False
            raise
        except Exception as exc:
            LAST_OK = False
            raise VectorStoreUnavailable(f"search failed: {exc}") from exc
    LAST_OK = True
    return hits


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
    LAST_OK = True


def last_ok(settings: Settings) -> bool:
    return LAST_OK is True
