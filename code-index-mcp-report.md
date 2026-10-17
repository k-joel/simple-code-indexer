# Code-Index-MCP — Investigation & Deployment Report

**Repository:** https://github.com/Consiliency/Code-Index-MCP (cloned at `../code-index-mcp-repo/`)
**Deployment workspace:** `D:\Projects\Docker\code-index-mcp`
**Report date:** 2026-10-17
**Tested version:** upstream `main` @ `6b29c4a` (v1.4.1 prepared candidate)

---

## 1. Executive summary

Code-Index-MCP is a local-first **Model Context Protocol (MCP) server** that gives AI
coding assistants a fast search index over a codebase: full-text (BM25/FTS5) search,
exact symbol lookup, and optional semantic (vector) search — instead of the assistant
reading whole files and burning tokens.

### Requirements verdict

| Requirement | Verdict | Notes |
|---|---|---|
| Runs in Docker via `docker-compose.yml` | ✅ Fits | Custom `docker-compose.yml` defines the long-lived service; MCP attaches via `docker exec`. |
| Externally configured embedding model | ✅ Fits | OpenAI-compatible endpoint; profile `oss_high` points at Qwen3-Embedding-4B-Q6_K (2560-dim) on `host.docker.internal:8080`. |
| Vectors stored in Qdrant | ✅ Fits | Server-mode Qdrant via `QDRANT_URL`; vectors proven written & queried (see §8). |
| File watcher: auto-index on save | ⚠️ Fits, with caveats | Watchdog/inotify runs inside the container's stdio process over the bind mount. Events are treated as *hints*; the indexer reconciles **committed** git state (~30s after commit), with a periodic full-tree sweeper as backstop. Details in §5. |

**Deployment completed and verified**: lexical search, symbol lookup, and the
watcher→reindex loop all work end-to-end through the MiMoCode harness. Semantic
search is fully wired but currently blocked by the project's strict
"summaries-before-vectors" pipeline (no LLM summarizer available) — see §9.

---

## 2. What the repo does

- **Search index for code.** Indexes a workspace into SQLite (FTS5 for BM25) plus
  per-symbol tables, so an assistant can jump straight to a function/class instead of
  grepping or reading files.
- **MCP server.** Primary surface is **STDIO** (`mcp-index stdio`); a FastAPI gateway
  exists but is admin/diagnostics only (remote MCP transport is deferred upstream).
  Tools: `search_code`, `symbol_lookup`, `get_status`, `list_plugins`, `reindex`,
  `write_summaries`, `summarize_sample`, `handshake`.
- **Multi-language plugins.** ~48 tree-sitter languages; specialized plugins for
  Python, C, C++, JS/TS, Dart, HTML/CSS, etc. Language auto-detection is on by default.
- **Optional semantic search.** Embeds code chunks + file summaries into a vector
  store (Qdrant) through an OpenAI-compatible embeddings endpoint (Voyage AI or
  self-hosted, e.g. vLLM/llama.cpp), with hybrid fusion over BM25 results.
- **Real-time updates.** File-system watcher (watchdog) + git ref polling keep the
  index in sync; a full-tree "sweeper" recovers dropped events.
- **Multi-repo (v3).** One server can serve many registered repositories; queries are
  scoped by `repository=` and are **fail-closed** on readiness (see §6).
- **Index portability.** Optional GitHub Artifacts sync of index baselines (disabled
  here).

---

## 3. Repository layout (upstream)

