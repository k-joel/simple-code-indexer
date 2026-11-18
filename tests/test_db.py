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
        # ISS-8: an empty name must not turn the LIKE fallback into `%`.
        assert db.symbol_lookup(conn, "") == []
        assert db.symbol_lookup(conn, "   ") == []


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


def test_chunks_needing_embedding_reports_missing_and_failed(
    tmp_path: Path,
) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        file_id = db.upsert_file(conn, _record())
        db.replace_file_chunks(
            conn,
            file_id,
            [
                Chunk(chunk_index=0, start_line=1, end_line=1, content="int a()"),
                Chunk(chunk_index=1, start_line=2, end_line=2, content="int b()"),
            ],
        )
        ids = db.chunk_ids_for_path(conn, "src/foo.cpp")
        # No embedding_state row and an error row both need a retry.
        db.record_embedding_state(conn, [(ids[1][0], "point-1", "error")])
        pending = db.chunks_needing_embedding(conn)
        assert [(path, chunk.chunk_index) for path, chunk in pending] == [
            ("src/foo.cpp", 0),
            ("src/foo.cpp", 1),
        ]

        db.record_embedding_state(
            conn,
            [(ids[0][0], "point-0", "ok"), (ids[1][0], "point-1", "ok")],
        )
        assert db.chunks_needing_embedding(conn) == []


