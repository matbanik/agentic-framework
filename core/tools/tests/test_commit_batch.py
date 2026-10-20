"""B-3 tests for ``tools/commit_batch.py`` (WP-4; AC-C.1 to AC-C.7, R§4.5 :814-998).

Every ``V3-`` vector of the families ``commit_txn``, ``candidate``, ``index``, ``route``,
``consent`` and ``recovery`` in the design plan's ``vectors.yaml`` has at least one test whose name holds
``vec_<id>_``. The ``hook`` and ``decision`` families are in ``tools/tests/test_commit_gate.py``,
V3-002 is in ``tools/tests/test_executor_worktree_candidate.py``, and V3-031 and V3-032 are the
row 7 and row 8 probes. AC-C.5 and AC-C.7 are also covered by ``tools/tests/test_agent_commit.py``.

The tests fix the driver contract of EA-8:

* ``python -m tools.commit_batch --repo R`` takes the grant route ``--phase plan|exec|finalize
  --op <id> --packet <file> [--run <run_id>]`` or the human route ``--human-directed --session <s>
  --message-uuid <u> --packet <file>``. It prints one JSON object and exits 0 ``reconciled``,
  1 ``refused`` / ``stopped`` / ``failed``, 2 on a usage error and 97 at the crash seam;
* ``{"result": "reconciled", "op", "commit", "parent", "tree", "index"}``, where ``index`` maps
  each manifest path to ``updated``, ``current``, ``conflicted`` or ``foreign_staged``; a batch
  adds ``commits`` and its ``commit`` is the last one; ``{"result": "refused", "reason"}``;
  ``{"result": "stopped", "reason": "ambiguous"}``; ``{"result": "failed", "reason":
  "candidate:<check>"}``;
* a packet refusal (``packet_schema``, ``containment``, ``message``, ``attribution``,
  ``batch_order``, ``batch_count``) and a reservation refusal (``not_reserved``) happen before the
  op file and any Git object are written, so the reserved op stays usable;
* every packet of a batch names the batch parent P; sub-op ``<op>/<n>`` (n from 1) builds on the
  commit of sub-op ``n - 1``; a batch under ``--phase plan`` or ``--phase finalize`` is refused
  ``packet_schema``;
* ``op.json`` holds ``candidate_path`` = ``<candidate root>/<op>`` from ``prepared`` on; the
  ``prepared`` evidence holds ``message_digest`` (the sha256 of the canonical message bytes) and,
  on the human route, ``consent``; the ``published`` evidence holds ``ref_old`` and ``ref_new``;
  the ``candidate_verified`` evidence holds ``residue``, the ignored-path inventory.

Every fixture is built inside the test body (``phase_b3.rig``), so a missing component fails the
test at Red instead of erroring a fixture. Crash injection runs only in a child process.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
OP = "op-1"
CHANGE = b"change\n"
MESSAGE = b"feat: fixture change\n"
STATUSES = ("started", "done")
TRAILER = "Co-Authored-" + "By: Claude <noreply@anthropic.com>"


# -- helpers ---------------------------------------------------------------------------------


def _rig(tmp_path: Path, **kwargs: Any) -> b3.Rig:
    return b3.rig(tmp_path / "fx", ROOT, **kwargs)


def _reconciled(res: b3.Result) -> dict[str, Any]:
    code, out, text = res
    assert (code, out.get("result")) == (0, "reconciled"), text
    return out


def _refused(res: b3.Result, reason: str) -> None:
    code, out, text = res
    assert (code, out.get("result"), out.get("reason")) == (1, "refused", reason), text


def _stopped(res: b3.Result) -> None:
    code, out, text = res
    assert (code, out.get("result"), out.get("reason")) == (
        1,
        "stopped",
        "ambiguous",
    ), text


def _failed(res: b3.Result, check: str) -> None:
    code, out, text = res
    assert (code, out.get("result"), out.get("reason")) == (
        1,
        "failed",
        f"candidate:{check}",
    ), text


def _crashed(
    tmp_path: Path, point: str, **kwargs: Any
) -> tuple[b3.Rig, dict[str, Any], str]:
    """A rig whose op ``op-1`` crashed at ``commit:<point>``: (rig, packet, parent)."""
    rig = _rig(tmp_path, **kwargs)
    parent = rig.ref()
    rig.reserve(OP)
    packet = rig.packet()
    rig.crash(OP, packet, point)
    return rig, packet, parent


def _evidence(
    rig: b3.Rig, op: str, phase: str, run: str = "interactive"
) -> dict[str, Any]:
    """The evidence of every journal entry of one phase, merged in order."""
    merged: dict[str, Any] = {}
    for item in rig.op_record(op, run)["journal"]:
        if item["phase"] == phase and isinstance(item.get("evidence"), dict):
            merged.update(item["evidence"])
    return merged


def _publications(rig: b3.Rig, commit: str) -> int:
    """How many reflog entries of ``main`` moved the ref to ``commit``."""
    return sum(1 for _old, new in rig.reflog() if new == commit)


def _head(path: Path) -> str:
    return bf.git(path, "rev-parse", "HEAD")


def _worktrees(rig: b3.Rig) -> set[str]:
    """The lower-cased forward-slash paths of every listed worktree."""
    listing = rig.git("worktree", "list", "--porcelain")
    return {
        line[len("worktree ") :].replace("\\", "/").lower()
        for line in listing.splitlines()
        if line.startswith("worktree ")
    }


def _same(path: Path) -> str:
    return path.as_posix().lower()


def _store_blob(rig: b3.Rig, data: bytes) -> str:
    proc = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=rig.repo,
        env=bf.git_env(),
        input=data,
        capture_output=True,
        check=True,
    )
    return proc.stdout.decode("ascii").strip()


def _index_info(rig: b3.Rig, lines: list[str]) -> None:
    subprocess.run(
        ["git", "update-index", "--index-info"],
        cwd=rig.repo,
        env=bf.git_env(),
        input="".join(f"{line}\n" for line in lines).encode("utf-8"),
        capture_output=True,
        check=True,
    )


def _stage(rig: b3.Rig, rel: str, data: bytes) -> None:
    """Write a file in the caller's working tree and stage it."""
    path = rig.repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    rig.git("add", "--", rel)


def _entry(data: bytes, mode: str = "100644") -> dict[str, Any]:
    return {"mode": mode, "oid": b3.blob_oid(data), "stage": 0}


def _snapshot(rig: b3.Rig) -> tuple[str, str, set[str], int]:
    return rig.ref(), rig.index(), rig.objects(), rig.loose_count()


