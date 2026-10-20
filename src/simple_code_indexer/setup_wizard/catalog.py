"""Embedding models the wizard can download and serve with llama.cpp."""

from __future__ import annotations

from dataclasses import dataclass


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


# The live probe always overrides `dim`; these values are the offline fallback.
CATALOG: tuple[EmbeddingModel, ...] = (
    EmbeddingModel(
        key="embeddinggemma2",
        label="EmbeddingGemma 2 (271M text, 768-dim) — recommended",
        url="https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/main/"
        "embeddinggemma-2-Q8_0.gguf",
        filename="embeddinggemma-2-Q8_0.gguf",
        api_model="embeddinggemma-2",
        dim=768,
        pooling="mean",
        approx_gb=0.4,
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
    ),
)
