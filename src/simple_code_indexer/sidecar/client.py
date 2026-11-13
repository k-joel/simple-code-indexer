"""Reader-side sidecar session: connect, register, heartbeat, respawn."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from multiprocessing.connection import Client
from multiprocessing.context import AuthenticationError
from typing import Any

from simple_code_indexer import parent_watch, workspace_lock
from simple_code_indexer.config import Settings, normalize_workspace_path
from simple_code_indexer.sidecar import paths, protocol

logger = logging.getLogger("simple_code_indexer.sidecar")

ATTACH_TIMEOUT_S = 3.0
RECONNECT_INTERVAL_S = 5.0
REQUEST_TIMEOUT_S = 3.0
_SPAWN_COOLDOWN_S = 2.0
_MAX_SPAWN_COOLDOWN_S = 30.0

# Windows process creation flags; harmless constants on other platforms.
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


class ReaderSession:
    """One MCP server's registration with the workspace's sidecar writer."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state_paths = paths.state_paths(settings)
        self.session_id = uuid.uuid4().hex
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: Any | None = None
        self._connected = False
        self._cached: dict[str, Any] | None = None
        self._children: list[subprocess.Popen[Any]] = []
        self._last_spawn_at = 0.0
        self._spawn_attempts = 0
        self._harness_pid, self._harness_name = self._harness_metadata()

    @property
    def connected(self) -> bool:
        return self._connected

    def cached_status(self) -> dict[str, Any] | None:
        return self._cached

    def start(self) -> bool:
        """Try one bounded attach, then keep reconnecting in the background."""
        logger.info(
            "reader session %s: workspace=%s harness=%s(%s) mode=%s",
            self.session_id,
            self.settings.workspace_root,
            self._harness_name,
            self._harness_pid,
            self.settings.mode,
        )
        try:
            connected = self._ensure_connected(ATTACH_TIMEOUT_S)
        except Exception:
            logger.warning("sidecar attach failed; serving read-only", exc_info=True)
            connected = False
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._supervise, name="sidecar-session", daemon=True
            )
            self._thread.start()
        return connected

    def close(self) -> None:
        """Unregister and close the control connection; idempotent."""
        if self._closed.is_set():
            return
        self._closed.set()
        connection = self._conn
        if connection is not None:
            try:
                protocol.request(
                    connection,
                    {"type": protocol.UNREGISTER},
                    1.0,
                    self._lock,
                )
                logger.info("reader session %s unregistered", self.session_id)
            except (protocol.ProtocolError, OSError, EOFError):
                logger.debug("reader session %s could not unregister", self.session_id)
            try:
                connection.close()
            except OSError:
                pass
        self._conn = None
        self._connected = False
        if self._thread is not None:
            self._thread.join(2.0)
        logger.info("reader session %s closed", self.session_id)

    def status(self, timeout: float = REQUEST_TIMEOUT_S) -> dict[str, Any] | None:
        """Ask the daemon for its status; never blocks longer than `timeout`."""
        connection = self._conn
        if connection is None or self._closed.is_set():
            return self._cached
        try:
            reply = protocol.request(
                connection, {"type": protocol.STATUS}, timeout, self._lock
            )
        except (protocol.ProtocolError, OSError, EOFError):
            self._disconnect()
            return self._cached
        if reply.get("type") != protocol.STATUS:
            return self._cached
        self._cached = reply
        return reply

    def _supervise(self) -> None:
        while not self._closed.is_set():
            if self._connected:
                if self._closed.wait(self.settings.heartbeat_s):
                    return
                try:
                    protocol.request(
                        self._conn,
                        {"type": protocol.HEARTBEAT},
                        REQUEST_TIMEOUT_S,
                        self._lock,
                    )
                except (protocol.ProtocolError, OSError, EOFError):
                    self._disconnect()
                continue
            if self._ensure_connected(1.0):
                continue
            self._closed.wait(RECONNECT_INTERVAL_S)

    def _ensure_connected(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while not self._closed.is_set() and time.monotonic() < deadline:
            if self._try_connect():
                return True
            self._spawn_if_needed()
            self._closed.wait(0.2)
        return False

    def _try_connect(self) -> bool:
        ready = paths.read_ready(self.settings)
        if ready is None:
            logger.debug("reader session %s: no sidecar ready file", self.session_id)
            return False
        if not self._pid_alive(ready["pid"]):
            logger.info(
                "reader session %s: stale sidecar pid %s; clearing discovery",
                self.session_id,
                ready["pid"],
            )
            paths.clear_ready(self.settings)
            paths.clear_token(self.settings)
            return False
        token = paths.read_token(self.settings)
        if token is None:
            logger.debug("reader session %s: no sidecar token", self.session_id)
            return False
        try:
            connection = Client(ready["endpoint"], authkey=token.encode("ascii"))
        except (OSError, EOFError, AuthenticationError, ValueError):
            logger.debug(
                "reader session %s: cannot connect to %s",
                self.session_id,
                ready["endpoint"],
                exc_info=True,
            )
            return False
        try:
            hello = {
                "type": protocol.HELLO,
                "protocol": protocol.PROTOCOL_VERSION,
                "workspace": normalize_workspace_path(self.settings.workspace_root),
                "session_id": self.session_id,
                "server_pid": os.getpid(),
                "harness_pid": self._harness_pid,
                "harness_name": self._harness_name,
            }
            welcome = protocol.request(connection, hello, REQUEST_TIMEOUT_S, self._lock)
            if welcome.get("type") != protocol.WELCOME:
                raise protocol.ProtocolError("expected welcome")
            registered = protocol.request(
                connection, {"type": protocol.REGISTER}, REQUEST_TIMEOUT_S, self._lock
            )
            if registered.get("type") != protocol.REGISTERED:
                logger.info(
                    "reader session %s: registration refused (%s)",
                    self.session_id,
                    registered.get("code", "unknown"),
                )
                raise protocol.ProtocolError(
                    f"registration failed: {registered.get('code', 'unknown')}"
                )
        except (protocol.ProtocolError, OSError, EOFError):
            logger.debug(
                "reader session %s: handshake with the sidecar failed",
                self.session_id,
                exc_info=True,
            )
            try:
                connection.close()
            except OSError:
                pass
            return False
        self._conn = connection
        self._connected = True
        self._spawn_attempts = 0
        status = registered.get("status")
        if isinstance(status, dict):
            self._cached = status
        logger.info(
            "reader session %s registered with the sidecar writer "
            "(daemon=%s, endpoint=%s, sessions=%s)",
            self.session_id,
            ready["pid"],
            ready["endpoint"],
            registered.get("sessions"),
        )
        return True

    def _disconnect(self) -> None:
        connection, self._conn = self._conn, None
        self._connected = False
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
        logger.info("sidecar connection lost; serving read-only until it returns")

    def _spawn_if_needed(self) -> None:
        now = time.monotonic()
        self._children = [child for child in self._children if child.poll() is None]
        if self._children:
            # The daemon we started is still starting (or running); a second
            # spawn would only race it for the lease and flash another window.
            return
        cooldown = min(
            _SPAWN_COOLDOWN_S * max(1, self._spawn_attempts), _MAX_SPAWN_COOLDOWN_S
        )
        if now - self._last_spawn_at < cooldown:
            return
        ready = paths.read_ready(self.settings)
        if ready is not None:
            if self._pid_alive(ready["pid"]):
                return
            paths.clear_ready(self.settings)
            paths.clear_token(self.settings)
        lock = workspace_lock.FileLock(self.state_paths.spawn_lock)
        try:
            acquired = lock.acquire()
        except OSError:
            logger.warning("cannot take the sidecar spawn lock", exc_info=True)
            return
        if not acquired:
            return
        try:
            ready = paths.read_ready(self.settings)
            if ready is not None and self._pid_alive(ready["pid"]):
                return
            self._last_spawn_at = now
            self._spawn_attempts += 1
            self._spawn_daemon()
        finally:
            lock.release()

    def _spawn_daemon(self) -> None:
        root = self.settings.workspace_root.resolve()
        env = dict(os.environ)
        env["WORKSPACE_ROOT"] = str(root)
        env["INDEX_DB"] = str(self.settings.index_db_path.resolve())
        command = [
            sys.executable,
            "-m",
            "simple_code_indexer.sidecar.daemon",
            "--workspace",
            str(root),
        ]
        options: dict[str, Any] = {
            "cwd": str(root),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        try:
            if sys.platform == "win32":
                # CREATE_NO_WINDOW (not DETACHED_PROCESS): the venv python.exe
                # redirector spawns the real interpreter without creation flags,
                # so a detached redirector would let that child allocate a
                # visible console window for the daemon's whole lifetime.
                flags = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
                try:
                    process = subprocess.Popen(
                        command,
                        creationflags=flags | _CREATE_BREAKAWAY_FROM_JOB,
                        **options,
                    )
                except OSError:
                    process = subprocess.Popen(command, creationflags=flags, **options)
            else:
                process = subprocess.Popen(
                    command, start_new_session=True, close_fds=True, **options
                )
        except OSError:
            logger.warning("cannot spawn the sidecar writer", exc_info=True)
            return
        self._children.append(process)
        threading.Thread(
            target=process.wait, name="sidecar-child-reaper", daemon=True
        ).start()
        logger.info("spawned sidecar writer pid=%d for %s", process.pid, root)

    def _harness_metadata(self) -> tuple[int | None, str | None]:
        try:
            harness = parent_watch.harness_process()
        except Exception:
            logger.debug("cannot resolve the harness process", exc_info=True)
            return None, None
        if harness is None:
            return None, None
        try:
            return harness.pid, harness.name
        finally:
            harness.close()

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            watched = parent_watch.watch_process(pid, "sidecar")
        except Exception:
            logger.debug("cannot check sidecar pid %d", pid, exc_info=True)
            return False
        if watched is None:
            return False
        watched.close()
        return True
