"""Builtin OpenCode harness plugin (`mcp.servers`, command array, environment).

`opencode mcp add` writes the project config by default and `--global` writes
`~/.config/opencode/opencode.json(c)`. OpenCode has no `enabled` key (it uses
`disabled`), so the entry must not emit one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

NAME = "opencode"
LABEL = "OpenCode"
HOME_DIRS = [
    "~/.config/opencode",
    "~/.local/share/opencode",
    "%APPDATA%/opencode",
    "%LOCALAPPDATA%/opencode",
]
BINARIES = ["opencode"]
CLI_BINARIES = ["opencode", "opencode-cli"]
GLOBAL_CONFIGS = [
    "~/.config/opencode/opencode.json",
    "~/.config/opencode/opencode.jsonc",
    "%APPDATA%/opencode/opencode.json",
    "%APPDATA%/opencode/opencode.jsonc",
    "%LOCALAPPDATA%/opencode/opencode.json",
    "%LOCALAPPDATA%/opencode/opencode.jsonc",
]
# Root `opencode.json(c)` first (the client's default), then `.opencode/`, which
# OpenCode always lets win when both exist.
LOCAL_CONFIGS = [
    "opencode.json",
    "opencode.jsonc",
    ".opencode/opencode.json",
    ".opencode/opencode.jsonc",
]
ROOT_KEY = "mcp.servers"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "local",
        "command": command,
        # A three-tool server is clearer on the native tool list than in Code Mode.
        "codemode": False,
    }
    if env:
        value["environment"] = dict(env)
    return value


def cli_add(
    scope: str,
    workspace: Path,
    name: str,
    command: list[str],
    entry: dict[str, Any],
) -> list[str] | None:
    """`opencode mcp add [--global] <name> -- <command>`.

    Project scope is the CLI's default, so no flag is needed there. `--env`
    is repeated per key; today the wizard passes none.
    """
    del workspace
    argv = ["opencode", "mcp", "add"]
    if scope == "global":
        argv.append("--global")
    elif scope != "project":
        return None
    for key, value in (entry.get("environment") or {}).items():
        argv += ["--env", f"{key}={value}"]
    argv += [name, "--", *command]
    return argv


def cli_remove(scope: str, workspace: Path, name: str) -> list[str] | None:
    del workspace
    argv = ["opencode", "mcp", "remove"]
    if scope == "global":
        argv.append("--global")
    elif scope != "project":
        return None
    return [*argv, name]
