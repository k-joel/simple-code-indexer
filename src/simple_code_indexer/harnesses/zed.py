"""Builtin Zed harness plugin (`context_servers`, not `mcpServers`)."""

NAME = "zed"
LABEL = "Zed"
HOME_DIRS = ["~/.config/zed", "%APPDATA%/Zed", "~/.zed"]
BINARIES = ["zed"]
GLOBAL_CONFIGS = ["~/.config/zed/settings.json", "%APPDATA%/Zed/settings.json"]
LOCAL_CONFIGS = [".zed/settings.json"]
ROOT_KEY = "context_servers"
