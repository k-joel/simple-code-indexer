# Architecture Decision Records

Concise record of architecturally significant choices made in this project—capturing the context, decision, and trade-offs behind non-obvious structure and dependencies. Read the relevant entry before modifying or reverting established behavior.

<!--
DECISIONS.md MAINTENANCE GUIDE (FOR AGENTS & CONTRIBUTORS)

PURPOSE & SCOPE
- Canonical, single-file log of architecturally significant decisions for future
  engineers and autonomous agents.
- Explains *why* structural, dependency, and cross-cutting design choices exist.
- NOT a changelog, task/issue tracker, release note, API doc, or how-to guide.

UPDATE TRIGGERS
Update `docs/DECISIONS.md` before ending a session or finalizing a change whenever you:
- Introduce, swap, or retire a technology, framework, protocol, or design pattern.
- Make a structural choice that constrains multiple modules or is costly to reverse.
- Accept or reject a `Proposed` ADR.
- Supersede or deprecate an existing ADR (update BOTH the new and old entries,
  plus the summary index table).
Draft entries before or alongside implementation—never leave decisions undocumented.

INCLUSION / EXCLUSION CRITERIA
INCLUDE:
- Framework, library, or runtime adoption/removal.
- Data storage, schema paradigm, caching, or state-management architecture.
- Public API, IPC, or integration contracts and concurrency/deployment models.
- Security, authentication, or boundary rules and non-obvious constraints.

EXCLUDE:
- Routine bug fixes, patch/minor version bumps, or dependency hygiene.
- Local implementation details, variable naming, or behavior-preserving refactors.
- Trivial config/lint tweaks, temporary workarounds, or unmade hypotheticals.

STRUCTURE & FORMATTING
- Single H1: Keep `# Architecture Decision Records` as the only H1 in the file
  (per MADR / markdownlint MD025).
- Summary Index Table: Maintain `| ADR | Decision |` under `## Entries`
  in ascending numeric order. Every row must link to its section anchor
  (`[NNN](#adr-nnn-kebab-case-title)`).
- Numbering: Use 3-digit zero-padded IDs (`ADR-001`, `ADR-002`, ...; expand to
  4 digits only past `999`). IDs are permanent; never reuse or renumber them.
- Entry Heading: `## ADR-NNN: <Short Descriptive Title>` (H2 so file keeps one H1).
- Required Metadata (immediately below the entry heading):
    **Status**: Proposed | Accepted | Rejected | Deprecated | Superseded by ADR-NNN
    **Date**: YYYY-MM-DD  (ISO 8601 date of creation or last status update)
    **Deciders**: <@handles, team/role, or agent/session identifier>
- Required Subsections (exact names and H3 level, in order):
    ### Context
    ### Decision
    ### Consequences
- Required Consequences Fields:
    **Good**: <Positive outcomes.>
    **Bad**: <Real trade-offs, costs, or limitations.>
    **Mitigations**: <Guardrails or follow-up actions; omit ONLY if none apply.>
- Never omit `### Context`, `### Decision`, `### Consequences`, `**Good**:`, or
  `**Bad**:`. Keep entries in ascending numeric order (`ADR-001` .. `ADR-NNN`).

QUALITY & STYLE RULES
- Tense & Tone: Neutral, factual, concise (~15-25 lines per entry). Use past
  tense for `Context` ("Faced..."), present/imperative for `Decision` ("Use...").
- Honesty: Document genuine downsides in `**Bad**:`; no choice is cost-free.
- Verifiability: Ground claims in concrete constraints, observed measurements,
  or repo-relative paths and ADR IDs (`ADR-NNN`). Avoid vague adjectives
  ("faster", "cleaner", "better") without specifics.
- Cross-Links: Reference related decisions inline as `ADR-NNN` (e.g., `see ADR-002`).

LIFECYCLE & WORKFLOW
- Add: Append the new entry at the end of the file with the next `ADR-NNN` and
  add its matching row to the summary index table.
