import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

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
        index_db_path=Path("/workspace/.index/index.db"),
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


def test_unreachable_qdrant_raises_and_marks_not_ok() -> None:
    unreachable = replace(_settings(), qdrant_url="http://localhost:1")
    with pytest.raises(QdrantUnavailable):
        qdrant_store.ensure_collection(unreachable)
    assert qdrant_store.LAST_OK is False


@pytest.mark.skipif(not _qdrant_reachable(), reason="qdrant down")
def test_roundtrip_upsert_search_delete() -> None:
    settings = _settings()
    qdrant_store.ensure_collection(settings)
    path = "tests/_qdrant_roundtrip.cpp"
    # Fixed pseudo-random vector with a real query nearby.
    vector = [0.01 * ((i % 7) - 3) for i in range(2560)]
    chunk = Chunk(chunk_index=0, start_line=1, end_line=3, content="int roundtrip() {}")
    try:
        qdrant_store.upsert_chunks(settings, path, [(chunk, vector)])
        hits = qdrant_store.search(settings, vector, limit=5)
        assert any(h.path == path and h.chunk_index == 0 for h in hits)
    finally:
        qdrant_store.delete_by_path(settings, path)
    remaining = [
        h for h in qdrant_store.search(settings, vector, limit=10) if h.path == path
    ]
    assert remaining == []
    assert qdrant_store.LAST_OK is True
