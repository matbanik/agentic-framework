"""Check the ``done`` evidence of one plan folder (report R§5.2, AC-E.2).

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component E).
The credits monitor (``.agent/skills/claude-credits/Watch-CreditsRuns.ps1``)
runs this tool on the tree of a run whose final Status is ``DONE``. The run is
``done`` only when every check holds; else it is ``done_unverified`` and the
notice names the missing check ids.

Usage::

    completion_preflight.py --plan <folder> --tree <path> --json

``--plan`` is relative to ``--tree`` and must name one folder directly under
``<tree>/docs/execution/plans/``. ``--tree`` must be an existing directory.

stdout is one JSON object: ``ok`` (bool), ``missing`` (check ids in a fixed
order) and ``details`` (one reason per missing id). Exit codes: 0 ok, 1 one or
more checks missing, 2 usage error. The tool reads only.

The checks, in order:

* ``task_rows``: every task table row is ``[x]`` or a valid ``[B]``. A valid
  ``[B]`` row names a follow-up, cites ``B-<row>`` and the file holds a
  ``### B-<row>`` block.
* ``stop_gate``: the frontmatter ``stop_gate`` is ``released:done``.
* ``approved_verdict``: ``.agent/context/handoffs/{plan}-implementation-critical-review.md``
  exists, holds the review markers, and its last ``verdict:`` line is
  ``approved``.
* ``handoff``: ``{plan}-handoff.md`` when ``meus`` is empty, else
  ``{plan}-{MEU}-handoff.md`` for each MEU; each holds the handoff markers.
* ``reflection``: ``docs/execution/reflections/{plan}-reflection.md`` holds the
  reflection markers.
* ``metrics``: ``docs/execution/metrics.md`` has a table row that names the
  plan folder or one of its MEUs.

The markers are the patterns of ``.agent/skills/completion-preflight/SKILL.md``.
They match without regard to case, as ``Select-String`` does there.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

EXIT_OK = 0
EXIT_MISSING = 1
EXIT_USAGE = 2

PLANS_DIR = Path("docs") / "execution" / "plans"
HANDOFFS_DIR = Path(".agent") / "context" / "handoffs"
REFLECTIONS_DIR = Path("docs") / "execution" / "reflections"
METRICS_FILE = Path("docs") / "execution" / "metrics.md"

CHECK_IDS = (
    "task_rows",
    "stop_gate",
    "approved_verdict",
    "handoff",
    "reflection",
    "metrics",
)

REVIEW_MARKERS = ("verdict:", "findings_count:", "Finding|Severity")
HANDOFF_MARKERS = (
    "Acceptance Criteria|AC-",
    "CACHE BOUNDARY",
    "Evidence|FAIL_TO_PASS",
    "Changed Files",
)
REFLECTION_MARKERS = (
    "Friction Log|Execution Trace",
    "Pattern Extraction|Patterns to KEEP",
    "Decisions Log",
    "Next Session Design Rules|RULE-",
    "Efficiency Metrics",
    "Rule Adherence",
    "Instruction Coverage|schema: v1",
    "sections:",
    "loaded:",
    "decisive_rules:",
)

STATUS_CELL_RE = re.compile(r"^`?\[(x|X| |/|B)\]`?$")
VERDICT_LINE_RE = re.compile(r"^\s*[*_`]*verdict[*_`]*\s*:\s*(.*?)\s*$", re.IGNORECASE)
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
FOLLOW_UP_RE = re.compile(r"follow[- ]up", re.IGNORECASE)
MEU_ID_RE = re.compile(r"^MEU-[A-Za-z0-9][A-Za-z0-9-]*$")
TOKEN_SPLIT_RE = re.compile(r"[\s,;()]+")


class UsageError(Exception):
    """A usage error: the tool exits 2 and checks nothing."""


class _Parser(argparse.ArgumentParser):
    """An argument parser whose errors exit 2 with one JSON line."""

    def error(self, message: str) -> NoReturn:
        emit({"ok": False, "missing": [], "error": f"usage: {message}"})
        sys.exit(EXIT_USAGE)


def emit(payload: dict[str, object]) -> None:
    """Write ``payload`` to stdout as one JSON line."""
    sys.stdout.write(json.dumps(payload, sort_keys=False) + "\n")
    sys.stdout.flush()


def build_parser() -> _Parser:
    """Return the CLI parser."""
    parser = _Parser(prog="completion_preflight.py", add_help=True)
    parser.add_argument("--plan", required=True, help="plan folder, relative to --tree")
    parser.add_argument("--tree", required=True, help="the tree root")
    parser.add_argument("--json", action="store_true", help="write one JSON line")
    return parser


def resolve_plan(tree_arg: str, plan_arg: str) -> tuple[Path, Path]:
    """Return the resolved tree and plan folder, or raise ``UsageError``.

    The plan folder must be one folder directly under ``docs/execution/plans/``
    of the tree. It need not exist: an absent folder fails every check.
    """
    tree = Path(tree_arg)
    if not tree.is_dir():
        raise UsageError(f"the tree is not a directory: {tree_arg}")
    tree = tree.resolve()
    plan_rel = Path(plan_arg)
    if plan_rel.is_absolute():
        raise UsageError("--plan must be relative to --tree")
    plans_root = (tree / PLANS_DIR).resolve()
    plan = (tree / plan_rel).resolve()
    if plan.parent != plans_root:
        raise UsageError(
            f"the plan folder is not directly under {PLANS_DIR.as_posix()}/"
        )
    return tree, plan


def read_text(path: Path) -> str | None:
    """Return the UTF-8 text of ``path``, or None when it is not a readable file."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, PermissionError):
        return None


