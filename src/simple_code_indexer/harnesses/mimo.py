"""Builtin MiMoCode harness plugin (`mcp` key, local command array).

`mimo mcp add` prompts for every field and offers no non-interactive flags, so
the wizard writes the JSON itself: `~/.config/mimocode/mimocode.json` globally
and `.mimocode/mimocode.json` for one project.
"""

from __future__ import annotations

from typing import Any

NAME = "mimo"
LABEL = "MiMoCode"
HOME_DIRS = [
    "~/.config/mimocode",
    "~/.mimocode",
    "%APPDATA%/mimocode",
    "%LOCALAPPDATA%/mimocode",
]
BINARIES = ["mimo"]
GLOBAL_CONFIGS = [
    "~/.config/mimocode/mimocode.json",
    "~/.config/mimocode/config.json",
    "~/.mimocode/mimocode.json",
    "%APPDATA%/mimocode/mimocode.json",
    "%LOCALAPPDATA%/mimocode/mimocode.json",
]
# `.jsonc` first: an existing commented config is the one MiMoCode loads.
LOCAL_CONFIGS = [".mimocode/mimocode.jsonc", ".mimocode/mimocode.json"]
ROOT_KEY = "mcp"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "local",
        "command": command,
        "enabled": True,
        "timeout": 120000,
    }
    if env:
        value["environment"] = env
    return value
