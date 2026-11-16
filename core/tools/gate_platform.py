"""Gate platform classes: which OS can run each stage of the full gate, and which tests differ.

The data file (schema ``gate-platform/1``) gives each stage of the gate's stage
tuple one class (``windows``, ``linux`` or ``any``), each test suite one class,
and each test whose class differs from its stage or suite, by id. The tool reads
the stage tuple from the gate source with ``ast`` and never imports that file.
It writes no file.

Verbs:

* ``show --json`` checks the structure and the stage set, then prints the data.
* ``check`` runs every check and prints ``check_ok stages=<n> tests=<n> suites=<n>``.

Exit codes: 0 pass; 1 with one ``<verb>_bad:<reason>`` line per fault; 2 a usage
error. A pytest test is found by ``SCAN``: a ``skipif`` or ``xfail`` mark on a
function or class, or in a module or class ``pytestmark``, whose condition names
``sys.platform``, ``os.name`` or ``platform.system``.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import NotRequired, TypedDict, cast

SCHEMA = "gate-platform/1"
CLASSES = ("windows", "linux", "any")
DEFAULT_CLASSES = "tools/gate_platform_classes.json"
DESCRIPTION = (
    "Gate platform classes: which OS can run each gate stage, and which tests differ."
)

TOP_KEYS = ("schema", "stage_source", "stages", "suites", "tests")
SOURCE_KEYS = ("path", "name")
STAGE_KEYS = ("class", "basis")
STAGE_OPTIONAL = ("scan_paths",)
SUITE_KEYS = ("path", "ci_job", "class", "basis")
TEST_KEYS = ("id", "class", "condition", "basis")
TEST_PARENTS = ("stage", "suite")

#: The mark names that SCAN reads.
MARKS = frozenset({"skipif", "xfail"})
#: The platform expression and the Windows literal it is compared with.
PLATFORM_LITERALS = {
    "sys.platform": "win32",
    "os.name": "nt",
    "platform.system()": "Windows",
}
#: The quote characters around a suite title in a spec file.
QUOTES = ("'", '"', "`")


class StageSource(TypedDict):
    """The file and the module-level tuple that name the gate stages."""

    path: str
    name: str


# ``class`` is a Python keyword, so the TypedDicts with a ``class`` key use the
# functional form.
Stage = TypedDict(
    "Stage",
    {"class": str, "basis": str, "scan_paths": NotRequired[list[str]]},
)
Suite = TypedDict("Suite", {"path": str, "ci_job": str, "class": str, "basis": str})
Entry = TypedDict(
    "Entry",
    {
        "id": str,
        "class": str,
        "condition": str,
        "basis": str,
        "stage": NotRequired[str],
        "suite": NotRequired[str],
    },
)


class Data(TypedDict):
    """The checked content of the data file."""

    schema: str
    stage_source: StageSource
    stages: dict[str, Stage]
    suites: dict[str, Suite]
    tests: list[Entry]


class DataError(Exception):
    """The data file fails the structure checks; ``faults`` holds one reason line each."""

    def __init__(self, faults: list[str]) -> None:
        """Keep the reason lines of the structure faults."""
        super().__init__("; ".join(faults))
        self.faults = faults


class SourceError(Exception):
    """The stage tuple cannot be read from the gate source."""


class ScanError(Exception):
    """A scan path is missing, or a scanned file cannot be read or parsed."""


# --------------------------------------------------------------------------- structure


def _is_text(value: object) -> bool:
    """True when ``value`` is a non-empty string."""
    return isinstance(value, str) and value != ""


def _is_rel_path(value: object) -> bool:
    """True when ``value`` is a non-empty relative POSIX path with no ``..`` part."""
    if not _is_text(value):
        return False
    text = cast(str, value)
    path = PurePosixPath(text)
    return (
        "\\" not in text
        and not path.is_absolute()
        and ":" not in text
        and ".." not in path.parts
    )


def _keys(
    where: str,
    value: Mapping[str, object],
    required: Sequence[str],
    optional: Sequence[str],
) -> list[str]:
    """The ``missing_key`` and ``extra_key`` faults of one object."""
    faults = [f"missing_key {where}.{key}" for key in required if key not in value]
    allowed = set(required) | set(optional)
    faults += [f"extra_key {where}.{key}" for key in value if key not in allowed]
    return faults


def _text_fields(
    where: str, value: Mapping[str, object], fields: Sequence[str]
) -> list[str]:
    """The ``value_bad`` faults of the string fields of one object."""
    return [
        f"value_bad {where}.{key} is not a non-empty string"
        for key in fields
        if key in value and not _is_text(value[key])
    ]


def _class_field(where: str, value: Mapping[str, object]) -> list[str]:
    """The ``class_bad`` fault of one object whose ``class`` is a string."""
    cls = value.get("class")
    if _is_text(cls) and cls not in CLASSES:
        return [f"class_bad {where}.class {cls!r} is not one of {', '.join(CLASSES)}"]
    return []


def _object(value: object) -> Mapping[str, object] | None:
    """``value`` as a string-keyed mapping, or None when it is not a JSON object."""
    if isinstance(value, dict):
        return cast(Mapping[str, object], value)
    return None


def _check_source(value: object) -> list[str]:
    """The structure faults of ``stage_source``."""
    source = _object(value)
    if source is None:
        return ["value_bad stage_source is not an object"]
    faults = _keys("stage_source", source, SOURCE_KEYS, ())
    faults += _text_fields("stage_source", source, SOURCE_KEYS)
    if _is_text(source.get("path")) and not _is_rel_path(source.get("path")):
        faults.append("value_bad stage_source.path is not a relative path")
    return faults


def _check_stages(value: object) -> list[str]:
    """The structure faults of ``stages``."""
    stages = _object(value)
    if stages is None or not stages:
        return ["value_bad stages is not a non-empty object"]
    faults: list[str] = []
    for name, raw in stages.items():
        where = f"stages[{name!r}]"
        if not _is_text(name):
            faults.append(f"value_bad {where} has an empty name")
        stage = _object(raw)
        if stage is None:
            faults.append(f"value_bad {where} is not an object")
            continue
        faults += _keys(where, stage, STAGE_KEYS, STAGE_OPTIONAL)
        faults += _text_fields(where, stage, STAGE_KEYS)
        faults += _class_field(where, stage)
        if "scan_paths" in stage:
            paths = stage["scan_paths"]
            if not isinstance(paths, list) or not paths:
                faults.append(f"value_bad {where}.scan_paths is not a non-empty list")
            elif not all(_is_rel_path(p) for p in cast(list[object], paths)):
                faults.append(
                    f"value_bad {where}.scan_paths holds a value that is not a relative path"
                )
    return faults


def _check_suites(value: object) -> list[str]:
    """The structure faults of ``suites``."""
    suites = _object(value)
    if suites is None:
        return ["value_bad suites is not an object"]
    faults: list[str] = []
    for name, raw in suites.items():
        where = f"suites[{name!r}]"
        if not _is_text(name):
            faults.append(f"value_bad {where} has an empty name")
        suite = _object(raw)
        if suite is None:
            faults.append(f"value_bad {where} is not an object")
            continue
        faults += _keys(where, suite, SUITE_KEYS, ())
        faults += _text_fields(where, suite, SUITE_KEYS)
        faults += _class_field(where, suite)
        if _is_text(suite.get("path")) and not _is_rel_path(suite.get("path")):
            faults.append(f"value_bad {where}.path is not a relative path")
    return faults


def _check_tests(value: object) -> list[str]:
    """The structure faults of ``tests``."""
    if not isinstance(value, list):
        return ["value_bad tests is not a list"]
    faults: list[str] = []
    for index, raw in enumerate(cast(list[object], value)):
        where = f"tests[{index}]"
        entry = _object(raw)
        if entry is None:
            faults.append(f"value_bad {where} is not an object")
            continue
        faults += _keys(where, entry, TEST_KEYS, TEST_PARENTS)
        parents = [key for key in TEST_PARENTS if key in entry]
        if not parents:
            faults.append(f"missing_key {where}.stage|suite")
        elif len(parents) > 1:
            faults.append(f"value_bad {where} has both stage and suite")
        faults += _text_fields(where, entry, (*TEST_KEYS, *TEST_PARENTS))
        faults += _class_field(where, entry)
        entry_id = entry.get("id")
        if _is_text(entry_id) and not _is_rel_path(
            cast(str, entry_id).split("::", 1)[0]
        ):
            faults.append(f"value_bad {where}.id does not start with a relative path")
    return faults


def _load(path: Path) -> Data:
    """Read and structure-check the data file at ``path``.

    Raises:
        DataError: the file is unreadable or fails a structure check; the error
            holds one reason line per fault.
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise DataError(
            [f"classes_unreadable {path.as_posix()}: {exc.__class__.__name__}"]
        ) from exc
    except json.JSONDecodeError as exc:
        raise DataError(
            [f"classes_unreadable {path.as_posix()}: {exc.msg} at line {exc.lineno}"]
        ) from exc
    top = _object(raw)
    if top is None:
        raise DataError(["value_bad the data file is not a JSON object"])
    faults = _keys("data", top, TOP_KEYS, ())
    if "schema" in top and top["schema"] != SCHEMA:
        faults.append(f"schema_bad {top['schema']!r} is not {SCHEMA!r}")
    if "stage_source" in top:
        faults += _check_source(top["stage_source"])
    if "stages" in top:
        faults += _check_stages(top["stages"])
    if "suites" in top:
        faults += _check_suites(top["suites"])
    if "tests" in top:
        faults += _check_tests(top["tests"])
    if faults:
        raise DataError(faults)
    return cast(Data, top)


