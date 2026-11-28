"""MEU-987 runner-path check: ``tools/plan_runner_paths.py`` and its create-plan bullet.

Plan 2026-11-26-row-helper-module (AC-987.1 to AC-987.7). The tool refuses a plan that
runs a script from the receipts folder of another plan. Each test builds a plan folder
in ``tmp_path`` and runs the tool in a child process. The doc test reads
``create-plan.md`` and mutated copies of it. Framework port: the AC-987.5 cases read
real plan folders of the project, so they stay in the project (D-9).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "plan_runner_paths.py"
CREATE_PLAN = ROOT / ".agent" / "workflows" / "create-plan.md"
OWN_SLUG = "2026-11-26-row-helper-module"
OTHER = "other-plan"
RUNNER_EXTS = (".ps1", ".psm1", ".sh", ".py", ".bat", ".cmd")
TIMEOUT_S = 120

#: The receipts root of the package text (a placeholder that the adopter fills in).
RECEIPTS_ROOT = "{{RECEIPTS_DIR}}"

#: The NEUTRAL census pattern of the plan, joined for the same reason.
NEUTRAL_RE = re.compile(
    "zori"
    + "vest|mat"
    + "banik|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[a-z]{2,}|\\b[PC]:[/\\\\]",
    re.IGNORECASE,
)

OWNERSHIP_PREFIX = "- **The ownership check blocks Step 5.**"

#: CP_HUNK of the plan, with ``{root}`` for the receipts root.
CP_BULLET = (
    "- **The runner-path check blocks Step 5.** After you write `task.md`, run "
    "`rtk proxy uv run python tools/plan_runner_paths.py --receipts-root {root} "
    "--plan-dir docs/execution/plans/<slug> *> {root}/runner-paths.txt; "
    "$code=$LASTEXITCODE; Get-Content {root}/runner-paths.txt; exit $code`. "
    "It must print `runner_paths_ok`. A `runner_foreign:<file>:<line>:<path>` line names "
    "a runner in the receipts folder of another plan. Move the runner into this plan's "
    "`artifacts/` folder or call `tools/RowHelpers.psm1`, then run the check again."
)


def _require_tool() -> None:
    """Fail with a clear reason while the tool is absent."""
    assert TOOL.is_file(), f"missing tools/plan_runner_paths.py at {TOOL}"


def run_tool(*args: str) -> tuple[int, list[str]]:
    """Run the tool with ``args``; return its exit code and its output lines."""
    _require_tool()
    done = subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=ROOT,
        capture_output=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    out = (done.stdout + done.stderr).decode("utf-8", "replace")
    return done.returncode, out.splitlines()


def make_plan(base: Path, files: dict[str, str], slug: str = OWN_SLUG) -> Path:
    """Write a plan folder ``base/slug`` with ``files`` (a ``task.md`` is always written)."""
    plan = base / slug
    (plan / "artifacts").mkdir(parents=True, exist_ok=True)
    files = {"task.md": "# task\n", **files}
    for name, text in files.items():
        path = plan / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return plan


def receipts_root(tmp_path: Path) -> str:
    """Return a receipts root under ``tmp_path`` in the ``/`` form."""
    root = tmp_path / "receipts"
    root.mkdir(exist_ok=True)
    return root.as_posix()


def check(root: str, plan: Path) -> tuple[int, list[str]]:
    """Run the tool on ``plan`` with ``root``."""
    return run_tool("--receipts-root", root, "--plan-dir", str(plan))


def foreign(lines: list[str]) -> list[str]:
    """Return the ``runner_foreign`` lines."""
    return [ln for ln in lines if ln.startswith("runner_foreign:")]


def assert_ok(code: int, lines: list[str]) -> None:
    """Fail unless the run passed."""
    assert code == 0, lines
    assert not foreign(lines), lines
    assert any(re.fullmatch(r"runner_paths_ok files=\d+", ln) for ln in lines), lines


def assert_refused(
    code: int, lines: list[str], file: str, line: int, tail: str
) -> None:
    """Fail unless the run exits 1 and names ``file:line`` and a path that ends with ``tail``."""
    assert code == 1, lines
    hits = [
        ln
        for ln in foreign(lines)
        if ln.startswith(f"runner_foreign:{file}:{line}:")
        and ln.lower().endswith(tail.lower())
    ]
    assert hits, lines
    assert not any(ln.startswith("runner_paths_ok") for ln in lines), lines


# ---- AC-987.1: raw runner paths.


@pytest.mark.parametrize("ext", RUNNER_EXTS)
def test_f2p_987_raw_foreign_runner_is_refused(tmp_path: Path, ext: str) -> None:
    """AC-987.1: a raw ``<root>/<other>/x<ext>`` path gives ``runner_foreign`` and exit 1."""
    root = receipts_root(tmp_path)
    plan = make_plan(tmp_path, {"task.md": f"# task\n\nrun `{root}/{OTHER}/x{ext}`\n"})
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 3, f"/{OTHER}/x{ext}")


@pytest.mark.parametrize("tail", ["repin/run.py", "repin/phases.json"])
def test_f2p_987_repin_part_is_a_runner(tmp_path: Path, tail: str) -> None:
    """AC-987.1: a path part that starts with ``repin`` makes a runner path."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path, {"artifacts/run.sh": f"#!/bin/sh\ncp {root}/{OTHER}/{tail} .\n"}
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "artifacts/run.sh", 2, f"/{OTHER}/{tail}")


