#!/usr/bin/env python3
"""Interactive setup launcher for simple-code-indexer.

This is NOT a setuptools script: packaging is configured in pyproject.toml with
the uv_build backend, which ignores this file. Run it after cloning the repo:

    python setup.py
    python setup.py --dry-run

It installs uv when missing, syncs the project environment, then hands over to
`simple_code_indexer.setup_wizard` while preserving the caller's working
directory (the project the wizard configures).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 9)

USAGE = """\
Usage: python setup.py [--dry-run] [--yes] [--scope global|local]
                       [--config PATH] [--model KEY] [--model-url URL]
                       [--gpu auto|nvidia|amd|intel|cpu]

  --dry-run     show every action without writing files or starting containers
  --yes         accept the recommended default for every prompt
  --scope       write only the global or only the local config.yaml
  --config      write one combined config.yaml at this path
  --model       download this embedding model without asking
  --model-url   override the chosen model's download URL
  --gpu         override GPU detection for the container image
"""


def _uv_candidates() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "uv.exe",
        home / ".local" / "bin" / "uv",
        home / ".cargo" / "bin" / "uv.exe",
        home / ".cargo" / "bin" / "uv",
    ]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "uv" / "uv.exe")
    return candidates


def _find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    for candidate in _uv_candidates():
        if candidate.is_file():
            return str(candidate)
    return None


def _install_uv() -> str | None:
    print("uv was not found; installing it from astral.sh ...")
    if os.name == "nt":
        command = [
            "powershell",
            "-ExecutionPolicy",
            "ByPass",
            "-c",
            "irm https://astral.sh/uv/install.ps1 | iex",
        ]
    else:
        command = ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]
    try:
        result = subprocess.call(command)
    except OSError as exc:
        print(f"Could not run the uv installer: {exc}")
        return None
    if result != 0:
        print(
            "The uv installer failed. Install uv manually: https://docs.astral.sh/uv/"
        )
        return None
    found = _find_uv()
    if found:
        os.environ["PATH"] = (
            str(Path(found).parent) + os.pathsep + os.environ.get("PATH", "")
        )
    return found


def _venv_python() -> Path:
    if os.name == "nt":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def main(argv: list[str]) -> int:
    if any(argument in ("-h", "--help") for argument in argv):
        print(__doc__ or "")
        print(USAGE)
        return 0
    if sys.version_info < MIN_PYTHON:
        print(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required.")
        return 1
    uv = _find_uv() or _install_uv()
    if uv is None:
        return 1
    print(f"Using uv: {uv}")
    print(f"Syncing {ROOT} ...")
    synced = subprocess.run(
        [uv, "sync", "--project", str(ROOT)], check=False, cwd=str(ROOT)
    )
    if synced.returncode != 0:
        print("uv sync failed; fix the error above and re-run setup.py.")
        return synced.returncode
    python = _venv_python()
    if not python.is_file():
        print(f"Expected the project virtualenv at {python} after uv sync.")
        return 1
    forwarded = list(argv)
    if "--repo-root" not in forwarded:
        forwarded.extend(["--repo-root", str(ROOT)])
    return subprocess.call(
        [str(python), "-m", "simple_code_indexer.setup_wizard", *forwarded],
        cwd=os.getcwd(),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
