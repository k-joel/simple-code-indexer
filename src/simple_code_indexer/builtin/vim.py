"""Builtin Vim script plugin (.vimrc has empty path.suffix — filename match)."""

NAME = "vim"
GRAMMAR = "vim"
EXTENSIONS = [".vim", ".vimrc"]
FILENAMES = [".vimrc"]
SYMBOL_NODES = {
    "function_definition": "function",
}
