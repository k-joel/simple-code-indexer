# Handoff — Building a Minimal "Code Index MCP" From Scratch

**Purpose:** everything a fresh LLM session needs to build a *new, smaller* project
that satisfies the original requirements, informed by the full investigation of
upstream Code-Index-MCP (report: [`code-index-mcp-report.md`](code-index-mcp-report.md)).

**Date:** 2026-10-17 · **Source investigation:** Code-Index-MCP v1.4.1 candidate,
deployment verified working in `D:\Projects\Docker\code-index-mcp`.

---

## 1. The original requirements (verbatim contract)

1. Must run in a Docker container via `docker-compose.yml`.
2. Must use an **externally configured embedding model**:
   - Model: `Qwen3-Embedding-4B-Q6_K`, dim **2560**
   - URL: `http://localhost:8080/v1/embeddings` (llama.cpp server, OpenAI-compatible)
3. Must use **Qdrant** to store vectors: `http://localhost:6333`.
4. Must have a **file watcher that indexes a file whenever it is saved**.
5. MCP server must be configured in `.mimocode/mimocode.json` (MiMoCode harness);
   after config changes the harness session must be closed/reopened to reload.
6. Acceptance test: create a test `.cpp` file, wait for it to index, retrieve it
   successfully.

Nice-to-haves proven in the reference deployment: symbol lookup with line numbers,
semantic (vector) search over Qdrant, `get_status`.

---

## 2. Environment facts (verified, do not re-derive)

| Fact | Value / proof |
|---|---|
| Host | Windows + Docker Desktop; bind mounts propagate **inotify events** into containers (verified empirically — see report §5) |
| Embedding server | llama.cpp (CUDA) publishing `0.0.0.0:8080`; accepts both the short name `Qwen3-Embedding-4B-Q6_K` and the full GGUF path as `model`; returns 2560-dim vectors; **also exposes `/v1/chat/completions`** (works but slow/unreliable for bulk jobs — see pitfalls) |
| Qdrant | host container publishing `0.0.0.0:6333`, no auth |
| Container → host | both services reachable as `http://host.docker.internal:<port>` (Docker Desktop resolves it; add `extra_hosts: ["host.docker.internal:host-gateway"]` for portability to Linux) |
| Probe from container | `docker exec <c> python -c "urllib…POST /v1/embeddings"` → 2560 dims ✓; `GET /collections` ✓ |
| MiMoCode | v0.1.15. Local MCP = `{"type":"local","command":[…],"timeout":<ms>,"sampling":"deny|ask|allow"}` in `.mimocode/mimocode.json` (project config). Docs: https://mimo.xiaomi.com/mimocode/mcp-servers |
| MiMoCode default tools timeout | **5000 ms** (`timeout` field overrides per server) |
| Harness reload | `.mimocode/mimocode.json` is read at session start; changes need harness restart |

Reference deployment files worth mining (all in `D:\Projects\Docker\code-index-mcp`):
`docker-compose.yml` (env wiring, git fixes), `code-index-mcp.profiles.yaml`
(profile schema), `mcp-compat-proxy.py` (what the harness rejects), `.mcp-probe.py`
(stdio test-client pattern), `AGENTS.md` (runbook), `code-index-mcp-report.md`
(full analysis).

---

## 3. What upstream does, and what you should keep vs cut

Read report §4 (architecture) for how Code-Index-MCP works. Summary of its machinery:
STDIO MCP server → stateless bootstrap (registry, store cache, resolver, dispatcher,
git index manager) → SQLite+FTS5 staged "generation" rebuilds with optimistic
publish → fail-closed per-repo readiness contract (git commit-gated) → 48 tree-sitter
plugins → summary-first semantic pipeline into namespaced Qdrant collections →
multi-repo watcher (watchdog + RefPoller + GitMonitor + hash sweeper) reconciling
**committed** git state.

### 3.1 Keep (core value)

- **MCP STDIO server** with a tiny tool surface: `search_code`, `symbol_lookup`,
  `get_status`. (Optionally `reindex` for manual rebuild.)
