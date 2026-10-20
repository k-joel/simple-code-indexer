"""Docker discovery, compose generation, model download, and port selection."""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from simple_code_indexer.setup_wizard.catalog import EmbeddingModel

logger = logging.getLogger(__name__)

HOME_DIRNAME = ".simple-ci"
COMPOSE_FILENAME = "docker-compose.yml"
EMBED_CONTAINER = "simple-ci-embed"
QDRANT_CONTAINER = "simple-ci-qdrant"

_DOCKER_TIMEOUT_S = 15.0
_COMPOSE_TIMEOUT_S = 300.0
_CHUNK_BYTES = 4 * 1024 * 1024
_REPORT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True, slots=True)
class Container:
    name: str
    image: str
    status: str
    ports: str

    @property
    def running(self) -> bool:
        return self.status.lower().startswith("up")


class Runner:
    """subprocess wrapper; tests inject a fake with the same two methods."""

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def run(
        self, argv: list[str], *, timeout: float = _DOCKER_TIMEOUT_S
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CommandResult(127, "", str(exc))
        return CommandResult(
            completed.returncode, completed.stdout or "", completed.stderr or ""
        )


def docker_available(runner: Runner) -> bool:
    if runner.which("docker") is None:
        return False
    return runner.run(["docker", "info"]).returncode == 0


def list_containers(runner: Runner) -> list[Container]:
    result = runner.run(
        [
            "docker",
            "ps",
            "-a",
            "--format",
            "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
        ]
    )
    if result.returncode != 0:
        return []
    containers: list[Container] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        containers.append(
            Container(
                name=parts[0],
                image=parts[1],
                status=parts[2],
                ports=parts[3] if len(parts) > 3 else "",
            )
        )
    return containers


def container_status(runner: Runner, name: str) -> str | None:
    result = runner.run(["docker", "inspect", "-f", "{{.State.Status}}", name])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def start_container(runner: Runner, name: str) -> bool:
    status = container_status(runner, name)
    if status == "running":
        return True
    if status == "paused":
        return runner.run(["docker", "unpause", name]).returncode == 0
    if status is None:
        return False
    return runner.run(["docker", "start", name]).returncode == 0


def container_url(
    runner: Runner,
    name: str,
    ports: tuple[int, ...] = (8080, 8000, 11434, 3000),
) -> str | None:
    """Derive a localhost URL from the container's published port."""
    for port in ports:
        result = runner.run(["docker", "port", name, f"{port}/tcp"])
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            _, _, host_port = line.strip().rpartition(":")
            if host_port.isdigit():
                return f"http://localhost:{host_port}"
    return None


def compose_up(runner: Runner, compose_file: Path, service: str) -> bool:
    result = runner.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d", service],
        timeout=_COMPOSE_TIMEOUT_S,
    )
    return result.returncode == 0


def write_compose(path: Path, services: dict[str, Any]) -> None:
    """Merge our services into an existing compose file, preserving the rest."""
    document: dict[str, Any] = {}
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is not None:
            if not isinstance(loaded, dict):
                raise ValueError(f"{path} does not contain a compose mapping")
            document = loaded
    existing = document.setdefault("services", {})
    if not isinstance(existing, dict):
        raise TypeError(f"{path}: 'services' must be a mapping")
    existing.update(services)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8", newline="\n"
    )


def embed_service(model: EmbeddingModel, port: int, filename: str) -> dict[str, Any]:
    return {
        "image": "ghcr.io/ggml-org/llama.cpp:server",
        "container_name": EMBED_CONTAINER,
        "ports": [f"127.0.0.1:{port}:8080"],
        "volumes": ["./models:/models:ro"],
        "command": [
            "-m",
            f"/models/{filename}",
            "--embedding",
            "--pooling",
            model.pooling,
            "-b",
            "2048",
            "-ub",
            "2048",
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
        ],
        "restart": "unless-stopped",
    }


def qdrant_service(port: int) -> dict[str, Any]:
    return {
        "image": "qdrant/qdrant:latest",
        "container_name": QDRANT_CONTAINER,
        "ports": [f"127.0.0.1:{port}:6333"],
        "volumes": ["./qdrant_storage:/qdrant/storage"],
        "restart": "unless-stopped",
    }


def available_port(host: str, preferred: int, attempts: int = 20) -> int:
    """First bindable port at or after `preferred` (preferred when none is free)."""
    for port in range(preferred, preferred + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    return preferred


def download_model(
    url: str,
    destination: Path,
    *,
    output: Callable[[str], None] = print,
    opener: Callable[..., Any] | None = None,
) -> None:
    """Stream a GGUF to `destination` (no-op when a non-empty file exists)."""
    if destination.is_file() and destination.stat().st_size > 0:
        output(f"Model already present: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "simple-code-indexer-setup"}
    token = os.environ.get("HF_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    open_url = opener or urllib.request.urlopen
    temporary = destination.with_name(destination.name + ".part")
    output(f"Downloading {url}")
    total = 0
    last_report = 0
    response = open_url(request, timeout=60)
    try:
        with temporary.open("wb") as handle:
            while True:
                block = response.read(_CHUNK_BYTES)
                if not block:
                    break
                handle.write(block)
                total += len(block)
                if total - last_report >= _REPORT_BYTES:
                    output(f"  {total / 1e9:.1f} GB downloaded")
                    last_report = total
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        response.close()
    os.replace(temporary, destination)
    output(f"Saved {destination} ({total / 1e6:.0f} MB)")


def wait_until(
    predicate: Callable[[], bool], *, timeout: float, interval: float = 1.0
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
