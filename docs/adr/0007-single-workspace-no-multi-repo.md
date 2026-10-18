# Single workspace, no multi-repo registry

**Amended by [ADR-0008](./0008-host-spawned-cwd-per-repo-collections.md):** there is still exactly one workspace per server process, but it comes from the process cwd instead of a `/workspace` mount, and each workspace owns a derived Qdrant collection. The cuts below (no `repository=` argument, no path sandbox, no worktree identity) stand.

One workspace is mounted at `/workspace` and indexed as a whole. Upstream's multi-repo registry, `RepoResolver`, path sandbox, and worktree identity rules are cut. Ignore rules come from a small allowlist/ignore set, not per-repo gitignore identity.

## Considered Options

- **Multi-repo registry (upstream):** required for product scope we do not have; large complexity tax.
- **Single workspace (chosen):** matches requirement set and acceptance test.

## Consequences

- No `repository=` argument on tools.
- Serving multiple roots later needs a sandbox allowlist (`MCP_ALLOWED_ROOTS`-style) and is out of scope for v1.
- Index lives under `/workspace/.index/` (see TDD data layout).
