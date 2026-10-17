# Technical Design — simple-code-indexer

**Status:** Ready for implementation handoff  
**Date:** 2026-10-17  
**Project:** `D:\Projects\Python\simple-code-indexer`  
**Domain terms:** [`GLOSSARY.md`](../GLOSSARY.md) · **Decisions:** [`docs/adr/`](./adr/)

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

1. Must run in a Docker container via `docker-compose.yml`.
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
- README runbook (commands, config reload, diagnosis).
- `ruff check` → `pyright` → `pytest` clean.

---

## 3. Environment facts (verified — do not re-derive)

| Fact | Value |
|---|---|
| Host | Windows + Docker Desktop; bind mounts propagate **inotify** into containers |
| Embeddings | llama.cpp (CUDA) `0.0.0.0:8080`; accepts short name and full GGUF path as `model`; 2560-dim; also exposes `/v1/chat/completions` (do **not** depend on it for bulk work) |
| Qdrant | host `0.0.0.0:6333`, no auth; collection `code_index_2560` exists (dim 2560, cosine, empty — reuse) |
| Container → host | `http://host.docker.internal:<port>` |
| MiMoCode | v0.1.15; local MCP = `{"type":"local","command":[…],"timeout":<ms>,"sampling":"deny\|ask\|allow"}` in `.mimocode/mimocode.json` |
| Default tools timeout | **5000 ms** — set `"timeout": 60000` on the server entry |
| Harness reload | config read at session start; restart harness after changes |

---

## 4. Architecture overview

### 4.1 Topology (MVP)

**All-in-one** ([ADR-0003](./adr/0003-all-in-one-mvp-topology.md)): one long-lived container; harness attaches via `docker exec -i`.

```
MiMoCode harness
    │  stdio JSON-RPC (newline-delimited)
    ▼
docker exec -i code-index python -m simple_code_indexer.server
    │
    ├─ MCP stdio loop: initialize / tools/list / tools/call
    │     search_code | symbol_lookup | get_status [| reindex]
    │
    ├─ Index writer (same process, worker thread)
    │     debounce queue → index_one_file → SQLite + Qdrant
    │
    └─ Watcher (watchdog Observer, background thread)
          /workspace recursive → events → queue
```

**Sidecar (post-MVP, config change only):** compose runs `watcher+indexer` as PID 1; MCP is a read-only query process. Queue/worker interface is identical.

### 4.2 Data flow — index on save

```
host file save
  → Docker Desktop bind mount inotify in container
  → watchdog Observer (recursive, /workspace)     [start on background thread]
  → per-path DEBOUNCE (300–500 ms)                [collapse temp+rename bursts]
  → bounded work queue (never index in the callback)
  → index_one_file(path):
       skip if ext not in allowlist or path matches ignore rules
       skip if sha256(content) == stored hash
       parse symbols (tree-sitter) → UPSERT symbols
       chunk → DELETE chunks/chunks_fts by file → INSERT
       UPDATE files(path, hash, mtime, language, size, indexed_at)
       embed chunk texts (batched) → Qdrant upsert by stable point id
         point id = uuid5(NAMESPACE, workspace|path|chunk_index)
  on deleted/moved → DELETE rows by path + Qdrant delete-by-filter(path)
```

### 4.3 Reliability backstops

1. **Reconciliation sweep** every `SWEEP_SECONDS` (default 45): walk workspace (respect ignores), compare `mtime+size`, then `sha256` on candidates; run `index_one_file` for mismatches.
2. **Startup reconcile:** same pass once at process start.
3. Optional `watchdog.polling.PollingObserverV2` behind env flag (not needed on Docker Desktop).

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
3. `get_status()`: counts, `watcher_alive`, `last_sweep`, `qdrant_ok`, `embed_ok`.

---

## 5. Domain model

See [`GLOSSARY.md`](../GLOSSARY.md) for canonical terms. Core entities:

| Entity | Identity | Key attributes |
|---|---|---|
| Workspace | single root path | mount `/workspace`, index under `.index/` |
| File record | `path` (unique) | language, size, sha256, mtime, indexed_at |
| Symbol | (`file_id`, name, line) | kind, line_end, signature |
| Chunk | (`file_id`, chunk_index) | start_line, end_line, content |
| Point ID | `uuid5(ns, path\|chunk_index)` | stable across re-index |

