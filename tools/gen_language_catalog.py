"""Regenerate `src/simple_code_indexer/languages/catalog.py`.

The upstream language table is the source of truth for which grammars exist and
which extensions each one claims. This script parses that table, resolves every
display name to a real `tree_sitter_language_pack` grammar name, merges the
hand-maintained data below, and writes a deterministic catalog module.

Usage (from the repo root):

    uv run python tools/gen_language_catalog.py            # fetch + rewrite
    uv run python tools/gen_language_catalog.py --check    # fail on drift
    uv run python tools/gen_language_catalog.py --table saved.html --write

`--table` accepts a locally saved copy of the docs page for offline runs.
Requires the docs page (network) unless `--table` is given.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "src" / "simple_code_indexer" / "languages" / "catalog.py"
TABLE_URL = "https://docs.tree-sitter-language-pack.xberg.io/languages/"

#: Bumped by hand when the generated output changes shape or content in a way
#: that requires existing indexes to be reconciled.
CATALOG_VERSION = "2026-11-17"

#: Bumped by hand when symbol maps change, so already-indexed files are re-parsed
#: for symbols. Kept separate from :data:`CATALOG_VERSION`: a reconcile drops
#: rows and re-embeds, whereas the symbol backfill only rewrites `symbols`.
SYMBOL_MAP_VERSION = "2026-11-22b"

# ---------------------------------------------------------------------------
# Hand-maintained data
# ---------------------------------------------------------------------------

#: Display name → pack grammar name, for rows whose display name is not already
#: a valid grammar name after normalization. Every entry is verified with
#: `has_language()` before use.
ALIASES: dict[str, str] = {
    "Cap’n Proto": "capnp",
    "Cap'n Proto": "capnp",
    "Protocol Buffers": "proto",
    "Emacs Lisp": "elisp",
    "F#": "fsharp",
    "Fsharp Signature": "fsharp_signature",
    "reStructuredText": "rst",
    "Llvm Mir": "llvm_mir",
    "QML": "qmljs",
    "Csharp": "csharp",
    "JSON5": "json5",
    "LaTeX": "latex",
    "Tsql": "tsql",
    "OCaml Interface": "ocaml_interface",
    "Markdown Inline": "markdown_inline",
    "Norg Meta": "norg_meta",
    "Ziggy Schema": "ziggy_schema",
    "Git Config": "git_config",
    "Git Rebase": "git_rebase",
    "Godot Resource": "godot_resource",
    "Haskell Persistent": "haskell_persistent",
    "Sql Bigquery": "sql_bigquery",
    "Poe Filter": "poe_filter",
    "Wgsl Bevy": "wgsl_bevy",
}

#: Extension → language id overrides. The upstream table gives `.h` to `c` and
#: `.m` to `objc`; our C++/ObjC split plus the `.tsx`/`.zsh`/`.fish` splits are
#: deliberate and must not regress to a combined grammar.
EXT_OVERRIDES: dict[str, str] = {
    ".h": "cpp",
    ".m": "objc",
    ".tsx": "tsx",
    ".zsh": "zsh",
    ".fish": "fish",
}

#: Bare filenames no extension table can express. Matched before any suffix, so
#: `CMakeLists.txt` resolves to `cmake` even though `.txt` belongs to `vimdoc`.
FILENAMES: dict[str, list[str]] = {
    "cmake": ["CMakeLists.txt"],
    "dockerfile": ["Dockerfile"],
    "make": ["Makefile", "makefile", "GNUmakefile"],
    "vim": [".vimrc"],
}

#: Languages whose files must never enter the index: serialization formats,
#: documentation, and VCS/tool config. Detection returns None for all of them.
DATA_FORMATS: list[str] = [
    "asciidoc",
    "beancount",
    "bibtex",
    "csv",
    "cue",
    "diff",
    "djot",
    "dot",
    "dotenv",
    "dtd",
    "editorconfig",
    "gitattributes",
    "git_config",
    "git_rebase",
    "gitcommit",
    "gitignore",
    "hjson",
    "hocon",
    "http",
    "ini",
    "json",
    "json5",
    "kdl",
    "latex",
    "ledger",
    "markdown",
    "markdown_inline",
    "mermaid",
    "norg",
    "norg_meta",
    "org",
    "pem",
    "pgn",
    "plantuml",
    "properties",
    "psv",
    "regex",
    "requirements",
    "ron",
    "rst",
    "rtf",
    "ssh_config",
    "textproto",
    "todotxt",
    "toml",
    "tsv",
    "vimdoc",
    "xml",
    "yaml",
]

#: Languages whose declarations are found by the pack's own **tags query**
#: (`get_tags_query`). That query is authored by the grammar maintainers and
#: names the real declaration node types with `@definition.*` / `@name`
#: captures, so the map is derived rather than guessed. Curated entries below
#: always win, so a derived kind can never downgrade a hand-verified one.
DERIVE_FROM_TAGS = True

#: Last-resort tier: for grammars with no tags query, map node kinds whose name
#: ends in a declaration word (`*_declaration`, `*_definition`, `*_def`, …).
#: Only runs when tiers 1 and 2 produce nothing. Validated by
#: `tools/gen_language_catalog.py --report`, which prints every resulting map
#: for review, and by `tests/test_language_catalog.py`.
DERIVE_FROM_SHAPE = True

#: Curated symbol maps, hand-verified against the installed grammar: every node
#: type below was confirmed to exist in the named grammar and to resolve a real
#: name in sample source (`tools/gen_language_catalog.py --report` re-checks
#: both). Languages covered by `DERIVE_FROM_TAGS` do not need an entry here;
#: only grammars whose tags query is missing, narrow, or wrong do.
SYMBOL_NODES: dict[str, dict[str, str]] = {
    "bash": {"function_definition": "function"},
    "csharp": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
    },
    "dart": {
        "class_definition": "class",
        "function_signature": "function",
        "method_signature": "method",
    },
    "elm": {
        "function_declaration_left": "function",
        "type_alias_declaration": "type_alias",
        "type_declaration": "type",
        "union_variant": "constructor",
        "value_declaration": "function",
    },
    "erlang": {"function_clause": "function"},
    "fortran": {
        "function": "function",
        "subroutine": "function",
        "derived_type_definition": "type",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_spec": "type",
    },
    "graphql": {
        "object_type_definition": "type",
        "interface_type_definition": "interface",
        "enum_type_definition": "enum",
        "input_object_type_definition": "type",
        "union_type_definition": "union",
        "field_definition": "field",
    },
    "haskell": {
        # `function` is both a definition (`name:`) and a type arrow
        # (`result:`), so the guard keeps the arrow out of the index.
        "function": "function@name",
        "signature": "signature",
        "data_type": "type",
        "newtype": "type",
        "class": "class",
        "instance": "instance",
    },
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "record_declaration": "class",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
    },
    "javascript": {
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
    },
    "julia": {
        "function_definition": "function",
        "struct_definition": "struct",
        "macro_definition": "macro",
        "module_definition": "module",
    },
    "kotlin": {
        "function_declaration": "function",
        "class_declaration": "class",
        "object_declaration": "object",
        "companion_object": "object",
    },
    "lua": {"function_declaration": "function"},
    "objc": {
        "method_declaration": "method",
        "method_definition": "method",
        "function_definition": "function",
        "class_interface": "class",
        "class_implementation": "class",
        "protocol_declaration": "interface",
        "struct_specifier": "struct",
        "enum_specifier": "enum",
    },
    "ocaml": {
        "value_definition": "function",
        "type_definition": "type",
        "module_definition": "module",
        "class_definition": "class",
    },
    "perl": {
        "subroutine_declaration_statement": "function",
        "method_declaration_statement": "method",
        "class_statement": "class",
    },
    "php": {
        "function_definition": "function",
        "method_declaration": "method",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "trait_declaration": "trait",
    },
    "ruby": {
        "method": "function",
        "singleton_method": "function",
        "class": "class",
        "module": "module",
    },
    "rust": {
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
        "impl_item": "impl",
        "mod_item": "module",
        "type_item": "type_alias",
        "macro_definition": "macro",
        "const_item": "constant",
        "static_item": "constant",
    },
    "scala": {
        "function_definition": "function",
        "class_definition": "class",
        "object_definition": "object",
        "trait_definition": "trait",
    },
    "swift": {
        "function_declaration": "function",
        "class_declaration": "class",
        "protocol_declaration": "interface",
        "init_declaration": "constructor",
    },
    "typescript": {
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "class_declaration": "class",
        "abstract_class_declaration": "class",
        "interface_declaration": "interface",
        "type_alias_declaration": "type_alias",
        "enum_declaration": "enum",
        "method_definition": "method",
    },
    "vim": {"function_definition": "function"},
    # --- Grammars with no tags query, or one whose captures are unusable. ---
    # Node types verified with `--report`; `_symbol_name` in parse.py resolves
    # the name from a field or the first identifier child.
    "zig": {
        "FnProto": "function",
        # `VarDecl` covers `const Point = struct {…}` as well as plain constants,
        # so it is the declaration that carries the name. `ContainerDecl` is the
        # anonymous type *expression* inside it — mapping both would index the
        # struct's first field as the type's name.
        "VarDecl": "constant",
        "TestDecl": "test",
    },
    "nim": {
        "routine": "function",
        # `typeDef` is the named declaration; `objectDecl`/`enumDecl` are the
        # anonymous bodies inside it.
        "typeDef": "type",
        "constant": "constant",
    },
    "odin": {
        "procedure_declaration": "function",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
        "union_declaration": "union",
        "variable_declaration": "variable",
        "const_declaration": "constant",
        "package_declaration": "module",
    },
    "v": {
        "function_declaration": "function",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
        "interface_declaration": "interface",
        "type_declaration": "type",
        "const_declaration": "constant",
    },
    "css": {"rule_set": "rule", "at_rule": "rule", "keyframes_statement": "rule"},
    "scss": {"rule_set": "rule", "at_rule": "rule", "mixin_statement": "mixin"},
    "powershell": {
        "function_statement": "function",
        "class_statement": "class",
        "enum_statement": "enum",
        "class_method_definition": "method",
        "class_property_definition": "property",
    },
    "sql": {
        "create_table": "table",
        "create_function": "function",
        "create_procedure": "function",
        "create_type": "type",
        "create_index": "index",
        "create_view": "view",
    },
    "solidity": {
        "function_definition": "function",
        "contract_declaration": "class",
        "interface_declaration": "interface",
        "library_declaration": "module",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
        "modifier_definition": "modifier",
        "event_definition": "event",
    },
    "gdscript": {
        "function_definition": "function",
        "class_definition": "class",
        "constructor_definition": "constructor",
        "enum_definition": "enum",
        "const_statement": "constant",
        "class_name_statement": "class",
    },
    "matlab": {"function_definition": "function", "class_definition": "class"},
    "d": {
        "function_declaration": "function",
        "class_declaration": "class",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
        "interface_declaration": "interface",
        "template_declaration": "template",
        "module_declaration": "module",
    },
    "crystal": {
        "method_def": "function",
        "class_def": "class",
        "module_def": "module",
        "struct_def": "struct",
        "enum_def": "enum",
    },
    "fsharp": {
        "function_or_value_defn": "function",
        "type_definition": "type",
        "module_defn": "module",
        "union_type_defn": "union",
        "record_type_defn": "record",
    },
    "haxe": {
        "function_declaration": "function",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "typedef_declaration": "type_alias",
    },
    "vala": {
        "function_definition": "function",
        "class_declaration": "class",
        "struct_declaration": "struct",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
    },
    "proto": {
        "message": "class",
        "enum": "enum",
        "service": "interface",
        "rpc": "method",
    },
    "verilog": {
        "module_declaration": "module",
        "function_declaration": "function",
        "task_declaration": "function",
    },
    "systemverilog": {
        "module_declaration": "module",
        "function_declaration": "function",
        "class_declaration": "class",
        "package_declaration": "module",
    },
    "vhdl": {
        "entity_declaration": "module",
        "architecture_body": "module",
        "function_declaration": "function",
        "procedure_declaration": "function",
    },
    "tcl": {"procedure": "function"},
    "awk": {"func_def": "function"},
    "fish": {"function_definition": "function"},
    "pascal": {"declProc": "function", "declType": "type", "declClass": "class"},
    "ada": {
        "function_specification": "function",
        "procedure_specification": "function",
        "package_declaration": "module",
    },
    "bicep": {
        "resource_declaration": "resource",
        "module_declaration": "module",
    },
    "puppet": {"class_definition": "class", "node_definition": "module"},
    "dhall": {"let_binding": "binding"},
    "reason": {
        "let_binding": "function",
        "type_declaration": "type",
        "module_declaration": "module",
    },
    "rescript": {
        "let_binding": "function",
        "type_declaration": "type",
        "module_declaration": "module",
    },
    "commonlisp": {"defun": "function"},
    "nix": {"binding": "binding"},
    "html": {"element": "element"},
    # `templ`'s grammar declares Go functions and its own component/script/css
    # blocks; the tags query only knows the Go side, so the rest is curated.
    # `_symbol_name` resolves each name from its `name:` field.
    "templ": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_spec": "type",
        "component_declaration": "component",
        "script_declaration": "script",
        "css_declaration": "css",
    },
}

#: Kind vocabulary emitted by the derivation and the curated maps. A new kind is
#: allowed, but keeping the set closed prevents `@definition.x-whatever` in a
#: future tags query from leaking an arbitrary string into the index.
SYMBOL_KINDS: frozenset[str] = frozenset(
    {
        "binding",
        "block",
        "class",
        "component",
        "constant",
        "constructor",
        "css",
        "element",
        "enum",
        "event",
        "field",
        "function",
        "impl",
        "index",
        "instance",
        "interface",
        "macro",
        "method",
        "mixin",
        "modifier",
        "module",
        "namespace",
        "object",
        "property",
        "record",
        "resource",
        "rule",
        "script",
        "signature",
        "struct",
        "table",
        "template",
        "test",
        "trait",
        "type",
        "type_alias",
        "typedef",
        "union",
        "variable",
        "view",
    }
)

#: Grammars prefetched at writer startup. A derived map exists for nearly every
#: language, but prefetching all ~320 would download the whole pack on first run
#: (ADR-016 forbids that). This is the curated set plus the most common
#: languages; anything absent still extracts symbols on first index, it just
#: loads its grammar then.
PREFETCH: tuple[str, ...] = (
    "bash",
    "c",
    "cpp",
    "csharp",
    "css",
    "dart",
    "elixir",
    "erlang",
    "go",
    "graphql",
    "haskell",
    "hcl",
    "html",
    "java",
    "javascript",
    "julia",
    "kotlin",
    "lua",
    "make",
    "matlab",
    "nim",
    "nix",
    "objc",
    "ocaml",
    "perl",
    "php",
    "powershell",
    "proto",
    "python",
    "r",
    "ruby",
    "rust",
    "scala",
    "scss",
    "solidity",
    "sql",
    "swift",
    "terraform",
    "tsx",
    "typescript",
    "v",
    "zig",
    "gdscript",
    "cmake",
)

#: Languages with a specialized extractor instead of a node map. `c` and `cpp`
#: share the declarator-chain walker, which beats the pack's own extractor;
#: `hcl`/`terraform` need block labels; the Lisp family needs the head-symbol
#: rule, and none of that is expressible as a node-type map. `twig` and `jinja2`
#: declare macros and blocks through template tags rather than nodes.
EXTRACTORS: dict[str, str] = {
    "c": "extract_c_family",
    "clojure": "extract_sexpr_definitions",
    "cmake": "extract_cmake",
    "cpp": "extract_c_family",
    "elixir": "extract_elixir",
    "hcl": "extract_hcl",
    "jinja2": "extract_jinja",
    "make": "extract_make",
    "python": "extract_python",
    "r": "extract_r_assignment",
    "racket": "extract_sexpr_definitions",
    "scheme": "extract_sexpr_definitions",
    "terraform": "extract_hcl",
    "twig": "extract_twig",
}

#: Host languages whose real declarations live in an embedded region that a
#: *different* grammar parses: a Vue/Svelte/Astro `<script>` block, a Heex
#: `<%= … %>` directive, a Blade `@php` block. Their `LanguageSpec.injections`
#: flag makes `parse.extract_from_tree` follow the pack's injections query into
#: those regions and index the symbols the host grammar alone cannot see
#: (ISS-014). Only the hosts whose own grammar declares nothing useful are
#: listed; a language that is fully covered natively does not need the pass, and
#: enabling it would only re-index its own declarations.
INJECTION_HOSTS: frozenset[str] = frozenset(
    {"astro", "blade", "heex", "svelte", "templ", "vue"}
)


# ---------------------------------------------------------------------------
# Tags-query derivation
# ---------------------------------------------------------------------------
#
# A tree-sitter tags query is the grammar authors' own statement of which node
# types are declarations:
#
#     (function_definition name: (identifier) @name) @definition.function
#     (module (expression_statement (assignment left: (identifier) @name)
#              @definition.constant))
#
# The capture that matters can be anywhere in the pattern, nested or postfix,
# so it needs a real S-expression parse rather than a regex. What comes out is
# `node type -> definition kind`; the runtime resolves the name from the node's
# fields, so a derived map never has to encode field names.

_QUERY_TOKEN = re.compile(r'@[\w.\-]+|\(|\)|\[|\]|"[^"]*"|[^\s()\[\]"]+')


class _QueryNode:
    """One list of a tags query: its head node type, captures, children."""

    __slots__ = ("captures", "children", "head")

    def __init__(self) -> None:
        self.head: str | None = None
        self.captures: list[str] = []
        self.children: list[tuple[str | None, _QueryNode]] = []


def _query_tokens(query: str) -> list[str]:
    """Tokens with `;` line comments removed (strings are left intact)."""
    tokens: list[str] = []
    for line in query.splitlines():
        in_string = False
        escaped = False
        cut = len(line)
        for index, char in enumerate(line):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == ";":
                cut = index
                break
        tokens.extend(_QUERY_TOKEN.findall(line[:cut]))
    return tokens


def _parse_query_expr(tokens: list[str], pos: int) -> tuple[_QueryNode, int]:
    """A list or alternation, plus the captures that follow it."""
    node = _QueryNode()
    if tokens[pos] == "[":
        pos += 1
        while pos < len(tokens) and tokens[pos] != "]":
            if tokens[pos] in "([":
                child, pos = _parse_query_expr(tokens, pos)
                node.children.append((None, child))
            else:
                pos += 1
        pos += 1
    else:
        pos += 1  # '('
        pending_field: str | None = None
        while pos < len(tokens) and tokens[pos] != ")":
            token = tokens[pos]
            if token in "([":
                child, pos = _parse_query_expr(tokens, pos)
                node.children.append((pending_field, child))
                pending_field = None
            elif token.startswith("@"):
                node.captures.append(token[1:])
                pos += 1
            elif token.startswith("#"):
                # A predicate (`#is-not?`, `#set-adjacent!`, `#match? …`) is a
                # sibling of the node, never part of its node type.
                pos += 1
            elif token.endswith(":") and len(token) > 1:
                pending_field = token[:-1]
                pos += 1
            else:
                if node.head is None:
                    node.head = token
                pos += 1
        pos += 1  # ')'
    while pos < len(tokens) and tokens[pos].startswith("@"):
        node.captures.append(tokens[pos][1:])
        pos += 1
    return node, pos


def derive_symbol_nodes(query: str) -> dict[str, str]:
    """`node type -> kind` from one grammar's tags query.

    A `@definition.<kind>` capture applies to the node type of the list it sits
    on. Predicates (`#is-not?`, `#match?`) and references are ignored. The first
    definition capture for a node type wins, so the mapping is deterministic.
    """
    tokens = _query_tokens(query)
    out: dict[str, str] = {}
    pos = 0
    while pos < len(tokens):
        if tokens[pos] in "([":
            node, pos = _parse_query_expr(tokens, pos)
            _collect_definitions(node, out)
        else:
            pos += 1
    return out


def _collect_definitions(node: _QueryNode, out: dict[str, str]) -> None:
    if node.head:
        for capture in node.captures:
            if capture.startswith("definition."):
                out.setdefault(node.head, capture.split(".", 1)[1])
                break
    for _, child in node.children:
        _collect_definitions(child, out)


def _grammar_kinds(grammar: str) -> set[str]:
    """Named node types the installed grammar actually has.

    `node_kind_is_supertype()` is deliberately not consulted: this binding
    reports True for punctuation such as `,`, which would empty the table.
    """
    from tree_sitter_language_pack import get_language

    language = get_language(grammar)
    kinds: set[str] = set()
    for kind_id in range(language.node_kind_count):
        if not language.node_kind_is_named(kind_id):
            continue
        kind = language.node_kind_for_id(kind_id)
        if kind:
            kinds.add(kind)
    return kinds


def symbol_map_for(name: str, *, strict: bool) -> dict[str, str]:
    """The effective symbol map for one language.

    Three tiers, in descending authority:

    1. A curated entry in `SYMBOL_NODES` (hand-verified).
    2. The grammar's own tags query, which names the real declaration nodes.
    3. A shape heuristic over the grammar's node-kind names, for the ~225
       grammars that ship neither. Tier 3 is deliberately conservative: it only
       accepts kinds whose name ends in a declaration word and rejects
       parameter/comment/call shapes, because a wrong node type that resolves a
       name produces a symbol that looks real but is not.

    `strict` raises on a node type the grammar does not have, which is what
    `--report` uses to catch a pack rename.
    """
    curated = dict(SYMBOL_NODES.get(name, {}))
    if curated:
        if strict:
            _validate_nodes(name, curated)
        return curated
    kinds = _grammar_kinds(name)
    if DERIVE_FROM_TAGS:
        from tree_sitter_language_pack import get_tags_query

        query = get_tags_query(name)
        if query:
            derived = derive_symbol_nodes(query)
            missing = sorted(node for node in derived if node not in kinds)
            if missing and strict:
                raise SystemExit(
                    f"{name}: tags query names node types the grammar does not "
                    f"have: {missing}"
                )
            usable = {
                node: kind
                for node, kind in derived.items()
                if node in kinds and kind in SYMBOL_KINDS
            }
            if usable:
                return usable
    return _heuristic_map(kinds) if DERIVE_FROM_SHAPE else {}


#: Tier 3 accepts a node kind only when the kind's **head noun** is one of these
#: declaration shapes. Matching the whole head (rather than any keyword anywhere
#: in the name) is what keeps `variable_declaration` out while keeping
#: `function_declaration` in: a variable is a binding inside a body, not a
#: definition site a caller looks up.
_DECLARATION_HEADS: tuple[str, ...] = (
    "function_definition",
    "function_declaration",
    "function_def",
    "function_statement",
    "function_item",
    "function_specification",
    "procedure_declaration",
    "procedure_definition",
    "subroutine",
    "method_definition",
    "method_declaration",
    "method_def",
    "method_specification",
    "constructor_definition",
    "constructor_declaration",
    "class_definition",
    "class_declaration",
    "class_def",
    "class_statement",
    "struct_definition",
    "struct_declaration",
    "struct_def",
    "interface_definition",
    "interface_declaration",
    "interface_def",
    "trait_definition",
    "trait_declaration",
    "enum_definition",
    "enum_declaration",
    "enum_def",
    "union_definition",
    "union_declaration",
    "record_definition",
    "record_declaration",
    "module_definition",
    "module_declaration",
    "module_def",
    "namespace_definition",
    "namespace_declaration",
    "type_definition",
    "type_declaration",
    "type_alias_declaration",
    "type_alias_def",
    "macro_definition",
    "macro_declaration",
    "constant_declaration",
    "const_declaration",
    "const_definition",
    "const_item",
    "function_item",
    "struct_item",
    "enum_item",
    "trait_item",
    "type_item",
    "const_item",
    "mod_item",
    "feature_statement",
    "scenario_statement",
)

#: Suffixes that turn a declaration head into a *part* of one. A
#: `function_declarator` is the child of the `function_definition` above it, so
#: mapping both indexes the same function twice.
_DECLARATION_PART_SUFFIXES: tuple[str, ...] = (
    "_declarator",
    "_specifier",
    "_signature",
)

#: Node kinds whose name contains a declaration word but is not a definition
#: site. Matched as a suffix or exact name (`argument_list`, `class_body`).
_KIND_NOISE: tuple[str, ...] = (
    "_list",
    "_body",
    "_block",
    "_clause",
    "_expression",
    "_pattern",
    "_options",
    "_initializer",
    "_member",
    "_field",
    "_level",
    "_usage",
    "_binding",
    "_reference",
    "_call",
    "_construct",
)

#: Node-kind head noun -> symbol kind, longest head first so
#: `function_definition` wins over `function`.
_KIND_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("constructor", "constructor"),
    ("destructor", "method"),
    ("function", "function"),
    ("procedure", "function"),
    ("subroutine", "function"),
    ("method", "method"),
    ("macro", "macro"),
    ("interface", "interface"),
    ("protocol", "interface"),
    ("trait", "trait"),
    ("namespace", "namespace"),
    ("module", "module"),
    ("package", "module"),
    ("class", "class"),
    ("struct", "struct"),
    ("union", "union"),
    ("enum", "enum"),
    ("record", "record"),
    ("type", "type"),
    ("constant", "constant"),
    ("const", "constant"),
    ("feature", "feature"),
    ("scenario", "scenario"),
    # Rust's `mod_item` is a module; `const_item`/`type_item` are matched above
    # by their leading keyword.
    ("mod", "module"),
)


def _kind_head(lowered: str) -> str | None:
    """The declaration head a node kind ends with, if any."""
    for head in _DECLARATION_HEADS:
        if lowered == head or lowered.endswith("_" + head):
            return head
    return None


def _heuristic_map(kinds: set[str]) -> dict[str, str]:
    """Tier 3: node kinds whose head noun is a known declaration shape."""
    out: dict[str, str] = {}
    for kind in kinds:
        lowered = kind.lower()
        head = _kind_head(lowered)
        if head is None:
            continue
        if lowered.endswith(_DECLARATION_PART_SUFFIXES):
            continue
        if any(lowered.endswith(noise) for noise in _KIND_NOISE):
            continue
        for keyword, symbol_kind in _KIND_KEYWORDS:
            if head.startswith(keyword) or ("_" + keyword) in head:
                out[kind] = symbol_kind
                break
    return out


def _validate_nodes(name: str, mapping: dict[str, str]) -> None:
    kinds = _grammar_kinds(name)
    missing = sorted(node for node in mapping if node not in kinds)
    if missing:
        raise SystemExit(f"{name}: curated map names unknown node types: {missing}")
    unknown = sorted(
        {
            entry.partition("@")[0]
            for entry in mapping.values()
            if entry.partition("@")[0] not in SYMBOL_KINDS
        }
    )
    if unknown:
        raise SystemExit(
            f"{name}: curated map uses kinds outside SYMBOL_KINDS: {unknown}"
        )
    from tree_sitter_language_pack import get_language

    language = get_language(name)
    absent_fields = sorted(
        {
            field
            for entry in mapping.values()
            if (field := entry.partition("@")[2])
            and language.field_id_for_name(field) is None
        }
    )
    if absent_fields:
        raise SystemExit(
            f"{name}: curated map guards on fields the grammar lacks: {absent_fields}"
        )


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------

_ROW = re.compile(
    r"^\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<exts>[^|]*?)\s*\|\s*(?P<repo>[^|]*?)\s*\|",
)
_HTML_ROW = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
_HTML_CELL = re.compile(r"<td>(.*?)</td>", re.DOTALL)
_HTML_CODE = re.compile(r"<code[^>]*>(.*?)</code>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class _Row:
    display: str
    extensions: tuple[str, ...]


def fetch_table(url: str) -> str:
    import urllib.request

    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def _extensions(cell: str) -> tuple[str, ...]:
    """Dotted extensions from a cell holding `<code>` tokens or backticks."""
    tokens = _HTML_CODE.findall(cell) or re.findall(r"`([^`]+)`", cell)
    return tuple(token.strip() for token in tokens if token.strip().startswith("."))


def parse_table(page: str) -> list[_Row]:
    """Extract `Language | Extensions | Repository | ABI` rows (HTML or markdown)."""
    rows: list[_Row] = []
    if "<table" in page:
        for block in _HTML_ROW.findall(page):
            cells = _HTML_CELL.findall(block)
            if len(cells) < 2:
                continue  # header row uses <th>
            display = _TAG.sub("", cells[0]).strip()
            if not display or display == "Language":
                continue
            rows.append(_Row(display=display, extensions=_extensions(cells[1])))
        return rows

    for line in page.splitlines():
        match = _ROW.match(line)
        if match is None:
            continue
        display = match.group("name").strip()
        if display in ("Language", "---") or not display:
            continue
        rows.append(_Row(display=display, extensions=_extensions(match.group("exts"))))
    return rows


def normalize(display: str) -> str:
    """Display name → grammar-name candidate (lowercase, non-alnum → `_`)."""
    slug = re.sub(r"[^0-9a-z]+", "_", display.lower()).strip("_")
    return slug


def resolve_name(display: str) -> str:
    """Display name → a grammar name the pack actually has."""
    from tree_sitter_language_pack import has_language

    if display in ALIASES:
        candidate = ALIASES[display]
        if not has_language(candidate):
            raise SystemExit(
                f"alias for {display!r} is not a pack language: {candidate}"
            )
        return candidate
    slug = normalize(display)
    if has_language(slug):
        return slug
    if slug in ALIASES and has_language(ALIASES[slug]):
        return ALIASES[slug]
    raise SystemExit(
        f"cannot resolve display name {display!r} (tried {slug!r}); add it to ALIASES"
    )


# ---------------------------------------------------------------------------
# Catalog construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Entry:
    name: str
    extensions: tuple[str, ...]
    filenames: tuple[str, ...]


def build_entries(rows: list[_Row]) -> list[_Entry]:
    resolved: dict[str, set[str]] = {}
    for row in rows:
        name = resolve_name(row.display)
        resolved.setdefault(name, set()).update(row.extensions)

    # Apply the deliberate ownership overrides: an extension belongs to exactly
    # one language, and the override wins over whatever the table claimed.
    for ext, owner in EXT_OVERRIDES.items():
        if owner not in resolved:
            raise SystemExit(f"EXT_OVERRIDES targets unknown language {owner!r}")
        for name, owned in resolved.items():
            if name != owner:
                owned.discard(ext)
        resolved[owner].add(ext)

    entries: list[_Entry] = []
    for name in sorted(resolved):
        entries.append(
            _Entry(
                name=name,
                extensions=tuple(sorted(resolved[name])),
                filenames=tuple(FILENAMES.get(name, ())),
            )
        )
    return entries


def _format_symbol_nodes(nodes: dict[str, str]) -> str:
    if not nodes:
        return "{}"
    lines = ",\n".join(f'            "{k}": "{v}"' for k, v in sorted(nodes.items()))
    return "{\n" + lines + ",\n        }"


def render(
    entries: list[_Entry], maps: dict[str, dict[str, str]], gaps: list[str]
) -> str:
    data_formats = "\n".join(f'    "{name}",' for name in sorted(set(DATA_FORMATS)))
    gaps_block = "\n".join(f'    "{name}",' for name in gaps)
    prefetch = "\n".join(f'    "{name}",' for name in PREFETCH)
    blocks: list[str] = []
    for entry in entries:
        extensions = (
            "frozenset({" + ", ".join(f'"{e}"' for e in entry.extensions) + "})"
            if entry.extensions
            else "frozenset()"
        )
        filenames = (
            "frozenset({" + ", ".join(f'"{f}"' for f in entry.filenames) + "})"
            if entry.filenames
            else "frozenset()"
        )
        nodes = _format_symbol_nodes(maps.get(entry.name, {}))
        extract = EXTRACTORS.get(entry.name)
        extract_arg = f", extract={extract}" if extract else ""
        injections_arg = ", injections=True" if entry.name in INJECTION_HOSTS else ""
        blocks.append(
            f"    LanguageSpec(\n"
            f'        name="{entry.name}",\n'
            f'        grammar="{entry.name}",\n'
            f"        extensions={extensions},\n"
            f"        filenames={filenames},\n"
            f"        symbol_nodes={nodes}{extract_arg}{injections_arg},\n"
            f"    ),"
        )
    body = "\n".join(blocks)
    return f'''"""Language catalog: the single declarative table of supported languages.

