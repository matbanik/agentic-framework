"""Lane-route instructions: ``ownership-check`` and the lane-route documents.

The ``ownership-check`` verb is reached through the CLI (``sys.executable tools/lanes.py ...``).
Do not skip, only, or early-return.

Design choices (the tests pin each one):

* ``tools/lanes.py ownership-check --task <task.md>``: ``<task.md>`` is a path relative to
  the working directory or absolute; the working directory is inside a git repository.
  It runs the Lane Ownership checks of ``claim`` (``_load_ownership`` and the
  junction-file cover check) without a card, and writes nothing. Success: a stdout
  line ``ownership_ok``, exit 0. A failure: a stdout line
  ``ownership_bad:<reason>[:<entry>]`` (an optional ``refused: `` prefix is accepted),
  exit 1. The reasons this file pins: ``no_ownership``, ``owns_junction:<entry>`` (the
  ``owns`` entry as written) and ``owns_overlap:<entry>`` (one of the two overlapping
  entries, as written), which is the ``ownership-check`` name of the ``claim`` reason
  ``ownership_contradiction``. The junction files come from the ``junction_files`` key of
  ``.agent/credits/worktree.json``, so every scratch repository here seeds that config.
* ``tools/lanes.py ownership-check --grouping <file>`` reads the one ``yaml`` fence of the
  file's ``## Session Ownership`` section, in block style::

      sessions:
        <id>:
          tier: <int >= 1>
          owns:
            - <entry>

  It prints one stdout line ``overlap:<tier>:<a>:<b>:<entry>`` for each pair of sessions
  in one tier whose ``owns`` sets cover a common path, with ``<entry>`` one
  of the pair's entries, and exits 1 when any line is printed. Sessions in different
  tiers may overlap: exit 0, no ``overlap:`` and no ``ownership_bad`` line. A tier below
  1 is ``ownership_bad:tier:<session>``; an unknown key, at the top or in a session, is
  ``ownership_bad:extra_key:<key>``; both exit 1.
* The documents: the TASK-TEMPLATE Lane Ownership section names the default (every plan
  in an executor worktree) and the main-tree exception with a recorded basis, in a
  sentence that keeps ``optional``; the start procedure is
  ``executor_worktree.py create <slug> --lane-plan <plan dir>``; H1-3, H2-3, H2-3a and
  H2-3b name their integration request forms; the H2-3c Task cell names
  ``tools/lanes.py land prepare`` before ``executor_worktree.py land``; ``create-plan.md``
  Step 4 runs ``tools/lanes.py ownership-check --task`` as a check that blocks Step 5;
  ``session-grouping.md`` STAGE B defines ``## Session Ownership`` and the
  ``tools/lanes.py ownership-check --grouping`` step; and ``execution-session.md`` §4, the
  H2-3c row and ``commands.md`` §Quick Commands state one release order: ``remove``, then
  ``tools/lanes.py release``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools.tests import lane_worktree_config as lwc

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "tools" / "lanes.py"
TASK_TEMPLATE = ROOT / "templates" / "TASK-TEMPLATE.md"
CREATE_PLAN = ROOT / ".agent" / "workflows" / "create-plan.md"
SESSION_GROUPING = ROOT / ".agent" / "workflows" / "session-grouping.md"
EXEC_SESSION = ROOT / ".agent" / "workflows" / "execution-session.md"
COMMANDS = ROOT / ".agent" / "docs" / "commands.md"

OWNERSHIP_OK = "ownership_ok"
JUNCTION_ENTRY = ".agent/context/meu-status.yaml"
LANE_PREPARE = "tools/lanes.py land prepare"
OLD_LAND = "executor_worktree.py land"
START_FORM = "executor_worktree.py create <slug> --lane-plan "
ROW_FORMS: dict[str, tuple[str, ...]] = {
    "H1-3": ("meu-status",),
    "H2-3": ("metrics-row",),
    "H2-3a": ("grouping-cursor",),
    "H2-3b": ("ki-close",),
}
ALL_FORMS = ("meu-status", "metrics-row", "grouping-cursor", "ki-close", "ki-file")

# One sentence (no ". " inside), no table cell or command break (no "|" or ";").
_SPAN = r"(?:(?!\.\s)[^;|]){0,200}?"
BAD_ORDER = re.compile(
    rf"\brelease\b{_SPAN}\bthen\b[\s`]*(?:(?:tools/)?executor_worktree\.py\s+)?remove\b",
    re.IGNORECASE,
)
GOOD_ORDER = re.compile(
    rf"\bremove\b{_SPAN}\bthen\b[\s`]*(?:tools/)?(?:lanes\.py\s+)?release\b"
    r"|\brelease\b[^|]{0,240}?\bafter\b[^|]{0,60}?\bremove(?:d|s)?\b",
    re.IGNORECASE,
)
LANE_WORD = re.compile(r"\blanes?\b", re.IGNORECASE)
LANE_SENSES = ("lanes.py", "Lane Ownership", "lane/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(path: Path) -> str:
    """The file's UTF-8 text with LF line ends."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _flat(text: str) -> str:
    """``text`` with every whitespace run made one space."""
    return " ".join(text.split())


