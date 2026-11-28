"""MEU-925 eligible and simulate: AC-925.1 to AC-925.8 (plan 2026-11-05-ao1-grouping-spec-scheduler).

Row 925-R writes these tests before ``tools/orch.py`` exists, so they fail first (RED).
Each test imports ``tools.orch`` inside its body, so the file collects on the tree
without the module (G19). Do not skip, only, or early-return (G36).

Design choices that row 925-G implements (the tests pin each one):

* ``tools/orch.py`` reads state and prints. It has the verbs ``simulate`` and
  ``eligible`` only. ``main(argv)`` returns the exit code: 0 for a result, 1 for a
  refused input (stdout line 1 is ``<verb>_bad:<reason>``, the detail goes to stderr),
  2 for an argparse error (``main`` returns the code of argparse's ``SystemExit``).
* ``load_spec(path)`` returns ``(lanes, sessions)``: the fixture's ``lanes`` list and a
  dict of session id to ``Session`` in file order. A fixture session has exactly the
  keys ``lane``, ``size``, ``tier``, ``owns``, ``after`` and ``vm``. An unknown key is
  ``key:<sid>:<key>``; a missing or bad value is ``<field>:<sid>``; an ``after`` id that
  is not a session is ``after:<sid>:<id>``. A session id is capital letters, a number
  and an optional lowercase suffix (``UF4c``); another id is ``sid:<sid>``.
* ``--grouping FILE`` (one or more) reads each ``## Session Ownership`` block with
  ``lanes.parse_session_spec``. The lane of a session is the letter prefix of its id.
  The lanes are in the order of first appearance. A session with no ``size`` is
  ``size:<sid>``. A session id in two files is ``duplicate:<sid>``. ``after`` ids
  resolve across every file on the command line.
* ``overlap(a, b)`` is the guide's: an equal entry, or an entry that ends in ``/`` and
  is a prefix of the other; each hit is the longer entry, once, in the order found.
  ``must_follow(session, sessions)`` is ``after`` plus the lower-tier sessions of the
  same grouping (the same lane for a fixture) that share an ``owns`` entry, in input
  order. ``conflicts(session, sessions)`` maps each other session to a ``Conflict``
  with ``entries`` (the overlap hits, a tuple) and ``vm`` (both sessions are ``vm``);
  a session with neither is not in the map.
* A cycle of ``must_follow`` is ``cycle:<ids>``: the ids of the sessions on a cycle,
  in input order, joined by ``,``.
* ``--order guide`` takes the sessions of a lane in input order (the guide's number
  order). ``--order critical-path`` (the default) ranks them by the longest remaining
  path of ``must_follow`` dependents, weighted by size (small 1.0, small-to-medium
  1.5, medium 2.0, medium-to-large 2.5, large 3.0), then by lane order, then by the
  number of the id, then by its letter suffix.
* ``simulate`` is the guide's greedy loop: each lane has ``--executors`` slots; at
  each time a free slot takes the first session of its queue whose ``must_follow``
  sessions have landed and that has no conflict with a running session. With
  ``--borrow LANE``, a free slot of that lane that finds nothing takes from the other
  lanes, the lane with the most remaining weight first; a lane that is not an input
  lane is ``borrow:<lane>``. The limits the guide does
  not model: one running ``e2e`` session; ``--workers N`` running sessions in all;
  ``--trees main`` gives one running session in all (one queue in rank order;
  ``--executors`` and ``--borrow`` have no effect). A held session and each session
  that must follow an unscheduled one are left out before the run and listed in
  ``held`` with ``hold:<kind>:<reason>`` or ``after:<sid>``. ``simulate`` reads no
  Session Progress status.
* ``simulate --json`` prints one object: ``makespan``, ``order``, ``executors``,
  ``trees``, ``borrow``, ``workers``, ``schedule`` (lane to a list of ``{sid, start,
  end, slot}``), ``held`` and ``caps_not_modeled``.
* ``eligible`` reads the Session Progress table of each grouping. ``pending`` and
  ``▶ NEXT`` sessions are candidates; ``in-progress`` sessions are running; a status
  that starts with the word ``done`` or ``skipped`` satisfies ``after``; ``blocked…``
  and ``split…`` sessions get only ``status:<word>``. Another status is
  ``status:<sid>:<value>``. A session in the block and not in the table, or the
  reverse, is ``progress:<sid>``.
* A reserving card (``active`` or ``landing``) maps to a session through the
  frontmatter ``grouping_source`` and ``grouping_session`` of
  ``<worktree>/<plan>/task.md``, else ``<repo>/<plan>/task.md``. A mapped session is
  running, and its card ``owns`` entries count with its spec ``owns``. A card whose
  plan has no grouping keys, or names a grouping that is not on the command line,
  is unmapped: its ``owns`` entries conflict as ``conflict:<card lane>:<entry>``. An
  unreadable card, a card with no task.md, or a card that names a session that is
  not in its grouping is ``card:<file name>``. Without ``--cards-dir``, the cards are
  in ``lanes/`` of the git common dir of ``--repo``, found from the files.
* ``eligible`` takes the candidates in critical-path order. For each one it records
  every reason that applies, and a candidate with no reason is selected and then
  counts as running. ``lane_busy``: a session of its lane runs. ``tree_busy`` (only
  with ``--trees main``, the default): a session runs, or an unmapped reserving card
  has the ``--repo`` folder as its worktree. With ``--trees lanes`` each lane has its
  own tree, so ``lane_busy`` covers it. ``--json`` prints ``eligible`` (selection order), ``excluded``
  (each waiting, blocked or split session to its reasons), ``running``,
  ``resources``, ``can_dispatch_review`` and ``can_plan_commit``.

Framework port (AC-925.9): the fixture is
``tools/tests/orch_fixtures/guide_spec_resolved.json``, with ``{{PROJECT_NAME}}`` in
place of the project name. The change is one-to-one, so the overlaps and the
AC-925.2 numbers do not change. The test that reads the adopter's own grouping
files (the live part of AC-925.6) stays in the adopter. The AC-925.7 scan looks for
the ``{{PROJECT_NAME}}`` literal.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / "tools" / "orch.py"
FIXTURE = ROOT / "tools" / "tests" / "orch_fixtures" / "guide_spec_resolved.json"
PROJECT_LITERAL = "{{PROJECT_NAME}}".lower()
#: A drive root, split so that this file holds no drive path (AC-J.2).
DRIVE = "P" + ":/"

GUIDE_NUMBERS = {
    "k1": (["--order", "guide"], 53.5),
    "borrow": (["--order", "guide", "--borrow", "RX"], 45.0),
    "k2": (["--order", "guide", "--executors", "2"], 31.0),
}
CAPS_NOT_MODELED = ["reviews:3", "plan_commits:1"]
RESOURCE_NAMES = {"reviews", "plan_commits", "workers", "vm", "e2e", "trees"}
RECORD_KEYS = {"limit_name", "configured_value", "observed_value", "window", "free"}
REFUSED_VERBS = (
    "push",
    "merge",
    "tag",
    "release",
    "deploy",
    "commit",
    "verdict",
    "approve",
    "rule",
)
FORBIDDEN_IMPORTS = (
    "anthropic",
    "openai",
    "subprocess",
    "multiprocessing",
    "asyncio",
    "socket",
    "http",
    "urllib",
)
HOLD_REASON = "Grouping section 8 D-16: the user rules the tree model before AO4."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _orch() -> ModuleType:
    return importlib.import_module("tools.orch")


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    """``orch.main(argv)`` with the captured ``(code, stdout, stderr)``."""
    code = _orch().main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def _json(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    """The ``--json`` object of a run that must exit 0."""
    code, out, err = _run(capsys, *argv, "--json")
    assert code == 0, f"exit={code}\nstdout={out!r}\nstderr={err[-800:]!r}"
    data = json.loads(out)
    assert isinstance(data, dict)
    return data


def _refusal(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    """Line 1 of stdout of a run that must exit 1."""
    code, out, err = _run(capsys, *argv)
    assert code == 1, f"exit={code}\nstdout={out!r}\nstderr={err[-800:]!r}"
    return out.splitlines()[0].strip()


def _spec_session(sid: str, **values: Any) -> dict[str, Any]:
    """One fixture session: the letter prefix as ``lane``, a small tier-1 default."""
    lane = re.match(r"[A-Z]+", sid)
    assert lane is not None
    data: dict[str, Any] = {
        "lane": lane.group(0),
        "size": "small",
        "tier": 1,
        "owns": [],
        "after": [],
        "vm": False,
    }
    data.update(values)
    return data


def _spec(
    tmp_path: Path,
    sessions: dict[str, dict[str, Any]],
    lanes: Sequence[str] | None = None,
    name: str = "spec.json",
) -> Path:
    """Write an ``orch-spec/1`` fixture; the lanes default to the order of first use."""
    if lanes is None:
        lanes = list(dict.fromkeys(str(s["lane"]) for s in sessions.values()))
    path = tmp_path / name
    data = {"schema": "orch-spec/1", "lanes": list(lanes), "sessions": sessions}
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return path


def _block_lines(
    sid: str,
    *,
    tier: int = 1,
    owns: Sequence[str] = (),
    after: Sequence[str] = (),
    size: str | None = "small",
    vm: bool = False,
    e2e: bool = False,
    hold: tuple[str, str] | None = None,
) -> list[str]:
    """The Session Ownership lines of one session in the AO1-D15 line forms."""
    lines = [f"  {sid}:", f"    tier: {tier}"]
    if owns:
        lines += ["    owns:", *(f"      - {entry}" for entry in owns)]
    else:
        lines.append("    owns: []")
    if after:
        lines += ["    after:", *(f"      - {other}" for other in after)]
    else:
        lines.append("    after: []")
    if size is not None:
        lines.append(f"    size: {size}")
    lines.append(f"    vm: {'true' if vm else 'false'}")
    lines.append(f"    e2e: {'true' if e2e else 'false'}")
    if hold is None:
        lines.append("    hold: null")
    else:
        lines += ["    hold:", f"      kind: {hold[0]}", f'      reason: "{hold[1]}"']
    return lines


def _grouping(
    path: Path,
    sessions: Sequence[list[str]],
    progress: dict[str, str],
) -> Path:
    """Write a grouping file: one Session Ownership block and one progress table."""
    body = [
        "# Grouping",
        "",
        "## Session Progress",
        "",
        "Global cursor: none",
        "",
        "| Session | Status | Plan folder | Completed | Notes |",
        "|---------|--------|-------------|-----------|-------|",
        *(f"| {sid} | {status} | — | — | n |" for sid, status in progress.items()),
        "",
        "## Session Ownership",
        "",
        "```yaml",
        "sessions:",
        *(line for lines in sessions for line in lines),
        "```",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def _card(
    cards: Path,
    lane: str,
    *,
    worktree: Path,
    plan: str,
    owns: Sequence[str],
    state: str = "active",
) -> Path:
    """Write a card that ``lanes._load_card`` accepts."""
    cards.mkdir(parents=True, exist_ok=True)
    data = {
        "lane": lane,
        "generation": "0123456789abcdef",
        "session": "s-1",
        "state": state,
        "op": "land-x" if state == "landing" else None,
        "worktree": worktree.as_posix(),
        "branch": f"lane/{lane}",
        "plan": plan,
        "owns": list(owns),
        "claims": [],
        "gates": [],
        "updated": "2026-11-06T12:00:00Z",
    }
    path = cards / f"{lane}.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _task_md(top: Path, plan: str, source: str | None, session: str | None) -> Path:
    """Write ``<top>/<plan>/task.md`` with the grouping frontmatter keys given."""
    lines = ["---", 'project: "p"']
    if source is not None:
        lines.append(f'grouping_source: "{source}"')
    if session is not None:
        lines.append(f'grouping_session: "{session}"  # the session')
    lines += ['status: "in_progress"', "---", "", "# Task", ""]
    path = top / plan / "task.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _eligible(
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    groupings: Sequence[Path],
    *extra: str,
    cards: Path | None = None,
) -> dict[str, Any]:
    """The ``eligible --json`` object for ``groupings`` with an explicit cards dir."""
    argv = ["eligible", *(arg for g in groupings for arg in ("--grouping", str(g)))]
    argv += ["--repo", str(repo), "--cards-dir", str(cards or repo / "no-cards")]
    return _json(capsys, *argv, *extra)


def _excluded(data: dict[str, Any]) -> dict[str, set[str]]:
    """``excluded`` with each reason list made a set (the AC-925.6 compare)."""
    return {sid: set(reasons) for sid, reasons in data["excluded"].items()}


def _sids(data: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """Session id to ``(start, end)`` over every lane of a ``simulate`` schedule."""
    out: dict[str, tuple[float, float]] = {}
    for entries in data["schedule"].values():
        for entry in entries:
            out[entry["sid"]] = (entry["start"], entry["end"])
    return out


def _simulate_spec(
    capsys: pytest.CaptureFixture[str], spec: Path, *extra: str
) -> dict[str, Any]:
    return _json(capsys, "simulate", "--spec", str(spec), *extra)


def _simulate_groupings(
    capsys: pytest.CaptureFixture[str], groupings: Sequence[Path], *extra: str
) -> dict[str, Any]:
    argv = ["simulate", *(arg for g in groupings for arg in ("--grouping", str(g)))]
    return _json(capsys, *argv, *extra)


def _never_overlap(data: dict[str, Any], sids: Sequence[str]) -> None:
    """No two of ``sids`` run at the same time in the schedule."""
    spans = _sids(data)
    for i, a in enumerate(sids):
        for b in sids[i + 1 :]:
            (a0, a1), (b0, b1) = spans[a], spans[b]
            assert a1 <= b0 or b1 <= a0, f"{a} {spans[a]} overlaps {b} {spans[b]}"


def _snapshot(*tops: Path) -> dict[str, bytes]:
    """Every file and folder under ``tops`` (a folder maps to ``b''``)."""
    out: dict[str, bytes] = {}
    for top in tops:
        for path in sorted(top.rglob("*")):
            key = path.as_posix()
            out[key] = path.read_bytes() if path.is_file() else b""
    return out


def _scan(source: str) -> list[str]:
    """The AC-925.7 findings of ``source``: imports, process calls, project literals."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    found.append(f"import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0 and module.split(".")[0] in FORBIDDEN_IMPORTS:
                found.append(f"import:{module}")
            if node.level == 0 and module == "os":
                for alias in node.names:
                    if _process_name(alias.name):
                        found.append(f"import:os.{alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
                and _process_name(func.attr)
            ):
                found.append(f"call:os.{func.attr}")
            name = func.attr if isinstance(func, ast.Attribute) else None
            if isinstance(func, ast.Name):
                name = func.id
            if name in ("import_module", "__import__") and node.args:
                first = node.args[0]
                if (
                    isinstance(first, ast.Constant)
                    and isinstance(first.value, str)
                    and first.value.split(".")[0] in FORBIDDEN_IMPORTS
                ):
                    found.append(f"import:{first.value}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = node.value.lower()
            if PROJECT_LITERAL in low or "p:/" in low or "p:\\" in low:
                found.append(f"literal:{node.value[:40]!r}")
    return found


def _process_name(name: str) -> bool:
    return name in ("system", "popen") or name.startswith(("exec", "spawn"))


# ---------------------------------------------------------------------------
# AC-925.1 — the pure functions and the critical-path order
# ---------------------------------------------------------------------------


def test_ac_925_1_overlap_is_the_guide_rule() -> None:
    orch = _orch()
    assert orch.overlap(["tools/a.py"], ["tools/"]) == ["tools/a.py"]
    assert orch.overlap(["tools/"], ["tools/a.py"]) == ["tools/a.py"]
    assert orch.overlap(["tools/"], ["tools/"]) == ["tools/"]
    assert orch.overlap(["docs/x.md", "ui/a.ts"], ["ui/", "docs/x.md"]) == [
        "docs/x.md",
        "ui/a.ts",
    ]
    assert orch.overlap(["tools"], ["tools/a.py"]) == []
    assert orch.overlap(["tools/a.py"], ["tools/a.pyc"]) == []
    assert orch.overlap([], ["tools/"]) == []


def test_ac_925_1_must_follow_adds_same_lane_lower_tiers(tmp_path: Path) -> None:
    orch = _orch()
    spec = _spec(
        tmp_path,
        {
            "A1": _spec_session("A1", tier=1, owns=["tools/a.py"]),
            "A2": _spec_session("A2", tier=2, owns=["tools/"]),
            "A3": _spec_session("A3", tier=2, owns=["docs/"]),
            "A4": _spec_session("A4", tier=3, owns=["docs/x.md"], after=["B1"]),
            "B1": _spec_session("B1", tier=1, owns=["tools/a.py"]),
            "B2": _spec_session("B2", tier=2, owns=["tools/a.py"], after=["A3"]),
        },
    )
    lanes, sessions = orch.load_spec(spec)
    assert lanes == ["A", "B"]
    assert list(sessions) == ["A1", "A2", "A3", "A4", "B1", "B2"]
    follow = {sid: orch.must_follow(sessions[sid], sessions) for sid in sessions}
    assert follow == {
        "A1": [],
        "A2": ["A1"],
        "A3": [],
        "A4": ["A3", "B1"],
        "B1": [],
        "B2": ["A3", "B1"],
    }


def test_ac_925_1_conflicts_are_shared_owns_or_both_vm(tmp_path: Path) -> None:
    orch = _orch()
    spec = _spec(
        tmp_path,
        {
            "A1": _spec_session("A1", owns=["tools/a.py"], vm=True),
            "A2": _spec_session("A2", tier=2, owns=["tools/", "docs/"]),
            "B1": _spec_session("B1", owns=["docs/b.md"]),
            "B2": _spec_session("B2", tier=2, owns=["ui/"], vm=True),
            "C1": _spec_session("C1", owns=["ui/x.ts"]),
        },
    )
    _lanes, sessions = orch.load_spec(spec)
    a1 = orch.conflicts(sessions["A1"], sessions)
    assert set(a1) == {"A2", "B2"}
    assert a1["A2"].entries == ("tools/a.py",) and a1["A2"].vm is False
    assert a1["B2"].entries == () and a1["B2"].vm is True
    a2 = orch.conflicts(sessions["A2"], sessions)
    assert {sid: c.entries for sid, c in a2.items()} == {
        "A1": ("tools/a.py",),
        "B1": ("docs/b.md",),
    }
    c1 = orch.conflicts(sessions["C1"], sessions)
    assert {sid: (c.entries, c.vm) for sid, c in c1.items()} == {
        "B2": (("ui/x.ts",), False)
    }


def test_ac_925_1_critical_path_beats_number_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(
        tmp_path,
        {
            "A1": _spec_session("A1"),
            "A2": _spec_session("A2"),
            "B1": _spec_session("B1", size="large", after=["A2"]),
        },
    )
    guide = _simulate_spec(capsys, spec, "--order", "guide")
    assert guide["order"] == "guide"
    assert _sids(guide) == {"A1": (0.0, 1.0), "A2": (1.0, 2.0), "B1": (2.0, 5.0)}
    assert guide["makespan"] == 5.0
    critical = _simulate_spec(capsys, spec, "--order", "critical-path")
    assert _sids(critical) == {"A2": (0.0, 1.0), "A1": (1.0, 2.0), "B1": (1.0, 4.0)}
    assert critical["makespan"] == 4.0
    default = _simulate_spec(capsys, spec)
    assert default["order"] == "critical-path"
    assert default["makespan"] == 4.0


def test_ac_925_1_ties_break_by_lane_then_number(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(
        tmp_path,
        {
            "B1": _spec_session("B1"),
            "A10": _spec_session("A10"),
            "A2b": _spec_session("A2b"),
            "A2": _spec_session("A2"),
            "A9": _spec_session("A9"),
        },
        lanes=["A", "B"],
    )
    data = _simulate_spec(capsys, spec, "--trees", "main")
    spans = _sids(data)
    assert sorted(spans, key=lambda sid: spans[sid][0]) == [
        "A2",
        "A2b",
        "A9",
        "A10",
        "B1",
    ]
    assert data["makespan"] == 5.0


def test_ac_925_1_longer_chain_ranks_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(
        tmp_path,
        {
            "A1": _spec_session("A1", size="medium"),
            "A2": _spec_session("A2"),
            "A3": _spec_session("A3", size="small-to-medium", after=["A2"]),
            "A4": _spec_session("A4", size="medium-to-large", after=["A3"]),
        },
    )
    data = _simulate_spec(capsys, spec)
    spans = _sids(data)
    assert sorted(spans, key=lambda sid: spans[sid][0]) == ["A2", "A3", "A4", "A1"]
    assert spans["A4"] == (2.5, 5.0)
    assert data["makespan"] == 7.0


# ---------------------------------------------------------------------------
# AC-925.2 — the guide numbers and the fixture input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(GUIDE_NUMBERS))
def test_ac_925_2_guide_numbers(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    extra, number = GUIDE_NUMBERS[name]
    data = _simulate_spec(capsys, FIXTURE, *extra)
    assert data["makespan"] == number
    assert data["caps_not_modeled"] == CAPS_NOT_MODELED
    assert data["held"] == {}


def test_ac_925_2_fixture_holds_every_guide_session(
    capsys: pytest.CaptureFixture[str],
) -> None:
    orch = _orch()
    lanes, sessions = orch.load_spec(FIXTURE)
    assert lanes == ["UF", "PE", "RX"]
    assert {s.lane for s in sessions.values()} == {"UF", "PE", "RX"}
    data = _simulate_spec(capsys, FIXTURE, "--order", "guide")
    assert set(_sids(data)) == set(sessions)
    assert set(data["schedule"]) == {"UF", "PE", "RX"}


def test_ac_925_2_script_entry_point() -> None:
    _orch()
    proc = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(ORCH),
            "simulate",
            "--spec",
            str(FIXTURE),
            "--order",
            "guide",
            "--json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert json.loads(proc.stdout)["makespan"] == 53.5


def test_ac_925_2_size_missing_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sessions = {"A1": _spec_session("A1"), "A2": _spec_session("A2")}
    del sessions["A2"]["size"]
    spec = _spec(tmp_path, sessions)
    assert _refusal(capsys, "simulate", "--spec", str(spec)) == "simulate_bad:size:A2"
    grouping = _grouping(
        tmp_path / "g.md",
        [_block_lines("A1"), _block_lines("A2", tier=2, size=None)],
        {"A1": "pending", "A2": "pending"},
    )
    assert (
        _refusal(capsys, "simulate", "--grouping", str(grouping))
        == "simulate_bad:size:A2"
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("size", "huge", "simulate_bad:size:A1"),
        ("tier", 0, "simulate_bad:tier:A1"),
        ("tier", True, "simulate_bad:tier:A1"),
        ("owns", "tools/", "simulate_bad:owns:A1"),
        ("after", "A2", "simulate_bad:after:A1"),
        ("vm", "no", "simulate_bad:vm:A1"),
        ("lane", "Q", "simulate_bad:lane:A1"),
        ("color", "red", "simulate_bad:key:A1:color"),
    ],
)
def test_ac_925_2_bad_spec_value_is_refused(
    field: str,
    value: object,
    reason: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sessions = {"A1": _spec_session("A1"), "A2": _spec_session("A2")}
    sessions["A1"][field] = value
    spec = _spec(tmp_path, sessions, lanes=["A"])
    assert _refusal(capsys, "simulate", "--spec", str(spec)) == reason


def test_ac_925_2_bad_spec_schema_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "spec.json"
    path.write_text(
        json.dumps({"schema": "orch-spec/9", "lanes": ["A"], "sessions": {}}),
        encoding="utf-8",
    )
    assert _refusal(capsys, "simulate", "--spec", str(path)).startswith(
        "simulate_bad:spec:"
    )
    path.write_text("{", encoding="utf-8")
    assert _refusal(capsys, "simulate", "--spec", str(path)).startswith(
        "simulate_bad:spec:"
    )


def test_ac_925_2_bad_session_id_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(tmp_path, {"a1": _spec_session("A1")}, lanes=["A"])
    assert _refusal(capsys, "simulate", "--spec", str(spec)) == "simulate_bad:sid:a1"
    grouping = _grouping(tmp_path / "g.md", [_block_lines("a1")], {"a1": "pending"})
    assert (
        _refusal(capsys, "simulate", "--grouping", str(grouping))
        == "simulate_bad:sid:a1"
    )


def test_ac_925_2_spec_and_grouping_are_exclusive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(tmp_path, {"A1": _spec_session("A1")})
    grouping = _grouping(tmp_path / "g.md", [_block_lines("A1")], {"A1": "pending"})
    code, _out, _err = _run(
        capsys, "simulate", "--spec", str(spec), "--grouping", str(grouping)
    )
    assert code == 2
    code, _out, _err = _run(capsys, "simulate")
    assert code == 2


# ---------------------------------------------------------------------------
# AC-925.3 — the limits the guide does not model, and the resources records
# ---------------------------------------------------------------------------


def test_ac_925_3_vm_limit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    both = _spec(
        tmp_path,
        {"A1": _spec_session("A1", vm=True), "B1": _spec_session("B1", vm=True)},
        name="vm.json",
    )
    data = _simulate_spec(capsys, both)
    assert data["makespan"] == 2.0
    _never_overlap(data, ["A1", "B1"])
    one = _spec(
        tmp_path,
        {"A1": _spec_session("A1", vm=True), "B1": _spec_session("B1")},
        name="one.json",
    )
    assert _simulate_spec(capsys, one)["makespan"] == 1.0


def test_ac_925_3_e2e_limit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    both = [
        _grouping(tmp_path / "a.md", [_block_lines("A1", e2e=True)], {"A1": "pending"}),
        _grouping(tmp_path / "b.md", [_block_lines("B1", e2e=True)], {"B1": "pending"}),
    ]
    data = _simulate_groupings(capsys, both)
    assert data["makespan"] == 2.0
    _never_overlap(data, ["A1", "B1"])
    one = [
        _grouping(tmp_path / "c.md", [_block_lines("C1", e2e=True)], {"C1": "pending"}),
        _grouping(tmp_path / "d.md", [_block_lines("D1")], {"D1": "pending"}),
    ]
    assert _simulate_groupings(capsys, one)["makespan"] == 1.0


def test_ac_925_3_hold_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    groupings = [
        _grouping(
            tmp_path / "a.md",
            [
                _block_lines("A1", hold=("human", "wait for the ruling")),
                _block_lines("A2", tier=2, after=["A1"]),
            ],
            {"A1": "pending", "A2": "pending"},
        ),
        _grouping(
            tmp_path / "b.md",
            [_block_lines("B1"), _block_lines("B2", tier=2, after=["A2"])],
            {"B1": "pending", "B2": "pending"},
        ),
    ]
    data = _simulate_groupings(capsys, groupings)
    assert data["held"] == {
        "A1": ["hold:human:wait for the ruling"],
        "A2": ["after:A1"],
        "B2": ["after:A2"],
    }
    assert set(_sids(data)) == {"B1"}
    assert data["makespan"] == 1.0


def test_ac_925_3_workers_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(
        tmp_path,
        {sid: _spec_session(sid) for sid in ("A1", "B1", "C1")},
    )
    assert _simulate_spec(capsys, spec)["makespan"] == 1.0
    capped = _simulate_spec(capsys, spec, "--workers", "2")
    assert capped["workers"] == 2
    assert capped["makespan"] == 2.0
    code, _out, _err = _run(capsys, "simulate", "--spec", str(spec), "--workers", "0")
    assert code == 2


def test_ac_925_3_trees_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(
        tmp_path,
        {sid: _spec_session(sid) for sid in ("A1", "A2", "B1", "C1")},
    )
    lanes = _simulate_spec(capsys, spec, "--executors", "2")
    assert lanes["trees"] == "lanes"
    assert lanes["makespan"] == 1.0
    main = _simulate_spec(capsys, spec, "--trees", "main", "--executors", "2")
    assert main["trees"] == "main"
    assert main["makespan"] == 4.0
    _never_overlap(main, ["A1", "A2", "B1", "C1"])


def test_ac_925_3_borrow_lane(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = _spec(
        tmp_path,
        {sid: _spec_session(sid) for sid in ("A1", "A2", "A3")},
        lanes=["A", "B"],
    )
    assert _simulate_spec(capsys, spec)["makespan"] == 3.0
    borrowed = _simulate_spec(capsys, spec, "--borrow", "B")
    assert borrowed["borrow"] == "B"
    assert borrowed["makespan"] == 2.0
    assert len(borrowed["schedule"]["B"]) == 1
    assert (
        _refusal(capsys, "simulate", "--spec", str(spec), "--borrow", "Q")
        == "simulate_bad:borrow:Q"
    )


def test_ac_925_3_caps_not_modeled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    orch = _orch()
    assert tuple(orch.CAPS_NOT_MODELED) == tuple(CAPS_NOT_MODELED)
    spec = _spec(tmp_path, {"A1": _spec_session("A1")})
    data = _simulate_spec(capsys, spec)
    assert data["caps_not_modeled"] == CAPS_NOT_MODELED
    assert {
        "makespan",
        "order",
        "executors",
        "trees",
        "borrow",
        "workers",
        "schedule",
        "held",
        "caps_not_modeled",
    } <= set(data)
    assert data["workers"] is None and data["borrow"] is None


def test_ac_925_3_resources_record_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    grouping = _grouping(
        repo / "g.md",
        [_block_lines("A1", vm=True), _block_lines("A2", tier=2)],
        {"A1": "in-progress", "A2": "pending"},
    )
    full = _eligible(capsys, repo, [grouping], "--reviews-running", "3")
    resources = full["resources"]
    assert set(resources) == RESOURCE_NAMES
    for name, record in resources.items():
        assert set(record) == RECORD_KEYS
        assert record["limit_name"] == name
        assert record["window"] == "concurrent"
    assert resources["reviews"] == {
        "limit_name": "reviews",
        "configured_value": 3,
        "observed_value": 3,
        "window": "concurrent",
        "free": 0,
    }
    assert full["can_dispatch_review"] is False
    assert full["can_plan_commit"] is True
    assert resources["plan_commits"]["configured_value"] == 1
    assert resources["plan_commits"]["free"] == 1
    assert resources["workers"]["configured_value"] is None
    assert resources["workers"]["free"] is None
    assert resources["workers"]["observed_value"] == 1
    assert resources["vm"] == {
        "limit_name": "vm",
        "configured_value": 1,
        "observed_value": 1,
        "window": "concurrent",
        "free": 0,
    }
    assert resources["e2e"]["observed_value"] == 0
    assert resources["e2e"]["free"] == 1
    assert resources["trees"]["configured_value"] == 1
    assert resources["trees"]["observed_value"] == 1
    assert resources["trees"]["free"] == 0
    other = _eligible(
        capsys,
        repo,
        [grouping],
        "--reviews-running",
        "1",
        "--plan-commits-running",
        "1",
        "--workers",
        "4",
        "--trees",
        "lanes",
    )
    assert other["can_dispatch_review"] is True
    assert other["resources"]["reviews"]["free"] == 2
    assert other["can_plan_commit"] is False
    assert other["resources"]["plan_commits"]["free"] == 0
    assert other["resources"]["workers"]["configured_value"] == 4
    assert other["resources"]["workers"]["free"] == 3
    assert other["resources"]["trees"]["configured_value"] == 1
    code, _out, _err = _run(
        capsys,
        "eligible",
        "--grouping",
        str(grouping),
        "--repo",
        str(repo),
        "--reviews-running",
        "-1",
    )
    assert code == 2


# ---------------------------------------------------------------------------
# AC-925.4 — eligible: the reasons, the cards, the status vocabulary
# ---------------------------------------------------------------------------


def test_ac_925_4_reasons_for_each_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    groupings = [
        _grouping(
            repo / "x.md",
            [
                _block_lines("X1", owns=["docs/x1/"]),
                _block_lines("X2", owns=["tools/x.py"], vm=True),
                _block_lines("X3", tier=2, owns=["docs/x3/"], after=["X1"]),
                _block_lines("X4", tier=2, owns=["docs/x4/"]),
            ],
            {"X1": "done", "X2": "in-progress", "X3": "pending", "X4": "blocked — KI"},
        ),
        _grouping(
            repo / "y.md",
            [
                _block_lines("Y1", owns=["tools/"]),
                _block_lines("Y2", tier=2, owns=["docs/y2/"], vm=True),
                _block_lines("Y3", tier=3, owns=["docs/y3/"], after=["X3"]),
            ],
            {"Y1": "pending", "Y2": "pending", "Y3": "pending"},
        ),
        _grouping(
            repo / "z.md",
            [
                _block_lines("Z1", owns=["docs/z1/"], e2e=True),
                _block_lines("Z2", tier=2, owns=["docs/z2/"], e2e=True),
            ],
            {"Z1": "in-progress", "Z2": "split"},
        ),
        _grouping(
            repo / "w.md",
            [_block_lines("W1", owns=["ui/w/"], e2e=True)],
            {"W1": "▶ NEXT"},
        ),
    ]
    data = _eligible(capsys, repo, groupings, "--trees", "lanes")
    assert data["eligible"] == []
    assert sorted(data["running"]) == ["X2", "Z1"]
    assert _excluded(data) == {
        "X3": {"lane_busy"},
        "X4": {"status:blocked"},
        "Y1": {"conflict:X2:tools/x.py"},
        "Y2": {"vm_busy"},
        "Y3": {"after:X3"},
        "Z2": {"status:split"},
        "W1": {"e2e_busy"},
    }


def test_ac_925_4_done_and_skipped_satisfy_after(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    grouping = _grouping(
        repo / "a.md",
        [
            _block_lines("A1"),
            _block_lines("A2"),
            _block_lines("A3", tier=2, after=["A1", "A2"]),
            _block_lines("A4", tier=2, after=["A5"]),
            _block_lines("A5"),
        ],
        {
            "A1": "done (MEU-1 only) · split at row 1-CP",
            "A2": "skipped — split into A9",
            "A3": "pending",
            "A4": "pending",
            "A5": "blocked",
        },
    )
    data = _eligible(capsys, repo, [grouping])
    assert data["eligible"] == ["A3"]
    assert _excluded(data) == {
        "A4": {"after:A5", "lane_busy", "tree_busy"},
        "A5": {"status:blocked"},
    }


def test_ac_925_4_tree_busy_under_main(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    groupings = [
        _grouping(
            repo / "a.md", [_block_lines("A1", owns=["a/"])], {"A1": "in-progress"}
        ),
        _grouping(repo / "b.md", [_block_lines("B1", owns=["b/"])], {"B1": "pending"}),
    ]
    main = _eligible(capsys, repo, groupings)
    assert main["eligible"] == []
    assert _excluded(main) == {"B1": {"tree_busy"}}
    lanes = _eligible(capsys, repo, groupings, "--trees", "lanes")
    assert lanes["eligible"] == ["B1"]
    assert lanes["excluded"] == {}


def test_ac_925_4_cap_workers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    groupings = [
        _grouping(
            repo / "a.md", [_block_lines("A1", owns=["a/"])], {"A1": "in-progress"}
        ),
        _grouping(repo / "b.md", [_block_lines("B1", owns=["b/"])], {"B1": "pending"}),
        _grouping(repo / "c.md", [_block_lines("C1", owns=["c/"])], {"C1": "pending"}),
    ]
    data = _eligible(capsys, repo, groupings, "--trees", "lanes", "--workers", "2")
    assert data["eligible"] == ["B1"]
    assert _excluded(data) == {"C1": {"cap:workers"}}
    free = _eligible(capsys, repo, groupings, "--trees", "lanes")
    assert free["eligible"] == ["B1", "C1"]


def test_ac_925_4_selection_is_critical_path_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    groupings = [
        _grouping(repo / "a.md", [_block_lines("A1", owns=["a/"])], {"A1": "pending"}),
        _grouping(
            repo / "b.md",
            [
                _block_lines("B1", owns=["b/"]),
                _block_lines("B2", tier=2, owns=["b2/"], after=["B1"], size="large"),
            ],
            {"B1": "pending", "B2": "pending"},
        ),
    ]
    lanes = _eligible(capsys, repo, groupings, "--trees", "lanes")
    assert lanes["eligible"] == ["B1", "A1"]
    assert _excluded(lanes) == {"B2": {"after:B1", "lane_busy"}}
    main = _eligible(capsys, repo, groupings)
    assert main["eligible"] == ["B1"]
    assert _excluded(main) == {
        "A1": {"tree_busy"},
        "B2": {"after:B1", "lane_busy", "tree_busy"},
    }


def test_ac_925_4_unknown_status_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    for status in ("paused", "Done", "in-progress now", "doneish"):
        grouping = _grouping(
            repo / "a.md",
            [_block_lines("A1"), _block_lines("A2")],
            {"A1": "pending", "A2": status},
        )
        reason = _refusal(
            capsys,
            "eligible",
            "--grouping",
            str(grouping),
            "--repo",
            str(repo),
            "--cards-dir",
            str(repo / "cards"),
        )
        assert reason == f"eligible_bad:status:A2:{status}"


def test_ac_925_4_progress_must_match_the_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    missing = _grouping(
        repo / "a.md", [_block_lines("A1"), _block_lines("A2")], {"A1": "pending"}
    )
    argv = ["--repo", str(repo), "--cards-dir", str(repo / "cards")]
    assert (
        _refusal(capsys, "eligible", "--grouping", str(missing), *argv)
        == "eligible_bad:progress:A2"
    )
    extra = _grouping(
        repo / "b.md", [_block_lines("B1")], {"B1": "pending", "B2": "pending"}
    )
    assert (
        _refusal(capsys, "eligible", "--grouping", str(extra), *argv)
        == "eligible_bad:progress:B2"
    )


def test_ac_925_4_reserving_card_maps_to_its_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    cards = tmp_path / "cards"
    grouping = _grouping(
        repo / "groupings" / "a.md",
        [
            _block_lines("A1", owns=["docs/a1/"]),
            _block_lines("A2", owns=["tools/a.py"]),
            _block_lines("A3", tier=2, owns=["docs/a3/"]),
        ],
        {"A1": "done", "A2": "pending", "A3": "pending"},
    )
    other = _grouping(
        repo / "groupings" / "b.md",
        [
            _block_lines("B1", owns=["tools/"]),
            _block_lines("B2", tier=2, owns=["ui/x.ts"]),
            _block_lines("B3", tier=3, owns=["docs/extra/b3.md"]),
            _block_lines("B4", tier=4, owns=["docs/b4/"]),
        ],
        {"B1": "pending", "B2": "pending", "B3": "pending", "B4": "pending"},
    )
    worktree = tmp_path / "wt-a2"
    _task_md(worktree, "plans/p-a2/", "groupings/a.md", "A2")
    _card(
        cards,
        "lane-a2",
        worktree=worktree,
        plan="plans/p-a2/",
        owns=["tools/a.py", "docs/extra/"],
    )
    _task_md(repo, "plans/p-ui/", None, None)
    _card(
        cards, "lane-ui", worktree=tmp_path / "wt-ui", plan="plans/p-ui/", owns=["ui/"]
    )
    _task_md(repo, "plans/p-old/", "groupings/b.md", "B4")
    _card(
        cards,
        "lane-old",
        worktree=tmp_path / "wt-old",
        plan="plans/p-old/",
        owns=["docs/b4/"],
        state="released",
    )
    data = _eligible(capsys, repo, [grouping, other], "--trees", "lanes", cards=cards)
    assert data["running"] == ["A2"]
    assert data["eligible"] == ["B4"]
    assert _excluded(data) == {
        "A3": {"lane_busy"},
        "B1": {"conflict:A2:tools/a.py"},
        "B2": {"conflict:lane-ui:ui/x.ts"},
        "B3": {"conflict:A2:docs/extra/b3.md"},
    }


def test_ac_925_4_landing_card_on_the_repo_top_busies_the_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    common = repo / ".git"
    grouping = _grouping(
        repo / "a.md", [_block_lines("A1", owns=["a/"])], {"A1": "pending"}
    )
    _task_md(repo, "plans/p-x/", None, None)
    _card(
        common / "lanes",
        "lane-x",
        worktree=repo,
        plan="plans/p-x/",
        owns=["docs/x/"],
        state="landing",
    )
    (common / "lanes" / "ref-guard.json").write_text("{}", encoding="utf-8")
    data = _json(capsys, "eligible", "--grouping", str(grouping), "--repo", str(repo))
    assert data["eligible"] == []
    assert _excluded(data) == {"A1": {"tree_busy"}}
    assert data["resources"]["trees"]["observed_value"] == 1


def test_ac_925_4_cards_dir_follows_a_gitdir_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    common = tmp_path / "main.git"
    gitdir = common / "worktrees" / "repo"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    repo.mkdir()
    (repo / ".git").write_text(f"gitdir: {gitdir.as_posix()}\n", encoding="utf-8")
    grouping = _grouping(
        repo / "a.md", [_block_lines("A1", owns=["ui/a.ts"])], {"A1": "pending"}
    )
    _task_md(repo, "plans/p-ui/", None, None)
    _card(
        common / "lanes",
        "lane-ui",
        worktree=tmp_path / "wt",
        plan="plans/p-ui/",
        owns=["ui/"],
    )
    data = _json(
        capsys,
        "eligible",
        "--grouping",
        str(grouping),
        "--repo",
        str(repo),
        "--trees",
        "lanes",
    )
    assert _excluded(data) == {"A1": {"conflict:lane-ui:ui/a.ts"}}
    norepo = tmp_path / "plain"
    norepo.mkdir()
    reason = _refusal(
        capsys, "eligible", "--grouping", str(grouping), "--repo", str(norepo)
    )
    assert reason.startswith("eligible_bad:repo:")


@pytest.mark.parametrize("case", ["json", "no_task", "unknown_session"])
def test_ac_925_4_bad_card_fails_closed(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    cards = tmp_path / "cards"
    grouping = _grouping(repo / "a.md", [_block_lines("A1")], {"A1": "pending"})
    if case == "json":
        cards.mkdir()
        (cards / "lane-bad.json").write_text("{", encoding="utf-8")
    elif case == "no_task":
        _card(cards, "lane-bad", worktree=tmp_path / "wt", plan="plans/none/", owns=[])
    else:
        _task_md(repo, "plans/p-q/", "a.md", "A7")
        _card(cards, "lane-bad", worktree=tmp_path / "wt", plan="plans/p-q/", owns=[])
    reason = _refusal(
        capsys,
        "eligible",
        "--grouping",
        str(grouping),
        "--repo",
        str(repo),
        "--cards-dir",
        str(cards),
    )
    assert reason == "eligible_bad:card:lane-bad.json"


def test_ac_925_4_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    cards = tmp_path / "cards"
    grouping = _grouping(
        repo / "a.md",
        [_block_lines("A1", owns=["a/"]), _block_lines("A2", tier=2, owns=["b/"])],
        {"A1": "in-progress", "A2": "pending"},
    )
    _task_md(repo, "plans/p-a1/", "a.md", "A1")
    _card(cards, "lane-a1", worktree=repo, plan="plans/p-a1/", owns=["a/"])
    before = _snapshot(repo, cards)
    _eligible(capsys, repo, [grouping], cards=cards)
    _eligible(capsys, repo, [grouping], "--trees", "lanes", cards=cards)
    code, _out, _err = _run(
        capsys,
        "eligible",
        "--grouping",
        str(grouping),
        "--repo",
        str(repo),
        "--cards-dir",
        str(cards),
    )
    assert code == 0
    assert _snapshot(repo, cards) == before


def test_ac_925_4_hold_blocks_ready_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    grouping = _grouping(
        repo / "ao.md",
        [
            _block_lines("AO3", tier=3, owns=["tools/orch.py"]),
            _block_lines(
                "AO4",
                tier=4,
                owns=["tools/orch.py", "tools/orch_tick.py"],
                after=["AO3"],
                size="large",
                hold=("human", HOLD_REASON),
            ),
            _block_lines("AO5", tier=5, owns=["tools/orch_tick.py"], after=["AO4"]),
        ],
        {"AO3": "done", "AO4": "pending", "AO5": "pending"},
    )
    data = _eligible(capsys, repo, [grouping])
    assert "AO4" not in data["eligible"]
    assert data["eligible"] == []
    assert _excluded(data) == {
        "AO4": {f"hold:human:{HOLD_REASON}"},
        "AO5": {"after:AO4"},
    }


# ---------------------------------------------------------------------------
# AC-925.4 — live ownership uses the lanes.py rules (EA-8, review R1-F1)
#
# A busy session and a reserving card collide as ``lanes.py`` admits a lane: NFC
# text, case-folded when the repository's ``core.ignorecase`` is true, and
# component-aware (``lanes._overlaps``). ``eligible`` reads ``core.ignorecase``
# from the config file of the git common dir, because it starts no process
# (AC-925.7). The guide rule (``overlap``) stays for ``must_follow`` and replay.
# ---------------------------------------------------------------------------

CASE_CONFIGS = [
    ("[core]\n\tignorecase = true\n", True),
    ("[Core]\n\tignoreCase = yes\n", True),
    ("[core]\n\tignorecase\n", True),
    ("[core]\n\tignorecase = 1 ; set by git init\n", True),
    ('[core]\n\tignorecase = "on"\n', True),
    ("[core]\n\tignorecase = false\n[core]\n\tignorecase = true\n", True),
    ("[core]\n\tignorecase = true\n\tignorecase = off\n", False),
    ("[core]\n\tignorecase = false\n", False),
    ("[core]\n\tignorecase =\n", False),
    ('[core "x"]\n\tignorecase = true\n', False),
    ("[user]\n\tname = n\n", False),
    (None, False),
]


def _case_repo(tmp_path: Path, config: str | None) -> Path:
    """A repository top whose ``.git/config`` holds ``config`` (no file for None)."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    if config is not None:
        (repo / ".git" / "config").write_text(config, encoding="utf-8")
    return repo


def _loose_card(repo: Path, tmp_path: Path, owns: Sequence[str]) -> None:
    """An ``active`` card ``other`` in ``<repo>/.git/lanes`` that maps to no session."""
    _task_md(repo, "plans/other/", None, None)
    _card(
        repo / ".git" / "lanes",
        "other",
        worktree=tmp_path / "wt-other",
        plan="plans/other/",
        owns=owns,
    )


@pytest.mark.parametrize(("config", "folds"), CASE_CONFIGS)
def test_ac_925_4_reservation_follows_the_repo_case_rule(
    config: str | None,
    folds: bool,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _case_repo(tmp_path, config)
    grouping = _grouping(
        repo / "a.md", [_block_lines("A1", owns=["tools/a.py"])], {"A1": "pending"}
    )
    _loose_card(repo, tmp_path, ["Tools/"])
    data = _json(
        capsys,
        "eligible",
        "--grouping",
        str(grouping),
        "--repo",
        str(repo),
        "--trees",
        "lanes",
    )
    if folds:
        assert data["eligible"] == []
        assert _excluded(data) == {"A1": {"conflict:other:tools/a.py"}}
    else:
        assert data["eligible"] == ["A1"]
        assert _excluded(data) == {}


def test_ac_925_4_case_rule_follows_a_gitdir_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    common = tmp_path / "main.git"
    gitdir = common / "worktrees" / "repo"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    (common / "config").write_text("[core]\n\tignorecase = true\n", encoding="utf-8")
    repo.mkdir()
    (repo / ".git").write_text(f"gitdir: {gitdir.as_posix()}\n", encoding="utf-8")
    grouping = _grouping(
        repo / "a.md", [_block_lines("A1", owns=["ui/a.ts"])], {"A1": "pending"}
    )
    _task_md(repo, "plans/p-ui/", None, None)
    _card(
        common / "lanes",
        "lane-ui",
        worktree=tmp_path / "wt",
        plan="plans/p-ui/",
        owns=["UI/"],
    )
    data = _json(
        capsys,
        "eligible",
        "--grouping",
        str(grouping),
        "--repo",
        str(repo),
        "--trees",
        "lanes",
    )
    assert _excluded(data) == {"A1": {"conflict:lane-ui:ui/a.ts"}}


def test_ac_925_4_bad_case_config_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _case_repo(tmp_path, "[core]\n\tignorecase = maybe\n")
    grouping = _grouping(
        repo / "a.md", [_block_lines("A1", owns=["tools/a.py"])], {"A1": "pending"}
    )
    reason = _refusal(
        capsys, "eligible", "--grouping", str(grouping), "--repo", str(repo)
    )
    assert reason == "eligible_bad:repo:git_config"


@pytest.mark.parametrize("folds", [True, False])
def test_ac_925_4_busy_and_mapped_entries_follow_the_case_rule(
    folds: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _case_repo(tmp_path, f"[core]\n\tignorecase = {str(folds).lower()}\n")
    first = _grouping(
        repo / "a.md", [_block_lines("A1", owns=["Docs/a/"])], {"A1": "in-progress"}
    )
    second = _grouping(
        repo / "b.md", [_block_lines("B1", owns=["docs/a/x.md"])], {"B1": "pending"}
    )
    third = _grouping(
        repo / "c.md", [_block_lines("C1", owns=["ui/x.ts"])], {"C1": "pending"}
    )
    worktree = tmp_path / "wt-a1"
    _task_md(worktree, "plans/p-a1/", "a.md", "A1")
    _card(
        repo / ".git" / "lanes",
        "lane-a1",
        worktree=worktree,
        plan="plans/p-a1/",
        owns=["UI/"],
    )
    argv = ["eligible", "--repo", str(repo), "--trees", "lanes"]
    for path in (first, second, third):
        argv += ["--grouping", str(path)]
    data = _json(capsys, *argv)
    assert data["running"] == ["A1"]
    if folds:
        assert data["eligible"] == []
        assert _excluded(data) == {
            "B1": {"conflict:A1:docs/a/x.md"},
            "C1": {"conflict:A1:ui/x.ts"},
        }
    else:
        assert sorted(data["eligible"]) == ["B1", "C1"]
        assert _excluded(data) == {}


@pytest.mark.parametrize(
    ("card_entry", "session_entry"),
    [("docs/café/", "docs/café/x.md"), ("docs/café/", "docs/café/x.md")],
)
def test_ac_925_4_reservation_compares_nfc_text(
    card_entry: str,
    session_entry: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _case_repo(tmp_path, None)
    grouping = _grouping(
        repo / "a.md", [_block_lines("A1", owns=[session_entry])], {"A1": "pending"}
    )
    _loose_card(repo, tmp_path, [card_entry])
    data = _json(
        capsys,
        "eligible",
        "--grouping",
        str(grouping),
        "--repo",
        str(repo),
        "--trees",
        "lanes",
    )
    assert data["eligible"] == []
    assert _excluded(data) == {"A1": {f"conflict:other:{session_entry}"}}


@pytest.mark.parametrize(
    ("card_entry", "session_entry", "hit"),
    [
        ("tools", "tools/a.py", "tools/a.py"),
        ("docs", "docs/", "docs/"),
        ("docs/a.md", "docs/a.md", "docs/a.md"),
        ("tools/a", "tools/ab.py", None),
        ("tools/a.py", "tools/a.pyc", None),
        ("tools/", "toolsx/a.py", None),
    ],
)
def test_ac_925_4_reservation_is_component_aware(
    card_entry: str,
    session_entry: str,
    hit: str | None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _case_repo(tmp_path, None)
    grouping = _grouping(
        repo / "a.md", [_block_lines("A1", owns=[session_entry])], {"A1": "pending"}
    )
    _loose_card(repo, tmp_path, [card_entry])
    data = _json(
        capsys,
        "eligible",
        "--grouping",
        str(grouping),
        "--repo",
        str(repo),
        "--trees",
        "lanes",
    )
    if hit is None:
        assert data["eligible"] == ["A1"]
        assert _excluded(data) == {}
    else:
        assert data["eligible"] == []
        assert _excluded(data) == {"A1": {f"conflict:other:{hit}"}}


def test_ac_925_4_guide_rule_stays_for_order_and_replay(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    orch = _orch()
    assert orch.overlap(["Tools/"], ["tools/a.py"]) == []
    assert orch.overlap(["tools"], ["tools/a.py"]) == []
    assert orch.overlap(["tools/"], ["tools/a.py"]) == ["tools/a.py"]
    first = orch.Session("A1", "A", "g", "small", 1, ("Tools/",), ())
    second = orch.Session("A2", "A", "g", "small", 2, ("tools/a.py",), ())
    assert orch.must_follow(second, {"A1": first, "A2": second}) == []
    repo = _case_repo(tmp_path, "[core]\n\tignorecase = true\n")
    grouping = _grouping(
        repo / "a.md",
        [
            _block_lines("A1", owns=["Tools/"]),
            _block_lines("A2", tier=2, owns=["tools/a.py"]),
        ],
        {"A1": "pending", "A2": "pending"},
    )
    data = _json(
        capsys,
        "eligible",
        "--grouping",
        str(grouping),
        "--repo",
        str(repo),
        "--trees",
        "lanes",
    )
    assert data["eligible"] == ["A1"]
    assert _excluded(data) == {"A2": {"lane_busy", "conflict:A1:tools/a.py"}}


# ---------------------------------------------------------------------------
# AC-925.4 — ``size`` is optional for ``eligible`` (EA-9, review R2-F2)
#
# Every Session Ownership key is optional (report §8.1; the plan row "Defaults
# when a key is absent"). Only ``simulate`` needs ``size``, because it weights the
# schedule with it: a session with no ``size`` is ``simulate_bad:size:<sid>``
# (AC-924.5, ``session-grouping.md`` B2a). ``eligible`` reads such a session as a
# candidate and puts no limit on it. In the critical-path order, a session with no
# ``size`` adds 0 to a chain, and the stated sizes of the chain still count.
# ---------------------------------------------------------------------------

LEGACY_A1 = ["  A1:", "    tier: 1", "    owns: []"]


def test_ac_925_4_block_with_no_size_is_a_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    orch = _orch()
    repo = _case_repo(tmp_path, "[core]\n\tignorecase = false\n")
    grouping = _grouping(repo / "a.md", [LEGACY_A1], {"A1": "pending"})
    data = _eligible(capsys, repo, [grouping])
    assert data["eligible"] == ["A1"]
    assert data["excluded"] == {}
    _lanes, sessions = orch.load_groupings([grouping])
    assert sessions["A1"].size is None
    assert sessions["A1"].tier == 1
    assert sessions["A1"].owns == ()


def test_ac_925_4_mixed_blocks_keep_the_stated_size_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _case_repo(tmp_path, None)
    grouping = _grouping(
        repo / "a.md",
        [
            ["  C1:", "    tier: 1", "    owns: []"],
            _block_lines("A1", size="small"),
            _block_lines("B1", size="large"),
        ],
        {"C1": "pending", "A1": "pending", "B1": "pending"},
    )
    data = _eligible(capsys, repo, [grouping], "--trees", "lanes")
    assert data["eligible"] == ["B1", "A1", "C1"]
    assert data["excluded"] == {}


def test_ac_925_4_no_size_adds_nothing_to_a_chain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _case_repo(tmp_path, None)
    grouping = _grouping(
        repo / "a.md",
        [
            ["  A1:", "    tier: 1", "    owns:", "      - x/"],
            _block_lines("A2", tier=2, owns=["x/a.py"], size="large"),
            _block_lines("B1", size="medium"),
            ["  C1:", "    tier: 1", "    owns: []"],
        ],
        {"A1": "pending", "A2": "pending", "B1": "pending", "C1": "pending"},
    )
    data = _eligible(capsys, repo, [grouping])
    assert data["eligible"] == ["A1"]
    assert _excluded(data) == {
        "A2": {"after:A1", "lane_busy", "tree_busy", "conflict:A1:x/a.py"},
        "B1": {"tree_busy"},
        "C1": {"tree_busy"},
    }


def test_ac_925_2_simulate_still_needs_size(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _case_repo(tmp_path, None)
    legacy = _grouping(repo / "a.md", [LEGACY_A1], {"A1": "pending"})
    assert (
        _refusal(capsys, "simulate", "--grouping", str(legacy))
        == "simulate_bad:size:A1"
    )
    mixed = _grouping(
        repo / "b.md",
        [_block_lines("B1", size="large"), ["  B2:", "    tier: 2", "    owns: []"]],
        {"B1": "pending", "B2": "pending"},
    )
    assert (
        _refusal(capsys, "simulate", "--grouping", str(mixed)) == "simulate_bad:size:B2"
    )
    data = _eligible(capsys, repo, [mixed])
    assert data["eligible"] == ["B1"]
    assert _excluded(data) == {"B2": {"lane_busy", "tree_busy"}}


def test_ac_925_1_no_size_weighs_zero_in_a_chain() -> None:
    orch = _orch()
    first = orch.Session("A1", "A", "g", None, 1, ("x/",), ())
    second = orch.Session("A2", "A", "g", "large", 2, ("x/a.py",), ())
    sessions = {"A1": first, "A2": second}
    follow = {sid: orch.must_follow(s, sessions) for sid, s in sessions.items()}
    assert follow == {"A1": [], "A2": ["A1"]}
    assert orch.critical_path(sessions, follow) == {"A1": 3.0, "A2": 3.0}
    with pytest.raises(orch.lanes.Refusal) as caught:
        orch.simulate(["A"], sessions)
    assert caught.value.reason == "size:A1"


# ---------------------------------------------------------------------------
# AC-925.5 — after ids and cycles
# ---------------------------------------------------------------------------


def test_ac_925_5_unknown_after_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    a = _grouping(repo / "a.md", [_block_lines("A1")], {"A1": "pending"})
    b = _grouping(repo / "b.md", [_block_lines("B1", after=["A1"])], {"B1": "pending"})
    argv = ["--repo", str(repo), "--cards-dir", str(repo / "cards")]
    assert (
        _refusal(capsys, "eligible", "--grouping", str(b), *argv)
        == "eligible_bad:after:B1:A1"
    )
    assert (
        _refusal(capsys, "simulate", "--grouping", str(b)) == "simulate_bad:after:B1:A1"
    )
    spec = _spec(tmp_path, {"A1": _spec_session("A1", after=["Q9"])})
    assert (
        _refusal(capsys, "simulate", "--spec", str(spec)) == "simulate_bad:after:A1:Q9"
    )
    both = _eligible(capsys, repo, [a, b], "--trees", "lanes")
    assert both["eligible"] == ["A1"]
    assert _excluded(both) == {"B1": {"after:A1"}}


def test_ac_925_5_duplicate_session_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _grouping(tmp_path / "a.md", [_block_lines("A1")], {"A1": "pending"})
    b = _grouping(tmp_path / "b.md", [_block_lines("A1")], {"A1": "pending"})
    assert (
        _refusal(capsys, "simulate", "--grouping", str(a), "--grouping", str(b))
        == "simulate_bad:duplicate:A1"
    )


def test_ac_925_5_cycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec = _spec(
        tmp_path,
        {
            "A1": _spec_session("A1", after=["B1"]),
            "C1": _spec_session("C1"),
            "B1": _spec_session("B1", after=["A1"]),
        },
    )
    assert (
        _refusal(capsys, "simulate", "--spec", str(spec)) == "simulate_bad:cycle:A1,B1"
    )
    repo = tmp_path / "repo"
    grouping = _grouping(
        repo / "a.md",
        [
            _block_lines("A1", tier=2, owns=["docs/"], after=["A2"]),
            _block_lines("A2", tier=1, owns=["docs/a.md"], after=["A3"]),
            _block_lines("A3", tier=3, owns=["ui/"], after=["A1"]),
        ],
        {"A1": "pending", "A2": "pending", "A3": "pending"},
    )
    assert (
        _refusal(
            capsys,
            "eligible",
            "--grouping",
            str(grouping),
            "--repo",
            str(repo),
            "--cards-dir",
            str(repo / "cards"),
        )
        == "eligible_bad:cycle:A1,A2,A3"
    )


# ---------------------------------------------------------------------------
# AC-925.6 — the hand check
# ---------------------------------------------------------------------------


def test_ac_925_6_synthetic_hand_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    cards = tmp_path / "cards"
    groupings = [
        _grouping(
            repo / "g" / "uf.md",
            [
                _block_lines("UF1", owns=["ui/a/"]),
                _block_lines("UF2", tier=2, owns=["ui/a/b.ts"], size="medium"),
                _block_lines(
                    "UF3", owns=["ui/c/"], vm=True, hold=("human", "VM steps")
                ),
            ],
            {"UF1": "done", "UF2": "pending", "UF3": "pending"},
        ),
        _grouping(
            repo / "g" / "pe.md",
            [
                _block_lines("PE1", owns=["tools/run.py"]),
                _block_lines("PE2", tier=2, owns=["tools/"], after=["UF2"]),
                _block_lines(
                    "PE3", owns=["docs/pe3/"], hold=("external", "fpem lands")
                ),
            ],
            {"PE1": "pending", "PE2": "pending", "PE3": "pending"},
        ),
        _grouping(
            repo / "g" / "rx.md",
            [
                _block_lines("RX1", owns=["tools/lanes.py"]),
                _block_lines("RX2", owns=["docs/rx2/"], e2e=True),
            ],
            {"RX1": "in-progress", "RX2": "pending"},
        ),
    ]
    _task_md(repo, "plans/rx1/", "g/rx.md", "RX1")
    _card(
        cards,
        "lane-rx1",
        worktree=tmp_path / "wt-rx1",
        plan="plans/rx1/",
        owns=["tools/lanes.py"],
    )
    data = _eligible(capsys, repo, groupings, "--trees", "lanes", cards=cards)
    hand_eligible = {"UF2", "PE1"}
    hand_excluded = {
        "UF3": {"hold:human:VM steps", "lane_busy"},
        "PE2": {
            "after:UF2",
            "after:PE1",
            "conflict:RX1:tools/lanes.py",
            "conflict:PE1:tools/run.py",
            "lane_busy",
        },
        "PE3": {"hold:external:fpem lands", "lane_busy"},
        "RX2": {"lane_busy"},
    }
    assert set(data["eligible"]) == hand_eligible
    assert _excluded(data) == hand_excluded
    assert data["running"] == ["RX1"]


# ---------------------------------------------------------------------------
# AC-925.7 — no model client, no process, no project literal
# ---------------------------------------------------------------------------


def test_ac_925_7_no_model_client_or_process() -> None:
    _orch()
    assert _scan(ORCH.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    ("added", "finding"),
    [
        ("import subprocess\n", "import:subprocess"),
        ("import http.client\n", "import:http.client"),
        ("from urllib import request\n", "import:urllib"),
        ("from os import system\n", "import:os.system"),
        ("import os\nos.execv('x', [])\n", "call:os.execv"),
        ("import os\nos.spawnl(0, 'x')\n", "call:os.spawnl"),
        (
            "import importlib\nimportlib.import_module('anthropic')\n",
            "import:anthropic",
        ),
        (f"ROOT = '{DRIVE}' + 'x'\n", f"literal:'{DRIVE}'"),
    ],
)
def test_ac_925_7_scan_catches_a_planted_line(added: str, finding: str) -> None:
    _orch()
    source = ORCH.read_text(encoding="utf-8") + "\n" + added
    assert finding in _scan(source)


# ---------------------------------------------------------------------------
# AC-925.8 — only the two read verbs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", REFUSED_VERBS)
def test_ac_925_8_refused_verb(verb: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, _out, err = _run(capsys, verb)
    assert code == 2
    assert "invalid choice" in err


def test_ac_925_8_only_eligible_and_simulate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _err = _run(capsys, "--help")
    assert code == 0
    # AC-951.4 (AG3 EA-7) replaces the two-verb parser of AC-925.8.
    assert "{eligible,simulate,facts,start,land,report}" in out
    code, _out, _err = _run(capsys)
    assert code == 2
    for verb in ("eligible", "simulate"):
        code, out, _err = _run(capsys, verb, "--help")
        assert code == 0
        assert "--json" in out
