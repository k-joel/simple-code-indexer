"""Sidecar daemon lifecycle: spawn, register, grace exit, crash respawn."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.registry import get_registry
from simple_code_indexer.sidecar import ReaderSession, paths
from simple_code_indexer.workspace_lock import WorkspaceLock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"


def _settings(
    workspace: Path, *, idle_grace_s: float = 1.0, heartbeat_s: float = 0.5
) -> Settings:
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
        idle_grace_s=idle_grace_s,
        heartbeat_s=heartbeat_s,
    )


def _env(monkeypatch: pytest.MonkeyPatch, workspace: Path, *, grace: float) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("INDEX_DB", str(workspace / ".simple-ci" / "index.db"))
    monkeypatch.setenv("SIMPLE_CI_MODE", "sidecar")
    monkeypatch.setenv("IDLE_GRACE_S", str(grace))
    monkeypatch.setenv("HEARTBEAT_S", "0.5")
    monkeypatch.setenv("EMBED_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EMBED_TIMEOUT_S", "1")
    monkeypatch.setenv("SWEEP_SECONDS", "0")
    monkeypatch.setenv("PREFETCH_GRAMMARS", "0")
    monkeypatch.setenv("SIMPLE_CI_PARENT_WATCH", "0")
    existing = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", str(SRC) + (os.pathsep + existing if existing else "")
    )


def _kill_daemon(settings: Settings) -> None:
    ready = paths.read_ready(settings)
    if ready is not None:
        pid = int(ready["pid"])
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    paths.clear_ready(settings)
    paths.clear_token(settings)


def _wait_until(predicate, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {label}")


def _lease_free(settings: Settings) -> bool:
    lock = WorkspaceLock(settings.index_db_path)
    if not lock.acquire():
        return False
    lock.release()
    return True


@pytest.fixture(autouse=True)
def _kill_leftover_daemon(tmp_path: Path):
    """A failed test must not leave a detached daemon behind."""
    yield
    _kill_daemon(_settings(tmp_path))


def _start(settings: Settings) -> ReaderSession:
    session = ReaderSession(settings)
    session.start()
    deadline = time.monotonic() + 20.0
    while not session.connected and time.monotonic() < deadline:
        time.sleep(0.1)
    assert session.connected, "the reader never registered with a daemon"
    return session


def _writer_pid(session: ReaderSession) -> int:
    status = session.status(5.0)
    assert status is not None, "no daemon status"
    pid = status.get("writer_pid")
    assert isinstance(pid, int)
    return int(pid)


def test_daemon_registers_then_exits_after_grace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, tmp_path, grace=1.0)
    settings = _settings(tmp_path, idle_grace_s=1.0)
    session = _start(settings)
    try:
        ready = paths.read_ready(settings)
        assert ready is not None
        assert _writer_pid(session) == ready["pid"]
        assert _lease_free(settings) is False
        status = session.status(5.0)
        assert status is not None
        assert status["sessions"] == 1
        assert (tmp_path / ".simple-ci" / "log" / "writer.log").is_file()
    finally:
        session.close()

    _wait_until(
        lambda: paths.read_ready(settings) is None,
        timeout=20.0,
        label="the daemon to exit after the grace period",
    )
    _wait_until(
        lambda: _lease_free(settings), timeout=20.0, label="the writer lease release"
    )


def test_a_new_session_during_grace_keeps_the_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, tmp_path, grace=30.0)
    settings = _settings(tmp_path, idle_grace_s=30.0)
    first = _start(settings)
    writer_pid = _writer_pid(first)
    first.close()

    time.sleep(0.5)
    second = _start(settings)
    try:
        assert _writer_pid(second) == writer_pid
        assert paths.read_ready(settings) is not None
    finally:
        second.close()
        _kill_daemon(settings)


def test_a_killed_daemon_is_respawned_by_the_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, tmp_path, grace=30.0)
    settings = _settings(tmp_path, idle_grace_s=30.0)
    session = _start(settings)
    try:
        first_pid = _writer_pid(session)
        _kill_daemon(settings)

        _wait_until(
            lambda: (
                (ready := paths.read_ready(settings)) is not None
                and ready["pid"] != first_pid
                and session.connected
            ),
            timeout=40.0,
            label="a replacement daemon",
        )
        assert _writer_pid(session) != first_pid
    finally:
        session.close()
        _kill_daemon(settings)


def test_concurrent_readers_share_one_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, tmp_path, grace=30.0)
    settings = _settings(tmp_path, idle_grace_s=30.0)
    sessions: list[ReaderSession] = []
    spawned: list[int] = []
    spawned_lock = threading.Lock()
    original_spawn = ReaderSession._spawn_daemon

    def counting_spawn(session: ReaderSession) -> subprocess.Popen[Any] | None:
        process = original_spawn(session)
        if process is not None:
            with spawned_lock:
                spawned.append(process.pid)
        return process

    monkeypatch.setattr(ReaderSession, "_spawn_daemon", counting_spawn)

    def start_one() -> ReaderSession:
        return _start(settings)

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            sessions = list(pool.map(lambda _: start_one(), range(3)))
        assert len(spawned) == 1, f"readers spawned duplicate daemons: {spawned}"
        writer_pids = {_writer_pid(session) for session in sessions}
        assert len(writer_pids) == 1
        status = sessions[0].status(5.0)
        assert status is not None
        assert status["sessions"] == 3
    finally:
        for session in sessions:
            session.close()
        _kill_daemon(settings)
