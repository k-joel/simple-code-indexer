from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from simple_code_indexer import configfile, logging_setup, model_prompts
from simple_code_indexer.config import ipv4_loopback, load_settings
from simple_code_indexer.harnesses import load_harnesses
from simple_code_indexer.setup_wizard import (
    SetupAborted,
    Wizard,
    gpu,
    provision,
)
from simple_code_indexer.setup_wizard import install as install_mod
from simple_code_indexer.setup_wizard import run as wizard_run
from simple_code_indexer.setup_wizard.catalog import CATALOG
from simple_code_indexer.setup_wizard.probe import Http
from simple_code_indexer.setup_wizard.prompts import Prompter
from simple_code_indexer.setup_wizard.provision import CommandResult, Runner

DIM = 1024
EMBED_URL = "http://embed.test:9000"
QDRANT_URL = "http://qdrant.test:6333"


class ScriptedPrompter(Prompter):
    def __init__(
        self,
        *,
        yes: Iterable[bool] = (),
        choices: Iterable[int] = (),
        texts: Iterable[str] = (),
        multis: Iterable[list[int]] = (),
    ) -> None:
        self._yes = list(yes)
        self._choices = list(choices)
        self._texts = list(texts)
        self._multis = list(multis)
        self.messages: list[str] = []
        self.menus: list[list[str]] = []

    def say(self, message: str = "") -> None:
        self.messages.append(message)

    def ask_yes_no(self, question: str, *, default: bool = True) -> bool:
        return self._yes.pop(0) if self._yes else default

    def ask_choice(
        self,
        question: str,
        options: Sequence[str],
        *,
        default: int = 0,
        search: bool = False,
        instruction: str | None = None,
    ) -> int:
        self.menus.append(list(options))
        return self._choices.pop(0) if self._choices else default

    def ask_text(
        self,
        question: str,
        *,
        default: str | None = None,
        allow_empty: bool = False,
        secret: bool = False,
    ) -> str:
        if self._texts:
            return self._texts.pop(0)
        return default or ""

    def ask_multi(
        self,
        question: str,
        options: Sequence[str],
        *,
        default: Sequence[int] = (),
        instruction: str | None = None,
    ) -> list[int]:
        return self._multis.pop(0) if self._multis else list(default)


class FakeRunner(Runner):
    def __init__(
        self,
        *,
        which_map: dict[str, str] | None = None,
        results: dict[tuple[str, ...], CommandResult] | None = None,
        default: CommandResult | None = None,
        console_rc: int = 0,
        creates_tool_env: Path | None = None,
    ) -> None:
        self.which_map = which_map or {}
        self.results = results or {}
        self.default = default or CommandResult(1)
        self.console_rc = console_rc
        self.creates_tool_env = creates_tool_env
        self.calls: list[list[str]] = []
        self.console_calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        return self.which_map.get(name)

    def run(self, argv: list[str], *, timeout: float = 15.0, cwd=None) -> CommandResult:
        self.calls.append(list(argv))
        if self.creates_tool_env is not None and argv[1:3] == ["tool", "install"]:
            self.creates_tool_env.mkdir(parents=True, exist_ok=True)
        for prefix, result in self.results.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return result
        return self.default

    def run_console(self, argv: list[str], *, timeout: float = 900.0) -> int:
        self.console_calls.append(list(argv))
        return self.console_rc


class FakeHttp(Http):
    def __init__(
        self,
        *,
        dim: int = DIM,
        qdrant: bool = True,
        models_by_url: dict[str, list[str]] | None = None,
    ) -> None:
        self.dim = dim
        self.qdrant = qdrant
        # probe rewrites loopback URLs to 127.0.0.1; keys are normalised the
        # same way so tests can keep spelling them "localhost".
        self.models_by_url = {
            ipv4_loopback(url): models for url, models in (models_by_url or {}).items()
        }
        self.urls: list[str] = []

    def get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 5.0,
    ) -> Any | None:
        self.urls.append(url)
        if url.endswith("/v1/models"):
            base = ipv4_loopback(url[: -len("/v1/models")])
            return {
                "data": [{"id": model} for model in self.models_by_url.get(base, [])]
            }
        if url.endswith(("/healthz", "/collections")):
            return {} if self.qdrant else None
        return None

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> tuple[int, Any] | None:
        self.urls.append(url)
        return 200, {"data": [{"embedding": [0.0] * self.dim, "index": 0}]}


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return project, home, repo


def _tool_runner(tmp_path: Path, *, preinstalled: bool = True) -> FakeRunner:
    """A runner whose `uv tool dir` reports a directory this test owns."""
    tool_root = tmp_path / "tools" / install_mod.TOOL_NAME
    if preinstalled:
        tool_root.mkdir(parents=True, exist_ok=True)
    return FakeRunner(
        which_map={"uv": "/usr/bin/uv"},
        results={
            ("/usr/bin/uv", "tool", "dir"): CommandResult(0, str(tmp_path / "tools"))
        },
        default=CommandResult(0),
        creates_tool_env=tool_root,
    )


@pytest.fixture(autouse=True)
def _fake_tool_install(request, tmp_path, monkeypatch):
    """Stub the uv tool install seam unless the test asserts the install argv.

    Every wizard run installs the tool, but almost no test cares: patch the two
    install-module functions so a run needs no uv and no real environment. Tests
    that do care declare the `real_install` fixture to opt out.
    """
    if "real_install" in request.fixturenames:
        return
    root = tmp_path / "toolenv"
    root.mkdir()
    monkeypatch.setattr(install_mod, "tool_env_root", lambda runner: root)

    def fake_ensure_tool(runner, *, spec, editable, output):
        return root

    monkeypatch.setattr(install_mod, "ensure_tool", fake_ensure_tool)


@pytest.fixture
def real_install() -> None:
    """Opt out of `_fake_tool_install` and use the real install seam."""


def _wizard(
    tmp_path: Path,
    *,
    prompts: ScriptedPrompter,
    runner: FakeRunner | None = None,
    http: FakeHttp | None = None,
    **options,
) -> tuple[Wizard, Path, Path]:
    project, home, repo = _workspace(tmp_path)
    options.setdefault("harnesses", "none")
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=runner or _docker_runner(),
        http=http or FakeHttp(),
        **options,
    )
    return wizard, project, home


def _docker_runner(
    *,
    containers: str = "",
    port: str = "",
    inspect: str = "running\n",
) -> FakeRunner:
    return FakeRunner(
        which_map={
            "docker": "/usr/bin/docker",
            "uv": "/usr/bin/uv",
            "uvx": "/usr/bin/uvx",
        },
        results={
            ("docker", "info"): CommandResult(0),
            ("docker", "ps"): CommandResult(0, stdout=containers),
            ("docker", "port"): CommandResult(0, stdout=port),
            ("docker", "inspect"): CommandResult(0, stdout=inspect),
            ("docker", "start"): CommandResult(0),
            ("docker", "compose"): CommandResult(0),
        },
        default=CommandResult(1),
    )


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _compose(home: Path) -> Any:
    return _yaml(home / ".simple-ci" / "docker" / "docker-compose.yml")


def _global(home: Path) -> Any:
    return _yaml(home / ".simple-ci" / "config.yaml")


def _global_config_block(messages: Sequence[str]) -> list[str]:
    """The lines printed under "Global config:", stopping at the first prompt."""
    lines: list[str] = []
    for message in messages:
        if message.startswith("Global config: "):
            lines = [message]
            continue
        if lines and message.startswith("  "):
            lines.append(message)
        elif lines:
            break
    return lines


