"""Environment-driven settings for the code index (frozen, no import side effects)."""

from __future__ import annotations

import hashlib
import os
import re
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


def normalize_workspace_path(workspace_root: Path) -> str:
    """Canonical hash input for a workspace: resolved, lowercased, forward slashes.

    Lowercasing keeps Windows drive-letter and directory case from splitting one
    project across two collections.
    """
    return str(workspace_root.resolve()).lower().replace("\\", "/")


def derive_collection_name(workspace_root: Path, embed_dim: int) -> str:
    """Per-workspace Qdrant collection: readable slug + path hash + vector dim."""
    digest = hashlib.sha256(
        normalize_workspace_path(workspace_root).encode("utf-8")
    ).hexdigest()[:8]
    slug = re.sub(r"[^a-z0-9]+", "-", workspace_root.resolve().name.lower())
    return f"code_index_{slug.strip('-')[:32] or 'root'}_{digest}_{embed_dim}"


def workspace_root_from_env() -> Path:
    """`WORKSPACE_ROOT` when set, else the process cwd (the harness spawn dir)."""
    env_root = os.environ.get("WORKSPACE_ROOT")
    return Path(env_root).resolve() if env_root else Path.cwd().resolve()


def load_settings() -> Settings:
    from simple_code_indexer.registry import get_registry

    registry = get_registry()
    workspace_root = workspace_root_from_env()
    embed_dim = int(os.environ.get("EMBED_DIM", "2560"))
    index_db = Path(
        os.environ.get("INDEX_DB", str(workspace_root / ".index" / "index.db"))
    )
    return Settings(
        workspace_root=workspace_root,
        index_db_path=index_db,
        qdrant_url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
        qdrant_collection=os.environ.get("QDRANT_COLLECTION")
        or derive_collection_name(workspace_root, embed_dim),
        embed_base_url=os.environ.get("EMBED_BASE_URL", "http://localhost:8080"),
        embed_model=os.environ.get("EMBED_MODEL", "Qwen3-Embedding-4B-Q6_K"),
        embed_dim=embed_dim,
        embed_timeout_s=15.0,
        sweep_seconds=float(os.environ.get("SWEEP_SECONDS", "45")),
        debounce_ms=int(os.environ.get("DEBOUNCE_MS", "400")),
        allowed_exts=registry.extension_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        allowed_filenames=registry.filename_allowlist(),
    )
