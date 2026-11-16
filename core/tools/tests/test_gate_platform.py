"""Tests for ``tools/gate_platform.py``, the gate platform class tool (MEU-947).

Each test builds a fixture project under ``tmp_path`` and runs the tool on it
with ``--repo``, so no test reads the adopting project's own data file. The
tests run the tool as a subprocess, or import it inside the test body, so a
missing tool fails each test and is never a collection error. The fault tests
plant one fault in the valid fixture and run ``check --repo <tmp_path>``
(AC-947.7); the scan tests plant or remove a platform mark (the SCAN rule);
the show tests read the data back as JSON.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "gate_platform.py"

FIXTURE_VALIDATOR = '''"""A fake gate for the fixture project."""

STAGE_COST_ORDER: tuple[str, ...] = (
    "Lint",
    "Unit Tests",
    "Integration Tests",
)
'''

FIXTURE_UNIT = '''"""One test per platform mark form."""

import os
import platform
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_win_only():
    pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX only")
def test_posix_only():
    pass


@pytest.mark.xfail(platform.system() != "Windows", reason="Windows only")
class TestWinClass:
    def test_a(self):
        pass


class TestHolder:
    @pytest.mark.skipif(condition=os.name != "nt", reason="Windows only")
    def test_method(self):
        pass


def test_plain():
    pass
'''

FIXTURE_INTEGRATION = '''"""A module-level platform mark."""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")


def test_posix_module():
    pass
'''

FIXTURE_SPEC = """import { test } from '@playwright/test'

const NOT_WIN32 = process.platform !== 'win32'

