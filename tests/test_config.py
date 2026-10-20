import hashlib
import re
from pathlib import Path

from simple_code_indexer.config import (
    derive_collection_name,
    load_settings,
    normalize_workspace_path,
)

# Qdrant rejects anything outside this charset (plan §2).
COLLECTION_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def test_defaults_come_from_the_process_cwd(monkeypatch) -> None:
    for name in (
        "WORKSPACE_ROOT",
        "INDEX_DB",
        "QDRANT_COLLECTION",
        "QDRANT_URL",
        "EMBED_BASE_URL",
        "EMBED_DIM",
    ):
        monkeypatch.delenv(name, raising=False)
    cwd = Path.cwd().resolve()
    settings = load_settings()
    assert settings.workspace_root == cwd
    assert settings.index_db_path == cwd / ".simple-ci" / "index.db"
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.embed_base_url == "http://localhost:8080"
    assert settings.embed_dim == 2560
    assert settings.embed_timeout_s == 15.0
    assert settings.embed_api_key is None
    assert settings.embedding_service is None
    assert settings.qdrant_service is None
    assert settings.config_source is None
    assert settings.sweep_seconds == 45.0
    assert settings.debounce_ms == 400
    assert settings.qdrant_collection.startswith("code_index_")
    assert settings.qdrant_collection.endswith("_2560")
    assert COLLECTION_RE.fullmatch(settings.qdrant_collection)
    assert ".cpp" in settings.allowed_exts
    assert ".git" in settings.ignore_dirs


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", "/data")
    monkeypatch.setenv("SWEEP_SECONDS", "10")
    monkeypatch.delenv("INDEX_DB", raising=False)
    monkeypatch.delenv("QDRANT_COLLECTION", raising=False)
    settings = load_settings()
    assert settings.workspace_root == Path("/data").resolve()
    assert settings.index_db_path == Path("/data").resolve() / ".simple-ci" / "index.db"
    assert settings.sweep_seconds == 10.0
    # Collection follows the overridden workspace, not the process cwd.
    assert "_data_" in settings.qdrant_collection
    assert settings.qdrant_collection.endswith("_2560")


def test_collection_env_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", "/data")
    monkeypatch.setenv("QDRANT_COLLECTION", "shared_manual")
    assert load_settings().qdrant_collection == "shared_manual"


def test_embed_dim_env_is_encoded_in_the_name(monkeypatch) -> None:
    monkeypatch.setenv("EMBED_DIM", "1024")
    monkeypatch.delenv("QDRANT_COLLECTION", raising=False)
    settings = load_settings()
    assert settings.embed_dim == 1024
    assert settings.qdrant_collection.endswith("_1024")


def test_collection_name_matches_the_spec_algorithm(tmp_path: Path) -> None:
    workspace = tmp_path / "My App (v2)"
    workspace.mkdir()
    # Plan §2 written longhand: lowercase, forward slashes, sha256, first 8 hex.
    normalized = str(workspace).lower().replace("\\", "/")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    name = derive_collection_name(workspace, 2560)
    assert name == f"code_index_my-app-v2_{digest}_2560"
    assert derive_collection_name(workspace, 2560) == name  # stable


def test_case_and_separator_do_not_change_the_normalized_path() -> None:
    assert normalize_workspace_path(Path("D:\\Projects\\App")) == (
        normalize_workspace_path(Path("d:/projects/app"))
    )


def test_slug_falls_back_to_root(tmp_path: Path) -> None:
    odd = tmp_path / "!!!"
    odd.mkdir()
    assert derive_collection_name(odd, 2560).startswith("code_index_root_")


def test_slug_is_capped_at_32_chars(tmp_path: Path) -> None:
    long_dir = tmp_path / ("x" * 40)
    long_dir.mkdir()
    assert derive_collection_name(long_dir, 2560).startswith(f"code_index_{'x' * 32}_")


def test_same_basename_in_different_parents_gets_distinct_collections(
    tmp_path: Path,
) -> None:
    first = tmp_path / "a" / "my-app"
    second = tmp_path / "b" / "my-app"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    name_first = derive_collection_name(first, 2560)
    name_second = derive_collection_name(second, 2560)
    assert name_first.startswith("code_index_my-app_")
    assert name_second.startswith("code_index_my-app_")
    assert name_first != name_second


def test_derived_names_are_qdrant_compliant(tmp_path: Path) -> None:
    for folder in ("App", "app.v2", "a b", "!!!"):
        directory = tmp_path / folder
        directory.mkdir()
        name = derive_collection_name(directory, 2560)
        assert COLLECTION_RE.fullmatch(name), name
        assert len(name) <= 255
