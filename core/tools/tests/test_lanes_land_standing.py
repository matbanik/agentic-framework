"""MEU-939 tests for the land under the standing grant, the D-3 base comparator, the D-4 dirty
main tree and the direction-claim lifecycle.

Plan: docs/execution/plans/2026-11-07-standing-commit-grant (AC-939.7, AC-939.8, AC-939.9,
AC-939.15).

The contract these tests fix (``{{RECEIPTS_DIR}}/standing-grant/interfaces.md`` §wave 2):

* ``lanes.py land publish --grant`` lands a legacy lane under the standing grant as a
  fast-forward of local ``main`` (one commit C on P, the noreply author and committer); a
  moved ``main`` still refuses ``main_moved``.
* D-3: at prepare a red gate also runs the gate on the base P and records ``gate.base`` (an
  ``outcome`` of ``matched``, ``new_red:<node id>``, ``red_unmatched:<stage>`` or
  ``base_gate_unavailable``); the grant publish admits only a green gate or ``matched`` and
  refuses with the outcome, or ``gate_red_no_base``, before any claim or ref move; the
  human route publishes on any gate. The base result is cached, so a second land on the
  same base does not run the base gate again.
* D-4: foreign dirt in the main tree survives a land byte-for-byte; ``main_overlap:<path>``,
  ``main_staged:<path>``, ``sync_reset_with_dirt`` and ``sync_dirt_changed:<path>``.
* The claim lifecycle of ``human-<uid>/direction.json`` (``state``: pending, released,
  spent): a refusal or a hook failure releases the claim, so the same direction lands
  with a new op; a spent claim refuses before any ref moves; a stale pending claim is
  resolved from its op; a live op refuses ``direction_busy:<op>``; a claim with no state
  reads as spent.

The rigs are the ``tools/tests/test_lanes_land.py`` rigs (real ``phase_b3`` fixture
repositories, the real ``tools/lanes.py`` CLI). The gate is a fake
``tools/validate_codebase.py`` committed into the fixture: it reads its failures from
``gate/base_failures.json`` (seeded at P) and ``src/lane/gate_failures.json`` (written by
the lane), writes junit and ``gate.json`` like the real gate, and logs every run with the
commit it ran on, so the tests count the base runs.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import lane_worktree_config as lwc
from tools.tests import test_lanes_land as tl
from tools.tests.test_lanes_commit import _Holder

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "/standing-commit-grant"
LEGACY = "2026-11-01-legacy-lane"
NOREPLY = "100+fixture@users.noreply.github.com"
OP = tl.OP
OP2 = "op-land-2"
GATE_SCRIPT = "tools/validate_codebase.py"
GATE_TEST = "tests/unit/test_gate_fixture.py"
BASE_FAILURES = "gate/base_failures.json"
LANE_FAILURES = "src/lane/gate_failures.json"
NODE = GATE_TEST + "::"
FOREIGN_TRACKED = tl.OUTSIDE_SEED
FOREIGN_LOCKED = tl.LOCKED_FILE
FOREIGN_UNTRACKED = "notes/scratch.txt"
OLD_RED = {"name": "test_old", "message": "AssertionError: old red"}

# The fake gate: the command line, the run folder and the gate.json of
# tools/validate_codebase.py, with junit cases from the two failure files.
FAKE_GATE = r"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LOG = Path(__LOG__)
RUNS = Path(__RUNS__)
SOURCES = (Path("gate/base_failures.json"), Path("src/lane/gate_failures.json"))
STAGE = "Pytest unit"
CLASSNAME = "tests.unit.test_gate_fixture"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    with LOG.open("a", encoding="utf-8") as out:
        out.write(json.dumps({"cwd": os.getcwd(), "head": head, "argv": sys.argv}) + "\n")
    merged = {}
    for source in SOURCES:
        if source.is_file():
            for item in json.loads(source.read_text(encoding="utf-8")).get("failures", []):
                merged[(item.get("stage", STAGE), item["name"])] = item
    RUNS.mkdir(parents=True, exist_ok=True)
    run_dir = RUNS / f"run-{len(list(RUNS.iterdir())) + 1}"
    run_dir.mkdir()
    print(f"GATE RUN DIR {run_dir}")
    cases = ['<testcase classname="%s" name="test_ok" time="0.010"/>' % CLASSNAME]
    stages = {STAGE: True}
    for (stage, _name), item in sorted(merged.items()):
        stages[stage] = False
        if stage != STAGE:
            continue
        message = (
            item["message"].replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
        )
        cases.append(
            '<testcase classname="%s" name="%s" time="0.020">'
            '<failure message="%s">%s\nE   at the fixture line</failure></testcase>'
            % (CLASSNAME, item["name"], message, message)
        )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">'
        + "".join(cases)
        + "</testsuite></testsuites>\n"
    )
    (run_dir / f"{slug(STAGE)}.xml").write_text(xml, encoding="utf-8")
    checks = []
    for name, passed in stages.items():
        (run_dir / f"{slug(name)}.log").write_text(
            "passed\n" if passed else "failed\n", encoding="utf-8"
        )
        checks.append(
            {
                "name": name,
                "passed": passed,
                "blocking": True,
                "skipped": False,
                "not_run": False,
                "duration_s": 0.1,
                "message": "" if passed else "failed",
            }
        )
    summary = "pass" if all(stages.values()) else "fail"
    (run_dir / "gate.json").write_text(
        json.dumps(
            {"run_dir": str(run_dir), "reused_from": None, "summary": summary, "checks": checks},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("GATE " + summary.upper())
    return 0 if summary == "pass" else 1


sys.exit(main())
"""


