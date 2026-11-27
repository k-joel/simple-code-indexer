# Runbook

Repeatable operational procedures for this repository, executed by operators or agents under time pressure. Each entry covers one verified task; see [Entries](#entries) below to locate a procedure.

**Risk legend:** `SAFE` (reads or disposable writes) · `OPERATOR` (recoverable state changes) · `MANUAL` (actions outside the terminal) · `DESTRUCTIVE` (deletion or irreversible change).

<!--
RUNBOOK MAINTENANCE GUIDE (FOR AGENTS & CONTRIBUTORS)

PURPOSE & SCOPE
- Repeatable, ordered operational procedures executed under time pressure (setup, probes, recovery, cleanup, release).
- Intended reader: an operator or agent executing a task mid-incident or mid-workflow.
- NOT for design rationale, architecture docs, API/config reference, or changelogs.

UPDATE TRIGGERS
Update this file before ending a session whenever you:
- Add a new repeatable operational workflow.
- Change commands, flags, paths, config keys, or expected output for an existing entry.
- Execute a [DRAFT] entry or branch in a real run (confirm steps and remove [DRAFT], or record observed failures).
- Confirm a new failure mode and its fix during a real run.
- Retire an obsolete workflow or step.

INCLUSION / EXCLUSION CRITERIA
- Include: one focused, repeatable task per entry; only steps and failures confirmed by a real run (or marked [DRAFT] if untested).
- Exclude: imagined procedures not marked [DRAFT], one-off commands, background prose, design rationale, and non-executable reference material.

STRUCTURE & FORMATTING
- Single H1: Keep `# Runbook` as the only H1 in the file.
- Summary Index Table: Maintain `| RUN | Procedure |` under `## Entries` in ascending numeric order. Every row must link to its section anchor (`[NNN](#run-nnn-risk-kebab-case-title)`).
- File order: visible preamble -> this comment -> `## Entries` index table -> `## RUN-NNN ...` sections in ascending ID order.
- IDs: sequential 3-digit zero-padded IDs (`RUN-NNN`, starting at 001). Assign the next free ID. Never renumber entries or reuse retired IDs.
- Entry heading: `## RUN-NNN (<RISK>): <imperative task>` (append `[DRAFT]` if untested).
- Risk tags: `SAFE`, `OPERATOR`, `MANUAL`, `DESTRUCTIVE`. Combine with `, ` when multiple apply (e.g., `OPERATOR, MANUAL`).
- Summary paragraph (required): 1-2 sentences right under the heading stating what the procedure does and what it does NOT cover.
- Steps (required): numbered ordinal steps (`1.`, `2.`, ...), one action per step, copy-pasteable code block, and `Expected: <observable result>.` when it helps confirm success.
- Troubleshooting (optional; omit heading if no confirmed failures exist): `**Troubleshooting**`, followed by symptom-first bullets ordered from cheapest to most expensive diagnostic: ``- **`<verbatim symptom>`**: <cause>. Fix: `<command>`.``

QUALITY & STYLE RULES
- Voice & brevity: imperative or present tense, concise, high-signal; no filler or historical commentary.
- Truth & placeholders: record only steps and failures observed in a real run. Keep unknown values visibly bracketed as `[placeholder]` and explain how to obtain them; never invent values. Mark untested entries or branches `[DRAFT]` and ask the first real runner to report back.
- Commands: copy-pasteable with concrete values where known; label variants inside the code block (`# safe mode` / `# live mode`).
- Ordering & safety: state wrong-order consequences inline before hazardous steps. For `OPERATOR` or `DESTRUCTIVE` entries, state the rollback path (or plainly note that none exists) and end with a verification step proving the final observable state. Mark the preferred path `(recommended)` when alternatives exist.

LIFECYCLE & WORKFLOW
- Add: assign the next free `RUN-NNN`, add a row to `## Entries`, and append the entry using the Example Layout below.
- Update: edit commands, expected results, and troubleshooting inline when behavior changes; remove obsolete steps.
- Promote draft: after a real run confirms the steps, update observed outputs, fill resolved placeholders, and remove `[DRAFT]`.
- Retire: delete the `## RUN-NNN` section body and update its `## Entries` row to `| [NNN](#...) | Retired - <reason or replacement RUN-NNN> |` so the ID is never reused.

ANTI-PATTERNS
- Writing desk-imagined steps without `[DRAFT]`.
- Inventing tokens, ports, hostnames, or IDs instead of using `[bracketed placeholders]`.
- Renumbering entries or reusing retired `RUN-NNN` IDs.
- Putting multiple actions in one step, or using bullets instead of numbered steps.
- Writing vague troubleshooting ("check logs") instead of verbatim symptom + cause + exact fix.
- Leaving stale commands after changing code/tooling, or adding design rationale.

EXAMPLE LAYOUT (4-SPACE INDENTED)

    ## Entries

    | RUN | Procedure |
    |---|---|
    | [001](#run-001-risk-imperative-task) | <imperative task> |

    ---

    ## RUN-001 (OPERATOR): <imperative task>

    <What this procedure does.> Does not <scope exclusion>. Rollback: <undo command, or "none; state change is irreversible">.

    1. <Perform one action (note wrong-order consequence if applicable)>:

       ```
       # safe mode (recommended)
       <command with [bracketed placeholder] - obtain via [how]>
       ```

       Expected: <observable result>.

    2. <Verify final observable state>:

       ```
       <verification command>
       ```

       Expected: <observable end state>.

    **Troubleshooting**

    - **`<verbatim error or log string>`**: <cause>. Fix: `<exact command>`.
-->

---

## Entries

| RUN | Procedure |
|---|---|
| [001](#run-001-safe-probe-the-backing-services) | Probe the backing services |
| [002](#run-002-safe-run-the-quality-gate-before-a-handoff) | Run the quality gate before a handoff |
| [003](#run-003-operator-verify-a-live-mcp-session-with-the-stdio-probes) | Verify a live MCP session with the stdio probes |
| [004](#run-004-destructive-rebuild-a-workspace-index-from-scratch) | Rebuild a workspace index from scratch |
| [005](#run-005-operator-stop-a-sidecar-writer-daemon) | Stop a sidecar writer daemon |
| [006](#run-006-safe-read-the-sidecar-session-timeline) | Read the sidecar session timeline |
| [007](#run-007-safe-regenerate-the-language-catalog) | Regenerate the language catalog |
| [008](#run-008-operator-rehearse-a-release-on-testpypi) | Rehearse a release on TestPyPI |
| [009](#run-009-destructive-publish-a-release-to-pypi) | Publish a release to PyPI |
| [010](#run-010-operator-install-the-editable-development-environment) | Install the editable development environment |
| [011](#run-011-operator-validate-the-prod-wheel-install) | Validate the prod wheel install |
| [012](#run-012-safe-verify-symbol-coverage-for-a-workspace) | Verify symbol coverage for a workspace |

## RUN-001 (SAFE): Probe the backing services

Checks the embedding endpoint required by semantic search and Qdrant when `vector_store: qdrant` is selected. It does not check the index, sidecar writer, or harness session.

1. Print the settings the probe will use:

   ```
   uv run python -c "from simple_code_indexer.config import load_settings; s = load_settings(); print('workspace:', s.workspace_root); print('source:', s.workspace_source); print('index_db:', s.index_db_path); print('vector_store:', s.vector_store); print('embed:', s.embed_model, s.embed_dim)"
   ```

2. Run the probe from the repository root:

   ```
   uv run python tests/service_probe.py
   ```

   Expect the final line to be `PROBE OK`.

3. Compare the reported `dim` with `s.embed_dim`. A mismatch prints `WARN` but still exits 0. Correct `embedding.dim` or unset the conflicting `EMBED_DIM` override before indexing.

4. Read the Qdrant result for the active backend. With `vector_store: sqlite-vec` or `faiss`, `qdrant unavailable (optional ...)` is expected — local backends need no server. With `vector_store: qdrant`, a failure exits 1; start Qdrant or correct `qdrant.url` before continuing.

5. For `vector_store: sqlite-vec`, confirm the interpreter can load the extension at all:

   ```
   uv run python -c "from simple_code_indexer import sqlite_vec_store; print(sqlite_vec_store.available())"
   ```

   Expect `(True, 'sqlite-vec v0.1.9')`. A `False` result means this Python blocks SQLite extension loading; select `vector_store: faiss` (the wizard does this automatically) or use a uv-managed interpreter.

**Troubleshooting**

- **`embeddings FAIL URLError: ...`**: the endpoint is unavailable or its URL or port is wrong. Run `docker ps`, inspect `embedding.base_url`, then start the service or correct the setting.
- **`embeddings WARN configured dim=...`**: the configuration and endpoint disagree. Align `embedding.dim` with the returned dimension before rebuilding an index.
- **Embedding requests slow or time out with several workspaces open**: each workspace runs one writer daemon, but they share one embedding endpoint; each request is capped at 16 inputs with two in flight per process, yet N workspaces still multiply the load. Fix: close idle sessions or raise `embedding.timeout_s`.

## RUN-002 (SAFE): Run the quality gate before a handoff

Runs lint, type checking, and tests. It does not format files, stage changes, or commit.

1. Run the linter:

   ```
   uv run ruff check .
   ```

   Expect `All checks passed!`.

2. Run the type checker:

   ```
   uv run pyright
   ```

   Expect `0 errors, 0 warnings, 0 informations`.

3. Run the test suite with a writable base directory:

   ```
   uv run pytest -p no:cacheprovider --basetemp "artifacts\pytest-$PID" -q
   ```

   Expect exit code 0 with no failed tests. Compare failures rather than test counts, which change as tests are added.

4. To run one test while iterating, use:

   ```
   uv run pytest tests/test_smoke.py::test_main_imports -p no:cacheprovider --basetemp "artifacts\pytest-$PID-single" -q
   ```

**Troubleshooting**

- **Pytest cannot write its temporary or cache directory**: keep `-p no:cacheprovider` and replace the `--basetemp` value with a writable directory.

## RUN-003 (OPERATOR): Verify a live MCP session with the stdio probes

Tests the MCP stdio contract and index-on-save behavior without a harness. Run it from the workspace to index; it does not test a specific harness configuration or lifecycle.

1. Probe the backing services:

   ```
   uv run python tests/service_probe.py
   ```

   Continue only after `PROBE OK`.

2. Run the protocol probe:

   ```
   uv run python tests/mcp_probe.py
   ```

   Expect the `search_code`, `symbol_lookup`, and `get_status` tools, responses from each tool, and `PROBE OK`.

3. Run the index-on-save probe:

   ```
   uv run python tests/live_watch_probe.py
   ```

   The probe creates `watch_probe_tmp_<pid>.cpp`, waits for the watcher, saves the file, polls `symbol_lookup`, and removes the file. Expect `PROBE OK`.

4. Read the final status. Expect `writer_ok: true` and `watcher_alive: true`. A nonzero `pending_embeddings` means vectors are still being written and is not a failure. `workspace_source` names the resolved source (`env`, `roots`, `harness:<name>`, `cwd`); a harness whose entry predates ADR-018 reports `cwd` until `simple-code-indexer setup --harnesses <name>` rewrites it.

**Troubleshooting**

- **`PROBE FAIL: server closed stdout waiting for id 1`**: the server did not answer. Run the service probe, read the probe's stderr tail, and inspect `.simple-ci/log/reader.log`.
- **`writer_ok: false` immediately after daemon startup**: the writer may still be starting. Wait a few seconds and rerun the probe.
- **`PROBE FAIL: watcher never became alive within 10 s of startup`**: inspect `.simple-ci/log/writer.log` and `.simple-ci/run/daemon.json`. Stop a stale daemon with RUN-005.
- **`PROBE FAIL: ... not indexed within 5 s of save`**: check `.gitignore` and `IGNORE_DIRS`, then search `writer.log` for a full-queue warning. Lexical indexing does not require the embedding endpoint.
- **Semantic search returns hits with `ready: false`**: vectors are still being written. Wait for `pending_embeddings` to reach 0.
- **`another simple-code-indexer already owns …index.db`**: only possible in `mode: embedded` (or when a legacy embedded writer holds the lease). In the default sidecar mode a second session is a read-only reader. Fix: leave the second session running in sidecar mode; use `mode: embedded` only for single-session diagnosis.
- **`get_status` reports the editor installation directory as the workspace**: the client spawns stdio children without a `cwd` (ISS-014). Check `workspace_source`: `roots` or `harness:<name>` should replace `cwd`. An entry without the `SIMPLE_CI_HARNESS` marker still gets `harness:<name>` (every resolver is asked when the cwd is an editor install), so a persistent `cwd` there means the plugin's discovery found no live window — check `~/.commandcode/ide/*.json` contains this window's extension-host pid. `load_settings` now refuses such a cwd with a `ConfigError` instead of building an empty index; re-run `simple-code-indexer setup --harnesses <name>` for the marker fast path, or set `WORKSPACE_ROOT` for a one-off diagnosis (remove it afterwards).
- **`config_file: null` in `get_status`**: `~/.simple-ci/config.yaml` does not exist, and project-local configs are ignored. Fix: run `simple-code-indexer setup` or create the global file.

## RUN-004 (DESTRUCTIVE): Rebuild a workspace index from scratch

Deletes one workspace's derived `.simple-ci/` data and rebuilds it through startup reconciliation. Source files, the global configuration, the uv tool environment, and other workspaces are untouched.

1. Confirm the target workspace and index path:

   ```
   uv run python -c "from simple_code_indexer.config import load_settings; s = load_settings(); print('workspace:', s.workspace_root); print('source:', s.workspace_source); print('index_db:', s.index_db_path); print('vector_store:', s.vector_store); print('embed:', s.embed_model, s.embed_dim)"
   ```

2. Confirm the backing services are available:

   ```
   uv run python tests/service_probe.py
   ```

   Continue after `PROBE OK`. A failed embedding endpoint leaves `pending_embeddings` high while lexical search remains available.

3. Close harness sessions and stop the workspace's sidecar writer with RUN-005. Deleting first can fail because the daemon holds index and log files open.

4. Delete the index directory:

   ```
   Remove-Item -Recurse -Force .simple-ci
   ```

   If `INDEX_DB` points elsewhere, delete that index directory and the configured `faiss.path` instead. Use the paths printed in step 1. Deleting the index directory removes the default `vec_chunks` table with it; a stale `vectors.faiss` from an earlier FAISS run is not read while `sqlite-vec` is active and can be deleted.

5. Trigger the rebuild with a probe, or open a harness session in the workspace. To use the probe, set a symbol that exists in the workspace:

   ```
   $env:PROBE_SYMBOL = 'calculateWidgetChecksum'
   uv run python tests/mcp_probe.py
   ```

6. Poll `get_status` until `pending_embeddings` reaches 0. Expect nonzero file, symbol, and chunk counts, `vectors_indexed` equal to `chunks_indexed`, and semantic hits with `ready: true`.

**Troubleshooting**

- **`The process cannot access the file '...' because it is being used by another process`**: the writer is still running. Stop it with RUN-005 and repeat the delete.
- **`files_indexed: 0` after the rebuild**: the server indexed another directory. Check `get_status.workspace`, then fix the spawn directory or set `WORKSPACE_ROOT` for the run.
- **`pending_embeddings` stays high**: run the service probe, then inspect `get_status.services.embedding` and `.simple-ci/log/writer.log`.
- **Semantic hits are empty with `ready: true`**: the workspace has no indexed files or the vector store has no chunks. Check the workspace and index counts.

## RUN-005 (OPERATOR): Stop a sidecar writer daemon

Stops one workspace's sidecar writer and removes stale discovery files after a forced stop. It does not stop readers, harnesses, or managed containers.

1. Read the discovery file and confirm its `workspace` is the target:

   ```
   Get-Content .simple-ci\run\daemon.json
   ```

   If the file does not exist — or exists but is empty — no daemon is published and there is nothing to stop. A shutdown clears discovery by emptying the file when a reader holds it open, so an empty file is a cleared file (ADR-027).

2. Confirm the recorded pid is live:

   ```
   $state = Get-Content .simple-ci\run\daemon.json | ConvertFrom-Json
   Get-Process -Id $state.pid | Select-Object Id,ProcessName,StartTime
   ```

3. Stop the process and its children:

   ```
   taskkill /PID $state.pid /T /F
   ```

4. After the process exits, remove discovery files left by the forced stop:

   ```
   Remove-Item .simple-ci\run\daemon.json, .simple-ci\run\daemon.token -ErrorAction SilentlyContinue
   ```

   Do not delete these files first. A new daemon could publish an endpoint that the old process then deletes.

5. Confirm the process is gone and the discovery file is absent or empty:

   ```
   Get-Process -Id $state.pid -ErrorAction SilentlyContinue
   Test-Path .simple-ci\run\daemon.json
   (Get-Item .simple-ci\run\daemon.json -ErrorAction SilentlyContinue).Length
   ```

   The first command returns nothing. The file is gone (`False`) or present with length `0`; either way no endpoint is published and the next reader session spawns a fresh daemon.

**Troubleshooting**

- **`Access is denied`**: use an account that can stop the process.
- **The daemon respawns immediately**: a reader is still attached. Close the harness or stop the reader process first; `get_status.sessions` and `writer.log` identify live sessions.
- **`daemon.json` is missing but a writer is running**: find the pid with `get_status.writer_pid` or the heartbeat rows in `index.db`. Do not kill processes by image name because other workspaces have their own daemons.
- **The delete in RUN-004 still fails**: reread `daemon.json`, confirm the writer pid, and repeat the stop.

## RUN-006 (SAFE): Read the sidecar session timeline

Reads `writer.log` to identify attached harnesses, live session counts, and shutdown behavior. Use `get_status` for current state.

1. Read `get_status.writer_log_file` to identify the active writer log. The `log_file` field identifies the reader log instead.

2. Read the writer log tail:

   ```
   Get-Content .simple-ci\log\writer.log -Tail 80
   ```

3. Filter the lifecycle lines:

   ```
   Select-String -Path .simple-ci\log\writer.log -Pattern 'workspace lock acquired|writer runtime ready|sidecar client connected|sidecar session registered|sidecar client disconnected|no sidecar sessions|workspace lock released|sidecar stopped' | Select-Object -Last 12 | ForEach-Object { $_.Line }
   ```

4. Judge shutdown from `sidecar stopped` and `workspace lock released`. A harness that kills its child can leave no `disconnected` line.

5. Treat `get_status.sessions` as a point-in-time value. When reporting how many harnesses ran, use the maximum `sessions=N` recorded in `writer.log`.

**Troubleshooting**

- **`writer.log` is missing**: the workspace has not run a sidecar writer. Check `get_status.role`; readers write `reader.log`, and embedded mode writes `embed.log`.
- **No `session registered` line appears but the tools work**: use the `writer_log_file` path from `get_status` to avoid reading another workspace's log.
- **Repeated `workspace lock acquired` lines appear within seconds**: more than one daemon started. Stop the extras with RUN-005 and check for a slow daemon spawn.
- **The tail contains mostly `db open ... (rw)` heartbeat lines**: use the filter in step 3 or increase the tail count.

## RUN-007 (SAFE): Regenerate the language catalog

Rebuilds `src/simple_code_indexer/languages/catalog.py` from the pack's published language table. It does not touch the index; a version bump takes effect on the next writer start.

1. Check whether the committed catalog is already current (needs network):

   ```
   uv run python tools/gen_language_catalog.py --check
   ```

   Exit 0 prints `catalog is current`. Exit 1 means the table drifted — for example after a `tree-sitter-language-pack` upgrade.

2. Regenerate and review the diff:

   ```
   uv run python tools/gen_language_catalog.py --report
   git diff --stat src/simple_code_indexer/languages/catalog.py
   ```

   `--report` prints every language's symbol map and the residual `SYMBOL_GAPS`. The tool fails
   loudly instead of guessing: an unresolvable display name means a new upstream row needs an
   entry in `ALIASES`, and a node type the grammar does not have means the pack renamed something
   and a map is silently dead.

3. Confirm the invariants before committing:

   ```
   uv run pytest tests/test_language_catalog.py -q
   ```

   That suite asserts unique extension/filename ownership, that every grammar exists in the pack,
   that no data-format extension leaks into the allowlist, and that every symbol map uses known
   kind names and that `SYMBOL_GAPS` matches the languages with no map.

4. Bump `CATALOG_VERSION` in the generator only when the change should force existing indexes to
   reconcile (a language id change, or a path that was indexed becoming denied). Bump
   `SYMBOL_MAP_VERSION` — **not** `CATALOG_VERSION` — when only symbol maps changed: the writer
   then re-parses indexed files once (`indexer.backfill_symbols`) without re-embedding anything.
   Regenerate again after either bump — both constants are emitted into the catalog.

**Troubleshooting**

- **`cannot resolve display name '...'`**: the upstream table gained a language whose display name is not a valid grammar name. Add it to `ALIASES` with the pack's name (verify with `tree_sitter_language_pack.has_language`).
- **`parsed only N language rows; table layout changed?`**: the docs page markup changed. Re-check `parse_table` against the saved page, using `--table <saved.html>` to iterate offline.
- **`catalog is stale` right after regenerating**: the file was formatted or hand-edited. The generated output is authoritative — re-run the tool rather than editing `catalog.py`.

## RUN-008 (OPERATOR): Rehearse a release on TestPyPI

Exercises the exact publish path without touching PyPI. Requires the `testpypi` GitHub environment and a pending Trusted Publisher registered at <https://test.pypi.org/manage/account/publishing/> (project `simple-code-indexer`, workflow `release.yml`, environment `testpypi`).

1. Confirm the build is sound locally:

   ```
   uv build --no-sources
   uv run --isolated --no-project --with ./dist/*.whl simple-code-indexer version
   ```

2. Confirm the version is unpublished on both indexes:

   ```
   uv run python tools/release.py --check-pypi
   curl -s -o NUL -w "%{http_code}" https://test.pypi.org/pypi/simple-code-indexer/json
   ```

3. Run the workflow by hand — Actions → **Release** → *Run workflow* on `master`. No tag exists, so only the `build` and `publish-testpypi` jobs run.

4. Install from TestPyPI into a scratch environment. The extra index is required: TestPyPI holds the package but none of its dependencies.

   ```
   uvx --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ --from "simple-code-indexer==$(uv run python -c "import re,pathlib; print(re.search(r'version = \"([^\"]+)\"', pathlib.Path('pyproject.toml').read_text()).group(1))")" simple-code-indexer version
   ```

**Troubleshooting**

- **`invalid-publisher` / 403**: the pending publisher's repository, workflow filename, or environment name does not match `release.yml`. They must match exactly.
- **`File already exists`**: TestPyPI cannot re-upload a version. Bump with `uv run python tools/release.py --bump patch` (which also needs `git push`) or rehearse with a `rc` version.
- **Dependency resolution fails**: add `--extra-index-url https://pypi.org/simple/`; TestPyPI only mirrors the project itself.

## RUN-009 (DESTRUCTIVE): Publish a release to PyPI

Irreversible: a published version can never be re-uploaded. Requires the `pypi` environment with required reviewers, a green CI run on `master`, and a pending Trusted Publisher on PyPI.

1. Confirm CI is green on `master`, then cut the release. This bumps `pyproject.toml` + `uv.lock`, moves the CHANGELOG section, commits, tags `v<version>`, and pushes:

   ```
   uv run python tools/release.py --bump patch
   ```

   Preview first with `--dry-run` if the version arithmetic is in doubt.

2. Watch Actions → **Release**. `build` verifies the tag against `pyproject.toml` (`tools/release.py --verify-tag`) and smoke-tests both distributions; `publish-pypi` waits for the `pypi` environment approval; `github-release` attaches the artifacts and generated notes.

3. Verify the served version, which is what a harness entry will launch:

   ```
   uvx simple-code-indexer version
   uvx simple-code-indexer setup --dry-run
   ```

4. Repoint an existing dev install at the published version. `setup` reinstalls the tool
   environment in place, so no extra flag is needed — but it picks **editable** while a checkout is
   detectable. Run from outside a checkout, or set the prod flavour with `--wheel` (details in
   RUN-010 and RUN-011):

   ```
   uvx simple-code-indexer setup
   uvx simple-code-indexer setup --wheel
   ```

   Either way the harness entry is unchanged. `simple-code-indexer status` reports
   `install_kind`; `uv-receipt.toml` in the tool environment is the ground truth.

**Troubleshooting**

- **`tag ... does not match pyproject version`**: `pyproject.toml` is the source of truth. Tag from `tools/release.py`, never by hand.
- **`<version> is already on PyPI`**: some files uploaded before the failure. Yank the release on PyPI and publish the next patch; do not reuse the version.
- **A bad release shipped**: use PyPI's *Yank* (it hides the version without freeing it), fix, then `--bump patch`.

## RUN-010 (OPERATOR): Install the editable development environment

Installs this checkout as a **uv tool** and links it, so the harnesses you already configured serve your working tree and source edits are live without reinstalling. It does not run the wizard, write config, or touch a workspace index. Rollback: `simple-code-indexer uninstall --yes`.

1. Confirm the checkout is what will be linked — detection is strict (it requires this package's own `src/` tree) and refuses to guess:

   ```
   uv run simple-code-indexer install --dry-run
   ```

   Expected: `Would install <repo> with uv tool (editable)`. A different path means `_default_repo_root()` found the wrong tree; stop and pass `--repo-root <repo>` explicitly.

2. Install (or reinstall) the editable environment. Run it from the repo root; this is the whole update step after a `git pull`:

   ```
   uv run simple-code-indexer install
   ```

   Expected: `Installed (editable): <tool-env>`, and any recorded harness entries are rewritten to that environment.

3. Prove the environment serves the working tree, not a copy:

   ```
   uv tool dir
   $envDir = Join-Path $(uv tool dir) 'simple-code-indexer'
   Get-Content (Join-Path $envDir 'uv-receipt.toml')
   ```

   Expected: `requirements = [{ name = "simple-code-indexer", editable = "<repo>" }]`. A `directory = "<repo>"` line instead means a wheel is installed — that is RUN-011, not this one.

4. Confirm the interpreter resolves the tree rather than a copy:

   ```
   & (Join-Path $envDir 'Scripts\python.exe') -c "import simple_code_indexer, pathlib; print(pathlib.Path(simple_code_indexer.__file__).resolve())"
   ```

   Expected: a path under `<repo>\src\simple_code_indexer\`. A `site-packages` path means the environment is not editable.

5. Restart the harness so it relaunches the entry. Existing sessions keep the old process until they restart.

**Troubleshooting**

- **`No source checkout found; installing the published wheel.`**: nothing to link, so this run silently took the wheel path. If you meant dev, pass `--repo-root <repo>`.
- **`uv tool install failed for <spec>`**: uv printed the build log above the error. Fix the build first; the resolver is usually a `pyproject.toml`/`uv.lock` mismatch.
- **`error: Executable already exists: simple-code-indexer.exe (use --force to overwrite)`**: a previous environment was removed but its shim survived in `uv tool dir --bin`, so `uv tool list` says "No tools installed". `install` detects the shim and passes `--force` by itself; if you hit this from a raw `uv tool install`, delete the leftover shim (or add `--force`) and re-run step 2.
- **`error: failed to remove file ...\Scripts\simple-code-indexer.exe: ... being used by another process (os error 32)`** or **`error: failed to remove directory ...\Scripts: Access is denied (os error 5)`**: uv tried to rewrite the tool environment while a process was running from it. `uvx simple-code-indexer setup` is the normal cause (uvx runs setup from inside the environment); `ensure_tool` now detects that, skips when the receipt already matches, and otherwise prints the `uv tool install …` line to run from outside. If the installer refuses because *another* process holds the shim, stop that process first (`get_status`, `daemon.json`). `uninstall` handles the same lock: when it detects it is running from that environment on Windows, it removes everything else and prints `uv tool uninstall simple-code-indexer` to run once the process exits.
- **`Already installed (...); keeping the running environment.`**: expected from `uvx … install` when the running environment already holds the requested editable link. Nothing is broken; run the printed command from outside if you really want to rebuild.
- **Edits still not visible**: the harness is running the previous process. Restart it, then re-check step 4.
- **`ImportError`/`ModuleNotFoundError` after deleting or moving the checkout**: this flavour cannot survive losing its tree by design. Re-clone and repeat step 2, or switch to RUN-011.

## RUN-011 (OPERATOR): Validate the prod wheel install

Builds a real wheel from this checkout, installs it into the **same** uv tool environment, and confirms the harness entry still points at it — so this is how you test the artifact users get. It does not publish, run the wizard, or touch a workspace index. Rollback: re-run RUN-010 step 2 to restore the editable link.

1. Snapshot the current entry so you can prove it does not move:

   ```
   $envDir = Join-Path $(uv tool dir) 'simple-code-indexer'
   $py = Join-Path $envDir 'Scripts\pythonw.exe'
   $before = (Get-FileHash $py -Algorithm SHA256).Hash
   ```

2. Install the built wheel (builds `<repo>` and reinstalls in place; `--refresh` busts uv's stale local-build cache):

   ```
   uv run simple-code-indexer install --wheel
   ```

   Expected: `Installed (wheel): <tool-env>` — the same root as RUN-010.

3. Confirm the receipt and the import path flipped to the built copy:

   ```
   Get-Content (Join-Path $envDir 'uv-receipt.toml')
   & (Join-Path $envDir 'Scripts\python.exe') -c "import simple_code_indexer, pathlib; print(pathlib.Path(simple_code_indexer.__file__).resolve())"
   ```

   Expected: `directory = "<repo>"`, and an import path under the tool environment's `Lib\site-packages\simple_code_indexer\`.

4. Prove the entry is byte-identical across the flavour change (this is the guarantee the whole model rests on):

   ```
   (Get-FileHash $py -Algorithm SHA256).Hash -eq $before
   ```

   Expected: `True`.

5. Smoke the entry the harness actually launches, under redirected pipes (`pythonw` detaches from a console):

   ```
   Start-Process -FilePath $py -ArgumentList '-m','simple_code_indexer','version' -RedirectStandardOutput $env:TEMP\out.txt -RedirectStandardError $env:TEMP\err.txt -Wait -PassThru | Select-Object ExitCode
   Get-Content $env:TEMP\out.txt
   ```

   Expected: `ExitCode 0` and the version from `pyproject.toml`.

6. Read the live flavour from the ground truth, then restore dev if this was a one-off:

   ```
   Select-String -Path (Join-Path $envDir 'uv-receipt.toml') -Pattern 'directory|editable'
   uv run simple-code-indexer install
   ```

   Expected: `directory = "<repo>"` (wheel) before the restore; after it the receipt shows `editable = "<repo>"` again. `status.install_kind` reports the same thing, but only after a full `setup` recorded it — `install` repoints entries and writes no config.

**Troubleshooting**

- **`install_kind` is `null`**: `install` repoints entries but writes no config, so nothing recorded a kind. Run `setup` once, or read `uv-receipt.toml` directly.
- **Entry hash differs after step 4**: something rewrote the entry — usually a `setup` run against a different harness config. Re-run `setup` and compare again; treat any remaining difference as a defect.
- **`--refresh` did not pick up a source-only edit**: uv's build cache is keyed on `pyproject.toml`/`setup.py`/`setup.cfg` and the presence of `src`, not file contents. `ensure_tool` already passes `--refresh`; if it still serves stale code, clear the cache with `uv cache clean`.
- **Wheel install says `No source checkout found`**: uvx/wheel runs have nothing local to build, so it pins `simple-code-indexer==<version>` from PyPI. Use RUN-010 if you meant to test this tree.
- **Import still resolves to `<repo>\src\...`**: the reinstall did not flip the flavour. Confirm the command exited 0, then repeat step 2.
- **A harness entry names a `…\Temp\…` or other nonexistent interpreter**: the server never starts and the client shows only a failed spawn. This is what ISS-023 caused; `--install-only` now refuses that rewrite and leaves the entry alone. Repair both the entry and the record with a real tool environment, then restart the harness:
  ```
  $exe = Join-Path (Join-Path (uv tool dir) 'simple-code-indexer') 'Scripts\pythonw.exe'
  Test-Path $exe            # must be True before repointing
  uv run simple-code-indexer install    # repoints the recorded entries at $exe
  ```

## RUN-012 (SAFE): Verify symbol coverage for a workspace

Checks whether `symbol_lookup` can resolve symbols in the languages a workspace actually contains, and distinguishes "no such symbol" from "this language cannot produce symbols". It does not rebuild the index or change any configuration.

1. Read the catalog's coverage split:

   ```
   uv run python -c "from simple_code_indexer.languages import catalog; from simple_code_indexer.registry import load_registry; r = load_registry(); print('maps:', len(r.mapped_grammars()), 'gaps:', len(catalog.SYMBOL_GAPS))"
   ```

   Expected: `maps:` in the 170s and `gaps:` equal to `len(SYMBOL_GAPS)`. A language listed in
   `SYMBOL_GAPS` is a known limitation, not a bug; a Vue, Svelte, Astro, Heex, Blade, Templ, Twig, or
   Jinja file is not a gap any more (ADR-021).

2. Ask the live server which languages it indexed and whether they produced symbols:

   ```
   uv run python tests/mcp_probe.py
   ```

   `symbol_lookup` on a name that does not exist returns `coverage` (`none`/`partial`/`full`), `languages_indexed`, `languages_with_symbols`, and a `hint` naming the languages that cannot resolve.

3. For a symbol that should exist, look it up by name:

   ```
   $env:PROBE_SYMBOL = 'add_two'
   uv run python tests/mcp_probe.py
   ```

   Expected: `found: true` with `kind`, `line`, and `signature` populated. A `found: false` whose `coverage` names the language means that language is a gap; a `found: false` with `coverage: full` means the name genuinely is not indexed.

4. If a language was recently added to a map, confirm the symbols-only backfill ran rather than assuming it did:

   ```
   Get-Content .simple-ci\log\writer.log | Select-String 'symbol backfill'
   ```

   Expected: one `symbol backfill: re-parsed N/M file(s)` line after the upgrade, with `chunks_indexed` and `vectors_indexed` unchanged in `get_status`.

**Troubleshooting**

- **`languages_without_symbol_maps` is unexpectedly large**: `SYMBOL_GAPS` is generated; a stale catalog means the constant predates the derivation. Re-run RUN-007.
- **A Vue/Svelte/Astro/Heex/Blade/Templ declaration does not resolve**: confirm the host entry carries `injections=True` in `catalog.ENTRIES`, then check that the region's injected language is one of `elixir`/`javascript`/`php_only`/`typescript` — the other targets are deliberately not indexed. Heex `<script>`/`<style>` tags stay unindexed because their query relies on `#offset!`, which the binding does not expose (see NOTES.md).
- **A language has a map but still resolves nothing**: its tags query may describe node types the grammar uses differently from the sample the map was verified against. Re-run `tools/gen_language_catalog.py --report` and check that language's entry.
- **Symbols did not change after a catalog update**: the map version was not bumped, so no backfill was enqueued. Bump `SYMBOL_MAP_VERSION` in the generator (not `CATALOG_VERSION`) and restart the writer.

---

## RUN-013 (OPERATOR): Install a project-scope harness entry and verify pickup

Writes the MCP server into one workspace's own client config and pins it, then proves the client
loads it. Global entries are never touched, and no settings file changes. Run this in a throwaway
profile first: a non-dry-run setup writes the global config, the uv tool environment, and client
configs (NOTES.md).

1. Pick the project and (for a rehearsal) a redirected profile:

   ```powershell
   $root = "$env:TEMP\sci-scope"; New-Item -ItemType Directory -Force "$root\home","$root\proj" | Out-Null
   $env:USERPROFILE = "$root\home"; $env:HOME = "$root\home"
   $env:APPDATA = "$root\home\AppData\Roaming"; $env:LOCALAPPDATA = "$root\home\AppData\Local"
   Set-Location "$root\proj"
   ```

2. See what the wizard would preselect and why (read-only; writes nothing):

   ```
   uvx simple-code-indexer setup --harnesses
   ```

   Expected: one row per harness with its proof — `cli: cursor --version`,
   `binary: <name> on PATH` or `dir: config dir ~/.config/kilo` — its config path, and whether it
   has a project scope. An installed client that shows `-` means neither its CLI nor its config
   directory was found (ADR-025).

3. Install the project entry, skipping the interactive questions:

   ```
   uvx simple-code-indexer setup --harness-scope project --harnesses opencode --gitignore \
     --config-mode use --yes
   ```

   Expected: `opencode (project): …` naming the workspace file, then
   `Added to .gitignore: opencode.json, .simple-ci/`. A client with no project config (Goose,
   Claude Desktop, Hermes, OpenClaw, Cline) prints its **global** fallback instead, with the reason.

4. Confirm the pin, the harness marker and the absence of a global entry:

   ```
   Get-Content opencode.json
   Test-Path "$env:USERPROFILE\.config\opencode\opencode.json"
   ```

   Expected: `args` ends with `--workspace <abs workspace>`; the second command is `False`. A global
   entry would instead have no `--workspace` and would live in the home profile. Entries must carry
   **no** `env`/`environment`/`envs` block — a marker is an argument now (ADR-024). Only a
   resolver-owning client (Command Code) carries `--harness <name>`; the others have no resolver.

5. Prove the server resolves the pin (`workspace_source` must be `arg`, not `cwd`):

   ```
   uv run python tests/mcp_probe.py
   ```

   Under a project entry the probe prints `workspace_source: arg` and the workspace it was pinned to.

6. Prove the client itself picks the entry up (OpenCode; see
   `references/opencode-acp-mode.md` §8 for the log evidence):

   ```
   uv run python tests/acp_probe.py <workspace> --agent opencode
   ```

   Expected: `configured entry (project): …` in the preflight, `[PASS] OpenCode entry is pinned to
   this workspace`, then `mcp connected server=simple-code-indexer tools=3` in
   `~/.local/share/opencode/log/opencode.log`.

**Troubleshooting**

- **`configured entry (global)` when a project entry was expected**: the client's project file is not where the plugin says it is. Check `LOCAL_CONFIGS` in `harnesses/<client>.py` against that client's docs; the file must resolve under the workspace.
- **`[FAIL] … entry is pinned to this workspace`**: the entry pins a different directory (usually an older checkout). Re-run step 2 from the right folder — `--install-only` also rewrites it, using the recorded `workspace`.
- **The client connects but the index is empty**: the pin worked but the client is refusing project config — Claude Code needs interactive approval for `.mcp.json` servers; Codex and Pi read `.codex/config.toml` / `.pi/mcp.json` only in a trusted project.
- **`get_status.workspace_source` is `env`**: `WORKSPACE_ROOT` is set and outranks `--workspace`. Unset it before concluding anything about the pin.
- **The entry must not be committed**: a project entry contains an absolute path. Keep the `.gitignore` entry, or re-run with the file untracked.
