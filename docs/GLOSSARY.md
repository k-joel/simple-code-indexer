# Glossary

A searchable index of a code workspace so an assistant can find symbols and code without reading whole files.

<!--
GLOSSARY.md MAINTENANCE GUIDE (FOR AGENTS & CONTRIBUTORS)

PURPOSE & SCOPE
- Canonical ubiquitous-language reference for this repository/context, written for developers and AI agents.
- Not a user guide, API reference, changelog, or general software engineering dictionary.
- If GLOSSARY-MAP.md exists at the repo root, keep this file strictly scoped to this context; otherwise, this is the single repo glossary.

UPDATE TRIGGERS
Update this file in the same task/PR before concluding whenever you:
- Introduce a new project-specific concept, architecture role, tool, or config artifact.
- Rename, split, merge, or redefine an existing canonical term.
- Retire a component or alias that could still cause naming confusion.
- Resolve terminology ambiguity across code, tests, or docs.

INCLUSION / EXCLUSION CRITERIA
- Include: Project-specific domain/system concepts, canonical names chosen over competing synonyms, and named tools/components with distinct conceptual roles.
- Exclude: General programming concepts (timeouts, error types, utility patterns, standard protocols), transient local variables, and step-by-step implementation details.
- Litmus test: "Is this unique to this project's context, or general programming vocabulary?" Only the former belongs.

STRUCTURE & FORMATTING
- Top of file: H1 context title followed by a 1–2 sentence overview paragraph.
- Sections: Start with `## Language`. Add `## <Cluster>` H2 sections only when 3+ related terms form a natural group. Omit empty sections; do not use H3+ headings.
- Ordering & IDs: Group logically within sections; do not add numbering, dates, status tags, or custom IDs.
- Entry syntax (separate entries with one blank line; no bullets or nested lists):
  - Line 1: `**Canonical Term**:` (optional plain `(qualifier)` before `:`). Use sentence-style casing for prose concepts; preserve exact casing for literal tool/command names (e.g., `**tool_name**:`).
  - Line 2+: 1–2 sentence definition.
  - Final line: `_Avoid_: synonym1, synonym2` (append `(in prose)` or `(retired)` in parentheses when disambiguating).

QUALITY & STYLE RULES
- Be opinionated: pick one canonical term per concept and list all rejected aliases under `_Avoid_`.
- Keep definitions tight: 1–2 sentences max, present tense, declarative. Define what the concept IS, not how it works step-by-step or why it exists.
- Verify against the codebase: confirm file paths, config keys, defaults, and exact tool/symbol names in code before adding or editing an entry.
- Cross-references: refer to other glossary entries inline using their canonical spelling (italicized if helpful); avoid external URLs or line-number links.

LIFECYCLE & WORKFLOW
- Add: Place under the fitting `## <Cluster>` or `## Language`; create a new `##` section only when a cohesive cluster emerges.
- Revise: Edit definitions in place when boundaries, paths, or defaults change while keeping the 1–2 sentence cap.
- Rename / Consolidate: Replace the bold term with the new canonical name and move the old name into `_Avoid_` (optionally tagged `(retired)`).
- Retire: Remove entries for deleted concepts. If the old term still appears in legacy files or prompts, keep it in the replacement entry's `_Avoid_` list rather than keeping a dead entry.

ANTI-PATTERNS
- Adding general programming terms or standard library/protocol concepts.
- Defining two synonyms as separate entries instead of choosing one and putting the other in `_Avoid_`.
- Writing multi-paragraph explanations, tutorials, or historical rationale inside definitions.
- Leaving empty `##` sections, using bullet points inside entries, or omitting `_Avoid_` when known aliases exist.

EXAMPLE LAYOUT (4-SPACE INDENTED)
    # Billing

    Processes customer invoices and tracks payment settlement for fulfilled orders.

    ## Language

    **Invoice**:
    A request for payment issued to a customer after order fulfillment.
    _Avoid_: bill, statement, payment request

    **Ledger entry** (settled):
    An immutable accounting record created once an invoice payment clears.
    _Avoid_: transaction, receipt (in prose)

    ## Operations

    **reconcile_invoices**:
    Scheduled job that matches bank settlement records against open invoices.
    _Avoid_: sync_bills, payment_sweep