# -- the journal and recovery (AC-C.1) ------------------------------------------------------


def test_vec_v3_001_clean_run_journals_started_and_done_around_each_phase(
    tmp_path: Path,
) -> None:
    """AC-C.1, AC-C.7: one packet commits the manifest blobs and journals every phase."""
    rig = _rig(tmp_path)
    parent = rig.ref()
    rig.reserve(OP)
    worktree = rig.worktree()
    out = _reconciled(rig.commit(OP, rig.packet()))

    commit = out["commit"]
    assert (out["op"], out["parent"]) == (OP, parent), out
    assert rig.ref() == commit
    assert rig.parents(commit) == [parent]
    assert out["tree"] == rig.git("rev-parse", f"{commit}^{{tree}}")
    assert rig.tree_entries(commit)["change.txt"] == ("100644", b3.blob_oid(CHANGE))
    assert rig.message_bytes(commit) == MESSAGE
    rig.git("verify-commit", commit)
    assert _publications(rig, commit) == 1

    record = rig.op_record(OP)
    assert record["schema"] == "commit-op/1"
    identity = record["identity"]
    assert {key: identity[key] for key in ("op", "run_id", "plan", "act")} == {
        "op": OP,
        "run_id": "interactive",
        "plan": rig.plan,
        "act": "exec_commit",
    }
    assert len(str(identity["packet_digest"])) == 64
    assert rig.journal(OP) == [
        (phase, status) for phase in b3.JOURNAL_PHASES for status in STATUSES
    ]
    assert all(item["identity"] == identity for item in record["journal"])
    seqs = [int(item["seq"]) for item in record["journal"]]
    assert seqs == sorted(set(seqs))
    published = _evidence(rig, OP, "published")
    assert (published["ref_old"], published["ref_new"]) == (parent, commit)

    candidate = rig.candidate_path(OP)
    assert _same(candidate.parent) == _same(rig.candidate_root)
    assert not candidate.exists()
    assert _same(candidate) not in _worktrees(rig)

    assert out["index"] == {"change.txt": "updated"}
    assert rig.git("rev-parse", ":change.txt") == b3.blob_oid(CHANGE)
    assert rig.worktree() == worktree


@pytest.mark.parametrize("phase", b3.JOURNAL_PHASES)
def test_vec_v3_003_crash_after_each_side_effect_recovers_by_the_table(
    tmp_path: Path, phase: str
) -> None:
    """AC-C.1: a crash after the side effect and before ``done``, then one recovering run."""
    rig, packet, parent = _crashed(tmp_path, f"{phase}:effect")
    assert rig.journal(OP)[-1] == (phase, "started")
    after_publish = b3.JOURNAL_PHASES.index(phase) >= b3.JOURNAL_PHASES.index(
        "published"
    )
    tip = rig.ref()
    if after_publish:
        assert tip != parent and rig.parents(tip) == [parent]
    else:
        assert tip == parent
    held = _head(rig.candidate_path(OP)) if phase == "candidate_verified" else None

    out = _reconciled(rig.commit(OP, packet))
    assert out["parent"] == parent and rig.ref() == out["commit"]
    assert rig.parents(out["commit"]) == [parent]
    if held is not None:
        assert out["commit"] == held
    if after_publish:
        assert out["commit"] == tip
    assert _publications(rig, out["commit"]) == 1
    assert rig.journal(OP)[-1] == ("reconciled", "done")
    assert rig.git("rev-parse", ":change.txt") == b3.blob_oid(CHANGE)
    assert not rig.candidate_path(OP).exists()


def test_vec_v3_045_reconciled_is_terminal_and_never_a_ref_write(
    tmp_path: Path,
) -> None:
    """AC-C.1: a re-run of a reconciled op changes nothing, even after the ref moved back."""
    rig = _rig(tmp_path)
    parent = rig.ref()
    rig.reserve(OP)
    packet = rig.packet()
    first = _reconciled(rig.commit(OP, packet))
    state = (rig.reflog(), rig.journal(OP), rig.index(), rig.ref())

    second = _reconciled(rig.commit(OP, packet))
    assert second["commit"] == first["commit"]
    assert (rig.reflog(), rig.journal(OP), rig.index(), rig.ref()) == state

    rig.git("update-ref", "refs/heads/main", parent, first["commit"])
    reflog = rig.reflog()
    rig.commit(OP, packet)
    assert rig.ref() == parent
    assert rig.reflog() == reflog


@pytest.mark.parametrize("point", ["prepared:started", "prepared:done"])
def test_vec_v3_033_prepared_crash_revalidates_the_manifest(
    tmp_path: Path, point: str
) -> None:
    """AC-C.1: recovery from ``prepared`` checks the op's digests, then stores the blobs."""
    rig, packet, parent = _crashed(tmp_path, point)
    assert rig.ref() == parent
    _refused(
        rig.commit(OP, rig.packet(files={"other.txt": b"other\n"})), "packet_mismatch"
    )
    out = _reconciled(rig.commit(OP, packet))
    assert ("blobs_stored", "done") in rig.journal(OP)
    assert rig.tree_entries(out["commit"])["change.txt"] == (
        "100644",
        b3.blob_oid(CHANGE),
    )
    assert "other.txt" not in rig.tree_entries(out["commit"])


@pytest.mark.parametrize("point", ["blobs_stored:started", "blobs_stored:done"])
def test_vec_v3_034_blobs_stored_crash_rechecks_every_oid(
    tmp_path: Path, point: str
) -> None:
    """AC-C.1: recovery from ``blobs_stored`` re-checks the OIDs, then builds the candidate."""
    rig, packet, parent = _crashed(tmp_path, point)
    if point.endswith(":done"):
        rig.git("cat-file", "-e", b3.blob_oid(CHANGE))
    assert rig.ref() == parent
    out = _reconciled(rig.commit(OP, packet))
    journal = rig.journal(OP)
    assert journal.index(("candidate_built", "done")) > journal.index(
        ("blobs_stored", "done")
    )
    assert rig.parents(out["commit"]) == [parent]


# -- the candidate path (AC-C.2) ----------------------------------------------------------------


def test_vec_v3_004_vec_v3_035_absent_candidate_is_rebuilt(tmp_path: Path) -> None:
    """AC-C.2: ``candidate_built:started`` with no candidate folder rebuilds it."""
    rig, packet, parent = _crashed(tmp_path, "candidate_built:started")
    assert not rig.candidate_path(OP).exists()
    out = _reconciled(rig.commit(OP, packet))
    assert rig.parents(out["commit"]) == [parent]


