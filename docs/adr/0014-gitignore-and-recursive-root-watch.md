# Honor `.gitignore` and watch the workspace root recursively

The indexer and watcher now honor workspace-local `.gitignore` files. `indexer.iter_workspace_files` prunes ignored directories during the walk, and `watcher.py` schedules a **single recursive watch** on `settings.workspace_root`; the handler drops events for paths excluded by `.gitignore` or `config.IGNORE_DIRS`. Nested ignore files are supported, with the deeper file taking precedence, and matching uses `pathspec` (gitwildmatch semantics: `*`, `**`, `!` negation, `dir/`, anchored `/path`). `IGNORE_DIRS` stays as the fixed fallback. The last sweep's exclusions are exposed as `get_status.ignored_dirs` / `ignored_files`.

This amends [ADR-0007](./0007-single-workspace-no-multi-repo.md), which recorded ignore rules as "a small allowlist/ignore set, not per-repo gitignore identity".

## Context

Two defects from the same E2E run drove this:

- **ISS-7:** the watcher scheduled one non-recursive watchdog watch per directory. On Windows each scheduled directory is a `ReadDirectoryChangesW` emitter thread plus a handle; a Visual Studio workspace opened in the harness reached 3,227 threads, ~16.4k handles and 2.5 GB private memory. Build trees (`bin/`, `obj/`) multiply the directory count.
- **ISS-8:** `.gitignore`d files were indexed and watched. `artifacts/` polluted retrieval results, and build trees fed the watcher. The workspace's own ignore policy was invisible to the server, even though the TDD already said identity comes from the working tree, not git state ([ADR-0001](./0001-index-on-save-not-git-state.md)).

An earlier note claimed `observer.schedule(..., recursive=True)` "blocked registration for seconds" over `.venv`. The installed watchdog shows `schedule()` only creates an `ObservedWatch` and an emitter; on Windows the emitter passes `recursive` to `ReadDirectoryChangesW(bWatchSubtree=TRUE)`. There is no tree walk at registration time. Watchdog does walk a *newly created* directory to synthesize sub-events, which is bounded by the create/move event, and the reconciliation sweep remains the backstop.

## Considered Options

- **Keep per-directory watches and only add `.gitignore` pruning:** removes watched build trees when they are gitignored, but any workspace without comprehensive ignore rules (or with many non-ignored directories) still pays one thread and handle per directory. Rejected; it does not fix ISS-7's mechanism.
- **One recursive root watch + handler-level filtering (chosen):** one emitter thread and one OS handle per workspace on Windows regardless of tree size. Filtering happens where ignore policy already lived (the event handler and the indexer).
- **Hybrid (recursive root, per-directory additions):** no benefit — the root watch already covers every subtree, and added watches only reintroduce the thread-per-directory cost.
- **Hand-rolled `.gitignore` matcher with `fnmatch`:** git's precedence, negation, anchoring, and directory-only rules are subtle; a partial matcher silently indexes the wrong set. Rejected in favor of `pathspec`.
- **`pathspec` as the matcher (chosen):** small pure-Python dependency with gitwildmatch semantics and type hints.
- **Read `.git/info/exclude` and global `core.excludesfile`:** requires git config/process coupling and makes results depend on the developer's machine. Rejected; only `.gitignore` files at/under the workspace root are honored.
- **A configuration switch for gitignore support:** adds a mode with no consumer; `.gitignore` is the workspace's declared ignore policy. Rejected.

## Consequences

- `pathspec` becomes a runtime dependency (`pyproject.toml`, `requirements.txt`, `uv.lock`).
- `IGNORE_DIRS` (`.git`, `.index`, `.simple-ci`, `__pycache__`, `.venv`, `node_modules`) is still checked first and remains the fallback for workspaces without `.gitignore` files.
- Ignore scope is the workspace root and below. A workspace that is a subdirectory of a git repo does not inherit `.gitignore` files above it.
- Matching is case-insensitive on Windows (git's `core.ignorecase` default) and case-sensitive elsewhere.
- `IgnoreRules` caches one `GitIgnoreSpec` per directory keyed by `st_mtime_ns`, so watcher events follow `.gitignore` edits without a restart. A `.gitignore` create/modify/move/delete outside `IGNORE_DIRS` enqueues `SWEEP_REQUEST`; the sweep's existing stale-path diff removes now-ignored rows and vectors, and indexes newly unignored files.
- `get_status` gained two additive fields, `ignored_dirs` and `ignored_files`, populated from `indexer.LAST_SWEEP_STATS` (0 before the first sweep).
- The status/log line reports `.gitignore` pruning only; `IGNORE_DIRS` remains a static, documented set.
- Watchdog synthesizes sub-events for a newly created directory by walking it, so creating a large tree while the server runs can delay event dispatch briefly. The 45 s sweep covers any missed file.
- Ignored files are not indexed, so they cannot be returned by `search_code` or `symbol_lookup`; this is an indexing policy, not an access-control boundary for the filesystem.
- The TDD watcher contract (§7.8) and the ignore line in §4.2 were updated; the old "non-recursive per directory" rule is retired.
