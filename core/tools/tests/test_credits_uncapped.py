"""Credits USD caps follow the repo's ``token_budgets`` switch (AC-21 (a)-(e)).

Plan: docs/execution/plans/2026-10-20-review-limits-parameters (WP-5; D-1, D-11, D-12,
D-13).

Under ``token_budgets: "off"`` in ``<project_root>/.agent/review-limits.json``, a manifest
may omit ``launch.segment_cap_usd``, ``budget.run_cap_usd`` and ``chain.chain_cap_usd``,
in any mix. The store keeps NULL for an omitted cap.

(a) ``register``: an omitted cap under ``"on"``, or with no repo file, is
    ``manifest_invalid``; a malformed repo file is ``review_limits_invalid``; a present
    cap is still checked. A manifest with every cap never reads the file.
(b) ``admit`` reserves the smallest room of the caps that are present. With no room it
    admits ``uncapped`` with a reservation of 0, and the floor does not apply.
(c) Each admission of a run with an omitted cap reads the file again: ``"on"`` or no file
    is ``caps_required``. A first start fails (``start_refused``); a resume stays
    ``stopped`` (``resume_refused``). A capped run never reads the file.
(d) An uncapped segment with no trusted cost books an exposure of 0.
(e) ``chain_room`` is None when no run of the chain holds a cap: ``chain_candidates``
    reports ``chain_room_usd: null``, and ``ready`` ignores the floor.

The tests drive the store through its CLI, in a subprocess, with a temp store and a temp
project folder per test.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from test_credits_state import (
    ROOT,
    SESSION_A,
    SESSION_B,
    Store,
    accept_args,
    finish,
    request_args,
    start_segment,
    stop,
    write_manifest,
)

EXIT_REFUSED = 3
FLOOR_USD = 5.0
LIMITS = ROOT / ".agent" / "review-limits.json"
CHAIN = {
    "chain_id": "chain-uncapped",
    "quote": "Run u-a, then u-b.",
    "given_at": "2026-10-20T01:00:00Z",
}
ALL_CAPS = ("segment", "run", "chain")


@pytest.fixture
def st(tmp_path: Path) -> Store:
    store = Store(tmp_path / "store")
    store.root.mkdir()
    store.init()
    return store


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project folder that is a git repository with one commit (``chain_candidates``)."""
    root = tmp_path / "project"
    root.mkdir()
    for args in (
        ["init", "-q"],
        ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-q", "--allow-empty", "-m", "fixture"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


def set_switch(project: Path, switch: str | None) -> None:
    """Write the shipped review-limits file with ``token_budgets`` set, or delete it."""
    path = project / ".agent" / "review-limits.json"
    if switch is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(exist_ok=True)
    data = json.loads(LIMITS.read_text(encoding="utf-8"))
    data["token_budgets"] = switch
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def break_switch(project: Path) -> None:
    path = project / ".agent" / "review-limits.json"
    path.parent.mkdir(exist_ok=True)
    data = json.loads(LIMITS.read_text(encoding="utf-8"))
    data["extra"] = 1
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def manifest(
    st: Store,
    project: Path,
    run_id: str,
    *,
    omit: tuple[str, ...] = (),
    caps: dict[str, float] | None = None,
    chain: bool = False,
) -> Path:
    """A fixture manifest rooted at ``project``, less the caps in ``omit``.

    ``caps`` sets ``segment``, ``run`` or ``chain`` to a value; ``chain`` adds a chain
    block (with ``chain_cap_usd`` unless ``"chain"`` is omitted). Each run has its own lane.
    """
    caps = {"segment": 75.0, "run": 200.0, "chain": 10.0, **(caps or {})}
    path = write_manifest(st, run_id, lane=f"tree:X:/fixture-tree/{run_id}")
    doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    doc["project_root"] = str(project)
    doc["launch"]["segment_cap_usd"] = caps["segment"]
    doc["budget"]["run_cap_usd"] = caps["run"]
    if chain:
        doc["chain"] = {**CHAIN, "chain_cap_usd": caps["chain"]}
    if "segment" in omit:
        del doc["launch"]["segment_cap_usd"]
    if "run" in omit:
        del doc["budget"]["run_cap_usd"]
    if "chain" in omit and "chain" in doc:
        del doc["chain"]["chain_cap_usd"]
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def register(st: Store, project: Path, run_id: str, **kw: Any) -> Any:
    return st.cli(
        "register",
        "--run-id",
        run_id,
        "--manifest",
        str(manifest(st, project, run_id, **kw)),
        "--cli-version",
        "9.9.9",
        "--kit-revision",
        "kitrev-fixture",
    )


def registered(st: Store, project: Path, run_id: str, **kw: Any) -> None:
    out = register(st, project, run_id, **kw)
    assert out.code == 0 and out.result == "changed", out.show()
    st.ok("registered", "--run-id", run_id, "--task-hash", f"taskhash-{run_id}")


def admit(
    st: Store, run_id: str, n: int, *, now: int, resume: bool = False
) -> dict[str, Any]:
    """Request, accept and admit segment ``n``; return the admit payload."""
    session = SESSION_A if n == 1 else SESSION_B
    st.ok("request", *request_args(run_id, n, resume=resume), now=now)
    st.ok("accept", *accept_args(run_id, n, session), now=now + 1)
    return st.ok(
        "admit",
        "--attempt-id",
        f"att-{run_id}-{n}",
        "--segment-id",
        f"seg-{run_id}-{n}",
        now=now + 2,
    )


def spent_run(
    st: Store, project: Path, run_id: str, total: float, **kw: Any
) -> None:
    """Register a run, run one segment that costs ``total``, and stop the run."""
    registered(st, project, run_id, **kw)
    seg = start_segment(st, run_id, 1, now=10)
    finish(st, seg, now=100, total=total)
    stop(st, run_id, now=110)


def run_row(st: Store, run_id: str) -> tuple[Any, ...]:
    return st.rows(
        "SELECT state, segment_cap_usd, run_cap_usd FROM runs WHERE run_id = ?",
        (run_id,),
    )[0]


def notices(st: Store, run_id: str) -> list[str]:
    return [
        str(row[0])
        for row in st.rows(
            "SELECT kind FROM notices WHERE run_id = ? ORDER BY created_utc", (run_id,)
        )
    ]


def check_ok(st: Store) -> None:
    out = st.cli("check", now=200)
    assert out.code == 0 and out.result == "ok", out.show()


# --- (a) register ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "omit", [("segment",), ("run",), ("chain",), ("segment", "run"), ALL_CAPS]
)
def test_off_registers_a_manifest_without_caps(
    st: Store, project: Path, omit: tuple[str, ...]
) -> None:
    set_switch(project, "off")
    out = register(st, project, "u-a", omit=omit, chain=True)
    assert out.code == 0 and out.result == "changed", out.show()
    _, segment_cap, run_cap = run_row(st, "u-a")
    assert (segment_cap is None) == ("segment" in omit)
    assert (run_cap is None) == ("run" in omit)
    stored = json.loads(str(st.one("SELECT manifest_json FROM runs")))
    assert ("chain_cap_usd" in stored["chain"]) == ("chain" not in omit)


