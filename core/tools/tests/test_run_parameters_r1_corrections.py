"""H1-7 round 1: the five runtime findings of the execution review (R1-F1 to R1-F5).

Design: the run-parameters plan (H1-7; the execution review, round 1). Each test drives the
shipped verbs or the commit driver in a child process, as the reviewer's probes did, so no seam
stands in for the behavior under test.

* R1-F1 (AC-C.6, report §4.1 path 3, §4.5, §4.6 manual completion): a manual plan has no store
  and no binding, and its human-directed commit still runs and is journaled.
* R1-F2 (AC-B.1, AC-B.5, P-1): a grant accepted in the main tree verifies in a linked worktree
  of the same repository.
* R1-F3 (AC-C.1, AC-C.2, AC-D.3, report §4.5 batch sub-ops): ``plan_ops`` and its consumers see
  every sub-op ``<op>/<n>`` of a batch, in order, completed or interrupted.
* R1-F4 (AC-D.3, report §4.6 repair, D-16): in committed mode an open repair generation reserves
  and publishes ``finalize`` under its new grant; the superseded grant still refuses.
* R1-F5 (AC-D.3, report §4.6 final receipt): the final-stage validator call carries the
  plan's target identity, so a correctly targeted approved review passes ``approved_review``.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
MANUAL = {
    "authorization": {"schema": "manual"},
    "commit_plan": False,
    "exec_after_plan": False,
    "commit_exec": False,
}


def _rp() -> ModuleType:
    return importlib.import_module("tools.run_parameters")


def _reconciled(res: b3.Result) -> dict[str, Any]:
    code, out, text = res
    assert (code, out.get("result")) == (0, "reconciled"), text
    return out


def _refused(res: b3.Result, reason: str) -> None:
    code, out, text = res
    assert (code, out.get("result"), out.get("reason")) == (1, "refused", reason), text


def _manual_rig(tmp_path: Path) -> b3.Rig:
    """A fixture whose carriers hold a manual block: no ``init``, no ``bind``, no store."""
    fx = bf.build(tmp_path / "fx", ROOT)
    fx.write_carrier({**fx.block, **MANUAL})
    key, fingerprint = b3.configure_signing(fx)
    return b3.Rig(fx=fx, key=key, fingerprint=fingerprint)


def _second_plan(rig: b3.Rig, slug: str) -> None:
    """Another open plan with the same carriers as the fixture plan, under ``slug``."""
    folder = rig.repo / "docs" / "execution" / "plans"
    for name in ("task.md", "implementation-plan.md"):
        text = (folder / rig.plan / name).read_text(encoding="utf-8")
        target = folder / slug / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text.replace(rig.plan, slug), encoding="utf-8")


def _consent(rig: b3.Rig, op: str) -> dict[str, Any]:
    record = rig.op_record(op, run=rig.fx.session)
    assert record["journal"][0]["phase"] == "prepared", record
    return dict(record["consent"])


# -- R1-F1: the manual plan's human-directed commit -----------------------------------------


def test_r1_f1_manual_plan_commits_by_human_direction_without_a_store(
    tmp_path: Path,
) -> None:
    """R1-F1: ``commit it`` in a manual plan commits, journaled, with no prior store or binding."""
    rig = _manual_rig(tmp_path)
    assert not rig.fx.store.exists()
    for n, text in enumerate(("commit it", f"commit the {rig.plan[11:]} plan"), 1):
        parent = rig.ref()
        uid = rig.fx.add_human(text)
        out = _reconciled(
            rig.human(uid, rig.packet(files={f"manual-{n}.txt": b"manual\n"}))
        )
        assert rig.parents(out["commit"]) == [parent] and rig.ref() == out["commit"]
        consent = _consent(rig, f"human-{uid}")
        assert consent["message_uuid"] == uid
        assert consent["scope"] == {
            "plan": rig.plan,
            "branch": "main",
            "repo": rig.fx.display,
        }
    assert (rig.fx.store / "store.json").is_file()


def test_r1_f1_manual_consent_never_resolves_to_more_than_one_plan(
    tmp_path: Path,
) -> None:
    """R1-F1: with two open manual plans an unnamed direction refuses; a named one commits."""
    rig = _manual_rig(tmp_path)
    _second_plan(rig, "2026-10-17-fixture-plan-b")
    before = rig.ref()
    uid = rig.fx.add_human("commit it")
    _refused(rig.human(uid, rig.packet()), "no_commit_direction")
    assert rig.ref() == before
    uid = rig.fx.add_human(f"commit the {rig.plan} plan")
    _reconciled(rig.human(uid, rig.packet(files={"named.txt": b"named\n"})))


def test_r1_f1_an_unbound_granted_plan_still_needs_its_binding(tmp_path: Path) -> None:
    """R1-F1: the manual route does not widen consent to a granted plan with no binding."""
    rig = b3.rig(tmp_path / "fx", ROOT)
    before = rig.ref()
    for text in ("commit it", f"commit the {rig.plan} plan"):
        uid = rig.fx.add_human(text)
        _refused(rig.human(uid, rig.packet()), "no_commit_direction")
    assert rig.ref() == before


# -- R1-F2: a linked executor worktree ------------------------------------------------------


def test_r1_f2_a_linked_worktree_verifies_the_main_tree_grant(tmp_path: Path) -> None:
    """R1-F2: the lane resolves the main tree's project and transcript; its carriers stay its own."""
    rig = b3.rig(tmp_path / "fx", ROOT)
    fx = rig.fx
    code, out = fx.run("verify", "exec_start", "--plan", fx.plan)
    assert (code, out.get("result")) == (0, "verified"), out
    lane = tmp_path / "wt" / "lane"
    bf.git(rig.repo, "worktree", "add", "--detach", str(lane), "HEAD")
    code, out = fx.run("verify", "exec_start", "--plan", fx.plan, repo=lane)
    assert (code, out.get("result"), out.get("authorized")) == (
        0,
        "verified",
        True,
    ), out
    task = lane / "docs" / "execution" / "plans" / fx.plan / "task.md"
    task.unlink()
    code, out = fx.run("verify", "exec_start", "--plan", fx.plan, repo=lane)
    assert (code, out.get("reason")) == (1, "binding"), out