def _section(text: str, heading: str) -> str:
    """From the line that starts with ``heading`` to the next heading of its level or higher."""
    level = len(heading) - len(heading.lstrip("#"))
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(heading)]
    assert len(starts) == 1, f"want one heading {heading!r}, found {len(starts)}"
    out = [lines[starts[0]]]
    for line in lines[starts[0] + 1 :]:
        hashes = len(line) - len(line.lstrip("#"))
        if 0 < hashes <= level and line[hashes : hashes + 1] == " ":
            break
        out.append(line)
    return "\n".join(out)


def _between(text: str, start: str, end: str) -> str:
    """The text from the first line that starts with ``start`` up to the line ``end``."""
    lines = text.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(start))
    last = next(i for i in range(first + 1, len(lines)) if lines[i].startswith(end))
    return "\n".join(lines[first:last])


def _chunks(text: str) -> list[str]:
    """The paragraphs and list items of ``text``, each flattened."""
    parts = re.split(r"\n\s*\n|\n(?=\s*- )", text)
    return [_flat(part) for part in parts if part.strip()]


def _sentences(text: str) -> list[str]:
    """The sentences of ``text`` (flattened, split after ``.``, ``!`` or ``?``)."""
    return re.split(r"(?<=[.!?])\s+(?=[A-Z`*(])", _flat(text))


def _row(template: str, row_id: str) -> str:
    """The one table row of ``template`` whose first cell is ``row_id``."""
    rows = [line for line in template.splitlines() if line.startswith(f"| {row_id} |")]
    assert len(rows) == 1, f"want one {row_id} row, found {len(rows)}"
    return rows[0]


def _cells(row: str) -> list[str]:
    """The cells of a table row; an escaped ``\\|`` stays inside its cell."""
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", row.strip())[1:-1]]


def _names_form(text: str, form: str) -> bool:
    """True when ``text`` names ``form`` as a word, not as part of a path or file name."""
    return re.search(rf"(?<![\w/.-]){re.escape(form)}(?![\w.-])", text) is not None


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``tools/lanes.py <args>`` with ``cwd``; never raises on exit."""
    return subprocess.run(
        [sys.executable, str(LANES), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )


def _lines(proc: subprocess.CompletedProcess[str]) -> list[str]:
    """The stdout lines with an optional ``refused: `` prefix removed."""
    return [line.removeprefix("refused: ").strip() for line in proc.stdout.splitlines()]


def _show(proc: subprocess.CompletedProcess[str]) -> str:
    return (
        f"exit={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr[-800:]!r}"
    )


def _repo(tmp_path: Path) -> Path:
    """An empty git repository under ``tmp_path``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", str(repo)],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    config = repo / lwc.WORKTREE_CONFIG
    config.parent.mkdir(parents=True)
    config.write_text(lwc.WORKTREE_CONFIG_TEXT, encoding="utf-8", newline="\n")
    return repo


def _task(owns: list[str], must_not_touch: list[str]) -> str:
    """A ``task.md`` body with one Lane Ownership section."""
    body = ["# Task", "", "## Lane Ownership", "", "```yaml", "owns:"]
    body += [f"  - {entry}" for entry in owns]
    body += ["must_not_touch:"] + [f"  - {entry}" for entry in must_not_touch]
    body += ["```", "", "## Task Table", ""]
    return "\n".join(body) + "\n"


