"""Builtin Python plugin (moved from parse._extract_python)."""

from __future__ import annotations

from typing import Any

from simple_code_indexer.models import Symbol
from simple_code_indexer.parse import _text, _walk

NAME = "python"
GRAMMAR = "python"
EXTENSIONS = [".py", ".pyw"]
FILENAMES: list[str] = []

_SYMBOL_NODES: dict[str, str] = {
    "function_definition": "function",
    "class_definition": "class",
}


def extract(root: Any, source: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    for node in _walk(root):
        kind = _SYMBOL_NODES.get(node.type)
        if kind is None:
            continue
        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue
        body = node.child_by_field_name("body")
        end = body.start_byte if body is not None else node.end_byte
        raw = source.encode("utf-8")[node.start_byte : end].decode("utf-8").rstrip()
        symbols.append(
            Symbol(
                name=_text(name_node, source),
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=raw.rstrip(":"),
            )
        )
    return symbols
