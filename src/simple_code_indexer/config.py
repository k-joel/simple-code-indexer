"""Settings resolution: config.yaml first, then env overrides (frozen, no I/O)."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from simple_code_indexer import configfile, model_prompts
from simple_code_indexer.errors import ConfigError

IGNORE_DIRS: frozenset[str] = frozenset(
    {".git", ".index", ".simple-ci", "__pycache__", ".venv", "node_modules"}
)


def is_temp_name(name: str) -> bool:
    """Editor temp files: .#*, *~, *.tmp, *.swp, *.swx, *.part."""
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
    vector_store: str = "sqlite-vec"
    faiss_path: Path | None = None
    sqlite_vec_chunk_size: int = 64
    sqlite_vec_mmap_size: int = 1_073_741_824
    sqlite_vec_cache_size: int = -262_144
    embed_query_prefix: str | None = None
    embed_document_prefix: str | None = None
    embed_fingerprint: str = ""
    config_sources: tuple[Path, ...] = ()
    log_level: str = "debug"
    log_max_bytes: int = 5_000_000
    log_backups: int = 3
    mode: str = "sidecar"
    idle_grace_s: float = 60.0
    heartbeat_s: float = 5.0

    @property
    def sweep_enabled(self) -> bool:
        """True when the periodic reconciliation sweep is configured."""
        return self.sweep_seconds > 0


VECTOR_STORES: frozenset[str] = frozenset({"sqlite-vec", "faiss", "qdrant"})
MODES: frozenset[str] = frozenset({"embedded", "sidecar"})
LOG_LEVELS: frozenset[str] = frozenset(
    {"debug", "info", "warning", "error", "critical"}
)


def faiss_index_path(settings: Settings) -> Path:
    """The FAISS file: explicit `faiss.path`, else next to the lexical index."""
    return settings.faiss_path or settings.index_db_path.parent / "vectors.faiss"


def is_allowed(settings: Settings, path: Path) -> bool:
    """True when the path matches a plugin extension or exact filename."""
    return (
        path.name in settings.allowed_filenames
        or path.suffix.lower() in settings.allowed_exts
    )


def ipv4_loopback(url: str) -> str:
    """Point a loopback URL at 127.0.0.1.

    Docker publishes ``127.0.0.1:<port>`` (IPv4 only), while ``localhost`` on
    Windows resolves to ``::1`` first. Connecting to the dead IPv6 address
    stalls until the connect timeout, so every embedding request paid ~1 s
    before retrying IPv4.
    """
    parts = urlsplit(url)
    if parts.hostname in {"localhost", "::1"}:
        netloc = f"127.0.0.1:{parts.port}" if parts.port else "127.0.0.1"
        return urlunsplit(parts._replace(netloc=netloc))
    return url


def normalize_workspace_path(workspace_root: Path) -> str:
    """Canonical hash input for a workspace: resolved, lowercased, forward slashes.

    Lowercasing keeps Windows drive-letter and directory case from splitting one
    project across two collections.
    """
    return str(workspace_root.resolve()).lower().replace("\\", "/")


def derive_collection_name(
    workspace_root: Path, embed_dim: int, fingerprint: str = ""
) -> str:
    """Per-workspace Qdrant collection: readable slug + path hash + vector dim.

    `fingerprint` pins the vector-shaping profile (document prompt + chunker);
    it is omitted only when the caller passes an empty fingerprint.
    """
    digest = hashlib.sha256(
        normalize_workspace_path(workspace_root).encode("utf-8")
    ).hexdigest()[:8]
    slug = re.sub(r"[^a-z0-9]+", "-", workspace_root.resolve().name.lower())
    suffix = f"_{fingerprint}" if fingerprint else ""
    return f"code_index_{slug.strip('-')[:32] or 'root'}_{digest}_{embed_dim}{suffix}"


def embedding_fingerprint(document_prefix: str | None) -> str:
    """Short hash of the vector-shaping inputs: document prefix + chunker.

    Both change the stored vectors, so either change must invalidate the FAISS
    identity and the derived Qdrant collection. Query prompts are not included:
    they affect only the query side and never stored vectors.
    """
    from simple_code_indexer.parse import CHUNKER_VERSION

    material = f"{document_prefix or ''}\x00{CHUNKER_VERSION}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]


def _prompt(
    section: dict[str, Any],
    key: str,
    env_name: str,
    default: str | None,
    placeholders: tuple[str, ...],
) -> str | None:
    """Env > explicit file value > model default; empty disables the prompt."""
    env_value = os.environ.get(env_name)
    if env_value is not None:
        value: str | None = env_value
    elif key in section:
        raw = section[key]
        if raw is not None and not isinstance(raw, str):
            raise ConfigError(f"'embedding.{key}' must be a string")
        value = raw
    else:
        value = default
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        value.format(**{name: "" for name in placeholders})
    except (KeyError, IndexError, ValueError) as exc:
        raise ConfigError(f"'embedding.{key}' has invalid placeholders: {exc}") from exc
    return value


