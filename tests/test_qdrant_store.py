import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from simple_code_indexer import qdrant_store
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.errors import QdrantUnavailable
from simple_code_indexer.models import Chunk
from simple_code_indexer.registry import get_registry

QDRANT_URL = "http://localhost:6333"


def _settings() -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=Path("/workspace"),
        index_db_path=Path("/workspace/.simple-ci/index.db"),
        qdrant_url=QDRANT_URL,
        qdrant_collection="code_index_2560",
        embed_base_url="http://localhost:8080",
        embed_model="Qwen3-Embedding-4B-Q6_K",
        embed_dim=2560,
        embed_timeout_s=15.0,
        sweep_seconds=45.0,
        debounce_ms=400,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
    )


def _qdrant_reachable() -> bool:
    try:
        urllib.request.urlopen(f"{QDRANT_URL}/collections", timeout=1)
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
    return True


def test_point_id_is_stable_and_index_sensitive() -> None:
    a = qdrant_store.point_id("src/foo.cpp", 0)
    b = qdrant_store.point_id("src/foo.cpp", 0)
    c = qdrant_store.point_id("src/foo.cpp", 1)
    d = qdrant_store.point_id("src/bar.cpp", 0)
    assert a == b
    assert len({a, c, d}) == 3
    assert a.int == a.int  # uuid5, fixed namespace


def _collection_info(size: int) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors=SimpleNamespace(size=size))
        )
    )


class _FakeClient:
    """Stands in for QdrantClient so collection-cache behaviour needs no server."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.attempts = 0
        self.vector_size = 2560

    def collection_exists(self, name: str) -> bool:
        return False

    def create_collection(self, name: str, vectors_config: object = None) -> None:
        self.attempts += 1
        self.created.append(name)
        time.sleep(0.05)  # open the check-then-create window for the race test

    def get_collection(self, name: str) -> SimpleNamespace:
        return _collection_info(self.vector_size)


class _ExistingClient(_FakeClient):
    """A collection that already exists before this process touches it."""

    def __init__(self, vector_size: int = 2560) -> None:
        super().__init__()
        self.vector_size = vector_size

    def collection_exists(self, name: str) -> bool:
        return True


def test_ensure_collection_is_keyed_by_url_and_collection(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(qdrant_store, "_client", lambda settings: client)
    monkeypatch.setattr(qdrant_store, "_ensured_collections", set())
    first = _settings()
    second = replace(first, qdrant_collection="code_index_other_2560")

    qdrant_store.ensure_collection(first)
    qdrant_store.ensure_collection(second)
    qdrant_store.ensure_collection(first)  # cached: no third create

    assert client.created == [first.qdrant_collection, second.qdrant_collection]


class _RaceClient(_FakeClient):
    """An observer that checks first and loses the create race (Qdrant 409)."""

    def __init__(self) -> None:
        super().__init__()
        self.exists = False

    def collection_exists(self, name: str) -> bool:
        return self.exists

    def create_collection(self, name: str, vectors_config: object = None) -> None:
        self.attempts += 1
        self.exists = True  # the other writer won
        raise RuntimeError("409 Conflict: collection already exists")


def test_ensure_collection_tolerates_a_concurrent_create(monkeypatch) -> None:
    client = _RaceClient()
    monkeypatch.setattr(qdrant_store, "_client", lambda settings: client)
    monkeypatch.setattr(qdrant_store, "_ensured_collections", set())

    qdrant_store.ensure_collection(_settings())  # must not raise

    assert qdrant_store.LAST_OK is True
    qdrant_store.ensure_collection(_settings())
    assert client.attempts == 1  # now cached, not retried


def test_existing_collection_with_matching_size_is_accepted(monkeypatch) -> None:
    client = _ExistingClient(vector_size=2560)
    monkeypatch.setattr(qdrant_store, "_client", lambda settings: client)
    monkeypatch.setattr(qdrant_store, "_ensured_collections", set())

    qdrant_store.ensure_collection(_settings())

    assert qdrant_store.LAST_OK is True
    assert client.created == []  # existing collection is reused, not recreated


def test_existing_collection_with_wrong_vector_size_is_rejected(monkeypatch) -> None:
    client = _ExistingClient(vector_size=1024)
    monkeypatch.setattr(qdrant_store, "_client", lambda settings: client)
    monkeypatch.setattr(qdrant_store, "_ensured_collections", set())

    with pytest.raises(QdrantUnavailable, match="1024"):
        qdrant_store.ensure_collection(_settings())

    assert qdrant_store.LAST_OK is False
    assert client.created == []


def test_concurrent_first_use_creates_the_collection_once(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(qdrant_store, "_client", lambda settings: client)
    monkeypatch.setattr(qdrant_store, "_ensured_collections", set())
    settings = _settings()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: qdrant_store.ensure_collection(settings), range(8)))

    assert client.created == [settings.qdrant_collection]


def test_unreachable_qdrant_raises_and_marks_not_ok() -> None:
    unreachable = replace(_settings(), qdrant_url="http://localhost:1")
    with pytest.raises(QdrantUnavailable):
        qdrant_store.ensure_collection(unreachable)
    assert qdrant_store.LAST_OK is False


class _UpsertClient(_ExistingClient):
    def __init__(self) -> None:
        super().__init__()
        self.points: list[object] = []

    def upsert(self, collection: str, points: list, wait: bool) -> None:
        self.points.extend(points)


def test_upsert_chunks_returns_the_point_ids(monkeypatch) -> None:
    client = _UpsertClient()
    monkeypatch.setattr(qdrant_store, "_client", lambda settings: client)
    monkeypatch.setattr(qdrant_store, "_ensured_collections", set())
    chunk = Chunk(chunk_index=2, start_line=1, end_line=2, content="int f()")

    ids = qdrant_store.upsert_chunks(
        _settings(), "src/foo.cpp", [(chunk, [0.0] * 2560)]
    )

    assert ids == [str(qdrant_store.point_id("src/foo.cpp", 2))]
    assert len(client.points) == 1
    assert qdrant_store.LAST_OK is True


@pytest.mark.skipif(not _qdrant_reachable(), reason="qdrant down")
def test_roundtrip_upsert_search_delete() -> None:
    settings = _settings()
    qdrant_store.ensure_collection(settings)
    path = "tests/_qdrant_roundtrip.cpp"
    # Fixed pseudo-random vector with a real query nearby.
    vector = [0.01 * ((i % 7) - 3) for i in range(2560)]
    chunk = Chunk(chunk_index=0, start_line=1, end_line=3, content="int roundtrip() {}")
    try:
        ids = qdrant_store.upsert_chunks(settings, path, [(chunk, vector)])
        assert ids == [str(qdrant_store.point_id(path, 0))]
        hits = qdrant_store.search(settings, vector, limit=5)
        assert any(h.path == path and h.chunk_index == 0 for h in hits)
    finally:
        qdrant_store.delete_by_path(settings, path)
    remaining = [
        h for h in qdrant_store.search(settings, vector, limit=10) if h.path == path
    ]
    assert remaining == []
    assert qdrant_store.LAST_OK is True
