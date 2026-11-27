"""Builtin Claude Code harness plugin.

`claude mcp add -s user` writes `~/.claude.json`; `-s project` writes
`.mcp.json` at the project root. `local` is Claude Code's own per-project scope
inside `~/.claude.json` and is not used here — project scope is the shared file.
"""

from pathlib import Path

NAME = "claude_code"
LABEL = "Claude Code"
HOME_DIRS = [".claude"]
BINARIES = ["claude"]
CLI_BINARIES = ["claude"]
GLOBAL_CONFIGS = ["~/.claude.json"]
LOCAL_CONFIGS = [".mcp.json"]
ROOT_KEY = "mcpServers"


def cli_add(
    scope: str,
    workspace: Path,
    name: str,
    command: list[str],
    entry: dict[str, object],
) -> list[str] | None:
    """`claude mcp add <scope> <name> -- <command>`.

    Everything after `--` is passed to the server untouched, so the workspace
    pin and the `--harness` marker survive. No `-e/--env` is used: entries carry
    arguments, never environment variables (ADR-024).
    """
    del workspace, entry
    cli_scope = "user" if scope == "global" else scope
    if cli_scope not in {"user", "project"}:
        return None
    return ["claude", "mcp", "add", "-s", cli_scope, name, "--", *command]


def cli_remove(scope: str, workspace: Path, name: str) -> list[str] | None:
    del workspace
    cli_scope = "user" if scope == "global" else scope
    if cli_scope not in {"user", "project"}:
        return None
    return ["claude", "mcp", "remove", "-s", cli_scope, name]
