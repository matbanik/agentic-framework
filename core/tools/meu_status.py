#!/usr/bin/env python3
"""MEU Status SSOT — CLI entrypoint.

Usage:
  uv run python tools/meu_status.py migrate            # One-time MD→YAML migration
  uv run python tools/meu_status.py render              # Regenerate Markdown regions
  uv run python tools/meu_status.py render --check      # Check if regions are up-to-date (CI gate)
  uv run python tools/meu_status.py list [--status S] [--band B] [--phase P] [--unblocked]
  uv run python tools/meu_status.py next [--band B] [--limit N]
  uv run python tools/meu_status.py get <row_key>
  uv run python tools/meu_status.py stats
  uv run python tools/meu_status.py update <row_key> <status> [--note N] [--plan P] [--reason R]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

# Ensure tools/ is importable when run as script
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.meu_status.model import (
    VALID_STATUSES,
    load,
    save,
    get_meu,
    update_meu_status,
    MeuStatusError,
)
from tools.meu_status.query import list_meus, next_meus, get_stats
from tools.meu_status.render import render_all, check_drift
from tools.meu_status.migrate import run_migration


def _ensure_utf8() -> None:
    """Ensure UTF-8 output on Windows."""
    if sys.platform == "win32":
        import io

        cast_stdout = cast(io.TextIOWrapper, sys.stdout)
        cast_stderr = cast(io.TextIOWrapper, sys.stderr)
        cast_stdout.reconfigure(encoding="utf-8", errors="replace")
        cast_stderr.reconfigure(encoding="utf-8", errors="replace")


# ─── Command handlers ────────────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> int:
    """List MEUs with filters."""
    data = load()
    results = list_meus(
        data,
        status=args.status,
        band=args.band,
        phase=args.phase,
        unblocked=args.unblocked,
    )

    if args.json:
        print(
            json.dumps([_meu_summary(m) for m in results], indent=2, ensure_ascii=False)
        )
    else:
        if not results:
            print("No matching MEUs found.")
            return 0
        for meu in results:
            icon = _status_icon(meu["status"])
            print(f"  {icon} {meu['row_key']:20s} {meu['slug']:30s} {meu['status']}")

    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Show next pending+unblocked MEUs."""
    data = load()
    results = next_meus(data, band=args.band, limit=args.limit)

    if not results:
        print("No pending+unblocked MEUs found.")
        return 0

    print(f"Next {len(results)} unblocked MEU(s):\n")
    for meu in results:
        deps = ", ".join(meu.get("depends_on", [])) or "none"
        print(
            f"  {meu['row_key']:20s} {meu['slug']:30s} band={meu['band']}  deps={deps}"
        )

    return 0


def cmd_get(args: argparse.Namespace) -> int:
    """Get a single MEU by row_key."""
    data = load()
    meu = get_meu(data, args.row_key)

    if meu is None:
        print(f"Error: Unknown row_key '{args.row_key}'", file=sys.stderr)
        return 1

    print(json.dumps(meu, indent=2, ensure_ascii=False))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Show summary statistics."""
    data = load()
    stats = get_stats(data)

    print(f"Total MEUs: {stats['total']}")
    print(f"Completed:  {stats['completed']}")
    print(f"Pending:    {stats['pending']}")
    print(f"In Progress:{stats['in_progress']}")
    print()
    print("By status:")
    for status, count in sorted(stats["by_status"].items()):
        if count > 0:
            print(f"  {_status_icon(status)} {status:20s} {count}")

    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """Update a MEU's status."""
    data = load()
    try:
        update_meu_status(
            data,
            args.row_key,
            args.status,
            note=args.note,
            plan=args.plan,
            reason=args.reason,
        )
    except MeuStatusError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    save(data)
    meu = get_meu(data, args.row_key)
    assert meu is not None  # row_key was validated by update_meu_status
    print(f"Updated {args.row_key} → {args.status} (updated: {meu['updated']})")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    """Render YAML→Markdown regions (or --check for CI gate)."""
    if args.check:
        return check_drift()
    return render_all()


def cmd_migrate(args: argparse.Namespace) -> int:
    """One-time MD→YAML migration."""
    return run_migration(force=args.force)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _status_icon(status: str) -> str:
    icons = {
        "pending": "⬜",
        "deferred": "⏸",
        "in_progress": "🔵",
        "ready_for_review": "🟡",
        "changes_required": "🔴",
        "approved": "✅",
        "closed": "🚫",
    }
    return icons.get(status, "?")


def _meu_summary(meu: dict) -> dict:
    return {
        "row_key": meu["row_key"],
        "slug": meu["slug"],
        "status": meu["status"],
        "band": meu["band"],
        "phase": meu["phase"],
    }


# ─── Argument Parser ─────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MEU Status SSOT — query, update, render, and migrate MEU status data."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="List MEUs with filters")
    p_list.add_argument(
        "--status", choices=sorted(VALID_STATUSES), help="Filter by status"
    )
    p_list.add_argument("--band", help="Filter by priority band")
    p_list.add_argument("--phase", help="Filter by phase ID")
    p_list.add_argument(
        "--unblocked",
        action="store_true",
        help="Only show pending MEUs with all deps approved",
    )
    p_list.add_argument("--json", action="store_true", help="JSON output")

    # next
    p_next = subparsers.add_parser("next", help="Show next pending+unblocked MEUs")
    p_next.add_argument("--band", help="Filter by priority band")
    p_next.add_argument("--limit", type=int, default=5, help="Max results (default: 5)")

    # get
    p_get = subparsers.add_parser("get", help="Get a single MEU by row_key")
    p_get.add_argument("row_key", help="The row_key to look up")

    # stats
    subparsers.add_parser("stats", help="Show summary statistics")

    # update
    p_update = subparsers.add_parser("update", help="Update a MEU's status")
    p_update.add_argument("row_key", help="The row_key to update")
    p_update.add_argument("status", choices=sorted(VALID_STATUSES), help="New status")
    p_update.add_argument("--note", help="Set the note field")
    p_update.add_argument("--plan", help="Set the execution_plan field")
    p_update.add_argument(
        "--reason", help="Set closed_reason (required for status=closed)"
    )

    # render
    p_render = subparsers.add_parser(
        "render", help="Regenerate Markdown regions from YAML"
    )
    p_render.add_argument(
        "--check",
        action="store_true",
        help="Check mode — exit non-zero if regions differ from on-disk",
    )

    # migrate
    p_migrate = subparsers.add_parser("migrate", help="One-time MD→YAML migration")
    p_migrate.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an already-populated SSOT (guards against accidental data loss)",
    )

    return parser


def main() -> int:
    _ensure_utf8()
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "list": cmd_list,
        "next": cmd_next,
        "get": cmd_get,
        "stats": cmd_stats,
        "update": cmd_update,
        "render": cmd_render,
        "migrate": cmd_migrate,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
