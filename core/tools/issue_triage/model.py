"""Issue Triage SSOT — load, validate, save, add.

Loads `known-issues.yaml`, validates against schema rules,
and provides typed access to the data + save-back.

Mirrors the `tools/meu_status/model.py` pattern.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# ISO 8601 date pattern (YYYY-MM-DD)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ─── Paths ────────────────────────────────────────────────────────────────

_PACKAGE_DIR = Path(__file__).parent
CONTEXT_DIR = Path(__file__).parent.parent.parent / ".agent" / "context"
DEFAULT_SSOT_PATH = CONTEXT_DIR / "known-issues.yaml"
DEFAULT_MD_PATH = CONTEXT_DIR / "known-issues.md"


# ─── Enums ────────────────────────────────────────────────────────────────

VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low"})

VALID_COMPONENTS = frozenset({"core", "infrastructure", "api", "ui", "mcp-server"})

VALID_STATUSES = frozenset(
    {
        "open",
        "in_progress",
        "workaround",
        "mitigated",
        "resolved",
        "candidate",
        "dismissed",
    }
)

VALID_EFFORTS = frozenset({"XS", "S", "M", "L", "XL"})

VALID_CATEGORIES = frozenset(
    {
        "MEU-NEW",
        "MEU-EXPAND",
        "CONFIGURATION",
        "DOCUMENTATION",
        "UPSTREAM",
        "DESIGN-DECISION",
        "MONITORING",
        "DEFER",
        "CLOSE",
        # Workflow taxonomy additions (issue-triage-workflow-v2)
        "PLAN-NEW",
        "ARCH-DECISION",
        "BLOCKED",
        "WORKAROUND-OK",
        "TECH-DEBT",
    }
)

VALID_PRIORITIES = frozenset({"P0", "P1", "P2", "P3", "P4"})

SEVERITY_ICONS: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
}

STATUS_ICONS: dict[str, str] = {
    "open": "⬜",
    "in_progress": "🔵",
    "workaround": "🟡",
    "mitigated": "🟢",
    "resolved": "✅",
    "candidate": "📋",
    "dismissed": "❌",
}

# Required fields for every issue
REQUIRED_FIELDS = frozenset(
    {
        "id",
        "title",
        "severity",
        "component",
        "status",
        "discovered",
        "root_cause",
        "blast_radius",
    }
)


# ─── Exceptions ───────────────────────────────────────────────────────────


class IssueTriageError(Exception):
    """Base error for Issue Triage operations."""


class SchemaValidationError(IssueTriageError):
    """YAML data fails schema validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} validation error(s): {'; '.join(errors[:5])}")


class DuplicateIdError(IssueTriageError):
    """Duplicate issue ID detected."""

    def __init__(self, issue_id: str) -> None:
        self.issue_id = issue_id
        super().__init__(f"Duplicate issue ID: '{issue_id}'")


# ─── Validation ───────────────────────────────────────────────────────────


