"""MEU-785 WP-C Red: the final read set takes the MEU handoffs (AC-785.41).

KI ``FINAL-PRODUCE-MEU-HANDOFF-SET``:
``tools/run_parameters.py`` ``_final_paths`` (:3569) names only the project handoff
``<slug>-handoff.md`` and ``_read_set`` (:3609) requires it, while
``completion_preflight.check_handoffs`` (:370) requires ``<slug>-<MEU>-handoff.md`` for
every entry of ``task.md`` ``meus``. The fix: the read set holds one MEU handoff per
``meus`` entry, and the project handoff only when ``meus`` is empty;
``run_stage_validators`` (:3830) passes one ``--handoff`` per MEU handoff to the closeout
validator (its ``--handoff`` is ``action="append"``) and runs the final preflight on a
snapshot that holds them.

Fixture: the ``commit_exec: false`` closeout flow of ``test_validate_closeout_stages.py``
(``_flow``: a real temporary repository, initialized, bound, closed, with its closeout
files; ``run_stage_validators`` replaced by a fixed result).
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.test_validate_closeout_stages import (
    VALIDATORS,
    _flow,
    _frontmatter,
    _produce,
    _receipt,
    _rel,
    _rp,
    _split,
)

HANDOFFS = ".agent/context/handoffs"


def _meu_handoff(plan: str, meu: str) -> str:
    return f"{HANDOFFS}/{plan}-{meu}-handoff.md"


def _set_meus(fx: bf.Fixture, meus: list[str]) -> None:
    """Write ``meus`` into the frontmatter of the fixture task.md."""
    meta, body = _split(fx.task_path())
    meta["meus"] = meus
    fx.task_path().write_bytes(_frontmatter(meta, body))


def _write_meu_handoffs(fx: bf.Fixture, meus: Sequence[str]) -> list[str]:
    rels = [_meu_handoff(fx.plan, meu) for meu in meus]
    for meu, rel in zip(meus, rels, strict=True):
        fx.write_text(rel, f"# {meu} handoff\n\nThe fixture run.\n")
    return rels


def _drop_project_handoff(fx: bf.Fixture) -> str:
    rel = _rel(fx.plan)["handoff"]
    (fx.repo / rel).unlink()
    return rel


def _read_set_paths(fx: bf.Fixture) -> set[str]:
    return {entry["path"] for entry in _rp().final_read_set(fx.repo, fx.plan)}


def test_meu_plan_read_set_takes_the_meu_handoff_not_the_project_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-785.41: ``meus: [MEU-1]`` with only ``<slug>-MEU-1-handoff.md`` binds that file."""
    fx = _flow(tmp_path, monkeypatch)
    _set_meus(fx, ["MEU-1"])
    project = _drop_project_handoff(fx)
    (meu_rel,) = _write_meu_handoffs(fx, ["MEU-1"])
    paths = _read_set_paths(fx)
    assert meu_rel in paths, paths
    assert project not in paths, paths
    entry = next(
        e for e in _rp().final_read_set(fx.repo, fx.plan) if e["path"] == meu_rel
    )
    assert (entry["shared"], entry["kind"]) == (False, "file"), entry


def test_meu_plan_final_produce_binds_and_its_snapshot_holds_the_meu_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-785.41: ``final --produce`` binds the MEU handoff; the validators' snapshot holds it."""
    fx = _flow(tmp_path, monkeypatch)
    _set_meus(fx, ["MEU-1"])
    project = _drop_project_handoff(fx)
    (meu_rel,) = _write_meu_handoffs(fx, ["MEU-1"])
    seen: dict[str, set[str]] = {}

    def validators(*args: Any, **kwargs: Any) -> dict[str, Any]:
        snapshot = Path(kwargs["snapshot"] if "snapshot" in kwargs else args[2])
        seen["files"] = {
            p.relative_to(snapshot).as_posix()
            for p in snapshot.rglob("*")
            if p.is_file()
        }
        return copy.deepcopy(VALIDATORS)

    monkeypatch.setattr(_rp(), "run_stage_validators", validators, raising=False)
    code, out = _produce(fx)
    assert code == 0, out
    receipt = _receipt(fx)
    bound = {entry["path"] for entry in receipt["read_set"]}
    assert meu_rel in bound and project not in bound, receipt
    assert meu_rel in seen.get("files", set()), seen


def test_meu_plan_missing_its_meu_handoff_refuses_read_set_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-785.41 edge: the same plan without ``<slug>-MEU-1-handoff.md`` refuses that path."""
    fx = _flow(tmp_path, monkeypatch)
    _set_meus(fx, ["MEU-1"])
    missing = _meu_handoff(fx.plan, "MEU-1")
    rp = _rp()
    with pytest.raises(rp.Refusal) as caught:
        rp.final_read_set(fx.repo, fx.plan)
    assert (caught.value.reason, caught.value.detail) == (
        "binding",
        f"read_set_missing:{missing}",
    ), caught.value
    code, out = _produce(fx)
    assert (code, out.get("reason")) == (1, "binding"), out


def test_empty_meus_keeps_the_project_handoff_and_meus_take_one_handoff_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-785.41: ``meus: []`` keeps ``<slug>-handoff.md``; two MEUs bind two MEU handoffs."""
    fx = _flow(tmp_path, monkeypatch)
    _set_meus(fx, [])
    project = _rel(fx.plan)["handoff"]
    stray = _write_meu_handoffs(fx, ["MEU-9"])[0]
    paths = _read_set_paths(fx)
    assert project in paths and stray not in paths, paths
    _set_meus(fx, ["MEU-1", "MEU-2"])
    _drop_project_handoff(fx)
    rels = _write_meu_handoffs(fx, ["MEU-1", "MEU-2"])
    paths = _read_set_paths(fx)
    assert set(rels) <= paths, paths
    assert project not in paths and stray not in paths, paths


def test_run_stage_validators_passes_one_handoff_per_meu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-785.41: the closeout validator gets one ``--handoff`` per MEU handoff, no project one."""
    rp = _rp()
    run_stage_validators = rp.run_stage_validators
    fx = _flow(tmp_path, monkeypatch)
    _set_meus(fx, ["MEU-1", "MEU-2"])
    _drop_project_handoff(fx)
    rels = _write_meu_handoffs(fx, ["MEU-1", "MEU-2"])
    calls: list[list[str]] = []

    def record(argv: Sequence[str], cwd: Path, env: Any) -> int:
        calls.append([str(item) for item in argv])
        return 0

    monkeypatch.setattr(rp, "_validator_run", record)
    run_stage_validators(fx.repo, fx.plan, fx.repo)
    finals = [argv for argv in calls if "--for-produce" in argv]
    assert len(finals) == 1, calls
    argv = finals[0]
    handoffs = [argv[i + 1] for i, item in enumerate(argv) if item == "--handoff"]
    assert handoffs == [str(fx.repo / rel) for rel in rels], argv
    preflight = [argv for argv in calls if "--tree" in argv]
    assert len(preflight) == 1, calls
    assert preflight[0][preflight[0].index("--tree") + 1] == str(fx.repo), preflight
