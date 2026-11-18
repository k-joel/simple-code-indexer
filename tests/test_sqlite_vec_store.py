import math
from dataclasses import replace
from pathlib import Path

import pytest

from simple_code_indexer import db, sqlite_vec_store
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.errors import VectorStoreUnavailable
from simple_code_indexer.models import Chunk, FileRecord, VectorHit
from simple_code_indexer.registry import get_registry

DIM = 8
PATH = "src/a.cpp"


@pytest.fixture(autouse=True)
def _fresh_store():
    sqlite_vec_store.LAST_OK = None
    sqlite_vec_store._created_on_load = False
    sqlite_vec_store._schema_ready.clear()
    yield
    sqlite_vec_store.LAST_OK = None
    sqlite_vec_store._created_on_load = False
    sqlite_vec_store._schema_ready.clear()


def _settings(tmp_path: Path, *, dim: int = DIM) -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=tmp_path,
        index_db_path=tmp_path / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_test",
        embed_base_url="http://localhost:1",
        embed_model="test-model",
        embed_dim=dim,
        embed_timeout_s=15.0,
        sweep_seconds=45.0,
        debounce_ms=400,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
    )


def _chunk(index: int) -> Chunk:
    return Chunk(
        chunk_index=index,
        start_line=index + 1,
        end_line=index + 2,
        content=f"chunk {index}",
    )


def _unit(axis: int, dim: int = DIM) -> list[float]:
    vector = [0.0] * dim
    vector[axis % dim] = 1.0
    return vector


def _seed_db(
    settings: Settings, *, path: str = PATH, chunk_indexes: tuple[int, ...] = (0,)
) -> None:
    """files/chunks/embedding_state rows so reconcile can join labels to chunks."""
    with db.connect(settings.index_db_path) as conn:
        db.ensure_schema(conn)
        with conn:
            file_id = db.upsert_file(
                conn,
                FileRecord(path=path, language="cpp", size=1, sha256="x", mtime=1.0),
            )
            db.replace_file_chunks(
                conn, file_id, [_chunk(index) for index in chunk_indexes]
            )
            db.record_embedding_state(
                conn,
                [
                    (chunk_id, "", "ok")
                    for chunk_id, _ in db.chunk_ids_for_path(conn, path)
                ],
            )


def _label_rows(settings: Settings, path: str = PATH) -> list[tuple[int, int]]:
    with db.connect(settings.index_db_path) as conn:
        return db.vector_label_rows(conn, path)


def _vec_count(settings: Settings) -> int:
    with sqlite_vec_store._connect(settings) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0])


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return dot / (left_norm * right_norm or 1.0)


def test_upsert_search_delete_roundtrip(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    vector = _unit(0)

    labels = sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), vector)])
    assert labels == ["1"]
    assert _label_rows(settings) == [(1, 0)]
    assert _vec_count(settings) == 1

    hits = sqlite_vec_store.search(settings, vector, 5)
    assert len(hits) == 1
    assert hits[0] == VectorHit(path=PATH, chunk_index=0, score=hits[0].score)
    assert hits[0].score == pytest.approx(1.0)
    assert sqlite_vec_store.LAST_OK is True

    sqlite_vec_store.delete_by_path(settings, PATH)
    assert sqlite_vec_store.search(settings, vector, 5) == []
    assert _label_rows(settings) == []
    assert _vec_count(settings) == 0


def test_scores_are_cosine_similarity(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    stored = [3.0, 4.0, 0, 0, 0, 0, 0, 0]
    query = [1.0, 0.0, 0, 0, 0, 0, 0, 0]
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), stored)])

    hits = sqlite_vec_store.search(settings, query, 1)
    assert hits[0].score == pytest.approx(_cosine(stored, query), abs=1e-5)

    same = sqlite_vec_store.search(settings, [30.0, 40.0, 0, 0, 0, 0, 0, 0], 1)
    assert same[0].score == pytest.approx(1.0, abs=1e-5)

    orthogonal = sqlite_vec_store.search(settings, [4.0, -3.0, 0, 0, 0, 0, 0, 0], 1)
    assert orthogonal[0].score == pytest.approx(0.0, abs=1e-5)


