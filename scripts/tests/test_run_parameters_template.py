"""Run-parameters template and adopter tests of the framework port (B-9; AC-I.1).

The framework ships the run-parameters port as templates and tools that an adopter
instantiates. These tests check both ends:

* the two templates (``core/templates/TASK-TEMPLATE.md`` v2.4 and ``PLAN-TEMPLATE.md`` v2.3)
  carry the ``run_parameters`` block, ``bound_sessions``, the rows ``PC``, ``COMMIT`` and
  H2-6 and the terminal-step wording, read semantically as the source project reads them;
* a real ``scripts/instantiate.py --root <scratch adopter> --config <file>`` leaves no token in
  the templates or in either commit script (``agent-commit.ps1`` and ``agent-commit.sh``),
  and the adopter's ``tools/run_parameters.py status`` reports the port disabled until the
  adopter activates it;
* adopter-shaped behaviours run inside that scratch adopter, with its instantiated tools and
  policy: the hook denies a direct commit in every mode and asks for an ``unsupported``
  construct under ``bypassPermissions``; a token on a commit grants nothing; an empty
  ``authorization`` and ``transcript_adapter: none`` fail closed; an absent policy file, or a
  ``GUARDRAILS.md`` without the grant sentence, reads both commit parameters as ``false``;
  ``stop_gate.py`` refuses DONE without a passed final receipt; a loosened lower carrier is
  refused;
* the gate lease of ``agent-commit.ps1``: the exact-scope phases run under the tree's lease, a
  foreign holder refuses ``lease_held``, and a child that carries the holder's token runs
  nested. The POSIX ``flock`` twin is ``core/.agent/skills/git-workflow/scripts/tests/
  agent-commit.test.sh``.

Each test asserts the installer's result itself, so a failed instantiate is a test failure,
never a fixture error. Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
INSTALLER = ROOT / "scripts" / "instantiate.py"
TEMPLATES = CORE / "templates"
TASK_TEMPLATE = TEMPLATES / "TASK-TEMPLATE.md"
PLAN_TEMPLATE = TEMPLATES / "PLAN-TEMPLATE.md"
SCRIPTS_REL = ".agent/skills/git-workflow/scripts"
COMMIT_SCRIPTS = ("agent-commit.ps1", "agent-commit.sh")
PS1 = CORE / SCRIPTS_REL / "agent-commit.ps1"

#: ADOPTION-GUIDE Step 2: package path -> adopter path.
COPY_MAP = (
    ("core/AGENTS.md", "AGENTS.md"),
    ("core/GUARDRAILS.md", "GUARDRAILS.md"),
    ("core/CLAUDE.md", "CLAUDE.md"),
    ("core/.agent", ".agent"),
    ("core/tools", "tools"),
    ("core/templates", ".agent/templates"),
    ("core/.claude/agents", ".claude/agents"),
    ("core/.claude/hooks", ".claude/hooks"),
    ("core/.claude/settings.hooks.json", ".claude/settings.hooks.json"),
)
POLICY = ".agent/run-parameters.policy.json"
POLICY_TEMPLATE = ".agent/run-parameters.policy.json.template"
TOKEN_OPEN = "{" * 2

BLOCK_KEYS = {
    "schema",
    "decisions",
    "commit_plan",
    "exec_after_plan",
    "commit_exec",
    "push",
    "tightened_from",
    "authorization",
}
ROW_ID_RE = re.compile(r"PC|COMMIT|H\d-\d+[a-z]?|\d+")
TERMINAL_STEPS = "**Terminal steps (not rows).**"
FINAL_AUDIT = "run_parameters.py final --produce"
SEAL_CALL = "credits_msg.py landing --part closeout"
RELEASED_DONE = "released:done"
N_A_SENTENCE = (
    "`[x] n/a` is valid for `PC` under `commit_plan: false` and for `COMMIT` under"
    " `commit_exec: false`"
)
PLAN_ECHO = "**Run parameters (v2.3):**"

# The adopter-shaped behaviours of FS §3 ``scripts/tests/``, as node ids of the ported tests.
ADOPTER_NODES = (
    "tools/tests/test_commit_gate.py::TestCommitGateClassifier::test_vec_v3_025_vec_v3_050_direct_commit_is_denied",
    "tools/tests/test_commit_gate.py::TestCommitGateClassifier::test_vec_v3_021_vec_v3_051_unsupported_construct_around_a_commit",
    "tools/tests/test_commit_gate.py::TestCommitGateClassifier::test_vec_v3_027_a_token_on_a_commit_has_no_authority",
    "tools/tests/test_run_parameters.py::test_vec_v2_001_disabled_without_policy",
    "tools/tests/test_run_parameters.py::test_vec_v2_002_unsupported_harness",
    "tools/tests/test_run_parameters.py::test_vec_v2_030_lower_carrier_loosens",
    "tools/tests/test_stop_gate_run_parameters.py::test_vec_v4_002_grant_plan_without_receipt_blocked_legacy_allowed",
)
DRIVER_REL = "tools/tests/test_zz_template_driver.py"
# Two cases the ported tests do not hold, run in the adopter with its fixture builder.
DRIVER = '''"""Template driver cases (AC-I.1), written by ``scripts/tests/test_run_parameters_template.py``."""

from __future__ import annotations

from pathlib import Path

from tools.tests import test_run_parameters as trp
from tools.tests.run_parameters_fixtures import phase_b7


def test_empty_authorization_fails_closed(tmp_path: Path) -> None:
    """An empty ``authorization`` grants nothing: every act refuses ``schema``, fail closed."""
    fx = trp._build(tmp_path)
    block = dict(fx.block)
    block["authorization"] = ""
    fx.write_carrier(block, grouping_line=False)
    trp._all_refused(fx, "schema")


def test_guardrails_without_the_grant_sentence_fails_closed(tmp_path: Path) -> None:
    """``GUARDRAILS.md`` without the SIGN 3 (b) grant sentence disables the port."""
    fx = trp._build(tmp_path)
    diff = trp.ROOT / phase_b7.GOVERNANCE / phase_b7.GOVERNANCE_DIFFS["GUARDRAILS.md"]
    _, after = phase_b7.diff_lines(diff.read_text(encoding="utf-8"))
    path = fx.repo / "GUARDRAILS.md"
    text = path.read_text(encoding="utf-8")
    assert after[1] in text
    path.write_bytes(text.replace(after[1], "").encode("utf-8"))
    code, out = fx.run("status", "--json")
    assert code == 0, out
    assert out.get("enabled") is False, out
    assert out.get("reason") == "governance_text:sign3_b_grant", out
    trp._all_refused(fx, "disabled")
'''
DRIVER_NODES = (
    f"{DRIVER_REL}::test_empty_authorization_fails_closed",
    f"{DRIVER_REL}::test_guardrails_without_the_grant_sentence_fails_closed",
)

# The gate lease (FS §3 "Gate lease"): the executor lease's protocol.
LEASE_NAME = "{{PROJECT_NAME}}-gate.lock"
LEASE_TOKEN_ENV = "{{PROJECT_NAME_UPPER}}_GATE_LEASE_TOKEN"
GRANT_ENV = "{{PROJECT_NAME_UPPER}}_COMMIT_GRANT"
PYTHON_ENV = "{{PROJECT_NAME_UPPER}}_PYTHON"
LEASE_LOCK_OFFSET = 2**20
LEASE_BODY_SCHEMA = 1
HEX32 = re.compile(r"[0-9a-f]{32}")
PHASES = ["candidate", "publish", "index"]
# ``tools.commit_batch`` as the script's child sees it: it logs its step, the token it
# inherited and whether the lease is held, then prints one result line.
STUB = '''import json
import os
import sys

TOKEN_ENV = %r
OFFSET = %d


def busy(path):
    fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, OFFSET, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            os.lseek(fd, OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return False
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


args = sys.argv[1:]
step = args[args.index("--step") + 1]
entry = {
    "step": step,
    "args": args,
    "token": os.environ.get(TOKEN_ENV),
    "busy": busy(os.environ["STUB_LEASE"]),
}
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(entry) + "\\n")
print(json.dumps({"result": "ok", "phase": step, "commit": "c0ffee", "parent": "p",
                  "tree": "t", "paths": ["a.txt"]}))
''' % (LEASE_TOKEN_ENV, LEASE_LOCK_OFFSET)


# -- helpers -------------------------------------------------------------------------------


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _flat(text: str) -> str:
    """Whitespace-normalized text without blockquote markers, so a wrapped sentence still matches."""
    return " ".join(re.sub(r"(?m)^>[ \t]?", "", text).split())


def _frontmatter(path: Path) -> dict[str, Any]:
    text = _text(path)
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path.name}: no YAML frontmatter"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict), f"{path.name}: the frontmatter is not a mapping"
    return cast("dict[str, Any]", data)


def _rows(text: str) -> list[tuple[str, str]]:
    """``(id, line)`` of every task-table row, in file order."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cell = line[2:].split(" |", 1)[0].strip()
        if ROW_ID_RE.fullmatch(cell):
            out.append((cell, line))
    return out


