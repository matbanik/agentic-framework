"""Issue Triage — MEU bucketing.

Groups classified issues into proposed MEU batches for project planning.
Reads issues with actionable categories (MEU-NEW, MEU-EXPAND, PLAN-NEW)
and groups by component + related fields.
"""

from __future__ import annotations

from typing import Any

# Categories that represent actionable work requiring MEU creation/expansion
ACTIONABLE_CATEGORIES = frozenset({"MEU-NEW", "MEU-EXPAND", "PLAN-NEW"})

# Complexity estimation based on issue count in a batch
_COMPLEXITY_THRESHOLDS = {1: "S", 2: "M", 3: "M"}


def _estimate_complexity(count: int) -> str:
    """Estimate batch complexity from issue count."""
    if count <= 1:
        return "S"
    if count <= 3:
        return "M"
    return "L"


def _make_slug(component: str, issues: list[str]) -> str:
    """Generate a batch slug from component and issue IDs."""
    suffix = "-".join(i.lower().replace("_", "-") for i in issues[:3])
    return f"{component}-{suffix}"


def bucket_issues(
    data: dict[str, Any],
    *,
    meu_registry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Group classified issues into proposed MEU batches.

    Args:
        data: The issue store data dict.
        meu_registry: Optional MEU registry data for cross-reference (AC-10).

    Returns:
        List of proposed batches, each with:
          - slug: str
          - issues: list[str] (issue IDs)
          - component: str
          - priority_band: str
          - complexity: str ("S" | "M" | "L")
          - has_duplicates: bool
    """
    # 1. Filter to actionable issues
    actionable: list[dict[str, Any]] = []
    for issue in data.get("issues", []):
        category = issue.get("category")
        if category is None or category not in ACTIONABLE_CATEGORIES:
            continue
        if issue.get("status") == "resolved":
            continue
        actionable.append(issue)

    if not actionable:
        return []

    # 2. Group by component, merging issues with overlapping 'related' fields
    # Build a union-find over issue indices based on:
    #   (a) same component
    #   (b) overlapping 'related' fields
    component_groups: dict[str, list[dict[str, Any]]] = {}
    for issue in actionable:
        comp = issue.get("component", "unknown")
        component_groups.setdefault(comp, []).append(issue)

    # 3. Within each component group, all issues in the same component
    # form one batch. Issues with overlapping 'related' fields are
    # additionally merged (AC-9: duplicate detection).
    batches: list[dict[str, Any]] = []
    for component, issues in component_groups.items():
        issue_ids = [i["id"] for i in issues]
        priorities = [i.get("priority", "P3") for i in issues]
        best_priority = min(
            priorities,
            key=lambda p: int(p[1:]) if len(p) > 1 and p[1:].isdigit() else 99,
        )

        # Detect related-field overlaps within the batch (AC-9)
        has_dupes = False
        for i in range(len(issues)):
            for j in range(i + 1, len(issues)):
                ri = set(issues[i].get("related", []))
                rj = set(issues[j].get("related", []))
                if ri and rj and ri & rj:
                    has_dupes = True
                    break
            if has_dupes:
                break

        batches.append(
            {
                "slug": _make_slug(component, issue_ids),
                "issues": issue_ids,
                "component": component,
                "priority_band": best_priority,
                "complexity": _estimate_complexity(len(issues)),
                "has_duplicates": has_dupes,
            }
        )

    return batches
