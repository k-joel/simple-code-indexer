# ACP End-to-End Test Process

A repeatable, **fully automated** procedure for verifying that the `simple-code-indexer`
checkout you are in is picked up by a real ACP harness, indexes its own workspace, answers all
three MCP tools, and shuts down with the session.

> **Target: the current directory.** Every stage below runs from the checkout under test
> (`$repo = (Get-Location).Path`) and launches
> `$repo\.venv\Scripts\pythonw.exe $repo\run_server.py`. Do **not** test or refresh the copy
> under `%APPDATA%\simple-code-indexer`: it is a separate install for the user's harnesses and is
> never the subject of this procedure.

This is the automation-first sibling of [`mcp-test-process.md`](./mcp-test-process.md). That
document hands the live session to a human-driven agent inside a GUI harness. This one has **no
human in the loop at all**: the host LLM spawns the harness as an ACP subprocess, drives it with
JSON-RPC, and asserts on the tool payloads that come back.

**Driver:** [`tests/acp_probe.py`](../tests/acp_probe.py) — standard library only.
**Reference:** [`opencode-acp-mode.md`](./opencode-acp-mode.md) — what ACP mode is and how it works.

---

## Table of Contents

1. [What this test covers](#1-what-this-test-covers)
2. [Why ACP makes this automatable](#2-why-acp-makes-this-automatable)
3. [Roles and rules](#3-roles-and-rules)
4. [Stage 0 — prepare](#4-stage-0--prepare)
5. [Stage 1 — prove the server from outside](#5-stage-1--prove-the-server-from-outside)
6. [Stage 2 — run the ACP driver](#6-stage-2--run-the-acp-driver)
7. [Stage 3 — read the evidence](#7-stage-3--read-the-evidence)
8. [Stage 4 — teardown and report](#8-stage-4--teardown-and-report)
9. [Host harness compatibility](#9-host-harness-compatibility)
10. [Troubleshooting](#10-troubleshooting)
11. [Templates](#11-templates)
12. [Definition of done](#12-definition-of-done)
13. [Appendix A — how the driver works](#appendix-a--how-the-driver-works)
14. [Appendix B — ground-truth query suite](#appendix-b--ground-truth-query-suite)
15. [Appendix C — evidence commands](#appendix-c--evidence-commands)
16. [Appendix D — known constraints](#appendix-d--known-constraints)

---

## 1. What this test covers

| Area | Verified by |
|---|---|
| Dependencies synced, embedding service reachable | §4, §5 |
| The checkout's venv actually serves MCP | §5 (SDK probe in the checkout) |
| An ACP harness spawns the server from the session `cwd` | Stage 2 `workspace is the target` |
| Per-session MCP injection works (no config edit) | Stage 2 `session created` + tool calls |
| Server indexes the harness's workspace (not home, not `C:\`) | Stage 2 `get_status` + counts |
| File watcher picks up a new file without a restart | Stage 2 `watcher indexed the new file` |
| All three tools, over ACP, in a real model turn | Stage 2 query checks |
| Retrieval quality against ground truth | Stage 2 + Appendix B |
| Vectors are written, not just rows | Stage 2 `semantic search returned hits` |
| Single writer per workspace (sidecar) | Stage 2 `one registered session`, `daemon.json` |
| Server exits when the harness closes stdin | Stage 2 `agent exited 0 on stdin close` |
| Run evidence is durable and reviewable afterwards | Stage 4 `artifacts/acp-results.md` |
| Defects are captured for follow-up | Stage 4 (`docs/ISSUES.md`) |

**Not covered:** protocol conformance against the ACP spec, multi-client concurrency on one
workspace (that is the GUI multi-harness variant in `mcp-test-process.md` §5), Qdrant parity, and
Windows service behaviour.

The four product areas that most often fail are the same as the MCP test: harness entry
path/schema, spawn working directory, vector readiness (rows vs embeddings), and shutdown when a
harness keeps a background service alive. ACP changes *how* each is exercised, not *whether*:

- **Entry schema** → the client supplies the MCP server on `session/new`, so a bad launcher path
  shows up as "3 tools never connected" rather than "entry missing from the UI".
- **Spawn cwd** → `get_status.workspace` must equal the session `cwd`, because that is the only
  thing that selects the workspace.
- **Vector readiness** → semantic hits can lag the row counts; the driver retries once.
- **Shutdown** → closing stdin is the documented ACP shutdown, and ACP never uses the shared
  background service, so there is no `serve --service` to keep the child alive.

---

## 2. Why ACP makes this automatable

In the MCP test the harness's agent is a model behind a GUI, so a human has to carry documents
between two sessions. ACP removes that: the harness is a **subprocess** speaking JSON-RPC on
stdio, so the host LLM can spawn it, prompt it, and read its tool results directly.

Three properties make the automation reliable:

1. **`session/new` accepts `mcpServers`.** The driver injects `simple-code-indexer` per session
   under its canonical name. In OpenCode 2.2.5 the **configured** entry of the same name still
   starts briefly before the injected one replaces it, and that first reader can spawn the writer
   daemon from the configured (for example `%APPDATA%`) launcher. For a checkout-only run, mask
   the configured entry first (Stage 6.2 does this, with a byte-exact backup); the final
   `get_status.sessions` check alone cannot tell which launcher owns the writer.
2. **Tool results arrive as structured payloads** on `tool_call_update`
   (`content[].content.text`), not as prose. The driver parses those payloads and asserts on
   fields — the model's summary is irrelevant.
3. **Permissions are answerable programmatically.** Every `session/request_permission` is
   answered `allow_once`, so a run never blocks on a UI.

What ACP does *not* remove is model variance: the same prompt can skip a tool call on one attempt
and take it on the next. The driver therefore retries each prompt once and polls readiness instead
of sampling once. See Appendix D.

---

## 3. Roles and rules

**Host agent** (Command Code, or any agent with shell access) — runs every stage below. It never
needs a second session and never needs a restart.

**ACP harness** (OpenCode by default) — a subprocess spawned by the driver. It carries the model,
the tools, and the file writes. It is not configured by this test.

**Human** — none required. Only intervene if §4 finds a clean-slate decision that is destructive.

Rules:

1. **The workspace is the current directory.** Run every stage from the checkout under test;
   `$repo = (Get-Location).Path` throughout. The run deletes and rebuilds `$repo\.simple-ci\`,
   adds a fixture, then deletes the fixture. A scratch directory is only for a disposable smoke
   run, never the default.
2. **Never pin the workspace in a harness entry.** The driver passes `cwd` on `session/new`; the
   entry stays workspace-free
   ([ADR-015](../docs/DECISIONS.md#adr-015-harness-entries-are-global-only-no-per-project-data)).
   `get_status.workspace` is how you confirm what actually happened.
3. **Assert on payloads, never on prose.** A model claiming success is not evidence; the JSON the
   tool returned is.
4. **One writer per workspace.** Two readers on one workspace are visible as
   `get_status.sessions: 2`. The driver injects under the canonical `simple-code-indexer` name to
   avoid that; a differently-named copy would add a second reader.
5. **A failed stage is a valid result.** Capture evidence, file it, continue. Do not weaken a
   check to make the run green.
6. **Drain the child's stderr.** The driver does this on a thread. Any replacement must too — an
   unread pipe blocks the harness inside a log write, which looks exactly like an agent hang.
7. **Every run writes `artifacts/acp-results.md`** (§8.3), pass or fail, the same way the MCP test
   writes `artifacts/mcp-results.md`. The driver's terminal output is not the record; the results
   document is. A run that ends without one is unfinished.

---

## 4. Stage 0 — prepare

### 4.1 Confirm the harness exists

```powershell
# OpenCode (default). The desktop bundle is not on PATH:
& "$env:LOCALAPPDATA\Programs\ai.opencode.desktop\resources\opencode-cli.exe" --version
# or, if installed globally:
opencode --version
```

Expect `2.2.5` or newer. `opencode acp --help` must list the `acp` subcommand.

```powershell
# Command Code (alternative harness):
& "$env:APPDATA\npm\cmdc.cmd" --version
& "$env:APPDATA\npm\cmdc.cmd" acp --help
```

### 4.2 Confirm a usable model

```powershell
opencode models            # lists models; `opencode/*-free` need no login
opencode auth list         # "No authenticated integrations" is fine for the free models
```

The free models answer prompts without credentials (verified on this host). They are also the
least reliable at calling tools, which is why the driver retries. Pin a paid/authenticated model
with `--model` when one is available.

### 4.3 Snapshot the baseline

Record for the report:

```powershell
$repo = (Get-Location).Path
git status --short
git log --oneline -3
Get-Content "$env:USERPROFILE\.simple-ci\config.yaml" -ErrorAction SilentlyContinue
Test-Path "$repo\.simple-ci\index.db"
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -in @('python.exe','pythonw.exe','uv.exe') -and $_.CommandLine -like '*run_server.py*' } |
  Select-Object ProcessId, CreationDate, CommandLine
docker ps --filter name=simple-ci
```

`$repo\.simple-ci\index.db` is the pre-run index; Stage 6.1 deletes it.

### 4.4 Ask the human only for destructive choices

- deleting an existing `<repo>\.simple-ci\` index — this procedure requires a clean rebuild, so
  confirm before removing a populated one,
- stopping the embedding container.

The `%APPDATA%\simple-code-indexer` install is never touched: this procedure does not run
`setup.py` and does not launch that copy.

Everything else runs unattended.

---

## 5. Stage 1 — prove the server from outside

Do this **before** blaming the harness. If the ACP run fails, you need to know whether the server
or the harness broke.

### 5.1 Sync the checkout (there is no install step)

The checkout is the server under test; only its dependencies need refreshing:

```powershell
uv sync
```

Do **not** run `python setup.py` / `--install-only` here: those write and configure
`%APPDATA%\simple-code-indexer`, which this procedure never launches. The launcher is the
checkout's own `.venv\Scripts\pythonw.exe` beside its `run_server.py`.

### 5.2 Probe the services

```powershell
uv run python tests/service_probe.py     # expect: embeddings OK dim=... / PROBE OK
```

### 5.3 Prove the checkout launcher serves MCP

```powershell
$repo = (Get-Location).Path
uv run python tests/mcp_probe.py `
  "$repo\.venv\Scripts\pythonw.exe" "$repo\run_server.py"
```

Run it from the checkout (the cwd is the workspace). Expect `PROBE OK` and exactly three tools.
`mcp_probe.py` drains stderr and bounds the run, so a failure is a verdict, not a hang.

### 5.4 Confirm the ACP-specific preconditions

| Check | Evidence |
|---|---|
| Launcher exists | `<repo>\.venv\Scripts\pythonw.exe` and `<repo>\run_server.py` (Windows); `uv` + `<repo>/run_server.py` (POSIX) |
| Workspace clean | `<repo>\.simple-ci\index.db` and `vectors.faiss` deleted (Stage 6.1), no `run_server.py` process for it |
| Harness version | `opencode --version` (2.2.5+) and `opencode acp --help` |
| Model reachable | one prompt answered in the TUI or via `opencode run` |

---

## 6. Stage 2 — run the ACP driver

### 6.1 Workspace: this checkout, with a clean index

```powershell
$repo = (Get-Location).Path

# Delete the existing index: rows and vectors must be rebuilt together.
Remove-Item "$repo\.simple-ci\index.db", "$repo\.simple-ci\index.db-wal",
  "$repo\.simple-ci\index.db-shm", "$repo\.simple-ci\vectors.faiss" `
  -Force -ErrorAction SilentlyContinue
Get-ChildItem "$repo\.simple-ci\run" -ErrorAction SilentlyContinue |
  Remove-Item -Force

# Expected indexable files (read-only; does not create an index).
uv run python -c "from simple_code_indexer.config import load_settings; from simple_code_indexer import indexer; print(len(list(indexer.iter_workspace_files(load_settings()))))"
```

Note the number printed as `N`; Stage 6.2 waits for it. The first server start walks the whole
workspace and re-embeds every chunk, so retrieval before that rebuild settles is invalid.

### 6.2 Wait for the rebuild, then run the driver

**Do not query a deleted index until it has settled.** Start the writer through the checkout's
MCP launcher and hold the reader open while it rebuilds; `PROBE_WAIT_INDEX=N` (the count from
Stage 6.1) makes `tests/mcp_probe.py` poll `get_status` until `files_indexed >= N`,
`pending_embeddings` is 0, `watcher_alive` is true, and `last_sweep` is set on two consecutive
samples, then run its normal contract checks:

```powershell
$env:PROBE_WAIT_INDEX = "<N>"
$env:PROBE_WAIT_TIMEOUT = "600"
uv run python tests/mcp_probe.py `
  "$repo\.venv\Scripts\pythonw.exe" "$repo\run_server.py" 2>&1 |
  Tee-Object artifacts\acp-reindex.log
Remove-Item Env:PROBE_WAIT_INDEX, Env:PROBE_WAIT_TIMEOUT
```

Wait for `PROBE OK` before continuing. While `PROBE_WAIT_INDEX` is set, the probe extends its
child watchdog to `PROBE_WAIT_TIMEOUT + 60 s`, so the reindex cannot be killed by the normal
180 s probe bound; raise `PROBE_TIMEOUT` only for a rebuild that needs longer than that.

OpenCode 2.2.5 also starts its **configured** `simple-code-indexer` entry before applying the
session injection, so its first reader can spawn the writer from `%APPDATA%\simple-code-indexer`
even though the injected launcher is `--install $repo`. Mask the configured entry for the run,
with a byte-exact backup you restore afterwards:

```powershell
$cfg = "$env:USERPROFILE\.config\opencode\opencode.json"
$backup = "$repo\artifacts\opencode-config-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss').json"
Copy-Item $cfg $backup -Force
(Get-FileHash $cfg -Algorithm SHA256).Hash    # record this value

$json = Get-Content $cfg -Raw | ConvertFrom-Json
if ($json.mcp -and $json.mcp.servers) {
  $json.mcp.servers.PSObject.Properties.Remove('simple-code-indexer')
}
$json | ConvertTo-Json -Depth 10 | Set-Content $cfg -Encoding UTF8

& "$env:LOCALAPPDATA\Programs\ai.opencode.desktop\resources\opencode-cli.exe" `
  debug config --standalone 2>&1 | Select-String -Pattern 'simple-code-indexer'
# expect no match
```

Then run the driver against the same checkout, passing the checkout as `--install` so the
injected server is the one under test:

```powershell
uv run python tests/acp_probe.py $repo --install $repo --json 2>&1 |
  Tee-Object artifacts\acp-run.log
```

`--install` is the launcher root, not an alternative installation: `--install $repo` selects
`$repo\.venv\Scripts\pythonw.exe` + `$repo\run_server.py`. During the run, confirm the writer's
command line names the checkout:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*simple_code_indexer.sidecar.daemon*' } |
  Select-Object ProcessId, CommandLine
```

Expect `<repo>\.venv\Scripts\pythonw.exe -m simple_code_indexer.sidecar.daemon`. If it names
`%APPDATA%`, the mask did not apply and the run is not checkout-only.

Restore the config immediately after the driver exits (also §8.6):

```powershell
Copy-Item $backup $cfg -Force
(Get-FileHash $cfg -Algorithm SHA256).Hash    # must equal the recorded value
```

Useful overrides:

| Flag | Purpose |
|---|---|
| `--agent <path>` | A different ACP agent (`cmdc.cmd`, a wrapper script, …) |
| `--agent-args '["--print-logs","acp"]'` | Harness flags; logs stay on stderr |
| `--model <id>` | Pin the session model via `session/set_config_option` |
| `--install <dir>` | Launcher root; pass the checkout itself (`--install $repo`) |
| `--tool-format '{name}_{tool}'` | Override tool naming (normally inferred) |
| `--timeout <s>` | Per-prompt bound (default 180) |

### 6.3 What the driver does

1. Spawns `<agent> acp` in the checkout with stderr drained on a thread.
2. `initialize` → asserts `agentInfo`.
3. `session/new` with `cwd` = the checkout and its MCP server injected **under its canonical
   name**, with `SIMPLE_CI_GIT_PULL=0` so `run_server.py` does not pull mid-run.
4. `get_status` — polls up to 60 s until `sessions >= 1` and `watcher_alive`. The Stage 6.2
   reindex gate must already have printed `PROBE OK`; the driver itself does not prove that the
   rebuild finished.
5. Writes `acp_probe_fixture.py` and polls `get_status` until `files_indexed` increases.
6. `symbol_lookup` for `acp_probe_function`.
7. `search_code` lexical for `acp_probe_marker`.
8. `search_code` semantic for "function that returns forty one".
9. Edge cases: empty query, unknown symbol.
10. Cross-checks `index.db` row counts against `get_status`, and `run/daemon.json`.
11. Deletes the fixture, closes stdin, reaps the child, asserts exit code 0.

### 6.4 Reading the output

```
agent: C:\Users\...\opencode-cli.exe
[PASS] ACP initialize — OpenCode 2.2.5
[PASS] session created — ses_...
[PASS] workspace is the target (cwd inference, no pin) — <workspace>
[PASS] role is reader (sidecar) — reader
[PASS] watcher alive
[PASS] one registered session — sessions=1
[PASS] single config source — ['C:\\Users\\...\\.simple-ci\\config.yaml']
[PASS] embedding service reachable — running
[PASS] watcher indexed the new file — files 1 -> 2
[PASS] symbol_lookup found the fixture — {...}
[PASS] lexical search hit the fixture — ['acp_probe_fixture.py']
[PASS] lexical source reported — lexical
[PASS] semantic source reported — semantic
[PASS] semantic search returned hits — 2 hit(s)
[PASS] empty query returns no hits — {"hits": [], "source": "lexical"}
[PASS] unknown symbol is flagged, not invented — {"symbol": "DefinitelyNotARealSymbolXYZ", "found": false, ...}
[PASS] index.db exists
[PASS] writer.log exists
[PASS] sqlite counts are non-zero — {'files': 2, 'symbols': 3, 'chunks': 2}
[PASS] sqlite files match get_status — sqlite=2 status=2
[PASS] sidecar daemon published for this workspace — pid=21820
[PASS] agent exited 0 on stdin close — exit=0

permissions=0 updates=113 stderr_lines=0
RESULT: PASS (23/23)
```

If a prompt is skipped by the model, you will see the retry line instead of a silent failure:

```
    attempt 1: stop=end_turn, no 'hits' payload
```

That is expected occasionally on free models, and it is **not** a product defect unless both
attempts fail.

### 6.5 Running against a scratch workspace

The default target is the checkout; a scratch directory is only for a disposable smoke run. The
same launcher still comes from the checkout:

```powershell
$ws = Join-Path $env:TEMP "acp-e2e"
Remove-Item -Recurse -Force $ws -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $ws | Out-Null
uv run python tests/acp_probe.py $ws --install $repo --json
```

A scratch run does not exercise the checkout's own index or the Stage 6.2 reindex gate.

---

## 7. Stage 3 — read the evidence

The driver's own checks are necessary but not sufficient; confirm the server side too.

### 7.1 Server log contract

```powershell
$repo = (Get-Location).Path
Get-Content "$repo\.simple-ci\log\reader.log" -Tail 80
Get-Content "$repo\.simple-ci\log\writer.log" -Tail 80
```

Assert, in the current session slice (from `starting (pid=...)` / `writer runtime ready`):

- `serving on stdio (…, role=reader)`, `parent watchdog: watching <harness>` — the harness is the
  ACP process, not a GUI;
- `tool=get_status`, `tool=symbol_lookup`, `tool=search_code` lines — one per call;
- `sweep: checked=N indexed=… unchanged=…` with no `errors>0`;
- `semantic search: N vector hit(s)` and `embed request ok`;
- **no** `ERROR`/`CRITICAL` (a deliberate duplicate-server lock refusal is the one expected
  `ERROR`); a DEBUG-level traceback from `sidecar client disconnected` is normal when the harness
  kills the reader, because the control pipe closes without an `UNREGISTER`;
- the writer side shows `sidecar client connected` / `session registered` /`disconnected`.

### 7.2 Sidecar identity

```powershell
Get-Content "$repo\.simple-ci\run\daemon.json"
Get-Content "$repo\.simple-ci\run\daemon.token" | Measure-Object -Character
```

`daemon.json` names one writer pid and the endpoint; `sessions` returns to 0 after the ACP process
exits, and the daemon exits after `idle_grace_s` (60 s). The process command line is the ground
truth for **which launcher owns the writer**:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*simple_code_indexer.sidecar.daemon*' } |
  Select-Object ProcessId, CommandLine
```

Expect `<repo>\.venv\Scripts\pythonw.exe`; a `%APPDATA%` path means Stage 6.2's mask did not
apply.

### 7.3 SQLite vs `get_status`

The `files`, `symbols`, and `chunks` counts must match `files_indexed`, `symbols_indexed`, and
`chunks_indexed` from the last `get_status`. `vectors_indexed` and `pending_embeddings` decide
whether the semantic path is ready — row counts alone do not.

```powershell
uv run python -c "import sqlite3,sys; c=sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True); print({t: c.execute(f'select count(*) from {t}').fetchone()[0] for t in ('files','symbols','chunks')})" "$repo\.simple-ci\index.db"
```

For `sqlite-vec`, `vector_index` is `<index.db>#vec_chunks` and `vectors_indexed` must equal the
`vec_chunks` row count. `vec_chunks` is a virtual table, so load the extension on the read-only
connection; `vectors.faiss` must be absent:

```powershell
uv run python -c "import sqlite3, sqlite_vec, sys; c=sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True); c.enable_load_extension(True); sqlite_vec.load(c); print('vec_chunks:', c.execute('select count(*) from vec_chunks').fetchone()[0])" "$repo\.simple-ci\index.db"
```

### 7.4 Fetch ACP-side evidence when a check fails

```powershell
Select-String -Path "$env:USERPROFILE\.local\share\opencode\log\opencode.log" -Pattern "mcp connected|simple-code-indexer" |
  Select-Object -Last 10
```

An `mcp connected server=simple-code-indexer tools=3` line is proof the harness loaded the three
tools; its absence points at the launcher, not the model.

---

## 8. Stage 4 — teardown and report

### 8.1 Verify shutdown

The driver already asserts `agent exited 0 on stdin close`. Confirm nothing survived. The reader
must die with the ACP harness; the writer daemon exits after `idle_grace_s` (60 s), so poll for up
to 90 s:

```powershell
$repo = (Get-Location).Path
$deadline = (Get-Date).AddSeconds(90)
do {
  $left = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and (
      $_.CommandLine -like "*$repo\run_server.py*" -or
      ($_.CommandLine -like '*simple_code_indexer.sidecar.daemon*' -and
       $_.CommandLine -like "*--workspace*$repo*")
    )
  })
  if ($left.Count -eq 0) { break }
  Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)
$left | Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine
Get-Content "$repo\.simple-ci\log\writer.log" -Tail 30
Test-Path "$repo\.simple-ci\run\daemon.json"
```

Expected: `$left` is empty, `writer.log` ends with `no sidecar sessions for … shutting down`,
`vector store flushed`, `workspace lock released`, `sidecar stopped`, and `daemon.json` is gone.
If a reader survives, read its `parent watchdog: watching …` line first — the ACP process is the
watched parent, so a survivor means the watchdog did not act or the process was orphaned. Stop it
with the human's consent and file a lifecycle issue.

### 8.2 Stop leftovers from a failed run

The index is the checkout's real index, but a killed run can orphan a daemon for it:

```powershell
$dj = Get-Content "$repo\.simple-ci\run\daemon.json" -Raw | ConvertFrom-Json
taskkill /PID $dj.pid /T /F
```

### 8.3 Write `artifacts/acp-results.md`

Every run — pass **or** fail — ends with a results document at `artifacts/acp-results.md`, the
counterpart of the MCP test's `artifacts/mcp-results.md`. It is the durable evidence: the terminal
scrollback is gone by the time anyone reads the report, and a failed run is only useful if its
evidence survived. Use the template in [§11.1](#111-run-log-artifactsacp-resultsmd).

It must contain:

1. **Verdict table** — one PASS/FAIL line per area (handshake/session, workspace inference,
   sidecar role + session count, watcher pickup, each tool, artifacts/sqlite agreement, clean
   shutdown), plus `Total: nn/nn (RESULT: PASS|FAIL)`. Copy the numbers from the driver's own
   `RESULT:` line; do not re-derive them from memory.
2. **Environment** — harness name and version, model id (including "default" when `--model` was
   not passed), launcher (`$repo\.venv\Scripts\pythonw.exe` + `run_server.py`), workspace path,
   vector store, embedding URL/model/dim.
3. **Driver output** — the full check list, verbatim, **including retry lines**
   (`attempt 1: … no 'hits' payload`). When `--json` was used, paste the `{pass, checks}` object.
   A retry that succeeded is evidence about model behaviour, not noise; keep it.
4. **Server evidence** — the current session slice of `reader.log`/`writer.log` (from their
   `starting (pid=…)` / `writer runtime ready` banners), `run/daemon.json`, the writer daemon's
   command line, and the sqlite counts beside the matching `get_status` fields.
5. **Problems observed** — symptom, command, raw output, suspected cause. If the run passed,
   write "none" rather than omitting the section.

Save repeat runs as `artifacts/acp-results-<YYYYmmdd-HHMMSS>.md` (or another suffix) instead of
overwriting the previous one. When the run is part of a release gate or a multi-run comparison,
add the summary in [§11.2](#112-final-report-artifactsacp-final-reportmd) as
`artifacts/acp-final-report.md`.

### 8.4 Record issues, notes, changelog

- Add defects to [`docs/ISSUES.md`](../docs/ISSUES.md) (next free `ISS-n`; delete once fixed).
- Add operational gotchas to [`docs/NOTES.md`](../docs/NOTES.md).
- Add user-visible changes to [`docs/CHANGELOG.md`](../docs/CHANGELOG.md).
- Update [`docs/TOOLS.md`](../docs/TOOLS.md) only if a tool under `tools/` changed — the driver
  lives in `tests/`.

### 8.5 Code changes

If the run required code changes: `uv run ruff check .` → `uv run pyright` → `uv run pytest`
(see `NOTES.md` for the writable `--basetemp` on this host).

### 8.6 Cleanup

- Leave `$repo\.simple-ci\` in place: it is the checkout's real index, now rebuilt.
- Restore the OpenCode config backup recorded in Stage 6.2 and verify its SHA-256; the temporary
  mask must never be left in place.
- Never leave a debugging `WORKSPACE_ROOT`/`cwd`/`SIMPLE_CI_GIT_PULL` in a harness entry;
  re-running `python setup.py --harnesses <name>` restores the clean entry.

---

## 9. Host harness compatibility

This test is driven by whatever agent is running it, so the host must be able to spawn a
subprocess and read JSON from it. Any agent with shell access qualifies; the host does **not**
need ACP support.

| Host | ACP server capability | Can drive this test | Verified |
|---|---|---|---|
| Command Code (`cmd` / `cmdc`) | Yes — `cmd acp` (ACP server for Zed and other clients) | Yes — via shell, spawning the ACP harness | 2026-11-18 |
| OpenCode | Yes — `opencode acp` | Yes | 2026-11-18 |

Command Code documents ACP at <https://commandcode.ai/docs/acp>: `cmd acp` runs an ACP server on
stdio, and `cmd login` in a terminal supplies the account. Confirmed live on this host:

```
cmd acp  →  initialize → agentInfo {name: "Command Code", version: "1.89.1"}
            session/new → session id
            session/prompt → "CMD_ACP_OK"
```

**Important:** `cmd acp` is an ACP **server**. It does not act as an ACP client, so Command Code
cannot attach to `opencode acp` itself. That is why the driver speaks the protocol directly
instead of delegating to a host ACP client. The same applies to OpenCode.

Both harnesses drive this repository's server correctly:

| Harness | Result | Tool naming | Permission prompts |
|---|---|---|---|
| OpenCode 2.2.5 | 23/23 PASS | `simple-code-indexer_get_status` | 0 observed |
| Command Code 1.89.1 | 23/23 PASS | `mcp__simple-code-indexer__get_status` | 7 observed (one per call) |

The driver infers the tool-name format from the agent name; pass `--tool-format` if you wrap the
binary under a different name. Permission prompts are answered `allow_once` and counted, never
asserted on.

---

## 10. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `agent exited (rc=…) during initialize` | Invalid flag for `acp` (e.g. `--auto`), or broken install | Run `<agent> acp --help`; drop unsupported flags |
| `initialize` never returns; child is alive | Client not draining stderr impatience aside, this is usually a wedged agent | Check the stderr tail the probe prints; try `--agent-args '["--print-logs","acp"]'` |
| `session created` fails with invalid params | Relative `cwd` | Pass an absolute path |
| First `get_status` shows `sessions: 0` | The reader registered after the call | The driver polls; do not "fix" it by asserting once |
| `files_indexed` never rises | Watcher not running, wrong workspace, or index error | Compare `workspace` with `cwd`; grep the reader log for `failed to index` |
| Semantic check fails twice but rows exist | Vectors still being written | `pending_embeddings`/`vectors_indexed`; the driver retries once after 12 s |
| Semantic check fails with `ready: false` | Embedding endpoint down or wrong model/dim | `tests/service_probe.py`, container logs, `embed_ok` lines |
| `sessions: 2` | A second reader on the same workspace | Use the canonical injected name; check for a stale configured entry |
| Tool never appears for the model | Launcher path wrong or process died at startup | Look for `mcp connected … tools=3` in `opencode.log`; run §5.3 |
| Model returns prose instead of a payload | Model skipped the tool call | Expected occasionally; the driver retries. Persistent → pin a stronger model |
| A tool call stalls and the log stops mid-write | Unread stderr pipe | Drain it on a thread (the driver does) |
| Agent does not exit on stdin close | Client kept the pipe open, or a wrapper swallowed it | Close `proc.stdin` explicitly; check the process tree |
| Windows: two `pythonw.exe` per session | venv trampoline → base interpreter | Count server instances by `index.db` lock, not process count |

---

## 11. Templates

### 11.1 Run log (`artifacts/acp-results.md`)

Written at the end of **every** run in Stage 4 (§8.3); this is the template.

```markdown
# ACP end-to-end run (<agent> <version>, <date>)

## Verdict
- ACP handshake / session: PASS/FAIL
- Workspace inference: PASS/FAIL (<workspace>)
- Sidecar role + single session: PASS/FAIL (sessions=)
- Watcher pickup: PASS/FAIL (files a -> b)
- Tools: status / symbol / lexical / semantic — N/4
- Artifacts + sqlite agreement: PASS/FAIL
- Clean shutdown: PASS/FAIL (exit=)
- Total: nn/nn (RESULT: PASS|FAIL)

## Environment
| Item | Value |
|---|---|
| Harness | <agent> <version> |
| Model | <id> |
| Launcher | `<repo>\.venv\Scripts\pythonw.exe` + `<repo>\run_server.py` |
| Workspace | <path> |
| Vector store | faiss / sqlite-vec / qdrant |
| Embedding | <url> / <model> / <dim> |

## Driver output
(paste the full check list, including retry lines)

## Server evidence
(reader.log / writer.log session slice, daemon.json, sqlite counts)

## Problems observed
1. symptom / command / raw output / suspected cause
```

### 11.2 Final report (`artifacts/acp-final-report.md`)

```markdown
# Automated ACP end-to-end test — final report (<date>)
## Verdict per area (install / ACP handshake / indexing / retrieval / shutdown)
## Install and preconditions evidence
## Driver summary (checks, retries, model behaviour)
## Retrieval results
## Shutdown evidence
## What worked / what didn't
## Issues filed (ISS-n) and notes/changelog updates
## Recommendations
```

---

## 12. Definition of done

- [ ] Harness confirmed: `<agent> --version` and `<agent> acp --help` succeed.
- [ ] A model is usable (`opencode models`, or a pinned `--model`).
- [ ] `uv sync` ran; the checkout's `.venv` and `run_server.py` are the launcher.
- [ ] The existing index was deleted and the reindex gate printed `files_indexed=N`,
      `pending_embeddings=0`, and `PROBE OK`.
- [ ] `tests/service_probe.py` passed; `tests/acp_probe.py $repo --install $repo` printed
      `RESULT: PASS`.
- [ ] Server session slice shows `serving on stdio`, the watchdog on the ACP process, `tool=` per
      call, the sweep summary, and no unexpected errors.
- [ ] `daemon.json` names one writer for the workspace; `sessions` returned to 0.
- [ ] The writer daemon's command line names `<repo>\.venv\Scripts\pythonw.exe`, not
      `%APPDATA%\simple-code-indexer`.
- [ ] The OpenCode config was restored byte-for-byte after the masked run (SHA-256 matches).
- [ ] No `run_server.py` reader and no `simple_code_indexer.sidecar.daemon` writer survives for
      the workspace after the session closes (the daemon may take up to `idle_grace_s`).
- [ ] `artifacts/acp-results.md` written from the §11.1 template — verdict table with the
      driver's own counts, environment, full check list (retries included), server evidence, and
      problems observed (pass or fail).
- [ ] Defects filed in `docs/ISSUES.md`; notes/changelog updated.
- [ ] `ruff check`, `pyright`, `pytest` pass if code changed.

---

## Appendix A — how the driver works

`tests/acp_probe.py` is a minimal ACP client, deliberately shaped like `tests/mcp_probe.py`: raw
JSON-RPC, no SDK, drained stderr, bounded lifetime.

**Message dispatch** — the one rule that matters:

```python
if "id" in msg and "method" in msg:      # server-initiated REQUEST → answer it
    handle_request(msg)
elif "id" in msg:                        # response to us
    responses[msg["id"]] = msg
elif msg.get("method") == "session/update":   # notification → dispatch
    handle_update(msg["params"])
```

Swapping the first two branches kills the reader thread; every later request then times out and
the failure looks like a harness hang. This cost a real debugging cycle while writing the probe.

**Permission handling** — answer, never ignore:

```python
chosen = next((o for o in options if o["kind"] == "allow_once"), options[0])
send({"jsonrpc": "2.0", "id": msg["id"],
      "result": {"outcome": {"outcome": "selected", "optionId": chosen["optionId"]}}})
```

**Payload extraction** — tool results live on `tool_call_update`:

```python
for block in update.get("content") or []:
    inner = block.get("content") or {}
    if inner.get("type") == "text":
        parsed, _ = json.JSONDecoder().raw_decode(text[text.find("{"):])
```

Models sometimes wrap the JSON in a fence or prefix it with prose, so search for the first `{`
and use `raw_decode` rather than `json.loads` on the whole string.

**Retry and polling** — `ask(..., marker, tries=2)` returns the first captured payload containing
`marker`; readiness checks poll `get_status` instead of sampling once.

---

## Appendix B — ground-truth query suite

For the **repo under test** (line numbers drift; verify with `git grep` before expecting an exact
hit — prefer file-level expectations).

| id | tool | query | expected |
|---|---|---|---|
| L1 | lexical | `iter_workspace_files` | `src/simple_code_indexer/indexer.py` |
| L2 | lexical | `LLAMA_ARG_POOLING` | `setup_wizard/__init__.py` or `tests/test_setup_wizard.py` |
| L3 | lexical | `vector_label_seq` | `src/simple_code_indexer/db.py` |
| S1 | semantic | how does the indexer avoid walking into virtualenv and cache directories | `indexer.py` (regression probe for the 30-line chunker) |
| S2 | semantic | prevent two indexer servers from writing to the same workspace at once | `workspace_lock.py` or `server.py` |
| S3 | semantic | merge Codex TOML config using marker comments so user comments survive | `harnesses/_toml.py` |
| S4 | semantic | allocate monotonic labels so vector ids are never reused | `db.py` or `faiss_store.py` |
| S5 | semantic | stop the server when the launching harness process dies while stdin stays open | `parent_watch.py` or `server.py` |
| Y1 | symbol | `iter_workspace_files` | `indexer.py` |
| Y2 | symbol | `WorkspaceLock` | `workspace_lock.py` |
| Y3 | symbol | `_acquire_workspace_lock` | `server.py` |
| Y4 | symbol | `DefinitelyNotARealSymbolXYZ` | `found: false` |
| U1 | semantic | how to bake sourdough bread | code chunks, clearly lower scores |

The driver runs a representative subset (status, watch, symbol, lexical, semantic, empty query,
unknown symbol). To run the full suite, prompt for each row with the same `ask` pattern:

```text
Call `simple-code-indexer_search_code` with {"query": "<q>", "limit": 3}.
Print its raw JSON.
```

```text
Call `simple-code-indexer_symbol_lookup` with {"symbol": "<s>"}.
Print its raw JSON.
```

Regenerate anchor lines:

```powershell
git grep -n "iter_workspace_files" -- src
git grep -n -E "^(def|class) WorkspaceLock" -- src
```

Expected indexable count (read-only, no index created):

```powershell
uv run python -c "from simple_code_indexer.config import load_settings; from simple_code_indexer import indexer; print(len(list(indexer.iter_workspace_files(load_settings()))))"
```

---

## Appendix C — evidence commands

```powershell
# processes (include pythonw.exe: the venv reader has no console window)
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -in @('python.exe','pythonw.exe','uv.exe') -and $_.CommandLine -like '*run_server.py*' } |
  Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine | Format-List

# artifacts
Get-ChildItem "<workspace>\.simple-ci" -Recurse | Select-Object FullName, Length

# logs (current session slice, not the raw tail across sessions)
Get-Content "<workspace>\.simple-ci\log\reader.log" -Tail 120
Get-Content "<workspace>\.simple-ci\log\writer.log" -Tail 120

# sidecar identity
Get-Content "<workspace>\.simple-ci\run\daemon.json"

# harness-side MCP evidence
Select-String -Path "$env:USERPROFILE\.local\share\opencode\log\opencode.log" -Pattern "mcp connected" |
  Select-Object -Last 5
```

POSIX equivalents: `ps -eo pid,ppid,lstart,args | grep run_server.py`, `ls -la .simple-ci`,
`tail -n 120 .simple-ci/log/reader.log`.

---

## Appendix D — known constraints

Verified while writing this process on 2026-11-18. These are properties of the harnesses, not
defects in this project; keep them in mind when a run looks flaky.

- **Free models skip tool calls intermittently.** One sweep that pinned
  `deepseek-v4.1-flash-free`, `mimo-v2.6-flash-free`, and `big-pickle` produced zero tool calls on
  the same prompt, while the default (`big-pickle`) did call the tool in most other runs. Retrying
  once is built into the driver; a second consecutive miss is worth recording but not chasing.
- **`--auto` is invalid with `acp` on OpenCode 2.2.5.** The child exits during the handshake.
  Permission handling belongs to the client.
- **The OpenCode desktop bundle is not on `PATH`.** Use
  `%LOCALAPPDATA%\Programs\ai.opencode.desktop\resources\opencode-cli.exe`, which the driver
  finds automatically on Windows when `opencode` is absent.
- **`cmdc` is usually on `PATH` before OpenCode is.** The driver prefers OpenCode explicitly;
  otherwise a run silently exercises Command Code.
- **A differently-named injected server adds a reader.** Injecting `simple-code-indexer-test`
  beside the configured `simple-code-indexer` produced `sessions: 2`. The driver always uses the
  canonical name, which replaces the configured entry.
- **The first `get_status` can precede session registration.** `sessions: 0` right after
  `session/new` is a race, not a bug; poll.
- **`opencode-cli serve --service` keeps the old GUI MCP servers alive, but ACP never uses that
  service.** ACP mode runs its own private server, so a clean stdin close ends the chain —
  no `opencode service stop` needed.
- **Command Code answers this repository's MCP tool calls with one permission prompt each.**
  OpenCode did not prompt in the same scenario. Both are correct; do not assert on the count.
