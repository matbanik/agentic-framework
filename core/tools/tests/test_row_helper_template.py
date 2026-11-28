"""MEU-988 template rows, framework port: the ``B`` row and the row-helper blockquote.

Plan 2026-11-26-row-helper-module (AC-988.1, .2 and .7). Each doc test reads the real
``templates/TASK-TEMPLATE.md`` and a mutated copy that it writes in ``tmp_path``. The
package copy has no ``RP`` row and no ``FW`` row: those rows name tools that the package
does not ship, so their cases stay in the project (D-9). One test fixes that form.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.validate_closeout_artifacts import TASK_ROW_RE

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "TASK-TEMPLATE.md"

#: The column index of the Depends-on cell (``#`` is column 0).
DEPENDS = 5

ROW_HELPERS_HEAD = "> **Row helpers (`tools/RowHelpers.psm1`).**"
DELEGATE_HEAD = "> **Optional `delegate_to` annotation.**"

B_PHRASES = (
    "Invoke-GuardSplit",
    "Add-BaseFail",
    "-WorkersEnv {{PROJECT_NAME_UPPER}}_PYTEST_WORKERS",
    "-Receipts {temp root outside the receipts folder}",
    "[x] n/a",
)
BLOCK_PHRASES = (
    "Import-Module ./tools/RowHelpers.psm1 -Force",
    "Assert-Run",
    "Assert-NoNewRed",
    "Invoke-GuardSplit",
    "Add-BaseFail",
    "Invoke-PolicyRepin",
    "Do not copy these functions into a plan.",
    "`tools/plan_runner_paths.py` refuses that path before Step 5 of `create-plan.md`.",
    "It finds no runner of another plan",
    "no completed baseline that the change would read in a new way",
    "It finds no dependency cycle.",
    "only that step runs again, after a proof that its inputs have the same bytes",
    "A parked plan adopts the module at its preflight, through an Execution amendment.",
)


# ---- Helpers.


def read(path: Path) -> str:
    """Return the text of ``path`` with LF line ends."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def template() -> str:
    """Return the real template text."""
    return read(TEMPLATE)


def cells(line: str) -> list[str]:
    """Return the cells of a table line; an escaped ``\\|`` stays inside its cell."""
    parts = re.split(r"(?<!\\)\|", line.strip())
    return [p.strip() for p in parts[1:-1]]


def row_index(lines: list[str], row_id: str) -> int:
    """Return the index of the table row whose first cell is ``row_id``, or -1."""
    hits = [i for i, ln in enumerate(lines) if ln.startswith(f"| {row_id} |")]
    return hits[0] if len(hits) == 1 else -1


def row_cells(lines: list[str], row_id: str) -> list[str]:
    """Return the cells of row ``row_id``, or an empty list when it is not one row."""
    index = row_index(lines, row_id)
    return cells(lines[index]) if index >= 0 else []


def depends_on(lines: list[str], row_id: str) -> str:
    """Return the Depends-on cell of row ``row_id``, or an empty text."""
    found = row_cells(lines, row_id)
    return found[DEPENDS] if len(found) > DEPENDS else ""


def mutate(tmp_path: Path, text: str, old: str, new: str, count: int = 1) -> str:
    """Write ``text`` with ``old`` replaced to a copy in ``tmp_path``; return the copy text."""
    assert text.count(old) >= 1, f"mutation anchor absent: {old[:60]!r}"
    copy = tmp_path / "TASK-TEMPLATE.md"
    copy.write_text(text.replace(old, new, count), encoding="utf-8", newline="\n")
    return read(copy)


def drop_line(tmp_path: Path, text: str, prefix: str) -> str:
    """Write ``text`` without the one line that starts with ``prefix``; return the copy."""
    lines = text.split("\n")
    kept = [ln for ln in lines if not ln.startswith(prefix)]
    assert len(kept) == len(lines) - 1, f"not one line: {prefix!r}"
    copy = tmp_path / "TASK-TEMPLATE.md"
    copy.write_text("\n".join(kept), encoding="utf-8", newline="\n")
    return read(copy)


def missing(text: str, phrases: tuple[str, ...], where: str) -> list[str]:
    """Return one problem for each phrase that ``text`` does not hold."""
    return [f"{where}: no {p!r}" for p in phrases if p not in text]


# ---- The checks of AC-988.1 and .2.


def b_problems(text: str) -> list[str]:
    """AC-988.1: the ``B`` row directly after ``CL``; row 1 depends on ``B``."""
    lines = text.split("\n")
    cl, b = row_index(lines, "CL"), row_index(lines, "B")
    if cl < 0 or b < 0:
        return ["no CL row or no B row"]
    problems = [] if b == cl + 1 else ["B is not directly after CL"]
    problems += missing(lines[b], B_PHRASES, "B")
    if depends_on(lines, "B") != "CL":
        problems.append("B does not depend on CL")
    if depends_on(lines, "1") != "B":
        problems.append("row 1 does not depend on B")
    return problems


