# Single-writer SQLite + WAL (no staged generations)

Upstream's staged generation rebuilds with optimistic publish raced under concurrent sessions (`expected_generation` mismatch). We use one SQLite file with WAL, `busy_timeout`, and a single index writer. Readers (MCP query path) open read-only connections. No generation staging, no quarantine tree.

## Considered Options

- **Staged generations + atomic publish (upstream):** crash-safe git-synced rebuilds; overkill and racy for one workspace.
- **Single-writer WAL (chosen):** simple, enough for one workspace and one writer thread.
- **Multi-writer with locking:** unnecessary complexity; no concurrent writers in topology A.

## Consequences

- Schema is plain tables: `files`, `symbols`, `chunks`, `chunks_fts` — no generation columns.
- Topology B is safe because the sidecar owns writes and MCP is read-only.
- Rebuild is just re-running `index_one_file` / startup reconcile, not a publish dance.
