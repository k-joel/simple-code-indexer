"""Docker discovery, compose generation, model download, and port selection."""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

import yaml

from simple_code_indexer.setup_wizard import gpu
from simple_code_indexer.setup_wizard.catalog import EmbeddingModel

logger = logging.getLogger(__name__)

HOME_DIRNAME = ".simple-ci"
GLOBAL_DOCKER_DIRNAME = "docker"
GLOBAL_MODEL_DIRNAME = "model"
COMPOSE_FILENAME = "docker-compose.yml"
COMPOSE_TEMPLATE = "docker-compose.yml"
GPU_SCRIPT_FILENAME = "gpu_init.sh"
# Compose derives the container name (<project>-<service>-<n>) unless the file
# pins `container_name`. The packaged file sets the project instead, so the
# generated containers are `simple-ci-embed-1` / `simple-ci-qdrant-1`; resolve
# the real name with `compose_container_name` rather than guessing it.
COMPOSE_PROJECT = "simple-ci"
EMBED_SERVICE = "embed"
QDRANT_SERVICE = "qdrant"
EMBED_CONTAINER = f"{COMPOSE_PROJECT}-{EMBED_SERVICE}-1"
QDRANT_CONTAINER = f"{COMPOSE_PROJECT}-{QDRANT_SERVICE}-1"

EMBED_PORTS = (8080, 8000, 11434, 3000, 1234)

_DOCKER_TIMEOUT_S = 30.0
_COMPOSE_TIMEOUT_S = 900.0
_GPU_SCRIPT_TIMEOUT_S = 900.0
_CHUNK_BYTES = 4 * 1024 * 1024
_REPORT_BYTES = 64 * 1024 * 1024

_GPU_LAYERS_LINE = "      - LLAMA_ARG_N_GPU_LAYERS=auto\n"
_GPU_BLOCKS: dict[str, str] = {
    "nvidia": (
        "    deploy:\n"
        "      resources:\n"
        "        reservations:\n"
        "          devices:\n"
        "            - driver: nvidia\n"
        "              count: all\n"
        "              capabilities: [gpu]\n"
    ),
    "amd": (
        "    devices:\n"
        "      - /dev/kfd\n"
        "      - /dev/dri\n"
        "    group_add:\n"
        "      - video\n"
        "      - render\n"
        "    security_opt:\n"
        "      - seccomp:unconfined\n"
    ),
    "intel": (
        "    devices:\n"
        "      - /dev/dri\n"
        "    group_add:\n"
        "      - video\n"
        "      - render\n"
    ),
    "cpu": "",
}


def global_dir(home: Path) -> Path:
    return home / HOME_DIRNAME


def compose_path(home: Path) -> Path:
    return global_dir(home) / GLOBAL_DOCKER_DIRNAME / COMPOSE_FILENAME


def model_dir(home: Path) -> Path:
    return global_dir(home) / GLOBAL_MODEL_DIRNAME


def template_text(name: str) -> str:
    resource = resources.files("simple_code_indexer.setup_wizard").joinpath(
        "templates", name
    )
    return resource.read_text(encoding="utf-8")


def install_gpu_script(home: Path) -> Path:
    """Copy the packaged NVIDIA container-toolkit script next to the compose file."""
    target = compose_path(home).parent / GPU_SCRIPT_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        template_text(GPU_SCRIPT_FILENAME), encoding="utf-8", newline="\n"
    )
    if os.name == "posix":
        target.chmod(0o755)
    return target


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


@dataclass(frozen=True, slots=True)
class EmbeddingContainer:
    name: str
    image: str
    status: str
    url: str | None

    @property
    def running(self) -> bool:
        return self.status.lower().startswith("up")


class Runner:
    """subprocess wrapper; tests inject a fake with the same methods."""

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

    def run_console(
        self, argv: list[str], *, timeout: float = _GPU_SCRIPT_TIMEOUT_S
    ) -> int:
        """Run with inherited stdio so sudo/WSL prompts stay interactive."""
        try:
            return subprocess.run(argv, timeout=timeout, check=False).returncode
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("console command %s could not run: %s", argv, exc)
            return 127