# -- the rigs -----------------------------------------------------------------------------------


def _rp() -> ModuleType:
    return importlib.import_module("tools.run_parameters")


def _failures(items: list[dict[str, str]]) -> bytes:
    return (json.dumps({"failures": items}, indent=2) + "\n").encode("utf-8")


def _gate_files(folder: Path, base: list[dict[str, str]] | None) -> dict[str, bytes]:
    """The fake gate, its junit test module and the base failures, for the commit P."""
    log = folder / "gate-calls.jsonl"
    runs = folder / "gate-runs"
    text = FAKE_GATE.replace("__LOG__", repr(str(log))).replace(
        "__RUNS__", repr(str(runs))
    )
    files = {
        GATE_SCRIPT: text.encode("utf-8"),
        GATE_TEST: b"def test_ok():\n    pass\n",
    }
    if base is not None:
        files[BASE_FAILURES] = _failures(base)
    return files


def _make(
    tmp_path: Path,
    *,
    legacy: bool = False,
    owns: tuple[str, ...] = (tl.LANE_DIR,),
    lane_files: Mapping[str, bytes] | None = None,
    main_files: Mapping[str, bytes] | None = None,
) -> tl.Land:
    """A lane rig: the plan (the fixture plan, or a legacy plan with no frontmatter) owns
    ``owns``; the lane commits ``src/lane/feature.py`` and ``lane_files``; then ``main``
    gets ``main_files`` as P."""
    rig = b3.rig(tmp_path / "fx", ROOT, seed=lwc.SEED)
    rig.bind()
    rig.git("config", "user.email", NOREPLY)
    seed = dict(tl.SEED)
    block = tl._ownership(list(owns), [])
    if legacy:
        slug = LEGACY
        seed[f"{tl.PLANS}/{slug}/task.md"] = (
            f"# Task: {slug}\n\n| # | Task | Status |\n| :- | :- | :- |\n| 0 | row | [ ] |\n"
            + block
        ).encode("utf-8")
        seed[f"{tl.PLANS}/{slug}/implementation-plan.md"] = f"# Plan: {slug}\n".encode()
    else:
        slug = rig.plan
        seed[f"{tl.PLANS}/{slug}/task.md"] = rig.fx.task_path(
            slug
        ).read_bytes() + block.encode("utf-8")
    rig.seed(seed, message="fixture: lane ownership")
    extra = dict(lane_files or {})

    def change(wt: Path) -> None:
        for rel, data in extra.items():
            path = wt / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    wt, l0 = tl._add_lane(rig, slug, tl.LANE_DIR, lane_change=change)
    p = rig.seed(
        dict(main_files or {tl.MAIN_SIDE: b"main side\n"}), message="main: move"
    )
    message = rig.fx.root / "land-message.txt"
    message.write_bytes(tl.MESSAGE)
    return tl.Land(rig=rig, slug=slug, wt=wt, message=message, l0=l0, p=p)


