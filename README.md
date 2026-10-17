# simple-code-indexer

Minimal code-index MCP server: file-watcher indexing into SQLite/FTS5 + Qdrant.

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest
```

See [AGENTS.md](AGENTS.md) for agent-oriented setup notes.
