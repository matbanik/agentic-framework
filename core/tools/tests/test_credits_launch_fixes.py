"""MEU-895 credits-headless-brief-authority: the launch fixes of the store and the tree check.

Plan: docs/execution/plans/2026-11-05-pe21-credits-authority (MEU-895 Design 5, 6, 10;
PE21-D11, D12, D16). The unit parts of:

* AC-895.6: ``cost_reconcile --segment-id --transcript --registry`` sets the information-only
  estimate of a killed segment. The exposure stays open at the full reservation.
* AC-895.7: ``complete_segment --class launch_failed --cli-start absent|present``.
* AC-895.11: ``tree`` and ``tree_continue`` on the main tree after a recorded removal.
* AC-895.12: ``authority`` is read-only.

Store calls are real ``credits_state.py`` subprocesses and tree calls are real
``credits_msg.py`` subprocesses, on temp stores and a real fixture git repository.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from test_credits_phases import RUN as PHASE_RUN
from test_credits_phases import _build, _drive, _init, _rp
from test_credits_authority import agent, authority, read_only
from test_credits_msg import CONFIG_DEFAULTS, MSG_TOOL
from test_credits_state import (
    ROOT,
    SESSION_B,
    Out,
    Seg,
    Store,
    accept_args,
    at,
    child_env,
    finish,
    first_start,
    held_lanes,
    launched_args,
    make_registered,
    parse_out,
    register_args,
    run_state,
    spend,
    start_segment,
    start_transcript_uuid,
    stop,
    transitions,
)

RUN = "run-launch"
FX_ROOT = "X:/fixture-project"
SKILL = ROOT / ".agent" / "skills" / "claude-credits"
GET_RUN = SKILL / "Get-CreditsRun.ps1"
# The form of ``$AGENT_MODEL_REGISTRY_HOME/model-registry.yaml``: ``catalog.<slug>.price_per_mtok``. It has no
# ``models`` key, so an implementation that reads ``models`` finds no price.
REGISTRY = {
    "schema_version": 1,
    "catalog": {"fixture-model": {"price_per_mtok": {"in": 3.0, "out": 15.0}}},
}


@pytest.fixture
def st(tmp_path: Path) -> Store:
    store = Store(tmp_path / "store")
    store.root.mkdir()
    store.init()
    return store


def _registry(tmp_path: Path) -> Path:
    path = tmp_path / "model-registry.yaml"
    # JSON is YAML: a YAML reader of the registry can read this fixture.
    path.write_text(json.dumps(REGISTRY), encoding="utf-8", newline="\n")
    return path


def _usage_record(
    message_id: str, stamp: str, usage: dict[str, Any], session: str
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "sessionId": session,
        "uuid": start_transcript_uuid(f"{message_id}|{stamp}"),
        "timestamp": stamp,
        "message": {"id": message_id, "role": "assistant", "usage": usage},
    }


def _iso_ms(seconds: int) -> str:
    """The transcript form of the store clock value ``at(seconds)``."""
    return at(seconds).replace("Z", ".000Z")


def _transcript(tmp_path: Path, session: str) -> Path:
    """Records of one segment that ``launched`` at ``at(8)``; the estimate is USD 0.0645.

    In 3, out 15, so 5m 3.75, 1h 6 and read 0.3 per MTok. Counted: ``msg_3`` (at the start),
    ``msg_1`` once and ``msg_2``. In 1600, out 2100, 5m 4000, 1h 2000, read 4000.
    """
    records = [
        # Before the segment's start: a record of an earlier segment of the session.
        _usage_record(
            "msg_0",
            _iso_ms(2),
            {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
            session,
        ),
        _usage_record("msg_3", _iso_ms(8), {"input_tokens": 100}, session),
        _usage_record(
            "msg_1",
            _iso_ms(10),
            {
                "input_tokens": 1000,
                "output_tokens": 2000,
                "cache_creation_input_tokens": 3000,
                "cache_read_input_tokens": 4000,
            },
            session,
        ),
        # The same ``message.id`` a second time: counted once.
        _usage_record(
            "msg_1",
            _iso_ms(20),
            {
                "input_tokens": 1000,
                "output_tokens": 2000,
                "cache_creation_input_tokens": 3000,
                "cache_read_input_tokens": 4000,
            },
            session,
        ),
        {
            "type": "user",
            "sessionId": session,
            "uuid": start_transcript_uuid("user-record"),
            "timestamp": _iso_ms(25),
            "message": {"role": "user", "content": "fixture text"},
        },
        _usage_record(
            "msg_2",
            _iso_ms(30),
            {
                "input_tokens": 500,
                "output_tokens": 100,
                "cache_creation_input_tokens": 3000,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 1000,
                    "ephemeral_1h_input_tokens": 2000,
                },
            },
            session,
        ),
    ]
    path = tmp_path / "segment-transcript.jsonl"
    text = "".join(json.dumps(record) + "\n" for record in records)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _reconcile(
    st: Store, seg: Seg, transcript: Path, registry: Path, *, now: int
) -> Out:
    return st.cli(
        "cost_reconcile",
        "--segment-id",
        seg.segment_id,
        "--transcript",
        str(transcript),
        "--registry",
        str(registry),
        now=now,
    )


def _exposures(st: Store, seg: Seg) -> list[tuple[Any, ...]]:
    return st.rows(
        "SELECT state, amount_usd FROM exposures WHERE segment_id = ?",
        (seg.segment_id,),
    )


def _killed(st: Store, tmp_path: Path) -> tuple[Seg, Path, Path]:
    """A segment that ended with no trusted total, plus its transcript and the registry."""
    seg = first_start(st, RUN)
    finish(st, seg, now=40, cls="exited")
    assert _exposures(st, seg) == [("open", 75.0)]
    return seg, _transcript(tmp_path, seg.session), _registry(tmp_path)


def test_ac_895_6_estimate_counts_each_message_of_the_segment_once(
    st: Store, tmp_path: Path
) -> None:
    """AC-895.6: each ``message.id`` once; a record before the start is not counted."""
    seg, transcript, registry = _killed(st, tmp_path)
    out = _reconcile(st, seg, transcript, registry, now=45)
    assert out.code == 0, out.show()
    found = st.rows(
        "SELECT cost_estimate_usd, cost_estimate_source FROM segments WHERE segment_id = ?",
        (seg.segment_id,),
    )
    assert len(found) == 1
    assert found[0][0] == pytest.approx(0.0645)
    assert found[0][1] == "transcript"


def test_ac_895_6_estimate_never_moves_the_exposure_or_the_cap_check(
    st: Store, tmp_path: Path
) -> None:
    """AC-895.6: information only. The exposure, ``cost_known`` and the spend stay as they were."""
    seg, transcript, registry = _killed(st, tmp_path)
    before = spend(st, RUN, 44)
    out = _reconcile(st, seg, transcript, registry, now=45)
    assert out.code == 0, out.show()
    assert _exposures(st, seg) == [("open", 75.0)]
    assert (
        st.one(
            "SELECT cost_known FROM segments WHERE segment_id = ?", (seg.segment_id,)
        )
        == 0
    )
    assert spend(st, RUN, 44) == before


def test_ac_895_6_no_transcript_files_cost_unknown_once(
    st: Store, tmp_path: Path
) -> None:
    """AC-895.6: no transcript gives the notice once and no estimate."""
    seg = first_start(st, RUN)
    finish(st, seg, now=40, cls="exited")
    registry = _registry(tmp_path)
    missing = tmp_path / "no-such-transcript.jsonl"
    for now in (45, 46):
        out = _reconcile(st, seg, missing, registry, now=now)
        assert out.code == 0, out.show()
    keys = st.rows("SELECT notice_key FROM notices WHERE kind = 'cost_unknown'")
    assert keys == [(f"cost_unknown:{seg.segment_id}",)]
    assert st.rows(
        "SELECT cost_estimate_usd, cost_estimate_source FROM segments WHERE segment_id = ?",
        (seg.segment_id,),
    ) == [(None, None)]
    assert _exposures(st, seg) == [("open", 75.0)]


def test_ac_895_6_get_credits_run_shows_the_estimate(st: Store, tmp_path: Path) -> None:
    """AC-895.6 (Files Modified): the check command shows the estimate and the new facts."""
    make_registered(st, RUN)
    seg = start_segment(st, RUN, 1, now=1, launch=False)
    policy = "a" * 64
    st.ok(
        "launched",
        *launched_args(seg.segment_id, 8),
        "--policy-sha256",
        policy,
        now=8,
    )
    finish(st, seg, now=40, cls="exited")
    out = _reconcile(
        st, seg, _transcript(tmp_path, seg.session), _registry(tmp_path), now=45
    )
    assert out.code == 0, out.show()

    pwsh = shutil.which("pwsh")
    assert pwsh is not None, "pwsh is required for this check"
    proc = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(GET_RUN),
            RUN,
            "-StateDb",
            str(st.db),
            "-OutputDir",
            str(tmp_path / "dispatch"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(st.env()),
        timeout=180,
        cwd=ROOT,
        check=False,
    )
    shown = proc.stdout + proc.stderr
    assert proc.returncode == 0, shown[-1500:]
    estimates = [line for line in shown.splitlines() if "estimate" in line.lower()]
    assert any("0.06" in line for line in estimates), shown[-1500:]
    assert re.search(r"(?i)source[_ ]check", shown), shown[-1500:]
    assert re.search(r"(?i)policy[_ ]sha256", shown), shown[-1500:]
    assert policy[:16] in shown, shown[-1500:]


# --- AC-895.7 ---------------------------------------------------------------------------


def _complete(
    st: Store, seg: Seg, cli_start: str, *, now: int, cls: str = "launch_failed"
) -> Out:
    return st.cli(
        "complete_segment",
        "--segment-id",
        seg.segment_id,
        "--finalized-by",
        "launcher",
        "--class",
        cls,
        "--cli-start",
        cli_start,
        now=now,
    )


def _messages(st: Store, label: str, text: str) -> tuple[str, str]:
    """A typed start message of ``text``: the session uuid and the message uuid."""
    session = start_transcript_uuid(f"{label}-session")
    message = start_transcript_uuid(f"{label}-message")
    st.start_transcript_record(FX_ROOT, session, message, text)
    return session, message


def _request_words(session: str, message: str, text: str) -> tuple[str, ...]:
    return (*agent(text), "--start-session", session, "--start-message", message)


def _launch_agent(
    st: Store, run_id: str, n: int, words: tuple[str, ...], *, now: int
) -> Seg:
    """Request ``n`` with named start words, then accept, admit and launch it."""
    request_id = f"req-{run_id}-{n}"
    st.ok("request", "--run-id", run_id, "--request-id", request_id, *words, now=now)
    st.ok("accept", *accept_args(run_id, n, SESSION_B), now=now + 5)
    segment_id = f"seg-{run_id}-{n}"
    st.ok(
        "admit",
        "--attempt-id",
        f"att-{run_id}-{n}",
        "--segment-id",
        segment_id,
        now=now + 6,
    )
    st.ok("launched", *launched_args(segment_id, now + 7), now=now + 7)
    return Seg(run_id, request_id, f"att-{run_id}-{n}", segment_id, SESSION_B)


def test_ac_895_7_unstarted_releases_the_exposure_and_restores_the_run(
    st: Store,
) -> None:
    """AC-895.7: a ``running`` segment with no CLI: released at 0, the run back, the lane free."""
    seg = first_start(st, RUN)
    previous = st.one(
        "SELECT previous_state FROM requests WHERE request_id = ?", (seg.request_id,)
    )
    assert previous == "registered"
    out = _complete(st, seg, "absent", now=20)
    assert out.code == 0, out.show()
    assert _exposures(st, seg) == [("released", 0.0)]
    request = st.rows(
        "SELECT state, message_released_utc FROM requests WHERE request_id = ?",
        (seg.request_id,),
    )
    assert request == [("launch_failed", at(20))]
    assert run_state(st, RUN) == previous
    assert held_lanes(st) == 0


def test_ac_895_7_an_unstarted_resume_returns_to_stopped(st: Store) -> None:
    """AC-895.7: the run goes back to ``previous_state``, here ``stopped``; the old spend stays."""
    first = first_start(st, RUN)
    finish(st, first, now=20, total=1.0)
    stop(st, RUN, now=21)
    seg = start_segment(st, RUN, 2, now=30, session=SESSION_B, resume=True)
    assert (
        st.one(
            "SELECT previous_state FROM requests WHERE request_id = ?",
            (seg.request_id,),
        )
        == "stopped"
    )
    out = _complete(st, seg, "absent", now=40)
    assert out.code == 0, out.show()
    assert run_state(st, RUN) == "stopped"
    assert _exposures(st, seg) == [("released", 0.0)]
    assert _exposures(st, first) == []
    assert held_lanes(st) == 0


def test_ac_895_7_unstarted_writes_its_event(st: Store) -> None:
    """AC-895.7: the event ``launch_failed_unstarted``, in the outbox or as a transition."""
    seg = first_start(st, RUN)
    out = _complete(st, seg, "absent", now=20)
    assert out.code == 0, out.show()
    verbs = {str(row[2]) for row in transitions(st, "segment", seg.segment_id)}
    verbs |= {str(row[1]) for row in transitions(st, "segment", seg.segment_id)}
    verbs |= {str(row[2]) for row in transitions(st, "run", RUN)}
    verbs |= {str(row[1]) for row in transitions(st, "run", RUN)}
    kinds = {str(row[0]) for row in st.rows("SELECT kind FROM outbox_events")}
    assert "launch_failed_unstarted" in verbs | kinds, out.show()


def test_ac_895_7_a_retry_with_the_same_message_is_accepted(st: Store) -> None:
    """AC-895.7: after ``absent`` the same typed words start the retry (AC-894.2)."""
    make_registered(st, RUN)
    text = "start run-launch"
    session, message = _messages(st, "retry", text)
    words = _request_words(session, message, text)
    seg = _launch_agent(st, RUN, 1, words, now=1)
    out = _complete(st, seg, "absent", now=20)
    assert out.code == 0, out.show()

    retry = st.cli(
        "request", "--run-id", RUN, "--request-id", f"req-{RUN}-2", *words, now=30
    )
    assert retry.code == 0, retry.show()
    accepted = st.ok("accept", *accept_args(RUN, 2, SESSION_B), now=35)
    assert accepted.get("outcome") == "accepted", accepted


def test_ac_895_7_present_keeps_the_open_exposure_and_the_message(st: Store) -> None:
    """AC-895.7 negative: ``present`` keeps today's path: a retry is refused ``start_message_reused``."""
    make_registered(st, RUN)
    text = "start run-launch"
    session, message = _messages(st, "present", text)
    words = _request_words(session, message, text)
    seg = _launch_agent(st, RUN, 1, words, now=1)
    out = _complete(st, seg, "present", now=20)
    assert out.code == 0, out.show()
    assert _exposures(st, seg) == [("open", 75.0)]
    assert (
        st.one(
            "SELECT message_released_utc FROM requests WHERE request_id = ?",
            (seg.request_id,),
        )
        is None
    )
    assert run_state(st, RUN) in ("finalizing", "stopped")

    if run_state(st, RUN) != "stopped":
        stop(st, RUN, now=21)
    retry = st.cli(
        "request",
        "--run-id",
        RUN,
        "--request-id",
        f"req-{RUN}-2",
        *words,
        "--resume",
        "--resume-mode",
        "fresh",
        "--brief",
        str(_brief(st)),
        now=30,
    )
    assert retry.code == 3 and retry.error == "start_message_reused", retry.show()


