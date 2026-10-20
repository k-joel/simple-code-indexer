"""Builtin Command Code harness plugin (stdio transport marker)."""

from __future__ import annotations

from typing import Any

NAME = "commandcode"
LABEL = "Command Code"
HOME_DIRS = [".commandcode"]
BINARIES: list[str] = []
GLOBAL_CONFIGS = ["~/.commandcode/mcp.json"]
LOCAL_CONFIGS = [".mcp.json"]
ROOT_KEY = "mcpServers"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "transport": "stdio",
        "enabled": True,
        "command": command[0],
    }
    if len(command) > 1:
        value["args"] = command[1:]
    if env:
        value["env"] = env
    return value
