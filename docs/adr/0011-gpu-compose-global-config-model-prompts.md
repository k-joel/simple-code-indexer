# GPU-aware compose generation, split global/local config, and model prompts

`setup.py` generates the embedding container from a packaged compose template and picks
the llama.cpp image for the host GPU: NVIDIA → `server-cuda`, AMD → `server-rocm`, Intel →
`server-intel`, otherwise `server`. Global assets live in `~/.simple-ci/` (`config.yaml`,
`docker/docker-compose.yml`, `docker/gpu_init.sh`, `model/*.gguf`); project data stays in
`<workspace>/.simple-ci/` (`config.yaml`, `index.db`, `vectors.faiss`). The wizard records
each model's documented code-retrieval prompts, and the server applies them to queries and
chunks. Config files are now layered instead of shadowing: global is loaded first, the
local file overrides individual keys.

## Context

The original wizard wrote one `~/.simple-ci/docker-compose.yml` with a CPU `server` image,
mounted `./models`, and only supported one config file per install. The hand-written
compose template used a fixed Windows model path and an NVIDIA reservation. EmbeddingGemma 2
and Qwen3-Embedding both publish GGUF files in different repositories and document
task-specific query instructions that materially change retrieval quality; the previous
catalog pointed EmbeddingGemma at a different repository and embedded all text raw.

The split between machine-wide assets (models, compose, endpoint) and per-project settings
(vector store, tuning) is the natural fit: a model download is expensive and shared, while
the FAISS/SQLite files and backend choice are workspace-specific. Shadowing configs broke
that split, because a minimal local file would have hidden the global embedding service.

## Decision

- Compose is rendered from `src/simple_code_indexer/setup_wizard/templates/docker-compose.yml`
  (environment-variable style, `LLAMA_ARG_*`), with the model mount `../model:/models:ro`.
  The template lives inside the package because `uv_build` ships the module directory but
  not a repo-root `docker_template/`.
- `LLAMA_ARG_ALIAS` pins the OpenAI `model` id to the catalog's `api_model`, so the served
  name matches `embedding.model` regardless of the GGUF's `general.name`.
- GPU detection is best-effort and injectable: `nvidia-smi -L`, then Windows
  `Win32_VideoController`, then Linux DRM vendor ids (`0x10de`/`0x1002`/`0x8086`); `--gpu`
  overrides. NVIDIA with no Docker runtime prompts to run the copied `gpu_init.sh`; a
  decline/failure falls back to the CPU image rather than leaving a container that cannot
  start. AMD/Intel use device passthrough (`/dev/kfd`, `/dev/dri`) without an init script.
- Models come from their upstream repos: EmbeddingGemma 2 BF16 from
  `unsloth/embeddinggemma-2-GGUF` (text backbone only; **no** `mmproj-*.gguf`), Qwen3
  Q8_0 from `Qwen/Qwen3-Embedding-0.6B-GGUF`. Both are stored in `~/.simple-ci/model/`;
  the wizard offers to reuse a complete global setup instead of re-downloading.
- Prompts come from `model_prompts.defaults_for_model` and are written to the global
  config (`embedding.query_prefix`, `embedding.document_prefix`). Explicit config wins,
  an empty string disables a side, and env vars override. `embed_texts` stays raw for
  service probes; `embed_query`/`embed_documents` apply the templates.
- `embed_fingerprint` hashes the document prefix only. It is part of the FAISS identity
  and the derived Qdrant collection name, so changing chunk formatting re-embeds, while
  changing only the query instruction does not.
- `configfile.config_paths` returns global then local; `load_layered_config` deep-merges
  mappings (scalars/lists/null replace). `SIMPLE_CI_CONFIG` remains the single-file escape
  hatch. `Settings.config_source` is the most specific path; `config_sources` exposes all
  of them in `get_status.config_files`.

## Considered Options

- **Keep generating compose dicts in Python:** fewer moving parts, but the template was
  the requested source of truth and the YAML is easier to inspect than a dict literal.
- **Keep the template at the repo root:** works for a clone, breaks for `uvx --from <repo>`
  installs because the backend only ships the module directory.
- **Always use the CPU image:** simplest and always starts, but wastes the GPU that both
  models fit in easily (EmbeddingGemma 2 is ~550 MB, Qwen3-0.6B Q8 ~640 MB).
- **Run `gpu_init.sh` unconditionally on NVIDIA:** would reinstall the toolkit on hosts
  where Docker already exposes the runtime; the wizard checks `docker info` first.
- **Put everything in the local config (previous behavior):** requires duplicating the
  embedding block per project and re-downloading models. Rejected in favor of layered files.
- **Apply only the query prompt:** cheaper, but the EmbeddingGemma model card specifies
  document-side `title: ... | text: ...` formatting and it affects retrieval quality.

## Consequences

- New CLI flags: `--model KEY` (auto-download without asking, also bypasses the reuse
  prompt) and `--gpu auto|nvidia|amd|intel|cpu`; `--scope` now selects a single config
  file, and `--config PATH` writes one combined file.
- `~/.simple-ci/models/` is renamed to `~/.simple-ci/model/`; `~/.simple-ci/docker-compose.yml`
  moves under `docker/`. The wizard migrates the model directory and re-renders the compose
  file; old Qdrant data stays at `~/.simple-ci/qdrant_storage` via `../qdrant_storage`.
- Changing the embedding model still changes the dimension and forces a re-index; changing
  only the query prompt does not re-embed, because stored vectors are unchanged.
- Existing configs without prompts keep their identity; configs whose model name matches
  EmbeddingGemma/Qwen3 gain prompts automatically. Document-prompt changes are detected
  through `embed_fingerprint`; model-name-only changes with the same dimension are not.
- AMD ROCm and Intel SYCL passthrough on WSL2 is best-effort; `--gpu cpu` is the escape
  hatch. On Windows `gpu_init.sh` runs via `wsl -e bash`, so it targets the default WSL2
  distro (which must be the one running dockerd).
- The wizard's compose/module paths are unit-tested; live downloads and container startup
  still need Docker plus network and are verified manually (`tests/service_probe.py`,
  `tests/mcp_probe.py`).
