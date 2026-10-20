"""Builtin Windsurf harness plugin (global config only)."""

NAME = "windsurf"
LABEL = "Windsurf"
HOME_DIRS = ["~/.codeium/windsurf"]
BINARIES = ["windsurf"]
GLOBAL_CONFIGS = ["~/.codeium/windsurf/mcp_config.json"]
LOCAL_CONFIGS: list[str] = []
ROOT_KEY = "mcpServers"