def missing_markers(text: str, markers: Sequence[str]) -> list[str]:
    """Return the markers (regex patterns, any case) that ``text`` does not match."""
    return [m for m in markers if not re.search(m, text, re.IGNORECASE | re.MULTILINE)]


def frontmatter(text: str) -> dict[str, str]:
    """Return the top-level ``key: value`` pairs of the leading ``---`` block.

    Values keep their raw text, without an inline comment. A block list that
    follows a key with no value is joined as ``[a, b]`` in YAML flow form.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    pairs: dict[str, str] = {}
    current: str | None = None
    items: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = FRONTMATTER_KEY_RE.match(line)
        if match:
            if current is not None and items:
                pairs[current] = json.dumps(items)
            key: str = match.group(1)
            current, items = key, []
            pairs[key] = strip_comment(match.group(2))
            continue
        stripped = line.strip()
        if current is not None and stripped.startswith("- ") and not pairs[current]:
            items.append(unquote(strip_comment(stripped[2:])))
    if current is not None and items:
        pairs[current] = json.dumps(items)
    return pairs


def strip_comment(value: str) -> str:
    """Return ``value`` without a ``#`` comment that is outside quotes."""
    value = value.strip()
    if value.startswith(('"', "'")):
        end = value.find(value[0], 1)
        return value[: end + 1] if end > 0 else value
    hash_at = value.find(" #")
    return value[:hash_at].rstrip() if hash_at >= 0 else value


