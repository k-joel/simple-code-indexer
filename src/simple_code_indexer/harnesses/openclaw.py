"""Builtin OpenClaw harness plugin (`mcp.servers.<name>`, JSON5 config).

OpenClaw keeps one config at `~/.openclaw/openclaw.json` (JSON5: comments and
trailing commas allowed) and has no project scope. The layout and the
`openclaw mcp` command come from the official docs
(`docs.openclaw.ai/cli/mcp`, `…/gateway/config-extensions`).

**No `cli_add` is declared on purpose.** The build installed on the dev host
(2026.2.26, `bc50708`) has no `mcp` command and rejects `mcp` as a config key
outright — `openclaw config set mcp.servers.<name> …` writes the file and then
exits with "Unrecognized key: mcp", which would leave a config the client
refuses to load. The wizard's merge is therefore the only writer until a
release that documents MCP ships it; add `cli_add` (`openclaw mcp set <name>
<json>` / `openclaw mcp unset <name>`) at that point. See ISSUES.md.

Stdio definitions take `command`/`args`/`env`; `requestTimeoutMs` is left at the
client default.
"""

from __future__ import annotations

from typing import Any

NAME = "openclaw"
LABEL = "OpenClaw"
HOME_DIRS = ["~/.openclaw", "%APPDATA%/openclaw"]
BINARIES = ["openclaw"]
GLOBAL_CONFIGS = [
    "~/.openclaw/openclaw.json",
    "%APPDATA%/openclaw/openclaw.json",
]
LOCAL_CONFIGS: list[str] = []
ROOT_KEY = "mcp.servers"


def entry(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    value: dict[str, Any] = {"command": command[0]}
    if len(command) > 1:
        value["args"] = command[1:]
    if env:
        value["env"] = dict(env)
    return value
