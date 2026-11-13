from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from simple_code_indexer import db, faiss_store
from simple_code_indexer.config import IGNORE_DIRS, Settings, faiss_index_path
from simple_code_indexer.errors import VectorStoreUnavailable
from simple_code_indexer.models import Chunk, FileRecord, VectorHit
from simple_code_indexer.registry import get_registry

DIM = 8
PATH = "src/a.cpp"


@pytest.fixture(autouse=True)
def _fresh_store():
    faiss_store._reset_state()
    faiss_store._reset_read_state()
    faiss_store.LAST_OK = None
    yield
    faiss_store._reset_state()
    faiss_store._reset_read_state()
    faiss_store.LAST_OK = None


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


def test_upsert_search_delete_roundtrip(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    vector = _unit(0)

    labels = faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), vector)])
    assert labels == ["1"]
    assert _label_rows(settings) == [(1, 0)]

    hits = faiss_store.search(settings, vector, 5)
    assert len(hits) == 1
    assert hits[0] == VectorHit(path=PATH, chunk_index=0, score=hits[0].score)
    assert hits[0].score == pytest.approx(1.0)
    assert faiss_store.LAST_OK is True

    faiss_store.delete_by_path(settings, PATH)
    assert faiss_store.search(settings, vector, 5) == []
    assert _label_rows(settings) == []
    assert faiss_store._index is not None
    assert faiss_store._index.ntotal == 0


def test_scores_are_cosine_similarity(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    faiss_store.upsert_chunks(
        settings, PATH, [(_chunk(0), [3.0, 4.0, 0, 0, 0, 0, 0, 0])]
    )

    same = faiss_store.search(settings, [30.0, 40.0, 0, 0, 0, 0, 0, 0], 1)
    assert same[0].score == pytest.approx(1.0)

    orthogonal = faiss_store.search(settings, [4.0, -3.0, 0, 0, 0, 0, 0, 0], 1)
    assert orthogonal[0].score == pytest.approx(0.0, abs=1e-6)


def test_reindexing_a_chunk_does_not_duplicate_the_label(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    faiss_store.flush(settings)

    assert faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(1))]) == ["1"]
    assert faiss_store._index is not None
    assert faiss_store._index.ntotal == 1
    assert [hit.score for hit in faiss_store.search(settings, _unit(1), 1)] == [
        pytest.approx(1.0)
    ]


def test_reindex_with_fewer_chunks_drops_the_stale_label(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    faiss_store.upsert_chunks(
        settings, PATH, [(_chunk(0), _unit(0)), (_chunk(1), _unit(1))]
    )
    assert [index for _, index in _label_rows(settings)] == [0, 1]

    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    assert _label_rows(settings) == [(1, 0)]
    assert faiss_store._index is not None
    assert faiss_store._index.ntotal == 1


def test_the_file_survives_a_reload(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    faiss_store.flush(settings)
    path = faiss_index_path(settings)
    assert path.is_file()

    faiss_store._reset_state()
    hits = faiss_store.search(settings, _unit(0), 5)
    assert [hit.path for hit in hits] == [PATH]
    assert faiss_store._reset_on_load is False


def test_an_empty_index_searches_as_empty(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert faiss_store.search(settings, _unit(0), 5) == []


def test_wrong_embedding_width_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(VectorStoreUnavailable) as error:
        faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), [1.0, 0.0, 0.0, 0.0])])
    message = str(error.value)
    assert "4" in message
    assert str(DIM) in message
    assert faiss_store.LAST_OK is False


def test_wrong_query_width_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(VectorStoreUnavailable):
        faiss_store.search(settings, [1.0, 0.0, 0.0, 0.0], 5)


def test_dim_mismatch_resets_the_index(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_db(settings)
    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    faiss_store.flush(settings)

    smaller = replace(settings, embed_dim=4)
    faiss_store._reset_state()
    faiss_store.ensure_ready(smaller)

    assert faiss_store._reset_on_load is True
    assert faiss_store._index is not None
    assert faiss_store._index.ntotal == 0

    assert faiss_store.reconcile(smaller) == 1
    with db.connect(smaller.index_db_path) as conn:
        pending = db.chunks_needing_embedding(conn)
    assert [chunk.chunk_index for _, chunk in pending] == [0]


def test_atomic_write_replaces_the_file(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    path = faiss_index_path(settings)
    replacements: list[tuple[Path, Path]] = []
    real_replace = faiss_store.os.replace

    def _replace(source, destination) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(faiss_store.os, "replace", _replace)
    faiss_store.flush(settings)

    assert replacements == [(path.with_name(path.name + ".tmp"), path)]
    assert not path.with_name(path.name + ".tmp").exists()
    assert path.is_file()


def test_flush_clears_the_dirty_flags(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    with db.connect(settings.index_db_path) as conn:
        assert db.dirty_vector_chunks(conn) == [(PATH, 0)]

    faiss_store.flush(settings)
    with db.connect(settings.index_db_path) as conn:
        assert db.dirty_vector_chunks(conn) == []


def test_reconcile_flags_chunks_when_the_file_was_lost(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_db(settings)
    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    faiss_store.flush(settings)

    faiss_index_path(settings).unlink()
    faiss_store._reset_state()

    assert faiss_store.reconcile(settings) == 1
    with db.connect(settings.index_db_path) as conn:
        assert db.dirty_vector_chunks(conn) == [(PATH, 0)]
        pending = db.chunks_needing_embedding(conn)
    assert [chunk.chunk_index for _, chunk in pending] == [0]


def test_search_drops_orphan_labels(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    with db.connect(settings.index_db_path) as conn, conn:
        db.delete_vector_labels(conn, PATH, [0])

    assert faiss_store.search(settings, _unit(0), 5) == []


def test_readonly_search_requires_a_published_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(VectorStoreUnavailable, match="not ready"):
        faiss_store.search_readonly(settings, _unit(0), 5)
    assert not faiss_index_path(settings).exists()


def test_readonly_search_reloads_after_the_writer_flushes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    faiss_store.flush(settings)

    first = faiss_store.search_readonly(settings, _unit(0), 5)
    assert [hit.path for hit in first] == [PATH]

    other = "src/b.cpp"
    faiss_store.upsert_chunks(settings, other, [(_chunk(0), _unit(1))])
    faiss_store.flush(settings)

    hits = faiss_store.search_readonly(settings, _unit(1), 1)
    assert [hit.path for hit in hits] == [other]


def test_readonly_search_never_writes_the_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    faiss_store.flush(settings)
    path = faiss_index_path(settings)
    before = path.stat()

    faiss_store.search_readonly(settings, _unit(0), 5)

    after = path.stat()
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)


def test_readonly_search_drops_orphan_labels(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    faiss_store.upsert_chunks(settings, PATH, [(_chunk(0), _unit(0))])
    faiss_store.flush(settings)
    with db.connect(settings.index_db_path) as conn, conn:
        db.delete_vector_labels(conn, PATH, [0])

    assert faiss_store.search_readonly(settings, _unit(0), 5) == []


def test_concurrent_search_and_upsert_do_not_corrupt_the_index(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    def _work(index: int) -> list[VectorHit]:
        path = f"src/f{index}.cpp"
        faiss_store.upsert_chunks(settings, path, [(_chunk(0), _unit(index))])
        return faiss_store.search(settings, _unit(index), 5)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_work, range(8)))

    assert all(results)
    assert faiss_store._index is not None
    assert faiss_store._index.ntotal == 8

    faiss_store.flush(settings)
    faiss_store._reset_state()
    assert len(faiss_store.search(settings, _unit(0), 8)) == 8
