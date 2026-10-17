"""Builtin JavaScript plugin."""

NAME = "javascript"
GRAMMAR = "javascript"
EXTENSIONS = [".js", ".mjs", ".cjs"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "method_definition": "method",
}
