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
- `get_status` now reports `vectors_indexed` and `pending_embeddings`, and semantic
  `search_code` responses include `ready`, `pending_embeddings`, and a `message` while vectors
  are still being written. A semantic query fired during indexing now says the index is warming
  up instead of silently returning `hits: []`.

### Changed

- Chunks are now 30-line windows with 15-line overlap instead of 80-line blocks. The
  embedding model mean-pools each input, so focused windows retrieve markedly better:
  on the 42-query benchmark R@1 rose 0.667 → 0.786, R@5 0.952 → 1.000, R@10 0.976 → 1.000,
  and nDCG@10 0.746 → 0.870. The chunker profile is part of the vector identity, so the
  first start after upgrading automatically re-embeds the workspace.
- Semantic search de-duplicates overlapping chunks: it over-fetches vector hits and drops
  any hit whose line range overlaps a higher-ranked chunk from the same file, so the
  overlapping windows do not crowd the top-10 with near-duplicates.
- Harness entries launch the installed copy through
  `uv run --project <install> --no-sync python <install>/run_server.py` instead of
  hardcoding the copy's `.venv\Scripts\python.exe`. `--project` preserves the caller's
  cwd, so workspace inference is unchanged.

### Fixed

- Semantic search now finds the ignored-directory pruning logic: the query
  "how does the indexer avoid walking into virtualenv and cache directories" returns
  `indexer.py:106-135` (the `os.walk`/`dirnames[:]` loop) at rank 1. The 80-line chunk
  that mixed the whole function with unrelated code scored 0.68 against the query, while
  focused windows score 0.80; the query is now part of `tests/retrieval_queries.json`
  (`q42-walk-pruning`).
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
- `tests/mcp_probe.py` and `tests/live_watch_probe.py` no longer hang when the server fills its
  stderr pipe: the child's stderr is drained on a thread, and `PROBE_TIMEOUT` (default 180 s)
  bounds the run so a stall fails instead of blocking forever.
- Embedding requests are split into batches of at most 16 inputs with at most two in flight per
  process, and retries use full-jitter exponential backoff. A bulk reindex in one workspace no
  longer starves another workspace's request on the shared embedding endpoint; N open
  workspaces still multiply the load.
- `tests/retrieval_bench.py` no longer deletes the live workspace index: a new `--local-path DIR`
  writes `index.db` and `vectors.faiss` into `DIR` instead of `<workspace>/.simple-ci`, and a
  `--reset` that would still hit the live index prints a warning naming the file.
  `tests/bench_matrix.py` gives every run its own scratch folder under
  `artifacts/bench/<timestamp>/local/`.
- Qdrant benchmark runs are isolated too: with `--local-path DIR`, the collection is derived
  from `DIR` instead of the workspace, so `--reset` can no longer delete the collection a live
  MCP server is using. Each `bench_matrix.py` run already has its own scratch folder, so it
  also gets its own collection.

### Removed

- The Cline builtin harness. The desktop client did not keep or read the wizard's settings
  file, so `setup.py` no longer offers `--harnesses cline`; use OpenCode or another harness.

