"""Builtin Command Code harness plugin (stdio transport + workspace discovery)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from simple_code_indexer.harnesses import RUNTIME_ENV

NAME = "commandcode"
LABEL = "Command Code"
HOME_DIRS = [".commandcode"]
# `cmd` is the Windows shell, so it must never be a detection binary; `cmdc` is
# the real CLI (NOTES.md).
BINARIES: list[str] = []
CLI_BINARIES = ["cmdc"]
GLOBAL_CONFIGS = ["~/.commandcode/mcp.json"]
# `project` scope is `.mcp.json` at the project root. Command Code's own
# `local` scope (`~/.commandcode/projects/<slug>/mcp.json`) is deliberately not
# used: the slug is derived by the client and the file is outside the workspace.
LOCAL_CONFIGS = [".mcp.json"]
ROOT_KEY = "mcpServers"

_IDE_DIR = "ide"

logger = logging.getLogger(__name__)

_CLI_SCOPES = {"user", "project"}


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "transport": "stdio",
        "enabled": True,
        "command": command[0],
        "env": {**env, RUNTIME_ENV: NAME},
    }
    if len(command) > 1:
        value["args"] = command[1:]
    return value


def cli_add(
    scope: str,
    workspace: Path,
    name: str,
    command: list[str],
    entry: dict[str, Any],
) -> list[str] | None:
    """`cmdc mcp add-json`, so the CLI writes our canonical entry verbatim.

    `add-json` takes the whole entry, which keeps `transport`, `enabled` and
    the `SIMPLE_CI_HARNESS` marker intact — the flag-style `add` cannot express
    them. `--scope user` is the global file, `--scope project` is `.mcp.json`;
    Command Code's `local` scope is a home-directory file and is not used.
    """
    del workspace, command
    cli_scope = "user" if scope == "global" else scope
    if cli_scope not in _CLI_SCOPES:
        return None
    return ["cmdc", "mcp", "add-json", "--scope", cli_scope, name, json.dumps(entry)]


def cli_remove(scope: str, workspace: Path, name: str) -> list[str] | None:
    del workspace
    cli_scope = "user" if scope == "global" else scope
    if cli_scope not in _CLI_SCOPES:
        return None
    return ["cmdc", "mcp", "remove", "--scope", cli_scope, name]


def _discovery_files(home: Path) -> list[dict[str, Any]]:
    """Parsed `~/.commandcode/ide/*.json` entries; malformed files are skipped."""
    directory = home / HOME_DIRS[0] / _IDE_DIR
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.debug("skipping unreadable discovery file %s", path)
            continue
        if not isinstance(data, dict):
            continue
        pid = data.get("pid")
        ide_name = data.get("ideName")
        folders = data.get("workspaceFolders")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or not isinstance(ide_name, str)
            or not ide_name
            or not isinstance(folders, list)
            or not folders
            or not all(isinstance(item, str) and item for item in folders)
        ):
            logger.debug("skipping malformed discovery file %s", path)
            continue
        entries.append(data)
    return entries


def _matches_ide(ancestor_name: str, ide_name: str) -> bool:
    """`Code.exe` publishes `ideName: "code"`; compare the executable stem."""
    base = ancestor_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    return base.removesuffix(".exe") == ide_name.lower()


def _published_workspace(
    cwd: Path, home: Path, ancestors: list[tuple[int, str]]
) -> Path | None:
    """First ancestor that owns a discovery file wins; nearest is first."""
    entries = _discovery_files(home)
    if not entries:
        logger.debug("no Command Code IDE discovery files under %s", home)
        return None
    by_pid = {int(item["pid"]): item for item in entries}
    for pid, name in ancestors:
        item = by_pid.get(pid)
        if item is None or not _matches_ide(name, str(item["ideName"])):
            continue
        folder = Path(str(item["workspaceFolders"][0]))
        if not folder.is_absolute():
            continue
        try:
            folder = folder.resolve()
        except OSError:
            continue
        if folder.is_dir():
            logger.info("harness workspace: %s (pid=%d, %s)", folder, pid, name)
            return folder
        logger.warning("published workspace %s no longer exists", folder)
    logger.warning(
        "no Command Code IDE window matches a live ancestor of %s; "
        "check ~/.commandcode/ide/*.json",
        cwd,
    )
    return None


def resolve_workspace(cwd: Path) -> Path | None:
    """The workspace this IDE window published for its extension host.

    Command Code writes one ``~/.commandcode/ide/<ideName>-<8hex>.json`` per
    window; ``pid`` is that window's extension host, an ancestor of this
    process even through the spawn shell. The files are not self-cleaning, so
    a candidate is accepted only when its pid is a live ancestor *and* the
    ancestor's image name matches ``ideName`` — never by recency alone.
    """
    from simple_code_indexer import parent_watch

    try:
        home = Path.home()
    except (OSError, RuntimeError):
        return None
    return _published_workspace(cwd, home, parent_watch.ancestor_chain())
