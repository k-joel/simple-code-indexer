# OpenCode ACP Mode — A Field Guide

`opencode acp` runs OpenCode as an **Agent Client Protocol** server on stdio. This booklet
covers what that is, why it exists, how to launch it, what it exposes, and how to debug it when
an editor refuses to talk to it. It is written for someone who has to *use* ACP mode, not just
read about it.

Verified against **opencode-cli 2.2.5** on Windows 11 unless noted.

---

## Table of Contents

1. [Why ACP exists](#1-why-acp-exists)
2. [What `opencode acp` actually is](#2-what-opencode-acp-actually-is)
3. [The transport contract](#3-the-transport-contract)
4. [Launching it](#4-launching-it)
5. [Editor configuration](#5-editor-configuration)
6. [The session lifecycle](#6-the-session-lifecycle)
7. [What the agent can do over ACP](#7-what-the-agent-can-do-over-acp)
8. [MCP servers over ACP](#8-mcp-servers-over-acp)
9. [Permissions and automation](#9-permissions-and-automation)
10. [Automating ACP from a script](#10-automating-acp-from-a-script)
11. [Troubleshooting](#11-troubleshooting)
12. [External resources](#12-external-resources)

---

## 1. Why ACP exists

Every editor used to need its own plugin, its own tool-call format, and its own permission UI for
every coding agent. Agent Client Protocol (ACP) replaces that N×M matrix with one standard:
JSON-RPC 2.0 over stdio, defined by Zed Industries at
[agentclientprotocol.com](https://agentclientprotocol.com).

The split is clean:

- **The ACP client is the editor.** It owns the UI: chat panel, diff view, permission prompts,
  model picker.
- **The ACP server is the agent.** It owns the model, the tools, and the files.

Neither side needs to know the other's internals. OpenCode is an **ACP server** ("agent" in ACP
vocabulary). It does not act as an ACP *client* to drive some other agent — that direction is not
natively supported.

---

## 2. What `opencode acp` actually is

One process, doing three things:

1. Reads newline-delimited JSON-RPC from **stdin**, writes it to **stdout**. Stdout carries ACP
   and nothing else.
2. Starts a **private** OpenCode server for its own use. It does *not* connect to the shared
   background service (`opencode serve --service`) and does not open a network port for ACP.
3. Serves **many ACP sessions** from that one process. Each session carries its own working
   directory, model, agent mode, and MCP servers.

It exits when the client closes stdin.

That last point matters for this repository: the MCP server's parent watchdog will watch the
`opencode acp` process, so a clean stdin close shuts everything down in order. The old
`opencode-cli serve --service` behaviour — where a reused background service kept MCP children
alive after the UI closed — does not apply to ACP mode, because ACP never uses that service.

> **Direct-terminal trap.** Running `opencode acp` in a terminal looks like a hang. It is
> waiting for ACP messages on stdin. That is the correct behaviour, not a bug.

---

## 3. The transport contract

| Property | Value |
|---|---|
| Protocol | ACP v1 |
| Framing | newline-delimited JSON-RPC 2.0 |
| Channels | stdin (client → agent), stdout (agent → client) |
| Logs | stderr only |
| Session scope | one `opencode acp` process can serve many sessions |

Bring your own `journalctl`-style discipline: because stdout is protocol-only, **anything**
written there that is not a JSON-RPC message corrupts the stream. OpenCode's own diagnostics go
to stderr prefixed `[acp]` when `--print-logs` is set.

### The methods you will actually use

| Method | Direction | Purpose |
|---|---|---|
| `initialize` | client → agent | Version + capability handshake |
| `session/new` | client → agent | Create a session with `cwd` and optional `mcpServers` |
| `session/prompt` | client → agent | Send user content; returns `stopReason` |
| `session/cancel` | client → agent | Stop the active prompt |
| `session/load` / `resume` / `fork` / `list` / `close` / `delete` | client → agent | Session management |
| `session/set_config_option` | client → agent | Switch `model`, `effort`, `mode` |
| `session/update` | agent → client | **Notification**: streamed chunks, tool calls, usage |
| `session/request_permission` | agent → client | **Request**: approve/deny a tool call |

`session/update` and `session/request_permission` are the two the agent initiates. A client that
ignores them will appear to hang, because tool calls block until permission is answered.

---

## 4. Launching it

```bash
opencode acp
```

Useful combinations:

```bash
opencode --print-logs acp        # ACP + private server logs on stderr
opencode --log-level debug --print-logs acp
opencode acp --login             # run the provider login flow, then exit
```

`--auto` is **not** valid with `acp`; the process exits immediately if you pass it. Permission
handling over ACP is driven by the client answering `session/request_permission`, not by a CLI
flag. Verified on 2.2.5:

```
$ opencode acp --auto     →  Connection closed (handshake never completes)
```

The client must spawn the process with an absolute path if a GUI cannot resolve `opencode`.
On Windows the Desktop build ships the binary at
`%LOCALAPPDATA%\Programs\ai.opencode.desktop\resources\opencode-cli.exe`, and that directory is
not on `PATH` by default.

### Authentication

ACP reuses the credentials the CLI already has. Sign in **once, in a terminal**, before starting
the client:

```bash
opencode auth login
```

`initialize` advertises one auth method, `opencode-login`. If the client sets
`clientCapabilities.auth.terminal = true`, that method becomes a *terminal* auth method and the
client is expected to run `opencode acp --login` in a real terminal rather than send
`authenticate`. Sending `authenticate` to a terminal method is a protocol error.

A prompt that fails for lack of credentials surfaces as ACP's `auth_required`.

**Free models need no login.** This host has `auth list` → "No authenticated integrations" yet
the built-in `opencode/*-free` models answer prompts normally (verified: `opencode/big-pickle`
replied `PONG`; `session/new` lists 11 free models). Useful for smoke tests, not for serious
work — see §9 on why.

---

## 5. Editor configuration

### Zed

```json
{
  "agent_servers": {
    "OpenCode": {
      "type": "custom",
      "command": "opencode",
      "args": ["acp"]
    }
  }
}
```

### JetBrains IDEs (`acp.json`)

```json
{
  "agent_servers": {
    "OpenCode": {
      "command": "/absolute/path/bin/opencode",
      "args": ["acp"]
    }
  }
}
```

### Neovim — Avante.nvim

```lua
{
  acp_providers = {
    ["opencode"] = {
      command = "opencode",
      args = { "acp" }
    }
  }
}
```

### Neovim — CodeCompanion.nvim

Set `adapter = { name = "opencode" }` in your `interactions.chat` setup.

### Command Code as an ACP *client*

Command Code exposes itself as an ACP **server** (`cmd acp`), not as a client. It can therefore
be driven *by* an ACP client, but it cannot itself drive `opencode acp`. For a scripted harness
use a real client (§10).

---

## 6. The session lifecycle

```
client                                   opencode acp
  │  initialize ───────────────────────────►│   protocolVersion, capabilities
  │◄─────────────────── agentCapabilities ──│
  │  session/new {cwd, mcpServers} ─────────►│   private server starts for that directory
  │◄──────────────── sessionId + config ────│   model / effort / mode options
  │◄────────── available_commands_update ───│
  │  session/prompt ───────────────────────►│
  │◄──────────── session/update (stream) ───│   thought chunks, message chunks
  │◄──── session/request_permission ────────│   (agent-initiated request)
  │  result: allow_once ───────────────────►│
  │◄──────────── session/update (tool) ─────│   tool_call, tool_call_update
  │◄───────────────────── result: end_turn ─│
```

Rules worth remembering:

- **`cwd` must be absolute.** A relative path is rejected with an invalid-params error.
- **`cwd` selects the configuration.** That directory's `AGENTS.md`, commands, skills, plugins,
  and configured MCP servers apply.
- **One prompt at a time per session.** A second concurrent `session/prompt` is an error.
- **`session/load` replays history**; `resume` and `fork` do not.
- **Additional directories** ride on `session/new` as `additionalDirectories` (absolute, no
  globs).

---

## 7. What the agent can do over ACP

Nearly everything from the TUI is available:

| Capability | Notes |
|---|---|
| File read / write / edit | Diffs are surfaced on the tool-call update when a preview is possible |
| Shell execution | Requires permission unless the client auto-approves |
| Custom tools, slash commands, skills | Same discovery as the TUI |
| `AGENTS.md` rules, formatters, linters | Loaded from the session `cwd` |
| MCP servers | Configured ones plus client-supplied ones (§8) |
| Model / agent switching | Via `session/set_config_option` |

**Not supported:** `/undo` and `/redo` (terminal-only actions). The agent also cannot act as an
ACP client to another agent.

Update kinds you will see on the wire: `available_commands_update`, `agent_thought_chunk`,
`agent_message_chunk`, `tool_call`, `tool_call_update`, `usage_update`, `session_info_update`,
and (for subagents) child-session updates tagged `_meta["opencode/child-session"]`.

---

## 8. MCP servers over ACP

Two independent sources load into a session:

1. **Configured servers** — whatever `opencode.json` declares under `mcp.servers` for that
   directory.
2. **Client-supplied servers** — `mcpServers` on `session/new` (also `load`/`resume`/`fork`).

```json
{
  "cwd": "C:\\work\\app",
  "mcpServers": [
    {
      "name": "simple-code-indexer",
      "command": "C:\\Users\\you\\AppData\\Roaming\\simple-code-indexer\\.venv\\Scripts\\pythonw.exe",
      "args": ["C:\\Users\\you\\AppData\\Roaming\\simple-code-indexer\\run_server.py"],
      "env": [{ "name": "SIMPLE_CI_GIT_PULL", "value": "0" }]
    }
  ]
}
```

Behaviour that matters in practice (verified against 2.2.5 and this repo's server):

- **A client-supplied server replaces a configured server of the same name** for that directory.
  This is how you get a hermetic test: inject `simple-code-indexer` yourself and the copy in
  `opencode.json` never spawns.
- **Different name = an extra server.** Two readers then attach to the same workspace and
  `get_status.sessions` reports `2`. Harmless but confusing; rename the injected server or drop
  the configured one.
- The injection persists for the life of the `opencode acp` process, so later sessions in the
  same directory see it too.
- HTTP MCP servers are supported; SSE is not advertised, and MCP-over-ACP is not supported.
- `codemode` is an OpenCode-side per-server option. With `codemode: false` the three tools appear
  in the model's **direct** tool list under names like
  `simple-code-indexer_get_status`. With codemode enabled they hide behind an `execute` tool,
  which costs extra round trips and makes scripted assertions brittle.

Log evidence that MCP wiring worked (from `~/.local/share/opencode/log/opencode.log`):

```
message="mcp connected" server=simple-code-indexer tools=3 directory="D:\\Projects\\..."
```

---

## 9. Permissions and automation

The agent asks; the client decides. Three options arrive on every request:

```json
[
  { "optionId": "once",   "kind": "allow_once",   "name": "Allow once" },
  { "optionId": "always", "kind": "allow_always", "name": "Always allow" },
  { "optionId": "reject", "kind": "reject_once",  "name": "Reject" }
]
```

Automation = answer every request with `allow_once` (see §10). A client that never answers leaves
the tool call pending forever, which is the most common "ACP hangs" report.

Two practical cautions:

- **Model quality decides whether tools get called at all.** In testing, the free models were
  inconsistent: one sweep that pinned `deepseek-v4.1-flash-free`, `mimo-v2.6-flash-free`, and
  `big-pickle` produced **zero** tool calls on the same prompt, while the identical prompt on
  `big-pickle` (the default) did call the tool in most other runs. Assertions must be based on the
  **tool payload the agent produced**, never on the model's prose summary, and every prompt
  should be retried once.
- **A permission prompt is not a failure.** `cmd acp` prompts on every injected MCP tool call
  (one `allow_once` observed per `get_status`); OpenCode ran the same server without prompting in
  several runs. Treat prompt counts as an observation, not a verdict.

---

## 10. Automating ACP from a script

You do not need an SDK. The protocol is small enough to speak with the standard library — which
is what `tests/acp_probe.py` in this repo does, mirroring `tests/mcp_probe.py`.

Skeleton:

```python
import json, subprocess, threading

proc = subprocess.Popen(
    [OPENCODE, "acp"], cwd=workspace,
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8", errors="replace",
)
# ALWAYS drain stderr on a thread; an unread pipe eventually blocks the child.
threading.Thread(target=drain, args=(proc.stderr,), daemon=True).start()
```

Then exchange newline-delimited messages:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1,"clientCapabilities":{}}}
{"jsonrpc":"2.0","id":2,"method":"session/new","params":{"cwd":"C:\\abs\\path","mcpServers":[]}}
{"jsonrpc":"2.0","id":3,"method":"session/prompt","params":{"sessionId":"ses_…","prompt":[{"type":"text","text":"…"}]}}
```

Three rules keep a hand-rolled client alive:

1. **Drain stderr** on a thread. This is not optional; see §11.
2. **Distinguish requests from notifications.** A message with both `id` and `method` is a
   *server-initiated request* (answer it). A message with `method` and no `id` is a notification
   (dispatch it). Getting this backwards kills the reader thread and every later request times
   out.
3. **Read tool payloads, not prose.** Tool results arrive on `tool_call_update` inside
   `content[].content.text`; the model's chat text is on `agent_message_chunk`.

A full, working implementation with assertions lives in
[`acp-test-process.md`](./acp-test-process.md) — it drives this repository's MCP server through
indexing, watching, all three tools, and shutdown.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `opencode acp` seems to hang in a terminal | It is waiting for stdin | That is normal — start it from a client |
| Client reports the process exited or "invalid protocol output" | Something wrote non-JSON to stdout | Add `--print-logs` so diagnostics go to **stderr**, and check for stray `print` debugging |
| Everything works, then a tool call stalls and the log stops mid-write | The client pipes stderr and never drains it | Drain it on a thread, or redirect it to a file |
| Prompts hang forever after one succeeds | Reader thread died on a mis-dispatched notification | Separate `id`+`method` (request) from `method`-only (notification) |
| `auth_required` on the first prompt | No provider credentials in the CLI | `opencode auth login` in a terminal, then reconnect |
| `Connection closed` immediately after spawn | Invalid flag for the subcommand (e.g. `acp --auto`) | Check `opencode acp --help`; drop the flag |
| Tool never appears in the model's list | MCP server failed to start, or codemode hid it | Grep `opencode.log` for `mcp connected … tools=`; set `codemode: false` |
| Two readers for one workspace | The client injected a differently-named copy of a configured server | Reuse the configured name, or remove the configured entry |
| An unrelated tool appears (`tools.opencode.*`) | The model wandered into OpenCode's built-in utility tools | Name the target tool exactly in the prompt and forbid `execute` |
| Session creation fails with invalid params | Relative `cwd` | Pass an absolute path |

### Where the logs are

| What | Where |
|---|---|
| ACP diagnostics (with `--print-logs`) | stderr, prefixed `[acp]` |
| OpenCode runtime log | `~/.local/share/opencode/log/opencode.log` |
| MCP connect lines | the same file: `message="mcp connected" server=… tools=…` |
| This repository's server | `<workspace>/.simple-ci/log/reader.log` and `writer.log` |

---

## 12. External resources

- **ACP specification** — <https://agentclientprotocol.com>
- **OpenCode ACP docs** (setup, protocol reference, capabilities, RFD `_meta` keys) —
  <https://opencode.ai/docs/cli/acp/> (the older `/docs/acp/` URL redirects here)
- **OpenCode CLI overview** — <https://opencode.ai/docs/cli/>
- **OpenCode repository** — <https://github.com/anomalyco/opencode>
- **Command Code ACP support** (`cmd acp`, Zed setup, MCP-in-ACP notes) —
  <https://commandcode.ai/docs/acp>
- **Python ACP SDK** (`agent-client-protocol`, useful for reading the schema and for typed
  clients) — <https://pypi.org/project/agent-client-protocol/>
