"""Index unit of work: index_one_file, reconciliation sweep (backstop),
and the single-writer queue consumer."""

from __future__ import annotations

import hashlib
import logging
import os
import queue
import sqlite3
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from simple_code_indexer import db, embed, parse, vector_store
from simple_code_indexer.config import Settings, is_allowed, is_temp_name
from simple_code_indexer.errors import EmbedError, VectorStoreUnavailable
from simple_code_indexer.ignore import IgnoreRules
from simple_code_indexer.models import Chunk, FileRecord

logger = logging.getLogger(__name__)

# Last successful sweep completion (UTC ISO); read by get_status.
LAST_SWEEP: str | None = None

# Completed sweeps since process start; the sweep timer uses it to tell whether
# the request it queued has run yet.
SWEEP_GENERATION = 0

# Minimum idle spacing between drain-triggered vector flushes.
FLUSH_DEBOUNCE_S = 30.0

# Sweep pacing: an enabled periodic sweep doubles its interval while the
# workspace stays idle, up to this cap. With sweeps disabled a dormant timer
# polls this often and temporarily re-enables sweeps while chunks are pending.
SWEEP_BACKOFF_MAX_S = 600.0
DORMANT_POLL_S = 60.0

_activity_lock = threading.Lock()
_watcher_events = 0


def note_watcher_event() -> None:
    """Record one queued watcher event (the sweep backoff's activity signal)."""
    global _watcher_events
    with _activity_lock:
        _watcher_events += 1


def watcher_activity() -> int:
    """Count of watcher events queued since process start."""
    with _activity_lock:
        return _watcher_events


def next_sweep_delay(base_s: float, current_s: float, *, idle: bool) -> float:
    """Double the sweep interval while idle, then clamp to the backoff cap."""
    if not idle:
        return base_s
    return min(max(current_s, base_s) * 2, max(SWEEP_BACKOFF_MAX_S, base_s))


class IndexOutcome(NamedTuple):
    path: str
    status: str  # indexed | skipped_unchanged | skipped_filtered | error
    duration_ms: int


class SweepStats(NamedTuple):
    checked: int
    indexed: int
    unchanged: int
    removed: int
    errors: int
    filtered: int = 0
    ignored_dirs: int = 0
    ignored_files: int = 0


# Counts of the last completed sweep; read by get_status.
LAST_SWEEP_STATS: SweepStats | None = None


@dataclass(slots=True)
class WalkStats:
    """Paths pruned by `.gitignore` during one workspace walk."""

    ignored_dirs: int = 0
    ignored_files: int = 0


@dataclass(frozen=True, slots=True)
class WorkItem:
    """Queue item: index path (or remove it when deleted=True)."""

    path: Path
    deleted: bool = False


class SweepRequest:
    """Queue sentinel: run a reconciliation sweep in the writer thread."""


SWEEP_REQUEST = SweepRequest()
WorkQueue = queue.Queue[WorkItem | SweepRequest]


def new_work_queue(maxsize: int = 500) -> WorkQueue:
    return queue.Queue(maxsize=maxsize)


def relative_path(settings: Settings, path: Path) -> str | None:
    """Workspace-relative POSIX path, or None when outside the workspace."""
    try:
        return path.resolve().relative_to(settings.workspace_root.resolve()).as_posix()
    except ValueError:
        return None


def _is_ignored(settings: Settings, rel: str) -> bool:
    return any(part in settings.ignore_dirs for part in rel.split("/"))


def iter_workspace_files(
    settings: Settings,
    rules: IgnoreRules | None = None,
    stats: WalkStats | None = None,
) -> Iterator[Path]:
    """Yield allowlisted files, pruning ignored dirs (rglob would walk .venv).

    Directory pruning keeps build trees and `.gitignore`d paths out of the walk
    entirely; `stats` counts what `.gitignore` excluded.
    """
    root = settings.workspace_root
    rules = rules or IgnoreRules(root)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        kept: list[str] = []
        for name in dirnames:
            if name in settings.ignore_dirs:
                continue
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if rules.is_ignored(rel, is_dir=True):
                if stats is not None:
                    stats.ignored_dirs += 1
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            if is_temp_name(name):
                continue
            path = Path(dirpath) / name
            if not is_allowed(settings, path):
                continue
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if rules.is_ignored(rel):
                if stats is not None:
                    stats.ignored_files += 1
                continue
            yield path


