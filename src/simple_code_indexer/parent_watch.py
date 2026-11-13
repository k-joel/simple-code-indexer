"""Exit when the harness that owns this MCP session is gone (ISS-3, ISS-10).

Some MCP clients keep the child's stdin open after their UI closes, so
``stdio_server`` never sees EOF and the server keeps sweeping forever. The
watchdog snapshots the harness process — the one that owns the stdio session —
and stops the serve loop as soon as it disappears.

Only the harness is watched. The launch plumbing between the harness and the
interpreter (``uv``/``uvx`` and the venv ``python.exe`` trampoline they spawn)
is skipped, and nothing above the harness is watched. That matters for OpenCode:
the desktop UI starts ``opencode-cli serve --service`` once and later sessions
*reuse* that service as a sibling, so the UI is not an ancestor of a reused
service. Watching the harness keeps the server alive exactly as long as the
service that owns it, which is the accepted trade-off (ISS-10).

Processes that merely happened to start the harness (shells, terminal hosts,
``explorer.exe``) are deliberately not watched: closing a terminal must not
stop a detached session. Set ``SIMPLE_CI_PARENT_WATCH=0`` to disable the
watchdog entirely (debugging, tests of the serving loop).
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("simple_code_indexer")

CHECK_INTERVAL_S = 2.0
_MAX_DEPTH = 8
_ENV_DISABLE = "SIMPLE_CI_PARENT_WATCH"

# Our own launch plumbing. `uv run` puts uv.exe above a venv `python.exe`
# trampoline, so the harness is normally two processes further up.
_LAUNCHER_NAMES = frozenset({"uv", "uv.exe", "uvx", "uvx.exe", "uvw", "uvw.exe"})
_PYTHON_NAMES = frozenset({"python", "python3", "pythonw", "py"})

if sys.platform == "win32":
    _BOUNDARY_NAMES = frozenset(
        {
            "system",
            "registry",
            "memcompression",
            "smss.exe",
            "csrss.exe",
            "wininit.exe",
            "winlogon.exe",
            "services.exe",
            "lsass.exe",
            "svchost.exe",
            "explorer.exe",
            "conhost.exe",
            "openconsole.exe",
            "windowsterminal.exe",
            "wt.exe",
            "cmd.exe",
            "powershell.exe",
            "pwsh.exe",
            "bash.exe",
            "sh.exe",
            "zsh.exe",
            "fish.exe",
            "mintty.exe",
            "wsl.exe",
            "wslhost.exe",
            "ubuntu.exe",
            "debian.exe",
            "kali.exe",
        }
    )
else:
    _BOUNDARY_NAMES = frozenset(
        {
            "init",
            "systemd",
            "launchd",
            "launchd_sim",
            "login",
            "sshd",
            "sh",
            "bash",
            "zsh",
            "fish",
            "dash",
            "ksh",
            "tcsh",
            "csh",
            "mintty",
            "xterm",
            "konsole",
            "gnome-terminal-",
            "alacritty",
            "kitty",
            "wezterm",
            "tmux",
            "screen",
            "systemd-logind",
        }
    )


class ProcessRef(Protocol):
    """A process the watchdog can poll and release."""

    pid: int
    name: str

    def alive(self) -> bool: ...

    def close(self) -> None: ...

    def describe(self) -> str: ...


@dataclass(slots=True)
class WatchedProcess:
    """A process snapshot; liveness is immune to PID reuse where possible."""

    pid: int
    name: str
    _handle: int | None = None
    _start_marker: str | None = None

    def alive(self) -> bool:
        return _alive(self)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            _close_handle(handle)

    def describe(self) -> str:
        return f"{self.pid} ({self.name})" if self.name else str(self.pid)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _SYNCHRONIZE = 0x00100000
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _WAIT_TIMEOUT = 0x00000102
    _TH32CS_SNAPPROCESS = 0x00000002
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _ProcessEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _KERNEL32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _KERNEL32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32),
    ]
    _KERNEL32.Process32FirstW.restype = wintypes.BOOL
    _KERNEL32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32),
    ]
    _KERNEL32.Process32NextW.restype = wintypes.BOOL
    _KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _KERNEL32.WaitForSingleObject.restype = wintypes.DWORD
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    def _process_table() -> dict[int, tuple[int, str]]:
        """pid -> (parent pid, executable name) from one Toolhelp snapshot."""
        snapshot = _KERNEL32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if snapshot == _INVALID_HANDLE_VALUE:
            return {}
        try:
            entry = _ProcessEntry32()
            entry.dwSize = ctypes.sizeof(_ProcessEntry32)
            table: dict[int, tuple[int, str]] = {}
            if not _KERNEL32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return table
            while True:
                table[int(entry.th32ProcessID)] = (
                    int(entry.th32ParentProcessID),
                    entry.szExeFile,
                )
                if not _KERNEL32.Process32NextW(snapshot, ctypes.byref(entry)):
                    return table
        finally:
            _KERNEL32.CloseHandle(snapshot)

    def _open_handle(pid: int) -> int | None:
        handle = _KERNEL32.OpenProcess(
            _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        return int(handle) if handle else None

    def _alive(process: WatchedProcess) -> bool:
        if process._handle is None:
            return False
        return _KERNEL32.WaitForSingleObject(process._handle, 0) == _WAIT_TIMEOUT

    def _start_marker(pid: int) -> str | None:
        return None

    def _image_path(pid: int) -> str | None:
        """Full executable path, when the process is still queryable."""
        handle = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not _KERNEL32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return None
            return buffer.value
        finally:
            _KERNEL32.CloseHandle(handle)

    def _close_handle(handle: int) -> None:
        _KERNEL32.CloseHandle(handle)

else:

    def _process_table() -> dict[int, tuple[int, str]]:
        """pid -> (parent pid, command name) via one ``ps`` call."""
        try:
            result = subprocess.run(
                ["ps", "-A", "-o", "pid=", "-o", "ppid=", "-o", "comm="],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        table: dict[int, tuple[int, str]] = {}
        for line in result.stdout.splitlines():
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            try:
                pid = int(parts[0])
                ppid = int(parts[1])
            except ValueError:
                continue
            table[pid] = (ppid, parts[2].strip())
        return table

    def _start_marker(pid: int) -> str | None:
        """Linux start time (jiffies since boot); PID reuse changes it."""
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return None
        fields = stat.rpartition(")")[2].split()
        return fields[19] if len(fields) > 19 else None

    def _image_path(pid: int) -> str | None:
        # uv typically execs the venv interpreter on POSIX: no trampoline.
        return None

    def _open_handle(pid: int) -> None:
        return None

    def _alive(process: WatchedProcess) -> bool:
        if (
            process._start_marker is not None
            and _start_marker(process.pid) != process._start_marker
        ):
            return False
        try:
            os.kill(process.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _close_handle(handle: int) -> None:
        return None


def _basename(name: str) -> str:
    return name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip().lower()


def _is_boundary(name: str) -> bool:
    return _basename(name) in _BOUNDARY_NAMES


def _is_launcher(name: str) -> bool:
    """`uv` and friends: our own launch plumbing, never the harness."""
    return _basename(name) in _LAUNCHER_NAMES


def _is_python(name: str) -> bool:
    base = _basename(name).removesuffix(".exe")
    return base in _PYTHON_NAMES or base.startswith("python3.")


def _is_trampoline(pid: int) -> bool:
    """True for a venv `python.exe` redirector (uv spawns one on Windows)."""
    path = _image_path(pid)
    if path is None:
        return False
    return "\\scripts\\python" in path.replace("/", "\\").lower()


def watch_process(pid: int, name: str = "") -> WatchedProcess | None:
    """Snapshot one process for liveness polling; None when already gone."""
    process = WatchedProcess(
        pid,
        name,
        _handle=_open_handle(pid),
        _start_marker=_start_marker(pid),
    )
    return process if process.alive() else None


def _launch_chain(table: dict[int, tuple[int, str]]) -> list[tuple[int, str]]:
    """Live ancestors, nearest first, up to a shell/system root."""
    chain: list[tuple[int, str]] = []
    pid = os.getpid()
    seen = {pid}
    for _ in range(_MAX_DEPTH):
        entry = table.get(pid)
        if entry is None:
            break
        parent_pid = entry[0]
        if parent_pid <= 0 or parent_pid in seen:
            break
        parent = table.get(parent_pid)
        if parent is None:
            break
        name = parent[1]
        if _is_boundary(name):
            break
        chain.append((parent_pid, name))
        seen.add(parent_pid)
        pid = parent_pid
    return chain


def harness_process(
    table: dict[int, tuple[int, str]] | None = None,
    watcher: Callable[[int, str], ProcessRef | None] = watch_process,
    trampoline: Callable[[int], bool] = _is_trampoline,
) -> ProcessRef | None:
    """Snapshot the one process that owns this MCP session, or None.

    Walks up past our own launch plumbing: `uv`/`uvx` and any venv `python.exe`
    trampoline (recognized by image path on Windows, or by sitting directly
    below a launcher). The first remaining ancestor is the harness; nothing
    above it is watched (ISS-10).
    """
    table = _process_table() if table is None else table
    chain = _launch_chain(table)
    logger.debug(
        "harness lookup: chain=%s",
        ", ".join(f"{pid} ({name})" for pid, name in chain) or "none",
    )
    for index, (pid, name) in enumerate(chain):
        if _is_launcher(name):
            continue
        parent_name = chain[index + 1][1] if index + 1 < len(chain) else ""
        if _is_python(name) and (_is_launcher(parent_name) or trampoline(pid)):
            continue  # venv trampoline, whichever process spawned it
        return watcher(pid, name)
    return None


def enabled() -> bool:
    value = os.environ.get(_ENV_DISABLE)
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


class ParentWatchdog:
    """Poll the harness process; ``wait`` returns when it is gone."""

    def __init__(
        self,
        interval_s: float = CHECK_INTERVAL_S,
        processes: Sequence[ProcessRef] | None = None,
    ) -> None:
        self._interval_s = interval_s
        if processes is None:
            harness = harness_process()
            self._processes: list[ProcessRef] = [harness] if harness is not None else []
        else:
            self._processes = list(processes)

    @property
    def processes(self) -> tuple[ProcessRef, ...]:
        return tuple(self._processes)

    def dead(self) -> ProcessRef | None:
        for process in self._processes:
            if not process.alive():
                return process
        return None

    async def wait(self) -> ProcessRef:
        while True:
            dead = self.dead()
            if dead is not None:
                return dead
            await asyncio.sleep(self._interval_s)

    def close(self) -> None:
        for process in self._processes:
            process.close()
        self._processes.clear()

    def describe(self) -> str:
        return ", ".join(process.describe() for process in self._processes) or "none"
