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

from simple_code_indexer import configfile
from simple_code_indexer.config import derive_collection_name
from simple_code_indexer.harnesses import HarnessSpec, load_harnesses
from simple_code_indexer.setup_wizard import catalog, probe, provision, write
from simple_code_indexer.setup_wizard.prereqs import docker_install_hint
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
        self._docker_checked: bool | None = None
        self._written_harnesses: list[tuple[HarnessSpec, Path]] = []

    def run(self) -> int:
        try:
            self._banner()
            self._step_gitignore()
            self._step_migrate_index()
            embedding = self._step_embedding()
            qdrant = self._step_qdrant()
            config_path = self._write_config(embedding, qdrant)
            self._step_harnesses()
            self._summary(embedding, qdrant, config_path)
            return 0
        except SetupAborted as exc:
            self.prompts.say(f"\nSetup aborted: {exc}")
            return 1
        except (OSError, TypeError, ValueError) as exc:
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
        labels = [model.label for model in catalog.CATALOG]
        labels.append("Cancel — I'll set up my own embedding server")
        choice = self._ask_choice(
            "No embedding server found. Auto-download a model?", labels, default=0
        )
        if choice >= len(catalog.CATALOG):
            raise SetupAborted("set up an embedding server, then re-run setup.py")
        model = catalog.CATALOG[choice]
        if self.model_url and choice == 0:
            model = replace(model, url=self.model_url)
        port = 8080 if self.dry_run else provision.available_port("127.0.0.1", 8080)
        compose_file = self.home / provision.HOME_DIRNAME / provision.COMPOSE_FILENAME
        destination = self.home / provision.HOME_DIRNAME / "models" / model.filename
        url = f"http://localhost:{port}"
        service = {
            "container": provision.EMBED_CONTAINER,
            "compose_file": str(compose_file),
            "compose_service": "embed",
            "startup_timeout_s": 60,
        }
        if self.dry_run:
            self.prompts.say(f"Would download {model.url}")
            self.prompts.say(f"Would add the 'embed' service to {compose_file}")
            return {
                "base_url": url,
                "model": model.api_model,
                "api_key": None,
                "dim": model.dim,
                "service": service,
            }
        provision.download_model(model.url, destination, output=self.prompts.say)
        provision.write_compose(
            compose_file,
            {"embed": provision.embed_service(model, port, destination.name)},
        )
        if not provision.compose_up(self.runner, compose_file, "embed"):
            raise SetupAborted("docker compose could not start the embedding container")
        if not provision.wait_until(
            lambda: probe.embedding_dim(self.http, url, model.api_model) is not None,
            timeout=180.0,
        ):
            self.prompts.say("The model is still loading; the server will wait for it.")
        dim = probe.embedding_dim(self.http, url, model.api_model) or model.dim
        return {
            "base_url": url,
            "model": model.api_model,
            "api_key": None,
            "dim": dim,
            "service": service,
        }

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
        result: dict[str, Any] = {
            "base_url": url.rstrip("/"),
            "model": model,
            "api_key": key,
            "dim": dim,
        }
        if service is not None:
            result["service"] = service
        return result

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
        compose_file = self.home / provision.HOME_DIRNAME / provision.COMPOSE_FILENAME
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

    def _write_config(self, embedding: dict[str, Any], qdrant: dict[str, Any]) -> Path:
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
        target = self.config_path or self._choose_config_path()
        if self.dry_run:
            self.prompts.say(f"Would write {target}")
        else:
            configfile.write_config(data, target)
            self.prompts.say(f"Wrote {target}")
        return target

    def _choose_config_path(self) -> Path:
        if self.scope == "global":
            return self.home / provision.HOME_DIRNAME / configfile.CONFIG_FILENAME
        if self.scope == "local":
            return self.cwd / configfile.LOCAL_DIRNAME / configfile.CONFIG_FILENAME
        default = 0 if self.cwd == self.repo_root else 1
        choice = self._ask_choice(
            "Where should config.yaml live?",
            [
                f"Global ({self.home / provision.HOME_DIRNAME})",
                f"Local ({self.cwd / configfile.LOCAL_DIRNAME})",
            ],
            default=default,
        )
        base = (
            self.home / provision.HOME_DIRNAME
            if choice == 0
            else self.cwd / configfile.LOCAL_DIRNAME
        )
        return base / configfile.CONFIG_FILENAME

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
        qdrant: dict[str, Any],
        config_path: Path,
    ) -> None:
        dim = int(embedding["dim"])
        self.prompts.say()
        self.prompts.say("Setup complete.")
        self.prompts.say(f"  config:      {config_path}")
        self.prompts.say(
            f"  index:       {self.cwd / configfile.LOCAL_DIRNAME / 'index.db'}"
        )
        self.prompts.say(
            f"  embedding:   {embedding['base_url']} "
            f"(model={embedding['model']}, dim={dim})"
        )
        self.prompts.say(f"  qdrant:      {qdrant['url']}")
        self.prompts.say(f"  collection:  {derive_collection_name(self.cwd, dim)}")
        for spec, target in self._written_harnesses:
            self.prompts.say(f"  harness:     {spec.label} -> {target}")
        self.prompts.say()
        self.prompts.say("Restart your harness to pick up the new server.")
        self.prompts.say(
            "Changing the embedding model later creates a new collection and "
            "re-indexes the workspace."
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
        "--model-url", default=None, help="override the first model URL"
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
    )
    return wizard.run()


if __name__ == "__main__":
    sys.exit(run())
