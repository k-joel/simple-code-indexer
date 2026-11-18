"""Specialized symbol extractors referenced by the catalog.

These beat the generic name-field walker where a grammar has no `name` field on
its declaration nodes (Make rule targets, C/C++ declarator chains) or where the
signature must be trimmed at the body rather than the first `;`.
"""

from __future__ import annotations

from typing import Any

from simple_code_indexer.models import Symbol
from simple_code_indexer.tsutil import signature, text, walk

_PYTHON_SYMBOL_NODES: dict[str, str] = {
    "function_definition": "function",
    "class_definition": "class",
}

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


def extract_python(root: Any, source: str) -> list[Symbol]:
    """Python functions and classes, signature trimmed at the body colon."""
    symbols: list[Symbol] = []
    for node in walk(root):
        kind = _PYTHON_SYMBOL_NODES.get(node.type)
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
                name=text(name_node, source),
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=raw.rstrip(":"),
            )
        )
    return symbols


def extract_make(root: Any, source: str) -> list[Symbol]:
    """Make targets; the generic walker finds nothing (no `name` field).

    `targets` is a named child of `rule`, not a tree-sitter field, so it has to be
    located by node type.
    """
    symbols: list[Symbol] = []
    for node in walk(root):
        if node.type != "rule":
            continue
        targets = next(
            (child for child in node.named_children if child.type == "targets"),
            None,
        )
        if targets is None or targets.named_child_count == 0:
            continue
        name = text(targets.named_children[0], source).strip()
        if not name:
            continue
        symbols.append(
            Symbol(
                name=name,
                kind="rule",
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=text(node, source).splitlines()[0].strip() or None,
            )
        )
    return symbols


def _function_name(node: Any, source: str) -> str | None:
    """Descend the declarator chain until a named identifier node."""
    current = node.child_by_field_name("declarator")
    if current is None:
        current = node.child_by_field_name("name")
    seen = 0
    while current is not None and seen < 10:
        if current.type in _CPP_NAME_NODES:
            return text(current, source)
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
    """C/C++ declarations resolved through the declarator chain."""
    symbols: list[Symbol] = []
    for node in walk(root):
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
                        name = text(current, source)
                        break
                    current = current.child_by_field_name("declarator") or (
                        current.named_children[0] if current.named_child_count else None
                    )
                    seen += 1
            if name is None:
                continue
            node_signature = text(node, source).rstrip().rstrip(";")
        else:
            name = _function_name(node, source)
            if name is None:
                continue
            node_signature = signature(node, source)
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=node_signature or None,
            )
        )
    return symbols