def _gate_land(
    tmp_path: Path,
    *,
    base: list[dict[str, str]] | None,
    lane: list[dict[str, str]] | None = None,
    legacy: bool = False,
    gate_in_lane: bool = False,
) -> tl.Land:
    """A lane whose gate fails with ``base`` (at P) plus ``lane`` (the lane's own failures).

    ``gate_in_lane`` commits the gate script in the lane instead of at P, so the base run
    cannot start (``base_gate_unavailable``).
    """
    folder = tmp_path / "gate"
    folder.mkdir(parents=True, exist_ok=True)
    gate = _gate_files(folder, base)
    lane_files: dict[str, bytes] = {}
    if lane is not None:
        lane_files[LANE_FAILURES] = _failures(lane)
    owns: tuple[str, ...] = (tl.LANE_DIR,)
    if gate_in_lane:
        lane_files[GATE_SCRIPT] = gate.pop(GATE_SCRIPT)
        owns = (tl.LANE_DIR, GATE_SCRIPT)
    main_files = {tl.MAIN_SIDE: b"main side\n", **gate}
    return _make(
        tmp_path, legacy=legacy, owns=owns, lane_files=lane_files, main_files=main_files
    )


def _base_runs(land: tl.Land) -> int:
    """How many gate runs ran on the base commit P."""
    log = land.rig.fx.root.parent / "gate" / "gate-calls.jsonl"
    if not log.is_file():
        return 0
    return sum(
        1
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("head") == land.p
    )


def _gate_base(land: tl.Land, op: str = OP) -> dict[str, Any]:
    """The recorded ``gate.base`` evidence of a land op (``{}`` when there is none)."""
    fields = tl._fields(tl._record(land, op))
    gate = fields.get("gate")
    if isinstance(gate, dict) and isinstance(gate.get("base"), dict):
        return dict(gate["base"])
    direct = fields.get("gate.base")
    return dict(direct) if isinstance(direct, dict) else {}


