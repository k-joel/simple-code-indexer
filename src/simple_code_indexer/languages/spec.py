"""The one language entry type shared by the catalog and the registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

ExtractFn = Callable[[Any, str], list[Any]]


@dataclass(frozen=True, slots=True)
class LanguageSpec:
    """One language: its id, grammar, matching rules, and symbol extraction."""

    name: str
    grammar: str
    extensions: frozenset[str]
    filenames: frozenset[str]
    symbol_nodes: dict[str, str] = field(default_factory=dict)
    extract: ExtractFn | None = None
    injections: bool = False

    @property
    def symbol_mapped(self) -> bool:
        """True when this language can resolve symbols on its own."""
        return self.extract is not None or bool(self.symbol_nodes) or self.injections
