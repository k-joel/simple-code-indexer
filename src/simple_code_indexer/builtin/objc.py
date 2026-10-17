"""Builtin Objective-C plugin (.m owned over matlab; .h owned by cpp)."""

NAME = "objc"
GRAMMAR = "objc"
EXTENSIONS = [".m", ".mm", ".h"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "method_declaration": "method",
    "function_definition": "function",
    "class_declaration": "class",
    "protocol_declaration": "interface",
}
