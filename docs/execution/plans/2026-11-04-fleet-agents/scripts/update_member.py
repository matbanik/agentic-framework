#!/usr/bin/env python3
"""Update the member machine's fleet.py from the hub and restart its member process, or only restart it with --restart-only.

Uses the MVP plan's member-update.ps1 and member-task.ps1 through its run_member.py, which take their values
from the hub's pairing file. Restart the hub first, so it serves the new fleet.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "2026-11-03-fleet-mvp" / "scripts"


def run(*args: str) -> int:
    code = subprocess.run([sys.executable, str(SCRIPTS / "run_member.py"), *args]).returncode
    print(f"{args[0]} exit {code}")
    return code


def main() -> int:
    if "--restart-only" not in sys.argv[1:]:
        code = run("member-update.ps1")
        if code:
            return code
    return run("member-task.ps1", "ACTION=Restart")


if __name__ == "__main__":
    raise SystemExit(main())
