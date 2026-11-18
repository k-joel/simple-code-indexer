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

#: Symbol node maps carried over from the retired `builtin/` modules. Languages
#: absent here get an empty map and rely on the pack's `process()` fallback.
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
        "type_alias": "type_alias",
        "type_declaration": "type",
        "union_variant": "constructor",
        "value_declaration": "function",
    },
    "erlang": {"function_clause": "function"},
    "fortran": {
        "function": "function",
        "subroutine": "function",
        "type": "type",
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
        "function": "function",
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
        "function_definition": "function",
        "class_declaration": "class",
        "protocol_declaration": "interface",
    },
    "ocaml": {
        "value_definition": "function",
        "type_definition": "type",
        "module_definition": "module",
        "class_definition": "class",
    },
    "perl": {
        "function_definition": "function",
        "method": "method",
        "subroutine_declaration": "function",
    },
    "php": {
        "function_definition": "function",
        "method_declaration": "method",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "trait_declaration": "trait",
    },
    "r": {"function_definition": "function"},
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
}

#: Languages with a specialized extractor instead of a node map. `c` and `cpp`
#: share the declarator-chain walker, which beats the pack's own extractor.
EXTRACTORS: dict[str, str] = {
    "c": "extract_c_family",
    "cpp": "extract_c_family",
    "make": "extract_make",
    "python": "extract_python",
}


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


def render(entries: list[_Entry]) -> str:
    data_formats = "\n".join(f'    "{name}",' for name in sorted(set(DATA_FORMATS)))
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
        nodes = _format_symbol_nodes(SYMBOL_NODES.get(entry.name, {}))
        extract = EXTRACTORS.get(entry.name)
        extract_arg = f", extract={extract}" if extract else ""
        blocks.append(
            f"    LanguageSpec(\n"
            f'        name="{entry.name}",\n'
            f'        grammar="{entry.name}",\n'
            f"        extensions={extensions},\n"
            f"        filenames={filenames},\n"
            f"        symbol_nodes={nodes}{extract_arg},\n"
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
"""

from __future__ import annotations

from simple_code_indexer.languages.extractors import (
    extract_c_family,
    extract_make,
    extract_python,
)
from simple_code_indexer.languages.spec import LanguageSpec

#: Bump when the table changes in a way that requires an index reconcile.
VERSION = "{CATALOG_VERSION}"

#: Grammars that must never be indexed: serialization, documentation, and
#: VCS/tool configuration. See docs/DECISIONS.md for the rationale.
DATA_FORMATS: frozenset[str] = frozenset({{
{data_formats}
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, help="saved copy of the docs page")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the committed catalog is stale",
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
    rendered = render(build_entries(rows))
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
    print(f"wrote {args.out.relative_to(REPO_ROOT)} ({len(rows)} languages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
