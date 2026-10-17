"""Builtin Julia plugin."""

NAME = "julia"
GRAMMAR = "julia"
EXTENSIONS = [".jl"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_definition": "function",
    "struct_definition": "struct",
    "macro_definition": "macro",
}
