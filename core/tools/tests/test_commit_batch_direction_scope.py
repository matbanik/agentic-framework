"""MEU-939 tests for the commit route stop list, identity, attribution and direction scope.

Plan: docs/execution/plans/2026-11-07-standing-commit-grant (AC-939.4, AC-939.5, AC-939.13,
AC-939.14).

The contract these tests fix (``{{RECEIPTS_DIR}}/standing-grant/interfaces.md`` §1-§4 and
§wave 2):

* The grant routes (the plan's own grant and the standing grant) run the stop list before any
  ref moves and before any op is reserved: ``foreign_hunks`` (detail ``<path>:<owner>``),
  ``foreign_delete`` (detail ``<path>``), ``author_not_noreply`` and ``secret`` (detail
  ``<path>``). A refusal writes no ref, reserves no op, spends no direction and leaves the
  working tree and the index byte-equal.
* ``commit_batch.check_identity(top, author)``, ``commit_batch.check_message(text)``,
  ``commit_batch.commit_identity_env(env, name, email)`` and ``commit_batch.NOREPLY_RE`` are
  the shared checks; every commit-writing entry point calls them (the batch route, the lane
  commit helper, the land message and the land publish here; ``tools/fw_commit.py`` in
  ``test_fw_commit.py``).
* The narrowed ``commit_batch._withdrawn(sentences, position, question)``.
* One direction covers a whole ``commit-batch/1``; the claim then reads ``state: spent``.

New names are imported inside the test bodies, so a missing name fails at Red rather than
erroring at collection. The commit tests drive the real ``tools.commit_batch`` and
``tools/lanes.py`` against real fixture repositories.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import io
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "/standing-commit-grant"
LEGACY = "2026-11-01-legacy-plan"
OTHER_PLAN = "2026-11-02-other-owner"
KI_PLAN = "2026-10-28-mf2-tax-wash-lot-integrity"
NOREPLY = "100+fixture@users.noreply.github.com"
AUTHOR = {"name": "Fixture", "email": NOREPLY}
OTHER_NOREPLY = "200+other@users.noreply.github.com"
INTRUDER = "300+intruder@users.noreply.github.com"
NOT_NOREPLY = "fixture@example.invalid"
SCAN_ENV = "{{PROJECT_NAME_UPPER}}_LANES_SCAN_ENTRY"
BASELINE = ".secrets.baseline"
IDENTITY_VARS = ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL")
ALL_IDENTITY_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
)
# The trailer strings are built by concatenation, so no file of the repository holds one.
CO = "Co-Authored-" + "By: "
TRAILERS = {
    "claude": CO + "Claude <claude@example.invalid>",
    "codex": CO + "Codex <codex@example.invalid>",
    "openai": CO + "OpenAI <openai@example.invalid>",
}
HUMAN_TRAILER = CO + "Pat Fixture <pat@example.invalid>"
EMPTY_BASELINE = {
    "version": "1.5.0",
    "plugins_used": [],
    "filters_used": [],
    "results": {},
    "generated_at": "2026-11-02T00:00:00Z",
}
# A stand-in for the detect-secrets hook (the ``test_lane_route_tooling.py`` protocol): a
# ``PLANTED = "<value>"`` line is a new secret, named as ``Location:    <path>:<line>``.
FAKE_SCANNER = r"""
import re
import sys
from pathlib import Path

PATTERN = re.compile(r'PLANTED = "([^"]+)"')
found = []
for rel in sys.argv[1:]:
    path = Path(rel)
    if not path.is_file():
        continue
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if PATTERN.search(line):
            found.append((rel, number))
if found:
    print("ERROR: Potential secrets about to be committed to git repo!")
    for rel, number in found:
        print()
        print("Secret Type: Planted Fixture")
        print(f"Location:    {rel}:{number}")
    sys.exit(1)