test.describe('Demo suite', () => {
    test('win card', async () => {
        test.skip(NOT_WIN32, 'Windows only')
    })

    test('posix sibling', async () => {
        test.skip(!NOT_WIN32, 'the non-Windows sibling')
    })
})
"""

UNIT_FILE = "tests/unit/test_forms.py"
INT_FILE = "tests/integration/test_mod.py"
SPEC_FILE = "ui/tests/e2e/demo.spec.ts"


def _fixture_data() -> dict[str, object]:
    """The valid ``gate-platform/1`` data of the fixture project."""
    return {
        "schema": "gate-platform/1",
        "stage_source": {
            "path": "tools/validate_codebase.py",
            "name": "STAGE_COST_ORDER",
        },
        "stages": {
            "Integration Tests": {
                "class": "any",
                "basis": "fixture basis",
                "scan_paths": ["tests/integration"],
            },
            "Lint": {"class": "windows", "basis": "fixture basis"},
            "Unit Tests": {
                "class": "any",
                "basis": "fixture basis",
                "scan_paths": ["tests/unit"],
            },
        },
        "suites": {
            "e2e": {
                "path": "ui/playwright.config.ts",
                "ci_job": "e2e-tests",
                "class": "any",
                "basis": "fixture basis",
            }
        },
        "tests": [
            {
                "id": f"{UNIT_FILE}::test_win_only",
                "stage": "Unit Tests",
                "class": "windows",
                "condition": "sys.platform != 'win32'",
                "basis": "fixture basis",
            },
            {
                "id": f"{UNIT_FILE}::test_posix_only",
                "stage": "Unit Tests",
                "class": "linux",
                "condition": "os.name == 'nt'",
                "basis": "fixture basis",
            },
            {
                "id": f"{UNIT_FILE}::TestWinClass",
                "stage": "Unit Tests",
                "class": "windows",
                "condition": "platform.system() != 'Windows'",
                "basis": "fixture basis",
            },
            {
                "id": f"{UNIT_FILE}::TestHolder::test_method",
                "stage": "Unit Tests",
                "class": "windows",
                "condition": "os.name != 'nt'",
                "basis": "fixture basis",
            },
            {
                "id": INT_FILE,
                "stage": "Integration Tests",
                "class": "linux",
                "condition": "sys.platform == 'win32'",
                "basis": "fixture basis",
            },
            {
                "id": f"{SPEC_FILE}::Demo suite",
                "suite": "e2e",
                "class": "windows",
                "condition": "NOT_WIN32",
                "basis": "fixture basis",
            },
            {
                "id": f"{SPEC_FILE}::Demo suite::posix sibling",
                "suite": "e2e",
                "class": "linux",
                "condition": "!NOT_WIN32",
                "basis": "fixture basis",
            },
        ],
    }


def _write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` as UTF-8 with LF line ends, making parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _write_data(repo: Path, data: object) -> None:
    """Write the fixture data file at its default path under ``repo``."""
    _write(
        repo / "tools" / "gate_platform_classes.json", json.dumps(data, indent=1) + "\n"
    )


def _make_fixture(repo: Path) -> Path:
    """Build the valid fixture project under ``repo`` and return ``repo``."""
    _write(repo / "tools" / "validate_codebase.py", FIXTURE_VALIDATOR)
    _write(repo / UNIT_FILE, FIXTURE_UNIT)
    _write(repo / INT_FILE, FIXTURE_INTEGRATION)
    _write(repo / "ui" / "playwright.config.ts", "export default {}\n")
    _write(repo / SPEC_FILE, FIXTURE_SPEC)
    _write_data(repo, _fixture_data())
    return repo


def _tree_hash(repo: Path) -> dict[str, str]:
    """The sha256 of every file under ``repo``, keyed by its relative path."""
    return {
        p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(repo.rglob("*"))
        if p.is_file()
    }


def _run(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    """Run the tool with ``args`` and return the finished process (UTF-8 text)."""
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def _import_by_path(name: str, path: Path) -> ModuleType:
    """Import the module at ``path`` under the unique module ``name``."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"no import spec for {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
        sys.modules.pop(name, None)
    return module


# --------------------------------------------------------------------------- AC-947.1


def test_ag1_ac_947_1_check_ok_on_the_valid_fixture(tmp_path: Path) -> None:
    """A fixture with one class per stage passes ``check`` and prints the counts."""
    repo = _make_fixture(tmp_path)
    done = _run("check", "--repo", str(repo))
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip().splitlines() == ["check_ok stages=3 tests=7 suites=1"]


def test_ag1_ac_947_1_a_stage_with_no_class_fails(tmp_path: Path) -> None:
    """Removing the class of one stage gives exit 1 and ``check_bad:stage_missing:<name>``."""
    repo = _make_fixture(tmp_path)
    data = _fixture_data()
    stages = data["stages"]
    assert isinstance(stages, dict)
    del stages["Lint"]
    _write_data(repo, data)
    done = _run("check", "--repo", str(repo))
    assert done.returncode == 1, done.stdout + done.stderr
    assert "check_bad:stage_missing:Lint" in done.stdout.splitlines()


def test_ag1_ac_947_1_ast_read_equals_the_imported_tuple(tmp_path: Path) -> None:
    """The tool's AST read of the stage tuple equals the tuple that the module imports."""
    repo = _make_fixture(tmp_path)
    tool = _import_by_path("gate_platform_under_test", TOOL)
    gate = _import_by_path(
        "fixture_validate_codebase_under_test", repo / "tools" / "validate_codebase.py"
    )
    read = tool._stage_names(
        repo, {"path": "tools/validate_codebase.py", "name": "STAGE_COST_ORDER"}
    )
    assert read == tuple(gate.STAGE_COST_ORDER)
    assert read == ("Lint", "Unit Tests", "Integration Tests")


# --------------------------------------------------------------------------- AC-947.3 (SCAN)


def test_ag1_ac_947_3_a_planted_unlisted_mark_fails(tmp_path: Path) -> None:
    """A new platform ``skipif`` with no entry gives ``check_bad:scan_unlisted:<id>``."""
    repo = _make_fixture(tmp_path)
    _write(
        repo / UNIT_FILE,
        FIXTURE_UNIT
        + '\n\n@pytest.mark.skipif(sys.platform != "win32", reason="new")\ndef test_new_mark():\n    pass\n',
    )
    done = _run("check", "--repo", str(repo))
    assert done.returncode == 1, done.stdout + done.stderr
    assert (
        f"check_bad:scan_unlisted:{UNIT_FILE}::test_new_mark"
        in done.stdout.splitlines()
    )


def test_ag1_ac_947_3_a_removed_mark_fails(tmp_path: Path) -> None:
    """Removing the mark of a listed test gives ``check_bad:scan_stale:<id>``."""
    repo = _make_fixture(tmp_path)
    _write(
        repo / UNIT_FILE,
        FIXTURE_UNIT.replace(
            '@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")\n', ""
        ),
    )
    done = _run("check", "--repo", str(repo))
    assert done.returncode == 1, done.stdout + done.stderr
    assert (
        f"check_bad:scan_stale:{UNIT_FILE}::test_win_only" in done.stdout.splitlines()
    )


# --------------------------------------------------------------------------- AC-947.4


def test_ag1_ac_947_4_show_json_prints_the_data_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """``show --json`` prints the data file as JSON and leaves the fixture tree unchanged."""
    repo = _make_fixture(tmp_path)
    before = _tree_hash(repo)
    done = _run("show", "--json", "--repo", str(repo))
    after = _tree_hash(repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout) == _fixture_data()
    assert after == before


def test_ag1_ac_947_4_show_without_json_is_a_usage_error(tmp_path: Path) -> None:
    """``show`` with no ``--json`` gives exit 2 (argparse usage error)."""
    repo = _make_fixture(tmp_path)
    done = _run("show", "--repo", str(repo))
    assert done.returncode == 2, done.stdout + done.stderr
    assert "usage:" in done.stderr
    assert "--json" in done.stderr


def test_ag1_ac_947_4_show_json_refuses_a_stage_with_no_class(tmp_path: Path) -> None:
    """``show --json`` runs the stage-set check: a stage with no class gives ``show_bad:stage_missing:``."""
    repo = _make_fixture(tmp_path)
    data = _fixture_data()
    stages = data["stages"]
    assert isinstance(stages, dict)
    del stages["Lint"]
    _write_data(repo, data)
    done = _run("show", "--json", "--repo", str(repo))
    assert done.returncode == 1, done.stdout + done.stderr
    assert "show_bad:stage_missing:Lint" in done.stdout.splitlines()


# --------------------------------------------------------------------------- AC-947.7

Mutation = Callable[[Path, dict[str, object]], object]


def _tests_of(data: dict[str, object]) -> list[dict[str, object]]:
    """The ``tests`` list of ``data``, typed."""
    tests = data["tests"]
    assert isinstance(tests, list)
    return tests


def _stages_of(data: dict[str, object]) -> dict[str, dict[str, object]]:
    """The ``stages`` map of ``data``, typed."""
    stages = data["stages"]
    assert isinstance(stages, dict)
    return stages


def _source_of(data: dict[str, object]) -> dict[str, object]:
    """The ``stage_source`` map of ``data``, typed."""
    source = data["stage_source"]
    assert isinstance(source, dict)
    return source


def _bad_json(repo: Path, data: dict[str, object]) -> object:
    _write(repo / "tools" / "gate_platform_classes.json", "{not json\n")
    return None


def _no_file(repo: Path, data: dict[str, object]) -> object:
    (repo / "tools" / "gate_platform_classes.json").unlink()
    return None


def _not_an_object(repo: Path, data: dict[str, object]) -> object:
    return [data]


def _schema(repo: Path, data: dict[str, object]) -> object:
    data["schema"] = "gate-platform/2"
    return data


def _top_extra(repo: Path, data: dict[str, object]) -> object:
    data["extra"] = 1
    return data


def _stage_extra(repo: Path, data: dict[str, object]) -> object:
    _stages_of(data)["Lint"]["note"] = "x"
    return data


def _test_extra(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[0]["note"] = "x"
    return data


def _top_missing(repo: Path, data: dict[str, object]) -> object:
    del data["suites"]
    return data


def _test_missing(repo: Path, data: dict[str, object]) -> object:
    del _tests_of(data)[0]["basis"]
    return data


def _test_no_parent(repo: Path, data: dict[str, object]) -> object:
    del _tests_of(data)[0]["stage"]
    return data


def _test_two_parents(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[0]["suite"] = "e2e"
    return data


def _empty_basis(repo: Path, data: dict[str, object]) -> object:
    _stages_of(data)["Lint"]["basis"] = ""
    return data


def _scan_paths_bad(repo: Path, data: dict[str, object]) -> object:
    _stages_of(data)["Unit Tests"]["scan_paths"] = [""]
    return data


def _source_path_bad(repo: Path, data: dict[str, object]) -> object:
    _source_of(data)["path"] = 123
    return data


def _class_bad(repo: Path, data: dict[str, object]) -> object:
    _stages_of(data)["Lint"]["class"] = "mac"
    return data


def _test_class_bad(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[0]["class"] = "Windows"
    return data


def _source_name_bad(repo: Path, data: dict[str, object]) -> object:
    _source_of(data)["name"] = "NO_SUCH_TUPLE"
    return data


def _source_syntax_bad(repo: Path, data: dict[str, object]) -> object:
    _write(repo / "tools" / "validate_codebase.py", "STAGE_COST_ORDER = (\n")
    return data


def _source_not_strings(repo: Path, data: dict[str, object]) -> object:
    _write(repo / "tools" / "validate_codebase.py", "STAGE_COST_ORDER = (1, 2)\n")
    return data


def _stage_missing(repo: Path, data: dict[str, object]) -> object:
    del _stages_of(data)["Lint"]
    return data


def _stage_unknown(repo: Path, data: dict[str, object]) -> object:
    _stages_of(data)["Extra"] = {"class": "any", "basis": "fixture basis"}
    return data


def _parent_bad(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[0]["stage"] = "No Such Stage"
    return data


def _duplicate(repo: Path, data: dict[str, object]) -> object:
    tests = _tests_of(data)
    tests.append(copy.deepcopy(tests[0]))
    return data


def _same_class(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[5]["class"] = "any"
    return data


def _same_class_ancestor(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[6]["class"] = "windows"
    return data


def _target_missing(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[0]["id"] = f"{UNIT_FILE}::test_gone"
    return data


def _target_file_missing(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[0]["id"] = "tests/unit/test_absent.py::test_win_only"
    return data


def _suite_title_missing(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[5]["id"] = f"{SPEC_FILE}::No such suite"
    return data


def _condition_mismatch(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[0]["condition"] = "sys.platform != 'linux'"
    return data


def _suite_condition_mismatch(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[5]["condition"] = "IS_MAC"
    return data


def _condition_unknown(repo: Path, data: dict[str, object]) -> object:
    _write(
        repo / UNIT_FILE,
        FIXTURE_UNIT.replace(
            'sys.platform != "win32"', 'sys.platform.startswith("win")'
        ),
    )
    _tests_of(data)[0]["condition"] = "sys.platform.startswith('win')"
    return data


def _condition_class(repo: Path, data: dict[str, object]) -> object:
    _tests_of(data)[0]["class"] = "linux"
    return data


def _scan_unlisted(repo: Path, data: dict[str, object]) -> object:
    del _tests_of(data)[1]
    return data


def _scan_stale(repo: Path, data: dict[str, object]) -> object:
    _write(repo / INT_FILE, FIXTURE_INTEGRATION.replace("pytestmark = ", "_unused = "))
    return data


def _suite_path_missing(repo: Path, data: dict[str, object]) -> object:
    (repo / "ui" / "playwright.config.ts").unlink()
    return data


FAULTS: list[tuple[str, Mutation, str]] = [
    ("classes_unreadable_json", _bad_json, "check_bad:classes_unreadable"),
    ("classes_unreadable_missing", _no_file, "check_bad:classes_unreadable"),
    ("value_bad_not_an_object", _not_an_object, "check_bad:value_bad"),
    ("schema_bad", _schema, "check_bad:schema_bad"),
    ("extra_key_top", _top_extra, "check_bad:extra_key"),
    ("extra_key_stage", _stage_extra, "check_bad:extra_key"),
    ("extra_key_test", _test_extra, "check_bad:extra_key"),
    ("missing_key_top", _top_missing, "check_bad:missing_key"),
    ("missing_key_test", _test_missing, "check_bad:missing_key"),
    ("missing_key_parent", _test_no_parent, "check_bad:missing_key"),
    ("value_bad_two_parents", _test_two_parents, "check_bad:value_bad"),
    ("value_bad_empty_basis", _empty_basis, "check_bad:value_bad"),
    ("value_bad_scan_paths", _scan_paths_bad, "check_bad:value_bad"),
    ("value_bad_source_path", _source_path_bad, "check_bad:value_bad"),
    ("class_bad_stage", _class_bad, "check_bad:class_bad"),
    ("class_bad_test", _test_class_bad, "check_bad:class_bad"),
    (
        "stage_source_unreadable_name",
        _source_name_bad,
        "check_bad:stage_source_unreadable",
    ),
    (
        "stage_source_unreadable_syntax",
        _source_syntax_bad,
        "check_bad:stage_source_unreadable",
    ),
    (
        "stage_source_unreadable_values",
        _source_not_strings,
        "check_bad:stage_source_unreadable",
    ),
    ("stage_missing", _stage_missing, "check_bad:stage_missing:Lint"),
    ("stage_unknown", _stage_unknown, "check_bad:stage_unknown:Extra"),
    (
        "entry_parent_bad",
        _parent_bad,
        f"check_bad:entry_parent_bad:{UNIT_FILE}::test_win_only",
    ),
    (
        "entry_duplicate",
        _duplicate,
        f"check_bad:entry_duplicate:{UNIT_FILE}::test_win_only",
    ),
    (
        "entry_same_class_suite",
        _same_class,
        f"check_bad:entry_same_class:{SPEC_FILE}::Demo suite",
    ),
    (
        "entry_same_class_ancestor",
        _same_class_ancestor,
        f"check_bad:entry_same_class:{SPEC_FILE}::Demo suite::posix sibling",
    ),
    (
        "entry_target_missing",
        _target_missing,
        f"check_bad:entry_target_missing:{UNIT_FILE}::test_gone",
    ),
    (
        "entry_target_missing_file",
        _target_file_missing,
        "check_bad:entry_target_missing:tests/unit/test_absent.py::test_win_only",
    ),
    (
        "entry_target_missing_title",
        _suite_title_missing,
        f"check_bad:entry_target_missing:{SPEC_FILE}::No such suite",
    ),
    (
        "condition_mismatch",
        _condition_mismatch,
        f"check_bad:condition_mismatch:{UNIT_FILE}::test_win_only",
    ),
    (
        "condition_mismatch_suite",
        _suite_condition_mismatch,
        f"check_bad:condition_mismatch:{SPEC_FILE}::Demo suite",
    ),
    (
        "condition_unknown",
        _condition_unknown,
        f"check_bad:condition_unknown:{UNIT_FILE}::test_win_only",
    ),
    (
        "condition_class",
        _condition_class,
        f"check_bad:condition_class:{UNIT_FILE}::test_win_only",
    ),
    (
        "scan_unlisted",
        _scan_unlisted,
        f"check_bad:scan_unlisted:{UNIT_FILE}::test_posix_only",
    ),
    ("scan_stale", _scan_stale, f"check_bad:scan_stale:{INT_FILE}"),
    ("suite_path_missing", _suite_path_missing, "check_bad:suite_path_missing:e2e"),
]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [(m, e) for _, m, e in FAULTS],
    ids=[n for n, _, _ in FAULTS],
)
def test_ag1_ac_947_7_each_fault_gives_exit_1_and_its_reason(
    tmp_path: Path, mutate: Mutation, expected: str
) -> None:
    """Each structure and content fault gives exit 1, its reason line, and writes nothing."""
    repo = _make_fixture(tmp_path)
    data = mutate(repo, _fixture_data())
    if data is not None:
        _write_data(repo, data)
    before = _tree_hash(repo)
    done = _run("check", "--repo", str(repo))
    after = _tree_hash(repo)
    assert done.returncode == 1, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert any(line == expected or line.startswith(expected + " ") for line in lines), (
        lines
    )
    assert all(line.startswith("check_bad:") for line in lines), lines
    assert after == before


def test_ag1_ac_947_7_a_structure_fault_skips_the_content_checks(
    tmp_path: Path,
) -> None:
    """A structure fault is reported alone: the content checks do not run on bad data."""
    repo = _make_fixture(tmp_path)
    data = _fixture_data()
    data["schema"] = "gate-platform/2"
    del _stages_of(data)["Lint"]
    _write_data(repo, data)
    done = _run("check", "--repo", str(repo))
    assert done.returncode == 1, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert any(line.startswith("check_bad:schema_bad") for line in lines), lines
    assert not any(line.startswith("check_bad:stage_missing") for line in lines), lines


def test_ag1_ac_947_7_an_explicit_classes_path_is_read(tmp_path: Path) -> None:
    """``--classes`` names another data file, read relative to ``--repo``."""
    repo = _make_fixture(tmp_path)
    data = _fixture_data()
    _write(repo / "alt" / "classes.json", json.dumps(data))
    (repo / "tools" / "gate_platform_classes.json").unlink()
    done = _run("check", "--repo", str(repo), "--classes", "alt/classes.json")
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip() == "check_ok stages=3 tests=7 suites=1"


# --------------------------------------------------------------------------- R1 regressions
# The R1-F1 SCAN statement-block tests and the R1-F2 order tests (MEU-947 review round 1).

CONDITIONAL_WIN = (
    '@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")\n'
    "def test_conditional_win():\n"
    "    pass\n"
)


def _indent(text: str, prefix: str = "    ") -> str:
    """``text`` with every non-empty line indented by ``prefix``."""
    return "".join(
        prefix + line if line.strip() else line for line in text.splitlines(True)
    )


def _check(repo: Path) -> tuple[int, list[str]]:
    """Run ``check --repo <repo>``; return the exit code and the stdout lines."""
    done = _run("check", "--repo", str(repo))
    return done.returncode, done.stdout.splitlines() + done.stderr.splitlines()


def _with_unit_tail(repo: Path, tail: str) -> None:
    """Append ``tail`` to the fixture's unit test file."""
    _write(repo / UNIT_FILE, FIXTURE_UNIT + "\n\n" + tail)


def _entry(test_id: str, cls: str, condition: str) -> dict[str, str]:
    """One Unit Tests entry of the fixture data."""
    return {
        "id": test_id,
        "stage": "Unit Tests",
        "class": cls,
        "condition": condition,
        "basis": "fixture basis",
    }


# --------------------------------------------------------------------------- R1-F1

CONTAINERS: dict[str, str] = {
    "if_body": "if True:\n" + _indent(CONDITIONAL_WIN),
    "if_else": "if False:\n    pass\nelse:\n" + _indent(CONDITIONAL_WIN),
    "elif": "if False:\n    pass\nelif True:\n" + _indent(CONDITIONAL_WIN),
    "try_body": "try:\n" + _indent(CONDITIONAL_WIN) + "except ImportError:\n    pass\n",
    "try_handler": "try:\n    import os\nexcept ImportError:\n"
    + _indent(CONDITIONAL_WIN),
    "try_else": "try:\n    import os\nexcept ImportError:\n    pass\nelse:\n"
    + _indent(CONDITIONAL_WIN),
    "try_finally": "try:\n    import os\nfinally:\n" + _indent(CONDITIONAL_WIN),
    "with": "import contextlib\n\nwith contextlib.suppress(ImportError):\n"
    + _indent(CONDITIONAL_WIN),
    "for": "for _once in (1,):\n" + _indent(CONDITIONAL_WIN),
    "while": "while True:\n" + _indent(CONDITIONAL_WIN) + "    break\n",
    "match": "match 1:\n    case _:\n" + _indent(CONDITIONAL_WIN, "        "),
    "nested": "if True:\n    try:\n"
    + _indent(CONDITIONAL_WIN, "        ")
    + "    except ImportError:\n        pass\n",
}


@pytest.mark.parametrize("container", sorted(CONTAINERS))
def test_ag1_r1_f1_a_mark_in_a_statement_block_is_scanned(
    tmp_path: Path, container: str
) -> None:
    """An unlisted platform mark in a module statement block gives ``scan_unlisted``."""
    repo = _make_fixture(tmp_path)
    _with_unit_tail(repo, CONTAINERS[container])
    code, lines = _check(repo)
    assert code == 1, lines
    assert f"check_bad:scan_unlisted:{UNIT_FILE}::test_conditional_win" in lines


@pytest.mark.parametrize("container", sorted(CONTAINERS))
def test_ag1_r1_f1_a_listed_mark_in_a_statement_block_passes(
    tmp_path: Path, container: str
) -> None:
    """The same mark with its entry passes: the target lookup finds the definition."""
    repo = _make_fixture(tmp_path)
    _with_unit_tail(repo, CONTAINERS[container])
    data: dict[str, Any] = _fixture_data()
    data["tests"].append(
        _entry(
            f"{UNIT_FILE}::test_conditional_win",
            "windows",
            "sys.platform != 'win32'",
        )
    )
    _write_data(repo, data)
    code, lines = _check(repo)
    assert code == 0, lines
    assert lines == ["check_ok stages=3 tests=8 suites=1"]


CLASS_BLOCKS = (
    "if True:\n"
    "    class TestCond:\n"
    "        if True:\n"
    '            pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")\n'
    "\n"
    "        def test_x(self):\n"
    "            pass\n"
    "\n"
    "\n"
    "class TestBlockMethod:\n"
    "    try:\n"
    '        @pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")\n'
    "        def test_y(self):\n"
    "            pass\n"
    "    except ImportError:\n"
    "        pass\n"
)


def test_ag1_r1_f1_class_marks_and_methods_in_blocks_are_scanned(
    tmp_path: Path,
) -> None:
    """A conditional class ``pytestmark`` and a method in a class block keep their class id."""
    repo = _make_fixture(tmp_path)
    _with_unit_tail(repo, CLASS_BLOCKS)
    code, lines = _check(repo)
    assert code == 1, lines
    assert f"check_bad:scan_unlisted:{UNIT_FILE}::TestCond" in lines
    assert f"check_bad:scan_unlisted:{UNIT_FILE}::TestBlockMethod::test_y" in lines
    assert f"check_bad:scan_unlisted:{UNIT_FILE}::test_y" not in lines
    assert f"check_bad:scan_unlisted:{UNIT_FILE}::TestCond::test_x" not in lines


def test_ag1_r1_f1_listed_class_blocks_pass(tmp_path: Path) -> None:
    """With both entries listed, the class-block fixture passes ``check``."""
    repo = _make_fixture(tmp_path)
    _with_unit_tail(repo, CLASS_BLOCKS)
    data: dict[str, Any] = _fixture_data()
    data["tests"] += [
        _entry(f"{UNIT_FILE}::TestCond", "windows", "sys.platform != 'win32'"),
        _entry(
            f"{UNIT_FILE}::TestBlockMethod::test_y",
            "linux",
            "sys.platform == 'win32'",
        ),
    ]
    _write_data(repo, data)
    code, lines = _check(repo)
    assert code == 0, lines
    assert lines == ["check_ok stages=3 tests=9 suites=1"]


def test_ag1_r1_f1_a_conditional_module_pytestmark_is_scanned(tmp_path: Path) -> None:
    """A module ``pytestmark`` inside an ``if`` block gives ``scan_unlisted:<path>``."""
    repo = _make_fixture(tmp_path)
    rel = "tests/unit/test_cond_module.py"
    _write(
        repo / rel,
        "import sys\n\nimport pytest\n\nif True:\n"
        '    pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")\n'
        "\n\ndef test_z():\n    pass\n",
    )
    code, lines = _check(repo)
    assert code == 1, lines
    assert f"check_bad:scan_unlisted:{rel}" in lines


def test_ag1_r1_f1_a_function_local_definition_is_not_scanned(tmp_path: Path) -> None:
    """A marked definition inside a function body is not collected and is not reported."""
    repo = _make_fixture(tmp_path)
    _with_unit_tail(
        repo,
        "def test_outer():\n"
        "    if True:\n"
        '        @pytest.mark.skipif(sys.platform != "win32", reason="local")\n'
        "        def test_local():\n"
        "            pass\n",
    )
    code, lines = _check(repo)
    assert code == 0, lines
    assert lines == ["check_ok stages=3 tests=7 suites=1"]


# --------------------------------------------------------------------------- R1-F2


def _spec_entries(data: dict[str, Any]) -> tuple[int, int]:
    """The list positions of the two spec entries (parent, child) in ``data``."""
    ids = [entry["id"] for entry in data["tests"]]
    return (
        ids.index(f"{SPEC_FILE}::Demo suite"),
        ids.index(f"{SPEC_FILE}::Demo suite::posix sibling"),
    )


def _ordered(data: dict[str, Any], child_first: bool) -> dict[str, Any]:
    """A copy of ``data`` with the spec child before its parent when ``child_first``."""
    out = copy.deepcopy(data)
    parent, child = _spec_entries(out)
    if child_first:
        out["tests"][parent], out["tests"][child] = (
            out["tests"][child],
            out["tests"][parent],
        )
    return out


@pytest.mark.parametrize(
    "child_first", [False, True], ids=["parent_first", "child_first"]
)
def test_ag1_r1_f2_a_valid_override_passes_in_both_orders(
    tmp_path: Path, child_first: bool
) -> None:
    """Suite ``linux``, parent ``windows``, child ``linux``: valid in either list order."""
    repo = _make_fixture(tmp_path)
    data: dict[str, Any] = _fixture_data()
    data["suites"]["e2e"]["class"] = "linux"
    _write_data(repo, _ordered(data, child_first))
    code, lines = _check(repo)
    assert code == 0, lines
    assert lines == ["check_ok stages=3 tests=7 suites=1"]


@pytest.mark.parametrize(
    "child_first", [False, True], ids=["parent_first", "child_first"]
)
def test_ag1_r1_f2_a_redundant_child_refuses_in_both_orders(
    tmp_path: Path, child_first: bool
) -> None:
    """A child with its listed parent's class gives ``entry_same_class`` in either order."""
    repo = _make_fixture(tmp_path)
    data: dict[str, Any] = _fixture_data()
    _parent, child = _spec_entries(data)
    data["tests"][child]["class"] = "windows"
    _write_data(repo, _ordered(data, child_first))
    code, lines = _check(repo)
    assert code == 1, lines
    child_id = f"{SPEC_FILE}::Demo suite::posix sibling"
    assert f"check_bad:entry_same_class:{child_id}" in lines
    assert f"check_bad:entry_same_class:{SPEC_FILE}::Demo suite" not in lines
