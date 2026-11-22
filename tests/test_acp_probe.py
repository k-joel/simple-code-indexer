from __future__ import annotations

import json
from pathlib import Path

import pytest

import acp_probe
from simple_code_indexer.harnesses import load_harnesses


@pytest.fixture(autouse=True)
def _isolated_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the developer's real OpenCode/MCP config."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))


def _spec(name: str):
    return next(spec for spec in load_harnesses(user_dirs=[]) if spec.name == name)


def _tool_env(tmp_path: Path) -> Path:
    env = tmp_path / "tools" / "simple-code-indexer"
    (env / "Scripts").mkdir(parents=True)
    (env / "Scripts" / "pythonw.exe").write_text("", encoding="utf-8")
    return env


def _entry(command: list[str]) -> dict[str, object]:
    return {"type": "local", "command": command, "codemode": False}


def _opencode_config(home: Path, entry: dict[str, object]) -> Path:
    config = home / ".config" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps({"mcp": {"servers": {acp_probe.SERVER_NAME: entry}}}),
        encoding="utf-8",
    )
    return config


def _commandcode_config(home: Path, entry: dict[str, object]) -> Path:
    config = home / ".commandcode" / "mcp.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps({"mcpServers": {acp_probe.SERVER_NAME: entry}}),
        encoding="utf-8",
    )
    return config


def test_harness_plugin_maps_the_agent_binary() -> None:
    opencode = r"C:\Programs\ai.opencode.desktop\resources\opencode-cli.exe"
    opencode_spec = acp_probe._harness_plugin(opencode)
    commandcode_spec = acp_probe._harness_plugin("/usr/local/bin/cmdc")

    assert opencode_spec is not None and opencode_spec.name == "opencode"
    assert commandcode_spec is not None and commandcode_spec.name == "commandcode"
    assert acp_probe._harness_plugin("/opt/unknown-agent") is None


def test_configured_entry_is_read_from_a_dotted_root_key(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config = _opencode_config(home, _entry(["x"]))

    path, entry = acp_probe._configured_entry(_spec("opencode"), tmp_path, home)

    assert path == config
    assert entry == _entry(["x"])


def test_configured_entry_prefers_the_global_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    global_config = _opencode_config(home, _entry(["global"]))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "opencode.json").write_text(
        json.dumps({"mcp": {"servers": {acp_probe.SERVER_NAME: _entry(["local"])}}}),
        encoding="utf-8",
    )

    path, entry = acp_probe._configured_entry(_spec("opencode"), workspace, home)

    assert path == global_config
    assert entry == _entry(["global"])


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (["pythonw.exe", "-m", "simple_code_indexer", "serve"], True),
        (["pythonw.exe", "-m", "simple_code_indexer"], False),
        (["python.exe", "run_server.py"], False),
        (
            ["pythonw.exe", "-m", "simple_code_indexer", "serve", "--workspace", "/w"],
            True,
        ),
        (
            ["pythonw.exe", "-m", "simple_code_indexer", "serve", "--workspace"],
            False,
        ),
    ],
)
def test_launches_install_requires_the_documented_argv(
    tmp_path: Path, command: list[str], expected: bool
) -> None:
    env = _tool_env(tmp_path)
    resolved = [str(env / "Scripts" / command[0]), *command[1:]]

    assert acp_probe._launches_install(_entry(resolved), env) is expected


def test_launches_install_rejects_an_interpreter_outside_the_tool_env(
    tmp_path: Path,
) -> None:
    env = _tool_env(tmp_path)
    stale = tmp_path / "old" / "pythonw.exe"

    assert (
        acp_probe._launches_install(
            _entry([str(stale), "-m", "simple_code_indexer", "serve"]), env
        )
        is False
    )


def test_preflight_fails_fast_for_a_harness_that_ignores_injection(
    tmp_path: Path,
) -> None:
    env = _tool_env(tmp_path)
    checks: list[dict[str, object]] = []

    def check(label: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": label, "pass": passed, "detail": detail})

    passed = acp_probe._preflight_entry(
        _spec("opencode"), tmp_path, env, check, home=tmp_path / "home"
    )

    assert passed is False
    assert checks == [
        {
            "check": "OpenCode configured entry launches this tool environment",
            "pass": False,
            "detail": "no 'simple-code-indexer' entry under mcp.servers",
        }
    ]


def test_preflight_accepts_the_configured_entry_that_launches_the_install(
    tmp_path: Path,
) -> None:
    env = _tool_env(tmp_path)
    home = tmp_path / "home"
    _opencode_config(
        home,
        _entry(
            [str(env / "Scripts" / "pythonw.exe"), "-m", "simple_code_indexer", "serve"]
        ),
    )
    checks: list[dict[str, object]] = []

    def check(label: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": label, "pass": passed, "detail": detail})

    assert (
        acp_probe._preflight_entry(_spec("opencode"), tmp_path, env, check, home=home)
        is True
    )
    assert [item["pass"] for item in checks] == [True]


def test_preflight_only_reports_a_stale_entry_when_injection_is_honoured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = _tool_env(tmp_path)
    home = tmp_path / "home"
    config = _commandcode_config(
        home, _entry(["C:\\old-install\\pythonw.exe", "serve"])
    )
    checks: list[dict[str, object]] = []

    def check(label: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": label, "pass": passed, "detail": detail})

    passed = acp_probe._preflight_entry(
        _spec("commandcode"), tmp_path, env, check, home=home
    )

    assert passed is True
    assert checks == []
    assert f"configured entry (global): {config}" in capsys.readouterr().out


def _project_opencode_config(workspace: Path, entry: dict[str, object]) -> Path:
    config = workspace / "opencode.json"
    config.write_text(
        json.dumps({"mcp": {"servers": {acp_probe.SERVER_NAME: entry}}}),
        encoding="utf-8",
    )
    return config


def test_a_project_entry_pins_the_workspace_and_is_accepted(tmp_path: Path) -> None:
    env = _tool_env(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    pinned = [
        str(env / "Scripts" / "pythonw.exe"),
        "-m",
        "simple_code_indexer",
        "serve",
        "--workspace",
        str(workspace),
    ]
    _project_opencode_config(workspace, _entry(pinned))
    checks: list[dict[str, object]] = []

    def check(label: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": label, "pass": passed, "detail": detail})

    passed = acp_probe._preflight_entry(
        _spec("opencode"), workspace, env, check, home=tmp_path / "home"
    )

    assert passed is True
    assert all(item["pass"] for item in checks)


def test_a_pin_pointing_elsewhere_fails_the_preflight(tmp_path: Path) -> None:
    env = _tool_env(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    pinned = [
        str(env / "Scripts" / "pythonw.exe"),
        "-m",
        "simple_code_indexer",
        "serve",
        "--workspace",
        str(other),
    ]
    _project_opencode_config(workspace, _entry(pinned))
    checks: list[dict[str, object]] = []

    def check(label: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": label, "pass": passed, "detail": detail})

    passed = acp_probe._preflight_entry(
        _spec("opencode"), workspace, env, check, home=tmp_path / "home"
    )

    assert passed is False
    assert checks[0]["pass"] is False
