"""Interactive setup wizard (invoked by the repo-root `setup.py`).

Everything external is injectable (`prompts`, `runner`, `http`) so the tests run
hermetically: no Docker, no network, no `input()`.

One global config (`~/.simple-ci/config.yaml`) drives every workspace; the
installed copy under the per-user app directory is what harnesses launch.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from simple_code_indexer import configfile, model_prompts
from simple_code_indexer.config import (
    derive_collection_name,
    embedding_fingerprint,
)
from simple_code_indexer.errors import ConfigError
from simple_code_indexer.harnesses import HarnessSpec, load_harnesses
from simple_code_indexer.setup_wizard import (
    catalog,
    gpu,
    install,
    probe,
    provision,
    write,
)
from simple_code_indexer.setup_wizard.prereqs import gpu_runtime_hint, install_docker
from simple_code_indexer.setup_wizard.prompts import Prompter
from simple_code_indexer.workspace_lock import WorkspaceLock

SERVER_NAME = "simple-code-indexer"
DEFAULT_EMBED_URL = "http://localhost:8080"
DEFAULT_EMBED_MODEL = "Qwen3-Embedding-4B-Q6_K"
DEFAULT_EMBED_DIM = 2560
DEFAULT_STARTUP_TIMEOUT_S = 120.0


class SetupAborted(Exception):
    """A user-visible abort; `run()` converts it to exit code 1."""


@dataclass(frozen=True, slots=True)
class ExistingSetup:
    embedding: dict[str, Any]
    backend: str
    qdrant: dict[str, Any] | None


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
        config_path: Path | None = None,
        model_url: str | None = None,
        model: str | None = None,
        gpu_backend: str | None = None,
        platform: str = sys.platform,
        config_mode: str | None = None,
        vector_store: str | None = None,
        container: str | None = None,
        embedding_url: str | None = None,
        embedding_model: str | None = None,
        harnesses: str | None = None,
        install_dir: Path | None = None,
        no_install: bool = False,
    ) -> None:
        self.cwd = (cwd or Path.cwd()).resolve()
        self.home = (home or Path.home()).resolve()
        self.repo_root = (repo_root or _default_repo_root()).resolve()
        self.prompts = prompts or Prompter()
        self.runner = runner or provision.Runner()
        self.http = http or probe.Http()
        self.dry_run = dry_run
        self.assume_yes = assume_yes
        self.config_path = config_path
        self.model_url = model_url
        self.model = model
        self.gpu_backend = gpu_backend
        self.platform = platform
        self.config_mode = config_mode
        self.vector_store = vector_store
        self.container = container
        self.embedding_url = embedding_url
        self.embedding_model = embedding_model
        self.harnesses = harnesses
        self.install_dir = install_dir
        self.no_install = no_install
        self._docker_checked: bool | None = None
        self._written_harnesses: list[tuple[HarnessSpec, Path]] = []

    def run(self) -> int:
        try:
            self._banner()
            self._step_docker()
            self._step_migrate_global_assets()
            self._step_migrate_local_config()
            reused = self._step_existing_config()
            if reused is None:
                embedding = self._step_embedding()
                backend = self._step_vector_store()
                qdrant = self._step_qdrant() if backend == "qdrant" else None
            else:
                embedding = reused.embedding
                backend = reused.backend
                qdrant = reused.qdrant
            self._step_gitignore()
            self._step_migrate_index()
            config_paths = self._write_global_config(embedding, backend, qdrant)
            install_result = self._step_install()
            self._step_harnesses(install_result)
            self._summary(embedding, backend, qdrant, config_paths, install_result)
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
        self,
        question: str,
        options: list[str],
        *,
        default: int = 0,
        search: bool = False,
    ) -> int:
        if self.assume_yes:
            return default
        return self.prompts.ask_choice(
            question, options, default=default, search=search
        )

    def _ask_text(
        self,
        question: str,
        *,
        default: str | None = None,
        allow_empty: bool = False,
        secret: bool = False,
    ) -> str:
        if self.assume_yes and default is not None:
            return default
        return self.prompts.ask_text(
            question,
            default=default,
            allow_empty=allow_empty,
            secret=secret,
        )

    def _ask_multi(
        self,
        question: str,
        options: list[str],
        *,
        default: list[int],
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

    def _step_docker(self) -> bool:
        if self.dry_run:
            self.prompts.say("Would check Docker and offer to install it when missing.")
            return True
        if provision.docker_available(self.runner):
            self._docker_checked = True
            return True
        if self.runner.which("docker") is not None:
            self.prompts.say("Docker is installed, but its daemon is not running.")
            if self._ask_yes_no("Start Docker now?", default=True):
                provision.start_docker_daemon(self.runner, platform=self.platform)
                self.prompts.say("Waiting for Docker to become ready ...")
                provision.wait_until(
                    lambda: provision.docker_available(self.runner), timeout=120.0
                )
            if provision.docker_available(self.runner):
                self._docker_checked = True
                return True
            self.prompts.say(
                "Docker is still unavailable; continuing without it. Start Docker "
                "and re-run setup.py to use Docker-backed services."
            )
            self._docker_checked = False
            return False
        self.prompts.say("Docker is not installed.")
        if not self._ask_yes_no("Install Docker now?", default=True):
            self.prompts.say(
                "Continuing without Docker; only an existing embedding server URL "
                "can be used."
            )
            self._docker_checked = False
            return False
        if install_docker(self.runner, platform=self.platform, output=self.prompts.say):
            self.prompts.say("Waiting for Docker to become ready ...")
            provision.wait_until(
                lambda: provision.docker_available(self.runner), timeout=180.0
            )
        self._docker_checked = provision.docker_available(self.runner)
        if not self._docker_checked:
            self.prompts.say(
                "Docker is still unavailable. Install it later and re-run setup.py "
                "to use Docker-backed services."
            )
        return self._docker_checked

    def _docker_ready(self) -> bool:
        if self._docker_checked is None:
            self._docker_checked = provision.docker_available(self.runner)
        if not self._docker_checked:
            self.prompts.say("Docker is unavailable; skipping Docker-backed options.")
        return self._docker_checked

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

    def _step_migrate_local_config(self) -> None:
        if self.config_path is not None:
            return
        local = self.cwd / configfile.LOCAL_DIRNAME / configfile.CONFIG_FILENAME
        if not local.is_file():
            return
        self.prompts.say(f"Found a legacy project config: {local}")
        if not self._ask_yes_no(
            "Move it into the global config and remove the local file?", default=True
        ):
            self.prompts.say(
                "Leaving it in place; the server ignores project-local configs now."
            )
            return
        try:
            local_raw = configfile.load_config(local)
        except ConfigError as exc:
            self.prompts.say(f"Could not read {local}: {exc}")
            return
        global_path = self._global_config_path()
        global_raw: dict[str, Any] = {}
        if global_path.is_file():
            try:
                global_raw = configfile.load_config(global_path)
            except ConfigError:
                global_raw = {}
        merged = configfile.merge_configs(global_raw, local_raw)
        if self.dry_run:
            self.prompts.say(
                f"Would merge {local} into {global_path} and delete the local file"
            )
            return
        configfile.write_config(merged, global_path)
        local.unlink()
        self.prompts.say(f"Merged into {global_path} and removed {local}")

    def _step_existing_config(self) -> ExistingSetup | None:
        if self.config_path is not None and not self.config_path.is_file():
            return None
        if (
            self.model is not None
            or self.container is not None
            or self.embedding_url is not None
        ):
            return None
        path = self.config_path or self._global_config_path()
        if not path.is_file():
            return None
        try:
            raw = configfile.load_config(path)
            embedding = configfile.get_mapping(raw, "embedding")
            base_url = configfile.get_str(embedding, "base_url", where="embedding")
            model = configfile.get_str(embedding, "model", where="embedding")
            dim = configfile.get_int(embedding, "dim", where="embedding") or 0
            api_key = configfile.get_str(embedding, "api_key", where="embedding")
            service_raw = configfile.get_mapping(embedding, "service")
            setup = configfile.get_mapping(raw, "setup")
            backend = self._vector_store_from_raw(raw)
            qdrant_raw = configfile.get_mapping(raw, "qdrant")
        except ConfigError as exc:
            self.prompts.say(f"Could not read {path}: {exc}")
            if self._ask_yes_no("Reconfigure from scratch?", default=True):
                return None
            raise SetupAborted(str(exc)) from exc
        if base_url is None or model is None:
            self.prompts.say(f"{path} has no embedding.base_url/model; reconfiguring.")
            return None
        self.prompts.say(f"Global config: {path}")
        self.prompts.say(f"  embedding:    {model} ({dim or '?'}-dim) at {base_url}")
        self.prompts.say(f"  vector store: {backend}")
        if service_raw.get("container"):
            self.prompts.say(f"  container:    {service_raw['container']}")
        choice = 0
        if self.config_mode is None:
            while True:
                choice = self._ask_choice(
                    "A global config already exists. What should I do?",
                    [
                        "Use the existing settings and continue",
                        "Reconfigure embedding and vector store",
                        "Show the config file",
                        "Cancel",
                    ],
                    default=0,
                )
                if choice == 2:
                    self.prompts.say(path.read_text(encoding="utf-8"))
                    continue
                break
        elif self.config_mode == "reconfigure":
            choice = 1
        if choice == 3:
            raise SetupAborted("user cancelled")
        if choice == 1:
            return None
        default_query, default_document = model_prompts.defaults_for_model(model)
        result: dict[str, Any] = {
            "base_url": base_url.rstrip("/"),
            "model": model,
            "dim": dim,
            "api_key": api_key or None,
            "query_prefix": _stored_prompt(embedding, "query_prefix", default_query),
            "document_prefix": _stored_prompt(
                embedding, "document_prefix", default_document
            ),
            "service": dict(service_raw) if service_raw else None,
            "model_key": configfile.get_str(setup, "model_key", where="setup"),
            "model_file": configfile.get_str(setup, "model_file", where="setup"),
            "gpu": configfile.get_str(setup, "gpu", where="setup"),
        }
        qdrant_value: dict[str, Any] | None = None
        if backend == "qdrant":
            qdrant_value = dict(qdrant_raw)
            qdrant_value.setdefault("url", "http://localhost:6333")
        if self.dry_run:
            self.prompts.say(f"Would reuse {base_url} ({model}).")
            return ExistingSetup(result, backend, qdrant_value)
        probed = probe.embedding_dim(self.http, base_url, model, result["api_key"])
        if probed is None and service_raw.get("container"):
            container = str(service_raw["container"])
            self.prompts.say(f"{base_url} is not answering; starting {container}.")
            provision.start_container(self.runner, container)
            provision.wait_until(
                lambda: (
                    probe.embedding_dim(self.http, base_url, model, result["api_key"])
                    is not None
                ),
                timeout=180.0,
            )
            probed = probe.embedding_dim(self.http, base_url, model, result["api_key"])
        if probed is None:
            if not self._ask_yes_no(
                f"{base_url} did not answer. Continue with these settings anyway?",
                default=True,
            ):
                return None
            self.prompts.say("Keeping the settings; the server retries when it starts.")
            if result["dim"] <= 0:
                result["dim"] = DEFAULT_EMBED_DIM
        else:
            result["dim"] = probed
            self.prompts.say(f"Reusing the global embedding setup at {base_url}.")
        return ExistingSetup(result, backend, qdrant_value)

    # -- embedding -------------------------------------------------------

    def _step_embedding(self) -> dict[str, Any]:
        if self.embedding_url is not None:
            return self._embedding_from_url(self.embedding_url)
        if self.container is not None:
            return self._embedding_from_named_container(self.container)
        if self.model is not None:
            return self._embedding_auto()
        kind, value = self._embedding_menu()
        if kind == "cancel":
            raise SetupAborted("no embedding model selected")
        if kind == "running":
            url, model = value
            return self._embedding_from_url(url, default_model=model)
        if kind == "container":
            return self._embedding_from_container(value)
        if kind == "gguf":
            return self._embedding_from_gguf(value)
        if kind == "download":
            return self._embedding_auto()
        return self._embedding_from_url()

    def _embedding_menu(self) -> tuple[str, Any]:
        options: list[tuple[str, Any]] = []
        labels: list[str] = []
        if not self.dry_run:
            models = probe.list_models(self.http, DEFAULT_EMBED_URL)
            if models:
                options.append(("running", (DEFAULT_EMBED_URL, models[0])))
                labels.append(
                    f"Use the running server at {DEFAULT_EMBED_URL} ({models[0]})"
                )
        if self._docker_ready():
            for container in provision.list_embedding_containers(
                self.runner, self.http
            ):
                options.append(("container", container))
                state = "running" if container.running else container.status
                model = container.models[0] if container.models else "model unknown"
                labels.append(
                    f"Container {container.name} — {container.image} — "
                    f"{state} — {model}"
                )
            for path in provision.downloaded_models(self.home):
                options.append(("gguf", path))
                labels.append(
                    f"Downloaded model {path.name} "
                    f"({path.stat().st_size / 1e9:.1f} GB) — create a container"
                )
            options.append(("download", None))
            labels.append("Download a model (EmbeddingGemma 2, Qwen3-0.6B, Nomic Code)")
        options.append(("url", None))
        labels.append("Use an existing embedding server URL")
        options.append(("cancel", None))
        labels.append("Cancel")
        index = self._ask_choice(
            "How should semantic search get its embeddings?",
            labels,
            default=0,
            search=True,
        )
        return options[index]

    def _embedding_from_url(
        self, url: str | None = None, *, default_model: str | None = None
    ) -> dict[str, Any]:
        target = url or DEFAULT_EMBED_URL
        while True:
            chosen = (
                target
                if url is not None
                else self._ask_text("Embedding base URL", default=target)
            )
            result = self._configure_embedding(
                chosen,
                ask_key=True,
                default_model=default_model
                or self.embedding_model
                or DEFAULT_EMBED_MODEL,
            )
            if result is not None:
                return result
            self.prompts.say(f"Could not read an embedding vector from {chosen}.")
            if url is not None:
                raise SetupAborted(f"{chosen} did not answer as an embedding server")
            if not self._ask_yes_no("Try a different URL?", default=True):
                raise SetupAborted("no working embedding endpoint")
            target = chosen

    def _embedding_from_named_container(self, name: str) -> dict[str, Any]:
        if not self._docker_ready():
            raise SetupAborted("Docker is required to use a container")
        containers = provision.list_containers(self.runner)
        container = next((item for item in containers if item.name == name), None)
        if container is None:
            container = next(
                (item for item in containers if item.name.startswith(name)), None
            )
        if container is None:
            raise SetupAborted(f"container {name!r} was not found")
        return self._embedding_from_container(
            provision.EmbeddingContainer(
                name=container.name,
                image=container.image,
                status=container.status,
                url=provision.container_url(
                    self.runner, container.name, provision.EMBED_PORTS
                ),
            )
        )

    def _embedding_from_container(
        self, container: provision.EmbeddingContainer
    ) -> dict[str, Any]:
        if (
            not container.running
            and not self.dry_run
            and not provision.start_container(self.runner, container.name)
        ):
            raise SetupAborted(f"could not start {container.name}")
        url = (
            provision.container_url(self.runner, container.name, provision.EMBED_PORTS)
            or container.url
        )
        if url is None:
            url = self._ask_text(
                "No published embedding port found; enter its URL",
                default=DEFAULT_EMBED_URL,
            )
        model = self.embedding_model
        if model is None and not self.dry_run:
            provision.wait_until(
                lambda: bool(probe.list_models(self.http, url)), timeout=120.0
            )
            models = probe.list_models(self.http, url)
            model = models[0] if models else None
        model = model or DEFAULT_EMBED_MODEL
        if not self.dry_run:
            pooling = provision.container_env(self.runner, container.name).get(
                "LLAMA_ARG_POOLING"
            )
            if pooling and "qwen3" in model.lower() and pooling != "last":
                self.prompts.say(
                    f"Warning: {container.name} uses {pooling} pooling, but "
                    "Qwen3-Embedding is trained for last-token pooling; retrieval "
                    "quality may be poor. Recreate it with LLAMA_ARG_POOLING=last."
                )
        if self.dry_run:
            dim = DEFAULT_EMBED_DIM
        else:
            provision.wait_until(
                lambda: probe.embedding_dim(self.http, url, model) is not None,
                timeout=DEFAULT_STARTUP_TIMEOUT_S,
            )
            dim = probe.embedding_dim(self.http, url, model)
        if dim is None:
            raise SetupAborted(
                f"{container.name} did not answer as an embedding server at {url}"
            )
        compose_file = provision.compose_path(self.home)
        service = provision.existing_service(
            container.name,
            compose_file=compose_file,
            compose_service=provision.compose_service_for_container(
                compose_file, container.name
            ),
            startup_timeout_s=DEFAULT_STARTUP_TIMEOUT_S,
        )
        self.prompts.say(f"Using {container.name} at {url} (model={model}, dim={dim})")
        return self._embedding_result(url, model, dim, service=service)

    def _embedding_from_gguf(self, path: Path) -> dict[str, Any]:
        model = catalog.for_filename(path.name)
        if model is None:
            api_model = self.embedding_model or self._ask_text(
                "Model name served by llama.cpp", default=path.stem
            )
            model = catalog.EmbeddingModel(
                key=path.stem,
                label=path.name,
                url="",
                filename=path.name,
                api_model=api_model,
                dim=DEFAULT_EMBED_DIM,
                pooling="last",
                approx_gb=path.stat().st_size / 1e9,
            )
        elif self.embedding_model:
            model = replace(model, api_model=self.embedding_model)
        return self._provision_embedding(model, path, download=False)

    def _embedding_auto(self) -> dict[str, Any]:
        if self.model is not None:
            model = catalog.for_key(self.model)
            if model is None:
                raise SetupAborted(f"unknown embedding model {self.model!r}")
            if self.model_url:
                model = replace(model, url=self.model_url)
        else:
            labels = [
                f"{item.label} — {item.approx_gb:.1f} GB" for item in catalog.CATALOG
            ]
            labels.append("Cancel — I'll set up my own embedding server")
            choice = self._ask_choice(
                "Download an embedding model", labels, default=0, search=True
            )
            if choice >= len(catalog.CATALOG):
                raise SetupAborted("set up an embedding server, then re-run setup.py")
            model = catalog.CATALOG[choice]
            if self.model_url and choice == 0:
                model = replace(model, url=self.model_url)
        destination = provision.model_dir(self.home) / model.filename
        return self._provision_embedding(model, destination, download=True)

    def _provision_embedding(
        self, model: catalog.EmbeddingModel, destination: Path, *, download: bool
    ) -> dict[str, Any]:
        if not self._docker_ready():
            raise SetupAborted("Docker is required to run a downloaded embedding model")
        gpu_info = self._resolve_gpu()
        port = 8080 if self.dry_run else self._embed_port()
        compose_file = provision.compose_path(self.home)
        url = f"http://localhost:{port}"
        service = {
            "container": provision.EMBED_CONTAINER,
            "compose_file": str(compose_file),
            "compose_service": "embed",
            "startup_timeout_s": DEFAULT_STARTUP_TIMEOUT_S,
        }
        result = self._embedding_result(
            url,
            model.api_model,
            model.dim,
            service=service,
            model_key=model.key,
            model_file=str(destination),
            gpu_vendor=gpu_info.vendor,
            query_prefix=model.query_prefix,
            document_prefix=model.document_prefix,
        )
        if self.dry_run:
            if download:
                self.prompts.say(f"Would download {model.url}")
            self.prompts.say(f"Would add the 'embed' service to {compose_file}")
            return result
        if download:
            provision.download_model(model.url, destination, output=self.prompts.say)
        elif not destination.is_file():
            raise SetupAborted(f"{destination} does not exist")
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
            timeout=300.0,
        ):
            self.prompts.say("The model is still loading; the server will wait for it.")
        probed = probe.embedding_dim(self.http, url, model.api_model)
        result["dim"] = probed or model.dim
        return result

    def _embedding_result(
        self,
        base_url: str,
        model: str,
        dim: int,
        *,
        service: dict[str, Any] | None = None,
        model_key: str | None = None,
        model_file: str | None = None,
        gpu_vendor: str | None = None,
        query_prefix: str | None = None,
        document_prefix: str | None = None,
    ) -> dict[str, Any]:
        if query_prefix is None and document_prefix is None:
            query_prefix, document_prefix = model_prompts.defaults_for_model(model)
        result: dict[str, Any] = {
            "base_url": base_url.rstrip("/"),
            "model": model,
            "dim": dim,
            "api_key": None,
            "query_prefix": query_prefix,
            "document_prefix": document_prefix,
        }
        if service:
            result["service"] = service
        if model_key:
            result["model_key"] = model_key
        if model_file:
            result["model_file"] = model_file
        if gpu_vendor:
            result["gpu"] = gpu_vendor
        return result

    def _embed_port(self) -> int:
        """Keep the running container's published port so re-runs don't churn."""
        url = provision.container_url(self.runner, provision.EMBED_CONTAINER)
        if url is not None:
            _, _, published = url.rpartition(":")
            if published.isdigit():
                return int(published)
        return provision.available_port("127.0.0.1", 8080)

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
                    secret=True,
                )
                or None
            )
        models = [] if self.dry_run else probe.list_models(self.http, url, key)
        if models:
            self.prompts.say("Detected models: " + ", ".join(models))
        if self.embedding_model:
            model = self.embedding_model
        else:
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
        result = self._embedding_result(url, model, dim, service=service)
        result["api_key"] = key
        return result

    # -- vector store ----------------------------------------------------

    def _vector_store_from_raw(self, raw: dict[str, Any]) -> str:
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

    def _existing_vector_store(self) -> str:
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
        return self._vector_store_from_raw(raw)

    def _step_vector_store(self) -> str:
        if self.vector_store is not None:
            return self.vector_store
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
        if not self._docker_ready():
            url = self._ask_text("Qdrant URL", default="http://localhost:6333")
            return self._qdrant_result(url)
        options: list[tuple[str, Any]] = []
        labels: list[str] = []
        for container in provision.find_qdrant_containers(self.runner):
            options.append(("container", container))
            labels.append(
                f"Use the existing container {container.name} — "
                f"{container.image} ({container.status})"
            )
        options.append(("compose", None))
        labels.append("Set up Qdrant automatically with Docker")
        options.append(("url", None))
        labels.append("Use an existing Qdrant URL")
        index = self._ask_choice(
            "How should Qdrant run?", labels, default=0, search=True
        )
        kind, value = options[index]
        if kind == "container":
            return self._qdrant_from_container(value)
        if kind == "compose":
            return self._qdrant_auto()
        url = self._ask_text("Qdrant URL", default="http://localhost:6333")
        return self._qdrant_result(url)

    def _qdrant_from_container(self, container: provision.Container) -> dict[str, Any]:
        if (
            not container.running
            and not self.dry_run
            and not provision.start_container(self.runner, container.name)
        ):
            self.prompts.say(f"Could not start {container.name}.")
        url = provision.container_url(self.runner, container.name, ports=(6333,))
        if url is None:
            url = self._ask_text(
                "No published Qdrant port found; enter its URL",
                default="http://localhost:6333",
            )
        if not self.dry_run:
            provision.wait_until(
                lambda: probe.qdrant_ready(self.http, url), timeout=120.0
            )
        compose_file = provision.compose_path(self.home)
        service = provision.existing_service(
            container.name,
            compose_file=compose_file,
            compose_service=provision.compose_service_for_container(
                compose_file, container.name
            ),
            startup_timeout_s=DEFAULT_STARTUP_TIMEOUT_S,
        )
        return self._qdrant_result(url, service)

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
            "startup_timeout_s": DEFAULT_STARTUP_TIMEOUT_S,
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

    # -- workspace hygiene ----------------------------------------------

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

    # -- config ----------------------------------------------------------

    def _write_global_config(
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
        document: dict[str, Any] = {
            "version": configfile.CONFIG_VERSION,
            "vector_store": backend,
            "sweep_seconds": 45,
            "debounce_ms": 400,
            "embedding": embedding_section,
        }
        setup: dict[str, Any] = {}
        for key in ("model_key", "model_file", "gpu"):
            if embedding.get(key):
                setup[key] = embedding[key]
        if setup:
            document["setup"] = setup
        if backend == "qdrant":
            assert qdrant is not None
            document["qdrant"] = {"url": qdrant["url"]}
            if qdrant.get("service"):
                document["qdrant"]["service"] = qdrant["service"]
        target = self.config_path or self._global_config_path()
        return (self._write_one(target, document),)

    def _write_one(self, target: Path, data: dict[str, Any]) -> Path:
        if self.dry_run:
            self.prompts.say(f"Would write {target}")
        else:
            configfile.write_config(data, target)
            self.prompts.say(f"Wrote {target}")
        return target

    def _global_config_path(self) -> Path:
        return configfile.global_config_path(self.home)

    # -- install ---------------------------------------------------------

    def _step_install(self) -> install.InstallResult:
        if self.no_install:
            python = install.existing_python(
                self.repo_root,
                platform=self.platform,
                fallback=Path(sys.executable),
            )
            result = install.InstallResult(
                root=self.repo_root,
                python=python,
                launcher=self.repo_root / install.LAUNCHER_FILENAME,
            )
            self.prompts.say(f"Using the source checkout: {self.repo_root}")
            return result
        target = (
            self.install_dir.expanduser().resolve()
            if self.install_dir is not None
            else install.install_root(home=self.home, platform=self.platform)
        )
        if target == self.repo_root:
            python = install.existing_python(
                self.repo_root,
                platform=self.platform,
                fallback=Path(sys.executable),
            )
            self.prompts.say(f"Already running from the install directory: {target}")
            return install.InstallResult(
                root=target,
                python=python,
                launcher=target / install.LAUNCHER_FILENAME,
            )
        self.prompts.say(f"Installing to {target} ...")
        if self.dry_run:
            self.prompts.say(f"Would copy {self.repo_root} to {target}")
            self.prompts.say(f"Would run uv sync --project {target}")
        else:
            install.copy_repo(self.repo_root, target)
            if not install.sync_env(self.runner, target, self.prompts.say):
                raise SetupAborted(f"uv sync failed in {target}")
        result = install.InstallResult(
            root=target,
            python=install.venv_python(target, platform=self.platform),
            launcher=target / install.LAUNCHER_FILENAME,
        )
        self.prompts.say(f"Installed: {target}")
        return result

    # -- harnesses -------------------------------------------------------

    def _step_harnesses(self, install_result: install.InstallResult) -> None:
        specs = load_harnesses()
        if not specs:
            self.prompts.say("No harness plugins found.")
            return
        detected = [
            index for index, spec in enumerate(specs) if spec.detected(self.home)
        ]
        if self.harnesses is not None:
            selected = self._parse_harness_selection(self.harnesses, specs)
        else:
            labels = [
                f"{spec.label} ({spec.name})"
                + (" — detected" if index in detected else "")
                for index, spec in enumerate(specs)
            ]
            selected = self._ask_multi(
                "Install the MCP server for which harnesses?",
                labels,
                default=detected,
            )
        command = install_result.server_command
        written: dict[Path, HarnessSpec] = {}
        for index in selected:
            spec = specs[index]
            target = write.choose_target(spec, "global", self.cwd, self.home)
            if target is None:
                self.prompts.say(f"{spec.label} has no global config path.")
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

    def _parse_harness_selection(
        self, value: str, specs: list[HarnessSpec]
    ) -> list[int]:
        normalized = value.strip().lower()
        if normalized == "none":
            return []
        if normalized == "all":
            return list(range(len(specs)))
        names = [name.strip() for name in normalized.split(",") if name.strip()]
        by_name = {spec.name: index for index, spec in enumerate(specs)}
        unknown = [name for name in names if name not in by_name]
        if unknown:
            raise SetupAborted("unknown harness(es): " + ", ".join(unknown))
        return sorted({by_name[name] for name in names})

    # -- summary ---------------------------------------------------------

    def _summary(
        self,
        embedding: dict[str, Any],
        backend: str,
        qdrant: dict[str, Any] | None,
        config_paths: tuple[Path, ...],
        install_result: install.InstallResult,
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
        self.prompts.say(f"  install:      {install_result.root}")
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
    parser.add_argument("--scope", default=None, help=argparse.SUPPRESS)
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
    parser.add_argument(
        "--vector-store",
        choices=["faiss", "qdrant"],
        default=None,
        help="force the semantic backend",
    )
    parser.add_argument(
        "--container",
        default=None,
        help="use this existing Docker container for embeddings",
    )
    parser.add_argument(
        "--embedding-url",
        default=None,
        help="use this existing embedding server URL",
    )
    parser.add_argument(
        "--embedding-model",
        default=None,
        help="override the served embedding model name",
    )
    parser.add_argument(
        "--config-mode",
        choices=["use", "reconfigure"],
        default=None,
        help="answer the existing-global-config prompt",
    )
    parser.add_argument(
        "--harnesses",
        default=None,
        help="'all', 'none', or a comma-separated list of harness names",
    )
    parser.add_argument(
        "--install-dir",
        type=Path,
        default=None,
        help="override the per-user install directory",
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="point harness entries at this checkout instead of copying it",
    )
    args = parser.parse_args(argv)
    if args.scope is not None:
        parser.error(
            "--scope was removed: configuration is always global "
            "(~/.simple-ci/config.yaml)"
        )
    wizard = Wizard(
        cwd=Path.cwd(),
        repo_root=args.repo_root,
        dry_run=args.dry_run,
        assume_yes=args.yes,
        config_path=args.config.expanduser() if args.config else None,
        model_url=args.model_url,
        model=args.model,
        gpu_backend=args.gpu,
        config_mode=args.config_mode,
        vector_store=args.vector_store,
        container=args.container,
        embedding_url=args.embedding_url,
        embedding_model=args.embedding_model,
        harnesses=args.harnesses,
        install_dir=args.install_dir,
        no_install=args.no_install,
    )
    return wizard.run()


if __name__ == "__main__":
    sys.exit(run())