def workspace_root_from_env() -> Path:
    """`WORKSPACE_ROOT` when set, else the process cwd (the harness spawn dir)."""
    env_root = os.environ.get("WORKSPACE_ROOT")
    return Path(env_root).resolve() if env_root else Path.cwd().resolve()


def _reject_home_workspace(workspace_root: Path) -> None:
    """Refuse a harness spawn that resolved to the user's home directory.

    Some clients (the OpenCode desktop home screen) start the global MCP entry
    with the home directory as cwd. Indexing all of home would write a huge
    `~/.simple-ci/index.db` next to the global config, so fail loudly instead;
    an explicit `WORKSPACE_ROOT` still opts in.
    """
    if os.environ.get("WORKSPACE_ROOT"):
        return
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        return
    if workspace_root == home:
        raise ConfigError(
            "the harness started the server in the user home directory "
            f"({workspace_root}); refusing to index it. Start a session in a "
            "project folder or set WORKSPACE_ROOT to the directory to index."
        )


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


def _vector_store(
    qdrant: dict[str, Any], file_value: str | None, env_value: str | None
) -> str:
    """VECTOR_STORE > `vector_store` > legacy `qdrant:` section > sqlite-vec."""
    for name, value in (("VECTOR_STORE", env_value), ("vector_store", file_value)):
        if value is None:
            continue
        normalized = value.strip().lower()
        if normalized not in VECTOR_STORES:
            raise ConfigError(
                f"{name} must be one of {sorted(VECTOR_STORES)}, got {value!r}"
            )
        return normalized
    return "qdrant" if qdrant else "sqlite-vec"


def _sqlite_vec_section(
    section: dict[str, Any],
) -> tuple[int, int, int]:
    """`sqlite_vec:` tuning: chunk_size, mmap_size, cache_size (KiB, negative)."""
    chunk_size = _pick_int(
        "SQLITE_VEC_CHUNK_SIZE",
        configfile.get_int(section, "chunk_size", where="sqlite_vec"),
        64,
    )
    if chunk_size <= 0:
        raise ConfigError("sqlite_vec.chunk_size must be a positive integer")
    mmap_size = _pick_int(
        "SQLITE_VEC_MMAP_SIZE",
        configfile.get_int(section, "mmap_size", where="sqlite_vec"),
        1_073_741_824,
    )
    if mmap_size < 0:
        raise ConfigError("sqlite_vec.mmap_size must be zero or a positive integer")
    cache_size = _pick_int(
        "SQLITE_VEC_CACHE_SIZE",
        configfile.get_int(section, "cache_size", where="sqlite_vec"),
        -262_144,
    )
    if cache_size == 0:
        raise ConfigError("sqlite_vec.cache_size must not be zero")
    return chunk_size, mmap_size, cache_size


def _faiss_path(raw_path: str | None, workspace_root: Path) -> Path | None:
    if raw_path is None:
        return None
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    return candidate.resolve()


def _mode(file_value: str | None, env_value: str | None) -> str:
    """SIMPLE_CI_MODE > `mode` > sidecar; an unknown name is a config error."""
    for name, value in (("SIMPLE_CI_MODE", env_value), ("mode", file_value)):
        if value is None:
            continue
        normalized = value.strip().lower()
        if normalized not in MODES:
            raise ConfigError(f"{name} must be one of {sorted(MODES)}, got {value!r}")
        return normalized
    return "sidecar"


def _log_level(file_value: str | None, env_value: str | None) -> str:
    """LOG_LEVEL > `log.level` > debug; an unknown name is a config error."""
    for name, value in (("LOG_LEVEL", env_value), ("log.level", file_value)):
        if value is None:
            continue
        normalized = value.strip().lower()
        if normalized not in LOG_LEVELS:
            raise ConfigError(
                f"{name} must be one of {sorted(LOG_LEVELS)}, got {value!r}"
            )
        return normalized
    return "debug"


