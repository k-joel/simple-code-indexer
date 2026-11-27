"""Builtin Hermes Agent harness plugin (YAML, `mcp_servers.<name>` stdio entry).

Hermes keeps one profile config at `~/.hermes/config.yaml` and has no project
scope: `hermes mcp add` writes the active profile, so a project-scope request
falls back to a global entry. The stdio shape is `command`, `args`, `env`.

`cli_add` is deliberately **not** declared. `hermes mcp add` always ends with an
interactive "Enable all N tools? [Y/n]" prompt (no `--yes` flag yet), which would
hang a wizard run, so the entry is merged into `config.yaml` instead.
"""

from __future__ import annotations

from typing import Any

NAME = "hermes"
LABEL = "Hermes Agent"
HOME_DIRS = ["~/.hermes"]
BINARIES = ["hermes"]
GLOBAL_CONFIGS = ["~/.hermes/config.yaml"]
LOCAL_CONFIGS: list[str] = []
FORMAT = "yaml"
ROOT_KEY = "mcp_servers"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {"command": command[0]}
    if len(command) > 1:
        value["args"] = command[1:]
    if env:
        value["env"] = dict(env)
    return value
