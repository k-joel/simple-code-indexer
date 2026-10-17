# Single workspace, no multi-repo registry

One workspace is mounted at `/workspace` and indexed as a whole. Upstream's multi-repo registry, `RepoResolver`, path sandbox, and worktree identity rules are cut. Ignore rules come from a small allowlist/ignore set, not per-repo gitignore identity.

## Considered Options

- **Multi-repo registry (upstream):** required for product scope we do not have; large complexity tax.
- **Single workspace (chosen):** matches requirement set and acceptance test.

## Consequences

- No `repository=` argument on tools.
- Serving multiple roots later needs a sandbox allowlist (`MCP_ALLOWED_ROOTS`-style) and is out of scope for v1.
- Index lives under `/workspace/.index/` (see TDD data layout).
