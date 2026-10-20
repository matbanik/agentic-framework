"""H1-7 round 2: the two runtime findings of the execution review (R2-F1, R2-F2).

Design: the run-parameters plan (H1-7; the execution review, round 2). Each test drives the
commit driver in a child process, as the reviewer's probes did, and reads the store with the
production readers.

* R2-F1 (AC-C.6, report §4.1 path 3, §4.5, D-12 A'): a completed manual or legacy plan still
  commits by a human direction that names it, as the closeout order does (H2-4 marks the plan
  complete, then H2-5 commits it); an unnamed direction never resolves to a completed plan.
* R2-F2 (AC-C.1, AC-C.2, AC-F.2, report §4.5 one reservation and batch sub-ops): an interrupted
  batch is pending under its own op id, inside a packet and between packets, until every packet
  of the batch is reconciled, and that id recovers the batch through the driver.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

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


def _closed_rig(tmp_path: Path, *, legacy: bool) -> tuple[b3.Rig, dict[str, bytes]]:
    """A manual (or legacy) plan closed as H2-4 closes one, and its closeout packet files.

    Both files say ``status: complete``; the task says ``stop_gate: released:done`` and every
    row is checked; a legacy plan carries no ``run_parameters`` block. The files are the exact
    bytes of the closed plan and task.
    """
    fx = bf.build(tmp_path / "fx", ROOT)
    fx.write_carrier({**fx.block, **MANUAL}, status="complete")
    files: dict[str, bytes] = {}
    for path in (fx.task_path(), fx.plan_path()):
        text = path.read_text(encoding="utf-8")
        end = text.index("\n---\n", 4)
        meta = yaml.safe_load(text[4:end])
        body = text[end + 5 :]
        meta["status"] = "complete"
        if path == fx.task_path():
            meta["stop_gate"] = "released:done"
            body = body.replace("[ ]", "[x]")
        if legacy:
            meta.pop("run_parameters", None)
        path.write_bytes((bf.frontmatter(meta) + body).encode("utf-8"))
        files[path.relative_to(fx.repo).as_posix()] = path.read_bytes()
    key, fingerprint = b3.configure_signing(fx)
    return b3.Rig(fx=fx, key=key, fingerprint=fingerprint), files


def _pending(rig: b3.Rig) -> str:
    rp = _rp()
    with bf.patched_environ(rig.fx.env()):
        return str(rp._run_pending_op(rp._open_repo(rig.repo), rig.plan, "interactive"))


def _two_packet_batch(rig: b3.Rig, stem: str) -> tuple[dict[str, Any], list[str]]:
    parent = rig.ref()
    paths = [f"{stem}-{n}.txt" for n in (1, 2)]
    packets = [
        rig.packet(files={path: f"{path}\n".encode()}, parent=parent) for path in paths
    ]
    return rig.batch(packets), paths


# -- R2-F1: the completed plan's closeout commit ---------------------------------------------


@pytest.mark.parametrize("legacy", [False, True], ids=["manual", "legacy"])
def test_r2_f1_a_completed_plan_commits_by_a_direction_that_names_it(
    tmp_path: Path, legacy: bool
) -> None:
    """R2-F1: ``commit the <plan> plan`` after closeout publishes the plan and task bytes."""
    rig, files = _closed_rig(tmp_path, legacy=legacy)
    assert not rig.fx.store.exists()
    parent = rig.ref()
    uid = rig.fx.add_human(f"commit the {rig.plan} plan")
    out = _reconciled(
        rig.human(uid, rig.packet(files=files, message="docs: complete fixture plan\n"))
    )
    assert rig.parents(out["commit"]) == [parent] and rig.ref() == out["commit"]
    tree = rig.tree_entries(out["commit"])
    assert {path: tree[path][1] for path in files} == {
        path: b3.blob_oid(data) for path, data in files.items()
    }
    record = rig.op_record(f"human-{uid}", run=rig.fx.session)
    assert record["consent"]["message_uuid"] == uid
    assert record["consent"]["scope"] == {
        "plan": rig.plan,
        "branch": "main",
        "repo": rig.fx.display,
    }


def test_r2_f1_an_unnamed_direction_never_resolves_to_a_completed_plan(
    tmp_path: Path,
) -> None:
    """R2-F1: ``commit it`` after closeout names no open plan, so it refuses and writes nothing."""
    rig, files = _closed_rig(tmp_path, legacy=False)
    before = rig.ref()
    uid = rig.fx.add_human("commit it")
    _refused(rig.human(uid, rig.packet(files=files)), "no_commit_direction")
    assert rig.ref() == before
    assert not rig.fx.store.exists()


# -- R2-F2: the interrupted batch's recovery --------------------------------------------------


def test_r2_f2_a_crash_inside_a_packet_recovers_through_the_pending_op(
    tmp_path: Path,
) -> None:
    """R2-F2: the pending id of a batch crashed inside packet 1 is the batch, and it recovers."""
    rp = _rp()
    rig = b3.rig(tmp_path / "fx", ROOT)
    rig.bind()
    rig.reserve("op-batch")
    parent = rig.ref()
    batch, paths = _two_packet_batch(rig, "inside")
    rig.crash("op-batch", batch, "candidate_verified:done")
    assert _pending(rig) == "op-batch"
    with bf.patched_environ(rig.fx.env()):
        facts = rp.resume_facts(
            rig.repo, plan=rig.plan, run_id="interactive", state="exec:active"
        )
    assert facts["acts_unconsumed"] is True, facts
    out = _reconciled(rig.commit(_pending(rig), batch))
    assert len(out["commits"]) == 2 and rig.ref() == out["commit"]
    assert rig.parents(out["commits"][0]) == [parent]
    assert rig.parents(out["commits"][1]) == [out["commits"][0]]
    assert set(paths) <= set(rig.tree_entries(out["commit"]))
    assert _pending(rig) == "none"


def test_r2_f2_a_crash_between_packets_leaves_the_batch_pending(tmp_path: Path) -> None:
    """R2-F2: after packet 1 is reconciled and before packet 2 opens, the batch is pending."""
    rp = _rp()
    rig = b3.rig(tmp_path / "fx", ROOT)
    rig.reserve("op-batch")
    batch, paths = _two_packet_batch(rig, "between")
    rig.crash("op-batch", batch, "reconciled:done")
    with bf.patched_environ(rig.fx.env()):
        ops = rp.plan_ops(rig.repo, rig.plan)
    assert [(op["op"], op["phase"]) for op in ops] == [("op-batch/1", "reconciled")]
    first = ops[0]["commit"]
    assert rig.ref() == first
    assert paths[1] not in rig.tree_entries(first)
    assert _pending(rig) == "op-batch"
    out = _reconciled(rig.commit(_pending(rig), batch))
    assert out["commits"][0] == first
    assert rig.parents(out["commits"][1]) == [first] and rig.ref() == out["commit"]
    assert set(paths) <= set(rig.tree_entries(out["commit"]))
    assert _pending(rig) == "none"


def test_r2_f2_a_batch_rerun_with_another_packet_count_refuses(tmp_path: Path) -> None:
    """R2-F2: the batch's recovery must carry the same packets; a shorter batch refuses."""
    rig = b3.rig(tmp_path / "fx", ROOT)
    rig.reserve("op-batch")
    batch, _paths = _two_packet_batch(rig, "count")
    rig.crash("op-batch", batch, "reconciled:done")
    before = rig.ref()
    shorter = rig.batch(batch["packets"][:1])
    _refused(rig.commit("op-batch", shorter), "packet_mismatch")
    assert rig.ref() == before
    assert _pending(rig) == "op-batch"
