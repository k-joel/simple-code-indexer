"""GPU detection for choosing the llama.cpp container image.

llama.cpp publishes one image per compute backend: `server` (CPU), `server-cuda`,
`server-rocm` (AMD) and `server-intel` (Intel SYCL). Detection runs on the host
that runs Docker: `nvidia-smi`, the Windows video-controller list, or the Linux
DRM vendor ids. `--gpu` overrides everything.

The `Runner` import is type-only so `provision` can import this module (the
reverse direction) without a cycle.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simple_code_indexer.setup_wizard.provision import Runner

CPU_IMAGE = "ghcr.io/ggml-org/llama.cpp:server"
IMAGES: dict[str, str] = {
    "nvidia": "ghcr.io/ggml-org/llama.cpp:server-cuda",
    "amd": "ghcr.io/ggml-org/llama.cpp:server-rocm",
    "intel": "ghcr.io/ggml-org/llama.cpp:server-intel",
    "cpu": CPU_IMAGE,
}

_VENDOR_IDS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}
_VENDOR_KEYWORDS = (
    ("nvidia", "nvidia"),
    ("geforce", "nvidia"),
    ("quadro", "nvidia"),
    ("rtx", "nvidia"),
    ("advanced micro devices", "amd"),
    ("amd", "amd"),
    ("radeon", "amd"),
    ("intel", "intel"),
    ("iris", "intel"),
    ("arc", "intel"),
)


@dataclass(frozen=True, slots=True)
class GpuInfo:
    vendor: str
    name: str

    @property
    def image(self) -> str:
        return IMAGES[self.vendor]


def detect_gpu(
    runner: Runner,
    *,
    platform: str = sys.platform,
    override: str | None = None,
    sysfs_root: Path = Path("/sys/class/drm"),
) -> GpuInfo:
    """Best-effort vendor detection; never raises for a missing GPU."""
    if override and override != "auto":
        vendor = override.lower()
        if vendor not in IMAGES:
            raise ValueError(f"unknown GPU backend {override!r}")
        return GpuInfo(vendor, "manual override")
    nvidia = _nvidia_name(runner)
    if nvidia is not None:
        return GpuInfo("nvidia", nvidia)
    names = _platform_names(runner, platform, sysfs_root)
    return GpuInfo(_vendor_from_names(names), ", ".join(names) or "no GPU detected")


def nvidia_runtime_ready(runner: Runner) -> bool:
    """True when the Docker daemon already exposes an NVIDIA runtime."""
    if runner.which("docker") is None:
        return False
    result = runner.run(["docker", "info", "--format", "{{json .Runtimes}}"])
    if result.returncode != 0:
        result = runner.run(["docker", "info"])
    return result.returncode == 0 and "nvidia" in result.stdout.lower()


def init_command(
    runner: Runner, script: Path, *, platform: str = sys.platform
) -> list[str] | None:
    """The gpu_init.sh invocation, or None when its runner is unavailable."""
    if platform == "win32":
        if runner.which("wsl") is None:
            return None
        return ["wsl", "-e", "bash", str(script)]
    if runner.which("bash") is None:
        return None
    return ["bash", str(script)]


def manual_command(script: Path, *, platform: str = sys.platform) -> str:
    if platform == "win32":
        return f'wsl -e bash "{script}"'
    return f'bash "{script}"'


def _nvidia_name(runner: Runner) -> str | None:
    if runner.which("nvidia-smi") is None:
        return None
    result = runner.run(["nvidia-smi", "-L"])
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[0] if lines else "NVIDIA GPU"


def _platform_names(runner: Runner, platform: str, sysfs_root: Path) -> list[str]:
    if platform == "win32":
        result = runner.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "Get-CimInstance Win32_VideoController | "
                    "Select-Object -ExpandProperty Name"
                ),
            ]
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    names = _sysfs_vendors(sysfs_root)
    if names:
        return names
    if runner.which("lspci") is not None:
        result = runner.run(["lspci"])
        if result.returncode == 0:
            return [
                line
                for line in result.stdout.splitlines()
                if any(needle in line.lower() for needle in ("vga", "3d controller"))
            ]
    return []


def _sysfs_vendors(root: Path) -> list[str]:
    vendors: list[str] = []
    try:
        paths = sorted(root.glob("card*/device/vendor"))
    except OSError:
        return []
    for path in paths:
        try:
            vendor_id = path.read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        vendor = _VENDOR_IDS.get(vendor_id)
        if vendor is not None:
            vendors.append(vendor)
    return vendors


def _vendor_from_names(names: list[str]) -> str:
    joined = " | ".join(names).lower()
    for keyword, vendor in _VENDOR_KEYWORDS:
        if keyword in joined:
            return vendor
    return "cpu"
