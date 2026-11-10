# Changelog

All notable changes to simple-code-indexer are documented in this file. It is a curated,
user-facing history — not a copy of the git log. **Every agent session must add the
notable changes it produced here before finishing.** See
[ref-docs/changelog-best-practices.md](../ref-docs/changelog-best-practices.md) for the
format and the rules for updating it.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `setup.py --install-only`: copy this checkout to the per-user install directory and exit,
  without prompts, config, services, harness entries, or an environment sync of the copy.
  `--install-dir` and `--dry-run` are honored.
- `ref-docs/mcp-test-process.md`: a repeatable end-to-end MCP integration test that installs
  from scratch, hands the live session to a secondary harness agent, and verifies indexing,
  retrieval and shutdown.
- Harness lifecycle watchdog: the server now exits when a process in its launch chain
  disappears (uv's venv trampoline and uv launcher included), so a harness that keeps the stdio
  pipe open can no longer leave the server sweeping after the harness dies.
  `SIMPLE_CI_PARENT_WATCH=0` disables it. Verified end-to-end against OpenCode 2.2.5: closing the
  desktop UI stopped the server in ~2 s even though `opencode-cli serve --service` stayed alive
  and the stdin pipe never closed.

### Changed

- Harness entries launch the installed copy through
  `uv run --project <install> --no-sync python <install>/run_server.py` instead of
  hardcoding the copy's `.venv\Scripts\python.exe`. `--project` preserves the caller's
  cwd, so workspace inference is unchanged.

### Fixed

- The file watcher now uses a single recursive watch on the workspace root instead of one
  watchdog watch (and thread/handle) per directory, so large workspaces with thousands of
  `bin/`/`obj/` directories no longer exhaust threads and memory.
- The indexer and watcher honor workspace `.gitignore` files (root and nested), so ignored
  files are no longer indexed or watched. `get_status` reports the last sweep's
  `ignored_dirs` and `ignored_files`.
- Embedding requests no longer stall ~1 s each on Windows: the client rewrites loopback
  URLs to `127.0.0.1` instead of letting `localhost` resolve to the dead `::1` address
  first. The wizard probes and the managed-service readiness probe use the same helper.
- The llama.cpp compose template now sets `LLAMA_ARG_BATCH` / `LLAMA_ARG_UBATCH` (this
  build ignores the old `_SIZE` names), so the intended 2048 physical batch is applied
  instead of silently falling back to 512 and rejecting longer inputs.

### Removed

- The Cline builtin harness. The desktop client did not keep or read the wizard's settings
  file, so `setup.py` no longer offers `--harnesses cline`; use OpenCode or another harness.

