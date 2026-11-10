"""Run the retrieval benchmark across models and vector stores.

Manual tool: it needs Docker (for the downloaded models) and the embedding
endpoints. Results land in ``artifacts/retrieval-quality-<timestamp>.{md,json}``.

    uv run python tests/bench_matrix.py --workspace .

Existing containers are used as-is; downloaded models are served from a
bench-only compose file so the user's ``simple-ci-embed`` service is untouched.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from simple_code_indexer.setup_wizard import catalog, gpu, probe, provision

ROOT = Path(__file__).resolve().parents[1]
BENCH_SCRIPT = Path(__file__).with_name("retrieval_bench.py")
BENCH_COMPOSE = provision.global_dir(Path.home()) / "docker" / "bench-compose.yml"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    key: str
    label: str
    container: str | None = None
    catalog_key: str | None = None


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "existing-embeddinggemma",
        "EmbeddingGemma 2 (existing container)",
        container="llamacpp-embeddinggemma-2-bf16-text",
    ),
    ModelSpec(
        "existing-qwen4b",
        "Qwen3-Embedding-4B (existing container)",
        container="llamacpp-qwen3-embedding-4b-q6_k",
    ),
    ModelSpec(
        "download-embeddinggemma2",
        "EmbeddingGemma 2 (downloaded)",
        catalog_key="embeddinggemma2",
    ),
    ModelSpec(
        "download-qwen3-0.6b",
        "Qwen3-Embedding-0.6B (downloaded)",
        catalog_key="qwen3-embedding-0.6b",
    ),
    ModelSpec(
        "download-nomic-code",
        "Nomic Embed Code 7B (downloaded)",
        catalog_key="nomic-embed-code",
    ),
)


def _docker(runner: provision.Runner, argv: list[str]) -> provision.CommandResult:
    return runner.run(["docker", *argv], timeout=120.0)


def _resolve_container(runner: provision.Runner, prefix: str) -> str | None:
    containers = provision.list_containers(runner)
    for container in containers:
        if container.name == prefix:
            return container.name
    for container in containers:
        if container.name.startswith(prefix):
            return container.name
    return None


def _stop_other_embeddings(runner: provision.Runner, keep: str | None) -> None:
    for spec in MODELS:
        if not spec.container or spec.container == keep:
            continue
        name = _resolve_container(runner, spec.container)
        if name is None or name == keep:
            continue
        if provision.container_status(runner, name) == "running":
            print(f"  stopping {name} to free the embedding port")
            _docker(runner, ["stop", name])


def _ensure_qdrant(runner: provision.Runner, http: probe.Http) -> None:
    containers = provision.find_qdrant_containers(runner)
    if not containers:
        raise RuntimeError("no qdrant container found")
    name = containers[0].name
    status = provision.container_status(runner, name)
    if status != "running" and not provision.start_container(runner, name):
        raise RuntimeError(f"could not start {name}")
    url = provision.container_url(runner, name, ports=(6333,)) or (
        "http://localhost:6333"
    )
    if not provision.wait_until(lambda: probe.qdrant_ready(http, url), timeout=180.0):
        raise RuntimeError(f"{name} did not become ready at {url}")
    print(f"  qdrant ready at {url}")


def _existing_endpoint(
    runner: provision.Runner,
    http: probe.Http,
    container: str,
) -> tuple[str, str, int]:
    name = _resolve_container(runner, container)
    if name is None:
        raise RuntimeError(f"container {container!r} not found")
    _stop_other_embeddings(runner, name)
    status = provision.container_status(runner, name)
    if status != "running" and not provision.start_container(runner, name):
        raise RuntimeError(f"could not start {name!r}")
    url = provision.container_url(runner, name, provision.EMBED_PORTS)
    if url is None:
        raise RuntimeError(f"{name!r} publishes no embedding port")
    ready = provision.wait_until(
        lambda: bool(probe.list_models(http, url)), timeout=180.0
    )
    if not ready:
        raise RuntimeError(f"{name!r} did not expose /v1/models")
    models = probe.list_models(http, url)
    model = models[0]
    dim = probe.embedding_dim(http, url, model)
    if dim is None:
        raise RuntimeError(f"{name!r} did not answer /v1/embeddings")
    return url, model, dim


def _downloaded_endpoint(
    runner: provision.Runner,
    http: probe.Http,
    spec: ModelSpec,
) -> tuple[str, str, int, str]:
    model = catalog.for_key(spec.catalog_key or "")
    if model is None:
        raise RuntimeError(f"unknown catalog model {spec.catalog_key!r}")
    destination = provision.model_dir(Path.home()) / model.filename
    provision.download_model(model.url, destination)
    gpu_info = gpu.detect_gpu(runner)
    port = provision.available_port("127.0.0.1", 8081)
    service_name = f"bench-{spec.key}"
    container_name = f"simple-ci-bench-{spec.key}"
    service = provision.embed_service(
        model,
        port,
        destination.name,
        image=gpu_info.image,
        gpu_vendor=gpu_info.vendor,
    )
    service["container_name"] = container_name
    _docker(runner, ["rm", "-f", container_name])
    provision.write_compose(BENCH_COMPOSE, {service_name: service})
    started, detail = provision.compose_up(runner, BENCH_COMPOSE, service_name)
    if not started:
        raise RuntimeError(f"docker compose could not start {container_name}: {detail}")
    url = f"http://localhost:{port}"
    ready = provision.wait_until(
        lambda: probe.embedding_dim(http, url, model.api_model) is not None,
        timeout=600.0,
    )
    if not ready:
        raise RuntimeError(f"{container_name} did not become ready")
    dim = probe.embedding_dim(http, url, model.api_model)
    if dim is None:
        raise RuntimeError(f"{container_name} did not answer /v1/embeddings")
    return url, model.api_model, dim, container_name


def _run_bench(
    *,
    workspace: Path,
    label: str,
    model: str,
    base_url: str,
    dim: int,
    backend: str,
    out: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(BENCH_SCRIPT),
        "--workspace",
        str(workspace),
        "--model",
        model,
        "--base-url",
        base_url,
        "--dim",
        str(dim),
        "--vector-store",
        backend,
        "--reset",
        "--label",
        label,
        "--out",
        str(out),
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=7200, check=False
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        print(f"  FAILED: {detail}", file=sys.stderr)
        return {
            "label": label,
            "model": model,
            "dim": dim,
            "backend": backend,
            "base_url": base_url,
            "error": detail or f"exit {completed.returncode}",
        }
    return json.loads(out.read_text(encoding="utf-8"))


def _report(results: list[dict[str, Any]], path: Path) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Retrieval quality benchmark",
        "",
        f"Generated: {timestamp}",
        "",
        "| Model | Dim | Backend | R@1 | R@5 | R@10 | MRR@10 | nDCG@10 | p50 ms | Lexical R@1 | Lexical nDCG |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        if "error" in result:
            lines.append(
                f"| {result['label']} | {result.get('dim', '?')} | "
                f"{result.get('backend', '?')} | FAILED | | | | | | | |"
            )
            continue
        semantic = result["aggregate"]["semantic"]
        lexical = result["aggregate"]["lexical"]
        lines.append(
            f"| {result['label']} | {result['dim']} | {result['backend']} | "
            f"{semantic['recall@1']:.3f} | {semantic['recall@5']:.3f} | "
            f"{semantic['recall@10']:.3f} | {semantic['mrr@10']:.3f} | "
            f"{semantic['ndcg@10']:.3f} | {result['latency_ms']['p50']:.1f} | "
            f"{lexical['recall@1']:.3f} | {lexical['ndcg@10']:.3f} |"
        )
    lines.extend(["", "## Runs", ""])
    for result in results:
        lines.append(f"### {result['label']}")
        if "error" in result:
            lines.append("")
            lines.append(f"Failed: `{result['error']}`")
            lines.append("")
            continue
        index = result["index"]
        lines.append("")
        lines.append(
            f"- endpoint: `{result['base_url']}` model `{result['model']}` "
            f"({result['dim']}-dim)"
        )
        lines.append(
            f"- indexed: {index['files']} files, {index['chunks']} chunks, "
            f"{index['symbols']} symbols in {index['seconds']}s "
            f"(errors: {index['errors']})"
        )
        lines.append(f"- git: `{result.get('git_head') or 'unknown'}`")
        misses = [
            row for row in result["per_query"] if row["semantic"]["recall@10"] == 0.0
        ]
        if misses:
            lines.append("- misses (semantic R@10 = 0):")
            for row in misses[:10]:
                expected = ", ".join(f"`{item}`" for item in row["expected_files"])
                lines.append(f"  - {row['id']}: {row['query']} (expected {expected})")
        else:
            lines.append("- no total misses at R@10")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--models", default="all")
    parser.add_argument("--vector-stores", default="faiss,qdrant")
    parser.add_argument(
        "--report", type=Path, default=ROOT / "artifacts" / "retrieval-quality.md"
    )
    parser.add_argument("--keep-containers", action="store_true")
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    wanted = (
        [spec.key for spec in MODELS]
        if args.models.strip().lower() == "all"
        else [item.strip() for item in args.models.split(",") if item.strip()]
    )
    specs = [spec for spec in MODELS if spec.key in wanted]
    if not specs:
        print("no matching models", file=sys.stderr)
        return 2
    backends = [item.strip() for item in args.vector_stores.split(",") if item.strip()]
    runner = provision.Runner()
    http = probe.Http()
    if "qdrant" in backends:
        try:
            _ensure_qdrant(runner, http)
        except RuntimeError as exc:
            print(f"warning: {exc}", file=sys.stderr)
    run_dir = ROOT / "artifacts" / "bench" / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for spec in specs:
        print(f"== {spec.label} ==")
        container_name: str | None = None
        try:
            if spec.container:
                url, model, dim = _existing_endpoint(runner, http, spec.container)
            else:
                _stop_other_embeddings(runner, None)
                url, model, dim, container_name = _downloaded_endpoint(
                    runner, http, spec
                )
                time.sleep(1.0)
        except RuntimeError as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            for backend in backends:
                results.append(
                    {
                        "label": f"{spec.label} / {backend}",
                        "model": spec.catalog_key or spec.key,
                        "dim": "?",
                        "backend": backend,
                        "error": str(exc),
                    }
                )
            continue
        for backend in backends:
            label = f"{spec.label} / {backend}"
            out = run_dir / f"{spec.key}-{backend}.json"
            print(f"-- {label}")
            results.append(
                _run_bench(
                    workspace=workspace,
                    label=label,
                    model=model,
                    base_url=url,
                    dim=dim,
                    backend=backend,
                    out=out,
                )
            )
        if container_name and not args.keep_containers:
            _docker(runner, ["rm", "-f", container_name])
    report = args.report
    _report(results, report)
    (report.with_suffix(".json")).write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    print(f"report: {report}")
    return 0 if any("error" not in item for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
