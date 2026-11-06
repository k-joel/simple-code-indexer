from dataclasses import replace
from pathlib import Path

import pytest

from simple_code_indexer import faiss_store, qdrant_store, vector_store
from simple_code_indexer.config import IGNORE_DIRS, Settings, faiss_index_path
from simple_code_indexer.errors import ConfigError
from simple_code_indexer.models import Chunk
from simple_code_indexer.registry import get_registry

DIM = 8


@pytest.fixture(autouse=True)
def _fresh_store():
    faiss_store._reset_state()
    faiss_store.LAST_OK = None
    yield
    faiss_store._reset_state()
    faiss_store.LAST_OK = None


def _settings(tmp_path: Path, *, backend: str = "faiss") -> Settings:
    registry = get_registry()
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
        vector_store=backend,
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


def test_faiss_backend_describes_the_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    path = tmp_path / ".simple-ci" / "vectors.faiss"
    assert vector_store.backend(settings) == "faiss"
    assert vector_store.describe(settings) == str(path)
    assert vector_store.identity(settings) == (str(path), str(DIM))
    assert faiss_index_path(settings) == path


def test_a_document_prompt_changes_the_faiss_identity(tmp_path: Path) -> None:
    settings = replace(_settings(tmp_path), embed_fingerprint="abcd1234")
    path = tmp_path / ".simple-ci" / "vectors.faiss"

    assert vector_store.identity(settings) == (str(path), f"{DIM}:abcd1234")


def test_a_query_prompt_leaves_the_faiss_identity_alone(tmp_path: Path) -> None:
    settings = replace(
        _settings(tmp_path), embed_query_prefix="Instruct: search\nQuery: {query}"
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


def test_faiss_roundtrip_through_the_router(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
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
