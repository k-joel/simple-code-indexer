"""Builtin Codex CLI harness plugin (TOML, marker-block merge)."""

NAME = "codex"
LABEL = "Codex CLI"
HOME_DIRS = [".codex"]
BINARIES = ["codex"]
GLOBAL_CONFIGS = ["~/.codex/config.toml"]
LOCAL_CONFIGS = [".codex/config.toml"]
FORMAT = "toml"