sys.exit(0)
"""


# -- helpers (the wave-1 forms) ----------------------------------------------------------------


def _cb() -> ModuleType:
    return importlib.import_module("tools.commit_batch")


def _rp() -> ModuleType:
    return importlib.import_module("tools.run_parameters")


def _rig(tmp_path: Path, name: str = "fx") -> b3.Rig:
    rig = b3.rig(tmp_path / name, ROOT)
    rig.git("config", "user.email", NOREPLY)
    return rig


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
    if any(line.strip() == f"standing_ok {uid}" for line in stdout.splitlines()):
        return True
    return any(
        item.get("result") == "standing_ok" and item.get("message_uuid") == uid
        for item in _json_lines(stdout)
    )


def _grant(fx: bf.Fixture, text: str = TOKEN) -> str:
    """Record a standing grant from a typed record; return its uuid."""
    uid = fx.add_human(text)
    code, out, err = _run_rp(
        fx, "standing", "--session", fx.session, "--message-uuid", uid
    )
    assert code == 0 and _says_standing_ok(out, uid), (code, out, err)
    return uid


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


def _outcome(res: b3.Result) -> str:
    """``reconciled``, or ``refused:<reason>``, or ``other:<exit>:<result>`` of one run."""
    code, out, _text = res
    if (code, out.get("result")) == (0, "reconciled"):
        return "reconciled"
    if (code, out.get("result")) == (1, "refused"):
        return f"refused:{out.get('reason')}"
    return f"other:{code}:{out.get('result')}"


def _reconciled(res: b3.Result) -> dict[str, Any]:
    code, out, text = res
    assert (code, out.get("result")) == (0, "reconciled"), text
    return out


def _legacy_text(plan: str, ownership: str = "") -> str:
    return (
        f"# Task: {plan}\n\n| # | Task | Status |\n| :- | :- | :- |\n| 0 | row | [ ] |\n"
        + ownership
    )


def _ownership(owns: list[str]) -> str:
    """The ``## Lane Ownership`` block (the stage-1 format of ``tools/tests/test_lanes_land.py``)."""
    return (
        "\n## Lane Ownership\n\n```yaml\nowns:\n"
        + "".join(f"  - {item}\n" for item in owns)
        + "must_not_touch: []\n```\n"
    )


def _claims(fx: bf.Fixture) -> list[Path]:
    return sorted(fx.store.glob("ops/*/*/*/direction.json"))


def _claim(fx: bf.Fixture, uid: str) -> dict[str, Any]:
    paths = sorted(fx.store.glob(f"ops/*/*/human-{uid}/direction.json"))
    assert len(paths) == 1, paths
    data = json.loads(paths[0].read_text(encoding="utf-8"))
    assert isinstance(data, dict), paths[0]
    return data


def _grants_bytes(fx: bf.Fixture) -> dict[str, bytes]:
    folder = fx.store / "grants"
    if not folder.is_dir():
        return {}
    return {path.name: path.read_bytes() for path in sorted(folder.glob("*.json"))}


def _state(rig: b3.Rig) -> dict[str, Any]:
    """Every surface a stop-list refusal must leave alone."""
    return {
        "ref": rig.ref(),
        "grants": _grants_bytes(rig.fx),
        "claims": [path.as_posix() for path in _claims(rig.fx)],
        "worktree": rig.worktree(),
        "index": rig.index(),
    }


def _scanner(tmp_path: Path) -> dict[str, str]:
    script = tmp_path / "scanner" / "fake_hook.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(FAKE_SCANNER, encoding="utf-8", newline="\n")
    return {SCAN_ENV: json.dumps([sys.executable, str(script), "{paths}"])}


