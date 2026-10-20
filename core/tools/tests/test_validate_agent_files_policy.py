"""B-7 tests for ``tools/validate_agent_files.py --policy run-parameters`` (WP-9; AC-H.2, R§4.8).

The policy mode checks the effective governance text, not the presence of one sentence: each
approved after-line of the R§7 ledger (``AGENTS.md`` ``:8`` and ``:36``, ``GUARDRAILS.md`` ``:13``
and ``:43``) is present by digest and each retired before-line is absent; the framework
ledger has no "Commits" bullet (D-42 A). The expected lines come from the approved
governance diffs
(``.agent/run-parameters/governance/01-agents.diff`` and ``02-guardrails.diff``): a tree built from their
``+`` lines is the approved text, and their ``-`` lines are the retired text.

The check is the pure function ``check_run_parameters_policy(top, d20)``, which returns the
failures as ``(check, message)`` pairs, and the CLI mode, which exits 0 or 1 and names each
failing check and line. The seven existing checks are untouched (EA-34).
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType

import pytest

from tools.tests.run_parameters_fixtures import phase_b7

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE = ROOT / phase_b7.GOVERNANCE
SCRIPT = ROOT / "tools" / "validate_agent_files.py"
# check id -> (file, index of its before/after pair in that file's diff)
PAIRS: dict[str, tuple[str, int]] = {
    "hard_gate_2": ("AGENTS.md", 0),
    "human_gate": ("AGENTS.md", 1),
    "sign1_replacement": ("GUARDRAILS.md", 0),
    "sign3_b_grant": ("GUARDRAILS.md", 1),
}
EXISTING_CHECKS = (
    "Check 1: Root AGENTS.md line count",
    "Check 2: CLAUDE.md redirect",
    "Check 3: .windsurfrules redirect",
    "Check 3a: .devin/rules/ redirect",
    "Check 4: Per-package AGENTS.md existence",
    "Check 5: Per-package AGENTS.md line limit",
    "Check 6: Required sections",
)


# -- helpers -------------------------------------------------------------------------------


def _vaf() -> ModuleType:
    """The module under test, imported inside a test body (a Red import error is a failure)."""
    return importlib.import_module("tools.validate_agent_files")


def _diff(name: str) -> tuple[list[str], list[str]]:
    """The (before, after) lines of the approved diff of ``name``."""
    text = (GOVERNANCE / phase_b7.GOVERNANCE_DIFFS[name]).read_text(encoding="utf-8")
    return phase_b7.diff_lines(text)


def _approved() -> dict[str, list[str]]:
    """The approved after-lines per governance file."""
    return {name: _diff(name)[1] for name in phase_b7.GOVERNANCE_DIFFS}


def _tree(
    tmp_path: Path, files: Mapping[str, Sequence[str]], *, eol: str = "\n"
) -> Path:
    """A repository root holding the given governance files, one paragraph per line."""
    top = tmp_path / "top"
    top.mkdir(exist_ok=True)
    for name, lines in files.items():
        text = eol.join([f"# {name}", "", *lines, ""])
        (top / name).write_bytes(text.encode("utf-8"))
    return top


def _check(top: Path, d20: str = "A") -> list[tuple[str, str]]:
    fn = getattr(_vaf(), "check_run_parameters_policy")
    failures = fn(top, d20)
    assert isinstance(failures, list), failures
    return [(str(check), str(message)) for check, message in failures]


def _cli(top: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(SCRIPT),
            "--policy",
            "run-parameters",
            "--repo-root",
            str(top),
            *extra,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )


def _listing(top: Path) -> list[tuple[str, int, int]]:
    return sorted(
        (str(p.relative_to(top)), p.stat().st_size, p.stat().st_mtime_ns)
        for p in top.rglob("*")
    )


# -- tests ---------------------------------------------------------------------------------


def test_ac_h2_approved_text_passes(tmp_path: Path) -> None:
    """AC-H.2: the approved after-lines, no before-line → no failure, exit 0, nothing written."""
    top = _tree(tmp_path, _approved())
    before = _listing(top)
    assert _check(top) == []
    done = _cli(top, "--d20", "A")
    assert done.returncode == 0, done.stdout + done.stderr
    assert _listing(top) == before


@pytest.mark.parametrize("check", sorted(PAIRS))
def test_ac_h2_before_line_instead_of_after_fails(tmp_path: Path, check: str) -> None:
    """AC-H.2: a retired before-line in place of its after-line → that check fails, exit 1."""
    name, index = PAIRS[check]
    files = _approved()
    before, _ = _diff(name)
    files[name] = list(files[name])
    files[name][index] = before[index]
    top = _tree(tmp_path, files)
    failures = _check(top)
    assert {c for c, _ in failures} == {check}, failures
    assert any(f"{name}:" in message for _, message in failures), failures
    done = _cli(top, "--d20", "A")
    assert done.returncode == 1, done.stdout + done.stderr
    assert check in done.stdout, done.stdout


@pytest.mark.parametrize("check", sorted(PAIRS))
def test_ac_h2_before_line_beside_after_fails(tmp_path: Path, check: str) -> None:
    """AC-H.2: the after-line present but its before-line kept as well → that check fails."""
    name, index = PAIRS[check]
    files = _approved()
    before, _ = _diff(name)
    files[name] = [*files[name], before[index]]
    top = _tree(tmp_path, files)
    assert {c for c, _ in _check(top)} == {check}


@pytest.mark.parametrize("check", sorted(PAIRS))
def test_ac_h2_after_line_missing_fails(tmp_path: Path, check: str) -> None:
    """AC-H.2: an after-line absent (and no before-line) → that check fails."""
    name, index = PAIRS[check]
    files = _approved()
    files[name] = [line for i, line in enumerate(files[name]) if i != index]
    top = _tree(tmp_path, files)
    assert {c for c, _ in _check(top)} == {check}


def test_ac_h2_after_line_must_be_whole(tmp_path: Path) -> None:
    """AC-H.2: the after-line is checked by digest, so a truncated copy does not count."""
    files = _approved()
    files["GUARDRAILS.md"] = list(files["GUARDRAILS.md"])
    files["GUARDRAILS.md"][1] = files["GUARDRAILS.md"][1][:-1]
    top = _tree(tmp_path, files)
    assert {c for c, _ in _check(top)} == {"sign3_b_grant"}


def test_ac_h2_crlf_text_passes(tmp_path: Path) -> None:
    """AC-H.2: the text check reads lines without their EOL, so CRLF governance files pass."""
    top = _tree(tmp_path, _approved(), eol="\r\n")
    assert b"\r\n" in (top / "AGENTS.md").read_bytes()
    assert _check(top) == []


@pytest.mark.parametrize("name", sorted(phase_b7.GOVERNANCE_DIFFS))
def test_ac_h2_missing_file_fails(tmp_path: Path, name: str) -> None:
    """AC-H.2: an absent governance file fails its checks; the function does not raise."""
    files = _approved()
    del files[name]
    top = _tree(tmp_path, files)
    expected = {c for c, (f, _) in PAIRS.items() if f == name}
    assert expected <= {c for c, _ in _check(top)}
    assert _cli(top, "--d20", "A").returncode == 1


def test_ac_h2_d20_b_fails_closed(tmp_path: Path) -> None:
    """AC-H.2 (EA-34): no approved D-13 sentence exists here, so D-20 B fails ``sign3_b_grant``."""
    top = _tree(tmp_path, _approved())
    assert [c for c, _ in _check(top, "B")] == ["sign3_b_grant"]
    assert _cli(top, "--d20", "B").returncode == 1


def test_ac_h2_existing_checks_untouched() -> None:
    """AC-H.2: the policy check is a separate mode; the existing checks are the same seven."""
    names = tuple(name for name, _ in _vaf().ALL_CHECKS)
    assert names == EXISTING_CHECKS
    assert callable(getattr(_vaf(), "check_run_parameters_policy"))


def test_ac_h2_repository_text_passes() -> None:
    """AC-H.1/AC-H.2: the working copy carries the approved texts (row 20 applies them)."""
    done = _cli(ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
