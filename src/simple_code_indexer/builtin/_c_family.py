"""Shared C/C++ extractor: declarator-chain name resolution (moved from parse.py)."""

from __future__ import annotations

from typing import Any

from simple_code_indexer.models import Symbol
from simple_code_indexer.parse import _signature, _text, _walk

_CPP_NAME_NODES: frozenset[str] = frozenset(
    {
        "identifier",
        "field_identifier",
        "qualified_identifier",
        "destructor_name",
        "operator_name",
        "template_function",
        "type_identifier",
    }
)

_CPP_SYMBOL_NODES: dict[str, str] = {
    "function_definition": "function",
    "class_specifier": "class",
    "struct_specifier": "struct",
    # Prototypes / in-class declarations; only kept when they carry a
    # function_declarator (see extract_c_family).
    "declaration": "function",
    "field_declaration": "function",
    "type_definition": "typedef",
    "alias_declaration": "type_alias",
}


def _function_name(node: Any, source: str) -> str | None:
    """Descend the declarator chain until a named identifier node."""
    current = node.child_by_field_name("declarator")
    if current is None:
        current = node.child_by_field_name("name")
    seen = 0
    while current is not None and seen < 10:
        if current.type in _CPP_NAME_NODES:
            return _text(current, source)
        nested = current.child_by_field_name("declarator")
        if nested is None:
            nested = current.child_by_field_name("name")
        if nested is None and current.named_child_count > 0:
            nested = current.named_children[0]
        current = nested
        seen += 1
    return None


def _contains_function_declarator(node: Any) -> Any | None:
    for child in node.children:
        if child.type == "function_declarator":
            return child
        found = _contains_function_declarator(child)
        if found is not None:
            return found
    return None


def extract_c_family(root: Any, source: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    for node in _walk(root):
        kind = _CPP_SYMBOL_NODES.get(node.type)
        if kind is None:
            continue
        if node.type in ("declaration", "field_declaration"):
            # Keep only real function prototypes/members, not `int x;`.
            declarator = _contains_function_declarator(node)
            if declarator is None:
                continue
            name_node = declarator.child_by_field_name("declarator")
            name = None
            if name_node is not None:
                current = name_node
                seen = 0
                while current is not None and seen < 10:
                    if current.type in _CPP_NAME_NODES:
                        name = _text(current, source)
                        break
                    current = current.child_by_field_name("declarator") or (
                        current.named_children[0] if current.named_child_count else None
                    )
                    seen += 1
            if name is None:
                continue
            signature = _text(node, source).rstrip().rstrip(";")
        else:
            name = _function_name(node, source)
            if name is None:
                continue
            signature = _signature(node, source)
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=signature or None,
            )
        )
    return symbols
