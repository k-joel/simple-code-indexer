"""Two workspaces index into separate collections and never see each other.

Spawns the real server (real Qdrant + real embeddings), so it is skipped when
those services are down (TDD §11.2 "integration, services when reachable"). The
collections it creates are deleted again on the way out.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from simple_code_indexer.config import derive_collection_name

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "http://localhost:8080")
EMBED_DIM = 2560
STEP_TIMEOUT_S = 60.0

# Ambient overrides would break the per-workspace contract under test, and could
# otherwise aim this test's cleanup at a collection outside its temp workspace.
_CHILD_ENV_EXCLUDES = (
    "WORKSPACE_ROOT",
    "INDEX_DB",
    "QDRANT_COLLECTION",
    "SIMPLE_CI_CONFIG",
)


def _child_env() -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in _CHILD_ENV_EXCLUDES
    }
    env["SIMPLE_CI_CONFIG"] = "none"
    return env


def _reachable(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=1)
    except urllib.error.HTTPError:
        return True  # answered, just not 200 (llama.cpp 404s on /)
    except (urllib.error.URLError, ValueError):
        return False
    return True


pytestmark = pytest.mark.skipif(
    not (_reachable(f"{QDRANT_URL}/collections") and _reachable(EMBED_BASE_URL)),
    reason="qdrant or embeddings not reachable",
)


class Server:
    """Stdio client for a spawned server: deadlines, and stderr always drained.

    An undrained stderr pipe can block the server on a log write, and a blocking
    readline turns any server stall into a hung test — hence both.
    """

    def __init__(self, workspace: Path) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "simple_code_indexer.server"],
            cwd=workspace,
            env=_child_env(),
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
                    "clientInfo": {"name": "isolation-check", "version": "0"},
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
        self._proc.kill()
        self._proc.wait()


def _observation_files(observed: dict[str, Any]) -> set[str]:
    """Every file the workspace's own search paths returned, semantic or lexical."""
    return {
        hit["file"]
        for key in ("own_semantic", "absent_semantic")
        for hit in observed[key]["hits"]
    }


def _observe(workspace: Path, own: str, other: str) -> dict[str, Any]:
    """Run the server inside `workspace` and report what its tools see."""
    server = Server(workspace)
    try:
        server.start()
        status = server.poll(
            "get_status", {}, lambda s: s.get("watcher_alive") and s.get("last_sweep")
        )
        symbol = server.poll("symbol_lookup", {"symbol": own}, lambda s: "line" in s)
        return {
            "status": status,
            "symbol": symbol,
            "own_semantic": server.call(
                "search_code", {"query": own, "semantic": True}
            ),
            # Nearest-chunk search, so an unrelated query still returns this
            # workspace's closest chunk — but never the other workspace's.
            "absent_semantic": server.call(
                "search_code", {"query": other, "semantic": True}
            ),
            "absent_symbol": server.call("symbol_lookup", {"symbol": other}),
            "absent_search": server.call("search_code", {"query": other}),
        }
    finally:
        server.close()


def _track(created: list[str], collection: str, workspace: Path) -> None:
    """Track only a collection this test derived for its own temp workspace."""
    if collection == derive_collection_name(workspace, EMBED_DIM):
        created.append(collection)


def test_two_workspaces_get_separate_collections(tmp_path: Path) -> None:
    workspace_a = tmp_path / "alpha-project"
    workspace_b = tmp_path / "beta-project"
    fixtures = (
        (workspace_a, "alpha.cpp", "alphaOnlySymbol"),
        (workspace_b, "beta.cpp", "betaOnlySymbol"),
    )
    for workspace, filename, symbol in fixtures:
        workspace.mkdir()
        (workspace / filename).write_text(
            f"int {symbol}() {{ return 42; }}\n", encoding="utf-8"
        )

    from qdrant_client import QdrantClient

    client = QdrantClient(url=QDRANT_URL, check_compatibility=False)
    created: list[str] = []
    try:
        seen = _observe(workspace_a, "alphaOnlySymbol", "betaOnlySymbol")
        _track(created, seen["status"]["collection"], workspace_a)
        other = _observe(workspace_b, "betaOnlySymbol", "alphaOnlySymbol")
        _track(created, other["status"]["collection"], workspace_b)
        status_a, status_b = seen["status"], other["status"]

        assert status_a["workspace"] == str(workspace_a.resolve())
        assert status_b["workspace"] == str(workspace_b.resolve())
        assert status_a["collection"] == derive_collection_name(workspace_a, EMBED_DIM)
        assert status_b["collection"] == derive_collection_name(workspace_b, EMBED_DIM)
        assert status_a["collection"] != status_b["collection"]

        observations = (
            (seen, status_a["collection"], "alpha.cpp"),
            (other, status_b["collection"], "beta.cpp"),
        )
        for observed, collection, own_file in observations:
            assert observed["symbol"]["defined_in"] == own_file
            # The other workspace's symbol is neither resolvable nor searchable.
            assert observed["absent_symbol"]["found"] is False
            # Lexical search reads this workspace's own index DB, so a shared
            # INDEX_DB (misconfiguration) cannot pass as isolation.
            assert observed["absent_search"]["hits"] == []
            # Semantic hits are nearest-chunk, not matches, so they only have to
            # stay inside this workspace: a hit from beta.cpp in alpha's collection
            # would be the leak this test exists to catch.
            assert _observation_files(observed) <= {own_file}
            assert observed["own_semantic"]["source"] == "semantic"
            assert observed["absent_semantic"]["source"] == "semantic"
            # Vectors may legitimately still be missing if an embed failed and
            # the sweep has not retried it yet, so presence is a precondition.
            if client.count(collection).count:
                assert observed["own_semantic"]["hits"]
    finally:
        for collection in created:
            if client.collection_exists(collection):
                client.delete_collection(collection)
