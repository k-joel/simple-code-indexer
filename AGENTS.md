# AGENTS.md

## What this is

Minimal **code-index MCP server** (Python): watch files, index on save into **SQLite/FTS5** (lexical) + **Qdrant** (semantic vectors). Background/context: [`code-index-mcp-handoff.md`](code-index-mcp-handoff.md) and [`code-index-mcp-report.md`](code-index-mcp-report.md) — trust those over prose here when they conflict with unfinished code.

## Toolchain (verified)

- **uv** only — never bare `pip` / `python -m venv`. Always `uv run …` from repo root.
- **Python 3.12** (`.python-version`; `requires-python = ">=3.12"`).
- **Ruff** lint + format, **Pyright** types, **pytest** tests.
- Editable install via `uv_build`; package lives at `src/simple_code_indexer/`.

## Commands (run from repo root)

```bash
uv sync
uv run ruff check .              # lint
uv run ruff format .             # format
uv run pyright                   # typecheck
uv run pytest                    # all tests
uv run pytest tests/test_smoke.py::test_main_imports   # single test
```

Do this before calling work done: **`ruff check` → `pyright` → `pytest`**.

After editing Python: `uv run ruff check --fix <file> && uv run ruff format <file>`, then re-run pyright on changed files.

## Layout

```
src/simple_code_indexer/   # package (import: simple_code_indexer)
tests/                     # pytest
pyproject.toml             # deps + ruff / pyright / pytest config
```

## Runtime / external services (from handoff — not wired in code yet)

These are the decided targets when the indexer is implemented; do not invent different defaults:

| Service | Endpoint / value |
|---|---|
| Embeddings (OpenAI-compatible) | `http://localhost:8080/v1/embeddings` — model `Qwen3-Embedding-4B-Q6_K`, **2560-dim** |
| Qdrant | `http://localhost:6333` (no auth) |
| In Docker | reach host services as `http://host.docker.internal:<port>` |

Config via env (e.g. `QDRANT_URL`, embedding base URL + key if any) — never hardcode secrets or local URLs in committed code.

## Conventions

- Prefer stdlib where it matters: **SQLite + FTS5** for lexical index (stdlib `sqlite3`).
- Semantic path: embed with the same endpoint used for queries; store in Qdrant.
- File-watcher / MCP surface should stay small: `search_code`, `symbol_lookup`, `get_status` (optional `reindex`).
- MCP config for the harness lives in `.mimocode/mimocode.json`; changes need a session restart to reload.
- No migrations/codegen tool yet — note them here when added.
