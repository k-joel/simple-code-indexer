"""Runtime logging: INFO on stderr, DEBUG detail in `<workspace>/.simple-ci/log/`.

The files live inside the gitignored, index-ignored `.simple-ci/` directory, so
writing them can never trigger the watcher or feed the index. Each role has its
own file: `embed.log` for the all-in-one embedded server, `writer.log` for the
sidecar daemon, and `reader.log` for sidecar MCP readers. All three use the same
`log.max_bytes` / `log.backups` rotation settings.

`reader.log` is shared by every reader in the workspace, so rotation is
best-effort there; the writer-owned files always have exactly one process.

stdout is the MCP JSON-RPC channel and must stay untouched.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from importlib.metadata import PackageNotFoundError, version
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from simple_code_indexer.config import Settings

LOG_DIRNAME = "log"
EMBED_LOG_FILENAME = "embed.log"
WRITER_LOG_FILENAME = "writer.log"
READER_LOG_FILENAME = "reader.log"
LOG_FILENAME = EMBED_LOG_FILENAME
FORMAT = "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"
PACKAGE = "simple_code_indexer"

_FILE_HANDLER: RotatingFileHandler | None = None
_CONSOLE_HANDLER: logging.StreamHandler | None = None
_ACTIVE: Path | None = None
_HOOKS_INSTALLED = False


def log_path(settings: Settings, filename: str = LOG_FILENAME) -> Path:
    """`<workspace>/.simple-ci/log/<filename>` (follows an INDEX_DB override)."""
    return settings.index_db_path.parent / LOG_DIRNAME / filename


def active_log_file() -> Path | None:
    """The configured log file, or None when it could not be opened."""
    return _ACTIVE


def package_version() -> str:
    try:
        return version("simple-code-indexer")
    except PackageNotFoundError:
        return "unknown"


def configure_console() -> None:
    """INFO lines on stderr — the harness's only view of the process.

    The handler carries its own level: DEBUG records from our modules reach it
    through propagation, and a NOTSET handler would print every one of them.
    """
    global _CONSOLE_HANDLER

    root = logging.getLogger()
    if _CONSOLE_HANDLER is None:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(handler)
        _CONSOLE_HANDLER = handler
    if root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    # Emit our DEBUG records; each handler decides whether to keep them.
    logging.getLogger(PACKAGE).setLevel(logging.DEBUG)


class _FileFilter(logging.Filter):
    """Our modules at the handler level; other libraries only at WARNING+."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or record.name.startswith(PACKAGE)


def configure_file(settings: Settings, *, filename: str = LOG_FILENAME) -> Path | None:
    """Attach the rotating file handler; fail soft so the server still serves."""
    global _FILE_HANDLER, _ACTIVE

    path = log_path(settings, filename)
    if _FILE_HANDLER is not None and Path(_FILE_HANDLER.baseFilename) == Path(
        os.path.abspath(path)
    ):
        return _ACTIVE
    detach_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backups,
            encoding="utf-8",
        )
    except OSError:
        logging.getLogger(PACKAGE).warning(
            "cannot open the log file %s; logging to stderr only",
            path,
            exc_info=True,
        )
        return None
    handler.setLevel(getattr(logging, settings.log_level.upper(), logging.DEBUG))
    handler.setFormatter(logging.Formatter(FORMAT))
    handler.addFilter(_FileFilter())
    logging.getLogger().addHandler(handler)
    configure_console()
    _FILE_HANDLER = handler
    _ACTIVE = path
    return path


def detach_file() -> None:
    """Remove and close the file handler (tests, config reloads)."""
    global _FILE_HANDLER, _ACTIVE

    handler, _FILE_HANDLER = _FILE_HANDLER, None
    if handler is not None:
        logging.getLogger().removeHandler(handler)
        handler.close()
    _ACTIVE = None


def install_excepthooks() -> None:
    """Log uncaught main/thread exceptions; stderr keeps its traceback too.

    Daemon threads (the sweep timer, the watcher, the index writer) have no other
    way to report a death: `threading.excepthook` is the only visitor.
    """
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return

    previous_thread_hook = threading.excepthook
    previous_sys_hook = sys.excepthook
    log = logging.getLogger(f"{PACKAGE}.unhandled")

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        thread_name = args.thread.name if args.thread is not None else "<unknown>"
        if args.exc_value is not None:
            log.critical(
                "uncaught exception in thread %s",
                thread_name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        else:
            log.critical(
                "uncaught exception in thread %s (%s)",
                thread_name,
                args.exc_type.__name__,
            )
        previous_thread_hook(args)

    def _sys_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        log.critical(
            "uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        previous_sys_hook(exc_type, exc_value, exc_traceback)

    threading.excepthook = _thread_hook
    sys.excepthook = _sys_hook
    _HOOKS_INSTALLED = True


def log_startup(
    settings: Settings, log_file: Path | None, *, role: str = "writer"
) -> None:
    """Banner with everything needed to interpret the rest of the session."""
    from simple_code_indexer import vector_store

    log = logging.getLogger(f"{PACKAGE}.server")
    log.info(
        "simple-code-indexer %s starting (pid=%d, python=%s)",
        package_version(),
        os.getpid(),
        sys.version.split()[0],
    )
    log.info("role=%s mode=%s", role, settings.mode)
    log.info(
        "workspace=%s index_db=%s vector_store=%s (%s)",
        settings.workspace_root,
        settings.index_db_path,
        settings.vector_store,
        vector_store.describe(settings),
    )
    log.info(
        "embed=%s model=%s dim=%d fingerprint=%s",
        settings.embed_base_url,
        settings.embed_model,
        settings.embed_dim,
        settings.embed_fingerprint or "-",
    )
    log.info(
        "config=%s sweep=%s debounce_ms=%d",
        [str(path) for path in settings.config_sources] or "defaults",
        "off" if not settings.sweep_enabled else f"{settings.sweep_seconds:.0f}s",
        settings.debounce_ms,
    )
    log.info(
        "log_file=%s level=%s",
        log_file or "unavailable (stderr only)",
        settings.log_level,
    )
    log.debug("log started at %.3f", time.time())
