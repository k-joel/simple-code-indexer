"""Language plugin registry: drop-in modules that extend the allowlist,
grammar mapping, and (optionally) symbol extraction.

Search order (later wins): builtin/*.py → repo-root plugins/ →
$WORKSPACE_ROOT/plugins/. A user plugin may override a builtin by NAME and
steals every extension/filename it claims. Bad plugins are skipped, never fatal.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, cast

logger = logging.getLogger(__name__)

# Builtin-vs-builtin extension owners (v1 mapping + original preference).
_EXT_OWNERS: dict[str, str] = {".h": "cpp", ".m": "objc"}

ExtractFn = Callable[[Any, str], list[Any]]


@dataclass(frozen=True, slots=True)
class LanguageSpec:
    """One loaded language plugin (builtin or user)."""

    name: str
    grammar: str
    extensions: frozenset[str]
    filenames: frozenset[str]
    symbol_nodes: dict[str, str] = field(default_factory=dict)
    extract: ExtractFn | None = None

    def matches(self, path: Path) -> bool:
        return path.name in self.filenames or path.suffix.lower() in self.extensions


class PluginRegistry:
    """Resolved language plugins: name → spec, extension/filename → name."""

    def __init__(self) -> None:
        self._specs: dict[str, LanguageSpec] = {}
        self._by_ext: dict[str, str] = {}
        self._by_filename: dict[str, str] = {}

    def detect(self, path: Path) -> LanguageSpec | None:
        name = self._by_filename.get(path.name)
        if name is None:
            name = self._by_ext.get(path.suffix.lower())
        if name is None:
            return None
        return self._specs.get(name)

    def spec(self, name: str) -> LanguageSpec | None:
        return self._specs.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def extension_allowlist(self) -> frozenset[str]:
        return frozenset(self._by_ext)

    def filename_allowlist(self) -> frozenset[str]:
        return frozenset(self._by_filename)

    def grammars(self) -> tuple[str, ...]:
        return tuple(sorted({spec.grammar for spec in self._specs.values()}))

    def __len__(self) -> int:
        return len(self._specs)

    def _register(self, spec: LanguageSpec, *, user: bool) -> None:
        self._free_name(spec.name)
        extensions: set[str] = set()
        for ext in spec.extensions:
            owner = self._by_ext.get(ext)
            wins = owner is None or user or _EXT_OWNERS.get(ext) == spec.name
            if wins:
                if owner is not None and owner != spec.name:
                    self._release_ext_from(owner, ext)
                self._by_ext[ext] = spec.name
                extensions.add(ext)
            else:
                logger.debug("plugin %s loses %s to %s", spec.name, ext, owner)
        filenames: set[str] = set()
        for filename in spec.filenames:
            owner = self._by_filename.get(filename)
            wins = owner is None or user
            if wins:
                if owner is not None and owner != spec.name:
                    self._release_filename_from(owner, filename)
                self._by_filename[filename] = spec.name
                filenames.add(filename)
        self._specs[spec.name] = LanguageSpec(
            name=spec.name,
            grammar=spec.grammar,
            extensions=frozenset(extensions),
            filenames=frozenset(filenames),
            symbol_nodes=dict(spec.symbol_nodes),
            extract=spec.extract,
        )

    def _free_name(self, name: str) -> None:
        previous = self._specs.pop(name, None)
        if previous is None:
            return
        for ext in previous.extensions:
            if self._by_ext.get(ext) == name:
                del self._by_ext[ext]
        for filename in previous.filenames:
            if self._by_filename.get(filename) == name:
                del self._by_filename[filename]

    def _release_ext_from(self, owner: str, ext: str) -> None:
        previous = self._specs.get(owner)
        if previous is None or ext not in previous.extensions:
            return
        self._specs[owner] = LanguageSpec(
            name=previous.name,
            grammar=previous.grammar,
            extensions=previous.extensions - {ext},
            filenames=previous.filenames,
            symbol_nodes=dict(previous.symbol_nodes),
            extract=previous.extract,
        )

    def _release_filename_from(self, owner: str, filename: str) -> None:
        previous = self._specs.get(owner)
        if previous is None or filename not in previous.filenames:
            return
        self._specs[owner] = LanguageSpec(
            name=previous.name,
            grammar=previous.grammar,
            extensions=previous.extensions,
            filenames=previous.filenames - {filename},
            symbol_nodes=dict(previous.symbol_nodes),
            extract=previous.extract,
        )


_REGISTRY: PluginRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> PluginRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = load_registry()
    return _REGISTRY


def reset_registry() -> None:
    """Drop the cached registry (tests only)."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = None


def load_registry(
    *,
    user_dirs: Sequence[Path] | None = None,
    include_builtin: bool = True,
) -> PluginRegistry:
    """Build a fresh registry; `user_dirs=None` uses the default search paths."""
    registry = PluginRegistry()
    if include_builtin:
        builtin_dir = Path(__file__).resolve().parent / "builtin"
        _load_dir(registry, builtin_dir, prefix="builtin", user=False)
    dirs = list(user_dirs) if user_dirs is not None else default_user_plugin_dirs()
    for directory in dirs:
        _load_dir(registry, directory, prefix="user", user=True)
    return registry