Relationships: File 1—* Symbol, File 1—* Chunk. Qdrant points reference chunk identity via payload `{path, chunk_index}`.

---

## 6. Data model

### 6.1 SQLite (`/workspace/.index/index.db`)

WAL mode, `busy_timeout=5000`, single writer.

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
```

**Update protocol for one file:** in a single writer transaction — delete symbols/chunks (and FTS rows via `chunks_fts` delete trigger or explicit `INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', …)`), insert fresh rows, upsert `files`. Keep triggers or an explicit FTS sync so `chunks` and `chunks_fts` never diverge.

### 6.2 Qdrant

- URL: `QDRANT_URL` (default `http://host.docker.internal:6333` in Docker, `http://localhost:6333` on host).
- Collection: `code_index_2560` (reuse existing), vector dim **2560**, distance **Cosine**.
- Point ID: `uuid5(NS, f"{path}:{chunk_index}")`.
- Payload: `{"path": str, "chunk_index": int}`.
- Delete: filter `path == deleted_path`.
- Upsert is idempotent (same ID replaces).

### 6.3 Filesystem layout

```
/workspace/                  # bind-mounted project (user code)
  .index/
    index.db                 # SQLite WAL (gitignore this)
  …user files…
/app/                        # in image
  simple_code_indexer/…
```

Never write logs into the workspace root (gitignore `.index/`; logs go to stderr or a gitignored path).

---

## 7. Component design

Package: `src/simple_code_indexer/` (import name `simple_code_indexer`).  
Python conventions follow [`python-patterns`](../../AGENTS.md): type hints on public functions, `pathlib.Path`, dataclasses/NamedTuple for records, EAFP at boundaries, context managers for DB/files, no mutable default args, stdlib first.

### 7.1 Modules

```
src/simple_code_indexer/
  __init__.py          # version, main() entry
  config.py            # Settings from env (frozen dataclass)
  models.py            # FileRecord, Symbol, Chunk, SearchHit (dataclasses)
  db.py                # schema ensure, connection helpers, FTS queries
  parse.py             # tree-sitter symbol extraction + chunking
  embed.py             # OpenAI-compatible embeddings client
  qdrant_store.py      # ensure_collection, upsert, delete_by_path, search
  indexer.py           # index_one_file, sweep, startup reconcile
  watcher.py           # Observer + debounce queue → indexer
  server.py            # MCP stdio: initialize, tools/list, tools/call
```

### 7.2 `config.py`

```python
@dataclass(frozen=True, slots=True)
class Settings:
    workspace_root: Path
    index_db_path: Path
    qdrant_url: str
    qdrant_collection: str
    embed_base_url: str          # e.g. http://host.docker.internal:8080
    embed_model: str             # Qwen3-Embedding-4B-Q6_K
    embed_dim: int               # 2560
    embed_timeout_s: float       # 15
    sweep_seconds: float         # 45
    debounce_ms: int             # 400
    allowed_exts: frozenset[str]
    ignore_dirs: frozenset[str]
```

Load via `os.environ` (EAFP: try/except KeyError → default). **Never** hardcode secrets. **Never** set `OPENAI_API_KEY`. If a feature is unused, omit it from config entirely (no empty blocks that enable fallbacks).

Env names (minimum set):

| Variable | Default |
|---|---|
| `WORKSPACE_ROOT` | `/workspace` |
| `INDEX_DB` | `$WORKSPACE_ROOT/.index/index.db` |
| `QDRANT_URL` | `http://host.docker.internal:6333` |
| `QDRANT_COLLECTION` | `code_index_2560` |
| `EMBED_BASE_URL` | `http://host.docker.internal:8080` |
| `EMBED_MODEL` | `Qwen3-Embedding-4B-Q6_K` |
| `EMBED_DIM` | `2560` |
| `SWEEP_SECONDS` | `45` |
| `DEBOUNCE_MS` | `400` |

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
- `chunk_source(source, max_lines=80, max_chars=2000) -> list[Chunk]` — line-aligned windows; fallback for unknown languages: regex-ish symbol scan (def/class/function) + same chunker.

