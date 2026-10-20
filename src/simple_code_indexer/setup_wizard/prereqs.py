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
