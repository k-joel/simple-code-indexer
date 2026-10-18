from pathlib import Path

from simple_code_indexer import db
from simple_code_indexer.models import Chunk, FileRecord, Symbol


def _record(path: str = "src/foo.cpp") -> FileRecord:
    return FileRecord(path=path, language="cpp", size=12, sha256="abc", mtime=1.0)


def test_schema_and_stats(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        assert db.stats(conn) == {"files": 0, "symbols": 0, "chunks": 0}
        conn.execute("PRAGMA journal_mode")  # must not raise while open


def test_upsert_file_and_replace_rows(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        file_id = db.upsert_file(conn, _record())
        db.replace_file_symbols(
            conn, file_id, [Symbol(name="f", kind="function", line=3)]
        )
        db.replace_file_chunks(
            conn,
            file_id,
            [Chunk(chunk_index=0, start_line=1, end_line=4, content="int f()")],
        )
        stats = db.stats(conn)
        assert stats == {"files": 1, "symbols": 1, "chunks": 1}

        # Re-index replaces rows instead of duplicating them.
        file_id2 = db.upsert_file(conn, _record())
        assert file_id2 == file_id
        db.replace_file_symbols(
            conn, file_id2, [Symbol(name="g", kind="function", line=9)]
        )
        db.replace_file_chunks(
            conn,
            file_id2,
            [
                Chunk(chunk_index=0, start_line=1, end_line=2, content="int g()"),
                Chunk(chunk_index=1, start_line=3, end_line=4, content="int g2()"),
            ],
        )
        assert db.stats(conn) == {"files": 1, "symbols": 1, "chunks": 2}


def test_unchanged_hash_short_circuit(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        db.upsert_file(conn, _record())
        assert db.file_hash(conn, "src/foo.cpp") == "abc"
        assert db.file_hash(conn, "missing.cpp") is None


def test_fts_search_hit_shape(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        file_id = db.upsert_file(conn, _record())
        db.replace_file_chunks(
            conn,
            file_id,
            [
                Chunk(
                    chunk_index=0,
                    start_line=10,
                    end_line=20,
                    content="uint32_t calculateWidgetChecksum() { return 1; }",
                ),
                Chunk(
                    chunk_index=1,
                    start_line=30,
                    end_line=40,
                    content="unrelated text about kettles",
                ),
            ],
        )
        hits = db.fts_search(conn, "calculateWidgetChecksum", limit=10)
        assert len(hits) == 1
        hit = hits[0]
        assert hit.path == "src/foo.cpp"
        assert hit.line == 10
        assert hit.end_line == 20
        assert hit.source == "lexical"
        assert "calculateWidgetChecksum" in hit.snippet
        assert isinstance(hit.score, float)

        # Hostile query must not raise (FTS5 operator injection).
        assert db.fts_search(conn, '"; DROP TABLE chunks; --', limit=5) == []
        assert db.fts_search(conn, "", limit=5) == []


def test_symbol_lookup_exact_and_prefix(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        file_id = db.upsert_file(conn, _record())
        db.replace_file_symbols(
            conn,
            file_id,
            [
                Symbol(
                    name="calculateWidgetChecksum",
                    kind="function",
                    line=9,
                    line_end=20,
                    signature="uint32_t calculateWidgetChecksum(const Widget&)",
                ),
                Symbol(name="calculateOther", kind="function", line=30),
            ],
        )
        hits = db.symbol_lookup(conn, "calculateWidgetChecksum")
        assert len(hits) == 1
        top = hits[0]
        assert top.path == "src/foo.cpp"
        assert top.kind == "function"
        assert top.line == 9
        assert top.line_end == 20
        assert top.signature == "uint32_t calculateWidgetChecksum(const Widget&)"

        prefix = db.symbol_lookup(conn, "calculate")
        assert len(prefix) == 2

        assert db.symbol_lookup(conn, "nope") == []


def test_delete_file_removes_rows(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        file_id = db.upsert_file(conn, _record())
        db.replace_file_symbols(
            conn, file_id, [Symbol(name="f", kind="function", line=1)]
        )
        db.replace_file_chunks(
            conn,
            file_id,
            [Chunk(chunk_index=0, start_line=1, end_line=1, content="int f()")],
        )
        db.delete_file(conn, "src/foo.cpp")
        assert db.stats(conn) == {"files": 0, "symbols": 0, "chunks": 0}
        assert db.fts_search(conn, "f", limit=5) == []


def _seed_rows(conn) -> None:
    file_id = db.upsert_file(conn, _record())
    db.replace_file_chunks(
        conn,
        file_id,
        [Chunk(chunk_index=0, start_line=1, end_line=1, content="int widget()")],
    )
    db.record_embedding_state(
        conn,
        [
            (chunk_id, "point-1", "ok")
            for chunk_id, _ in db.chunk_ids_for_path(conn, "src/foo.cpp")
        ],
    )


def _bind(conn, collection: str, url: str = "http://localhost:6333") -> bool:
    return db.ensure_index_identity(conn, qdrant_url=url, collection=collection)


COLLECTION_A = "code_index_a_11111111_2560"
COLLECTION_B = "code_index_b_22222222_2560"


def test_index_identity_leaves_an_empty_index_alone(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        assert _bind(conn, COLLECTION_A) is False
        assert _bind(conn, COLLECTION_A) is False


def test_index_identity_treats_unrecorded_rows_as_stale(tmp_path: Path) -> None:
    # Rows written before identities were recorded belong to an unknown
    # collection, so their vectors cannot be assumed to exist in the current one.
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        _seed_rows(conn)
        assert db.stats(conn) == {"files": 1, "symbols": 0, "chunks": 1}

        assert _bind(conn, COLLECTION_A) is True
        assert db.stats(conn) == {"files": 0, "symbols": 0, "chunks": 0}
        assert _bind(conn, COLLECTION_A) is False


def test_index_identity_wipes_rows_when_the_collection_changes(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        assert _bind(conn, COLLECTION_A) is False
        _seed_rows(conn)
        assert _bind(conn, COLLECTION_A) is False
        assert db.stats(conn) == {"files": 1, "symbols": 0, "chunks": 1}

        # A different collection invalidates every row: no vectors exist in it,
        # and unchanged files would never be re-embedded.
        assert _bind(conn, COLLECTION_B) is True
        assert db.stats(conn) == {"files": 0, "symbols": 0, "chunks": 0}
        embedding_rows = conn.execute("SELECT COUNT(*) FROM embedding_state").fetchone()
        assert embedding_rows[0] == 0
        assert db.fts_search(conn, "widget", limit=5) == []

        # The new binding sticks.
        assert _bind(conn, COLLECTION_B) is False


def test_index_identity_wipes_rows_when_the_qdrant_endpoint_changes(
    tmp_path: Path,
) -> None:
    other = "http://other-host:6333"
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        assert _bind(conn, COLLECTION_A) is False
        _seed_rows(conn)

        # Same collection name, different server: the vectors are not there.
        assert _bind(conn, COLLECTION_A, other) is True
        assert db.stats(conn) == {"files": 0, "symbols": 0, "chunks": 0}
        assert _bind(conn, COLLECTION_A, other) is False
