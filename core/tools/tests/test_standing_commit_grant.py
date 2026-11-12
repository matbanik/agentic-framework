"""MEU-939 tests for the standing commit grant (AC-939.1, AC-939.2, AC-939.3, AC-939.6).

Plan: docs/execution/plans/2026-11-07-standing-commit-grant (D-1 A: one typed grant that
covers commits of the agent's own work until it is revoked; a manual plan opts out).

The contract these tests fix (see ``{{RECEIPTS_DIR}}/standing-grant/interfaces.md``):

* ``python -m tools.run_parameters --repo R standing --session <s> --message-uuid <u>`` reads
  the typed human record and writes ``grants/<u>.json`` of form ``standing-commit`` in the
  existing store envelope. Success exits 0 and reports ``standing_ok`` with the uuid (one JSON
  object with ``result: standing_ok`` and ``message_uuid``, or the line ``standing_ok <uuid>``).
  A refusal exits 1 with reason ``consent`` and detail ``not_user``, ``not_a_standing_grant`` or
  ``standing_manual``, and writes no grant file.
* ``tools.run_parameters.standing_authority(repo, plan, act)`` returns the live standing
  envelope (a dict) or None, and raises ``Refusal("standing_opt_out", "manual" | "commit_exec" |
  "commit_plan")`` for a plan that opts out.
* The ``commit_batch`` grant route (``--phase exec --op <id> --packet <f>``) commits under the
  standing grant when the plan has no grant of its own; it records ``consumed[<plan>][<act>]``
  in the standing envelope. A planless packet (``plan: none``) is recorded in the op tree
  ``ops/planless/<packet digest>/`` and never in ``consumed``.

Every fixture is built inside the test body, so a missing name fails at Red rather than erroring
at collection. The commit tests run the real driver against a real fixture repository, as
``tools/tests/test_commit_batch.py`` does.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "/standing-commit-grant"
MENTION = "@.agent/workflows/standing-commit-grant.md"
LEGACY = "2026-11-01-legacy-plan"
ENVELOPE_KEYS = {
    "message_uuid",
    "offer",
    "offer_digest",
    "chain",
    "consumed",
    "superseded_by",
}
STANDING_SCOPE = {"plan": "none", "grouping": "none", "branch": "main"}
STANDING_GRANTS = ["exec_commit", "finalize", "plan_commit"]


# -- helpers ---------------------------------------------------------------------------------


def _rp() -> ModuleType:
    return importlib.import_module("tools.run_parameters")


def _rig(tmp_path: Path) -> b3.Rig:
    return b3.rig(tmp_path / "fx", ROOT)


def _run_rp(fx: bf.Fixture, *argv: str) -> tuple[int, str, str]:
    """``tools.run_parameters.main`` in-process: (exit, stdout, stderr)."""
    rp = _rp()
    out, err = io.StringIO(), io.StringIO()
    with (
        bf.patched_environ(fx.env()),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        try:
            code = rp.main(["--repo", str(fx.repo), *argv])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
    return int(code), out.getvalue(), err.getvalue()


def _json_lines(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def _says_standing_ok(stdout: str, uid: str) -> bool:
    """The ``standing_ok <uuid>`` report, as a plain line or as the one JSON object."""
    if any(line.strip() == f"standing_ok {uid}" for line in stdout.splitlines()):
        return True
    return any(
        item.get("result") == "standing_ok" and item.get("message_uuid") == uid
        for item in _json_lines(stdout)
    )


def _standing(fx: bf.Fixture, uid: str) -> tuple[int, str, str]:
    return _run_rp(fx, "standing", "--session", fx.session, "--message-uuid", uid)


def _grant(fx: bf.Fixture, text: str = TOKEN) -> str:
    """Record a standing grant from a typed record; return its uuid."""
    uid = fx.add_human(text)
    code, out, err = _standing(fx, uid)
    assert code == 0 and _says_standing_ok(out, uid), (code, out, err)
    return uid


def _rp_refusal(res: tuple[int, str, str]) -> tuple[str, str]:
    """The (reason, detail) of a refused ``run_parameters`` verb (stdout reason, stderr detail)."""
    code, out, err = res
    assert code == 1, (code, out, err)
    emitted = _json_lines(out)
    assert emitted and emitted[-1].get("result") == "refused", (out, err)
    logged = [item for item in _json_lines(err) if item.get("event") == "refused"]
    assert logged, err
    assert logged[-1]["reason"] == emitted[-1]["reason"], (out, err)
    return str(logged[-1]["reason"]), str(logged[-1]["detail"])


def _commit_refusal(res: b3.Result) -> tuple[str, str]:
    """The (reason, detail) of a refused ``commit_batch`` run."""
    code, out, text = res
    assert (code, out.get("result")) == (1, "refused"), text
    logged = [
        item for item in _json_lines(text) if item.get("event") == "commit_refused"
    ]
    assert logged, text
    assert logged[-1]["reason"] == out["reason"], text
    return str(logged[-1]["reason"]), str(logged[-1]["detail"])


def _reconciled(res: b3.Result) -> dict[str, Any]:
    code, out, text = res
    assert (code, out.get("result")) == (0, "reconciled"), text
    return out


def _grant_path(fx: bf.Fixture, uid: str) -> Path:
    return fx.store / "grants" / f"{uid}.json"


def _envelope(fx: bf.Fixture, uid: str) -> dict[str, Any]:
    data = json.loads(_grant_path(fx, uid).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _repo(fx: bf.Fixture) -> Any:
    rp = _rp()
    with bf.patched_environ(fx.env()):
        return rp._open_repo(fx.repo)


def _authority(fx: bf.Fixture, plan: str, act: str) -> dict[str, Any] | None:
    rp = _rp()
    with bf.patched_environ(fx.env()):
        repo = rp._open_repo(fx.repo)
        return rp.standing_authority(repo, plan, act)


def _opt_out(fx: bf.Fixture, plan: str, act: str) -> str:
    rp = _rp()
    with bf.patched_environ(fx.env()):
        repo = rp._open_repo(fx.repo)
        with pytest.raises(rp.Refusal) as info:
            rp.standing_authority(repo, plan, act)
    assert info.value.reason == "standing_opt_out", info.value
    return str(info.value.detail)


def _legacy_plan(rig: b3.Rig, plan: str = LEGACY) -> None:
    """A plan folder whose ``task.md`` has no frontmatter and so no ``run_parameters`` block."""
    rig.fx.write_text(
        f"docs/execution/plans/{plan}/task.md",
        f"# Task: {plan}\n\n| # | Task | Status |\n| :- | :- | :- |\n| 0 | row | [ ] |\n",
    )
    rig.fx.write_text(
        f"docs/execution/plans/{plan}/implementation-plan.md", f"# Plan: {plan}\n"
    )
    rig.fx.commit("fixture: a legacy plan")


def _manual_plan(rig: b3.Rig) -> None:
    """Rewrite the rig's plan as a manual plan (``authorization: {schema: manual}``)."""
    rig.fx.write_carrier({**rig.fx.block, "authorization": {"schema": "manual"}})
    rig.fx.commit("fixture: a manual plan")


