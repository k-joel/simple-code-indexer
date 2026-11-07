"""Global `config.yaml` discovery and parsing.

There is exactly one config file: `~/.simple-ci/config.yaml`. Project-local
`<workspace>/.simple-ci/config.yaml` files are legacy — the wizard migrates them
into the global file and the server never reads them. Individual settings are
still overridable by their own environment variables in `config.py`.

`SIMPLE_CI_CONFIG` replaces discovery entirely with one explicit file (`none`/
`off` disables discovery, which is what the test suite uses).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from simple_code_indexer.errors import ConfigError

logger = logging.getLogger(__name__)

LOCAL_DIRNAME = ".simple-ci"
CONFIG_FILENAME = "config.yaml"
CONFIG_VERSION = 1

_DISABLED_VALUES = {"none", "off"}


def global_config_path(home: Path | None = None) -> Path:
    """The single supported config location."""
    return (home or Path.home()) / LOCAL_DIRNAME / CONFIG_FILENAME


def config_paths(workspace_root: Path, home: Path | None = None) -> tuple[Path, ...]:
    """Config files to read: the global file, or `SIMPLE_CI_CONFIG`.

    `workspace_root` is accepted for call-site compatibility; local configs are
    deliberately no longer part of discovery.
    """
    del workspace_root
    explicit = os.environ.get("SIMPLE_CI_CONFIG")
    if explicit is not None:
        if explicit.strip().lower() in _DISABLED_VALUES:
            return ()
        path = Path(explicit).expanduser()
        if path.is_file():
            return (path,)
        logger.warning("SIMPLE_CI_CONFIG points at a missing file: %s", path)
        return ()
    global_config = global_config_path(home)
    return (global_config,) if global_config.is_file() else ()


def find_config_file(workspace_root: Path, home: Path | None = None) -> Path | None:
    """The active config file; `SIMPLE_CI_CONFIG` wins."""
    paths = config_paths(workspace_root, home)
    return paths[-1] if paths else None


def load_layered_config(paths: Iterable[Path]) -> dict[str, Any]:
    """Deep-merge config files in order: later mappings override earlier keys."""
    merged: dict[str, Any] = {}
    for path in paths:
        merged = _deep_merge(merged, load_config(path))
    return merged


def merge_configs(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Public wrapper used when migrating a legacy local config."""
    return _deep_merge(base, overlay)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Mappings merge recursively; scalars, lists and explicit nulls replace."""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path) -> dict[str, Any]:
    """Read one YAML file; empty files are `{}`, non-mappings raise ConfigError."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"config {path} must contain a mapping, got {type(raw).__name__}"
        )
    version = raw.get("version")
    if version is not None and version != CONFIG_VERSION:
        logger.warning(
            "config %s has version %r; this build expects %d",
            path,
            version,
            CONFIG_VERSION,
        )
    return raw


def write_config(data: dict[str, Any], path: Path) -> None:
    """Atomically write a YAML config (0600 on POSIX: it may hold an API key)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    if os.name == "posix":
        path.chmod(0o600)


def get_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a nested mapping, treating absent/null as `{}`."""
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' must be a mapping, got {type(value).__name__}")
    return value


def get_str(section: dict[str, Any], key: str, *, where: str) -> str | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"'{where}.{key}' must be a string")
    return value


def get_int(section: dict[str, Any], key: str, *, where: str) -> int | None:
    value = section.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"'{where}.{key}' must be an integer")
    return value


def get_float(section: dict[str, Any], key: str, *, where: str) -> float | None:
    value = section.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"'{where}.{key}' must be a number")
    return float(value)
