"""Run-parameters tests for the review limits (AC-13 … AC-16).

AC-13  A ``basis: loosened`` block opens a ledger only when ``run_parameters.py limits-check
       --plan <slug>`` exits 0: the task's ``authorization/1`` verifies, its ``form`` is
       ``self-contained`` (the human typed the values), and the offer's ``review_limits``
       equals the block.
AC-14  Offer schema ``run-parameters-offer/2`` adds ``review_limits``; a /1 offer cannot carry
       it, and its six keys are typed (a quoted ``"3"`` is not a round count).
AC-15  The final audit's execution round cap comes from ``audit_round_cap``: the ``exec-<slug>``
       ledger's ``rounds_allowed()``; ``exec_ledger_missing`` when the task carries a block but
       no ledger exists; the repo file, then 6, only for a legacy task.
AC-16  ``limits-check`` is read-only: the store and the plan files are byte-identical after it.

The run-parameters fixtures are the B-2 ones (``run_parameters_fixtures.build_fixture``). The
ledger is ``tools.review_ledger`` with ``REPO_ROOT`` pointed at the fixture repository, and its
``begin`` runs the real ``limits-check`` in a child process with the fixture environment.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / bf.RUN_PARAMETERS_HOME / "schemas"
GOAL = "Bounded independent review of the review-limits fixture"
#: The fixture repository has no ``.agent/review-limits.json``, so the ledger's constants
#: (execution 6 rounds, 21,000,000 tokens) are the repo limits; 9 rounds is looser.
LOOSENED: dict[str, Any] = {
    "schema": "review-limits/1",
    "plan_rounds": 3,
    "execution_rounds": 9,
    "plan_tokens": 10500000,
    "execution_tokens": 21000000,
    "basis": "loosened",
}
TOKENS_OFF: dict[str, Any] = {**LOOSENED, "execution_rounds": 6, "execution_tokens": "off"}
#: An approved execution review in the closeout validator's markdown form.
APPROVED_REVIEW = """---
date: "2026-10-20"
review_mode: "execution"
target_plan: "{target}"
verdict: "approved"
findings_count: 0
template_version: "2.1"
---

# Critical Review: fixture-plan

## Findings

| # | Severity | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|

## Verdict

`approved` -- behaviour matches the plan.
"""


def _rp() -> ModuleType:
    return importlib.import_module("tools.run_parameters")


def _ledger_mod() -> ModuleType:
    return importlib.import_module("tools.review_ledger")


def _build(tmp_path: Path) -> bf.Fixture:
    return bf.build(tmp_path / "fx", ROOT)


def _limits_text(limits: Mapping[str, Any]) -> str:
    return "review_limits:\n" + "".join(f"  {key}: {value}\n" for key, value in limits.items())


def _add_limits(path: Path, limits: Mapping[str, Any]) -> None:
    """Put a ``review_limits`` block at the end of ``path``'s frontmatter."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    end = text.index("\n---\n", 3) + 1
    path.write_bytes((text[:end] + _limits_text(limits) + text[end:]).encode("utf-8"))


def _carriers_with_limits(fx: bf.Fixture, limits: Mapping[str, Any]) -> None:
    """The block in both carriers, and two AC rows in the plan for ``begin`` to count."""
    _add_limits(fx.plan_path(), limits)
    _add_limits(fx.task_path(), limits)
    with fx.plan_path().open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n| AC-1 | x |\n| AC-2 | y |\n")


