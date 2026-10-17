"""Builtin Scala plugin."""

NAME = "scala"
GRAMMAR = "scala"
EXTENSIONS = [".scala", ".sc"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_definition": "function",
    "class_definition": "class",
    "object_definition": "object",
    "trait_definition": "trait",
}
