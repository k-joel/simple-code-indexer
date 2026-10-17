"""Builtin SQL plugin (best-effort; dialect-dependent nodes)."""

NAME = "sql"
GRAMMAR = "sql"
EXTENSIONS = [".sql"]
FILENAMES: list[str] = []
SYMBOL_NODES: dict[str, str] = {}
