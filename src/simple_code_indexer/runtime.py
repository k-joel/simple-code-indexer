"""Writer runtime: the single per-workspace owner of the index.

Used by the embedded MCP server (``mode: embedded``) and by the sidecar daemon.
The runtime owns the workspace lease, the writer thread, the watcher, the sweep
timer, the service probe, and the writer heartbeat. Shutdown always finalizes
(persists vectors and clears dirty flags) *before* releasing the lease.
"""

from __future__ import annotations

import logging
import os
import queue
import sqlite3
import threading
import time
from datetime import UTC, datetime
from typing import Any

from watchdog.observers.api import BaseObserver

from simple_code_indexer import (
    db,
    indexer,
    services,
    vector_store,
    watcher,
    workspace_lock,
)
from simple_code_indexer.config import Settings, is_allowed
from simple_code_indexer.errors import VectorStoreUnavailable, WorkspaceBusy
from simple_code_indexer.languages import catalog
from simple_code_indexer.parse import detect_language
from simple_code_indexer.registry import start_prefetch_thread

logger = logging.getLogger(__name__)

# Long enough for an in-flight embedding request (EMBED_TIMEOUT_S default 15 s).
DRAIN_TIMEOUT_S = 30.0
_STOP_TICK_S = 0.5


class WriterRuntime:
    """Owns every writer component for one workspace, in one process."""

    def __init__(self, settings: Settings, *, started_at: float | None = None) -> None:
        self.settings = settings
        self._started_at = time.monotonic() if started_at is None else started_at
        self._started_at_iso = datetime.now(UTC).isoformat(timespec="seconds")
        self._lease = workspace_lock.WorkspaceLock(settings.index_db_path)
        self._stop = threading.Event()
        self._stopped = False
        self._started = False
        self._work_queue: indexer.WorkQueue | None = None
        self._writer_thread: threading.Thread | None = None
        self._sweep_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._observer: BaseObserver | None = None

    @property
    def lease(self) -> workspace_lock.WorkspaceLock:
        return self._lease

    def start(self) -> None:
        """Acquire the writer lease and start every writer component."""
        if self._started:
            return
        if not self._lease.acquire():
            raise WorkspaceBusy(str(self.settings.index_db_path))
        logger.info("workspace lock acquired: %s", self.settings.index_db_path)
        self._started = True
        try:
            self._start_components()
        except BaseException:
            self.stop()
            raise

    def _start_components(self) -> None:
        settings = self.settings
        phase = time.monotonic()
        services.ensure_managed_services(settings)
        logger.info(
            "startup: managed services in %d ms (%s)",
            int((time.monotonic() - phase) * 1000),
            dict(services.LAST_STATE),
        )
        start_prefetch_thread()
        backend = vector_store.backend(settings)
        phase = time.monotonic()
        with db.connect(settings.index_db_path) as conn:
            db.ensure_schema(conn)
            with conn:
                invalidated = db.ensure_index_identity(
                    conn,
                    backend=backend,
                    identity=vector_store.identity(settings),
                )
        logger.info(
            "startup: schema + identity in %d ms (backend=%s, invalidated=%s)",
            int((time.monotonic() - phase) * 1000),
            backend,
            invalidated,
        )
        _reconcile_language_catalog(settings)
        if invalidated:
            logger.warning(
                "vector store %s changed — index cleared for a full re-index",
                vector_store.describe(settings),
            )
            try:
                vector_store.reset(settings)
            except VectorStoreUnavailable:
                logger.warning("cannot reset the vector index", exc_info=True)
        phase = time.monotonic()
        try:
            vector_store.ensure_ready(settings)
            flagged = vector_store.reconcile(settings)
            if flagged:
                logger.info("%d chunk(s) flagged for re-embedding", flagged)
        except VectorStoreUnavailable:
            logger.warning("vector store unavailable at startup", exc_info=True)
        logger.info(
            "startup: vector store in %d ms (%s)",
            int((time.monotonic() - phase) * 1000),
            vector_store.describe(settings),
        )
        threading.Thread(
            target=_probe_services,
            args=(settings,),
            name="service-probe",
            daemon=True,
        ).start()

        # Single writer owns all index writes; startup reconcile goes through it.
        work_queue = indexer.new_work_queue()
        self._work_queue = work_queue
        self._writer_thread = threading.Thread(
            target=indexer.writer_loop,
            args=(settings, work_queue, self._stop),
            name="index-writer",
            daemon=True,
        )
        self._writer_thread.start()
        work_queue.put(indexer.SWEEP_REQUEST)
        self._observer = watcher.start_watcher(settings, work_queue)
        logger.info("startup: watcher started")
        self._sweep_thread = threading.Thread(
            target=_periodic_sweep,
            args=(settings, work_queue, self._stop),
            name="sweep-timer",
            daemon=True,
        )
        self._sweep_thread.start()

        _set_writer_meta(
            settings,
            **{
                db.WRITER_PID_KEY: str(os.getpid()),
                db.WRITER_HEARTBEAT_KEY: f"{time.time():.3f}",
                db.WRITER_STARTED_AT_KEY: self._started_at_iso,
            },
        )
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="writer-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        logger.info("writer runtime ready (pid=%d)", os.getpid())

    def _heartbeat_loop(self) -> None:
        interval = max(0.5, self.settings.heartbeat_s)
        while not self._stop.wait(interval):
            _set_writer_meta(
                self.settings,
                **{
                    db.WRITER_PID_KEY: str(os.getpid()),
                    db.WRITER_HEARTBEAT_KEY: f"{time.time():.3f}",
                },
            )

    def stop(self) -> None:
        """Stop writers, flush while the lease is held, then release the lease."""
        if self._stopped:
            return
        self._stopped = True
        logger.info("shutting down after %.1fs", time.monotonic() - self._started_at)
        try:
            watcher.stop_watcher(self._observer)
        except Exception:
            logger.warning("cannot stop the watcher cleanly", exc_info=True)
        self._stop.set()
        self._join(self._sweep_thread, 2.0)
        self._join(self._heartbeat_thread, 2.0)
        self._join(self._writer_thread, DRAIN_TIMEOUT_S)
        _set_writer_meta(
            self.settings,
            **{
                db.WRITER_PID_KEY: "",
                db.WRITER_HEARTBEAT_KEY: f"{time.time():.3f}",
            },
        )
        try:
            vector_store.flush(self.settings)
            logger.info(
                "vector store flushed (%s)", vector_store.describe(self.settings)
            )
        except Exception:
            logger.warning("vector store flush failed at shutdown", exc_info=True)
        try:
            with db.connect(self.settings.index_db_path, readonly=True) as conn:
                logger.info("final index: %s", db.stats(conn))
        except Exception:
            logger.debug("cannot read the final index stats", exc_info=True)
        self._lease.release()
        logger.info("workspace lock released")

    def status(self) -> dict[str, Any]:
        stats = indexer.LAST_SWEEP_STATS
        alive = not self._stopped
        return {
            "role": "writer",
            "writer_pid": os.getpid() if alive else None,
            "writer_ok": alive,
            "writer_heartbeat_age_s": 0.0 if alive else None,
            "watcher_alive": watcher.is_alive(),
            "last_sweep": indexer.LAST_SWEEP,
            "ignored_dirs": stats.ignored_dirs if stats else 0,
            "ignored_files": stats.ignored_files if stats else 0,
            "vector_store_ok": vector_store.last_ok(self.settings),
            "vector_index_age_s": vector_index_age(self.settings),
            "services": dict(services.LAST_STATE),
            "started_at": self._started_at_iso,
        }

    @staticmethod
    def _join(thread: threading.Thread | None, timeout: float) -> None:
        if thread is None:
            return
        thread.join(timeout)
        if thread.is_alive():
            logger.warning("thread %s did not stop within %.0f s", thread.name, timeout)


