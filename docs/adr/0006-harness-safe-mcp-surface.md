# Harness-safe minimal MCP tool surface

MiMoCode's client failed `tools/list` for three reasons found via stdio trace: (1) oversized single-line payload from large `outputSchema`s, (2) `capabilities.tasks` in initialize, (3) per-tool `execution.taskSupport`. We emit none of those, keep descriptions short, and ship only `search_code`, `symbol_lookup`, `get_status` (optional `reindex`).

## Considered Options

- **Full upstream tool surface + schemas:** rejected — harness cannot load it.
- **Minimal tools, no `outputSchema` (chosen):** `mimo mcp list` shows `✓ connected`.
- **Compat proxy to strip fields:** only if a third-party server cannot be controlled; not needed for greenfield.

## Consequences

- Output shapes are documented in the TDD and probe-tested, not enforced by `outputSchema`.
- Grow the tool surface slowly; re-verify `mimo mcp list` after any tools/list change.
- Set `"timeout": 60000` and aim for <3 s startup (lazy parsers; watcher register on background thread).
