# simple-code-indexer

Minimal code-index MCP server: file-watcher indexing into SQLite/FTS5 + Qdrant.

## How it runs

The harness spawns the server **on the host, inside the project you have open**:

- **Workspace** = the process working directory (`Path.cwd().resolve()`), overridable with `WORKSPACE_ROOT`.
- **Index** = `$WORKSPACE_ROOT/.simple-ci/index.db` — gitignore `.simple-ci/` in every indexed project.
- **Config** = `<workspace>/.simple-ci/config.yaml` (local) or `~/.simple-ci/config.yaml`
  (global); environment variables override both. See [ADR-0009](docs/adr/0009-setup-wizard-managed-services-config.md).
- **Collection** = `code_index_{folder_slug}_{sha256(path)[:8]}_{embed_dim}`, derived per workspace so projects never share vectors. `QDRANT_COLLECTION` overrides it.
- **Services** = Qdrant and an OpenAI-compatible embedding endpoint. They can be long-lived
  host services, or Docker containers the server starts on demand when `config.yaml` names
  them. See [ADR-0008](docs/adr/0008-host-spawned-cwd-per-repo-collections.md).

## How to use

### Prerequisites

- **Python 3.12+** and **git**.
- **Docker Desktop** only if you want the wizard to download an embedding model or run
  Qdrant for you. Existing services elsewhere work too.
- `uv` is installed by `setup.py` when missing.

### Quick start

```bash
git clone <repo> simple-code-indexer
cd simple-code-indexer
python setup.py
```

`setup.py` installs `uv` if needed, runs `uv sync`, and launches the interactive wizard.
Run `python setup.py --dry-run` first to see every action without writing files or starting
containers, or `python setup.py --yes` to accept the recommended answer everywhere.

### What the wizard asks

| Step | Choices |
|---|---|
| Embedding server | Use an existing OpenAI-compatible endpoint (type the URL, optional API key, model name), pick an existing Docker container (started for you), or auto-download a model |
| Auto-download model | EmbeddingGemma 2 (recommended, 768-dim), Qwen3-Embedding-0.6B (1024-dim), Nomic Embed Code (3584-dim), or cancel |
| Embedding dimension | Always probed from a real `/v1/embeddings` call; catalog values are only an offline fallback |
| Qdrant | Use an existing URL/container, provision `qdrant/qdrant` with Docker, or abort |
| Harnesses | Detected from your home folder; choose any subset and global vs project-local scope |
| Config location | Global `~/.simple-ci/config.yaml` or local `<project>/.simple-ci/config.yaml` |

The wizard also appends `.simple-ci/` to the project `.gitignore` and offers to migrate a
legacy `.index/` directory.

### Where files land

| Path | Contents |
|---|---|
| `~/.simple-ci/config.yaml` | Global config (used when the project has no local config) |
| `<project>/.simple-ci/config.yaml` | Per-project config; wins over the global file |
| `<project>/.simple-ci/index.db` | SQLite index (+ WAL files and the single-writer lock) |
| `~/.simple-ci/docker-compose.yml` | Services the wizard generated (`embed`, `qdrant`) |
| `~/.simple-ci/models/` | Downloaded GGUF files |

Local config lives inside the gitignored `.simple-ci/` directory because it may hold an
API key. Config precedence is **environment variable > local YAML > global YAML > default**.

### Supported harnesses

Builtin plugins write the server entry into each client's own file:

| Harness | Global config | Project config |
|---|---|---|
| Claude Code | `~/.claude.json` | `.mcp.json` |
| Claude Desktop | `%APPDATA%/Claude/claude_desktop_config.json` (and macOS/Linux equivalents) | — |
| Codex CLI | `~/.codex/config.toml` | `.codex/config.toml` |
| Gemini CLI | `~/.gemini/settings.json` | `.gemini/settings.json` |
| OpenCode | `~/.config/opencode/opencode.json(c)` | `opencode.json(c)` |
| Cursor | `~/.cursor/mcp.json` | `.cursor/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | — |
| VS Code | `%APPDATA%/Code/User/mcp.json` (and macOS/Linux equivalents) | `.vscode/mcp.json` |
| Zed | `~/.config/zed/settings.json` | `.zed/settings.json` |
| Cline | VS Code globalStorage `cline_mcp_settings.json` | — |
| Command Code | `~/.commandcode/mcp.json` | `.mcp.json` |
| MiMoCode | `~/.mimocode/mimocode.json` | `.mimocode/mimocode.json` |

The entry is `uvx --from <this clone> simple-code-indexer`. Restart the harness after it is
written; the file is read at session start. If both services are Docker-managed, raise the
harness `timeout` to `120000` — the server waits for the containers before serving.

### Manual config

```yaml
version: 1
embedding:
  base_url: http://localhost:8080
  model: embeddinggemma-2
  dim: 768                 # must match the endpoint; the wizard probes it
  api_key: null
  timeout_s: 15
  service:                 # optional: server starts this container at boot
    container: simple-ci-embed
    compose_file: /home/you/.simple-ci/docker-compose.yml
    compose_service: embed
    startup_timeout_s: 60
