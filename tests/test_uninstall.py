from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable
from pathlib import Path

import pytest
import yaml

from simple_code_indexer.setup_wizard import run as wizard_run
from simple_code_indexer.setup_wizard import uninstall
from simple_code_indexer.setup_wizard.prompts import Prompter
from simple_code_indexer.setup_wizard.provision import CommandResult, Runner

SERVER = "simple-code-indexer"


@pytest.fixture(autouse=True)
def _isolate_the_install_root(tmp_path: Path, monkeypatch) -> None:
    """Never let the fallback app-data path reach the machine's real install."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)


class ScriptedPrompter(Prompter):
    def __init__(self, *, yes: Iterable[bool] = ()) -> None:
        self._yes = list(yes)
        self.messages: list[str] = []

    def say(self, message: str = "") -> None:
        self.messages.append(message)

    def ask_yes_no(self, question: str, *, default: bool = True) -> bool:
        return self._yes.pop(0) if self._yes else default


class FakeRunner(Runner):
    def __init__(self, *, docker: bool = True) -> None:
        self.docker = docker
        self.calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        return "/usr/bin/docker" if self.docker and name == "docker" else None

    def run(self, argv: list[str], *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(list(argv))
        if argv[:2] == ["docker", "info"]:
            return CommandResult(0 if self.docker else 1)
        if argv[:2] == ["docker", "compose"]:
            return CommandResult(0)
        return CommandResult(1)


def _write_config(
    path: Path,
    *,
    harnesses: Iterable[dict[str, str]] = (),
) -> None:
    setup: dict[str, object] = {}
    records = list(harnesses)
    if records:
        setup["harnesses"] = records
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "embedding": {
                    "base_url": "http://localhost:8080",
                    "model": "m",
                    "dim": 8,
                },
                "setup": setup,
            }
        ),
        encoding="utf-8",
    )


def _prepare(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    home.mkdir()

    target = home / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"command": "x"},
                    SERVER: {"command": "old"},
                },
                "theme": "dark",
            }
        ),
        encoding="utf-8",
    )
    (target.parent / "mcp.json.bak.20260101-000000").write_text("{}", encoding="utf-8")
    global_dir = home / ".simple-ci"
    (global_dir / "docker").mkdir(parents=True)
    compose = global_dir / "docker" / "docker-compose.yml"
    compose.write_text("name: simple-ci\n", encoding="utf-8")
    (global_dir / "model").mkdir()
    (global_dir / "model" / "x.gguf").write_bytes(b"gguf")
    _write_config(
        global_dir / "config.yaml",
        harnesses=[{"name": "cursor", "config": str(target)}],
    )
    return home, target, compose


def _uninstaller(
    home: Path,
    tmp_path: Path,
    *,
    prompts: ScriptedPrompter | None = None,
    runner: FakeRunner | None = None,
    **options,
) -> uninstall.Uninstaller:
    return uninstall.Uninstaller(
        home=home,
        prompts=prompts or ScriptedPrompter(),
        runner=runner or FakeRunner(),
        platform="win32",
        **options,
    )


def test_uninstall_removes_everything_the_install_created(tmp_path: Path) -> None:
    home, target, compose = _prepare(tmp_path)
    runner = FakeRunner()

    code = _uninstaller(home, tmp_path, runner=runner, assume_yes=True).run()

    assert code == 0
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document == {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}
    assert not list(target.parent.glob("mcp.json.bak.*"))
    assert not (home / ".simple-ci").exists()
    assert ["docker", "compose", "-f", str(compose), "down", "--remove-orphans"] in (
        runner.calls
    )


def test_keep_models_leaves_the_cache_and_the_global_directory(
    tmp_path: Path,
) -> None:
    home, _target, _compose = _prepare(tmp_path)

    code = _uninstaller(home, tmp_path, assume_yes=True, keep_models=True).run()

    assert code == 0
    assert (home / ".simple-ci" / "model" / "x.gguf").is_file()
    assert not (home / ".simple-ci" / "config.yaml").exists()
    assert not (home / ".simple-ci" / "docker").exists()


def test_dry_run_deletes_nothing_and_runs_no_commands(tmp_path: Path) -> None:
    home, target, _compose = _prepare(tmp_path)
    runner = FakeRunner()

    code = _uninstaller(
        home, tmp_path, runner=runner, assume_yes=True, dry_run=True
    ).run()

    assert code == 0
    assert (home / ".simple-ci" / "config.yaml").is_file()
    assert (home / ".simple-ci" / "docker" / "docker-compose.yml").is_file()
    assert (home / ".simple-ci" / "model" / "x.gguf").is_file()
    assert target.is_file()
    # `uv tool dir` is a read-only probe; nothing may actually change state.
    assert all(call[1:3] == ["tool", "dir"] for call in runner.calls)


def test_declining_the_prompt_changes_nothing(tmp_path: Path) -> None:
    home, target, _compose = _prepare(tmp_path)
    prompts = ScriptedPrompter(yes=[False])

    code = _uninstaller(home, tmp_path, prompts=prompts).run()

    assert code == 0
    assert "Cancelled." in prompts.messages
    assert (home / ".simple-ci" / "config.yaml").is_file()
    assert target.is_file()


def test_a_missing_install_is_a_no_op(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    prompts = ScriptedPrompter()

    code = _uninstaller(home, tmp_path, prompts=prompts, assume_yes=True).run()

    assert code == 0
    assert "Nothing to remove." in prompts.messages


def test_a_config_that_only_held_the_entry_is_deleted_with_its_directory(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = home / ".config" / "opencode" / "opencode.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({"mcp": {"servers": {SERVER: {"type": "local"}}}}),
        encoding="utf-8",
    )
    _write_config(
        home / ".simple-ci" / "config.yaml",
        harnesses=[{"name": "opencode", "config": str(target)}],
    )

    code = _uninstaller(
        home, tmp_path, runner=FakeRunner(docker=False), assume_yes=True
    ).run()

    assert code == 0
    assert not target.exists()
    assert not (home / ".config").exists()


def test_codex_marker_block_is_removed_and_the_rest_survives(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = home / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text(
        'model = "gpt-5"\n\n'
        "# >>> simple-code-indexer >>>\n"
        '[mcp_servers."simple-code-indexer"]\n'
        'command = "python"\n'
        "# <<< simple-code-indexer <<<\n",
        encoding="utf-8",
    )
    _write_config(
        home / ".simple-ci" / "config.yaml",
        harnesses=[{"name": "codex", "config": str(target)}],
    )

    code = _uninstaller(
        home, tmp_path, runner=FakeRunner(docker=False), assume_yes=True
    ).run()

    assert code == 0
    text = target.read_text(encoding="utf-8")
    assert text == 'model = "gpt-5"\n'
    assert "mcp_servers" not in tomllib.loads(text)


def test_a_recorded_config_that_is_gone_is_tolerated(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_config(
        home / ".simple-ci" / "config.yaml",
        harnesses=[{"name": "cursor", "config": str(home / ".cursor" / "mcp.json")}],
    )
    prompts = ScriptedPrompter()

    code = _uninstaller(
        home,
        tmp_path,
        prompts=prompts,
        runner=FakeRunner(docker=False),
        assume_yes=True,
    ).run()

    assert code == 0
    assert any("is gone already" in message for message in prompts.messages)


def test_docker_unavailable_still_deletes_the_docker_assets(tmp_path: Path) -> None:
    home, _target, _compose = _prepare(tmp_path)
    prompts = ScriptedPrompter()

    code = _uninstaller(
        home,
        tmp_path,
        prompts=prompts,
        runner=FakeRunner(docker=False),
        assume_yes=True,
    ).run()

    assert code == 0
    assert any("Docker is not running" in message for message in prompts.messages)
    assert not (home / ".simple-ci").exists()


def test_a_failed_harness_edit_keeps_the_record_for_a_retry(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = home / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")
    config = home / ".simple-ci" / "config.yaml"
    _write_config(config, harnesses=[{"name": "cursor", "config": str(target)}])
    prompts = ScriptedPrompter()

    code = _uninstaller(
        home,
        tmp_path,
        prompts=prompts,
        runner=FakeRunner(docker=False),
        assume_yes=True,
    ).run()

    assert code == 1
    assert config.is_file()
    assert any("Could not update" in message for message in prompts.messages)


def test_keep_models_requires_uninstall() -> None:
    with pytest.raises(SystemExit):
        wizard_run(["--keep-models"])


def test_uninstall_rejects_install_only_flags() -> None:
    with pytest.raises(SystemExit):
        wizard_run(["--uninstall", "--vector-store", "faiss"])