def test_existing_endpoint_writes_one_global_config(
    tmp_path: Path, monkeypatch
) -> None:
    prompts = ScriptedPrompter(
        choices=[2, 2, 1],
        texts=[EMBED_URL, "", "my-model", QDRANT_URL],
    )
    wizard, project, home = _wizard(tmp_path, prompts=prompts)

    assert wizard.run() == 0

    global_config = home / ".simple-ci" / "config.yaml"
    document = _global(home)
    assert document["embedding"]["base_url"] == EMBED_URL
    assert document["embedding"]["model"] == "my-model"
    assert document["embedding"]["dim"] == DIM
    assert document["embedding"]["api_key"] is None
    assert "service" not in document["embedding"]
    assert document["vector_store"] == "qdrant"
    assert document["qdrant"] == {"url": QDRANT_URL}
    assert not (project / ".simple-ci" / "config.yaml").exists()

    monkeypatch.setenv("WORKSPACE_ROOT", str(project))
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(global_config))
    settings = load_settings()
    assert settings.vector_store == "qdrant"
    assert settings.embed_dim == DIM
    assert settings.embed_base_url == EMBED_URL
    assert settings.config_source == global_config
    assert settings.config_sources == (global_config,)
    assert settings.embedding_service is None


def test_cancel_at_embedding_choice_aborts_without_writing(tmp_path: Path) -> None:
    prompts = ScriptedPrompter(choices=[3])
    wizard, project, home = _wizard(tmp_path, prompts=prompts)

    assert wizard.run() == 1
    assert not (project / ".simple-ci").exists()
    assert not (home / ".simple-ci").exists()


def test_auto_download_writes_compose_and_services(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        provision, "available_port", lambda host, preferred, attempts=20: preferred
    )
    downloaded: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        provision,
        "download_model",
        lambda url, destination, **kwargs: downloaded.append((url, destination)),
    )
    prompts = ScriptedPrompter(choices=[1, 1, 2, 0])
    runner = _docker_runner()
    wizard, project, home = _wizard(tmp_path, prompts=prompts, runner=runner)

    assert wizard.run() == 0

    compose = _compose(home)
    embed = compose["services"]["embed"]
    assert embed["image"] == gpu.CPU_IMAGE
    assert (
        "LLAMA_ARG_MODEL=/models/Qwen3-Embedding-0.6B-Q8_0.gguf" in embed["environment"]
    )
    assert "LLAMA_ARG_ALIAS=Qwen3-Embedding-0.6B" in embed["environment"]
    assert "LLAMA_ARG_POOLING=last" in embed["environment"]
    assert "LLAMA_ARG_CTX_SIZE=8192" in embed["environment"]
    assert "LLAMA_ARG_BATCH=2048" in embed["environment"]
    assert "LLAMA_ARG_UBATCH=2048" in embed["environment"]
    assert not any("N_GPU_LAYERS" in item for item in embed["environment"])
    assert embed["volumes"] == ["../model:/models:ro"]
    assert "deploy" not in embed
    assert compose["services"]["qdrant"]["volumes"] == [
        "../qdrant_storage:/qdrant/storage"
    ]

    expected = (
        "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/resolve/main/"
        "Qwen3-Embedding-0.6B-Q8_0.gguf"
    )
    model_file = home / ".simple-ci" / "model" / "Qwen3-Embedding-0.6B-Q8_0.gguf"
    assert downloaded == [(expected, model_file)]

    document = _global(home)
    assert document["embedding"]["model"] == "Qwen3-Embedding-0.6B"
    assert document["embedding"]["dim"] == DIM
    assert document["embedding"]["query_prefix"] == model_prompts.QWEN_CODE_QUERY
    assert document["embedding"]["document_prefix"] is None
    assert document["embedding"]["service"]["compose_service"] == "embed"
    assert document["setup"]["model_key"] == "qwen3-embedding-0.6b"
    assert document["setup"]["gpu"] == "cpu"
    assert document["vector_store"] == "qdrant"
    assert not (project / ".simple-ci" / "config.yaml").exists()
    assert any(call[:2] == ["docker", "compose"] for call in runner.calls)


def test_auto_download_reuses_the_running_container_port(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        provision, "download_model", lambda url, destination, **kwargs: None
    )
    monkeypatch.setattr(
        provision, "available_port", lambda host, preferred, attempts=20: 8080
    )
    runner = _docker_runner(port="127.0.0.1:9191\n")
    wizard, _project, home = _wizard(
        tmp_path,
        prompts=ScriptedPrompter(choices=[0]),
        runner=runner,
        model="embeddinggemma2",
    )

    assert wizard.run() == 0

    embed = _compose(home)["services"]["embed"]
    assert "127.0.0.1:9191:8080" in embed["ports"]
    assert _global(home)["embedding"]["base_url"] == "http://localhost:9191"


def test_auto_download_gemma_on_nvidia_writes_prompts_and_devices(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        provision, "available_port", lambda host, preferred, attempts=20: preferred
    )
    downloaded: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        provision,
        "download_model",
        lambda url, destination, **kwargs: downloaded.append((url, destination)),
    )
    prompts = ScriptedPrompter(choices=[1, 0, 0])
    runner = FakeRunner(
        which_map={
            "docker": "/usr/bin/docker",
            "uvx": "/usr/bin/uvx",
            "nvidia-smi": "/usr/bin/nvidia-smi",
        },
        results={
            ("nvidia-smi", "-L"): CommandResult(0, "GPU 0: NVIDIA GeForce RTX 4090\n"),
            ("docker", "info", "--format"): CommandResult(0, '{"nvidia": {}}'),
            ("docker", "info"): CommandResult(0),
            ("docker", "compose"): CommandResult(0),
        },
        default=CommandResult(1),
    )
    wizard, _project, home = _wizard(tmp_path, prompts=prompts, runner=runner)

    assert wizard.run() == 0

    embed = _compose(home)["services"]["embed"]
    assert embed["image"] == "ghcr.io/ggml-org/llama.cpp:server-cuda"
    assert "LLAMA_ARG_N_GPU_LAYERS=auto" in embed["environment"]
    devices = embed["deploy"]["resources"]["reservations"]["devices"]
    assert devices[0]["driver"] == "nvidia"
    assert devices[0]["capabilities"] == ["gpu"]

    assert downloaded
    assert "unsloth/embeddinggemma-2-GGUF" in downloaded[0][0]
    assert "mmproj" not in downloaded[0][0]
    assert downloaded[0][1].name == "embeddinggemma-2-BF16.gguf"
    assert (home / ".simple-ci" / "docker" / "gpu_init.sh").is_file()

    document = _global(home)
    assert document["embedding"]["query_prefix"] == model_prompts.GEMMA_CODE_QUERY
    assert document["embedding"]["document_prefix"] == model_prompts.GEMMA_CODE_DOCUMENT
    assert document["setup"]["gpu"] == "nvidia"
    assert document["vector_store"] == "sqlite-vec"


def test_nvidia_init_runs_when_the_runtime_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        provision, "available_port", lambda host, preferred, attempts=20: preferred
    )
    monkeypatch.setattr(
        provision, "download_model", lambda url, destination, **kwargs: None
    )
    prompts = ScriptedPrompter(yes=[True], choices=[0])
    runner = FakeRunner(
        which_map={
            "docker": "/usr/bin/docker",
            "uvx": "/usr/bin/uvx",
            "nvidia-smi": "/usr/bin/nvidia-smi",
            "wsl": "C:/Windows/System32/wsl.exe",
        },
        results={
            ("nvidia-smi", "-L"): CommandResult(0, "GPU 0: NVIDIA RTX 4090\n"),
            ("docker", "info"): CommandResult(0),
            ("docker", "compose"): CommandResult(0),
        },
        default=CommandResult(1),
        console_rc=0,
    )
    wizard, _project, home = _wizard(
        tmp_path,
        prompts=prompts,
        runner=runner,
        platform="win32",
        model="embeddinggemma2",
    )

    assert wizard.run() == 0

    script = home / ".simple-ci" / "docker" / "gpu_init.sh"
    assert runner.console_calls == [["wsl", "-e", "bash", str(script)]]
    assert (
        _compose(home)["services"]["embed"]["image"]
        == "ghcr.io/ggml-org/llama.cpp:server-cuda"
    )


