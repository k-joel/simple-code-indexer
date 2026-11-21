# Architecture

This is the live, as-built architecture reference. It describes the code as it
exists today, not planned or historical designs. When this document and the code
disagree, the code wins — update this document in the same change. Canonical
terms live in [`GLOSSARY.md`](GLOSSARY.md), rationale in
[`DECISIONS.md`](DECISIONS.md), open defects in [`ISSUES.md`](ISSUES.md),
structural debt in [`ARCH_ISSUES.md`](ARCH_ISSUES.md), and operational gotchas
in [`NOTES.md`](NOTES.md).

<!--
ARCH.md MAINTENANCE GUIDE (FOR AGENTS & CONTRIBUTORS)

PURPOSE & SCOPE
- Audience: Engineers and LLM agents needing an accurate map of the codebase.
- Purpose: Authoritative as-built reference of system structure, boundaries,
  runtime topology, data/control flows, schemas, contracts, cross-cutting
  mechanisms, extension points, deployment, and test/quality gates.
- Code-First Rule: Derive every claim directly from source, config, build, and
  CI files (package manifests, entry points, schemas, routes, tests). Never
  document theoretical patterns or unimplemented plans.

UPDATE TRIGGERS
Update docs/ARCH.md whenever a change alters any of the following:
- Process/runtime topology, concurrency model, or lifecycle ownership.
- External API, CLI, RPC, or MCP tool surface and payload contracts.
- Configuration sources, discovery precedence, or environment overrides.
- Database schemas, migrations, identity/invalidation keys, or vector/cache layouts.
- Core data, ingestion, or query/read-path pipelines.
- Cross-cutting boundaries (auth, error handling, logging, security, OS behavior).
- Plugin/extension contracts, deployment/install layout, or test/CI quality gates.
- Any spotted mismatch between this file and actual code.

INCLUSION / EXCLUSION CRITERIA
- INCLUDE:
  - Verified stack, architectural style/hybrids, and explicit In-Scope vs.
    Out-of-Scope boundaries.
  - Runtime topology, process/thread ownership, and dependency direction rules.
  - Component inventory, internal abstractions, interaction protocols, and
    concrete extension mechanisms.
  - Data architecture: domain entities, relationships, actual DDL/schemas,
    consistency/caching/invalidation rules, and filesystem layout.
  - Cross-cutting implementation patterns (auth/secrets, error/retry/fallback,
    logging/observability, input validation, config precedence).
  - Deployment/install topology and test layers + runnable quality-gate commands.
- EXCLUDE (ROUTE ELSEWHERE OR OMIT):
  - Why a choice was made / alternatives considered -> DECISIONS.md
  - Functional bugs or regressions -> ISSUES.md
  - Structural debt, layer violations, or smells -> ARCH_ISSUES.md
  - Operational quirks or debugging tips -> NOTES.md
  - Standalone term definitions -> GLOSSARY.md
  - Speculative roadmaps, exhaustive line-by-line code dumps, or boilerplate
    sections for technology stacks not detected in the codebase.

STRUCTURE & FORMATTING
- Top-level sections: Numbered H2 headings (`1. Purpose and scope` .. `13. ...`)
  separated by `---` horizontal rules on their own lines.
- Subsections: Numbered H3 headings (`2.1 ...`, `6.1 ...`). Omit unused optional
  subsections; never leave empty "TBD" sections.
- Canonical section order (adapt domain-specific titles to the codebase):
  1. Purpose and scope
  2. Runtime topology
  3. Primary write / ingestion data flow
  4. Primary read / query paths
  5. Domain model
  6. Data architecture
  7. Component design
  8. External interface / API contracts
  9. Cross-cutting concerns
  10. Extension points
  11. Install and launch architecture
  12. Testing architecture
  13. Maintaining this document
- Tables: Use compact Markdown tables for inventories, configs, and schemas.
- Diagrams: Use fenced ASCII diagrams with Unicode arrows (`→`, `──►`, `▼`).
  Never use `-->` inside HTML comments or diagrams that could break parsers.
- Code blocks: Always specify a language tag (`sql`, `json`, `bash`, `text`).

QUALITY & STYLE RULES
- Tense & Tone: Present tense, declarative, terse, and high-signal. No filler.
- Verification: Inspect actual files before writing; cite exact module paths,
  symbol names, config keys, and CLI commands in backticks.
- Consistency: Match canonical vocabulary in GLOSSARY.md and link ADRs inline
  (e.g., `(ADR-005)` or `[ADR-015](DECISIONS.md#...)`) without duplicating rationale.
- Privacy/Safety: Never embed real secrets, tokens, or personal local paths in
  examples; use placeholders (`<workspace>`, `~/.app/`).

LIFECYCLE & WORKFLOW
1. Inspect diff/codebase: Detect active stack, entry points, schemas, and configs.
2. Add: Insert new components/endpoints/tables into the matching numbered section.
3. Modify: Update flows, config tables, and schemas in place to match the code.
4. Retire: Delete removed components, flags, and endpoints from ARCH.md (history
   belongs in git and DECISIONS.md, not stale sections here).
5. Reconcile: If an existing section contradicts the code, fix ARCH.md immediately.

ANTI-PATTERNS
- Documenting planned features, aspirational clean layers, or unverified memory.
- Mixing ADRs, bug lists, or tech-debt commentary into ARCH.md.
- Leaving stale DDL, obsolete CLI flags, or dead module names after refactors.
- Including framework sections (e.g., React/Java/.NET) not present in the repo.
- Using vague qualifiers ("probably", "usually", "various helpers").

EXAMPLE LAYOUT (4-SPACE INDENTED)

    ---

    ## 1. Purpose and scope

    | In scope | Out of scope |
    |---|---|
    | `<core capability>` | `<explicit boundary>` |

    ---

    ## 2. Runtime topology

    ### 2.1 Default mode (`mode: <name>`)

    ```text
    caller ──► <entry-point> ──► <worker/store>
    ```

    | Process / thread | Role | Owns |
    |---|---|---|
    | `<process>` | `<role>` | `<resources>` |

    ---

    ## 3. <Write / ingestion> data flow

    ```text
    input event → filter/debounce → bounded queue → <unit_of_work>() → store
    ```

    ### 3.1 Reconciliation backstops

    1. **Startup reconcile** — `<initial catch-up behavior>`.

    ---

    ## 4. <Read / query> paths

    ### 4.1 <Query path name>

    1. `<Step 1: parse/validate>`
    2. `<Step 2: query store and rank/merge>`

    ---

    ## 5. Domain model

    | Entity | Identity | Key attributes |
    |---|---|---|
    | **<Entity>** | `<unique key>` | `<core fields>` |

    Relationships: `<EntityA> 1—* <EntityB>`.

    ---

    ## 6. Data architecture

    ### 6.1 Primary store (`<path-or-engine>`)

    ```sql
    CREATE TABLE <entity> (id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE);
    ```

    ### 6.2 Secondary / index store

    - `<Engine>`: `<key structure, consistency, and identity binding rules>`.

    ### 6.3 Filesystem layout

    ```text
    <root>/
      <data-dir>/
        <db-file>
        log/<role>.log
    ```

    ---

    ## 7. Component design

    | Module | Responsibility |
    |---|---|
    | `src/<pkg>/<mod>.py` | `<single-sentence role>` |

    ### 7.1 Configuration

    | Config key | Environment | Default |
    |---|---|---|
    | `<section.key>` | `<ENV_VAR>` | `<default>` |

    ---

    ## 8. <Interface / API> surface

    ### 8.1 `<operation_name>`

    | Input | Type | Default | Notes |
    |---|---|---|---|
    | `<param>` | string | required | `<constraint>` |

    ```json
    {"status": "ok", "results": []}
    ```

    ---

    ## 9. Cross-cutting concerns

    ### 9.1 Error handling
    `<Exception hierarchy and fail-soft vs. fatal boundaries.>`

    ### 9.2 Concurrency and consistency
    `<Locks, leases, read-only isolation, and ordering guarantees.>`

    ### 9.3 Logging and observability
    `<Log destinations, levels, redaction rules, and status signals.>`

    ### 9.4 Security boundaries
    `<Auth tokens, file permissions, and non-sandbox boundaries.>`

    ### 9.5 Platform behavior
    `<OS-specific watchers, locks, sockets/pipes, or process flags.>`

    ---

    ## 10. Extension points

    | Extension | Mechanism | Rules |
    |---|---|---|
    | `<plugin type>` | `<discovery path>` | `<override/validation rules>` |

    ---

    ## 11. Install and launch architecture

    ```text
    source ──<installer>──► runtime copy ──► <launcher> ──► entrypoint
    ```

    ---

    ## 12. Testing architecture

    ### 12.1 Test isolation
    `<Env overrides and fixtures isolating tests from user/global state.>`

    ### 12.2 Test layers

    | Layer | What it covers |
    |---|---|
    | Unit | `<isolated modules>` |
    | Integration | `<end-to-end flows with real/stubbed boundaries>` |

    ### 12.3 Quality gates

    ```bash
    <lint / typecheck / test commands>
    ```

    ---

    ## 13. Maintaining this document

    Update triggers and companion-doc split (`ARCH.md`, `DECISIONS.md`,
    `ISSUES.md`, `ARCH_ISSUES.md`, `NOTES.md`, `GLOSSARY.md`).
