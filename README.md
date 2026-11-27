# simple-code-indexer 🔍 — code search that indexes itself

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square)](https://www.python.org/downloads/) [![Platforms: Windows, macOS, Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-3776AB?style=flat-square)](https://github.com/k-joel/simple-code-indexer#quick-start) [![License: Apache-2.0](https://img.shields.io/github/license/k-joel/simple-code-indexer?style=flat-square)](LICENSE) [![Last commit](https://img.shields.io/github/last-commit/k-joel/simple-code-indexer?style=flat-square)](https://github.com/k-joel/simple-code-indexer/commits/master)

Local-first MCP server that gives your AI coding agent hybrid lexical + semantic code search, re-indexed on every save.

simple-code-indexer runs alongside your coding agent — Claude Code, VS Code, Cursor, Zed,
OpenCode, Codex CLI, and [others](#supported-harnesses) — as a standard
[MCP](https://modelcontextprotocol.io) server. A file watcher re-indexes every saved file into
**SQLite/FTS5** (keyword search) and **sqlite-vec** (semantic search, vectors in the same
`index.db`; [FAISS](https://github.com/facebookresearch/faiss) and [Qdrant](https://qdrant.tech)
selectable), so results stay current without manual reindexing. Everything stays on your
machine: each project keeps its index in `<project>/.simple-ci/`, and the single global config
lives in `~/.simple-ci/config.yaml`.

## Why this one

- **Hybrid search in one tool.** `search_code` runs keyword queries through FTS5 and, with
  `semantic=true`, vector search over 30-line chunk windows — overlapping hits are de-duplicated
  automatically.
- **Fresh on every save.** A file watcher indexes each save as it happens; a startup reconcile
  heals anything the watcher missed, and a periodic sweep (`sweep_seconds`, every 5 minutes by
  default) is the backstop. No manual reindex step.
- **322 indexable languages.** All 371 tree-sitter grammars from `tree-sitter-language-pack`
  are catalogued. Documentation and serialization formats — `.md`, `.txt`, `.json`, `.yaml`,
  `.toml`, and the rest — are deliberately never indexed.
- **Symbols, not just text.** `symbol_lookup` resolves definitions via tree-sitter, with
  specialized extractors for Python, C/C++, and Make, and a `coverage` signal when a language
  cannot produce symbols.
- **One-command setup.** An interactive wizard writes the MCP entry into 17 supported harnesses
  (see below) — you never edit a client config by hand.
- **Local-first.** sqlite-vec is the default store: vectors live in the same `index.db` as the
  chunks, so a save and its vectors commit together. FAISS (a separate index file) and Qdrant
  remain selectable. Bring your own OpenAI-compatible embedding endpoint, or let the wizard
  download a model (EmbeddingGemma 2 ~0.6 GB, Qwen3-Embedding 0.6B or 4B, Nomic Embed Code) and
  serve it locally via llama.cpp in Docker (NVIDIA/AMD/Intel aware).
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

Prerequisites: **[uv](https://docs.astral.sh/uv/)** (the setup command installs it
when missing) and **Python 3.12+**, which `uv` will fetch. **Docker Desktop** is
optional — only needed to download an embedding model or run Qdrant; an embedding
endpoint you already run elsewhere works too.

```bash
uvx simple-code-indexer setup
```

That installs a version-pinned environment with `uv tool install` and launches the
interactive wizard. Useful variants:

```bash
uvx simple-code-indexer setup --dry-run                          # print every action, change nothing
uvx simple-code-indexer setup --yes                              # accept all recommended defaults
uvx simple-code-indexer setup --yes --model embeddinggemma2 --gpu auto
uvx simple-code-indexer setup --yes --model qwen3-embedding-4b --vector-store faiss
```

The wizard:

1. installs the pinned wheel into a uv tool environment and points every harness
   entry at that environment's interpreter,
2. installs/starts Docker if it is missing (only needed for model downloads or Qdrant),
3. picks an embedding source: an existing container or URL, or a downloadable model
   (EmbeddingGemma 2, Qwen3-Embedding 0.6B, Qwen3-Embedding 4B, Nomic Embed Code), probing
   the real embedding dimension from the endpoint,
4. picks the vector store: **sqlite-vec** (recommended — vectors inside `index.db`, no Docker),
   **FAISS** (a separate local file), or **Qdrant**,
5. selects which harnesses to configure (global scope; restart each harness afterwards).

Everything the wizard writes — config, services, models, tool environment — is global. The
server creates `<project>/.simple-ci/` (index + vectors) only when it runs in a project.

### From a source checkout (no publishing needed)

```bash
git clone https://github.com/k-joel/simple-code-indexer.git simple-code-indexer
cd simple-code-indexer
uv sync                             # editable install of the package
uv run simple-code-indexer setup    # wizard; installs this checkout as a uv tool
```

`simple-code-indexer install` does the install step alone — it installs **this checkout** with
`uv tool install --editable <path>` and exits, installing `uv` first if it is missing. That
replaces the old `python setup.py` bootstrap; there is no committed launcher script any more.

Where it lands (`uv tool dir` prints the environment root, `uv tool dir --bin` the
executables directory):

```
%APPDATA%\uv\tools\simple-code-indexer\                 # Windows
~/Library/Application Support/uv/tools/simple-code-indexer/   # macOS
$XDG_DATA_HOME/uv/tools/simple-code-indexer/            # Linux, else ~/.local/share/uv/tools/...
  Scripts\pythonw.exe        # Windows entry interpreter (windowless)
  bin/python                 # POSIX entry interpreter
  Lib\site-packages\simple_code_indexer\   # the installed copy
```

The default is an **editable** install: a `.pth` in that environment points at the checkout, so
edits are live without reinstalling. `simple-code-indexer install --wheel` (or `setup --wheel`)
builds and installs a real wheel instead — the prod-validation switch — and a run with no
source checkout (e.g. `uvx`) always takes that path, pinned to the published version.

Both flavours reuse the same environment, so the harness entry never changes: switching is just
another `install`, which force-reinstalls. `uv-receipt.toml` inside the environment records which
one is live (`editable = …` means your working tree is being served), and
`simple-code-indexer status` reports it as `install_kind`. An editable install stops working if
you delete the checkout; the wheel flavour does not.

### Verify the install

```bash
uvx simple-code-indexer status          # workspace, index counts, vector store
uv run python tests/service_probe.py    # expect: embeddings OK dim=<n>, PROBE OK
uv run python tests/mcp_probe.py        # exercises all three tools over stdio, expect PROBE OK
```

### Uninstall

```bash
uvx simple-code-indexer uninstall --dry-run             # show the plan first
uvx simple-code-indexer uninstall --yes                 # remove the tool env, config, services, entries
uvx simple-code-indexer uninstall --yes --keep-models   # same, but keep the downloaded GGUFs
```

Uninstall is record-driven: it removes exactly what setup wrote. Workspace `.simple-ci/`
indexes, externally managed containers, and endpoints you configured yourself are left alone.

On Windows, `uvx simple-code-indexer uninstall` cannot delete the tool environment it is
executing from. It removes everything else and prints `uv tool uninstall simple-code-indexer`
to run after it exits.

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

The wizard writes the MCP entry into each client's global config (or the project config, when a
project scope is chosen):

Claude Code · Claude Desktop · Codex CLI · Gemini CLI · OpenCode · Cursor · Windsurf (Devin
Local) · VS Code · Zed · Goose · Pi · Command Code · MiMoCode · Hermes Agent · OpenClaw ·
Kilo Code · Cline

Detection is by the client's own CLI where it has one (`cursor --version`) and by its config
directory where it does not, and `simple-code-indexer setup --harnesses` prints which signal
matched for every supported client. Once you have answered the harness question once, a re-run
preselects your recorded choice rather than re-detecting.

To support a client that is not on the list, drop a plugin module into
[`harnesses/`](harnesses/) — see [harnesses/README.md](harnesses/README.md) for the contract.

## Configuration

One global file, `~/.simple-ci/config.yaml`. Precedence: **environment variable > YAML >
default** — and every environment variable is prefixed `SIMPLE_CI_` (`SIMPLE_CI_LOG_LEVEL`, not
`LOG_LEVEL`); they exist for debugging, so prefer the file or a flag in normal use. The wizard
writes it; this is the whole file for the default sqlite-vec backend:

```yaml
version: 1
mode: sidecar              # read-only sessions + one writer daemon (default); SIMPLE_CI_MODE overrides
vector_store: sqlite-vec   # SIMPLE_CI_VECTOR_STORE overrides; faiss | qdrant also supported
embedding:
  base_url: http://localhost:8080
  model: embeddinggemma-2
  dim: 768                 # probed by the wizard from the endpoint
sweep_seconds: 300         # 0 = watcher only; 300 s = periodic reconcile backstop (default)
```

Optional sqlite-vec tuning (defaults shown): `sqlite_vec.chunk_size: 64`,
`sqlite_vec.mmap_size: 1073741824` (a mapping limit, not preallocation), and
`sqlite_vec.cache_size: -262144` (KiB); `SQLITE_VEC_CHUNK_SIZE`, `SQLITE_VEC_MMAP_SIZE`, and
`SQLITE_VEC_CACHE_SIZE` override them. Changing `chunk_size` rebuilds the vector table and
re-embeds the workspace.

For FAISS, set `vector_store: faiss` (the separate `vectors.faiss` file; `faiss.path` /
`SIMPLE_CI_FAISS_PATH`). For Qdrant, set `vector_store: qdrant` and add a `qdrant:` block with `url` (a
`service:` block lets the server start that container at boot; services are fail-soft — the
server never refuses to start when Docker is down, lexical search keeps working).
Model-specific query and document prompt prefixes are applied automatically;
`embedding.query_prefix` / `embedding.document_prefix` override them. Config is read at
startup — **restart the harness session after changing it**.

Where things land:

| Path | Contents |
|---|---|
| `~/.simple-ci/config.yaml` | The only config file |
| `~/.simple-ci/model/` | Downloaded GGUF models |
| `~/.simple-ci/docker/` | Generated compose file + GPU bootstrap script |
| uv tool environment (`uv tool dir`) | The pinned install the harnesses launch |
| `<project>/.simple-ci/index.db` | SQLite index (per workspace), including the default vector table |
| `<project>/.simple-ci/vectors.faiss` | FAISS vectors (per workspace, `vector_store: faiss` only) |
| `<project>/.simple-ci/log/` | `writer.log` + `reader.log` (sidecar) or `embed.log` (embedded) |

Logs are DEBUG by default with rotation (`log.max_bytes`, `log.backups`, `SIMPLE_CI_LOG_LEVEL`). File
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
  --base-url http://localhost:8080 --vector-store sqlite-vec --reset \
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

See [AGENTS.md](AGENTS.md) for the full dev loop. `uv sync` installs the package
editably, so `uv run simple-code-indexer …` and `python -m simple_code_indexer …`
run your working tree.

## Releasing

Releases are tag-driven and publish through PyPI Trusted Publishing, so no token is
stored in the repository.

```bash
python tools/release.py --bump patch     # bump, cut the CHANGELOG, commit, tag, push
```

The tag triggers `.github/workflows/release.yml`, which builds once, verifies the tag
matches `pyproject.toml`, and publishes to PyPI (gated by the `pypi` environment) and
TestPyPI (on manual dispatch). `pyproject.toml` holds the version because `uv_build`
needs static metadata; `tools/release.py --verify-tag` enforces that the tag agrees.
A published version can never be re-uploaded — ship a new patch and yank the bad one.

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
