"""MEU-785 AC-785.13, .14, .16, .17, .19, .21, .22, .24 and the EA-12 cases: the governed land — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.13 (design D:244), AC-785.14 (D:229, D:245), AC-785.16 (D:247), AC-785.17 (D:248),
AC-785.19 (D:250), AC-785.21 (D:251; §10b N-2), AC-785.22 (D:252) and AC-785.24
(D:373-374). EA-12 moves two groups of cases here, written against the land journal:
the AC-785.8 ``release --reset`` cases (D:217, D:252: L0 -> C, ``lane_dirty``,
``lane_moved``, ``land_open``) and the AC-785.12 re-read after the op lease
(D:166: ``journal_moved``, ``card_superseded``).

CLI contract (boundary inventory, IP:143-156): ``lanes.py land prepare --worktree W
--l0 L0 --message-file F --op ID`` runs steps 1-5 and ends ``land_ready:<op>:<tree>``;
``land prepare --op ID --verdict FILE`` records a ``land-verdict/1`` verdict;
``land publish --op ID [--grant | --human-directed --session S --message-uuid U]`` runs
steps 6-9; ``land recover --op ID`` re-runs an op. A refusal prints
``refused: <reason>`` and exits 1 (stage-1 contract); HALT is asserted only as a nonzero
exit with a ``halt`` token. The land journal lives in the commit_batch op store
(``<common>/run-parameters/ops/<plan>/<run>/<op>/op.json``); the plan and run components
are not fixed by the plan, so the tests find the op folder by its id. Journal entries
carry ``phase``, ``status``, ``evidence`` and ``identity`` (commit_batch ``_append``);
the land fields are read from the record and every entry, merged in order. Crash
injection uses ``RUN_PARAMETERS_TEST_CRASH_AT=land:<phase>:<started|done>`` (exit 97);
as in commit_batch, the ``started`` and ``done`` seams fire after their journal entry.

Every repository is a disposable ``phase_b3`` fixture (``git init -b main``, SSH
signing, an initialized run-parameters store) in ``tmp_path``. The lane slug is the
fixture plan, so the plan folder, the card and ``lane/<slug>`` share one name. Each
test builds its rig inside the test body, so a missing land verb fails the test call
and never the setup. The human route uses a typed fixture transcript record with the
commit_batch consent sentence. Tests reach new symbols at run time. Do not skip, only,
or early-return (G36).
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import lane_worktree_config as lwc
from tools.tests.test_lanes_commit import _Holder

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "tools" / "lanes.py"
PLANS = "docs/execution/plans"
OP = "op-land-1"
OP_B = "op-land-b1"
GATE_LOCK = "{{PROJECT_NAME}}-gate.lock"
SESSION_ENV = "{{PROJECT_NAME_UPPER}}_SESSION"
CLI_TIMEOUT_S = 300
WAIT_S = 0.2
POLL_S = 0.01
OTHER_GENERATION = "fedcba9876543210"
VERDICT_SCHEMA = "land-verdict/1"
MESSAGE = b"land: the fixture lane\n\nOne governed land of the fixture lane.\n"
LANE_DIR = "src/lane/"
LANE_B_DIR = "src/lane-b/"
FEATURE = "src/lane/feature.py"
BASE_FILE = "src/lane/base.py"
# Outside ``owns``: stage 1 refuses an owns entry that overlaps a must_not_touch entry
# (``ownership_contradiction``, lanes.py ``_load_ownership``), so N-4 "must_not_touch wins"
# is observable only as a must_not_touch path outside ``owns``.
LOCKED_FILE = "src/locked.py"
OUTSIDE_SEED = "src/outside_seed.py"
MAIN_SIDE = "src/main_side.txt"
SEED: dict[str, bytes] = {
    BASE_FILE: b"BASE = 1\n",
    LOCKED_FILE: b"LOCKED = 1\n",
    OUTSIDE_SEED: b"OUTSIDE = 1\n",
}

Changer = Callable[[Path], None]


def _lanes() -> ModuleType:
    return importlib.import_module("tools.lanes")


# ---------------------------------------------------------------------------
# The rig
# ---------------------------------------------------------------------------


@dataclass
class Land:
    """One lane on a ``phase_b3`` fixture: its worktree, its reviewed tip and ``P``."""

    rig: b3.Rig
    slug: str
    wt: Path
    message: Path
    l0: str
    p: str

    @property
    def repo(self) -> Path:
        return self.rig.repo

    @property
    def common(self) -> Path:
        return Path(
            self.git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        ).resolve()

    @property
    def session(self) -> str:
        return self.rig.fx.session

    @property
    def branch_ref(self) -> str:
        return f"refs/heads/lane/{self.slug}"

    @property
    def card_path(self) -> Path:
        return self.common / "lanes" / f"{self.slug}.json"

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        return bf.git(cwd or self.repo, *args, check=check)

    def tip(self) -> str:
        return self.git("rev-parse", self.branch_ref).strip()

    def card(self) -> dict[str, Any]:
        data = json.loads(self.card_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), self.card_path
        return data

    def git_dir(self, wt: Path) -> Path:
        return Path(
            self.git("rev-parse", "--absolute-git-dir", cwd=wt).strip()
        ).resolve()


def _ownership(owns: list[str], must_not_touch: list[str]) -> str:
    """The ``## Lane Ownership`` block of a lane ``task.md`` (the stage-1 format)."""
    mnt = (
        "must_not_touch:\n" + "".join(f"  - {item}\n" for item in must_not_touch)
        if must_not_touch
        else "must_not_touch: []\n"
    )
    return (
        "\n## Lane Ownership\n\n```yaml\nowns:\n"
        + "".join(f"  - {item}\n" for item in owns)
        + mnt
        + "```\n"
    )


