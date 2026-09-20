#!/usr/bin/env python3
"""Plan-local WP3 acceptance: templates-installed then d9-no.

Runs the adoption-contract cases in order and returns the first nonzero
exit. Writes nothing except through the child runner. Repo is not mutated.
"""
from __future__ import annotations

import subprocess
import sys

RUNNER = "scripts/tests/test_adoption_contract.py"


def main() -> int:
    for case in ("templates-installed", "d9-no"):
        r = subprocess.run([sys.executable, RUNNER, "--case", case])
        if r.returncode:
            return int(r.returncode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
