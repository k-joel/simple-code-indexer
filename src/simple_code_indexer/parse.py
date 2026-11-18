"""Symbol extraction and chunking (tree-sitter parsers load lazily).

Language dispatch goes through the registry (registry.py), which is driven by the
generated catalog in languages/catalog.py. Languages with a curated node map or
a specialized extractor use those; the rest fall back to the pack's own
`process()` analysis, and finally to the five generic node types.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from simple_code_indexer.models import Chunk, Symbol
from simple_code_indexer.registry import LanguageSpec, get_registry
from simple_code_indexer.tsutil import signature, text, walk

logger = logging.getLogger(__name__)

_GENERIC_SYMBOL_NODES: dict[str, str] = {
    "function_declaration": "function",
    "function_definition": "function",
    "class_declaration": "class",
    "interface_declaration": "interface",
    "method_definition": "method",
}

# Fallback scan for languages without a loaded grammar.
_REGEX_SYMBOLS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*def\s+([A-Za-z_]\w*)"), "function"),
    (
        re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)"),
        "function",
    ),
    (re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)"), "function"),
    (re.compile(r"^\s*class\s+([A-Za-z_]\w*)"), "class"),
    (re.compile(r"^\s*interface\s+([A-Za-z_]\w*)"), "interface"),
)

_parsers: dict[str, Any] = {}

# Chunk shape is a retrieval-quality knob, not only a token budget. The
# configured model (EmbeddingGemma 2) mean-pools each input, so a focused
# 30-line window scores far above an 80-line block that mixes unrelated
# declarations; 50% overlap keeps a whole function body inside at least one
# window even when it straddles a boundary. CHUNKER_VERSION is part of the
# vector identity (see config.embedding_fingerprint), so changing any of these
# values re-embeds the workspace instead of mixing old and new vectors.
CHUNK_LINES = 30
CHUNK_CHARS = 1200
CHUNK_OVERLAP_LINES = 15
CHUNKER_VERSION = f"windows/{CHUNK_LINES}x{CHUNK_OVERLAP_LINES}/{CHUNK_CHARS}"


def detect_language(path: Path) -> str | None:
    """Map a path to a catalog language id, or None if not indexable."""
    spec = get_registry().detect(path)
    language = spec.name if spec is not None else None
    logger.debug("detected language %s for %s", language or "text", path.name)
    return language


def chunk_source(
    source: str,
    *,
    max_lines: int = CHUNK_LINES,
    max_chars: int = CHUNK_CHARS,
    overlap_lines: int = CHUNK_OVERLAP_LINES,
) -> list[Chunk]:
    """Line-aligned overlapping windows bounded by max_lines and max_chars.

    Adjacent windows share `overlap_lines` lines so a symbol that crosses a
    window boundary still appears whole in one of them. The char budget may end
    a window early; the next window then starts at the first uncovered line, so
    a long-line file never loses content.
    """
    lines = source.splitlines()
    if not lines:
        return []
    total = len(lines)
    step = max(1, max_lines - max(0, overlap_lines))
    chunks: list[Chunk] = []
    start = 0
    while start < total:
        end = min(start + max_lines, total)
        content = "\n".join(lines[start:end])
        while len(content) > max_chars and end > start + 1:
            end -= 1
            content = "\n".join(lines[start:end])
        if content.strip():
            chunks.append(
                Chunk(
                    chunk_index=len(chunks),
                    start_line=start + 1,
                    end_line=end,
                    content=content,
                )
            )
        if end >= total:
            break
        start = max(start + 1, min(start + step, end))
    return chunks


def _parser(lang: str) -> Any:
    """Lazy parser load: keeps server startup fast."""
    if lang not in _parsers:
        logger.debug("loading tree-sitter grammar %s", lang)
        from tree_sitter_language_pack import get_parser

        _parsers[lang] = get_parser(lang)
    return _parsers[lang]


def extract_symbols(path: Path, source: str) -> list[Symbol]:
    """Extract symbols from source; regex fallback when no grammar is loadable."""
    spec = get_registry().detect(path)
    if spec is None:
        logger.debug("no indexed language for %s; using regex symbols", path.name)
        return _regex_symbols(source)
    try:
        parser = _parser(spec.grammar)
    except (ImportError, LookupError, OSError, ValueError) as exc:
        logger.warning(
            "tree-sitter grammar %r unavailable for %s (%s); using regex symbols",
            spec.grammar,
            path.name,
            exc,
        )
        return _regex_symbols(source)
    tree = parser.parse(source.encode("utf-8"))
    return extract_from_tree(spec, tree.root_node, source)


def extract_from_tree(spec: LanguageSpec, root: Any, source: str) -> list[Symbol]:
    """Run the specialized extractor, the node map, or the pack's analysis.

    The pack's `process()` re-parses the source, so it is only consulted for an
    unmapped language whose generic walk produced nothing. Mapped languages never
    pay for it.
    """
    if spec.extract is not None:
        return spec.extract(root, source)
    symbols = _extract_generic(
        root, source, {**_GENERIC_SYMBOL_NODES, **spec.symbol_nodes}
    )
    if symbols or spec.symbol_nodes or not _symbol_fallback_enabled():
        return symbols
    return _process_symbols(spec.grammar, source) or symbols


def _symbol_fallback_enabled() -> bool:
    return os.environ.get("SYMBOL_FALLBACK", "1") != "0"


def _process_symbols(grammar: str, source: str) -> list[Symbol]:
    """Named symbols from the pack's own analyzer (unmapped languages only).

    The pack recognizes declarations that our five generic node types do not, so
    this roughly doubles symbol coverage for the catalog. Any failure is a debug
    log: symbol extraction must never fail an index write.
    """
    try:
        from tree_sitter_language_pack import ProcessConfig, process
    except ImportError:
        return []
    try:
        result = process(
            source,
            ProcessConfig(
                language=grammar,
                structure=True,
                imports=False,
                exports=False,
                docstrings=False,
                diagnostics=False,
            ),
        )
    except Exception:
        logger.debug("pack process() unavailable for %r", grammar, exc_info=True)
        return []
    symbols: list[Symbol] = []
    for item in getattr(result, "structure", ()) or ():
        name = getattr(item, "name", None)
        if not name:
            continue
        span = getattr(item, "span", None)
        start = int(getattr(span, "start_line", 0)) + 1 if span else 1
        end = int(getattr(span, "end_line", 0)) + 1 if span else None
        symbols.append(
            Symbol(
                name=str(name),
                kind=str(getattr(item, "kind", "function") or "function"),
                line=start,
                line_end=end,
                signature=None,
            )
        )
    return symbols


def _extract_generic(
    root: Any, source: str, symbol_nodes: dict[str, str]
) -> list[Symbol]:
    symbols: list[Symbol] = []
    for node in walk(root):
        kind = symbol_nodes.get(node.type)
        if kind is None:
            continue
        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue
        symbols.append(
            Symbol(
                name=text(name_node, source),
                kind=kind,
                line=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=signature(node, source) or None,
            )
        )
    return symbols


def _regex_symbols(source: str) -> list[Symbol]:
    symbols: list[Symbol] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        for pattern, kind in _REGEX_SYMBOLS:
            match = pattern.match(line)
            if match:
                symbols.append(
                    Symbol(
                        name=match.group(1),
                        kind=kind,
                        line=line_no,
                        signature=line.strip(),
                    )
                )
                break
    return symbols
