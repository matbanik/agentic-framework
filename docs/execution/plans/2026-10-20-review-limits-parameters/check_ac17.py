"""AC-17 oracle: the bounded FIXED_CAP_INVENTORY from implementation-plan.md.

Passes only when every inventory phrase is gone from the working tree, every
inventory file points at the limits source, and the same check fails against
the HEAD-at-planning text (d698342), which proves the oracle can fail.
"""
import subprocess
import sys
from pathlib import Path

BASE_REV = "d698342"
POINTERS = ("review_limits", "review-limits.json")
FIXED_CAP_INVENTORY = {
    "core/.agent/workflows/create-plan.md": (
        "Plan review round cap: 3 rounds",
        "reaches 3 rounds",
        "Plan review reached 3 rounds without approval",
        "Round cap reached (3 rounds)",
        "round cap (6)",
        "Round cap: 6 rounds",
    ),
    "core/.agent/workflows/execution-session.md": (
        "3-round cap",
        "execution = 6",
    ),
    "core/.agent/workflows/delegated-plan-creation.md": (
        "round cap (3)",
        "the cap of 3",
        "is 3 rounds",
        "If 3 rounds without approval",
    ),
    "core/.agent/skills/cli-dispatch/SKILL.md": (
        "capped at 3 rounds",
    ),
    "core/.agent/docs/development-lifecycle.md": (
        "(≤3 rounds)",
        "(≤6 rounds)",
        "max 3 rounds",
        "max 6 rounds",
        "≤3 rounds, agent loops",
        "≤6 rounds, agent loops",
        "3 non-approved rounds",
        "6 non-approved rounds",
        "7th autonomous round",
    ),
}


def problems(read):
    out = []
    for path, phrases in FIXED_CAP_INVENTORY.items():
        text = read(path)
        out += ["%s: still says %r" % (path, ph) for ph in phrases if ph in text]
        if not any(p in text for p in POINTERS):
            out.append("%s: no pointer to review_limits or review-limits.json" % path)
    return out


def at_base(path):
    return subprocess.run(["git", "show", "%s:%s" % (BASE_REV, path)], check=True,
                          capture_output=True).stdout.decode("utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    base = problems(at_base)
    missing = [ph for path, phs in FIXED_CAP_INVENTORY.items() for ph in phs if ph not in at_base(path)]
    if missing:
        print("SELF-CHECK FAILED: inventory phrases absent at %s: %r" % (BASE_REV, missing))
        return 1
    if not base:
        print("SELF-CHECK FAILED: the oracle passes against %s" % BASE_REV)
        return 1
    print("self-check: %d problems at %s (oracle can fail)" % (len(base), BASE_REV))
    now = problems(lambda p: Path(p).read_text(encoding="utf-8"))
    print(*now, sep="\n")
    print("AC-17 %s: %d problems in the working tree" % ("FAIL" if now else "PASS", len(now)))
    return 1 if now else 0


if __name__ == "__main__":
    sys.exit(main())
