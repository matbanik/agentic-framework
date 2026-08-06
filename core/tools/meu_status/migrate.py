"""MEU Status SSOT — migration from Markdown → YAML.

Parses `meu-registry.md` to extract all MEU records and phase metadata,
producing a valid `meu-status.yaml`.

Key design decisions:
- Registry is the primary parse source (most complete data per MEU).
- BUILD_PLAN.md is cross-referenced for build_ref links and phase metadata.
- Status variants (✅ approved/complete/done/2026-XX-XX) all map to "approved".
- Duplicate MEU IDs get row_key suffixes (e.g., MEU-238-edge-liquidity).
- Emits a duplicate-ID reconciliation report (no silent merge).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml


# ─── Paths ────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).parent.parent.parent
REGISTRY_PATH = _ROOT / ".agent" / "context" / "meu-registry.md"
BUILD_PLAN_PATH = _ROOT / "docs" / "BUILD_PLAN.md"
OUTPUT_PATH = _ROOT / ".agent" / "context" / "meu-status.yaml"

# ─── Status Parsing ──────────────────────────────────────────────────────

# Maps raw status text (lowercase, stripped) → canonical status
_STATUS_MAP: dict[str, str] = {
    "approved": "approved",
    "complete": "approved",
    "done": "approved",
    "in-progress": "in_progress",
    "in_progress": "in_progress",
    "planned": "pending",
    "pending": "pending",
    "deferred": "deferred",
    "changes_required": "changes_required",
    "ready_for_review": "ready_for_review",
}

# Icon → canonical status
_ICON_STATUS: dict[str, str] = {
    "✅": "approved",
    "🚫": "closed",
    "🟡": "in_progress",  # 🟡 maps to ready_for_review in legend, but used as in_progress in practice
    "🔵": "in_progress",
    "🔴": "changes_required",
    "⏸": "deferred",
    "⬜": "pending",
}


def parse_status(raw: str) -> tuple[str, str]:
    """Parse raw status text into (canonical_status, original_label).

    Handles: "✅ approved", "✅ 2026-06-16", "✅ complete", "✅ done",
             "🚫 closed — reason", "🟡 in-progress", "⬜ planned"
    """
    raw = raw.strip()
    original = raw

    # Extract leading icon
    icon = ""
    text = raw
    for candidate_icon in _ICON_STATUS:
        if raw.startswith(candidate_icon):
            icon = candidate_icon
            text = raw[len(candidate_icon) :].strip()
            break

    # Check for closed with reason
    if icon == "🚫":
        return "closed", original

    # Check for date-only (e.g., "2026-06-16")
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return "approved", original

    # Try text-based lookup
    text_lower = text.lower().strip()
    # Strip trailing dates/parentheticals for lookup
    text_key = re.sub(r"\s*\(.*$", "", text_lower)
    text_key = re.sub(r"\s*—.*$", "", text_key)
    text_key = text_key.strip()

    if text_key in _STATUS_MAP:
        return _STATUS_MAP[text_key], original

    # Icon-based fallback
    if icon in _ICON_STATUS:
        return _ICON_STATUS[icon], original

    # Unknown — default to pending
    return "pending", original


def extract_date(raw_status: str) -> str | None:
    """Extract YYYY-MM-DD date from status text."""
    match = re.search(r"(\d{4}-\d{2}-\d{2})", raw_status)
    return match.group(1) if match else None


def extract_closed_reason(raw_status: str) -> str | None:
    """Extract closed reason from status text like '🚫 closed — reason'."""
    match = re.search(r"—\s*(.+)", raw_status)
    if match:
        return match.group(1).strip()
    # Try em-dash variants
    match = re.search(r"closed\s*[–—-]\s*(.+)", raw_status, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


# ─── Table Parsing ────────────────────────────────────────────────────────


def parse_registry_table_row(row: str) -> dict[str, str] | None:
    """Parse a single Markdown table row into column values.

    Returns {meu, slug, matrix, description, status} or None if not a data row.
    """
    row = row.strip()
    if not row.startswith("|"):
        return None

    # Split by pipes, strip whitespace
    cells = [c.strip() for c in row.split("|")]
    # Remove empty first/last from leading/trailing pipes
    cells = [c for c in cells if c != ""]

    # Skip separator rows
    if all(set(c) <= {"-", ":", " "} for c in cells):
        return None

    # Skip header rows
    if cells[0].lower() in ("meu", "meu id", "#"):
        return None

    if len(cells) < 5:
        return None

    # Extract slug — strip backticks
    slug = cells[1].strip("`").strip()

    return {
        "meu": cells[0].strip(),
        "slug": slug,
        "matrix": cells[2].strip(),
        "description": cells[3].strip(),
        "status": cells[4].strip(),
    }


def parse_section_header(line: str) -> dict[str, str] | None:
    """Parse a section header like '## Phase 1: Domain Layer (P0)'.

    Returns {phase_id, name, band} or None.
    """
    line = line.strip()
    # Match various header formats:
    # ## Phase 1: Domain Layer (P0)
    # ## Phase 1A: Logging Infrastructure (P0 — Parallel)
    # ## Phase 8c: Options Chain GUI Hardening (P2)
    # ## P1: Trade Reviews & Multi-Account
    # ## P2: Planning & Watchlists
    # ## Phase 9: Scheduling & Pipeline Engine — Domain Foundation (P2.5)
    # ## P2.75 — Expansion: Broker Adapters & Import
    # ## Phase 6m: GUI Style Migration (P0)

    if not line.startswith("## ") and not line.startswith("### "):
        return None

    text = re.sub(r"^#{2,4}\s+", "", line).strip()

    # Try "Phase X: Name (Band)" format
    match = re.match(
        r"Phase\s+(\w+):\s+(.+?)\s*\(([^)]+)\)",
        text,
    )
    if match:
        phase_id = match.group(1)
        name = match.group(2).strip()
        band = match.group(3).strip()
        # Normalize band — strip "— Parallel", etc.
        band = re.sub(r"\s*—\s*.*", "", band).strip()
        return {"phase_id": phase_id, "name": name, "band": band}

    # Try "Phase X: Name — SubName (Band)" format
    match = re.match(
        r"Phase\s+(\w+):\s+(.+?)\s*—\s*(.+?)\s*\(([^)]+)\)",
        text,
    )
    if match:
        phase_id = match.group(1)
        name = f"{match.group(2).strip()} — {match.group(3).strip()}"
        band = match.group(4).strip()
        return {"phase_id": phase_id, "name": name, "band": band}

    # Try "BandLabel: Name" or "BandLabel — Name" format
    match = re.match(r"(P\d+(?:\.\d+\w*)?)\s*[:—–-]\s*(.+)", text)
    if match:
        band = match.group(1).strip()
        name = match.group(2).strip()
        # Strip trailing parenthetical
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        return {"phase_id": band, "name": name, "band": band}

    # Try "Phase Xm: Name (Band)" — for style migration
    match = re.match(r"Phase\s+(\w+):\s+(.+?)(?:\s*\(([^)]+)\))?$", text)
    if match:
        phase_id = match.group(1)
        name = match.group(2).strip()
        band = match.group(3).strip() if match.group(3) else "P0"
        return {"phase_id": phase_id, "name": name, "band": band}

    return None


def extract_dependency_info(desc: str) -> tuple[str, str, list[str]]:
    """Extract dependency info from description text.

    Returns (dependencies_raw, parse_status, depends_on_list).
    """
    # Look for "Depends on: MEU-X" or "Depends MEU-X" patterns
    dep_match = re.search(r"[Dd]epends?\s+(?:on:?\s*)?(.+?)(?:\.|$)", desc)
    if not dep_match:
        return "", "none", []

    raw = dep_match.group(0).strip().rstrip(".")
    dep_text = dep_match.group(1).strip()

    # Try to extract specific MEU IDs
    meu_ids = re.findall(r"(MEU-\w+)", dep_text)
    if meu_ids:
        return raw, "parsed", meu_ids

    # Check for range-style deps like "PW4–PW7"
    range_match = re.search(r"(\w+)\s*[–—-]\s*(\w+)", dep_text)
    if range_match:
        return raw, "ambiguous", []

    return raw, "ambiguous", []


# ─── Migration Engine ────────────────────────────────────────────────────


def _extract_narrative_sections(content: str) -> list[dict[str, Any]]:
    """Extract free-form prose (Execution Order/Evidence/Exit Criteria, etc.) —
    every heading-delimited segment that does NOT contain a MEU table. Preserves
    institutional memory verbatim so a forced re-migrate does not drop it.
    """
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    cur: dict[str, Any] | None = None

    def _slug(text: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        return s or "section"

    def _flush(seg: dict[str, Any] | None) -> None:
        if not seg:
            return
        body_lines: list[str] = seg["body"]
        has_table = any(re.match(r"^\|\s*MEU\s*\|", ln) for ln in body_lines)
        body_text = "\n".join(body_lines).rstrip()
        if has_table or not body_text.strip():
            return
        anchor = _slug(seg["heading"])
        base, i = anchor, 2
        while anchor in seen:
            anchor = f"{base}-{i}"
            i += 1
        seen.add(anchor)
        hashes = "#" * seg["level"]
        sections.append(
            {
                "anchor": anchor,
                "title": seg["heading"],
                "body": f"{hashes} {seg['heading']}\n\n{body_text}".rstrip(),
            }
        )

    for ln in content.splitlines():
        m = re.match(r"^(#{2,4})\s+(.*)$", ln)
        if m:
            _flush(cur)
            cur = {"level": len(m.group(1)), "heading": m.group(2).strip(), "body": []}
        elif cur is not None:
            cur["body"].append(ln)
    _flush(cur)
    return sections


def parse_registry(
    path: Path | None = None,
) -> tuple[dict[str, Any], list[tuple[str, str, str]]]:
    """Parse meu-registry.md into SSOT data structure.

    Returns a tuple of (data_dict, duplicates_list).
    """
    reg_path = path or REGISTRY_PATH
    content = reg_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    phases: list[dict[str, Any]] = []
    meus: list[dict[str, Any]] = []
    narrative_sections: list[dict[str, Any]] = _extract_narrative_sections(content)

    current_phase: dict[str, Any] | None = None
    seen_row_keys: set[str] = set()
    duplicates: list[tuple[str, str, str]] = []  # (meu_id, slug1, slug2)

    source_line: str | None = None

    for line in lines:
        stripped = line.strip()

        # Capture > Source: lines. In the rendered registry the source line
        # appears AFTER its phase header, so attach to the open phase directly;
        # only buffer when no phase is open yet (source before first header).
        if stripped.startswith("> Source:"):
            if current_phase is not None:
                for _text, link in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", stripped):
                    if link not in current_phase["sources"]:
                        current_phase["sources"].append(link)
            else:
                source_line = stripped
            continue

        # Try to parse as section header
        header = parse_section_header(stripped)
        if header:
            current_phase = {
                "id": header["phase_id"],
                "name": header["name"],
                "band": header["band"],
                "sources": [],
                "execution_plans": [],
                "last_updated": None,
                "note": None,
            }
            # Extract source links if we have a source line
            if source_line:
                src_links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", source_line)
                for _text, link in src_links:
                    current_phase["sources"].append(link)
                source_line = None

            # Check if this phase already exists (avoid duplicates)
            existing = [p for p in phases if p["id"] == header["phase_id"]]
            if not existing:
                phases.append(current_phase)
            else:
                current_phase = existing[0]
            continue

        # Try to parse as table row
        row = parse_registry_table_row(stripped)
        if row and current_phase:
            meu_id = row["meu"]
            slug = row["slug"]
            status_text = row["status"]
            description = row["description"]
            matrix_item = row["matrix"]

            canonical_status, original_label = parse_status(status_text)
            updated_date = extract_date(status_text)
            closed_reason = (
                extract_closed_reason(status_text)
                if canonical_status == "closed"
                else None
            )

            # Dependency extraction from description
            deps_raw, deps_status, deps_list = extract_dependency_info(description)

            # Generate unique row_key
            row_key = meu_id
            if row_key in seen_row_keys:
                # Duplicate — append slug suffix
                row_key = f"{meu_id}-{slug}"
                duplicates.append((meu_id, slug, "duplicate in registry"))
                if row_key in seen_row_keys:
                    # Still duplicate — append line number
                    row_key = f"{meu_id}-{slug}-dup"

            seen_row_keys.add(row_key)

            # Update phase last_updated
            if updated_date and current_phase:
                if (
                    not current_phase["last_updated"]
                    or updated_date > current_phase["last_updated"]
                ):
                    current_phase["last_updated"] = updated_date

            meu_record: dict[str, Any] = {
                "row_key": row_key,
                "id": meu_id,
                "slug": slug,
                "phase": current_phase["id"],
                "band": current_phase["band"],
                "matrix_item": matrix_item,
                "build_ref": None,  # Populated from BUILD_PLAN cross-reference
                "description": description,
                "status": canonical_status,
                "status_labels": {
                    "registry": original_label,
                    "build_plan": None,  # Populated from BUILD_PLAN cross-reference
                },
                "surface_overrides": None,
                "dependencies_raw": deps_raw,
                "dependency_parse_status": deps_status,
                "depends_on": deps_list,
                "execution_plan": None,
                "updated": updated_date,
                "closed_reason": closed_reason,
                "note": None,
            }

            meus.append(meu_record)

    # Build summary bands from phases
    summary_bands = _build_summary_bands(phases, meus)

    data: dict[str, Any] = {
        "version": 1,
        "phases": phases,
        "meus": meus,
        "summary_bands": summary_bands,
        "narrative_sections": narrative_sections,
    }

    return data, duplicates


def _build_summary_bands(
    phases: list[dict[str, Any]],
    meus: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build summary bands from phase data."""
    # Group MEUs by band
    band_meus: dict[str, list[str]] = {}
    band_labels: dict[str, str] = {}

    for phase in phases:
        band = phase["band"]
        if band not in band_labels:
            band_labels[band] = f"{band} — {phase['name']}"

    for meu in meus:
        band = meu["band"]
        if band not in band_meus:
            band_meus[band] = []
        band_meus[band].append(meu["id"])

    bands = []
    for band_key in band_labels:
        meu_ids = band_meus.get(band_key, [])
        if not meu_ids:
            continue

        # Build range text
        if len(meu_ids) == 1:
            range_text = meu_ids[0]
        else:
            range_text = f"{meu_ids[0]} → {meu_ids[-1]}"

        bands.append(
            {
                "key": band_key,
                "label": band_labels[band_key],
                "range": range_text,
            }
        )

    return bands


