"""MCP `roots/list`: the client's own statement of the folders it has open.

`roots/list` is a server-initiated request, so it is only legal once the
session is initialized and only on a connection with a back-channel (the
2026-07-28 protocol forbids server-initiated requests). `server.ServerState`
asks for roots when it binds the workspace (ADR-018).

The probe is best-effort and bounded: a client may advertise `roots` and never
answer — the Command Code VS Code extension does exactly that — so a timeout
falls through to the next workspace source.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

from mcp import types

logger = logging.getLogger(__name__)

ROOTS_ENV = "SIMPLE_CI_ROOTS_TIMEOUT_S"
DEFAULT_TIMEOUT_S = 1.0
_WORKSPACE_ROOT_ENV = "WORKSPACE_ROOT"


def timeout_s() -> float:
    """Probe budget; `SIMPLE_CI_ROOTS_TIMEOUT_S=0` disables the probe."""
    raw = os.environ.get(ROOTS_ENV)
    if raw is None:
        return DEFAULT_TIMEOUT_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("%s must be a number, got %r", ROOTS_ENV, raw)
        return DEFAULT_TIMEOUT_S


def _root_path(uri: object) -> Path | None:
    """Local directory behind a `file:` root URI, or None."""
    parts = urlsplit(str(uri))
    if parts.scheme != "file" or parts.netloc not in {"", "localhost"}:
        return None
    try:
        path = Path(url2pathname(parts.path))
    except (OSError, ValueError):
        return None
    if not path.is_absolute():
        return None
    try:
        path = path.resolve()
    except OSError:
        return None
    return path if path.is_dir() else None


async def first_workspace(session: Any) -> Path | None:
    """First existing directory in the client's MCP roots, or None.

    Returns early when `WORKSPACE_ROOT` is set (it already wins), when the
    connection has no back-channel, when the client did not declare `roots`,
    or when the request fails or times out. Never raises.
    """
    if os.environ.get(_WORKSPACE_ROOT_ENV):
        return None
    budget = timeout_s()
    if budget <= 0:
        return None
    if not getattr(session, "can_send_request", False):
        return None
    try:
        declared = session.check_client_capability(
            types.ClientCapabilities(roots=types.RootsCapability())
        )
    except Exception:  # noqa: BLE001 - a probe must never break startup
        declared = False
    if not declared:
        return None
    try:
        async with asyncio.timeout(budget):
            result = await session.send_request(
                types.ListRootsRequest(),
                types.ListRootsResult,
                request_read_timeout_seconds=budget,
            )
    except Exception as exc:  # noqa: BLE001 - timeout/no-back-channel/peer error
        logger.debug("roots/list unavailable: %s", exc)
        return None
    for root in result.roots:
        path = _root_path(root.uri)
        if path is not None:
            logger.debug("roots/list workspace: %s", path)
            return path
        logger.debug("ignoring unusable root %r", root.uri)
    return None