def docker_available(runner: Runner) -> bool:
    if runner.which("docker") is None:
        return False
    return runner.run(["docker", "info"]).returncode == 0


def start_docker_daemon(runner: Runner, *, platform: str = sys.platform) -> bool:
    """Launch Docker Desktop / the Docker service; False when no launcher exists."""
    command: list[str] = []
    if platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidate = program_files / "Docker" / "Docker" / "Docker Desktop.exe"
        if candidate.is_file():
            command = [str(candidate)]
    elif platform == "darwin":
        command = ["open", "-a", "Docker"]
    else:
        command = ["systemctl", "--user", "start", "docker"]
    if not command:
        return False
    try:
        subprocess.Popen(command)
    except OSError:
        return False
    return True


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
    return _parse_container_lines(result.stdout)


def container_status(runner: Runner, name: str) -> str | None:
    for attempt in range(2):
        result = runner.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", name],
            timeout=_DOCKER_TIMEOUT_S,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
        if attempt == 0:
            time.sleep(0.5)
    return None


def compose_ps(runner: Runner, compose_file: Path) -> list[Container]:
    """Containers belonging to the project in `compose_file`."""
    if not compose_file.is_file():
        return []
    result = runner.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "ps",
            "-a",
            "--format",
            "{{.Name}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
        ],
        timeout=_DOCKER_TIMEOUT_S,
    )
    if result.returncode != 0:
        return []
    return _parse_container_lines(result.stdout)


def _parse_container_lines(text: str) -> list[Container]:
    containers: list[Container] = []
    for line in text.splitlines():
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


def compose_project(
    compose_file: Path, runner: Runner | None = None, *, fallback: str = COMPOSE_PROJECT
) -> str:
    """The project name compose derives container names from.

    A top-level `name:` wins over the directory name; `COMPOSE_PROJECT_NAME`
    overrides both. Ask the daemon when we can, so a hand-edited file still
    resolves to the containers it actually created.
    """
    if runner is not None and compose_file.is_file():
        result = runner.run(
            [
                "docker",
                "compose",
                "-f",
                str(compose_file),
                "config",
                "--format",
                "json",
            ],
            timeout=_DOCKER_TIMEOUT_S,
        )
        if result.returncode == 0:
            try:
                document = json.loads(result.stdout)
            except json.JSONDecodeError:
                document = None
            if isinstance(document, dict) and isinstance(document.get("name"), str):
                return document["name"]
    if compose_file.is_file():
        try:
            loaded = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            loaded = None
        if isinstance(loaded, dict) and isinstance(loaded.get("name"), str):
            return loaded["name"]
    return fallback


def compose_container_name(
    runner: Runner, compose_file: Path, service: str, *, fallback: str
) -> str:
    """The container compose created for `service`, resolved from the daemon.

    The packaged file sets a top-level `name:` instead of `container_name`, so
    compose composes the name itself (`simple-ci-embed-1`). Ask compose rather
    than assume, and fall back to the derived name when it has never run.
    """
    project = compose_project(compose_file, runner)
    expected = f"{project}-{service}-1"
    for container in compose_ps(runner, compose_file):
        if container.name == expected:
            return container.name
    for container in list_containers(runner):
        if container.name.startswith(f"{project}-{service}-"):
            return container.name
    return fallback


def container_name_for(
    runner: Runner, name: str, *, compose_file: Path | None, service: str
) -> str:
    """Resolve `name` to a container that actually exists; `name` when unknown."""
    if container_status(runner, name) is not None:
        return name
    if compose_file is not None:
        resolved = compose_container_name(runner, compose_file, service, fallback=name)
        if container_status(runner, resolved) is not None:
            return resolved
    return name


def container_env(runner: Runner, name: str) -> dict[str, str]:
    """Parse `docker inspect` Config.Env into a mapping (empty on failure)."""
    result = runner.run(
        ["docker", "inspect", "-f", "{{json .Config.Env}}", name],
        timeout=_DOCKER_TIMEOUT_S,
    )
    if result.returncode != 0:
        return {}
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    if not isinstance(values, list):
        return {}
    env: dict[str, str] = {}
    for item in values:
        if isinstance(item, str) and "=" in item:
            key, _, value = item.partition("=")
            env[key] = value
    return env


