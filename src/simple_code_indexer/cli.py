"""`simple-code-indexer` console entry point.

One command, explicit subcommands, so `uvx simple-code-indexer setup` and
`uvx simple-code-indexer serve` both work without a `--from` flag: the console
script name and the PyPI project name are the same.

No subcommand means `serve`. Harness entries always pass ``serve`` explicitly,
but a bare invocation (and the pre-existing ``simple_code_indexer:main`` entry
point) must keep starting the MCP server rather than printing a usage error.

stdout is the MCP transport. Nothing here may write to it on the serve path;
diagnostics go to stderr, which is where logging already points.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from simple_code_indexer import logging_setup

SUBCOMMANDS = ("setup", "install", "serve", "uninstall", "status", "version")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simple-code-indexer",
        description="Local-first hybrid lexical + semantic code index, served over MCP.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=SUBCOMMANDS,
        default="serve",
        help=(
            "serve: run the MCP server on stdio (default); "
            "setup: configure the global install; "
            "install: install this checkout as a uv tool (editable by default, "
            "--wheel for prod) and exit; "
            "uninstall: remove what setup wrote; "
            "status: print the resolved workspace and index health; "
            "version: print the package version"
        ),
    )
    return parser


def _serve(argv: list[str]) -> int:
    # Unknown flags are ignored on purpose: a stray argument in a harness config
    # must never leave the pipe without a server. `--workspace` and `--harness`
    # are the exceptions — a project-scope entry pins its workspace (ADR-022) and
    # a resolver-owning entry names its plugin (ADR-024).
    workspace, rest = _flag_arg(argv, "--workspace")
    harness, rest = _flag_arg(rest, "--harness")
    _parser().parse_known_args(rest)
    logging_setup.configure_console()
    from simple_code_indexer.server import main as server_main

    path = _absolute(workspace)
    server_main(workspace=path, harness=harness)
    return 0


def _flag_arg(argv: list[str], flag: str) -> tuple[str | None, list[str]]:
    """Split `flag value` / `flag=value` out of `argv`; last occurrence wins.

    Hand-rolled rather than argparse because `serve` must tolerate unknown
    flags (stdout is the MCP transport) and these two are the only ones it reads.
    """
    found: str | None = None
    rest: list[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == flag:
            if index + 1 < len(argv):
                found = argv[index + 1]
                index += 1
        elif item.startswith(flag + "="):
            found = item.partition("=")[2]
        else:
            rest.append(item)
        index += 1
    return found, rest


def _absolute(raw: str | None) -> Path | None:
    """A `--workspace` value as an absolute path (relative resolves against cwd)."""
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _setup(argv: list[str]) -> int:
    from simple_code_indexer.setup_wizard import run

    return run(argv)


def _install(argv: list[str]) -> int:
    """Install the running checkout as an editable uv tool; no prompts.

    This is the replacement for the old `python setup.py` bootstrap: it needs no
    committed launcher script and works from any wheel or checkout. Pass
    ``--wheel`` to build and install a real wheel instead (prod validation).
    """
    from simple_code_indexer.setup_wizard import run

    return run(["--install-only", *argv])


def _uninstall(argv: list[str]) -> int:
    from simple_code_indexer.setup_wizard import run

    return run(["--uninstall", *argv])


def _install_kind() -> str | None:
    """What the last `setup`/`install` recorded: ``editable`` or ``wheel``."""
    from simple_code_indexer import configfile
    from simple_code_indexer.errors import ConfigError

    path = configfile.global_config_path()
    if not path.is_file():
        return None
    try:
        setup = configfile.get_mapping(configfile.load_config(path), "setup")
    except ConfigError:
        return None
    return configfile.get_str(setup, "install_kind", where="setup")


def _status(argv: list[str]) -> int:
    """Read-only summary for the current directory; never opens a writer."""
    _parser().parse_known_args(argv)
    from simple_code_indexer import config, db
    from simple_code_indexer import logging_setup as logs

    settings = config.load_settings()
    with db.try_connect_readonly(settings.index_db_path) as conn:
        counts = db.stats(conn) if conn is not None else None
        embedding = db.embedding_counts(conn) if conn is not None else None
    payload = {
        "version": logs.package_version(),
        "workspace": str(settings.workspace_root),
        "workspace_source": settings.workspace_source,
        "index_db": str(settings.index_db_path),
        "index_ready": counts is not None,
        "files_indexed": counts["files"] if counts else 0,
        "symbols_indexed": counts["symbols"] if counts else 0,
        "chunks_indexed": counts["chunks"] if counts else 0,
        "vectors_indexed": embedding["embedded"] if embedding else 0,
        "pending_embeddings": embedding["pending"] if embedding else 0,
        "vector_store": settings.vector_store,
        "embed_model": settings.embed_model,
        "embed_dim": settings.embed_dim,
        "mode": settings.mode,
        "install_kind": _install_kind(),
        "config_file": str(settings.config_source) if settings.config_source else None,
    }
    print(json.dumps(payload, indent=2))
    return 0


def _cli_main(argv: list[str] | None = None) -> int:
    argparse_argv = sys.argv[1:] if argv is None else argv
    command, rest = _split_subcommand(argparse_argv)
    if command == "setup":
        return _setup(rest)
    if command == "install":
        return _install(rest)
    if command == "uninstall":
        return _uninstall(rest)
    if command == "status":
        return _status(rest)
    if command == "version":
        print(logging_setup.package_version())
        return 0
    return _serve(rest)


def _split_subcommand(argv: list[str]) -> tuple[str, list[str]]:
    """Resolve the leading subcommand without argparse rejecting server flags.

    A bare `--help` has to reach argparse so the help text is printed; any other
    leading dash means "no subcommand", i.e. serve.
    """
    if not argv:
        return "serve", []
    head = argv[0]
    if head in SUBCOMMANDS:
        return head, argv[1:]
    if head in ("-h", "--help"):
        _parser().parse_args(argv)
        return "serve", []
    return "serve", argv


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point: always exits through ``SystemExit``."""
    raise SystemExit(_cli_main(argv))


if __name__ == "__main__":
    main()