-->

---

## 1. Purpose and scope

The system answers three questions about one local workspace:

- **Lexical search** — where does this text or identifier appear?
- **Semantic search** — which chunks are closest in embedding space?
- **Symbol lookup** — where is this symbol defined?

Architectural boundaries:

| In scope | Out of scope |
|---|---|
| One workspace per process: `WORKSPACE_ROOT`, then the client's MCP roots, then the harness-published workspace, then cwd (ADR-018) | Multi-repo registry, path sandbox, worktree identity |
| Index-on-save from working-tree bytes | Git readiness, commit gating, provenance |
| SQLite + FTS5 lexical index | Staged generations, quarantine trees |
| Direct chunk embeddings; sqlite-vec default, FAISS and Qdrant opt-in | LLM chunk summaries before embedding |
| Three MCP tools: `search_code`, `symbol_lookup`, `get_status` | Admin/enterprise gateway, auth service, metrics stack |
| One writer per workspace; readers are read-only | Multi-writer coordination |

Each boundary is a recorded decision; see
[`DECISIONS.md`](DECISIONS.md). The tool surface deliberately omits
`outputSchema`, `capabilities.tasks`, and per-tool `execution.taskSupport`
because the harness rejects them (ADR-005).

---

## 2. Runtime topology

### 2.1 Sidecar (default, `mode: sidecar`)

```
harness process(es)
  │  stdio JSON-RPC (newline-delimited)
  ▼
MCP server — reader role
  ├─ tool handlers: search_code | symbol_lookup | get_status
  │    read-only SQLite (mode=ro), read-only sqlite-vec/FAISS/Qdrant search
  ├─ ReaderSession: attach/register/heartbeat/status over a local control channel
  └─ ParentWatchdog: exits when the harness process that owns the session dies

sidecar daemon — writer role (one per workspace, detached)
  └─ WriterRuntime
       ├─ WorkspaceLock       <index_db>.lock (OS advisory lease)
       ├─ watcher             one recursive Observer thread
       ├─ writer thread       queue consumer; sole SQLite/vector writer
       ├─ sweep timer         optional reconciliation; off by default
       ├─ heartbeat thread    publishes meta.writer_pid / writer_heartbeat
       └─ managed services    optional Docker containers, started fail-soft
```

Every harness still spawns its own MCP server, but only the daemon writes. The
first reader that cannot reach a daemon spawns one under
`<index dir>/run/daemon.spawn.lock`, then publishes
`<index dir>/run/daemon.spawn.json` with the child pid before releasing the lock;
peers that see a live claim wait for that daemon instead of spawning a duplicate.
The daemon takes the writer lease **before** publishing
`<index dir>/run/daemon.json`, so a discovered endpoint always points at a live
writer. The control channel is stdlib `multiprocessing.connection`
(Windows named pipe or POSIX AF_UNIX) with the token in `daemon.token` as the
`authkey`; message bodies are JSON text, never pickle.

Lifetime:

- A live control connection is the primary session lease.
- Readers heartbeat every `heartbeat_s` (default 5 s); the daemon reaps a
  session after three missed intervals or when the registered server pid dies.
- After the last session plus `idle_grace_s` (default 60 s), the daemon stops
  accepting, clears its discovery files while it still holds the writer lease,
  flushes vectors, releases the lease, and exits.
- A reader exits with its stdio session and when its harness process disappears.
  The daemon never watches the harness.

### 2.2 Embedded (escape hatch, `mode: embedded`)

One process hosts both the MCP stdio server and `WriterRuntime`. It takes the
writer lease and therefore owns the watcher, writer thread, sweep timer, vector
stores, and managed services. A second session for the same workspace cannot
serve (it exits on `WorkspaceBusy`). Sidecar is the default, not an auto-fallback:
a daemon that cannot start leaves readers serving stale read-only data rather
than silently reverting to a competing embedded writer.

### 2.3 Process and thread inventory

| Process / thread | Role | Owns |
|---|---|---|
| MCP server (one per harness session) | reader | stdio JSON-RPC, read-only queries, session registration, harness watchdog |
| Sidecar daemon (one per workspace) | writer | writer lease, watcher, writer queue/thread, sweep timer, heartbeat, vector stores, managed services |
| Embedded server (one per workspace) | writer + reader | the same writer components plus the stdio server |
| `watcher` thread | writer | one recursive filesystem watch |
| `index-writer` thread | writer | queue consumption, SQLite transactions, embeddings, vector upserts |
| `sweep-timer` thread | writer | periodic or dormant reconciliation requests |
| `writer-heartbeat` thread | writer | `meta` liveness rows for readers |
| `grammar-prefetch` thread | either | best-effort tree-sitter grammar loading |
| `service-probe` thread | writer | vector-store / embedding readiness probe |

---

## 3. Indexing data flow

```
file saved in the workspace
  → native filesystem event
  → one recursive watchdog observer
  → filter: allowlist, temp names, IGNORE_DIRS, .gitignore, active log file
  → per-path debounce (debounce_ms, default 400 ms)
  → bounded queue (max 500; full queue drops work and relies on the next sweep)
  → index_one_file(path):
       read bytes; sha256
       if sha256 == stored hash → skipped_unchanged
       parse symbols (tree-sitter plugin or regex fallback)
       chunk source into overlapping windows
       one SQLite transaction:
         UPSERT files
         DELETE + INSERT symbols for the file
         DELETE + INSERT chunks for the file (FTS triggers keep chunks_fts aligned)
       embed chunk texts (batched) → upsert vectors
       record embedding_state per chunk (ok | error)
  → on delete/move: DELETE file rows (cascade) + delete vectors by path
```

The writer queue also carries a sweep sentinel and tombstones:

- `WorkItem(path, deleted=False)` → index the path.
- `WorkItem(path, deleted=True)` → remove the path from SQLite and the vector store.
- `SWEEP_REQUEST` → run a reconciliation sweep in the writer thread.

When the queue drains, the writer flushes the vector store at most once per
`FLUSH_DEBOUNCE_S` (30 s). For sqlite-vec and Qdrant that is a WAL checkpoint
respectively a no-op; FAISS persists its in-memory index here. A sweep flushes at
its end regardless. Queued work left behind at shutdown is recovered by the next
startup reconcile.

### 3.1 Reconciliation backstops

1. **Startup reconcile** — `WriterRuntime.start()` enqueues one sweep
   unconditionally. It builds the first index and drops rows for files deleted
   while the system was down.
2. **Periodic sweep** — opt-in via `sweep_seconds > 0`. The workspace is walked
   with directory pruning; a file is re-indexed when `(mtime, size)` differs,
   with the sha256 short circuit inside `index_one_file` as the final guard.
   Rows whose files disappeared are removed, and their vectors are deleted.
   The interval doubles while the workspace is idle (no queued watcher events or
   an empty sweep) up to `SWEEP_BACKOFF_MAX_S` (600 s), and resets on activity.
3. **Dormant embedding sweeps** — with sweeps disabled, the timer polls
   `pending_embeddings` every `DORMANT_POLL_S` (60 s). While chunks are pending
   it temporarily requests sweeps, backs off while the count does not move, and
   stops at zero.
4. **Re-embed pass** — every sweep (including startup) first re-embeds chunks
   whose `embedding_state.status != 'ok'` or that have no row. It stops at the
   first failing file, so an unavailable embedding endpoint costs one retry per
   sweep rather than one per file.

Never index in the observer callback; never block the observer thread. The
watcher is the primary path, and the sweeps are backstops.

---

## 4. Search paths

### 4.1 Lexical

`db.fts_search` tokenizes the query with `\w+`, builds an OR expression of
quoted tokens, and runs BM25 over `chunks_fts`, joining `chunks` and `files` for
the path and line span. The snippet comes from FTS5. Results are ordered by
`bm25` rank and capped at `limit`.

### 4.2 Semantic

1. Read `embedding_counts`; `ready` is true only when no chunk is pending.
2. Embed the query with the configured query prompt.
3. Search the configured vector store with an over-fetch of `limit * 3`.
4. Map hits back to chunk metadata; orphan ids are dropped (a delete raced).
5. Drop a hit whose line span overlaps a higher-ranked hit from the same file —
   adjacent chunks overlap 50%, so without this the top results collapse into
   near-duplicates.
6. Return at most `limit` hits. While vectors are still pending, the response
   carries `ready: false`, `pending_embeddings`, and a warming-up message; empty
   hits then mean "not ready yet", not "no match". An embedding or vector-store
   failure returns `ready: false` with a `semantic search unavailable: …` message
   instead of raising.

