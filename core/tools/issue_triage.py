#!/usr/bin/env python3
"""Issue Triage CLI — manage known-issues.yaml.

Usage:
    uv run python tools/issue_triage.py stats
    uv run python tools/issue_triage.py list [--severity S] [--component C] [--status S]
    uv run python tools/issue_triage.py get <id>
    uv run python tools/issue_triage.py add --id ID --title T --severity S --component C
    uv run python tools/issue_triage.py verify [--deep]
    uv run python tools/issue_triage.py render
    uv run python tools/issue_triage.py render --check
    uv run python tools/issue_triage.py render --include-candidates
    uv run python tools/issue_triage.py migrate [--dry-run]
    uv run python tools/issue_triage.py bucket
    uv run python tools/issue_triage.py triage [--output PATH]
    uv run python tools/issue_triage.py discover [--root DIR] [--dry-run]
    uv run python tools/issue_triage.py promote <id>
    uv run python tools/issue_triage.py dismiss <id>

Follows the meu_status.py CLI pattern (argparse + subcommands).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Ensure tools/ is importable when run as script
sys.path.insert(0, str(Path(__file__).parent.parent))


from tools.issue_triage.model import (
    DEFAULT_MD_PATH,
    DEFAULT_SSOT_PATH,
    VALID_COMPONENTS,
    VALID_SEVERITIES,
    VALID_STATUSES,
    add_issue,
    load,
    save,
)
from tools.issue_triage.query import QueryError, get_issue, get_stats, list_issues
from tools.issue_triage.render import check_drift, render_all
from tools.issue_triage.verify import verify_all


def _cmd_stats(args: argparse.Namespace) -> int:
    """Show issue statistics."""
    data = load(args.yaml)
    stats = get_stats(data)

    print(f"[STATS] Issue Triage Stats ({args.yaml.name})")
    print(f"   Total issues: {stats['total']}")
    print()

    if stats["by_severity"]:
        print("   By Severity:")
        for sev in ("critical", "high", "medium", "low"):
            count = stats["by_severity"].get(sev, 0)
            if count:
                print(f"     {sev:10s}: {count}")

    if stats["by_component"]:
        print("   By Component:")
        for comp, count in sorted(stats["by_component"].items()):
            print(f"     {comp:15s}: {count}")

    if stats["by_status"]:
        print("   By Status:")
        for status, count in sorted(stats["by_status"].items()):
            print(f"     {status:15s}: {count}")

    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List issues with optional filters."""
    data = load(args.yaml)

    try:
        results = list_issues(
            data,
            severity=args.severity,
            component=args.component,
            status=args.status,
        )
    except QueryError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(results, indent=2, default=str))
        return 0

    if not results:
        print("No issues match the given filters.")
        return 0

    print(f"Found {len(results)} issue(s):\n")
    for issue in results:
        print(f"  [{issue['severity']:8s}] {issue['id']:25s} {issue['title']}")

    return 0


