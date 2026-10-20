# Module: Setup Wizard

## Responsibilities

- Run the **interactive first-run setup**: choose an embedding endpoint, provision Qdrant,
  probe the vector dimension, write `config.yaml`, and register the server with the detected
  MCP harnesses.
- Keep every external effect **injectable** (`prompts`, `runner`, `http`) so the tests run
  hermetically — no Docker, no network, no `input()`.
- Support a **dry run** that prints every action without writing files or starting
  containers.
- Migrate a legacy `.index/` directory to `.simple-ci/` under the workspace lock.
- Update the project's `.gitignore` with `.simple-ci/`.

## Key Files

| Path | Purpose |
|---|---|
| `src/simple_code_indexer/setup_wizard/__init__.py` | The `Wizard` class — every step and its ordering |
| `src/simple_code_indexer/setup_wizard/prompts.py` | Stdlib-only yes/no, choice, multi-select, text prompts |
| `src/simple_code_indexer/setup_wizard/probe.py` | HTTP probes: model list, embedding dimension, Qdrant readiness |
| `src/simple_code_indexer/setup_wizard/provision.py` | Docker discovery, compose generation, model download, port selection |
| `src/simple_code_indexer/setup_wizard/write.py` | `.gitignore`, harness config merges, atomic writes |
| `src/simple_code_indexer/setup_wizard/catalog.py` | The three downloadable embedding models |
| `src/simple_code_indexer/setup_wizard/prereqs.py` | Docker install hints |
| `src/simple_code_indexer/setup_wizard/__main__.py` | `python -m simple_code_indexer.setup_wizard` |
| `setup.py` | The repo-root launcher that calls the wizard |

## Public Interfaces

| Name | Kind | Description |
|---|---|---|
| `Wizard.run() -> int` | method | The whole flow; `0` ok, `1` aborted, `130` cancelled |
| `Wizard(...)` | class | `cwd`, `home`, `repo_root`, `prompts`, `runner`, `http`, `dry_run`, `assume_yes`, `scope`, `config_path`, `model_url` |
| `run(argv) -> int` | function | Argparse entry (`--dry-run`, `--yes`, `--scope`, `--config`, `--repo-root`, `--model-url`) |
| `SetupAborted` | exception | A user-visible abort |
| `prompts.Prompter` | class | `say`, `ask_yes_no`, `ask_choice`, `ask_multi`, `ask_text` |
| `probe.Http` | class | `get_json`, `post_json` over urllib |
| `provision.Runner` | class | `which`, `run` — the subprocess seam |

### Wizard steps, in order

| Step | What it does |
|---|---|
| `_banner` | Prints project / home / dry-run banner |
| `_step_gitignore` | Adds `.simple-ci/` to the git root's `.gitignore` |
| `_step_migrate_index` | Moves `.index/index.db` → `.simple-ci/index.db` under the lock |
| `_step_embedding` | Existing URL / existing container / auto-download |
| `_step_qdrant` | Existing URL / existing container / Docker provisioning |
| `_write_config` | Writes `config.yaml` (global or local) |
| `_step_harnesses` | Writes the MCP entry into every selected harness config |
| `_summary` | Prints the resolved config, index, endpoints, collection and harness targets |

## Inputs and Outputs

| Type | Name | Location | Description |
| --- | --- | --- | --- |
| Input | Command line | `setup.py` / `__main__` | `--dry-run`, `--yes`, `--scope`, `--config`, `--model-url` |
| Input | Embedding endpoint | HTTP | Probed for models and the real vector dimension |
| Input | Docker daemon | `docker` CLI | Container list, start, compose up |
| Input | Harness specs | `harnesses.load_harnesses()` | Which clients to configure and where their config lives |
| Output | `config.yaml` | `~/.simple-ci/` or `<cwd>/.simple-ci/` | Embedding, Qdrant, sweep and debounce settings |
| Output | Harness configs | per-harness paths | The `simple-code-indexer` server entry |
| Output | Compose file | `~/.simple-ci/docker-compose.yml` | `embed` and/or `qdrant` services |
| Output | Model file | `~/.simple-ci/models/*.gguf` | The downloaded GGUF |
| Output | `.gitignore` entry | git root | `.simple-ci/` |

## Configuration

| Flag / variable | Effect |
|---|---|
| `--dry-run` | Print every action; write nothing, start nothing |
| `--yes` | Accept the recommended default at every prompt |
| `--scope global\|local` | Force the config location without asking |
| `--config PATH` | Write the config to an explicit path |
| `--model-url URL` | Override the download URL of the first catalog model |
| `--repo-root PATH` | Where the `uvx --from <repo>` entry points (set by `setup.py`) |

