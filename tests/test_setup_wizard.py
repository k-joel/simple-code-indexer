from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import yaml

from simple_code_indexer import configfile, model_prompts
from simple_code_indexer import harnesses as harnesses_pkg
from simple_code_indexer.config import load_settings
from simple_code_indexer.harnesses import load_harnesses
from simple_code_indexer.setup_wizard import Wizard, gpu, provision
from simple_code_indexer.setup_wizard.catalog import CATALOG
from simple_code_indexer.setup_wizard.probe import Http
from simple_code_indexer.setup_wizard.prompts import Prompter
from simple_code_indexer.setup_wizard.provision import CommandResult, Runner

DIM = 1024


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

    def say(self, message: str = "") -> None:
        self.messages.append(message)

    def ask_yes_no(self, question: str, *, default: bool = True) -> bool:
        return self._yes.pop(0) if self._yes else default

    def ask_choice(
        self, question: str, options: Sequence[str], *, default: int = 0
    ) -> int:
        return self._choices.pop(0) if self._choices else default

    def ask_text(
        self,
        question: str,
        *,
        default: str | None = None,
        allow_empty: bool = False,
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
    def __init__(self, *, dim: int = DIM, qdrant: bool = True) -> None:
        self.dim = dim
        self.qdrant = qdrant
        self.urls: list[str] = []

    def get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 5.0,
    ) -> Any | None:
        self.urls.append(url)
        if url.endswith("/v1/models"):
            return {"data": [{"id": "my-model"}]}
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
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
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
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=runner or FakeRunner(),
        http=http or FakeHttp(),
        **options,
    )
    return wizard, project, home


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _compose(home: Path) -> Any:
    return _yaml(home / ".simple-ci" / "docker" / "docker-compose.yml")


def test_existing_endpoint_writes_probed_dimension(tmp_path: Path, monkeypatch) -> None:
    prompts = ScriptedPrompter(
        yes=[True, False, True, False],
        choices=[1],
        texts=[
            "http://embed.test:9000",
            "",
            "my-model",
            "http://qdrant.test:6333",
        ],
        multis=[[]],
    )
    wizard, project, home = _wizard(tmp_path, prompts=prompts)
    global_config = home / ".simple-ci" / "config.yaml"
    local_config = project / ".simple-ci" / "config.yaml"

    assert wizard.run() == 0

    global_document = _yaml(global_config)
    assert global_document["embedding"]["base_url"] == "http://embed.test:9000"
    assert global_document["embedding"]["model"] == "my-model"
    assert global_document["embedding"]["dim"] == DIM
    assert global_document["embedding"]["api_key"] is None
    assert "service" not in global_document["embedding"]
    assert "vector_store" not in global_document
    assert global_document["qdrant"] == {"url": "http://qdrant.test:6333"}

    local_document = _yaml(local_config)
    assert local_document["vector_store"] == "qdrant"
    assert "embedding" not in local_document

    monkeypatch.setenv("WORKSPACE_ROOT", str(project))
    monkeypatch.setattr(
        configfile, "config_paths", lambda _root: (global_config, local_config)
    )
    settings = load_settings()
    assert settings.vector_store == "qdrant"
    assert settings.embed_dim == DIM
    assert settings.embed_base_url == "http://embed.test:9000"
    assert settings.config_source == local_config
    assert settings.config_sources == (global_config, local_config)
    assert settings.embedding_service is None


def test_cancel_at_model_choice_aborts_without_writing(tmp_path: Path) -> None:
    prompts = ScriptedPrompter(yes=[False], choices=[len(CATALOG)])
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
    prompts = ScriptedPrompter(
        yes=[False, False, True],
        choices=[1, 1],
        multis=[[]],
    )
    runner = FakeRunner(
        which_map={"docker": "/usr/bin/docker", "uvx": "/usr/bin/uvx"},
        results={
            ("docker", "info"): CommandResult(0),
            ("docker", "compose"): CommandResult(0),
        },
        default=CommandResult(1),
    )
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
    assert "LLAMA_ARG_CTX_SIZE=32768" in embed["environment"]
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

    global_document = _yaml(home / ".simple-ci" / "config.yaml")
    assert global_document["embedding"]["model"] == "Qwen3-Embedding-0.6B"
    assert global_document["embedding"]["dim"] == DIM
    assert global_document["embedding"]["query_prefix"] == model_prompts.QWEN_CODE_QUERY
    assert global_document["embedding"]["document_prefix"] is None
    assert global_document["embedding"]["service"]["compose_service"] == "embed"
    assert global_document["setup"]["model_key"] == "qwen3-embedding-0.6b"
    assert global_document["setup"]["gpu"] == "cpu"

    local_document = _yaml(project / ".simple-ci" / "config.yaml")
    assert local_document["vector_store"] == "qdrant"
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
    runner = FakeRunner(
        which_map={"docker": "/usr/bin/docker", "uvx": "/usr/bin/uvx"},
        results={
            ("docker", "port"): CommandResult(0, stdout="127.0.0.1:9191\n"),
            ("docker", "compose"): CommandResult(0),
        },
        default=CommandResult(1),
    )
    wizard, _project, home = _wizard(
        tmp_path,
        prompts=ScriptedPrompter(multis=[[]]),
        runner=runner,
        model="embeddinggemma2",
    )

    assert wizard.run() == 0

    embed = _compose(home)["services"]["embed"]
    assert "127.0.0.1:9191:8080" in embed["ports"]
    assert (
        _yaml(home / ".simple-ci" / "config.yaml")["embedding"]["base_url"]
        == "http://localhost:9191"
    )


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
    prompts = ScriptedPrompter(yes=[False], choices=[0], multis=[[]])
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
    wizard, project, home = _wizard(tmp_path, prompts=prompts, runner=runner)

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

    global_document = _yaml(home / ".simple-ci" / "config.yaml")
    assert (
        global_document["embedding"]["query_prefix"] == model_prompts.GEMMA_CODE_QUERY
    )
    assert (
        global_document["embedding"]["document_prefix"]
        == model_prompts.GEMMA_CODE_DOCUMENT
    )
    assert global_document["setup"]["gpu"] == "nvidia"

    local_document = _yaml(project / ".simple-ci" / "config.yaml")
    assert local_document["vector_store"] == "faiss"


