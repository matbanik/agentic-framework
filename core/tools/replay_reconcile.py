"""The reconcile step of a land: a reconciler joins two sessions that changed one file.

MEU-952 (plan ``2026-11-11-ag4-pilot-c-reconcile-crash-states``, design §9.4). When
``lanes.py land replay`` of a run stops on a text conflict with a run that landed after
the run's base, lanes writes ``<git common dir>/{{PROJECT_NAME}}-results/<run>/reconcile-request.json``
with exactly the keys ``base`` (P, the main ``HEAD``), ``sides`` (the landed run, then this
run) and ``paths`` (the conflict paths). This tool reads that request:

* ``brief --request <file>`` writes ``reconcile-brief.json`` (``reconcile-brief/1``) beside
  the request: the base, the paths and each side's run, session, author vendor, base,
  commit, handoffs, intents (the ``implementation-plan.md`` of each changed plan folder)
  and test ids (the ``<file>::<test>`` ids of each changed ``test_*.py``). It prints
  ``reconcile_brief <path>``.
* ``prepare --request <file> --clone <clone>`` writes the change set of the second side
  into a scratch clone at P: the side's bytes where P still has the side's base bytes,
  else the ``git merge-file`` result with its conflict markers. It records the prepared
  bytes in ``reconcile-prepared.json`` beside the request and prints
  ``reconcile_prepared <clone> conflicts=<n>``.
* ``check --request <file> --clone <clone>`` reads ``<clone>/reconcile-report.json``
  (exactly ``verdict``, ``session``, ``notes``). ``cannot_keep_both`` prints
  ``reconcile_ok cannot_keep_both:<session>``. ``both_kept`` refuses conflict markers,
  a delta (a path that the reconciler wrote after ``prepare``, or put back to P) in the
  deny set, and a test id that a side collects (with its parameters, in a scratch copy of
  the side's commit) and the clone does not; then it prints one
  ``reconcile_delta <path>`` line per delta path and ``reconcile_ok both_kept``.
* ``record --request <file> --clone <clone> --run <run> --author <session>
  --author-vendor <vendor>`` writes ``<common>/{{PROJECT_NAME}}-results/<run>/reconcile.json``
  (``reconcile-record/1``: ``role: reconciler``, the author and its vendor, the delta,
  both intents and each test file that both sides changed), which
  ``result_snapshot.py scope`` reads for the ``scope_item reconcile`` lines.

A refusal prints one line ``reconcile_bad:<reason>`` and exits 1; a denied path also
writes one JSON WARN record ``reconcile_refused`` with the four limit fields to stderr.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, cast

if not __package__:
    # Script mode (``python tools/replay_reconcile.py``): the repository root holds ``tools``.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import run_parameters as rp  # noqa: E402

RESULTS_FOLDER = "{{PROJECT_NAME}}-results"
REQUEST_NAME = "reconcile-request.json"
BRIEF_NAME = "reconcile-brief.json"
PREPARED_NAME = "reconcile-prepared.json"
REPORT_NAME = "reconcile-report.json"
RECORD_NAME = "reconcile.json"
BRIEF_SCHEMA = "reconcile-brief/1"
PREPARED_SCHEMA = "reconcile-prepared/1"
RECORD_SCHEMA = "reconcile-record/1"
REQUEST_KEYS = frozenset({"base", "sides", "paths"})
REPORT_KEYS = frozenset({"verdict", "session", "notes"})
VERDICTS = ("both_kept", "cannot_keep_both")
AUTHOR_VENDORS = ("anthropic", "openai")
LEDGER_KEYS = frozenset(
    {"schema", "run", "clone", "base", "commit", "tree", "session", "author_vendor"}
)
RUN_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,60}")
SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
OID_RE = re.compile(r"[0-9a-f]{40}")
MARKER_RE = re.compile(rb"^(<{7} |={7}\r?$|>{7} )", re.MULTILINE)
HANDOFF_PREFIX = ".agent/context/handoffs/"
PLAN_RE = re.compile(r"(docs/execution/plans/[^/]+)/")
COLLECT_TIMEOUT_S = 600
FIXTURE_FOLDERS = frozenset({"tests", "fixtures"})
FIXTURE_MODULES = frozenset({"pytest", "pytest_asyncio"})
FIXTURE_NAMES = frozenset({"fixture", "yield_fixture"})
FIXTURE_RE = re.compile(rb"^\s*@(?:pytest\.|pytest_asyncio\.)?fixture\b", re.MULTILINE)
# The deny set of a reconcile delta (AC-952.4): the pytest collection configuration and
# each shared fixture file (a fixture file of the side base that both sides import). A
# fixture file is a module under a ``tests`` or ``fixtures`` folder, or a module that
# defines a pytest fixture. A production module that both sides change and import is the
# usual reconcile, so it is not denied.
DENY_LIMIT = "reconcile_deny_set"
DENY_VALUE = (
    "conftest.py at any level; pyproject.toml [tool.pytest.ini_options]; pytest.ini; "
    "setup.cfg [tool:pytest]; tox.ini [pytest]; a base fixture file "
    "that both sides import"
)

EXIT_OK = 0
EXIT_REFUSED = 1


class ReconcileRefusal(Exception):
    """A reconcile rule refused; ``reason`` is the ``reconcile_bad:`` code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def _refuse(reason: str, detail: str = "") -> NoReturn:
    raise ReconcileRefusal(reason, detail)


