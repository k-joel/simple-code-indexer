"""Builtin Codex CLI harness plugin (TOML, marker-block merge).

`codex mcp add` only writes `~/.codex/config.toml` — it has no project-scope
flag, so a project entry is merged into `.codex/config.toml` by the wizard.
Codex reads that file only for a trusted project.
"""

from pathlib import Path

NAME = "codex"
LABEL = "Codex CLI"
HOME_DIRS = [".codex"]
BINARIES = ["codex"]
CLI_BINARIES = ["codex"]
GLOBAL_CONFIGS = ["~/.codex/config.toml"]
LOCAL_CONFIGS = [".codex/config.toml"]
FORMAT = "toml"
ENABLED = True


def cli_add(
    scope: str,
    workspace: Path,
    name: str,
    command: list[str],
    entry: dict[str, object],
) -> list[str] | None:
    """`codex mcp add <name> [--env K=V] -- <command>`; global scope only.

    Codex has no `--scope`, and `.codex/config.toml` is written by the wizard's
    marker-block merge instead (`ENABLED` adds `enabled = true`).
    """
    del workspace, entry
    if scope != "global":
        return None
    return ["codex", "mcp", "add", name, "--", *command]


def cli_remove(scope: str, workspace: Path, name: str) -> list[str] | None:
    del workspace
    if scope != "global":
        return None
    return ["codex", "mcp", "remove", name]