def start_container(runner: Runner, name: str) -> bool:
    status = container_status(runner, name)
    if status == "running":
        return True
    if status is None:
        return False
    command = ["docker", "unpause" if status == "paused" else "start", name]
    if runner.run(command, timeout=60.0).returncode == 0:
        return True
    # A slow Docker Desktop can exceed the command timeout while the container
    # still starts; trust the state over the exit code.
    return container_status(runner, name) == "running"


def stop_container(runner: Runner, name: str, *, timeout: float = 60.0) -> bool:
    """`docker stop` the container; True when it is no longer running."""
    if container_status(runner, name) is None:
        return False
    if runner.run(["docker", "stop", name], timeout=timeout).returncode == 0:
        return True
    # Same slow-daemon caveat as start_container: trust the observed state.
    return container_status(runner, name) != "running"


def port_holders(runner: Runner, port: int) -> list[Container]:
    """Running containers that publish `port` on the host."""
    holders: list[Container] = []
    needle = f":{port}->"
    for container in list_containers(runner):
        if container.running and needle in container.ports:
            holders.append(container)
    return holders


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


def find_qdrant_containers(runner: Runner) -> list[Container]:
    return [
        container
        for container in list_containers(runner)
        if "qdrant" in f"{container.name} {container.image}".lower()
    ]


def downloaded_models(home: Path) -> list[Path]:
    directory = model_dir(home)
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.glob("*.gguf")
        if path.is_file() and path.stat().st_size
    )


def existing_service(
    container: str,
    *,
    compose_file: Path | None = None,
    compose_service: str | None = None,
    startup_timeout_s: float = 120.0,
) -> dict[str, Any]:
    """The `service` block for a container the wizard did not create itself."""
    service: dict[str, Any] = {
        "container": container,
        "startup_timeout_s": startup_timeout_s,
    }
    if compose_file is not None and compose_file.is_file():
        service["compose_file"] = str(compose_file)
        if compose_service:
            service["compose_service"] = compose_service
    return service


def compose_services(compose_file: Path) -> dict[str, Any]:
    if not compose_file.is_file():
        return {}
    loaded = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    services = loaded.get("services") if isinstance(loaded, dict) else None
    return services if isinstance(services, dict) else {}


def compose_service_for_container(compose_file: Path, container: str) -> str | None:
    for name, definition in compose_services(compose_file).items():
        if (
            isinstance(definition, dict)
            and definition.get("container_name") == container
        ):
            return name
    # Without `container_name` compose names containers <project>-<service>-<n>,
    # so a configured `simple-ci-embed-1` belongs to the `embed` service.
    prefix = f"{compose_project(compose_file)}-"
    if container.startswith(prefix) and container.endswith("-1"):
        service = container[len(prefix) : -len("-1")]
        if service in compose_services(compose_file):
            return service
    return None


def compose_up(runner: Runner, compose_file: Path, service: str) -> tuple[bool, str]:
    """Run `compose up -d`; (ok, the daemon's error text when it failed)."""
    result = runner.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d", service],
        timeout=_COMPOSE_TIMEOUT_S,
    )
    if result.returncode == 0:
        return True, ""
    detail = (result.stderr or result.stdout or "").strip()
    return False, detail.splitlines()[-1] if detail else ""


def compose_down(runner: Runner, compose_file: Path) -> tuple[bool, str]:
    """Run `compose down --remove-orphans`; (ok, the daemon's error text)."""
    result = runner.run(
        ["docker", "compose", "-f", str(compose_file), "down", "--remove-orphans"],
        timeout=_COMPOSE_TIMEOUT_S,
    )
    if result.returncode == 0:
        return True, ""
    detail = (result.stderr or result.stdout or "").strip()
    return False, detail.splitlines()[-1] if detail else ""


