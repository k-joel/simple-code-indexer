# simple-code-indexer 🔍 — code search that indexes itself

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square)](https://www.python.org/downloads/) [![Platforms: Windows, macOS, Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-3776AB?style=flat-square)](https://github.com/k-joel/simple-code-indexer#quick-start) [![License: Apache-2.0](https://img.shields.io/github/license/k-joel/simple-code-indexer?style=flat-square)](LICENSE) [![Last commit](https://img.shields.io/github/last-commit/k-joel/simple-code-indexer?style=flat-square)](https://github.com/k-joel/simple-code-indexer/commits/master)

Local-first MCP server that gives your AI coding agent hybrid lexical + semantic code search, re-indexed on every save.

simple-code-indexer runs alongside your coding agent — Claude Code, VS Code, Cursor, Zed,
OpenCode, Codex CLI, and [others](#supported-harnesses) — as a standard
[MCP](https://modelcontextprotocol.io) server. A file watcher re-indexes every saved file into
**SQLite/FTS5** (keyword search) and **FAISS** (semantic search; [Qdrant](https://qdrant.tech)
optional), so results stay current without manual reindexing. Everything stays on your
machine: each project keeps its index in `<project>/.simple-ci/`, and the single global config
lives in `~/.simple-ci/config.yaml`.

## Why this one

- **Hybrid search in one tool.** `search_code` runs keyword queries through FTS5 and, with
  `semantic=true`, vector search over 30-line chunk windows — overlapping hits are de-duplicated
  automatically.
- **Fresh on every save.** A file watcher indexes each save as it happens; a startup reconcile
  heals anything the watcher missed, and an opt-in periodic sweep (`sweep_seconds`) is the
  backstop. No manual reindex step.
- **322 indexable languages.** All 371 tree-sitter grammars from `tree-sitter-language-pack`
  are catalogued. Documentation and serialization formats — `.md`, `.txt`, `.json`, `.yaml`,
  `.toml`, and the rest — are deliberately never indexed.
- **Symbols, not just text.** `symbol_lookup` resolves definitions via tree-sitter, with
  specialized extractors for Python, C/C++, and Make, and a `coverage` signal when a language
  cannot produce symbols.
- **One-command setup.** An interactive wizard writes the MCP entry into 13 supported harnesses
  (see below) — you never edit a client config by hand.
- **Local-first.** FAISS is the default store (a plain file in your project). Bring your own
  OpenAI-compatible embedding endpoint, or let the wizard download a model (EmbeddingGemma 2
  ~0.6 GB, Qwen3-Embedding 0.6B or 4B, Nomic Embed Code) and serve it locally via llama.cpp in
  Docker (NVIDIA/AMD/Intel aware).
- **Multi-session safe.** Each harness session runs a read-only reader; one writer daemon per
  workspace keeps the index fresh and exits after the last session closes. Closing one harness
  never affects another.

**When not to use it:** you don't run an MCP-capable agent (the tools are only reachable
through one); you need a shared team index (indexes are per-machine and per-workspace); or you
want markdown/JSON/config content searchable (data formats are excluded by design).

## Status

Actively maintained, **pre-1.0** — no tagged releases yet; recent work is tracked in
[docs/CHANGELOG.md](docs/CHANGELOG.md) under *Unreleased*. Python 3.12+; Windows, macOS,
Linux. Lexical search works with no external services; semantic search needs an OpenAI-compatible
embedding endpoint, which the wizard can start for you in Docker.

## Quick start

Prerequisites: **Python 3.12+** and **git**. **Docker Desktop** is optional — only needed to
download an embedding model or run Qdrant; an embedding endpoint you already run elsewhere
works too. The installer installs `uv` when missing.

```bash
git clone https://github.com/k-joel/simple-code-indexer.git simple-code-indexer
cd simple-code-indexer
python setup.py
```

That launches the interactive wizard. Useful variants:

```bash
python setup.py --dry-run                                 # print every action, change nothing
python setup.py --yes                                     # accept all recommended defaults
python setup.py --yes --model embeddinggemma2 --gpu auto  # one model, GPU autodetected
python setup.py --yes --model qwen3-embedding-4b --vector-store faiss
```

The wizard:

1. installs/starts Docker if it is missing (only needed for model downloads or Qdrant),
2. picks an embedding source: an existing container or URL, or a downloadable model
   (EmbeddingGemma 2, Qwen3-Embedding 0.6B, Qwen3-Embedding 4B, Nomic Embed Code), probing the
   real embedding dimension from the endpoint,
3. picks the vector store: **FAISS** (recommended — a local file, no Docker) or **Qdrant**,
4. selects which harnesses to configure (global scope; restart each harness afterwards),
5. copies the repo to a per-user install directory and points the harness entries at it; the
   launcher self-updates via `git pull` on each start.

Everything the wizard writes — config, services, models, install copy — is global. The server
creates `<project>/.simple-ci/` (index + vectors) only when it runs in a project.

### Verify the install

```bash
uv run python tests/service_probe.py   # expect: embeddings OK dim=<n>, PROBE OK
uv run python tests/mcp_probe.py     # exercises all three tools over stdio, expect PROBE OK
```

### Uninstall

```bash
python setup.py --uninstall --dry-run             # show the plan first
python setup.py --uninstall --yes                 # remove install copy, config, services, entries
python setup.py --uninstall --yes --keep-models  # same, but keep the downloaded GGUFs
```

Uninstall is record-driven: it removes exactly what setup wrote. Workspace `.simple-ci/`
indexes, externally managed containers, and endpoints you configured yourself are left alone.

## Using it

After the wizard finishes, **restart your harness** (MCP entries are read at session start),
open a project, and ask in plain language: *"where is the writer lease acquired?"* The agent
calls one of three tools:

| Tool | What it does |
|---|---|
| `search_code` | Keyword (FTS5) search; `semantic=true` switches to vector search |
| `symbol_lookup` | Find definitions by symbol name, with a `coverage` signal |
| `get_status` | Workspace, role, index/vector-store health, sessions, services |

Every hit is a chunk: file path, line range, snippet, score. Every semantic response adds
`ready` and `pending_embeddings`, so an empty result during indexing is distinguishable from a
genuine no-match:

```json
{
  "hits": [
    {
      "file": "src/simple_code_indexer/indexer.py",
      "line": 106,
      "end_line": 135,
      "snippet": "…",
      "score": 0.81
    }
  ],
  "source": "semantic",
  "ready": true,
  "pending_embeddings": 0
}
```

## Supported harnesses

The wizard writes the MCP entry into each client's global config:

Claude Code · Claude Desktop · Codex CLI · Gemini CLI · OpenCode · Cursor · Windsurf (Devin
Local) · VS Code · Zed · Goose · Pi · Command Code · MiMoCode

To support a client that is not on the list, drop a plugin module into
[`harnesses/`](harnesses/) — see [harnesses/README.md](harnesses/README.md) for the contract.

## Configuration

One global file, `~/.simple-ci/config.yaml`. Precedence: **environment variable > YAML >
default**. The wizard writes it; this is the whole file for the default FAISS backend:

```yaml
version: 1
mode: sidecar         # read-only sessions + one writer daemon (default); SIMPLE_CI_MODE overrides
vector_store: faiss   # VECTOR_STORE overrides
embedding:
  base_url: http://localhost:8080
  model: embeddinggemma-2
  dim: 768            # probed by the wizard from the endpoint
sweep_seconds: 0      # 0 = watcher only (default); >0 = periodic reconcile backstop
```

For Qdrant, set `vector_store: qdrant` and add a `qdrant:` block with `url` (a `service:`
block lets the server start that container at boot; services are fail-soft — the server never
refuses to start when Docker is down, lexical search keeps working). Model-specific query and
document prompt prefixes are applied automatically; `embedding.query_prefix` /
`embedding.document_prefix` override them. Config is read at startup — **restart the harness
session after changing it**.

Where things land:

| Path | Contents |
|---|---|
| `~/.simple-ci/config.yaml` | The only config file |
| `~/.simple-ci/model/` | Downloaded GGUF models |
| `~/.simple-ci/docker/` | Generated compose file + GPU bootstrap script |
| Per-user app dir (e.g. `%APPDATA%\simple-code-indexer`) | Installed copy the harnesses launch |
| `<project>/.simple-ci/index.db` | SQLite index (per workspace) |
| `<project>/.simple-ci/vectors.faiss` | FAISS vectors (per workspace, default backend) |
| `<project>/.simple-ci/log/` | `writer.log` + `reader.log` (sidecar) or `embed.log` (embedded) |

Logs are DEBUG by default with rotation (`log.max_bytes`, `log.backups`, `LOG_LEVEL`). File
contents are never logged — only paths, sizes, line ranges, and counts.

## Troubleshooting

- **Wizard says Docker is unavailable** — start Docker Desktop, or choose a branch that doesn't
  need it (existing URL / FAISS).
- **Port already in use** — the wizard picks the next free port and writes it to the config.
- **Config changes ignored** — config is read at startup; restart the harness session.
- **Semantic hits empty, lexical works** — check `ready` / `pending_embeddings` in the response:
  vectors may still be warming up. Qwen3 embedding models need last-token pooling
  (`LLAMA_ARG_POOLING=last`); the wizard warns when it detects a mean-pooling container.
- **Clean rebuild** — delete `<project>/.simple-ci/` and trigger any MCP call; the startup
  reconcile re-indexes and re-embeds everything.
- **Anything else** — [docs/RUNBOOK.md](docs/RUNBOOK.md) has numbered procedures: service
  probes, live-session verification, index rebuilds, stopping the writer daemon, reading logs.

## Benchmarks

`tests/retrieval_bench.py` scores a 42-query golden set (Recall@1/5/10, MRR@10, nDCG@10) on
your workspace, with a lexical FTS baseline:

```bash
uv run python tests/retrieval_bench.py --workspace . --model embeddinggemma-2 \
  --base-url http://localhost:8080 --vector-store faiss --reset \
  --local-path artifacts/bench/local
```

`--local-path` keeps the run away from the live index. `tests/bench_matrix.py` runs every
model/backend combination.

## Development

Toolchain: [uv](https://docs.astral.sh/uv/), Python 3.12, Ruff, Pyright, pytest.

```bash
uv sync             # install dependencies
uv run ruff check . # lint (uv run ruff format . to format)
uv run pyright      # typecheck
uv run pytest       # tests
```

See [AGENTS.md](AGENTS.md) for the full dev loop.

## Documentation

| Doc | Contents |
|---|---|
| [docs/ARCH.md](docs/ARCH.md) | Architecture overview: topology, data flow, components, testing |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operator procedures (RUN-001 …) |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decision records |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Domain terms |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Notable changes |
| [AGENTS.md](AGENTS.md) | Notes for AI coding agents: dev loop, toolchain |

## Licence

[Apache-2.0](LICENSE).
