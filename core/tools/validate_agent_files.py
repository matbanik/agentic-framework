"""AGENTS.md tree validator — drift checker for contributor documentation.

Validates that the AGENTS.md file tree is well-formed and consistent.
Runs 7 drift checks:
  1. Root AGENTS.md (docs/AGENTS.md) ≤200 lines
  2. CLAUDE.md contains redirect reference to AGENTS.md
  3. .windsurfrules content redirects to AGENTS.md
  3a. .devin/rules/{{PROJECT_NAME}}-rules.md exists and redirects to AGENTS.md
  4. Per-package AGENTS.md exists for every package in ``PACKAGES``
  5. No per-package AGENTS.md exceeds 60 lines
  6. Root AGENTS.md contains required sections (build commands, test commands, dependency rule)

The drift-check paths and ``PACKAGES`` describe the adopter's layout; edit them to match it.

A separate mode, ``--policy run-parameters``, checks the effective governance text of the
run-parameters feature instead: each approved line of ``AGENTS.md`` and ``GUARDRAILS.md`` is
present and each retired line is absent. The approved and retired lines are the ``+`` and
``-`` lines of the approved ledger diffs under ``.agent/run-parameters/governance/``, read at
run time from the tree that holds this script (installation rewrites tokens, so the lines
cannot ship as digests). It runs only that check; the drift checks above are not run in that
mode.

Usage:
    python tools/validate_agent_files.py          # run all checks
    python tools/validate_agent_files.py --quiet   # suppress per-check output, show summary only
    python tools/validate_agent_files.py --policy run-parameters [--d20 A|B]

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# --- Constants ---

ROOT_AGENTS_PATH = Path("docs/AGENTS.md")
ROOT_AGENTS_MAX_LINES = 200

CLAUDE_MD_PATH = Path("CLAUDE.md")

WINDSURFRULES_PATH = Path(".windsurfrules")
DEVIN_RULES_PATH = Path(".devin/rules/{{PROJECT_NAME}}-rules.md")

# The adopter's package folders, each of which carries its own AGENTS.md.
PACKAGES: list[str] = []
PACKAGE_AGENTS_MAX_LINES = 60

REQUIRED_SECTIONS: list[str] = [
    "build commands",
    "test commands",
    "dependency rule",
]

REDIRECT_MARKER = "AGENTS.md"

# --- Run-parameters policy (approved ledger diffs) ---

POLICY_MODES: tuple[str, ...] = ("run-parameters",)
D20_RULINGS: tuple[str, ...] = ("A", "B")
RUN_PARAMETERS_POLICY_PATH = Path(".agent/run-parameters.policy.json")
GOVERNANCE_HOME = Path(".agent/run-parameters/governance")

# (governance file, ledger diff, check ids): the n-th check id names the n-th before/after
# pair of that diff, in diff order.
LEDGER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "AGENTS.md",
        "01-agents.diff",
        ("hard_gate_2", "human_gate", "closeout_commits", "git_authorization"),
    ),
    ("GUARDRAILS.md", "02-guardrails.diff", ("sign1_replacement", "sign3_b_grant")),
)
# Only the D-20 A text of SIGN 3 (b) is approved; under D-20 B this check fails closed.
D20_CLOSED_CHECK = "sign3_b_grant"


# --- Check Functions ---


def check_root_agents_line_count(repo_root: Path) -> tuple[bool, str]:
    """Check 1: Root AGENTS.md exists and is ≤200 lines."""
    agents_path = repo_root / ROOT_AGENTS_PATH
    if not agents_path.is_file():
        return False, f"FAIL: {ROOT_AGENTS_PATH} does not exist"

    line_count = len(agents_path.read_text(encoding="utf-8").splitlines())
    if line_count > ROOT_AGENTS_MAX_LINES:
        return False, (
            f"FAIL: {ROOT_AGENTS_PATH} is {line_count} lines "
            f"(limit: {ROOT_AGENTS_MAX_LINES})"
        )

    return (
        True,
        f"PASS: {ROOT_AGENTS_PATH} is {line_count} lines (<={ROOT_AGENTS_MAX_LINES})",
    )


def check_claude_md_redirect(repo_root: Path) -> tuple[bool, str]:
    """Check 2: CLAUDE.md contains redirect reference to AGENTS.md."""
    claude_path = repo_root / CLAUDE_MD_PATH
    if not claude_path.is_file():
        return False, f"FAIL: {CLAUDE_MD_PATH} does not exist"

    content = claude_path.read_text(encoding="utf-8")
    if REDIRECT_MARKER not in content:
        return False, f"FAIL: {CLAUDE_MD_PATH} does not reference {REDIRECT_MARKER}"

    return True, f"PASS: {CLAUDE_MD_PATH} references {REDIRECT_MARKER}"


def check_windsurfrules_redirect(repo_root: Path) -> tuple[bool, str]:
    """Check 3: .windsurfrules exists and redirects to AGENTS.md."""
    ws_path = repo_root / WINDSURFRULES_PATH
    if not ws_path.is_file():
        return False, f"FAIL: {WINDSURFRULES_PATH} does not exist"

    content = ws_path.read_text(encoding="utf-8")
    if REDIRECT_MARKER not in content:
        return False, f"FAIL: {WINDSURFRULES_PATH} does not reference {REDIRECT_MARKER}"

    return True, f"PASS: {WINDSURFRULES_PATH} references {REDIRECT_MARKER}"


def check_devin_rules_redirect(repo_root: Path) -> tuple[bool, str]:
    """Check 3a: the .devin/rules/ file exists and redirects to AGENTS.md."""
    devin_path = repo_root / DEVIN_RULES_PATH
    if not devin_path.is_file():
        return False, f"FAIL: {DEVIN_RULES_PATH} does not exist"

    content = devin_path.read_text(encoding="utf-8")
    if REDIRECT_MARKER not in content:
        return False, f"FAIL: {DEVIN_RULES_PATH} does not reference {REDIRECT_MARKER}"

    return True, f"PASS: {DEVIN_RULES_PATH} references {REDIRECT_MARKER}"


def check_per_package_agents_exist(repo_root: Path) -> tuple[bool, str]:
    """Check 4: Per-package AGENTS.md exists for every package."""
    missing: list[str] = []
    for pkg in PACKAGES:
        pkg_agents = repo_root / pkg / "AGENTS.md"
        if not pkg_agents.is_file():
            missing.append(pkg)

    if missing:
        return False, f"FAIL: Missing AGENTS.md in: {', '.join(missing)}"

    return True, f"PASS: All {len(PACKAGES)} per-package AGENTS.md files exist"


def check_per_package_agents_line_limit(repo_root: Path) -> tuple[bool, str]:
    """Check 5: No per-package AGENTS.md exceeds 60 lines."""
    violations: list[str] = []
    for pkg in PACKAGES:
        pkg_agents = repo_root / pkg / "AGENTS.md"
        if not pkg_agents.is_file():
            continue  # Check 4 will catch missing files
        line_count = len(pkg_agents.read_text(encoding="utf-8").splitlines())
        if line_count > PACKAGE_AGENTS_MAX_LINES:
            violations.append(f"{pkg} ({line_count} lines)")

    if violations:
        return False, (
            f"FAIL: Per-package AGENTS.md exceeds {PACKAGE_AGENTS_MAX_LINES} lines: "
            f"{', '.join(violations)}"
        )

    return True, (
        f"PASS: All per-package AGENTS.md files are <={PACKAGE_AGENTS_MAX_LINES} lines"
    )


def check_required_sections(repo_root: Path) -> tuple[bool, str]:
    """Check 6: Root AGENTS.md contains required sections."""
    agents_path = repo_root / ROOT_AGENTS_PATH
    if not agents_path.is_file():
        return False, f"FAIL: {ROOT_AGENTS_PATH} does not exist (cannot check sections)"

    content = agents_path.read_text(encoding="utf-8").lower()
    missing_sections: list[str] = []

    for section in REQUIRED_SECTIONS:
        # Flexible matching: "build commands" matches heading "## Build Commands"
        # or inline text "build commands"
        section_lower = section.lower()
        # Also check for common variations
        if section_lower == "build commands":
            found = "build commands" in content or "uv sync" in content
        elif section_lower == "test commands":
            found = "test commands" in content or "pytest" in content
        elif section_lower == "dependency rule":
            found = "dependency rule" in content
        else:
            found = section_lower in content

        if not found:
            missing_sections.append(section)

    if missing_sections:
        return False, (
            f"FAIL: {ROOT_AGENTS_PATH} missing sections: {', '.join(missing_sections)}"
        )

    return True, f"PASS: {ROOT_AGENTS_PATH} contains all required sections"


# --- Run-parameters policy check ---


def _governance_lines(path: Path) -> list[str] | None:
    """The file's lines without their EOL (LF or CRLF), or None when it cannot be read."""
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return [line.removesuffix("\r") for line in text.split("\n")]


