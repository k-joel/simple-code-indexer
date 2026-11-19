"""Reader-side spawn behaviour: one daemon at a time, and windowless on Windows."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.registry import get_registry
from simple_code_indexer.sidecar import ReaderSession, client


def _settings(workspace: Path) -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=workspace,
        index_db_path=workspace / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_test",
        embed_base_url="http://127.0.0.1:9",
        embed_model="test-model",
        embed_dim=8,
        embed_timeout_s=1.0,
        sweep_seconds=0.0,
        debounce_ms=100,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        vector_store="faiss",
        mode="sidecar",
        idle_grace_s=1.0,
        heartbeat_s=0.5,
    )


class _Child:
    def __init__(self, alive: bool) -> None:
        self.pid = 4242
        self._alive = alive

    def poll(self) -> int | None:
        return None if self._alive else 0

    def wait(self) -> int:
        return 0


def test_spawn_if_needed_waits_for_the_running_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = ReaderSession(_settings(tmp_path))
    spawned: list[bool] = []
    monkeypatch.setattr(session, "_spawn_daemon", lambda: spawned.append(True))
    monkeypatch.setattr(client.paths, "read_ready", lambda _settings: None)

    session._children = cast(Any, [_Child(alive=True)])
    session._spawn_if_needed()
    assert spawned == []

    session._children = cast(Any, [_Child(alive=False)])
    session._spawn_if_needed()
    assert spawned == [True]


def test_spawn_daemon_uses_a_windowless_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = ReaderSession(_settings(tmp_path))
    calls: list[dict[str, Any]] = []
    child = _Child(alive=True)

    def _popen(_command: list[str], **kwargs: Any) -> _Child:
        calls.append(kwargs)
        return child

    monkeypatch.setattr(client.subprocess, "Popen", _popen)
    monkeypatch.setattr(client.sys, "platform", "win32")

    session._spawn_daemon()

    assert calls
    flags = calls[0]["creationflags"]
    assert flags & client._CREATE_NO_WINDOW
    assert flags & client._CREATE_NEW_PROCESS_GROUP


def test_daemon_command_skips_the_windows_venv_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_packages = tmp_path / "site-packages"
    monkeypatch.setattr(client.sys, "platform", "win32")
    monkeypatch.setattr(
        client.sys, "executable", str(tmp_path / "venv" / "pythonw.exe")
    )
    monkeypatch.setattr(
        client.sys, "_base_executable", str(tmp_path / "base" / "pythonw.exe")
    )
    monkeypatch.setattr(client.sys, "path", [str(site_packages)])

    command = client._daemon_command(tmp_path)

    assert command[0] == str(tmp_path / "base" / "pythonw.exe")
    assert command[1] == "-c"
    assert repr(str(site_packages)) in command[2]
    assert command[3:] == ["--workspace", str(tmp_path)]


def test_daemon_command_falls_back_to_the_venv_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = str(tmp_path / "venv" / "pythonw.exe")
    monkeypatch.setattr(client.sys, "platform", "win32")
    monkeypatch.setattr(client.sys, "executable", executable)
    monkeypatch.setattr(client.sys, "_base_executable", executable)

    command = client._daemon_command(tmp_path)

    assert command == [
        executable,
        "-m",
        "simple_code_indexer.sidecar.daemon",
        "--workspace",
        str(tmp_path),
    ]