def _brief(st: Store) -> Path:
    path = st.root / "resume-brief.md"
    path.write_text("# resume brief\n", encoding="utf-8", newline="\n")
    return path


@pytest.mark.parametrize("cli_start", ["absent", "present"])
def test_ac_895_7_cli_start_needs_class_launch_failed(
    st: Store, cli_start: str
) -> None:
    """AC-895.7 negative: ``--cli-start`` with class ``exited`` is refused; nothing changes."""
    seg = first_start(st, RUN)
    out = _complete(st, seg, cli_start, now=20, cls="exited")
    assert out.code == 3 and out.error == "cli_start_class", out.show()
    assert (
        st.one("SELECT state FROM segments WHERE segment_id = ?", (seg.segment_id,))
        == "running"
    )
    assert run_state(st, RUN) == "running"


def test_ac_895_7_launcher_and_wrapper_carry_the_marker() -> None:
    """AC-895.7 (Design 6): ICC writes the marker; the launcher reads it and passes ``--cli-start``.

    The store accepts the flag in MEU-894 (AC-894.2). The launcher's use of it is MEU-895, and
    the real path is in ``tools/tests/CreditsPolicyInject.Tests.ps1``. The launcher's store calls
    can be in SRUN or in its module, so this check reads the two files as one text.
    """
    wrapper = (SKILL / "Invoke-ClaudeCredits.ps1").read_text(encoding="utf-8")
    launcher = "\n".join(
        (SKILL / name).read_text(encoding="utf-8")
        for name in ("Start-CreditsRun.ps1", "CreditsRun.psm1")
    )
    assert "cli-start.json" in wrapper
    assert "cli-start.json" in launcher
    assert "--cli-start" in launcher


