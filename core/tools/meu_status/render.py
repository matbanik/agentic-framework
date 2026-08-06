"""MEU Status SSOT — render YAML→Markdown regions.

Regenerates the 3 generated surfaces between named AUTOGEN markers:
  1. :phase-tracker     (BUILD_PLAN.md — Phase Status Tracker)
  2. :summary           (BUILD_PLAN.md — MEU Summary)
  3. :registry          (meu-registry.md — per-phase MEU tables)

Content outside markers is byte-identical; missing, duplicate, or nested
markers → hard error (render aborts non-zero).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from tools.meu_status.model import (
    COMPLETED_STATUSES,
    STATUS_ICONS,
    compute_band_counts,
    load,
)


# ─── Paths ────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).parent.parent.parent
BUILD_PLAN_PATH = _ROOT / "docs" / "BUILD_PLAN.md"
REGISTRY_PATH = _ROOT / ".agent" / "context" / "meu-registry.md"

# ─── Marker Protocol ─────────────────────────────────────────────────────

BEGIN_MARKER = "<!-- BEGIN AUTOGEN:meu-status:{region} -->"
END_MARKER = "<!-- END AUTOGEN:meu-status:{region} -->"


def _begin(region: str) -> str:
    return BEGIN_MARKER.format(region=region)


def _end(region: str) -> str:
    return END_MARKER.format(region=region)


# ─── Region Replacement ──────────────────────────────────────────────────


def replace_region(content: str, region: str, new_body: str) -> str:
    """Replace the content between BEGIN/END markers for `region`.

    Raises ValueError on missing, duplicate, or nested markers.
    """
    begin = _begin(region)
    end = _end(region)

    # Count occurrences
    begin_count = content.count(begin)
    end_count = content.count(end)

    if begin_count == 0 or end_count == 0:
        raise ValueError(f"Missing AUTOGEN markers for region '{region}'")
    if begin_count > 1 or end_count > 1:
        raise ValueError(f"Duplicate AUTOGEN markers for region '{region}'")

    # Find positions
    begin_idx = content.index(begin)
    end_idx = content.index(end)

    if end_idx <= begin_idx:
        raise ValueError(f"END marker before BEGIN for region '{region}'")

    # Check for nesting (another BEGIN between our BEGIN and END)
    between = content[begin_idx + len(begin) : end_idx]
    if "<!-- BEGIN AUTOGEN:meu-status:" in between:
        raise ValueError(f"Nested AUTOGEN markers found inside region '{region}'")

    # Replace: keep the marker lines, replace content between them
    before = content[: begin_idx + len(begin)]
    after = content[end_idx:]

    return before + "\n" + new_body + "\n" + after


# ─── Renderers ────────────────────────────────────────────────────────────


def render_phase_tracker(data: dict[str, Any]) -> str:
    """Render the Phase Status Tracker table."""
    lines = []
    lines.append("")
    lines.append("| Phase | Status | Last Updated |")
    lines.append("|-------|--------|--------------|")

    for phase in data["phases"]:
        # Compute phase-level status from member MEUs
        phase_meus = [m for m in data["meus"] if m["phase"] == phase["id"]]

        if not phase_meus:
            status_text = "⚪ Not Started"
        else:
            all_approved = all(m["status"] in COMPLETED_STATUSES for m in phase_meus)
            any_started = any(m["status"] != "pending" for m in phase_meus)

            if all_approved:
                status_text = "✅ Completed"
            elif any_started:
                status_text = "🟡 In Progress"
            else:
                status_text = "⚪ Not Started"

        # Append phase note if present
        if phase.get("note"):
            status_text += f" ({phase['note']})"

        last_updated = phase.get("last_updated") or "—"
        name = f"{phase['id']} — {phase['name']}"
        lines.append(f"| {name} | {status_text} | {last_updated} |")

    lines.append("")
    return "\n".join(lines)


def render_summary(data: dict[str, Any]) -> str:
    """Render the MEU Summary table (counts computed from data)."""
    band_counts = compute_band_counts(data)

    lines = []
    lines.append("")
    lines.append("| Priority | MEU Range | Count | Completed |")
    lines.append("|----------|-----------|:-----:|:---------:|")

    total_count = 0
    total_completed = 0

    for band in data["summary_bands"]:
        key = band["key"]
        counts = band_counts.get(key, {"count": 0, "completed": 0})
        count = counts["count"]
        completed = counts["completed"]
        total_count += count
        total_completed += completed

        # Format completed — include special status counts if not all approved
        completed_str = str(completed)
        lines.append(
            f"| {band['label']} | {band['range']} | {count} | {completed_str} |"
        )

    # Compute non-standard counts for total line
    all_meus = data.get("meus", [])
    in_progress_count = sum(1 for m in all_meus if m["status"] == "in_progress")
    review_count = sum(1 for m in all_meus if m["status"] == "ready_for_review")
    closed_count = sum(1 for m in all_meus if m["status"] == "closed")

    total_parts = [str(total_completed - closed_count)]
    if in_progress_count:
        total_parts.append(f"{in_progress_count}🔵")
    if review_count:
        total_parts.append(f"{review_count}🟡")
    if closed_count:
        total_parts.append(f"{closed_count}🚫")

    completed_display = " + ".join(total_parts)
    lines.append(f"| **Total** | | **{total_count}** | **{completed_display}** |")

    lines.append("")
    return "\n".join(lines)


def _build_plan_ref(build_ref: dict[str, Any] | None) -> str:
    """Render an MEU's build-plan reference as a Markdown link.

    `build_ref.path` is stored relative to `docs/` (e.g.
    `build-plan/14-quant-foundation.md`); meu-registry.md lives in
    `.agent/context/`, so the link is prefixed with `../../docs/`. Returns
    an en-dash when no reference is available.
    """
    if not build_ref or not build_ref.get("path"):
        return "—"
    text = build_ref.get("text") or build_ref["path"]
    target = f"../../docs/{build_ref['path']}"
    if build_ref.get("anchor"):
        target += f"#{build_ref['anchor']}"
    return f"[{text}]({target})"


def render_registry_table(data: dict[str, Any], phase_id: str) -> str:
    """Render a single phase's MEU table for meu-registry.md."""
    phase_meus = [m for m in data["meus"] if m["phase"] == phase_id]
    if not phase_meus:
        return ""

    lines = []
    lines.append("| MEU | Slug | Matrix | Build Plan Ref | Description | Status |")
    lines.append("|-----|------|:------:|----------------|-------------|:------:|")

    for meu in phase_meus:
        status_text = (
            meu["status_labels"].get("registry")
            or f"{STATUS_ICONS.get(meu['status'], '?')} {meu['status']}"
        )
        ref = _build_plan_ref(meu.get("build_ref"))
        lines.append(
            f"| {meu['id']} | `{meu['slug']}` | {meu['matrix_item']} | {ref} | {meu['description']} | {status_text} |"
        )

    return "\n".join(lines)


