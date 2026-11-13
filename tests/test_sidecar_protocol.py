"""Sidecar discovery files and the JSON control protocol."""

from __future__ import annotations

import sys
import threading
import time
from multiprocessing.connection import Client, Listener
from multiprocessing.context import AuthenticationError
from pathlib import Path
from typing import Any

import pytest

from simple_code_indexer.config import IGNORE_DIRS, Settings, normalize_workspace_path
from simple_code_indexer.registry import get_registry
from simple_code_indexer.sidecar import paths, protocol


def _settings(workspace: Path) -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=workspace,
        index_db_path=workspace / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_test",
        embed_base_url="http://localhost:1",
        embed_model="test-model",
        embed_dim=8,
        embed_timeout_s=1.0,
        sweep_seconds=0.0,
        debounce_ms=100,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
    )


def test_state_paths_live_in_the_workspace_run_directory(tmp_path: Path) -> None:
    state = paths.state_paths(_settings(tmp_path))
    expected = tmp_path / ".simple-ci" / "run"
    assert state.ready == expected / paths.READY_FILENAME
    assert state.token == expected / paths.TOKEN_FILENAME
    assert state.spawn_lock == expected / paths.SPAWN_LOCK_FILENAME


def test_endpoint_is_stable_and_workspace_specific(tmp_path: Path) -> None:
    first = _settings(tmp_path / "one")
    second = _settings(tmp_path / "two")
    assert paths.endpoint(first) == paths.endpoint(first)
    assert paths.endpoint(first) != paths.endpoint(second)


def test_ready_file_round_trip_and_clear(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert paths.read_ready(settings) is None

    paths.write_ready(settings, pid=12345, endpoint=paths.endpoint(settings))
    ready = paths.read_ready(settings)
    assert ready is not None
    assert ready["pid"] == 12345
    assert ready["protocol"] == paths.PROTOCOL_VERSION
    assert ready["workspace"] == str(settings.workspace_root.resolve())

    paths.clear_ready(settings)
    assert paths.read_ready(settings) is None


def test_token_round_trip_and_clear(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert paths.read_token(settings) is None
    paths.write_token(settings, "secret")
    assert paths.read_token(settings) == "secret"
    paths.clear_token(settings)
    assert paths.read_token(settings) is None


def _hello(settings: Settings, **overrides: Any) -> dict[str, Any]:
    message = {
        "type": protocol.HELLO,
        "protocol": paths.PROTOCOL_VERSION,
        "workspace": normalize_workspace_path(settings.workspace_root),
        "session_id": "session-1",
        "server_pid": 4242,
    }
    message.update(overrides)
    return message


def test_validate_hello_accepts_a_matching_workspace(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert protocol.validate_hello(_hello(settings), settings) == "session-1"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"protocol": 99}, "protocol"),
        ({"workspace": "/somewhere/else"}, "workspace"),
        ({"session_id": ""}, "session_id"),
        ({"server_pid": 0}, "server_pid"),
        ({"type": "status"}, "first message"),
    ],
)
def test_validate_hello_rejects_bad_handshakes(
    tmp_path: Path, overrides: dict[str, Any], match: str
) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(protocol.ProtocolError, match=match):
        protocol.validate_hello(_hello(settings, **overrides), settings)


class _FakeConnection:
    def __init__(self, reply: Any = None, *, ready: bool = True) -> None:
        self.reply = reply
        self.ready = ready
        self.sent: list[Any] = []

    def poll(self, timeout: float) -> bool:
        return self.ready

    def recv(self) -> Any:
        return self.reply

    def send(self, message: Any) -> None:
        self.sent.append(message)


def test_receive_message_rejects_non_json_text() -> None:
    with pytest.raises(protocol.ProtocolError, match="invalid JSON"):
        protocol.receive_message(_FakeConnection("not json"), 1.0)


def test_receive_message_rejects_a_pickled_object() -> None:
    with pytest.raises(protocol.ProtocolError, match="JSON text"):
        protocol.receive_message(_FakeConnection({"type": "hello"}), 1.0)


def test_request_times_out_without_a_reply() -> None:
    with pytest.raises(protocol.ProtocolError, match="timed out"):
        protocol.request(
            _FakeConnection(ready=False), {"type": "status"}, 0.1, threading.Lock()
        )


def _listener_for(settings: Settings, token: str) -> Listener:
    endpoint = paths.endpoint(settings)
    if sys.platform != "win32":
        try:
            Path(endpoint).unlink()
        except OSError:
            pass
        return Listener(endpoint, family="AF_UNIX", authkey=token.encode("ascii"))
    return Listener(endpoint, authkey=token.encode("ascii"))


def test_authkey_and_json_round_trip(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    endpoint = paths.endpoint(settings)
    token = "test-token"
    listener = _listener_for(settings, token)
    received: list[dict[str, Any]] = []

    def serve() -> None:
        try:
            connection = listener.accept()
        except (OSError, ConnectionError, AuthenticationError):
            return
        try:
            message = protocol.receive_message(connection, 5.0)
            if message is not None:
                received.append(message)
                protocol.send_message(connection, {"type": protocol.WELCOME})
        finally:
            connection.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        connection = Client(endpoint, authkey=token.encode("ascii"))
        try:
            reply = protocol.request(
                connection, {"type": protocol.HELLO}, 5.0, threading.Lock()
            )
        finally:
            connection.close()
        assert reply["type"] == protocol.WELCOME
        assert received == [{"type": protocol.HELLO}]
    finally:
        listener.close()
        thread.join(5.0)
        if sys.platform != "win32":
            try:
                Path(endpoint).unlink()
            except OSError:
                pass


def test_a_wrong_authkey_is_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    endpoint = paths.endpoint(settings)
    listener = _listener_for(settings, "right-token")

    def accept_and_close() -> None:
        try:
            connection = listener.accept()
            connection.close()
        except (OSError, ConnectionError, AuthenticationError):
            return

    thread = threading.Thread(target=accept_and_close, daemon=True)
    thread.start()
    try:
        with pytest.raises(AuthenticationError):
            Client(endpoint, authkey=b"wrong-token")
    finally:
        listener.close()
        thread.join(2.0)
        time.sleep(0.05)
        if sys.platform != "win32":
            try:
                Path(endpoint).unlink()
            except OSError:
                pass
