import os

import pytest


def _grammar_cache_dir() -> str | None:
    """The pack's default cache root under the *real* profile, if it exists.

    The fixture below moves `HOME`/`USERPROFILE`, which the pack uses to find its
    cache; without this pin every parse test would try to re-download ~300
    grammars. `TREE_SITTER_LANGUAGE_PACK_CACHE_DIR` is the documented override,
    so the cache stays shared and spawned servers inherit the same answer.
    """
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
    else:
        root = os.environ.get("XDG_CACHE_HOME") or (
            f"{os.environ['HOME']}/.cache" if os.environ.get("HOME") else None
        )
    if not root:
        return None
    candidate = os.path.join(root, "tree-sitter-language-pack")
    return candidate if os.path.isdir(candidate) else None


_GRAMMAR_CACHE = _grammar_cache_dir()


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch, tmp_path) -> None:
    """Never let a developer's ~/.simple-ci/config.yaml change test defaults."""
    monkeypatch.setenv("SIMPLE_CI_CONFIG", "none")
    # Existing tests exercise the single-process writer; sidecar tests override.
    monkeypatch.setenv("SIMPLE_CI_MODE", "embedded")
    # Keep questionary from drawing a TUI if a test instantiates the real Prompter.
    monkeypatch.setenv("SIMPLE_CI_NO_TUI", "1")
    # A harness-launched server inherits these; tests must start from defaults.
    monkeypatch.delenv("SIMPLE_CI_HARNESS", raising=False)
    monkeypatch.delenv("SIMPLE_CI_ROOTS_TIMEOUT_S", raising=False)
    # Move the whole profile, not just the app-data directories: `Path.home()`
    # decides where `~/.simple-ci/config.yaml` and every client's global config
    # live, so a path that forgets to thread `home` must not reach the real one
    # either (ISS-023). The variable pair covers both platforms and is inherited
    # by spawned servers, so parent and child agree on the endpoint.
    home = tmp_path / "pytest-profile"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    if _GRAMMAR_CACHE is not None:
        monkeypatch.setenv("TREE_SITTER_LANGUAGE_PACK_CACHE_DIR", _GRAMMAR_CACHE)
