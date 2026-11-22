"""Builtin Gemini CLI harness plugin.

`gemini mcp add --scope user` writes `~/.gemini/settings.json`;
`--scope project` writes `.gemini/settings.json` in the workspace (and is the
CLI's default).
"""

from pathlib import Path

NAME = "gemini_cli"
LABEL = "Gemini CLI"
HOME_DIRS = [".gemini"]
BINARIES = ["gemini"]
CLI_BINARIES = ["gemini"]
GLOBAL_CONFIGS = ["~/.gemini/settings.json"]
LOCAL_CONFIGS = [".gemini/settings.json"]
ROOT_KEY = "mcpServers"


def cli_add(
    scope: str,
    workspace: Path,
    name: str,
    command: list[str],
    entry: dict[str, object],
) -> list[str] | None:
    """`gemini mcp add --scope <scope> <name> <command> [args...]`.

    Gemini parses the server command positionally, so the pin is passed as
    plain arguments after the name.
    """
    del workspace, entry
    cli_scope = "user" if scope == "global" else scope
    if cli_scope not in {"user", "project"}:
        return None
    return ["gemini", "mcp", "add", "--scope", cli_scope, name, *command]


def cli_remove(scope: str, workspace: Path, name: str) -> list[str] | None:
    del workspace
    cli_scope = "user" if scope == "global" else scope
    if cli_scope not in {"user", "project"}:
        return None
    return ["gemini", "mcp", "remove", "--scope", cli_scope, name]
