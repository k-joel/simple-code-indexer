"""SQLite lexical index: schema, single-writer upserts, FTS5 queries."""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from simple_code_indexer.models import Chunk, FileRecord, SearchHit, Symbol

logger = logging.getLogger(__name__)

# A connection that lives longer than this is worth a diagnostic line.
_SLOW_DB_MS = 250

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  id          INTEGER PRIMARY KEY,
  path        TEXT NOT NULL UNIQUE,
  language    TEXT NOT NULL,
  size        INTEGER NOT NULL,
  sha256      TEXT NOT NULL,
  mtime       REAL NOT NULL,
  indexed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
  id          INTEGER PRIMARY KEY,
  file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL,
  line        INTEGER NOT NULL,
  line_end    INTEGER,
  signature   TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);

CREATE TABLE IF NOT EXISTS chunks (
  id          INTEGER PRIMARY KEY,
  file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  start_line  INTEGER NOT NULL,
  end_line    INTEGER NOT NULL,
  content     TEXT NOT NULL,
  UNIQUE(file_id, chunk_index)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  content,
  content='chunks',
  content_rowid='id',
  tokenize='unicode61'
);

-- Keep chunks_fts in sync with chunks (external-content FTS5 protocol).
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
  INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE IF NOT EXISTS embedding_state (
  chunk_id   INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  vector_id  TEXT NOT NULL,
  status     TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vector_labels (
  label       INTEGER PRIMARY KEY,
  path        TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  dirty       INTEGER NOT NULL DEFAULT 1,
  UNIQUE(path, chunk_index)
);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

_FTS_SELECT = """
SELECT c.start_line AS start_line,
       c.end_line AS end_line,
       f.path AS path,
       bm25(chunks_fts) AS rank,
       snippet(chunks_fts, 0, '', '', '…', 12) AS snip
FROM chunks_fts
JOIN chunks c ON c.id = chunks_fts.rowid
JOIN files f ON f.id = c.file_id
WHERE chunks_fts MATCH ?
ORDER BY rank
LIMIT ?
"""


@contextmanager
def connect(db_path: Path, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    """WAL connection with busy_timeout; readonly opens the file in mode=ro."""
    started = time.perf_counter()
    logger.debug("db open %s (%s)", db_path, "ro" if readonly else "rw")
    if readonly:
        uri = db_path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if elapsed_ms >= _SLOW_DB_MS:
            logger.debug("slow db session: %s took %d ms", db_path.name, elapsed_ms)


def ensure_schema(conn: sqlite3.Connection) -> None:
    started = time.perf_counter()
    conn.executescript(_SCHEMA)
    _migrate_embedding_state(conn)
    conn.commit()
    logger.debug("schema ensured in %d ms", int((time.perf_counter() - started) * 1000))


def _migrate_embedding_state(conn: sqlite3.Connection) -> None:
    """Rename the Qdrant-specific column; PRAGMA guards against a re-run."""
    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(embedding_state)")
    }
    if "qdrant_point_id" in columns and "vector_id" not in columns:
        logger.info("migrating embedding_state.qdrant_point_id -> vector_id")
        conn.execute(
            "ALTER TABLE embedding_state RENAME COLUMN qdrant_point_id TO vector_id"
        )


def upsert_file(conn: sqlite3.Connection, record: FileRecord) -> int:
    conn.execute(
        """
        INSERT INTO files (path, language, size, sha256, mtime, indexed_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(path) DO UPDATE SET
          language=excluded.language,
          size=excluded.size,
          sha256=excluded.sha256,
          mtime=excluded.mtime,
          indexed_at=excluded.indexed_at
        """,
        (record.path, record.language, record.size, record.sha256, record.mtime),
    )
    row = conn.execute("SELECT id FROM files WHERE path = ?", (record.path,)).fetchone()
    assert row is not None
    file_id = int(row["id"])
    logger.debug(
        "file upsert %s: id=%d language=%s size=%d sha=%s",
        record.path,
        file_id,
        record.language,
        record.size,
        record.sha256[:12],
    )
    return file_id


def file_hash(conn: sqlite3.Connection, path: str) -> str | None:
    row = conn.execute("SELECT sha256 FROM files WHERE path = ?", (path,)).fetchone()
    return None if row is None else str(row["sha256"])


def replace_file_symbols(
    conn: sqlite3.Connection, file_id: int, symbols: list[Symbol]
) -> None:
    conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
    conn.executemany(
        """
        INSERT INTO symbols (file_id, name, kind, line, line_end, signature)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(file_id, s.name, s.kind, s.line, s.line_end, s.signature) for s in symbols],
    )
    logger.debug("symbols for file %d: %d row(s)", file_id, len(symbols))


def replace_file_chunks(
    conn: sqlite3.Connection, file_id: int, chunks: list[Chunk]
) -> None:
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    conn.executemany(
        """
        INSERT INTO chunks (file_id, chunk_index, start_line, end_line, content)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(file_id, c.chunk_index, c.start_line, c.end_line, c.content) for c in chunks],
    )
    logger.debug("chunks for file %d: %d row(s)", file_id, len(chunks))