```
Code-Index-MCP/
├── mcp_server/                  # The entire Python package
│   ├── cli/                     # stdio_runner (MCP server), tool_handlers, bootstrap,
│   │                            #   repository/index/setup CLI commands
│   ├── dispatcher/              # EnhancedDispatcher: plugin routing, caching,
│   │                            #   search execution, semantic staging hooks
│   ├── plugins/                 # language plugins (python, cpp, js, c, dart, html…)
│   ├── plugin_system/           # PluginManager, lazy loading, memory-aware eviction
│   ├── storage/                 # SQLiteStore (FTS5), GitAwareIndexManager,
│   │                            #   RepositoryRegistry, repo_identity
│   ├── watcher/                 # file_watcher (single repo), ref_poller, sweeper
│   ├── watcher_multi_repo.py    # MultiRepositoryWatcher + per-repo handlers
│   ├── indexer/ / utils/        # semantic_indexer (Qdrant), embedding_providers
│   ├── indexing/summarization.py# summary-first chunk summarizer (LLM)
│   ├── artifacts/               # GitHub Artifacts index sync, semantic profiles
│   ├── health/                  # ReadinessClassifier (fail-closed query gate)
│   ├── config/settings.py       # env + profiles YAML resolution
│   └── core/                    # repo_resolver, ignore_patterns, repo_context
├── docker/dockerfiles/          # Dockerfile.minimal/.standard/.production/…
├── docker-compose.yml           # dev stack (FastAPI + redis + qdrant) — not used here
├── docker/compose/development/
│   └── docker-compose.mcp-sidecar.yml   # sidecar pattern used as the basis here
├── code-index-mcp.profiles.yaml # semantic profiles (commercial_high, oss_high)
├── .mcp.json.templates/         # client templates (incl. docker-sidecar.json)
├── scripts/, tests/, docs/, specs/, architecture/, k8s/, monitoring/ …
```

Canonical dependency/CLI: `uv sync --locked`; entry points `mcp-index` / `index-it-mcp`
→ `mcp_server.cli:cli` (the minimal image doesn't install the entry points, so we run
`python /app/mcp_server_cli.py`, the STDIO shim).

---

## 4. Architecture breakdown

### 4.1 Process & transport model

```
MiMoCode harness (client, protocol 2025-11-25)
   │  stdio (JSON-RPC, newline-delimited)
   ▼
docker exec -i code-index-mcp python /workspace/mcp-compat-proxy.py   ← compat shim (§7.3)
   │  pipes + response sanitization
   ▼
python /app/mcp_server_cli.py  →  mcp_server.cli.stdio_runner.run()
   │
   ├─ _serve(): bootstrap + serve loop
   │    ├─ initialize_stateless_services()      (mcp_server/cli/bootstrap.py)
   │    │    ├─ RepositoryRegistry   (~/.mcp/repository_registry.json, on mcp-home volume)
   │    │    ├─ StoreRegistry        (per-repo SQLite handles)
   │    │    ├─ RepoResolver         (path → RepoContext + readiness classification)
   │    │    ├─ EnhancedDispatcher   (plugins, search, semantic hooks)
   │    │    └─ GitAwareIndexManager (staged rebuilds / incremental syncs)
   │    ├─ MultiRepositoryWatcher.start_watching_all()   (per registered repo)
   │    ├─ RefPoller.start()                             (30s git HEAD polling)
   │    └─ MCP server loop (initialize / tools/list / tools/call)
   └─ call_tool() → tool_handlers.handle_* → dispatcher / index manager
```

Startup order matters: the watcher and ref poller start **eagerly** before serving,
which is what made startup latency critical for the harness (§7.1).

### 4.2 Storage

