# MCP Integration Test Process

A repeatable, end-to-end procedure for verifying that `simple-code-indexer` installs cleanly
into a uv tool environment, is picked up by a real MCP harness, indexes a workspace, answers all
three MCP tools, and shuts down with the session.

**Log files:** `mode: embedded` writes `<workspace>/.simple-ci/log/embed.log`; the default
sidecar mode writes `writer.log` (daemon) and `reader.log` (MCP servers). The commands below
use `reader.log`/`embed.log`; substitute `<log>` when a step applies to either role.

It uses a **double handoff**:

```
Primary agent (Command Code / any coding agent)
  └─ Stage 1: install the uv tool environment + verify from outside
  └─ Stage 2: write a handoff doc
        └─ Human restarts the harness, opens the workspace, gives the handoff to the
           Secondary agent (the LLM inside the harness)
              └─ Stage 3: live MCP session, writes the results doc
        └─ Human closes the harness and brings the results back
  └─ Stage 4: verify shutdown, write the final report, log issues
```

To start a run, the human prompts the primary agent with:

> I want to test MCP integration. Follow the instructions here: `references/mcp-test-process.md`

The primary agent owns §1–§5 and §7. The secondary agent only ever sees the handoff document
(§9.1), which the primary agent fills in with run-specific facts.

---

## Install model (what the commands below assume)