### 4.3 Symbol lookup

Exact match on `symbols.name` first; when none, a prefix match (`LIKE 'name%'`
with escaped wildcards). Results join `files` for path and language and are
ordered by path then line.

---

## 5. Domain model

| Entity | Identity | Key attributes |
|---|---|---|
| **Workspace** | one root path per process | `WORKSPACE_ROOT` > MCP roots > harness-published workspace > cwd; indexes under `<workspace>/.simple-ci/` |
| **File record** | workspace-relative POSIX `path` (unique) | language, size, sha256, mtime, indexed_at |
| **Symbol** | (`file_id`, name, line) | kind, line_end, signature |
| **Chunk** | (`file_id`, `chunk_index`) | start_line, end_line, content |
| **Vector label** | monotonic integer in `vector_labels` | (`path`, `chunk_index`); never reused; `dirty` is FAISS-only |
| **Qdrant point ID** | `uuid5(namespace, "path:chunk_index")` | payload `{path, chunk_index}` |
| **Embedding state** | `chunk_id` | vector id (label, or Qdrant point id), status `ok`/`error`/`missing`, updated_at |
| **Writer** | process holding `<index_db>.lock` | embedded server or sidecar daemon |
| **Reader** | MCP server process | session id, server pid, harness pid/name |
| **Session lease** | session id | live control connection, last heartbeat, registered process |
| **Managed service** | (`config.yaml` service block) | container name, optional compose file/service, startup timeout |
| **Language catalog entry** | `name` (the pack grammar name) | grammar, extensions, filenames, symbol node map, optional extractor |
| **Harness plugin** | `NAME` | detection dirs/binaries, config paths, format, entry/render/remove |

Relationships: File 1—* Symbol; File 1—* Chunk; Chunk 1—1 `embedding_state`;
(`path`, `chunk_index`) 1—1 `vector_labels`; a vector store maps labels/point ids
back to chunk identity.

---

## 6. Data architecture

### 6.1 SQLite (`$WORKSPACE_ROOT/.simple-ci/index.db`)

WAL mode, `busy_timeout=5000`, `foreign_keys=ON`, single writer. The writer
holds the OS advisory lease on `<index_db>.lock`; readers never take it and open
`mode=ro` connections.

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE files (
  id          INTEGER PRIMARY KEY,
  path        TEXT NOT NULL UNIQUE,
  language    TEXT NOT NULL,
  size        INTEGER NOT NULL,
  sha256      TEXT NOT NULL,
  mtime       REAL NOT NULL,
  indexed_at  TEXT NOT NULL
);

CREATE TABLE symbols (
  id          INTEGER PRIMARY KEY,
  file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL,
  line        INTEGER NOT NULL,
  line_end    INTEGER,
  signature   TEXT
);
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_file ON symbols(file_id);

CREATE TABLE chunks (
  id          INTEGER PRIMARY KEY,
  file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  start_line  INTEGER NOT NULL,
  end_line    INTEGER NOT NULL,
  content     TEXT NOT NULL,
  UNIQUE(file_id, chunk_index)
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  content,
  content='chunks',
  content_rowid='id',
  tokenize='unicode61'
);

-- External-content FTS5 protocol: chunks_fts always mirrors chunks.
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content)
  VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content)
  VALUES ('delete', old.id, old.content);
  INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE embedding_state (
  chunk_id   INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  vector_id  TEXT NOT NULL,
  status     TEXT NOT NULL,             -- ok | error | missing
  updated_at TEXT NOT NULL
);

CREATE TABLE vector_labels (
  label       INTEGER PRIMARY KEY,
  path        TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  dirty       INTEGER NOT NULL DEFAULT 1,
  UNIQUE(path, chunk_index)
);

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

Per-file update protocol: in one transaction, delete the file's symbols and
chunks, insert the fresh rows, and upsert the `files` row. The FTS triggers keep
lexical content aligned; the writer never manually deletes FTS rows.

`embedding_state` is observability and retry state, not the source of truth for
chunk existence. A chunk counts as embedded only when a row with `status='ok'`
exists; absent, `error`, and `missing` all count as pending.

`vector_labels` is the stable label map kept in SQLite: it maps a monotonic
integer label to `(path, chunk_index)` and records whether a FAISS vector may not
have been persisted yet (`dirty`). Labels are allocated from
`meta.vector_label_seq` and are **never reused**; recycling an id could attach an
old vector left by a crash to a new chunk. sqlite-vec uses the same label as its
`vec_chunks.rowid`; Qdrant derives its own point ids and ignores the table.

`meta` keys written by the current code:

| Key | Meaning |
|---|---|
| `vector_backend` | `sqlite-vec`, `faiss` or `qdrant` |
| `qdrant_url`, `qdrant_collection` | Qdrant binding |
| `faiss_path`, `faiss_dim` | FAISS binding; `faiss_dim` is `<dim>:<fingerprint>` when a fingerprint exists |
| `sqlite_vec_store`, `sqlite_vec_dim` | sqlite-vec binding; `sqlite_vec_store` is the constant `sqlite-vec`, the dim slot carries `<dim>:<fingerprint>` |
| `vector_label_seq` | highest label ever allocated |
| `writer_pid`, `writer_heartbeat`, `writer_started_at` | writer liveness for readers without a daemon RPC |

`ensure_schema` also migrates the legacy `embedding_state.qdrant_point_id` column
to `vector_id` with a guarded `ALTER TABLE ... RENAME COLUMN`.

#### Identity binding and invalidation

`db.ensure_index_identity` binds one database to one vector store:

- Qdrant identity: `(qdrant_url, qdrant_collection)`.
- FAISS identity: `(faiss_path, "<dim>:<embed_fingerprint>")`.
- sqlite-vec identity: `("sqlite-vec", "<dim>:<embed_fingerprint>")` — the path is
  deliberately absent because the vectors live inside this same database, so
  moving or renaming a workspace must not force a re-embed.

If the binding differs from what `meta` records, every `files` row and every
`vector_labels` row is deleted, so the startup reconcile re-indexes and
re-embeds the workspace. Vectors from another store are never migrated. A legacy
database with Qdrant keys and no `vector_backend` is treated as Qdrant-bound.
On a FAISS identity change the runtime also replaces `vectors.faiss` with an
empty index immediately; otherwise the stale file could survive and collide with
the restarted label sequence. sqlite-vec drops and recreates `vec_chunks` on
reset, and the router drops a leftover `vec_chunks` table whenever another
backend becomes active.

### 6.2 Vector stores

`vector_store.py` is a registry-backed router, not a branch table. Every backend
module exposes the same module-level function set (`STORE_CONTRACT`):

`describe`, `identity`, `ensure_ready`, `reset`, `upsert_chunks`,
`delete_by_path`, `search`, `search_readonly`, `reconcile`, `flush`, `last_ok`,
`vector_index_age_s`.

`_STORES` maps a backend name to a lazy module loader, so a sqlite-vec workspace
never imports faiss or qdrant-client and vice versa. Adding a backend means one
module plus one registry entry; `tests/test_vector_store.py` asserts every
registered module still implements the whole contract. `vector_util.py` supplies
the shared width validation and L2 normalisation, so both local stores accept the
same vectors and report the same cosine score.

**sqlite-vec (default)**

- Storage: a `vec_chunks` virtual table inside `<index dir>/index.db`, created by
  the store (never by `ensure_schema`), so a file update and its vectors commit in
  one transaction.
  `vec0(embedding float[<embed_dim>] distance_metric=cosine, chunk_size=<n>)`;
  `rowid` is the `vector_labels.label`.
- Vectors are L2-normalised on write and on query; sqlite-vec returns cosine
  *distance*, so the score is `1 - distance` (same range as the other backends).
- `upsert_chunks` allocates/reuses labels, deletes stale labels and their vec
  rows, then updates each row (`INSERT OR REPLACE` does not exist on vec0 0.1.9,
  so an update that changes nothing falls back to an insert) — all in one
  transaction.
- `chunk_size` and the dimension are fixed in the DDL: a mismatch drops and
  recreates the table and marks every `ok` embedding `missing`, so the next sweep
  re-embeds without re-parsing.
- Query connections (writer and reader) load the extension and set
  `PRAGMA mmap_size` / `PRAGMA cache_size`; read-only search opens `mode=ro` and
  never creates the table — a missing table means "semantic index not ready".
- `flush` is a `wal_checkpoint(PASSIVE)`; `reconcile` only heals a table that had
  to be recreated; `vector_index_age_s` is the age of the newest `ok` embedding.
- `identity` ignores the workspace path; see the invalidation notes above.

**FAISS (second option)**

- File: `<index dir>/vectors.faiss`; `faiss.path` / `FAISS_PATH` overrides.
- Structure: `IndexIDMap2(IndexFlatIP(embed_dim))`.
- Vectors are L2-normalised before insertion and query, so inner product equals
  cosine similarity in `[-1, 1]`.