# --- AC-895.11 --------------------------------------------------------------------------


def _msg(
    st: Store,
    fx: bf.Fixture,
    run_id: str,
    segment_id: str,
    config: Path,
    verb: str,
    *args: str,
    now: int,
    base: str,
) -> Out:
    """One ``credits_msg.py`` call with the launcher's environment over the repo's own."""
    env = {
        **fx.env(),
        **st.env(
            {
                "CREDITS_RUN_ID": run_id,
                "CREDITS_SEGMENT": segment_id,
                "CREDITS_STATE_DB": str(st.db),
                "CREDITS_CONFIG": str(config),
                "CREDITS_BASE_COMMIT": base,
            }
        ),
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(MSG_TOOL),
            "--now-utc",
            at(now),
            verb,
            *args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(env),
        timeout=120,
        cwd=ROOT,
        check=False,
    )
    return parse_out(proc.returncode, proc.stdout, proc.stderr)


def _removal(fx: bf.Fixture, run_id: str) -> None:
    """The two removal records of H2-3c, in the form of the phases tests."""
    rp = _rp()
    with bf.patched_environ(fx.env()):
        for event in ("worktree_removal_started", "worktree_removed"):
            rp.record_removal(
                fx.repo,
                plan=fx.plan,
                run_id=run_id,
                event=event,
                path="{{PROJECT_ROOT}}-wt/fixture-run",
                manifest_digest="c" * 64,
                by="executor_worktree.py remove",
                row="H2-3c",
            )