def test_nvidia_init_failure_falls_back_to_cpu(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        provision, "available_port", lambda host, preferred, attempts=20: preferred
    )
    monkeypatch.setattr(
        provision, "download_model", lambda url, destination, **kwargs: None
    )
    prompts = ScriptedPrompter(yes=[True], choices=[0])
    runner = FakeRunner(
        which_map={
            "docker": "/usr/bin/docker",
            "uvx": "/usr/bin/uvx",
            "nvidia-smi": "/usr/bin/nvidia-smi",
            "wsl": "C:/Windows/System32/wsl.exe",
        },
        results={
            ("nvidia-smi", "-L"): CommandResult(0, "GPU 0: NVIDIA RTX 4090\n"),
            ("docker", "info"): CommandResult(0),
            ("docker", "compose"): CommandResult(0),
        },
        default=CommandResult(1),
        console_rc=1,
    )
    wizard, _project, home = _wizard(
        tmp_path,
        prompts=prompts,
        runner=runner,
        platform="win32",
        model="embeddinggemma2",
    )

    assert wizard.run() == 0

    embed = _compose(home)["services"]["embed"]
    assert embed["image"] == gpu.CPU_IMAGE
    assert "deploy" not in embed
    assert not any("N_GPU_LAYERS" in item for item in embed["environment"])
    assert _global(home)["setup"]["gpu"] == "cpu"


def test_existing_stopped_container_is_started(tmp_path: Path) -> None:
    prompts = ScriptedPrompter(choices=[0, 0, 2, 1], texts=[QDRANT_URL])
    runner = _docker_runner(
        containers=(
            "embed-box\tghcr.io/ggml-org/llama.cpp:server\t"
            "Exited (1) 2 hours ago\t0.0.0.0:9191->8080/tcp\n"
        ),
        port="0.0.0.0:9191\n",
        inspect="exited\n",
    )
    http = FakeHttp(models_by_url={"http://localhost:9191": ["my-model"]})
    wizard, project, home = _wizard(tmp_path, prompts=prompts, runner=runner, http=http)

    assert wizard.run() == 0

    assert ["docker", "start", "embed-box"] in runner.calls
    document = _global(home)
    assert document["embedding"]["base_url"] == "http://localhost:9191"
    assert document["embedding"]["service"] == {
        "container": "embed-box",
        "startup_timeout_s": 120.0,
    }
    assert document["vector_store"] == "qdrant"
    assert not (project / ".simple-ci" / "config.yaml").exists()


def test_embedding_menu_lists_all_containers_with_running_marker(
    tmp_path: Path,
) -> None:
    prompts = ScriptedPrompter(choices=[0, 0, 0])
    runner = _docker_runner(
        containers=(
            "web-box\tnginx:latest\tUp 2 hours\t0.0.0.0:80->80/tcp\n"
            "embed-box\tghcr.io/ggml-org/llama.cpp:server\t"
            "Exited (1) 2 hours ago\t0.0.0.0:9191->8080/tcp\n"
        ),
        port="0.0.0.0:9191\n",
        inspect="exited\n",
    )
    http = FakeHttp(models_by_url={"http://localhost:9191": ["my-model"]})
    wizard, _project, home = _wizard(
        tmp_path, prompts=prompts, runner=runner, http=http
    )

    assert wizard.run() == 0

    assert prompts.menus[0] == [
        "Use an existing embedding docker container",
        "Download a model",
        "Use an existing embedding server URL",
        "Cancel",
    ]
    assert prompts.menus[1] == [
        "web-box — nginx:latest (running)",
        "embed-box — ghcr.io/ggml-org/llama.cpp:server",
    ]
    assert _global(home)["embedding"]["service"]["container"] == "web-box"


def test_download_menu_marks_downloaded_models(tmp_path: Path, monkeypatch) -> None:
    project, home, repo = _workspace(tmp_path)
    model_dir = home / ".simple-ci" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / CATALOG[0].filename).write_bytes(b"gguf")
    monkeypatch.setattr(
        provision, "download_model", lambda url, destination, **kwargs: None
    )
    prompts = ScriptedPrompter(choices=[1, 0, 0])
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=_docker_runner(),
        http=FakeHttp(),
        harnesses="none",
    )

    assert wizard.run() == 0

    labels = prompts.menus[1]
    assert labels[0].endswith(" (downloaded)")
    assert labels[1].endswith("GB")
    assert labels[2] == "Qwen3-Embedding-4B (2560-dim) — 3.3 GB"
    assert len(labels) == len(CATALOG) + 1


def test_catalog_lists_qwen3_4b_third() -> None:
    assert [model.key for model in CATALOG[:3]] == [
        "embeddinggemma2",
        "qwen3-embedding-0.6b",
        "qwen3-embedding-4b",
    ]
    model = CATALOG[2]
    assert model.url.startswith("https://huggingface.co/Qwen/Qwen3-Embedding-4B-GGUF/")
    assert model.filename == "Qwen3-Embedding-4B-Q6_K.gguf"
    assert model.dim == 2560
    assert model.pooling == "last"


def test_existing_global_setup_is_reused(tmp_path: Path, monkeypatch) -> None:
    project, home, repo = _workspace(tmp_path)
    global_dir = home / ".simple-ci"
    (global_dir / "docker").mkdir(parents=True)
    (global_dir / "model").mkdir()
    model_file = global_dir / "model" / "embeddinggemma-2-BF16.gguf"
    model_file.write_bytes(b"gguf")
    compose_file = global_dir / "docker" / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    configfile.write_config(
        {
            "version": 1,
            "embedding": {
                "base_url": "http://localhost:8099",
                "model": "embeddinggemma-2",
                "dim": 768,
                "query_prefix": model_prompts.GEMMA_CODE_QUERY,
                "document_prefix": model_prompts.GEMMA_CODE_DOCUMENT,
                "service": {
                    "container": "simple-ci-embed",
                    "compose_file": str(compose_file),
                    "compose_service": "embed",
                },
            },
            "setup": {
                "model_key": "embeddinggemma2",
                "model_file": str(model_file),
                "gpu": "nvidia",
            },
        },
        global_dir / "config.yaml",
    )
    downloaded: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        provision,
        "download_model",
        lambda url, destination, **kwargs: downloaded.append((url, destination)),
    )
    prompts = ScriptedPrompter()
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=_docker_runner(),
        http=FakeHttp(dim=768),
        harnesses="none",
        config_mode="use",
    )

    assert wizard.run() == 0

    assert downloaded == []
    assert any(
        "Reusing the global embedding setup" in line for line in prompts.messages
    )
    block = _global_config_block(prompts.messages)
    assert "  container:    simple-ci-embed" in block
    # This config has no sweep_seconds, so the line is omitted.
    assert not any(line.startswith("  sweep:") for line in block)
    document = _global(home)
    assert document["embedding"]["dim"] == 768
    assert document["setup"]["model_key"] == "embeddinggemma2"
    assert document["embedding"]["service"]["compose_file"] == str(compose_file)
    assert document["vector_store"] == "sqlite-vec"
    assert not (project / ".simple-ci" / "config.yaml").exists()


def test_existing_config_shows_the_sweep_interval_after_the_container(
    tmp_path: Path,
) -> None:
    project, home, repo = _workspace(tmp_path)
    configfile.write_config(
        {
            "version": 1,
            "sweep_seconds": 300,
            "vector_store": "faiss",
            "embedding": {
                "base_url": "http://localhost:8099",
                "model": "embeddinggemma-2",
                "dim": 768,
                "service": {"container": "simple-ci-embed"},
            },
        },
        home / ".simple-ci" / "config.yaml",
    )
    prompts = ScriptedPrompter()
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=_docker_runner(),
        http=FakeHttp(dim=768),
        harnesses="none",
        config_mode="use",
    )

    assert wizard.run() == 0

    block = _global_config_block(prompts.messages)
    container = next(
        index for index, line in enumerate(block) if line.startswith("  container:")
    )
    assert block[container + 1] == "  sweep:        every 300 s"


def test_existing_config_hides_a_disabled_sweep(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    configfile.write_config(
        {
            "version": 1,
            "sweep_seconds": 0,
            "vector_store": "faiss",
            "embedding": {
                "base_url": "http://localhost:8099",
                "model": "embeddinggemma-2",
                "dim": 768,
            },
        },
        home / ".simple-ci" / "config.yaml",
    )
    prompts = ScriptedPrompter()
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=_docker_runner(),
        http=FakeHttp(dim=768),
        harnesses="none",
        config_mode="use",
    )

    assert wizard.run() == 0

    block = _global_config_block(prompts.messages)
    assert not any(line.startswith("  sweep:") for line in block)


