import pytest


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
