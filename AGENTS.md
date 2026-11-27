# AGENTS.md

## Project Overview

Minimal **code-index MCP server** (Python): watch files, index on save into **SQLite/FTS5** (lexical) + **sqlite-vec** (semantic vectors, default; FAISS and Qdrant selectable).
See [README.md](README.md) for the detailed overview.

## Project Folders
This project has four dedicated folders for non-production files. Pick the right one based on purpose:

- [docs/](docs/) — Project documentation: the issue tracker, changelog, benchmarks, and tools inventory.
- [references/](references/) — All reference documentation: research docs, best-practices guides, and instruction manuals.
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
uv run simple-code-indexer setup            # wizard; installs this checkout as a uv tool
uv run simple-code-indexer setup --dry-run  # print actions without touching files/containers
uv run simple-code-indexer install          # install/reinstall the tool env, editable (dev default)
uv run simple-code-indexer install --wheel  # same env, built wheel (prod validation; entry unchanged)
uv run simple-code-indexer uninstall --dry-run   # show what an uninstall would remove
uv run simple-code-indexer uninstall --yes       # remove tool env, config, services, models, MCP entries
uv run simple-code-indexer uninstall --yes --keep-models   # same, but keep ~/.simple-ci/model/
uvx simple-code-indexer setup    # supported entry point once published
uvx simple-code-indexer serve    # what harness entries run (stdio MCP)
uvx simple-code-indexer status   # workspace + index health for the cwd
uv run simple-code-indexer version      # the checkout's editable install
python tools/release.py --bump patch    # bump, cut CHANGELOG, tag, push -> CI publishes
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
uv build --no-sources            # wheel + sdist exactly as PyPI receives them
```

**Never run a non-dry-run `setup` or `uninstall` against your real profile**: both are
machine-wide (global config, uv tool env, harness configs, `~/.simple-ci/`). Redirect
`HOME`/`USERPROFILE`/`APPDATA`/`LOCALAPPDATA` first, or use `--dry-run`.

Do this before calling work done: **`ruff check` → `pyright` → `pytest`**.

On this host use `uv run pytest -p no:cacheprovider --basetemp <writable dir>` (see NOTES.md).

After editing Python: `uv run ruff check --fix <file> && uv run ruff format <file>`, then re-run pyright on changed files.

## Layout

```
src/simple_code_indexer/   # package (import: simple_code_indexer)
  cli.py                   # console entry point: setup / install / serve / uninstall / status / version
  languages/               # GENERATED catalog.py + LanguageSpec + specialized extractors
  harnesses/               # MCP-client plugins: install entries + runtime workspace hooks
  setup_wizard/            # prompts, probes, Docker provisioning, uv tool install/uninstall
  tsutil.py                # tree-sitter node helpers shared by parse/ and languages/