def test_vec_v3_004_vec_v3_035_owned_candidate_is_checked_and_rebuilt(
    tmp_path: Path,
) -> None:
    """AC-C.2: an owned candidate carries its manifest; one whose index is not T is rebuilt."""
    rig, packet, parent = _crashed(tmp_path, "candidate_built:effect")
    candidate = rig.candidate_path(OP)
    git_dir = Path(bf.git(candidate, "rev-parse", "--absolute-git-dir"))
    manifest = json.loads((git_dir / b3.CANDIDATE_MANIFEST).read_text(encoding="utf-8"))
    assert manifest == {
        "schema": "candidate-worktree/1",
        "kind": "candidate",
        "op": OP,
        "run_id": "interactive",
        "plan": rig.plan,
    }
    assert _head(candidate) == parent
    (candidate / "extra.txt").write_bytes(b"extra\n")
    bf.git(candidate, "add", "--", "extra.txt")

    out = _reconciled(rig.commit(OP, packet))
    expected = rig.tree_entries(parent)
    expected["change.txt"] = ("100644", b3.blob_oid(CHANGE))
    assert rig.tree_entries(out["commit"]) == expected


@pytest.mark.parametrize("kind", ["plain_folder", "other_op_manifest"])
def test_vec_v3_004_vec_v3_035_foreign_candidate_stops(
    tmp_path: Path, kind: str
) -> None:
    """AC-C.2: a candidate path with no manifest, or another op's, is foreign: ambiguous."""
    rig, packet, parent = _crashed(tmp_path, "candidate_built:started")
    candidate = rig.candidate_path(OP)
    if kind == "plain_folder":
        candidate.mkdir(parents=True)
        (candidate / "foreign.txt").write_bytes(b"foreign\n")
    else:
        rig.git("worktree", "add", "-q", "--detach", str(candidate), parent)
        git_dir = Path(bf.git(candidate, "rev-parse", "--absolute-git-dir"))
        other = {
            "schema": "candidate-worktree/1",
            "kind": "candidate",
            "op": "op-other",
            "run_id": "interactive",
            "plan": rig.plan,
        }
        (git_dir / b3.CANDIDATE_MANIFEST).write_bytes(json.dumps(other).encode("utf-8"))
        (candidate / "foreign.txt").write_bytes(b"foreign\n")

    _stopped(rig.commit(OP, packet))
    assert (candidate / "foreign.txt").read_bytes() == b"foreign\n"
    assert rig.ref() == parent


def test_vec_v3_036_candidate_built_done_verifies_before_it_publishes(
    tmp_path: Path,
) -> None:
    """AC-C.1: recovery from ``candidate_built:done`` runs the step-4 checks before step 5."""
    rig, packet, parent = _crashed(tmp_path, "candidate_built:done")
    assert rig.ref() == parent
    _reconciled(rig.commit(OP, packet))
    journal = rig.journal(OP)
    assert journal.index(("candidate_verified", "done")) < journal.index(
        ("published", "started")
    )


def test_vec_v3_036_ref_holding_an_unverified_candidate_stops(tmp_path: Path) -> None:
    """AC-C.1: ref == C before ``candidate_verified:done`` is not proof of verification."""
    rig, packet, parent = _crashed(tmp_path, "candidate_verified:effect")
    held = _head(rig.candidate_path(OP))
    rig.git("update-ref", "refs/heads/main", held, parent)
    _stopped(rig.commit(OP, packet))
    assert rig.ref() == held


@pytest.mark.parametrize(
    "point", ["candidate_verified:started", "candidate_verified:effect"]
)
def test_vec_v3_037_candidate_verified_started_commits_or_reuses(
    tmp_path: Path, point: str
) -> None:
    """AC-C.1: HEAD P commits after the pre-hook check; HEAD C' is verified and reused."""
    rig, packet, parent = _crashed(tmp_path, point)
    head = _head(rig.candidate_path(OP))
    out = _reconciled(rig.commit(OP, packet))
    if point.endswith(":started"):
        assert head == parent
    else:
        assert head != parent and out["commit"] == head
    assert rig.parents(out["commit"]) == [parent]


def test_vec_v3_038_verified_candidate_publishes_with_expected_old_parent(
    tmp_path: Path,
) -> None:
    """AC-C.1: recovery from ``candidate_verified:done`` re-verifies the act, then publishes."""
    rig, packet, parent = _crashed(tmp_path, "candidate_verified:done")
    assert rig.ref() == parent
    out = _reconciled(rig.commit(OP, packet))
    assert _evidence(rig, OP, "published")["ref_old"] == parent
    assert _publications(rig, out["commit"]) == 1


def test_vec_v3_038_publication_time_expiry_refuses(tmp_path: Path) -> None:
    """AC-C.2: a closure that lands after ``prepared`` refuses at publication (R5-12)."""
    rig, packet, parent = _crashed(tmp_path, "candidate_verified:done")
    rig.seal_plan()
    _refused(rig.commit(OP, packet), "expired")
    assert rig.ref() == parent


def test_vec_v3_005_competing_update_ref_writer_refuses_publication(
    tmp_path: Path,
) -> None:
    """AC-C.2: the ref moved before step 5; ``update-ref`` with expected old P refuses."""
    rig, packet, parent = _crashed(tmp_path, "candidate_verified:done")
    other = rig.other_commit(parent, "competing writer")
    rig.git("update-ref", "refs/heads/main", other, parent)
    _refused(rig.commit(OP, packet), "publish_refused")
    assert rig.ref() == other


def test_vec_v3_006_aba_before_publication_is_not_drift(tmp_path: Path) -> None:
    """AC-C.2: the ref moved away and back to P before the first publication: publish."""
    rig, packet, parent = _crashed(tmp_path, "candidate_verified:done")
    other = rig.other_commit(parent, "away")
    rig.git("update-ref", "refs/heads/main", other, parent)
    rig.git("update-ref", "refs/heads/main", parent, other)
    out = _reconciled(rig.commit(OP, packet))
    assert rig.parents(out["commit"]) == [parent]


def test_vec_v3_006_vec_v3_040_aba_after_publication_stops(tmp_path: Path) -> None:
    """AC-C.1, AC-C.2: ref == P after a recorded publication is an external reversal."""
    rig, packet, parent = _crashed(tmp_path, "published:done")
    published = rig.ref()
    rig.git("update-ref", "refs/heads/main", parent, published)
    _stopped(rig.commit(OP, packet))
    assert rig.ref() == parent