def delete_file(conn: sqlite3.Connection, path: str) -> None:
    # FK cascade drops symbols/chunks; FTS triggers keep chunks_fts aligned.
    conn.execute("DELETE FROM files WHERE path = ?", (path,))
    logger.debug("deleted %s (cascades symbols/chunks/FTS rows)", path)


def _fts_match_expression(query: str) -> str | None:
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)


def fts_search(conn: sqlite3.Connection, query: str, limit: int) -> list[SearchHit]:
    started = time.perf_counter()
    match = _fts_match_expression(query)
    if match is None:
        logger.debug("fts query %.200r has no searchable tokens", query)
        return []
    rows = conn.execute(_FTS_SELECT, (match, limit)).fetchall()
    logger.debug(
        "fts %s -> %d hit(s) in %d ms",
        match,
        len(rows),
        int((time.perf_counter() - started) * 1000),
    )
    return [
        SearchHit(
            path=str(row["path"]),
            line=int(row["start_line"]),
            end_line=int(row["end_line"]),
            snippet=str(row["snip"]),
            score=-float(row["rank"]),
            source="lexical",
        )
        for row in rows
    ]


def symbol_lookup(conn: sqlite3.Connection, name: str) -> list[Symbol]:
    select = """
        SELECT s.name, s.kind, s.line, s.line_end, s.signature,
               f.path AS path, f.language AS language
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE {where}
        ORDER BY f.path, s.line
    """
    rows = conn.execute(select.format(where="s.name = ?"), (name,)).fetchall()
    fallback = False
    if not rows:
        fallback = True
        rows = conn.execute(
            select.format(where="s.name LIKE ? ESCAPE '\\'"),
            (name.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%",),
        ).fetchall()
    logger.debug(
        "symbol lookup %r -> %d match(es)%s",
        name,
        len(rows),
        " (LIKE fallback)" if fallback else "",
    )
    return [
        Symbol(
            name=str(r["name"]),
            kind=str(r["kind"]),
            line=int(r["line"]),
            line_end=None if r["line_end"] is None else int(r["line_end"]),
            signature=None if r["signature"] is None else str(r["signature"]),
            path=str(r["path"]),
            language=None if r["language"] is None else str(r["language"]),
        )
        for r in rows
    ]


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM files) AS files,
          (SELECT COUNT(*) FROM symbols) AS symbols,
          (SELECT COUNT(*) FROM chunks) AS chunks
        """
    ).fetchone()
    assert row is not None
    return {
        "files": int(row["files"]),
        "symbols": int(row["symbols"]),
        "chunks": int(row["chunks"]),
    }


def chunk_ids_for_path(conn: sqlite3.Connection, path: str) -> list[tuple[int, int]]:
    """(chunk_id, chunk_index) pairs for one indexed path."""
    rows = conn.execute(
        """
        SELECT c.id, c.chunk_index
        FROM chunks c JOIN files f ON f.id = c.file_id
        WHERE f.path = ? ORDER BY c.chunk_index
        """,
        (path,),
    ).fetchall()
    return [(int(r["id"]), int(r["chunk_index"])) for r in rows]


def record_embedding_state(
    conn: sqlite3.Connection, rows: list[tuple[int, str, str]]
) -> None:
    """Upsert (chunk_id, vector_id, status) observability rows (TDD §7.5)."""
    conn.executemany(
        """
        INSERT INTO embedding_state (chunk_id, vector_id, status, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(chunk_id) DO UPDATE SET
          vector_id=excluded.vector_id,
          status=excluded.status,
          updated_at=excluded.updated_at
        """,
        rows,
    )
    logger.debug(
        "embedding_state: %d row(s) status=%s",
        len(rows),
        rows[0][2] if rows else "-",
    )


def chunks_needing_embedding(conn: sqlite3.Connection) -> list[tuple[str, Chunk]]:
    """(path, chunk) rows with no successful embedding_state record."""
    rows = conn.execute(
        """
        SELECT f.path AS path, c.chunk_index, c.start_line, c.end_line, c.content
        FROM chunks c
        JOIN files f ON f.id = c.file_id
        LEFT JOIN embedding_state e ON e.chunk_id = c.id
        WHERE e.chunk_id IS NULL OR e.status != 'ok'
        ORDER BY f.path, c.chunk_index
        """
    ).fetchall()
    logger.debug(
        "chunks needing embedding: %d chunk(s) in %d file(s)",
        len(rows),
        len({str(row["path"]) for row in rows}),
    )
    return [
        (
            str(row["path"]),
            Chunk(
                chunk_index=int(row["chunk_index"]),
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                content=str(row["content"]),
            ),
        )
        for row in rows
    ]


_COLLECTION_KEY = "qdrant_collection"
_QDRANT_URL_KEY = "qdrant_url"
_BACKEND_KEY = "vector_backend"
_FAISS_PATH_KEY = "faiss_path"
_FAISS_DIM_KEY = "faiss_dim"
_LABEL_SEQ_KEY = "vector_label_seq"

_IDENTITY_KEYS = {
    "qdrant": (_QDRANT_URL_KEY, _COLLECTION_KEY),
    "faiss": (_FAISS_PATH_KEY, _FAISS_DIM_KEY),
}

_SQL_BATCH = 500


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO meta (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )


def ensure_index_identity(
    conn: sqlite3.Connection, *, backend: str, identity: tuple[str, str]
) -> bool:
    """Bind the index to one vector store; drop rows whose vectors are gone.

    `identity` is (url, collection) for Qdrant and (path, dim) for FAISS. Rows
    indexed against another store have no vectors where the next write lands,
    and the hash/mtime short circuits would never re-embed them, so they must
    go. A DB written before `vector_backend` existed was Qdrant-bound when the
    Qdrant keys are present, so an existing Qdrant install survives the upgrade.
    Returns True when the index was invalidated — an earlier binding existed,
    or rows were present.
    """
    keys = _IDENTITY_KEYS[backend]
    requested = (str(identity[0]), str(identity[1]))
    stored_backend = get_meta(conn, _BACKEND_KEY)
    if stored_backend is None:
        qdrant_stored = (
            get_meta(conn, _QDRANT_URL_KEY),
            get_meta(conn, _COLLECTION_KEY),
        )
        if qdrant_stored != (None, None):
            stored_backend = "qdrant"
    stored = (get_meta(conn, keys[0]), get_meta(conn, keys[1]))
    if stored_backend == backend and stored == requested:
        # Backfill the explicit binding for a legacy Qdrant DB.
        set_meta(conn, _BACKEND_KEY, backend)
        logger.debug("index identity unchanged (%s %s)", backend, requested)
        return False
    has_rows = conn.execute("SELECT EXISTS(SELECT 1 FROM files)").fetchone()
    invalidated = stored_backend is not None or bool(has_rows[0])
    logger.debug(
        "index identity differs: stored=%s/%s requested=%s/%s",
        stored_backend,
        stored,
        backend,
        requested,
    )
    if invalidated:
        logger.info(
            "index invalidated: dropping indexed files for the %s binding %s",
            backend,
            requested,
        )
        conn.execute("DELETE FROM files")  # cascades symbols/chunks/embedding_state
        conn.execute("DELETE FROM vector_labels")
    set_meta(conn, _BACKEND_KEY, backend)
    set_meta(conn, keys[0], requested[0])
    set_meta(conn, keys[1], requested[1])
    return invalidated


def allocate_vector_label(conn: sqlite3.Connection, path: str, chunk_index: int) -> int:
    """Stable FAISS id for one chunk; labels are never reused after deletion."""
    row = conn.execute(
        "SELECT label FROM vector_labels WHERE path = ? AND chunk_index = ?",
        (path, chunk_index),
    ).fetchone()
    if row is not None:
        return int(row["label"])
    stored = get_meta(conn, _LABEL_SEQ_KEY)
    highest = conn.execute("SELECT COALESCE(MAX(label), 0) FROM vector_labels")
    label = max(int(stored or 0), int(highest.fetchone()[0])) + 1
    conn.execute(
        """
        INSERT INTO vector_labels (label, path, chunk_index, dirty)
        VALUES (?, ?, ?, 1)
        """,
        (label, path, chunk_index),
    )
    set_meta(conn, _LABEL_SEQ_KEY, str(label))
    logger.debug("allocated label %d for %s#%d", label, path, chunk_index)
    return label


def vector_label_rows(conn: sqlite3.Connection, path: str) -> list[tuple[int, int]]:
    """(label, chunk_index) pairs currently mapped to one path."""
    rows = conn.execute(
        "SELECT label, chunk_index FROM vector_labels WHERE path = ? ORDER BY label",
        (path,),
    ).fetchall()
    return [(int(row["label"]), int(row["chunk_index"])) for row in rows]


def vector_paths_for_labels(
    conn: sqlite3.Connection, labels: list[int]
) -> dict[int, tuple[str, int]]:
    """Map FAISS ids back to (path, chunk_index); unknown ids are absent."""
    mapping: dict[int, tuple[str, int]] = {}
    values = [int(label) for label in labels]
    for start in range(0, len(values), _SQL_BATCH):
        batch = values[start : start + _SQL_BATCH]
        placeholders = ", ".join("?" for _ in batch)
        rows = conn.execute(
            f"SELECT label, path, chunk_index FROM vector_labels "
            f"WHERE label IN ({placeholders})",
            batch,
        ).fetchall()
        for row in rows:
            mapping[int(row["label"])] = (
                str(row["path"]),
                int(row["chunk_index"]),
            )
    return mapping


def delete_vector_labels(
    conn: sqlite3.Connection, path: str, chunk_indexes: list[int]
) -> None:
    """Drop mappings for chunks a file no longer has."""
    conn.executemany(
        "DELETE FROM vector_labels WHERE path = ? AND chunk_index = ?",
        [(path, int(index)) for index in chunk_indexes],
    )
    logger.debug("deleted %d vector label(s) for %s", len(chunk_indexes), path)


def mark_vectors_dirty(conn: sqlite3.Connection, labels: list[int]) -> None:
    conn.executemany(
        "UPDATE vector_labels SET dirty = 1 WHERE label = ?",
        [(int(label),) for label in labels],
    )
    logger.debug("marked %d vector(s) dirty", len(labels))


def mark_all_vectors_dirty(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE vector_labels SET dirty = 1")
    logger.debug("marked all vector labels dirty")


def clear_vector_dirty(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE vector_labels SET dirty = 0 WHERE dirty != 0")
    logger.debug("cleared the vector dirty flags")


def dirty_vector_chunks(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """(path, chunk_index) for every label whose vector may not be persisted."""
    rows = conn.execute(
        "SELECT path, chunk_index FROM vector_labels WHERE dirty != 0"
        " ORDER BY path, chunk_index"
    ).fetchall()
    return [(str(row["path"]), int(row["chunk_index"])) for row in rows]


def flag_chunks_for_reembed(conn: sqlite3.Connection) -> int:
    """Mark dirty-label chunks missing so `chunks_needing_embedding` retries.

    Returns the number of chunks (not embedding_state rows) covered.
    """
    conn.execute(
        """
        UPDATE embedding_state SET status = 'missing', updated_at = datetime('now')
        WHERE chunk_id IN (
          SELECT c.id
          FROM chunks c
          JOIN files f ON f.id = c.file_id
          JOIN vector_labels v ON v.path = f.path AND v.chunk_index = c.chunk_index
          WHERE v.dirty != 0
        )
        """
    )
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM chunks c
        JOIN files f ON f.id = c.file_id
        JOIN vector_labels v ON v.path = f.path AND v.chunk_index = c.chunk_index
        WHERE v.dirty != 0
        """
    ).fetchone()
    assert row is not None
    covered = int(row[0])
    logger.debug("flagged %d chunk(s) for re-embedding", covered)
    return covered


class ChunkSpan(NamedTuple):
    start_line: int
    end_line: int
    content: str


def get_chunk(
    conn: sqlite3.Connection, path: str, chunk_index: int
) -> ChunkSpan | None:
    row = conn.execute(
        """
        SELECT c.start_line, c.end_line, c.content
        FROM chunks c JOIN files f ON f.id = c.file_id
        WHERE f.path = ? AND c.chunk_index = ?
        """,
        (path, chunk_index),
    ).fetchone()
    if row is None:
        return None
    return ChunkSpan(
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        content=str(row["content"]),
    )
