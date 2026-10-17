"""S3 done-evidence check: ``tools/completion_preflight.py`` (Component E).

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component E,
AC-E.2 and the AC-E.2 boundary row; report R§5.2; acceptance matrix MX-25, the
S3 part). The monitor side of Component E (AC-E.1, AC-E.3, AC-E.4, AC-E.5 and
AC-E.6) is in ``tools/tests/Watch-CreditsRuns.Tests.ps1``; that file also runs
this tool through the monitor (``done`` and ``done_unverified``).

The tests run the tool only through its CLI, in a subprocess, on a temp tree
per test. They fix this CLI contract:

* ``completion_preflight.py --plan <folder> --tree <path> --json``. ``--plan``
  is relative to ``--tree`` and must resolve under
  ``<tree>/docs/execution/plans/``. ``--tree`` must be an existing directory.
* stdout is one JSON object with ``ok`` (bool) and ``missing`` (a list of
  check ids). Other keys are free.
* Exit 0: ok. Exit 1: one or more checks missing. Exit 2: usage error (an
  unknown flag, a tree that is not a directory, a plan folder outside
  ``docs/execution/plans/``).
* The check ids: ``task_rows`` (a row not ``[x]`` and not a valid ``[B]``),
  ``stop_gate`` (not ``released:done``), ``approved_verdict`` (no
  ``{plan}-implementation-critical-review.md``, its last ``verdict:`` line not
  approved, or its markers missing), ``handoff`` (``{plan}-handoff.md`` when
  ``meus`` is empty, else ``{plan}-{MEU}-handoff.md`` per MEU; missing, or
  markers missing), ``reflection`` (``{plan}-reflection.md``; missing, or
  markers missing) and ``metrics`` (no ``docs/execution/metrics.md`` row that
  names the plan folder or one of its MEUs).
* The tool reads only. The markers are those of
  ``.agent/skills/completion-preflight/SKILL.md``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "completion_preflight.py"
PLAN = "2026-10-15-fixture"
PLAN_REL = f"docs/execution/plans/{PLAN}"
CHECK_IDS = frozenset(
    {"task_rows", "stop_gate", "approved_verdict", "handoff", "reflection", "metrics"}
)

TASK_HEADER = "| # | Task | Owner | Deliverable | Status |\n|---|------|-------|-------------|--------|\n"
ROWS_DONE = (
    "| 1 | Write the tests | coder | tests | [x] |\n"
    "| 2 | Make them pass | coder | code | [x] |\n"
    "| H1-1 | Handoff | coder | handoff | [x] |\n"
)
B_ROW = "| 3 | Live check | tester | receipt | [B] |\n"
B_ROW_VALID = "| 3 | Live check, follow-up in B-3 | tester | receipt | [B] |\n"
B_BLOCK = (
    "\n### B-3\n\n"
    "Decision: the human holds the live check "
    "([decision](../../../../.agent/context/handoffs/fixture-decision.md)).\n"
)

REVIEW_APPROVED = """---
verdict: "approved"
findings_count: 0
---

# Implementation critical review

## Round 1

verdict: changes_required
findings_count: 1

| Finding | Severity |
|---------|----------|
| F-1 | Low |

## Round 2

verdict: approved
findings_count: 0
"""

HANDOFF = """# Handoff

## Acceptance Criteria

AC-1 holds.

<!-- CACHE BOUNDARY -->

## Evidence

FAIL_TO_PASS: tests/unit/test_fixture.py

## Changed Files

- tools/fixture.py
"""

REFLECTION = """# Reflection

## Friction Log

None.

## Pattern Extraction

None.

## Decisions Log

None.

## Next Session Design Rules

RULE-1: none.

## Efficiency Metrics

None.

## Rule Adherence

None.

## Instruction Coverage

