# MCP Integration Test Process

A repeatable, end-to-end procedure for verifying that `simple-code-indexer` installs cleanly,
is picked up by a real MCP harness, indexes a workspace, answers all three MCP tools, and
shuts down with the session.

It uses a **double handoff**:

```
Primary agent (Command Code / any coding agent)
  └─ Stage 1: install + verify from outside
  └─ Stage 2: write a handoff doc
        └─ Human restarts the harness, opens the workspace, gives the handoff to the
           Secondary agent (the LLM inside the harness)
              └─ Stage 3: live MCP session, writes the results doc
        └─ Human closes the harness and brings the results back
  └─ Stage 4: verify shutdown, write the final report, log issues
```

To start a run, the human prompts the primary agent with:

> I want to test MCP integration. Follow the instructions here: `ref-docs/mcp-test-process.md`

The primary agent owns §1–§5 and §7. The secondary agent only ever sees the handoff document
(§9.1), which the primary agent fills in with run-specific facts.

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
| Installed copy/venv actually serves MCP | Stage 1 (SDK probe in a scratch workspace) |
| Harness reads the entry **after a restart** and spawns the server | Stage 3 preflight |
| Server indexes the harness's workspace (not home, not `C:\`) | Stage 3 `get_status.workspace` + counts |
| All three tools over the MCP **stdio channel** | Stage 3 query suite |
| Retrieval quality against ground truth | Stage 3 query suite |
| Server exits when the harness closes | Stage 4 process + log check |
| Defects are captured for follow-up | Stage 4 (`docs/ISSUES.md`) |

**Not covered:** protocol conformance against the spec, multi-client concurrency, Qdrant parity
(use the FAISS default unless Qdrant is the target), and Windows service behaviour.

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
3. **The secondary agent never runs `setup.py`, `--uninstall`, or edits `~/.simple-ci/`.** It
   writes only under `artifacts/`.
4. **One writer per workspace.** A stale server holds the lock and the new one exits with
   `another simple-code-indexer already owns`. Check the process list and log before blaming
   the harness.
5. **Record the server PID and start time before closing the harness.** Shutdown can only be
   proven later against those values.
6. **A failed stage is a valid result.** Capture evidence and continue; do not rewrite the test
   to make it pass.

---

## 3. Stage 0 — prepare

### 3.1 Ask the human (one batch)

- **Harness**: which MCP client will run the secondary session? It must have a builtin plugin in
  `src/simple_code_indexer/harnesses/` (current set: `claude_code`, `claude_desktop`, `codex`,
  `gemini_cli`, `opencode`, `cursor`, `windsurf`, `vscode`, `zed`, `commandcode`, `mimo`).
  **Cline is not supported** — its builtin plugin was removed on 2026-11-08 after its settings
  file did not survive a restart.
- **Clean slate?** Reinstalling or uninstalling is destructive. Confirm before:
  - `python setup.py --uninstall --yes` (removes the install copy, config, services, models and
    recorded MCP entries; add `--keep-models` to keep the GGUFs),
  - deleting `<workspace>/.simple-ci/` (the previous index).
- **Embedding model**: default `--model embeddinggemma2` (768-dim, ~0.6 GB). Other catalog keys
  are in `src/simple_code_indexer/setup_wizard/catalog.py`.
- **Vector store**: default `--vector-store faiss` (local file, no extra container).
- **Target workspace**: normally the repository under test (the harness must open this folder).

### 3.2 Snapshot the baseline

Record, in the eventual report:

- `git status --short`, `git log --oneline -3`, and whether `HEAD` matches `origin` (see §4.5);
- the harness entry file content (or "absent");
- `~/.simple-ci/config.yaml` (or "absent") and `%APPDATA%/simple-code-indexer` (or "absent");
- `docker ps -a --filter name=simple-code-indexer`/`simple-ci-embed`;
- whether `<workspace>/.simple-ci/` exists;
- any `run_server.py` processes already running.

```powershell
git status --short
Get-Content "$env:USERPROFILE\.simple-ci\config.yaml" -ErrorAction SilentlyContinue
Test-Path "<workspace>\.simple-ci"
Get-CimInstance Win32_Process -Filter "name='python.exe'" |
  Where-Object { $_.CommandLine -like '*run_server.py*' } |
  Select-Object ProcessId, CreationDate, CommandLine
```

---

## 4. Stage 1 — install and verify from outside

> This stage is not "run setup.py and hope". Every item in §4.3 must be observed before the
> handoff is written.

### 4.1 Dry run first

