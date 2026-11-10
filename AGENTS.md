# AGENTS.md

## Project Overview

Minimal **code-index MCP server** (Python): watch files, index on save into **SQLite/FTS5** (lexical) + **FAISS** (semantic vectors, default) or **Qdrant** (opt-in).
See [README.md](README.md) for the detailed overview.

## Project Folders
This project has four dedicated folders for non-production files. Pick the right one based on purpose:

- [docs/](docs/) — Project documentation: the issue tracker, changelog, benchmarks, and tools inventory.
- [ref-docs/](agent-docs/) — All reference documentation: research docs, best-practices guides, and instruction manuals.
- [artifacts/](artifacts/) — All intermediate/throwaway artifact files (markdown, test files, scratch outputs, etc.) that aren't production code.
- [tools/](tools/) — All internal scripts and tools used to support development (e.g. formatting, analysis, build helpers).

## Project Docs

Read the relevant doc before planning or reporting work:
- [docs/ISSUES.md](docs/ISSUES.md) — the ongoing issue tracker. **Add every issue, bug or defect flagged during an LLM session here — even if it is only mentioned in passing in the summary — and delete the entry once it is fixed.**
- [docs/ARCH_ISSUES.md](docs/ARCH_ISSUES.md) — architectural debt and code smells. **Add every structural anti-pattern, code duplication, or AI-induced code smell spotted during a session here, and delete the entry once refactored.**
- [docs/NOTES.md](docs/NOTES.md) — gotchas, watch-outs and oddities. **Add anything a future session needs to know that is not an open issue here.**
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — the user-facing, curated history of notable changes. **It must be updated after every agent session**; follow [ref-docs/changelog-best-practices.md](agent-docs/changelog-best-practices.md).
- [docs/TOOLS.md](docs/TOOLS.md) — the inventory of development scripts in [tools/](tools/). **Check it before writing any new tool, and update it whenever a tool is created or modified.**
- [docs/HANDOFF.md](docs/HANDOFF.md) — active session context and state. **Update with incomplete work, pending multi-step tasks, and exact next steps at the end of every session, and delete entries once the work is fully completed.**

## Toolchain (verified)

- **uv** only — never bare `pip` / `python -m venv`. Always `uv run …` from repo root.
- **Python 3.12** (`.python-version`; `requires-python = ">=3.12"`).
- **Ruff** lint + format, **Pyright** types, **pytest** tests.
- Editable install via `uv_build`; package lives at `src/simple_code_indexer/`.

## Commands (run from repo root)

```bash
uv sync
python setup.py                  # interactive wizard (questionary; installs uv if missing)
python setup.py --dry-run        # print actions without touching files/containers
python setup.py --yes --install-dir "$env:TEMP\sci-install"   # non-interactive
python setup.py --uninstall --dry-run   # show what an uninstall would remove
python setup.py --uninstall --yes       # remove install copy, config, services, models, MCP entries
python setup.py --uninstall --keep-models   # same, but keep ~/.simple-ci/model/
uv run ruff check .              # lint
uv run ruff format .             # format
uv run pyright                   # typecheck
uv run pytest                    # all tests
uv run pytest tests/test_smoke.py::test_main_imports   # single test
uv run python tests/retrieval_bench.py --workspace . --model embeddinggemma-2 \
  --base-url http://localhost:8080 --vector-store faiss --reset \
  --local-path artifacts/bench/local   # one model, never the live .simple-ci index
uv run python tests/bench_matrix.py --workspace .                # all models/backends
```

Do this before calling work done: **`ruff check` → `pyright` → `pytest`**.

On this host `%TEMP%\pytest-of-KJ` is unreadable, so use
`uv run pytest -p no:cacheprovider --basetemp <writable dir>` (see NOTES.md).

After editing Python: `uv run ruff check --fix <file> && uv run ruff format <file>`, then re-run pyright on changed files.

## Layout

