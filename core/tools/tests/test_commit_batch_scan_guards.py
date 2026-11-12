"""MEU-939 execution-review round 1 fixes: the secret scan and the foreign-hunk stop.

Plan: docs/execution/plans/2026-11-07-standing-commit-grant (AC-939.4, AC-939.5; D-1 A,
D-3, D-4 "foreign hunks stop the commit", SG-D4). Review:
``.agent/context/handoffs/2026-11-07-standing-commit-grant-implementation-critical-review.md``
Round 1, findings R1-F3, R1-F4 and R1-F5.

The contract these tests fix:

* R1-F3: the human-directed route runs the same independent secret scan as the grant route,
  before the direction is claimed and before anything is written, so an inherited
  ``SKIP=detect-secrets`` (or no pre-commit hook at all) cannot let a secret through. A
  refusal is ``secret:<path>``; no ref moves, no direction claim exists, and the direction is
  still usable.
* R1-F4: the scan reads every version that any packet of a batch writes, not only the final
  state, so a secret that packet 1 adds and packet 2 replaces or deletes still refuses, on the
  grant route and on the human route.
* R1-F5: on the grant route a path whose working file differs from the parent and that another
  live owner covers refuses ``foreign_hunks:<path>:<owner>`` even when the working bytes are
  the bytes the packet commits. The packet's own plan is never foreign, and the human route
  keeps no foreign-hunk stop.

The scanner is the fake detect-secrets entry of ``test_commit_batch_direction_scope.py``
(``{{PROJECT_NAME_UPPER}}_LANES_SCAN_ENTRY``): a ``PLANTED = "<value>"`` line is a new secret. The fixture
repositories have no pre-commit hook (``core.hooksPath`` is an empty folder), so only the
independent scan can refuse.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import test_commit_batch_direction_scope as ds

pytestmark = pytest.mark.integration

SECRET_PATH = "src/mine/creds.py"
SECRET = b'PLANTED = "fixture-secret-value"\n'
CLEAN = b"CREDS = None\n"
SKIP_HOOK = {"SKIP": "detect-secrets"}


# -- helpers ---------------------------------------------------------------------------------


def _plan_rig(tmp_path: Path) -> b3.Rig:
    """The two-owner rig of the direction-scope tests, on the plan's own grant (op-1 reserved).

    The rig's plan owns ``src/mine/``; the in-progress plan ``ds.OTHER_PLAN`` owns
    ``src/other/``; ``.secrets.baseline`` is empty.
    """
    rig, plan, _uid = ds._scope_rig(tmp_path, "plan")
    assert plan == rig.plan
    return rig


def _scan_env(tmp_path: Path) -> dict[str, str | None]:
    """The fake scanner entry, with the detect-secrets hook skipped as an agent might."""
    return {**ds._scanner(tmp_path), **SKIP_HOOK}


def _direct(
    rig: b3.Rig, uid: str, data: dict[str, Any], env: dict[str, str | None]
) -> b3.Result:
    """The human route with an environment: ``--human-directed`` on one packet or a batch."""
    return rig.drive(
        "--human-directed",
        "--session",
        rig.fx.session,
        "--message-uuid",
        uid,
        "--packet",
        str(rig.write_packet(data)),
        env=env,
    )


def _human_uid(rig: b3.Rig) -> str:
    """Bind the rig's plan and record a typed direction that names it."""
    rig.bind()
    return rig.fx.add_human(f"Commit the {rig.plan} plan.")


def _two_packets(rig: b3.Rig, case: str) -> dict[str, Any]:
    """A batch whose packet 1 adds the secret and whose packet 2 replaces or deletes it."""
    parent = rig.ref()
    first = rig.packet(
        files={SECRET_PATH: SECRET},
        message="feat: add the credentials\n",
        parent=parent,
    )
    if case == "replace":
        second = rig.packet(
            files={SECRET_PATH: CLEAN},
            message="feat: clear the credentials\n",
            parent=parent,
        )
    else:
        second = rig.packet(
            files={},
            deletes=(SECRET_PATH,),
            message="feat: drop the credentials\n",
            parent=parent,
        )
        second["entries"] = [{"path": SECRET_PATH, "delete": True}]
    return rig.batch([first, second])


def _unchanged(before: dict[str, Any], after: dict[str, Any]) -> None:
    """A refusal before any write: same ref, grants, claims, working tree and index."""
    assert after["ref"] == before["ref"], "no ref moves"
    assert after["grants"] == before["grants"], "no grant is reserved or consumed"
    assert after["claims"] == before["claims"], "no direction is claimed"
    assert after["worktree"] == before["worktree"], "the working tree is byte-equal"
    assert after["index"] == before["index"], "the index is byte-equal"


# -- R1-F3: the human route scans independently of the hooks ---------------------------------