def _row(text: str, row_id: str) -> str:
    found = [line for rid, line in _rows(text) if rid == row_id]
    assert len(found) == 1, f"row {row_id}: {len(found)} rows"
    return found[0]


def _row_order_violations(ids: list[str]) -> list[str]:
    """The row-order rules; an empty list when the order holds."""
    bad: list[str] = []
    if "H2-5a" in ids:
        bad.append("seal_row_present")
    numeric = [i for i, rid in enumerate(ids) if rid.isdigit()]
    if "PC" not in ids or not numeric or ids.index("PC") > numeric[0]:
        bad.append("pc_not_before_first_row")
    if "H2-5" not in ids or "COMMIT" not in ids:
        bad.append("commit_or_h2_5_missing")
    elif ids.index("COMMIT") != ids.index("H2-5") + 1:
        bad.append("commit_not_after_h2_5")
    if not ids or ids[-1] != "H2-6":
        bad.append("h2_6_not_last")
    return bad


def _run(
    args: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )


def _git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    result = _run(["git", "init", "-q"], cwd=path)
    assert result.returncode == 0, result.stdout + result.stderr


@dataclass
class Adopter:
    """A scratch adopter: the copied package and the installer's result."""

    root: Path
    install: subprocess.CompletedProcess[str]

    def assert_installed(self) -> None:
        assert self.install.returncode == 0, self.install.stdout + self.install.stderr