def _run_rp(fx: bf.Fixture, *argv: str) -> tuple[int, str, str]:
    rp = _rp()
    out, err = io.StringIO(), io.StringIO()
    with (
        bf.patched_environ(fx.env()),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        try:
            code = rp.main(["--repo", str(fx.repo), *argv])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
    return int(code), out.getvalue(), err.getvalue()


def _grant(fx: bf.Fixture) -> str:
    """Record a standing grant from a typed record; return its uuid."""
    uid = fx.add_human(TOKEN)
    code, out, err = _run_rp(
        fx, "standing", "--session", fx.session, "--message-uuid", uid
    )
    said = any(
        line.strip() == f"standing_ok {uid}" for line in out.splitlines()
    ) or any('"standing_ok"' in line and uid in line for line in out.splitlines())
    assert code == 0 and said, (code, out, err)
    return uid


def _publish_uid(land: tl.Land, uid: str, *, op: str = OP) -> Any:
    """``land publish`` on the human route with a given direction uuid."""
    return tl._cli(
        land,
        "land",
        "publish",
        "--op",
        op,
        "--human-directed",
        "--session",
        land.session,
        "--message-uuid",
        uid,
    )


def _direction(land: tl.Land) -> str:
    return land.rig.fx.add_human(f"commit the {land.slug} plan on main")


def _claim_path(land: tl.Land, uid: str) -> Path:
    return (
        land.rig.fx.store
        / "ops"
        / land.slug
        / land.session
        / f"human-{uid}"
        / "direction.json"
    )


def _claim(land: tl.Land, uid: str) -> dict[str, Any]:
    paths = sorted(land.rig.fx.store.glob(f"ops/*/*/human-{uid}/direction.json"))
    assert len(paths) == 1, paths
    data = json.loads(paths[0].read_text(encoding="utf-8"))
    assert isinstance(data, dict), paths[0]
    return data


def _all_claims(land: tl.Land) -> list[str]:
    return sorted(
        path.relative_to(land.rig.fx.store).as_posix()
        for path in land.rig.fx.store.glob("ops/*/*/*/direction.json")
    )


def _grants(land: tl.Land) -> dict[str, bytes]:
    folder = land.rig.fx.store / "grants"
    if not folder.is_dir():
        return {}
    return {path.name: path.read_bytes() for path in sorted(folder.glob("*.json"))}


def _refusal(proc: Any) -> str | None:
    """The reason of a ``refused: <reason>`` line, or None."""
    for line in proc.stdout.splitlines():
        if line.startswith("refused: "):
            return line[len("refused: ") :].strip()
    return None


def _forge(land: tl.Land, uid: str, **fields: Any) -> Path:
    """Write a land claim for ``uid`` as an earlier run would have left it."""
    path = _claim_path(land, uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "act": "land",
        "message_uuid": uid,
        "plan": land.slug,
        "schema": "direction-claim/1",
        "session": land.session,
    }
    data.update(fields)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


# -- AC-939.7: the land under the standing grant -------------------------------------------------


def test_ac_939_7_grant_publish_lands_a_legacy_lane_as_a_fast_forward(
    tmp_path: Path,
) -> None:
    """AC-939.7: a legacy lane lands on ``--grant`` under the standing grant: one commit on P."""
    land = _gate_land(tmp_path, base=None, legacy=True)
    _grant(land.rig.fx)
    tree = tl._ready(land)
    proc = tl._publish_grant(land, op=OP)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    c = land.rig.ref()
    assert land.rig.parents(c) == [land.p], (
        "a fast-forward of local main: C's parent is P"
    )
    assert land.git("rev-parse", f"{c}^{{tree}}").strip() == tree
    shown = land.git("show", "-s", "--format=%ae|%ce", c).strip()
    assert shown == f"{NOREPLY}|{NOREPLY}", shown
    assert ("published", "done") in tl._phases(tl._record(land))


def test_ac_939_7_a_moved_main_still_refuses_under_the_standing_grant(
    tmp_path: Path,
) -> None:
    """AC-939.7: the non-fast-forward rule stays: a moved ``main`` refuses ``main_moved``."""
    land = _gate_land(tmp_path, base=None, legacy=True)
    _grant(land.rig.fx)
    tl._ready(land)
    moved = land.rig.seed({"src/late.txt": b"late\n"}, message="main: late")
    proc = tl._publish_grant(land, op=OP)
    assert _refusal(proc) == "main_moved", (proc.stdout, proc.stderr)
    assert land.rig.ref() == moved


# -- AC-939.8: the D-3 base comparator ------------------------------------------------------------

GATE_CASES: dict[str, dict[str, Any]] = {
    "new_red": {
        "base": [OLD_RED],
        "lane": [{"name": "test_new", "message": "AssertionError: new red"}],
        "outcome": f"new_red:{NODE}test_new",
    },
    "changed_first_line": {
        "base": [OLD_RED],
        "lane": [{"name": "test_old", "message": "AssertionError: another text"}],
        "outcome": f"new_red:{NODE}test_old",
    },
    "red_unmatched": {
        "base": [],
        "lane": [{"stage": "Lint", "name": "lint", "message": "E501 line too long"}],
        "outcome": "red_unmatched:",
    },
    "base_gate_unavailable": {
        "base": None,
        "lane": [{"name": "test_new", "message": "AssertionError: new red"}],
        "outcome": "base_gate_unavailable",
        "gate_in_lane": True,
    },
}


def test_ac_939_8_a_red_land_whose_failures_match_the_base_lands_on_the_grant(
    tmp_path: Path,
) -> None:
    """AC-939.8: prepare records ``gate.base`` ``matched``; the grant publish lands it."""
    land = _gate_land(tmp_path, base=[OLD_RED])
    tl._ready(land)
    gate = tl._fields(tl._record(land)).get("gate", {})
    assert str(gate.get("result", "")).startswith("fail"), gate
    base = _gate_base(land)
    assert base.get("outcome") == "matched", base
    assert _base_runs(land) == 1, "the base gate ran once, on P"
    proc = tl._publish_grant(land, op=OP)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert land.rig.parents(land.rig.ref()) == [land.p]


@pytest.mark.parametrize("case", sorted(GATE_CASES))
def test_ac_939_8_the_grant_route_refuses_an_unmatched_red_gate(
    tmp_path: Path, case: str
) -> None:
    """AC-939.8: each outcome other than ``matched`` refuses on the grant route, before any
    claim or ref move; the same prepared land then lands on the human route."""
    spec = GATE_CASES[case]
    land = _gate_land(
        tmp_path,
        base=spec["base"],
        lane=spec["lane"],
        gate_in_lane=bool(spec.get("gate_in_lane")),
    )
    tl._ready(land)
    outcome = str(_gate_base(land).get("outcome", ""))
    assert outcome.startswith(spec["outcome"]), (case, _gate_base(land))
    grants = _grants(land)
    proc = tl._publish_grant(land, op=OP)
    reason = _refusal(proc) or ""
    assert proc.returncode == 1 and reason.startswith(spec["outcome"]), (
        case,
        proc.stdout,
        proc.stderr,
    )
    if case == "red_unmatched":
        assert "lint" in reason.lower(), reason
    assert land.rig.ref() == land.p, "no ref moves"
    assert _all_claims(land) == [], "no direction is claimed"
    assert _grants(land) == grants, "no grant act is consumed"
    _ok_land = _publish_uid(land, _direction(land))
    assert _ok_land.returncode == 0, (_ok_land.stdout, _ok_land.stderr)
    assert land.rig.parents(land.rig.ref()) == [land.p], "the human route lands it"


def test_ac_939_8_a_red_gate_with_no_base_record_refuses_gate_red_no_base(
    tmp_path: Path,
) -> None:
    """AC-939.8: a red land prepared before this change (no ``gate.base``) refuses on the grant."""
    land = _gate_land(tmp_path, base=[OLD_RED])
    tl._ready(land)
    path = tl._op_file(land)
    assert path is not None
    record = json.loads(path.read_text(encoding="utf-8"))
    stripped = 0
    for item in record.get("journal", []):
        evidence = item.get("evidence") if isinstance(item, dict) else None
        if not isinstance(evidence, dict):
            continue
        if isinstance(evidence.get("gate"), dict) and "base" in evidence["gate"]:
            del evidence["gate"]["base"]
            stripped += 1
        if "gate.base" in evidence:
            del evidence["gate.base"]
            stripped += 1
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    assert stripped >= 1, "prepare recorded gate.base"
    proc = tl._publish_grant(land, op=OP)
    assert _refusal(proc) == "gate_red_no_base", (proc.stdout, proc.stderr)
    assert land.rig.ref() == land.p
    assert _all_claims(land) == []


def test_ac_939_8_a_second_land_on_the_same_base_reads_the_cache(
    tmp_path: Path,
) -> None:
    """AC-939.8: the base result is cached by P, files and env: the base gate runs once."""
    land = _gate_land(tmp_path, base=[OLD_RED])
    tl._ready(land)
    assert _base_runs(land) == 1
    cache = sorted((land.rig.fx.store / "gate-base").glob(f"{land.p}-*.json"))
    assert len(cache) == 1, cache
    stray = land.repo / tl.FEATURE
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"edited in main\n")
    uid = _direction(land)
    assert _refusal(_publish_uid(land, uid)) == f"main_overlap:{tl.FEATURE}"
    stray.unlink()
    tl._ready(land, op=OP2)
    assert _base_runs(land) == 1, "the second land on P read the cache"
    assert _gate_base(land, OP2).get("outcome") == "matched", _gate_base(land, OP2)
    proc = tl._publish_grant(land, op=OP2)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


