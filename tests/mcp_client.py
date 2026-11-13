"""Stdio MCP client for integration tests: deadlines and always-drained stderr."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

STEP_TIMEOUT_S = 60.0


class StdioServer:
    """One spawned MCP server with a small JSON-RPC client.

    An undrained stderr pipe can block the server on a log write, and a blocking
    readline turns any server stall into a hung test — hence both.
    """

    def __init__(self, workspace: Path, *, env: dict[str, str]) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "simple_code_indexer.server"],
            cwd=workspace,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self._lines: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self._stderr: list[str] = []
        self._next_id = 1
        for stream, kind in ((self._proc.stdout, "out"), (self._proc.stderr, "err")):
            threading.Thread(
                target=self._pump, args=(stream, kind), daemon=True
            ).start()

    def _pump(self, stream: Any, kind: str) -> None:
        for line in stream:
            self._lines.put((kind, line.rstrip()))

    def _send(self, message: dict[str, Any]) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(message) + "\n")
        self._proc.stdin.flush()

    def _await(self, msg_id: int, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                kind, line = self._lines.get(timeout=0.25)
            except queue.Empty:
                continue
            if kind == "err":
                self._stderr.append(line or "")
                continue
            if line is None:
                raise AssertionError(f"server closed stdout; stderr: {self._tail()}")
            if not line.startswith("{"):
                continue
            message = json.loads(line)
            if message.get("id") == msg_id:
                return message
        raise AssertionError(f"no reply to id {msg_id} in {timeout}s; {self._tail()}")

    def _tail(self) -> str:
        return "stderr tail: " + " | ".join(self._stderr[-5:])

    def start(self) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "integration-check", "version": "0"},
                },
            }
        )
        self._await(1, STEP_TIMEOUT_S)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(
        self, tool: str, args: dict[str, Any], timeout: float = STEP_TIMEOUT_S
    ) -> Any:
        msg_id = self._next_id
        self._next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            }
        )
        reply = self._await(msg_id, timeout)
        return json.loads(reply["result"]["content"][0]["text"])

    def poll(
        self,
        tool: str,
        args: dict[str, Any],
        ready: Any,
        timeout: float = STEP_TIMEOUT_S,
    ) -> Any:
        deadline = time.monotonic() + timeout
        while True:
            payload = self.call(tool, args)
            if ready(payload):
                return payload
            if time.monotonic() > deadline:
                raise AssertionError(f"{tool}({args}) never became ready: {payload}")
            time.sleep(0.5)

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
        self._proc.wait()
