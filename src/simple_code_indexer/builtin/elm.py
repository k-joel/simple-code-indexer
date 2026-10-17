"""Builtin Elm plugin."""

NAME = "elm"
GRAMMAR = "elm"
EXTENSIONS = [".elm"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_declaration_left": "function",
    "type_alias": "type_alias",
    "type_declaration": "type",
    "union_variant": "constructor",
    "value_declaration": "function",
}
