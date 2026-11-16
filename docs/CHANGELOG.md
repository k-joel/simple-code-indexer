# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
CHANGELOG.md MAINTENANCE GUIDE (FOR AGENTS & CONTRIBUTORS)

PURPOSE & SCOPE
- Curated, reverse-chronological record of notable, user-visible changes per version.
- Audience: human end users, operators, and developers evaluating upgrades or diagnosing
  regressions—not a git commit dump or internal engineering diary.
- Portable source of truth: reuse release sections from this file for GitHub Releases.

UPDATE TRIGGERS
- Update `## [Unreleased]` in the same task/session whenever you add a user-visible feature,
  change existing behavior/API/CLI/config/defaults, deprecate or remove functionality, fix a
  user-facing bug, or patch a security vulnerability.
- Update on release: promote `## [Unreleased]` to a versioned section and open a new
  `## [Unreleased]` section above it.
- Update post-release only to mark a pulled release `[YANKED]`, record a missed release or
  breaking change, or fix typos/broken links.
- Before ending a session that altered user-facing behavior, verify `## [Unreleased]`
  captures every qualifying change.

INCLUSION / EXCLUSION CRITERIA
- Include: Every notable user-visible change (features, behavior changes, deprecations,
  removals, bug fixes, security fixes). Consistency is mandatory—an incomplete changelog
  misleads users relying on it as the source of truth.
- Exclude: Whitespace/formatting edits, pure internal refactors with no behavior change, merge
  commits, work-in-progress steps, routine CI tweaks, and raw `git log` entries.

STRUCTURE & FORMATTING
- Section order: `## [Unreleased]` at the top, followed by releases newest-first
  (`## [X.Y.Z] - YYYY-MM-DD`). Never skip a released version.
- Dates & Versions: Strict ISO 8601 dates (`YYYY-MM-DD`) and SemVer (`MAJOR.MINOR.PATCH`:
  breaking / backward-compatible feature / backward-compatible fix). Append `[YANKED]` to
  pulled releases (`## [X.Y.Z] - YYYY-MM-DD [YANKED]`).
- Categories: Under `## [Unreleased]` and each release, group bullets strictly under these
  six `###` headings in order, omitting any empty category:
    - `Added`      (new features)
    - `Changed`    (changes to existing functionality)
    - `Deprecated` (soon-to-be-removed features)
    - `Removed`    (now-removed features)
    - `Fixed`      (bug fixes)
    - `Security`   (vulnerability fixes and security-relevant changes)
- Reference links: Keep reference-style links at the bottom of the file so every heading
  links to its comparison diff or tag (`[unreleased]` -> `vLATEST...HEAD`, `[X.Y.Z]` ->
  `vPREV...vX.Y.Z`, initial `[X.Y.Z]` -> `releases/tag/vX.Y.Z`).

QUALITY & STYLE RULES
- Describe user-visible impact, not internal implementation; name the specific feature,
  endpoint, flag, setting, or behavior affected.
- Keep bullets concise (1-2 lines), match audience tone, maintain consistent tense across
  entries, and end every bullet with a period.
- Evidence rule: Document only changes actually implemented and verified in the code/diff;
  never record speculative, planned, or unverified work.
- Link to the relevant issue, PR, commit, or ADR where helpful (and credit contributors if
  appropriate).
- Good: `- Login timeout on mobile caused by premature token expiry. ([#456](https://github.com/org/repo/issues/456))`
- Bad:  `- Refactored session handler.` or `- Various bug fixes and improvements.`

LIFECYCLE & WORKFLOW
- Ongoing edits: Add entries to `## [Unreleased]` as changes land, not only at release time.
- Deprecations & Breaking Changes: Deprecate in an earlier release before removing so users
  have a safe upgrade path. Prefix breaking changes and removals with `**BREAKING:**`, state
  the replacement, migration path, and deadline, and pair with a `MAJOR` version bump.
- Release-day workflow:
  1. Confirm `## [Unreleased]` captures all notable changes since the last release.
  2. Choose next `X.Y.Z` per SemVer.
  3. Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`.
  4. Insert a fresh empty `## [Unreleased]` section directly above it.
  5. Update bottom reference links (`[unreleased]` -> `vX.Y.Z...HEAD`; add `[X.Y.Z]`).
  6. Review wording, `**BREAKING:**` prominence, and links before tagging.
- Yanks & Corrections: Never silently delete a pulled release—keep it and append `[YANKED]`.
  Only rewrite past releases to add missed releases/breaking changes, fix typos, or repair
  broken links; never erase history.

