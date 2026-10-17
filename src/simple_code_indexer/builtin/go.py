"""Builtin Go plugin."""

NAME = "go"
GRAMMAR = "go"
EXTENSIONS = [".go"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_declaration": "function",
    "method_declaration": "method",
    "type_spec": "type",
}