```powershell
python setup.py --dry-run --yes --model embeddinggemma2 --vector-store faiss --harnesses <name>
```

Confirm the four choices in the output: model, vector store, install target, harness entry path.
`--yes` only answers prompts; explicit flags win.

### 4.2 Real install

```powershell
python setup.py --yes --model embeddinggemma2 --vector-store faiss --harnesses <name>
```

Run it in the background if the model must download (see `NOTES.md` for the long-command cap),
then read the log file it writes.

### 4.3 External verification checklist

| Check | Evidence |
|---|---|
| Global config | `~/.simple-ci/config.yaml` has `embedding.model`, `embedding.dim`, `vector_store`, a `service` block, and `setup.install_root`/`setup.harnesses` |
| Container | `docker ps` shows the embed container `Up` with the published port; `docker logs` ends with `listening on http://0.0.0.0:8080` |
| Endpoint | `uv run python tests/service_probe.py` → `embeddings OK dim=... model=...` and `PROBE OK` |
| Install copy | `%APPDATA%\simple-code-indexer` exists with `.venv`; the venv imports the server |
| Tools | the installed venv reports exactly `search_code`, `symbol_lookup`, `get_status` |
| Harness entry | expected path contains `command` = uv and `args` = `run --project <install> --no-sync python <install>/run_server.py` |
| Workspace untouched | `<workspace>/.simple-ci` does **not** exist yet |

```powershell
# installed environment imports the server and FAISS, and exposes the three tools
cd $env:TEMP
uv run --project "$env:APPDATA\simple-code-indexer" --no-sync python -c `
  "import simple_code_indexer.server as s, faiss; print([t.name for t in s._TOOLS]); print(faiss.__version__)"
```

### 4.4 Pin the workspace (harness permitting)

The server indexes `WORKSPACE_ROOT` when set, otherwise its process cwd. Harnesses that spawn
stdio servers outside the project directory (documented for Cline; possible for others) index
the wrong tree — including drive roots or home. The server rejects a home directory, but not an
arbitrary large directory.

In the harness entry, add the workspace explicitly:

```jsonc
// JSON MCP clients (mcpServers.*)
"env": { "WORKSPACE_ROOT": "D:\\Projects\\Python\\simple-code-indexer" }

