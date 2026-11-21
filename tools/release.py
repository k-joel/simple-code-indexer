#!/usr/bin/env python3
"""Release plumbing: bump the version, tag it, and verify the tag matches.

`pyproject.toml` is the single source of truth for the version (`uv_build`
requires static metadata, so the git tag cannot be the source). This script
keeps the two in step and is the only thing a maintainer runs to cut a release:

    python tools/release.py --bump patch          # 0.1.0 -> 0.1.1, tag, push
    python tools/release.py --bump patch --dry-run
    python tools/release.py --verify-tag v0.1.0   # used by the release workflow
    python tools/release.py --check-pypi          # is this version already out?

The publish itself happens in `.github/workflows/release.yml` on tag push, through
PyPI Trusted Publishing: no token is stored anywhere.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"
DISTRIBUTION = "simple-code-indexer"
MAIN_BRANCH = "master"
UNRELEASED = "## [Unreleased]"
PYPI_TIMEOUT_S = 15.0


def _run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(f"{' '.join(argv)} failed: {detail}")
    return result


def current_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"no static version in {PYPROJECT}")
    return match.group(1)


def _require_clean_tree() -> None:
    if _run(["git", "status", "--porcelain"]).stdout.strip():
        raise SystemExit("working tree is dirty; commit or stash before releasing")


def _require_branch() -> None:
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != MAIN_BRANCH:
        raise SystemExit(f"release from {MAIN_BRANCH} (currently on {branch})")


def _tag_exists(tag: str) -> bool:
    return (
        _run(["git", "rev-parse", "--verify", "--quiet", tag], check=False).returncode
        == 0
    )


def published_versions() -> set[str]:
    """Versions already on PyPI; an unknown project simply has none."""
    try:
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/{DISTRIBUTION}/json", timeout=PYPI_TIMEOUT_S
        ) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return set()
        raise SystemExit(f"PyPI lookup failed: {exc}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"PyPI lookup failed: {exc}") from exc
    return set(payload.get("releases", {}))


def _bump_version(args: argparse.Namespace) -> int:
    _require_clean_tree()
    _require_branch()
    before = current_version()
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required (it bumps pyproject.toml and uv.lock)")

    bump = [uv, "version", "--bump", args.bump, "--no-sync"]
    if args.dry_run:
        print(f"{before} (dry run: would bump {args.bump})")
        return 0
    _run(bump)
    after = current_version()
    tag = f"v{after}"
    if _tag_exists(tag):
        raise SystemExit(f"{tag} already exists; bump again or delete the stale tag")
    if after in published_versions():
        raise SystemExit(f"{after} is already on PyPI; versions cannot be re-uploaded")

    _cut_changelog(after)
    _run(["git", "add", "pyproject.toml", "uv.lock", str(CHANGELOG)])
    _run(["git", "commit", "-m", f"release: {tag}"])
    _run(["git", "tag", "-a", tag, "-m", tag])
    _run(["git", "push", "--follow-tags"])
    print(f"{before} -> {after}; pushed {tag}. The release workflow now publishes it.")
    return 0


def _cut_changelog(version: str) -> None:
    """Turn the Unreleased heading into a dated release heading."""
    if not CHANGELOG.is_file():
        return
    text = CHANGELOG.read_text(encoding="utf-8")
    if UNRELEASED not in text:
        raise SystemExit(f"{CHANGELOG} has no {UNRELEASED!r} heading")
    heading = f"## [{version}] - {date.today().isoformat()}"
    text = text.replace(UNRELEASED, f"{UNRELEASED}\n\n{heading}", 1)
    CHANGELOG.write_text(text, encoding="utf-8", newline="\n")


def _verify_tag(args: argparse.Namespace) -> int:
    tag = args.verify_tag
    version = current_version()
    if tag != f"v{version}":
        raise SystemExit(f"tag {tag!r} does not match pyproject version {version!r}")
    if version in published_versions():
        raise SystemExit(
            f"{version} is already on PyPI; versions cannot be re-uploaded"
        )
    print(f"{tag} matches {version} and is unpublished")
    return 0


def _check_pypi() -> int:
    version = current_version()
    if version in published_versions():
        raise SystemExit(
            f"{version} is already on PyPI; versions cannot be re-uploaded"
        )
    print(f"{version} is unpublished")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--bump", choices=["patch", "minor", "major"], default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-tag", metavar="TAG", default=None)
    parser.add_argument("--check-pypi", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.verify_tag is not None:
        return _verify_tag(args)
    if args.check_pypi:
        return _check_pypi()
    if args.bump is not None:
        return _bump_version(args)
    parser.error("choose --bump, --verify-tag or --check-pypi")


if __name__ == "__main__":
    raise SystemExit(main())