def _set_writer_meta(settings: Settings, **values: str) -> None:
    """Best-effort writer liveness row; a failure must never stop indexing."""
    try:
        with db.connect(settings.index_db_path) as conn, conn:
            for key, value in values.items():
                db.set_meta(conn, key, value)
    except sqlite3.Error:
        logger.debug("cannot update the writer heartbeat", exc_info=True)


def writer_state(settings: Settings, *, stale_after_s: float) -> dict[str, Any]:
    """Writer liveness from `meta` (readers use this when no daemon is reachable)."""
    result: dict[str, Any] = {
        "writer_pid": None,
        "writer_heartbeat_age_s": None,
        "writer_ok": False,
    }
    try:
        with db.try_connect_readonly(settings.index_db_path) as conn:
            if conn is None:
                return result
            pid = db.get_meta(conn, db.WRITER_PID_KEY)
            beat = db.get_meta(conn, db.WRITER_HEARTBEAT_KEY)
    except sqlite3.Error:
        logger.debug("cannot read the writer heartbeat", exc_info=True)
        return result
    if pid:
        try:
            result["writer_pid"] = int(pid)
        except ValueError:
            result["writer_pid"] = None
    age: float | None = None
    if beat:
        try:
            age = max(0.0, time.time() - float(beat))
        except ValueError:
            age = None
    result["writer_heartbeat_age_s"] = age
    result["writer_ok"] = (
        result["writer_pid"] is not None and age is not None and age <= stale_after_s
    )
    return result


def vector_index_age(settings: Settings) -> float | None:
    """Age of the vector index view: file mtime for FAISS, live for Qdrant."""
    if vector_store.backend(settings) == "faiss":
        from simple_code_indexer import faiss_store

        return faiss_store.vector_index_age_s(settings)
    return 0.0 if vector_store.last_ok(settings) else None


def _request_sweep(work_queue: indexer.WorkQueue, stop_event: threading.Event) -> bool:
    """Queue a sweep unless shutting down; bounded so stop cannot hang."""
    while not stop_event.is_set():
        try:
            work_queue.put(indexer.SWEEP_REQUEST, timeout=_STOP_TICK_S)
            return True
        except queue.Full:
            continue
    return False