GENERATED by ``tools/gen_language_catalog.py`` — do not edit by hand. Re-run the
tool after a ``tree-sitter-language-pack`` upgrade and review the diff.

Languages listed in :data:`DATA_FORMATS` are catalogued for completeness but are
never registered, so ``detect()`` returns ``None`` for them and their files can
never enter the index. That exclusion is absolute: ``.md``, ``.txt`` and every
other documentation/serialization format stay out.

Symbol maps come from two sources: a hand-verified entry in the generator's
``SYMBOL_NODES`` table, or the pack's own tags query for the grammar, which names
the real declaration node types. Languages in :data:`SYMBOL_GAPS` have neither;
they still get the generic node map and the pack's ``process()`` fallback.
"""

from __future__ import annotations

from simple_code_indexer.languages.extractors import (
    extract_c_family,
    extract_cmake,
    extract_elixir,
    extract_hcl,
    extract_jinja,
    extract_make,
    extract_python,
    extract_r_assignment,
    extract_sexpr_definitions,
    extract_twig,
)
from simple_code_indexer.languages.spec import LanguageSpec

#: Bump when the table changes in a way that requires an index reconcile.
VERSION = "{CATALOG_VERSION}"

#: Bump when the symbol maps change in a way that requires re-parsing indexed
#: files. Unlike :data:`VERSION` this never drops rows, so it cannot force a
#: re-embed: the writer runs a symbols-only backfill (`indexer.backfill_symbols`).
SYMBOL_MAP_VERSION = "{SYMBOL_MAP_VERSION}"

#: Grammars that must never be indexed: serialization, documentation, and
#: VCS/tool configuration. See docs/DECISIONS.md for the rationale.
DATA_FORMATS: frozenset[str] = frozenset({{
{data_formats}
}})

#: Registered languages with no symbol map and no extractor. They fall back to
#: the five generic node types and the pack's ``process()`` analysis, so
#: ``symbol_lookup`` may legitimately find nothing in them. Reported by
#: ``get_status.languages_without_symbol_maps``.
SYMBOL_GAPS: frozenset[str] = frozenset({{
{gaps_block}
}})

#: Grammars loaded eagerly at writer startup. Deliberately a small subset: a map
#: exists for nearly every language, but prefetching all of them would download
#: the whole pack on first run.
PREFETCH: frozenset[str] = frozenset({{
{prefetch}
}})

ENTRIES: tuple[LanguageSpec, ...] = (
{body}
)
'''


def _ruff_format(source: str) -> str:
    """Normalize output through `ruff format -` so `--check` compares like with like.

    A formatted catalog is what reviewers see; without this the tool would report
    drift on every run after a `ruff format`. The interpreter's `Scripts`
    directory is searched explicitly because `ruff` ships as a standalone binary
    on Windows, not as an importable module.
    """
    candidates = [
        Path(sys.executable).parent / ("ruff.exe" if os.name == "nt" else "ruff"),
        Path(shutil.which("ruff") or ""),
    ]
    executable = next((path for path in candidates if path and path.is_file()), None)
    if executable is None:
        raise SystemExit("cannot find `ruff`; run `uv sync` or pass --no-format")
    try:
        completed = subprocess.run(
            [
                str(executable),
                "format",
                "--stdin-filename",
                "src/simple_code_indexer/languages/catalog.py",
                "-",
            ],
            input=source,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            cwd=REPO_ROOT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"`ruff format` failed ({exc})") from exc
    return completed.stdout or source


def build_maps(entries: list[_Entry], *, strict: bool) -> dict[str, dict[str, str]]:
    """The effective symbol map per language, gaps included as empty dicts.

    A language with a dedicated extractor gets no map: `parse.extract_from_tree`
    calls the extractor first and never consults `symbol_nodes`, so emitting one
    would only mislead a reader of the generated catalog. An injection host keeps
    its own map when it has one (`templ` declares Go functions and its own
    component/script/css blocks as well as injecting into script blocks).
    """
    maps: dict[str, dict[str, str]] = {}
    for entry in entries:
        if entry.name in DATA_FORMATS or entry.name in EXTRACTORS:
            continue
        maps[entry.name] = symbol_map_for(entry.name, strict=strict)
    return maps


def symbol_gaps(entries: list[_Entry], maps: dict[str, dict[str, str]]) -> list[str]:
    """Registered languages that cannot resolve a symbol by any mechanism.

    A language with a specialized extractor has no node map and is still fully
    covered (`python`, `c`, `cpp`, `make`, `hcl`, `terraform`, `twig`, `jinja2`),
    so it is not a gap. Neither is an injection host: its declarations are
    indexed from the embedded region (`vue`, `svelte`, `astro`, `heex`, `blade`,
    `templ`). The list feeds `catalog.SYMBOL_GAPS` and `get_status`.
    """
    return sorted(
        entry.name
        for entry in entries
        if entry.name not in DATA_FORMATS
        and not maps.get(entry.name)
        and entry.name not in EXTRACTORS
        and entry.name not in INJECTION_HOSTS
    )


def report(
    entries: list[_Entry], maps: dict[str, dict[str, str]], gaps: list[str]
) -> None:
    """Print per-language derivation results and the remaining gaps."""
    registered = [entry for entry in entries if entry.name not in DATA_FORMATS]
    mapped = [entry for entry in registered if maps.get(entry.name)]
    curated = [entry.name for entry in registered if SYMBOL_NODES.get(entry.name)]
    derived = [entry.name for entry in mapped if entry.name not in SYMBOL_NODES]
    extractor = [name for name in EXTRACTORS if name not in maps]

    print(f"registered languages: {len(registered)}")
    print(
        f"  symbol maps:        {len(mapped)} "
        f"(curated {len(curated)}, derived {len(derived)})"
    )
    print(f"  extractors:         {len(extractor)} ({' '.join(sorted(extractor))})")
    print(f"  injection hosts:    {len(INJECTION_HOSTS)}")
    print(f"  gaps (no map):      {len(gaps)}")
    print(f"  prefetch grammars:  {len(PREFETCH)}")

    missing_prefetch = sorted(set(PREFETCH) - {entry.name for entry in registered})
    if missing_prefetch:
        print(f"!! PREFETCH names unregistered languages: {missing_prefetch}")

    print("\nper-language maps:")
    for entry in registered:
        mapping = maps.get(entry.name) or {}
        if SYMBOL_NODES.get(entry.name):
            source = "curated"
        elif mapping:
            source = "derived"
        elif entry.name in EXTRACTORS:
            source = "extractor"
        else:
            source = "-"
        if entry.name in INJECTION_HOSTS:
            source += "+injections"
        detail = ", ".join(f"{node}={kind}" for node, kind in sorted(mapping.items()))
        print(f"  {entry.name:20s} {source:20s} {detail}")

    print(f"\ngaps ({len(gaps)}): {' '.join(gaps)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, help="saved copy of the docs page")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the committed catalog is stale",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="print every language's symbol map and the remaining gaps",
    )
    parser.add_argument("--out", type=Path, default=CATALOG_PATH)
    parser.add_argument(
        "--no-format",
        action="store_true",
        help="write raw output (debugging the generator itself)",
    )
    args = parser.parse_args(argv)

    page = (
        args.table.read_text(encoding="utf-8") if args.table else fetch_table(TABLE_URL)
    )
    rows = parse_table(page)
    if len(rows) < 300:
        raise SystemExit(
            f"parsed only {len(rows)} language rows; table layout changed?"
        )
    entries = build_entries(rows)
    # Strict on a real generation or check: a node type the grammar does not
    # have means the pack renamed something and the map is silently dead.
    maps = build_maps(entries, strict=True)
    gaps = symbol_gaps(entries, maps)
    if args.report:
        report(entries, maps, gaps)

    rendered = render(entries, maps, gaps)
    if not args.no_format:
        rendered = _ruff_format(rendered)

    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != rendered:
            print(f"catalog is stale: re-run {Path(__file__).name}", file=sys.stderr)
            return 1
        print(f"catalog is current ({len(rows)} languages)")
        return 0

    args.out.write_text(rendered, encoding="utf-8")
    try:
        shown = args.out.resolve().relative_to(REPO_ROOT)
    except ValueError:
        shown = args.out
    print(f"wrote {shown} ({len(rows)} languages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