- Upsert allocates labels, marks them dirty, removes any existing labels for the
  file, and appends the new vectors — one lock covers both the index and the
  `vector_labels` mapping.
- `flush` writes `vectors.faiss.tmp` and atomically replaces the file, then
  clears dirty flags. A crash between write and clear only causes a harmless
  re-embed.
- `reset` writes an empty index (and unlinks the file if the write fails).
- `reconcile` flags dirty labels back to `missing` so the next re-embed pass
  retries them.
- Read-only search reloads the published file when `(mtime_ns, size)` changes;
  a missing file means "semantic index not ready", never "create it".
- Memory and query cost scale with the number of vectors; `IndexFlatIP` is a
  linear scan, acceptable for the intended workspace sizes.

**Qdrant (third option)**

- URL: `qdrant.url` / `QDRANT_URL`, default `http://localhost:6333`.
- Collection: `qdrant.collection` / `QDRANT_COLLECTION`, otherwise derived as
  `code_index_{slug}_{sha256(normalized_path)[:8]}_{embed_dim}` with
  `_{embed_fingerprint}` appended when the fingerprint is non-empty. `slug` is
  the folder name lowercased, non-alphanumerics replaced by `-`, capped at 32
  characters, or `root` when empty. The path input is resolved, lowercased, and
  forward-slashed.
- Distance `Cosine`; one unnamed vector of size `embed_dim`.
- Point id: `uuid5(fixed_namespace, f"{path}:{chunk_index}")`, stable across
  re-index and processes.
- Payload: `{"path": str, "chunk_index": int}`.
- Delete: filter on `path`.
- `ensure_collection` is serialized, creation-race tolerant, and validates an
  existing collection's vector size against `embed_dim` (a mismatch or named
  vectors raises instead of silently producing a vectorless workspace).
- Readers call `validate_collection` / `search_readonly`, which never create or
  mutate the collection.

### 6.3 Filesystem layout

Global state (one per user):

```
~/.simple-ci/
  config.yaml                 # the only config file
  docker/docker-compose.yml   # generated managed-service compose
  docker/gpu_init.sh          # optional NVIDIA runtime bootstrap
  model/                      # downloaded GGUF files
  qdrant_storage/             # Qdrant data when that backend is managed
```

