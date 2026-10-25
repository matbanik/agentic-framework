"""Red tests for MEU-785 AC-785.31, AC-785.32 and AC-785.39: the lane docs, pins and request grammar.

* AC-785.31 (docs). ``git-workflow/SKILL.md`` has a D-1 lane section; ``commands.md`` names every new ``tools/lanes.py`` verb and its
  ``executor_worktree.py create`` / ``remove`` lines name the lane branch;
  ``execution-session.md`` §4 names the land path; the ``TASK-TEMPLATE.md`` H2-3c
  row has the lane sentence.
* AC-785.32 (pins). Every tool module that the lane path imports is in the pinned
  component set of ``.agent/run-parameters.policy.json``.
* AC-785.39 (one grammar). The ``## Integration requests`` section of
  ``.agent/context/handoffs/TEMPLATE.md`` holds one code-span example row per form of
  ``tools/lanes.py`` ``REQUEST_FORMS``; the rows, copied into a fixture lane handoff
  with their ids filled in, go through the production integrator (step 3 of
  ``land prepare``) in a disposable repository, and every row applies.

Framework port (AC-785.33): ``AGENTS.md`` is adopter-owned (the framework ships
it as the ``01-agents.diff`` overlay), so its D-1 commit-sentence check stays in the
adopter. Each doc path takes the adopter location first and the framework
``core/`` location second (``templates/``, ``.policy.json.template``), so the same
file runs in the framework and in a fresh adoption.

Readings (recorded in the C-R3 evidence): the lane path is the static import closure of
``tools/lanes.py`` and ``tools/ref_guard.py`` (D:381: helper, lease module, ref
guard), and it reaches ``tools/commit_batch.py`` because ``land publish`` publishes
through the commit_batch tree adapter (IP AC-785.18, ``_build_candidate``); the
template may write concrete values or the id placeholders ``<lane>``,
``<generation>``, ``<n>``, ``<lane plan>``, ``<plan>``, ``<MEU-ID>``, ``<KI-ID>``,
``<grouping-file>`` and ``<session-id>``, which the test fills from the fixture.

The AC-785.39 rig is ``tools/tests/test_lanes_integrate.py`` (``phase_b3.rig`` with
the junction-file fixtures and tools, a claimed lane worktree, one more ``main``
commit), reused by import.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

from tools.tests import test_lanes_integrate as li

ROOT = Path(__file__).resolve().parents[2]


def _first(*candidates: Path) -> Path:
    """The first existing path of ``candidates`` (adopter location first), else the first."""
    return next((path for path in candidates if path.is_file()), candidates[0])


GIT_SKILL = ROOT / ".agent" / "skills" / "git-workflow" / "SKILL.md"
COMMANDS_MD = ROOT / ".agent" / "docs" / "commands.md"
EXECUTION_SESSION = ROOT / ".agent" / "workflows" / "execution-session.md"
TASK_TEMPLATE = _first(
    ROOT / "docs" / "execution" / "plans" / "TASK-TEMPLATE.md",
    ROOT / ".agent" / "templates" / "TASK-TEMPLATE.md",
    ROOT / "templates" / "TASK-TEMPLATE.md",
)
HANDOFF_TEMPLATE = _first(
    ROOT / ".agent" / "context" / "handoffs" / "TEMPLATE.md",
    ROOT / ".agent" / "templates" / "HANDOFF-TEMPLATE.md",
    ROOT / "templates" / "HANDOFF-TEMPLATE.md",
)
POLICY = _first(
    ROOT / ".agent" / "run-parameters.policy.json",
    ROOT / ".agent" / "run-parameters.policy.json.template",
)

LANE_COMMIT = "tools/lanes.py commit"
COMMIT_BATCH = "tools/commit_batch.py"
SECTION = "## Integration requests"
GRAMMAR_FORMS = frozenset(
    {"meu-status", "grouping-cursor", "ki-file", "ki-close", "metrics-row"}
)
LANE_PATH_ROOTS = ("tools/lanes.py", "tools/ref_guard.py")
D1_EXCLUSIONS = ("push", "rebase", "reset", "delet")
STAGE1_EXAMPLE = "MEU-758 status → done"
PROBE = "lane_unpinned_probe"

# The new tools/lanes.py verbs of the boundary table (IP "Boundary inventory").
NEW_VERBS: tuple[tuple[str, str], ...] = (
    ("commit", r"tools/lanes\.py commit\b"),
    ("release --worktree", r"tools/lanes\.py release\b.*--worktree"),
    ("land prepare", r"tools/lanes\.py land prepare\b"),
    ("land publish", r"tools/lanes\.py land publish\b"),
    ("land recover", r"tools/lanes\.py land recover\b"),
    ("deps begin", r"tools/lanes\.py deps begin\b"),
    ("deps end", r"tools/lanes\.py deps (?:begin\\?\|)?end\b"),
    ("gate run", r"tools/lanes\.py gate run\b"),
)


def _lines(path: Path) -> list[str]:
    return path.read_bytes().decode("utf-8").splitlines()


def _headed_sections(path: Path) -> list[tuple[str, list[str]]]:
    """``(heading, body)`` pairs of a Markdown file; ``#`` lines inside code fences are not headings."""
    sections: list[tuple[str, list[str]]] = []
    fenced = False
    for line in _lines(path):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if not fenced and re.match(r"#{1,6} ", line):
            sections.append((line, []))
        elif sections:
            sections[-1][1].append(line)
    return sections


