"""MEU-785 AC-785.23: land recovery, one test per row of the recovery table — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.23 (design D:254-266, §10b N-6; boundary rows IP:147, IP:150, IP:155; AD-15).

Recovery is ``lanes.py land recover --op <op>`` (or a re-run with the same op). Each row of
the design's recovery table (D:258-266, nine rows; the fixture copy
``lanes_fixtures/recovery-table.md``) has one parametrized case, and
:func:`test_the_parametrization_has_one_case_per_recovery_row` checks that the cases and
the table rows are the same set. Crashes are injected through
``RUN_PARAMETERS_TEST_CRASH_AT`` (``tools/run_parameters.py:209``, read in a marked store):
the land names ``land:<phase>:<started|done>`` (IP:155) and, for the publication step, the
``commit_batch.py`` names ``commit:published:<started|effect>`` (``commit_batch.py:561-566``).
A crashed child exits 97.

After publication, recovery resumes sync and close and never step 1 (no second
``land:freeze`` entry). "Publish again" keeps the ``commit_batch.py`` conditions
(``_step_published``: an informative reflog, no earlier ``P -> C``, the expected current
ref): an earlier ``P -> C`` refuses ``publication_unclear``. An unknown journal phase
refuses ``recovery_unclear:<phase>``. Recovery never touches a card with another
generation or op.

Every repository is a disposable ``phase_b3`` fixture (``git init -b main``, SSH signing, a
marked run-parameters store) in ``tmp_path``, built inside the test body. The lane rig here
(:func:`lane_rig`) is shared with ``test_lanes_acceptance.py``. Tests reach new symbols at
run time. Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import lane_worktree_config as lwc

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "tools" / "lanes.py"
# The recovery table of the multi-agent lanes design (section 5.5), copied verbatim.
DESIGN = Path(__file__).resolve().parent / "lanes_fixtures" / "recovery-table.md"
PLANS = "docs/execution/plans"
HANDOFFS = ".agent/context/handoffs"
METRICS = "docs/execution/metrics.md"
METRICS_HEAD = "| Date | Lane | Note |\n|---|---|---|\n"
SESSION_ENV = "{{PROJECT_NAME_UPPER}}_SESSION"
CARD_SESSION = "s-lane-a"
OTHER_GENERATION = "f" * 16
OP = "op-land-1"
CRASH = b3.CRASH
CRASH_EXIT = b3.CRASH_EXIT
CLI_TIMEOUT_S = 240
GATE_LOCK = "{{PROJECT_NAME}}-gate.lock"
TABLE_HEAD = "| Crash point | Recovery |"

HOLDER = """
import os
import sys
from pathlib import Path

from tools import os_lease

for raw in sys.argv[1:]:
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    os_lease.acquire(path, wait_s=0.0, body=b'{"pid": %d}' % os.getpid())
print("held", flush=True)
os._exit(0)
"""


# ---------------------------------------------------------------------------
# The lane rig (shared with test_lanes_acceptance.py)
# ---------------------------------------------------------------------------


@dataclass
class LaneRig:
    """A ``phase_b3`` fixture with one claimed lane ``lane/<plan>`` holding one commit."""

    rig: b3.Rig
    plan: str
    session: str
    wt: Path
    scratch: Path
    message: Path
    p: str
    l0: str
    changed: str

    @property
    def repo(self) -> Path:
        return self.rig.repo

    @property
    def common(self) -> Path:
        return self.rig.fx.common_dir

    @property
    def card_path(self) -> Path:
        return self.common / "lanes" / f"{self.plan}.json"

    @property
    def branch_ref(self) -> str:
        return f"refs/heads/lane/{self.plan}"


def git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd``; assert exit 0; return stripped stdout."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=b3_env(),
        timeout=CLI_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (args, proc.stdout, proc.stderr)
    return proc.stdout.strip()


def b3_env() -> dict[str, str]:
    """The fixture git environment (no ``GIT_*`` redirects, no system config)."""
    return bf.git_env()


def ownership(owns: list[str]) -> str:
    """The ``## Lane Ownership`` block a lane's ``task.md`` carries (``lanes.py claim``)."""
    return (
        "\n## Lane Ownership\n\n```yaml\nowns:\n"
        + "".join(f"  - {item}\n" for item in owns)
        + "must_not_touch: []\n```\n"
    )


