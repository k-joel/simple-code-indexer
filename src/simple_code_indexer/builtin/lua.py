"""Builtin Lua plugin."""

NAME = "lua"
GRAMMAR = "lua"
EXTENSIONS = [".lua"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_declaration": "function",
}
