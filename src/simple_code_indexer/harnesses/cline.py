"""Builtin Cline harness plugin (Cline keeps its settings under `~/.cline`)."""

from __future__ import annotations

from typing import Any

NAME = "cline"
LABEL = "Cline"
HOME_DIRS = [".cline"]
BINARIES = ["cline", "code"]
GLOBAL_CONFIGS = ["~/.cline/data/settings/cline_mcp_settings.json"]
LOCAL_CONFIGS: list[str] = []
ROOT_KEY = "mcpServers"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {"command": command[0]}
    if len(command) > 1:
        value["args"] = command[1:]
    if env:
        value["env"] = env
    value["disabled"] = False
    value["autoApprove"] = []
    return value
