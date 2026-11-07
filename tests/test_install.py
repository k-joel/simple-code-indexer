from __future__ import annotations

from pathlib import Path

from simple_code_indexer.setup_wizard import install
from simple_code_indexer.setup_wizard.provision import CommandResult, Runner


class FakeRunner(Runner):
    def __init__(self, *, uv: str | None = "/uv") -> None:
        self.uv = uv
        self.calls: list[list[str]] = []
        self.result = CommandResult(0)

    def which(self, name: str) -> str | None:
        return self.uv if name == "uv" else None

    def run(self, argv: list[str], *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(list(argv))
        return self.result


def test_install_root_per_platform(tmp_path: Path) -> None:
    home = tmp_path / "home"
    environ = {"APPDATA": str(tmp_path / "appdata")}

    assert install.install_root(home=home, platform="win32", env=environ) == (
        tmp_path / "appdata" / "simple-code-indexer"
    )
    assert install.install_root(home=home, platform="darwin", env={}) == (
        home / "Library" / "Application Support" / "simple-code-indexer"
    )
    assert install.install_root(
        home=home, platform="linux", env={"XDG_DATA_HOME": str(tmp_path / "xdg")}
    ) == (tmp_path / "xdg" / "simple-code-indexer")
    assert install.install_root(home=home, platform="linux", env={}) == (
        home / ".local" / "share" / "simple-code-indexer"
    )


def test_install_root_falls_back_to_appdata_under_home(tmp_path: Path) -> None:
    home = tmp_path / "home"

    assert install.install_root(home=home, platform="win32", env={}) == (
        home / "AppData" / "Roaming" / "simple-code-indexer"
    )


def test_venv_python_per_platform(tmp_path: Path) -> None:
    assert (
        install.venv_python(tmp_path, platform="win32")
        == tmp_path / ".venv" / "Scripts" / "python.exe"
    )
    assert (
        install.venv_python(tmp_path, platform="linux")
        == tmp_path / ".venv" / "bin" / "python"
    )


def test_copy_repo_includes_git_and_excludes_build_state(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (source / ".venv").mkdir()
    (source / ".venv" / "marker").write_text("x", encoding="utf-8")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")
    (source / "src").mkdir()
    (source / "src" / "app.py").write_text("print('x')\n", encoding="utf-8")
    target = tmp_path / "target"

    install.copy_repo(source, target)

    assert (target / ".git" / "config").is_file()
    assert (target / "src" / "app.py").is_file()
    assert not (target / ".venv").exists()
    assert not (target / "__pycache__").exists()

    (target / ".git" / "config").write_text(
        "[core]\n\tinstalled=true\n", encoding="utf-8"
    )
    install.copy_repo(source, target)
    assert "installed=true" in (target / ".git" / "config").read_text(encoding="utf-8")


def test_sync_env_runs_uv_sync_for_the_target(tmp_path: Path) -> None:
    runner = FakeRunner()
    messages: list[str] = []

    assert install.sync_env(runner, tmp_path, messages.append) is True
    assert runner.calls == [["/uv", "sync", "--project", str(tmp_path)]]
    assert messages and "Syncing" in messages[0]

    runner.result = CommandResult(1, "", "boom")
    assert install.sync_env(runner, tmp_path, messages.append) is False


def test_existing_python_prefers_the_venv(tmp_path: Path) -> None:
    fallback = tmp_path / "fallback-python"
    assert (
        install.existing_python(tmp_path, platform="win32", fallback=fallback)
        == fallback
    )

    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    assert (
        install.existing_python(tmp_path, platform="win32", fallback=fallback) == python
    )


def test_server_command_points_at_the_launcher() -> None:
    result = install.InstallResult(
        root=Path("C:/install"),
        python=Path("C:/install/.venv/Scripts/python.exe"),
        launcher=Path("C:/install/run_server.py"),
    )

    assert result.server_command == [
        str(Path("C:/install/.venv/Scripts/python.exe")),
        str(Path("C:/install/run_server.py")),
    ]