// OpenCode (mcp.*): key is "environment"
"environment": { "WORKSPACE_ROOT": "D:\\Projects\\Python\\simple-code-indexer" }
```

Where the harness supports a stdio `cwd` field, set that too. Re-running `setup.py` rewrites the
entry and drops manual additions — re-apply this after any reinstall, and verify
`get_status.workspace` in Stage 3. For a truly global install that serves any folder, prefer a
harness that spawns MCP servers with the project cwd (OpenCode does) and do not hard-code the
path.

### 4.5 Make sure you test the working tree, not upstream

`run_server.py` runs `git pull --ff-only --autostash --quiet` inside the **installed copy** before
importing the server (fail-soft, 20 s). If upstream has moved, the secondary session tests
upstream, not the checkout.

```powershell
git rev-parse HEAD
git ls-remote origin refs/heads/master
```

If they differ, pick one:

- accept it and say so in the report ("tested upstream `<sha>`"), or
- add `"SIMPLE_CI_GIT_PULL": "0"` to the entry's env and test the installed snapshot.

### 4.6 Prove the server works before blaming the harness

Drive the installed launcher with the official MCP SDK client against a throwaway workspace
(two small `.py` files). This validates initialize → tools/list → indexing → `get_status` →
lexical + semantic search → symbol lookup, and that closing stdin shuts the server down.

A minimal driver is in Appendix B.2. Expected: all three tools, both search modes return hits
(allow a short wait for vectors), and closing stdin yields exit code 0 within a few seconds with
`workspace lock released` and `shutting down after Ns` in the scratch log.

### 4.7 Record the installed entry

Paste the entry JSON verbatim into the handoff and the final report. Note the exact path, the
command, and any env additions.

---

## 5. Stage 2 — write the handoff

Create `artifacts/mcp-handoff.md` from the template in §9.1. It must contain:

1. **Facts table** — workspace, config path, install copy, model/endpoint/dim, vector store,
   entry path, expected indexable file count, index/vector/log paths.
2. **Pre-verified baseline** — the result of §4.6, so a harness failure is not mistaken for a
   server failure.
3. **Preflight** — confirm the server is listed/connected in the harness UI; confirm the three
   tools; record the server `ProcessId` **and** `CreationDate`.
4. **Baseline `get_status`** — paste the full JSON and list the assertions (workspace, store,
   index path, single config source, log file, watcher).
5. **Indexing watch** — poll until `files_indexed` and `chunks_indexed` are stable for two
   reads; record every sample; expected count from §4.3. Include the **vectors-lag** warning:
   counts are SQLite rows, FAISS vectors are written afterwards; retry a 0-hit semantic query
   once after 10–15 s and record both attempts.
6. **Query suite with ground truth** — lexical, semantic, symbol, a nonexistent symbol, and an
   unrelated semantic query. Use Appendix A or regenerate ground truth for the target repo.
7. **Log/artifact inspection** — `sci.log` tail, index/vector/log sizes, sqlite counts.
8. **Results template** — the exact sections and verdict table to fill in.
9. **Failure path** — missing entry, wrong workspace, held lock, hanging tool call (include the
   stderr-pipe note), and "still write the results document".
10. **Finish** — record the PID, write `artifacts/mcp-results.md`, tell the human to close the
    harness, and run no further MCP calls.

**Ground-truth rule:** every expected `file:line` must be verified at handoff time
(`grep -n`/`grep -rn`); line numbers drift. Prefer file-level expectations when lines move often.

The human then restarts the harness (required — entries are read at startup), opens the target
workspace, and gives the secondary agent:

> Follow `artifacts/mcp-handoff.md` and write `artifacts/mcp-results.md`.

---

## 6. Stage 3 — secondary harness session

The secondary agent follows the handoff. Order matters:

1. **Preflight:** server listed and connected; exactly three tools; record PID + start time.
   - One launch can appear as **two** `python.exe` processes: uv's venv `python.exe` is a
     trampoline over the base interpreter. Count *instances* by the trampoline parent, not raw
     process count.
2. **`get_status`:** paste the full JSON; stop if `workspace` is wrong.
3. **Index the workspace:** poll until counts are stable; record the timeline. Do not rely on
   `vector_store_ok` for vector readiness.
4. **Query suite:** call the tools through the harness. Record top-3 `file:line` + score and
   PASS/FAIL per query. If the harness cannot expose the tools, record FAIL and stop — a direct
   handler run may be added as diagnostic evidence, clearly labelled.
5. **Inspect:** log tail (startup lines, `serving on stdio`, `tool=` lines, errors), artifact
   sizes, sqlite counts.
6. **Write `artifacts/mcp-results.md`** using the template. Include the raw JSON and log lines.
7. **Tell the human to close the harness.** Leave the server running; Stage 4 needs the
   shutdown evidence.

---

## 7. Stage 4 — return, verify, report

### 7.1 Shutdown verification

Compare the recorded PID/start time with the live process list, then read the log tail:

```powershell
Get-CimInstance Win32_Process -Filter "name='python.exe'" |
  Where-Object { $_.CommandLine -like '*run_server.py*' } |
  Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine
