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
- [docs/ARCH.md](docs/ARCH.md) — the live architecture overview (topology, data flow, domain/data model, component design, testing). **Important:** update it whenever the project's structure, runtime topology, interfaces, schema, or behaviour changes; when the document and the code disagree, the code wins.
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — the user-facing, curated history of notable changes. **It must be updated after every agent session**.
- [docs/DECISIONS.md](docs/DECISIONS.md) — architecture decision records (ADRs) in compressed form: the "why" behind structural, architectural, and dependency choices. **Read the relevant entry before changing behaviour that looks unusual, and add an entry for every new architectural decision; superseded entries are deleted, not kept.**
- [docs/GLOSSARY.md](docs/GLOSSARY.md) — canonical domain terms; use its vocabulary in code, docs, and summaries.
- [docs/ISSUES.md](docs/ISSUES.md) — the ongoing issue tracker. **Add every issue, bug or defect flagged during an LLM session here — even if it is only mentioned in passing in the summary — and delete the entry once it is fixed.**
- [docs/NOTES.md](docs/NOTES.md) — gotchas, watch-outs and oddities. **Add anything a future session needs to know that is not an open issue here.**
- [docs/RUNBOOK.md](docs/RUNBOOK.md): numbered operator procedures. **Review it each session and update any procedures affected by the work.**
- [docs/TECH_DEBT.md](docs/TECH_DEBT.md) — architectural debt and code smells. **Add every structural anti-pattern, code duplication, or AI-induced code smell spotted during a session here, and delete the entry once refactored.**
- [docs/TOOLS.md](docs/TOOLS.md) — the inventory of development scripts in [tools/](tools/). **Check it before writing any new tool, and update it whenever a tool is created or modified.**

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
uv run python tools/gen_language_catalog.py --check              # catalog drift (needs network)
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
  languages/               # GENERATED catalog.py + LanguageSpec + specialized extractors
  harnesses/               # MCP-client plugins for the setup wizard
  setup_wizard/            # prompts, probes, Docker provisioning, install copy
  tsutil.py                # tree-sitter node helpers shared by parse/ and languages/