def write_compose(path: Path, services: dict[str, Any]) -> None:
    """Merge our services into an existing compose file, preserving the rest."""
    document: dict[str, Any] = {}
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is not None:
            if not isinstance(loaded, dict):
                raise ValueError(f"{path} does not contain a compose mapping")
            document = loaded
    # Pin the project so container names are predictable across machines. Set
    # unconditionally: a file written before this key existed would otherwise
    # derive names from the directory (`docker-embed-1`).
    document["name"] = COMPOSE_PROJECT
    existing = document.setdefault("services", {})
    if not isinstance(existing, dict):
        raise TypeError(f"{path}: 'services' must be a mapping")
    existing.update(services)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8", newline="\n"
    )


def render_embed_services(
    model: EmbeddingModel,
    port: int,
    filename: str,
    *,
    image: str,
    gpu_vendor: str,
) -> dict[str, Any]:
    """Render the packaged compose template for one embedding model."""
    rendered = Template(template_text(COMPOSE_TEMPLATE)).substitute(
        IMAGE=image,
        PROJECT=COMPOSE_PROJECT,
        MODEL_FILE=filename,
        API_MODEL=model.api_model,
        CTX_SIZE=str(model.ctx_size),
        POOLING=model.pooling,
        PORT=str(port),
        GPU_LAYERS=_GPU_LAYERS_LINE if gpu_vendor != "cpu" else "",
        GPU_BLOCK=_GPU_BLOCKS.get(gpu_vendor, ""),
    )
    document = yaml.safe_load(rendered)
    if not isinstance(document, dict) or not isinstance(document.get("services"), dict):
        raise TypeError("docker-compose template did not render a services mapping")
    return document["services"]


def embed_service(
    model: EmbeddingModel,
    port: int,
    filename: str,
    *,
    image: str | None = None,
    gpu_vendor: str = "cpu",
) -> dict[str, Any]:
    services = render_embed_services(
        model,
        port,
        filename,
        image=image or gpu.CPU_IMAGE,
        gpu_vendor=gpu_vendor,
    )
    return services["embed"]


def qdrant_service(port: int) -> dict[str, Any]:
    return {
        "image": "qdrant/qdrant:latest",
        "ports": [f"127.0.0.1:{port}:6333"],
        "volumes": ["../qdrant_storage:/qdrant/storage"],
        "restart": "unless-stopped",
    }


def available_port(host: str, preferred: int, attempts: int = 20) -> int:
    """First bindable port at or after `preferred` (preferred when none is free).

    `SO_REUSEADDR` must NOT be set: on Windows it lets `bind()` succeed on a
    port a container already publishes, so the wizard picked 8080, compose
    failed to start, and the run aborted after the container was created.
    """
    for port in range(preferred, preferred + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    return preferred


def port_is_free(runner: Runner, host: str, port: int) -> bool:
    """True when nothing — container or host process — publishes `port`."""
    if port_holders(runner, port):
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def available_port_for_docker(
    runner: Runner, host: str, preferred: int, attempts: int = 20
) -> int:
    """`available_port`, but a port a running container publishes also counts as taken.

    Docker Desktop publishes through a host proxy, so `bind()` alone can
    succeed while compose later fails with "address already in use".
    """
    for port in range(preferred, preferred + attempts):
        if port_is_free(runner, host, port):
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
    predicate: Callable[[], bool],
    *,
    timeout: float,
    interval: float = 1.0,
    output: Callable[[str], None] | None = None,
    progress_every: float = 15.0,
) -> bool:
    """Poll `predicate` until it is true or `timeout` elapses.

    `output` gets a heartbeat line every `progress_every` seconds so a slow
    model load never looks like a hung setup.
    """
    start = time.monotonic()
    deadline = start + timeout
    next_report = start + progress_every
    while time.monotonic() < deadline:
        if predicate():
            return True
        now = time.monotonic()
        if output is not None and now >= next_report:
            output(f"  still waiting ({now - start:.0f}s of {timeout:.0f}s) ...")
            next_report = now + progress_every
        time.sleep(interval)
    return False
