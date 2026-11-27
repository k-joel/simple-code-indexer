"""Builtin OpenClaw harness plugin (`mcp.servers.<name>`, JSON5 config).

OpenClaw keeps one config at `~/.openclaw/openclaw.json` (JSON5: comments and
trailing commas allowed) and has no project scope. `openclaw mcp set <name>
<json>` writes a definition into `mcp.servers` without touching anything else
and works whether or not the Gateway is running, so the CLI is preferred over
merging the file here.

Stdio definitions take `command`/`args`/`env`; `requestTimeoutMs` is left at the
client default.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NAME = "openclaw"
LABEL = "OpenClaw"
HOME_DIRS = ["~/.openclaw", "%APPDATA%/openclaw"]
BINARIES = ["openclaw"]
CLI_BINARIES = ["openclaw"]
GLOBAL_CONFIGS = [
    "~/.openclaw/openclaw.json",
    "%APPDATA%/openclaw/openclaw.json",
]
LOCAL_CONFIGS: list[str] = []
ROOT_KEY = "mcp.servers"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {"command": command[0]}
    if len(command) > 1:
        value["args"] = command[1:]
    if env:
        value["env"] = dict(env)
    return value


def cli_add(
    scope: str,
    workspace: Path,
    name: str,
    command: list[str],
    entry: dict[str, Any],
) -> list[str] | None:
    """`openclaw mcp set <name> <json>`; global scope only.

    `set` takes the definition as one JSON object and saves it under
    `mcp.servers`, which is exactly the entry built above — no field is lost to
    a flag-shaped CLI. `add` is avoided: it probes the server before saving and
    refuses while the Gateway runs, either of which would stall a wizard.
    """
    del workspace, command
    if scope != "global":
        return None
    return ["openclaw", "mcp", "set", name, json.dumps(entry)]


def cli_remove(scope: str, workspace: Path, name: str) -> list[str] | None:
    del workspace
    if scope != "global":
        return None
    return ["openclaw", "mcp", "unset", name]
