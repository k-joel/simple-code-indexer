import os
import tempfile
from pathlib import Path

import pytest

_SAFE_HOME = Path(tempfile.gettempdir()) / "sci-pytest-home"
"""A profile no developer uses, so a leaked `Path.home()` cannot edit real configs."""


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch) -> None:
    """Never let a developer's ~/.simple-ci/config.yaml change test defaults."""
    monkeypatch.setenv("SIMPLE_CI_CONFIG", "none")
    # Existing tests exercise the single-process writer; sidecar tests override.
    monkeypatch.setenv("SIMPLE_CI_MODE", "embedded")
    # Keep questionary from drawing a TUI if a test instantiates the real Prompter.
    monkeypatch.setenv("SIMPLE_CI_NO_TUI", "1")
    # A harness-launched server inherits these; tests must start from defaults.
    monkeypatch.delenv("SIMPLE_CI_HARNESS", raising=False)
    monkeypatch.delenv("SIMPLE_CI_ROOTS_TIMEOUT_S", raising=False)
    # A wizard path that forgets to thread `home` must not reach a real client
    # config. Only the app-data variables move: `HOME`/`USERPROFILE` stay real so
    # tree-sitter grammars and uv tool environments keep using the real cache.
    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(_SAFE_HOME / "AppData" / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(_SAFE_HOME / "AppData" / "Local"))
