"""Environment-variable names: all of ours are prefixed `SIMPLE_CI_`.

Environment variables exist for debugging and tests; a production setting is a
CLI flag or a `config.yaml` key (ADR-024). One rule follows from that: every
variable this project reads is spelled ``SIMPLE_CI_<NAME>``, so a process
environment can be audited for our knobs in one pass and can never collide
with an unrelated tool's ``LOG_LEVEL`` or ``MODE``.

There is deliberately no fallback to a bare spelling. The rename that
introduced the prefix is complete — the old names were never documented as
stable, and honouring them silently would keep a second vocabulary alive and
make "what do we read?" unanswerable from the code. A stale shell profile is
fixed by renaming the variable, which the error message names.

This module imports nothing from the package: `config`, `mcp_roots`, `registry`,
`parse` and the sidecar all read it, and a cycle would make importing any one of
them fragile.
"""

from __future__ import annotations

import os

PREFIX = "SIMPLE_CI_"


def name(plain: str) -> str:
    """The prefixed spelling of a bare knob name (`LOG_LEVEL` → `SIMPLE_CI_LOG_LEVEL`)."""
    return plain if plain.startswith(PREFIX) else f"{PREFIX}{plain}"


def get(plain: str) -> str | None:
    """The value of `SIMPLE_CI_<plain>`, or ``None`` when it is not set.

    A set-but-empty value is returned as ``""`` so the caller can decide
    (several knobs treat empty as "disabled"). Pass the bare name; the prefix
    is applied here, and already-prefixed names pass through unchanged.
    """
    return os.environ.get(name(plain))


def flag_default(plain: str, default: str) -> str:
    """`get` with a string default, for the on/off toggles."""
    value = get(plain)
    return default if value is None else value
