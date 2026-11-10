"""Filesystem writes: harness configs and rendered snippets."""

from __future__ import annotations

import json
import os
import re
import time
import tomllib
from pathlib import Path

from simple_code_indexer.harnesses import HarnessSpec

_BACKUP_STAMP = re.compile(r"\.bak\.\d{8}-\d{6}$")


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


def remove(spec: HarnessSpec, target: Path, server_name: str) -> bool:
    """Strip the server entry from `target`; False when it was not there.

    A file left with nothing in it is deleted (the wizard created it).
    """
    if not target.is_file():
        return False
    existing = target.read_text(encoding="utf-8")
    rendered = spec.remove(existing, name=server_name)
    if rendered is None or rendered == existing:
        return False
    if not rendered.strip():
        target.unlink()
        return True
    _validate(spec.format, rendered)
    _atomic_write(target, rendered)
    return True


def remove_backups(target: Path) -> list[Path]:
    """Delete the `<name>.bak.<YYYYmmdd-HHMMSS>` files `install` created."""
    removed: list[Path] = []
    if not target.parent.is_dir():
        return removed
    for path in target.parent.glob(target.name + ".bak.*"):
        if path.is_file() and _BACKUP_STAMP.search(path.name):
            try:
                path.unlink()
            except OSError:
                continue
            removed.append(path)
    return removed


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
