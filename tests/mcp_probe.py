"""Stdio probe: initialize → tools/list → tools/call get_status.

Usage:
    uv run python tests/mcp_probe.py [cmd ...]   # default: current interpreter -m server

Run it from the workspace to index: the server inherits the process cwd unless
`WORKSPACE_ROOT` is set. Dumps the exact wire payloads so harness rejections
(outputSchema, tasks) can be inspected byte-for-byte. Exits non-zero if any
contract check fails.

The server's stderr is drained on a thread (an unread pipe blocks the server on
its next INFO log write), and `PROBE_TIMEOUT` (seconds, default 180) bounds the
child's lifetime so a stall becomes `PROBE FAIL` instead of a hang.

Set `PROBE_WAIT_INDEX=<N>` to hold the reader open until the index has at least
N files, zero pending embeddings and a completed sweep on two consecutive
samples. Use it before querying an index that was just deleted and rebuilt;
`PROBE_WAIT_TIMEOUT` (seconds, default 600) bounds that wait.
"""

from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import threading
import time
from typing import Any

_STDERR_TAIL: collections.deque[str] = collections.deque(maxlen=200)
_DEFAULT_PROBE_TIMEOUT_S = 180.0


def _stderr_tail(lines: int = 10) -> str:
    return "\n".join(list(_STDERR_TAIL)[-lines:])


class ProbeError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"PROBE FAIL: {message}")


