# AGENTS.md

## Project Overview

Minimal **code-index MCP server** (Python): watch files, index on save into **SQLite/FTS5** (lexical) + **Qdrant** (semantic vectors).

## Project Docs

Read the relevant doc before planning or reporting work:
- @ISSUES.md — the ongoing issue tracker. **Add every issue, bug or defect flagged during an LLM session here — even if it is only mentioned in passing in the summary — and delete the entry once it is fixed.** 
- @NOTES.md — gotchas, watch-outs and oddities. **Add anything a future session needs to know that is not an open issue here.**

## Generated Files

- @/artifacts/ — All intermediate/throwaway artifact files (markdown, test files, scratch outputs, etc.) that aren't production code.

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

## Runtime / external services

Host-spawned MCP process (no container in this repo — [ADR-0008](docs/adr/0008-host-spawned-cwd-per-repo-collections.md)):

| Service | Endpoint / value |
|---|---|
| Embeddings (OpenAI-compatible) | `http://localhost:8080/v1/embeddings` — model `Qwen3-Embedding-4B-Q6_K`, **2560-dim** |
| Qdrant | `http://localhost:6333` (no auth) — one derived collection per workspace |
| Workspace | the MCP process cwd (`WORKSPACE_ROOT` overrides); index at `$WORKSPACE_ROOT/.index/index.db` |

Config via env (e.g. `QDRANT_URL`, `EMBED_BASE_URL`) — never hardcode secrets or local URLs in committed code.
Probe the services with `uv run python tests/service_probe.py` before a live-model session.

## Conventions

- Prefer stdlib where it matters: **SQLite + FTS5** for lexical index (stdlib `sqlite3`).
- Semantic path: embed with the same endpoint used for queries; store in Qdrant.
- File-watcher / MCP surface should stay small: `search_code`, `symbol_lookup`, `get_status` (optional `reindex`).
- MCP config for the harness lives in `.mimocode/mimocode.json` (gitignored); changes need a session restart to reload. It points at the host-spawned `uvx --from <repo> simple-code-indexer`.
- No migrations/codegen tool yet — note them here when added.
