"""Builtin Kotlin plugin."""

NAME = "kotlin"
GRAMMAR = "kotlin"
EXTENSIONS = [".kt", ".kts"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_declaration": "function",
    "class_declaration": "class",
    "object_declaration": "object",
    "companion_object": "object",
}
