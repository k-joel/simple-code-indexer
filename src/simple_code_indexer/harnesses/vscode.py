"""Builtin VS Code harness plugin (`servers` key, explicit stdio type)."""

from __future__ import annotations

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
