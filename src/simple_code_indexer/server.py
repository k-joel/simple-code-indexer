"""MCP stdio server: initialize / tools/list / tools/call for the harness.

No outputSchema, no capabilities.tasks, no execution.taskSupport — the harness
rejects them (ADR-005). Logs go to stderr and
`<workspace>/.simple-ci/log/{reader,embed}.log`; stdout is the MCP channel.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import sqlite3
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
    mcp_roots,
    parent_watch,
    runtime,
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
    WorkspaceBusy,
)
from simple_code_indexer.languages import catalog
from simple_code_indexer.registry import get_registry
from simple_code_indexer.sidecar import ReaderSession

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


def _not_ready(source: str) -> dict[str, Any]:
    return {
        "hits": [],
        "source": source,
        "ready": False,
        "pending_embeddings": 0,
        "message": "index is not ready yet",
    }


def _status_payload(
    settings: Settings,
    *,
    role: str = "writer",
    session: ReaderSession | None = None,
) -> dict[str, Any]:
    try:
        with db.try_connect_readonly(settings.index_db_path) as conn:
            if conn is None:
                counts = {"files": 0, "symbols": 0, "chunks": 0}
                embedding = {"embedded": 0, "pending": 0}
                languages_seen: dict[str, int] = {}
                index_ready = False
            else:
                counts = db.stats(conn)
                embedding = db.embedding_counts(conn)
                languages_seen = db.languages_indexed(conn)
                index_ready = True
    except sqlite3.Error:
        logger.debug("cannot read the index for get_status", exc_info=True)
        counts = {"files": 0, "symbols": 0, "chunks": 0}
        embedding = {"embedded": 0, "pending": 0}
        languages_seen = {}
        index_ready = False
    registry = get_registry()
    from simple_code_indexer.parse import _parsers

    log_file = logging_setup.active_log_file()
    sweep_stats = indexer.LAST_SWEEP_STATS
    payload: dict[str, Any] = {
        "files_indexed": counts["files"],
        "symbols_indexed": counts["symbols"],
        "chunks_indexed": counts["chunks"],
        "vectors_indexed": embedding["embedded"],
        "pending_embeddings": embedding["pending"],
        "watcher_alive": watcher.is_alive(),
        "last_sweep": indexer.LAST_SWEEP,
        "sweep_seconds": settings.sweep_seconds,
        "ignored_dirs": sweep_stats.ignored_dirs if sweep_stats else 0,
        "ignored_files": sweep_stats.ignored_files if sweep_stats else 0,
        "vector_store": vector_store.backend(settings),
        "vector_store_ok": vector_store.last_ok(settings),
        "vector_index": vector_store.describe(settings),
        "embed_ok": embed.LAST_OK is True,
        "languages_loaded": len(registry),
        "languages_with_symbol_maps": len(registry.mapped_grammars()),
        "languages_without_symbol_maps": len(catalog.SYMBOL_GAPS),
        "languages_indexed": len(languages_seen),
        "data_formats_excluded": len(catalog.DATA_FORMATS),
        "grammars_ready": len(_parsers),
        "workspace": str(settings.workspace_root),
        "workspace_source": settings.workspace_source,
        "index_db": str(settings.index_db_path),
        "config_file": str(settings.config_source) if settings.config_source else None,
        "config_files": [str(path) for path in settings.config_sources],
        "log_file": str(log_file) if log_file else None,
        "log_level": settings.log_level,
        "services": dict(services.LAST_STATE),
        "role": role,
        "index_ready": index_ready,
        "writer_pid": os.getpid() if role == "writer" else None,
        "writer_ok": role == "writer",
        "writer_heartbeat_age_s": 0.0 if role == "writer" else None,
        "writer_log_file": str(log_file) if log_file else None,
        "daemon_endpoint": None,
        "sessions": 1 if role == "writer" else 0,
        "harnesses": [],
        "vector_index_age_s": runtime.vector_index_age(settings),
    }
    if role != "reader":
        return payload

    status = session.status() if session is not None else None
    if status is not None:
        payload.update(
            {
                "writer_pid": status.get("writer_pid"),
                "writer_ok": bool(status.get("writer_ok")),
                "writer_heartbeat_age_s": status.get("writer_heartbeat_age_s"),
                "writer_log_file": status.get("writer_log_file"),
                "daemon_endpoint": status.get("endpoint"),
                "sessions": int(status.get("sessions") or 0),
                "harnesses": status.get("harnesses") or [],
                "watcher_alive": bool(status.get("watcher_alive")),
                "last_sweep": status.get("last_sweep"),
                "ignored_dirs": int(status.get("ignored_dirs") or 0),
                "ignored_files": int(status.get("ignored_files") or 0),
                "vector_store_ok": status.get("vector_store_ok"),
                "services": status.get("services") or {},
                "vector_index_age_s": status.get("vector_index_age_s"),
            }
        )
        return payload

    state = runtime.writer_state(settings, stale_after_s=3.0 * settings.heartbeat_s)
    payload.update(
        {
            "writer_pid": state["writer_pid"],
            "writer_ok": state["writer_ok"],
            "writer_heartbeat_age_s": state["writer_heartbeat_age_s"],
            "writer_log_file": str(
                logging_setup.log_path(settings, logging_setup.WRITER_LOG_FILENAME)
            ),
            "watcher_alive": False,
            "sessions": 0,
            "harnesses": [],
            "daemon_endpoint": None,
        }
    )
    return payload


def _semantic_hits(
    settings: Settings, query: str, limit: int, *, readonly: bool = False
) -> dict[str, Any]:
    try:
        with db.try_connect_readonly(settings.index_db_path) as conn:
            if conn is None:
                return _not_ready("semantic")
            embedding = db.embedding_counts(conn)
    except sqlite3.Error:
        logger.debug("semantic search cannot read the index yet", exc_info=True)
        return _not_ready("semantic")
    ready = embedding["pending"] == 0
    embed_started = time.perf_counter()
    try:
        vector = embed.embed_query(settings, query)
        embed_ms = int((time.perf_counter() - embed_started) * 1000)
        search_started = time.perf_counter()
        # Over-fetch: adjacent chunks overlap, so the top `limit` vector hits
        # can collapse to fewer distinct spans after dedupe below.
        if readonly:
            vector_hits = vector_store.search_readonly(settings, vector, limit * 3)
        else:
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
    with db.try_connect_readonly(settings.index_db_path) as conn:
        if conn is None:
            return _not_ready("semantic")
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


def _search_code(
    settings: Settings, args: dict[str, Any], *, readonly: bool = False
) -> dict[str, Any]:
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
        return _semantic_hits(settings, query, limit, readonly=readonly)
    try:
        with db.try_connect_readonly(settings.index_db_path) as conn:
            if conn is None:
                return _not_ready("lexical")
            hits = db.fts_search(conn, query, limit)
    except sqlite3.Error:
        logger.debug("lexical search cannot read the index yet", exc_info=True)
        return _not_ready("lexical")
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


def _symbol_coverage(settings: Settings) -> dict[str, Any]:
    """Distinguish "no symbol support for this language" from "symbol absent".

    A zero-symbol language and a genuinely missing symbol used to return the same
    payload, which makes the tool look broken. Callers get the coverage signal so
    they fall back to `search_code` instead of concluding the symbol does not
    exist.
    """
    try:
        with db.try_connect_readonly(settings.index_db_path) as conn:
            if conn is None:
                return {}
            indexed = db.languages_indexed(conn)
            mapped = db.languages_with_symbols(conn)
    except sqlite3.Error:
        logger.debug("cannot read symbol coverage", exc_info=True)
        return {}

    languages = sorted(indexed)
    covered = sorted(set(languages) & mapped)
    if not languages or not covered:
        state = "none"
    elif len(covered) == len(languages):
        state = "full"
    else:
        state = "partial"
    payload: dict[str, Any] = {
        "coverage": state,
        "languages_indexed": languages,
        "languages_with_symbols": covered,
    }
    if state != "full":
        payload["hint"] = (
            "symbol extraction is unavailable for "
            + ", ".join(sorted(set(languages) - set(covered)))
            + "; use search_code for those languages instead of concluding the "
            "symbol does not exist"
        )
    return payload


def _symbol_lookup(settings: Settings, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("symbol", ""))
    try:
        with db.try_connect_readonly(settings.index_db_path) as conn:
            if conn is None:
                return {
                    "symbol": name,
                    "found": False,
                    "matches": [],
                    "ready": False,
                    "message": "index is not ready yet",
                }
            symbols = db.symbol_lookup(conn, name)
    except sqlite3.Error:
        logger.debug("symbol lookup cannot read the index yet", exc_info=True)
        return {
            "symbol": name,
            "found": False,
            "matches": [],
            "ready": False,
            "message": "index is not ready yet",
        }

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

    coverage = _symbol_coverage(settings)

    if not symbols:
        return {"symbol": name, "found": False, "matches": [], **coverage}
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
    settings: Settings,
    name: str,
    args: dict[str, Any],
    *,
    role: str = "writer",
    session: ReaderSession | None = None,
) -> types.CallToolResult:
    started = time.perf_counter()
    try:
        if name == "get_status":
            payload = _status_payload(settings, role=role, session=session)
        elif name == "search_code":
            payload = _search_code(settings, args, readonly=role == "reader")
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


class ServerState:
    """Workspace-bound settings and the role runtime, resolved once the session exists.

    Workspace sources are, in order, `WORKSPACE_ROOT`, the `--workspace`
    argument, the client's MCP roots, the harness-published workspace, and the
    process cwd (`config.resolve_workspace_root`). MCP roots can only be
    requested after the handshake, so this object defers `load_settings()`, the
    log file, and the runtime start until then (ADR-018). A `--workspace` pin
    answers the question up front, so the roots probe is skipped entirely.
    """

    def __init__(
        self,
        exit: Callable[[int], NoReturn] = os._exit,
        workspace: Path | None = None,
    ) -> None:
        self._exit = exit
        self._pinned = workspace
        self._lock = asyncio.Lock()
        self._cleanup: Callable[[], None] | None = None
        self._finalized = False
        self._started_at = time.monotonic()
        self.settings: Settings | None = None
        self.role = "reader"
        self.session: ReaderSession | None = None

    async def ensure_started(self, session: Any) -> None:
        """Resolve the workspace and start the writer/reader exactly once."""
        if self.settings is not None:
            return
        async with self._lock:
            if self.settings is not None:
                return
            roots = (
                None
                if self._pinned is not None
                else await mcp_roots.first_workspace(session)
            )
            try:
                settings = load_settings(
                    mcp_workspace=roots, cli_workspace=self._pinned
                )
            except ConfigError as exc:
                logger.error("%s", exc)
                self._exit(1)
                raise
            self._start(settings)

    def _start(self, settings: Settings) -> None:
        if settings.mode == "embedded":
            log_file = logging_setup.configure_file(
                settings, filename=logging_setup.EMBED_LOG_FILENAME
            )
            logging_setup.log_startup(settings, log_file, role="writer")
            writer = runtime.WriterRuntime(settings, started_at=self._started_at)
            try:
                writer.start()
            except WorkspaceBusy:
                logger.error(
                    "another simple-code-indexer already owns %s; refusing to start",
                    settings.index_db_path,
                )
                self._exit(1)
                raise
            self.role = "writer"
            self._cleanup = writer.stop
        else:
            log_file = logging_setup.configure_file(
                settings, filename=logging_setup.READER_LOG_FILENAME
            )
            logging_setup.log_startup(settings, log_file, role="reader")
            reader = ReaderSession(settings)
            reader.start()
            self.session = reader
            self.role = "reader"
            self._cleanup = reader.close
        self.settings = settings
        atexit.register(self.cleanup_once)
        logger.info(
            "serving on stdio (startup %.0f ms, role=%s)",
            (time.monotonic() - self._started_at) * 1000,
            self.role,
        )

    def cleanup_once(self) -> None:
        """Stop the writer or unregister the reader exactly once."""
        if self._finalized:
            return
        self._finalized = True
        atexit.unregister(self.cleanup_once)
        if self._cleanup is None:
            return
        try:
            self._cleanup()
        except Exception:
            logger.warning("shutdown cleanup failed", exc_info=True)


def _build_server(state: ServerState) -> Server:
    async def on_call_tool(
        ctx: Any, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        await state.ensure_started(ctx.session)
        assert state.settings is not None
        return _call_tool(
            state.settings,
            params.name,
            params.arguments or {},
            role=state.role,
            session=state.session,
        )

    async def on_initialized(ctx: Any, params: types.NotificationParams) -> None:
        await state.ensure_started(ctx.session)

    server = Server(
        "simple-code-indexer",
        on_list_tools=_on_list_tools,
        on_call_tool=on_call_tool,
    )
    server.add_notification_handler(
        "notifications/initialized", types.NotificationParams, on_initialized
    )
    return server


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
        logger.info("parent watchdog: watching %s", watchdog.describe())
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


async def _run(workspace: Path | None = None) -> None:
    logging_setup.install_excepthooks()
    state = ServerState(workspace=workspace)
    watchdog = parent_watch.ParentWatchdog() if parent_watch.enabled() else None

    try:
        server = _build_server(state)

        def _watchdog_exit(description: str) -> NoReturn:
            """Harness gone: stdio_server's reader thread cannot be cancelled, so
            returning from the serve loop would hang on the open pipe. Run the
            role cleanup (flush + release, or unregister), then end the process."""
            logger.warning(
                "parent process %s is gone; shutting down so the server cannot "
                "outlive the harness",
                description,
            )
            try:
                state.cleanup_once()
            finally:
                if watchdog is not None:
                    watchdog.close()
                logging.shutdown()
                os._exit(0)

        await _serve(server, watchdog, _watchdog_exit)
    finally:
        state.cleanup_once()


def main(workspace: Path | None = None) -> None:
    logging_setup.configure_console()
    try:
        asyncio.run(_run(workspace))
    except ConfigError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