# --------------------------------------------------------------------------- stage source


def _stage_names(repo: Path, source: Mapping[str, object]) -> tuple[str, ...]:
    """The stage names of the module-level tuple that ``source`` names, read by ``ast``.

    ``source`` is a ``stage_source`` object: ``path`` (relative to ``repo``) and
    ``name``. The file is parsed, never imported. The assignment may be plain or
    annotated.

    Raises:
        SourceError: ``source`` lacks a string ``path`` or ``name``, the file is
            missing or unparsable, the name is not assigned at module level, or
            its value is not a non-empty tuple of strings.
    """
    rel, name = source.get("path"), source.get("name")
    if not (isinstance(rel, str) and rel and isinstance(name, str) and name):
        raise SourceError("stage_source needs a string path and name")
    path = repo / rel
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise SourceError(f"{rel}: {exc.__class__.__name__}") from exc
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if not (isinstance(target, ast.Name) and target.id == name) or value is None:
            continue
        try:
            names: object = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError, RecursionError) as exc:
            raise SourceError(f"{name} is not a literal") from exc
        if (
            isinstance(names, tuple)
            and names
            and all(isinstance(n, str) and n for n in cast(tuple[object, ...], names))
        ):
            return cast(tuple[str, ...], names)
        raise SourceError(f"{name} is not a non-empty tuple of strings")
    raise SourceError(f"{rel} assigns no module-level {name}")