# -- AC-939.9: the D-4 dirty main tree ------------------------------------------------------------


def _dirty_foreign(land: tl.Land) -> dict[str, str | None]:
    """Foreign dirt in the main tree: a modified tracked file, a second one and an untracked one."""
    (land.repo / FOREIGN_TRACKED).write_bytes(b"OUTSIDE = 'dirty in main'\n")
    (land.repo / FOREIGN_LOCKED).write_bytes(b"LOCKED = 'dirty in main'\n")
    untracked = land.repo / FOREIGN_UNTRACKED
    untracked.parent.mkdir(parents=True, exist_ok=True)
    untracked.write_bytes(b"scratch notes\n")
    return _foreign_hashes(land)


def _foreign_hashes(land: tl.Land) -> dict[str, str | None]:
    return {
        rel: _sha(land.repo / rel)
        for rel in (FOREIGN_TRACKED, FOREIGN_LOCKED, FOREIGN_UNTRACKED)
    }


def test_ac_939_9_a_land_onto_a_dirty_main_tree_keeps_every_foreign_file(
    tmp_path: Path,
) -> None:
    """AC-939.9: no overlap: the land succeeds and every foreign dirty and untracked file survives."""
    land = _make(tmp_path)
    tl._ready(land)
    before = _dirty_foreign(land)
    proc = _publish_uid(land, _direction(land))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    c = land.rig.ref()
    assert land.rig.parents(c) == [land.p]
    assert _foreign_hashes(land) == before, "every foreign file keeps its bytes"
    assert ("land:sync", "done") in tl._phases(tl._record(land))
    assert (land.repo / tl.FEATURE).read_bytes() == b"FEATURE = 1\n"
    left = [
        path
        for path in tl._unequal_paths(land, land.repo, c)
        if path not in {FOREIGN_TRACKED, FOREIGN_LOCKED}
    ]
    assert left == [], left


