"""Write one harness entry through the client's own CLI, else merge its config.

The ladder, per harness and per scope (ADR-022):

1. **Client CLI** — the plugin's ``cli_add`` builds an argv; the binary must be
   on ``PATH``. This is the standard way to add a server and stays correct when
   a client changes its file format.
2. **Manual merge** — CLI missing, unsupported for the scope, non-zero exit, or
   the entry does not verify afterwards: ``write.install`` merges the same entry
   into the config file (backup, validation, atomic write).
3. **Global fallback** — the client has no project config at all (Goose, Claude
   Desktop): its *global* entry is written, unpinned, and the caller warns.

All per-client knowledge lives in ``harnesses/<client>.py``; this module never
inspects a harness name.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simple_code_indexer.harnesses import (
    HarnessSpec,
    Scope,
    _json,
    _yaml,
    entry_argv,
    expand_config_path,
    pinned_command,
    spawnable,
)
from simple_code_indexer.setup_wizard import write
from simple_code_indexer.setup_wizard.provision import Runner

logger = logging.getLogger(__name__)

CLI_TIMEOUT_S = 60.0

VIA_CLI = "cli"
VIA_CONFIG = "config"
NOT_WRITTEN = "skipped"


@dataclass(frozen=True, slots=True)
class EntryOutcome:
    """How an entry was written, where, and enough detail for the wizard."""

    kind: str
    scope: str
    path: Path | None = None
    detail: str = ""

    @property
    def wrote(self) -> bool:
        return self.kind != NOT_WRITTEN

    @property
    def fell_back_to_global(self) -> bool:
        return self.scope == Scope.GLOBAL and self.kind != NOT_WRITTEN


def scope_for(spec: HarnessSpec, scope: str) -> str:
    """The scope an entry will actually be written at.

    A client with no project config (`goose`, `claude_desktop`) can only be
    installed globally; the caller warns when this differs from the request.
    """
    return scope if spec.supports(scope) else Scope.GLOBAL


def cli_target(
    spec: HarnessSpec, scope: str, workspace: Path, home: Path | None
) -> Path | None:
    """The file `spec.cli_add` writes at `scope`, or None when it has no CLI.

    Most clients write their own config path, so this returns that candidate.
    Cursor is the exception: `--add-mcp` edits the profile settings file, and
    the returned path is what the wizard must record instead of
    `~/.cursor/mcp.json`.
    """
    if spec.cli_add is None:
        return None
    pattern = spec.cli_target(scope) if spec.cli_target is not None else None
    if pattern is None:
        return write.choose_target(spec, scope, workspace, home)
    return expand_config_path(pattern, workspace, home)


def _verify_cli_result(
    spec: HarnessSpec,
    path: Path,
    scope: str,
    server_name: str,
    workspace: Path,
) -> str | None:
    """Check that the CLI really wrote the entry it claimed to add.

    A CLI can report success and write a different file, or write under a
    different root key (Cursor's profile settings use `mcp.servers`), so the
    path is read back before it is recorded. A miss is a warning, not a
    failure: the caller still gets the path to record.
    """
    if not path.is_file():
        return f"{path} does not exist"
    root_key = spec.cli_root_key or spec.root_key
    if root_key is None:
        return None
    stored = read_entry_at(path, spec.format, root_key, server_name)
    if stored is None:
        return f"no {server_name!r} entry in {path}"
    if scope == Scope.PROJECT:
        if _pinned_workspace(entry_argv(stored)) is None:
            return f"the entry in {path} is not pinned to {workspace}"
    elif _pinned_workspace(entry_argv(stored)) is not None:
        return f"the global entry in {path} carries a workspace pin"
    return None


def read_entry_at(
    path: Path, fmt: str, root_key: str, server_name: str
) -> dict[str, Any] | None:
    """One entry from `path`, read at an explicit format and root key."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        if fmt == "toml":
            import tomllib

            document: Any = tomllib.loads(text)
        elif fmt == "yaml":
            document = _yaml.parse(text)
        else:
            document = _json.parse(text)
    except (OSError, ValueError):
        return None
    node: Any = document
    for part in root_key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    entry = node.get(server_name) if isinstance(node, dict) else None
    return entry if isinstance(entry, dict) else None


def install_entry(
    spec: HarnessSpec,
    *,
    scope: str,
    workspace: Path,
    home: Path | None,
    server_name: str,
    command: list[str],
    env: dict[str, str],
    runner: Runner,
    dry_run: bool,
    say: Callable[[str], None],
    target: Path | None = None,
) -> EntryOutcome:
    """Install `spec`'s server entry in `scope`, using the client CLI when it can.

    `target` pins the exact file (a recorded config); otherwise the first
    existing candidate for the effective scope is used, else the first one for
    the platform. When the client CLI writes somewhere else, the outcome names
    *that* file, so the caller records a path it can clean up later.
    """
    effective = scope_for(spec, scope)
    pinned = (
        pinned_command(command, workspace)
        if effective == Scope.PROJECT
        else list(command)
    )
    entry = spec.entry(pinned, env)
    explicit = target is not None
    if target is None:
        target = write.choose_target(spec, effective, workspace, home)
    if target is None:
        return EntryOutcome(
            NOT_WRITTEN, effective, detail=f"{spec.label} has no config path"
        )

    argv = _cli_argv(spec, effective, workspace, server_name, pinned, entry)
    cli_ready = argv is not None and runner.which(argv[0]) is not None
    written = target
    if cli_ready:
        candidate = cli_target(spec, effective, workspace, home) or target
        if explicit and candidate.resolve() != target.resolve():
            # An explicit target (a recorded entry being repinned) must be edited
            # in place: letting the client CLI run would rewrite its own profile
            # and leave the recorded file stale.
            cli_ready = False
        else:
            written = candidate

    if dry_run:
        if cli_ready:
            assert argv is not None
            return EntryOutcome(
                VIA_CLI, effective, written, "Would run: " + " ".join(argv)
            )
        snippet = spec.render("", name=server_name, command=pinned, env=env)
        return EntryOutcome(
            VIA_CONFIG, effective, target, f"Would update {target}:\n{snippet}"
        )

    if argv is not None and cli_ready:
        detail = _run_cli(argv, workspace, runner, say)
        if detail is not None:
            problem = _verify_cli_result(
                spec, written, effective, server_name, workspace
            )
            suffix = f" (warning: {problem})" if problem else ""
            return EntryOutcome(VIA_CLI, effective, written, detail + suffix)

    try:
        write.install(spec, target, server_name, pinned, env)
    except (TypeError, ValueError, OSError) as exc:
        return EntryOutcome(
            NOT_WRITTEN, effective, target, f"Could not update {target}: {exc}"
        )
    problem = verify(spec, target, effective, server_name, workspace)
    if problem is not None:
        return EntryOutcome(
            VIA_CONFIG, effective, target, f"updated {target} ({problem})"
        )
    return EntryOutcome(VIA_CONFIG, effective, target, f"updated {target}")


def remove_entry(
    spec: HarnessSpec,
    *,
    scope: str,
    workspace: Path,
    home: Path | None,
    server_name: str,
    runner: Runner,
    dry_run: bool,
    say: Callable[[str], None],
    target: Path | None = None,
) -> EntryOutcome:
    """Remove the entry at `scope`; a no-op when the file or entry is absent.

    The client's remove command is tried first (it knows about its own
    bookkeeping, such as OAuth tokens) and a failure falls through to the file
    merge, so a stale CLI never blocks cleanup. `target` names the recorded
    file when there is one.
    """
    effective = scope_for(spec, scope)
    argv = _remove_argv(spec, effective, workspace, server_name)

    if argv is not None and runner.which(argv[0]) is not None:
        if dry_run:
            return EntryOutcome(
                VIA_CLI, effective, detail="Would run: " + " ".join(argv)
            )
        result = runner.run(
            _spawnable([runner.which(argv[0]) or argv[0], *argv[1:]]),
            timeout=CLI_TIMEOUT_S,
            cwd=workspace,
        )
        if result.returncode == 0:
            return EntryOutcome(VIA_CLI, effective, detail=f"removed with {argv[0]}")

    if target is None:
        target = write.choose_target(spec, effective, workspace, home)
    if target is None:
        return EntryOutcome(
            NOT_WRITTEN, effective, detail=f"{spec.label} has no config path"
        )
    if dry_run:
        return EntryOutcome(
            VIA_CONFIG, effective, target, f"Would remove the entry from {target}"
        )
    try:
        removed = write.remove(spec, target, server_name)
    except (TypeError, ValueError, OSError) as exc:
        say(f"Could not update {target}: {exc}")
        return EntryOutcome(NOT_WRITTEN, effective, target, str(exc))
    if not removed:
        return EntryOutcome(NOT_WRITTEN, effective, target, f"no entry in {target}")
    write.remove_backups(target)
    return EntryOutcome(
        VIA_CONFIG, effective, target, f"removed the entry from {target}"
    )


def verify(
    spec: HarnessSpec,
    path: Path,
    scope: str,
    server_name: str,
    workspace: Path,
) -> str | None:
    """None when `path` holds a usable entry, else why not.

    A project entry must carry the pin; a global entry must not (ADR-015).
    This is a warning, not a rejection: a client that rewrote the entry its own
    way still gets reported accurately rather than silently accepted.
    """
    entry = read_entry(spec, path, server_name)
    if entry is None:
        return f"no {server_name!r} entry"
    argv = entry_argv(entry)
    if not argv:
        return "the entry has no launch command"
    pinned = _pinned_workspace(argv)
    if scope == Scope.PROJECT and pinned is None:
        return f"the entry is not pinned to {workspace}"
    if scope != Scope.PROJECT and pinned is not None:
        return f"the global entry is pinned to {pinned}"
    return None


def read_entry(
    spec: HarnessSpec, path: Path, server_name: str
) -> dict[str, Any] | None:
    """This server's entry as stored in `path`, or None."""
    if spec.root_key is None:
        return None
    return read_entry_at(path, spec.format, spec.root_key, server_name)


def _pinned_workspace(argv: list[str]) -> str | None:
    """The `--workspace` value in `argv`, or None when it carries no pin."""
    for index, item in enumerate(argv):
        if item == "--workspace" and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith("--workspace="):
            return item.partition("=")[2]
    return None


def _run_cli(
    argv: list[str],
    workspace: Path,
    runner: Runner,
    say: Callable[[str], None],
) -> str | None:
    """Run the client's add command; None when it failed (caller merges instead)."""
    executable = runner.which(argv[0]) or argv[0]
    result = runner.run(
        _spawnable([executable, *argv[1:]]), timeout=CLI_TIMEOUT_S, cwd=workspace
    )
    if result.returncode == 0:
        return "added with " + " ".join(argv[:3])
    lines = (result.stderr or result.stdout).strip().splitlines()
    reason = f": {lines[0]}" if lines else ""
    say(f"{argv[0]} could not add the server{reason}; writing the config file instead.")
    return None


def _spawnable(argv: list[str]) -> list[str]:
    """Route a Windows `.cmd`/`.bat` shim through `cmd /c` (see `spawnable`).

    Kept as a module-local name because tests patch and assert on it here.
    """
    return spawnable(argv)


def _cli_argv(
    spec: HarnessSpec,
    scope: str,
    workspace: Path,
    server_name: str,
    command: list[str],
    entry: dict[str, Any],
) -> list[str] | None:
    if spec.cli_add is None:
        return None
    try:
        return spec.cli_add(scope, workspace, server_name, command, entry)
    except Exception:
        logger.warning("%s cli_add failed", spec.name, exc_info=True)
        return None


def _remove_argv(
    spec: HarnessSpec, scope: str, workspace: Path, server_name: str
) -> list[str] | None:
    if spec.cli_remove is None:
        return None
    try:
        return spec.cli_remove(scope, workspace, server_name)
    except Exception:
        logger.warning("%s cli_remove failed", spec.name, exc_info=True)
        return None
