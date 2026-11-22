"""Harness plugins: how each MCP client stores its server list.

Contract (plain module globals):

    NAME            stable id (file stem by convention)
    LABEL           human label shown by the setup wizard
    HOME_DIRS       detection dirs, relative to home or absolute (%VARS% expand)
    BINARIES        optional CLI names that also count as "installed"
    GLOBAL_CONFIGS  user-scope config files (``~``, ``%APPDATA%`` supported)
    LOCAL_CONFIGS   project-scope config files, relative to the workspace
    FORMAT          "json" (default), "toml" or "yaml"
    ROOT_KEY        config root key ("mcpServers", "servers", "mcp", ...)
    entry(...)      optional: build the per-harness server entry
    render(...)     optional: full override for merging into existing text
    remove(...)     optional: strip the server entry (None = nothing to remove)
    resolve_workspace(cwd)  optional: publish this session's workspace at runtime

A plugin that implements ``resolve_workspace`` must also put the reserved
``SIMPLE_CI_HARNESS=<NAME>`` key into its entry env (``RUNTIME_ENV``), so the
server asks that plugin — and only that plugin — for the workspace. The key is
install-scoped (the same value for every project), never a path. Entries written
before the key existed are still served: when the cwd is not a plausible project
the server asks every resolver instead (see ``discover_workspace``).

Search order (later wins): builtin package → ``<repo>/harnesses`` →
``<workspace>/harnesses``. A user plugin overrides a builtin by NAME; bad
plugins are logged and skipped.

Entries are global-only (ADR-015): a plugin must never put per-project data in
the entry it builds — no ``cwd`` derived from ``env``, no ``WORKSPACE_ROOT``,
``INDEX_DB`` or ``FAISS_PATH``. The wizard passes an empty ``env`` unless
``--no-git-pull`` (debug) adds ``SIMPLE_CI_GIT_PULL=0``, and the
server infers the workspace from its process cwd at runtime (ADR-007).
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

from simple_code_indexer.harnesses import _json, _toml, _yaml

logger = logging.getLogger(__name__)

EntryFn = Callable[[list[str], dict[str, str]], dict[str, Any]]
RenderFn = Callable[..., str]
RemoveFn = Callable[..., str | None]
ResolveWorkspaceFn = Callable[[Path], Path | None]

RUNTIME_ENV = "SIMPLE_CI_HARNESS"
"""Reserved entry env key naming the plugin that launched this session.

Install-scoped, not per-project: the server uses it to pick the one plugin
allowed to publish a workspace at runtime (ADR-018)."""

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
    root_key: str | None
    entry: EntryFn
    render: RenderFn
    remove: RemoveFn
    workspace_resolver: ResolveWorkspaceFn | None = None

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


def default_user_harness_dirs(workspace: Path | None = None) -> list[Path]:
    """Repo-root harnesses/ (walk up to pyproject.toml) then workspace harnesses/.

    `workspace` is explicit when the caller is *resolving* the workspace
    (`discover_workspace`); otherwise `workspace_root_from_env()` is used.
    """
    from simple_code_indexer.config import workspace_root_from_env

    dirs: list[Path] = []
    repo_harnesses = _repo_harnesses_dir()
    if repo_harnesses is not None:
        dirs.append(repo_harnesses)
    base = workspace if workspace is not None else workspace_root_from_env()
    dirs.append(base / "harnesses")
    return dirs


def discover_workspace(
    cwd: Path, *, require_marker: bool = True
) -> tuple[Path, str] | None:
    """Workspace published by the harness that launched this session.

    The entry names its plugin through `RUNTIME_ENV`; only that plugin is
    asked, and only it can answer (ADR-018). ``require_marker=False`` asks every
    plugin that declares a resolver (the marked one first): an entry installed
    before the marker existed then keeps working after a package update, with no
    setup re-run. Fail-soft: an unknown plugin, a resolver
    that raises, or a result that is not an existing directory all fall through
    to the caller's next workspace source.
    """
    name = os.environ.get(RUNTIME_ENV)
    if require_marker and not name:
        return None
    specs = load_harnesses(user_dirs=default_user_harness_dirs(cwd))
    candidates = [item for item in specs if item.workspace_resolver is not None]
    if require_marker:
        candidates = [item for item in candidates if item.name == name]
        if not candidates:
            logger.debug("harness %r declares no workspace resolver", name)
            return None
    elif name:
        candidates.sort(key=lambda item: item.name != name)
    for spec in candidates:
        found = _ask_resolver(spec, cwd)
        if found is not None:
            return found
    if not name:
        logger.debug("no harness declares a workspace for this session")
    return None


def _ask_resolver(spec: HarnessSpec, cwd: Path) -> tuple[Path, str] | None:
    """Ask one plugin for its workspace; never raise (startup must not fail)."""
    resolver = spec.workspace_resolver
    if resolver is None:
        return None
    try:
        found = resolver(cwd)
    except Exception:
        logger.warning("harness %r workspace resolver failed", spec.name, exc_info=True)
        return None
    if found is None:
        logger.debug(
            "harness %r published no workspace for this session; next source wins",
            spec.name,
        )
        return None
    try:
        found = found.resolve()
    except OSError:
        return None
    if not found.is_dir():
        logger.warning(
            "harness %r published %s, which is not a directory", spec.name, found
        )
        return None
    return found, spec.name


def _repo_harnesses_dir() -> Path | None:
    """`<checkout>/harnesses`, or None when running from an installed wheel.

    The check mirrors `setup_wizard._default_repo_root`: the parent must hold this
    package's own `src/` tree. A plain `pyproject.toml` search would adopt the
    enclosing project of an installed package (`.venv/Lib/site-packages/...`) and
    load its drop-ins. Falling back to `Path.cwd() / "harnesses"` would make the
    workspace directory appear twice in the search path.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "src" / "simple_code_indexer" / "__init__.py").is_file():
            return parent / "harnesses"
    return None


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
    resolve_workspace = getattr(module, "resolve_workspace", None)
    if resolve_workspace is not None and not callable(resolve_workspace):
        logger.warning("harness plugin %s resolve_workspace must be callable", path)
        return None
    fmt = getattr(module, "FORMAT", "json")
    if fmt not in {"json", "toml", "yaml"}:
        logger.warning("harness plugin %s FORMAT must be json, toml or yaml", path)
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
        root_key=(
            module.ROOT_KEY
            if isinstance(getattr(module, "ROOT_KEY", None), str)
            else None
        ),
        entry=resolved_entry,
        render=resolved_render,
        remove=resolved_remove,
        workspace_resolver=(
            cast(ResolveWorkspaceFn, resolve_workspace)
            if resolve_workspace is not None
            else None
        ),
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
        raise ValueError("ROOT_KEY is required for JSON and YAML harness plugins")
    merge = _yaml.upsert if fmt == "yaml" else _json.upsert
    return lambda existing, *, name, command, env: merge(
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
        raise ValueError("ROOT_KEY is required for JSON and YAML harness plugins")
    remove = _yaml.remove if fmt == "yaml" else _json.remove
    return lambda existing, *, name: remove(existing, root_key=root_key, name=name)


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
