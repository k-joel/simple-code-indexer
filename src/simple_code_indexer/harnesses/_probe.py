"""Does a harness's own CLI actually answer?

A leftover config directory is not proof of an install: uninstalling an editor
or a CLI leaves `~/.cursor`, `~/.config/kilo` and friends behind, so directory
detection reports harnesses that are gone. The strong signal is the client's
own binary — resolve it, run it with ``PROBE_ARGS`` (default ``--version``) and
accept a zero exit.

Directories stay as a fallback (``HarnessSpec.detection``): some harnesses are
extension-only and have no CLI at all (Kilo and Cline inside an editor, Claude
Desktop's GUI), and Zed's ``zed`` on ``PATH`` is usually authzed's SpiceDB CLI.
The two signals are ORed, never exclusive: a false negative would hide a real
harness, which is worse than the stale-directory false positive this module
reduces.

Nothing here may import ``setup_wizard``: a runner is any object with
``which(name)`` and ``run(argv, *, timeout, cwd)``, which both
``setup_wizard.provision.Runner`` and the wizard's test fake already are.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

PROBE_TIMEOUT_S = 10.0
"""Generous on purpose: an npm-installed CLI behind a Windows ``.cmd`` shim needs
2-4 s to answer ``--version`` (measured: ``openclaw`` 4.2 s, ``command-code``
2.1 s), and a tighter cap would silently fall back to directory detection."""

CLI = "cli"
"""The binary answered: the harness is installed and runnable."""

BINARY = "binary"
"""The binary is on `PATH` but did not answer in time — still counts."""

DIR = "dir"
"""Only a config directory was found: an extension-only or GUI harness."""


class Runnable(Protocol):
    """The slice of `provision.Runner` a probe needs (no import, no cycle)."""

    def which(self, name: str) -> str | None: ...

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = ...,
        cwd: Path | None = None,
    ) -> Any: ...


class LocalRunner:
    """`Runnable` over `shutil.which` + `subprocess.run` (the wizard's default)."""

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = PROBE_TIMEOUT_S,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            capture_output=True,
            check=False,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            cwd=str(cwd) if cwd is not None else None,
        )


@dataclass(frozen=True, slots=True)
class Detection:
    """Which proof won, and a short user-facing reason for the menu label."""

    state: str
    detail: str


def spawnable(argv: list[str]) -> list[str]:
    """Route a Windows `.cmd`/`.bat` shim through `cmd /c`.

    `shutil.which("cursor")` finds `cursor.CMD`, and `subprocess` cannot execute
    a batch file directly (`WinError 2`). Every Windows client that ships a shim
    — Cursor, VS Code, npm-installed CLIs — needs this, for `--version` probes
    and for `mcp add` alike.
    """
    if os.name != "nt" or not argv:
        return argv
    suffix = Path(argv[0]).suffix.lower()
    if suffix not in {".cmd", ".bat"}:
        return argv
    comspec = os.environ.get("COMSPEC") or "cmd.exe"
    return [comspec, "/c", *argv]


def responds(runner: Runnable, binary: str, args: Sequence[str]) -> str | None:
    """The resolved path when `binary args` exits 0, else None.

    Never raises: a missing binary, an unexecutable shim, a timeout or a
    non-zero exit all mean "not proven" and fall through to the next signal.
    """
    try:
        resolved = runner.which(binary)
    except OSError:
        return None
    if resolved is None:
        return None
    argv = spawnable([resolved, *args])
    try:
        result = runner.run(argv, timeout=PROBE_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - a probe must never break the wizard
        return None
    return resolved if getattr(result, "returncode", 1) == 0 else None


def probe_binaries(
    binaries: Sequence[str], args: Sequence[str], runner: Runnable
) -> Detection | None:
    """First binary that answers wins; else the first one merely on `PATH`."""
    found: str | None = None
    for binary in binaries:
        resolved = responds(runner, binary, args)
        if resolved is not None:
            command = " ".join([binary, *args])
            return Detection(CLI, command)
        if found is None:
            try:
                found = runner.which(binary)
            except OSError:
                found = None
    if found is not None:
        return Detection(BINARY, f"{binaries[0]} on PATH")
    return None