def _with_ownership(rig: b3.Rig, slug: str, owned: str, mnt: list[str]) -> bytes:
    current = rig.fx.task_path(slug).read_bytes()
    return current + _ownership([owned], mnt).encode("utf-8")


def _add_lane(
    rig: b3.Rig,
    slug: str,
    owned: str,
    *,
    lane_change: Changer | None = None,
) -> tuple[Path, str]:
    """A linked worktree on ``lane/<slug>``, claimed, with one lane commit: (worktree, L0)."""
    wt = (rig.fx.root / f"wt-{slug}").absolute()
    bf.git(rig.repo, "worktree", "add", "-q", "-b", f"lane/{slug}", str(wt))
    claim = _cli_at(
        rig,
        wt,
        "claim",
        "--plan",
        f"{PLANS}/{slug}",
        "--worktree",
        str(wt),
        "--session",
        rig.fx.session,
    )
    assert claim.returncode == 0, ("claim", claim.stdout, claim.stderr)
    feature = wt / owned / "feature.py"
    feature.parent.mkdir(parents=True, exist_ok=True)
    feature.write_bytes(b"FEATURE = 1\n")
    if lane_change is not None:
        lane_change(wt)
    bf.git(wt, "add", "-A")
    bf.git(wt, "commit", "-q", "-m", f"lane: work of {slug}")
    return wt, bf.git(wt, "rev-parse", "HEAD").strip()


def _build(
    tmp_path: Path,
    *,
    lane_change: Changer | None = None,
    main_change: Mapping[str, bytes] | None = None,
    mnt: list[str] | None = None,
    second: bool = False,
) -> tuple[Land, Land | None]:
    """The fixture, lane A (and lane B when ``second``), then one more ``main`` commit (``P``)."""
    rig = b3.rig(tmp_path / "fx", ROOT, seed=lwc.SEED)
    rig.bind()
    slug = rig.plan
    seed = dict(SEED)
    seed[f"{PLANS}/{slug}/task.md"] = _with_ownership(rig, slug, LANE_DIR, mnt or [])
    if second:
        # Plan B carries its own accepted grant (scope.plan = plan B), not plan A's.
        block_b = rig.fx.present_and_accept(plan=bf.PLAN_B)
        rig.fx.write_carrier(block_b, plan=bf.PLAN_B)
        seed[f"{PLANS}/{bf.PLAN_B}/task.md"] = _with_ownership(
            rig, bf.PLAN_B, LANE_B_DIR, []
        )
    rig.seed(seed, message="fixture: lane ownership")
    if second:
        code, out = rig.fx.run("init", "--plan", bf.PLAN_B)
        if (code, out.get("result")) != (0, "initialized"):
            raise RuntimeError(f"init of plan B failed: {out}")
    wt, l0 = _add_lane(rig, slug, LANE_DIR, lane_change=lane_change)
    other: tuple[Path, str] | None = None
    if second:
        other = _add_lane(rig, bf.PLAN_B, LANE_B_DIR)
    p = rig.seed(dict(main_change or {MAIN_SIDE: b"main side\n"}), message="main: move")
    message = rig.fx.root / "land-message.txt"
    message.write_bytes(MESSAGE)
    land = Land(rig=rig, slug=slug, wt=wt, message=message, l0=l0, p=p)
    land_b = (
        Land(rig=rig, slug=bf.PLAN_B, wt=other[0], message=message, l0=other[1], p=p)
        if other is not None
        else None
    )
    return land, land_b


def _one(tmp_path: Path, **kwargs: Any) -> Land:
    land, _ = _build(tmp_path, **kwargs)
    return land


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------


def _cli_at(
    rig: b3.Rig, cwd: Path, *args: str, env: Mapping[str, str | None] | None = None
) -> subprocess.CompletedProcess[str]:
    extra: dict[str, str | None] = {SESSION_ENV: rig.fx.session}
    extra.update(env or {})
    return subprocess.run(
        [sys.executable, str(LANES), *args],
        cwd=str(cwd),
        env=rig.fx.env(**extra),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLI_TIMEOUT_S,
        check=False,
    )


