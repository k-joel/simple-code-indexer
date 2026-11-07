import pytest


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch) -> None:
    """Never let a developer's ~/.simple-ci/config.yaml change test defaults."""
    monkeypatch.setenv("SIMPLE_CI_CONFIG", "none")
    # Keep questionary from drawing a TUI if a test instantiates the real Prompter.
    monkeypatch.setenv("SIMPLE_CI_NO_TUI", "1")
