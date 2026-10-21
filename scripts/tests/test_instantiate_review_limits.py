"""Installer tests for the repo review limits (AC-1 … AC-4).

AC-1  ``core/.agent/review-limits.json`` ships ``token_budgets: "on"`` and the rounds and
      tokens of ``review_ledger.ROUND_BUDGETS`` and ``TOKEN_BUDGETS``, so the two cannot
      drift.
AC-2  ``--round-caps`` and ``--token-budgets`` (or ``ROUND_CAPS`` and ``TOKEN_BUDGETS`` in a
      ``--config`` file; the flag wins) write the adopted file; a bad value exits 2 and
      writes nothing.
AC-3  With neither answer the adopted file stays byte-identical to the shipped one.
AC-4  ``--verify`` reports a file that ``review_ledger.load_repo_limits`` refuses.

Each test loads the installer inside its body, so a missing function fails that test and
never errors the collection. Every tree the tests write is a temporary copy of ``core/``.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
INSTALLER = ROOT / "scripts" / "instantiate.py"
LEDGER = CORE / "tools" / "review_ledger.py"
SHIPPED = CORE / ".agent" / "review-limits.json"
LIMITS_REL = ".agent/review-limits.json"
MODES = ("plan", "execution", "discovery", "handoff", "multi-handoff")

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


# --- helpers ------------------------------------------------------------------------------


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_installer() -> ModuleType:
    return _load(INSTALLER, "instantiate_under_test")


def _copy_core(dest: Path) -> Path:
    """Copy the package into ``dest`` as ADOPTION-GUIDE Step 2 does."""
    for src_rel, dst_rel in COPY_MAP:
        src = ROOT / src_rel
        dst = dest / dst_rel
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return dest


def _values(root: Path) -> dict[str, str]:
    return {
        "project_name": "acme",
        "project_root": str(root),
        "receipts_dir": "C:/Temp/acme",
        "repo_url": "github.com/you/acme",
    }


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(INSTALLER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


def _cli_values(root: Path) -> list[str]:
    v = _values(root)
    return [
        "--root",
        str(root),
        "--project-name",
        v["project_name"],
        "--project-root",
        v["project_root"],
        "--receipts-dir",
        v["receipts_dir"],
        "--repo-url",
        v["repo_url"],
    ]


def _vars_file(root: Path, path: Path, *extra: str) -> Path:
    path.write_text(
        "".join(f"{k.upper()}={val}\n" for k, val in _values(root).items())
        + "".join(f"{line}\n" for line in extra),
        encoding="utf-8",
    )
    return path


def _limits(root: Path) -> dict[str, object]:
    return json.loads((root / LIMITS_REL).read_text(encoding="utf-8"))


@pytest.fixture
def adopter(tmp_path: Path) -> Path:
    return _copy_core(tmp_path / "acme")


# --- AC-1 ---------------------------------------------------------------------------------


def test_shipped_file_equals_constants() -> None:
    """AC-1: the shipped file is the constants, with token budgets on."""
    ledger = _load(LEDGER, "review_ledger_under_test")
    data = json.loads(SHIPPED.read_text(encoding="utf-8"))
    assert list(data) == ["schema", "token_budgets", "rounds", "tokens"]
    assert data["schema"] == "review-limits/1"
    assert data["token_budgets"] == "on"
    assert data["rounds"] == ledger.ROUND_BUDGETS
    assert data["tokens"] == ledger.TOKEN_BUDGETS
    assert tuple(data["rounds"]) == MODES
    assert tuple(data["tokens"]) == MODES


def test_reader_accepts_the_repo_file() -> None:
    """AC-1: the ledger's own reader accepts the shipped file unchanged."""
    ledger = _load(LEDGER, "review_ledger_under_test")
    assert ledger.load_repo_limits(CORE) == json.loads(SHIPPED.read_text(encoding="utf-8"))


# --- AC-2 ---------------------------------------------------------------------------------

PLAN_LINE = f"write  {LIMITS_REL} rounds=plan:4,execution:8 token_budgets=off"


def _expected_answer() -> dict[str, object]:
    want = json.loads(SHIPPED.read_text(encoding="utf-8"))
    want["token_budgets"] = "off"
    want["rounds"] = {**want["rounds"], "plan": 4, "execution": 8}
    return want


def test_flags_write_the_answers(adopter: Path) -> None:
    """AC-2: the two flags write their values and leave every other mode shipped."""
    result = _cli(*_cli_values(adopter), "--round-caps", "plan=4,execution=8", "--token-budgets", "off")
    assert result.returncode == 0, result.stdout + result.stderr
    assert PLAN_LINE in result.stdout
    assert _limits(adopter) == _expected_answer()