def test_a_malformed_global_config_is_not_reused(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    global_dir = home / ".simple-ci"
    global_dir.mkdir(parents=True)
    (global_dir / "config.yaml").write_text("embedding: [1, 2]\n", encoding="utf-8")
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=FakeRunner(),
        assume_yes=True,
    )

    assert wizard._step_existing_config() is None


def test_model_flag_bypasses_the_reuse_prompt(tmp_path: Path, monkeypatch) -> None:
    project, home, repo = _workspace(tmp_path)
    global_dir = home / ".simple-ci"
    (global_dir / "docker").mkdir(parents=True)
    (global_dir / "model").mkdir()
    (global_dir / "model" / "embeddinggemma-2-BF16.gguf").write_bytes(b"gguf")
    (global_dir / "docker" / "docker-compose.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    configfile.write_config(
        {
            "version": 1,
            "embedding": {"base_url": "http://localhost:8099", "model": "old"},
            "setup": {"model_file": str(global_dir / "model" / "x.gguf")},
        },
        global_dir / "config.yaml",
    )
    downloaded: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        provision,
        "download_model",
        lambda url, destination, **kwargs: downloaded.append((url, destination)),
    )
    monkeypatch.setattr(
        provision, "available_port", lambda host, preferred, attempts=20: preferred
    )
    prompts = ScriptedPrompter(choices=[0])
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=_docker_runner(),
        http=FakeHttp(),
        model="qwen3-embedding-0.6b",
        harnesses="none",
    )

    assert wizard.run() == 0

    assert downloaded
    assert "Qwen3-Embedding-0.6B" in downloaded[0][0]
    assert not any("Reuse" in line for line in prompts.messages)


def test_dry_run_writes_nothing_and_runs_no_commands(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    prompts = ScriptedPrompter()
    runner = FakeRunner()
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=runner,
        http=FakeHttp(),
        dry_run=True,
        assume_yes=True,
        harnesses="none",
    )

    assert wizard.run() == 0

    assert runner.calls == []
    assert runner.console_calls == []
    assert not (project / ".simple-ci").exists()
    assert not (home / ".simple-ci").exists()
    assert not (project / ".gitignore").exists()


def _embedding() -> dict[str, Any]:
    return {
        "base_url": "http://localhost:8080",
        "model": "embeddinggemma-2",
        "dim": 768,
        "query_prefix": model_prompts.GEMMA_CODE_QUERY,
        "document_prefix": model_prompts.GEMMA_CODE_DOCUMENT,
        "model_key": "embeddinggemma2",
        "model_file": "/models/embeddinggemma-2-BF16.gguf",
        "gpu": "cpu",
    }


def test_global_config_write_creates_only_one_file(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    wizard = Wizard(cwd=project, home=home, repo_root=repo)

    paths = wizard._write_global_config(_embedding(), "faiss", None, 0)

    assert paths == (home / ".simple-ci" / "config.yaml",)
    document = _yaml(paths[0])
    assert document["embedding"]["model"] == "embeddinggemma-2"
    assert document["setup"]["gpu"] == "cpu"
    assert document["vector_store"] == "faiss"
    assert document["sweep_seconds"] == 0
    assert "qdrant" not in document
    assert not (project / ".simple-ci" / "config.yaml").exists()


def test_explicit_config_writes_one_combined_file(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    target = tmp_path / "custom.yaml"
    wizard = Wizard(cwd=project, home=home, repo_root=repo, config_path=target)

    paths = wizard._write_global_config(_embedding(), "faiss", None, 90)

    assert paths == (target,)
    document = _yaml(target)
    assert document["embedding"]["model"] == "embeddinggemma-2"
    assert document["vector_store"] == "faiss"
    assert document["sweep_seconds"] == 90
    assert not (home / ".simple-ci" / "config.yaml").exists()


def test_sweep_is_off_by_default_and_can_be_enabled(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)

    defaults = Wizard(
        cwd=project, home=home, repo_root=repo, prompts=ScriptedPrompter()
    )
    assert defaults._step_sweep() == 0.0

    enabled = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(yes=[True]),
    )
    assert enabled._step_sweep() == 300.0

    custom = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(yes=[True], texts=["90"]),
    )
    assert custom._step_sweep() == 90.0


def test_existing_sweep_interval_is_reused(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    path = home / ".simple-ci" / "config.yaml"
    configfile.write_config({"sweep_seconds": 30}, path)

    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        config_path=path,
    )

    assert wizard._step_sweep() == 30.0


def test_reuse_skips_the_sweep_question_and_keeps_the_stored_interval(
    tmp_path: Path,
) -> None:
    """The sweep is a global setting: a reused config must not re-ask it."""
    project, home, repo = _workspace(tmp_path)
    configfile.write_config(
        {
            "version": 1,
            "sweep_seconds": 30,
            "vector_store": "faiss",
            "embedding": {
                "base_url": "http://localhost:8099",
                "model": "embeddinggemma-2",
                "dim": DIM,
            },
        },
        home / ".simple-ci" / "config.yaml",
    )
    prompts = ScriptedPrompter(yes=[False])
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=_docker_runner(),
        http=FakeHttp(),
        harnesses="none",
        config_mode="use",
    )

    assert wizard.run() == 0

    # A False here would answer the sweep question and store 0.
    assert _global(home)["sweep_seconds"] == 30


def test_sweep_seconds_flag_overrides_a_reused_interval(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    configfile.write_config(
        {
            "version": 1,
            "sweep_seconds": 30,
            "vector_store": "faiss",
            "embedding": {
                "base_url": "http://localhost:8099",
                "model": "embeddinggemma-2",
                "dim": DIM,
            },
        },
        home / ".simple-ci" / "config.yaml",
    )
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(yes=[False]),
        runner=_docker_runner(),
        http=FakeHttp(),
        harnesses="none",
        config_mode="use",
        sweep_seconds=90,
    )

    assert wizard.run() == 0

    assert _global(home)["sweep_seconds"] == 90


def test_sweep_seconds_option_reaches_the_config(tmp_path: Path) -> None:
    wizard, _project, home = _wizard(
        tmp_path,
        prompts=ScriptedPrompter(),
        runner=FakeRunner(),
        embedding_url=EMBED_URL,
        vector_store="faiss",
        sweep_seconds=90,
    )

    assert wizard.run() == 0

    assert _global(home)["sweep_seconds"] == 90


def test_negative_sweep_seconds_flag_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        wizard_run(["--sweep-seconds", "-1"])

    assert exc.value.code == 2
    assert "--sweep-seconds" in capsys.readouterr().err


def test_scope_flag_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        wizard_run(["--scope", "local"])

    assert exc.value.code == 2
    assert "--scope was removed" in capsys.readouterr().err


def test_local_config_is_migrated_and_removed(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    local = project / ".simple-ci" / "config.yaml"
    local.parent.mkdir(parents=True)
    configfile.write_config(
        {"version": 1, "vector_store": "qdrant", "embedding": {"model": "local"}},
        local,
    )
    configfile.write_config(
        {
            "version": 1,
            "embedding": {"base_url": "http://localhost:8080", "model": "global"},
        },
        home / ".simple-ci" / "config.yaml",
    )
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(yes=[True]),
        runner=FakeRunner(),
    )

    wizard._step_migrate_local_config()

    document = _global(home)
    assert document["vector_store"] == "qdrant"
    assert document["embedding"]["model"] == "local"
    assert document["embedding"]["base_url"] == "http://localhost:8080"
    assert not local.exists()


def test_docker_missing_offers_winget_install(tmp_path: Path, monkeypatch) -> None:
    project, home, repo = _workspace(tmp_path)
    runner = FakeRunner(
        which_map={"winget": "C:/winget.exe"},
        console_rc=0,
    )
    monkeypatch.setattr(provision, "wait_until", lambda *args, **kwargs: False)
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(yes=[True]),
        runner=runner,
        platform="win32",
    )

    assert wizard._step_docker() is False

    assert runner.console_calls
    assert runner.console_calls[0][:3] == ["winget", "install", "--id"]


