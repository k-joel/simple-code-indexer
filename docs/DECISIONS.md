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
| [009](#adr-009-faiss-is-the-primary-vector-store-qdrant-opt-in) | FAISS is the primary vector store; Qdrant opt-in (superseded by ADR-017) |
| [010](#adr-010-gpu-aware-compose-and-model-prompt-templates) | GPU-aware compose and model prompt templates |
| [011](#adr-011-global-only-config-per-user-install-self-updating-launcher) | Global-only config, per-user install, self-updating launcher |
| [012](#adr-012-role-specific-per-workspace-log-files) | Role-specific per-workspace log files |
| [013](#adr-013-honor-gitignore-and-watch-the-workspace-root-recursively) | Honor `.gitignore` and watch the root recursively |
| [014](#adr-014-per-workspace-sidecar-writer--read-only-mcp-sessions) | Per-workspace sidecar writer + read-only MCP sessions |
| [015](#adr-015-global-harness-entries-carry-no-per-project-data) | Global harness entries carry no per-project data |
| [016](#adr-016-a-generated-language-catalog-replaces-the-plugin-folder) | A generated language catalog replaces the plugin folder |
| [017](#adr-017-sqlite-vec-is-the-default-vector-store-faiss-and-qdrant-opt-in) | sqlite-vec is the default vector store; FAISS and Qdrant opt-in |
| [018](#adr-018-mcp-roots-first-harness-published-workspace-third) | MCP roots first, harness-published workspace third |
| [019](#adr-019-pypi-distribution-uv-tool-install-replaces-the-git-copy-install) | PyPI distribution; `uv tool install` replaces the git-copy install |
| [020](#adr-020-symbol-maps-are-derived-from-the-packs-tags-queries-at-catalog-generation-time) | Symbol maps from the pack's tags queries |
| [021](#adr-021-embedded-regions-are-indexed-through-the-grammars-injections-query-opt-in-per-host) | Embedded regions via the grammar's injections query |
| [022](#adr-022-harness-entries-can-be-project-scoped-pinned-by-serve---workspace) | Harness entries can be project-scoped, pinned by `serve --workspace` |
| [023](#adr-023-embeddinggemma-2-is-the-default-model-and-the-sweep-defaults-to-300-s) | EmbeddingGemma 2 is the default model; the sweep defaults to 300 s |
| [024](#adr-024-flags-are-for-production-environment-variables-are-for-debugging) | Flags are for production, environment variables are for debugging |
| [025](#adr-025-harness-detection-probes-the-client-cli-with-a-directory-fallback) | Harness detection probes the client CLI, with a directory fallback |
| [026](#adr-026-the-harness-menu-prefills-from-the-recorded-selection-not-detection) | The harness menu prefills from the recorded selection |
| [027](#adr-027-absence-in-a-discovery-file-is-empty-content-never-a-missing-file) | Absence in a discovery file is empty content |
| [028](#adr-028-the-daemon-wakes-its-accept-loop-with-a-self-connection) | The daemon wakes its accept loop with a self-connection |


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
  through `vector_store.py`: sqlite-vec by default, FAISS and `qdrant-client` selectable (ADR-017).
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
- **Decision:** The server runs **on the host**, spawned by the harness. The workspace originally came from
  `Path.cwd().resolve()`, overridable with `WORKSPACE_ROOT`; ADR-018 extends the order to
  `WORKSPACE_ROOT` > MCP `roots/list` > harness-published workspace > cwd. No Docker image for the server
  ships in this repo. The index lives at `$WORKSPACE_ROOT/.simple-ci/index.db`; each workspace gets its own
  derived Qdrant collection `code_index_{slug}_{sha256(path)[:8]}_{dim}` on the Qdrant backend, and its own
  `vectors.faiss` on the FAISS backend.
- **Consequences:** One static harness snippet works for every project; `get_status.workspace` and
  `get_status.workspace_source` make the inference observable. `WORKSPACE_ROOT` is the escape hatch when a
  harness spawns servers from elsewhere and always wins. An inferred workspace that is the user's home
  directory is refused; an explicit pin or a client-published root opts in. Do not go back to
  `uvx --from <repo>` entries or a mounted container: the harness already starts the server inside (or, with
  ADR-018, tells it) the project, so the workspace needs no configuration.

## ADR-008: Setup wizard and fail-soft managed services

- **Context:** Every setting used to come from an environment variable, so a fresh clone required
  hand-editing a harness config with machine-specific paths and knowing which services to start. Nothing
  recorded which container backed an endpoint, so the server could not bring services up itself.
- **Decision:** One command, `simple-code-indexer setup`, is the install path: it installs `uv` when
  missing, installs the pinned wheel as a uv tool, and runs an
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
  still works and `get_status` reports the state. The original `git clone && python setup.py` entry point
  is gone (ADR-019); the bootstrap now lives in the package as `cli.py` + `install.ensure_uv`.

## ADR-009: FAISS is the primary vector store, Qdrant opt-in

**Status**: Superseded by ADR-017 (2026-11-18)

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

## ADR-011: Global-only config, one machine-wide settings file

- **Context:** Three problems: (1) the project-local config drifted from the deployment model, silently
  overriding the machine-wide embedding endpoint, while the only per-project setting was `vector_store`;
  (2) harness entries pointed at the source checkout (`uvx --from <repo>`), so updating the checkout changed
  behaviour without a version bump and deleting it broke every install; (3) `simple-term-menu` imports
  `termios` at module load and raises `NotImplementedError` on Windows.
- **Decision:** **One** config file, `~/.simple-ci/config.yaml` (`SIMPLE_CI_CONFIG` replaces discovery).
  Project-local configs are never read; the wizard merges a legacy one into the global file and removes it.
  Menus use `questionary`, with numbered `input()` prompts as the non-interactive fallback
  (`SIMPLE_CI_NO_TUI=1`).
- **Consequences:** `--scope` is gone (passing it is a parser error); `get_status.config_files` has 0 or 1
  entries. `vector_store` and `faiss.path` live globally, while the SQLite DB and FAISS file stay
  per-workspace, so isolation is unchanged. The wizard must configure the caller's cwd (the project being
  indexed) rather than its own location, so it resolves the workspace from cwd and reads the checkout
  separately. The installer and launcher wiring this ADR originally described is superseded by ADR-019.

## ADR-019: PyPI distribution; `uv tool install` replaces the git-copy install

- **Context:** The install model was "copy the git working tree into `%APPDATA%/simple-code-indexer` and let a
  `run_server.py` launcher `git pull` on every start". That is incompatible with publishing: a wheel contains
  only `src/simple_code_indexer/**`, so no `run_server.py`, no `.git`, no `uv.lock`. Three forces made the
  copy model actively harmful: (1) it required a git checkout as the distribution unit, which PyPI cannot
  express; (2) `git pull` at launch meant an unpinned, untraceable version served every session, the exact
  problem ADR-011 set out to fix; (3) `_default_repo_root()` fell back to `Path.cwd()` when no
  `pyproject.toml` was above the package, so from an installed wheel the wizard would have copied the
  *user's project* into the install directory.
- **Decision:** The **wheel is the distribution unit** and `uv tool install` is the install mechanism.
  `uvx simple-code-indexer setup` installs a pinned `simple-code-indexer==<version>` into the uv tool
  environment and writes harness entries that launch that environment directly:
  `<tool-env>/Scripts/pythonw.exe -m simple_code_indexer serve` on Windows (windowless, so a GUI harness
  gets no console window), `<tool-env>/bin/python -m simple_code_indexer serve` on POSIX. The console script
  is `simple-code-indexer` with subcommands `setup`, `install`, `serve`, `uninstall`, `status`, `version`;
  `serve` is the default so a bare invocation still starts the MCP server. There are two install flavours
  into that one environment: **editable** (`uv tool install --editable <checkout>`, the default whenever a
  source checkout is detectable) links the working tree, and **wheel** (`--wheel`, or any run without a
  checkout) builds/installs a real wheel — the prod-validation switch. Both leave the environment root and
  therefore the harness entry byte-identical; only the uv receipt (`editable = …` vs `directory = …`) records
  which is live. `--install-mode`, `checkout` mode and its `uv run --project` entry form are deleted.
- **Consequences:** Releases are tag-driven: `tools/release.py --bump` updates `pyproject.toml` + `uv.lock`,
  moves the CHANGELOG section, commits and pushes the tag; `.github/workflows/release.yml` builds once and
  publishes through PyPI Trusted Publishing (OIDC, no stored token). `pyproject.toml` is the source of truth
  for the version because `uv_build` needs static metadata — the tag must match it, and
  `release.py --verify-tag` enforces that as the first CI step. `run_server.py`, `copy_repo`, `sync_env` and
  `SIMPLE_CI_GIT_PULL` are deleted, along with every piece of the legacy install-copy
  machinery (`install_root`, `target_root`, `legacy_install_root`, `--install-dir`): a copy that
  predates this decision is simply left for the user to delete, never detected or removed by the
  wizard or `--uninstall`. `setup.py` is deleted too; `simple-code-indexer install` replaces its
  bootstrap, and the wizard finds a source checkout itself (`_default_repo_root`, which requires
  this package's own `src/` tree — it now decides *which tree gets linked*, so it must stay strict).
  Harness entries still carry no
  workspace data (ADR-015). Because `uvx` environments live in the uv cache, `uv cache clean` can strand a
  `uvx`-launched process; tool environments are unaffected, which is why entries launch one.

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
  `daemon.spawn.lock` and publishes a `daemon.spawn.json` claim with the child pid before releasing the
  lock, so concurrent readers wait for that daemon instead of racing a duplicate; the daemon acquires the
  writer lease *before* publishing `daemon.json` and owns the
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

## ADR-015: Global harness entries carry no per-project data

- **Context:** Every harness entry used to be written at **global** scope (ADR-011: one config file,
  one install, one entry set), and the workspace is inferred from the process cwd (ADR-007).
  Despite that, repeated debugging sessions hand-edited `WORKSPACE_ROOT` and `cwd` into the OpenCode,
  Goose and Pi entries, pinning this checkout's absolute path in files that belong to every project
  on the machine. The result was a global entry that silently indexed one fixed tree for every
  project opened afterwards, and a git-tracked repo path leaking into user-home config. The
  behaviour was even documented as a step (`references/mcp-test-process.md` §4.4) and as a harness
  capability (the three plugins emit `cwd` from `WORKSPACE_ROOT`), so each new session re-created
  it. ADR-022 later added an explicit *project* scope, so this rule is now stated per scope.
- **Decision:** A **global** harness entry contains **only** install-scoped data: the interpreter
  and the user's global settings. It must never contain a workspace path — no `WORKSPACE_ROOT`, no
  `--workspace`, no `cwd`, no `INDEX_DB`, no `FAISS_PATH`. Workspace resolution stays entirely
  runtime-inferred (ADR-007; ADR-018 adds roots and harness-published sources). Harness plugins
  therefore never turn `WORKSPACE_ROOT` into a `cwd`, and the wizard passes an empty `env`. One
  reserved key is allowed: `SIMPLE_CI_HARNESS=<NAME>`, a stable install-scoped marker that tells
  the server which plugin may publish this session's workspace. It carries no project data, so it
  does not reintroduce the pinning this ADR forbids. A **project** entry (ADR-022) is written into
  the workspace and *must* carry the pin, because that file belongs to one project by construction.
  A temporary pin in a *global* entry is allowed **only** inside a debugging session, and must be
  removed before the session's work is called done.
- **Consequences:** One static global entry set serves every project; moving or cloning a repo
  cannot leave a stale absolute path behind, and re-running setup is idempotent with respect to the
  workspace. `get_status.workspace` remains the way to detect a harness that spawns from elsewhere
  — the fix is a harness that spawns in the project cwd, not an entry edit. When a harness
  genuinely cannot spawn in the project directory, that is a harness defect to record in
  `docs/ISSUES.md`, or a case for the project scope in ADR-022.

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
  storage-format change. Symbol coverage was the gap this ADR left open — only ~29 languages had a
  curated node map — and [ADR-020](#adr-020-symbol-maps-are-derived-from-the-packs-tags-queries-at-catalog-generation-time)
  closes it by deriving maps from each grammar's tags query (167 languages) and recording the rest in
  `catalog.SYMBOL_GAPS`. `symbol_lookup` reports a `coverage` signal (`none`/`partial`/`full`) plus a
  hint when a language produced no symbols. Prefetch stays a bounded set (`catalog.PREFETCH`) so
  startup cannot trigger a ~370-grammar download storm. `catalog.VERSION` is stored in `meta` and
  drives a targeted reconcile (drop rows that are no longer allowed or whose stored language changed)
  rather than a full re-embed. Fixing a wrong mapping is now a generator edit plus regeneration, not a
  user drop-in — accepted because the folder was empty.

## ADR-017: sqlite-vec is the default vector store; FAISS and Qdrant opt-in

**Status**: Accepted
**Date**: 2026-11-18
**Deciders**: @k-joel, agent session (report `artifacts/report-vector-store-replacement.md`)

- **Context:** ADR-009 chose a separate `vectors.faiss` file because embedding vectors in SQLite needed an
  extension or an O(n) Python distance loop. That premise no longer holds: `sqlite-vec` 0.1.9 is a 0.29 MB
  wheel whose exact scan, tuned with `chunk_size=64` and `PRAGMA mmap_size`, measured 0.95 ms at this
  repo's 1.5k×768 scale (FAISS: 0.70 ms) and 22–65 ms at 10k–30k×2560 (FAISS: 5–16 ms), with identical
  recall. The separate file is what forces `vector_labels.dirty`, the atomic file replace, the reader
  reload cache, and the reconcile pass. Read-only `mode=ro` KNN was verified while a writer held an
  uncommitted WAL.
- **Decision:** `sqlite-vec` (`vector_store: sqlite-vec`) is the default backend. Vectors live in a
  `vec_chunks` virtual table inside `index.db`, `rowid` = the existing `vector_labels.label`, cosine
  distance converted to `1 - distance`. FAISS stays fully supported as the second option (unchanged
  code and dirty-flag semantics); Qdrant stays the third. `vector_store.py` is a registry of backend
  modules implementing one `STORE_CONTRACT`, with lazy imports, so adding a backend is one module plus
  one registry entry. `sqlite_vec.chunk_size` / `mmap_size` / `cache_size` are configurable
  (`SQLITE_VEC_*`), and the wizard probes that the interpreter can load the extension before offering it.
- **Consequences:** **Good**: one transaction covers labels and vectors, so there is no dirty-flag,
  flush-file, reload-cache, or reconcile machinery for the default backend; one file to back up; a
  smaller native dependency. **Bad**: sqlite-vec is pre-v1 and pinned to `>=0.1.9,<0.2`; the stable
  release is an exact O(n·d) scan, roughly 4× FAISS at 30k×2560 (~65 ms); changing `chunk_size` or
  `EMBED_DIM` rebuilds the table and re-embeds; interpreters without SQLite extension loading cannot use
  it at all. **Mitigations**: FAISS remains selectable for large workspaces or blocked interpreters (the
  wizard defaults to it when the probe fails); `mmap_size`/`cache_size` are tunable; a backend change
  invalidates the binding and re-indexes rather than migrating vectors, and a leftover `vec_chunks` table
  is dropped when another backend becomes active.

## ADR-018: MCP roots first, harness-published workspace third

- **Context:** The Command Code VS Code extension spawns stdio MCP children **without a `cwd`**
  (`shell: true`), so the server inherited the extension host's working directory
  (`C:\Program Files\Microsoft VS Code`) and indexed nothing (ISS-014). ADR-015 correctly forbids pinning a
  path in the global entry. The MCP protocol already has a first-class answer — `roots/list`, which every
  client advertises — but the installed SDK (`mcp>=2.3.0`) handles `initialize` inline with the read loop
  parked, so a server-initiated request cannot be awaited before the handshake, and the 2026-era protocol
  forbids server-initiated requests entirely. The extension advertises `roots` and then never answers the
  request, so roots alone cannot fix this client.
- **Decision:** Workspace sources are resolved in this order: `WORKSPACE_ROOT` > the client's first
  plausible `roots/list` `file:` directory > the launching harness's published workspace > process cwd.
  Because roots requires a session, `server.ServerState` defers `load_settings()`, the file log, and the
  writer/reader start until `notifications/initialized` (or the first `tools/*` call), with a bounded probe
  (`SIMPLE_CI_ROOTS_TIMEOUT_S`, default 1 s, `0` disables; skipped when `WORKSPACE_ROOT` is set, the client
  did not declare `roots`, or the connection has no back-channel). Harness-published workspaces are a
  **plugin hook**: an optional `resolve_workspace(cwd)` on a harness plugin, dispatched to the plugin
  named by the entry's stable `SIMPLE_CI_HARNESS=<NAME>` marker; the plugin owns all client-specific
  discovery. Only `harnesses/commandcode.py` implements it, reading `~/.commandcode/ide/*.json` and
  matching its `pid` against live ancestors (`parent_watch.ancestor_chain`) plus the IDE image name — never
  by file recency, because the files are not self-cleaning. An entry installed before the marker existed
  asks **every** resolver instead, but only when the cwd is implausible (the user home or a live
  ancestor's executable directory); a plausible cwd is never overridden, so a terminal launch keeps
  indexing where it was started. `get_status.workspace_source` and the startup banner report which
  source won.
- **Consequences:** A client that implements roots now controls the workspace without any discovery code
  in this repo; a client that advertises roots but drops the request costs one bounded timeout per
  session (the Command Code extension, today) and falls through to the harness source. A `run_server.py`
  code update is enough for an existing install: the marker is a fast path, not a prerequisite. Deferred
  startup moves the workspace refusal and the log-file setup from process start to session start; a
  server that never receives a handshake never opens an index, which is correct, and one that lands in
  an editor install or the home directory fails loudly instead of building an empty index. Discovery
  stays isolated: core code knows only the generic hook, the marker key, and the ancestor walk.

## ADR-020: Symbol maps are derived from the pack's tags queries at catalog-generation time

- **Context:** ADR-016 replaced the plugin folder with a generated catalog but kept only 29 curated
  `SYMBOL_NODES` maps, so 293 indexable languages produced no symbols at all (ISS-013). Hand-writing
  maps does not scale and does not stay correct: of 77 maps drafted by hand for this decision, 40
  named node types that do not exist in the installed grammar — `elm`'s `type_alias`, `fortran`'s
  `type`, `perl`'s `function_definition` had all been silently dead. The pack ships two authoritative
  sources per grammar that were both unused: a **tags query** (`get_tags_query`) — the grammar
  authors' own list of `@definition.*` / `@name` captures, which names the real declaration node
  types — and a `symbols=True` mode on `process()` that the fallback never enabled.
- **Decision:** `tools/gen_language_catalog.py` builds each language's map in three tiers, highest
  first: a hand-verified `SYMBOL_NODES` entry; the grammar's tags query, parsed as S-expressions and
  validated against the grammar's own node-kind table; and a shape heuristic over node-kind names
  (`*_definition`, `*_declaration`, `*_def`, …) for the ~225 grammars that ship neither. A node type
  the grammar does not have is a hard error in the generator, not a silent skip, so a pack rename is
  caught at regeneration. Name resolution moved into `parse._symbol_name`, which tries the name-bearing
  field conventions and then a bounded search that skips body/type/value fields, because grammars
  disagree on both the field (`name:`, `declarator:`, `function:`, `attrpath:`) and whether the name
  is nested. Languages that hold a declaration in a label list, block label, head symbol, or an
  enclosing assignment get an extractor instead of a map. `get_status` reports the residual
  `SYMBOL_GAPS`, and `catalog.PREFETCH` is a hand-picked bounded set so the map for most of the
  catalog cannot turn startup into a whole-pack download.
- **Consequences:** Symbol coverage goes 29 → 167 languages at zero runtime cost, and a pack upgrade
  is still a reviewable diff. The laws that follow: a map cannot fix a grammar whose declarations are
  found by neither a field nor a node-kind shape, so `SYMBOL_GAPS` (155 languages) is expected to stay
  non-empty; template hosts (`vue`, `svelte`, `astro`, `heex`) index no symbols from their embedded
  `<script>` blocks under this decision — [ADR-021](#adr-021-embedded-regions-are-indexed-through-the-grammars-injections-query-opt-in-per-host)
  closed that gap with an injection pass; and a map change must bump `SYMBOL_MAP_VERSION`, never
  `CATALOG_VERSION`, because the former triggers a symbols-only re-parse whereas the latter drops rows
  and forces a re-embed.

## ADR-021: Embedded regions are indexed through the grammar's injections query, opt-in per host

**Status**: Accepted
**Date**: 2026-11-22
**Deciders**: @k-joel, agent session (ISS-014)

- **Context:** ADR-020 closed symbol coverage for grammars whose declarations are their own nodes, but
  a whole class of languages declares nothing useful in the host grammar: Vue/Svelte/Astro component
  code lives in a `<script>` block, Heex in `<%= %>` directives, Blade in `@php`, Templ in a `script`
  block. Those regions are parsed by a *different* grammar and are reachable only through tree-sitter
  injections, which `extract_symbols` never ran. The pack ships an injections query per grammar
  (`get_injections_query`), but it is authored for syntax highlighting: it also targets CSS, comments,
  regexes, HTML, bash and doc comments, and one region can match several patterns.
- **Decision:** `parse.extract_from_tree` runs an injection pass for a language whose generated
  `LanguageSpec.injections` flag is set (`astro`, `blade`, `heex`, `svelte`, `templ`, `vue` — the hosts
  whose own grammar declares nothing). The target language comes from the pattern's
  `#set! injection.language` property or, for Svelte, from the capture name (`@javascript`,
  `@typescript`). Only code targets are indexed — `elixir`, `javascript`, `php_only`, `typescript` —
  and a region matching several patterns is deduplicated by span, keeping the more specific language
  (TypeScript over JavaScript). Symbols are shifted by the region's start line, so they point at the
  host file. `php_only` is not a pack grammar and is parsed through `php` behind a `<?php ` prefix; a
  `<script lang="ts">` upgrades the hard-coded `javascript` target to `typescript`, because the
  JavaScript grammar turns `interface`/`enum`/generics into ERROR nodes. The pass recurses only through
  `_extract_local`, so a host's injections are never followed twice. Twig and Jinja get extractors
  instead of injections, because their declarations are template tags rather than embedded code.
- **Consequences:** Symbol-mapped languages go 167 → 174 and `SYMBOL_GAPS` 155 → 148, with no schema
  or storage change; `SYMBOL_MAP_VERSION` is bumped so existing indexes re-parse once. The cost is one
  extra query match and a re-parse per embedding file, and the injection pass is deliberately not
  applied to every one of the 142 grammars that ship a query: a highlighting query targets CSS,
  comments, and regexes too, so enabling it wholesale would index selectors and comments as symbols.
  Heex `<script>`/`<style>` tags stay unindexed because their query captures the whole tag and its
  `#offset!` directives are not exposed by the binding; the limitation is recorded rather than
  worked around with a host-specific offset table.

## ADR-022: Harness entries can be project-scoped, pinned by `serve --workspace`

- **Context:** Global-only entries (ADR-015) rely on the client spawning the server in the project
  directory. That is true for most terminal clients, but not for an IDE extension whose stdio
  children inherit the editor's install directory (ISS-014), and some clients read a
  project-level config anyway — OpenCode, Claude Code, Cursor, VS Code, Codex, Pi, MiMo and
  Windsurf all do. Users also asked for an index that belongs to one repository, listed in that
  repository's own config, without touching every other project on the machine. The earlier answer,
  a `--scope` flag, was deleted with ADR-011 because it selected a *settings* file; the settings
  file stays global.
- **Decision:** `setup` asks for a **harness scope** after the harness selection:
  `global` (default) or `project` (the current workspace). Running from the home directory always
  means global, because that is where a bare `uvx … setup` lands and a home-scope entry would
  index all of `$HOME`. A project entry is written to the client's project config file
  (`harnesses/<client>.py: LOCAL_CONFIGS`) and carries the pin `serve --workspace <abs workspace>`;
  a global entry never does. `WORKSPACE_ROOT` still wins over the argument, which wins over MCP
  roots, the harness-published workspace, and cwd, and `get_status.workspace_source` reports
  `env` / `arg` / `roots` / `harness:<name>` / `cwd`. `--workspace` is a serve-only flag: it is
  parsed in `cli._serve`, deliberately absent from the argparse help of the other subcommands, and
  treated like `WORKSPACE_ROOT` as an explicit opt-in for the implausible-directory refusal.
  Entries are written by the client's own `mcp add` CLI when the plugin declares one
  (`CLI_BINARIES` / `cli_add` / `cli_remove`), falling back to the wizard's config merge, and
  finally — for a client with no project config at all (Goose, Claude Desktop) — to its **global**
  entry plus a warning. A CLI that writes somewhere other than the plugin's config paths declares
  `cli_target` / `cli_root_key` (Cursor's `--add-mcp` edits the profile settings under
  `mcp.servers`); such a file must **not** also appear in `GLOBAL_CONFIGS`, or the merge path would
  write the wrong root key into it. On Windows the ladder runs the path `shutil.which` resolved and
  routes `.cmd`/`.bat` shims through `cmd /c`, because `subprocess` cannot execute a batch file and
  every shim-based client would otherwise fall back silently.
  `enabled: true` is emitted only for clients that document the key (Codex,
  Pi, Goose, MiMo, Command Code); OpenCode uses `disabled` and its entry must not carry `enabled`.
  After a project write the wizard offers to add the config file and `.simple-ci/` to
  `.gitignore`, because a pinned entry is machine-specific.
- **Consequences:** A global entry stays workspace-free, so ADR-015 continues to hold where it
  matters. A project entry is per-machine by design: it must be gitignored, and a teammate cloning
  the repo runs `setup` themselves. `setup.harnesses` records `scope` and `workspace`, so
  `--install-only` repoints the same file with the same pin and a deselect removes the entry where
  it was written; records from before this ADR default to `global`. Adding a client means adding
  its project path and — only if it ships a non-interactive `mcp add` — a `cli_add` in its own
  plugin module; the wizard has no per-client branches. A client that requires interactive
  approval for project servers (Claude Code) or project trust (Codex, Pi) still connects only after
  the user grants it, which no config writer can shortcut.

## ADR-023: EmbeddingGemma 2 is the default model; the sweep defaults to 300 s

**Status**: Accepted
**Date**: 2026-11-27

- **Context:** The defaults were sized for the largest supported model: `EMBED_DIM` defaulted to
  2560 and the wizard suggested `Qwen3-Embedding-4B-Q6_K` for any endpoint or container it did not
  provision itself. That made the zero-config path depend on a 3.3 GB download and a 2560-wide
  vector table, even though EmbeddingGemma 2 is already the first catalog entry (0.6 GB, 768-dim)
  and the model the README and benchmarks use. Separately, the wizard's suggested sweep interval
  was 45 s while the runtime backs off to a 600 s cap, so the suggested value mostly exercised the
  backoff rather than reconciling at a steady cadence.
- **Decision:** `embedding.model` / `EMBED_MODEL` defaults to `embeddinggemma-2` and
  `embedding.dim` / `EMBED_DIM` to 768, matching the existing first catalog entry; the wizard's
  `DEFAULT_EMBED_MODEL` / `DEFAULT_EMBED_DIM` for a bare URL or container follow. `DEFAULT_SWEEP_SECONDS`
  (the interval the wizard offers when the sweep is enabled) is 300 s. The sweep *question* still
  defaults to no, and an existing `config.yaml` keeps its recorded model, dimension, and interval.
- **Consequences:** The fallback path no longer assumes a model the user did not download, and a
  fresh `setup --yes` and the docs agree. The default is only a fallback: load precedence is
  unchanged, so a config file or environment variable still wins, and no existing index is migrated
  — a dimension change invalidates the vector binding and re-embeds (the normal identity rule, not
  a new one). A 768-dim table is also ~3× smaller and cheaper to scan than 2560.

## ADR-024: Flags are for production, environment variables are for debugging

**Status**: Accepted
**Date**: 2026-11-27

- **Context:** A generated harness entry injected `SIMPLE_CI_HARNESS=<NAME>` into its `env` block,
  and the server wrote `WORKSPACE_ROOT`/`INDEX_DB` into a spawned daemon's environment. Both were
  invisible in the client's own config (a user reading `.mcp.json` could not tell why the server
  picked a workspace), easy to forget when hand-writing an entry, and unreadable in a process
  listing. Environment variables were also a mix of prefixed (`SIMPLE_CI_CONFIG`,
  `SIMPLE_CI_MODE`) and bare names (`WORKSPACE_ROOT`, `INDEX_DB`, `EMBED_*`, `LOG_LEVEL`,
  `SQLITE_VEC_*`, `PREFETCH_GRAMMARS`, `SYMBOL_FALLBACK`), so a `LOG_LEVEL` or `MODE` in a process
  environment could not be attributed to this project at all.
- **Decision:**
  1. **Every setting has a parallel CLI argument.** A generated entry carries arguments, never
     environment variables: `serve` reads `--workspace`, `--harness` and `--index-db`, and the
     wizard builds an entry's argv in exactly one place (`entries.launch_argv`). A builtin plugin's
     `entry()` receives an empty `env`, so a written entry has no `env` block; `entries.verify`
     reports one that does, whichever key the client uses (`env`, `environment`, `envs`).
  2. **`--harness <NAME>` replaces the `SIMPLE_CI_HARNESS` entry key.** It names the plugin allowed
     to publish a session's workspace (ADR-018). The variable is still *read* as a debug and
     pre-ADR-024 fallback — the flag wins — so an older entry keeps resolving.
  3. **Every variable of ours is prefixed `SIMPLE_CI_`, and only that spelling is read.**
     `simple_code_indexer/env.py` is the only seam (`env.get("LOG_LEVEL")` reads
     `SIMPLE_CI_LOG_LEVEL`), imports nothing from the package, and is shared by `config`,
     `mcp_roots`, `registry`, `parse` and the sidecar. There is no bare-name fallback: the
     rename is complete, and honouring the old spelling would keep a second vocabulary alive and
     make "what do we read?" unanswerable from the code. A stale shell profile is fixed by renaming
     the variable. Third-party names (`COMSPEC`, `ProgramFiles`, `HF_TOKEN`, `XDG_RUNTIME_DIR`,
     `APPDATA`, `LOCALAPPDATA`, `HOME`, Cline's own `CLINE_*`) are never renamed.
  4. **A child process is production.** The sidecar daemon is spawned with `--workspace` and
     `--index-db` arguments, not with `WORKSPACE_ROOT`/`INDEX_DB` in its environment.
- **Consequences:** An entry is self-describing: what it does is what it says, and it survives being
  copied between clients. The flag parser stays hand-rolled and tolerant (`cli._flag_arg`, last
  occurrence wins), because `serve` must still ignore unknown arguments — stdout is the MCP
  transport. Env vars remain the fast path for a one-off debug session and for tests, and stay
  documented as such. A new knob must ship a flag (or be `config.yaml`-only); a knob that exists
  only as an env var is a review failure. `status` deliberately has no `--harness`/`--index-db`
  flags: it is a terminal command and `parse_known_args` ignores them.

## ADR-025: Harness detection probes the client CLI, with a directory fallback

**Status**: Accepted
**Date**: 2026-11-27

- **Context:** The wizard preselected a harness when one of its `HOME_DIRS` existed *or* a `BINARIES`
  name was on `PATH`. Directory existence survives uninstall — `~/.cursor`, `~/.config/kilo` and
  friends are commonly left behind — so the menu offered harnesses that were gone. `PATH` lookup
  alone is not proof either, and it is actively wrong for names that belong to another tool: `zed`
  on `PATH` is usually authzed's SpiceDB CLI, and `cmd` on Windows is the shell.
- **Decision:** `HarnessSpec.detection()` resolves the plugin's binary, runs it with `PROBE_ARGS`
  (default `--version`) under a 10 s cap, and treats a zero exit as the strong signal (`cli`). A
  binary that is merely on `PATH` is the weaker `binary`, and a present directory under `HOME_DIRS`
  is `dir`. The three are **ORed**, never exclusive, and the winning reason is shown in the menu
  (`— detected: cursor --version` / `— detected: config dir .cursor`) and by
  `setup --harnesses`. Plugins may override `PROBE_ARGS`; declaring a binary is opt-in, so a
  client whose executable is a GUI that would open a window on `--version` declares none (Claude
  Desktop, Zed) and is detected by directory. The probe lives in
  `harnesses/_probe.py` behind a `Runnable` protocol (`which`/`run`), so the wizard's
  `provision.Runner` and its test fake drop in with no `harnesses → setup_wizard` import. Windows
  `.cmd`/`.bat` shims are routed through `cmd /c` by the shared `spawnable()`, because `subprocess`
  cannot execute a batch file.
- **Consequences:** A stale directory can still produce a false positive, which is accepted
  deliberately: a false *negative* hides a real harness and cannot be corrected from the menu,
  while a false positive costs one unchecked box. Extension-only harnesses (Kilo and Cline inside
  an editor, with no CLI on `PATH`) remain preselectable. The cap is 10 s because an npm-installed
  CLI behind a Windows shim needs 2–4 s to answer (measured: `openclaw` 4.2 s, `command-code`
  2.1 s); a wizard run probes up to 17 harnesses, so a silent binary costs the cap once and then
  falls through to `binary`/`dir`.

## ADR-026: The harness menu prefills from the recorded selection, not detection

**Status**: Accepted
**Date**: 2026-11-27

- **Context:** Preselecting detected harnesses is right for a first run and wrong for a re-run: a
  user who deliberately installed only two of five detected clients had to untick the other three
  on every `setup`, and a client that was temporarily uninstalled (or whose probe started failing)
  silently dropped out of the preselection.
- **Decision:** `setup.harnesses` in the global config is the record of what the user chose, and it
  wins: when it is non-empty the menu preselects exactly those names, whatever detection says. Only
  a first run — or a config that records nothing, e.g. after `--harnesses none` — preselects the
  detected set. `--harnesses <value>` still overrides both. The menu leads with two shortcut rows,
  "Select all detected" and "Unselect all", handled after the answer with *unselect* taking
  precedence so clearing is never silently ignored, and the numbered fallback gained the matching
  `all-detected` and `none` tokens. `--harnesses` with no value is a read-only report of every
  plugin's proof, config path and scope; it exits before any prompt or write.
- **Consequences:** A re-run is stable and reflects intent rather than the machine's current state,
  and a user who wants newly installed clients re-detected clears the selection once (or deselects
  and re-adds). The two meanings of `--harnesses` — bare lists, valued selects — are distinguished
  by an argparse `nargs="?"` sentinel, and combining the bare form with `--uninstall`/`--install-only`
  is a parser error so the read-only path can never be mistaken for an action.

## ADR-027: Absence in a discovery file is empty content, never a missing file

**Status**: Accepted
**Date**: 2026-11-27

- **Context:** `daemon.json` and `daemon.token` are how a reader finds its writer. Readers poll the
  ready file continuously, and on Windows an open read handle denies `unlink` (`FILE_SHARE_DELETE` is
  not granted by `Path.read_text`), so the daemon's shutdown-side delete failed often enough that a
  stale file outlived the process it described — the reader then kept "connecting" to a dead
  endpoint. Treating a delete failure as fatal is not an option: the file is best-effort state and
  no reader can be asked to stop polling first.
- **Decision:** every discovery write is a temp file plus `os.replace`, and every clear goes through
  `paths._clear`: delete, else truncate to empty. Empty content is the documented absence signal —
  `read_ready` and `read_spawn_claim` reject it, `read_token` returns `None` — so "the daemon is
  gone" is represented by content, not by `Path.exists()`. `read_ready` remains the only liveness
  check callers use.
- **Consequences:**
  **Good:** a clear succeeds regardless of concurrent readers, so a dead daemon can never keep
  looking alive; the same rule covers the token and the spawn claim, and a kill -9 still leaves a
  file the next reader corrects by pid-liveness.
  **Bad:** an empty leftover file stays on disk until the next daemon overwrites it, so a manual
  `ls` can show a "present" file that means nothing, and `Path.exists()` is no longer a valid
  liveness probe anywhere in this module.
  **Mitigations:** ARCH §2.1 states the contract and NOTES carries the do-not-simplify warning;
  `tests/test_sidecar_protocol.py` pins the truncating clear against a simulated sharing violation.

## ADR-028: The daemon wakes its accept loop with a self-connection

**Status**: Accepted
**Date**: 2026-11-27

- **Context:** `SidecarDaemon` accepts control connections on a dedicated thread and stops it with
  `join`. `Listener.close()` does not interrupt a thread already parked in `accept()`: the Windows
  `PipeListener` keeps its pending pipe handle open, and a POSIX socket close is not a reliable
  wake either. Every shutdown therefore waited out the full 2 s join timeout, which also kept the
  stale discovery file pollable for longer than the idle grace period.
- **Decision:** `_stop_accepting` connects to its own endpoint with the current token, then closes
  the listener. `_accept_loop` checks the stop event after `accept()` returns, closes the connection
  and exits, so the wake-up is never registered as a session. The listener is passed to the thread
  instead of read from a mutable attribute, and the connect runs on a bounded daemon thread
  (`_WAKE_TIMEOUT_S`) because `multiprocessing.connection.Client` has no connect timeout of its own.
- **Consequences:**
  **Good:** shutdown is deterministic and ends within the grace period plus process teardown, with
  no timeout tuning and no platform branch; a partly written connection is harmless because the
  daemon is already draining.
  **Bad:** the daemon must be able to authenticate to itself, so the token has to exist until
  `_stop_accepting` has run, and if the accept loop already died the wake costs its one-second cap
  before the old close-and-join path finishes the job.
  **Mitigations:** discovery is cleared before the runtime stops,
  `test_daemon_shutdown_is_not_delayed_by_its_own_accept_loop` fails if the join ever stalls again,
  and `test_stop_accepting_is_bounded_when_nobody_accepts` pins the cap.

