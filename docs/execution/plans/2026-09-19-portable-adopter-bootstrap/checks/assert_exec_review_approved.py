#!/usr/bin/env python3
"""Plan-local two-stage H1-7 closeout check.

Writes the review-state receipt under RECEIPTS_DIR, then consumes it with
--approved-state-only. Mutates nothing in the repository.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REVIEW = Path(
    ".agent/context/handoffs/"
    "2026-09-19-portable-adopter-bootstrap-implementation-critical-review.md"
)
PLAN = (
    "docs/execution/plans/2026-09-19-portable-adopter-bootstrap/"
    "implementation-plan.md"
)
VALIDATOR = Path("core/tools/validate_closeout_artifacts.py")


def main() -> int:
    receipts = os.environ.get("RECEIPTS_DIR")
    if not receipts:
        print("USAGE: RECEIPTS_DIR is required", file=sys.stderr)
        return 2
    state = str(Path(receipts) / "exec-review-state.json")
    cmd1 = [
        sys.executable,
        str(VALIDATOR),
        "--review",
        str(REVIEW),
        "--review-state-only",
        "--expected-review-mode",
        "execution",
        "--expected-target-plan",
        PLAN,
        "--max-review-rounds",
        "6",
        "--output",
        state,
    ]
    r1 = subprocess.run(cmd1)
    if r1.returncode:
        return int(r1.returncode)
    cmd2 = [
        sys.executable,
        str(VALIDATOR),
        "--review",
        str(REVIEW),
        "--review-state-receipt",
        state,
        "--approved-state-only",
        "--expected-review-mode",
        "execution",
        "--expected-target-plan",
        PLAN,
        "--max-review-rounds",
        "6",
    ]
    r2 = subprocess.run(cmd2)
    return int(r2.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
