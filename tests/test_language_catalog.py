"""Offline guards on the generated language catalog.

These assert invariants the generator is supposed to guarantee, so a bad
regeneration (or a hand edit to the generated file) fails the suite instead of
silently corrupting the index.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
from tree_sitter_language_pack import has_language

from simple_code_indexer.languages import catalog
from simple_code_indexer.registry import load_registry

DENIED = (".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".toml", ".csv", ".xml")

#: The generator's own kind vocabulary, imported rather than restated so the two
#: can never drift apart. (`sys.modules` must be populated before `exec_module`,
#: or the module's own `@dataclass` decorators cannot resolve their module.)
_spec = importlib.util.spec_from_file_location(
    "gen_language_catalog_for_tests",
    Path(__file__).resolve().parents[1] / "tools" / "gen_language_catalog.py",
)
assert _spec is not None and _spec.loader is not None
_generator = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name or "gen_language_catalog_for_tests"] = _generator
_spec.loader.exec_module(_generator)
KINDS = _generator.SYMBOL_KINDS


def test_catalog_version_is_set() -> None:
    assert isinstance(catalog.VERSION, str) and catalog.VERSION


def test_entries_have_name_and_grammar() -> None:
    for spec in catalog.ENTRIES:
        assert spec.name
        assert spec.grammar
        assert spec.name == spec.grammar


def test_symbol_maps_use_real_node_types_and_known_kinds() -> None:
    """Every mapped node type is a valid identifier and a known kind.

    Offline on purpose: the generator validates node types against the installed
    grammar, but that needs the grammar downloaded, which the unit suite must not
    do. This catches a hand edit or a truncated regeneration.
    """
    registered = {spec.name for spec in catalog.ENTRIES} - catalog.DATA_FORMATS
    allowed = [spec for spec in catalog.ENTRIES if spec.name in registered]
    pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    for spec in allowed:
        for node, entry in spec.symbol_nodes.items():
            assert pattern.match(node), f"{spec.name}: {node!r} is not a node type"
            kind = entry.partition("@")[0]
            assert kind in KINDS, f"{spec.name}: {node} -> unknown kind {kind!r}"


def test_symbol_gaps_do_not_overlap_mapped_languages() -> None:
    mapped = {spec.name for spec in catalog.ENTRIES if spec.symbol_nodes}
    assert not (set(catalog.SYMBOL_GAPS) & mapped)


def test_symbol_gaps_do_not_overlap_injection_hosts() -> None:
    """A host whose declarations come from an embedded region is not a gap."""
    hosts = {spec.name for spec in catalog.ENTRIES if spec.injections}
    assert hosts
    assert not (set(catalog.SYMBOL_GAPS) & hosts)


def test_injection_hosts_are_symbol_mapped() -> None:
    for spec in catalog.ENTRIES:
        if spec.injections:
            assert spec.symbol_mapped, spec.name


def test_symbol_gaps_are_registered_languages() -> None:
    registered = {spec.name for spec in catalog.ENTRIES} - catalog.DATA_FORMATS
    assert set(catalog.SYMBOL_GAPS) <= registered


def test_prefetch_is_a_bounded_subset() -> None:
    registered = {spec.name for spec in catalog.ENTRIES} - catalog.DATA_FORMATS
    assert catalog.PREFETCH <= registered
    assert 0 < len(catalog.PREFETCH) <= 60


def test_symbol_map_version_is_set() -> None:
    assert isinstance(catalog.SYMBOL_MAP_VERSION, str) and catalog.SYMBOL_MAP_VERSION
    assert catalog.SYMBOL_MAP_VERSION != catalog.VERSION


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