def test_ac_939_9_a_dirty_landed_path_is_main_overlap(tmp_path: Path) -> None:
    """AC-939.9: a tracked path that the land changes, dirty in main, refuses ``main_overlap:<path>``."""
    land = _make(tmp_path, lane_files={tl.BASE_FILE: b"BASE = 2\n"})
    tl._ready(land)
    _dirty_foreign(land)
    (land.repo / tl.BASE_FILE).write_bytes(b"BASE = 'main'\n")
    proc = _publish_uid(land, _direction(land))
    assert _refusal(proc) == f"main_overlap:{tl.BASE_FILE}", (proc.stdout, proc.stderr)
    assert land.rig.ref() == land.p
    assert (land.repo / tl.BASE_FILE).read_bytes() == b"BASE = 'main'\n"


def test_ac_939_9_a_staged_entry_is_main_staged(tmp_path: Path) -> None:
    """AC-939.9: an index entry that differs from HEAD refuses ``main_staged:<path>``."""
    land = _make(tmp_path)
    tl._ready(land)
    (land.repo / FOREIGN_TRACKED).write_bytes(b"OUTSIDE = 'staged'\n")
    land.git("add", FOREIGN_TRACKED)
    index = (land.common / "index").read_bytes()
    proc = _publish_uid(land, _direction(land))
    assert _refusal(proc) == f"main_staged:{FOREIGN_TRACKED}", (
        proc.stdout,
        proc.stderr,
    )
    assert land.rig.ref() == land.p
    assert (land.common / "index").read_bytes() == index


def test_ac_939_9_the_reset_branch_with_foreign_dirt_refuses(tmp_path: Path) -> None:
    """AC-939.9: a sync that would take ``read-tree --reset`` while foreign dirt exists stops."""
    land = _make(tmp_path)
    tl._ready(land)
    before = _dirty_foreign(land)
    tl._crashed(tl._publish_human(land, env=tl._crash("land:sync:started")))
    c = land.rig.ref()
    assert c != land.p
    land.git("read-tree", c)
    proc = tl._recover(land)
    line = tl._stopped(proc, "sync_reset_with_dirt")
    assert "sync_reset_with_dirt" in line
    assert _foreign_hashes(land) == before, "the foreign files keep their bytes"
    assert ("land:sync", "done") not in tl._phases(tl._record(land))


def test_ac_939_9_a_foreign_file_changed_during_the_sync_refuses(
    tmp_path: Path,
) -> None:
    """AC-939.9: a foreign file whose bytes change during the sync refuses ``sync_dirt_changed:<path>``."""
    land = _make(tmp_path)
    tl._ready(land)
    _dirty_foreign(land)
    tl._crashed(tl._publish_human(land, env=tl._crash("land:sync:started")))
    (land.repo / FOREIGN_TRACKED).write_bytes(b"OUTSIDE = 'changed during the sync'\n")
    proc = tl._recover(land)
    line = tl._stopped(proc, f"sync_dirt_changed:{FOREIGN_TRACKED}")
    assert FOREIGN_TRACKED in line
    assert (
        land.repo / FOREIGN_TRACKED
    ).read_bytes() == b"OUTSIDE = 'changed during the sync'\n"


# -- AC-939.15: the claim lifecycle ----------------------------------------------------------------


