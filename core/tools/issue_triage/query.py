"""Issue Triage — query, filter, stats.

Provides list_issues (with severity/component/status filters),
get_stats, and get_issue functions.
"""

from __future__ import annotations

from typing import Any

from tools.issue_triage.model import VALID_COMPONENTS, VALID_SEVERITIES, VALID_STATUSES


class QueryError(Exception):
    """Invalid query parameter."""


def list_issues(
    data: dict[str, Any],
    *,
    severity: str | None = None,
    component: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List issues with optional filters.

    Raises QueryError for invalid filter values.
    """
    if severity is not None and severity not in VALID_SEVERITIES:
        raise QueryError(
            f"Invalid severity filter: '{severity}'. Valid: {sorted(VALID_SEVERITIES)}"
        )
    if component is not None and component not in VALID_COMPONENTS:
        raise QueryError(
            f"Invalid component filter: '{component}'. Valid: {sorted(VALID_COMPONENTS)}"
        )
    if status is not None and status not in VALID_STATUSES:
        raise QueryError(
            f"Invalid status filter: '{status}'. Valid: {sorted(VALID_STATUSES)}"
        )

    results: list[dict[str, Any]] = []
    for issue in data.get("issues", []):
        if severity is not None and issue.get("severity") != severity:
            continue
        if component is not None and issue.get("component") != component:
            continue
        if status is not None and issue.get("status") != status:
            continue
        results.append(issue)

    return results


def get_issue(data: dict[str, Any], issue_id: str) -> dict[str, Any] | None:
    """Find an issue by ID. Returns None if not found."""
    for issue in data.get("issues", []):
        if issue.get("id") == issue_id:
            return issue
    return None


def get_stats(data: dict[str, Any]) -> dict[str, Any]:
    """Compute summary statistics.

    Returns dict with: total, by_severity, by_component, by_status.
    """
    issues = data.get("issues", [])

    by_severity: dict[str, int] = {}
    by_component: dict[str, int] = {}
    by_status: dict[str, int] = {}

    for issue in issues:
        sev = issue.get("severity", "unknown")
        by_severity[sev] = by_severity.get(sev, 0) + 1

        comp = issue.get("component", "unknown")
        by_component[comp] = by_component.get(comp, 0) + 1

        st = issue.get("status", "unknown")
        by_status[st] = by_status.get(st, 0) + 1

    return {
        "total": len(issues),
        "by_severity": by_severity,
        "by_component": by_component,
        "by_status": by_status,
    }
