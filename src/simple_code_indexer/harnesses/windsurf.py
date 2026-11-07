"""Builtin Windsurf / Devin Local harness plugin."""

NAME = "windsurf"
LABEL = "Windsurf / Devin Local"
HOME_DIRS = ["~/.config/devin", "~/.codeium/windsurf", "%APPDATA%/devin"]
BINARIES = ["windsurf", "devin"]
GLOBAL_CONFIGS = [
    "~/.config/devin/mcp_config.json",
    "%APPDATA%/devin/mcp_config.json",
    "~/.codeium/windsurf/mcp_config.json",
]
LOCAL_CONFIGS = [".devin/mcp_config.json"]
ROOT_KEY = "mcpServers"