@pytest.mark.parametrize("switch", ["on", None])
@pytest.mark.parametrize("omit", [("segment",), ("run",), ("chain",)])
def test_an_omitted_cap_needs_off(
    st: Store, project: Path, switch: str | None, omit: tuple[str, ...]
) -> None:
    set_switch(project, switch)
    out = register(st, project, "u-a", omit=omit, chain=True)
    assert out.code == EXIT_REFUSED and out.error == "manifest_invalid", out.show()
    name = {"segment": "segment_cap_usd", "run": "run_cap_usd", "chain": "chain_cap_usd"}
    message = str(out.payload and out.payload["message"])
    assert name[omit[0]] in message and "token_budgets" in message, message
    assert st.rows("SELECT * FROM runs") == []


def test_a_malformed_repo_file_refuses_an_omitted_cap(
    st: Store, project: Path
) -> None:
    break_switch(project)
    out = register(st, project, "u-a", omit=("segment",))
    assert out.code == EXIT_REFUSED and out.error == "review_limits_invalid", out.show()
    assert st.rows("SELECT * FROM runs") == []


@pytest.mark.parametrize("cap", ["segment", "run", "chain"])
def test_off_still_refuses_a_cap_of_zero(st: Store, project: Path, cap: str) -> None:
    set_switch(project, "off")
    out = register(st, project, "u-a", caps={cap: 0}, chain=True)
    assert out.code == EXIT_REFUSED and out.error == "manifest_invalid", out.show()