v1 allowlist minimum: `.cpp`, `.cc`, `.cxx`, `.h`, `.hpp`, `.py`, `.ts`, `.js`. Generic chunking for anything else in the allowlist.

**Lazy-load parsers** (do not import language packs at module import time) so startup stays <3 s.

### 7.5 `embed.py`

- `embed_texts(texts: Sequence[str]) -> list[list[float]]` — one POST `{base}/v1/embeddings` with `{"model": …, "input": texts}`.
- Explicit `timeout=15`, **retries=0..2**, no default OpenAI client behavior toward the public internet.
- Measure dim on first response; assert equals `Settings.embed_dim` (2560).
- `embed_query(text) -> list[float]` = `embed_texts([text])[0]`.
- Fail soft on index path: log, mark `embedding_state.status='error'`, continue lexical indexing.

### 7.6 `qdrant_store.py`

- `ensure_collection(client, name, dim, distance="Cosine")`.
- `upsert_chunks(path, chunk_vectors)` using stable point IDs.
- `delete_by_path(path)`.
- `search(vector, limit) -> list[point]`.

### 7.7 `indexer.py`

- `index_one_file(path: Path) -> IndexOutcome` — the unit of work (hash short-circuit).
- `sweep() -> SweepStats` — mtime+size then hash candidates.
- `startup_reconcile()`.
- Bounded `queue.Queue` consumer; items are paths or tombstones.

`IndexOutcome` (NamedTuple): `path`, `status` (`indexed|skipped_unchanged|skipped_filtered|error`), `duration_ms`.

### 7.8 `watcher.py`

- `Observer.schedule(handler, root, recursive=True)`.
- `observer.start()` **on a daemon thread** (recursive inotify over bind mounts blocks).
- Debounce per path 300–500 ms; on fire enqueue; never index in the callback.
- Handle `on_created` / `on_modified` / `on_moved` / `on_deleted`.
- Ignore: `.git`, `.index`, `__pycache__`, `.venv`, `node_modules`, temp editor names (`*~`, `*.tmp`, `.#*`).

### 7.9 `server.py` (MCP)

Official `mcp` SDK:

- `Server("simple-code-indexer")`
- `@server.list_tools` → **exactly** the tools below, short descriptions, **no `outputSchema`**
- `@server.call_tool` → dispatch
- `mcp.server.stdio.stdio_server()`
- Initialize result: **no** `capabilities.tasks`
- Per-tool: **no** `execution.taskSupport`
- Startup: open DB, ensure schema, `startup_reconcile` on worker thread, start watcher on daemon thread, **then** serve (target ready <3 s)

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

When `semantic=true`, `source` is `"semantic"` (or `"hybrid"` if fused later).

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
  "watcher_alive": true,
  "last_sweep": "2026-10-17T20:01:02Z",
  "qdrant_ok": true,
  "embed_ok": true,
  "workspace": "/workspace",
  "index_db": "/workspace/.index/index.db"
}
```

### 8.4 `reindex` (optional, phase 5+)

**Output:** `{"queued": N, "status": "started"}` — enqueue full sweep, return immediately. Keep the tool absent until the first three are stable.

---

## 9. Deployment

### 9.1 `Dockerfile`

- Base: `python:3.12-slim`
- Install `uv`; `uv sync --locked --no-install-project` pattern; copy package; no custom compile steps.
- `WORKDIR /app`
- Default command: keep-alive for topology A (`tail -f /dev/null`) **or** `python -m simple_code_indexer.server` if you prefer the process to be PID 1 — either is fine as long as MCP attach and watcher lifetime match §4.1.
- Build context **outside** the watched workspace (avoid watcher startup blow-up).

### 9.2 `docker-compose.yml`

```yaml
services:
  code-index:
    build: .
    container_name: code-index
    working_dir: /workspace
    volumes:
      - .:/workspace
    environment:
      WORKSPACE_ROOT: /workspace
      QDRANT_URL: http://host.docker.internal:6333
      EMBED_BASE_URL: http://host.docker.internal:8080
      EMBED_MODEL: Qwen3-Embedding-4B-Q6_K
      EMBED_DIM: "2560"
      SWEEP_SECONDS: "45"
      # no OPENAI_API_KEY — ever
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
    command: ["tail", "-f", "/dev/null"]
