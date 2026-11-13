"""Session lease registry: add/remove, heartbeat expiry, replacement."""

from __future__ import annotations

from simple_code_indexer.sidecar.registry import Lease, LeaseRegistry


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _lease(session_id: str, *, now: float = 100.0) -> Lease:
    return Lease(
        session_id=session_id,
        server_pid=1234,
        harness_pid=4321,
        harness_name="opencode-cli.exe",
        connected_at=now,
        last_heartbeat=now,
    )


def test_register_heartbeat_and_remove() -> None:
    registry = LeaseRegistry()
    lease = _lease("a")
    registry.register(lease)

    assert len(registry) == 1
    assert registry.heartbeat("a", now=120.0) is True
    assert registry.snapshot()[0].last_heartbeat == 120.0
    assert registry.remove("a") is lease
    assert len(registry) == 0
    assert registry.heartbeat("a") is False


def test_expired_leases_are_returned_only_after_the_timeout() -> None:
    clock = _Clock()
    registry = LeaseRegistry(clock=clock)
    registry.register(_lease("a", now=clock.now))

    clock.now = 110.0
    assert registry.expired(15.0) == []

    clock.now = 116.0
    assert [lease.session_id for lease in registry.expired(15.0)] == ["a"]


def test_replacing_a_session_closes_the_previous_connection() -> None:
    registry = LeaseRegistry()
    old_connection = _Connection()
    first = _lease("a")
    first.connection = old_connection
    registry.register(first)

    second = _lease("a")
    registry.register(second)

    assert len(registry) == 1
    assert registry.snapshot()[0] is second
    assert old_connection.closed


def test_harnesses_are_reported_without_empty_entries() -> None:
    registry = LeaseRegistry()
    registry.register(_lease("a"))
    second = _lease("b")
    second.harness_pid = None
    second.harness_name = None
    registry.register(second)

    assert registry.harnesses() == [{"pid": 4321, "name": "opencode-cli.exe"}]


def test_lease_close_closes_the_connection() -> None:
    connection = _Connection()
    lease = _lease("a")
    lease.connection = connection
    lease.close()

    assert connection.closed
    assert lease.connection is None


def test_process_alive_without_a_snapshot_is_true() -> None:
    assert _lease("a").process_alive() is True


def test_session_ids_stay_distinct_behind_one_shared_harness() -> None:
    registry = LeaseRegistry()
    registry.register(_lease("a"))
    registry.register(_lease("b"))

    registry.remove("a")
    assert [lease.session_id for lease in registry.snapshot()] == ["b"]
