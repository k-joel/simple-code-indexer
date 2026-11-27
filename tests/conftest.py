import os

import pytest


def _existing_grammar_cache_dir() -> str | None:
    """The pack's default cache root under the *real* profile, if it exists.

    Reusing it keeps the developer's downloaded grammars: the fixture below moves
    `HOME`/`USERPROFILE`, which is where the pack looks for its cache.
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


@pytest.fixture(scope="session")
def _grammar_cache(tmp_path_factory: pytest.TempPathFactory) -> str:
    """One grammar cache for the whole session, at a path the pack always accepts.

    `TREE_SITTER_LANGUAGE_PACK_CACHE_DIR` is the documented override and must
    always be set, never only when a developer already has a cache: the pack
    derives its download directory from the profile the fixture below moves, and
    on Windows it refuses to create `%LOCALAPPDATA%` itself. A fresh redirected
    profile has no `AppData\\Local`, so the pack raised `DownloadError` before
    downloading anything — every parse-dependent test failed on windows-latest.
    A session directory also keeps a cold run to one download per grammar instead
    of one per test.
    """
    existing = _existing_grammar_cache_dir()
    if existing is not None:
        return existing
    return str(tmp_path_factory.mktemp("grammar-cache"))


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch, tmp_path, _grammar_cache) -> None:
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
    # The pack reads its cache from the profile too (on Windows: `%LOCALAPPDATA%`),
    # and refuses to create that directory itself — a redirected profile has no
    # `AppData\Local`, so it raised `DownloadError` before downloading anything and
    # every parse-dependent test failed on a clean runner. The override must always
    # be set, and it is inherited by spawned servers so they agree on the path.
    monkeypatch.setenv("TREE_SITTER_LANGUAGE_PACK_CACHE_DIR", _grammar_cache)
