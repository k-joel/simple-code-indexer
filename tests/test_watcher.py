import sqlite3
import threading
import time
from pathlib import Path

import pytest

from simple_code_indexer import db, embed, indexer, watcher
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.errors import EmbedError
from simple_code_indexer.registry import get_registry


@pytest.fixture(autouse=True)
def _no_embed_network(monkeypatch) -> None:
    """Watcher tests index lexically; embedding failure path is test_embed's job."""

    def _stub(settings, texts):
        raise EmbedError("stubbed out in unit tests")

    monkeypatch.setattr(embed, "embed_texts", _stub)


def _settings(workspace: Path, *, debounce_ms: int = 100) -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=workspace,
        index_db_path=workspace / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_2560",
        embed_base_url="http://localhost:1",  # hermetic: fail-soft embed path
        embed_model="Qwen3-Embedding-4B-Q6_K",
        embed_dim=2560,
        embed_timeout_s=15.0,
        sweep_seconds=3600.0,
        debounce_ms=debounce_ms,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
    )


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_watcher_indexes_file_on_save(tmp_path: Path) -> None:
    """Index on save: create a file → found without a manual reindex."""
    settings = _settings(tmp_path)
    work_queue: indexer.WorkQueue = indexer.new_work_queue()
    writer = threading.Thread(
        target=indexer.writer_loop, args=(settings, work_queue), daemon=True
    )
    writer.start()
    observer = watcher.start_watcher(settings, work_queue)
    try:
        assert watcher.wait_until_ready(timeout=5.0)
        # ISS-7 regression guard: one watch => one emitter thread, not one per dir.
        assert len(observer.emitters) == 1
        assert next(iter(observer.emitters)).watch.is_recursive
        fresh = tmp_path / "fresh_symbol.cpp"
        fresh.write_text("int fresh_symbol_xyzzy() { return 1; }\n", encoding="utf-8")
        found = _wait_for(
            lambda: _symbol_in_index(settings, "fresh_symbol_xyzzy"), timeout=5.0
        )
        assert found, "file saved on disk was not indexed within 5 s"

        # No-op save is a no-op; content change re-indexes.
        fresh.write_text(
            "int fresh_symbol_xyzzy() { return 42; }  // v2\n", encoding="utf-8"
        )
        assert _wait_for(lambda: _chunk_contains(settings, "return 42"), 5.0)

        # Delete removes rows.
        fresh.unlink()
        assert _wait_for(
            lambda: not _symbol_in_index(settings, "fresh_symbol_xyzzy"), 5.0
        )
    finally:
        observer.stop()
        observer.join(timeout=2.0)


def test_debounce_collapses_event_burst(tmp_path: Path) -> None:
    settings = _settings(tmp_path, debounce_ms=150)
    work_queue: indexer.WorkQueue = indexer.new_work_queue()
    handler = watcher.build_handler(settings, work_queue)
    path = str(tmp_path / "burst.cpp")
    from watchdog.events import FileModifiedEvent

    for _ in range(6):
        handler.on_modified(FileModifiedEvent(path))
    time.sleep(0.05)
    assert work_queue.empty(), "event enqueued before the debounce window closed"
    assert _wait_for(lambda: not work_queue.empty(), timeout=2.0)
    time.sleep(0.3)
    assert work_queue.qsize() == 1, "burst was not collapsed to one work item"


def test_ignored_and_temp_events_are_dropped(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    work_queue: indexer.WorkQueue = indexer.new_work_queue()
    handler = watcher.build_handler(settings, work_queue)
    from watchdog.events import FileCreatedEvent, FileModifiedEvent

    handler.on_created(FileCreatedEvent(str(tmp_path / "notes.md")))
    handler.on_created(FileCreatedEvent(str(tmp_path / ".#scratch.cpp")))
    handler.on_created(FileCreatedEvent(str(tmp_path / "lib.cpp.tmp")))
    handler.on_modified(FileModifiedEvent(str(tmp_path / ".venv" / "x.py")))
    time.sleep(0.3)
    assert work_queue.empty()


def test_gitignored_events_are_dropped(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    (tmp_path / "artifacts").mkdir()
    settings = _settings(tmp_path)
    work_queue: indexer.WorkQueue = indexer.new_work_queue()
    handler = watcher.build_handler(settings, work_queue)
    from watchdog.events import FileCreatedEvent

    handler.on_created(FileCreatedEvent(str(tmp_path / "artifacts" / "probe.py")))
    time.sleep(0.3)
    assert work_queue.empty()


def test_gitignore_change_enqueues_sweep(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("artifacts/\n", encoding="utf-8")
    settings = _settings(tmp_path)
    work_queue: indexer.WorkQueue = indexer.new_work_queue()
    handler = watcher.build_handler(settings, work_queue)
    from watchdog.events import FileModifiedEvent

    handler.on_modified(FileModifiedEvent(str(gitignore)))
    assert work_queue.get_nowait() is indexer.SWEEP_REQUEST


def _symbol_in_index(settings: Settings, name: str) -> bool:
    if not settings.index_db_path.exists():
        return False
    try:
        with db.connect(settings.index_db_path, readonly=True) as conn:
            return bool(db.symbol_lookup(conn, name))
    except sqlite3.OperationalError:
        # The writer thread may not have created the schema yet; retry.
        return False


def _chunk_contains(settings: Settings, needle: str) -> bool:
    if not settings.index_db_path.exists():
        return False
    try:
        with db.connect(settings.index_db_path, readonly=True) as conn:
            return bool(db.fts_search(conn, needle, limit=5))
    except sqlite3.OperationalError:
        return False
