import json
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from simple_code_indexer import embed
from simple_code_indexer.config import IGNORE_DIRS, Settings
from simple_code_indexer.errors import EmbedError
from simple_code_indexer.registry import get_registry

REAL_EMBED_URL = "http://localhost:8080"


def _settings(base_url: str) -> Settings:
    registry = get_registry()
    return Settings(
        workspace_root=Path("/workspace"),
        index_db_path=Path("/workspace/.simple-ci/index.db"),
        qdrant_url="http://localhost:6333",
        qdrant_collection="code_index_2560",
        embed_base_url=base_url,
        embed_model="Qwen3-Embedding-4B-Q6_K",
        embed_dim=2560,
        embed_timeout_s=15.0,
        sweep_seconds=45.0,
        debounce_ms=400,
        allowed_exts=registry.extension_allowlist(),
        allowed_filenames=registry.filename_allowlist(),
        ignore_dirs=IGNORE_DIRS,
    )


def _embeddings_reachable() -> bool:
    try:
        request = urllib.request.Request(
            f"{REAL_EMBED_URL}/v1/embeddings",
            data=b'{"model":"Qwen3-Embedding-4B-Q6_K","input":"ping"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            if response.status != 200:
                return False
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not data:
        return False
    vector = data[0].get("embedding") if isinstance(data[0], dict) else None
    return isinstance(vector, list) and len(vector) == 2560


def test_unreachable_endpoint_raises_and_marks_not_ok() -> None:
    # Connection refused: fails fast, retries exhausted, still fail-soft-able.
    with pytest.raises(EmbedError):
        embed.embed_texts(_settings("http://localhost:1"), ["anything"])
    assert embed.LAST_OK is False


def test_empty_input_returns_empty() -> None:
    assert embed.embed_texts(_settings("http://localhost:1"), []) == []


def _capture(monkeypatch) -> dict[str, list[str]]:
    captured: dict[str, list[str]] = {}

    def fake_post(settings: Settings, texts: list[str]) -> list[list[float]]:
        captured["texts"] = texts
        return [[0.0] * settings.embed_dim for _ in texts]

    monkeypatch.setattr(embed, "_post_embeddings", fake_post)
    return captured


def test_embed_query_applies_the_query_prefix(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    settings = replace(
        _settings("http://unused"),
        embed_query_prefix="task: code retrieval | query: {query}",
    )

    embed.embed_query(settings, "parse a file")

    assert captured["texts"] == ["task: code retrieval | query: parse a file"]


def test_embed_documents_applies_the_document_prefix(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    settings = replace(
        _settings("http://unused"),
        embed_document_prefix="title: {title} | text: {content}",
    )

    vectors = embed.embed_documents(settings, ["alpha", "beta"], title="src/a.py")

    assert len(vectors) == 2
    assert captured["texts"] == [
        "title: src/a.py | text: alpha",
        "title: src/a.py | text: beta",
    ]


def test_embed_documents_uses_none_without_a_title(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    settings = replace(
        _settings("http://unused"),
        embed_document_prefix="title: {title} | text: {content}",
    )

    embed.embed_documents(settings, ["alpha"])

    assert captured["texts"] == ["title: none | text: alpha"]


def test_no_prompt_leaves_texts_unchanged(monkeypatch) -> None:
    captured = _capture(monkeypatch)

    embed.embed_documents(_settings("http://unused"), ["alpha"], title="src/a.py")

    assert captured["texts"] == ["alpha"]


def test_post_embeddings_rewrites_loopback_to_ipv4(monkeypatch) -> None:
    urls: list[str] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"index": 0, "embedding": [0.0] * 2560}]}

    def fake_post(url: str, **kwargs) -> Response:
        urls.append(url)
        return Response()

    monkeypatch.setattr(embed.httpx, "post", fake_post)

    vectors = embed._post_embeddings(_settings("http://localhost:8080"), ["alpha"])

    assert urls == ["http://127.0.0.1:8080/v1/embeddings"]
    assert len(vectors) == 1


def test_split_for_limit_prefers_lines_and_covers_text() -> None:
    text = "\n".join(f"line {i:04d} " + "x" * 80 for i in range(60))
    pieces = embed._split_for_limit(text)
    assert len(pieces) > 1
    assert "".join(pieces) == text
    assert all(len(p) <= embed._SAFE_CHARS for p in pieces)


def test_split_for_limit_plain_text() -> None:
    text = "y" * (embed._SAFE_CHARS * 2 + 100)
    pieces = embed._split_for_limit(text)
    assert "".join(pieces) == text
    assert all(len(p) <= embed._SAFE_CHARS for p in pieces)


@pytest.mark.skipif(not _embeddings_reachable(), reason="embeddings endpoint down")
def test_real_endpoint_returns_2560_dim() -> None:
    vectors = embed.embed_texts(_settings(REAL_EMBED_URL), ["alpha", "beta"])
    assert len(vectors) == 2
    assert all(len(v) == 2560 for v in vectors)
    assert embed.LAST_OK is True


@pytest.mark.skipif(not _embeddings_reachable(), reason="embeddings endpoint down")
def test_real_endpoint_splits_oversized_text() -> None:
    """A >512-token text still yields exactly one 2560-dim vector (mean-pooled)."""
    long_text = "def handler(request):\n    return request.value\n" * 80
    assert len(long_text) > embed._SAFE_CHARS
    vectors = embed.embed_texts(_settings(REAL_EMBED_URL), [long_text])
    assert len(vectors) == 1
    assert len(vectors[0]) == 2560