@pytest.mark.parametrize("ext", RUNNER_EXTS)
def test_f2p_987_own_runner_passes(tmp_path: Path, ext: str) -> None:
    """AC-987.1 negative: the same path under ``<root>/<own slug>/`` passes."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "task.md": f"# task\n\nrun `{root}/{OWN_SLUG}/x{ext}`\n",
            "artifacts/notes.md": f"{root}/{OWN_SLUG}/repin/run.py\n",
        },
    )
    assert_ok(*check(root, plan))


# ---- AC-987.2: variables resolve plan-wide.


def test_f2p_987_value_in_plan_use_in_task(tmp_path: Path) -> None:
    """AC-987.2: a value in ``implementation-plan.md`` and a use in ``task.md`` resolve."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "implementation-plan.md": f"| X | `$s2c='{root}/{OTHER}'` |\n",
            "task.md": "# task\n\n| RP | run the `$s2c/repin.ps1` form |\n",
        },
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 3, f"/{OTHER}/repin.ps1")


@pytest.mark.parametrize(
    "assign",
    [
        "$dir='{root}/{other}'",
        '$dir="{root}/{other}"',
        "dir={root}/{other}",
    ],
)
def test_f2p_987_three_assignment_forms(tmp_path: Path, assign: str) -> None:
    """AC-987.2: the forms ``$x='...'``, ``$x="..."`` and ``x=...`` resolve."""
    root = receipts_root(tmp_path)
    line = assign.format(root=root, other=OTHER)
    plan = make_plan(
        tmp_path, {"artifacts/step.md": f"{line}\nthen run $dir/do.sh now\n"}
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "artifacts/step.md", 2, f"/{OTHER}/do.sh")


def test_f2p_987_names_match_without_case(tmp_path: Path) -> None:
    """AC-987.2: a name in a different case resolves."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "implementation-plan.md": f"$Src='{root}/{OTHER}'\n",
            "task.md": "# task\n\n`$SRC/run.py`\n",
        },
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 3, f"/{OTHER}/run.py")


def test_f2p_987_chain_of_two_names(tmp_path: Path) -> None:
    """AC-987.2: a chain of two names resolves (``R=...``, then ``Q=$R/sub``)."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "task.md": (
                f"# task\n\n`R={root}/{OTHER}; Q=$R/sub; bash $Q/run.sh`\n"
                "`powershell -File ${Q}/b.ps1`\n"
            )
        },
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 3, f"/{OTHER}/sub/run.sh")
    assert_refused(code, lines, "task.md", 4, f"/{OTHER}/sub/b.ps1")