def load_settings() -> Settings:
    from simple_code_indexer.registry import get_registry

    registry = get_registry()
    workspace_root = workspace_root_from_env()
    _reject_home_workspace(workspace_root)
    config_paths = configfile.config_paths(workspace_root)
    raw = configfile.load_layered_config(config_paths) if config_paths else {}
    embedding = configfile.get_mapping(raw, "embedding")
    qdrant = configfile.get_mapping(raw, "qdrant")
    faiss = configfile.get_mapping(raw, "faiss")
    sqlite_vec = configfile.get_mapping(raw, "sqlite_vec")
    log = configfile.get_mapping(raw, "log")
    env_log_level = os.environ.get("LOG_LEVEL")
    file_log_level = (
        None
        if env_log_level is not None
        else configfile.get_str(log, "level", where="log")
    )
    log_level = _log_level(file_log_level, env_log_level)
    env_vector_store = os.environ.get("VECTOR_STORE")
    file_vector_store = (
        None
        if env_vector_store is not None
        else configfile.get_str(raw, "vector_store", where="config")
    )
    vector_store = _vector_store(qdrant, file_vector_store, env_vector_store)
    vec_chunk_size, vec_mmap_size, vec_cache_size = _sqlite_vec_section(sqlite_vec)
    faiss_path = _faiss_path(
        os.environ.get("FAISS_PATH")
        or configfile.get_str(faiss, "path", where="faiss"),
        workspace_root,
    )

    embed_dim = _pick_int(
        "EMBED_DIM", configfile.get_int(embedding, "dim", where="embedding"), 2560
    )
    embed_model = _pick_str(
        "EMBED_MODEL",
        configfile.get_str(embedding, "model", where="embedding"),
        "Qwen3-Embedding-4B-Q6_K",
    )
    default_query, default_document = model_prompts.defaults_for_model(embed_model)
    query_prefix = _prompt(
        embedding, "query_prefix", "EMBED_QUERY_PREFIX", default_query, ("query",)
    )
    document_prefix = _prompt(
        embedding,
        "document_prefix",
        "EMBED_DOCUMENT_PREFIX",
        default_document,
        ("title", "content"),
    )
    fingerprint = embedding_fingerprint(document_prefix)
    index_db = Path(
        os.environ.get(
            "INDEX_DB",
            str(workspace_root / configfile.LOCAL_DIRNAME / "index.db"),
        )
    )
    api_key = os.environ.get("EMBED_API_KEY")
    if api_key is None:
        api_key = configfile.get_str(embedding, "api_key", where="embedding")
    sweep_seconds = _pick_float(
        "SWEEP_SECONDS",
        configfile.get_float(raw, "sweep_seconds", where="config"),
        0.0,
    )
    if sweep_seconds < 0:
        raise ConfigError(
            "sweep_seconds must be 0 to disable the periodic reconciliation "
            "sweep or a positive number of seconds"
        )
    env_mode = os.environ.get("SIMPLE_CI_MODE")
    file_mode = (
        None
        if env_mode is not None
        else configfile.get_str(raw, "mode", where="config")
    )
    mode = _mode(file_mode, env_mode)
    idle_grace_s = _pick_float(
        "IDLE_GRACE_S",
        configfile.get_float(raw, "idle_grace_s", where="config"),
        60.0,
    )
    if idle_grace_s < 0:
        raise ConfigError("idle_grace_s must be zero or a positive number of seconds")
    heartbeat_s = _pick_float(
        "HEARTBEAT_S",
        configfile.get_float(raw, "heartbeat_s", where="config"),
        5.0,
    )
    if heartbeat_s <= 0:
        raise ConfigError("heartbeat_s must be a positive number of seconds")
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
        or derive_collection_name(workspace_root, embed_dim, fingerprint),
        embed_base_url=_pick_str(
            "EMBED_BASE_URL",
            configfile.get_str(embedding, "base_url", where="embedding"),
            "http://localhost:8080",
        ),
        embed_model=embed_model,
        embed_dim=embed_dim,
        embed_timeout_s=_pick_float(
            "EMBED_TIMEOUT_S",
            configfile.get_float(embedding, "timeout_s", where="embedding"),
            15.0,
        ),
        sweep_seconds=sweep_seconds,
        debounce_ms=_pick_int(
            "DEBOUNCE_MS", configfile.get_int(raw, "debounce_ms", where="config"), 400
        ),
        allowed_exts=registry.extension_allowlist(),
        ignore_dirs=IGNORE_DIRS,
        allowed_filenames=registry.filename_allowlist(),
        embed_api_key=api_key or None,
        embedding_service=_managed_service(embedding, "embedding"),
        qdrant_service=_managed_service(qdrant, "qdrant"),
        config_source=config_paths[-1] if config_paths else None,
        vector_store=vector_store,
        faiss_path=faiss_path,
        sqlite_vec_chunk_size=vec_chunk_size,
        sqlite_vec_mmap_size=vec_mmap_size,
        sqlite_vec_cache_size=vec_cache_size,
        embed_query_prefix=query_prefix,
        embed_document_prefix=document_prefix,
        embed_fingerprint=fingerprint,
        config_sources=config_paths,
        log_level=log_level,
        log_max_bytes=_pick_int(
            "LOG_MAX_BYTES",
            configfile.get_int(log, "max_bytes", where="log"),
            5_000_000,
        ),
        log_backups=_pick_int(
            "LOG_BACKUPS", configfile.get_int(log, "backups", where="log"), 3
        ),
        mode=mode,
        idle_grace_s=idle_grace_s,
        heartbeat_s=heartbeat_s,
    )
