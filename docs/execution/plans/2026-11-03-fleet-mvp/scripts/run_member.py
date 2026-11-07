#!/usr/bin/env python3
"""Run one prepared script on the member, through the local WinRM helper, which holds the login.

usage: run_member.py <script.ps1> [KEY=VALUE ...]

FLEET_WINRM_HELPER names the helper's path.

The runner takes a file and no parameters, so each KEY=VALUE becomes a ``$KEY='VALUE'`` line at the top
of a temporary copy. The hub's pairing values are added the same way when the hub has saved them. The
output is printed and appended to RECEIPTS_DIR/member-bootstrap-report.txt.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REMOTE_RUN = os.environ.get("FLEET_WINRM_HELPER", "")
# The runner base64-encodes the script onto a command line, which Windows limits to 8191 characters.
MAX_SCRIPT_CHARS = 3000
HERE = Path(__file__).resolve().parent
PAIRING_NAMES = {"url": "HUB_URL", "pin": "PIN", "fleet_py": "FLEET_SHA", "bootstrap_md": "BOOT_SHA"}


def pairing_values() -> dict[str, str]:
    home = Path(os.environ.get("FLEET_HOME") or Path.home() / ".agent" / "fleet")
    path = home / "hub" / "pairing.txt"
    if not path.exists():
        return {}
    fields = dict(part.split("=", 1) for part in path.read_text(encoding="utf-8").split()[1:])
    return {PAIRING_NAMES[k]: v for k, v in fields.items()}


def build_script(name: str, values: dict[str, str]) -> str:
    lines = [f"${k}='{v.replace(chr(39), chr(39) * 2)}'" for k, v in values.items()]
    return "\n".join(lines + [(HERE / name).read_text(encoding="utf-8")])


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    if not REMOTE_RUN:
        print("set FLEET_WINRM_HELPER to the WinRM helper's path")
        return 2
    name = sys.argv[1]
    values = pairing_values()
    values.update(arg.split("=", 1) for arg in sys.argv[2:])
    script = build_script(name, values)
    if len(script) > MAX_SCRIPT_CHARS:
        print(f"{name} is {len(script)} characters with its values; the limit is {MAX_SCRIPT_CHARS}")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_text(script, encoding="utf-8")
        r = subprocess.run(
            ["uv", "run", "--no-project", "--with", "pywinrm", "python", REMOTE_RUN, "--file", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
        )
    output = r.stdout + r.stderr
    print(output)
    receipts = Path(os.environ["RECEIPTS_DIR"])
    receipts.mkdir(parents=True, exist_ok=True)
    with open(receipts / "member-bootstrap-report.txt", "a", encoding="utf-8") as f:
        f.write(f"=== {name} {' '.join(sys.argv[2:])} exit {r.returncode}\n{output}\n")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
