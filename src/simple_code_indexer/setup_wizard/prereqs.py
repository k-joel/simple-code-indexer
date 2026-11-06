"""Platform hints for prerequisites the wizard cannot install itself."""

from __future__ import annotations

import sys


def docker_install_hint() -> str:
    if sys.platform == "win32":
        return (
            "Install Docker Desktop: "
            "https://docs.docker.com/desktop/install/windows-install/"
        )
    if sys.platform == "darwin":
        return (
            "Install Docker Desktop: "
            "https://docs.docker.com/desktop/install/mac-install/"
        )
    return "Install Docker Engine: https://docs.docker.com/engine/install/"


def gpu_runtime_hint() -> str:
    if sys.platform == "win32":
        return (
            "For NVIDIA GPU containers, run `wsl --update` and then the generated "
            "gpu_init.sh inside the WSL2 distro that runs dockerd."
        )
    return (
        "For NVIDIA GPU containers, run the generated gpu_init.sh on the Docker "
        "host to install the NVIDIA container toolkit."
    )