def _grouping(sessions: dict[str, tuple[object, list[str]]], extra: str = "") -> str:
    """A grouping file with one ``## Session Ownership`` fence; ``extra`` goes in raw."""
    body = ["# Grouping", "", "## Session Ownership", "", "```yaml", "sessions:"]
    for session, (tier, owns) in sessions.items():
        body += [f"  {session}:", f"    tier: {tier}", "    owns:"]
        body += [f"      - {entry}" for entry in owns]
    if extra:
        body.append(extra)
    body += ["```", "", "## Session Progress", ""]
    return "\n".join(body) + "\n"


def _check_grouping(tmp_path: Path, text: str) -> subprocess.CompletedProcess[str]:
    repo = _repo(tmp_path)
    (repo / "grouping.md").write_text(text, encoding="utf-8", newline="\n")
    return _run(repo, "ownership-check", "--grouping", "grouping.md")


def _overlaps(proc: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in _lines(proc) if line.startswith("overlap:")]


# ---------------------------------------------------------------------------
# ownership-check --task
# ---------------------------------------------------------------------------


def test_ac828_1_task_check_passes_the_template(tmp_path: Path) -> None:
    """The template's own example prints ``ownership_ok`` (run in a seeded scratch repo)."""
    assert TASK_TEMPLATE.is_file(), TASK_TEMPLATE
    repo = _repo(tmp_path)
    (repo / "task.md").write_text(_text(TASK_TEMPLATE), encoding="utf-8", newline="\n")
    proc = _run(repo, "ownership-check", "--task", "task.md")
    assert proc.returncode == 0, _show(proc)
    assert OWNERSHIP_OK in _lines(proc), _show(proc)


def test_ac828_1_task_without_the_section_is_no_ownership(tmp_path: Path) -> None:
    """no Lane Ownership section → ``ownership_bad:no_ownership``."""
    repo = _repo(tmp_path)
    (repo / "task.md").write_text("# Task\n\nNo section.\n", encoding="utf-8")
    proc = _run(repo, "ownership-check", "--task", "task.md")
    assert proc.returncode == 1, _show(proc)
    assert "ownership_bad:no_ownership" in _lines(proc), _show(proc)
    assert OWNERSHIP_OK not in _lines(proc), _show(proc)


@pytest.mark.parametrize("entry", [JUNCTION_ENTRY, ".agent/context/"])
def test_ac828_1_junction_entry_is_owns_junction(tmp_path: Path, entry: str) -> None:
    """an ``owns`` entry on or above a junction file → ``owns_junction``."""
    repo = _repo(tmp_path)
    (repo / "task.md").write_text(_task([entry], []), encoding="utf-8")
    proc = _run(repo, "ownership-check", "--task", "task.md")
    assert proc.returncode == 1, _show(proc)
    assert f"ownership_bad:owns_junction:{entry}" in _lines(proc), _show(proc)


def test_ac828_1_owns_must_not_touch_overlap_is_owns_overlap(tmp_path: Path) -> None:
    """``owns`` ``tools/`` against ``must_not_touch`` ``tools/lanes.py``."""
    repo = _repo(tmp_path)
    (repo / "task.md").write_text(
        _task(["tools/"], ["tools/lanes.py"]), encoding="utf-8"
    )
    proc = _run(repo, "ownership-check", "--task", "task.md")
    assert proc.returncode == 1, _show(proc)
    bad = [line for line in _lines(proc) if line.startswith("ownership_bad:")]
    assert bad in (
        ["ownership_bad:owns_overlap:tools/"],
        ["ownership_bad:owns_overlap:tools/lanes.py"],
    ), _show(proc)


def test_ac828_1_valid_task_in_a_scratch_repo_passes(tmp_path: Path) -> None:
    """a valid section with no junction entry and no overlap → ``ownership_ok``."""
    repo = _repo(tmp_path)
    (repo / "task.md").write_text(
        _task(["tools/a.py"], ["tools/b.py"]), encoding="utf-8"
    )
    proc = _run(repo, "ownership-check", "--task", "task.md")
    assert proc.returncode == 0, _show(proc)
    assert _lines(proc).count(OWNERSHIP_OK) == 1, _show(proc)


# ---------------------------------------------------------------------------
# ownership-check --grouping
# ---------------------------------------------------------------------------


