"""Builtin Zed harness plugin (`context_servers`, not `mcpServers`).

Zed stores MCP servers in its settings file (`~/.config/zed/settings.json`, or
`.zed/settings.json` for one project) and has no CLI for them: the editor binary
accepts only paths/`--diff`, and `zed mcp` belongs to the unrelated SpiceDB CLI
from authzed. That name collision is why `zed` is deliberately **not** a
detection or CLI binary here — on a machine with the SpiceDB CLI on `PATH`,
`shutil.which("zed")` finds a program that has nothing to do with the editor,
so detection relies on the config directory instead.
"""

NAME = "zed"
LABEL = "Zed"
HOME_DIRS = ["%APPDATA%/Zed", "~/.config/zed", "~/.zed"]
BINARIES: list[str] = []
# Windows Zed writes `%APPDATA%/Zed/settings.json` (verified on 1.x); the XDG
# path is the macOS/Linux location. `choose_target` prefers an existing file,
# so the order only decides where a *new* file is created — put the
# platform-native one first on Windows.
GLOBAL_CONFIGS = ["%APPDATA%/Zed/settings.json", "~/.config/zed/settings.json"]
LOCAL_CONFIGS = [".zed/settings.json"]
ROOT_KEY = "context_servers"
