#!/usr/bin/env python3
"""validate_closeout_artifacts.py -- structural gates for the closeout artifact set.

Five checks, selected by which arguments are supplied:

  --handoff H --plan P                     handoff/plan binding, AC table, [B] rows
  --handoff H --plan P --ac-coverage-only   only: every plan AC-ID appears in the handoff
  --handoff H --handoff-structure-only      only: handoff structure, no plan needed
  --review F --review-state-only ...        parse the rolling review file -> state receipt
  --review F --review-state-receipt J ...   approval decided from the receipt on disk
  --reflection F --reflection-template T --reflection-schema S
  --reflection F ... --decision-source P [--decision-source H] [--decision-issue ID]
                                            plus: every decision recorded in the plan,
                                            handoff or issue has a Decisions Log row

Exit codes, and the first line of output always names which:

  0  ``OK:``           the check passed
  1  ``REFUSE:``       the check ran and says no
  2  ``USAGE:``        the invocation is wrong
  3  ``FAIL-CLOSED:``  the check could not run

3 is distinct from 1 on purpose, everywhere, without exception. Collapsing them is
how a repo comes to believe an unrun check passed: a missing file, an unreadable
artifact and an absent dependency all produce "no findings", and "no findings"
reads as approval. The caller must be able to tell "the gate said no" from "the
gate never spoke" (V5).

Run ``--selftest`` to prove every refusal above can actually fire. A gate that
cannot fail is not a gate, and the only evidence that this one can is a case that
makes it.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import textwrap
from durable_evidence import blocked_evidence_problems, evidence_problems
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Iterator, NamedTuple

SCHEMA_VERSION = "closeout-review-state.v1"

#: THE ONE ALLOWLIST for the review-state receipt. ``write_state`` and ``read_state``
#: both use this tuple and nothing else may. A write path and a read path maintained
#: separately drift, and the drift is silent in the worst direction: the write
#: succeeds, every later read refuses the file it just wrote, and the state is
#: unrecoverable without hand-editing. Adding a field means adding it HERE, once.
#: (V42 -- the originating repo bricked a live review loop exactly this way.)
STATE_KEYS = (
    "schema_version",
    "review_path",
    "review_digest",
    "review_mode",
    "target_plan",
    "verdict",
    "rounds",
    "max_rounds",
    "open_findings",
)

REVIEW_MODES = ("plan", "execution", "discovery", "handoff", "multi-handoff")

AC_ID = re.compile(r"\bAC-(\d+)\b")
RECHECK_HEADING = re.compile(r"^##\s+Recheck\b", re.MULTILINE)
TABLE_ROW = re.compile(r"^\|(?!\s*[-: ]+\|)(.+)\|\s*$", re.MULTILINE)
PLAN_SLUG = re.compile(r"(\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*)")
# A placeholder token, not a value. Any of these in a cell means the template was
# copied and not filled -- which passes every "is the section present" check.
PLACEHOLDER = re.compile(r"\{[A-Za-z0-9_|\\ .-]+\}|TBD|TODO|XXX|<[a-z-]+>")
# The specific unfilled markers REFLECTION-TEMPLATE.md ships. A copied-not-filled
# reflection has every required heading and every required schema field, so section
# and field checks both pass on it -- these strings are the only thing that tells a
# filled reflection from a fresh copy of the form.
UNFILLED = (
    "_Answer here_",
    "_Practice that worked well_",
    "_Ceremony without payoff_",
    "_Gap that caused problems_",
    "RULE-1: {description}",
    "{conversation-id}",
    "| ___ |",
)
# One field name at indent 2 inside the schema's `fields:` block.
SCHEMA_FIELD = re.compile(r"^  ([a-z_][a-z0-9_]*):\s*$")
YAML_FENCE = re.compile(r"```ya?ml\n(.*?)```", re.DOTALL)
RULE_LINE = re.compile(r"^RULE-\d+:\s*(\S.*)$", re.MULTILINE)


class Refuse(Exception):
    """The check ran and the answer is no."""


class FailClosed(Exception):
    """The check could not run. Never report this as a pass."""


class Usage(Exception):
    """The invocation is wrong."""


# --------------------------------------------------------------------------- io


def read_text(path: str, label: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FailClosed(
            f"{label} not found at {path}. This is not a pass: the check had nothing "
            f"to read, so it proved nothing about the artifact."
        )
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise FailClosed(f"{label} at {path} could not be read: {exc}")
    except UnicodeDecodeError as exc:
        raise FailClosed(
            f"{label} at {path} is not UTF-8 ({exc}). Refusing to guess an encoding: "
            f"a mis-decoded artifact fails structural checks for reasons that look "
            f"like content problems."
        )
    if not text.strip():
        raise Refuse(f"{label} at {path} is empty. An empty artifact is not a closeout.")
    return text


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def frontmatter(text: str, label: str) -> dict:
    """Parse leading ``---`` YAML frontmatter as flat ``key: value`` pairs.

    Deliberately not a YAML parser. The artifact templates all use flat scalar
    frontmatter, and a real YAML dependency would make this tool fail closed on
    machines that have every artifact but not PyYAML -- trading a check that
    works for one that is merely more general.
    """
    if not text.startswith("---"):
        raise Refuse(
            f"{label} has no YAML frontmatter. The frontmatter carries the fields "
            f"every other check reads (plan_source, review_mode, verdict); without "
            f"it there is nothing to bind the artifact to its target."
        )
    end = text.find("\n---", 3)
    if end == -1:
        raise Refuse(f"{label} has an unterminated frontmatter block (no closing ---).")
    out: dict[str, str] = {}
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def table_cells(text: str, heading: str) -> list[list[str]]:
    """Rows of the first markdown table under ``heading``, as lists of cell strings."""
    return table_with_header(text, heading)[1]


CELL_SPLIT = re.compile(r"(?<!\\)\|")


def split_cells(row: str) -> list[str]:
    r"""Split a table row on *unescaped* pipes, then unescape the rest.

    ``str.split("|")`` was wrong for the tables this tool actually reads. Markdown needs
    a pipe inside a cell written ``\|``, and REVIEW-TEMPLATE's own placeholder rows are
    full of them: ``{Critical\|High\|Medium\|Low}``, ``{yes\|no}``,
    ``{open\|fixed\|accepted_risk}``. Splitting naively turned one such row into eleven
    cells against a seven-cell header, and every column located by position then pointed
    at the wrong cell -- silently, because a longer row raises nothing.
    """
    return [c.replace("\\|", "|") for c in CELL_SPLIT.split(row)]


def column_index(header: list[str], label: str) -> int | None:
    """Position of the column named ``label``, or ``None``.

    One helper for every column lookup, because the alternative -- each caller
    normalising the header its own way -- is how one check finds the ``**Status**``
    column and the next one does not.
    """
    for i, cell in enumerate(header):
        if cell.strip().strip("*`").lower() == label:
            return i
    return None


def table_with_header(text: str, heading: str) -> tuple[list[str], list[list[str]]]:
    """``(header cells, data rows)`` of the first markdown table under ``heading``.

    Callers that locate a column by label need the header; callers that only count
    rows use :func:`table_cells`. Same scan either way, so the two cannot disagree
    about which table they are reading.
    """
    idx = text.find(heading)
    if idx == -1:
        return [], []
    # Stop at the next same-or-higher-level heading so a later table is not read as
    # this section's -- the single most common way a "section present" check passes
    # while pointing at the wrong table.
    level = len(heading) - len(heading.lstrip("#"))
    stop = re.search(rf"^#{{1,{max(level, 1)}}}\s", text[idx + len(heading):], re.MULTILINE)
    body = text[idx + len(heading):]
    if stop:
        body = body[: stop.start()]
    rows = []
    for match in TABLE_ROW.finditer(body):
        cells = [c.strip() for c in split_cells(match.group(1))]
        if cells and not all(re.fullmatch(r"[-: ]*", c) for c in cells):
            rows.append(cells)
    if not rows:
        return [], []
    return rows[0], rows[1:]  # header, then the data rows


# ------------------------------------------------------------------- receipt io


def write_state(path: str, state: dict) -> None:
    payload = {k: state[k] for k in STATE_KEYS}
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        raise FailClosed(
            f"could not write the review-state receipt to {path}: {exc}. The next "
            f"stage reads approval from this file, so a failed write must not look "
            f"like a passing check."
        )


def read_state(path: str) -> dict:
    raw = read_text(path, "review-state receipt")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FailClosed(f"review-state receipt at {path} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise FailClosed(f"review-state receipt at {path} is not a JSON object.")
    missing = [k for k in STATE_KEYS if k not in data]
    if missing:
        raise FailClosed(
            f"review-state receipt at {path} is missing {', '.join(missing)}. It was "
            f"probably written by a different version of this tool; re-run the "
            f"--review-state-only stage rather than editing the receipt."
        )
    if data["schema_version"] != SCHEMA_VERSION:
        raise FailClosed(
            f"review-state receipt at {path} is {data['schema_version']!r}, this tool "
            f"writes {SCHEMA_VERSION!r}. Re-run the --review-state-only stage."
        )
    return data


# ---------------------------------------------------------------- handoff check


def plan_slug(plan_path: str) -> str:
    """The ``{date}-{project-slug}`` directory that identifies one plan.

    The slug, not the filename. Every plan is called ``implementation-plan.md``, so
    a handoff that merely mentions that filename is bound to no particular plan --
    which is the defect this whole check exists for.
    """
    parts = Path(plan_path).as_posix().split("/")
    for part in reversed(parts[:-1] if parts[-1].endswith(".md") else parts):
        match = PLAN_SLUG.fullmatch(part)
        if match:
            return match.group(1)
    raise Usage(
        f"cannot derive a plan slug from {plan_path!r}. Expected a path under "
        f"docs/execution/plans/{{YYYY-MM-DD}}-{{project-slug}}/."
    )


def check_handoff_binding(handoff_text: str, handoff_path: str, plan_path: str) -> list[str]:
    slug = plan_slug(plan_path)
    fm = frontmatter(handoff_text, f"handoff {handoff_path}")
    source = fm.get("plan_source", "")
    notes = []
    if not source:
        raise Refuse(
            f"handoff {handoff_path} has no plan_source in its frontmatter, so it is "
            f"not bound to any plan."
        )
    if slug not in source:
        raise Refuse(
            f"handoff {handoff_path} declares plan_source {source!r}, which does not "
            f"name the plan under review ({slug}). Every plan file is called "
            f"implementation-plan.md; matching the filename is not matching the plan, "
            f"and a handoff bound to the wrong plan passes every other check here."
        )
    if PLACEHOLDER.search(source):
        raise Refuse(
            f"handoff {handoff_path} plan_source is still a template placeholder "
            f"({source!r}). The field is present, which is why this needs its own "
            f"check rather than a presence test."
        )
    notes.append(f"plan_source binds to {slug}")
    return notes


def check_blocked_rows(text: str, path: str) -> list[str]:
    """Every ``[B]`` row needs a linked follow-up and row-bound evidence.

    ``[B]`` is the one status that closes a row without the work being done, so it
    is the only status worth a machine check: an unlinked ``[B]`` is indistinguishable
    from abandonment, and reads as completion in every tally.
    """
    blocked = [line for line in text.splitlines() if "[B]" in line and line.lstrip().startswith("|")]
    if not blocked:
        return ["no [B] rows"]
    bad = []
    for line in blocked:
        # The row's own AC-N identifier is stripped first. It matches every
        # ticket-shaped pattern below, so without this every [B] row on an AC table
        # would look like it cited a follow-up -- the check would be structurally
        # incapable of failing on exactly the table it was written for.
        row_id = split_cells(line.strip().strip("|"))[0].strip("`* ")
        problems = blocked_evidence_problems(line, row_id, text, Path(path))
        bad.extend(f"{row_id}: {problem}" for problem in problems)
    if bad:
        raise Refuse(
            f"Invalid [B] evidence in {path}:\n  " + "\n  ".join(bad)
        )
    return [f"{len(blocked)} [B] row(s), all with linked follow-up and blocker evidence"]


def check_ac_coverage(handoff_text: str, handoff_path: str, plan_text: str, plan_path: str) -> list[str]:
    plan_acs = {m.group(0) for m in AC_ID.finditer(plan_text)}
    if not plan_acs:
        raise Refuse(
            f"plan {plan_path} declares no AC-N identifiers. Coverage of an empty AC "
            f"set is vacuously complete, so this is refused rather than passed (V5)."
        )
    handoff_acs = {m.group(0) for m in AC_ID.finditer(handoff_text)}
    missing = sorted(plan_acs - handoff_acs, key=lambda s: int(s.split("-")[1]))
    if missing:
        raise Refuse(
            f"{len(missing)} plan AC(s) never appear in handoff {handoff_path}: "
            f"{', '.join(missing)}. A silently dropped AC is a blocker, not a "
            f"deferral (HANDOFF-TEMPLATE control C4) -- list it with a non-done "
            f"status instead of omitting it."
        )
    return [f"all {len(plan_acs)} plan AC(s) present in the handoff"]


def check_handoff_structure(text: str, path: str) -> list[str]:
    required = ["## Acceptance Criteria", "## Decision Log", "## Evidence"]
    absent = [h for h in required if h not in text]
    if absent:
        raise Refuse(
            f"handoff {path} is missing required section(s): {', '.join(absent)}."
        )
    # HDP-10: the section attests in a form the reconciliation reads, or not at all.
    decisions = handoff_decision_log(text, path)
    rows = table_cells(text, "## Acceptance Criteria")
    if not rows:
        raise Refuse(
            f"handoff {path} has an '## Acceptance Criteria' heading but no table "
            f"rows under it. The heading is what a presence check sees; the rows are "
            f"what a reviewer needs."
        )
    problems = evidence_problems(text)
    if problems:
        raise Refuse(f"handoff {path}: " + "; ".join(problems))
    return [
        f"required sections present; {len(rows)} AC row(s); "
        f"{len(decisions)} decision(s) logged; durable evidence present"
    ]


# ----------------------------------------------------------------- review check


def parse_review(text: str, path: str) -> dict:
    fm = frontmatter(text, f"review {path}")
    mode = fm.get("review_mode", "")
    verdict = fm.get("verdict", "")
    target = fm.get("target_plan", "")
    rounds = 1 + len(RECHECK_HEADING.findall(text))
    header, rows = table_with_header(text, "## Findings")
    blocking_col = column_index(header, "blocking")
    # The status is read from the column that says Status, not from wherever the row
    # happens to end. This used to scan ``cells[-2:]``, which is wrong in both
    # directions and worse in one:
    #
    #   * REVIEW-TEMPLATE's Findings table ends `... | Recommendation | Status |`, so
    #     the scan also read Recommendation -- a fix reading "open a follow-up issue"
    #     counted a *fixed* row as open, and the reviewer's remedy for that is to write
    #     vaguer recommendations.
    #   * Append one column (Owner, Round, Verified-by -- all things reviewers add) and
    #     Status moves out of the last two cells entirely. Every row then reads as not
    #     open, `open_findings` is 0, and an `approved` verdict sitting on top of open
    #     blocking findings passes the gate. A false approval is the failure this whole
    #     stage exists to prevent, and it arrived via a table edit nobody would think
    #     to re-verify.
    status_col = column_index(header, "status")
    if rows and status_col is None:
        raise Refuse(
            f"review {path} has a '## Findings' table with {len(rows)} row(s) but no "
            f"'Status' column, so no row's state can be determined. Refusing rather "
            f"than reading the last cell and hoping: guessing the column is how an open "
            f"blocking finding becomes invisible to the approval gate. Use the "
            f"REVIEW-TEMPLATE header, which names Status explicitly."
        )
    open_findings = 0
    for n, cells in enumerate(rows, 1):
        if len(cells) != len(header):
            raise Refuse(
                f"review {path}: Findings row {n} has {len(cells)} cell(s) but the "
                f"header has {len(header)}. Positional column lookup is meaningless on "
                f"a ragged row, and the failure is silent in the dangerous direction -- "
                f"an extra cell shifts Status out from under the reader and the row "
                f"stops counting as open. The usual cause is an unescaped pipe inside a "
                f"cell: write it as a backslash-pipe, the way REVIEW-TEMPLATE does."
            )
        status = cells[status_col]
        if status.strip() and not re.search(r"\bopen\b", status, re.IGNORECASE):
            continue
        # Falling through on an empty or absent Status cell is deliberate, and matches
        # the Blocking column's rule below: a row that does not say it is closed has
        # not been shown to be closed, so it counts. The template's unfilled
        # `{open|fixed|accepted_risk}` placeholder counts too -- it contains "open".
        # review-verdict.schema.v2 separates `blocking` from `severity`: an approval MAY
        # carry an open non-blocking finding. Counting those as blockers here would push
        # the reviewer back into recording real observations as prose to get the array
        # empty -- the exact v1 behaviour v2 dropped.
        #
        # Only an explicit negative exempts a row. A missing Blocking column (the legacy
        # table shape), an empty cell, or an unfilled `{yes|no}` placeholder cannot prove
        # a finding is non-blocking, so every open row still counts: the ambiguous case
        # refuses the approval rather than granting it.
        if blocking_col is not None and blocking_col < len(cells):
            cell = cells[blocking_col].strip().strip("*`").lower()
            if cell in ("no", "false", "non-blocking", "n"):
                continue
        open_findings += 1
    return {
        "review_mode": mode,
        "verdict": verdict,
        "target_plan": target,
        "rounds": rounds,
        "open_findings": open_findings,
    }


def check_review_state(
    text: str, path: str, expected_mode: str, expected_plan: str, max_rounds: int
) -> tuple[dict, list[str]]:
    parsed = parse_review(text, path)

    if parsed["review_mode"] not in REVIEW_MODES:
        raise Refuse(
            f"review {path} declares review_mode {parsed['review_mode']!r}, which is "
            f"not one of {', '.join(REVIEW_MODES)}. The mode selects the round budget, "
            f"so an unrecognised one has no budget to check against."
        )
    if expected_mode and parsed["review_mode"] != expected_mode:
        raise Refuse(
            f"review {path} is review_mode {parsed['review_mode']!r} but this gate "
            f"expected {expected_mode!r}. A plan review satisfying an execution gate "
            f"is the failure this argument exists to catch."
        )
    if expected_plan:
        want = plan_slug(expected_plan)
        if want not in parsed["target_plan"]:
            raise Refuse(
                f"review {path} targets {parsed['target_plan']!r}, which does not name "
                f"{want}. The rolling review file must be the one for THIS plan -- a "
                f"review of a sibling plan passes every content check here."
            )
    if parsed["rounds"] > max_rounds:
        raise Refuse(
            f"review {path} has {parsed['rounds']} round(s), over the cap of "
            f"{max_rounds}. Rounds are counted from this one rolling file (1 for the "
            f"initial pass plus one per '## Recheck' heading); forking a sibling "
            f"'-recheck'/'-final' file is how a capped loop becomes uncapped, so the "
            f"cap reads this path and only this path."
        )

    state = {
        "schema_version": SCHEMA_VERSION,
        "review_path": Path(path).as_posix(),
        "review_digest": digest(text),
        "review_mode": parsed["review_mode"],
        "target_plan": parsed["target_plan"],
        "verdict": parsed["verdict"],
        "rounds": parsed["rounds"],
        "max_rounds": max_rounds,
        "open_findings": parsed["open_findings"],
    }
    notes = [
        f"review_mode={state['review_mode']}",
        f"round {state['rounds']} of {max_rounds}",
        f"verdict={state['verdict'] or '(none)'}",
        f"open findings={state['open_findings']}",
    ]
    return state, notes


def check_approved_state(
    text: str, path: str, state: dict, expected_mode: str, expected_plan: str, max_rounds: int
) -> list[str]:
    """Approval is decided from the receipt on disk, not re-derived here (SIGN-10b).

    Re-parsing would make this stage a second opinion, and two parsers of the same
    file disagree eventually. But a receipt is only evidence about the file it was
    written from, so the digest is checked first: without that, editing the review
    to say ``approved`` after the receipt was written would pass, and "read from a
    receipt" would be a laundering step rather than a control.
    """
    if state["review_digest"] != digest(text):
        raise Refuse(
            f"review-state receipt was written from a different version of {path} "
            f"(digest {state['review_digest']} vs {digest(text)} now). Re-run the "
            f"--review-state-only stage against the current file. Accepting a stale "
            f"receipt would let an edit after the state check decide the verdict."
        )
    if state["review_path"] != Path(path).as_posix():
        raise Refuse(
            f"review-state receipt is about {state['review_path']!r}, not {path!r}."
        )
    if expected_mode and state["review_mode"] != expected_mode:
        raise Refuse(
            f"receipt records review_mode {state['review_mode']!r}, expected "
            f"{expected_mode!r}."
        )
    if expected_plan:
        want = plan_slug(expected_plan)
        if want not in state["target_plan"]:
            raise Refuse(
                f"receipt targets {state['target_plan']!r}, which does not name {want}."
            )
    if state["rounds"] > max_rounds:
        raise Refuse(
            f"receipt records {state['rounds']} round(s), over the cap of {max_rounds}."
        )
    if state["verdict"] != "approved":
        raise Refuse(
            f"receipt records verdict {state['verdict']!r}, not 'approved'. "
            f"'pending' and 'changes_required' are not approval, and neither is a "
            f"missing verdict field."
        )
    if state["open_findings"]:
        raise Refuse(
            f"receipt records {state['open_findings']} open finding(s) that are not "
            f"marked non-blocking while the verdict is 'approved'. Approval over a "
            f"blocking row is not approval -- close it, or mark it 'no' in the "
            f"Findings table's Blocking column if it genuinely does not gate approval "
            f"(review-verdict.schema.v2 allows an approval to carry non-blocking "
            f"findings; it does not allow one to carry blocking findings)."
        )
    return [
        f"approved at round {state['rounds']} of {max_rounds}, "
        f"0 open blocking findings"
    ]


# ------------------------------------------------------------- reflection check


def schema_required_fields(text: str, path: str) -> list[str]:
    """The reflection fields a filled reflection must emit.

    Read structurally, not as YAML. A PyYAML dependency would make this whole tool
    fail closed on a machine that has every artifact and every schema, trading a
    check that works for one that is merely more general.

    ``required: false`` is honoured, and that is the point rather than a nicety:
    ``slim_candidate`` is documented as encouraged by the lint gate and *never*
    schema-required, so a checker that demanded every field would contradict the
    schema it claims to enforce.
    """
    fields: dict[str, bool] = {}
    # Top-level scalars (`schema: v1`) sit outside the `fields:` block but are part
    # of the shape a reflection emits.
    for match in re.finditer(r"^([a-z_][a-z0-9_]*):[ \t]+\S", text, re.MULTILINE):
        fields[match.group(1)] = True

    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == "fields:")
    except StopIteration:
        raise FailClosed(
            f"{path} has no top-level 'fields:' block, so no field names could be "
            f"read and the schema arm would pass vacuously. Zero matches is evidence "
            f"only once the detector is proven able to match (V5)."
        )

    current = None
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith("  "):
            break  # a new top-level key ends the fields block
        match = SCHEMA_FIELD.match(line)
        if match:
            current = match.group(1)
            fields[current] = True
            continue
        # Indent exactly 4 == this field's own `required:`. Deeper ones belong to a
        # nested property (reflection.v1.yaml has one at indent 8 under review_churn)
        # and must not flip the parent's requiredness.
        if current and re.match(r"^ {4}required:\s*false\s*$", line):
            fields[current] = False

    required = [name for name, req in fields.items() if req]
    if not required:
        raise FailClosed(
            f"{path} yielded no required field names. Refusing to report a pass from "
            f"an empty expectation set (V5)."
        )
    return required


# ------------------------------------------------------------ decisions log

DECISION_STAGES = ("planning", "plan-review", "execution", "closeout", "triage", "grouping")
DECISION_RESOLUTIONS = ("autonomous", "human")
# The reflection's Decisions Log table, exactly as REFLECTION-TEMPLATE.md ships it.
DECISIONS_LOG_HEADERS = [
    "ID",
    "Stage",
    "Question",
    "Resolution",
    "Chosen",
    "Source tag",
    "Reasoning (why this; why the alternatives lost)",
    "Human ref",
]
# A session grouping's §8 table is the same row without Stage (the stage is always
# `grouping`) and may still be undecided, so `open` is a third resolution there.
GROUPING_DECISION_HEADERS = [h for h in DECISIONS_LOG_HEADERS if h != "Stage"]
GROUPING_RESOLUTIONS = ("autonomous", "human", "open")
# Any fenced block, whatever its language tag. YAML_FENCE above only sees ```yaml,
# and a decision log that landed in a ```text fence has to be refused, not skipped.
# A fence may sit up to three columns in (CommonMark's indented-fence rule) and its
# body is dedented before it is read, so an indented record is still a record
# (HDP-15); four columns is an indented code block, which is not a fence anywhere.
# Three tildes open a fence exactly as three backticks do, and a fence closes only on
# its own marker (HDP-29): a `~~~` example left unmasked would stand in for a section
# or hide a record in prose.
FENCE = re.compile(
    r"^ {0,3}(?P<fence>```|~~~)(?P<lang>[^\n]*)\n(?P<body>.*?)\n {0,3}(?P=fence)[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
# The discovery signal for a `decision_log` KEY, wherever YAML can put one: at the
# start of a line under any indentation (`  decision_log:` is a root key the author
# indented, not a different key -- HDP-15), after one or more `- ` sequence markers,
# or inside a flow collection after `{`, `[` or `,`; plain or quoted (HDP-27). It is
# deliberately a superset: `decision_log_keys` decides what a match means, so a match
# in a quoted scalar or a comment costs nothing, while a key this signal missed would
# never be walked at all. Quoted excerpts are excluded by fence context (```diff /
# ```patch fences are never read), not by ignoring shapes.
DECISION_LOG_KEY = re.compile(
    r"(?:^[ \t]*(?:-[ \t]+)*|[{,\[][ \t]*)(?:decision_log|\"decision_log\"|'decision_log')"
    r":(?=[ \t]|$|[,}\]])",
    re.MULTILINE,
)
# The same key inside one flow collection's text (HDP-28).
FLOW_DECISION_LOG_KEY = re.compile(
    r"[{,\[][ \t]*(?:decision_log|\"decision_log\"|'decision_log')[ \t]*:(?=[ \t]|$|[,}\]])"
)
EXCERPT_FENCE_LANGS = ("diff", "patch")
YAML_ITEM = re.compile(r"^(?P<indent>[ \t]*)-(?:[ \t]+|$)", re.MULTILINE)
# `key:` / `key: value`; keys are the snake_case protocol keys or a quoted string.
YAML_KEY = re.compile(r"^(?P<key>[A-Za-z0-9_][A-Za-z0-9_.\-]*|\"[^\"]*\"|'[^']*'):(?:[ \t]+(?P<value>.*)|)$")
YAML_BLOCK_SCALAR = re.compile(r"^[|>](?:[+-]?\d?|\d?[+-]?)$")
# The template closes the handoff's Decision Log with a horizontal rule; the rule is
# the section's frame, not its content (HDP-16).
TRAILING_RULE = re.compile(r"(?:\n[ \t]*(?:---|\*\*\*|___)[ \t]*)+\s*\Z")
# A session grouping is known by its §8 heading or by being the file a plan's
# frontmatter declares as `grouping_source`, never by its filename alone (HDP-18).
# The heading is matched against the file's structure (fences and comments blanked),
# so a quoted example of it is not a signal (HDP-25).
OPEN_DECISIONS_HEADING = re.compile(r"^## 8\. Open Decisions", re.MULTILINE)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# YAML's spellings of null; a frontmatter value that is one of these is absent (HDP-31).
YAML_NULLS = ("", "~", "null", "Null", "NULL")
# A known-issues file is its root-level `issues:` sequence, an inline comment allowed;
# an `issues:` nested under another key is a layout this reader does not support and
# says so rather than reading zero issues from it (HDP-17).
ISSUES_ROOT = re.compile(r"^issues:[ \t]*(?:#.*)?$", re.MULTILINE)
ISSUES_NESTED = re.compile(r"^[ \t]+issues:[ \t]*(?:#.*)?$", re.MULTILINE)
ENRICHMENT_KEY = re.compile(r"^[ \t]+enrichment:[ \t]*(?:#.*)?$", re.MULTILINE)


def fence_body(match: re.Match[str]) -> str:
    """A fence body with its common indentation removed (HDP-15)."""
    return textwrap.dedent(match.group("body"))


def markdown_structure(text: str) -> str:
    """``text`` with every fenced block and HTML comment blanked out, offsets kept.

    HDP-25: a heading quoted inside a fence or a comment is an example, not the
    file's structure; a ``~~~`` fence is masked like a ````` one (HDP-29). Each
    masked character becomes a space (newlines stay), so a match against the result
    slices the original text at the same offsets.
    """

    def blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    return HTML_COMMENT.sub(blank, FENCE.sub(blank, text))


def _strip_inline_comment(value: str) -> str:
    quote: str | None = None
    for n, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (n == 0 or value[n - 1] in " \t"):
            return value[:n].rstrip()
    return value.rstrip()


# YAML 1.2 §5.7 escape characters a double-quoted scalar may spell after `\`; `x`,
# `u` and `U` take 2, 4 and 8 hex digits. Anything else (`\q`) is not YAML (HDP-22).
DQ_ESCAPES = "0abt\tnvfre \"/\\N_LP"
DQ_HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}


def _scan_double_quoted(text: str, start: int, refuse) -> int:
    """Index just past the closing quote of the double-quoted scalar opening at ``start``."""
    n = start + 1
    while n < len(text):
        ch = text[n]
        if ch == "\\":
            if n + 1 >= len(text):
                break
            esc = text[n + 1]
            if esc in DQ_HEX_ESCAPES:
                width = DQ_HEX_ESCAPES[esc]
                digits = text[n + 2 : n + 2 + width]
                if len(digits) != width or any(d not in "0123456789abcdefABCDEF" for d in digits):
                    refuse(f"double-quoted scalar has a malformed \\{esc} escape in {text[start:]!r}")
                n += 2 + width
                continue
            if esc not in DQ_ESCAPES:
                refuse(f"double-quoted scalar has the escape \\{esc}, which is not YAML, in {text[start:]!r}")
            n += 2
            continue
        if ch == '"':
            return n + 1
        n += 1
    refuse(f"double-quoted scalar {text[start:]!r} does not close on its line")
    return len(text)


def _scan_single_quoted(text: str, start: int, refuse) -> int:
    """Index just past the closing quote of the single-quoted scalar at ``start``."""
    n = start + 1
    while n < len(text):
        if text[n] == "'":
            if n + 1 < len(text) and text[n + 1] == "'":
                n += 2
                continue
            return n + 1
        n += 1
    refuse(f"single-quoted scalar {text[start:]!r} does not close on its line")
    return len(text)


def _check_flow(value: str, refuse) -> None:
    """Refuse a flow collection that is not one balanced, well-formed `[...]` / `{...}`.

    A small recursive-descent walk (HDP-22): brackets pair by kind, every entry is a
    non-empty scalar or nested collection (a trailing comma is YAML and allowed, an
    empty entry `[a,,b]` is not), a mapping entry is `key: value` or a bare `key`, and
    nothing follows the closing bracket. Plain scalars end at `,` `]` `}` and, in a
    mapping, at `:`.
    """
    n = 0

    def skip_space() -> None:
        nonlocal n
        while n < len(value) and value[n] == " ":
            n += 1

    def scalar(stop: str) -> None:
        nonlocal n
        if value[n] == '"':
            n = _scan_double_quoted(value, n, refuse)
        elif value[n] == "'":
            n = _scan_single_quoted(value, n, refuse)
        else:
            start = n
            while n < len(value) and value[n] not in stop:
                n += 1
            plain = value[start:n].strip()
            if not plain:
                refuse(f"flow collection {value!r} has an empty entry")
            if plain[0] in "[{":
                refuse(f"flow collection {value!r} nests a collection where a scalar was expected")
            if ": " in plain or plain.endswith(":"):
                refuse(f"flow collection {value!r} holds ': ' inside a plain scalar; quote it")

    def item(stop: str) -> None:
        nonlocal n
        skip_space()
        if n >= len(value):
            refuse(f"flow collection {value!r} is not closed on its line")
        if value[n] == "[":
            sequence()
        elif value[n] == "{":
            mapping()
        else:
            scalar(stop)
        skip_space()

    def sequence() -> None:
        nonlocal n
        n += 1
        skip_space()
        while True:
            if n >= len(value):
                refuse(f"flow collection {value!r} is not closed on its line")
            if value[n] == "]":
                n += 1
                return
            if value[n] in ",}":
                refuse(f"flow collection {value!r} has an empty or mismatched entry at {value[n]!r}")
            item(",]}")
            if n >= len(value):
                refuse(f"flow collection {value!r} is not closed on its line")
            if value[n] == ",":
                n += 1
                skip_space()
            elif value[n] != "]":
                refuse(f"flow sequence {value!r} expected ',' or ']' at {value[n]!r}")

    def mapping() -> None:
        nonlocal n
        n += 1
        skip_space()
        while True:
            if n >= len(value):
                refuse(f"flow collection {value!r} is not closed on its line")
            if value[n] == "}":
                n += 1
                return
            if value[n] in ",]:":
                refuse(f"flow collection {value!r} has an empty or mismatched entry at {value[n]!r}")
            scalar(":,}]")
            skip_space()
            if n < len(value) and value[n] == ":":
                n += 1
                if n < len(value) and value[n] not in " ,}":
                    refuse(f"flow mapping {value!r} needs a space after ':'")
                skip_space()
                if n < len(value) and value[n] not in ",}":
                    item(",}]")
            if n >= len(value):
                refuse(f"flow collection {value!r} is not closed on its line")
            if value[n] == ",":
                n += 1
                skip_space()
            elif value[n] != "}":
                refuse(f"flow mapping {value!r} expected ',' or '}}' at {value[n]!r}")

    item(",]}")
    if n != len(value):
        refuse(f"text follows the flow collection {value!r}")


def _check_yaml_scalar(value: str, refuse) -> str:
    """Classify one value of the bounded grammar: empty / quoted / flow / block / plain."""
    value = _strip_inline_comment(value.strip())
    if not value:
        return "empty"
    if value[0] == '"':
        if _scan_double_quoted(value, 0, refuse) != len(value):
            refuse(f"text follows the double-quoted scalar {value!r}")
        return "quoted"
    if value[0] == "'":
        if _scan_single_quoted(value, 0, refuse) != len(value):
            refuse(f"text follows the single-quoted scalar {value!r}")
        return "quoted"
    if value[0] in "[{":
        _check_flow(value, refuse)
        return "flow"
    if YAML_BLOCK_SCALAR.match(value):
        return "block"
    if value[0] in "]}&*!%@`":
        refuse(f"scalar {value!r} starts with a YAML indicator this grammar does not read")
    if ": " in value or value.endswith(":"):
        refuse(f"plain scalar {value!r} contains ': '; quote it")
    return "plain"


def check_yaml_subset(text: str, label: str) -> None:
    """Refuse text outside the bounded YAML grammar this stdlib-only reader walks (HDP-19).

    The grammar, one construct per line: ``key:`` opening a nested block, ``key:
    scalar``, ``key: [flow]`` / ``key: {flow}`` balanced on that line, ``key: |`` /
    ``key: >`` whose deeper lines are opaque, ``- `` items at one indent, blank and
    ``#`` comment lines, and a ``#`` comment after a value. Quoted scalars open and
    close on one line (with YAML's escapes only), flow collections pair their
    brackets by kind and hold no empty entry, indentation is spaces, a dedent returns
    to an open level, one indentation level is either a mapping or a sequence (never
    both), and only an empty ``key:`` / bare ``-`` opens a deeper block -- a line
    indented under a scalar, quoted or flow value is refused (HDP-22). A record
    outside the grammar is refused as not valid YAML rather than read as a well-formed
    one or dropped, which is what ``yaml_sequence`` would otherwise do.
    """
    levels = [0]
    # The container kind of each open level, fixed by its first line.
    kinds: list[str | None] = [None]
    opened = True
    block_scalar_indent: int | None = None
    for number, raw in enumerate(text.splitlines(), 1):

        def refuse(why: str, number: int = number) -> None:
            raise Refuse(f"{label} is not valid YAML: line {number}: {why}.")

        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        if block_scalar_indent is not None:
            if not stripped or indent > block_scalar_indent:
                continue
            block_scalar_indent = None
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            refuse("indented with a tab")
        if indent > levels[-1]:
            if not opened:
                refuse(f"unexpected indentation before {stripped!r}")
            levels.append(indent)
            kinds.append(None)
        elif indent < levels[-1]:
            while levels and levels[-1] > indent:
                levels.pop()
                kinds.pop()
            if not levels or levels[-1] != indent:
                refuse(f"{stripped!r} dedents to an indentation level that is not open")
        line_kind = "sequence" if stripped == "-" or stripped.startswith("- ") else "mapping"
        if kinds[-1] is None:
            kinds[-1] = line_kind
        elif kinds[-1] != line_kind:
            refuse(f"{stripped!r} mixes a mapping and a sequence at one indentation")
        content, column = stripped, indent
        if content == "-":
            opened = True
            continue
        if content.startswith("- "):
            inner = content[2:].lstrip()
            column = indent + len(content) - len(inner)
            content = inner
        key = YAML_KEY.match(content)
        if key is None:
            if column == indent:
                refuse(f"{stripped!r} is not a 'key: value' line")
            _check_yaml_scalar(content, refuse)
            opened = False
            continue
        kind = _check_yaml_scalar(key.group("value") or "", refuse)
        if kind == "block":
            block_scalar_indent = column
        # An item's mapping continues at the item's inner column; that level is a
        # mapping, and whether anything may sit deeper is decided by this value alone.
        if column > indent:
            levels.append(column)
            kinds.append("mapping")
        opened = kind == "empty"


class YamlLine(NamedTuple):
    """One key-bearing line of a bounded-grammar block, as the key walkers see it."""

    number: int
    column: int
    key: str | None
    value: str
    item: bool


def yaml_key_lines(text: str) -> Iterator[YamlLine]:
    """Every line of ``text`` that can carry a mapping key, with its mapping column.

    The walk follows the bounded grammar the way ``check_yaml_subset`` does -- blank
    and comment lines skipped, block-scalar bodies skipped, one or more ``- `` markers
    moving the key's column and flagging the line as the start of a sequence item --
    so the words ``decision_log:`` or ``id:`` inside a quoted scalar, a block scalar
    or a comment are text, not keys. A bare flow item (``- {a: b}``) is yielded with
    ``key`` None and the collection as its ``value``, so a walker can look inside it.
    """
    block_scalar_indent: int | None = None
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" \t"))
        if block_scalar_indent is not None:
            if not stripped or indent > block_scalar_indent:
                continue
            block_scalar_indent = None
        if not stripped or stripped.startswith("#") or stripped == "-":
            continue
        content, column, item = stripped, indent, False
        while content.startswith("- "):
            inner = content[2:].lstrip()
            column += len(content) - len(inner)
            content, item = inner, True
        key = YAML_KEY.match(content)
        if key is None:
            if content[0] in "[{":
                yield YamlLine(number, column, None, content, item)
            continue
        value = _strip_inline_comment((key.group("value") or "").strip())
        if YAML_BLOCK_SCALAR.match(value):
            block_scalar_indent = column
        yield YamlLine(number, column, _unquote(key.group("key")), value, item)


def decision_log_keys(text: str, label: str) -> None:
    """Refuse a ``decision_log:`` key anywhere but once at the root (HDP-20, HDP-24).

    A root key that parses can still hide a second log nested under another key
    (``wrapper:`` then ``decision_log:``), inside a flow collection
    (``wrapper: {decision_log: [...]}``, HDP-28), inside a sequence item
    (``- decision_log:``, HDP-27) or as a second root key that YAML's last-wins rule
    would silently take over the first; every one of those drops a recorded decision
    from the reconciliation, so each is refused by name. The lines come from
    ``yaml_key_lines``, so scalar text and comments are never keys; a flow
    collection is not walked but searched for the key, and any ``decision_log`` in
    one is refused, because the reader records a block sequence and nothing inside
    ``{...}`` / ``[...]`` would reach the reflection.
    """
    roots = 0
    for line in yaml_key_lines(text):
        if line.value[:1] in ("{", "[") and FLOW_DECISION_LOG_KEY.search(line.value):
            raise Refuse(
                f"{label} has a decision_log: inside a flow collection (line {line.number}); a "
                f"decision log is the block's root key written as a block sequence, and one "
                f"inside {{...}} or [...] would never reach the reflection (HDP-24, HDP-28)."
            )
        if line.key != "decision_log":
            continue
        if line.item:
            raise Refuse(
                f"{label} has a decision_log: inside a sequence item (line {line.number}); a "
                f"decision log is the block's root key, and one written under a `- ` marker "
                f"would never reach the reflection (HDP-27)."
            )
        if line.column > 0:
            raise Refuse(
                f"{label} has a decision_log: nested under another key (line {line.number}); a "
                f"decision log is the block's root key, and a nested one would never reach "
                f"the reflection (HDP-20, HDP-24)."
            )
        roots += 1
        if roots > 1:
            raise Refuse(
                f"{label} has a second root decision_log: key (line {line.number}); one block "
                f"records one log, and YAML would silently keep only the last (HDP-24)."
            )


def duplicate_mapping_key(text: str) -> tuple[str, int] | None:
    """``(key, line)`` of the first key written twice in one block mapping, else None.

    HDP-30: YAML keeps the last value of a repeated key, so ``id: D-1`` followed by
    ``id: D-LOST`` in one record reconciles whichever the reader happened to take and
    silently drops the other. Mappings are told apart by column and by ``- `` markers
    (a new item at the same column is a new mapping), so the same key name in two
    records, in two nested mappings, in a comment or in scalar text is never a
    duplicate. Keys inside a flow collection are outside this walk; ``check_yaml_subset``
    bounds their shape.
    """
    levels: list[tuple[int, set[str]]] = []
    for line in yaml_key_lines(text):
        while levels and levels[-1][0] > line.column:
            levels.pop()
        if line.item and levels and levels[-1][0] == line.column:
            levels.pop()
        if not levels or levels[-1][0] != line.column:
            levels.append((line.column, set()))
        if line.key is None:
            continue
        seen = levels[-1][1]
        if line.key in seen:
            return line.key, line.number
        seen.add(line.key)
    return None


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value.split(" #", 1)[0].strip()


def yaml_sequence(text: str, key: str, label: str, *, root: bool) -> list[str] | None:
    """The items of the first ``key:`` block sequence in ``text``, one string each.

    Stdlib only, like the rest of this file, so this is an indentation walk rather
    than a YAML parser: the sequence is every line indented deeper than the key,
    plus ``- `` lines at the key's own indent (YAML allows both), and an item is a
    ``- `` line at the first item's indent together with its continuation lines.
    ``root=True`` reads only a column-0 key (a fenced block's own root); otherwise
    the key may sit at any depth (an issue's ``enrichment.decision_log``). A quoted
    spelling of the key is the same key (HDP-27). Returns ``None`` when the key is
    absent; refuses an inline value that is not ``[]``.
    """
    spelled = rf"(?:{re.escape(key)}|\"{re.escape(key)}\"|'{re.escape(key)}')"
    pattern = rf"^{'' if root else '(?P<indent>[ \t]*)'}{spelled}:(?P<rest>[^\n]*)$"
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        return None
    depth = len(match.group("indent")) if not root else 0
    inline = match.group("rest").split("#", 1)[0].strip()
    if inline == "[]":
        return []
    if inline:
        raise Refuse(
            f"{label} {key}: has the inline value {inline!r}; the protocol records a "
            f"block sequence of decisions under it."
        )
    kept: list[str] = []
    for line in text[match.end():].splitlines(keepends=True):
        if line.strip():
            indent = len(line) - len(line.lstrip(" \t"))
            if indent < depth or (indent == depth and not YAML_ITEM.match(line)):
                break
        kept.append(line)
    body = "".join(kept)
    starts = list(YAML_ITEM.finditer(body))
    if not starts:
        return []
    item_indent = len(starts[0].group("indent"))
    starts = [m for m in starts if len(m.group("indent")) == item_indent]
    items: list[str] = []
    for n, start in enumerate(starts):
        end = starts[n + 1].start() if n + 1 < len(starts) else len(body)
        item = body[start.start(): end]
        # Rewrite the `- ` marker as spaces so every key of the item's mapping sits at
        # one column; a key at any deeper column belongs to a nested value.
        marker = start.end() - start.start()
        items.append(" " * marker + item[marker:])
    return items


def item_key(item: str, key: str) -> str | None:
    """The scalar of ``key:`` in a sequence item's own mapping, at any key order.

    The mapping's keys all sit at the column where the first key was written after
    ``- ``; ``yaml_sequence`` rewrote that marker as spaces, so the column is the
    indent of the item's first non-blank line, and ``research:`` / ``precedents:``
    values one level deeper cannot shadow the item's own ``id`` or ``stage``.
    """
    first = next((line for line in item.splitlines() if line.strip()), "")
    column = len(first) - len(first.lstrip(" \t"))
    match = re.search(rf"^[ \t]{{{column}}}{re.escape(key)}:(?P<value>[^\n]*)$", item, re.MULTILINE)
    if match is None:
        return None
    return _unquote(match.group("value"))


def decision_entries(items: list[str] | None, label: str) -> list[tuple[str, str | None]]:
    """``(id, stage)`` for every item of a ``decision_log:`` sequence.

    A ``{template}`` slot anywhere in an item means the plan kept the example, and
    an example is not a decision -- refusing it is how an unfilled Decision Log is
    told apart from an empty one. The key itself with nothing under it is refused
    too: the protocol spells an empty log ``None.``, never as an empty record. A key
    written twice in one mapping of a record is refused before ``id`` or ``stage``
    is read, so no reading is first-wins where YAML is last-wins (HDP-30).
    """
    if items is None:
        return []
    if not items:
        raise Refuse(
            f"{label} decision_log has no items; an empty log is spelled None. "
            f"(human-decision-protocol.md §6)."
        )
    entries: list[tuple[str, str | None]] = []
    for n, item in enumerate(items, 1):
        check_yaml_subset(textwrap.dedent(item), f"{label} decision_log item {n}")
        duplicate = duplicate_mapping_key(item)
        if duplicate is not None:
            raise Refuse(
                f"{label} decision_log item {n} names the mapping key {duplicate[0]!r} twice "
                f"(item line {duplicate[1]}); YAML keeps only the last value, so the first "
                f"would be dropped silently (HDP-30)."
            )
        if PLACEHOLDER.search(item):
            raise Refuse(
                f"{label} decision_log item {n} still carries a template placeholder. "
                f"An unfilled example is not a decision; delete it or fill it."
            )
        decision_id = item_key(item, "id")
        if not decision_id:
            raise Refuse(
                f"{label} decision_log item {n} has no id; a decision that cannot be "
                f"named cannot be reconciled with the reflection."
            )
        stage = item_key(item, "stage")
        if stage is not None and stage not in DECISION_STAGES:
            raise Refuse(
                f"{label} decision_log entry {decision_id} names stage {stage!r}; the "
                f"protocol stages are {', '.join(DECISION_STAGES)}."
            )
        entries.append((decision_id, stage))
    return entries


def fenced_decision_logs(text: str, label: str) -> list[tuple[str, str | None]]:
    """Every decision recorded in ``text``'s fenced ``yaml`` blocks (HDP-10).

    A ``decision_log:`` root key inside a fence with any other language tag, or in
    prose outside every fence, is refused rather than skipped: the author meant to
    record a decision and the record would otherwise vanish from reconciliation.
    The key is discovered in every shape YAML can write it -- sequence item, flow
    map, quoted -- and ``decision_log_keys`` then decides whether that shape is a
    supported record (HDP-27); a ``~~~yaml`` fence is a fence like a ```yaml one
    (HDP-29).
    """
    entries: list[tuple[str, str | None]] = []
    for match in FENCE.finditer(text):
        lang, body = match.group("lang").strip(), fence_body(match)
        if lang in EXCERPT_FENCE_LANGS or not DECISION_LOG_KEY.search(body):
            continue
        if lang not in ("yaml", "yml"):
            raise Refuse(
                f"{label} records a decision_log: inside a {match.group('fence')}"
                f"{lang or 'plain'} fence; "
                f"a decision log is only read from a ```yaml fence "
                f"(human-decision-protocol.md §6)."
            )
        check_yaml_subset(body, f"{label} decision_log block")
        decision_log_keys(body, f"{label} decision_log block")
        items = yaml_sequence(body, "decision_log", label, root=True)
        if items is None:
            raise Refuse(
                f"{label} names decision_log: in a ```yaml fence that has no root "
                f"decision_log: key; a decision log is the fence's root key "
                f"(HDP-20, HDP-24)."
            )
        entries.extend(decision_entries(items, label))
    if DECISION_LOG_KEY.search(FENCE.sub("", text)):
        raise Refuse(
            f"{label} has a decision_log: line outside any fence; a decision log is "
            f"only read from a ```yaml fence (human-decision-protocol.md §6)."
        )
    return entries


def handoff_decision_log(text: str, path: str) -> list[tuple[str, str | None]]:
    """The handoff's ``## Decision Log`` is exactly ``None.`` or one ```yaml fence.

    Anything else -- prose, a ```text fence, a ```yaml block without the key, two
    fences, an empty list -- is refused, so a handoff cannot attest "no decisions"
    in words the reconciliation never reads (HDP-10). The template's instruction
    comment and its closing horizontal rule are the section's frame and are ignored,
    so a filled copy of the shipped template validates (HDP-16); the block's YAML is
    checked against the bounded grammar before it is read (HDP-19).
    """
    match = re.search(r"^## Decision Log[^\n]*\n(?P<body>.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if match is None:
        raise Refuse(f"handoff {path} is missing required section(s): ## Decision Log.")
    body = re.sub(r"<!--.*?-->", "", match.group("body"), flags=re.DOTALL).rstrip()
    body = TRAILING_RULE.sub("", body).strip()
    if body == "None.":
        return []
    fence = FENCE.fullmatch(body)
    if fence is None or len(FENCE.findall(body)) != 1 or fence.group("lang").strip() not in ("yaml", "yml"):
        raise Refuse(
            f"handoff {path} Decision Log must be exactly 'None.' or one fenced ```yaml "
            f"decision_log block (human-decision-protocol.md §6)."
        )
    label = f"handoff {path} Decision Log"
    block = fence_body(fence)
    check_yaml_subset(block, f"{label} block")
    decision_log_keys(block, f"{label} block")
    items = yaml_sequence(block, "decision_log", label, root=True)
    if items is None:
        raise Refuse(f"{label} ```yaml block has no root decision_log: key.")
    return decision_entries(items, label)


def handoff_decisions(text: str, path: str) -> list[tuple[str, str | None]]:
    """Every decision a handoff records, read exactly as the structure gate reads it.

    HDP-15: ``check_handoff_structure`` and the reconciliation must share ONE
    interpretation of the handoff, or a record can pass the gate and vanish from
    the reflection. The ``## Decision Log`` section is the only place a handoff
    records a decision; a ``decision_log:`` anywhere else in the file is refused.
    """
    entries = handoff_decision_log(text, path)
    section = re.search(r"^## Decision Log[^\n]*\n(?P<body>.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    elsewhere = text.replace(section.group(0), "", 1) if section else text
    if fenced_decision_logs(elsewhere, f"handoff {path}"):
        raise Refuse(
            f"handoff {path} records a decision_log: outside its ## Decision Log section; "
            f"a handoff records decisions only there (human-decision-protocol.md §6)."
        )
    return entries


def issue_decision_log(text: str, name: str, issue: str) -> list[tuple[str, str | None]]:
    """``enrichment.decision_log`` of one issue in a known-issues file (HDP-11).

    The ``issues:`` sequence may be written at any indent and an item's ``id:`` in
    any key order; the named issue must exist, because reading nothing from a file
    that does not hold it would let a wrong ``--decision-issue`` pass vacuously.
    """
    if not ISSUES_ROOT.search(text):
        raise Refuse(
            f"decision source {name} has no root-level issues: key"
            + (" (one sits nested under another key)" if ISSUES_NESTED.search(text) else "")
            + "; a known-issues file is read only from its root-level issues: sequence, "
            f"so issue {issue}'s enrichment.decision_log could not be read (HDP-17)."
        )
    items = yaml_sequence(text, "issues", f"known-issues {name}", root=True) or []
    for item in items:
        if item_key(item, "id") == issue:
            enrichment = ENRICHMENT_KEY.search(item)
            block = item[enrichment.start():] if enrichment else ""
            return decision_entries(
                yaml_sequence(block, "decision_log", f"issue {issue}", root=False),
                f"issue {issue}",
            )
    raise Refuse(
        f"decision source {name} has no issue {issue}; --decision-issue must name an "
        f"issue the file holds, or the reconciliation reads nothing and passes vacuously."
    )


def grouping_decisions(text: str, name: str) -> list[tuple[str, str | None]]:
    """Every D-row of a session grouping's ``## 8. Open Decisions`` table (HDP-13).

    §8 is optional and may read ``None.``; otherwise it is the reflection's table
    without the Stage column, and every row -- decided or still ``open`` -- must be
    carried into the consuming session's reflection with stage ``grouping``. An
    ad-hoc table is refused: rows that cannot be read cannot be carried forward.
    The section is located in the file's structure: a ``## 8.`` inside a fence or a
    comment is an example that cannot stand in for it (HDP-25).
    """
    match = re.search(
        r"^## 8\.[^\n]*\n(?P<body>.*?)(?=^## |\Z)", markdown_structure(text), re.MULTILINE | re.DOTALL
    )
    if match is None:
        return []
    section = text[match.start(): match.end()]
    body = HTML_COMMENT.sub("", text[match.start("body"): match.end("body")])
    label = f"grouping {name} §8 Open Decisions"
    if body.strip() == "None.":
        return []
    header, rows = table_with_header(section, "## 8.")
    if [h.strip().lower() for h in header] != [h.lower() for h in GROUPING_DECISION_HEADERS]:
        raise Refuse(
            f"{label} must be 'None.' or the canonical table "
            f"{' | '.join(GROUPING_DECISION_HEADERS)}; an ad-hoc table cannot be "
            f"carried into the reflection."
        )
    entries: list[tuple[str, str | None]] = []
    for n, cells in enumerate(rows, 1):
        if len(cells) != len(header) or PLACEHOLDER.search(" ".join(cells)):
            raise Refuse(f"{label} row {n} is ragged or still carries a template placeholder.")
        decision_id, resolution = cells[0].strip("`* "), cells[2].strip("`* ")
        if not decision_id:
            raise Refuse(f"{label} row {n} has a blank ID cell.")
        if resolution not in GROUPING_RESOLUTIONS:
            raise Refuse(
                f"{label} row {decision_id} resolution {resolution!r} is not one of "
                f"{', '.join(GROUPING_RESOLUTIONS)}."
            )
        entries.append((decision_id, "grouping"))
    return entries


def decision_sources(paths: list[str], issue: str | None) -> dict[str, tuple[str, str]]:
    """Every decision recorded outside the reflection: ``id -> (stage, source)``.

    A markdown source is classified by its structure (HDP-23, HDP-25): a
    ``## 8. Open Decisions`` heading outside every fence and comment, or being the
    file a plan's frontmatter declares as ``grouping_source``, makes it a session
    grouping whose §8 D-rows are read; a ``plan_source`` frontmatter key or a
    ``handoff`` filename makes it a handoff, read through its ``## Decision Log``
    section the way the structure gate reads it; anything else is a plan whose
    fenced ``yaml`` blocks with a root ``decision_log:`` are read. A file carrying
    signals of two kinds -- a grouping that also declares a ``grouping_source``,
    carries handoff signals or records a ``decision_log:`` -- is refused rather than
    routed by whichever check ran first, and every file is classified before any
    declaration is enforced, so the refusal names the contradiction. A YAML source
    contributes a top-level ``decision_log:`` list, or -- with ``issue`` -- the
    ``enrichment.decision_log`` of that one issue in a known-issues file
    (human-decision-protocol.md §6). A plan that declares a real ``grouping_source``
    binds that one file, resolved from the plan's project root: it must be among the
    sources, or the grouping's decisions would be reconciled against nothing
    (HDP-18, HDP-21) -- and a quoted §8 example in the plan never lifts that
    obligation (HDP-25).
    """
    expected: dict[str, tuple[str, str]] = {}
    texts = [(path, read_text(path, "decision source")) for path in paths]
    declared: list[tuple[str, str]] = []
    for path, text in texts:
        if not path.lower().endswith((".yaml", ".yml")):
            source = declared_grouping_source(text)
            if source is not None:
                declared.append((path, source))
    kinds = {
        path: markdown_source_kind(path, text, declared)
        for path, text in texts
        if not path.lower().endswith((".yaml", ".yml"))
    }
    for plan_path, source in declared:
        if not any(path_matches_declared(path, source, plan_path) for path, _ in texts):
            raise Refuse(
                f"plan {Path(plan_path).name} declares grouping_source {source!r} "
                f"(resolved from the plan's project root as "
                f"{resolve_declared_source(source, plan_path)}); pass that file as a "
                f"--decision-source so its §8 decisions are reconciled, since another "
                f"grouping or none at all cannot stand in for it (HDP-18)."
            )
    issue_read = False
    for path, text in texts:
        name = Path(path).name
        if path.lower().endswith((".yaml", ".yml")):
            if ISSUES_ROOT.search(text) or (issue and ISSUES_NESTED.search(text)):
                if not issue:
                    raise Usage(
                        f"decision source {name} is a known-issues file; pass "
                        f"--decision-issue ID to say whose enrichment.decision_log to read."
                    )
                default_stage, label = "triage", f"issue {issue}"
                entries = issue_decision_log(text, name, issue)
                issue_read = True
            else:
                default_stage, label = "planning", name
                decision_log_keys(text, f"decision source {name}")
                entries = decision_entries(yaml_sequence(text, "decision_log", name, root=True), name)
        elif kinds[path] == "grouping":
            default_stage, label = "grouping", f"grouping {name} §8"
            entries = grouping_decisions(text, name)
        elif kinds[path] == "handoff":
            default_stage, label = "execution", name
            entries = handoff_decisions(text, name)
        else:
            default_stage, label = "planning", name
            entries = fenced_decision_logs(text, name)
        for decision_id, stage in entries:
            stage = stage or default_stage
            previous = expected.get(decision_id)
            if previous and previous[0] != stage:
                raise Refuse(
                    f"decision {decision_id} is recorded as {stage!r} in {label} but "
                    f"{previous[0]!r} in {previous[1]}; one decision has one stage."
                )
            expected.setdefault(decision_id, (stage, label))
    if issue and not issue_read:
        raise Refuse(
            f"--decision-issue {issue} was given but no --decision-source is a known-issues "
            f"file with a root-level issues: sequence, so its enrichment.decision_log was "
            f"not read (HDP-17)."
        )
    return expected


def markdown_source_kind(path: str, text: str, declared: list[tuple[str, str]]) -> str:
    """``grouping`` / ``handoff`` / ``plan`` for one markdown decision source (HDP-23).

    The signals are structural: a ``## 8. Open Decisions`` heading in the file's
    structure (never inside a fence or a comment, HDP-25, HDP-29) or being the file a
    plan declares as ``grouping_source`` says grouping; ``plan_source`` frontmatter
    (a YAML null is no value, HDP-31) or a ``handoff`` filename says handoff; a
    ``grouping_source`` declaration or a ``decision_log:`` key -- in any shape YAML
    can write one, HDP-27 -- says the file is not a grouping. A grouping that also
    carries any of the latter is refused rather than read as an empty grouping
    (HDP-23, HDP-26).
    """
    name = Path(path).name
    grouping_signals = [
        signal for signal, present in (
            ("a ## 8. Open Decisions heading", bool(OPEN_DECISIONS_HEADING.search(markdown_structure(text)))),
            ("being a plan's declared grouping_source", any(
                path_matches_declared(path, source, plan_path)
                for plan_path, source in declared if plan_path != path)),
        ) if present
    ]
    handoff_signals = [
        signal for signal, present in (
            ("plan_source frontmatter", frontmatter_value(text, "plan_source") is not None),
            ("a handoff filename", "handoff" in name.lower()),
        ) if present
    ]
    other_signals = handoff_signals + [
        signal for signal, present in (
            ("a grouping_source declaration", declared_grouping_source(text) is not None),
            ("a decision_log: key", bool(DECISION_LOG_KEY.search(text))),
        ) if present
    ]
    if grouping_signals and other_signals:
        raise Refuse(
            f"decision source {name} is a session grouping by "
            f"{' and '.join(grouping_signals)} but also carries "
            f"{' and '.join(other_signals)}; one file is one kind of source, so it "
            f"cannot be read as either (HDP-23, HDP-26)."
        )
    if grouping_signals:
        return "grouping"
    if handoff_signals:
        return "handoff"
    return "plan"


def frontmatter_value(text: str, key: str) -> str | None:
    """The unquoted scalar of ``key`` in a markdown file's YAML frontmatter, else None.

    A YAML null -- ``key: null`` in any of YAML's spellings, ``key: ~`` or ``key:``
    with nothing after it -- is an absent value, not a present one, so
    ``plan_source: null`` makes a file a handoff exactly as much as no ``plan_source``
    line does: not at all (HDP-31). A quoted ``"null"`` is a string and is present.
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    match = re.search(rf"^{re.escape(key)}:[ \t]*(?P<value>[^\n]*)$", text[4:end], re.MULTILINE)
    if match is None:
        return None
    raw = _strip_inline_comment(match.group("value").strip())
    if raw in YAML_NULLS:
        return None
    return _unquote(raw)


def declared_grouping_source(text: str) -> str | None:
    """A plan's real ``grouping_source``; None when absent, null or still a template slot."""
    value = frontmatter_value(text, "grouping_source")
    if not value or value.lower() == "null" or PLACEHOLDER.search(value):
        return None
    return value


def project_root(plan_path: str) -> Path:
    """The root a plan's relative ``grouping_source`` is resolved from (HDP-21).

    A plan declares ``.agent/context/grouping/{file}.md`` relative to its repository,
    so the root is the nearest ancestor of the plan file that holds a ``.agent``
    directory; a plan with no such ancestor resolves beside itself. The working
    directory never takes part, so the binding cannot move with ``cd``.
    """
    plan = Path(plan_path).resolve()
    for ancestor in plan.parents:
        if (ancestor / ".agent").is_dir():
            return ancestor
    return plan.parent


def resolve_declared_source(declared: str, plan_path: str) -> Path:
    """The one file a plan's ``grouping_source`` names, absolute and normalised."""
    declared_path = Path(declared.strip())
    if not declared_path.is_absolute():
        declared_path = project_root(plan_path) / declared_path
    return declared_path.resolve()


def path_matches_declared(path: str, declared: str, plan_path: str) -> bool:
    """Is ``path`` the very file the plan at ``plan_path`` declares as ``grouping_source``?

    HDP-18 / HDP-21: the declared value names exactly one file -- absolute as
    written, otherwise resolved from the plan's project root -- and the supplied
    path binds only when it is that same file on disk. There is no suffix match: a
    different file that shares the declared trailing path, or its basename, is
    another file, and a declared file that does not exist binds nothing.
    """
    try:
        return os.path.samefile(str(resolve_declared_source(declared, plan_path)), path)
    except OSError:
        return False


def reflection_decision_rows(text: str, path: str) -> dict[str, str]:
    """``id -> stage`` from the reflection's ``### Decisions Log``; ``{}`` for ``None.``.

    The table is the canonical one from REFLECTION-TEMPLATE.md, whole: an ID and a
    Stage alone enumerate a decision without disclosing it, so every cell must be
    filled, the resolution must be ``autonomous`` or ``human``, and an ID appears
    once (HDP-12).
    """
    match = re.search(r"^### Decisions Log\n(?P<body>.*?)(?=^##+ |\Z)", text, re.MULTILINE | re.DOTALL)
    if match is None:
        raise Refuse(
            f"reflection {path} has no '### Decisions Log' section, so the decisions "
            f"recorded elsewhere cannot be reconciled with what the human was shown."
        )
    body = match.group("body")
    prose = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    prose = "\n".join(line for line in prose.splitlines() if line.strip() != "---")
    if prose.strip() == "None.":
        return {}
    header, rows = table_with_header(body, "")
    if [h.strip().lower() for h in header] != [h.lower() for h in DECISIONS_LOG_HEADERS]:
        raise Refuse(
            f"reflection {path} Decisions Log must be 'None.' or the canonical template "
            f"table {' | '.join(DECISIONS_LOG_HEADERS)}."
        )
    recorded: dict[str, str] = {}
    for n, cells in enumerate(rows, 1):
        if len(cells) != len(header) or PLACEHOLDER.search(" ".join(cells)):
            raise Refuse(
                f"reflection {path} Decisions Log row {n} is ragged or still carries a "
                f"template placeholder."
            )
        row = {name: cell.strip("`* ") for name, cell in zip(DECISIONS_LOG_HEADERS, cells)}
        decision_id = row["ID"] or f"#{n}"
        for column, value in row.items():
            if not value:
                raise Refuse(
                    f"reflection {path} Decisions Log row {decision_id} has a blank "
                    f"{column} cell; a row that does not say what was decided, or why, "
                    f"discloses nothing."
                )
        if decision_id in recorded:
            raise Refuse(
                f"reflection {path} Decisions Log row {decision_id} appears twice; one "
                f"decision has one row."
            )
        if row["Stage"] not in DECISION_STAGES:
            raise Refuse(
                f"reflection {path} Decisions Log row {decision_id} names stage "
                f"{row['Stage']!r}; the protocol stages are {', '.join(DECISION_STAGES)}."
            )
        if row["Resolution"] not in DECISION_RESOLUTIONS:
            raise Refuse(
                f"reflection {path} Decisions Log row {decision_id} resolution "
                f"{row['Resolution']!r} is not one of {', '.join(DECISION_RESOLUTIONS)}."
            )
        recorded[decision_id] = row["Stage"]
    return recorded


def check_decisions_log(text: str, path: str, sources: list[str], issue: str | None) -> str:
    """Every decision recorded in a source must have a reflection row (HDP-8).

    The reflection's ``### Decisions Log`` is the only place the human reads the
    decisions the agent did not stop for (human-decision-protocol.md §6). A
    decision that lives in the plan, a handoff, a grouping's §8 or an issue's
    enrichment but not here was made in silence, and ``None.`` is only true when
    no source recorded one.
    """
    expected = decision_sources(sources, issue)
    recorded = reflection_decision_rows(text, path)
    if expected and not recorded:
        listing = ", ".join(f"{d} ({s}, {src})" for d, (s, src) in expected.items())
        raise Refuse(
            f"reflection {path} Decisions Log says None. but {len(expected)} "
            f"decision(s) are recorded elsewhere: {listing}. Autonomy that is not "
            f"disclosed is silence."
        )
    for decision_id, (stage, source) in expected.items():
        if decision_id not in recorded:
            raise Refuse(
                f"reflection {path} Decisions Log is missing decision {decision_id} "
                f"({stage}, recorded in {source})."
            )
        if recorded[decision_id] != stage:
            raise Refuse(
                f"reflection {path} Decisions Log stage mismatch for {decision_id}: the "
                f"row says {recorded[decision_id]!r}, {source} says {stage!r}."
            )
    return (
        f"{len(expected)} recorded decision(s) reconciled against "
        f"{len(recorded)} Decisions Log row(s)"
    )


def check_reflection(
    text: str,
    path: str,
    template_path: str | None,
    schema_path: str | None,
    decision_sources_paths: list[str] | None = None,
    decision_issue: str | None = None,
) -> list[str]:
    notes = []

    # Checked before anything else. Every other arm below passes on a fresh copy of
    # the template -- the headings are all there and the fenced YAML block is
    # complete -- so an unfilled reflection is the one input that would otherwise
    # sail through the whole gate.
    found = [marker for marker in UNFILLED if marker in text]
    if found:
        raise Refuse(
            f"reflection {path} still contains {len(found)} unfilled template "
            f"marker(s): {', '.join(repr(f) for f in found[:4])}"
            + (" ..." if len(found) > 4 else "")
            + ". A copied-but-unfilled reflection satisfies every structural check "
            "here, which is why the markers are checked directly."
        )

    if template_path:
        template = read_text(template_path, "reflection template")
        headings = re.findall(r"^##+ .+$", template, re.MULTILINE)
        # Placeholder headings in the template are prompts, not required sections.
        required = [h for h in headings if not PLACEHOLDER.search(h)]
        absent = [h for h in required if h not in text]
        if absent:
            raise Refuse(
                f"reflection {path} is missing {len(absent)} section(s) present in "
                f"{template_path}: {', '.join(a.strip('# ') for a in absent[:6])}"
                + (" ..." if len(absent) > 6 else "")
            )
        notes.append(f"all {len(required)} template section(s) present")

    if schema_path:
        required = schema_required_fields(read_text(schema_path, "reflection schema"), schema_path)
        # Looked for inside the fenced YAML block, not anywhere in the document. A
        # field name that appears only in the surrounding prose is a mention, not an
        # emission, and the aggregator reads the block.
        fences = YAML_FENCE.findall(text)
        if not fences:
            raise Refuse(
                f"reflection {path} has no fenced ```yaml block. The Instruction "
                f"Coverage section is defined as exactly one such block; without it "
                f"there is nothing for the aggregator to read."
            )
        block = max(fences, key=len)
        absent = [k for k in required if not re.search(rf"^{re.escape(k)}:", block, re.MULTILINE)]
        if absent:
            raise Refuse(
                f"reflection {path} omits {len(absent)} required field(s) from "
                f"{schema_path}: {', '.join(absent[:8])}"
                + (" ..." if len(absent) > 8 else "")
            )
        notes.append(f"all {len(required)} required schema field(s) emitted")

    # Dispositions need a durable home. "Patterns to ADD/DROP" is where a reflection
    # decides something; `## Next Session Design Rules` is the only part of the
    # template that carries a decision into the next session. A reflection that
    # names patterns and writes no rule has produced observations and changed
    # nothing -- and it passes every section check, because the rules heading is
    # present and its body is empty.
    patterns = []
    for heading in ("### Patterns to ADD", "### Patterns to DROP"):
        for cell in re.findall(rf"{re.escape(heading)}\n(.*?)(?=\n#|\Z)", text, re.DOTALL):
            patterns += [
                line for line in cell.splitlines()
                if re.match(r"^\s*\d+\.\s+\S", line) and not PLACEHOLDER.search(line)
            ]
    rules = RULE_LINE.findall(text)
    if patterns and not rules:
        raise Refuse(
            f"reflection {path} names {len(patterns)} pattern(s) to ADD/DROP but "
            f"records no 'RULE-N:' under '## Next Session Design Rules'. A pattern "
            f"with no rule has no durable home: nothing carries it past this "
            f"session, and the observation is lost while the reflection reads as "
            f"complete."
        )
    if rules:
        # Each rule needs its SOURCE line: an unsourced rule is the "uncited best
        # practice" this framework rejects everywhere else (AV-6).
        blocks = re.findall(r"^RULE-\d+:.*?(?=^RULE-\d+:|\Z)", text, re.MULTILINE | re.DOTALL)
        unsourced = [b.splitlines()[0] for b in blocks if not re.search(r"^SOURCE:\s*\S", b, re.MULTILINE)]
        if unsourced:
            raise Refuse(
                f"reflection {path} has {len(unsourced)} design rule(s) with no "
                f"SOURCE line: {'; '.join(u[:60] for u in unsourced[:3])}. An "
                f"uncited rule is the 'best practice' the review checklist rejects "
                f"(AV-6) -- name the signal that produced it."
            )
        notes.append(f"{len(rules)} design rule(s), all sourced")
    else:
        notes.append("no patterns raised, no design rules required")

    # HDP-8: the Decisions Log heading being present says nothing about whether the
    # decisions made in the plan, the handoffs or the closed issue reached it.
    if decision_sources_paths:
        notes.append(check_decisions_log(text, path, decision_sources_paths, decision_issue))
    return notes


# ---------------------------------------------------------------------- dispatch


def run(args: argparse.Namespace) -> list[str]:
    """Dispatch to exactly one check. Returns the OK notes, or raises."""
    selected = [
        bool(args.review),
        bool(args.reflection),
        bool(args.handoff or args.plan),
    ]
    if sum(selected) != 1:
        raise Usage(
            "choose exactly one artifact family per invocation: --handoff/--plan, or "
            "--review, or --reflection. Mixing them in one call makes a single exit "
            "code stand for several independent checks, and the receipt no longer "
            "says which one failed."
        )

    if args.review:
        if args.review_state_only and args.review_state_receipt:
            raise Usage(
                "--review-state-only writes a receipt and --review-state-receipt reads "
                "one; passing both leaves it ambiguous which is authoritative."
            )
        if not args.review_state_only and not args.review_state_receipt:
            raise Usage(
                "--review needs either --review-state-only (parse and write the state "
                "receipt) or --review-state-receipt PATH (decide approval from it)."
            )
        if args.max_review_rounds is None:
            raise Usage("--review requires --max-review-rounds N.")
        if args.max_review_rounds < 1:
            raise Usage("--max-review-rounds must be at least 1.")
        if args.expected_review_mode and args.expected_review_mode not in REVIEW_MODES:
            raise Usage(
                f"--expected-review-mode must be one of {', '.join(REVIEW_MODES)}."
            )
        text = read_text(args.review, "review file")
        if args.review_state_only:
            if not args.output:
                raise Usage(
                    "--review-state-only requires --output PATH: the next stage reads "
                    "approval from that receipt, so there is no useful in-memory-only "
                    "form of this check."
                )
            state, notes = check_review_state(
                text,
                args.review,
                args.expected_review_mode,
                args.expected_target_plan,
                args.max_review_rounds,
            )
            write_state(args.output, state)
            return notes + [f"state receipt written to {args.output}"]
        state = read_state(args.review_state_receipt)
        return check_approved_state(
            text,
            args.review,
            state,
            args.expected_review_mode,
            args.expected_target_plan,
            args.max_review_rounds,
        )

    if (args.decision_source or args.decision_issue) and not args.reflection:
        raise Usage(
            "--decision-source/--decision-issue reconcile recorded decisions against a "
            "reflection's Decisions Log; pass --reflection PATH."
        )

    if args.reflection:
        if not args.reflection_template and not args.reflection_schema:
            raise Usage(
                "--reflection needs --reflection-template and/or --reflection-schema. "
                "With neither, the only thing left to check is that the file is "
                "non-empty, which is not a gate."
            )
        if args.decision_issue and not args.decision_source:
            raise Usage(
                "--decision-issue names whose enrichment.decision_log to read; it needs "
                "a known-issues file passed with --decision-source."
            )
        text = read_text(args.reflection, "reflection")
        return check_reflection(
            text,
            args.reflection,
            args.reflection_template,
            args.reflection_schema,
            args.decision_source,
            args.decision_issue,
        )

    # handoff family
    if args.handoff_structure_only:
        if not args.handoff:
            raise Usage("--handoff-structure-only requires --handoff PATH.")
        if args.plan:
            raise Usage(
                "--handoff-structure-only ignores --plan; drop one so the receipt says "
                "which check ran."
            )
        text = read_text(args.handoff, "handoff")
        return check_handoff_structure(text, args.handoff)

    if not (args.handoff and args.plan):
        raise Usage("this check requires both --handoff PATH and --plan PATH.")
    handoff_text = read_text(args.handoff, "handoff")
    plan_text = read_text(args.plan, "plan")

    if args.ac_coverage_only:
        return check_ac_coverage(handoff_text, args.handoff, plan_text, args.plan)

    notes = check_handoff_structure(handoff_text, args.handoff)
    notes += check_handoff_binding(handoff_text, args.handoff, args.plan)
    notes += check_ac_coverage(handoff_text, args.handoff, plan_text, args.plan)
    notes += check_blocked_rows(handoff_text, args.handoff)
    return notes


# ---------------------------------------------------------------------- selftest

_GOOD_PLAN = """---
date: "2026-09-01"
template_version: "2.1"
---

# Implementation Plan

#### Acceptance Criteria

| AC | Type | Criterion | Source | Negative |
|---|---|---|---|---|
| AC-1 | unit | thing works | Spec | bad input rejected |
| AC-2 | integration | other thing works | Spec | bad input rejected |
"""

_GOOD_HANDOFF = """---
date: "2026-09-01"
project: "demo-thing"
plan_source: "docs/execution/plans/2026-09-01-demo-thing/implementation-plan.md"
template_version: "2.1"
---

# Handoff: 2026-09-01-demo-thing-handoff

## Acceptance Criteria

| AC | Type | Description | Source | Test(s) | Status |
|---|---|---|---|---|---|
| AC-1 | unit | thing works | Spec | test_a.py::test_thing | done |
| AC-2 | integration | other thing works | Spec | test_b.py::test_other | done |

## Decision Log

None.

## Evidence

```json
{"schema_version":"evidence.v1","check_id":"suite","command":"python -m unittest","cwd":".","scope":"unit suite","phase":"targeted","exit_code":0,"result":"pass","tested_state":"fixture-tree","output":"12 tests passed"}
```
"""

_GOOD_REVIEW = """---
date: "2026-09-02"
review_mode: "execution"
target_plan: "docs/execution/plans/2026-09-01-demo-thing/implementation-plan.md"
verdict: "approved"
findings_count: 1
template_version: "2.1"
---

# Critical Review: demo-thing

## Findings

| # | Severity | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|
| 1 | Low | naming nit | a.py:3 | rename | fixed |

## Verdict

`approved` -- behaviour matches the plan.
"""

#: The v2 Findings shape, where ``Blocking`` is its own column instead of being inferred
#: from severity. ``{blocking}`` is filled per arm: an OPEN row that is explicitly
#: non-blocking must not stop an approval, and anything else about an open row must.
_V2_REVIEW_TMPL = (
    _GOOD_REVIEW.replace(
        "| # | Severity | Finding | File:Line | Recommendation | Status |",
        "| # | Severity | Blocking | Finding | File:Line | Recommendation | Status |",
    )
    .replace("|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|")
    .replace(
        "| 1 | Low | naming nit | a.py:3 | rename | fixed |",
        "| 1 | Low | {blocking} | naming nit | a.py:3 | rename | open |",
    )
)

# Shaped like REFLECTION-TEMPLATE.md: the ADD/DROP pattern lists, the design-rules
# block, and the fenced Instruction Coverage YAML.
_GOOD_REFLECTION_TEMPLATE = """# {YYYY-MM-DD} Meta-Reflection

## Execution Trace

### Friction Log

1. **What took longer than expected?**
   _Answer here_

### Decisions Log

| ID | Stage | Question | Resolution | Chosen | Source tag | Reasoning (why this; why the alternatives lost) | Human ref |
|----|-------|----------|------------|--------|------------|--------------------------------------------------|-----------|
| D-1 | planning / plan-review / execution / closeout / triage / grouping | _{one line}_ | autonomous / human | _{option}_ | Local Canon / Research-backed / Human-approved | _{the deciding factor}_ | _{USER_EXPLICIT date + quote, or —}_ |

## Pattern Extraction

### Patterns to KEEP
1. _Practice that worked well_

### Patterns to DROP
1. _Ceremony without payoff_

### Patterns to ADD
1. _Gap that caused problems_

## Next Session Design Rules

```
RULE-1: {description}
SOURCE: {signal}
```

## Instruction Coverage

```yaml
schema: v1
session:
  id: "{conversation-id}"
loaded: {}
note: ""
```
"""

_GOOD_REFLECTION = """# 2026-09-02 Meta-Reflection

## Execution Trace

### Friction Log

1. **What took longer than expected?**
   The AC table reconciliation.

### Decisions Log

None.

## Pattern Extraction

### Patterns to KEEP
1. Writing the negative case beside the positive one.

### Patterns to DROP
1. Restating the plan in the handoff prose.

### Patterns to ADD
1. Check the AC table before claiming coverage.

## Next Session Design Rules

```
RULE-1: reconcile the handoff AC table against the plan before writing Evidence
SOURCE: two rounds lost to a dropped AC in this session
```

## Instruction Coverage

```yaml
schema: v1
session:
  id: abc-123
  task_class: tdd
  outcome: success
loaded:
  workflows: []
note: "nothing fought anything"
review_churn:
  rounds_to_approval: { execution: 1 }
```
"""

_DECISION_PLAN_TAIL = """
## Decision Log

```yaml
decision_log:
  - id: D-1
    stage: planning
    question: "Which store?"
    resolution: autonomous
    class: two-way
    chosen: "SQLite"
    source_tag: Local Canon
    precedents: ["docs/adr/001.md:10 — SQLite is the local store"]
    research: { engine: none, sources: [] }
    reasoning: "precedent converges; two-way door"
```
"""

_DECISION_ROW_D3 = (
    "| D-3 | triage | Scope the fix? | autonomous | New MEU | Local Canon "
    "| grouping ruling; two-way door | — |\n"
)

_DECISIONS_LOG_ROWS = (
    "### Decisions Log\n\n"
    "| ID | Stage | Question | Resolution | Chosen | Source tag "
    "| Reasoning (why this; why the alternatives lost) | Human ref |\n"
    "|----|-------|----------|------------|--------|------------"
    "|--------------------------------------------------|-----------|\n"
    "| D-1 | planning | Which store? | autonomous | SQLite | Local Canon "
    "| docs/adr/001.md:10 precedent; two-way door | — |\n" + _DECISION_ROW_D3
)

_DECISION_KNOWN_ISSUES = """issues:
- id: OTHER-ISSUE
  status: active
  enrichment:
    decision_log:
    - id: D-9
      stage: triage
- id: CORE-DEMO
  status: resolved
  enrichment:
    decided_by: "agent"
    decision_log:
    - id: D-3
      stage: triage
      question: "Scope the fix?"
      resolution: autonomous
      reasoning: "grouping ruling"
"""

# HDP-11: the same two issues with the sequence indented under `issues:` (2 spaces;
# the 4-space variant is derived), the decision items indented under their key, and
# the issue's `id:` written AFTER `status:` -- every shape a YAML author may pick.
_DECISION_KNOWN_ISSUES_INDENTED = """issues:
  - status: active
    id: OTHER-ISSUE
    enrichment:
      decision_log:
        - stage: triage
          id: D-9
  - status: resolved
    id: CORE-DEMO
    enrichment:
      decided_by: "agent"
      decision_log:
        - stage: triage
          id: D-3
          question: "Scope the fix?"
          resolution: autonomous
          reasoning: "grouping ruling"
"""

_DECISION_HANDOFF_ENTRY = """```yaml
decision_log:
  - id: D-2
    stage: execution
    question: "Retry budget?"
    resolution: autonomous
    chosen: "3"
    source_tag: Local Canon
    reasoning: "matches the client default; two-way door"
```
"""

# HDP-13: a session-grouping file whose §8 table carries one decided and one still-open
# D-row; both must reach the consuming session's reflection with stage `grouping`.
_GROUPING_ROW_D8 = (
    "| D-8 | Split S2? | open | — | — | needs the S1 outcome | — |\n"
)
_DECISION_GROUPING = (
    "# Session grouping\n\n## 1. MEU summary\n\n| MEU | slug |\n|---|---|\n| MEU-1 | demo |\n\n"
    "## 8. Open Decisions\n\n"
    "| ID | Question | Resolution | Chosen | Source tag "
    "| Reasoning (why this; why the alternatives lost) | Human ref |\n"
    "|----|----------|------------|--------|------------"
    "|--------------------------------------------------|-----------|\n"
    "| D-7 | One session or two? | autonomous | One | Local Canon "
    "| p15 precedent; two-way door | — |\n" + _GROUPING_ROW_D8 + "\n## 9. Notes\n"
)
_GROUPING_ROWS = (
    "| D-7 | grouping | One session or two? | autonomous | One | Local Canon "
    "| p15 precedent; two-way door | — |\n"
    "| D-8 | grouping | Split S2? | human | No | Human-approved "
    "| ruled after S1 | USER_EXPLICIT 2026-09-02 |\n"
)

# Shaped like reflection.v1.yaml: a top-level scalar, a `fields:` block with names at
# indent 2, an explicit `required: false`, and a nested `required: false` at indent 8
# that must NOT flip its parent to optional.
_GOOD_SCHEMA = """schema: v1

fields:
  session:
    description: "Session metadata"
    required: true
    properties:
      id:
        type: string
  loaded:
    description: "Files loaded"
    required: true
  note:
    description: "One sentence"
    type: string
  slim_candidate:
    description: "Encouraged by the lint gate, never schema-required"
    required: false
    type: array
  review_churn:
    description: "Churn signal"
    properties:
      finding_categories:
        type: object
        required: false
"""


def selftest() -> int:
    """Prove every refusal can fire, and that passing cases still pass.

    The second half is not decoration. A tool that refused every input would
    satisfy all the negative arms below, and the negative arms are the ones easy
    to write -- so the must-OK count is printed with the total, and a run where it
    is zero is a broken selftest however green it looks (V5).
    """
    results: list[tuple[str, str, str]] = []
    tmp = Path(tempfile.mkdtemp(prefix="closeout-selftest-"))

    def w(name: str, text: str) -> str:
        p = tmp / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    # The plan slug comes from the parent directory, so the good plan needs a real one.
    plan_dir = tmp / "docs" / "execution" / "plans" / "2026-09-01-demo-thing"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "implementation-plan.md").write_text(_GOOD_PLAN, encoding="utf-8")
    plan = str(plan_dir / "implementation-plan.md")

    handoff = w("handoff.md", _GOOD_HANDOFF)
    review = w("review.md", _GOOD_REVIEW)
    reflection = w("reflection.md", _GOOD_REFLECTION)
    template = w("REFLECTION-TEMPLATE.md", _GOOD_REFLECTION_TEMPLATE)
    schema = w("reflection.v1.yaml", _GOOD_SCHEMA)

    parser = build_parser()

    def arm(label: str, want: str, argv: list[str], must_say: str | None = None) -> None:
        """One arm. ``must_say`` is not optional decoration.

        A non-zero exit says something refused, not that the clause under test
        refused (V3). Several arms below construct an artifact that would trip two
        or three clauses if the logic were sloppy, and without a substring assertion
        an arm firing the WRONG clause is indistinguishable from a pass. So every
        negative arm names the clause it expects to reject it.
        """
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                code = main(argv, parser=parser)
        except SystemExit as exc:  # argparse's own exits
            code = int(exc.code or 0)
        text = buf.getvalue()
        got = {0: "0/OK", 1: "1/REFUSE", 2: "2/USAGE", 3: "3/FAIL-CLOSED"}.get(code, str(code))
        if got == want and must_say and must_say not in text:
            got = f"{want} but not for the expected reason: {text[:110]!r}"
        results.append((label, want, got))

    # -- must-OK arms ------------------------------------------------------------
    arm("handoff+plan-full-ok", "0/OK", ["--handoff", handoff, "--plan", plan])
    arm("ac-coverage-ok", "0/OK", ["--handoff", handoff, "--plan", plan, "--ac-coverage-only"])
    arm("handoff-structure-only-ok", "0/OK", ["--handoff", handoff, "--handoff-structure-only"])
    state_out = str(tmp / "state.json")
    arm(
        "review-state-ok",
        "0/OK",
        ["--review", review, "--review-state-only", "--expected-review-mode", "execution",
         "--expected-target-plan", plan, "--max-review-rounds", "6", "--output", state_out],
    )
    arm(
        "approved-state-ok",
        "0/OK",
        ["--review", review, "--review-state-receipt", state_out, "--approved-state-only",
         "--expected-review-mode", "execution", "--expected-target-plan", plan,
         "--max-review-rounds", "6"],
    )
    arm(
        "reflection-ok",
        "0/OK",
        ["--reflection", reflection, "--reflection-template", template,
         "--reflection-schema", schema],
    )

    # -- handoff refusals -------------------------------------------------------
    wrong_plan_dir = tmp / "docs" / "execution" / "plans" / "2026-09-01-other-thing"
    wrong_plan_dir.mkdir(parents=True, exist_ok=True)
    (wrong_plan_dir / "implementation-plan.md").write_text(_GOOD_PLAN, encoding="utf-8")
    arm(
        "handoff-bound-to-other-plan-refused",
        "1/REFUSE",
        ["--handoff", handoff, "--plan", str(wrong_plan_dir / "implementation-plan.md")],
        must_say="does not name the plan under review",
    )
    arm(
        "handoff-placeholder-plan-source-refused",
        "1/REFUSE",
        ["--handoff", w("ph.md", _GOOD_HANDOFF.replace(
            'plan_source: "docs/execution/plans/2026-09-01-demo-thing/implementation-plan.md"',
            'plan_source: "docs/execution/plans/{YYYY-MM-DD}-2026-09-01-demo-thing/implementation-plan.md"')),
         "--plan", plan],
        must_say="still a template placeholder",
    )
    arm(
        "handoff-missing-ac-refused",
        "1/REFUSE",
        ["--handoff", w("noac2.md", _GOOD_HANDOFF.replace(
            "| AC-2 | integration | other thing works | Spec | test_b.py::test_other | done |\n", "")),
         "--plan", plan],
        must_say="never appear in handoff",
    )
    arm(
        "handoff-no-frontmatter-refused",
        "1/REFUSE",
        ["--handoff", w("nofm.md", _GOOD_HANDOFF.split("---\n", 2)[2]), "--plan", plan],
        must_say="no YAML frontmatter",
    )
    arm(
        "handoff-missing-section-refused",
        "1/REFUSE",
        ["--handoff", w("nosec.md", _GOOD_HANDOFF.replace("## Evidence", "## Notes")),
         "--plan", plan],
        must_say="missing required section",
    )
    arm(
        "handoff-empty-ac-table-refused",
        "1/REFUSE",
        ["--handoff", w("emptyac.md", re.sub(
            r"\| AC-\d.*\n", "", _GOOD_HANDOFF).replace(
            "| AC | Type | Description | Source | Test(s) | Status |\n|---|---|---|---|---|---|\n", "")),
         "--plan", plan],
        must_say="no table rows under it",
    )
    arm(
        "blocked-row-without-followup-refused",
        "1/REFUSE",
        ["--handoff", w("blocked.md", _GOOD_HANDOFF.replace(
            "| AC-2 | integration | other thing works | Spec | test_b.py::test_other | done |",
            "| AC-2 | integration | other thing works | Spec | test_b.py::test_other | [B] no time |")),
         "--plan", plan],
        must_say="no linked follow-up",
    )
    arm(
        "blocked-row-with-followup-ok",
        "0/OK",
        ["--handoff", w("blocked_ok.md", _GOOD_HANDOFF.replace(
            "| AC-2 | integration | other thing works | Spec | test_b.py::test_other | done |",
            "| AC-2 | integration | other thing works | Spec | test_b.py::test_other | [B] B-AC-2; follow-up [decision](https://example.org/issues/42) |")
            + "\n### B-AC-2\nReason: human-decision\nDecision: [pending decision](https://example.org/issues/42)\n"),
         "--plan", plan],
    )
    # In a properly-slugged directory on purpose: a plan at an unslugged path raises
    # USAGE from plan_slug, and this arm is about the empty-AC-set clause. An arm that
    # trips a different clause than the one it names is not evidence for that clause (V3).
    noac_dir = tmp / "docs" / "execution" / "plans" / "2026-09-01-demo-thing-noac"
    noac_dir.mkdir(parents=True, exist_ok=True)
    (noac_dir / "implementation-plan.md").write_text(
        '---\ndate: "2026-09-01"\n---\n\n# Plan with no criteria\n', encoding="utf-8"
    )
    arm(
        "plan-with-no-acs-refused",
        "1/REFUSE",
        ["--handoff", w("noac_handoff.md", _GOOD_HANDOFF.replace(
            "2026-09-01-demo-thing/implementation-plan.md",
            "2026-09-01-demo-thing-noac/implementation-plan.md")),
         "--plan", str(noac_dir / "implementation-plan.md")],
        must_say="declares no AC-N identifiers",
    )
    arm(
        "unslugged-plan-path-is-usage",
        "2/USAGE",
        ["--handoff", handoff, "--plan", w("loose-plan.md", _GOOD_PLAN)],
        must_say="cannot derive a plan slug",
    )

    # -- review refusals --------------------------------------------------------
    arm(
        "review-wrong-mode-refused",
        "1/REFUSE",
        ["--review", review, "--review-state-only", "--expected-review-mode", "plan",
         "--expected-target-plan", plan, "--max-review-rounds", "6", "--output", str(tmp / "s2.json")],
        must_say="expected 'plan'",
    )
    arm(
        "review-wrong-target-refused",
        "1/REFUSE",
        ["--review", review, "--review-state-only",
         "--expected-target-plan", str(wrong_plan_dir / "implementation-plan.md"),
         "--max-review-rounds", "6", "--output", str(tmp / "s3.json")],
        must_say="which does not name",
    )
    arm(
        "review-unknown-mode-refused",
        "1/REFUSE",
        ["--review", w("badmode.md", _GOOD_REVIEW.replace('review_mode: "execution"', 'review_mode: "vibes"')),
         "--review-state-only", "--max-review-rounds", "6", "--output", str(tmp / "s4.json")],
        must_say="is not one of",
    )
    over_cap = _GOOD_REVIEW + "\n## Recheck (2026-09-03)\n\n### Verdict\n\n`approved`\n"
    arm(
        "review-over-round-cap-refused",
        "1/REFUSE",
        ["--review", w("overcap.md", over_cap), "--review-state-only",
         "--max-review-rounds", "1", "--output", str(tmp / "s5.json")],
        must_say="over the cap of 1",
    )
    arm(
        "review-under-cap-ok",
        "0/OK",
        ["--review", w("undercap.md", over_cap), "--review-state-only",
         "--max-review-rounds", "6", "--output", str(tmp / "s6.json")],
    )

    # -- approval refusals ------------------------------------------------------
    pending_state = str(tmp / "pending.json")
    pending_review = w("pending.md", _GOOD_REVIEW.replace('verdict: "approved"', 'verdict: "pending"'))
    arm(
        "pending-state-write-ok",
        "0/OK",
        ["--review", pending_review, "--review-state-only", "--max-review-rounds", "6",
         "--output", pending_state],
    )
    arm(
        "pending-not-approval-refused",
        "1/REFUSE",
        ["--review", pending_review, "--review-state-receipt", pending_state,
         "--approved-state-only", "--max-review-rounds", "6"],
        must_say="not 'approved'",
    )
    open_state = str(tmp / "open.json")
    open_review = w("open.md", _GOOD_REVIEW.replace("| rename | fixed |", "| rename | open |"))
    arm(
        "open-findings-state-write-ok",
        "0/OK",
        ["--review", open_review, "--review-state-only", "--max-review-rounds", "6",
         "--output", open_state],
    )
    arm(
        "approved-with-open-findings-refused",
        "1/REFUSE",
        ["--review", open_review, "--review-state-receipt", open_state,
         "--approved-state-only", "--max-review-rounds", "6"],
        must_say="not marked non-blocking",
    )
    # -- v2's blocking/severity split -------------------------------------------
    # An approval may carry an OPEN non-blocking finding (that is the whole point of
    # separating the axes), and must not carry a blocking one. Both directions are
    # asserted: a check that refused every open row would silently restore v1 and push
    # reviewers back into hiding observations in prose.
    for label, blocking, expect, says in (
        ("nonblocking", "no", "0/OK", None),
        ("blocking", "yes", "1/REFUSE", "not marked non-blocking"),
        # A Blocking column whose cell was never filled in. Unknown is not "no": the
        # ambiguous row refuses the approval instead of being waved through.
        # The pipe is escaped because that is how the template writes it and how a
        # reviewer copying the template will leave it. An unescaped one is a ragged row
        # and has its own arm below.
        ("unfilled-blocking-cell", r"{yes\|no}", "1/REFUSE", "not marked non-blocking"),
    ):
        v2_review = w(f"v2-{label}.md", _V2_REVIEW_TMPL.replace("{blocking}", blocking))
        v2_state = str(tmp / f"v2-{label}.json")
        arm(
            f"v2-{label}-state-write-ok",
            "0/OK",
            ["--review", v2_review, "--review-state-only", "--max-review-rounds", "6",
             "--output", v2_state],
        )
        arm(
            f"approved-with-open-{label}-finding",
            expect,
            ["--review", v2_review, "--review-state-receipt", v2_state,
             "--approved-state-only", "--max-review-rounds", "6"],
            must_say=says,
        )
    # -- the Status column is found by name, not by position ---------------------
    # The reason this matters is the direction it fails in. `open_findings` used to be
    # read from the last two cells of each row, so appending one column -- Owner,
    # Round, Verified-by, all things reviewers add -- pushed Status out of range, every
    # row read as not-open, and an `approved` verdict over an open blocking finding
    # passed the gate. Nobody re-verifies a gate after adding a table column.
    _open_blocking = _V2_REVIEW_TMPL.replace("{blocking}", "yes")
    shifted = _open_blocking.replace(
        "| # | Severity | Blocking | Finding | File:Line | Recommendation | Status |",
        "| # | Severity | Blocking | Finding | File:Line | Recommendation | Status | Owner | Round |",
    ).replace(
        "|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|---|"
    ).replace(
        "| 1 | Low | yes | naming nit | a.py:3 | rename | open |",
        "| 1 | Low | yes | naming nit | a.py:3 | rename | open | reviewer-a | 1 |",
    )
    shifted_review = w("shifted.md", shifted)
    shifted_state = str(tmp / "shifted.json")
    arm(
        "status-not-last-column-state-write-ok",
        "0/OK",
        ["--review", shifted_review, "--review-state-only", "--max-review-rounds", "6",
         "--output", shifted_state],
    )
    arm(
        "approved-with-status-not-last-column-refused",
        "1/REFUSE",
        ["--review", shifted_review, "--review-state-receipt", shifted_state,
         "--approved-state-only", "--max-review-rounds", "6"],
        must_say="not marked non-blocking",
    )
    # The other direction, and the reason "scan the whole row" is not the fix either:
    # a Recommendation of "open a follow-up issue" must not make a fixed row open. This
    # arm is must-OK, so a checker that counts any occurrence of the word fails it.
    recommendation_open = _GOOD_REVIEW.replace(
        "| 1 | Low | naming nit | a.py:3 | rename | fixed |",
        "| 1 | Low | naming nit | a.py:3 | open a follow-up issue | fixed |",
    )
    ro_review = w("rec-open.md", recommendation_open)
    ro_state = str(tmp / "rec-open.json")
    arm(
        "recommendation-saying-open-state-write-ok",
        "0/OK",
        ["--review", ro_review, "--review-state-only", "--max-review-rounds", "6",
         "--output", ro_state],
    )
    arm(
        "approved-over-fixed-row-with-open-in-recommendation-ok",
        "0/OK",
        ["--review", ro_review, "--review-state-receipt", ro_state,
         "--approved-state-only", "--max-review-rounds", "6"],
    )
    # No Status column at all: the state of no row can be determined, so there is
    # nothing to approve over. Refused rather than defaulted to zero open findings.
    arm(
        "findings-table-without-status-column-refused",
        "1/REFUSE",
        ["--review", w("nostatus.md", _GOOD_REVIEW.replace(
            "| # | Severity | Finding | File:Line | Recommendation | Status |",
            "| # | Severity | Finding | File:Line | Recommendation |",
        ).replace(
            "|---|---|---|---|---|---|", "|---|---|---|---|---|"
        ).replace(
            "| 1 | Low | naming nit | a.py:3 | rename | fixed |",
            "| 1 | Low | naming nit | a.py:3 | rename |",
        )),
         "--review-state-only", "--max-review-rounds", "6",
         "--output", str(tmp / "nostatus.json")],
        must_say="no 'Status' column",
    )
    # A raw pipe inside a cell. Positional lookup on a ragged row is meaningless, and
    # the shift lands on Recommendation -- which reads as a closed row.
    arm(
        "ragged-findings-row-refused",
        "1/REFUSE",
        ["--review", w("ragged.md", _V2_REVIEW_TMPL.replace("{blocking}", "{yes|no}")),
         "--review-state-only", "--max-review-rounds", "6",
         "--output", str(tmp / "ragged.json")],
        must_say="unescaped pipe",
    )

    # The laundering path: edit the review after the receipt was written.
    edited = w("edited.md", _GOOD_REVIEW + "\n<!-- changed after the state check -->\n")
    edited_state = str(tmp / "edited.json")
    arm(
        "edited-state-write-ok",
        "0/OK",
        ["--review", edited, "--review-state-only", "--max-review-rounds", "6",
         "--output", edited_state],
    )
    Path(edited).write_text(_GOOD_REVIEW + "\n<!-- edited again -->\n", encoding="utf-8")
    arm(
        "stale-receipt-digest-refused",
        "1/REFUSE",
        ["--review", edited, "--review-state-receipt", edited_state, "--approved-state-only",
         "--max-review-rounds", "6"],
        must_say="written from a different version",
    )

    # -- reflection refusals ----------------------------------------------------
    arm(
        "reflection-missing-section-refused",
        "1/REFUSE",
        ["--reflection", w("norefl.md", _GOOD_REFLECTION.replace("## Pattern Extraction", "## Notes")),
         "--reflection-template", template],
        must_say="missing 1 section",
    )
    arm(
        "reflection-missing-schema-field-refused",
        "1/REFUSE",
        ["--reflection", w("nofield.md", _GOOD_REFLECTION.replace(
            'note: "nothing fought anything"\n', "")),
         "--reflection-schema", schema],
        must_say="omits 1 required field",
    )
    # The other half of honouring `required: false`. Without this arm, a checker that
    # demanded every schema field would look identical to a correct one, and it would
    # contradict the schema's own "NEVER schema-required" note on slim_candidate.
    arm(
        "optional-schema-field-absent-ok",
        "0/OK",
        ["--reflection", reflection, "--reflection-schema", schema],
    )
    arm(
        "reflection-unfilled-template-refused",
        "1/REFUSE",
        ["--reflection", w("unfilled.md", _GOOD_REFLECTION_TEMPLATE),
         "--reflection-template", template, "--reflection-schema", schema],
        must_say="unfilled template marker",
    )
    arm(
        "reflection-no-yaml-fence-refused",
        "1/REFUSE",
        ["--reflection", w("nofence.md", _GOOD_REFLECTION.split("```yaml")[0]),
         "--reflection-schema", schema],
        must_say="no fenced ```yaml block",
    )
    arm(
        "patterns-without-design-rule-refused",
        "1/REFUSE",
        ["--reflection", w("norule.md", re.sub(
            r"```\nRULE-1:.*?```\n", "", _GOOD_REFLECTION, flags=re.DOTALL)),
         "--reflection-schema", schema],
        must_say="records no 'RULE-N:'",
    )
    arm(
        "unsourced-design-rule-refused",
        "1/REFUSE",
        ["--reflection", w("nosource.md", _GOOD_REFLECTION.replace(
            "SOURCE: two rounds lost to a dropped AC in this session\n", "")),
         "--reflection-schema", schema],
        must_say="with no SOURCE line",
    )
    arm(
        "schema-without-fields-block-fails-closed",
        "3/FAIL-CLOSED",
        ["--reflection", reflection,
         "--reflection-schema", w("nofields.yaml", "# just a comment\nversion: 1\n")],
        must_say="no top-level 'fields:' block",
    )

    # -- fail-closed arms -------------------------------------------------------
    arm(
        "absent-handoff-fails-closed",
        "3/FAIL-CLOSED",
        ["--handoff", str(tmp / "nope.md"), "--plan", plan],
        must_say="not found",
    )
    arm(
        "absent-receipt-fails-closed",
        "3/FAIL-CLOSED",
        ["--review", review, "--review-state-receipt", str(tmp / "nope.json"),
         "--approved-state-only", "--max-review-rounds", "6"],
        must_say="not found",
    )
    arm(
        "receipt-missing-key-fails-closed",
        "3/FAIL-CLOSED",
        ["--review", review, "--review-state-receipt",
         w("short.json", json.dumps({"schema_version": SCHEMA_VERSION})),
         "--approved-state-only", "--max-review-rounds", "6"],
        must_say="is missing",
    )
    arm(
        "receipt-wrong-schema-fails-closed",
        "3/FAIL-CLOSED",
        ["--review", review, "--review-state-receipt",
         w("oldver.json", json.dumps({k: "x" for k in STATE_KEYS})),
         "--approved-state-only", "--max-review-rounds", "6"],
        must_say="this tool writes",
    )
    arm(
        "empty-handoff-refused",
        "1/REFUSE",
        ["--handoff", w("empty.md", "   \n"), "--plan", plan],
        must_say="is empty",
    )

    # -- usage arms -------------------------------------------------------------
    arm("no-artifact-is-usage", "2/USAGE", [], must_say="exactly one artifact family")
    arm(
        "mixed-families-is-usage",
        "2/USAGE",
        ["--handoff", handoff, "--reflection", reflection],
        must_say="exactly one artifact family",
    )
    arm(
        "review-without-stage-is-usage",
        "2/USAGE",
        ["--review", review, "--max-review-rounds", "6"],
        must_say="either --review-state-only",
    )
    arm(
        "review-both-stages-is-usage",
        "2/USAGE",
        ["--review", review, "--review-state-only", "--review-state-receipt", state_out,
         "--max-review-rounds", "6"],
        must_say="which is authoritative",
    )
    arm(
        "state-only-without-output-is-usage",
        "2/USAGE",
        ["--review", review, "--review-state-only", "--max-review-rounds", "6"],
        must_say="requires --output",
    )
    arm(
        "review-without-cap-is-usage",
        "2/USAGE",
        ["--review", review, "--review-state-only", "--output", str(tmp / "s7.json")],
        must_say="--max-review-rounds",
    )
    arm(
        "reflection-without-reference-is-usage",
        "2/USAGE",
        ["--reflection", reflection],
        must_say="needs --reflection-template",
    )

    # -- decisions-log reconciliation (HDP-8) -----------------------------------
    decided_plan = w("decided-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL)
    decided_reflection = w(
        "decided-reflection.md",
        _GOOD_REFLECTION.replace("### Decisions Log\n\nNone.\n", _DECISIONS_LOG_ROWS),
    )
    known_issues = w("known-issues.yaml", _DECISION_KNOWN_ISSUES)
    arm(
        "decision-source-reconciled-ok",
        "0/OK",
        ["--reflection", decided_reflection, "--reflection-template", template,
         "--decision-source", decided_plan],
    )
    arm(
        "decision-issue-source-reconciled-ok",
        "0/OK",
        ["--reflection", decided_reflection, "--reflection-template", template,
         "--decision-source", decided_plan, "--decision-source", known_issues,
         "--decision-issue", "CORE-DEMO"],
    )
    arm(
        "decision-source-without-decisions-ok",
        "0/OK",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", plan],
    )
    arm(
        "decision-missing-from-reflection-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", decided_plan],
        must_say="Decisions Log says None. but 1 decision(s)",
    )
    arm(
        "decision-issue-missing-from-reflection-refused",
        "1/REFUSE",
        ["--reflection", w("plan-only.md", _GOOD_REFLECTION.replace(
            "### Decisions Log\n\nNone.\n",
            _DECISIONS_LOG_ROWS.replace(_DECISION_ROW_D3, ""))),
         "--reflection-template", template,
         "--decision-source", decided_plan, "--decision-source", known_issues,
         "--decision-issue", "CORE-DEMO"],
        must_say="missing decision D-3 (triage",
    )
    arm(
        "decision-stage-mismatch-refused",
        "1/REFUSE",
        ["--reflection", w("wrong-stage.md", _GOOD_REFLECTION.replace(
            "### Decisions Log\n\nNone.\n",
            _DECISIONS_LOG_ROWS.replace("| D-1 | planning |", "| D-1 | execution |"))),
         "--reflection-template", template, "--decision-source", decided_plan],
        must_say="stage mismatch for D-1",
    )
    arm(
        "decision-placeholder-entry-refused",
        "1/REFUSE",
        ["--reflection", decided_reflection, "--reflection-template", template,
         "--decision-source", w("unfilled-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             'question: "Which store?"', 'question: "{one line}"'))],
        must_say="still carries a template placeholder",
    )
    arm(
        "decision-issue-without-source-is-usage",
        "2/USAGE",
        ["--reflection", decided_reflection, "--reflection-template", template,
         "--decision-issue", "CORE-DEMO"],
        must_say="--decision-issue",
    )
    arm(
        "decision-source-without-reflection-is-usage",
        "2/USAGE",
        ["--handoff", handoff, "--plan", plan, "--decision-source", decided_plan],
        must_say="pass --reflection",
    )
    arm(
        "decision-source-missing-fails-closed",
        "3/FAIL-CLOSED",
        ["--reflection", decided_reflection, "--reflection-template", template,
         "--decision-source", str(tmp / "absent-plan.md")],
        must_say="decision source not found",
    )

    # -- HDP-10: a Decision Log is None. or one ```yaml fence, nowhere else ---------
    handoff_none = "## Decision Log\n\nNone.\n"
    arm(
        "handoff-decision-log-missing-refused",
        "1/REFUSE",
        ["--handoff", w("nodl.md", _GOOD_HANDOFF.replace(handoff_none, "")),
         "--handoff-structure-only"],
        must_say="## Decision Log",
    )
    arm(
        "handoff-decision-log-prose-refused",
        "1/REFUSE",
        ["--handoff", w("prosedl.md", _GOOD_HANDOFF.replace(
            handoff_none, "## Decision Log\n\nNo decisions were made.\n")),
         "--handoff-structure-only"],
        must_say="exactly 'None.'",
    )
    arm(
        "handoff-decision-log-text-fence-refused",
        "1/REFUSE",
        ["--handoff", w("textdl.md", _GOOD_HANDOFF.replace(
            handoff_none, "## Decision Log\n\n" + _DECISION_HANDOFF_ENTRY.replace(
                "```yaml", "```text"))),
         "--handoff-structure-only"],
        must_say="```yaml",
    )
    arm(
        "handoff-decision-log-empty-list-refused",
        "1/REFUSE",
        ["--handoff", w("emptydl.md", _GOOD_HANDOFF.replace(
            handoff_none, "## Decision Log\n\n```yaml\ndecision_log: []\n```\n")),
         "--handoff-structure-only"],
        must_say="spelled None.",
    )
    arm(
        "handoff-decision-log-entries-ok",
        "0/OK",
        ["--handoff", w("dl.md", _GOOD_HANDOFF.replace(
            handoff_none,
            "## Decision Log\n\n<!-- kept from the template -->\n\n" + _DECISION_HANDOFF_ENTRY)),
         "--handoff-structure-only"],
    )
    arm(
        "decision-text-fence-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("textfence-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "```yaml", "```text"))],
        must_say="```yaml",
    )
    arm(
        "decision-bare-key-outside-fence-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("bare-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "```yaml\n", "").replace("```\n", ""))],
        must_say="outside any fence",
    )

    # -- HDP-11: issue sequences at any indent, mapping keys in any order ------------
    indented_issues = w("known-issues-indented.yaml", _DECISION_KNOWN_ISSUES_INDENTED)
    arm(
        "decision-issue-indented-sequence-ok",
        "0/OK",
        ["--reflection", decided_reflection, "--reflection-template", template,
         "--decision-source", decided_plan, "--decision-source", indented_issues,
         "--decision-issue", "CORE-DEMO"],
    )
    arm(
        "decision-issue-indented-4-missing-refused",
        "1/REFUSE",
        ["--reflection", w("plan-only-4.md", _GOOD_REFLECTION.replace(
            "### Decisions Log\n\nNone.\n",
            _DECISIONS_LOG_ROWS.replace(_DECISION_ROW_D3, ""))),
         "--reflection-template", template,
         "--decision-source", decided_plan,
         "--decision-source", w("known-issues-4.yaml", "\n".join(
             ("  " + line if line.strip() else line)
             for line in _DECISION_KNOWN_ISSUES_INDENTED.splitlines()).replace(
             "  issues:", "issues:", 1) + "\n"),
         "--decision-issue", "CORE-DEMO"],
        must_say="missing decision D-3 (triage",
    )
    arm(
        "decision-stage-before-id-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("stage-first-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "  - id: D-1\n    stage: planning\n", "  - stage: planning\n    id: D-1\n"))],
        must_say="Decisions Log says None. but 1 decision(s)",
    )
    arm(
        "decision-item-without-id-refused",
        "1/REFUSE",
        ["--reflection", decided_reflection, "--reflection-template", template,
         "--decision-source", w("noid-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "  - id: D-1\n    stage: planning\n", "  - stage: planning\n"))],
        must_say="has no id",
    )
    arm(
        "decision-empty-key-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("emptykey-plan.md", _GOOD_PLAN
                                + "\n## Decision Log\n\n```yaml\ndecision_log:\n```\n")],
        must_say="no items",
    )
    arm(
        "decision-issue-absent-refused",
        "1/REFUSE",
        ["--reflection", decided_reflection, "--reflection-template", template,
         "--decision-source", decided_plan, "--decision-source", known_issues,
         "--decision-issue", "NOPE-1"],
        must_say="has no issue NOPE-1",
    )

    # -- HDP-12: a Decisions Log row must disclose, not just enumerate ---------------
    def rows_reflection(name: str, rows: str) -> str:
        return w(name, _GOOD_REFLECTION.replace("### Decisions Log\n\nNone.\n", rows))

    arm(
        "decision-two-column-table-refused",
        "1/REFUSE",
        ["--reflection", rows_reflection(
            "two-col.md",
            "### Decisions Log\n\n| ID | Stage |\n|----|-------|\n| D-1 | planning |\n"),
         "--reflection-template", template, "--decision-source", decided_plan],
        must_say="canonical",
    )
    arm(
        "decision-blank-reasoning-refused",
        "1/REFUSE",
        ["--reflection", rows_reflection("blank-reason.md", _DECISIONS_LOG_ROWS.replace(
            "| docs/adr/001.md:10 precedent; two-way door |", "|  |")),
         "--reflection-template", template, "--decision-source", decided_plan],
        must_say="blank",
    )
    arm(
        "decision-invalid-resolution-refused",
        "1/REFUSE",
        ["--reflection", rows_reflection("bad-res.md", _DECISIONS_LOG_ROWS.replace(
            "| Which store? | autonomous |", "| Which store? | maybe |")),
         "--reflection-template", template, "--decision-source", decided_plan],
        must_say="resolution",
    )
    arm(
        "decision-duplicate-id-refused",
        "1/REFUSE",
        ["--reflection", rows_reflection("dup.md", _DECISIONS_LOG_ROWS.replace(
            _DECISION_ROW_D3, _DECISION_ROW_D3.replace("| D-3 |", "| D-1 |"))),
         "--reflection-template", template, "--decision-source", decided_plan],
        must_say="twice",
    )

    # -- HDP-13: grouping §8 D-rows are carried into the consuming session ----------
    grouping = w("demo-session-grouping.md", _DECISION_GROUPING)
    arm(
        "grouping-source-reconciled-ok",
        "0/OK",
        ["--reflection", rows_reflection("grouped.md", _DECISIONS_LOG_ROWS + _GROUPING_ROWS),
         "--reflection-template", template,
         "--decision-source", decided_plan, "--decision-source", grouping],
    )
    arm(
        "grouping-decision-missing-refused",
        "1/REFUSE",
        ["--reflection", decided_reflection, "--reflection-template", template,
         "--decision-source", decided_plan, "--decision-source", grouping],
        must_say="missing decision D-7 (grouping",
    )
    arm(
        "grouping-table-wrong-shape-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("adhoc-session-grouping.md", _DECISION_GROUPING.split(
             "## 8. Open Decisions")[0] + "## 8. Open Decisions\n\n| # | Question | Resolution |\n"
             "|---|---|---|\n| 1 | Split? | **Decided** — no |\n\n## 9. Notes\n")],
        must_say="canonical",
    )
    arm(
        "grouping-none-ok",
        "0/OK",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", plan,
         "--decision-source", w("none-session-grouping.md", _DECISION_GROUPING.split(
             "## 8. Open Decisions")[0] + "## 8. Open Decisions\n\nNone.\n\n## 9. Notes\n")],
    )


    # -- HDP-15: indentation must not hide a recorded decision -------------------
    def indented(text: str, *, fence_too: bool) -> str:
        return "\n".join(
            "  " + line if line and (fence_too or not line.startswith("```")) else line
            for line in text.splitlines()
        ) + "\n"

    d1_reflection = rows_reflection(
        "d1-only.md", _DECISIONS_LOG_ROWS.replace(_DECISION_ROW_D3, ""))
    arm(
        "decision-indented-fence-reconciled",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("indented-fence-plan.md",
                                _GOOD_PLAN + indented(_DECISION_PLAN_TAIL, fence_too=True))],
        must_say="says None. but 1 decision",
    )
    arm(
        "decision-indented-root-reconciled",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("indented-root-plan.md",
                                _GOOD_PLAN + indented(_DECISION_PLAN_TAIL, fence_too=False))],
        must_say="says None. but 1 decision",
    )
    arm(
        "decision-indented-fence-ok",
        "0/OK",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("indented-fence-plan.md",
                                _GOOD_PLAN + indented(_DECISION_PLAN_TAIL, fence_too=True))],
    )
    arm(
        "decision-diff-excerpt-ignored-ok",
        "0/OK",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("diff-plan.md", _GOOD_PLAN
                                + "\n## Notes\n\n```diff\n+decision_log:\n+  - id: D-Q\n```\n")],
    )
    arm(
        "decision-indented-outside-fence-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("indented-bare-plan.md", _GOOD_PLAN
                                + "\n## Decision Log\n\n  decision_log:\n    - id: D-1\n")],
        must_say="outside any fence",
    )
    indented_root_handoff = w("indented-root-handoff.md", _GOOD_HANDOFF.replace(
        "## Decision Log\n\nNone.", "## Decision Log\n\n"
        + indented(_DECISION_HANDOFF_ENTRY, fence_too=False)))
    arm(
        "handoff-indented-root-structure-ok",
        "0/OK",
        ["--handoff", indented_root_handoff, "--handoff-structure-only"],
        must_say="1 decision(s) logged",
    )
    arm(
        "handoff-indented-root-reconciled",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", indented_root_handoff],
        must_say="says None. but 1 decision",
    )

    # -- HDP-16: the shipped handoff template must validate once filled in --------
    template_shape = (
        "## Decision Log\n\n<!-- instruction comment -->\n\n{body}\n---\n")
    arm(
        "handoff-template-separator-none-ok",
        "0/OK",
        ["--handoff", w("sep-none-handoff.md", _GOOD_HANDOFF.replace(
            "## Decision Log\n\nNone.\n", template_shape.format(body="None.\n"))),
         "--handoff-structure-only"],
        must_say="0 decision(s) logged",
    )
    arm(
        "handoff-template-separator-block-ok",
        "0/OK",
        ["--handoff", w("sep-block-handoff.md", _GOOD_HANDOFF.replace(
            "## Decision Log\n\nNone.\n", template_shape.format(body=_DECISION_HANDOFF_ENTRY))),
         "--handoff-structure-only"],
        must_say="1 decision(s) logged",
    )
    arm(
        "handoff-separator-then-prose-refused",
        "1/REFUSE",
        ["--handoff", w("sep-prose-handoff.md", _GOOD_HANDOFF.replace(
            "## Decision Log\n\nNone.\n", template_shape.format(body="None.\n\nI chose SQLite.\n"))),
         "--handoff-structure-only"],
        must_say="exactly 'None.' or one fenced",
    )
    shipped_handoff_template = Path(__file__).resolve().parents[1] / "templates" / "HANDOFF-TEMPLATE.md"
    if shipped_handoff_template.is_file():
        shipped = shipped_handoff_template.read_text(encoding="utf-8")
        shipped_match = re.search(
            r"^## Decision Log\n(?P<body>.*?)(?=^## |\Z)", shipped, re.MULTILINE | re.DOTALL)
        shipped_body = shipped_match.group("body") if shipped_match else ""
        for label, filled, want, must in [
            ("shipped-handoff-template-none-ok",
             re.sub(r"```yaml.*?```\n", "None.\n", shipped_body, count=1, flags=re.DOTALL),
             "0/OK", "0 decision(s) logged"),
            ("shipped-handoff-template-block-ok",
             re.sub(r"```yaml.*?```\n", _DECISION_HANDOFF_ENTRY, shipped_body, count=1,
                    flags=re.DOTALL),
             "0/OK", "1 decision(s) logged"),
            ("shipped-handoff-template-unfilled-refused", shipped_body, "1/REFUSE", "placeholder"),
        ]:
            arm(
                label, want,
                ["--handoff", w(label + ".md", _GOOD_HANDOFF.replace(
                    "## Decision Log\n\nNone.\n", "## Decision Log\n" + filled)),
                 "--handoff-structure-only"],
                must_say=must,
            )
    else:
        results.append(("shipped-handoff-template-present", "0/OK", "template file missing"))

    # -- HDP-17: valid YAML comments and unsupported roots in known-issues ----------
    arm(
        "issues-inline-comment-read",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", decided_plan,
         "--decision-source", w("commented-issues.yaml", _DECISION_KNOWN_ISSUES.replace(
             "issues:", "issues: # current issues", 1)),
         "--decision-issue", "CORE-DEMO"],
        must_say="missing decision D-3 (triage",
    )
    arm(
        "enrichment-inline-comment-read",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", decided_plan,
         "--decision-source", w("commented-enrichment.yaml", _DECISION_KNOWN_ISSUES.replace(
             "  enrichment:", "  enrichment: # facts")),
         "--decision-issue", "CORE-DEMO"],
        must_say="missing decision D-3 (triage",
    )
    arm(
        "decision-log-inline-comment-read",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", decided_plan,
         "--decision-source", w("commented-log.yaml", _DECISION_KNOWN_ISSUES.replace(
             "    decision_log:", "    decision_log: # rulings")),
         "--decision-issue", "CORE-DEMO"],
        must_say="missing decision D-3 (triage",
    )
    arm(
        "issues-nested-root-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("nested-issues.yaml", "container:\n" + "".join(
             "  " + line + "\n" for line in _DECISION_KNOWN_ISSUES.splitlines())),
         "--decision-issue", "CORE-DEMO"],
        must_say="root-level issues:",
    )

    # -- HDP-18: the grouping is the one the plan declares, whatever its filename ---
    unnamed_grouping = w("sessions.md", _DECISION_GROUPING)
    arm(
        "grouping-any-filename-read",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", plan, "--decision-source", unnamed_grouping],
        must_say="D-7 (grouping",
    )
    declared_plan = w("declared-plan.md", _GOOD_PLAN.replace(
        'date: "2026-09-01"\n', 'date: "2026-09-01"\ngrouping_source: "'
        + Path(grouping).as_posix() + '"\n', 1))
    arm(
        "grouping-declared-supplied-ok",
        "0/OK",
        ["--reflection", rows_reflection("grouped-2.md", _DECISIONS_LOG_ROWS + _GROUPING_ROWS),
         "--reflection-template", template,
         "--decision-source", declared_plan, "--decision-source", grouping],
    )
    arm(
        "grouping-declared-not-supplied-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", declared_plan],
        must_say="declares grouping_source",
    )
    arm(
        "grouping-declared-other-file-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", declared_plan,
         "--decision-source", w("other-session-grouping.md", _DECISION_GROUPING.split(
             "## 8. Open Decisions")[0] + "## 8. Open Decisions\n\nNone.\n\n## 9. Notes\n")],
        must_say="declares grouping_source",
    )
    arm(
        "grouping-placeholder-source-ok",
        "0/OK",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("placeholder-plan.md", _GOOD_PLAN.replace(
             'date: "2026-09-01"\n',
             'date: "2026-09-01"\ngrouping_source: "{.agent/context/grouping/{file}.md | null}"\n', 1))],
    )

    # -- HDP-19: malformed YAML is refused, not read as a record --------------------
    arm(
        "handoff-malformed-yaml-refused",
        "1/REFUSE",
        ["--handoff", w("malformed-handoff.md", _GOOD_HANDOFF.replace(
            "## Decision Log\n\nNone.", "## Decision Log\n\n```yaml\ndecision_log:\n"
            "  - id: D-2\n    stage: execution\n    question: [oops\n```")),
         "--handoff-structure-only"],
        must_say="not valid YAML",
    )
    arm(
        "decision-malformed-matched-refused",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("malformed-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             'question: "Which store?"', "question: [oops"))],
        must_say="not valid YAML",
    )
    arm(
        "decision-unclosed-quote-refused",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("unclosed-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             'chosen: "SQLite"', 'chosen: "SQLite'))],
        must_say="not valid YAML",
    )
    arm(
        "decision-dedent-to-unknown-level-refused",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("dedent-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "    resolution: autonomous", "   resolution: autonomous"))],
        must_say="not valid YAML",
    )

    # -- HDP-20: a decision_log: nested under another key is refused, not read as empty
    nested_tail = "\n## Decision Log\n\n```yaml\nwrapper:\n" + "".join(
        "  " + line + "\n" for line in _DECISION_PLAN_TAIL.split("```yaml\n", 1)[1]
        .split("```", 1)[0].splitlines()) + "```\n"
    arm(
        "decision-nested-key-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("nested-plan.md", _GOOD_PLAN + nested_tail)],
        must_say="nested under",
    )
    arm(
        "decision-nested-key-yaml-file-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("nested.yaml", "wrapper:\n  decision_log:\n  - id: D-1\n")],
        must_say="nested under",
    )
    arm(
        "decision-root-key-matched-ok",
        "0/OK",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", decided_plan],
    )

    # -- HDP-21: the declared grouping binds one file, resolved from the plan's root --
    def grouping_at(path: Path, text: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    empty_grouping = _DECISION_GROUPING.split("## 8. Open Decisions")[0] + (
        "## 8. Open Decisions\n\nNone.\n\n## 9. Notes\n")
    bind = tmp / "bind"
    bound_actual = grouping_at(bind / ".agent" / "context" / "grouping" / "demo.md", _DECISION_GROUPING)
    bound_decoy = grouping_at(bind / "other" / ".agent" / "context" / "grouping" / "demo.md", empty_grouping)
    bound_plan = grouping_at(bind / "plan.md", _GOOD_PLAN.replace(
        'date: "2026-09-01"\n', 'date: "2026-09-01"\ngrouping_source: "./.agent/context/grouping/demo.md "\n', 1))
    arm(
        "grouping-declared-same-suffix-decoy-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", bound_plan, "--decision-source", bound_decoy],
        must_say="declares grouping_source",
    )
    arm(
        "grouping-declared-root-resolved-read",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", bound_plan, "--decision-source", bound_actual],
        must_say="D-7 (grouping",
    )
    arm(
        "grouping-declared-root-resolved-ok",
        "0/OK",
        ["--reflection", rows_reflection("grouped-3.md", _DECISIONS_LOG_ROWS.split("| D-1")[0] + _GROUPING_ROWS),
         "--reflection-template", template,
         "--decision-source", bound_plan, "--decision-source", bound_actual],
    )
    base = tmp / "basename"
    base_actual = grouping_at(base / "demo.md", _DECISION_GROUPING)
    base_decoy = grouping_at(base / "other" / "demo.md", empty_grouping)
    base_plan = grouping_at(base / "plan.md", _GOOD_PLAN.replace(
        'date: "2026-09-01"\n', 'date: "2026-09-01"\ngrouping_source: "demo.md"\n', 1))
    arm(
        "grouping-declared-basename-decoy-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", base_plan, "--decision-source", base_decoy],
        must_say="declares grouping_source",
    )
    arm(
        "grouping-declared-basename-beside-plan-read",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", base_plan, "--decision-source", base_actual],
        must_say="D-7 (grouping",
    )

    # -- HDP-22: the bounded grammar refuses malformed flow, escapes and mixed blocks --
    for label, extra in [
        ("flow-mismatched", "    extra: [oops}\n"),
        ("flow-empty-entry", "    extra: [a,,b]\n"),
        ("flow-map-mismatched", "    extra: {a: [1}\n"),
        ("invalid-escape", '    extra: "bad\\q"\n'),
        ("mixed-map-sequence", "    extra:\n      key: value\n      - item\n"),
        ("mixed-sequence-map", "    extra:\n      - item\n      key: value\n"),
        ("child-under-scalar", "    extra:\n      - id: X\n          child: invalid\n"),
        ("child-under-flow", "    extra: [a]\n      child: invalid\n"),
    ]:
        arm(
            f"decision-{label}-refused",
            "1/REFUSE",
            ["--reflection", d1_reflection, "--reflection-template", template,
             "--decision-source", w(f"{label}-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
                 "```\n", extra + "```\n"))],
            must_say="not valid YAML",
        )
    arm(
        "decision-flow-and-escapes-ok",
        "0/OK",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("flow-ok-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "```\n",
             '    extra: {a: 1, b: [x, "y, z", \'q\'], c: [], d: }\n'
             '    escapes: "tab\\t quote\\" slash\\/ hex\\x41 uni\\u00e9 back\\\\"\n'
             "    trailing: [a, b, ]\n"
             "    nested:\n      - id: X\n        note: v\n      - id: Y\n"
             "    alone:\n      -\n        id: Z\n"
             "```\n"))],
    )

    # -- HDP-23: a source is classified by its structure, never by its filename -------
    arm(
        "grouping-named-plan-read-as-plan",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("grouping-parser-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL)],
        must_say="D-1 (planning",
    )
    grouping_named_handoff = w("grouping-parser-handoff.md", _GOOD_HANDOFF.replace(
        "## Decision Log\n\nNone.", "## Decision Log\n\n" + _DECISION_HANDOFF_ENTRY))
    arm(
        "grouping-named-handoff-structure-ok",
        "0/OK",
        ["--handoff", grouping_named_handoff, "--handoff-structure-only"],
    )
    arm(
        "grouping-named-handoff-read-as-handoff",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", grouping_named_handoff],
        must_say="D-2 (execution",
    )
    arm(
        "grouping-with-decision-log-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("mixed-grouping.md", _DECISION_GROUPING + _DECISION_PLAN_TAIL)],
        must_say="one kind of source",
    )
    arm(
        "handoff-with-open-decisions-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("mixed-handoff.md", _GOOD_HANDOFF + "\n## 8. Open Decisions\n\nNone.\n")],
        must_say="one kind of source",
    )
    declared_handoff_dir = tmp / "declared-handoff"
    arm(
        "grouping-declared-with-plan-source-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", grouping_at(declared_handoff_dir / "plan.md", _GOOD_PLAN.replace(
             'date: "2026-09-01"\n', 'date: "2026-09-01"\ngrouping_source: "demo.md"\n', 1)),
         "--decision-source", grouping_at(declared_handoff_dir / "demo.md", _GOOD_HANDOFF)],
        must_say="one kind of source",
    )

    # -- HDP-24: a valid root decision_log must not mask a second, nested one ------------
    hidden_block = (
        "wrapper:\n"
        "  decision_log:\n"
        "    - id: D-HIDDEN\n"
        "      stage: planning\n"
        '      question: "Hidden?"\n'
        "      resolution: autonomous\n"
        '      chosen: "yes"\n'
        "      source_tag: Local Canon\n"
        '      reasoning: "never reconciled"\n'
    )
    arm(
        "decision-root-plus-nested-refused",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("root-plus-nested-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "```\n", hidden_block + "```\n"))],
        must_say="nested under",
    )
    root_plus_nested_handoff = w("root-plus-nested-handoff.md", _GOOD_HANDOFF.replace(
        "## Decision Log\n\nNone.",
        "## Decision Log\n\n" + _DECISION_HANDOFF_ENTRY.replace(
            "```\n", hidden_block.replace("stage: planning", "stage: execution") + "```\n")))
    arm(
        "decision-root-plus-nested-handoff-structure-refused",
        "1/REFUSE",
        ["--handoff", root_plus_nested_handoff, "--handoff-structure-only"],
        must_say="nested under",
    )
    d2_reflection = rows_reflection("d2-only.md", _DECISIONS_LOG_ROWS.split("| D-1")[0] + (
        "| D-2 | execution | Retry budget? | autonomous | 3 | Local Canon "
        "| matches the client default; two-way door | — |\n"))
    arm(
        "decision-root-plus-nested-handoff-reconcile-refused",
        "1/REFUSE",
        ["--reflection", d2_reflection, "--reflection-template", template,
         "--decision-source", root_plus_nested_handoff],
        must_say="nested under",
    )
    arm(
        "decision-root-plus-nested-yaml-file-refused",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("root-plus-nested.yaml",
                                "decision_log:\n- id: D-1\n  stage: planning\n" + hidden_block)],
        must_say="nested under",
    )
    arm(
        "decision-duplicate-root-key-refused",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("duplicate-root-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "```\n", "decision_log:\n  - id: D-HIDDEN\n    stage: planning\n```\n"))],
        must_say="second root decision_log",
    )
    arm(
        "decision-log-named-in-scalars-and-comments-ok",
        "0/OK",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("scalar-mention-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "```\n",
             '    note: "see the decision_log: fence in the handoff"\n'
             "    # decision_log: is the root key of this block\n"
             "    memo: |\n"
             "      decision_log: mentioned inside a block scalar\n"
             "```\n"))],
    )

    # -- HDP-25: a heading inside a fence or comment is not the file's structure ---------
    fenced_heading = (
        "\n## Notes\n\nThe grouping template reads:\n\n"
        "```markdown\n## 8. Open Decisions\n\nNone.\n\n## 9. Notes\n```\n"
    )
    fenced = tmp / "fenced-heading"
    fenced_plan = grouping_at(fenced / "plan.md", _GOOD_PLAN.replace(
        'date: "2026-09-01"\n', 'date: "2026-09-01"\ngrouping_source: "demo.md"\n', 1) + fenced_heading)
    fenced_grouping = grouping_at(fenced / "demo.md", _DECISION_GROUPING)
    arm(
        "grouping-fenced-heading-declared-omitted-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", fenced_plan],
        must_say="declares grouping_source",
    )
    arm(
        "grouping-fenced-heading-declared-unreconciled-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", fenced_plan, "--decision-source", fenced_grouping],
        must_say="D-7 (grouping",
    )
    arm(
        "grouping-fenced-heading-declared-reconciled-ok",
        "0/OK",
        ["--reflection", rows_reflection("grouped-fenced.md", _DECISIONS_LOG_ROWS.split("| D-1")[0] + _GROUPING_ROWS),
         "--reflection-template", template,
         "--decision-source", fenced_plan, "--decision-source", fenced_grouping],
    )
    arm(
        "plan-fenced-heading-read-as-plan",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("fenced-heading-plan.md", _GOOD_PLAN + fenced_heading + _DECISION_PLAN_TAIL)],
        must_say="D-1 (planning",
    )
    arm(
        "plan-commented-heading-read-as-plan",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("commented-heading-plan.md", _GOOD_PLAN + (
             "\n<!--\n## 8. Open Decisions\n\nNone.\n-->\n") + _DECISION_PLAN_TAIL)],
        must_say="D-1 (planning",
    )
    arm(
        "grouping-declaring-grouping-source-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("self-declaring-grouping.md",
                                '---\ngrouping_source: "demo.md"\n---\n' + _DECISION_GROUPING)],
        must_say="one kind of source",
    )
    arm(
        "grouping-fenced-example-before-real-section-read",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("fenced-example-grouping.md", _DECISION_GROUPING.replace(
             "## 8. Open Decisions",
             "```markdown\n## 8. Open Decisions\n\nNone.\n\n## 9. Notes\n```\n\n"
             "<!--\n## 8. Open Decisions\n\nNone.\n-->\n\n## 8. Open Decisions", 1))],
        must_say="D-7 (grouping",
    )

    # -- HDP-27: a decision_log key is a key wherever YAML puts it ----------------------
    def fenced_plan(name: str, block: str) -> str:
        return w(name, _GOOD_PLAN + "\n## Decision Log\n\n```yaml\n" + block + "```\n")

    sequence_item_log = "- decision_log:\n    - id: D-HIDDEN\n      stage: planning\n"
    flow_only_log = "wrapper: {decision_log: [{id: D-HIDDEN, stage: planning}]}\n"
    arm(
        "decision-sequence-item-root-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", fenced_plan("sequence-item-plan.md", sequence_item_log)],
        must_say="sequence item",
    )
    arm(
        "decision-flow-only-nested-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", fenced_plan("flow-only-plan.md", flow_only_log)],
        must_say="flow collection",
    )
    arm(
        "decision-quoted-root-key-read",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", fenced_plan(
             "quoted-root-plan.md", '"decision_log":\n  - id: D-1\n    stage: planning\n')],
        must_say="D-1 (planning",
    )
    arm(
        "decision-sequence-item-outside-fence-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("sequence-item-prose-plan.md",
                                _GOOD_PLAN + "\n## Decision Log\n\n" + sequence_item_log)],
        must_say="outside any fence",
    )
    for shape, block in (("sequence-item", sequence_item_log), ("flow-only", flow_only_log)):
        arm(
            f"grouping-{shape}-log-in-other-section-refused",
            "1/REFUSE",
            ["--reflection", reflection, "--reflection-template", template,
             "--decision-source", w(f"grouping-{shape}-log.md", empty_grouping + (
                 "\n```yaml\n" + block + "```\n"))],
            must_say="one kind of source",
        )

    # -- HDP-28: a flow collection is walked for the key too --------------------------
    flow_beside_root = _DECISION_PLAN_TAIL.replace("```\n", flow_only_log + "```\n")
    arm(
        "decision-root-plus-flow-nested-refused",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("root-plus-flow-plan.md", _GOOD_PLAN + flow_beside_root)],
        must_say="flow collection",
    )
    arm(
        "decision-root-plus-flow-nested-handoff-structure-refused",
        "1/REFUSE",
        ["--handoff", w("root-plus-flow-handoff.md", _GOOD_HANDOFF.replace(
            "## Decision Log\n\nNone.",
            "## Decision Log\n\n" + _DECISION_HANDOFF_ENTRY.replace(
                "```\n", flow_only_log.replace("planning", "execution") + "```\n"))),
         "--handoff-structure-only"],
        must_say="flow collection",
    )
    arm(
        "decision-root-plus-flow-nested-yaml-file-refused",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("root-plus-flow.yaml",
                                "decision_log:\n- id: D-1\n  stage: planning\n" + flow_only_log)],
        must_say="flow collection",
    )
    arm(
        "decision-flow-scalars-naming-the-key-ok",
        "0/OK",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("flow-scalar-mention-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "```\n",
             '    tags: ["decision_log: mention", "other"]\n'
             '    extra: { note: "decision_log: text" }\n'
             "```\n"))],
    )

    # -- HDP-29: a tilde fence is a fence ----------------------------------------------
    tilde_example = "~~~markdown\n## 8. Open Decisions\n\nNone.\n\n## 9. Notes\n~~~\n"
    arm(
        "grouping-tilde-fenced-example-before-real-section-read",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("tilde-example-grouping.md", _DECISION_GROUPING.replace(
             "## 8. Open Decisions", tilde_example + "\n## 8. Open Decisions", 1))],
        must_say="D-7 (grouping",
    )
    tilde = tmp / "tilde-heading"
    tilde_plan = grouping_at(tilde / "plan.md", _GOOD_PLAN.replace(
        'date: "2026-09-01"\n', 'date: "2026-09-01"\ngrouping_source: "demo.md"\n', 1)
        + "\n## Notes\n\n" + tilde_example)
    tilde_grouping = grouping_at(tilde / "demo.md", _DECISION_GROUPING)
    arm(
        "grouping-tilde-fenced-heading-declared-reconciled-ok",
        "0/OK",
        ["--reflection", rows_reflection("grouped-tilde.md", _DECISIONS_LOG_ROWS.split("| D-1")[0] + _GROUPING_ROWS),
         "--reflection-template", template,
         "--decision-source", tilde_plan, "--decision-source", tilde_grouping],
    )
    arm(
        "plan-tilde-fenced-heading-read-as-plan",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("tilde-heading-plan.md",
                                _GOOD_PLAN + "\n## Notes\n\n" + tilde_example + _DECISION_PLAN_TAIL)],
        must_say="D-1 (planning",
    )
    arm(
        "decision-tilde-yaml-fence-read",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("tilde-yaml-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "```yaml\n", "~~~yaml\n").replace("```\n", "~~~\n"))],
        must_say="says None. but 1 decision",
    )
    arm(
        "decision-tilde-text-fence-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("tilde-text-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "```yaml\n", "~~~text\n").replace("```\n", "~~~\n"))],
        must_say="inside a ~~~text fence",
    )

    # -- HDP-30: a duplicate key inside one record is refused, not first-wins -----------
    duplicate_id = _DECISION_PLAN_TAIL.replace("  - id: D-1\n", "  - id: D-1\n    id: D-LOST\n")
    arm(
        "decision-duplicate-id-in-record-refused",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("duplicate-id-plan.md", _GOOD_PLAN + duplicate_id)],
        must_say="'id' twice",
    )
    arm(
        "decision-duplicate-id-in-record-handoff-structure-refused",
        "1/REFUSE",
        ["--handoff", w("duplicate-id-handoff.md", _GOOD_HANDOFF.replace(
            "## Decision Log\n\nNone.",
            "## Decision Log\n\n" + _DECISION_HANDOFF_ENTRY.replace(
                "  - id: D-2\n", "  - id: D-2\n    id: D-LOST\n"))),
         "--handoff-structure-only"],
        must_say="'id' twice",
    )
    arm(
        "decision-duplicate-nested-key-yaml-file-refused",
        "1/REFUSE",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("duplicate-nested.yaml",
                                "decision_log:\n- id: D-1\n  stage: planning\n"
                                "  research:\n    engine: none\n    engine: tavily\n")],
        must_say="'engine' twice",
    )
    arm(
        "decision-same-key-in-distinct-mappings-ok",
        "0/OK",
        ["--reflection", d1_reflection, "--reflection-template", template,
         "--decision-source", w("distinct-mappings-plan.md", _GOOD_PLAN + _DECISION_PLAN_TAIL.replace(
             "```\n",
             "    alternatives:\n"
             "      - id: A-1\n"
             "        engine: none\n"
             "      - id: A-2\n"
             "        engine: none\n"
             '    # id: a comment is not a key\n'
             '    memo: "id: text is not a key"\n'
             "```\n"))],
    )

    # -- HDP-31: `plan_source: null` is no plan_source ---------------------------------
    arm(
        "grouping-plan-source-null-read-as-grouping",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("plan-source-null-grouping.md",
                                "---\nplan_source: null\n---\n" + _DECISION_GROUPING)],
        must_say="D-7 (grouping",
    )
    arm(
        "grouping-plan-source-null-reconciled-ok",
        "0/OK",
        ["--reflection", rows_reflection("grouped-null.md", _DECISIONS_LOG_ROWS.split("| D-1")[0] + _GROUPING_ROWS),
         "--reflection-template", template,
         "--decision-source", w("plan-source-tilde-grouping.md",
                                "---\nplan_source: ~\n---\n" + _DECISION_GROUPING)],
    )
    arm(
        "grouping-plan-source-string-refused",
        "1/REFUSE",
        ["--reflection", reflection, "--reflection-template", template,
         "--decision-source", w("plan-source-string-grouping.md",
                                '---\nplan_source: "null"\n---\n' + _DECISION_GROUPING)],
        must_say="one kind of source",
    )

    failures = [r for r in results if r[1] != r[2]]
    must_ok = sum(1 for r in results if r[1] == "0/OK")
    for label, want, got in results:
        flag = "ok  " if want == got else "FAIL"
        print(f"  {flag} {label} want={want} got={got}")
    print(
        f"\nRESULT: {len(results)} arm(s), {len(failures)} failure(s) "
        f"[{must_ok} must-OK arms, so the tool is not refusing everything]"
    )
    return 1 if failures else 0


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="validate_closeout_artifacts.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--handoff")
    p.add_argument("--plan")
    p.add_argument("--handoff-structure-only", action="store_true")
    p.add_argument(
        "--ac-coverage-only",
        action="store_true",
        help="only prove every plan AC-ID appears in the handoff",
    )
    p.add_argument("--review")
    p.add_argument("--review-state-only", action="store_true")
    p.add_argument("--review-state-receipt")
    p.add_argument(
        "--approved-state-only",
        action="store_true",
        help="accepted for symmetry with --review-state-only; the receipt is what decides",
    )
    p.add_argument("--expected-review-mode", default="")
    p.add_argument("--expected-target-plan", default="")
    p.add_argument("--max-review-rounds", type=int)
    p.add_argument("--output")
    p.add_argument("--reflection")
    p.add_argument("--reflection-template")
    p.add_argument("--reflection-schema")
    p.add_argument(
        "--decision-source",
        action="append",
        default=None,
        help=(
            "plan / handoff markdown (fenced decision_log YAML), a session grouping (its "
            "## 8. Open Decisions table; the file a plan declares as grouping_source must "
            "be supplied) or a YAML file whose decisions must each have a row in the "
            "reflection's Decisions Log; repeatable"
        ),
    )
    p.add_argument(
        "--decision-issue",
        help="issue ID whose enrichment.decision_log to read from a known-issues --decision-source",
    )
    p.add_argument("--selftest", action="store_true", help="prove every refusal can fire")
    return p


def main(argv: list[str] | None = None, parser: argparse.ArgumentParser | None = None) -> int:
    parser = parser or build_parser()
    argv = sys.argv[1:] if argv is None else argv

    # argparse exits 2 on a bad flag, which already matches USAGE. Intercepting it
    # would only risk turning a malformed invocation into a different code.
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    try:
        notes = run(args)
    except Refuse as exc:
        print(f"REFUSE: {exc}")
        return 1
    except FailClosed as exc:
        print(f"FAIL-CLOSED: {exc}")
        return 3
    except Usage as exc:
        print(f"USAGE: {exc}")
        return 2
    print("OK: " + "; ".join(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