# --- AC-785.31: the docs -------------------------------------------------------


def test_git_workflow_skill_has_the_d1_lane_section() -> None:
    """AC-785.31 / D:179: a lane section names the helper and what D-1 does not cover."""
    found = [
        (heading, "\n".join(body))
        for heading, body in _headed_sections(GIT_SKILL)
        if "lane" in heading.lower()
    ]
    assert found, "git-workflow/SKILL.md has no heading that names lanes"
    matching = [
        heading
        for heading, body in found
        if LANE_COMMIT in body and all(word in body.lower() for word in D1_EXCLUSIONS)
    ]
    assert matching, (
        f"no lane section names {LANE_COMMIT} and the D-1 exclusions "
        f"{D1_EXCLUSIONS}: {[heading for heading, _ in found]}"
    )


@pytest.mark.parametrize(
    ("verb", "pattern"), NEW_VERBS, ids=[verb for verb, _ in NEW_VERBS]
)
def test_commands_md_names_each_new_lane_verb(verb: str, pattern: str) -> None:
    """AC-785.31: ``commands.md`` documents each new ``tools/lanes.py`` verb."""
    regex = re.compile(pattern)
    assert any(regex.search(line) for line in _lines(COMMANDS_MD)), (
        f"commands.md does not name `tools/lanes.py {verb}`"
    )


@pytest.mark.parametrize("verb", ["create", "remove"])
def test_commands_md_executor_worktree_line_names_the_lane_branch(verb: str) -> None:
    """AC-785.31 (commands.md :32 create, :36 remove; AC-785.9): the line names ``lane/<slug>``."""
    lines = [
        line
        for line in _lines(COMMANDS_MD)
        if f"tools/executor_worktree.py {verb} " in line
    ]
    assert len(lines) == 1, f"{len(lines)} executor_worktree.py {verb} lines"
    assert "lane/<slug>" in lines[0], lines[0][:240]


def test_execution_session_section_4_names_the_land_path() -> None:
    """AC-785.31: §4 of ``execution-session.md`` names ``land prepare`` and ``land publish``."""
    lines = _lines(EXECUTION_SESSION)
    start = next(i for i, line in enumerate(lines) if line.startswith("### 4. "))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("### "))
    body = "\n".join(lines[start:end])
    for verb in ("land prepare", "land publish"):
        assert f"tools/lanes.py {verb}" in body, f"§4 does not name {verb}"


def test_task_template_h2_3c_has_the_lane_sentence() -> None:
    """AC-785.31: the TASK-TEMPLATE H2-3c row names the lane land."""
    rows = [line for line in _lines(TASK_TEMPLATE) if line.startswith("| H2-3c |")]
    assert len(rows) == 1, f"{len(rows)} H2-3c rows"
    assert "tools/lanes.py land" in rows[0], rows[0][:240]


# --- AC-785.32: the pinned set -------------------------------------------------


def _module_file(base: Path, dotted: str) -> str | None:
    """The repository path of ``tools.<name>`` under ``base``; None when it is not a tool module."""
    rel = dotted.replace(".", "/")
    for candidate in (f"{rel}.py", f"{rel}/__init__.py"):
        if (base / candidate).is_file():
            return candidate
    return None


