"""Builtin Goose harness plugin (YAML, `extensions.<name>` stdio entry)."""

from __future__ import annotations

from typing import Any

NAME = "goose"
LABEL = "Goose"
HOME_DIRS = ["%APPDATA%/Block/goose", "~/.config/goose"]
BINARIES = ["goose"]
GLOBAL_CONFIGS = [
    "%APPDATA%/Block/goose/config/config.yaml",
    "~/.config/goose/config.yaml",
]
LOCAL_CONFIGS: list[str] = []
FORMAT = "yaml"
ROOT_KEY = "extensions"

EXTENSION_NAME = "simple-code-indexer"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "stdio",
        "name": EXTENSION_NAME,
        "cmd": command[0],
        "args": command[1:],
        "enabled": True,
        "timeout": 300,
    }
    if env:
        value["envs"] = dict(env)
    return value