```yaml
schema: v1
sections:
  - id: tdd
loaded:
  - AGENTS.md
decisive_rules:
  - tests first
```
"""

METRICS = (
    "# Metrics\n\n"
    "| Date | MEU(s) | Rounds | Notes |\n"
    "|------|--------|--------|-------|\n"
    "| 2026-10-14 | 2026-10-14-other | 1 | other plan |\n"
)


def task_md(
    *,
    stop_gate: str = "released:done",
    meus: str = "[]",
    rows: str = ROWS_DONE,
    tail: str = "",
) -> str:
    """Return a task.md with frontmatter, one task table and an optional tail."""
    return (
        "---\n"
        f'project: "{PLAN}"\n'
        'status: "done"\n'
        f'stop_gate: "{stop_gate}"\n'
        f"meus: {meus}\n"
        "---\n\n"
        "# Task\n\n" + TASK_HEADER + rows + tail
    )


def write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` with LF line ends, creating parent folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def make_tree(root: Path, *, meus: tuple[str, ...] = ()) -> Path:
    """Write a tree whose plan passes every check; return the tree root."""
    tree = root / "tree"
    meus_text = "[" + ", ".join(f'"{m}"' for m in meus) + "]"
    write(tree / PLAN_REL / "task.md", task_md(meus=meus_text))
    write(tree / PLAN_REL / "implementation-plan.md", "# Plan\n\nThe fixture plan.\n")
    handoffs = tree / ".agent" / "context" / "handoffs"
    write(handoffs / f"{PLAN}-implementation-critical-review.md", REVIEW_APPROVED)
    write(handoffs / "fixture-decision.md", "# Decision\n\nHeld.\n")
    if meus:
        for meu in meus:
            write(handoffs / f"{PLAN}-{meu}-handoff.md", HANDOFF)
    else:
        write(handoffs / f"{PLAN}-handoff.md", HANDOFF)
    write(
        tree / "docs" / "execution" / "reflections" / f"{PLAN}-reflection.md",
        REFLECTION,
    )
    label = ", ".join(meus) if meus else PLAN
    write(
        tree / "docs" / "execution" / "metrics.md",
        METRICS + f"| 2026-10-15 | {label} | 2 | fixture |\n",
    )
    return tree


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the tool in a subprocess and return the completed process.

    The tool must exist, so an exit 2 from the interpreter itself never passes
    a boundary test.
    """
    assert TOOL.is_file(), f"the tool is missing: {TOOL}"
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def check(tree: Path, plan: str = PLAN_REL) -> tuple[int, dict[str, Any]]:
    """Run the check on ``tree``; return the exit code and the JSON object."""
    proc = run_tool("--plan", plan, "--tree", str(tree), "--json")
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        doc = {"_stdout": proc.stdout, "_stderr": proc.stderr}
    return proc.returncode, doc


