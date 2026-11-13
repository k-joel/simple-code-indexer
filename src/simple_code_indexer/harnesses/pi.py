"""Builtin Pi harness plugin (`mcpServers`, direct tool exposure)."""

from __future__ import annotations

from typing import Any

NAME = "pi"
LABEL = "Pi"
HOME_DIRS = ["~/.pi/agent"]
BINARIES = ["pi"]
GLOBAL_CONFIGS = ["~/.pi/agent/mcp.json"]
LOCAL_CONFIGS = [".pi/mcp.json"]
ROOT_KEY = "mcpServers"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {"command": command[0]}
    if len(command) > 1:
        value["args"] = command[1:]
    if env:
        value["env"] = dict(env)
    # Pi hides MCP tools behind codemode by default; declare them directly so a
    # harness session can call them without writing a codemode script.
    value["exposure"] = "direct"
    value["timeout"] = 120
    return value
