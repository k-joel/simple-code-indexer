from __future__ import annotations

import json
import math
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

from simple_code_indexer import logging_setup
from simple_code_indexer.config import (
    derive_collection_name,
    faiss_index_path,
    load_settings,
)

BENCH_PATH = Path(__file__).with_name("retrieval_bench.py")
_SPEC = spec_from_file_location("retrieval_bench", BENCH_PATH)
assert _SPEC is not None and _SPEC.loader is not None
bench: Any = module_from_spec(_SPEC)
_SPEC.loader.exec_module(bench)

QUERY_PATH = Path(__file__).with_name("retrieval_queries.json")
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_recall_at_k() -> None:
    ranked = ["a", "b", "c"]

    assert bench.recall_at_k(ranked, ["b"], 1) == 0.0
    assert bench.recall_at_k(ranked, ["b"], 2) == 1.0
    assert bench.recall_at_k(ranked, ["missing"], 3) == 0.0


def test_mrr_at_k() -> None:
    ranked = ["a", "b", "c"]

    assert bench.mrr_at_k(ranked, ["a"], 10) == 1.0
    assert bench.mrr_at_k(ranked, ["b"], 10) == 0.5
    assert bench.mrr_at_k(ranked, ["c"], 2) == 0.0


def test_ndcg_at_k() -> None:
    ranked = ["a", "b", "c", "d"]

    assert bench.ndcg_at_k(ranked, ["a"], 10) == 1.0
    value = bench.ndcg_at_k(ranked, ["a", "c"], 10)
    ideal = 1.0 + 1.0 / math.log2(3)
    expected = 1.0 + 1.0 / math.log2(4)
    assert value == expected / ideal


def test_dedupe_preserves_order_and_normalizes_separators() -> None:
    assert bench._dedupe(["a/b.py", "a\\b.py", "c.py"]) == ["a/b.py", "c.py"]


def test_query_file_is_well_formed() -> None:
    payload = json.loads(QUERY_PATH.read_text(encoding="utf-8"))
    queries = payload["queries"]

    assert len(queries) >= 40
    ids = [case["id"] for case in queries]
    assert len(ids) == len(set(ids))
    for case in queries:
        assert case["expected_files"]
        for relative in case["expected_files"]:
            assert (REPO_ROOT / relative).is_file(), relative


def test_row_metrics_and_aggregate() -> None:
    rows = [
        bench._row_metrics(["a", "b"], ["a"], 10),
        bench._row_metrics(["x", "b"], ["b"], 10),
    ]

    assert set(rows[0]) == {
        "recall@1",
        "recall@5",
        "recall@10",
        "mrr@10",
        "ndcg@10",
    }
    aggregate = bench._aggregate(rows)
    assert aggregate["recall@1"] == 0.5
    assert aggregate["recall@10"] == 1.0
    assert aggregate["mrr@10"] == 0.75


def test_local_state_env_moves_the_whole_local_folder(tmp_path: Path) -> None:
    local = tmp_path / "scratch"

    env = bench._local_state_env(local)

    assert env == {
        "INDEX_DB": str(local.resolve() / "index.db"),
        "FAISS_PATH": str(local.resolve() / "vectors.faiss"),
    }


def test_local_state_env_isolates_settings(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    for name in ("INDEX_DB", "FAISS_PATH"):
        monkeypatch.delenv(name, raising=False)

    baseline = load_settings()
    assert baseline.index_db_path == workspace / ".simple-ci" / "index.db"

    local = tmp_path / "scratch"
    for name, value in bench._local_state_env(local).items():
        monkeypatch.setenv(name, value)
    isolated = load_settings()

    assert isolated.index_db_path == local.resolve() / "index.db"
    assert faiss_index_path(isolated) == local.resolve() / "vectors.faiss"
    assert logging_setup.log_path(isolated) == local.resolve() / "log" / "embed.log"


def test_env_overrides_still_win_when_no_local_path_is_passed(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("INDEX_DB", str(tmp_path / "custom.db"))
    monkeypatch.setenv("FAISS_PATH", str(tmp_path / "custom.faiss"))

    settings = load_settings()

    assert settings.index_db_path == tmp_path / "custom.db"
    assert faiss_index_path(settings) == tmp_path / "custom.faiss"


def test_local_path_derives_a_scratch_qdrant_collection(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    for name in ("INDEX_DB", "FAISS_PATH", "QDRANT_COLLECTION"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings()

    first = bench._isolate_collection(settings, tmp_path / "run-a")
    second = bench._isolate_collection(settings, tmp_path / "run-b")

    assert first.qdrant_collection == derive_collection_name(
        (tmp_path / "run-a").resolve(),
        settings.embed_dim,
        settings.embed_fingerprint,
    )
    assert first.qdrant_collection != settings.qdrant_collection
    assert first.qdrant_collection != second.qdrant_collection


def test_local_path_is_not_present_in_the_cleared_env_overrides() -> None:
    assert "INDEX_DB" not in bench._ENV_OVERRIDES
    assert "FAISS_PATH" not in bench._ENV_OVERRIDES
