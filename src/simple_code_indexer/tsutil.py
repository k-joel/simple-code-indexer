"""Tree-sitter node helpers shared by `parse` and the language extractors.

Kept in a standalone module so `languages/extractors.py` can use them without
importing `parse` (which imports the registry, which imports the catalog).
"""

from __future__ import annotations

from typing import Any


def walk(root: Any) -> list[Any]:
    """Iterative pre-order node list (no recursion: deep trees are common)."""
    nodes: list[Any] = []
    stack = [root]
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(reversed(node.children))
    return nodes


def text(node: Any, source: str) -> str:
    """Source text covered by a node."""
    return source.encode("utf-8")[node.start_byte : node.end_byte].decode("utf-8")


def signature(node: Any, source: str) -> str:
    """Node text up to its body — e.g. `uint32_t f(const Widget&)`.

    Declaration nodes with no `body` field (`type_spec`, `namespace_definition`,
    Zig's `FnProto`) would otherwise return the entire node, body included. For
    those the signature stops at the first `{` or newline, which keeps it to the
    declaration line.
    """
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else node.end_byte
    raw = (
        source.encode("utf-8")[node.start_byte : end]
        .decode("utf-8")
        .rstrip()
        .rstrip(";")
    )
    if body is not None:
        return raw
    for marker in ("{", "\n"):
        cut = raw.find(marker)
        if cut > 0:
            raw = raw[:cut]
    return raw.rstrip().rstrip(";")
