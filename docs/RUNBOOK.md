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

## RUN-001 (SAFE): Probe the backing services

Checks the embedding endpoint required by semantic search and Qdrant when `vector_store: qdrant` is selected. It does not check the index, sidecar writer, or harness session.

1. Print the settings the probe will use:

   ```
   uv run python -c "from simple_code_indexer.config import load_settings; s = load_settings(); print('workspace:', s.workspace_root); print('index_db:', s.index_db_path); print('vector_store:', s.vector_store); print('embed:', s.embed_model, s.embed_dim)"
   ```

2. Run the probe from the repository root:

   ```
   uv run python tests/service_probe.py
   ```

   Expect the final line to be `PROBE OK`.

3. Compare the reported `dim` with `s.embed_dim`. A mismatch prints `WARN` but still exits 0. Correct `embedding.dim` or unset the conflicting `EMBED_DIM` override before indexing.

4. Read the Qdrant result for the active backend. With `vector_store: faiss`, `qdrant unavailable (optional ...)` is expected. With `vector_store: qdrant`, a failure exits 1; start Qdrant or correct `qdrant.url` before continuing.

**Troubleshooting**

- **`embeddings FAIL URLError: ...`**: the endpoint is unavailable or its URL or port is wrong. Run `docker ps`, inspect `embedding.base_url`, then start the service or correct the setting.
- **`embeddings WARN configured dim=...`**: the configuration and endpoint disagree. Align `embedding.dim` with the returned dimension before rebuilding an index.

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

4. Read the final status. Expect `writer_ok: true` and `watcher_alive: true`. A nonzero `pending_embeddings` means vectors are still being written and is not a failure.

**Troubleshooting**

- **`PROBE FAIL: server closed stdout waiting for id 1`**: the server did not answer. Run the service probe, read the probe's stderr tail, and inspect `.simple-ci/log/reader.log`.
- **`writer_ok: false` immediately after daemon startup**: the writer may still be starting. Wait a few seconds and rerun the probe.
- **`PROBE FAIL: watcher never became alive within 10 s of startup`**: inspect `.simple-ci/log/writer.log` and `.simple-ci/run/daemon.json`. Stop a stale daemon with RUN-005.
- **`PROBE FAIL: ... not indexed within 5 s of save`**: check `.gitignore` and `IGNORE_DIRS`, then search `writer.log` for a full-queue warning. Lexical indexing does not require the embedding endpoint.
- **Semantic search returns hits with `ready: false`**: vectors are still being written. Wait for `pending_embeddings` to reach 0.

## RUN-004 (DESTRUCTIVE): Rebuild a workspace index from scratch

Deletes one workspace's derived `.simple-ci/` data and rebuilds it through startup reconciliation. Source files, the global configuration, the install copy, and other workspaces are untouched.

1. Confirm the target workspace and index path:

   ```
   uv run python -c "from simple_code_indexer.config import load_settings; s = load_settings(); print('workspace:', s.workspace_root); print('index_db:', s.index_db_path); print('vector_store:', s.vector_store); print('embed:', s.embed_model, s.embed_dim)"
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

   If `INDEX_DB` points elsewhere, delete that index directory and the configured `faiss.path` instead. Use the paths printed in step 1.

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

   If the file does not exist, no daemon is published and there is nothing to stop.

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

5. Confirm the process is gone and the discovery file is absent:

   ```
   Get-Process -Id $state.pid -ErrorAction SilentlyContinue
   Test-Path .simple-ci\run\daemon.json
   ```

   The first command returns nothing and the second prints `False`. The next reader session spawns a fresh daemon.

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
   uv run python tools/gen_language_catalog.py
   git diff --stat src/simple_code_indexer/languages/catalog.py
   ```

   The tool fails loudly instead of guessing: an unresolvable display name means a new upstream row needs an entry in `ALIASES`.

3. Confirm the invariants before committing:

   ```
   uv run pytest tests/test_language_catalog.py -q
   ```

   That suite asserts unique extension/filename ownership, that every grammar exists in the pack, and that no data-format extension leaks into the allowlist.

4. Bump `CATALOG_VERSION` in the generator only when the change should force existing indexes to reconcile (a language id change, or a path that was indexed becoming denied). Then regenerate again — the constant is emitted into the catalog. Without a bump, the startup reconcile is a no-op and stale rows stay as they are.

**Troubleshooting**

- **`cannot resolve display name '...'`**: the upstream table gained a language whose display name is not a valid grammar name. Add it to `ALIASES` with the pack's name (verify with `tree_sitter_language_pack.has_language`).
- **`parsed only N language rows; table layout changed?`**: the docs page markup changed. Re-check `parse_table` against the saved page, using `--table <saved.html>` to iterate offline.
- **`catalog is stale` right after regenerating**: the file was formatted or hand-edited. The generated output is authoritative — re-run the tool rather than editing `catalog.py`.