ANTI-PATTERNS
- Dumping `git log` / raw commit messages or vague bullets ("bug fixes", "improvements").
- Ambiguous regional dates (`03/04/26`), empty `###` headings, skipped versions, or mixed
  formatting/tenses across releases.
- Silent breaking changes/removals without deprecation notice or migration instructions.
- Silently deleting yanked releases or selectively omitting notable changes.

EXAMPLE LAYOUT (4-SPACE INDENTED)

    ## [Unreleased]

    ### Added

    - User profile export in JSON format via `/v2/export`. ([#489](https://github.com/org/repo/pull/489))

    ## [2.0.0] - 2026-03-15

    ### Removed

    - **BREAKING:** Legacy `/v1/export` endpoint. Migrate to `/v2/export`.

    ### Fixed

    - Login timeout on mobile devices during token refresh. ([#456](https://github.com/org/repo/issues/456))

    ## [1.0.1] - 2026-02-01 [YANKED]

    ### Security

    - Patched token validation bypass in OAuth callback.

    [unreleased]: https://github.com/org/repo/compare/v2.0.0...HEAD
    [2.0.0]: https://github.com/org/repo/compare/v1.0.1...v2.0.0
    [1.0.1]: https://github.com/org/repo/compare/v1.0.0...v1.0.1
    [1.0.0]: https://github.com/org/repo/releases/tag/v1.0.0
-->

---

## [Unreleased]

### Added

- `docs/RUNBOOK.md`: numbered operator procedures (`RUN-001` upward) for service probes, the
  quality gate, live MCP verification, index rebuilds, sidecar shutdown, and log reading. The
  file header carries the maintenance contract and the evidence rules for new entries.
- Per-workspace sidecar writer daemon (ADR-014). Every harness still spawns its own
  stdio MCP server, but those servers are now **readers**: one detached daemon owns
  `index.db`, `vectors.faiss`, the Qdrant collection, the watcher, the writer thread,
  the sweep timer, and the managed Docker services. Multiple harnesses in one workspace
  all get working tools. The daemon exits after the last registered session plus
  `idle_grace_s` (default 60 s) and is respawned by the next session.
- `mode` (`sidecar` by default, or `embedded`), `idle_grace_s`, and `heartbeat_s` in
  `config.yaml`; `SIMPLE_CI_MODE`, `IDLE_GRACE_S`, and `HEARTBEAT_S` override them.
  `mode: embedded` restores the old single-process writer.
- `get_status` now reports `role` (`reader`/`writer`), `index_ready`, `writer_pid`,
  `writer_ok`, `writer_heartbeat_age_s`, `writer_log_file`, `daemon_endpoint`,
  `sessions`, `harnesses`, and `vector_index_age_s`.
- The sidecar daemon logs to `<workspace>/.simple-ci/log/writer.log` and reader sessions
  to `reader.log`; `mode: embedded` uses `embed.log`. All three use the same
  `log.max_bytes` / `log.backups` rotation. `reader.log` is shared by readers, so its
  rotation is best-effort.
- Harness plugins for **Goose** and **Pi**. Goose is written to its YAML
  `%APPDATA%\Block\goose\config\config.yaml` (or `~/.config/goose/config.yaml`) under
  `extensions.<name>` with `type: stdio`, `cmd`, `args`, `envs`; Pi is written to
  `~/.pi/agent/mcp.json` (or `.pi/mcp.json`) under `mcpServers` with `exposure: direct` so the
  three tools are declared to the model. Harness plugins can now use `FORMAT = "yaml"` in
  addition to JSON and TOML.
- OpenCode entries now set `codemode: false`, so the three tools are exposed directly instead
  of through Code Mode.
- Sidecar lifecycle logging: the daemon logs each client hello (`sidecar client connected`), each
  `REGISTER`/disconnect with the live session and harness list, the configured idle grace and
  heartbeat, and `sidecar stopped`; readers log their session id, workspace, harness process,
  registration, unregistration, and close. `reader.log` remains shared by every reader in the
  workspace.
- `setup.py` asks whether to run a periodic reconciliation sweep (default: no) and accepts
  `--sweep-seconds N` for non-interactive runs. `get_status` reports the configured interval as
  `sweep_seconds` (0 = sweeps off).
- `setup.py --no-git-pull` (debug): write `SIMPLE_CI_GIT_PULL=0` into the harness
  entries so the installed launcher skips its `git pull`, for testing the installed
  snapshot. With `--install-only` it also rewrites the entries already recorded in
  `setup.harnesses`.
- `setup.py --install-only`: copy this checkout to the per-user install directory and exit,
  without prompts, config, services, harness entries, or an environment sync of the copy.
  `--install-dir` and `--dry-run` are honored.
- `ref-docs/mcp-test-process.md`: a repeatable end-to-end MCP integration test that installs
  from scratch, hands the live session to a secondary harness agent, and verifies indexing,
  retrieval and shutdown.
- Harness lifecycle watchdog: the server now exits when a process in its launch chain
  disappears (uv's venv trampoline and uv launcher included), so a harness that keeps the stdio
  pipe open can no longer leave the server sweeping after the harness dies.
  `SIMPLE_CI_PARENT_WATCH=0` disables it. Verified end-to-end against OpenCode 2.2.5: closing the
  desktop UI stopped the server in ~2 s even though `opencode-cli serve --service` stayed alive
  and the stdin pipe never closed.
- `get_status` now reports `vectors_indexed` and `pending_embeddings`, and semantic
  `search_code` responses include `ready`, `pending_embeddings`, and a `message` while vectors
  are still being written. A semantic query fired during indexing now says the index is warming
  up instead of silently returning `hits: []`.

### Changed

- Documentation: `docs/ARCH.md` is now the live architecture overview — topology, data flow,
  domain/data model, component design, and testing — replacing the retired technical-design
  document.
  Individual decisions stay in `docs/DECISIONS.md` and structural debt in
  `docs/ARCH_ISSUES.md`. The domain glossary moved to `docs/GLOSSARY.md`, and all references
  were updated.
- Architecture decision records are consolidated into a single
  [docs/DECISIONS.md](DECISIONS.md), compressed to Context / Decision / Consequences. The
  `docs/adr/` folder is gone; the superseded all-in-one-process entry was folded into the
  sidecar decision and the rest renumbered 001–014.
- Runtime logs are split by role: `embed.log` (`mode: embedded`), `writer.log` (sidecar
  daemon), and `reader.log` (sidecar MCP readers), all with the same rotation settings.
  The old `sci.log*` files are no longer written or rotated; delete them by hand.
- The default runtime is now the sidecar topology: the MCP server is a read-only query
  process, and one daemon per workspace performs all indexing. Closing one harness no
  longer affects another, and the index stays fresh while any session is attached.
  Set `SIMPLE_CI_MODE=embedded` (or `mode: embedded`) to keep the old all-in-one process.
- Readers reload the published FAISS file when its mtime/size changes and validate (but
  never create) the Qdrant collection. A reader that starts before the index exists
  returns empty results with `ready: false` instead of crashing.
- The periodic reconciliation sweep is now opt-in and **off by default** (`sweep_seconds: 0`).
  The file watcher is the primary index path; the startup reconcile still runs once at server
  start. When enabled, the interval doubles while the workspace is idle — no watcher events or
  an empty sweep — up to 10 minutes, and resets on activity. With sweeps off, a dormant timer
  temporarily runs them only while chunks are waiting for embeddings, stopping again once none
  are pending, so a transient embedding outage still heals without a full walk every minute.
- Chunks are now 30-line windows with 15-line overlap instead of 80-line blocks. The
  embedding model mean-pools each input, so focused windows retrieve markedly better:
  on the 42-query benchmark R@1 rose 0.667 → 0.786, R@5 0.952 → 1.000, R@10 0.976 → 1.000,
  and nDCG@10 0.746 → 0.870. The chunker profile is part of the vector identity, so the
  first start after upgrading automatically re-embeds the workspace.
- Semantic search de-duplicates overlapping chunks: it over-fetches vector hits and drops
  any hit whose line range overlaps a higher-ranked chunk from the same file, so the
  overlapping windows do not crowd the top-10 with near-duplicates.
- Harness entries launch the installed copy through
  `uv run --project <install> --no-sync python <install>/run_server.py` instead of
  hardcoding the copy's `.venv\Scripts\python.exe`. `--project` preserves the caller's
  cwd, so workspace inference is unchanged.

### Fixed

- Harness entries no longer contain per-project paths. The OpenCode, Goose, and Pi plugins used to
  turn a `WORKSPACE_ROOT` value into an entry `cwd`, and debugging sessions hand-pinned
  `WORKSPACE_ROOT` into global entries — so one project's absolute path became the workspace for
  every project opened afterwards. Entries are now install-scoped only ([ADR-015](DECISIONS.md#adr-015-harness-entries-are-global-only-no-per-project-data));
  the workspace comes from the harness spawn cwd as before.
- Windows no longer opens stray console windows when a harness starts the MCP server. Recent
  harness entries launched `uv.exe`, and the sidecar daemon was spawned with `DETACHED_PROCESS`;
  both left console-subsystem children to allocate a visible window that stayed for the life of
  the process. On Windows the entry now runs the venv's windowless `pythonw.exe` directly, the
  daemon uses `CREATE_NO_WINDOW`, and `run_server.py`/Docker child processes are spawned with the
  same flag. A reader also waits for the daemon it just started instead of spawning duplicates
  during a slow startup, which was the source of the extra windows that flashed and closed.
- **ISS-11:** a second harness in the same workspace no longer exits with
  `another simple-code-indexer already owns …`. Its MCP server runs as a reader, attaches
  to the workspace daemon (or spawns it), and keeps all tools available when another
  harness closes.
- Shutdown now flushes the vector store while the workspace writer lease is still held, and
  finalization is idempotent. A server starting immediately after another exits can no longer
  race the old process's FAISS write and dirty-flag clear, which could silently drop vectors.
  A failure during startup after the lease is acquired also releases the lease.
- The lifecycle watchdog now watches only the harness process that owns the stdio session,
  skipping the `uv` launcher and venv `python.exe` trampoline. A reused
  `opencode-cli serve --service` — started by an earlier UI and shared by the next one — *is*
  the harness, so the server no longer depends on a UI ancestor that may be missing: it exits
  with the service instead of outliving it. `SIMPLE_CI_PARENT_WATCH=0` still disables the
  watchdog.
- `symbol_lookup` with an empty or whitespace-only `symbol` returns no matches instead of
  treating it as a wildcard and returning every indexed symbol.
- The watcher no longer logs events from ignored directories or its own log file, so an idle
  server no longer grows the active log file in a self-triggering loop. Ignored paths (including
  the active log file) are dropped before any event logging.
- The watcher and `index_one_file` now honor ignored **directories** for nested paths: every
  ancestor directory is checked before the path itself, so a deeper `.gitignore` negation
  (`!keep.py`) cannot re-include a file under a root-ignored tree such as `artifacts/`.
- Semantic search now finds the ignored-directory pruning logic: the query
  "how does the indexer avoid walking into virtualenv and cache directories" returns
  `indexer.py:106-135` (the `os.walk`/`dirnames[:]` loop) at rank 1. The 80-line chunk
  that mixed the whole function with unrelated code scored 0.68 against the query, while
  focused windows score 0.80; the query is now part of `tests/retrieval_queries.json`
  (`q42-walk-pruning`).
- The file watcher now uses a single recursive watch on the workspace root instead of one
  watchdog watch (and thread/handle) per directory, so large workspaces with thousands of
  `bin/`/`obj/` directories no longer exhaust threads and memory.
- The indexer and watcher honor workspace `.gitignore` files (root and nested), so ignored
  files are no longer indexed or watched. `get_status` reports the last sweep's
  `ignored_dirs` and `ignored_files`.
- Embedding requests no longer stall ~1 s each on Windows: the client rewrites loopback
  URLs to `127.0.0.1` instead of letting `localhost` resolve to the dead `::1` address
  first. The wizard probes and the managed-service readiness probe use the same helper.
- The llama.cpp compose template now sets `LLAMA_ARG_BATCH` / `LLAMA_ARG_UBATCH` (this
  build ignores the old `_SIZE` names), so the intended 2048 physical batch is applied
  instead of silently falling back to 512 and rejecting longer inputs.
- `tests/mcp_probe.py` and `tests/live_watch_probe.py` no longer hang when the server fills its
  stderr pipe: the child's stderr is drained on a thread, and `PROBE_TIMEOUT` (default 180 s)
  bounds the run so a stall fails instead of blocking forever.
- Embedding requests are split into batches of at most 16 inputs with at most two in flight per
  process, and retries use full-jitter exponential backoff. A bulk reindex in one workspace no
  longer starves another workspace's request on the shared embedding endpoint; N open
  workspaces still multiply the load.
- `tests/retrieval_bench.py` no longer deletes the live workspace index: a new `--local-path DIR`
  writes `index.db` and `vectors.faiss` into `DIR` instead of `<workspace>/.simple-ci`, and a
  `--reset` that would still hit the live index prints a warning naming the file.
  `tests/bench_matrix.py` gives every run its own scratch folder under
  `artifacts/bench/<timestamp>/local/`.
- Qdrant benchmark runs are isolated too: with `--local-path DIR`, the collection is derived
  from `DIR` instead of the workspace, so `--reset` can no longer delete the collection a live
  MCP server is using. Each `bench_matrix.py` run already has its own scratch folder, so it
  also gets its own collection.

### Removed

- The Cline builtin harness. The desktop client did not keep or read the wizard's settings
  file, so `setup.py` no longer offers `--harnesses cline`; use OpenCode or another harness.