# -- R1-F3: batch sub-ops -------------------------------------------------------------------


def test_r1_f3_plan_ops_and_the_audit_see_every_batch_sub_op_in_order(
    tmp_path: Path,
) -> None:
    """R1-F3: a ten-packet batch is ten ops ``op-batch/1`` to ``/10``, published in order."""
    rp = _rp()
    rig = b3.rig(tmp_path / "fx", ROOT)
    rig.reserve("op-batch")
    parent = rig.ref()
    packets = [
        rig.packet(
            files={f"batch-{n}.txt": f"{n}\n".encode()},
            message=f"feat: batch packet {n}\n",
            parent=parent,
        )
        for n in range(1, 11)
    ]
    out = _reconciled(rig.commit("op-batch", rig.batch(packets)))
    with bf.patched_environ(rig.fx.env()):
        ops = rp.plan_ops(rig.repo, rig.plan)
        report = rp.plan_report(rig.repo, rig.plan)
        audit = rp.plan_audit(rig.repo, rig.plan)
    names = [f"op-batch/{n}" for n in range(1, 11)]
    assert [op["op"] for op in ops] == names, ops
    assert [op["commit"] for op in ops] == out["commits"]
    assert [op["parent"] for op in ops] == [parent, *out["commits"][:-1]]
    assert {(op["act"], op["phase"], op["run_id"]) for op in ops} == {
        ("exec_commit", "reconciled", "interactive")
    }
    assert [op["op"] for op in report["ops"]] == names
    publications = audit["publication_audit"]["publications"]
    assert [item["op"] for item in publications] == names, audit
    assert audit["publication_audit"]["result"] == "passed", audit