def test_embedding_counts_tracks_ok_and_pending(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        file_id = db.upsert_file(conn, _record())
        db.replace_file_chunks(
            conn,
            file_id,
            [
                Chunk(chunk_index=0, start_line=1, end_line=1, content="int a()"),
                Chunk(chunk_index=1, start_line=2, end_line=2, content="int b()"),
            ],
        )
        ids = db.chunk_ids_for_path(conn, "src/foo.cpp")
        assert db.embedding_counts(conn) == {"embedded": 0, "pending": 2}

        db.record_embedding_state(conn, [(ids[0][0], "point-0", "error")])
        assert db.embedding_counts(conn) == {"embedded": 0, "pending": 2}

        db.record_embedding_state(
            conn,
            [(ids[0][0], "point-0", "ok"), (ids[1][0], "point-1", "ok")],
        )
        assert db.embedding_counts(conn) == {"embedded": 2, "pending": 0}


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


def _bind(
    conn,
    collection: str,
    url: str = "http://localhost:6333",
    *,
    backend: str = "qdrant",
) -> bool:
    return db.ensure_index_identity(conn, backend=backend, identity=(url, collection))


def _bind_faiss(conn) -> bool:
    return db.ensure_index_identity(conn, backend="faiss", identity=FAISS_IDENTITY)


COLLECTION_A = "code_index_a_11111111_2560"
COLLECTION_B = "code_index_b_22222222_2560"
FAISS_IDENTITY = ("/ws/.simple-ci/vectors.faiss", "2560")


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


def test_index_identity_defaults_to_faiss_on_a_fresh_db(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        assert _bind_faiss(conn) is False
        assert db.get_meta(conn, "vector_backend") == "faiss"
        assert db.get_meta(conn, "faiss_path") == FAISS_IDENTITY[0]
        assert db.get_meta(conn, "faiss_dim") == FAISS_IDENTITY[1]


def test_legacy_qdrant_db_survives_the_upgrade(tmp_path: Path) -> None:
    # A DB written before `vector_backend` existed has only the Qdrant keys;
    # treating it as unknown would wipe an existing install on every restart.
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        db.set_meta(conn, "qdrant_url", "http://localhost:6333")
        db.set_meta(conn, "qdrant_collection", COLLECTION_A)
        _seed_rows(conn)

        assert _bind(conn, COLLECTION_A) is False
        assert db.stats(conn) == {"files": 1, "symbols": 0, "chunks": 1}
        assert db.get_meta(conn, "vector_backend") == "qdrant"


def test_switching_a_legacy_qdrant_db_to_faiss_invalidates_it(
    tmp_path: Path,
) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        db.set_meta(conn, "qdrant_url", "http://localhost:6333")
        db.set_meta(conn, "qdrant_collection", COLLECTION_A)
        _seed_rows(conn)
        db.allocate_vector_label(conn, "src/foo.cpp", 0)

        assert _bind_faiss(conn) is True
        assert db.stats(conn) == {"files": 0, "symbols": 0, "chunks": 0}
        assert db.vector_label_rows(conn, "src/foo.cpp") == []
        assert db.get_meta(conn, "vector_backend") == "faiss"
        # The legacy Qdrant keys stay as they were.
        assert db.get_meta(conn, "qdrant_collection") == COLLECTION_A


def test_switching_back_to_qdrant_invalidates_faiss_rows(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        _bind_faiss(conn)
        _seed_rows(conn)

        assert _bind(conn, COLLECTION_A) is True
        assert db.stats(conn) == {"files": 0, "symbols": 0, "chunks": 0}
        assert _bind(conn, COLLECTION_A) is False


def _bind_sqlite_vec(conn, dim: str = "2560") -> bool:
    return db.ensure_index_identity(
        conn, backend="sqlite-vec", identity=("sqlite-vec", dim)
    )


def test_sqlite_vec_identity_binds_the_table_dimension(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        assert _bind_sqlite_vec(conn) is False
        assert db.get_meta(conn, "vector_backend") == "sqlite-vec"
        assert db.get_meta(conn, "sqlite_vec_store") == "sqlite-vec"
        assert db.get_meta(conn, "sqlite_vec_dim") == "2560"
        assert _bind_sqlite_vec(conn) is False


def test_sqlite_vec_dimension_change_invalidates_the_index(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        assert _bind_sqlite_vec(conn) is False
        _seed_rows(conn)
        db.allocate_vector_label(conn, "src/foo.cpp", 0)

        assert _bind_sqlite_vec(conn, "1024") is True
        assert db.stats(conn) == {"files": 0, "symbols": 0, "chunks": 0}
        assert db.vector_label_rows(conn, "src/foo.cpp") == []
        assert _bind_sqlite_vec(conn, "1024") is False


def test_switching_from_sqlite_vec_invalidates_the_index(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        _bind_sqlite_vec(conn)
        _seed_rows(conn)

        assert _bind_faiss(conn) is True
        assert db.stats(conn) == {"files": 0, "symbols": 0, "chunks": 0}
        assert db.get_meta(conn, "vector_backend") == "faiss"


def test_invalidate_embeddings_flags_only_ok_rows(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        _seed_rows(conn)
        with conn:
            assert db.invalidate_embeddings(conn) == 1
            assert db.embedding_counts(conn) == {"embedded": 0, "pending": 1}
            # Nothing left in 'ok', so a second pass is a no-op.
            assert db.invalidate_embeddings(conn) == 0


def test_vector_labels_are_stable_and_never_reused(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        first = db.allocate_vector_label(conn, "src/a.cpp", 0)
        assert db.allocate_vector_label(conn, "src/a.cpp", 0) == first
        second = db.allocate_vector_label(conn, "src/a.cpp", 1)
        assert second > first

        # Deleting every row must not make a freed number allocatable again:
        # a crash can leave the old vector in the FAISS file.
        db.delete_vector_labels(conn, "src/a.cpp", [0, 1])
        assert db.vector_label_rows(conn, "src/a.cpp") == []
        third = db.allocate_vector_label(conn, "src/b.cpp", 0)
        assert third > second


def test_label_mapping_helpers(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        label = db.allocate_vector_label(conn, "src/a.cpp", 2)
        other = db.allocate_vector_label(conn, "src/b.cpp", 0)

        assert db.vector_label_rows(conn, "src/a.cpp") == [(label, 2)]
        mapping = db.vector_paths_for_labels(conn, [label, other, 999_999])
        assert mapping == {
            label: ("src/a.cpp", 2),
            other: ("src/b.cpp", 0),
        }

        assert db.dirty_vector_chunks(conn) == [
            ("src/a.cpp", 2),
            ("src/b.cpp", 0),
        ]
        db.clear_vector_dirty(conn)
        assert db.dirty_vector_chunks(conn) == []
        db.mark_vectors_dirty(conn, [other])
        assert db.dirty_vector_chunks(conn) == [("src/b.cpp", 0)]

        db.delete_vector_labels(conn, "src/a.cpp", [2])
        assert db.vector_label_rows(conn, "src/a.cpp") == []
        assert db.vector_label_rows(conn, "src/b.cpp") == [(other, 0)]


def test_flag_chunks_for_reembed_only_touches_dirty_labels(tmp_path: Path) -> None:
    with db.connect(db_path=tmp_path / "index.db") as conn:
        db.ensure_schema(conn)
        _seed_rows(conn)
        label = db.allocate_vector_label(conn, "src/foo.cpp", 0)

        # A clean label means the vector is presumed persisted.
        db.clear_vector_dirty(conn)
        assert db.flag_chunks_for_reembed(conn) == 0
        assert db.chunks_needing_embedding(conn) == []

        db.mark_vectors_dirty(conn, [label])
        assert db.flag_chunks_for_reembed(conn) == 1
        statuses = [
            str(row["status"])
            for row in conn.execute("SELECT status FROM embedding_state")
        ]
        assert statuses == ["missing"]
        assert [
            chunk.chunk_index for _, chunk in db.chunks_needing_embedding(conn)
        ] == [0]
