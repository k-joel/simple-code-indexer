"""Reachability probe for the backing services (run this first, always).

Usage: uv run python tests/service_probe.py

Prints OK + vector dimension for the embedding endpoint, and the collections
payload status for Qdrant. Debug nothing else until both pass.
"""

from __future__ import annotations

import json
import os
import urllib.request

EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "http://localhost:8080")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "Qwen3-Embedding-4B-Q6_K")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")


def _post(url: str, payload: dict[str, object], timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def main() -> int:
    try:
        body = _post(
            f"{EMBED_BASE_URL}/v1/embeddings",
            {"model": EMBED_MODEL, "input": "probe"},
            timeout=20,
        )
        print(f"embeddings OK  dim={len(body['data'][0]['embedding'])}")
    except (OSError, KeyError, IndexError, ValueError) as exc:
        print(f"embeddings FAIL {type(exc).__name__}: {exc}")
        return 1
    try:
        with urllib.request.urlopen(f"{QDRANT_URL}/collections", timeout=5) as resp:
            collections = json.load(resp)
        print(f"qdrant OK      status={collections['status']}")
    except (OSError, KeyError, ValueError) as exc:
        print(f"qdrant FAIL {type(exc).__name__}: {exc}")
        return 1
    print("PROBE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