def test_docker_installed_but_stopped_offers_to_start(
    tmp_path: Path, monkeypatch
) -> None:
    project, home, repo = _workspace(tmp_path)
    runner = FakeRunner(
        which_map={"docker": "/usr/bin/docker"},
        results={("docker", "info"): CommandResult(1)},
    )
    monkeypatch.setattr(provision, "wait_until", lambda *args, **kwargs: False)
    started: list[bool] = []
    monkeypatch.setattr(
        provision,
        "start_docker_daemon",
        lambda *args, **kwargs: started.append(True) or True,
    )
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(yes=[True]),
        runner=runner,
    )

    assert wizard._step_docker() is False
    assert started == [True]


def test_install_editable_points_entries_at_the_tool_environment(
    tmp_path: Path, real_install
) -> None:
    project, _home, repo = _workspace(tmp_path)
    tools = tmp_path / "tools" / install_mod.TOOL_NAME
    tools.mkdir(parents=True)
    runner = _tool_runner(tmp_path)
    wizard = Wizard(
        cwd=project,
        home=_home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=runner,
        platform="win32",
    )

    result = wizard._step_install()

    assert result.root == tools
    assert result.server_command == [
        str(tools / "Scripts" / "pythonw.exe"),
        "-m",
        "simple_code_indexer",
        "serve",
    ]
    install_call = next(
        call for call in runner.calls if call[:3] == ["/usr/bin/uv", "tool", "install"]
    )
    # A source checkout links itself, so setup works before the first publish.
    assert install_call[-1] == str(repo.resolve())
    assert "--editable" in install_call
    assert wizard._record_tool_env == tools
    assert wizard._record_install_kind == "editable"


def test_install_wheel_produces_the_same_entry_as_editable(
    tmp_path: Path, real_install
) -> None:
    """The whole point: switching flavour must never change the harness entry."""
    project, _home, repo = _workspace(tmp_path)
    tools = tmp_path / "tools" / install_mod.TOOL_NAME
    tools.mkdir(parents=True)
    editable = Wizard(
        cwd=project,
        home=_home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=_tool_runner(tmp_path),
        platform="win32",
    )._step_install()
    wheel = Wizard(
        cwd=project,
        home=_home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=_tool_runner(tmp_path),
        platform="win32",
        editable=False,
    )._step_install()

    assert editable.server_command == wheel.server_command
    assert editable.root == wheel.root == tools


def test_install_wheel_builds_the_local_tree(tmp_path: Path, real_install) -> None:
    project, _home, repo = _workspace(tmp_path)
    tools = tmp_path / "tools" / install_mod.TOOL_NAME
    tools.mkdir(parents=True)
    runner = _tool_runner(tmp_path)
    wizard = Wizard(
        cwd=project,
        home=_home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=runner,
        platform="win32",
        editable=False,
    )

    wizard._step_install()

    install_call = next(
        call for call in runner.calls if call[:3] == ["/usr/bin/uv", "tool", "install"]
    )
    assert install_call[-1] == str(repo.resolve())
    assert "--editable" not in install_call
    assert "--refresh" in install_call
    assert wizard._record_install_kind == "wheel"


def test_install_without_a_checkout_pins_the_published_version(
    tmp_path: Path, real_install
) -> None:
    """Editable needs a tree to link, so a wheel run falls back to PyPI."""
    tool_root = tmp_path / "tools" / install_mod.TOOL_NAME
    tool_root.mkdir(parents=True)
    runner = _tool_runner(tmp_path)
    prompts = ScriptedPrompter()
    wizard = Wizard(
        cwd=tmp_path,
        home=tmp_path / "home",
        prompts=prompts,
        runner=runner,
        platform="win32",
    )

    wizard._step_install()

    install_call = next(
        call for call in runner.calls if call[:3] == ["/usr/bin/uv", "tool", "install"]
    )
    assert (
        install_call[-1]
        == f"{install_mod.TOOL_NAME}=={logging_setup.package_version()}"
    )
    assert "--editable" not in install_call
    assert any("No source checkout found" in line for line in prompts.messages)
    assert wizard._record_install_kind == "wheel"


def test_install_only_installs_the_tool_and_writes_no_config(
    tmp_path: Path, monkeypatch, real_install
) -> None:
    _project, home, repo = _workspace(tmp_path)
    tools = tmp_path / "tools" / install_mod.TOOL_NAME
    tools.mkdir(parents=True)
    calls: list[list[str]] = []

    class RecordingRunner(Runner):
        def which(self, name: str) -> str | None:
            return "/usr/bin/uv" if name == "uv" else None

        def run(
            self, argv: list[str], *, timeout: float = 15.0, cwd=None
        ) -> CommandResult:
            calls.append(list(argv))
            if argv[1:3] == ["tool", "dir"]:
                return CommandResult(0, str(tmp_path / "tools"))
            return CommandResult(0)

    monkeypatch.setattr(provision, "Runner", RecordingRunner)

    code = wizard_run(["--install-only", "--repo-root", str(repo)])

    assert code == 0
    assert not (home / ".simple-ci").exists()
    assert any(call[:3] == ["/usr/bin/uv", "tool", "install"] for call in calls)


def test_install_only_never_repins_to_an_interpreter_that_is_missing(
    tmp_path: Path, monkeypatch, real_install
) -> None:
    """A fake or stale `uv tool dir` must not reach a client config (ISS-023).

    The repin is the one write `--install-only` performs outside the tool
    environment, and it acts on real config files. Pointing an entry at a
    `<tools>/…/pythonw.exe` that does not exist disables the server silently,
    so a missing interpreter is a refusal, not a rewrite.
    """
    _project, home, repo = _workspace(tmp_path)
    (tmp_path / "tools" / install_mod.TOOL_NAME).mkdir(parents=True)
    config = home / ".simple-ci" / "config.yaml"
    config.parent.mkdir(parents=True)
    cursor_config = home / ".cursor" / "mcp.json"
    cursor_config.parent.mkdir(parents=True)
    before = '{"mcpServers": {"simple-code-indexer": {"command": "keep"}}}'
    cursor_config.write_text(before, encoding="utf-8")
    config.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "setup": {
                    "harnesses": [{"name": "cursor", "config": str(cursor_config)}]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(config))

    class ToolRunner(Runner):
        def which(self, name: str) -> str | None:
            return "/usr/bin/uv" if name == "uv" else None

        def run(
            self, argv: list[str], *, timeout: float = 15.0, cwd=None
        ) -> CommandResult:
            if argv[1:3] == ["tool", "dir"]:
                return CommandResult(0, str(tmp_path / "tools"))
            return CommandResult(0)

    monkeypatch.setattr(provision, "Runner", ToolRunner)

    assert wizard_run(["--install-only", "--repo-root", str(repo)]) == 1
    assert cursor_config.read_text(encoding="utf-8") == before


def test_install_only_reads_the_config_simple_ci_config_names(
    tmp_path: Path, monkeypatch, real_install
) -> None:
    """The record must come from the documented override, not `Path.home()`.

    Reading `.simple-ci/config.yaml` directly ignores `SIMPLE_CI_CONFIG`, which
    is exactly how a test's fake tool directory reached the developer's real
    `~/.commandcode/mcp.json` (ISS-023).
    """
    _project, home, repo = _workspace(tmp_path)
    (tmp_path / "tools" / install_mod.TOOL_NAME).mkdir(parents=True)
    real_home_record = tmp_path / "untouched" / "config.yaml"
    real_home_record.parent.mkdir(parents=True)
    real_home_record.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "setup": {"harnesses": [{"name": "cursor", "config": "nowhere.json"}]},
            }
        ),
        encoding="utf-8",
    )
    chosen = tmp_path / "chosen" / "config.yaml"
    chosen.parent.mkdir(parents=True)
    chosen.write_text(
        yaml.safe_dump({"version": 1, "setup": {"harnesses": []}}), encoding="utf-8"
    )
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(chosen))
    monkeypatch.setattr(
        configfile, "global_config_path", lambda home=None: real_home_record
    )

    class ToolRunner(Runner):
        def which(self, name: str) -> str | None:
            return "/usr/bin/uv" if name == "uv" else None

        def run(
            self, argv: list[str], *, timeout: float = 15.0, cwd=None
        ) -> CommandResult:
            if argv[1:3] == ["tool", "dir"]:
                return CommandResult(0, str(tmp_path / "tools"))
            return CommandResult(0)

    monkeypatch.setattr(provision, "Runner", ToolRunner)

    assert wizard_run(["--install-only", "--repo-root", str(repo)]) == 0
    assert not (home / ".simple-ci").exists()


