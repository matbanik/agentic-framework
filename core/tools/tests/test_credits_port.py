"""Port tests for the scheduled credits runs (AC-J.1, AC-J.2).

AC-J.1  Port step 1: ``Invoke-ClaudeDispatch.ps1`` takes ``-ApiKeyFile`` and every other
        parameter the credits front end passes; ``Get-ClaudeDispatch.ps1`` and
        ``stop_gate.py`` (with the ``done`` release) are in ``core/tools/``.
AC-J.2  Every file of the port inventory is at its framework path in template form: it
        compiles, the ported tests collect, the probe kit self-test passes, and the lines
        added under ``core/`` hold no local drive path, no source project name and no model
        slug. ``executor_worktree.py`` reads the project parts from an adopter config file.

These tests check the package itself, so they skip in an adopter tree, which has no
``scripts/instantiate.py``. Each test loads its module inside its body, so a missing file
fails that test and never errors the collection.
"""

from __future__ import annotations

import importlib.util
import json
import py_compile
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

PKG = Path(__file__).resolve().parents[3]
CORE = PKG / "core"
TOOLS = CORE / "tools"
SKILL = CORE / ".agent" / "skills" / "claude-credits"
PROBES = SKILL / "probes"
TESTS = TOOLS / "tests"

pytestmark = pytest.mark.skipif(
    not (PKG / "scripts" / "instantiate.py").is_file() or not CORE.is_dir(),
    reason="package test: needs the framework checkout (scripts/instantiate.py and core/)",
)

#: The framework commit the port starts from (row 0, PORT_BASE).
PORT_BASE = "e387dec"

SKILL_FILES = (
    "SKILL.md",
    "CreditsRun.psm1",
    "Invoke-ClaudeCredits.ps1",
    "Register-CreditsRun.ps1",
    "Start-CreditsRunTask.ps1",
    "Start-CreditsRun.ps1",
    "Stop-CreditsRun.ps1",
    "Watch-CreditsRuns.ps1",
    "Get-CreditsRun.ps1",
    "Send-CreditsRunMessage.ps1",
    "schemas/credits-run.v1.json",
    "schemas/credits-msg.v1.json",
    "schemas/credits-outbox.v1.json",
    "templates/resume-brief.md",
    "probes/README.md",
    "probes/kit.py",
    "probes/run_gate.py",
    "probes/inbox_hook.py",
)
CORE_FILES = (
    ".agent/credits/config.json",
    ".agent/credits/worktree.json",
    ".claude/hooks/credits_inbox.py",
    ".claude/settings.hooks.json",
    "tools/credits_state.py",
    "tools/credits_msg.py",
    "tools/completion_preflight.py",
    "tools/executor_worktree.py",
    "tools/stop_gate.py",
    "tools/Get-ClaudeDispatch.ps1",
    "tools/Invoke-ClaudeDispatch.ps1",
)
PORTED_PYTEST = (
    "test_credits_state.py",
    "test_credits_state_crash.py",
    "test_credits_msg.py",
    "test_credits_inbox.py",
    "test_credits_ruling.py",
    "test_credits_wait.py",
    "test_credits_stop_reminder.py",
    "test_stop_gate.py",
    "test_stop_gate_done.py",
    "test_completion_preflight.py",
    "test_executor_worktree.py",
    "test_executor_worktree_base.py",
)
PORTED_PESTER = (
    "ClaudeCredits.Manual",
    "ClaudeCredits.Wrapper",
    "CreditsChain",
    "CreditsRuling",
    "CreditsRun.Job",
    "CreditsStopPath",
    "Get-CreditsRun.Settle",
    "Get-CreditsRun",
    "Register-CreditsRun",
    "Send-CreditsRunMessage",
    "Start-CreditsRun",
    "Start-CreditsRunTask",
    "Watch-CreditsRuns",
)
WORKTREE_TEMPLATE = {
    "env_files": [".env"],
    "frozen_dirs": [],
    "venv_build": None,
    "linked_trees": ["node_modules"],
}

#: The source project's name, split so this file does not hold it.
SOURCE_NAME = "zori" + "vest"
LEAK_PATTERNS = (
    ("local drive path", re.compile(r"P:[\\/]")),
    ("user profile path", re.compile(r"[A-Za-z]:[\\/]Users[\\/]")),
    ("source project name", re.compile(SOURCE_NAME, re.IGNORECASE)),
    (
        "model slug",
        re.compile(
            r"\b(?:claude-(?:opus|sonnet|haiku|fable)-\d|gpt-\d|o\d-(?:mini|pro)\b|"  # <!-- model-slug-ok: the leak detector's own pattern, names no model to route to -->
            r"gemini-\d|grok-\d)",
            re.IGNORECASE,
        ),
    ),
)


