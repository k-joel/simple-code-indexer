"""Builtin Claude Desktop harness plugin (global config only)."""

NAME = "claude_desktop"
LABEL = "Claude Desktop"
HOME_DIRS = [
    "%APPDATA%/Claude",
    "~/Library/Application Support/Claude",
    "~/.config/Claude",
]
BINARIES: list[str] = []
GLOBAL_CONFIGS = [
    "%APPDATA%/Claude/claude_desktop_config.json",
    "~/Library/Application Support/Claude/claude_desktop_config.json",
    "~/.config/Claude/claude_desktop_config.json",
]
LOCAL_CONFIGS: list[str] = []
ROOT_KEY = "mcpServers"
