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

### ISS-2: Embedding failures are never retried for unchanged files
- **Symptom:** A file indexed while Qdrant or the embedding endpoint is down keeps `embedding_state.status='error'` and never gets vectors — semantic search silently misses it forever, because nothing retries the embed: `index_one_file` short-circuits on an unchanged sha256 and the sweep skips on `(mtime, size)` before the embed step. Reproduced 2026-10-18: a fresh workspace whose first index lost the collection-create race (`ensure_collection` 409, since fixed) or whose embed hit a busy endpoint ends up with an empty collection and no way back except deleting `.index/`.
- **Location:** `src/simple_code_indexer/indexer.py:117` (hash short-circuit), `:192` (sweep mtime/size skip), `_embed_and_store` at `:139`.
- **Suggested fix:** at startup (or each sweep) re-embed the chunks whose `embedding_state.status != 'ok'`, independent of the hash short-circuit.

### ISS-3: Two sessions in one workspace have no cross-process writer guard
- **Symptom:** `docker exec` gave one container per workspace, so the single-writer invariant (ADR-0004) held by construction. Host spawning lets two harness sessions in the same project write `.index/index.db` and the collection concurrently; SQLite WAL + `busy_timeout` prevents corruption, but the two processes interleave and duplicate work, and their `ensure_index_identity` rebinds can race.
- **Location:** `src/simple_code_indexer/server.py` `_run()` — no lock/lease is taken.
- **Suggested fix:** take an advisory lock (lock file, or a `BEGIN EXCLUSIVE` probe) at startup and warn/refuse when another server owns the workspace.

### ISS-4: An existing collection with the wrong vector size is never detected
- **Symptom:** `ensure_collection` accepts any collection that already exists, so pointing an index at a collection created with a different dimension (e.g. after changing `EMBED_DIM`, or reusing a name from another tool) yields `LAST_OK: true` while every upsert fails — fail-soft, so the workspace ends up vectorless with nothing but a warning (compounded by ISS-2, which never retries).
- **Location:** `src/simple_code_indexer/qdrant_store.py` `ensure_collection` — existence is checked, vectors config is not.
- **Suggested fix:** compare the collection's configured size with `settings.embed_dim` on first use and raise/report a clear mismatch instead of proceeding.