def _tightened_plan(rig: b3.Rig, key: str) -> None:
    """Rewrite the rig's plan with ``<key>: false`` as a recorded tightening."""
    tight = {**rig.fx.block, key: False, "tightened_from": "grouping"}
    rig.fx.write_carrier(tight, task_block=tight, grouping_values=rig.fx.block)
    rig.fx.commit(f"fixture: {key} false")


def _digest(packet: dict[str, Any]) -> str:
    """The packet digest: sha256 hex of its canonical JSON (``commit_batch._packet_digest``)."""
    data = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("ascii")).hexdigest()


# -- AC-939.1: the grant record ---------------------------------------------------------------


def test_ac_939_1_standing_verb_writes_one_standing_commit_grant(
    tmp_path: Path,
) -> None:
    """AC-939.1: ``standing`` writes one ``standing-commit`` grant in the existing envelope."""
    rig = _rig(tmp_path)
    fx = rig.fx
    uid = _grant(fx)
    envelope = _envelope(fx, uid)
    assert set(envelope) == ENVELOPE_KEYS
    assert envelope["message_uuid"] == uid
    assert envelope["chain"] == [uid]
    assert envelope["consumed"] == {}
    assert envelope["superseded_by"] in (None, "none")
    digest = str(envelope["offer_digest"])
    assert digest.startswith("sha256:") and len(digest) == len("sha256:") + 64
    offer = envelope["offer"]
    assert offer["form"] == "standing-commit"
    assert offer["source"] == "USER_EXPLICIT"
    assert offer["session"] == fx.session
    assert offer["message_uuid"] == uid
    assert offer["presentation_uuid"] == uid
    assert offer["response"] == TOKEN
    assert offer["scope"] == STANDING_SCOPE
    assert offer["members"] == []
    assert offer["expires"] == "none"
    assert offer["grants"] == STANDING_GRANTS
    assert "exec_start" not in offer["grants"]
    assert offer["standing"] is True
    assert offer["supersedes"] == "none"