def _cli(
    land: Land,
    *args: str,
    cwd: Path | None = None,
    env: Mapping[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    return _cli_at(land.rig, cwd or land.wt, *args, env=env)


def _crash(point: str) -> dict[str, str | None]:
    return {b3.CRASH: point}


def _prepare(
    land: Land,
    *,
    l0: str | None = None,
    op: str = OP,
    env: Mapping[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    return _cli(
        land,
        "land",
        "prepare",
        "--worktree",
        str(land.wt),
        "--l0",
        l0 or land.l0,
        "--message-file",
        str(land.message),
        "--op",
        op,
        env=env,
    )


def _verdict(
    land: Land,
    tree: str,
    *,
    verdict: str = "approved",
    op: str = OP,
    extra: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    data: dict[str, str] = {
        "schema": VERDICT_SCHEMA,
        "op": op,
        "tree": tree,
        "verdict": verdict,
        "review": f".agent/context/handoffs/{land.slug}-land-review.md",
    }
    data.update(extra or {})
    folder = land.rig.fx.root / "verdicts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{op}-{len(list(folder.iterdir())) + 1}.json"
    path.write_bytes(json.dumps(data, indent=2).encode("utf-8"))
    return _cli(land, "land", "prepare", "--op", op, "--verdict", str(path))


def _publish_human(
    land: Land,
    *,
    op: str = OP,
    cwd: Path | None = None,
    env: Mapping[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    uid = land.rig.fx.add_human(f"commit the {land.slug} plan on main")
    return _cli(
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
        cwd=cwd,
        env=env,
    )


def _publish_grant(
    land: Land, *, op: str, env: Mapping[str, str | None] | None = None
) -> subprocess.CompletedProcess[str]:
    return _cli(land, "land", "publish", "--op", op, "--grant", env=env)


def _recover(
    land: Land, *, op: str = OP, env: Mapping[str, str | None] | None = None
) -> subprocess.CompletedProcess[str]:
    return _cli(land, "land", "recover", "--op", op, env=env)


def _release_reset(land: Land) -> subprocess.CompletedProcess[str]:
    """``release --worktree W --reset`` (boundary row IP:143); the session comes from the env."""
    return _cli(land, "release", "--worktree", str(land.wt), "--reset", cwd=land.repo)


def _ok(proc: subprocess.CompletedProcess[str]) -> str:
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return proc.stdout


def _refused(proc: subprocess.CompletedProcess[str], reason: str) -> str:
    assert proc.returncode == 1, (reason, proc.returncode, proc.stdout, proc.stderr)
    assert any(
        line.startswith(f"refused: {reason}") for line in proc.stdout.splitlines()
    ), (reason, proc.stdout, proc.stderr)
    return proc.stdout


def _stopped(proc: subprocess.CompletedProcess[str], token: str) -> str:
    """A nonzero exit and a stdout line that names ``token`` (exit code not fixed by the plan)."""
    assert proc.returncode != 0, (token, proc.stdout, proc.stderr)
    lines = [line for line in proc.stdout.splitlines() if token in line]
    assert lines, (token, proc.stdout, proc.stderr)
    return lines[0]


def _crashed(proc: subprocess.CompletedProcess[str]) -> None:
    assert proc.returncode == b3.CRASH_EXIT, (proc.returncode, proc.stdout, proc.stderr)


def _ready_tree(proc: subprocess.CompletedProcess[str], op: str = OP) -> str:
    """The tree id of the ``land_ready:<op>:<tree>`` line."""
    _ok(proc)
    prefix = f"land_ready:{op}:"
    trees = [
        line.strip()[len(prefix) :]
        for line in proc.stdout.splitlines()
        if line.strip().startswith(prefix)
    ]
    assert len(trees) == 1 and len(trees[0]) == 40, (proc.stdout, proc.stderr)
    return trees[0]


def _ready(land: Land, *, op: str = OP) -> str:
    """Steps 1-5 and an ``approved`` verdict: the tree of ``T``."""
    tree = _ready_tree(_prepare(land, op=op), op)
    _ok(_verdict(land, tree, op=op))
    return tree


def _landed(land: Land) -> tuple[str, str]:
    """A whole land through the human route: (tree of T, C)."""
    tree = _ready(land)
    _ok(_publish_human(land))
    return tree, land.rig.ref()


# ---------------------------------------------------------------------------
# Journal and git readers
# ---------------------------------------------------------------------------


def _op_file(land: Land, op: str = OP) -> Path | None:
    paths = sorted(land.rig.fx.store.glob(f"ops/*/*/{op}/op.json"))
    assert len(paths) <= 1, paths
    return paths[0] if paths else None


def _record(land: Land, op: str = OP) -> dict[str, Any] | None:
    path = _op_file(land, op)
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path
    return data


def _journal_bytes(land: Land, op: str = OP) -> bytes | None:
    path = _op_file(land, op)
    return path.read_bytes() if path is not None else None


def _phases(record: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    if record is None:
        return []
    return [
        (str(item.get("phase")), str(item.get("status")))
        for item in record.get("journal", [])
        if isinstance(item, dict)
    ]


def _fields(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """The land fields of an op record: the record, then each entry's identity and evidence."""
    merged: dict[str, Any] = {}
    if record is None:
        return merged
    merged.update({key: value for key, value in record.items() if key != "journal"})
    for item in record.get("journal", []):
        if not isinstance(item, dict):
            continue
        for part in ("identity", "evidence"):
            if isinstance(item.get(part), dict):
                merged.update(item[part])
    return merged


def _kept(land: Land, op: str = OP) -> dict[str, str]:
    """``refs/lanes/<slug>/<op>/*``: name -> object id."""
    out = land.git(
        "for-each-ref",
        "--format=%(refname) %(objectname)",
        f"refs/lanes/{land.slug}/{op}/",
    )
    kept: dict[str, str] = {}
    for line in out.splitlines():
        name, _, oid = line.strip().partition(" ")
        if name:
            kept[name.rsplit("/", 1)[-1]] = oid
    return kept


def _candidates(land: Land) -> list[Path]:
    """Every listed worktree under the fixture candidate root."""
    root = land.rig.candidate_root.resolve()
    found: list[Path] = []
    for line in land.git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree ") :]).resolve()
            if path == root or root in path.parents:
                found.append(path)
    return found


def _unequal_paths(land: Land, cwd: Path, commit: str) -> list[str]:
    """Paths whose index or tracked working file differs from ``commit`` (task carriers left out).

    ``run_parameters`` writes ``store_seq`` into each plan ``task.md`` (phase_b3
    ``Rig.worktree``), so the carriers are not compared.
    """
    land.git("update-index", "-q", "--refresh", cwd=cwd, check=False)
    names = land.git("diff-index", "--cached", "--name-only", commit, cwd=cwd)
    names += land.git("diff-files", "--name-only", cwd=cwd)
    return sorted(
        {
            name
            for name in names.splitlines()
            if name and not (name.startswith(f"{PLANS}/") and name.endswith("/task.md"))
        }
    )


def _snapshot(land: Land, op: str = OP) -> dict[str, Any]:
    """Lane ref, lane HEAD, lane index, card, journal, kept refs and ``main``."""
    index = land.git_dir(land.wt) / "index"
    return {
        "lane": land.tip(),
        "head": (land.git_dir(land.wt) / "HEAD").read_text(encoding="utf-8"),
        "index": index.read_bytes() if index.is_file() else None,
        "card": land.card_path.read_bytes(),
        "journal": _journal_bytes(land, op),
        "kept": _kept(land, op),
        "main": land.rig.ref(),
    }


def _lease_is_free(path: Path) -> None:
    holder = _Holder(path)
    holder.stop()


# ---------------------------------------------------------------------------
# AC-785.13 — step 1 freeze
# ---------------------------------------------------------------------------


def test_freeze_journals_before_it_marks_the_card(tmp_path: Path) -> None:
    land = _one(tmp_path)
    _crashed(_prepare(land, env=_crash("land:freeze:started")))
    record = _record(land)
    assert record is not None, "step 1 writes the journal entry first"
    assert _phases(record)[0][0] == "land:freeze", _phases(record)
    card = land.card()
    assert (card["state"], card["op"]) == ("active", None), card


def test_freeze_records_the_op_and_sets_the_card_landing(tmp_path: Path) -> None:
    land = _one(tmp_path)
    generation = land.card()["generation"]
    _ok(_prepare(land))
    fields = _fields(_record(land))
    assert ("land:freeze", "done") in _phases(_record(land)), _phases(_record(land))
    expected = {
        "op": OP,
        "lane": land.slug,
        "generation": generation,
        "session": land.session,
        "P": land.p,
        "L0": land.l0,
    }
    assert {key: fields.get(key) for key in expected} == expected, fields
    card = land.card()
    assert (card["state"], card["op"]) == ("landing", OP), card
    _lease_is_free(land.git_dir(land.wt) / GATE_LOCK)


def _dirty_lane(land: Land) -> str:
    (land.wt / FEATURE).write_bytes(b"FEATURE = 2\n")
    return land.l0


def _moved_lane(land: Land) -> str:
    (land.wt / LANE_DIR / "later.py").write_bytes(b"LATER = 1\n")
    land.git("add", "-A", cwd=land.wt)
    land.git("commit", "-q", "-m", "lane: later", cwd=land.wt)
    return land.l0


def _landing_card(land: Land) -> str:
    card = land.card()
    card.update(state="landing", op="op-other-1")
    land.card_path.write_text(json.dumps(card), encoding="utf-8")
    return land.l0


FREEZE_REFUSALS: dict[str, Callable[[Land], str]] = {
    "lane_dirty": _dirty_lane,
    "lane_moved": _moved_lane,
    "card_landing": _landing_card,
}


@pytest.mark.parametrize("reason", sorted(FREEZE_REFUSALS))
def test_freeze_refuses_without_a_journal(tmp_path: Path, reason: str) -> None:
    land = _one(tmp_path)
    l0 = FREEZE_REFUSALS[reason](land)
    before = _snapshot(land)
    _refused(_prepare(land, l0=l0), reason)
    assert _record(land) is None, "a freeze refusal writes no journal"
    assert _snapshot(land) == before


# ---------------------------------------------------------------------------
# AC-785.14 — step 2 rebase in a disposable candidate
# ---------------------------------------------------------------------------


def test_the_rebase_runs_in_a_candidate_and_leaves_the_lane_alone(
    tmp_path: Path,
) -> None:
    land = _one(tmp_path)
    head = (land.git_dir(land.wt) / "HEAD").read_bytes()
    _ok(_prepare(land))
    assert land.tip() == land.l0, "lane/<slug> never moves in a land"
    assert (land.git_dir(land.wt) / "HEAD").read_bytes() == head
    assert land.git("status", "--porcelain", cwd=land.wt) == ""
    assert land.git("rev-parse", "HEAD", cwd=land.wt).strip() == land.l0
    l1 = _fields(_record(land)).get("L1")
    assert isinstance(l1, str) and len(l1) == 40, _fields(_record(land))
    assert l1 != land.l0
    land.git("merge-base", "--is-ancestor", land.p, l1)
    changed = land.git("diff", "--name-only", land.p, l1).split()
    assert changed == [FEATURE], changed
    for candidate in _candidates(land):
        assert land.git(
            "rev-parse", "--symbolic-full-name", "HEAD", cwd=candidate
        ).strip() in (
            "HEAD",
            "",
        ), candidate


def test_a_rebase_conflict_journals_removes_the_candidate_and_reactivates(
    tmp_path: Path,
) -> None:
    land = _one(tmp_path, main_change={FEATURE: b"FEATURE = 'main'\n"})
    line = _stopped(_prepare(land), "land_conflict:")
    assert FEATURE in line, line
    assert "land:conflict" in [phase for phase, _ in _phases(_record(land))]
    card = land.card()
    assert (card["state"], card["op"]) == ("active", None), card
    assert _candidates(land) == [], "the conflicted candidate is removed"
    assert land.tip() == land.l0


def _outside(wt: Path) -> None:
    path = wt / "other" / "outside.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"outside\n")


def _rename_out(wt: Path) -> None:
    (wt / "docs").mkdir(parents=True, exist_ok=True)
    bf.git(wt, "mv", BASE_FILE, "docs/moved.py")


def _rename_in(wt: Path) -> None:
    bf.git(wt, "mv", OUTSIDE_SEED, "src/lane/inside.py")


def _locked(wt: Path) -> None:
    (wt / LOCKED_FILE).write_bytes(b"LOCKED = 2\n")


OWNS_CASES: dict[str, tuple[Changer, str]] = {
    "outside_owns": (_outside, "other/outside.txt"),
    "rename_out_counts_the_new_path": (_rename_out, "docs/moved.py"),
    "rename_in_counts_the_old_path": (_rename_in, OUTSIDE_SEED),
    "must_not_touch_wins": (_locked, LOCKED_FILE),
}


@pytest.mark.parametrize("case", sorted(OWNS_CASES))
def test_a_change_outside_owns_is_owns_violation(tmp_path: Path, case: str) -> None:
    change, path = OWNS_CASES[case]
    land = _one(tmp_path, lane_change=change, mnt=[LOCKED_FILE])
    _refused(_prepare(land), f"owns_violation:{path}")
    assert land.tip() == land.l0


# ---------------------------------------------------------------------------
# AC-785.16 — step 4 keeps the objects; recovery reuses them
# ---------------------------------------------------------------------------


def test_the_kept_refs_survive_a_changed_candidate_and_recovery_reuses_them(
    tmp_path: Path,
) -> None:
    land = _one(tmp_path)
    _crashed(_prepare(land, env=_crash("land:kept:done")))
    kept = _kept(land)
    assert set(kept) == {"L0", "L1", "T"}, kept
    assert kept["L0"] == land.l0
    assert kept["L1"] == _fields(_record(land)).get("L1")
    assert land.git("cat-file", "-t", kept["T"]).strip() == "commit"
    kept_tree = land.git("rev-parse", f"{kept['T']}^{{tree}}").strip()
    candidates = _candidates(land)
    assert candidates, "the candidate exists between steps 2 and 9"
    for candidate in candidates:
        (candidate / FEATURE).write_bytes(b"FEATURE = 'tampered'\n")
        (candidate / "stray.txt").write_bytes(b"stray\n")
    tree = _ready_tree(_recover(land))
    assert tree == kept_tree, "recovery restores T from the kept refs"
    assert _kept(land) == kept, "recovery never rebuilds L1 or T"


# ---------------------------------------------------------------------------
# AC-785.17 — step 5 gate, report and verdict
# ---------------------------------------------------------------------------


def test_prepare_ends_land_ready_with_the_tree_of_t_and_the_review_inputs(
    tmp_path: Path,
) -> None:
    land = _one(tmp_path)
    proc = _prepare(land)
    tree = _ready_tree(proc)
    kept = _kept(land)
    assert land.git("rev-parse", f"{kept['T']}^{{tree}}").strip() == tree
    record = _record(land)
    assert ("land:ready", "done") in _phases(record), _phases(record)
    gate = _fields(record).get("gate")
    assert isinstance(gate, dict) and gate.get("tree") == tree, gate
    assert "result" in gate, gate
    mb = land.git("merge-base", land.p, land.l0).strip()
    assert "range-diff" in proc.stdout, proc.stdout
    assert f"{mb}..{land.l0}" in proc.stdout, proc.stdout
    assert f"{land.p}..{kept['L1']}" in proc.stdout, proc.stdout


def test_an_approved_verdict_for_the_tree_of_t_is_recorded(tmp_path: Path) -> None:
    land = _one(tmp_path)
    tree = _ready_tree(_prepare(land))
    _ok(_verdict(land, tree))
    verdict = _fields(_record(land)).get("verdict")
    assert isinstance(verdict, dict), _fields(_record(land))
    assert (verdict.get("tree"), verdict.get("verdict")) == (tree, "approved")


def _stale(land: Land, tree: str) -> subprocess.CompletedProcess[str]:
    return _verdict(land, land.git("rev-parse", f"{land.p}^{{tree}}").strip())


def _not_approved(land: Land, tree: str) -> subprocess.CompletedProcess[str]:
    return _verdict(land, tree, verdict="changes_required")


def _unknown_key(land: Land, tree: str) -> subprocess.CompletedProcess[str]:
    return _verdict(land, tree, extra={"note": "extra"})


VERDICT_REFUSALS: dict[str, Callable[[Land, str], subprocess.CompletedProcess[str]]] = {
    "verdict_stale": _stale,
    "verdict_not_approved": _not_approved,
    "verdict_schema:note": _unknown_key,
}


@pytest.mark.parametrize("reason", sorted(VERDICT_REFUSALS))
def test_a_bad_verdict_is_refused_and_records_nothing(
    tmp_path: Path, reason: str
) -> None:
    land = _one(tmp_path)
    tree = _ready_tree(_prepare(land))
    before = _journal_bytes(land)
    _refused(VERDICT_REFUSALS[reason](land, tree), reason)
    assert _journal_bytes(land) == before


# ---------------------------------------------------------------------------
# AC-785.19 — step 7 publish
# ---------------------------------------------------------------------------


def test_publish_from_the_lane_worktree_publishes_t_as_one_commit_on_p(
    tmp_path: Path,
) -> None:
    land = _one(tmp_path)
    tree = _ready(land)
    _ok(_publish_human(land, cwd=land.wt))
    c = land.rig.ref()
    assert land.rig.parents(c) == [land.p], "one main commit on P"
    assert land.git("rev-parse", f"{c}^{{tree}}").strip() == tree, "tree(C) == tree(T)"
    assert ("published", "done") in _phases(_record(land)), _phases(_record(land))


def _halt(land: Land) -> None:
    halt = land.common / "lanes" / "HALT"
    halt.parent.mkdir(parents=True, exist_ok=True)
    halt.write_bytes(b"")


def test_publish_stops_under_halt_without_a_write(tmp_path: Path) -> None:
    land = _one(tmp_path)
    _ready(land)
    _halt(land)
    before = _snapshot(land)
    proc = _publish_human(land)
    assert proc.returncode != 0, (proc.stdout, proc.stderr)
    assert "halt" in (proc.stdout + proc.stderr).lower(), (proc.stdout, proc.stderr)
    assert _snapshot(land) == before


def test_publish_is_land_busy_while_another_land_is_between_publication_and_close(
    tmp_path: Path,
) -> None:
    land, other = _build(tmp_path, second=True)
    assert other is not None
    _ready(land)
    _ready(other, op=OP_B)
    _crashed(_publish_grant(other, op=OP_B, env=_crash("land:sync:started")))
    main = land.rig.ref()
    assert main != land.p, "lane B published"
    card = land.card_path.read_bytes()
    _refused(_publish_human(land), f"land_busy:{OP_B}")
    assert land.rig.ref() == main
    assert land.card_path.read_bytes() == card


def test_a_moved_main_is_main_moved_and_the_card_goes_back_to_active(
    tmp_path: Path,
) -> None:
    land = _one(tmp_path)
    _ready(land)
    moved = land.rig.seed({"src/late.txt": b"late\n"}, message="main: late")
    _refused(_publish_human(land), "main_moved")
    assert land.rig.ref() == moved
    card = land.card()
    assert (card["state"], card["op"]) == ("active", None), card


def test_a_dirty_main_tree_is_main_dirty(tmp_path: Path) -> None:
    land = _one(tmp_path)
    _ready(land)
    (land.repo / MAIN_SIDE).write_bytes(b"edited in main\n")
    _refused(_publish_human(land), f"main_dirty:{MAIN_SIDE}")
    assert land.rig.ref() == land.p


def test_a_hook_that_changes_the_tree_is_hook_drift(tmp_path: Path) -> None:
    land = _one(tmp_path)
    _ready(land)
    land.rig.install_hook(
        "pre-commit", "echo drift > drift.txt\ngit add drift.txt\nexit 0"
    )
    _refused(_publish_human(land), "hook_drift")
    assert land.rig.ref() == land.p


# ---------------------------------------------------------------------------
# AC-785.21 — step 8 synchronizes the main checkout
# ---------------------------------------------------------------------------


def test_sync_leaves_the_main_index_and_tracked_files_at_c(tmp_path: Path) -> None:
    land = _one(tmp_path)
    _ready(land)
    _ok(_publish_human(land))
    c = land.rig.ref()
    assert ("land:sync", "done") in _phases(_record(land)), _phases(_record(land))
    assert _unequal_paths(land, land.repo, c) == []
    assert (land.repo / FEATURE).read_bytes() == b"FEATURE = 1\n"


def test_an_index_at_c_with_files_at_p_is_not_a_finished_sync(tmp_path: Path) -> None:
    land = _one(tmp_path)
    _ready(land)
    _crashed(_publish_human(land, env=_crash("land:sync:started")))
    c = land.rig.ref()
    assert c != land.p
    land.git("read-tree", c)
    assert _unequal_paths(land, land.repo, c) != [], "the files are still at P"
    proc = _recover(land)
    synced = ("land:sync", "done") in _phases(_record(land))
    assert synced or proc.returncode != 0, (proc.stdout, proc.stderr)
    assert not synced or _unequal_paths(land, land.repo, c) == [], (
        "the sync step completes only when the index and the files equal C"
    )
    assert "sync_unexplained" not in proc.stdout, proc.stdout


def test_an_unexplained_path_stops_the_sync_and_blocks_every_publication(
    tmp_path: Path,
) -> None:
    land = _one(tmp_path)
    _ready(land)
    _crashed(_publish_human(land, env=_crash("land:sync:started")))
    c = land.rig.ref()
    stray = land.repo / FEATURE
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"FEATURE = 'neither'\n")
    line = _stopped(_recover(land), "sync_unexplained:")
    assert FEATURE in line, line
    assert "land:closed" not in [phase for phase, _ in _phases(_record(land))]
    assert stray.read_bytes() == b"FEATURE = 'neither'\n"
    land.rig.reserve("op-other-1")
    code, out, text = land.rig.commit(
        "op-other-1", land.rig.packet(files={"other.txt": b"other\n"})
    )
    assert (code, out.get("reason")) == (1, f"sync_pending:{OP}"), text
    assert land.rig.ref() == c


# ---------------------------------------------------------------------------
# AC-785.22 — step 9 close
# ---------------------------------------------------------------------------


def test_close_deletes_the_kept_refs_journals_closed_and_keeps_the_card_landing(
    tmp_path: Path,
) -> None:
    land = _one(tmp_path)
    _landed(land)
    assert _kept(land) == {}, "close deletes refs/lanes/<slug>/<op>/*"
    assert "land:closed" in [phase for phase, _ in _phases(_record(land))]
    card = land.card()
    assert (card["state"], card["op"]) == ("landing", OP), card
    _lease_is_free(land.git_dir(land.repo) / GATE_LOCK)


def test_a_second_close_is_land_closed_and_changes_nothing(tmp_path: Path) -> None:
    land = _one(tmp_path)
    _landed(land)
    before = _snapshot(land)
    proc = _recover(land)
    _ok(proc)
    assert f"land_closed:{OP}" in proc.stdout, proc.stdout
    assert _snapshot(land) == before


# ---------------------------------------------------------------------------
# AC-785.24 — the land is Windows-only
# ---------------------------------------------------------------------------


def _main_code(lanes: ModuleType, argv: list[str]) -> int | str | None:
    try:
        return lanes.main(argv, wait_s=WAIT_S, poll_s=POLL_S)
    except SystemExit as exc:  # argparse usage exit: reported, not raised
        return exc.code


LAND_VERBS: dict[str, Callable[[Land], list[str]]] = {
    "prepare": lambda land: [
        "land",
        "prepare",
        "--worktree",
        str(land.wt),
        "--l0",
        land.l0,
        "--message-file",
        str(land.message),
        "--op",
        OP,
    ],
    "publish": lambda land: ["land", "publish", "--op", OP],
    "recover": lambda land: ["land", "recover", "--op", OP],
}


@pytest.mark.parametrize("verb", sorted(LAND_VERBS))
def test_the_land_refuses_on_a_non_windows_platform_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verb: str,
) -> None:
    land = _one(tmp_path)
    before = _snapshot(land)
    lanes = _lanes()
    for key, value in land.rig.fx.env(**{SESSION_ENV: land.session}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(b3.CRASH, raising=False)
    monkeypatch.chdir(land.wt)
    monkeypatch.setattr(sys, "platform", "linux")
    code = _main_code(lanes, LAND_VERBS[verb](land))
    monkeypatch.setattr(sys, "platform", "win32")
    out = capsys.readouterr().out
    assert code == 1, (code, out)
    assert "land_unsupported_platform" in out, out
    assert _record(land) is None
    assert _snapshot(land) == before


# ---------------------------------------------------------------------------
# AC-785.8 (EA-12) — release --reset after a closed land
# ---------------------------------------------------------------------------


def test_release_reset_moves_the_lane_from_l0_to_c_and_releases(tmp_path: Path) -> None:
    land = _one(tmp_path)
    _, c = _landed(land)
    assert land.tip() == land.l0
    _ok(_release_reset(land))
    assert land.tip() == c
    assert land.git("symbolic-ref", "HEAD", cwd=land.wt).strip() == land.branch_ref, (
        "the lane keeps its symbolic HEAD"
    )
    assert _unequal_paths(land, land.wt, c) == []
    assert land.git("status", "--porcelain", "--untracked-files=all", cwd=land.wt) == ""
    assert land.card()["state"] == "released"


def _closed_then_dirty(land: Land) -> None:
    _landed(land)
    (land.wt / FEATURE).write_bytes(b"FEATURE = 'dirty'\n")


def _closed_then_moved(land: Land) -> None:
    _landed(land)
    (land.wt / LANE_DIR / "after.py").write_bytes(b"AFTER = 1\n")
    land.git("add", "-A", cwd=land.wt)
    land.git("commit", "-q", "-m", "lane: after the land", cwd=land.wt)


def _still_open(land: Land) -> None:
    _ready(land)


RESET_REFUSALS: dict[str, Callable[[Land], None]] = {
    "lane_dirty": _closed_then_dirty,
    "lane_moved": _closed_then_moved,
    "land_open": _still_open,
}


@pytest.mark.parametrize("reason", sorted(RESET_REFUSALS))
def test_release_reset_refuses_without_a_ref_or_file_change(
    tmp_path: Path, reason: str
) -> None:
    land = _one(tmp_path)
    RESET_REFUSALS[reason](land)
    before = _snapshot(land)
    files = {
        rel: (land.wt / rel).read_bytes()
        for rel in (FEATURE, BASE_FILE)
        if (land.wt / rel).is_file()
    }
    _refused(_release_reset(land), reason)
    assert _snapshot(land) == before
    assert {rel: (land.wt / rel).read_bytes() for rel in files} == files


# ---------------------------------------------------------------------------
# AC-785.12 (EA-12) — the journal and the card are read again after the op lease
# ---------------------------------------------------------------------------


def _supersede(land: Land) -> None:
    card = land.card()
    card["generation"] = OTHER_GENERATION
    land.card_path.write_text(json.dumps(card), encoding="utf-8")


def _rewind(land: Land) -> None:
    path = _op_file(land)
    assert path is not None
    record = json.loads(path.read_text(encoding="utf-8"))
    record["journal"] = record["journal"][:-1]
    path.write_bytes(json.dumps(record, indent=2).encode("utf-8"))


REREAD_CASES: dict[str, Callable[[Land], None]] = {
    "card_superseded": _supersede,
    "journal_moved": _rewind,
}


@pytest.mark.parametrize("reason", sorted(REREAD_CASES))
def test_recovery_reads_the_journal_and_the_card_again_after_the_op_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reason: str,
) -> None:
    land = _one(tmp_path)
    _crashed(_prepare(land, env=_crash("land:kept:done")))
    lanes = _lanes()
    os_lease = importlib.import_module("tools.os_lease")
    real_acquire = os_lease.acquire
    changed: list[str] = []

    def acquire(path: Path, *args: object, **kwargs: object) -> object:
        lease = real_acquire(path, *args, **kwargs)
        if Path(path).name == f"{OP}.lease" and not changed:
            REREAD_CASES[reason](land)
            changed.append(str(path))
        return lease

    for key, value in land.rig.fx.env(**{SESSION_ENV: land.session}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(b3.CRASH, raising=False)
    monkeypatch.setattr(os_lease, "acquire", acquire)
    monkeypatch.chdir(land.wt)
    kept = _kept(land)
    code = _main_code(lanes, ["land", "recover", "--op", OP])
    out = capsys.readouterr().out
    assert changed, "recovery takes the per-op lease <common>/lanes/ops/<op>.lease"
    after = {"card": land.card_path.read_bytes(), "journal": _journal_bytes(land)}
    assert code == 1, (code, out)
    assert any(line.startswith(f"refused: {reason}") for line in out.splitlines()), out
    assert _kept(land) == kept
    assert {
        "card": land.card_path.read_bytes(),
        "journal": _journal_bytes(land),
    } == after, "no write after the refusal"