- **SQLite + FTS5** index (stdlib Python sqlite3 ships with FTS5 — upstream logs
  "FTS5 support confirmed" on `python:3.12-slim`).
- **Per-file records**: path, language, size, content-hash, mtime + `symbols` table
  (name, kind, line, signature) + FTS table over chunks/lines.
- **Embeddings → Qdrant** for semantic search; **embed the query** with the same
  endpoint and search Qdrant, fuse or expose `semantic=true`.
- **File watcher → index on save** (§6 of this handoff — the headline difference
  from upstream).
- **docker-compose** service with the workspace bind-mounted; MCP attached via
  `docker exec -i …` (sidecar pattern, report §7.1).
- **`mimo mcp list` as your acceptance gate for harness integration** (§5).

### 3.2 Cut entirely (and why)

| Upstream feature | Why it's cut for the subset |
|---|---|
| Git-based readiness / commit-gating / staleness / provenance | The single biggest source of pain (report §6, §7.2, §7.5-3): every commit made the index "stale", non-git dirs were `missing_provenance`, rebuilds raced. **Index on save, no git.** |
| Staged generation rebuilds + optimistic publish + quarantine | Designed for crash-safe git-synced rebuilds; caused `expected_generation` race failures with >1 session. A single-writer SQLite file with WAL is enough. |
| Multi-repo registry, `RepoResolver`, path sandbox, worktree identity rules | One workspace. (`MCP_ALLOWED_ROOTS`-style sandbox only if you later serve multiple roots.) |
| Summary-first semantic pipeline (LLM chunk summaries before vectors) | Requires an LLM summarizer; without one, every rebuild fails (`_semantic_stage_error`, report §7.5-3). **Embed code chunks directly** — the embedding model doesn't need summaries. |
| 48 plugins / plugin sandbox / memory-aware manager / factory | Start with the languages you care about (`.cpp` for the test) via `tree-sitter-language-pack`; generic line/chunk fallback for the rest. |
| FastAPI gateway, JWT auth, Prometheus, Redis cache, rerankers, MCP handshake/sampling/tasks | Admin/enterprise surface; irrelevant to a local MCP. |
| GitHub Artifacts sync, attestations, BAML/Cerebras paths, MCP sampling summarization | Extra external dependencies and failure modes. |
| `outputSchema` on tools, `capabilities.tasks`, `execution.taskSupport` | **The harness rejects them** (§5.1). |
| File watcher treating events as "hints" over committed state | Directly contradicts requirement 4. Replace with immediate per-file reindex (§6). |

Net: upstream is ~5/5 complexity for a multi-repo, git-aware, artifact-syncing
product. Your subset is **~1/5**: one workspace, one SQLite file, one Qdrant
namespace, one watcher, ~500–1500 lines.

---

## 4. Issues / gotchas / pitfalls (each cost hours here — don't repeat)

### 4.1 Harness integration (the #1 risk — test this FIRST)

MiMoCode's client failed `tools/list` ("Failed to get tools") for three reasons
(trace evidence in report §7.3):

1. **Oversized single-line payload.** tools/list was ~30 KB on one newline-delimited
   line (8 tools × huge `oneOf` `outputSchema`s) → exceeded the client's line limit.
   **Fix: don't emit `outputSchema` at all** (optional in the MCP spec) and keep
   descriptions short.
2. **`capabilities.tasks`** in the initialize result was rejected. Don't advertise it.
3. **Per-tool `execution: {"taskSupport": …}`** was rejected. Don't emit it.

