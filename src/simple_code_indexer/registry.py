"""Language registry: the catalog turned into extension/filename lookups.

The table itself lives in :mod:`simple_code_indexer.languages.catalog`; this
module only indexes it. Languages in ``catalog.DATA_FORMATS`` are skipped, so
data/documentation files are never detected and never enter the index.

There are no user drop-ins: extending language support means editing the
catalog (regenerate it with ``tools/gen_language_catalog.py``).
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from simple_code_indexer.languages import catalog
from simple_code_indexer.languages.spec import ExtractFn, LanguageSpec

__all__ = [
    "ExtractFn",
    "LanguageSpec",
    "PluginRegistry",
    "get_registry",
    "load_registry",
    "prefetch_grammars",
    "reset_registry",
    "start_prefetch_thread",
]

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Resolved languages: name → spec, extension/filename → name."""

    def __init__(self) -> None:
        self._specs: dict[str, LanguageSpec] = {}
        self._by_ext: dict[str, str] = {}
        self._by_filename: dict[str, str] = {}

    def detect(self, path: Path) -> LanguageSpec | None:
        """Exact filename first, then the lowercased final suffix."""
        name = self._by_filename.get(path.name)
        if name is None:
            name = self._by_ext.get(path.suffix.lower())
        if name is None:
            return None
        return self._specs.get(name)

    def spec(self, name: str) -> LanguageSpec | None:
        return self._specs.get(name)

    def extension_allowlist(self) -> frozenset[str]:
        return frozenset(self._by_ext)

    def filename_allowlist(self) -> frozenset[str]:
        return frozenset(self._by_filename)

    def grammars(self) -> tuple[str, ...]:
        return tuple(sorted({spec.grammar for spec in self._specs.values()}))

    def mapped_grammars(self) -> tuple[str, ...]:
        """Grammars that can actually produce symbols (prefetch targets).

        Prefetching the whole catalog would download ~370 grammars on first run
        for a marginal benefit; only the languages that resolve symbols need to
        be ready eagerly.
        """
        return tuple(
            sorted(
                {spec.grammar for spec in self._specs.values() if spec.symbol_mapped}
            )
        )

    def __len__(self) -> int:
        return len(self._specs)

    def _register(self, spec: LanguageSpec) -> None:
        """Insert one entry, releasing a duplicate extension/filename claim."""
        self._specs[spec.name] = spec
        for ext in spec.extensions:
            owner = self._by_ext.get(ext)
            if owner is not None and owner != spec.name:
                # The catalog is generated with unique ownership; a collision
                # means a hand edit or a stale generated file.
                logger.warning(
                    "language %s takes %s from %s (catalog collision)",
                    spec.name,
                    ext,
                    owner,
                )
            self._by_ext[ext] = spec.name
        for filename in spec.filenames:
            owner = self._by_filename.get(filename)
            if owner is not None and owner != spec.name:
                logger.warning(
                    "language %s takes %r from %s (catalog collision)",
                    spec.name,
                    filename,
                    owner,
                )
            self._by_filename[filename] = spec.name


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


def load_registry() -> PluginRegistry:
    """Build a fresh registry from the catalog, minus the data formats."""
    registry = PluginRegistry()
    for spec in catalog.ENTRIES:
        if spec.name in catalog.DATA_FORMATS:
            continue
        registry._register(spec)
    logger.debug(
        "language registry: %d language(s), %d data format(s) excluded",
        len(registry),
        len(catalog.DATA_FORMATS),
    )
    return registry


def prefetch_grammars(registry: PluginRegistry | None = None) -> None:
    """Best-effort load the grammars in `catalog.PREFETCH` (never raises).

    Deliberately *not* every symbol-mapped grammar: a map exists for nearly the
    whole catalog, and loading them all would download the entire pack on first
    run. A language outside the prefetch set still extracts symbols; its grammar
    loads on the first file indexed (ADR-016).
    """
    from simple_code_indexer import parse

    reg = registry if registry is not None else get_registry()
    grammars = tuple(
        sorted(name for name in catalog.PREFETCH if reg.spec(name) is not None)
    )
    loaded = 0
    for grammar in grammars:
        try:
            parse._parser(grammar)
            loaded += 1
        except Exception:
            logger.warning("grammar prefetch failed for %r", grammar, exc_info=True)
    logger.info("grammar prefetch: %d/%d grammar(s) ready", loaded, len(grammars))


def start_prefetch_thread() -> threading.Thread | None:
    """Daemon-thread prefetch so startup stays fast. None when disabled."""
    if os.environ.get("PREFETCH_GRAMMARS", "1") == "0":
        return None

    def _run() -> None:
        prefetch_grammars()

    thread = threading.Thread(target=_run, name="grammar-prefetch", daemon=True)
    thread.start()
    return thread
