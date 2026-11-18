from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from simple_code_indexer import (
    faiss_store,
    qdrant_store,
    sqlite_vec_store,
    vector_store,
)
from simple_code_indexer.config import IGNORE_DIRS, Settings, faiss_index_path
from simple_code_indexer.errors import ConfigError
from simple_code_indexer.models import Chunk
from simple_code_indexer.registry import get_registry

DIM = 8


@pytest.fixture(autouse=True)
def _fresh_store():
    faiss_store._reset_state()
    faiss_store.LAST_OK = None
    sqlite_vec_store.LAST_OK = None
    sqlite_vec_store._created_on_load = False
    sqlite_vec_store._schema_ready.clear()
    yield
    faiss_store._reset_state()
    faiss_store.LAST_OK = None
    sqlite_vec_store.LAST_OK = None
    sqlite_vec_store._created_on_load = False
    sqlite_vec_store._schema_ready.clear()


def _settings(tmp_path: Path, *, backend: str | None = None) -> Settings:
    registry = get_registry()
    values: dict[str, Any] = {"vector_store": backend} if backend is not None else {}
    return Settings(
        workspace_root=tmp_path,
        index_db_path=tmp_path / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_test_8",
        embed_base_url="http://localhost:1",
        embed_model="test-model",
        embed_dim=DIM,
        embed_timeout_s=15.0,
        sweep_seconds=45.0,
        debounce_ms=400,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        **values,
    )


def _chunk(index: int = 0) -> Chunk:
    return Chunk(
        chunk_index=index,
        start_line=index + 1,
        end_line=index + 2,
        content=f"chunk {index}",
    )


def _unit(axis: int = 0) -> list[float]:
    vector = [0.0] * DIM
    vector[axis % DIM] = 1.0
    return vector


def test_the_default_backend_is_sqlite_vec(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.vector_store == "sqlite-vec"
    assert vector_store.backend(settings) == "sqlite-vec"


def test_every_backend_exposes_the_store_contract() -> None:
    """The registry is the only coupling point; drift must fail here."""
    for name in vector_store.VECTOR_STORES:
        module = vector_store._STORES[name]()
        for member in vector_store.STORE_CONTRACT:
            assert callable(getattr(module, member, None)), f"{name}.{member}"


def test_sqlite_vec_backend_describes_the_table(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert vector_store.backend(settings) == "sqlite-vec"
    assert vector_store.describe(settings) == f"{settings.index_db_path}#vec_chunks"
    assert vector_store.identity(settings) == ("sqlite-vec", str(DIM))


def test_a_document_prompt_changes_the_sqlite_vec_identity(tmp_path: Path) -> None:
    settings = replace(_settings(tmp_path), embed_fingerprint="abcd1234")
    assert vector_store.identity(settings) == ("sqlite-vec", f"{DIM}:abcd1234")


def test_a_query_prompt_leaves_the_sqlite_vec_identity_alone(tmp_path: Path) -> None:
    settings = replace(
        _settings(tmp_path), embed_query_prefix="Instruct: search\nQuery: {query}"
    )
    assert vector_store.identity(settings) == ("sqlite-vec", str(DIM))


def test_faiss_backend_describes_the_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path, backend="faiss")
    path = tmp_path / ".simple-ci" / "vectors.faiss"
    assert vector_store.backend(settings) == "faiss"
    assert vector_store.describe(settings) == str(path)
    assert vector_store.identity(settings) == (str(path), str(DIM))
    assert faiss_index_path(settings) == path


def test_a_document_prompt_changes_the_faiss_identity(tmp_path: Path) -> None:
    settings = replace(
        _settings(tmp_path, backend="faiss"), embed_fingerprint="abcd1234"
    )
    path = tmp_path / ".simple-ci" / "vectors.faiss"

    assert vector_store.identity(settings) == (str(path), f"{DIM}:abcd1234")


def test_a_query_prompt_leaves_the_faiss_identity_alone(tmp_path: Path) -> None:
    settings = replace(
        _settings(tmp_path, backend="faiss"),
        embed_query_prefix="Instruct: search\nQuery: {query}",
    )
    path = tmp_path / ".simple-ci" / "vectors.faiss"

    assert vector_store.identity(settings) == (str(path), str(DIM))


def test_qdrant_backend_describes_the_collection(tmp_path: Path) -> None:
    settings = _settings(tmp_path, backend="qdrant")
    assert vector_store.backend(settings) == "qdrant"
    assert vector_store.describe(settings) == settings.qdrant_collection
    assert vector_store.identity(settings) == (
        settings.qdrant_url,
        settings.qdrant_collection,
    )


def test_an_unknown_backend_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path, backend="pinecone")
    with pytest.raises(ConfigError):
        vector_store.backend(settings)