def test_ac828_2_same_tier_overlap_prints_one_line(tmp_path: Path) -> None:
    """two tier-1 sessions on ``tools/`` and ``tools/lanes.py`` → one line, exit 1."""
    text = _grouping({"A1": (1, ["tools/"]), "A2": (1, ["tools/lanes.py"])})
    proc = _check_grouping(tmp_path, text)
    assert proc.returncode == 1, _show(proc)
    lines = _overlaps(proc)
    assert len(lines) == 1, _show(proc)
    match = re.fullmatch(r"overlap:1:(A1:A2|A2:A1):(tools/|tools/lanes\.py)", lines[0])
    assert match is not None, _show(proc)


def test_ac828_2_different_tiers_may_overlap(tmp_path: Path) -> None:
    """the same pair in tiers 1 and 2 → exit 0, no ``overlap:`` line."""
    text = _grouping({"A1": (1, ["tools/"]), "A2": (2, ["tools/lanes.py"])})
    proc = _check_grouping(tmp_path, text)
    assert proc.returncode == 0, _show(proc)
    assert _overlaps(proc) == [], _show(proc)
    assert not [ln for ln in _lines(proc) if ln.startswith("ownership_bad")], _show(
        proc
    )


def test_ac828_2_one_line_per_overlapping_pair(tmp_path: Path) -> None:
    """three tier-1 sessions with two overlapping pairs → exactly two lines."""
    text = _grouping(
        {
            "A1": (1, ["tools/"]),
            "A2": (1, ["tools/lanes.py"]),
            "A3": (1, ["tools/x.py"]),
            "A4": (1, ["docs/"]),
        }
    )
    proc = _check_grouping(tmp_path, text)
    assert proc.returncode == 1, _show(proc)
    pairs = sorted("".join(sorted(line.split(":")[2:4])) for line in _overlaps(proc))
    assert pairs == ["A1A2", "A1A3"], _show(proc)


def test_ac828_2_disjoint_same_tier_sessions_pass(tmp_path: Path) -> None:
    """same-tier sessions with disjoint ``owns`` sets → exit 0, no line."""
    text = _grouping({"A1": (1, ["tools/a.py"]), "A2": (1, ["tools/ab.py", "docs/"])})
    proc = _check_grouping(tmp_path, text)
    assert proc.returncode == 0, _show(proc)
    assert _overlaps(proc) == [], _show(proc)


@pytest.mark.parametrize("tier", ["0", "-1"])
def test_ac828_2_tier_below_one_is_refused(tmp_path: Path, tier: str) -> None:
    """Boundary: ``tier`` below 1 → ``ownership_bad:tier:<session>``, exit 1."""
    text = _grouping({"A1": (tier, ["tools/"]), "A2": (2, ["docs/"])})
    proc = _check_grouping(tmp_path, text)
    assert proc.returncode == 1, _show(proc)
    assert "ownership_bad:tier:A1" in _lines(proc), _show(proc)


@pytest.mark.parametrize(
    ("extra", "key"),
    [("    notes: x", "notes"), ("owners: []", "owners")],
    ids=["session_key", "top_key"],
)
def test_ac828_2_unknown_key_is_extra_key(tmp_path: Path, extra: str, key: str) -> None:
    """Boundary: an unknown key in a session or at the top → ``ownership_bad:extra_key``."""
    text = _grouping({"A1": (1, ["tools/"])}, extra)
    proc = _check_grouping(tmp_path, text)
    assert proc.returncode == 1, _show(proc)
    assert f"ownership_bad:extra_key:{key}" in _lines(proc), _show(proc)


# ---------------------------------------------------------------------------
# TASK-TEMPLATE.md v2.6
# ---------------------------------------------------------------------------


def test_ac828_3_lane_ownership_is_the_default() -> None:
    """the default for executor-worktree plans and the main-tree exception."""
    section = _section(_text(TASK_TEMPLATE), "## Lane Ownership")
    sentences = _sentences(section)
    default = [s for s in sentences if "default" in s and "executor worktree" in s]
    assert default, "no sentence makes the section the default in an executor worktree"
    exception = [
        s
        for s in sentences
        if "optional" in s and re.search(r"main[- ]tree", s) and "basis" in s
    ]
    assert exception, "no sentence keeps `optional` for a main-tree plan with a basis"
    assert "Keep it only when the plan runs as a lane" not in _flat(section)