def _now() -> str:
    """The UTC time, ISO 8601 with seconds and ``Z``."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def _git_run(
    cwd: Path, *args: str, data: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run git in ``cwd`` without inherited ``GIT_*`` values; no check."""
    return subprocess.run(  # noqa: S603 - fixed argv
        ["git", *args],
        cwd=cwd,
        env=rp._git_env(None),
        input=data,
        capture_output=True,
        check=False,
    )


def _git(cwd: Path, *args: str) -> bytes:
    """The stdout of a git command that must succeed.

    Raises:
        ReconcileRefusal: ``git_failed``.
    """
    proc = _git_run(cwd, *args)
    if proc.returncode != 0:
        _refuse(
            "git_failed",
            f"git {' '.join(args)} exited {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}",
        )
    return proc.stdout


def _blob(cwd: Path, commit: str, rel: str) -> bytes | None:
    """The bytes of ``rel`` in ``commit``; None when the commit has no file there."""
    proc = _git_run(cwd, "cat-file", "blob", f"{commit}:{rel}")
    return proc.stdout if proc.returncode == 0 else None


@dataclass(frozen=True)
class Change:
    """One path that a side changed from its base B to its result S."""

    rel: str
    deleted: bool


def _changes(cwd: Path, base: str, commit: str) -> list[Change]:
    """The paths that ``base..commit`` changes, sorted (renames as delete and add)."""
    out = _git(cwd, "diff-tree", "-r", "-z", "--no-renames", "--raw", base, commit)
    parts = out.split(b"\0")
    found: list[Change] = []
    index = 0
    while index + 1 < len(parts):
        head = parts[index].decode("utf-8", "replace")
        rel = parts[index + 1].decode("utf-8")
        index += 2
        if not head.startswith(":"):
            continue
        status = head.split()[-1]
        found.append(Change(rel=rel, deleted=status.startswith("D")))
    return sorted(found, key=lambda change: change.rel)


# ---------------------------------------------------------------------------
# the request and the two sides
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Side:
    """One side of the reconcile: its ledger entry and its change set."""

    run: str
    session: str
    author_vendor: str | None
    base: str
    commit: str
    changes: tuple[Change, ...]

    def changed(self) -> list[str]:
        """The paths that the side changed and still holds."""
        return [change.rel for change in self.changes if not change.deleted]


@dataclass(frozen=True)
class Request:
    """The reconcile request of one run, its folder and its two sides."""

    path: Path
    common: Path
    base: str
    paths: tuple[str, ...]
    sides: tuple[Side, Side]

    @property
    def folder(self) -> Path:
        return self.path.parent

    def sessions(self) -> tuple[str, str]:
        return self.sides[0].session, self.sides[1].session


def _read_json(path: Path, missing: str, bad: str) -> object:
    """The JSON value of ``path``.

    Raises:
        ReconcileRefusal: ``missing`` when there is no file, ``bad`` when it does not parse.
    """
    if not path.is_file():
        _refuse(missing, f"no file {path}")
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _refuse(bad, f"cannot read {path}: {exc}")


def _check_rel(rel: object) -> str:
    """``rel`` when it is a repository-relative POSIX path with no ``..`` part."""
    if not isinstance(rel, str) or not rel or "\\" in rel or rel.startswith("/"):
        _refuse("request_bad", f"path {rel!r} is not repository-relative")
    parts = PurePosixPath(rel).parts
    if ".." in parts or ":" in parts[0]:
        _refuse("request_bad", f"path {rel!r} leaves the repository")
    return rel


