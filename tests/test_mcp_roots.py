"""MCP roots as the second workspace source (ADR-018)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from mcp import types

from simple_code_indexer import mcp_roots


class FakeSession:
    """Duck-typed `ServerSession`: only the roots surface `first_workspace` uses."""

    def __init__(
        self,
        roots: list[Path] | None = None,
        *,
        can_send: bool = True,
        declared: bool = True,
        error: Exception | None = None,
    ) -> None:
        self._roots = roots or []
        self.can_send_request = can_send
        self._declared = declared
        self._error = error
        self.calls = 0

    def check_client_capability(self, capability: types.ClientCapabilities) -> bool:
        return self._declared

    async def send_request(
        self, request: Any, result_type: Any, **kwargs: Any
    ) -> types.ListRootsResult:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return types.ListRootsResult(
            roots=[types.Root(uri=cast(Any, item.as_uri())) for item in self._roots]
        )


def test_root_path_accepts_an_existing_local_directory(tmp_path: Path) -> None:
    assert mcp_roots._root_path(tmp_path.as_uri()) == tmp_path.resolve()


def test_root_path_rejects_unusable_uris(tmp_path: Path) -> None:
    assert mcp_roots._root_path("https://example.com/project") is None
    assert mcp_roots._root_path("file:relative/path") is None
    assert mcp_roots._root_path((tmp_path / "missing").as_uri()) is None


def test_first_workspace_returns_the_first_existing_directory(tmp_path: Path) -> None:
    existing = tmp_path / "project"
    existing.mkdir()
    session = FakeSession([tmp_path / "missing", existing])

    assert asyncio.run(mcp_roots.first_workspace(session)) == existing.resolve()
    assert session.calls == 1


def test_first_workspace_is_skipped_when_workspace_root_is_set(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    session = FakeSession([tmp_path])

    assert asyncio.run(mcp_roots.first_workspace(session)) is None
    assert session.calls == 0


def test_first_workspace_is_skipped_without_a_back_channel(tmp_path: Path) -> None:
    session = FakeSession([tmp_path], can_send=False)

    assert asyncio.run(mcp_roots.first_workspace(session)) is None
    assert session.calls == 0


def test_first_workspace_requires_the_client_capability(tmp_path: Path) -> None:
    session = FakeSession([tmp_path], declared=False)

    assert asyncio.run(mcp_roots.first_workspace(session)) is None
    assert session.calls == 0


def test_first_workspace_is_fail_soft(tmp_path: Path) -> None:
    for error in (TimeoutError(), RuntimeError("peer dropped the request")):
        session = FakeSession([tmp_path], error=error)
        assert asyncio.run(mcp_roots.first_workspace(session)) is None


def test_first_workspace_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(mcp_roots.ROOTS_ENV, "0")
    session = FakeSession([tmp_path])

    assert asyncio.run(mcp_roots.first_workspace(session)) is None
    assert session.calls == 0


def test_timeout_env_is_parsed_fail_soft(monkeypatch) -> None:
    monkeypatch.delenv(mcp_roots.ROOTS_ENV, raising=False)
    assert mcp_roots.timeout_s() == mcp_roots.DEFAULT_TIMEOUT_S

    monkeypatch.setenv(mcp_roots.ROOTS_ENV, "-5")
    assert mcp_roots.timeout_s() == 0.0

    monkeypatch.setenv(mcp_roots.ROOTS_ENV, "2.5")
    assert mcp_roots.timeout_s() == 2.5

    monkeypatch.setenv(mcp_roots.ROOTS_ENV, "soon")
    assert mcp_roots.timeout_s() == mcp_roots.DEFAULT_TIMEOUT_S
