"""Builtin Kilo Code harness plugin (`mcp.<name>`, local command array).

Kilo Code is a VS Code extension *and* a CLI (`@kilocode/cli` installs `kilo`
and `kilocode`); both read the same config pair. Global:
`~/.config/kilo/kilo.jsonc` (JSONC). Project: `kilo.jsonc` or `kilo.json` at the
workspace root, or `.kilo/kilo.jsonc` for a cleaner tree — project config wins
over global.

A local server is `{"type": "local", "command": ["exe", ...args]}`: the whole
argv goes in one array, and the environment block is spelled `environment`.
There is no `mcp add` subcommand (the `kilo` binary opens the TUI), so the
wizard merges the file for both scopes.

Being extension-only for many users is why `HOME_DIRS` carries the config
directory: the CLI probe can legitimately find nothing while Kilo is installed.
"""

from __future__ import annotations

from typing import Any

NAME = "kilo"
LABEL = "Kilo Code"
HOME_DIRS = ["~/.config/kilo", "~/.kilocode", "%APPDATA%/Kilo-Code"]
BINARIES = ["kilo", "kilocode"]
GLOBAL_CONFIGS = ["~/.config/kilo/kilo.jsonc", "~/.config/kilo/kilo.json"]
# `kilo.jsonc` first (the client's own default), then `.kilo/`, which is the
# cleaner layout Kilo documents for projects that do not want a root file.
LOCAL_CONFIGS = [
    "kilo.jsonc",
    "kilo.json",
    ".kilo/kilo.jsonc",
    ".kilo/kilo.json",
]
ROOT_KEY = "mcp"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "local",
        "command": command,
        "enabled": True,
        # Milliseconds; the wizard's other clients use 120000 for the same reason
        # (managed services can hold startup).
        "timeout": 120000,
    }
    if env:
        value["environment"] = dict(env)
    return value
