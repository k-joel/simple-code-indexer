"""Install the tool into a uv-managed environment and build the launch command.

Every install is a ``uv tool install``: one persistent, isolated environment
under the uv tool directory, which the harness entries launch directly.

The environment root does not depend on the flavour, so the entry never changes:

- **editable** (the default from a source checkout) links the working tree into
  the environment, so edits are live without reinstalling.
- **wheel** builds and installs a wheel — from the checkout, or the pinned
  published version when there is no checkout. This is the prod-validation
  switch, and the one flavour that survives deleting the checkout.

Only ``uv-receipt.toml`` records which is installed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from simple_code_indexer.errors import ConfigError
from simple_code_indexer.setup_wizard.provision import CommandResult, Runner

TOOL_NAME = "simple-code-indexer"
TOOL_TIMEOUT_S = 900.0

# Interpreter launched by harness entries. `-m` rather than the console-script
# shim: on Windows pythonw.exe is windowless, so a GUI harness does not get a
# console window for the whole session.
ENTRY_MODULE = "simple_code_indexer"


def tool_dir(runner: Runner) -> Path | None:
    """``uv tool dir``; None when uv cannot report it."""
    uv = runner.which("uv") or "uv"
    result: CommandResult = runner.run([uv, "tool", "dir"])
    if result.returncode != 0:
        return None
    reported = result.stdout.strip().splitlines()
    if not reported:
        return None
    return Path(reported[0].strip()).expanduser()


def tool_env_root(runner: Runner) -> Path | None:
    """The installed tool environment, or None when the tool is not installed."""
    base = tool_dir(runner)
    if base is None:
        return None
    root = base / TOOL_NAME
    return root if root.is_dir() else None


def tool_bin_dir(runner: Runner) -> Path | None:
    """``uv tool dir --bin``; None when uv cannot report it."""
    uv = runner.which("uv") or "uv"
    result: CommandResult = runner.run([uv, "tool", "dir", "--bin"])
    if result.returncode != 0:
        return None
    reported = result.stdout.strip().splitlines()
    if not reported:
        return None
    return Path(reported[0].strip()).expanduser()


def entrypoint_present(runner: Runner) -> bool:
    """Whether the tool's launch shim is still in ``uv tool dir --bin``.

    An environment can be deleted by hand (or by a failed uninstall) while its
    entrypoint survives. ``uv tool list`` and ``tool_env_root`` both report
    "not installed" in that state, yet uv refuses to write over the shim
    without ``--force``, so installs must treat it as an existing tool.
    """
    bin_dir = tool_bin_dir(runner)
    if bin_dir is None or not bin_dir.is_dir():
        return False
    return any(entry.stem == TOOL_NAME for entry in bin_dir.iterdir())


def ensure_uv(runner: Runner, *, output) -> str | None:
    """Find `uv`, installing it from astral.sh when missing.

    This is the one thing the deleted `setup.py` bootstrap provided that a plain
    `uv tool install` cannot: you need uv to install uv.
    """
    found = runner.which("uv")
    if found is not None:
        return found
    output("uv was not found; installing it from astral.sh ...")
    if sys.platform == "win32":
        command = [
            "powershell",
            "-ExecutionPolicy",
            "ByPass",
            "-c",
            "irm https://astral.sh/uv/install.ps1 | iex",
        ]
    else:
        command = ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]
    if runner.run_console(command, timeout=TOOL_TIMEOUT_S) != 0:
        output(
            "The uv installer failed. Install uv manually: https://docs.astral.sh/uv/"
        )
        return None
    found = runner.which("uv")
    if found is None:
        output(
            "uv is still not on PATH; add its install directory and re-run "
            "(https://docs.astral.sh/uv/)"
        )
    return found


def install_spec(repo_root: Path | None, version: str, *, editable: bool) -> str:
    """The ``uv tool install`` target.

    Editable installs must name a directory, so they require a checkout. Without
    one — running from a published wheel — there is nothing to link and nothing
    local to build, so pin the published version.
    """
    if editable and repo_root is None:
        raise ConfigError("editable installs need a source checkout")
    if repo_root is not None:
        return str(repo_root)
    return f"{TOOL_NAME}=={version}"


def ensure_tool(
    runner: Runner,
    *,
    spec: str,
    editable: bool,
    output,
) -> Path:
    """Install (or reinstall) the tool and return its environment root.

    An existing environment is always force-reinstalled: that is what lets the
    *same* environment flip between an editable link and a built wheel without
    touching the entry path the harnesses recorded. A surviving entrypoint shim
    counts as existing too, because uv refuses to overwrite it without
    ``--force`` even when the environment itself is gone.

    ``--refresh`` applies to wheel installs only. It busts uv's local-build
    cache, which is keyed on ``pyproject.toml``/``setup.py``/``setup.cfg`` and
    the presence of ``src`` rather than on file contents, so without it a
    source-only edit can reuse a stale wheel. Editable installs write a ``.pth``
    and never build anything, so there is nothing to refresh.
    """
    uv = runner.which("uv") or "uv"
    argv = [uv, "tool", "install"]
    env_present = tool_env_root(runner) is not None
    if editable:
        argv.append("--editable")
    if env_present or entrypoint_present(runner):
        argv.append("--force")
    if env_present and not editable:
        argv.append("--refresh")
    argv.append(spec)
    output(f"Installing {spec} with uv tool ...")
    result = runner.run(argv, timeout=TOOL_TIMEOUT_S)
    if result.returncode != 0:
        for stream in (result.stdout, result.stderr):
            if stream.strip():
                output(stream.strip())
        raise ConfigError(f"uv tool install failed for {spec}")
    root = tool_env_root(runner)
    if root is None:
        raise ConfigError(f"uv tool install reported success but {TOOL_NAME} is absent")
    return root


def remove_tool(runner: Runner, output) -> bool:
    """Uninstall the tool environment; False when it was not installed."""
    if tool_env_root(runner) is None:
        return False
    uv = runner.which("uv") or "uv"
    output(f"Removing the uv tool environment for {TOOL_NAME} ...")
    result = runner.run([uv, "tool", "uninstall", TOOL_NAME], timeout=TOOL_TIMEOUT_S)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        output(
            f"uv tool uninstall failed for {TOOL_NAME}"
            + (f": {detail}" if detail else "")
        )
        return False
    return True


@dataclass(frozen=True, slots=True)
class InstallResult:
    root: Path
    platform: str = sys.platform

    @property
    def interpreter(self) -> Path:
        """The windowless interpreter a GUI harness can spawn without a console."""
        if self.platform == "win32":
            return self.root / "Scripts" / "pythonw.exe"
        return self.root / "bin" / "python"

    @property
    def server_command(self) -> list[str]:
        """Launch the MCP server, preserving the caller's cwd.

        The environment's interpreter runs the module directly, so the same argv
        works for an editable and a wheel install alike: ``-m`` rather than the
        console-script shim keeps Windows windowless.
        """
        return [str(self.interpreter), "-m", ENTRY_MODULE, "serve"]


def prune_empty_dirs(start: Path, *, stop: Path) -> list[Path]:
    """Remove `start` and its parents while empty, never at or above `stop`."""
    boundary = stop.resolve()
    current = start.resolve()
    removed: list[Path] = []
    while current != boundary and boundary in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        removed.append(current)
        current = current.parent
    return removed