def test_off_still_refuses_a_null_cap(st: Store, project: Path) -> None:
    set_switch(project, "off")
    path = manifest(st, project, "u-a")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["launch"]["segment_cap_usd"] = None
    path.write_text(json.dumps(doc), encoding="utf-8")
    out = st.cli(
        "register", "--run-id", "u-a", "--manifest", str(path),
        "--cli-version", "9.9.9", "--kit-revision", "kitrev-fixture",
    )
    assert out.code == EXIT_REFUSED and out.error == "manifest_invalid", out.show()


@pytest.mark.parametrize("state", ["absent", "malformed", "on"])
def test_a_manifest_with_every_cap_never_reads_the_file(
    st: Store, project: Path, state: str
) -> None:
    if state == "malformed":
        break_switch(project)
    elif state == "on":
        set_switch(project, "on")
    out = register(st, project, "u-a", chain=True)
    assert out.code == 0 and out.result == "changed", out.show()
    assert run_row(st, "u-a") == ("registering", 75.0, 200.0)


def test_the_chain_block_keeps_its_exact_keys(st: Store, project: Path) -> None:
    set_switch(project, "off")
    path = manifest(st, project, "u-a", chain=True, omit=("chain",))
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["chain"]["extra"] = 1
    path.write_text(json.dumps(doc), encoding="utf-8")
    out = st.cli(
        "register", "--run-id", "u-a", "--manifest", str(path),
        "--cli-version", "9.9.9", "--kit-revision", "kitrev-fixture",
    )
    assert out.code == EXIT_REFUSED and out.error == "manifest_invalid", out.show()


# --- (b) admission -----------------------------------------------------------------------


def test_an_uncapped_run_is_admitted_after_any_spend(st: Store, project: Path) -> None:
    set_switch(project, "off")
    spent_run(st, project, "u-a", 1_000_000.0, omit=ALL_CAPS, chain=True)
    spend = st.ok("spend", "--run-id", "u-a", now=120, expect=("ok",))
    assert spend["known_spent_usd"] == 1e6, spend
    admitted = admit(st, "u-a", 2, now=130, resume=True)
    assert admitted["outcome"] == "admitted", admitted
    assert admitted["reservation_usd"] == 0 and admitted["uncapped"] is True, admitted
    check_ok(st)


def test_a_capped_admission_says_it_is_capped(st: Store, project: Path) -> None:
    registered(st, project, "u-a")
    admitted = admit(st, "u-a", 1, now=10)
    assert admitted["reservation_usd"] == 75.0 and admitted["uncapped"] is False


def test_a_run_cap_alone_still_has_the_floor(st: Store, project: Path) -> None:
    set_switch(project, "off")
    spent_run(st, project, "u-a", 197.0, omit=("segment",))
    rejected = admit(st, "u-a", 2, now=130, resume=True)
    assert rejected["outcome"] == "rejected", rejected
    assert rejected["reason"] == "budget_floor", rejected
    assert run_row(st, "u-a")[0] == "stopped"


def test_a_segment_cap_alone_is_the_reservation(st: Store, project: Path) -> None:
    set_switch(project, "off")
    registered(st, project, "u-a", omit=("run",), caps={"segment": 40.0})
    admitted = admit(st, "u-a", 1, now=10)
    assert admitted["reservation_usd"] == 40.0 and admitted["uncapped"] is False


# --- (c) the switch at each admission ----------------------------------------------------


@pytest.mark.parametrize("switch", ["on", None])
def test_a_first_start_fails_when_caps_are_required_again(
    st: Store, project: Path, switch: str | None
) -> None:
    set_switch(project, "off")
    registered(st, project, "u-a", omit=("run",))
    set_switch(project, switch)
    rejected = admit(st, "u-a", 1, now=10)
    assert rejected["outcome"] == "rejected" and rejected["reason"] == "caps_required"
    assert run_row(st, "u-a")[0] == "failed"
    assert "start_refused" in notices(st, "u-a")
    check_ok(st)


