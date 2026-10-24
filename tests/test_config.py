import hashlib
import re
from pathlib import Path

import pytest

from simple_code_indexer.config import (
    derive_collection_name,
    faiss_index_path,
    load_settings,
    normalize_workspace_path,
)
from simple_code_indexer.errors import ConfigError

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
        "VECTOR_STORE",
        "FAISS_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    cwd = Path.cwd().resolve()
    settings = load_settings()
    assert settings.workspace_root == cwd
    assert settings.index_db_path == cwd / ".simple-ci" / "index.db"
    assert settings.vector_store == "faiss"
    assert settings.faiss_path is None
    assert faiss_index_path(settings) == cwd / ".simple-ci" / "vectors.faiss"
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


def _config(tmp_path: Path, monkeypatch, text: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(path))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))


def test_a_legacy_qdrant_section_selects_qdrant(tmp_path: Path, monkeypatch) -> None:
    _config(
        tmp_path,
        monkeypatch,
        "embedding:\n  dim: 8\nqdrant:\n  url: http://localhost:6333\n",
    )
    settings = load_settings()
    assert settings.vector_store == "qdrant"
    assert settings.qdrant_url == "http://localhost:6333"


def test_an_empty_qdrant_section_is_not_legacy(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch, "qdrant:\n  {}\n")
    assert load_settings().vector_store == "faiss"


def test_explicit_faiss_beats_the_legacy_qdrant_section(
    tmp_path: Path, monkeypatch
) -> None:
    _config(
        tmp_path,
        monkeypatch,
        "vector_store: faiss\nqdrant:\n  url: http://localhost:6333\n",
    )
    assert load_settings().vector_store == "faiss"


def test_vector_store_env_overrides_the_file(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch, "vector_store: faiss\n")
    monkeypatch.setenv("VECTOR_STORE", "qdrant")
    assert load_settings().vector_store == "qdrant"


def test_invalid_vector_store_values_raise(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch, "vector_store: pinecone\n")
    with pytest.raises(ConfigError):
        load_settings()

    _config(tmp_path, monkeypatch, "vector_store: faiss\n")
    monkeypatch.setenv("VECTOR_STORE", "chroma")
    with pytest.raises(ConfigError):
        load_settings()


def test_vector_store_env_ignores_a_malformed_file_value(
    tmp_path: Path, monkeypatch
) -> None:
    _config(tmp_path, monkeypatch, "vector_store: [1, 2]\n")
    monkeypatch.setenv("VECTOR_STORE", "faiss")
    assert load_settings().vector_store == "faiss"


def test_faiss_path_from_config_is_relative_to_the_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    _config(tmp_path, monkeypatch, "faiss:\n  path: cache/vectors.faiss\n")
    settings = load_settings()
    assert settings.faiss_path == (tmp_path / "cache" / "vectors.faiss").resolve()
    assert faiss_index_path(settings) == settings.faiss_path


def test_faiss_path_env_overrides_the_file(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch, "faiss:\n  path: cache/vectors.faiss\n")
    other = tmp_path / "elsewhere" / "index.faiss"
    monkeypatch.setenv("FAISS_PATH", str(other))
    assert load_settings().faiss_path == other.resolve()


def test_absolute_faiss_path_is_kept(tmp_path: Path, monkeypatch) -> None:
    other = (tmp_path / "elsewhere" / "index.faiss").resolve()
    _config(tmp_path, monkeypatch, f"faiss:\n  path: {other}\n")
    assert load_settings().faiss_path == other