def test_nvidia_init_runs_when_the_runtime_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        provision, "available_port", lambda host, preferred, attempts=20: preferred
    )
    monkeypatch.setattr(
        provision, "download_model", lambda url, destination, **kwargs: None
    )
    prompts = ScriptedPrompter(yes=[False, True], choices=[0], multis=[[]])
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
        tmp_path, prompts=prompts, runner=runner, platform="win32"
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
    prompts = ScriptedPrompter(yes=[False, True], choices=[0], multis=[[]])
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
        tmp_path, prompts=prompts, runner=runner, platform="win32"
    )

    assert wizard.run() == 0

    embed = _compose(home)["services"]["embed"]
    assert embed["image"] == gpu.CPU_IMAGE
    assert "deploy" not in embed
    assert not any("N_GPU_LAYERS" in item for item in embed["environment"])
    assert _yaml(home / ".simple-ci" / "config.yaml")["setup"]["gpu"] == "cpu"


def test_existing_stopped_container_is_started(tmp_path: Path) -> None:
    prompts = ScriptedPrompter(
        yes=[True, True, True, False],
        texts=["", "my-embed-model", "http://localhost:6333"],
        choices=[0, 1],
        multis=[[]],
    )
    runner = FakeRunner(
        which_map={"docker": "/usr/bin/docker", "uvx": "/usr/bin/uvx"},
        results={
            ("docker", "info"): CommandResult(0),
            ("docker", "ps"): CommandResult(
                0,
                stdout=(
                    "embed-box\tghcr.io/ggml-org/llama.cpp:server\t"
                    "Exited (1) 2 hours ago\t0.0.0.0:9191->8080/tcp\n"
                ),
            ),
            ("docker", "inspect"): CommandResult(0, stdout="exited\n"),
            ("docker", "start"): CommandResult(0),
            ("docker", "port"): CommandResult(0, stdout="0.0.0.0:9191\n"),
        },
    )
    wizard, project, home = _wizard(tmp_path, prompts=prompts, runner=runner)

    assert wizard.run() == 0

    assert ["docker", "start", "embed-box"] in runner.calls
    global_document = _yaml(home / ".simple-ci" / "config.yaml")
    assert global_document["embedding"]["base_url"] == "http://localhost:9191"
    assert global_document["embedding"]["service"] == {"container": "embed-box"}
    assert _yaml(project / ".simple-ci" / "config.yaml")["vector_store"] == "qdrant"


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
    prompts = ScriptedPrompter(yes=[True], multis=[[]])
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=FakeRunner(),
        http=FakeHttp(dim=768),
    )

    assert wizard.run() == 0

    assert downloaded == []
    assert any(
        "Reusing the global embedding setup" in line for line in prompts.messages
    )
    global_document = _yaml(global_dir / "config.yaml")
    assert global_document["embedding"]["dim"] == 768
    assert global_document["setup"]["model_key"] == "embeddinggemma2"
    assert global_document["embedding"]["service"]["compose_file"] == str(compose_file)
    local_document = _yaml(project / ".simple-ci" / "config.yaml")
    assert local_document["vector_store"] == "faiss"


