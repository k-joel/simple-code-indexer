from pathlib import Path

import pytest

from simple_code_indexer.setup_wizard import gpu
from simple_code_indexer.setup_wizard.provision import CommandResult, Runner


class FakeRunner(Runner):
    def __init__(
        self,
        *,
        which_map: dict[str, str] | None = None,
        results: dict[tuple[str, ...], CommandResult] | None = None,
        default: CommandResult | None = None,
        console_rc: int = 0,
    ) -> None:
        self.which_map = which_map or {}
        self.results = results or {}
        self.default = default or CommandResult(1)
        self.console_rc = console_rc
        self.calls: list[list[str]] = []
        self.console_calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        return self.which_map.get(name)

    def run(self, argv: list[str], *, timeout: float = 15.0, cwd=None) -> CommandResult:
        self.calls.append(list(argv))
        for prefix, result in self.results.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return result
        return self.default

    def run_console(self, argv: list[str], *, timeout: float = 900.0) -> int:
        self.console_calls.append(list(argv))
        return self.console_rc


def _sysfs(tmp_path: Path, vendor_ids: list[str]) -> Path:
    root = tmp_path / "drm"
    for index, vendor_id in enumerate(vendor_ids):
        device = root / f"card{index}" / "device"
        device.mkdir(parents=True)
        (device / "vendor").write_text(vendor_id + "\n", encoding="utf-8")
    return root


def test_nvidia_smi_selects_the_cuda_image() -> None:
    runner = FakeRunner(
        which_map={"nvidia-smi": "/usr/bin/nvidia-smi"},
        results={
            ("nvidia-smi", "-L"): CommandResult(
                0, "GPU 0: NVIDIA GeForce RTX 4090 (UUID: GPU-1)\n"
            )
        },
    )

    info = gpu.detect_gpu(runner, platform="linux")

    assert info.vendor == "nvidia"
    assert "RTX 4090" in info.name
    assert info.image == "ghcr.io/ggml-org/llama.cpp:server-cuda"


def test_windows_video_controller_detection_covers_amd_and_intel(
    tmp_path: Path,
) -> None:
    amd = FakeRunner(
        results={("powershell",): CommandResult(0, "AMD Radeon RX 7900\n")}
    )
    intel = FakeRunner(
        results={("powershell",): CommandResult(0, "Intel(R) Arc(TM) A770\n")}
    )

    assert gpu.detect_gpu(amd, platform="win32").vendor == "amd"
    assert gpu.detect_gpu(amd, platform="win32").image.endswith("server-rocm")
    assert gpu.detect_gpu(intel, platform="win32").vendor == "intel"
    assert gpu.detect_gpu(intel, platform="win32").image.endswith("server-intel")


def test_linux_sysfs_vendor_ids(tmp_path: Path) -> None:
    nvidia_root = _sysfs(tmp_path / "nvidia", ["0x10de"])
    amd_root = _sysfs(tmp_path / "amd", ["0x1002"])
    intel_root = _sysfs(tmp_path / "intel", ["0x8086"])

    assert (
        gpu.detect_gpu(FakeRunner(), platform="linux", sysfs_root=nvidia_root).vendor
        == "nvidia"
    )
    assert (
        gpu.detect_gpu(FakeRunner(), platform="linux", sysfs_root=amd_root).vendor
        == "amd"
    )
    assert (
        gpu.detect_gpu(FakeRunner(), platform="linux", sysfs_root=intel_root).vendor
        == "intel"
    )


def test_no_gpu_falls_back_to_cpu(tmp_path: Path) -> None:
    info = gpu.detect_gpu(
        FakeRunner(), platform="linux", sysfs_root=_sysfs(tmp_path, [])
    )

    assert info.vendor == "cpu"
    assert info.image == "ghcr.io/ggml-org/llama.cpp:server"


def test_override_wins_without_probing() -> None:
    runner = FakeRunner(which_map={"nvidia-smi": "/usr/bin/nvidia-smi"})

    info = gpu.detect_gpu(runner, platform="linux", override="cpu")

    assert info.vendor == "cpu"
    assert runner.calls == []


def test_unknown_override_raises() -> None:
    with pytest.raises(ValueError, match="unknown GPU backend"):
        gpu.detect_gpu(FakeRunner(), override="matrox")


def test_nvidia_runtime_ready_reads_docker_runtimes() -> None:
    ready = FakeRunner(
        which_map={"docker": "/usr/bin/docker"},
        results={
            ("docker", "info", "--format"): CommandResult(
                0, '{"nvidia": {}, "runc": {}}'
            )
        },
    )
    missing = FakeRunner(
        which_map={"docker": "/usr/bin/docker"},
        results={("docker", "info"): CommandResult(0, "Runtimes: runc")},
    )

    assert gpu.nvidia_runtime_ready(ready) is True
    assert gpu.nvidia_runtime_ready(missing) is False
    assert gpu.nvidia_runtime_ready(FakeRunner()) is False


def test_init_command_targets_wsl_or_bash(tmp_path: Path) -> None:
    script = tmp_path / "gpu_init.sh"
    windows = FakeRunner(which_map={"wsl": "C:/Windows/System32/wsl.exe"})
    linux = FakeRunner(which_map={"bash": "/usr/bin/bash"})

    assert gpu.init_command(windows, script, platform="win32") == [
        "wsl",
        "-e",
        "bash",
        str(script),
    ]
    assert gpu.init_command(linux, script, platform="linux") == ["bash", str(script)]
    assert gpu.init_command(FakeRunner(), script, platform="win32") is None
    assert "wsl -e bash" in gpu.manual_command(script, platform="win32")
    assert "bash" in gpu.manual_command(script, platform="linux")