def test_reindexing_a_chunk_updates_in_place(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])

    assert sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(1))]) == [
        "1"
    ]
    assert _vec_count(settings) == 1
    assert [hit.score for hit in sqlite_vec_store.search(settings, _unit(1), 1)] == [
        pytest.approx(1.0)
    ]


def test_reindex_with_fewer_chunks_drops_the_stale_vector(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.upsert_chunks(
        settings, PATH, [(_chunk(0), _unit(0)), (_chunk(1), _unit(1))]
    )
    assert [index for _, index in _label_rows(settings)] == [0, 1]
    assert _vec_count(settings) == 2

    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    assert _label_rows(settings) == [(1, 0)]
    assert _vec_count(settings) == 1


def test_the_table_survives_a_reconnect(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    sqlite_vec_store.flush(settings)

    hits = sqlite_vec_store.search(settings, _unit(0), 5)
    assert [hit.path for hit in hits] == [PATH]


def test_an_empty_index_searches_as_empty(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.ensure_ready(settings)
    assert sqlite_vec_store.search(settings, _unit(0), 5) == []


def test_wrong_embedding_width_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(VectorStoreUnavailable) as error:
        sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), [1.0, 0.0, 0.0])])
    message = str(error.value)
    assert "3" in message
    assert str(DIM) in message
    assert sqlite_vec_store.LAST_OK is False


def test_wrong_query_width_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(VectorStoreUnavailable):
        sqlite_vec_store.search(settings, [1.0, 0.0, 0.0], 5)


def test_dim_mismatch_rebuilds_the_table_and_flags_reembed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_db(settings)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])

    smaller = replace(settings, embed_dim=4)
    sqlite_vec_store.ensure_ready(smaller)

    assert _vec_count(smaller) == 0
    with db.connect(smaller.index_db_path) as conn:
        pending = db.chunks_needing_embedding(conn)
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'vec_chunks'"
        ).fetchone()[0]
    assert [chunk.chunk_index for _, chunk in pending] == [0]
    assert "float[4]" in ddl


def test_search_rebuilds_a_mismatched_table_and_commits_it(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.ensure_ready(settings)
    _seed_db(settings)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])

    smaller = replace(settings, embed_dim=4)
    assert sqlite_vec_store.search(smaller, _unit(0, 4), 5) == []

    with db.connect(smaller.index_db_path) as conn:
        pending = db.chunks_needing_embedding(conn)
    assert [chunk.chunk_index for _, chunk in pending] == [0]


def test_chunk_size_change_rebuilds_the_table(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_db(settings)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])

    retuned = replace(settings, sqlite_vec_chunk_size=128)
    sqlite_vec_store.ensure_ready(retuned)

    assert _vec_count(retuned) == 0
    with db.connect(retuned.index_db_path) as conn:
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'vec_chunks'"
        ).fetchone()[0]
        pending = db.chunks_needing_embedding(conn)
    assert "chunk_size=128" in ddl
    assert [chunk.chunk_index for _, chunk in pending] == [0]


def test_the_ddl_uses_cosine_and_the_configured_chunk_size(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.ensure_ready(settings)
    with db.connect(settings.index_db_path) as conn:
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'vec_chunks'"
        ).fetchone()[0]
    assert f"float[{DIM}]" in ddl
    assert "distance_metric=cosine" in ddl
    assert f"chunk_size={settings.sqlite_vec_chunk_size}" in ddl


def test_reset_drops_and_recreates_the_table(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])

    sqlite_vec_store.reset(settings)

    assert _vec_count(settings) == 0
    assert _label_rows(settings) == []
    assert sqlite_vec_store.search(settings, _unit(0), 5) == []


def test_reconcile_is_a_noop_for_a_healthy_index(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.ensure_ready(settings)  # the writer's startup order
    _seed_db(settings)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])

    assert sqlite_vec_store.reconcile(settings) == 0


def test_reconcile_flags_chunks_when_the_table_was_lost(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_db(settings)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])

    sqlite_vec_store.discard(settings)
    sqlite_vec_store._created_on_load = False

    assert sqlite_vec_store.reconcile(settings) == 1
    with db.connect(settings.index_db_path) as conn:
        pending = db.chunks_needing_embedding(conn)
    assert [chunk.chunk_index for _, chunk in pending] == [0]


