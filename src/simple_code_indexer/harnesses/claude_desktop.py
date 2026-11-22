"""Builtin Claude Desktop harness plugin.

Claude Desktop has no CLI and no project scope: one config file per user
(`%APPDATA%/Claude/claude_desktop_config.json` on Windows,
`~/Library/Application Support/Claude/…` on macOS), so a project-scope request
falls back to a global entry.
"""

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
