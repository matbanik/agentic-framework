#!/usr/bin/env python3
"""Carry setup-member.ps1 and a copy of the model registry to the member over WinRM, run it, and save its report.

Run through: uv run --no-project --with pywinrm python run_member_setup.py <n>

<n> numbers the report under RECEIPTS_DIR as fa-setup-report-<n>.json. The registry copy gains
classes.isolated_worker.bindings["codex-cli"], with its slug taken from the reviewer's binding (P-1), and
The hub's own file is only ever read. A run that sees the hub's hash change stops (stop condition 12).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "2026-11-03-fleet-mvp" / "scripts"))
from fleet_auth import connect, redacted, run_ps, run_with_stdin  # noqa: E402

ROOT = Path(__file__).resolve().parents[5]
HUB_REGISTRY = Path("P:/.agent/model-registry.json")
REGISTRY_SHA_PREFIX = "7097dc5bb0f07978"
SETUP = ROOT / ".agent" / "fleet" / "setup-member.ps1"
REMOTE_REGISTRY = r"$HOME\.agent\model-registry.json"
REMOTE_SETUP = r"$HOME\.agent\fleet\setup-member.ps1"
REMOTE_REPORT = r"$HOME\.agent\fleet\setup-report.json"
COPY_FILE = r"""
$ErrorActionPreference = 'Stop'
$path = "__PATH__"
New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
[IO.File]::WriteAllBytes($path, [Convert]::FromBase64String([Console]::In.ReadToEnd().Trim()))
Write-Output ('SHA256=' + (Get-FileHash $path -Algorithm SHA256).Hash.ToLower())
"""


def registry_copy() -> bytes:
    raw = HUB_REGISTRY.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if not sha.startswith(REGISTRY_SHA_PREFIX):
        raise RuntimeError(f"The hub's registry hash is {sha[:16]}, not {REGISTRY_SHA_PREFIX} (stop condition 12)")
    data = json.loads(raw.decode("utf-8"))
    reviewer = data["classes"]["independent_reviewer"]["bindings"].get("codex-cli", {})
    if not reviewer.get("slug"):
        raise RuntimeError("the reviewer has no codex-cli binding to copy a slug from")
    data["classes"]["isolated_worker"]["bindings"]["codex-cli"] = {"slug": reviewer["slug"]}
    return json.dumps(data, indent=2).encode("utf-8")


def copy_file(session, remote_path: str, data: bytes) -> None:
    code, out, err = run_with_stdin(session, COPY_FILE.replace("__PATH__", remote_path), base64.b64encode(data))
    if code != 0:
        raise RuntimeError(f"copy to {remote_path} exited {code}: {redacted(err)[:400]}")
    if f"SHA256={hashlib.sha256(data).hexdigest()}" not in out:
        raise RuntimeError(f"the copy at {remote_path} has the wrong hash")


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(__doc__)
        return 2
    session = connect()
    copy_file(session, REMOTE_REGISTRY, registry_copy())
    copy_file(session, REMOTE_SETUP, SETUP.read_bytes())
    code, out, err = run_with_stdin(
        session, f'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{REMOTE_SETUP}"; exit $LASTEXITCODE',
    )
    print(redacted(out).strip())
    if err.strip():
        print("stderr:", redacted(err)[:1500])
    report = run_ps(session, f'if (Test-Path "{REMOTE_REPORT}") {{ Get-Content "{REMOTE_REPORT}" -Raw }}').strip()
    if report:
        receipts = Path(os.environ["RECEIPTS_DIR"])
        receipts.mkdir(parents=True, exist_ok=True)
        (receipts / f"fa-setup-report-{sys.argv[1]}.json").write_text(report, encoding="utf-8")
    if not hashlib.sha256(HUB_REGISTRY.read_bytes()).hexdigest().startswith(REGISTRY_SHA_PREFIX):
        print("The hub's registry hash changed (stop condition 12)")
        return 1
    print(f"setup exit {code}")
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:  # A traceback could carry values, so only a scrubbed message prints.
        print(f"failed: {redacted(str(exc))[:500]}")
        raise SystemExit(1)