def test_f2p_987_assignment_of_a_foreign_runner_is_refused(tmp_path: Path) -> None:
    """AC-987.2: an assignment whose value is a foreign runner path is refused."""
    root = receipts_root(tmp_path)
    plan = make_plan(tmp_path, {"artifacts/a.ps1": f"$s='{root}/{OTHER}/x.ps1'\n"})
    code, lines = check(root, plan)
    assert_refused(code, lines, "artifacts/a.ps1", 1, f"/{OTHER}/x.ps1")


def test_f2p_987_unresolved_name_is_ignored(tmp_path: Path) -> None:
    """AC-987.2 negative: a use of an unresolved name gives no refusal."""
    root = receipts_root(tmp_path)
    plan = make_plan(tmp_path, {"task.md": "# task\n\n`bash $nowhere/repin.ps1`\n"})
    assert_ok(*check(root, plan))


def test_f2p_987_unresolved_folder_is_ignored(tmp_path: Path) -> None:
    """AC-987.2 negative: a plan folder part with no value (``s=$?`` merges with ``S``) passes."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "task.md": f"# task\n\n`S={OWN_SLUG}; R={root}/$S; bash $R/ps/run.ps1`\n",
            "artifacts/rows.sh": "#!/bin/sh\nrun() { cmd; local s=$?; return $s; }\n",
        },
    )
    assert_ok(*check(root, plan))


def test_f2p_987_one_foreign_value_of_two_is_refused(tmp_path: Path) -> None:
    """AC-987.2 negative: one own value and one foreign value of a name: the use is refused."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "implementation-plan.md": f"$d='{root}/{OWN_SLUG}'\n",
            "artifacts/b.md": f"$d='{root}/{OTHER}'\n",
            "task.md": "# task\n\n`& $d/run.ps1`\n",
        },
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 3, f"/{OTHER}/run.ps1")
    assert not any(
        f"/{OWN_SLUG}/run.ps1".lower() in ln.lower() for ln in foreign(lines)
    ), lines


def test_f2p_987_foreign_data_use_passes(tmp_path: Path) -> None:
    """AC-987.2 negative: ``Get-Content $proof`` with ``$proof`` a foreign data path passes."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "implementation-plan.md": f"$proof='{root}/{OTHER}/base.txt'\n",
            "task.md": "# task\n\n`Get-Content $proof`\n",
        },
    )
    assert_ok(*check(root, plan))


# ---- AC-987.2, review round 1 (R1-F1): the fragments of one shell word stay together.


@pytest.mark.parametrize(
    "use",
    [
        'python "$R"/run.py',
        'python "${R}"/run.py',
        'python "$R""/run.py"',
        "& ($R + '/run.py')",
        '& "$R" + "/run.py"',
    ],
)
def test_f2p_987_quoted_directory_with_a_suffix_is_refused(
    tmp_path: Path, use: str
) -> None:
    """R1-F1: a quoted foreign directory with an unquoted runner suffix is refused."""
    root = receipts_root(tmp_path)
    plan = make_plan(tmp_path, {"task.md": f"# task\n\n`R={root}/{OTHER}; {use}`\n"})
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 3, f"/{OTHER}/run.py")


@pytest.mark.parametrize(
    "line",
    [
        'R={root}/{own}; python "$R"/run.py',
        'R={root}/{other}; cat "$R"/base.txt',
        "R={root}/{other}; Get-Content ($R + '/base.txt')",
    ],
)
def test_f2p_987_quoted_own_or_data_suffix_passes(tmp_path: Path, line: str) -> None:
    """R1-F1 negative: a quoted own directory or a foreign data suffix passes."""
    root = receipts_root(tmp_path)
    text = line.format(root=root, own=OWN_SLUG, other=OTHER)
    plan = make_plan(tmp_path, {"task.md": f"# task\n\n`{text}`\n"})
    assert_ok(*check(root, plan))


# ---- AC-987.2, review round 1 (R1-F2): a local assignment hides the other values.


def test_f2p_987_script_assignment_hides_a_document_value(tmp_path: Path) -> None:
    """R1-F2: a row reads foreign data and a script runs its own runner: the plan passes."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "task.md": f"# task\n\n`R={root}/{OTHER}`\n\n`cat $R/base.txt`\n",
            "artifacts/run.sh": f"R={root}/{OWN_SLUG}\npython $R/run.py\n",
        },
    )
    assert_ok(*check(root, plan))