def test_vec_v3_040_other_oid_after_publication_stops(tmp_path: Path) -> None:
    """AC-C.1: any other OID after a recorded publication stops; the journal is kept."""
    rig, packet, _parent = _crashed(tmp_path, "published:done")
    published = rig.ref()
    other = rig.other_commit(published, "later")
    rig.git("update-ref", "refs/heads/main", other, published)
    journal = rig.journal(OP)
    _stopped(rig.commit(OP, packet))
    assert rig.ref() == other
    assert rig.journal(OP)[: len(journal)] == journal


def test_vec_v3_039_published_started_retries_when_not_published(
    tmp_path: Path,
) -> None:
    """AC-C.1: ref == P and the reflog answers with no P → C: retry step 5 once."""
    rig, packet, parent = _crashed(tmp_path, "published:started")
    assert rig.ref() == parent
    out = _reconciled(rig.commit(OP, packet))
    assert _publications(rig, out["commit"]) == 1


def test_vec_v3_039_published_reflog_gone_after_the_effect_stops(
    tmp_path: Path,
) -> None:
    """AC-C.1: a reflog that cannot answer stops, even with ref == C."""
    rig, packet, parent = _crashed(tmp_path, "published:effect")
    tip = rig.ref()
    assert tip != parent
    (rig.fx.common_dir / "logs" / "refs" / "heads" / "main").unlink()
    _stopped(rig.commit(OP, packet))
    assert rig.ref() == tip


def test_vec_v3_039_published_reversal_stops(tmp_path: Path) -> None:
    """AC-C.1: ref == P with P → C in the reflog is a reversal: ambiguous, never republished."""
    rig, packet, parent = _crashed(tmp_path, "published:effect")
    tip = rig.ref()
    rig.git("update-ref", "refs/heads/main", parent, tip)
    _stopped(rig.commit(OP, packet))
    assert rig.ref() == parent
    assert _publications(rig, tip) == 1


def test_vec_v3_039_cannot_answer_wins_over_no_publication_found(
    tmp_path: Path,
) -> None:
    """AC-C.1: an expired reflog is never read as "no P → C found" (ref == P alone)."""
    rig, packet, parent = _crashed(tmp_path, "published:started")
    (rig.fx.common_dir / "logs" / "refs" / "heads" / "main").unlink()
    _stopped(rig.commit(OP, packet))
    assert rig.ref() == parent


def test_vec_v3_041_our_index_lock_is_resumed(tmp_path: Path) -> None:
    """AC-C.1, AC-C.4: our lock and ``before.json`` without the replace: redo, unlock."""
    rig, packet, _parent = _crashed(tmp_path, "index_reconciled:locked")
    lock = rig.fx.common_dir / "index.lock"
    assert OP in lock.read_text(encoding="utf-8")
    assert rig.index_record(OP, "before")["op"] == OP
    out = _reconciled(rig.commit(OP, packet))
    assert not lock.exists()
    assert out["index"] == {"change.txt": "updated"}
    assert rig.git("rev-parse", ":change.txt") == b3.blob_oid(CHANGE)


def test_vec_v3_041_foreign_index_lock_is_stale_lock(tmp_path: Path) -> None:
    """AC-C.4: an ``index.lock`` with another body is someone else's: wait, then refuse."""
    rig, packet, parent = _crashed(tmp_path, "index_reconciled:started")
    tip = rig.ref()
    lock = rig.fx.common_dir / "index.lock"
    lock.write_bytes(b"someone-else\n")
    _refused(rig.commit(OP, packet), "stale_lock")
    assert lock.read_bytes() == b"someone-else\n"
    assert tip != parent and rig.ref() == tip


def test_vec_v3_042_index_reconciled_done_is_verified_then_cleaned(
    tmp_path: Path,
) -> None:
    """AC-C.1, AC-C.4: the durable per-path result is checked against ``after.json``."""
    rig, packet, _parent = _crashed(tmp_path, "index_reconciled:done")
    after = rig.index_record(OP, "after")
    assert after["entries"]["change.txt"] == [_entry(CHANGE)]
    _reconciled(rig.commit(OP, packet))
    journal = rig.journal(OP)
    assert journal.index(("cleanup_done", "done")) > journal.index(
        ("index_reconciled", "done")
    )
    assert rig.index_entries("change.txt") == [
        f"100644 {b3.blob_oid(CHANGE)} 0\tchange.txt"
    ]


@pytest.mark.parametrize("point", ["cleanup_done:started", "cleanup_done:effect"])
def test_vec_v3_043_cleanup_is_idempotent(tmp_path: Path, point: str) -> None:
    """AC-C.1: the candidate is removed or pruned; the evidence stays in the journal."""
    rig, packet, _parent = _crashed(tmp_path, point)
    candidate = rig.candidate_path(OP)
    _reconciled(rig.commit(OP, packet))
    assert not candidate.exists()
    assert _same(candidate) not in _worktrees(rig)
    assert "residue" in _evidence(rig, OP, "candidate_verified")


def test_vec_v3_044_cleanup_done_writes_reconciled_once(tmp_path: Path) -> None:
    """AC-C.1: recovery from ``cleanup_done:done`` writes ``reconciled`` and nothing else."""
    rig, packet, _parent = _crashed(tmp_path, "cleanup_done:done")
    journal = rig.journal(OP)
    _reconciled(rig.commit(OP, packet))
    assert rig.journal(OP) == [
        *journal,
        ("reconciled", "started"),
        ("reconciled", "done"),
    ]


# -- the candidate checks (AC-C.2, AC-C.3) ----------------------------------------------------


def test_vec_v3_007_pre_hook_check_rejects_unstaged_drift(tmp_path: Path) -> None:
    """AC-C.2: the candidate's worktree must equal its index before any hook runs."""
    rig, packet, parent = _crashed(tmp_path, "candidate_built:done")
    candidate = rig.candidate_path(OP)
    with (candidate / "change.txt").open("ab") as handle:
        handle.write(b"drift\n")
    _failed(rig.commit(OP, packet), "unstaged_drift")
    assert rig.ref() == parent
    assert any(
        status == "failed:candidate:unstaged_drift" for _p, status in rig.journal(OP)
    )


