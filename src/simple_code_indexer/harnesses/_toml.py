"""Marker-block TOML merge for Codex-style `config.toml`.

`tomllib` is read-only, so instead of rewriting the user's file we own a marked
block and replace it wholesale. Everything outside the markers is untouched.
"""

from __future__ import annotations

import json

_BEGIN = "# >>> simple-code-indexer >>>"
_END = "# <<< simple-code-indexer <<<"
STARTUP_TIMEOUT_SEC = 120


def upsert(existing: str, *, name: str, command: list[str], env: dict[str, str]) -> str:
    block = _render(name, command, env)
    if _BEGIN in existing and _END in existing:
        before, _, rest = existing.partition(_BEGIN)
        _, _, after = rest.partition(_END)
        return before + block + after.lstrip("\r\n")
    body = existing.rstrip("\n")
    separator = "\n\n" if body else ""
    return body + separator + block


def remove(existing: str, *, name: str) -> str | None:
    """Strip the marker block; None when absent, "" when nothing else remains.

    The block is ours alone, so `name` is only accepted for symmetry with
    `upsert` and the JSON helper.
    """
    del name
    if _BEGIN not in existing or _END not in existing:
        return None
    before, _, rest = existing.partition(_BEGIN)
    _, _, after = rest.partition(_END)
    head = before.rstrip("\r\n")
    tail = after.lstrip("\r\n")
    if head and tail:
        return f"{head}\n\n{tail}"
    if head:
        return f"{head}\n"
    return tail


def _render(name: str, command: list[str], env: dict[str, str]) -> str:
    lines = [
        _BEGIN,
        f"[mcp_servers.{json.dumps(name)}]",
        f"command = {json.dumps(command[0])}",
        f"startup_timeout_sec = {STARTUP_TIMEOUT_SEC}",
    ]
    if len(command) > 1:
        lines.append(f"args = {json.dumps(command[1:])}")
    if env:
        pairs = ", ".join(
            f"{json.dumps(key)} = {json.dumps(value)}" for key, value in env.items()
        )
        lines.append(f"env = {{ {pairs} }}")
    lines.append(_END)
    return "\n".join(lines) + "\n"