def test_search_drops_orphan_labels(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    with db.connect(settings.index_db_path) as conn, conn:
        db.delete_vector_labels(conn, PATH, [0])

    assert sqlite_vec_store.search(settings, _unit(0), 5) == []


def test_readonly_search_requires_a_published_table(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(VectorStoreUnavailable, match="not ready"):
        sqlite_vec_store.search_readonly(settings, _unit(0), 5)

    with db.connect(settings.index_db_path) as conn:
        db.ensure_schema(conn)
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'vec_chunks'"
        ).fetchone()


def test_readonly_search_reads_an_uncheckpointed_wal(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])

    # Hold the writer connection open: the committed vector is still in the WAL,
    # not in the database file, which is the reader's real-world condition.
    with db.connect(settings.index_db_path) as writer:
        hits = sqlite_vec_store.search_readonly(settings, _unit(0), 5)
        assert [hit.path for hit in hits] == [PATH]
        assert hits[0].score == pytest.approx(1.0)
        assert writer.execute("SELECT COUNT(*) FROM vector_labels").fetchone()[0] == 1


def test_readonly_search_never_writes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    sqlite_vec_store.flush(settings)
    before = settings.index_db_path.stat()

    sqlite_vec_store.search_readonly(settings, _unit(0), 5)

    after = settings.index_db_path.stat()
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)


def test_readonly_search_drops_orphan_labels(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    with db.connect(settings.index_db_path) as conn, conn:
        db.delete_vector_labels(conn, PATH, [0])

    assert sqlite_vec_store.search_readonly(settings, _unit(0), 5) == []


def test_query_connections_are_tuned(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.ensure_ready(settings)

    with sqlite_vec_store._connect(settings) as conn:
        assert conn.execute("PRAGMA mmap_size").fetchone()[0] >= 0
        assert conn.execute("PRAGMA cache_size").fetchone()[0] == -262_144

    with sqlite_vec_store._connect(settings, readonly=True) as conn:
        assert conn.execute("PRAGMA cache_size").fetchone()[0] == -262_144


def test_an_unloadable_extension_raises(tmp_path: Path, monkeypatch) -> None:
    def _broken():
        raise VectorStoreUnavailable("sqlite-vec is not importable: boom")

    monkeypatch.setattr(sqlite_vec_store, "_sqlite_vec", _broken)
    with pytest.raises(VectorStoreUnavailable, match="not importable"):
        sqlite_vec_store.ensure_ready(_settings(tmp_path))
    assert sqlite_vec_store.LAST_OK is False


def test_available_reports_the_version() -> None:
    ok, detail = sqlite_vec_store.available()
    assert ok is True
    assert "sqlite-vec" in detail


def test_vector_index_age_uses_the_newest_embedding(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_db(settings)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])

    age = sqlite_vec_store.vector_index_age_s(settings)

    assert age is not None
    assert age >= 0.0


def test_vector_index_age_is_none_without_embeddings(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.ensure_ready(settings)
    assert sqlite_vec_store.vector_index_age_s(settings) is None


def test_flush_checkpoints_without_raising(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    sqlite_vec_store.flush(settings)

    assert sqlite_vec_store.LAST_OK is True


def test_identity_ignores_the_workspace_location(tmp_path: Path) -> None:
    first = _settings(tmp_path / "one")
    second = _settings(tmp_path / "two")

    assert sqlite_vec_store.identity(first) == ("sqlite-vec", str(DIM))
    assert sqlite_vec_store.identity(first) == sqlite_vec_store.identity(second)

    fingerprinted = replace(first, embed_fingerprint="abcd1234")
    assert sqlite_vec_store.identity(fingerprinted) == ("sqlite-vec", f"{DIM}:abcd1234")


def test_describe_names_the_table(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert sqlite_vec_store.describe(settings) == (
        f"{settings.index_db_path}#vec_chunks"
    )


def test_delete_of_an_unknown_path_is_a_noop(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sqlite_vec_store.ensure_ready(settings)

    sqlite_vec_store.delete_by_path(settings, PATH)

    assert _vec_count(settings) == 0
    assert _label_rows(settings) == []
