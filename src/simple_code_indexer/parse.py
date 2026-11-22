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
from dataclasses import replace
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

#: Field names that hold a declaration's name, tried in order. Grammars disagree
#: constantly: Zig names a `FnProto` through `function:` but a `VarDecl` through
#: `variable_type_function:`, while most C-like grammars use `declarator:`.
_NAME_FIELDS: tuple[str, ...] = (
    "name",
    "declarator",
    "function",
    "variable_type_function",
    "identifier",
    "attrpath",
    "selectors",
    "subject",
    "target",
)

#: Node types that *are* an identifier, for the positional fallback used by
#: grammars that expose no name field at all (Nim, Odin, Clojure).
_IDENTIFIER_TYPES: frozenset[str] = frozenset(
    {
        "identifier",
        "IDENTIFIER",
        "ident",
        "symbol",
        "name",
        "simple_identifier",
        "type_identifier",
        "field_identifier",
        "property_identifier",
        "constant",
        "constant_name",
        "constructor_name",
        "module_name",
        "namespace_name",
        "method_name",
        "class_name",
        "function_name",
        "variable_name",
        "bareword",
        "lower_case_identifier",
        "sym_name",
        "tag_name",
        "label",
    }
)

#: Node types that *hold* a name one level down (`message_name`, SQL's
#: `object_reference`, CSS's `selectors`). The search descends through these but
#: never treats their text as the name unless nothing better is found.
_NAME_HOLDER_SUFFIXES: tuple[str, ...] = (
    "_name",
    "_identifier",
    "_reference",
    "_header",
)

#: Fields whose subtree is a body, a type, or a value — never the name. Skipping
#: them keeps the search from returning a parameter or a type name.
_NAME_SEARCH_SKIP_FIELDS: frozenset[str] = frozenset(
    {
        "body",
        "parameters",
        "parameter",
        "arguments",
        "argument",
        "type",
        "result",
        "return_type",
        "value",
        "right",
        "expression",
        "initializer",
        "superclass",
        "interfaces",
        "decorator",
        "attributes",
        "annotation",
        "type_parameters",
        "type_arguments",
    }
)

#: How far the positional name search descends. Deep enough for
#: `module_declaration -> module_header -> simple_identifier`, shallow enough
#: that it cannot wander into a function body.
_NAME_SEARCH_DEPTH = 4

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
    """Symbols from the host grammar, plus any embedded regions worth indexing.

    The pack's `process()` re-parses the source in Rust, so it is consulted only
    for a language with no node map (an empty result there means the map is
    missing, not that the file is empty). A mapped language never pays for it: a
    file whose declarations the map already covers would only be re-parsed to
    find the same symbols.

    A host listed in `catalog`-generated `spec.injections` (Vue, Svelte, Astro,
    Heex, Blade, Templ) also re-parses the regions its injections query marks as
    another language, so a function declared inside a `<script>` block is
    indexed (ISS-014).
    """
    symbols = _extract_local(spec, root, source)
    if not spec.injections:
        return symbols
    injected = _injected_symbols(spec, root, source)
    seen = {(symbol.name, symbol.line) for symbol in symbols}
    symbols.extend(
        symbol for symbol in injected if (symbol.name, symbol.line) not in seen
    )
    return symbols


def _extract_local(spec: LanguageSpec, root: Any, source: str) -> list[Symbol]:
    """One grammar's own symbol extraction, with no injection pass.

    Injected fragments are extracted through here, so a host's injections are
    never followed recursively.
    """
    if spec.extract is not None:
        return spec.extract(root, source)
    symbols = _extract_generic(
        root, source, {**_GENERIC_SYMBOL_NODES, **spec.symbol_nodes}
    )
    if symbols or spec.symbol_nodes or not _symbol_fallback_enabled():
        return symbols
    return _process_symbols(spec.grammar, source) or symbols


#: Injection target languages whose embedded regions are indexed. Curated to the
#: code grammars the enabled hosts actually embed: Vue/Svelte/Astro/Templ/Heex
#: `<script>` blocks inject `javascript`, Svelte and Astro front matter inject
#: `typescript`, Heex `<% … %>` injects `elixir`, and Blade's `@php` region
#: injects `php_only`. Style, comment, regex and markup targets are deliberately
#: absent: they carry no declaration to look up, and indexing them would fill the
#: table with a file's CSS selectors and HTML tags.
_INJECTION_TARGETS: frozenset[str] = frozenset(
    {"elixir", "javascript", "php_only", "typescript"}
)