```

Own **only** this service. User's Qdrant and llama.cpp live in their own compose projects.

### 9.3 `.mimocode/mimocode.json`

```json
{
  "$schema": "https://mimo.xiaomi.com/mimocode/config.json",
  "mcp": {
    "code-index": {
      "type": "local",
      "command": ["docker", "exec", "-i", "code-index", "python", "-m", "simple_code_indexer.server"],
      "enabled": true,
      "timeout": 60000,
      "sampling": "deny"
    }
  }
}
```

Restart the harness after any change to this file.

### 9.4 From-container probes (run first, always)

```bash
docker exec code-index python -c "import urllib.request,json; \
  req=urllib.request.Request('http://host.docker.internal:8080/v1/embeddings', \
  data=json.dumps({'model':'Qwen3-Embedding-4B-Q6_K','input':'probe'}).encode(), \
  headers={'Content-Type':'application/json'}); \
  print(len(json.load(urllib.request.urlopen(req,timeout=15))['data'][0]['embedding']))"

docker exec code-index python -c "import urllib.request,json; \
  print(json.load(urllib.request.urlopen('http://host.docker.internal:6333/collections'))['status'])"
```

Expect `2560` and an OK collections payload. Debug nothing else until both pass.

---

## 10. Error handling & operational pitfalls

| Pitfall | Rule |
|---|---|
| Oversized tools/list | No `outputSchema`; short descriptions; 2–3 tools at first |
| 5 s tool timeout | `timeout: 60000` + <3 s startup (lazy parsers, watcher on thread) |
| `localhost` in container | Always `host.docker.internal` |
| Dummy `OPENAI_API_KEY` | Never set it — enables real api.openai.com retries |
| Config blocks that enable features | If unused, omit entirely (no empty `summarization:` key) |
| PowerShell + `docker exec` quoting | Write script files; `docker exec … python /workspace/foo.py` |
| Wrong CWD for compose | Compose runs against CWD file — always start from project root |
| Docker Desktop idle restarts | `restart: unless-stopped`; re-check `docker ps` at session start |
| Observer.start() blocking | Start on daemon thread; keep watched tree small |
| Dropped inotify events | Sweep + startup reconcile always on |
| Multi-writer races | One writer; design out, don't lock harder |
| Slow network in write path | Local-first; embeddings short timeout + fail soft |
| Logs in workspace | stderr or gitignored path only |

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

1. `docker compose up -d --build`
2. From-container probes (§9.4)
3. `mimo mcp list` → `✓ connected`
4. Harness session reload
5. Create `widget_checksum.cpp` with unique symbol `calculateWidgetChecksum`
6. Poll `search_code` / `symbol_lookup` until found (target <5 s)
7. `search_code(..., semantic=true)` returns a hit (vectors may lag a few seconds)
8. `get_status` healthy; `docker compose down && up -d` resilience check

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
| **0 Scaffold** | package layout, `pyproject` deps, Dockerfile, compose | `uv run pytest` smoke green; image builds |
| **1 Harness gate** | MCP server with **only** `get_status`, mimocode.json | `mimo mcp list` `✓ connected`; stdio probe works |
| **2 Indexer** | SQLite schema + FTS, `.cpp` parse, `search_code`/`symbol_lookup` over startup-built index | unit tests pass; probe finds fixture symbols |
| **3 Watcher** | observer + debounce + per-file upsert; sweep + startup reconcile | create `test.cpp` → found in <5 s without manual reindex |
| **4 Embeddings + Qdrant** | embed-on-index, embed-on-query, `semantic=true` | from-container probes + semantic hit on acceptance file |
| **5 Acceptance** | full test through harness; resilience check | DoD §2.1 |
| **6 Optional** | topology B sidecar | always-on watch with harness closed |

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

---

## 15. Handoff checklist for implementers

- [ ] Phase 1 harness gate first (`mimo mcp list`)
- [ ] No `outputSchema` / `capabilities.tasks` / `execution.taskSupport`
- [ ] No `OPENAI_API_KEY`; no unused config blocks
- [ ] Probes from **inside** the container before debugging
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
