from pathlib import Path

import pytest

from simple_code_indexer.parse import (
    chunk_source,
    detect_language,
    extract_symbols,
)

CPP_FIXTURE = """\
#include <cstdint>

struct Widget {
    int id;
};

uint32_t calculateWidgetChecksum(const Widget& w);

class WidgetStore {
public:
    void put(const Widget& w);
private:
    int count_;
};

uint32_t calculateWidgetChecksum(const Widget& w) {
    uint32_t acc = 0;
    for (int i = 0; i < 8; ++i) {
        acc ^= static_cast<uint32_t>(w.id + i);
    }
    return acc;
}
"""

PY_FIXTURE = """\
class Widget:
    def save(self) -> None:
        pass


def load_widget(path: str) -> Widget:
    return Widget()
"""


def test_detect_language() -> None:
    assert detect_language(Path("a/b.cpp")) == "cpp"
    assert detect_language(Path("a/b.hpp")) == "cpp"
    assert detect_language(Path("x.py")) == "python"
    assert detect_language(Path("x.ts")) == "typescript"
    assert detect_language(Path("x.rs")) == "rust"
    assert detect_language(Path("x.md")) is None  # data formats intentionally skipped


def test_chunk_source_line_windows() -> None:
    source = "\n".join(f"line {i}" for i in range(1, 201))
    chunks = chunk_source(source, max_lines=80, max_chars=10_000, overlap_lines=0)
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert chunks[0].start_line == 1 and chunks[0].end_line == 80
    assert chunks[1].start_line == 81
    assert chunks[2].end_line == 200


def test_chunk_source_defaults_overlap() -> None:
    source = "\n".join(f"line {i}" for i in range(1, 201))
    chunks = chunk_source(source)
    assert chunks[0].start_line == 1 and chunks[0].end_line == 30
    assert chunks[1].start_line == 16 and chunks[1].end_line == 45
    assert chunks[-1].end_line == 200
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    covered: set[int] = set()
    for chunk in chunks:
        covered.update(range(chunk.start_line, chunk.end_line + 1))
    assert covered == set(range(1, 201))


def test_chunk_source_char_budget() -> None:
    source = "\n".join("x" * 100 for _ in range(50))
    chunks = chunk_source(source, max_lines=80, max_chars=500, overlap_lines=0)
    assert chunks
    for chunk in chunks:
        # Last chunk may hold a single unbreakable line.
        assert len(chunk.content) <= 500 or chunk.start_line == chunk.end_line


def test_chunk_source_char_budget_never_skips_lines() -> None:
    source = "\n".join("x" * 100 for _ in range(50))
    chunks = chunk_source(source, max_lines=30, max_chars=500, overlap_lines=15)
    covered: set[int] = set()
    for chunk in chunks:
        covered.update(range(chunk.start_line, chunk.end_line + 1))
        assert len(chunk.content) <= 500 or chunk.start_line == chunk.end_line
    assert covered == set(range(1, 51))


def test_chunk_source_empty() -> None:
    assert chunk_source("") == []
    assert chunk_source("\n\n  \n") == []


def test_extract_cpp_symbols() -> None:
    symbols = extract_symbols(Path("widget_checksum.cpp"), CPP_FIXTURE)
    by_name = {s.name: s for s in symbols}
    fn = by_name["calculateWidgetChecksum"]
    assert fn.kind == "function"
    assert fn.line == 16
    assert fn.signature is not None
    assert "calculateWidgetChecksum" in fn.signature
    assert "uint32_t" in fn.signature
    assert "{" not in fn.signature
    assert by_name["Widget"].kind == "struct"
    assert by_name["WidgetStore"].kind == "class"
    assert "put" in by_name and "count_" not in by_name


def test_extract_python_symbols() -> None:
    symbols = extract_symbols(Path("widgets.py"), PY_FIXTURE)
    by_name = {s.name: s for s in symbols}
    assert by_name["Widget"].kind == "class"
    assert by_name["load_widget"].kind == "function"
    assert by_name["save"].kind == "function"
    assert by_name["load_widget"].line == 6


def test_regex_fallback_for_unknown_language() -> None:
    # .rs is a known plugin language now; truly unknown suffixes still fall back.
    source = "fn main() {\n}\npub struct Foo;\n"
    symbols = extract_symbols(Path("x.unknown-ext"), source)
    assert [s.name for s in symbols] == ["main"]
    assert symbols[0].line == 1