```
setup.py                   # wizard launcher (NOT a setuptools script)
run_server.py              # harness launcher: git pull → uv sync → server (cwd preserved)
src/simple_code_indexer/   # package (import: simple_code_indexer)
  builtin/                 # language plugins
  harnesses/               # MCP-client plugins for the setup wizard
  setup_wizard/            # prompts, probes, Docker provisioning, install copy
harnesses/                 # user harness plugin drop-ins (tracked)
plugins/                   # user language plugin drop-ins (tracked)
tests/                     # pytest + retrieval_bench.py + bench_matrix.py
pyproject.toml             # deps + ruff / pyright / pytest config
```

## Runtime / external services

Host-spawned MCP process (no container in this repo — [ADR-0008](docs/adr/0008-host-spawned-cwd-per-repo-collections.md)):

| Service | Endpoint / value |
|---|---|
| Embeddings (OpenAI-compatible) | `http://localhost:8080/v1/embeddings` — model `Qwen3-Embedding-4B-Q6_K`, **2560-dim** |
| FAISS (default) | `<workspace>/.simple-ci/vectors.faiss` — no service; `faiss.path` / `FAISS_PATH` override |
| Qdrant (opt-in) | `http://localhost:6333` (no auth) — one derived collection per workspace |
| Workspace | the MCP process cwd (`WORKSPACE_ROOT` overrides); index at `$WORKSPACE_ROOT/.simple-ci/index.db` |
| Config | `~/.simple-ci/config.yaml` only (global); project-local configs are migrated by the wizard and never read; env vars win (`SIMPLE_CI_CONFIG=none` disables discovery) |
| Logs | `<workspace>/.simple-ci/log/sci.log` (DEBUG, rotated 5 MB × 3; `log.level` / `LOG_LEVEL` controls the file) plus the INFO summary on stderr; stdout stays pure MCP |
| Lifecycle | the server exits with its stdio session and when a launch-chain ancestor dies (`parent_watch.py`, uv launcher and venv trampoline included; `SIMPLE_CI_PARENT_WATCH=0` disables). A harness service started outside the UI (detached) has no UI ancestor and is not visible; the desktop-UI-started OpenCode service is covered |
| Install | `%APPDATA%\simple-code-indexer` (Windows), `~/Library/Application Support/...` (macOS), `$XDG_DATA_HOME/...` (Linux); harness entries run `uv run --project <install> --no-sync python run_server.py` |
| Install record | `setup.install_root` + `setup.harnesses` in `~/.simple-ci/config.yaml`; used by re-runs to remove deselected entries and by `--uninstall` |

Config comes from the YAML file first, then env (e.g. `VECTOR_STORE`, `FAISS_PATH`,
`QDRANT_URL`, `EMBED_BASE_URL`, `EMBED_API_KEY`) — never hardcode secrets or local URLs in
committed code. A `service` block makes the server start that Docker container at boot
(fail-soft); a `qdrant.service` is ignored on the FAISS backend.
Probe the services with `uv run python tests/service_probe.py` before a live-model session.

## Conventions

- Prefer stdlib where it matters: **SQLite + FTS5** for lexical index (stdlib `sqlite3`).
- Semantic path: embed with the same endpoint used for queries; store through `vector_store.py` (FAISS by default, Qdrant opt-in) so call sites stay backend-agnostic.
- File-watcher / MCP surface should stay small: `search_code`, `symbol_lookup`, `get_status` (optional `reindex`).
- MCP config for the harness lives in `.mimocode/mimocode.json` (gitignored); changes need a session restart to reload. It points at the installed `run_server.py`, which pulls the repo and runs the server in the harness cwd. `python setup.py` writes the same entry for other harnesses (global scope, no per-location prompt).
- Harness support is a plugin folder (`src/simple_code_indexer/harnesses/`); bad plugins are skipped, never fatal, and user drop-ins override builtins by `NAME`.
- Tests must set `SIMPLE_CI_CONFIG=none` (the autouse fixture in `tests/conftest.py` does this) so a developer's global config cannot change defaults.
- The watchdog path finalizes by hand and calls `os._exit(0)`: `stdio_server`'s stdin reader blocks in a non-cancellable worker thread, so returning from the serve loop would hang on the open pipe. Keep the vector flush + lock release before the exit.
- No migrations/codegen tool yet — note them here when added.
