"""MEU-785 WP-C Red: the lane-to-transcript mapping of ``tools/run_parameters.py`` (AC-785.27).

A Claude session that runs in a lane worktree keeps its transcript in the project folder
of the lane worktree path, not of the main tree (design D:276, D:364). The transcript
lookup (``_transcript_path``, ``tools/run_parameters.py:1036``) finds such a transcript
only when the worktree is in ``git worktree list`` AND a lane card in ``active`` or
``landing`` reserves it. The lookup stays inside the configured Claude transcript
adapter (``_config_dir()``). A transcript under an unreserved worktree refuses
``transcript_unmapped``.

Fixture: a real temporary repository (``phase_b3.rig``) with a grant accepted in the
main tree, a lane worktree on ``lane/<slug>``, and the session transcript moved from the
main tree's project folder to the lane's. Cards are written to ``<common>/lanes/`` and
checked with the stage-1 card validator (``tools/lanes.py`` ``_validate_card``). The main
tree transcript rule of R1-F2 (``test_run_parameters_r1_corrections.py``) is unchanged.
"""

from __future__ import annotations

import importlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import lane_worktree_config as lwc

ROOT = Path(__file__).resolve().parents[2]
LANDING_OP = "op-land-transcript-1"
GENERATION = "0123456789abcdef"


def _lanes() -> ModuleType:
    return importlib.import_module("tools.lanes")


def _rp() -> ModuleType:
    return importlib.import_module("tools.run_parameters")


def _lane_worktree(rig: b3.Rig, tmp_path: Path, name: str) -> Path:
    """Add the linked worktree ``<tmp>/wt/<name>`` on branch ``lane/<name>``."""
    lane = tmp_path / "wt" / name
    lane.parent.mkdir(parents=True, exist_ok=True)
    bf.git(rig.repo, "worktree", "add", "-q", "-b", f"lane/{name}", str(lane), "HEAD")
    return lane


def _move_transcript(fx: bf.Fixture, lane: Path) -> Path:
    """Move the session transcript into the project folder of ``lane``; return its path."""
    source = fx.transcript_path()
    target = fx.transcript_path(display=bf.display_path(lane))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    assert not source.exists(), source
    return target


