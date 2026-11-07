# simple-code-indexer

Minimal code-index MCP server: file-watcher indexing into SQLite/FTS5 with FAISS
semantic vectors (Qdrant optional).

## How it runs

The harness spawns the server **on the host, inside the project you have open**:

- **Workspace** = the process working directory (`Path.cwd().resolve()`), overridable with `WORKSPACE_ROOT`.
- **Index** = `$WORKSPACE_ROOT/.simple-ci/index.db` — gitignore `.simple-ci/` in every indexed project.
- **Config** = one global file, `~/.simple-ci/config.yaml`. Project-local
  `<workspace>/.simple-ci/config.yaml` files are legacy: the wizard migrates their keys into
  the global file and removes them, and the server never reads them. Environment variables
  override the file; `SIMPLE_CI_CONFIG` replaces discovery with one explicit file. See
  [ADR-0009](docs/adr/0009-setup-wizard-managed-services-config.md),
  [ADR-0011](docs/adr/0011-gpu-compose-global-config-model-prompts.md), and
  [ADR-0012](docs/adr/0012-global-config-appdata-install.md).
- **Vector store** = FAISS by default, persisted at `$WORKSPACE_ROOT/.simple-ci/vectors.faiss`
  (override with `faiss.path` or `FAISS_PATH`). Vectors are L2-normalised, so scores are
  cosine similarity. Qdrant stays available with `vector_store: qdrant`; its per-workspace
  collection is `code_index_{folder_slug}_{sha256(path)[:8]}_{embed_dim}` (`QDRANT_COLLECTION`
  overrides it). See [ADR-0010](docs/adr/0010-faiss-primary-vector-store.md).
- **Services** = an OpenAI-compatible embedding endpoint always, plus Qdrant only when the
  Qdrant backend is selected. They can be long-lived host services, or Docker containers the
  server starts on demand when `config.yaml` names them. See
  [ADR-0008](docs/adr/0008-host-spawned-cwd-per-repo-collections.md).
- **Models and containers** = downloaded into `~/.simple-ci/model/` and described by
  `~/.simple-ci/docker/docker-compose.yml`, generated from a packaged template. The wizard
  picks the llama.cpp image for the detected GPU (NVIDIA `server-cuda`, AMD `server-rocm`,
  Intel `server-intel`, otherwise `server`). See
  [ADR-0011](docs/adr/0011-gpu-compose-global-config-model-prompts.md).

## How to use

### Prerequisites

- **Python 3.12+** and **git**.
- **Docker Desktop** only if you want the wizard to download an embedding model or run
  Qdrant for you. The default FAISS backend needs no Docker at all, and existing services
  elsewhere work too.
- **GPU (optional)** — the wizard detects NVIDIA/AMD/Intel and uses the matching llama.cpp
  image. On NVIDIA, Docker must expose the container toolkit; the wizard copies
  `~/.simple-ci/docker/gpu_init.sh` and offers to run it when the runtime is missing, and
  falls back to the CPU image if that fails. `--gpu cpu` forces CPU.
- `uv` is installed by `setup.py` when missing.

### Quick start

```bash
git clone <repo> simple-code-indexer
cd simple-code-indexer
python setup.py
```

`setup.py` installs `uv` if needed, runs `uv sync`, and launches the interactive wizard
(questionary menus on every platform). Run `python setup.py --dry-run` first to see every
action without writing files or starting containers, or `python setup.py --yes` to accept the
recommended answer everywhere. For a reproducible install, pick the model and backend
explicitly:

```bash
python setup.py --yes --model embeddinggemma2 --gpu auto
python setup.py --yes --model qwen3-embedding-0.6b --vector-store faiss
python setup.py --yes --container llamacpp-qwen3-embedding-4b-q6_k --vector-store qdrant
```

The wizard copies the repo (including `.git`) to the per-user app directory and points every
selected harness at that copy:

| Platform | Install directory |
|---|---|
| Windows | `%APPDATA%\simple-code-indexer` |
| macOS | `~/Library/Application Support/simple-code-indexer` |
| Linux | `$XDG_DATA_HOME/simple-code-indexer` or `~/.local/share/simple-code-indexer` |