def _scope_rig(tmp_path: Path, authority: str) -> tuple[b3.Rig, str, str | None]:
    """A rig whose plan owns ``src/mine/``, beside an in-progress plan that owns ``src/other/``.

    Returns (rig, the packet plan, the standing grant uuid or None).
    """
    rig = _rig(tmp_path)
    other_task = '---\nstatus: "in_progress"\n---\n' + _legacy_text(
        OTHER_PLAN, _ownership(["src/other/"])
    )
    seed: dict[str, bytes] = {
        f"docs/execution/plans/{OTHER_PLAN}/task.md": other_task.encode("utf-8"),
        f"docs/execution/plans/{OTHER_PLAN}/implementation-plan.md": (
            f"# Plan: {OTHER_PLAN}\n".encode()
        ),
        "src/other/x.py": b"OTHER = 1\n",
        "src/mine/a.py": b"MINE = 1\n",
        "src/free.py": b"FREE = 1\n",
        BASELINE: (json.dumps(EMPTY_BASELINE, indent=2) + "\n").encode("utf-8"),
    }
    if authority == "plan":
        current = rig.fx.task_path(rig.plan).read_bytes()
        seed[f"docs/execution/plans/{rig.plan}/task.md"] = current + _ownership(
            ["src/mine/"]
        ).encode("utf-8")
        rig.seed(seed, message="fixture: two owners")
        rig.reserve("op-1")
        return rig, rig.plan, None
    seed[f"docs/execution/plans/{LEGACY}/task.md"] = _legacy_text(
        LEGACY, _ownership(["src/mine/"])
    ).encode("utf-8")
    seed[f"docs/execution/plans/{LEGACY}/implementation-plan.md"] = (
        f"# Plan: {LEGACY}\n".encode()
    )
    rig.seed(seed, message="fixture: two owners")
    return rig, LEGACY, _grant(rig.fx)


# -- AC-939.4: the stop list on the grant routes -----------------------------------------------


@pytest.mark.parametrize("authority", ["plan", "standing"])
@pytest.mark.parametrize(
    "case", ["foreign_hunks", "foreign_delete", "author_not_noreply", "secret"]
)
def test_ac_939_4_stop_list_refuses_before_any_write(
    tmp_path: Path, authority: str, case: str
) -> None:
    """AC-939.4: each stop item refuses with no ref, no op reserved, no direction, byte-equal tree."""
    rig, plan, uid = _scope_rig(tmp_path, authority)
    env: dict[str, str | None] | None = None
    authors: list[dict[str, str]] = [AUTHOR]
    if case == "foreign_hunks":
        (rig.repo / "src/other/x.py").write_bytes(b"OTHER = 2\n")
        files = {"src/other/x.py": b"OTHER = 3\n"}
        deletes: tuple[str, ...] = ()
        expected: tuple[str, str | None] = (
            "foreign_hunks",
            f"src/other/x.py:{OTHER_PLAN}",
        )
    elif case == "foreign_delete":
        files = {"src/mine/b.py": b"MINE = 2\n"}
        deletes = ("src/free.py",)
        expected = ("foreign_delete", "src/free.py")
    elif case == "author_not_noreply":
        files = {"src/mine/b.py": b"MINE = 2\n"}
        deletes = ()
        authors = [
            {"name": "Fixture", "email": NOT_NOREPLY},
            {"name": "Fixture", "email": OTHER_NOREPLY},
        ]
        expected = ("author_not_noreply", None)
    else:
        files = {"src/mine/creds.py": b'PLANTED = "fixture-secret-value"\n'}
        deletes = ()
        env = dict(_scanner(tmp_path))
        expected = ("secret", "src/mine/creds.py")
    for author in authors:
        before = _state(rig)
        packet = rig.packet(files=files, deletes=deletes, author=author, plan=plan)
        reason, detail = _commit_refusal(rig.commit("op-1", packet, env=env))
        assert reason == expected[0], (author, reason, detail)
        if expected[1] is not None:
            assert detail == expected[1], (author, detail)
        after = _state(rig)
        assert after["ref"] == before["ref"], "no ref moves"
        assert after["grants"] == before["grants"], "no op is reserved or consumed"
        assert after["claims"] == before["claims"] == [], "no direction is spent"
        assert after["worktree"] == before["worktree"], "the working tree is byte-equal"
        assert after["index"] == before["index"], "the index is byte-equal"
        if uid is not None:
            envelope = json.loads(
                (rig.fx.store / "grants" / f"{uid}.json").read_text(encoding="utf-8")
            )
            assert envelope["consumed"] == {}, envelope["consumed"]


# -- AC-939.5: the shared checks -------------------------------------------------------------------