harnesses/                 # user harness plugin drop-ins (tracked; not in the wheel)
tests/                     # pytest + retrieval_bench.py + bench_matrix.py
tools/                     # dev scripts (see docs/TOOLS.md)
.github/workflows/         # ci.yml (test + dist) and release.yml (tag-driven PyPI publish)
pyproject.toml             # deps + metadata + ruff / pyright / pytest config
```

## Runtime / external services

Host-spawned MCP **reader** processes + one detached per-workspace **sidecar writer**
([ADR-014](docs/DECISIONS.md#adr-014-per-workspace-sidecar-writer--read-only-mcp-sessions); host process per
[ADR-007](docs/DECISIONS.md#adr-007-host-spawned-mcp-process-workspace--cwd)):

| Service | Endpoint / value |
|---|---|
| Embeddings (OpenAI-compatible) | `http://localhost:8080/v1/embeddings` — default model `embeddinggemma-2`, **768-dim** |
| sqlite-vec (**default**) | `vec_chunks` virtual table inside `<workspace>/.simple-ci/index.db` — no service; `sqlite_vec.chunk_size` / `mmap_size` / `cache_size` (`SQLITE_VEC_*`) |
| FAISS (second) | `<workspace>/.simple-ci/vectors.faiss` — no service; `faiss.path` / `SIMPLE_CI_FAISS_PATH` override |
| Qdrant (opt-in) | `http://localhost:6333` (no auth) — one derived collection per workspace |
| Workspace | `SIMPLE_CI_WORKSPACE_ROOT` > `serve --workspace` (a project-scope entry's pin, source `arg`) > client MCP `roots/list` > harness-published workspace > cwd (ADR-018, ADR-022); index at `<workspace>/.simple-ci/index.db`; `get_status.workspace_source` reports the winner |
| Config | `~/.simple-ci/config.yaml` only (global); project-local configs are migrated by the wizard and never read; env vars win (`SIMPLE_CI_CONFIG=none` disables discovery) |
| Mode | `mode: sidecar` (default) or `embedded`; env `SIMPLE_CI_MODE`. Readers never take the writer lease; `embedded` is the all-in-one fallback |
| Sidecar writer | one daemon per workspace owns the lease, watcher, writer thread, sweep timer, vector stores, and managed services; exits after the last registered session + `idle_grace_s` (60 s); respawned on demand |
| Sidecar IPC | `<workspace>/.simple-ci/run/daemon.json` + `daemon.token` (0600); Windows named pipe / POSIX AF_UNIX; `multiprocessing.connection` authkey + JSON bodies; `daemon.spawn.lock` serializes first spawns and `daemon.spawn.json` (child pid + timestamp) claims an in-flight spawn |
| Sidecar lifetime | live control connection is the primary lease; `heartbeat_s` (5 s) reaped after 3 intervals; `server_pid` liveness via `parent_watch.watch_process`; harness pid is metadata (the reader's own watchdog handles the harness) |
| Sweep | `sweep_seconds: 0` disables it (watcher only); the wizard offers 300 s. Periodic reconcile with idle backoff (cap `SWEEP_BACKOFF_MAX_S` = 10 min) and temporary sweeps while chunks are pending; `get_status.sweep_seconds` reports it |
| Logs | sidecar writer: `writer.log`; readers: `reader.log`; embedded: `embed.log` (all under `<workspace>/.simple-ci/log/`, same `log.max_bytes`/`log.backups` rotation; `log.level` / `SIMPLE_CI_LOG_LEVEL` controls them). `reader.log` is shared by readers, so its rotation is best-effort. INFO stays on stderr; stdout stays pure MCP |
| Lifecycle | a reader exits with its stdio session and when the harness process dies (`parent_watch.py` skips `uv`/`uvx`, the venv trampoline, and a spawn shell below the harness; `SIMPLE_CI_PARENT_WATCH=0` disables). A reused `opencode-cli serve --service` *is* the harness, so the reader lives as long as it does; stop it with `opencode service stop`. The daemon never watches the harness |
| Install | `uv tool install <spec>` into one environment, in one of two flavours: **editable** (default from a checkout: `--editable <checkout>`) or **wheel** (`--wheel`, or any run with no checkout: `[--refresh] <checkout>` / `simple-code-indexer==<version>`). `<spec>` is the checkout path when running from a source tree (so local installs work before publishing) and the pinned published version otherwise. Environment root: `%APPDATA%\uv\tools\simple-code-indexer`, `~/Library/Application Support/uv/tools/...`, `$XDG_DATA_HOME/uv/tools/...`; harness entries run its `Scripts/pythonw.exe -m simple_code_indexer serve` on Windows (no console window) and `bin/python -m simple_code_indexer serve` on POSIX — identical for both flavours, so switching never rewrites an entry |
| Install record | `setup.install_kind` (`editable`/`wheel`) + `setup.tool_env` + `setup.harnesses` in `~/.simple-ci/config.yaml`; `uv-receipt.toml` in the tool env is the ground truth for which flavour is live |
| Release | tag-driven: `tools/release.py --bump` → `.github/workflows/release.yml` → PyPI Trusted Publishing (OIDC). `pyproject.toml` holds the version; the tag must match (`--verify-tag`) |

Config comes from the YAML file first, then env (e.g. `SIMPLE_CI_VECTOR_STORE`, `SIMPLE_CI_FAISS_PATH`,
`SQLITE_VEC_CHUNK_SIZE`, `SQLITE_VEC_MMAP_SIZE`, `SQLITE_VEC_CACHE_SIZE`, `QDRANT_URL`,
`SIMPLE_CI_EMBED_BASE_URL`, `SIMPLE_CI_EMBED_API_KEY`, `SIMPLE_CI_MODE`, `SIMPLE_CI_IDLE_GRACE_S`, `SIMPLE_CI_HEARTBEAT_S`) — never
hardcode secrets or local URLs in committed code. A `service` block makes the writer start that
Docker container at boot (fail-soft); a `qdrant.service` is ignored on the sqlite-vec and FAISS
backends.
Probe the services with `uv run python tests/service_probe.py` before a live-model session.

## Conventions

- Prefer stdlib where it matters: **SQLite + FTS5** for lexical index (stdlib `sqlite3`).
- Semantic path: embed with the same endpoint used for queries; store through `vector_store.py` (sqlite-vec by default, FAISS and Qdrant selectable) so call sites stay backend-agnostic.
- **The router is a registry, not a branch table**: every backend module implements `vector_store.STORE_CONTRACT` (`describe`, `identity`, `ensure_ready`, `reset`, `upsert_chunks`, `delete_by_path`, `search`, `search_readonly`, `reconcile`, `flush`, `last_ok`, `vector_index_age_s`). Adding a backend = one module + one `_STORES` entry; `tests/test_vector_store.py` fails if a module drifts. Shared width checks/normalisation live in `vector_util.py`, and `vector_store.describe/identity` come from the module, never from backend checks in the router.
- **sqlite-vec owns its table**: `vec_chunks` is created by `sqlite_vec_store.ensure_ready`, never by `db.ensure_schema` (creating it needs the extension loaded, and readers must not create it). Every sqlite-vec connection loads the extension and sets `PRAGMA mmap_size`/`cache_size`; read-only queries go through `search_readonly` on a `mode=ro` connection.
- **Sidecar is the default** (`mode: sidecar`): `server._run` starts either `runtime.WriterRuntime` (embedded) or `sidecar.ReaderSession` (sidecar), never both. Readers must use `db.try_connect_readonly`, `sqlite_vec_store.search_readonly`, `faiss_store.search_readonly`, and `qdrant_store.search_readonly`; never call `ensure_schema`, `flush`, `reset`, `reconcile`, `upsert_chunks`, or a delete path from a reader.
- **Writer lifecycle**: `runtime.WriterRuntime.start()` acquires `index.db.lock`; `stop()` stops the watcher + writer/sweep/heartbeat threads, flushes vectors and clears dirty flags **while the lease is held**, then releases it last. The daemon clears `.simple-ci/run/daemon.json`/`daemon.token` before releasing the lease so a new daemon cannot publish into a file the old one deletes.
- **Daemon spawn**: `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` (plus `CREATE_BREAKAWAY_FROM_JOB` with fallback; POSIX `start_new_session=True`), stdio redirected, own `writer.log`, and no `ParentWatchdog` (it must outlive the spawner). Never use `DETACHED_PROCESS` here: the venv `python.exe` redirector spawns the real interpreter without creation flags, and that child then allocates a visible console window. The control channel is `multiprocessing.connection` with a token `authkey` and JSON string bodies, never pickle.
- File-watcher / MCP surface should stay small: `search_code`, `symbol_lookup`, `get_status` (optional `reindex`). The watcher is the primary index path; the periodic reconciliation sweep (`sweep_seconds`, 300 s offered by the wizard, `0` = off) must stay a backstop, with idle backoff.
- MCP config for the harness lives in `.mimocode/mimocode.json` (gitignored); changes need a session restart to reload. It points at the installed tool environment, which runs the server in the harness cwd. `simple-code-indexer setup` writes the same entry for other harnesses (global scope by default; `--harness-scope project` writes the workspace's own client config instead).
- Harness support is a plugin folder (`src/simple_code_indexer/harnesses/`); bad plugins are skipped, never fatal, and user drop-ins override builtins by `NAME`. A plugin may declare `resolve_workspace(cwd)` (runtime hook); the wizard then appends `serve --harness <NAME>` to its entry (`harnesses.harness_flag`), and `harnesses.discover_workspace` asks only that plugin (`SIMPLE_CI_HARNESS` is still read as a debug/pre-ADR-024 fallback). An entry without the marker (installed before it existed) still resolves: when the cwd is implausible (home or an ancestor's executable dir, `config._implausible_reason`) every resolver is asked, while a plausible cwd is never overridden. Keep client-specific discovery inside the plugin.
- **Entries come in two scopes** ([ADR-015](docs/DECISIONS.md#adr-015-global-harness-entries-carry-no-per-project-data), [ADR-022](docs/DECISIONS.md#adr-022-harness-entries-can-be-project-scoped-pinned-by-serve---workspace)). A **global** entry serves every project and is workspace-free: no `SIMPLE_CI_WORKSPACE_ROOT`, no `cwd`, no `--workspace`, no `SIMPLE_CI_INDEX_DB`/`SIMPLE_CI_FAISS_PATH`, and no `env` block at all. A resolver-owning plugin's entry carries the argument `serve --harness <NAME>` instead of the old `SIMPLE_CI_HARNESS` env key. A **project** entry is written into the workspace's own config (`LOCAL_CONFIGS`) and always carries `serve --workspace <abs workspace>`. Workspace resolution order is `SIMPLE_CI_WORKSPACE_ROOT` > `--workspace` (`arg`) > MCP roots > harness-published > cwd (ADR-018); `get_status.workspace`/`workspace_source` confirm it. Pin only while debugging a *global* entry, and remove the pin before finishing (re-running `simple-code-indexer setup --harnesses <name>` rewrites a clean entry).
- **Harness writes are CLI-first and per-client code lives in the plugin**: a plugin may declare `CLI_BINARIES` + `cli_add(scope, workspace, name, command, entry)` / `cli_remove(...)`; `setup_wizard/entries.py` runs that CLI, falls back to `write.install`, then to the client's global entry when it has no project config (Goose, Claude Desktop). Never add `if spec.name == …` to the wizard. A client whose CLI writes elsewhere adds `cli_target`/`cli_root_key` (Cursor: `%APPDATA%/Cursor/User/settings.json` under `mcp.servers`) — such a file must stay out of `GLOBAL_CONFIGS`, or the merge writes the wrong root key into it. On Windows the ladder runs the `shutil.which` path and routes `.cmd`/`.bat` through `cmd /c` (`subprocess` cannot exec a batch file); use the resolved path, never the bare name. `enabled: true` only where the client documents it — Codex (`ENABLED` in the plugin, because TOML bypasses `entry()`), Pi, Goose, MiMo, Command Code; never OpenCode (it uses `disabled`), VS Code, Cursor, Zed, Gemini CLI, Claude Code, Claude Desktop, or Windsurf. Zed declares no `BINARIES`/`CLI_BINARIES`: `zed` on `PATH` is usually authzed's SpiceDB CLI. Per-client flag shapes are recorded in `docs/NOTES.md`.
- Tests must set `SIMPLE_CI_CONFIG=none` (the autouse fixture in `tests/conftest.py` does this) so a developer's global config cannot change defaults. The same fixture sets `SIMPLE_CI_MODE=embedded` and, on Windows, redirects `APPDATA`/`LOCALAPPDATA` to a scratch profile so a wizard path that forgets to thread `home` cannot edit a real Cursor/Zed/VS Code config; sidecar tests override the mode explicitly and must kill spawned daemons by the pid in `.simple-ci/run/daemon.json` in `finally`.
- The watchdog watches **only the harness process** (`parent_watch.harness_process` skips `uv`/`uvx`, the venv trampoline, and a spawn shell that sits below the harness) and finalizes by hand with `os._exit(0)`: `stdio_server`'s stdin reader blocks in a non-cancellable worker thread, so returning from the serve loop would hang on the open pipe. A reader unregisters its sidecar lease in the cleanup; a writer flushes and releases the lease. Keep the cleanup before the exit.
- **Language support is a table, not a plugin folder**: `languages/catalog.py` is generated by `tools/gen_language_catalog.py` — never hand-edit it, edit the generator and re-run it (`--check` detects drift). `registry.py` only indexes the table.
- **Data formats are never indexed** — an absolute rule, enforced twice: `catalog.DATA_FORMATS` entries are not registered, so `detect` returns `None` and the allowlist never contains their extensions. `.md` and `.txt` are in that set (`.txt` → `vimdoc`). Filename matching runs first, so `CMakeLists.txt` still resolves to `cmake`.
- **Never use the pack's own detector** (`detect_language_from_path` / `detect_language_from_extension`) at runtime: it maps `.h` to `c`, `.txt` to `vimdoc`, and `Dockerfile` to nothing. The catalog's table is authoritative; ownership overrides live in the generator (`EXT_OVERRIDES`, `FILENAMES`).
- Changing `catalog.VERSION` (or a language id) is an index migration: `runtime._reconcile_language_catalog` drops rows whose path is no longer allowed or whose stored language no longer matches, and the startup sweep re-indexes them. No schema change, no full re-embed.
- No migrations/codegen tool yet — note them here when added.