Per-user install — the uv tool environment harness entries launch
([ADR-019](DECISIONS.md#adr-019-pypi-distribution-uv-tool-install-replaces-the-git-copy-install)):

```
%APPDATA%/uv/tools/simple-code-indexer/                   # Windows
~/Library/Application Support/uv/tools/simple-code-indexer/   # macOS
$XDG_DATA_HOME/uv/tools/simple-code-indexer/             # Linux, else ~/.local/share/uv/tools/...
  Scripts/pythonw.exe        # Windows: windowless, spawnable by a GUI harness
  bin/python                 # POSIX
  Lib/site-packages/simple_code_indexer/...   # installed from the wheel
```

`uv tool dir` reports the base directory; never hardcode it.

The install spec is `install.install_spec()`: a source checkout is installed **by
path**, so a local install works before the project is published; only a wheel
install — where no checkout exists — pins `simple-code-indexer==<version>`. The
path is handed to `uv tool install` with or without `--editable`: editable (the
default) links the working tree, a wheel build (`--wheel`) installs a copy. Both
land in the same environment root, so the harness entry is identical and only
`uv-receipt.toml` records which flavour is live.

Per workspace (gitignore `.simple-ci/`):

```
<workspace>/.simple-ci/
  index.db                     # SQLite (plus -wal/-shm); holds vec_chunks by default
  index.db.lock                # writer lease
  vectors.faiss                # FAISS backend only
  run/
    daemon.json                # published endpoint + pid (protocol versioned)
    daemon.token               # control-channel auth token (0600)
    daemon.spawn.lock          # serializes first daemon spawns
    daemon.spawn.json          # in-flight spawn claim (child pid + timestamp)
  log/
    embed.log                  # mode: embedded
    writer.log                 # sidecar daemon
    reader.log                 # sidecar readers (shared)
```

There is deliberately no workspace `config.yaml`: project-local configs are
legacy, migrated into the global file by the wizard, and never read by the
server. The index and vector files stay per workspace; only configuration is
global.

---

## 7. Component design

Package: `src/simple_code_indexer/` (import `simple_code_indexer`).

| Module | Responsibility |
|---|---|
| `__init__.py` | `main()` alias to the server entry point |
| `config.py` | `Settings` resolution: YAML values, env overrides, derived identity helpers |
| `configfile.py` | global config discovery/read/write, YAML validation, deep merge (migration/tests) |
| `errors.py` | `IndexerError` hierarchy |
| `models.py` | `FileRecord`, `Symbol`, `Chunk`, `SearchHit`, `VectorHit` |
| `db.py` | SQLite schema/migrations, FTS queries, symbols, embedding state, vector labels, `meta` |
| `parse.py` | language detection, symbol extraction, overlapping chunker, lazy parsers |
| `tsutil.py` | tree-sitter node helpers (`walk`/`text`/`signature`) shared by `parse` and the extractors |
| `registry.py` | indexes the language catalog: detection, allowlists, grammar prefetch |
| `embed.py` | OpenAI-compatible embeddings client: prompts, batching, retries, dimension checks |
| `model_prompts.py` | documented query/document prefixes per supported model family |
| `vector_store.py` | registry-backed backend router and identity description |
| `vector_util.py` | shared vector width validation and L2 normalisation |
| `sqlite_vec_store.py` | `vec_chunks` table lifecycle, transactional upsert/delete/search, read-only search |
| `faiss_store.py` | FAISS index lifecycle, labels, dirty tracking, read-only search |
| `qdrant_store.py` | collection lifecycle, upsert/delete/search, read-only validation |
| `ignore.py` | layered workspace `.gitignore` resolution |
| `indexer.py` | `index_one_file`, queue consumer, re-embed pass, reconciliation sweep |
| `watcher.py` | one recursive observer, per-path debounce, event filtering |
| `runtime.py` | `WriterRuntime`: lease, writer thread, watcher, sweeps, heartbeat, services |
| `workspace_lock.py` | cross-platform advisory file lease |
| `parent_watch.py` | harness process discovery (launch chain, raw ancestor walk, ancestor install dirs) and liveness watchdog |
| `mcp_roots.py` | bounded `roots/list` probe used as the second workspace source |
| `services.py` | managed Docker container startup and readiness probes |
| `cli.py` | console entry point: `setup` / `serve` / `uninstall` / `status` / `version` subcommands |
| `logging_setup.py` | stderr/file logging, rotation, excepthooks, active log path |
| `server.py` | MCP stdio server, deferred workspace binding (`ServerState`), tool handlers, status assembly |
| `sidecar/` | daemon, reader session, JSON control protocol, discovery paths, lease registry |
| `languages/` | generated `catalog.py`, `LanguageSpec`, specialized extractors |
| `harnesses/` | MCP-client plugins: install entries + runtime workspace hooks |
| `setup_wizard/` | prompts, probes, GPU detection, compose/model provisioning, install/uninstall |

Repo-root entry points:

- `setup.py` — clone-time bootstrap only. Not a setuptools script; it finds or
  installs `uv`, syncs the checkout (an editable install), and hands over to
  `simple_code_indexer.setup_wizard` while preserving the caller's cwd. A
  published install never needs it: `uvx simple-code-indexer setup` is the
  supported entry point.
- `tools/release.py` — version bump, changelog cut, tag, push, plus the
  `--verify-tag` / `--check-pypi` guards the release workflow runs.

### 7.1 Configuration

`load_settings()` reads one global YAML file and applies environment overrides.
Precedence is **environment variable > global YAML value > default**. Discovery:

1. `SIMPLE_CI_CONFIG` — one explicit file. `none`/`off` disables discovery
   (the test suite uses this). A missing explicit file logs a warning and yields
   no config.
2. Otherwise `~/.simple-ci/config.yaml` when it exists.
3. Never `<workspace>/.simple-ci/config.yaml`. The wizard merges a legacy local
   file into the global one and deletes it.

`Settings.config_sources` therefore has 0 or 1 entries, and
`get_status.config_files` reflects that.

| YAML key | Environment | Default |
|---|---|---|
| `vector_store` | `VECTOR_STORE` | `sqlite-vec` (`qdrant` when a non-empty `qdrant:` section exists and no key is set) |
| `qdrant.url` | `QDRANT_URL` | `http://localhost:6333` |
| `qdrant.collection` | `QDRANT_COLLECTION` | derived per workspace |
| `faiss.path` | `FAISS_PATH` | `<index dir>/vectors.faiss` |
| `sqlite_vec.chunk_size` | `SQLITE_VEC_CHUNK_SIZE` | `64` |
| `sqlite_vec.mmap_size` | `SQLITE_VEC_MMAP_SIZE` | `1073741824` (mapping limit, not preallocation) |
| `sqlite_vec.cache_size` | `SQLITE_VEC_CACHE_SIZE` | `-262144` (KiB; negative means KiB) |
| `embedding.base_url` | `EMBED_BASE_URL` | `http://localhost:8080` |
| `embedding.model` | `EMBED_MODEL` | `Qwen3-Embedding-4B-Q6_K` |
| `embedding.dim` | `EMBED_DIM` | `2560` |
| `embedding.api_key` | `EMBED_API_KEY` | unset |
| `embedding.timeout_s` | `EMBED_TIMEOUT_S` | `15` |
| `embedding.query_prefix` / `document_prefix` | `EMBED_QUERY_PREFIX` / `EMBED_DOCUMENT_PREFIX` | model default; empty disables |
| `embedding.service` / `qdrant.service` | — | unset (no managed container) |
| `sweep_seconds` | `SWEEP_SECONDS` | `0` (periodic sweep off) |
| `debounce_ms` | `DEBOUNCE_MS` | `400` |
| `mode` | `SIMPLE_CI_MODE` | `sidecar` |
| `idle_grace_s` | `IDLE_GRACE_S` | `60` |
| `heartbeat_s` | `HEARTBEAT_S` | `5` |
| `log.level` | `LOG_LEVEL` | `debug` (file only) |
| `log.max_bytes` / `log.backups` | `LOG_MAX_BYTES` / `LOG_BACKUPS` | `5000000` / `3` |
| — | `WORKSPACE_ROOT` | process cwd |
| — | `INDEX_DB` | `$WORKSPACE_ROOT/.simple-ci/index.db` |

Prompt resolution is environment > explicit file value > model default. Empty
string disables that side. Templates are validated at load time for their
placeholders (`{query}` or `{title}`/`{content}`); a bad placeholder raises
`ConfigError`. `embedding_fingerprint` is
`sha256(document_prefix + "\0" + CHUNKER_VERSION)[:8]` — it changes only when
stored vectors change, so query-prompt edits do not force a re-embed.

`Registry` supplies `allowed_exts` (catalog extensions, data formats excluded) and
`allowed_filenames` (exact names such as `Dockerfile`). `ignore_dirs` is fixed:
`.git`, `.index`, `.simple-ci`, `__pycache__`, `.venv`, `node_modules`.

An inferred workspace that cannot be a project root is refused with a
`ConfigError`: the user's home directory, or the installation directory of a
live ancestor process (`config._implausible_reason`, using
`parent_watch.ancestor_install_dirs`). An explicit `WORKSPACE_ROOT` or a
client-published MCP root still opts in.

Workspace resolution order (`config.resolve_workspace_root`, ADR-018):

1. `WORKSPACE_ROOT` — explicit escape hatch.
2. **MCP `roots/list`** — the connected client's own folder list, first
   existing `file:` root. A server-initiated request, so it is asked only after
   the handshake (`notifications/initialized`, with the first `tools/*` call as
   a fallback), bounded by `SIMPLE_CI_ROOTS_TIMEOUT_S` (default 1 s, `0`
   disables), gated on the client declaring `roots` and on the connection having
   a back-channel (the 2026-era protocol forbids server-initiated requests).
3. **Harness-published workspace** — `harnesses.discover_workspace` asks the
   plugin named by the entry's `SIMPLE_CI_HARNESS` env value. Today only
   `commandcode` implements it (its `~/.commandcode/ide/*.json` window files,
   matched by live ancestry). When the cwd is implausible (home or an ancestor's
   install directory) an entry without the marker — installed before the marker
   existed — asks **every** plugin that declares a resolver instead, so shipping
   a new version of the package is enough and no setup re-run is needed.
4. Process cwd — only when it is plausible; otherwise the `ConfigError` above
   names the directory and the sources that were tried.

`Settings.workspace_source` records `env` / `roots` / `harness:<name>` / `cwd`
and is surfaced as `get_status.workspace_source` and in the startup banner.
Because roots needs a session, `server.ServerState` defers `load_settings()`,
the file log, and the writer/reader start until the MCP session exists; tool
handlers await `ensure_started`.

### 7.2 `db.py`

- `connect(path, readonly=...)` — WAL, busy timeout, row factory; read-only opens
  `file:…?mode=ro`.
- `try_connect_readonly` — yields `None` when the database does not exist yet,
  so a reader can serve `ready: false` instead of failing.
- `ensure_schema` — schema, FTS triggers, legacy column migration.
- `upsert_file`, `file_hash`, `replace_file_symbols`, `replace_file_chunks`,
  `delete_file`.
- `fts_search`, `symbol_lookup`, `stats`, `embedding_counts`, `get_chunk`,
  `chunk_ids_for_path`, `record_embedding_state`, `chunks_needing_embedding`.
- `ensure_index_identity`, `get_meta`/`set_meta`.
- `allocate_vector_label`, `vector_label_rows`, `vector_paths_for_labels`,
  `delete_vector_labels`, `mark_vectors_dirty`, `mark_all_vectors_dirty`,
  `clear_vector_dirty`, `dirty_vector_chunks`, `flag_chunks_for_reembed`.

Writes happen only in the writer role. Readers use `try_connect_readonly`.

### 7.3 `parse.py`, `registry.py` and `languages/`

- `registry.py` indexes the **generated** table in `languages/catalog.py`. Every
  entry is `LanguageSpec(name, grammar, extensions, filenames, symbol_nodes,
  extract)`, and `name` is always the pack grammar name. There is no drop-in
  folder: extending support means editing `tools/gen_language_catalog.py` and
  re-running it.
- `detect_language(path)` resolves an entry by exact filename first, then the
  lowercased final suffix.
- **Data formats are never registered.** `catalog.DATA_FORMATS` (json, yaml,
  toml, xml, csv, markdown, vimdoc/`.txt`, rst, latex, regex, ini, properties and
  the VCS/config grammars) exist in the table only for completeness, so `detect`
  returns `None`, `extension_allowlist()` never contains their suffixes, and the
  indexer skips the file. Because filename matching runs first, `CMakeLists.txt`
  still resolves to `cmake`.
- `extract_symbols` loads the grammar lazily; a missing or broken grammar falls
  back to a regex scan for `def`/`function`/`fn`/`class`/`interface`.
- `extract_from_tree` tries, in order: the entry's `extract` callable
  (`languages/extractors.py`: Python, Make, C/C++ declarator chain); the generic
  walk over `SYMBOL_NODES` merged with the default map; and, when that yields
  nothing for an unmapped language, the pack's own `process()` analysis
  (`SYMBOL_FALLBACK=0` disables). A signature is the node text up to its `body`
  field, with the trailing `;` stripped.
- `chunk_source` emits line-aligned windows: `CHUNK_LINES = 30`,
  `CHUNK_CHARS = 1200`, `CHUNK_OVERLAP_LINES = 15`. A long line may end a window
  early, but the next window starts at the first uncovered line, so no content
  is skipped. `CHUNKER_VERSION` (`windows/30x15/1200`) is part of the vector
  identity.
- Grammars are prefetched on a daemon thread at writer startup
  (`PREFETCH_GRAMMARS=0` disables). Only the symbol-mapped grammars
  (`mapped_grammars()`, ~30) are prefetched: pulling all ~370 would trigger a
  download storm for no benefit.
- `catalog.VERSION` is stored as `meta.language_catalog_version`.
  `runtime._reconcile_language_catalog` compares it at startup and drops rows
  whose path is no longer allowed or whose stored `language` no longer matches
  detection; the startup sweep re-indexes them. No schema change, no re-embed.

### 7.4 `embed.py` and `model_prompts.py`

- `embed_texts` posts to `{base}/v1/embeddings` with `{"model", "input"}` and an
  optional bearer token. It splits an oversized input into ≤1200-character
  pieces (preferring line boundaries) and mean-pools the piece vectors back to
  one vector per original text.
- Requests carry at most 16 inputs; at most two HTTP posts are in flight per
  process. A failed request is retried up to three total attempts with
  full-jitter exponential backoff capped at 2 s. Connect timeout is 1 s; the
  overall timeout is `embedding.timeout_s`. `embed_texts` accepts a keyword-only
  `stop_event`: it aborts before each attempt and during the backoff wait,
  raising `EmbedError` without touching `LAST_OK` (a cancelled request is not an
  endpoint failure). Only the service probe passes one.
- Loopback URLs are rewritten to `127.0.0.1` because Docker publishes IPv4 only
  while `localhost` may resolve to `::1` first.
- `embed_documents` applies the document prompt with
  `title = workspace-relative path` (or `none`); `embed_query` applies the query
  prompt. `embed_texts` stays raw for service probes.
- Model defaults: EmbeddingGemma 2 gets `task: code retrieval | query: {query}`
  and `title: {title} | text: {content}`; Qwen3-Embedding gets the query-side
  `Instruct: ...\nQuery: {query}` line and no document prefix.
- `LAST_OK` records the last outcome for `get_status.embed_ok`. It is
  process-local: a fresh reader reports `false` until *that process* embeds a
  query.

### 7.5 `vector_store.py`, `sqlite_vec_store.py`, `faiss_store.py`, `qdrant_store.py`

Covered in §6.2. Notable concurrency rules:

- Every backend module owns its `identity`/`describe`/lifecycle functions; the
  router only validates `vector_store` and dispatches through `_STORES`.
- sqlite-vec needs no process lock for writes (SQLite serialises writers and
  there is no in-process index state); a small lock covers the check-then-create
  of `vec_chunks`. Reads open their own `mode=ro` connection and never create.
- FAISS mutations hold one process lock covering the index and the
  `vector_labels` mapping; `flush` writes and clears dirty flags under the same
  lock.
- Qdrant collection creation is serialized in-process and tolerant of losing a
  create race to another process.
- `describe` returns the `<index.db>#vec_chunks` binding, the FAISS file path, or
  the Qdrant collection for status/logs.

### 7.6 `ignore.py`

`IgnoreRules` resolves workspace-local `.gitignore` files with `pathspec`
gitwildmatch semantics. Deeper files override shallower ones, ancestors are
checked before the path itself (a negation cannot re-include a file under an
ignored directory), and specs are cached by `st_mtime_ns`. Matching is
case-insensitive on Windows. `.git/info/exclude`, global excludes, and ignore
files above the workspace root are deliberately ignored. `IGNORE_DIRS` is
applied first and remains the fixed fallback.

### 7.7 `indexer.py`

- `relative_path` — workspace-relative POSIX path or `None`.
- `iter_workspace_files` — `os.walk` with `dirnames[:]` pruning; counts
  `.gitignore` exclusions in `WalkStats`.
- `index_one_file` — the unit of work; filters before reading bytes, hash short
  circuit, parse/chunk, one SQLite transaction, then `_embed_and_store`.
  `IndexOutcome.status` is `indexed | skipped_unchanged | skipped_filtered |
  error`.
- `_embed_and_store` — fails soft, records `embedding_state`, returns whether
  every chunk got a vector.
- `reembed_pending` — retries chunks without a successful embedding; stops at
  the first failing file.
- `sweep` — re-embed pass, walk, `(mtime, size)` comparison, stale-path removal,
  vector deletion, flush, `LAST_SWEEP` / `LAST_SWEEP_STATS` / `SWEEP_GENERATION`.
- `writer_loop` — consumes `WorkItem` / `SWEEP_REQUEST`, logs per-item failures,
  and flushes the vector store at most once per 30 s while the queue is idle.
- `note_watcher_event` / `watcher_activity` — the activity signal that resets
  sweep backoff. Only successfully queued work counts; ignored events do not.

### 7.8 `watcher.py`

- One `Observer.schedule(handler, workspace_root, recursive=True)` on a daemon
  thread. On Windows this is one `ReadDirectoryChangesW` with subtree watching
  and one emitter thread; never one watch per directory.
- Per-path debounce with `threading.Timer`; the timer enqueues a `WorkItem` and
  never indexes in the callback.
- Handles create, modify, move, and delete. Directory events are logged but need
  no extra scheduling because the recursive root watch covers new subtrees.
- `excluded()` runs before any event logging and drops paths outside the
  workspace, `IGNORE_DIRS` components, the active log file and its rotations,
  and `.gitignore` matches. This prevents the watcher from logging its own log
  writes in a self-triggering loop.
- A `.gitignore` create/modify/move/delete enqueues `SWEEP_REQUEST` so newly
  ignored rows are removed and unignored files are indexed.
- A full queue drops the item with a warning; the next sweep or startup pass is
  the backstop.

### 7.9 `runtime.py` and `workspace_lock.py`

`WriterRuntime.start()`:

1. Acquire `<index_db>.lock`; raise `WorkspaceBusy` if another live process owns
   it.
2. Ensure managed Docker services (fail-soft, bounded by their startup timeout).
3. Start the grammar prefetch thread.
4. `ensure_schema` and `ensure_index_identity`; on invalidation, `reset` the
   active vector store (drops/recreates `vec_chunks`, writes an empty FAISS file,
   or no-ops for Qdrant).
5. `vector_store.ensure_ready` and `reconcile` (fail-soft).
6. Start the service-probe thread (owned by the runtime, gated by its stop
   event).
7. Start `index-writer`, enqueue the startup `SWEEP_REQUEST`, start the watcher,
   start `sweep-timer`.
8. Publish `meta.writer_pid` / `writer_heartbeat` / `writer_started_at` and start
   the heartbeat thread.

`stop()` is idempotent and order-sensitive: stop the watcher, signal the shared
stop event (which also ends the probe's retry loop), join the
probe/sweep/heartbeat/writer threads (the probe is bounded by
`PROBE_JOIN_TIMEOUT_S`, the writer by `DRAIN_TIMEOUT_S`), clear writer liveness,
flush vectors (and, for FAISS, clear dirty flags) **while the lease is still
held**, log final stats, then release the lease last. The sidecar daemon also
clears `daemon.json` and `daemon.token` before releasing, so a new daemon cannot
publish files the old one then deletes. `clear_vector_dirty` is unscoped;
releasing the lease first would let the old process clear the next writer's
dirty flags.

`workspace_lock.FileLock` uses `msvcrt.locking` on Windows and `fcntl.flock` on
POSIX. The open handle is the lease: the OS releases it when the process exits,
so a killed writer never leaves a stale lock (only the file).

### 7.10 `sidecar/`

- `paths.py` — protocol version, `<index dir>/run/` discovery files, atomic
  `daemon.json` and `daemon.spawn.json` writes, 0600 token, deterministic endpoint:
  `\\.\pipe\simple-code-indexer-<hash>` on Windows; a per-user runtime directory
  with `<hash>.sock` on POSIX.
- `protocol.py` — message types `hello`, `welcome`, `register`, `registered`,
  `heartbeat`, `heartbeat_ack`, `unregister`, `unregistered`, `status`, `stop`,
  `stopping`, `error`; JSON text bodies; `request()` serializes one
  request/reply exchange per connection.
- `client.py` — `ReaderSession` attaches within 3 s, spawns a daemon if none is
  reachable, registers, heartbeats every `heartbeat_s`, reconnects every 5 s,
  caches the latest daemon status, and never spawns a second child while the one
  it started is still alive.
- `daemon.py` — `SidecarDaemon` starts the writer runtime first, opens the
  listener, publishes discovery files, accepts clients, and reaps sessions that
  missed heartbeats or whose server process died. It exits after `idle_grace_s`
  with no sessions.
- `registry.py` — thread-safe `LeaseRegistry`; a lease holds the session id,
  server/harness metadata, the watched server process, and the live connection.
- Daemon spawn uses `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` on Windows
  (plus `CREATE_BREAKAWAY_FROM_JOB` with a fallback) and `start_new_session=True`
  on POSIX. On Windows `_daemon_command` runs `sys._base_executable` with the
  reader's resolved `sys.path` instead of the venv `pythonw.exe`, whose redirector
  would keep a second process alive for the daemon's lifetime.
  `DETACHED_PROCESS` is deliberately not used: a redirector (the fallback path)
  spawns the real interpreter without creation flags, which would allocate a
  visible console window.

### 7.11 `server.py`

- Selects the role from `settings.mode`: embedded starts `WriterRuntime` and logs
  to `embed.log`; sidecar starts `ReaderSession` and logs to `reader.log`.
- Builds the MCP server with the installed SDK's constructor handlers
  (`on_list_tools`, `on_call_tool`) — the older decorator API no longer exists in
  the SDK version in use.
- Emits exactly three tools with short descriptions and no `outputSchema`; the
  initialize result advertises no `capabilities.tasks`, and tools carry no
  `execution.taskSupport`.
- `_call_tool` dispatches to `_search_code`, `_symbol_lookup`, or
  `_status_payload`; readers pass `readonly=True` to semantic search.
- `_status_payload` is role-aware: a reader merges the daemon's status when
  reachable and otherwise falls back to `meta.writer_pid` /
  `meta.writer_heartbeat` with a staleness threshold of `3 * heartbeat_s`.
- Startup is non-blocking for queries: readers can serve `ready: false` before
  the database exists; the writer performs schema/identity work before serving.

### 7.12 `parent_watch.py`

`ParentWatchdog` watches exactly one process: the harness that owns the MCP
session. It walks the launch chain upward, skipping boundary processes
(shells, terminals, system processes), `uv`/`uvx`, and the venv `python.exe`
trampoline (recognized by image path on Windows or by a launcher parent), then
watches the first remaining process. A shell is crossed **only** while
everything below it is our own launch plumbing, because the VS Code extension
spawns stdio children with `shell: true` (`harness -> cmd.exe -> uv/python ->
server`); a shell reached above the harness still ends the walk, so a
terminal-launched server has no harness. `parent_watch.ancestor_chain()` exposes
the raw, boundary-free ancestor walk that harness workspace discovery uses.
Nothing above the harness is watched. Liveness is a process handle on Windows,
and on Linux the `/proc/<pid>/stat` start time plus state (a zombie counts as
dead, because `kill(pid, 0)` still succeeds for one); other POSIX hosts fall
back to `kill(pid, 0)`. When the harness disappears, `server._serve` runs role
cleanup and exits with `os._exit(0)`:
`stdio_server`'s stdin reader blocks in a non-cancellable worker thread, so
returning from the serve loop could hang on the open pipe. The daemon
intentionally has no parent watchdog because it must outlive the reader that
spawned it. `SIMPLE_CI_PARENT_WATCH=0` disables the reader watchdog.

### 7.13 `services.py`

`ManagedService` comes from `embedding.service` (always considered) and
`qdrant.service` (only on the Qdrant backend; otherwise the state is
`not_managed`). The writer inspects the container, starts or unpauses it when
needed, falls back to `docker compose up -d <service>` when the container is
missing, resolves the name compose actually created, and waits for the endpoint
until `startup_timeout_s`.

The whole path is fail-soft: missing Docker, a failed container, or a service
that never answers leaves the state `unavailable`, logs it, and lets lexical
search continue. `get_status.services` reports
`running | started | unavailable | not_managed`.

### 7.14 `logging_setup.py`

- stderr: INFO and above, the harness's view of the process.
- File: rotating handler under `<index dir>/log/`, filtered to
  `simple_code_indexer.*` at `log.level` plus WARNING+ from any logger. The
  path follows `index_db_path.parent`.
- Role files: `embed.log` for embedded mode, `writer.log` for the daemon,
  `reader.log` for readers (shared, so its rotation is best-effort).
- stdout is the MCP JSON-RPC channel and is never written by logging.
- `sys.excepthook` and `threading.excepthook` are chained, not replaced, so a
  dead daemon thread reports its traceback.
- An unwritable log directory warns and leaves `get_status.log_file` null; the
  server still serves.

### 7.15 `harnesses/` and `setup_wizard/`

A harness plugin is a plain module loaded from `src/simple_code_indexer/harnesses/`,
`<repo>/harnesses/`, or `<workspace>/harnesses/`; a user plugin overrides a builtin by `NAME`. It
declares `NAME`, `LABEL`, detection dirs/binaries, global config paths, format
(`json`, `toml`, or `yaml`), the config root key, and optional
`entry`/`render`/`remove` callables. A plugin may also implement
`resolve_workspace(cwd) -> Path | None`; it must then put
`SIMPLE_CI_HARNESS=<NAME>` into its entry env (the reserved `RUNTIME_ENV` key),
which is how the server knows which single plugin to ask at runtime. That key is
install-scoped — never a path — so ADR-015 still holds. Writer helpers
parse/merge without destroying unrelated keys; JSONC comments are lost on
rewrite, so the writer backs up the file and refuses to rewrite an unparsable
document. TOML harness configs are merged with marker comments rather than a
round-trip, because the parser cannot write. Bad plugins are skipped.

The setup wizard:

- installs or finds `uv`, syncs the checkout, and runs with the caller's cwd;
- resolves the embedding endpoint (existing container, existing URL, or a
  downloaded GGUF served by a generated compose file), probes the real
  dimension, and records model prompts;
- chooses sqlite-vec, FAISS, or Qdrant (sqlite-vec first, and it probes that the
  interpreter can load the extension before offering it) and optionally
  provisions services;
- writes **one** global `~/.simple-ci/config.yaml`, merging a legacy local file
  and deleting it;
- installs the tool with `uv tool install`, editable when a checkout is detectable
  (the default) or as a built wheel with `--wheel`;
- writes the server entry into selected harness configs at global scope and
  records `setup.install_kind` (`editable`/`wheel`) / `setup.tool_env` plus
  `setup.harnesses`;
- supports `--install-only` (install + repoint the recorded entries) and
  record-driven `--uninstall` (harness entries, uv tool environment, config,
  docker assets, model cache; never workspace indexes).

Harness launch commands preserve the harness cwd and are the same for both install
flavours: the uv tool environment's `bin/python -m simple_code_indexer serve` on
POSIX and its windowless `Scripts/pythonw.exe -m simple_code_indexer serve` on
Windows. Entries are
**workspace-free**
([ADR-015](DECISIONS.md#adr-015-harness-entries-are-global-only-no-per-project-data)):
they carry the install-scoped interpreter only — never `WORKSPACE_ROOT`, `cwd`,
`INDEX_DB`, or `FAISS_PATH` — because the workspace is resolved at runtime
(ADR-018). The only entry env the wizard may write for a resolver harness is the
stable `SIMPLE_CI_HARNESS=<NAME>` marker. Because the server resolves the
workspace after the MCP handshake (roots first), the harness cwd is one source
among four, not the definition.

---

## 8. MCP interface

Output shapes are the contract. They are probe-tested, not enforced by
`outputSchema`.

### 8.1 `search_code`

| Input | Type | Default | Notes |
|---|---|---|---|
| `query` | string | required | free text or code idiom |
| `semantic` | bool | `false` | use the vector store |
| `limit` | int | `10` | clamped to 1..50 |

Lexical response:

```json
{
  "hits": [
    {
      "file": "src/foo.cpp",
      "line": 42,
      "end_line": 58,
      "snippet": "…highlighted match…",
      "score": 12.3,
      "source": "lexical"
    }
  ],
  "source": "lexical"
}
```

Semantic response:

```json
{
  "hits": [],
  "source": "semantic",
  "ready": false,
  "pending_embeddings": 12,
  "message": "semantic index is warming up: 12 chunk(s) still pending embedding"
}
```

`ready: false` with empty `hits` means vectors are still being written;
`ready: true` with empty `hits` is a genuine no-match. A failed embedding or
vector-store call returns `ready: false` with a `semantic search unavailable: …`
message instead of raising. For a non-empty query, if the index database does
not exist yet, either mode returns `ready: false` with
`"index is not ready yet"`; an empty query returns empty hits without a
readiness flag.

### 8.2 `symbol_lookup`

Input: `symbol` (string, required). A single match is returned flat:

```json
{
  "symbol": "calculateWidgetChecksum",
  "kind": "function",
  "defined_in": "widget_checksum.cpp",
  "line": 9,
  "line_end": 20,
  "signature": "uint32_t calculateWidgetChecksum(const Widget&)",
  "language": "cpp"
}
```

Not found: `{"symbol": "…", "found": false, "matches": []}`.
Ambiguous: `found: true` with `matches[]` sorted by path.
Before the index exists: `found: false`, `matches: []`, `ready: false`, and a
message.

### 8.3 `get_status`

```json
{
  "files_indexed": 12,
  "symbols_indexed": 87,
  "chunks_indexed": 240,
  "vectors_indexed": 228,
  "pending_embeddings": 12,
  "watcher_alive": true,
  "last_sweep": "2026-11-12T20:01:02+00:00",
  "sweep_seconds": 0,
  "ignored_dirs": 3,
  "ignored_files": 12,
  "vector_store": "sqlite-vec",
  "vector_store_ok": true,
  "vector_index": "d:/projects/my-app/.simple-ci/index.db#vec_chunks",
  "embed_ok": true,
  "languages_loaded": 322,
  "languages_with_symbol_maps": 29,
  "languages_indexed": 4,
  "data_formats_excluded": 49,
  "grammars_ready": 36,
  "workspace": "d:/projects/my-app",
  "workspace_source": "harness:commandcode",
  "index_db": "d:/projects/my-app/.simple-ci/index.db",
  "config_file": "C:/Users/me/.simple-ci/config.yaml",
  "config_files": ["C:/Users/me/.simple-ci/config.yaml"],
  "log_file": "d:/projects/my-app/.simple-ci/log/reader.log",
  "log_level": "debug",
  "services": {"embedding": "running", "qdrant": "not_managed"},
  "role": "reader",
  "index_ready": true,
  "writer_pid": 1234,
  "writer_ok": true,
  "writer_heartbeat_age_s": 1.2,
  "writer_log_file": "d:/projects/my-app/.simple-ci/log/writer.log",
  "daemon_endpoint": "\\\\.\\pipe\\simple-code-indexer-…",
  "sessions": 2,
  "harnesses": [{"pid": 987, "name": "…"}],
  "vector_index_age_s": 3.4
}
```

- `vectors_indexed` counts chunks with `embedding_state.status='ok'`;
  `pending_embeddings` is `chunks_indexed - vectors_indexed`.
- `vector_store_ok` can be true for an empty index; it does not imply vectors
  exist.
- `vector_index` names the sqlite-vec table binding (`<index.db>#vec_chunks`),
  the FAISS file, or the derived Qdrant collection; `vector_index_age_s` is the
  age of the newest successful embedding for sqlite-vec, the file mtime age for
  FAISS, and `0`/null for Qdrant.
- `last_sweep` is the last completed sweep, not the config interval;
  `sweep_seconds` reports the configured interval (`0` = periodic sweeps off).
- `ignored_dirs` / `ignored_files` are what the last sweep pruned via
  `.gitignore` (0 before the first sweep completes).
- `config_file` is null when no config file exists; `config_files` has 0 or 1
  entries.
- `workspace_source` is `env` (`WORKSPACE_ROOT`), `roots` (the client's
  `roots/list`), `harness:<name>` (a plugin-published workspace), or `cwd`.
- `log_file` is the active reader/embedded file; `writer_log_file` names the
  writer-side file (the daemon's `writer.log`, or `embed.log` in embedded mode).
- `role` is `reader` or `writer`. Readers merge the daemon RPC (`sessions`,
  `harnesses`, `writer_*`, `watcher_alive`, `last_sweep`, services) and fall back
  to `meta` writer liveness when the daemon is unreachable.
- `embed_ok` is process-local (see §7.4).

---

## 9. Cross-cutting concerns

### 9.1 Error handling

`IndexerError` is the base for `EmbedError`, `ParseError`,
`VectorStoreUnavailable` (with `QdrantUnavailable`), `ConfigError`, and
`WorkspaceBusy`. Exceptions are caught at process and tool boundaries, never
with bare `except:`. Indexing and vector work fail soft: one bad file, an
unreachable embedding endpoint, or a broken vector store is logged and leaves
the lexical index usable. Configuration and workspace-lease failures are fatal
at startup (`ConfigError`, `WorkspaceBusy` → exit).

### 9.2 Concurrency and consistency

- Exactly one writer per workspace, enforced by an OS advisory lease.
- Readers open SQLite `mode=ro` and use only read-only vector-store entry
  points. They never call `ensure_schema`, `flush`, `reset`, `reconcile`,
  `upsert_chunks`, or a delete path.
- The writer queue decouples the observer callback from indexing.
- sqlite-vec writes rely on SQLite's own writer serialisation; FAISS mutations
  and dirty-flag updates share a process lock.
- SQLite foreign-key cascades keep symbols, chunks, FTS rows, and embedding
  state aligned with `files`.
- Finalization order (flush while the lease is held, release last) is
  load-bearing.

### 9.3 Logging and observability

Durable DEBUG logs per role, INFO on stderr, and role-aware `get_status` fields
are the observability surface. Logs never contain file contents or chunk text —
only paths, sizes, line ranges, counts, scores, and truncated query text.
`LAST_OK` flags, sweep stats, and writer heartbeat metadata feed status without
extra RPCs. `get_status` is the primary way to verify which workspace a live
harness actually spawned; `get_status.workspace_source` names the source that
won (`env`, `roots`, `harness:<name>`, or `cwd`).

### 9.4 Security boundaries

- The sidecar control channel is local-only and authenticated with a random
  token as the `multiprocessing.connection` authkey; bodies are JSON, never
  pickle.
- Discovery/token files are written atomically with 0600 permissions; the POSIX
  socket directory is user-private.
- `.gitignore` and `IGNORE_DIRS` are indexing policy, not access control. They
  prevent noise and runaway indexing; they do not sandbox reads.
- Secrets come from `embedding.api_key` / `EMBED_API_KEY`; no default API key is
  set, and endpoints are never retried against a public default.

### 9.5 Platform behavior

- **Windows:** single `ReadDirectoryChangesW` subtree watch; named-pipe sidecar
  endpoint; `msvcrt` file lease; case-insensitive `.gitignore` matching; loopback
  URLs rewritten to `127.0.0.1`; `CREATE_NO_WINDOW` for daemon and subprocess
  children so GUI harnesses do not get stray consoles.
- **POSIX:** one recursive inotify watch; AF_UNIX socket in an `XDG_RUNTIME_DIR`
  or `/tmp` per-user directory; `fcntl` lease; `start_new_session=True` daemon
  spawn.
- The workspace is the process cwd on every platform; `WORKSPACE_ROOT` is the
  escape hatch when a harness spawns servers elsewhere.

---

## 10. Extension points

| Extension | Mechanism | Rules |
|---|---|---|
| Language support | Generated table in `languages/catalog.py` | one `LanguageSpec` per language (`name` == `grammar`); `DATA_FORMATS` are never registered; hand-maintained overrides live in `tools/gen_language_catalog.py`; re-run the tool rather than editing the table |
| Harness support | Drop-in module in `harnesses/` or workspace `harnesses/` | config paths, format, root key, optional entry/render/remove; global scope only in the wizard; user overrides builtin by `NAME` |
| Vector backend | New module in `src/simple_code_indexer/` plus one `_STORES` entry in `vector_store.py` | must implement the whole `STORE_CONTRACT` (writer and read-only query paths, identity/describe, flush/reconcile/age); `tests/test_vector_store.py` enforces it |
| Embedding model | Catalog entry plus `model_prompts.defaults_for_model` | dimension is probed, never trusted; document-prompt or chunker changes alter the vector identity |
| Managed service | `service` block under `embedding` or `qdrant` | fail-soft; readiness waits bounded by `startup_timeout_s` |

---

## 11. Install and launch architecture

```
uvx simple-code-indexer setup ──► uv tool install simple-code-indexer==<version>
                                     │
                                     ├─ ~/.simple-ci/config.yaml
                                     ├─ ~/.simple-ci/docker/... (managed services)
                                     └─ harness entry → <tool-env>/pythonw.exe -m simple_code_indexer serve
                                                                          │
                                                                          └─ server.main() in the harness cwd
```

The uv tool environment is the stable launch target: it is version-pinned, needs
no checkout, and is removed with `uv tool uninstall` (which `uninstall` runs).
The launcher must not change cwd; all workspace inference depends on it.
`--editable` (the default from a checkout) and `--wheel` install into that same
environment, so flipping between a live working tree and a built artifact never
rewrites an entry. The wizard is the only supported place that
writes harness entries, config, compose files, and model downloads.

---

## 12. Testing architecture

### 12.1 Test isolation

`tests/conftest.py` applies an autouse fixture that sets:

- `SIMPLE_CI_CONFIG=none` — a developer's global config cannot change defaults.
- `SIMPLE_CI_MODE=embedded` — most tests exercise the single-process writer;
  sidecar tests override it explicitly.
- `SIMPLE_CI_NO_TUI=1` — the real prompter never draws a TUI.

### 12.2 Test layers

| Layer | What it covers |
|---|---|
| Unit | `parse` symbols/chunks, `db` schema/FTS/short-circuit, `config` precedence, `ignore` matching, `embed` batching/retries, `sqlite_vec_store`/`faiss_store`/`qdrant_store` operations, `services`, `logging`, locks |
| Integration | `test_indexer` (tmp workspace, stubbed embeddings), `test_watcher` (real events), `test_runtime`, multi-workspace isolation (FAISS + embedding endpoint) |
| Sidecar | protocol validation, lease registry, reader client, daemon lifecycle, MCP over a real daemon; tests kill spawned daemons by the pid in `daemon.json` in `finally` |
| Stdio contract | `tests/mcp_client.py` is a reusable client with drained stderr and step deadlines; `mcp_probe.py` checks initialize/tools/list/tool shapes |
| Live probes | `service_probe.py` (embedding dimension + optional Qdrant), `live_watch_probe.py` (create a file, find it via MCP) |
| Retrieval benchmarks | `retrieval_bench.py` scores a golden query set; `bench_matrix.py` runs model/backend combinations in isolated scratch directories |

Probes spawn a real server, drain stderr on a thread, and bound the run with
`PROBE_TIMEOUT` (default 180 s), so a stalled server fails instead of hanging.
Benchmarks use `--local-path` to keep `index.db` (and therefore the default
`vec_chunks` table) and `vectors.faiss` out of the
live workspace, and derive a Qdrant collection from that path too.

### 12.3 Quality gates

```bash
uv run ruff check .
uv run ruff format .
uv run pyright
uv run pytest
```

Ruff excludes `*.md` so documentation code blocks are never rewritten. No
Docker, network, or live model is required for the unit suite; service-backed
tests skip or stub when the service is absent.

---

## 13. Maintaining this document

Update this file whenever any of the following changes: process topology, the
MCP tool surface, configuration discovery or precedence, the SQLite schema or
`meta` identity keys, vector-store identity/naming, watcher or sweep behaviour,
sidecar discovery/protocol, logging roles, or the test/probe entry points.

Keep the split of responsibilities:

- **`ARCH.md`** — how the system is structured and how data moves today.
- **[`DECISIONS.md`](DECISIONS.md)** — why a structural choice was made.
- **[`ISSUES.md`](ISSUES.md)** — open functional defects.
- **[`ARCH_ISSUES.md`](ARCH_ISSUES.md)** — open structural debt and smells.
- **[`NOTES.md`](NOTES.md)** — gotchas and operational oddities.
- **[`GLOSSARY.md`](GLOSSARY.md)** — canonical domain terms.

When code and this document disagree, the code is correct: fix the document in
the same change.
