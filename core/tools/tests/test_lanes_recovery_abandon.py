"""MEU-785 AC-785.23 / EA-53: the recovery row "Step 1 done, before step 4" is idempotent.

Design D:260: "Remove the candidate; set the card back to ``active``. Nothing in the lane
changed." EA-53 asks that this row is a no-op when the candidate is already gone and the card
is already ``active`` (no error, no second card write). Two end states reach it:

* an ``owns_violation`` at step 2: ``land prepare`` itself removes the candidate and sets the
  card back to ``active``, and the journal stays at ``land:rebase:done``;
* a crash at ``land:rebase:started``: the first ``land recover`` does both.

Each test recovers the op twice and compares the card and journal bytes between the two
runs. Every repository is a disposable ``phase_b3`` fixture in ``tmp_path``. The lane rig is
the one of ``test_lanes_recovery.py`` with ``owns`` entries that stage 1 accepts (exact
paths, ``a/b/`` for a folder).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import lane_worktree_config as lwc
from tools.tests import test_lanes_recovery as base

OUTSIDE = "other/outside.txt"


def exact_rig(tmp_path: Path) -> base.LaneRig:
    """One fixture, one lane; ``owns`` names the lane folder, its handoff and its review."""
    rig = b3.rig(tmp_path / "fx", base.ROOT, seed=lwc.SEED)
    rig.bind()
    plan = rig.plan
    task = base.ensure_task(rig, plan)
    owns = [
        f"src/{plan}/",
        f"{base.HANDOFFS}/{plan}-handoff.md",
        f"{base.HANDOFFS}/{plan}-implementation-critical-review.md",
    ]
    rig.seed(
        {
            task.relative_to(rig.repo).as_posix(): (
                task.read_text(encoding="utf-8") + base.ownership(owns)
            ).encode("utf-8"),
            base.METRICS: base.METRICS_HEAD.encode(),
        },
        message=f"fixture: lane ownership of {plan}",
    )
    return base.open_lane(rig, tmp_path, plan, base.CARD_SESSION)


def journal(lr: base.LaneRig) -> bytes:
    return base.op_file(lr).read_bytes()


def candidate_of(lr: base.LaneRig) -> Path:
    """The candidate folder of the op: listed nowhere once recovery has run."""
    return next(
        (path for path in base.worktrees(lr) if path.name == f"land-{base.OP}"),
        Path("absent"),
    )


def test_recovery_after_an_owns_violation_is_a_no_op(tmp_path: Path) -> None:
    lr = exact_rig(tmp_path)
    outside = lr.wt / OUTSIDE
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"OUT = 1\n")
    base.git(lr.wt, "add", "-A")
    base.git(lr.wt, "commit", "-q", "-m", "lane: a file outside owns")
    lr = replace(lr, l0=base.git(lr.wt, "rev-parse", "HEAD"))
    base.refused(base.prepare(lr), f"owns_violation:{OUTSIDE}")
    assert (base.card(lr)["state"], base.card(lr).get("op")) == ("active", None)
    assert base.phases(lr)[-1] == ("land:rebase", "done")
    assert candidate_of(lr) == Path("absent")
    settled_card = lr.card_path.read_bytes()
    settled_journal = journal(lr)
    for _ in range(2):
        out = base.ok(base.recover(lr))
        assert f"land_abandoned:{base.OP}" in out, out
        assert lr.card_path.read_bytes() == settled_card, "a second card write"
        assert journal(lr) == settled_journal
    assert base.git(lr.repo, "rev-parse", lr.branch_ref) == lr.l0
    assert base.main_ref(lr) == lr.p


def test_a_second_recovery_of_the_rebase_crash_writes_nothing(tmp_path: Path) -> None:
    lr = exact_rig(tmp_path)
    base.crashed(base.prepare(lr, env={base.CRASH: "land:rebase:started"}))
    assert (base.card(lr)["state"], base.card(lr).get("op")) == ("landing", base.OP)
    base.ok(base.recover(lr))
    assert (base.card(lr)["state"], base.card(lr).get("op")) == ("active", None)
    settled_card = lr.card_path.read_bytes()
    settled_journal = journal(lr)
    again = base.ok(base.recover(lr))
    assert f"land_abandoned:{base.OP}" in again, again
    assert lr.card_path.read_bytes() == settled_card
    assert journal(lr) == settled_journal
    record = json.loads(base.op_file(lr).read_text(encoding="utf-8"))
    assert record["journal"][-1]["phase"] == "land:rebase"
