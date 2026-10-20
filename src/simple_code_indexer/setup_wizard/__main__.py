"""`python -m simple_code_indexer.setup_wizard`."""

from __future__ import annotations

import sys

from simple_code_indexer.setup_wizard import run

if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
