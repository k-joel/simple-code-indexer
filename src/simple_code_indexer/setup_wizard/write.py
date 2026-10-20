"""Filesystem writes: .gitignore, harness configs, rendered snippets."""

from __future__ import annotations

import json
import os
import time
import tomllib
from pathlib import Path

from simple_code_indexer.harnesses import HarnessSpec
from simple_code_indexer.setup_wizard.provision import Runner

GITIGNORE_ENTRY = ".simple-ci/"


def git_root(cwd: Path, runner: Runner) -> Path | None:
    result = runner.run(["git", "rev-parse", "--show-toplevel"])
    if result.returncode == 0 and result.stdout.strip():
        candidate = Path(result.stdout.strip())
        if candidate.is_dir():
            return candidate
    for parent in (cwd, *cwd.parents):
        if (parent / ".git").exists():
            return parent
    return None


def append_gitignore(path: Path, entry: str = GITIGNORE_ENTRY) -> bool:
    """Append the entry once; False when it is already present."""
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if any(line.strip() == entry for line in existing.splitlines()):
        return False
    body = existing
    if body and not body.endswith("\n"):
        body += "\n"
    if body:
        body += "\n"
    body += f"# simple-code-indexer\n{entry}\n"
    path.write_text(body, encoding="utf-8", newline="\n")
    return True


def choose_target(
    spec: HarnessSpec, scope: str, workspace: Path, home: Path | None = None
) -> Path | None:
    """First existing candidate, else the first platform-supported one."""
    candidates = spec.candidates(scope, workspace, home)
    if not candidates:
        return None
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def render(
    spec: HarnessSpec,
    server_name: str,
    command: list[str],
    env: dict[str, str],
) -> str:
    return spec.render("", name=server_name, command=command, env=env)


def install(
    spec: HarnessSpec,
    target: Path,
    server_name: str,
    command: list[str],
    env: dict[str, str],
    *,
    backup: bool = True,
    stamp: str | None = None,
) -> None:
    """Merge the server entry into `target`, backing up and validating first."""
    existing = target.read_text(encoding="utf-8") if target.is_file() else ""
    rendered = spec.render(existing, name=server_name, command=command, env=env)
    _validate(spec.format, rendered)
    if backup and target.is_file():
        suffix = stamp or time.strftime("%Y%m%d-%H%M%S")
        backup_path = target.with_name(f"{target.name}.bak.{suffix}")
        backup_path.write_text(existing, encoding="utf-8", newline="\n")
    _atomic_write(target, rendered)


def _validate(fmt: str, text: str) -> None:
    if fmt == "toml":
        tomllib.loads(text)
        return
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise TypeError("rendered config is not a JSON object")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
