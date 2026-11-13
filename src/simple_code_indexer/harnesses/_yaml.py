"""YAML merge helper for Goose-style `config.yaml`.

The file is re-serialized with `sort_keys=False`, so the user's mapping order is
kept; comments and formatting are not preserved (Goose writes this file itself
and does not add comments).
"""

from __future__ import annotations

from typing import Any

import yaml


class ParseError(ValueError):
    """The existing file is not YAML we can safely rewrite."""


def parse(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ParseError(f"invalid YAML: {exc}") from exc
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ParseError("top-level YAML value must be a mapping")
    return document


def upsert(existing: str, *, root_key: str, name: str, entry: dict[str, Any]) -> str:
    """Set `root_key[name] = entry` and re-serialize the whole document."""
    document = parse(existing)
    servers = _resolve_root(document, root_key)
    servers[name] = entry
    return _dump(document)


def remove(existing: str, *, root_key: str, name: str) -> str | None:
    """Delete `root_key[name]`, pruning emptied containers along the path."""
    document = parse(existing)
    node: dict[str, Any] = document
    chain: list[tuple[dict[str, Any], str]] = []
    for part in root_key.split("."):
        child = node.get(part)
        if not isinstance(child, dict):
            return None
        chain.append((node, part))
        node = child
    if name not in node:
        return None
    del node[name]
    for parent, key in reversed(chain):
        child = parent.get(key)
        if isinstance(child, dict) and not child:
            del parent[key]
    if not document:
        return ""
    return _dump(document)


def _resolve_root(document: dict[str, Any], root_key: str) -> dict[str, Any]:
    node = document
    for part in root_key.split("."):
        value = node.setdefault(part, {})
        if not isinstance(value, dict):
            raise ParseError(f"'{root_key}' must be a mapping")
        node = value
    return node


def _dump(document: dict[str, Any]) -> str:
    return yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