def test_vec_v3_007_pre_hook_check_rejects_an_index_that_is_not_t(
    tmp_path: Path,
) -> None:
    """AC-C.2: the staged P → T delta is admitted; an extra staged path is not."""
    rig, packet, parent = _crashed(tmp_path, "candidate_built:done")
    candidate = rig.candidate_path(OP)
    (candidate / "extra.txt").write_bytes(b"extra\n")
    bf.git(candidate, "add", "--", "extra.txt")
    _failed(rig.commit(OP, packet), "index_tree")
    assert rig.ref() == parent


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "printf 'hook\\n' >> change.txt && git add change.txt", id="stages"
        ),
        pytest.param("printf 'hook\\n' >> change.txt", id="unstaged"),
    ],
)
def test_vec_v3_008_hook_drift_fails_the_candidate(tmp_path: Path, body: str) -> None:
    """AC-C.2: a pre-commit hook that changes a file, staged or not, fails ``hook_drift``."""
    rig = _rig(tmp_path)
    parent = rig.ref()
    rig.reserve(OP)
    rig.install_hook("pre-commit", body)
    _failed(rig.commit(OP, rig.packet()), "hook_drift")
    assert rig.ref() == parent
    assert not (rig.repo / "change.txt").exists()


def test_vec_v3_009_ignored_residue_outside_the_allow_list_fails(
    tmp_path: Path,
) -> None:
    """AC-C.2: an ignored path outside the allow-list fails ``ignored_residue:<path>``."""
    rig = _rig(tmp_path, seed={".gitignore": b"*.log\n__pycache__/\n"})
    parent = rig.ref()
    rig.reserve(OP)
    rig.install_hook("pre-commit", "printf 'x\\n' > residue.log")
    _failed(rig.commit(OP, rig.packet()), "ignored_residue:residue.log")
    assert rig.ref() == parent


def test_vec_v3_009_allowed_residue_is_inventoried(tmp_path: Path) -> None:
    """AC-C.2: ``__pycache__/`` is on the allow-list; the inventory is journaled."""
    rig = _rig(tmp_path, seed={".gitignore": b"*.log\n__pycache__/\n"})
    rig.reserve(OP)
    rig.install_hook(
        "pre-commit", "mkdir -p __pycache__ && printf 'x\\n' > __pycache__/x.pyc"
    )
    _reconciled(rig.commit(OP, rig.packet()))
    residue = _evidence(rig, OP, "candidate_verified")["residue"]
    assert any(str(path).startswith("__pycache__") for path in residue), residue


def test_vec_v3_010_deletions_renames_modes_and_eol_are_exact(tmp_path: Path) -> None:
    """AC-C.2: the tree is the manifest: removals, a rename, a mode change, CRLF bytes."""
    script = b"#!/bin/sh\necho hi\n"
    rig = _rig(
        tmp_path,
        seed={
            "gone.txt": b"gone\n",
            "old-name.txt": b"renamed\n",
            "script.sh": script,
            "crlf.txt": b"lf\n",
        },
    )
    parent = rig.ref()
    rig.reserve(OP)
    worktree = rig.worktree()
    packet = rig.packet(
        files={
            "new-name.txt": b"renamed\n",
            "script.sh": script,
            "crlf.txt": b"a\r\nb\r\n",
        },
        deletes=["gone.txt", "old-name.txt"],
        modes={"script.sh": "100755"},
    )
    out = _reconciled(rig.commit(OP, packet))

    expected = rig.tree_entries(parent)
    del expected["gone.txt"], expected["old-name.txt"]
    expected["new-name.txt"] = ("100644", b3.blob_oid(b"renamed\n"))
    expected["script.sh"] = ("100755", b3.blob_oid(script))
    expected["crlf.txt"] = ("100644", b3.blob_oid(b"a\r\nb\r\n"))
    assert rig.tree_entries(out["commit"]) == expected
    assert out["index"] == {
        path: "updated"
        for path in (
            "new-name.txt",
            "script.sh",
            "crlf.txt",
            "gone.txt",
            "old-name.txt",
        )
    }
    assert (
        rig.index_entries("gone.txt") == [] and rig.index_entries("old-name.txt") == []
    )
    assert rig.index_entries("script.sh")[0].startswith("100755 ")
    assert rig.worktree() == worktree


MESSAGE_VECTORS = [
    ("feat: no final lf", b"feat: no final lf\n"),
    ("feat: crlf\r\n\r\nbody line\r\n", b"feat: crlf\n\nbody line\n"),
    ("\n\nfeat: leading blank\n", b"feat: leading blank\n"),
    ("feat: two blanks\n\n\n\nbody\n", b"feat: two blanks\n\nbody\n"),
    ("feat: hash line\n\n# kept\n", b"feat: hash line\n\n# kept\n"),
    ("feat: trailing   \n\nbody \t\n", b"feat: trailing\n\nbody\n"),
]


def test_vec_v3_011_canonical_message_unit_vectors() -> None:
    """AC-C.3: ``canonical_message`` gives the D-32 byte form."""
    module = importlib.import_module("tools.commit_batch")
    for text, expected in MESSAGE_VECTORS:
        assert module.canonical_message(text) == expected, text


def test_vec_v3_011_commit_objects_hold_the_canonical_message_bytes(
    tmp_path: Path,
) -> None:
    """AC-C.3: the commit message bytes equal the journaled digest; ``# kept`` survives strip."""
    rig = _rig(tmp_path)
    parent = rig.ref()
    rig.git("config", "commit.cleanup", "strip")
    rig.reserve(OP)
    packets = [
        rig.packet(
            files={f"msg-{n}.txt": f"{n}\n".encode()}, message=text, parent=parent
        )
        for n, (text, _expected) in enumerate(MESSAGE_VECTORS, 1)
    ]
    out = _reconciled(rig.commit(OP, rig.batch(packets)))
    commits = out["commits"]
    assert len(commits) == len(MESSAGE_VECTORS)
    for n, (commit, (_text, expected)) in enumerate(
        zip(commits, MESSAGE_VECTORS, strict=True), 1
    ):
        assert rig.message_bytes(commit) == expected
        digest = _evidence(rig, f"{OP}/{n}", "prepared")["message_digest"]
        assert digest == hashlib.sha256(expected).hexdigest()


def _post_commit(marker: Path, command: str) -> str:
    """A post-commit hook that runs ``command`` once (the marker stops the recursion)."""
    target = marker.as_posix()
    return f"[ -f '{target}' ] && exit 0\n: > '{target}'\n{command}"


