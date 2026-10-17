"""Builtin Ruby plugin."""

NAME = "ruby"
GRAMMAR = "ruby"
EXTENSIONS = [".rb", ".rake"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "method": "function",
    "singleton_method": "function",
    "class": "class",
    "module": "module",
}
