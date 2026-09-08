#!/usr/bin/env python3
"""validate_closeout_artifacts.py -- structural gates for the closeout artifact set.

Five checks, selected by which arguments are supplied:

  --handoff H --plan P                     handoff/plan binding, AC table, [B] rows
  --handoff H --plan P --ac-coverage-only   only: every plan AC-ID appears in the handoff
  --handoff H --handoff-structure-only      only: handoff structure, no plan needed
  --review F --review-state-only ...        parse the rolling review file -> state receipt
  --review F --review-state-receipt J ...   approval decided from the receipt on disk
  --reflection F --reflection-template T --reflection-schema S

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
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

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
    """Every ``[B]`` row needs a linked follow-up.

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
        haystack = AC_ID.sub("", line.replace("[B]", ""))
        has_link = bool(re.search(r"\[[^\]]+\]\([^)]+\)|#\d+|\b[A-Z]{2,}-\d+\b", haystack))
        if not has_link:
            bad.append(line.strip()[:120])
    if bad:
        raise Refuse(
            f"{len(bad)} of {len(blocked)} [B] row(s) in {path} carry no linked "
            f"follow-up. A [B] without a follow-up is a dropped row that counts as "
            f"closed:\n  " + "\n  ".join(bad)
        )
    return [f"{len(blocked)} [B] row(s), all with a linked follow-up"]


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
    required = ["## Acceptance Criteria", "## Evidence"]
    absent = [h for h in required if h not in text]
    if absent:
        raise Refuse(
            f"handoff {path} is missing required section(s): {', '.join(absent)}."
        )
    rows = table_cells(text, "## Acceptance Criteria")
    if not rows:
        raise Refuse(
            f"handoff {path} has an '## Acceptance Criteria' heading but no table "
            f"rows under it. The heading is what a presence check sees; the rows are "
            f"what a reviewer needs."
        )
    return [f"required sections present; {len(rows)} AC row(s)"]


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


def check_reflection(
    text: str, path: str, template_path: str | None, schema_path: str | None
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

    if args.reflection:
        if not args.reflection_template and not args.reflection_schema:
            raise Usage(
                "--reflection needs --reflection-template and/or --reflection-schema. "
                "With neither, the only thing left to check is that the file is "
                "non-empty, which is not a gate."
            )
        text = read_text(args.reflection, "reflection")
        return check_reflection(
            text, args.reflection, args.reflection_template, args.reflection_schema
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

## Evidence

Ran the suite; 12 passed.
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
            "| AC-2 | integration | other thing works | Spec | test_b.py::test_other | [B] ISSUE-42 |")),
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