harnesses/                 # user harness plugin drop-ins (tracked)
tests/                     # pytest + retrieval_bench.py + bench_matrix.py
tools/                     # dev scripts (see docs/TOOLS.md)
pyproject.toml             # deps + ruff / pyright / pytest config
```

## Runtime / external services

Host-spawned MCP **reader** processes + one detached per-workspace **sidecar writer**
([ADR-014](docs/DECISIONS.md#adr-014-per-workspace-sidecar-writer--read-only-mcp-sessions); host process per
[ADR-007](docs/DECISIONS.md#adr-007-host-spawned-mcp-process-workspace--cwd)):

| Service | Endpoint / value |
|---|---|
| Embeddings (OpenAI-compatible) | `http://localhost:8080/v1/embeddings` — model `Qwen3-Embedding-4B-Q6_K`, **2560-dim** |
| FAISS (default) | `<workspace>/.simple-ci/vectors.faiss` — no service; `faiss.path` / `FAISS_PATH` override |
| Qdrant (opt-in) | `http://localhost:6333` (no auth) — one derived collection per workspace |
| Workspace | the MCP process cwd (`WORKSPACE_ROOT` overrides); index at `$WORKSPACE_ROOT/.simple-ci/index.db` |
| Config | `~/.simple-ci/config.yaml` only (global); project-local configs are migrated by the wizard and never read; env vars win (`SIMPLE_CI_CONFIG=none` disables discovery) |
| Mode | `mode: sidecar` (default) or `embedded`; env `SIMPLE_CI_MODE`. Readers never take the writer lease; `embedded` is the all-in-one fallback |
| Sidecar writer | one daemon per workspace owns the lease, watcher, writer thread, sweep timer, vector stores, and managed services; exits after the last registered session + `idle_grace_s` (60 s); respawned on demand |
| Sidecar IPC | `<workspace>/.simple-ci/run/daemon.json` + `daemon.token` (0600); Windows named pipe / POSIX AF_UNIX; `multiprocessing.connection` authkey + JSON bodies; `daemon.spawn.lock` serializes first spawns |
| Sidecar lifetime | live control connection is the primary lease; `heartbeat_s` (5 s) reaped after 3 intervals; `server_pid` liveness via `parent_watch.watch_process`; harness pid is metadata (the reader's own watchdog handles the harness) |
| Sweep | off by default (`sweep_seconds: 0`, watcher only); opt-in periodic reconcile with idle backoff (cap `SWEEP_BACKOFF_MAX_S` = 10 min) and temporary sweeps while chunks are pending; `get_status.sweep_seconds` reports it |
| Logs | sidecar writer: `writer.log`; readers: `reader.log`; embedded: `embed.log` (all under `<workspace>/.simple-ci/log/`, same `log.max_bytes`/`log.backups` rotation; `log.level` / `LOG_LEVEL` controls them). `reader.log` is shared by readers, so its rotation is best-effort. INFO stays on stderr; stdout stays pure MCP |
| Lifecycle | a reader exits with its stdio session and when the harness process dies (`parent_watch.py` skips `uv`/`uvx` and the venv trampoline; `SIMPLE_CI_PARENT_WATCH=0` disables). A reused `opencode-cli serve --service` *is* the harness, so the reader lives as long as it does; stop it with `opencode service stop`. The daemon never watches the harness |
| Install | `%APPDATA%\simple-code-indexer` (Windows), `~/Library/Application Support/...` (macOS), `$XDG_DATA_HOME/...` (Linux); harness entries run `uv run --project <install> --no-sync python run_server.py` on POSIX and the venv's windowless `<install>/.venv/Scripts/pythonw.exe run_server.py` on Windows (no console window) |
| Install record | `setup.install_root` + `setup.harnesses` in `~/.simple-ci/config.yaml`; used by re-runs to remove deselected entries and by `--uninstall` |

Config comes from the YAML file first, then env (e.g. `VECTOR_STORE`, `FAISS_PATH`,
`QDRANT_URL`, `EMBED_BASE_URL`, `EMBED_API_KEY`, `SIMPLE_CI_MODE`, `IDLE_GRACE_S`,
`HEARTBEAT_S`) — never hardcode secrets or local URLs in committed code. A `service` block
makes the writer start that Docker container at boot (fail-soft); a `qdrant.service` is
ignored on the FAISS backend.
Probe the services with `uv run python tests/service_probe.py` before a live-model session.

## Conventions

- Prefer stdlib where it matters: **SQLite + FTS5** for lexical index (stdlib `sqlite3`).
- Semantic path: embed with the same endpoint used for queries; store through `vector_store.py` (FAISS by default, Qdrant opt-in) so call sites stay backend-agnostic.
- **Sidecar is the default** (`mode: sidecar`): `server._run` starts either `runtime.WriterRuntime` (embedded) or `sidecar.ReaderSession` (sidecar), never both. Readers must use `db.try_connect_readonly`, `faiss_store.search_readonly`, and `qdrant_store.search_readonly`; never call `ensure_schema`, `flush`, `reset`, `reconcile`, `upsert_chunks`, or a delete path from a reader.
- **Writer lifecycle**: `runtime.WriterRuntime.start()` acquires `index.db.lock`; `stop()` stops the watcher + writer/sweep/heartbeat threads, flushes vectors and clears dirty flags **while the lease is held**, then releases it last. The daemon clears `.simple-ci/run/daemon.json`/`daemon.token` before releasing the lease so a new daemon cannot publish into a file the old one deletes.
- **Daemon spawn**: `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` (plus `CREATE_BREAKAWAY_FROM_JOB` with fallback; POSIX `start_new_session=True`), stdio redirected, own `writer.log`, and no `ParentWatchdog` (it must outlive the spawner). Never use `DETACHED_PROCESS` here: the venv `python.exe` redirector spawns the real interpreter without creation flags, and that child then allocates a visible console window. The control channel is `multiprocessing.connection` with a token `authkey` and JSON string bodies, never pickle.
- File-watcher / MCP surface should stay small: `search_code`, `symbol_lookup`, `get_status` (optional `reindex`). The watcher is the primary index path; the periodic reconciliation sweep is opt-in (`sweep_seconds: 0` = off) and must stay a backstop, with idle backoff.
- MCP config for the harness lives in `.mimocode/mimocode.json` (gitignored); changes need a session restart to reload. It points at the installed `run_server.py`, which pulls the repo and runs the server in the harness cwd. `python setup.py` writes the same entry for other harnesses (global scope, no per-location prompt).
- Harness support is a plugin folder (`src/simple_code_indexer/harnesses/`); bad plugins are skipped, never fatal, and user drop-ins override builtins by `NAME`.
- **Harness entries are global-only and workspace-free** ([ADR-015](docs/DECISIONS.md#adr-015-harness-entries-are-global-only-no-per-project-data)): never write a project path into an entry — no `WORKSPACE_ROOT`, no `cwd`, no `INDEX_DB`/`FAISS_PATH`. The workspace comes from the harness spawn cwd (ADR-007); `get_status.workspace` confirms it. Pin only while debugging, and remove the pin before finishing (re-running `python setup.py --harnesses <name>` rewrites a clean entry).
- Tests must set `SIMPLE_CI_CONFIG=none` (the autouse fixture in `tests/conftest.py` does this) so a developer's global config cannot change defaults. The same fixture sets `SIMPLE_CI_MODE=embedded`; sidecar tests override it explicitly and must kill spawned daemons by the pid in `.simple-ci/run/daemon.json` in `finally`.
- The watchdog watches **only the harness process** (`parent_watch.harness_process` skips `uv`/`uvx` and the venv trampoline) and finalizes by hand with `os._exit(0)`: `stdio_server`'s stdin reader blocks in a non-cancellable worker thread, so returning from the serve loop would hang on the open pipe. A reader unregisters its sidecar lease in the cleanup; a writer flushes and releases the lease. Keep the cleanup before the exit.
- **Language support is a table, not a plugin folder**: `languages/catalog.py` is generated by `tools/gen_language_catalog.py` — never hand-edit it, edit the generator and re-run it (`--check` detects drift). `registry.py` only indexes the table.
- **Data formats are never indexed** — an absolute rule, enforced twice: `catalog.DATA_FORMATS` entries are not registered, so `detect` returns `None` and the allowlist never contains their extensions. `.md` and `.txt` are in that set (`.txt` → `vimdoc`). Filename matching runs first, so `CMakeLists.txt` still resolves to `cmake`.
- **Never use the pack's own detector** (`detect_language_from_path` / `detect_language_from_extension`) at runtime: it maps `.h` to `c`, `.txt` to `vimdoc`, and `Dockerfile` to nothing. The catalog's table is authoritative; ownership overrides live in the generator (`EXT_OVERRIDES`, `FILENAMES`).
- Changing `catalog.VERSION` (or a language id) is an index migration: `runtime._reconcile_language_catalog` drops rows whose path is no longer allowed or whose stored language no longer matches, and the startup sweep re-indexes them. No schema change, no full re-embed.
- No migrations/codegen tool yet — note them here when added.