def test_install_only_dry_run_runs_nothing(
    tmp_path: Path, monkeypatch, real_install
) -> None:
    _project, _home, repo = _workspace(tmp_path)
    calls: list[list[str]] = []

    class RecordingRunner(Runner):
        def which(self, name: str) -> str | None:
            return "/usr/bin/uv" if name == "uv" else None

        def run(
            self, argv: list[str], *, timeout: float = 15.0, cwd=None
        ) -> CommandResult:
            calls.append(list(argv))
            return CommandResult(0)

    monkeypatch.setattr(provision, "Runner", RecordingRunner)

    code = wizard_run(["--install-only", "--dry-run", "--repo-root", str(repo)])

    assert code == 0
    assert not any(
        call[1:3] in (["tool", "install"], ["tool", "uninstall"]) for call in calls
    )


def test_install_only_rejects_setup_flags() -> None:
    with pytest.raises(SystemExit):
        wizard_run(["--install-only", "--vector-store", "faiss"])
    with pytest.raises(SystemExit):
        wizard_run(["--install-only", "--uninstall"])


def test_an_entry_carries_no_env(tmp_path: Path, monkeypatch) -> None:
    project, home, repo = _workspace(tmp_path)
    (home / ".cursor").mkdir()
    specs = load_harnesses(user_dirs=[])
    cursor_index = next(
        index for index, spec in enumerate(specs) if spec.name == "cursor"
    )
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(multis=[[cursor_index]]),
        runner=FakeRunner(),
    )
    result = install_mod.InstallResult(root=tmp_path / "tool-env", platform="linux")

    wizard._step_harnesses(result)

    entry = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))[
        "mcpServers"
    ]["simple-code-indexer"]
    assert "env" not in entry
    assert entry["command"] == str(tmp_path / "tool-env" / "bin" / "python")
    assert entry["args"] == ["-m", "simple_code_indexer", "serve"]


def test_install_only_refreshes_the_recorded_entries(
    tmp_path: Path, monkeypatch, real_install
) -> None:
    _project, home, repo = _workspace(tmp_path)
    tools = tmp_path / "tools" / install_mod.TOOL_NAME
    tools.mkdir(parents=True)
    config = home / ".simple-ci" / "config.yaml"
    config.parent.mkdir(parents=True)
    cursor_config = home / ".cursor" / "mcp.json"
    cursor_config.parent.mkdir(parents=True)
    cursor_config.write_text(
        '{"mcpServers": {"other": {"command": "x"}}}', encoding="utf-8"
    )
    config.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "setup": {
                    "harnesses": [{"name": "cursor", "config": str(cursor_config)}],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(config))
    interpreter = install_mod.InstallResult(
        root=tools, platform=sys.platform
    ).interpreter
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"stub")

    class ToolRunner(Runner):
        def which(self, name: str) -> str | None:
            return "/usr/bin/uv" if name == "uv" else None

        def run(
            self, argv: list[str], *, timeout: float = 15.0, cwd=None
        ) -> CommandResult:
            if argv[1:3] == ["tool", "dir"]:
                return CommandResult(0, str(tmp_path / "tools"))
            return CommandResult(0)

    monkeypatch.setattr(provision, "Runner", ToolRunner)

    opts = ["--install-only", "--repo-root", str(repo)]
    assert wizard_run(opts) == 0
    first = cursor_config.read_text(encoding="utf-8")
    assert wizard_run(opts) == 0
    assert cursor_config.read_text(encoding="utf-8") == first

    document = json.loads(first)
    assert document["mcpServers"]["other"] == {"command": "x"}
    entry = document["mcpServers"]["simple-code-indexer"]
    expected = (
        tools / "Scripts" / "pythonw.exe"
        if sys.platform == "win32"
        else tools / "bin" / "python"
    )
    assert entry["command"] == str(expected)
    assert "env" not in entry


def test_harness_install_merges_and_backs_up(tmp_path: Path, monkeypatch) -> None:
    project, home, repo = _workspace(tmp_path)
    (home / ".cursor").mkdir()
    target = home / ".cursor" / "mcp.json"
    target.write_text(
        '{"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}',
        encoding="utf-8",
    )
    specs = load_harnesses(user_dirs=[])
    cursor_index = next(
        index for index, spec in enumerate(specs) if spec.name == "cursor"
    )
    prompts = ScriptedPrompter(multis=[[cursor_index]])
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=FakeRunner(),
    )
    result = install_mod.InstallResult(root=repo, platform="linux")

    wizard._step_harnesses(result)

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["theme"] == "dark"
    assert document["mcpServers"]["other"] == {"command": "x"}
    entry = document["mcpServers"]["simple-code-indexer"]
    assert entry["command"] == str(repo / "bin" / "python")
    assert entry["args"] == ["-m", "simple_code_indexer", "serve"]
    assert list((home / ".cursor").glob("mcp.json.bak.*"))
    assert not (project / ".cursor" / "mcp.json").exists()


def test_harness_install_is_recorded_in_the_config(tmp_path: Path) -> None:
    wizard, _project, home = _wizard(
        tmp_path,
        prompts=ScriptedPrompter(),
        runner=_docker_runner(),
        embedding_url=EMBED_URL,
        vector_store="faiss",
        harnesses="cursor",
    )

    assert wizard.run() == 0

    target = home / ".cursor" / "mcp.json"
    setup = _global(home)["setup"]
    assert setup["harnesses"] == [
        {"name": "cursor", "config": str(target), "scope": "global"}
    ]


def test_the_tool_environment_is_recorded(tmp_path: Path, real_install) -> None:
    tools = tmp_path / "tools" / install_mod.TOOL_NAME
    tools.mkdir(parents=True)
    wizard, _project, home = _wizard(
        tmp_path,
        prompts=ScriptedPrompter(),
        runner=_tool_runner(tmp_path),
        harnesses="none",
        embedding_url=EMBED_URL,
        vector_store="faiss",
    )

    assert wizard.run() == 0

    setup = _global(home)["setup"]
    assert setup["install_kind"] == "editable"
    assert "install_mode" not in setup
    assert setup["tool_env"] == str(tools)


def test_the_summary_shows_the_install_kind(tmp_path: Path, real_install) -> None:
    """Guards the anti-drift line: an editable install must not be invisible."""
    for editable, expected in ((True, "editable"), (False, "wheel")):
        prompts = ScriptedPrompter()
        wizard, _project, _home = _wizard(
            tmp_path,
            prompts=prompts,
            runner=_tool_runner(tmp_path),
            editable=editable,
            embedding_url=EMBED_URL,
            vector_store="faiss",
        )

        assert wizard.run() == 0
        assert f"  kind:         {expected}" in prompts.messages


def test_deselecting_a_harness_removes_its_entry_and_backup(tmp_path: Path) -> None:
    _project, home, _repo = _workspace(tmp_path)
    target = home / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        '{"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}',
        encoding="utf-8",
    )
    first = _wizard(
        tmp_path,
        prompts=ScriptedPrompter(),
        harnesses="cursor",
        embedding_url=EMBED_URL,
        vector_store="faiss",
        runner=_docker_runner(),
    )[0]
    assert first.run() == 0
    assert list(target.parent.glob("mcp.json.bak.*"))
    assert (
        "simple-code-indexer"
        in json.loads(target.read_text(encoding="utf-8"))["mcpServers"]
    )

    second = _wizard(
        tmp_path,
        prompts=ScriptedPrompter(),
        harnesses="none",
        embedding_url=EMBED_URL,
        vector_store="faiss",
        runner=_docker_runner(),
    )[0]
    assert second.run() == 0

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["theme"] == "dark"
    assert document["mcpServers"] == {"other": {"command": "x"}}
    assert not list(target.parent.glob("mcp.json.bak.*"))
    assert "harnesses" not in _global(home).get("setup", {})


