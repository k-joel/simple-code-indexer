"""Cross-process advisory lock: one index writer per workspace (ADR-0004)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import BinaryIO

if sys.platform == "win32":
    import msvcrt

    def _lock(handle: BinaryIO) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle: BinaryIO) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle: BinaryIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: BinaryIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class WorkspaceLock:
    """Non-blocking exclusive lease on `<index_db>.lock`.

    The open handle *is* the lease: the OS releases it when the process exits,
    so a killed session never leaves a stale lock behind (only the file stays).
    """

    def __init__(self, index_db_path: Path) -> None:
        self._path = index_db_path.with_name(index_db_path.name + ".lock")
        self._handle: BinaryIO | None = None

    def acquire(self) -> bool:
        """Take the lock; False when another live process already owns it."""
        if self._handle is not None:
            return True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        try:
            _lock(handle)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            _unlock(handle)
        finally:
            handle.close()