def test_f2p_987_row_assignment_hides_another_row(tmp_path: Path) -> None:
    """R1-F2: two rows that each set ``R`` before the use do not mix their values."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "task.md": (
                f"# task\n\n| A | `R={root}/{OTHER}; cat $R/base.txt` |\n"
                f"| B | `R={root}/{OWN_SLUG}; python $R/run.py` |\n"
            )
        },
    )
    assert_ok(*check(root, plan))


def test_f2p_987_script_assignment_of_a_foreign_runner_is_refused(
    tmp_path: Path,
) -> None:
    """R1-F2 negative: a script's own foreign value is refused in that script."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "task.md": f"# task\n\n`R={root}/{OWN_SLUG}`\n",
            "artifacts/run.sh": f"R={root}/{OTHER}\npython $R/run.py\n",
        },
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "artifacts/run.sh", 2, f"/{OTHER}/run.py")
    assert len(foreign(lines)) == 1, lines


def test_f2p_987_script_use_of_a_document_value_is_refused(tmp_path: Path) -> None:
    """R1-F2 negative: a script name with no local value still takes the plan value."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "implementation-plan.md": f"$s2c='{root}/{OTHER}'\n",
            "artifacts/run.sh": "#!/bin/sh\nbash $s2c/repin.sh\n",
        },
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "artifacts/run.sh", 2, f"/{OTHER}/repin.sh")


def test_f2p_987_row_use_before_a_later_row_value_is_refused(tmp_path: Path) -> None:
    """R1-F2 negative: a row with no local value of ``R`` takes each plan value of ``R``."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "task.md": (
                f"# task\n\n| A | `R={root}/{OTHER}; cat $R/base.txt` |\n"
                "| B | `python $R/run.py` |\n"
            )
        },
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 4, f"/{OTHER}/run.py")


# ---- AC-987.2, review round 2 (R2-F1): a PowerShell row assignment binds the row.


def test_f2p_987_powershell_row_assignment_hides_another_row(tmp_path: Path) -> None:
    """R2-F1: two PowerShell rows that each set ``$R`` first do not mix their values."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "task.md": (
                f'# task\n\n| A | `$R="{root}/{OTHER}"; Get-Content "$R/base.txt"` |\n'
                f'| B | `$R="{root}/{OWN_SLUG}"; & "$R/x.ps1"` |\n'
            )
        },
    )
    assert_ok(*check(root, plan))


def test_f2p_987_powershell_assignment_of_a_foreign_runner_is_refused(
    tmp_path: Path,
) -> None:
    """R2-F1 negative: a PowerShell row that sets a foreign ``$R`` is refused there."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "task.md": (
                f"# task\n\n| A | `$R='{root}/{OWN_SLUG}'; & \"$R/x.ps1\"` |\n"
                f"| B | `$R='{root}/{OTHER}'; & \"$R/x.ps1\"` |\n"
            )
        },
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 4, f"/{OTHER}/x.ps1")
    assert len(foreign(lines)) == 1, lines