@pytest.fixture(scope="module")
def adopter(tmp_path_factory: pytest.TempPathFactory) -> Adopter:
    """ADOPTION-GUIDE Step 2, then a real ``instantiate.py --root --config`` run."""
    base = tmp_path_factory.mktemp("run-parameters-adopter")
    root = base / "acme"
    for src_rel, dst_rel in COPY_MAP:
        src = ROOT / src_rel
        dst = root / dst_rel
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    vars_file = base / "framework.vars"
    vars_file.write_text(
        f"PROJECT_NAME=acme\nPROJECT_ROOT={root.as_posix()}\n"
        "RECEIPTS_DIR=C:/Temp/acme\nREPO_URL=github.com/you/acme\n",
        encoding="utf-8",
    )
    install = _run(
        [sys.executable, "-X", "utf8", str(INSTALLER), "--root", str(root), "--config", str(vars_file)],
        cwd=base,
    )
    _git_init(root)
    return Adopter(root=root, install=install)


def _status(adopter: Adopter) -> dict[str, Any]:
    tool = adopter.root / "tools" / "run_parameters.py"
    assert tool.is_file(), f"missing {tool}"
    result = _run([sys.executable, "-X", "utf8", str(tool), "status", "--json"], cwd=adopter.root)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.lstrip().startswith("{")]
    assert lines, result.stdout + result.stderr
    out = json.loads(lines[-1])
    assert isinstance(out, dict), out
    return cast("dict[str, Any]", out)


