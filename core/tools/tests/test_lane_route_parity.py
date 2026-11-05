"""MEU-831: the framework's parity with the source project's closeout and activation checks.

AC-831.1 to AC-831.5 of the MAL stage 2c plan. A lane plan writes its metrics row as a
``metrics-row`` integration request, so before the land ``docs/execution/metrics.md`` has no
such row (G1). An adopter that copied ``.agent/lane-route.json`` must pin it with the file, or
an edit of the route goes unseen (G2). A plan with several MEUs repeats ``--meu`` and lists the
MEUs in the ``**MEU:**`` field of the focus file.

Every module is imported inside a test body, so a missing name fails the test rather than the
collection.
"""

from __future__ import annotations

import importlib
import json
import re
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates/TASK-TEMPLATE.md"
CHECKLIST = ROOT.parent / "UPDATE-CHECKLIST.md"
POLICY_TEMPLATE = ROOT / ".agent/run-parameters.policy.json.template"
ROUTE_TEMPLATE = ROOT / ".agent/lane-route.json.template"
LANE_ROUTE = ".agent/lane-route.json"

DATE = "2026-11-03"
MEU = "MEU-830"
OTHER_MEU = "MEU-831"
FOCUS_ONE = f"## Status\n**Outcome:** approved\n**MEU:** {MEU}\n"
FOCUS_TWO = f"## Status\n**Outcome:** approved\n**MEU:** {MEU}, {OTHER_MEU}\n"
KNOWN = "## Active Issues\nOther issue.\n## Mitigated / Workaround\nNone.\n"


def _vca() -> ModuleType:
    return importlib.import_module("tools.validate_closeout_artifacts")


def _row(meu: str = MEU, *, tests_added: str = "10") -> str:
    return f"| {DATE} | {meu} | 20 | 5 min | {tests_added} | none | 7/7 | 100% | 60 | Complete |"


def _metrics(tmp_path: Path, rows: Sequence[str] = ()) -> Path:
    headers = _vca().METRICS_HEADERS
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers), *rows]
    path = tmp_path / "metrics.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _handoff(tmp_path: Path, *rows: str) -> Path:
    """A handoff whose ``## Integration requests`` table has one ``metrics-row`` per row."""
    body = [
        "## Integration requests",
        "",
        "| Id | Request |",
        "|---|---|",
        *(
            f"| `metrics-{index}` | `metrics-row {row.replace('|', chr(92) + '|')}` |"
            for index, row in enumerate(rows)
        ),
    ]
    path = tmp_path / "handoff.md"
    path.write_text("\n".join(["# Handoff", "", *body, "", "## Next", ""]), encoding="utf-8")
    return path


def _run(
    tmp_path: Path,
    *,
    focus: str = FOCUS_ONE,
    meu: Any = MEU,
    rows: Sequence[str] = (MEU,),
) -> Any:
    """A final-stage ``_StageRun`` over a metrics table and three context files."""
    vca = _vca()
    known = tmp_path / "known-issues.md"
    known.write_text(KNOWN, encoding="utf-8")
    ssot = tmp_path / "known-issues.yaml"
    ssot.write_text("issues: []\n", encoding="utf-8")
    focus_path = tmp_path / "current-focus.md"
    focus_path.write_text(focus, encoding="utf-8")
    args = Namespace(
        metrics=_metrics(tmp_path, [_row(item) for item in rows]),
        date=DATE,
        meu=meu,
        issue=None,
        known_issues=known,
        known_issues_yaml=ssot,
        current_focus=focus_path,
    )
    return vca._StageRun(
        args=args,
        stage="final",
        for_produce=False,
        handoffs=[],
        legacy=True,
        commit_exec=False,
    )


def _template_row(row: str) -> str:
    rows = [
        line
        for line in TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"| {row} |")
    ]
    assert len(rows) == 1, rows
    return rows[0]


# --- AC-831.1: the metrics check reads the lane plan's request ---------------------


def test_request_row_passes_with_no_row_in_metrics(tmp_path: Path) -> None:
    """AC-831.1: a good request passes, and ``metrics.md`` has no such row (the land adds it)."""
    _vca()._validate_metrics_row(
        _metrics(tmp_path), date_value=DATE, meu=MEU, handoff=_handoff(tmp_path, _row())
    )