def test_config_answers_give_the_same_bytes(adopter: Path, tmp_path: Path) -> None:
    """AC-2: ``ROUND_CAPS`` and ``TOKEN_BUDGETS`` in the config file write the same bytes."""
    by_flag = _copy_core(tmp_path / "by-flag")
    flag = _cli(*_cli_values(by_flag), "--round-caps", "plan=4,execution=8", "--token-budgets", "off")
    assert flag.returncode == 0, flag.stdout + flag.stderr
    vars_file = _vars_file(
        adopter, tmp_path / "framework.vars", "ROUND_CAPS=plan=4,execution=8", "TOKEN_BUDGETS=off"
    )
    conf = _cli("--root", str(adopter), "--config", str(vars_file))
    assert conf.returncode == 0, conf.stdout + conf.stderr
    assert PLAN_LINE in conf.stdout
    assert (adopter / LIMITS_REL).read_bytes() == (by_flag / LIMITS_REL).read_bytes()


def test_flag_beats_config(adopter: Path, tmp_path: Path) -> None:
    """AC-2: a flag beats the config value, as ``--credits-start-policy`` does."""
    vars_file = _vars_file(
        adopter, tmp_path / "framework.vars", "ROUND_CAPS=plan=5", "TOKEN_BUDGETS=on"
    )
    result = _cli(
        "--root", str(adopter), "--config", str(vars_file),
        "--round-caps", "plan=4,execution=8", "--token-budgets", "off",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _limits(adopter) == _expected_answer()


def test_run_takes_the_answers(adopter: Path) -> None:
    """AC-2: ``run`` takes the answers as arguments, and a dry run writes nothing."""
    inst = _load_installer()
    before = _snapshot(adopter)
    assert inst.run(
        _values(adopter), dry_run=True, root=adopter,
        round_caps="plan=4,execution=8", token_budgets="off",
    ) == 0
    assert _snapshot(adopter) == before


@pytest.mark.parametrize(
    "args",
    [
        ("--round-caps", "plan=0"),
        ("--round-caps", "plan=x"),
        ("--round-caps", "bogus=3"),
        ("--round-caps", "plan=3,plan=4"),
        ("--round-caps", "plan"),
        ("--round-caps", ""),
        ("--round-caps", "plan=-1"),
        ("--token-budgets", "maybe"),
    ],
)
def test_a_bad_answer_exits_2(adopter: Path, args: tuple[str, str]) -> None:
    """AC-2: a bad value is a usage error, exit 2, and the tree is unchanged."""
    before = _snapshot(adopter)
    result = _cli(*_cli_values(adopter), *args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "round-caps" in result.stderr or "token-budgets" in result.stderr or (
        "round_caps" in result.stderr or "token_budgets" in result.stderr
    )
    assert _snapshot(adopter) == before


@pytest.mark.parametrize("line", ["ROUND_CAPS=plan=0", "TOKEN_BUDGETS=maybe"])
def test_a_bad_config_answer_exits_2(adopter: Path, tmp_path: Path, line: str) -> None:
    """AC-2: the same refusal for a config-file answer."""
    before = _snapshot(adopter)
    vars_file = _vars_file(adopter, tmp_path / "framework.vars", line)
    result = _cli("--root", str(adopter), "--config", str(vars_file))
    assert result.returncode == 2, result.stdout + result.stderr
    assert _snapshot(adopter) == before


# --- AC-3 ---------------------------------------------------------------------------------


def test_no_answer_keeps_the_file_identical(adopter: Path) -> None:
    """AC-3: neither flag leaves the file byte-identical to the shipped one."""
    result = _cli(*_cli_values(adopter))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (adopter / LIMITS_REL).read_bytes() == SHIPPED.read_bytes()
    assert LIMITS_REL not in result.stdout


# --- AC-4 ---------------------------------------------------------------------------------


def test_verify_accepts_an_untouched_file(adopter: Path) -> None:
    """AC-4: an instantiated tree with the shipped file verifies."""
    assert _cli(*_cli_values(adopter)).returncode == 0
    result = _cli("--root", str(adopter), "--verify")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra=1),
        lambda d: d["rounds"].update(plan=0),
        lambda d: d.update(token_budgets="maybe"),
        lambda d: d["tokens"].pop("discovery"),
    ],
    ids=["extra-key", "rounds-plan-0", "token-budgets-maybe", "missing-mode"],
)
def test_verify_refuses_a_bad_file(adopter: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    """AC-4: ``--verify`` fails on a file that ``load_repo_limits`` refuses, and writes nothing."""
    assert _cli(*_cli_values(adopter)).returncode == 0
    data = _limits(adopter)
    mutate(data)
    (adopter / LIMITS_REL).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    before = _snapshot(adopter)
    result = _cli("--root", str(adopter), "--verify")
    assert result.returncode == 2, result.stdout + result.stderr
    assert LIMITS_REL in result.stdout
    assert _snapshot(adopter) == before
