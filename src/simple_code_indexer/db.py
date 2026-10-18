"""SQLite lexical index: schema, single-writer upserts, FTS5 queries."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from simple_code_indexer.models import Chunk, FileRecord, SearchHit, Symbol

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
  chunk_id        INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  qdrant_point_id TEXT NOT NULL,
  status          TEXT NOT NULL,
  updated_at      TEXT NOT NULL
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


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


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
    return int(row["id"])


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


def delete_file(conn: sqlite3.Connection, path: str) -> None:
    # FK cascade drops symbols/chunks; FTS triggers keep chunks_fts aligned.
    conn.execute("DELETE FROM files WHERE path = ?", (path,))


def _fts_match_expression(query: str) -> str | None:
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)


def fts_search(conn: sqlite3.Connection, query: str, limit: int) -> list[SearchHit]:
    match = _fts_match_expression(query)
    if match is None:
        return []
    rows = conn.execute(_FTS_SELECT, (match, limit)).fetchall()
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
    if not rows:
        rows = conn.execute(
            select.format(where="s.name LIKE ? ESCAPE '\\'"),
            (name.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%",),
        ).fetchall()
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
    """Upsert (chunk_id, qdrant_point_id, status) observability rows (TDD §7.5)."""
    conn.executemany(
        """
        INSERT INTO embedding_state (chunk_id, qdrant_point_id, status, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(chunk_id) DO UPDATE SET
          qdrant_point_id=excluded.qdrant_point_id,
          status=excluded.status,
          updated_at=excluded.updated_at
        """,
        rows,
    )


_COLLECTION_KEY = "qdrant_collection"
_QDRANT_URL_KEY = "qdrant_url"


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
    conn: sqlite3.Connection, *, qdrant_url: str, collection: str
) -> bool:
    """Bind the index to one Qdrant endpoint + collection; drop stale rows.

    Rows indexed elsewhere have no vectors where the next write lands, and the
    hash/mtime short circuits would never re-embed them, so they must go. Rows
    with no recorded identity are stale by the same argument.
    Returns True when the index was invalidated — an earlier binding existed, or
    rows were present.
    """
    stored = (get_meta(conn, _QDRANT_URL_KEY), get_meta(conn, _COLLECTION_KEY))
    if stored == (qdrant_url, collection):
        return False
    has_rows = conn.execute("SELECT EXISTS(SELECT 1 FROM files)").fetchone()
    invalidated = stored != (None, None) or bool(has_rows[0])
    if invalidated:
        conn.execute("DELETE FROM files")  # cascades symbols/chunks/embedding_state
    set_meta(conn, _QDRANT_URL_KEY, qdrant_url)
    set_meta(conn, _COLLECTION_KEY, collection)
    return invalidated


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