# -- the templates -------------------------------------------------------------------------


def test_task_template_frontmatter_carries_the_block() -> None:
    """AC-I.1: ``run_parameters`` (eight keys), ``bound_sessions: []``; version 2.5 (review limits)."""
    meta = _frontmatter(TASK_TEMPLATE)
    block = meta.get("run_parameters")
    assert isinstance(block, dict), meta
    block = cast("dict[str, Any]", block)
    assert set(block) == BLOCK_KEYS, sorted(block)
    assert block["schema"] == "run-parameters/1"
    assert block["push"] == "never"
    assert meta.get("bound_sessions") == []
    assert meta.get("template_version") == "2.5"


def test_task_template_row_order() -> None:
    """AC-I.1: ``PC`` before the first row, ``COMMIT`` right after H2-5, H2-6 last, no H2-5a."""
    ids = [rid for rid, _ in _rows(_text(TASK_TEMPLATE))]
    assert _row_order_violations(ids) == [], ids


@pytest.mark.parametrize(
    ("ids", "violation"),
    [
        (["PC", "1", "H2-5", "H2-5a", "COMMIT", "H2-6"], "seal_row_present"),
        (["PC", "1", "COMMIT", "H2-5", "H2-6"], "commit_not_after_h2_5"),
        (["1", "PC", "H2-5", "COMMIT", "H2-6"], "pc_not_before_first_row"),
        (["PC", "1", "H2-5", "COMMIT", "H2-6", "H2-7"], "h2_6_not_last"),
    ],
    ids=["h2_5a", "commit_early", "pc_late", "h2_6_not_last"],
)
def test_row_order_rule_rejects(ids: list[str], violation: str) -> None:
    """AC-I.1 negative: the order rule names each broken order."""
    assert violation in _row_order_violations(ids)


def test_task_template_terminal_steps_follow_h2_6() -> None:
    """AC-I.1: the final audit and the seal are terminal steps after H2-6, not rows."""
    text = _text(TASK_TEMPLATE)
    for _, line in _rows(text):
        assert SEAL_CALL not in line, line
    h2_6 = _row(text, "H2-6")
    assert RELEASED_DONE in h2_6
    start = text.find(TERMINAL_STEPS)
    assert start > text.find(h2_6), "the terminal steps come before H2-6"
    paragraph = _flat(text[start:].split("\n\n", 1)[0])
    assert FINAL_AUDIT in paragraph, paragraph
    assert SEAL_CALL in paragraph, paragraph


def test_task_template_h2_rows() -> None:
    """AC-I.1: H2-3c removes by path; H2-4 runs the structural stage and writes no completion."""
    text = _text(TASK_TEMPLATE)
    assert "remove <path>" in _row(text, "H2-3c")
    h2_4 = _row(text, "H2-4")
    assert "structural" in h2_4, h2_4
    assert not re.search(r'status: "?complete', h2_4), h2_4


def test_task_template_n_a_is_valid_for_pc_and_commit() -> None:
    """AC-I.1: ``[x] n/a`` for ``PC`` under ``commit_plan: false``, ``COMMIT`` under ``commit_exec: false``."""
    assert N_A_SENTENCE in _flat(_text(TASK_TEMPLATE))


def test_plan_template_v2_3() -> None:
    """AC-I.1: PLAN-TEMPLATE (v2.3, now v2.4) carries the ``run_parameters`` key and the echo line."""
    meta = _frontmatter(PLAN_TEMPLATE)
    assert meta.get("template_version") == "2.4"
    assert "run_parameters" in meta, sorted(meta)
    assert PLAN_ECHO in _text(PLAN_TEMPLATE)


# -- a real instantiate --------------------------------------------------------------------


