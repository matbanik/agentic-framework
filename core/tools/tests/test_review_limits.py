"""Ledger tests for the review limits (AC-5 … AC-12).

AC-5   ``begin`` reads ``.agent/review-limits.json`` and says so: ``source=repo:<sha12>``.
AC-6   No repo file means the constants, said as such; a malformed file is exit 3.
AC-7   For plan and execution loops, the ``review_limits`` block in the ``--ac-file``
       frontmatter sets the limits when its ``basis`` matches; other modes ignore it.
AC-8   A sibling ``task.md`` that carries the block must carry the same block (exit 1).
AC-9   ``--round-budget`` and ``--token-budget N|off`` only tighten (exit 1 otherwise).
AC-10  A token budget of ``off`` has no tokens stop and nothing for ``continue`` to lift;
       a hand-edited budget of 0 or null is exit 3.
AC-11  The selftest still passes, with at least 115 arms.
AC-12  A ledger written before this change gives the same stops as it did before.

Every test calls ``review_ledger.main`` in-process with ``REPO_ROOT`` pointed at a temporary
tree, so the repo file the test writes is the only one the ledger can see.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import review_ledger  # noqa: E402

GOAL = "Bounded independent review of the review-limits fixture"
MODES = ("plan", "execution", "discovery", "handoff", "multi-handoff")
DIFFERS = "review_limits differs between implementation-plan.md and task.md"

BLOCK_REPO = """\
review_limits:
  schema: review-limits/1
  plan_rounds: 3
  execution_rounds: 6
  plan_tokens: 10500000
  execution_tokens: 21000000
  basis: repo
"""

BLOCK_TIGHTENED = """\
review_limits:
  schema: review-limits/1
  plan_rounds: 2
  execution_rounds: 4
  plan_tokens: 5000                # a comment is allowed
  execution_tokens: 9000
  basis: tightened
"""


# --- helpers ------------------------------------------------------------------------------


def _repo_file(root: Path, **changes: object) -> Path:
    """Write ``<root>/.agent/review-limits.json``: the shipped values with ``changes``."""
    data: dict = {
        "schema": "review-limits/1",
        "token_budgets": "on",
        "rounds": dict(review_ledger.ROUND_BUDGETS),
        "tokens": dict(review_ledger.TOKEN_BUDGETS),
    }
    for key, value in changes.items():
        if isinstance(value, dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    path = root / ".agent" / "review-limits.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _plan(folder: Path, block: str | None = None, name: str = "implementation-plan.md") -> Path:
    """A plan with two ACs and, when given, a ``review_limits`` block in its frontmatter."""
    folder.mkdir(parents=True, exist_ok=True)
    front = f"---\nproject: \"fixture\"\n{block or ''}status: \"draft\"\n---\n"
    path = folder / name
    path.write_text(front + "\n# Plan\n| AC-1 | x |\n| AC-2 | y |\n", encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A receipts dir and an empty repo root; returns the root."""
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    monkeypatch.setenv("RECEIPTS_DIR", str(receipts))
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(review_ledger, "REPO_ROOT", root)
    return root


def _begin(
    capsys: pytest.CaptureFixture[str],
    plan: Path,
    mode: str = "execution",
    loop_id: str = "loop-x",
    *extra: str,
) -> tuple[int, str]:
    code = review_ledger.main([
        "begin", "--loop-id", loop_id, "--review-mode", mode, "--producer", "builder-x",
        "--goal-anchor", GOAL, "--ac-file", str(plan), *extra,
    ])
    return code, capsys.readouterr().out


def _ledger(loop_id: str = "loop-x") -> dict:
    return json.loads(review_ledger.ledger_path(loop_id).read_text(encoding="utf-8"))


