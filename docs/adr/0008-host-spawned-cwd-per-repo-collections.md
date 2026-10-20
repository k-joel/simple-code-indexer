# Host-spawned MCP process, cwd workspace, per-repo collections

The MCP server now runs **on the host**, spawned by the harness (`uvx --from <repo> simple-code-indexer`), and takes its workspace from the process working directory: `Path.cwd().resolve()`, overridable with `WORKSPACE_ROOT`. Each workspace gets its own Qdrant collection, `code_index_{slug}_{sha256(path)[:8]}_{embed_dim}`, so two projects never share vectors. Docker (`Dockerfile`, `docker-compose.yml`) is removed from this repo; Qdrant and the embedding endpoint are long-lived host services (`localhost:6333`, `localhost:8080`).

## Context

The container topology ([ADR-0003](./0003-all-in-one-mvp-topology.md)) mounted **this** repo at `/workspace`, so the indexer could only ever index itself; pointing it at another project needed a compose edit and a rebuild. Bind mounts also cost real time: watcher registration over `.venv` blocked for >10 s and the startup reconcile had to be written around `Path.rglob` for the same reason (see `NOTES.md`). Container filesystem mounts are fixed at `docker compose up`, so "open project X and index X" is not expressible with that topology.

## Considered Options

- **Keep the container, mount differently per project:** compose files can only mount paths fixed at start; per-project mounts mean one compose file (and rebuild) per project. Rejected.
- **Sidecar writer + read-only MCP query (topology B):** still needs the same host/container split plus a second process; deferred, not required for acceptance.
- **Host-spawned MCP, workspace = cwd (chosen):** the harness already starts the server inside the project the user has open, so the workspace needs no configuration at all. Native OS filesystem events replace inotify-over-bind-mount.
- **Host-spawned with an explicit `WORKSPACE_ROOT` per project:** requires one harness config entry per project and breaks the zero-configuration goal; kept as an override for unusual setups.

## Consequences

- A single static harness snippet works for every project; `get_status` reports the resolved `workspace` and `collection` so the inference is observable.
- Collection naming is derived, so the pre-existing global `code_index_2560` collection is left orphaned (its points are not migrated); delete it by hand.
- The index DB stays in the workspace at `$WORKSPACE_ROOT/.index/index.db`; each project should gitignore `.index/`.

**Superseded path:** the index and the local config live under `.simple-ci/` — see [ADR-0009](./0009-setup-wizard-managed-services-config.md). Harness registration is now written by `setup.py`.
- The workspace is decided by the harness spawn directory, so `WORKSPACE_ROOT` is the escape hatch when a harness spawns servers from elsewhere.
- Cold `uvx` start is ~5 s (build + install), warm ~0.3 s; harness `timeout: 60000` leaves room, and `uv tool install` is the faster alternative.
- The process exits with the harness session, so freshness while no session is attached is still unguaranteed (unchanged from ADR-0003).
- Single-writer safety now holds per process, not per container: two harness sessions in the same workspace share one SQLite file and collection.
