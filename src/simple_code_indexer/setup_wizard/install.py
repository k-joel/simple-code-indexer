"""Install the repo into a stable per-user directory.

Harness entries launch ``run_server.py`` through ``uv run --project <install>
--no-sync``, so they survive deleting the original checkout and can self-update
with ``git pull`` on every launch.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from simple_code_indexer.setup_wizard.provision import Runner

APP_DIRNAME = "simple-code-indexer"
LAUNCHER_FILENAME = "run_server.py"

_IGNORED: tuple[str, ...] = (
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".simple-ci",
    ".index",
    "artifacts",
    ".mimocode",
    ".commandcode",
    ".kilo",
    "build",
    "dist",
    "*.egg-info",
    "*.pyc",
)


@dataclass(frozen=True, slots=True)
class InstallResult:
    root: Path
    launcher: Path
    uv: str = "uv"
    platform: str = sys.platform

    @property
    def server_command(self) -> list[str]:
        """Launch the installed copy, preserving the caller's cwd.

        On Windows the venv ``pythonw.exe`` is used directly: ``uv.exe`` and
        ``python.exe`` are console applications, and a GUI harness that spawns
        one without ``CREATE_NO_WINDOW`` gets a visible console window that
        lives as long as the server. ``pythonw`` is windowless and still speaks
        MCP over the inherited stdio pipes.
        """
        if self.platform == "win32":
            pythonw = self.root / ".venv" / "Scripts" / "pythonw.exe"
            return [str(pythonw), str(self.launcher)]
        return [
            self.uv,
            "run",
            "--project",
            str(self.root),
            "--no-sync",
            "python",
            str(self.launcher),
        ]


def install_root(
    *,
    home: Path | None = None,
    platform: str = sys.platform,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Per-platform per-user application directory."""
    environ = os.environ if env is None else env
    home = home or Path.home()
    if platform == "win32":
        appdata = environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / APP_DIRNAME
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_DIRNAME
    data_home = environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else home / ".local" / "share"
    return base / APP_DIRNAME


def target_root(
    *,
    home: Path | None = None,
    install_dir: Path | None = None,
    platform: str = sys.platform,
) -> Path:
    """The install target: an explicit --install-dir wins over the per-user default."""
    if install_dir is not None:
        return install_dir.expanduser().resolve()
    return install_root(home=home, platform=platform)


def copy_repo(source: Path, target: Path) -> None:
    """Copy the working tree (including `.git` on the first install)."""
    ignore = list(_IGNORED)
    if (target / ".git").exists():
        ignore.append(".git")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*ignore),
    )


def sync_env(
    runner: Runner,
    target: Path,
    output,
) -> bool:
    """Run `uv sync` for the installed copy; False on failure."""
    uv = runner.which("uv") or "uv"
    output(f"Syncing the installed environment in {target} ...")
    result = runner.run(
        [uv, "sync", "--project", str(target)],
        timeout=600,
    )
    if result.returncode != 0:
        if result.stdout.strip():
            output(result.stdout.strip())
        if result.stderr.strip():
            output(result.stderr.strip())
        return False
    return True


def prune_empty_dirs(start: Path, *, stop: Path) -> list[Path]:
    """Remove `start` and its parents while empty, never at or above `stop`."""
    boundary = stop.resolve()
    current = start.resolve()
    removed: list[Path] = []
    while current != boundary and boundary in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        removed.append(current)
        current = current.parent
    return removed
