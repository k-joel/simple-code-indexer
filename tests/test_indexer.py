from dataclasses import replace
from pathlib import Path

import pytest

from simple_code_indexer import (
    db,
    embed,
    faiss_store,
    indexer,
    qdrant_store,
    sqlite_vec_store,
)
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.errors import EmbedError
from simple_code_indexer.languages import catalog
from simple_code_indexer.registry import get_registry

FIXTURE = """\
#include <cstdint>

uint32_t calculateWidgetChecksum(int seed) {
    uint32_t acc = static_cast<uint32_t>(seed);
    return acc ^ 0x9E3779B9u;
}
"""


@pytest.fixture(autouse=True)
def _no_embed_network(monkeypatch) -> None:
    """Unit tests index lexically; embedding failure path is test_embed's job."""

    def _stub(settings, texts):
        raise EmbedError("stubbed out in unit tests")

    monkeypatch.setattr(embed, "embed_texts", _stub)


def _settings(workspace: Path) -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=workspace,
        index_db_path=workspace / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_2560",
        embed_base_url="http://localhost:1",  # hermetic: fail-soft embed path
        embed_model="Qwen3-Embedding-4B-Q6_K",
        embed_dim=2560,
        embed_timeout_s=15.0,
        sweep_seconds=45.0,
        debounce_ms=400,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        vector_store="qdrant",
    )


def _ids(path: str, items) -> list[str]:
    """Stand-in for qdrant_store.upsert_chunks: one stable id per chunk."""
    return [f"{path}:{chunk.chunk_index}" for chunk, _ in items]