Everything here descends from [ADR-019](../docs/DECISIONS.md#adr-019-pypi-distribution-uv-tool-install-replaces-the-git-copy-install):

| Piece | Value |
|---|---|
| Distribution unit | the wheel; `uv tool install` is the install mechanism |
| Environment root | `uv tool dir` + `simple-code-indexer` (`%APPDATA%\uv\tools\...`, `~/Library/Application Support/uv/tools/...`, `$XDG_DATA_HOME/uv/tools/...`) |
| Interpreter | `<tool-env>\Scripts\pythonw.exe` (Windows, windowless) / `<tool-env>/bin/python` (POSIX) |
| Entry argv | `<interpreter> -m simple_code_indexer serve` |
| Editable (default from a checkout) | `uv tool install --editable <checkout>` — a `.pth` links the working tree |
| Wheel | `simple-code-indexer install --wheel` — a built snapshot in the same environment |
| Ground truth for the flavour | `<tool-env>/uv-receipt.toml` (`editable = …` vs `directory = …`) |
| Deleted by ADR-019 | `setup.py`, `run_server.py`, the `%APPDATA%\simple-code-indexer` copy, `SIMPLE_CI_GIT_PULL`, `setup.install_root` |

Both flavours share one environment, so the harness entry path never changes; only the receipt
records which is live. `simple-code-indexer status` reports `install_kind` after a full `setup`
has recorded it.

---

## Table of Contents

1. [What this test covers](#1-what-this-test-covers)
2. [Roles and rules](#2-roles-and-rules)
3. [Stage 0 — prepare](#3-stage-0--prepare)
4. [Stage 1 — install and verify from outside](#4-stage-1--install-and-verify-from-outside)
5. [Stage 2 — write the handoff](#5-stage-2--write-the-handoff)
6. [Stage 3 — secondary harness session](#6-stage-3--secondary-harness-session)
7. [Stage 4 — return, verify, report](#7-stage-4--return-verify-report)
8. [Troubleshooting](#8-troubleshooting)
9. [Templates](#9-templates)
10. [Definition of done](#10-definition-of-done)
11. [Appendix A — ground-truth query suite](#appendix-a--ground-truth-query-suite)
12. [Appendix B — evidence commands](#appendix-b--evidence-commands)
13. [Appendix C — known issues that affect this test](#appendix-c--known-issues-that-affect-this-test)
14. [Appendix D — conventions](#appendix-d--conventions)

---

## 1. What this test covers

| Area | Verified by |
|---|---|
| One-command install, model download, Docker service | Stage 1 |
| The uv tool environment actually serves MCP | Stage 1 (SDK probe in a scratch workspace) |
| Harness reads the entry **after a restart** and spawns the server | Stage 3 preflight |
| Server indexes the harness's workspace (not home, not `C:\`) | Stage 3 `get_status.workspace` + counts |
| All three tools over the MCP **stdio channel** | Stage 3 query suite |
| Retrieval quality against ground truth | Stage 3 query suite |
| Server exits when the harness closes | Stage 4 process + log check |
| Defects are captured for follow-up | Stage 4 (`docs/ISSUES.md`) |

**Not covered:** protocol conformance against the spec, multi-client concurrency, Qdrant parity
(use the sqlite-vec default unless another backend is the target), and Windows service behaviour.

The four *product* areas that most often fail are: harness entry path/schema, spawn working
directory, vector readiness (rows vs embeddings), and shutdown when a harness keeps a
background service alive. The process below checks each one explicitly.

---

## 2. Roles and rules

**Primary agent** — installation, external verification, handoff authoring, shutdown
verification, final report. Never drives the query suite through the harness itself.

**Secondary agent** — runs inside the target harness (OpenCode, Cursor, VS Code, Codex, …) with
the workspace open. It performs the live session and writes the results document. It must not
change the installation.

**Human** — chooses the harness, restarts it, closes it, and carries the two documents between
the agents.

Rules:

1. **Never start the server in the target workspace from the primary session.** It would create
   `.simple-ci/` before the harness ever runs, which hides pickup failures and can leave a
   workspace lock held. Use a throwaway workspace for external probes.
2. **The secondary agent must exercise the MCP tools exposed by the harness**, not import the
   handlers. Direct handler invocation is a diagnostic fallback only and must be labelled as
   such in the results.
3. **The secondary agent never runs `setup`/`install`/`uninstall` or edits `~/.simple-ci/`.** It
   writes only under `artifacts/`.
4. **One writer per workspace.** A stale server holds the lock and the new one exits with
   `another simple-code-indexer already owns`. Check the process list and log before blaming
   the harness.
5. **Record the server PID and start time before closing the harness.** Shutdown can only be
   proven later against those values.
6. **A failed stage is a valid result.** Capture evidence and continue; do not rewrite the test
   to make it pass.
7. **Know which flavour is installed.** Editable serves the working tree; wheel serves a built
   snapshot. The entry path is identical, so only `uv-receipt.toml` distinguishes them.

---

## 3. Stage 0 — prepare

### 3.1 Ask the human (one batch)

- **Harness**: which MCP client will run the secondary session? It must have a builtin plugin in
  `src/simple_code_indexer/harnesses/` (current set: `claude_code`, `claude_desktop`, `codex`,
  `gemini_cli`, `opencode`, `cursor`, `windsurf`, `vscode`, `zed`, `commandcode`, `mimo`, `goose`,
  `pi`).
  **Cline is not supported** — its builtin plugin was removed on 2026-11-08 after its settings
  file did not survive a restart.
- **Clean slate?** Reinstalling or uninstalling is destructive and machine-wide. Confirm before:
  - `simple-code-indexer uninstall --yes` (removes the uv tool environment, config, services,
    models and recorded MCP entries; add `--keep-models` to keep the GGUFs),
  - deleting `<workspace>/.simple-ci/` (the previous index).
- **Embedding model**: default `--model embeddinggemma2` (768-dim, ~0.6 GB). Other catalog keys
  are in `src/simple_code_indexer/setup_wizard/catalog.py`.
- **Vector store**: default sqlite-vec (vectors inside `index.db`, no extra container). `faiss`
  writes a separate local file; `qdrant` needs a service.
- **Target workspace**: normally the repository under test (the harness must open this folder).

### 3.2 Snapshot the baseline

Record, in the eventual report:

- `git status --short`, `git log --oneline -3`, and whether `HEAD` matches `origin` (see §4.5);
- the harness entry file content (or "absent");
- `~/.simple-ci/config.yaml` (or "absent") and `(uv tool dir)\simple-code-indexer` (or "absent");
- the installed flavour from `uv-receipt.toml` (or "absent");
- `docker ps -a --filter name=simple-ci`/`llamacpp`;
- whether `<workspace>/.simple-ci/` exists;
- any `simple_code_indexer` processes already running.

```powershell
$repo = (Get-Location).Path
$envDir = Join-Path (uv tool dir) 'simple-code-indexer'
git status --short
Get-Content "$env:USERPROFILE\.simple-ci\config.yaml" -ErrorAction SilentlyContinue
Test-Path $envDir
Get-Content (Join-Path $envDir 'uv-receipt.toml') -ErrorAction SilentlyContinue
Test-Path "$repo\.simple-ci"
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*simple_code_indexer*' } |
  Select-Object ProcessId, CreationDate, CommandLine
```

---

## 4. Stage 1 — install and verify from outside

> This stage is not "run the wizard and hope". Every item in §4.3 must be observed before the
> handoff is written.

### 4.1 Dry run first

```powershell
uv run simple-code-indexer setup --dry-run --yes --model embeddinggemma2 --vector-store sqlite-vec --harnesses <name>
```

Confirm the four choices in the output: model, vector store, install flavour/target, harness entry
path. `--yes` only answers prompts; explicit flags win. A dry run needs an already-installed tool
environment (it cannot invent one), so run it after §4.2 on a re-run.

### 4.2 Real install

```powershell
uv run simple-code-indexer setup --yes --model embeddinggemma2 --vector-store sqlite-vec --harnesses <name>
```

This is the whole install: it installs `uv` when missing, installs the checkout into the uv tool
environment, provisions the embedding model/container when asked, probes the real embedding
dimension, writes `~/.simple-ci/config.yaml`, and registers the harness entry. From a source
checkout the install is **editable**, so later edits are live without reinstalling.

If the model must download, run it in the background (see `NOTES.md` for the long-command cap)
and capture the output to a file; the wizard prints its progress, it does not write a log file.

**Install step alone:** when you only need to (re)create the environment — for example after a
`git pull`, or to repoint entries at it — run:

```powershell
uv run simple-code-indexer install
```

`install` force-reinstalls the tool environment and rewrites every entry recorded in
`~/.simple-ci/config.yaml`; it writes no config and touches no index. `install --wheel` builds and
installs a real wheel into the **same** environment instead (the prod-validation switch) — the
entry stays byte-identical.

Verify the environment and its flavour:

```powershell
Select-String -Path (Join-Path $envDir 'uv-receipt.toml') -Pattern 'editable|directory'
& (Join-Path $envDir 'Scripts\python.exe') -c "import simple_code_indexer, pathlib; print(pathlib.Path(simple_code_indexer.__file__).resolve())"
```

Expected for an editable checkout install: `editable = "<repo>"` and an import path under
`<repo>\src\simple_code_indexer\`. A `directory = "<repo>"` line with a `site-packages` import
path means a wheel is live — say so in the report, because the run then tests a snapshot.

### 4.3 External verification checklist

| Check | Evidence |
|---|---|
| Global config | `~/.simple-ci/config.yaml` has `embedding.model`, `embedding.dim`, `vector_store`, a `service` block when one was provisioned, and `setup.install_kind`/`setup.tool_env`/`setup.harnesses` |
| Tool environment | `Join-Path (uv tool dir) 'simple-code-indexer'` exists with `Scripts\pythonw.exe` (Windows) or `bin/python` (POSIX) |
| Flavour | `uv-receipt.toml` says `editable = "<repo>"`; the interpreter imports the tree rather than a copy |
| Container | `docker ps` shows the embed container `Up` with the published port; `docker logs <container>` contains `listening on http://0.0.0.0:8080` (the tail is request logs once it has served) |
| Endpoint | `uv run python tests/service_probe.py` → `embeddings OK dim=... model=...` and `PROBE OK` |
| Tools | the tool environment reports exactly `search_code`, `symbol_lookup`, `get_status` |
| Harness entry | matches the harness schema: `command` + `args` for most JSON clients, or one `command` array for OpenCode; the launcher is `<tool-env>\Scripts\pythonw.exe -m simple_code_indexer serve` on Windows (no console window) and `<tool-env>/bin/python -m simple_code_indexer serve` on POSIX; **no workspace data** — no `WORKSPACE_ROOT`, `cwd`, `INDEX_DB`, or `FAISS_PATH` (ADR-015) |
| Workspace untouched | `<workspace>/.simple-ci` does **not** exist yet |

```powershell
# the installed environment imports the server and the default vector store, and exposes three tools
cd $env:TEMP
& (Join-Path $envDir 'Scripts\python.exe') -c `
  "import simple_code_indexer.server as s, sqlite_vec; print([t.name for t in s._TOOLS]); print(sqlite_vec.__version__ if hasattr(sqlite_vec,'__version__') else 'sqlite_vec loaded')"
```

For `vector_store: faiss`, swap the import for `faiss`; for `qdrant`, the client is the
`qdrant-client` dependency.

### 4.4 Confirm the workspace is inferred, never pinned

The server indexes its process cwd, so the harness must spawn the entry **inside the project**.
The entry itself must stay workspace-free ([ADR-015](../docs/DECISIONS.md#adr-015-harness-entries-are-global-only-no-per-project-data)):
no `WORKSPACE_ROOT`, no `cwd`, no `INDEX_DB` — those keys are per-project data in a file that
serves every project, and a leftover path silently indexes one fixed tree forever after.

Check the workspace after the first tool call in Stage 3 (`get_status.workspace`). If it is wrong,
the harness spawns stdio servers from somewhere else; fix that in the harness (or record it in
`docs/ISSUES.md`), do not edit the entry.

**Debugging exception:** a temporary pin is allowed while diagnosing, and **must be removed
before the session ends.** Remove the `env`/`environment`/`envs` key (and any `cwd`) you added,
or simply re-run `simple-code-indexer setup --harnesses <name>`, which always writes the clean
entry.

### 4.5 Make sure you test the working tree, not the published wheel

There is no launcher-time `git pull` any more: the environment serves whatever the install linked.
An editable install follows the working tree (uncommitted edits included), so what you edited is
what runs — but only after `uv run simple-code-indexer install` has linked the checkout and the
harness has restarted.

```powershell
git rev-parse HEAD
git ls-remote origin refs/heads/master
```

If the checkout has uncommitted changes, say so in the report ("tested the working tree at
`<sha>` + local edits"). If you deliberately installed a wheel, the report must say "tested the
built wheel at `<sha>`" instead, because the environment no longer follows your edits.

### 4.6 Prove the server works before blaming the harness

Drive the installed launcher with the official MCP SDK client against a throwaway workspace.
The probe must cover the whole lifecycle, not just "it starts":

1. **Indexing** — seed a fresh workspace with several languages (`.py`, `.cpp`, `.vimrc`),
   filename matches (`Dockerfile`, `CMakeLists.txt`), a `.gitignore`d file, an ignored directory
   (`.venv`), a disallowed format (`.md`, `.json`), plus empty, syntactically broken, Unicode,
   and >300-line files. Poll `get_status` until `last_sweep` is set and the counts are stable;
   `files_indexed` must equal the enumerator count, and the ignored/disallowed paths must be
   absent from SQLite. Wait until `pending_embeddings` reaches 0.
2. **Querying** — run Appendix A plus the edge suite: exact lexical hits, an unrelated semantic
   query, duplicate and nonexistent symbols, empty query/symbol, punctuation-only input, and
   `limit=0`/`limit=1000` clamps. No call may raise or hang.
3. **Watching** — create, modify, and delete a file and assert the index follows within ~5 s;
   append to `.gitignore` and assert the sweep drops the now-ignored file. Leave the server idle
   for ~30 s and assert the log is not growing from its own writes (ISS-9: the watcher currently
   logs `watcher: file modified …<log>` and re-triggers itself).
4. **Startup/shutdown** — close stdin; expect exit code 0, `workspace lock released`,
   `shutting down after Ns`, `vector store flushed`, and `final index:`. Restart in the same
   workspace and expect the reconcile log `checked=N indexed≈0 unchanged≈N`. While a server is
   running, a second one must exit 1 with `another simple-code-indexer already owns`.
5. **Logging** — assert the session log slice (from the `starting (pid=...)` banner) contains the
   startup banner, config/workspace/embed lines, lock acquired, services, vector store, watcher
   ready, `serving on stdio`, a `tool=` line per query, `indexed ... in N ms` per fixture, the
   sweep summary, and the shutdown lines; and no unexpected `ERROR`/`CRITICAL`/`Traceback`, and
   no repeated `watcher: file modified …<log>` self-events.

A minimal driver is in Appendix B.2. If the probe cannot assert one of these from the
active log file (`reader.log` in sidecar mode, `embed.log` in embedded mode),
that is a logging gap: add the missing log line before writing the handoff.

### 4.7 Record the installed entry

Paste the entry JSON verbatim into the handoff and the final report. Note the exact path, the
command, the `SIMPLE_CI_HARNESS` marker, and whether the environment is editable or wheel.

---

## 5. Stage 2 — write the handoff

Create `artifacts/mcp-handoff.md` from the template in §9.1. It must contain:

1. **Facts table** — workspace, config path, tool environment + flavour, model/endpoint/dim,
   vector store, entry path, expected indexable file count, index/log paths.
2. **Pre-verified baseline** — the result of §4.6, so a harness failure is not mistaken for a
   server failure.
3. **Preflight** — confirm the server is listed/connected in the harness UI; confirm the three
   tools; record the server `ProcessId` **and** `CreationDate`.
4. **Baseline `get_status`** — paste the full JSON and list the assertions (workspace, store,
   index path, single config source, log file, watcher).
5. **Indexing watch** — poll until `files_indexed` and `chunks_indexed` are stable for two
   reads; record every sample; use the expected count from Appendix A (recompute it at handoff
   time). Include the **vectors-lag** warning: counts are SQLite rows, so check
   `pending_embeddings`/`vectors_indexed`; retry a 0-hit semantic query once after 10–15 s and
   record both attempts. Do **not** claim `indexed≈0` from counts alone: compare each file's
   stored `mtime`/`size` with the filesystem (or accept `indexed>0` and record it). The
   2026-11-10 run re-indexed 5 files that had changed after the previous index build even though
   the row counts looked stable.
6. **Query suite with ground truth** — lexical, semantic, symbol, a nonexistent symbol, an
   unrelated semantic query, and the edge suite in Appendix A. Regenerate ground truth for the
   target repo.
7. **Log/artifact inspection** — the current session slice of the active log
   (`reader.log` in sidecar mode, `embed.log` in embedded mode) (from its
   `starting (pid=...)` banner, not the raw tail across sessions), index/vector/log sizes, and
   sqlite counts; assert the log contract from §4.6.5.
8. **Results template** — the exact sections and verdict table to fill in.
9. **Failure path** — missing entry, wrong workspace, held lock, hanging tool call (include the
   stderr-pipe note), and "still write the results document".
10. **Finish** — record the PID, write `artifacts/mcp-results.md`, tell the human to close the
    harness, and run no further MCP calls.

**Ground-truth rule:** every expected `file:line` must be verified at handoff time
(`git grep -n` or `Select-String`); line numbers drift. Prefer file-level expectations when lines
move often.

The human then restarts the harness (required — entries are read at startup), opens the target
workspace, and gives the secondary agent:

> Follow `artifacts/mcp-handoff.md` and write `artifacts/mcp-results.md`.

**Multi-harness variant (verified 2026-11-13 with Pi + Goose + OpenCode):** give the same
handoff to every harness, have each agent write its own
`artifacts/mcp-results-<harness>.md`, and assert one shared `writer_pid`/`daemon_endpoint`
with `sessions` equal to the number of harnesses. Treat `writer.log` as the authoritative
session timeline — `get_status.sessions` is point-in-time, so an agent that queries before
its peers connect can legitimately see a smaller number. Include `pythonw.exe` in Windows
process checks (the venv reader has no console window), and record the maximum `sessions`
observed immediately before writing results. For OpenCode, quit the UI **and** run
`opencode service stop`; the reader watches the service, not the window.

---

## 6. Stage 3 — secondary harness session

The secondary agent follows the handoff. Order matters:

1. **Preflight:** server listed and connected; exactly three tools; record PID + start time.
   - One launch can appear as several processes: on Windows the tool environment's `pythonw.exe`
     is a redirector that re-executes the base `pythonw.exe`; on POSIX `uv`-style trampolines can
     add a layer. The sidecar daemon is the exception: it is spawned as the base interpreter with
     the reader's `sys.path` (`sidecar.client._daemon_command`), so it has no launcher parent.
     Count *server instances* by the `index.db` lock / parent chain, not by a raw interpreter
     count, and include `pythonw.exe` in the filter.
2. **`get_status`:** paste the full JSON; stop if `workspace` is wrong.
3. **Index the workspace:** poll until counts are stable; record the timeline and
   `pending_embeddings`/`vectors_indexed`. Do not rely on `vector_store_ok` alone for vector
   readiness.
4. **Query suite:** call the tools through the harness. Run Appendix A including its edge suite;
   record top-3 `file:line` + score and PASS/FAIL per query. If the harness cannot expose the
   tools, record FAIL and stop — a direct handler run may be added as diagnostic evidence,
   clearly labelled.
5. **Inspect:** the current session slice of the active log (`reader.log` in sidecar mode,
   `embed.log` in embedded mode) from `starting (pid=...)` — startup
   lines, `serving on stdio`, `tool=` lines, the sweep summary, shutdown lines, errors — plus
   artifact sizes and sqlite counts.
6. **Write `artifacts/mcp-results.md`** using the template. Include the raw JSON and log lines.
7. **Tell the human to close the harness.** Leave the server running; Stage 4 needs the
   shutdown evidence.

---

## 7. Stage 4 — return, verify, report

### 7.1 Shutdown verification

Compare the recorded PID/start time with the live process list, then read the log tail:

```powershell
$repo = (Get-Location).Path
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*simple_code_indexer*' } |
  Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine
Get-Content "$repo\.simple-ci\log\reader.log" -Tail 40   # sidecar (default)
Get-Content "$repo\.simple-ci\log\embed.log" -Tail 40    # mode: embedded
```

- **Pass:** the recorded PID is gone and the **current session slice** of the log (from its
  `starting (pid=...)` banner) contains, in order, `workspace lock released`,
  `shutting down after Ns`, `vector store flushed`, and `final index:`. The raw tail may also
  contain earlier sessions; do not anchor on the absolute last line.
- **Fail (processes remain):** first read the server's `parent watchdog: watching ...` line. It
  names the single harness process; anything above it (the UI, `uv`, the venv trampoline) is
  deliberately not watched, so a reused `opencode-cli serve --service` keeping the server alive
  is expected. If the harness process itself is gone and the server survives, treat it as a
  regression. Otherwise look for a harness background service that holds the child's stdin (an
  extension host, a desktop helper): closing the window does not close the pipe. Record the
  parent, then stop the process tree only with the human's consent:

  ```powershell
  taskkill /PID <trampoline-or-parent> /T /F
  ```

  Log it as a lifecycle issue. A clean stdin close has been proven to shut the server down, so
  do not call this a broken `finally`.

### 7.2 Validate the results

- sqlite counts equal `get_status` (`files_indexed`, `symbols_indexed`, `chunks_indexed` map to
  the `files`, `symbols`, `chunks` tables);
- `files_indexed` is close to the computed expected count (drift is fine — report it);
- the current session slice of the active log file has no unexpected `ERROR`/`CRITICAL`/traceback (a
  deliberate duplicate-server lock refusal is the one expected `ERROR`);
- every query PASS/FAIL is backed by a `file:line` and score;
- note which status fields came from a direct-handler invocation (they read
  `watcher_alive=false`, `log_file=null`, etc.) versus the live server.

### 7.3 Write `artifacts/mcp-final-report.md` (§9.3)

Verdict per stage, evidence, what worked/didn't, recommendations, and the list of issues filed.
Correct any misreadings from the results doc (for example: trampoline pairs are not duplicate
servers; direct invocation is not an MCP-channel test).

### 7.4 Record issues and notes

- Add every defect/gap to `docs/ISSUES.md` (next free `ISS-n`, symptom / where flagged / cause /
  suggested fix). Delete entries once fixed.
- Add operational gotchas (harness quirks, process behaviour, paths) to `docs/NOTES.md`.
- Add user-visible changes to `docs/CHANGELOG.md`.
- Update `docs/HANDOFF.md` if the work is incomplete or multi-session.

### 7.5 Cleanup (ask first)

- Leave the tool environment installed for daily use, **or** `simple-code-indexer uninstall --yes`
  (`--keep-models` to keep the GGUFs). Uninstall is record-driven: it removes the uv tool
  environment, the config, generated compose files, downloaded models and the recorded MCP
  entries, and never touches workspace `.simple-ci/` indexes.
- Stop the embedding container if the test should not leave it running.
- Remove any debugging `WORKSPACE_ROOT`/`cwd` additions so the entries go back to the stock,
  workspace-free form (ADR-015). Re-running `simple-code-indexer setup --harnesses <name>`
  does it in one step; verify with `get_status.workspace` in a fresh session.
- If you installed a wheel, restore the editable link with `uv run simple-code-indexer install`.
- If code changed: `uv run ruff check .` → `uv run pyright` → `uv run pytest` (see `NOTES.md`
  for the writable `--basetemp` on this host).

---

## 8. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Server absent from the harness after restart | entry path/schema wrong; harness overwrote or deleted the file; restart not done | read the entry file, validate JSON, check the harness MCP log, restart once, add an issue |
| Entry launches nothing | `<tool-env>\Scripts\pythonw.exe` missing — the tool environment was never installed, or `uv tool uninstall` ran | `uv run simple-code-indexer install`, then re-check `uv tool dir` |
| Edits are not live in a harness session | a wheel flavour is installed, or the session predates the reinstall | read `uv-receipt.toml`; run `simple-code-indexer install`; restart the harness |
| Server starts then exits immediately | home workspace rejected, bad config YAML, lock held | read the active log (`reader.log`/`writer.log` in sidecar, `embed.log` in embedded); look for `another simple-code-indexer already owns` or a config error |
| `get_status.workspace` is not the target | harness spawns with another cwd | fix the harness spawn cwd (or its config scope); a temporary `WORKSPACE_ROOT` is for debugging only and must be removed (ADR-015) |
| `files_indexed`/`chunks_indexed` stay 0 | workspace wrong, walk pruned everything, or a database error | compare `get_status.workspace` with the target; check the `sweep:` line and `failed to index`/tracebacks in the session log |
| `chunks_indexed` climbs but `pending_embeddings` never falls | embedding endpoint down or wrong model/dim | `tests/service_probe.py`, container logs, `embed_ok`/`embedding failed` lines |
| Semantic query returns 0 hits | vectors still being written, or empty index | check `pending_embeddings` and the vector-store line; for sqlite-vec verify `vectors_indexed` matches `vec_chunks`; wait 10–15 s and retry once |
| A tool call hangs and the log's last line is an INFO record | harness is not draining the server's stderr pipe | record it; the server blocks in a log write on the serve thread. Keep the stderr-drain rule in `NOTES.md` |
| Server survives closing the harness | check the server's `parent watchdog: watching` line: if the UI is absent, the service was started detached **or reused from an earlier UI** (the new UI is a sibling) | record the parent, stop the service/tree with consent; file a lifecycle issue only when the UI **was** in the watched list |
| Several processes per session | Windows: tool-env `pythonw.exe` → base `pythonw.exe`; POSIX: trampoline → base interpreter | count server instances by the `index.db` lock, not processes; include `pythonw.exe` in the filter |
| One expected file missing from top-3 | retrieval quality | record FAIL with hits/scores; file an issue; do not retry the same query endlessly |

---

## 9. Templates

### 9.1 `artifacts/mcp-handoff.md`

```markdown
# Stage 2 handoff — MCP integration test (<harness>, <date>)

Audience: the LLM running in <harness> with <workspace> open.
Do not run setup/install/uninstall, edit ~/.simple-ci, delete .simple-ci, or kill the server.
Write only under artifacts/.

## Facts
| Item | Value |
|---|---|
| Workspace | <abs path> |
| Config | <~/.simple-ci/config.yaml> |
| Tool environment | <(uv tool dir)\simple-code-indexer> |
| Install flavour | editable (`editable = "<repo>"`) / wheel (`directory = "<repo>"`) |
| Launcher | <tool-env>\Scripts\pythonw.exe -m simple_code_indexer serve |
| Embedding | <url> / <model> / <dim> |
| Vector store | <sqlite-vec|faiss|qdrant> |
| Entry | <path>, key/dotted path <name> |
| Indexable files (expected) | <N> |
| Index / log | <.simple-ci/...> |

## Pre-verified baseline (outside the harness)
<result of the SDK probe; note the clean shutdown evidence>

## Preflight (do these first)
1. Server listed/connected; screen text: ___
2. Tools: search_code, symbol_lookup, get_status
3. Powershell: Get-CimInstance ... -> record ProcessId + CreationDate
   (Windows: tool-env pythonw.exe -> base pythonw.exe; the sidecar daemon is the base
    interpreter with a sys.path bootstrap)

## Baseline get_status
<paste full JSON; assertions: workspace, vector_store, vector_index, config_files, log_file>

## Indexing watch
Poll get_status every 20-30 s until files_indexed and chunks_indexed are stable twice.
Record each sample. Expected files ≈ <N>. Vectors lag the counts: check pending_embeddings
and retry a 0-hit semantic query once after 10-15 s and record both attempts.

## Query suite
| id | tool | query | expected file |
|---|---|---|---|
| L1 | search_code lexical | <q> | <file> |
| ... | | | |
Run Appendix A plus its edge suite; record #hits, top-3 file:line+score, PASS/FAIL.

## Inspect
- The current session slice of "<workspace>\.simple-ci\log\reader.log" (sidecar default;
  `embed.log` in embedded mode) (from its last
  `starting (pid=...)` banner), not the raw tail across sessions
- sizes of index.db / vectors.faiss / reader.log / writer.log
- sqlite counts must match get_status

## Results file
Write artifacts/mcp-results.md with: verdict table, environment (PID/start time, raw JSON),
indexing timeline, query table, log evidence, artifact sizes, problems.

## Failure path
<missing entry / wrong workspace / held lock / hanging call (stderr note) — still write results>

## Finish
Record PID + start time, write the results doc, ask the human to close <harness>, run no
further MCP calls.
```

### 9.2 `artifacts/mcp-results.md`

```markdown
# Stage 2 results — MCP integration test (<harness>, <date>)

## Verdict
- Server picked up on restart: PASS/FAIL
- Workspace/index correctness: PASS/FAIL
- Indexing completed: PASS/FAIL (files=, symbols=, chunks=, elapsed=)
- Lexical: N/M | Semantic: N/M | Symbol: N/M
- Shutdown evidence recorded: YES/NO (PID + start time)

## Environment
(tool environment + flavour, server status, tool list, PID/CreationDate, baseline+final
 get_status JSON; mark fields that came from direct handler invocation)

## Indexing timeline
| t | files | symbols | chunks | notes |

## Query results
| id | tool | query | #hits | top-3 file:line + score | PASS/FAIL | notes |

## Log evidence
(session slice: startup lines, lock, serving, sweep summary, tool= lines, semantic/vector lines,
watchdog line, errors)

## Artifacts
(index.db / vectors.faiss / writer.log / reader.log sizes; sqlite counts)

## Problems observed
1. symptom / command / raw output / suspected cause
```

### 9.3 `artifacts/mcp-final-report.md`

```markdown
# End-to-end MCP test — final report (<date>)
## Verdict per stage (install / pickup / indexing / retrieval / shutdown)
## Install evidence (uv tool dir, uv-receipt.toml flavour, service probe)
## Indexing evidence (counts, elapsed, sizes, log)
## Retrieval results (table; expectations vs hits)
## Shutdown evidence (PIDs, log lines, cleanup)
## What worked / what didn't
## Issues filed (ISS-n) and notes/changelog updates
## Recommendations
```

---

## 10. Definition of done

- [ ] Dry run and real install completed with explicit model/store/harness flags.
- [ ] The uv tool environment exists; `uv-receipt.toml` shows `editable = "<repo>"` (or the
      report states that a wheel was tested).
- [ ] `simple-code-indexer install` ran after the last edit when a wheel flavour was in use.
- [ ] §4.3 checklist observed and recorded (config, tool environment, container, probe, entry).
- [ ] §4.5 provenance check done: the report names the commit (and local edits) or the built wheel.
- [ ] §4.6 comprehensive SDK probe passed in a scratch workspace: indexing, ignored/disallowed
      paths, query edge cases, watch create/modify/delete, lock refusal, and clean shutdown.
- [ ] Log contract asserted from the session slice; any missing evidence added as logging.
- [ ] Handoff written with verified ground truth, expected count, PID instruction, results
      template, failure path.
- [ ] Secondary session recorded PID/start time and wrote results with raw evidence.
- [ ] Shutdown verified against the recorded PID and log lines; stragglers explained.
- [ ] Final report written to `artifacts/`.
- [ ] `docs/ISSUES.md` updated; `docs/NOTES.md` updated; `docs/CHANGELOG.md` updated if
      user-visible.
- [ ] `ruff check`, `pyright`, `pytest` pass if code changed.

---

## Appendix A — ground-truth query suite

Use this suite for this repository (line numbers drift; verify before handing off). Replace it
with an equivalent suite for another target repo.

| id | tool | query | expected |
|---|---|---|---|
| L1 | lexical | `iter_workspace_files` | `src/simple_code_indexer/indexer.py` (def ~line 94; tests also match — top-3) |
| L2 | lexical | `LLAMA_ARG_POOLING` | `src/simple_code_indexer/setup_wizard/__init__.py` (~line 578) or `tests/test_setup_wizard.py` (the compose `.yml` is not indexed) |
| L3 | lexical | `vector_label_seq` | `src/simple_code_indexer/db.py` (~line 395) |
| S1 | semantic | how does the indexer avoid walking into virtualenv and cache directories | `src/simple_code_indexer/indexer.py` (regression probe for the 30-line chunker; must PASS now) |
| S2 | semantic | prevent two indexer servers from writing to the same workspace at once | `workspace_lock.py` or `server.py` |
| S3 | semantic | merge Codex TOML config using marker comments so user comments survive | `harnesses/_toml.py` |
| S4 | semantic | allocate monotonic vector labels so ids are never reused | `db.py` or `sqlite_vec_store.py` / `faiss_store.py` |
| S5 | semantic | stop the server when the launching harness process dies while stdin stays open | `parent_watch.py` or `server.py` |
| Y1 | symbol | `iter_workspace_files` | `indexer.py` |
| Y2 | symbol | `WorkspaceLock` | `workspace_lock.py` (~line 30) |
| Y3 | symbol | `_acquire_workspace_lock` | `server.py` (~line 384) |
| Y4 | symbol | `DefinitelyNotARealSymbolXYZ` | `found: false` |
| U1 | semantic | how to bake sourdough bread | non-empty code chunks, clearly lower scores |

Edge suite (same workspace, run through the harness where possible):

| id | tool | input | expected |
|---|---|---|---|
| E1 | lexical | empty string | `hits: []`, `source: lexical`, no error |
| E2 | lexical | punctuation/operators only (`AND OR " (*)`) | no error; zero or sane hits (tokens are stripped) |
| E3 | lexical | `iter_workspace_files` with `limit: 0` | at most 1 hit (clamped to 1) |
| E4 | lexical | `iter_workspace_files` with `limit: 1000` | at most 50 hits (clamped to 50) |
| E5 | symbol | empty string | `found: false`, `matches: []` (empty names are rejected) |
| E6 | symbol | `iter_workspace` | prefix `LIKE` fallback returns `iter_workspace_files` |
| E7 | symbol | `main` | `found: true` `matches` envelope with several files |
| E8 | semantic | empty string | `hits: []`, no embed call |
| E9 | semantic | `zzzzzzzzzzzzzzzz` | no crash; nearest-chunk hits are allowed |
| E10 | get_status | `{}` | full JSON, no error |

`search_code`'s lexical path tokenizes to `\w+` before FTS5, so operator characters must never
produce an SQL/FTS error. `symbol_lookup` falls back to a prefix `LIKE` when the exact name has
no row — a prefix query can legitimately return many matches.

Regenerating ground truth:

```powershell
# lexical anchor exists? (git grep is tracked-files-only; rg -n also works)
git grep -n "iter_workspace_files" -- src
# symbol definition site?
git grep -n -E "^(def|class) WorkspaceLock" -- src
# semantic anchors: read the module and pick a distinctive behaviour, then confirm the file
```

Expected indexable count: run the enumerator without creating an index (read-only):

```powershell
uv run python -c "from simple_code_indexer.config import load_settings; from simple_code_indexer import indexer; print(len(list(indexer.iter_workspace_files(load_settings()))))"
```

## Appendix B — evidence commands

### B.1 Process and workspace state (Windows)

```powershell
Get-CimInstance Win32_Process -Filter "name='python.exe' or name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*simple_code_indexer*' } |
  Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine | Format-List

$envDir = Join-Path (uv tool dir) 'simple-code-indexer'
Get-Content (Join-Path $envDir 'uv-receipt.toml')

Get-ChildItem "<workspace>\.simple-ci" -Recurse | Select-Object FullName, Length
Get-Content "<workspace>\.simple-ci\log\reader.log" -Tail 120   # sidecar (default)
Get-Content "<workspace>\.simple-ci\log\embed.log" -Tail 120    # mode: embedded
```

POSIX equivalent: `ps -eo pid,ppid,lstart,args | grep simple_code_indexer`, `ls -la .simple-ci`,
`tail -n 120 .simple-ci/log/reader.log` (or `embed.log` in embedded mode).

### B.2 External SDK probe (primary agent, scratch workspace)

```python
import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# `uv tool dir` + simple-code-indexer; scripts/ on Windows, bin/ elsewhere.
TOOL_ENV = r"C:\Users\<you>\AppData\Roaming\uv\tools\simple-code-indexer"
params = StdioServerParameters(
    # Windows entry: the environment's GUI-subsystem interpreter, so no console window opens.
    command=TOOL_ENV + r"\Scripts\pythonw.exe",
    args=["-m", "simple_code_indexer", "serve"],
    # cwd alone selects the workspace; WORKSPACE_ROOT is only a debugging override
    # and must never be written into a harness entry (ADR-015).
    cwd=r"<scratch workspace>",
)

async def main():
    with anyio.fail_after(110), open(r"<scratch>\stderr.log", "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                print([t.name for t in (await s.list_tools()).tools])
                print((await s.call_tool("get_status", {})).content[0].text)
                # symbol_lookup + lexical + semantic, then close the context;
                # the client closes stdin and the server must exit cleanly.

anyio.run(main)
```

Important: send the child's stderr to a **file** (as above). A harness or probe that pipes
stderr and never drains it will eventually block the server; redirect stderr to a file or drain
it (`tests/mcp_probe.py` does the latter on a thread).

## Appendix C — known issues that affect this test

Check `docs/ISSUES.md` before starting. As of 2026-11-11 the earlier ISS entries (including
ISS-10) are fixed and removed. Keep these fixed cases in the check suite as regressions:

- **ISS-8 (fixed)** — `symbol_lookup` with an empty symbol must return no matches; record it in
  the edge suite (E5).
- **ISS-9 (fixed)** — the watcher must not log its own active-log-file writes; an idle server must
  not grow its log continuously. Check for it in the watch/logging step.

The standing operational constraints live in `NOTES.md`: drain the child's stderr, watch the
harness process rather than assuming a UI ancestor (a reused service is the harness), and check
`pending_embeddings` while vectors catch up. If a run finds a new defect, add it to
`docs/ISSUES.md` and reference it here.

## Appendix D — conventions

- Reports live in `artifacts/` (gitignored, throwaway). Reference docs live in `references/`.
- Name run documents `artifacts/mcp-handoff.md`, `artifacts/mcp-results.md`,
  `artifacts/mcp-final-report.md`; add a date suffix for repeat runs.
- Log new defects in `docs/ISSUES.md` with the next free `ISS-n`; delete them when fixed.
- Add operational gotchas to `docs/NOTES.md`; user-visible changes to `docs/CHANGELOG.md`.
