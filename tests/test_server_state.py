"""Deferred workspace binding: roots -> harness -> cwd (ADR-018)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar, NoReturn

import pytest

from simple_code_indexer import logging_setup, mcp_roots, server
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.registry import get_registry


def _settings(workspace: Path, *, mode: str = "sidecar") -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=workspace,
        index_db_path=workspace / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_test",
        embed_base_url="http://localhost:1",
        embed_model="test-model",
        embed_dim=8,
        embed_timeout_s=15.0,
        sweep_seconds=0.0,
        debounce_ms=400,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        vector_store="sqlite-vec",
        mode=mode,
    )


class FakeReader:
    instances: ClassVar[list[FakeReader]] = []

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.started = False
        self.closes = 0
        FakeReader.instances.append(self)

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closes += 1


@pytest.fixture(autouse=True)
def _no_log_file(monkeypatch) -> None:
    monkeypatch.setattr(logging_setup, "configure_file", lambda *a, **k: None)
    monkeypatch.setattr(logging_setup, "log_startup", lambda *a, **k: None)
    FakeReader.instances.clear()


def test_ensure_started_resolves_the_workspace_once(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "published"
    workspace.mkdir()
    settings = _settings(workspace)
    probes: list[object] = []
    loads: list[Path | None] = []

    async def fake_probe(session: object) -> Path:
        probes.append(session)
        return workspace

    def fake_load(
        *, mcp_workspace: Path | None = None, cli_workspace: Path | None = None
    ) -> Settings:
        loads.append(mcp_workspace)
        return settings

    monkeypatch.setattr(mcp_roots, "first_workspace", fake_probe)
    monkeypatch.setattr(server, "load_settings", fake_load)
    monkeypatch.setattr(server, "ReaderSession", FakeReader)

    state = server.ServerState()
    session = object()
    asyncio.run(state.ensure_started(session))
    asyncio.run(state.ensure_started(session))

    assert probes == [session]
    assert loads == [workspace]
    assert state.settings is settings
    assert state.role == "reader"
    assert isinstance(state.session, FakeReader)
    assert state.session.started
    assert len(FakeReader.instances) == 1

    state.cleanup_once()
    state.cleanup_once()
    assert FakeReader.instances[0].closes == 1


def test_a_workspace_pin_skips_the_roots_probe(tmp_path: Path, monkeypatch) -> None:
    """`serve --workspace <dir>` answers the question before the handshake."""
    workspace = tmp_path / "pinned"
    workspace.mkdir()
    settings = _settings(workspace)
    probes: list[object] = []
    loads: list[object] = []

    async def fake_probe(session: object) -> Path:
        probes.append(session)
        return workspace

    def fake_load(
        *, mcp_workspace: Path | None = None, cli_workspace: Path | None = None
    ) -> Settings:
        loads.append((mcp_workspace, cli_workspace))
        return settings

    monkeypatch.setattr(mcp_roots, "first_workspace", fake_probe)
    monkeypatch.setattr(server, "load_settings", fake_load)
    monkeypatch.setattr(server, "ReaderSession", FakeReader)

    state = server.ServerState(workspace=workspace)
    asyncio.run(state.ensure_started(object()))

    assert probes == []
    assert loads == [(None, workspace)]


def test_ensure_started_refuses_an_inferred_home_workspace(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(home)
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)

    async def no_roots(session: object) -> None:
        return None

    monkeypatch.setattr(mcp_roots, "first_workspace", no_roots)
    exits: list[int] = []

    def fake_exit(code: int) -> NoReturn:
        exits.append(code)
        raise SystemExit(code)

    state = server.ServerState(exit=fake_exit)
    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(state.ensure_started(object()))

    assert excinfo.value.code == 1
    assert exits == [1]
    assert state.settings is None
    assert "refusing to index it" in caplog.text