Get-Content "<workspace>\.simple-ci\log\sci.log" -Tail 25
```

- **Pass:** the recorded PID is gone and the log ends with `workspace lock released` and
  `shutting down after Ns`.
- **Fail (processes remain):** first read the server's `parent watchdog: watching ...` line. If
  the harness UI is in that list, the watchdog should have fired — treat survival as a
  regression. If it is not, the harness service was started detached (shell/daemon) and no
  process watchdog can see the UI. Look for a harness background service that outlived the UI
  and still holds the child's stdin (e.g. `opencode-cli serve --service`, an extension host, a
  desktop helper). Closing the window does not close the pipe. Record the parent, then stop the
  process tree only with the human's consent:

  ```powershell
  taskkill /PID <trampoline-or-parent> /T /F
  ```

  Log it as a lifecycle issue. A clean stdin close has been proven to shut the server down, so
  do not call this a broken `finally`.

### 7.2 Validate the results

- sqlite counts equal `get_status` (`files`, `symbols`, `chunks`);
- `files_indexed` is close to the computed expected count (drift is fine — report it);
- no `ERROR`/`CRITICAL`/traceback in `sci.log`;
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
- Add user-visible changes to `docs/CHANGELOG.md` per `ref-docs/changelog-best-practices.md`.
- Update `docs/HANDOFF.md` if the work is incomplete or multi-session.

### 7.5 Cleanup (ask first)

- Leave installed for daily use, **or** `python setup.py --uninstall --yes` (`--keep-models` to
  keep GGUFs). Uninstall never touches workspace `.simple-ci/` indexes.
- Stop the embedding container if the test should not leave it running.
- Remove any manual `WORKSPACE_ROOT`/`SIMPLE_CI_GIT_PULL` additions if the harness should use
  the stock entry again.
- If code changed: `uv run ruff check .` → `uv run pyright` → `uv run pytest` (see `NOTES.md`
  for the writable `--basetemp` on this host).

---

## 8. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Server absent from the harness after restart | entry path/schema wrong; harness overwrote or deleted the file; restart not done | read the entry file, validate JSON, check the harness MCP log, restart once, add an issue |
| Server starts then exits immediately | home workspace rejected, bad config YAML, lock held | read `sci.log`; look for `another simple-code-indexer already owns` or a config error |
| `get_status.workspace` is not the target | harness spawns with another cwd and no `WORKSPACE_ROOT` | add `WORKSPACE_ROOT` to the entry; restart |
| Indexing stalls at 0 chunks | embedding endpoint down or wrong model/dim | `tests/service_probe.py`, container logs, `embed_ok`/log errors |
| Semantic query returns 0 hits | vectors still being written, or empty index | wait 10–15 s and retry once; check `faiss search: ntotal=` in the log; see ISS-4 |
| A tool call hangs and the log's last line is an INFO record | harness is not draining the server's stderr pipe | record it (ISS-2); the server blocks in a log write on the serve thread |
| Server survives closing the harness | check the server's `parent watchdog: watching` line: if the UI is absent, the service was started detached | record the parent, stop the service/tree with consent, file a lifecycle issue |
| Four `python.exe` for two sessions | uv venv trampoline + base interpreter | count trampolines, not processes |
| One expected file missing from top-3 | retrieval quality | record FAIL with hits/scores; file an issue; do not retry the same query endlessly |

---

## 9. Templates

### 9.1 `artifacts/mcp-handoff.md`

```markdown
# Stage 2 handoff — MCP integration test (<harness>, <date>)

Audience: the LLM running in <harness> with <workspace> open.
Do not run setup.py/uninstall, edit ~/.simple-ci, delete .simple-ci, or kill the server.
Write only under artifacts/.

## Facts
| Item | Value |
|---|---|
| Workspace | <abs path> |
| Config | <~/.simple-ci/config.yaml> |
| Install copy | <%APPDATA%/simple-code-indexer> |
| Embedding | <url> / <model> / <dim> |
| Vector store | <faiss|qdrant> |
| Entry | <path>, key <name> |
| Indexable files (expected) | <N> |
| Index / vectors / log | <.simple-ci/...> |

## Pre-verified baseline (outside the harness)
<result of the SDK probe; note the clean shutdown evidence>

## Preflight (do these first)
1. Server listed/connected; screen text: ___
2. Tools: search_code, symbol_lookup, get_status
3. Powershell: Get-CimInstance ... -> record ProcessId + CreationDate
   (one launch may be two processes: venv trampoline + base interpreter)

## Baseline get_status
<paste full JSON; assertions: workspace, vector_store, vector_index, config_files, log_file>

## Indexing watch
Poll get_status every 20-30 s until files_indexed and chunks_indexed are stable twice.
Record each sample. Expected files ≈ <N>. Vectors lag the counts: retry a 0-hit semantic
query once after 10-15 s and record both attempts.

## Query suite
| id | tool | query | expected file |
|---|---|---|---|
| L1 | search_code lexical | <q> | <file> |
| ... | | | |
Run all of them; record #hits, top-3 file:line+score, PASS/FAIL.

## Inspect
- Get-Content "<workspace>\.simple-ci\log\sci.log" -Tail 120
- sizes of index.db / vectors.faiss / sci.log
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
(server status, tool list, PID/CreationDate, baseline+final get_status JSON; mark fields that
 came from direct handler invocation)

## Indexing timeline
| t | files | symbols | chunks | notes |

## Query results
| id | tool | query | #hits | top-3 file:line + score | PASS/FAIL | notes |

## Log evidence
(startup lines, lock, serving, tool= lines, errors)

## Artifacts
(index.db / vectors.faiss / sci.log sizes; sqlite counts)

