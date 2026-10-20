"""B-2 tests for ``tools/run_parameters.py`` (WP-3; AC-B.1 to AC-B.12, R§4.1 and R§4.8).

Every ``V2-`` vector of the design plan's ``vectors.yaml`` has at least one test whose name holds
``vec_<id>_``. The AC-B.13 tests (the closeout validator) are appended to
``tools/tests/run_parameters_fixtures/closeout_cases.py``. AC-B.14 (no regression: every existing test
file outside ``M7_EDITS`` is byte-unchanged) is checked by the Green regression-hash gate of
``red_green.ps1``, not by a test in this file.

The tests fix this command contract (EA-5):

* every verb prints one JSON object; exit 0 is success (a verified act, a written transaction),
  exit 1 a refusal or a non-authorizing result, exit 2 a usage error;
* a refusal prints ``{"result": "refused", "reason": <code>, "authorized": false, "failure": true}``
  and, for ``verify`` and ``reserve``, ``"effective"`` holds the fail-closed values (V-11);
* ``manual`` and ``legacy`` print ``result`` and ``reason`` equal to the code, ``authorized: false``
  and ``failure: false`` (the two non-failure codes);
* a verified act prints ``{"result": "verified", "authorized": true, "failure": false, "act",
  "plan", "fixture", "effective"}``.

Every fixture is built inside the test body (``bf.build``), so a missing component fails the test
at Red instead of erroring a fixture. Crash injection runs only in a child process.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest
import yaml

from tools.tests.run_parameters_fixtures import build_fixture as bf

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / bf.RUN_PARAMETERS_HOME / "schemas"
CRASH = "RUN_PARAMETERS_TEST_CRASH_AT"
CLOCK = "RUN_PARAMETERS_TEST_CLOCK"
LOCK_WAIT = "RUN_PARAMETERS_TEST_LOCK_WAIT_S"
CRASH_EXIT = 97
TXN_STEPS = ("after_data", "after_intent", "after_replace_1", "after_done")
INDEX_STEPS = (
    "index_lock",
    "index_copy",
    "index_before",
    "index_update",
    "index_after",
    "index_replace",
    "index_unlock",
)
FAIL_CLOSED = {
    "decisions": "human-all",
    "commit_plan": False,
    "exec_after_plan": False,
    "commit_exec": False,
    "push": "never",
}
SIGMA = {
    "decisions": "hdp",
    "commit_plan": True,
    "exec_after_plan": True,
    "commit_exec": True,
    "push": "never",
}
REASON_ORDER = (
    "disabled",
    "unsupported_harness",
    "capability",
    "schema",
    "legacy",
    "manual",
    "transcript_missing",
    "record",
    "chain",
    "no_offer",
    "duplicate_offer",
    "offer_schema",
    "digest",
    "consent",
    "binding",
    "not_granted",
    "scope",
    "store_missing",
    "store_mismatch",
    "store_malformed",
    "txn_pending",
    "stale_lock",
    "history_missing",
    "consumed",
    "revoked",
    "superseded",
    "expired",
)
VERBS = {
    "inspect",
    "verify",
    "reserve",
    "bind",
    "document",
    "revoke",
    "init",
    "status",
    "resolve",
    "final",
    "stop",
    "unlock",
    "repair",
    "audit",
}
HOLD = (
    "import sys, time\n"
    "from pathlib import Path\n"
    "from tools.run_parameters import writer_lock\n"
    "with writer_lock(Path(sys.argv[1]), session='fixture-holder'):\n"
    "    print('HELD', flush=True)\n"
    "    time.sleep(float(sys.argv[2]))\n"
    "print('RELEASED', flush=True)\n"
)

Result = tuple[int, dict[str, Any]]


# -- helpers -------------------------------------------------------------------------------


def _rp() -> ModuleType:
    """The module under test, imported inside a test body (a Red import error is a failure)."""
    return importlib.import_module("tools.run_parameters")


def _build(tmp_path: Path, name: str = "fx", **kw: Any) -> bf.Fixture:
    return bf.build(tmp_path / name, ROOT, **kw)


def _verify(
    fx: bf.Fixture,
    act: str,
    *,
    plan: str | None = None,
    op: str | None = None,
    repo: Path | None = None,
    env: Mapping[str, str | None] | None = None,
) -> Result:
    argv = ["verify", act, "--plan", plan or fx.plan]
    if op is not None:
        argv += ["--op", op]
    return fx.run(*argv, repo=repo, env=env)


def _reserve(fx: bf.Fixture, act: str, op: str, *, plan: str | None = None) -> Result:
    return fx.run("reserve", act, "--plan", plan or fx.plan, "--op", op)


def _refused(res: Result, reason: str, *, effective: bool = True) -> None:
    code, out = res
    assert out.get("reason") == reason, out
    assert code == 1, out
    assert out.get("result") == "refused", out
    assert out.get("authorized") is False, out
    assert out.get("failure") is True, out
    if effective:
        assert out.get("effective") == FAIL_CLOSED, out


def _non_authorizing(res: Result, kind: str) -> None:
    code, out = res
    assert (code, out.get("result"), out.get("reason")) == (1, kind, kind), out
    assert out.get("authorized") is False, out
    assert out.get("failure") is False, out


def _verified(res: Result) -> dict[str, Any]:
    code, out = res
    assert out.get("result") == "verified", out
    assert code == 0, out
    assert out.get("authorized") is True, out
    assert out.get("failure") is False, out
    return out


def _all_refused(
    fx: bf.Fixture, reason: str, *, plan: str | None = None, repo: Path | None = None
) -> None:
    for act in bf.ACTS:
        _refused(_verify(fx, act, plan=plan, repo=repo), reason)


def _init(
    fx: bf.Fixture, *, plan: str | None = None, repo: Path | None = None
) -> dict[str, Any]:
    code, out = fx.run("init", "--plan", plan or fx.plan, repo=repo)
    assert (code, out.get("result")) == (0, "initialized"), out
    return out


def _schema_valid(name: str, root: str, instance: object) -> None:
    schema = json.loads(
        (SCHEMAS / f"{name}.v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate({root: instance})


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    data = yaml.safe_load(text.split("---\n", 2)[1])
    assert isinstance(data, dict), path
    return data


def _set_status(fx: bf.Fixture, plan: str, status: str) -> None:
    path = fx.task_path(plan)
    text = path.read_text(encoding="utf-8")
    head, body = text.split("---\n", 2)[1:]
    data = yaml.safe_load(head)
    data["status"] = status
    path.write_bytes((bf.frontmatter(data) + body).encode("utf-8"))


def _mu(block: Mapping[str, Any]) -> str:
    return str(block["authorization"]["message_uuid"])


def _last_seq(fx: bf.Fixture) -> int:
    return max(int(line["seq"]) for line in fx.txn_lines())


def _raw_system(
    fx: bf.Fixture, uid: str, parent: str | None, *, session_id: str | None = None
) -> str:
    """A hand-built system record (cycles and foreign session ids need explicit fields)."""
    record = {
        "type": "system",
        "uuid": uid,
        "parentUuid": parent,
        "sessionId": session_id or fx.session,
        "isSidechain": False,
        "timestamp": bf.RECORD_TS,
        "cwd": fx.display,
        "version": "fixture",
        "subtype": "informational",
        "content": "",
        "level": "info",
    }
    return fx.add_record(record)


def _offer_case(
    fx: bf.Fixture,
    *,
    values: Mapping[str, Any] | None = None,
    lines: Sequence[str] | None = None,
    text: str | None = None,
    word: str | None = None,
    before_reply: Callable[[bf.Fixture], object] | None = None,
    reply: Callable[[bf.Fixture, str], str] | None = None,
    auth_over: Mapping[str, Any] | None = None,
    plan: str | None = None,
    carrier: bool = True,
) -> dict[str, Any]:
    """Write a presentation and a reply, build the block, and (by default) its carriers."""
    offered = dict(values) if values is not None else fx.offer()
    payload = list(lines) if lines is not None else fx.lines(offered)
    presentation = fx.add_assistant(
        text if text is not None else fx.offer_text(payload)
    )
    if before_reply is not None:
        before_reply(fx)
    response = word if word is not None else str(offered["accept"])
    message = reply(fx, response) if reply is not None else fx.add_human(response)
    auth = fx.authorization(
        offered,
        message_uuid=message,
        presentation_uuid=presentation,
        response=response,
        lines=payload,
    )
    auth.update(auth_over or {})
    block = fx.make_block(offered, auth)
    if carrier:
        fx.write_carrier(block, plan=plan)
    return block


def _replace_line(lines: Sequence[str], key: str, *new: str) -> list[str]:
    """Replace the payload line of ``key`` with ``new`` (no line removes it)."""
    out: list[str] = []
    hit = False
    for line in lines:
        if line.startswith(f"  {key}:"):
            out.extend(new)
            hit = True
        else:
            out.append(line)
    assert hit, key
    return out


def _final(fx: bf.Fixture, plan: str, n: int = 1, *, sealed: bool = True) -> Path:
    """A schema-valid ``final/<plan>/<n>.json``, written as the sealing writer would."""
    validator = {"exit": 0, "version": "fixture", "sha256": "a" * 64}
    receipt = {
        "schema": "final-receipt/1",
        "plan": plan,
        "run_id": "fixture-run",
        "repo_id": {},
        "branch": "main",
        "generation": n,
        "mode": "tree",
        "op": "none",
        "commit": "none",
        "tree": bf.git(fx.repo, "rev-parse", "HEAD^{tree}"),
        "read_set": [],
        "validators": {"closeout": validator, "preflight": validator},
        "publication_audit": {},
        "predecessor": "none" if n == 1 else n - 1,
        "sealed": sealed,
        "seal": {"path": f"final/{plan}/{n}.seal", "sha256": "b" * 64}
        if sealed
        else "none",
        "ts": bf.FIXTURE_CLOCK,
    }
    _schema_valid("final", "final-receipt", receipt)
    path = fx.store / "final" / plan / f"{n}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def _lock_body(fx: bf.Fixture, token: str | None = None) -> dict[str, Any]:
    body = {
        "pid": fx.dead_pid(),
        "pid_start": "fixture-start",
        "host": socket.gethostname(),
        "session": fx.session,
        "token": token or uuid.uuid4().hex,
        "ts": bf.FIXTURE_CLOCK,
    }
    _schema_valid("store", "run-parameters-store", {"lock": body})
    return body


def _stale_lock(fx: bf.Fixture, token: str | None = None) -> dict[str, Any]:
    """A ``store.lock`` whose owner has exited."""
    body = _lock_body(fx, token)
    (fx.store / "store.lock").write_text(json.dumps(body) + "\n", encoding="utf-8")
    return body


def _unlock(fx: bf.Fixture) -> None:
    """The human-run unlock of a crashed writer's lock (no-op without a lock)."""
    lock = fx.store / "store.lock"
    if not lock.exists():
        return
    token = json.loads(lock.read_text(encoding="utf-8"))["token"]
    record = fx.add_human("unlock the run-parameters store")
    code, out = fx.run(
        "unlock", "--expect", token, "--session", fx.session, "--message", record
    )
    assert (code, out.get("result")) == (0, "unlocked"), out


