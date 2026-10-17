# Python 3.12 + official MCP SDK stack

The four requirements are I/O-bound glue (watcher, HTTP, SQLite). Python is proven end-to-end in this exact environment (including every integration pitfall). Rewriting reintroduces those pitfalls as fresh discoveries.

| Layer | Choice |
|---|---|
| Language | Python 3.12 (`python:3.12-slim`) |
| MCP | official `mcp` SDK, stdio server |
| Watcher | `watchdog` |
| DB | stdlib `sqlite3` + FTS5 |
| Vectors | `qdrant-client` |
| Embeddings | `httpx` (or OpenAI-compatible client with explicit timeouts, retries 0–2) |
| Parsing | `tree-sitter` + `tree-sitter-language-pack` |
| Packaging | `uv` |

## Considered Options

- **TypeScript:** viable; weaker tree-sitter story.
- **Go:** good for always-on daemon; steeper path to MVP.
- **Rust:** highest ceiling, slowest path. Rejected.

## Consequences

- Keep write path local-first; embeddings use short explicit timeouts.
- Never let a client default-retry toward the public internet.
