from __future__ import annotations

import shutil
import subprocess
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import pytest

LAUNCHER_PATH = Path(__file__).resolve().parents[1] / "run_server.py"
_SPEC = spec_from_file_location("sci_launcher_test", LAUNCHER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
launcher: Any = module_from_spec(_SPEC)
_SPEC.loader.exec_module(launcher)


def test_main_syncs_only_when_head_moved(monkeypatch) -> None:
    heads = iter(["aaa", "aaa"])
    monkeypatch.setattr(launcher, "_head", lambda: next(heads))
    monkeypatch.setattr(launcher, "_git_pull", lambda: None)
    synced: list[bool] = []
    monkeypatch.setattr(launcher, "_uv_sync", lambda: synced.append(True))
    called: list[bool] = []
    import simple_code_indexer.server as server_mod

    monkeypatch.setattr(server_mod, "main", lambda: called.append(True))

    assert launcher.main() == 0
    assert synced == []
    assert called == [True]

    heads = iter(["aaa", "bbb"])
    monkeypatch.setattr(launcher, "_head", lambda: next(heads))
    assert launcher.main() == 0
    assert synced == [True]
    assert called == [True, True]


def test_git_pull_is_skipped_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLE_CI_GIT_PULL", "0")
    calls: list[list[str]] = []
    monkeypatch.setattr(launcher, "_run", lambda argv, timeout: calls.append(argv))

    launcher._git_pull()

    assert calls == []


def test_git_pull_invokes_the_ff_only_pull(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_CI_GIT_PULL", raising=False)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/git")
    calls: list[list[str]] = []

    def _run(argv: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(launcher, "_run", _run)

    launcher._git_pull()

    assert calls == [
        [
            "git",
            "-C",
            str(launcher.ROOT),
            "pull",
            "--ff-only",
            "--autostash",
            "--quiet",
        ]
    ]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_pull_fast_forwards_a_clone(tmp_path: Path, monkeypatch) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-b", "main")
    _git(origin, "config", "user.email", "bench@example.test")
    _git(origin, "config", "user.name", "bench")
    (origin / "a.txt").write_text("one\n", encoding="utf-8")
    _git(origin, "add", "a.txt")
    _git(origin, "commit", "-m", "one")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)], check=True, capture_output=True
    )
    (origin / "a.txt").write_text("two\n", encoding="utf-8")
    _git(origin, "add", "a.txt")
    _git(origin, "commit", "-m", "two")

    monkeypatch.setattr(launcher, "ROOT", clone)
    launcher._git_pull()

    assert (clone / "a.txt").read_text(encoding="utf-8") == "two\n"


def _git(directory: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(directory), *args], check=True, capture_output=True
    )
