"""JSON/JSONC merge helper: update one server entry, preserve everything else."""

from __future__ import annotations

import json
import re
from typing import Any

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


class ParseError(ValueError):
    """The existing file is not JSON/JSONC we can safely rewrite."""


def parse(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        try:
            document = json.loads(_strip_jsonc(text))
        except json.JSONDecodeError as exc:
            raise ParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ParseError("top-level JSON value must be an object")
    return document


def upsert(existing: str, *, root_key: str, name: str, entry: dict[str, Any]) -> str:
    """Set `root_key[name] = entry` and re-serialize the whole document."""
    document = parse(existing)
    servers = document.setdefault(root_key, {})
    if not isinstance(servers, dict):
        raise ParseError(f"'{root_key}' must be an object")
    servers[name] = entry
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _strip_jsonc(text: str) -> str:
    """Best-effort comment/trailing-comma removal so OpenCode `.jsonc` parses."""
    output: list[str] = []
    index = 0
    in_string = False
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if char == "\\" and index + 1 < len(text):
                output.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(text):
            following = text[index + 1]
            if following == "/":
                index += 2
                while index < len(text) and text[index] not in "\r\n":
                    index += 1
                continue
            if following == "*":
                index += 2
                while index + 1 < len(text) and not (
                    text[index] == "*" and text[index + 1] == "/"
                ):
                    index += 1
                index += 2
                continue
        output.append(char)
        index += 1
    cleaned = "".join(output)
    while True:
        reduced = _TRAILING_COMMA.sub(r"\1", cleaned)
        if reduced == cleaned:
            return cleaned
        cleaned = reduced