def test_a_malformed_global_config_is_not_reused(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    global_dir = home / ".simple-ci"
    (global_dir / "docker").mkdir(parents=True)
    (global_dir / "model").mkdir()
    (global_dir / "model" / "x.gguf").write_bytes(b"gguf")
    (global_dir / "docker" / "docker-compose.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    (global_dir / "config.yaml").write_text("embedding: [1, 2]\n", encoding="utf-8")
    wizard = Wizard(cwd=project, home=home, repo_root=repo)

    assert wizard._step_existing_global_setup() is None


def test_model_flag_bypasses_the_skip_prompt(tmp_path: Path, monkeypatch) -> None:
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
    prompts = ScriptedPrompter(multis=[[]])
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=FakeRunner(results={("docker", "compose"): CommandResult(0)}),
        http=FakeHttp(),
        model="qwen3-embedding-0.6b",
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
    )

    assert wizard.run() == 0

    assert all(call[0] not in {"docker", "wsl", "bash"} for call in runner.calls)
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


def test_default_writes_global_and_local_configs(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    wizard = Wizard(cwd=project, home=home, repo_root=repo)

    paths = wizard._write_config(_embedding(), "faiss", None)

    assert paths == (
        home / ".simple-ci" / "config.yaml",
        project / ".simple-ci" / "config.yaml",
    )
    global_document = _yaml(paths[0])
    local_document = _yaml(paths[1])
    assert global_document["embedding"]["model"] == "embeddinggemma-2"
    assert global_document["setup"]["gpu"] == "cpu"
    assert "vector_store" not in global_document
    assert "embedding" not in local_document
    assert local_document["vector_store"] == "faiss"


def test_scope_global_writes_only_the_global_file(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    wizard = Wizard(cwd=project, home=home, repo_root=repo, scope="global")

    paths = wizard._write_config(_embedding(), "faiss", None)

    assert paths == (home / ".simple-ci" / "config.yaml",)
    assert not (project / ".simple-ci" / "config.yaml").exists()


def test_scope_local_writes_a_combined_local_file(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    wizard = Wizard(cwd=project, home=home, repo_root=repo, scope="local")

    paths = wizard._write_config(_embedding(), "faiss", None)

    assert paths == (project / ".simple-ci" / "config.yaml",)
    document = _yaml(paths[0])
    assert document["vector_store"] == "faiss"
    assert document["embedding"]["model"] == "embeddinggemma-2"
    assert not (home / ".simple-ci" / "config.yaml").exists()


def test_explicit_config_writes_one_combined_file(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    target = tmp_path / "custom.yaml"
    wizard = Wizard(cwd=project, home=home, repo_root=repo, config_path=target)

    paths = wizard._write_config(_embedding(), "faiss", None)

    assert paths == (target,)
    document = _yaml(target)
    assert document["embedding"]["model"] == "embeddinggemma-2"
    assert document["vector_store"] == "faiss"
    assert not (home / ".simple-ci" / "config.yaml").exists()


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


def test_gitignore_is_appended_once(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    (project / ".git").mkdir()
    gitignore = project / ".gitignore"
    gitignore.write_text("dist/\n", encoding="utf-8")
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=FakeRunner(),
    )

    wizard._step_gitignore()
    wizard._step_gitignore()

    text = gitignore.read_text(encoding="utf-8")
    assert text.startswith("dist/\n")
    assert text.count(".simple-ci/") == 1


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
    prompts = ScriptedPrompter(multis=[[cursor_index]], choices=[0])
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=prompts,
        runner=FakeRunner(which_map={"uvx": "/usr/bin/uvx"}),
    )

    wizard._step_harnesses()

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["theme"] == "dark"
    assert document["mcpServers"]["other"] == {"command": "x"}
    entry = document["mcpServers"]["simple-code-indexer"]
    assert entry["command"] == "/usr/bin/uvx"
    assert entry["args"] == ["--from", str(repo), "simple-code-indexer"]
    assert list((home / ".cursor").glob("mcp.json.bak.*"))


def test_legacy_index_is_migrated(tmp_path: Path) -> None:
    project, home, repo = _workspace(tmp_path)
    legacy = project / ".index" / "index.db"
    legacy.parent.mkdir()
    legacy.write_bytes(b"old-index")
    wizard = Wizard(
        cwd=project,
        home=home,
        repo_root=repo,
        prompts=ScriptedPrompter(),
        runner=FakeRunner(),
    )

    wizard._step_migrate_index()

    assert (project / ".simple-ci" / "index.db").read_bytes() == b"old-index"
    assert not legacy.exists()


def test_faiss_branch_writes_no_qdrant_config(tmp_path: Path) -> None:
    prompts = ScriptedPrompter(
        yes=[True, False],
        texts=["http://embed.test:9000", "", "my-model"],
        multis=[[]],
    )
    runner = FakeRunner(which_map={"docker": "/usr/bin/docker", "uvx": "/usr/bin/uvx"})
    wizard, project, home = _wizard(tmp_path, prompts=prompts, runner=runner)

    assert wizard.run() == 0

    global_document = _yaml(home / ".simple-ci" / "config.yaml")
    local_document = _yaml(project / ".simple-ci" / "config.yaml")
    assert local_document["vector_store"] == "faiss"
    assert "qdrant" not in global_document
    assert not any(call[:1] == ["docker"] for call in runner.calls)


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