def test_ac_939_5_check_identity_accepts_only_the_configured_noreply(
    tmp_path: Path,
) -> None:
    """AC-939.5: ``check_identity`` refuses a personal address and a foreign noreply address."""
    cb = _cb()
    rig = _rig(tmp_path)
    with bf.patched_environ(rig.fx.env()):
        cb.check_identity(rig.repo, {"name": "Fixture", "email": NOREPLY})
        for email in (NOT_NOREPLY, OTHER_NOREPLY, "fixture@users.noreply.github.com"):
            with pytest.raises(cb.rp.Refusal) as info:
                cb.check_identity(rig.repo, {"name": "Fixture", "email": email})
            assert info.value.reason == "author_not_noreply", (email, info.value)


def test_ac_939_5_check_message_refuses_every_trailer_and_ai_credit() -> None:
    """AC-939.5: the widened ``ATTRIBUTION_RE``: any co-author trailer and the AI-name credit forms."""
    cb = _cb()
    refused = [
        f"feat: fixture change\n\n{TRAILERS['claude']}\n",
        f"feat: fixture change\n\n{TRAILERS['codex']}\n",
        f"feat: fixture change\n\n{TRAILERS['openai']}\n",
        f"feat: fixture change\n\n{HUMAN_TRAILER}\n",
        "feat: fixture change\n\nGenerated with Copilot\n",
        "feat: fixture change\n\nAuthored by Gemini\n",
        "feat: fixture change\n\nGenerated by ChatGPT\n",
    ]
    for text in refused:
        with pytest.raises(cb.rp.Refusal) as info:
            cb.check_message(text)
        assert info.value.reason == "attribution", (text, info.value)
    for text in (
        "feat: fixture change\n",
        "docs: note the Claude Code setting\n\nThe settings file names Claude Code.\n",
    ):
        cb.check_message(text)


def test_ac_939_5_commit_identity_env_binds_or_refuses() -> None:
    """AC-939.5: an override that differs refuses ``identity_env:<var>``; else all four are set."""
    cb = _cb()
    for var in IDENTITY_VARS:
        env = {"PATH": "fixture", var: INTRUDER}
        with pytest.raises(cb.rp.Refusal) as info:
            cb.commit_identity_env(env, "Fixture", NOREPLY)
        assert (info.value.reason, info.value.detail) == ("identity_env", var), (
            info.value
        )
    env = {"PATH": "fixture", "GIT_AUTHOR_EMAIL": NOREPLY}
    result = cb.commit_identity_env(env, "Fixture", NOREPLY)
    bound = result if isinstance(result, dict) else env
    assert {var: bound.get(var) for var in ALL_IDENTITY_VARS} == {
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": NOREPLY,
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": NOREPLY,
    }


def test_ac_939_5_noreply_rule_holds_no_personal_address() -> None:
    """AC-939.5: ``NOREPLY_RE`` is the plan's pattern; ``commit_batch.py`` holds no personal literal."""
    cb = _cb()
    assert cb.NOREPLY_RE.pattern == r"^\d+\+[A-Za-z0-9-]+@users\.noreply\.github\.com$"
    assert cb.NOREPLY_RE.match(NOREPLY)
    assert not cb.NOREPLY_RE.match(NOT_NOREPLY)
    tree = ast.parse((ROOT / "tools" / "commit_batch.py").read_text(encoding="utf-8"))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert not [text for text in literals if "@gmail" in text.lower()]
    personal = re.compile(
        r"[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com)[A-Za-z0-9-]+\.com"
    )
    assert not [text for text in literals if personal.search(text)], (
        "no address literal"
    )


def test_ac_939_5_human_route_refuses_a_personal_author(tmp_path: Path) -> None:
    """AC-939.5: the human route checks the author too; no ref moves and the direction is not spent."""
    rig = _rig(tmp_path)
    rig.bind()
    uid = rig.fx.add_human("commit")
    before = rig.ref()
    packet = rig.packet(author={"name": "Fixture", "email": NOT_NOREPLY})
    reason, _detail = _commit_refusal(rig.human(uid, packet))
    assert reason == "author_not_noreply"
    assert rig.ref() == before
    for path in sorted(rig.fx.store.glob(f"ops/*/*/human-{uid}/direction.json")):
        claim = json.loads(path.read_text(encoding="utf-8"))
        assert claim.get("state") == "released", claim


