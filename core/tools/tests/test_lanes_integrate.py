"""Red tests for MEU-785 AC-785.15: ``land prepare`` integrates a lane's requests at P.

Step 3 of ``land prepare`` (``integrate``) reads the ``## Integration requests``
table of the lane handoff and applies each request to the junction files at the
pinned main P, in the candidate, so that the integrated tree T carries them. The
grammar (IP "Integration request grammar") has five forms:

* ``meu-status <MEU-ID> -> <status> [reason=<text>]``
* ``grouping-cursor <grouping-file> -> <session-id>``
* ``ki-file <KI-ID> <payload-path>``
* ``ki-close <KI-ID> -> <text>``
* ``metrics-row <row>``

Each row id is ``<lane>/<generation>/<n>`` and each Request cell is one code
span. Errors: ``request_unknown:<id>`` stops the land; ``request_id:``,
``request_field:<id>:<field>`` and ``request_payload:<id>:...`` refuse it;
``request_conflict:<id>`` leaves the request out, lists it and the land
continues. A re-run applies nothing twice. ``.secrets.baseline`` and
``tools/temp_citation_baseline.json`` never change, and ``current-focus.md``
keeps the other lanes and the current priority.

Fixture: a real temporary repository (``phase_b3.rig``: SSH signing and the
run-parameters store) that carries the generic junction-file fixtures of
``lanes_fixtures/`` (rendered by the framework tools) and the
``meu_status`` / ``issue_triage`` tools from this working copy, a lane worktree on
``lane/<slug>`` claimed with the real ``claim`` verb, one lane commit with the
handoff, and one more ``main`` commit so that P is not the lane base. Every rig
is built inside the test body, so a missing ``land`` verb fails at call.

Readings (recorded in the B-R2 evidence): the grouping file is a repository path
under ``.agent/context/grouping/`` (where every grouping file and
``run_parameters._grouping_path`` live); the cursor line is
``Global cursor: **<session>**``; the Request cell is read from its first to
its last backtick, so a metrics row keeps its pipes; the journal run folder is
found by glob; the fixture gate ``tools/validate_codebase.py`` is an exit-0 stub
(AC-785.17 names no gate command), so success reads the journal, not the exit.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import lane_worktree_config as lwc

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "tools" / "lanes.py"
PLANS = "docs/execution/plans"
OP_ID = "op-land-integrate-1"
CLI_TIMEOUT_S = 180
SESSION_ENV = "{{PROJECT_NAME_UPPER}}_SESSION"
# The generic junction-file fixtures, by repository path (flat file names).
FIXTURES = Path(__file__).resolve().parent / "lanes_fixtures"

MEU_STATUS = ".agent/context/meu-status.yaml"
KI_YAML = ".agent/context/known-issues.yaml"
KI_MD = ".agent/context/known-issues.md"
METRICS = "docs/execution/metrics.md"
CURRENT_FOCUS = ".agent/context/current-focus.md"
SECRETS_BASELINE = ".secrets.baseline"
CITATION_BASELINE = "tools/temp_citation_baseline.json"
GROUPING = ".agent/context/grouping/lane-fixture-session-grouping.md"
CANON_FILES = (
    MEU_STATUS,
    KI_YAML,
    KI_MD,
    ".agent/context/meu-registry.md",
    "docs/BUILD_PLAN.md",
    METRICS,
    SECRETS_BASELINE,
    CITATION_BASELINE,
)
# Repository path -> file name in ``lanes_fixtures/``.
CANON: dict[str, str] = {rel: rel.rsplit("/", 1)[-1].lstrip(".") for rel in CANON_FILES}
TOOL_FILES = ("tools/__init__.py", "tools/meu_status.py", "tools/issue_triage.py")
TOOL_PACKAGES = ("tools/meu_status", "tools/issue_triage")
NEW_KI = "LANE-FIXTURE-KI"
STATUSES = ("in_progress", "ready_for_review")

CURRENT_FOCUS_TEXT = (
    "# Current Focus\n\n"
    "## Current Priority\n\n"
    "Fixture priority: this body stays byte-equal.\n\n"
    "## Other lanes\n\n"
    "- 2026-10-20-lane-b: fixture other lane (this line stays).\n"
)
GROUPING_TEXT = (
    "# Lane fixture session grouping\n\n"
    "Global cursor: **LX1** (this file)\n\n"
    "### Session LX1 — first\n\n"
    "Routing: fixture\n\n"
    "### Session LX2 — second\n\n"
    "Routing: fixture\n"
)
GATE_STUB = (
    '"""Fixture gate stub for the land integrate tests (AC-785.17 names no gate command)."""\n'
    "\n"
    "import sys\n"
    "\n"
    "sys.exit(0)\n"
)
P_ROW = "| 2026-10-23 | MEU-P | main moved | - | - | - | - | - | - | fixture main row |"
LANE_ROW = (
    "| 2026-10-23 | MEU-785 | lane fixture | - | - | - | - | - | - | fixture lane row |"
)
KI_PAYLOAD = (
    "title: Lane fixture issue\n"
    "severity: low\n"
    "component: infrastructure\n"
    "status: open\n"
    "discovered: '2026-10-23'\n"
)

Rows = list[tuple[str, str]]
Payloads = dict[str, str]


@dataclass
class Land:
    """A claimed lane in a ``phase_b3`` rig, with the real-data picks of its requests."""

    rig: b3.Rig
    wt: Path
    generation: str
    meu_row: str
    meu_target: str
    open_ki: str
    resolved_ki: str
    existing_ki: str
    l0: str = ""
    p: str = ""

    @property
    def slug(self) -> str:
        return self.rig.plan

    @property
    def repo(self) -> Path:
        return self.rig.repo

    @property
    def handoff(self) -> str:
        return f".agent/context/handoffs/{self.slug}-handoff.md"

    def rid(self, n: int) -> str:
        """The request id ``<lane>/<generation>/<n>``."""
        return f"{self.slug}/{self.generation}/{n}"

    def payload_path(self, ki: str) -> str:
        return f"{PLANS}/{self.slug}/artifacts/ki/{ki}.yaml"

    def kept(self, name: str) -> str:
        """The OID of ``refs/lanes/<slug>/<op>/<name>``; empty when the ref is absent."""
        return self.rig.git(
            "rev-parse",
            "-q",
            "--verify",
            f"refs/lanes/{self.slug}/{OP_ID}/{name}",
            check=False,
        )


def _issues(data: Any) -> list[dict[str, Any]]:
    """The top-level issue list of ``known-issues.yaml`` (nested ``- id:`` entries excluded)."""
    if isinstance(data, dict):
        data = data.get("issues")
    assert isinstance(data, list), type(data)
    return [item for item in data if isinstance(item, dict) and "id" in item]


def _meus(data: Any) -> list[dict[str, Any]]:
    assert isinstance(data, dict) and isinstance(data.get("meus"), list), type(data)
    return [item for item in data["meus"] if isinstance(item, dict)]


KI_SEED_COUNT = 5


def _trimmed_known_issues(tmp_path: Path) -> tuple[bytes, bytes]:
    """A small ``known-issues`` store (yaml, rendered md): the first top-level issues.

    A long store makes the renderer fold low-severity rows past its line budget,
    so a fixture with one could not list a filed issue. The source is the
    ``lanes_fixtures/known-issues.yaml`` fixture.
    The trimmed store keeps the file's keys, the first ``KI_SEED_COUNT`` top-level
    issues, and one ``open`` and one ``resolved`` issue if those are not among them.
    """
    data = yaml.safe_load((FIXTURES / CANON[KI_YAML]).read_text(encoding="utf-8"))
    assert isinstance(data, dict), type(data)
    issues = _issues(data)
    kept = issues[:KI_SEED_COUNT]
    for status in ("open", "resolved"):
        if not any(item.get("status") == status for item in kept):
            kept.append(next(item for item in issues if item.get("status") == status))
    data["issues"] = kept
    work = tmp_path / "ki-seed"
    work.mkdir()
    yaml_path = work / "known-issues.yaml"
    md_path = work / "known-issues.md"
    yaml_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "issue_triage.py"),
            "--yaml",
            str(yaml_path),
            "--md",
            str(md_path),
            "render",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLI_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return yaml_path.read_bytes(), md_path.read_bytes()


def _source_files() -> dict[str, bytes]:
    """The junction-file fixtures and the two tools (with their packages) of this copy."""
    files = {rel: (FIXTURES / CANON[rel]).read_bytes() for rel in CANON_FILES}
    files.update({rel: (ROOT / rel).read_bytes() for rel in TOOL_FILES})
    for package in TOOL_PACKAGES:
        for path in sorted((ROOT / package).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    return files


def _ownership(task: bytes, slug: str) -> bytes:
    """The fixture task.md with a ``## Lane Ownership`` block for the lane's own paths."""
    owns = (
        "src/lane/",
        f".agent/context/handoffs/{slug}-handoff.md",
        f".agent/context/handoffs/{slug}-implementation-critical-review.md",
        f"{PLANS}/{slug}/artifacts/",
    )
    block = (
        "\n## Lane Ownership\n\n```yaml\nowns:\n"
        + "".join(f"  - {item}\n" for item in owns)
        + "must_not_touch: []\n```\n"
    )
    return task + block.encode("utf-8")


