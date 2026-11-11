"""Workspace ignore rules: `.gitignore` files layered over `config.IGNORE_DIRS`.

Only ignore files at or below the workspace root are honored. Patterns in a
`.gitignore` apply relative to the directory that holds it, and deeper files
override shallower ones, matching git's precedence. Nested files are loaded
lazily and re-read when their `mtime_ns` changes, so a long-lived watcher
matcher follows edits without an explicit reload.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from pathspec import GitIgnoreSpec

logger = logging.getLogger(__name__)

GITIGNORE_NAME = ".gitignore"


def _fold(text: str) -> str:
    """Git's `core.ignorecase` default: Windows paths match case-insensitively."""
    return text.lower() if os.name == "nt" else text


class IgnoreRules:
    """Cached, thread-safe resolver for workspace `.gitignore` rules."""

    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root
        self._cache: dict[str, tuple[int, GitIgnoreSpec | None]] = {}
        self._lock = threading.Lock()

    def is_ignored(self, rel: str, *, is_dir: bool = False) -> bool:
        """Decide a workspace-relative POSIX path; deeper ignore files win.

        Ancestors are checked before the path itself: git cannot re-include a
        path whose parent directory is excluded, so a nested `!keep.py` must not
        resurrect a file under an ignored tree.
        """
        parts = [part for part in _fold(rel).split("/") if part and part != "."]
        if not parts:
            return False
        specs = self._applicable_specs(parts)
        for index in range(len(parts) - 1):
            if self._decide(specs, parts, index, is_dir=True):
                return True
        return self._decide(specs, parts, len(parts) - 1, is_dir=is_dir)

    def _applicable_specs(self, parts: list[str]) -> list[tuple[int, GitIgnoreSpec]]:
        """Existing ignore files for the path, deepest first."""
        specs: list[tuple[int, GitIgnoreSpec]] = []
        for depth in range(len(parts) - 1, -1, -1):
            spec = self._spec("/".join(parts[:depth]))
            if spec is not None:
                specs.append((depth, spec))
        return specs

    @staticmethod
    def _decide(
        specs: list[tuple[int, GitIgnoreSpec]],
        parts: list[str],
        index: int,
        *,
        is_dir: bool,
    ) -> bool:
        """Match the entry at `parts[index]`; the deepest matching spec wins."""
        for depth, spec in specs:
            if depth > index:
                continue
            candidate = "/".join(parts[depth : index + 1])
            if is_dir:
                # A trailing slash tells pathspec the match target is a dir.
                candidate += "/"
            decision = spec.check_file(candidate).include
            if decision is not None:
                return decision
        return False

    def _spec(self, rel_dir: str) -> GitIgnoreSpec | None:
        if rel_dir:
            path = self._root / rel_dir / GITIGNORE_NAME
        else:
            path = self._root / GITIGNORE_NAME
        try:
            marker = path.stat().st_mtime_ns
        except OSError:
            marker = -1
        with self._lock:
            cached = self._cache.get(rel_dir)
            if cached is not None and cached[0] == marker:
                return cached[1]
        spec: GitIgnoreSpec | None = None
        if marker >= 0:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                spec = GitIgnoreSpec.from_lines([_fold(line) for line in lines])
            except (OSError, ValueError):
                logger.warning("ignoring unparsable %s", path, exc_info=True)
        with self._lock:
            self._cache[rel_dir] = (marker, spec)
        return spec
