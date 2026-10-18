# simple-code-indexer

Minimal code-index MCP server: file-watcher indexing into SQLite/FTS5 + Qdrant.

## How it runs

The harness spawns the server **on the host, inside the project you have open**:

- **Workspace** = the process working directory (`Path.cwd().resolve()`), overridable with `WORKSPACE_ROOT`.
- **Index** = `$WORKSPACE_ROOT/.index/index.db` — gitignore `.index/` in every indexed project.
- **Collection** = `code_index_{folder_slug}_{sha256(path)[:8]}_{embed_dim}`, derived per workspace so projects never share vectors. `QDRANT_COLLECTION` overrides it.
- **Services** = long-lived host services: Qdrant on `localhost:6333`, embeddings on `localhost:8080` (`Qwen3-Embedding-4B-Q6_K`, 2560-dim). See [ADR-0008](docs/adr/0008-host-spawned-cwd-per-repo-collections.md).

## Design docs (start here for implementation)

| Doc | Purpose |
|---|---|
| [docs/tdd.md](docs/tdd.md) | Technical design — build contract |
| [GLOSSARY.md](GLOSSARY.md) | Domain language |
| [docs/adr/](docs/adr/) | Architecture decision records |

## Runbook

### Start / stop

There is no container in this repo any more. Start the two backing services (owned by
their own compose projects / `docker run`), then let the harness spawn the server per
session. Nothing to stop: the server exits with the session.

```bash
# Qdrant, if you do not already run one
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

| Service | Endpoint |
|---|---|
| Embeddings (llama.cpp) | `http://localhost:8080/v1/embeddings` |
| Qdrant | `http://localhost:6333` |

Probe both before debugging anything else:

```bash
uv run python tests/service_probe.py    # expect: embeddings OK dim=2560, qdrant OK, PROBE OK
```

### Harness (MiMoCode) integration

Add this to your **global** harness config once — it works for every project, because the
server reads the workspace from its own cwd:

```json
{
  "mcp": {
    "code-index": {
      "type": "local",
      "command": ["uvx", "--from", "d:/Projects/Python/simple-code-indexer", "simple-code-indexer"],
      "enabled": true,
      "timeout": 60000,
      "sampling": "deny"
    }
  }
}
```

- **Restart the harness session after changing that file** (config is read at session start).
- Slower to start than a container attach: the first `uvx` launch builds and installs in a
  cached environment (~5 s), every later launch is ~0.3 s. `uv tool install --from <repo>`
  once, then `"command": ["simple-code-indexer"]`, avoids even that.
- This repo's own `.mimocode/mimocode.json` (gitignored) uses the snippet above.
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

The lexical+semantic index lives at `$WORKSPACE_ROOT/.index/index.db`, the vectors in the
per-workspace Qdrant collection. Switching collection (moving the project, changing
`EMBED_DIM`, editing `QDRANT_COLLECTION`) invalidates the stored rows automatically on the
next start, and the startup reconcile re-indexes and re-embeds everything (~30 s for this
repo). To force that by hand — for example after upgrading code that changes chunking —
delete the DB and restart the session:

```bash
Remove-Item -Recurse -Force .index      # or: rm -rf .index
# then trigger any MCP call: startup reconcile re-embeds everything
```

### Diagnosis

| Symptom | Check |
|---|---|
| `mimo mcp list` → `Failed to get tools` | Run `tests/mcp_probe.py`; the probe fails loudly on `outputSchema`/`tasks` regressions. First `uvx` launch legitimately takes ~5 s. |
| Indexing the wrong tree / unexpected `collection` | `get_status.workspace` shows the resolved workspace. If the harness did not spawn the server in your project, set `WORKSPACE_ROOT`. |
| `get_status` → `watcher_alive: false` | Server not running / still starting; the watcher registers on a background thread (true within ~1 s of the first call). |
| `qdrant_ok`/`embed_ok: false` | `tests/service_probe.py`; check the service compose projects are up. |
| Save not picked up within 5 s | Reconciliation sweep (45 s) is the backstop; then check `last_sweep` in `get_status`. |
| Semantic hits empty but lexical works | Collection changed without a rebuild (restart the session), or vectors failed earlier — `embedding_state` shows per-chunk `ok`/`error`; delete `.index/` to re-embed everything. |
| Logs | stderr of the spawned server (harness); never files in the workspace root. |

### Retired state

The pre-ADR-0008 deployment used a global collection `code_index_2560` and a
`docker exec`-attached container. Nothing reads that collection now — delete it in Qdrant
by hand when convenient. The `Dockerfile` and `docker-compose.yml` are gone.

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