def render_registry_block(data: dict[str, Any]) -> str:
    """Build the FULL meu-registry.md generated region.

    Per phase: header + `> Source:` lines (from phases[].sources) + MEU table.
    Then all preserved free-form prose from narrative_sections (institutional
    memory: Execution Order / Evidence / Exit Criteria). Shared by both
    `_render_registry` and `check_drift` so the two can never diverge.
    """
    parts: list[str] = []
    for phase in data["phases"]:
        table = render_registry_table(data, phase["id"])
        if not table:
            continue
        parts.append(f"\n## {phase['name']} ({phase['band']})\n")
        for src in phase.get("sources") or []:
            parts.append(f"> Source: {src}\n")
        parts.append(table)
        parts.append("")

    narrative = data.get("narrative_sections") or []
    if narrative:
        parts.append("\n## Execution Notes & Evidence (preserved)\n")
        parts.append(
            "> Free-form sections preserved from the pre-SSOT registry. "
            "Edit these in `meu-status.yaml` (`narrative_sections`), not here.\n"
        )
        for ns in narrative:
            parts.append(ns["body"].rstrip())
            parts.append("")

    return "\n".join(parts)


# ─── Top-Level Commands ──────────────────────────────────────────────────


def render_all() -> int:
    """Render all 3 surfaces. Returns exit code."""
    try:
        data = load()
    except Exception as e:
        print(f"Error loading SSOT: {e}", file=sys.stderr)
        return 1

    errors: list[str] = []

    # For now, just validate the data loads correctly
    # Full region rendering requires markers to be present in the docs
    print(f"Loaded {len(data['meus'])} MEUs across {len(data['phases'])} phases")
    print(f"Summary bands: {len(data['summary_bands'])}")

    # Verify marker presence before rendering
    for path, regions in [
        (BUILD_PLAN_PATH, ["phase-tracker", "summary"]),
        (REGISTRY_PATH, ["registry"]),
    ]:
        if not path.exists():
            errors.append(f"File not found: {path}")
            continue

        content = path.read_text(encoding="utf-8")
        for region in regions:
            begin = _begin(region)
            end_m = _end(region)
            if begin not in content:
                errors.append(f"Missing BEGIN marker for '{region}' in {path.name}")
            if end_m not in content:
                errors.append(f"Missing END marker for '{region}' in {path.name}")

    if errors:
        print("\nMarker errors (insert markers before rendering):")
        for e in errors:
            print(f"  ❌ {e}")
        return 1

    # Actually render
    _render_build_plan(data)
    _render_registry(data)

    print("✅ All regions rendered successfully.")
    return 0


