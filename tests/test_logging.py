"""Runtime file logging: placement, filtering, rotation, fail-soft, hooks."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from simple_code_indexer import db, embed, indexer, logging_setup, server
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.errors import EmbedError
from simple_code_indexer.registry import get_registry


@pytest.fixture(autouse=True)
def _detach() -> Iterator[None]:
    """Never leave a handler on a deleted tmp file (Windows cleanup fails)."""
    logging_setup.detach_file()
    yield
    logging_setup.detach_file()


def _settings(workspace: Path, **overrides: object) -> Settings:
    registry = get_registry()
    base = Settings(
        workspace_root=workspace,
        index_db_path=workspace / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_test",
        embed_base_url="http://localhost:1",
        embed_model="test-model",
        embed_dim=8,
        embed_timeout_s=15.0,
        sweep_seconds=45.0,
        debounce_ms=400,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        vector_store="faiss",
    )
    return replace(base, **overrides) if overrides else base


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_log_file_is_created_next_to_the_index(tmp_path: Path) -> None:
    path = logging_setup.configure_file(_settings(tmp_path))
    assert path == tmp_path / ".simple-ci" / "log" / "embed.log"
    assert path is not None
    assert path.is_file()
    assert logging_setup.active_log_file() == path


def test_package_records_land_and_other_libraries_only_warn(tmp_path: Path) -> None:
    path = logging_setup.configure_file(_settings(tmp_path))
    assert path is not None
    logging.getLogger("simple_code_indexer.test").debug("package-debug-line")
    logging.getLogger("httpx").debug("library-debug-line")
    logging.getLogger("mcp").warning("library-warning-line")
    text = _read(path)
    assert "package-debug-line" in text
    assert "library-debug-line" not in text
    assert "library-warning-line" in text


def test_configure_file_is_idempotent_and_switches_workspaces(tmp_path: Path) -> None:
    first = logging_setup.configure_file(_settings(tmp_path / "one"))
    assert first is not None
    attached = [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "baseFilename", None) == str(first.resolve())
    ]
    assert len(attached) == 1

    assert logging_setup.configure_file(_settings(tmp_path / "one")) == first
    assert (
        len(
            [
                handler
                for handler in logging.getLogger().handlers
                if getattr(handler, "baseFilename", None) == str(first.resolve())
            ]
        )
        == 1
    )

    second = logging_setup.configure_file(_settings(tmp_path / "two"))
    assert second is not None
    assert second != first
    base_filenames = {
        getattr(handler, "baseFilename", None)
        for handler in logging.getLogger().handlers
    }
    assert str(first.resolve()) not in base_filenames
    assert str(second.resolve()) in base_filenames


def test_the_configured_level_filters_the_file(tmp_path: Path) -> None:
    path = logging_setup.configure_file(_settings(tmp_path, log_level="INFO"))
    assert path is not None
    log = logging.getLogger("simple_code_indexer.test")
    log.debug("hidden-debug-line")
    log.warning("kept-warning-line")
    text = _read(path)
    assert "hidden-debug-line" not in text
    assert "kept-warning-line" in text


def test_the_log_rotates(tmp_path: Path) -> None:
    path = logging_setup.configure_file(
        _settings(tmp_path, log_max_bytes=400, log_backups=1)
    )
    assert path is not None
    log = logging.getLogger("simple_code_indexer.rotate")
    for _ in range(20):
        log.info("x" * 100)
    assert path.is_file()
    assert path.with_name(path.name + ".1").is_file()


@pytest.mark.parametrize(
    "filename",
    [
        logging_setup.EMBED_LOG_FILENAME,
        logging_setup.WRITER_LOG_FILENAME,
        logging_setup.READER_LOG_FILENAME,
    ],
)
def test_each_role_has_its_own_file(tmp_path: Path, filename: str) -> None:
    path = logging_setup.configure_file(_settings(tmp_path), filename=filename)
    assert path == tmp_path / ".simple-ci" / "log" / filename
    assert path is not None
    assert path.is_file()


@pytest.mark.parametrize(
    "filename",
    [
        logging_setup.EMBED_LOG_FILENAME,
        logging_setup.WRITER_LOG_FILENAME,
        logging_setup.READER_LOG_FILENAME,
    ],
)
def test_rotation_parameters_and_encoding(tmp_path: Path, filename: str) -> None:
    path = logging_setup.configure_file(_settings(tmp_path), filename=filename)
    assert path is not None
    target = str(path.resolve())
    handler = next(
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "baseFilename", None) == target
    )
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == 5_000_000
    assert handler.backupCount == 3
    assert handler.encoding == "utf-8"


def test_an_unwritable_log_path_is_fail_soft(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    settings = _settings(tmp_path, index_db_path=blocker / "index.db")
    assert logging_setup.configure_file(settings) is None
    assert logging_setup.active_log_file() is None


def test_index_one_file_logs_its_details(tmp_path: Path, monkeypatch) -> None:
    def _stub(_settings: Settings, _texts: list[str]) -> list[list[float]]:
        raise EmbedError("stubbed out")

    monkeypatch.setattr(embed, "embed_texts", _stub)
    settings = _settings(tmp_path)
    path = logging_setup.configure_file(settings)
    assert path is not None

    source = tmp_path / "widget.cpp"
    source.write_text("int f() { return 1; }\n", encoding="utf-8")
    outcome = indexer.index_one_file(settings, source)

    assert outcome.status == "indexed"
    text = _read(path)
    assert "indexed widget.cpp" in text
    assert "chunk(s)" in text
    assert "symbol(s)" in text


def test_tool_calls_are_logged(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    path = logging_setup.configure_file(settings)
    assert path is not None
    with db.connect(settings.index_db_path) as conn:
        db.ensure_schema(conn)

    server._call_tool(settings, "search_code", {"query": "calculateWidget", "limit": 3})
    server._call_tool(settings, "search_code", {"query": "x" * 500})
    server._call_tool(settings, "symbol_lookup", {"symbol": "calculateWidget"})

    text = _read(path)
    assert "tool=search_code" in text
    assert "query='calculateWidget'" in text
    assert "0 hit(s)" in text
    assert "0 match(es)" in text
    assert "…" in text


def test_thread_exception_hook_logs_a_traceback(tmp_path: Path, monkeypatch) -> None:
    path = logging_setup.configure_file(_settings(tmp_path))
    assert path is not None
    # Isolate from pytest's own hook (it would warn about our synthetic args).
    monkeypatch.setattr(logging_setup, "_HOOKS_INSTALLED", False)
    monkeypatch.setattr(threading, "excepthook", lambda _args: None)
    logging_setup.install_excepthooks()
    try:
        raise RuntimeError("boom-in-thread")
    except RuntimeError as exc:
        args = threading.ExceptHookArgs(
            (type(exc), exc, exc.__traceback__, threading.current_thread())
        )
    threading.excepthook(args)
    text = _read(path)
    assert "uncaught exception in thread" in text
    assert "boom-in-thread" in text


def test_status_payload_exposes_the_log_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    path = logging_setup.configure_file(settings)
    assert path is not None
    with db.connect(settings.index_db_path) as conn:
        db.ensure_schema(conn)

    payload = server._status_payload(settings)

    assert payload["log_file"] == str(path)
    assert payload["log_level"] == "debug"