def _periodic_sweep(
    settings: Settings,
    work_queue: indexer.WorkQueue,
    stop_event: threading.Event,
) -> None:
    """Request reconciliation sweeps on a schedule that backs off when idle."""
    if not settings.sweep_enabled:
        logger.info(
            "periodic sweep: off (watcher only); checking pending embeddings "
            "every %.0f s",
            indexer.DORMANT_POLL_S,
        )
        _dormant_sweep(settings, work_queue, stop_event)
        return
    base = settings.sweep_seconds
    logger.info(
        "periodic sweep: on (base %.0f s, backoff cap %.0f s)",
        base,
        indexer.SWEEP_BACKOFF_MAX_S,
    )
    delay = base
    events = indexer.watcher_activity()
    generation = indexer.SWEEP_GENERATION
    while not stop_event.is_set():
        if stop_event.wait(delay):
            return
        stats = indexer.LAST_SWEEP_STATS
        completed = indexer.SWEEP_GENERATION > generation
        changed = bool(
            completed
            and stats is not None
            and (stats.indexed or stats.removed or stats.errors)
        )
        # Back off when nothing happened: no watcher events or an empty sweep.
        idle = indexer.watcher_activity() == events or not changed
        delay = indexer.next_sweep_delay(base, delay, idle=idle)
        events = indexer.watcher_activity()
        generation = indexer.SWEEP_GENERATION
        try:
            if _request_sweep(work_queue, stop_event):
                logger.debug("periodic sweep requested (next in %.0f s)", delay)
        except Exception:
            # Keep the timer alive: one bad request must not stop all sweeps.
            logger.exception("cannot request a periodic sweep")


def _dormant_sweep(
    settings: Settings,
    work_queue: indexer.WorkQueue,
    stop_event: threading.Event,
) -> None:
    """Disabled sweeps: run one only while embeddings are behind."""
    delay = indexer.DORMANT_POLL_S
    pending_before: int | None = None
    generation = indexer.SWEEP_GENERATION
    while not stop_event.is_set():
        if stop_event.wait(delay):
            return
        pending = indexer.pending_embedding_count(settings)
        if pending == 0:
            delay = indexer.DORMANT_POLL_S
            pending_before = None
            continue
        changed = pending_before is not None and pending != pending_before
        delay = indexer.next_sweep_delay(
            indexer.DORMANT_POLL_S, delay, idle=not changed
        )
        pending_before = pending
        # Do not pile requests behind a sweep that is still running.
        if indexer.SWEEP_GENERATION <= generation:
            continue
        generation = indexer.SWEEP_GENERATION
        try:
            if _request_sweep(work_queue, stop_event):
                logger.info(
                    "temporary sweep: %d pending embedding(s); next check in %.0f s",
                    pending,
                    delay,
                )
        except Exception:
            logger.exception("cannot request a temporary sweep")


def _reconcile_language_catalog(settings: Settings) -> None:
    """Drop rows the catalog no longer covers after a catalog change.

    Language ids can change between catalog versions (``c_sharp`` → ``csharp``)
    and a previously indexed path can become a denied data format. Dropping those
    rows is enough: the startup sweep re-indexes a path that is no longer stored,
    so the file comes back under its current language id. No schema change and no
    full re-embed.
    """
    with db.connect(settings.index_db_path) as conn:
        stored_version = db.get_meta(conn, "language_catalog_version")
        if stored_version == catalog.VERSION:
            return
        rows = conn.execute("SELECT path, language FROM files").fetchall()
        stale: list[str] = []
        for row in rows:
            path = str(row["path"])
            candidate = settings.workspace_root / path
            if not is_allowed(settings, candidate) or (
                detect_language(candidate) != str(row["language"])
            ):
                stale.append(path)
        with conn:
            for path in stale:
                db.delete_file(conn, path)
            db.set_meta(conn, "language_catalog_version", catalog.VERSION)
    if stale:
        logger.info(
            "language catalog %s: dropping %d stale path(s) for re-index",
            catalog.VERSION,
            len(stale),
        )
        for path in stale:
            try:
                vector_store.delete_by_path(settings, path)
            except VectorStoreUnavailable:
                logger.warning("cannot drop vectors for %s", path, exc_info=True)
    else:
        logger.debug("language catalog %s: no stale paths", catalog.VERSION)


def _probe_services(settings: Settings) -> None:
    """Warm vector store + embed endpoint off the serve path; feeds status flags."""
    from simple_code_indexer import embed

    try:
        vector_store.ensure_ready(settings)
        logger.info(
            "service probe: vector store ready (%s)", vector_store.describe(settings)
        )
    except Exception:
        logger.exception("vector store probe failed")
    try:
        embed.embed_texts(settings, ["service probe"])
        logger.info(
            "service probe: embedding endpoint answered (%s)", settings.embed_base_url
        )
    except Exception:
        logger.exception("embed probe failed")