def index_one_file(
    settings: Settings,
    path: Path,
    rules: IgnoreRules | None = None,
) -> IndexOutcome:
    """Parse + store one file; hash short-circuit on no-op saves."""
    start = time.perf_counter()
    rel = relative_path(settings, path)
    rules = rules or IgnoreRules(settings.workspace_root)

    def done(status: str, detail: str = "") -> IndexOutcome:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.log(
            logging.INFO if status == "indexed" else logging.DEBUG,
            "%s %s in %d ms%s",
            status,
            rel or path,
            duration_ms,
            detail,
        )
        return IndexOutcome(
            path=rel or str(path),
            status=status,
            duration_ms=duration_ms,
        )

    if (
        rel is None
        or not is_allowed(settings, path)
        or is_temp_name(path.name)
        or _is_ignored(settings, rel)
        or rules.is_ignored(rel)
    ):
        return done("skipped_filtered")
    try:
        data = path.read_bytes()
    except OSError:
        logger.warning("cannot read %s", path, exc_info=True)
        return done("error")

    digest = hashlib.sha256(data).hexdigest()
    source = data.decode("utf-8", errors="replace")
    try:
        with db.connect(settings.index_db_path) as conn:
            db.ensure_schema(conn)
            if db.file_hash(conn, rel) == digest:
                return done("skipped_unchanged")
            record = FileRecord(
                path=rel,
                language=parse.detect_language(path) or "text",
                size=len(data),
                sha256=digest,
                mtime=path.stat().st_mtime,
            )
            symbols = parse.extract_symbols(path, source)
            chunks = parse.chunk_source(source)
            for chunk in chunks:
                logger.debug(
                    "chunk %d of %s: lines %d-%d, %d chars",
                    chunk.chunk_index,
                    rel,
                    chunk.start_line,
                    chunk.end_line,
                    len(chunk.content),
                )
            with conn:
                file_id = db.upsert_file(conn, record)
                db.replace_file_symbols(conn, file_id, symbols)
                db.replace_file_chunks(conn, file_id, chunks)
        _embed_and_store(settings, rel, chunks)
        return done(
            "indexed",
            f": {len(data)} byte(s), {len(source.splitlines())} line(s), "
            f"{len(symbols)} symbol(s), {len(chunks)} chunk(s), "
            f"language={record.language}",
        )
    except (sqlite3.Error, OSError, ValueError):
        logger.exception("failed to index %s", path)
        return done("error")


def _embed_and_store(settings: Settings, rel: str, chunks: list[Chunk]) -> bool:
    """Embed + upsert vectors; fail soft and record embedding_state.

    Returns True when every chunk got a vector, so retry callers can stop at the
    first failure instead of hammering a service that is down.
    """
    if not chunks:
        return True
    status = "ok"
    vector_ids: dict[int, str] = {}
    started = time.perf_counter()
    try:
        vectors = embed.embed_documents(
            settings, [c.content for c in chunks], title=rel
        )
        logger.debug(
            "embedded %d chunk(s) for %s in %d ms",
            len(chunks),
            rel,
            int((time.perf_counter() - started) * 1000),
        )
        if len(vectors) != len(chunks):
            raise EmbedError(
                f"embedding returned {len(vectors)} vectors for {len(chunks)} chunks"
            )
        try:
            ids = vector_store.upsert_chunks(settings, rel, list(zip(chunks, vectors)))
            if len(ids) != len(chunks):
                raise VectorStoreUnavailable(
                    f"vector store returned {len(ids)} ids for {len(chunks)} chunks"
                )
            logger.debug("stored %d vector(s) for %s", len(ids), rel)
            vector_ids = dict(zip((c.chunk_index for c in chunks), ids))
        except VectorStoreUnavailable:
            status = "error"
            logger.warning("vector upsert failed for %s", rel, exc_info=True)
    except EmbedError:
        status = "error"
        logger.warning("embedding failed for %s", rel, exc_info=True)
    try:
        with db.connect(settings.index_db_path) as conn, conn:
            wanted = {c.chunk_index for c in chunks}
            rows = [
                (chunk_id, vector_ids.get(chunk_index, ""), status)
                for chunk_id, chunk_index in db.chunk_ids_for_path(conn, rel)
                if chunk_index in wanted
            ]
            db.record_embedding_state(conn, rows)
    except sqlite3.Error:
        logger.warning("embedding_state update failed for %s", rel, exc_info=True)
    return status == "ok"


def pending_embedding_count(settings: Settings) -> int:
    """Chunks still waiting for a vector; 0 when the index is unreadable."""
    try:
        with db.connect(settings.index_db_path, readonly=True) as conn:
            return db.embedding_counts(conn)["pending"]
    except (OSError, sqlite3.Error):
        return 0


def reembed_pending(settings: Settings) -> int:
    """Re-embed chunks that have no vector; unaffected by hash/mtime skips.

    Called at the start of every sweep (including the startup reconcile), so a
    fail-soft embed or Qdrant outage heals without deleting the index. Stops at
    the first failure: the service is down for the rest too, and the next sweep
    retries the remainder.
    """
    with db.connect(settings.index_db_path) as conn:
        db.ensure_schema(conn)
        pending = db.chunks_needing_embedding(conn)
    by_path: dict[str, list[Chunk]] = {}
    for rel, chunk in pending:
        by_path.setdefault(rel, []).append(chunk)
    logger.debug(
        "re-embed pass: %d pending chunk(s) in %d file(s)",
        len(pending),
        len(by_path),
    )
    reembedded = 0
    for rel, chunks in by_path.items():
        if not _embed_and_store(settings, rel, chunks):
            logger.debug(
                "re-embed stopped at %s; %d file(s) not retried",
                rel,
                len(by_path) - reembedded - 1,
            )
            break
        reembedded += 1
    if reembedded:
        logger.info("re-embedded pending chunks for %d file(s)", reembedded)
    return reembedded


