"""Builtin Dockerfile plugin (filename match, not suffix)."""

NAME = "dockerfile"
GRAMMAR = "dockerfile"
EXTENSIONS = [".dockerfile"]
FILENAMES = ["Dockerfile"]
SYMBOL_NODES: dict[str, str] = {}
