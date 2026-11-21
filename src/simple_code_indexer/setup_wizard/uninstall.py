"""Uninstall: reverse a setup run from the record the wizard wrote.

`~/.simple-ci/config.yaml` keeps every harness config that received the
`simple-code-indexer` entry. Removal is record-driven: a harness whose config was
never recorded stays untouched.

The workspace is never touched — `<project>/.simple-ci/` (index and vectors) is
per-workspace state the server manages, not part of the install.
"""

from __future__ import annotations

import logging
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from simple_code_indexer import configfile
from simple_code_indexer.errors import ConfigError
from simple_code_indexer.harnesses import load_harnesses
from simple_code_indexer.setup_wizard import install, provision, write
from simple_code_indexer.setup_wizard.prompts import Prompter
from simple_code_indexer.setup_wizard.provision import Runner

logger = logging.getLogger(__name__)

DEFAULT_SERVER_NAME = "simple-code-indexer"


@dataclass(frozen=True, slots=True)
class HarnessRecord:
    name: str
    config: Path


@dataclass(frozen=True, slots=True)
class InstallRecord:
    harnesses: tuple[HarnessRecord, ...] = ()


def read_record(config_path: Path) -> InstallRecord:
    """Parse the wizard bookkeeping; malformed or missing keys are `()`."""
    if not config_path.is_file():
        return InstallRecord()
    try:
        raw = configfile.load_config(config_path)
        setup = configfile.get_mapping(raw, "setup")
    except ConfigError:
        return InstallRecord()
    harnesses: list[HarnessRecord] = []
    items = setup.get("harnesses")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            config = item.get("config")
            if isinstance(name, str) and isinstance(config, str) and name and config:
                harnesses.append(HarnessRecord(name, Path(config).expanduser()))
    return InstallRecord(tuple(harnesses))