- Promote / Reject: Transition `**Status**` (`Proposed` -> `Accepted` or
  `Rejected`) and update `**Date**`. Keep `Rejected` entries so dead ends are
  not retried.
- Clarify: Only typo or wording fixes that preserve meaning are allowed on an
  `Accepted` entry. Never silently change the substance of an `Accepted` ADR.
- Supersede / Deprecate (Preserve History): Never delete old entries. To replace
  an `Accepted` decision, append a new `ADR-MMM` citing `ADR-NNN`, then update
  the old entry's `**Status**` to `Superseded by ADR-MMM` (or `Deprecated` if
  retired without replacement) and update its `**Date**`.

ANTI-PATTERNS
- Editing an `Accepted` ADR to say the opposite instead of writing a new ADR.
- Deleting `Deprecated`, `Rejected`, or `Superseded` entries, or renumbering IDs.
- Adding extra H1 (`#`) headings, skipping metadata fields, or forgetting to
  update the top summary index table / anchor links.
- Writing `**Bad**: None.` or omitting trade-offs.
- Recording implementation steps, file diffs, or routine bug fixes as ADRs.

EXAMPLE LAYOUT (4-SPACE INDENTED)

    ## Entries

    | ADR | Decision |
    |---|---|
    | [001](#adr-001-short-descriptive-title) | Short descriptive title |

    ---

    ## ADR-001: Short Descriptive Title

    **Status**: Accepted
    **Date**: YYYY-MM-DD
    **Deciders**: @handle, Core Team

    ### Context

    <2-4 sentences describing the problem, technical constraints, and forces
    requiring a decision. Cite affected components or prior ADRs if relevant.>

    ### Decision

    <1-3 sentences stating the exact choice made and any firm boundaries.>

    ### Consequences

    **Good**: <Concrete benefits and enabled capabilities.>

    **Bad**: <Accepted costs, complexity, or limitations.>

    **Mitigations**: <Steps or controls reducing the bad consequences.>

-->

---

## Entries

| ADR | Decision |
|---|---|
| [001](#adr-001-index-on-save-not-git-committed-state) | Index on save, not git-committed state |
| [002](#adr-002-embed-code-chunks-directly-no-llm-summaries) | Embed code chunks directly (no LLM summaries) |
| [003](#adr-003-single-writer-sqlite--wal-no-staged-generations) | Single-writer SQLite + WAL, no staged generations |
| [004](#adr-004-python-312--official-mcp-sdk-stack) | Python 3.12 + official MCP SDK stack |
| [005](#adr-005-harness-safe-minimal-mcp-tool-surface) | Harness-safe minimal MCP tool surface |
| [006](#adr-006-single-workspace-no-multi-repo-registry) | Single workspace, no multi-repo registry |
| [007](#adr-007-host-spawned-mcp-process-workspace--cwd) | Host-spawned MCP process, workspace = cwd |
| [008](#adr-008-setup-wizard-and-fail-soft-managed-services) | Setup wizard and fail-soft managed services |
| [009](#adr-009-faiss-is-the-primary-vector-store-qdrant-opt-in) | FAISS is the primary vector store; Qdrant opt-in |
| [010](#adr-010-gpu-aware-compose-and-model-prompt-templates) | GPU-aware compose and model prompt templates |
| [011](#adr-011-global-only-config-per-user-install-self-updating-launcher) | Global-only config, per-user install, self-updating launcher |
| [012](#adr-012-role-specific-per-workspace-log-files) | Role-specific per-workspace log files |
| [013](#adr-013-honor-gitignore-and-watch-the-workspace-root-recursively) | Honor `.gitignore` and watch the root recursively |
| [014](#adr-014-per-workspace-sidecar-writer--read-only-mcp-sessions) | Per-workspace sidecar writer + read-only MCP sessions |
| [015](#adr-015-harness-entries-are-global-only-no-per-project-data) | Harness entries are global-only, no per-project data |


## ADR-001: Index on save, not git-committed state

- **Context:** Upstream reconciled **committed** git state, so untracked or edited files were invisible
  until commit (~30 s), and git readiness was the largest source of operational pain (`stale_commit`,
  `missing_provenance`, rebuild races). Requirement 4 is index-on-save.
- **Decision:** A save event reindexes the working-tree bytes immediately. Git readiness, commit-gating,
  and provenance are cut entirely.
- **Consequences:** The acceptance test can create a `.cpp` file and retrieve it without committing. No
  container git fixes (`safe.directory`, `core.autocrlf`) are needed. Dropped watch events are healed by
  the hash reconciliation sweep — do not reintroduce a git-state gate.

## ADR-002: Embed code chunks directly (no LLM summaries)

- **Context:** Upstream required LLM chunk summaries before writing vectors. Without a summarizer every
  rebuild failed (`_semantic_stage_error`) and semantic search stayed `semantic_not_ready`; the chat
  endpoint is slow and unreliable for bulk jobs.
- **Decision:** Embed chunk text directly. The summarization pipeline does not exist.
- **Consequences:** Config must **omit** any `summarization:` block and **omit** `OPENAI_API_KEY` (a dummy
  key enables real `api.openai.com` retries). Semantic results are raw-code similarity, which is fine for
  code search. Vectors may lag lexical writes by a few seconds.

## ADR-003: Single-writer SQLite + WAL, no staged generations

- **Context:** Upstream's staged generation rebuilds with optimistic publish raced under concurrent
  sessions (`expected_generation` mismatch). There is one workspace and one writer here.
- **Decision:** One SQLite file with WAL and `busy_timeout`, exactly one index writer (the sidecar daemon,
  ADR-014). The MCP query path opens read-only connections. No generation staging, no quarantine tree.
- **Consequences:** Schema is plain tables — `files`, `symbols`, `chunks`, `chunks_fts` — with no
  generation columns. A rebuild is just re-running `index_one_file` or the startup reconcile, not a
  publish dance. Do not add multi-writer locking or staged generations; topology B is safe precisely
  because the writer owns all writes and MCP is read-only.

## ADR-004: Python 3.12 + official MCP SDK stack

- **Context:** The requirements are I/O-bound glue (watcher, HTTP, SQLite). Python was proven end-to-end
  in this exact environment, including every integration pitfall; a rewrite reintroduces those pitfalls
  as fresh discoveries.
- **Decision:** Python 3.12, official `mcp` SDK over stdio, `watchdog`, stdlib `sqlite3` + FTS5,
  `httpx` for embeddings, `tree-sitter` + `tree-sitter-language-pack`, `uv` for packaging. Vectors go
  through `vector_store.py`: FAISS by default, `qdrant-client` opt-in (ADR-009).
- **Consequences:** Keep the write path local-first, with short explicit timeouts and 0–2 retries. Never
  let a client default-retry toward the public internet.

## ADR-005: Harness-safe minimal MCP tool surface

- **Context:** The harness failed `tools/list` for three reasons found via stdio trace: an oversized
  single-line payload from large `outputSchema`s, `capabilities.tasks` in initialize, and per-tool
  `execution.taskSupport`.
- **Decision:** Emit none of those, keep descriptions short, and ship only `search_code`,
  `symbol_lookup`, `get_status` (optional `reindex`).
- **Consequences:** Output shapes are documented and probe-tested, not enforced by `outputSchema`. Grow the
  surface slowly and re-verify `mimo mcp list` after any `tools/list` change. Harness configs use
  `"timeout": 60000` with a <3 s startup target (lazy parsers, watcher registered on a background thread).

## ADR-006: Single workspace, no multi-repo registry

- **Context:** Upstream's multi-repo registry, `RepoResolver`, path sandbox, and worktree identity rules
  were a large complexity tax for a scope this project does not have.
- **Decision:** Exactly one workspace per process, indexed as a whole. No `repository=` argument on tools,
  no path sandbox, no worktree identity.
- **Consequences:** Serving multiple roots later needs an `MCP_ALLOWED_ROOTS`-style sandbox and is out of
  scope for v1. How the workspace is resolved is ADR-007; ignore policy is ADR-013.

## ADR-007: Host-spawned MCP process, workspace = cwd

- **Context:** The container topology mounted **this** repo at `/workspace`, so the indexer could only
  index itself; pointing it at another project needed a compose edit and a rebuild. Bind mounts also cost
  real time (watcher registration over `.venv` blocked for >10 s). Compose mounts are fixed at
  `docker compose up`, so "open project X and index X" was not expressible.
- **Decision:** The server runs **on the host**, spawned by the harness, and takes its workspace from
  `Path.cwd().resolve()`, overridable with `WORKSPACE_ROOT`. No Docker image for the server ships in this
  repo. The index lives at `$WORKSPACE_ROOT/.simple-ci/index.db`; each workspace gets its own derived
  Qdrant collection `code_index_{slug}_{sha256(path)[:8]}_{dim}` on the Qdrant backend, and its own
  `vectors.faiss` on the FAISS backend.
- **Consequences:** One static harness snippet works for every project; `get_status.workspace` and
  `vector_index` make the inference observable. `WORKSPACE_ROOT` is the escape hatch when a harness spawns
  servers from elsewhere. An inferred workspace that is the user's home directory is refused. Do not go
  back to `uvx --from <repo>` entries or a mounted container: the harness already starts the server inside
  the project, so the workspace needs no configuration.

## ADR-008: Setup wizard and fail-soft managed services

- **Context:** Every setting used to come from an environment variable, so a fresh clone required
  hand-editing a harness config with machine-specific paths and knowing which services to start. Nothing
  recorded which container backed an endpoint, so the server could not bring services up itself.
- **Decision:** `setup.py` is the install path: it installs `uv` when missing, syncs, and runs an
  interactive wizard that configures the embedding endpoint, provisions Docker containers when asked,
  probes the embedding dimension, writes `~/.simple-ci/config.yaml`, and registers detected harnesses.
  A `service` block names a container the writer starts and waits for at boot. Harness support is a
  plugin folder (`src/simple_code_indexer/harnesses/`, user drop-ins in `<repo>/harnesses/` and
  `<workspace>/harnesses/`); a bad plugin is skipped, never fatal,
  and a user drop-in overrides a builtin by `NAME`. (Language support was originally a parallel plugin
  folder; ADR-016 replaced it with a generated table, so harnesses are now the only plugin axis.)
- **Consequences:** `pyyaml` is a runtime dependency. The wizard and service manager take injectable
  runners/probers so tests need neither Docker nor network. Managed services are **fail-soft**: startup can
  block up to `startup_timeout_s`, but Docker being unavailable never refuses to serve — lexical search
  still works and `get_status` reports the state. `setup.py` is not a setuptools script (`uv_build` ignores
  it); the name exists because the workflow is `git clone && python setup.py`.

## ADR-009: FAISS is the primary vector store, Qdrant opt-in

- **Context:** Qdrant as the only backend made a second service mandatory for every install — a running
  server or Docker plus a managed container, a per-workspace collection, and a network round trip per
  search and upsert. For one workspace, tens of thousands of chunks, and a single writer, the operational
  cost outweighed the benefit. Embedding vectors in SQLite needed either an extension (`sqlite-vec`) or an
  O(n) Python distance loop per query.
- **Decision:** Semantic search uses a local FAISS index by default:
  `IndexIDMap2(IndexFlatIP(dim))` persisted at `<workspace>/.simple-ci/vectors.faiss`. Vectors are
  L2-normalised, so inner product equals cosine similarity — the same score as Qdrant's `COSINE`. Qdrant
  stays available with `vector_store: qdrant`; a config with a non-empty `qdrant:` section and no
  `vector_store` key keeps using Qdrant. `vector_store.py` is the backend-agnostic router.
- **Consequences:** `faiss-cpu` and `numpy` are runtime dependencies, imported lazily so the Qdrant path
  never imports FAISS; a broken FAISS fails soft (`vector_store_ok: false`) and leaves lexical search
  working. SQLite owns chunk metadata, the `vector_labels` mapping, and `meta.vector_label_seq`; labels are
  never reused, because recycling an id would attribute an old vector to a new chunk. `flush` writes
  `vectors.faiss.tmp` and `os.replace`s it, then clears dirty flags; `reconcile` re-flags every dirty
  label, so a lost file heals on the next start. Changing backend, path, dimension, URL, or collection
  wipes rows and label mappings and re-indexes — existing vectors are re-embedded, never migrated. Memory
  scales with the index (~500 MB for 50 k chunks at 2560 dims); `IndexFlatIP` is O(n) but n is small, so
  IVF/HNSW is only a follow-up if that becomes a problem.

## ADR-010: GPU-aware compose and model prompt templates

- **Context:** The original wizard wrote one CPU compose file with a hardcoded Windows model path and an
  NVIDIA reservation, and embedded all text raw. Both catalog models publish GGUF files in different
  repositories and document task-specific query/document instructions that materially change retrieval
  quality.
- **Decision:** Compose is rendered from the packaged template
  `setup_wizard/templates/docker-compose.yml` (env-var style `LLAMA_ARG_*`, model mount
  `../model:/models:ro`), picking the llama.cpp image for the host GPU: NVIDIA → `server-cuda`, AMD →
  `server-rocm`, Intel → `server-intel`, otherwise `server`. `LLAMA_ARG_ALIAS` pins the OpenAI `model` id
  to the catalog's `api_model`. Per-model query/document prompts come from
  `model_prompts.defaults_for_model` and are written to `embedding.query_prefix` / `document_prefix`.
- **Consequences:** The template must stay inside the package — `uv_build` ships the module directory but
  not a repo-root directory. GPU detection is best-effort and injectable (`nvidia-smi -L`, Windows
  `Win32_VideoController`, Linux DRM vendor ids), `--gpu` overrides it, and a declined/failed NVIDIA
  runtime init falls back to the CPU image rather than leaving a container that cannot start. An explicit
  config prompt wins and an empty string disables that side; `embed_texts` stays raw for probes.
  `embed_fingerprint` hashes the **document** prefix only, so changing chunk formatting re-embeds while
  changing just the query instruction does not. Models live in `~/.simple-ci/model/`; AMD/Intel
  passthrough on WSL2 is best-effort, with `--gpu cpu` as the escape hatch.

## ADR-011: Global-only config, per-user install, self-updating launcher

- **Context:** Three problems: (1) the project-local config drifted from the deployment model, silently
  overriding the machine-wide embedding endpoint, while the only per-project setting was `vector_store`;
  (2) harness entries pointed at the source checkout (`uvx --from <repo>`), so updating the checkout changed
  behaviour without a version bump and deleting it broke every install; (3) `simple-term-menu` imports
  `termios` at module load and raises `NotImplementedError` on Windows.
- **Decision:** **One** config file, `~/.simple-ci/config.yaml` (`SIMPLE_CI_CONFIG` replaces discovery).
  Project-local configs are never read; the wizard merges a legacy one into the global file and removes it.
  `setup_wizard/install.py` copies the working tree (including `.git`) to the per-user app directory, and
  harness entries launch that copy's `run_server.py` — `uv run --project <install> --no-sync python
  run_server.py` on POSIX, the venv's windowless `pythonw.exe` on Windows so no console window flashes. The
  launcher does `git pull --ff-only --autostash` (bounded at 20 s) and `uv sync` only when `HEAD` moved.
  Menus use `questionary`, with numbered `input()` prompts as the non-interactive fallback
  (`SIMPLE_CI_NO_TUI=1`).
- **Consequences:** `--scope` is gone (passing it is a parser error); `get_status.config_files` has 0 or 1
  entries. `vector_store` and `faiss.path` live globally, while the SQLite DB and FAISS file stay
  per-workspace, so isolation is unchanged. Harness entries reference an absolute install path, so moving
  or deleting the install directory requires re-running `setup.py`. `setup.py` itself must run the venv
  interpreter directly, never `uv run --project`: that changes cwd, and the wizard has to configure the
  caller's cwd (the project being indexed). The launcher imports and runs the server in-process for the
  same reason. `SIMPLE_CI_GIT_PULL=0` disables the pull. Keep `pull --ff-only --autostash`; a
  `git reset --hard` on every launch would discard edits in the installed copy.

## ADR-012: Role-specific per-workspace log files

- **Context:** A host-spawned server runs with stderr piped into the harness, so nothing persisted: every
  failure that mattered for diagnosis was lost (`IndexOutcome`/`SweepStats` discarded, daemon-thread deaths
  visible only through the default `threading.excepthook`, no record of which file blocked a stop). The
  only durable state was `get_status` flags, which carry no exception text and no history.
- **Decision:** Write rotating DEBUG logs under `<workspace>/.simple-ci/log/`, split by role: `embed.log`
  for `mode: embedded`, `writer.log` for the sidecar daemon, `reader.log` for readers. The path derives
  from `settings.index_db_path.parent`, so it follows `INDEX_DB` and always sits inside the gitignored,
  index-ignored `.simple-ci/`. Rotation is `log.max_bytes` / `log.backups`; `log.level` / `LOG_LEVEL`
  (default `debug`) controls the file only — stderr never goes below INFO, and stdout stays the untouched
  MCP JSON-RPC channel.
- **Consequences:** `logging_setup.py` owns the handlers; the stderr handler carries its own INFO level so
  package DEBUG records cannot leak into the harness console, and the file handler filters to
  `simple_code_indexer.*` at the configured level plus WARNING+ from any logger. `sys.excepthook` and
  `threading.excepthook` are chained, not replaced. Logging is fail-soft (an unwritable `.simple-ci/` warns
  and `get_status.log_file` is `null`). Logs hold paths, sizes, ranges, counts, scores, and truncated query
  text — never file contents or chunk text. `reader.log` is shared by readers, so its rotation is
  best-effort. Do not move logs to a global file: rotation would race between workspaces and lines could
  not be correlated with the index they describe.

## ADR-013: Honor `.gitignore` and watch the workspace root recursively

- **Context:** Two defects from one E2E run. Per-directory watches cost one `ReadDirectoryChangesW`
  emitter thread and handle each on Windows — a Visual Studio workspace reached 3,227 threads, ~16.4 k
  handles, and 2.5 GB private memory. And `.gitignore`d files were indexed and watched, so `artifacts/`
  polluted retrieval and build trees (`bin/`, `obj/`) fed the watcher.
- **Decision:** Schedule a **single recursive watch** on `settings.workspace_root`. Filter in the event
  handler and prune during `indexer.iter_workspace_files`. Honor nested workspace-local `.gitignore` files
  (the deeper file wins) using `pathspec` gitwildmatch semantics; `IGNORE_DIRS` remains the fixed fallback.
  Expose `get_status.ignored_dirs` / `ignored_files`.
- **Consequences:** `pathspec` is a runtime dependency. One emitter thread and one OS handle per workspace
  regardless of tree size — do not reintroduce per-directory watches or a hybrid. Ignore scope is the
  workspace root and below (a workspace nested in a git repo does not inherit `.gitignore` files above it).
  Matching is case-insensitive on Windows and case-sensitive elsewhere. `IgnoreRules` caches one
  `GitIgnoreSpec` per directory keyed by `st_mtime_ns`, so `.gitignore` edits apply without a restart; a
  create/modify/move/delete outside `IGNORE_DIRS` enqueues a sweep, whose stale-path diff removes
  now-ignored rows and vectors. Ignored files are an indexing policy, not an access-control boundary.

## ADR-014: Per-workspace sidecar writer + read-only MCP sessions

- **Context:** The MVP ran one all-in-one process per session, so the writer lease on
  `<workspace>/.simple-ci/index.db.lock` made a shared workspace all-or-nothing: the second harness's
  server logged `another simple-code-indexer already owns …` and exited, and most harnesses do not respawn
  it mid-session. A persistent harness service could also hold the lease after its UI closed. The query
  path was already read-only (WAL + `mode=ro`); only startup insisted on being the writer.
- **Decision:** Topology B. Every harness still spawns its own MCP server, but that server is a **reader**
  by default (`mode: sidecar`). The first reader that cannot reach a daemon spawns one detached under
  `daemon.spawn.lock`; the daemon acquires the writer lease *before* publishing `daemon.json` and owns the
  watcher, writer thread, sweep timer, managed services, SQLite, FAISS file, Qdrant collection, and
  heartbeat. One process hosts at most one runtime — no multi-workspace daemon. The control channel is
  stdlib `multiprocessing.connection` (Windows named pipe / POSIX AF_UNIX) with the token as `authkey` and
  JSON bodies, never pickle; discovery is `<workspace>/.simple-ci/run/daemon.json` + `daemon.token`
  (0600), written only after the lease, runtime, and listener are ready. Readers use
  `db.try_connect_readonly`, `faiss_store.search_readonly`, and `qdrant_store.search_readonly`, and never
  create, migrate, or delete. Lifetime: a live control connection is the primary lease, backed by
  `heartbeat_s` (5 s, reaped after three intervals) and `server_pid` liveness; after the last session plus
  `idle_grace_s` (60 s) the daemon stops accepting, clears discovery while it still holds the lease,
  flushes vectors, releases the lease, and exits. `mode: embedded` keeps the all-in-one process as an
  explicit escape hatch.
- **Consequences:** Multiple harnesses in one workspace each get `search_code`, `symbol_lookup`, and
  `get_status`, while exactly one process writes; closing one harness does not affect another, and
  freshness is decoupled from any single harness. A daemon crash degrades readers to stale read-only; the
  supervisor respawns it, dirty flags survive, and the next reconcile re-embeds. The default is `sidecar`,
  **not** `auto`: a daemon that cannot start leaves the workspace read-only rather than silently falling
  back to an embedded writer that would defeat the fix. Writer finalize order is load-bearing — stop the
  watcher and threads, flush vectors and clear dirty flags **while the lease is held**, clear discovery,
  then release the lease last, because `clear_vector_dirty` is unscoped and reversing the order would
  clear the next writer's flags. Migration from an install is automatic; a legacy embedded writer holding
  the lease makes the daemon exit and readers serve read-only until it is gone. `get_status` is role-aware
  (`role`, `index_ready`, `writer_pid`, `writer_ok`, `writer_heartbeat_age_s`, `writer_log_file`,
  `daemon_endpoint`, `sessions`, `harnesses`, `vector_index_age_s`).

## ADR-015: Harness entries are global-only, no per-project data

- **Context:** Every harness entry is written at **global** scope (ADR-011: one config file, one
  install, one entry set), and the workspace is inferred from the process cwd (ADR-007). Despite
  that, repeated debugging sessions hand-edited `WORKSPACE_ROOT` and `cwd` into the OpenCode, Goose
  and Pi entries, pinning this checkout's absolute path in files that belong to every project on
  the machine. The result was a global entry that silently indexed one fixed tree for every project
  opened afterwards, and a git-tracked repo path leaking into user-home config. The behaviour was
  even documented as a step (`ref-docs/mcp-test-process.md` §4.4) and as a harness capability (the
  three plugins emit `cwd` from `WORKSPACE_ROOT`), so each new session re-created it.
- **Decision:** A harness entry contains **only** install-scoped data: the interpreter, the
  installed `run_server.py` launcher, and the user's global settings. It must never contain a
  workspace path — no `WORKSPACE_ROOT`, no `cwd`, no `INDEX_DB`, no `FAISS_PATH`. Workspace
  resolution stays entirely runtime-inferred from the harness's spawn cwd (ADR-007). Harness
  plugins therefore drop `WORKSPACE_ROOT`/`cwd` from the entry they build and pass `env` through
  untouched; the wizard passes an empty `env` unless `--no-git-pull` (a debug switch) adds
  `SIMPLE_CI_GIT_PULL=0`. A temporary pin is allowed **only** inside a
  debugging session, and must be removed before the session's work is called done.
- **Consequences:** One static entry set serves every project; moving or cloning a repo cannot
  leave a stale absolute path behind, and re-running `setup.py` is idempotent with respect to the
  workspace. `get_status.workspace` remains the way to detect a harness that spawns from elsewhere
  — the fix is a harness that spawns in the project cwd, not an entry edit. `SIMPLE_CI_GIT_PULL=0`
  is *not* covered by this ban: it is a machine/install-scoped toggle, not a project path, but it
  too is debugging-only and should not survive the session. When a harness genuinely cannot spawn
  in the project directory, that is a harness defect to record in `docs/ISSUES.md`, not something
  to paper over per project.

## ADR-016: A generated language catalog replaces the plugin folder

- **Context:** Language support was 38 `.py` modules under `builtin/` loaded with `importlib`, plus a
  user drop-in folder (`<repo>/plugins/`, `<workspace>/plugins/`) with `NAME`-based override and
  extension-stealing semantics. The folder shipped empty, and the override rules carried a documented
  gotcha (a same-`NAME` drop-in frees the original extensions silently). Coverage was 36 languages;
  the pack ships 371, so a Zig/Nim/Svelte/Solidity repo got `language="text"` and regex symbols.
  Adding 336 modules would have cost ~0.35 s of `importlib` startup per process — for shipped data.
  Two traps came with the expansion: the upstream table maps `.txt` to `vimdoc` and `.h` to `c`, and
  49 catalog languages declare no extension at all.
- **Decision:** `src/simple_code_indexer/languages/catalog.py` is a single generated
  `tuple[LanguageSpec, ...]`, produced by `tools/gen_language_catalog.py` from the pack's published
  language table. `registry.py` only indexes it; the `importlib` loader, the override machinery, and
  both `plugins/` folders are deleted. Deliberate deviations from upstream live in the generator as
  `EXT_OVERRIDES` (`.h`→`cpp`, `.m`→`objc`, `.tsx`→`tsx`) and `FILENAMES` (`CMakeLists.txt`,
  `Dockerfile`, `Makefile`, `.vimrc`). Language ids are pack grammar names (`csharp`, not `c_sharp`).
  The pack's own detector is never called at runtime.
- **Decision (data formats):** `catalog.DATA_FORMATS` names every serialization/documentation/VCS
  grammar, and those entries are **not registered**. Detection therefore returns `None`, the allowlist
  never contains their extensions, and the indexer cannot ingest them. This keeps the pre-existing
  "data formats are not indexed" rule and hardens it: a filename match still runs first, so
  `CMakeLists.txt` resolves to `cmake` even though `.txt` belongs to the denied `vimdoc` language.
- **Consequences:** Language coverage goes 36 → 322 indexable languages at zero startup cost, with no
  storage-format change. Symbols are not free: only ~29 languages have a curated node map or extractor.
  `symbol_lookup` now returns a `coverage` signal (`none`/`partial`/`full`) plus a hint when a language
  produced no symbols, and unmapped languages get one attempt through the pack's `process()` analysis
  (`SYMBOL_FALLBACK=0`, measured to name a symbol for 6 of 29 unmapped languages sampled). Prefetch is
  bounded to the symbol-mapped grammars so startup cannot trigger a ~370-grammar download storm.
  `catalog.VERSION` is stored in `meta` and drives a targeted reconcile (drop rows that are no longer
  allowed or whose stored language changed) rather than a full re-embed. Fixing a wrong mapping is now
  a generator edit plus regeneration, not a user drop-in — accepted because the folder was empty.