def validate(data: dict[str, Any]) -> list[str]:
    """Validate issue store data against schema + business rules.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []

    # 1. Top-level structure
    if not isinstance(data, dict):
        return ["[schema] Root must be a mapping"]

    if "version" not in data:
        errors.append("[schema] Missing required field: version")

    if "issues" not in data:
        errors.append("[schema] Missing required field: issues")
        return errors

    if not isinstance(data["issues"], list):
        errors.append("[schema] 'issues' must be a list")
        return errors

    # 2. Per-issue validation
    seen_ids: set[str] = set()

    for idx, issue in enumerate(data["issues"]):
        prefix = f"[schema] issues[{idx}]"

        if not isinstance(issue, dict):
            errors.append(f"{prefix}: must be a mapping")
            continue

        # Required fields
        for field in REQUIRED_FIELDS:
            if field not in issue:
                errors.append(f"{prefix}: missing required field '{field}'")

        # Enum validation
        if "severity" in issue and issue["severity"] not in VALID_SEVERITIES:
            errors.append(
                f"{prefix}.severity: '{issue['severity']}' is not a valid severity. "
                f"Valid: {sorted(VALID_SEVERITIES)}"
            )

        if "component" in issue and issue["component"] not in VALID_COMPONENTS:
            errors.append(
                f"{prefix}.component: '{issue['component']}' is not a valid component. "
                f"Valid: {sorted(VALID_COMPONENTS)}"
            )

        if "status" in issue and issue["status"] not in VALID_STATUSES:
            errors.append(
                f"{prefix}.status: '{issue['status']}' is not a valid status. "
                f"Valid: {sorted(VALID_STATUSES)}"
            )

        # Date field validation (discovered)
        if "discovered" in issue:
            disc = issue["discovered"]
            if isinstance(disc, str) and disc != "":
                if not _ISO_DATE_RE.match(disc):
                    errors.append(
                        f"{prefix}.discovered: '{disc}' is not a valid ISO date (YYYY-MM-DD)"
                    )
            elif not isinstance(disc, str):
                errors.append(
                    f"{prefix}.discovered: must be a string (YYYY-MM-DD or empty)"
                )

        # Optional enum validation
        if "effort" in issue and issue["effort"] not in VALID_EFFORTS:
            errors.append(
                f"{prefix}.effort: '{issue['effort']}' is not a valid effort. "
                f"Valid: {sorted(VALID_EFFORTS)}"
            )

        if "category" in issue and issue["category"] not in VALID_CATEGORIES:
            errors.append(
                f"{prefix}.category: '{issue['category']}' is not a valid category. "
                f"Valid: {sorted(VALID_CATEGORIES)}"
            )

        if "priority" in issue and issue["priority"] not in VALID_PRIORITIES:
            errors.append(
                f"{prefix}.priority: '{issue['priority']}' is not a valid priority. "
                f"Valid: {sorted(VALID_PRIORITIES)}"
            )

        # Verification metadata validation
        if "verification" in issue:
            ver = issue["verification"]
            if not isinstance(ver, dict):
                errors.append(f"{prefix}.verification: must be a mapping")
            else:
                # last_checked: must be ISO date string
                if "last_checked" in ver:
                    lc = ver["last_checked"]
                    if not isinstance(lc, str):
                        errors.append(
                            f"{prefix}.verification.last_checked: must be a date string (YYYY-MM-DD)"
                        )
                    elif not _ISO_DATE_RE.match(lc):
                        errors.append(
                            f"{prefix}.verification.last_checked: '{lc}' is not a valid ISO date"
                        )
                # method: must be str
                if "method" in ver and not isinstance(ver["method"], str):
                    errors.append(f"{prefix}.verification.method: must be a string")
                # result: must be str
                if "result" in ver and not isinstance(ver["result"], str):
                    errors.append(f"{prefix}.verification.result: must be a string")
                # evidence_file: must be str
                if "evidence_file" in ver and not isinstance(ver["evidence_file"], str):
                    errors.append(
                        f"{prefix}.verification.evidence_file: must be a string"
                    )

        # meu_links validation
        if "meu_links" in issue:
            if not isinstance(issue["meu_links"], list):
                errors.append(f"{prefix}.meu_links: must be a list")

        # Optional string field validation
        for str_field in ("resolution_path", "notes"):
            if str_field in issue and not isinstance(issue[str_field], str):
                errors.append(f"{prefix}.{str_field}: must be a string")

        # Optional list-of-strings field validation
        for list_field in ("blocks", "blocked_by", "related"):
            if list_field in issue:
                val = issue[list_field]
                if not isinstance(val, list):
                    errors.append(f"{prefix}.{list_field}: must be a list")
                elif not all(isinstance(item, str) for item in val):
                    errors.append(f"{prefix}.{list_field}: all items must be strings")

        # Enrichment field validation (optional dict)
        if "enrichment" in issue:
            enr = issue["enrichment"]
            if not isinstance(enr, dict):
                errors.append(f"{prefix}.enrichment: must be a mapping")
            else:
                # questions_asked: must be list
                if "questions_asked" in enr and not isinstance(
                    enr["questions_asked"], list
                ):
                    errors.append(
                        f"{prefix}.enrichment.questions_asked: must be a list"
                    )
                # answers: must be list
                if "answers" in enr and not isinstance(enr["answers"], list):
                    errors.append(f"{prefix}.enrichment.answers: must be a list")
                # decided_by: must be str
                if "decided_by" in enr and not isinstance(enr["decided_by"], str):
                    errors.append(f"{prefix}.enrichment.decided_by: must be a string")

        # Duplicate ID check
        issue_id = issue.get("id")
        if issue_id is not None:
            if issue_id in seen_ids:
                errors.append(f"[business] Duplicate issue ID: '{issue_id}'")
            seen_ids.add(issue_id)

    return errors


def validate_strict(data: dict[str, Any]) -> None:
    """Validate and raise on first error."""
    errors = validate(data)
    if errors:
        raise SchemaValidationError(errors)


# ─── Load / Save ──────────────────────────────────────────────────────────


def load(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the SSOT YAML file.

    Returns the parsed data dict.
    Raises SchemaValidationError if invalid, FileNotFoundError if missing.
    """
    ssot_path = path or DEFAULT_SSOT_PATH
    if not ssot_path.exists():
        raise FileNotFoundError(f"SSOT file not found: {ssot_path}")

    with ssot_path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)

    if data is None:
        raise IssueTriageError(f"SSOT file is empty: {ssot_path}")

    validate_strict(data)
    return data


def save(data: dict[str, Any], path: Path | None = None) -> None:
    """Validate and save the SSOT YAML file.

    Re-validates before writing to prevent corruption.
    """
    validate_strict(data)

    ssot_path = path or DEFAULT_SSOT_PATH
    ssot_path.parent.mkdir(parents=True, exist_ok=True)

    with ssot_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Known Issues SSOT — managed by tools/issue_triage.py\n")
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=200,
        )


# ─── Helpers ──────────────────────────────────────────────────────────────


def get_issue(data: dict[str, Any], issue_id: str) -> dict[str, Any] | None:
    """Find an issue by ID."""
    for issue in data.get("issues", []):
        if issue["id"] == issue_id:
            return issue
    return None


def add_issue(
    data: dict[str, Any],
    *,
    id: str,
    title: str,
    severity: str,
    component: str,
    status: str,
    discovered: str,
    root_cause: str,
    blast_radius: str,
    **optional_fields: Any,
) -> dict[str, Any]:
    """Add a new issue to the store with schema validation.

    Returns the modified data dict.
    Raises IssueTriageError if ID already exists.
    Raises SchemaValidationError if the new issue is invalid.
    """
    # Check for duplicate ID
    if get_issue(data, id) is not None:
        raise DuplicateIdError(id)

    new_issue: dict[str, Any] = {
        "id": id,
        "title": title,
        "severity": severity,
        "component": component,
        "status": status,
        "discovered": discovered,
        "root_cause": root_cause,
        "blast_radius": blast_radius,
    }

    # Add optional fields
    for key, value in optional_fields.items():
        if value is not None:
            new_issue[key] = value

    data.setdefault("issues", []).append(new_issue)

    # Validate after adding
    errors = validate(data)
    if errors:
        # Rollback
        data["issues"].pop()
        raise SchemaValidationError(errors)

    return data
