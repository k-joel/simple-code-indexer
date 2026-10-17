"""Builtin Erlang plugin (best-effort via function_clause)."""

NAME = "erlang"
GRAMMAR = "erlang"
EXTENSIONS = [".erl", ".hrl"]
FILENAMES: list[str] = []
SYMBOL_NODES = {
    "function_clause": "function",
}