Harness entries run `<install>/.venv/.../python.exe <install>/run_server.py`. The launcher
runs `git pull --ff-only --autostash` first, runs `uv sync` only when `HEAD` moved, and then
starts the server **in the harness's working directory**, so workspace inference is preserved.

### What the wizard asks

| Step | Choices |
|---|---|
| Docker | Detected; if missing, offers to install it (`winget` on Windows, `brew` on macOS, the get.docker.com script on Linux) and waits for the daemon |
| Existing config | If `~/.simple-ci/config.yaml` exists, shows it and offers **use / reconfigure / show file / cancel** (`--config-mode use\|reconfigure` answers non-interactively) |
| Embedding source | A running server on `localhost:8080`, an existing Docker container (started for you; `--container NAME` forces one), an already-downloaded GGUF in `~/.simple-ci/model/`, a catalog download, or an existing URL |
| Embedding dimension | Always probed from a real `/v1/embeddings` call; catalog values are only an offline fallback |
| Vector store | **FAISS** (recommended — a local file, no Docker) or **Qdrant** (existing container/URL, or Docker compose) |
| Harnesses | Multi-select from detected harnesses; selected harnesses are always installed at their **global** scope (`--harnesses all\|none\|name,name` is non-interactive) |
| Install | Copies the repo to the per-user app directory and runs `uv sync` there (`--install-dir`, `--no-install`) |

The wizard also appends `.simple-ci/` to the project `.gitignore` and offers to migrate a
legacy `.index/` directory. `--config PATH` writes one explicit config file for tests/advanced
use. `--scope` was removed: configuration is always global.

### Model prompt instructions

The wizard records each model's documented code-retrieval prompts, and the server applies
them automatically when the model name matches (`embedding.query_prefix` and
`embedding.document_prefix` in `config.yaml` override them):

| Model | Query | Document (chunk) |
|---|---|---|
| EmbeddingGemma 2 | `task: code retrieval \| query: …` | `title: <relative path> \| text: …` |
| Qwen3-Embedding | `Instruct: Given a code search query, …\nQuery: …` | none |

`embed_texts` (service probes) stays raw. The document prefix is part of the vector-store
identity, so changing it re-embeds the workspace; changing only the query prefix does not.

### Where files land

| Path | Contents |
|---|---|
| `~/.simple-ci/config.yaml` | The only config file: embedding endpoint/model/prompts/service, vector store, Qdrant |
| `~/.simple-ci/docker/docker-compose.yml` | Generated services (`embed`, and `qdrant` only for the Qdrant backend) |
| `~/.simple-ci/docker/gpu_init.sh` | NVIDIA container-toolkit bootstrap copied by the wizard |
| `~/.simple-ci/model/` | Downloaded GGUF files (`embeddinggemma-2-BF16.gguf`, `Qwen3-Embedding-0.6B-Q8_0.gguf`, …) |
| `~/.simple-ci/qdrant_storage/` | Qdrant data when that backend is selected |
| `%APPDATA%/simple-code-indexer/` | Installed copy (`.git`, source, `.venv`, `run_server.py`) that harnesses launch |
| `<project>/.simple-ci/index.db` | SQLite index (+ WAL files and the single-writer lock) |
| `<project>/.simple-ci/vectors.faiss` | FAISS vectors (default backend; override with `faiss.path`) |

The FAISS index and SQLite database stay **per workspace**; only the configuration is global.
`vector_store` and an optional `faiss.path` live in the global file, so every project uses the
same backend choice. A relative `faiss.path` resolves against the workspace; an absolute path
shares one index file (opt-in). Config precedence is **environment variable > global YAML >
default**.


### Supported harnesses

Builtin plugins write the server entry into each client's own file:

