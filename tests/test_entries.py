"""The harness-entry ladder: client CLI, then config merge, then global."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from simple_code_indexer.harnesses import Scope, load_harnesses
from simple_code_indexer.setup_wizard import entries
from simple_code_indexer.setup_wizard.provision import CommandResult, Runner

SERVER = "simple-code-indexer"


class RecordingRunner(Runner):
    """A runner that reports only the binaries a test allows and records argv."""

    def __init__(
        self,
        *,
        on_path: dict[str, str] | None = None,
        results: dict[tuple[str, ...], CommandResult] | None = None,
        writes: dict[Path, dict[str, object]] | None = None,
    ) -> None:
        self.on_path = on_path or {}
        self.results = results or {}
        self.writes = writes or {}
        self.calls: list[tuple[list[str], Path | None]] = []

    def which(self, name: str) -> str | None:
        return self.on_path.get(name)

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = 15.0,
        cwd: Path | None = None,
    ) -> CommandResult:
        self.calls.append((list(argv), cwd))
        # Stand in for a client that writes its own config file.
        for target, document in self.writes.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(document), encoding="utf-8")
        for prefix, result in self.results.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return result
        return CommandResult(0)


def _spec(name: str):
    return next(spec for spec in load_harnesses(user_dirs=[]) if spec.name == name)


def _command(tmp_path: Path) -> list[str]:
    return [
        str(tmp_path / "tool" / "bin" / "python"),
        "-m",
        "simple_code_indexer",
        "serve",
    ]


def _messages() -> tuple[list[str], Callable[[str], None]]:
    said: list[str] = []
    return said, said.append


def test_the_cli_writes_the_entry_when_it_is_on_path(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    said, say = _messages()
    runner = RecordingRunner(on_path={"cursor": "/usr/bin/cursor"})
    target = workspace / ".cursor" / "mcp.json"
    command = _command(tmp_path)

    def fake_cli_add(
        scope: str, ws: Path, name: str, argv: list[str], entry: dict
    ) -> list[str]:
        del scope, ws, entry
        return ["cursor", "mcp", "add", name, "--", *argv]

    # Cursor ships no CLI; give it one so the CLI rung is exercised on its own.
    spec = replace(_spec("cursor"), cli_add=fake_cli_add, cli_binaries=("cursor",))
    runner.writes[target] = {
        "mcpServers": {
            SERVER: {
                "command": command[0],
                "args": [*command[1:], "--workspace", str(workspace)],
            }
        }
    }

    outcome = entries.install_entry(
        spec,
        scope=Scope.PROJECT,
        workspace=workspace,
        home=home,
        server_name=SERVER,
        command=command,
        env={},
        runner=runner,
        dry_run=False,
        say=say,
        target=target,
    )

    assert outcome.kind == entries.VIA_CLI
    assert runner.calls and runner.calls[0][1] == workspace
    assert outcome.detail.startswith("added with cursor mcp add")
    assert said == []


def test_a_missing_cli_merges_the_config_instead(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _said, say = _messages()
    runner = RecordingRunner()
    spec = _spec("cursor")
    target = workspace / ".cursor" / "mcp.json"

    outcome = entries.install_entry(
        spec,
        scope=Scope.PROJECT,
        workspace=workspace,
        home=home,
        server_name=SERVER,
        command=_command(tmp_path),
        env={},
        runner=runner,
        dry_run=False,
        say=say,
        target=target,
    )

    assert outcome.kind == entries.VIA_CONFIG
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["mcpServers"][SERVER]["args"][-2:] == [
        "--workspace",
        str(workspace),
    ]
    assert runner.calls == []


def test_a_failing_cli_falls_back_and_says_why(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    said, say = _messages()
    runner = RecordingRunner(
        on_path={"claude": "/usr/bin/claude"},
        results={("/usr/bin/claude",): CommandResult(2, "", "not logged in")},
    )
    spec = _spec("claude_code")
    target = workspace / ".mcp.json"

    outcome = entries.install_entry(
        spec,
        scope=Scope.PROJECT,
        workspace=workspace,
        home=home,
        server_name=SERVER,
        command=_command(tmp_path),
        env={},
        runner=runner,
        dry_run=False,
        say=say,
        target=target,
    )

    assert outcome.kind == entries.VIA_CONFIG
    assert any("not logged in" in message for message in said)
    assert target.is_file()
    # The CLI is run at the path `which` resolved, not the bare name.
    assert runner.calls and runner.calls[0][0][0] == "/usr/bin/claude"


def test_a_dry_run_writes_nothing_and_shows_the_pin(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _said, say = _messages()
    runner = RecordingRunner()
    target = workspace / ".cursor" / "mcp.json"

    outcome = entries.install_entry(
        _spec("cursor"),
        scope=Scope.PROJECT,
        workspace=workspace,
        home=home,
        server_name=SERVER,
        command=_command(tmp_path),
        env={},
        runner=runner,
        dry_run=True,
        say=say,
        target=target,
    )

    assert outcome.kind == entries.VIA_CONFIG
    assert not target.exists()
    assert runner.calls == []
    assert str(workspace) in outcome.detail


def test_a_client_without_project_support_writes_its_global_entry(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _said, say = _messages()
    runner = RecordingRunner()

    outcome = entries.install_entry(
        _spec("goose"),
        scope=Scope.PROJECT,
        workspace=workspace,
        home=home,
        server_name=SERVER,
        command=_command(tmp_path),
        env={},
        runner=runner,
        dry_run=False,
        say=say,
    )

    assert outcome.scope == Scope.GLOBAL
    assert outcome.fell_back_to_global
    assert outcome.path is not None and outcome.path.is_file()
    assert str(workspace) not in outcome.path.read_text(encoding="utf-8")


def test_verify_requires_a_pin_on_a_project_entry(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    spec = _spec("cursor")
    path = workspace / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True)
    pinned = [*_command(tmp_path), "--workspace", str(workspace)]

    def write(command: list[str]) -> None:
        path.write_text(
            json.dumps(
                {"mcpServers": {SERVER: {"command": command[0], "args": command[1:]}}}
            ),
            encoding="utf-8",
        )

    write(_command(tmp_path))
    assert "not pinned" in (
        entries.verify(spec, path, Scope.PROJECT, SERVER, workspace) or ""
    )

    write(pinned)
    assert entries.verify(spec, path, Scope.PROJECT, SERVER, workspace) is None
    assert "pinned" in (
        entries.verify(spec, path, Scope.GLOBAL, SERVER, workspace) or ""
    )


def test_verify_reports_a_missing_entry(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()

    reason = entries.verify(
        _spec("cursor"),
        workspace / ".cursor" / "mcp.json",
        Scope.GLOBAL,
        SERVER,
        workspace,
    )

    assert reason is not None and "no" in reason


def test_remove_uses_the_recorded_file(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _said, say = _messages()
    target = workspace / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({"mcpServers": {SERVER: {"command": "x"}}, "other": 1}),
        encoding="utf-8",
    )

    outcome = entries.remove_entry(
        _spec("cursor"),
        scope=Scope.PROJECT,
        workspace=workspace,
        home=home,
        server_name=SERVER,
        runner=RecordingRunner(),
        dry_run=False,
        say=say,
        target=target,
    )

    assert outcome.kind == entries.VIA_CONFIG
    assert json.loads(target.read_text(encoding="utf-8")) == {"other": 1}


def test_a_windows_cmd_shim_is_run_through_cmd(tmp_path: Path) -> None:
    """`shutil.which("cursor")` finds `cursor.cmd`, which subprocess cannot exec.

    The ladder must route a batch shim through `cmd /c`, or every Windows
    client that ships one (Cursor, VS Code, npm CLIs) silently falls back.
    """
    from simple_code_indexer.setup_wizard import entries as entries_mod

    if os.name != "nt":
        pytest.skip("Windows shim routing only applies on Windows")

    routed = entries_mod._spawnable(["C:/tools/cursor.cmd", "--add-mcp", "{}"])

    assert routed[0].lower().endswith("cmd.exe") or "cmd" in routed[0].lower()
    assert routed[1] == "/c"
    assert routed[2] == "C:/tools/cursor.cmd"
    assert entries_mod._spawnable(["C:/tools/cursor.exe"]) == ["C:/tools/cursor.exe"]


def test_removing_an_absent_entry_is_not_an_error(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    _said, say = _messages()

    outcome = entries.remove_entry(
        _spec("cursor"),
        scope=Scope.GLOBAL,
        workspace=workspace,
        home=tmp_path / "home",
        server_name=SERVER,
        runner=RecordingRunner(),
        dry_run=False,
        say=say,
    )

    assert outcome.kind == entries.NOT_WRITTEN


def test_a_cli_that_writes_elsewhere_is_recorded_at_its_own_file(
    tmp_path: Path,
) -> None:
    """Cursor's CLI edits the profile settings, so that is the path to record.

    Recording `~/.cursor/mcp.json` instead would leave the real entry
    unremovable: a later deselect would clean up a file the CLI never touched.
    """
    workspace = tmp_path / "project"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    settings = home / "AppData" / "Roaming" / "Cursor" / "User" / "settings.json"
    _said, say = _messages()
    runner = RecordingRunner(on_path={"cursor": "/usr/bin/cursor"})
    runner.writes[settings] = {
        "mcp": {"servers": {SERVER: {"command": "x", "args": ["serve"]}}}
    }
    spec = _spec("cursor")

    outcome = entries.install_entry(
        spec,
        scope=Scope.GLOBAL,
        workspace=workspace,
        home=home,
        server_name=SERVER,
        command=_command(tmp_path),
        env={},
        runner=runner,
        dry_run=False,
        say=say,
    )

    assert outcome.kind == entries.VIA_CLI
    assert outcome.path == settings
    assert outcome.detail.startswith("added with cursor --add-mcp")


def test_a_recorded_target_elsewhere_disables_the_cli(tmp_path: Path) -> None:
    """A repin of a recorded entry must edit that file, not the CLI's profile.

    Without this guard, `--install-only` on a Cursor record would run
    `cursor --add-mcp` and edit the real profile settings instead of the
    recorded `~/.cursor/mcp.json`.
    """
    workspace = tmp_path / "project"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _said, say = _messages()
    recorded = home / ".cursor" / "mcp.json"
    recorded.parent.mkdir(parents=True)
    recorded.write_text('{"mcpServers": {}}', encoding="utf-8")
    runner = RecordingRunner(on_path={"cursor": "/usr/bin/cursor"})

    outcome = entries.install_entry(
        _spec("cursor"),
        scope=Scope.GLOBAL,
        workspace=workspace,
        home=home,
        server_name=SERVER,
        command=_command(tmp_path),
        env={},
        runner=runner,
        dry_run=False,
        say=say,
        target=recorded,
    )

    assert outcome.kind == entries.VIA_CONFIG
    assert outcome.path == recorded
    assert runner.calls == []
    document = json.loads(recorded.read_text(encoding="utf-8"))
    assert SERVER in document["mcpServers"]


def test_a_dry_run_never_touches_the_cli_target(tmp_path: Path) -> None:
    """A dry run names the file the CLI would write, but writes nothing."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    _said, say = _messages()
    settings = home / "AppData" / "Roaming" / "Cursor" / "User" / "settings.json"
    runner = RecordingRunner(on_path={"cursor": "/usr/bin/cursor"})

    outcome = entries.install_entry(
        _spec("cursor"),
        scope=Scope.GLOBAL,
        workspace=workspace,
        home=home,
        server_name=SERVER,
        command=_command(tmp_path),
        env={},
        runner=runner,
        dry_run=True,
        say=say,
    )

    assert outcome.kind == entries.VIA_CLI
    assert outcome.path == settings
    assert outcome.detail.startswith("Would run: cursor --add-mcp")
    assert runner.calls == []
    assert not settings.exists()
