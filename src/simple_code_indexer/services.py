"""Managed Docker services: start containers, wait for readiness, never raise.

`get_status` reads `LAST_STATE`; the agreed policy is fail-soft — an unreachable
managed service leaves the server serving lexical search.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from simple_code_indexer.config import ManagedService, Settings

logger = logging.getLogger(__name__)

# "embedding"/"qdrant" -> not_managed | running | started | unavailable
LAST_STATE: dict[str, str] = {}

_DOCKER_TIMEOUT_S = 10.0
_DAEMON_WAIT_S = 30.0
_CONTAINER_WAIT_S = 30.0
_PROBE_TIMEOUT_S = 3.0
_POLL_S = 0.5

# Test seams: unit tests never shell out or touch the network.
_run = subprocess.run
_popen = subprocess.Popen
_which = shutil.which
_clock = time.monotonic
_sleep = time.sleep


def ensure_managed_services(settings: Settings) -> None:
    """Ensure configured containers are up and answering, then record the state."""
    services = [("embedding", settings.embedding_service)]
    if settings.vector_store == "qdrant":
        services.append(("qdrant", settings.qdrant_service))
    else:
        # FAISS needs no server; an old qdrant.service block must not start Docker.
        LAST_STATE["qdrant"] = "not_managed"
    for kind, service in services:
        if service is None:
            LAST_STATE[kind] = "not_managed"
            continue
        try:
            state = _ensure_container(service)
            if state is None:
                LAST_STATE[kind] = "unavailable"
                continue
            if _wait_ready(kind, settings, service.startup_timeout_s):
                LAST_STATE[kind] = state
            else:
                logger.error(
                    "managed %s service %s did not become ready",
                    kind,
                    service.container,
                )
                LAST_STATE[kind] = "unavailable"
        except Exception:
            logger.exception("managed %s service failed", kind)
            LAST_STATE[kind] = "unavailable"


def _ensure_container(service: ManagedService) -> str | None:
    """Return "running"/"started" when the container is up, None otherwise."""
    if not _docker_available():
        return None
    ok, status = _docker_output("inspect", "-f", "{{.State.Status}}", service.container)
    if not ok:
        logger.warning(
            "container %s not found; trying its compose service", service.container
        )
        if not _compose_up(service):
            return None
        return "started" if _wait_container(service.container) else None
    if status == "running":
        logger.info("managed container %s is already running", service.container)
        return "running"
    logger.info("starting managed container %s (was %s)", service.container, status)
    if status == "paused":
        started = _docker("unpause", service.container)
    else:
        started = _docker("start", service.container)
    if not started:
        return None
    if not _wait_container(service.container):
        logger.error("container %s did not reach running", service.container)
        return None
    return "started"


def _docker_available() -> bool:
    if _which("docker") is None:
        logger.warning("docker CLI not found; managed services cannot be started")
        return False
    if _docker("info"):
        return True
    logger.info("docker daemon is not answering; trying to start it")
    _start_docker_daemon()
    deadline = _clock() + _DAEMON_WAIT_S
    while _clock() < deadline:
        _sleep(1.0)
        if _docker("info"):
            return True
    logger.error("docker daemon did not become ready")
    return False


def _start_docker_daemon() -> None:
    command: list[str] = []
    if sys.platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidate = program_files / "Docker" / "Docker" / "Docker Desktop.exe"
        if candidate.is_file():
            command = [str(candidate)]
    elif sys.platform == "darwin":
        command = ["open", "-a", "Docker"]
    else:
        command = ["systemctl", "--user", "start", "docker"]
    if not command:
        return
    try:
        _popen(command)
    except OSError:
        logger.warning("could not launch Docker", exc_info=True)


def _docker(*args: str, timeout: float = _DOCKER_TIMEOUT_S) -> bool:
    ok, _ = _docker_output(*args, timeout=timeout)
    return ok


def _docker_output(*args: str, timeout: float = _DOCKER_TIMEOUT_S) -> tuple[bool, str]:
    try:
        result = _run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("docker %s could not run: %s", " ".join(args), exc)
        return False, ""
    if result.returncode != 0:
        logger.debug(
            "docker %s failed: %s",
            " ".join(args),
            (result.stderr or "").strip(),
        )
        return False, ""
    return True, (result.stdout or "").strip()


def _compose_up(service: ManagedService) -> bool:
    if service.compose_file is None or service.compose_service is None:
        logger.warning(
            "container %s is missing and no compose service is configured",
            service.container,
        )
        return False
    if not service.compose_file.is_file():
        logger.error("compose file %s does not exist", service.compose_file)
        return False
    logger.info(
        "creating %s with docker compose (%s)",
        service.container,
        service.compose_file,
    )
    return _docker(
        "compose",
        "-f",
        str(service.compose_file),
        "up",
        "-d",
        service.compose_service,
        timeout=180.0,
    )


def _wait_container(container: str, timeout: float = _CONTAINER_WAIT_S) -> bool:
    deadline = _clock() + timeout
    while _clock() < deadline:
        ok, status = _docker_output("inspect", "-f", "{{.State.Status}}", container)
        if ok and status == "running":
            return True
        _sleep(_POLL_S)
    return False


def _wait_ready(kind: str, settings: Settings, timeout_s: float) -> bool:
    deadline = _clock() + timeout_s
    while _clock() < deadline:
        if _probe(kind, settings):
            return True
        _sleep(_POLL_S)
    return False


def _probe(kind: str, settings: Settings) -> bool:
    if kind == "qdrant":
        base = settings.qdrant_url.rstrip("/")
        return _http_get(base + "/healthz", _PROBE_TIMEOUT_S) or _http_get(
            base + "/collections", _PROBE_TIMEOUT_S
        )
    headers = _embed_headers(settings)
    return _http_post(
        settings.embed_base_url.rstrip("/") + "/v1/embeddings",
        {"model": settings.embed_model, "input": ["ping"]},
        headers,
        _PROBE_TIMEOUT_S,
    )


def _embed_headers(settings: Settings) -> dict[str, str]:
    if settings.embed_api_key:
        return {"Authorization": f"Bearer {settings.embed_api_key}"}
    return {}


def _http_get(url: str, timeout: float) -> bool:
    try:
        response = httpx.get(url, timeout=httpx.Timeout(timeout, connect=1.0))
    except httpx.HTTPError:
        return False
    return response.status_code < 500


def _http_post(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
) -> bool:
    try:
        response = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=1.0),
        )
    except httpx.HTTPError:
        return False
    return response.status_code < 500
