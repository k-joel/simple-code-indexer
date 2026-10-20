"""Builtin Cline harness plugin (VS Code globalStorage, global config only)."""

NAME = "cline"
LABEL = "Cline"
HOME_DIRS = [
    "%APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev",
    "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev",
    "~/.config/Code/User/globalStorage/saoudrizwan.claude-dev",
]
BINARIES = ["code"]
GLOBAL_CONFIGS = [
    "%APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
    "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
    "~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
    "%APPDATA%/Code - Insiders/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
    "~/Library/Application Support/Code - Insiders/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
    "~/.config/Code - Insiders/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
]
LOCAL_CONFIGS: list[str] = []
ROOT_KEY = "mcpServers"
