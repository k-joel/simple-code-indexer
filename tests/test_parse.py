from pathlib import Path

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
