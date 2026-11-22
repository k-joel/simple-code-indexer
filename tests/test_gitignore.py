"""The project-scope `.gitignore` offer."""

from __future__ import annotations

from pathlib import Path

from simple_code_indexer.setup_wizard import gitignore


def test_ensure_appends_only_the_missing_patterns(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")

    added = gitignore.ensure(tmp_path, [".cursor/mcp.json", ".simple-ci/"])

    assert added == [".cursor/mcp.json", ".simple-ci/"]
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith("build/\n")
    assert ".cursor/mcp.json" in text and ".simple-ci/" in text


def test_ensure_is_idempotent(tmp_path: Path) -> None:
    patterns = [".cursor/mcp.json", ".simple-ci/"]

    first = gitignore.ensure(tmp_path, patterns)
    second = gitignore.ensure(tmp_path, patterns)

    assert first == patterns
    assert second == []
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert text.count(".simple-ci/") == 1


def test_a_directory_pattern_covers_the_files_below_it(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(".cursor/\n", encoding="utf-8")

    assert gitignore.missing(tmp_path, [".cursor/mcp.json"]) == []


def test_a_missing_final_newline_is_preserved_as_a_separator(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("build/", encoding="utf-8")

    gitignore.ensure(tmp_path, [".simple-ci/"])

    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines == ["build/", ".simple-ci/"]


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    added = gitignore.ensure(tmp_path, [".simple-ci/"], dry_run=True)

    assert added == [".simple-ci/"]
    assert not (tmp_path / ".gitignore").exists()


def test_relative_targets_drop_configs_outside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    inside = workspace / ".cursor" / "mcp.json"
    outside = tmp_path / "home" / "mcp.json"

    patterns = gitignore.relative_targets([inside, outside], workspace)

    assert patterns == [".cursor/mcp.json", ".simple-ci/"]


def test_relative_targets_deduplicate(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    config = workspace / ".mcp.json"

    patterns = gitignore.relative_targets([config, config], workspace)

    assert patterns == [".mcp.json", ".simple-ci/"]


def test_a_directory_without_git_is_not_a_workspace(tmp_path: Path) -> None:
    assert not gitignore.is_git_workspace(tmp_path)

    (tmp_path / ".git").mkdir()

    assert gitignore.is_git_workspace(tmp_path)


def test_a_repository_above_the_workspace_counts(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    workspace = tmp_path / "nested"
    workspace.mkdir()

    assert gitignore.is_git_workspace(workspace)


def test_an_existing_gitignore_counts_even_without_git(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")

    assert gitignore.is_git_workspace(tmp_path)