-->

---

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
Vector store of chunk embeddings. Powers similarity search. Backed by a local FAISS file
by default, or by a Qdrant collection when configured.
_Avoid_: embedding index

**Vector store**:
The configured backend for the semantic index: `faiss` (default) or `qdrant`.
_Avoid_: vector database, vector backend (in prose)

**FAISS index**:
The ID-mapped flat index persisted at `<index directory>/vectors.faiss`. Owns the vectors;
SQLite owns the chunk metadata and the label mapping.
_Avoid_: FAISS database, vector file

**Vector label**:
Monotonic FAISS id mapped to one `(path, chunk_index)` in `vector_labels`. Allocated from
`meta.vector_label_seq`, never reused after a deletion.
_Avoid_: FAISS id, vector id

**Index** (the whole):
The combined lexical index and semantic index for one workspace.
_Avoid_: database, catalog, store

**Index directory**:
The gitignored `.simple-ci/` directory in a workspace. Holds `index.db` (plus WAL and lock
files), `vectors.faiss` for the FAISS backend, `run/` for sidecar discovery, and `log/` for
role-specific logs. Configuration lives globally, not here.
_Avoid_: data directory, cache folder, `.index` (the retired name)

**Config file**:
The single global `~/.simple-ci/config.yaml` read at server startup (or the explicit
`SIMPLE_CI_CONFIG` file; `none` disables discovery). Project-local
`<workspace>/.simple-ci/config.yaml` files are legacy, migrated by the setup wizard and never
read. Environment variables override individual file values. Records the vector-store
backend, the embedding endpoint/model/dimension, either the FAISS path or the Qdrant URL, the
runtime mode, and any Docker services the server should start.
_Avoid_: settings, preferences, env file

**Managed service**:
A Docker container named in `config.yaml` (`embedding.service`, or `qdrant.service` on the
Qdrant backend) that the MCP server starts and waits for at boot. Fail-soft: an unavailable
service degrades to lexical-only search instead of blocking the session.
_Avoid_: sidecar, dependency, docker service (in prose)

**Setup wizard**:
The interactive flow started by `python setup.py`: installs `uv`, chooses an embedding
endpoint (existing or downloaded), chooses FAISS or Qdrant, probes the vector dimension,
registers the server with detected harnesses, and writes `config.yaml`.
_Avoid_: installer, bootstrap, setup script (as a noun for the logic)

**Collection name**:
The Qdrant collection holding one workspace's vectors (Qdrant backend only):
`code_index_{folder_slug}_{sha256(path)[:8]}_{embed_dim}`, with `_{embedding_fingerprint}`
appended when the fingerprint is non-empty. Derived from the workspace so projects never share
vectors. Overridable with `QDRANT_COLLECTION`.
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
Stable Qdrant point identifier derived from the indexed file path and chunk index so upserts are idempotent (Qdrant backend only).
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
The one process per workspace allowed to write the SQLite index and the vector store: the embedded server or the sidecar daemon.
_Avoid_: indexer process, writer, mutator

**Reader**:
An MCP server in sidecar mode. It queries SQLite/FAISS/Qdrant read-only and registers with the workspace daemon for lifetime and status.
_Avoid_: query process, read-only server, slave

**Session lease**:
One reader's registration with the daemon, keyed by session id. The live control connection is the primary signal; heartbeats and the server pid are backstops.
_Avoid_: client record, registration, heartbeat

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
One host process per harness session hosts both the MCP stdio server and the watcher/writer. Selected with `mode: embedded`.
_Avoid_: embedded mode, combined mode

**Sidecar topology**:
One detached writer daemon per workspace plus read-only MCP query processes. The default; the daemon exits after the last session plus `idle_grace_s`.
_Avoid_: daemon mode, split mode, background mode