| Harness | Global config (the wizard writes here) |
|---|---|
| Claude Code | `~/.claude.json` |
| Claude Desktop | `%APPDATA%/Claude/claude_desktop_config.json` (and macOS/Linux equivalents) |
| Codex CLI | `~/.codex/config.toml` (`[mcp_servers.<name>]`, `startup_timeout_sec = 120`) |
| Gemini CLI | `~/.gemini/settings.json` |
| OpenCode | `~/.config/opencode/opencode.json(c)` (`mcp.servers.<name>`) |
| Cursor | `~/.cursor/mcp.json` |
| Windsurf / Devin Local | `~/.config/devin/mcp_config.json` (legacy `~/.codeium/windsurf/mcp_config.json`) |
| VS Code | `%APPDATA%/Code/User/mcp.json` (and macOS/Linux equivalents) |
| Zed | `~/.config/zed/settings.json` |
| Cline | `~/.cline/data/settings/cline_mcp_settings.json` |
| Command Code | `~/.commandcode/mcp.json` |
| MiMoCode | `~/.config/mimocode/mimocode.json`, `~/.config/mimocode/config.json`, legacy `~/.mimocode/mimocode.json` |

The wizard does **not** ask where to save each harness: selected harnesses are installed at
their global scope. The entry is
`<install>/.venv/.../python <install>/run_server.py`. Restart the harness after it is written;
the file is read at session start. Codex/MiMo/OpenCode get a 120 s startup timeout because the
launcher may sync dependencies and the server waits for Docker services before serving.


### Manual config

FAISS (the default — no Qdrant section is needed):

```yaml
version: 1
vector_store: faiss        # VECTOR_STORE overrides this
embedding:
  base_url: http://localhost:8080
  model: embeddinggemma-2
  dim: 768                 # must match the endpoint; the wizard probes it
  api_key: null
  timeout_s: 15
  query_prefix: "task: code retrieval | query: {query}"
  document_prefix: "title: {title} | text: {content}"
  service:                 # optional: server starts this container at boot
    container: simple-ci-embed
    compose_file: /home/you/.simple-ci/docker/docker-compose.yml
    compose_service: embed
    startup_timeout_s: 60
faiss:
  path: .simple-ci/vectors.faiss   # optional; FAISS_PATH overrides it
sweep_seconds: 45
debounce_ms: 400
```

Qdrant instead:

```yaml
version: 1
vector_store: qdrant
embedding:
  base_url: http://localhost:8080
  model: embeddinggemma-2
  dim: 768
  query_prefix: "task: code retrieval | query: {query}"
  document_prefix: "title: {title} | text: {content}"
qdrant:
  url: http://localhost:6333
  collection: code_index_my-app_1a2b3c4d_768   # optional; derived when absent
  service:                 # optional: server starts this container at boot
    container: simple-ci-qdrant
    compose_file: /home/you/.simple-ci/docker-compose.yml
    compose_service: qdrant
    startup_timeout_s: 45
sweep_seconds: 45
debounce_ms: 400
```

These blocks live in the single global `~/.simple-ci/config.yaml`. The wizard writes
`embedding`, `vector_store`, `qdrant`, and the service blocks there; the index and vector
files stay per workspace. A config with **no** `vector_store` key but a non-empty `qdrant:`
section is treated as Qdrant, so existing installations keep their backend until they
explicitly switch.

When a `service` block is present the server verifies the container is running (starting it
if needed) and waits for the endpoint before serving. It never refuses to start: if Docker
or the service is unavailable, the server logs it, keeps lexical search working, and reports
the state in `get_status.services`. A `qdrant.service` block is ignored (state
`not_managed`) when the FAISS backend is active.

### Verify

```bash
uv run python tests/service_probe.py
uv run python tests/mcp_probe.py
```

`get_status` reports the resolved `workspace`, `vector_store`, `vector_store_ok`,
`vector_index` (the FAISS file path or the Qdrant collection), `config_file` (the global
file, or `null`), `config_files` (0 or 1 entry), and `services` (`running`, `started`,
`unavailable`, or `not_managed`). `tests/service_probe.py` resolves the same settings, so it
probes the configured endpoint and model automatically.

### Retrieval benchmark

