from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import yaml

from simple_code_indexer import harnesses as harnesses_pkg
from simple_code_indexer.config import load_settings
from simple_code_indexer.harnesses import load_harnesses
from simple_code_indexer.setup_wizard import Wizard, provision
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
    ) -> None:
        self.which_map = which_map or {}
        self.results = results or {}
        self.default = default or CommandResult(1)
        self.calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        return self.which_map.get(name)

    def run(self, argv: list[str], *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(list(argv))
        for prefix, result in self.results.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return result
        return self.default


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


def test_existing_endpoint_writes_probed_dimension(
    tmp_path: Path, monkeypatch
) -> None:
    prompts = ScriptedPrompter(
        yes=[True, False, True, False],
        texts=[
            "http://embed.test:9000",
            "",
            "my-model",
            "http://qdrant.test:6333",
        ],
        multis=[[]],
    )
    wizard, project, _ = _wizard(tmp_path, prompts=prompts)

    assert wizard.run() == 0

    config = project / ".simple-ci" / "config.yaml"
    assert config.is_file()
    document = _yaml(config)
    assert document["embedding"]["base_url"] == "http://embed.test:9000"
    assert document["embedding"]["model"] == "my-model"
    assert document["embedding"]["dim"] == DIM
    assert document["embedding"]["api_key"] is None
    assert "service" not in document["embedding"]
    assert document["qdrant"] == {"url": "http://qdrant.test:6333"}

    monkeypatch.setenv("SIMPLE_CI_CONFIG", str(config))
    monkeypatch.setenv("WORKSPACE_ROOT", str(project))
    settings = load_settings()
    assert settings.embed_dim == DIM
    assert settings.embed_base_url == "http://embed.test:9000"
    assert settings.config_source == config
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
        choices=[1],
        multis=[[]],
    )
    runner = FakeRunner(
        which_map={"docker": "/usr/bin/docker", "uvx": "/usr/bin/uvx"},
        results={("docker", "info"): CommandResult(0)},
        default=CommandResult(0),
    )
    wizard, project, home = _wizard(tmp_path, prompts=prompts, runner=runner)

    assert wizard.run() == 0

    compose = home / ".simple-ci" / "docker-compose.yml"
    compose_text = compose.read_text(encoding="utf-8")
    assert "ghcr.io/ggml-org/llama.cpp:server" in compose_text
    assert "qdrant/qdrant:latest" in compose_text
    assert "--pooling" in compose_text
    assert downloaded and downloaded[0][1].name == "Qwen3-Embedding-0.6B-Q8_0.gguf"

    document = _yaml(project / ".simple-ci" / "config.yaml")
    assert document["embedding"]["dim"] == DIM
    assert document["embedding"]["service"]["compose_service"] == "embed"
    assert document["qdrant"]["service"]["compose_service"] == "qdrant"
    assert any(call[:2] == ["docker", "compose"] for call in runner.calls)


def test_existing_stopped_container_is_started(tmp_path: Path) -> None:
    prompts = ScriptedPrompter(
        yes=[True, True, True, False],
        texts=["my-embed-model", "http://localhost:6333"],
        choices=[0],
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
    wizard, project, _ = _wizard(tmp_path, prompts=prompts, runner=runner)

    assert wizard.run() == 0

    assert ["docker", "start", "embed-box"] in runner.calls
    document = _yaml(project / ".simple-ci" / "config.yaml")
    assert document["embedding"]["base_url"] == "http://localhost:9191"
    assert document["embedding"]["service"] == {"container": "embed-box"}


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

    assert runner.calls == []
    assert not (project / ".simple-ci").exists()
    assert not (home / ".simple-ci").exists()
    assert not (project / ".gitignore").exists()


def test_global_config_scope_path(tmp_path: Path) -> None:
    _project, home, repo = _workspace(tmp_path)
    wizard = Wizard(cwd=repo, home=home, repo_root=repo, scope="global")

    assert wizard._choose_config_path() == home / ".simple-ci" / "config.yaml"


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


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
