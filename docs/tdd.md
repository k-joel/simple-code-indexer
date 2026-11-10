# Technical Design — simple-code-indexer

**Status:** Ready for implementation handoff  
**Date:** 2026-10-17  
**Project:** `D:\Projects\Python\simple-code-indexer`  
**Domain terms:** [`GLOSSARY.md`](../GLOSSARY.md) · **Decisions:** [`docs/adr/`](./adr/)

**Deployment note (2026-10-18):** the shipped runtime is a **host-spawned** MCP process whose
workspace is its working directory, with one derived Qdrant collection per workspace
([ADR-0008](./adr/0008-host-spawned-cwd-per-repo-collections.md)). The Docker topology these
sections originally assumed was removed along with `Dockerfile` / `docker-compose.yml`
([ADR-0003](./adr/0003-all-in-one-mvp-topology.md)).

This document is the build contract for a **new, simplified** code-index MCP server. It is informed by a full investigation of upstream Code-Index-MCP but is **not** a port of that codebase. When this document and unfinished code disagree, this document wins.

---

## 1. Purpose

Give an AI coding assistant a fast search index over one local workspace — lexical (SQLite FTS5) and semantic (Qdrant) — maintained by a file watcher that **indexes on save**, exposed as a small MCP STDIO tool surface.

### 1.1 Goals

1. Satisfy the four original requirements (§2) and the acceptance test.
2. Stay at ~1/5 upstream complexity: one workspace, one SQLite file, one Qdrant namespace, one watcher, ~500–1500 lines.
3. Be operable from this repo with `uv` + Docker Compose + MiMoCode.

### 1.2 Non-goals (out of scope)

| Cut | Why |
|---|---|
| Git readiness / commit-gating / provenance | Requirement 4 is index-on-save; git was upstream's largest pain source ([ADR-0001](./adr/0001-index-on-save-not-git-state.md)) |
| Staged generation rebuilds / quarantine | Single-writer WAL is enough ([ADR-0004](./adr/0004-single-writer-sqlite-wal.md)) |
| Multi-repo registry / path sandbox / worktrees | One workspace ([ADR-0007](./adr/0007-single-workspace-no-multi-repo.md)) |
| LLM chunk summaries before vectors | Direct embedding ([ADR-0002](./adr/0002-direct-chunk-embedding.md)) |
| 48 language plugins / plugin sandbox | tree-sitter-language-pack + generic fallback |
| FastAPI gateway, JWT, Prometheus, Redis, rerankers | Admin/enterprise surface |
| GitHub Artifacts sync, attestations, MCP sampling/tasks | Extra dependencies and failure modes |
| `outputSchema`, `capabilities.tasks`, `execution.taskSupport` | Harness rejects them ([ADR-0006](./adr/0006-harness-safe-mcp-surface.md)) |

---

## 2. Requirements (verbatim contract)

1. Must run in a Docker container via `docker-compose.yml`. *(Superseded by ADR-0008: the server runs on the host; no container ships in this repo.)*
2. Must use an **externally configured embedding model**:
   - Model: `Qwen3-Embedding-4B-Q6_K`, dim **2560**
   - URL: `http://localhost:8080/v1/embeddings` (llama.cpp, OpenAI-compatible)
3. Must use **Qdrant** to store vectors: `http://localhost:6333`.
4. Must have a **file watcher that indexes a file whenever it is saved**.
5. MCP server configured in `.mimocode/mimocode.json` (MiMoCode); harness session must be closed/reopened after config changes.
6. **Acceptance test:** create a test `.cpp` file, wait for it to index, retrieve it successfully.

Nice-to-haves proven in the reference deployment and **in scope**: symbol lookup with line numbers, semantic (vector) search, `get_status`.

### 2.1 Definition of done

- All four original requirements + acceptance test green **through the harness**.
- `mimo mcp list` shows `✓ connected`.
- Semantic path exercised (`search_code(..., semantic=true)` with real embeddings + Qdrant).
- README runbook + “How to use” (setup wizard, config precedence, diagnosis).
- `ruff check` → `pyright` → `pytest` clean.

---

## 3. Environment facts (verified — do not re-derive)

