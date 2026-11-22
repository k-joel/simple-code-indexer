"""Builtin Windsurf / Devin Local harness plugin.

Devin Local reads user servers from `~/.config/devin/mcp_config.json` and
project servers from `.devin/mcp_config.json`; `.devin/mcp_config.local.json`
is its gitignored personal override. There is no CLI for either file.
"""

NAME = "windsurf"
LABEL = "Windsurf / Devin Local"
HOME_DIRS = ["~/.config/devin", "~/.codeium/windsurf", "%APPDATA%/devin"]
BINARIES = ["windsurf", "devin"]
GLOBAL_CONFIGS = [
    "~/.config/devin/mcp_config.json",
    "%APPDATA%/devin/mcp_config.json",
    "~/.codeium/windsurf/mcp_config.json",
]
LOCAL_CONFIGS = [".devin/mcp_config.json", ".devin/mcp_config.local.json"]
ROOT_KEY = "mcpServers"