def test_instantiate_leaves_no_token_in_the_templates(adopter: Adopter) -> None:
    """AC-I.1: the instantiated templates keep the block and hold no token."""
    adopter.assert_installed()
    for name in ("TASK-TEMPLATE.md", "PLAN-TEMPLATE.md"):
        path = adopter.root / ".agent" / "templates" / name
        text = _text(path)
        assert TOKEN_OPEN not in text, f"{name}: a token is left"
    meta = _frontmatter(adopter.root / ".agent" / "templates" / "TASK-TEMPLATE.md")
    assert isinstance(meta.get("run_parameters"), dict), meta
    assert meta.get("bound_sessions") == []


@pytest.mark.parametrize("name", COMMIT_SCRIPTS)
def test_instantiate_ships_both_commit_scripts(adopter: Adopter, name: str) -> None:
    """AC-I.1: both script platforms land in the adopter, carry the grant route and no token."""
    adopter.assert_installed()
    path = adopter.root / SCRIPTS_REL / name
    assert path.is_file(), f"missing {path}"
    text = _text(path)
    assert TOKEN_OPEN not in text, f"{name}: a token is left"
    assert "ACME_COMMIT_GRANT" in text, f"{name}: no commit-grant route"
    assert "tools.commit_batch" in text, f"{name}: the driver is not the authority"
    assert "acme-gate.lock" in text or "LEASE" in text.upper(), f"{name}: no gate lease"


def test_adopter_status_is_disabled_without_a_policy(adopter: Adopter) -> None:
    """AC-I.1: no policy file → ``status`` reports the port disabled."""
    adopter.assert_installed()
    assert not (adopter.root / POLICY).exists()
    out = _status(adopter)
    assert out.get("enabled") is False, out
    assert out.get("reason") == "policy_missing", out


def test_adopter_status_is_disabled_with_the_template_policy(adopter: Adopter) -> None:
    """AC-I.1: the shipped policy template, copied unedited, enables nothing."""
    adopter.assert_installed()
    template = adopter.root / POLICY_TEMPLATE
    assert template.is_file(), f"missing {template}"
    policy = adopter.root / POLICY
    shutil.copyfile(template, policy)
    try:
        out = _status(adopter)
    finally:
        policy.unlink()
    assert out.get("enabled") is False, out


def test_adopter_behaviours_hold_in_the_instantiated_adopter(adopter: Adopter) -> None:
    """AC-I.1: the FS §3 behaviours pass against the instantiated tools and policy."""
    adopter.assert_installed()
    driver = adopter.root / DRIVER_REL
    driver.write_text(DRIVER, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    result = _run(
        [sys.executable, "-X", "utf8", "-m", "pytest", "-p", "no:cacheprovider", "-q",
         "--tb=short", *ADOPTER_NODES, *DRIVER_NODES],
        cwd=adopter.root,
        env=env,
        timeout=1800,
    )
    tail = "\n".join((result.stdout + result.stderr).splitlines()[-40:])
    assert result.returncode == 0, tail
    assert " passed" in tail and " failed" not in tail and " error" not in tail, tail


# -- the gate lease of agent-commit.ps1 ----------------------------------------------------


def _lease_lock(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, LEASE_LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _lease_unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, LEASE_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _open_lease(path: Path) -> int:
    return os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)


@contextmanager
def _hold(path: Path, token: str) -> Iterator[bytes]:
    """Hold the lease as another tool would: lock first, then write a schema-1 body."""
    fd = _open_lease(path)
    try:
        assert _lease_lock(fd), f"the lease is already held: {path}"
        body = json.dumps(
            {"schema": LEASE_BODY_SCHEMA, "pid": os.getpid(), "token": token}, sort_keys=True
        ).encode("utf-8")
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, body)
        try:
            yield body
        finally:
            _lease_unlock(fd)
    finally:
        os.close(fd)


def _free(path: Path) -> bool:
    fd = _open_lease(path)
    try:
        if not _lease_lock(fd):
            return False
        _lease_unlock(fd)
        return True
    finally:
        os.close(fd)