| Fact | Value |
|---|---|
| Host | Windows; the MCP process runs natively and sees native filesystem events (bind-mount inotify is history — ADR-0008) |
| Embeddings | OpenAI-compatible at `0.0.0.0:8080` (llama.cpp on this host); accepts short name and full GGUF path as `model`; the dimension is whatever `config.yaml`/`EMBED_DIM` says and the wizard probes it (this host's original service was 2560-dim); also exposes `/v1/chat/completions` (do **not** depend on it for bulk work) |
| Qdrant | host `0.0.0.0:6333`, no auth; one derived collection per workspace, created on first use (the retired global `code_index_2560` is orphaned) |
| Workspace | the MCP process cwd (`WORKSPACE_ROOT` overrides) |
| MiMoCode | v0.1.15; local MCP = `{"type":"local","command":[…],"timeout":<ms>,"sampling":"deny\|ask\|allow"}` in `.mimocode/mimocode.json` |
| Default tools timeout | **5000 ms** — set `"timeout": 120000` on the server entry (startup may wait for managed containers) |
| Harness reload | config read at session start; restart harness after changes |

---

## 4. Architecture overview

### 4.1 Topology (MVP)

**All-in-one** ([ADR-0003](./adr/0003-all-in-one-mvp-topology.md), host-spawned per [ADR-0008](./adr/0008-host-spawned-cwd-per-repo-collections.md)): one process per harness session, started with the session's project as its working directory.

```
MiMoCode harness  (session cwd = project root)
    │  stdio JSON-RPC (newline-delimited)
    ▼
uvx --from <repo> simple-code-indexer      # host process; cwd inherited
    │
    ├─ MCP stdio loop: initialize / tools/list / tools/call
    │     search_code | symbol_lookup | get_status [| reindex]
    │
    ├─ Index writer (same process, worker thread)
    │     debounce queue → index_one_file → SQLite + Qdrant
    │
    └─ Watcher (watchdog Observer, background thread)
          workspace root (cwd), one recursive watch → events → queue
```

**Sidecar (post-MVP, config change only):** compose runs `watcher+indexer` as PID 1; MCP is a read-only query process. Queue/worker interface is identical.

### 4.2 Data flow — index on save

```
host file save
  → native filesystem event (no bind mount, no inotify forwarding)
  → watchdog Observer (workspace root)        [start on background thread]
  → per-path DEBOUNCE (300–500 ms)                [collapse temp+rename bursts]
  → bounded work queue (never index in the callback)
  → index_one_file(path):
       skip if ext not in allowlist, temp name, IGNORE_DIRS, or .gitignore match
       skip if sha256(content) == stored hash
       parse symbols (tree-sitter) → UPSERT symbols
       chunk → DELETE chunks/chunks_fts by file → INSERT
       UPDATE files(path, hash, mtime, language, size, indexed_at)
       embed chunk texts (batched) → Qdrant upsert by stable point id
         point id = uuid5(NAMESPACE, path|chunk_index)
  on deleted/moved → DELETE rows by path + Qdrant delete-by-filter(path)
```

### 4.3 Reliability backstops

1. **Reconciliation sweep** every `SWEEP_SECONDS` (default 45): walk workspace (respect ignores), compare `mtime+size`, then `sha256` on candidates; run `index_one_file` for mismatches.
2. **Startup reconcile:** same pass once at process start.
3. Optional `watchdog.polling.PollingObserverV2` behind env flag — **not implemented**; native filesystems deliver events reliably, and the sweep is the backstop.

Design rules:

- Never block the observer callback.
- Single writer owns writes; MCP query path is read-only (WAL).
- Fail soft: one bad file logs and continues.

### 4.4 Search path

1. `search_code(query, semantic=false, limit)`:
   - Lexical: FTS5 BM25 over `chunks_fts`, join to `files` for path/lines/snippet.
   - Semantic: embed query with the same endpoint → Qdrant search → map point IDs to chunks.
   - Hybrid (optional later): fuse ranks; v1 may return semantic hits only when `semantic=true`.
2. `symbol_lookup(symbol)`: exact then prefix match on `symbols.name`; return kind, file, line, signature.
3. `get_status()`: counts, `watcher_alive`, `last_sweep`, `ignored_dirs`/`ignored_files` (last sweep), `vector_store_ok`, `embed_ok`.

---

## 5. Domain model

See [`GLOSSARY.md`](../GLOSSARY.md) for canonical terms. Core entities:

| Entity | Identity | Key attributes |
|---|---|---|
| Workspace | single root path | the process cwd, index under `.simple-ci/` |
| File record | `path` (unique) | language, size, sha256, mtime, indexed_at |
| Symbol | (`file_id`, name, line) | kind, line_end, signature |
| Chunk | (`file_id`, chunk_index) | start_line, end_line, content |
| Point ID | `uuid5(ns, path\|chunk_index)` | stable across re-index |

Relationships: File 1—* Symbol, File 1—* Chunk. Qdrant points reference chunk identity via payload `{path, chunk_index}`.

---

## 6. Data model

### 6.1 SQLite (`$WORKSPACE_ROOT/.simple-ci/index.db`)

WAL mode, `busy_timeout=5000`, single writer. Startup takes an OS advisory lock on
`<index_db>.lock`; a second server process for the same workspace refuses to start.

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS files (
  id          INTEGER PRIMARY KEY,
  path        TEXT NOT NULL UNIQUE,
  language    TEXT NOT NULL,
  size        INTEGER NOT NULL,
  sha256      TEXT NOT NULL,
  mtime       REAL NOT NULL,
  indexed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
  id          INTEGER PRIMARY KEY,
  file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL,
  line        INTEGER NOT NULL,
  line_end    INTEGER,
  signature   TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);

CREATE TABLE IF NOT EXISTS chunks (
  id          INTEGER PRIMARY KEY,
  file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  start_line  INTEGER NOT NULL,
  end_line    INTEGER NOT NULL,
  content     TEXT NOT NULL,
  UNIQUE(file_id, chunk_index)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  content,
  content='chunks',
  content_rowid='id',
  tokenize='unicode61'
);

-- optional but recommended for observability
CREATE TABLE IF NOT EXISTS embedding_state (
  chunk_id       INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  qdrant_point_id TEXT NOT NULL,
  status          TEXT NOT NULL,  -- pending | ok | error
  updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (          -- binds the DB to one endpoint + collection
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL                      -- qdrant_url | qdrant_collection
);
```

`meta` records the Qdrant endpoint and collection this DB feeds. When either differs — or
when rows exist with no recorded identity — every row is dropped at startup: those chunks
have no vectors where the next write lands and the hash/mtime short circuits would never
re-embed them, so the reconcile must re-index from scratch.

**Update protocol for one file:** in a single writer transaction — delete symbols/chunks (and FTS rows via `chunks_fts` delete trigger or explicit `INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', …)`), insert fresh rows, upsert `files`. Keep triggers or an explicit FTS sync so `chunks` and `chunks_fts` never diverge.

### 6.2 Qdrant

- URL: `QDRANT_URL` (default `http://localhost:6333`).
- Collection: `code_index_{slug}_{sha256(normalized path)[:8]}_{embed_dim}` — derived per
  workspace (`slug` = folder name, non-alphanumerics → `-`, capped at 32, `root` when empty;
  normalized path = resolved, lowercased, forward slashes). `QDRANT_COLLECTION` overrides it.
  Vector dim **2560**, distance **Cosine**. Created on first use; `ensure_collection` caches
  per `(url, collection)`. An existing collection's configured vector size is validated
  against `embed_dim` — a mismatch (or named vectors) raises rather than failing every upsert.
- Point ID: `uuid5(NS, f"{path}:{chunk_index}")`.
- Payload: `{"path": str, "chunk_index": int}`.
- Delete: filter `path == deleted_path`.
- Upsert is idempotent (same ID replaces).

### 6.3 Filesystem layout

```
<workspace>/                 # the project the harness opened (process cwd)
  .simple-ci/
    index.db                 # SQLite WAL (gitignore this whole directory)
    vectors.faiss            # FAISS index (default vector store)
    log/sci.log              # runtime diagnostics (rotated, gitignored)
    config.yaml              # optional per-project config (may hold an API key)
  …user files…
<repo>/src/simple_code_indexer/…   # the server itself (uvx-built env; no image)
```

Never write logs into the workspace root (gitignore `.simple-ci/`). The only log file is
`<workspace>/.simple-ci/log/sci.log`: DEBUG in the file, INFO on stderr, and never stdout
(the MCP channel).

---

## 7. Component design

Package: `src/simple_code_indexer/` (import name `simple_code_indexer`).  
Python conventions follow [`python-patterns`](../../AGENTS.md): type hints on public functions, `pathlib.Path`, dataclasses/NamedTuple for records, EAFP at boundaries, context managers for DB/files, no mutable default args, stdlib first.

### 7.1 Modules

```
src/simple_code_indexer/
  __init__.py          # version, main() entry
  config.py            # Settings from config.yaml + env (frozen dataclass)
  configfile.py        # config discovery, YAML load/write, typed getters
  errors.py            # IndexerError hierarchy (Embed, Parse, Qdrant, Config)
  models.py            # FileRecord, Symbol, Chunk, SearchHit (dataclasses)
  db.py                # schema ensure, connection helpers, FTS queries
  parse.py             # tree-sitter symbol extraction + chunking
  embed.py             # OpenAI-compatible embeddings client (query/document prompts)
  model_prompts.py     # documented code-retrieval prefixes for supported models
  qdrant_store.py      # ensure_collection, upsert, delete_by_path, search
  ignore.py            # IgnoreRules: workspace .gitignore (root + nested) matching
  indexer.py           # index_one_file, sweep, startup reconcile
  watcher.py           # recursive root Observer + debounce queue → indexer
  services.py          # start managed containers, wait for readiness (fail-soft)
  logging_setup.py     # stderr INFO + per-workspace rotating debug log
  server.py            # MCP stdio: initialize, tools/list, tools/call
  builtin/             # language plugins
  harnesses/           # MCP-client plugins used by the setup wizard
  setup_wizard/        # interactive setup (prompts, probes, provisioning, writes)
    gpu.py             # vendor detection → llama.cpp image tag
    templates/         # docker-compose.yml + gpu_init.sh shipped in the wheel
```

### 7.2 `config.py`

```python
@dataclass(frozen=True, slots=True)
class ManagedService:
    container: str
    compose_file: Path | None = None
    compose_service: str | None = None
    startup_timeout_s: float = 45.0

@dataclass(frozen=True, slots=True)
class Settings:
    workspace_root: Path
    index_db_path: Path
    qdrant_url: str
    qdrant_collection: str
    embed_base_url: str          # e.g. http://localhost:8080
    embed_model: str             # Qwen3-Embedding-4B-Q6_K
    embed_dim: int               # 2560 (config.yaml / EMBED_DIM; probe it when unsure)
    embed_timeout_s: float       # 15
    sweep_seconds: float         # 45
    debounce_ms: int             # 400
    allowed_exts: frozenset[str]
    ignore_dirs: frozenset[str]
    allowed_filenames: frozenset[str] = frozenset()
    embed_api_key: str | None = None
    embedding_service: ManagedService | None = None
    qdrant_service: ManagedService | None = None
    config_source: Path | None = None
    vector_store: str = "faiss"
    faiss_path: Path | None = None
    embed_query_prefix: str | None = None       # e.g. "task: code retrieval | query: {query}"
    embed_document_prefix: str | None = None    # e.g. "title: {title} | text: {content}"
    embed_fingerprint: str = ""                 # sha256(document_prefix + chunker)[:8]
    config_sources: tuple[Path, ...] = ()       # every layered file, lowest precedence first
    log_level: str = "debug"                    # file verbosity; stderr stays at info
    log_max_bytes: int = 5_000_000              # rotation threshold
    log_backups: int = 3                        # sci.log.1 … sci.log.3
```

Load order: `SIMPLE_CI_CONFIG` (an explicit path; `none`/`off` disables discovery) →
`~/.simple-ci/config.yaml` (global) → `<workspace>/.simple-ci/config.yaml` (local). Both
files are deep-merged, with the local file winning individual keys; `find_config_file()`
still returns the most specific path for compatibility. Each setting's own environment
variable overrides the merged file value.

Prompt resolution is env (`EMBED_QUERY_PREFIX`, `EMBED_DOCUMENT_PREFIX`) > explicit file
value (empty disables) > `model_prompts.defaults_for_model(embed_model)`. Templates are
validated at load time (`{query}` / `{title}` / `{content}`); bad placeholders raise
`ConfigError`. `embed_fingerprint` hashes the document prefix plus the chunker profile
(`parse.CHUNKER_VERSION`), because both change stored chunk vectors; it is appended to the
FAISS identity and the derived Qdrant collection name. Changing only the query prompt does
not change the fingerprint and does not force a re-embed.
**Never** hardcode secrets in code; `EMBED_API_KEY` / `embedding.api_key` is optional and
sent as a bearer token. If a feature is unused, omit it from config entirely (no empty
blocks that enable fallbacks).

Env names (minimum set):

| Variable | Default |
|---|---|
| `WORKSPACE_ROOT` | the process cwd (an inferred user home directory is refused) |
| `SIMPLE_CI_CONFIG` | discovery (`none` disables; tests set this) |
| `INDEX_DB` | `$WORKSPACE_ROOT/.simple-ci/index.db` |
| `QDRANT_URL` | `http://localhost:6333` |
| `QDRANT_COLLECTION` | derived per workspace: `code_index_{slug}_{path_hash}_{embed_dim}` |
| `EMBED_BASE_URL` | `http://localhost:8080` |
| `EMBED_MODEL` | `Qwen3-Embedding-4B-Q6_K` |
| `EMBED_DIM` | `2560` |
| `EMBED_QUERY_PREFIX` | model default (`task: code retrieval \| query: {query}` for EmbeddingGemma 2, `Instruct: …\nQuery: {query}` for Qwen3) |
| `EMBED_DOCUMENT_PREFIX` | model default (`title: {title} \| text: {content}` for EmbeddingGemma 2; none for Qwen3) |
| `EMBED_API_KEY` | unset |
| `EMBED_TIMEOUT_S` | `15` |
| `VECTOR_STORE` | `faiss` (`faiss` or `qdrant`) |
| `FAISS_PATH` | `$WORKSPACE_ROOT/.simple-ci/vectors.faiss` |
| `SWEEP_SECONDS` | `45` |
| `DEBOUNCE_MS` | `400` |
| `LOG_LEVEL` | `debug` (`debug` \| `info` \| `warning` \| `error` \| `critical`; file only) |
| `LOG_MAX_BYTES` | `5000000` |
| `LOG_BACKUPS` | `3` |

### 7.3 `db.py`

- `connect(readonly: bool) -> sqlite3.Connection` — WAL, busy_timeout, row factory.
- `ensure_schema(conn)`.
- `upsert_file`, `replace_file_symbols`, `replace_file_chunks`, `delete_file`.
- `fts_search(query, limit) -> list[SearchHit]`.
- `symbol_lookup(name) -> list[Symbol]`.
- `stats() -> dict`.

Use context managers for connections; specific exceptions (`sqlite3.Error`) wrapped at the service boundary.

### 7.4 `parse.py`

- `detect_language(path) -> str | None` from extension allowlist.
- `extract_symbols(path, source) -> list[Symbol]` via `tree_sitter_language_pack.get_parser(lang)`.
- `chunk_source(source, max_lines=30, max_chars=1200, overlap_lines=15) -> list[Chunk]` — line-aligned overlapping windows. Focused windows matter for mean-pooled embedding models; 50% overlap keeps a symbol inside at least one window even when it straddles a boundary. A char-budget cut never skips lines (the next window starts at the first uncovered line). Fallback for unknown languages: regex-ish symbol scan (def/class/function) + the same chunker. Changing the defaults/overlap requires bumping `CHUNKER_VERSION` so stored vectors are invalidated.

v1 allowlist minimum: `.cpp`, `.cc`, `.cxx`, `.h`, `.hpp`, `.py`, `.ts`, `.js`. Generic chunking for anything else in the allowlist.

**Lazy-load parsers** (do not import language packs at module import time) so startup stays <3 s.

### 7.5 `embed.py`

- `embed_texts(texts: Sequence[str]) -> list[list[float]]` — one or more POSTs to
  `{base}/v1/embeddings` with `{"model": …, "input": texts}`; inputs are split into batches of at
  most 16 pieces so a bulk reindex cannot occupy the shared endpoint for an entire file. Raw: no
  prompt, used by service probes.
- `embed_documents(texts, title=…)` — applies `embed_document_prefix` (EmbeddingGemma 2's `title: {title} | text: {content}`, `title: none` when absent) then calls `embed_texts`.
- `embed_query(text)` — applies `embed_query_prefix` (EmbeddingGemma's `task: code retrieval | query: …`, Qwen3's `Instruct: …\nQuery: …`) then calls `embed_texts`.
- Explicit `timeout=15`, **retries=0..2**, no default OpenAI client behavior toward the public internet.
- At most 2 HTTP posts in flight per process (`threading.BoundedSemaphore`), and retries use
  full-jitter exponential backoff (`U(0, min(2 s, 0.5 s · 2^attempt))`). This is request-level
  back-pressure, not an endpoint-wide limiter: N workspaces still multiply the load.
- Measure dim on first response; assert equals `Settings.embed_dim`.
- Fail soft on index path: log, mark `embedding_state.status='error'`, continue lexical indexing.
- Retry on the next sweep: `indexer.reembed_pending` re-embeds chunks whose
  `embedding_state.status != 'ok'` (or that lack a row), independent of the hash/mtime
  short circuits, stopping at the first failing file.

### 7.6 `qdrant_store.py`

- `ensure_collection(settings)` — create when missing, validate an existing collection's
  vector size, cached per `(qdrant_url, qdrant_collection)`.
- `upsert_chunks(path, chunk_vectors)` using stable point IDs.
- `delete_by_path(path)`.
- `search(vector, limit) -> list[point]`.

### 7.7 `indexer.py`

- `relative_path(settings, path) -> str | None` — workspace-relative POSIX path.
- `index_one_file(path: Path, rules: IgnoreRules | None = None) -> IndexOutcome` — the unit
  of work (hash short-circuit); applies `IGNORE_DIRS` and `.gitignore` before reading bytes.
- `sweep(rules: IgnoreRules | None = None) -> SweepStats` — retry pending embeddings, then
  mtime+size then hash candidates; `ignored_dirs`/`ignored_files` count `.gitignore` pruning
  and land in `LAST_SWEEP_STATS` (read by `get_status`).
- `iter_workspace_files(settings, rules, stats)` — `os.walk` with `dirnames[:]` pruning.
- `startup_reconcile()`.
- Bounded `queue.Queue` consumer; items are paths or tombstones; one matcher per writer.

`IndexOutcome` (NamedTuple): `path`, `status` (`indexed|skipped_unchanged|skipped_filtered|error`), `duration_ms`.

### 7.8 `watcher.py`

- **One recursive** `Observer.schedule(handler, workspace_root, recursive=True)` — watchdog maps this to a single `ReadDirectoryChangesW(bWatchSubtree=TRUE)` and one emitter thread on Windows. Never go back to one watch per directory: that produced one thread per directory (ISS-7).
- `observer.schedule()` + `observer.start()` **on a daemon thread**; if the watch fails, log and let the sweep act as the backstop (`watcher_alive=false`).
- Debounce per path 300–500 ms; on fire enqueue; never index in the callback.
- Handle `on_created` / `on_modified` / `on_moved` / `on_deleted`; directory events need no extra scheduling (the recursive watch covers new subtrees).
- Ignore at event time: temp editor names (`*~`, `*.tmp`, `.#*`), `IGNORE_DIRS` components (`.git`, `.index`, `.simple-ci`, `__pycache__`, `.venv`, `node_modules`), and workspace `.gitignore` matches (`ignore.IgnoreRules`).
- A `.gitignore` created/modified/moved/deleted outside `IGNORE_DIRS` enqueues `SWEEP_REQUEST`, so newly ignored rows are purged and unignored files indexed immediately.

### 7.9 `server.py` (MCP)

Official `mcp` SDK:

- `Server("simple-code-indexer")`
- `@server.list_tools` → **exactly** the tools below, short descriptions, **no `outputSchema`**
- `@server.call_tool` → dispatch
- `mcp.server.stdio.stdio_server()`
- Initialize result: **no** `capabilities.tasks`
- Per-tool: **no** `execution.taskSupport`
- Startup: open DB, ensure schema, `ensure_index_identity` (wipe rows left by another endpoint or collection), `startup_reconcile` on worker thread, start watcher on daemon thread, **then** serve (target ready <3 s)

---

## 8. MCP tool contracts

Output shapes are the contract (probe-tested). Do not emit `outputSchema`.

### 8.1 `search_code`

**Input**

| Field | Type | Default | Notes |
|---|---|---|---|
| `query` | string | required | free text or code idiom |
| `semantic` | bool | `false` | use Qdrant path |
| `limit` | int | `10` | clamp 1..50 |

**Output**

```json
{
  "hits": [
    {
      "file": "src/foo.cpp",
      "line": 42,
      "end_line": 58,
      "snippet": "…highlighted match…",
      "score": 12.3,
      "source": "lexical"
    }
  ],
  "source": "lexical"
}
```

When `semantic=true`, `source` is `"semantic"` (or `"hybrid"` if fused later). Semantic responses
always include `ready` and `pending_embeddings` (chunks whose `embedding_state.status != 'ok'`);
`message` appears only while `ready` is false:

```json
{
  "hits": [],
  "source": "semantic",
  "ready": false,
  "pending_embeddings": 12,
  "message": "semantic index is warming up: 12 chunk(s) still pending embedding"
}
```

An empty `hits` with `ready: false` means vectors are still being written, not that nothing
matched; `ready: true` with empty `hits` is a genuine no-match. A failed embedding or vector-store
call returns `ready: false` with a `semantic search unavailable: …` message instead of raising.

### 8.2 `symbol_lookup`

**Input:** `symbol` (string, required).

**Output**

```json
{
  "symbol": "calculateWidgetChecksum",
  "kind": "function",
  "defined_in": "widget_checksum.cpp",
  "line": 9,
  "line_end": 20,
  "signature": "uint32_t calculateWidgetChecksum(const Widget&)",
  "language": "cpp"
}
```

Not found: `{"symbol": "…", "found": false, "matches": []}`.  
Ambiguous: `found: true` with `matches[]` sorted by path.

### 8.3 `get_status`

**Output**

```json
{
  "files_indexed": 12,
  "symbols_indexed": 87,
  "chunks_indexed": 240,
  "vectors_indexed": 228,
  "pending_embeddings": 12,
  "watcher_alive": true,
  "last_sweep": "2026-10-17T20:01:02Z",
  "ignored_dirs": 3,
  "ignored_files": 12,
  "vector_store": "faiss",
  "vector_store_ok": true,
  "vector_index": "d:/projects/my-app/.simple-ci/vectors.faiss",
  "embed_ok": true,
  "plugins_loaded": 36,
  "grammars_ready": 36,
  "workspace": "d:/projects/my-app",
  "index_db": "d:/projects/my-app/.simple-ci/index.db",
  "config_file": "C:/Users/me/.simple-ci/config.yaml",
  "config_files": ["C:/Users/me/.simple-ci/config.yaml"],
  "log_file": "d:/projects/my-app/.simple-ci/log/sci.log",
  "log_level": "debug",
  "services": {"embedding": "running", "qdrant": "not_managed"}
}
```

`workspace` is how a live harness's workspace inference is verified (`vector_index` names
the FAISS file or the derived Qdrant collection). `ignored_dirs`/`ignored_files` are what
the last sweep pruned via `.gitignore` (0 before the first sweep completes or when none
match). `vectors_indexed` counts chunks with `embedding_state.status='ok'`; `pending_embeddings`
is `chunks_indexed - vectors_indexed` (an absent row, `error`, and `missing` all count as
pending). `vector_store_ok` alone does not mean vectors exist — it is true for an empty index.
`config_file` is `null` when no config file exists. `log_file` is `null` when the
log could not be opened. `services` values are `running`, `started`, `unavailable`, or
`not_managed`.

### 8.4 `reindex` (optional, phase 5+)

**Output:** `{"queued": N, "status": "started"}` — enqueue full sweep, return immediately. Keep the tool absent until the first three are stable.

---

## 9. Deployment

### 9.1 Host process

- Run `uvx --from <repo> simple-code-indexer`; the harness does this for you. `python setup.py`
  writes that entry into each selected harness config. `uv tool install --from <repo>
  simple-code-indexer` once, then the bare command, skips the ~5 s first build.
- The process inherits the harness cwd as its workspace (`WORKSPACE_ROOT` overrides); it writes `$WORKSPACE_ROOT/.simple-ci/index.db` and exits with the session. An inferred workspace that is the user's home directory is refused instead of indexed.
- Before serving, `services.ensure_managed_services` starts any containers named in
  `embedding.service` / `qdrant.service` and waits for their endpoints (fail-soft).
- No image for the server itself: `Dockerfile` and `docker-compose.yml` were removed with the Docker topology ([ADR-0008](./adr/0008-host-spawned-cwd-per-repo-collections.md)); the wizard renders `~/.simple-ci/docker/docker-compose.yml` from the packaged template for the backing services, choosing the llama.cpp image for the detected GPU ([ADR-0011](./adr/0011-gpu-compose-global-config-model-prompts.md)).

### 9.2 Backing services

Qdrant and llama.cpp/embeddings are owned by the user and must already be listening, or be
declared as managed services in `config.yaml` so the server starts them. `python setup.py`
can generate the compose file and download a GGUF.

```bash
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

### 9.3 `.mimocode/mimocode.json`

```json
{
  "$schema": "https://mimo.xiaomi.com/mimocode/config.json",
  "mcp": {
    "code-index": {
      "type": "local",
      "command": ["uvx", "--from", "<this repo>", "simple-code-indexer"],
      "enabled": true,
      "timeout": 120000,
      "sampling": "deny"
    }
  }
}
```

Restart the harness after any change to this file.

### 9.4 Host probes (run first, always)

```bash
uv run python tests/service_probe.py     # embeddings dim + qdrant status
uv run python tests/mcp_probe.py         # stdio contract, tool shapes, status keys
uv run python tests/live_watch_probe.py  # index-on-save latency
```

Run them from the workspace to index — the server inherits that cwd. Expect the dimension
configured for that workspace and an OK collections payload. Debug nothing else until both pass.

---

## 10. Error handling & operational pitfalls

| Pitfall | Rule |
|---|---|
| Oversized tools/list | No `outputSchema`; short descriptions; 2–3 tools at first |
| 5 s tool timeout | `timeout: 120000` + fail-soft startup (lazy parsers, watcher on thread, managed containers bounded by `startup_timeout_s`) |
| Services not reachable | `uv run python tests/service_probe.py` (Qdrant `localhost:6333`, embeddings `localhost:8080`) before anything else |
| Dummy `OPENAI_API_KEY` | Never set it — enables real api.openai.com retries |
| Config blocks that enable features | If unused, omit entirely (no empty `summarization:` key) |
| Harness cwd ≠ project | `get_status.workspace` reports the resolved workspace; set `WORKSPACE_ROOT` when a harness spawns servers from elsewhere |
| Cold `uvx` build on first launch | ~5 s once per source change, cached afterwards; `uv tool install` removes even that |
| Collection switch without re-embed | `ensure_index_identity` wipes the index so the reconcile re-embeds; a manual `.simple-ci/` delete does the same |
| Observer thread explosion | One recursive root watch (one emitter); never schedule per directory (ISS-7) |
| Dropped inotify events | Sweep + startup reconcile always on |
| Multi-writer races | One writer; design out, don't lock harder |
| Slow network in write path | Local-first; embeddings short timeout + fail soft |
| Logs in workspace | stderr + gitignored `<workspace>/.simple-ci/log/sci.log` only |

Exceptions: define a small hierarchy (`IndexerError` → `EmbedError`, `ParseError`, `QdrantUnavailable`) and catch at process boundaries — never bare `except:`.

---

## 11. Testing strategy

### 11.1 Unit (pytest, no Docker)

- `parse`: symbols + chunks on sample `.cpp` / `.py` fixtures.
- `db`: schema, upsert/delete, FTS hit shape, hash short-circuit.
- `indexer`: `index_one_file` on tmp_path; sweep detects drift; delete removes rows.
- `config`: env parsing defaults; no key required.

### 11.2 Integration (optional markers)

- `embed` / `qdrant` against local services when reachable; skip otherwise.
- Stdio probe (`.mcp-probe.py` pattern): `initialize` → `tools/list` → `tools/call get_status`.

### 11.3 Acceptance (manual / scripted, through harness)

1. `uv run python tests/service_probe.py` — Qdrant and embeddings reachable
2. `mimo mcp list` → `✓ connected`
3. Harness session reload (config is read at session start)
4. Create `widget_checksum.cpp` with unique symbol `calculateWidgetChecksum`
5. Poll `search_code` / `symbol_lookup` until found (target <5 s)
6. `search_code(..., semantic=true)` returns a hit (vectors may lag a few seconds)
7. `get_status` healthy, with the expected `workspace` and `collection`
8. Open a second project in another session → different `collection`, no cross-hits

### 11.4 Quality gates

```bash
uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest
```

---

## 12. Implementation plan

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **0 Scaffold** | package layout, `pyproject` deps | `uv run pytest` smoke green |
| **1 Harness gate** | MCP server with **only** `get_status`, mimocode.json | `mimo mcp list` `✓ connected`; stdio probe works |
| **2 Indexer** | SQLite schema + FTS, `.cpp` parse, `search_code`/`symbol_lookup` over startup-built index | unit tests pass; probe finds fixture symbols |
| **3 Watcher** | observer + debounce + per-file upsert; sweep + startup reconcile | create `test.cpp` → found in <5 s without manual reindex |
| **4 Embeddings + Qdrant** | embed-on-index, embed-on-query, `semantic=true` | host probes + semantic hit on acceptance file |
| **5 Acceptance** | full test through harness; resilience check | DoD §2.1 |
| **6 Optional** | topology B sidecar | always-on watch with harness closed |
| **7 Setup + config** | `setup.py` wizard, layered `config.yaml`, managed services, harness plugins, `.simple-ci/` rename | fresh clone → `python setup.py` → harness connects; `ruff`/`pyright`/`pytest` green |

**Phase 1 is a hard gate** — do not build the indexer until `mimo mcp list` is green (harness integration is risk #1).

---

## 13. Coding standards (python-patterns)

- **Type hints** on all public functions; modern built-in generics (`list[str]`, `dict[str, int]`).
- **Dataclasses** (`frozen=True`, `slots=True` where practical) for records and settings; NamedTuple for small results.
- **EAFP** at boundaries; specific exception types; chain with `raise … from e`.
- **Context managers** for sqlite, files, timers.
- **pathlib.Path** for filesystem work.
- **No mutable default arguments**; no bare `except`; no `from x import *`.
- **Comprehensions** for simple transforms; generators for large walks.
- **Explicit over implicit** — no import-time side effects that block startup.
- Format/lint: ruff (line length 88, py312); types: pyright standard.

---

## 14. Decision index (ADRs)

| ADR | Decision |
|---|---|
| [0001](./adr/0001-index-on-save-not-git-state.md) | Index on save, not git-committed state |
| [0002](./adr/0002-direct-chunk-embedding.md) | Embed code chunks directly (no LLM summaries) |
| [0003](./adr/0003-all-in-one-mvp-topology.md) | All-in-one process for MVP |
| [0004](./adr/0004-single-writer-sqlite-wal.md) | Single-writer SQLite + WAL |
| [0005](./adr/0005-python-mcp-stack.md) | Python 3.12 + official MCP SDK stack |
| [0006](./adr/0006-harness-safe-mcp-surface.md) | Harness-safe minimal MCP tool surface |
| [0007](./adr/0007-single-workspace-no-multi-repo.md) | Single workspace, no multi-repo registry |
| [0008](./adr/0008-host-spawned-cwd-per-repo-collections.md) | Host-spawned process, cwd workspace, per-repo collections |
| [0009](./adr/0009-setup-wizard-managed-services-config.md) | Setup wizard, layered YAML config, managed local services |

---

## 15. Handoff checklist for implementers

- [ ] Phase 1 harness gate first (`mimo mcp list`)
- [ ] No `outputSchema` / `capabilities.tasks` / `execution.taskSupport`
- [ ] No `OPENAI_API_KEY`; no unused config blocks; secrets only via `embedding.api_key`/`EMBED_API_KEY`
- [ ] Tests set `SIMPLE_CI_CONFIG=none` so a developer's global config cannot change defaults
- [ ] Config discovery: `SIMPLE_CI_CONFIG` → local `.simple-ci/config.yaml` → global → defaults; env overrides
- [ ] Managed containers are fail-soft: never block the MCP server forever, always report in `get_status.services`
- [ ] New harness support goes in `src/simple_code_indexer/harnesses/` (bad plugins skipped, never fatal)
- [ ] `tests/service_probe.py` + `tests/mcp_probe.py` before debugging
- [ ] Watcher never blocks; debounce + queue + sweep
- [ ] Single writer; hash short-circuit on no-op saves
- [ ] Acceptance test through the harness (not only unit tests)
- [ ] `ruff` → `pyright` → `pytest` before calling a phase done
- [ ] Update README runbook when commands stabilize

---

## 16. Open questions intentionally deferred

These are **not** blockers for implementation start:

1. Hybrid fusion ranking for `semantic=true` (v1 may return semantic-only).
2. Topology B (sidecar) scheduling — post-acceptance.
3. Additional language grammars beyond the v1 allowlist.
4. Fuzzy/trigram symbol search (upstream optional path).