def _ledger_pairs(path: Path) -> list[tuple[str, str]] | None:
    """The (retired, approved) line pairs of one unified diff, in order, or None.

    Only hunk bodies count, so a header line (``diff``, ``index``, ``---``, ``+++``) is never
    read as a changed line. The n-th ``-`` line pairs with the n-th ``+`` line; a diff that
    cannot be read, has no pair, or has unequal ``-`` and ``+`` counts is None.
    """
    lines = _governance_lines(path)
    if lines is None:
        return None
    removed: list[str] = []
    added: list[str] = []
    in_hunk = False
    for line in lines:
        if line.startswith("@@"):
            in_hunk = True
        elif line.startswith("diff "):
            in_hunk = False
        elif not in_hunk:
            continue
        elif line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
    if not removed or len(removed) != len(added):
        return None
    return list(zip(removed, added, strict=True))


def _ledger_root() -> Path:
    """The tree that holds this script, whose ledger diffs are the approved text."""
    return Path(__file__).resolve().parent.parent


def check_run_parameters_policy(
    repo_root: Path, d20: str, *, ledger_root: Path | None = None
) -> list[tuple[str, str]]:
    """The ledger checks over ``AGENTS.md`` and ``GUARDRAILS.md`` under ``repo_root``.

    The expected lines are the pairs of the ledger diffs under ``ledger_root`` (default: the
    tree that holds this script). Returns the failures as ``(check, message)`` pairs, at most
    one per check, in ledger order; an empty list means the text is the approved one. A
    retired line takes precedence over a missing approved line, and a message names
    ``<file>:<line>`` when a line was found. An absent or unreadable governance file, or a
    ledger diff whose pairs do not match its check ids, fails every check of that file.
    Under ``d20 == "B"`` the ``sign3_b_grant`` check fails closed. Nothing is written.
    """
    if d20 not in D20_RULINGS:
        raise ValueError(f"d20 must be one of {D20_RULINGS}, got {d20!r}")
    root = ledger_root if ledger_root is not None else _ledger_root()
    failures: list[tuple[str, str]] = []
    for name, diff, checks in LEDGER:
        pairs = _ledger_pairs(root / GOVERNANCE_HOME / diff)
        if pairs is None or len(pairs) != len(checks):
            found = "missing or unreadable" if pairs is None else f"{len(pairs)} pairs"
            message = f"{GOVERNANCE_HOME.as_posix()}/{diff}: ledger {found}, expected {len(checks)} pairs"
            failures.extend((check, message) for check in checks)
            continue
        lines = _governance_lines(repo_root / name)
        if lines is None:
            failures.extend(
                (check, f"{name}: missing or unreadable") for check in checks
            )
            continue
        for check, (before, after) in zip(checks, pairs, strict=True):
            if before in lines:
                number = lines.index(before) + 1
                failures.append(
                    (check, f"{name}:{number}: the retired line is still present")
                )
            elif after not in lines:
                failures.append((check, f"{name}: the approved line is absent"))
            elif d20 == "B" and check == D20_CLOSED_CHECK:
                number = lines.index(after) + 1
                failures.append(
                    (
                        check,
                        f"{name}:{number}: D-20 B has no approved text; fails closed",
                    )
                )
    return failures