def test_f2p_987_powershell_use_before_the_assignment_is_refused(
    tmp_path: Path,
) -> None:
    """R2-F1 negative: a use of ``$R`` before the row sets ``$R`` takes the plan value."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "implementation-plan.md": f"$R='{root}/{OTHER}'\n",
            "task.md": f'# task\n\n`& "$R/x.ps1"; $R="{root}/{OWN_SLUG}"`\n',
        },
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 3, f"/{OTHER}/x.ps1")


@pytest.mark.parametrize(
    "assign",
    ['$R="$R/sub"', "R=$R/sub"],
)
def test_f2p_987_self_reference_keeps_the_plan_value(
    tmp_path: Path, assign: str
) -> None:
    """R2-F1 negative: a value that reads its own name reads the plan value of it."""
    root = receipts_root(tmp_path)
    plan = make_plan(
        tmp_path,
        {
            "implementation-plan.md": f"$R='{root}/{OTHER}'\n",
            "task.md": f'# task\n\n`{assign}; & "$R/x.ps1"`\n',
        },
    )
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 3, f"/{OTHER}/x.ps1")


# ---- AC-987.2, review round 2 (R2-F2): Join-Path joins its two known parts.


@pytest.mark.parametrize(
    "use",
    [
        '& (Join-Path $R "x.ps1")',
        "& (Join-Path $R 'x.ps1')",
        "& (Join-Path $R x.ps1)",
        '& (Join-Path "$R" "x.ps1")',
        '& (Join-Path $R "/x.ps1")',
        '& (Join-Path -Path $R -ChildPath "x.ps1")',
        "& (join-path -childpath x.ps1 -path $R)",
    ],
)
def test_f2p_987_join_path_of_a_foreign_runner_is_refused(
    tmp_path: Path, use: str
) -> None:
    """R2-F2: ``Join-Path`` of a foreign directory and a runner name is refused."""
    root = receipts_root(tmp_path)
    plan = make_plan(tmp_path, {"task.md": f'# task\n\n`$R="{root}/{OTHER}"; {use}`\n'})
    code, lines = check(root, plan)
    assert_refused(code, lines, "task.md", 3, f"/{OTHER}/x.ps1")


@pytest.mark.parametrize(
    "line",
    [
        '$R="{root}/{own}"; & (Join-Path $R "x.ps1")',
        '$R="{root}/{other}"; Get-Content (Join-Path $R "base.txt")',
        '$R="{root}/{other}"; Get-Content (Join-Path -Path $R -ChildPath base.txt)',
    ],
)
def test_f2p_987_join_path_own_or_data_passes(tmp_path: Path, line: str) -> None:
    """R2-F2 negative: ``Join-Path`` of an own runner or of foreign data passes."""
    root = receipts_root(tmp_path)
    text = line.format(root=root, own=OWN_SLUG, other=OTHER)
    plan = make_plan(tmp_path, {"task.md": f"# task\n\n`{text}`\n"})
    assert_ok(*check(root, plan))


# ---- AC-987.3: data paths, RECEIPTS/, backslashes and case.


def test_f2p_987_data_and_own_paths_pass(tmp_path: Path) -> None:
    """AC-987.3: ``RECEIPTS/``, own and foreign data paths pass."""
    root = receipts_root(tmp_path)
    text = "\n".join(
        [
            "# task",
            "`RECEIPTS/run.ps1` and `RECEIPTS/repin/run.py`",
            f"`{root}/{OWN_SLUG}/ps/split-run.ps1`",
            *(
                f"`{root}/{OTHER}/proof{ext}`"
                for ext in (".txt", ".md", ".json", ".xml")
            ),
            "",
        ]
    )
    plan = make_plan(
        tmp_path, {"task.md": text, "artifacts/x.py": f"P = '{root}/{OTHER}/a.xml'\n"}
    )
    assert_ok(*check(root, plan))


def test_f2p_987_backslash_and_case_resolve(tmp_path: Path) -> None:
    """AC-987.3: a backslash path and a root in another case resolve the same way."""
    root = receipts_root(tmp_path)
    upper = root.upper().replace("/", "\\")
    plan = make_plan(
        tmp_path,
        {
            "task.md": f"# task\n\n`{upper}\\{OTHER.upper()}\\RUN.PS1`\n",
            "artifacts/own.md": f"{upper}\\{OWN_SLUG.upper()}\\RUN.PS1\n",
        },
    )
    code, lines = check(root.lower(), plan)
    assert_refused(code, lines, "task.md", 3, f"/{OTHER}/run.ps1")
    assert len(foreign(lines)) == 1, lines


# ---- AC-987.4: bad invocations.


def test_f2p_987_missing_plan_dir_is_bad(tmp_path: Path) -> None:
    """AC-987.4: no ``--plan-dir`` exits 2 with ``runner_paths_bad``."""
    code, lines = run_tool("--receipts-root", receipts_root(tmp_path))
    assert code == 2, lines
    assert any(ln.startswith("runner_paths_bad:") for ln in lines), lines
    assert not any(ln.startswith("runner_paths_ok") for ln in lines), lines


def test_f2p_987_plan_dir_without_task_is_bad(tmp_path: Path) -> None:
    """AC-987.4: a plan folder without ``task.md`` exits 2 with ``runner_paths_bad``."""
    plan = tmp_path / OWN_SLUG
    plan.mkdir()
    (plan / "implementation-plan.md").write_text("# plan\n", encoding="utf-8")
    code, lines = check(receipts_root(tmp_path), plan)
    assert code == 2, lines
    assert any(ln.startswith("runner_paths_bad:") for ln in lines), lines
    assert not any(ln.startswith("runner_paths_ok") for ln in lines), lines


def test_f2p_987_missing_receipts_root_is_bad(tmp_path: Path) -> None:
    """AC-987.4: no ``--receipts-root`` exits 2 with ``runner_paths_bad``."""
    plan = make_plan(tmp_path, {})
    code, lines = run_tool("--plan-dir", str(plan))
    assert code == 2, lines
    assert any(ln.startswith("runner_paths_bad:") for ln in lines), lines
    assert not any(ln.startswith("runner_paths_ok") for ln in lines), lines


def test_f2p_987_unknown_argument_is_bad(tmp_path: Path) -> None:
    """AC-987.4: an unknown argument exits 2 with ``runner_paths_bad``."""
    plan = make_plan(tmp_path, {})
    code, lines = run_tool(
        "--receipts-root", receipts_root(tmp_path), "--plan-dir", str(plan), "--bogus"
    )
    assert code == 2, lines
    assert any(ln.startswith("runner_paths_bad:") for ln in lines), lines


# ---- AC-987.6: the create-plan bullet.


def cp_problems(text: str) -> list[str]:
    """Return the problems of the runner-path bullet in a ``create-plan.md`` text."""
    lines = text.split("\n")
    bullet = CP_BULLET.format(root=RECEIPTS_ROOT)
    owners = [i for i, ln in enumerate(lines) if ln.startswith(OWNERSHIP_PREFIX)]
    hits = [i for i, ln in enumerate(lines) if ln == bullet]
    problems: list[str] = []
    if len(owners) != 1:
        problems.append(f"ownership_bullets={len(owners)}")
    if len(hits) != 1:
        problems.append(f"runner_bullets={len(hits)}")
    if not problems and hits[0] != owners[0] + 1:
        problems.append(f"runner_bullet_at={hits[0]} ownership_at={owners[0]}")
    return problems


def test_f2p_987_create_plan_holds_the_bullet() -> None:
    """AC-987.6: the bullet is directly after the ownership bullet."""
    text = CREATE_PLAN.read_text(encoding="utf-8")
    assert cp_problems(text) == []
    assert "runner_paths_ok" in CP_BULLET
    assert "tools/plan_runner_paths.py --receipts-root" in CP_BULLET


def test_f2p_987_create_plan_mutations_fail() -> None:
    """AC-987.6 negative: a copy without the bullet, or with it before the ownership bullet, fails."""
    text = CREATE_PLAN.read_text(encoding="utf-8")
    bullet = CP_BULLET.format(root=RECEIPTS_ROOT)
    assert cp_problems(text) == []
    lines = text.split("\n")
    without = "\n".join(ln for ln in lines if ln != bullet)
    assert cp_problems(without)
    owner = next(i for i, ln in enumerate(lines) if ln.startswith(OWNERSHIP_PREFIX))
    moved = [ln for ln in lines if ln != bullet]
    moved.insert(owner, bullet)
    assert cp_problems("\n".join(moved))


# ---- AC-987.7: NEUTRAL.


def test_f2p_987_tool_is_neutral() -> None:
    """AC-987.7: the tool text has no project name, user name, mail address or drive path."""
    _require_tool()
    text = TOOL.read_text(encoding="utf-8")
    assert NEUTRAL_RE.findall(text) == []


def test_f2p_987_neutral_mutation_fails() -> None:
    """AC-987.7 negative: a copy with a drive-path default fails the census."""
    _require_tool()
    text = TOOL.read_text(encoding="utf-8")
    mutated = text + "\nDEFAULT_ROOT = '" + "C" + ":/Temp'\n"
    assert NEUTRAL_RE.findall(mutated)
