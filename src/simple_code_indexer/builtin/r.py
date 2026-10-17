"""Builtin R plugin."""

NAME = "r"
GRAMMAR = "r"
EXTENSIONS = [".r"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_definition": "function",
}
