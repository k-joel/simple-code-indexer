"""Builtin Elixir plugin (best-effort; `call` nodes are generic)."""

NAME = "elixir"
GRAMMAR = "elixir"
EXTENSIONS = [".ex", ".exs"]
FILENAMES: list[str] = []
SYMBOL_NODES: dict[str, str] = {}