# --------------------------------------------------------------------------- SCAN


def _dotted(node: ast.expr) -> str | None:
    """``a.b`` for an attribute of a plain name, ``a.b()`` for a call of one with no arguments."""
    if isinstance(node, ast.Call) and not node.args and not node.keywords:
        inner = _dotted(node.func)
        return f"{inner}()" if inner is not None and not inner.endswith(")") else None
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _names_platform(node: ast.expr) -> bool:
    """True when the condition ``node`` names ``sys.platform``, ``os.name`` or ``platform.system``."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
            if (sub.value.id, sub.attr) in {
                ("sys", "platform"),
                ("os", "name"),
                ("platform", "system"),
            }:
                return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if any(
                name in sub.value
                for name in ("sys.platform", "os.name", "platform.system")
            ):
                return True
    return False


def _condition_class(node: ast.expr) -> str | None:
    """The class that the platform condition ``node`` gives, or None for any other form.

    ``X != W`` gives ``windows`` (the test skips off Windows) and ``X == W`` gives
    ``linux``, where ``X`` is ``sys.platform``, ``os.name`` or ``platform.system()``
    and ``W`` is its Windows literal (``'win32'``, ``'nt'`` or ``'Windows'``), on
    either side.
    """
    if not (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and len(node.comparators) == 1
    ):
        return None
    left, right = node.left, node.comparators[0]
    for platform_side, literal_side in ((left, right), (right, left)):
        expr = _dotted(platform_side)
        if expr is None or expr not in PLATFORM_LITERALS:
            continue
        if (
            isinstance(literal_side, ast.Constant)
            and literal_side.value == PLATFORM_LITERALS[expr]
        ):
            if isinstance(node.ops[0], ast.NotEq):
                return "windows"
            if isinstance(node.ops[0], ast.Eq):
                return "linux"
    return None


def _mark_condition(node: ast.expr) -> ast.expr | None:
    """The condition of a ``skipif`` or ``xfail`` mark call when it names a platform, else None."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = (
        func.attr
        if isinstance(func, ast.Attribute)
        else func.id
        if isinstance(func, ast.Name)
        else None
    )
    if name not in MARKS:
        return None
    condition: ast.expr | None = node.args[0] if node.args else None
    for keyword in node.keywords:
        if keyword.arg == "condition":
            condition = keyword.value
    if condition is None or not _names_platform(condition):
        return None
    return condition


