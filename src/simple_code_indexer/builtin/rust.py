"""Builtin Rust plugin."""

NAME = "rust"
GRAMMAR = "rust"
EXTENSIONS = [".rs"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_item": "function",
    "struct_item": "struct",
    "enum_item": "enum",
    "trait_item": "trait",
    "impl_item": "impl",
    "mod_item": "module",
    "type_item": "type_alias",
    "macro_definition": "macro",
    "const_item": "constant",
    "static_item": "constant",
}
