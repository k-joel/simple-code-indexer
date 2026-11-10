"""HTTP probes used by the wizard: model list, embedding dimension, Qdrant."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from simple_code_indexer.config import ipv4_loopback

logger = logging.getLogger(__name__)


class Http:
    """Small urllib wrapper with a single injectable seam for tests."""

    def get_json(
        self, url: str, headers: dict[str, str] | None = None, timeout: float = 5.0
    ) -> Any | None:
        response = self._request("GET", url, None, headers, timeout)
        if response is None:
            return None
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return None

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> tuple[int, Any] | None:
        body = json.dumps(payload).encode("utf-8")
        response = self._request(
            "POST",
            url,
            body,
            {"Content-Type": "application/json", **(headers or {})},
            timeout,
        )
        if response is None:
            return None
        try:
            return 200, json.loads(response)
        except json.JSONDecodeError:
            return 200, None

    def _request(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: dict[str, str] | None,
        timeout: float,
    ) -> str | None:
        request = urllib.request.Request(
            url, data=body, headers=headers or {}, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            # An error status still proves the service is up.
            logger.debug("%s %s -> HTTP %s", method, url, exc.code)
            return None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.debug("%s %s failed: %s", method, url, exc)
            return None


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def list_models(http: Http, base_url: str, api_key: str | None = None) -> list[str]:
    """GET /v1/models, returning ids (llama.cpp and most OpenAI-compatible servers)."""
    target = ipv4_loopback(base_url.rstrip("/") + "/v1/models")
    body = http.get_json(target, _headers(api_key))
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if not isinstance(data, list):
        return []
    return [
        item["id"]
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def embedding_dim(
    http: Http,
    base_url: str,
    model: str,
    api_key: str | None = None,
    *,
    timeout: float = 60.0,
) -> int | None:
    """POST one short text and return the vector length."""
    result = http.post_json(
        ipv4_loopback(base_url.rstrip("/") + "/v1/embeddings"),
        {"model": model, "input": ["dimension probe"]},
        _headers(api_key),
        timeout,
    )
    if result is None:
        return None
    body = result[1]
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    vector = first.get("embedding")
    return len(vector) if isinstance(vector, list) else None


def qdrant_ready(http: Http, url: str) -> bool:
    base = ipv4_loopback(url.rstrip("/"))
    return (
        http.get_json(base + "/healthz", timeout=2.0) is not None
        or http.get_json(base + "/collections", timeout=2.0) is not None
    )
