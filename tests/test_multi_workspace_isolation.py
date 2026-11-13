"""Two workspaces index into separate FAISS files and never see each other.

Spawns the real server (real embeddings, local FAISS), so it is skipped when the
embedding service is down.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from mcp_client import StdioServer

EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "http://localhost:8080")
STEP_TIMEOUT_S = 60.0

# Ambient overrides would break the per-workspace contract under test.
_CHILD_ENV_EXCLUDES = (
    "WORKSPACE_ROOT",
    "INDEX_DB",
    "VECTOR_STORE",
    "FAISS_PATH",
    "QDRANT_URL",
    "QDRANT_COLLECTION",
    "SIMPLE_CI_CONFIG",
    "SIMPLE_CI_MODE",
)


def _child_env() -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in _CHILD_ENV_EXCLUDES
    }
    env["SIMPLE_CI_CONFIG"] = "none"
    env["SIMPLE_CI_MODE"] = "embedded"
    env["VECTOR_STORE"] = "faiss"
    return env


def _reachable(url: str) -> bool:
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/embeddings",
        data=b'{"model":"Qwen3-Embedding-4B-Q6_K","input":"ping"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            if response.status != 200:
                return False
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not data:
        return False
    vector = data[0].get("embedding") if isinstance(data[0], dict) else None
    return isinstance(vector, list) and len(vector) == 2560


pytestmark = pytest.mark.skipif(
    not _reachable(EMBED_BASE_URL), reason="embeddings not reachable"
)


def _observation_files(observed: dict[str, Any]) -> set[str]:
    """Every file the workspace's own search paths returned, semantic or lexical."""
    return {
        hit["file"]
        for key in ("own_semantic", "absent_semantic")
        for hit in observed[key]["hits"]
    }


def _observe(workspace: Path, own: str, other: str) -> dict[str, Any]:
    """Run the server inside `workspace` and report what its tools see."""
    server = StdioServer(workspace, env=_child_env())
    try:
        server.start()
        status = server.poll(
            "get_status",
            {},
            lambda s: (
                s.get("watcher_alive")
                and s.get("last_sweep")
                and s.get("pending_embeddings") == 0
            ),
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


def test_two_workspaces_get_separate_vector_files(tmp_path: Path) -> None:
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

    seen = _observe(workspace_a, "alphaOnlySymbol", "betaOnlySymbol")
    other = _observe(workspace_b, "betaOnlySymbol", "alphaOnlySymbol")
    status_a, status_b = seen["status"], other["status"]

    assert status_a["workspace"] == str(workspace_a.resolve())
    assert status_b["workspace"] == str(workspace_b.resolve())
    assert status_a["vector_store"] == "faiss"
    assert status_b["vector_store"] == "faiss"
    vector_a = Path(status_a["vector_index"])
    vector_b = Path(status_b["vector_index"])
    assert vector_a == workspace_a.resolve() / ".simple-ci" / "vectors.faiss"
    assert vector_b == workspace_b.resolve() / ".simple-ci" / "vectors.faiss"
    assert vector_a != vector_b
    assert vector_a.is_file()
    assert vector_b.is_file()
    assert status_a["vector_store_ok"] is True
    assert status_b["vector_store_ok"] is True

    observations = ((seen, "alpha.cpp"), (other, "beta.cpp"))
    for observed, own_file in observations:
        assert observed["symbol"]["defined_in"] == own_file
        # The other workspace's symbol is neither resolvable nor searchable.
        assert observed["absent_symbol"]["found"] is False
        # Lexical search reads this workspace's own index DB, so a shared
        # INDEX_DB (misconfiguration) cannot pass as isolation.
        assert observed["absent_search"]["hits"] == []
        # Semantic hits are nearest-chunk, not matches, so they only have to
        # stay inside this workspace: a hit from beta.cpp in alpha's file would
        # be the leak this test exists to catch.
        assert _observation_files(observed) <= {own_file}
        assert observed["own_semantic"]["source"] == "semantic"
        assert observed["absent_semantic"]["source"] == "semantic"
        assert observed["own_semantic"]["hits"]
