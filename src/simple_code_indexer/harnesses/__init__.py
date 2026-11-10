"""Harness plugins: how each MCP client stores its server list.

Contract (same as `builtin/` language plugins — plain module globals):

    NAME            stable id (file stem by convention)
    LABEL           human label shown by the setup wizard
    HOME_DIRS       detection dirs, relative to home or absolute (%VARS% expand)
    BINARIES        optional CLI names that also count as "installed"
    GLOBAL_CONFIGS  user-scope config files (``~``, ``%APPDATA%`` supported)
    LOCAL_CONFIGS   project-scope config files, relative to the workspace
    FORMAT          "json" (default) or "toml"
    ROOT_KEY        JSON root key ("mcpServers", "servers", "mcp", ...)
    entry(...)      optional: build the per-harness server entry
    render(...)     optional: full override for merging into existing text
    remove(...)     optional: strip the server entry (None = nothing to remove)

Search order (later wins): builtin package → ``<repo>/harnesses`` →
``<workspace>/harnesses``. A user plugin overrides a builtin by NAME; bad
plugins are logged and skipped.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import shutil
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from simple_code_indexer.harnesses import _json, _toml

logger = logging.getLogger(__name__)

EntryFn = Callable[[list[str], dict[str, str]], dict[str, Any]]
RenderFn = Callable[..., str]
RemoveFn = Callable[..., str | None]

_which = shutil.which
_UNRESOLVED_VAR = re.compile(r"%[^%]+%")


@dataclass(frozen=True, slots=True)
class HarnessSpec:
    name: str
    label: str
    home_dirs: tuple[str, ...]
    binaries: tuple[str, ...]
    global_configs: tuple[str, ...]
    local_configs: tuple[str, ...]
    format: str
    entry: EntryFn
    render: RenderFn
    remove: RemoveFn

    def detected(self, home: Path | None = None) -> bool:
        """True when one of the harness's home folders or binaries exists."""
        root = home or Path.home()
        for raw in self.home_dirs:
            path = _expand(raw, root, root)
            if path is not None and path.is_dir():
                return True
        return any(_which(binary) is not None for binary in self.binaries)

    def candidates(
        self, scope: str, workspace: Path, home: Path | None = None
    ) -> list[Path]:
        """Config paths to try for "global" or "local" scope (may not exist)."""
        raw = self.global_configs if scope == "global" else self.local_configs
        paths: list[Path] = []
        for item in raw:
            path = _expand(item, workspace, home)
            if path is not None:
                paths.append(path)
        return paths


def _expand(raw: str, base: Path, home: Path | None = None) -> Path | None:
    """Expand ~ and environment variables; None when a variable stays unresolved."""
    expanded = os.path.expandvars(raw)
    if _UNRESOLVED_VAR.search(expanded):
        return None
    if expanded == "~" or expanded.startswith(("~/", "~\\")):
        root = home or Path.home()
        expanded = str(root) + expanded[1:]
    path = Path(expanded)
    return path if path.is_absolute() else base / path


_HARNESSES: tuple[HarnessSpec, ...] | None = None
_HARNESSES_LOCK = threading.Lock()


def get_harnesses() -> tuple[HarnessSpec, ...]:
    global _HARNESSES
    if _HARNESSES is None:
        with _HARNESSES_LOCK:
            if _HARNESSES is None:
                _HARNESSES = tuple(load_harnesses())
    return _HARNESSES


def reset_harnesses() -> None:
    """Drop the cached plugin list (tests only)."""
    global _HARNESSES
    with _HARNESSES_LOCK:
        _HARNESSES = None


def load_harnesses(
    *,
    user_dirs: Sequence[Path] | None = None,
    include_builtin: bool = True,
) -> list[HarnessSpec]:
    """Build a fresh list; `user_dirs=None` uses the default search paths."""
    specs: dict[str, HarnessSpec] = {}
    if include_builtin:
        _load_dir(specs, Path(__file__).resolve().parent, prefix="builtin")
    directories = (
        list(user_dirs) if user_dirs is not None else default_user_harness_dirs()
    )
    for directory in directories:
        _load_dir(specs, directory, prefix="user")
    return [specs[name] for name in sorted(specs)]


def default_user_harness_dirs() -> list[Path]:
    """Repo-root harnesses/ (walk up to pyproject.toml) then workspace harnesses/."""
    from simple_code_indexer.config import workspace_root_from_env

    dirs: list[Path] = []
    repo_harnesses = _repo_harnesses_dir()
    if repo_harnesses is not None:
        dirs.append(repo_harnesses)
    dirs.append(workspace_root_from_env() / "harnesses")
    return dirs


