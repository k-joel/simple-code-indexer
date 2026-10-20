"""Marker-block TOML merge for Codex-style `config.toml`.

`tomllib` is read-only, so instead of rewriting the user's file we own a marked
block and replace it wholesale. Everything outside the markers is untouched.
"""

from __future__ import annotations

import json

_BEGIN = "# >>> simple-code-indexer >>>"
_END = "# <<< simple-code-indexer <<<"


def upsert(existing: str, *, name: str, command: list[str], env: dict[str, str]) -> str:
    block = _render(name, command, env)
    if _BEGIN in existing and _END in existing:
        before, _, rest = existing.partition(_BEGIN)
        _, _, after = rest.partition(_END)
        return before + block + after.lstrip("\r\n")
    body = existing.rstrip("\n")
    separator = "\n\n" if body else ""
    return body + separator + block


def _render(name: str, command: list[str], env: dict[str, str]) -> str:
    lines = [
        _BEGIN,
        f"[mcp_servers.{json.dumps(name)}]",
        f"command = {json.dumps(command[0])}",
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
