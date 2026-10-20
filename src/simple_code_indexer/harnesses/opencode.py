"""Builtin OpenCode harness plugin (`mcp` key, command array, environment)."""

from __future__ import annotations

from typing import Any

NAME = "opencode"
LABEL = "OpenCode"
HOME_DIRS = ["~/.config/opencode", "~/.local/share/opencode"]
BINARIES = ["opencode"]
GLOBAL_CONFIGS = [
    "~/.config/opencode/opencode.json",
    "~/.config/opencode/opencode.jsonc",
]
LOCAL_CONFIGS = ["opencode.json", "opencode.jsonc"]
ROOT_KEY = "mcp"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "local",
        "command": command,
        "enabled": True,
    }
    if env:
        value["environment"] = env
    return value