def test_request_with_a_pending_cell_fails(tmp_path: Path) -> None:
    """AC-831.1: a pending cell in the request fails, even with a good row in ``metrics.md``."""
    vca = _vca()
    with pytest.raises(vca.Refuse, match="metrics row must be fully populated"):
        vca._validate_metrics_row(
            _metrics(tmp_path, [_row()]),
            date_value=DATE,
            meu=MEU,
            handoff=_handoff(tmp_path, _row(tests_added="pending")),
        )


def test_request_for_another_meu_fails(tmp_path: Path) -> None:
    """AC-831.1: the request must name this MEU; ``metrics.md`` does not stand in for it."""
    vca = _vca()
    with pytest.raises(vca.Refuse, match="one exact date/MEU row"):
        vca._validate_metrics_row(
            _metrics(tmp_path, [_row()]),
            date_value=DATE,
            meu=MEU,
            handoff=_handoff(tmp_path, _row(OTHER_MEU)),
        )


def test_handoff_with_no_request_falls_back_to_metrics(tmp_path: Path) -> None:
    """AC-831.1: with no ``metrics-row`` request, ``metrics.md`` decides, in both directions."""
    vca = _vca()
    handoff = _handoff(tmp_path)
    vca._validate_metrics_row(
        _metrics(tmp_path, [_row()]), date_value=DATE, meu=MEU, handoff=handoff
    )
    with pytest.raises(vca.Refuse, match="one exact date/MEU row"):
        vca._validate_metrics_row(
            _metrics(tmp_path, [_row(OTHER_MEU)]),
            date_value=DATE,
            meu=MEU,
            handoff=handoff,
        )


def test_no_handoff_keeps_the_old_call(tmp_path: Path) -> None:
    """AC-831.1: the call without ``handoff`` still reads ``metrics.md``."""
    _vca()._validate_metrics_row(_metrics(tmp_path, [_row()]), date_value=DATE, meu=MEU)


# --- AC-831.2: the H2-3 cell passes the handoff ------------------------------------


def _h2_3_code(handoff: Path) -> str:
    """The ``python -c`` body of the H2-3 cell, with its placeholders filled."""
    found = re.search(r'python -c "(?P<code>.+?)" \*>', _template_row("H2-3"))
    assert found is not None, "the H2-3 cell runs no python -c"
    return (
        found.group("code")
        .replace("{YYYY-MM-DD}", DATE)
        .replace("{MEU-ID}", MEU)
        .replace("{handoff-file}", handoff.as_posix())
    )


def test_h2_3_cell_passes_the_handoff() -> None:
    """AC-831.2: the H2-3 cell passes ``handoff=Path('{handoff-file}')``."""
    assert "handoff=Path('{handoff-file}')" in _template_row("H2-3")


@pytest.mark.parametrize(
    ("tests_added", "expected_ok"), [("10", True), ("pending", False)]
)
def test_h2_3_cell_runs_and_can_fail(
    tmp_path: Path, tests_added: str, expected_ok: bool
) -> None:
    """AC-831.2: the cell's own command runs from the tools' parent, and a pending cell fails it."""
    handoff = _handoff(tmp_path, _row(tests_added=tests_added))
    done = subprocess.run(
        [sys.executable, "-c", _h2_3_code(handoff)],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert (done.returncode == 0) is expected_ok, done.stdout + done.stderr
    if not expected_ok:
        assert "metrics row must be fully populated" in done.stderr


# --- AC-831.3: the conditional lane-route pin --------------------------------------


def _status(fx: bf.Fixture) -> dict[str, Any]:
    code, out = fx.run("status", "--json")
    assert code == 0, out
    return out


def _copy_route(fx: bf.Fixture) -> Path:
    target = fx.repo / LANE_ROUTE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROUTE_TEMPLATE, target)
    return target


@pytest.mark.integration
def test_adopter_that_copied_nothing_stays_enabled(tmp_path: Path) -> None:
    """AC-831.3: a repository with no lane route activates as before."""
    fx = bf.build(tmp_path / "fx", ROOT)
    assert not (fx.repo / LANE_ROUTE).exists()
    assert _status(fx).get("enabled") is True