#: Injection targets the pack does not ship as their own grammar, mapped to the
#: grammar that parses them.
_INJECTION_GRAMMARS: dict[str, str] = {"php_only": "php"}

#: How specific a target is when one region matches several injections patterns
#: (Svelte captures a `<script>` body as both `@javascript` and `@typescript`).
#: A typed block is a TypeScript file: parsing it as JavaScript happens to work
#: for most declarations but loses generics, `enum`, and `interface`.
_INJECTION_PRECEDENCE: dict[str, int] = {
    "javascript": 1,
    "php_only": 1,
    "typescript": 2,
}

#: Parser preamble for an injection target whose grammar needs a delimiter the
#: captured region does not carry. Blade's `php_only` is bare PHP, but the `php`
#: grammar only parses inside a `<?php` tag. The prefix holds no newline, so
#: every line of the fragment stays on its host line.
_INJECTION_PREFIXES: dict[str, str] = {"php_only": "<?php "}

#: `lang=` values on a script tag that mean the body is TypeScript.
_TYPESCRIPT_LANGS: frozenset[str] = frozenset({"ts", "typescript"})

_injection_queries: dict[str, Any] = {}


def _injections_query(grammar: str) -> Any | None:
    """Compiled injections query for a grammar, or None when it bundles none.

    Compiled once per grammar per process; `Query` is immutable, and each call
    matches with its own cursor.
    """
    if grammar not in _injection_queries:
        query = None
        try:
            from tree_sitter import Query
            from tree_sitter_language_pack import get_injections_query

            query_text = get_injections_query(grammar)
            if query_text:
                query = Query(_parser(grammar).language, query_text)
        except Exception:
            logger.debug("no injections query for %r", grammar, exc_info=True)
        _injection_queries[grammar] = query
    return _injection_queries[grammar]


def _injected_symbols(spec: LanguageSpec, root: Any, source: str) -> list[Symbol]:
    """Symbols from the regions this grammar's injections query marks as code.

    The query states the embedded language either as a `#set! injection.language`
    property (Vue, Astro, Heex, Blade, Templ) or as the name of the capture that
    holds the region (Svelte captures `@javascript` / `@typescript`). Only the
    capture body is re-parsed, so a symbol's line is the capture's start line
    plus its own offset — the injected text begins mid-line on the host line.

    One region can match several patterns: Svelte's query captures every
    `<script>` body as `@javascript` and captures it again as `@typescript` when
    the tag carries `lang="ts"`, and a highlighting-oriented query can overlap
    itself. Regions are therefore deduplicated by span, keeping the most specific
    language of the ones that matched, so a typed block is parsed as TypeScript
    rather than as its JavaScript superset's weaker first match.

    A fragment is parsed with the *target* grammar and its own map/extractor, and
    every failure stays at debug — a broken query or a grammar the pack cannot
    load must never fail an index write.
    """
    query = _injections_query(spec.grammar)
    if query is None:
        return []
    from tree_sitter import QueryCursor

    regions: dict[tuple[int, int], tuple[str, Any]] = {}
    for pattern_index, captures in QueryCursor(query).matches(root):
        try:
            for target, node in _injection_regions(query, pattern_index, captures):
                span = (node.start_byte, node.end_byte)
                target = _upgrade_by_lang_attribute(target, node, source)
                current = regions.get(span)
                if current is None or _INJECTION_PRECEDENCE.get(
                    target, 0
                ) > _INJECTION_PRECEDENCE.get(current[0], 0):
                    regions[span] = (target, node)
        except Exception:
            logger.debug(
                "injection %s pattern %d failed",
                spec.grammar,
                pattern_index,
                exc_info=True,
            )
    registry = get_registry()
    symbols: list[Symbol] = []
    for target, node in regions.values():
        try:
            symbols.extend(_region_symbols(target, node, source, registry))
        except Exception:
            logger.debug(
                "injection target %r failed for %s",
                target,
                spec.grammar,
                exc_info=True,
            )
    return symbols


