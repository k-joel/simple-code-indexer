from __future__ import annotations

from pathlib import Path

import pytest

from simple_code_indexer.errors import ConfigError
from simple_code_indexer.setup_wizard import install
from simple_code_indexer.setup_wizard.provision import CommandResult, Runner


class FakeRunner(Runner):
    def __init__(self, *, uv: str | None = "/uv") -> None:
        self.uv = uv
        self.calls: list[list[str]] = []
        self.tool_dir = "/tools"
        self.tool_bin = "/tools/bin"
        self.result = CommandResult(0)
        self.responses: dict[tuple[str, ...], CommandResult] = {}
        self.creates_tool_env = False
        self.console_calls: list[list[str]] = []
        self.console_rc = 0

    def which(self, name: str) -> str | None:
        return self.uv if name == "uv" else None

    def run_console(self, argv: list[str], *, timeout: float = 900.0) -> int:
        self.console_calls.append(list(argv))
        return self.console_rc

    def run(self, argv: list[str], *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(list(argv))
        for key, result in self.responses.items():
            if tuple(argv[: len(key)]) == key:
                return result
        if argv[1:4] == ["tool", "dir", "--bin"]:
            return CommandResult(0, self.tool_bin + "\n")
        if argv[1:3] == ["tool", "dir"]:
            return CommandResult(0, self.tool_dir + "\n")
        if argv[1:3] == ["tool", "install"] and self.creates_tool_env:
            (Path(self.tool_dir) / install.TOOL_NAME).mkdir(parents=True, exist_ok=True)
        return self.result


def test_ensure_uv_returns_an_existing_uv() -> None:
    runner = FakeRunner()
    messages: list[str] = []

    assert install.ensure_uv(runner, output=messages.append) == "/uv"
    assert runner.console_calls == []
    assert messages == []


def test_ensure_uv_installs_when_missing() -> None:
    """The deleted setup.py bootstrap is now in the package: uv installs uv."""
    runner = FakeRunner(uv=None)
    messages: list[str] = []

    def which(name: str) -> str | None:
        # The installer puts uv on PATH; the re-check observes it.
        return "/uv" if runner.console_calls else None

    runner.which = which  # type: ignore[method-assign]

    assert install.ensure_uv(runner, output=messages.append) == "/uv"
    assert runner.console_calls and "astral.sh" in " ".join(runner.console_calls[0])
    assert any("installing" in message for message in messages)


def test_ensure_uv_reports_a_failed_installer() -> None:
    runner = FakeRunner(uv=None)
    runner.console_rc = 1
    messages: list[str] = []

    assert install.ensure_uv(runner, output=messages.append) is None
    assert any("failed" in message for message in messages)


def test_the_running_checkout_is_detected() -> None:
    """An editable install must find its own tree, so no --repo-root is needed."""
    from simple_code_indexer.setup_wizard import _default_repo_root

    root = _default_repo_root()

    assert root is not None
    assert (root / "src" / "simple_code_indexer" / "__init__.py").is_file()
    assert (root / "pyproject.toml").is_file()


def test_an_unrelated_project_above_site_packages_is_not_a_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    """A bare pyproject.toml must not be adopted; only our own src/ counts.

    `harnesses._repo_harnesses_dir` carries the same check as
    `setup_wizard._default_repo_root`, and is a plain module we can patch.
    """
    from simple_code_indexer import harnesses as harnesses_pkg

    project = tmp_path / "someapp"
    site = project / ".venv" / "Lib" / "site-packages" / "simple_code_indexer"
    site.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    fake_module = site / "__init__.py"
    fake_module.write_text("", encoding="utf-8")

    monkeypatch.setattr(harnesses_pkg, "__file__", str(fake_module))

    assert harnesses_pkg._repo_harnesses_dir() is None


def test_a_sibling_src_tree_does_not_make_a_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    """A project that merely holds a src/simple_code_indexer/ is still not us.

    The walk must claim the tree this module executes from, so a site-packages
    copy nested inside a checkout cannot adopt the checkout's harness drop-ins.
    """
    from simple_code_indexer import harnesses as harnesses_pkg
    from simple_code_indexer import setup_wizard as wizard_pkg

    site = (
        tmp_path
        / "checkout"
        / ".venv"
        / "Lib"
        / "site-packages"
        / "simple_code_indexer"
    )
    site.mkdir(parents=True)
    foreign = tmp_path / "checkout" / "src" / "simple_code_indexer" / "__init__.py"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("", encoding="utf-8")
    fake_module = site / "__init__.py"
    fake_module.write_text("", encoding="utf-8")

    monkeypatch.setattr(harnesses_pkg, "__file__", str(fake_module))
    monkeypatch.setattr(wizard_pkg, "__file__", str(fake_module))

    assert harnesses_pkg._repo_harnesses_dir() is None
    assert wizard_pkg._default_repo_root() is None


def test_the_mirrored_checkout_check_agrees_with_the_harness_one() -> None:
    """`_default_repo_root` and `_repo_harnesses_dir` must agree on this tree."""
    from simple_code_indexer.harnesses import _repo_harnesses_dir
    from simple_code_indexer.setup_wizard import _default_repo_root

    root = _default_repo_root()

    assert root is not None
    assert _repo_harnesses_dir() == root / "harnesses"


def test_install_spec_from_a_checkout_editable_names_the_checkout(
    tmp_path: Path,
) -> None:
    """Unpublished installs must not need PyPI: link the checkout instead."""
    assert install.install_spec(tmp_path, "0.1.0", editable=True) == str(tmp_path)


def test_install_spec_from_a_checkout_wheel_builds_the_local_tree(
    tmp_path: Path,
) -> None:
    """Prod validation still builds the local tree rather than hitting PyPI."""
    assert install.install_spec(tmp_path, "0.1.0", editable=False) == str(tmp_path)


def test_install_spec_without_a_checkout_pins_the_published_version() -> None:
    assert (
        install.install_spec(None, "0.1.0", editable=False)
        == "simple-code-indexer==0.1.0"
    )


def test_install_spec_without_a_checkout_cannot_be_editable() -> None:
    """There is nothing to link, so fail loudly instead of installing a wheel."""
    with pytest.raises(ConfigError):
        install.install_spec(None, "0.1.0", editable=True)


def test_ensure_tool_installs_and_returns_the_environment(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.tool_dir = str(tmp_path / "tools")
    runner.creates_tool_env = True
    messages: list[str] = []

    root = install.ensure_tool(
        runner,
        spec="simple-code-indexer==1.2.3",
        editable=False,
        output=messages.append,
    )

    assert root == tmp_path / "tools" / install.TOOL_NAME
    assert ["/uv", "tool", "install", "simple-code-indexer==1.2.3"] in runner.calls
    assert any("Installing" in message for message in messages)


def test_ensure_tool_forces_an_editable_reinstall_when_present(
    tmp_path: Path,
) -> None:
    """--force is what lets one env flip flavours without changing the entry."""
    runner = FakeRunner()
    runner.tool_dir = str(tmp_path / "tools")
    runner.creates_tool_env = True
    (tmp_path / "tools" / install.TOOL_NAME).mkdir(parents=True)

    install.ensure_tool(
        runner,
        spec=str(tmp_path),
        editable=True,
        output=lambda _: None,
    )

    assert [
        "/uv",
        "tool",
        "install",
        "--editable",
        "--force",
        str(tmp_path),
    ] in runner.calls


def test_ensure_tool_refreshes_a_wheel_reinstall_when_present(
    tmp_path: Path,
) -> None:
    """--refresh busts the local-build cache; editable has nothing to refresh."""
    runner = FakeRunner()
    runner.tool_dir = str(tmp_path / "tools")
    runner.creates_tool_env = True
    (tmp_path / "tools" / install.TOOL_NAME).mkdir(parents=True)

    install.ensure_tool(
        runner,
        spec="simple-code-indexer==1.2.3",
        editable=False,
        output=lambda _: None,
    )

    assert [
        "/uv",
        "tool",
        "install",
        "--force",
        "--refresh",
        "simple-code-indexer==1.2.3",
    ] in runner.calls


def test_ensure_tool_forces_an_install_past_an_orphan_entrypoint(
    tmp_path: Path,
) -> None:
    """ISS-016: a shim can outlive its environment, so the env alone is not proof."""
    runner = FakeRunner()
    runner.tool_dir = str(tmp_path / "tools")
    runner.tool_bin = str(tmp_path / "bin")
    runner.creates_tool_env = True
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir(parents=True)
    (shim_dir / f"{install.TOOL_NAME}.exe").write_bytes(b"stale")

    install.ensure_tool(
        runner,
        spec=str(tmp_path),
        editable=True,
        output=lambda _: None,
    )

    assert [
        "/uv",
        "tool",
        "install",
        "--editable",
        "--force",
        str(tmp_path),
    ] in runner.calls


def test_ensure_tool_skips_refresh_when_only_the_orphan_entrypoint_exists(
    tmp_path: Path,
) -> None:
    """The shim path forces; it must not invent a cache to refresh."""
    runner = FakeRunner()
    runner.tool_dir = str(tmp_path / "tools")
    runner.tool_bin = str(tmp_path / "bin")
    runner.creates_tool_env = True
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir(parents=True)
    (shim_dir / f"{install.TOOL_NAME}.exe").write_bytes(b"stale")

    install.ensure_tool(
        runner,
        spec="simple-code-indexer==1.2.3",
        editable=False,
        output=lambda _: None,
    )

    assert [
        "/uv",
        "tool",
        "install",
        "--force",
        "simple-code-indexer==1.2.3",
    ] in runner.calls


def test_ensure_tool_omits_force_for_a_first_install(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.tool_dir = str(tmp_path / "tools")
    runner.tool_bin = str(tmp_path / "bin")
    runner.creates_tool_env = True

    install.ensure_tool(
        runner,
        spec=str(tmp_path),
        editable=True,
        output=lambda _: None,
    )

    assert ["/uv", "tool", "install", "--editable", str(tmp_path)] in runner.calls


def test_entrypoint_present_ignores_a_missing_bin_dir(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.tool_bin = str(tmp_path / "no-such-bin")

    assert install.entrypoint_present(runner) is False


def test_entrypoint_present_ignores_other_executables(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.tool_bin = str(tmp_path / "bin")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / f"{install.TOOL_NAME}-other.exe").write_bytes(b"x")

    assert install.entrypoint_present(runner) is False


def test_ensure_tool_raises_when_uv_fails() -> None:
    runner = FakeRunner()
    runner.result = CommandResult(1, "", "boom")

    try:
        install.ensure_tool(
            runner,
            spec="simple-code-indexer==1.2.3",
            editable=False,
            output=lambda _: None,
        )
    except Exception as exc:  # noqa: BLE001 - the type is asserted below
        assert "uv tool install failed" in str(exc)
    else:
        raise AssertionError("ensure_tool should raise on a non-zero exit")


def test_remove_tool_is_a_noop_when_absent(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.tool_dir = str(tmp_path / "tools")

    assert install.remove_tool(runner, lambda _: None) is False
    assert ["/uv", "tool", "uninstall", install.TOOL_NAME] not in runner.calls


def test_remove_tool_uninstalls(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.tool_dir = str(tmp_path / "tools")
    (tmp_path / "tools" / install.TOOL_NAME).mkdir(parents=True)
    messages: list[str] = []

    assert install.remove_tool(runner, messages.append) is True
    assert ["/uv", "tool", "uninstall", install.TOOL_NAME] in runner.calls
    assert messages


def test_server_command_uses_pythonw_on_windows(tmp_path: Path) -> None:
    result = install.InstallResult(root=tmp_path, platform="win32")

    assert result.server_command == [
        str(tmp_path / "Scripts" / "pythonw.exe"),
        "-m",
        "simple_code_indexer",
        "serve",
    ]


def test_server_command_uses_the_env_python_on_posix(tmp_path: Path) -> None:
    result = install.InstallResult(root=tmp_path, platform="linux")

    assert result.server_command == [
        str(tmp_path / "bin" / "python"),
        "-m",
        "simple_code_indexer",
        "serve",
    ]


def test_prune_empty_dirs_stops_at_the_boundary(tmp_path: Path) -> None:
    stop = tmp_path
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)

    removed = install.prune_empty_dirs(deep, stop=stop)

    assert deep in removed
    assert not (tmp_path / "a").exists()
    assert stop.is_dir()