## Problems observed
1. symptom / command / raw output / suspected cause
```

### 9.3 `artifacts/mcp-final-report.md`

```markdown
# End-to-end MCP test — final report (<date>)
## Verdict per stage (install / pickup / indexing / retrieval / shutdown)
## Install evidence
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
- [ ] §4.3 checklist observed and recorded (config, container, probe, install copy, entry).
- [ ] §4.5 upstream check done; `SIMPLE_CI_GIT_PULL=0` used if testing the working tree.
- [ ] §4.6 SDK probe passed in a scratch workspace, including clean shutdown.
- [ ] Handoff written with verified ground truth, PID instruction, results template, failure path.
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
| L1 | lexical | `iter_workspace_files` | `src/simple_code_indexer/indexer.py` |
| L2 | lexical | `LLAMA_ARG_POOLING` | `src/simple_code_indexer/setup_wizard/__init__.py` |
| L3 | lexical | `vector_label_seq` | `src/simple_code_indexer/db.py` |
| S1 | semantic | how does the indexer avoid walking into virtualenv and cache directories | `src/simple_code_indexer/indexer.py` (known miss, ISS-5 — keep as a regression probe) |
| S2 | semantic | prevent two indexer servers from writing to the same workspace at once | `workspace_lock.py` or `server.py` |
| S3 | semantic | merge Codex TOML config using marker comments so user comments survive | `harnesses/_toml.py` |
| S4 | semantic | allocate monotonic FAISS label ids so ids are never reused | `db.py` or `faiss_store.py` |
| Y1 | symbol | `iter_workspace_files` | `indexer.py` |
| Y2 | symbol | `WorkspaceLock` | `workspace_lock.py` |
| Y3 | symbol | `_acquire_workspace_lock` | `server.py` |
| Y4 | symbol | `DefinitelyNotARealSymbolXYZ` | `found: false` |
| U1 | semantic | how to bake sourdough bread | non-empty code chunks, clearly lower scores |

Regenerating ground truth:

```powershell
# lexical anchor exists?
rg -n "iter_workspace_files" src
# symbol definition site?
rg -n "^(def|class) WorkspaceLock" src
# semantic anchors: read the module and pick a distinctive behaviour, then confirm the file
```

Expected indexable count: run the enumerator without creating an index (read-only):

```powershell
uv run python -c "from simple_code_indexer.config import load_settings; from simple_code_indexer import indexer; print(len(list(indexer.iter_workspace_files(load_settings()))))"
```

## Appendix B — evidence commands

### B.1 Process and workspace state (Windows)

```powershell
Get-CimInstance Win32_Process -Filter "name='python.exe'" |
  Where-Object { $_.CommandLine -like '*run_server.py*' } |
  Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine | Format-List

Get-ChildItem "<workspace>\.simple-ci" -Recurse | Select-Object FullName, Length
Get-Content "<workspace>\.simple-ci\log\sci.log" -Tail 120
```

POSIX equivalent: `ps -eo pid,ppid,lstart,args | grep run_server.py`, `ls -la .simple-ci`,
`tail -n 120 .simple-ci/log/sci.log`.

### B.2 External SDK probe (primary agent, scratch workspace)

```python
import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

INSTALL = r"C:\Users\<you>\AppData\Roaming\simple-code-indexer"
params = StdioServerParameters(
    command="uv",
    args=["run", "--project", INSTALL, "--no-sync", "python", INSTALL + r"\run_server.py"],
    env={"WORKSPACE_ROOT": r"<scratch workspace>"},
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
stderr and never drains it will eventually block the server (ISS-2).

## Appendix C — known issues that affect this test

Check `docs/ISSUES.md` before starting; these were open when this document was written:

- **ISS-2** — probes that spawn the server with `stderr=PIPE` and never drain it hang the
  server. Redirect stderr to a file or drain it.
- **ISS-3 (resolved 2026-11-10)** — the server now watches its launch chain and exits when an
  ancestor dies; closing the OpenCode desktop UI stopped it within ~2 s even though
  `opencode-cli serve --service` survived and the stdin pipe stayed open. A service started from
  a shell is detached and has no UI ancestor; check the `parent watchdog: watching` line.
- **ISS-4** — `get_status` can report a complete index before FAISS vectors exist; semantic
  queries can silently return zero. Wait/retry and record both attempts.
- **ISS-5** — S1 (virtualenv pruning) is a known retrieval miss; keep it as a regression probe.

## Appendix D — conventions

- Reports live in `artifacts/` (gitignored, throwaway). Reference docs live in `ref-docs/`.
- Name run documents `artifacts/mcp-handoff.md`, `artifacts/mcp-results.md`,
  `artifacts/mcp-final-report.md`; add a date suffix for repeat runs.
- Log new defects in `docs/ISSUES.md` with the next free `ISS-n`; delete them when fixed.
- Add operational gotchas to `docs/NOTES.md`; user-visible changes to `docs/CHANGELOG.md`.
