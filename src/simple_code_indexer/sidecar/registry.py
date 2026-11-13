"""Thread-safe session leases for the sidecar daemon's on-demand lifetime."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from simple_code_indexer import parent_watch


@dataclass
class Lease:
    """One live MCP session; the connection is the primary liveness signal."""

    session_id: str
    server_pid: int
    harness_pid: int | None
    harness_name: str | None
    connected_at: float
    last_heartbeat: float
    process: parent_watch.WatchedProcess | None = None
    connection: Any | None = field(default=None, repr=False)

    def process_alive(self) -> bool:
        """True when the MCP server process still exists (PID-reuse safe)."""
        return self.process is None or self.process.alive()

    def close(self) -> None:
        """Close the control connection and release the process handle."""
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
        process, self.process = self.process, None
        if process is not None:
            process.close()


class LeaseRegistry:
    """A dict of leases keyed by session id; all methods are thread-safe."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._leases: dict[str, Lease] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._leases)

    def register(self, lease: Lease) -> None:
        with self._lock:
            previous = self._leases.get(lease.session_id)
            self._leases[lease.session_id] = lease
        if previous is not None and previous is not lease:
            previous.close()

    def heartbeat(self, session_id: str, *, now: float | None = None) -> bool:
        moment = self._clock() if now is None else now
        with self._lock:
            lease = self._leases.get(session_id)
            if lease is None:
                return False
            lease.last_heartbeat = moment
            return True

    def remove(self, session_id: str) -> Lease | None:
        with self._lock:
            return self._leases.pop(session_id, None)

    def snapshot(self) -> list[Lease]:
        with self._lock:
            return list(self._leases.values())

    def expired(self, timeout_s: float, *, now: float | None = None) -> list[Lease]:
        moment = self._clock() if now is None else now
        with self._lock:
            return [
                lease
                for lease in self._leases.values()
                if moment - lease.last_heartbeat > timeout_s
            ]

    def harnesses(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"pid": lease.harness_pid, "name": lease.harness_name}
                for lease in self._leases.values()
                if lease.harness_pid is not None
            ]
