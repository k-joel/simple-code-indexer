"""sqlite-vec semantic index: vectors inside the lexical `index.db`.

The `vec_chunks` virtual table shares the database (and therefore the writer
transaction) with `chunks` and `vector_labels`, so a file update and its vectors
commit atomically. `vector_labels` keeps its role as the stable
label -> (path, chunk_index) map, which is what lets a deleted or re-indexed path
drop its vectors without scanning the index.

Vectors are L2-normalised and the table uses `distance_metric=cosine`, so the
reported score is cosine similarity in [-1, 1] — identical to the FAISS and
Qdrant backends. sqlite-vec returns cosine *distance*, hence `1 - distance`.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from simple_code_indexer import db
from simple_code_indexer.config import Settings
from simple_code_indexer.errors import VectorStoreUnavailable
from simple_code_indexer.models import Chunk, VectorHit
from simple_code_indexer.vector_util import normalize_query, normalize_rows

logger = logging.getLogger(__name__)

# Outcome of the most recent store operation; read by get_status.
LAST_OK: bool | None = None

TABLE = "vec_chunks"

# vec0 fixes the dimension and the storage chunk size in the DDL; a change needs
# the table rebuilt (see _ensure_table).
_DIM_RE = re.compile(r"float\[\s*(\d+)\s*\]", re.IGNORECASE)
_CHUNK_SIZE_RE = re.compile(r"chunk_size\s*=\s*(\d+)", re.IGNORECASE)

_KNN_SQL = f"""
SELECT vl.path AS path, vl.chunk_index AS chunk_index, 1.0 - v.distance AS score
FROM {TABLE} v
JOIN vector_labels vl ON vl.label = v.rowid
WHERE v.embedding MATCH vec_f32(?) AND k = ?
ORDER BY v.distance
"""

# Table discovery and DDL are read-modify-write; one lock keeps two threads from
# both deciding to rebuild it. Vector writes need no lock: SQLite serialises
# writers and there is no in-process index state (unlike FAISS).
_ensure_lock = threading.Lock()

# Set when the table had to be created while embeddings already claimed to be
# ok; `reconcile` consumes it and flags them for re-embedding.
_created_on_load = False

# Databases whose schema the writer already ensured in this process. Hot paths
# (a semantic query per tool call) must not re-run the whole schema script.
_schema_ready: set[Path] = set()


def _ensure_schema(conn: sqlite3.Connection, settings: Settings) -> None:
    """`db.ensure_schema` once per database per process; the writer is the only caller."""
    key = settings.index_db_path
    if key in _schema_ready:
        return
    db.ensure_schema(conn)
    _schema_ready.add(key)


def _sqlite_vec() -> Any:
    """Lazy import: the FAISS and Qdrant paths must never pay for the wheel."""
    try:
        import sqlite_vec
    except Exception as exc:  # ImportError, but also a broken wheel on Windows
        raise VectorStoreUnavailable(f"sqlite-vec is not importable: {exc}") from exc
    return sqlite_vec


def _load_extension(conn: sqlite3.Connection, settings: Settings) -> None:
    """Load vec0 on this connection and apply the per-connection tuning PRAGMAs."""
    enable = getattr(conn, "enable_load_extension", None)
    if enable is None:
        raise VectorStoreUnavailable(
            "this Python build cannot load SQLite extensions; "
            "use a uv-managed interpreter or select vector_store: faiss"
        )
    try:
        enable(True)
        _sqlite_vec().load(conn)
    finally:
        try:
            enable(False)
        except sqlite3.Error:  # pragma: no cover - defensive on odd builds
            logger.debug("cannot disable extension loading", exc_info=True)
    conn.execute(f"PRAGMA mmap_size={int(settings.sqlite_vec_mmap_size)}")
    conn.execute(f"PRAGMA cache_size={int(settings.sqlite_vec_cache_size)}")


@contextmanager
def _connect(
    settings: Settings, *, readonly: bool = False
) -> Iterator[sqlite3.Connection]:
    if readonly:
        with db.try_connect_readonly(settings.index_db_path) as conn:
            if conn is None:
                raise VectorStoreUnavailable(
                    f"semantic index is not ready: {settings.index_db_path} is missing"
                )
            _load_extension(conn, settings)
            yield conn
        return
    with db.connect(settings.index_db_path) as conn:
        _load_extension(conn, settings)
        yield conn


def available() -> tuple[bool, str]:
    """Whether this interpreter can load vec0 at all; (ok, detail) for the wizard."""
    try:
        vec = _sqlite_vec()
    except VectorStoreUnavailable as exc:
        return (False, str(exc))
    try:
        conn = sqlite3.connect(":memory:")
        try:
            enable = getattr(conn, "enable_load_extension", None)
            if enable is None:
                return (False, "this Python build cannot load SQLite extensions")
            enable(True)
            vec.load(conn)
            row = conn.execute("SELECT vec_version()").fetchone()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - the wizard reports, never crashes
        return (False, f"cannot load the sqlite-vec extension: {exc}")
    return (True, f"sqlite-vec {row[0] if row else '?'}")


def _table_sql(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
    ).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def _table_spec(sql: str) -> tuple[int | None, int | None]:
    dim = _DIM_RE.search(sql)
    chunk_size = _CHUNK_SIZE_RE.search(sql)
    return (
        int(dim.group(1)) if dim else None,
        int(chunk_size.group(1)) if chunk_size else None,
    )


def _create_table(conn: sqlite3.Connection, settings: Settings) -> None:
    dim = int(settings.embed_dim)
    if dim > 8192:
        raise VectorStoreUnavailable(
            f"sqlite-vec supports at most 8192 dimensions, EMBED_DIM is {dim}; "
            f"select vector_store: faiss"
        )
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {TABLE} USING vec0("
        f"embedding float[{dim}] distance_metric=cosine, "
        f"chunk_size={int(settings.sqlite_vec_chunk_size)})"
    )


def _embedded_chunks(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM embedding_state WHERE status = 'ok'"
    ).fetchone()
    return int(row[0])


def _ensure_table(conn: sqlite3.Connection, settings: Settings) -> None:
    """Create `vec_chunks`, or rebuild it when its fixed layout no longer matches."""
    global _created_on_load

    with _ensure_lock:
        sql = _table_sql(conn)
        if sql is None:
            embedded = _embedded_chunks(conn)
            _create_table(conn, settings)
            if embedded:
                logger.warning(
                    "sqlite-vec table was missing; flagging %d embedded chunk(s) "
                    "for re-embedding",
                    embedded,
                )
                _created_on_load = True
            return
        dim, chunk_size = _table_spec(sql)
        expected = (int(settings.embed_dim), int(settings.sqlite_vec_chunk_size))
        if (dim, chunk_size) == expected:
            return
        logger.warning(
            "vec_chunks was built for float[%s] chunk_size=%s, expected "
            "float[%d] chunk_size=%d; rebuilding it",
            dim,
            chunk_size,
            expected[0],
            expected[1],
        )
        conn.execute(f"DROP TABLE {TABLE}")
        _create_table(conn, settings)
        changed = db.invalidate_embeddings(conn)
        if changed:
            logger.warning("%d chunk(s) will be re-embedded", changed)


def _serialize(vector: np.ndarray) -> bytes:
    """Little-endian float32 blob, the layout vec0 stores and matches."""
    return np.asarray(vector, dtype="<f4").tobytes()


def _score(value: float) -> float:
    """Clamp float noise so a cosine similarity stays inside [-1, 1]."""
    return max(-1.0, min(1.0, float(value)))


def _knn(
    conn: sqlite3.Connection, query: np.ndarray, limit: int, *, path: str = "-"
) -> list[VectorHit]:
    started = time.perf_counter()
    k = max(1, int(limit))
    rows = conn.execute(_KNN_SQL, (_serialize(query[0]), k)).fetchall()
    hits = [
        VectorHit(
            path=str(row["path"]),
            chunk_index=int(row["chunk_index"]),
            score=_score(row["score"]),
        )
        for row in rows
    ]
    logger.debug(
        "sqlite-vec knn (%s): k=%d hits=%d in %d ms",
        path,
        k,
        len(hits),
        int((time.perf_counter() - started) * 1000),
    )
    return hits


def describe(settings: Settings) -> str:
    """Human-readable identity: the database that owns the vectors, plus the table."""
    return f"{settings.index_db_path}#{TABLE}"


def identity(settings: Settings) -> tuple[str, str]:
    """The binding stored in `meta`: ("sqlite-vec", dimension slot).

    The vectors travel with `index.db`, so the workspace path is deliberately not
    part of the binding — renaming or moving a project must not re-embed it. A
    non-empty `embed_fingerprint` still invalidates, because it changes the
    stored vectors themselves.
    """
    dim = str(settings.embed_dim)
    if settings.embed_fingerprint:
        dim = f"{dim}:{settings.embed_fingerprint}"
    return ("sqlite-vec", dim)


def ensure_ready(settings: Settings) -> None:
    """Create the vector table in the writer's database (idempotent)."""
    global LAST_OK

    try:
        with _connect(settings) as conn, conn:
            _ensure_schema(conn, settings)
            _ensure_table(conn, settings)
    except VectorStoreUnavailable:
        LAST_OK = False
        raise
    except Exception as exc:
        LAST_OK = False
        raise VectorStoreUnavailable(f"cannot prepare {TABLE}: {exc}") from exc
    LAST_OK = True