def block_problems(text: str) -> list[str]:
    """AC-988.2: the row-helper blockquote directly before the ``delegate_to`` blockquote."""
    lines = text.split("\n")
    heads = [i for i, ln in enumerate(lines) if ln.startswith(ROW_HELPERS_HEAD)]
    delegate = [i for i, ln in enumerate(lines) if ln.startswith(DELEGATE_HEAD)]
    if len(heads) != 1 or len(delegate) != 1:
        return ["not one row-helper blockquote and one delegate_to blockquote"]
    end = heads[0]
    while end < len(lines) and lines[end].startswith(">"):
        end += 1
    block = "\n".join(lines[heads[0] : end])
    problems = missing(block, BLOCK_PHRASES, "blockquote")
    rest = lines[end : delegate[0]]
    if delegate[0] < heads[0] or any(ln.strip() for ln in rest):
        problems.append(
            "the blockquote is not directly before the delegate_to blockquote"
        )
    return problems


def package_form_problems(text: str) -> list[str]:
    """The package form: no ``RP`` row, no ``FW`` row, and H1-5 depends on H1-4."""
    lines = text.split("\n")
    problems = [f"{r} row present" for r in ("RP", "FW") if row_index(lines, r) >= 0]
    if depends_on(lines, "H1-5") != "H1-4":
        problems.append("H1-5 does not depend on H1-4")
    return problems


# ---- AC-988.1: the B row.


def test_f2p_988_b_row() -> None:
    """AC-988.1: the real template has the ``B`` row and row 1 depends on it."""
    assert b_problems(template()) == []


def test_f2p_988_b_row_mutations_fail(tmp_path: Path) -> None:
    """AC-988.1 negative: row 1 on ``CL``, a ``B`` row without ``Add-BaseFail`` or a temp root in the receipts folder fails."""
    text = template()
    assert b_problems(text) == []
    lines = text.split("\n")
    row1 = lines[row_index(lines, "1")]
    assert b_problems(mutate(tmp_path, text, row1, row1.replace("| B |", "| CL |")))
    b_row = lines[row_index(lines, "B")]
    no_add = b_row.replace("Add-BaseFail", "Add-Base")
    assert b_problems(mutate(tmp_path, text, b_row, no_add))
    in_receipts = b_row.replace(
        "-Receipts {temp root outside the receipts folder}",
        "-Receipts {{RECEIPTS_DIR}}/{slug}",
    )
    assert b_problems(mutate(tmp_path, text, b_row, in_receipts))


# ---- AC-988.2: the blockquote.


def test_f2p_988_row_helper_blockquote() -> None:
    """AC-988.2: the blockquote names the module, its five functions and the preflight."""
    assert block_problems(template()) == []


def test_f2p_988_blockquote_mutations_fail(tmp_path: Path) -> None:
    """AC-988.2 negative: a copy without "Do not copy" or without the parked-plan line fails."""
    text = template()
    assert block_problems(text) == []
    no_copy = mutate(
        tmp_path, text, "Do not copy these functions", "Copy these functions"
    )
    assert block_problems(no_copy)
    parked = "> A parked plan adopts the module at its preflight, through an Execution amendment."
    assert block_problems(drop_line(tmp_path, text, parked))


# ---- The package form (the framework side of AC-988.6).


def test_f2p_988_package_has_no_rp_or_fw_row() -> None:
    """The package template has no ``RP`` row and no ``FW`` row; H1-5 depends on H1-4."""
    assert package_form_problems(template()) == []
    assert b_problems(template()) == []


def test_f2p_988_package_form_mutation_fails(tmp_path: Path) -> None:
    """Negative: a copy with an ``FW`` row that H1-5 depends on fails the package form."""
    text = template()
    lines = text.split("\n")
    h15 = lines[row_index(lines, "H1-5")]
    fw = "| FW | framework port | orchestrator | x | `x` | H1-4 | shared | x | `coordinator` | `[ ]` |"
    on_fw = h15.replace("| H1-4 | compact_continue |", "| FW | compact_continue |")
    copy = mutate(tmp_path, text, h15, fw + "\n" + on_fw)
    found = package_form_problems(copy)
    assert "FW row present" in found
    assert "H1-5 does not depend on H1-4" in found


# ---- AC-988.7: the closeout row grammar.


def test_f2p_988_b_row_read_by_task_row_re() -> None:
    """AC-988.7: ``TASK_ROW_RE`` reads the ``B`` row with status ``[ ]``."""
    lines = template().split("\n")
    index = row_index(lines, "B")
    assert index >= 0
    match = TASK_ROW_RE.match(lines[index])
    assert match is not None
    assert match.group("id") == "B"
    assert match.group("status") == "[ ]"


def test_f2p_988_b_row_without_status_is_not_a_row(tmp_path: Path) -> None:
    """AC-988.7 negative: a copy whose ``B`` row lacks the status cell is not read as a row."""
    text = template()
    lines = text.split("\n")
    b_row = lines[row_index(lines, "B")] if row_index(lines, "B") >= 0 else ""
    assert TASK_ROW_RE.match(b_row) is not None
    cut = b_row[: b_row.rindex("| `[ ]` |")] + "|"
    copy = mutate(tmp_path, text, b_row, cut).split("\n")
    assert TASK_ROW_RE.match(copy[row_index(copy, "B")]) is None
