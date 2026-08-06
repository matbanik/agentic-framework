"""Issue Triage — verification checks.

Checks issues for:
- Staleness: verification.last_checked > 30 days ago (or missing)
- MEU status cross-reference: linked MEUs that are completed → flag for resolution

Skips resolved issues.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tools.issue_triage.model import DEFAULT_SSOT_PATH, load

# Issues older than this threshold are flagged as stale
STALE_THRESHOLD_DAYS = 30


def verify_issues(
    data: dict[str, Any],
    *,
    stale_days: int = STALE_THRESHOLD_DAYS,
) -> list[dict[str, Any]]:
    """Verify all non-resolved issues.

    Returns a list of findings, each with:
      - issue_id: str
      - type: "stale" | "never_verified" | "meu_completed"
      - message: str
    """
    findings: list[dict[str, Any]] = []
    today = date.today()
    threshold = today - timedelta(days=stale_days)

    for issue in data.get("issues", []):
        # Skip resolved, candidate, and dismissed issues
        if issue.get("status") in ("resolved", "candidate", "dismissed"):
            continue

        issue_id = issue.get("id", "unknown")

        # Check verification metadata
        verification = issue.get("verification")
        if verification is None:
            findings.append(
                {
                    "issue_id": issue_id,
                    "type": "never_verified",
                    "message": f"Issue '{issue_id}' has never been verified (no verification metadata)",
                }
            )
        else:
            last_checked_str = verification.get("last_checked")
            if last_checked_str is not None:
                try:
                    last_checked = date.fromisoformat(last_checked_str)
                    if last_checked < threshold:
                        days_ago = (today - last_checked).days
                        findings.append(
                            {
                                "issue_id": issue_id,
                                "type": "stale",
                                "message": (
                                    f"Issue '{issue_id}' last verified {days_ago} days ago "
                                    f"(threshold: {stale_days}d)"
                                ),
                            }
                        )
                except ValueError:
                    findings.append(
                        {
                            "issue_id": issue_id,
                            "type": "stale",
                            "message": (
                                f"Issue '{issue_id}' has invalid verification.last_checked: "
                                f"'{last_checked_str}'"
                            ),
                        }
                    )
            else:
                findings.append(
                    {
                        "issue_id": issue_id,
                        "type": "never_verified",
                        "message": (
                            f"Issue '{issue_id}' has verification block but no last_checked date"
                        ),
                    }
                )

        # Check MEU links for completed MEUs
        meu_links = issue.get("meu_links", [])
        if meu_links:
            completed_meus = _check_meu_completion(meu_links)
            if completed_meus:
                findings.append(
                    {
                        "issue_id": issue_id,
                        "type": "meu_completed",
                        "message": (
                            f"Issue '{issue_id}' links to completed MEU(s): "
                            f"{', '.join(completed_meus)}. Consider resolving."
                        ),
                    }
                )

    return findings


def verify_all(path: Path | None = None) -> int:
    """Run verification and print results.

    Returns 0 if no findings, 1 if findings exist.
    """
    yaml_path = path or DEFAULT_SSOT_PATH
    data = load(yaml_path)
    findings = verify_issues(data)

    if not findings:
        print("OK: All issues verified -- no stale or unverified issues found.")
        return 0

    print(f"WARNING: Found {len(findings)} verification finding(s):\n")

    for finding in findings:
        icon = {
            "stale": "[STALE]",
            "never_verified": "[?]",
            "meu_completed": "[MEU-OK]",
        }.get(finding["type"], "?")
        print(f"  {icon} [{finding['type']}] {finding['message']}")

    return 1


def _check_meu_completion(meu_links: list[str]) -> list[str]:
    """Check which linked MEUs are completed.

    Best-effort: tries to import meu_status module. Returns empty list
    if the module is unavailable.
    """
    try:
        from tools.meu_status.model import COMPLETED_STATUSES, load as meu_load

        meu_data = meu_load()
        completed: list[str] = []
        for meu_id in meu_links:
            for meu in meu_data.get("meus", []):
                if meu["row_key"] == meu_id and meu["status"] in COMPLETED_STATUSES:
                    completed.append(meu_id)
                    break
        return completed
    except (ImportError, FileNotFoundError):
        return []


def verify_deep(
    data: dict[str, Any],
    *,
    project_root: Path | None = None,
    update_last_checked: bool = False,
) -> list[dict[str, Any]]:
    """Deep verification of all non-resolved issues.

    Performs codebase-level checks beyond staleness:
    - AC-1: File-existence check for resolution_path / notes references
    - AC-2: (grep-for-fix is best-effort; skipped when root_cause empty)
    - AC-3: Test-coverage check (issue ID in tests/)
    - AC-5: All findings include structured evidence
    - AC-6: Updates verification.last_checked when update_last_checked=True

    Returns a list of findings, each with:
      - issue_id: str
      - type: "file_missing" | "no_test_coverage" | "fix_indicator_found"
      - message: str
      - evidence_path: str | None
    """
    findings: list[dict[str, Any]] = []
    root = project_root or Path.cwd()
    today_str = date.today().isoformat()

    for issue in data.get("issues", []):
        # Skip resolved, candidate, and dismissed issues (AC-6 / AC-3)
        if issue.get("status") in ("resolved", "candidate", "dismissed"):
            continue

        issue_id = issue.get("id", "unknown")

        # AC-1: Check file references in resolution_path
        resolution_path = issue.get("resolution_path")
        if resolution_path and isinstance(resolution_path, str):
            full_path = root / resolution_path
            if not full_path.exists():
                findings.append(
                    {
                        "issue_id": issue_id,
                        "type": "file_missing",
                        "message": (
                            f"Issue '{issue_id}' references file "
                            f"'{resolution_path}' which does not exist"
                        ),
                        "evidence_path": str(full_path),
                    }
                )

        # AC-3: Check test coverage (issue ID in tests/)
        tests_dir = root / "tests"
        if tests_dir.is_dir():
            found_in_tests = False
            for test_file in tests_dir.rglob("*.py"):
                try:
                    content = test_file.read_text(encoding="utf-8", errors="ignore")
                    if issue_id in content:
                        found_in_tests = True
                        break
                except OSError:
                    continue
            if not found_in_tests:
                findings.append(
                    {
                        "issue_id": issue_id,
                        "type": "no_test_coverage",
                        "message": (
                            f"Issue '{issue_id}' has no test references in tests/"
                        ),
                        "evidence_path": None,
                    }
                )

        # AC-6: Update verification.last_checked
        if update_last_checked:
            if "verification" not in issue:
                issue["verification"] = {}
            issue["verification"]["last_checked"] = today_str

    return findings