`tests/retrieval_bench.py` indexes the workspace with one model/backend and scores the
40-query golden set in `tests/retrieval_queries.json` (Recall@1/5/10, MRR@10, nDCG@10, plus
a lexical FTS baseline):

```bash
uv run python tests/retrieval_bench.py --workspace . --model embeddinggemma-2 \
  --base-url http://localhost:8080 --vector-store faiss --reset \
  --out artifacts/bench/gemma-faiss.json
```

`tests/bench_matrix.py` runs every model/backend combination, starts the containers
(including the downloadable catalog models), deletes the index/collection between runs, and
writes `artifacts/retrieval-quality-*.{md,json}`:

```bash
uv run python tests/bench_matrix.py --workspace . --vector-stores faiss,qdrant
```

The existing Qwen3-4B container was originally created with `LLAMA_ARG_POOLING=mean`; after
recreating it with `last`, its nDCG@10 rose from 0.317 to 0.719. The wizard warns when it
detects a Qwen3 model in a mean-pooling container.

### Troubleshooting

| Symptom | Fix |
|---|---|
| Wizard says Docker is unavailable | Start Docker Desktop, or choose the URL/container-less branches |
| Port already in use | The wizard picks the next free port (8080→8081, 6333→6334) and writes it to config |
| GPU container exits immediately | `--gpu cpu`, or run `~/.simple-ci/docker/gpu_init.sh` in the WSL2/Linux distro that runs dockerd, then re-run setup. On Windows: `wsl --update` first |
| Container image is `server` despite an NVIDIA card | Docker does not expose the NVIDIA runtime; run the generated `gpu_init.sh` (or `--gpu nvidia` after fixing it) |
| Wizard offers to reuse the setup | It found `~/.simple-ci/config.yaml`; choose “reconfigure” or pass `--config-mode reconfigure`, or `--model KEY` to force a model |
| Qwen3 embeddings look poor | The container is probably using mean pooling. Qwen3-Embedding is trained for last-token pooling: recreate it with `LLAMA_ARG_POOLING=last` (the wizard warns when it detects this) |
| `get_status.services` shows `unavailable` | `docker ps -a`, inspect the container logs, then re-run `python setup.py` |
| Changed the embedding model | The dimension changes, so the vector-store identity changes and the index re-embeds |
| Config changes ignored | The server reads config at startup — restart the harness session |
| `.simple-ci/index.db` deleted | Nothing to restore: the startup reconcile re-indexes the workspace |
| `.simple-ci/vectors.faiss` deleted | Same: the store rebuilds empty and reconcile re-embeds every chunk |
| Want a clean rebuild | Delete `.simple-ci/` and trigger an MCP call |

## Design docs (start here for implementation)

| Doc | Purpose |
|---|---|
| [docs/tdd.md](docs/tdd.md) | Technical design — build contract |
| [GLOSSARY.md](GLOSSARY.md) | Domain language |
| [docs/adr/](docs/adr/) | Architecture decision records |

## Runbook

### Start / stop

Start the backing services (let the wizard manage them, run your own compose project, or
`docker run` them), then let the harness spawn the server per session. The FAISS backend
needs only the embedding endpoint. Nothing to stop: the server exits with the session.

```bash
# Qdrant, only when vector_store: qdrant
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

| Service | Endpoint | Required |
|---|---|---|
| Embeddings (llama.cpp / OpenAI-compatible) | `http://localhost:8080/v1/embeddings` | always |
| Qdrant | `http://localhost:6333` | only with `vector_store: qdrant` |

Probe before debugging anything else:

```bash
uv run python tests/service_probe.py    # expect: embeddings OK dim=<your config>, PROBE OK
                                        # (qdrant OK only when that backend is in use)
```

### Harness integration

`setup.py` writes the entry for you. The equivalent global MiMoCode snippet is:

```json
{
  "mcp": {
    "simple-code-indexer": {
      "type": "local",
      "command": [
        "C:\\Users\\you\\AppData\\Roaming\\simple-code-indexer\\.venv\\Scripts\\python.exe",
        "C:\\Users\\you\\AppData\\Roaming\\simple-code-indexer\\run_server.py"
      ],
      "enabled": true,
      "timeout": 120000
    }
  }
}
```

