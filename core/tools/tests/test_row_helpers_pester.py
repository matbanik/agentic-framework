"""MEU-986 row-helper module: the Pester run of its tests (AC-986.10).

Plan 2026-11-26-row-helper-module. The gate has no Pester stage, so this wrapper
runs Pester 5.7.1 on ``tools/tests/RowHelpers.Tests.ps1`` in a child ``pwsh``
with ``New-PesterConfiguration``. The run passes only with ``FailedCount`` 0,
``FailedContainersCount`` 0, ``SkippedCount`` 0, ``NotRunCount`` 0 and a
``PassedCount`` above 0. The wrapper skips only when ``pwsh`` or Pester 5.7.1 is
missing; the project plan rows ``986-V`` and ``M`` prove that it did not skip (D-14).

Two more tests run the same check on small Pester files in ``tmp_path``: one
with a failing ``It`` and one that fails its container. Both runs must fail
the check.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
PESTER_FILE = ROOT / "tools" / "tests" / "RowHelpers.Tests.ps1"
TIMEOUT_S = 600
COUNTS_MARK = "PESTER_COUNTS "

#: The child runner: Pester 5.7.1, one configuration, one JSON line of counts.
RUNNER = """param([Parameter(Mandatory)][string]$Path)
$ErrorActionPreference = 'Stop'
Import-Module Pester -RequiredVersion 5.7.1 -Force
$c = New-PesterConfiguration
$c.Run.Path = $Path
$c.Run.PassThru = $true
$c.Output.Verbosity = 'Detailed'
$c.Output.RenderMode = 'Plaintext'
$r = Invoke-Pester -Configuration $c
$counts = [ordered]@{
    total = $r.TotalCount
    passed = $r.PassedCount
    failed = $r.FailedCount
    skipped = $r.SkippedCount
    not_run = $r.NotRunCount
    failed_containers = $r.FailedContainersCount
}
'PESTER_COUNTS ' + ($counts | ConvertTo-Json -Compress)
exit 0
"""

#: The probe for the installed Pester version.
PROBE = (
    "if (Get-Module -ListAvailable Pester | Where-Object { $_.Version -eq [version]'5.7.1' }) "
    "{ 'pester_found' } else { 'pester_missing' }"
)

FAILING_IT = """Describe 'one red' {
    It 'passes' { 1 | Should -Be 1 }
    It 'fails' { 1 | Should -Be 2 }
}
"""

FAILING_CONTAINER = """throw 'container breaks'
Describe 'never reached' {
    It 'passes' { 1 | Should -Be 1 }
}
"""


@dataclass(frozen=True)
class PesterCounts:
    """The counts of one Pester run."""

    total: int
    passed: int
    failed: int
    skipped: int
    not_run: int
    failed_containers: int


def _require_pester() -> str:
    """Return the ``pwsh`` path; skip only when ``pwsh`` or Pester 5.7.1 is missing.

    Raises:
        AssertionError: the version probe gives neither answer.
    """
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is missing")
    done = subprocess.run(
        [pwsh, "-NoProfile", "-Command", PROBE],
        capture_output=True,
        timeout=120,
        check=False,
    )
    out = (done.stdout + done.stderr).decode("utf-8", "replace")
    if "pester_missing" in out:
        pytest.skip("Pester 5.7.1 is missing")
    assert "pester_found" in out, (
        f"Pester probe failed (exit {done.returncode}):\n{out}"
    )
    return pwsh


def run_pester(pwsh: str, path: Path, work: Path) -> tuple[PesterCounts, str]:
    """Run Pester 5.7.1 on ``path`` in a child ``pwsh``; return its counts and its output.

    Raises:
        AssertionError: the child exits nonzero or prints no counts line.
    """
    runner = work / "pester-runner.ps1"
    runner.write_text(RUNNER, encoding="utf-8", newline="\n")
    done = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(runner), "-Path", str(path)],
        cwd=ROOT,
        capture_output=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    out = (done.stdout + done.stderr).decode("utf-8", "replace")
    tail = "\n".join(out.splitlines()[-40:])
    assert done.returncode == 0, f"Pester runner exit {done.returncode}:\n{tail}"
    lines = [ln for ln in out.splitlines() if ln.startswith(COUNTS_MARK)]
    assert lines, f"no counts line:\n{tail}"
    data = json.loads(lines[-1][len(COUNTS_MARK) :])
    return PesterCounts(**{k: int(v) for k, v in data.items()}), out


def assert_green(counts: PesterCounts, out: str) -> None:
    """Fail unless the run has no failed test or container, no skip, and a pass.

    Raises:
        AssertionError: one message for each broken rule, with the run output tail.
    """
    problems = [
        f"{name}={value}"
        for name, value in (
            ("failed", counts.failed),
            ("failed_containers", counts.failed_containers),
            ("skipped", counts.skipped),
            ("not_run", counts.not_run),
        )
        if value != 0
    ]
    if counts.passed <= 0:
        problems.append(f"passed={counts.passed}")
    tail = "\n".join(out.splitlines()[-60:])
    assert not problems, f"Pester run not green: {', '.join(problems)}\n{tail}"


def test_f2p_986_pester_suite_is_green(tmp_path: Path) -> None:
    """AC-986.10: the Pester file of the module passes in full under Pester 5.7.1."""
    pwsh = _require_pester()
    assert PESTER_FILE.is_file(), f"missing {PESTER_FILE}"
    counts, out = run_pester(pwsh, PESTER_FILE, tmp_path)
    assert_green(counts, out)


def test_wrapper_fails_on_a_failing_it(tmp_path: Path) -> None:
    """AC-986.10 negative: a Pester file with one failing It fails the check."""
    pwsh = _require_pester()
    path = tmp_path / "OneRed.Tests.ps1"
    path.write_text(FAILING_IT, encoding="utf-8", newline="\n")
    counts, out = run_pester(pwsh, path, tmp_path)
    assert (counts.passed, counts.failed) == (1, 1), counts
    with pytest.raises(AssertionError, match="failed=1"):
        assert_green(counts, out)


def test_wrapper_fails_on_a_failing_container(tmp_path: Path) -> None:
    """AC-986.10 negative: a Pester file that fails its container fails the check."""
    pwsh = _require_pester()
    path = tmp_path / "Broken.Tests.ps1"
    path.write_text(FAILING_CONTAINER, encoding="utf-8", newline="\n")
    counts, out = run_pester(pwsh, path, tmp_path)
    assert counts.failed_containers == 1, counts
    with pytest.raises(AssertionError, match="failed_containers=1"):
        assert_green(counts, out)
