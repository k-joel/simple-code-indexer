from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from simple_code_indexer import harnesses as harnesses_pkg
from simple_code_indexer.harnesses import (
    _json,
    _toml,
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

    assert len(specs) >= 10
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
        "cline",
        "commandcode",
        "mimo",
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
    assert "enabled" not in entry


def test_cline_uses_the_dot_cline_settings_file() -> None:
    spec = _spec("cline")
    rendered = spec.render("", name=NAME, command=COMMAND, env={})

    assert spec.global_configs == ("~/.cline/data/settings/cline_mcp_settings.json",)
    entry = json.loads(rendered)["mcpServers"][NAME]
    assert entry["command"] == "uvx"
    assert entry["args"] == ["--from", "/repo", NAME]
    assert entry["disabled"] is False
    assert entry["autoApprove"] == []


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