def test_ac_939_5_grant_route_refuses_each_ai_trailer(tmp_path: Path) -> None:
    """AC-939.5: a Claude, a Codex and an OpenAI trailer each refuse ``attribution`` on the batch route."""
    outcomes = {}
    moved = []
    for name, trailer in TRAILERS.items():
        rig = _rig(tmp_path, name)
        rig.reserve("op-1")
        before = rig.ref()
        packet = rig.packet(message=f"feat: fixture change\n\n{trailer}\n")
        outcomes[name] = _outcome(rig.commit("op-1", packet))
        if rig.ref() != before:
            moved.append(name)
    assert outcomes == {name: "refused:attribution" for name in TRAILERS}, outcomes
    assert moved == [], moved


def test_ac_939_5_batch_route_scrubs_identity_overrides_and_checks_the_author(
    tmp_path: Path,
) -> None:
    """AC-939.5: overrides are scrubbed (author and committer stay the checked identity); a bad author refuses."""
    rig = _rig(tmp_path)
    rig.reserve("op-1")
    overrides: dict[str, str | None] = {var: INTRUDER for var in IDENTITY_VARS}
    packet = rig.packet(files={"scrub.txt": b"scrub\n"}, author=AUTHOR)
    _reconciled(
        rig.drive(
            "--phase",
            "exec",
            "--op",
            "op-1",
            "--packet",
            str(rig.write_packet(packet)),
            env=overrides,
        )
    )
    shown = rig.git("show", "-s", "--format=%ae|%ce", "HEAD").strip()
    assert shown == f"{NOREPLY}|{NOREPLY}", shown
    changed = dict(packet, author={"name": "Fixture", "email": OTHER_NOREPLY})
    reason, _detail = _commit_refusal(rig.commit("op-1", changed))
    assert reason == "packet_mismatch", "an existing op keeps its packet check"
    rig.reserve("op-2", act="plan_commit")
    before = rig.ref()
    bad = rig.packet(
        files={"bad.txt": b"bad\n"}, author={"name": "Fixture", "email": NOT_NOREPLY}
    )
    reason, _detail = _commit_refusal(rig.commit("op-2", bad, phase="plan"))
    assert reason == "author_not_noreply"
    assert rig.ref() == before


# -- AC-939.5 on the lane routes ------------------------------------------------------------------


def _lane(tmp_path: Path) -> Any:
    from tools.tests import test_lanes_land as tl

    land = tl._one(tmp_path)
    land.rig.git("config", "user.email", NOREPLY)
    return land


def _lane_refused(proc: Any, reason: str, detail: str | None = None) -> str | None:
    """None when ``proc`` refused ``reason`` (and names ``detail``); else what it did."""
    lines = proc.stdout.splitlines()
    hit = proc.returncode == 1 and any(
        line.startswith(f"refused: {reason}") for line in lines
    )
    if hit and (detail is None or detail in proc.stdout):
        return None
    return f"exit {proc.returncode}: {proc.stdout.strip()[-300:]}"