def _self_contained(
    fx: bf.Fixture,
    limits: Mapping[str, Any] | None = LOOSENED,
    *,
    carrier_limits: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A human-typed offer (``form: self-contained``), its carriers, and their block.

    ``limits`` None writes a /1 offer without ``review_limits``; the carriers get
    ``carrier_limits`` (default: the offered ones).
    """
    values = fx.offer()
    if limits is not None:
        values["schema"] = "run-parameters-offer/2"
        values["review_limits"] = dict(limits)
    lines = fx.lines(values)
    text = "\n".join(["/create-plan fixture", "```yaml", *lines, "```"])
    message = fx.add_human(text)
    auth = fx.authorization(
        values,
        message_uuid=message,
        presentation_uuid=message,
        response=text,
        lines=lines,
        form="self-contained",
    )
    fx.write_carrier(fx.make_block(values, auth))
    _carriers_with_limits(fx, carrier_limits or limits or LOOSENED)
    return values


def _limits_check(fx: bf.Fixture) -> tuple[int, dict[str, Any]]:
    return fx.run("limits-check", "--plan", fx.plan)


def _refused(res: tuple[int, dict[str, Any]], reason: str) -> None:
    code, out = res
    assert (code, out.get("result"), out.get("reason")) == (1, "refused", reason), out
    assert out.get("authorized") is False, out


def _passed(res: tuple[int, dict[str, Any]], limits: Mapping[str, Any]) -> None:
    code, out = res
    assert (code, out.get("result")) == (0, "limits_verified"), out
    assert out.get("review_limits") == dict(limits), out


@pytest.fixture
def ledger_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ModuleType, Path]:
    """``tools.review_ledger`` with a temporary ``RECEIPTS_DIR``; returns (module, receipts)."""
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    monkeypatch.setenv("RECEIPTS_DIR", str(receipts))
    return _ledger_mod(), receipts


def _begin(
    ledger: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fx: bf.Fixture,
    *,
    loop_id: str = "exec-loop",
    mode: str = "execution",
    ac_file: Path | None = None,
) -> tuple[int, str]:
    """``review_ledger begin`` over the fixture plan, with the fixture's verb environment."""
    monkeypatch.setattr(ledger, "REPO_ROOT", fx.repo)
    for key, value in fx.env().items():
        if key.startswith(("CLAUDE_", "RUN_PARAMETERS_TEST_")) or key == "PYTHONPATH":
            monkeypatch.setenv(key, value)
    code = ledger.main(
        [
            "begin",
            "--loop-id",
            loop_id,
            "--review-mode",
            mode,
            "--producer",
            "builder-x",
            "--goal-anchor",
            GOAL,
            "--ac-file",
            str(ac_file or fx.plan_path()),
        ]
    )
    out = capsys.readouterr()
    return code, out.out + out.err


def _tree_digests(fx: bf.Fixture) -> dict[str, str]:
    """sha256 of every file in the fixture repository outside ``.git``."""
    return {
        path.relative_to(fx.repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(fx.repo.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(fx.repo).parts
    }


# --- AC-13 --------------------------------------------------------------------------------


@pytest.mark.parametrize("limits", [LOOSENED, TOKENS_OFF], ids=["rounds-9", "tokens-off"])
def test_human_typed_offer_passes_limits_check(tmp_path: Path, limits: dict[str, Any]) -> None:
    """AC-13: a self-contained /2 offer with the block's values passes ``limits-check``."""
    fx = _build(tmp_path)
    _self_contained(fx, limits)
    _passed(_limits_check(fx), limits)


@pytest.mark.parametrize("limits", [LOOSENED, TOKENS_OFF], ids=["rounds-9", "tokens-off"])
def test_begin_opens_a_loosened_loop_after_limits_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ledger_env: tuple[ModuleType, Path],
    limits: dict[str, Any],
) -> None:
    """AC-13: ``begin`` runs the real ``limits-check`` and opens the loosened loop."""
    ledger, _receipts = ledger_env
    fx = _build(tmp_path)
    _self_contained(fx, limits)
    code, out = _begin(ledger, monkeypatch, capsys, fx)
    assert code == 0, out
    opened = ledger.load_ledger("exec-loop")
    assert opened["round_budget"] == limits["execution_rounds"], opened
    assert opened["token_budget"] == limits["execution_tokens"], opened


def _case_disabled(fx: bf.Fixture) -> None:
    _self_contained(fx)
    fx.policy_path.unlink()


def _case_manual(fx: bf.Fixture) -> None:
    fx.write_carrier({**fx.block, "authorization": {"schema": "manual"}})
    _carriers_with_limits(fx, LOOSENED)


def _case_legacy(fx: bf.Fixture) -> None:
    auth = fx.block["authorization"]
    legacy = {
        "schema": "authorization/1-legacy",
        "source": "USER_EXPLICIT",
        **{
            key: auth[key]
            for key in (
                "project",
                "session",
                "message_uuid",
                "presentation_uuid",
                "offer_digest",
                "date",
                "response",
            )
        },
        "scope": {"plan": "none", "grouping": "none", "branch": "none"},
        "grants": ["ruling"],
        "standing": False,
        "supersedes": "none",
    }
    fx.write_carrier({**fx.block, "authorization": legacy})
    _carriers_with_limits(fx, LOOSENED)


def _case_reply_form(fx: bf.Fixture) -> None:
    """The assistant presents a /2 offer with the loosened values; the human types ``proceed``."""
    values = fx.offer()
    values["schema"] = "run-parameters-offer/2"
    values["review_limits"] = dict(LOOSENED)
    fx.write_carrier(fx.present_and_accept(values=values))
    _carriers_with_limits(fx, LOOSENED)


def _case_one_value_differs(fx: bf.Fixture) -> None:
    _self_contained(fx, LOOSENED, carrier_limits={**LOOSENED, "execution_rounds": 10})


def _case_offer_without_key(fx: bf.Fixture) -> None:
    _self_contained(fx, None)


REFUSALS: dict[str, tuple[Any, str]] = {
    "disabled": (_case_disabled, "disabled"),
    "manual": (_case_manual, "manual"),
    "legacy": (_case_legacy, "legacy"),
    "reply-form": (_case_reply_form, "consent"),
    "one-value-differs": (_case_one_value_differs, "binding"),
    "offer-without-key": (_case_offer_without_key, "binding"),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_limits_check_refuses(tmp_path: Path, case: str) -> None:
    """AC-13: each case named by the AC is refused (manual and legacy are non-authorizing)."""
    fx = _build(tmp_path)
    build, reason = REFUSALS[case]
    build(fx)
    code, out = _limits_check(fx)
    assert code == 1, out
    assert out.get("reason") == reason, out
    assert out.get("authorized") is False, out
    assert out.get("result") in ("refused", reason), out


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_begin_exits_1_when_limits_check_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ledger_env: tuple[ModuleType, Path],
    case: str,
) -> None:
    """AC-13: ``begin`` exits 1 and opens no ledger for each refused case."""
    ledger, _receipts = ledger_env
    fx = _build(tmp_path)
    REFUSALS[case][0](fx)
    code, out = _begin(ledger, monkeypatch, capsys, fx)
    assert code == 1, out
    assert "limits-check" in out, out
    assert not ledger.ledger_path("exec-loop").exists()


def test_begin_refuses_a_same_slug_ac_file_with_other_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ledger_env: tuple[ModuleType, Path],
) -> None:
    """AC-13: ``limits-check`` verifies the repository plan, so ``begin`` installs only that block.

    An ``--ac-file`` outside the repository, in a folder with the plan's slug, asks for 999
    rounds and no token budget; the real ``limits-check`` passes on the repository plan, and
    ``begin`` refuses because the block it would install is not the block that was verified.
    """
    ledger, _receipts = ledger_env
    fx = _build(tmp_path)
    _self_contained(fx)
    _passed(_limits_check(fx), LOOSENED)
    alternate = tmp_path / "elsewhere" / fx.plan / "implementation-plan.md"
    alternate.parent.mkdir(parents=True)
    shutil.copyfile(fx.plan_path(), alternate)
    text = alternate.read_text(encoding="utf-8")
    alternate.write_bytes(
        text.replace("execution_rounds: 9", "execution_rounds: 999")
        .replace("execution_tokens: 21000000", "execution_tokens: off")
        .encode("utf-8")
    )
    code, out = _begin(ledger, monkeypatch, capsys, fx, ac_file=alternate)
    assert code == 1, out
    assert "not the block limits-check verified" in out, out
    assert not ledger.ledger_path("exec-loop").exists()


def test_limits_check_refuses_off_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-13: off Windows the check refuses ``disabled`` before reading any carrier."""
    fx = _build(tmp_path)
    _self_contained(fx)
    monkeypatch.setattr(_rp(), "_is_windows", lambda: False)
    _refused(_limits_check(fx), "disabled")


def test_limits_check_refuses_a_plan_without_a_block(tmp_path: Path) -> None:
    """AC-13: no ``review_limits`` in the plan means nothing to verify (``binding``)."""
    fx = _build(tmp_path)
    _self_contained(fx)
    fx.plan_path().write_bytes(
        fx.plan_path().read_bytes().replace(_limits_text(LOOSENED).encode("utf-8"), b"")
    )
    _refused(_limits_check(fx), "binding")


def test_limits_check_refuses_a_task_block_that_differs(tmp_path: Path) -> None:
    """AC-13: a task block that is not the plan block is refused (``binding``)."""
    fx = _build(tmp_path)
    _self_contained(fx)
    task = fx.task_path()
    data = task.read_bytes()
    # The last one is the block's: the authorization's verbatim response holds the same line.
    at = data.rindex(b"execution_rounds: 9")
    task.write_bytes(data[:at] + b"execution_rounds: 8" + data[at + 19 :])
    _refused(_limits_check(fx), "binding")


def test_limits_check_refuses_a_malformed_block(tmp_path: Path) -> None:
    """AC-13: a block the ledger's strict reader refuses is ``schema``, never a guess."""
    fx = _build(tmp_path)
    _self_contained(fx)
    plan = fx.plan_path()
    plan.write_bytes(plan.read_bytes().replace(b"plan_rounds: 3", b"plan_rounds: three"))
    _refused(_limits_check(fx), "schema")


# --- AC-14 --------------------------------------------------------------------------------


def _offer_lines(fx: bf.Fixture, **over: Any) -> list[str]:
    values = fx.offer()
    values.update(over)
    return fx.lines(values)


def test_v2_offer_parses_typed_limits(tmp_path: Path) -> None:
    """AC-14: a /2 offer parses ``review_limits`` to ints and ``off``."""
    fx = _build(tmp_path)
    lines = _offer_lines(
        fx, schema="run-parameters-offer/2", review_limits=dict(TOKENS_OFF)
    )
    offer = _rp()._parse_offer(lines)
    assert offer["review_limits"] == TOKENS_OFF
    assert type(offer["review_limits"]["plan_rounds"]) is int


def test_v1_offer_is_unchanged(tmp_path: Path) -> None:
    """AC-14: a /1 offer still parses to its fourteen keys."""
    fx = _build(tmp_path)
    offer = _rp()._parse_offer(_offer_lines(fx))
    assert list(offer) == list(_rp().OFFER_KEYS)
    assert "review_limits" not in offer


def _offer_refused(lines: list[str]) -> None:
    rp = _rp()
    with pytest.raises(rp.Refusal) as caught:
        rp._parse_offer(lines)
    assert caught.value.reason == "offer_schema", caught.value


def test_v1_offer_cannot_carry_review_limits(tmp_path: Path) -> None:
    """AC-14: a /1 offer that carries ``review_limits`` is refused (``offer_schema``)."""
    fx = _build(tmp_path)
    _offer_refused(_offer_lines(fx, review_limits=dict(LOOSENED)))


def test_v2_offer_needs_review_limits(tmp_path: Path) -> None:
    """AC-14: a /2 offer without ``review_limits`` is refused."""
    fx = _build(tmp_path)
    _offer_refused(_offer_lines(fx, schema="run-parameters-offer/2"))


def test_v2_offer_refuses_a_quoted_round_count(tmp_path: Path) -> None:
    """AC-14: ``plan_rounds: "3"`` (a string) is refused."""
    fx = _build(tmp_path)
    lines = _offer_lines(
        fx, schema="run-parameters-offer/2", review_limits=dict(LOOSENED)
    )
    lines = [
        line.replace("plan_rounds: 3,", 'plan_rounds: "3",') if "review_limits" in line else line
        for line in lines
    ]
    assert any('plan_rounds: "3"' in line for line in lines)
    _offer_refused(lines)


@pytest.mark.parametrize(
    "change",
    [
        {"plan_rounds": 0},
        {"execution_rounds": "off"},
        {"plan_tokens": "none"},
        {"basis": "relaxed"},
        {"schema": "review-limits/2"},
        {"extra": 1},
    ],
    ids=["zero-rounds", "rounds-off", "tokens-word", "basis", "schema", "extra-key"],
)
def test_v2_offer_refuses_a_bad_limit(tmp_path: Path, change: dict[str, Any]) -> None:
    """AC-14: the six-key check refuses each bad value and an unknown key."""
    fx = _build(tmp_path)
    limits = {**LOOSENED, **change}
    _offer_refused(
        _offer_lines(fx, schema="run-parameters-offer/2", review_limits=limits)
    )


def test_v2_offer_refuses_a_missing_limit_key(tmp_path: Path) -> None:
    """AC-14: all six keys are required."""
    fx = _build(tmp_path)
    limits = {key: value for key, value in LOOSENED.items() if key != "basis"}
    _offer_refused(
        _offer_lines(fx, schema="run-parameters-offer/2", review_limits=limits)
    )


def test_v2_offer_verifies_acts(tmp_path: Path) -> None:
    """AC-14: a /2 offer is an ordinary offer for ``verify``."""
    fx = _build(tmp_path)
    _self_contained(fx)
    code, out = fx.run("init", "--plan", fx.plan)
    assert code == 0, out
    code, out = fx.run("verify", "exec_start", "--plan", fx.plan)
    assert (code, out.get("result")) == (0, "verified"), out


def test_v2_schema_file_matches_the_parser(tmp_path: Path) -> None:
    """AC-14: the /2 schema accepts a parsed /2 offer; the /1 schema refuses ``review_limits``."""
    fx = _build(tmp_path)
    offer = _rp()._parse_offer(
        _offer_lines(fx, schema="run-parameters-offer/2", review_limits=dict(TOKENS_OFF))
    )
    v2 = json.loads(
        (SCHEMAS / "run-parameters-offer.v2.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(v2).validate({"run-parameters-offer": offer})
    v1 = json.loads(
        (SCHEMAS / "run-parameters-offer.v1.schema.json").read_text(encoding="utf-8")
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(v1).validate(
            {"run-parameters-offer": {**offer, "schema": "run-parameters-offer/1"}}
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(v2).validate(
            {
                "run-parameters-offer": {
                    **offer,
                    "review_limits": {**TOKENS_OFF, "plan_rounds": "3"},
                }
            }
        )


# --- AC-15 --------------------------------------------------------------------------------

PLAN = bf.PLAN


def _audit_tree(tmp_path: Path, limits: Mapping[str, Any] | None = None) -> Path:
    """A tree with the plan's task (and, when given, its ``review_limits``) and plan file."""
    top = tmp_path / "tree"
    paths = _rp()._final_paths(PLAN)
    task = top / paths["task"]
    task.parent.mkdir(parents=True)
    block = _limits_text(limits) if limits is not None else ""
    task.write_text(f"---\nstatus: complete\n{block}---\n\n# Task\n", encoding="utf-8")
    (top / paths["plan"]).write_text(
        "---\nproject: \"fixture\"\n---\n\n# Plan\n| AC-1 | x |\n| AC-2 | y |\n",
        encoding="utf-8",
    )
    return top


def _open_exec_ledger(
    ledger: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    top: Path,
    *,
    mode: str = "execution",
    grant: int = 0,
) -> None:
    """``exec-<plan>`` at the repo limits (6 rounds), plus ``grant`` rounds through continue."""
    monkeypatch.setattr(ledger, "REPO_ROOT", top)
    plan = top / _rp()._final_paths(PLAN)["plan"]
    code = ledger.main(
        [
            "begin",
            "--loop-id",
            f"exec-{PLAN}",
            "--review-mode",
            mode,
            "--producer",
            "builder-x",
            "--goal-anchor",
            GOAL,
            "--ac-file",
            str(plan),
        ]
    )
    assert code == 0, capsys.readouterr()
    if grant:
        code = ledger.main(
            [
                "continue",
                "--loop-id",
                f"exec-{PLAN}",
                "--rounds",
                str(grant),
                "--said",
                "the reviewer is converging and one more round is worth it",
                "--by",
                "Pat",
                "--at",
                "2026-10-20T10:00:00",
            ]
        )
        assert code == 0, capsys.readouterr()
    capsys.readouterr()


def _review_with_rounds(top: Path, rounds: int) -> None:
    paths = _rp()._final_paths(PLAN)
    review = top / paths["review"]
    review.parent.mkdir(parents=True, exist_ok=True)
    rechecks = "".join(
        f"\n## Recheck (2026-10-2{n})\n\n### Verdict\n\n`approved`\n" for n in range(rounds - 1)
    )
    review.write_text(
        APPROVED_REVIEW.format(target=paths["plan"]) + rechecks, encoding="utf-8"
    )


def _stage_calls(top: Path, capfd: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """Run the final-stage validators; return their ``validator_failed`` events."""
    capfd.readouterr()
    _rp().run_stage_validators(top, PLAN, top)
    err = capfd.readouterr().err
    return [
        event
        for event in (json.loads(line) for line in err.splitlines() if line.startswith("{"))
        if event.get("event") == "validator_failed"
    ]


def test_audit_cap_counts_a_continue_grant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    ledger_env: tuple[ModuleType, Path],
) -> None:
    """AC-15 (1): base 6 plus a 1-round continue lets a round-7 approval pass the review state."""
    ledger, _receipts = ledger_env
    top = _audit_tree(tmp_path)
    _open_exec_ledger(ledger, monkeypatch, capfd, top, grant=1)
    assert _rp().audit_round_cap(top, PLAN) == 7
    _review_with_rounds(top, 7)
    failed = _stage_calls(top, capfd)
    assert not [e for e in failed if "--review-state-only" in e["argv"]], failed
    produce = [e for e in failed if "--for-produce" in e["argv"]]
    assert len(produce) == 1, failed
    argv = produce[0]["argv"]
    assert argv[argv.index("--max-review-rounds") + 1] == "7", argv


def test_audit_cap_without_a_grant_stops_round_7(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    ledger_env: tuple[ModuleType, Path],
) -> None:
    """AC-15 (2): the same round-7 review against a ledger with no grant fails."""
    ledger, _receipts = ledger_env
    top = _audit_tree(tmp_path)
    _open_exec_ledger(ledger, monkeypatch, capfd, top)
    assert _rp().audit_round_cap(top, PLAN) == 6
    _review_with_rounds(top, 7)
    failed = _stage_calls(top, capfd)
    state = [e for e in failed if "--review-state-only" in e["argv"]]
    assert len(state) == 1, failed
    assert "over the cap of 6" in state[0]["stdout"] + state[0]["stderr"], state


def _audit_refused(top: Path, detail: str) -> None:
    rp = _rp()
    with pytest.raises(rp.Refusal) as caught:
        rp.audit_round_cap(top, PLAN)
    assert (caught.value.reason, caught.value.detail) == ("binding", detail), caught.value
    with pytest.raises(rp.Refusal):
        rp.run_stage_validators(top, PLAN, top)


def test_audit_cap_refuses_a_block_without_a_ledger(
    tmp_path: Path, ledger_env: tuple[ModuleType, Path]
) -> None:
    """AC-15 (3): a valid /1 grant and a task block with 7 rounds, but no ledger: refused."""
    fx = _build(tmp_path)
    _add_limits(fx.task_path(), {**LOOSENED, "execution_rounds": 7})
    _review_with_rounds(fx.repo, 7)
    _audit_refused(fx.repo, "exec_ledger_missing")


def test_audit_cap_refuses_a_malformed_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ledger_env: tuple[ModuleType, Path],
) -> None:
    """AC-15 (4): a ledger that does not load fails closed."""
    ledger, _receipts = ledger_env
    top = _audit_tree(tmp_path)
    _open_exec_ledger(ledger, monkeypatch, capsys, top)
    path = ledger.ledger_path(f"exec-{PLAN}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["token_budget"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")
    _audit_refused(top, "exec_ledger_malformed")
    path.write_text("{not json", encoding="utf-8")
    _audit_refused(top, "exec_ledger_malformed")


def test_audit_cap_refuses_a_plan_mode_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ledger_env: tuple[ModuleType, Path],
) -> None:
    """AC-15 (5): ``exec-<slug>`` whose ``review_mode`` is ``plan`` fails closed."""
    ledger, _receipts = ledger_env
    top = _audit_tree(tmp_path)
    _open_exec_ledger(ledger, monkeypatch, capsys, top, mode="plan")
    _audit_refused(top, "exec_ledger_mode")


def test_audit_cap_of_a_legacy_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ledger_env: tuple[ModuleType, Path],
) -> None:
    """AC-15 (6): no block and no ledger: the repo file's ``rounds.execution``, else 6."""
    rp = _rp()
    top = _audit_tree(tmp_path)
    assert rp.audit_round_cap(top, PLAN) == 6
    shipped = top / ".agent" / "review-limits.json"
    shipped.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / ".agent" / "review-limits.json", shipped)
    assert rp.audit_round_cap(top, PLAN) == 6
    data = json.loads(shipped.read_text(encoding="utf-8"))
    data["rounds"]["execution"] = 8
    shipped.write_text(json.dumps(data), encoding="utf-8")
    assert rp.audit_round_cap(top, PLAN) == 8
    monkeypatch.delenv("RECEIPTS_DIR")
    assert rp.audit_round_cap(top, PLAN) == 8


def test_audit_cap_refuses_a_malformed_repo_file(
    tmp_path: Path, ledger_env: tuple[ModuleType, Path]
) -> None:
    """AC-15 (6): a repo file the reader refuses is not a fall back to 6."""
    rp = _rp()
    top = _audit_tree(tmp_path)
    bad = top / ".agent" / "review-limits.json"
    bad.parent.mkdir(parents=True)
    bad.write_text('{"schema": "review-limits/1"}', encoding="utf-8")
    with pytest.raises(rp.Refusal) as caught:
        rp.audit_round_cap(top, PLAN)
    assert caught.value.reason == "schema", caught.value


def test_the_fixed_cap_is_no_longer_passed_directly() -> None:
    """AC-15: ``EXEC_REVIEW_MAX_ROUNDS`` is only the legacy fallback, never an argv value."""
    text = (ROOT / "tools" / "run_parameters.py").read_text(encoding="utf-8")
    assert "str(EXEC_REVIEW_MAX_ROUNDS)" not in text


# --- AC-16 --------------------------------------------------------------------------------


@pytest.mark.parametrize("passing", [True, False], ids=["pass", "refuse"])
def test_limits_check_writes_nothing(tmp_path: Path, passing: bool) -> None:
    """AC-16: the store and every repository file are byte-identical after a run."""
    fx = _build(tmp_path)
    if passing:
        _self_contained(fx)
    else:
        _case_one_value_differs(fx)
    code, out = fx.run("init", "--plan", fx.plan)
    assert (code, out.get("result")) == (0, "initialized"), out
    store, tree = fx.store_snapshot(), _tree_digests(fx)
    code, out = _limits_check(fx)
    assert code == (0 if passing else 1), out
    assert fx.store_snapshot() == store
    assert _tree_digests(fx) == tree


def test_limits_check_without_a_store_creates_none(tmp_path: Path) -> None:
    """AC-16: with no store, a passing run does not create one."""
    fx = _build(tmp_path)
    _self_contained(fx)
    assert not fx.store.exists()
    _passed(_limits_check(fx), LOOSENED)
    assert not fx.store.exists()
