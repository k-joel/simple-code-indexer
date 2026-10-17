"""MCP stdio server: initialize / tools/list / tools/call for the harness.

No outputSchema, no capabilities.tasks, no execution.taskSupport — the harness
rejects them (ADR-0006). Logs go to stderr only; stdout is the MCP channel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from simple_code_indexer import db, embed, indexer, qdrant_store, watcher
from simple_code_indexer.config import Settings, load_settings
from simple_code_indexer.errors import EmbedError, QdrantUnavailable
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
    return types.ListToolsResult(tools=_TOOLS)


def _json_result(payload: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload))]
    )


def _status_payload(settings: Settings) -> dict[str, Any]:
    with db.connect(settings.index_db_path, readonly=True) as conn:
        counts = db.stats(conn)
    registry = get_registry()
    from simple_code_indexer.parse import _parsers

    return {
        "files_indexed": counts["files"],
        "symbols_indexed": counts["symbols"],
        "chunks_indexed": counts["chunks"],
        "watcher_alive": watcher.is_alive(),
        "last_sweep": indexer.LAST_SWEEP,
        "qdrant_ok": qdrant_store.LAST_OK is True,
        "embed_ok": embed.LAST_OK is True,
        "plugins_loaded": len(registry),
        "grammars_ready": len(_parsers),
        "workspace": str(settings.workspace_root),
        "index_db": str(settings.index_db_path),
    }


def _semantic_hits(settings: Settings, query: str, limit: int) -> dict[str, Any]:
    try:
        vector = embed.embed_query(settings, query)
        vector_hits = qdrant_store.search(settings, vector, limit)
    except (EmbedError, QdrantUnavailable):
        logger.warning("semantic search failed", exc_info=True)
        return {"hits": [], "source": "semantic"}
    hits: list[dict[str, Any]] = []
    with db.connect(settings.index_db_path, readonly=True) as conn:
        for vector_hit in vector_hits:
            span = db.get_chunk(conn, vector_hit.path, vector_hit.chunk_index)
            if span is None:
                continue  # orphan point (delete raced); lexical row is source of truth
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
    return {"hits": hits, "source": "semantic"}


def _search_code(settings: Settings, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", ""))
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))
    semantic = bool(args.get("semantic", False))
    if not query.strip():
        return {"hits": [], "source": "semantic" if semantic else "lexical"}
    if semantic:
        return _semantic_hits(settings, query, limit)
    with db.connect(settings.index_db_path, readonly=True) as conn:
        hits = db.fts_search(conn, query, limit)
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


def _call_tool(
    settings: Settings, name: str, args: dict[str, Any]
) -> types.CallToolResult:
    if name == "get_status":
        return _json_result(_status_payload(settings))
    if name == "search_code":
        return _json_result(_search_code(settings, args))
    if name == "symbol_lookup":
        return _json_result(_symbol_lookup(settings, args))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="unknown tool")],
        is_error=True,
    )


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
        work_queue.put(indexer.SWEEP_REQUEST)


def _probe_services(settings: Settings) -> None:
    """Warm collection + embed endpoint off the serve path; feeds status flags."""
    try:
        qdrant_store.ensure_collection(settings)
    except Exception:
        logger.exception("qdrant probe failed")
    try:
        embed.embed_texts(settings, ["service probe"])
    except Exception:
        logger.exception("embed probe failed")


async def _run() -> None:
    settings = load_settings()
    start_prefetch_thread()
    with db.connect(settings.index_db_path) as conn:
        db.ensure_schema(conn)
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
    threading.Thread(
        target=_periodic_sweep,
        args=(settings, work_queue),
        name="sweep-timer",
        daemon=True,
    ).start()
    server = _build_server(settings)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