def _upgrade_by_lang_attribute(target: str, node: Any, source: str) -> str:
    """`javascript` -> `typescript` when the enclosing script tag says `lang="ts"`.

    Vue's injections query hard-codes `javascript` for every `<script>`, and so
    does Templ's for its script block, so a typed block would be parsed as plain
    JavaScript. That is not merely less precise: the JavaScript grammar turns
    `interface`, `enum`, and generic declarations into ERROR nodes, so an
    SFC written in TypeScript would index its functions but silently drop its
    types. Svelte's query encodes the typed case itself; this covers the rest.
    """
    if target != "javascript":
        return target
    for ancestor in _ancestors(node):
        if ancestor.type != "script_element":
            continue
        if _attribute_value(ancestor, source, "lang") in _TYPESCRIPT_LANGS:
            return "typescript"
        return target
    return target


def _ancestors(node: Any) -> list[Any]:
    """The node's ancestors, nearest first."""
    chain: list[Any] = []
    current = node.parent
    while current is not None:
        chain.append(current)
        current = current.parent
    return chain


def _attribute_value(tag: Any, source: str, name: str) -> str:
    """The unquoted value of `name=…` on a start tag, or "" when absent.

    The value nests differently per quoting style: a quoted value is a
    `quoted_attribute_value` wrapping an `attribute_value`, while a bare
    `lang=ts` puts the `attribute_value` directly under the `attribute`. Reading
    the innermost `attribute_value` covers both.
    """
    for child in walk(tag):
        if child.type != "attribute":
            continue
        attribute_name = child.child_by_field_name("name") or next(
            (c for c in child.named_children if c.type == "attribute_name"), None
        )
        if attribute_name is None or text(attribute_name, source).strip() != name:
            continue
        value = next((c for c in walk(child) if c.type == "attribute_value"), None)
        if value is None:
            return ""
        return text(value, source).strip().strip("\"'")
    return ""


def _injection_regions(
    query: Any,
    pattern_index: int,
    captures: dict[str, list[Any]],
) -> list[tuple[str, Any]]:
    """`(target language, region node)` for one injections-query match.

    `captures` is keyed by capture name, and one capture can hold several regions
    (an injections query may match once per script tag), so every node is
    returned rather than only the first.
    """
    settings = query.pattern_settings(pattern_index) or {}
    declared = settings.get("injection.language")
    regions: list[tuple[str, Any]] = []
    if isinstance(declared, str):
        if declared in _INJECTION_TARGETS:
            regions.extend(
                (declared, node) for node in captures.get("injection.content") or []
            )
        return regions
    for name, nodes in captures.items():
        if name not in _INJECTION_TARGETS:
            continue
        regions.extend((name, node) for node in nodes)
    return regions


def _region_symbols(target: str, node: Any, source: str, registry: Any) -> list[Symbol]:
    """Symbols declared inside one injected region, on the host file's lines."""
    grammar = _INJECTION_GRAMMARS.get(target, target)
    target_spec = registry.spec(grammar)
    if target_spec is None or not target_spec.symbol_mapped:
        return []
    fragment = _INJECTION_PREFIXES.get(target, "") + text(node, source)
    if not fragment.strip():
        return []
    tree = _parser(grammar).parse(fragment.encode("utf-8"))
    offset = node.start_point[0]
    return [
        replace(
            symbol,
            line=symbol.line + offset,
            line_end=(
                symbol.line_end + offset if symbol.line_end is not None else None
            ),
        )
        for symbol in _extract_local(target_spec, tree.root_node, fragment)
    ]


def _symbol_fallback_enabled() -> bool:
    return os.environ.get("SYMBOL_FALLBACK", "1") != "0"


