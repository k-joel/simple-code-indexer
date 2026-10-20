# Setup wizard, layered YAML config, managed local services

`setup.py` is now the install path: it installs `uv` when missing, syncs the project, and
runs an interactive wizard that configures an embedding endpoint, provisions Qdrant and a
llama.cpp embedding container with Docker when asked, probes the embedding dimension, writes
`config.yaml` globally (`~/.simple-ci/config.yaml`) or locally
(`<workspace>/.simple-ci/config.yaml`), and registers the server with detected MCP harnesses.
The server reads local config first, then global config, with environment variables
overriding both. A `service` block in either section names a Docker container the server
starts and waits for at boot (fail-soft). The index moved from `.index/` to `.simple-ci/`
so config and data share one gitignored directory. Harness integration is a plugin folder
(`src/simple_code_indexer/harnesses/`, user overrides in `<repo>/harnesses/` and
`<workspace>/harnesses/`) mirroring the language plugin system.

## Context

Before this, every setting came from an environment variable, so a fresh clone required
hand-editing a harness config with machine-specific paths and knowing which services to
start. There was no record of which Docker container backed an endpoint, so the server could
not bring services up itself. `setup.py` was also the natural place to answer the two
questions every install raises: which embedding model, and which MCP client.

## Considered Options

- **Environment variables only (status quo):** zero dependencies and no new config surface,
  but no place for API keys, managed-service names, or per-project defaults.
- **TOML config:** matches `pyproject.toml`, but the wizard writes nested service blocks and
  YAML is what Docker compose already uses; `tomllib` is read-only, so writing would need a
  new dependency anyway.
- **Global config only:** simplest lookup, but a project cannot pin a different embedding
  model or collection settings without exporting environment variables.
- **Local YAML over global YAML (chosen):** matches the workspace-is-cwd model (ADR-0008),
  keeps secrets out of git (`.simple-ci/` is ignored), and still gives every project a
  machine-wide default.
- **Server shells out to `docker compose up` for every managed service on every start:** makes
  "configure once" sufficient, but couples startup to Docker being healthy.
- **Fail-soft startup (chosen):** start containers before serving, but never refuse to start
  when Docker or a service is unavailable — lexical search remains usable, and `get_status`
  reports the state.

## Consequences

- New dependency: `pyyaml` (runtime config parsing + compose generation).
- The wizard and the service manager must be testable without Docker or network; both take
  injectable runners/probers and tests use fakes.
- Config discovery must be disabled in tests (`SIMPLE_CI_CONFIG=none`); otherwise a
  developer's `~/.simple-ci/config.yaml` silently changes test defaults.
- `setup.py` is **not** a setuptools script. `pyproject.toml` keeps the `uv_build` backend,
  which ignores it; the name was chosen because the requested workflow is
  `git clone && python setup.py`.
- The wizard runs the project virtualenv's interpreter instead of `uv run --project`, because
  `--project` changes the working directory and the wizard must configure the caller's cwd.
- Managed services can block startup for up to `startup_timeout_s`; harness configs written
  by the wizard use `timeout: 120000`.
- Changing the embedding model changes the probed dimension, which changes the derived
  collection name; `db.ensure_index_identity` clears rows and the workspace re-indexes. Old
  collections are left for the operator to delete.
- Harness JSON files are rewritten with `json.dumps`; JSONC comments are lost (the wizard
  backs the file up and refuses to write a file it cannot parse). Codex's TOML keeps a
  marker-delimited block so the rest of the file is untouched.
- `.index/` is still in `IGNORE_DIRS` so legacy checkouts are never indexed after the rename.