def reset(settings: Settings) -> None:
    """Replace the vector table with an empty one (identity changed under us)."""
    global LAST_OK, _created_on_load

    try:
        with _connect(settings) as conn, conn:
            _ensure_schema(conn, settings)
            conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
            _create_table(conn, settings)
            conn.execute("DELETE FROM vector_labels")
    except VectorStoreUnavailable:
        LAST_OK = False
        raise
    except Exception as exc:
        LAST_OK = False
        raise VectorStoreUnavailable(f"cannot reset {TABLE}: {exc}") from exc
    _created_on_load = False
    LAST_OK = True


def discard(settings: Settings) -> None:
    """Drop a leftover vector table; used when another backend becomes active."""
    if not settings.index_db_path.is_file():
        return
    try:
        with _connect(settings) as conn, conn:
            conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
    except (OSError, sqlite3.Error, VectorStoreUnavailable):
        logger.debug("cannot drop a stale %s table", TABLE, exc_info=True)


def upsert_chunks(
    settings: Settings, path: str, items: list[tuple[Chunk, list[float]]]
) -> list[str]:
    """Replace one file's vectors and labels in a single transaction."""
    global LAST_OK

    if not items:
        return []
    started = time.perf_counter()
    try:
        vectors = normalize_rows(items, settings.embed_dim, path=path)
    except VectorStoreUnavailable:
        LAST_OK = False
        raise
    blobs = [_serialize(row) for row in vectors]
    chunk_indexes = [chunk.chunk_index for chunk, _ in items]

    try:
        with _connect(settings) as conn, conn:
            _ensure_schema(conn, settings)
            _ensure_table(conn, settings)
            labels = [
                db.allocate_vector_label(conn, path, chunk_index)
                for chunk_index in chunk_indexes
            ]
            rows = db.vector_label_rows(conn, path)
            keep = set(chunk_indexes)
            stale = [(label, ci) for label, ci in rows if ci not in keep]
            for label, _ in stale:
                conn.execute(f"DELETE FROM {TABLE} WHERE rowid = ?", (int(label),))
            db.delete_vector_labels(conn, path, [ci for _, ci in stale])
            for label, blob in zip(labels, blobs, strict=True):
                # 0.1.9 has no INSERT OR REPLACE on vec0; update, insert if new.
                cursor = conn.execute(
                    f"UPDATE {TABLE} SET embedding = ? WHERE rowid = ?",
                    (blob, int(label)),
                )
                if cursor.rowcount == 0:
                    conn.execute(
                        f"INSERT INTO {TABLE}(rowid, embedding) VALUES (?, ?)",
                        (int(label), blob),
                    )
    except VectorStoreUnavailable:
        LAST_OK = False
        raise
    except Exception as exc:
        LAST_OK = False
        raise VectorStoreUnavailable(f"upsert failed for {path}: {exc}") from exc

    LAST_OK = True
    logger.debug(
        "sqlite-vec upsert %s: %d vector(s), %d stale, %d ms",
        path,
        len(labels),
        len(stale),
        int((time.perf_counter() - started) * 1000),
    )
    return [str(label) for label in labels]