def _render_build_plan(data: dict[str, Any]) -> None:
    """Render the 2 BUILD_PLAN.md regions."""
    content = BUILD_PLAN_PATH.read_text(encoding="utf-8")

    content = replace_region(content, "phase-tracker", render_phase_tracker(data))
    content = replace_region(content, "summary", render_summary(data))

    BUILD_PLAN_PATH.write_text(content, encoding="utf-8", newline="\n")


def _render_registry(data: dict[str, Any]) -> None:
    """Render the meu-registry.md region (tables + sources + preserved narrative)."""
    content = REGISTRY_PATH.read_text(encoding="utf-8")
    block = render_registry_block(data)
    if block.strip():
        content = replace_region(content, "registry", block)
    REGISTRY_PATH.write_text(content, encoding="utf-8", newline="\n")


def check_drift() -> int:
    """Check if rendered output matches on-disk docs.

    Renders all regions to memory and compares with the current
    on-disk content between AUTOGEN markers. Returns 0 if in sync,
    1 if drifted or errors found.
    """
    try:
        data = load()
    except Exception as e:
        print(f"Error loading SSOT: {e}", file=sys.stderr)
        return 1

    meu_count = len(data.get("meus", []))
    phase_count = len(data.get("phases", []))
    drifted: list[str] = []
    errors: list[str] = []

    # Check BUILD_PLAN.md regions
    if not BUILD_PLAN_PATH.exists():
        errors.append(f"File not found: {BUILD_PLAN_PATH}")
    else:
        bp_content = BUILD_PLAN_PATH.read_text(encoding="utf-8")

        # phase-tracker
        try:
            expected_pt = render_phase_tracker(data)
            current_pt = _extract_region(bp_content, "phase-tracker")
            if current_pt.strip() != expected_pt.strip():
                drifted.append("phase-tracker (BUILD_PLAN.md)")
        except ValueError as e:
            errors.append(f"phase-tracker: {e}")

        # summary
        try:
            expected_sum = render_summary(data)
            current_sum = _extract_region(bp_content, "summary")
            if current_sum.strip() != expected_sum.strip():
                drifted.append("summary (BUILD_PLAN.md)")
        except ValueError as e:
            errors.append(f"summary: {e}")

    # Check meu-registry.md region
    if not REGISTRY_PATH.exists():
        errors.append(f"File not found: {REGISTRY_PATH}")
    else:
        reg_content = REGISTRY_PATH.read_text(encoding="utf-8")
        begin_reg = _begin("registry")
        end_reg = _end("registry")
        if begin_reg not in reg_content or end_reg not in reg_content:
            errors.append("Missing AUTOGEN markers for 'registry' in meu-registry.md")
        else:
            expected_reg = render_registry_block(data)
            if expected_reg.strip():
                try:
                    current_reg = _extract_region(reg_content, "registry")
                    if current_reg.strip() != expected_reg.strip():
                        drifted.append("registry (meu-registry.md)")
                except ValueError as e:
                    errors.append(f"registry: {e}")

    if errors:
        print("❌ Drift check failed — errors:")
        for e in errors:
            print(f"  ❌ {e}")
        return 1

    if drifted:
        print("❌ Drift check failed — regions out of sync:")
        for d in drifted:
            print(f"  ⚠️  {d}")
        return 1

    print(
        f"✅ Drift check passed — SSOT loaded ({meu_count} MEUs, {phase_count} phases), "
        f"rendered regions match on-disk content"
    )
    return 0


def _extract_region(content: str, region: str) -> str:
    """Extract the content between BEGIN/END markers for a region."""
    begin = _begin(region)
    end = _end(region)

    begin_idx = content.index(begin)
    end_idx = content.index(end)

    return content[begin_idx + len(begin) : end_idx]