def _blocks(node: ast.stmt) -> list[list[ast.stmt]]:
    """The statement blocks of one ``if``, ``for``, ``while``, ``with``, ``try`` or ``match``.

    Any other statement has no block here: a function or class body is a new
    scope, which the caller walks under its own id or not at all.
    """
    if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        return [node.body, node.orelse]
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return [node.body]
    if isinstance(node, (ast.Try, ast.TryStar)):
        return [
            node.body,
            *(handler.body for handler in node.handlers),
            node.orelse,
            node.finalbody,
        ]
    if isinstance(node, ast.Match):
        return [case.body for case in node.cases]
    return []


def _flat(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    """The statements of one scope: ``body`` and its statement blocks, in source order.

    A definition in an ``if``, ``try``, ``with``, ``for``, ``while`` or ``match``
    block binds in the same module or class namespace, so pytest collects it.
    The body of a function or class is never entered.
    """
    for node in body:
        yield node
        for block in _blocks(node):
            yield from _flat(block)


def _pytestmark(body: Sequence[ast.stmt]) -> list[ast.expr]:
    """The platform conditions of a ``pytestmark`` assignment in the scope ``body``."""
    found: list[ast.expr] = []
    for node in _flat(body):
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            not (isinstance(target, ast.Name) and target.id == "pytestmark")
            or value is None
        ):
            continue
        marks = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
        found += [c for c in (_mark_condition(m) for m in marks) if c is not None]
    return found


def _record(out: dict[str, str], node_id: str, conditions: list[ast.expr]) -> None:
    """Record the condition text of ``node_id``; two or more marks join with ``and``."""
    if not conditions:
        return
    if len(conditions) == 1:
        out[node_id] = ast.unparse(conditions[0])
    else:
        out[node_id] = ast.unparse(ast.BoolOp(op=ast.And(), values=conditions))


def _walk(body: Sequence[ast.stmt], prefix: str, out: dict[str, str]) -> None:
    """Record the platform marks of the functions and classes of the scope ``body`` under ``prefix``."""
    for node in _flat(body):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        node_id = f"{prefix}::{node.name}"
        conditions = [
            c
            for c in (_mark_condition(d) for d in node.decorator_list)
            if c is not None
        ]
        if isinstance(node, ast.ClassDef):
            conditions += _pytestmark(node.body)
            _walk(node.body, node_id, out)
        _record(out, node_id, conditions)


def _scan_file(repo: Path, path: Path) -> dict[str, str]:
    """The SCAN findings of one Python file.

    Raises:
        ScanError: the file cannot be read or parsed.
    """
    rel = path.relative_to(repo).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ScanError(rel) from exc
    if not any(mark in text for mark in MARKS):
        return {}
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        raise ScanError(rel) from exc
    out: dict[str, str] = {}
    _record(out, rel, _pytestmark(tree.body))
    _walk(tree.body, rel, out)
    return out