def delete_by_path(settings: Settings, path: str) -> None:
    """Drop every vector and label of one path."""
    global LAST_OK

    try:
        with _connect(settings) as conn, conn:
            _ensure_schema(conn, settings)
            _ensure_table(conn, settings)
            rows = db.vector_label_rows(conn, path)
            for label, _ in rows:
                conn.execute(f"DELETE FROM {TABLE} WHERE rowid = ?", (int(label),))
            db.delete_vector_labels(conn, path, [ci for _, ci in rows])
    except VectorStoreUnavailable:
        LAST_OK = False
        raise
    except Exception as exc:
        LAST_OK = False
        raise VectorStoreUnavailable(f"delete failed for {path}: {exc}") from exc
    LAST_OK = True
    logger.debug("sqlite-vec delete %s: %d label(s)", path, len(rows))


def search(settings: Settings, vector: list[float], limit: int) -> list[VectorHit]:
    """Nearest chunks by cosine similarity (writer/embedded role)."""
    global LAST_OK

    try:
        query = normalize_query(vector, settings.embed_dim)
        with _connect(settings) as conn:
            _ensure_schema(conn, settings)
            # A rebuild writes (drop/create + invalidate), so it needs its own
            # transaction even on this read path.
            with conn:
                _ensure_table(conn, settings)
            hits = _knn(conn, query, limit)
    except VectorStoreUnavailable:
        LAST_OK = False
        raise
    except Exception as exc:
        LAST_OK = False
        raise VectorStoreUnavailable(f"search failed: {exc}") from exc
    LAST_OK = True
    return hits