@dataclass
class LeaseRig:
    repo: Path
    lease: Path
    stub: Path
    log: Path

    def run(self, *extra: str, token: str | None = None) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k != LEASE_TOKEN_ENV}
        env.update(
            {
                GRANT_ENV: "op-1",
                PYTHON_ENV: sys.executable,
                "STUB_LOG": str(self.log),
                "STUB_LEASE": str(self.lease),
            }
        )
        if token is not None:
            env[LEASE_TOKEN_ENV] = token
        return _run(
            ["pwsh", "-NoProfile", "-File", str(PS1), "-RepositoryPath", str(self.repo),
             "-NoPush", *extra],
            cwd=self.stub,
            env=env,
            timeout=120,
        )

    def calls(self) -> list[dict[str, Any]]:
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in _text(self.log).splitlines() if line.strip()]


@pytest.fixture
def lease_rig(tmp_path: Path) -> LeaseRig:
    repo = tmp_path / "repo"
    _git_init(repo)
    git_dir = _run(["git", "rev-parse", "--absolute-git-dir"], cwd=repo)
    assert git_dir.returncode == 0, git_dir.stderr
    stub = tmp_path / "stub"
    (stub / "tools").mkdir(parents=True)
    (stub / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (stub / "tools" / "commit_batch.py").write_text(STUB, encoding="utf-8")
    lease = Path(git_dir.stdout.strip()) / LEASE_NAME
    lease.touch()
    return LeaseRig(repo=repo, lease=lease, stub=stub, log=tmp_path / "calls.jsonl")


def _last_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    lines = [line for line in result.stdout.splitlines() if line.lstrip().startswith("{")]
    assert lines, result.stdout + result.stderr
    return cast("dict[str, Any]", json.loads(lines[-1]))


def test_ps1_runs_the_phases_under_the_gate_lease(lease_rig: LeaseRig) -> None:
    """AC-I.1: the three phases run in order under the lease; the child carries its token."""
    result = lease_rig.run()
    assert result.returncode == 0, result.stdout + result.stderr
    calls = lease_rig.calls()
    assert [c["step"] for c in calls] == PHASES, calls
    assert all(c["busy"] for c in calls), calls
    tokens = {c["token"] for c in calls}
    assert len(tokens) == 1 and HEX32.fullmatch(str(next(iter(tokens)))), calls
    assert lease_rig.lease.is_file(), "the lease file is never deleted"
    assert _free(lease_rig.lease), "the lease is still held after the run"


def test_ps1_refuses_while_another_tool_holds_the_lease(lease_rig: LeaseRig) -> None:
    """AC-I.1: a foreign holder → ``lease_held``, exit 1, and no phase runs."""
    with _hold(lease_rig.lease, "a" * 32):
        result = lease_rig.run()
    assert result.returncode == 1, result.stdout + result.stderr
    assert _last_json(result).get("reason") == "lease_held", result.stdout
    assert lease_rig.calls() == []


def test_ps1_refuses_a_token_that_is_not_the_holders(lease_rig: LeaseRig) -> None:
    """AC-I.1: a child token that differs from the holder's body → ``lease_held``."""
    with _hold(lease_rig.lease, "a" * 32):
        result = lease_rig.run(token="b" * 32)
    assert result.returncode == 1, result.stdout + result.stderr
    assert _last_json(result).get("reason") == "lease_held", result.stdout
    assert lease_rig.calls() == []


def test_ps1_runs_nested_under_the_holders_token(lease_rig: LeaseRig) -> None:
    """AC-I.1: the holder's own token → nested: the phases run and the body is untouched."""
    token = "c" * 32
    with _hold(lease_rig.lease, token) as body:
        result = lease_rig.run(token=token)
        assert lease_rig.lease.read_bytes()[: len(body)] == body
    assert result.returncode == 0, result.stdout + result.stderr
    calls = lease_rig.calls()
    assert [c["step"] for c in calls] == PHASES, calls
    assert {c["token"] for c in calls} == {token}, calls
