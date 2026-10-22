"""MEU-784 AC-784.11–18: the ``refs/heads/main`` reference-transaction guard — red first (G19).

FIC: ``docs/execution/plans/2026-10-20-multi-agent-lanes/implementation-plan.md``
§MEU-784 (AC-784.11 to AC-784.18; design §5.1 "The ref guard", §9.2 installer,
§10b N-1, N-2, N-6, N-8).

The pure predicate (``decide``) and the store lookup (``load_intents``) run on every
platform. The installer, the chaining and the acceptance matrix need the guard
installed, which happens on Git for Windows only (D§9.2 platform boundary), so those
tests carry the ``WINDOWS`` marker and the POSIX ``not installed`` case carries the
inverse one (precedent: ``tests/tooling/test_executor_worktree.py`` AC-659.6). Test
names keep the row selectors of ``task.md`` exact: rows 11 (``decide or intent or
lock``) and 13 (``install or chain``). Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import copy
import importlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable

import pytest

if TYPE_CHECKING:
    # The commit_batch rig is imported only by the Windows acceptance rows
    # (``_guarded_rig``): an install on any other OS removes ``run_parameters_fixtures``
    # (``scripts/instantiate.py`` RUN_PARAMETERS_WINDOWS_ONLY), and the portable rows of
    # this file must still collect there (AC-784.18 ``wsl-adopter``).
    from tools.tests.run_parameters_fixtures import phase_b3 as b3

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "ref_guard.py"
SWITCH = "{{PROJECT_NAME_UPPER}}_REF_GUARD"
MAIN = "refs/heads/main"
ZERO = "0" * 40
ZERO64 = "0" * 64
P = "1" * 40
C = "2" * 40
X = "3" * 40
P64 = "4" * 64
HOOK = "reference-transaction"
INTENT_FIELDS = ("repo", "ref", "ref_old", "ref_new", "op", "candidate")
INVENTORY_KEYS = {
    "schema",
    "interpreter",
    "guard",
    "hook_path",
    "chained_local",
    "previous",
    "git_version",
    "installed",
}
PREVIOUS_KEYS = ("gc.packRefs", "maintenance.pack-refs.enabled")
# Generous for one Python start on a loaded host; a guard that waits on store.lock never ends.
HOOK_MAX_S = 5.0
OP = "op-1"
PLAN = "2026-10-20-lane-a"
RUN = "interactive"
OPEN_JOURNAL: list[tuple[str, str]] = [
    ("prepared", "started"),
    ("prepared", "done"),
    ("candidate_verified", "started"),
    ("candidate_verified", "done"),
]

WINDOWS = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the guard installs on Git for Windows only (D§9.2 platform boundary, AC-784.15)",
)
POSIX = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the POSIX install refusal (AC-784.15, AC-784.18) runs where the guard is not installed",
)


# -- helpers ---------------------------------------------------------------------------------


def _ref_guard() -> ModuleType:
    """The module under test, imported inside a test body (a Red import error is a failure)."""
    return importlib.import_module("tools.ref_guard")


def _env(**extra: str | None) -> dict[str, str]:
    """``build_fixture.git_env`` (inlined, see the rig import) without the human escape
    switch, plus ``extra``."""
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env.pop(SWITCH, None)
    for key, value in extra.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def _run(
    argv: list[str],
    cwd: Path,
    *,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env if env is not None else _env(),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _git(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd, env=env)


def _ok(cwd: Path, *args: str) -> str:
    proc = _git(cwd, *args)
    assert proc.returncode == 0, (args, proc.stdout, proc.stderr)
    return proc.stdout.strip()


def _guard(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """``python tools/ref_guard.py <args>`` from the source tree, run in ``cwd``."""
    return _run([sys.executable, str(GUARD), *args], cwd, **kwargs)


def _text(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


def _configure(repo: Path) -> None:
    for key, value in (
        ("user.name", "Fixture"),
        ("user.email", "fixture@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
    ):
        _ok(repo, "config", key, value)


def _new_repo(path: Path, *init: str) -> Path:
    path.mkdir(parents=True)
    _ok(path, "init", "-q", "-b", "main", *init)
    _configure(path)
    return path


def _commit(repo: Path, rel: str, data: bytes) -> str:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    _ok(repo, "add", "--", rel)
    _ok(repo, "commit", "-q", "-m", f"fixture: {rel}")
    return _ok(repo, "rev-parse", "HEAD")


def _main(repo: Path) -> str:
    return _ok(repo, "rev-parse", "--verify", "-q", MAIN)


def _common(repo: Path) -> Path:
    return repo / ".git"


def _hooks(repo: Path) -> Path:
    return _common(repo) / "hooks"


def _inventory_path(repo: Path) -> Path:
    return _common(repo) / "lanes" / "ref-guard.json"


def _inventory(repo: Path) -> dict[str, Any]:
    data = json.loads(_inventory_path(repo).read_text(encoding="utf-8"))
    assert isinstance(data, dict), data
    return data


def _config(repo: Path, key: str) -> str | None:
    proc = _git(repo, "config", "--get", key)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _seeded(tmp_path: Path, name: str = "repo") -> tuple[Path, str]:
    """A files-backend repository with one commit on ``main``: (repo, tip)."""
    repo = _new_repo(tmp_path / name)
    return repo, _commit(repo, "a.txt", b"a\n")


def _installed(repo: Path) -> None:
    proc = _guard(repo, "install")
    assert proc.returncode == 0, _text(proc)


def _line(old: str, new: str, ref: str = MAIN) -> str:
    return f"{old} {new} {ref}"


def _intent(**over: str) -> dict[str, str]:
    doc = {
        "repo": "D:/fixture/.git",
        "ref": MAIN,
        "ref_old": P,
        "ref_new": C,
        "op": OP,
        "candidate": C,
    }
    doc.update(over)
    return doc


def _evidence(common: Path, op: str, old: str = P, new: str = C) -> dict[str, str]:
    return {
        "repo": str(common),
        "ref": MAIN,
        "ref_old": old,
        "ref_new": new,
        "op": op,
        "candidate": new,
    }


def _write_op(
    common: Path,
    op: str,
    entries: list[tuple[str, str, dict[str, Any]]],
    plan: str = PLAN,
    run: str = RUN,
) -> Path:
    """An ``op.json`` in the run-parameters store layout (``ops/<plan>/<run>/<op>``)."""
    path = common / "run-parameters" / "ops" / plan / run / op / "op.json"
    journal = [
        {
            "phase": phase,
            "status": status,
            "evidence": evidence,
            "identity": {"op": op, "run_id": run, "plan": plan},
            "seq": seq,
            "ts": "2026-10-21T00:00:00Z",
        }
        for seq, (phase, status, evidence) in enumerate(entries, start=1)
    ]
    doc = {"schema": "commit-op/1", "identity": {"op": op}, "journal": journal}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def _open_entries(evidence: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    rows: list[tuple[str, str, dict[str, Any]]] = [(p, s, {}) for p, s in OPEN_JOURNAL]
    rows.append(("published", "started", evidence))
    return rows


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _refused_reason(reason: str | None) -> str:
    assert isinstance(reason, str), reason
    return reason


# -- AC-784.11: the pure predicate --------------------------------------------------------


def test_ac784_11_decide_rule_1_same_id_allows() -> None:
    guard = _ref_guard()
    assert guard.decide("prepared", [_line(P, P)], [], False, {}) is None
    assert guard.decide("prepared", [_line(P64, P64)], [], False, {}) is None


def test_ac784_11_decide_rule_2_one_main_line_with_a_matching_intent_allows() -> None:
    guard = _ref_guard()
    assert guard.decide("prepared", [_line(P, C)], [_intent()], False, {}) is None
    lines = [_line(P, C, "HEAD"), _line(ZERO, X, "refs/heads/lane/x"), _line(P, C)]
    assert (
        guard.decide(
            "prepared", lines, [_intent(), _intent(op="op-2", ref_old=X)], False, {}
        )
        is None
    )


def test_ac784_11_decide_counts_only_refs_heads_main() -> None:
    guard = _ref_guard()
    lines = [
        _line(P, C, "HEAD"),
        _line(ZERO, C, "refs/heads/lane/x"),
        _line(P, ZERO, "refs/heads/lane/y"),
        _line(P, "ref:refs/heads/lane/x", "HEAD"),
        _line("ref:refs/heads/main", "ref:refs/heads/lane/x", "HEAD"),
        _line(P, C, "refs/heads/main2"),
        _line(P, C, "refs/heads/mainline"),
        _line(P, C, "refs/heads/lane/main"),
        _line(P, C, "refs/remotes/origin/main"),
        _line(P, C, "refs/tags/main"),
    ]
    assert guard.decide("prepared", lines, [], False, {}) is None


REFUSED_VECTORS: dict[str, tuple[list[str], list[dict[str, str]]]] = {
    "zero_to_p": ([_line(ZERO, P)], []),
    "zero_to_p_with_intent": (
        [_line(ZERO, P)],
        [_intent(ref_old=ZERO, ref_new=P, candidate=P)],
    ),
    "p_to_zero": ([_line(P, ZERO)], [_intent()]),
    "p_to_zero64": ([_line(P64, ZERO64)], []),
    "zero_to_zero": ([_line(ZERO, ZERO)], []),
    "symbolic_new": ([_line(P, "ref:refs/heads/x")], [_intent()]),
    "symbolic_old": ([_line("ref:refs/heads/x", C)], [_intent()]),
    "no_intent": ([_line(P, C)], []),
    "second_main_line": ([_line(P, C), _line(P, C)], [_intent()]),
    "second_main_line_other_ids": ([_line(P, C), _line(C, X)], [_intent()]),
    "wrong_candidate": ([_line(P, C)], [_intent(candidate=X)]),
    "wrong_ref_old": ([_line(P, C)], [_intent(ref_old=X)]),
    "wrong_ref_new": ([_line(P, C)], [_intent(ref_new=X)]),
    "wrong_ref": ([_line(P, C)], [_intent(ref="refs/heads/lane/x")]),
}


@pytest.mark.parametrize("name", sorted(REFUSED_VECTORS))
def test_ac784_11_decide_rule_3_refuses_and_names_commit_batch(name: str) -> None:
    guard = _ref_guard()
    lines, intents = REFUSED_VECTORS[name]
    reason = _refused_reason(guard.decide("prepared", lines, intents, False, {}))
    assert "tools/commit_batch.py" in reason, (name, reason)


def test_ac784_11_decide_intent_missing_any_field_is_no_match() -> None:
    guard = _ref_guard()
    for field in INTENT_FIELDS:
        partial = _intent()
        del partial[field]
        reason = _refused_reason(
            guard.decide("prepared", [_line(P, C)], [partial], False, {})
        )
        assert "tools/commit_batch.py" in reason, (field, reason)


def test_ac784_11_decide_rule_4_halt_refuses_a_matching_intent() -> None:
    guard = _ref_guard()
    reason = _refused_reason(
        guard.decide("prepared", [_line(P, C)], [_intent()], True, {})
    )
    assert reason.startswith("halt"), reason
    # HALT stops publications to main; other refs and HEAD still move.
    lines = [_line(P, C, "HEAD"), _line(ZERO, C, "refs/heads/lane/x")]
    assert guard.decide("prepared", lines, [], True, {}) is None


def test_ac784_11_decide_off_switch_is_the_exact_value_off() -> None:
    guard = _ref_guard()
    assert guard.decide("prepared", [_line(P, C)], [], False, {SWITCH: "off"}) is None
    assert (
        guard.decide("prepared", [_line(P, ZERO)], [], False, {SWITCH: "off"}) is None
    )
    for value in ("OFF", "Off", "0", "false", "no", "", "off ", " off", "disabled"):
        reason = _refused_reason(
            guard.decide("prepared", [_line(P, C)], [], False, {SWITCH: value})
        )
        assert "tools/commit_batch.py" in reason, (value, reason)


def test_ac784_11_decide_only_prepared_decides() -> None:
    guard = _ref_guard()
    for phase in ("preparing", "committed", "aborted"):
        assert guard.decide(phase, [_line(P, C)], [], False, {}) is None, phase
        assert guard.decide(phase, [_line(P, ZERO)], [], True, {}) is None, phase
        assert guard.decide(phase, ["not a ref line"], [], False, {}) is None, phase


MALFORMED = (
    "not a ref line",
    f"{P} {C}",
    f"{P[:-1]} {C} {MAIN}",
    f"{P} {C}1 {MAIN}",
    f"{'g' * 40} {C} {MAIN}",
    f"{P} {C} {MAIN} extra",
    f"{P} ref: {MAIN}",
)


def test_ac784_11_decide_malformed_line_in_prepared_is_stdin_bad() -> None:
    guard = _ref_guard()
    for line in MALFORMED:
        reason = _refused_reason(
            guard.decide("prepared", [line], [_intent()], False, {})
        )
        assert reason.startswith("stdin_bad"), (line, reason)
        # A malformed line refuses even next to a valid, matching main line.
        mixed = [_line(P, C), line]
        reason = _refused_reason(
            guard.decide("prepared", mixed, [_intent()], False, {})
        )
        assert reason.startswith("stdin_bad"), (line, reason)


# -- AC-784.12: the intent lookup ----------------------------------------------------------


def test_ac784_12_intent_lookup_keeps_only_an_open_publication(tmp_path: Path) -> None:
    guard = _ref_guard()
    common = tmp_path / "repo" / ".git"
    common.mkdir(parents=True)
    open_ev = _evidence(common, "op-open")
    _write_op(common, "op-open", _open_entries(open_ev))
    done = _open_entries(_evidence(common, "op-done"))
    done.append(("published", "done", {"ref_old": P, "ref_new": C}))
    _write_op(common, "op-done", done)
    superseded = _open_entries(_evidence(common, "op-later"))
    superseded.append(("index_reconciled", "started", {"paths": ["a.txt"]}))
    _write_op(common, "op-later", superseded)
    other = _evidence(tmp_path / "other" / ".git", "op-other")
    _write_op(common, "op-other", _open_entries(other))
    _write_op(common, "op-early", [(p, s, {}) for p, s in OPEN_JOURNAL])
    for field in INTENT_FIELDS:
        partial: dict[str, Any] = _evidence(common, f"op-no-{field}")
        del partial[field]
        _write_op(common, f"op-no-{field}", _open_entries(partial))
    numeric: dict[str, Any] = _evidence(common, "op-numeric")
    numeric["candidate"] = 2
    _write_op(common, "op-numeric", _open_entries(numeric))
    _write_op(
        common,
        "op-other-run",
        _open_entries(_evidence(common, "op-other-run")),
        plan="2026-10-20-lane-b",
        run="credits-x",
    )

    before = _files(common)
    intents = guard.load_intents(common)
    assert sorted(item["op"] for item in intents) == ["op-open", "op-other-run"], (
        intents
    )
    by_op = {item["op"]: item for item in intents}
    assert {key: by_op["op-open"][key] for key in INTENT_FIELDS} == open_ev
    # Read-only: no byte of the store changes and no file appears.
    assert _files(common) == before


def test_ac784_12_intent_lookup_without_a_store_is_empty(tmp_path: Path) -> None:
    guard = _ref_guard()
    common = tmp_path / "repo" / ".git"
    common.mkdir(parents=True)
    assert list(guard.load_intents(common)) == []
    assert _files(common) == {}


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows paths are case-blind and take either slash"
)
def test_ac784_12_intent_lookup_normalizes_the_repo_spelling(tmp_path: Path) -> None:
    guard = _ref_guard()
    common = tmp_path / "repo" / ".git"
    common.mkdir(parents=True)
    spelled = _evidence(common, "op-spelled")
    spelled["repo"] = common.as_posix().swapcase()
    _write_op(common, "op-spelled", _open_entries(spelled))
    assert [item["op"] for item in guard.load_intents(common)] == ["op-spelled"]


def test_ac784_12_hook_reads_the_intent_from_the_store(tmp_path: Path) -> None:
    repo, tip = _seeded(tmp_path)
    tree = _ok(repo, "rev-parse", "HEAD^{tree}")
    candidate = _ok(repo, "commit-tree", tree, "-p", tip, "-m", "candidate")
    line = _line(tip, candidate) + "\n"
    _write_op(
        _common(repo), OP, _open_entries(_evidence(_common(repo), OP, tip, candidate))
    )
    allowed = _guard(repo, "hook", "prepared", stdin=line)
    assert allowed.returncode == 0, _text(allowed)
    done = _open_entries(_evidence(_common(repo), OP, tip, candidate))
    done.append(("published", "done", {"ref_old": tip, "ref_new": candidate}))
    _write_op(_common(repo), OP, done)
    refused = _guard(repo, "hook", "prepared", stdin=line)
    assert refused.returncode == 1, _text(refused)
    assert "tools/commit_batch.py" in refused.stderr, _text(refused)


def test_ac784_12_hook_intent_under_halt_refuses(tmp_path: Path) -> None:
    repo, tip = _seeded(tmp_path)
    tree = _ok(repo, "rev-parse", "HEAD^{tree}")
    candidate = _ok(repo, "commit-tree", tree, "-p", tip, "-m", "candidate")
    _write_op(
        _common(repo), OP, _open_entries(_evidence(_common(repo), OP, tip, candidate))
    )
    halt = _common(repo) / "lanes" / "HALT"
    halt.parent.mkdir(parents=True)
    halt.write_bytes(b"stopped by the human\n")
    proc = _guard(repo, "hook", "prepared", stdin=_line(tip, candidate) + "\n")
    assert proc.returncode == 1, _text(proc)
    assert "halt" in proc.stderr.lower(), _text(proc)


def test_ac784_11_hook_decide_refuses_main_on_stderr_and_passes_lanes(
    tmp_path: Path,
) -> None:
    repo, tip = _seeded(tmp_path)
    refused = _guard(repo, "hook", "prepared", stdin=_line(tip, X) + "\n")
    assert refused.returncode == 1, _text(refused)
    assert "tools/commit_batch.py" in refused.stderr, _text(refused)
    lane = _guard(
        repo, "hook", "prepared", stdin=_line(ZERO, tip, "refs/heads/lane/x") + "\n"
    )
    assert lane.returncode == 0, _text(lane)
    bad = _guard(repo, "hook", "prepared", stdin=f"{tip} {X}\n")
    assert bad.returncode == 1, _text(bad)
    assert "stdin_bad" in bad.stderr, _text(bad)
    off = _guard(
        repo,
        "hook",
        "prepared",
        stdin=_line(tip, X) + "\n",
        env=_env(**{SWITCH: "off"}),
    )
    assert off.returncode == 0, _text(off)


# -- AC-784.14: no lock, no state ------------------------------------------------------------


def test_ac784_14_no_lock_taken_with_store_lock_held(tmp_path: Path) -> None:
    repo, tip = _seeded(tmp_path)
    lock = _common(repo) / "run-parameters" / "store.lock"
    lock.parent.mkdir(parents=True)
    lock.write_bytes(b'{"pid": 1, "argv": ["commit_batch.py"]}\n')
    for stdin, expected in (
        (_line(ZERO, tip, "refs/heads/lane/x") + "\n", 0),
        (_line(tip, X) + "\n", 1),
    ):
        start = time.monotonic()
        proc = _guard(repo, "hook", "prepared", stdin=stdin, timeout=HOOK_MAX_S * 6)
        elapsed = time.monotonic() - start
        assert proc.returncode == expected, _text(proc)
        assert elapsed < HOOK_MAX_S, elapsed
    assert lock.read_bytes() == b'{"pid": 1, "argv": ["commit_batch.py"]}\n'


def test_ac784_14_no_lock_and_no_store_read_outside_prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = _ref_guard()
    repo, tip = _seeded(tmp_path)

    def _no_read(*_args: object, **_kwargs: object) -> list[dict[str, Any]]:
        raise AssertionError("the store was read outside prepared")

    monkeypatch.setattr(guard, "load_intents", _no_read)
    monkeypatch.chdir(repo)
    before = _files(_common(repo))
    for phase in ("preparing", "committed", "aborted"):
        for stdin in (_line(tip, X) + "\n", "not a ref line\n"):
            assert (
                guard.main(["hook", phase], stdin=stdin.encode("ascii"), env={}) == 0
            ), phase
    # Keeps no state: the common dir is byte-for-byte unchanged.
    assert _files(_common(repo)) == before


# -- AC-784.15: the installer --------------------------------------------------------------


def test_ac784_15_install_parses_the_git_version() -> None:
    guard = _ref_guard()
    assert guard.MIN_GIT == (2, 46, 0)
    assert guard._parse_git_version("git version 2.45.2.windows.1") == (2, 45, 2)
    assert guard._parse_git_version("git version 2.46.0") == (2, 46, 0)
    assert guard._parse_git_version("git version 2.56.0.windows.1\n") == (2, 56, 0)


@WINDOWS
def test_ac784_15_install_writes_the_shim_inventory_and_config(tmp_path: Path) -> None:
    guard = _ref_guard()
    repo, tip = _seeded(tmp_path)
    _installed(repo)
    shim = _hooks(repo) / HOOK
    text = shim.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n"), text
    assert "ref_guard.py" in text and " hook" in text, text
    inv = _inventory(repo)
    assert set(inv) == INVENTORY_KEYS, inv
    assert inv["schema"] == "ref-guard/1"
    assert os.path.samefile(inv["interpreter"], sys.executable), inv
    assert inv["interpreter"] in text or Path(inv["interpreter"]).as_posix() in text, (
        text
    )
    assert os.path.samefile(inv["guard"], GUARD), inv
    assert os.path.samefile(inv["hook_path"], shim), inv
    assert inv["chained_local"] is False
    assert inv["previous"] == {key: None for key in PREVIOUS_KEYS}, inv
    version = guard._parse_git_version(_ok(repo, "--version"))
    assert inv["git_version"] == ".".join(str(n) for n in version), inv
    assert isinstance(inv["installed"], str) and inv["installed"], inv
    for key in PREVIOUS_KEYS:
        assert _config(repo, key) == "false", key
    assert not (_hooks(repo) / f"{HOOK}.local").exists()
    assert _main(repo) == tip


@WINDOWS
def test_ac784_15_install_twice_is_one_shim_and_no_local_loop(tmp_path: Path) -> None:
    repo, _tip = _seeded(tmp_path)
    foreign = b"#!/bin/sh\ncat >/dev/null\nexit 0\n"
    (_hooks(repo) / HOOK).write_bytes(foreign)
    _installed(repo)
    shim = (_hooks(repo) / HOOK).read_bytes()
    first = _inventory(repo)
    _installed(repo)
    assert (_hooks(repo) / HOOK).read_bytes() == shim
    assert (_hooks(repo) / f"{HOOK}.local").read_bytes() == foreign
    names = sorted(p.name for p in _hooks(repo).iterdir() if p.name.startswith(HOOK))
    assert names == [HOOK, f"{HOOK}.local"], names
    second = _inventory(repo)
    assert second["chained_local"] is True
    # The second install records nothing new: the previous values are the first ones.
    assert (
        second["previous"] == first["previous"] == {key: None for key in PREVIOUS_KEYS}
    )


@WINDOWS
def test_ac784_15_install_refuses_reftable(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path / "repo", "--ref-format=reftable")
    _commit(repo, "a.txt", b"a\n")
    _install_refused(repo, "reftable_unsupported")


@WINDOWS
def test_ac784_15_install_refuses_a_packed_main_and_names_the_human_step(
    tmp_path: Path,
) -> None:
    repo, tip = _seeded(tmp_path)
    _ok(repo, "pack-refs", "--all")
    assert not (_common(repo) / "refs" / "heads" / "main").exists()
    proc = _install_refused(repo, "main_packed")
    assert "human" in _text(proc).lower(), _text(proc)
    assert _main(repo) == tip


@WINDOWS
def test_ac784_15_install_refuses_a_hooks_path_outside_the_repository(
    tmp_path: Path,
) -> None:
    repo, _tip = _seeded(tmp_path)
    outside = tmp_path / "shared-hooks"
    outside.mkdir()
    _ok(repo, "config", "core.hooksPath", str(outside))
    _install_refused(repo, "hooks_path_unsupported")
    assert list(outside.iterdir()) == []


@WINDOWS
def test_ac784_15_install_refuses_a_foreign_hook_when_local_exists(
    tmp_path: Path,
) -> None:
    repo, _tip = _seeded(tmp_path)
    (_hooks(repo) / HOOK).write_bytes(b"#!/bin/sh\nexit 0\n")
    (_hooks(repo) / f"{HOOK}.local").write_bytes(b"#!/bin/sh\nexit 0\n")
    _install_refused(repo, "local_exists")
    assert (_hooks(repo) / HOOK).read_bytes() == b"#!/bin/sh\nexit 0\n"


@WINDOWS
def test_ac784_15_install_refuses_git_too_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    guard = _ref_guard()
    repo, _tip = _seeded(tmp_path)
    monkeypatch.setattr(guard, "_git_version", lambda *_a, **_k: (2, 45, 2))
    monkeypatch.chdir(repo)
    assert guard.main(["install"]) == 1
    assert "refused: git_too_old" in capsys.readouterr().out
    _nothing_installed(repo)


def _install_refused(repo: Path, reason: str) -> subprocess.CompletedProcess[str]:
    proc = _guard(repo, "install")
    assert proc.returncode == 1, _text(proc)
    assert f"refused: {reason}" in proc.stdout, _text(proc)
    _nothing_installed(repo)
    return proc


def _nothing_installed(repo: Path) -> None:
    assert not _inventory_path(repo).exists()
    for key in PREVIOUS_KEYS:
        assert _config(repo, key) is None, key
    shim = _hooks(repo) / HOOK
    assert not shim.exists() or b"ref_guard.py" not in shim.read_bytes()


@WINDOWS
def test_ac784_15_uninstall_restores_the_hook_the_local_and_the_config(
    tmp_path: Path,
) -> None:
    repo, _tip = _seeded(tmp_path)
    foreign = b"#!/bin/sh\ncat >/dev/null\nexit 0\n"
    (_hooks(repo) / HOOK).write_bytes(foreign)
    _ok(repo, "config", "gc.packRefs", "true")
    _installed(repo)
    assert _inventory(repo)["previous"] == {
        "gc.packRefs": "true",
        "maintenance.pack-refs.enabled": None,
    }
    proc = _guard(repo, "uninstall")
    assert proc.returncode == 0, _text(proc)
    assert (_hooks(repo) / HOOK).read_bytes() == foreign
    assert not (_hooks(repo) / f"{HOOK}.local").exists()
    assert _config(repo, "gc.packRefs") == "true"
    assert _config(repo, "maintenance.pack-refs.enabled") is None
    assert not _inventory_path(repo).exists()


@WINDOWS
def test_ac784_15_uninstall_without_a_foreign_hook_removes_the_shim(
    tmp_path: Path,
) -> None:
    repo, _tip = _seeded(tmp_path)
    _installed(repo)
    proc = _guard(repo, "uninstall")
    assert proc.returncode == 0, _text(proc)
    assert not (_hooks(repo) / HOOK).exists()
    _nothing_installed(repo)


@WINDOWS
def test_ac784_15_uninstall_refuses_a_bad_inventory(tmp_path: Path) -> None:
    repo, _tip = _seeded(tmp_path)
    _installed(repo)
    doc = _inventory(repo)
    doc["extra"] = True
    _inventory_path(repo).write_text(json.dumps(doc) + "\n", encoding="utf-8")
    proc = _guard(repo, "uninstall")
    assert proc.returncode == 1, _text(proc)
    assert "refused: inventory_bad" in proc.stdout, _text(proc)
    assert b"ref_guard.py" in (_hooks(repo) / HOOK).read_bytes()


def _hooks_path_env(tmp_path: Path, scope: str, hooks: Path) -> dict[str, str]:
    """An environment whose ``scope`` git config file sets ``core.hooksPath`` to ``hooks``."""
    config = tmp_path / f"{scope}.gitconfig"
    config.write_text(f"[core]\n\thooksPath = {hooks.as_posix()}\n", encoding="utf-8")
    if scope == "system":
        return _env(GIT_CONFIG_NOSYSTEM=None, GIT_CONFIG_SYSTEM=str(config))
    return _env(GIT_CONFIG_GLOBAL=str(config))


@WINDOWS
@pytest.mark.parametrize("scope", ["system", "global"])
def test_ac784_15_install_follows_a_system_or_global_hooks_path(
    tmp_path: Path, scope: str
) -> None:
    # R1-F1: git reads core.hooksPath from the system and global files too, so the
    # installer must, or the shim lands in a folder git never runs.
    repo, tip = _seeded(tmp_path)
    hooks = repo / f"{scope}-hooks"
    hooks.mkdir()
    env = _hooks_path_env(tmp_path, scope, hooks)
    proc = _guard(repo, "install", env=env)
    assert proc.returncode == 0, _text(proc)
    assert b"ref_guard.py" in (hooks / HOOK).read_bytes()
    assert not (_hooks(repo) / HOOK).exists()
    assert os.path.samefile(_inventory(repo)["hook_path"], hooks / HOOK)
    tree = _ok(repo, "rev-parse", "HEAD^{tree}")
    other = _ok(repo, "commit-tree", tree, "-p", tip, "-m", "other")
    moved = _git(repo, "update-ref", MAIN, other, tip, env=env)
    assert moved.returncode != 0, _text(moved)
    assert "tools/commit_batch.py" in _text(moved), _text(moved)
    assert _main(repo) == tip


@WINDOWS
@pytest.mark.parametrize("scope", ["system", "global"])
def test_ac784_15_install_refuses_a_system_or_global_hooks_path_outside_the_repository(
    tmp_path: Path, scope: str
) -> None:
    repo, _tip = _seeded(tmp_path)
    outside = tmp_path / f"{scope}-hooks"
    outside.mkdir()
    proc = _guard(repo, "install", env=_hooks_path_env(tmp_path, scope, outside))
    assert proc.returncode == 1, _text(proc)
    assert "refused: hooks_path_unsupported" in proc.stdout, _text(proc)
    _nothing_installed(repo)
    assert list(outside.iterdir()) == []


@WINDOWS
def test_ac784_15_uninstall_after_a_config_failure_restores_everything_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # R1-F5: a config write that fails during uninstall leaves a state the retry finishes.
    guard = _ref_guard()
    repo, _tip = _seeded(tmp_path)
    foreign = b"#!/bin/sh\ncat >/dev/null\nexit 0\n"
    (_hooks(repo) / HOOK).write_bytes(foreign)
    _ok(repo, "config", "gc.packRefs", "true")
    _installed(repo)
    real = guard._config_put
    calls: list[str] = []

    def second_put_fails(cwd: Path, common: Path, key: str, value: str | None) -> None:
        calls.append(key)
        if len(calls) == 2:
            raise guard.Refusal("config_unwritable", "injected")
        real(cwd, common, key, value)

    monkeypatch.setattr(guard, "_config_put", second_put_fails)
    monkeypatch.chdir(repo)
    assert guard.main(["uninstall"]) == 1
    assert "refused: config_unwritable" in capsys.readouterr().out
    monkeypatch.setattr(guard, "_config_put", real)
    assert guard.main(["uninstall"]) == 0, capsys.readouterr().out
    assert (_hooks(repo) / HOOK).read_bytes() == foreign
    assert not (_hooks(repo) / f"{HOOK}.local").exists()
    assert _config(repo, "gc.packRefs") == "true"
    assert _config(repo, "maintenance.pack-refs.enabled") is None
    assert not _inventory_path(repo).exists()


@WINDOWS
def test_ac784_15_uninstall_finishes_after_the_hook_was_already_restored(
    tmp_path: Path,
) -> None:
    # R1-F5: the state an uninstall leaves when it stops after restoring the chained
    # hook (the inventory is still there): a retry completes it.
    repo, _tip = _seeded(tmp_path)
    foreign = b"#!/bin/sh\ncat >/dev/null\nexit 0\n"
    (_hooks(repo) / HOOK).write_bytes(foreign)
    _installed(repo)
    os.replace(_hooks(repo) / f"{HOOK}.local", _hooks(repo) / HOOK)
    proc = _guard(repo, "uninstall")
    assert proc.returncode == 0, _text(proc)
    assert (_hooks(repo) / HOOK).read_bytes() == foreign
    _nothing_installed(repo)


@WINDOWS
def test_ac784_15_concurrent_installs_keep_the_foreign_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # R1-F6: two installs that both look at the hook before either writes must not
    # move the shim over the chained foreign hook.
    guard = _ref_guard()
    repo, _tip = _seeded(tmp_path)
    foreign = b"#!/bin/sh\ncat >/dev/null\nexit 0\n"
    (_hooks(repo) / HOOK).write_bytes(foreign)
    barrier = threading.Barrier(2, timeout=3.0)
    real = guard._is_shim

    def meet(path: Path) -> bool:
        result = real(path)
        if path.name == HOOK:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return result

    monkeypatch.setattr(guard, "_is_shim", meet)
    monkeypatch.chdir(repo)
    codes: list[int] = []
    threads = [
        threading.Thread(target=lambda: codes.append(guard.main(["install"])))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert codes == [0, 0], codes
    assert (_hooks(repo) / f"{HOOK}.local").read_bytes() == foreign
    assert b"ref_guard.py" in (_hooks(repo) / HOOK).read_bytes()
    assert _inventory(repo)["chained_local"] is True


@POSIX
def test_ac784_15_install_on_posix_is_not_installed(tmp_path: Path) -> None:
    repo, _tip = _seeded(tmp_path)
    proc = _guard(repo, "install")
    assert proc.returncode == 4, _text(proc)
    assert "not installed: no governed publish route" in proc.stdout, _text(proc)
    assert not (_hooks(repo) / HOOK).exists()
    _nothing_installed(repo)


# -- AC-784.16: chaining -------------------------------------------------------------------


def _chained(tmp_path: Path, local_body: str) -> tuple[Path, str]:
    repo, tip = _seeded(tmp_path)
    (_hooks(repo) / HOOK).write_bytes(f"#!/bin/sh\n{local_body}\n".encode("utf-8"))
    _installed(repo)
    assert _inventory(repo)["chained_local"] is True
    return repo, tip


@WINDOWS
def test_ac784_16_chain_gives_the_local_the_same_stdin_and_argv(tmp_path: Path) -> None:
    record = tmp_path / "record.txt"
    body = f'{{ echo "argv:$*"; cat; echo "end"; }} >> "{record.as_posix()}"'
    repo, tip = _chained(tmp_path, body)
    _ok(repo, "update-ref", "refs/heads/lane/x", tip)
    text = record.read_bytes().decode("utf-8")
    assert f"argv:prepared\n{ZERO} {tip} refs/heads/lane/x\nend\n" in text, text
    assert f"argv:committed\n{ZERO} {tip} refs/heads/lane/x\nend\n" in text, text


@WINDOWS
def test_ac784_16_chain_local_refusal_refuses_the_update(tmp_path: Path) -> None:
    body = 'cat >/dev/null\nif [ "$1" = prepared ]; then echo local-refused >&2; exit 1; fi\nexit 0'
    repo, tip = _chained(tmp_path, body)
    proc = _git(repo, "update-ref", "refs/heads/lane/x", tip)
    assert proc.returncode != 0, _text(proc)
    assert "local-refused" in _text(proc), _text(proc)
    assert (
        _git(repo, "rev-parse", "--verify", "-q", "refs/heads/lane/x").returncode != 0
    )


@WINDOWS
def test_ac784_16_chain_guard_refuses_main_when_the_local_allows(
    tmp_path: Path,
) -> None:
    repo, tip = _chained(tmp_path, "cat >/dev/null\nexit 0")
    tree = _ok(repo, "rev-parse", "HEAD^{tree}")
    other = _ok(repo, "commit-tree", tree, "-p", tip, "-m", "other")
    proc = _git(repo, "update-ref", MAIN, other, tip)
    assert proc.returncode != 0, _text(proc)
    assert "tools/commit_batch.py" in _text(proc), _text(proc)
    assert _main(repo) == tip


# -- AC-784.17: acceptance in disposable repositories ---------------------------------------


@dataclass(frozen=True)
class Guarded:
    """A guarded repository: ``main`` at ``tip`` over ``base``, a ``side`` branch, an upstream ahead."""

    root: Path
    repo: Path
    base: str
    tip: str
    side: str
    upstream: Path


@pytest.fixture
def guarded(tmp_path: Path) -> Guarded:
    repo = _new_repo(tmp_path / "repo")
    base = _commit(repo, "a.txt", b"a\n")
    _ok(repo, "checkout", "-q", "-b", "side")
    side = _commit(repo, "side.txt", b"side\n")
    _ok(repo, "checkout", "-q", "main")
    tip = _commit(repo, "b.txt", b"b\n")
    upstream = tmp_path / "upstream"
    _ok(tmp_path, "clone", "-q", str(repo), str(upstream))
    _configure(upstream)
    _commit(upstream, "c.txt", b"c\n")
    _installed(repo)
    return Guarded(tmp_path, repo, base, tip, side, upstream)


def _write_and_commit(g: Guarded) -> subprocess.CompletedProcess[str]:
    (g.repo / "d.txt").write_bytes(b"d\n")
    _ok(g.repo, "add", "--", "d.txt")
    return _git(g.repo, "commit", "-q", "-m", "direct")


def _detached(g: Guarded, *args: str) -> subprocess.CompletedProcess[str]:
    _ok(g.repo, "checkout", "-q", "--detach")
    return _git(g.repo, *args)


REFUSED: dict[str, Callable[[Guarded], subprocess.CompletedProcess[str]]] = {
    "commit_on_main": _write_and_commit,
    "update_ref_main": lambda g: _git(g.repo, "update-ref", MAIN, g.side, g.tip),
    "reset": lambda g: _git(g.repo, "reset", "-q", "--hard", g.base),
    "cherry_pick": lambda g: _git(g.repo, "cherry-pick", g.side),
    "rebase_on_main": lambda g: _git(g.repo, "rebase", "-q", "side"),
    "pull": lambda g: _git(g.repo, "pull", "-q", "--ff-only", str(g.upstream), "main"),
    "fetch_into_main": lambda g: _detached(
        g, "fetch", "-q", str(g.upstream), "main:main"
    ),
    "branch_delete_main": lambda g: _detached(g, "branch", "-D", "main"),
    "symbolic_ref_main": lambda g: _git(
        g.repo, "symbolic-ref", MAIN, "refs/heads/side"
    ),
}


@WINDOWS
@pytest.mark.parametrize("name", sorted(REFUSED))
def test_ac784_17_accept_refused_rows_leave_main_unchanged(
    guarded: Guarded, name: str
) -> None:
    proc = REFUSED[name](guarded)
    assert proc.returncode != 0, (name, _text(proc))
    assert "commit_batch.py" in _text(proc), (name, _text(proc))
    assert _main(guarded.repo) == guarded.tip, name


def _maintenance(*args: str) -> Callable[[Guarded], None]:
    def run(g: Guarded) -> None:
        _ok(g.repo, *args)

    return run


def _worktrees(g: Guarded) -> None:
    first = g.root / "wt-1"
    _ok(g.repo, "worktree", "add", "-q", "--detach", str(first))
    _ok(g.repo, "worktree", "remove", str(first))
    second = g.root / "wt-2"
    _ok(g.repo, "worktree", "add", "-q", "-b", "lane/wt", str(second))
    shutil.rmtree(second)
    _ok(g.repo, "worktree", "prune")


def _normal_fetch(g: Guarded) -> None:
    _ok(g.repo, "fetch", "-q", str(g.upstream), "main")
    _ok(g.repo, "fetch", "-q", str(g.upstream), "main:refs/remotes/up/main")


def _detached_candidate(g: Guarded) -> None:
    wt = g.root / "candidate"
    _ok(g.repo, "worktree", "add", "-q", "--detach", str(wt))
    head = _commit(wt, "e.txt", b"e\n")
    assert head != g.tip


def _lane_commit(g: Guarded) -> None:
    _ok(g.repo, "checkout", "-q", "-b", "lane/x")
    head = _commit(g.repo, "f.txt", b"f\n")
    assert _ok(g.repo, "rev-parse", "refs/heads/lane/x") == head


def _head_target(g: Guarded) -> None:
    _ok(g.repo, "checkout", "-q", "side")
    _ok(g.repo, "checkout", "-q", "main")
    _ok(g.repo, "symbolic-ref", "HEAD", "refs/heads/side")
    _ok(g.repo, "symbolic-ref", "HEAD", MAIN)


ALLOWED: dict[str, Callable[[Guarded], None]] = {
    "gc": _maintenance("gc", "-q"),
    "gc_auto": _maintenance("gc", "--auto", "-q"),
    "maintenance_run": _maintenance("maintenance", "run"),
    "maintenance_run_auto": _maintenance("maintenance", "run", "--auto"),
    "pack_refs_auto": _maintenance("pack-refs", "--auto"),
    "pack_refs_all_exclude_main": _maintenance("pack-refs", "--all", "--exclude", MAIN),
    "worktree_add_remove_prune": _worktrees,
    "normal_fetch": _normal_fetch,
    "detached_candidate": _detached_candidate,
    "lane_branch_commit": _lane_commit,
    "head_target_change": _head_target,
}


@WINDOWS
@pytest.mark.parametrize("name", sorted(ALLOWED))
def test_ac784_17_accept_allowed_rows_leave_main_unchanged(
    guarded: Guarded, name: str
) -> None:
    ALLOWED[name](guarded)
    assert _main(guarded.repo) == guarded.tip, name
    # Ref maintenance never packs main (the guard sees loose-ref transactions only, D§5.1).
    assert (_common(guarded.repo) / "refs" / "heads" / "main").is_file(), name


@WINDOWS
def test_ac784_17_accept_off_switch_allows_a_manual_update_ref(
    guarded: Guarded,
) -> None:
    proc = _git(
        guarded.repo,
        "update-ref",
        MAIN,
        guarded.side,
        guarded.tip,
        env=_env(**{SWITCH: "off"}),
    )
    assert proc.returncode == 0, _text(proc)
    assert _main(guarded.repo) == guarded.side


def _guarded_rig(tmp_path: Path) -> b3.Rig:
    """The commit_batch fixture with its outside ``core.hooksPath`` dropped and the guard installed."""
    b3_mod = importlib.import_module("tools.tests.run_parameters_fixtures.phase_b3")
    rig: b3.Rig = b3_mod.rig(tmp_path / "fx", ROOT)
    rig.git("config", "--unset", "core.hooksPath")
    _installed(rig.repo)
    return rig


@WINDOWS
def test_ac784_17_accept_commit_batch_publication_moves_main(tmp_path: Path) -> None:
    rig = _guarded_rig(tmp_path)
    parent = rig.ref()
    rig.reserve(OP)
    code, out, text = rig.commit(OP, rig.packet(), env={SWITCH: None})
    assert (code, out.get("result")) == (0, "reconciled"), text
    assert rig.ref() == out["commit"] != parent


@WINDOWS
def test_ac784_17_accept_halt_refuses_the_publication(tmp_path: Path) -> None:
    rig = _guarded_rig(tmp_path)
    halt = rig.fx.common_dir / "lanes" / "HALT"
    halt.parent.mkdir(parents=True, exist_ok=True)
    halt.write_bytes(b"stopped by the human\n")
    parent = rig.ref()
    rig.reserve(OP)
    code, out, text = rig.commit(OP, rig.packet(), env={SWITCH: None})
    assert code != 0 and out.get("result") != "reconciled", text
    assert rig.ref() == parent
    assert ("published", "done") not in rig.journal(OP)


@WINDOWS
def test_ac784_13_accept_journal_entry_without_a_field_is_refused(
    tmp_path: Path,
) -> None:
    """AC-784.13 negative: the real ``published``/``started`` entry, one field removed → refused."""
    rig = _guarded_rig(tmp_path)
    parent = rig.ref()
    rig.reserve(OP)
    rig.crash(OP, rig.packet(), "published:started")
    assert rig.ref() == parent
    path = rig.op_dir(OP) / "op.json"
    original = path.read_bytes()
    record = json.loads(original.decode("utf-8"))
    last = record["journal"][-1]
    assert (last["phase"], last["status"]) == ("published", "started"), last
    evidence = last.get("evidence")
    assert isinstance(evidence, dict) and set(INTENT_FIELDS) <= set(evidence), last
    commit = str(evidence["candidate"])
    for field in INTENT_FIELDS:
        doc = copy.deepcopy(record)
        del doc["journal"][-1]["evidence"][field]
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        proc = _git(rig.repo, "update-ref", MAIN, commit, parent)
        assert proc.returncode != 0, (field, _text(proc))
        assert "commit_batch.py" in _text(proc), (field, _text(proc))
        assert rig.ref() == parent, field
    # The intact entry is the intent: the same publication now passes.
    path.write_bytes(original)
    proc = _git(rig.repo, "update-ref", MAIN, commit, parent)
    assert proc.returncode == 0, _text(proc)
    assert rig.ref() == commit
