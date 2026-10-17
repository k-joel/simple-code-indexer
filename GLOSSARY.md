# Code Index

A local MCP server that maintains a searchable index of a code workspace so an assistant can find symbols and code without reading whole files.

## Language

**Workspace**:
The single root directory whose files are indexed and watched. Mounted at `/workspace` in Docker.
_Avoid_: repo, repository, project root, codebase

**File record**:
The stored metadata for one indexed workspace file: path, language, size, content hash, mtime.
_Avoid_: document, entry, file entry

**Symbol**:
A named code definition extracted from a file (function, class, method, etc.) with kind, line range, and signature.
_Avoid_: definition, identifier, entity

**Chunk**:
A contiguous slice of file content used for full-text indexing and embedding. Bounded by start and end lines.
_Avoid_: segment, fragment, piece, passage

**Lexical index**:
SQLite + FTS5 store over file records, symbols, and chunk text. Powers BM25/keyword search.
_Avoid_: text index, full-text index, FTS index

**Semantic index**:
Qdrant vector store of chunk embeddings. Powers similarity search.
_Avoid_: vector index, embedding index

**Index** (the whole):
The combined lexical index and semantic index for one workspace.
_Avoid_: database, catalog, store

**Index on save**:
Re-indexing a file immediately when a save event is observed, independent of version-control state.
_Avoid_: live indexing, hot reload, auto-sync

**Reconciliation sweep**:
Periodic full-tree walk that compares file hashes to the index and re-indexes mismatches. Backstop for dropped watch events.
_Avoid_: full scan, hash sweep, resync, sweeper (in prose)

**Startup reconcile**:
One reconciliation sweep at process start covering changes made while the system was down.
_Avoid_: cold start index, bootstrap scan

**Point ID**:
Stable Qdrant point identifier derived from workspace path and chunk index so upserts are idempotent.
_Avoid_: vector ID, embedding ID

**Harness**:
The MCP client host (MiMoCode) that spawns the server over stdio and loads tools from `.mimocode/mimocode.json`.
_Avoid_: client, IDE, agent host

## Search

**search_code**:
MCP tool returning ranked file/line/snippet hits for a query. May be lexical, semantic, or fused.
_Avoid_: find, grep, query

**symbol_lookup**:
MCP tool resolving a symbol name to definition site (file, line, kind, signature).
_Avoid_: find_symbol, go_to_definition

**get_status**:
MCP tool reporting index health: file counts, watcher liveness, sweep age, external service reachability.
_Avoid_: health, status_check, ping

**Semantic hit**:
A search result sourced from vector similarity rather than (or in addition to) lexical matching.
_Avoid_: vector hit, embedding match

## Process

**Index writer**:
The single process (or thread) allowed to write the SQLite index and Qdrant points.
_Avoid_: indexer process, writer, mutator

**MCP server**:
The stdio process implementing initialize / tools/list / tools/call for the harness.
_Avoid_: server, MCP process, tool server

**Watcher**:
Filesystem observer that turns save/delete events into index work via a debounced queue.
_Avoid_: file monitor, listener, FS watcher

**Debounce window**:
Short delay (300–500 ms) that collapses editor temp+rename bursts into one index job per path.
_Avoid_: throttle, delay, cooldown

**All-in-one topology**:
One container process hosts both the MCP stdio server and the watcher/writer. MVP default.
_Avoid_: embedded mode, combined mode

**Sidecar topology**:
Always-on watcher/indexer service with a separate read-only MCP query process. Post-MVP option.
_Avoid_: daemon mode, split mode, background mode
