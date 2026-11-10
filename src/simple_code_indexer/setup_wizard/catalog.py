"""Embedding models the wizard can download and serve with llama.cpp."""

from __future__ import annotations

from dataclasses import dataclass

from simple_code_indexer import model_prompts


@dataclass(frozen=True, slots=True)
class EmbeddingModel:
    key: str
    label: str
    url: str
    filename: str
    api_model: str
    dim: int
    pooling: str
    approx_gb: float
    ctx_size: int = 8192
    query_prefix: str | None = None
    document_prefix: str | None = None


# The live probe always overrides `dim`; these values are the offline fallback.
# `mmproj-*.gguf` is the vision/audio projector for EmbeddingGemma 2 and is
# deliberately not part of the download: the text backbone embeds code on its own.
CATALOG: tuple[EmbeddingModel, ...] = (
    EmbeddingModel(
        key="embeddinggemma2",
        label="EmbeddingGemma 2 (text, 768-dim) — recommended",
        url="https://huggingface.co/unsloth/embeddinggemma-2-GGUF/resolve/main/"
        "embeddinggemma-2-BF16.gguf",
        filename="embeddinggemma-2-BF16.gguf",
        api_model="embeddinggemma-2",
        dim=768,
        pooling="mean",
        approx_gb=0.6,
        ctx_size=8192,
        query_prefix=model_prompts.GEMMA_CODE_QUERY,
        document_prefix=model_prompts.GEMMA_CODE_DOCUMENT,
    ),
    EmbeddingModel(
        key="qwen3-embedding-0.6b",
        label="Qwen3-Embedding-0.6B (1024-dim)",
        url="https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/resolve/main/"
        "Qwen3-Embedding-0.6B-Q8_0.gguf",
        filename="Qwen3-Embedding-0.6B-Q8_0.gguf",
        api_model="Qwen3-Embedding-0.6B",
        dim=1024,
        pooling="last",
        approx_gb=0.7,
        ctx_size=8192,
        query_prefix=model_prompts.QWEN_CODE_QUERY,
    ),
    EmbeddingModel(
        key="qwen3-embedding-4b",
        label="Qwen3-Embedding-4B (2560-dim)",
        url="https://huggingface.co/Qwen/Qwen3-Embedding-4B-GGUF/resolve/main/"
        "Qwen3-Embedding-4B-Q6_K.gguf",
        filename="Qwen3-Embedding-4B-Q6_K.gguf",
        api_model="Qwen3-Embedding-4B-Q6_K",
        dim=2560,
        pooling="last",
        approx_gb=3.3,
        ctx_size=8192,
        query_prefix=model_prompts.QWEN_CODE_QUERY,
    ),
    EmbeddingModel(
        key="nomic-embed-code",
        label="Nomic Embed Code 7B (3584-dim, ~4.5 GB download)",
        url="https://huggingface.co/nomic-ai/nomic-embed-code-GGUF/resolve/main/"
        "nomic-embed-code.Q4_K_M.gguf",
        filename="nomic-embed-code.Q4_K_M.gguf",
        api_model="nomic-embed-code",
        dim=3584,
        pooling="last",
        approx_gb=4.5,
        ctx_size=8192,
    ),
)


def for_key(key: str) -> EmbeddingModel | None:
    for model in CATALOG:
        if model.key == key:
            return model
    return None
