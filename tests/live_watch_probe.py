"""Index-on-save probe: create a file, find it via MCP in <5 s.

Runs on the host: spawns the MCP server as a subprocess, creates a temp .cpp in
the workspace (the process cwd, or `WORKSPACE_ROOT`), polls symbol_lookup until
the symbol appears, then cleans up. Prints PROBE OK + elapsed seconds.

Usage: uv run python tests/live_watch_probe.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from mcp_probe import ProbeError, _read_until, _rpc, _send, _spawn, _stderr_tail

SYMBOL = f"liveWatchProbeIndexOnSave{os.getpid()}"
WORKSPACE = Path(os.environ.get("WORKSPACE_ROOT") or Path.cwd()).resolve()
PROBE_FILE = WORKSPACE / f"watch_probe_tmp_{os.getpid()}.cpp"
SOURCE = f"""\
// index-on-save probe fixture (created and removed by live_watch_probe.py)
int {SYMBOL}(int seed) {{
    return seed * 31 + 7;
}}
"""


def main() -> None:
    proc, watchdog = _spawn([sys.executable, "-m", "simple_code_indexer.server"])
    assert proc.stdin is not None and proc.stdout is not None
    probe_file = PROBE_FILE
    started = time.monotonic()
    try:
        _send(
            proc,
            _rpc(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "live-watch-probe", "version": "0"},
                },
            ),
        )
        _read_until(proc, 1)
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        # Wait until the watcher is live so the save event is guaranteed to land.
        msg_id = 2
        ready_deadline = time.monotonic() + 10.0
        watcher_ready = False
        while time.monotonic() < ready_deadline:
            _send(
                proc,
                _rpc(msg_id, "tools/call", {"name": "get_status", "arguments": {}}),
            )
            result = _read_until(proc, msg_id).get("result", {})
            status = json.loads(result["content"][0]["text"])
            if status.get("watcher_alive"):
                watcher_ready = True
                break
            time.sleep(0.3)
            msg_id += 1
        if not watcher_ready:
            raise ProbeError("watcher never became alive within 10 s of startup")
        print(f"watcher alive after {msg_id - 2} polls")

        # Save event: create the file now that the watcher is up.
        probe_file.write_text(SOURCE, encoding="utf-8")
        created = time.monotonic()

        deadline = created + 5.0
        msg_id = 2
        elapsed = None
        while time.monotonic() < deadline:
            _send(
                proc,
                _rpc(
                    msg_id,
                    "tools/call",
                    {"name": "symbol_lookup", "arguments": {"symbol": SYMBOL}},
                ),
            )
            result = _read_until(proc, msg_id).get("result", {})
            content = result.get("content") or []
            payload = json.loads(content[0]["text"]) if content else {}
            if "line" in payload:
                elapsed = time.monotonic() - created
                break
            time.sleep(0.25)
            msg_id += 1

        if elapsed is None:
            raise ProbeError(f"{SYMBOL} not indexed within 5 s of save")
        print(f"indexed in {elapsed:.2f}s after save")
        if elapsed >= 5.0:
            raise ProbeError(f"index-on-save took {elapsed:.2f}s (target <5 s)")

        # Status should report a live watcher and a completed sweep
        # (startup reconcile may trail the watcher hit slightly).
        status: dict = {}
        status_deadline = time.monotonic() + 10.0
        while time.monotonic() < status_deadline:
            _send(
                proc,
                _rpc(msg_id + 1, "tools/call", {"name": "get_status", "arguments": {}}),
            )
            status_result = _read_until(proc, msg_id + 1).get("result", {})
            msg_id += 1
            status = json.loads(status_result["content"][0]["text"])
            if status.get("watcher_alive") and status.get("last_sweep"):
                break
            time.sleep(0.5)
        print(f"get_status: {json.dumps(status)}")
        if not status.get("watcher_alive"):
            raise ProbeError("watcher_alive is false after save")
        if not status.get("last_sweep"):
            raise ProbeError("last_sweep is null (startup reconcile did not finish)")
        print(f"PROBE OK ({time.monotonic() - started:.2f}s total)")
    finally:
        probe_file.unlink(missing_ok=True)
        time.sleep(1.0)  # let the tombstone pass the 400 ms debounce before kill
        watchdog.cancel()
        proc.kill()
        proc.wait()
        tail = _stderr_tail()
        if tail:
            print(tail, file=sys.stderr)


if __name__ == "__main__":
    main()
