"""Control protocol between an MCP reader and its sidecar writer daemon.

`multiprocessing.connection` already authenticates both sides with an HMAC
challenge (`authkey`). Message bodies are JSON text, never pickled objects, so
a malformed or unexpected payload cannot execute code.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from simple_code_indexer.config import Settings, normalize_workspace_path
from simple_code_indexer.sidecar.paths import PROTOCOL_VERSION

HELLO = "hello"
WELCOME = "welcome"
REGISTER = "register"
REGISTERED = "registered"
HEARTBEAT = "heartbeat"
HEARTBEAT_ACK = "heartbeat_ack"
UNREGISTER = "unregister"
UNREGISTERED = "unregistered"
STATUS = "status"
STOP = "stop"
STOPPING = "stopping"
ERROR = "error"


class ProtocolError(Exception):
    """A control message is malformed, out of order, or timed out."""


def send_message(conn: Any, message: dict[str, Any]) -> None:
    conn.send(json.dumps(message, separators=(",", ":")))


def receive_message(conn: Any, timeout: float) -> dict[str, Any] | None:
    """Return the next message, or None when nothing arrived within `timeout`."""
    if not conn.poll(timeout):
        return None
    try:
        raw = conn.recv()
    except (EOFError, OSError) as exc:
        raise ProtocolError("connection closed") from exc
    if not isinstance(raw, str):
        raise ProtocolError("expected a JSON text message")
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("message is not an object")
    return message


def request(
    conn: Any,
    message: dict[str, Any],
    timeout: float,
    lock: threading.Lock,
) -> dict[str, Any]:
    """Send one request and wait for its reply, serialized on this connection."""
    with lock:
        send_message(conn, message)
        reply = receive_message(conn, timeout)
    if reply is None:
        raise ProtocolError("timed out waiting for a reply")
    return reply


def validate_hello(message: dict[str, Any], settings: Settings) -> str:
    """Validate the first message and return its session id."""
    if message.get("type") != HELLO:
        raise ProtocolError("the first message must be hello")
    if message.get("protocol") != PROTOCOL_VERSION:
        raise ProtocolError(
            f"protocol {message.get('protocol')!r} is not {PROTOCOL_VERSION}"
        )
    workspace = message.get("workspace")
    expected = normalize_workspace_path(settings.workspace_root)
    if workspace != expected:
        raise ProtocolError(f"workspace {workspace!r} is not {expected!r}")
    session_id = message.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ProtocolError("hello requires a non-empty session_id")
    server_pid = message.get("server_pid")
    if not isinstance(server_pid, int) or server_pid <= 0:
        raise ProtocolError("hello requires a positive server_pid")
    return session_id