def _scan(repo: Path, paths: Sequence[str]) -> dict[str, str]:
    """SCAN: the id of each platform-marked test under ``paths``, mapped to its condition text.

    Ids are ``<path>``, ``<path>::<func>``, ``<path>::<Class>`` and
    ``<path>::<Class>::<method>``; the text is ``ast.unparse`` of the condition.

    Raises:
        ScanError: a path does not exist, or a file under it cannot be read or parsed.
    """
    out: dict[str, str] = {}
    for rel in paths:
        root = repo / rel
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = sorted(root.rglob("*.py"))
        else:
            raise ScanError(rel)
        for path in files:
            out.update(_scan_file(repo, path))
    return out


# --------------------------------------------------------------------------- content checks


def _stage_set(repo: Path, data: Data) -> list[str]:
    """The ``stage_source_unreadable``, ``stage_missing`` and ``stage_unknown`` faults."""
    try:
        names = _stage_names(repo, data["stage_source"])
    except SourceError as exc:
        return [f"stage_source_unreadable {exc}"]
    faults = [f"stage_missing:{name}" for name in names if name not in data["stages"]]
    faults += [f"stage_unknown:{name}" for name in data["stages"] if name not in names]
    return faults


def _ast_target(tree: ast.Module, names: Sequence[str]) -> bool:
    """True when the nested class and function ``names`` exist in ``tree``.

    Each name is looked up in one scope with its statement blocks (``_flat``).
    """
    body: Sequence[ast.stmt] = tree.body
    for name in names:
        match = next(
            (
                n
                for n in _flat(body)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.name == name
            ),
            None,
        )
        if match is None:
            return False
        body = match.body if isinstance(match, ast.ClassDef) else []
    return True


def _parent_class(entry: Entry, listed: Mapping[str, str], data: Data) -> str:
    """The class of the entry's parent: the nearest listed ancestor id, else its stage or suite.

    ``listed`` maps every entry id of ``data`` to its class, so the result does
    not depend on the order of the ``tests`` list.
    """
    parts = entry["id"].split("::")
    for size in range(len(parts) - 1, 0, -1):
        ancestor = "::".join(parts[:size])
        if ancestor in listed:
            return listed[ancestor]
    stage_name = entry.get("stage")
    if stage_name is not None:
        return data["stages"][stage_name]["class"]
    return data["suites"][entry.get("suite", "")]["class"]


def _check_pytest_entry(
    repo: Path,
    entry: Entry,
    scanned: bool,
    findings: dict[str, dict[str, str]],
) -> list[str]:
    """The target and condition faults of one pytest (stage) entry."""
    entry_id = entry["id"]
    file_rel, *names = entry_id.split("::")
    path = repo / file_rel
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return [f"entry_target_missing:{entry_id}"]
    if not _ast_target(tree, names):
        return [f"entry_target_missing:{entry_id}"]
    if file_rel not in findings:
        try:
            findings[file_rel] = _scan_file(repo, path)
        except ScanError:
            return [f"entry_target_missing:{entry_id}"]
    text = findings[file_rel].get(entry_id)
    if text is None:
        return [
            f"scan_stale:{entry_id}" if scanned else f"condition_mismatch:{entry_id}"
        ]
    if entry["condition"] != text:
        return [f"condition_mismatch:{entry_id}"]
    cls = _condition_class(ast.parse(text, mode="eval").body)
    if cls is None:
        return [] if scanned else [f"condition_unknown:{entry_id}"]
    if cls != entry["class"]:
        return [f"condition_class:{entry_id}"]
    return []