def _tree_run(st: Store, fx: bf.Fixture) -> tuple[Seg, Path, str]:
    """A running segment of an executor-worktree run that sits on the main tree."""
    args = register_args(st, PHASE_RUN)
    manifest = Path(args[args.index("--manifest") + 1])
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["project_root"] = str(fx.repo)
    doc["launch"]["working_directory"] = str(fx.repo)
    doc["plan_folder"] = f"docs/execution/plans/{fx.plan}/"
    doc["executor_worktree"] = True
    manifest.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    st.ok("register", *args, now=0)
    st.ok("registered", "--run-id", PHASE_RUN, "--task-hash", "taskhash-tree", now=0)
    seg = start_segment(st, PHASE_RUN, 1, now=1)
    config = st.root / "config.json"
    config.write_text(json.dumps(CONFIG_DEFAULTS), encoding="utf-8")
    return seg, config, bf.git(fx.repo, "rev-parse", "HEAD")


def _phase_fixture(tmp_path: Path) -> bf.Fixture:
    fx = _build(tmp_path)
    _init(fx)
    _drive(fx, "exec:active")
    return fx


def test_ac_895_11_tree_after_a_recorded_removal_is_the_main_tree(
    st: Store, tmp_path: Path
) -> None:
    """AC-895.11: ``tree``, then ``tree_continue``, give ``main_after_removal``."""
    fx = _phase_fixture(tmp_path)
    _removal(fx, PHASE_RUN)
    seg, config, head = _tree_run(st, fx)
    first = _msg(
        st,
        fx,
        PHASE_RUN,
        seg.segment_id,
        config,
        "tree",
        str(fx.repo),
        now=20,
        base=head,
    )
    assert first.code == 0, first.show()
    assert first.payload is not None
    assert first.payload.get("tree_kind") == "main_after_removal", first.show()
    # The first call fixed B and pinned S, so this call takes the tree_continue path.
    assert st.one("SELECT base_fixed FROM runs WHERE run_id = ?", (PHASE_RUN,)) == 1, (
        first.show()
    )
    second = _msg(
        st,
        fx,
        PHASE_RUN,
        seg.segment_id,
        config,
        "tree",
        str(fx.repo),
        now=30,
        base=head,
    )
    assert second.code == 0, second.show()
    assert second.payload is not None
    assert second.payload.get("tree_kind") == "main_after_removal", second.show()


