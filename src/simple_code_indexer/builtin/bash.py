"""Builtin Bash plugin."""

NAME = "bash"
GRAMMAR = "bash"
EXTENSIONS = [".sh", ".bash", ".zsh", ".fish"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_definition": "function",
}
