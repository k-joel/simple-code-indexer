#!/usr/bin/env python3
"""MCP launcher used by harness entries.

Runs inside the installed copy (``%APPDATA%/simple-code-indexer`` on Windows).
It pulls the latest code, re-syncs the virtualenv when HEAD moved, and then
starts the MCP server **without changing the working directory** — the server
uses the caller's cwd as the workspace to index.

The pull and sync are deliberately fail-soft: an offline machine, a missing
``git``/``uv``, or a dirty tree must never stop the indexer from serving.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_GIT_TIMEOUT_S = 20.0
_SYNC_TIMEOUT_S = 300.0
_MAX_ERROR_CHARS = 500
_CREATE_NO_WINDOW = 0x08000000


def _run(argv: list[str], *, timeout: float) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            argv,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            # A harness that spawns us without a console would otherwise get a
            # visible console window for every git/uv child (run_server.py is
            # itself often launched with pythonw).
            creationflags=_CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _report(action: str, result: subprocess.CompletedProcess[str] | None) -> None:
    if result is None:
        print(f"simple-code-indexer: {action} could not run", file=sys.stderr)
        return
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    if len(detail) > _MAX_ERROR_CHARS:
        detail = detail[: _MAX_ERROR_CHARS - 1] + "…"
    print(
        f"simple-code-indexer: {action} failed (exit {result.returncode})"
        + (f": {detail}" if detail else ""),
        file=sys.stderr,
    )


def _head() -> str | None:
    result = _run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], timeout=10.0)
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _pull_enabled() -> bool:
    value = os.environ.get("SIMPLE_CI_GIT_PULL", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _git_pull() -> None:
    if not _pull_enabled():
        return
    if shutil.which("git") is None:
        return
    _report(
        "git pull",
        _run(
            [
                "git",
                "-C",
                str(ROOT),
                "pull",
                "--ff-only",
                "--autostash",
                "--quiet",
            ],
            timeout=_GIT_TIMEOUT_S,
        ),
    )


def _uv_sync() -> None:
    uv = shutil.which("uv")
    if uv is None:
        print(
            "simple-code-indexer: uv not found; keeping the existing environment",
            file=sys.stderr,
        )
        return
    _report(
        "uv sync",
        _run([uv, "sync", "--project", str(ROOT), "--quiet"], timeout=_SYNC_TIMEOUT_S),
    )


def main() -> int:
    # Two `git rev-parse` spawns per launch are pointless when pulling is off:
    # HEAD cannot move between them.
    if _pull_enabled():
        before = _head()
        _git_pull()
        if before != _head():
            _uv_sync()
    from simple_code_indexer.server import main as server_main

    server_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