# --- helpers ------------------------------------------------------------------------------


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _load(name: str, path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    assert path.is_file(), f"{path.relative_to(PKG).as_posix()} is missing"
    monkeypatch.syspath_prepend(str(path.parent))
    monkeypatch.syspath_prepend(str(CORE))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def _pwsh(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("pwsh")
    assert exe is not None, "pwsh (PowerShell 7) is not on PATH"
    # -Command appends every later argument to the command text, so the arguments go to a
    # script block as quoted literals; there they are $args and nothing runs them.
    quoted = " ".join("'" + arg.replace("'", "''") + "'" for arg in args)
    return subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-Command", f"& {{ {script} }} {quoted}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


_PARSE = (
    "$errs = $null; $toks = $null; "
    "$ast = [System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$toks, [ref]$errs); "
    "\"ERRORS=$($errs.Count)\"; "
    "foreach ($e in $errs) { \"ERROR $($e.Extent.StartLineNumber): $($e.Message)\" }; "
    "if ($ast.ParamBlock) { foreach ($p in $ast.ParamBlock.Parameters) { "
    "$d = if ($p.DefaultValue) { $p.DefaultValue.Extent.Text } else { '' }; "
    "\"PARAM $($p.Name.VariablePath.UserPath)=$d\" } }"
)


def _parse(path: Path) -> tuple[int, dict[str, str], str]:
    """Parse a PowerShell file; return its error count, its script params and the output."""
    assert path.is_file(), f"{path.relative_to(PKG).as_posix()} is missing"
    result = _pwsh(_PARSE, str(path))
    out = result.stdout + result.stderr
    match = re.search(r"^ERRORS=(\d+)$", result.stdout, re.MULTILINE)
    assert match is not None, out
    params = dict(
        line[len("PARAM ") :].split("=", 1)
        for line in result.stdout.splitlines()
        if line.startswith("PARAM ")
    )
    return int(match.group(1)), params, out


def _dispatch_arg_keys() -> set[str]:
    """Every parameter name ``Invoke-ClaudeCredits.ps1`` puts into ``$dispatchArgs``."""
    text = _text(SKILL / "Invoke-ClaudeCredits.ps1")
    literal = re.search(r"(?ms)^\$dispatchArgs = @\{\n(.*?)^\}", text)
    assert literal is not None, "no $dispatchArgs hashtable literal"
    keys = set(re.findall(r"(?m)^\s+(\w+)\s+=", literal.group(1)))
    keys |= set(re.findall(r"\$dispatchArgs\.(\w+)\s*=", text))
    return keys


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(PKG), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _added_core_lines() -> list[tuple[str, str]]:
    """(path, line) for every line added under ``core/`` since PORT_BASE, untracked files
    included, this file excluded."""
    me = Path(__file__).resolve().relative_to(PKG).as_posix()
    added: list[tuple[str, str]] = []
    path = ""
    for line in _git("diff", "--unified=0", "--no-color", PORT_BASE, "--", "core/").splitlines():
        if line.startswith("+++ "):
            path = line[len("+++ b/") :] if line.startswith("+++ b/") else ""
        elif line.startswith("+") and path and path != me:
            added.append((path, line[1:]))
    for rel in _git("ls-files", "--others", "--exclude-standard", "--", "core/").splitlines():
        if rel == me or "__pycache__" in rel:
            continue
        data = (PKG / rel).read_bytes()
        if b"\0" in data:
            continue
        added.extend((rel, ln) for ln in data.decode("utf-8", "replace").splitlines())
    return added


# --- AC-J.1: the base brought up to date ---------------------------------------------------


def test_dispatch_wrapper_takes_every_credits_argument() -> None:
    """AC-J.1: the wrapper parses with 0 errors and declares ``-ApiKeyFile`` and every
    other key that the credits front end splats into it."""
    errors, params, out = _parse(TOOLS / "Invoke-ClaudeDispatch.ps1")
    assert errors == 0, out
    assert "ApiKeyFile" in params, sorted(params)
    keys = _dispatch_arg_keys()
    assert "ApiKeyFile" in keys and "LaunchHook" in keys, sorted(keys)
    missing = sorted(keys - set(params))
    assert not missing, f"Invoke-ClaudeDispatch.ps1 lacks parameters {missing}"


def test_dispatch_status_reader_is_ported() -> None:
    """AC-J.1: ``Get-ClaudeDispatch.ps1`` parses and reads ``{{RECEIPTS_DIR}}/dispatch``."""
    errors, params, out = _parse(TOOLS / "Get-ClaudeDispatch.ps1")
    assert errors == 0, out
    assert params.get("OutputDir") == "'{{RECEIPTS_DIR}}/dispatch'", params


_TASK = """\
---
project: "2026-01-01-demo"
status: "in_progress"
stop_gate: "{gate}"
---

# Task — Demo

| # | Task | Owner | Deliverable | Validation | Status |
|---|------|-------|-------------|------------|--------|
| 1 | Implement thing | coder | code | `pytest` | `[x]` |
| H1-6 | Create handoff | reviewer | handoff.md | `rg Evidence h.md` | `[ ]` |
"""


def _plan(repo: Path, gate: str) -> Path:
    folder = repo / "docs" / "execution" / "plans" / "2026-01-01-demo"
    folder.mkdir(parents=True)
    task = folder / "task.md"
    task.write_text(_TASK.format(gate=gate), encoding="utf-8")
    return task


def test_stop_gate_accepts_released_done(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-J.1: ``released:done`` is a sanctioned stop; an armed plan with an open row
    blocks."""
    gate = _load("stop_gate_under_test", TOOLS / "stop_gate.py", monkeypatch)
    assert gate.release_reason("released:done") == "done"
    assert gate.release_reason("released:blocked-resources") is None
    done_repo = tmp_path / "done"
    _plan(done_repo, "released:done")
    assert gate.evaluate(done_repo)[0] is True
    open_repo = tmp_path / "open"
    _plan(open_repo, "armed")
    done, reason = gate.evaluate(open_repo)
    assert done is False, reason
    assert "H1-6" in reason


# --- AC-J.2: the inventory, in template form ------------------------------------------------


@pytest.mark.parametrize("rel", SKILL_FILES)
def test_skill_file_is_ported(rel: str) -> None:
    """AC-J.2: each claude-credits skill file is in ``core/.agent/skills/claude-credits``."""
    assert (SKILL / rel).is_file(), rel


@pytest.mark.parametrize("rel", CORE_FILES)
def test_core_file_is_ported(rel: str) -> None:
    """AC-J.2: each tool, hook and config file is at its framework path."""
    assert (CORE / rel).is_file(), rel


def test_ported_tests_are_present() -> None:
    """AC-J.2: the module tests are in ``core/tools/tests``: 12 pytest and 14 Pester."""
    missing = [n for n in PORTED_PYTEST if not (TESTS / n).is_file()]
    missing += [f"{n}.Tests.ps1" for n in PORTED_PESTER if not (TESTS / f"{n}.Tests.ps1").is_file()]
    assert not missing, missing


def _python_files() -> list[Path]:
    files = [CORE / rel for rel in CORE_FILES if rel.endswith(".py")]
    files += sorted(p for p in SKILL.rglob("*.py") if "__pycache__" not in p.parts)
    files += [TESTS / n for n in PORTED_PYTEST]
    return files


def test_python_files_compile(tmp_path: Path) -> None:
    """AC-J.2: every ported Python file compiles."""
    files = _python_files()
    assert all(p.is_file() for p in files), [str(p) for p in files if not p.is_file()]
    for index, path in enumerate(files):
        py_compile.compile(str(path), cfile=str(tmp_path / f"{index}.pyc"), doraise=True)


def test_powershell_files_parse() -> None:
    """AC-J.2: every ported PowerShell file parses with 0 errors."""
    files = sorted(SKILL.rglob("*.ps1")) + sorted(SKILL.rglob("*.psm1"))
    files += [TOOLS / "Get-ClaudeDispatch.ps1"]
    files += [TESTS / f"{n}.Tests.ps1" for n in PORTED_PESTER]
    assert len(files) > len(PORTED_PESTER) + 9, files
    bad = []
    for path in files:
        if not path.is_file():
            bad.append(f"{path.relative_to(PKG).as_posix()} missing")
            continue
        errors, _params, out = _parse(path)
        if errors:
            bad.append(f"{path.relative_to(PKG).as_posix()}: {out}")
    assert not bad, bad


def test_ported_pytest_files_collect() -> None:
    """AC-J.2: the ported pytest files collect in the package with 0 errors."""
    files = [str(TESTS / n) for n in PORTED_PYTEST]
    assert all(Path(f).is_file() for f in files), files
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", *files],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(CORE),
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


def test_probe_kit_self_test_passes(tmp_path: Path) -> None:
    """AC-J.2: ``run_gate.py --self-test`` exits 0 in a copy of the ported kit."""
    assert (PROBES / "run_gate.py").is_file()
    kit = tmp_path / "probes"
    shutil.copytree(PROBES, kit, ignore=shutil.ignore_patterns("__pycache__"))
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(kit / "run_gate.py"), "--self-test"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(kit),
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]


def test_added_lines_hold_no_project_leak() -> None:
    """AC-J.2: the lines added under ``core/`` hold no drive path, user profile path,
    source project name or model slug."""
    added = _added_core_lines()
    assert any(rel.startswith("core/.agent/skills/claude-credits/") for rel, _ in added), (
        "no claude-credits lines were added under core/"
    )
    leaks = [
        f"{rel}: {label}: {line.strip()[:120]}"
        for rel, line in added
        for label, pattern in LEAK_PATTERNS
        if pattern.search(line)
    ]
    assert not leaks, "\n".join(leaks[:50])


def test_leak_scan_catches_each_pattern() -> None:
    """AC-J.2: each leak pattern matches its sample, so the scan above is not vacuous."""
    samples = {
        "local drive path": "root = 'P:/acme'",
        "user profile path": "C:\\Users\\someone\\.claude",
        "source project name": f"\\{SOURCE_NAME.title()}\\Credits\\",
        "model slug": "Model = 'claude-opus-5-5'",  # <!-- model-slug-ok: a sample the leak detector must catch, not a routing pin -->
    }
    for label, pattern in LEAK_PATTERNS:
        assert pattern.search(samples[label]), label
    assert not any(p.search("{{PROJECT_NAME_TITLE}} {{RECEIPTS_DIR}}/credits") for _l, p in LEAK_PATTERNS)


def test_module_uses_tokens_for_project_names() -> None:
    """AC-J.2: the shared module names its task folder and mutex from tokens."""
    text = _text(SKILL / "CreditsRun.psm1")
    assert "\\{{PROJECT_NAME_TITLE}}\\Credits\\" in text
    assert "{{PROJECT_NAME_UPPER}}Credits-" in text
    register = _text(SKILL / "Register-CreditsRun.ps1")
    assert "'{{RECEIPTS_DIR}}/credits/state.db'" in register


# --- AC-J.2: the executor worktree helper reads an adopter config ---------------------------


def test_worktree_helper_has_no_project_gate_import() -> None:
    """AC-J.2: ``executor_worktree.py`` does not import the source project's gate module."""
    text = _text(TOOLS / "executor_worktree.py")
    assert "validate_codebase" not in text


def test_worktree_config_template_keys() -> None:
    """AC-J.2: the adopter config template has exactly the four project parts."""
    assert json.loads(_text(CORE / ".agent" / "credits" / "worktree.json")) == WORKTREE_TEMPLATE


def _worktree(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return _load("executor_worktree_under_test", TOOLS / "executor_worktree.py", monkeypatch)


def _write_config(root: Path, data: object) -> None:
    path = root / ".agent" / "credits" / "worktree.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_worktree_config_loads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-J.2: ``load_worktree_config`` returns the adopter's values."""
    ew = _worktree(monkeypatch)
    data = {**WORKTREE_TEMPLATE, "frozen_dirs": ["ui/dist"], "venv_build": ["uv", "sync"]}
    _write_config(tmp_path, data)
    assert ew.load_worktree_config(tmp_path) == data


@pytest.mark.parametrize(
    "data",
    [
        None,
        {**WORKTREE_TEMPLATE, "extra": True},
        {k: v for k, v in WORKTREE_TEMPLATE.items() if k != "linked_trees"},
        {**WORKTREE_TEMPLATE, "env_files": ".env"},
        {**WORKTREE_TEMPLATE, "frozen_dirs": [1]},
        {**WORKTREE_TEMPLATE, "venv_build": "uv sync"},
        [],
    ],
    ids=["missing", "unknown-key", "missing-key", "str-list", "int-item", "str-command", "array"],
)
def test_worktree_config_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, data: object
) -> None:
    """AC-J.2: a missing file, an unknown or missing key, or a wrong type is refused."""
    ew = _worktree(monkeypatch)
    if data is not None:
        _write_config(tmp_path, data)
    with pytest.raises(ew.WorktreeConfigError):
        ew.load_worktree_config(tmp_path)