def test_r1_f3_human_route_refuses_a_secret_with_the_hook_skipped(
    tmp_path: Path,
) -> None:
    """R1-F3: ``SKIP=detect-secrets`` and no hook; the human route still refuses ``secret:<path>``.

    The refusal comes before the claim: no direction file exists, and the same direction then
    commits a clean packet, so it was not spent.
    """
    rig = _plan_rig(tmp_path)
    uid = _human_uid(rig)
    env = _scan_env(tmp_path)
    before = ds._state(rig)
    packet = rig.packet(files={SECRET_PATH: SECRET})
    assert ds._commit_refusal(_direct(rig, uid, packet, env)) == ("secret", SECRET_PATH)
    _unchanged(before, ds._state(rig))
    assert ds._claims(rig.fx) == [], "the direction is not claimed"
    clean = rig.packet(files={SECRET_PATH: CLEAN})
    out = ds._reconciled(_direct(rig, uid, clean, env))
    assert rig.ref() == out["commit"]
    assert ds._claim(rig.fx, uid).get("state") == "spent"


# -- R1-F4: every packet's written files are scanned ------------------------------------------


@pytest.mark.parametrize("case", ["replace", "delete"])
def test_r1_f4_grant_route_scans_each_packet_of_a_batch(
    tmp_path: Path, case: str
) -> None:
    """R1-F4: a secret added by packet 1 and replaced or deleted by packet 2 refuses on the grant route."""
    rig = _plan_rig(tmp_path)
    before = ds._state(rig)
    batch = _two_packets(rig, case)
    res = rig.commit("op-1", batch, env=_scan_env(tmp_path))
    assert ds._commit_refusal(res) == ("secret", SECRET_PATH)
    _unchanged(before, ds._state(rig))
    assert not (rig.op_dir("op-1") / "batch.json").exists(), "the op never started"


@pytest.mark.parametrize("case", ["replace", "delete"])
def test_r1_f4_human_route_scans_each_packet_of_a_batch(
    tmp_path: Path, case: str
) -> None:
    """R1-F4: the same add-then-replace or add-then-delete batch refuses on the human route."""
    rig = _plan_rig(tmp_path)
    uid = _human_uid(rig)
    before = ds._state(rig)
    batch = _two_packets(rig, case)
    res = _direct(rig, uid, batch, _scan_env(tmp_path))
    assert ds._commit_refusal(res) == ("secret", SECRET_PATH)
    _unchanged(before, ds._state(rig))
    assert ds._claims(rig.fx) == [], "the direction is not claimed"


# -- R1-F5: a packet built from another owner's dirty working file ----------------------------


def test_r1_f5_grant_route_refuses_foreign_dirt_equal_to_the_packet(
    tmp_path: Path,
) -> None:
    """R1-F5: another live owner's dirty file, packed byte for byte, refuses ``foreign_hunks``."""
    rig = _plan_rig(tmp_path)
    dirty = b"OTHER = 2\n"
    (rig.repo / "src/other/x.py").write_bytes(dirty)
    before = ds._state(rig)
    packet = rig.packet(files={"src/other/x.py": dirty})
    assert ds._commit_refusal(rig.commit("op-1", packet)) == (
        "foreign_hunks",
        f"src/other/x.py:{ds.OTHER_PLAN}",
    )
    _unchanged(before, ds._state(rig))
    assert (rig.repo / "src/other/x.py").read_bytes() == dirty, "the edit survives"


def test_r1_f5_grant_route_commits_the_plans_own_dirty_file(tmp_path: Path) -> None:
    """R1-F5: the packet's own in-progress plan owns ``src/mine/``; its own dirty file commits."""
    rig = _plan_rig(tmp_path)
    mine = b"MINE = 2\n"
    (rig.repo / "src/mine/a.py").write_bytes(mine)
    parent = rig.ref()
    out = ds._reconciled(rig.commit("op-1", rig.packet(files={"src/mine/a.py": mine})))
    assert out["parent"] == parent
    assert rig.ref() == out["commit"]
    assert rig.git("show", f"{out['commit']}:src/mine/a.py") == "MINE = 2"


def test_r1_f5_human_route_keeps_no_foreign_hunk_stop(tmp_path: Path) -> None:
    """R1-F5: the human route is unchanged: the typed direction commits the packed bytes."""
    rig = _plan_rig(tmp_path)
    uid = _human_uid(rig)
    dirty = b"OTHER = 2\n"
    (rig.repo / "src/other/x.py").write_bytes(dirty)
    packet = rig.packet(files={"src/other/x.py": dirty})
    out = ds._reconciled(rig.human(uid, packet))
    assert rig.ref() == out["commit"]
    assert rig.git("show", f"{out['commit']}:src/other/x.py") == "OTHER = 2"