def _side(common: Path, run: str) -> Side:
    """The side of ``run`` from its result ledger ``<common>/{{PROJECT_NAME}}-results/<run>.json``."""
    data = _read_json(
        common / RESULTS_FOLDER / f"{run}.json",
        f"side_ledger:{run}",
        f"side_ledger:{run}",
    )
    if not isinstance(data, dict) or set(data) != LEDGER_KEYS:
        _refuse(
            f"side_ledger:{run}",
            f"the ledger of {run} does not hold {sorted(LEDGER_KEYS)}",
        )
    entry = cast(dict[str, Any], data)
    base, commit, session = entry.get("base"), entry.get("commit"), entry.get("session")
    vendor = entry.get("author_vendor")
    shaped = (
        entry.get("run") == run
        and isinstance(base, str)
        and OID_RE.fullmatch(base) is not None
        and isinstance(commit, str)
        and OID_RE.fullmatch(commit) is not None
        and isinstance(session, str)
        and SESSION_RE.fullmatch(session) is not None
        and (vendor is None or vendor in AUTHOR_VENDORS)
    )
    if not shaped:
        _refuse(
            f"side_ledger:{run}",
            f"the ledger of {run} has a bad run, oid, session or vendor",
        )
    if _git_run(common, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        _refuse(
            f"side_commit:{run}",
            f"the result commit {commit} of {run} is not in {common}",
        )
    return Side(
        run=run,
        session=str(session),
        author_vendor=cast(str | None, vendor),
        base=str(base),
        commit=str(commit),
        changes=tuple(_changes(common, str(base), str(commit))),
    )


def _request(path_arg: str) -> Request:
    """The request at ``path_arg``, which must be ``<common>/{{PROJECT_NAME}}-results/<run>/``.

    Raises:
        ReconcileRefusal: ``request_missing``, ``request_bad``, ``request_keys``,
            ``side_ledger:<run>``, ``side_commit:<run>``.
    """
    path = Path(path_arg).resolve()
    data = _read_json(path, "request_missing", "request_bad")
    if path.name != REQUEST_NAME or path.parent.parent.name != RESULTS_FOLDER:
        _refuse(
            "request_bad",
            f"{path} is not <common>/{RESULTS_FOLDER}/<run>/{REQUEST_NAME}",
        )
    common = path.parent.parent.parent
    if not (common / "objects").is_dir():
        _refuse("request_bad", f"{common} is not a git common dir")
    if not isinstance(data, dict) or set(data) != REQUEST_KEYS:
        _refuse("request_keys", f"the request must hold exactly {sorted(REQUEST_KEYS)}")
    body = cast(dict[str, Any], data)
    base, sides, paths = body["base"], body["sides"], body["paths"]
    if not isinstance(base, str) or OID_RE.fullmatch(base) is None:
        _refuse("request_bad", "base is not a 40-hex commit id")
    if (
        not isinstance(sides, list)
        or len(cast(list[Any], sides)) != 2
        or not all(
            isinstance(s, str) and RUN_RE.fullmatch(s) for s in cast(list[Any], sides)
        )
        or sides[0] == sides[1]
    ):
        _refuse("request_bad", "sides must be two different run names")
    if sides[1] != path.parent.name:
        _refuse(
            "request_bad", f"the second side {sides[1]} is not the run of {path.parent}"
        )
    if not isinstance(paths, list) or not paths:
        _refuse("request_bad", "paths must be a non-empty list")
    rels = tuple(_check_rel(rel) for rel in cast(list[Any], paths))
    one, two = (_side(common, str(run)) for run in cast(list[str], sides))
    return Request(path=path, common=common, base=base, paths=rels, sides=(one, two))


# ---------------------------------------------------------------------------
# brief: the reconciler's inputs
# ---------------------------------------------------------------------------


def _plan_folders(paths: Iterable[str]) -> list[str]:
    folders = {match.group(1) for rel in paths if (match := PLAN_RE.match(rel))}
    return sorted(folders)


def _intents(cwd: Path, side: Side) -> list[str]:
    """The ``implementation-plan.md`` of each plan folder that the side changed."""
    found: list[str] = []
    for folder in _plan_folders(change.rel for change in side.changes):
        rel = f"{folder}/implementation-plan.md"
        if _blob(cwd, side.commit, rel) is not None:
            found.append(rel)
    return found


def _is_test_file(rel: str) -> bool:
    name = PurePosixPath(rel).name
    return name.startswith("test_") and name.endswith(".py")


def _test_ids(rel: str, data: bytes) -> list[str]:
    """The ``<file>::<test>`` ids of the top-level tests and ``Test*`` class methods."""
    try:
        module = ast.parse(data.decode("utf-8"), filename=rel)
    except (SyntaxError, UnicodeDecodeError, ValueError):
        _refuse(f"test_parse:{rel}", f"{rel} does not parse as Python")
    ids: list[str] = []
    for node in module.body:
        if isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef
        ) and node.name.startswith("test"):
            ids.append(f"{rel}::{node.name}")
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(
                    item, ast.FunctionDef | ast.AsyncFunctionDef
                ) and item.name.startswith("test"):
                    ids.append(f"{rel}::{node.name}::{item.name}")
    return ids


