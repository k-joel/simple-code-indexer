# FAISS is the primary vector store; Qdrant becomes an option

Semantic search is now backed by a local FAISS index by default: an
`IndexIDMap2(IndexFlatIP(dim))` persisted at `<workspace>/.simple-ci/vectors.faiss`.
Vectors are L2-normalised, so inner product is cosine similarity — the same score Qdrant's
`COSINE` distance returns. Qdrant remains available with the top-level config key
`vector_store: qdrant`; a config with no `vector_store` key but a non-empty `qdrant:` section
keeps using Qdrant, so existing installations do not re-index on upgrade. The MCP server
talks to a backend-agnostic router (`vector_store.py`); `setup.py` offers FAISS first and
skips all Qdrant/Docker provisioning on that branch.

## Context

Qdrant was the only semantic backend ([ADR-0008](./0008-host-spawned-cwd-per-repo-collections.md)),
which made a second service mandatory for every install: a running Qdrant server (or Docker
plus a managed container), a per-workspace collection, and a network round trip on every
semantic search and upsert. For a code index — one workspace, tens of thousands of chunks,
single writer — the operational cost outweighed the benefit: FAISS ships as a single
`faiss-cpu` wheel, keeps every vector in RAM (≈10 KB per 2560-dim chunk), and needs no
service, URL, collection, or Docker.

The constraint was preserving the existing Qdrant path and data model (chunk vectors,
`embedding_state` observability, re-embed on identity change) without a rewrite of the
indexer, watcher, or MCP surface.

## Considered Options

- **Keep Qdrant as the only backend:** simplest code, but every install needs a service and
  the wizard must provision or locate one. Rejected as the default.
- **Embed vectors in SQLite (sqlite-vec / BLOB scan):** no new dependency, but either an
  extension (`sqlite-vec`) or an O(n) Python distance loop per query; neither matches FAISS
  on speed or simplicity. Rejected.
- **FAISS as the default, Qdrant opt-in (chosen):** `faiss-cpu` + `numpy` wheels install on
  the supported platforms; the file is per workspace and gitignored with the index; the
  Qdrant module keeps its existing surface and config.
- **Migrate existing Qdrant vectors into FAISS on switch:** requires reading every point and
  side-stepping dimension/identity checks. Rejected; switching re-embeds instead, which the
  identity machinery already does.
- **Hybrid / IVF / HNSW indexes:** unnecessary at code-index scale; `IndexFlatIP` search is
  O(n) but n is small, and reconstruction stays trivial.

## Consequences

- `faiss-cpu` and `numpy` are runtime dependencies. `faiss` is imported lazily, so the
  Qdrant path never imports it; a missing/broken faiss fails soft (`vector_store_ok: false`)
  and leaves lexical search working.
- SQLite owns the chunk metadata and the label mapping; the FAISS file owns the vectors.
  `vector_labels(label → path, chunk_index)` maps FAISS ids back to chunks. Labels are
  allocated from `meta.vector_label_seq` and never reused — a crash can leave a vector in
  the file after its mapping row is gone, and recycling that id would attribute the old
  vector to a new chunk.
- The store lock covers both the index and the label mapping. `flush` writes
  `vectors.faiss.tmp` and `os.replace`s it, then clears the dirty flags; a crash between the
  two only causes a harmless re-embed. `reconcile` flags every chunk whose label is dirty,
  so a lost file or an unflushed write heals on the next start.
- Changing the backend, the FAISS path, the dimension, the Qdrant URL, or the collection
  invalidates the index: rows and label mappings are deleted, the FAISS file is replaced
  with an empty index, and the startup reconcile re-indexes everything. Old Qdrant points
  are left orphaned; the operator deletes them.
- The status payload changed: `qdrant_ok` and `collection` are replaced by `vector_store`,
  `vector_store_ok`, and `vector_index` (the FAISS file path or the Qdrant collection).
- Memory scales with the index (all vectors resident). A 50 k-chunk workspace of 2560-dim
  vectors needs roughly 500 MB; IVF/HNSW is the follow-up if that becomes a problem.
- A managed `qdrant.service` is ignored (`not_managed`) on the FAISS backend, so an old
  config never starts Docker for a store that is not used.
