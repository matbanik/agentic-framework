#!/usr/bin/env python3
"""Adoption-contract runner for portable-adopter-bootstrap.

Cases (plan Verification Plan §6):
  wp1, templates-installed, d9-no, d6, profile-permissions, hd03, wp7, lane-gate

First stdout line is always OK: / REFUSE: / USAGE: / FAIL-CLOSED:.
Exit 0/1/2/3. Writes nothing except under RECEIPTS_DIR when a case records a fixture; lane-gate
builds its disposable adoption (core/ instantiated as acme, two claimed lanes) in a
temporary directory.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO

ROOT = Path(__file__).resolve().parents[2]
EGRESS_NEEDLES = (
    "EGRESS_PRECEDENCE",
    "named human",
    "SIGN 1",
)
FORBIDDEN_WEB = "must not prepare a provider web-prompt"


def _out(kind: str, msg: str, code: int) -> int:
    print(f"{kind}: {msg}")
    return code


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _must_contain(rel: str, needles: list[str], *, absent: list[str] | None = None) -> list[str]:
    text = _read(rel)
    missing = [n for n in needles if n not in text]
    extra = [n for n in (absent or []) if n in text]
    errs: list[str] = []
    if missing:
        errs.append(f"{rel} missing {missing!r}")
    if extra:
        errs.append(f"{rel} still contains {extra!r}")
    return errs


def _load_py(rel: str, name: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {rel}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def case_wp1() -> int:
    errs: list[str] = []
    errs += _must_contain(
        "ADOPTION-GUIDE.md",
        [".agent-registry/", "session-scoped", "EGRESS_PRECEDENCE", "Git for Windows"],
        absent=["copy the package-root `.agent/` (a sibling of `core/`"],
    )
    errs += _must_contain(
        "ADOPTION-QUESTIONS.md",
        [".agent-registry/", "deferral", "A10"],
    )
    errs += _must_contain(
        "PROJECT-PROFILE-TEMPLATE.md",
        ["A10", "C3b", "E5", "B4", "D9", "F3b"],
    )
    errs += _must_contain(
        ".agent/INSTANTIATE.md",
        [".agent-registry/", "fail-closed", "LOCATE_ORDER"],
        absent=["P:\\.agent"],
    )
    for rel in (
        "core/.agent/workflows/create-plan.md",
        "core/.agent/workflows/delegated-plan-creation.md",
        "core/.agent/workflows/execution-session.md",
        "core/.agent/workflows/execution-critical-review.md",
        "core/.agent/skills/cli-dispatch/SKILL.md",
        "core/AGENTS.md",
        "core/GUARDRAILS.md",
    ):
        errs += _must_contain(rel, list(EGRESS_NEEDLES))
    errs += _must_contain(
        "core/.agent/skills/cli-dispatch/SKILL.md",
        [FORBIDDEN_WEB, "named human"],
        absent=["If `can_dispatch_external_reviewer == no`, write the complete reviewer prompt"],
    )

    # Isolated locator: configured missing home must not select USERPROFILE fallback.
    with tempfile.TemporaryDirectory(prefix="adopt-wp1-") as tmp:
        tmp_p = Path(tmp)
        missing = tmp_p / "missing-home"
        unrelated = tmp_p / "unrelated"
        (unrelated / ".agent").mkdir(parents=True)
        (unrelated / ".agent" / "model-registry.json").write_text("{}", encoding="utf-8")
        (unrelated / ".agent" / "tools").mkdir()
        decoy = unrelated / ".agent" / "tools" / "resolve_model.py"
        decoy.write_text("print('decoy')\n", encoding="utf-8")

        env = os.environ.copy()
        env.pop("AGENT_MODEL_REGISTRY", None)
        env["AGENT_MODEL_REGISTRY_HOME"] = str(missing)
        env["USERPROFILE"] = str(unrelated)
        env["HOME"] = str(unrelated)

        rm = _load_py(".agent/tools/resolve_model.py", "resolve_model_wrap")
        old = os.environ.copy()
        try:
            os.environ.pop("AGENT_MODEL_REGISTRY", None)
            os.environ["AGENT_MODEL_REGISTRY_HOME"] = str(missing)
            os.environ["USERPROFILE"] = str(unrelated)
            os.environ["HOME"] = str(unrelated)
            try:
                rm.locate_tool("resolve_model.py")
                errs.append("resolve_model.locate_tool fell through to an unrelated home")
            except SystemExit as exc:
                if int(exc.code or 0) == 0:
                    errs.append("resolve_model.locate_tool exited 0 on missing configured home")
        finally:
            os.environ.clear()
            os.environ.update(old)

        psm1 = ROOT / ".agent" / "tools" / "ModelRegistry.psm1"
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if pwsh:
            script = (
                f"$env:AGENT_MODEL_REGISTRY=''; "
                f"$env:AGENT_MODEL_REGISTRY_HOME='{missing.as_posix()}'; "
                f"$env:USERPROFILE='{unrelated.as_posix()}'; "
                f"Import-Module '{psm1.as_posix()}' -Force; "
                "try { Resolve-RegistryPath | Out-Host; exit 0 } "
                "catch { if ($_.ToString() -match 'registry_not_found') { exit 1 }; "
                "Write-Output $_; exit 2 }"
            )
            r = subprocess.run(
                [pwsh, "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                env=env,
            )
            if r.returncode == 0:
                errs.append(
                    "Resolve-RegistryPath selected a path when configured home was missing: "
                    + (r.stdout or "")[:200]
                )
            elif r.returncode != 1:
                errs.append(
                    f"Resolve-RegistryPath unexpected exit {r.returncode}: "
                    + ((r.stdout or "") + (r.stderr or ""))[:300]
                )
        else:
            errs.append("no pwsh/powershell to exercise ModelRegistry.psm1")

    if errs:
        return _out("REFUSE", "; ".join(errs), 1)
    return _out("OK", "wp1 layout, locators, and EGRESS_PRECEDENCE", 0)


def case_templates_installed() -> int:
    req = [
        ".agent/templates/PLAN-TEMPLATE.md",
        ".agent/templates/TASK-TEMPLATE.md",
        ".agent/templates/REVIEW-TEMPLATE.md",
    ]
    bad = [
        "docs/execution/plans/PLAN-TEMPLATE",
        "handoffs/REVIEW-TEMPLATE",
    ]
    errs: list[str] = []
    for rel in (
        "core/.agent/workflows/create-plan.md",
        "core/.agent/roles/orchestrator.md",
        "core/.agent/workflows/delegated-plan-creation.md",
        "core/.agent/workflows/plan-critical-review.md",
        "core/.agent/workflows/execution-critical-review.md",
    ):
        text = _read(rel)
        for n in req:
            if n not in text and rel.endswith("create-plan.md"):
                errs.append(f"{rel} missing {n}")
            if n not in text and rel.endswith("orchestrator.md") and "TEMPLATE" in n:
                if ".agent/templates/" not in text and "HANDOFF-TEMPLATE" not in text:
                    errs.append(f"{rel} missing TEMPLATE_HOME")
        for n in bad:
            if n in text:
                errs.append(f"{rel} still names {n}")
    if "core/.agent/context/current-focus.md" not in str(
        (ROOT / "core/.agent/context/current-focus.md").exists()
    ) and not (ROOT / "core/.agent/context/current-focus.md").is_file():
        errs.append("missing core/.agent/context/current-focus.md")
    if not (ROOT / "core/.agent/context/current-focus.md").is_file():
        errs.append("missing current-focus.md seed")
    if errs:
        return _out("REFUSE", "; ".join(errs), 1)
    return _out("OK", "TEMPLATE_HOME consumers", 0)


def case_d9_no() -> int:
    text = _read("core/.agent/workflows/create-plan.md")
    errs: list[str] = []
    if "D9_NO_BRANCH" not in text and "D9 is no" not in text and "D9=no" not in text:
        errs.append("create-plan.md has no D9=no branch")
    # Unconditional meu_status discovery must not remain the only path.
    if "python tools/meu_status.py stats" in text and "D9" not in text.split(
        "python tools/meu_status.py stats"
    )[0][-400:]:
        # still allowed if guarded nearby; require an explicit skip sentence
        if "If PROFILE D9" not in text and "D9 is no" not in text and "D9=no" not in text:
            errs.append("meu_status.py still unconditional")
    if errs:
        return _out("REFUSE", "; ".join(errs), 1)
    return _out("OK", "D9_NO_BRANCH present", 0)


def case_d6() -> int:
    errs: list[str] = []
    cmds = _read("core/.agent/docs/commands.md")
    if "uv run python tools/validate_codebase.py" in cmds:
        errs.append("commands.md still registers validate_codebase.py")
    if "D6_ADOPTER_ARGV" not in cmds and "adopter-supplied" not in cmds.lower() and "PROJECT-PROFILE" not in cmds:
        errs.append("commands.md does not defer to PROFILE D6")
    readme = _read("core/.agent/workflows/README.md")
    if "/mcp-audit" in readme:
        errs.append("workflows README still registers /mcp-audit")
    with tempfile.TemporaryDirectory(prefix="adopt-d6-") as tmp:
        t = Path(tmp)
        (t / "test_hello.py").write_text(
            "def test_hello():\n    assert True\n", encoding="utf-8"
        )
        r1 = subprocess.run(
            [sys.executable, "-m", "pytest", "test_hello.py", "-q"],
            cwd=t,
            capture_output=True,
            text=True,
        )
        if r1.returncode != 0:
            errs.append("pytest hello fixture failed: " + (r1.stdout + r1.stderr)[:200])
        (t / "test_fail.py").write_text(
            "def test_a():\n    assert False, 'diag-one'\n"
            "def test_b():\n    raise RuntimeError('diag-two')\n",
            encoding="utf-8",
        )
        rec = t / "fail-receipt.txt"
        r2 = subprocess.run(
            [sys.executable, "-m", "pytest", "test_fail.py", "-q"],
            cwd=t,
            capture_output=True,
            text=True,
        )
        rec.write_text((r2.stdout or "") + (r2.stderr or ""), encoding="utf-8")
        body = rec.read_text(encoding="utf-8")
        if r2.returncode == 0:
            errs.append("failing pytest exited 0")
        if "diag-one" not in body or "diag-two" not in body:
            errs.append("failing diagnostics dropped from receipt")
        missing_exe = t / "no-such-d6.exe"
        try:
            missing = subprocess.run(
                [str(missing_exe)],
                cwd=t,
                capture_output=True,
                text=True,
            )
            missing_failed = missing.returncode != 0
        except FileNotFoundError:
            missing_failed = True
        if not missing_failed:
            errs.append("missing executable exited 0")
        alt = subprocess.run(
            [sys.executable, "-c", "print('alt-d6-ok')"],
            cwd=t,
            capture_output=True,
            text=True,
        )
        if alt.returncode != 0 or "alt-d6-ok" not in (alt.stdout or ""):
            errs.append("alternate non-pytest D6 argv failed")
    if errs:
        return _out("REFUSE", "; ".join(errs), 1)
    return _out("OK", "D6_ADOPTER_ARGV and no mcp-audit", 0)


def case_profile_permissions() -> int:
    text = _read("core/.agent/workflows/create-plan.md")
    errs: list[str] = []
    if "PROJECT-PROFILE.md" not in text:
        errs.append("create-plan.md does not require PROJECT-PROFILE.md")
    if "EGRESS_PRECEDENCE" not in text:
        errs.append("create-plan.md missing EGRESS_PRECEDENCE")
    if "Immediately dispatch" in text and "forbids" not in text.lower():
        errs.append("create-plan.md still dispatches unconditionally")
    tmpl = _read("PROJECT-PROFILE-TEMPLATE.md")
    for slot in ("A4b", "A4c", "A4d", "A6b", "A9", "A10", "C3b", "D8", "D9", "F3b"):
        if slot not in tmpl:
            errs.append(f"PROFILE template missing slot {slot}")
    if errs:
        return _out("REFUSE", "; ".join(errs), 1)
    return _out("OK", "profile slots and permission behavior", 0)


def case_hd03() -> int:
    receipts = os.environ.get("RECEIPTS_DIR")
    if not receipts:
        return _out("USAGE", "RECEIPTS_DIR is required", 2)
    path = Path(receipts) / "hd03-live-registry.txt"
    if not path.is_file():
        return _out("REFUSE", f"missing {path}", 1)
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text.strip() else ""
    if first.startswith("INCOMPLETE:"):
        if "resolve_model.py" not in text or "check_model_slugs.py" not in text:
            return _out("REFUSE", "INCOMPLETE receipt missing wrapper paths", 1)
        if "registry ready" in text.lower():
            return _out("REFUSE", "INCOMPLETE receipt claims registry ready", 1)
        return _out("OK", "HD03 incompleteness receipt", 0)
    if first.startswith("READY:"):
        if "provenance" not in text.lower():
            return _out("REFUSE", "READY receipt missing provenance", 1)
        return _out("OK", "HD03 ready receipt", 0)
    return _out(
        "REFUSE",
        "hd03 receipt first line is not INCOMPLETE: or READY: (existence/size is not evidence)",
        1,
    )


def _wp7_field(text: str, key: str) -> str:
    prefix = key + "="
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip()
    return ""


def _wp7_receipt_errors(text: str) -> list[str]:
    errs: list[str] = []
    if "fw-adopt-probe" in text.replace("\\", "/"):
        errs.append("replay mentions fw-adopt-probe")
    need = (
        "fixture=",
        "D6_EXIT=",
        "LINT_EXIT=",
        "PREFLIGHT_FIRST=",
        "PREFLIGHT_EXIT=",
        "PROVIDER_CALLS=0",
        "D9_NO_BRANCH=",
        "PLAN_FROM_TEMPLATE=yes",
        "TASK_FROM_TEMPLATE=yes",
        "EGRESS_STOP=",
    )
    missing = [n for n in need if n not in text]
    if missing:
        errs.append(f"replay missing {missing}")
    for key in ("D6_EXIT", "LINT_EXIT", "PREFLIGHT_EXIT", "INSTANTIATE_EXIT"):
        val = _wp7_field(text, key)
        if val != "0":
            errs.append(f"{key} is {val!r}, want 0")
    first = _wp7_field(text, "PREFLIGHT_FIRST")
    if not first.startswith("OK:"):
        errs.append(f"preflight first line was {first!r}")
    d9 = _wp7_field(text, "D9_NO_BRANCH")
    if d9 != "yes":
        errs.append(f"D9_NO_BRANCH is {d9!r}, want yes from PROFILE")
    egress = _wp7_field(text, "EGRESS_STOP")
    if egress != "named-human-no-web-prompt":
        errs.append(f"EGRESS_STOP is {egress!r}")
    fixture = Path(_wp7_field(text, "fixture"))
    plan = fixture / "docs/execution/plans/2026-09-19-wp7-first/implementation-plan.md"
    task = fixture / "docs/execution/plans/2026-09-19-wp7-first/task.md"
    if not plan.is_file() or not task.is_file():
        errs.append("fixture plan/task missing")
    else:
        plan_text = plan.read_text(encoding="utf-8")
        for needle in (
            "#### Acceptance Criteria",
            "## Verification Plan",
            "#### Spec Sufficiency Table",
            "D9_NO_BRANCH",
            "EGRESS_PRECEDENCE",
            "template_version",
        ):
            if needle not in plan_text:
                errs.append(f"plan missing {needle} (not a PLAN-TEMPLATE skeleton)")
        task_text = task.read_text(encoding="utf-8")
        if "Status Legend" not in task_text or "template_version" not in task_text:
            errs.append("task missing TASK-TEMPLATE skeleton markers")
    return errs


def case_wp7() -> int:
    receipts = os.environ.get("RECEIPTS_DIR")
    if not receipts:
        return _out("USAGE", "RECEIPTS_DIR is required", 2)
    bogus = (
        "fixture=C:/Temp/agentic-framework/wp7-bogus\n"
        "D6_EXIT=1\n"
        "LINT_EXIT=1\n"
        "PREFLIGHT_FIRST=OK: forged\n"
        "PREFLIGHT_EXIT=0\n"
        "PROVIDER_CALLS=0\n"
        "D9_NO_BRANCH=yes\n"
        "PLAN_FROM_TEMPLATE=yes\n"
        "TASK_FROM_TEMPLATE=yes\n"
        "EGRESS_STOP=named-human-no-web-prompt\n"
        "INSTANTIATE_EXIT=0\n"
    )
    bogus_errs = _wp7_receipt_errors(bogus)
    if not bogus_errs:
        return _out("REFUSE", "wp7 checker accepted D6_EXIT=1 and LINT_EXIT=1", 1)
    replay = Path(receipts) / "wp7-adopter-replay.txt"
    if not replay.is_file():
        return _out("REFUSE", f"missing {replay}", 1)
    text = replay.read_text(encoding="utf-8")
    errs = _wp7_receipt_errors(text)
    if errs:
        return _out("REFUSE", "; ".join(errs), 1)
    return _out("OK", "wp7 disposable adopter replay", 0)


LANE_GATE_SLUGS = ("2026-10-24-lane-a", "2026-10-24-lane-b")
LANE_GATE_SESSION = "s-lane-gate"
LANE_GATE_PLANS = "docs/execution/plans"
LANE_GATE_TIMEOUT_S = 120.0
LANE_GATE_SETTLE_S = 60.0
LANE_GATE_ORPHAN_S = 10.0
LANE_GATE_STILL_ACTIVE = 259
LANE_GATE_QUERY = 0x1000

# The workload child of each ``gate run``: argv = [pid file, heartbeat file, stop file].
# It writes its pid, rewrites the heartbeat every 50 ms and ends when the stop file
# exists (cap 180 s), so the case decides when the child ends.
LANE_GATE_SLEEPER = """
import os
import sys
import time

