"""OpenAI-compatible embeddings client (local llama.cpp or a hosted endpoint).

An optional bearer token is sent when `embedding.api_key` / `EMBED_API_KEY` is set.
Queries and documents get the configured model prompts (`embedding.query_prefix`
and `embedding.document_prefix`), so EmbeddingGemma 2 sees its
``task: code retrieval``/``title: ... | text: ...`` prefixes and Qwen3 sees its
query-side ``Instruct: ...`` line. `embed_texts` stays raw for service probes.


Environment fact: llama.cpp rejects a single input larger than its physical
batch (``n_ubatch``, 512 by default), so texts are split to a safe character
budget and their piece vectors mean-pooled — one vector per original text.

Loopback URLs are rewritten to 127.0.0.1: on Windows ``localhost`` resolves to
``::1`` first while Docker publishes IPv4 only, so every request would stall
on the dead IPv6 attempt before retrying.
"""

from __future__ import annotations

import logging
import random
import threading
import time

import httpx

from simple_code_indexer.config import Settings, ipv4_loopback
from simple_code_indexer.errors import EmbedError

logger = logging.getLogger(__name__)

# Outcome of the most recent embed attempt; read by get_status.
LAST_OK: bool | None = None

_ATTEMPTS = 3  # initial + 2 retries (TDD §7.5)
# 512 tokens of Qwen tokenizer over dense code stays under ~1300 chars;
# 1200 leaves margin. Pieces are mean-pooled back to one vector per text.
_SAFE_CHARS = 1200
# Requests are split so one workspace's bulk reindex cannot occupy the shared
# endpoint for the length of an entire file. Several workspaces may share one
# embedding container (one server per workspace), so smaller requests let a
# small file's request interleave instead of timing out behind a huge one.
_MAX_INPUTS = 16
# Per-process cap on concurrent HTTP posts (writer, service probe and query
# can otherwise hit the endpoint together). This is not endpoint-wide limiting.
_MAX_INFLIGHT = 2
_INFLIGHT = threading.BoundedSemaphore(_MAX_INFLIGHT)
_BACKOFF_BASE_S = 0.5
_BACKOFF_CAP_S = 2.0
_sleep = time.sleep  # test seam


def _retry_delay(attempt: int) -> float:
    """Full-jitter exponential backoff: U(0, min(cap, base * 2**attempt))."""
    return random.uniform(0.0, min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2**attempt))


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
    started = time.perf_counter()
    groups = [_split_for_limit(text) for text in texts]
    flat = [piece for group in groups for piece in group]
    vectors: list[list[float]] = []
    batches = 0
    for start in range(0, len(flat), _MAX_INPUTS):
        vectors.extend(_post_embeddings(settings, flat[start : start + _MAX_INPUTS]))
        batches += 1
    pooled: list[list[float]] = []
    index = 0
    for group in groups:
        group_vectors = vectors[index : index + len(group)]
        index += len(group)
        if len(group_vectors) == 1:
            pooled.append(group_vectors[0])
        else:
            pooled.append([sum(values) / len(values) for values in zip(*group_vectors)])
    was_ok = LAST_OK
    LAST_OK = True
    logger.debug(
        "embedded %d text(s) as %d piece(s) in %d batch(es) in %d ms",
        len(texts),
        len(flat),
        batches,
        int((time.perf_counter() - started) * 1000),
    )
    if was_ok is False:
        logger.info("embedding endpoint recovered (%s)", settings.embed_base_url)
    return pooled


def _post_embeddings(settings: Settings, texts: list[str]) -> list[list[float]]:
    """POST {base}/v1/embeddings with retries; validates count and dim."""
    global LAST_OK
    url = ipv4_loopback(settings.embed_base_url.rstrip("/") + "/v1/embeddings")
    payload = {"model": settings.embed_model, "input": texts}
    headers = (
        {"Authorization": f"Bearer {settings.embed_api_key}"}
        if settings.embed_api_key
        else {}
    )
    was_ok = LAST_OK
    error: Exception | None = None
    for attempt in range(_ATTEMPTS):
        attempt_started = time.perf_counter()
        try:
            # connect=1.0: fail fast when the endpoint is down; the full
            # timeout still covers real batch embedding latency.
            with _INFLIGHT:
                response = httpx.post(
                    url,
                    json=payload,
                    headers=headers,
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
            logger.debug(
                "embed request ok: %d vector(s) in %d ms",
                len(vectors),
                int((time.perf_counter() - attempt_started) * 1000),
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
                _sleep(_retry_delay(attempt))
    LAST_OK = False
    if was_ok is not False:
        logger.warning(
            "embedding endpoint failing: %s (%d attempt(s) to %s)",
            error,
            _ATTEMPTS,
            url,
        )
    raise EmbedError(f"embedding failed after {_ATTEMPTS} attempts: {url}") from error


def embed_documents(
    settings: Settings, texts: list[str], *, title: str | None = None
) -> list[list[float]]:
    """Embed indexed chunks, applying the model's document prompt when set.

    `title` is used by EmbeddingGemma 2's ``title: {title} | text: {content}``
    format; pass the file's relative path. Callers that already formatted the
    text can use `embed_texts` instead.
    """
    prefix = settings.embed_document_prefix
    if not prefix:
        return embed_texts(settings, texts)
    title_value = title or "none"
    return embed_texts(
        settings,
        [prefix.format(title=title_value, content=text) for text in texts],
    )


def embed_query(settings: Settings, text: str) -> list[float]:
    """Embed a search query with the model's code-retrieval instruction."""
    prefix = settings.embed_query_prefix
    if prefix:
        text = prefix.format(query=text)
    return embed_texts(settings, [text])[0]
