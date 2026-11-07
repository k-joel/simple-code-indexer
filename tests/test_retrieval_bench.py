from __future__ import annotations

import json
import math
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

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