def test_ac828_3_start_procedure_names_lane_plan() -> None:
    """the start procedure is ``executor_worktree.py create <slug> --lane-plan``."""
    assert START_FORM in _text(TASK_TEMPLATE)


@pytest.mark.parametrize("row_id", sorted(ROW_FORMS))
def test_ac828_3_junction_rows_name_their_request_forms(row_id: str) -> None:
    """H1-3, H2-3, H2-3a and H2-3b write integration requests in a lane plan."""
    row = _row(_text(TASK_TEMPLATE), row_id)
    missing = [form for form in ROW_FORMS[row_id] if not _names_form(row, form)]
    assert missing == [], f"{row_id} does not name {missing}"
    assert re.search(r"integration request", row, re.IGNORECASE), row_id


def test_ac828_3_junction_rows_cover_all_five_forms() -> None:
    """the four rows together name the five request forms."""
    template = _text(TASK_TEMPLATE)
    rows = " ".join(_row(template, row_id) for row_id in ROW_FORMS)
    assert [form for form in ALL_FORMS if not _names_form(rows, form)] == []


def test_ac828_3_h2_3c_names_the_lane_route_first() -> None:
    """the H2-3c Task cell names ``land prepare`` before ``executor_worktree.py land``."""
    task = _cells(_row(_text(TASK_TEMPLATE), "H2-3c"))[1]
    lane, old = task.find(LANE_PREPARE), task.find(OLD_LAND)
    assert lane >= 0 and old >= 0, (lane, old)
    assert lane < old, f"{LANE_PREPARE}@{lane} comes after {OLD_LAND}@{old}"


# ---------------------------------------------------------------------------
# create-plan.md Step 4
# ---------------------------------------------------------------------------


def _step_4() -> str:
    return _between(_text(CREATE_PLAN), "### 4. Generate Plan", "### 4A.")


def test_ac828_4_step_4_blocks_step_5_on_ownership_check() -> None:
    """Step 4 runs ``ownership-check --task``; a failure blocks Step 5."""
    hits = [
        c for c in _chunks(_step_4()) if "tools/lanes.py ownership-check --task" in c
    ]
    assert hits, "Step 4 does not name `tools/lanes.py ownership-check --task`"
    assert any(
        "Step 5" in c and re.search(r"\bblock", c, re.IGNORECASE) for c in hits
    ), hits


def test_ac828_4_step_4_writes_lane_ownership_by_default() -> None:
    """Step 4 writes the ``## Lane Ownership`` section by default."""
    hits = [c for c in _chunks(_step_4()) if "## Lane Ownership" in c]
    assert hits, "Step 4 does not name `## Lane Ownership`"
    assert any(re.search(r"\bdefault\b", c) for c in hits), hits


# ---------------------------------------------------------------------------
# session-grouping.md
# ---------------------------------------------------------------------------


def test_ac828_5_stage_b_defines_session_ownership() -> None:
    """STAGE B defines the block and the ``ownership-check --grouping`` step."""
    stage_b = _between(
        _text(SESSION_GROUPING), "## STAGE B", "## Handoff to `/create-plan`"
    )
    for token in (
        "## Session Ownership",
        "tools/lanes.py ownership-check --grouping",
        "sessions:",
        "tier:",
        "owns:",
    ):
        assert token in stage_b, f"STAGE B does not name {token!r}"


def test_ac828_5_lane_means_a_lanes_py_lane() -> None:
    """each paragraph that says "lane" means a ``tools/lanes.py`` lane."""
    stray = [
        chunk
        for chunk in _chunks(_text(SESSION_GROUPING))
        if LANE_WORD.search(chunk) and not any(sense in chunk for sense in LANE_SENSES)
    ]
    assert stray == [], stray
    assert not re.search(
        r"\bserial lanes?\b|\blanes? of sessions\b", _text(SESSION_GROUPING)
    )


# ---------------------------------------------------------------------------
# one release order (remove, then release)
# ---------------------------------------------------------------------------


def _release_lines(commands: str) -> str:
    # The packaged commands.md keeps shell comment lines (``# ...``) inside the Quick Commands
    # fence, which ``_section`` would read as level-1 headings; end at the next ``## `` heading.
    after = commands.split("## Quick Commands", 1)[1]
    quick = after.split(chr(10) + "## ", 1)[0]
    return "\n".join(ln for ln in quick.splitlines() if "tools/lanes.py release" in ln)


