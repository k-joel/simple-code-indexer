from pathlib import Path

from simple_code_indexer.config import is_allowed, load_settings
from simple_code_indexer.parse import detect_language, extract_symbols
from simple_code_indexer.registry import load_registry

VALID_PLUGIN = """\
NAME = "mylang"
GRAMMAR = "python"
EXTENSIONS = [".myl"]
FILENAMES = ["SpecialCase"]
SYMBOL_NODES = {"function_definition": "function"}
"""

OVERRIDE_CPP = """\
NAME = "cpp"
GRAMMAR = "python"
EXTENSIONS = [".cpp", ".mycpp"]
FILENAMES: list[str] = []
"""


def _write(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_builtin_languages_load() -> None:
    registry = load_registry()
    assert len(registry) >= 30
    assert registry.spec("python") is not None
    assert registry.spec("cpp") is not None
    c_sharp = registry.spec("c_sharp")
    assert c_sharp is not None
    assert c_sharp.grammar == "csharp"
    # v1 collisions resolved toward cpp/objc.
    h_spec = registry.detect(Path("x.h"))
    m_spec = registry.detect(Path("x.m"))
    assert h_spec is not None and h_spec.name == "cpp"
    assert m_spec is not None and m_spec.name == "objc"
    assert ".md" not in registry.extension_allowlist()


def test_user_plugin_registers(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    _write(plugins, "mylang.py", VALID_PLUGIN)
    registry = load_registry(user_dirs=[plugins])
    spec = registry.detect(Path("code.myl"))
    assert spec is not None
    assert spec.name == "mylang"
    assert spec.grammar == "python"
    assert registry.detect(Path("SpecialCase")) is not None
    assert ".myl" in registry.extension_allowlist()


def test_user_plugin_overrides_builtin(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    _write(plugins, "cpp.py", OVERRIDE_CPP)
    registry = load_registry(user_dirs=[plugins])
    spec = registry.detect(Path("code.mycpp"))
    assert spec is not None
    assert spec.name == "cpp"
    assert spec.grammar == "python"
    # Original cpp extension still maps to cpp (same NAME entry replaced).
    cpp_spec = registry.detect(Path("x.cpp"))
    assert cpp_spec is not None and cpp_spec.name == "cpp"


def test_user_plugin_steals_extension(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    _write(
        plugins,
        "mylang.py",
        'NAME = "mylang"\nGRAMMAR = "python"\nEXTENSIONS = [".py"]\n',
    )
    registry = load_registry(user_dirs=[plugins])
    py_spec = registry.detect(Path("x.py"))
    assert py_spec is not None and py_spec.name == "mylang"
    # builtin python still exists but no longer owns .py
    assert registry.spec("python") is not None


def test_bad_plugin_is_skipped(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    _write(plugins, "broken.py", "def broken(:\n")  # SyntaxError on import
    _write(plugins, "noname.py", 'GRAMMAR = "python"\nEXTENSIONS = [".nn"]\n')
    _write(plugins, "mylang.py", VALID_PLUGIN)
    registry = load_registry(user_dirs=[plugins])
    assert registry.spec("broken") is None
    assert registry.spec("noname") is None
    mylang = registry.detect(Path("code.myl"))
    assert mylang is not None and mylang.name == "mylang"


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
    assert registry.detect(Path("x.md")) is None


def test_settings_allowlist_from_plugins() -> None:
    settings = load_settings()
    assert ".cpp" in settings.allowed_exts
    assert ".rs" in settings.allowed_exts
    assert ".go" in settings.allowed_exts
    assert "Dockerfile" in settings.allowed_filenames
    assert is_allowed(settings, Path("/w/Dockerfile"))
    assert is_allowed(settings, Path("/w/CMakeLists.txt"))
    assert not is_allowed(settings, Path("/w/x.md"))


def test_builtin_python_extract_still_works() -> None:
    source = "def load_widget():\n    return None\n"
    symbols = extract_symbols(Path("widgets.py"), source)
    assert [s.name for s in symbols] == ["load_widget"]


def test_detect_language_returns_plugin_name() -> None:
    assert detect_language(Path("x.cs")) == "c_sharp"
    assert detect_language(Path("x.sh")) == "bash"