@pytest.mark.parametrize(
    ("command", "check"),
    [
        pytest.param(
            "git commit -q --allow-empty --no-verify -C HEAD", "parent", id="parent"
        ),
        pytest.param(
            "git commit -q --amend --no-verify -C HEAD --author='Other <other@example.com>'",
            "identity",
            id="identity",
        ),
        pytest.param(
            "git commit -q --amend --no-verify -C HEAD", "signature", id="signature"
        ),
    ],
)
def test_vec_v3_012_post_hook_parent_identity_and_signer_checks(
    tmp_path: Path, command: str, check: str
) -> None:
    """AC-C.2: a hook that adds a commit, changes the author or drops the signature fails."""
    rig = _rig(tmp_path)
    parent = rig.ref()
    rig.reserve(OP)
    rig.install_hook("post-commit", _post_commit(tmp_path / "marker", command))
    _failed(rig.commit(OP, rig.packet()), check)
    assert rig.ref() == parent


# -- the caller's index (AC-C.4) -------------------------------------------------------------


def test_vec_v3_013_conflict_stage_is_kept_and_reported(tmp_path: Path) -> None:
    """AC-C.4: a conflict stage of a manifest path is left as it is: ``conflicted``."""
    rig = _rig(tmp_path, seed={"keep.txt": b"keep\n"})
    rig.reserve(OP)
    oids = [_store_blob(rig, f"stage {n}\n".encode()) for n in (1, 2, 3)]
    _index_info(
        rig,
        [f"0 {'0' * 40}\tkeep.txt"]
        + [f"100644 {oid} {n}\tkeep.txt" for n, oid in enumerate(oids, 1)],
    )
    stages = rig.index_entries("keep.txt")
    assert len(stages) == 3
    out = _reconciled(rig.commit(OP, rig.packet(files={"keep.txt": b"kept\n"})))
    assert out["index"] == {"keep.txt": "conflicted"}
    assert rig.index_entries("keep.txt") == stages
    assert rig.ref() == out["commit"]


def test_vec_v3_014_foreign_staged_entries_are_preserved(tmp_path: Path) -> None:
    """AC-C.4: a foreign staged entry and a foreign staged deletion survive byte-identical."""
    rig = _rig(
        tmp_path,
        seed={
            "shared.txt": b"shared\n",
            "gone.txt": b"gone\n",
            "other.txt": b"other\n",
        },
    )
    rig.reserve(OP)
    _stage(rig, "shared.txt", b"foreign\n")
    rig.git("rm", "-q", "--cached", "--", "gone.txt")
    _stage(rig, "other.txt", b"other foreign\n")
    before = {
        path: rig.index_entries(path)
        for path in ("shared.txt", "gone.txt", "other.txt")
    }
    worktree = rig.worktree()
    packet = rig.packet(
        files={
            "shared.txt": b"packet\n",
            "gone.txt": b"packet gone\n",
            "fresh.txt": b"fresh\n",
        }
    )
    out = _reconciled(rig.commit(OP, packet))
    assert out["index"] == {
        "shared.txt": "foreign_staged",
        "gone.txt": "foreign_staged",
        "fresh.txt": "updated",
    }
    assert {path: rig.index_entries(path) for path in before} == before
    assert rig.worktree() == worktree


def test_vec_v3_014_concurrent_staging_during_reconciliation_is_preserved(
    tmp_path: Path,
) -> None:
    """AC-C.4: a path staged after ``index_reconciled:started`` is reported, not overwritten."""
    rig, packet, _parent = _crashed(tmp_path, "index_reconciled:started")
    _stage(rig, "change.txt", b"concurrent\n")
    staged = rig.index_entries("change.txt")
    out = _reconciled(rig.commit(OP, packet))
    assert out["index"] == {"change.txt": "foreign_staged"}
    assert rig.index_entries("change.txt") == staged


def test_vec_v3_015_durable_index_record_and_idempotent_rerun(tmp_path: Path) -> None:
    """AC-C.4: ``before.json`` and ``after.json`` record the vectors; a re-run changes nothing."""
    rig = _rig(tmp_path, seed={"keep.txt": b"keep\n", "same.txt": b"same\n"})
    rig.reserve(OP)
    _stage(rig, "same.txt", b"same new\n")
    worktree = rig.worktree()
    packet = rig.packet(
        files={"keep.txt": b"kept\n", "change.txt": CHANGE, "same.txt": b"same new\n"}
    )
    out = _reconciled(rig.commit(OP, packet))
    assert out["index"] == {
        "keep.txt": "updated",
        "change.txt": "updated",
        "same.txt": "current",
    }
    before = rig.index_record(OP, "before")
    after = rig.index_record(OP, "after")
    assert before == {
        "op": OP,
        "entries": {
            "keep.txt": [_entry(b"keep\n")],
            "change.txt": [],
            "same.txt": [_entry(b"same new\n")],
        },
    }
    assert after == {
        "op": OP,
        "entries": {
            "keep.txt": [_entry(b"kept\n")],
            "change.txt": [_entry(CHANGE)],
            "same.txt": [_entry(b"same new\n")],
        },
    }
    index = rig.index()
    _reconciled(rig.commit(OP, packet))
    assert (rig.index_record(OP, "before"), rig.index_record(OP, "after")) == (
        before,
        after,
    )
    assert rig.index() == index
    assert rig.worktree() == worktree


# -- the route and the authority (AC-C.5) ------------------------------------------------------


def test_vec_v3_016_driver_scrubs_the_inherited_git_environment(tmp_path: Path) -> None:
    """AC-C.5: inherited ``GIT_*`` and the old token are unset; the op's identity is used."""
    rig = _rig(tmp_path)
    rig.reserve(OP)
    bogus = tmp_path / "bogus"
    env = {
        "GIT_INDEX_FILE": str(bogus / "index"),
        "GIT_WORK_TREE": str(bogus / "wt"),
        "GIT_DIR": str(bogus / "git"),
        "GIT_AUTHOR_NAME": "Intruder",
        "GIT_COMMITTER_EMAIL": "intruder@example.com",
        "{{PROJECT_NAME_UPPER}}_COMMIT_APPROVED": "1",
    }
    out = _reconciled(rig.commit(OP, rig.packet(), env=env))
    assert not bogus.exists()
    identity = rig.git("show", "-s", "--format=%an <%ae>|%cn <%ce>", out["commit"])
    assert (
        identity
        == "Fixture <fixture@example.invalid>|Fixture <fixture@example.invalid>"
    )
    assert rig.git("rev-parse", ":change.txt") == b3.blob_oid(CHANGE)


