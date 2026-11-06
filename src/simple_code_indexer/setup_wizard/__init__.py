"""Interactive setup wizard (invoked by the repo-root `setup.py`).

Everything external is injectable (`prompts`, `runner`, `http`) so the tests run
hermetically: no Docker, no network, no `input()`.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from simple_code_indexer import configfile, model_prompts
from simple_code_indexer.config import (
    derive_collection_name,
    embedding_fingerprint,
)
from simple_code_indexer.errors import ConfigError
from simple_code_indexer.harnesses import HarnessSpec, load_harnesses
from simple_code_indexer.setup_wizard import catalog, gpu, probe, provision, write
from simple_code_indexer.setup_wizard.prereqs import (
    docker_install_hint,
    gpu_runtime_hint,
)
from simple_code_indexer.setup_wizard.prompts import Prompter
from simple_code_indexer.workspace_lock import WorkspaceLock

SERVER_NAME = "simple-code-indexer"
DEFAULT_EMBED_MODEL = "Qwen3-Embedding-4B-Q6_K"
DEFAULT_EMBED_DIM = 2560


class SetupAborted(Exception):
    """A user-visible abort; `run()` converts it to exit code 1."""


def _default_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def _stored_prompt(
    section: dict[str, Any], key: str, default: str | None
) -> str | None:
    """Explicit config value (empty disables) else the model default."""
    if key in section:
        raw = section[key]
        if isinstance(raw, str):
            return raw.strip() or None
    return default


class Wizard:
    def __init__(
        self,
        *,
        cwd: Path | None = None,
        home: Path | None = None,
        repo_root: Path | None = None,
        prompts: Prompter | None = None,
        runner: provision.Runner | None = None,
        http: probe.Http | None = None,
        dry_run: bool = False,
        assume_yes: bool = False,
        scope: str | None = None,
        config_path: Path | None = None,
        model_url: str | None = None,
        model: str | None = None,
        gpu_backend: str | None = None,
        platform: str = sys.platform,
    ) -> None:
        self.cwd = (cwd or Path.cwd()).resolve()
        self.home = (home or Path.home()).resolve()
        self.repo_root = (repo_root or _default_repo_root()).resolve()
        self.prompts = prompts or Prompter()
        self.runner = runner or provision.Runner()
        self.http = http or probe.Http()
        self.dry_run = dry_run
        self.assume_yes = assume_yes
        self.scope = scope
        self.config_path = config_path
        self.model_url = model_url
        self.model = model
        self.gpu_backend = gpu_backend
        self.platform = platform
        self._docker_checked: bool | None = None
        self._written_harnesses: list[tuple[HarnessSpec, Path]] = []

    def run(self) -> int:
        try:
            self._banner()
            self._step_migrate_global_assets()
            embedding = self._step_existing_global_setup()
            self._step_gitignore()
            self._step_migrate_index()
            if embedding is None:
                embedding = self._step_embedding()
            backend = self._step_vector_store()
            qdrant = self._step_qdrant() if backend == "qdrant" else None
            config_paths = self._write_config(embedding, backend, qdrant)
            self._step_harnesses()
            self._summary(embedding, backend, qdrant, config_paths)
            return 0
        except SetupAborted as exc:
            self.prompts.say(f"\nSetup aborted: {exc}")
            return 1
        except (ConfigError, OSError, TypeError, ValueError) as exc:
            self.prompts.say(f"\nSetup failed: {exc}")
            return 1
        except KeyboardInterrupt:
            self.prompts.say("\nCancelled.")
            return 130

    # -- prompts ---------------------------------------------------------

    def _ask_yes_no(self, question: str, *, default: bool = True) -> bool:
        if self.assume_yes:
            return default
        return self.prompts.ask_yes_no(question, default=default)

    def _ask_choice(
        self, question: str, options: list[str], *, default: int = 0
    ) -> int:
        if self.assume_yes:
            return default
        return self.prompts.ask_choice(question, options, default=default)

    def _ask_text(
        self,
        question: str,
        *,
        default: str | None = None,
        allow_empty: bool = False,
    ) -> str:
        if self.assume_yes and default is not None:
            return default
        return self.prompts.ask_text(question, default=default, allow_empty=allow_empty)

    def _ask_multi(
        self, question: str, options: list[str], *, default: list[int]
    ) -> list[int]:
        if self.assume_yes:
            return list(default)
        return self.prompts.ask_multi(question, options, default=default)

    # -- steps -----------------------------------------------------------

    def _banner(self) -> None:
        self.prompts.say("simple-code-indexer setup")
        self.prompts.say(f"  project: {self.cwd}")
        self.prompts.say(f"  home:    {self.home}")
        if self.dry_run:
            self.prompts.say("  dry run: no files, containers, or downloads")
        self.prompts.say()

    def _step_migrate_global_assets(self) -> None:
        """Rename the pre-0.1 `~/.simple-ci/models` directory when found."""
        legacy = provision.global_dir(self.home) / "models"
        target = provision.model_dir(self.home)
        if not legacy.is_dir() or target.exists():
            return
        if not self._ask_yes_no(f"Found {legacy}. Move it to {target}?", default=True):
            return
        if self.dry_run:
            self.prompts.say(f"Would move {legacy} to {target}")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(legacy, target)
        self.prompts.say(f"Moved the models to {target}")

    def _step_existing_global_setup(self) -> dict[str, Any] | None:
        """Offer to reuse a complete global setup instead of re-downloading."""
        if (
            self.config_path is not None
            or self.model is not None
            or self.gpu_backend is not None
        ):
            return None
        global_dir = provision.global_dir(self.home)
        compose_file = provision.compose_path(self.home)
        config_path = global_dir / configfile.CONFIG_FILENAME
        model_files = sorted(provision.model_dir(self.home).glob("*.gguf"))
        if not (compose_file.is_file() and config_path.is_file() and model_files):
            return None
        try:
            raw = configfile.load_config(config_path)
            embedding = configfile.get_mapping(raw, "embedding")
            base_url = configfile.get_str(embedding, "base_url", where="embedding")
            model = configfile.get_str(embedding, "model", where="embedding")
            setup = configfile.get_mapping(raw, "setup")
            dim = configfile.get_int(embedding, "dim", where="embedding")
            api_key = configfile.get_str(embedding, "api_key", where="embedding")
            service = self._existing_service(
                configfile.get_mapping(embedding, "service"), compose_file
            )
            model_key = configfile.get_str(setup, "model_key", where="setup")
            stored_gpu = configfile.get_str(setup, "gpu", where="setup")
            recorded = configfile.get_str(setup, "model_file", where="setup")
        except ConfigError:
            return None
        if base_url is None or model is None:
            return None
        chosen = model_files[0]
        if recorded is not None:
            candidate = Path(recorded).expanduser()
            if not candidate.is_file():
                return None
            chosen = candidate
        self.prompts.say(f"Found the global embedding setup in {global_dir}.")
        if not self._ask_yes_no(
            f"Reuse {model} ({chosen.name}) and skip the download?", default=True
        ):
            return None
        default_query, default_document = model_prompts.defaults_for_model(model)
        result: dict[str, Any] = {
            "base_url": base_url,
            "model": model,
            "dim": dim or 0,
            "api_key": api_key or None,
            "query_prefix": _stored_prompt(embedding, "query_prefix", default_query),
            "document_prefix": _stored_prompt(
                embedding, "document_prefix", default_document
            ),
            "service": service,
            "model_key": model_key,
            "model_file": str(chosen),
            "gpu": stored_gpu,
        }
        if self.dry_run:
            self.prompts.say(f"Would reuse {base_url} ({model}).")
            return result
        if result["dim"] <= 0:
            probed = probe.embedding_dim(self.http, base_url, model, result["api_key"])
            if probed is None:
                self.prompts.say(f"{base_url} did not answer; reconfiguring.")
                return None
            result["dim"] = probed
        elif probe.embedding_dim(self.http, base_url, model, result["api_key"]) is None:
            self.prompts.say(f"{base_url} is not answering; starting the container.")
            if not provision.compose_up(self.runner, compose_file, "embed"):
                self.prompts.say("Could not start the container; reconfiguring.")
                return None
            provision.wait_until(
                lambda: probe.embedding_dim(self.http, base_url, model) is not None,
                timeout=180.0,
            )
        self.prompts.say(f"Reusing the global embedding setup at {base_url}.")
        return result

    def _existing_service(
        self, raw: dict[str, Any], compose_file: Path
    ) -> dict[str, Any]:
        service: dict[str, Any] = {
            "container": provision.EMBED_CONTAINER,
            "compose_file": str(compose_file),
            "compose_service": "embed",
            "startup_timeout_s": 60,
        }
        container = configfile.get_str(raw, "container", where="embedding.service")
        compose_service = configfile.get_str(
            raw, "compose_service", where="embedding.service"
        )
        if container:
            service["container"] = container
        if compose_service:
            service["compose_service"] = compose_service
        timeout = raw.get("startup_timeout_s")
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
            service["startup_timeout_s"] = float(timeout)
        return service

    def _docker_ready(self) -> bool:
        if self._docker_checked is None:
            self._docker_checked = provision.docker_available(self.runner)
            if not self._docker_checked:
                self.prompts.say("Docker is not available. " + docker_install_hint())
        return self._docker_checked

    def _step_gitignore(self) -> None:
        if self.dry_run:
            root: Path | None = self.cwd
        else:
            root = write.git_root(self.cwd, self.runner)
        if root is None:
            self.prompts.say("No git repository found; skipping the .gitignore update.")
            return
        path = root / ".gitignore"
        if not path.is_file():
            if self._ask_yes_no(f"No .gitignore in {root}. Create one?", default=True):
                self.prompts.say(
                    f"{'Would create' if self.dry_run else 'Creating'} {path}"
                )
                if not self.dry_run:
                    write.append_gitignore(path)
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if any(line.strip() == write.GITIGNORE_ENTRY for line in lines):
            self.prompts.say(f"{path} already ignores {write.GITIGNORE_ENTRY}")
            return
        if self._ask_yes_no(f"Add {write.GITIGNORE_ENTRY} to {path}?", default=True):
            if not self.dry_run:
                write.append_gitignore(path)
            self.prompts.say(
                f"{'Would add' if self.dry_run else 'Added'} "
                f"{write.GITIGNORE_ENTRY} to {path}"
            )

    def _step_migrate_index(self) -> None:
        legacy = self.cwd / ".index" / "index.db"
        target = self.cwd / ".simple-ci" / "index.db"
        if not legacy.is_file() or target.exists():
            return
        if not self._ask_yes_no(
            "Found an old .index/ directory. Move it to .simple-ci/?", default=True
        ):
            return
        if self.dry_run:
            self.prompts.say(f"Would move {legacy} to {target}")
            return
        lock = WorkspaceLock(legacy)
        if not lock.acquire():
            self.prompts.say(
                "Skipped: another server owns the old index; stop it and re-run."
            )
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("", "-wal", "-shm"):
                source = legacy.with_name(legacy.name + suffix)
                if source.exists():
                    os.replace(source, target.with_name(target.name + suffix))
        finally:
            lock.release()
        self.prompts.say(f"Moved the index to {target}")

    def _step_embedding(self) -> dict[str, Any]:
        if self.model is not None:
            return self._embedding_auto()
        if self._ask_yes_no(
            "Do you already have an embedding model server?", default=False
        ):
            if self._ask_yes_no("Is it running in Docker?", default=False):
                from_container = self._embedding_from_container()
                if from_container is not None:
                    return from_container
            return self._embedding_from_url()
        return self._embedding_auto()

    def _embedding_from_url(self) -> dict[str, Any]:
        default_url = "http://localhost:8080"
        while True:
            url = self._ask_text("Embedding base URL", default=default_url)
            result = self._configure_embedding(
                url, ask_key=True, default_model=DEFAULT_EMBED_MODEL
            )
            if result is not None:
                return result
            self.prompts.say(f"Could not read an embedding vector from {url}.")
            if not self._ask_yes_no("Try a different URL?", default=True):
                raise SetupAborted("no working embedding endpoint")
            default_url = url

    def _embedding_from_container(self) -> dict[str, Any] | None:
        if not self._docker_ready():
            return None
        containers = provision.list_containers(self.runner)
        if not containers:
            self.prompts.say("No Docker containers found.")
            return None
        labels = [f"{c.name} — {c.image} ({c.status})" for c in containers]
        choice = self._ask_choice(
            "Select the embedding container",
            labels,
            default=self._preferred(containers, ("llama", "ollama", "embed", "tei")),
        )
        container = containers[choice]
        url: str | None = None
        if self.dry_run:
            url = "http://localhost:8080"
        else:
            if not provision.start_container(self.runner, container.name):
                self.prompts.say(f"Could not start {container.name}.")
            url = provision.container_url(self.runner, container.name)
        if url is None:
            url = self._ask_text(
                "No published embedding port found; enter its URL",
                default="http://localhost:8080",
            )
        result = self._configure_embedding(
            url,
            ask_key=True,
            default_model=DEFAULT_EMBED_MODEL,
            service={"container": container.name},
        )
        if result is None:
            self.prompts.say("That container did not answer as an embedding server.")
        return result

    def _embedding_auto(self) -> dict[str, Any]:
        if self.model is not None:
            matches = [item for item in catalog.CATALOG if item.key == self.model]
            if not matches:
                raise SetupAborted(f"unknown embedding model {self.model!r}")
            model = matches[0]
            if self.model_url:
                model = replace(model, url=self.model_url)
        else:
            labels = [item.label for item in catalog.CATALOG]
            labels.append("Cancel — I'll set up my own embedding server")
            choice = self._ask_choice(
                "No embedding server found. Auto-download a model?", labels, default=0
            )
            if choice >= len(catalog.CATALOG):
                raise SetupAborted("set up an embedding server, then re-run setup.py")
            model = catalog.CATALOG[choice]
            if self.model_url and choice == 0:
                model = replace(model, url=self.model_url)
        gpu_info = self._resolve_gpu()
        port = 8080 if self.dry_run else self._embed_port()
        compose_file = provision.compose_path(self.home)
        destination = provision.model_dir(self.home) / model.filename
        url = f"http://localhost:{port}"
        service = {
            "container": provision.EMBED_CONTAINER,
            "compose_file": str(compose_file),
            "compose_service": "embed",
            "startup_timeout_s": 60,
        }
        result: dict[str, Any] = {
            "base_url": url,
            "model": model.api_model,
            "api_key": None,
            "dim": model.dim,
            "service": service,
            "query_prefix": model.query_prefix,
            "document_prefix": model.document_prefix,
            "model_key": model.key,
            "model_file": str(destination),
            "gpu": gpu_info.vendor,
        }
        if self.dry_run:
            self.prompts.say(f"Would download {model.url}")
            self.prompts.say(f"Would add the 'embed' service to {compose_file}")
            return result
        provision.download_model(model.url, destination, output=self.prompts.say)
        provision.write_compose(
            compose_file,
            {
                "embed": provision.embed_service(
                    model,
                    port,
                    destination.name,
                    image=gpu_info.image,
                    gpu_vendor=gpu_info.vendor,
                )
            },
        )
        if not provision.compose_up(self.runner, compose_file, "embed"):
            raise SetupAborted("docker compose could not start the embedding container")
        if not provision.wait_until(
            lambda: probe.embedding_dim(self.http, url, model.api_model) is not None,
            timeout=180.0,
        ):
            self.prompts.say("The model is still loading; the server will wait for it.")
        probed = probe.embedding_dim(self.http, url, model.api_model)
        result["dim"] = probed or model.dim
        return result

    def _embed_port(self) -> int:
        """Keep the running container's published port so re-runs don't churn."""
        url = provision.container_url(self.runner, provision.EMBED_CONTAINER)
        if url is not None:
            _, _, published = url.rpartition(":")
            if published.isdigit():
                return int(published)
        return provision.available_port("127.0.0.1", 8080)

    def _resolve_gpu(self) -> gpu.GpuInfo:
        info = gpu.detect_gpu(
            self.runner, platform=self.platform, override=self.gpu_backend
        )
        self.prompts.say(f"GPU: {info.name}")
        self.prompts.say(f"Container image: {info.image}")
        if info.vendor != "nvidia":
            return info
        if self.dry_run:
            self.prompts.say(
                "Would install gpu_init.sh and offer to run it when the NVIDIA "
                "runtime is missing."
            )
            return info
        script = provision.install_gpu_script(self.home)
        if gpu.nvidia_runtime_ready(self.runner):
            self.prompts.say("Docker already exposes the NVIDIA runtime.")
            return info
        if not provision.docker_available(self.runner):
            self.prompts.say("Docker is unavailable; GPU setup cannot run yet.")
            return info
        if not self._ask_yes_no(
            "NVIDIA GPU detected but Docker has no GPU runtime. "
            f"Run {script.name} now? (needs sudo)",
            default=True,
        ):
            self.prompts.say(
                "Run it later: " + gpu.manual_command(script, platform=self.platform)
            )
            return gpu.GpuInfo("cpu", info.name)
        argv = gpu.init_command(self.runner, script, platform=self.platform)
        if argv is None:
            self.prompts.say(
                "No WSL/bash runner found. Run it by hand: "
                + gpu.manual_command(script, platform=self.platform)
            )
            return gpu.GpuInfo("cpu", info.name)
        self.prompts.say("Running " + " ".join(argv))
        if self.runner.run_console(argv) != 0:
            self.prompts.say(
                "gpu_init.sh failed. Falling back to the CPU image; fix the GPU "
                "runtime and re-run setup.py to use the GPU."
            )
            self.prompts.say(gpu_runtime_hint())
            return gpu.GpuInfo("cpu", info.name)
        return info

    def _configure_embedding(
        self,
        url: str,
        *,
        ask_key: bool,
        default_model: str,
        service: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        key: str | None = None
        if ask_key:
            key = (
                self._ask_text(
                    "API key (optional, blank for none)",
                    default="",
                    allow_empty=True,
                )
                or None
            )
        models = [] if self.dry_run else probe.list_models(self.http, url, key)
        if models:
            self.prompts.say("Detected models: " + ", ".join(models))
        model = self._ask_text(
            "Embedding model name",
            default=models[0] if models else default_model,
        )
        if self.dry_run:
            dim = DEFAULT_EMBED_DIM
            self.prompts.say(f"Dry run: assuming dimension {dim}")
        else:
            dim = probe.embedding_dim(self.http, url, model, key)
            if dim is None:
                return None
            self.prompts.say(f"Embedding dimension: {dim}")
        query_prefix, document_prefix = model_prompts.defaults_for_model(model)
        result: dict[str, Any] = {
            "base_url": url.rstrip("/"),
            "model": model,
            "api_key": key,
            "dim": dim,
            "query_prefix": query_prefix,
            "document_prefix": document_prefix,
        }
        if service is not None:
            result["service"] = service
        return result

    def _existing_vector_store(self) -> str:
        """Follow the config the server would read, so a re-run keeps its backend."""
        paths = (
            (self.config_path,)
            if self.config_path is not None
            else configfile.config_paths(self.cwd, self.home)
        )
        if not paths:
            return "faiss"
        try:
            raw = configfile.load_layered_config(paths)
        except ConfigError:
            return "faiss"
        configured = raw.get("vector_store")
        if isinstance(configured, str) and configured.strip().lower() in {
            "faiss",
            "qdrant",
        }:
            return configured.strip().lower()
        qdrant = raw.get("qdrant")
        if isinstance(qdrant, dict) and qdrant:
            return "qdrant"
        return "faiss"

    def _step_vector_store(self) -> str:
        labels = [
            "FAISS (recommended) — local file, no Docker",
            "Qdrant — Docker container or existing server",
        ]
        default = 0 if self._existing_vector_store() == "faiss" else 1
        choice = self._ask_choice(
            "Which vector store should back semantic search?",
            labels,
            default=default,
        )
        return "qdrant" if choice == 1 else "faiss"

    def _step_qdrant(self) -> dict[str, Any]:
        if self._ask_yes_no("Do you already have Qdrant set up?", default=False):
            if self._ask_yes_no("Is it running in Docker?", default=False):
                from_container = self._qdrant_from_container()
                if from_container is not None:
                    return from_container
            url = self._ask_text("Qdrant URL", default="http://localhost:6333")
            return self._qdrant_result(url)
        if self._ask_yes_no("Set up Qdrant automatically with Docker?", default=True):
            return self._qdrant_auto()
        raise SetupAborted("Qdrant is required; install it and re-run setup.py")

    def _qdrant_from_container(self) -> dict[str, Any] | None:
        if not self._docker_ready():
            return None
        containers = provision.list_containers(self.runner)
        matching = [c for c in containers if "qdrant" in c.image.lower()]
        pool = matching or containers
        if not pool:
            self.prompts.say("No Docker containers found.")
            return None
        labels = [f"{c.name} — {c.image} ({c.status})" for c in pool]
        choice = self._ask_choice("Select the Qdrant container", labels, default=0)
        container = pool[choice]
        url: str | None = None
        if self.dry_run:
            url = "http://localhost:6333"
        else:
            if not provision.start_container(self.runner, container.name):
                self.prompts.say(f"Could not start {container.name}.")
            url = provision.container_url(self.runner, container.name, ports=(6333,))
        if url is None:
            url = self._ask_text(
                "No published Qdrant port found; enter its URL",
                default="http://localhost:6333",
            )
        return self._qdrant_result(url, {"container": container.name})

    def _qdrant_auto(self) -> dict[str, Any]:
        if not self.dry_run and not self._docker_ready():
            raise SetupAborted("Docker is required for automatic Qdrant setup")
        port = 6333 if self.dry_run else provision.available_port("127.0.0.1", 6333)
        compose_file = provision.compose_path(self.home)
        url = f"http://localhost:{port}"
        service = {
            "container": provision.QDRANT_CONTAINER,
            "compose_file": str(compose_file),
            "compose_service": "qdrant",
            "startup_timeout_s": 45,
        }
        if self.dry_run:
            self.prompts.say(f"Would add the 'qdrant' service to {compose_file}")
            return {"url": url, "service": service}
        provision.write_compose(
            compose_file, {"qdrant": provision.qdrant_service(port)}
        )
        if not provision.compose_up(self.runner, compose_file, "qdrant"):
            raise SetupAborted("docker compose could not start Qdrant")
        if not provision.wait_until(
            lambda: probe.qdrant_ready(self.http, url), timeout=120.0
        ):
            self.prompts.say("Qdrant is still starting; the server will wait for it.")
        return {"url": url, "service": service}

    def _qdrant_result(
        self, url: str, service: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.dry_run and not probe.qdrant_ready(self.http, url):
            self.prompts.say(f"Warning: {url} did not answer; saving it anyway.")
        result: dict[str, Any] = {"url": url.rstrip("/")}
        if service is not None:
            result["service"] = service
        return result

    def _preferred(
        self, containers: list[provision.Container], needles: tuple[str, ...]
    ) -> int:
        for index, container in enumerate(containers):
            image = container.image.lower()
            if any(needle in image for needle in needles):
                return index
        return 0

    def _write_config(
        self,
        embedding: dict[str, Any],
        backend: str,
        qdrant: dict[str, Any] | None,
    ) -> tuple[Path, ...]:
        embedding_section: dict[str, Any] = {
            "base_url": embedding["base_url"],
            "model": embedding["model"],
            "dim": embedding["dim"],
            "api_key": embedding.get("api_key"),
            "timeout_s": 15.0,
            "query_prefix": embedding.get("query_prefix"),
            "document_prefix": embedding.get("document_prefix"),
        }
        if embedding.get("service"):
            embedding_section["service"] = embedding["service"]
        project: dict[str, Any] = {
            "version": configfile.CONFIG_VERSION,
            "vector_store": backend,
            "sweep_seconds": 45,
            "debounce_ms": 400,
        }
        global_document: dict[str, Any] = {
            "version": configfile.CONFIG_VERSION,
            "embedding": embedding_section,
        }
        setup: dict[str, Any] = {}
        for key in ("model_key", "model_file", "gpu"):
            if embedding.get(key):
                setup[key] = embedding[key]
        if setup:
            global_document["setup"] = setup
        if backend == "qdrant":
            assert qdrant is not None
            global_document["qdrant"] = {"url": qdrant["url"]}
            if qdrant.get("service"):
                global_document["qdrant"]["service"] = qdrant["service"]
        if self.config_path is not None:
            combined = {**project, "embedding": embedding_section}
            for key in ("setup", "qdrant"):
                if key in global_document:
                    combined[key] = global_document[key]
            return (self._write_one(self.config_path, combined),)
        if self.scope == "global":
            return (self._write_one(self._global_config_path(), global_document),)
        if self.scope == "local":
            combined = {**project, "embedding": embedding_section}
            if "qdrant" in global_document:
                combined["qdrant"] = global_document["qdrant"]
            return (self._write_one(self._local_config_path(), combined),)
        return (
            self._write_one(self._global_config_path(), global_document),
            self._write_one(self._local_config_path(), project),
        )

    def _write_one(self, target: Path, data: dict[str, Any]) -> Path:
        if self.dry_run:
            self.prompts.say(f"Would write {target}")
        else:
            configfile.write_config(data, target)
            self.prompts.say(f"Wrote {target}")
        return target

    def _global_config_path(self) -> Path:
        return provision.global_dir(self.home) / configfile.CONFIG_FILENAME

    def _local_config_path(self) -> Path:
        return self.cwd / configfile.LOCAL_DIRNAME / configfile.CONFIG_FILENAME

    def _step_harnesses(self) -> None:
        specs = load_harnesses()
        if not specs:
            self.prompts.say("No harness plugins found.")
            return
        detected = [
            index for index, spec in enumerate(specs) if spec.detected(self.home)
        ]
        labels = [
            f"{spec.label} ({spec.name})" + (" — detected" if index in detected else "")
            for index, spec in enumerate(specs)
        ]
        selected = self._ask_multi(
            "Install the MCP server for which harnesses?",
            labels,
            default=detected,
        )
        command = [
            self.runner.which("uvx") or "uvx",
            "--from",
            str(self.repo_root),
            SERVER_NAME,
        ]
        written: dict[Path, HarnessSpec] = {}
        for index in selected:
            spec = specs[index]
            scope_choice = self._ask_choice(
                f"{spec.label}: save where?",
                [
                    (
                        f"Global "
                        f"({spec.candidates('global', self.cwd, self.home)[:1] or 'n/a'})"
                    ),
                    "Project-local",
                ],
                default=0,
            )
            target = write.choose_target(
                spec,
                "global" if scope_choice == 0 else "local",
                self.cwd,
                self.home,
            )
            if target is None:
                self.prompts.say(f"{spec.label} has no config path for that scope.")
                continue
            resolved = target.resolve()
            if resolved in written:
                self.prompts.say(
                    f"{target} was already updated for {written[resolved].label}; "
                    f"skipping {spec.label}."
                )
                continue
            if self.dry_run:
                snippet = write.render(spec, SERVER_NAME, command, {})
                self.prompts.say(f"Would update {target}:\n{snippet}")
            else:
                try:
                    write.install(spec, target, SERVER_NAME, command, {})
                except (TypeError, ValueError, OSError) as exc:
                    self.prompts.say(f"Could not update {target}: {exc}")
                    self.prompts.say(
                        "Add this entry manually:\n"
                        + write.render(spec, SERVER_NAME, command, {})
                    )
                    continue
                self.prompts.say(f"Updated {target}")
            written[resolved] = spec
            self._written_harnesses.append((spec, target))

    def _summary(
        self,
        embedding: dict[str, Any],
        backend: str,
        qdrant: dict[str, Any] | None,
        config_paths: tuple[Path, ...],
    ) -> None:
        dim = int(embedding["dim"])
        fingerprint = embedding_fingerprint(embedding.get("document_prefix"))
        self.prompts.say()
        self.prompts.say("Setup complete.")
        for path in config_paths:
            self.prompts.say(f"  config:       {path}")
        self.prompts.say(
            f"  index:        {self.cwd / configfile.LOCAL_DIRNAME / 'index.db'}"
        )
        self.prompts.say(
            f"  embedding:    {embedding['base_url']} "
            f"(model={embedding['model']}, dim={dim})"
        )
        self.prompts.say(f"  vector store: {backend}")
        self.prompts.say(f"  compose:      {provision.compose_path(self.home)}")
        self.prompts.say(f"  models:       {provision.model_dir(self.home)}")
        if embedding.get("gpu"):
            self.prompts.say(f"  gpu backend:  {embedding['gpu']}")
        if backend == "qdrant":
            assert qdrant is not None
            self.prompts.say(f"  qdrant:       {qdrant['url']}")
            self.prompts.say(
                f"  collection:   {derive_collection_name(self.cwd, dim, fingerprint)}"
            )
        else:
            self.prompts.say(
                f"  vectors:      "
                f"{self.cwd / configfile.LOCAL_DIRNAME / 'vectors.faiss'}"
            )
        for spec, target in self._written_harnesses:
            self.prompts.say(f"  harness:      {spec.label} -> {target}")
        self.prompts.say()
        self.prompts.say("Restart your harness to pick up the new server.")
        if backend == "qdrant":
            self.prompts.say(
                "Changing the embedding model later creates a new collection and "
                "re-indexes the workspace."
            )
        else:
            self.prompts.say(
                "Changing the embedding model later re-embeds the workspace."
            )


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="setup.py",
        description="Interactive setup for simple-code-indexer.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print actions without changing anything"
    )
    parser.add_argument(
        "--yes", action="store_true", help="accept every recommended default"
    )
    parser.add_argument("--scope", choices=["global", "local"], default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument(
        "--model-url", default=None, help="override the model download URL"
    )
    parser.add_argument(
        "--model",
        choices=[model.key for model in catalog.CATALOG],
        default=None,
        help="download this embedding model without asking",
    )
    parser.add_argument(
        "--gpu",
        choices=["auto", "nvidia", "amd", "intel", "cpu"],
        default=None,
        help="override GPU detection for the container image",
    )
    args = parser.parse_args(argv)
    wizard = Wizard(
        cwd=Path.cwd(),
        repo_root=args.repo_root,
        dry_run=args.dry_run,
        assume_yes=args.yes,
        scope=args.scope,
        config_path=args.config.expanduser() if args.config else None,
        model_url=args.model_url,
        model=args.model,
        gpu_backend=args.gpu,
    )
    return wizard.run()


if __name__ == "__main__":
    sys.exit(run())