qdrant:
  url: http://localhost:6333
  service:
    container: simple-ci-qdrant
    compose_file: /home/you/.simple-ci/docker-compose.yml
    compose_service: qdrant
    startup_timeout_s: 45
sweep_seconds: 45
debounce_ms: 400
```

When a `service` block is present the server verifies the container is running (starting it
if needed) and waits for the endpoint before serving. It never refuses to start: if Docker
or the service is unavailable, the server logs it, keeps lexical search working, and reports
the state in `get_status.services`.

### Verify

```bash
uv run python tests/service_probe.py
uv run python tests/mcp_probe.py
```

`get_status` reports the resolved `workspace`, `collection`, `config_file`, and
`services` (`running`, `started`, `unavailable`, or `not_managed`).

### Troubleshooting

| Symptom | Fix |
|---|---|
| Wizard says Docker is unavailable | Start Docker Desktop, or choose the URL/container-less branches |
| Port already in use | The wizard picks the next free port (8080→8081, 6333→6334) and writes it to config |
| `get_status.services` shows `unavailable` | `docker ps -a`, inspect the container logs, then re-run `python setup.py` |
| Changed the embedding model | The dimension changes, so the collection name changes and the index re-embeds |
| Config changes ignored | The server reads config at startup — restart the harness session |
| `.simple-ci/index.db` deleted | Nothing to restore: the startup reconcile re-indexes the workspace |
| Want a clean rebuild | Delete `.simple-ci/` (or only `index.db`) and trigger an MCP call |

## Design docs (start here for implementation)

| Doc | Purpose |
|---|---|
| [docs/tdd.md](docs/tdd.md) | Technical design — build contract |
| [GLOSSARY.md](GLOSSARY.md) | Domain language |
| [docs/adr/](docs/adr/) | Architecture decision records |

## Runbook

### Start / stop

Start the backing services (let the wizard manage them, run your own compose project, or
`docker run` them), then let the harness spawn the server per session. Nothing to stop: the
server exits with the session.

```bash
# Qdrant, if you do not already run one
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

| Service | Endpoint |
|---|---|
| Embeddings (llama.cpp / OpenAI-compatible) | `http://localhost:8080/v1/embeddings` |
| Qdrant | `http://localhost:6333` |

Probe both before debugging anything else:

```bash
uv run python tests/service_probe.py    # expect: embeddings OK dim=<your config>, qdrant OK, PROBE OK
```

### Harness integration

`setup.py` writes the entry for you. The equivalent global MiMoCode snippet is:

```json
{
  "mcp": {
    "code-index": {
      "type": "local",
      "command": ["uvx", "--from", "d:/Projects/Python/simple-code-indexer", "simple-code-indexer"],
      "enabled": true,
      "timeout": 120000,
      "sampling": "deny"
    }
  }
}
```

- **Restart the harness session after changing that file** (config is read at session start).
- Slower to start than a container attach: the first `uvx` launch builds and installs in a
  cached environment (~5 s), every later launch is ~0.3 s. `uv tool install --from <repo>`
  once, then `"command": ["simple-code-indexer"]`, avoids even that.
- Gate: `mimo mcp list` must show `✓ code-index connected`.
- Tools exposed: `search_code` (lexical; `semantic=true` for Qdrant), `symbol_lookup`, `get_status`.

### Probes (no harness needed)

