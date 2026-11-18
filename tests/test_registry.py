from pathlib import Path

from simple_code_indexer.config import is_allowed, load_settings
from simple_code_indexer.languages import catalog
from simple_code_indexer.parse import detect_language, extract_symbols
from simple_code_indexer.registry import get_registry, load_registry


def test_catalog_languages_load() -> None:
    registry = load_registry()
    assert len(registry) >= 300
    assert registry.spec("python") is not None
    assert registry.spec("cpp") is not None
    # Language ids are pack grammar names; the old c_sharp id is gone.
    assert registry.spec("c_sharp") is None
    assert registry.spec("csharp") is not None
    zig = registry.spec("zig")
    assert zig is not None and zig.grammar == "zig"
    # v1 collisions resolved toward cpp/objc without an ownership table.
    h_spec = registry.detect(Path("x.h"))
    m_spec = registry.detect(Path("x.m"))
    assert h_spec is not None and h_spec.name == "cpp"
    assert m_spec is not None and m_spec.name == "objc"


def test_filename_matching() -> None:
    registry = load_registry()
    dockerfile = registry.detect(Path("Dockerfile"))
    makefile = registry.detect(Path("Makefile"))
    cmake = registry.detect(Path("CMakeLists.txt"))
    vimrc = registry.detect(Path(".vimrc"))
    assert dockerfile is not None and dockerfile.name == "dockerfile"
    assert makefile is not None and makefile.name == "make"
    assert cmake is not None and cmake.name == "cmake"
    assert vimrc is not None and vimrc.name == "vim"


def test_settings_allowlist_from_the_catalog() -> None:
    settings = load_settings()
    assert ".cpp" in settings.allowed_exts
    assert ".rs" in settings.allowed_exts
    assert ".go" in settings.allowed_exts
    assert "Dockerfile" in settings.allowed_filenames
    assert is_allowed(settings, Path("/w/Dockerfile"))
    # A filename match survives even though its suffix is a denied data format.
    assert is_allowed(settings, Path("/w/CMakeLists.txt"))
    assert not is_allowed(settings, Path("/w/x.md"))


def test_python_extractor_still_works() -> None:
    source = "def load_widget():\n    return None\n"
    symbols = extract_symbols(Path("widgets.py"), source)
    assert [s.name for s in symbols] == ["load_widget"]


def test_make_extractor_finds_rule_targets() -> None:
    # `targets` is a named child of `rule`, not a tree-sitter field.
    source = "all:\n\techo hi\n\nbuild: all\n\techo done\n"
    symbols = extract_symbols(Path("Makefile"), source)
    assert [s.name for s in symbols] == ["all", "build"]
    assert {s.kind for s in symbols} == {"rule"}


def test_detect_language_returns_the_catalog_name() -> None:
    assert detect_language(Path("x.cs")) == "csharp"
    assert detect_language(Path("x.sh")) == "bash"
    assert detect_language(Path("x.zig")) == "zig"


def test_data_formats_are_never_registered() -> None:
    registry = load_registry()
    for name in sorted(catalog.DATA_FORMATS):
        assert registry.spec(name) is None, f"{name} must not be registered"


def test_prefetch_targets_stay_small() -> None:
    registry = load_registry()
    mapped = registry.mapped_grammars()
    assert 0 < len(mapped) <= 60
    assert set(mapped) < set(registry.grammars())


def test_symbol_mapped_flags_cover_the_curated_languages() -> None:
    registry = load_registry()
    python = registry.spec("python")
    rust = registry.spec("rust")
    zig = registry.spec("zig")
    assert python is not None and python.symbol_mapped
    assert rust is not None and rust.symbol_mapped
    assert zig is not None and not zig.symbol_mapped
    assert len(get_registry()) == len(registry)
