"""MEU-785 execution review round 2 corrections (R2-F1, R2-F2) — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.17 / AC-785.21 / AC-785.23 / AC-785.33 (design D:248, D:258-266).

R2-F1: step 8 writes working files before it writes the index, so a crash can leave a
working file already at C while its index entry is still at P. Both states are
explained, and recovery must finish the sync.

R2-F2: the candidate gets the runtime that the reviewed tree T configures. A lane that
changes ``venv_build`` in ``.agent/credits/worktree.json`` gives its candidate a venv
built with that command, at ``land prepare`` and at recovery; an unchanged config keeps
the main tree's command.

Every rig is a disposable ``phase_b3`` repository in ``tmp_path`` (the lane rigs of
``test_lanes_recovery.py`` and ``test_lanes_integrate.py``). Do not skip, only, or
early-return (G36).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.tests import lane_worktree_config as lwc
from tools.tests import test_lanes_integrate as ti
from tools.tests import test_lanes_recovery as lrx

CONFIG = lwc.WORKTREE_CONFIG
VENV_BUILD = [sys.executable, "-m", "venv", "--without-pip", ".venv"]
# The gate passes only under the candidate's own venv interpreter.
VENV_GATE = (
    '"""Fixture gate: it runs under the candidate\'s own .venv (R2-F2)."""\n'
    "\n"
    "import os\n"
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "venv = Path(__file__).resolve().parents[1] / '.venv'\n"
    "if not (venv.is_dir() and os.path.samefile(sys.prefix, venv)):\n"
    "    print('gate interpreter', sys.prefix, 'is not', venv)\n"
    "    sys.exit(3)\n"
    "sys.exit(0)\n"
)


# ---------------------------------------------------------------------------
# R2-F1
# ---------------------------------------------------------------------------


def _crashed_at_sync(tmp_path: Path) -> tuple[lrx.LaneRig, str]:
    """A land published to C whose step 8 crashed at ``land:sync:started``; (rig, C)."""
    lr = lrx.lane_rig(tmp_path)
    lrx.ready(lr)
    lrx.crashed(lrx.publish(lr, env={lrx.CRASH: "land:sync:started"}))
    c = lrx.main_ref(lr)
    assert c != lr.p
    return lr, c


