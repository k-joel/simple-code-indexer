from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from simple_code_indexer import services
from simple_code_indexer.config import IGNORE_DIRS, ManagedService, Settings
from simple_code_indexer.registry import get_registry


class Result:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Docker:
    """Fake `docker` CLI: records calls and simulates container state."""

    def __init__(
        self,
        statuses: dict[str, str] | None = None,
        *,
        missing: bool = False,
        info: bool = False,
    ) -> None:
        self.calls: list[list[str]] = []
        self.statuses = statuses or {}
        self.missing = missing
        self.info = info

    def __call__(self, argv: list[str], **kwargs: object) -> Result:
        self.calls.append(list(argv))
        args = argv[1:]
        if args[0] == "info":
            return Result(0 if self.info else 1)
        if args[0] == "inspect":
            if self.missing:
                return Result(1, stderr="no such object")
            name = args[-1]
            return Result(0, stdout=self.statuses.get(name, "running") + "\n")
        if args[0] in {"start", "unpause"}:
            self.missing = False
            self.statuses[args[1]] = "running"
        if args[0] == "compose":
            self.missing = False
            self.statuses["simple-ci-embed"] = "running"
            self.statuses["simple-ci-qdrant"] = "running"
        return Result(0)

    def commands(self) -> list[tuple[str, ...]]:
        return [tuple(call[1:]) for call in self.calls]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    services.LAST_STATE.clear()
    yield
    services.LAST_STATE.clear()


@pytest.fixture(autouse=True)
def _fast_time(monkeypatch) -> None:
    monkeypatch.setattr(services, "_clock", Clock())
    monkeypatch.setattr(services, "_sleep", lambda _seconds: None)


def _settings(
    tmp_path: Path,
    *,
    embedding: ManagedService | None = None,
    qdrant: ManagedService | None = None,
    api_key: str | None = None,
    timeout: float = 45.0,
) -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=tmp_path,
        index_db_path=tmp_path / ".simple-ci" / "index.db",
        qdrant_url="http://127.0.0.1:6333",
        qdrant_collection="code_index_test",
        embed_base_url="http://127.0.0.1:8080",
        embed_model="test-model",
        embed_dim=1024,
        embed_timeout_s=15.0,
        sweep_seconds=45.0,
        debounce_ms=400,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        embed_api_key=api_key,
        embedding_service=embedding,
        qdrant_service=qdrant,
    )