@pytest.mark.parametrize(
    ("filename", "source", "expected"),
    [
        # Zig: `FnProto` inside `Decl`; the name is in the `function:` field.
        (
            "a.zig",
            "pub fn addTwo(a: i32) i32 {\n    return a;\n}\n",
            ("addTwo", "function"),
        ),
        # Nim: `routine` with no fields at all; the name is `symbol -> ident`.
        (
            "a.nim",
            "proc addTwo(a: int): int =\n  return a\n",
            ("addTwo", "function"),
        ),
        # Odin: `procedure_declaration`, name is the first identifier child.
        (
            "a.odin",
            "package main\n\nadd_two :: proc(a: int) -> int {\n\treturn a\n}\n",
            ("add_two", "function"),
        ),
        # V: a plain `name:` field.
        (
            "a.v",
            "module main\n\npub fn add_two(a int) int {\n\treturn a\n}\n",
            ("add_two", "function"),
        ),
        # Gleam: derived from the grammar's tags query.
        (
            "a.gleam",
            "pub fn add_two(a: Int) -> Int {\n  a\n}\n",
            ("add_two", "function"),
        ),
        # Nix: `binding` whose name is the `attrpath`.
        (
            "a.nix",
            "{ pkgs }:\nlet\n  helper = x: x + 1;\nin\n{ inherit helper; }\n",
            ("helper", "binding"),
        ),
        # Terraform: block labels, handled by extract_hcl.
        (
            "a.tf",
            'variable "region" {\n  default = "x"\n}\n',
            ("region", "variable"),
        ),
        # CSS: `rule_set` with no fields; the name comes from `selectors`.
        ("a.css", ".widget {\n  color: red;\n}\n", ("widget", "rule")),
        # SQL: `create_table` naming an `object_reference`.
        (
            "a.sql",
            "CREATE TABLE widgets (id INT);\n",
            ("widgets", "table"),
        ),
        # Proto: `message` holding a `message_name`.
        (
            "a.proto",
            "message Widget {\n  string name = 1;\n}\n",
            ("Widget", "class"),
        ),
        # Elixir: a `call` whose target is the `def` keyword.
        (
            "a.ex",
            "defmodule Demo do\n  def add_two(a) do\n    a\n  end\nend\n",
            ("add_two", "function"),
        ),
        # R: the name is the `lhs` of the assignment holding the function.
        (
            "a.r",
            "add_two <- function(a) {\n  a\n}\n",
            ("add_two", "function"),
        ),
        # Clojure: a `list` whose head symbol selects the definition kind.
        (
            "a.clj",
            "(ns demo)\n(defn add-two [a] (+ a b))\n",
            ("add-two", "function"),
        ),
    ],
)
def test_issue_013_languages_resolve_symbols(
    filename: str, source: str, expected: tuple[str, str]
) -> None:
    """The languages named in ISS-013 must produce a real symbol."""
    symbols = extract_symbols(Path(filename), source)
    pairs = [(s.name, s.kind) for s in symbols]
    assert expected in pairs, f"{filename}: got {pairs}"


def test_signature_stops_at_the_body_for_bodyless_nodes() -> None:
    """A declaration with no `body` field must not return the whole node."""
    symbols = extract_symbols(
        Path("a.zig"), "pub fn addTwo(a: i32) i32 {\n    return a;\n}\n"
    )
    assert len(symbols) == 1
    signature = symbols[0].signature
    assert signature is not None
    assert "return" not in signature


def test_a_nameless_declaration_produces_no_symbol() -> None:
    """A mapping that guesses a wrong node type must not invent a symbol."""
    # `ContainerDecl` is the anonymous `struct { … }` type expression; its first
    # field is not the declaration's name.
    symbols = extract_symbols(Path("a.zig"), "const Point = struct { x: f32 };\n")
    assert [(s.name, s.kind) for s in symbols] == [("Point", "constant")]


