from __future__ import annotations

import json
import tomllib
from pathlib import Path

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

    assert len(specs) >= 12
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
    assert mimo.candidates("local", tmp_path) == [
        tmp_path / ".mimocode" / "mimocode.json"
    ]


def test_windsurf_uses_the_devin_local_config(tmp_path: Path) -> None:
    windsurf = _spec("windsurf")
    home = tmp_path / "home"

    candidates = windsurf.candidates("global", tmp_path, home=home)
    assert candidates[0] == home / ".config" / "devin" / "mcp_config.json"
    assert candidates[-1] == home / ".codeium" / "windsurf" / "mcp_config.json"
    assert windsurf.candidates("local", tmp_path) == [
        tmp_path / ".devin" / "mcp_config.json"
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


def test_candidates_expand_global_and_local_scopes(tmp_path: Path) -> None:
    codex = _spec("codex")

    assert codex.candidates("global", tmp_path) == [
        Path("~/.codex/config.toml").expanduser()
    ]
    assert codex.candidates("local", tmp_path) == [tmp_path / ".codex" / "config.toml"]


def test_candidates_use_the_supplied_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cursor = _spec("cursor")

    assert cursor.candidates("global", tmp_path, home=home) == [
        home / ".cursor" / "mcp.json"
    ]


def test_detection_uses_home_dirs(tmp_path: Path, monkeypatch) -> None:
    codex = _spec("codex")
    monkeypatch.setattr(harnesses_pkg, "_which", lambda _name: None)

    assert codex.detected(tmp_path) is False
    (tmp_path / ".codex").mkdir()
    assert codex.detected(tmp_path) is True


def test_detection_uses_binaries(tmp_path: Path, monkeypatch) -> None:
    cursor = _spec("cursor")
    monkeypatch.setattr(
        harnesses_pkg,
        "_which",
        lambda name: "/bin/cursor" if name == "cursor" else None,
    )

    assert cursor.detected(tmp_path) is True


def test_default_user_dirs_follow_the_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    assert tmp_path.resolve() / "harnesses" in default_user_harness_dirs()