def test_vec_v3_016_three_phase_entry_points_use_their_acts(tmp_path: Path) -> None:
    """AC-C.5: ``--phase plan|exec|finalize`` serve ``plan_commit``/``exec_commit``/``finalize``."""
    rig = _rig(tmp_path)
    ops = {phase: f"op-{phase}" for phase in b3.ACT_FOR_PHASE}
    for phase, act in b3.ACT_FOR_PHASE.items():
        rig.reserve(ops[phase], act=act)
    _refused(rig.commit(ops["plan"], rig.packet(), phase="exec"), "not_reserved")
    for n, (phase, act) in enumerate(b3.ACT_FOR_PHASE.items(), 1):
        packet = rig.packet(files={f"{phase}.txt": f"{n}\n".encode()})
        out = _reconciled(rig.commit(ops[phase], packet, phase=phase))
        assert rig.op_record(ops[phase])["identity"]["act"] == act
        assert rig.ref() == out["commit"]


def test_vec_v3_017_unreserved_op_is_refused(tmp_path: Path) -> None:
    """AC-C.5: an op id that names no reservation is refused before any Git object."""
    rig = _rig(tmp_path)
    rig.reserve(OP)
    before = _snapshot(rig)
    _refused(rig.commit("op-2", rig.packet()), "not_reserved")
    assert _snapshot(rig) == before
    assert not rig.op_dir("op-2").exists()


def test_vec_v3_017_script_refuses_a_fabricated_op_and_unsafe_grants(
    tmp_path: Path,
) -> None:
    """AC-C.5: a copied op file of the right shape names no reservation; a grant is an id."""
    rig, packet, parent = _crashed(tmp_path, "blobs_stored:done")
    fake = rig.op_dir("op-fake")
    shutil.copytree(rig.op_dir(OP), fake)
    record = json.loads((fake / "op.json").read_text(encoding="utf-8"))
    record["identity"]["op"] = "op-fake"
    for item in record["journal"]:
        item["identity"]["op"] = "op-fake"
    (fake / "op.json").write_bytes(
        (json.dumps(record, indent=2) + "\n").encode("utf-8")
    )

    code, out, text = rig.script("-Phase", "candidate", "-NoPush", grant="op-fake")
    assert (code, out.get("result"), out.get("reason")) == (
        1,
        "refused",
        "not_reserved",
    ), text
    for grant in ("op-missing", (rig.op_dir(OP) / "op.json").as_posix(), "../op-1"):
        code, out, text = rig.script("-Phase", "candidate", "-NoPush", grant=grant)
        assert (code, out.get("result"), out.get("reason")) == (
            1,
            "refused",
            "grant",
        ), text
    assert rig.ref() == parent
    assert rig.journal(OP)[-1] == ("blobs_stored", "done")
    _reconciled(rig.commit(OP, packet))


# -- commit consent (AC-C.6) -----------------------------------------------------------------


def test_vec_v3_018_directing_messages_commit_without_a_grant(tmp_path: Path) -> None:
    """AC-C.6: a directing message commits; the consent is in the ``prepared`` evidence."""
    rig = _rig(tmp_path)
    rig.bind()
    texts = [
        "commit it",
        "commit the fixture-plan plan on main",
        "go ahead and commit the 2026-10-17-fixture-plan plan in repo.",
    ]
    for n, text in enumerate(texts, 1):
        parent = rig.ref()
        uid = rig.fx.add_human(text)
        out = _reconciled(
            rig.human(uid, rig.packet(files={f"human-{n}.txt": b"human\n"}))
        )
        assert rig.parents(out["commit"]) == [parent] and rig.ref() == out["commit"]
        op = f"human-{uid}"
        assert out["op"] == op
        record = rig.op_record(op, run=rig.fx.session)
        assert record["journal"][0]["phase"] == "prepared"
        consent = _evidence(rig, op, "prepared", run=rig.fx.session)["consent"]
        assert consent["message_uuid"] == uid
        assert consent["scope"] == {
            "plan": rig.plan,
            "branch": "main",
            "repo": rig.fx.display,
        }
        assert str(consent["clause"]).lower() in text.lower() and consent["clause"]


def test_vec_v3_019_non_directing_messages_refuse_before_any_mutation(
    tmp_path: Path,
) -> None:
    """AC-C.6: negation, question, condition, unrelated, other scope → ``no_commit_direction``."""
    rig = _rig(tmp_path)
    rig.bind()
    packet = rig.packet()
    before = _snapshot(rig)
    for text in (
        "Do not commit anything",
        "please don't commit",
        "can you commit?",
        "if tests pass, commit",
        "looks good",
        "commit it on feature-x",
        "commit the fixture-plan-b plan",
        "commit it in other-repo",
    ):
        uid = rig.fx.add_human(text)
        _refused(rig.human(uid, packet), "no_commit_direction")
        assert _snapshot(rig) == before, text
    uid = rig.fx.add_assistant("commit it")
    _refused(rig.human(uid, packet), "record")
    assert _snapshot(rig) == before


# -- packet, binding and usage refusals (AC-C.2, AC-C.3) --------------------------------------


def test_packet_paths_and_op_ids_must_stay_in_the_repository(tmp_path: Path) -> None:
    """AC-C.2: op containment: an absolute, drive, backslash, ``..`` or ``.git/`` path."""
    rig = _rig(tmp_path)
    rig.reserve(OP)
    before = _snapshot(rig)
    for path in (
        "../x.txt",
        "dir/../../x.txt",
        ".git/config",
        ".Git/config",
        "C:/x.txt",
        "a\\b.txt",
        "/abs.txt",
    ):
        _refused(rig.commit(OP, rig.packet(files={path: b"x\n"})), "containment")
    _refused(rig.commit(OP, rig.packet(deletes=[".git/HEAD"])), "containment")
    for op in ("../evil", "C:/evil", "a\\b"):
        _refused(rig.commit(op, rig.packet()), "containment")
    assert _snapshot(rig) == before
    assert not rig.op_dir(OP).exists()
    _reconciled(rig.commit(OP, rig.packet()))


def test_packet_schema_is_strict(tmp_path: Path) -> None:
    """AC-C.2: an extra field, an unknown mode, a missing field or another schema is refused."""
    rig = _rig(tmp_path)
    rig.reserve(OP)
    before = _snapshot(rig)
    extra = {**rig.packet(), "extra": 1}
    symlink = rig.packet(modes={"change.txt": "120000"})
    missing = {key: value for key, value in rig.packet().items() if key != "message"}
    schema = {**rig.packet(), "schema": "commit-packet/2"}
    entry = rig.packet()
    entry["entries"][0]["extra"] = True
    for packet in (extra, symlink, missing, schema, entry):
        _refused(rig.commit(OP, packet), "packet_schema")
    assert _snapshot(rig) == before
    assert not rig.op_dir(OP).exists()