- **Restart the harness session after changing that file** (config is read at session start).
- The launcher runs `git pull --ff-only --autostash` in the installed copy, re-runs `uv sync`
  when `HEAD` moved, then starts the server in the harness's cwd. Set `SIMPLE_CI_GIT_PULL=0`
  to skip the pull (offline use or local development).
- Gate: `mimo mcp list` must show `✓ simple-code-indexer connected`.
- Tools exposed: `search_code` (lexical; `semantic=true` uses the vector store), `symbol_lookup`, `get_status`.

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

The lexical index lives at `$WORKSPACE_ROOT/.simple-ci/index.db`; the vectors live in
`$WORKSPACE_ROOT/.simple-ci/vectors.faiss` (FAISS) or the per-workspace Qdrant collection.
Switching the store, its path/URL/collection/dimension, the vector store backend, or the
embedding model invalidates the stored rows automatically on the next start, and the startup
reconcile re-indexes and re-embeds everything. Switching to FAISS leaves the old Qdrant
points orphaned; delete that collection by hand if you care. To force a rebuild by hand —
for example after upgrading code that changes chunking — delete `.simple-ci/` and restart
the session:

```bash
Remove-Item -Recurse -Force .simple-ci   # or: rm -rf .simple-ci
# then trigger any MCP call: startup reconcile re-embeds everything
```

### Diagnosis

| Symptom | Check |
|---|---|
| `mimo mcp list` → `Failed to get tools` | Run `tests/mcp_probe.py`; the probe fails loudly on `outputSchema`/`tasks` regressions. First `uvx` launch legitimately takes ~5 s. A managed container may take longer — raise the harness timeout. |
| Indexing the wrong tree / unexpected `vector_index` | `get_status.workspace` shows the resolved workspace. If the harness did not spawn the server in your project, set `WORKSPACE_ROOT`. |
| `get_status` → `watcher_alive: false` | Server not running / still starting; the watcher registers on a background thread (true within ~1 s of the first call). |
| `vector_store_ok`/`embed_ok: false` | `tests/service_probe.py`; check `get_status.services` and the Docker container logs. `vector_store_ok: false` with `vector_store: faiss` usually means faiss failed to import or the file is unwritable. |
| Server exits with `already owns …index.db` | Two sessions share one workspace; the second refuses to start (single writer, ADR-0004). Close the other session. |
| Save not picked up within 5 s | Reconciliation sweep (45 s) is the backstop; then check `last_sweep` in `get_status`. |
| Semantic hits empty but lexical works | The vector-store identity changed without a rebuild (restart the session), or vectors failed earlier — the next sweep retries chunks whose `embedding_state` is not `ok`; if the log reports a vector width/collection-size mismatch, align `EMBED_DIM` (and for Qdrant delete the mismatched collection). |
| `config_file: null` in `get_status` | `~/.simple-ci/config.yaml` does not exist; run `python setup.py` or create one. Project-local configs are ignored |
| Logs | stderr of the spawned server (harness); never files in the workspace root. |

### Retired state

The pre-ADR-0008 deployment used a global collection `code_index_2560` and a
`docker exec`-attached container. Nothing reads that collection now — delete it in Qdrant
by hand when convenient. The old `.index/` directory is migrated by the wizard and remains
ignored for backwards compatibility. Switching a workspace from Qdrant to FAISS (or back)
also leaves the previous store's vectors orphaned; the Qdrant collection can be deleted by
hand, and the FAISS file is replaced on the next identity reset.

The pre-ADR-0011 global layout (`~/.simple-ci/docker-compose.yml`, `~/.simple-ci/models/`)
is replaced by `~/.simple-ci/docker/docker-compose.yml` and `~/.simple-ci/model/`. The
wizard offers to rename the model directory and re-renders the compose file on the next
run; an old compose file is simply ignored.

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
