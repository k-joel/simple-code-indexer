"""Environment-driven settings for the code index (frozen, no import side effects)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

IGNORE_DIRS: frozenset[str] = frozenset(
    {".git", ".index", "__pycache__", ".venv", "node_modules"}
)


def is_temp_name(name: str) -> bool:
    """Editor temp files (TDD §7.8): .#*, *~, *.tmp, *.swp, *.swx, *.part."""
    return name.startswith(".#") or name.endswith(
        ("~", ".tmp", ".swp", ".swx", ".part")
    )


@dataclass(frozen=True, slots=True)
class Settings:
    workspace_root: Path
    index_db_path: Path
    qdrant_url: str
    qdrant_collection: str
    embed_base_url: str
    embed_model: str
    embed_dim: int
    embed_timeout_s: float
    sweep_seconds: float
    debounce_ms: int
    allowed_exts: frozenset[str]
    ignore_dirs: frozenset[str]
    allowed_filenames: frozenset[str] = field(default_factory=frozenset)


def is_allowed(settings: Settings, path: Path) -> bool:
    """True when the path matches a plugin extension or exact filename."""
    return (
        path.name in settings.allowed_filenames
        or path.suffix.lower() in settings.allowed_exts
    )


def load_settings() -> Settings:
    from simple_code_indexer.registry import get_registry

    registry = get_registry()
    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    index_db = Path(
        os.environ.get("INDEX_DB", str(workspace_root / ".index" / "index.db"))
    )
    return Settings(
        workspace_root=workspace_root,
        index_db_path=index_db,
        qdrant_url=os.environ.get("QDRANT_URL", "http://host.docker.internal:6333"),
        qdrant_collection=os.environ.get("QDRANT_COLLECTION", "code_index_2560"),
        embed_base_url=os.environ.get(
            "EMBED_BASE_URL", "http://host.docker.internal:8080"
        ),
        embed_model=os.environ.get("EMBED_MODEL", "Qwen3-Embedding-4B-Q6_K"),
        embed_dim=int(os.environ.get("EMBED_DIM", "2560")),
        embed_timeout_s=15.0,
        sweep_seconds=float(os.environ.get("SWEEP_SECONDS", "45")),
        debounce_ms=int(os.environ.get("DEBOUNCE_MS", "400")),
        allowed_exts=registry.extension_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        allowed_filenames=registry.filename_allowlist(),
    )
