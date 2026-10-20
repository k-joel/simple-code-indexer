# Code Index

A local MCP server that maintains a searchable index of a code workspace so an assistant can find symbols and code without reading whole files.

## Language

**Workspace**:
The single root directory whose files are indexed and watched. The MCP process working directory, unless `WORKSPACE_ROOT` says otherwise.
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

**Index directory**:
The gitignored `.simple-ci/` directory in a workspace. Holds `index.db` (plus WAL and lock
files) and, when the project uses a local config, `config.yaml`.
_Avoid_: data directory, cache folder, `.index` (the retired name)

**Config file**:
Optional `config.yaml` read at server startup: `<workspace>/.simple-ci/config.yaml` first,
then `~/.simple-ci/config.yaml`. Environment variables override both. Records the embedding
endpoint/model/dimension, the Qdrant URL, and any Docker services the server should start.
_Avoid_: settings, preferences, env file

**Managed service**:
A Docker container named in `config.yaml` (`embedding.service` / `qdrant.service`) that the
MCP server starts and waits for at boot. Fail-soft: an unavailable service degrades to
lexical-only search instead of blocking the session.
_Avoid_: sidecar, dependency, docker service (in prose)

**Setup wizard**:
The interactive flow started by `python setup.py`: installs `uv`, chooses an embedding
endpoint (existing or downloaded), provisions Qdrant, probes the vector dimension, registers
the server with detected harnesses, and writes `config.yaml`.
_Avoid_: installer, bootstrap, setup script (as a noun for the logic)

**Collection name**:
The Qdrant collection holding one workspace's vectors: `code_index_{folder_slug}_{sha256(path)[:8]}_{embed_dim}`, derived from the workspace so projects never share vectors. Overridable with `QDRANT_COLLECTION`.
_Avoid_: namespace, index name, vector store name

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
Stable Qdrant point identifier derived from the indexed file path and chunk index so upserts are idempotent.
_Avoid_: vector ID, embedding ID

**Harness**:
An MCP client host (Claude Code, Codex, OpenCode, MiMoCode, and others) that spawns the
server over stdio — with the session's project as its working directory — and loads tools
from its own config file. The *harness plugin* (below) describes where that file lives.
_Avoid_: client, IDE, agent host

**Harness plugin**:
A module in `src/simple_code_indexer/harnesses/` (or a user override in `<repo>/harnesses/`
or `<workspace>/harnesses/`) that declares one harness's detection folders, global/project
config paths, and how to merge a server entry into its file. Overrides a builtin by `NAME`.
_Avoid_: adapter, integration, connector

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
One host process per harness session hosts both the MCP stdio server and the watcher/writer. Shipped default.
_Avoid_: embedded mode, combined mode

**Sidecar topology**:
Always-on watcher/indexer service with a separate read-only MCP query process. Post-MVP option.
_Avoid_: daemon mode, split mode, background mode
