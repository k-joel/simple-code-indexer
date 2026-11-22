"""Builtin VS Code harness plugin (`servers` key, explicit stdio type).

`code --add-mcp '<json>'` only writes the user profile, so both scopes are
written by the wizard: global `%APPDATA%/Code/User/mcp.json` and project
`.vscode/mcp.json`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

NAME = "vscode"
LABEL = "VS Code"
HOME_DIRS = ["%APPDATA%/Code", "~/.vscode", "~/.config/Code"]
BINARIES = ["code"]
GLOBAL_CONFIGS = [
    "%APPDATA%/Code/User/mcp.json",
    "~/Library/Application Support/Code/User/mcp.json",
    "~/.config/Code/User/mcp.json",
]
LOCAL_CONFIGS = [".vscode/mcp.json"]
ROOT_KEY = "servers"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "stdio",
        "command": command[0],
    }
    if len(command) > 1:
        value["args"] = command[1:]
    if env:
        value["env"] = env
    return value


def cli_add(
    scope: str,
    workspace: Path,
    name: str,
    command: list[str],
    entry: dict[str, Any],
) -> list[str] | None:
    """Always None: `code --add-mcp` is user-profile only.

    Returning None sends every scope to the wizard's file merge, which keeps
    the pinned project entry in the workspace where it belongs.
    """
    del scope, workspace, name, command, entry
    return None