def _lanes(
    land: Land, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """``python tools/lanes.py <args>`` with the fixture environment and the rig's session."""
    full = land.rig.fx.env(**{SESSION_ENV: land.rig.fx.session}, **(env or {}))
    return subprocess.run(
        [sys.executable, str(LANES), *args],
        cwd=str(cwd or land.repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=full,
        timeout=CLI_TIMEOUT_S,
        check=False,
    )


def _build(tmp_path: Path) -> Land:
    """Seed the junction files on ``main``, add the lane worktree and claim it."""
    rig = b3.rig(tmp_path / "fx", ROOT, seed=lwc.SEED)
    slug = rig.plan
    files = _source_files()
    files[KI_YAML], files[KI_MD] = _trimmed_known_issues(tmp_path)
    task_rel = f"{PLANS}/{slug}/task.md"
    files[task_rel] = _ownership((rig.repo / task_rel).read_bytes(), slug)
    files[CURRENT_FOCUS] = CURRENT_FOCUS_TEXT.encode("utf-8")
    files[GROUPING] = GROUPING_TEXT.encode("utf-8")
    files["tools/validate_codebase.py"] = GATE_STUB.encode("utf-8")
    rig.seed(files, "fixture: junction files and the lane plan")
    meus = _meus(yaml.safe_load(files[MEU_STATUS].decode("utf-8")))
    row = next(item for item in meus if item.get("row_key") == "MEU-785")
    target = next(status for status in STATUSES if status != row.get("status"))
    issues = _issues(yaml.safe_load(files[KI_YAML].decode("utf-8")))
    open_ki = next(str(item["id"]) for item in issues if item.get("status") == "open")
    resolved_ki = next(
        str(item["id"]) for item in issues if item.get("status") == "resolved"
    )
    assert NEW_KI not in {str(item["id"]) for item in issues}
    wt = tmp_path / "lane-wt"
    rig.git("worktree", "add", "-q", "-b", f"lane/{slug}", str(wt))
    claim = subprocess.run(
        [
            sys.executable,
            str(LANES),
            "claim",
            "--plan",
            f"{PLANS}/{slug}",
            "--worktree",
            str(wt),
            "--session",
            rig.fx.session,
        ],
        cwd=str(wt),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=rig.fx.env(**{SESSION_ENV: rig.fx.session}),
        timeout=CLI_TIMEOUT_S,
        check=False,
    )
    assert claim.returncode == 0, (claim.stdout, claim.stderr)
    card = json.loads((rig.fx.common_dir / "lanes" / f"{slug}.json").read_text("utf-8"))
    return Land(
        rig=rig,
        wt=wt,
        generation=str(card["generation"]),
        meu_row="MEU-785",
        meu_target=target,
        open_ki=open_ki,
        resolved_ki=resolved_ki,
        existing_ki=str(issues[0]["id"]),
    )


def _handoff_text(rows: Rows) -> str:
    """A lane handoff whose requests table has one code-span Request cell per row."""
    table = "".join(f"| {rid} | `{request}` |\n" for rid, request in rows)
    return (
        "# Lane fixture handoff\n\n"
        "## Integration requests\n\n"
        "| Id | Request |\n"
        "|---|---|\n" + table
    )


def _lane_commit(land: Land, rows: Rows, payloads: Payloads | None = None) -> None:
    """Commit the lane's work, its handoff and its KI payloads; record L0."""
    files: dict[str, str] = {
        "src/lane/feature.py": '"""Lane fixture feature."""\n\nFEATURE = 1\n',
        land.handoff: _handoff_text(rows),
    }
    for ki, text in (payloads or {}).items():
        files[land.payload_path(ki)] = text
    for rel, text in files.items():
        path = land.wt / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    bf.git(land.wt, "add", "-A")
    bf.git(land.wt, "commit", "-q", "-m", "lane: fixture work and handoff")
    land.l0 = bf.git(land.wt, "rev-parse", "HEAD")


def _move_main(land: Land) -> None:
    """One more ``main`` commit (a metrics row) so that P is not the lane base."""
    data = (land.repo / METRICS).read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in data else "\n"
    land.p = land.rig.seed(
        {METRICS: (data + P_ROW + newline).encode("utf-8")}, "main: another metrics row"
    )


def _prepare(
    land: Land, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """``land prepare --worktree W --l0 L0 --message-file F --op OP`` from the main tree."""
    message = land.rig.fx.root / "land-message.txt"
    message.write_bytes(b"feat(lane): land the fixture lane\n")
    return _lanes(
        land,
        "land",
        "prepare",
        "--worktree",
        str(land.wt),
        "--l0",
        land.l0,
        "--message-file",
        str(message),
        "--op",
        OP_ID,
        env=env,
    )


def _ready(
    tmp_path: Path, rows: Callable[[Land], Rows], payloads: Payloads | None = None
) -> tuple[Land, subprocess.CompletedProcess[str]]:
    land = _build(tmp_path)
    _lane_commit(land, rows(land), payloads)
    _move_main(land)
    return land, _prepare(land)


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    """The land fields of an op record: the record, then each entry's identity and evidence."""
    merged: dict[str, Any] = {
        key: value for key, value in record.items() if key != "journal"
    }
    for item in record.get("journal", []):
        if not isinstance(item, dict):
            continue
        for part in ("identity", "evidence"):
            if isinstance(item.get(part), dict):
                merged.update(item[part])
    return merged


def _journal(land: Land) -> dict[str, Any]:
    """The land journal ``<store>/ops/<plan>/<run>/<op>/op.json`` (the run folder by glob)."""
    found = sorted(land.rig.fx.store.glob(f"ops/*/*/{OP_ID}/op.json"))
    assert len(found) == 1, found
    data = json.loads(found[0].read_text(encoding="utf-8"))
    assert isinstance(data, dict), found[0]
    return _fields(data)


def _tree(land: Land) -> str:
    """The integrated tree T from the journal, checked against the kept ref ``T``."""
    journal = _journal(land)
    tree = land.rig.git("rev-parse", f"{journal['T']}^{{tree}}")
    kept = land.kept("T")
    assert kept, "refs/lanes/<slug>/<op>/T is missing"
    assert land.rig.git("rev-parse", f"{kept}^{{tree}}") == tree
    return tree


def _show(land: Land, rev: str, rel: str) -> str:
    return land.rig.git("show", f"{rev}:{rel}")


def _blob(land: Land, rev: str, rel: str) -> str:
    return land.rig.git("rev-parse", f"{rev}:{rel}")


def _section(text: str, heading: str) -> list[str]:
    """The lines of a ``## `` section, up to the next ``## `` heading."""
    lines = text.splitlines()
    start = lines.index(heading)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def _refused(proc: subprocess.CompletedProcess[str], reason: str) -> None:
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert any(
        line.startswith(f"refused: {reason}") for line in proc.stdout.splitlines()
    ), (reason, proc.stdout, proc.stderr)


def _all_verbs(land: Land) -> Rows:
    return [
        (land.rid(1), f"meu-status {land.meu_row} -> {land.meu_target}"),
        (land.rid(2), f"grouping-cursor {GROUPING} -> LX2"),
        (land.rid(3), f"ki-file {NEW_KI} {land.payload_path(NEW_KI)}"),
        (land.rid(4), f"ki-close {land.open_ki} -> fixed by the lane fixture"),
        (land.rid(5), f"metrics-row {LANE_ROW}"),
    ]


def test_integrate_applies_every_verb_at_p(tmp_path: Path) -> None:
    """AC-785.15: each of the five forms lands in T, applied at P; nothing else moves."""
    land, proc = _ready(tmp_path, _all_verbs, {NEW_KI: KI_PAYLOAD})
    rows = _all_verbs(land)
    journal = _journal(land)
    ids = [str(item) for item in journal["request_ids"]]
    assert sorted(ids) == sorted(rid for rid, _ in rows), (ids, proc.stdout)
    assert len(ids) == len(set(ids)), ids
    tree = _tree(land)

    meus = _meus(yaml.safe_load(_show(land, tree, MEU_STATUS)))
    assert [m.get("status") for m in meus if m.get("row_key") == land.meu_row] == [
        land.meu_target
    ]

    cursor = [
        line
        for line in _show(land, tree, GROUPING).splitlines()
        if line.startswith("Global cursor:")
    ]
    assert len(cursor) == 1 and cursor[0].startswith("Global cursor: **LX2**"), cursor

    issues = {
        str(item["id"]): item
        for item in _issues(yaml.safe_load(_show(land, tree, KI_YAML)))
    }
    assert NEW_KI in issues, sorted(issues)[:5]
    filed = issues[NEW_KI]
    assert (filed.get("title"), filed.get("severity"), filed.get("component")) == (
        "Lane fixture issue",
        "low",
        "infrastructure",
    )
    assert issues[land.open_ki].get("status") == "resolved"
    assert NEW_KI in _show(land, tree, KI_MD)

    metrics = _show(land, tree, METRICS).splitlines()
    assert metrics.count(P_ROW) == 1 and metrics.count(LANE_ROW) == 1

    for rel in (SECRETS_BASELINE, CITATION_BASELINE):
        assert _blob(land, tree, rel) == _blob(land, land.p, rel), rel
    before = _show(land, land.p, CURRENT_FOCUS)
    after = _show(land, tree, CURRENT_FOCUS)
    for heading in ("## Current Priority", "## Other lanes"):
        assert _section(after, heading) == _section(before, heading), heading
    assert _show(land, tree, "src/lane/feature.py").startswith('"""Lane fixture')


def test_integrate_rerun_applies_nothing_twice(tmp_path: Path) -> None:
    """AC-785.15: a crash after the kept refs, then ``land recover``, applies each request once."""
    land = _build(tmp_path)
    _lane_commit(land, _all_verbs(land), {NEW_KI: KI_PAYLOAD})
    _move_main(land)
    crashed = _prepare(land, env={b3.CRASH: "land:kept:done"})
    assert crashed.returncode == b3.CRASH_EXIT, (crashed.stdout, crashed.stderr)
    recovered = _lanes(land, "land", "recover", "--op", OP_ID)
    ids = [str(item) for item in _journal(land)["request_ids"]]
    assert sorted(ids) == sorted(rid for rid, _ in _all_verbs(land)), (
        ids,
        recovered.stdout,
        recovered.stderr,
    )
    tree = _tree(land)
    assert _show(land, tree, METRICS).splitlines().count(LANE_ROW) == 1
    filed = [
        item
        for item in _issues(yaml.safe_load(_show(land, tree, KI_YAML)))
        if str(item["id"]) == NEW_KI
    ]
    assert len(filed) == 1, filed


def _case_unknown(land: Land) -> tuple[Rows, Payloads, str]:
    return (
        [(land.rid(1), "MEU-758 status → done")],
        {},
        f"request_unknown:{land.rid(1)}",
    )


def _case_id_shape(land: Land) -> tuple[Rows, Payloads, str]:
    bad = f"{land.slug}/{land.generation}/x"
    return [(bad, f"meu-status {land.meu_row} -> {land.meu_target}")], {}, "request_id:"


def _case_id_missing_n(land: Land) -> tuple[Rows, Payloads, str]:
    bad = f"{land.slug}/{land.generation}"
    return [(bad, f"meu-status {land.meu_row} -> {land.meu_target}")], {}, "request_id:"


def _field(land: Land, request: str) -> tuple[Rows, Payloads, str]:
    return [(land.rid(1), request)], {}, f"request_field:{land.rid(1)}:"


def _case_status_done(land: Land) -> tuple[Rows, Payloads, str]:
    return _field(land, f"meu-status {land.meu_row} -> done")


def _case_closed_no_reason(land: Land) -> tuple[Rows, Payloads, str]:
    return _field(land, f"meu-status {land.meu_row} -> closed")


def _case_unknown_row(land: Land) -> tuple[Rows, Payloads, str]:
    return _field(land, "meu-status MEU-99999 -> in_progress")


def _case_grouping_missing(land: Land) -> tuple[Rows, Payloads, str]:
    return _field(
        land,
        "grouping-cursor .agent/context/grouping/missing-session-grouping.md -> LX2",
    )


def _case_grouping_session(land: Land) -> tuple[Rows, Payloads, str]:
    return _field(land, f"grouping-cursor {GROUPING} -> LX9")


def _case_metrics_columns(land: Land) -> tuple[Rows, Payloads, str]:
    return _field(land, "metrics-row | 2026-10-23 | MEU-785 | three |")


def _payload(land: Land, text: str, suffix: str) -> tuple[Rows, Payloads, str]:
    rows = [(land.rid(1), f"ki-file {NEW_KI} {land.payload_path(NEW_KI)}")]
    return rows, {NEW_KI: text}, f"request_payload:{land.rid(1)}:{suffix}"


def _case_payload_unknown_key(land: Land) -> tuple[Rows, Payloads, str]:
    return _payload(land, KI_PAYLOAD + "owner: fixture\n", "owner")


def _case_payload_missing_key(land: Land) -> tuple[Rows, Payloads, str]:
    text = "".join(
        line + "\n" for line in KI_PAYLOAD.splitlines() if not line.startswith("title:")
    )
    return _payload(land, text, "missing:title")


def _case_payload_bad_severity(land: Land) -> tuple[Rows, Payloads, str]:
    return _payload(land, KI_PAYLOAD.replace("severity: low", "severity: urgent"), "")


REFUSALS: tuple[Callable[[Land], tuple[Rows, Payloads, str]], ...] = (
    _case_unknown,
    _case_id_shape,
    _case_id_missing_n,
    _case_status_done,
    _case_closed_no_reason,
    _case_unknown_row,
    _case_grouping_missing,
    _case_grouping_session,
    _case_metrics_columns,
    _case_payload_unknown_key,
    _case_payload_missing_key,
    _case_payload_bad_severity,
)


@pytest.mark.parametrize(
    "case",
    [pytest.param(case, id=case.__name__.removeprefix("_case_")) for case in REFUSALS],
)
def test_integrate_refuses_a_bad_request(
    tmp_path: Path, case: Callable[[Land], tuple[Rows, Payloads, str]]
) -> None:
    """AC-785.15: an unknown form, a bad id, a bad field or a bad payload stops the land before T."""
    land = _build(tmp_path)
    rows, payloads, reason = case(land)
    _lane_commit(land, rows, payloads)
    _move_main(land)
    proc = _prepare(land)
    _refused(proc, reason)
    assert land.rig.ref() == land.p
    assert land.kept("T") == ""


def _conflict_ki_file(land: Land) -> tuple[Rows, Payloads, str]:
    rows = [
        (
            land.rid(1),
            f"ki-file {land.existing_ki} {land.payload_path(land.existing_ki)}",
        )
    ]
    return rows, {land.existing_ki: KI_PAYLOAD}, land.rid(1)


def _conflict_ki_close_resolved(land: Land) -> tuple[Rows, Payloads, str]:
    return [(land.rid(1), f"ki-close {land.resolved_ki} -> again")], {}, land.rid(1)


def _conflict_ki_close_unknown(land: Land) -> tuple[Rows, Payloads, str]:
    return [(land.rid(1), "ki-close NO-SUCH-KI-FIXTURE -> gone")], {}, land.rid(1)


CONFLICTS: tuple[Callable[[Land], tuple[Rows, Payloads, str]], ...] = (
    _conflict_ki_file,
    _conflict_ki_close_resolved,
    _conflict_ki_close_unknown,
)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(case, id=case.__name__.removeprefix("_conflict_"))
        for case in CONFLICTS
    ],
)
def test_integrate_lists_a_conflict_and_continues(
    tmp_path: Path, case: Callable[[Land], tuple[Rows, Payloads, str]]
) -> None:
    """AC-785.15: a conflicting request is left out and listed; the other requests still land."""
    land = _build(tmp_path)
    rows, payloads, conflict = case(land)
    good = (land.rid(2), f"metrics-row {LANE_ROW}")
    _lane_commit(land, [*rows, good], payloads)
    _move_main(land)
    proc = _prepare(land)
    assert any(
        f"request_conflict:{conflict}" in line for line in proc.stdout.splitlines()
    ), (proc.stdout, proc.stderr)
    ids = [str(item) for item in _journal(land)["request_ids"]]
    assert conflict not in ids and good[0] in ids, ids
    tree = _tree(land)
    assert _show(land, tree, METRICS).splitlines().count(LANE_ROW) == 1
    assert _blob(land, tree, KI_YAML) == _blob(land, land.p, KI_YAML)