def _policy_d20(repo_root: Path) -> str:
    """The policy's D-20 ruling when the policy parses and holds one, else ``A``."""
    try:
        policy = json.loads((repo_root / RUN_PARAMETERS_POLICY_PATH).read_bytes())
    except (OSError, ValueError):
        return "A"
    rulings = policy.get("rulings") if isinstance(policy, dict) else None
    d20 = rulings.get("d20") if isinstance(rulings, dict) else None
    return d20 if isinstance(d20, str) and d20 in D20_RULINGS else "A"


def run_policy(repo_root: Path, d20: str | None) -> int:
    """Run the run-parameters policy check, print each failure, return the exit code."""
    ruling = d20 if d20 is not None else _policy_d20(repo_root)
    failures = check_run_parameters_policy(repo_root, ruling)
    for check, message in failures:
        print(f"  FAIL {check}: {message}")
    if failures:
        print(f"\nRun-parameters policy check (D-20 {ruling}): {len(failures)} FAILED")
        return 1
    print(f"\nRun-parameters policy check (D-20 {ruling}): all checks passed")
    return 0


# --- Runner ---

ALL_CHECKS: list[tuple[str, object]] = [
    ("Check 1: Root AGENTS.md line count", check_root_agents_line_count),
    ("Check 2: CLAUDE.md redirect", check_claude_md_redirect),
    ("Check 3: .windsurfrules redirect", check_windsurfrules_redirect),
    ("Check 3a: .devin/rules/ redirect", check_devin_rules_redirect),
    ("Check 4: Per-package AGENTS.md existence", check_per_package_agents_exist),
    ("Check 5: Per-package AGENTS.md line limit", check_per_package_agents_line_limit),
    ("Check 6: Required sections", check_required_sections),
]


def main() -> int:
    """Run all drift checks and report results."""
    parser = argparse.ArgumentParser(
        description="Validate AGENTS.md tree for drift",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-check output, show summary only",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--policy",
        choices=POLICY_MODES,
        default=None,
        help="Run only the named policy check instead of the drift checks",
    )
    parser.add_argument(
        "--d20",
        choices=D20_RULINGS,
        default=None,
        help="D-20 ruling for --policy run-parameters (default: the policy's, else A)",
    )
    args = parser.parse_args()
    if args.d20 is not None and args.policy is None:
        parser.error("--d20 requires --policy run-parameters")

    # Auto-detect repo root: script is at tools/validate_agent_files.py
    repo_root: Path = args.repo_root or Path(__file__).resolve().parent.parent

    if args.policy is not None:
        return run_policy(repo_root, args.d20)

    passed = 0
    failed = 0

    for check_name, check_fn in ALL_CHECKS:
        ok, message = check_fn(repo_root)  # type: ignore[operator]
        if ok:
            passed += 1
        else:
            failed += 1
        if not args.quiet:
            print(f"  {message}")

    total = passed + failed
    print(f"\nAgent files check complete: {passed}/{total} checks passed")

    if failed > 0:
        print(f"  {failed} check(s) FAILED")
        return 1

    print("  All checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
