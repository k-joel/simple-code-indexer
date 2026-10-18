"""Stdio probe: initialize → tools/list → tools/call get_status.

Usage:
    uv run python tests/mcp_probe.py [cmd ...]   # default: current interpreter -m server

Run it from the workspace to index: the server inherits the process cwd unless
`WORKSPACE_ROOT` is set. Dumps the exact wire payloads so harness rejections
(outputSchema, tasks) can be inspected byte-for-byte. Exits non-zero if any
contract check fails.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any


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
            raise ProbeError(f"server closed stdout waiting for id {msg_id}")
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


def main() -> None:
    cmd = sys.argv[1:] or [sys.executable, "-m", "simple_code_indexer.server"]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
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
            "watcher_alive",
            "workspace",
            "collection",
            "index_db",
        ):
            if key not in payload:
                raise ProbeError(f"get_status payload missing {key}: {payload}")
        print(f"get_status: {json.dumps(payload)}")

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
        proc.kill()
        proc.wait()
        if proc.stderr is not None:
            stderr_text = proc.stderr.read()
            if stderr_text:
                print(stderr_text, file=sys.stderr)


if __name__ == "__main__":
    main()
