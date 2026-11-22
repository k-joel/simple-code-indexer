"""Builtin Pi harness plugin (`mcpServers`, direct tool exposure).

`pi mcp add` writes `~/.pi/agent/mcp.json`; `-l/--local` writes `.pi/mcp.json`
in the current project, which Pi reads only for a trusted project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

NAME = "pi"
LABEL = "Pi"
HOME_DIRS = ["~/.pi/agent"]
BINARIES = ["pi"]
CLI_BINARIES = ["pi"]
GLOBAL_CONFIGS = ["~/.pi/agent/mcp.json"]
LOCAL_CONFIGS = [".pi/mcp.json"]
ROOT_KEY = "mcpServers"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {"command": command[0], "enabled": True}
    if len(command) > 1:
        value["args"] = command[1:]
    if env:
        value["env"] = dict(env)
    # Pi hides MCP tools behind codemode by default; declare them directly so a
    # harness session can call them without writing a codemode script.
    value["exposure"] = "direct"
    value["timeout"] = 120
    return value


def cli_add(
    scope: str,
    workspace: Path,
    name: str,
    command: list[str],
    entry: dict[str, Any],
) -> list[str] | None:
    """`pi mcp add [-l] <name> [--env K=V] -- <command>`.

    `--local` selects `.pi/mcp.json`; Pi's global file is the default. Pi's
    `--exposure direct` matches the entry we build, so tools stay on the
    native list.
    """
    del workspace
    argv = ["pi", "mcp", "add"]
    if scope == "project":
        argv.append("-l")
    elif scope != "global":
        return None
    for key, value in (entry.get("env") or {}).items():
        argv += ["--env", f"{key}={value}"]
    exposure = entry.get("exposure")
    if isinstance(exposure, str):
        argv += ["--exposure", exposure]
    argv += [name, "--", *command]
    return argv


def cli_remove(scope: str, workspace: Path, name: str) -> list[str] | None:
    del workspace
    argv = ["pi", "mcp", "remove"]
    if scope == "project":
        argv.append("-l")
    elif scope != "global":
        return None
    return [*argv, name]
