"""The env-var seam: every knob is prefixed, legacy names still work (ADR-024)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from simple_code_indexer import env


def test_names_are_prefixed() -> None:
    assert env.name("LOG_LEVEL") == "SIMPLE_CI_LOG_LEVEL"
    # already-prefixed names are returned unchanged, not double-prefixed
    assert env.name("SIMPLE_CI_LOG_LEVEL") == "SIMPLE_CI_LOG_LEVEL"


def test_the_prefixed_name_is_read_first(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLE_CI_LOG_LEVEL", "error")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    assert env.get("LOG_LEVEL") == "error"


def test_a_legacy_name_still_works_and_warns_once(monkeypatch, caplog) -> None:
    monkeypatch.delenv("SIMPLE_CI_LOG_LEVEL", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "info")
    env._warned.clear()

    with caplog.at_level(logging.WARNING):
        assert env.get("LOG_LEVEL") == "info"
        assert env.get("LOG_LEVEL") == "info"

    warnings = [line for line in caplog.text.splitlines() if "deprecated" in line]
    assert len(warnings) == 1
    assert "SIMPLE_CI_LOG_LEVEL" in warnings[0]


def test_unset_returns_none(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    assert env.get("LOG_LEVEL") is None


def test_an_empty_value_is_not_none(monkeypatch) -> None:
    """Several knobs treat empty as "disabled", so the caller must see it."""
    monkeypatch.setenv("SIMPLE_CI_EMBED_QUERY_PREFIX", "")

    assert env.get("EMBED_QUERY_PREFIX") == ""


def test_the_sidecar_passes_the_index_db_as_an_argument(tmp_path: Path) -> None:
    """A spawned daemon is production: it gets flags, not env (ADR-024)."""
    from simple_code_indexer.sidecar import client

    argv = client._daemon_command(tmp_path, tmp_path / "index.db")

    assert "--workspace" in argv
    assert argv[argv.index("--index-db") + 1] == str(tmp_path / "index.db")


def test_an_invalid_prefixed_value_names_the_prefixed_variable(
    tmp_path: Path, monkeypatch
) -> None:
    from simple_code_indexer import config

    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(tmp_path / "none.yaml"))
    monkeypatch.setenv("SIMPLE_CI_LOG_LEVEL", "verbose")
    with pytest.raises(config.ConfigError, match="SIMPLE_CI_LOG_LEVEL"):
        config.load_settings(cli_workspace=tmp_path)