def test_message_that_has_no_canonical_form_is_refused(tmp_path: Path) -> None:
    """AC-C.3: an empty message, a NUL or a lone surrogate → ``message``."""
    rig = _rig(tmp_path)
    rig.reserve(OP)
    before = _snapshot(rig)
    for message in ("", "\n \n\t\n", "feat: nul\x00\n", "feat: \ud800\n"):
        _refused(rig.commit(OP, rig.packet(message=message)), "message")
    assert _snapshot(rig) == before
    assert not rig.op_dir(OP).exists()


def test_ai_attribution_in_any_packet_is_refused(tmp_path: Path) -> None:
    """AC-C.2: the ``agent-commit.ps1`` attribution pattern applies to every packet (D-5)."""
    rig = _rig(tmp_path)
    rig.reserve(OP)
    before = _snapshot(rig)
    for message in (
        f"feat: fixture change\n\n{TRAILER}\n",
        "feat: fixture change\n\nGenerated " + "with Claude Code\n",
        "feat: fixture change\n\nauthored " + "by anthropic\n",
    ):
        _refused(rig.commit(OP, rig.packet(message=message)), "attribution")
    assert _snapshot(rig) == before


def test_batch_commits_in_commit_rule_order_under_one_reservation(
    tmp_path: Path,
) -> None:
    """AC-C.2: batch ownership: sub-ops ``<op>/<n>`` chain on one ``exec_commit`` reservation."""
    rig = _rig(tmp_path)
    parent = rig.ref()
    rig.reserve(OP)
    subjects = [
        "test: specify the batch",
        "feat: add the batch",
        "fix: correct the batch",
        "docs(build-plan): mark the batch built",
        "docs(handoff): record the batch",
    ]
    packets = [
        rig.packet(
            files={f"batch-{n}.txt": f"{n}\n".encode()},
            message=f"{subject}\n",
            parent=parent,
        )
        for n, subject in enumerate(subjects, 1)
    ]
    out = _reconciled(rig.commit(OP, rig.batch(packets)))
    commits = out["commits"]
    assert len(commits) == len(subjects) and out["commit"] == commits[-1] == rig.ref()
    for n, (base, commit) in enumerate(
        zip([parent, *commits], commits, strict=False), 1
    ):
        assert rig.parents(commit) == [base]
        assert rig.message_bytes(commit) == f"{subjects[n - 1]}\n".encode()
        assert rig.journal(f"{OP}/{n}")[-1] == ("reconciled", "done")
    assert {f"batch-{n}.txt" for n in range(1, 6)} <= set(rig.tree_entries(commits[-1]))


def test_batch_is_validated_whole_before_any_git_mutation(tmp_path: Path) -> None:
    """AC-C.2: order, count, attribution and the phase are checked before the first packet."""
    rig = _rig(tmp_path)
    rig.reserve(OP)
    rig.reserve("op-plan", act="plan_commit")

    def packet(n: int, subject: str) -> dict[str, Any]:
        return rig.packet(files={f"b{n}.txt": b"x\n"}, message=f"{subject}\n")

    before = _snapshot(rig)
    _refused(
        rig.commit(OP, rig.batch([packet(1, "feat: a"), packet(2, "test: b")])),
        "batch_order",
    )
    _refused(
        rig.commit(
            OP, rig.batch([packet(1, "docs(build-plan): a"), packet(2, "feat: b")])
        ),
        "batch_order",
    )
    _refused(
        rig.commit(
            OP, rig.batch([packet(1, "test: a"), packet(2, "feat: b")], count=3)
        ),
        "batch_count",
    )
    _refused(
        rig.commit(
            OP, rig.batch([packet(1, "test: a"), packet(2, f"feat: b\n\n{TRAILER}")])
        ),
        "attribution",
    )
    _refused(
        rig.commit("op-plan", rig.batch([packet(1, "test: a")]), phase="plan"),
        "packet_schema",
    )
    assert _snapshot(rig) == before
    assert not rig.op_dir(OP).exists()


@pytest.mark.parametrize("case", ["parent_moved", "detached_head"])
def test_parent_binding_refuses_a_moved_parent_or_a_detached_head(
    tmp_path: Path, case: str
) -> None:
    """AC-C.2, AC-C.7: step 1 binds ``refs/heads/<branch>`` to P on the shared-branch route."""
    rig = _rig(tmp_path)
    rig.reserve(OP)
    if case == "parent_moved":
        packet = rig.packet(parent=rig.other_commit(message="elsewhere"))
    else:
        packet = rig.packet()
        rig.git("checkout", "-q", "--detach")
    before = _snapshot(rig)
    _refused(rig.commit(OP, packet), case)
    assert _snapshot(rig) == before


@pytest.mark.parametrize("value", ["relative/candidates", "drive-root-child"])
def test_candidate_root_must_be_absolute_and_not_a_drive_root_child(
    tmp_path: Path, value: str
) -> None:
    """AC-C.2: ``run-parameters.candidateRoot`` is absolute and never a drive-root child."""
    rig = _rig(tmp_path)
    rig.reserve(OP)
    root = (
        f"{tmp_path.drive or 'C:'}/candidates" if value == "drive-root-child" else value
    )
    rig.fx.config_set(b3.CANDIDATE_ROOT_KEY, root)
    parent = rig.ref()
    _refused(rig.commit(OP, rig.packet()), "candidate_root")
    assert rig.ref() == parent


def test_usage_errors_exit_2(tmp_path: Path) -> None:
    """AC-C.5: an unknown flag, a missing packet, an unknown phase or two routes → exit 2."""
    rig = _rig(tmp_path)
    rig.reserve(OP)
    packet = str(rig.write_packet(rig.packet()))
    for argv in (
        ["--bogus"],
        ["--phase", "exec", "--op", OP],
        ["--phase", "deploy", "--op", OP, "--packet", packet],
        [
            "--phase",
            "exec",
            "--op",
            OP,
            "--packet",
            packet,
            "--human-directed",
            "--session",
            rig.fx.session,
            "--message-uuid",
            "u",
        ],
    ):
        code, _out, text = rig.drive(*argv)
        assert code == 2, (argv, text)
    assert not rig.op_dir(OP).exists()