def _holder(fx: bf.Fixture, seconds: float) -> subprocess.Popen[str]:
    """A child process that holds the writer lock for ``seconds``; returns once it holds it."""
    proc = subprocess.Popen(  # noqa: S603 - fixed argv
        [sys.executable, "-c", HOLD, str(fx.repo), str(seconds)],
        cwd=fx.source,
        env=fx.env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdout is not None
    first = proc.stdout.readline().strip()
    if first != "HELD":
        proc.kill()
        _, err = proc.communicate(timeout=30)
        raise AssertionError(f"lock holder did not start: {first!r} {err}")
    return proc


def _crash(fx: bf.Fixture, step: str, *argv: str) -> None:
    code, out, err = fx.run_subprocess(*argv, env={CRASH: step})
    assert code == CRASH_EXIT, (step, code, out, err)


def _pending_txns(fx: bf.Fixture) -> set[str]:
    lines = fx.txn_lines()
    intents = {str(line["txn"]) for line in lines if line.get("intent")}
    dones = {str(line["txn"]) for line in lines if line.get("done")}
    return intents - dones


def _human_text(fx: bf.Fixture, uid: str) -> str:
    for line in fx.transcript.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("uuid") == uid:
            return str(record["message"]["content"])
    raise AssertionError(uid)


# -- module surface ------------------------------------------------------------------------


@pytest.mark.unit
def test_reason_codes_follow_the_rule_order() -> None:
    """AC-B.3: ``REASON_CODES`` is complete and in the R§4.1 :249 precedence order."""
    assert tuple(_rp().REASON_CODES) == REASON_ORDER


def test_vec_v2_049_entry_points_and_help(tmp_path: Path) -> None:
    """AC-B.3: the fourteen entry points exist; ``--help`` exits 0; an unknown verb exits 2."""
    assert set(_rp().RP_VERBS) == VERBS
    assert len(_rp().RP_VERBS) == 14
    fx = _build(tmp_path)
    for verb in sorted(VERBS):
        code, _, err = fx.run_subprocess(verb, "--help")
        assert code == 0, (verb, err)
    code, _, _ = fx.run_subprocess("no-such-verb")
    assert code == 2


def test_vec_v2_049_verify_writes_nothing(tmp_path: Path) -> None:
    """AC-B.3: ``verify`` and ``inspect`` leave every store file and config key byte-identical."""
    fx = _build(tmp_path)
    _init(fx)
    assert _reserve(fx, "exec_start", "op-1")[0] == 0
    before = fx.store_snapshot()
    txn_before = (fx.store / "txn.jsonl").read_bytes()
    for act in bf.ACTS:
        _verify(fx, act)
        _verify(fx, act, op="op-1")
    fx.run("inspect", "--plan", fx.plan)
    assert fx.store_snapshot() == before
    assert (fx.store / "txn.jsonl").read_bytes() == txn_before


# -- V-A activation ------------------------------------------------------------------------


def test_vec_v2_001_disabled_without_policy(tmp_path: Path) -> None:
    """AC-B.3: no policy file → ``disabled`` for every act and for ``inspect``."""
    fx = _build(tmp_path)
    fx.policy_path.unlink()
    _all_refused(fx, "disabled")
    _refused(fx.run("inspect", "--plan", fx.plan), "disabled", effective=False)
    code, out = fx.run("status", "--json")
    assert code == 0, out
    assert out.get("enabled") is False, out


def test_vec_v2_002_unsupported_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-B.3: a transcript adapter other than ``claude-code`` → ``unsupported_harness``."""
    fx = _build(tmp_path)
    monkeypatch.setattr(_rp(), "TRANSCRIPT_ADAPTER", "none")
    _all_refused(fx, "unsupported_harness")


def test_vec_v2_003_capability_off(tmp_path: Path) -> None:
    """AC-B.3: an act whose policy capability is ``off`` → ``capability``; inspect skips it."""
    fx = _build(tmp_path)
    caps = bf.capabilities_for("A")
    caps["plan_commit"] = "off"
    fx.write_policy(capabilities=caps)
    fx.commit("fixture: plan_commit off")
    _init(fx)
    _refused(_verify(fx, "plan_commit"), "capability")
    _verified(_verify(fx, "exec_start"))
    code, out = fx.run("inspect", "--plan", fx.plan)
    assert (code, out.get("result")) == (0, "inspected"), out


def test_activation_component_drift_disables(tmp_path: Path) -> None:
    """AC-B.3: a component whose bytes differ from the policy digest → ``disabled``."""
    fx = _build(tmp_path)
    with (fx.repo / "tools" / "run_parameters.py").open(
        "a", encoding="utf-8"
    ) as handle:
        handle.write("\n# drift\n")
    _refused(_verify(fx, "exec_start"), "disabled")
    code, out = fx.run("status", "--json")
    assert code == 0, out
    assert out.get("enabled") is False, out
    assert out.get("reason") == "component_drift:tools/run_parameters.py", out


# -- V-0 schema, manual and legacy ---------------------------------------------------------


@pytest.mark.parametrize(
    "auth",
    [
        pytest.param({"schema": "authorization/2"}, id="unknown-schema"),
        pytest.param({"schema": "manual", "note": "x"}, id="manual-second-key"),
    ],
)
def test_vec_v2_004_schema(tmp_path: Path, auth: dict[str, Any]) -> None:
    """AC-B.3: an unknown authorization schema, or a manual block with a second key → ``schema``."""
    fx = _build(tmp_path)
    block = dict(fx.block)
    if auth["schema"] == "manual":
        block["authorization"] = dict(auth)
    else:
        block["authorization"] = {**fx.block["authorization"], **auth}
    fx.write_carrier(block, grouping_line=False)
    _all_refused(fx, "schema")


@pytest.mark.parametrize(
    ("where", "key", "value"),
    [
        pytest.param(
            "auth", "date", "2026-02-30T00:00:00Z", id="calendar-invalid-date"
        ),
        pytest.param("auth", "date", "2026-10-17t14:34:40z", id="lower-case-date"),
        pytest.param("auth", "date", "2026-10-17T14:34:40.5Z", id="fractional-seconds"),
        pytest.param("auth", "date", "2026-10-17T14:34:40+00:00", id="offset-not-z"),
        pytest.param("auth", "expires", "None", id="sentinel-case"),
        pytest.param("block", "commit_plan", "true", id="string-true"),
        pytest.param("block", "colour", "blue", id="unknown-key"),
        pytest.param("project", "", "/", id="project-trailing-slash"),
        pytest.param("plan", "", "2026-10-17-Fixture_Plan", id="plan-slug"),
    ],
)
def test_projection_typing_rejects(
    tmp_path: Path, where: str, key: str, value: str
) -> None:
    """AC-B.1: the typed projection (P-1 to P-5): strict dates, sentinels, booleans, slugs, keys."""
    fx = _build(tmp_path)
    block = json.loads(json.dumps(fx.block))
    auth = block["authorization"]
    if where == "auth":
        auth[key] = value
    elif where == "block":
        block[key] = value
    elif where == "project":
        auth["project"] = auth["project"] + value
    else:
        auth["scope"]["plan"] = value
    fx.write_carrier(block, grouping_line=False)
    _refused(_verify(fx, "exec_start"), "schema")


def test_projection_duplicate_key_in_task_block(tmp_path: Path) -> None:
    """AC-B.1: a duplicate key in the task.md block → ``schema`` (YAML loaders hide it)."""
    fx = _build(tmp_path)
    path = fx.task_path()
    text = path.read_text(encoding="utf-8")
    assert "\n  decisions: hdp\n" in text
    path.write_bytes(
        text.replace(
            "\n  decisions: hdp\n", "\n  decisions: hdp\n  decisions: hdp\n", 1
        ).encode()
    )
    _refused(_verify(fx, "exec_start"), "schema")


@pytest.mark.parametrize("branch", ["Main", "no-such-branch"])
def test_projection_branch_exists_by_bytes(tmp_path: Path, branch: str) -> None:
    """AC-B.1: ``scope.branch`` names ``refs/heads/<branch>`` by bytes (P-4); a miss → ``scope``."""
    fx = _build(tmp_path)
    _offer_case(fx, values=fx.offer(branch=branch))
    _refused(_verify(fx, "exec_start"), "scope")


def test_vec_v2_005_legacy(tmp_path: Path) -> None:
    """AC-B.3: an ``authorization/1-legacy`` reference returns ``legacy`` for every act."""
    fx = _build(tmp_path)
    auth = fx.block["authorization"]
    legacy = {
        "schema": "authorization/1-legacy",
        "source": "USER_EXPLICIT",
        "project": auth["project"],
        "session": auth["session"],
        "message_uuid": auth["message_uuid"],
        "presentation_uuid": auth["presentation_uuid"],
        "offer_digest": auth["offer_digest"],
        "date": auth["date"],
        "response": auth["response"],
        "scope": {"plan": "none", "grouping": "none", "branch": "none"},
        "grants": ["ruling"],
        "standing": False,
        "supersedes": "none",
    }
    _schema_valid("authorization", "authorization", legacy)
    fx.write_carrier({**fx.block, "authorization": legacy})
    for act in bf.ACTS:
        _non_authorizing(_verify(fx, act), "legacy")
    _non_authorizing(_reserve(fx, "exec_start", "op-1"), "legacy")
    assert not fx.store.exists()


def test_vec_v2_006_manual(tmp_path: Path) -> None:
    """AC-B.4: ``verify`` and ``reserve`` on a manual block return ``manual`` and grant nothing."""
    fx = _build(tmp_path)
    fx.write_carrier({**fx.block, "authorization": {"schema": "manual"}})
    for act in bf.ACTS:
        _non_authorizing(_verify(fx, act), "manual")
    _non_authorizing(_reserve(fx, "exec_start", "op-1"), "manual")
    assert not fx.store.exists()


def test_vec_v2_007_inspect_manual_block(tmp_path: Path) -> None:
    """AC-B.4: ``inspect`` on a manual block → exit 0, ``manual``, store absent, before V-A."""
    fx = _build(tmp_path)
    path = fx.write_block_file(
        {**fx.block, "authorization": {"schema": "manual"}}, "manual"
    )
    code, out = fx.run("inspect", "--block", str(path))
    assert (code, out.get("result")) == (0, "manual"), out
    assert not fx.store.exists()
    fx.policy_path.unlink()
    code, out = fx.run("inspect", "--block", str(path))
    assert (code, out.get("result")) == (0, "manual"), out
    assert not fx.store.exists()


def test_vec_v2_008_inspect_reports_consumption(tmp_path: Path) -> None:
    """AC-B.4: ``inspect`` reports a fully consumed grant (exit 0) and writes nothing."""
    fx = _build(tmp_path)
    _init(fx)
    for n, act in enumerate(bf.ACTS, start=1):
        code, out = _reserve(fx, act, f"op-{n}")
        assert (code, out.get("result")) == (0, "reserved"), out
    before = fx.store_snapshot()
    code, out = fx.run("inspect", "--plan", fx.plan)
    assert (code, out.get("result")) == (0, "inspected"), out
    assert sorted(out["report"]["consumed"]) == list(bf.ACTS), out
    assert fx.store_snapshot() == before


# -- V-1 transcript and V-2 record ---------------------------------------------------------


@pytest.mark.parametrize("how", ["deleted", "rotated"])
def test_vec_v2_009_transcript_missing(tmp_path: Path, how: str) -> None:
    """AC-B.3: a missing or rotated transcript → ``transcript_missing``; no quote cache."""
    fx = _build(tmp_path)
    if how == "deleted":
        fx.transcript.unlink()
    else:
        fx.transcript.rename(fx.transcript.with_suffix(".jsonl.1"))
    _all_refused(fx, "transcript_missing")


def test_vec_v2_010_other_project_never_searched(tmp_path: Path) -> None:
    """AC-B.3: a transcript in another project's folder is never searched."""
    fx = _build(tmp_path)
    other = fx.config_dir / "projects" / "other-project"
    other.mkdir(parents=True)
    shutil.move(str(fx.transcript), str(other / fx.transcript.name))
    _all_refused(fx, "transcript_missing")


def test_vec_v2_011_quote_only_in_tool_result(tmp_path: Path) -> None:
    """AC-B.3: the accepting words exist only inside a tool result → ``record``."""
    fx = _build(tmp_path)
    _offer_case(fx, reply=lambda f, w: f.add_tool_result(w))
    _refused(_verify(fx, "exec_start"), "record")


def test_vec_v2_012_hook_frame(tmp_path: Path) -> None:
    """AC-B.3: ``message_uuid`` names a hook frame (``isMeta``) → ``record``."""
    fx = _build(tmp_path)
    _offer_case(fx, reply=lambda f, w: f.add_hook_frame(w))
    _refused(_verify(fx, "exec_start"), "record")


def test_vec_v2_013_compact_summary(tmp_path: Path) -> None:
    """AC-B.3: ``message_uuid`` names a compact summary record → ``record``."""
    fx = _build(tmp_path)
    _offer_case(fx, reply=lambda f, w: f.add_compact_summary(w))
    _refused(_verify(fx, "exec_start"), "record")


def test_vec_v2_014_sidechain(tmp_path: Path) -> None:
    """AC-B.3: ``message_uuid`` names a sidechain record → ``record``."""
    fx = _build(tmp_path)
    _offer_case(fx, reply=lambda f, w: f.add_human(w, isSidechain=True))
    _refused(_verify(fx, "exec_start"), "record")


def test_vec_v2_015_other_session_id(tmp_path: Path) -> None:
    """AC-B.3: the record's ``sessionId`` is another session → ``record``."""
    fx = _build(tmp_path)
    _offer_case(fx, reply=lambda f, w: f.add_human(w, sessionId=str(uuid.uuid4())))
    _refused(_verify(fx, "exec_start"), "record")


def test_vec_v2_016_assistant_message(tmp_path: Path) -> None:
    """AC-B.3: ``message_uuid`` names an assistant record → ``record``."""
    fx = _build(tmp_path)
    _offer_case(fx, reply=lambda f, w: f.add_assistant(w))
    _refused(_verify(fx, "exec_start"), "record")


@pytest.mark.parametrize("case", ["parent-outside-file", "duplicate-uuid"])
def test_record_parent_outside_file_and_duplicate_uuid(
    tmp_path: Path, case: str
) -> None:
    """AC-B.3: V-2's own rejections: a parent outside the file; a uuid that occurs twice."""
    fx = _build(tmp_path)

    def reply(f: bf.Fixture, word: str) -> str:
        if case == "parent-outside-file":
            return f.add_human(word, parent=str(uuid.uuid4()))
        uid = f.add_human(word)
        line = f.transcript.read_text(encoding="utf-8").splitlines()[-1]
        f.add_record(json.loads(line))
        return uid

    _offer_case(fx, reply=reply)
    _refused(_verify(fx, "exec_start"), "record")


def _sdk_human(f: bf.Fixture, word: str, **over: Any) -> str:
    """The SDK shape of a typed turn (the VSCode extension): one text block, ``sdk`` source."""
    record: dict[str, Any] = {
        "promptSource": "sdk",
        "message": {"role": "user", "content": [{"type": "text", "text": word}]},
    }
    record.update(over)
    return f.add_human(word, **record)


def test_record_text_block_content_verifies(tmp_path: Path) -> None:
    """V-2 (``is_human_entry``): a typed turn whose content is text blocks verifies (EA-62)."""
    fx = _build(tmp_path)
    _offer_case(fx, reply=_sdk_human)
    _init(fx)
    _verified(_verify(fx, "exec_start"))


@pytest.mark.parametrize(
    "over",
    [
        {"origin": {"kind": "task-notification"}},
        {"origin": None},
        {"turnOrigin": "task_notification"},
        {"promptSource": "system"},
        {"promptId": ""},
    ],
    ids=["task_notification", "no_origin", "turn_origin", "prompt_source", "prompt_id"],
)
@pytest.mark.parametrize("shape", ["string", "text_blocks"])
def test_record_that_is_not_a_typed_turn(
    tmp_path: Path, over: dict[str, Any], shape: str
) -> None:
    """V-2: a record that fails ``is_human_entry`` or ``is_typed_turn`` → ``record`` (EA-62)."""
    fx = _build(tmp_path)

    def reply(f: bf.Fixture, word: str) -> str:
        if shape == "string":
            return f.add_human(word, **over)
        return _sdk_human(f, word, **over)

    _offer_case(fx, reply=reply)
    _refused(_verify(fx, "exec_start"), "record")


@pytest.mark.parametrize(
    "blocks",
    [
        [{"type": "image", "source": {"type": "base64", "data": ""}}],
        [{"type": "tool_result", "tool_use_id": "toolu_fixture", "content": "x"}],
        [],
    ],
    ids=["image", "tool_result", "empty"],
)
def test_record_with_a_block_that_is_not_text(
    tmp_path: Path, blocks: list[dict[str, object]]
) -> None:
    """V-2: content with any block other than text, or no block, → ``record`` (EA-62)."""
    fx = _build(tmp_path)

    def reply(f: bf.Fixture, word: str) -> str:
        content = [{"type": "text", "text": word}, *blocks] if blocks else []
        return _sdk_human(f, word, message={"role": "user", "content": content})

    _offer_case(fx, reply=reply)
    _refused(_verify(fx, "exec_start"), "record")


def test_typed_human_text_reads_text_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``typed_human_text`` joins the text blocks of an SDK typed turn (E17, EA-62)."""
    fx = _build(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(fx.config_dir))
    uid = fx.add_human(
        "proceed",
        promptSource="sdk",
        message={
            "role": "user",
            "content": [
                {"type": "text", "text": "proceed"},
                {"type": "text", "text": "now"},
            ],
        },
    )
    assert _rp().typed_human_text(fx.repo, fx.session, uid) == "proceed\nnow"
    notice = fx.add_human("proceed", origin={"kind": "task-notification"})
    assert _rp().typed_human_text(fx.repo, fx.session, notice) is None


# -- V-3R chain ----------------------------------------------------------------------------


def test_vec_v2_017_older_presentation(tmp_path: Path) -> None:
    """AC-B.3: the recorded presentation is older than the nearest assistant record → ``chain``."""
    fx = _build(tmp_path)
    newer = fx.offer_text(fx.lines(fx.offer()))
    _offer_case(fx, before_reply=lambda f: f.add_assistant(newer))
    _refused(_verify(fx, "exec_start"), "chain")


def _chain_user(fx: bf.Fixture) -> None:
    fx.add_human("an interjection")


def _chain_boundary(fx: bf.Fixture) -> None:
    fx.add_system("compact_boundary")


def _chain_cycle(fx: bf.Fixture) -> None:
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    _raw_system(fx, first, second)
    _raw_system(fx, second, first)


def _chain_missing_parent(fx: bf.Fixture) -> None:
    _raw_system(fx, str(uuid.uuid4()), str(uuid.uuid4()))


def _chain_five_passed(fx: bf.Fixture) -> None:
    for _ in range(5):
        fx.add_system()


def _chain_other_session(fx: bf.Fixture) -> None:
    last = fx._last.get(fx.session)
    _raw_system(fx, str(uuid.uuid4()), last, session_id=str(uuid.uuid4()))


@pytest.mark.parametrize(
    "between",
    [
        pytest.param(_chain_user, id="user-record"),
        pytest.param(_chain_boundary, id="compact-boundary"),
        pytest.param(_chain_cycle, id="cycle"),
        pytest.param(_chain_missing_parent, id="missing-parent"),
        pytest.param(_chain_five_passed, id="five-passed-over"),
        pytest.param(_chain_other_session, id="other-session"),
    ],
)
def test_vec_v2_018_chain_walk(
    tmp_path: Path, between: Callable[[bf.Fixture], None]
) -> None:
    """AC-B.3: the parent walk meets a user record, a boundary, a cycle or a bad record → ``chain``."""
    fx = _build(tmp_path)
    _offer_case(fx, before_reply=between)
    _refused(_verify(fx, "exec_start"), "chain")


# -- O-1f fences and O-1 shape -------------------------------------------------------------


def _payload(fx: bf.Fixture) -> list[str]:
    return fx.lines(fx.offer())


@pytest.mark.parametrize(
    ("fence", "close", "indent"),
    [
        pytest.param("```yaml", "```", "  ", id="indented"),
        pytest.param("````yaml", "````", "", id="four-backticks"),
        pytest.param("~~~yaml", "~~~", "", id="tilde"),
    ],
)
def test_vec_v2_019_fence_not_at_column_zero(
    tmp_path: Path, fence: str, close: str, indent: str
) -> None:
    """AC-B.2: an indented, longer or tilde fence is ordinary text → ``no_offer``."""
    fx = _build(tmp_path)
    lines = _payload(fx)
    text = "\n".join(
        [
            "Offer:",
            "",
            indent + fence,
            *(indent + line for line in lines),
            indent + close,
        ]
    )
    _offer_case(fx, lines=lines, text=text)
    _refused(_verify(fx, "exec_start"), "no_offer")


def test_vec_v2_020_quoted_fence(tmp_path: Path) -> None:
    """AC-B.2: a quoted (``> ```) fence is ordinary text → ``no_offer``."""
    fx = _build(tmp_path)
    lines = _payload(fx)
    text = "\n".join(
        ["Offer:", "", "> ```yaml", *(f"> {line}" for line in lines), "> ```"]
    )
    _offer_case(fx, lines=lines, text=text)
    _refused(_verify(fx, "exec_start"), "no_offer")


@pytest.mark.parametrize("case", ["table-cell", "unfenced", "list-nested"])
def test_vec_v2_021_pseudo_offer(tmp_path: Path, case: str) -> None:
    """AC-B.2: a table-cell, unfenced or list-nested pseudo-offer is ordinary text → ``no_offer``."""
    fx = _build(tmp_path)
    lines = _payload(fx)
    if case == "table-cell":
        text = "| offer | ```yaml " + " ".join(lines) + " ``` |"
    elif case == "unfenced":
        text = "\n".join(["Offer:", "", *lines])
    else:
        text = "\n".join(["- the offer", "- ```yaml", *lines, "- ```"])
    _offer_case(fx, lines=lines, text=text)
    _refused(_verify(fx, "exec_start"), "no_offer")


@pytest.mark.parametrize(
    "second",
    [
        pytest.param("```\nprint('a code sample')\n```", id="bare-fence"),
        pytest.param("```yaml\nkey: value\n```", id="yaml-non-offer"),
    ],
)
def test_vec_v2_022_second_fenced_block(tmp_path: Path, second: str) -> None:
    """AC-B.2: an offer plus a second fenced block of any kind → ``duplicate_offer``."""
    fx = _build(tmp_path)
    lines = _payload(fx)
    _offer_case(fx, lines=lines, text=fx.offer_text(lines) + "\n\n" + second)
    _refused(_verify(fx, "exec_start"), "duplicate_offer")


def test_vec_v2_023_two_offers(tmp_path: Path) -> None:
    """AC-B.2: two offers in one presentation → ``duplicate_offer``."""
    fx = _build(tmp_path)
    lines = _payload(fx)
    _offer_case(
        fx, lines=lines, text=fx.offer_text(lines) + "\n\n" + fx.offer_text(lines)
    )
    _refused(_verify(fx, "exec_start"), "duplicate_offer")


# -- O-1a payload grammar ------------------------------------------------------------------


def _scope_line(fx: bf.Fixture, grouping: str) -> str:
    return f"  scope: {{plan: {fx.plan}, grouping: {grouping}, branch: main}}"


O1A_CASES: dict[str, Callable[[bf.Fixture, list[str]], list[str]]] = {
    "quoted-true": lambda fx, L: _replace_line(
        L, "commit_plan", '  commit_plan: "true"'
    ),
    "tab": lambda fx, L: _replace_line(L, "commit_plan", "  commit_plan:\ttrue"),
    "trailing-space": lambda fx, L: _replace_line(
        L, "commit_plan", "  commit_plan: true "
    ),
    "no-space-after-colon": lambda fx, L: _replace_line(
        L, "commit_plan", "  commit_plan:true"
    ),
    "empty-value": lambda fx, L: _replace_line(L, "commit_plan", "  commit_plan:"),
    "unknown-key": lambda fx, L: [*L, "  colour: blue"],
    "missing-key": lambda fx, L: _replace_line(L, "push"),
    "duplicate-key": lambda fx, L: [*L, "  decisions: hdp"],
    "anchor": lambda fx, L: _replace_line(L, "decisions", "  decisions: &d hdp"),
    "alias": lambda fx, L: _replace_line(L, "push", "  push: *p"),
    "merge-key": lambda fx, L: [*L, "  <<: {decisions: hdp}"],
    "tag": lambda fx, L: _replace_line(L, "push", "  push: !!str never"),
    "document-start": lambda fx, L: [*L, "---"],
    "document-end": lambda fx, L: [*L, "..."],
    "second-document": lambda fx, L: [*L, "---", "run-parameters-offer:", *L[1:]],
    "block-scalar": lambda fx, L: _replace_line(
        L, "decisions", "  decisions: |", "    hdp"
    ),
    "block-list": lambda fx, L: _replace_line(
        L, "grants", "  grants:", *(f"    - {act}" for act in bf.ACTS)
    ),
    "nested-mapping": lambda fx, L: _replace_line(
        L,
        "scope",
        "  scope:",
        f"    plan: {fx.plan}",
        f"    grouping: {fx.grouping}",
        "    branch: main",
    ),
    "non-ascii-key": lambda fx, L: _replace_line(L, "decisions", "  décisions: hdp"),
    "backtick-payload-line": lambda fx, L: [L[0], "```x", *L[1:]],
    "root-trailing-space": lambda fx, L: ["run-parameters-offer: ", *L[1:]],
    "bad-grouping-slug": lambda fx, L: _replace_line(
        L, "scope", _scope_line(fx, "Bad_Slug")
    ),
    "calendar-invalid-expires": lambda fx, L: _replace_line(
        L, "expires", "  expires: 2026-02-30"
    ),
}


@pytest.mark.parametrize("case", sorted(O1A_CASES))
def test_vec_v2_024_offer_schema(tmp_path: Path, case: str) -> None:
    """AC-B.2: a quoted ``"true"`` and one case per O-1a reject clause → ``offer_schema``."""
    fx = _build(tmp_path)
    lines = O1A_CASES[case](fx, _payload(fx))
    _offer_case(fx, lines=lines)
    _refused(_verify(fx, "exec_start"), "offer_schema")


# -- positives: P-1 to P-5 normal forms ----------------------------------------------------


@pytest.mark.parametrize("act", bf.ACTS)
def test_vec_v2_025_default_block_verifies(tmp_path: Path, act: str) -> None:
    """AC-B.1: the built default block verifies for each act after ``init``."""
    fx = _build(tmp_path)
    _init(fx)
    out = _verified(_verify(fx, act))
    assert (out.get("act"), out.get("plan")) == (act, fx.plan), out


def test_vec_v2_025_hash_inside_quotes_is_text(tmp_path: Path) -> None:
    """AC-B.2: a ``#`` inside a quoted project path is text (the repo name holds `` #``)."""
    fx = _build(tmp_path, repo_name="re #po")
    values = fx.offer()
    lines = _replace_line(fx.lines(values), "project", f'  project: "{fx.display}"')
    _offer_case(fx, values=values, lines=lines)
    _init(fx)
    _verified(_verify(fx, "exec_start"))


def test_vec_v2_025_trailing_comment(tmp_path: Path) -> None:
    """AC-B.2: a plain scalar ends at the first `` #``; the comment is not part of the value."""
    fx = _build(tmp_path)
    values = fx.offer()
    lines = _replace_line(
        fx.lines(values), "decisions", "  decisions: hdp # the default"
    )
    _offer_case(fx, values=values, lines=lines)
    _init(fx)
    _verified(_verify(fx, "exec_start"))


def test_vec_v2_025_self_contained_form(tmp_path: Path) -> None:
    """AC-B.1: V-3S: the human record holds the invocation line and the offer; no accept word."""
    fx = _build(tmp_path)
    values = fx.offer()
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
    _init(fx)
    _verified(_verify(fx, "exec_start"))


def test_vec_v2_025_standing_grant(tmp_path: Path) -> None:
    """AC-B.1: a standing grant for two members verifies for each member (sorted ``members``)."""
    fx = _build(tmp_path)
    values = fx.standing_offer([bf.PLAN_B, bf.PLAN])
    block = _offer_case(fx, values=values, carrier=False)
    _schema_valid("authorization", "authorization", block["authorization"])
    fx.write_carrier(block, plan=bf.PLAN)
    fx.write_carrier(block, plan=bf.PLAN_B)
    _init(fx)
    _verified(_verify(fx, "exec_start", plan=bf.PLAN))
    _verified(_verify(fx, "exec_start", plan=bf.PLAN_B))


def test_vec_v2_025_four_passed_over_records(tmp_path: Path) -> None:
    """AC-B.3: up to four system or attachment records may be passed over (V-3R)."""
    fx = _build(tmp_path)

    def between(f: bf.Fixture) -> None:
        f.add_system()
        f.add_attachment()
        f.add_system()
        f.add_attachment()

    _offer_case(fx, before_reply=between)
    _init(fx)
    _verified(_verify(fx, "exec_start"))


# -- V-4 digest and V-5 consent ------------------------------------------------------------


def test_vec_v2_026_wrong_digest(tmp_path: Path) -> None:
    """AC-B.3: ``offer_digest`` differs from the O-3 digest → ``digest``."""
    fx = _build(tmp_path)
    _offer_case(fx, auth_over={"offer_digest": "sha256:" + "0" * 64})
    _refused(_verify(fx, "exec_start"), "digest")


def test_vec_v2_027_do_not_proceed(tmp_path: Path) -> None:
    """AC-B.3: the reply "do not proceed" → ``consent``."""
    fx = _build(tmp_path)
    _offer_case(fx, word="do not proceed")
    _refused(_verify(fx, "exec_start"), "consent")


@pytest.mark.parametrize("word", ["ok proceed", "proceed with the plan"])
def test_vec_v2_028_substring_never_verifies(tmp_path: Path, word: str) -> None:
    """AC-B.3: a reply that only contains the accept word → ``consent``."""
    fx = _build(tmp_path)
    _offer_case(fx, word=word)
    _refused(_verify(fx, "exec_start"), "consent")


# -- V-6 binding and inheritance; V-6a act -------------------------------------------------


def test_vec_v2_029_task_value_differs(tmp_path: Path) -> None:
    """AC-B.5: a task.md value that differs from the offer, with no tightening record → ``binding``."""
    fx = _build(tmp_path)
    fx.write_carrier(fx.block, task_block={**fx.block, "commit_exec": False})
    _all_refused(fx, "binding")


@pytest.mark.parametrize("case", ["loosened", "loosened-below-plan"])
def test_vec_v2_030_lower_carrier_loosens(tmp_path: Path, case: str) -> None:
    """AC-B.5: a lower carrier that loosens without a new reference → ``binding``."""
    fx = _build(tmp_path)
    if case == "loosened":
        block = _offer_case(fx, values=fx.offer(commit_exec=False), carrier=False)
        fx.write_carrier({**block, "commit_exec": True})
    else:
        plan_block = {**fx.block, "commit_exec": False, "tightened_from": "grouping"}
        fx.write_carrier(
            plan_block, task_block=dict(fx.block), grouping_values=fx.block
        )
    _refused(_verify(fx, "exec_start"), "binding")


@pytest.mark.parametrize(
    "grants",
    [
        pytest.param(["ruling"], id="ruling"),
        pytest.param(["plan_commit", "exec_start"], id="unsorted"),
    ],
)
def test_vec_v2_031_grants_outside_the_acts(tmp_path: Path, grants: list[str]) -> None:
    """AC-B.3: ``grants: [ruling]`` (or an unsorted list) fails ``binding`` for every act (V-6a)."""
    fx = _build(tmp_path)
    block = json.loads(json.dumps(fx.block))
    block["authorization"]["grants"] = grants
    fx.write_carrier(block)
    _all_refused(fx, "binding")


def test_vec_v2_032_grouping_line_changed_after_start(tmp_path: Path) -> None:
    """AC-B.5: the grouping line changed after the session started → ``binding``."""
    fx = _build(tmp_path)
    _init(fx)
    code, out = fx.run("bind", "--pending", fx.plan, "--session", fx.session)
    assert code == 0, out
    code, out = fx.run("bind", "--plan", fx.plan, "--session", fx.session)
    assert code == 0, out
    text = fx.grouping_path.read_text(encoding="utf-8")
    assert "decisions=hdp" in text
    fx.grouping_path.write_bytes(
        text.replace("decisions=hdp", "decisions=human-all").encode()
    )
    _refused(_verify(fx, "exec_start"), "binding")


def test_vec_v2_033_recorded_tightening_verifies(tmp_path: Path) -> None:
    """AC-B.5: a carrier tightened with ``tightened_from`` naming the offered carrier verifies."""
    fx = _build(tmp_path)
    tight = {**fx.block, "commit_exec": False, "tightened_from": "grouping"}
    fx.write_carrier(tight, task_block=tight, grouping_values=fx.block)
    _init(fx)
    _verified(_verify(fx, "exec_start"))
    _refused(_verify(fx, "exec_commit"), "not_granted")
    _refused(_verify(fx, "finalize"), "not_granted")


def test_vec_v2_034_act_not_granted(tmp_path: Path) -> None:
    """AC-B.3: an act outside ``grants`` → ``not_granted``."""
    fx = _build(tmp_path)
    _offer_case(fx, values=fx.offer(grants=["exec_start", "plan_commit"]))
    _init(fx)
    _refused(_verify(fx, "finalize"), "not_granted")
    _refused(_verify(fx, "exec_commit"), "not_granted")
    _verified(_verify(fx, "exec_start"))


def test_vec_v2_035_enabling_parameter_false(tmp_path: Path) -> None:
    """AC-B.3: an act whose enabling parameter is false → ``not_granted``; ``inspect`` accepts it."""
    fx = _build(tmp_path)
    _offer_case(fx, values=fx.offer(commit_exec=False))
    _init(fx)
    _refused(_verify(fx, "exec_commit"), "not_granted")
    _refused(_verify(fx, "finalize"), "not_granted")
    code, out = fx.run("inspect", "--plan", fx.plan)
    assert (code, out.get("result")) == (0, "inspected"), out
    _verified(_verify(fx, "plan_commit"))


# -- V-7 scope -----------------------------------------------------------------------------


def test_vec_v2_036_strasse_is_another_directory(tmp_path: Path) -> None:
    """AC-B.1: ``straße`` and ``strasse`` are two directories; a grant for one fails in the other."""
    fx = _build(tmp_path, repo_name="straße")
    other = fx.clone("strasse")
    fx.set_mark(other)
    _refused(_verify(fx, "exec_start", repo=other), "scope")


def test_vec_v2_037_second_slug(tmp_path: Path) -> None:
    """AC-B.6: an invocation grant used by a second slug fails ``scope`` before any store read."""
    fx = _build(tmp_path)
    _refused(_verify(fx, "exec_start", plan=bf.PLAN_B), "scope")
    assert not fx.store.exists()


# -- V-8 store identity --------------------------------------------------------------------


def test_vec_v2_038_clone_has_no_store(tmp_path: Path) -> None:
    """AC-B.6: before ``init``, and in a clean clone, every act fails ``store_missing``."""
    fx = _build(tmp_path)
    _all_refused(fx, "store_missing")
    _init(fx)
    clone = fx.clone("clone")
    fx.set_mark(clone)
    cx = fx.for_repo(clone)
    cx.add_system()
    cx.write_carrier(cx.present_and_accept())
    _all_refused(cx, "store_missing", repo=clone)


def test_vec_v2_039_copied_store(tmp_path: Path) -> None:
    """AC-B.6: a store and its anchor copied into another repository → ``store_mismatch``."""
    fx = _build(tmp_path)
    _init(fx)
    clone = fx.clone("copy")
    fx.set_mark(clone)
    shutil.copytree(fx.store, clone / ".git" / "run-parameters")
    for key in (
        "run-parameters.storeUuid",
        "run-parameters.witnessSeq",
        "run-parameters.witnessDigest",
    ):
        value = fx.config_get(key)
        if value is not None:
            fx.config_set(key, value, repo=clone)
    cx = fx.for_repo(clone)
    cx.add_system()
    cx.write_carrier(cx.present_and_accept())
    _all_refused(cx, "store_mismatch", repo=clone)


def test_vec_v2_039_moved_repository_until_migrate(tmp_path: Path) -> None:
    """AC-B.6: a moved repository → ``store_mismatch`` until ``repair --migrate``."""
    fx = _build(tmp_path)
    _init(fx)
    moved = fx.root / "moved"
    os.rename(fx.repo, moved)
    mx = fx.for_repo(moved)
    mx.add_system()
    mx.write_carrier(mx.present_and_accept())
    _all_refused(mx, "store_mismatch", repo=moved)
    record = mx.add_human("repair the run-parameters store: the repository moved")
    code, out = mx.run(
        "repair", "--migrate", "--session", mx.session, "--message", record, repo=moved
    )
    assert code == 0, out
    _init(mx, repo=moved)
    _verified(_verify(mx, "exec_start", repo=moved))
    audit = (mx.store / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(line.strip() for line in audit)


# -- V-8 bytes, transactions and locks -----------------------------------------------------


def _corrupt_revocations(fx: bf.Fixture) -> None:
    with (fx.store / "revocations.jsonl").open(
        "a", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write('{"revoked": "')


def _corrupt_grant(fx: bf.Fixture) -> None:
    (fx.store / "grants" / f"{_mu(fx.block)}.json").write_text(
        '{"x": 1}\n', encoding="utf-8"
    )


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param(_corrupt_revocations, id="partial-revocation-line"),
        pytest.param(_corrupt_grant, id="grant-fails-schema"),
    ],
)
def test_vec_v2_040_store_malformed(
    tmp_path: Path, corrupt: Callable[[bf.Fixture], None]
) -> None:
    """AC-B.6: a partial JSONL line or a grant file that fails its schema → ``store_malformed``."""
    fx = _build(tmp_path)
    _init(fx)
    corrupt(fx)
    _all_refused(fx, "store_malformed")


def test_vec_v2_040_bad_payload_digest(tmp_path: Path) -> None:
    """AC-B.6: a ``txn/<txn>/data/`` file whose digest differs from ``intent`` → ``store_malformed``."""
    fx = _build(tmp_path)
    _init(fx)
    _crash(
        fx, "after_intent", "reserve", "exec_start", "--plan", fx.plan, "--op", "op-1"
    )
    _unlock(fx)
    data = [
        p for p in (fx.store / "txn").rglob("*") if p.is_file() and "data" in p.parts
    ]
    assert data, "the crashed transaction left no payload"
    data[0].write_bytes(data[0].read_bytes() + b"corrupt")
    _refused(_reserve(fx, "exec_start", "op-1"), "store_malformed")


def test_vec_v2_041_reader_meets_unfinished_txn(tmp_path: Path) -> None:
    """AC-B.7: a reader meets an ``intent`` without ``done`` → ``txn_pending``; readers never replay."""
    fx = _build(tmp_path)
    _init(fx)
    _crash(
        fx, "after_intent", "reserve", "exec_start", "--plan", fx.plan, "--op", "op-1"
    )
    before = fx.store_snapshot()
    _all_refused(fx, "txn_pending")
    assert fx.store_snapshot() == before


def test_vec_v2_042_stale_lock_and_atomic_unlock(tmp_path: Path) -> None:
    """AC-B.6, AC-B.8: a stale lock blocks writers, not readers; ``unlock`` compares the token."""
    fx = _build(tmp_path)
    _init(fx)
    body = _stale_lock(fx)
    lock = fx.store / "store.lock"
    _refused(_reserve(fx, "exec_start", "op-1"), "stale_lock")
    _verified(_verify(fx, "exec_start"))
    record = fx.add_human("unlock the run-parameters store")
    raw = lock.read_bytes()
    code, out = fx.run(
        "unlock", "--expect", "0" * 32, "--session", fx.session, "--message", record
    )
    assert (code, out.get("reason")) == (1, "token_mismatch"), out
    assert lock.read_bytes() == raw
    record = fx.add_human("unlock the run-parameters store with the right token")
    code, out = fx.run(
        "unlock",
        "--expect",
        body["token"],
        "--session",
        fx.session,
        "--message",
        record,
    )
    assert (code, out.get("result")) == (0, "unlocked"), out
    assert not lock.exists()
    audit = (fx.store / "audit.jsonl").read_text(encoding="utf-8")
    assert body["token"] in audit
    code, out = _reserve(fx, "exec_start", "op-1")
    assert (code, out.get("result")) == (0, "reserved"), out


@pytest.mark.serial
def test_vec_v2_042_held_lock(tmp_path: Path) -> None:
    """AC-B.6: a writer waits for a held lock, then fails ``stale_lock``; the body is schema-valid."""
    fx = _build(tmp_path)
    _init(fx)
    holder = _holder(fx, 6)
    try:
        start = time.monotonic()
        _refused(_reserve(fx, "exec_start", "op-1"), "stale_lock")
        assert time.monotonic() - start >= 0.2
        body = json.loads((fx.store / "store.lock").read_text(encoding="utf-8"))
        _schema_valid("store", "run-parameters-store", {"lock": body})
        assert body["session"] == "fixture-holder"
    finally:
        holder.kill()
        holder.communicate(timeout=30)


def test_vec_v2_043_lost_fact(tmp_path: Path) -> None:
    """AC-B.6: an inventory item lost (``revocations.jsonl``) → ``history_missing``."""
    fx = _build(tmp_path)
    _init(fx)
    (fx.store / "revocations.jsonl").unlink()
    _all_refused(fx, "history_missing")


def test_vec_v2_043_witness_absent(tmp_path: Path) -> None:
    """AC-B.10: the witness is absent where the inventory says it was written → ``history_missing``."""
    fx = _build(tmp_path)
    _init(fx)
    assert fx.config_get("run-parameters.witnessSeq") is not None
    fx.config_unset("run-parameters.witnessSeq")
    _all_refused(fx, "history_missing")


@pytest.mark.parametrize("fact", ["store-seq-ahead", "unknown-bound-session"])
def test_vec_v2_043_tree_fact_without_store_record(tmp_path: Path, fact: str) -> None:
    """AC-B.6: a tree ``store_seq`` above the store, or a tree fact with no record → ``history_missing``."""
    fx = _build(tmp_path)
    _init(fx)
    if fact == "store-seq-ahead":
        fx.write_carrier(fx.block, store_seq=999)
    else:
        fx.write_carrier(fx.block, bound_sessions=[str(uuid.uuid4())])
    _all_refused(fx, "history_missing")


def _ack_revocation(fx: bf.Fixture) -> None:
    session = str(uuid.uuid4())
    record = fx.add_human(
        f"revoke run_parameters {_mu(fx.block)}", parent=None, session=session
    )
    code, out = fx.run("revoke", "--session", session, "--message", record)
    assert code == 0, out


def _ack_supersession(fx: bf.Fixture) -> None:
    newer = fx.present_and_accept(supersedes=_mu(fx.block))
    code, out = fx.run("init", "--block", str(fx.write_block_file(newer, "newer")))
    assert code == 0, out


def _ack_consumption(fx: bf.Fixture) -> None:
    code, out = _reserve(fx, "exec_commit", "op-c")
    assert code == 0, out


@pytest.mark.parametrize(
    "acknowledge",
    [
        pytest.param(_ack_revocation, id="revocation"),
        pytest.param(_ack_supersession, id="supersession"),
        pytest.param(_ack_consumption, id="consumption"),
    ],
)
def test_vec_v2_043_rollback_witness_12_14_12(
    tmp_path: Path, acknowledge: Callable[[bf.Fixture], None]
) -> None:
    """AC-B.10: the 12/14/12 trace: a valid older copy restored at the same path fails closed.

    The tree is at the store's seq S, the store acknowledges a fact (seq > S) and the tree is set
    back to S, a copy taken at S is restored at the same path, and every act then fails
    ``history_missing`` because the witness in the common config is ahead. A restore that also
    rolls back the common config (the whole common dir replaced) is outside the trust boundary;
    this test names that case and does not assert on it.
    """
    fx = _build(tmp_path)
    _init(fx)
    seq = _last_seq(fx)
    fx.write_carrier(fx.block, store_seq=seq)
    snapshot = fx.root / "store-at-seq"
    fx.copy_store(snapshot)
    _verified(_verify(fx, "exec_start"))
    acknowledge(fx)
    assert _last_seq(fx) > seq
    fx.write_carrier(fx.block, store_seq=seq)
    fx.restore_store(snapshot)
    _all_refused(fx, "history_missing")


def test_vec_v2_043_repair_preserves_facts(tmp_path: Path) -> None:
    """AC-B.6: ``repair`` keeps every fact: a partial revocation line naming the grant revokes."""
    fx = _build(tmp_path)
    _init(fx)
    with (fx.store / "revocations.jsonl").open(
        "a", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(f'{{"revoked": "{_mu(fx.block)}", "by_sess')
    _refused(_verify(fx, "exec_start"), "store_malformed")
    record = fx.add_human("repair the run-parameters store")
    code, out = fx.run("repair", "--session", fx.session, "--message", record)
    assert code == 0, out
    _all_refused(fx, "revoked")
    assert any((fx.store / "audit").rglob("*")), "repair moved nothing to audit/"
    assert (fx.store / "audit.jsonl").read_text(encoding="utf-8").strip()


# -- V-8 consumption and V-8w reservation --------------------------------------------------


def test_vec_v2_044_other_op_refused(tmp_path: Path) -> None:
    """AC-B.6: a second op of the same plan and act → ``consumed``; the same op still verifies."""
    fx = _build(tmp_path)
    _init(fx)
    code, out = _reserve(fx, "exec_start", "op-1")
    assert (code, out.get("result")) == (0, "reserved"), out
    _refused(_reserve(fx, "exec_start", "op-2"), "consumed")
    _refused(_verify(fx, "exec_start", op="op-2"), "consumed")
    _refused(_verify(fx, "exec_start"), "consumed")
    _verified(_verify(fx, "exec_start", op="op-1"))


def test_vec_v2_045_init_after_inspect_and_same_op_recovery(tmp_path: Path) -> None:
    """AC-B.6: ``init`` after ``inspect``; a reservation; the same op returns the existing entry."""
    fx = _build(tmp_path)
    code, out = fx.run("inspect", "--plan", fx.plan)
    assert (code, out.get("result")) == (0, "inspected"), out
    assert not fx.store.exists()
    _init(fx)
    store = fx.read_json("store.json")
    _schema_valid("store", "run-parameters-store", {"store_json": store})
    assert fx.config_get("run-parameters.storeUuid") == store["repo_id"]["store_uuid"]
    code, out = _reserve(fx, "exec_start", "op-1")
    assert (code, out.get("result")) == (0, "reserved"), out
    entry = out["entry"]
    assert (entry["op_id"], entry["state"]) == ("op-1", "reserved"), out
    grant = fx.read_json(f"grants/{_mu(fx.block)}.json")
    _schema_valid("grant", "run-parameters-grant", grant)
    assert grant["consumed"][fx.plan]["exec_start"] == entry
    for line in fx.txn_lines():
        _schema_valid("store", "run-parameters-store", {"txn_line": line})
    assert entry["seq"] == _last_seq(fx)
    assert _frontmatter(fx.task_path())["store_seq"] == entry["seq"]
    code, again = _reserve(fx, "exec_start", "op-1")
    assert (code, again.get("result"), again.get("entry")) == (0, "reserved", entry), (
        again
    )
    _verified(_verify(fx, "exec_start", op="op-1"))


# -- V-9 revocation and supersession; V-10 closure -----------------------------------------


def test_vec_v2_046_revocation(tmp_path: Path) -> None:
    """AC-B.6: a complete revocation line naming the grant → ``revoked`` for every act."""
    fx = _build(tmp_path)
    _init(fx)
    session = str(uuid.uuid4())
    record = fx.add_human(
        f"revoke run_parameters {_mu(fx.block)}", parent=None, session=session
    )
    code, out = fx.run("revoke", "--session", session, "--message", record)
    assert (code, out.get("result")) == (0, "revoked"), out
    _all_refused(fx, "revoked")
    lines = (fx.store / "revocations.jsonl").read_text(encoding="utf-8").splitlines()
    line = json.loads(lines[-1])
    _schema_valid("revocation", "run-parameters-revocation", line)
    assert (line["revoked"], line["by_session"], line["by_message_uuid"]) == (
        _mu(fx.block),
        session,
        record,
    )


def test_vec_v2_047_supersession(tmp_path: Path) -> None:
    """AC-B.6: a later verified grant whose ``supersedes`` names this uuid → ``superseded``."""
    fx = _build(tmp_path)
    _init(fx)
    newer = fx.present_and_accept(supersedes=_mu(fx.block))
    code, out = fx.run("init", "--block", str(fx.write_block_file(newer, "newer")))
    assert code == 0, out
    _all_refused(fx, "superseded")
    old = fx.read_json(f"grants/{_mu(fx.block)}.json")
    assert old["superseded_by"] == _mu(newer)


def test_vec_v2_048_sealed_generation_closes_the_plan(tmp_path: Path) -> None:
    """AC-B.6: a sealed final generation closes every act; an unsealed receipt closes nothing."""
    fx = _build(tmp_path)
    _init(fx)
    _final(fx, fx.plan, sealed=False)
    _verified(_verify(fx, "exec_start"))
    _final(fx, fx.plan, sealed=True)
    _all_refused(fx, "expired")


def test_vec_v2_048_standing_per_member_expiry(tmp_path: Path) -> None:
    """AC-B.6: a standing grant expires by date, and per member by that member's sealed generation."""
    fx = _build(tmp_path)
    block = _offer_case(
        fx, values=fx.standing_offer([bf.PLAN, bf.PLAN_B]), carrier=False
    )
    fx.write_carrier(block, plan=bf.PLAN)
    fx.write_carrier(block, plan=bf.PLAN_B)
    _init(fx)
    late = {CLOCK: "2027-01-01T00:00:00Z"}
    _refused(_verify(fx, "exec_start", env=late), "expired")
    _final(fx, bf.PLAN, sealed=True)
    _refused(_verify(fx, "exec_start", plan=bf.PLAN), "expired")
    _verified(_verify(fx, "exec_start", plan=bf.PLAN_B))


def test_vec_v2_050_fixture_labelled(tmp_path: Path) -> None:
    """AC-B.3: verification against the fixture transcript is labelled ``fixture: true``."""
    fx = _build(tmp_path)
    _init(fx)
    out = _verified(_verify(fx, "exec_start"))
    assert out.get("fixture") is True, out
    assert out.get("effective") == SIGMA, out


# -- AC-B.7 crash and concurrency ----------------------------------------------------------


@pytest.mark.parametrize("step", TXN_STEPS)
def test_txn_crash_then_recovery(tmp_path: Path, step: str) -> None:
    """AC-B.7: a crash after each transaction step; the next writer recovers the transaction."""
    fx = _build(tmp_path)
    _init(fx)
    _crash(fx, step, "reserve", "exec_start", "--plan", fx.plan, "--op", "op-1")
    if step in ("after_intent", "after_replace_1"):
        _refused(_verify(fx, "exec_start"), "txn_pending")
    elif step == "after_data":
        _verified(_verify(fx, "exec_start"))
    else:
        _verified(_verify(fx, "exec_start", op="op-1"))
    pending = _pending_txns(fx)
    _unlock(fx)
    code, out = _reserve(fx, "exec_start", "op-1")
    assert (code, out.get("result")) == (0, "reserved"), out
    lines = fx.txn_lines()
    assert lines[-1].get("done") is True, lines[-1]
    assert not _pending_txns(fx)
    for txn in pending:
        assert not (fx.store / "txn" / txn).exists(), txn


@pytest.mark.serial
def test_two_concurrent_writers(tmp_path: Path) -> None:
    """AC-B.7: two concurrent writers both succeed in turn, with distinct sequence numbers."""
    fx = _build(tmp_path)
    _init(fx)
    wait = {LOCK_WAIT: "30"}
    first = fx.spawn(
        "reserve", "exec_start", "--plan", fx.plan, "--op", "op-a", env=wait
    )
    second = fx.spawn(
        "reserve", "plan_commit", "--plan", fx.plan, "--op", "op-b", env=wait
    )
    outs = [proc.communicate(timeout=90) for proc in (first, second)]
    assert first.returncode == 0 and second.returncode == 0, outs
    entries = [bf.parse_output(out)["entry"] for out, _ in outs]
    assert entries[0]["seq"] != entries[1]["seq"], entries
    assert not _pending_txns(fx)


@pytest.mark.serial
def test_production_store_ignores_the_seams(tmp_path: Path) -> None:
    """AC-B.7: an unmarked (production) store ignores the crash, lock-wait and clock seams."""
    fx = _build(tmp_path, mark=False)
    assert fx.config_get(bf.MARK_KEY) is None
    _init(fx)
    code, out, err = fx.run_subprocess(
        "reserve",
        "exec_start",
        "--plan",
        fx.plan,
        "--op",
        "op-1",
        env={CRASH: "after_intent"},
    )
    assert (code, out.get("result")) == (0, "reserved"), (out, err)
    holder = _holder(fx, 3)
    try:
        waiter = fx.spawn(
            "reserve",
            "plan_commit",
            "--plan",
            fx.plan,
            "--op",
            "op-2",
            env={LOCK_WAIT: "0.2"},
        )
        time.sleep(1.5)
        assert waiter.poll() is None, (
            "the production writer did not wait for the held lock"
        )
        stdout, stderr = waiter.communicate(timeout=90)
        assert waiter.returncode == 0, (stdout, stderr)
        assert bf.parse_output(stdout).get("result") == "reserved"
    finally:
        holder.kill()
        holder.communicate(timeout=30)
    block = _offer_case(
        fx,
        values=fx.standing_offer([bf.PLAN, bf.PLAN_B], expires="2099-12-31"),
        carrier=False,
    )
    fx.write_carrier(block, plan=bf.PLAN_B)
    _init(fx, plan=bf.PLAN_B)
    _verified(
        _verify(fx, "exec_start", plan=bf.PLAN_B, env={CLOCK: "2100-01-01T00:00:00Z"})
    )


# -- AC-B.8 atomic unlock ------------------------------------------------------------------


@pytest.mark.serial
def test_two_concurrent_unlockers(tmp_path: Path) -> None:
    """AC-B.8: two concurrent unlockers with the same token: exactly one succeeds."""
    fx = _build(tmp_path)
    _init(fx)
    body = _stale_lock(fx)
    record = fx.add_human("unlock the run-parameters store")
    argv = (
        "unlock",
        "--expect",
        body["token"],
        "--session",
        fx.session,
        "--message",
        record,
    )
    procs = [fx.spawn(*argv), fx.spawn(*argv)]
    outs = [proc.communicate(timeout=90) for proc in procs]
    results = [
        (proc.returncode, bf.parse_output(out)) for proc, (out, _) in zip(procs, outs)
    ]
    wins = [
        out for code, out in results if code == 0 and out.get("result") == "unlocked"
    ]
    losses = [
        out
        for code, out in results
        if code == 1 and out.get("reason") in ("no_lock", "unlock_conflict")
    ]
    assert (len(wins), len(losses)) == (1, 1), results
    assert not (fx.store / "store.lock").exists()
    assert not list(fx.store.glob("store.lock.unlock-*"))


def test_unlock_never_removes_a_retaken_lock(tmp_path: Path) -> None:
    """AC-B.8: a lock taken again with a new token after the human read it is never removed."""
    fx = _build(tmp_path)
    _init(fx)
    first = _stale_lock(fx)
    second = _stale_lock(fx)
    raw = (fx.store / "store.lock").read_bytes()
    record = fx.add_human("unlock the run-parameters store")
    code, out = fx.run(
        "unlock",
        "--expect",
        first["token"],
        "--session",
        fx.session,
        "--message",
        record,
    )
    assert (code, out.get("reason")) == (1, "token_mismatch"), out
    assert (fx.store / "store.lock").read_bytes() == raw
    assert json.loads(raw)["token"] == second["token"]


@pytest.mark.serial
def test_unlock_refuses_a_live_holder(tmp_path: Path) -> None:
    """AC-B.8: the unlock needs quiescence: a live holder's lock → ``lock_held``."""
    fx = _build(tmp_path)
    _init(fx)
    holder = _holder(fx, 6)
    try:
        lock = fx.store / "store.lock"
        token = json.loads(lock.read_text(encoding="utf-8"))["token"]
        record = fx.add_human("unlock the run-parameters store")
        code, out = fx.run(
            "unlock", "--expect", token, "--session", fx.session, "--message", record
        )
        assert (code, out.get("reason")) == (1, "lock_held"), out
        assert lock.exists()
    finally:
        holder.kill()
        holder.communicate(timeout=30)


# -- AC-B.9 index recovery -----------------------------------------------------------------


def _published_commit(fx: bf.Fixture, content: bytes) -> tuple[str, str, str]:
    """Commit ``notes.txt`` through a temporary index and move ``main``; return (P, C, blob)."""
    parent = bf.git(fx.repo, "rev-parse", "HEAD")
    blob_path = fx.root / "notes-new.txt"
    blob_path.write_bytes(content)
    blob = bf.git(fx.repo, "hash-object", "-w", str(blob_path))
    env = bf.git_env()
    env["GIT_INDEX_FILE"] = str(fx.root / "temp-index")

    def git_temp(*args: str) -> str:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            ["git", *args],
            cwd=fx.repo,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return proc.stdout.strip()

    git_temp("read-tree", parent)
    git_temp("update-index", "--add", "--cacheinfo", f"100644,{blob},notes.txt")
    tree = git_temp("write-tree")
    commit = bf.git(fx.repo, "commit-tree", tree, "-p", parent, "-m", "fixture: packet")
    bf.git(fx.repo, "update-ref", "refs/heads/main", commit, parent)
    (fx.repo / "notes.txt").write_bytes(content)
    return parent, commit, blob


def _reconcile_code(fx: bf.Fixture, parent: str, commit: str) -> str:
    return (
        "import json\n"
        "from pathlib import Path\n"
        "from tools.run_parameters import reconcile_index\n"
        f"result = reconcile_index(Path({str(fx.repo)!r}), plan={fx.plan!r}, run_id='run-1',"
        f" op='op-1', paths=['notes.txt'], parent={parent!r}, commit={commit!r})\n"
        "print(json.dumps(result), flush=True)\n"
    )


def _index_blob(fx: bf.Fixture, path: str) -> str:
    entry = bf.git(fx.repo, "ls-files", "-s", "--", path)
    return entry.split()[1] if entry else ""


def _index_setup(fx: bf.Fixture) -> tuple[str, str, str]:
    (fx.repo / "notes.txt").write_bytes(b"one\n")
    fx.commit("fixture: notes")
    _init(fx)
    return _published_commit(fx, b"two\n")


@pytest.mark.parametrize("step", INDEX_STEPS)
def test_index_recovery_after_each_substep(tmp_path: Path, step: str) -> None:
    """AC-B.9: a crash after each index-reconciliation substep recovers with no lost entry."""
    fx = _build(tmp_path)
    parent, commit, blob = _index_setup(fx)
    code = _reconcile_code(fx, parent, commit)
    proc = fx.run_python(code, env={CRASH: step})
    assert proc.returncode == CRASH_EXIT, (step, proc.stdout, proc.stderr)
    _unlock(fx)
    proc = fx.run_python(code)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["paths"] == {"notes.txt": "updated"}, result
    assert _index_blob(fx, "notes.txt") == blob
    assert not (fx.common_dir / "index.lock").exists()
    folder = fx.store / "ops" / fx.plan / "run-1"
    assert (folder / "op-1" / "index" / "before.json").is_file()
    assert (folder / "op-1" / "index" / "after.json").is_file()
    journal = [
        p.read_text(encoding="utf-8")
        for p in folder.rglob("*.json")
        if "index" not in p.relative_to(folder).parts
    ]
    assert any("index_reconciled" in text and "done" in text for text in journal), (
        journal
    )


def test_index_recovery_keeps_a_foreign_staged_entry(tmp_path: Path) -> None:
    """AC-B.9: a foreign staged entry keeps its bytes and is reported ``foreign_staged``."""
    fx = _build(tmp_path)
    parent, commit, _ = _index_setup(fx)
    (fx.repo / "notes.txt").write_bytes(b"three\n")
    bf.git(fx.repo, "add", "notes.txt")
    foreign = _index_blob(fx, "notes.txt")
    proc = fx.run_python(_reconcile_code(fx, parent, commit))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert str(result["paths"]["notes.txt"]).startswith("foreign_staged"), result
    assert _index_blob(fx, "notes.txt") == foreign


def test_index_recovery_production_ignores_the_crash_seam(tmp_path: Path) -> None:
    """AC-B.7: in an unmarked store the crash seam of ``reconcile_index`` is ignored."""
    fx = _build(tmp_path, mark=False)
    parent, commit, blob = _index_setup(fx)
    proc = fx.run_python(
        _reconcile_code(fx, parent, commit), env={CRASH: "index_update"}
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert _index_blob(fx, "notes.txt") == blob


# -- AC-B.11 sessions ----------------------------------------------------------------------


def _session_record(fx: bf.Fixture, session: str) -> dict[str, Any]:
    record = fx.read_json(f"sessions/{session}.json")
    _schema_valid("session", "run-parameters-session", record)
    return record


def _states(record: Mapping[str, Any]) -> dict[str, str]:
    return {str(entry["plan"]): str(entry["state"]) for entry in record["plans"]}


def test_session_reuse_after_sealed_completion(tmp_path: Path) -> None:
    """AC-B.11: one open plan per session; a ``complete`` and sealed plan frees the session."""
    fx = _build(tmp_path)
    _init(fx)
    session = fx.session
    code, out = fx.run("bind", "--pending", fx.plan, "--session", session)
    assert code == 0, out
    assert _states(_session_record(fx, session)) == {fx.plan: "pending"}
    code, out = fx.run("bind", "--plan", fx.plan, "--session", session)
    assert code == 0, out
    assert _states(_session_record(fx, session)) == {fx.plan: "active"}
    task = _frontmatter(fx.task_path())
    assert task["bound_sessions"] == [session]
    assert isinstance(task["store_seq"], int)
    code, out = fx.run("bind", "--pending", bf.PLAN_B, "--session", session)
    assert (code, out.get("reason")) == (1, "session_busy"), out
    code, out = fx.run("bind", "--plan", bf.PLAN_B, "--session", session)
    assert (code, out.get("reason")) == (1, "session_busy"), out
    _final(fx, fx.plan, sealed=True)
    _set_status(fx, fx.plan, "complete")
    code, out = fx.run("bind", "--pending", bf.PLAN_B, "--session", session)
    assert code == 0, out
    assert _states(_session_record(fx, session)) == {
        fx.plan: "closed",
        bf.PLAN_B: "pending",
    }


def test_session_handover(tmp_path: Path) -> None:
    """AC-B.11: ``bind --plan`` in a new session hands the plan over; both copies record it."""
    fx = _build(tmp_path)
    _init(fx)
    first = fx.session
    assert fx.run("bind", "--pending", fx.plan, "--session", first)[0] == 0
    assert fx.run("bind", "--plan", fx.plan, "--session", first)[0] == 0
    second = str(uuid.uuid4())
    fx.add_system(parent=None, session=second)
    code, out = fx.run("bind", "--plan", fx.plan, "--session", second)
    assert code == 0, out
    assert _states(_session_record(fx, first)) == {fx.plan: "handed_over"}
    assert _states(_session_record(fx, second)) == {fx.plan: "active"}
    assert _frontmatter(fx.task_path())["bound_sessions"] == [first, second]
    _verified(_verify(fx, "exec_start"))


# -- AC-B.12 the fixture builder -----------------------------------------------------------


@pytest.mark.unit
def test_fixture_builder_refuses_a_non_empty_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-B.12: a non-empty ``--root`` → exit 2 and nothing is written."""
    root = tmp_path / "busy"
    root.mkdir()
    (root / "keep.txt").write_text("keep\n", encoding="utf-8")
    code = bf.main(["--root", str(root), "--source", str(ROOT), "--profile", "test"])
    assert code == 2
    assert sorted(p.name for p in root.iterdir()) == ["keep.txt"]
    assert json.loads(capsys.readouterr().out)["result"] == "refused"


@pytest.mark.unit
def test_fixture_builder_refuses_a_root_inside_a_work_tree(tmp_path: Path) -> None:
    """AC-B.12: a root inside a git work tree → exit 2 and the root is not created."""
    tree = tmp_path / "tree"
    tree.mkdir()
    bf.git(tree, "init", "-q")
    root = tree / "fx"
    code = bf.main(["--root", str(root), "--source", str(ROOT), "--profile", "test"])
    assert code == 2
    assert not root.exists()


def test_fixture_builder_contents(tmp_path: Path) -> None:
    """AC-B.12: the fixture files, the ``fixture: true`` evidence, the transcript and the manifest."""
    fx = _build(tmp_path)
    for name in ("AGENTS.md", "GUARDRAILS.md"):
        assert (
            (fx.repo / name).read_text(encoding="utf-8").startswith(bf.FIXTURE_HEADER)
        )
    evidence = json.loads(fx.evidence_path.read_text(encoding="utf-8"))
    assert sorted(evidence) == sorted(bf.EVIDENCE_PHASES)
    assert all(entry.get("fixture") is True for entry in evidence.values())
    policy = json.loads(fx.policy_path.read_text(encoding="utf-8"))
    _schema_valid("policy", "run-parameters-policy", policy)
    for rel in bf.B2_COMPONENTS:
        assert policy["components"][rel] == bf.sha256_file(fx.source / rel)
    records = [
        json.loads(line)
        for line in fx.transcript.read_text(encoding="utf-8").splitlines()
    ]
    auth = fx.block["authorization"]
    kinds = {record["uuid"]: record["type"] for record in records}
    assert kinds[auth["presentation_uuid"]] == "assistant"
    assert kinds[auth["message_uuid"]] == "user"
    assert _human_text(fx, auth["message_uuid"]) == "proceed"
    manifest = json.loads((fx.root / "fixture.json").read_text(encoding="utf-8"))
    assert manifest == fx.manifest()
    assert fx.config_get(bf.MARK_KEY) == "true"
    _schema_valid("run-parameters", "run_parameters", fx.block)


def test_production_status_never_reads_a_fixture_file(tmp_path: Path) -> None:
    """AC-B.12: fixture evidence in an unmarked repository never enables a production status."""
    fx = _build(tmp_path)
    fx.config_unset(bf.MARK_KEY)
    code, out = fx.run("status", "--json")
    assert code == 0, out
    assert out.get("enabled") is False, out
    _refused(_verify(fx, "exec_start"), "disabled")
    prod = _build(tmp_path, name="prod", mark=False)
    code, out = prod.run("status", "--json")
    assert code == 0, out
    assert out.get("enabled") is True, out