def _process_symbols(grammar: str, source: str) -> list[Symbol]:
    """Named symbols from the pack's own analyzer.

    Both of the pack's extractors are consulted: `structure` (declarations with
    names) and `symbols` (`symbols=True`, which is off by default and sees a
    different set — it finds Go `type` specs and Lua globals that `structure`
    misses). Results are merged by `(name, line)` so a declaration that appears
    in both is indexed once. Any failure is a debug log: symbol extraction must
    never fail an index write.
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
                symbols=True,
            ),
        )
    except Exception:
        logger.debug("pack process() unavailable for %r", grammar, exc_info=True)
        return []

    symbols: list[Symbol] = []
    seen: set[tuple[str, int]] = set()

    def add(name: str, kind: str, span: Any) -> None:
        start = int(getattr(span, "start_line", 0)) + 1 if span else 1
        end = int(getattr(span, "end_line", 0)) + 1 if span else None
        key = (name, start)
        if key in seen:
            return
        seen.add(key)
        symbols.append(
            Symbol(name=name, kind=kind, line=start, line_end=end, signature=None)
        )

    for item in getattr(result, "structure", ()) or ():
        name = getattr(item, "name", None)
        if name:
            add(
                str(name),
                _pack_kind(getattr(item, "kind", None)),
                getattr(item, "span", None),
            )
    for item in getattr(result, "symbols", ()) or ():
        name = getattr(item, "name", None)
        if name:
            add(
                str(name),
                _pack_kind(getattr(item, "kind", None)),
                getattr(item, "span", None),
            )
    return symbols


def _pack_kind(kind: Any) -> str:
    """Normalize the pack's `Function`/`function` kind strings."""
    value = str(kind or "").strip()
    if not value:
        return "function"
    return value.replace(" ", "_").lower()


def _symbol_name(node: Any, source: str) -> str | None:
    """Resolve a declaration node's name across grammar conventions.

    Grammars disagree so thoroughly that no single rule works: most name a node
    through a `name:` field, C/C++/ObjC use `declarator:`, Zig uses `function:`
    or `variable_type_function:` depending on the node, and several (`CSS`
    `rule_set`, `proto` `message`, `verilog` `module_declaration`) expose no
    field at all, holding the name one or two levels down.

    Resolution order: known name field -> a name-holder child -> the first
    identifier in a bounded breadth-first walk that skips body/type/value
    fields. Returning None is a valid outcome: a declaration with no name (an
    anonymous initialiser, a `dynamic` block) must not become a symbol.
    """
    for field in _NAME_FIELDS:
        child = node.child_by_field_name(field)
        if child is None:
            continue
        # A `declarator`/`function` field may be a wrapper whose text is the
        # whole signature (`addTwo(int a)`), so prefer an identifier inside it.
        for candidate in (child, *child.named_children):
            if candidate.type in _IDENTIFIER_TYPES:
                value = text(candidate, source).strip()
                if value:
                    return value
        value = text(child, source).strip()
        # A single-line non-identifier field (Nix `attrpath: a.b`) is still a
        # name; a multi-line one is a body masquerading as a field.
        if value and "\n" not in value:
            return value

    found = _descend_for_name(node, source, depth=_NAME_SEARCH_DEPTH)
    return found


def _descend_for_name(node: Any, source: str, depth: int) -> str | None:
    """Breadth-first search for an identifier, avoiding bodies and types."""
    if depth <= 0:
        return None
    # An identifier reached through a body/type/value field is a parameter or a
    # type name, never the declaration's name (Haskell's type-arrow `function`
    # node would otherwise resolve to `Int`).
    for index in range(node.child_count):
        child = node.child(index)
        if child is None or not child.is_named:
            continue
        if child.type in _IDENTIFIER_TYPES and (
            node.field_name_for_child(index) not in _NAME_SEARCH_SKIP_FIELDS
        ):
            value = text(child, source).strip()
            if value:
                return value
    for child in node.named_children:
        if child.type.endswith(_NAME_HOLDER_SUFFIXES):
            found = _descend_for_name(child, source, depth - 1)
            if found:
                return found
    for index in range(node.child_count):
        child = node.child(index)
        if child is None or not child.is_named:
            continue
        if node.field_name_for_child(index) in _NAME_SEARCH_SKIP_FIELDS:
            continue
        found = _descend_for_name(child, source, depth - 1)
        if found:
            return found
    return None


def _extract_generic(
    root: Any, source: str, symbol_nodes: dict[str, str]
) -> list[Symbol]:
    """Map node types to symbols; `<kind>@<field>` require that field to exist.

    The field guard exists because some grammars reuse one node type for both a
    declaration and a look-alike: Haskell's `function` is a definition when it
    has a `name:` field and a type arrow (`Int -> Int`) when it has `result:`.
    Without the guard the arrow becomes a symbol named after its result type.
    """
    symbols: list[Symbol] = []
    for node in walk(root):
        entry = symbol_nodes.get(node.type)
        if entry is None:
            continue
        kind, _, required_field = entry.partition("@")
        if required_field and node.child_by_field_name(required_field) is None:
            continue
        name = _symbol_name(node, source)
        if not name:
            continue
        symbols.append(
            Symbol(
                name=name,
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
