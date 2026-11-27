from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from simple_code_indexer import harnesses as harnesses_pkg
from simple_code_indexer.harnesses import (
    _json,
    _toml,
    _yaml,
    default_user_harness_dirs,
    load_harnesses,
)
from simple_code_indexer.harnesses._probe import Detection

COMMAND = ["uvx", "--from", "/repo", "simple-code-indexer"]
NAME = "simple-code-indexer"


def _write(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def _spec(name: str):
    return next(spec for spec in load_harnesses(user_dirs=[]) if spec.name == name)


def test_builtin_harnesses_load() -> None:
    specs = load_harnesses(user_dirs=[])
    names = {spec.name for spec in specs}

    assert len(specs) >= 17
    assert {
        "claude_code",
        "claude_desktop",
        "codex",
        "gemini_cli",
        "opencode",
        "cursor",
        "windsurf",
        "vscode",
        "zed",
        "commandcode",
        "mimo",
        "goose",
        "pi",
        "hermes",
        "openclaw",
        "kilo",
        "cline",
    } <= names


def test_user_plugin_registers_and_overrides_by_name(tmp_path: Path) -> None:
    user = tmp_path / "harnesses"
    _write(
        user,
        "custom.py",
        'NAME = "custom"\nLABEL = "Custom"\n'
        'GLOBAL_CONFIGS = ["~/custom.json"]\nROOT_KEY = "mcpServers"\n',
    )
    specs = load_harnesses(user_dirs=[user])
    assert next(spec for spec in specs if spec.name == "custom").label == "Custom"

    _write(
        user,
        "claude_code.py",
        'NAME = "claude_code"\nLABEL = "Overridden"\n'
        'GLOBAL_CONFIGS = ["~/mine.json"]\nROOT_KEY = "mcpServers"\n',
    )
    overridden = next(
        spec for spec in load_harnesses(user_dirs=[user]) if spec.name == "claude_code"
    )
    assert overridden.label == "Overridden"
    assert overridden.global_configs == ("~/mine.json",)


def test_bad_plugins_are_skipped(tmp_path: Path) -> None:
    user = tmp_path / "harnesses"
    _write(user, "broken.py", "def broken(:\n")
    _write(user, "nameless.py", 'LABEL = "x"\n')
    _write(user, "noroot.py", 'NAME = "noroot"\nGLOBAL_CONFIGS = ["~/x.json"]\n')
    _write(
        user,
        "good.py",
        'NAME = "good"\nGLOBAL_CONFIGS = ["~/good.json"]\nROOT_KEY = "mcpServers"\n',
    )

    names = {spec.name for spec in load_harnesses(user_dirs=[user])}

    assert "good" in names
    assert {"nameless", "noroot"}.isdisjoint(names)


def test_json_upsert_preserves_unrelated_content() -> None:
    existing = '{"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}'
    updated = _json.upsert(
        existing,
        root_key="mcpServers",
        name=NAME,
        entry={"command": "uvx", "args": ["--from", "/repo", NAME]},
    )

    document = json.loads(updated)
    assert document["theme"] == "dark"
    assert document["mcpServers"]["other"] == {"command": "x"}
    assert document["mcpServers"][NAME]["command"] == "uvx"
    assert (
        _json.upsert(
            updated,
            root_key="mcpServers",
            name=NAME,
            entry={"command": "uvx", "args": ["--from", "/repo", NAME]},
        )
        == updated
    )


def test_json_upsert_supports_a_dotted_root_key() -> None:
    updated = _json.upsert(
        '{"mcp": {"servers": {"other": {"type": "local"}}}}',
        root_key="mcp.servers",
        name=NAME,
        entry={"type": "local"},
    )

    document = json.loads(updated)
    assert document["mcp"]["servers"]["other"] == {"type": "local"}
    assert document["mcp"]["servers"][NAME] == {"type": "local"}


def test_jsonc_comments_and_trailing_commas_are_tolerated() -> None:
    existing = '{\n  // a comment\n  "mcp": {},\n  /* block */\n}\n'
    updated = _json.upsert(existing, root_key="mcp", name=NAME, entry={"enabled": True})

    assert json.loads(updated)["mcp"][NAME] == {"enabled": True}


def test_unparseable_json_raises() -> None:
    with pytest.raises(_json.ParseError):
        _json.upsert("{not json", root_key="mcpServers", name=NAME, entry={})


def test_json_remove_keeps_unrelated_content_and_prunes_the_root() -> None:
    existing = (
        '{"mcpServers": {"other": {"command": "x"}, '
        '"simple-code-indexer": {"command": "y"}}, "theme": "dark"}'
    )

    updated = _json.remove(existing, root_key="mcpServers", name=NAME)

    assert updated is not None
    document = json.loads(updated)
    assert document == {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}
    assert _json.remove(updated, root_key="mcpServers", name=NAME) is None


def test_json_remove_prunes_an_emptied_dotted_root() -> None:
    updated = _json.remove(
        '{"mcp": {"servers": {"simple-code-indexer": {}}}, "x": 1}',
        root_key="mcp.servers",
        name=NAME,
    )

    assert updated is not None
    assert json.loads(updated) == {"x": 1}


def test_json_remove_of_the_only_entry_is_empty() -> None:
    assert (
        _json.remove(
            '{"mcpServers": {"simple-code-indexer": {}}}',
            root_key="mcpServers",
            name=NAME,
        )
        == ""
    )


def test_toml_remove_strips_only_the_marker_block() -> None:
    existing = 'model = "gpt-5"\n\n[other]\nkey = "value"\n'
    installed = _toml.upsert(existing, name=NAME, command=COMMAND, env={})

    removed = _toml.remove(installed, name=NAME)

    assert removed == existing
    assert _toml.remove(removed, name=NAME) is None


def test_spec_remove_round_trips_upsert() -> None:
    cursor = _spec("cursor")
    installed = cursor.render('{"theme": "dark"}', name=NAME, command=COMMAND, env={})
    removed = cursor.remove(installed, name=NAME)
    assert removed is not None
    assert json.loads(removed) == {"theme": "dark"}

    codex = _spec("codex")
    installed = codex.render('model = "gpt-5"\n', name=NAME, command=COMMAND, env={})
    removed = codex.remove(installed, name=NAME)
    assert removed is not None
    assert tomllib.loads(removed) == {"model": "gpt-5"}


def test_toml_block_is_idempotent_and_valid() -> None:
    existing = 'model = "gpt-5"\n\n[other]\nkey = "value"\n'
    once = _toml.upsert(existing, name=NAME, command=COMMAND, env={"A": "b"})
    twice = _toml.upsert(once, name=NAME, command=COMMAND, env={"A": "b"})

    assert once == twice
    assert 'model = "gpt-5"' in once
    assert "[other]" in once
    assert once.count('[mcp_servers."simple-code-indexer"]') == 1
    parsed = tomllib.loads(once)
    assert parsed["mcp_servers"][NAME]["command"] == "uvx"
    assert parsed["mcp_servers"][NAME]["args"] == ["--from", "/repo", NAME]
    assert parsed["mcp_servers"][NAME]["env"] == {"A": "b"}
    assert parsed["mcp_servers"][NAME]["startup_timeout_sec"] == 120


def test_vscode_entry_shape() -> None:
    spec = _spec("vscode")
    rendered = spec.render("", name=NAME, command=COMMAND, env={})

    assert json.loads(rendered)["servers"][NAME] == {
        "type": "stdio",
        "command": "uvx",
        "args": ["--from", "/repo", NAME],
    }


def test_opencode_entry_shape() -> None:
    spec = _spec("opencode")
    rendered = spec.render("", name=NAME, command=COMMAND, env={"K": "V"})

    entry = json.loads(rendered)["mcp"]["servers"][NAME]
    assert entry["type"] == "local"
    assert entry["command"] == COMMAND
    assert entry["environment"] == {"K": "V"}
    assert entry["codemode"] is False
    assert "cwd" not in entry
    assert "enabled" not in entry


def test_mimo_global_paths_cover_xdg_and_appdata(tmp_path: Path) -> None:
    mimo = _spec("mimo")
    home = tmp_path / "home"

    assert mimo.candidates("global", tmp_path, home=home)[0] == (
        home / ".config" / "mimocode" / "mimocode.json"
    )
    # `.jsonc` first: an existing commented config is the one the client loads.
    assert mimo.candidates("project", tmp_path) == [
        tmp_path / ".mimocode" / "mimocode.jsonc",
        tmp_path / ".mimocode" / "mimocode.json",
    ]


def test_windsurf_uses_the_devin_local_config(tmp_path: Path) -> None:
    windsurf = _spec("windsurf")
    home = tmp_path / "home"

    candidates = windsurf.candidates("global", tmp_path, home=home)
    assert candidates[0] == home / ".config" / "devin" / "mcp_config.json"
    assert candidates[-1] == home / ".codeium" / "windsurf" / "mcp_config.json"
    assert windsurf.candidates("project", tmp_path) == [
        tmp_path / ".devin" / "mcp_config.json",
        tmp_path / ".devin" / "mcp_config.local.json",
    ]


def test_zed_uses_context_servers_without_a_type() -> None:
    spec = _spec("zed")
    rendered = spec.render("", name=NAME, command=COMMAND, env={})

    entry = json.loads(rendered)["context_servers"][NAME]
    assert entry == {"command": "uvx", "args": ["--from", "/repo", NAME]}


def test_goose_entry_shape_and_yaml_merge() -> None:
    spec = _spec("goose")
    existing = (
        "active_provider: anthropic\nextensions:\n  developer:\n    type: builtin\n"
    )
    rendered = spec.render(
        existing,
        name=NAME,
        command=COMMAND,
        env={"WORKSPACE_ROOT": "D:\\repo", "K": "V"},
    )

    document = yaml.safe_load(rendered)
    assert document["active_provider"] == "anthropic"
    assert document["extensions"]["developer"] == {"type": "builtin"}
    entry = document["extensions"][NAME]
    assert entry["type"] == "stdio"
    assert entry["name"] == NAME
    assert entry["cmd"] == "uvx"
    assert entry["args"] == ["--from", "/repo", NAME]
    assert entry["envs"] == {"WORKSPACE_ROOT": "D:\\repo", "K": "V"}
    assert "cwd" not in entry
    assert entry["enabled"] is True
    assert entry["timeout"] == 300


def test_goose_remove_round_trips_yaml() -> None:
    spec = _spec("goose")
    existing = "active_provider: anthropic\n"
    installed = spec.render(existing, name=NAME, command=COMMAND, env={})
    removed = spec.remove(installed, name=NAME)

    assert removed is not None
    assert yaml.safe_load(removed) == {"active_provider": "anthropic"}
    assert spec.remove(removed, name=NAME) is None


def test_yaml_upsert_is_idempotent_and_rejects_bad_documents() -> None:
    once = _yaml.upsert(
        "extensions: {}\n", root_key="extensions", name=NAME, entry={"type": "stdio"}
    )
    twice = _yaml.upsert(
        once, root_key="extensions", name=NAME, entry={"type": "stdio"}
    )
    assert once == twice

    with pytest.raises(_yaml.ParseError):
        _yaml.upsert("- not\n- a map\n", root_key="extensions", name=NAME, entry={})


def test_pi_entry_exposes_tools_directly() -> None:
    spec = _spec("pi")
    rendered = spec.render(
        '{"mcpServers": {"other": {"command": "x"}}}',
        name=NAME,
        command=COMMAND,
        env={"K": "V"},
    )

    document = json.loads(rendered)
    assert document["mcpServers"]["other"] == {"command": "x"}
    entry = document["mcpServers"][NAME]
    assert entry["command"] == "uvx"
    assert entry["args"] == ["--from", "/repo", NAME]
    assert entry["env"] == {"K": "V"}
    assert entry["exposure"] == "direct"
    assert entry["timeout"] == 120
    assert "cwd" not in entry


def test_no_harness_entry_emits_a_cwd() -> None:
    """ADR-015: a plugin must never turn an env pin into an entry `cwd`."""
    workspace = "D:\\Projects\\Python\\simple-code-indexer"
    for spec in load_harnesses(user_dirs=[]):
        rendered = spec.render(
            "", name=NAME, command=COMMAND, env={"WORKSPACE_ROOT": workspace}
        )
        assert '"cwd"' not in rendered, spec.name


def test_wizard_entries_carry_no_workspace_path() -> None:
    """ADR-015: the wizard writes install-scoped entries only (`env={}`)."""
    workspace = "D:\\Projects\\Python\\simple-code-indexer"
    for spec in load_harnesses(user_dirs=[]):
        rendered = spec.render("", name=NAME, command=COMMAND, env={})
        assert workspace not in rendered, spec.name
        assert workspace.replace("\\", "\\\\") not in rendered, spec.name
        assert "WORKSPACE_ROOT" not in rendered, spec.name


def test_commandcode_marks_the_stdio_transport() -> None:
    spec = _spec("commandcode")
    rendered = spec.render("", name=NAME, command=COMMAND, env={})

    entry = json.loads(rendered)["mcpServers"][NAME]
    assert entry["transport"] == "stdio"
    assert entry["enabled"] is True
    assert entry["command"] == "uvx"
    assert entry["args"] == ["--from", "/repo", NAME]
    # No env marker: the wizard passes `--harness commandcode` instead (ADR-024).
    assert "env" not in entry
    assert harnesses_pkg.entry_argv(entry) == COMMAND


LOCAL_CONFIGS = {
    "claude_code": [".mcp.json"],
    "commandcode": [".mcp.json"],
    "cursor": [".cursor/mcp.json"],
    "gemini_cli": [".gemini/settings.json"],
    "opencode": [
        "opencode.json",
        "opencode.jsonc",
        ".opencode/opencode.json",
        ".opencode/opencode.jsonc",
    ],
    "pi": [".pi/mcp.json"],
    "codex": [".codex/config.toml"],
    "vscode": [".vscode/mcp.json"],
    "zed": [".zed/settings.json"],
    "mimo": [".mimocode/mimocode.jsonc", ".mimocode/mimocode.json"],
    "windsurf": [".devin/mcp_config.json", ".devin/mcp_config.local.json"],
    "kilo": ["kilo.jsonc", "kilo.json", ".kilo/kilo.jsonc", ".kilo/kilo.json"],
    "goose": [],
    "claude_desktop": [],
    "hermes": [],
    "openclaw": [],
    "cline": [],
}


def test_local_config_paths_are_the_documented_ones() -> None:
    """Each client's project-scope file, verified against its own docs (ADR-022)."""
    for name, expected in LOCAL_CONFIGS.items():
        assert list(_spec(name).local_configs) == expected, name


def test_a_client_without_a_project_config_does_not_support_project_scope() -> None:
    assert not _spec("goose").supports("project")
    assert not _spec("claude_desktop").supports("project")
    assert _spec("claude_code").supports("project")
    assert _spec("goose").supports("global")


def test_pinned_command_appends_the_workspace_flag(tmp_path: Path) -> None:
    pinned = harnesses_pkg.pinned_command(COMMAND, tmp_path)

    assert pinned == [*COMMAND, "--workspace", str(tmp_path)]
    assert pinned[: len(COMMAND)] == COMMAND


def test_entry_argv_handles_every_client_shape() -> None:
    assert harnesses_pkg.entry_argv({"command": ["a", "b"]}) == ["a", "b"]
    assert harnesses_pkg.entry_argv({"command": "a", "args": ["b"]}) == ["a", "b"]
    assert harnesses_pkg.entry_argv({"cmd": "a", "args": ["b"]}) == ["a", "b"]
    assert harnesses_pkg.entry_argv({"name": "a"}) == []


def test_only_supported_clients_emit_enabled() -> None:
    """`enabled` exists where the client documents it, and nowhere else."""
    supported = {"codex", "pi", "goose", "mimo", "commandcode", "kilo"}
    for spec in load_harnesses(user_dirs=[]):
        rendered = spec.render("", name=NAME, command=COMMAND, env={})
        if spec.name in supported:
            assert "enabled" in rendered, spec.name
        else:
            assert "enabled" not in rendered, spec.name


def test_codex_enables_the_server_in_its_toml_block() -> None:
    rendered = _spec("codex").render("", name=NAME, command=COMMAND, env={})

    assert "enabled = true" in rendered
    assert tomllib.loads(rendered)["mcp_servers"][NAME]["enabled"] is True


def test_pi_enables_the_server() -> None:
    entry = json.loads(_spec("pi").render("", name=NAME, command=COMMAND, env={}))

    assert entry["mcpServers"][NAME]["enabled"] is True


def test_the_new_clients_write_their_documented_shape() -> None:
    """Hermes (YAML), OpenClaw (JSON5), Kilo (command array), Cline (mcpServers)."""
    hermes = yaml.safe_load(
        _spec("hermes").render("", name=NAME, command=COMMAND, env={})
    )
    assert hermes["mcp_servers"][NAME] == {
        "command": "uvx",
        "args": ["--from", "/repo", NAME],
    }

    openclaw = json.loads(
        _spec("openclaw").render("", name=NAME, command=COMMAND, env={})
    )
    assert openclaw["mcp"]["servers"][NAME] == {
        "command": "uvx",
        "args": ["--from", "/repo", NAME],
    }

    kilo = json.loads(_spec("kilo").render("", name=NAME, command=COMMAND, env={}))
    assert kilo["mcp"][NAME] == {
        "type": "local",
        "command": COMMAND,
        "enabled": True,
        "timeout": 120000,
    }

    cline = json.loads(_spec("cline").render("", name=NAME, command=COMMAND, env={}))
    assert cline["mcpServers"][NAME] == {
        "command": "uvx",
        "args": ["--from", "/repo", NAME],
        "disabled": False,
        "autoApprove": [],
    }


def test_a_jsonc_client_keeps_comments_it_can_parse() -> None:
    """Kilo's `~/.config/kilo/kilo.jsonc` and OpenClaw's JSON5 both comment."""
    existing = '{\n  // a comment\n  "theme": "dark",\n}\n'

    updated = _spec("kilo").render(existing, name=NAME, command=COMMAND, env={})

    document = json.loads(updated)
    assert document["theme"] == "dark"
    assert document["mcp"][NAME]["type"] == "local"


def test_cli_adapters_build_the_documented_argv(tmp_path: Path) -> None:
    """The per-client `mcp add` shapes, isolated in each plugin (ADR-022)."""
    command = [str(tmp_path / "python"), "-m", "simple_code_indexer", "serve"]
    pinned = harnesses_pkg.pinned_command(command, tmp_path)
    cases = {
        "claude_code": (
            ["claude", "mcp", "add", "-s", "user", NAME, "--", *command],
            ["claude", "mcp", "add", "-s", "project", NAME, "--", *pinned],
        ),
        "gemini_cli": (
            ["gemini", "mcp", "add", "--scope", "user", NAME, *command],
            ["gemini", "mcp", "add", "--scope", "project", NAME, *pinned],
        ),
        "opencode": (
            ["opencode", "mcp", "add", "--global", NAME, "--", *command],
            ["opencode", "mcp", "add", NAME, "--", *pinned],
        ),
        "pi": (
            ["pi", "mcp", "add", "--exposure", "direct", NAME, "--", *command],
            ["pi", "mcp", "add", "-l", "--exposure", "direct", NAME, "--", *pinned],
        ),
        "codex": (
            ["codex", "mcp", "add", NAME, "--", *command],
            None,
        ),
        # Cursor's CLI has no project flag (`--mcp-workspace` is rejected by
        # 3.31.15), so only the global scope has an argv.
        "cursor": (
            [
                "cursor",
                "--add-mcp",
                json.dumps({"name": NAME, "command": command[0], "args": command[1:]}),
            ],
            None,
        ),
        "vscode": (None, None),
        "zed": (None, None),
        "windsurf": (None, None),
        "mimo": (None, None),
        "goose": (None, None),
        "claude_desktop": (None, None),
        "kilo": (None, None),
        "hermes": (None, None),
        # OpenClaw hands its CLI the entry as one JSON object, like `cmdc`.
        "openclaw": (
            [
                "openclaw",
                "mcp",
                "set",
                NAME,
                json.dumps(_spec("openclaw").entry(command, {})),
            ],
            None,
        ),
        "cline": (
            ["cline", "mcp", "add", NAME, "--yes", "--", *command],
            None,
        ),
    }
    for name, (global_argv, project_argv) in cases.items():
        spec = _spec(name)
        if global_argv is None and project_argv is None and spec.cli_add is None:
            continue
        assert spec.cli_add is not None, name
        entry = spec.entry(command, {})
        assert spec.cli_add("global", tmp_path, NAME, command, entry) == global_argv, (
            name
        )
        entry = spec.entry(pinned, {})
        assert spec.cli_add("project", tmp_path, NAME, pinned, entry) == project_argv, (
            name
        )


def test_commandcode_hands_the_whole_entry_to_its_cli(tmp_path: Path) -> None:
    """`add-json` keeps `transport`, `enabled` and the marker the flags cannot."""
    spec = _spec("commandcode")
    assert spec.cli_add is not None
    command = [str(tmp_path / "python"), "-m", "simple_code_indexer", "serve"]
    pinned = harnesses_pkg.pinned_command(command, tmp_path)
    entry = spec.entry(pinned, {})

    argv = spec.cli_add("project", tmp_path, NAME, pinned, entry)

    assert argv is not None
    assert argv[:5] == ["cmdc", "mcp", "add-json", "--scope", "project"]
    assert argv[5] == NAME
    assert json.loads(argv[6]) == entry
    assert spec.cli_add("local", tmp_path, NAME, pinned, entry) is None


def test_a_cli_remove_names_the_recorded_scope(tmp_path: Path) -> None:
    claude = _spec("claude_code")
    pi = _spec("pi")
    codex = _spec("codex")
    assert claude.cli_remove is not None
    assert pi.cli_remove is not None
    assert codex.cli_remove is not None

    assert claude.cli_remove("project", tmp_path, NAME) == [
        "claude",
        "mcp",
        "remove",
        "-s",
        "project",
        NAME,
    ]
    assert pi.cli_remove("project", tmp_path, NAME) == [
        "pi",
        "mcp",
        "remove",
        "-l",
        NAME,
    ]
    assert codex.cli_remove("project", tmp_path, NAME) is None
    assert _spec("cursor").cli_remove is None


def test_cursor_adds_through_its_profile_cli(tmp_path: Path) -> None:
    """`cursor --add-mcp` writes the profile settings, not `.cursor/mcp.json`.

    Cursor 3.31.15 has no `mcp remove` and rejects `--mcp-workspace`, so the
    plugin exposes a CLI for the global scope only and names the file the CLI
    really edits.
    """
    cursor = _spec("cursor")
    assert cursor.cli_add is not None
    command = [str(tmp_path / "python"), "-m", "simple_code_indexer", "serve"]
    pinned = harnesses_pkg.pinned_command(command, tmp_path)

    argv = cursor.cli_add("global", tmp_path, NAME, command, cursor.entry(command, {}))

    assert argv is not None
    assert argv[:2] == ["cursor", "--add-mcp"]
    payload = json.loads(argv[2])
    assert payload == {"name": NAME, "command": command[0], "args": command[1:]}
    assert cursor.cli_add("project", tmp_path, NAME, pinned, {}) is None
    assert cursor.cli_root_key == "mcp.servers"


def test_zed_is_not_offered_as_a_cli_binary() -> None:
    """`zed` on PATH is the SpiceDB CLI (authzed), not the editor."""
    zed = _spec("zed")

    assert zed.binaries == ()
    assert zed.cli_binaries == ()
    assert zed.cli_add is None


def test_cursor_settings_file_is_never_a_merge_target() -> None:
    """A JSON merge into it would add `mcpServers` to Cursor's own settings."""
    cursor = _spec("cursor")

    for scope in ("global", "project"):
        for raw in cursor.global_configs + cursor.local_configs:
            assert "settings.json" not in raw, (scope, raw)
    assert cursor.cli_target is not None
    assert cursor.cli_target("global") == "%APPDATA%/Cursor/User/settings.json"


def _discovery(
    home: Path,
    name: str,
    *,
    pid: int,
    folders: list[str],
    ide: str = "code",
) -> None:
    directory = home / ".commandcode" / "ide"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        json.dumps(
            {
                "socketPath": "\\\\.\\pipe\\commandcode-code-b41e2d27",
                "workspaceFolders": folders,
                "pid": pid,
                "ideName": ide,
                "appName": "Visual Studio Code",
                "timestamp": 1795094441611,
            }
        ),
        encoding="utf-8",
    )


