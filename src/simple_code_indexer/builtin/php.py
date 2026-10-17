"""Builtin PHP plugin."""

NAME = "php"
GRAMMAR = "php"
EXTENSIONS = [".php", ".php3", ".php4", ".php5", ".phtml"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_definition": "function",
    "method_declaration": "method",
    "class_declaration": "class",
    "interface_declaration": "interface",
    "trait_declaration": "trait",
}