def _tool_imports(base: Path, rel: str) -> set[str]:
    """The tool modules that ``rel`` imports statically (relative, ``tools.`` and sibling forms)."""
    tree = ast.parse((base / rel).read_bytes().decode("utf-8"), filename=rel)
    names: set[str] = set()

    def sibling(name: str) -> None:
        head = name.split(".")[0]
        if _module_file(base, f"tools.{head}") is not None:
            names.add(f"tools.{head}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("tools."):
                    names.add(alias.name)
                elif alias.name != "tools":
                    sibling(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level >= 1:
                if module:
                    names.add(f"tools.{module}")
                else:
                    names.update(f"tools.{alias.name}" for alias in node.names)
            elif module == "tools":
                names.update(f"tools.{alias.name}" for alias in node.names)
            elif module.startswith("tools."):
                names.add(module)
            elif module:
                sibling(module)
    files = {_module_file(base, name) for name in names}
    return {item for item in files if item is not None and item != rel}


def _closure(base: Path, roots: tuple[str, ...]) -> set[str]:
    """Every tool module reached from ``roots`` by static imports, the roots included."""
    seen: set[str] = set()
    todo = [root for root in roots if (base / root).is_file()]
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        todo.extend(sorted(_tool_imports(base, rel) - seen))
    return seen


def _pinned() -> set[str]:
    data = json.loads(POLICY.read_bytes().decode("utf-8"))
    assert isinstance(data, dict) and isinstance(data.get("components"), dict), POLICY
    return {str(key) for key in data["components"]}


def test_every_lane_path_module_is_pinned(tmp_path: Path) -> None:
    """AC-785.32 / D:381: the lane path's tool modules are all pinned; a new unpinned one is caught."""
    closure = _closure(ROOT, LANE_PATH_ROOTS)
    assert COMMIT_BATCH in closure, (
        "the lane path does not reach tools/commit_batch.py (land publish goes "
        f"through its tree adapter): {sorted(closure)}"
    )
    pinned = _pinned()
    assert sorted(closure - pinned) == [], "unpinned lane-path modules"

    copy = tmp_path / "copy"
    for rel in closure:
        target = copy / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    (copy / "tools" / "__init__.py").write_bytes(b"")
    (copy / "tools" / f"{PROBE}.py").write_bytes(b'"""Unpinned probe."""\n')
    lanes = copy / "tools" / "lanes.py"
    lanes.write_bytes(lanes.read_bytes() + f"\nfrom . import {PROBE}\n".encode())
    caught = _closure(copy, LANE_PATH_ROOTS) - pinned
    assert caught == {f"tools/{PROBE}.py"}, sorted(caught)


# --- AC-785.39: one request grammar --------------------------------------------


def _template_section() -> list[str]:
    return li._section(HANDOFF_TEMPLATE.read_bytes().decode("utf-8"), SECTION)


def _table_rows(section: list[str]) -> list[tuple[str, str]]:
    """``(id cell, request code-span body)`` per data row; each Request cell must be one code span."""
    rows: list[tuple[str, str]] = []
    for line in section:
        if not line.startswith("|") or re.match(r"\|\s*-", line):
            continue
        cells = re.split(r"(?<!\\)\|", line.strip())
        if len(cells) < 3 or cells[1].strip() == "Id":
            continue
        rest = line.strip()[len(cells[0]) + len(cells[1]) + 2 :].rstrip()
        assert rest.endswith("|"), line
        cell = rest[:-1].strip()
        assert (
            len(cell) >= 2
            and cell.startswith("`")
            and cell.endswith("`")
            and cell.count("`") == 2
        ), f"the Request cell is not one code span: {line!a}"
        rows.append((cells[1].strip(), cell[1:-1].replace("\\|", "|")))
    return rows


def _check_template_structure(section: list[str]) -> list[tuple[str, str]]:
    rows = _table_rows(section)
    free = [line for line in section if line.lower().startswith("other examples")]
    assert free == [], f"free-text examples remain: {free}"
    forms = [request.split(" ", 1)[0] for _, request in rows]
    assert sorted(forms) == sorted(set(forms)), f"a form has two example rows: {forms}"
    assert set(forms) == GRAMMAR_FORMS, sorted(forms)
    return rows


def _form_names(forms: object) -> set[str]:
    """The form names of ``lanes.REQUEST_FORMS`` (a mapping by name, or a collection)."""
    if isinstance(forms, Mapping):
        return {str(key) for key in forms}
    if isinstance(forms, (list, tuple, set, frozenset)):
        names: set[str] = set()
        for item in forms:
            name = item if isinstance(item, str) else getattr(item, "name", None)
            assert isinstance(name, str), f"REQUEST_FORMS item without a name: {item!r}"
            names.add(name)
        return names
    pytest.fail(f"REQUEST_FORMS has the unsupported type {type(forms).__name__}")


def test_template_rows_cover_request_forms() -> None:
    """AC-785.39: one code-span example row per form, and the forms are ``REQUEST_FORMS``."""
    rows = _check_template_structure(_template_section())
    lanes: ModuleType = importlib.import_module("tools.lanes")
    names = _form_names(lanes.REQUEST_FORMS)
    assert names == GRAMMAR_FORMS, sorted(names)
    assert {request.split(" ", 1)[0] for _, request in rows} == names


def _fill(land: li.Land, line: str, n: int, form: str) -> str:
    """Fill the id placeholders of one template row from the fixture lane."""
    ki = li.NEW_KI if form == "ki-file" else land.open_ki
    values = {
        "<lane>": land.slug,
        "<generation>": land.generation,
        "<n>": str(n),
        "<lane plan>": land.slug,
        "<plan>": land.slug,
        "<MEU-ID>": land.meu_row,
        "<KI-ID>": ki,
        "<grouping-file>": li.GROUPING,
        "<session-id>": "LX2",
    }
    for key, value in values.items():
        line = line.replace(key, value)
    return line


def test_template_integration_rows_apply(tmp_path: Path) -> None:
    """AC-785.39: the template's example rows, ids filled in, all apply through ``land prepare``."""
    section = _template_section()
    _check_template_structure(section)
    land = li._build(tmp_path)

    filled: list[str] = []
    n = 0
    for line in section:
        rows = _table_rows([line]) if line.startswith("|") else []
        if rows:
            n += 1
            form = rows[0][1].split(" ", 1)[0]
            line = _fill(land, line, n, form)
        filled.append(line)
    requests = _table_rows(filled)
    ids = [rid.strip("`") for rid, _ in requests]
    assert ids == [land.rid(i) for i in range(1, len(ids) + 1)], ids

    main_files: dict[str, bytes] = {}
    lane_files: dict[str, str] = {
        "src/lane/feature.py": '"""Lane fixture feature."""\n\nFEATURE = 1\n',
        land.handoff: "# Lane fixture handoff\n\n" + "\n".join(filled) + "\n",
    }
    for _, request in requests:
        words = request.split(" ")
        if words[0] == "grouping-cursor" and words[1] != li.GROUPING:
            source = ROOT / words[1]
            if source.is_file():
                main_files[words[1]] = source.read_bytes()
        if words[0] == "ki-file" and len(words) >= 3:
            lane_files[words[2]] = li.KI_PAYLOAD
    if main_files:
        land.rig.seed(main_files, "main: the template's grouping file")
    for rel, text in lane_files.items():
        path = land.wt / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    li.bf.git(land.wt, "add", "-A")
    li.bf.git(land.wt, "commit", "-q", "-m", "lane: fixture work and template handoff")
    land.l0 = li.bf.git(land.wt, "rev-parse", "HEAD")
    li._move_main(land)

    proc = li._prepare(land)
    out = proc.stdout.splitlines()
    assert [line for line in out if line.startswith("refused:")] == [], (
        proc.stdout,
        proc.stderr,
    )
    assert [line for line in out if "request_conflict:" in line] == [], proc.stdout
    applied = [str(item) for item in li._journal(land)["request_ids"]]
    assert sorted(applied) == sorted(ids), (applied, proc.stdout, proc.stderr)


def test_stage1_free_text_example_is_unknown(tmp_path: Path) -> None:
    """AC-785.39 edge case: the stage-1 example ``MEU-758 status → done`` → ``request_unknown:<id>``."""
    land, proc = li._ready(tmp_path, lambda lane: [(lane.rid(1), STAGE1_EXAMPLE)])
    li._refused(proc, f"request_unknown:{land.rid(1)}")
