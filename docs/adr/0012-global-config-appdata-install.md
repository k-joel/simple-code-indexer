# Global-only config, per-user install, self-updating launcher, and questionary menus

`setup.py` now writes exactly one config file (`~/.simple-ci/config.yaml`), copies the repo
(including `.git`) into the per-user app directory, and points every harness entry at that
copy. The entry runs `run_server.py`, which pulls the latest code, re-syncs the virtualenv
only when `HEAD` moved, and starts the server in the harness's working directory. Menus use
`questionary`; `simple-term-menu` cannot be imported on Windows.

## Context

Three problems motivated this change:

- **The local config contradicted the deployment model.** ADR-0011 split global assets from
  per-project settings. In practice the only per-project setting was `vector_store`, and
  keeping two files meant a second place to drift, a second file to document, and a
  project-local file that silently overrode the machine-wide embedding endpoint. The user
  asked for a single global config and for FAISS settings to persist globally.
- **Harness entries pointed at the checkout.** `uvx --from <repo>` rebuilt from the source
  tree, so updating the checkout changed behavior without any version bump, and deleting the
  checkout broke every installed harness. A stable installed copy with an explicit launcher
  makes entries durable and updatable.
- **The menu library did not support the host.** `simple-term-menu` imports `termios` at
  module load and raises `NotImplementedError` on Windows (its README says Linux/macOS only).
  The wizard has to run on Windows, so the menu layer was replaced with `questionary`
  (`select`, `checkbox`, `confirm`, `text`/`password`), with the numbered `input()` prompts
  kept as a non-interactive fallback for pipes, tests, and `SIMPLE_CI_NO_TUI=1`.

The harness locations also drifted from the clients' actual files: Cline now stores MCP
settings under `~/.cline/data/settings/`, OpenCode V2 nests servers under `mcp.servers`,
MiMo's global config moved to the XDG config directory, and Windsurf is now Devin Local.

## Decision

- **One config file.** `configfile.config_paths` returns only `~/.simple-ci/config.yaml`
  (or the `SIMPLE_CI_CONFIG` override). Project-local configs are never read. The wizard
  merges a legacy local file into the global one and removes it. `vector_store` and an
  optional `faiss.path` live globally; the SQLite database and FAISS file remain
  per-workspace, so workspace isolation is unchanged.
- **Per-user install.** `setup_wizard/install.py` copies the working tree to
  `%APPDATA%\simple-code-indexer` (Windows), `~/Library/Application Support/...` (macOS), or
  `$XDG_DATA_HOME/simple-code-indexer` (Linux). `.venv`, caches, `artifacts/`, and
  `.simple-ci/` are excluded; `.git` is copied on the first install and preserved on updates.
  `uv sync --project <install>` creates the venv. `--install-dir` and `--no-install` exist
  for tests and development.
- **Self-updating launcher.** Harness entries are
  `[<install>/.venv/.../python, <install>/run_server.py]`. The launcher runs
  `git pull --ff-only --autostash` (bounded at 20 s), runs `uv sync` only if `HEAD` changed,
  then imports and runs the server. All failures are logged to stderr and never block
  serving. It never uses `uv run --project`, because that changes cwd and breaks workspace
  inference. `SIMPLE_CI_GIT_PULL=0` disables the pull.
- **Detection-first wizard.** The flow is Docker check/install → legacy local-config
  migration → existing-global-config summary (use/reconfigure) → embedding source menu
  (running server, existing container, downloaded GGUF, catalog download, URL) → vector store
  → global config write → install copy → harness multi-select (global only) → summary.
  `--container`, `--embedding-url`, `--vector-store`, `--config-mode`, `--harnesses`, and
  `--install-dir` make every branch scriptable.
- **Managed services stay blocking.** `services.ensure_managed_services` still starts stopped
  containers and waits for `/v1/embeddings` and Qdrant `/healthz` before the MCP handshake.
  The wizard writes `service` blocks with a 120 s startup timeout. A Qwen3 container using
  `LLAMA_ARG_POOLING=mean` is flagged: Qwen3-Embedding needs last-token pooling.
- **Harness schema fixes.** Cline uses `~/.cline/data/settings/cline_mcp_settings.json`;
  OpenCode writes `mcp.servers.<name>` (the JSON helper accepts dotted root keys); MiMo lists
  XDG/AppData candidates plus the legacy `~/.mimocode`; Windsurf prefers
  `~/.config/devin/mcp_config.json` and falls back to the legacy Codeium path; Codex gets
  `startup_timeout_sec = 120`; VS Code drops the non-user `~/.vscode/mcp.json` candidate.

## Considered Options

- **Keep simple-term-menu and use a Windows fallback.** The requested library would never run
  on the host; the user chose questionary instead so the same menus work everywhere.
- **Keep `uvx --from <install>` in harness entries.** `uvx` caches builds by version, so a
  `git pull` would not invalidate the cached environment; the source changes would not be
  used until the version or cache changed. The venv + launcher pair is deterministic.
- **Clone the repo into AppData instead of copying.** A clone ignores the local working tree
  (including uncommitted changes, plugins, and harness drop-ins) and needs network access at
  install time. Copying preserves the checkout exactly and still supports `git pull`.
- **Force `git reset --hard` on every launch.** It would guarantee the latest code but
  discard edits in the installed copy. `pull --ff-only --autostash` is the least destructive
  way to stay current.

## Consequences

- `--scope` is gone; passing it is a parser error explaining that config is global.
- `get_status.config_files` has 0 or 1 entries, and `config_file` is that entry or `null`.
- Harness entries reference an absolute install path, so moving or deleting the install
  directory requires re-running `setup.py`.
- The first launch after a pull may spend a few seconds in `uv sync`; the launcher bounds it
  at 300 s and falls back to the existing venv on failure.
- `tests/retrieval_bench.py` and `tests/bench_matrix.py` score Recall@1/5/10, MRR@10, and
  nDCG@10 over `tests/retrieval_queries.json`, with a lexical baseline, and reset the
  database/collection between model runs. Reports land in `artifacts/`.