def test_ac_895_11_no_removal_record_is_worktree_required(
    st: Store, tmp_path: Path
) -> None:
    """AC-895.11: with no removal record the refusal stays."""
    fx = _phase_fixture(tmp_path)
    seg, config, head = _tree_run(st, fx)
    out = _msg(
        st,
        fx,
        PHASE_RUN,
        seg.segment_id,
        config,
        "tree",
        str(fx.repo),
        now=20,
        base=head,
    )
    assert out.code == 3 and out.error == "worktree_required", out.show()


def test_ac_895_11_a_removal_of_another_run_does_not_count(
    st: Store, tmp_path: Path
) -> None:
    """AC-895.11 negative: the record must be of THIS run."""
    fx = _phase_fixture(tmp_path)
    other = "run-fixture-2"
    _drive(fx, "exec:active", run_id=other)
    _removal(fx, other)
    seg, config, head = _tree_run(st, fx)
    out = _msg(
        st,
        fx,
        PHASE_RUN,
        seg.segment_id,
        config,
        "tree",
        str(fx.repo),
        now=20,
        base=head,
    )
    assert out.code == 3 and out.error == "worktree_required", out.show()


# --- AC-895.12 --------------------------------------------------------------------------


def test_ac_895_12_authority_is_read_only(st: Store) -> None:
    """AC-895.12: two runs give the same output and the store bytes do not change."""
    seg = first_start(st, RUN)
    first = read_only(st, lambda: authority(st, RUN, seg.segment_id))
    second = read_only(st, lambda: authority(st, RUN, seg.segment_id))
    assert first.code == 0, first.show()
    assert (second.code, second.stdout) == (first.code, first.stdout)
