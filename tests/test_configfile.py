from pathlib import Path

import pytest

from simple_code_indexer import configfile, model_prompts
from simple_code_indexer.config import load_settings
from simple_code_indexer.errors import ConfigError


def test_local_config_is_ignored(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_CONFIG", raising=False)
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    (workspace / ".simple-ci").mkdir(parents=True)
    (home / ".simple-ci").mkdir(parents=True)
    local = workspace / ".simple-ci" / "config.yaml"
    local.write_text("embedding:\n  dim: 1024\n", encoding="utf-8")
    global_config = home / ".simple-ci" / "config.yaml"
    global_config.write_text("embedding:\n  dim: 768\n", encoding="utf-8")

    found = configfile.find_config_file(workspace, home=home)

    assert found == global_config


def test_global_config_is_the_only_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_CONFIG", raising=False)
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    (home / ".simple-ci").mkdir(parents=True)
    global_config = home / ".simple-ci" / "config.yaml"
    global_config.write_text("embedding:\n  dim: 768\n", encoding="utf-8")

    assert configfile.find_config_file(workspace, home=home) == global_config
    assert configfile.config_paths(workspace, home=home) == (global_config,)


def test_config_paths_never_returns_a_local_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_CONFIG", raising=False)
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    local = workspace / ".simple-ci" / "config.yaml"
    local.parent.mkdir(parents=True)
    local.write_text("vector_store: qdrant\n", encoding="utf-8")

    assert configfile.config_paths(workspace, home=home) == ()


def test_layered_config_deep_merges_and_local_wins(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    local_path = tmp_path / "local.yaml"
    configfile.write_config(
        {
            "embedding": {
                "base_url": "http://global:8080",
                "model": "embeddinggemma-2",
                "dim": 768,
                "service": {"container": "simple-ci-embed"},
            },
            "vector_store": "qdrant",
            "sweep_seconds": 10,
        },
        global_path,
    )
    configfile.write_config(
        {"embedding": {"dim": 1024}, "vector_store": "faiss"}, local_path
    )

    merged = configfile.load_layered_config((global_path, local_path))

    assert merged["embedding"]["base_url"] == "http://global:8080"
    assert merged["embedding"]["model"] == "embeddinggemma-2"
    assert merged["embedding"]["dim"] == 1024
    assert merged["embedding"]["service"] == {"container": "simple-ci-embed"}
    assert merged["vector_store"] == "faiss"
    assert merged["sweep_seconds"] == 10


def test_local_null_clears_a_global_value(tmp_path: Path) -> None:
    global_path = tmp_path / "global.yaml"
    local_path = tmp_path / "local.yaml"
    configfile.write_config({"embedding": {"api_key": "secret"}}, global_path)
    configfile.write_config({"embedding": {"api_key": None}}, local_path)

    merged = configfile.load_layered_config((global_path, local_path))

    assert merged["embedding"]["api_key"] is None


def test_model_defaults_supply_code_prompts(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.yaml"
    configfile.write_config(
        {"embedding": {"model": "embeddinggemma-2", "dim": 768}}, path
    )
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(path))
    for name in (
        "EMBED_MODEL",
        "EMBED_DIM",
        "EMBED_QUERY_PREFIX",
        "EMBED_DOCUMENT_PREFIX",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()

    assert settings.embed_query_prefix == model_prompts.GEMMA_CODE_QUERY
    assert settings.embed_document_prefix == model_prompts.GEMMA_CODE_DOCUMENT
    assert settings.embed_fingerprint


def test_qwen_gets_a_query_only_instruction(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.yaml"
    configfile.write_config(
        {"embedding": {"model": "Qwen3-Embedding-0.6B", "dim": 1024}}, path
    )
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(path))
    for name in (
        "EMBED_MODEL",
        "EMBED_DIM",
        "EMBED_QUERY_PREFIX",
        "EMBED_DOCUMENT_PREFIX",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()

    assert settings.embed_query_prefix == model_prompts.QWEN_CODE_QUERY
    assert settings.embed_document_prefix is None
    # The chunker profile is part of the vector identity even when documents
    # are embedded raw, so a chunking change still invalidates stored vectors.
    assert settings.embed_fingerprint


def test_explicit_empty_prompt_disables_defaults(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.yaml"
    configfile.write_config(
        {
            "embedding": {
                "model": "embeddinggemma-2",
                "query_prefix": "",
                "document_prefix": "",
            }
        },
        path,
    )
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(path))
    for name in (
        "EMBED_MODEL",
        "EMBED_QUERY_PREFIX",
        "EMBED_DOCUMENT_PREFIX",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()

    assert settings.embed_query_prefix is None
    assert settings.embed_document_prefix is None
    assert settings.embed_fingerprint


def test_bad_prompt_placeholders_raise(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.yaml"
    configfile.write_config(
        {
            "embedding": {
                "model": "embeddinggemma-2",
                "document_prefix": "title: {filename}",
            }
        },
        path,
    )
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(path))
    for name in ("EMBED_DOCUMENT_PREFIX",):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ConfigError, match="document_prefix"):
        load_settings()


def test_missing_config_returns_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_CONFIG", raising=False)
    assert configfile.find_config_file(tmp_path, home=tmp_path / "home") is None


def test_explicit_path_overrides_discovery(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".simple-ci").mkdir()
    (workspace / ".simple-ci" / "config.yaml").write_text(
        "embedding:\n  dim: 1024\n", encoding="utf-8"
    )
    explicit = tmp_path / "elsewhere.yaml"
    explicit.write_text("embedding:\n  dim: 512\n", encoding="utf-8")
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(explicit))

    assert configfile.find_config_file(workspace) == explicit


def test_none_disables_discovery(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".simple-ci").mkdir(parents=True)
    (workspace / ".simple-ci" / "config.yaml").write_text(
        "embedding:\n  dim: 1024\n", encoding="utf-8"
    )
    monkeypatch.setenv("SIMPLE_CI_CONFIG", "none")

    assert configfile.find_config_file(workspace) is None


def test_empty_file_is_an_empty_mapping(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("", encoding="utf-8")
    assert configfile.load_config(path) == {}


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("embedding: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        configfile.load_config(path)


def test_non_mapping_config_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        configfile.load_config(path)


def test_file_values_reach_settings(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = tmp_path / "config.yaml"
    configfile.write_config(
        {
            "version": 1,
            "embedding": {
                "base_url": "http://example.test:9000",
                "model": "custom-embed",
                "dim": 1024,
                "api_key": "file-key",
                "timeout_s": 22.5,
            },
            "qdrant": {"url": "http://example.test:6333"},
            "sweep_seconds": 10,
            "debounce_ms": 250,
        },
        path,
    )
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(path))
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    for name in (
        "EMBED_BASE_URL",
        "EMBED_MODEL",
        "EMBED_DIM",
        "EMBED_API_KEY",
        "EMBED_TIMEOUT_S",
        "QDRANT_URL",
        "QDRANT_COLLECTION",
        "SWEEP_SECONDS",
        "DEBOUNCE_MS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()

    assert settings.config_source == path
    assert settings.embed_base_url == "http://example.test:9000"
    assert settings.embed_model == "custom-embed"
    assert settings.embed_dim == 1024
    assert settings.embed_api_key == "file-key"
    assert settings.embed_timeout_s == 22.5
    assert settings.qdrant_url == "http://example.test:6333"
    assert "_1024_" in settings.qdrant_collection
    assert settings.qdrant_collection.endswith(settings.embed_fingerprint)
    assert settings.sweep_seconds == 10.0
    assert settings.debounce_ms == 250


def test_env_overrides_file_values(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.yaml"
    configfile.write_config({"embedding": {"dim": 1024, "api_key": "file-key"}}, path)
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(path))
    monkeypatch.setenv("EMBED_DIM", "768")
    monkeypatch.setenv("EMBED_API_KEY", "env-key")

    settings = load_settings()

    assert settings.embed_dim == 768
    assert settings.embed_api_key == "env-key"


def test_managed_services_are_parsed(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.yaml"
    configfile.write_config(
        {
            "embedding": {
                "service": {
                    "container": "simple-ci-embed",
                    "compose_file": "~/.simple-ci/docker-compose.yml",
                    "compose_service": "embed",
                    "startup_timeout_s": 30,
                }
            },
            "qdrant": {"service": {"container": "simple-ci-qdrant"}},
        },
        path,
    )
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(path))

    settings = load_settings()

    embedding = settings.embedding_service
    assert embedding is not None
    assert embedding.container == "simple-ci-embed"
    assert (
        embedding.compose_file == Path("~/.simple-ci/docker-compose.yml").expanduser()
    )
    assert embedding.compose_service == "embed"
    assert embedding.startup_timeout_s == 30.0
    qdrant = settings.qdrant_service
    assert qdrant is not None
    assert qdrant.container == "simple-ci-qdrant"
    assert qdrant.compose_file is None


def test_wrong_value_type_raises(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.yaml"
    configfile.write_config({"embedding": {"base_url": 42}}, path)
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(path))

    with pytest.raises(ConfigError, match="embedding.base_url"):
        load_settings()


def test_write_config_is_round_trippable(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.yaml"
    data = {"version": 1, "embedding": {"dim": 768, "api_key": None}}
    configfile.write_config(data, path)

    assert configfile.load_config(path) == data
    assert path.read_text(encoding="utf-8").startswith("version: 1")
