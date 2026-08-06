"""MEU Status SSOT — query and retrieve operations.

Provides list, get, next, stats with filters including --unblocked.
"""

from __future__ import annotations

from typing import Any

from tools.meu_status.model import (
    COMPLETED_STATUSES,
    VALID_STATUSES,
    compute_band_counts,
    get_meu,
)


def list_meus(
    data: dict[str, Any],
    *,
    status: str | None = None,
    band: str | None = None,
    phase: str | None = None,
    unblocked: bool = False,
) -> list[dict[str, Any]]:
    """List MEUs with optional filters.

    Args:
        status: Filter by canonical status value.
        band: Filter by priority band.
        phase: Filter by phase ID.
        unblocked: If True (requires status="pending"), include only MEUs
                   whose depends_on are all approved AND dependency_parse_status != "ambiguous".
    """
    meus = data.get("meus", [])
    result = []

    for meu in meus:
        # Status filter
        if status and meu["status"] != status:
            continue

        # Band filter
        if band and meu["band"] != band:
            continue

        # Phase filter
        if phase and meu["phase"] != phase:
            continue

        # Unblocked filter
        if unblocked:
            if not _is_unblocked(meu, data):
                continue

        result.append(meu)

    return result


def _is_unblocked(meu: dict[str, Any], data: dict[str, Any]) -> bool:
    """Check if a MEU is unblocked.

    Unblocked = pending AND dependency_parse_status != "ambiguous" AND
    all depends_on have status in COMPLETED_STATUSES.
    """
    if meu["status"] != "pending":
        return False

    if meu["dependency_parse_status"] == "ambiguous":
        return False

    for dep_key in meu.get("depends_on", []):
        dep = get_meu(data, dep_key)
        if dep is None:
            return False  # Unknown dep = not unblocked
        if dep["status"] not in COMPLETED_STATUSES:
            return False

    return True


def next_meus(
    data: dict[str, Any],
    *,
    band: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Get the next pending+unblocked MEUs ordered by matrix/section order then row_key.

    Args:
        band: Optional band filter.
        limit: Max results (default 5).
    """
    candidates = list_meus(data, status="pending", unblocked=True, band=band)

    # Sort by matrix_item (semantic order), then row_key
    candidates.sort(key=lambda m: (_matrix_sort_key(m["matrix_item"]), m["row_key"]))

    return candidates[:limit]


def _matrix_sort_key(item: str) -> tuple[float, str]:
    """Parse matrix_item into a sortable tuple.

    Handles: "1", "3a", "10a", "49.6", "30.24", "5.A"
    """
    # Try to extract a numeric prefix
    import re

    match = re.match(r"^(\d+(?:\.\d+)?)(.*)", item)
    if match:
        num = float(match.group(1))
        suffix = match.group(2).lower()
        return (num, suffix)
    return (9999.0, item.lower())


def get_stats(data: dict[str, Any]) -> dict[str, Any]:
    """Compute summary statistics.

    Returns:
        {
            "total": int,
            "by_status": {status: count, ...},
            "by_band": {band: {"count": N, "completed": M}, ...},
            "completed": int,
            "pending": int,
            "in_progress": int,
        }
    """
    meus = data.get("meus", [])

    by_status: dict[str, int] = {}
    for s in VALID_STATUSES:
        by_status[s] = 0
    for meu in meus:
        by_status[meu["status"]] = by_status.get(meu["status"], 0) + 1

    by_band = compute_band_counts(data)

    return {
        "total": len(meus),
        "by_status": by_status,
        "by_band": by_band,
        "completed": sum(1 for m in meus if m["status"] in COMPLETED_STATUSES),
        "pending": by_status.get("pending", 0),
        "in_progress": by_status.get("in_progress", 0),
    }