pid_file, beat, stop = sys.argv[1:4]
with open(pid_file + ".tmp", "w", encoding="utf-8") as fh:
    fh.write(str(os.getpid()))
os.replace(pid_file + ".tmp", pid_file)
count = 0
deadline = time.monotonic() + 180
while not os.path.exists(stop) and time.monotonic() < deadline:
    count += 1
    with open(beat, "w", encoding="utf-8") as fh:
        fh.write(str(count))
    time.sleep(0.05)
"""


class _LaneGateError(Exception):
    """One failed expectation of the lane-gate case (the message is the REFUSE text)."""


def _lane_gate_py() -> str:
    """The base interpreter: a Windows venv ``python.exe`` is a launcher whose pid is not the adapter's."""
    return str(getattr(sys, "_base_executable", "") or sys.executable)


def _lane_gate_env(gitconfig: Path) -> dict[str, str]:
    """A git environment with no system or global config and a fixed identity."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "ACME_"))
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(gitconfig),
        GIT_AUTHOR_NAME="Lane Gate",
        GIT_AUTHOR_EMAIL="lane-gate@example.invalid",
        GIT_COMMITTER_NAME="Lane Gate",
        GIT_COMMITTER_EMAIL="lane-gate@example.invalid",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env


def _lane_gate_run(
    argv: list[str], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """One finished child, with its output captured and the case's time bound."""
    return subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=LANE_GATE_TIMEOUT_S,
        check=False,
    )


