# Generation Metadata

| Field | Value |
|---|---|
| Commit hash | `bf859e22745bff1f4a5c921606a48f26e709e9` |
| Short commit | `bf859e2` |
| Commit message | `Implement workspace locking mechanism and enhance configuration testing` |
| Branch | `master` |
| Commit date | 2026-10-20T08:26:33+05:30 |
| Generation timestamp (local) | 2026-10-20 08:45:11 +05:30 |
| Output language | English |
| Generator | `deepwiki` skill (Kilo) |
| Template set | `templates/overview.md`, `architecture.md`, `dependencies.md`, `data-flow.md`, `module.md`, `glossary.md` |

## Incremental Update Notes

Re-running the generator should:

1. Re-read this file and compare the commit hash above with the current HEAD:

   ```bash
   git rev-parse HEAD
   git log --oneline bf859e2..HEAD
   ```
2. Diff the source tree against the recorded commit for changes under
   `src/simple_code_indexer/`, `tests/`, `setup.py`, `pyproject.toml`, `docs/adr/` and the
   top-level docs.
3. Update the affected pages, **preserving existing headings** and appending an
   `## Update Notes` section in this format:

   ```markdown
   ## Update Notes
   - YYYY-MM-DD: Short summary of what changed and why.
   ```

4. Regenerate `INDEX.md` so that every page appears exactly once, with deterministic section
   and entry ordering.
5. Update the commit hash, branch and timestamp in this file.

## Page Inventory

| Page | Template | Sections | Status |
|---|---|---|---|
| `INDEX.md` | dynamic index | 8 | generated |
| `overview.md` | `templates/overview.md` | 11 | generated |
| `architecture.md` | `templates/architecture.md` | 12 | generated |
| `dependencies.md` | `templates/dependencies.md` | 9 | generated |
| `data-flow.md` | `templates/data-flow.md` | 9 | generated |
| `glossary.md` | `templates/glossary.md` | 6 | generated |
| `configuration.md` | extra guide | 11 | generated |
| `operations.md` | extra guide | 10 | generated |
| `plugins.md` | extra guide | 6 | generated |
| `testing.md` | extra guide | 9 | generated |
| `troubleshooting.md` | extra guide | 11 | generated |
| `modules/server.md` | `templates/module.md` | 10 | generated |
| `modules/indexer.md` | `templates/module.md` | 10 | generated |
| `modules/db.md` | `templates/module.md` | 10 | generated |
| `modules/parse.md` | `templates/module.md` | 10 | generated |
| `modules/embed.md` | `templates/module.md` | 10 | generated |
| `modules/qdrant-store.md` | `templates/module.md` | 10 | generated |
| `modules/config.md` | `templates/module.md` | 10 | generated |
| `modules/watcher.md` | `templates/module.md` | 10 | generated |
| `modules/services.md` | `templates/module.md` | 10 | generated |
| `modules/workspace-lock.md` | `templates/module.md` | 10 | generated |
| `modules/registry.md` | `templates/module.md` | 10 | generated |
| `modules/builtin-plugins.md` | `templates/module.md` | 10 | generated |
| `modules/harnesses.md` | `templates/module.md` | 10 | generated |
| `modules/setup-wizard.md` | `templates/module.md` | 10 | generated |
| `assets/README.md` | asset folder note | 4 | generated |

## Coverage

| Area of the repository | Covered by |
|---|---|
| MCP surface, startup, status | `overview.md`, `architecture.md`, `modules/server.md` |
| Indexing pipeline | `data-flow.md`, `modules/indexer.md`, `modules/watcher.md`, `modules/db.md` |
| Parsing and chunking | `modules/parse.md`, `modules/builtin-plugins.md`, `modules/registry.md` |
| Semantic path | `modules/embed.md`, `modules/qdrant-store.md` |
| Configuration and services | `configuration.md`, `modules/config.md`, `modules/services.md`, `modules/workspace-lock.md` |
| Setup and harness integration | `operations.md`, `modules/setup-wizard.md`, `modules/harnesses.md`, `plugins.md` |
| Quality and recovery | `testing.md`, `troubleshooting.md`, `dependencies.md` |
| Domain language | `glossary.md` |

## Assets

The repository contains **no local raster or vector images** (no PNG, JPG, SVG or GIF files
outside build and cache directories), so `assets/` holds no copied images in this build. All
diagrams are authored as **mermaid** blocks embedded directly in the Markdown pages, which
compatible renderers draw inline. When a future page references a local image, copy it into
`assets/` under a deterministic name (`<source-page>-<reference-index>-<slug>.<ext>`) and
reference it with a project-relative path.

## Missing Assets

None — no page references an unresolvable image or diagram.

## Source References

- `README.md`
- `AGENTS.md`
- `docs/tdd.md`
- `GLOSSARY.md`
- `NOTES.md`
- `ISSUES.md`
- `docs/adr/0001-index-on-save-not-git-state.md`
- `docs/adr/0002-direct-chunk-embedding.md`
- `docs/adr/0003-all-in-one-mvp-topology.md`
- `docs/adr/0004-single-writer-sqlite-wal.md`
- `docs/adr/0005-python-mcp-stack.md`
- `docs/adr/0006-harness-safe-mcp-surface.md`
- `docs/adr/0007-single-workspace-no-multi-repo.md`
- `docs/adr/0008-host-spawned-cwd-per-repo-collections.md`
- `docs/adr/0009-setup-wizard-managed-services-config.md`