def _install_docker(monkeypatch, docker: Docker) -> None:
    monkeypatch.setattr(services, "_which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(services, "_run", docker)


def test_unmanaged_services_are_reported(tmp_path: Path, monkeypatch) -> None:
    _install_docker(monkeypatch, Docker(info=True))
    services.ensure_managed_services(_settings(tmp_path))

    assert services.LAST_STATE == {
        "embedding": "not_managed",
        "qdrant": "not_managed",
    }


def test_running_container_is_not_started(tmp_path: Path, monkeypatch) -> None:
    docker = Docker({"simple-ci-embed": "running"}, info=True)
    _install_docker(monkeypatch, docker)
    monkeypatch.setattr(services, "_http_post", lambda *args: True)

    services.ensure_managed_services(
        _settings(tmp_path, embedding=ManagedService("simple-ci-embed"))
    )

    assert services.LAST_STATE["embedding"] == "running"
    assert ("start", "simple-ci-embed") not in docker.commands()


def test_stopped_container_is_started(tmp_path: Path, monkeypatch) -> None:
    docker = Docker({"simple-ci-embed": "exited"}, info=True)
    _install_docker(monkeypatch, docker)
    monkeypatch.setattr(services, "_http_post", lambda *args: True)

    services.ensure_managed_services(
        _settings(tmp_path, embedding=ManagedService("simple-ci-embed"))
    )

    assert services.LAST_STATE["embedding"] == "started"
    assert ("start", "simple-ci-embed") in docker.commands()


def test_paused_container_is_unpaused(tmp_path: Path, monkeypatch) -> None:
    docker = Docker({"simple-ci-qdrant": "paused"}, info=True)
    _install_docker(monkeypatch, docker)
    monkeypatch.setattr(services, "_http_get", lambda *args: True)

    services.ensure_managed_services(
        _settings(tmp_path, qdrant=ManagedService("simple-ci-qdrant"))
    )

    assert ("unpause", "simple-ci-qdrant") in docker.commands()
    assert services.LAST_STATE["qdrant"] == "started"


def test_missing_container_is_created_with_compose(tmp_path: Path, monkeypatch) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    docker = Docker(missing=True, info=True)
    _install_docker(monkeypatch, docker)
    monkeypatch.setattr(services, "_http_post", lambda *args: True)

    services.ensure_managed_services(
        _settings(
            tmp_path,
            embedding=ManagedService(
                "simple-ci-embed",
                compose_file=compose,
                compose_service="embed",
            ),
        )
    )

    assert ("compose", "-f", str(compose), "up", "-d", "embed") in docker.commands()
    assert services.LAST_STATE["embedding"] == "started"


def test_missing_container_without_compose_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    _install_docker(monkeypatch, Docker(missing=True, info=True))

    services.ensure_managed_services(
        _settings(tmp_path, embedding=ManagedService("gone-container"))
    )

    assert services.LAST_STATE["embedding"] == "unavailable"


def test_missing_docker_is_fail_soft(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(services, "_which", lambda _name: None)
    monkeypatch.setattr(services, "_run", Docker(info=True))

    services.ensure_managed_services(
        _settings(tmp_path, qdrant=ManagedService("simple-ci-qdrant"))
    )

    assert services.LAST_STATE["qdrant"] == "unavailable"


def test_daemon_start_is_attempted(tmp_path: Path, monkeypatch) -> None:
    attempts: list[bool] = []
    monkeypatch.setattr(services, "_which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(services, "_run", Docker(info=False))
    monkeypatch.setattr(services, "_start_docker_daemon", lambda: attempts.append(True))

    services.ensure_managed_services(
        _settings(tmp_path, qdrant=ManagedService("simple-ci-qdrant"))
    )

    assert attempts == [True]
    assert services.LAST_STATE["qdrant"] == "unavailable"


def test_embedding_probe_sends_the_bearer_header(tmp_path: Path, monkeypatch) -> None:
    captured: list[dict[str, str]] = []

    def _post(url: str, payload: dict, headers: dict[str, str], timeout: float) -> bool:
        captured.append(headers)
        return True

    _install_docker(monkeypatch, Docker({"simple-ci-embed": "running"}, info=True))
    monkeypatch.setattr(services, "_http_post", _post)

    services.ensure_managed_services(
        _settings(
            tmp_path,
            embedding=ManagedService("simple-ci-embed"),
            api_key="secret",
        )
    )

    assert captured == [{"Authorization": "Bearer secret"}]


def test_readiness_timeout_marks_unavailable(tmp_path: Path, monkeypatch) -> None:
    _install_docker(monkeypatch, Docker({"simple-ci-embed": "running"}, info=True))
    monkeypatch.setattr(services, "_http_post", lambda *args: False)

    services.ensure_managed_services(
        _settings(
            tmp_path,
            embedding=ManagedService("simple-ci-embed", startup_timeout_s=2.0),
        )
    )

    assert services.LAST_STATE["embedding"] == "unavailable"


def test_qdrant_probe_falls_back_to_collections(tmp_path: Path, monkeypatch) -> None:
    urls: list[str] = []

    def _get(url: str, timeout: float) -> bool:
        urls.append(url)
        return url.endswith("/collections")

    _install_docker(monkeypatch, Docker({"simple-ci-qdrant": "running"}, info=True))
    monkeypatch.setattr(services, "_http_get", _get)

    services.ensure_managed_services(
        _settings(tmp_path, qdrant=ManagedService("simple-ci-qdrant"))
    )

    assert urls[0].endswith("/healthz")
    assert urls[-1].endswith("/collections")
    assert services.LAST_STATE["qdrant"] == "running"
