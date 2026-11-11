"""Filesystem watcher: one recursive watch on the workspace root, save events
→ debounced queue (never index in callback).

Watchdog maps `recursive=True` to a single `ReadDirectoryChangesW` with
`bWatchSubtree=TRUE` on Windows, so the whole tree is one emitter thread. The
old one-watch-per-directory schedule created one thread per directory (ISS-7:
3,227 threads on a Visual Studio workspace). Events under ignored paths
(`config.IGNORE_DIRS`, the active log file, and `.gitignore`) are dropped
silently before any event logging, so the watcher can never log its own log
writes; watchdog walks a newly created directory to synthesize sub-events, and
the sweep remains the backstop for anything missed.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from simple_code_indexer import logging_setup
from simple_code_indexer.config import Settings, is_allowed, is_temp_name
from simple_code_indexer.ignore import GITIGNORE_NAME, IgnoreRules
from simple_code_indexer.indexer import (
    SWEEP_REQUEST,
    WorkItem,
    WorkQueue,
    relative_path,
)

logger = logging.getLogger(__name__)

_OBSERVER: BaseObserver | None = None
_READY = threading.Event()


def build_handler(settings: Settings, work_queue: WorkQueue) -> FileSystemEventHandler:
    debounce_s = settings.debounce_ms / 1000.0
    logger.debug("watcher: debounce %.0f ms", settings.debounce_ms)
    rules = IgnoreRules(settings.workspace_root)

    def is_log_file(path: Path) -> bool:
        """The active log file and its rotation siblings (never log those)."""
        log_file = logging_setup.active_log_file()
        if log_file is None:
            return False
        try:
            log_file = log_file.resolve()
            path = path.resolve()
        except OSError:
            return False
        if path.parent != log_file.parent:
            return False
        name = os.path.normcase(path.name)
        target = os.path.normcase(log_file.name)
        return name == target or name.startswith(target + ".")

    def excluded(path: str, *, is_dir: bool = False) -> bool:
        """Silent drop: outside the workspace, ignored dirs, log file, .gitignore.

        This runs before any event logging. Logging a path inside the workspace
        writes to `sci.log`, which is itself watched, so logging first would
        schedule another event forever (ISS-9).
        """
        p = Path(path)
        rel = relative_path(settings, p)
        if rel is None:
            return True
        if any(part in settings.ignore_dirs for part in rel.split("/")):
            return True
        if is_log_file(p):
            return True
        return rules.is_ignored(rel, is_dir=is_dir)

    def workspace_relative(path: str) -> str | None:
        rel = relative_path(settings, Path(path))
        if rel is None:
            logger.debug("watcher: ignoring %s (outside the workspace)", path)
            return None
        if any(part in settings.ignore_dirs for part in rel.split("/")):
            logger.debug("watcher: ignoring %s (ignored dir)", path)
            return None
        return rel

    def interesting(path: str) -> bool:
        p = Path(path)
        if not is_allowed(settings, p) or is_temp_name(p.name):
            logger.debug("watcher: ignoring %s (not allowlisted)", path)
            return False
        rel = workspace_relative(path)
        if rel is None:
            return False
        if rules.is_ignored(rel):
            logger.debug("watcher: ignoring %s (.gitignore)", path)
            return False
        return True

    def enqueue(item: WorkItem) -> None:
        try:
            work_queue.put_nowait(item)
        except queue.Full:
            # Writer is behind; the reconciliation sweep will cover it.
            logger.warning("work queue full, dropping %s", item.path)

    def gitignore_changed(path: str) -> bool:
        """Reload is implicit (mtime cache); queue a sweep for the index."""
        if Path(path).name != GITIGNORE_NAME:
            return False
        rel = workspace_relative(path)
        if rel is None:
            return False
        try:
            work_queue.put_nowait(SWEEP_REQUEST)
        except queue.Full:
            logger.warning("work queue full, dropping sweep for %s", rel)
        else:
            logger.debug("watcher: %s changed; queued a sweep", rel)
        return True

    class Handler(FileSystemEventHandler):
        # Timers are touched from the observer thread and Timer threads;
        # worst case of a missed cancel is one idempotent extra index.
        def __init__(self) -> None:
            super().__init__()
            self._timers: dict[str, threading.Timer] = {}

        def _schedule_index(self, path: str) -> None:
            if not interesting(path):
                return
            previous = self._timers.pop(path, None)
            if previous is not None:
                previous.cancel()
            timer = threading.Timer(debounce_s, self._fire, args=(path,))
            timer.daemon = True
            self._timers[path] = timer
            timer.start()
            logger.debug("watcher: debounced %s", path)

        def _fire(self, path: str) -> None:
            self._timers.pop(path, None)
            enqueue(WorkItem(Path(path)))
            logger.debug("watcher: index queued for %s", path)

        def on_created(self, event: FileSystemEvent) -> None:
            path = str(event.src_path)
            if excluded(path, is_dir=event.is_directory):
                return
            if event.is_directory:
                # The recursive root watch already covers the new subtree.
                logger.debug("watcher: directory created %s", path)
                return
            logger.debug("watcher: file created %s", path)
            if not gitignore_changed(path):
                self._schedule_index(path)

        def on_modified(self, event: FileSystemEvent) -> None:
            path = str(event.src_path)
            if excluded(path, is_dir=event.is_directory):
                return
            if not event.is_directory:
                logger.debug("watcher: file modified %s", path)
                if not gitignore_changed(path):
                    self._schedule_index(path)

        def on_moved(self, event: FileSystemEvent) -> None:
            src = str(event.src_path)
            dest = str(event.dest_path)
            src_excluded = excluded(src, is_dir=event.is_directory)
            dest_excluded = excluded(dest, is_dir=event.is_directory)
            if src_excluded and dest_excluded:
                return
            if event.is_directory:
                logger.debug("watcher: directory moved %s -> %s", src, dest)
                return
            logger.debug("watcher: file moved %s -> %s", src, dest)
            if not src_excluded and gitignore_changed(src):
                return
            if not dest_excluded and gitignore_changed(dest):
                return
            if not src_excluded and interesting(src):
                enqueue(WorkItem(Path(src), deleted=True))
            if not dest_excluded:
                self._schedule_index(dest)

        def on_deleted(self, event: FileSystemEvent) -> None:
            path = str(event.src_path)
            if excluded(path, is_dir=event.is_directory):
                return
            if event.is_directory:
                logger.debug("watcher: directory deleted %s", path)
                return
            if gitignore_changed(path):
                return
            if interesting(path):
                logger.debug("watcher: file deleted %s", path)
                enqueue(WorkItem(Path(path), deleted=True))

    return Handler()


def start_watcher(settings: Settings, work_queue: WorkQueue) -> BaseObserver:
    """Start a single recursive root watch on a daemon thread; returns without
    blocking serve."""
    global _OBSERVER

    observer = Observer()
    handler = build_handler(settings, work_queue)

    def _start() -> None:
        started = time.perf_counter()
        try:
            observer.schedule(handler, str(settings.workspace_root), recursive=True)
            observer.start()
            _READY.set()
            logger.info(
                "watcher ready: recursive watch on %s in %d ms",
                settings.workspace_root,
                int((time.perf_counter() - started) * 1000),
            )
        except Exception:
            logger.exception("watcher failed to start; sweeps continue")

    logger.info("watcher starting in %s", settings.workspace_root)

    _READY.clear()
    threading.Thread(target=_start, name="watcher", daemon=True).start()
    _OBSERVER = observer
    return observer


def wait_until_ready(timeout: float) -> bool:
    """Block until the observer has started (tests / diagnostics)."""
    return _READY.wait(timeout)


def is_alive() -> bool:
    return _OBSERVER is not None and _OBSERVER.is_alive()