def tree_digest(tree: Path) -> str:
    """Return one hash of every file path, size and content under ``tree``."""
    h = hashlib.sha256()
    for path in sorted(p for p in tree.rglob("*") if p.is_file()):
        h.update(path.relative_to(tree).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def review_path(tree: Path) -> Path:
    """Return the path of the plan's implementation review file."""
    return (
        tree
        / ".agent"
        / "context"
        / "handoffs"
        / f"{PLAN}-implementation-critical-review.md"
    )


# --- AC-E.2: the evidence items ---------------------------------------------------


def test_ac_e2_full_tree_ok(tmp_path: Path) -> None:
    """AC-E.2: every evidence item holds → exit 0, ``ok`` true, ``missing`` empty."""
    code, doc = check(make_tree(tmp_path))
    assert code == 0, doc
    assert doc.get("ok") is True
    assert doc.get("missing") == []


def test_ac_e2_output_is_one_json_object(tmp_path: Path) -> None:
    """AC-E.2: stdout is one JSON object with ``ok`` and ``missing``."""
    proc = run_tool("--plan", PLAN_REL, "--tree", str(make_tree(tmp_path)), "--json")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, proc.stdout
    doc = json.loads(lines[0])
    assert isinstance(doc, dict)
    assert isinstance(doc.get("ok"), bool)
    assert isinstance(doc.get("missing"), list)


def test_ac_e2_missing_ids_are_known(tmp_path: Path) -> None:
    """AC-E.2: a tree with only a task.md names every check id, and no other."""
    tree = tmp_path / "tree"
    write(
        tree / PLAN_REL / "task.md",
        task_md(stop_gate="armed", rows="| 1 | a | b | c | [ ] |\n"),
    )
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("ok") is False
    assert set(doc.get("missing", [])) == CHECK_IDS


@pytest.mark.parametrize("status", ["[ ]", "[/]"])
def test_ac_e2_open_row_is_missing(tmp_path: Path, status: str) -> None:
    """AC-E.2 negative: a row that is not ``[x]`` → ``task_rows``."""
    tree = make_tree(tmp_path)
    rows = ROWS_DONE + f"| 4 | Open work | coder | code | {status} |\n"
    write(tree / PLAN_REL / "task.md", task_md(rows=rows))
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["task_rows"]


def test_ac_e2_valid_blocked_row_is_ok(tmp_path: Path) -> None:
    """AC-E.2: a ``[B]`` row with a follow-up, a ``B-<id>`` citation and its block → ok."""
    tree = make_tree(tmp_path)
    write(
        tree / PLAN_REL / "task.md", task_md(rows=ROWS_DONE + B_ROW_VALID, tail=B_BLOCK)
    )
    code, doc = check(tree)
    assert code == 0, doc
    assert doc.get("ok") is True


@pytest.mark.parametrize(
    ("row", "tail"),
    [
        (B_ROW, B_BLOCK),
        (B_ROW_VALID, ""),
        ("| 3 | Live check, follow-up | tester | receipt | [B] |\n", B_BLOCK),
    ],
    ids=["no-follow-up-no-cite", "no-block", "no-cite"],
)
def test_ac_e2_invalid_blocked_row_is_missing(
    tmp_path: Path, row: str, tail: str
) -> None:
    """AC-E.2 negative: a ``[B]`` row without its evidence → ``task_rows``."""
    tree = make_tree(tmp_path)
    write(tree / PLAN_REL / "task.md", task_md(rows=ROWS_DONE + row, tail=tail))
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["task_rows"]


@pytest.mark.parametrize("gate", ["armed", "released:handback", "released:human-gate"])
def test_ac_e2_stop_gate_not_done_is_missing(tmp_path: Path, gate: str) -> None:
    """AC-E.2 negative: ``stop_gate`` other than ``released:done`` → ``stop_gate``."""
    tree = make_tree(tmp_path)
    write(tree / PLAN_REL / "task.md", task_md(stop_gate=gate))
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["stop_gate"]


def test_mx_25_ac_e2_no_review_is_missing(tmp_path: Path) -> None:
    """mx_25_ AC-E.2 negative: no approved verdict file → ``approved_verdict``."""
    tree = make_tree(tmp_path)
    review_path(tree).unlink()
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["approved_verdict"]


def test_ac_e2_last_verdict_not_approved_is_missing(tmp_path: Path) -> None:
    """AC-E.2 negative: the last ``verdict:`` line is ``changes_required`` → ``approved_verdict``."""
    tree = make_tree(tmp_path)
    text = REVIEW_APPROVED.replace('verdict: "approved"', 'verdict: "changes_required"')
    text += "\n## Round 3\n\nverdict: changes_required\nfindings_count: 2\n"
    write(review_path(tree), text)
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["approved_verdict"]


def test_ac_e2_last_verdict_approved_without_frontmatter_is_ok(tmp_path: Path) -> None:
    """AC-E.2: no frontmatter verdict; the last round's ``verdict: approved`` → ok."""
    tree = make_tree(tmp_path)
    text = REVIEW_APPROVED.split("---\n", 2)[2]
    write(review_path(tree), text)
    code, doc = check(tree)
    assert code == 0, doc


def test_ac_e2_review_without_markers_is_missing(tmp_path: Path) -> None:
    """AC-E.2 negative: an approved review with no findings table → ``approved_verdict``."""
    tree = make_tree(tmp_path)
    write(review_path(tree), "# Review\n\nverdict: approved\n")
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["approved_verdict"]


def test_mx_25_ac_e2_no_handoff_is_missing(tmp_path: Path) -> None:
    """mx_25_ AC-E.2 negative: no handoff → ``handoff``."""
    tree = make_tree(tmp_path)
    (tree / ".agent" / "context" / "handoffs" / f"{PLAN}-handoff.md").unlink()
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["handoff"]


def test_ac_e2_handoff_without_marker_is_missing(tmp_path: Path) -> None:
    """AC-E.2 negative: a handoff with no ``CACHE BOUNDARY`` → ``handoff``."""
    tree = make_tree(tmp_path)
    path = tree / ".agent" / "context" / "handoffs" / f"{PLAN}-handoff.md"
    write(path, HANDOFF.replace("<!-- CACHE BOUNDARY -->\n", ""))
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["handoff"]


def test_ac_e2_product_plan_needs_one_handoff_per_meu(tmp_path: Path) -> None:
    """AC-E.2: ``meus`` lists two MEUs → one handoff each; the plan-level name does not count."""
    tree = make_tree(tmp_path, meus=("MEU-901", "MEU-902"))
    code, doc = check(tree)
    assert code == 0, doc
    handoffs = tree / ".agent" / "context" / "handoffs"
    (handoffs / f"{PLAN}-MEU-902-handoff.md").unlink()
    write(handoffs / f"{PLAN}-handoff.md", HANDOFF)
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["handoff"]


def test_mx_25_ac_e2_no_reflection_is_missing(tmp_path: Path) -> None:
    """mx_25_ AC-E.2 negative: no reflection → ``reflection``."""
    tree = make_tree(tmp_path)
    (tree / "docs" / "execution" / "reflections" / f"{PLAN}-reflection.md").unlink()
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["reflection"]


def test_ac_e2_reflection_without_marker_is_missing(tmp_path: Path) -> None:
    """AC-E.2 negative: a reflection with no Instruction Coverage block → ``reflection``."""
    tree = make_tree(tmp_path)
    path = tree / "docs" / "execution" / "reflections" / f"{PLAN}-reflection.md"
    write(path, REFLECTION.split("## Instruction Coverage", 1)[0])
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["reflection"]


def test_ac_e2_no_metrics_row_is_missing(tmp_path: Path) -> None:
    """AC-E.2 negative: metrics.md has no row for the plan → ``metrics``."""
    tree = make_tree(tmp_path)
    write(tree / "docs" / "execution" / "metrics.md", METRICS)
    code, doc = check(tree)
    assert code == 1, doc
    assert doc.get("missing") == ["metrics"]


def test_ac_e2_two_missing_items_are_both_named(tmp_path: Path) -> None:
    """AC-E.2 negative: no review and no reflection → both ids, exit 1."""
    tree = make_tree(tmp_path)
    review_path(tree).unlink()
    (tree / "docs" / "execution" / "reflections" / f"{PLAN}-reflection.md").unlink()
    code, doc = check(tree)
    assert code == 1, doc
    assert set(doc.get("missing", [])) == {"approved_verdict", "reflection"}


def test_ac_e2_reads_only(tmp_path: Path) -> None:
    """AC-E.2: the check writes nothing in the tree (pass and fail)."""
    tree = make_tree(tmp_path)
    before = tree_digest(tree)
    code, _ = check(tree)
    assert code == 0
    review_path(tree).unlink()
    middle = tree_digest(tree)
    code, _ = check(tree)
    assert code == 1
    assert tree_digest(tree) == middle
    assert before != middle


# --- AC-E.2 boundary: the CLI -----------------------------------------------------


def test_ac_e2_boundary_unknown_flag_exit_2(tmp_path: Path) -> None:
    """AC-E.2 boundary: an unknown flag → exit 2."""
    tree = make_tree(tmp_path)
    proc = run_tool("--plan", PLAN_REL, "--tree", str(tree), "--json", "--fix")
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_ac_e2_boundary_tree_not_a_directory_exit_2(tmp_path: Path) -> None:
    """AC-E.2 boundary: a tree that does not exist, or is a file → exit 2."""
    tree = make_tree(tmp_path)
    code, _ = check(tmp_path / "no-such-tree")
    assert code == 2
    code, _ = check(tree / PLAN_REL / "task.md")
    assert code == 2


@pytest.mark.parametrize(
    "plan",
    [
        "docs/execution/reflections",
        f"docs/execution/plans/{PLAN}/../../../../..",
        "docs/execution/plans",
    ],
    ids=["outside", "dot-dot", "plans-root"],
)
def test_ac_e2_boundary_plan_outside_plans_exit_2(tmp_path: Path, plan: str) -> None:
    """AC-E.2 boundary: a plan folder not under ``docs/execution/plans/`` → exit 2."""
    tree = make_tree(tmp_path)
    code, _ = check(tree, plan)
    assert code == 2


def test_ac_e2_boundary_missing_plan_folder_is_not_ok(tmp_path: Path) -> None:
    """AC-E.2 boundary: a plan folder under plans/ with no task.md → not ok, never exit 0."""
    tree = make_tree(tmp_path)
    code, doc = check(tree, "docs/execution/plans/2026-10-15-absent")
    assert code in (1, 2), doc
    assert doc.get("ok") is not True
