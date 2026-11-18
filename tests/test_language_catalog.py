"""Offline guards on the generated language catalog.

These assert invariants the generator is supposed to guarantee, so a bad
regeneration (or a hand edit to the generated file) fails the suite instead of
silently corrupting the index.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tree_sitter_language_pack import has_language

from simple_code_indexer.languages import catalog
from simple_code_indexer.registry import load_registry

DENIED = (".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".toml", ".csv", ".xml")


def test_catalog_version_is_set() -> None:
    assert isinstance(catalog.VERSION, str) and catalog.VERSION


def test_entries_have_name_and_grammar() -> None:
    for spec in catalog.ENTRIES:
        assert spec.name
        assert spec.grammar
        assert spec.name == spec.grammar


def test_every_grammar_exists_in_the_pack() -> None:
    missing = [
        spec.grammar for spec in catalog.ENTRIES if not has_language(spec.grammar)
    ]
    assert missing == []


def test_extension_ownership_is_unique() -> None:
    owners: dict[str, str] = {}
    collisions: list[str] = []
    for spec in catalog.ENTRIES:
        for ext in spec.extensions:
            if ext in owners and owners[ext] != spec.name:
                collisions.append(f"{ext}: {owners[ext]} vs {spec.name}")
            owners[ext] = spec.name
    assert collisions == []


def test_filename_ownership_is_unique() -> None:
    owners: dict[str, str] = {}
    collisions: list[str] = []
    for spec in catalog.ENTRIES:
        for filename in spec.filenames:
            if filename in owners and owners[filename] != spec.name:
                collisions.append(f"{filename}: {owners[filename]} vs {spec.name}")
            owners[filename] = spec.name
    assert collisions == []


def test_data_formats_exist_in_the_catalog() -> None:
    names = {spec.name for spec in catalog.ENTRIES}
    assert catalog.DATA_FORMATS <= names


def test_no_data_format_extension_reaches_the_allowlist() -> None:
    registry = load_registry()
    allowlist = registry.extension_allowlist()
    leaked = sorted(ext for ext in DENIED if ext in allowlist)
    assert leaked == []


def test_data_format_detection_is_none() -> None:
    registry = load_registry()
    for name in ("a.md", "a.txt", "a.json", "a.yaml", "a.toml", "a.csv", "a.xml"):
        assert registry.detect(Path(name)) is None


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("CMakeLists.txt", "cmake"),
        ("Dockerfile", "dockerfile"),
        ("Makefile", "make"),
        ("GNUmakefile", "make"),
        (".vimrc", "vim"),
    ],
)
def test_filename_entries_survive_the_deny_set(filename: str, expected: str) -> None:
    registry = load_registry()
    spec = registry.detect(Path(filename))
    assert spec is not None and spec.name == expected


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("x.h", "cpp"),
        ("x.m", "objc"),
        ("x.tsx", "tsx"),
        ("x.cs", "csharp"),
        ("x.zsh", "zsh"),
        ("x.fish", "fish"),
        ("x.py", "python"),
    ],
)
def test_extension_overrides(filename: str, expected: str) -> None:
    registry = load_registry()
    spec = registry.detect(Path(filename))
    assert spec is not None and spec.name == expected


def test_extensionless_languages_are_still_catalogued() -> None:
    registry = load_registry()
    assert registry.spec("git_config") is None
    assert registry.spec("gitignore") is None
    assert registry.spec("regex") is None


def test_catalog_reconcile_drops_denied_and_stale_rows(tmp_path: Path) -> None:
    from simple_code_indexer import db, runtime
    from simple_code_indexer.config import IGNORE_DIRS, Settings
    from simple_code_indexer.models import FileRecord

    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "gone.md").write_text("# doc\n", encoding="utf-8")
    registry = load_registry()
    settings = Settings(
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
        allowed_exts=registry.extension_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        allowed_filenames=registry.filename_allowlist(),
    )
    with db.connect(settings.index_db_path) as conn, conn:
        db.ensure_schema(conn)
        for path, language in (
            ("keep.py", "python"),
            ("gone.md", "markdown"),
            ("old.cs", "c_sharp"),
        ):
            db.upsert_file(
                conn,
                FileRecord(
                    path=path, language=language, size=1, sha256=path, mtime=1.0
                ),
            )

    runtime._reconcile_language_catalog(settings)

    with db.connect(settings.index_db_path) as conn:
        assert sorted(r["path"] for r in conn.execute("SELECT path FROM files")) == [
            "keep.py"
        ]
        assert db.get_meta(conn, "language_catalog_version") == catalog.VERSION
