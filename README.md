# simple-code-indexer

Minimal code-index MCP server: file-watcher indexing into SQLite/FTS5 + Qdrant.

## Design docs (start here for implementation)

| Doc | Purpose |
|---|---|
| [implementation-prompt.md](implementation-prompt.md) | LLM implementation brief (skills + context + DoD) |
| [docs/tdd.md](docs/tdd.md) | Technical design — build contract |
| [GLOSSARY.md](GLOSSARY.md) | Domain language |
| [docs/adr/](docs/adr/) | Architecture decision records |

## Runbook

### Start / stop

```bash
docker compose up -d --build   # from the repo root (CWD matters for compose)
docker compose down
docker ps --filter name=code-index   # expect Up
```

External services (owned by other compose projects, must already be running):

| Service | Endpoint |
|---|---|
| Embeddings (llama.cpp) | `http://host.docker.internal:8080/v1/embeddings` |
| Qdrant | `http://host.docker.internal:6333` |

From-container probe (run these first when something looks down):

```bash
docker exec code-index python -c "import urllib.request,json; \
  req=urllib.request.Request('http://host.docker.internal:8080/v1/embeddings', \
  data=json.dumps({'model':'Qwen3-Embedding-4B-Q6_K','input':'probe'}).encode(), \
  headers={'Content-Type':'application/json'}); \
  print(len(json.load(urllib.request.urlopen(req,timeout=15))['data'][0]['embedding']))"
# expect: 2560

docker exec code-index python -c "import urllib.request,json; \
  print(json.load(urllib.request.urlopen('http://host.docker.internal:6333/collections'))['status'])"
# expect: ok
```

(PowerShell quoting is hostile — write a script file under `tests/` and run
`docker exec code-index python /workspace/tests/<file>.py` instead of inline.)

### Harness (MiMoCode) integration

- MCP config: `.mimocode/mimocode.json` → `docker exec -i code-index python -m simple_code_indexer.server`, `timeout: 60000`.
- **Restart the harness session after any change to that file** (config is read at session start).
- Gate: `mimo mcp list` must show `✓ code-index connected`.
- Tools exposed: `search_code` (lexical; `semantic=true` for Qdrant), `symbol_lookup`, `get_status`.

### Probes (no harness needed)

```bash
# stdio protocol + tool shapes (+ fixture symbol + semantic hit when PROBE_SYMBOL set)
docker exec -e PROBE_SYMBOL=calculateWidgetChecksum code-index python /workspace/tests/mcp_probe.py

# index-on-save latency (creates/removes its own temp .cpp in /workspace)
docker exec code-index python /workspace/tests/live_watch_probe.py
```

### Rebuild the index

The lexical+semantic index lives at `.index/index.db` (gitignored). Delete it to force a full re-index — needed after upgrading code if you want vectors re-embedded for unchanged files (hash short-circuit skips them otherwise):

```bash
docker compose down
Remove-Item -Recurse -Force .index      # or: rm -rf .index
docker compose up -d
# then trigger any MCP call: startup reconcile re-embeds everything (~30 s for this repo)
```

### Diagnosis

| Symptom | Check |
|---|---|
| `mimo mcp list` → `Failed to get tools` | Run `tests/mcp_probe.py`; the probe fails loudly on `outputSchema`/`tasks` regressions. |
| `get_status` → `watcher_alive: false` | Server not running / still starting; watcher registers on a background thread (should be true within ~1 s of the first call). |
| `qdrant_ok`/`embed_ok: false` | From-container probes above; check the service compose projects are up. |
| Save not picked up within 5 s | Reconciliation sweep (45 s) is the backstop; then check `last_sweep` in `get_status`. |
| Semantic hits empty but lexical works | Vectors may be missing for old files — rebuild the index (above). `embedding_state` table shows per-chunk `ok`/`error`. |
| Logs | stderr of the spawned server (harness/`docker exec`); never files in the workspace root. |

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