@pytest.mark.integration
def test_adopter_that_copied_the_file_without_the_pin_is_disabled(tmp_path: Path) -> None:
    """AC-831.3: the file on disk and not in ``components`` is ``component_missing``."""
    fx = bf.build(tmp_path / "fx", ROOT)
    _copy_route(fx)
    out = _status(fx)
    assert out.get("enabled") is False, out
    assert out.get("reason") == f"component_missing:{LANE_ROUTE}", out


@pytest.mark.integration
def test_adopter_that_pinned_the_file_is_enabled(tmp_path: Path) -> None:
    """AC-831.3: the file on disk and in ``components`` activates."""
    fx = bf.build(tmp_path / "fx", ROOT)
    _copy_route(fx)
    fx.components.append(LANE_ROUTE)
    fx.seal_activation()
    assert _status(fx).get("enabled") is True


@pytest.mark.integration
def test_pinned_file_edited_is_drift(tmp_path: Path) -> None:
    """AC-831.3: an edit of the pinned file is ``component_drift``."""
    fx = bf.build(tmp_path / "fx", ROOT)
    target = _copy_route(fx)
    fx.components.append(LANE_ROUTE)
    fx.seal_activation()
    target.write_bytes(target.read_bytes() + b"\n")
    out = _status(fx)
    assert out.get("enabled") is False, out
    assert out.get("reason") == f"component_drift:{LANE_ROUTE}", out


def test_the_package_ships_no_pin() -> None:
    """AC-831.3: the policy template and the required set stay without the opt-in file."""
    rp = importlib.import_module("tools.run_parameters")
    assert rp.LANE_ROUTE == LANE_ROUTE
    assert LANE_ROUTE not in rp.REQUIRED_COMPONENTS
    policy = json.loads(POLICY_TEMPLATE.read_text(encoding="utf-8"))
    assert LANE_ROUTE not in policy["components"]


# --- AC-831.4: the MEU tokens and the repeated flag --------------------------------


@pytest.mark.parametrize(
    "line",
    [
        f"**MEU:** {MEU}, {OTHER_MEU}",
        f"**MEU:** `{MEU}`, `{OTHER_MEU}`",
        f"**MEU:** {MEU},{OTHER_MEU}",
    ],
)
@pytest.mark.parametrize("meu", [MEU, OTHER_MEU])
def test_focus_lists_two_meus(tmp_path: Path, line: str, meu: str) -> None:
    """AC-831.4: a list in the ``**MEU:**`` field passes for each MEU that it names."""
    focus = f"## Status\n**Outcome:** approved\n{line}\n"
    run = _run(tmp_path, focus=focus, meu=meu, rows=(meu,))
    assert _vca()._stage_metrics_context(run) is None


@pytest.mark.parametrize(
    "line",
    [
        f"**MEU:** {MEU}0",
        f"**MEU:** see {MEU}",
        f"**MEU:** {OTHER_MEU}",
        f"not the field {MEU}",
    ],
)
def test_focus_meu_is_an_exact_token(tmp_path: Path, line: str) -> None:
    """AC-831.4: a longer id, or an id inside other words, does not match."""
    vca = _vca()
    run = _run(tmp_path, focus=f"## Status\n**Outcome:** approved\n{line}\n")
    with pytest.raises(vca.Refuse) as caught:
        vca._stage_metrics_context(run)
    assert str(caught.value) == "current_focus missing exact MEU field"


def test_focus_must_name_every_meu(tmp_path: Path) -> None:
    """AC-831.4: with two MEUs, a focus that names only the first fails."""
    vca = _vca()
    meus = [MEU, OTHER_MEU]
    run = _run(tmp_path, meu=meus, rows=meus)
    with pytest.raises(vca.Refuse, match="current_focus missing exact MEU"):
        vca._stage_metrics_context(run)