def test_ac_939_1_load_store_reads_the_grant_back(tmp_path: Path) -> None:
    """AC-939.1: ``_load_store`` reads the standing grant back with no ``store_malformed``."""
    rig = _rig(tmp_path)
    _grant(rig.fx)
    rp = _rp()
    with bf.patched_environ(rig.fx.env()):
        rp._load_store(rp._open_repo(rig.fx.repo))
    code, out = rig.fx.run("status")
    assert code == 0, out


def test_ac_939_1_token_on_a_later_prose_line_and_the_mention_form(
    tmp_path: Path,
) -> None:
    """AC-939.1: the token on a later prose line, and the workflow mention, record the grant."""
    rig = _rig(tmp_path)
    first = _grant(rig.fx, f"Thanks, the build has landed.\n{TOKEN}")
    second = _grant(rig.fx, f"{MENTION} for my own work")
    assert _envelope(rig.fx, first)["offer"]["form"] == "standing-commit"
    assert _envelope(rig.fx, second)["offer"]["form"] == "standing-commit"


def test_ac_939_1_a_second_record_supersedes_the_first(tmp_path: Path) -> None:
    """AC-939.1: a second grant supersedes the live one in both envelopes."""
    rig = _rig(tmp_path)
    old = _grant(rig.fx)
    new = _grant(rig.fx)
    assert _envelope(rig.fx, new)["offer"]["supersedes"] == old
    assert _envelope(rig.fx, old)["superseded_by"] == new
    live = _authority(rig.fx, LEGACY, "exec_commit")
    assert live is not None and live["message_uuid"] == new


def test_ac_939_1_assistant_record_refuses_not_user(tmp_path: Path) -> None:
    """AC-939.1: a record from the assistant refuses ``consent:not_user`` and writes nothing."""
    rig = _rig(tmp_path)
    uid = rig.fx.add_assistant(TOKEN)
    assert _rp_refusal(_standing(rig.fx, uid)) == ("consent", "not_user")
    assert not _grant_path(rig.fx, uid).exists()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("please commit my work from now on", id="no-token"),
        pytest.param(
            f"Here is the form:\n```\n{TOKEN}\n```\nnot yet", id="fenced-only"
        ),
        pytest.param(f"You wrote:\n> {TOKEN}\nnot yet", id="quoted-only"),
    ],
)
def test_ac_939_1_record_without_a_prose_token_refuses(
    tmp_path: Path, text: str
) -> None:
    """AC-939.1: no token, or the token only in a fence or on a ``>`` line, refuses ``not_a_standing_grant``."""
    rig = _rig(tmp_path)
    uid = rig.fx.add_human(text)
    assert _rp_refusal(_standing(rig.fx, uid)) == ("consent", "not_a_standing_grant")
    assert not _grant_path(rig.fx, uid).exists()


