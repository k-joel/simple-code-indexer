"""ACP end-to-end probe: drives an ACP agent (OpenCode by default) over stdio and
asserts this repository's MCP server through it.

Usage:
    uv run python tests/acp_probe.py <workspace> [options]

Options:
    --agent PATH|NAME   ACP agent launcher (default: opencode, then the OpenCode
                        desktop bundle's opencode-cli.exe on Windows)
    --agent-args JSON   Arguments for the agent (default: ["acp"])
    --install PATH      uv tool environment (default: `uv tool dir` + simple-code-indexer)
    --model ID          Pin the session model via session/set_config_option
    --timeout S         Per-prompt bound (default 180)
    --tool-format FMT   Tool-name template (default is inferred: `{name}_{tool}`
                        for OpenCode, `mcp__{name}__{tool}` for Command Code)
    --json              Emit a machine-readable result object on stdout

The probe is fully automated: it spawns the agent, creates a session with the MCP
server injected per session, drives prompts that make the model call each tool,
and asserts on the **tool payloads** the agent returns - never on the model's
prose. Every prompt is retried once, because free models skip tool calls
intermittently.

OpenCode 2.2.5 **ignores** `session/new.mcpServers` (measured 2026-11-21): only
the `simple-code-indexer` entry already configured for that harness launches, so
the probe reads that entry first, requires it to launch this tool environment,
and fails fast with the remedy when it does not. Without that preflight a run
just exercises whatever the ambient harness config happens to contain - or
falls back to shell scripts and reports a misleading 10/23 (ISS-017).

The agent's stderr is drained on a thread. An unread stderr pipe blocks the agent
(and, through it, the MCP server) inside a log write; that single omission was
the cause of a 5-minute "hang" while this probe was being written.

Exit code 0 = every check passed. Progress is printed as `[PASS]`/`[FAIL]` lines.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any

from simple_code_indexer.harnesses import (
    WORKSPACE_FLAG,
    HarnessSpec,
    _json,
    _yaml,
    entry_argv,
    load_harnesses,
)

SERVER_NAME = "simple-code-indexer"
ENTRY_MODULE = "simple_code_indexer"
_STDERR_TAIL: list[str] = []
_DEFAULT_TIMEOUT_S = 180.0
_UPDATES: list[str] = []

_IGNORES_INJECTION = {"opencode"}
"""Harnesses that never start `session/new.mcpServers` (measured 2026-11-21)."""


def _install_root(explicit: str | None) -> Path:
    """The uv tool environment (or an explicit --install path)."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    import subprocess

    completed = subprocess.run(
        ["uv", "tool", "dir"], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise SystemExit("could not resolve `uv tool dir`; pass --install <path>")
    root = Path(completed.stdout.strip().splitlines()[0]) / "simple-code-indexer"
    if not root.is_dir():
        raise SystemExit(
            f"{root} is missing; run `uvx simple-code-indexer setup` first "
            "or pass --install <path>"
        )
    return root


def _find_agent(explicit: str | None) -> str:
    if explicit:
        found = shutil.which(explicit) or (
            explicit if Path(explicit).exists() else None
        )
        if not found:
            raise SystemExit(f"agent not found: {explicit}")
        return found
    # Prefer OpenCode: it is the harness this probe is written for. The desktop
    # bundle is checked before Command Code because `cmdc` is usually on PATH
    # while the OpenCode desktop binary is not.
    for name in ("opencode", "opencode-cli"):
        found = shutil.which(name)
        if found:
            return found
    if sys.platform == "win32":
        bundled = (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs"
            / "ai.opencode.desktop"
            / "resources"
            / "opencode-cli.exe"
        )
        if bundled.exists():
            return str(bundled)
    for name in ("cmdc", "command-code", "cmd"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("no ACP agent found; pass --agent <path>")


def _tool_format(agent: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    base = Path(agent).name.lower()
    if "cmd" in base or "command" in base:
        return "mcp__{name}__{tool}"
    return "{name}_{tool}"


def _mcp_server(install: Path) -> dict[str, Any]:
    """The per-session MCP server entry; the workspace stays implicit (cwd)."""
    if sys.platform == "win32":
        exe = install / "Scripts" / "pythonw.exe"
        if not exe.exists():
            exe = install / "Scripts" / "python.exe"
    else:
        exe = install / "bin" / "python"
    return {
        "name": SERVER_NAME,
        "command": str(exe),
        "args": ["-m", ENTRY_MODULE, "serve"],
    }


def _harness_plugin(agent: str) -> HarnessSpec | None:
    """The harness plugin whose config the ACP agent reads, or None."""
    base = Path(agent).name.lower()
    if "opencode" in base:
        wanted = "opencode"
    elif "cmd" in base or "command" in base:
        wanted = "commandcode"
    else:
        return None
    return next((spec for spec in load_harnesses() if spec.name == wanted), None)


def _entry_from_file(spec: HarnessSpec, path: Path) -> dict[str, Any] | None:
    """This server's entry in `path`, or None when the file has no usable one."""
    if spec.root_key is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
        if spec.format == "toml":
            document: Any = tomllib.loads(text)
        elif spec.format == "yaml":
            document = _yaml.parse(text)
        else:
            document = _json.parse(text)
    except (OSError, ValueError):
        return None
    node: Any = document
    for part in spec.root_key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    entry = node.get(SERVER_NAME) if isinstance(node, dict) else None
    return entry if isinstance(entry, dict) else None


def _configured_entry(
    spec: HarnessSpec, workspace: Path, home: Path | None = None
) -> tuple[Path | None, dict[str, Any] | None]:
    """First config file that already declares this server, global scope first."""
    candidates = [
        *spec.candidates("global", workspace, home),
        *spec.candidates("local", workspace, home),
    ]
    for path in candidates:
        if path.is_file():
            entry = _entry_from_file(spec, path)
            if entry is not None:
                return path, entry
    return None, None


def _entry_argv(entry: dict[str, Any]) -> list[str]:
    """The entry's launch command as one argv list (shape varies by harness)."""
    return entry_argv(entry)


def _inside(path: str, root: Path) -> bool:
    """Path containment without following symlinks.

    A POSIX venv's `bin/python` is a symlink to the base interpreter, so
    resolving it would report the entry as outside its own tool environment.
    """
    candidate = os.path.normcase(os.path.abspath(path))
    base = os.path.normcase(os.path.abspath(str(root)))
    return candidate == base or candidate.startswith(base + os.sep)


def _launches_install(entry: dict[str, Any], install: Path) -> bool:
    """True when the entry serves this module from an `install` interpreter.

    The interpreter must live in the tool environment (`python.exe` and
    `pythonw.exe` are both valid) and the argv must be the documented
    `-m simple_code_indexer serve` launch, optionally followed by the
    project-scope pin `--workspace <dir>` (ADR-022), so a stale entry naming
    another install or the deleted checkout copy is rejected.
    """
    argv = _entry_argv(entry)
    if not argv or not _inside(argv[0], install):
        return False
    tail = argv[1:]
    if len(tail) >= 2 and tail[-2] == WORKSPACE_FLAG:
        tail = tail[:-2]
    return tail == ["-m", ENTRY_MODULE, "serve"]


def _pinned_workspace(entry: dict[str, Any]) -> Path | None:
    """The workspace a project-scope entry pins, or None for a global entry."""
    argv = _entry_argv(entry)
    for index, item in enumerate(argv):
        if item == WORKSPACE_FLAG and index + 1 < len(argv):
            return Path(argv[index + 1])
        if item.startswith(WORKSPACE_FLAG + "="):
            return Path(item.partition("=")[2])
    return None


def _preflight_entry(
    spec: HarnessSpec,
    workspace: Path,
    install: Path,
    check: Any,
    *,
    home: Path | None = None,
) -> bool:
    """Prove the entry that will actually serve launches `install`.

    A harness in `_IGNORES_INJECTION` never starts the `session/new` server, so
    a missing or stale configured entry must stop the run here instead of
    surfacing later as a model that shells out. Harnesses that do honour the
    injection only report their entry.
    """
    required = spec.name in _IGNORES_INJECTION
    path, entry = _configured_entry(spec, workspace, home)
    label = f"{spec.label} configured entry launches this tool environment"
    if entry is None:
        if not required:
            print(
                "configured entry: none (this agent honours session injection)",
                flush=True,
            )
            return True
        check(label, False, f"no {SERVER_NAME!r} entry under {spec.root_key}")
        return False
    argv = _entry_argv(entry)
    pinned = _pinned_workspace(entry)
    scope = "project" if pinned is not None else "global"
    print(
        f"configured entry ({scope}): {path} -> {' '.join(argv)}",
        flush=True,
    )
    if not required:
        return True
    launches = _launches_install(entry, install)
    if launches and pinned is not None:
        try:
            same = pinned.resolve() == workspace.resolve()
        except OSError:
            same = False
        if not same:
            check(
                f"{spec.label} entry is pinned to this workspace",
                False,
                f"entry pins {pinned}, probe indexes {workspace}",
            )
            return False
        check(f"{spec.label} entry is pinned to this workspace", True, str(pinned))
    check(label, launches, f"{path}: {' '.join(argv)}")
    return launches


def _drain(stream: Any) -> None:
    for line in stream:
        _STDERR_TAIL.append(line.rstrip())
        del _STDERR_TAIL[:-400]


class AcpClient:
    """Minimal ACP client: newline-delimited JSON-RPC over the agent's stdio."""

    def __init__(self, argv: list[str], cwd: Path) -> None:
        self.proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        threading.Thread(target=_drain, args=(self.proc.stderr,), daemon=True).start()
        self._next_id = 0
        self._responses: dict[int, dict[str, Any]] = {}
        self.payloads: list[tuple[str, dict[str, Any]]] = []
        self.permissions = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            # `id` + `method` is a server-initiated REQUEST (must be answered);
            # `method` alone is a NOTIFICATION (must be dispatched). Swapping
            # these kills this thread and every later request times out.
            if "id" in msg and "method" in msg:
                self._server_request(msg)
            elif "id" in msg:
                self._responses[msg["id"]] = msg
            elif msg.get("method") == "session/update":
                self._update(msg.get("params") or {})

    def _update(self, params: dict[str, Any]) -> None:
        update = params.get("update") or {}
        kind = update.get("sessionUpdate")
        if kind:
            _UPDATES.append(kind)
        if kind != "tool_call_update":
            return
        name = update.get("name") or update.get("title") or "?"
        for block in update.get("content") or []:
            inner = block.get("content") or {}
            if inner.get("type") != "text":
                continue
            text = str(inner.get("text") or "").strip()
            # Tool results arrive either bare or inside a fenced block, and a
            # model may prefix them with prose; find the first JSON object.
            start = text.find("{")
            if start < 0:
                continue
            try:
                parsed, _ = json.JSONDecoder().raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                self.payloads.append((name, parsed))

    def _server_request(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        if method != "session/request_permission":
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "error": {"code": -32601, "message": f"unsupported: {method}"},
                }
            )
            return
        options = (msg.get("params") or {}).get("options") or []
        chosen = next(
            (o for o in options if o.get("kind") == "allow_once"),
            options[0] if options else None,
        )
        self.permissions += 1
        if chosen is None:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": {"outcome": {"outcome": "cancelled"}},
                }
            )
            return
        self._send(
            {
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {
                    "outcome": {"outcome": "selected", "optionId": chosen["optionId"]}
                },
            }
        )

    def _send(self, msg: dict[str, Any]) -> None:
        with self._lock:
            assert self.proc.stdin is not None
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()

    def request(
        self, method: str, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
        self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if request_id in self._responses:
                return self._responses.pop(request_id)
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"agent exited (rc={self.proc.returncode}) during {method}; "
                    f"stderr tail:\n" + "\n".join(_STDERR_TAIL[-10:])
                )
            time.sleep(0.05)
        raise TimeoutError(f"{method} timed out after {timeout:.0f}s")

    def prompt(self, session: str, text: str, timeout: float) -> str:
        result = self.request(
            "session/prompt",
            {"sessionId": session, "prompt": [{"type": "text", "text": text}]},
            timeout,
        )
        return str((result.get("result") or {}).get("stopReason") or "error")

    def close(self) -> int:
        """Close stdin (the documented shutdown) and reap the process."""
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            return self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return -1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace")
    parser.add_argument("--agent", default=None)
    parser.add_argument("--agent-args", default='["acp"]')
    parser.add_argument("--install", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT_S)
    parser.add_argument("--tool-format", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    install = _install_root(args.install)
    agent = _find_agent(args.agent)
    tool_format = _tool_format(agent, args.tool_format)

    def tool(tool_name: str) -> str:
        return tool_format.format(name=SERVER_NAME, tool=tool_name)

    checks: list[dict[str, Any]] = []

    def check(label: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": label, "pass": bool(passed), "detail": detail})
        print(
            f"[{'PASS' if passed else 'FAIL'}] {label}"
            + (f" — {detail}" if detail else ""),
            flush=True,
        )

    print(f"agent: {agent}", flush=True)
    print(f"workspace: {workspace}", flush=True)
    print(f"install: {install}", flush=True)
    print(
        f"tools: {tool('get_status')}, {tool('search_code')}, {tool('symbol_lookup')}",
        flush=True,
    )

    spec = _harness_plugin(agent)
    if spec is not None and not _preflight_entry(spec, workspace, install, check):
        print(
            f"\nRESULT: FAIL (0/{len(checks)})\n"
            f"the {spec.label} session will not start {SERVER_NAME!r}. "
            f"Rewrite the entry with `uv run simple-code-indexer setup "
            f"--harnesses {spec.name}`, restart the harness, and re-run.",
            flush=True,
        )
        if args.json:
            print(json.dumps({"pass": False, "checks": checks}, indent=2), flush=True)
        return 1

    client = AcpClient([agent, *json.loads(args.agent_args)], workspace)
    exit_code = -1
    try:
        init = client.request(
            "initialize", {"protocolVersion": 1, "clientCapabilities": {}}, args.timeout
        )
        info = (init.get("result") or {}).get("agentInfo") or {}
        check(
            "ACP initialize",
            bool(info),
            f"{info.get('name')} {info.get('version')}".strip(),
        )

        created = client.request(
            "session/new",
            {"cwd": str(workspace), "mcpServers": [_mcp_server(install)]},
            args.timeout,
        )
        session = (created.get("result") or {}).get("sessionId")
        check("session created", bool(session), str(session))
        if not session:
            raise RuntimeError("no session id")

        if args.model:
            client.request(
                "session/set_config_option",
                {"sessionId": session, "configId": "model", "value": args.model},
                args.timeout,
            )
            print(f"model: {args.model}", flush=True)

        def ask(instruction: str, marker: str, tries: int = 2) -> dict[str, Any] | None:
            """Ask for a tool call; return the first payload containing `marker`."""
            for attempt in range(tries):
                before = len(client.payloads)
                try:
                    stop = client.prompt(session, instruction, args.timeout)
                except TimeoutError as exc:
                    print(f"    attempt {attempt + 1}: {exc}", flush=True)
                    continue
                for _name, payload in client.payloads[before:]:
                    if marker in payload:
                        return payload
                print(
                    f"    attempt {attempt + 1}: stop={stop}, no '{marker}' payload",
                    flush=True,
                )
            return None

        # 1. get_status. The first call can beat the reader's registration with
        # the sidecar daemon, so poll the daemon-reported fields instead of
        # asserting on one sample.
        status: dict[str, Any] | None = None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            sample = ask(
                f"Call the tool named exactly `{tool('get_status')}` with arguments {{}}. "
                "Print its raw JSON.",
                "workspace",
                tries=1,
            )
            if sample is None:
                continue
            status = sample
            if sample.get("sessions") and sample.get("watcher_alive"):
                break
            time.sleep(3)
        if status is None:
            check("get_status returned a payload", False, "no JSON captured")
            raise RuntimeError("get_status unusable")
        check("get_status returned a payload", True)
        check(
            "workspace is the target (cwd inference, no pin)",
            Path(str(status.get("workspace"))).resolve() == workspace,
            str(status.get("workspace")),
        )
        check(
            "role is reader (sidecar)",
            status.get("role") == "reader",
            str(status.get("role")),
        )
        check("watcher alive", bool(status.get("watcher_alive")))
        check(
            "one registered session",
            (status.get("sessions") or 0) == 1,
            f"sessions={status.get('sessions')}",
        )
        check(
            "single config source",
            len(status.get("config_files") or []) <= 1,
            str(status.get("config_files")),
        )
        check(
            "embedding service reachable",
            (status.get("services") or {}).get("embedding") == "running",
            str((status.get("services") or {}).get("embedding")),
        )
        baseline_files = int(status.get("files_indexed") or 0)

        # 2. File watcher: create a fixture and require the index to follow.
        fixture = workspace / "acp_probe_fixture.py"
        fixture.write_text(
            "def acp_probe_function():\n    return 41\n\n\n"
            "class AcpProbeClass:\n    marker = 'acp_probe_marker'\n",
            encoding="utf-8",
        )
        watch_deadline = time.monotonic() + 45
        seen = baseline_files
        while time.monotonic() < watch_deadline:
            sample = ask(
                f"Call `{tool('get_status')}` with {{}}. Print its raw JSON.",
                "workspace",
                tries=1,
            )
            if sample and int(sample.get("files_indexed") or 0) > baseline_files:
                seen = int(sample["files_indexed"])
                break
            time.sleep(3)
        check(
            "watcher indexed the new file",
            seen > baseline_files,
            f"files {baseline_files} -> {seen}",
        )

        # 3. Symbol lookup.
        symbol = ask(
            f"Call the tool named exactly `{tool('symbol_lookup')}` with arguments "
            '{"symbol": "acp_probe_function"}. Print its raw JSON.',
            "symbol",
        )
        check(
            "symbol_lookup found the fixture",
            bool(symbol) and symbol.get("defined_in") == "acp_probe_fixture.py",
            json.dumps(symbol)[:160] if symbol else "no payload",
        )

        # 4. Lexical search.
        lexical = ask(
            f"Call the tool named exactly `{tool('search_code')}` with arguments "
            '{"query": "acp_probe_marker", "limit": 5}. Print its raw JSON.',
            "hits",
        )
        lexical_files = [h.get("file") for h in (lexical or {}).get("hits", [])]
        check(
            "lexical search hit the fixture",
            "acp_probe_fixture.py" in lexical_files,
            str(lexical_files[:3]),
        )
        check(
            "lexical source reported",
            (lexical or {}).get("source") == "lexical",
            str((lexical or {}).get("source")),
        )

        # 5. Semantic search (vectors may lag; retry once after a pause).
        semantic = ask(
            f"Call the tool named exactly `{tool('search_code')}` with arguments "
            '{"query": "function that returns forty one", "semantic": true, "limit": 3}. '
            "Print its raw JSON.",
            "hits",
        )
        if (
            semantic is not None
            and not semantic.get("hits")
            and semantic.get("ready") is False
        ):
            time.sleep(12)
            semantic = ask(
                f"Call `{tool('search_code')}` with "
                '{"query": "function that returns forty one", "semantic": true, "limit": 3}. '
                "Print its raw JSON.",
                "hits",
                tries=1,
            )
        check(
            "semantic source reported",
            (semantic or {}).get("source") == "semantic",
            str((semantic or {}).get("source")),
        )
        check(
            "semantic search returned hits",
            bool((semantic or {}).get("hits")),
            f"{len((semantic or {}).get('hits') or [])} hit(s)",
        )

        # 6. Edge cases: no crash, documented shapes.
        empty = ask(
            f'Call `{tool("search_code")}` with {{"query": ""}}. Print its raw JSON.',
            "hits",
        )
        check(
            "empty query returns no hits",
            (empty or {}).get("hits") == [],
            json.dumps(empty)[:120] if empty else "no payload",
        )
        unknown = ask(
            f'Call `{tool("symbol_lookup")}` with {{"symbol": "DefinitelyNotARealSymbolXYZ"}}. '
            "Print its raw JSON.",
            "symbol",
        )
        check(
            "unknown symbol is flagged, not invented",
            bool(unknown)
            and (unknown.get("found") is False or not unknown.get("defined_in")),
            json.dumps(unknown)[:120] if unknown else "no payload",
        )

        # 7. Artifacts must exist and agree with the tool.
        db = workspace / ".simple-ci" / "index.db"
        check("index.db exists", db.exists(), str(db))
        check(
            "writer.log exists",
            (workspace / ".simple-ci" / "log" / "writer.log").exists(),
        )
        if db.exists():
            try:
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                counts = {
                    table: con.execute(f"select count(*) from {table}").fetchone()[0]
                    for table in ("files", "symbols", "chunks")
                }
                con.close()
                print(f"    sqlite: {counts}", flush=True)
                check(
                    "sqlite counts are non-zero",
                    counts["files"] > 0 and counts["chunks"] > 0,
                    str(counts),
                )
                check(
                    "sqlite files match get_status",
                    counts["files"] == seen,
                    f"sqlite={counts['files']} status={seen}",
                )
            except sqlite3.Error as exc:
                check("sqlite readable", False, str(exc))

        # 8. Daemon identity (the reader is a client of the per-workspace writer).
        daemon_file = workspace / ".simple-ci" / "run" / "daemon.json"
        if daemon_file.exists():
            try:
                daemon = json.loads(daemon_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                daemon = {}
            check(
                "sidecar daemon published for this workspace",
                Path(str(daemon.get("workspace", ""))).resolve() == workspace,
                f"pid={daemon.get('pid')}",
            )
        else:
            check(
                "sidecar daemon published for this workspace",
                False,
                "daemon.json missing",
            )

        fixture.unlink(missing_ok=True)
    finally:
        exit_code = client.close()
        check("agent exited 0 on stdin close", exit_code == 0, f"exit={exit_code}")
        print(
            f"\npermissions={client.permissions} updates={len(_UPDATES)} "
            f"stderr_lines={len(_STDERR_TAIL)}",
            flush=True,
        )
        if _STDERR_TAIL:
            print(
                "-- agent stderr (tail) --\n" + "\n".join(_STDERR_TAIL[-10:]),
                file=sys.stderr,
            )

    passed = all(c["pass"] for c in checks)
    if args.json:
        print(json.dumps({"pass": passed, "checks": checks}, indent=2), flush=True)
    print(
        f"\nRESULT: {'PASS' if passed else 'FAIL'} ({sum(c['pass'] for c in checks)}/{len(checks)})",
        flush=True,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
