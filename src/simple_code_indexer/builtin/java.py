"""Builtin Java plugin."""

NAME = "java"
GRAMMAR = "java"
EXTENSIONS = [".java"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "class",
    "method_declaration": "method",
    "constructor_declaration": "constructor",
}
