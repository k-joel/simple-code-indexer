"""Domain records for the code index (frozen, slots)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    language: str
    size: int
    sha256: str
    mtime: float


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    kind: str
    line: int
    line_end: int | None = None
    signature: str | None = None
    path: str | None = None
    language: str | None = None


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_index: int
    start_line: int
    end_line: int
    content: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    path: str
    line: int
    end_line: int
    snippet: str
    score: float
    source: str = "lexical"
