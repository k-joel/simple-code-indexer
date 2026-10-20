"""Builtin MiMoCode harness plugin (`mcp` key, local command array)."""

from __future__ import annotations

from typing import Any

NAME = "mimo"
LABEL = "MiMoCode"
HOME_DIRS = [".mimocode"]
BINARIES = ["mimo"]
GLOBAL_CONFIGS = ["~/.mimocode/mimocode.json"]
LOCAL_CONFIGS = [".mimocode/mimocode.json"]
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