# ─── Cross-Reference with BUILD_PLAN ─────────────────────────────────────


def cross_reference_build_plan(
    data: dict[str, Any],
    bp_path: Path | None = None,
) -> None:
    """Enrich MEU records with build_ref and build_plan status labels from BUILD_PLAN.md."""
    path = bp_path or BUILD_PLAN_PATH
    if not path.exists():
        return

    content = path.read_text(encoding="utf-8")

    # Build a lookup: MEU-ID → build_plan row info
    # Match BUILD_PLAN registry rows like:
    # | MEU-1 | `calculator` | 1 | [01 §1.3](build-plan/01-domain-layer.md) | Description | ✅ |
    bp_pattern = re.compile(
        r"\|\s*(MEU-\w+)\s*\|\s*`([^`]+)`\s*\|\s*([^|]+)\|\s*\[([^\]]*)\]\(([^)]+)\)\s*\|([^|]*)\|([^|]*)\|"
    )

    for match in bp_pattern.finditer(content):
        meu_id = match.group(1).strip()
        bp_ref_text = match.group(4).strip()
        bp_ref_path = match.group(5).strip()
        bp_status = match.group(7).strip()

        # Find matching MEU in data
        for meu in data.get("meus", []):
            if meu["id"] == meu_id and meu["build_ref"] is None:
                # Parse build_ref
                anchor = None
                ref_path = bp_ref_path
                if "#" in ref_path:
                    ref_path, anchor = ref_path.split("#", 1)

                meu["build_ref"] = {
                    "path": ref_path,
                    "anchor": anchor,
                    "text": bp_ref_text or None,
                }

                if bp_status:
                    meu["status_labels"]["build_plan"] = bp_status

                break