def test_deselecting_the_only_harness_removes_the_created_config(
    tmp_path: Path,
) -> None:
    wizard, _project, home = _wizard(
        tmp_path,
        prompts=ScriptedPrompter(),
        runner=_docker_runner(),
        embedding_url=EMBED_URL,
        vector_store="faiss",
        harnesses="cursor",
    )
    assert wizard.run() == 0
    target = home / ".cursor" / "mcp.json"
    assert target.is_file()

    _wizard(tmp_path, prompts=ScriptedPrompter(), harnesses="none")[0].run()

    assert not target.exists()
    assert not (home / ".cursor").exists()


def test_a_recorded_harness_path_that_moved_is_cleaned_up(
    tmp_path: Path, monkeypatch
) -> None:
    project, home, repo = _workspace(tmp_path)
    stale = home / ".old" / "mcp.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(
        '{"mcpServers": {"simple-code-indexer": {"command": "old"}}}',
        encoding="utf-8",
    )
    specs = load_harnesses(user_dirs=[])
    cursor_index = next(
        index for index, spec in enumerate(specs) if spec.name == "cursor"
    )
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(multis=[[cursor_index]]),
        runner=FakeRunner(),
    )
    wizard._record_harnesses = [{"name": "cursor", "config": str(stale)}]
    result = install_mod.InstallResult(root=repo, platform="linux")

    wizard._step_harnesses(result)

    target = home / ".cursor" / "mcp.json"
    assert not stale.exists()
    assert not stale.parent.exists()
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["mcpServers"]["simple-code-indexer"]["command"] == str(
        repo / "bin" / "python"
    )
    assert wizard._record_harnesses == [
        {"name": "cursor", "config": str(target), "scope": "global"}
    ]


def test_harness_selection_parser(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    wizard = Wizard(cwd=project, home=home, repo_root=repo)
    specs = load_harnesses(user_dirs=[])

    assert wizard._parse_harness_selection("none", specs) == []
    assert wizard._parse_harness_selection("all", specs) == list(range(len(specs)))
    names = {"mimo", "opencode"}
    expected = sorted(index for index, spec in enumerate(specs) if spec.name in names)
    assert wizard._parse_harness_selection("mimo,opencode", specs) == expected
    with pytest.raises(SetupAborted):
        wizard._parse_harness_selection("nope", specs)


def test_container_flag_forces_an_existing_container(tmp_path: Path) -> None:
    runner = _docker_runner(
        containers=(
            "embed-box\tghcr.io/ggml-org/llama.cpp:server\t"
            "Up 2 hours\t0.0.0.0:9191->8080/tcp\n"
        ),
        port="0.0.0.0:9191\n",
    )
    http = FakeHttp(models_by_url={"http://localhost:9191": ["my-model"]})
    wizard, _project, home = _wizard(
        tmp_path,
        prompts=ScriptedPrompter(),
        runner=runner,
        http=http,
        container="embed-box",
        vector_store="faiss",
    )

    assert wizard.run() == 0

    document = _global(home)
    assert document["embedding"]["base_url"] == "http://localhost:9191"
    assert document["embedding"]["model"] == "my-model"
    assert document["embedding"]["dim"] == DIM


def test_embedding_url_flag_forces_a_url(tmp_path: Path) -> None:
    wizard, _project, home = _wizard(
        tmp_path,
        prompts=ScriptedPrompter(yes=[False]),
        runner=FakeRunner(),
        embedding_url=EMBED_URL,
        vector_store="faiss",
    )

    assert wizard.run() == 0

    document = _global(home)
    assert document["embedding"]["base_url"] == EMBED_URL
    assert document["embedding"]["dim"] == DIM
    assert "service" not in document["embedding"]


def test_legacy_models_directory_is_migrated(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    legacy = home / ".simple-ci" / "models"
    legacy.mkdir(parents=True)
    (legacy / "old.gguf").write_bytes(b"gguf")
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=FakeRunner(),
    )

    wizard._step_migrate_global_assets()

    assert (home / ".simple-ci" / "model" / "old.gguf").is_file()
    assert not legacy.exists()


def test_faiss_branch_writes_no_qdrant_config(tmp_path: Path) -> None:
    prompts = ScriptedPrompter(choices=[2, 1], texts=[EMBED_URL, "", "my-model"])
    runner = _docker_runner()
    wizard, _project, home = _wizard(tmp_path, prompts=prompts, runner=runner)

    assert wizard.run() == 0

    document = _global(home)
    assert document["vector_store"] == "faiss"
    assert "qdrant" not in document
    assert not any(call[:2] == ["docker", "compose"] for call in runner.calls)


def test_run_leaves_the_workspace_untouched(tmp_path: Path) -> None:
    prompts = ScriptedPrompter(choices=[2, 1], texts=[EMBED_URL, "", "my-model"])
    wizard, project, _home = _wizard(tmp_path, prompts=prompts)

    assert wizard.run() == 0

    assert not (project / ".simple-ci").exists()
    assert not (project / ".index").exists()
    assert not (project / ".gitignore").exists()
    assert not any(
        line.strip().startswith(("index:", "vectors:", "collection:"))
        for line in prompts.messages
    )


def test_the_backend_default_follows_the_existing_config(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    config = project / ".simple-ci" / "config.yaml"
    config.parent.mkdir()
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=FakeRunner(),
        config_path=config,
    )

    config.write_text("qdrant:\n  url: http://x:6333\n", encoding="utf-8")
    assert wizard._existing_vector_store() == "qdrant"

    config.write_text(
        "vector_store: faiss\nqdrant:\n  url: http://x:6333\n", encoding="utf-8"
    )
    assert wizard._existing_vector_store() == "faiss"

    config.write_text("vector_store: qdrant\n", encoding="utf-8")
    assert wizard._existing_vector_store() == "qdrant"

    config.write_text("vector_store: faiss\n", encoding="utf-8")
    assert wizard._existing_vector_store() == "faiss"


def test_container_env_parses_docker_inspect() -> None:
    runner = FakeRunner(
        results={
            ("docker", "inspect", "-f", "{{json .Config.Env}}"): CommandResult(
                0, '["A=1","B=x=y"]'
            )
        }
    )

    assert provision.container_env(runner, "box") == {"A": "1", "B": "x=y"}


def test_qwen_container_with_mean_pooling_warns(tmp_path: Path) -> None:
    runner = FakeRunner(
        which_map={"docker": "/usr/bin/docker"},
        results={
            ("docker", "inspect", "-f", "{{json .Config.Env}}"): CommandResult(
                0, '["LLAMA_ARG_POOLING=mean"]'
            ),
            ("docker", "inspect"): CommandResult(0, "running\n"),
            ("docker", "port"): CommandResult(0, "0.0.0.0:9191\n"),
        },
    )
    prompts = ScriptedPrompter()
    http = FakeHttp(
        dim=2560,
        models_by_url={"http://localhost:9191": ["Qwen3-Embedding-4B-Q6_K"]},
    )
    project, home, repo = _workspace(tmp_path)
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=runner,
        http=http,
        embedding_model="Qwen3-Embedding-4B-Q6_K",
    )
    container = provision.EmbeddingContainer(
        name="box",
        image="llama.cpp",
        status="Up",
        url="http://localhost:9191",
    )

    result = wizard._embedding_from_container(container)

    assert result["dim"] == 2560
    assert any("mean pooling" in message for message in prompts.messages)


def test_the_catalog_downloads_no_mmproj() -> None:
    gemma = CATALOG[0]

    assert "unsloth/embeddinggemma-2-GGUF" in gemma.url
    assert gemma.filename == "embeddinggemma-2-BF16.gguf"
    assert all(
        "mmproj" not in item.url and "mmproj" not in item.filename for item in CATALOG
    )


