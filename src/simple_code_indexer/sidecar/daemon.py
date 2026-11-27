"""Per-workspace sidecar writer daemon (on-demand lifetime).

Started detached by an MCP reader. Holds the workspace writer lease for its whole
lifetime, serves a local control pipe, and exits after the last registered
session has been gone for `idle_grace_s`.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import secrets
import signal
import sys
import threading
import time
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Any

from simple_code_indexer import logging_setup, parent_watch, runtime
from simple_code_indexer.config import Settings, load_settings
from simple_code_indexer.errors import WorkspaceBusy
from simple_code_indexer.sidecar import paths, protocol
from simple_code_indexer.sidecar.registry import Lease, LeaseRegistry

logger = logging.getLogger("simple_code_indexer.sidecar")

# Bound on the self-connection that wakes `_accept_loop` at shutdown; a local
# pipe/socket connect either completes immediately or the loop is already gone.
_WAKE_TIMEOUT_S = 1.0


class SidecarDaemon:
    """The single writer process for one workspace."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state_paths = paths.state_paths(settings)
        self.endpoint = paths.endpoint(settings)
        self._runtime = runtime.WriterRuntime(settings)
        self._registry = LeaseRegistry()
        self._stop = threading.Event()
        self._draining = False
        self._shutdown_done = False
        self._listener: Listener | None = None
        self._accept_thread: threading.Thread | None = None
        self._reaper_thread: threading.Thread | None = None
        self._clients: set[Any] = set()
        self._clients_lock = threading.Lock()
        self._last_session_at = time.monotonic()
        self._started_at = time.monotonic()
        self._ready_written = False
        self._token_written = False

    def run(self) -> int:
        try:
            self._runtime.start()
        except WorkspaceBusy:
            logger.info(
                "another writer owns %s; the sidecar exits",
                self.settings.index_db_path,
            )
            return 0
        except Exception:
            logger.exception("the sidecar writer failed to start")
            return 1
        try:
            self._open_listener()
            paths.write_ready(self.settings, pid=os.getpid(), endpoint=self.endpoint)
            self._ready_written = True
            atexit.register(self._shutdown)
            self._install_signal_handlers()
            listener = self._listener
            assert listener is not None
            self._accept_thread = threading.Thread(
                target=self._accept_loop,
                args=(listener,),
                name="sidecar-accept",
                daemon=True,
            )
            self._accept_thread.start()
            self._reaper_thread = threading.Thread(
                target=self._reaper_loop, name="sidecar-reaper", daemon=True
            )
            self._reaper_thread.start()
            logger.info("sidecar ready: %s", self.endpoint)
            self._stop.wait()
        finally:
            self._shutdown()
        return 0

    def _open_listener(self) -> None:
        token = secrets.token_hex(32)
        token_path = paths.write_token(self.settings, token)
        self._token_written = True
        logger.debug("sidecar token written to %s", token_path)
        if sys.platform != "win32":
            try:
                Path(self.endpoint).unlink()
            except OSError:
                pass
        authkey = token.encode("ascii")
        if sys.platform == "win32":
            self._listener = Listener(self.endpoint, authkey=authkey)
        else:
            self._listener = Listener(self.endpoint, family="AF_UNIX", authkey=authkey)
            try:
                os.chmod(self.endpoint, 0o600)
            except OSError:
                pass

    def _accept_loop(self, listener: Listener) -> None:
        while not self._stop.is_set():
            try:
                connection = listener.accept()
            except (OSError, EOFError):
                break
            if self._stop.is_set():
                # The self-connection from `_stop_accepting`: acknowledge it and
                # leave, so shutdown never registers a phantom session.
                try:
                    connection.close()
                except OSError:
                    pass
                break
            with self._clients_lock:
                self._clients.add(connection)
            threading.Thread(
                target=self._client_loop,
                args=(connection,),
                name="sidecar-client",
                daemon=True,
            ).start()

    def _client_loop(self, connection: Any) -> None:
        session_id: str | None = None
        hello: dict[str, Any] | None = None
        registered = False
        try:
            hello = protocol.receive_message(connection, timeout=self._timeout())
            if hello is None:
                return
            try:
                session_id = protocol.validate_hello(hello, self.settings)
            except protocol.ProtocolError as exc:
                protocol.send_message(
                    connection,
                    {"type": protocol.ERROR, "code": "protocol", "message": str(exc)},
                )
                return
            logger.info(
                "sidecar client connected: session=%s server_pid=%s harness=%s(%s) "
                "workspace=%s",
                session_id,
                hello.get("server_pid"),
                hello.get("harness_name"),
                hello.get("harness_pid"),
                hello.get("workspace"),
            )
            self._last_session_at = time.monotonic()
            protocol.send_message(
                connection,
                {
                    "type": protocol.WELCOME,
                    "protocol": protocol.PROTOCOL_VERSION,
                    "daemon_pid": os.getpid(),
                    "status": self._status(),
                },
            )
            while not self._stop.is_set():
                message = protocol.receive_message(connection, timeout=self._timeout())
                if message is None:
                    break
                kind = message.get("type")
                if kind == protocol.REGISTER:
                    if self._draining:
                        protocol.send_message(
                            connection, {"type": protocol.ERROR, "code": "draining"}
                        )
                        continue
                    self._registry.register(
                        self._make_lease(session_id, hello, connection)
                    )
                    registered = True
                    self._last_session_at = time.monotonic()
                    logger.info(
                        "sidecar session registered: %s (sessions=%d, harnesses=%s)",
                        session_id,
                        len(self._registry),
                        self._registry.harnesses(),
                    )
                    protocol.send_message(
                        connection,
                        {
                            "type": protocol.REGISTERED,
                            "sessions": len(self._registry),
                            "status": self._status(),
                        },
                    )
                elif kind == protocol.HEARTBEAT:
                    self._registry.heartbeat(session_id)
                    protocol.send_message(connection, {"type": protocol.HEARTBEAT_ACK})
                elif kind == protocol.STATUS:
                    protocol.send_message(
                        connection, {"type": protocol.STATUS, **self._status()}
                    )
                elif kind == protocol.UNREGISTER:
                    protocol.send_message(connection, {"type": protocol.UNREGISTERED})
                    break
                elif kind == protocol.STOP:
                    protocol.send_message(connection, {"type": protocol.STOPPING})
                    self._stop.set()
                    break
                else:
                    protocol.send_message(
                        connection,
                        {
                            "type": protocol.ERROR,
                            "code": "unknown",
                            "message": str(kind),
                        },
                    )
                    break
        except (protocol.ProtocolError, OSError, EOFError):
            logger.debug("sidecar client disconnected", exc_info=True)
        finally:
            if session_id is not None:
                removed = self._registry.remove(session_id)
                if removed is not None:
                    removed.close()
                logger.info(
                    "sidecar client disconnected: session=%s registered=%s "
                    "(sessions=%d, harnesses=%s)",
                    session_id,
                    registered,
                    len(self._registry),
                    self._registry.harnesses(),
                )
            with self._clients_lock:
                self._clients.discard(connection)
            try:
                connection.close()
            except OSError:
                pass

    def _make_lease(
        self, session_id: str, hello: dict[str, Any], connection: Any
    ) -> Lease:
        server_pid = int(hello["server_pid"])
        harness_pid = hello.get("harness_pid")
        if not isinstance(harness_pid, int) or harness_pid <= 0:
            harness_pid = None
        harness_name = hello.get("harness_name")
        if not isinstance(harness_name, str):
            harness_name = None
        now = time.monotonic()
        return Lease(
            session_id=session_id,
            server_pid=server_pid,
            harness_pid=harness_pid,
            harness_name=harness_name,
            connected_at=now,
            last_heartbeat=now,
            process=parent_watch.watch_process(
                server_pid, harness_name or "mcp-server"
            ),
            connection=connection,
        )

    def _reaper_loop(self) -> None:
        while not self._stop.wait(1.0):
            now = time.monotonic()
            timeout = max(1.0, 3.0 * self.settings.heartbeat_s)
            for lease in self._registry.expired(timeout, now=now):
                if self._registry.remove(lease.session_id) is not None:
                    logger.info("reaping stale sidecar session %s", lease.session_id)
                    lease.close()
            for lease in self._registry.snapshot():
                if not lease.process_alive() and (
                    self._registry.remove(lease.session_id) is not None
                ):
                    logger.info(
                        "reaping sidecar session %s (server exited)",
                        lease.session_id,
                    )
                    lease.close()
            if self._draining:
                continue
            if len(self._registry):
                self._last_session_at = now
                continue
            idle_for = now - self._last_session_at
            if idle_for >= self.settings.idle_grace_s:
                logger.info("no sidecar sessions for %.0f s; shutting down", idle_for)
                self._draining = True
                self._stop.set()

    def _status(self) -> dict[str, Any]:
        writer = self._runtime.status()
        return {
            "daemon_pid": os.getpid(),
            "sessions": len(self._registry),
            "harnesses": self._registry.harnesses(),
            "watcher_alive": writer["watcher_alive"],
            "last_sweep": writer["last_sweep"],
            "ignored_dirs": writer["ignored_dirs"],
            "ignored_files": writer["ignored_files"],
            "vector_store_ok": writer["vector_store_ok"],
            "services": writer["services"],
            "vector_index_age_s": writer["vector_index_age_s"],
            "writer_log_file": str(
                logging_setup.log_path(self.settings, logging_setup.WRITER_LOG_FILENAME)
            ),
            "endpoint": self.endpoint,
            "sweep_seconds": self.settings.sweep_seconds,
            "started_at": writer["started_at"],
            "uptime_s": time.monotonic() - self._started_at,
            "writer_pid": writer["writer_pid"],
            "writer_ok": writer["writer_ok"],
            "writer_heartbeat_age_s": writer["writer_heartbeat_age_s"],
        }

    def _timeout(self) -> float:
        return max(1.0, 3.0 * self.settings.heartbeat_s)

    def _install_signal_handlers(self) -> None:
        def _stop(*_args: Any) -> None:
            self._stop.set()

        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            signum = getattr(signal, name, None)
            if signum is None:
                continue
            try:
                signal.signal(signum, _stop)
            except (ValueError, OSError):
                pass

    def _wake_accept_loop(self, token: str) -> None:
        try:
            Client(self.endpoint, authkey=token.encode("ascii")).close()
        except (OSError, EOFError):
            logger.debug("cannot wake the accept loop", exc_info=True)

    def _stop_accepting(self) -> None:
        """Wake `_accept_loop`, then close the listener.

        `Listener.close()` does not interrupt a thread already blocked in
        `accept()` (a Windows named pipe keeps its pending handle, and a POSIX
        socket close is not a reliable wake either), so a plain close leaves that
        thread parked and shutdown waits out its join timeout — 2 s on every
        exit. One self-connection ends the loop deterministically: `_accept_loop`
        recognises it by the already-set stop event and closes it without
        registering a session.

        The connect runs on its own thread with a short join because
        `multiprocessing.connection.Client` waits for a pipe instance with no
        timeout: if the accept loop has already died, the connect would block
        shutdown forever. The thread is a daemon, so a pathological case costs at
        most the join below and never the process.
        """
        listener, self._listener = self._listener, None
        if listener is None:
            return
        token = paths.read_token(self.settings)
        if token is not None:
            wake = threading.Thread(
                target=self._wake_accept_loop,
                args=(token,),
                name="sidecar-wake",
                daemon=True,
            )
            wake.start()
            wake.join(_WAKE_TIMEOUT_S)
        try:
            listener.close()
        except OSError:
            pass

    def _shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._draining = True
        self._stop.set()
        self._stop_accepting()
        with self._clients_lock:
            clients = list(self._clients)
        for connection in clients:
            try:
                connection.close()
            except OSError:
                pass
        # Clear discovery before the runtime stops, so a reader that has just
        # lost the session cannot see a ready file that points at a dying daemon.
        if self._ready_written:
            paths.clear_ready(self.settings)
            self._ready_written = False
        if self._token_written:
            paths.clear_token(self.settings)
            self._token_written = False
        for thread in (self._accept_thread, self._reaper_thread):
            if thread is not None:
                thread.join(2.0)
        if sys.platform != "win32":
            try:
                Path(self.endpoint).unlink()
            except OSError:
                pass
        self._runtime.stop()
        logger.info("sidecar stopped")
        logging.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simple-code-indexer-sidecar")
    parser.add_argument("--workspace")
    parser.add_argument("--index-db")
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).resolve() if args.workspace else None
    index_db = Path(args.index_db).resolve() if args.index_db else None
    settings = load_settings(cli_workspace=workspace, cli_index_db=index_db)
    if workspace is not None and workspace != settings.workspace_root:
        print(
            "simple-code-indexer sidecar: workspace mismatch "
            f"({workspace} != {settings.workspace_root})",
            file=sys.stderr,
        )
        return 2
    log_file = logging_setup.configure_file(
        settings, filename=logging_setup.WRITER_LOG_FILENAME
    )
    logging_setup.install_excepthooks()
    logging_setup.log_startup(settings, log_file, role="writer")
    logging.getLogger("simple_code_indexer.sidecar").info(
        "sidecar lifetime: idle_grace=%ss heartbeat=%ss",
        settings.idle_grace_s,
        settings.heartbeat_s,
    )
    return SidecarDaemon(settings).run()


if __name__ == "__main__":
    raise SystemExit(main())
