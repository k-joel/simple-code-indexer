"""Retrieval prompt defaults for the embedding models the wizard supports.

EmbeddingGemma 2 is trained with task prefixes on both sides of a retrieval pair
(``task: code retrieval | query: ...`` for queries and
``title: {title} | text: ...`` for documents); Qwen3-Embedding is instruction
aware on the query side only (``Instruct: ...\\nQuery: ...``). The strings use
`str.format` placeholders so a config file can override them.

Explicit ``embedding.query_prefix`` / ``embedding.document_prefix`` values win;
an explicit empty string disables the default for that side.
"""

from __future__ import annotations

GEMMA_CODE_QUERY = "task: code retrieval | query: {query}"
GEMMA_CODE_DOCUMENT = "title: {title} | text: {content}"

QWEN_CODE_QUERY = (
    "Instruct: Given a code search query, retrieve relevant code snippets "
    "that answer the query\nQuery: {query}"
)


def defaults_for_model(model: str) -> tuple[str | None, str | None]:
    """Return ``(query_prefix, document_prefix)`` for a served model name."""
    name = model.lower()
    if "embeddinggemma" in name:
        return GEMMA_CODE_QUERY, GEMMA_CODE_DOCUMENT
    if "qwen3" in name:
        return QWEN_CODE_QUERY, None
    return None, None