def _ancestors(monkeypatch, *rows: tuple[int, str]) -> None:
    from simple_code_indexer import parent_watch

    monkeypatch.setattr(parent_watch, "ancestor_chain", lambda *a, **k: list(rows))


def test_commandcode_resolves_the_ancestor_keyed_discovery_file(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "project"
    workspace.mkdir()
    _discovery(home, "code-b41e2d27.json", pid=4242, folders=[str(workspace)])
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    _ancestors(monkeypatch, (999, "cmd.exe"), (4242, "Code.exe"))

    resolver = _spec("commandcode").workspace_resolver
    assert resolver is not None
    assert resolver(tmp_path) == workspace.resolve()


def test_commandcode_prefers_the_nearest_matching_ancestor(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    outer = tmp_path / "outer"
    inner = tmp_path / "inner"
    outer.mkdir()
    inner.mkdir()
    _discovery(home, "code-11111111.json", pid=1000, folders=[str(outer)])
    _discovery(home, "code-22222222.json", pid=2000, folders=[str(inner)])
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    _ancestors(monkeypatch, (2000, "Code.exe"), (1000, "Code.exe"))

    resolver = _spec("commandcode").workspace_resolver
    assert resolver is not None
    assert resolver(tmp_path) == inner.resolve()


def test_commandcode_ignores_files_that_are_not_live_ancestors(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "project"
    workspace.mkdir()
    _discovery(home, "code-deadbeef.json", pid=4242, folders=[str(workspace)])
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    _ancestors(monkeypatch, (999, "cmd.exe"), (1000, "Code.exe"))

    resolver = _spec("commandcode").workspace_resolver
    assert resolver is not None
    assert resolver(tmp_path) is None


def test_commandcode_requires_the_ide_name_to_match_the_ancestor_image(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "project"
    workspace.mkdir()
    _discovery(
        home, "cursor-abcdef12.json", pid=4242, folders=[str(workspace)], ide="cursor"
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    _ancestors(monkeypatch, (4242, "Code.exe"))

    resolver = _spec("commandcode").workspace_resolver
    assert resolver is not None
    assert resolver(tmp_path) is None


def test_commandcode_skips_malformed_files_and_missing_folders(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    directory = home / ".commandcode" / "ide"
    directory.mkdir(parents=True)
    (directory / "code-broken.json").write_text("{not json", encoding="utf-8")
    workspace = tmp_path / "project"
    workspace.mkdir()
    _discovery(home, "code-ok.json", pid=4242, folders=[str(workspace)])
    _discovery(home, "code-gone.json", pid=1000, folders=[str(tmp_path / "missing")])
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    _ancestors(monkeypatch, (1000, "Code.exe"), (4242, "Code.exe"))

    resolver = _spec("commandcode").workspace_resolver
    assert resolver is not None
    assert resolver(tmp_path) == workspace.resolve()


def test_discover_workspace_requires_the_marker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(harnesses_pkg.RUNTIME_ENV, raising=False)
    assert harnesses_pkg.discover_workspace(tmp_path) is None


def test_discover_workspace_without_the_marker_asks_every_resolver(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "published"
    workspace.mkdir()
    _write(
        tmp_path / "harnesses",
        "probe.py",
        "from pathlib import Path\n"
        'NAME = "probe"\nGLOBAL_CONFIGS = ["~/probe.json"]\nROOT_KEY = "mcpServers"\n'
        f"def resolve_workspace(cwd):\n    return Path({str(workspace)!r})\n",
    )
    monkeypatch.delenv(harnesses_pkg.RUNTIME_ENV, raising=False)
    _ancestors(monkeypatch)  # the builtin resolver sees no live ancestors

    assert harnesses_pkg.discover_workspace(tmp_path) is None
    assert harnesses_pkg.discover_workspace(tmp_path, require_marker=False) == (
        workspace.resolve(),
        "probe",
    )


def test_discover_workspace_dispatches_to_the_named_plugin(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "published"
    workspace.mkdir()
    _write(
        tmp_path / "harnesses",
        "probe.py",
        "from pathlib import Path\n"
        'NAME = "probe"\nGLOBAL_CONFIGS = ["~/probe.json"]\nROOT_KEY = "mcpServers"\n'
        f"def resolve_workspace(cwd):\n    return Path({str(workspace)!r})\n",
    )
    monkeypatch.setenv(harnesses_pkg.RUNTIME_ENV, "probe")

    assert harnesses_pkg.discover_workspace(tmp_path) == (
        workspace.resolve(),
        "probe",
    )


def test_discover_workspace_is_fail_soft(tmp_path: Path, monkeypatch) -> None:
    user = tmp_path / "harnesses"
    _write(
        user,
        "boom.py",
        'NAME = "boom"\nGLOBAL_CONFIGS = ["~/boom.json"]\nROOT_KEY = "mcpServers"\n'
        "def resolve_workspace(cwd):\n    raise RuntimeError('nope')\n",
    )
    _write(
        user,
        "notdir.py",
        'NAME = "notdir"\nGLOBAL_CONFIGS = ["~/notdir.json"]\nROOT_KEY = "mcpServers"\n'
        "def resolve_workspace(cwd):\n    return cwd / 'missing'\n",
    )
    _write(
        user,
        "badhook.py",
        'NAME = "badhook"\nGLOBAL_CONFIGS = ["~/badhook.json"]\n'
        'ROOT_KEY = "mcpServers"\nresolve_workspace = 42\n',
    )

    for name in ("boom", "notdir", "unknown"):
        monkeypatch.setenv(harnesses_pkg.RUNTIME_ENV, name)
        assert harnesses_pkg.discover_workspace(tmp_path) is None

    names = {spec.name for spec in load_harnesses(user_dirs=[user])}
    assert "boom" in names
    assert "badhook" not in names


def test_default_user_dirs_accept_an_explicit_workspace(tmp_path: Path) -> None:
    assert tmp_path.resolve() / "harnesses" in default_user_harness_dirs(
        tmp_path.resolve()
    )


def test_candidates_expand_global_and_local_scopes(tmp_path: Path) -> None:
    codex = _spec("codex")

    assert codex.candidates("global", tmp_path) == [
        Path("~/.codex/config.toml").expanduser()
    ]
    assert codex.candidates("local", tmp_path) == [tmp_path / ".codex" / "config.toml"]


def test_candidates_use_the_supplied_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cursor = _spec("cursor")

    # Cursor's profile settings file is where its CLI writes, but it is not a
    # merge target: the wizard's JSON merge would put `mcpServers` into a file
    # that expects `mcp.servers`. Only `~/.cursor/mcp.json` is a config path.
    assert cursor.candidates("global", tmp_path, home=home) == [
        home / ".cursor" / "mcp.json"
    ]


class ProbeRunner:
    """A `_probe.Runnable` whose binaries answer only if `answers` names them."""

    def __init__(
        self,
        *,
        which_map: dict[str, str] | None = None,
        answers: set[str] | None = None,
        rc: int = 0,
    ) -> None:
        self.which_map = which_map or {}
        self.answers = answers or set()
        self.rc = rc
        self.calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        return self.which_map.get(name)

    def run(self, argv: list[str], *, timeout: float = 0.0, cwd=None):
        self.calls.append(list(argv))
        binary = Path(argv[0]).name.split(".")[0]
        return SimpleNamespace(returncode=self.rc if binary in self.answers else 1)


def test_detection_probes_the_client_cli(tmp_path: Path) -> None:
    runner = ProbeRunner(which_map={"codex": "/bin/codex"}, answers={"codex"})

    assert _spec("codex").detection(tmp_path, runner) == Detection(
        "cli", "codex --version"
    )
    assert runner.calls == [["/bin/codex", "--version"]]


def test_a_silent_binary_does_not_prove_an_install(tmp_path: Path) -> None:
    # On PATH but `--version` fails: the binary alone is the weak signal.
    runner = ProbeRunner(which_map={"codex": "/bin/codex"}, answers=set())

    assert _spec("codex").detection(tmp_path, runner) == Detection(
        "binary", "codex on PATH"
    )
    assert _spec("codex").detected(tmp_path, runner) is True


def test_detection_falls_back_to_the_config_directory(tmp_path: Path) -> None:
    runner = ProbeRunner()
    codex = _spec("codex")

    assert codex.detection(tmp_path, runner) is None
    (tmp_path / ".codex").mkdir()
    assert codex.detection(tmp_path, runner) == Detection("dir", "config dir .codex")


def test_a_probe_that_raises_is_never_a_cli_proof(tmp_path: Path) -> None:
    class Exploding(ProbeRunner):
        def run(self, argv, *, timeout=0.0, cwd=None):
            raise OSError("cannot execute")

    spec = _spec("codex")
    found = spec.detection(tmp_path, Exploding(which_map={"codex": "/bin/codex"}))
    # On PATH but unexecutable: the weak signal, never the strong one.
    assert found == Detection("binary", "codex on PATH")


def test_only_resolver_harnesses_need_a_harness_flag() -> None:
    with_flag = {
        spec.name for spec in load_harnesses(user_dirs=[]) if spec.workspace_resolver
    }
    assert with_flag == {"commandcode"}


def test_every_plugin_declares_a_probeable_binary_or_a_directory() -> None:
    """A plugin with neither could never be preselected — a silent regression."""
    for spec in load_harnesses(user_dirs=[]):
        assert spec.binaries or spec.home_dirs, spec.name
        if spec.binaries:
            assert spec.probe_args, spec.name


def test_default_user_dirs_follow_the_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    assert tmp_path.resolve() / "harnesses" in default_user_harness_dirs()