def test_ac_939_1_manual_record_refuses_standing_manual(tmp_path: Path) -> None:
    """AC-939.1: a record that holds ``run_parameters: manual`` refuses ``standing_manual``."""
    rig = _rig(tmp_path)
    uid = rig.fx.add_human(f"{TOKEN}\nrun_parameters: manual")
    assert _rp_refusal(_standing(rig.fx, uid)) == ("consent", "standing_manual")
    assert not _grant_path(rig.fx, uid).exists()


def test_ac_939_1_grant_route_reserves_consumed_plan_act(tmp_path: Path) -> None:
    """AC-939.1: a standing commit records ``consumed[<plan>][<act>]``; a second op refuses ``consumed``."""
    rig = _rig(tmp_path)
    _legacy_plan(rig)
    uid = _grant(rig.fx)
    out = _reconciled(rig.commit("op-1", rig.packet(plan=LEGACY)))
    assert rig.ref() == out["commit"]
    entry = _envelope(rig.fx, uid)["consumed"][LEGACY]["exec_commit"]
    assert entry["op_id"] == "op-1"
    before = rig.ref()
    second = rig.packet(files={"second.txt": b"second\n"}, plan=LEGACY)
    assert _commit_refusal(rig.commit("op-2", second)) == (
        "consumed",
        f"{LEGACY}:exec_commit",
    )
    assert rig.ref() == before


def test_ac_939_1_check_scope_covers_any_plan_of_the_project(tmp_path: Path) -> None:
    """AC-939.1: the standing grant is in scope for any plan slug of the project."""
    rig = _rig(tmp_path)
    _legacy_plan(rig)
    _legacy_plan(rig, "2026-11-02-another-legacy-plan")
    uid = _grant(rig.fx)
    for plan in (LEGACY, "2026-11-02-another-legacy-plan"):
        live = _authority(rig.fx, plan, "exec_commit")
        assert live is not None and live["message_uuid"] == uid, plan


# -- AC-939.2: revocation ---------------------------------------------------------------------


def test_ac_939_2_revoke_ends_the_standing_grant(tmp_path: Path) -> None:
    """AC-939.2: the real ``revoke`` on a real store ends the grant; the grant route refuses ``no_authority``."""
    rig = _rig(tmp_path)
    _legacy_plan(rig)
    uid = _grant(rig.fx)
    assert _authority(rig.fx, LEGACY, "exec_commit") is not None
    record = rig.fx.add_human(f"revoke run_parameters {uid}")
    code, out = rig.fx.run("revoke", "--session", rig.fx.session, "--message", record)
    assert (code, out.get("result"), out.get("revoked")) == (0, "revoked", uid), out
    assert _authority(rig.fx, LEGACY, "exec_commit") is None
    before = rig.ref()
    reason, _detail = _commit_refusal(rig.commit("op-1", rig.packet(plan=LEGACY)))
    assert reason == "no_authority"
    assert rig.ref() == before


def test_ac_939_2_commit_after_revocation_refuses(tmp_path: Path) -> None:
    """AC-939.2: after a revoke, a commit that worked before the revoke refuses."""
    rig = _rig(tmp_path)
    _legacy_plan(rig)
    _legacy_plan(rig, "2026-11-02-another-legacy-plan")
    uid = _grant(rig.fx)
    _reconciled(rig.commit("op-1", rig.packet(plan=LEGACY)))
    record = rig.fx.add_human(f"revoke run_parameters {uid}")
    code, out = rig.fx.run("revoke", "--session", rig.fx.session, "--message", record)
    assert code == 0, out
    before = rig.ref()
    packet = rig.packet(
        files={"after.txt": b"after\n"}, plan="2026-11-02-another-legacy-plan"
    )
    reason, _detail = _commit_refusal(rig.commit("op-2", packet))
    assert reason == "no_authority"
    assert rig.ref() == before


