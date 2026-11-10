from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from simple_code_indexer import configfile, model_prompts
from simple_code_indexer import harnesses as harnesses_pkg
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
    ) -> None:
        self.which_map = which_map or {}
        self.results = results or {}
        self.default = default or CommandResult(1)
        self.console_rc = console_rc
        self.calls: list[list[str]] = []
        self.console_calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        return self.which_map.get(name)

    def run(self, argv: list[str], *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(list(argv))
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
    (repo / "run_server.py").write_text("# launcher\n", encoding="utf-8")
    return project, home, repo


def _wizard(
    tmp_path: Path,
    *,
    prompts: ScriptedPrompter,
    runner: FakeRunner | None = None,
    http: FakeHttp | None = None,
    **options,
) -> tuple[Wizard, Path, Path]:
    project, home, repo = _workspace(tmp_path)
    options.setdefault("no_install", True)
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


def test_existing_endpoint_writes_one_global_config(
    tmp_path: Path, monkeypatch
) -> None:
    prompts = ScriptedPrompter(
        choices=[2, 1, 1],
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
    prompts = ScriptedPrompter(choices=[1, 1, 1, 0])
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
    assert document["vector_store"] == "faiss"


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
    prompts = ScriptedPrompter(choices=[0, 0, 1, 1], texts=[QDRANT_URL])
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
        no_install=True,
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
        no_install=True,
        harnesses="none",
        config_mode="use",
    )

    assert wizard.run() == 0

    assert downloaded == []
    assert any(
        "Reusing the global embedding setup" in line for line in prompts.messages
    )
    document = _global(home)
    assert document["embedding"]["dim"] == 768
    assert document["setup"]["model_key"] == "embeddinggemma2"
    assert document["embedding"]["service"]["compose_file"] == str(compose_file)
    assert document["vector_store"] == "faiss"
    assert not (project / ".simple-ci" / "config.yaml").exists()


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
        no_install=True,
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
        no_install=True,
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

    paths = wizard._write_global_config(_embedding(), "faiss", None)

    assert paths == (home / ".simple-ci" / "config.yaml",)
    document = _yaml(paths[0])
    assert document["embedding"]["model"] == "embeddinggemma-2"
    assert document["setup"]["gpu"] == "cpu"
    assert document["vector_store"] == "faiss"
    assert "qdrant" not in document
    assert not (project / ".simple-ci" / "config.yaml").exists()


def test_explicit_config_writes_one_combined_file(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    target = tmp_path / "custom.yaml"
    wizard = Wizard(cwd=project, home=home, repo_root=repo, config_path=target)

    paths = wizard._write_global_config(_embedding(), "faiss", None)

    assert paths == (target,)
    document = _yaml(target)
    assert document["embedding"]["model"] == "embeddinggemma-2"
    assert document["vector_store"] == "faiss"
    assert not (home / ".simple-ci" / "config.yaml").exists()


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


def test_install_copies_repo_and_points_entries_at_the_install(
    tmp_path: Path, monkeypatch
) -> None:
    project, _home, repo = _workspace(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "marker").write_text("x", encoding="utf-8")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")
    install_dir = tmp_path / "install"
    synced: list[Path] = []
    monkeypatch.setattr(
        install_mod,
        "sync_env",
        lambda runner, target, output: synced.append(target) or True,
    )
    wizard = Wizard(
        cwd=project,
        home=_home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=FakeRunner(which_map={"uv": "/usr/bin/uv"}),
        install_dir=install_dir,
        platform="win32",
    )

    result = wizard._step_install()

    assert (install_dir / "run_server.py").is_file()
    assert (install_dir / ".git" / "config").is_file()
    assert not (install_dir / ".venv").exists()
    assert not (install_dir / "__pycache__").exists()
    assert result.root == install_dir
    assert result.server_command == [
        "/usr/bin/uv",
        "run",
        "--project",
        str(install_dir),
        "--no-sync",
        "python",
        str(install_dir / "run_server.py"),
    ]
    assert synced == [install_dir]

    (install_dir / ".git" / "config").write_text(
        "[core]\n\tinstalled=true\n", encoding="utf-8"
    )
    wizard._step_install()
    assert "installed=true" in (install_dir / ".git" / "config").read_text(
        encoding="utf-8"
    )


def test_install_only_copies_the_checkout_and_writes_no_config(
    tmp_path: Path,
) -> None:
    _project, home, repo = _workspace(tmp_path)
    (repo / "setup.py").write_text("# setup\n", encoding="utf-8")
    target = tmp_path / "install"

    code = wizard_run(
        [
            "--install-only",
            "--repo-root",
            str(repo),
            "--install-dir",
            str(target),
        ]
    )

    assert code == 0
    assert (target / "run_server.py").is_file()
    assert (target / "setup.py").is_file()
    assert not (home / ".simple-ci").exists()


def test_install_only_defaults_to_the_per_user_app_directory(
    tmp_path: Path, monkeypatch
) -> None:
    _project, _home, repo = _workspace(tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))
    target = install_mod.install_root(home=Path.home(), platform=sys.platform)

    assert wizard_run(["--install-only", "--repo-root", str(repo)]) == 0

    assert (target / "run_server.py").is_file()


def test_install_only_dry_run_copies_nothing(tmp_path: Path) -> None:
    _project, _home, repo = _workspace(tmp_path)
    target = tmp_path / "install"

    code = wizard_run(
        [
            "--install-only",
            "--dry-run",
            "--repo-root",
            str(repo),
            "--install-dir",
            str(target),
        ]
    )

    assert code == 0
    assert not target.exists()


def test_install_only_rejects_setup_flags() -> None:
    with pytest.raises(SystemExit):
        wizard_run(["--install-only", "--vector-store", "faiss"])
    with pytest.raises(SystemExit):
        wizard_run(["--install-only", "--uninstall"])


def test_harness_install_merges_and_backs_up(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(harnesses_pkg, "_which", lambda _name: None)
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
    result = install_mod.InstallResult(
        root=repo,
        launcher=repo / "run_server.py",
        uv="/usr/bin/uv",
    )

    wizard._step_harnesses(result)

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["theme"] == "dark"
    assert document["mcpServers"]["other"] == {"command": "x"}
    entry = document["mcpServers"]["simple-code-indexer"]
    assert entry["command"] == "/usr/bin/uv"
    assert entry["args"] == [
        "run",
        "--project",
        str(repo),
        "--no-sync",
        "python",
        str(repo / "run_server.py"),
    ]
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
    assert setup["harnesses"] == [{"name": "cursor", "config": str(target)}]
    assert "install_root" not in setup


def test_the_install_copy_is_recorded(tmp_path: Path, monkeypatch) -> None:
    project, home, repo = _workspace(tmp_path)
    install_dir = tmp_path / "install"
    monkeypatch.setattr(install_mod, "sync_env", lambda runner, target, output: True)
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=_docker_runner(),
        http=FakeHttp(),
        install_dir=install_dir,
        harnesses="none",
        embedding_url=EMBED_URL,
        vector_store="faiss",
    )

    assert wizard.run() == 0

    assert _global(home)["setup"]["install_root"] == str(install_dir.resolve())
    assert (install_dir / "run_server.py").is_file()


def _recorded_install(tmp_path: Path, home: Path) -> Path:
    old = tmp_path / "old-install"
    old.mkdir()
    (old / install_mod.LAUNCHER_FILENAME).write_text("# launcher\n", encoding="utf-8")
    config = home / ".simple-ci" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        yaml.safe_dump({"version": 1, "setup": {"install_root": str(old)}}),
        encoding="utf-8",
    )
    return old


