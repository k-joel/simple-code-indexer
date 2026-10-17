from pathlib import Path

from simple_code_indexer.config import load_settings


def test_defaults() -> None:
    settings = load_settings()
    assert settings.workspace_root == Path("/workspace")
    assert settings.index_db_path == Path("/workspace/.index/index.db")
    assert settings.qdrant_collection == "code_index_2560"
    assert settings.embed_dim == 2560
    assert settings.embed_timeout_s == 15.0
    assert settings.sweep_seconds == 45.0
    assert settings.debounce_ms == 400
    assert ".cpp" in settings.allowed_exts
    assert ".git" in settings.ignore_dirs


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", "/data")
    monkeypatch.setenv("SWEEP_SECONDS", "10")
    monkeypatch.delenv("INDEX_DB", raising=False)
    settings = load_settings()
    assert settings.workspace_root == Path("/data")
    assert settings.index_db_path == Path("/data/.index/index.db")
    assert settings.sweep_seconds == 10.0
