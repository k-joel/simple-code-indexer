"""Builtin Swift plugin."""

NAME = "swift"
GRAMMAR = "swift"
EXTENSIONS = [".swift"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_declaration": "function",
    "class_declaration": "class",
    "protocol_declaration": "interface",
    "init_declaration": "constructor",
}