def default_user_plugin_dirs() -> list[Path]:
    """Repo-root plugins/ (walk up to pyproject.toml) then workspace plugins/."""
    from simple_code_indexer.config import workspace_root_from_env

    dirs: list[Path] = []
    repo_plugins = _repo_plugins_dir()
    if repo_plugins is not None:
        dirs.append(repo_plugins)
    dirs.append(workspace_root_from_env() / "plugins")
    return dirs


def prefetch_grammars(registry: PluginRegistry | None = None) -> None:
    """Best-effort load every grammar into parse's cache (never raises)."""
    from simple_code_indexer import parse

    reg = registry if registry is not None else get_registry()
    for grammar in reg.grammars():
        try:
            parse._parser(grammar)
        except Exception:
            logger.warning("grammar prefetch failed for %r", grammar, exc_info=True)


def start_prefetch_thread() -> threading.Thread | None:
    """Daemon-thread prefetch so startup stays <3 s. None when disabled."""
    if os.environ.get("PREFETCH_GRAMMARS", "1") == "0":
        return None

    def _run() -> None:
        prefetch_grammars()

    thread = threading.Thread(target=_run, name="grammar-prefetch", daemon=True)
    thread.start()
    return thread


def _repo_plugins_dir() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent / "plugins"
    return Path.cwd() / "plugins"


def _load_dir(
    registry: PluginRegistry, directory: Path, *, prefix: str, user: bool
) -> None:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        spec = _load_file(path, prefix=prefix)
        if spec is None:
            continue
        if registry.spec(spec.name) is not None and not user:
            logger.debug("builtin %s replaces earlier entry", spec.name)
        registry._register(spec, user=user)


def _load_file(path: Path, *, prefix: str) -> LanguageSpec | None:
    module_name = f"simple_code_indexer._plugin_{prefix}_{path.stem}"
    loader_spec = importlib.util.spec_from_file_location(module_name, path)
    if loader_spec is None or loader_spec.loader is None:
        logger.warning("cannot load plugin %s", path)
        return None
    module = importlib.util.module_from_spec(loader_spec)
    try:
        loader_spec.loader.exec_module(module)
    except Exception:
        logger.warning("plugin %s raised on import", path, exc_info=True)
        return None
    return _spec_from_module(module, path)


def _spec_from_module(module: ModuleType, path: Path) -> LanguageSpec | None:
    name = getattr(module, "NAME", None)
    grammar = getattr(module, "GRAMMAR", None)
    if not isinstance(name, str) or not name:
        logger.warning("plugin %s missing NAME", path)
        return None
    if not isinstance(grammar, str) or not grammar:
        logger.warning("plugin %s missing GRAMMAR", path)
        return None
    extensions, filenames = _tokens(module, path, name)
    if not extensions and not filenames:
        logger.warning("plugin %s declares no EXTENSIONS/FILENAMES", path)
        return None
    symbol_nodes = getattr(module, "SYMBOL_NODES", {})
    if symbol_nodes is None:
        symbol_nodes = {}
    if not isinstance(symbol_nodes, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in symbol_nodes.items()
    ):
        logger.warning("plugin %s SYMBOL_NODES must be dict[str, str]", path)
        return None
    extract = getattr(module, "extract", None)
    if extract is not None and not callable(extract):
        logger.warning("plugin %s extract must be callable", path)
        return None
    extract_fn = cast("ExtractFn | None", extract)
    return LanguageSpec(
        name=name,
        grammar=grammar,
        extensions=frozenset(extensions),
        filenames=frozenset(filenames),
        symbol_nodes=dict(symbol_nodes),
        extract=extract_fn,
    )


def _tokens(module: ModuleType, path: Path, name: str) -> tuple[set[str], set[str]]:
    """Normalize EXTENSIONS/FILENAMES. Bare (non-dotted) tokens are filenames."""
    extensions: set[str] = set()
    filenames: set[str] = set()
    raw_exts = getattr(module, "EXTENSIONS", ()) or ()
    raw_fns = getattr(module, "FILENAMES", ()) or ()
    if isinstance(raw_exts, str) or not isinstance(raw_exts, Iterable):
        logger.warning("plugin %s EXTENSIONS must be a list of strings", path)
        return set(), set()
    if isinstance(raw_fns, str) or not isinstance(raw_fns, Iterable):
        logger.warning("plugin %s FILENAMES must be a list of strings", path)
        return set(), set()
    for token in raw_exts:
        if not isinstance(token, str) or not token:
            logger.warning("plugin %s EXTENSIONS must be strings", path)
            return set(), set()
        if token.startswith("."):
            extensions.add(token.lower())
        else:
            filenames.add(token)
    for token in raw_fns:
        if not isinstance(token, str) or not token:
            logger.warning("plugin %s FILENAMES must be strings", path)
            return set(), set()
        filenames.add(token)
    _ = name  # reserved for future per-module validation messages
    return extensions, filenames