def _check_suite_entry(repo: Path, entry: Entry) -> list[str]:
    """The target and condition faults of one suite (spec title) entry."""
    entry_id = entry["id"]
    file_rel, *titles = entry_id.split("::")
    try:
        text = (repo / file_rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [f"entry_target_missing:{entry_id}"]
    if not titles or not all(any(f"{q}{t}{q}" in text for q in QUOTES) for t in titles):
        return [f"entry_target_missing:{entry_id}"]
    if entry["condition"] not in text:
        return [f"condition_mismatch:{entry_id}"]
    return []


def _check(repo: Path, data: Data) -> list[str]:
    """Every content fault of the structure-checked ``data`` against the project at ``repo``."""
    faults = _stage_set(repo, data)
    faults += [
        f"suite_path_missing:{name}"
        for name, suite in data["suites"].items()
        if not (repo / suite["path"]).is_file()
    ]
    stage_scans: dict[str, dict[str, str]] = {}
    for name, stage in data["stages"].items():
        if "scan_paths" not in stage:
            continue
        try:
            stage_scans[name] = _scan(repo, stage["scan_paths"])
        except ScanError as exc:
            faults.append(f"scan_unreadable:{exc}")
            stage_scans[name] = {}
    listed: dict[str, str] = {}
    for entry in data["tests"]:
        listed.setdefault(entry["id"], entry["class"])
    seen: set[str] = set()
    by_stage: dict[str, set[str]] = {}
    findings: dict[str, dict[str, str]] = {}
    for entry in data["tests"]:
        entry_id = entry["id"]
        if entry_id in seen:
            faults.append(f"entry_duplicate:{entry_id}")
            continue
        seen.add(entry_id)
        stage_name = entry.get("stage")
        suite_name = entry.get("suite")
        if (stage_name is not None and stage_name not in data["stages"]) or (
            suite_name is not None and suite_name not in data["suites"]
        ):
            faults.append(f"entry_parent_bad:{entry_id}")
            continue
        if _parent_class(entry, listed, data) == entry["class"]:
            faults.append(f"entry_same_class:{entry_id}")
        if stage_name is not None:
            by_stage.setdefault(stage_name, set()).add(entry_id)
            faults += _check_pytest_entry(
                repo, entry, stage_name in stage_scans, findings
            )
        else:
            faults += _check_suite_entry(repo, entry)
    for name, found in stage_scans.items():
        for finding_id, text in found.items():
            if _condition_class(ast.parse(text, mode="eval").body) is None:
                faults.append(f"condition_unknown:{finding_id}")
            if finding_id not in by_stage.get(name, set()):
                faults.append(f"scan_unlisted:{finding_id}")
    return faults


# --------------------------------------------------------------------------- command line


def _parser() -> argparse.ArgumentParser:
    """The command-line parser: ``show --json`` and ``check``, each with ``--repo`` and ``--classes``."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--repo", default=".", help="the project root (default: the current directory)"
    )
    common.add_argument(
        "--classes",
        default=DEFAULT_CLASSES,
        help=f"the data file, relative to --repo when relative (default: {DEFAULT_CLASSES})",
    )
    parser = argparse.ArgumentParser(prog="gate_platform.py", description=DESCRIPTION)
    verbs = parser.add_subparsers(dest="verb", required=True)
    show = verbs.add_parser(
        "show", parents=[common], help="print the classes as JSON (read-only)"
    )
    show.add_argument(
        "--json", action="store_true", required=True, help="print JSON (required)"
    )
    verbs.add_parser(
        "check",
        parents=[common],
        help="fail on a stage with no class or a stale test list",
    )
    return parser


def _emit(lines: Sequence[str]) -> None:
    """Print ``lines`` to standard output as UTF-8."""
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    for line in lines:
        print(line)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one verb and return its exit code (0 pass, 1 faults; argparse exits 2 on a usage error)."""
    args = _parser().parse_args(argv)
    verb = cast(str, args.verb)
    repo = Path(cast(str, args.repo)).resolve()
    classes = Path(cast(str, args.classes))
    if not classes.is_absolute():
        classes = repo / classes
    try:
        data = _load(classes)
    except DataError as exc:
        _emit([f"{verb}_bad:{fault}" for fault in exc.faults])
        return 1
    faults = _stage_set(repo, data) if verb == "show" else _check(repo, data)
    if faults:
        _emit([f"{verb}_bad:{fault}" for fault in faults])
        return 1
    if verb == "show":
        _emit([json.dumps(data, indent=1, ensure_ascii=False)])
    else:
        _emit(
            [
                f"check_ok stages={len(data['stages'])} tests={len(data['tests'])} suites={len(data['suites'])}"
            ]
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
