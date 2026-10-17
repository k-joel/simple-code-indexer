# Index on save, not git-committed state

Requirement 4 is index-on-save. Upstream Code-Index-MCP treats filesystem events as hints and reconciles **committed** git state, so untracked/edited files are invisible until commit (~30 s). We invert that: a save event triggers immediate per-file reindex of working-tree bytes. Git readiness, commit-gating, and provenance are cut entirely.

## Considered Options

- **Git-committed reconciliation (upstream):** safe for multi-clone provenance, but fails the requirement and was the largest source of operational pain (`stale_commit`, `missing_provenance`, rebuild races).
- **Index on save (chosen):** matches the product contract; one workspace, no git coupling.
- **Hybrid (save + optional git):** complexity without a consumer; rejected.

## Consequences

- Acceptance test can create a `.cpp` file and retrieve it after save without committing.
- No `safe.directory` / `core.autocrlf` container git fixes needed.
- Dropped watch events require a hash reconciliation sweep (see related design).
