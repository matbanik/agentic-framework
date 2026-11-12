"""MEU-939 EA-21 tests: ``land recover`` of a publication that stopped at ``published:started``.

Plan: docs/execution/plans/2026-11-07-standing-commit-grant (AC-939.2, AC-939.3, AC-939.7,
AC-939.9; execution review round 3, R3-F1 and R3-F2).

The contract these tests fix:

* R3-F1: a land published under the standing grant records the grant's message uuid in its
  publication intent. When ``land recover`` must still move ``main`` from P to C, it
  re-checks that grant under ``store.lock`` before the swap: a revoked grant refuses
  ``revoked:<uuid>`` and a plan that opts out refuses ``standing_opt_out:<field>``; ``main``, the
  index and the journal stay as they were. When ``main`` is already at C, the recovery only
  completes the journal and the close; it needs no live authority.
* R3-F2: when ``land recover`` must still move ``main`` from P to C, it runs the D-4 check of
  the main tree first, under the main-tree lease: a staged entry refuses
  ``main_staged:<path>`` and a dirty landed path refuses ``main_overlap:<path>``, with the
  refs, the index and the files unchanged. Foreign dirt at paths that the land does not
  change stays and the recovery lands.

The rigs are the ``tools/tests/test_lanes_land.py`` and
``tools/tests/test_lanes_land_standing.py`` rigs: real ``phase_b3`` fixture repositories, a
real store and the real ``tools/lanes.py`` CLI, stopped at the ``commit:published:started``
and ``commit:published:effect`` crash seams.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.tests import test_lanes_land as tl
from tools.tests import test_lanes_land_standing as ts

pytestmark = pytest.mark.integration

OP = tl.OP
STARTED = "commit:published:started"
EFFECT = "commit:published:effect"


def _standing_crashed_at(tmp_path: Path, point: str) -> tuple[tl.Land, str]:
    """A legacy lane published on ``--grant`` under the standing grant, stopped at ``point``."""
    land = ts._gate_land(tmp_path, base=None, legacy=True)
    uid = ts._grant(land.rig.fx)
    tl._ready(land)
    tl._crashed(tl._publish_grant(land, op=OP, env=tl._crash(point)))
    return land, uid


def _human_crashed_at(tmp_path: Path, point: str, **make: Any) -> tl.Land:
    """A lane published on the human route, stopped at ``point``."""
    land = ts._make(tmp_path, **make)
    tl._ready(land)
    tl._crashed(tl._publish_human(land, env=tl._crash(point)))
    return land


def _revoke(land: tl.Land, uid: str) -> None:
    fx = land.rig.fx
    record = fx.add_human(f"revoke run_parameters {uid}")
    code, out = fx.run("revoke", "--session", fx.session, "--message", record)
    assert (code, out.get("result"), out.get("revoked")) == (0, "revoked", uid), out


def _journal_bytes(land: tl.Land) -> bytes:
    return json.dumps(tl._record(land), sort_keys=True).encode("utf-8")


def _last(land: tl.Land) -> tuple[str, str]:
    phases = tl._phases(tl._record(land))
    return phases[-1]


# -- R3-F1: the standing authority on recovery ---------------------------------------------------


def test_r3_f1_the_publication_intent_names_the_standing_grant(tmp_path: Path) -> None:
    """R3-F1: the ``published:started`` intent of a standing land carries the grant uuid."""
    land, uid = _standing_crashed_at(tmp_path, STARTED)
    assert land.rig.ref() == land.p
    assert _last(land) == ("published", "started")
    assert tl._fields(tl._record(land)).get("standing") == uid


def test_r3_f1_recovery_after_a_revoke_refuses_and_leaves_main_at_p(
    tmp_path: Path,
) -> None:
    """R3-F1: stopped before the swap, then revoked: recover refuses and ``main`` stays at P."""
    land, uid = _standing_crashed_at(tmp_path, STARTED)
    assert land.rig.ref() == land.p
    _revoke(land, uid)
    index = (land.common / "index").read_bytes()
    journal = _journal_bytes(land)
    proc = tl._recover(land)
    assert ts._refusal(proc) == f"revoked:{uid}", (proc.stdout, proc.stderr)
    assert land.rig.ref() == land.p, "main does not move after the revoke"
    assert (land.common / "index").read_bytes() == index
    assert _journal_bytes(land) == journal, "the journal stays at published:started"


def test_r3_f1_recovery_rechecks_the_standing_opt_out(tmp_path: Path) -> None:
    """R3-F1: stopped before the swap, then the plan opts out: recover refuses."""
    land, _uid = _standing_crashed_at(tmp_path, STARTED)
    fx = land.rig.fx
    fx.write_carrier(
        {**fx.block, "authorization": {"schema": "manual"}},
        plan=land.slug,
        task=False,
        grouping_line=False,
    )
    proc = tl._recover(land)
    assert ts._refusal(proc) == "standing_opt_out:manual", (proc.stdout, proc.stderr)
    assert land.rig.ref() == land.p
    assert _last(land) == ("published", "started")


def test_r3_f1_recovery_with_a_live_grant_lands(tmp_path: Path) -> None:
    """R3-F1 control: stopped before the swap with the grant still live: recover lands C on P."""
    land, _uid = _standing_crashed_at(tmp_path, STARTED)
    proc = tl._recover(land)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    c = land.rig.ref()
    assert land.rig.parents(c) == [land.p]
    assert ("land:closed", "done") in tl._phases(tl._record(land))


def test_r3_f1_an_already_published_land_completes_after_a_revoke(
    tmp_path: Path,
) -> None:
    """R3-F1 control: stopped after the swap, then revoked: recover completes the close."""
    land, uid = _standing_crashed_at(tmp_path, EFFECT)
    c = land.rig.ref()
    assert c != land.p and land.rig.parents(c) == [land.p]
    _revoke(land, uid)
    proc = tl._recover(land)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert land.rig.ref() == c
    assert ("published", "done") in tl._phases(tl._record(land))
    assert ("land:closed", "done") in tl._phases(tl._record(land))


# -- R3-F2: the D-4 main-tree check on recovery ---------------------------------------------------


def test_r3_f2_recovery_refuses_a_staged_entry_in_main(tmp_path: Path) -> None:
    """R3-F2: stopped before the swap, then a staged foreign entry: ``main_staged:<path>``."""
    land = _human_crashed_at(tmp_path, STARTED)
    assert land.rig.ref() == land.p
    (land.repo / ts.FOREIGN_TRACKED).write_bytes(b"OUTSIDE = 'staged'\n")
    land.git("add", ts.FOREIGN_TRACKED)
    index = (land.common / "index").read_bytes()
    journal = _journal_bytes(land)
    proc = tl._recover(land)
    assert ts._refusal(proc) == f"main_staged:{ts.FOREIGN_TRACKED}", (
        proc.stdout,
        proc.stderr,
    )
    assert land.rig.ref() == land.p
    assert (land.common / "index").read_bytes() == index
    assert (land.repo / ts.FOREIGN_TRACKED).read_bytes() == b"OUTSIDE = 'staged'\n"
    assert _journal_bytes(land) == journal


def test_r3_f2_recovery_refuses_a_dirty_landed_path(tmp_path: Path) -> None:
    """R3-F2: stopped before the swap, then a landed path dirty in main: ``main_overlap:<path>``."""
    land = _human_crashed_at(
        tmp_path, STARTED, lane_files={tl.BASE_FILE: b"BASE = 2\n"}
    )
    assert land.rig.ref() == land.p
    (land.repo / tl.BASE_FILE).write_bytes(b"BASE = 'main'\n")
    index = (land.common / "index").read_bytes()
    journal = _journal_bytes(land)
    proc = tl._recover(land)
    assert ts._refusal(proc) == f"main_overlap:{tl.BASE_FILE}", (
        proc.stdout,
        proc.stderr,
    )
    assert land.rig.ref() == land.p
    assert (land.common / "index").read_bytes() == index
    assert (land.repo / tl.BASE_FILE).read_bytes() == b"BASE = 'main'\n"
    assert _journal_bytes(land) == journal


def test_r3_f2_recovery_keeps_unrelated_foreign_dirt_and_lands(tmp_path: Path) -> None:
    """R3-F2 control: foreign dirt at paths the land does not change stays; recover lands."""
    land = _human_crashed_at(tmp_path, STARTED)
    before = ts._dirty_foreign(land)
    proc = tl._recover(land)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    c = land.rig.ref()
    assert land.rig.parents(c) == [land.p]
    assert ts._foreign_hashes(land) == before, "every foreign file keeps its bytes"
    assert ("land:closed", "done") in tl._phases(tl._record(land))
