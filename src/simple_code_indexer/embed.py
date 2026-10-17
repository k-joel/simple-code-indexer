"""OpenAI-compatible embeddings client (local llama.cpp; never sets a key).

Environment fact: this llama.cpp instance has physical batch size 512, so any
single input over ~512 tokens is rejected with HTTP 500. Texts are therefore
split to a safe character budget and their piece vectors mean-pooled — one
vector per original text.
"""

from __future__ import annotations

import logging
import time

import httpx

from simple_code_indexer.config import Settings
from simple_code_indexer.errors import EmbedError

logger = logging.getLogger(__name__)

# Outcome of the most recent embed attempt; read by get_status.
LAST_OK: bool | None = None

_ATTEMPTS = 3  # initial + 2 retries (TDD §7.5)
# 512 tokens of Qwen tokenizer over dense code stays under ~1300 chars;
# 1200 leaves margin. Pieces are mean-pooled back to one vector per text.
_SAFE_CHARS = 1200


def _split_for_limit(text: str, limit: int = _SAFE_CHARS) -> list[str]:
    """Split text into ≤limit-char pieces, preferring line boundaries."""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + limit // 2, end)
            if cut != -1:
                end = cut + 1
        piece = text[start:end]
        if piece.strip():
            pieces.append(piece)
        start = end
    return pieces or [text[:limit]]


def embed_texts(settings: Settings, texts: list[str]) -> list[list[float]]:
    """Embed texts; raise EmbedError on failure. One vector per input text."""
    global LAST_OK
    if not texts:
        return []
    groups = [_split_for_limit(text) for text in texts]
    flat = [piece for group in groups for piece in group]
    vectors = _post_embeddings(settings, flat)
    pooled: list[list[float]] = []
    index = 0
    for group in groups:
        group_vectors = vectors[index : index + len(group)]
        index += len(group)
        if len(group_vectors) == 1:
            pooled.append(group_vectors[0])
        else:
            pooled.append([sum(values) / len(values) for values in zip(*group_vectors)])
    LAST_OK = True
    return pooled


def _post_embeddings(settings: Settings, texts: list[str]) -> list[list[float]]:
    """POST {base}/v1/embeddings with retries; validates count and dim."""
    global LAST_OK
    url = settings.embed_base_url.rstrip("/") + "/v1/embeddings"
    payload = {"model": settings.embed_model, "input": texts}
    error: Exception | None = None
    for attempt in range(_ATTEMPTS):
        try:
            # connect=1.0: fail fast when the endpoint is down; the full
            # timeout still covers real batch embedding latency.
            response = httpx.post(
                url,
                json=payload,
                timeout=httpx.Timeout(settings.embed_timeout_s, connect=1.0),
            )
            response.raise_for_status()
            body = response.json()
            data = sorted(body["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in data]
            if len(vectors) != len(texts):
                raise EmbedError(f"expected {len(texts)} vectors, got {len(vectors)}")
            if any(len(vector) != settings.embed_dim for vector in vectors):
                raise EmbedError(
                    f"dimension mismatch: expected {settings.embed_dim}, "
                    f"got {len(vectors[0])}"
                )
            return vectors
        except (
            EmbedError,
            httpx.HTTPError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as exc:
            error = exc
            logger.debug("embed attempt %d/%d failed: %s", attempt + 1, _ATTEMPTS, exc)
            if attempt + 1 < _ATTEMPTS:
                time.sleep(0.25 * (attempt + 1))
    LAST_OK = False
    raise EmbedError(f"embedding failed after {_ATTEMPTS} attempts: {url}") from error


def embed_query(settings: Settings, text: str) -> list[float]:
    """Embed a search query with the same endpoint used for chunks."""
    return embed_texts(settings, [text])[0]