def _repo_harnesses_dir() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent / "harnesses"
    return Path.cwd() / "harnesses"


def _load_dir(specs: dict[str, HarnessSpec], directory: Path, *, prefix: str) -> None:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        spec = _load_file(path, prefix=prefix)
        if spec is None:
            continue
        specs[spec.name] = spec


def _load_file(path: Path, *, prefix: str) -> HarnessSpec | None:
    module_name = f"simple_code_indexer._harness_{prefix}_{path.stem}"
    loader_spec = importlib.util.spec_from_file_location(module_name, path)
    if loader_spec is None or loader_spec.loader is None:
        logger.warning("cannot load harness plugin %s", path)
        return None
    module = importlib.util.module_from_spec(loader_spec)
    try:
        loader_spec.loader.exec_module(module)
    except Exception:
        logger.warning("harness plugin %s raised on import", path, exc_info=True)
        return None
    return _spec_from_module(module, path)


def _spec_from_module(module: ModuleType, path: Path) -> HarnessSpec | None:
    name = getattr(module, "NAME", None)
    if not isinstance(name, str) or not name:
        logger.warning("harness plugin %s missing NAME", path)
        return None
    label = getattr(module, "LABEL", name)
    if not isinstance(label, str) or not label:
        label = name
    global_configs = _string_tuple(module, "GLOBAL_CONFIGS", path)
    local_configs = _string_tuple(module, "LOCAL_CONFIGS", path)
    if not global_configs and not local_configs:
        logger.warning("harness plugin %s declares no config paths", path)
        return None
    render = getattr(module, "render", None)
    if render is not None and not callable(render):
        logger.warning("harness plugin %s render must be callable", path)
        return None
    remove = getattr(module, "remove", None)
    if remove is not None and not callable(remove):
        logger.warning("harness plugin %s remove must be callable", path)
        return None
    entry = getattr(module, "entry", None)
    if entry is not None and not callable(entry):
        logger.warning("harness plugin %s entry must be callable", path)
        return None
    fmt = getattr(module, "FORMAT", "json")
    if fmt not in {"json", "toml"}:
        logger.warning("harness plugin %s FORMAT must be json or toml", path)
        return None
    try:
        resolved_entry = cast(EntryFn, entry) if entry is not None else _default_entry
        resolved_render = (
            cast(RenderFn, render)
            if render is not None
            else _build_render(module, path, fmt)
        )
        resolved_remove = (
            cast(RemoveFn, remove)
            if remove is not None
            else _build_remove(module, path, fmt)
        )
    except ValueError as exc:
        logger.warning("harness plugin %s: %s", path, exc)
        return None
    return HarnessSpec(
        name=name,
        label=label,
        home_dirs=_string_tuple(module, "HOME_DIRS", path),
        binaries=_string_tuple(module, "BINARIES", path),
        global_configs=global_configs,
        local_configs=local_configs,
        format=fmt,
        entry=resolved_entry,
        render=resolved_render,
        remove=resolved_remove,
    )


def _build_render(module: ModuleType, path: Path, fmt: str) -> RenderFn:
    entry = getattr(module, "entry", None)
    entry_fn = cast(EntryFn, entry) if callable(entry) else _default_entry
    if fmt == "toml":
        return lambda existing, *, name, command, env: _toml.upsert(
            existing, name=name, command=command, env=env
        )
    root_key = getattr(module, "ROOT_KEY", None)
    if not isinstance(root_key, str) or not root_key:
        raise ValueError("ROOT_KEY is required for JSON harness plugins")
    return lambda existing, *, name, command, env: _json.upsert(
        existing,
        root_key=root_key,
        name=name,
        entry=entry_fn(command, env),
    )


def _build_remove(module: ModuleType, path: Path, fmt: str) -> RemoveFn:
    if fmt == "toml":
        return lambda existing, *, name: _toml.remove(existing, name=name)
    root_key = getattr(module, "ROOT_KEY", None)
    if not isinstance(root_key, str) or not root_key:
        raise ValueError("ROOT_KEY is required for JSON harness plugins")
    return lambda existing, *, name: _json.remove(
        existing, root_key=root_key, name=name
    )


def _default_entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    entry: dict[str, Any] = {"command": command[0]}
    if len(command) > 1:
        entry["args"] = command[1:]
    if env:
        entry["env"] = env
    return entry


def _string_tuple(module: ModuleType, attr: str, path: Path) -> tuple[str, ...]:
    raw = getattr(module, attr, ()) or ()
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        logger.warning("harness plugin %s %s must be a list of strings", path, attr)
        return ()
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            logger.warning("harness plugin %s %s must be strings", path, attr)
            return ()
        values.append(item)
    return tuple(values)
