"""Fake harness for the parent-watchdog integration test.

Usage: python fake_harness.py <pid-file> <workspace> <server command...>

The spawned server inherits this process's stdin, which the test holds open —
exactly the harness behaviour that leaves ``stdio_server`` waiting for EOF
(ISS-3). The test writes the MCP handshake into that pipe so the deferred
workspace resolution runs. The script then sleeps until the test kills it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    pid_file = Path(sys.argv[1])
    workspace = Path(sys.argv[2])
    command = sys.argv[3:]
    with (workspace / "server-stderr.log").open("ab") as stderr:
        subprocess.Popen(command, cwd=workspace, stderr=stderr)
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        time.sleep(300)


if __name__ == "__main__":
    main()