def test_ac_939_5_lane_commit_helper_runs_the_shared_checks(tmp_path: Path) -> None:
    """AC-939.5: ``lanes.py commit`` refuses a personal author, each AI trailer and each override."""
    from tools.tests import test_lanes_land as tl

    land = _lane(tmp_path)
    mismatches: dict[str, str] = {}
    counter = 0

    def attempt(message: str, env: dict[str, str | None] | None = None) -> Any:
        nonlocal counter
        counter += 1
        extra = land.wt / tl.LANE_DIR / f"extra_{counter}.py"
        extra.write_bytes(f"EXTRA = {counter}\n".encode())
        bf.git(land.wt, "add", "-A")
        path = land.rig.fx.root / f"lane-message-{counter}.txt"
        path.write_bytes(message.encode("utf-8"))
        return tl._cli(
            land,
            "commit",
            "--worktree",
            str(land.wt),
            "--message-file",
            str(path),
            env=env,
        )

    land.rig.git("config", "user.email", NOT_NOREPLY)
    tip = land.tip()
    seen = _lane_refused(attempt("lane: personal author\n"), "author_not_noreply")
    if seen is not None or land.tip() != tip:
        mismatches["author_not_noreply"] = str(seen)
    land.rig.git("config", "user.email", NOREPLY)
    for name, trailer in TRAILERS.items():
        tip = land.tip()
        seen = _lane_refused(attempt(f"lane: work\n\n{trailer}\n"), "attribution")
        if seen is not None or land.tip() != tip:
            mismatches[f"attribution:{name}"] = str(seen)
    for var in IDENTITY_VARS:
        tip = land.tip()
        seen = _lane_refused(
            attempt("lane: work\n", {var: INTRUDER}), "identity_env", var
        )
        if seen is not None or land.tip() != tip:
            mismatches[f"identity_env:{var}"] = str(seen)
    assert mismatches == {}, mismatches
    proc = attempt("lane: the control commit\n")
    assert proc.returncode == 0 and "commit_ok:" in proc.stdout, proc.stdout
    shown = land.git("show", "-s", "--format=%ae|%ce", land.tip()).strip()
    assert shown == f"{NOREPLY}|{NOREPLY}", shown


def test_ac_939_5_land_message_with_a_trailer_refuses_at_prepare(
    tmp_path: Path,
) -> None:
    """AC-939.5: ``_land_message`` / ``store_land_message`` refuse a trailer before the land op exists."""
    from tools.tests import test_lanes_land as tl

    for name, trailer in TRAILERS.items():
        land = _lane(tmp_path / name)
        land.message.write_bytes(f"land: the fixture lane\n\n{trailer}\n".encode())
        proc = tl._prepare(land)
        assert _lane_refused(proc, "attribution") is None, (
            name,
            proc.stdout,
            proc.stderr,
        )
        assert tl._op_file(land) is None, "no land op is written"
        assert land.rig.ref() == land.p


def test_ac_939_5_land_publish_binds_the_identity(tmp_path: Path) -> None:
    """AC-939.5: on the land publish an override refuses ``identity_env:<var>``; main stays at P."""
    from tools.tests import test_lanes_land as tl

    mismatches: dict[str, str] = {}
    for var in IDENTITY_VARS:
        land = _lane(tmp_path / var)
        tl._ready(land)
        seen = _lane_refused(
            tl._publish_human(land, env={var: INTRUDER}), "identity_env", var
        )
        if seen is not None or land.rig.ref() != land.p:
            mismatches[var] = str(seen)
    assert mismatches == {}, mismatches


def test_ac_939_5_land_refuses_a_personal_author(tmp_path: Path) -> None:
    """AC-939.5: a land whose commit identity is not the noreply address refuses; main stays at P."""
    from tools.tests import test_lanes_land as tl

    land = _lane(tmp_path)
    land.rig.git("config", "user.email", NOT_NOREPLY)
    proc = tl._prepare(land)
    if proc.returncode == 0:
        tree = tl._ready_tree(proc)
        tl._ok(tl._verdict(land, tree))
        proc = tl._publish_human(land)
    assert _lane_refused(proc, "author_not_noreply") is None, (proc.stdout, proc.stderr)
    assert land.rig.ref() == land.p


# -- AC-939.13: the narrowed _withdrawn -----------------------------------------------------------


