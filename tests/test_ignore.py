import os
from pathlib import Path

import pytest

from simple_code_indexer import db, embed, indexer
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.errors import EmbedError
from simple_code_indexer.ignore import IgnoreRules
from simple_code_indexer.registry import get_registry


@pytest.fixture(autouse=True)
def _no_embed_network(monkeypatch) -> None:
    """These tests index lexically; embedding failure path is test_embed's job."""

    def _stub(settings, texts):
        raise EmbedError("stubbed out in unit tests")

    monkeypatch.setattr(embed, "embed_texts", _stub)


def _settings(workspace: Path) -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=workspace,
        index_db_path=workspace / ".simple-ci" / "index.db",
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_2560",
        embed_base_url="http://localhost:1",  # hermetic: fail-soft embed path
        embed_model="Qwen3-Embedding-4B-Q6_K",
        embed_dim=2560,
        embed_timeout_s=15.0,
        sweep_seconds=45.0,
        debounce_ms=400,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        vector_store="qdrant",
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _yielded(settings: Settings, stats: indexer.WalkStats | None = None) -> list[str]:
    return sorted(
        indexer.relative_path(settings, path) or str(path)
        for path in indexer.iter_workspace_files(settings, stats=stats)
    )


def test_root_gitignore_prunes_dirs_and_files(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", "artifacts/\nignored*.py\n")
    _write(tmp_path / "artifacts" / "deep" / "x.py", "def x():\n    pass\n")
    _write(tmp_path / "ignored_gen.py", "def generated():\n    pass\n")
    _write(tmp_path / "keep.py", "def keep():\n    pass\n")
    settings = _settings(tmp_path)
    stats = indexer.WalkStats()

    assert _yielded(settings, stats) == ["keep.py"]
    assert stats.ignored_dirs == 1
    assert stats.ignored_files == 1


def test_negation_reincludes_a_file(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", "*.py\n!keep.py\n")
    _write(tmp_path / "keep.py", "def keep():\n    pass\n")
    _write(tmp_path / "other.py", "def other():\n    pass\n")

    assert _yielded(_settings(tmp_path)) == ["keep.py"]


def test_nested_gitignore_overrides_root(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", "*.py\n")
    _write(tmp_path / "sub" / ".gitignore", "!keep.py\n")
    _write(tmp_path / "sub" / "keep.py", "def keep():\n    pass\n")
    _write(tmp_path / "sub" / "other.py", "def other():\n    pass\n")
    _write(tmp_path / "top.py", "def top():\n    pass\n")

    assert _yielded(_settings(tmp_path)) == ["sub/keep.py"]


def test_anchored_pattern_only_matches_at_root(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", "/build\n")
    _write(tmp_path / "build" / "x.py", "def root_build():\n    pass\n")
    _write(tmp_path / "sub" / "build" / "y.py", "def nested_build():\n    pass\n")

    assert _yielded(_settings(tmp_path)) == ["sub/build/y.py"]


def test_rules_cache_follows_gitignore_edits(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    _write(gitignore, "first.py\n")
    rules = IgnoreRules(tmp_path)
    assert rules.is_ignored("first.py")

    _write(gitignore, "second.py\n")
    stat = gitignore.stat()
    os.utime(gitignore, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert not rules.is_ignored("first.py")
    assert rules.is_ignored("second.py")


def test_invalid_gitignore_is_fail_soft(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", "!\n")
    _write(tmp_path / "keep.py", "def keep():\n    pass\n")

    assert _yielded(_settings(tmp_path)) == ["keep.py"]


@pytest.mark.skipif(os.name != "nt", reason="git core.ignorecase default is Windows")
def test_windows_matching_is_case_insensitive(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", "Artifacts/\n")
    _write(tmp_path / "artifacts" / "x.py", "def x():\n    pass\n")

    assert _yielded(_settings(tmp_path)) == []


def test_index_one_file_skips_gitignored(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", "secret.py\n")
    _write(tmp_path / "secret.py", "def secret():\n    pass\n")
    settings = _settings(tmp_path)

    outcome = indexer.index_one_file(settings, tmp_path / "secret.py")
    assert outcome.status == "skipped_filtered"


def test_sweep_removes_newly_ignored_files(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write(tmp_path / "keep.py", "def keep():\n    pass\n")
    _write(tmp_path / "later.py", "def later():\n    pass\n")
    assert indexer.sweep(settings).indexed == 2

    _write(tmp_path / ".gitignore", "later.py\n")
    stats = indexer.sweep(settings)

    assert stats.removed == 1
    assert stats.ignored_files == 1
    assert indexer.LAST_SWEEP_STATS is stats
    with db.connect(settings.index_db_path, readonly=True) as conn:
        paths = [str(row["path"]) for row in conn.execute("SELECT path FROM files")]
    assert paths == ["keep.py"]
