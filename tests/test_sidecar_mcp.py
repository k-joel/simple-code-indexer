"""ISS-11: two MCP servers in one workspace share one sidecar writer."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mcp_client import StdioServer

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
READY_PATH = Path(".simple-ci") / "run" / "daemon.json"

_ENV_EXCLUDES = (
    "SIMPLE_CI_WORKSPACE_ROOT",
    "SIMPLE_CI_INDEX_DB",
    "SIMPLE_CI_VECTOR_STORE",
    "SIMPLE_CI_FAISS_PATH",
    "SIMPLE_CI_QDRANT_URL",
    "SIMPLE_CI_QDRANT_COLLECTION",
    "SIMPLE_CI_CONFIG",
    "SIMPLE_CI_MODE",
    "SIMPLE_CI_IDLE_GRACE_S",
    "SIMPLE_CI_HEARTBEAT_S",
    "SIMPLE_CI_EMBED_BASE_URL",
    "SIMPLE_CI_EMBED_TIMEOUT_S",
    "SIMPLE_CI_SWEEP_SECONDS",
    "SIMPLE_CI_PARENT_WATCH",
    "SIMPLE_CI_PREFETCH_GRAMMARS",
)


def _env(workspace: Path) -> dict[str, str]:
    env = {
        name: value for name, value in os.environ.items() if name not in _ENV_EXCLUDES
    }
    env["SIMPLE_CI_CONFIG"] = "none"
    env["SIMPLE_CI_MODE"] = "sidecar"
    env["SIMPLE_CI_WORKSPACE_ROOT"] = str(workspace)
    env["SIMPLE_CI_INDEX_DB"] = str(workspace / ".simple-ci" / "index.db")
    env["SIMPLE_CI_VECTOR_STORE"] = "faiss"
    env["SIMPLE_CI_EMBED_BASE_URL"] = "http://127.0.0.1:9"
    env["SIMPLE_CI_EMBED_TIMEOUT_S"] = "1"
    env["SIMPLE_CI_SWEEP_SECONDS"] = "0"
    env["SIMPLE_CI_PREFETCH_GRAMMARS"] = "0"
    env["SIMPLE_CI_PARENT_WATCH"] = "0"
    env["SIMPLE_CI_IDLE_GRACE_S"] = "3"
    env["SIMPLE_CI_HEARTBEAT_S"] = "0.5"
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + existing if existing else "")
    return env


def _read_ready(workspace: Path) -> dict[str, object] | None:
    try:
        payload = json.loads((workspace / READY_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _kill_daemon(workspace: Path) -> None:
    payload = _read_ready(workspace)
    pid = payload.get("pid") if payload else None
    if isinstance(pid, int) and pid > 0:
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
    for name in ("daemon.json", "daemon.token"):
        try:
            (workspace / ".simple-ci" / "run" / name).unlink(missing_ok=True)
        except OSError:
            pass


def _wait_until(predicate, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {label}")


@pytest.fixture(autouse=True)
def _kill_leftover_daemon(tmp_path: Path):
    """A failed test must not leave a detached daemon behind."""
    yield
    _kill_daemon(tmp_path / "workspace")


def test_two_harnesses_share_one_writer_and_survive_a_close(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "alpha.cpp").write_text(
        "int sharedSymbol() { return 42; }\n", encoding="utf-8"
    )
    env = _env(workspace)
    first = StdioServer(workspace, env=env)
    second = StdioServer(workspace, env=env)

    def ready(status: dict) -> bool:
        return bool(
            status.get("index_ready")
            and status.get("sessions") == 2
            and status.get("writer_pid")
        )

    try:
        first.start()
        second.start()

        first_status = first.poll("get_status", {}, ready, timeout=90.0)
        second_status = second.poll("get_status", {}, ready, timeout=90.0)

        assert first_status["role"] == "reader"
        assert second_status["role"] == "reader"
        assert first_status["writer_pid"] == second_status["writer_pid"]
        assert first_status["sessions"] == 2
        assert first_status["watcher_alive"] is True
        log_dir = workspace / ".simple-ci" / "log"
        assert (log_dir / "reader.log").is_file()
        assert (log_dir / "writer.log").is_file()
        assert first_status["log_file"].endswith("reader.log")
        assert first_status["writer_log_file"].endswith("writer.log")

        # Both readers expose the full tool surface.
        first.poll(
            "symbol_lookup",
            {"symbol": "sharedSymbol"},
            lambda payload: "line" in payload,
            timeout=90.0,
        )
        second.poll(
            "symbol_lookup",
            {"symbol": "sharedSymbol"},
            lambda payload: "line" in payload,
            timeout=90.0,
        )
        lexical = first.poll(
            "search_code",
            {"query": "sharedSymbol"},
            lambda payload: bool(payload.get("hits")),
            timeout=90.0,
        )
        assert lexical["source"] == "lexical"

        # Closing A must not disturb B.
        first.close()
        second.poll(
            "get_status", {}, lambda status: status.get("sessions") == 1, timeout=30.0
        )
        assert "line" in second.call("symbol_lookup", {"symbol": "sharedSymbol"})
        assert second.call("get_status", {})["writer_ok"] is True
    finally:
        first.close()
        second.close()

    # The daemon exits after the last session plus the grace period.
    _wait_until(
        lambda: _read_ready(workspace) is None,
        timeout=30.0,
        label="the daemon to exit after the last session",
    )

    # A new server starts a fresh daemon and the index is still searchable.
    third = StdioServer(workspace, env=env)
    try:
        third.start()
        status = third.poll(
            "get_status",
            {},
            lambda payload: bool(
                payload.get("writer_pid") and payload.get("sessions") == 1
            ),
            timeout=90.0,
        )
        assert status["role"] == "reader"
        assert "line" in third.poll(
            "symbol_lookup",
            {"symbol": "sharedSymbol"},
            lambda payload: "line" in payload,
            timeout=90.0,
        )
    finally:
        third.close()
        _kill_daemon(workspace)
