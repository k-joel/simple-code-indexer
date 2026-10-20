from pathlib import Path

import pytest

from simple_code_indexer import server
from simple_code_indexer.workspace_lock import WorkspaceLock


def test_lock_is_exclusive_until_released(tmp_path: Path) -> None:
    first = WorkspaceLock(tmp_path / ".simple-ci" / "index.db")
    second = WorkspaceLock(tmp_path / ".simple-ci" / "index.db")

    assert first.acquire() is True
    assert (tmp_path / ".simple-ci" / "index.db.lock").exists()
    assert second.acquire() is False

    first.release()
    assert second.acquire() is True
    second.release()


def test_acquire_is_idempotent_and_release_is_safe(tmp_path: Path) -> None:
    lock = WorkspaceLock(tmp_path / "index.db")
    lock.release()
    assert lock.acquire() is True
    assert lock.acquire() is True
    lock.release()
    lock.release()


def test_server_refuses_a_second_writer(tmp_path: Path) -> None:
    first = server._acquire_workspace_lock(tmp_path / "index.db")
    try:
        with pytest.raises(SystemExit):
            server._acquire_workspace_lock(tmp_path / "index.db")
    finally:
        first.release()
