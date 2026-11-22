"""symbol_lookup coverage signal and the pack `process()` symbol fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from simple_code_indexer import db, server
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.languages.spec import LanguageSpec
from simple_code_indexer.models import FileRecord, Symbol
from simple_code_indexer.parse import _parser, extract_from_tree, extract_symbols


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_root=tmp_path,
        index_db_path=tmp_path / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="c",
        embed_base_url="http://localhost:1",
        embed_model="m",
        embed_dim=8,
        embed_timeout_s=1.0,
        sweep_seconds=0.0,
        debounce_ms=10,
        allowed_exts=frozenset({".py", ".zig"}),
        ignore_dirs=IGNORE_DIRS,
        allowed_filenames=frozenset(),
    )


def _seed(settings: Settings, languages: list[str], with_symbols: bool) -> None:
    with db.connect(settings.index_db_path) as conn, conn:
        db.ensure_schema(conn)
        for index, language in enumerate(languages):
            path = f"src/f{index}.{language}"
            file_id = db.upsert_file(
                conn,
                FileRecord(
                    path=path,
                    language=language,
                    size=1,
                    sha256=f"h{index}",
                    mtime=1.0,
                ),
            )
            if with_symbols:
                db.replace_file_symbols(
                    conn,
                    file_id,
                    [Symbol(name=f"only_{language}", kind="function", line=1)],
                )


def test_coverage_is_none_when_no_language_produced_symbols(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, ["zig", "nim"], with_symbols=False)

    payload = server._symbol_lookup(settings, {"symbol": "absent"})

    assert payload["found"] is False
    assert payload["coverage"] == "none"
    assert payload["languages_indexed"] == ["nim", "zig"]
    assert payload["languages_with_symbols"] == []
    assert "search_code" in payload["hint"]


def test_coverage_is_partial_when_some_languages_have_symbols(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, ["python", "zig"], with_symbols=True)
    with db.connect(settings.index_db_path) as conn, conn:
        # Drop zig's symbols so only python is covered.
        conn.execute(
            "DELETE FROM symbols WHERE file_id IN "
            "(SELECT id FROM files WHERE language = 'zig')"
        )

    payload = server._symbol_lookup(settings, {"symbol": "absent"})

    assert payload["coverage"] == "partial"
    assert payload["languages_with_symbols"] == ["python"]
    assert "zig" in payload["hint"]


def test_coverage_is_full_when_every_language_has_symbols(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, ["python"], with_symbols=True)

    payload = server._symbol_lookup(settings, {"symbol": "absent"})

    assert payload["coverage"] == "full"
    assert "hint" not in payload


def test_a_found_symbol_is_unaffected_by_coverage(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, ["python"], with_symbols=True)

    payload = server._symbol_lookup(settings, {"symbol": "only_python"})

    assert payload["line"] == 1
    assert "coverage" not in payload


def test_fallback_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """`SYMBOL_FALLBACK=0` disables the pack's `process()` step."""
    monkeypatch.setenv("SYMBOL_FALLBACK", "0")
    spec = LanguageSpec(
        name="demo",
        grammar="elixir",
        extensions=frozenset(),
        filenames=frozenset(),
        symbol_nodes={},
    )
    source = "defmodule Demo do\nend\n"
    tree = _parser("elixir").parse(source.encode())
    assert extract_from_tree(spec, tree.root_node, source) == []


def test_unmapped_language_falls_back_to_the_pack() -> None:
    """A language with no map relies on the pack's own analysis.

    The spec is built explicitly rather than taken from the catalog: nearly every
    catalog language now has a map, so a real unmapped grammar is not a stable
    fixture.
    """
    spec = LanguageSpec(
        name="demo",
        grammar="d",
        extensions=frozenset(),
        filenames=frozenset(),
        symbol_nodes={},
    )
    source = "int add(int a) { return a; }\n"
    tree = _parser("d").parse(source.encode())
    names = [s.name for s in extract_from_tree(spec, tree.root_node, source)]
    assert "add" in names


def test_curated_map_wins_over_the_fallback() -> None:
    # Python's extractor must still handle signatures the pack has no opinion on.
    symbols = extract_symbols(Path("a.py"), "def add(a, b):\n    return a\n")
    assert [(s.name, s.kind) for s in symbols] == [("add", "function")]
    assert symbols[0].signature == "def add(a, b)"
