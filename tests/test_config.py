import hashlib
import re
from pathlib import Path

import pytest

from simple_code_indexer.config import (
    derive_collection_name,
    faiss_index_path,
    ipv4_loopback,
    load_settings,
    normalize_workspace_path,
)
from simple_code_indexer.errors import ConfigError

# Qdrant rejects anything outside this charset (plan §2).
COLLECTION_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def test_ipv4_loopback_rewrites_only_loopback_hosts() -> None:
    assert ipv4_loopback("http://localhost:8080") == "http://127.0.0.1:8080"
    assert ipv4_loopback("http://localhost/v1/models") == "http://127.0.0.1/v1/models"
    assert ipv4_loopback("http://[::1]:8080") == "http://127.0.0.1:8080"
    assert ipv4_loopback("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert ipv4_loopback("http://embed.test:9000") == "http://embed.test:9000"


def test_defaults_come_from_the_process_cwd(monkeypatch) -> None:
    for name in (
        "SIMPLE_CI_WORKSPACE_ROOT",
        "SIMPLE_CI_INDEX_DB",
        "SIMPLE_CI_QDRANT_COLLECTION",
        "SIMPLE_CI_QDRANT_URL",
        "SIMPLE_CI_EMBED_BASE_URL",
        "SIMPLE_CI_EMBED_DIM",
        "SIMPLE_CI_VECTOR_STORE",
        "SIMPLE_CI_FAISS_PATH",
        "SIMPLE_CI_SQLITE_VEC_CHUNK_SIZE",
        "SIMPLE_CI_SQLITE_VEC_MMAP_SIZE",
        "SIMPLE_CI_SQLITE_VEC_CACHE_SIZE",
        "SIMPLE_CI_LOG_LEVEL",
        "SIMPLE_CI_LOG_MAX_BYTES",
        "SIMPLE_CI_LOG_BACKUPS",
        "SIMPLE_CI_MODE",
        "SIMPLE_CI_IDLE_GRACE_S",
        "SIMPLE_CI_HEARTBEAT_S",
    ):
        monkeypatch.delenv(name, raising=False)
    cwd = Path.cwd().resolve()
    settings = load_settings()
    assert settings.workspace_root == cwd
    assert settings.index_db_path == cwd / ".simple-ci" / "index.db"
    assert settings.vector_store == "sqlite-vec"
    assert settings.faiss_path is None
    assert faiss_index_path(settings) == cwd / ".simple-ci" / "vectors.faiss"
    assert settings.sqlite_vec_chunk_size == 64
    assert settings.sqlite_vec_mmap_size == 1_073_741_824
    assert settings.sqlite_vec_cache_size == -262_144
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.embed_base_url == "http://localhost:8080"
    assert settings.embed_model == "embeddinggemma-2"
    assert settings.embed_dim == 768
    assert settings.embed_timeout_s == 15.0
    assert settings.embed_api_key is None
    assert settings.embedding_service is None
    assert settings.qdrant_service is None
    assert settings.config_source is None
    assert settings.sweep_seconds == 0.0
    assert not settings.sweep_enabled
    assert settings.debounce_ms == 400
    assert settings.log_level == "debug"
    assert settings.log_max_bytes == 5_000_000
    assert settings.log_backups == 3
    assert settings.mode == "sidecar"
    assert settings.idle_grace_s == 60.0
    assert settings.heartbeat_s == 5.0
    assert settings.qdrant_collection.startswith("code_index_")
    assert f"_{settings.embed_dim}_" in settings.qdrant_collection
    assert settings.qdrant_collection.endswith(settings.embed_fingerprint)
    assert COLLECTION_RE.fullmatch(settings.qdrant_collection)
    assert ".cpp" in settings.allowed_exts
    assert ".git" in settings.ignore_dirs


def test_inferred_home_workspace_is_refused(tmp_path: Path, monkeypatch) -> None:
    from simple_code_indexer import harnesses

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("SIMPLE_CI_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(harnesses, "discover_workspace", lambda *a, **k: None)
    monkeypatch.chdir(home)
    with pytest.raises(ConfigError, match="user home directory"):
        load_settings()


def test_an_implausible_cwd_asks_legacy_entries_for_a_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    from simple_code_indexer import config, harnesses

    cwd = tmp_path / "editor"
    cwd.mkdir()
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("SIMPLE_CI_WORKSPACE_ROOT", raising=False)

    def reason(path: Path) -> str | None:
        return "an editor installation directory" if path == cwd.resolve() else None

    monkeypatch.setattr(config, "_implausible_reason", reason)
    calls: list[bool] = []

    def fake(cwd_arg: Path, *, require_marker: bool = True, name=None):
        calls.append(require_marker)
        return None if require_marker else (workspace, "commandcode")

    monkeypatch.setattr(harnesses, "discover_workspace", fake)

    settings = load_settings()

    assert settings.workspace_root == workspace.resolve()
    assert settings.workspace_source == "harness:commandcode"
    assert calls == [True, False]


def test_a_plausible_cwd_is_not_overridden_by_a_legacy_entry(
    tmp_path: Path, monkeypatch
) -> None:
    from simple_code_indexer import config, harnesses

    workspace = tmp_path / "published"
    workspace.mkdir()
    monkeypatch.delenv("SIMPLE_CI_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(config, "_implausible_reason", lambda path: None)
    calls: list[bool] = []

    def fake(cwd_arg: Path, *, require_marker: bool = True, name=None):
        calls.append(require_marker)
        return None if require_marker else (workspace, "commandcode")

    monkeypatch.setattr(harnesses, "discover_workspace", fake)

    settings = load_settings()

    assert settings.workspace_root == Path.cwd().resolve()
    assert settings.workspace_source == "cwd"
    assert calls == [True]


def test_an_ancestor_install_directory_is_implausible(
    tmp_path: Path, monkeypatch
) -> None:
    from simple_code_indexer import config, parent_watch

    install = tmp_path / "Microsoft VS Code"
    install.mkdir()
    monkeypatch.setattr(
        parent_watch,
        "ancestor_install_dirs",
        lambda *a, **k: ((install, "Code.exe"),),
    )

    assert config._implausible_reason(install) == "the Code.exe installation directory"
    assert config._implausible_reason(tmp_path) is None


def test_an_editor_install_cwd_is_refused_when_no_harness_publishes(
    tmp_path: Path, monkeypatch
) -> None:
    from simple_code_indexer import config, harnesses

    cwd = tmp_path / "editor"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("SIMPLE_CI_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(harnesses, "discover_workspace", lambda *a, **k: None)
    monkeypatch.setattr(
        config,
        "_implausible_reason",
        lambda path: "the Code.exe installation directory",
    )

    with pytest.raises(ConfigError, match="Code.exe installation directory"):
        load_settings()


def test_explicit_workspace_root_may_be_the_home_directory(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SIMPLE_CI_WORKSPACE_ROOT", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(home)
    settings = load_settings()
    assert settings.workspace_root == home.resolve()
    assert settings.index_db_path == home.resolve() / ".simple-ci" / "index.db"


def test_workspace_source_defaults_to_the_cwd(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_WORKSPACE_ROOT", raising=False)
    settings = load_settings()
    assert settings.workspace_source == "cwd"


def test_the_workspace_argument_beats_roots_and_the_harness(
    tmp_path: Path, monkeypatch
) -> None:
    """`serve --workspace <dir>` is an explicit opt-in (ADR-022)."""
    from simple_code_indexer import harnesses

    pinned = tmp_path / "pinned"
    pinned.mkdir()
    roots = tmp_path / "roots"
    roots.mkdir()
    published = tmp_path / "published"
    published.mkdir()
    monkeypatch.delenv("SIMPLE_CI_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(
        harnesses, "discover_workspace", lambda cwd, **_: (published, "commandcode")
    )

    settings = load_settings(mcp_workspace=roots, cli_workspace=pinned)

    assert settings.workspace_root == pinned.resolve()
    assert settings.workspace_source == "arg"


def test_workspace_root_beats_the_workspace_argument(
    tmp_path: Path, monkeypatch
) -> None:
    env_root = tmp_path / "env"
    env_root.mkdir()
    pinned = tmp_path / "pinned"
    pinned.mkdir()
    monkeypatch.setenv("SIMPLE_CI_WORKSPACE_ROOT", str(env_root))

    settings = load_settings(cli_workspace=pinned)

    assert settings.workspace_root == env_root.resolve()
    assert settings.workspace_source == "env"


def test_an_implausible_workspace_is_allowed_when_pinned(
    tmp_path: Path, monkeypatch
) -> None:
    """An explicit pin opts in, exactly like `WORKSPACE_ROOT` and roots do."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("SIMPLE_CI_WORKSPACE_ROOT", raising=False)

    settings = load_settings(cli_workspace=home)

    assert settings.workspace_root == home.resolve()
    assert settings.workspace_source == "arg"


def test_harness_published_workspace_wins_over_the_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    from simple_code_indexer import harnesses

    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.delenv("SIMPLE_CI_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(
        harnesses, "discover_workspace", lambda cwd, **_: (workspace, "commandcode")
    )

    settings = load_settings()

    assert settings.workspace_root == workspace.resolve()
    assert settings.workspace_source == "harness:commandcode"


def test_mcp_roots_beat_the_harness_published_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    from simple_code_indexer import harnesses

    roots = tmp_path / "roots"
    roots.mkdir()
    published = tmp_path / "published"
    published.mkdir()
    monkeypatch.delenv("SIMPLE_CI_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(
        harnesses, "discover_workspace", lambda cwd, **_: (published, "commandcode")
    )

    settings = load_settings(mcp_workspace=roots)

    assert settings.workspace_root == roots.resolve()
    assert settings.workspace_source == "roots"


def test_workspace_root_env_beats_mcp_roots(tmp_path: Path, monkeypatch) -> None:
    env_root = tmp_path / "env"
    env_root.mkdir()
    roots = tmp_path / "roots"
    roots.mkdir()
    monkeypatch.setenv("SIMPLE_CI_WORKSPACE_ROOT", str(env_root))

    settings = load_settings(mcp_workspace=roots)

    assert settings.workspace_root == env_root.resolve()
    assert settings.workspace_source == "env"


def test_a_published_home_workspace_is_allowed(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("SIMPLE_CI_WORKSPACE_ROOT", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(home)

    settings = load_settings(mcp_workspace=home)

    assert settings.workspace_root == home.resolve()
    assert settings.workspace_source == "roots"


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLE_CI_WORKSPACE_ROOT", "/data")
    monkeypatch.setenv("SIMPLE_CI_SWEEP_SECONDS", "10")
    monkeypatch.delenv("SIMPLE_CI_INDEX_DB", raising=False)
    monkeypatch.delenv("SIMPLE_CI_QDRANT_COLLECTION", raising=False)
    settings = load_settings()
    assert settings.workspace_root == Path("/data").resolve()
    assert settings.index_db_path == Path("/data").resolve() / ".simple-ci" / "index.db"
    assert settings.sweep_seconds == 10.0
    assert settings.sweep_enabled
    # Collection follows the overridden workspace, not the process cwd.
    assert "_data_" in settings.qdrant_collection
    assert f"_{settings.embed_dim}_" in settings.qdrant_collection
    assert settings.qdrant_collection.endswith(settings.embed_fingerprint)


def test_negative_sweep_seconds_are_rejected(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch, "sweep_seconds: -5\n")
    with pytest.raises(ConfigError, match="sweep_seconds"):
        load_settings()

    _config(tmp_path, monkeypatch, "sweep_seconds: 0\n")
    monkeypatch.setenv("SIMPLE_CI_SWEEP_SECONDS", "-1")
    with pytest.raises(ConfigError, match="sweep_seconds"):
        load_settings()


def test_collection_env_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLE_CI_WORKSPACE_ROOT", "/data")
    monkeypatch.setenv("SIMPLE_CI_QDRANT_COLLECTION", "shared_manual")
    assert load_settings().qdrant_collection == "shared_manual"


def test_embed_dim_env_is_encoded_in_the_name(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLE_CI_EMBED_DIM", "1024")
    monkeypatch.delenv("SIMPLE_CI_QDRANT_COLLECTION", raising=False)
    settings = load_settings()
    assert settings.embed_dim == 1024
    assert "_1024_" in settings.qdrant_collection
    assert settings.qdrant_collection.endswith(settings.embed_fingerprint)


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
    monkeypatch.setenv("SIMPLE_CI_WORKSPACE_ROOT", str(tmp_path))


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
    assert load_settings().vector_store == "sqlite-vec"


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
    monkeypatch.setenv("SIMPLE_CI_VECTOR_STORE", "qdrant")
    assert load_settings().vector_store == "qdrant"


def test_invalid_vector_store_values_raise(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch, "vector_store: pinecone\n")
    with pytest.raises(ConfigError):
        load_settings()

    _config(tmp_path, monkeypatch, "vector_store: faiss\n")
    monkeypatch.setenv("SIMPLE_CI_VECTOR_STORE", "chroma")
    with pytest.raises(ConfigError):
        load_settings()


def test_vector_store_env_ignores_a_malformed_file_value(
    tmp_path: Path, monkeypatch
) -> None:
    _config(tmp_path, monkeypatch, "vector_store: [1, 2]\n")
    monkeypatch.setenv("SIMPLE_CI_VECTOR_STORE", "faiss")
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
    monkeypatch.setenv("SIMPLE_CI_FAISS_PATH", str(other))
    assert load_settings().faiss_path == other.resolve()


def test_absolute_faiss_path_is_kept(tmp_path: Path, monkeypatch) -> None:
    other = (tmp_path / "elsewhere" / "index.faiss").resolve()
    _config(tmp_path, monkeypatch, f"faiss:\n  path: {other}\n")
    assert load_settings().faiss_path == other


def test_sqlite_vec_tuning_reaches_the_settings(tmp_path: Path, monkeypatch) -> None:
    for name in (
        "SIMPLE_CI_SQLITE_VEC_CHUNK_SIZE",
        "SIMPLE_CI_SQLITE_VEC_MMAP_SIZE",
        "SIMPLE_CI_SQLITE_VEC_CACHE_SIZE",
    ):
        monkeypatch.delenv(name, raising=False)
    _config(
        tmp_path,
        monkeypatch,
        "sqlite_vec:\n  chunk_size: 128\n  mmap_size: 268435456\n  cache_size: -1000\n",
    )
    settings = load_settings()
    assert settings.sqlite_vec_chunk_size == 128
    assert settings.sqlite_vec_mmap_size == 268_435_456
    assert settings.sqlite_vec_cache_size == -1000


def test_sqlite_vec_env_overrides_the_file(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch, "sqlite_vec:\n  chunk_size: 128\n")
    monkeypatch.setenv("SIMPLE_CI_SQLITE_VEC_CHUNK_SIZE", "32")
    monkeypatch.setenv("SIMPLE_CI_SQLITE_VEC_MMAP_SIZE", "0")
    settings = load_settings()
    assert settings.sqlite_vec_chunk_size == 32
    assert settings.sqlite_vec_mmap_size == 0


def test_invalid_sqlite_vec_values_raise(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch, "sqlite_vec:\n  chunk_size: 0\n")
    with pytest.raises(ConfigError):
        load_settings()

    _config(tmp_path, monkeypatch, "sqlite_vec:\n  mmap_size: -1\n")
    with pytest.raises(ConfigError):
        load_settings()

    _config(tmp_path, monkeypatch, "sqlite_vec:\n  cache_size: 0\n")
    with pytest.raises(ConfigError):
        load_settings()


def test_log_section_values_reach_the_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_LOG_LEVEL", raising=False)
    monkeypatch.delenv("SIMPLE_CI_LOG_MAX_BYTES", raising=False)
    monkeypatch.delenv("SIMPLE_CI_LOG_BACKUPS", raising=False)
    _config(
        tmp_path,
        monkeypatch,
        "log:\n  level: warning\n  max_bytes: 1234\n  backups: 2\n",
    )
    settings = load_settings()
    assert settings.log_level == "warning"
    assert settings.log_max_bytes == 1234
    assert settings.log_backups == 2


def test_log_env_overrides_the_file_and_normalizes_case(
    tmp_path: Path, monkeypatch
) -> None:
    _config(tmp_path, monkeypatch, "log:\n  level: warning\n")
    monkeypatch.setenv("SIMPLE_CI_LOG_LEVEL", "INFO")
    monkeypatch.setenv("SIMPLE_CI_LOG_MAX_BYTES", "2048")
    monkeypatch.setenv("SIMPLE_CI_LOG_BACKUPS", "1")
    settings = load_settings()
    assert settings.log_level == "info"
    assert settings.log_max_bytes == 2048
    assert settings.log_backups == 1


def test_invalid_log_levels_raise(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_LOG_LEVEL", raising=False)
    _config(tmp_path, monkeypatch, "log:\n  level: loud\n")
    with pytest.raises(ConfigError, match="log.level"):
        load_settings()

    _config(tmp_path, monkeypatch, "log:\n  level: debug\n")
    monkeypatch.setenv("SIMPLE_CI_LOG_LEVEL", "verbose")
    with pytest.raises(ConfigError, match="SIMPLE_CI_LOG_LEVEL"):
        load_settings()


def test_sidecar_settings_come_from_config_and_env(tmp_path: Path, monkeypatch) -> None:
    for name in ("SIMPLE_CI_MODE", "SIMPLE_CI_IDLE_GRACE_S", "SIMPLE_CI_HEARTBEAT_S"):
        monkeypatch.delenv(name, raising=False)
    _config(
        tmp_path,
        monkeypatch,
        "mode: embedded\nidle_grace_s: 12.5\nheartbeat_s: 1.5\n",
    )
    settings = load_settings()
    assert settings.mode == "embedded"
    assert settings.idle_grace_s == 12.5
    assert settings.heartbeat_s == 1.5

    monkeypatch.setenv("SIMPLE_CI_MODE", "SIDECAR")
    monkeypatch.setenv("SIMPLE_CI_IDLE_GRACE_S", "0")
    monkeypatch.setenv("SIMPLE_CI_HEARTBEAT_S", "2.5")
    settings = load_settings()
    assert settings.mode == "sidecar"
    assert settings.idle_grace_s == 0.0
    assert settings.heartbeat_s == 2.5


def test_invalid_sidecar_settings_raise(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_MODE", raising=False)
    _config(tmp_path, monkeypatch, "mode: daemon\n")
    with pytest.raises(ConfigError, match="SIMPLE_CI_MODE|mode"):
        load_settings()

    _config(tmp_path, monkeypatch, "idle_grace_s: -1\n")
    with pytest.raises(ConfigError, match="idle_grace_s"):
        load_settings()

    _config(tmp_path, monkeypatch, "heartbeat_s: 0\n")
    with pytest.raises(ConfigError, match="heartbeat_s"):
        load_settings()