def handoff_text(plan: str, requests: list[str]) -> str:
    """A lane handoff with an ``## Integration requests`` table, one code span per request.

    A ``|`` inside a request is escaped (``\\|``), as a GFM table cell requires.
    """
    rows = "".join(
        f"| `{{gen}}/{n}` | `{request.replace('|', chr(92) + '|')}` |\n"
        for n, request in enumerate(requests, 1)
    )
    return (
        f"# {plan} handoff\n\n## Integration requests\n\n| Id | Request |\n|----|---------|\n"
        + rows
    )


def lanes(
    cwd: Path,
    fx_env: Callable[..., dict[str, str]],
    *args: str,
    session: str,
    env: Mapping[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """``python tools/lanes.py <args>`` in ``cwd`` with the fixture environment."""
    extra: dict[str, str | None] = {SESSION_ENV: session}
    extra.update(env or {})
    return subprocess.run(
        [sys.executable, str(LANES), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=fx_env(**extra),
        timeout=CLI_TIMEOUT_S,
        check=False,
    )


def ensure_task(rig: b3.Rig, plan: str) -> Path:
    """``plan``'s ``task.md``; a copy of the fixture plan's when the fixture has none."""
    task = rig.fx.task_path(plan)
    if not task.is_file():
        source = rig.fx.task_path(rig.plan)
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_bytes(source.read_bytes().replace(rig.plan.encode(), plan.encode()))
    return task


def seed_plan(rig: b3.Rig, plan: str, extra: Mapping[str, bytes] | None = None) -> str:
    """Give ``plan``'s ``task.md`` a Lane Ownership block (and ``extra`` files); return P."""
    task = ensure_task(rig, plan)
    # Stage 1 owns entries are exact paths or ``/`` folders, never name prefixes.
    owns = [
        f"src/{plan}/",
        f"{HANDOFFS}/{plan}-handoff.md",
        f"{HANDOFFS}/{plan}-implementation-critical-review.md",
    ]
    files = {
        task.relative_to(rig.repo).as_posix(): (
            task.read_text(encoding="utf-8") + ownership(owns)
        ).encode("utf-8")
    }
    files.update(extra or {})
    return rig.seed(files, message=f"fixture: lane ownership of {plan}")


def open_lane(
    rig: b3.Rig,
    tmp_path: Path,
    plan: str,
    session: str,
    requests: list[str] | None = None,
) -> LaneRig:
    """Create ``lane/<plan>`` at ``main``, claim it, commit one change and the handoff."""
    p = rig.ref()
    wt = tmp_path / "lanes" / plan
    wt.parent.mkdir(parents=True, exist_ok=True)
    git(rig.repo, "worktree", "add", "-q", "-b", f"lane/{plan}", str(wt), "main")
    claim = lanes(
        wt,
        rig.fx.env,
        "claim",
        "--plan",
        f"{PLANS}/{plan}",
        "--worktree",
        str(wt),
        "--session",
        session,
        session=session,
    )
    assert claim.returncode == 0, (claim.stdout, claim.stderr)
    card = json.loads((rig.fx.common_dir / "lanes" / f"{plan}.json").read_text("utf-8"))
    generation = str(card["generation"])
    changed = f"src/{plan}/lane.py"
    (wt / changed).parent.mkdir(parents=True, exist_ok=True)
    (wt / changed).write_bytes(f"LANE = {plan!r}\n".encode())
    handoff = wt / HANDOFFS / f"{plan}-handoff.md"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(
        handoff_text(plan, requests or []).replace("{gen}", f"{plan}/{generation}"),
        encoding="utf-8",
        newline="\n",
    )
    review = wt / HANDOFFS / f"{plan}-implementation-critical-review.md"
    review.write_text("# Review\n\nVerdict: approved\n", encoding="utf-8", newline="\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", f"lane: work of {plan}")
    scratch = tmp_path / "scratch" / plan
    scratch.mkdir(parents=True, exist_ok=True)
    message = scratch / "land-message.txt"
    message.write_bytes(f"feat: land the {plan} lane\n".encode())
    return LaneRig(
        rig=rig,
        plan=plan,
        session=session,
        wt=wt.resolve(),
        scratch=scratch,
        message=message,
        p=p,
        l0=git(wt, "rev-parse", "HEAD"),
        changed=changed,
    )


def lane_rig(tmp_path: Path) -> LaneRig:
    """One fixture, one lane on the fixture plan; the plan is bound for the human route."""
    rig = b3.rig(tmp_path / "fx", ROOT, seed=lwc.SEED)
    # Bind first: ``bind`` writes the task.md frontmatter, and the seed commits it, so the
    # main tree is clean at P (the B-R1 rig order, test_lanes_land.py).
    rig.bind()
    seed_plan(rig, rig.plan, {METRICS: METRICS_HEAD.encode()})
    return open_lane(rig, tmp_path, rig.plan, CARD_SESSION)


def run(
    lr: LaneRig, *args: str, env: Mapping[str, str | None] | None = None
) -> subprocess.CompletedProcess[str]:
    return lanes(lr.wt, lr.rig.fx.env, *args, session=lr.session, env=env)


def prepare(
    lr: LaneRig, op: str = OP, env: Mapping[str, str | None] | None = None
) -> subprocess.CompletedProcess[str]:
    """``land prepare --worktree W --l0 L0 --message-file F --op ID`` (IP:144)."""
    return run(
        lr,
        "land",
        "prepare",
        "--worktree",
        str(lr.wt),
        "--l0",
        lr.l0,
        "--message-file",
        str(lr.message),
        "--op",
        op,
        env=env,
    )


def ready_tree(proc: subprocess.CompletedProcess[str], op: str = OP) -> str:
    """The tree id of ``land_ready:<op>:<tree>`` (AC-785.17)."""
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    trees = [
        line.split(":", 2)[2].strip()
        for line in proc.stdout.splitlines()
        if line.startswith(f"land_ready:{op}:")
    ]
    assert len(trees) == 1, (proc.stdout, proc.stderr)
    return trees[0]


def record_verdict(lr: LaneRig, tree: str, op: str = OP) -> None:
    """``land prepare --op ID --verdict FILE`` with an ``approved`` ``land-verdict/1`` (IP:145)."""
    verdict = lr.scratch / f"verdict-{op}.json"
    verdict.write_text(
        json.dumps(
            {
                "schema": "land-verdict/1",
                "op": op,
                "tree": tree,
                "verdict": "approved",
                "review": f"{HANDOFFS}/{lr.plan}-implementation-critical-review.md",
            }
        ),
        encoding="utf-8",
    )
    proc = run(lr, "land", "prepare", "--op", op, "--verdict", str(verdict))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


def ready(lr: LaneRig, op: str = OP) -> str:
    """Prepare and record an approved verdict; return tree(T)."""
    tree = ready_tree(prepare(lr, op), op)
    record_verdict(lr, tree, op)
    return tree


def publish(
    lr: LaneRig, op: str = OP, env: Mapping[str, str | None] | None = None
) -> subprocess.CompletedProcess[str]:
    """``land publish`` through the fixture human route (AC-785.18 sentence).

    The ``commit_batch.py`` human route (``_human_route``) reads one typed human record of
    the session and its consent; it needs no plan binding.
    """
    session = lr.rig.fx.session
    uid = lr.rig.fx.add_human(f"Commit the {lr.plan} plan on main.", session=session)
    return run(
        lr,
        "land",
        "publish",
        "--op",
        op,
        "--human-directed",
        "--session",
        session,
        "--message-uuid",
        uid,
        env=env,
    )


def recover(lr: LaneRig, op: str = OP) -> subprocess.CompletedProcess[str]:
    return run(lr, "land", "recover", "--op", op)


def crashed(proc: subprocess.CompletedProcess[str]) -> None:
    assert proc.returncode == CRASH_EXIT, (proc.returncode, proc.stdout, proc.stderr)


def ok(proc: subprocess.CompletedProcess[str]) -> str:
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return proc.stdout


def refused(proc: subprocess.CompletedProcess[str], reason: str) -> None:
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert any(
        line.startswith(f"refused: {reason}") for line in proc.stdout.splitlines()
    ), (reason, proc.stdout, proc.stderr)


def op_file(lr: LaneRig, op: str = OP) -> Path:
    """The land op's ``op.json`` in the commit_batch op store (IP:150); exactly one."""
    found = sorted(lr.rig.fx.store.glob(f"ops/*/*/{op}/op.json"))
    assert len(found) == 1, found
    return found[0]


def phases(lr: LaneRig, op: str = OP) -> list[tuple[str, str]]:
    record = json.loads(op_file(lr, op).read_text(encoding="utf-8"))
    return [(str(item["phase"]), str(item["status"])) for item in record["journal"]]


def card(lr: LaneRig) -> dict[str, Any]:
    data = json.loads(lr.card_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), data
    return data


def kept_refs(lr: LaneRig, op: str = OP) -> dict[str, str]:
    """``{L0|L1|T: id}`` of ``refs/lanes/<slug>/<op>/`` (AC-785.16)."""
    prefix = f"refs/lanes/{lr.plan}/{op}/"
    out = git(lr.repo, "for-each-ref", "--format=%(refname) %(objectname)", prefix)
    return {
        line.split()[0][len(prefix) :]: line.split()[1]
        for line in out.splitlines()
        if line.strip()
    }


def worktrees(lr: LaneRig) -> set[Path]:
    out = git(lr.repo, "worktree", "list", "--porcelain")
    return {
        Path(line[len("worktree ") :]).resolve()
        for line in out.splitlines()
        if line.startswith("worktree ")
    }


def main_ref(lr: LaneRig) -> str:
    return git(lr.repo, "rev-parse", "refs/heads/main")


def assert_main_tree_at(lr: LaneRig, commit: str) -> None:
    """The main checkout's HEAD, index and tracked working files equal ``commit``."""
    assert git(lr.repo, "rev-parse", "HEAD") == commit
    assert git(lr.repo, "diff-index", "--cached", "--name-only", commit) == ""
    assert git(lr.repo, "diff-files", "--name-only") == ""


def assert_closed(lr: LaneRig, op: str = OP) -> None:
    assert phases(lr, op)[-1] == ("land:closed", "done"), phases(lr, op)
    assert kept_refs(lr, op) == {}


def freezes(lr: LaneRig, op: str = OP) -> int:
    return sum(1 for phase, _status in phases(lr, op) if phase == "land:freeze")


# ---------------------------------------------------------------------------
# One case per row of the recovery table (D:258-266)
# ---------------------------------------------------------------------------


def _row_lease_of_an_exited_process(tmp_path: Path) -> None:
    lr = lane_rig(tmp_path)
    lane_lease = Path(git(lr.wt, "rev-parse", "--absolute-git-dir")) / GATE_LOCK
    registry = lr.common / "lanes" / "registry.lock"
    holder = subprocess.run(
        [sys.executable, "-c", HOLDER, str(lane_lease), str(registry)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=lr.rig.fx.env(),
        timeout=CLI_TIMEOUT_S,
        check=False,
    )
    assert (holder.returncode, holder.stdout.strip()) == (0, "held"), holder.stderr
    tree = ready_tree(prepare(lr))
    assert (card(lr)["state"], card(lr).get("op")) == ("landing", OP)
    assert git(lr.repo, "rev-parse", f"{kept_refs(lr)['T']}^{{tree}}") == tree


def _row_freeze_journal_written(tmp_path: Path) -> None:
    lr = lane_rig(tmp_path)
    generation = card(lr)["generation"]
    crashed(prepare(lr, env={CRASH: "land:freeze:started"}))
    assert phases(lr)[-1] == ("land:freeze", "started")
    assert (card(lr)["state"], card(lr).get("op")) == ("active", None)
    ok(recover(lr))
    after = card(lr)
    assert after["generation"] == generation
    # Resumed (landing with this op) or abandoned (active, no op): never reserved twice.
    assert (after["state"], after.get("op")) in {("active", None), ("landing", OP)}
    assert git(lr.repo, "rev-parse", lr.branch_ref) == lr.l0
    assert main_ref(lr) == lr.p
    op_file(lr)
    settled = lr.card_path.read_bytes()
    ok(recover(lr))
    assert lr.card_path.read_bytes() == settled


def _row_freeze_done_before_kept(tmp_path: Path) -> None:
    lr = lane_rig(tmp_path)
    crashed(prepare(lr, env={CRASH: "land:rebase:started"}))
    assert (card(lr)["state"], card(lr).get("op")) == ("landing", OP)
    ok(recover(lr))
    assert (card(lr)["state"], card(lr).get("op")) == ("active", None)
    assert worktrees(lr) == {lr.repo.resolve(), lr.wt}
    assert git(lr.repo, "rev-parse", lr.branch_ref) == lr.l0
    assert git(lr.wt, "status", "--porcelain") == ""
    assert kept_refs(lr) == {}
    assert main_ref(lr) == lr.p


def _row_kept_and_tested(tmp_path: Path) -> None:
    lr = lane_rig(tmp_path)
    crashed(prepare(lr, env={CRASH: "land:kept:done"}))
    kept = kept_refs(lr)
    assert sorted(kept) == ["L0", "L1", "T"], kept
    tree = ready_tree(recover(lr))
    assert tree == git(lr.repo, "rev-parse", f"{kept['T']}^{{tree}}")
    assert kept_refs(lr) == kept, "recovery rebuilt the kept objects"


def _row_waiting_for_authority(tmp_path: Path) -> None:
    from tools import os_lease

    lr = lane_rig(tmp_path)
    crashed(prepare(lr, env={CRASH: "land:ready:done"}))
    journal = op_file(lr).read_bytes()
    reserved = lr.card_path.read_bytes()
    ok(recover(lr))
    assert op_file(lr).read_bytes() == journal
    assert lr.card_path.read_bytes() == reserved
    assert main_ref(lr) == lr.p
    for lock in (lr.common / "lanes" / "registry.lock", lr.common / GATE_LOCK):
        lease = os_lease.acquire(lock, wait_s=0.0, body=b"{}")
        os_lease.release(lease)


def _row_ref_not_updated(tmp_path: Path) -> None:
    lr = lane_rig(tmp_path)
    tree = ready(lr)
    crashed(publish(lr, env={CRASH: "commit:published:started"}))
    assert main_ref(lr) == lr.p
    before = freezes(lr)
    ok(recover(lr))
    c = main_ref(lr)
    assert git(lr.repo, "rev-list", "--parents", "-n", "1", c).split()[1:] == [lr.p]
    assert git(lr.repo, "rev-parse", f"{c}^{{tree}}") == tree
    assert lr.rig.reflog().count((lr.p, c)) == 1
    assert freezes(lr) == before, "recovery after publication restarted step 1"
    assert_closed(lr)
    assert_main_tree_at(lr, c)


def _row_ref_updated_record_missing(tmp_path: Path) -> None:
    lr = lane_rig(tmp_path)
    tree = ready(lr)
    crashed(publish(lr, env={CRASH: "commit:published:effect"}))
    c = main_ref(lr)
    assert c != lr.p
    before = freezes(lr)
    ok(recover(lr))
    assert main_ref(lr) == c, "recovery published twice"
    assert git(lr.repo, "rev-parse", f"{c}^{{tree}}") == tree
    assert lr.rig.reflog().count((lr.p, c)) == 1
    assert freezes(lr) == before
    assert_closed(lr)
    assert_main_tree_at(lr, c)


def _row_sync_partly_done(tmp_path: Path) -> None:
    lr = lane_rig(tmp_path)
    ready(lr)
    crashed(publish(lr, env={CRASH: "land:sync:started"}))
    c = main_ref(lr)
    assert c != lr.p
    ok(recover(lr))
    assert main_ref(lr) == c
    assert (lr.repo / lr.changed).read_bytes() == (lr.wt / lr.changed).read_bytes()
    assert_closed(lr)
    assert_main_tree_at(lr, c)


def _row_close(tmp_path: Path) -> None:
    lr = lane_rig(tmp_path)
    ready(lr)
    crashed(publish(lr, env={CRASH: "land:closed:started"}))
    other = card(lr)
    other["generation"] = OTHER_GENERATION
    lr.card_path.write_text(json.dumps(other, indent=2) + "\n", encoding="utf-8")
    foreign = lr.card_path.read_bytes()
    ok(recover(lr))
    assert_closed(lr)
    assert lr.card_path.read_bytes() == foreign, "recovery touched another generation"
    journal = op_file(lr).read_bytes()
    again = ok(recover(lr))
    assert f"land_closed:{OP}" in again
    assert op_file(lr).read_bytes() == journal


@dataclass(frozen=True)
class Row:
    """One recovery-table row: its ``Crash point`` cell (verbatim) and its case."""

    point: str
    case: Callable[[Path], None]


ROWS: tuple[Row, ...] = (
    Row(
        "A lease or the registry lock held by an exited process",
        _row_lease_of_an_exited_process,
    ),
    Row("Step 1, journal written, card still `active`", _row_freeze_journal_written),
    Row("Step 1 done, before step 4", _row_freeze_done_before_kept),
    Row("Steps 4–5", _row_kept_and_tested),
    Row("Step 6", _row_waiting_for_authority),
    Row("Step 7, ref not updated", _row_ref_not_updated),
    Row("Step 7, ref updated, record missing", _row_ref_updated_record_missing),
    Row("Step 8 partly done", _row_sync_partly_done),
    Row("Step 9", _row_close),
)


def _table_points() -> list[str]:
    """The ``Crash point`` cells of the design's recovery table, in order."""
    lines = DESIGN.read_text(encoding="utf-8").splitlines()
    start = lines.index(TABLE_HEAD)
    points: list[str] = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        points.append(line.split("|")[1].strip())
    return points


@pytest.mark.parametrize("row", ROWS, ids=[row.case.__name__[5:] for row in ROWS])
def test_recovery_row(row: Row, tmp_path: Path) -> None:
    row.case(tmp_path)


def test_the_parametrization_has_one_case_per_recovery_row() -> None:
    points = _table_points()
    assert len(points) == 9, points
    assert len(ROWS) == len(points)
    assert [row.point for row in ROWS] == points
    # The entry point that the table's rows describe (IP:147).
    proc = subprocess.run(
        [sys.executable, str(LANES), "land", "recover", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLI_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "--op" in proc.stdout


# ---------------------------------------------------------------------------
# Refusals: uncertainty refuses rather than guesses
# ---------------------------------------------------------------------------


def test_publish_again_after_an_earlier_p_to_c_is_publication_unclear(
    tmp_path: Path,
) -> None:
    lr = lane_rig(tmp_path)
    ready(lr)
    crashed(publish(lr, env={CRASH: "commit:published:effect"}))
    c = main_ref(lr)
    # main back at P with P -> C already in the reflog: "publish again" must not hold.
    git(lr.repo, "update-ref", "refs/heads/main", lr.p, c)
    refused(recover(lr), "publication_unclear")
    assert main_ref(lr) == lr.p
    assert ("land:closed", "done") not in phases(lr)


def test_an_unknown_journal_phase_is_recovery_unclear(tmp_path: Path) -> None:
    lr = lane_rig(tmp_path)
    crashed(prepare(lr, env={CRASH: "land:ready:done"}))
    path = op_file(lr)
    record = json.loads(path.read_text(encoding="utf-8"))
    bogus = dict(record["journal"][-1])
    bogus["phase"] = "land:bogus"
    record["journal"].append(bogus)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    written = path.read_bytes()
    refused(recover(lr), "recovery_unclear:land:bogus")
    assert path.read_bytes() == written


def test_a_sync_path_at_neither_p_nor_c_stops_the_land(tmp_path: Path) -> None:
    lr = lane_rig(tmp_path)
    ready(lr)
    crashed(publish(lr, env={CRASH: "land:sync:started"}))
    stray = lr.repo / lr.changed
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"NEITHER = True\n")
    refused(recover(lr), f"sync_unexplained:{lr.changed}")
    assert stray.read_bytes() == b"NEITHER = True\n"
    assert ("land:closed", "done") not in phases(lr)
    assert os.path.isfile(stray)