## Example Snippets

The written config shape:

```python
data: dict[str, Any] = {
    "version": configfile.CONFIG_VERSION,
    "embedding": {
        "base_url": embedding["base_url"],
        "model": embedding["model"],
        "dim": embedding["dim"],
        "api_key": embedding.get("api_key"),
        "timeout_s": 15.0,
    },
    "qdrant": {"url": qdrant["url"]},
    "sweep_seconds": 45,
    "debounce_ms": 400,
}
if embedding.get("service"):
    data["embedding"]["service"] = embedding["service"]
if qdrant.get("service"):
    data["qdrant"]["service"] = qdrant["service"]
```

The MCP entry written into a harness:

```python
command = [
    self.runner.which("uvx") or "uvx",
    "--from",
    str(self.repo_root),
    SERVER_NAME,
]
```

The dimension probe — the live value always wins over the catalog fallback:

```python
dim = probe.embedding_dim(self.http, url, model, key)
if dim is None:
    return None
self.prompts.say(f"Embedding dimension: {dim}")
```

The catalog (offline fallback dimensions):

| Model | API name | Dim | Pooling | Download |
|---|---|---|---|---|
| EmbeddingGemma 2 (recommended) | `embeddinggemma-2` | 768 | mean | ~0.4 GB |
| Qwen3-Embedding-0.6B | `Qwen3-Embedding-0.6B` | 1024 | last | ~0.7 GB |
| Nomic Embed Code 7B | `nomic-embed-code` | 3584 | last | ~4.5 GB |

## Edge Cases

- **`--dry-run`** → nothing is written; the wizard prints the actions and the would-be config.
- **Docker unavailable** → the container branches are skipped; the URL branches still work; the
  wizard prints the install hint.
- **Port already in use** → `available_port` walks up (`8080 → 8081`, `6333 → 6334`).
- **Embedding endpoint does not answer** → the wizard offers to try a different URL and
  aborts with `SetupAborted` if the user declines.
- **Container has no published port** → the wizard asks for the URL manually.
- **Harness config file already contains the entry** → the file is rewritten, and the previous
  content is backed up as `<name>.bak.<timestamp>`.
- **Harness config is unparseable JSON** → the wizard prints the manual snippet instead of
  writing.
- **Two harnesses share one config file** → the second is skipped with a message.
- **Legacy `.index/` present** → migrated under the workspace lock; if another server owns it,
  the migration is skipped with a message.
- **Ctrl-C** → exit code 130, "Cancelled." printed.
- **`uv` missing** → `setup.py` installs it (PowerShell on Windows, `curl | sh` elsewhere).

## Diagrams

```mermaid
flowchart TB
    RUN[python setup.py] --> UV[find or install uv]
    UV --> SYNC[uv sync --project ROOT]
    SYNC --> WIZ[python -m simple_code_indexer.setup_wizard\ncwd = caller's cwd]
    WIZ --> BANNER[_banner]
    BANNER --> GI[_step_gitignore]
    GI --> MIG[_step_migrate_index]
    MIG --> EMB[_step_embedding\nURL | container | download]
    EMB --> QDR[_step_qdrant\nURL | container | docker]
    QDR --> CFG[_write_config]
    CFG --> HARN[_step_harnesses]
    HARN --> SUM[_summary]
    SUM -->|print| DONE[Restart the harness]
```

## Tests

- `tests/test_setup_wizard.py` — the full flow with injected prompts, runner and HTTP.
- `tests/test_harnesses.py` — the harness plugin contract the wizard depends on.
- `tests/test_configfile.py` — the config the wizard writes.

## Source References

- `src/simple_code_indexer/setup_wizard/__init__.py`
- `src/simple_code_indexer/setup_wizard/__main__.py`
- `src/simple_code_indexer/setup_wizard/prompts.py`
- `src/simple_code_indexer/setup_wizard/probe.py`
- `src/simple_code_indexer/setup_wizard/provision.py`
- `src/simple_code_indexer/setup_wizard/write.py`
- `src/simple_code_indexer/setup_wizard/catalog.py`
- `src/simple_code_indexer/setup_wizard/prereqs.py`
- `src/simple_code_indexer/harnesses/__init__.py`
- `src/simple_code_indexer/configfile.py`
- `src/simple_code_indexer/config.py`
- `setup.py`
- `tests/test_setup_wizard.py`
- `docs/adr/0009-setup-wizard-managed-services-config.md`