def _moved_install_wizard(
    tmp_path: Path, monkeypatch, prompts: ScriptedPrompter, **options
) -> tuple[Wizard, Path, Path]:
    project, home, repo = _workspace(tmp_path)
    monkeypatch.setattr(install_mod, "sync_env", lambda runner, target, output: True)
    options.setdefault("install_dir", tmp_path / "new-install")
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=_docker_runner(),
        http=FakeHttp(),
        harnesses="none",
        embedding_url=EMBED_URL,
        vector_store="faiss",
        **options,
    )
    return wizard, home, options["install_dir"]


def test_a_changed_install_dir_removes_the_old_copy(
    tmp_path: Path, monkeypatch
) -> None:
    prompts = ScriptedPrompter()
    wizard, home, new = _moved_install_wizard(tmp_path, monkeypatch, prompts)
    old = _recorded_install(tmp_path, home)

    assert wizard.run() == 0

    assert not old.exists()
    assert _global(home)["setup"]["install_root"] == str(new.resolve())
    assert (new / "run_server.py").is_file()


def test_declining_removal_keeps_the_old_copy(tmp_path: Path, monkeypatch) -> None:
    prompts = ScriptedPrompter(yes=[False])
    wizard, home, _new = _moved_install_wizard(tmp_path, monkeypatch, prompts)
    old = _recorded_install(tmp_path, home)

    assert wizard.run() == 0

    assert (old / install_mod.LAUNCHER_FILENAME).is_file()
    assert any("Kept" in message for message in prompts.messages)


def test_dry_run_keeps_the_old_install_copy(tmp_path: Path, monkeypatch) -> None:
    prompts = ScriptedPrompter()
    wizard, home, _new = _moved_install_wizard(
        tmp_path, monkeypatch, prompts, dry_run=True
    )
    old = _recorded_install(tmp_path, home)

    assert wizard.run() == 0

    assert old.is_dir()
    assert any("Would delete the previous install copy" in m for m in prompts.messages)


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
    monkeypatch.setattr(harnesses_pkg, "_which", lambda _name: None)
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
    result = install_mod.InstallResult(
        root=repo,
        launcher=repo / "run_server.py",
        uv="/usr/bin/uv",
    )

    wizard._step_harnesses(result)

    target = home / ".cursor" / "mcp.json"
    assert not stale.exists()
    assert not stale.parent.exists()
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["mcpServers"]["simple-code-indexer"]["command"] == "/usr/bin/uv"
    assert wizard._record_harnesses == [{"name": "cursor", "config": str(target)}]


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


def test_no_install_entries_point_at_the_checkout(tmp_path: Path) -> None:
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
    document = json.loads(target.read_text(encoding="utf-8"))
    entry = document["mcpServers"]["simple-code-indexer"]
    assert entry["command"] == "/usr/bin/uv"
    assert entry["args"] == [
        "run",
        "--project",
        str(wizard.repo_root),
        "--no-sync",
        "python",
        str(wizard.repo_root / "run_server.py"),
    ]


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
    prompts = ScriptedPrompter(choices=[2, 0], texts=[EMBED_URL, "", "my-model"])
    runner = _docker_runner()
    wizard, _project, home = _wizard(tmp_path, prompts=prompts, runner=runner)

    assert wizard.run() == 0

    document = _global(home)
    assert document["vector_store"] == "faiss"
    assert "qdrant" not in document
    assert not any(call[:2] == ["docker", "compose"] for call in runner.calls)


def test_run_leaves_the_workspace_untouched(tmp_path: Path) -> None:
    prompts = ScriptedPrompter(choices=[2, 0], texts=[EMBED_URL, "", "my-model"])
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