@pytest.mark.parametrize(
    ("filename", "source", "expected"),
    [
        # Vue: the `<script>` body is JavaScript/TypeScript, not Vue.
        (
            "Page.vue",
            (
                "<template><div>{{ msg }}</div></template>\n"
                '<script setup lang="ts">\n'
                "function greet(name: string) {\n  return name;\n}\n"
                "class Widget {\n  render() {}\n}\n"
                "</script>\n"
            ),
            {("greet", "function"), ("Widget", "class"), ("render", "method")},
        ),
        # Svelte: typed `lang="ts"` block; the region matches both the
        # `@javascript` and `@typescript` captures and must be indexed once.
        (
            "Page.svelte",
            (
                '<script lang="ts">\n'
                "function greet(name: string) {\n  return name;\n}\n"
                "enum Mode { A, B }\n"
                "</script>\n"
                "<h1>{greet('a')}</h1>\n"
            ),
            {("greet", "function"), ("Mode", "enum")},
        ),
        # Astro: the frontmatter fence holds TypeScript.
        (
            "Page.astro",
            "---\nfunction load(): string {\n  return 'x';\n}\n---\n<h1>hi</h1>\n",
            {("load", "function")},
        ),
        # Heex: Elixir inside a `<%= … %>` directive.
        (
            "page.heex",
            "<div><% def greet(name) do %>x<% end %></div>\n",
            {("greet", "function")},
        ),
        # Blade: bare PHP inside `@php`, parsed through the `php` grammar.
        (
            "page.blade",
            "@php\nfunction greet($n) { return $n; }\n@endphp\n",
            {("greet", "function")},
        ),
        # Templ: the component declaration is the host grammar's own node, and
        # the `script` block's function comes from the injected JavaScript.
        (
            "page.templ",
            "package main\n\ntempl hello(name string) {\n  <div>{ name }</div>\n}\n",
            {("hello", "component")},
        ),
        # Twig: macro/block live in template tags, not in nodes.
        (
            "page.twig",
            "{% macro hello(name) %}{{ name }}{% endmacro %}\n",
            {("hello", "macro")},
        ),
        # Jinja: its grammar collapses every statement tag into one opaque node.
        (
            "page.j2",
            "{% macro hello(name) %}{{ name }}{% endmacro %}\n",
            {("hello", "macro")},
        ),
    ],
)
def test_iss_014_embedded_declarations_are_indexed(
    filename: str, source: str, expected: set[tuple[str, str]]
) -> None:
    """ISS-014: a declaration inside an embedded block must resolve."""
    symbols = extract_symbols(Path(filename), source)
    pairs = {(s.name, s.kind) for s in symbols}
    assert expected <= pairs, f"{filename}: got {pairs}"
    assert len(symbols) == len({(s.name, s.line) for s in symbols}), (
        f"{filename}: duplicate symbol for one line: {symbols}"
    )


def test_injected_symbols_keep_their_host_line_numbers() -> None:
    """An injected declaration's line is its line in the host file."""
    source = (
        "<template><div>x</div></template>\n"
        "<script>\n"
        "const a = 1;\n"
        "function late() {}\n"
        "</script>\n"
    )
    symbols = extract_symbols(Path("Line.vue"), source)
    assert [(s.name, s.line) for s in symbols] == [("late", 4)]


def test_a_typed_script_block_is_parsed_as_typescript() -> None:
    """`lang="ts"` upgrades the injection target.

    Vue's injections query hard-codes `javascript`; the JavaScript grammar turns
    `interface`/`enum` into ERROR nodes, so a typed SFC would lose its types.
    """
    source = (
        '<script setup lang="ts">\n'
        "interface Props { a: string }\n"
        "enum Mode { A }\n"
        "</script>\n"
    )
    symbols = extract_symbols(Path("Typed.vue"), source)
    assert {(s.name, s.kind) for s in symbols} == {
        ("Props", "interface"),
        ("Mode", "enum"),
    }


def test_an_unquoted_lang_attribute_also_upgrades_to_typescript() -> None:
    """`lang=ts` nests its value differently from `lang="ts"`."""
    source = "<script setup lang=ts>\ntype Alias = string;\n</script>\n"
    symbols = extract_symbols(Path("Bare.vue"), source)
    assert [(s.name, s.kind) for s in symbols] == [("Alias", "type_alias")]


def test_a_dotted_twig_macro_keeps_its_full_name() -> None:
    """Twig's `method` child only holds the first segment of `forms.input`."""
    source = "{% macro forms.input(name) %}{% endmacro %}\n"
    symbols = extract_symbols(Path("Forms.twig"), source)
    assert [(s.name, s.kind) for s in symbols] == [("forms.input", "macro")]


def test_injections_are_only_followed_for_flagged_hosts() -> None:
    """A host without the catalog flag keeps its pre-ISS-014 behaviour."""
    source = "<div><script>function s() { return 1; }</script></div>\n"
    from simple_code_indexer.languages.spec import LanguageSpec

    unflagged = LanguageSpec(
        name="demo",
        grammar="html",
        extensions=frozenset(),
        filenames=frozenset(),
        symbol_nodes={"element": "element"},
    )
    from simple_code_indexer.parse import _parser, extract_from_tree

    tree = _parser("html").parse(source.encode())
    names = [s.name for s in extract_from_tree(unflagged, tree.root_node, source)]
    assert "s" not in names
    # The catalog's html entry carries no flag either: HTML is fully described
    # by its own node map, so indexing every `<script>` body is opt-in.
    from simple_code_indexer.registry import get_registry

    html = get_registry().spec("html")
    assert html is not None and not html.injections
