"""Discovery files and the local endpoint for the per-workspace sidecar.

The ready file and token live in `<workspace>/.simple-ci/run/`, which is already
ignored by the watcher and by `.gitignore` conventions. The control endpoint
itself lives outside the workspace: a named pipe on Windows, a user-private
Unix socket on POSIX.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simple_code_indexer.config import Settings, normalize_workspace_path

PROTOCOL_VERSION = 1
READY_FILENAME = "daemon.json"
TOKEN_FILENAME = "daemon.token"
SPAWN_LOCK_FILENAME = "daemon.spawn.lock"
RUN_DIRNAME = "run"


@dataclass(frozen=True, slots=True)
class StatePaths:
    ready: Path
    token: Path
    spawn_lock: Path


def state_paths(settings: Settings) -> StatePaths:
    run = settings.index_db_path.parent / RUN_DIRNAME
    return StatePaths(
        ready=run / READY_FILENAME,
        token=run / TOKEN_FILENAME,
        spawn_lock=run / SPAWN_LOCK_FILENAME,
    )


def endpoint(settings: Settings) -> str:
    """Deterministic local IPC address for one canonical workspace."""
    digest = hashlib.sha256(
        normalize_workspace_path(settings.workspace_root).encode("utf-8")
    ).hexdigest()[:16]
    if sys.platform == "win32":
        return rf"\\.\pipe\simple-code-indexer-{digest}"
    base = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    user = hashlib.sha256(str(Path.home()).encode("utf-8")).hexdigest()[:8]
    directory = base / f"simple-code-indexer-{user}"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return str(directory / f"{digest}.sock")


def _private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def write_ready(settings: Settings, *, pid: int, endpoint: str) -> Path:
    """Publish the endpoint only after the daemon is ready to serve."""
    paths = state_paths(settings)
    paths.ready.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "protocol": PROTOCOL_VERSION,
        "pid": pid,
        "endpoint": endpoint,
        "workspace": str(settings.workspace_root.resolve()),
    }
    temporary = paths.ready.with_name(paths.ready.name + ".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    _private(temporary)
    os.replace(temporary, paths.ready)
    return paths.ready


def read_ready(settings: Settings) -> dict[str, Any] | None:
    """Return the published endpoint, or None when absent/unreadable/stale-format."""
    try:
        payload = json.loads(state_paths(settings).ready.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("protocol") != PROTOCOL_VERSION:
        return None
    if not isinstance(payload.get("pid"), int) or payload["pid"] <= 0:
        return None
    if not isinstance(payload.get("endpoint"), str) or not payload["endpoint"]:
        return None
    return payload


def clear_ready(settings: Settings) -> None:
    try:
        state_paths(settings).ready.unlink(missing_ok=True)
    except OSError:
        pass


def write_token(settings: Settings, token: str) -> Path:
    paths = state_paths(settings)
    paths.token.parent.mkdir(parents=True, exist_ok=True)
    paths.token.write_text(token, encoding="utf-8")
    _private(paths.token)
    return paths.token


def read_token(settings: Settings) -> str | None:
    try:
        token = state_paths(settings).token.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def clear_token(settings: Settings) -> None:
    try:
        state_paths(settings).token.unlink(missing_ok=True)
    except OSError:
        pass