def test_a_resume_stays_stopped_when_caps_are_required_again(
    st: Store, project: Path
) -> None:
    set_switch(project, "off")
    spent_run(st, project, "u-a", 3.0, omit=ALL_CAPS)
    set_switch(project, "on")
    rejected = admit(st, "u-a", 2, now=130, resume=True)
    assert rejected["outcome"] == "rejected" and rejected["reason"] == "caps_required"
    assert run_row(st, "u-a")[0] == "stopped"
    assert "resume_refused" in notices(st, "u-a")


def test_a_malformed_file_at_admission_is_review_limits_invalid(
    st: Store, project: Path
) -> None:
    set_switch(project, "off")
    registered(st, project, "u-a", omit=("segment",))
    break_switch(project)
    rejected = admit(st, "u-a", 1, now=10)
    assert rejected["reason"] == "review_limits_invalid", rejected
    assert run_row(st, "u-a")[0] == "failed"


def test_an_omitted_chain_cap_also_reads_the_switch(st: Store, project: Path) -> None:
    set_switch(project, "off")
    registered(st, project, "u-a", omit=("chain",), chain=True)
    set_switch(project, "on")
    assert admit(st, "u-a", 1, now=10)["reason"] == "caps_required"


@pytest.mark.parametrize("state", ["on", "absent", "malformed"])
def test_a_capped_run_is_admitted_whatever_the_file_says(
    st: Store, project: Path, state: str
) -> None:
    registered(st, project, "u-a", chain=True)
    if state == "on":
        set_switch(project, "on")
    elif state == "malformed":
        break_switch(project)
    admitted = admit(st, "u-a", 1, now=10)
    assert admitted["outcome"] == "admitted" and admitted["reservation_usd"] == 10.0


# --- (d) exposure ------------------------------------------------------------------------


def test_an_uncapped_segment_without_a_cost_exposes_nothing(
    st: Store, project: Path
) -> None:
    set_switch(project, "off")
    registered(st, project, "u-a", omit=ALL_CAPS)
    seg = start_segment(st, "u-a", 1, now=10)
    finish(st, seg, now=100, total=None)
    assert st.rows("SELECT exposed_usd, amount_usd FROM exposures") == [(0.0, 0.0)]
    assert st.one("SELECT cost_known FROM segments") == 0
    spend = st.ok("spend", "--run-id", "u-a", now=120, expect=("ok",))
    assert spend["run_cap_usd"] is None, spend
    check_ok(st)


def test_a_capped_segment_still_exposes_its_reservation(
    st: Store, project: Path
) -> None:
    registered(st, project, "u-a")
    seg = start_segment(st, "u-a", 1, now=10)
    finish(st, seg, now=100, total=None)
    assert st.rows("SELECT exposed_usd FROM exposures") == [(75.0,)]


# --- (e) chains --------------------------------------------------------------------------


def candidates(st: Store) -> dict[str, dict[str, Any]]:
    payload = st.ok("chain_candidates", now=200, expect=("ok",))
    return {c["run_id"]: c for c in payload["candidates"]}


def test_an_uncapped_chain_is_ready_after_any_spend(st: Store, project: Path) -> None:
    set_switch(project, "off")
    spent_run(st, project, "u-a", 1_000_000.0, omit=ALL_CAPS, chain=True)
    registered(st, project, "u-b", omit=ALL_CAPS, chain=True)
    found = candidates(st)["u-b"]
    assert found["holds"] is True and found["error"] is None, found
    assert found["chain_room_usd"] is None and found["ready"] is True, found


def test_a_chain_cannot_mix_capped_and_uncapped_blocks(
    st: Store, project: Path
) -> None:
    set_switch(project, "off")
    registered(st, project, "u-a", omit=("chain",), chain=True)
    out = register(st, project, "u-b", chain=True)
    assert out.code == EXIT_REFUSED and out.error == "chain_conflict", out.show()


def test_a_capped_chain_below_the_floor_is_not_ready(st: Store, project: Path) -> None:
    spent_run(st, project, "u-a", 6.0, chain=True)
    registered(st, project, "u-b", chain=True)
    found = candidates(st)["u-b"]
    assert found["holds"] is True and found["chain_room_usd"] == 4.0, found
    assert found["chain_room_usd"] < FLOOR_USD and found["ready"] is False, found