def test_ac_939_2_revoke_of_a_malformed_envelope_fails_closed(tmp_path: Path) -> None:
    """AC-939.2: a revoke over a malformed standing envelope refuses ``store_malformed``."""
    rig = _rig(tmp_path)
    uid = _grant(rig.fx)
    envelope = _envelope(rig.fx, uid)
    _grant_path(rig.fx, uid).write_text(
        json.dumps({**envelope, "unknown": True}) + "\n", encoding="utf-8"
    )
    record = rig.fx.add_human(f"revoke run_parameters {uid}")
    code, out = rig.fx.run("revoke", "--session", rig.fx.session, "--message", record)
    assert (code, out.get("result"), out.get("reason")) == (
        1,
        "refused",
        "store_malformed",
    ), out


# -- AC-939.3: the authority order ------------------------------------------------------------


def test_ac_939_3_no_standing_grant_returns_none(tmp_path: Path) -> None:
    """AC-939.3: with no standing grant recorded, ``standing_authority`` returns None."""
    rig = _rig(tmp_path)
    _legacy_plan(rig)
    assert _authority(rig.fx, LEGACY, "exec_commit") is None
    assert _authority(rig.fx, "none", "exec_commit") is None


def test_ac_939_3_legacy_and_planless_are_covered(tmp_path: Path) -> None:
    """AC-939.3: the standing grant covers a legacy plan and a planless packet for its three acts."""
    rig = _rig(tmp_path)
    _legacy_plan(rig)
    uid = _grant(rig.fx)
    for plan in (LEGACY, "none"):
        for act in STANDING_GRANTS:
            live = _authority(rig.fx, plan, act)
            assert live is not None and live["message_uuid"] == uid, (plan, act)
    assert _authority(rig.fx, LEGACY, "exec_start") is None


def test_ac_939_3_plan_grant_comes_first(tmp_path: Path) -> None:
    """AC-939.3: a plan with its own reserved grant commits on it; the standing envelope stays unconsumed."""
    rig = _rig(tmp_path)
    uid = _grant(rig.fx)
    rig.reserve("op-1")
    _reconciled(rig.commit("op-1", rig.packet()))
    assert _envelope(rig.fx, uid)["consumed"] == {}


def test_ac_939_3_manual_plan_opts_out(tmp_path: Path) -> None:
    """AC-939.3: a manual plan opts out: ``standing_opt_out:manual`` on the grant route."""
    rig = _rig(tmp_path)
    _grant(rig.fx)
    _manual_plan(rig)
    for act in STANDING_GRANTS:
        assert _opt_out(rig.fx, rig.plan, act) == "manual"
    before = rig.ref()
    assert _commit_refusal(rig.commit("op-1", rig.packet())) == (
        "standing_opt_out",
        "manual",
    )
    assert rig.ref() == before


def test_ac_939_3_commit_exec_false_opts_out(tmp_path: Path) -> None:
    """AC-939.3: ``commit_exec: false`` opts out of exec_commit and finalize (``standing_opt_out:commit_exec``)."""
    rig = _rig(tmp_path)
    _grant(rig.fx)
    _tightened_plan(rig, "commit_exec")
    assert _opt_out(rig.fx, rig.plan, "exec_commit") == "commit_exec"
    assert _opt_out(rig.fx, rig.plan, "finalize") == "commit_exec"
    before = rig.ref()
    assert _commit_refusal(rig.commit("op-1", rig.packet())) == (
        "standing_opt_out",
        "commit_exec",
    )
    assert rig.ref() == before


def test_ac_939_3_commit_plan_false_opts_out_of_plan_commit(tmp_path: Path) -> None:
    """AC-939.3: ``commit_plan: false`` opts out of plan_commit (``standing_opt_out:commit_plan``)."""
    rig = _rig(tmp_path)
    _grant(rig.fx)
    _tightened_plan(rig, "commit_plan")
    assert _opt_out(rig.fx, rig.plan, "plan_commit") == "commit_plan"


