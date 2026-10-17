"""Builtin C++ plugin (specialized declarator-chain extractor)."""

from __future__ import annotations

from typing import Any

from simple_code_indexer.builtin._c_family import extract_c_family
from simple_code_indexer.models import Symbol

NAME = "cpp"
GRAMMAR = "cpp"
EXTENSIONS = [".cpp", ".cc", ".cxx", ".c++", ".hpp", ".h", ".hh", ".h++", ".hxx"]
FILENAMES: list[str] = []


def extract(root: Any, source: str) -> list[Symbol]:
    return extract_c_family(root, source)
