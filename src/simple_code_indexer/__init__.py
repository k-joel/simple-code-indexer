"""Local-first hybrid lexical + semantic code index, served over MCP.

`main` is the historical entry point (``[project.scripts]`` used to point here);
it now delegates to `simple_code_indexer.cli`, which exposes `setup`, `serve`,
`uninstall`, `status` and `version` as subcommands.
"""


def main() -> None:
    from simple_code_indexer.cli import main as cli_main

    cli_main()