def test_ac_939_13_withdrawn_reads_only_leading_withdrawals() -> None:
    """AC-939.13: a sentence withdraws only by a leading word, an opening conditional or a governed negator."""
    cb = _cb()
    ki = [
        f"Commit the {KI_PLAN} plan.",
        "Also file an issue about commit not being auto executed so this can be "
        "investigated later.",
    ]
    table: list[tuple[list[str], bool, bool]] = [
        (ki, False, False),
        (["Commit.", "No, wait."], False, True),
        (["Commit.", "Don't commit the tests."], False, True),
        (["Commit.", "Never commit the generated files."], False, True),
        (["Can you commit?", "Only if the tests pass."], True, True),
        (["Commit.", "Unless the gate is red."], False, True),
        (["Commit.", "Please wait."], False, True),
        (["Commit.", "But wait."], False, True),
        (["Commit.", "The tests pass if you run them twice."], False, False),
        (["Commit.", "I did not run the slow tests."], False, False),
        (["Can you commit?", "Do not push."], True, False),
        (["Can you commit?", "Why did the last one fail?"], True, True),
    ]
    wrong = {
        " ".join(sentences): expected
        for sentences, question, expected in table
        if cb._withdrawn(sentences, 0, question) is not expected
    }
    assert wrong == {}, wrong


def test_ac_939_13_direction_messages_on_the_human_route(tmp_path: Path) -> None:
    """AC-939.13: the KI message and "Do not push." commit; the withdrawing forms refuse."""
    ki_rig = _rig(tmp_path, "ki")
    ki_rig.bind()
    ki_rig.seed(
        {
            f"docs/execution/plans/{KI_PLAN}/task.md": _legacy_text(KI_PLAN).encode(),
            f"docs/execution/plans/{KI_PLAN}/implementation-plan.md": (
                f"# Plan: {KI_PLAN}\n".encode()
            ),
        },
        message="fixture: the KI plan",
    )
    rig = _rig(tmp_path, "fx")
    rig.bind()
    cases: list[tuple[b3.Rig, str, str | None, str]] = [
        (
            ki_rig,
            f"Commit the {KI_PLAN} plan. Also file an issue about commit not being auto "
            "executed so this can be investigated later.",
            KI_PLAN,
            "reconciled",
        ),
        (rig, "Can you commit? Do not push.", None, "reconciled"),
        (rig, "Commit. Don't commit the tests.", None, "refused:no_commit_direction"),
        (rig, "Commit, unless the gate is red.", None, "refused:no_commit_direction"),
        (rig, "Commit. No, wait.", None, "refused:no_commit_direction"),
        (
            rig,
            "Can you commit? Only if the tests pass.",
            None,
            "refused:no_commit_direction",
        ),
    ]
    mismatches: dict[str, str] = {}
    for number, (where, text, plan, expected) in enumerate(cases):
        uid = where.fx.add_human(text)
        packet = where.packet(files={f"direction_{number}.txt": b"d\n"}, plan=plan)
        before = where.ref()
        got = _outcome(where.human(uid, packet))
        if got != expected:
            mismatches[text] = got
        elif expected != "reconciled" and where.ref() != before:
            mismatches[text] = "the ref moved"
    assert mismatches == {}, mismatches


# -- AC-939.14: one direction covers a whole batch ---------------------------------------------


def test_ac_939_14_one_direction_covers_a_three_commit_batch(tmp_path: Path) -> None:
    """AC-939.14: a three-packet batch commits on one direction; a second batch on it refuses."""
    rig = _rig(tmp_path)
    rig.bind()
    uid = rig.fx.add_human("Commit.")
    parent = rig.ref()
    packets = [
        rig.packet(files={f"batch_{n}.txt": f"{n}\n".encode()}, parent=parent)
        for n in range(3)
    ]
    out = _reconciled(rig.human(uid, rig.batch(packets)))
    assert len(out["commits"]) == 3, out
    assert out["op"] == f"human-{uid}", out
    assert _claim(rig.fx, uid).get("state") == "spent", _claim(rig.fx, uid)
    after = rig.ref()
    again = [
        rig.packet(files={f"again_{n}.txt": f"{n}\n".encode()}, parent=after)
        for n in range(3)
    ]
    reason, _detail = _commit_refusal(rig.human(uid, rig.batch(again)))
    assert reason in {"packet_mismatch", "direction_spent"}, reason
    assert rig.ref() == after
    assert _claim(rig.fx, uid).get("state") == "spent"