def _side_tests(cwd: Path, side: Side) -> list[str]:
    """The test ids of each ``test_*.py`` file that the side changed and still holds."""
    ids: list[str] = []
    for rel in side.changed():
        if not _is_test_file(rel):
            continue
        data = _blob(cwd, side.commit, rel)
        if data is not None:
            ids.extend(_test_ids(rel, data))
    return ids


def _side_body(cwd: Path, side: Side) -> dict[str, Any]:
    return {
        "run": side.run,
        "session": side.session,
        "author_vendor": side.author_vendor,
        "base": side.base,
        "commit": side.commit,
        "handoffs": [rel for rel in side.changed() if rel.startswith(HANDOFF_PREFIX)],
        "intents": _intents(cwd, side),
        "tests": _side_tests(cwd, side),
    }


def _write_json(path: Path, body: Mapping[str, Any]) -> None:
    """Write ``body`` to ``path`` atomically.

    Raises:
        ReconcileRefusal: ``io_error``.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rp._write_atomic(
            path, (json.dumps(dict(body), indent=2) + "\n").encode("utf-8")
        )
    except OSError as exc:
        _refuse("io_error", f"cannot write {path}: {exc}")


def _brief(request_arg: str) -> int:
    req = _request(request_arg)
    body = {
        "schema": BRIEF_SCHEMA,
        "request": req.path.as_posix(),
        "base": req.base,
        "paths": list(req.paths),
        "sides": [_side_body(req.common, side) for side in req.sides],
        "report": {
            "file": REPORT_NAME,
            "keys": sorted(REPORT_KEYS),
            "verdicts": list(VERDICTS),
        },
    }
    path = req.folder / BRIEF_NAME
    _write_json(path, body)
    print(f"reconcile_brief {path.as_posix()}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# prepare: the second side's change set in a clone at P, with conflict markers
# ---------------------------------------------------------------------------


def _clone(clone_arg: str, base: str) -> Path:
    """The clone at ``clone_arg``; its ``HEAD`` must be the request base P.

    Raises:
        ReconcileRefusal: ``clone_bad``, ``clone_base``.
    """
    clone = Path(clone_arg).resolve()
    if not (clone / ".git").exists():
        _refuse("clone_bad", f"{clone} is not a clone")
    proc = _git_run(clone, "rev-parse", "--verify", "-q", "HEAD")
    head = proc.stdout.decode("utf-8").strip()
    if proc.returncode != 0 or head != base:
        _refuse(
            "clone_base",
            f"the clone HEAD is {head or 'none'}, not the request base {base}",
        )
    return clone


def _sha(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _read_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError as exc:
        _refuse("io_error", f"cannot read {path}: {exc}")


def _merge(
    clone: Path, rel: str, current: bytes, base: bytes, other: bytes, run: str
) -> tuple[bytes, bool]:
    """``git merge-file -p`` of the three versions: (the result, True on a conflict)."""
    with tempfile.TemporaryDirectory(prefix="reconcile-") as scratch:
        folder = Path(scratch)
        names = []
        for name, data in (("current", current), ("base", base), ("other", other)):
            target = folder / name
            target.write_bytes(data)
            names.append(str(target))
        proc = _git_run(
            clone, "merge-file", "-p", "-L", "main", "-L", "base", "-L", run, *names
        )
    if proc.returncode < 0 or proc.returncode > 127:
        _refuse("merge_failed", f"git merge-file of {rel} exited {proc.returncode}")
    return proc.stdout, proc.returncode > 0


def _write_file(path: Path, data: bytes | None) -> None:
    try:
        if data is None:
            if path.is_file():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        _refuse("io_error", f"cannot write {path}: {exc}")


def _result(req: Request, clone: Path, change: Change) -> tuple[bytes | None, bool]:
    """The bytes that ``prepare`` writes for one change of the second side.

    Returns:
        ``(bytes, conflicted)``; the bytes are None for a path that is deleted.

    Raises:
        ReconcileRefusal: ``delete_conflict:<path>``, ``merge_failed``.
    """
    side, rel = req.sides[1], change.rel
    b2 = _blob(req.common, side.base, rel)
    s2 = None if change.deleted else _blob(req.common, side.commit, rel)
    p = _blob(clone, req.base, rel)
    if p == s2:
        return p, False
    if p == b2:
        return s2, False
    if s2 is None:
        _refuse(
            f"delete_conflict:{rel}",
            f"{side.run} deletes {rel}, which main changed",
        )
    if p is None:
        _refuse(
            f"delete_conflict:{rel}",
            f"main deleted {rel}, which {side.run} changes",
        )
    return _merge(clone, rel, p, b2 or b"", s2, side.run)


def _prepare(request_arg: str, clone_arg: str) -> int:
    req = _request(request_arg)
    clone = _clone(clone_arg, req.base)
    prepared: dict[str, str | None] = {}
    conflicts: list[str] = []
    for change in req.sides[1].changes:
        rel = change.rel
        result, conflicted = _result(req, clone, change)
        if conflicted:
            conflicts.append(rel)
        _write_file(clone / rel, result)
        prepared[rel] = _sha(result)
    _write_json(
        req.folder / PREPARED_NAME,
        {
            "schema": PREPARED_SCHEMA,
            "clone": clone.as_posix(),
            "base": req.base,
            "conflicts": conflicts,
            "files": prepared,
        },
    )
    print(f"reconcile_prepared {clone.as_posix()} conflicts={len(conflicts)}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# check: the report, the markers, the deny set and the union of both test lists
# ---------------------------------------------------------------------------


def _report(clone: Path, req: Request) -> tuple[str, str | None]:
    """(verdict, session) of ``<clone>/reconcile-report.json``.

    Raises:
        ReconcileRefusal: ``report_missing``, ``report_keys``, ``report_verdict``,
            ``report_session``.
    """
    data = _read_json(clone / REPORT_NAME, "report_missing", "report_keys")
    if not isinstance(data, dict) or set(data) != REPORT_KEYS:
        _refuse("report_keys", f"the report must hold exactly {sorted(REPORT_KEYS)}")
    body = cast(dict[str, Any], data)
    if not isinstance(body["notes"], str):
        _refuse("report_keys", "notes is not a string")
    verdict, session = body["verdict"], body["session"]
    if verdict not in VERDICTS:
        _refuse("report_verdict", f"verdict {verdict!r} is not one of {list(VERDICTS)}")
    if verdict == "cannot_keep_both":
        if session not in req.sessions():
            _refuse(
                "report_session", f"session {session!r} is not a side of the request"
            )
        return str(verdict), str(session)
    if session is not None:
        _refuse("report_session", "a both_kept report names no session")
    return str(verdict), None


def _prepared(req: Request, clone: Path) -> dict[str, str | None]:
    data = _read_json(req.folder / PREPARED_NAME, "not_prepared", "not_prepared")
    body = cast(dict[str, Any], data) if isinstance(data, dict) else {}
    files = body.get("files")
    if (
        body.get("schema") != PREPARED_SCHEMA
        or body.get("clone") != clone.as_posix()
        or not isinstance(files, dict)
    ):
        _refuse(
            "not_prepared",
            f"{req.folder / PREPARED_NAME} is not the prepare record of {clone}",
        )
    return cast(dict[str, str | None], files)


def _z(out: bytes) -> list[str]:
    return [item.decode("utf-8") for item in out.split(b"\0") if item]


def _working_changes(clone: Path, base: str) -> list[str]:
    """The paths whose working bytes differ from P, tracked or new (not ignored)."""
    tracked = _z(_git(clone, "diff", "--no-renames", "--name-only", "-z", base, "--"))
    new = _z(_git(clone, "ls-files", "-z", "--others", "--exclude-standard"))
    return sorted({*tracked, *new} - {REPORT_NAME})


def _delta(req: Request, clone: Path) -> list[str]:
    """The paths that the reconciler wrote: their bytes differ from the prepared bytes.

    A prepared path that now holds the bytes of P is no working change, but it is a delta.
    """
    prepared = _prepared(req, clone)
    found: list[str] = []
    for rel in sorted({*_working_changes(clone, req.base), *prepared}):
        now = _sha(_read_file(clone / rel))
        expected = (
            prepared[rel] if rel in prepared else _sha(_blob(clone, req.base, rel))
        )
        if now != expected:
            found.append(rel)
    return found


def _pytest_section(rel: str, data: bytes | None) -> object:
    """The pytest configuration that ``data`` of ``rel`` holds (None when none)."""
    if data is None:
        return None
    text = data.decode("utf-8", "replace")
    name = PurePosixPath(rel).name
    if name == "pyproject.toml":
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return ("unparsed", text)
        tool = parsed.get("tool", {})
        pytest_table = tool.get("pytest", {}) if isinstance(tool, dict) else {}
        return (
            pytest_table.get("ini_options")
            if isinstance(pytest_table, dict)
            else pytest_table
        )
    section = {"setup.cfg": "tool:pytest", "tox.ini": "pytest"}.get(name)
    if section is None:
        return text
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error:
        return ("unparsed", text)
    return dict(parser[section]) if parser.has_section(section) else None


def _module_of(rel: str) -> str | None:
    path = PurePosixPath(rel)
    if path.suffix != ".py":
        return None
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _imports(data: bytes, rel: str) -> set[str]:
    """Each module name that ``data`` imports, with ``from a import b`` as ``a`` and ``a.b``.

    A name in a ``pytest_plugins`` assignment counts: pytest imports that module.
    """
    try:
        module = ast.parse(data.decode("utf-8"), filename=rel)
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return set()
    names: set[str] = set()
    package = ".".join(PurePosixPath(rel).parent.parts)
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                keep = (
                    parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                )
                base = ".".join([*keep, base] if base else keep)
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(target, ast.Name) and target.id == "pytest_plugins"
                for target in targets
            ):
                names.update(
                    item.value
                    for item in ast.walk(node.value)
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
    return names


def _side_imports(common: Path, side: Side) -> set[str]:
    names: set[str] = set()
    for rel in side.changed():
        if rel.endswith(".py"):
            data = _blob(common, side.commit, rel)
            if data is not None:
                names |= _imports(data, rel)
    return names


def _uses_fixture(rel: str, data: bytes) -> bool:
    """Whether ``data`` uses pytest's fixture under any import name, at any place.

    Either a name imported from ``FIXTURE_MODULES`` (``from pytest import fixture as x``),
    or an attribute of a name of such a module (``import pytest as pt``; ``pt.fixture``).
    """
    try:
        module = ast.parse(data.decode("utf-8"), filename=rel)
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return False
    modules: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module in FIXTURE_MODULES:
            if any(alias.name in FIXTURE_NAMES for alias in node.names):
                return True
        elif isinstance(node, ast.Import):
            modules.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in FIXTURE_MODULES
            )
    return any(
        isinstance(node, ast.Attribute)
        and node.attr in FIXTURE_NAMES
        and isinstance(node.value, ast.Name)
        and node.value.id in modules
        for node in ast.walk(module)
    )


def _is_fixture_file(rel: str, data: bytes) -> bool:
    """Whether the module ``rel`` with the base bytes ``data`` is a fixture file."""
    folders = PurePosixPath(rel).parts[:-1]
    return bool(
        FIXTURE_FOLDERS.intersection(folders)
        or FIXTURE_RE.search(data)
        or _uses_fixture(rel, data)
    )


def _section_kept(req: Request, clone: Path, rel: str) -> bool:
    """Whether the pytest section of ``rel`` is the one that ``prepare`` wrote.

    The second side's own change of the section stays in the result. A file that
    conflicted holds markers, so its section is merged as one value: the side that changed
    it wins, and two different changes have no permitted result.
    """
    now = _pytest_section(rel, _read_file(clone / rel))
    p = _pytest_section(rel, _blob(clone, req.base, rel))
    side = req.sides[1]
    change = next((item for item in side.changes if item.rel == rel), None)
    if change is None:
        return now == p
    result, conflicted = _result(req, clone, change)
    if not conflicted:
        return now == _pytest_section(rel, result)
    b2 = _pytest_section(rel, _blob(req.common, side.base, rel))
    s2 = _pytest_section(rel, _blob(req.common, side.commit, rel))
    if s2 in (p, b2):
        return now == p
    return p == b2 and now == s2


def _denied(
    req: Request, clone: Path, rel: str, both_import: Sequence[set[str]]
) -> bool:
    name = PurePosixPath(rel).name
    if name in ("conftest.py", "pytest.ini"):
        return True
    if name in ("pyproject.toml", "setup.cfg", "tox.ini"):
        return not _section_kept(req, clone, rel)
    module = _module_of(rel)
    before_data = _blob(req.common, req.sides[0].base, rel)
    if module is None or before_data is None or not _is_fixture_file(rel, before_data):
        return False
    return all(
        any(name == module or name.startswith(f"{module}.") for name in names)
        for names in both_import
    )


def _warn(rel: str, run: str) -> None:
    record = {
        "level": "WARN",
        "event": "reconcile_refused",
        "limit_name": DENY_LIMIT,
        "configured_value": DENY_VALUE,
        "observed_value": rel,
        "window": f"the reconcile delta of {run}",
    }
    print(json.dumps(record, sort_keys=True), file=sys.stderr)


# The collector runs pytest in-process in a child interpreter with a plugin that prints
# each collected node id, so the repository's addopts (for example ``-q``) do not change
# the output that this tool reads.
_COLLECTOR = """
import sys