def _blob(repo: Path, c: str, rel: str) -> bytes:
    """The exact bytes of ``rel`` at ``c`` (``git show``, no text decoding)."""
    proc = subprocess.run(
        ["git", "show", f"{c}:{rel}"],
        cwd=str(repo),
        capture_output=True,
        env=lrx.b3_env(),
        timeout=lrx.CLI_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (rel, proc.stderr)
    return proc.stdout


def _work_at_c(lr: lrx.LaneRig, c: str, paths: list[str]) -> None:
    """Setup only: the working files of ``paths`` hold C's bytes; the index stays at P."""
    for rel in paths:
        full = lr.repo / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(_blob(lr.repo, c, rel))


def _changed(lr: lrx.LaneRig, c: str) -> list[str]:
    """The paths of P..C that C holds (the lane's file and the integrated junction files)."""
    names = lrx.git(lr.repo, "diff-tree", "-r", "--no-renames", "--name-only", lr.p, c)
    kept = lrx.git(lr.repo, "ls-tree", "-r", "--name-only", c)
    return sorted(set(names.splitlines()) & set(kept.splitlines()))


@pytest.mark.parametrize("scope", ["new-file", "every-path"])
def test_r2_f1_a_working_file_at_c_with_its_index_at_p_still_recovers(
    tmp_path: Path, scope: str
) -> None:
    """R2-F1, AC-785.21/.23 row "Step 8 partly done": a working file already at C with
    its index entry at P is explained; recovery finishes the sync and closes the land
    without a refused read-tree."""
    lr, c = _crashed_at_sync(tmp_path)
    paths = [lr.changed] if scope == "new-file" else _changed(lr, c)
    assert lr.changed in paths and len(paths) >= 1, paths
    _work_at_c(lr, c, paths)
    assert lrx.git(lr.repo, "ls-files", "--", lr.changed) == "", "index not at P"
    lrx.ok(lrx.recover(lr))
    assert (lr.repo / lr.changed).read_bytes() == (lr.wt / lr.changed).read_bytes()
    lrx.assert_closed(lr)
    lrx.assert_main_tree_at(lr, c)
    assert ("land:sync", "refused:sync_refused") not in lrx.phases(lr)


# ---------------------------------------------------------------------------
# R2-F2
# ---------------------------------------------------------------------------


def _config_text(venv_build: list[str] | None) -> str:
    return json.dumps({**lwc.WORKTREE_CONFIG_DATA, "venv_build": venv_build}) + "\n"


ORIGINAL_OWNERSHIP = ti._ownership


def _owning_the_config(task: bytes, slug: str) -> bytes:
    """``ti._ownership`` with the worktree config added to the lane's ``owns``."""
    text = ORIGINAL_OWNERSHIP(task, slug).decode("utf-8")
    assert text.count("owns:\n") == 1, text
    return text.replace("owns:\n", f"owns:\n  - {CONFIG}\n").encode("utf-8")


def _venv_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, lane_config: bool
) -> ti.Land:
    """Setup only: a lane with a real ``.venv``; the gate needs the candidate's own venv.

    ``lane_config``: main keeps ``venv_build: null`` and the lane commits ``VENV_BUILD``
    in its owned worktree config. Otherwise main already holds ``VENV_BUILD`` and the
    lane leaves the config alone. One lane commit; main moved.
    """
    monkeypatch.setattr(ti, "GATE_STUB", VENV_GATE)
    if lane_config:
        monkeypatch.setattr(ti, "_ownership", _owning_the_config)
    else:
        monkeypatch.setattr(
            lwc, "SEED", {CONFIG: _config_text(VENV_BUILD).encode("utf-8")}
        )
    land = ti._build(tmp_path)
    exclude = land.rig.fx.common_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("ab") as out:
        out.write(b".venv/\n")
    if lane_config:
        (land.wt / CONFIG).write_bytes(_config_text(VENV_BUILD).encode("utf-8"))
    ti._lane_commit(land, [(land.rid(1), f"metrics-row {ti.LANE_ROW}")])
    built = subprocess.run(
        [*VENV_BUILD[:-1], str(land.wt / ".venv")],
        capture_output=True,
        timeout=ti.CLI_TIMEOUT_S,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    assert ti.bf.git(land.wt, "status", "--porcelain") == "", "the lane venv is tracked"
    ti._move_main(land)
    main_config = json.loads((land.repo / CONFIG).read_text(encoding="utf-8"))
    assert main_config["venv_build"] == (None if lane_config else VENV_BUILD)
    return land


def _candidate(land: ti.Land) -> Path:
    """The land candidate worktree of the op (``land-<op>``), from ``git worktree list``."""
    listing = ti.bf.git(land.repo, "worktree", "list", "--porcelain")
    found = [
        Path(line[len("worktree ") :])
        for line in listing.splitlines()
        if line.startswith("worktree ")
        and Path(line[len("worktree ") :]).name == f"land-{ti.OP_ID}"
    ]
    assert len(found) == 1, listing
    return found[0]


@pytest.mark.parametrize(
    ("lane_config", "recovery"),
    [(True, False), (True, True), (False, False)],
    ids=["lane-config-prepare", "lane-config-recovery", "main-config-prepare"],
)
def test_r2_f2_the_candidate_venv_follows_the_reviewed_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lane_config: bool, recovery: bool
) -> None:
    """R2-F2, AC-785.17/.33: the candidate's venv is built with the ``venv_build`` of
    T's worktree config, so the gate on T runs under the candidate's own interpreter."""
    land = _venv_lane(tmp_path, monkeypatch, lane_config=lane_config)
    if recovery:
        lrx.crashed(ti._prepare(land, env={lrx.CRASH: "land:ready:started"}))
        proc = ti._lanes(land, "land", "recover", "--op", ti.OP_ID, cwd=land.wt)
    else:
        proc = ti._prepare(land)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert ti._journal(land)["gate"]["result"] == "pass", ti._journal(land)
    assert (_candidate(land) / ".venv" / "pyvenv.cfg").is_file()
