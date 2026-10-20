"""Builtin Gemini CLI harness plugin."""

NAME = "gemini_cli"
LABEL = "Gemini CLI"
HOME_DIRS = [".gemini"]
BINARIES = ["gemini"]
GLOBAL_CONFIGS = ["~/.gemini/settings.json"]
LOCAL_CONFIGS = [".gemini/settings.json"]
ROOT_KEY = "mcpServers"
