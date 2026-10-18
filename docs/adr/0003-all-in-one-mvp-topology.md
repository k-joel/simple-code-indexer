# All-in-one process for MVP (topology A)

**Superseded by [ADR-0008](./0008-host-spawned-cwd-per-repo-collections.md)** for the container part: the all-in-one *process* shape (MCP loop + watcher/writer in one process) still holds, but it runs on the host instead of a container, and the workspace is the process cwd rather than a `/workspace` mount. The queue/worker split is unchanged.

One container process hosts the MCP stdio server **and** the watcher/index writer. Watching only happens while a harness session is attached. The queue/worker interface is kept so a later sidecar (topology B: always-on writer + read-only MCP) is a config change, not a rewrite.

## Considered Options

- **All-in-one (chosen):** single writer by construction; matches how MiMoCode attaches via `docker exec`; smallest MVP.
- **Sidecar now:** always-on indexing while harness is closed; two processes, shared SQLite WAL + Qdrant. Deferred — not required for acceptance.

## Consequences

- Single-writer invariant is trivial in topology A.
- Index freshness while the harness is closed is not guaranteed until topology B.
- Startup must still beat the harness tool-fetch budget (<3 s target, `timeout: 60000` as safety).
