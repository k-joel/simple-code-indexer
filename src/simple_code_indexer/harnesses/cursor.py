"""Builtin Cursor harness plugin.

Cursor keeps MCP servers in two different places, and they are not
interchangeable:

- the editor reads `~/.cursor/mcp.json` (user) and `.cursor/mcp.json` (project);
- `cursor --add-mcp '<json>'` writes the **user profile** file,
  `%APPDATA%/Cursor/User/settings.json` under `mcp.servers` — verified on Cursor
  3.31.15, where `--mcp-workspace` is rejected as an unknown option. That file
  is also the one the Customize page edits, so it is the real user scope.

There is no `mcp remove` and no project flag, so the wizard merges
`.cursor/mcp.json` itself for the project scope and uses the CLI for the global
one — and must record the profile file the CLI actually wrote, not
`~/.cursor/mcp.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NAME = "cursor"
LABEL = "Cursor"
HOME_DIRS = [".cursor"]
# The editor installs the `cursor` shell command; Cursor's standalone agent CLI
# is a separate install that ships `agent` (cursor.com/docs/cli).
BINARIES = ["cursor", "agent"]
CLI_BINARIES = ["cursor"]
# `%APPDATA%/Cursor/User/settings.json` is deliberately **not** listed: it is
# Cursor's whole editor settings file, and the wizard's merge would insert an
# `mcpServers` key into a document that expects `mcp.servers`, clobbering the
# user's settings. Only the CLI writes that file (`cli_target` below).
GLOBAL_CONFIGS = ["~/.cursor/mcp.json"]
LOCAL_CONFIGS = [".cursor/mcp.json"]
ROOT_KEY = "mcpServers"

# `--add-mcp` takes a flat `{name, command, args, env}` object, and writes it
# under `mcp.servers` in the profile settings file — not to `GLOBAL_CONFIGS[0]`
# and not under `ROOT_KEY`. Verified on Cursor 3.31.15: it prints
# "Added MCP servers: <name>", and `--mcp-workspace` is rejected as unknown.
CLI_SETTINGS = "%APPDATA%/Cursor/User/settings.json"
CLI_ROOT_KEY = "mcp.servers"


def cli_target(scope: str) -> str | None:
    """Where the CLI writes at `scope`, as a `GLOBAL_CONFIGS`-style pattern."""
    return CLI_SETTINGS if scope == "global" else None


def cli_add(
    scope: str,
    workspace: Path,
    name: str,
    command: list[str],
    entry: dict[str, Any],
) -> list[str] | None:
    """`cursor --add-mcp '<json>'`; global only (no project flag exists)."""
    del workspace, entry
    if scope != "global":
        return None
    payload: dict[str, Any] = {"name": name, "command": command[0]}
    if len(command) > 1:
        payload["args"] = command[1:]
    return ["cursor", "--add-mcp", json.dumps(payload)]
