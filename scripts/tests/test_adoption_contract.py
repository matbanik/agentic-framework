#!/usr/bin/env python3
"""Adoption-contract runner for portable-adopter-bootstrap.

Cases (plan Verification Plan §6):
  wp1, templates-installed, d9-no, d6, profile-permissions, hd03, wp7

First stdout line is always OK: / REFUSE: / USAGE: / FAIL-CLOSED:.
Exit 0/1/2/3. Writes nothing except under RECEIPTS_DIR when a case records a fixture.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

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


CASES = {
    "wp1": case_wp1,
    "templates-installed": case_templates_installed,
    "d9-no": case_d9_no,
    "d6": case_d6,
    "profile-permissions": case_profile_permissions,
    "hd03": case_hd03,
    "wp7": case_wp7,
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