def unquote(value: str) -> str:
    """Return ``value`` without one pair of surrounding quotes."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_meus(raw: str | None) -> list[str] | None:
    """Return the MEU ids of the ``meus`` value, or None when it is not readable."""
    if raw is None:
        return None
    raw = raw.strip()
    if raw in ("", "[]", "null", "~"):
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        value = [unquote(part) for part in raw.strip("[]").split(",") if part.strip()]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    meus = [v.strip() for v in value]
    if not all(MEU_ID_RE.match(m) for m in meus):
        return None
    return meus


def table_cells(line: str) -> list[str] | None:
    """Return the cells of a Markdown table line, or None for any other line."""
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")) or len(stripped) < 2:
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def row_id(cell: str) -> str:
    """Return the row id of a first cell, without emphasis or code marks."""
    return cell.strip().strip("*_`").strip()


def check_task_rows(text: str) -> str | None:
    """Return why the task rows fail, or None when every row is done or validly blocked."""
    open_rows: list[str] = []
    bad_blocks: list[str] = []
    rows = 0
    for line in text.splitlines():
        cells = table_cells(line)
        if not cells or len(cells) < 2:
            continue
        status = STATUS_CELL_RE.match(cells[-1])
        if not status:
            continue
        rows += 1
        mark = status.group(1)
        rid = row_id(cells[0])
        if mark in ("x", "X"):
            continue
        if mark == "B" and valid_block(text, line, rid):
            continue
        (bad_blocks if mark == "B" else open_rows).append(rid)
    if rows == 0:
        return "no task rows"
    reasons = []
    if open_rows:
        reasons.append("open rows: " + ", ".join(open_rows))
    if bad_blocks:
        reasons.append("[B] rows without evidence: " + ", ".join(bad_blocks))
    return "; ".join(reasons) or None


def valid_block(text: str, line: str, rid: str) -> bool:
    """Return True when a ``[B]`` row names a follow-up, cites ``B-<row>`` and has its block."""
    if not rid:
        return False
    cite = re.compile(rf"(?<![A-Za-z0-9-])B-{re.escape(rid)}(?![A-Za-z0-9-])")
    block = re.compile(rf"^###\s+B-{re.escape(rid)}(?![A-Za-z0-9-])", re.MULTILINE)
    return bool(FOLLOW_UP_RE.search(line) and cite.search(line) and block.search(text))


def check_stop_gate(meta: dict[str, str]) -> str | None:
    """Return why the stop gate fails, or None when it is ``released:done``."""
    gate = unquote(meta.get("stop_gate", ""))
    return None if gate == "released:done" else f"stop_gate is {gate or 'absent'}"


def check_review(path: Path) -> str | None:
    """Return why the implementation review fails, or None when it is approved."""
    text = read_text(path)
    if text is None:
        return f"no file {path.name}"
    absent = missing_markers(text, REVIEW_MARKERS)
    if absent:
        return "review markers missing: " + ", ".join(absent)
    verdicts = [m.group(1) for m in map(VERDICT_LINE_RE.match, text.splitlines()) if m]
    last = unquote(verdicts[-1].strip("*_` ")) if verdicts else ""
    return None if last.lower() == "approved" else f"last verdict is {last or 'empty'}"


def check_handoffs(handoffs: Path, plan: str, meus: list[str] | None) -> str | None:
    """Return why the handoffs fail, or None when each one holds the markers."""
    if meus is None:
        return "the meus value is not a list of MEU ids"
    names = (
        [f"{plan}-{meu}-handoff.md" for meu in meus] if meus else [f"{plan}-handoff.md"]
    )
    reasons = []
    for name in names:
        text = read_text(handoffs / name)
        if text is None:
            reasons.append(f"no file {name}")
            continue
        absent = missing_markers(text, HANDOFF_MARKERS)
        if absent:
            reasons.append(f"{name} markers missing: " + ", ".join(absent))
    return "; ".join(reasons) or None


def check_reflection(path: Path) -> str | None:
    """Return why the reflection fails, or None when it holds every marker."""
    text = read_text(path)
    if text is None:
        return f"no file {path.name}"
    absent = missing_markers(text, REFLECTION_MARKERS)
    return ("reflection markers missing: " + ", ".join(absent)) if absent else None


def check_metrics(path: Path, plan: str, meus: list[str] | None) -> str | None:
    """Return why the metrics check fails, or None when a row names the plan or an MEU."""
    text = read_text(path)
    if text is None:
        return "no metrics file"
    names = {plan, *(meus or [])}
    for line in text.splitlines():
        cells = table_cells(line)
        if not cells:
            continue
        for cell in cells:
            tokens = {t.strip("*_`") for t in TOKEN_SPLIT_RE.split(cell)}
            if cell.strip("*_` ") in names or tokens & names:
                return None
    return "no metrics row names the plan or its MEUs"


def run_checks(tree: Path, plan_dir: Path) -> dict[str, str]:
    """Return the failing check ids, each with its reason, in ``CHECK_IDS`` order."""
    plan = plan_dir.name
    task_text = read_text(plan_dir / "task.md")
    meta = frontmatter(task_text) if task_text is not None else {}
    meus = parse_meus(meta.get("meus")) if task_text is not None else None
    handoffs = tree / HANDOFFS_DIR
    results: dict[str, str | None] = {
        "task_rows": "no task.md" if task_text is None else check_task_rows(task_text),
        "stop_gate": "no task.md" if task_text is None else check_stop_gate(meta),
        "approved_verdict": check_review(
            handoffs / f"{plan}-implementation-critical-review.md"
        ),
        "handoff": "no task.md"
        if task_text is None
        else check_handoffs(handoffs, plan, meus),
        "reflection": check_reflection(
            tree / REFLECTIONS_DIR / f"{plan}-reflection.md"
        ),
        "metrics": check_metrics(tree / METRICS_FILE, plan, meus),
    }
    return {key: reason for key in CHECK_IDS if (reason := results[key]) is not None}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; return the exit code."""
    args = build_parser().parse_args(argv)
    try:
        tree, plan_dir = resolve_plan(args.tree, args.plan)
    except (UsageError, OSError) as exc:
        emit({"ok": False, "missing": [], "error": f"usage: {exc}"})
        return EXIT_USAGE
    failures = run_checks(tree, plan_dir)
    emit({"ok": not failures, "missing": list(failures), "details": failures})
    return EXIT_MISSING if failures else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