class Uninstaller:
    def __init__(
        self,
        *,
        home: Path | None = None,
        prompts: Prompter | None = None,
        runner: Runner | None = None,
        platform: str = sys.platform,
        config_path: Path | None = None,
        keep_models: bool = False,
        dry_run: bool = False,
        assume_yes: bool = False,
        server_name: str = DEFAULT_SERVER_NAME,
    ) -> None:
        self.home = (home or Path.home()).resolve()
        self.prompts = prompts or Prompter()
        self.runner = runner or Runner()
        self.platform = platform
        self.config_path = config_path
        self.keep_models = keep_models
        self.dry_run = dry_run
        self.assume_yes = assume_yes
        self.server_name = server_name
        self._failures = 0

    def run(self) -> int:
        try:
            return self._run()
        except (ConfigError, OSError, TypeError, ValueError) as exc:
            self.prompts.say(f"\nUninstall failed: {exc}")
            return 1
        except KeyboardInterrupt:
            self.prompts.say("\nCancelled.")
            return 130

    # -- flow ------------------------------------------------------------

    def _run(self) -> int:
        config_path = self.config_path or configfile.global_config_path(self.home)
        self.prompts.say("simple-code-indexer uninstall")
        self.prompts.say(f"  home:   {self.home}")
        self.prompts.say(f"  config: {config_path}")
        if self.dry_run:
            self.prompts.say("  dry run: nothing will be deleted")
        self.prompts.say()

        record = read_record(config_path)
        compose_file = provision.compose_path(self.home)
        docker_dir = provision.global_dir(self.home) / provision.GLOBAL_DOCKER_DIRNAME
        model_dir = provision.model_dir(self.home)

        plan = self._plan(
            config_path=config_path,
            compose_file=compose_file,
            docker_dir=docker_dir,
            model_dir=model_dir,
            record=record,
        )
        if not plan:
            self.prompts.say("Nothing to remove.")
            return 0
        for line in plan:
            self.prompts.say(f"  - {line}")
        self.prompts.say()
        if self.dry_run:
            self.prompts.say("Dry run: nothing was deleted.")
            return 0
        if not self.assume_yes and not self.prompts.ask_yes_no(
            "Remove simple-code-indexer from this machine?", default=True
        ):
            self.prompts.say("Cancelled.")
            return 0

        harness_failures = self._remove_harnesses(record)
        self._compose_down(compose_file)
        install.remove_tool(self.runner, self.prompts.say)
        if harness_failures:
            self.prompts.say(
                f"Keeping {config_path} so a re-run can retry the harness edits."
            )
        else:
            self._delete_file(config_path, "config")
        self._delete_tree(docker_dir, "docker assets")
        if self.keep_models:
            if model_dir.is_dir():
                self.prompts.say(f"Kept the model cache: {model_dir}")
        else:
            self._delete_tree(model_dir, "model cache")
        self._prune_global()

        self.prompts.say()
        if self._failures:
            self.prompts.say(f"Uninstall finished with {self._failures} failure(s).")
            return 1
        self.prompts.say("Uninstalled. Restart your harnesses to drop the server.")
        return 0

    def _plan(
        self,
        *,
        config_path: Path,
        compose_file: Path,
        docker_dir: Path,
        model_dir: Path,
        record: InstallRecord,
    ) -> list[str]:
        plan: list[str] = []
        specs = {spec.name: spec for spec in load_harnesses()}
        for item in record.harnesses:
            if item.name not in specs:
                plan.append(
                    f"{item.name}: harness plugin not found; leaving {item.config} alone"
                )
            elif item.config.is_file():
                plan.append(f"remove the MCP entry from {item.config} ({item.name})")
        if compose_file.is_file():
            plan.append(f"stop the compose services from {compose_file}")
        if install.tool_env_root(self.runner) is not None:
            plan.append(f"remove the uv tool environment ({install.TOOL_NAME})")
        if config_path.is_file():
            plan.append(f"delete {config_path}")
        if docker_dir.is_dir():
            plan.append(f"delete {docker_dir}")
        if model_dir.is_dir():
            if self.keep_models:
                plan.append(f"keep the model cache {model_dir}")
            else:
                plan.append(f"delete the model cache {model_dir}")
        return plan

    # -- steps -----------------------------------------------------------

    def _remove_harnesses(self, record: InstallRecord) -> int:
        """Remove the recorded entries; returns how many edits failed."""
        failures = 0
        specs = {spec.name: spec for spec in load_harnesses()}
        for item in record.harnesses:
            spec = specs.get(item.name)
            if spec is None:
                self.prompts.say(
                    f"{item.name}: harness plugin not found; leaving {item.config} alone."
                )
                continue
            target = item.config
            if not target.is_file():
                self.prompts.say(f"{item.name}: {target} is gone already.")
                continue
            try:
                removed = write.remove(spec, target, self.server_name)
            except (TypeError, ValueError, OSError) as exc:
                self.prompts.say(f"Could not update {target}: {exc}")
                self._failures += 1
                failures += 1
                continue
            write.remove_backups(target)
            if not removed:
                self.prompts.say(f"No MCP entry in {target}")
                continue
            install.prune_empty_dirs(target.parent, stop=self.home)
            self.prompts.say(f"Removed the MCP entry from {target}")
        return failures

    def _compose_down(self, compose_file: Path) -> None:
        if not compose_file.is_file():
            return
        if not provision.docker_available(self.runner):
            self.prompts.say(
                "Docker is not running; leaving the containers alone "
                "(delete them by hand if they still run)."
            )
            return
        ok, detail = provision.compose_down(self.runner, compose_file)
        if ok:
            self.prompts.say("Stopped the compose services.")
        else:
            self.prompts.say(
                "Docker could not stop the compose services"
                + (f": {detail}" if detail else "")
            )

    def _delete_tree(self, path: Path | None, label: str) -> None:
        if path is None or not path.is_dir():
            return
        try:
            shutil.rmtree(path)
        except OSError as exc:
            self.prompts.say(f"Could not delete the {label} ({path}): {exc}")
            self._failures += 1
            return
        self.prompts.say(f"Deleted the {label}: {path}")

    def _delete_file(self, path: Path, label: str) -> None:
        if not path.is_file():
            return
        try:
            path.unlink()
        except OSError as exc:
            self.prompts.say(f"Could not delete the {label} ({path}): {exc}")
            self._failures += 1
            return
        self.prompts.say(f"Deleted the {label}: {path}")

    def _prune_global(self) -> None:
        global_dir = provision.global_dir(self.home)
        model_dir = global_dir / provision.GLOBAL_MODEL_DIRNAME
        if self.keep_models and model_dir.is_dir():
            return
        try:
            global_dir.rmdir()
        except OSError:
            return
        self.prompts.say(f"Deleted {global_dir}")
