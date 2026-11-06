"""Reachability probe for the backing services (run this first, always).

Usage: uv run python tests/service_probe.py

Uses the workspace's resolved config (environment variables still win), so it
probes exactly what the MCP server would use. Qdrant is optional for the default
FAISS backend; `vector_store: qdrant` makes it mandatory.
"""

from __future__ import annotations

import json
import urllib.request

from simple_code_indexer.config import load_settings


def _post(url: str, payload: dict[str, object], timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def main() -> int:
    settings = load_settings()
    try:
        body = _post(
            f"{settings.embed_base_url.rstrip('/')}/v1/embeddings",
            {"model": settings.embed_model, "input": "probe"},
            timeout=20,
        )
        dim = len(body["data"][0]["embedding"])
        print(f"embeddings OK  dim={dim}  model={settings.embed_model}")
        if dim != settings.embed_dim:
            print(
                f"embeddings WARN  configured dim={settings.embed_dim}, "
                f"endpoint returned {dim}"
            )
    except (OSError, KeyError, IndexError, ValueError) as exc:
        print(f"embeddings FAIL {type(exc).__name__}: {exc}")
        return 1
    try:
        with urllib.request.urlopen(
            f"{settings.qdrant_url.rstrip('/')}/collections", timeout=5
        ) as resp:
            collections = json.load(resp)
        print(f"qdrant OK      status={collections['status']}")
    except (OSError, KeyError, ValueError) as exc:
        if settings.vector_store == "qdrant":
            print(f"qdrant FAIL {type(exc).__name__}: {exc}")
            return 1
        print(f"qdrant unavailable (optional for vector_store={settings.vector_store})")
    print("PROBE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