def test_cli_meu_repeats(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-831.4: the parser collects every ``--meu``, and no ``--issue`` is required."""
    vca = _vca()
    seen: list[Any] = []

    def capture(args: Any, stage: str, *, for_produce: bool) -> dict[str, Any]:
        seen.append((args.meu, args.issue, stage, for_produce))
        return {"status": "PASS"}

    monkeypatch.setattr(vca, "validate_stage", capture)
    code = vca.main(["--stage", "structural", "--meu", MEU, "--meu", OTHER_MEU])
    capsys.readouterr()
    assert code == 0
    assert seen == [([MEU, OTHER_MEU], None, "structural", False)]


def test_two_meus_pass_with_both_rows(tmp_path: Path) -> None:
    """AC-831.4: two MEUs with both metrics rows and both focus tokens pass."""
    meus = [MEU, OTHER_MEU]
    run = _run(tmp_path, focus=FOCUS_TWO, meu=meus, rows=meus)
    assert _vca()._stage_metrics_context(run) is None


def test_second_meu_row_is_required(tmp_path: Path) -> None:
    """AC-831.4: a missing metrics row for the second MEU fails."""
    vca = _vca()
    run = _run(tmp_path, focus=FOCUS_TWO, meu=[MEU, OTHER_MEU], rows=(MEU,))
    with pytest.raises(vca.Refuse) as caught:
        vca._stage_metrics_context(run)
    assert str(caught.value) == "metrics must contain one exact date/MEU row"


@pytest.mark.parametrize("meu", [None, []])
def test_no_meu_keeps_the_exact_message(tmp_path: Path, meu: Any) -> None:
    """AC-831.4: no ``--meu`` keeps the message of a missing row."""
    vca = _vca()
    with pytest.raises(vca.Refuse) as caught:
        vca._stage_metrics_context(_run(tmp_path, meu=meu))
    assert str(caught.value) == "metrics must contain one exact date/MEU row"


def test_str_in_a_namespace_still_works(tmp_path: Path) -> None:
    """AC-831.4: a ``str`` in a ``Namespace`` still works."""
    assert _vca()._stage_metrics_context(_run(tmp_path, meu=MEU)) is None


# --- AC-831.5: the checklist and the H2-4 sentence ---------------------------------


def _checklist() -> str:
    """The package's checklist, which an adopter's copy of this test does not have."""
    if not CHECKLIST.is_file():
        pytest.skip("UPDATE-CHECKLIST.md is a package file; an adopter has no copy")
    return CHECKLIST.read_text(encoding="utf-8")


def test_h2_4_cell_says_how_to_call_the_validator() -> None:
    """AC-831.5: the H2-4 task cell holds the three parts of the sentence."""
    cell = _template_row("H2-4").split(" | ")[1]
    assert "resolves no known issue" in cell
    assert "passes no `--issue`" in cell
    assert "passes `--meu` once per MEU" in cell
    assert "no plan-local `stage_check.py` is needed" in cell


def test_checklist_has_the_port_rows() -> None:
    """AC-831.5: G1, G2 and the validator port each have a row that names its change."""
    text = _checklist()
    validator = [
        line
        for line in text.splitlines()
        if line.startswith("| `tools/validate_closeout_artifacts.py` |")
        and "metrics-row" in line
    ]
    assert len(validator) == 1, validator
    assert "--meu" in validator[0]
    pin = [
        line
        for line in text.splitlines()
        if line.startswith("| `tools/run_parameters.py` |")
        and f"component_missing:{LANE_ROUTE}" in line
    ]
    assert len(pin) == 1, pin


def test_checklist_refreshed_line_changed() -> None:
    """AC-831.5: the stage 2b note moved to ``Previous`` and a new note leads the line."""
    lines = [line for line in _checklist().splitlines() if line.startswith("Last refreshed:")]
    assert len(lines) == 1, lines
    assert "Previous: **2026-11-03** (parallel lanes stage 2b" in lines[0]
    assert not lines[0].startswith("Last refreshed: **2026-11-03** (parallel lanes stage 2b")


def test_opt_in_step_says_pin_it_with_the_file() -> None:
    """AC-831.5: the opt-in paragraph tells the adopter to pin the file it copied."""
    section = _checklist().split("### Parallel lanes (stage 2b: the lane route)", 1)[1]
    paragraph = section.split("| Source |", 1)[0]
    assert "pin it with the file" in " ".join(paragraph.split())