def test_r1_f3_an_interrupted_batch_is_the_run_s_pending_op(tmp_path: Path) -> None:
    """R1-F3: a crash inside a batch leaves the batch pending for the run's recovery (D-49)."""
    rp = _rp()
    rig = b3.rig(tmp_path / "fx", ROOT)
    rig.reserve("op-crash")
    parent = rig.ref()
    packets = [
        rig.packet(files={f"crash-{n}.txt": b"crash\n"}, parent=parent) for n in (1, 2)
    ]
    rig.crash("op-crash", rig.batch(packets), "candidate_verified:done")
    with bf.patched_environ(rig.fx.env()):
        ops = rp.plan_ops(rig.repo, rig.plan)
        pending = rp._run_pending_op(rp._open_repo(rig.repo), rig.plan, "interactive")
    assert [(op["op"], op["phase"]) for op in ops] == [
        ("op-crash/1", "candidate_verified")
    ], ops
    assert pending == "op-crash"


# -- R1-F4: the committed-mode repair generation ---------------------------------------------


def test_r1_f4_an_open_repair_generation_reserves_and_publishes_finalize(
    tmp_path: Path,
) -> None:
    """R1-F4: only the open repair's grant passes the sealed and superseded checks."""
    rig = b3.rig(tmp_path / "fx", ROOT)
    fx = rig.fx
    old = fx.block["authorization"]["message_uuid"]
    rig.seal_plan()
    newer = fx.present_and_accept(grants=["finalize"], supersedes=old)
    code, out = fx.run("init", "--block", str(fx.write_block_file(newer, "repair")))
    assert (code, out.get("result")) == (0, "initialized"), out
    reserve = ("reserve", "finalize", "--plan", fx.plan, "--op", "op-repair")
    code, out = fx.run(*reserve)
    assert (code, out.get("reason")) == (1, "superseded"), out
    fx.write_carrier(newer)
    code, out = fx.run(*reserve)
    assert (code, out.get("reason"), out.get("authorized")) == (1, "expired", False), (
        out
    )
    fx.write_carrier(fx.block)
    code, out = fx.run("repair", "--final", "--plan", fx.plan)
    assert (code, out.get("result"), out.get("generation")) == (0, "repaired", 2), out
    fx.write_carrier(newer)
    rig.reserve("op-repair", act="finalize")
    parent = rig.ref()
    published = _reconciled(
        rig.commit(
            "op-repair",
            rig.packet(files={"repair.txt": b"repair\n"}),
            phase="finalize",
        )
    )
    assert rig.parents(published["commit"]) == [parent]
    assert rig.ref() == published["commit"]
    fx.write_carrier(fx.block)
    code, out = fx.run(*reserve)
    assert (code, out.get("reason")) == (1, "superseded"), out


# -- R1-F5: the final-stage validator call --------------------------------------------------

#: An approved execution review in the closeout validator's markdown form. Without
#: ``--expected-target-plan`` the validator never compares its target with the plan.
APPROVED_REVIEW = """---
date: "2026-10-19"
review_mode: "execution"
target_plan: "{target}"
verdict: "approved"
findings_count: 0
template_version: "2.1"
---

# Critical Review: fixture-plan

## Findings

| # | Severity | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|

## Verdict

`approved` -- behaviour matches the plan.
"""


def test_r1_f5_the_final_stage_call_carries_the_target_plan(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """R1-F5: a review bound to the plan passes ``approved_review`` in the real final call."""
    rp = _rp()
    plan = "2026-10-17-fixture-plan"
    paths = rp._final_paths(plan)
    snapshot = tmp_path / "tree"
    task = snapshot / paths["task"]
    task.parent.mkdir(parents=True)
    task.write_text("---\nstatus: complete\n---\n\n# Task\n", encoding="utf-8")
    review = snapshot / paths["review"]
    review.parent.mkdir(parents=True)
    review.write_text(APPROVED_REVIEW.format(target=paths["plan"]), encoding="utf-8")
    capfd.readouterr()
    rp.run_stage_validators(snapshot, plan, snapshot)
    err = capfd.readouterr().err
    calls = [
        event
        for event in (
            json.loads(line) for line in err.splitlines() if line.startswith("{")
        )
        if event.get("event") == "validator_failed" and "--for-produce" in event["argv"]
    ]
    assert len(calls) == 1, err
    argv = calls[0]["argv"]
    assert "--expected-target-plan" in argv, argv
    assert argv[argv.index("--expected-target-plan") + 1] == paths["plan"], argv
    result = json.loads(calls[0]["stdout"])
    assert result["checks"]["approved_review"] == "pass", result
