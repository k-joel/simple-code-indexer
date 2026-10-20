"""Settings resolution: config.yaml first, then env overrides (frozen, no I/O)."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simple_code_indexer.errors import ConfigError

IGNORE_DIRS: frozenset[str] = frozenset(
    {".git", ".index", ".simple-ci", "__pycache__", ".venv", "node_modules"}
)


def is_temp_name(name: str) -> bool:
    """Editor temp files (TDD §7.8): .#*, *~, *.tmp, *.swp, *.swx, *.part."""
    return name.startswith(".#") or name.endswith(
        ("~", ".tmp", ".swp", ".swx", ".part")
    )


@dataclass(frozen=True, slots=True)
class ManagedService:
    """A Docker container the MCP server starts and waits for before serving."""

    container: str
    compose_file: Path | None = None
    compose_service: str | None = None
    startup_timeout_s: float = 45.0


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
    embed_api_key: str | None = None
    embedding_service: ManagedService | None = None
    qdrant_service: ManagedService | None = None
    config_source: Path | None = None


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


def _pick_str(env_name: str, file_value: str | None, default: str) -> str:
    env_value = os.environ.get(env_name)
    if env_value is not None:
        return env_value
    return file_value if file_value is not None else default


def _pick_int(env_name: str, file_value: int | None, default: int) -> int:
    env_value = os.environ.get(env_name)
    if env_value is None:
        return file_value if file_value is not None else default
    try:
        return int(env_value)
    except ValueError as exc:
        raise ConfigError(f"{env_name} must be an integer, got {env_value!r}") from exc


def _pick_float(env_name: str, file_value: float | None, default: float) -> float:
    env_value = os.environ.get(env_name)
    if env_value is None:
        return file_value if file_value is not None else default
    try:
        return float(env_value)
    except ValueError as exc:
        raise ConfigError(f"{env_name} must be a number, got {env_value!r}") from exc


def _managed_service(section: dict[str, Any], where: str) -> ManagedService | None:
    raw = section.get("service")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"'{where}.service' must be a mapping")
    container = raw.get("container")
    if not isinstance(container, str) or not container:
        raise ConfigError(f"'{where}.service.container' must be a non-empty string")
    compose_file: Path | None = None
    raw_compose = raw.get("compose_file")
    if raw_compose is not None:
        if not isinstance(raw_compose, str) or not raw_compose:
            raise ConfigError(f"'{where}.service.compose_file' must be a string")
        compose_file = Path(raw_compose).expanduser()
    compose_service = raw.get("compose_service")
    if compose_service is not None and (
        not isinstance(compose_service, str) or not compose_service
    ):
        raise ConfigError(f"'{where}.service.compose_service' must be a string")
    timeout = raw.get("startup_timeout_s", 45.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ConfigError(f"'{where}.service.startup_timeout_s' must be a number")
    return ManagedService(
        container=container,
        compose_file=compose_file,
        compose_service=compose_service,
        startup_timeout_s=float(timeout),
    )


def load_settings() -> Settings:
    from simple_code_indexer import configfile
    from simple_code_indexer.registry import get_registry

    registry = get_registry()
    workspace_root = workspace_root_from_env()
    config_path = configfile.find_config_file(workspace_root)
    raw = configfile.load_config(config_path) if config_path is not None else {}
    embedding = configfile.get_mapping(raw, "embedding")
    qdrant = configfile.get_mapping(raw, "qdrant")

    embed_dim = _pick_int(
        "EMBED_DIM", configfile.get_int(embedding, "dim", where="embedding"), 2560
    )
    index_db = Path(
        os.environ.get(
            "INDEX_DB",
            str(workspace_root / configfile.LOCAL_DIRNAME / "index.db"),
        )
    )
    api_key = os.environ.get("EMBED_API_KEY")
    if api_key is None:
        api_key = configfile.get_str(embedding, "api_key", where="embedding")
    return Settings(
        workspace_root=workspace_root,
        index_db_path=index_db,
        qdrant_url=_pick_str(
            "QDRANT_URL",
            configfile.get_str(qdrant, "url", where="qdrant"),
            "http://localhost:6333",
        ),
        qdrant_collection=os.environ.get("QDRANT_COLLECTION")
        or configfile.get_str(qdrant, "collection", where="qdrant")
        or derive_collection_name(workspace_root, embed_dim),
        embed_base_url=_pick_str(
            "EMBED_BASE_URL",
            configfile.get_str(embedding, "base_url", where="embedding"),
            "http://localhost:8080",
        ),
        embed_model=_pick_str(
            "EMBED_MODEL",
            configfile.get_str(embedding, "model", where="embedding"),
            "Qwen3-Embedding-4B-Q6_K",
        ),
        embed_dim=embed_dim,
        embed_timeout_s=_pick_float(
            "EMBED_TIMEOUT_S",
            configfile.get_float(embedding, "timeout_s", where="embedding"),
            15.0,
        ),
        sweep_seconds=_pick_float(
            "SWEEP_SECONDS",
            configfile.get_float(raw, "sweep_seconds", where="config"),
            45.0,
        ),
        debounce_ms=_pick_int(
            "DEBOUNCE_MS", configfile.get_int(raw, "debounce_ms", where="config"), 400
        ),
        allowed_exts=registry.extension_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        allowed_filenames=registry.filename_allowlist(),
        embed_api_key=api_key or None,
        embedding_service=_managed_service(embedding, "embedding"),
        qdrant_service=_managed_service(qdrant, "qdrant"),
        config_source=config_path,
    )