def test_ac_939_15_a_main_overlap_refusal_releases_the_direction_for_a_new_op(
    tmp_path: Path,
) -> None:
    """AC-939.15: a refused land leaves the claim ``released``; the same direction lands with a new op."""
    land = _make(tmp_path)
    tl._ready(land)
    stray = land.repo / tl.FEATURE
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"edited in main\n")
    uid = _direction(land)
    assert _refusal(_publish_uid(land, uid)) == f"main_overlap:{tl.FEATURE}"
    assert land.rig.ref() == land.p
    assert _claim(land, uid).get("state") == "released", _claim(land, uid)
    stray.unlink()
    tl._ready(land, op=OP2)
    proc = _publish_uid(land, uid, op=OP2)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert land.rig.parents(land.rig.ref()) == [land.p]
    claim = _claim(land, uid)
    assert (claim.get("state"), claim.get("op")) == ("spent", OP2), claim


def test_ac_939_15_grant_route_main_overlap_reserves_nothing(tmp_path: Path) -> None:
    """AC-939.15 (EA-6): on the grant route a ``main_overlap`` refusal reserves no grant act, so
    a new op of the same lane lands on the same grant."""
    land = _gate_land(tmp_path, base=None)
    tl._ready(land)
    assert tl._fields(tl._record(land)).get("gate", {}).get("result") == "pass"
    grants = _grants(land)
    stray = land.repo / tl.FEATURE
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"edited in main\n")
    proc = tl._publish_grant(land, op=OP)
    assert _refusal(proc) == f"main_overlap:{tl.FEATURE}", (proc.stdout, proc.stderr)
    assert land.rig.ref() == land.p, "no ref moves"
    assert _grants(land) == grants, "no grant act is reserved"
    stray.unlink()
    tl._ready(land, op=OP2)
    proc = tl._publish_grant(land, op=OP2)
    assert _refusal(proc) not in {"consumed", "op_exists"}, (proc.stdout, proc.stderr)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert land.rig.parents(land.rig.ref()) == [land.p]


def test_ac_939_15_a_hook_drift_refusal_does_not_spend_the_direction(
    tmp_path: Path,
) -> None:
    """AC-939.15: hook_drift, then main moves (the card goes back to active), then op-land-2 lands
    on the same direction."""
    land = _make(tmp_path)
    tl._ready(land)
    land.rig.install_hook(
        "pre-commit", "echo drift > drift.txt\ngit add drift.txt\nexit 0"
    )
    uid = _direction(land)
    assert _refusal(_publish_uid(land, uid)) == "hook_drift"
    assert land.rig.ref() == land.p
    assert _claim(land, uid).get("state") == "released", _claim(land, uid)
    (land.rig.hooks / "pre-commit").unlink()
    moved = land.rig.seed({"src/late.txt": b"late\n"}, message="main: late")
    assert _refusal(_publish_uid(land, uid)) == "main_moved"
    assert land.card()["state"] == "active", land.card()
    tl._ready(land, op=OP2)
    proc = _publish_uid(land, uid, op=OP2)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert land.rig.parents(land.rig.ref()) == [moved]
    assert _claim(land, uid).get("state") == "spent", _claim(land, uid)


def test_ac_939_15_a_batch_hook_failure_releases_the_claim(tmp_path: Path) -> None:
    """AC-939.15: on the batch route a hook failure leaves ``released``; the retry commits and spends it."""
    rig = b3.rig(tmp_path / "fx", ROOT)
    rig.git("config", "user.email", NOREPLY)
    rig.bind()
    rig.install_hook("pre-commit", "exit 1")
    uid = rig.fx.add_human("commit")
    before = rig.ref()
    packet = rig.packet(files={"hooked.txt": b"hooked\n"})
    code, out, text = rig.human(uid, packet)
    assert (code, out.get("result")) != (0, "reconciled"), text
    assert rig.ref() == before
    paths = sorted(rig.fx.store.glob(f"ops/*/*/human-{uid}/direction.json"))
    assert len(paths) == 1, paths
    assert json.loads(paths[0].read_text(encoding="utf-8")).get("state") == "released"
    (rig.hooks / "pre-commit").unlink()
    code, out, text = rig.human(uid, packet)
    assert (code, out.get("result")) == (0, "reconciled"), text
    assert json.loads(paths[0].read_text(encoding="utf-8")).get("state") == "spent"


