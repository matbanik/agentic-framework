"""Issue Triage — migration from markdown to YAML.

Parses the existing known-issues.md and converts to YAML entries.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


from tools.issue_triage.model import (
    DEFAULT_MD_PATH,
    DEFAULT_SSOT_PATH,
    VALID_SEVERITIES,
    save,
    validate,
)


# Component name normalization map
_COMPONENT_MAP: dict[str, str] = {
    "core": "core",
    "infrastructure": "infrastructure",
    "infra": "infrastructure",
    "api": "api",
    "ui": "ui",
    "mcp-server": "mcp-server",
    "mcp": "mcp-server",
    "mcp server": "mcp-server",
}

# Status normalization map
_STATUS_MAP: dict[str, str] = {
    "open": "open",
    "in_progress": "in_progress",
    "workaround": "workaround",
    "mitigated": "mitigated",
    "resolved": "resolved",
    "partially mitigated": "mitigated",
    "partially resolved": "mitigated",
    "active": "open",
    "closed": "resolved",
}


def parse_markdown_issues(md_path: Path) -> list[dict[str, Any]]:
    """Parse existing known-issues.md into issue dicts.

    Handles the `### [ID] — Title` format with `- **Key:** Value` metadata.
    """
    content = md_path.read_text(encoding="utf-8")
    issues: list[dict[str, Any]] = []

    # Split on ### headers
    header_re = re.compile(r"^### \[([^\]]+)\]\s*[—–-]\s*(.+)$", re.MULTILINE)

    matches = list(header_re.finditer(content))

    for i, match in enumerate(matches):
        issue_id = match.group(1).strip()
        title = match.group(2).strip()

        # Extract body between this header and the next
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()

        issue = _parse_issue_body(issue_id, title, body)
        issues.append(issue)

    return issues


def _parse_issue_body(issue_id: str, title: str, body: str) -> dict[str, Any]:
    """Parse the body of an issue section into a dict."""
    issue: dict[str, Any] = {
        "id": issue_id,
        "title": title,
        "severity": "medium",  # default
        "component": "core",  # default
        "status": "open",  # default
        "discovered": "",
        "root_cause": "",
        "blast_radius": "",
    }

    # Extract key-value pairs from `- **Key:** Value` format
    kv_re = re.compile(r"^-\s*\*\*([^*:]+):?\*\*:?\s*(.+)$", re.MULTILINE)
    for kv_match in kv_re.finditer(body):
        key = kv_match.group(1).strip().lower()
        value = kv_match.group(2).strip()

        if key == "severity":
            severity = _normalize_severity(value)
            if severity:
                issue["severity"] = severity

        elif key == "component":
            component = _normalize_component(value)
            if component:
                issue["component"] = component

        elif key == "discovered":
            # Extract date portion
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", value)
            if date_match:
                issue["discovered"] = date_match.group(1)

        elif key == "status":
            status = _normalize_status(value)
            if status:
                issue["status"] = status

        elif key == "details":
            # Use details as root_cause and blast_radius source
            if not issue["root_cause"]:
                issue["root_cause"] = _truncate(value, 200)

        elif key == "fix" or key == "fix scope":
            if not issue["blast_radius"]:
                issue["blast_radius"] = _truncate(value, 200)

    # Extract any remaining body text as details
    detail_re = re.compile(r"^-\s*\*\*Details\*\*[:]\s*(.+)$", re.MULTILINE | re.DOTALL)
    detail_match = detail_re.search(body)
    if detail_match and not issue["root_cause"]:
        issue["root_cause"] = _truncate(detail_match.group(1).strip(), 200)

    return issue


def _normalize_severity(value: str) -> str | None:
    """Normalize severity from markdown to enum value."""
    value_lower = value.lower()
    for sev in VALID_SEVERITIES:
        if sev in value_lower:
            return sev
    return None


def _normalize_component(value: str) -> str | None:
    """Normalize component from markdown to enum value."""
    value_lower = value.lower()
    # Try parenthetical hint first: "api (routes/...)"
    paren_match = re.match(r"(\w[\w-]*)", value_lower)
    if paren_match:
        raw = paren_match.group(1)
        if raw in _COMPONENT_MAP:
            return _COMPONENT_MAP[raw]

    # Try longer substring matches
    for key, mapped in _COMPONENT_MAP.items():
        if key in value_lower:
            return mapped

    return None


def _normalize_status(value: str) -> str | None:
    """Normalize status from markdown to enum value."""
    value_lower = value.lower()
    for key, mapped in _STATUS_MAP.items():
        if key in value_lower:
            return mapped
    return None


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len chars, ending with '...' if needed."""
    # Strip markdown artifacts
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def migrate(
    md_path: Path | None = None,
    yaml_path: Path | None = None,
    *,
    dry_run: bool = False,
) -> int:
    """Migrate known-issues.md → known-issues.yaml.

    Returns 0 on success, 1 on error.
    """
    source = md_path or DEFAULT_MD_PATH
    target = yaml_path or DEFAULT_SSOT_PATH

    if not source.exists():
        print(f"ERROR: Source file not found: {source}", file=sys.stderr)
        return 1

    print(f"Parsing {source.name}...")

    # Guard: detect auto-generated markdown (table format, not legacy ### headers)
    content = source.read_text(encoding="utf-8")
    if "Auto-generated from `known-issues.yaml`" in content:
        print(
            "ERROR: Source file is auto-generated markdown (from YAML render). "
            "Migration is only for legacy hand-written known-issues.md files. "
            "The YAML SSOT already exists — use `stats` or `list` to query it.",
            file=sys.stderr,
        )
        return 1

    issues = parse_markdown_issues(source)
    print(f"  Found {len(issues)} issues")

    store: dict[str, Any] = {
        "version": 1,
        "issues": issues,
    }

    errors = validate(store)
    if errors:
        print(f"\nWARNING: {len(errors)} validation warning(s):", file=sys.stderr)
        for err in errors[:10]:
            print(f"  {err}", file=sys.stderr)

    if dry_run:
        print(f"\n[DRY RUN] Would write {len(issues)} issues to {target.name}")
        # Print summary
        for issue in issues:
            print(
                f"  {issue['severity']:8s} | {issue['id']:25s} | {issue['title'][:50]}"
            )
        return 0

    save(store, target)
    print(f"\nOK: Wrote {len(issues)} issues to {target.name}")
    return 0