Additional timing facts:
- Server readiness must beat the client's tools fetch: default **5 s**. Set
  `"timeout": 60000` in `mimocode.json`, *and* still aim for <3 s startup (lazy-load
  parsers, start the watcher's recursive registration on a background thread —
  upstream's `observer.start()` blocked ~3–5 s on the bind mount, report §7.5-2).
- `mimo mcp list` is your quickest oracle: it spawns the command and reports
  `✓ connected` or `✗ Failed to get tools`.
- Keep the **whole tool surface minimal at first** (2–3 tools) and grow.

### 4.2 Process/container pitfalls

- **`docker exec` + PowerShell quoting is hostile.** Inline `python -c "…"` with
  nested quotes/redirects breaks repeatedly. Write script files into the workspace
  and `docker exec … python /workspace/foo.py`.
- **`docker compose up` runs against the compose file in the CWD.** Running it in
  the wrong directory silently operates on a different project (there is an upstream
  `docker-compose.yml` in the clone!).
- **Docker Desktop restarts kill containers** (we found everything `Exited (137)`
  after ~11 h idle). Use `restart: unless-stopped` and re-verify `docker ps` at
  session start; your compose should own *your* service only — the user's Qdrant and
  llama.cpp live in their own compose projects (`D:\Projects\Docker\qdrant\`,
  `...\llamacpp-Qwen3-Embedding-4B-Q6_K\`).
- **Stderr volume:** the server logs a lot to stderr. If you write a stdio proxy or
  wrapper, forward stderr through and never block on it; log files must live in a
  gitignored path (upstream kept appending `mcp_server.log` into the workspace root).

### 4.3 Network/config pitfalls (external services)

- **Never set a placeholder `OPENAI_API_KEY`.** The OpenAI SDK/summarizer treated
  the presence of the key as "direct API configured" and issued real
  `api.openai.com` calls that retried until the 30 s tool budget expired
  (report §7.4). For embeddings, pass an explicit `base_url` and no key (or the
  provider's own dummy like `vllm-local` *inside the request*, not via env).
- **Config "blocks" can silently enable features.** Upstream emitted a fallback
  enrichment `base_url` (`http://ai:8002/v1`) merely because a `summarization:`
  key existed (even `enabled: false`) → connection retries against a dead host
  (report §7.4-2). Rule: **if you don't use a feature, don't mention it in config.**
- **`localhost` inside a container is the container.** Always
  `host.docker.internal` for host-published ports; verify both endpoints *from
  inside* the container before debugging anything else.
- Batch embedding worked fine: 20 texts in 1.6 s (2560-dim). The llama.cpp **chat**
  endpoint, however, hung/timed out on bulk summarization — don't build anything
  that depends on it.

### 4.4 Windows-host specifics (if you keep git at all)

You're dropping git-based readiness, so most of this disappears — but if you keep
any git usage inside the container:

- `fatal: detected dubious ownership` → set
  `GIT_CONFIG_KEY_0=safe.directory`, `GIT_CONFIG_VALUE_0=*`.
- Container git saw CRLF differences vs host git →
  `GIT_CONFIG_KEY_1=core.autocrlf`, `GIT_CONFIG_VALUE_1=input`
  (report §7.2). Without these, "clean tree" checks disagree between host/container.

### 4.5 Watcher specifics (Docker Desktop)

- inotify events **do** propagate host→container through the bind mount (verified:
  a committed file was picked up by the sync path; report §5.2/§8).
- Registering recursive watches over a large tree **blocks** `observer.start()`
  (watchdog waits for every `inotify_add_watch` through the slow 9p/virtiofs layer).
  Keep the watched tree small and/or start the observer on a background thread
  (upstream patch, report §7.5-2). The upstream clone had to be moved **out** of the
  watched workspace for this reason (report §7.6).
- Events can still drop → always keep a **hash-based reconciliation sweep** as a
  backstop (upstream's `WatcherSweeper`, `MCP_WATCHER_SWEEP_MINUTES`; report §5.1).

### 4.6 Multi-process data races (design out)

- Two sessions doing full rebuilds raced `publish_generation` → both failed
  (`expected_generation` mismatch). For the subset: **one writer process owns the
  index** (see §6.3); readers use SQLite WAL.
- The upstream reindex tool has a **~30 s internal timeout** — anything slow
  (network retries, LLM calls) inside rebuilds kills them. Keep the write path
  local-first; do embeddings with explicit short timeouts and retry policy.

---

## 5. MiMoCode MCP integration (do this in phase 1)

`.mimocode/mimocode.json`:

```json
{
  "$schema": "https://mimo.xiaomi.com/mimocode/config.json",
  "mcp": {
    "code-index": {
      "type": "local",
      "command": ["docker", "exec", "-i", "<your-container>", "python", "/app/server.py"],
      "enabled": true,
      "timeout": 60000,
      "sampling": "deny"
    }
  }
}
```

Acceptance loop (from this session):

1. `mimo mcp list` → must show `✓ connected`.
2. Stdio probe (pattern of `.mcp-probe.py`): `initialize` → `tools/list` →
   `tools/call get_status` inside the container.
3. Only after 1–2 pass, wire real tools and reload the harness (session restart) so
   the tools appear; then run the acceptance test through the harness if desired.

If `mimo mcp list` says `Failed to get tools`, instrument: tee stdin/stdout of your
server to a file (we used a temp proxy) and inspect the exact exchange — that is how
the three rejections in §4.1 were found.

---

## 6. File watcher: achieving **index on save** (requirement 4)

Upstream deliberately does NOT do this (events are hints; committed state is
reconciled — report §5). Your project should invert that.

### 6.1 Event → index pipeline

```
host file save
  → (Docker Desktop bind mount) inotify in container
  → watchdog Observer (recursive, /workspace)      [start on background thread]
  → per-path DEBOUNCE (300–500 ms; editors write temp+rename bursts)
  → bounded work queue (worker thread/asyncio task — never index in the callback)
  → index_one_file(path):
       if ext not in allowlist or path matches ignore rules → skip
       sha256(content) == stored hash? → skip (no-op saves)
       parse symbols (tree-sitter) → UPSERT symbols rows
       chunk → UPSERT/REPLACE FTS rows  (DELETE by path first)
       UPDATE files(path, hash, mtime, language, indexed_at)
       embed chunk texts (batched) → Qdrant upsert by stable point id
       (point id = uuid5(namespace, repo|path|chunk_index) → idempotent upserts)
  on deleted/moved → DELETE rows by path + Qdrant delete by filter(path)
```

Design rules learned here:
- **Never block the observer callback** — upstream's debounce+queue pattern
  (`file_watcher.py`, report §5.1) is worth copying.
- **Single writer**: the watcher worker owns writes; the MCP process either *is*
  that process (all-in-one) or only reads (WAL mode, `busy_timeout`). See §6.3.
- **Fail soft**: log and continue; one bad file must not kill the loop.

### 6.2 Reliability backstops (events can drop)

1. **Reconciliation sweep**: every `SWEEP_SECONDS` (start at 30–60), walk the
   workspace (respecting ignores), compare `mtime+size`, then `sha256` on candidates;
   run `index_one_file` for mismatches. Cheap on small workspaces; this is upstream's
   sweeper minus the git.
2. **Startup reconcile**: same pass once at process start — covers files changed
   while the harness/container was down.
3. Optional: `watchdog.polling.PollingObserverV2` behind an env flag if a platform's
   events prove unreliable (we never needed it on Docker Desktop).

### 6.3 Two viable topologies

- **A — All-in-one (recommended MVP):** one container process = MCP stdio server +
  watcher thread. Simple, single writer, matches how the harness runs it. Downside:
  watching only happens while a session is attached (same as upstream).
- **B — Sidecar (recommended for "even when the harness is closed"):** compose runs
  `watcher+indexer` as PID 1 (always on); MCP stdio is a read-only query process
  `docker exec`'d per session. SQLite WAL + Qdrant make this safe. Two services in
  the same compose file, shared volume for the index + the workspace mount.

The requirement ("index whenever saved") reads as *eventual consistency after save*;
A gives it whenever the harness is open, B gives it always. Pick A first, keep the
queue/worker interface so B is a config change.

### 6.4 What "indexed" must mean for the acceptance test

Minimum: the file's path+contents are searchable via `search_code` and its symbols
via `symbol_lookup`. Semantic vectors can lag by a few seconds (enqueue after
lexical write); the acceptance test doesn't require them, but requirement 2+3 mean
the embed path must exist and be exercised — add `semantic: true` to your test.

---

## 7. Suggested architecture for the new project

```
compose:
  code-index:                # build from your Dockerfile (python:3.12-slim + uv)
    mounts: .:/workspace
    env: workspace path, qdrant url, embed base url/model/dim, sweep seconds
    command: keep-alive (tail -f /dev/null)      # MCP attaches via docker exec
    restart: unless-stopped
    extra_hosts: host.docker.internal:host-gateway

/app (in image):
  server.py        # MCP stdio: initialize, tools/list (SMALL), tools/call
  indexer.py       # SQLite schema, parse/chunk/embed/upsert, sweep, hash store
  watcher.py       # watchdog observer + debounce queue → indexer
  embed.py         # one OpenAI-compatible embeddings client (explicit timeouts)
  qdrant_store.py  # collection ensure (dim 2560, cosine), upsert/delete/search
  tree-sitter via tree-sitter-language-pack (precompiled grammars, no build step)

data:
  /workspace/.index/index.db        # SQLite WAL: files, symbols, chunks, FTS
  Qdrant collection: e.g. "code_index_2560" (already exists on the host, dim 2560
                    cosine, currently empty — reuse it)
```

Suggested SQLite schema (roughly upstream's, minus generations/git columns):

```sql
files(id PK, path UNIQUE, language, size, sha256, mtime, indexed_at);
symbols(id PK, file_id FK, name, kind, line, line_end, signature);
chunks(id PK, file_id FK, chunk_index, start_line, end_line, content);
chunks_fts  USING fts5(content, content='chunks', content_rowid='id');
-- optional: embedding_state(file_id/chunk_id, qdrant_point_id, status)
```

MCP tools (keep output schemas **absent**, per §4.1):

- `search_code(query, semantic=false, limit)` → `[{file, line, snippet}]`
- `symbol_lookup(symbol)` → `{symbol, kind, defined_in, line, signature}`
- `get_status()` → `{files_indexed, last_sweep, watcher_alive, qdrant_ok, embed_ok}`

---

## 8. Tech stack recommendation

### Verdict: **stay on Python for v1** (unless you already prefer Go/TS)

The four requirements are I/O-bound glue (watcher + HTTP + SQLite), not CPU-bound.
Python is where every needed library is mature, the official MCP SDK is first-class,
and this exact environment has been proven end-to-end — including every integration
pitfall (§4), which is now documented. Rewriting in a new language reintroduces all
of §4 as fresh discoveries.

| Layer | Choice | Notes |
|---|---|---|
| Language | **Python 3.12** | Same as upstream; `python:3.12-slim` image proven |
| MCP server | **`mcp` (official SDK)** | Upstream pins 1.27.0, negotiates protocol `2025-11-25`; `Server` + `@server.list_tools/call_tool` + `mcp.server.stdio.stdio_server`. Remember §4.1 output rules |
| Watcher | **`watchdog`** | Best cross-platform inotify; `Observer.schedule(..., recursive=True)`; start on a thread; debounce yourself (small queue is ~30 lines) |
| DB | **stdlib `sqlite3` + FTS5** | No ORM needed. WAL + `busy_timeout=5000`. FTS5 confirmed on slim image |
| Vectors | **`qdrant-client`** | `QdrantClient(url=QDRANT_URL)`; `ensure_collection(dim=2560, cosine)`; upsert/delete-by-filter/search |
| Embeddings | **`httpx` (or `openai` with explicit timeout/retries=0..2)** | One POST `/v1/embeddings`; set `timeout=15` — *do not* let any client default-retry toward the public internet (§4.3) |
| Parsing | **`tree-sitter` + `tree-sitter-language-pack`** | One dependency, 167 precompiled grammars (`get_parser("cpp")`); upstream's Dockerfile lesson: don't reference the old `tree_sitter_languages` package (report §7.5-1). Fallback: line-based chunking + regex symbol scan is acceptable for v1 |
| Env/config | **plain `os.environ`** (or `pydantic-settings` if you like) | Fewer knobs than upstream (report §7.1 lists the entire needed set) |
| Packaging | **`uv`** (`pyproject.toml` + `uv.lock`) | Reproducible image builds; `uv sync --locked --no-install-project` pattern from `Dockerfile.minimal` works well |
| Tests | stdlib `unittest`/`pytest` + the stdio probe script | The probe (`.mcp-probe.py` pattern) doubles as an e2e test |

### When to pick something else

- **TypeScript/Node**: reasonable if the rest of your stack is JS —
  `@modelcontextprotocol/sdk`, `chokidar`, `better-sqlite3` (FTS5 built in),
  `qdrant-client`, `openai`. Weakest point: tree-sitter (native `node-tree-sitter`
  grammar installs per language, or slower `web-tree-sitter` WASM).
- **Go**: best if you want a tiny always-on watcher daemon (topology B) and a single
  static binary — `github.com/modelcontextprotocol/go-sdk`, `fsnotify`,
  `modernc.org/sqlite` (FTS5 build-tag), official `qdrant-client-go`, tree-sitter Go
  bindings are easy per-language. Steeper per-feature speed than Python for MVP.
- **Rust**: no — highest correctness/perf ceiling, slowest path to satisfying four
  glue-y requirements.

Language-agnostic rules that matter more than the language: **small tools/list
(§4.1), direct index-on-save (§6), no LLM in the write path (§4.3), single index
writer (§4.6), probe both external endpoints from inside the container first
(§2).**

---

## 9. Implementation plan for the next session

1. **Scaffold** repo + `pyproject.toml` (deps above) + `Dockerfile`
   (python:3.12-slim, uv, `WORKDIR /app`, copy code; no custom compile steps).
2. **Phase 1 — harness gate (do early!):** minimal MCP server (only `get_status`),
   compose file, `.mimocode/mimocode.json` → `mimo mcp list` = `✓ connected`.
   Then a stdio probe. This de-risks §4.1 before you build anything real.
3. **Phase 2 — indexer:** SQLite schema + FTS, `.cpp` parsing via
   tree-sitter-language-pack, `search_code`/`symbol_lookup` over a prebuilt index of
   the workspace (build at startup if empty).
4. **Phase 3 — watcher on save:** observer thread + debounce queue + per-file
   upsert; sweep + startup reconcile; verify: create `test.cpp` with a unique
   symbol → poll `search_code`/`symbol_lookup` until found (target <5 s).
5. **Phase 4 — embeddings + Qdrant:** embed-on-index (batch), embed-on-query,
   `semantic=true` path; reuse collection `code_index_2560`. From-container probes
   first (§2).
6. **Phase 5 — acceptance:** the original test end-to-end **through the harness**
   (reload session), plus `docker compose down && up -d` resilience check.
7. Optional topology B (always-on watcher sidecar) once A passes.

**Definition of done:** all four original requirements + acceptance test green;
`mimo mcp list ✓`; README section with the runbook commands (model it on
`AGENTS.md` in the reference deployment).

---

## 10. Quick reference — commands that worked

```bash
# from the project dir (watch your CWD — §4.2)
docker compose up -d --build
docker ps --filter name=<service>

# container → host service probes (run these first)
docker exec <c> python -c "import urllib.request,json; \
  req=urllib.request.Request('http://host.docker.internal:8080/v1/embeddings', \
  data=json.dumps({'model':'Qwen3-Embedding-4B-Q6_K','input':'probe'}).encode(), \
  headers={'Content-Type':'application/json'}); \
  print(len(json.load(urllib.request.urlopen(req,timeout=15))['data'][0]['embedding']))"
docker exec <c> python -c "import urllib.request,json; \
  print(json.load(urllib.request.urlopen('http://host.docker.internal:6333/collections'))['status'])"

# harness gate
mimo mcp list
```

Further reading in this repo: **report §5** (watcher event route, with file:line),
**§7** (every change made to the reference deployment, incl. the three upstream
patches), **§8** (verification evidence), **§9** (semantic caveat — the reason we
recommend no-LLM embedding design), **§4.6** (index isolation — relevant if you ever
serve multiple workspaces).