DOC_VIEWS = {
    "execution-session step 4": lambda: _section(
        _text(EXEC_SESSION), "### 4. Execute the Approved Plan"
    ),
    "TASK-TEMPLATE H2-3c": lambda: _row(_text(TASK_TEMPLATE), "H2-3c"),
    "commands.md release": lambda: _release_lines(_text(COMMANDS)),
}


@pytest.mark.parametrize("where", sorted(DOC_VIEWS))
def test_ac828_6_one_release_order(where: str) -> None:
    """no release-then-remove order; the remove-then-release order is stated."""
    text = _flat(DOC_VIEWS[where]())
    assert text, f"{where} is empty"
    bad = BAD_ORDER.search(text)
    assert bad is None, (
        f"{where} releases before remove: {bad.group(0) if bad else ''!r}"
    )
    assert GOOD_ORDER.search(text), f"{where} does not state remove, then release"


def test_ac828_6_order_patterns_reject_and_accept() -> None:
    """the patterns flag the v2.4 order and accept the frozen order."""
    old = "run `tools/lanes.py release --worktree <path> --reset`, then `remove`."
    new = "run `executor_worktree.py remove <path>`, then `tools/lanes.py release --worktree <path>`."
    assert BAD_ORDER.search(old) and not GOOD_ORDER.search(old)
    assert GOOD_ORDER.search(new) and not BAD_ORDER.search(new)


RESUME_BRIEF = (
    ROOT / ".agent" / "skills" / "claude-credits" / "templates" / "resume-brief.md"
)
IDENTITY_CREATE = "create <run-id> --run-id <run-id> --op <op> --plan <slug>"


def test_credits_docs_name_the_identity_create() -> None:
    """The resume brief and the landing record name the identity create."""
    landing = _flat(_section(_text(EXEC_SESSION), "### The landing record"))
    for where, text in (
        ("resume-brief", _flat(_text(RESUME_BRIEF))),
        ("landing record", landing),
    ):
        assert IDENTITY_CREATE in text, f"{where} does not name `{IDENTITY_CREATE}`"
    assert "admission creates the worktree" not in _text(RESUME_BRIEF), (
        "the resume brief still says admission creates the worktree"
    )


# ---------------------------------------------------------------------------
# H2-3c routes by the landed query
# ---------------------------------------------------------------------------

LANDED_QUERY = "tools/lanes.py landed --worktree {worktree}"
LANE_REMOVE = "tools/executor_worktree.py remove {worktree}"
LANE_RELEASE = "tools/lanes.py release --worktree {worktree} --reset"
OLD_LAND_CMD = "tools/executor_worktree.py land {worktree}"


def _validation(row_id: str) -> str:
    return _cells(_row(_text(TASK_TEMPLATE), row_id))[4]


def test_h2_3c_validation_asks_the_landed_query_first() -> None:
    """The command reads ``landed`` before it can run the old-route ``land``."""
    command = _validation("H2-3c")
    query, land = command.find(LANDED_QUERY), command.find(OLD_LAND_CMD)
    assert 0 <= query < land, (query, land)
    assert "not_landed:no_card" in command, "the old route is not keyed on no_card"
    assert "^landed:" in command, "the lane route is not keyed on the landed: line"


def test_h2_3c_lane_branch_removes_then_releases_without_land() -> None:
    """The lane branch runs ``remove``, then ``release --reset``, and no ``land``."""
    command = _validation("H2-3c")
    query = command.find(LANDED_QUERY)
    remove = command.find(LANE_REMOVE, query)
    release = command.find(LANE_RELEASE, query)
    land = command.find(OLD_LAND_CMD, query)
    assert 0 <= query < remove < release < land, (query, remove, release, land)
    lane_branch = command[query:land]
    assert OLD_LAND_CMD not in lane_branch
    assert "exit $code }" in command[release:land], "the lane branch does not end"


def test_h2_3c_task_cell_names_the_landed_routing() -> None:
    """The Task cell says how the Validation command picks the route."""
    task = _flat(_cells(_row(_text(TASK_TEMPLATE), "H2-3c"))[1])
    for token in ("tools/lanes.py landed --worktree", "not_landed:no_card", "landed:"):
        assert token in task, f"the H2-3c Task cell does not name {token!r}"