def test_index_one_file_end_to_end(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = tmp_path / "widget_checksum.cpp"
    source.write_text(FIXTURE, encoding="utf-8")

    outcome = indexer.index_one_file(settings, source)
    assert outcome.status == "indexed"
    assert outcome.path == "widget_checksum.cpp"
    assert outcome.duration_ms >= 0

    with db.connect(settings.index_db_path, readonly=True) as conn:
        assert db.stats(conn) == {"files": 1, "symbols": 1, "chunks": 1}
        hits = db.fts_search(conn, "calculateWidgetChecksum", limit=5)
        assert len(hits) == 1
        assert hits[0].path == "widget_checksum.cpp"
        symbols = db.symbol_lookup(conn, "calculateWidgetChecksum")
        assert len(symbols) == 1
        assert symbols[0].line == 3


def test_hash_short_circuit(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = tmp_path / "a.cpp"
    source.write_text("int a() { return 1; }", encoding="utf-8")
    assert indexer.index_one_file(settings, source).status == "indexed"
    second = indexer.index_one_file(settings, source)
    assert second.status == "skipped_unchanged"


def test_sweep_reembeds_failed_chunks_without_file_changes(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    source = tmp_path / "a.cpp"
    source.write_text("int a() { return 1; }", encoding="utf-8")
    assert indexer.index_one_file(settings, source).status == "indexed"

    with db.connect(settings.index_db_path, readonly=True) as conn:
        statuses = [
            str(r["status"]) for r in conn.execute("SELECT status FROM embedding_state")
        ]
    assert statuses == ["error"]

    embedded: list[str] = []
    upserted: list[str] = []

    def _embed(settings: Settings, texts: list[str]) -> list[list[float]]:
        embedded.extend(texts)
        return [[0.0] * 8 for _ in texts]

    monkeypatch.setattr(embed, "embed_texts", _embed)

    def _upsert(_settings: Settings, path: str, items) -> list[str]:
        upserted.append(path)
        return _ids(path, items)

    monkeypatch.setattr(qdrant_store, "upsert_chunks", _upsert)

    stats = indexer.sweep(settings)
    assert stats.unchanged == 1
    assert embedded  # retried despite the unchanged hash/mtime short circuit
    assert upserted == ["a.cpp"]

    with db.connect(settings.index_db_path, readonly=True) as conn:
        statuses = [
            str(r["status"]) for r in conn.execute("SELECT status FROM embedding_state")
        ]
    assert statuses == ["ok"]

    embedded.clear()
    indexer.sweep(settings)
    assert embedded == []  # successful chunks are not re-embedded


def test_reembed_stops_at_the_first_failing_file(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    for name in ("a.cpp", "b.cpp"):
        (tmp_path / name).write_text(
            f"int {name[0]}() {{ return 1; }}", encoding="utf-8"
        )
    indexer.sweep(settings)  # autouse stub fails both embeds

    calls: list[list[str]] = []

    def _fail(settings: Settings, texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        raise EmbedError("down")

    monkeypatch.setattr(embed, "embed_texts", _fail)
    assert indexer.reembed_pending(settings) == 0
    assert len(calls) == 1


def test_a_short_embedding_response_is_recorded_as_an_error(
    tmp_path: Path, monkeypatch
) -> None:
    settings = replace(_settings(tmp_path), vector_store="faiss", embed_dim=8)
    faiss_store._reset_state()
    faiss_store.LAST_OK = None
    monkeypatch.setattr(embed, "embed_texts", lambda _settings, _texts: [])
    try:
        source = tmp_path / "a.cpp"
        source.write_text("int a() { return 1; }", encoding="utf-8")
        assert indexer.index_one_file(settings, source).status == "indexed"
        with db.connect(settings.index_db_path) as conn:
            statuses = [
                str(row["status"])
                for row in conn.execute("SELECT status FROM embedding_state")
            ]
        assert statuses == ["error"]
    finally:
        faiss_store._reset_state()
        faiss_store.LAST_OK = None


def test_skipped_filtered_and_missing_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    md = tmp_path / "notes.md"
    md.write_text("hi", encoding="utf-8")
    assert indexer.index_one_file(settings, md).status == "skipped_filtered"
    missing = tmp_path / "ghost.cpp"
    assert indexer.index_one_file(settings, missing).status == "error"


def test_sweep_prunes_ignored_dirs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    (tmp_path / ".venv").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text(
        "def hidden():\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "node_modules" / "x.py").write_text(
        "def also_hidden():\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "visible.py").write_text("def visible():\n    pass\n", encoding="utf-8")

    stats = indexer.sweep(settings)
    assert stats.indexed == 1
    with db.connect(settings.index_db_path, readonly=True) as conn:
        paths = [str(r["path"]) for r in conn.execute("SELECT path FROM files")]
    assert paths == ["visible.py"]


def test_faiss_backend_records_labels_and_reembeds(tmp_path: Path, monkeypatch) -> None:
    settings = replace(_settings(tmp_path), vector_store="faiss", embed_dim=8)
    faiss_store._reset_state()
    faiss_store.LAST_OK = None
    vector = [1.0] + [0.0] * 7

    def _embed(_settings: Settings, texts: list[str]) -> list[list[float]]:
        return [vector for _ in texts]

    monkeypatch.setattr(embed, "embed_texts", _embed)
    try:
        source = tmp_path / "a.cpp"
        source.write_text("int a() { return 1; }", encoding="utf-8")
        assert indexer.index_one_file(settings, source).status == "indexed"

        with db.connect(settings.index_db_path) as conn:
            assert db.vector_label_rows(conn, "a.cpp") == [(1, 0)]
            rows = conn.execute(
                "SELECT vector_id, status FROM embedding_state"
            ).fetchall()
            assert [(str(r["vector_id"]), str(r["status"])) for r in rows] == [
                ("1", "ok")
            ]
            assert db.dirty_vector_chunks(conn) == [("a.cpp", 0)]

        assert indexer.sweep(settings).unchanged == 1
        with db.connect(settings.index_db_path) as conn:
            assert db.dirty_vector_chunks(conn) == []
        assert (tmp_path / ".simple-ci" / "vectors.faiss").is_file()

        # A lost vector is flagged at startup and re-embedded under its label.
        with db.connect(settings.index_db_path) as conn, conn:
            db.mark_vectors_dirty(conn, [1])
            db.flag_chunks_for_reembed(conn)
        assert indexer.sweep(settings).unchanged == 1
        with db.connect(settings.index_db_path) as conn:
            statuses = [
                str(row["status"])
                for row in conn.execute("SELECT status FROM embedding_state")
            ]
        assert statuses == ["ok"]
        assert faiss_store.search(settings, vector, 1)[0].path == "a.cpp"
    finally:
        faiss_store._reset_state()
        faiss_store.LAST_OK = None


def test_sqlite_vec_backend_records_labels_and_reembeds(
    tmp_path: Path, monkeypatch
) -> None:
    settings = replace(_settings(tmp_path), vector_store="sqlite-vec", embed_dim=8)
    sqlite_vec_store._created_on_load = False
    vector = [1.0] + [0.0] * 7

    def _embed(_settings: Settings, texts: list[str]) -> list[list[float]]:
        return [vector for _ in texts]

    monkeypatch.setattr(embed, "embed_texts", _embed)
    try:
        sqlite_vec_store.ensure_ready(settings)
        source = tmp_path / "a.cpp"
        source.write_text("int a() { return 1; }", encoding="utf-8")
        assert indexer.index_one_file(settings, source).status == "indexed"

        with db.connect(settings.index_db_path) as conn:
            assert db.vector_label_rows(conn, "a.cpp") == [(1, 0)]
            rows = conn.execute(
                "SELECT vector_id, status FROM embedding_state"
            ).fetchall()
            assert [(str(r["vector_id"]), str(r["status"])) for r in rows] == [
                ("1", "ok")
            ]
        assert sqlite_vec_store.search(settings, vector, 1)[0].path == "a.cpp"

        # A chunk flagged missing is re-embedded; the vector is replaced in place.
        with db.connect(settings.index_db_path) as conn, conn:
            db.invalidate_embeddings(conn)
        assert indexer.sweep(settings).unchanged == 1
        with db.connect(settings.index_db_path) as conn:
            statuses = [
                str(row["status"])
                for row in conn.execute("SELECT status FROM embedding_state")
            ]
        assert statuses == ["ok"]
        assert sqlite_vec_store.search(settings, vector, 1)[0].path == "a.cpp"
    finally:
        sqlite_vec_store._created_on_load = False
        sqlite_vec_store.LAST_OK = None


def test_sweep_indexes_drift_and_removes_deleted(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    a = tmp_path / "a.cpp"
    b = tmp_path / "b.py"
    a.write_text("int a() { return 1; }", encoding="utf-8")
    b.write_text("def b():\n    return 2\n", encoding="utf-8")

    first = indexer.sweep(settings)
    assert first.indexed == 2
    assert first.errors == 0

    again = indexer.sweep(settings)
    assert again.indexed == 0
    assert again.unchanged == 2

    a.write_text("int a() { return 42; }  // changed", encoding="utf-8")
    b.unlink()
    third = indexer.sweep(settings)
    assert third.indexed == 1

    with db.connect(settings.index_db_path, readonly=True) as conn:
        stats = db.stats(conn)
        assert stats["files"] == 1
        assert db.fts_search(conn, "return", limit=10) and all(
            h.path == "a.cpp" for h in db.fts_search(conn, "return", limit=10)
        )
        assert db.symbol_lookup(conn, "b") == []


def test_next_sweep_delay_doubles_while_idle_and_caps() -> None:
    assert indexer.next_sweep_delay(45.0, 45.0, idle=False) == 45.0
    assert indexer.next_sweep_delay(45.0, 45.0, idle=True) == 90.0
    assert indexer.next_sweep_delay(45.0, 360.0, idle=True) == 600.0
    assert indexer.next_sweep_delay(45.0, 600.0, idle=True) == 600.0
    # A base above the cap is never shortened.
    assert indexer.next_sweep_delay(1200.0, 1200.0, idle=True) == 1200.0


def test_pending_embedding_count_is_zero_without_an_index(tmp_path: Path) -> None:
    assert indexer.pending_embedding_count(_settings(tmp_path)) == 0


def test_pending_embedding_count_counts_unembedded_chunks(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(qdrant_store, "upsert_chunks", _ids)
    source = tmp_path / "a.cpp"
    source.write_text("int a() { return 1; }", encoding="utf-8")
    indexer.index_one_file(settings, source)

    assert indexer.pending_embedding_count(settings) > 0


def test_sweep_generation_advances(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    before = indexer.SWEEP_GENERATION
    indexer.sweep(settings)
    assert indexer.SWEEP_GENERATION == before + 1


def test_backfill_symbols_rewrites_symbols_only(tmp_path: Path) -> None:
    """A symbol-map upgrade re-parses files without re-chunking or re-embedding."""
    settings = _settings(tmp_path)
    source = tmp_path / "widget.cpp"
    source.write_text(FIXTURE, encoding="utf-8")
    indexer.index_one_file(settings, source)

    with db.connect(settings.index_db_path) as conn:
        before = db.stats(conn)
        with conn:
            conn.execute("DELETE FROM symbols")
        assert db.stats(conn)["symbols"] == 0

    updated = indexer.backfill_symbols(settings)

    assert updated == 1
    with db.connect(settings.index_db_path) as conn:
        after = db.stats(conn)
        assert after["symbols"] > 0
        # Only the symbols table moved; chunks and embedding state are untouched.
        assert after["chunks"] == before["chunks"]
        assert after["files"] == before["files"]


def test_backfill_symbols_is_stamped_with_the_map_version(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    (tmp_path / "widget.cpp").write_text(FIXTURE, encoding="utf-8")
    indexer.index_one_file(settings, tmp_path / "widget.cpp")

    indexer.backfill_symbols(settings)

    with db.connect(settings.index_db_path) as conn:
        assert db.get_meta(conn, "symbol_map_version") == catalog.SYMBOL_MAP_VERSION


def test_backfill_symbols_tolerates_a_missing_file(tmp_path: Path) -> None:
    """A path deleted while the backfill runs is skipped, not fatal."""
    settings = _settings(tmp_path)
    source = tmp_path / "gone.cpp"
    source.write_text(FIXTURE, encoding="utf-8")
    indexer.index_one_file(settings, source)
    source.unlink()

    assert indexer.backfill_symbols(settings) == 0
    with db.connect(settings.index_db_path) as conn:
        assert db.get_meta(conn, "symbol_map_version") == catalog.SYMBOL_MAP_VERSION