def _write_card(
    rig: b3.Rig, lane_name: str, worktree: Path, state: str
) -> dict[str, Any]:
    """Write a valid lane card that names ``worktree``, in ``state``."""
    lanes = _lanes()
    card: dict[str, Any] = {
        "lane": lane_name,
        "generation": GENERATION,
        "session": rig.fx.session,
        "state": state,
        "op": LANDING_OP if state == "landing" else None,
        "worktree": worktree.resolve().as_posix(),
        "branch": None,
        "plan": f"docs/execution/plans/{rig.plan}/",
        "owns": ["src/lane/"],
        "claims": [],
        "gates": [],
        "updated": lanes._utc_text(datetime.now(timezone.utc)),
    }
    lanes._validate_card(card)
    path = lanes._card_path(rig.fx.common_dir, lane_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    return card


def _verify(
    fx: bf.Fixture, lane: Path, **env: str | None
) -> tuple[int, dict[str, Any]]:
    return fx.run("verify", "exec_start", "--plan", fx.plan, repo=lane, env=env)


def _assert_verified(code: int, out: dict[str, Any]) -> None:
    assert (code, out.get("result"), out.get("authorized")) == (
        0,
        "verified",
        True,
    ), out


def _assert_unmapped(code: int, out: dict[str, Any]) -> None:
    assert (code, out.get("reason")) == (1, "transcript_unmapped"), out


def _rig_with_lane(tmp_path: Path, name: str = "lane-a") -> tuple[b3.Rig, Path]:
    """The rig (grant verified in the main tree) and a lane worktree holding the transcript."""
    rig = b3.rig(tmp_path / "fx", ROOT, seed=lwc.SEED)
    code, out = rig.fx.run("verify", "exec_start", "--plan", rig.plan)
    _assert_verified(code, out)
    lane = _lane_worktree(rig, tmp_path, name)
    _move_transcript(rig.fx, lane)
    return rig, lane


def test_active_card_maps_the_lane_transcript(tmp_path: Path) -> None:
    """AC-785.27: a listed worktree that an ``active`` card reserves finds its transcript."""
    rig, lane = _rig_with_lane(tmp_path)
    _write_card(rig, "lane-a", lane, "active")
    _assert_verified(*_verify(rig.fx, lane))


def test_landing_card_maps_the_lane_transcript(tmp_path: Path) -> None:
    """AC-785.27: a ``landing`` card reserves the worktree too."""
    rig, lane = _rig_with_lane(tmp_path)
    _write_card(rig, "lane-a", lane, "landing")
    _assert_verified(*_verify(rig.fx, lane))


def test_unreserved_worktree_refuses_transcript_unmapped(tmp_path: Path) -> None:
    """AC-785.27 edge: a listed worktree with no card refuses ``transcript_unmapped``."""
    rig, lane = _rig_with_lane(tmp_path)
    assert not _lanes()._card_files(_lanes()._lanes_dir(rig.fx.common_dir))
    _assert_unmapped(*_verify(rig.fx, lane))


def test_released_card_does_not_reserve(tmp_path: Path) -> None:
    """AC-785.27 edge: a ``released`` card does not reserve the worktree."""
    rig, lane = _rig_with_lane(tmp_path)
    _write_card(rig, "lane-a", lane, "released")
    _assert_unmapped(*_verify(rig.fx, lane))


def test_card_for_another_worktree_does_not_map(tmp_path: Path) -> None:
    """AC-785.27 edge: an active card that names a different listed worktree maps nothing."""
    rig, lane = _rig_with_lane(tmp_path)
    other = _lane_worktree(rig, tmp_path, "lane-b")
    _write_card(rig, "lane-b", other, "active")
    _assert_unmapped(*_verify(rig.fx, lane))


def test_mapping_reads_the_configured_adapter_folder(tmp_path: Path) -> None:
    """AC-785.27: the lane folder is resolved under ``_config_dir()`` (``CLAUDE_CONFIG_DIR``)."""
    rig, lane = _rig_with_lane(tmp_path)
    _write_card(rig, "lane-a", lane, "active")
    moved = tmp_path / "relocated-claude"
    shutil.copytree(rig.fx.config_dir, moved)
    shutil.rmtree(rig.fx.config_dir)
    code, out = _verify(rig.fx, lane, CLAUDE_CONFIG_DIR=str(moved))
    _assert_verified(code, out)
    with bf.patched_environ(rig.fx.env(CLAUDE_CONFIG_DIR=str(moved))):
        rp = _rp()
        path = rp._transcript_path(rp._open_repo(lane), rig.fx.session)
    slug = bf.project_slug(bf.display_path(lane))
    assert path == moved / "projects" / slug / f"{rig.fx.session}.jsonl", path


def test_main_tree_transcript_rule_is_unchanged_beside_a_reserved_lane(
    tmp_path: Path,
) -> None:
    """AC-785.27: with a reserved lane, the main tree still reads its own project folder only."""
    rig, lane = _rig_with_lane(tmp_path)
    _write_card(rig, "lane-a", lane, "active")
    _assert_verified(*_verify(rig.fx, lane))
    code, out = rig.fx.run("verify", "exec_start", "--plan", rig.plan)
    assert (code, out.get("reason")) == (1, "transcript_missing"), out


def test_removed_worktree_is_no_longer_mapped(tmp_path: Path) -> None:
    """AC-785.27: the mapping needs the worktree in ``git worktree list``, not only the card."""
    rig, lane = _rig_with_lane(tmp_path)
    _write_card(rig, "lane-a", lane, "active")
    _assert_verified(*_verify(rig.fx, lane))
    bf.git(rig.repo, "worktree", "remove", "--force", str(lane))
    bf.git(rig.repo, "worktree", "prune")
    assert not lane.exists(), lane
    assert rig.fx.transcript_path(display=bf.display_path(lane)).is_file()
    code, out = rig.fx.run("verify", "exec_start", "--plan", rig.plan)
    assert (code, out.get("reason")) == (1, "transcript_missing"), out
