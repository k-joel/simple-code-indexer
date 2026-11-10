# Issues

Ongoing issue tracker for bugs, defects and gaps found while working on this
repo — by humans or by LLM sessions.

**Rules of this file**
- **Every issue, bug or defect flagged during a session — however small, and even
  if only mentioned in passing in a summary — must be added here.**
- **Once an issue is fixed, delete its entry from this doc.** Do not mark it done
  and leave it: this file must only ever contain open issues. Operational gotchas 
  that are not defects belong in `NOTES.md`.
- Keep entries short: symptom, where it was flagged, cause (`file:line`),
  suggested fix. Add new issues with the next free `ISS-n` id.

## Open

### ISS-2 — `tests/mcp_probe.py` hangs once the server fills its stderr pipe

- **Symptom:** the probe blocks at `initialize` or at the second/third `tools/call` with no
  reply; the server log keeps writing to the file, so the process looks alive but is stuck.
- **Where flagged:** E2E install/retrieval session, 2026-11-08, driving the installed server
  (`run_server.py`) from the probe. With the child's stderr redirected to a drained stream the
  same probe prints `PROBE OK` and both lexical and semantic hits.
- **Cause:** `tests/mcp_probe.py` spawns the server with `stderr=subprocess.PIPE` and only
  reads it in `finally`; `logging_setup.configure_console()` writes INFO per indexed file and
  per tool call, so the pipe buffer fills and the server blocks inside a log call on the event
  loop thread.
- **Suggested fix:** send the child's stderr to a file (`stderr=sys.stderr` or a temp file) or
  drain it in a thread, as `mcp.client.stdio.stdio_client(errlog=...)` does. Consider keeping
  per-tool/per-file INFO off the serve thread if a harness may not drain stderr.

### ISS-4 — `get_status` reports a complete index while the FAISS vectors are still missing

- **Symptom:** `files_indexed=2, chunks_indexed=2, vector_store_ok=true` but a semantic query
  fired at that moment returned 0 hits with no error; the log showed `faiss search: ntotal=0
  k=0`. Vectors are written seconds after the rows are counted.
- **Where flagged:** E2E pre-check, 2026-11-08, with the official MCP SDK client (query fired
  ~3 ms before the first upsert).
- **Cause:** `chunks_indexed` counts `chunks` rows in SQLite; embedding happens afterwards in
  the index-writer (`embedding_state.status`). The status payload exposes neither the embedded/
  pending counts nor the FAISS `ntotal`, and `vector_store_ok` is true for an empty index.
- **Suggested fix:** add `vectors_indexed` (count of `embedding_state.status='ok'`) and
  `pending_embeddings` (or the FAISS `ntotal`) to `get_status`, and make the semantic path
  report readiness rather than silently returning `hits: []`.

### ISS-5 — semantic retrieval misses the pruning code for the virtualenv query

- **Symptom:** query "how does the indexer avoid walking into virtualenv and cache directories"
  returned 10 hits but `src/simple_code_indexer/indexer.py` (defines `iter_workspace_files` /
  the ignored-dir pruning) was not in the top 3; the top hits were
  `harnesses/__init__.py:1` (0.77), `run_server.py:1` (0.75), `harnesses/__init__.py:120`
  (0.75). The other three semantic checks passed (scores 0.73–0.78).
- **Where flagged:** OpenCode E2E run, 2026-11-08 (`artifacts/stage2-results.md`, S1); reconfirmed
  2026-11-10 (`artifacts/mcp-results.md`): `indexer.py` ranked 5th at 0.745 and the returned chunk
  was 1–78 (docstring/imports), not the pruning code at 78–88.
- **Cause:** retrieval quality, not a crash — the document prefix / chunk layout and mean
  pooling let file-walking code in the harness package and the launcher outscore the indexer.
- **Suggested fix:** re-run `tests/retrieval_bench.py` against this workspace and compare
  document-prefix and chunking variants (path-aware prefix, symbol header per chunk); check
  whether the `indexer.py` chunks for `iter_workspace_files` are being truncated.

### ISS-6 — concurrent workspaces share one embedding container with no admission control

- **Symptom:** during a full reindex of this repo, a 220-byte file hit
  `embed attempt 3/3 failed: timed out` after 46,445 ms and `embedding_state` showed
  `status=error`; a second MCP server (`VideoDeduper`) was embedding its tree through the same
  `simple-ci-embed-1` container at the same time. The chunk recovered on the next sweep.
- **Where flagged:** OpenCode E2E, 2026-11-10 (`artifacts/mcp-results.md`, problem 2).
- **Cause:** one server per workspace (ADR-0004) but one global embedding endpoint; `embed.py`
  retries without cross-process back-pressure or admission control, so concurrent bulk embeds
  saturate llama.cpp.
- **Suggested fix:** add request-level back-pressure (lower in-flight concurrency, jittered
  retry/backoff on timeout) and/or a per-endpoint limiter; document that N open workspaces
  multiply the load on the shared endpoint.
