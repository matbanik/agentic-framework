#!/usr/bin/env python3
"""Plan-local check for AC-32: no new package-gate failure against the row-0 baseline.

Modes:
  --baseline   save refcheck and sanitize --verify failure lines, plus the input identity
  --selftest   prove the comparison fails when the baseline is missing a line
  (no flag)    compare with the baseline, then check MANIFEST entries and AC-to-test coverage

Writes only under RECEIPTS_DIR. Failure lines are compared without their line numbers, so an edit
above a known failure does not read as a new one.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RECEIPTS = Path(os.environ.get("RECEIPTS_DIR", "C:/Temp/agentic-framework/receipts"))
BASELINE = RECEIPTS / "fleet-gates-baseline.json"
GATES = {
    "refcheck": ["scripts/refcheck.py"],
    "sanitize": ["scripts/sanitize.py", "--verify"],
}
ENTRY_RE = re.compile(r"^\s*(UNRESOLVED|UNCLASSIFIED-TOOL|STALE-[A-Z]+)\s")
HEADER_RE = re.compile(r"^\s*VERIFY FAILED:")
LINE_NO_RE = re.compile(r"(\.[A-Za-z0-9_]+):\d+")
LIVE_ACS = {20, 21, 31, 32}
AC_COUNT = 32
MANIFEST_ENTRIES = (".agent/fleet/fleet.py", ".agent/fleet/bootstrap.md", "core/.agent/fleet.json.template")
TEST_FILES = ("test_fleet_hub.py", "test_fleet_bootstrap.py", "test_fleet_run.py")


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def normalize(line: str) -> str:
    return " ".join(LINE_NO_RE.sub(r"\1", line).split())


def failure_lines(text: str) -> list[str]:
    """Entries by themselves, and each VERIFY FAILED section's indented lines. Counts read as N."""
    found: set[str] = set()
    in_section = False
    for ln in text.splitlines():
        if HEADER_RE.match(ln):
            found.add(re.sub(r"\d+", "N", normalize(ln)))
            in_section = True
        elif ENTRY_RE.match(ln) or (in_section and ln.startswith("      ")):
            found.add(normalize(ln))
        elif in_section and not ln.startswith(" "):
            in_section = False
    return sorted(found)


def collect() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for name, argv in GATES.items():
        r = run([sys.executable, *argv])
        found[name] = failure_lines(r.stdout + r.stderr)
    return found


def new_failures(baseline: dict[str, list[str]], current: dict[str, list[str]]) -> list[str]:
    out = []
    for name, lines in current.items():
        known = set(baseline.get(name, []))
        out.extend(f"{name}: {ln}" for ln in lines if ln not in known)
    return out


def write_baseline() -> int:
    identity = {
        "head": run(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "porcelain": run(["git", "status", "--porcelain"]).stdout,
        "python": sys.version,
    }
    data = {"identity": identity, "gates": collect()}
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    counts = {k: len(v) for k, v in data["gates"].items()}
    print(f"baseline saved: {BASELINE} head={identity['head'][:7]} failure lines={counts}")
    return 0


def selftest() -> int:
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    gate = next((k for k, v in data["gates"].items() if v), None)
    if gate is None:
        print("selftest cannot run: the baseline has no failure line to remove")
        return 1
    current = data["gates"]
    weakened = {k: list(v) for k, v in current.items()}
    removed = weakened[gate].pop()
    found = new_failures(weakened, current)
    if f"{gate}: {removed}" not in found:
        print(f"selftest FAILED: removing a baseline line went unnoticed: {removed}")
        return 1
    if new_failures(current, current):
        print("selftest FAILED: an unchanged baseline reports a new failure")
        return 1
    if normalize("UNRESOLVED  a/b.md:12  ->  c.py") != normalize("UNRESOLVED  a/b.md:99  ->  c.py"):
        print("selftest FAILED: a moved line reads as a new failure")
        return 1
    counted = failure_lines("  VERIFY FAILED:   reference integrity: 54 failure(s):")
    if counted != failure_lines("  VERIFY FAILED:   reference integrity: 53 failure(s):"):
        print("selftest FAILED: a falling count reads as a new failure")
        return 1
    print(f"selftest ok: a baseline without [{removed}] reports it as new")
    return 0


def coverage_gaps() -> list[str]:
    text = ""
    for name in TEST_FILES:
        path = ROOT / "scripts" / "tests" / name
        if path.is_file():
            text += path.read_text(encoding="utf-8")
    have = {int(n) for n in re.findall(r"def test_ac(\d\d)_", text)}
    want = set(range(1, AC_COUNT + 1)) - LIVE_ACS
    return [f"no test_ac{n:02d}_* function" for n in sorted(want - have)]


def manifest_gaps() -> list[str]:
    text = (ROOT / "core" / "MANIFEST.md").read_text(encoding="utf-8")
    return [f"core/MANIFEST.md does not list {e}" for e in MANIFEST_ENTRIES if e not in text]


def compare() -> int:
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    problems = new_failures(data["gates"], collect()) + coverage_gaps() + manifest_gaps()
    for p in problems:
        print(p)
    print(f"{len(problems)} problem(s) against baseline head {data['identity']['head'][:7]}")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--baseline", action="store_true")
    g.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.baseline:
        return write_baseline()
    if a.selftest:
        return selftest()
    return compare()


if __name__ == "__main__":
    raise SystemExit(main())