def _rpc(
    msg_id: int, method: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _read_until(proc: subprocess.Popen[str], msg_id: int) -> dict[str, Any]:
    """Read stdout lines until the response for msg_id; ignore notifications."""
    assert proc.stdout is not None
    for _ in range(200):
        line = proc.stdout.readline()
        if not line:
            tail = _stderr_tail()
            raise ProbeError(
                f"server closed stdout waiting for id {msg_id}"
                + (f"; stderr tail:\n{tail}" if tail else "")
            )
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            raise ProbeError(f"non-JSON line on stdout: {line!r}") from None
        print(f"<< {line.rstrip()}")
        if msg.get("id") == msg_id:
            return msg
    raise ProbeError(f"no response for id {msg_id} in 200 lines")


def _send(proc: subprocess.Popen[str], msg: dict[str, Any]) -> None:
    assert proc.stdin is not None
    line = json.dumps(msg)
    print(f">> {line}")
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


def _drain_stderr(proc: subprocess.Popen[str]) -> None:
    """Keep the child's stderr pipe empty; retain only a tail for failures."""
    assert proc.stderr is not None
    for line in proc.stderr:
        _STDERR_TAIL.append(line.rstrip())


def _spawn(cmd: list[str]) -> tuple[subprocess.Popen[str], threading.Timer]:
    """Spawn the server with a drained stderr and a bounded lifetime."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    threading.Thread(
        target=_drain_stderr, args=(proc,), daemon=True, name="stderr-drain"
    ).start()
    timeout = float(os.environ.get("PROBE_TIMEOUT", _DEFAULT_PROBE_TIMEOUT_S))
    if int(os.environ.get("PROBE_WAIT_INDEX", "0") or 0) > 0:
        # The reindex gate outlives the plain probe bound; do not kill the
        # child before the gate's own deadline can fire.
        wait_timeout = float(os.environ.get("PROBE_WAIT_TIMEOUT", "600"))
        timeout = max(timeout, wait_timeout + 60.0)
    watchdog = threading.Timer(timeout, proc.kill)
    watchdog.daemon = True
    watchdog.start()
    return proc, watchdog


def main() -> None:
    cmd = sys.argv[1:] or [sys.executable, "-m", "simple_code_indexer.server"]
    proc, watchdog = _spawn(cmd)
    assert proc.stdin is not None and proc.stdout is not None

    try:
        _send(
            proc,
            _rpc(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-probe", "version": "0"},
                },
            ),
        )
        init = _read_until(proc, 1)
        init_result = init.get("result", {})
        if "tasks" in (init_result.get("capabilities") or {}):
            raise ProbeError("initialize result advertises capabilities.tasks")
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(proc, _rpc(2, "tools/list", {}))
        tools = _read_until(proc, 2).get("result", {}).get("tools", [])
        names = [t.get("name") for t in tools]
        print(f"tools: {names}")
        for required in ("search_code", "symbol_lookup", "get_status"):
            if required not in names:
                raise ProbeError(f"{required} missing from tools/list: {names}")
        for tool in tools:
            if tool.get("outputSchema"):
                raise ProbeError(f"tool {tool['name']} has a non-null outputSchema")
            if tool.get("execution"):
                raise ProbeError(f"tool {tool['name']} has execution.taskSupport")

        _send(proc, _rpc(3, "tools/call", {"name": "get_status", "arguments": {}}))
        call = _read_until(proc, 3).get("result", {})
        content = call.get("content") or []
        if not content or content[0].get("type") != "text":
            raise ProbeError(f"get_status returned no text content: {call}")
        payload = json.loads(content[0]["text"])
        for key in (
            "files_indexed",
            "symbols_indexed",
            "chunks_indexed",
            "vectors_indexed",
            "pending_embeddings",
            "watcher_alive",
            "workspace",
            "vector_store",
            "vector_store_ok",
            "vector_index",
            "index_db",
        ):
            if key not in payload:
                raise ProbeError(f"get_status payload missing {key}: {payload}")
        print(f"get_status: {json.dumps(payload)}")

        wait_for = int(os.environ.get("PROBE_WAIT_INDEX", "0") or 0)
        if wait_for > 0:
            wait_timeout = float(os.environ.get("PROBE_WAIT_TIMEOUT", "600"))
            deadline = time.monotonic() + wait_timeout
            stable = 0
            wait_id = 1000
            while True:
                _send(
                    proc,
                    _rpc(
                        wait_id,
                        "tools/call",
                        {"name": "get_status", "arguments": {}},
                    ),
                )
                wait_payload = json.loads(
                    _read_until(proc, wait_id)["result"]["content"][0]["text"]
                )
                wait_id += 1
                print(
                    "reindex: "
                    f"files={wait_payload['files_indexed']} "
                    f"chunks={wait_payload['chunks_indexed']} "
                    f"vectors={wait_payload['vectors_indexed']} "
                    f"pending={wait_payload['pending_embeddings']} "
                    f"sweep={wait_payload['last_sweep']}"
                )
                settled = (
                    int(wait_payload["files_indexed"]) >= wait_for
                    and int(wait_payload["pending_embeddings"]) == 0
                    and bool(wait_payload["watcher_alive"])
                    and bool(wait_payload["last_sweep"])
                )
                stable = stable + 1 if settled else 0
                if stable >= 2:
                    break
                if time.monotonic() > deadline:
                    raise ProbeError(
                        f"index did not settle at {wait_for} files with 0 pending "
                        f"within {wait_timeout:.0f}s: {wait_payload}"
                    )
                time.sleep(2.0)

        symbol_from_env = "PROBE_SYMBOL" in os.environ
        symbol = os.environ.get("PROBE_SYMBOL", "calculateWidgetChecksum")
        # Startup reconcile runs on a thread; poll until the fixture is indexed.
        deadline = time.monotonic() + (15.0 if symbol_from_env else 0.0)
        msg_id = 4
        while True:
            _send(
                proc,
                _rpc(
                    msg_id,
                    "tools/call",
                    {"name": "symbol_lookup", "arguments": {"symbol": symbol}},
                ),
            )
            sym_result = _read_until(proc, msg_id).get("result", {})
            sym_content = sym_result.get("content") or []
            if not sym_content:
                raise ProbeError(f"symbol_lookup returned no content: {sym_result}")
            sym_payload = json.loads(sym_content[0]["text"])
            # Flat shape (single hit) or found/matches envelope (zero/many).
            if "line" not in sym_payload and "found" not in sym_payload:
                raise ProbeError(f"symbol_lookup payload shape wrong: {sym_payload}")
            print(f"symbol_lookup: {json.dumps(sym_payload)}")

            _send(
                proc,
                _rpc(
                    msg_id + 1,
                    "tools/call",
                    {"name": "search_code", "arguments": {"query": symbol}},
                ),
            )
            search_result = _read_until(proc, msg_id + 1).get("result", {})
            search_content = search_result.get("content") or []
            if not search_content:
                raise ProbeError(f"search_code returned no content: {search_result}")
            search_payload = json.loads(search_content[0]["text"])
            if "hits" not in search_payload or "source" not in search_payload:
                raise ProbeError(f"search_code payload shape wrong: {search_payload}")
            print(f"search_code: {json.dumps(search_payload)}")

            found_ok = not symbol_from_env or "line" in sym_payload
            search_ok = not symbol_from_env or bool(search_payload["hits"])
            if found_ok and search_ok:
                break
            if time.monotonic() > deadline:
                raise ProbeError(f"PROBE_SYMBOL {symbol!r} not found before deadline")
            time.sleep(0.5)
            msg_id += 2

        if symbol_from_env:
            # Semantic path: vectors are written during index_one_file, so a
            # lexical hit implies vectors should exist (brief lag tolerated).
            sem_deadline = time.monotonic() + 10.0
            while True:
                _send(
                    proc,
                    _rpc(
                        msg_id,
                        "tools/call",
                        {
                            "name": "search_code",
                            "arguments": {"query": symbol, "semantic": True},
                        },
                    ),
                )
                sem_result = _read_until(proc, msg_id).get("result", {})
                msg_id += 1
                sem_payload = json.loads(sem_result["content"][0]["text"])
                if sem_payload.get("source") != "semantic":
                    raise ProbeError(f"semantic search source wrong: {sem_payload}")
                if sem_payload["hits"]:
                    print(f"semantic search: {json.dumps(sem_payload)}")
                    break
                if time.monotonic() > sem_deadline:
                    raise ProbeError(f"semantic search found nothing for {symbol!r}")
                time.sleep(1.0)
        print("PROBE OK")
    finally:
        watchdog.cancel()
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        tail = _stderr_tail()
        if tail:
            print(f"-- server stderr (tail) --\n{tail}", file=sys.stderr)


if __name__ == "__main__":
    main()
