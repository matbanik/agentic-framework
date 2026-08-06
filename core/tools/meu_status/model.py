"""MEU Status SSOT — load, validate, save.

Loads `meu-status.yaml`, validates against the JSON Schema,
and provides typed access to the data + save-back.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml

try:
    import jsonschema
except ImportError as exc:
    raise ImportError("jsonschema is required: `uv add jsonschema`") from exc


# ─── Paths ────────────────────────────────────────────────────────────────

_PACKAGE_DIR = Path(__file__).parent
SCHEMA_PATH = _PACKAGE_DIR / "meu-status.schema.json"
CONTEXT_DIR = Path(__file__).parent.parent.parent / ".agent" / "context"
DEFAULT_SSOT_PATH = CONTEXT_DIR / "meu-status.yaml"


# ─── Status Enum ──────────────────────────────────────────────────────────

VALID_STATUSES = frozenset(
    {
        "pending",
        "deferred",
        "in_progress",
        "ready_for_review",
        "changes_required",
        "approved",
        "closed",
    }
)

# Status values that count as "completed" for summary aggregates
COMPLETED_STATUSES = frozenset({"approved", "closed"})

# Status icon mapping (for rendering)
STATUS_ICONS: dict[str, str] = {
    "pending": "⬜",
    "deferred": "⏸",
    "in_progress": "🔵",
    "ready_for_review": "🟡",
    "changes_required": "🔴",
    "approved": "✅",
    "closed": "🚫",
}


# ─── Schema Loading ──────────────────────────────────────────────────────


def _load_schema() -> dict[str, Any]:
    """Load and cache the JSON Schema."""
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


_SCHEMA_CACHE: dict[str, Any] | None = None


def get_schema() -> dict[str, Any]:
    """Return the cached JSON Schema."""
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = _load_schema()
    return _SCHEMA_CACHE


# ─── Validation ───────────────────────────────────────────────────────────


class MeuStatusError(Exception):
    """Base error for MEU Status operations."""


class SchemaValidationError(MeuStatusError):
    """YAML data fails JSON Schema validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} validation error(s): {'; '.join(errors[:3])}")


class DuplicateRowKeyError(MeuStatusError):
    """Duplicate row_key detected."""

    def __init__(self, duplicates: list[str]) -> None:
        self.duplicates = duplicates
        super().__init__(f"Duplicate row_key(s): {', '.join(duplicates)}")


class ClosedReasonMissingError(MeuStatusError):
    """MEU with status 'closed' is missing closed_reason."""

    def __init__(self, row_key: str) -> None:
        self.row_key = row_key
        super().__init__(f"MEU '{row_key}' has status 'closed' but no closed_reason")


class PhaseReferenceError(MeuStatusError):
    """MEU references a phase ID that doesn't exist."""

    def __init__(self, row_key: str, phase: str) -> None:
        self.row_key = row_key
        self.phase = phase
        super().__init__(f"MEU '{row_key}' references unknown phase '{phase}'")


def validate(data: dict[str, Any]) -> list[str]:
    """Validate data against the JSON Schema + business rules.

    Returns a list of error messages (empty = valid).
    Raises nothing — caller decides severity.
    """
    errors: list[str] = []

    # 1. JSON Schema validation
    schema = get_schema()
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"[schema] {path}: {err.message}")

    if errors:
        # Don't run business rules if schema is broken
        return errors

    # 2. Unique row_key check
    row_keys: list[str] = [m["row_key"] for m in data.get("meus", [])]
    seen: set[str] = set()
    duplicates: list[str] = []
    for rk in row_keys:
        if rk in seen:
            duplicates.append(rk)
        seen.add(rk)
    if duplicates:
        errors.append(f"[business] Duplicate row_key(s): {', '.join(duplicates)}")

    # 3. Phase FK check
    phase_ids = {p["id"] for p in data.get("phases", [])}
    for meu in data.get("meus", []):
        if meu["phase"] not in phase_ids:
            errors.append(
                f"[business] MEU '{meu['row_key']}' references unknown phase '{meu['phase']}'"
            )

    # 4. Closed reason check
    for meu in data.get("meus", []):
        if meu["status"] == "closed" and not meu.get("closed_reason"):
            errors.append(
                f"[business] MEU '{meu['row_key']}' has status 'closed' but no closed_reason"
            )

    # 5. Status enum check (redundant with schema but explicit)
    for meu in data.get("meus", []):
        if meu["status"] not in VALID_STATUSES:
            errors.append(
                f"[business] MEU '{meu['row_key']}' has invalid status '{meu['status']}'"
            )

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
    Raises SchemaValidationError if invalid.
    """
    ssot_path = path or DEFAULT_SSOT_PATH
    if not ssot_path.exists():
        raise FileNotFoundError(f"SSOT file not found: {ssot_path}")

    with ssot_path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)

    if data is None:
        raise MeuStatusError(f"SSOT file is empty: {ssot_path}")

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
        # Write schema modeline as first line
        f.write(
            "# yaml-language-server: $schema=../../tools/meu_status/meu-status.schema.json\n"
        )
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=200,
        )


# ─── Helpers ──────────────────────────────────────────────────────────────


def get_meu(data: dict[str, Any], row_key: str) -> dict[str, Any] | None:
    """Find a MEU record by row_key."""
    for meu in data.get("meus", []):
        if meu["row_key"] == row_key:
            return meu
    return None


def update_meu_status(
    data: dict[str, Any],
    row_key: str,
    new_status: str,
    *,
    note: str | None = None,
    plan: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Update a MEU's status in the data, auto-stamping `updated`.

    Returns the modified data dict.
    Raises MeuStatusError if row_key not found or status invalid.
    """
    if new_status not in VALID_STATUSES:
        raise MeuStatusError(
            f"Invalid status: '{new_status}'. Valid: {sorted(VALID_STATUSES)}"
        )

    meu = get_meu(data, row_key)
    if meu is None:
        raise MeuStatusError(f"Unknown row_key: '{row_key}'")

    if new_status == "closed" and not reason:
        raise ClosedReasonMissingError(row_key)

    meu["status"] = new_status
    meu["updated"] = date.today().isoformat()
    # Refresh BOTH surface labels so neither renders stale text after an update.
    labels = meu.setdefault("status_labels", {"registry": None, "build_plan": None})
    labels["registry"] = f"{STATUS_ICONS[new_status]} {new_status}"
    labels["build_plan"] = STATUS_ICONS[new_status]

    if note is not None:
        meu["note"] = note
    if plan is not None:
        meu["execution_plan"] = plan
    if reason is not None:
        meu["closed_reason"] = reason

    return data


def compute_band_counts(data: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Compute count/completed per summary band from MEU data.

    Returns {band_key: {"count": N, "completed": M}}.
    """
    counts: dict[str, dict[str, int]] = {}
    for band in data.get("summary_bands", []):
        counts[band["key"]] = {"count": 0, "completed": 0}

    for meu in data.get("meus", []):
        band_key = meu["band"]
        if band_key not in counts:
            counts[band_key] = {"count": 0, "completed": 0}
        counts[band_key]["count"] += 1
        if meu["status"] in COMPLETED_STATUSES:
            counts[band_key]["completed"] += 1

    return counts
