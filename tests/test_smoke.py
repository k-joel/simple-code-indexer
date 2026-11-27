from __future__ import annotations

import json
import subprocess
import sys

import pytest

from simple_code_indexer import cli, logging_setup, main


def test_main_imports() -> None:
    assert callable(main)


def test_faiss_is_importable() -> None:
    import faiss

    assert faiss.__version__


def test_the_default_vector_store_is_sqlite_vec(monkeypatch) -> None:
    monkeypatch.delenv("VECTOR_STORE", raising=False)
    monkeypatch.delenv("FAISS_PATH", raising=False)
    from simple_code_indexer.config import load_settings

    assert load_settings().vector_store == "sqlite-vec"


def test_version_prints_the_package_version(capsys) -> None:
    assert cli._cli_main(["version"]) == 0
    assert capsys.readouterr().out.strip() == logging_setup.package_version()


def test_a_bare_invocation_serves() -> None:
    """No subcommand must still start the MCP server, not print usage."""
    assert cli._split_subcommand([]) == ("serve", [])
    assert cli._split_subcommand(["--unknown-flag"]) == ("serve", ["--unknown-flag"])


def test_setup_and_uninstall_dispatch_to_the_wizard(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("simple_code_indexer.setup_wizard.run", fake_run)

    assert cli._cli_main(["setup", "--dry-run"]) == 0
    assert cli._cli_main(["uninstall", "--yes"]) == 0
    assert calls == [["--dry-run"], ["--uninstall", "--yes"]]


def test_serve_passes_unknown_flags_through(monkeypatch) -> None:
    """A stray argument in a harness config must not leave a dead pipe."""
    imported: list[bool] = []

    def fake_server_main(workspace=None, harness=None) -> None:
        imported.append(True)

    monkeypatch.setattr("simple_code_indexer.server.main", fake_server_main)

    assert cli._cli_main(["serve", "--bogus"]) == 0
    assert imported == [True]


def test_serve_reads_the_workspace_pin(monkeypatch, tmp_path) -> None:
    """A project-scope entry pins its workspace with `serve --workspace <dir>`."""
    seen: list[object] = []

    def fake_server_main(workspace=None, harness=None) -> None:
        seen.append(workspace)

    monkeypatch.setattr("simple_code_indexer.server.main", fake_server_main)

    assert cli._cli_main(["serve", "--workspace", str(tmp_path)]) == 0
    assert cli._cli_main(["serve", f"--workspace={tmp_path}"]) == 0
    assert cli._cli_main(["serve"]) == 0
    assert seen == [tmp_path, tmp_path, None]


def test_serve_reads_the_harness_marker(monkeypatch) -> None:
    """`serve --harness <name>` names the plugin allowed to publish a workspace."""
    seen: list[object] = []

    def fake_server_main(workspace=None, harness=None) -> None:
        seen.append(harness)

    monkeypatch.setattr("simple_code_indexer.server.main", fake_server_main)

    assert cli._cli_main(["serve", "--harness", "commandcode"]) == 0
    assert cli._cli_main(["serve", "--harness=commandcode"]) == 0
    assert cli._cli_main(["serve"]) == 0
    assert seen == ["commandcode", "commandcode", None]


def test_the_module_entry_point_runs_the_cli() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "simple_code_indexer", "version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == logging_setup.package_version()


@pytest.mark.parametrize(
    "command", ["setup", "install", "serve", "uninstall", "status"]
)
def test_every_subcommand_is_exposed(command: str) -> None:
    assert command in cli.SUBCOMMANDS


def test_status_reports_the_recorded_install_kind(
    tmp_path, monkeypatch, capsys
) -> None:
    """`status` answers "am I serving my working tree or a built wheel?"."""
    from simple_code_indexer import configfile

    path = tmp_path / "config.yaml"
    configfile.write_config({"version": 1, "setup": {"install_kind": "editable"}}, path)
    monkeypatch.setattr(configfile, "global_config_path", lambda home=None: path)

    assert cli._cli_main(["status"]) == 0

    assert json.loads(capsys.readouterr().out)["install_kind"] == "editable"


def test_status_install_kind_is_null_without_a_record(
    tmp_path, monkeypatch, capsys
) -> None:
    from simple_code_indexer import configfile

    monkeypatch.setattr(
        configfile, "global_config_path", lambda home=None: tmp_path / "missing.yaml"
    )

    assert cli._cli_main(["status"]) == 0

    assert json.loads(capsys.readouterr().out)["install_kind"] is None