def _lane_gate_must(proc: subprocess.CompletedProcess[str], what: str) -> str:
    """The stdout of a child that must exit 0; ``_LaneGateError`` otherwise."""
    if proc.returncode != 0:
        raise _LaneGateError(
            f"{what} exited {proc.returncode}: {(proc.stdout + proc.stderr)[-600:]}"
        )
    return proc.stdout


def _lane_gate_alive(pid: int) -> bool:
    """Whether ``pid`` names a live process (exit code STILL_ACTIVE on Windows)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(LANE_GATE_QUERY, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == LANE_GATE_STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lane_gate_kill(pid: int) -> None:
    """End one process only (TerminateProcess on Windows, SIGKILL on POSIX)."""
    import signal

    os.kill(pid, signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL)


def _lane_gate_end(proc: subprocess.Popen[str]) -> None:
    """Cleanup: kill ``proc`` when it still runs, then reap it."""
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=LANE_GATE_TIMEOUT_S)


def _lane_gate_end_pid(pid: int) -> None:
    """Cleanup: end the workload child ``pid`` when it still lives."""
    if _lane_gate_alive(pid):
        _lane_gate_kill(pid)


class _LaneGateSleeper:
    """The file paths of one workload child (``LANE_GATE_SLEEPER``)."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.script = root / "sleeper.py"
        self.script.write_text(LANE_GATE_SLEEPER, encoding="utf-8")
        self.pid_file = root / "child.pid"
        self.beat = root / "beat.txt"
        self.stop_file = root / "stop"

    def argv(self) -> list[str]:
        return [
            _lane_gate_py(),
            str(self.script),
            str(self.pid_file),
            str(self.beat),
            str(self.stop_file),
        ]

    def pid(self) -> int | None:
        try:
            return int(self.pid_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def beating(self) -> bool:
        """Whether the heartbeat file changes within 0.5 s."""

        def read() -> str | None:
            try:
                return self.beat.read_text(encoding="utf-8")
            except OSError:
                return None

        first = read()
        time.sleep(0.5)
        return read() != first

    def stop(self) -> None:
        self.stop_file.write_text("stop", encoding="utf-8")


class _LaneGateRig:
    """A disposable adoption: ``core/`` instantiated as ``acme``, with two lanes claimed."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.adopter = tmp / "acme"
        gitconfig = tmp / "empty.gitconfig"
        gitconfig.write_text("", encoding="utf-8")
        self.env = _lane_gate_env(gitconfig)
        self.lanes = self.adopter / "tools" / "lanes.py"
        self.worktrees: dict[str, Path] = {}
        self.common = Path()

    def git(self, cwd: Path, *args: str) -> str:
        return _lane_gate_must(
            _lane_gate_run(["git", *args], cwd, self.env), "git " + " ".join(args[:2])
        )

    def lanes_cli(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return _lane_gate_run([_lane_gate_py(), str(self.lanes), *args], cwd, self.env)

    def build(self) -> None:
        shutil.copytree(
            ROOT / "core",
            self.adopter,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
        )
        values = self.tmp / "acme.vars"
        values.write_text(
            "PROJECT_NAME=acme\n"
            f"PROJECT_ROOT={self.adopter.as_posix()}\n"
            f"RECEIPTS_DIR={(self.tmp / 'receipts').as_posix()}\n"
            "REPO_URL=github.com/example/acme\n",
            encoding="utf-8",
        )
        instantiate = [sys.executable, str(ROOT / "scripts" / "instantiate.py")]
        _lane_gate_must(
            _lane_gate_run(
                [*instantiate, "--root", str(self.adopter), "--config", str(values)],
                ROOT,
                self.env,
            ),
            "instantiate",
        )
        _lane_gate_must(
            _lane_gate_run(
                [*instantiate, "--root", str(self.adopter), "--verify"], ROOT, self.env
            ),
            "instantiate --verify",
        )
        self.git(self.adopter, "init", "-q", "-b", "main")
        for key, value in (
            ("core.autocrlf", "false"),
            ("commit.gpgsign", "false"),
            ("user.name", "Lane Gate"),
            ("user.email", "lane-gate@example.invalid"),
        ):
            self.git(self.adopter, "config", key, value)
        for slug in LANE_GATE_SLUGS:
            task = self.adopter / LANE_GATE_PLANS / slug / "task.md"
            task.parent.mkdir(parents=True, exist_ok=True)
            task.write_text(
                "---\nproject: lane-gate\n---\n\n# Task\n\n| # | Task |\n|---|---|\n"
                "| 1 | work |\n\n## Lane Ownership\n\n```yaml\nowns:\n"
                f"  - src/{slug}/\nmust_not_touch: []\n```\n",
                encoding="utf-8",
            )
        self.git(self.adopter, "add", "-A")
        self.git(self.adopter, "commit", "-q", "-m", "acme: the disposable adoption")
        self.common = Path(
            self.git(
                self.adopter, "rev-parse", "--path-format=absolute", "--git-common-dir"
            ).strip()
        ).resolve()
        for slug in LANE_GATE_SLUGS:
            wt = self.tmp / "wt" / slug
            self.git(self.adopter, "worktree", "add", "-q", "-b", f"lane/{slug}", str(wt))
            wt = wt.resolve()
            self.worktrees[slug] = wt
            _lane_gate_must(
                self.lanes_cli(
                    wt,
                    "claim",
                    "--plan",
                    f"{LANE_GATE_PLANS}/{slug}",
                    "--worktree",
                    str(wt),
                    "--session",
                    LANE_GATE_SESSION,
                ),
                f"claim {slug}",
            )

    def card(self, slug: str) -> dict[str, object]:
        data = json.loads(
            (self.common / "lanes" / f"{slug}.json").read_text(encoding="utf-8")
        )
        if not isinstance(data, dict):
            raise _LaneGateError(f"card {slug} is not an object")
        return data

    def gates(self, slug: str) -> list[object]:
        gates = self.card(slug).get("gates")
        if not isinstance(gates, list):
            raise _LaneGateError(f"card {slug} has no gates list")
        return gates

    def deps_states(self, slug: str) -> list[str]:
        claims = self.card(slug).get("claims")
        return [
            str(claim.get("state"))
            for claim in (claims if isinstance(claims, list) else [])
            if isinstance(claim, dict) and claim.get("kind") == "deps"
        ]

    def deps(self, slug: str, *args: str) -> subprocess.CompletedProcess[str]:
        wt = self.worktrees[slug]
        return self.lanes_cli(wt, "deps", *args, "--worktree", str(wt))

    def start_gate(
        self, slug: str, sleeper: _LaneGateSleeper, log: Path
    ) -> tuple[subprocess.Popen[str], IO[str]]:
        """``gate run`` on ``slug``'s worktree around ``sleeper`` (output to ``log``)."""
        wt = self.worktrees[slug]
        out = log.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [
                _lane_gate_py(),
                str(self.lanes),
                "gate",
                "run",
                "--worktree",
                str(wt),
                "--",
                *sleeper.argv(),
            ],
            cwd=str(wt),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=self.env,
        )
        return proc, out

    def wait_entry(
        self, slug: str, proc: subprocess.Popen[str], sleeper: _LaneGateSleeper, log: Path
    ) -> int:
        """Wait until the gate entry records its workload; return the child pid."""
        deadline = time.monotonic() + LANE_GATE_SETTLE_S
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise _LaneGateError(
                    f"gate run ended early ({proc.returncode}): "
                    + log.read_text(encoding="utf-8")[-600:]
                )
            gates = self.gates(slug)
            child = sleeper.pid()
            if (
                len(gates) == 1
                and isinstance(gates[0], dict)
                and gates[0].get("workload")
                and child is not None
            ):
                if gates[0].get("pid") != proc.pid:
                    raise _LaneGateError(
                        f"the gate entry names pid {gates[0].get('pid')}, not the adapter {proc.pid}"
                    )
                return child
            time.sleep(0.05)
        raise _LaneGateError(f"no gate entry with a workload on {slug}")


