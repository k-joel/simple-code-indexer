"""Builtin OpenClaw harness plugin (`mcp.servers.<name>`, JSON5 config).

OpenClaw keeps one config at `~/.openclaw/openclaw.json` (JSON5: comments and
trailing commas allowed) and has no project scope: `mcp.servers` is a
user-scoped registry that OpenClaw projects into whichever runtime it launches.

Definitions are written with the client's own registry command,
`openclaw mcp set <name> <json>` (one JSON object on the command line) and
removed with `openclaw mcp unset <name>`. `set` does not connect to the server
and works whether or not the Gateway is running, so it never blocks a wizard;
`add` is deliberately avoided because it probes the server first and refuses
while the Gateway runs. Stdio definitions take `command`/`args`/`env`;
`requestTimeoutMs` is left at the client default.
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

    `set` takes the whole definition as one JSON object, so `command`, `args`
    and any env block survive verbatim — unlike the flag-shaped `add`, which
    also probes the server (and refuses while the Gateway runs).
    """
    del workspace, command
    if scope != "global":
        return None
    return ["openclaw", "mcp", "set", name, json.dumps(entry)]


def cli_remove(scope: str, workspace: Path, name: str) -> list[str] | None:
    """`openclaw mcp unset <name>`; fails when the name is absent.

    That failure is harmless: `entries.remove_entry` falls through to the
    config merge, which reports "no entry" for a name that was never there.
    """
    del workspace
    if scope != "global":
        return None
    return ["openclaw", "mcp", "unset", name]