def _cmd_get(args: argparse.Namespace) -> int:
    """Get details of a specific issue."""
    data = load(args.yaml)
    issue = get_issue(data, args.id)

    if issue is None:
        print(f"ERROR: Issue '{args.id}' not found.", file=sys.stderr)
        return 1

    # Pretty-print the issue
    print(json.dumps(issue, indent=2, default=str))
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    """Add a new issue."""
    data = load(args.yaml)

    try:
        updated = add_issue(
            data,
            id=args.id,
            title=args.title,
            severity=args.severity,
            component=args.component,
            status=args.add_status or "open",
            discovered=args.discovered or date.today().isoformat(),
            root_cause=args.root_cause or "",
            blast_radius=args.blast_radius or "",
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    save(updated, args.yaml)
    print(f"OK: Added issue '{args.id}' to {args.yaml.name}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    """Run verification checks."""
    if getattr(args, "deep", False):
        from tools.issue_triage.verify import verify_deep

        data = load(args.yaml)
        findings = verify_deep(data, update_last_checked=True)
        if findings:
            print(f"[DEEP VERIFY] Found {len(findings)} finding(s):")
            for f in findings:
                print(f"  [{f['type']:20s}] {f['issue_id']:25s} {f['message']}")
            save(data, args.yaml)
            return 1
        else:
            print("[DEEP VERIFY] No findings. All issues verified.")
            save(data, args.yaml)
            return 0
    return verify_all(args.yaml)


def _cmd_render(args: argparse.Namespace) -> int:
    """Render YAML → markdown."""
    if args.check:
        return check_drift(args.yaml, args.md)
    return render_all(
        args.yaml,
        args.md,
        include_candidates=getattr(args, "include_candidates", False),
    )


def _cmd_migrate(args: argparse.Namespace) -> int:
    """Migrate from markdown to YAML."""
    from tools.issue_triage.migrate import migrate

    return migrate(args.md, args.yaml, dry_run=args.dry_run)


def _cmd_bucket(args: argparse.Namespace) -> int:
    """Group actionable issues into proposed MEU batches."""
    from tools.issue_triage.bucket import bucket_issues

    data = load(args.yaml)
    batches = bucket_issues(data)

    if not batches:
        print("[BUCKET] No actionable issues to group.")
        return 0

    print(f"[BUCKET] {len(batches)} proposed batch(es):\n")
    for batch in batches:
        dupes = " ⚠ HAS RELATED OVERLAP" if batch.get("has_duplicates") else ""
        print(
            f"  [{batch['priority_band']}] {batch['slug']} "
            f"({batch['complexity']}, {len(batch['issues'])} issue(s)){dupes}"
        )
        for issue_id in batch["issues"]:
            print(f"    - {issue_id}")
    return 0


def _cmd_triage(args: argparse.Namespace) -> int:
    """Generate ephemeral triage-output.yaml."""
    from tools.issue_triage.triage import generate_triage_output

    data = load(args.yaml)
    output_path = args.output
    generate_triage_output(data, output_path)
    print(f"[TRIAGE] Generated triage output at {output_path}")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    """Run TODO/FIXME/HACK scanner and report findings."""
    from tools.issue_triage.discover import scan_todos, VALID_SOURCES

    # Validate --source (AC-15)
    source = getattr(args, "source", "todo")
    if source not in VALID_SOURCES:
        print(
            f"ERROR: Unsupported source '{source}'. Valid: {', '.join(sorted(VALID_SOURCES))}",
            file=sys.stderr,
        )
        return 1

    data = load(args.yaml)
    existing_ids = {i["id"] for i in data.get("issues", [])}
    root = getattr(args, "root", None) or Path.cwd()
    findings = scan_todos(root, existing_issue_ids=existing_ids)

    new_findings = [f for f in findings if not f.get("linked_issue_id")]
    linked_findings = [f for f in findings if f.get("linked_issue_id")]

    print(f"[DISCOVER] Scanned {root}")
    print(f"  New candidates: {len(new_findings)}")
    print(f"  Linked to existing: {len(linked_findings)}")

    def _safe_print(text: str) -> None:
        """Print with ASCII fallback for Windows cp1252 console."""
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", errors="replace").decode("ascii"))

    if new_findings:
        _safe_print("\nNew candidates:")
        for f in new_findings:
            raw = f["raw_text"][:120]
            _safe_print(
                f"  {f['pattern']} {f['file_path']}:{f['line_number']} -- {raw}"
            )

    if linked_findings:
        _safe_print("\nLinked to existing issues:")
        for f in linked_findings:
            _safe_print(
                f"  {f['linked_issue_id']} <- {f['file_path']}:{f['line_number']}"
            )

    if not getattr(args, "dry_run", True):
        # In non-dry-run mode, add new candidates to YAML
        for f in new_findings:
            candidate_id = f"DISC-{f['file_path']}:{f['line_number']}"
            # Avoid duplicate candidates
            if any(i["id"] == candidate_id for i in data.get("issues", [])):
                continue
            data["issues"].append(
                {
                    "id": candidate_id,
                    "title": f"{f['pattern']}: {f['raw_text'][:80]}",
                    "severity": "low",
                    "component": f["component"],
                    "status": "candidate",
                    "discovered": date.today().isoformat(),
                    "root_cause": "",
                    "blast_radius": "",
                }
            )
        save(data, args.yaml)
        print(f"\nSaved {len(new_findings)} candidate(s) to {args.yaml.name}")

    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    """Promote a candidate issue to open status."""
    data = load(args.yaml)
    target_id = args.id

    for issue in data.get("issues", []):
        if issue["id"] == target_id:
            if issue["status"] != "candidate":
                print(
                    f"ERROR: Issue '{target_id}' has status '{issue['status']}', "
                    "not 'candidate'. Only candidates can be promoted.",
                    file=sys.stderr,
                )
                return 1
            issue["status"] = "open"
            save(data, args.yaml)
            print(f"OK: Promoted '{target_id}' from candidate -> open")
            return 0

    print(f"ERROR: Issue '{target_id}' not found", file=sys.stderr)
    return 1


def _cmd_dismiss(args: argparse.Namespace) -> int:
    """Dismiss a candidate issue."""
    data = load(args.yaml)
    target_id = args.id

    for issue in data.get("issues", []):
        if issue["id"] == target_id:
            if issue["status"] != "candidate":
                print(
                    f"ERROR: Issue '{target_id}' has status '{issue['status']}', "
                    "not 'candidate'. Only candidates can be dismissed.",
                    file=sys.stderr,
                )
                return 1
            issue["status"] = "dismissed"
            save(data, args.yaml)
            print(f"OK: Dismissed '{target_id}' from candidate -> dismissed")
            return 0

    print(f"ERROR: Issue '{target_id}' not found", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="issue_triage",
        description="Manage the {{PROJECT_NAME_TITLE}} known-issues.yaml SSOT.",
    )
    parser.add_argument(
        "--yaml",
        type=Path,
        default=DEFAULT_SSOT_PATH,
        help="Path to known-issues.yaml",
    )
    parser.add_argument(
        "--md",
        type=Path,
        default=DEFAULT_MD_PATH,
        help="Path to known-issues.md",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # stats
    sub.add_parser("stats", help="Show issue statistics")

    # list
    list_parser = sub.add_parser("list", help="List issues with optional filters")
    list_parser.add_argument("--severity", choices=sorted(VALID_SEVERITIES))
    list_parser.add_argument("--component", choices=sorted(VALID_COMPONENTS))
    list_parser.add_argument("--status", choices=sorted(VALID_STATUSES))
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # get
    get_parser = sub.add_parser("get", help="Get details of a specific issue")
    get_parser.add_argument("id", help="Issue ID")

    # add
    add_parser = sub.add_parser("add", help="Add a new issue")
    add_parser.add_argument("--id", required=True, help="Issue ID (e.g., BUG-001)")
    add_parser.add_argument("--title", required=True, help="Issue title")
    add_parser.add_argument(
        "--severity", required=True, choices=sorted(VALID_SEVERITIES)
    )
    add_parser.add_argument(
        "--component", required=True, choices=sorted(VALID_COMPONENTS)
    )
    add_parser.add_argument(
        "--add-status",
        dest="add_status",
        choices=sorted(VALID_STATUSES),
        default="open",
    )
    add_parser.add_argument("--discovered", help="Discovery date (YYYY-MM-DD)")
    add_parser.add_argument("--root-cause", dest="root_cause", default="")
    add_parser.add_argument("--blast-radius", dest="blast_radius", default="")

    # verify
    verify_parser = sub.add_parser("verify", help="Run verification checks")
    verify_parser.add_argument(
        "--deep",
        action="store_true",
        help="Run deep codebase verification (file checks, test coverage)",
    )

    # render
    render_parser = sub.add_parser("render", help="Render YAML → markdown")
    render_parser.add_argument(
        "--check", action="store_true", help="Check for drift only"
    )
    render_parser.add_argument(
        "--include-candidates",
        action="store_true",
        dest="include_candidates",
        help="Include candidate issues in a separate Candidates section",
    )

    # migrate
    migrate_parser = sub.add_parser("migrate", help="Migrate markdown → YAML")
    migrate_parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writing"
    )

    # bucket
    sub.add_parser("bucket", help="Group actionable issues into proposed MEU batches")

    # triage
    triage_parser = sub.add_parser(
        "triage", help="Generate ephemeral triage-output.yaml"
    )
    triage_parser.add_argument(
        "--output",
        type=Path,
        default=Path(".agent/context/triage-output.yaml"),
        help="Output path for triage-output.yaml",
    )

    # discover
    discover_parser = sub.add_parser(
        "discover", help="Scan for TODO/FIXME/HACK comments"
    )
    discover_parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Root directory to scan (default: cwd)",
    )
    discover_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Report findings without modifying YAML",
    )
    discover_parser.add_argument(
        "--source",
        type=str,
        default="todo",
        help="Discovery source (currently: 'todo')",
    )

    # promote
    promote_parser = sub.add_parser("promote", help="Promote a candidate issue to open")
    promote_parser.add_argument("id", help="Issue ID to promote")

    # dismiss
    dismiss_parser = sub.add_parser("dismiss", help="Dismiss a candidate issue")
    dismiss_parser.add_argument("id", help="Issue ID to dismiss")

    args = parser.parse_args(argv)

    handlers = {
        "stats": _cmd_stats,
        "list": _cmd_list,
        "get": _cmd_get,
        "add": _cmd_add,
        "verify": _cmd_verify,
        "render": _cmd_render,
        "migrate": _cmd_migrate,
        "bucket": _cmd_bucket,
        "triage": _cmd_triage,
        "discover": _cmd_discover,
        "promote": _cmd_promote,
        "dismiss": _cmd_dismiss,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