def _lane_gate_refused(proc: subprocess.CompletedProcess[str], token: str, what: str) -> None:
    if proc.returncode == 0 or token not in proc.stdout:
        raise _LaneGateError(
            f"{what}: want a refusal {token!r}, got exit {proc.returncode}: "
            + (proc.stdout + proc.stderr)[-600:]
        )


def _lane_gate_steps(rig: _LaneGateRig, cleanup: list[Callable[[], None]]) -> None:
    lane_a, lane_b = LANE_GATE_SLUGS
    # (1) Lane A runs a gate; lane B's deps begin cannot drain it and clears its claim.
    first = _LaneGateSleeper(rig.tmp / "gate-1")
    cleanup.append(first.stop)
    log1 = rig.tmp / "gate-1.log"
    gate1, out1 = rig.start_gate(lane_a, first, log1)
    cleanup.append(out1.close)
    cleanup.append(lambda: _lane_gate_end(gate1))
    rig.wait_entry(lane_a, gate1, first, log1)
    _lane_gate_refused(
        rig.deps(lane_b, "begin", "--wait-s", "0"),
        "deps_drain_timeout:1",
        "deps begin while lane A's gate runs",
    )
    if rig.deps_states(lane_b) != []:
        raise _LaneGateError(f"the timed-out deps claim stayed: {rig.deps_states(lane_b)}")
    # (2) A's gate ends: B reaches exclusive, and A's next gate run refuses deps_pending.
    first.stop()
    code = gate1.wait(timeout=LANE_GATE_TIMEOUT_S)
    if code != 0:
        raise _LaneGateError(f"gate run did not exit with the child's 0: {code}")
    if rig.gates(lane_a) != []:
        raise _LaneGateError(f"the ended gate left its entry: {rig.gates(lane_a)}")
    _lane_gate_must(rig.deps(lane_b, "begin", "--wait-s", "0"), "deps begin after A ends")
    if rig.deps_states(lane_b) != ["exclusive"]:
        raise _LaneGateError(f"deps begin is not exclusive: {rig.deps_states(lane_b)}")
    marker = rig.tmp / "started.txt"
    wt_a = rig.worktrees[lane_a]
    pending = rig.lanes_cli(
        wt_a,
        "gate",
        "run",
        "--worktree",
        str(wt_a),
        "--",
        _lane_gate_py(),
        "-c",
        "import sys; open(sys.argv[1], 'w').write('x')",
        str(marker),
    )
    _lane_gate_refused(pending, "deps_pending", "gate run under B's exclusive claim")
    if marker.exists() or rig.gates(lane_a) != []:
        raise _LaneGateError("the refused gate run started its child or wrote an entry")
    _lane_gate_must(rig.deps(lane_b, "end"), "deps end")
    if rig.deps_states(lane_b) != []:
        raise _LaneGateError(f"deps end left a claim: {rig.deps_states(lane_b)}")
    # (3) Wrapper loss: kill only the gate run process while its child lives. While the
    # child lives, deps begin is never exclusive (Windows: the kill-on-close job ends
    # the child; POSIX: the orphan keeps the entry until the case stops the child).
    second = _LaneGateSleeper(rig.tmp / "gate-2")
    cleanup.append(second.stop)
    log2 = rig.tmp / "gate-2.log"
    gate2, out2 = rig.start_gate(lane_a, second, log2)
    cleanup.append(out2.close)
    cleanup.append(lambda: _lane_gate_end(gate2))
    child = rig.wait_entry(lane_a, gate2, second, log2)
    cleanup.append(lambda: _lane_gate_end_pid(child))
    _lane_gate_kill(gate2.pid)
    gate2.wait(timeout=LANE_GATE_TIMEOUT_S)
    killed = time.monotonic()
    deadline = killed + LANE_GATE_SETTLE_S
    while True:
        proc = rig.deps(lane_b, "begin", "--wait-s", "0")
        if proc.returncode == 0:
            # A child alive (or beating) after the exclusive answer lived through it.
            if _lane_gate_alive(child) or second.beating():
                raise _LaneGateError(
                    "deps begin was exclusive while the gate's child lived"
                )
            break
        _lane_gate_refused(proc, "deps_drain_timeout:1", "deps begin after the wrapper loss")
        if rig.deps_states(lane_b) != []:
            raise _LaneGateError("the timed-out deps claim stayed after the wrapper loss")
        if time.monotonic() - killed > LANE_GATE_ORPHAN_S:
            second.stop()
        if time.monotonic() > deadline:
            raise _LaneGateError("deps begin never reached exclusive after the wrapper loss")
        time.sleep(0.1)
    if rig.deps_states(lane_b) != ["exclusive"] or rig.gates(lane_a) != []:
        raise _LaneGateError(
            f"after the drain: deps {rig.deps_states(lane_b)}, gates {rig.gates(lane_a)}"
        )
    _lane_gate_must(rig.deps(lane_b, "end"), "deps end after the wrapper loss")


