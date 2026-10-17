"""Builtin Perl plugin."""

NAME = "perl"
GRAMMAR = "perl"
EXTENSIONS = [".pl", ".pm", ".t"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_definition": "function",
    "method": "method",
    "subroutine_declaration": "function",
}
