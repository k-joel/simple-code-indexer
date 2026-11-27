"""Retrieval-quality benchmark for one embedding model and one vector store.

Run it in a fresh process per model/backend combination (``bench_matrix.py`` does
that) so FAISS and embed module state never leak between runs.

    uv run python tests/retrieval_bench.py \
        --workspace . --local-path artifacts/bench/local \
        --model embeddinggemma-2 --base-url http://localhost:8080 \
        --vector-store sqlite-vec --reset --out artifacts/gemma-sqlite-vec.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from simple_code_indexer import db, embed, indexer, vector_store
from simple_code_indexer.config import (
    Settings,
    derive_collection_name,
    faiss_index_path,
    load_settings,
)
from simple_code_indexer.configfile import LOCAL_DIRNAME
from simple_code_indexer.errors import ConfigError, EmbedError, VectorStoreUnavailable
from simple_code_indexer.setup_wizard import probe

DEFAULT_QUERY_FILE = Path(__file__).with_name("retrieval_queries.json")
_ENV_OVERRIDES = (
    "SIMPLE_CI_EMBED_BASE_URL",
    "SIMPLE_CI_EMBED_MODEL",
    "SIMPLE_CI_EMBED_DIM",
    "SIMPLE_CI_EMBED_API_KEY",
    "SIMPLE_CI_EMBED_TIMEOUT_S",
    "SIMPLE_CI_EMBED_QUERY_PREFIX",
    "SIMPLE_CI_EMBED_DOCUMENT_PREFIX",
    "SIMPLE_CI_VECTOR_STORE",
    "SIMPLE_CI_QDRANT_URL",
    "SIMPLE_CI_QDRANT_COLLECTION",
    "SIMPLE_CI_SQLITE_VEC_CHUNK_SIZE",
    "SIMPLE_CI_SQLITE_VEC_MMAP_SIZE",
    "SIMPLE_CI_SQLITE_VEC_CACHE_SIZE",
    "SIMPLE_CI_SWEEP_SECONDS",
    "SIMPLE_CI_DEBOUNCE_MS",
)


def _local_state_env(local_path: Path) -> dict[str, str]:
    """Point the index and the vectors at one folder instead of `.simple-ci`."""
    resolved = local_path.expanduser().resolve()
    return {
        "SIMPLE_CI_INDEX_DB": str(resolved / "index.db"),
        "SIMPLE_CI_FAISS_PATH": str(resolved / "vectors.faiss"),
    }


def _isolate_collection(settings: Settings, local_path: Path) -> Settings:
    """Derive the Qdrant collection from the scratch folder, not the workspace."""
    return dataclasses.replace(
        settings,
        qdrant_collection=derive_collection_name(
            local_path.expanduser().resolve(),
            settings.embed_dim,
            settings.embed_fingerprint,
        ),
    )


def recall_at_k(ranked: list[str], expected: list[str], k: int) -> float:
    return 1.0 if set(ranked[:k]) & set(expected) else 0.0


def mrr_at_k(ranked: list[str], expected: list[str], k: int) -> float:
    expected_set = set(expected)
    for rank, path in enumerate(ranked[:k], start=1):
        if path in expected_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked: list[str], expected: list[str], k: int) -> float:
    expected_set = set(expected)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, path in enumerate(ranked[:k], start=1)
        if path in expected_set
    )
    ideal = sum(
        1.0 / math.log2(rank + 1) for rank in range(1, min(len(expected_set), k) + 1)
    )
    return dcg / ideal if ideal else 0.0


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in paths:
        path = Path(raw.replace("\\", "/")).as_posix()
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def _row_metrics(ranked: list[str], expected: list[str], k: int) -> dict[str, float]:
    return {
        "recall@1": recall_at_k(ranked, expected, 1),
        "recall@5": recall_at_k(ranked, expected, 5),
        "recall@10": recall_at_k(ranked, expected, 10),
        "mrr@10": mrr_at_k(ranked, expected, min(k, 10)),
        "ndcg@10": ndcg_at_k(ranked, expected, min(k, 10)),
    }


def _aggregate(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    return {key: round(statistics.mean(row[key] for row in rows), 4) for key in rows[0]}


def _reset(settings, backend: str) -> None:
    for suffix in ("", "-wal", "-shm", ".lock"):
        Path(str(settings.index_db_path) + suffix).unlink(missing_ok=True)
    if backend == "faiss":
        faiss_index_path(settings).unlink(missing_ok=True)
        return
    if backend != "qdrant":
        return  # sqlite-vec lives inside the index.db deleted above
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=settings.qdrant_url, check_compatibility=False)
        if client.collection_exists(settings.qdrant_collection):
            client.delete_collection(settings.qdrant_collection)
        client.close()
    except Exception as exc:  # noqa: BLE001 - bench tool reports, never crashes
        print(f"warning: could not reset Qdrant collection: {exc}", file=sys.stderr)


def _git_head(workspace: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _load_queries(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    queries = payload.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError(f"{path} has no queries")
    for case in queries:
        if not isinstance(case, dict) or not isinstance(case.get("query"), str):
            raise TypeError(f"{path} has an invalid query entry")
        expected = case.get("expected_files")
        if not isinstance(expected, list) or not expected:
            raise ValueError(f"{case.get('id')} has no expected_files")
    return queries


def _write_config(
    path: Path,
    *,
    backend: str,
    base_url: str,
    model: str,
    dim: int,
    api_key: str | None,
) -> None:
    from simple_code_indexer import configfile

    embedding: dict[str, Any] = {
        "base_url": base_url,
        "model": model,
        "dim": dim,
        "timeout_s": 120.0,
    }
    if api_key:
        embedding["api_key"] = api_key
    configfile.write_config(
        {
            "version": configfile.CONFIG_VERSION,
            "vector_store": backend,
            "embedding": embedding,
        },
        path,
    )


def run(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(f"workspace not found: {workspace}", file=sys.stderr)
        return 2
    queries = _load_queries(args.queries)

    for name in _ENV_OVERRIDES:
        os.environ.pop(name, None)
    if args.local_path is not None:
        os.environ.update(_local_state_env(args.local_path))
    os.environ["SIMPLE_CI_WORKSPACE_ROOT"] = str(workspace)

    http = probe.Http()
    dim = args.dim
    if dim is None:
        dim = probe.embedding_dim(http, args.base_url, args.model, args.api_key)
        if dim is None:
            print(
                f"embedding endpoint {args.base_url} did not answer; start it first",
                file=sys.stderr,
            )
            return 2
    config_path = Path(tempfile.mkdtemp(prefix="sci-bench-")) / "config.yaml"
    _write_config(
        config_path,
        backend=args.vector_store,
        base_url=args.base_url,
        model=args.model,
        dim=dim,
        api_key=args.api_key,
    )
    os.environ["SIMPLE_CI_CONFIG"] = str(config_path)

    settings = load_settings()
    if args.local_path is not None:
        settings = _isolate_collection(settings, args.local_path)
    if args.reset:
        live_index = workspace / LOCAL_DIRNAME / "index.db"
        if settings.index_db_path.resolve() == live_index.resolve():
            print(
                f"warning: --reset deletes the live workspace index {live_index}; "
                "pass --local-path DIR to isolate the benchmark",
                file=sys.stderr,
            )
        _reset(settings, args.vector_store)

    started = time.perf_counter()
    sweep = indexer.sweep(settings)
    vector_store.flush(settings)
    index_seconds = time.perf_counter() - started

    with db.connect(settings.index_db_path) as conn:
        db.ensure_schema(conn)
        counts = db.stats(conn)

    semantic_rows: list[dict[str, float]] = []
    lexical_rows: list[dict[str, float]] = []
    per_query: list[dict[str, Any]] = []
    latencies: list[float] = []
    with db.connect(settings.index_db_path, readonly=True) as conn:
        for case in queries:
            expected = [Path(item).as_posix() for item in case["expected_files"]]
            query = str(case["query"])
            before = time.perf_counter()
            try:
                vector = embed.embed_query(settings, query)
                hits = vector_store.search(settings, vector, args.limit)
            except (EmbedError, VectorStoreUnavailable) as exc:
                print(f"query failed ({case['id']}): {exc}", file=sys.stderr)
                return 2
            latencies.append((time.perf_counter() - before) * 1000.0)
            semantic_files = _dedupe([hit.path for hit in hits])
            lexical_files = _dedupe(
                [hit.path for hit in db.fts_search(conn, query, args.limit)]
            )
            semantic_metrics = _row_metrics(semantic_files, expected, args.limit)
            lexical_metrics = _row_metrics(lexical_files, expected, args.limit)
            semantic_rows.append(semantic_metrics)
            lexical_rows.append(lexical_metrics)
            per_query.append(
                {
                    "id": case["id"],
                    "query": query,
                    "tags": case.get("tags", []),
                    "expected_files": expected,
                    "semantic_files": semantic_files[: args.limit],
                    "lexical_files": lexical_files[: args.limit],
                    "semantic": semantic_metrics,
                    "lexical": lexical_metrics,
                    "missed_files": [
                        item for item in expected if item not in semantic_files
                    ],
                }
            )

    semantic_aggregate = _aggregate(semantic_rows)
    lexical_aggregate = _aggregate(lexical_rows)
    result = {
        "label": args.label or f"{args.model}/{args.vector_store}",
        "model": args.model,
        "dim": dim,
        "backend": args.vector_store,
        "base_url": args.base_url,
        "workspace": str(workspace),
        "git_head": _git_head(workspace),
        "queries": len(queries),
        "limit": args.limit,
        "index": {
            "checked": sweep.checked,
            "indexed": sweep.indexed,
            "unchanged": sweep.unchanged,
            "removed": sweep.removed,
            "errors": sweep.errors,
            "seconds": round(index_seconds, 2),
            **counts,
        },
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 2),
            "p50": round(statistics.median(latencies), 2),
        },
        "aggregate": {
            "semantic": semantic_aggregate,
            "lexical": lexical_aggregate,
        },
        "per_query": per_query,
    }
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{result['label']}: "
        f"R@1={semantic_aggregate.get('recall@1', 0):.3f} "
        f"R@5={semantic_aggregate.get('recall@5', 0):.3f} "
        f"R@10={semantic_aggregate.get('recall@10', 0):.3f} "
        f"MRR={semantic_aggregate.get('mrr@10', 0):.3f} "
        f"nDCG={semantic_aggregate.get('ndcg@10', 0):.3f} "
        f"p50={result['latency_ms']['p50']:.1f}ms"
    )
    print(
        f"  lexical baseline: "
        f"R@1={lexical_aggregate.get('recall@1', 0):.3f} "
        f"R@10={lexical_aggregate.get('recall@10', 0):.3f} "
        f"nDCG={lexical_aggregate.get('ndcg@10', 0):.3f}"
    )
    print(
        f"  indexed {counts['files']} files / {counts['chunks']} chunks "
        f"in {index_seconds:.1f}s"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERY_FILE)
    parser.add_argument(
        "--vector-store",
        choices=["sqlite-vec", "faiss", "qdrant"],
        default="sqlite-vec",
    )
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--model", required=True)
    parser.add_argument("--dim", type=int, default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--label", default=None)
    parser.add_argument(
        "--local-path",
        type=Path,
        default=None,
        metavar="DIR",
        help="write index.db, the vector table/FAISS file and the Qdrant collection "
        "into DIR instead of <workspace>/.simple-ci",
    )
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ConfigError, OSError, ValueError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