def sweep(settings: Settings, rules: IgnoreRules | None = None) -> SweepStats:
    """Walk the workspace; re-index drift, drop deleted paths."""
    global LAST_SWEEP, LAST_SWEEP_STATS, SWEEP_GENERATION
    started = time.perf_counter()
    rules = rules or IgnoreRules(settings.workspace_root)

    reembed_pending(settings)
    with db.connect(settings.index_db_path) as conn:
        db.ensure_schema(conn)
        stored = {
            str(row["path"]): (float(row["mtime"]), int(row["size"]))
            for row in conn.execute("SELECT path, mtime, size FROM files")
        }

    checked = indexed = unchanged = filtered = errors = 0
    seen: set[str] = set()
    walk = WalkStats()
    for path in iter_workspace_files(settings, rules, walk):
        rel = relative_path(settings, path)
        if rel is None:
            continue
        seen.add(rel)
        checked += 1
        try:
            stat = path.stat()
        except OSError:
            continue  # vanished mid-sweep; next pass handles removal
        if stored.get(rel) == (stat.st_mtime, stat.st_size):
            unchanged += 1
            continue
        status = index_one_file(settings, path, rules).status
        if status == "indexed":
            indexed += 1
        elif status == "skipped_unchanged":
            unchanged += 1
        elif status == "skipped_filtered":
            filtered += 1
        else:
            errors += 1

    stale_paths = sorted(stored.keys() - seen)
    removed = 0
    if stale_paths:
        logger.debug(
            "sweep: removing %d stale path(s): %s", len(stale_paths), stale_paths
        )
    with db.connect(settings.index_db_path) as conn, conn:
        for stale in stale_paths:
            db.delete_file(conn, stale)
            removed += 1
    for stale in stale_paths:
        _delete_vectors(settings, stale)
    try:
        vector_store.flush(settings)
    except Exception:
        logger.warning("vector store flush failed", exc_info=True)

    LAST_SWEEP = datetime.now(UTC).isoformat(timespec="seconds")
    stats = SweepStats(
        checked=checked,
        indexed=indexed,
        unchanged=unchanged,
        removed=removed,
        errors=errors,
        filtered=filtered,
        ignored_dirs=walk.ignored_dirs,
        ignored_files=walk.ignored_files,
    )
    LAST_SWEEP_STATS = stats
    SWEEP_GENERATION += 1
    logger.info(
        "sweep: checked=%d indexed=%d unchanged=%d filtered=%d removed=%d "
        "errors=%d ignored_dirs=%d ignored_files=%d in %d ms",
        stats.checked,
        stats.indexed,
        stats.unchanged,
        stats.filtered,
        stats.removed,
        stats.errors,
        stats.ignored_dirs,
        stats.ignored_files,
        int((time.perf_counter() - started) * 1000),
    )
    return stats


def _delete_vectors(settings: Settings, rel: str) -> None:
    try:
        vector_store.delete_by_path(settings, rel)
    except VectorStoreUnavailable:
        # Orphan vectors are harmless: semantic hits are re-checked against SQLite.
        logger.warning("vector delete failed for %s", rel, exc_info=True)


def remove_file(settings: Settings, path: Path) -> None:
    """Drop a deleted path from the index (tombstone work item)."""
    rel = relative_path(settings, path)
    if rel is None:
        return
    with db.connect(settings.index_db_path) as conn, conn:
        db.delete_file(conn, rel)
    _delete_vectors(settings, rel)
    logger.debug("removed %s from the index", rel)


def writer_loop(
    settings: Settings,
    work_queue: WorkQueue,
    stop_event: threading.Event | None = None,
) -> None:
    """Single index writer: consumes paths, tombstones and sweep requests.

    When the queue drains, the vector store is flushed, at most once per
    FLUSH_DEBOUNCE_S (a WAL checkpoint for sqlite-vec, a file write for FAISS,
    a no-op for Qdrant). A sweep already flushes at its end. A stop event lets
    the owning runtime end the thread without losing the process; queued items
    left behind are recovered by the next startup sweep.
    """
    last_flush = 0.0
    rules = IgnoreRules(settings.workspace_root)
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        try:
            item = work_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        logger.debug(
            "index queue: %s (%d waiting)",
            "sweep" if isinstance(item, SweepRequest) else item,
            work_queue.qsize(),
        )
        try:
            if isinstance(item, SweepRequest):
                sweep(settings, rules)
            elif item.deleted:
                remove_file(settings, item.path)
            else:
                index_one_file(settings, item.path, rules)
        except Exception:
            logger.exception("writer failed on %s", item)
        finally:
            work_queue.task_done()
        if work_queue.empty():
            now = time.monotonic()
            if now - last_flush >= FLUSH_DEBOUNCE_S:
                try:
                    vector_store.flush(settings)
                    logger.debug(
                        "vector store flush after idle queue (%s)",
                        vector_store.describe(settings),
                    )
                except Exception:
                    logger.warning("vector store flush failed", exc_info=True)
                last_flush = now
