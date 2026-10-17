"""Filesystem watcher: save events → debounced queue (never index in callback).

Registered per interesting directory (non-recursive) with a pruned walk — a
single recursive schedule() walks .venv over the Docker Desktop bind mount and
blocks for tens of seconds (handoff §4.5). New directories are picked up from
parent directory-created events; the sweep remains the backstop for misses.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from simple_code_indexer.config import Settings, is_allowed, is_temp_name
from simple_code_indexer.indexer import WorkItem, WorkQueue

logger = logging.getLogger(__name__)

_OBSERVER: BaseObserver | None = None
_READY = threading.Event()


def interesting_dirs(settings: Settings) -> list[str]:
    """Workspace dirs that may hold indexed files (ignored dirs pruned)."""
    dirs: list[str] = []
    for dirpath, dirnames, _filenames in os.walk(settings.workspace_root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in settings.ignore_dirs]
        dirs.append(dirpath)
    return dirs


def build_handler(
    settings: Settings,
    work_queue: WorkQueue,
    watch_dir: Callable[[str], None],
) -> FileSystemEventHandler:
    debounce_s = settings.debounce_ms / 1000.0

    def interesting(path: str) -> bool:
        p = Path(path)
        if not is_allowed(settings, p) or is_temp_name(p.name):
            return False
        return not any(part in settings.ignore_dirs for part in p.parts)

    def enqueue(item: WorkItem) -> None:
        try:
            work_queue.put_nowait(item)
        except queue.Full:
            # Writer is behind; the reconciliation sweep will cover it.
            logger.warning("work queue full, dropping %s", item.path)

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

        def _fire(self, path: str) -> None:
            self._timers.pop(path, None)
            enqueue(WorkItem(Path(path)))

        def on_created(self, event: FileSystemEvent) -> None:
            if event.is_directory:
                watch_dir(str(event.src_path))
            else:
                self._schedule_index(str(event.src_path))

        def on_modified(self, event: FileSystemEvent) -> None:
            if not event.is_directory:
                self._schedule_index(str(event.src_path))

        def on_moved(self, event: FileSystemEvent) -> None:
            if event.is_directory:
                watch_dir(str(event.dest_path))
                return
            if interesting(str(event.src_path)):
                enqueue(WorkItem(Path(str(event.src_path)), deleted=True))
            self._schedule_index(str(event.dest_path))

        def on_deleted(self, event: FileSystemEvent) -> None:
            if not event.is_directory and interesting(str(event.src_path)):
                enqueue(WorkItem(Path(str(event.src_path)), deleted=True))

    return Handler()


def start_watcher(settings: Settings, work_queue: WorkQueue) -> BaseObserver:
    """Start watches on a daemon thread; returns without blocking serve."""
    global _OBSERVER

    observer = Observer()
    handler: FileSystemEventHandler | None = None

    def watch_dir(path: str) -> None:
        if handler is None or Path(path).name in settings.ignore_dirs:
            return
        try:
            observer.schedule(handler, path, recursive=False)
        except Exception:
            logger.exception("failed to watch %s", path)

    handler = build_handler(settings, work_queue, watch_dir)

    def _start() -> None:
        try:
            for directory in interesting_dirs(settings):
                watch_dir(directory)
            observer.start()
            _READY.set()
        except Exception:
            logger.exception("watcher failed to start")

    _READY.clear()
    threading.Thread(target=_start, name="watcher", daemon=True).start()
    _OBSERVER = observer
    return observer


def wait_until_ready(timeout: float) -> bool:
    """Block until the observer has started (tests / diagnostics)."""
    return _READY.wait(timeout)


def is_alive() -> bool:
    return _OBSERVER is not None and _OBSERVER.is_alive()
