"""Builtin OpenCode harness plugin (`mcp.servers`, command array, environment)."""

from __future__ import annotations

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
GLOBAL_CONFIGS = [
    "~/.config/opencode/opencode.json",
    "~/.config/opencode/opencode.jsonc",
    "%APPDATA%/opencode/opencode.json",
    "%APPDATA%/opencode/opencode.jsonc",
    "%LOCALAPPDATA%/opencode/opencode.json",
    "%LOCALAPPDATA%/opencode/opencode.jsonc",
]
LOCAL_CONFIGS = ["opencode.json", "opencode.jsonc"]
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
