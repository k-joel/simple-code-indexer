"""WriterRuntime: lease ownership, shutdown ordering, and idempotence."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import pytest

from simple_code_indexer import db, indexer, runtime, vector_store, watcher
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.errors import WorkspaceBusy
from simple_code_indexer.registry import get_registry
from simple_code_indexer.workspace_lock import WorkspaceLock


def _settings(workspace: Path) -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=workspace,
        index_db_path=workspace / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_test",
        embed_base_url="http://127.0.0.1:9",
        embed_model="test-model",
        embed_dim=8,
        embed_timeout_s=1.0,
        sweep_seconds=0.0,
        debounce_ms=100,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        vector_store="faiss",
        heartbeat_s=0.2,
    )


@pytest.fixture(autouse=True)
def _no_grammar_prefetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLE_CI_PREFETCH_GRAMMARS", "0")


def _start(settings: Settings) -> runtime.WriterRuntime:
    writer = runtime.WriterRuntime(settings)
    writer.start()
    return writer


def test_vector_index_age_delegates_to_the_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(vector_store, "vector_index_age_s", lambda _s: 12.5)
    assert runtime.vector_index_age(settings) == 12.5


def test_start_acquires_the_lease_and_stop_releases_it(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    writer = _start(settings)
    try:
        other = WorkspaceLock(settings.index_db_path)
        assert other.acquire() is False
    finally:
        writer.stop()

    other = WorkspaceLock(settings.index_db_path)
    assert other.acquire() is True
    other.release()


def test_a_second_runtime_raises_workspace_busy(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = _start(settings)
    try:
        with pytest.raises(WorkspaceBusy):
            runtime.WriterRuntime(settings).start()
    finally:
        first.stop()


def test_stop_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    writer = _start(settings)
    writer.stop()
    writer.stop()
    assert writer.status()["writer_ok"] is False


def test_stop_flushes_before_releasing_the_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    seen: list[bool] = []

    def fake_flush(settings: Settings) -> None:
        probe = WorkspaceLock(settings.index_db_path)
        seen.append(probe.acquire())
        if seen[-1]:
            probe.release()

    def idle_writer(settings: Settings, queue, stop_event) -> None:
        stop_event.wait()

    monkeypatch.setattr(indexer, "writer_loop", idle_writer)
    monkeypatch.setattr(vector_store, "flush", fake_flush)

    writer = _start(settings)
    writer.stop()

    assert seen == [False], "flush must run while index.db.lock is still held"


def test_stop_order_is_logged_for_the_parent_watch_test(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _settings(tmp_path)
    caplog.set_level(logging.INFO, logger="simple_code_indexer")

    writer = _start(settings)
    watcher.wait_until_ready(5.0)
    writer.stop()

    messages = [record.getMessage() for record in caplog.records]
    shutdown = next(
        i for i, line in enumerate(messages) if "shutting down after" in line
    )
    released = next(
        i for i, line in enumerate(messages) if "workspace lock released" in line
    )
    assert shutdown < released
    assert not watcher.is_alive()


def test_stop_joins_the_service_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    order: list[str] = []

    def idle_probe(_settings: Settings, stop_event: threading.Event) -> None:
        stop_event.wait(5.0)
        order.append("probe")

    monkeypatch.setattr(runtime, "_probe_services", idle_probe)

    writer = _start(settings)
    writer.stop()
    order.append("stop-returned")

    assert order == ["probe", "stop-returned"]


def test_writer_heartbeat_lives_and_then_clears(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    writer = _start(settings)
    with db.connect(settings.index_db_path) as conn:
        assert db.get_meta(conn, db.WRITER_PID_KEY) == str(os.getpid())
        assert db.get_meta(conn, db.WRITER_HEARTBEAT_KEY)

    writer.stop()
    with db.connect(settings.index_db_path) as conn:
        assert db.get_meta(conn, db.WRITER_PID_KEY) == ""

    state = runtime.writer_state(settings, stale_after_s=15.0)
    assert state["writer_pid"] is None
    assert state["writer_ok"] is False
