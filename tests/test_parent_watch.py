"""Harness lifecycle watchdog: the server must not outlive its launcher (ISS-3)."""

from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from simple_code_indexer import parent_watch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
FAKE_HARNESS = Path(__file__).resolve().parent / "fixtures" / "fake_harness.py"

_ENV_EXCLUDES = (
    "WORKSPACE_ROOT",
    "INDEX_DB",
    "SIMPLE_CI_CONFIG",
    "SIMPLE_CI_PARENT_WATCH",
)


class FakeProcess:
    """Duck-typed ProcessRef so the watchdog loop needs no real processes."""

    def __init__(self, pid: int, alive: bool = True) -> None:
        self.pid = pid
        self.name = "fake"
        self.is_alive = alive
        self.closed = False

    def alive(self) -> bool:
        return self.is_alive

    def close(self) -> None:
        self.closed = True

    def describe(self) -> str:
        return f"{self.pid} ({self.name})"


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _wait_for(predicate: Callable[[], bool], timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {label}")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def test_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_PARENT_WATCH", raising=False)
    assert parent_watch.enabled()


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_can_be_disabled(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("SIMPLE_CI_PARENT_WATCH", value)
    assert not parent_watch.enabled()


def test_ancestors_are_live_processes() -> None:
    for process in parent_watch.ancestors():
        assert process.alive(), process.describe()


def test_watched_process_reports_exit() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        watched = parent_watch.watch_process(process.pid, "sleeper")
        assert watched is not None
        assert watched.alive()
    finally:
        _terminate_tree(process)
    _wait_for(lambda: not watched.alive(), timeout=10.0, label="process exit")
    watched.close()


def test_watchdog_returns_the_dead_ancestor() -> None:
    alive = FakeProcess(1)
    dead = FakeProcess(2, alive=False)
    watchdog = parent_watch.ParentWatchdog(interval_s=0.01, processes=[alive, dead])
    assert watchdog.dead() is dead
    assert asyncio.run(watchdog.wait()) is dead
    watchdog.close()
    assert alive.closed and dead.closed


def test_server_exits_when_the_harness_process_dies(tmp_path: Path) -> None:
    """The stdin pipe stays open; only the watchdog can end this server."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    pid_file = tmp_path / "harness.pid"

    env = {
        name: value for name, value in os.environ.items() if name not in _ENV_EXCLUDES
    }
    env["SIMPLE_CI_CONFIG"] = "none"
    env["VECTOR_STORE"] = "faiss"
    env["PREFETCH_GRAMMARS"] = "0"
    env["EMBED_BASE_URL"] = "http://127.0.0.1:9"
    env["EMBED_TIMEOUT_S"] = "1"
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + pythonpath if pythonpath else "")

    harness = subprocess.Popen(
        [
            sys.executable,
            str(FAKE_HARNESS),
            str(pid_file),
            str(workspace),
            sys.executable,
            "-m",
            "simple_code_indexer.server",
        ],
        cwd=str(workspace),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log_file = workspace / ".simple-ci" / "log" / "sci.log"
    server_watch: parent_watch.WatchedProcess | None = None
    try:
        _wait_for(
            lambda: "serving on stdio" in _read(log_file),
            timeout=60.0,
            label="server serving",
        )
        log = _read(log_file)
        match = re.search(r"starting \(pid=(\d+),", log)
        assert match is not None, log
        server_watch = parent_watch.watch_process(int(match.group(1)), "server")
        assert server_watch is not None, "server process is already gone"
        assert server_watch.alive()
        assert "parent watchdog: watching" in log

        os.kill(int(pid_file.read_text(encoding="utf-8")), signal.SIGTERM)

        _wait_for(
            lambda: "shutting down so the server cannot outlive" in _read(log_file),
            timeout=20.0,
            label="watchdog shutdown",
        )
        _wait_for(
            lambda: not server_watch.alive(),
            timeout=20.0,
            label="server exit",
        )
        final = _read(log_file)
        assert "workspace lock released" in final
        assert "shutting down after" in final
    finally:
        if server_watch is not None:
            server_watch.close()
        _terminate_tree(harness)
        if harness.stdin is not None:
            harness.stdin.close()