def _hand_edit(loop_id: str, **changes: object) -> None:
    path = review_ledger.ledger_path(loop_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _round(n: int, usage: int | None) -> dict:
    return {
        "round": n, "agent": "reviewer-a", "verdict": "changes_required", "date": "2026-10-20",
        "blocking": 1,
        "findings": [{"id": f"F-{n}", "blocking": True, "subject": "deliverable",
                      "finding_kind": "behavior", "violates": "AC-1"}],
        "usage": usage, "unmeasured": usage is None, "intent_achieved": "partial",
    }


def _continue(capsys: pytest.CaptureFixture[str], loop_id: str, *buy: str) -> tuple[int, str]:
    code = review_ledger.main([
        "continue", "--loop-id", loop_id, *buy,
        "--said", "the reviewer is converging and one more round is worth it",
        "--by", "Pat", "--at", "2026-10-20T10:00:00",
    ])
    return code, capsys.readouterr().out


# --- AC-5 ---------------------------------------------------------------------------------


def test_repo_file_sets_the_limits(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-5: a repo file with ``rounds.execution: 9`` opens a loop with budget 9."""
    path = _repo_file(env, rounds={"execution": 9}, tokens={"execution": 777})
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    code, out = _begin(capsys, _plan(tmp_path / "plan"))
    assert code == 0, out
    assert "budget=9" in out
    assert f"source=repo:{sha[:12]}" in out
    ledger = _ledger()
    assert ledger["round_budget"] == 9
    assert ledger["token_budget"] == 777
    assert ledger["limits_source"] == {"repo": sha, "plan": None, "flags": []}


def test_repo_switch_off_opens_an_unbudgeted_loop(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-5/AC-10: ``token_budgets: "off"`` in the repo file stores ``token_budget: "off"``."""
    _repo_file(env, token_budgets="off")
    code, out = _begin(capsys, _plan(tmp_path / "plan"))
    assert code == 0, out
    assert "tokens=off" in out
    assert _ledger()["token_budget"] == "off"


# --- AC-6 ---------------------------------------------------------------------------------


def test_no_repo_file_uses_the_constants(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-6: no repo file means the constants, and the OK line says so."""
    code, out = _begin(capsys, _plan(tmp_path / "plan"), "discovery")
    assert code == 0, out
    assert "source=constants (no .agent/review-limits.json)" in out
    ledger = _ledger()
    assert ledger["round_budget"] == review_ledger.ROUND_BUDGETS["discovery"]
    assert ledger["token_budget"] == review_ledger.TOKEN_BUDGETS["discovery"]
    assert ledger["limits_source"]["repo"] == "constants"


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        json.dumps({"schema": "review-limits/1", "token_budgets": "on", "rounds": {}, "tokens": {}}),
        "",
    ],
    ids=["not-json", "empty-tables", "empty-file"],
)
def test_malformed_repo_file_fails_closed(env: Path, tmp_path: Path, capsys, text: str) -> None:  # type: ignore[no-untyped-def]
    """AC-6: a malformed repo file is exit 3, never a fall back to the constants."""
    path = env / ".agent" / "review-limits.json"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    code, out = _begin(capsys, _plan(tmp_path / "plan"))
    assert code == 3, out
    assert "review-limits.json" in out
    assert not review_ledger.ledger_path("loop-x").exists()


def test_repo_value_of_zero_fails_closed(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-6: ``rounds.plan: 0`` is malformed, exit 3."""
    _repo_file(env, rounds={"plan": 0})
    code, out = _begin(capsys, _plan(tmp_path / "plan"), "plan")
    assert code == 3, out


# --- AC-7 ---------------------------------------------------------------------------------


def test_block_at_basis_repo_names_the_plan(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-7: a ``basis: repo`` block opens the loop and ``limits_source.plan`` names the file."""
    plan = _plan(tmp_path / "plan", BLOCK_REPO)
    code, out = _begin(capsys, plan)
    assert code == 0, out
    ledger = _ledger()
    assert ledger["round_budget"] == 6
    assert ledger["token_budget"] == 21000000
    assert ledger["limits_source"]["plan"] == str(plan)
    assert ledger["limits_source"]["repo"] == "constants"


@pytest.mark.parametrize("mode,rounds,tokens", [("execution", 4, 9000), ("plan", 2, 5000)])
def test_tightened_block_sets_the_mode_values(env: Path, tmp_path: Path, capsys, mode, rounds, tokens) -> None:  # type: ignore[no-untyped-def]
    """AC-7: a tightened block sets the values for the loop's own mode."""
    code, out = _begin(capsys, _plan(tmp_path / "plan", BLOCK_TIGHTENED), mode)
    assert code == 0, out
    assert f"budget={rounds}" in out
    ledger = _ledger()
    assert (ledger["round_budget"], ledger["token_budget"]) == (rounds, tokens)


@pytest.mark.parametrize("mode", ["discovery", "handoff", "multi-handoff"])
def test_other_modes_ignore_the_block(env: Path, tmp_path: Path, capsys, mode: str) -> None:  # type: ignore[no-untyped-def]
    """AC-7: discovery and the handoff modes do not read the plan block."""
    code, out = _begin(capsys, _plan(tmp_path / "plan", BLOCK_TIGHTENED), mode)
    assert code == 0, out
    ledger = _ledger()
    assert ledger["round_budget"] == review_ledger.ROUND_BUDGETS[mode]
    assert ledger["limits_source"]["plan"] is None


def test_tightened_against_a_repo_switch_off(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-7: a number is tighter than ``off``, so a numeric block under repo "off" is tightened."""
    _repo_file(env, token_budgets="off")
    code, out = _begin(capsys, _plan(tmp_path / "plan", BLOCK_TIGHTENED))
    assert code == 0, out
    assert _ledger()["token_budget"] == 9000


def test_off_block_at_basis_repo_under_repo_off(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-7: ``off`` token values equal a repo "off" switch, so the basis is repo."""
    _repo_file(env, token_budgets="off")
    block = BLOCK_REPO.replace("10500000", "off").replace("21000000", "off")
    code, out = _begin(capsys, _plan(tmp_path / "plan", block))
    assert code == 0, out
    assert _ledger()["token_budget"] == "off"


@pytest.mark.parametrize(
    "block",
    [
        BLOCK_TIGHTENED.replace("execution_rounds: 4", "execution_rounds: 7"),
        BLOCK_TIGHTENED.replace("execution_tokens: 9000", "execution_tokens: off"),
        BLOCK_REPO.replace("plan_rounds: 3", "plan_rounds: 2"),
        BLOCK_REPO.replace("basis: repo", "basis: sideways"),
    ],
    ids=["tightened-but-looser", "tightened-but-off", "repo-but-tighter", "unknown-basis"],
)
def test_basis_mismatch_fails_closed(env: Path, tmp_path: Path, capsys, block: str) -> None:  # type: ignore[no-untyped-def]
    """AC-7: a ``basis`` that does not match the computed relation is exit 3."""
    code, out = _begin(capsys, _plan(tmp_path / "plan", block))
    assert code == 3, out
    assert "review_limits" in out
    assert not review_ledger.ledger_path("loop-x").exists()


@pytest.mark.parametrize(
    "block",
    [
        BLOCK_REPO.replace("  basis: repo\n", ""),
        BLOCK_REPO + "  extra: 1\n",
        BLOCK_REPO.replace("  basis: repo\n", "  plan_rounds: 3\n  basis: repo\n"),
        BLOCK_REPO.replace("  plan_rounds: 3", "    plan_rounds: 3"),
        BLOCK_REPO.replace("plan_rounds: 3", 'plan_rounds: "3"'),
        BLOCK_REPO.replace("plan_rounds: 3", "plan_rounds: 0"),
        BLOCK_REPO.replace("plan_rounds: 3", "plan_rounds: off"),
        BLOCK_REPO.replace("plan_rounds: 3", "plan_rounds: {a: 1}"),
        BLOCK_REPO.replace("schema: review-limits/1", "schema: review-limits/2"),
        BLOCK_REPO.replace("review_limits:\n", "review_limits: {}\n"),
        BLOCK_REPO + BLOCK_REPO,
    ],
    ids=[
        "missing-key", "extra-key", "duplicate-key", "deep-indent", "quoted", "zero",
        "rounds-off", "flow-map", "wrong-schema", "inline-value", "two-blocks",
    ],
)
def test_malformed_block_fails_closed(env: Path, tmp_path: Path, capsys, block: str) -> None:  # type: ignore[no-untyped-def]
    """AC-7: anything the strict line parser does not accept is exit 3."""
    code, out = _begin(capsys, _plan(tmp_path / "plan", block))
    assert code == 3, out
    assert "review_limits" in out


def test_loosened_block_needs_limits_check(env: Path, tmp_path: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """AC-7/AC-13: a loosened block opens a loop only when ``limits-check`` passes on that block."""
    calls: list[str] = []

    def refuse(plan: Path) -> tuple[int, str]:
        calls.append(plan.parent.name)
        return 1, "REFUSE: limits-check: policy_missing"

    monkeypatch.setattr(review_ledger, "run_limits_check", refuse)
    block = BLOCK_REPO.replace("execution_rounds: 6", "execution_rounds: 9").replace(
        "basis: repo", "basis: loosened"
    )
    code, out = _begin(capsys, _plan(tmp_path / "my-plan", block))
    assert code == 1, out
    assert "limits-check" in out
    assert calls == ["my-plan"]
    assert not review_ledger.ledger_path("loop-x").exists()

    monkeypatch.setattr(review_ledger, "run_limits_check", lambda plan: (0, "OK"))
    code, out = _begin(capsys, _plan(tmp_path / "my-plan", block))
    assert code == 1, out
    assert "not the block limits-check verified" in out
    assert not review_ledger.ledger_path("loop-x").exists()

    verified = review_ledger.load_plan_limits(tmp_path / "my-plan" / "implementation-plan.md")
    said = json.dumps({"result": "limits_verified", "review_limits": verified})
    monkeypatch.setattr(review_ledger, "run_limits_check", lambda plan: (0, said))
    code, out = _begin(capsys, _plan(tmp_path / "my-plan", block))
    assert code == 0, out
    assert _ledger()["round_budget"] == 9


# --- AC-8 ---------------------------------------------------------------------------------


def test_equal_task_block_is_accepted(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-8: the same block in the sibling ``task.md`` is accepted."""
    folder = tmp_path / "plan"
    _plan(folder, BLOCK_TIGHTENED.replace("  # a comment is allowed", ""), "task.md")
    code, out = _begin(capsys, _plan(folder, BLOCK_TIGHTENED))
    assert code == 0, out


def test_task_without_a_block_is_accepted(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-8: a sibling ``task.md`` without the block is not compared."""
    folder = tmp_path / "plan"
    _plan(folder, None, "task.md")
    code, out = _begin(capsys, _plan(folder, BLOCK_TIGHTENED))
    assert code == 0, out


def test_unequal_task_block_is_refused(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-8: a different block in the sibling ``task.md`` is exit 1."""
    folder = tmp_path / "plan"
    _plan(folder, BLOCK_TIGHTENED.replace("plan_rounds: 2", "plan_rounds: 1"), "task.md")
    code, out = _begin(capsys, _plan(folder, BLOCK_TIGHTENED))
    assert code == 1, out
    assert DIFFERS in out
    assert not review_ledger.ledger_path("loop-x").exists()


# --- AC-9 ---------------------------------------------------------------------------------


def test_tightening_flags_are_recorded(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-9: flags at or below the resolved values are accepted and listed."""
    code, out = _begin(
        capsys, _plan(tmp_path / "plan"), "execution", "loop-x",
        "--round-budget", "2", "--token-budget", "100",
    )
    assert code == 0, out
    ledger = _ledger()
    assert (ledger["round_budget"], ledger["token_budget"]) == (2, 100)
    assert ledger["limits_source"]["flags"] == ["round_budget", "token_budget"]


def test_flag_equal_to_the_resolved_value_is_accepted(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-9: equal is not looser."""
    code, out = _begin(capsys, _plan(tmp_path / "plan"), "execution", "loop-x", "--round-budget", "6")
    assert code == 0, out
    assert _ledger()["limits_source"]["flags"] == ["round_budget"]


@pytest.mark.parametrize(
    "flags,says",
    [
        (("--round-budget", "7"), "6"),
        (("--token-budget", "21000001"), "21,000,000"),
        (("--token-budget", "off"), "21,000,000"),
    ],
    ids=["rounds-looser", "tokens-looser", "off-against-a-number"],
)
def test_loosening_flag_is_refused(env: Path, tmp_path: Path, capsys, flags, says) -> None:  # type: ignore[no-untyped-def]
    """AC-9: a looser flag is exit 1, and the refusal names the resolved value and source."""
    code, out = _begin(capsys, _plan(tmp_path / "plan"), "execution", "loop-x", *flags)
    assert code == 1, out
    assert says in out
    assert "constants" in out
    assert not review_ledger.ledger_path("loop-x").exists()


def test_flag_applies_after_the_plan_block(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-9: the flag resolves against the plan block, not the repo file."""
    plan = _plan(tmp_path / "plan", BLOCK_TIGHTENED)
    code, out = _begin(capsys, plan, "execution", "loop-x", "--round-budget", "5")
    assert code == 1, out
    assert "4" in out and str(plan) in out


def test_token_flag_under_repo_off(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-9: under repo "off" a numeric flag tightens, and ``off`` equals the resolved value."""
    _repo_file(env, token_budgets="off")
    code, out = _begin(capsys, _plan(tmp_path / "plan"), "execution", "loop-a", "--token-budget", "100")
    assert code == 0, out
    assert _ledger("loop-a")["token_budget"] == 100
    code, out = _begin(capsys, _plan(tmp_path / "plan"), "execution", "loop-b", "--token-budget", "off")
    assert code == 0, out
    assert _ledger("loop-b")["token_budget"] == "off"


@pytest.mark.parametrize("flags", [("--round-budget", "0"), ("--token-budget", "0"), ("--token-budget", "x")])
def test_bad_flag_value_is_a_usage_error(env: Path, tmp_path: Path, capsys, flags) -> None:  # type: ignore[no-untyped-def]
    """AC-9: a flag that is not an integer >= 1 (or ``off``) is exit 2."""
    code, out = _begin(capsys, _plan(tmp_path / "plan"), "execution", "loop-x", *flags)
    assert code == 2, out


# --- AC-10 --------------------------------------------------------------------------------


def _off_loop(env: Path, tmp_path: Path, capsys, loop_id: str = "loop-off") -> None:  # type: ignore[no-untyped-def]
    _repo_file(env, token_budgets="off")
    code, out = _begin(capsys, _plan(tmp_path / "plan"), "execution", loop_id)
    assert code == 0, out


def test_off_loop_has_no_tokens_stop(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-10: 10^12 tokens of usage on an "off" loop raise no tokens stop."""
    _off_loop(env, tmp_path, capsys)
    _hand_edit("loop-off", rounds=[_round(1, 10**12)])
    ledger = review_ledger.load_ledger("loop-off")
    assert [kind for kind, _ in review_ledger.stops(ledger)] == []
    assert review_ledger.main(["state", "--loop-id", "loop-off"]) == 0
    out = capsys.readouterr().out
    assert "tokens     off (1,000,000,000,000 spent, not budgeted)" in out
    assert "NEXT ROUND: permitted" in out


def test_off_loop_reserve_does_not_divide(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-10: with nothing measured, the reserve of an "off" loop is not computed from "off"."""
    _off_loop(env, tmp_path, capsys)
    spent, reserve, budget = review_ledger.tokens_spent(review_ledger.load_ledger("loop-off"))
    assert (spent, budget) == (0, "off")
    assert reserve == 0


def test_off_loop_readout_says_off(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-10: the stop readout of an exhausted "off" loop prints the tokens line as off."""
    _off_loop(env, tmp_path, capsys)
    _hand_edit("loop-off", rounds=[_round(n, 10**9) for n in range(1, 7)])
    ledger = review_ledger.load_ledger("loop-off")
    assert [kind for kind, _ in review_ledger.stops(ledger)] == ["budget"]
    readout = review_ledger.stop_readout(ledger)
    assert "tokens      off (6,000,000,000 spent, not budgeted)" in readout
    assert "--tokens" not in readout


def test_numeric_budget_of_one_still_stops(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-10: the tokens stop still fires on a numeric budget."""
    code, out = _begin(capsys, _plan(tmp_path / "plan"), "execution", "loop-one", "--token-budget", "1")
    assert code == 0, out
    _hand_edit("loop-one", rounds=[_round(1, 5)])
    kinds = [kind for kind, _ in review_ledger.stops(review_ledger.load_ledger("loop-one"))]
    assert kinds == ["tokens"]


def test_continue_tokens_on_an_off_loop_is_refused(env: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-10: there is no token budget to lift, so ``continue --tokens`` is exit 1."""
    _off_loop(env, tmp_path, capsys)
    code, out = _continue(capsys, "loop-off", "--tokens", "5")
    assert code == 1, out
    assert "token budget is off for this loop; nothing to lift" in out
    assert review_ledger.load_ledger("loop-off")["grants"] == []
    code, out = _continue(capsys, "loop-off", "--rounds", "1")
    assert code == 0, out
    assert "tokens off" in out


@pytest.mark.parametrize("value", [0, None, -5, True, "on", 1.5])
def test_hand_edited_bad_budget_fails_closed(env: Path, tmp_path: Path, capsys, value) -> None:  # type: ignore[no-untyped-def]
    """AC-10: a ``token_budget`` that is neither an integer >= 1 nor "off" is exit 3."""
    code, out = _begin(capsys, _plan(tmp_path / "plan"))
    assert code == 0, out
    _hand_edit("loop-x", token_budget=value)
    assert review_ledger.main(["state", "--loop-id", "loop-x"]) == 3
    assert "token_budget" in capsys.readouterr().out
    assert review_ledger.main(["evaluate", "--loop-id", "loop-x"]) == 3


# --- AC-11 --------------------------------------------------------------------------------


def test_selftest_passes_with_at_least_115_arms(capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-11: every existing arm still passes, and the new arms bring the count to >= 115."""
    code = review_ledger.main(["selftest"])
    out = capsys.readouterr().out
    assert code == 0, out[-2000:]
    found = re.search(r"RESULT: (\d+) arm\(s\), 0 failure\(s\)", out)
    assert found, out[-2000:]
    assert int(found.group(1)) >= 115


# --- AC-12 --------------------------------------------------------------------------------

#: ``stops()`` of the legacy fixture below, computed by the ledger at e667fb6 (before this
#: change). The fixture has no ``limits_source`` and an integer ``token_budget``.
LEGACY_STOPS = [
    ("budget",
     "round budget exhausted: 3 round(s) used, 3 allowed (base 2 + 1 bought by continue). A "
     "named human may continue: continue --loop-id legacy-loop --rounds 1 --said \"<at least "
     "20 characters>\" --by <name> --at <ISO-8601>."),
    ("tokens",
     "tokens: 1,100 spent + 500 reserved for the next round > budget 1,000. The reserve is "
     "the last measured round's cost, so the loop stops before the round that would overrun, "
     "not after it. A named human may continue: continue --loop-id legacy-loop --tokens "
     "<extra> --said \"<at least 20 characters>\" --by <name> --at <ISO-8601>."),
]


def _legacy_ledger() -> dict:
    return {
        "schema_version": review_ledger.SCHEMA_VERSION,
        "loop_id": "legacy-loop",
        "review_mode": "execution",
        "round_budget": 2,
        "producer": "builder-x",
        "opened": "2026-10-01",
        "instrument_digest": review_ledger.instrument_digest(),
        "rounds": [_round(1, 600), _round(2, 500), _round(3, None)],
        "grants": [{"round": 3, "owner": "Pat",
                    "rationale": "legacy grant from before rounds were counted",
                    "granted": "2026-10-01T10:00:00"}],
        "mechanism_reliefs": [],
        "token_budget": 1000,
        "goal_anchor": "Bounded independent review of the legacy fixture",
        "ac_ids": ["AC-1"],
        "vocabulary_path": "x",
    }


def _write_legacy() -> None:
    path = review_ledger.ledger_path("legacy-loop")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_legacy_ledger(), indent=2) + "\n", encoding="utf-8")


def test_legacy_ledger_gives_the_same_stops(env: Path) -> None:
    """AC-12: a pre-change ledger loads and gives the stops it gave before the change."""
    _write_legacy()
    ledger = review_ledger.load_ledger("legacy-loop")
    assert "limits_source" not in ledger
    assert review_ledger.tokens_spent(ledger) == (1100, 500, 1000)
    assert [tuple(s) for s in review_ledger.stops(ledger)] == LEGACY_STOPS


def test_legacy_ledger_state_and_continue(env: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """AC-12: ``state`` marks a pre-change ledger, and ``continue`` works as before."""
    _write_legacy()
    assert review_ledger.main(["state", "--loop-id", "legacy-loop"]) == 0
    out = capsys.readouterr().out
    assert "limits: (pre-review-limits ledger)" in out
    assert "tokens     1,100/1,000 spent" in out
    code, out = _continue(capsys, "legacy-loop", "--rounds", "1", "--tokens", "1000")
    assert code == 0, out
    assert "lifted budget, tokens" in out
    ledger = review_ledger.load_ledger("legacy-loop")
    assert "limits_source" not in ledger
    assert review_ledger.stops(ledger) == []