def search_readonly(
    settings: Settings, vector: list[float], limit: int
) -> list[VectorHit]:
    """Query the published table without creating or mutating anything."""
    global LAST_OK

    try:
        query = normalize_query(vector, settings.embed_dim)
        with _connect(settings, readonly=True) as conn:
            if _table_sql(conn) is None:
                raise VectorStoreUnavailable(
                    "semantic index is not ready: the vector table has not been "
                    "created yet"
                )
            hits = _knn(conn, query, limit)
    except VectorStoreUnavailable:
        LAST_OK = False
        raise
    except sqlite3.OperationalError as exc:
        LAST_OK = False
        raise VectorStoreUnavailable(f"semantic index is not ready: {exc}") from exc
    except Exception as exc:
        LAST_OK = False
        raise VectorStoreUnavailable(f"read-only search failed: {exc}") from exc
    LAST_OK = True
    return hits


def reconcile(settings: Settings) -> int:
    """Flag chunks whose vectors were lost with a recreated table."""
    global LAST_OK, _created_on_load

    try:
        with _connect(settings) as conn, conn:
            _ensure_schema(conn, settings)
            _ensure_table(conn, settings)
            flagged = 0
            if _created_on_load:
                flagged = db.invalidate_embeddings(conn)
                _created_on_load = False
    except VectorStoreUnavailable:
        LAST_OK = False
        raise
    except sqlite3.Error as exc:
        LAST_OK = False
        raise VectorStoreUnavailable(f"reconcile failed: {exc}") from exc
    LAST_OK = True
    return flagged


def flush(settings: Settings) -> None:
    """Checkpoint the WAL; writes are already durable when the transaction commits."""
    global LAST_OK

    if not settings.index_db_path.is_file():
        return
    try:
        with _connect(settings) as conn:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except Exception:
        LAST_OK = False
        logger.debug("sqlite-vec checkpoint failed", exc_info=True)
        return
    LAST_OK = True


def vector_index_age_s(settings: Settings) -> float | None:
    """Seconds since the newest successful embedding, or None when unready."""
    try:
        with db.try_connect_readonly(settings.index_db_path) as conn:
            if conn is None:
                return None
            row = conn.execute(
                """
                SELECT (julianday('now') - julianday(MAX(updated_at))) * 86400.0
                FROM embedding_state WHERE status = 'ok'
                """
            ).fetchone()
    except sqlite3.Error:
        logger.debug("cannot read the embedding age", exc_info=True)
        return None
    if row is None or row[0] is None:
        return None
    return max(0.0, float(row[0]))


def last_ok(settings: Settings) -> bool:
    del settings
    return LAST_OK is True
