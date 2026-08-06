"""Issue Triage — triage output pipeline.

Generates ephemeral triage-output.yaml that feeds into
/session-grouping and /create-plan workflows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tools.issue_triage.bucket import bucket_issues

# Categories that indicate deferred/non-actionable issues
_DEFERRED_CATEGORIES = frozenset({"DEFER", "CLOSE", "UPSTREAM", "WORKAROUND-OK"})


def generate_triage_output(
    data: dict[str, Any],
    output_path: Path,
    *,
    meu_registry: dict[str, Any] | None = None,
) -> None:
    """Generate ephemeral triage-output.yaml.

    Sections:
      - archived: resolved issues
      - actionable: open issues with actionable categories
      - deferred: issues marked for deferral
      - proposed_batches: output of bucket_issues()

    Each issue entry includes enrichment data (or null if absent).
    """
    archived: list[dict[str, Any]] = []
    actionable: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []

    for issue in data.get("issues", []):
        entry = _make_entry(issue)

        if issue.get("status") == "resolved":
            archived.append(entry)
        elif issue.get("category") in _DEFERRED_CATEGORIES:
            deferred.append(entry)
        else:
            actionable.append(entry)

    # Generate proposed batches
    proposed_batches = bucket_issues(data, meu_registry=meu_registry)

    result = {
        "archived": archived,
        "actionable": actionable,
        "deferred": deferred,
        "proposed_batches": proposed_batches,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(
            "# Auto-generated. Do not edit. Regenerate with `issue_triage.py triage`\n"
        )
        yaml.dump(
            result,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=200,
        )


def _make_entry(issue: dict[str, Any]) -> dict[str, Any]:
    """Create a triage output entry from an issue."""
    return {
        "id": issue.get("id", "unknown"),
        "title": issue.get("title", ""),
        "severity": issue.get("severity", ""),
        "component": issue.get("component", ""),
        "status": issue.get("status", ""),
        "category": issue.get("category"),
        "priority": issue.get("priority"),
        "enrichment": issue.get("enrichment", None),
    }
