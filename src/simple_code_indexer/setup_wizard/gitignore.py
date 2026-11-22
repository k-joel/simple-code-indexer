"""Keep project-scope harness files out of version control.

A project entry is written into the workspace, so it lands in the repository
the user is about to commit. The pin makes those files machine-specific, and
`.simple-ci/` holds the index, so the wizard offers to ignore both. Matching is
delegated to `ignore.IgnoreRules` — that is the same gitwildmatch semantics the
indexer uses, so "already ignored" cannot disagree with what the indexer sees.
"""

from __future__ import annotations

import os
from pathlib import Path

from simple_code_indexer.ignore import GITIGNORE_NAME, IgnoreRules

INDEX_DIR = ".simple-ci/"


def is_git_workspace(workspace: Path) -> bool:
    """True when the workspace is (or is inside) a git repo, or has a `.gitignore`.

    A directory with no git anything is left untouched: creating a `.gitignore`
    there would be a surprise, and there is nothing to ignore it from.
    """
    if (workspace / GITIGNORE_NAME).is_file():
        return True
    for candidate in (workspace, *workspace.parents):
        if (candidate / ".git").exists():
            return True
    return False


def ignored(workspace: Path, rel: str) -> bool:
    """True when `rel` (workspace-relative, POSIX) is already ignored."""
    return IgnoreRules(workspace).is_ignored(rel, is_dir=rel.endswith("/"))


def missing(workspace: Path, rels: list[str]) -> list[str]:
    """The subset of `rels` the workspace's `.gitignore` files do not cover."""
    rules = IgnoreRules(workspace)
    return [rel for rel in rels if not rules.is_ignored(rel, is_dir=rel.endswith("/"))]


def ensure(workspace: Path, rels: list[str], *, dry_run: bool = False) -> list[str]:
    """Append the missing patterns; returns the ones actually added.

    Existing lines are never reordered or removed, and a file that already ends
    without a trailing newline gets one before the new block.
    """
    add = missing(workspace, rels)
    if not add or dry_run:
        return add
    path = workspace / GITIGNORE_NAME
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    block = "\n".join(add) + "\n"
    separator = "\n" if existing.endswith("\n\n") else ""
    path.write_text(existing + separator + block, encoding="utf-8", newline="\n")
    return add


def relative_targets(configs: list[Path], workspace: Path) -> list[str]:
    """The workspace-relative patterns for `configs`, plus the index directory.

    A config outside the workspace cannot be ignored from inside it and is
    dropped; `.simple-ci/` is always included because the index lives there.
    """
    patterns: list[str] = []
    for path in configs:
        try:
            rel = path.resolve().relative_to(workspace.resolve())
        except (OSError, ValueError):
            continue
        patterns.append(rel.as_posix())
    patterns.append(INDEX_DIR)
    seen: set[str] = set()
    unique: list[str] = []
    for pattern in patterns:
        key = pattern.lower() if os.name == "nt" else pattern
        if key in seen:
            continue
        seen.add(key)
        unique.append(pattern)
    return unique
