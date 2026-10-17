"""Builtin Make plugin: rule targets (generic name-field walker finds nothing)."""

from __future__ import annotations

from typing import Any

from simple_code_indexer.models import Symbol
from simple_code_indexer.parse import _text, _walk

NAME = "make"
GRAMMAR = "make"
EXTENSIONS = [".mk"]
FILENAMES = ["Makefile", "makefile", "GNUmakefile"]


def extract(root: Any, source: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    for node in _walk(root):
        if node.type not in ("rule", "rule_block"):
            continue
        targets = node.child_by_field_name("targets")
        name = None
        if targets is not None and targets.named_child_count > 0:
            name = _text(targets.named_children[0], source).strip()
        elif targets is not None:
            name = _text(targets, source).strip()
        if not name:
            continue
        symbols.append(
            Symbol(
                name=name.split()[0],
                kind="rule",
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=_text(node, source).splitlines()[0].strip() or None,
            )
        )
    return symbols