# ─── Top-Level Migration ─────────────────────────────────────────────────


def run_migration(
    registry_path: Path | None = None,
    build_plan_path: Path | None = None,
    output_path: Path | None = None,
    *,
    force: bool = False,
) -> int:
    """Run the full migration.

    Returns exit code (0 = success).

    Guards against accidental data loss: if the target SSOT already exists and
    contains MEUs, the migration aborts unless ``force=True``. Migration is a
    one-time bootstrap — re-running it rebuilds the YAML from the Markdown and
    would discard any status updates / narrative captured since.
    """
    _ensure_utf8()

    reg_path = registry_path or REGISTRY_PATH
    bp_path = build_plan_path or BUILD_PLAN_PATH
    out_path = output_path or OUTPUT_PATH

    if not reg_path.exists():
        print(f"Error: Registry not found: {reg_path}", file=sys.stderr)
        return 1

    # Overwrite guard — migration is a one-time bootstrap.
    if out_path.exists() and not force:
        try:
            existing = yaml.safe_load(out_path.read_text(encoding="utf-8")) or {}
            n_existing = len(existing.get("meus", []))
        except Exception:
            n_existing = -1
        if n_existing != 0:
            print(
                f"Error: SSOT already populated at {out_path} "
                f"({n_existing if n_existing >= 0 else 'unknown'} MEUs).\n"
                "Re-running migrate rebuilds from Markdown and would discard status "
                "updates / narrative captured since the initial migration.\n"
                "Use `update` + `render` for ongoing changes, or pass --force to override.",
                file=sys.stderr,
            )
            return 1

    print(f"Parsing {reg_path.name}...")
    data, duplicates = parse_registry(reg_path)

    print(f"  Phases: {len(data['phases'])}")
    print(f"  MEUs: {len(data['meus'])}")
    print(f"  Summary bands: {len(data['summary_bands'])}")

    if duplicates:
        print(f"\n⚠️  Duplicate MEU IDs ({len(duplicates)}):")
        for meu_id, slug, reason in duplicates:
            print(f"  {meu_id} ({slug}) — {reason}")
        # Write reconciliation report
        report_path = Path("{{RECEIPTS_DIR}}/meu-dupe-report.txt")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as f:
            f.write("MEU Duplicate ID Reconciliation Report\n")
            f.write("=" * 50 + "\n\n")
            for meu_id, slug, reason in duplicates:
                f.write(f"{meu_id} ({slug}) — {reason}\n")
        print(f"  Report: {report_path}")

    # Cross-reference with BUILD_PLAN.md
    if bp_path.exists():
        print(f"\nCross-referencing with {bp_path.name}...")
        cross_reference_build_plan(data, bp_path)

    # Validate before saving
    from tools.meu_status.model import validate

    errors = validate(data)
    if errors:
        print(f"\n❌ Validation errors ({len(errors)}):")
        for e in errors[:10]:
            print(f"  {e}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
        # Save anyway for debugging — mark as draft
        print("\nSaving anyway for debugging...")

    # Save
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
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

    print(f"\n✅ Saved to {out_path}")
    print(f"   {len(data['meus'])} MEUs across {len(data['phases'])} phases")

    return 0


def _ensure_utf8() -> None:
    if sys.platform == "win32":
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
