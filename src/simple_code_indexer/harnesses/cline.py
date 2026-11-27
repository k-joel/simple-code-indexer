"""Builtin Cline harness plugin (`mcpServers.<name>`, VS Code extension + CLI).

Cline ships as a VS Code-family extension and as a CLI (`npm i -g cline`). The
extension keeps its servers in `cline_mcp_settings.json` under VS Code's
`globalStorage/saoudrizwan.claude-dev/settings/`; the CLI keeps the same
filename under `~/.cline/data/settings/`. Both are global only — Cline has no
per-project server file — so a project-scope request falls back to a global
entry.

`cline mcp add <name> --yes -- <command> [args…]` is non-interactive and is the
preferred writer; `cline mcp remove <name>` deletes it again.

`HOME_DIRS` covers the extension-only case, where no `cline` binary exists but
the settings directory does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

NAME = "cline"
LABEL = "Cline"
HOME_DIRS = [
    "~/.cline",
    "%APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev",
    "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev",
    "~/.config/Code/User/globalStorage/saoudrizwan.claude-dev",
]
BINARIES = ["cline"]
CLI_BINARIES = ["cline"]
GLOBAL_CONFIGS = [
    "~/.cline/data/settings/cline_mcp_settings.json",
    "%APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
    "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
    "~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
]
LOCAL_CONFIGS: list[str] = []
ROOT_KEY = "mcpServers"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "command": command[0],
        "disabled": False,
        "autoApprove": [],
    }
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
    """`cline mcp add <name> --yes -- <command> [args…]`; global scope only.

    `--yes` skips the add wizard and the `--` separator hands the server argv
    over untouched, so the workspace pin and the `--harness` marker survive.
    """
    del workspace, entry
    if scope != "global":
        return None
    return ["cline", "mcp", "add", name, "--yes", "--", *command]


def cli_remove(scope: str, workspace: Path, name: str) -> list[str] | None:
    del workspace
    if scope != "global":
        return None
    return ["cline", "mcp", "remove", name]
