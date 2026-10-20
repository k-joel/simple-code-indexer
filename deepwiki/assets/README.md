# Assets

Local images and rendered diagram assets referenced by the deepwiki pages.

## Current Contents

This build contains **no copied image files**: the source repository ships no local raster
or vector images (no PNG, JPG, SVG, GIF or WEBP outside build and cache directories).

| Item | Count | Notes |
|---|---|---|
| Copied images | 0 | No local images exist in the repository |
| Mermaid diagram blocks | 24 | Embedded directly in the Markdown pages |
| Missing-asset notes | 0 | No page references an unresolvable asset |

All diagrams are authored as **mermaid** blocks embedded directly in the Markdown, so they
render inline in any mermaid-capable viewer without a separate asset file.

## Naming Convention for Future Copies

When a page starts referencing a local image, copy it here with a deterministic name so
repeated runs produce identical output:

```
<source-page>-<reference-index>-<slug>.<ext>
```

The reference index is the 1-based position of the image within its source page, and the
slug is a lowercase, hyphenated form of the alt text.

| Example | Source page | Reference index | Alt text |
|---|---|---|---|
| `overview-1-startup-flow.svg` | `overview.md` | 1 | Startup flow |
| `architecture-2-index-on-save.png` | `architecture.md` | 2 | Index on save |

## Referencing

Images are referenced with a project-relative path from the page that uses them:

```markdown
![Alt text preserved from the source](../assets/overview-1-startup-flow.svg)
```

Alt text and captions from the source content are preserved verbatim.

## Diagram Inventory

Every mermaid block in this wiki, by page and kind:

| Page | Diagram kind | Subject |
|---|---|---|
| `overview.md` | flowchart | The harness, server, stores and services at a glance |
| `architecture.md` | flowchart | The host process and its external boundaries |
| `architecture.md` | sequence | The index-on-save hot path |
| `architecture.md` | flowchart | The threads inside the server process |
| `data-flow.md` | flowchart | Inputs, processing, stores and outputs |
| `data-flow.md` | stateDiagram | The lifecycle of one chunk through the pipeline |
| `configuration.md` | flowchart | How one setting is resolved |
| `dependencies.md` | flowchart | The runtime dependency surface |
| `operations.md` | flowchart | The lifecycle of one harness session |
| `plugins.md` | flowchart | The two plugin loaders |
| `testing.md` | flowchart | The test layers and their seams |
| `troubleshooting.md` | flowchart | The diagnostic order |
| `glossary.md` | flowchart | The index domain, the stores and the runtime |
| `INDEX.md` | flowchart | The wiki's own section structure |
| `modules/server.md` | flowchart | The tool dispatch |
| `modules/indexer.md` | flowchart | The write path and the sweep |
| `modules/db.md` | erDiagram | The SQLite schema and its cascades |
| `modules/parse.md` | flowchart | Detection, extraction and chunking |
| `modules/embed.md` | flowchart | Split, post, validate, pool |
| `modules/qdrant-store.md` | flowchart | The collection guard |
| `modules/config.md` | flowchart | Config discovery and resolution |
| `modules/watcher.md` | sequence | Save event to index job |
| `modules/watcher.md` | flowchart | Watch registration and event routing |
| `modules/services.md` | flowchart | The managed-container lifecycle |
| `modules/workspace-lock.md` | sequence | Two servers, one workspace |
| `modules/registry.md` | flowchart | The plugin loader and the allowlists |
| `modules/builtin-plugins.md` | flowchart | From file to symbols |
| `modules/harnesses.md` | flowchart | The harness plugin loader and the merge |
| `modules/setup-wizard.md` | flowchart | The wizard steps |

All diagrams are plain mermaid and render in GitHub, VS Code, Obsidian and most static
site generators without an extra build step.

## Missing Assets

If an image or diagram cannot be resolved, the page must carry a missing-asset note naming
the **source page** and the **referenced path**, for example:

```markdown
> **Missing asset** -- `architecture.md` references `assets/startup-flow.svg`, which could
> not be resolved in the source repository.
```

No such notes are present in this build.

## Source References

- `assets/README.md`
- `deepwiki/INDEX.md`
- `deepwiki/GENERATION.md`
- `deepwiki/overview.md`
- `deepwiki/architecture.md`
- `deepwiki/data-flow.md`
- `deepwiki/glossary.md`
- `deepwiki/configuration.md`
- `deepwiki/dependencies.md`
- `deepwiki/operations.md`
- `deepwiki/plugins.md`
- `deepwiki/testing.md`
- `deepwiki/troubleshooting.md`
- `deepwiki/modules/`