import pytest


class _Ids:
    def pytest_collection_finish(self, session):
        for item in session.items:
            print("reconcile_collected " + item.nodeid, flush=True)


sys.exit(pytest.main(sys.argv[1:], plugins=[_Ids()]))
"""


def _collected(clone: Path, files: Sequence[str]) -> set[str]:
    """The node ids that ``pytest --collect-only`` of ``files`` collects in the clone."""
    if not files:
        return set()
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    argv = [
        sys.executable,
        "-c",
        _COLLECTOR,
        "--collect-only",
        "-p",
        "no:cacheprovider",
        "--rootdir",
        str(clone),
        *files,
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            argv,
            cwd=clone,
            env=env,
            capture_output=True,
            check=False,
            timeout=COLLECT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _refuse("collect_failed", f"pytest --collect-only in {clone}: {exc}")
    prefix = "reconcile_collected "
    text = proc.stdout.decode("utf-8", "replace")
    return {
        line[len(prefix) :].strip()
        for line in text.splitlines()
        if line.startswith(prefix)
    }


def _side_ids(req: Request, side: Side) -> list[tuple[str, bool]]:
    """``(id, exact)`` of each test of the side's changed test files.

    The ids are the ones that pytest collects in a scratch copy of the side's commit, with
    their parameters. A file that does not collect there gives the ids of its source: each
    stands for that test with any parameters (``exact`` is False).

    Raises:
        ReconcileRefusal: ``test_parse:<path>``; ``side_tree`` when git or the disk cannot
            give the scratch copy; ``collect_failed``.
    """
    named = _side_tests(req.common, side)
    files = [
        rel
        for rel in side.changed()
        if _is_test_file(rel) and _blob(req.common, side.commit, rel) is not None
    ]
    if not files:
        return []
    with tempfile.TemporaryDirectory(
        prefix="reconcile-side-", ignore_cleanup_errors=True
    ) as scratch:
        root = Path(scratch).resolve()
        archive = _git_run(req.common, "archive", "--format=tar", side.commit)
        if archive.returncode != 0:
            _refuse("side_tree", archive.stderr.decode("utf-8", "replace").strip())
        try:
            with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
                tar.extractall(root, filter="data")
        except (OSError, tarfile.TarError) as exc:
            _refuse("side_tree", f"cannot extract {side.commit}: {exc}")
        collected = _collected(root, files)
    done = {test_id.split("::", 1)[0] for test_id in collected}
    return [(test_id, True) for test_id in sorted(collected)] + [
        (test_id, False) for test_id in named if test_id.split("::", 1)[0] not in done
    ]


def _union(req: Request, clone: Path) -> None:
    """Every test id of both sides is collected in the clone.

    Raises:
        ReconcileRefusal: ``missing_test:<id>`` for the first id that is not collected;
            the refusals of ``_side_ids``.
    """
    wanted: dict[str, bool] = {}
    for side in req.sides:
        for test_id, exact in _side_ids(req, side):
            wanted.setdefault(test_id, exact)
    files = sorted({test_id.split("::", 1)[0] for test_id in wanted})
    present = [rel for rel in files if (clone / rel).is_file()]
    collected = _collected(clone, present)
    bases = {test_id.split("[", 1)[0] for test_id in collected}
    for test_id, exact in wanted.items():
        if test_id not in (collected if exact else bases):
            _refuse(
                f"missing_test:{test_id}",
                f"the clone {clone} does not collect {test_id}",
            )


def checked(req: Request, clone: Path) -> tuple[str, str | None, list[str]]:
    """(verdict, session, delta) of a reconciled clone, after every check.

    Raises:
        ReconcileRefusal: the report refusals, ``markers:<path>``, ``denied:<path>``
            (after the WARN record) and ``missing_test:<id>``.
    """
    verdict, session = _report(clone, req)
    if verdict == "cannot_keep_both":
        return verdict, session, []
    changed = _working_changes(clone, req.base)
    for rel in changed:
        data = _read_file(clone / rel)
        if data is not None and MARKER_RE.search(data):
            _refuse(f"markers:{rel}", f"{rel} still holds conflict markers")
    delta = _delta(req, clone)
    both_import = [_side_imports(req.common, side) for side in req.sides]
    for rel in delta:
        if _denied(req, clone, rel, both_import):
            _warn(rel, req.sides[1].run)
            _refuse(f"denied:{rel}", f"the reconcile delta may not change {rel}")
    _union(req, clone)
    return verdict, None, delta


def _check(request_arg: str, clone_arg: str) -> int:
    req = _request(request_arg)
    clone = _clone(clone_arg, req.base)
    verdict, session, delta = checked(req, clone)
    if verdict == "cannot_keep_both":
        print(f"reconcile_ok cannot_keep_both:{session}")
        return EXIT_OK
    for rel in delta:
        print(f"reconcile_delta {rel}")
    print("reconcile_ok both_kept")
    return EXIT_OK


# ---------------------------------------------------------------------------
# record: the reconcile record of the reconciler's run
# ---------------------------------------------------------------------------


def _record(
    request_arg: str, clone_arg: str, run_arg: str, author: str, vendor: str
) -> int:
    if RUN_RE.fullmatch(run_arg) is None:
        _refuse("run", f"{run_arg!r} is not a run name")
    if SESSION_RE.fullmatch(author) is None:
        _refuse("author", f"{author!r} is not a session id")
    if vendor not in AUTHOR_VENDORS:
        _refuse("author_vendor", f"{vendor!r} is not one of {list(AUTHOR_VENDORS)}")
    req = _request(request_arg)
    if author in req.sessions():
        _refuse("reconciler_is_author", f"{author} is the author of a side")
    clone = _clone(clone_arg, req.base)
    verdict, _session, delta = checked(req, clone)
    if verdict != "both_kept":
        _refuse("record_verdict", "only a both_kept reconcile is recorded")
    one, two = req.sides
    intents = sorted({*_intents(req.common, one), *_intents(req.common, two)})
    shared_tests = sorted(
        rel for rel in set(one.changed()) & set(two.changed()) if _is_test_file(rel)
    )
    path = req.common / RESULTS_FOLDER / run_arg / RECORD_NAME
    _write_json(
        path,
        {
            "schema": RECORD_SCHEMA,
            "role": "reconciler",
            "run": run_arg,
            "request": req.path.as_posix(),
            "author": author,
            "author_vendor": vendor,
            "base": req.base,
            "sides": [one.run, two.run],
            "sessions": [one.session, two.session],
            "delta": delta,
            "intents": intents,
            "tests": shared_tests,
            "at": _now(),
        },
    )
    print(f"reconcile_recorded {path.as_posix()}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="replay_reconcile.py",
        description="The reconcile step of a land: brief, prepare, check and record.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    brief = sub.add_parser("brief", help="write the reconciler's brief")
    brief.add_argument("--request", required=True)
    for name, text in (
        ("prepare", "write the second side into a clone at P"),
        ("check", "check the reconciled clone"),
        ("record", "record the reconcile of the reconciler's run"),
    ):
        verb = sub.add_parser(name, help=text)
        verb.add_argument("--request", required=True)
        verb.add_argument("--clone", required=True)
        if name == "record":
            verb.add_argument("--run", required=True)
            verb.add_argument("--author", required=True)
            verb.add_argument("--author-vendor", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command; 0 on success, 1 on a refusal (``reconcile_bad:<reason>``)."""
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_REFUSED
    try:
        if args.command == "brief":
            return _brief(args.request)
        if args.command == "prepare":
            return _prepare(args.request, args.clone)
        if args.command == "check":
            return _check(args.request, args.clone)
        return _record(
            args.request, args.clone, args.run, args.author, args.author_vendor
        )
    except ReconcileRefusal as exc:
        print(f"reconcile_bad:{exc.reason}")
        if exc.detail:
            print(exc.detail, file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