- **SQLite + FTS5** per repository, stored as *generations*:
  `.mcp-index/generations/<id>.db`, with `current.db` as the published active
  generation (registry's `index_path`). A rebuild builds into a
  `.current.db.staging-<rand>/source` staging tree, then publishes atomically
  (`publish_generation`) with optimistic-concurrency on the registration +
  generation, quarantining a broken previous index.
- Tables: `files`, `symbols`, `code_chunks`, `chunk_summaries`, `schema_version`,
  `repositories`, plus FTS over chunks. Readiness inspects the DB (integrity,
  required tables, row counts, chunk-scheme marker).
- **Qdrant** (server mode) holds vectors, in *namespaced per-repo collections*:
  `ci__<repo>__oss-high__<fingerprint>` — not the profile's base collection name.

### 4.3 Dispatcher & plugin flow (search path)

1. Tool handler resolves a `RepoContext` from the `repository` arg or
   `MCP_WORKSPACE_ROOT` via `RepoResolver`, and classifies readiness.
2. Fail-closed gate: non-`ready` → `index_unavailable` + `safe_fallback:
   "native_search"` + remediation.
3. `EnhancedDispatcher` routes by extension/language (lazy plugin loading,
   memory-aware eviction), executes BM25/FTS queries, symbol-table lookups,
   query-intent routing (symbolic patterns go straight to `symbols`), optional
   fuzzy trigram search, optional semantic retrieval + fusion.

### 4.4 Semantic pipeline (profiles, embeddings, summaries)

- **Profiles** live in `code-index-mcp.profiles.yaml` (or `MCP_PROFILES_PATH`);
  `SEMANTIC_DEFAULT_PROFILE` selects one (`oss_high` here). Settings convert YAML →
  runtime config (model, dimension, distance, collection, embedding base URL, …).
- **Env overrides:** `SEMANTIC_EMBEDDING_BASE_URL` (primary) / `VLLM_EMBEDDING_BASE_URL`
  (legacy) for embeddings; `SEMANTIC_ENRICHMENT_BASE_URL` for the summarizer;
  `QDRANT_URL` for server-mode Qdrant; `SEMANTIC_SEARCH_ENABLED` gates the feature.
- **Embedding client:** `OpenAICompatibleEmbeddingProvider`
  (`utils/embedding_providers.py`) posts `{model, input}` to `<base>/v1/embeddings`;
  dimension is *measured* from the response (2560 here).
- **Summary-first strict pipeline:** before chunk vectors are written, chunks must
  have LLM summaries (dispatcher's `_semantic_stage` calls
  `ComprehensiveChunkWriter.process_scope`, then `index_files_batch(
  require_summaries=True)`). Summarizer sources, in order: MCP sampling (if the
  client declares it) → Cerebras BAML → direct API (profile base_url →
  Cerebras/Anthropic/OpenAI keys). This design point drove issues §7.4–7.5.
- **Hybrid search:** `search_code(semantic=true)` embeds the query (same endpoint),
  queries Qdrant, fuses with BM25.

### 4.5 Readiness contract (fail-closed)

`ReadinessClassifier` (health/repository_readiness.py) gates every query:

```
ready | unregistered_repository | missing_index | index_empty | stale_commit
wrong_branch | index_building | missing_provenance | corrupt_sqlite
index_locked | scheme_mismatch | index_rebuilding | unsupported_worktree | …
```

Key behaviors observed in practice:

- `last_indexed_commit` must equal live `HEAD`, and the tracked tree must be clean
  (untracked files ignored) — so **every commit makes the index stale** until the
  next sync/reindex.
- Non-git directories end up `missing_provenance` — the workspace must be a git repo
  with at least one commit.
- Semantic readiness is separate: `ready | vectors_missing | summaries_missing |
  enrichment_unavailable | …`.

### 4.6 Index isolation across workspaces / multi-project management

Indexes from different projects are kept separate by **identity, storage location,
scoping, and namespacing**, layered as follows.

**1. Repository identity (`repo_id`) — the isolation key.**
`compute_repo_id()` (`mcp_server/storage/repo_identity.py:71`) derives a stable
16-hex-SHA256 ID with three fallback tiers:

| Tier | Input | Meaning |
|---|---|---|
| 1 | `git rev-parse --git-common-dir` → resolved absolute POSIX path → `sha256[:16]` | Default for any git checkout |
| 2 | normalized `remote.origin.url` → `sha256[:16]` | Only if Tier 1 fails (e.g. `.git` absent) |
| 3 | resolved absolute path → `sha256[:16]` | Non-git directory fallback |

Consequences:

- **Separate clones / separate projects get different IDs** (their `.git` common-dir
  paths differ), even when they share the same remote URL — Tier 1 wins over Tier 2.
- **All worktrees of the same repository share one ID** (same `--git-common-dir`).
  To prevent double-indexing, registering a *sibling* worktree of an already
  registered repo raises `MultipleWorktreesUnsupportedError`
  (`repository_registry.py:357-365`), and queries against unsupported sibling
  worktrees are refused with `unsupported_worktree` (P27 contract) instead of
  silently reusing another checkout's index.

**2. Physical storage — each workspace owns its index files.**
Registration places each repository's index **inside that workspace**:

```
register_repository() (repository_registry.py:369-370):
    index_base = <repo_path>/.mcp-index
    index_db   = <repo_path>/.mcp-index/current.db     ← active published generation
    generations/<generation_id>.db                     ← immutable rebuild stages
```

So project A's SQLite never touches project B's — isolation is by directory, not by
table/namespace within a shared file. (Index discovery also understands a legacy
centralized `.indexes/<repo_hash>/` layout and `code_index.db` naming
— `utils/index_discovery.py` — but the v3 registry path above is what's active
here; our deployment's index lives at `/workspace/.mcp-index/` on the bind mount.)
Each repo additionally has its own optional `.mcp-index.json` (per-repo opt-out /
artifact prefs) and is filtered by its **own** `.gitignore` + `.mcp-index-ignore`.

**3. Registry — the routing table.**
`RepositoryRegistry` (`storage/repository_registry.py`) persists one JSON record per
repo at `~/.mcp/repository_registry.json` (in our deployment: the `mcp-home` volume),
mapping `repo_id → RepositoryInfo {path, index_path, git_common_dir, tracked_branch,
current/last_indexed commit, auto_sync, …}`. All scoping, readiness, and watcher
decisions resolve through this table; a server started against one workspace simply
sees one entry (our case), while `MCP_ALLOWED_ROOTS` (colon-separated allowlist)
additionally sandboxes which filesystem paths tools may touch at all.

**4. Query-time scoping.**
Every query tool takes an optional `repository=` argument (registered ID, registered
name, or absolute path inside `MCP_ALLOWED_ROOTS`). Resolution
(`tool_handlers._resolve_ctx` → `RepoResolver` / `ReadinessClassifier.classify_path`)
matches in order: exact repo ID → registered name → exact path → git-root path. Each
resolved `RepoContext` carries **its own** `sqlite_store`, workspace root, and
tracked branch — a search never mixes another workspace's rows. Without a
`repository` argument, the fallback target is `MCP_WORKSPACE_ROOT` (single-workspace
deployments) or cwd.

**5. Readiness is per-repository.**
`ReadinessClassifier` evaluates `last_indexed_commit` vs live HEAD, branch, and DB
health *for the selected repo only* (`health/repository_readiness.py`). One project
being stale/unregistered causes `index_unavailable` **only for queries targeting
that project**; others stay `ready`. `get_status` lists all registered repos with
independent readiness rows.

**6. Vector (semantic) isolation — Qdrant collection namespacing.**
Vectors are never written into a shared collection. Names are resolved per repo +
profile + lineage (`artifacts/semantic_namespace.py:56`):

```
ci__<repo_hash>__<profile>__<lineage/fingerprint>
e.g. ci__bece6e4519cb__oss-high__4f988d008d08a2bdd4908ef3d8b4f822
```

so different projects (and different index generations) upsert into different Qdrant
collections, and a dimension/profile change can't collide with another project's
vectors. The profile's base collection name in `code-index-mcp.profiles.yaml` is
overridden by this resolver.

**7. Runtime caches are keyed by `repo_id`.**
- `StoreRegistry` (`storage/store_registry.py`) — thread-safe per-repo SQLite handle
  cache with per-`repo_id` construction locks (no cross-repo connection sharing).
- `SemanticIndexerRegistry` — per-repo semantic indexer instances with explicit
  eviction (`evict(repo_id, expected_owner=…)`).
- `EnhancedDispatcher.evict_repository_state` / plugin lifecycle — dispatcher
  per-repo state (caches, language plugins) is evicted per repo ID, though plugin
  *code* is shared.
- `RepoContext` is a frozen dataclass bundling `{repo_id, sqlite_store,
  workspace_root, tracked_branch, registry_entry}` — the unit that flows through
  search/reindex/watcher paths.

**8. Watcher isolation.**
`MultiRepositoryWatcher` runs **one watchdog `Observer` per registered repo**
scoped to that repo's root, plus per-repo `RefPoller`/`GitMonitor` entries. The
handler's branch guard (`should_reindex_for_branch`) and gitignore filter prevent
events from a different branch/worktree of the same repo from polluting the indexed
generation.

**In our deployment** this manifests as: a single registered repo (`/workspace`,
`repo_id bb6d138355bc7a8c`), its index in `/workspace/.mcp-index/`, its vectors in
`ci__…__oss-high__…`, the registry in the `mcp-home` volume, and
`MCP_ALLOWED_ROOTS=/workspace` blocking any path outside the project. To index a
*second* project you would either mount it under the same `/workspace` (it registers
as its own `repo_id` with its own `.mcp-index/`) or add it to `MCP_ALLOWED_ROOTS`
and `repository register` it — queries stay scoped via `repository=` either way.

---

## 5. File watcher: how file events reach the container (requirement #4)

### 5.1 Components

| Component | File | Role |
|---|---|---|
| `FileWatcher` | `mcp_server/watcher/file_watcher.py` | Single-dir watchdog `Observer`, 0.5s debounce → `index_file_guarded` |
| `MultiRepositoryWatcher` | `mcp_server/watcher_multi_repo.py` | One watchdog `Observer` **per registered repo** + handler with branch/gitignore guards |
| `RefPoller` | `mcp_server/watcher/ref_poller.py` | Polls recorded default branch HEAD every ~30s |
| `GitMonitor` | `watcher_multi_repo.py` | Polls `git rev-parse HEAD` every 30s |
| `WatcherSweeper` | `mcp_server/watcher/sweeper.py` | Full-tree SHA-256 scan vs SQLite every `MCP_WATCHER_SWEEP_MINUTES` (set to **1** here) to recover dropped events |

In the v3 STDIO flow the effective watcher is the **MultiRepositoryWatcher** (the
single-dir `FileWatcher` lives in `initialize_services()`, which the stateless
bootstrap path skips).

### 5.2 Event routing path (host save → container index)

```
Save on Windows host (D:\Projects\Docker\code-index-mcp\…)
   │  Docker Desktop bind mount (9p/virtiofs) propagates inotify events
   ▼
inotify inside container on /workspace (watchdog Observer, registered recursively)
   │  MultiRepositoryHandler.on_any_event (watcher_multi_repo.py:372)
   ▼
_trigger_reindex_with_ctx (line 225)
   │  because a RepoResolver exists → _reconcile_committed_event (line 357)
   │  "Watchdog is a hint to reconcile Git, never authority for working-tree bytes"
   ▼
GitAwareIndexManager.sync_repository_index(repo_id, …)
   │  compares working git state vs last_indexed_commit
   │  → incremental projection of the changeset, or staged full rebuild
   ▼
published generation (current.db) → queries see the new file
```

Backstops if native events are dropped (common on Docker Desktop mounts):

- **RefPoller / GitMonitor**: HEAD polled every ~30s → sync on drift.
- **WatcherSweeper**: full-tree hash scan every 1 minute (`MCP_WATCHER_SWEEP_MINUTES=1`).

### 5.3 The two important caveats

1. **Committed-state reconciliation.** Because events only trigger
   `sync_repository_index`, a *new or edited file is indexed after you commit it*
   (≈30s latency), not on the raw save of an uncommitted file. Untracked files are
   not picked up at all until committed. This is deliberate upstream design
   ("never authority for working-tree bytes").
2. **Watcher lifetime = MCP session lifetime.** The observers run inside the STDIO
   process the harness spawns; when the harness closes, watching stops.

Empirically: committing `widget_checksum.cpp` while a session was open caused the
sync to fire, index the file (2 C++ symbols), and complete in ~2 minutes (that run
was slowed by the since-fixed summarizer hangs).

---

## 6. Requirements assessment detail

### 6.1 Docker via docker-compose — YES

Upstream ships several compose files (dev FastAPI stack, sidecar pattern,
production). The `docker-compose.mcp-sidecar.yml` pattern (long-lived container +
`docker exec -i … stdio` per client) matched MiMoCode's local-MCP model best, so the
deployment uses that shape (§7.1).

### 6.2 External embedding model — YES

Configured through `code-index-mcp.profiles.yaml` + env:

```yaml
oss_high → model.name: Qwen3-Embedding-4B-Q6_K, output_dimension: 2560,
           base_url: ${SEMANTIC_EMBEDDING_BASE_URL}   # host.docker.internal:8080/v1
           vector_store: qdrant, distance: cosine, l2_normalize: true
```

Verified from inside the container: `POST /v1/embeddings` returns 2560-dim vectors
(short alias and full GGUF path both accepted by the llama.cpp server).

### 6.3 Qdrant — YES

`QDRANT_URL=http://host.docker.internal:6333` (existing host-published server).
Verified: collections probe OK; a namespaced `ci__…__oss-high__…` collection was
created with **4 points, dim 2560, distance Cosine**, and a semantic query
("widget checksum validation") returned the test file from Qdrant during the session
before the summary-pipeline issue was uncovered.

### 6.4 File watcher — YES (with §5.3 caveats)

Mechanics proven (event/RefPoller-driven sync indexed the new .cpp). Caveats are
inherent to the project's committed-state design, not misconfiguration.

---

## 7. Changes made to get it working

### 7.1 Deployment artifacts (this workspace)

| File | Purpose |
|---|---|
| `docker-compose.yml` | `code-index-mcp` service: `mcp-index:minimal` image, `tail -f /dev/null` entrypoint, `working_dir: /workspace`, mounts `.:/workspace` + named volume `mcp-home:/home/mcp` (registry persistence). Env: workspace/sandbox (`MCP_WORKSPACE_ROOT`, `MCP_ALLOWED_ROOTS`), semantic endpoints (`SEMANTIC_EMBEDDING_BASE_URL`, `OPENAI_API_BASE`, `QDRANT_URL`), `MCP_WATCHER_SWEEP_MINUTES=1`, `MCP_AUTO_INDEX=false` (registration+reindex own the canonical index), `GIT_CONFIG_*` (see §7.2). **No `OPENAI_API_KEY`** (deliberate, §7.4). |
| `code-index-mcp.profiles.yaml` | Custom `oss_high` profile: Qwen3-Embedding-4B-Q6_K, 2560-dim, cosine, Qdrant collection `code_index_2560`. **No `summarization:` block** (deliberate, §7.4). |
| `mcp-compat-proxy.py` | **Required** stdio compatibility shim (§7.3). |
| `.mimocode/mimocode.json` | MiMoCode MCP entry: `docker exec -i code-index-mcp python /workspace/mcp-compat-proxy.py`, `timeout: 60000`, `sampling: "deny"`, `enabled: true`. |
| `.mcp-probe.py` | Test client (MCP stdio) used for reindex/search verification. |
| `AGENTS.md` | Operational runbook + non-obvious behaviors. |
| `.gitignore`, git repo | Workspace is a **git repo with an initial commit** (readiness requires it); index files, logs, probes ignored. `.gitignore` pre-seeds exactly the four lines the server would otherwise append (keeps the tracked tree clean). |
| `widget_checksum.cpp` | Test file (commit `6762e73`). |

**One-time setup actions:** image build, `repository register /workspace --no-artifacts`
(persisted in the `mcp-home` volume), full `reindex`.

**Image build:** `docker build -f docker/dockerfiles/Dockerfile.minimal -t
mcp-index:minimal ../code-index-mcp-repo` (context outside the watched workspace —
also speeds watcher startup, §7.6).

### 7.2 Git-inside-container fixes (`GIT_CONFIG_*` env in compose)

| Problem | Fix |
|---|---|
| `fatal: detected dubious ownership` — bind-mounted files appear owned by another UID → git unreadable → readiness `unregistered_repository` | `GIT_CONFIG_KEY_0=safe.directory`, `GIT_CONFIG_VALUE_0=*` |
| Container git saw ` M .gitignore` while host git saw clean (CRLF normalization mismatch on Windows) → rebuild refused with "Commit or discard tracked edits" | `GIT_CONFIG_KEY_1=core.autocrlf`, `GIT_CONFIG_VALUE_1=input` |

### 7.3 MiMoCode harness compatibility — `mcp-compat-proxy.py`

`mimo mcp list` reported **"Failed to get tools"** even though a standard MCP client
could complete `initialize` + `tools/list` against the same command. A stdio tee
revealed the full valid exchange; the failures were:

1. **`capabilities.tasks`** in the initialize result — rejected by the client's
   schema → proxy strips it.
2. **Per-tool `"execution": {"taskSupport": …}`** in tools/list → proxy strips it.
3. **Payload size**: tools/list is a single ~30KB line (8 tools × large `oneOf`
   `outputSchema`s) — exceeding the client's line limit. Proxy drops `outputSchema`
   (optional per spec). **This was the decisive fix.**

The proxy passes everything else through untouched; optional tracing via
`MCP_PROXY_TRACE=<path>`.

Also set in `mimocode.json`:
- `timeout: 60000` — server startup (bootstrap + eager watchers) is ~3–7s, over the
  5s default.
- `sampling: "deny"` — the server can attempt MCP `sampling/createMessage` for
  summarization; deny avoids harness prompts.

### 7.4 Summarizer configuration traps (reindex hangs)

Two misconfigurations each caused ~30s reindex timeouts (the reindex tool's budget):

1. **Dummy `OPENAI_API_KEY=local-no-key-required`** → summarizer considered
   "direct API available" → real retries against `api.openai.com` (unreachable)
   inside the rebuild → `TimeoutError`. **Fix: no `OPENAI_API_KEY` at all**
   (embedding provider falls back to an internal placeholder key).
2. **`summarization: {enabled: false}` block still emitted a base_url fallback**
   (`http://ai:8002/v1` — settings resolves a fallback whenever the block exists)
   → summarizer targeted an unreachable host with connection retries. **Fix: remove
   the `summarization:` block entirely.**
3. Earlier attempt: pointing the summarizer at the llama.cpp **chat** endpoint worked
   functionally but was too slow/unreliable (batch API timeouts) for the pipeline.

### 7.5 Local patches to upstream code

All three are committed in the clone (`../code-index-mcp-repo`) and baked into the
image:

1. **`docker/dockerfiles/Dockerfile.minimal`** — precompile step referenced the
   removed `tree_sitter_languages` package (build failure). Changed to
   `tree-sitter-language-pack` (what the code actually uses today).
2. **`watcher_multi_repo._start_repo_watcher`** — `observer.start()` blocks until
   every recursive inotify watch is registered (~3–5s over the Windows bind mount;
   watchdog's `Emitter.start` waits on `on_thread_start`). Now runs `observer.start()`
   on a daemon thread → startup ~7s → ~3–4s, under the client's tool-fetch budget.
3. **`git_index_manager._semantic_stage_error`** — strict contract: a full rebuild
   with `semantic_blocked > 0` (all chunks "missing summaries" when no summarizer
   exists) fails `clean=False` → staged rebuild aborted → readiness stuck at
   `missing_provenance` forever. Patch treats summary-blocked stages
   (`blocked_missing_summaries` / `blocked_summary_plateau` / `blocked_summary_timeout`
   / `blocked_summary_call_timeout`, with `semantic_failed == 0`) as **non-fatal**:
   the lexical generation publishes; vectors can still arrive later via
   incremental/watcher syncs.

A temporary `logger.exception` addition inside the rebuild's failure handler (the
upstream code swallows the underlying RuntimeError) also remains in the image — it
only fires on real failures and was instrumental in diagnosing issue 3.

### 7.6 Workspace topology change

The upstream clone was **moved out of the watched workspace** to
`../code-index-mcp-repo` (i.e. `D:\Projects\Docker\code-index-mcp-repo`):
inotify registers recursively, and thousands of clone directories made watcher
startup exceed client timeouts. Compose `build.context` updated to match.

### 7.7 Harness lifecycle

MiMoCode reads `.mimocode/mimocode.json` at session start; after any config change
the harness must be **closed and reopened** to (re)load the MCP server.

---

## 8. Verification results

Final state (all through `mcp-compat-proxy.py`, i.e. the exact harness path):

| Check | Result |
|---|---|
| `mimo mcp list` | `✓ code-index-mcp connected` |
| `reindex` (recovery, clean tree) | `staged_full`, 3 files, **7.7s**, commit == HEAD |
| `get_status` readiness | **`ready`** (last_indexed_commit == HEAD, tree clean) |
| `search_code("calculateWidgetChecksum")` | **1 hit** — `widget_checksum.cpp`, snippet with match highlight |
| `symbol_lookup("calculateWidgetChecksum")` | `widget::calculateWidgetChecksum`, kind=function, language=cpp, signature, **@ /workspace/widget_checksum.cpp:9** |
| Embedding endpoint (from container) | 2560-dim vectors, `Qwen3-Embedding-4B-Q6_K` |
| Qdrant (from container) | reachable; namespace collection written: **4 points, dim 2560, Cosine** |
| Semantic `search_code(semantic=true)` | Returned a Qdrant-backed hit *while vectors existed*; currently `semantic_not_ready` after lexical-only rebuilds (see §9) |
| Watcher | Committed `.cpp` file was picked up by the sync path and indexed (2 symbols) without manual intervention |

---

## 9. Known limitations & caveats

1. **Semantic search after full rebuilds.** Upstream's summary-first pipeline needs
   an LLM summarizer before chunk vectors are written. No summarizer is configured
   (and none should be, per §7.4), so fresh rebuilds publish lexical-only
   generations and `semantic=true` returns `semantic_not_ready`. Embedding+Qdrant
   wiring is proven working (vectors were written and queried earlier via the
   incremental path). To fully enable: add a `summarization:` block with a *fast,
   reliable* chat endpoint to `code-index-mcp.profiles.yaml` and reindex.
2. **Committed-state indexing.** Saves are auto-indexed *after commit* (~30s), not
   on raw save; untracked files are ignored until added (§5.3).
3. **Staleness on every commit.** Queries fail closed (`stale_commit`) until the
   RefPoller/sweeper syncs (~30s) or someone runs the `reindex` tool.
4. **Watcher lifetime.** Watching only happens while the harness (MCP session) is
   open — no indexing while the harness is closed.
5. **Upstream is beta** for STDIO + multi-repo; expect surface changes on upgrade
   (re-apply §7.5 patches and re-verify the proxy if you update the clone).
6. **MCP-sampling summarization** is denied in config; if the harness sampling
   policy is ever set to `allow`, the server may attempt client-side summarization.
7. **Rebuild concurrency.** Multiple simultaneous sessions rebuilding the same
   generation can race publishes (`expected_generation` mismatch → failed rebuild);
   benign in normal use (one harness session), but avoid running probes during one.

---

## 10. Operational runbook

```bash
# Stack
docker compose up -d                    # start service (from this directory)
docker compose down                     # stop
docker logs code-index-mcp             # container logs

# One-time (already done; registry persists in the mcp-home volume)
docker exec code-index-mcp python -c "import sys; from mcp_server.cli import cli; \
  sys.argv=['mcp-index','repository','register','/workspace','--no-artifacts']; cli()"

# Manual reindex (also available as the MCP `reindex` tool)
docker exec code-index-mcp python /workspace/.mcp-probe.py phase1

# Rebuild image after upstream/clone changes
docker build -f docker/dockerfiles/Dockerfile.minimal -t mcp-index:minimal ../code-index-mcp-repo
docker compose up -d --build

# After updating the clone: re-check that §7.5 patches still apply
git -C ../code-index-mcp-repo log --oneline -3
```

**MCP client config** (`.mimocode/mimocode.json`):

```json
{
  "mcp": {
    "code-index-mcp": {
      "type": "local",
      "command": ["docker", "exec", "-i", "code-index-mcp", "python",
                  "/workspace/mcp-compat-proxy.py"],
      "enabled": true,
      "timeout": 60000,
      "sampling": "deny"
    }
  }
}
```

Reload the harness after changing this file.

**Diagnosing readiness:** call `get_status` (MCP) or
`docker exec code-index-mcp git -C /workspace status --porcelain` — queries require
`ready` (clean tracked tree + `last_indexed_commit == HEAD`).

---

## Appendix A — Environment used

| Piece | Value |
|---|---|
| Embeddings | llama.cpp server (CUDA), `Qwen3-Embedding-4B-Q6_K-Q6_K.gguf`, `http://localhost:8080/v1/embeddings`, 2560-dim |
| Qdrant | host server `http://localhost:6333` (existing compose stack) |
| Host → container addressing | `host.docker.internal` (both services bind `0.0.0.0`) |
| Workspace | `D:\Projects\Docker\code-index-mcp` → `/workspace` (bind mount) |
| MiMoCode | v0.1.15, local MCP type, project config in `.mimocode/mimocode.json` |

## Appendix B — Key source references

| Topic | Location |
|---|---|
| STDIO server / tool dispatch | `mcp_server/cli/stdio_runner.py` (`_serve`, `call_tool`, `_build_tool_list`) |
| Tool handlers & readiness gates | `mcp_server/cli/tool_handlers.py` (`_resolve_ctx`, `handle_reindex` recovery branch) |
| Stateless bootstrap | `mcp_server/cli/bootstrap.py:25-64` |
| Watcher (multi-repo) | `mcp_server/watcher_multi_repo.py:225-370, 696-738` |
| Sweeper | `mcp_server/watcher/sweeper.py` |
| Readiness classifier | `mcp_server/health/repository_readiness.py` |
| Staged rebuild / generation publish | `mcp_server/storage/git_index_manager.py:690-870, 1514-1551` |
| Semantic profile config | `mcp_server/config/settings.py` (`_find_profiles_yaml`, `get_semantic_profiles_config`, `get_profile_summarization_config`) |
| Embedding provider | `mcp_server/utils/embedding_providers.py` |
| Summary-first pipeline | `mcp_server/dispatcher/dispatcher_enhanced.py:2988-3335`, `mcp_server/indexing/summarization.py` |
| MiMoCode MCP config docs | https://mimo.xiaomi.com/mimocode/mcp-servers, /mimocode/config-files |
