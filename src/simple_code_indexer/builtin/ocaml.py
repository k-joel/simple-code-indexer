"""Builtin OCaml plugin."""

NAME = "ocaml"
GRAMMAR = "ocaml"
EXTENSIONS = [".ml", ".mli"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "value_definition": "function",
    "type_definition": "type",
    "module_definition": "module",
    "class_definition": "class",
}