def test_sqlite_vec_roundtrip_through_the_router(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    vector_store.ensure_ready(settings)

    labels = vector_store.upsert_chunks(settings, "src/a.cpp", [(_chunk(), _unit())])
    assert labels == ["1"]
    hits = vector_store.search(settings, _unit(), 5)
    assert [(hit.path, hit.chunk_index) for hit in hits] == [("src/a.cpp", 0)]
    assert vector_store.last_ok(settings) is True
    assert vector_store.reconcile(settings) == 0

    vector_store.flush(settings)
    assert not faiss_index_path(settings).exists()

    vector_store.delete_by_path(settings, "src/a.cpp")
    assert vector_store.search(settings, _unit(), 5) == []


def test_faiss_roundtrip_through_the_router(tmp_path: Path) -> None:
    settings = _settings(tmp_path, backend="faiss")
    vector_store.ensure_ready(settings)

    labels = vector_store.upsert_chunks(settings, "src/a.cpp", [(_chunk(), _unit())])
    assert labels == ["1"]
    hits = vector_store.search(settings, _unit(), 5)
    assert [(hit.path, hit.chunk_index) for hit in hits] == [("src/a.cpp", 0)]
    assert vector_store.last_ok(settings) is True
    assert vector_store.reconcile(settings) == 0

    vector_store.flush(settings)
    assert faiss_index_path(settings).is_file()

    vector_store.delete_by_path(settings, "src/a.cpp")
    assert vector_store.search(settings, _unit(), 5) == []


def test_qdrant_dispatch_stays_unchanged(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, backend="qdrant")
    calls: list[str] = []

    monkeypatch.setattr(
        qdrant_store, "ensure_collection", lambda _s: calls.append("ensure")
    )
    monkeypatch.setattr(
        qdrant_store,
        "upsert_chunks",
        lambda _s, path, items: calls.append("upsert") or ["point-1"],
    )
    monkeypatch.setattr(
        qdrant_store, "delete_by_path", lambda _s, path: calls.append("delete")
    )
    monkeypatch.setattr(
        qdrant_store,
        "search",
        lambda _s, vector, limit: calls.append("search") or [],
    )
    monkeypatch.setattr(qdrant_store, "LAST_OK", True)

    vector_store.ensure_ready(settings)
    assert vector_store.upsert_chunks(settings, "src/a.cpp", [(_chunk(), _unit())]) == [
        "point-1"
    ]
    vector_store.delete_by_path(settings, "src/a.cpp")
    assert vector_store.search(settings, _unit(), 5) == []
    assert vector_store.reconcile(settings) == 0
    vector_store.flush(settings)  # no-op for Qdrant

    assert calls == ["ensure", "upsert", "delete", "search"]
    assert vector_store.last_ok(settings) is True
    assert not faiss_index_path(settings).exists()


def test_reset_is_a_noop_for_qdrant(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, backend="qdrant")
    calls: list[str] = []
    monkeypatch.setattr(
        qdrant_store, "ensure_collection", lambda _s: calls.append("ensure")
    )
    vector_store.reset(settings)
    assert calls == []


def test_reset_drops_a_stale_vec_table_when_switching_away(tmp_path: Path) -> None:
    sqlite_settings = _settings(tmp_path)
    vector_store.ensure_ready(sqlite_settings)
    vector_store.upsert_chunks(sqlite_settings, "src/a.cpp", [(_chunk(), _unit())])

    vector_store.reset(_settings(tmp_path, backend="faiss"))

    with sqlite_vec_store._connect(sqlite_settings) as conn:
        assert sqlite_vec_store._table_sql(conn) is None
