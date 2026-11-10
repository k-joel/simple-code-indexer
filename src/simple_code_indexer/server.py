"""MCP stdio server: initialize / tools/list / tools/call for the harness.

No outputSchema, no capabilities.tasks, no execution.taskSupport — the harness
rejects them (ADR-0006). Logs go to stderr and <workspace>/.simple-ci/log/sci.log;
stdout is the MCP channel.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from simple_code_indexer import (
    db,
    embed,
    indexer,
    logging_setup,
    parent_watch,
    services,
    vector_store,
    watcher,
    workspace_lock,
)
from simple_code_indexer.config import Settings, load_settings
from simple_code_indexer.errors import (
    ConfigError,
    EmbedError,
    VectorStoreUnavailable,
)
from simple_code_indexer.registry import get_registry, start_prefetch_thread

logger = logging.getLogger("simple_code_indexer")

_TOOLS = [
    types.Tool(
        name="search_code",
        description="Search the index; semantic=true for vector hits.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "semantic": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="symbol_lookup",
        description="Resolve a symbol name to its definition site.",
        input_schema={
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="get_status",
        description="Index health: counts, watcher, services.",
        input_schema={"type": "object", "properties": {}},
    ),
]


async def _on_list_tools(
    ctx: Any, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    logger.debug("tools/list")
    return types.ListToolsResult(tools=_TOOLS)


def _json_result(payload: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload))]
    )


def _status_payload(settings: Settings) -> dict[str, Any]:
    with db.connect(settings.index_db_path, readonly=True) as conn:
        counts = db.stats(conn)
        embedding = db.embedding_counts(conn)
    registry = get_registry()
    from simple_code_indexer.parse import _parsers

    log_file = logging_setup.active_log_file()
    sweep_stats = indexer.LAST_SWEEP_STATS
    return {
        "files_indexed": counts["files"],
        "symbols_indexed": counts["symbols"],
        "chunks_indexed": counts["chunks"],
        "vectors_indexed": embedding["embedded"],
        "pending_embeddings": embedding["pending"],
        "watcher_alive": watcher.is_alive(),
        "last_sweep": indexer.LAST_SWEEP,
        "ignored_dirs": sweep_stats.ignored_dirs if sweep_stats else 0,
        "ignored_files": sweep_stats.ignored_files if sweep_stats else 0,
        "vector_store": vector_store.backend(settings),
        "vector_store_ok": vector_store.last_ok(settings),
        "vector_index": vector_store.describe(settings),
        "embed_ok": embed.LAST_OK is True,
        "plugins_loaded": len(registry),
        "grammars_ready": len(_parsers),
        "workspace": str(settings.workspace_root),
        "index_db": str(settings.index_db_path),
        "config_file": str(settings.config_source) if settings.config_source else None,
        "config_files": [str(path) for path in settings.config_sources],
        "log_file": str(log_file) if log_file else None,
        "log_level": settings.log_level,
        "services": dict(services.LAST_STATE),
    }


def _semantic_hits(settings: Settings, query: str, limit: int) -> dict[str, Any]:
    with db.connect(settings.index_db_path, readonly=True) as conn:
        embedding = db.embedding_counts(conn)
    ready = embedding["pending"] == 0
    embed_started = time.perf_counter()
    try:
        vector = embed.embed_query(settings, query)
        embed_ms = int((time.perf_counter() - embed_started) * 1000)
        search_started = time.perf_counter()
        # Over-fetch: adjacent chunks overlap, so the top `limit` vector hits
        # can collapse to fewer distinct spans after dedupe below.
        vector_hits = vector_store.search(settings, vector, limit * 3)
        search_ms = int((time.perf_counter() - search_started) * 1000)
    except (EmbedError, VectorStoreUnavailable) as exc:
        logger.warning(
            "semantic search failed for %.200r (store=%s, embed_ok=%s)",
            query,
            vector_store.describe(settings),
            embed.LAST_OK,
            exc_info=True,
        )
        return {
            "hits": [],
            "source": "semantic",
            "ready": False,
            "pending_embeddings": embedding["pending"],
            "message": f"semantic search unavailable: {exc}",
        }
    hits: list[dict[str, Any]] = []
    kept_spans: dict[str, list[tuple[int, int]]] = {}
    orphans = overlaps = 0
    with db.connect(settings.index_db_path, readonly=True) as conn:
        for vector_hit in vector_hits:
            span = db.get_chunk(conn, vector_hit.path, vector_hit.chunk_index)
            if span is None:
                orphans += 1  # delete raced; the lexical row is source of truth
                continue
            if any(
                span.start_line <= end and start <= span.end_line
                for start, end in kept_spans.get(vector_hit.path, [])
            ):
                overlaps += 1  # overlapping window of a higher-ranked chunk
                continue
            kept_spans.setdefault(vector_hit.path, []).append(
                (span.start_line, span.end_line)
            )
            hits.append(
                {
                    "file": vector_hit.path,
                    "line": span.start_line,
                    "end_line": span.end_line,
                    "snippet": span.content[:300],
                    "score": vector_hit.score,
                    "source": "semantic",
                }
            )
            if len(hits) == limit:
                break
    logger.debug(
        "semantic search: %d vector hit(s), %d orphan(s), %d overlapping, "
        "%d returned, embed=%d ms, store=%d ms",
        len(vector_hits),
        orphans,
        overlaps,
        len(hits),
        embed_ms,
        search_ms,
    )
    if not hits:
        log = logger.warning if not ready else logger.info
        log(
            "semantic search returned no hits (pending=%d, store=%s, "
            "store_ok=%s, embed_ok=%s)",
            embedding["pending"],
            vector_store.describe(settings),
            vector_store.last_ok(settings),
            embed.LAST_OK,
        )
    payload: dict[str, Any] = {
        "hits": hits,
        "source": "semantic",
        "ready": ready,
        "pending_embeddings": embedding["pending"],
    }
    if not ready:
        message = (
            f"semantic index is warming up: {embedding['pending']} chunk(s) "
            "still pending embedding"
        )
        if hits:
            message += " (results may be incomplete)"
        payload["message"] = message
    return payload


def _search_code(settings: Settings, args: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    query = str(args.get("query", ""))
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))
    semantic = bool(args.get("semantic", False))
    if not query.strip():
        logger.debug("empty search query (semantic=%s)", semantic)
        return {"hits": [], "source": "semantic" if semantic else "lexical"}
    if semantic:
        return _semantic_hits(settings, query, limit)
    with db.connect(settings.index_db_path, readonly=True) as conn:
        hits = db.fts_search(conn, query, limit)
    logger.debug(
        "lexical search %.200r: %d hit(s) in %d ms",
        query,
        len(hits),
        int((time.perf_counter() - started) * 1000),
    )
    return {
        "hits": [
            {
                "file": h.path,
                "line": h.line,
                "end_line": h.end_line,
                "snippet": h.snippet,
                "score": h.score,
                "source": h.source,
            }
            for h in hits
        ],
        "source": "lexical",
    }


def _symbol_lookup(settings: Settings, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("symbol", ""))
    with db.connect(settings.index_db_path, readonly=True) as conn:
        symbols = db.symbol_lookup(conn, name)

    def flat(s: Any) -> dict[str, Any]:
        return {
            "symbol": s.name,
            "kind": s.kind,
            "defined_in": s.path,
            "line": s.line,
            "line_end": s.line_end,
            "signature": s.signature,
            "language": s.language,
        }

    if not symbols:
        return {"symbol": name, "found": False, "matches": []}
    if len(symbols) == 1:
        return flat(symbols[0])
    return {
        "symbol": name,
        "found": True,
        "matches": [flat(s) for s in sorted(symbols, key=lambda s: s.path or "")],
    }


def _tool_summary(name: str, args: dict[str, Any]) -> str:
    """One-line request description; query text capped so a line stays a line."""
    if name == "search_code":
        query = str(args.get("query", ""))
        if len(query) > 200:
            query = query[:200] + "…"
        return (
            f"query={query!r} semantic={bool(args.get('semantic', False))} "
            f"limit={args.get('limit', 10)}"
        )
    if name == "symbol_lookup":
        symbol = str(args.get("symbol", ""))
        return f"symbol={symbol[:200]!r}"
    return "status"


def _result_summary(name: str, payload: dict[str, Any]) -> str:
    if name == "search_code":
        return f"{len(payload.get('hits') or [])} hit(s)"
    if name == "symbol_lookup":
        count = 1 if "line" in payload else len(payload.get("matches") or [])
        return f"{count} match(es)"
    return ""


def _call_tool(
    settings: Settings, name: str, args: dict[str, Any]
) -> types.CallToolResult:
    started = time.perf_counter()
    try:
        if name == "get_status":
            payload = _status_payload(settings)
        elif name == "search_code":
            payload = _search_code(settings, args)
        elif name == "symbol_lookup":
            payload = _symbol_lookup(settings, args)
        else:
            logger.warning("unknown tool %r", name)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="unknown tool")],
                is_error=True,
            )
    except Exception:
        logger.exception("tool %s failed", name)
        raise
    result = _result_summary(name, payload)
    logger.log(
        logging.DEBUG if name == "get_status" else logging.INFO,
        "tool=%s %s%s in %d ms",
        name,
        _tool_summary(name, args),
        f" -> {result}" if result else "",
        int((time.perf_counter() - started) * 1000),
    )
    return _json_result(payload)


def _build_server(settings: Settings) -> Server:
    async def on_call_tool(
        ctx: Any, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        return _call_tool(settings, params.name, params.arguments or {})

    return Server(
        "simple-code-indexer",
        on_list_tools=_on_list_tools,
        on_call_tool=on_call_tool,
    )


def _periodic_sweep(settings: Settings, work_queue: indexer.WorkQueue) -> None:
    while True:
        time.sleep(settings.sweep_seconds)
        try:
            work_queue.put(indexer.SWEEP_REQUEST)
            logger.debug("periodic sweep requested")
        except Exception:
            # Keep the timer alive: one bad request must not stop all sweeps.
            logger.exception("cannot request a periodic sweep")


def _probe_services(settings: Settings) -> None:
    """Warm vector store + embed endpoint off the serve path; feeds status flags."""
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


def _acquire_workspace_lock(index_db_path: Path) -> workspace_lock.WorkspaceLock:
    """Enforce one writer per workspace; the lease dies with the process."""
    lock = workspace_lock.WorkspaceLock(index_db_path)
    if not lock.acquire():
        logger.error(
            "another simple-code-indexer already owns %s; refusing to start",
            index_db_path,
        )
        raise SystemExit(1)
    logger.info("workspace lock acquired: %s", index_db_path)
    return lock


def _finalize(settings: Settings, started_at: float) -> None:
    """atexit: record the shutdown, persist vectors, log the final counts."""
    logger.info("shutting down after %.1fs", time.monotonic() - started_at)
    try:
        vector_store.flush(settings)
        logger.info("vector store flushed (%s)", vector_store.describe(settings))
    except Exception:
        logger.warning("vector store flush failed at shutdown", exc_info=True)
    try:
        with db.connect(settings.index_db_path, readonly=True) as conn:
            logger.info("final index: %s", db.stats(conn))
    except Exception:
        logger.debug("cannot read the final index stats", exc_info=True)


async def _serve(
    server: Server,
    watchdog: parent_watch.ParentWatchdog | None,
    on_parent_gone: Callable[[str], NoReturn],
) -> None:
    """Serve until the stdio session ends or the launching harness is gone."""
    if watchdog is not None:
        dead = watchdog.dead()
        if dead is not None:
            on_parent_gone(dead.describe())
        logger.debug("parent watchdog: watching %s", watchdog.describe())
    try:
        async with stdio_server() as (read_stream, write_stream):
            serving = asyncio.create_task(
                server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
            )
            if watchdog is None:
                await serving
                return
            watching = asyncio.create_task(watchdog.wait())
            try:
                done, _ = await asyncio.wait(
                    {serving, watching}, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                for task in (serving, watching):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(serving, watching, return_exceptions=True)
            if serving in done:
                serving.result()
                return
            on_parent_gone(watching.result().describe())
    finally:
        if watchdog is not None:
            watchdog.close()


async def _run() -> None:
    started_at = time.monotonic()
    settings = load_settings()
    watchdog = parent_watch.ParentWatchdog() if parent_watch.enabled() else None
    log_file = logging_setup.configure_file(settings)
    logging_setup.install_excepthooks()
    logging_setup.log_startup(settings, log_file)
    lock = _acquire_workspace_lock(settings.index_db_path)

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
    atexit.register(_finalize, settings, started_at)
    threading.Thread(
        target=_probe_services, args=(settings,), name="service-probe", daemon=True
    ).start()
    # Single writer owns all index writes; startup reconcile goes through it.
    work_queue = indexer.new_work_queue()
    threading.Thread(
        target=indexer.writer_loop,
        args=(settings, work_queue),
        name="index-writer",
        daemon=True,
    ).start()
    work_queue.put(indexer.SWEEP_REQUEST)
    watcher.start_watcher(settings, work_queue)
    logger.info("startup: watcher started")
    threading.Thread(
        target=_periodic_sweep,
        args=(settings, work_queue),
        name="sweep-timer",
        daemon=True,
    ).start()
    server = _build_server(settings)
    logger.info(
        "serving on stdio (startup %.0f ms)", (time.monotonic() - started_at) * 1000
    )

    def _watchdog_exit(description: str) -> NoReturn:
        """Harness gone: stdio_server's reader thread cannot be cancelled, so
        returning from the serve loop would hang on the open pipe. Finalize and
        end the process instead."""
        logger.warning(
            "parent process %s is gone; shutting down so the server cannot "
            "outlive the harness",
            description,
        )
        lock.release()
        logger.info("workspace lock released")
        if watchdog is not None:
            watchdog.close()
        _finalize(settings, started_at)
        logging.shutdown()
        os._exit(0)

    try:
        await _serve(server, watchdog, _watchdog_exit)
    finally:
        lock.release()
        logger.info("workspace lock released")


def main() -> None:
    logging_setup.configure_console()
    try:
        asyncio.run(_run())
    except ConfigError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
