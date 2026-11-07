"""Prerequisite detection and installation helpers."""

from __future__ import annotations

import sys
from collections.abc import Callable

from simple_code_indexer.setup_wizard.provision import Runner

DOCKER_DOWNLOAD_URL = "https://www.docker.com/products/docker-desktop/"


def docker_install_hint(platform: str = sys.platform) -> str:
    if platform == "win32":
        return f"Install Docker Desktop: {DOCKER_DOWNLOAD_URL}"
    if platform == "darwin":
        return f"Install Docker Desktop: {DOCKER_DOWNLOAD_URL}"
    return "Install Docker Engine: https://docs.docker.com/engine/install/"


def docker_install_command(
    platform: str = sys.platform, *, runner: Runner
) -> list[str] | None:
    """Best available non-interactive install command, or None."""
    if platform == "win32":
        if runner.which("winget") is None:
            return None
        return [
            "winget",
            "install",
            "--id",
            "Docker.DockerDesktop",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
    if platform == "darwin":
        if runner.which("brew") is None:
            return None
        return ["brew", "install", "--cask", "docker"]
    return ["sh", "-c", "curl -fsSL https://get.docker.com | sh"]


def install_docker(
    runner: Runner,
    *,
    platform: str = sys.platform,
    output: Callable[[str], None] = print,
) -> bool:
    """Run the platform installer (interactive stdio: sudo/UAC prompts)."""
    command = docker_install_command(platform, runner=runner)
    if command is None:
        output(docker_install_hint(platform))
        return False
    output(f"Installing Docker: {' '.join(command)}")
    return runner.run_console(command) == 0


def gpu_runtime_hint(platform: str = sys.platform) -> str:
    if platform == "win32":
        return (
            "For NVIDIA GPU containers, run `wsl --update` and then the generated "
            "gpu_init.sh inside the WSL2 distro that runs dockerd."
        )
    return (
        "For NVIDIA GPU containers, run the generated gpu_init.sh on the Docker "
        "host to install the NVIDIA container toolkit."
    )
