# Per-workspace runtime log file (`<workspace>/.simple-ci/log/sci.log`)

The MCP server now writes a rotating DEBUG log to
`<workspace>/.simple-ci/log/sci.log` in addition to the INFO summary it keeps on stderr.
The path derives from `settings.index_db_path.parent`, so it follows `INDEX_DB` and always
sits inside the gitignored, index-ignored `.simple-ci/` directory. Rotation is 5 MB with
three backups; `log.level` / `LOG_LEVEL` (default `debug`) controls the file only, stderr
never goes below INFO, and stdout stays the untouched MCP JSON-RPC channel.

## Context

A host-spawned server runs with its stderr piped into the harness
([ADR-0008](./0008-host-spawned-cwd-per-repo-collections.md)); nothing persisted. Every
failure that mattered for diagnosis was lost: `IndexOutcome` and `SweepStats` were discarded,
`db.py` had no logger at all, daemon-thread deaths were only visible through the default
`threading.excepthook`, and a stop mid-index left no record of which file blocked. The only
durable state was `get_status` flags (`embed_ok`, `vector_store_ok`, `last_sweep`), which
carry no exception text and no history.

The TDD already required logs to go "to stderr or a gitignored path"
(`docs/tdd.md` §6.3), so a file inside `.simple-ci/` satisfies the contract; the directory is
in `IGNORE_DIRS`, so writes cannot feed the watcher or the index.

## Considered Options

- **Log to stderr only, rely on the harness:** zero code, but tracebacks disappear with the
  harness's console, and there is no way to inspect a failure after the fact. Rejected.
- **Log to a global file (`~/.simple-ci/log/`):** simple, but one shared writer per process,
  rotation races between workspaces, and no way to correlate lines with the workspace whose
  index they describe. Rejected.
- **Per-workspace file inside `.simple-ci/` (chosen):** bounded writers (the single-writer
  lock, [ADR-0004](./0004-single-writer-sqlite-wal.md), guarantees one process per
  workspace), the file is deleted with the index, and the path is trivially discoverable
  next to `index.db`.
- **Structured JSON lines:** better for machine parsing, worse for `tail`/grep on a running
  machine and no consumer exists yet. Rejected for now; the format is a one-line human
  format with thread name.
- **A logging dependency (`structlog`, `loguru`):** no benefit over stdlib handlers here and
  one more dependency in a minimal server. Rejected.

## Consequences

- `logging_setup.py` owns the handlers. The stderr handler carries its own INFO level because
  a plain `basicConfig(level=INFO)` leaves the handler at NOTSET and propagated DEBUG records
  from the package logger would leak into the harness console.
- The file handler is attached to the root logger with a filter: records from
  `simple_code_indexer.*` at the configured level, and any logger at WARNING+ (so `mcp`
  dispatch failures land in the file). Third-party INFO/DEBUG (`httpx`, `mcp`) stays on
  stderr only.
- `sys.excepthook` and `threading.excepthook` are chained, not replaced: uncaught failures
  are logged with a traceback and still printed to stderr.
- Logging setup is fail-soft: an unwritable `.simple-ci/` warns on stderr and
  `get_status.log_file` reports `null`; the server still serves.
- Logs contain paths, sizes, line ranges, counts, scores and query text (truncated); never
  file contents or chunk text.
- Rotation is not configurable per workspace through the wizard; `log.max_bytes`,
  `log.backups`, `LOG_MAX_BYTES` and `LOG_BACKUPS` exist for unusual cases.
- `get_status` gained `log_file` and `log_level`, a small additive payload change.
- The setup wizard and `run_server.py` keep printing to stderr: they run before settings
  exist (the launcher) or interactively (the wizard).