def case_lane_gate() -> int:
    """AC-785.33 / AC-785.40: ``tools/lanes.py gate run`` and ``deps`` in a fresh adoption.

    Lane A runs a gate, so lane B's ``deps begin --wait-s 0`` refuses
    ``deps_drain_timeout:1`` and clears its claim; after A's gate ends, B is
    ``exclusive`` and A's next ``gate run`` refuses ``deps_pending``. Then the
    wrapper-loss step kills only the ``gate run`` process while its child lives:
    ``deps begin`` is never ``exclusive`` while that child lives.
    """
    cleanup: list[Callable[[], None]] = []
    with tempfile.TemporaryDirectory(
        prefix="adopt-lane-gate-", ignore_cleanup_errors=True
    ) as tmp:
        rig = _LaneGateRig(Path(tmp))
        try:
            rig.build()
            _lane_gate_steps(rig, cleanup)
        except _LaneGateError as exc:
            return _out("REFUSE", f"lane-gate: {exc}", 1)
        except subprocess.TimeoutExpired as exc:
            return _out("REFUSE", f"lane-gate: a child timed out: {exc.cmd!r}", 1)
        finally:
            # Cleanup is best effort, so a cleanup error never hides the result;
            # each one is reported on stderr.
            for step in reversed(cleanup):
                try:
                    step()
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f"lane-gate cleanup: {exc}", file=sys.stderr)
    return _out(
        "OK",
        "lane-gate: gate run registers, deps drains and refuses, wrapper loss never exclusive",
        0,
    )


CASES = {
    "wp1": case_wp1,
    "templates-installed": case_templates_installed,
    "d9-no": case_d9_no,
    "d6": case_d6,
    "profile-permissions": case_profile_permissions,
    "hd03": case_hd03,
    "wp7": case_wp7,
    "lane-gate": case_lane_gate,
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--case", required=True, choices=sorted(CASES))
    args = p.parse_args()
    try:
        return int(CASES[args.case]())
    except OSError as exc:
        return _out("FAIL-CLOSED", str(exc), 3)


if __name__ == "__main__":
    raise SystemExit(main())