def test_compose_template_renders_each_backend() -> None:
    model = CATALOG[0]

    nvidia = provision.embed_service(
        model, 8080, model.filename, image=gpu.IMAGES["nvidia"], gpu_vendor="nvidia"
    )
    amd = provision.embed_service(
        model, 8080, model.filename, image=gpu.IMAGES["amd"], gpu_vendor="amd"
    )
    intel = provision.embed_service(
        model, 8080, model.filename, image=gpu.IMAGES["intel"], gpu_vendor="intel"
    )
    cpu = provision.embed_service(model, 8080, model.filename)

    assert nvidia["deploy"]["resources"]["reservations"]["devices"][0][
        "capabilities"
    ] == ["gpu"]
    assert "LLAMA_ARG_N_GPU_LAYERS=auto" in nvidia["environment"]
    assert amd["devices"] == ["/dev/kfd", "/dev/dri"]
    assert "seccomp:unconfined" in amd["security_opt"]
    assert intel["devices"] == ["/dev/dri"]
    assert "deploy" not in amd
    assert "deploy" not in intel
    assert "deploy" not in cpu
    assert not any("N_GPU_LAYERS" in item for item in cpu["environment"])


# -- project scope (ADR-022) ---------------------------------------------


def _scope_wizard(
    tmp_path: Path, *, harnesses: str, scope: str, runner: FakeRunner | None = None
) -> tuple[Wizard, Path, Path, Path]:
    project, home, repo = _workspace(tmp_path)
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=runner or FakeRunner(),
        harnesses=harnesses,
        harness_scope=scope,
    )
    return wizard, project, home, repo


def test_a_project_entry_pins_the_workspace(tmp_path: Path) -> None:
    monkeypatch_specs = load_harnesses(user_dirs=[])
    assert any(spec.name == "cursor" for spec in monkeypatch_specs)
    wizard, project, home, _repo = _scope_wizard(
        tmp_path, harnesses="cursor", scope="project"
    )
    result = install_mod.InstallResult(root=tmp_path / "tool-env", platform="linux")

    wizard._step_harnesses(result)

    target = project / ".cursor" / "mcp.json"
    entry = json.loads(target.read_text(encoding="utf-8"))["mcpServers"][
        "simple-code-indexer"
    ]
    assert entry["args"] == [
        "-m",
        "simple_code_indexer",
        "serve",
        "--workspace",
        str(project),
    ]
    assert "env" not in entry
    assert not (home / ".cursor" / "mcp.json").exists()
    assert wizard._record_harnesses == [
        {
            "name": "cursor",
            "config": str(target),
            "scope": "project",
            "workspace": str(project),
        }
    ]


def test_a_global_entry_is_never_pinned(tmp_path: Path) -> None:
    wizard, _project, home, _repo = _scope_wizard(
        tmp_path, harnesses="cursor", scope="global"
    )
    result = install_mod.InstallResult(root=tmp_path / "tool-env", platform="linux")

    wizard._step_harnesses(result)

    entry = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))[
        "mcpServers"
    ]["simple-code-indexer"]
    assert entry["args"] == ["-m", "simple_code_indexer", "serve"]
    assert "--workspace" not in entry["args"]


def test_switching_scope_removes_the_old_entry(tmp_path: Path) -> None:
    wizard, project, home, repo = _scope_wizard(
        tmp_path, harnesses="cursor", scope="global"
    )
    result = install_mod.InstallResult(root=tmp_path / "tool-env", platform="linux")
    wizard._step_harnesses(result)
    assert (home / ".cursor" / "mcp.json").is_file()

    second = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=FakeRunner(),
        harnesses="cursor",
        harness_scope="project",
    )
    second._record_harnesses = list(wizard._record_harnesses)

    second._step_harnesses(result)

    assert not (home / ".cursor" / "mcp.json").exists()
    assert (project / ".cursor" / "mcp.json").is_file()


def test_running_in_the_home_directory_forces_global(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    prompts = ScriptedPrompter()
    wizard = Wizard(
        cwd=home,
        home=home,
        prompts=prompts,
        runner=FakeRunner(),
        harnesses="cursor",
        harness_scope="project",
    )

    assert wizard._step_harness_scope(load_harnesses(user_dirs=[])) == "global"
    assert any("home directory" in message for message in prompts.messages)


def test_a_client_without_a_project_config_falls_back_to_global(
    tmp_path: Path, capsys
) -> None:
    wizard, project, _home, _repo = _scope_wizard(
        tmp_path, harnesses="goose", scope="project"
    )
    result = install_mod.InstallResult(root=tmp_path / "tool-env", platform="linux")

    wizard._step_harnesses(result)

    assert not (project / "goose").exists()
    recorded = wizard._record_harnesses
    assert recorded and recorded[0]["scope"] == "global"
    assert Path(recorded[0]["config"]).is_file()
    assert "workspace" not in recorded[0]


def test_the_client_cli_is_preferred_when_it_is_on_path(
    tmp_path: Path, monkeypatch
) -> None:
    runner = FakeRunner(
        which_map={"claude": "/usr/bin/claude"}, default=CommandResult(0)
    )

    def fake_run(argv: list[str], *, timeout: float = 15.0, cwd=None) -> CommandResult:
        runner.calls.append(list(argv))
        return CommandResult(0)

    monkeypatch.setattr(runner, "run", fake_run)
    wizard, project, _home, _repo = _scope_wizard(
        tmp_path, harnesses="claude_code", scope="project", runner=runner
    )
    result = install_mod.InstallResult(root=tmp_path / "tool-env", platform="linux")

    wizard._step_harnesses(result)

    # The CLI is run at the path `which` resolved, not the bare name.
    add = [
        call for call in runner.calls if call[:3] == ["/usr/bin/claude", "mcp", "add"]
    ]
    assert add and add[0][3:5] == ["-s", "project"]
    assert "--workspace" in add[0] and str(project) in add[0]


def test_a_failing_cli_falls_back_to_the_config_file(
    tmp_path: Path, monkeypatch
) -> None:

    def fake_run(argv: list[str], *, timeout: float = 15.0, cwd=None) -> CommandResult:
        return CommandResult(1, "", "boom")

    runner = FakeRunner(which_map={"claude": "/usr/bin/claude"})
    monkeypatch.setattr(runner, "run", fake_run)
    wizard, project, _home, _repo = _scope_wizard(
        tmp_path, harnesses="claude_code", scope="project", runner=runner
    )
    result = install_mod.InstallResult(root=tmp_path / "tool-env", platform="linux")

    wizard._step_harnesses(result)

    entry = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))[
        "mcpServers"
    ]["simple-code-indexer"]
    assert entry["args"][-2:] == ["--workspace", str(project)]


def test_project_scope_offers_gitignore_once(tmp_path: Path, monkeypatch) -> None:
    wizard, project, _home, _repo = _scope_wizard(
        tmp_path, harnesses="cursor", scope="project"
    )
    (project / ".git").mkdir()
    wizard.gitignore = True
    result = install_mod.InstallResult(root=tmp_path / "tool-env", platform="linux")

    wizard._step_harnesses(result)
    wizard._step_harnesses(result)

    text = (project / ".gitignore").read_text(encoding="utf-8")
    assert text.count(".cursor/mcp.json") == 1
    assert text.count(".simple-ci/") == 1


def test_gitignore_is_left_alone_outside_a_repository(
    tmp_path: Path, monkeypatch
) -> None:
    wizard, project, _home, _repo = _scope_wizard(
        tmp_path, harnesses="cursor", scope="project"
    )
    wizard.gitignore = True
    result = install_mod.InstallResult(root=tmp_path / "tool-env", platform="linux")

    wizard._step_harnesses(result)

    assert not (project / ".gitignore").exists()


def test_gitignore_already_covering_the_entry_is_not_rewritten(
    tmp_path: Path, monkeypatch
) -> None:
    from simple_code_indexer.setup_wizard import gitignore

    wizard, project, _home, _repo = _scope_wizard(
        tmp_path, harnesses="cursor", scope="project"
    )
    (project / ".git").mkdir()
    (project / ".gitignore").write_text(".cursor/\n.simple-ci/\n", encoding="utf-8")
    wizard.gitignore = True
    result = install_mod.InstallResult(root=tmp_path / "tool-env", platform="linux")

    wizard._step_harnesses(result)

    assert gitignore.missing(project, [".cursor/mcp.json", ".simple-ci/"]) == []
