"""Environment-variable names: all of ours are prefixed `SIMPLE_CI_`.

Environment variables exist for debugging and tests; a production setting is a
CLI flag or a `config.yaml` key (ADR-024). Two rules follow from that:

- every variable this project reads is spelled ``SIMPLE_CI_<NAME>``, so a
  process environment can be audited for our knobs in one pass and can never
  collide with an unrelated tool's ``LOG_LEVEL`` or ``MODE``;
- a bare legacy spelling is still honoured, with a one-shot deprecation
  warning, so an existing shell profile or a hand-written harness entry keeps
  working after the rename. The prefixed name always wins.

This module deliberately imports nothing from the package: `config`,
`mcp_roots`, `registry`, `parse` and the sidecar all read it, and a cycle would
make importing any one of them fragile.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

PREFIX = "SIMPLE_CI_"

_warned: set[str] = set()


def name(plain: str) -> str:
    """The prefixed spelling of a bare knob name (`LOG_LEVEL` → `SIMPLE_CI_LOG_LEVEL`)."""
    return plain if plain.startswith(PREFIX) else f"{PREFIX}{plain}"


def get(plain: str) -> str | None:
    """The value of `SIMPLE_CI_<plain>`, else a deprecated bare `<plain>`.

    Returns ``None`` when neither is set, which is what every caller's default
    already expects. A set-but-empty value is returned as ``""`` so the caller
    can decide (several knobs treat empty as "disabled").
    """
    prefixed = name(plain)
    value = os.environ.get(prefixed)
    if value is not None:
        return value
    legacy = os.environ.get(plain)
    if legacy is None:
        return None
    if plain not in _warned:
        _warned.add(plain)
        logger.warning(
            "%s is deprecated; use %s (environment variables are debug-only)",
            plain,
            prefixed,
        )
    return legacy


def flag_default(plain: str, default: str) -> str:
    """`get` with a string default, for the on/off toggles."""
    value = get(plain)
    return default if value is None else value
