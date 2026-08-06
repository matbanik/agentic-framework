"""Issue Triage — render YAML → markdown + drift check.

Generates a compact known-issues.md from the YAML SSOT.
Target: <100 lines (AGENTS.md §Session Discipline).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


from tools.issue_triage.model import (
    DEFAULT_MD_PATH,
    DEFAULT_SSOT_PATH,
    SEVERITY_ICONS,
    STATUS_ICONS,
    load,
)


def render_markdown(
    data: dict[str, Any],
    *,
    include_candidates: bool = False,
) -> str:
    """Render issue store to compact markdown.

    Produces a table-based view grouped by status:
    1. Active Issues (open, in_progress) — detailed table
    2. Mitigated/Workaround — compact table
    3. Candidates (only when include_candidates=True)
    4. Archive link

    Target: <100 lines total.
    """
    issues = data.get("issues", [])

    # Separate candidate/dismissed from main flow
    candidates = [i for i in issues if i.get("status") == "candidate"]
    # Main categories exclude candidate/dismissed
    active = [i for i in issues if i.get("status") in ("open", "in_progress")]
    mitigated = [i for i in issues if i.get("status") in ("workaround", "mitigated")]
    resolved = [i for i in issues if i.get("status") == "resolved"]

    lines: list[str] = []
    lines.append("# Known Issues — {{PROJECT_NAME_TITLE}}")
    lines.append("")
    lines.append(
        "> Auto-generated from `known-issues.yaml` by `tools/issue_triage.py render`."
    )
    lines.append(
        "> Do not edit manually. Run `uv run python tools/issue_triage.py render` to regenerate."
    )
    lines.append("")

    # Summary counts (candidates/dismissed excluded from Active/Mitigated)
    total = len(issues)
    active_count = len(active)
    mitigated_count = len(mitigated)
    resolved_count = len(resolved)
    lines.append(
        f"**Total: {total}** — "
        f"Active: {active_count} | "
        f"Mitigated: {mitigated_count} | "
        f"Resolved: {resolved_count}"
    )
    lines.append("")

    # Active Issues Table — AUDIT-* bulk findings are summarized (session hygiene
    # <100 lines). Full detail remains in known-issues.yaml.
    product_active = [i for i in active if not _is_audit_finding(i)]
    audit_active = [i for i in active if _is_audit_finding(i)]
    if product_active or audit_active:
        lines.append("## Active Issues")
        lines.append("")
        if product_active:
            lines.append("| Sev | ID | Title | Component | Status | Discovered |")
            lines.append("|-----|-----|-------|-----------|--------|------------|")
            for issue in sorted(product_active, key=_severity_sort_key):
                sev_icon = SEVERITY_ICONS.get(issue["severity"], "?")
                status_icon = STATUS_ICONS.get(issue["status"], "?")
                lines.append(
                    f"| {sev_icon} | `{issue['id']}` | {_compact_title(issue['title'])} | "
                    f"{issue['component']} | {status_icon} {issue['status']} | "
                    f"{issue['discovered']} |"
                )
            lines.append("")
        if audit_active:
            by_sev: dict[str, int] = {}
            for issue in audit_active:
                sev = str(issue.get("severity", "low"))
                by_sev[sev] = by_sev.get(sev, 0) + 1
            sev_bits = ", ".join(
                f"{count} {sev}"
                for sev, count in sorted(
                    by_sev.items(), key=lambda item: _SEVERITY_ORDER.get(item[0], 99)
                )
            )
            lines.append(
                f"**Audit findings ({len(audit_active)}):** {sev_bits}. "
                "Listed in `known-issues.yaml` (`AUDIT-*`); not expanded here to keep "
                "this file under the 100-line session-hygiene budget."
            )
            lines.append("")

    # Critical UPSTREAM blockers — compact Dependency / Why / Workaround notes.
    # Only severity=critical + category=UPSTREAM + non-empty notes expand here so
    # the Active table stays under the <100-line session-hygiene budget.
    upstream_detail = [
        i
        for i in product_active
        if i.get("category") == "UPSTREAM"
        and i.get("severity") == "critical"
        and str(i.get("notes") or "").strip()
    ]
    if upstream_detail:
        lines.append("## UPSTREAM (cannot fix in-repo)")
        lines.append("")
        lines.append(
            "These are defects in dependencies we consume, not in {{PROJECT_NAME_TITLE}} application "
            "code. No MEU can close them; workarounds only. Full root_cause / blast_radius "
            "live in `known-issues.yaml`."
        )
        lines.append("")
        for issue in sorted(upstream_detail, key=_severity_sort_key):
            lines.append(f"### `{issue['id']}`")
            lines.append("")
            for bullet in _upstream_note_bullets(str(issue["notes"])):
                lines.append(f"- {bullet}")
            lines.append("")

    # Mitigated/Workaround Table
    if mitigated:
        lines.append("## Mitigated / Workaround")
        lines.append("")
        lines.append("| Sev | ID | Title | Component | Status |")
        lines.append("|-----|-----|-------|-----------|--------|")
        for issue in sorted(mitigated, key=_severity_sort_key):
            sev_icon = SEVERITY_ICONS.get(issue["severity"], "?")
            status_icon = STATUS_ICONS.get(issue["status"], "?")
            lines.append(
                f"| {sev_icon} | `{issue['id']}` | {_compact_title(issue['title'])} | "
                f"{issue['component']} | {status_icon} {issue['status']} |"
            )
        lines.append("")

    # Candidates section (only when explicitly requested)
    if include_candidates and candidates:
        lines.append("## Candidates")
        lines.append("")
        lines.append("| Sev | ID | Title | Component | Discovered |")
        lines.append("|-----|-----|-------|-----------|------------|")
        for issue in sorted(candidates, key=_severity_sort_key):
            sev_icon = SEVERITY_ICONS.get(issue["severity"], "?")
            lines.append(
                f"| {sev_icon} | `{issue['id']}` | {issue['title']} | "
                f"{issue['component']} | {issue['discovered']} |"
            )
        lines.append("")

    # Resolved count
    if resolved:
        lines.append(f"## Resolved ({resolved_count})")
        lines.append("")
        lines.append(
            f"{resolved_count} issues resolved. "
            "Query with `uv run python tools/issue_triage.py list --status resolved`."
        )
        lines.append("")

    # Footer
    lines.append("---")
    lines.append(
        "*Managed by `tools/issue_triage.py`. "
        "See `known-issues.yaml` for full details including root cause, "
        "blast radius, and verification metadata.*"
    )
    lines.append("")

    return "\n".join(lines)


def render_all(
    yaml_path: Path | None = None,
    md_path: Path | None = None,
    *,
    include_candidates: bool = False,
) -> int:
    """Render YAML → markdown file on disk.

    Returns 0 on success.
    """
    yaml_path = yaml_path or DEFAULT_SSOT_PATH
    md_path = md_path or DEFAULT_MD_PATH

    data = load(yaml_path)
    output = render_markdown(data, include_candidates=include_candidates)

    md_path.write_text(output, encoding="utf-8", newline="\n")

    line_count = len(output.strip().splitlines())
    print(f"Rendered {md_path.name}: {line_count} lines")

    if line_count >= 100:
        print(
            f"WARNING: Rendered output is {line_count} lines (target: <100)",
            file=sys.stderr,
        )
        return 1

    return 0


def check_drift(
    yaml_path: Path | None = None,
    md_path: Path | None = None,
) -> int:
    """Check if on-disk markdown matches what would be rendered.

    Returns 0 if synced, 1 if drifted.
    """
    yaml_path = yaml_path or DEFAULT_SSOT_PATH
    md_path = md_path or DEFAULT_MD_PATH

    if not md_path.exists():
        print(f"DRIFT: {md_path.name} does not exist", file=sys.stderr)
        return 1

    data = load(yaml_path)
    expected = render_markdown(data)
    actual = md_path.read_text(encoding="utf-8")

    if expected != actual:
        print(f"DRIFT: {md_path.name} differs from rendered YAML", file=sys.stderr)
        return 1

    print(f"OK: {md_path.name} is up-to-date")
    return 0


# ─── Helpers ──────────────────────────────────────────────────────────────

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_TITLE_MAX = 72


def _severity_sort_key(issue: dict[str, Any]) -> int:
    """Sort issues by severity (critical first)."""
    return _SEVERITY_ORDER.get(issue.get("severity", "low"), 99)


def _is_audit_finding(issue: dict[str, Any]) -> bool:
    """True for platform-architect AUDIT-* bulk findings."""
    return str(issue.get("id", "")).startswith("AUDIT-")


def _compact_title(title: str) -> str:
    """Truncate long titles so the Active table stays within the line budget."""
    text = " ".join(str(title).split())
    if len(text) <= _TITLE_MAX:
        return text
    return text[: _TITLE_MAX - 1].rstrip() + "…"


_UPSTREAM_NOTE_LABELS = (
    "Dependency",
    "Why UPSTREAM",
    "Why no {{PROJECT_NAME_TITLE}} fix",
    "Workaround",
)


def _upstream_note_bullets(notes: str) -> list[str]:
    """Split a structured UPSTREAM notes blob into markdown bullets.

    Expected shape (order flexible):
      **Dependency:** ... **Why UPSTREAM:** ... **Why no {{PROJECT_NAME_TITLE}} fix:** ... **Workaround:** ...
    Falls back to a single collapsed paragraph when labels are absent.
    """
    text = " ".join(notes.split())
    if not text:
        return []

    # Find label positions; keep insertion order of discovered labels.
    found: list[tuple[int, str, int]] = []
    for label in _UPSTREAM_NOTE_LABELS:
        marker = f"**{label}:**"
        idx = text.find(marker)
        if idx >= 0:
            found.append((idx, label, len(marker)))
    if not found:
        return [text]

    found.sort(key=lambda item: item[0])
    bullets: list[str] = []
    for i, (start, label, marker_len) in enumerate(found):
        body_start = start + marker_len
        body_end = found[i + 1][0] if i + 1 < len(found) else len(text)
        body = text[body_start:body_end].strip()
        bullets.append(f"**{label}:** {body}")
    return bullets