def test_ac_939_15_a_spent_direction_refuses_before_any_ref_moves(
    tmp_path: Path,
) -> None:
    """AC-939.15: a direction spent by a commit refuses a land ``direction_spent``; main stays at M."""
    land = _make(tmp_path)
    uid = _direction(land)
    code, out, text = land.rig.human(
        uid, land.rig.packet(files={"spent.txt": b"spent\n"})
    )
    assert (code, out.get("result")) == (0, "reconciled"), text
    m = land.rig.ref()
    assert _claim(land, uid).get("state") == "spent", _claim(land, uid)
    tl._ready(land)
    proc = _publish_uid(land, uid)
    assert _refusal(proc) == "direction_spent", (proc.stdout, proc.stderr)
    assert land.rig.ref() == m


def test_ac_939_15_a_released_commit_claim_still_refuses_a_land(tmp_path: Path) -> None:
    """AC-939.15: a commit claim released by a hook failure keeps its act: a land refuses."""
    land = _make(tmp_path)
    land.rig.install_hook("pre-commit", "exit 1")
    uid = _direction(land)
    code, out, text = land.rig.human(uid, land.rig.packet(files={"hooked.txt": b"h\n"}))
    assert (code, out.get("result")) != (0, "reconciled"), text
    (land.rig.hooks / "pre-commit").unlink()
    claim = _claim(land, uid)
    assert claim.get("state") == "released", claim
    tl._ready(land)
    proc = _publish_uid(land, uid)
    assert _refusal(proc) == "direction_spent", (proc.stdout, proc.stderr)
    assert land.rig.ref() == land.p
    assert _claim(land, uid) == claim, "the claim keeps its act and state"


def test_ac_939_15_a_stale_pending_claim_is_resolved_from_its_op(
    tmp_path: Path,
) -> None:
    """AC-939.15: a claim with no state reads as spent; a pending claim of a dead op whose target
    is not on main is released and the land publishes with the new op."""
    land = _make(tmp_path)
    tl._ready(land)
    old = _direction(land)
    _forge(land, old, op="op-land-old")
    proc = _publish_uid(land, old)
    assert _refusal(proc) == "direction_spent", (proc.stdout, proc.stderr)
    assert land.rig.ref() == land.p
    dead = _direction(land)
    _forge(
        land, dead, op="op-land-dead", state="pending", target=land.rig.other_commit()
    )
    proc = _publish_uid(land, dead)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert land.rig.parents(land.rig.ref()) == [land.p]
    claim = _claim(land, dead)
    assert (claim.get("state"), claim.get("op")) == ("spent", OP), claim


def test_ac_939_15_a_pending_claim_whose_target_is_on_main_is_spent(
    tmp_path: Path,
) -> None:
    """AC-939.15: a pending claim of a dead op whose target main contains becomes ``spent``."""
    land = _make(tmp_path)
    tl._ready(land)
    uid = _direction(land)
    _forge(land, uid, op="op-land-dead", state="pending", target=land.p)
    proc = _publish_uid(land, uid)
    assert _refusal(proc) == "direction_spent", (proc.stdout, proc.stderr)
    assert land.rig.ref() == land.p
    assert _claim(land, uid).get("state") == "spent", _claim(land, uid)


def test_ac_939_15_a_pending_claim_of_a_live_op_is_direction_busy(
    tmp_path: Path,
) -> None:
    """AC-939.15: while the claim's op holds its lease, the land refuses ``direction_busy:<op>``."""
    land = _make(tmp_path)
    tl._ready(land)
    uid = _direction(land)
    path = _forge(
        land, uid, op="op-land-live", state="pending", target=land.rig.other_commit()
    )
    claim = path.read_bytes()
    holder = _Holder(land.common / "lanes" / "ops" / "op-land-live.lease")
    try:
        proc = _publish_uid(land, uid)
    finally:
        holder.stop()
    assert _refusal(proc) == "direction_busy:op-land-live", (proc.stdout, proc.stderr)
    assert land.rig.ref() == land.p
    assert path.read_bytes() == claim, "a busy claim is left as it was"