def test_ac_939_3_legacy_plan_commits_under_the_standing_grant(tmp_path: Path) -> None:
    """AC-939.3: a legacy plan with no block commits on the grant route under the standing grant."""
    rig = _rig(tmp_path)
    _legacy_plan(rig)
    _grant(rig.fx)
    parent = rig.ref()
    out = _reconciled(rig.commit("op-1", rig.packet(plan=LEGACY)))
    assert out["parent"] == parent
    assert rig.ref() == out["commit"]


# -- AC-939.6: planless packets ---------------------------------------------------------------


def test_ac_939_6_planless_packet_commits_under_the_standing_grant(
    tmp_path: Path,
) -> None:
    """AC-939.6: a ``plan: none`` packet commits under the grant, keyed by its digest, not in consumed."""
    rig = _rig(tmp_path)
    uid = _grant(rig.fx)
    packet = rig.packet(files={"planless.txt": b"planless\n"}, plan="none")
    out = _reconciled(rig.commit("op-1", packet))
    assert rig.ref() == out["commit"]
    assert (rig.fx.store / "ops" / "planless" / _digest(packet)).is_dir()
    assert "none" not in _envelope(rig.fx, uid)["consumed"]


def test_ac_939_6_second_run_of_the_same_packet_is_already_consumed(
    tmp_path: Path,
) -> None:
    """AC-939.6: a second run of the same planless packet refuses ``already_consumed``."""
    rig = _rig(tmp_path)
    _grant(rig.fx)
    packet = rig.packet(files={"planless.txt": b"planless\n"}, plan="none")
    _reconciled(rig.commit("op-1", packet))
    after = rig.ref()
    reason, _detail = _commit_refusal(rig.commit("op-2", packet))
    assert reason == "already_consumed"
    assert rig.ref() == after


def test_ac_939_6_typed_direction_names_the_planless_id(tmp_path: Path) -> None:
    """AC-939.6: a typed direction that names ``planless:<digest8>`` commits the planless packet."""
    rig = _rig(tmp_path)
    packet = rig.packet(files={"directed.txt": b"directed\n"}, plan="none")
    uid = rig.fx.add_human(f"commit planless:{_digest(packet)[:8]}")
    out = _reconciled(rig.human(uid, packet))
    assert rig.ref() == out["commit"]


def test_ac_939_6_direction_with_a_wrong_digest_refuses(tmp_path: Path) -> None:
    """AC-939.6: a direction that names another digest refuses ``no_commit_direction``."""
    rig = _rig(tmp_path)
    packet = rig.packet(files={"directed.txt": b"directed\n"}, plan="none")
    real = _digest(packet)[:8]
    wrong = "0" * 8 if real != "0" * 8 else "1" * 8
    uid = rig.fx.add_human(f"commit planless:{wrong}")
    before = rig.ref()
    reason, _detail = _commit_refusal(rig.human(uid, packet))
    assert reason == "no_commit_direction"
    assert rig.ref() == before


def test_ac_939_6_planless_delete_under_the_grant_refuses(tmp_path: Path) -> None:
    """AC-939.6: a planless packet that deletes a path under the grant refuses ``foreign_delete:<path>``."""
    rig = _rig(tmp_path)
    rig.seed({"seeded.txt": b"seeded\n"})
    _grant(rig.fx)
    before = rig.ref()
    packet = rig.packet(
        files={"planless.txt": b"planless\n"}, deletes=("seeded.txt",), plan="none"
    )
    assert _commit_refusal(rig.commit("op-1", packet)) == (
        "foreign_delete",
        "seeded.txt",
    )
    assert rig.ref() == before
    assert not (rig.fx.store / "ops" / "planless" / _digest(packet)).exists()