```bash
# services first, always
uv run python tests/service_probe.py

# stdio protocol + tool shapes (+ fixture symbol + semantic hit when PROBE_SYMBOL set)
PROBE_SYMBOL=calculateWidgetChecksum uv run python tests/mcp_probe.py

# index-on-save latency (creates/removes its own temp .cpp in the workspace)
uv run python tests/live_watch_probe.py
```

Run them from the workspace you want indexed: each probe spawns the server, which inherits
that cwd unless `WORKSPACE_ROOT` is set.

### Rebuild the index

The lexical+semantic index lives at `$WORKSPACE_ROOT/.simple-ci/index.db`, the vectors in the
per-workspace Qdrant collection. Switching collection (moving the project, changing
`EMBED_DIM`, editing `QDRANT_COLLECTION`, changing the embedding model) invalidates the
stored rows automatically on the next start, and the startup reconcile re-indexes and
re-embeds everything. To force that by hand — for example after upgrading code that changes
chunking — delete the DB and restart the session:

```bash
Remove-Item -Recurse -Force .simple-ci   # or: rm -rf .simple-ci
# then trigger any MCP call: startup reconcile re-embeds everything
```

### Diagnosis

| Symptom | Check |
|---|---|
| `mimo mcp list` → `Failed to get tools` | Run `tests/mcp_probe.py`; the probe fails loudly on `outputSchema`/`tasks` regressions. First `uvx` launch legitimately takes ~5 s. A managed container may take longer — raise the harness timeout. |
| Indexing the wrong tree / unexpected `collection` | `get_status.workspace` shows the resolved workspace. If the harness did not spawn the server in your project, set `WORKSPACE_ROOT`. |
| `get_status` → `watcher_alive: false` | Server not running / still starting; the watcher registers on a background thread (true within ~1 s of the first call). |
| `qdrant_ok`/`embed_ok: false` | `tests/service_probe.py`; check `get_status.services` and the Docker container logs. |
| Server exits with `already owns …index.db` | Two sessions share one workspace; the second refuses to start (single writer, ADR-0004). Close the other session. |
| Save not picked up within 5 s | Reconciliation sweep (45 s) is the backstop; then check `last_sweep` in `get_status`. |
| Semantic hits empty but lexical works | Collection changed without a rebuild (restart the session), or vectors failed earlier — the next sweep retries chunks whose `embedding_state` is not `ok`; if the log reports a vector-size mismatch, delete the collection or align `EMBED_DIM`. |
| `config_file: null` in `get_status` | Neither `<workspace>/.simple-ci/config.yaml` nor `~/.simple-ci/config.yaml` exists; run `python setup.py` or create one. |
| Logs | stderr of the spawned server (harness); never files in the workspace root. |

### Retired state

The pre-ADR-0008 deployment used a global collection `code_index_2560` and a
`docker exec`-attached container. Nothing reads that collection now — delete it in Qdrant
by hand when convenient. The old `.index/` directory is migrated by the wizard and remains
ignored for backwards compatibility.

## Harness plugins

The wizard's knowledge of each MCP client lives in
`src/simple_code_indexer/harnesses/` — plain modules with `NAME`, `HOME_DIRS`,
`GLOBAL_CONFIGS`, `LOCAL_CONFIGS`, `FORMAT`, `ROOT_KEY`, and optional `entry`/`render`.
Drop `my_harness.py` in [`harnesses/`](harnesses/) or `$WORKSPACE_ROOT/harnesses/` to add
one; a user plugin overrides a builtin by `NAME`. See
[harnesses/README.md](harnesses/README.md) for the contract. Bad plugins are logged and
skipped, never fatal.

## Language plugins

36 builtin languages ship in `src/simple_code_indexer/builtin/` (original
Code-Index-MCP set minus data/doc formats). To add one: drop `lang_name.py` in
[`plugins/`](plugins/) or `$WORKSPACE_ROOT/plugins/` — see
[plugins/README.md](plugins/README.md) for the contract. User plugins override
builtin plugins with the same `NAME`. Restart the server to pick up changes.
Data formats (json, yaml, markdown, …) are intentionally not indexed.

`get_status` reports `plugins_loaded` and `grammars_ready`. Grammars download
from tree-sitter-language-pack on demand (background prefetch at startup;
`PREFETCH_GRAMMARS=0` disables it).

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest
```

See [AGENTS.md](AGENTS.md) for agent-oriented setup notes.
