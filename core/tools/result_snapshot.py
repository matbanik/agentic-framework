"""Result snapshot of a scratch clone (MEU-949, MEU-950, plan 2026-11-11-ag3-pilot-b-replay-land).

A worker on the replay route edits its scratch clone (``executor_worktree.py clone``)
and leaves the changes uncommitted. This tool turns that working tree into one commit
that the main tree can fetch and replay, and it never changes the clone's index,
``HEAD`` or working files. After ``lanes.py land replay`` it lists what of the
replayed candidate C no reviewer read, records the reviews and writes the review
prompt (MEU-950).

Commands (each prints its result lines and returns 0, or prints one refusal line
``snapshot_bad:<reason>`` with its detail on stderr and returns 1):

* ``take --clone <path> --run <run>``: B is the ``parent`` of the clone marker
  ``<clone>/.git/scratch-clone.json``. A temporary index is seeded with B (``read-tree``),
  then ``add -A`` reads the working tree (``.gitignore`` holds) and ``write-tree`` gives T.
  ``commit-tree T -p B -m "result <run>"`` gives S with the identity of the environment,
  no hooks and no signing. ``update-ref refs/fleet/result/<run> S`` writes the ref in the
  clone only. Last line: ``snapshot_ok <run> base=<B> commit=<S> tree=<T>``.
  Refusals: ``run`` (the run name breaks ``[a-z0-9][a-z0-9-]{1,60}``), ``not_clone``,
  ``exists`` (the result ref is already there), ``empty`` (T is the tree of B).
* ``fetch --clone <path> --run <run> [--session <s>] [--author-vendor <v>]
  [--status <status.json>]``: fetches the result ref into the same ref of the main
  repository that the marker's ``main`` names, prints ``fetch_ok <run> commit=<S>`` and
  writes the ledger ``<git common dir>/{{PROJECT_NAME}}-results/<run>.json`` (schema
  ``result-ledger/1``). ``--status`` reads the worker's ``dispatch-status.v1`` file: the
  ledger ``author_vendor`` is the vendor of its ``cli`` (``claude`` is ``anthropic``,
  ``codex`` is ``openai``), never its ``author_vendor`` key, which names the author a
  review dispatch checks (I4). Refusals: ``status_bad``, ``vendor_conflict`` (it differs
  from ``--author-vendor``).
* ``drop --run <run>``: in the main repository of the working folder, reads the ledger,
  deletes the result ref in the main repository and in the clone it names
  (``update-ref -d``), keeps the ledger and prints ``drop_ok <run>``.
* ``seen --clone <path> --out <file> --dispatch-dir <dir>`` (EA-39 to EA-42):
  before the worker review dispatch starts, snapshots the clone's working tree as the
  commit ``refs/fleet/seen/<commit>`` on B (in the clone, then fetched into the main
  repository that the marker names), claims ``<dir>`` (the dispatch folder) for this
  record and writes the ``review-seen.v1`` record ``<file>`` (kind ``worker``, the
  clone, B, the commit, its tree, ``<dir>`` and the time). It prints ``seen_ok
  clone=<path> tree=<tree> out=<file>``. Refusals: ``not_clone``, ``exists``
  (``<file>`` is already there), ``dispatch_missing``, ``seen_late`` (``<dir>`` is
  there: its dispatch started), ``dispatch_claimed`` (another record claimed it),
  ``dispatch_bad`` (``<dir>`` is not one canonical spelling: a name part ends in a
  dot or a space, or the last part is not a ``-DispatchId``).
* ``review --run <run> --kind worker|integration --verdict <file> [--seen <file>]``
  (I3): records an ``approved`` ``review-verdict.v1`` file as one ``review`` line of
  the run's event file ``<git common dir>/{{PROJECT_NAME}}-results/<run>/events.jsonl``. The
  key is the input that the review dispatch saw (EA-39): the ``tree`` of the ``seen``
  record for the worker review (W), and ``(parent, tree)`` of the ``<out>.seen.json``
  record of ``brief`` for the integration review (P and the tree of C). It prints
  ``review_ok <run> <kind> <key>``. The runs of one ledger ``session`` share their
  reviews: a correction is a new run of the same clone. The latest review of a kind is
  the one whose input was seen last. A seen record keys one verdict: the same verdict
  (same path and sha256) may record it again, another verdict may not. Without
  ``--seen``, only a verdict that the session recorded before is taken, with its
  first key (EA-37). The verdict's ``target_plan`` must name the plan of the replay
  batch, or before the batch a plan whose folder the result changes; a worker review
  of another plan is void at ``scope`` (``void worker plan``). Refusals:
  ``verdict_bad``, ``no_replay``, ``replay_bad``, ``seen_missing`` (no ``--seen`` and
  no recorded verdict), ``seen_used`` (another verdict used the record), ``seen_bad``
  (the record is not the input of this run and kind, or no record claimed its
  dispatch folder), ``dispatch_claimed`` (two claims name the dispatch folder, or
  its claim is of another record; EA-42).
* ``scope --run <run> [--gate-run <dir>]`` (I1): reads the ledger and the batch of the
  last ``land replay`` (``<run dir>/replay-batch.json``) and prints one line per item:
  ``scope_item lock <rel>`` (item 2), ``scope_item record <rel>`` (item 3),
  ``scope_item correction <rel>`` (item 4), ``scope_item context <plan slug> <rel>``
  (item 5); item 1 (reconcile) stays empty until MEU-952. Then one line per void review,
  ``void <kind> <reason>[ <paths>]``, which is also written to the event file. With no
  item and no void it prints ``integration_review:none``.
* ``brief --run <run> --out <file>`` (I2, I4): writes the review prompt (``B..S``,
  ``P..C``, ``git range-diff B..S P..C``, the scope items and the sessions that landed
  between B and P with their write sets and the public names of each changed Python
  module) and the ``review-seen.v1`` record ``<file>.seen.json`` of its input (kind
  ``integration``: the run, P, the tree of C and the plan), and prints ``brief_ok
  <run> out=<file>``, ``brief_seen <run> seen=<file>.seen.json`` and one ``dispatch
  <delta>[,<delta>] -AuthorVendor <vendor>`` line per vendor (``worker``,
  ``correction``). Refusals: ``exists`` (the seen record is already there),
  ``dispatch_missing``, ``seen_late``, ``dispatch_claimed`` and ``dispatch_bad``
  as for ``seen``.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, NoReturn, cast

RESULT_PREFIX = "refs/fleet/result/"
LEDGER_FOLDER = "{{PROJECT_NAME}}-results"
ORCH_FOLDER = "{{PROJECT_NAME}}-orch"
RECEIPTS_ROOT = Path("{{RECEIPTS_DIR}}")
LEDGER_SCHEMA = "result-ledger/1"
LEDGER_KEYS = (
    "schema",
    "run",
    "clone",
    "base",
    "commit",
    "tree",
    "session",
    "author_vendor",
)
REFUSAL_PREFIX = "snapshot_bad:"
EXIT_OK = 0
EXIT_REFUSED = 1
GIT_TIMEOUT_S = 600
RUN_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,60}")
OID_RE = re.compile(r"[0-9a-f]{40}")
AUTHOR_VENDORS = ("anthropic", "openai")
# The options that take a value; main joins each to its value (``_bind_values``).
VALUE_OPTIONS = frozenset(
    {
        "--clone",
        "--run",
        "--session",
        "--author-vendor",
        "--status",
        "--kind",
        "--verdict",
        "--out",
        "--gate-run",
        "--seen",
        "--dispatch-dir",
    }
)
# Variables that would point git at another repository, index or config; the identity
# variables (GIT_AUTHOR_*, GIT_COMMITTER_*) and GIT_CONFIG_GLOBAL/NOSYSTEM stay.
SCRUBBED_GIT_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
)
SCRUBBED_GIT_ENV_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")

# MEU-950: the worker status, the verdict, the event file and the scope rules.
STATUS_SCHEMA = "dispatch-status.v1"
VENDOR_OF_CLI = {"claude": "anthropic", "codex": "openai"}
VERDICT_SCHEMA = "review-verdict.v1"
VERDICT_APPROVED = "approved"
REVIEW_KINDS = ("worker", "integration")
EVENTS_NAME = "events.jsonl"
EVENT_REVIEW = "review"
EVENT_VOID = "void"
REPLAY_BATCH_NAME = "replay-batch.json"
GATE_RECORD_NAME = "gate.json"
NO_SCOPE = "integration_review:none"
# EA-39: the record of the input that a review dispatch saw.
SEEN_SCHEMA = "review-seen.v1"
SEEN_PREFIX = "refs/fleet/seen/"
SEEN_SUFFIX = ".seen.json"
# EA-40 (review R1-F1): the verdict of a review is the final.json that the dispatch
# wrapper writes in the dispatch folder that the seen record names, after the record.
DISPATCH_VERDICT = "final.json"
# A file time is coarser than _now() (NTFS takes the clock tick, FAT keeps 2 s).
MTIME_SLACK_S = 2.0
# EA-41 (review R1-F1, round 4): a seen record is taken before its dispatch starts
# (the wrapper makes the folder when it starts), and one seen record claims each
# folder. The claims are kept under the ledger folder of the main repository; a run
# name cannot start with "_".
SEEN_CLAIMS = "_seen-claims"
# EA-42 (review R1-F1, round 5): the -DispatchId grammar of the dispatch wrapper
# (tools/Invoke-CodexDispatch.ps1). Windows reads a name part with a trailing dot
# or space as the name without it, so such a spelling is refused at capture, and a
# claim is keyed like the wrapper's Get-RunDirIdentityKey.
DISPATCH_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
ALIAS_TAIL = ". "
NO_VENDOR = "none"
SCOPE_CANDIDATE_PREFIX = "scope-"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # pragma: allowlist secret
LOCK_NAMES = frozenset({"uv.lock", "package-lock.json"})
PLANS_DIR = "docs/execution/plans"
REFLECTIONS_DIR = "docs/execution/reflections"
# EA-6: the handoff sections a change after W may only add lines to.
APPEND_SECTIONS = frozenset(
    {"## Codex Validation Report", "## Corrections Applied", "## History"}
)
# EA-6: the derived cells of the one metrics-row request (METRICS_HEADERS names).
DERIVED_METRICS_HEADERS = (
    "Tool Calls",
    "Codex Findings",
    "Handoff Score",
    "Rule Adherence",
)
METRICS_ROW_PREFIX = "metrics-row "
STATUS_HEADER = "Status"
FRONTMATTER_FENCE = "---"
MARK_KEY_RE = re.compile(r"(status|stop_gate):(?:\s|$)")
HEADING_RE = re.compile(r"#{1,6} \S")
PLAN_PATH_RE = re.compile(r"docs/execution/plans/([^/]+)/")
PLAN_SLUG_RE = re.compile(r"\b(\d{4}-\d\d-\d\d-[a-z0-9][a-z0-9-]*[a-z0-9])\b")


class SnapshotRefusal(Exception):
    """A refusal: the reason is printed as ``snapshot_bad:<reason>``, the detail on stderr."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _refuse(reason: str, detail: str) -> NoReturn:
    """Raise the refusal ``reason`` with ``detail``."""
    raise SnapshotRefusal(reason, detail)


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def _git_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The process environment without the repository-redirect variables, no prompt."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in SCRUBBED_GIT_ENV
        and not key.upper().startswith(SCRUBBED_GIT_ENV_PREFIXES)
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra or {})
    return env


def _git_run(
    cwd: Path, *args: str, extra_env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``git -C <cwd> <args>``; the completed process (never raises on exit code).

    Raises:
        SnapshotRefusal: ``git_failed`` when git cannot start or times out.
    """
    command = ["git", "-c", "core.longpaths=true", "-C", str(cwd), *args]
    try:
        return subprocess.run(
            command,
            env=_git_env(extra_env),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _refuse("git_failed", f"git {' '.join(args)} in {cwd}: {exc}")


def _git(cwd: Path, *args: str, extra_env: Mapping[str, str] | None = None) -> str:
    """Run git in ``cwd``; its stripped stdout.

    Raises:
        SnapshotRefusal: ``git_failed`` when git exits non-zero.
    """
    proc = _git_run(cwd, *args, extra_env=extra_env)
    if proc.returncode != 0:
        output = (proc.stderr or proc.stdout).strip()
        _refuse(
            "git_failed",
            f"git {' '.join(args)} in {cwd} exited {proc.returncode}: {output}",
        )
    return proc.stdout.strip()


def _git_bytes(cwd: Path, *args: str) -> bytes:
    """Run git in ``cwd``; its raw stdout bytes (blobs and ``-z`` lists).

    Raises:
        SnapshotRefusal: ``git_failed`` when git cannot start, times out or exits
        non-zero.
    """
    command = ["git", "-c", "core.longpaths=true", "-C", str(cwd), *args]
    try:
        proc = subprocess.run(
            command,
            env=_git_env(),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _refuse("git_failed", f"git {' '.join(args)} in {cwd}: {exc}")
    if proc.returncode != 0:
        output = proc.stderr.decode("utf-8", "replace").strip()
        _refuse(
            "git_failed",
            f"git {' '.join(args)} in {cwd} exited {proc.returncode}: {output}",
        )
    return proc.stdout


def _z_list(data: bytes) -> list[str]:
    """The NUL-separated paths of a ``-z`` listing (git never quotes them)."""
    return [
        item.decode("utf-8", "surrogateescape") for item in data.split(b"\0") if item
    ]


def _ref(repo: Path, ref: str) -> str:
    """The commit id of ``ref`` in ``repo``; empty when the ref does not exist."""
    proc = _git_run(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _common_dir(repo: Path) -> Path:
    """The absolute git common dir of ``repo``.

    Raises:
        SnapshotRefusal: ``not_repo`` when ``repo`` is not a git repository.
    """
    proc = _git_run(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if proc.returncode != 0 or not proc.stdout.strip():
        _refuse("not_repo", f"{repo} is not a git repository: {proc.stderr.strip()}")
    return Path(proc.stdout.strip())


def _top_dir(repo: Path) -> Path:
    """The working-tree top of ``repo``.

    Raises:
        SnapshotRefusal: ``not_repo`` when ``repo`` has no working tree.
    """
    proc = _git_run(repo, "rev-parse", "--show-toplevel")
    if proc.returncode != 0 or not proc.stdout.strip():
        _refuse("not_repo", f"{repo} has no working tree: {proc.stderr.strip()}")
    return Path(proc.stdout.strip())


def _blob(top: Path, treeish: str, rel: str) -> bytes | None:
    """The bytes of ``rel`` in ``treeish``; ``None`` when ``treeish`` has no entry there.

    A link or submodule entry reads as ``<mode> <type> <oid>``, so two of them compare
    by their object and never equal a file.

    Raises:
        SnapshotRefusal: ``git_failed``.
    """
    listed = _git_bytes(top, "ls-tree", "-z", treeish, "--", rel).split(b"\0", 1)[0]
    if not listed:
        return None
    meta = listed.partition(b"\t")[0].decode("ascii", "replace").split()
    if len(meta) != 3:
        _refuse("git_failed", f"git ls-tree {treeish} -- {rel} gave {listed!r}")
    mode, kind, oid = meta
    if kind != "blob" or mode == "120000":
        return f"{mode} {kind} {oid}".encode("ascii")
    return _git_bytes(top, "cat-file", "blob", oid)


def _changed_paths(top: Path, old: str, new: str) -> list[str]:
    """The paths that differ between the trees ``old`` and ``new`` (no rename pairs)."""
    return _z_list(
        _git_bytes(
            top, "diff-tree", "-r", "-z", "--no-renames", "--name-only", old, new
        )
    )


# ---------------------------------------------------------------------------
# the clone, the run and the ledger
# ---------------------------------------------------------------------------


def _repo_on_path() -> None:
    """Put the repository root on ``sys.path`` first.

    A run as a script (``python tools/result_snapshot.py``) then imports the same
    package modules that a test patches.
    """
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)


def _executor_worktree() -> ModuleType:
    """``tools.executor_worktree`` (the PK3 clone and gate-candidate constants)."""
    _repo_on_path()
    from tools import executor_worktree  # noqa: PLC0415 - only some commands need it

    return executor_worktree


def _lanes() -> ModuleType:
    """``tools.lanes`` (the replay candidate, the requests and the junction files).

    ``lanes`` never imports this module (949-G3), so the import goes one way only.
    """
    _repo_on_path()
    from tools import lanes  # noqa: PLC0415 - only scope, review and brief need it

    return lanes


def _commit_batch() -> ModuleType:
    """``tools.commit_batch`` (the packet parser and ``batch_tree``)."""
    _repo_on_path()
    from tools import commit_batch  # noqa: PLC0415 - only scope, review and brief need it

    return commit_batch


def _check_run(run: str) -> str:
    """``run`` when it matches ``[a-z0-9][a-z0-9-]{1,60}``.

    Raises:
        SnapshotRefusal: ``run`` otherwise.
    """
    if not RUN_RE.fullmatch(run):
        _refuse("run", f"the run name {run!r} must match {RUN_RE.pattern}")
    return run


def _clone_marker(clone: Path) -> dict[str, str]:
    """The PK3 marker of the scratch clone ``clone``, with a checked ``parent``.

    A clone is a folder strictly inside the clone root of ``executor_worktree`` with
    the marker ``.git/scratch-clone.json`` of the PK3 key set.

    Raises:
        SnapshotRefusal: ``not_clone`` when ``clone`` is not such a clone.
    """
    ew = _executor_worktree()
    marker: dict[str, str] | None = ew._clone_marker(clone)  # noqa: SLF001
    if marker is None:
        _refuse(
            "not_clone",
            f"{clone} holds no scratch-clone marker .git/{ew.CLONE_MARKER} "
            "(make it with executor_worktree.py clone)",
        )
    if not ew._clone_contained(clone):  # noqa: SLF001
        _refuse("not_clone", f"{clone} is not inside the clone root {ew.clone_root()}")
    if not OID_RE.fullmatch(marker["parent"]):
        _refuse(
            "not_clone", f"the marker parent {marker['parent']!r} is not a commit id"
        )
    return marker


def _ledger_path(common: Path, run: str) -> Path:
    """``<git common dir>/{{PROJECT_NAME}}-results/<run>.json``."""
    return common / LEDGER_FOLDER / f"{run}.json"


def _read_ledger(path: Path) -> dict[str, str | None]:
    """The ledger entry at ``path`` with exactly LEDGER_KEYS.

    Raises:
        SnapshotRefusal: ``no_ledger`` when the file is missing, ``ledger_bad`` when it
        cannot be read or has another shape.
    """
    if not path.is_file():
        _refuse("no_ledger", f"no result ledger at {path} (run fetch first)")
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _refuse("ledger_bad", f"cannot read the ledger {path}: {exc}")
    if not isinstance(data, dict) or set(data) != set(LEDGER_KEYS):
        _refuse("ledger_bad", f"the ledger {path} does not hold the keys {LEDGER_KEYS}")
    entry: dict[str, str | None] = {}
    for key, value in data.items():
        if value is not None and not isinstance(value, str):
            _refuse("ledger_bad", f"the ledger {path} key {key!r} is not a string")
        entry[str(key)] = value
    if entry["schema"] != LEDGER_SCHEMA:
        _refuse("ledger_bad", f"the ledger {path} schema is not {LEDGER_SCHEMA}")
    return entry


def _write_ledger(path: Path, entry: Mapping[str, str | None]) -> None:
    """Write ``entry`` to ``path`` atomically (a temporary file, then a replace), LF.

    Raises:
        SnapshotRefusal: ``ledger_bad`` when the file cannot be written.
    """
    text = json.dumps(dict(entry), indent=2, sort_keys=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(
            prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
                out.write(text)
            os.replace(temp, path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
    except OSError as exc:
        _refuse("ledger_bad", f"cannot write the ledger {path}: {exc}")


@dataclass(frozen=True)
class Result:
    """One checked ledger entry: the run, its session, B, S, the tree of S, the vendor."""

    run: str
    session: str
    base: str
    commit: str
    tree: str
    author_vendor: str | None


def _result(common: Path, run: str) -> Result:
    """The ledger entry of ``run`` with its ids checked.

    Raises:
        SnapshotRefusal: ``no_ledger``, ``ledger_bad``.
    """
    path = _ledger_path(common, run)
    entry = _read_ledger(path)
    ids = (entry["base"], entry["commit"], entry["tree"])
    if entry["run"] != run or not all(OID_RE.fullmatch(oid or "") for oid in ids):
        _refuse(
            "ledger_bad",
            f"the ledger {path} is not an entry of run {run} with 40-hex base, commit "
            "and tree",
        )
    session = entry["session"]
    if not session:
        _refuse("ledger_bad", f"the ledger {path} has no session")
    return Result(
        run=run,
        session=session,
        base=str(entry["base"]),
        commit=str(entry["commit"]),
        tree=str(entry["tree"]),
        author_vendor=entry["author_vendor"],
    )


def _session_results(common: Path, session: str) -> list[Result]:
    """Every ledger entry of ``session`` (the runs that share their reviews).

    Raises:
        SnapshotRefusal: ``ledger_bad`` (an entry of the folder cannot be read).
    """
    folder = common / LEDGER_FOLDER
    if not folder.is_dir():
        return []
    found: list[Result] = []
    for path in sorted(folder.glob("*.json")):
        entry = _read_ledger(path)
        run = entry["run"]
        if entry["session"] == session and isinstance(run, str):
            found.append(_result(common, run))
    return found


# ---------------------------------------------------------------------------
# the event file of a run (reviews and voids; the ledger keeps its key set)
# ---------------------------------------------------------------------------


def _events_path(common: Path, run: str) -> Path:
    """``<git common dir>/{{PROJECT_NAME}}-results/<run>/events.jsonl``."""
    return common / LEDGER_FOLDER / run / EVENTS_NAME


def _now() -> str:
    """The current UTC time, ISO 8601 with microseconds (the event order)."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _read_events(common: Path, run: str) -> list[dict[str, Any]]:
    """The events of ``run`` in file order; none when the file is absent.

    Raises:
        SnapshotRefusal: ``events_bad`` (a line is not a JSON event object).
    """
    path = _events_path(common, run)
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _refuse("events_bad", f"cannot read {path}: {exc}")
    events: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data: object = json.loads(line)
        except json.JSONDecodeError as exc:
            _refuse("events_bad", f"{path} line {number} is not JSON: {exc}")
        if not isinstance(data, dict):
            _refuse("events_bad", f"{path} line {number} is not an object")
        event = cast(dict[str, Any], data)
        if event.get("event") not in (EVENT_REVIEW, EVENT_VOID):
            _refuse("events_bad", f"{path} line {number} has no known event kind")
        events.append(event)
    return events


def _append_event(common: Path, run: str, event: Mapping[str, Any]) -> None:
    """Append ``event`` as one JSON line (LF) to the event file of ``run``.

    Raises:
        SnapshotRefusal: ``events_bad`` when the file cannot be written.
    """
    path = _events_path(common, run)
    line = json.dumps(dict(event), sort_keys=True, separators=(",", ":")) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as out:
            out.write(line)
    except OSError as exc:
        _refuse("events_bad", f"cannot write {path}: {exc}")


@dataclass(frozen=True)
class Review:
    """One recorded review: its kind, run, time, key and the author vendor of the run.

    ``plan`` is the plan slug that the verdict names (None for an event without a
    verdict); ``reviewed_at`` is the time its input was seen (EA-39), None for an
    event recorded before EA-39.
    """

    kind: str
    run: str
    recorded: str
    key: dict[str, str]
    author_vendor: str | None
    plan: str | None = None
    reviewed_at: str | None = None

    def order(self) -> tuple[str, str, str]:
        """The review order: the time the input was seen, then the record time, run."""
        return (self.reviewed_at or self.recorded, self.recorded, self.run)


def _review_of(event: Mapping[str, Any], run: str) -> Review:
    """The ``review`` event of ``run`` as a Review.

    Raises:
        SnapshotRefusal: ``events_bad`` (a field is missing or of another type).
    """
    kind, recorded, key = event.get("kind"), event.get("recorded"), event.get("key")
    vendor = event.get("author_vendor")
    reviewed_at = event.get("reviewed_at")
    verdict = event.get("verdict")
    shaped = (
        kind in REVIEW_KINDS
        and isinstance(recorded, str)
        and isinstance(key, dict)
        and all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in cast(dict[object, object], key).items()
        )
        and (vendor is None or isinstance(vendor, str))
        and (reviewed_at is None or isinstance(reviewed_at, str))
        and (verdict is None or isinstance(verdict, dict))
    )
    if not shaped:
        _refuse("events_bad", f"a review event of run {run} has another shape: {event}")
    plan = (
        _plan_slug(cast(dict[str, object], verdict).get("target_plan"))
        if isinstance(verdict, dict)
        else None
    )
    return Review(
        kind=str(kind),
        run=run,
        recorded=str(recorded),
        key={
            str(name): str(value) for name, value in cast(dict[str, str], key).items()
        },
        author_vendor=cast(str | None, vendor),
        plan=plan,
        reviewed_at=cast(str | None, reviewed_at),
    )


def _session_reviews(common: Path, session: str) -> dict[str, Review]:
    """The latest review of each kind over every run of ``session``.

    The latest is the review whose input was seen last (EA-39): a review of an older
    tree that is recorded later does not take the place of a review of a newer tree.
    """
    latest: dict[str, Review] = {}
    for result in _session_results(common, session):
        for event in _read_events(common, result.run):
            if event.get("event") != EVENT_REVIEW:
                continue
            review = _review_of(event, result.run)
            held = latest.get(review.kind)
            if held is None or review.order() > held.order():
                latest[review.kind] = review
    return latest


# ---------------------------------------------------------------------------
# the replay batch of the last ``land replay`` (C − P)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Replay:
    """The replay batch of a run: the plan slug, P, the tree of C and C − P.

    ``files`` maps each packet path to its C bytes, or ``None`` for a delete.
    """

    path: Path
    plan: str
    parent: str
    tree: str
    files: dict[str, bytes | None]

    def landed(self, top: Path, rel: str) -> bytes | None:
        """The bytes of ``rel`` in C: the packet entry, else the blob of P."""
        if rel in self.files:
            return self.files[rel]
        return _blob(top, self.parent, rel)


def _replay(top: Path, common: Path, run: str) -> Replay:
    """The batch ``<run dir>/replay-batch.json`` and the tree it builds on its parent.

    Raises:
        SnapshotRefusal: ``no_replay`` (no batch: run ``land replay`` first),
            ``replay_bad`` (not one valid ``commit-batch/1`` packet) or
            ``git_failed``.
    """
    path = common / LEDGER_FOLDER / run / REPLAY_BATCH_NAME
    if not path.is_file():
        _refuse(
            "no_replay",
            f"no replay batch at {path}; run lanes.py land replay --snapshot "
            f"{RESULT_PREFIX}{run} --task <task.md> --check-only first",
        )
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _refuse("replay_bad", f"cannot read {path}: {exc}")
    cb = _commit_batch()
    raw = cast(dict[str, Any], data) if isinstance(data, dict) else {}
    packets = raw.get("packets")
    if raw.get("schema") != cb.BATCH_SCHEMA or not isinstance(packets, list):
        _refuse("replay_bad", f"{path} is not a {cb.BATCH_SCHEMA} batch")
    if len(cast(list[object], packets)) != 1:
        _refuse("replay_bad", f"{path} holds {len(packets)} packets, not one")
    try:
        packet = cb._parse_packet(packets[0])  # noqa: SLF001
        tree = str(cb.batch_tree(top, packet.parent, [packet]))
    except (cb.rp.Refusal, cb.Stopped) as exc:
        _refuse("replay_bad", f"the packet of {path} is refused: {exc}")
    except (cb.rp.GitError, OSError) as exc:
        _refuse("git_failed", f"building the tree of {path} failed: {exc}")
    files: dict[str, bytes | None] = {
        str(rel): bytes(item[1]) for rel, item in packet.files.items()
    }
    for rel in packet.deletes:
        files[str(rel)] = None
    return Replay(
        path=path,
        plan=str(packet.plan),
        parent=str(packet.parent),
        tree=tree,
        files=files,
    )


# ---------------------------------------------------------------------------
# scope: the items of design §9.3 and the void reviews
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Landed:
    """One commit of ``B..P``: its id, subject, plan slug and paths."""

    commit: str
    subject: str
    slug: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Void:
    """A review whose key no longer matches: its kind, reason, paths and both keys."""

    kind: str
    reason: str
    paths: tuple[str, ...]
    voided: dict[str, str]
    current: dict[str, str]

    def line(self) -> str:
        """``void <kind> <reason>[ <path>,<path>...]``."""
        tail = f" {','.join(self.paths)}" if self.paths else ""
        return f"void {self.kind} {self.reason}{tail}"


@dataclass(frozen=True)
class Scope:
    """What of C no reviewer read, for one run."""

    top: Path
    common: Path
    result: Result
    replay: Replay
    worker: Review | None
    integration: Review | None
    locks: list[str]
    records: list[str]
    corrections: list[str]
    context: list[Landed]
    # The plan of the worker review when it is not the plan of the replay (EA-39).
    worker_plan: str | None = None

    def item_lines(self) -> list[str]:
        """The ``scope_item`` lines, items 2 to 5 in order (item 1 waits for MEU-952)."""
        lines = [f"scope_item lock {rel}" for rel in self.locks]
        lines += [f"scope_item record {rel}" for rel in self.records]
        lines += [f"scope_item correction {rel}" for rel in self.corrections]
        for landed in self.context:
            lines += [f"scope_item context {landed.slug} {rel}" for rel in landed.paths]
        return lines


def _lock_items(top: Path, s_tree: str, replay: Replay) -> list[str]:
    """Item 2: each ``uv.lock`` or ``package-lock.json`` whose S and C bytes differ."""
    names: set[str] = set(replay.files)
    for treeish in (s_tree, replay.parent):
        names.update(
            _z_list(_git_bytes(top, "ls-tree", "-r", "-z", "--name-only", treeish))
        )
    found: list[str] = []
    for rel in sorted(names):
        if PurePosixPath(rel).name not in LOCK_NAMES:
            continue
        if _blob(top, s_tree, rel) != replay.landed(top, rel):
            found.append(rel)
    return found


def _write_entry(root: Path, rel: str, data: bytes | None) -> None:
    """Write one packet entry into the checkout ``root`` (``None`` deletes the file).

    Raises:
        SnapshotRefusal: ``record_failed`` when the file cannot be written.
    """
    path = root / rel
    try:
        if data is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        _refuse("record_failed", f"cannot write {path}: {exc}")


def _file_bytes(path: Path) -> bytes | None:
    """The bytes of the file ``path``; ``None`` when there is no file.

    Raises:
        SnapshotRefusal: ``record_failed`` when the file cannot be read.
    """
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        _refuse("record_failed", f"cannot read {path}: {exc}")


def _record_items(top: Path, result: Result, replay: Replay) -> list[str]:
    """Item 3: each junction file of C that the requests of S's handoffs do not produce.

    R is a shared checkout of P (the replay candidate recipe of ``lanes``, under the
    gate-candidate root as ``scope-<run>``) with every non-junction entry of C − P
    written into it; then ``lanes._apply_requests`` applies the integration requests
    of the handoffs there, as ``land replay`` did (lane: the plan slug, generation:
    ``B[:16]``, EA-3). A junction file whose R bytes differ from its C bytes is an
    item. With no junction file in C − P the requests changed none, so R is not built.
    R is removed at the end.

    Raises:
        SnapshotRefusal: ``record_failed[:<lanes reason>]`` or ``git_failed``.
    """
    lanes = _lanes()
    junction: tuple[str, ...] = tuple(lanes.JUNCTION_FILES)
    if not any(rel in replay.files for rel in junction):
        return []
    ew = _executor_worktree()
    candidate = Path(ew.gate_candidate_root()) / f"{SCOPE_CANDIDATE_PREFIX}{result.run}"
    if not ew._gate_candidate_contained(candidate):  # noqa: SLF001
        _refuse(
            "record_failed",
            f"{candidate} is not strictly inside {ew.gate_candidate_root()}",
        )
    found: list[str] = []
    try:
        identity = lanes._checked_identity(top)  # noqa: SLF001
        lanes._make_replay_candidate(top, candidate, replay.parent, identity)  # noqa: SLF001
        for rel, data in replay.files.items():
            if rel not in junction:
                _write_entry(candidate, rel, data)
        conflicts = io.StringIO()
        with contextlib.redirect_stdout(conflicts):
            lanes._apply_requests(  # noqa: SLF001
                candidate,
                f"{PLANS_DIR}/{replay.plan}",
                lane=replay.plan,
                generation=result.base[:16],
            )
        for rel in junction:
            if _file_bytes(candidate / rel) != replay.landed(top, rel):
                found.append(rel)
    except lanes.Refusal as exc:
        _refuse(f"record_failed:{exc.reason}", exc.detail)
    finally:
        try:
            lanes._drop_replay_candidate(candidate)  # noqa: SLF001
        except lanes.Refusal as exc:
            print(f"scope_warn {exc.reason} {exc.detail}", file=sys.stderr, flush=True)
    return found


def _handoff_rels(top: Path, plan: str, s_tree: str) -> list[str]:
    """The handoff set of the plan in S, as ``lanes._apply_requests`` finds it.

    ``lanes._handoff_set`` reads the ``meus`` of the plan's ``task.md``; a temporary
    folder holds S's ``task.md`` for it.

    Raises:
        SnapshotRefusal: ``plan_bad:<lanes reason>`` or ``io_error``.
    """
    lanes = _lanes()
    rel = f"{PLANS_DIR}/{plan}/task.md"
    task = _blob(top, s_tree, rel)
    try:
        with tempfile.TemporaryDirectory(prefix="scope-task-") as scratch:
            root = Path(scratch)
            if task is not None:
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_bytes(task)
            try:
                found = lanes._handoff_set(root, f"{PLANS_DIR}/{plan}")  # noqa: SLF001
            except lanes.Refusal as exc:
                _refuse(f"plan_bad:{exc.reason}", exc.detail)
    except OSError as exc:
        _refuse("io_error", f"cannot stage the task.md of {plan}: {exc}")
    return [str(item) for item in found]


def _frontmatter_end(lines: Sequence[str]) -> int | None:
    """The index of the closing ``---`` of a leading frontmatter, or None."""
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return None
    return next(
        (i for i in range(1, len(lines)) if lines[i].strip() == FRONTMATTER_FENCE),
        None,
    )


def _same_mark_key(old: str, new: str) -> bool:
    """True when both lines set the same top-level ``status`` or ``stop_gate`` key."""
    a, b = MARK_KEY_RE.match(old), MARK_KEY_RE.match(new)
    return a is not None and b is not None and a.group(1) == b.group(1)


def _status_cell_only(lines: Sequence[str], index: int, old: str, new: str) -> bool:
    """True when ``old`` and ``new`` are rows of one table that differ only in Status.

    The table runs up from ``index`` to its first row, the header, which a ``|---|``
    separator follows; the column is the header cell named ``Status``.
    """
    lanes = _lanes()
    if not (old.lstrip().startswith("|") and new.lstrip().startswith("|")):
        return False
    start = index
    while start > 0 and lines[start - 1].lstrip().startswith("|"):
        start -= 1
    if index <= start + 1 or not lanes._SEPARATOR_RE.fullmatch(  # noqa: SLF001
        lines[start + 1].strip()
    ):
        return False
    header: tuple[str, ...] = lanes._cells(lines[start])  # noqa: SLF001
    if STATUS_HEADER not in header:
        return False
    a: tuple[str, ...] = lanes._cells(old)  # noqa: SLF001
    b: tuple[str, ...] = lanes._cells(new)  # noqa: SLF001
    if len(a) != len(b) or len(a) != len(header):
        return False
    changed = {i for i in range(len(a)) if a[i] != b[i]}
    return changed == {header.index(STATUS_HEADER)}


def _marks_only(old: str, new: str, *, status_cells: bool) -> bool:
    """EA-6 (3) and (4): only frontmatter ``status``/``stop_gate`` lines and Status cells.

    The two texts must have the same lines in the same places; each line that
    differs is a top-level ``status:`` or ``stop_gate:`` line of the frontmatter,
    or (``status_cells``, the plan's ``task.md``) a task-table row whose only
    changed cell is the Status cell.
    """
    if old.endswith("\n") != new.endswith("\n"):
        return False
    a, b = old.splitlines(), new.splitlines()
    end = _frontmatter_end(a)
    if len(a) != len(b) or end != _frontmatter_end(b):
        return False
    for index, (line_a, line_b) in enumerate(zip(a, b, strict=True)):
        if line_a == line_b:
            continue
        if end is not None and 0 < index < end and _same_mark_key(line_a, line_b):
            continue
        if status_cells and _status_cell_only(a, index, line_a, line_b):
            continue
        return False
    return True


def _sections(lines: Sequence[str]) -> list[tuple[str, list[str]]]:
    """``(heading, body lines)`` per Markdown heading; the preamble has the heading ``""``."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in lines:
        if HEADING_RE.match(line):
            sections.append((line.strip(), []))
        else:
            sections[-1][1].append(line)
    return sections


def _is_subsequence(old: Sequence[str], new: Sequence[str]) -> bool:
    """True when every line of ``old`` is in ``new`` in order (``new`` only adds lines)."""
    remaining = iter(new)
    return all(any(line == other for other in remaining) for line in old)


def _request_row(line: str) -> tuple[str, str] | None:
    """``(Id, Request)`` of one request-table row, read by ``lanes._request_rows``."""
    lanes = _lanes()
    text = "\n".join([lanes.REQUESTS_HEADING, "| Id | Request |", line])
    rows: list[tuple[str, str]] = lanes._request_rows(text)  # noqa: SLF001
    return rows[0] if len(rows) == 1 else None


def _derived_metrics(old: str, new: str) -> bool:
    """EA-6 (1): two metrics-row requests that differ only in the derived cells."""
    lanes = _lanes()
    if not (old.startswith(METRICS_ROW_PREFIX) and new.startswith(METRICS_ROW_PREFIX)):
        return False
    headers: tuple[str, ...] = tuple(lanes.METRICS_HEADERS)
    a: tuple[str, ...] = lanes._cells(old[len(METRICS_ROW_PREFIX) :])  # noqa: SLF001
    b: tuple[str, ...] = lanes._cells(new[len(METRICS_ROW_PREFIX) :])  # noqa: SLF001
    if len(a) != len(headers) or len(b) != len(headers):
        return False
    derived = {headers.index(name) for name in DERIVED_METRICS_HEADERS}
    changed = {i for i in range(len(a)) if a[i] != b[i]}
    return bool(changed) and changed <= derived


def _derived_requests(old: Sequence[str], new: Sequence[str]) -> bool:
    """EA-6 (1) in the request section: each changed line is the metrics-row request
    with the same Id at the same place, changed only in its derived cells."""
    if len(old) != len(new):
        return False
    for line_a, line_b in zip(old, new, strict=True):
        if line_a == line_b:
            continue
        row_a, row_b = _request_row(line_a), _request_row(line_b)
        if row_a is None or row_b is None or row_a[0] != row_b[0]:
            return False
        if not _derived_metrics(row_a[1], row_b[1]):
            return False
    return True


def _handoff_derived_only(old: str, new: str) -> bool:
    """EA-6 (1) and (2) for one handoff: derived metrics cells and appended lines.

    The heading sequence stays. In the integration-request section only the one
    metrics-row request of W may change, in its derived cells; the three record
    sections (``APPEND_SECTIONS``) may only gain lines; every other section is equal.
    """
    lanes = _lanes()
    if old.endswith("\n") != new.endswith("\n"):
        return False
    a, b = _sections(old.splitlines()), _sections(new.splitlines())
    if [heading for heading, _ in a] != [heading for heading, _ in b]:
        return False
    rows: list[tuple[str, str]] = lanes._request_rows(old)  # noqa: SLF001
    metrics = [rid for rid, request in rows if request.startswith(METRICS_ROW_PREFIX)]
    for (heading, body_a), (_, body_b) in zip(a, b, strict=True):
        if body_a == body_b:
            continue
        if heading in APPEND_SECTIONS:
            if not _is_subsequence(body_a, body_b):
                return False
        elif heading == lanes.REQUESTS_HEADING:
            if len(metrics) != 1 or not _derived_requests(body_a, body_b):
                return False
        else:
            return False
    return True


def _derived_only(
    rel: str,
    before: bytes | None,
    after: bytes | None,
    *,
    plan: str,
    handoffs: Iterable[str],
) -> bool:
    """True when the change of ``rel`` from W to S is one of the EA-6 exceptions."""
    if rel == f"{REFLECTIONS_DIR}/{plan}-reflection.md":
        return before is None
    if before is None or after is None:
        return False
    try:
        old, new = before.decode("utf-8"), after.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if rel == f"{PLANS_DIR}/{plan}/task.md":
        return _marks_only(old, new, status_cells=True)
    if rel == f"{PLANS_DIR}/{plan}/implementation-plan.md":
        return _marks_only(old, new, status_cells=False)
    if rel in handoffs:
        return _handoff_derived_only(old, new)
    return False


def _correction_items(top: Path, plan: str, w_tree: str, s_tree: str) -> list[str]:
    """Item 4: each path whose S bytes differ from the reviewed W tree, EA-6 aside."""
    paths = _changed_paths(top, w_tree, s_tree)
    if not paths:
        return []
    handoffs = _handoff_rels(top, plan, s_tree)
    return [
        rel
        for rel in paths
        if not _derived_only(
            rel,
            _blob(top, w_tree, rel),
            _blob(top, s_tree, rel),
            plan=plan,
            handoffs=handoffs,
        )
    ]


def _first_parent(top: Path, commit: str) -> str:
    """The first parent of ``commit``, or the empty tree for a root commit."""
    ids = _git(top, "rev-list", "--parents", "-n", "1", commit).split()
    return ids[1] if len(ids) > 1 else EMPTY_TREE


def _landed(top: Path, base: str, parent: str) -> list[Landed]:
    """Item 5: each commit of ``B..P`` (oldest first) with its plan slug and paths.

    The slug is that of the first ``docs/execution/plans/<slug>/`` path, else the
    first ``YYYY-MM-DD-<words>`` slug of the subject, else ``-``.
    """
    landed: list[Landed] = []
    for commit in _git(top, "rev-list", "--reverse", f"{base}..{parent}").split():
        subject = _git(top, "log", "-1", "--format=%s", commit)
        paths = _changed_paths(top, _first_parent(top, commit), commit)
        slug = next(
            (m.group(1) for m in (PLAN_PATH_RE.match(rel) for rel in paths) if m),
            None,
        )
        if slug is None:
            named = PLAN_SLUG_RE.search(subject)
            slug = named.group(1) if named else "-"
        landed.append(
            Landed(commit=commit, subject=subject, slug=slug, paths=tuple(paths))
        )
    return landed


def _scope_of(run_arg: str) -> Scope:
    """The scope of ``run`` in the main repository of the working folder (I1).

    Raises:
        SnapshotRefusal: the ledger, replay, event, record and git refusals.
    """
    run = _check_run(run_arg)
    main = Path.cwd()
    top, common = _top_dir(main), _common_dir(main)
    result = _result(common, run)
    replay = _replay(top, common, run)
    reviews = _session_reviews(common, result.session)
    worker = reviews.get("worker")
    # A worker review of another plan read no delta of this plan: W is B (EA-39).
    worker_plan = (
        worker.plan
        if worker is not None and worker.plan is not None and worker.plan != replay.plan
        else None
    )
    w_tree = (
        worker.key.get("tree", "")
        if worker is not None and worker_plan is None
        else _git(top, "rev-parse", f"{result.base}^{{tree}}")
    )
    if not OID_RE.fullmatch(w_tree):
        _refuse("events_bad", f"the worker review of {worker} has no 40-hex tree key")
    return Scope(
        worker_plan=worker_plan,
        top=top,
        common=common,
        result=result,
        replay=replay,
        worker=worker,
        integration=reviews.get("integration"),
        locks=_lock_items(top, result.tree, replay),
        records=_record_items(top, result, replay),
        corrections=_correction_items(top, replay.plan, w_tree, result.tree),
        context=_landed(top, result.base, replay.parent),
    )


def _key_void(held: Mapping[str, str], current: Mapping[str, str]) -> str | None:
    """``main_moved`` (another parent), ``correction`` (another tree) or None."""
    if held.get("parent") != current["parent"]:
        return "main_moved"
    if held.get("tree") != current["tree"]:
        return "correction"
    return None


def _gate_key(gate_run: Path) -> tuple[bool, dict[str, str]]:
    """(passed and completed, the candidate ``parent`` and ``tree``) of ``gate.json``.

    Raises:
        SnapshotRefusal: ``gate_bad`` (no file, or no candidate parent and tree).
    """
    path = gate_run / GATE_RECORD_NAME
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _refuse("gate_bad", f"cannot read {path}: {exc}")
    record = cast(dict[str, Any], data) if isinstance(data, dict) else {}
    candidate = record.get("candidate")
    summary = record.get("summary")
    if not isinstance(candidate, dict) or not isinstance(summary, dict):
        _refuse("gate_bad", f"{path} holds no candidate and summary objects")
    held = cast(dict[str, object], candidate)
    parent, tree = held.get("parent"), held.get("tree")
    if not isinstance(parent, str) or not isinstance(tree, str):
        _refuse("gate_bad", f"{path} names no candidate parent and tree")
    passed = cast(dict[str, object], summary).get("passed") is True
    return passed and record.get("completed") is True, {"parent": parent, "tree": tree}


def _voids(scope: Scope, gate_run: Path | None) -> list[Void]:
    """I3: the reviews whose key no longer matches the run and its replay.

    A worker review of another plan is void (``plan``, EA-39); else a correction item
    voids the worker review (of the changed paths); another P voids the integration
    review and the gate (``main_moved``); the same P with another C tree voids them
    as ``correction``. A gate that did not pass is ``not_passed``.
    """
    current = {"parent": scope.replay.parent, "tree": scope.replay.tree}
    voids: list[Void] = []
    if scope.worker is not None and scope.worker_plan is not None:
        voids.append(
            Void(
                kind="worker",
                reason="plan",
                paths=(),
                voided=scope.worker.key,
                current={"plan": scope.replay.plan},
            )
        )
    elif scope.worker is not None and scope.corrections:
        voids.append(
            Void(
                kind="worker",
                reason="correction",
                paths=tuple(scope.corrections),
                voided=scope.worker.key,
                current={"tree": scope.result.tree},
            )
        )
    if scope.integration is not None:
        reason = _key_void(scope.integration.key, current)
        if reason is not None:
            voids.append(
                Void("integration", reason, (), scope.integration.key, current)
            )
    if gate_run is not None:
        passed, key = _gate_key(gate_run)
        reason = "not_passed" if not passed else _key_void(key, current)
        if reason is not None:
            voids.append(Void("gate", reason, (), key, current))
    return voids


def _log_voids(scope: Scope, voids: Sequence[Void]) -> None:
    """Write each void to the run's event file once (an equal void is not repeated)."""
    seen: set[tuple[object, object, tuple[str, ...], str, str]] = {
        (
            event.get("kind"),
            event.get("reason"),
            tuple(str(rel) for rel in event.get("paths") or ()),
            json.dumps(event.get("voided"), sort_keys=True),
            json.dumps(event.get("current"), sort_keys=True),
        )
        for event in _read_events(scope.common, scope.result.run)
        if event.get("event") == EVENT_VOID
    }
    for void in voids:
        mark = (
            void.kind,
            void.reason,
            void.paths,
            json.dumps(void.voided, sort_keys=True),
            json.dumps(void.current, sort_keys=True),
        )
        if mark in seen:
            continue
        seen.add(mark)
        _append_event(
            scope.common,
            scope.result.run,
            {
                "event": EVENT_VOID,
                "kind": void.kind,
                "reason": void.reason,
                "paths": list(void.paths),
                "voided": void.voided,
                "current": void.current,
                "run": scope.result.run,
                "session": scope.result.session,
                "recorded": _now(),
            },
        )


# ---------------------------------------------------------------------------
# brief: the review prompt and the dispatch per author vendor
# ---------------------------------------------------------------------------


def _public_names(source: bytes) -> list[str] | None:
    """The top-level public ``def`` and ``class`` names of a module; None if unparsed."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and not node.name.startswith("_")
    ]


def _interfaces(top: Path, landed: Landed) -> list[str]:
    """One line per changed Python module of ``landed``: its public names."""
    lines: list[str] = []
    for rel in landed.paths:
        if not rel.endswith(".py"):
            continue
        source = _blob(top, landed.commit, rel)
        if source is None:
            lines.append(f"- `{rel}`: deleted")
            continue
        names = _public_names(source)
        if names is None:
            lines.append(f"- `{rel}`: not parsed (not valid Python)")
        elif names:
            lines.append(f"- `{rel}`: {', '.join(f'`{name}`' for name in names)}")
        else:
            lines.append(f"- `{rel}`: no public names")
    return lines


def _c_commit(scope: Scope) -> str:
    """A commit of the C tree on P (no ref), the right side of the range-diff."""
    commit = _git(
        scope.top,
        "-c",
        "commit.gpgsign=false",
        "commit-tree",
        scope.replay.tree,
        "-p",
        scope.replay.parent,
        "-m",
        f"result {scope.result.run}",
    )
    if not OID_RE.fullmatch(commit):
        _refuse("git_failed", f"git commit-tree of the C tree gave {commit!r}")
    return commit


def _deltas(scope: Scope) -> list[tuple[str, str | None]]:
    """``(delta, author vendor)``: the worker delta, then a correction delta if any.

    The worker delta is the run that holds the worker review of the session (this
    run when none does); a correction is this run when it is another run with
    another tree, and it carries its own vendor (h). A worker review of another plan
    is void (EA-39), so the delta is reviewed as if no review held it.
    """
    worker = scope.worker if scope.worker_plan is None else None
    if worker is None:
        return [("worker", scope.result.author_vendor)]
    deltas: list[tuple[str, str | None]] = [("worker", worker.author_vendor)]
    if worker.run != scope.result.run and worker.key.get("tree") != scope.result.tree:
        deltas.append(("correction", scope.result.author_vendor))
    return deltas


def _prompt(scope: Scope, c_commit: str, range_diff: str) -> str:
    """The review prompt text (I2)."""
    result, replay = scope.result, scope.replay
    items = scope.item_lines()
    lines = [
        f"# Integration review: run {result.run}",
        "",
        f"- Plan: `{replay.plan}`",
        f"- Session: `{result.session}`",
        f"- Worker delta B..S: `{result.base}..{result.commit}`",
        f"- Replay P..C: `{replay.parent}..{c_commit}` (C tree `{replay.tree}`)",
        "",
        "## Scope items",
        "",
        *([f"- {line}" for line in items] or ["- None: items 1 to 5 are empty."]),
        "",
        "## Range-diff B..S against P..C",
        "",
        "```text",
        range_diff or "(no output)",
        "```",
        "",
        "## Sessions landed between B and P",
        "",
    ]
    if not scope.context:
        lines += ["None: P is B.", ""]
    for landed in scope.context:
        lines += [
            f"### {landed.slug}: commit `{landed.commit}`",
            "",
            f"Subject: {landed.subject}",
            "",
            "Write set:",
            "",
            *[f"- `{rel}`" for rel in landed.paths],
            "",
            "Interfaces changed (public names of each changed Python module):",
            "",
            *(_interfaces(scope.top, landed) or ["- none"]),
            "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def _working_tree(clone: Path, marker: Mapping[str, str]) -> tuple[str, str]:
    """(B, the tree of the clone's working tree), the index, HEAD and files untouched.

    A temporary index is seeded with B (``read-tree``), then ``add -A`` reads the
    working tree (``.gitignore`` holds) and ``write-tree`` gives the tree.

    Raises:
        SnapshotRefusal: ``git_failed``.
    """
    base = _git(clone, "rev-parse", "--verify", "-q", f"{marker['parent']}^{{commit}}")
    with tempfile.TemporaryDirectory(prefix="result-snapshot-") as scratch:
        index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        _git(clone, "read-tree", base, extra_env=index)
        _git(clone, "add", "-A", "--", ".", extra_env=index)
        tree = _git(clone, "write-tree", extra_env=index)
    if not OID_RE.fullmatch(tree):
        _refuse("git_failed", f"git write-tree in {clone} gave {tree!r}")
    return base, tree


def _commit_on(clone: Path, tree: str, base: str, message: str) -> str:
    """``commit-tree <tree> -p <base>`` in ``clone``: no hooks, no signing, no ref.

    Raises:
        SnapshotRefusal: ``git_failed``.
    """
    commit = _git(
        clone,
        "-c",
        "commit.gpgsign=false",
        "commit-tree",
        tree,
        "-p",
        base,
        "-m",
        message,
    )
    if not OID_RE.fullmatch(commit):
        _refuse("git_failed", f"git commit-tree in {clone} gave {commit!r}")
    return commit


def _write_new(path: Path, text: str, what: str) -> None:
    """Create ``path`` with ``text`` (LF); it must not exist.

    Raises:
        SnapshotRefusal: ``exists`` (the file is there), ``out_bad`` (it cannot be
        written).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError:
        _refuse("exists", f"the {what} {path} is already there; it is written once")
    except OSError as exc:
        _refuse("out_bad", f"cannot write the {what} {path}: {exc}")


def _dispatch_dir(dispatch_arg: str | None) -> Path:
    """The review dispatch folder that a new seen record names (EA-40, review R1-F1).

    It is the wrapper's ``<OutputDir>/<DispatchId>`` of the review that will read the
    input. The record is taken before that dispatch starts, and the wrapper makes the
    folder when it starts (EA-41), so the folder is not there yet. This function does
    not make the folder: the wrapper refuses a folder that exists.

    Raises:
        SnapshotRefusal: ``dispatch_missing`` (no ``--dispatch-dir``),
        ``dispatch_bad`` (not one canonical spelling of the folder, EA-42),
        ``seen_late`` (the folder is there: the dispatch started, and it can read
        another tree).
    """
    if not dispatch_arg:
        _refuse(
            "dispatch_missing",
            "--dispatch-dir <dir> names the review dispatch folder "
            "(<OutputDir>/<DispatchId> of the wrapper) that will read this input",
        )
    raw = Path(dispatch_arg)
    folder = raw.resolve()
    _check_spelling(raw, folder)
    _refuse_started(folder)
    return folder


def _check_spelling(raw: Path, folder: Path) -> None:
    """EA-42 (review R1-F1, round 5): one spelling names one dispatch folder.

    Windows reads a name part that ends in a dot or a space as the name without
    them, but ``Path.resolve`` keeps them while the folder is not there. So
    ``<dir>.`` and ``<dir>`` would claim two folders that are one. The check is the
    same on all platforms, as the wrapper's ``-DispatchId`` rule is.

    Raises:
        SnapshotRefusal: ``dispatch_bad`` when the last part of ``folder`` is not a
        ``-DispatchId`` (or ends in a dot), or a name part of ``raw`` or ``folder``
        ends in a dot or a space.
    """
    leaf = folder.name
    if not DISPATCH_ID_RE.fullmatch(leaf) or leaf.endswith("."):
        _refuse(
            "dispatch_bad",
            f"the dispatch folder name {leaf!r} is not a -DispatchId of the wrapper "
            "(a letter or digit, then letters, digits, '.', '_' or '-'; not ending "
            "in '.')",
        )
    raw_parts = raw.parts[1:] if raw.anchor else raw.parts
    names = [name for name in raw_parts if name not in (".", "..")]
    names += list(folder.parts[1:] if folder.anchor else folder.parts)
    for name in names:
        if name != name.rstrip(ALIAS_TAIL):
            _refuse(
                "dispatch_bad",
                f"the dispatch folder {raw.as_posix()!r} has the name part {name!r}, "
                "which ends in a dot or a space; Windows reads it as another "
                "spelling of a folder, so name the folder without them",
            )


def _folder_key(folder: Path) -> str:
    """EA-42: the identity of a folder name, as the wrapper's Get-RunDirIdentityKey.

    Each name part loses its trailing dots and spaces, and the name is upper case,
    so the Windows spellings of one folder give one key.
    """
    names = folder.as_posix().split("/")
    return "/".join(name.rstrip(ALIAS_TAIL) for name in names).upper()


def _refuse_started(folder: Path) -> None:
    """EA-41 (review R1-F1, round 4): refuse a dispatch folder that is there.

    Raises:
        SnapshotRefusal: ``seen_late`` when ``folder`` exists.
    """
    if folder.exists():
        _refuse(
            "seen_late",
            f"{folder.as_posix()} is already there, so its dispatch started; take the "
            "seen record before the dispatch starts, with a new -DispatchId",
        )


def _claim_path(common: Path, folder: Path) -> Path:
    """``<git common dir>/<ledger folder>/_seen-claims/<sha256 of the folder>.json``.

    The hash is of the folder identity key (EA-42), so two spellings of one folder
    give one claim file.
    """
    name = _folder_key(folder).encode("utf-8")
    return (
        common
        / LEDGER_FOLDER
        / SEEN_CLAIMS
        / f"{hashlib.sha256(name).hexdigest()}.json"
    )


def _claim_dispatch(common: Path, folder: Path, seen_path: Path) -> Path:
    """EA-41 (review R1-F1, round 4): claim ``folder`` for one seen record.

    The claim file is made once (exclusive create), so a second seen record that
    names the same folder before its dispatch starts is refused. The folder must
    still not exist after the claim is made.

    Raises:
        SnapshotRefusal: ``dispatch_claimed`` (another seen record claimed the
        folder), ``seen_late`` (the dispatch started), ``out_bad`` (the claim cannot
        be written).
    """
    claim = _claim_path(common, folder)
    text = json.dumps(
        {"dispatch_dir": folder.as_posix(), "seen": seen_path.as_posix(), "at": _now()},
        indent=2,
    )
    try:
        claim.parent.mkdir(parents=True, exist_ok=True)
        with claim.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
    except FileExistsError:
        _refuse(
            "dispatch_claimed",
            f"another seen record claimed {folder.as_posix()} ({claim.as_posix()}); "
            "each review dispatch has one seen record, taken before it starts, with a "
            "new -DispatchId",
        )
    except OSError as exc:
        _refuse("out_bad", f"cannot write the dispatch claim {claim}: {exc}")
    try:
        _refuse_started(folder)
    except SnapshotRefusal:
        _release_claim(claim)
        raise
    return claim


def _release_claim(claim: Path) -> None:
    """Remove the claim of a seen record that was not written (EA-41).

    A claim that cannot be removed keeps its folder claimed; the caller then uses a
    new ``-DispatchId``, so the warning names the file.
    """
    try:
        claim.unlink()
    except OSError as exc:
        print(f"claim_left {claim.as_posix()}: {exc}", file=sys.stderr)


def _seen(clone_arg: str, out_arg: str, dispatch_arg: str | None = None) -> int:
    """EA-39 ``seen``: record the clone's working tree that a worker review will read.

    The tree is kept as the commit ``refs/fleet/seen/<commit>`` on B in the clone and
    in the main repository that the marker names, so ``review`` can check it later.
    The record names the dispatch folder of that review (EA-40, review R1-F1) and
    claims it before that dispatch starts (EA-41).
    """
    out = Path(out_arg).resolve()
    if out.exists():
        _refuse("exists", f"the seen record {out} is already there; it is written once")
    dispatch = _dispatch_dir(dispatch_arg)
    clone = Path(clone_arg).resolve()
    marker = _clone_marker(clone)
    base, tree = _working_tree(clone, marker)
    commit = _commit_on(clone, tree, base, f"seen {marker['slug']}")
    ref = f"{SEEN_PREFIX}{commit}"
    _git(clone, "update-ref", ref, commit)
    main = Path(marker["main"]).resolve()
    if _ref(main, ref) != commit:
        _git(
            main,
            "fetch",
            "--quiet",
            "--no-tags",
            "--no-write-fetch-head",
            "--",
            str(clone),
            f"+{ref}:{ref}",
        )
    if _ref(main, ref) != commit:
        _refuse("git_failed", f"{ref} in {main} is not {commit} after the fetch")
    record = {
        "schema_version": SEEN_SCHEMA,
        "kind": "worker",
        "clone": clone.as_posix(),
        "base": base,
        "commit": commit,
        "tree": tree,
        "dispatch_dir": dispatch.as_posix(),
        "taken": _now(),
    }
    claim = _claim_dispatch(_common_dir(main), dispatch, out)  # EA-41
    try:
        _write_new(out, json.dumps(record, indent=2) + "\n", "seen record")
    except SnapshotRefusal:
        _release_claim(claim)
        raise
    print(f"seen_ok clone={clone.as_posix()} tree={tree} out={out.as_posix()}")
    return EXIT_OK


def _take(clone_arg: str, run_arg: str) -> int:
    """S1 ``take``: snapshot the clone's working tree as ``refs/fleet/result/<run>``."""
    run = _check_run(run_arg)
    clone = Path(clone_arg).resolve()
    marker = _clone_marker(clone)
    ref = f"{RESULT_PREFIX}{run}"
    if _ref(clone, ref):
        _refuse("exists", f"{ref} already exists in {clone}; a run is taken once")
    base, tree = _working_tree(clone, marker)
    base_tree = _git(clone, "rev-parse", f"{base}^{{tree}}")
    if tree == base_tree:
        _refuse("empty", f"the working tree of {clone} has no change against {base}")
    commit = _commit_on(clone, tree, base, f"result {run}")
    written = _git_run(clone, "update-ref", ref, commit, "")
    if written.returncode != 0:
        if _ref(clone, ref):
            _refuse("exists", f"{ref} appeared in {clone} during the take")
        _refuse(
            "git_failed",
            f"git update-ref {ref} in {clone} exited {written.returncode}: "
            f"{written.stderr.strip()}",
        )
    print(f"snapshot_ok {run} base={base} commit={commit} tree={tree}")
    return EXIT_OK


def _status_vendor(status_arg: str) -> str:
    """I4: the vendor of the worker dispatch, from the ``cli`` of its status file.

    The ``author_vendor`` key of ``dispatch-status.v1`` names the author that a
    review dispatch checks, not the vendor of the dispatch, so it is not read.

    Raises:
        SnapshotRefusal: ``status_bad`` (no ``dispatch-status.v1`` file with a known
        ``cli``).
    """
    path = Path(status_arg)
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _refuse("status_bad", f"cannot read the status file {path}: {exc}")
    status = cast(dict[str, object], data) if isinstance(data, dict) else {}
    if status.get("schema_version") != STATUS_SCHEMA:
        _refuse("status_bad", f"{path} is not a {STATUS_SCHEMA} file")
    cli = status.get("cli")
    if not isinstance(cli, str) or cli not in VENDOR_OF_CLI:
        _refuse(
            "status_bad",
            f"{path} has the cli {cli!r}, not one of {sorted(VENDOR_OF_CLI)}",
        )
    return VENDOR_OF_CLI[cli]


def _fetch(
    clone_arg: str,
    run_arg: str,
    session: str | None,
    author_vendor: str | None,
    status: str | None = None,
) -> int:
    """S2 ``fetch``: copy the result ref into the main repository and write the ledger."""
    run = _check_run(run_arg)
    if status is not None:
        vendor = _status_vendor(status)
        if author_vendor is not None and author_vendor != vendor:
            _refuse(
                "vendor_conflict",
                f"--author-vendor {author_vendor} differs from the vendor {vendor} "
                f"of the worker dispatch in {status}",
            )
        author_vendor = vendor
    clone = Path(clone_arg).resolve()
    marker = _clone_marker(clone)
    ref = f"{RESULT_PREFIX}{run}"
    commit = _ref(clone, ref)
    if not commit:
        _refuse("no_result", f"{ref} does not exist in {clone} (run take first)")
    base = marker["parent"]
    parents = _git(clone, "rev-list", "--parents", "-n", "1", commit).split()[1:]
    if parents != [base]:
        _refuse("base", f"{ref} has the parents {parents}, not the clone base {base}")
    main = Path(marker["main"]).resolve()
    common = _common_dir(main)
    ledger = _ledger_path(common, run)
    held = _ref(main, ref)
    if held and held != commit:
        _refuse("exists", f"{ref} in {main} is {held}, not the clone's {commit}")
    if ledger.is_file():
        prior = _read_ledger(ledger)
        if prior["commit"] != commit:
            _refuse("exists", f"the ledger {ledger} names {prior['commit']}")
    if not held:
        _git(
            main,
            "fetch",
            "--quiet",
            "--no-tags",
            "--no-write-fetch-head",
            "--",
            str(clone),
            f"{ref}:{ref}",
        )
    fetched = _ref(main, ref)
    if fetched != commit:
        _refuse("git_failed", f"{ref} in {main} is {fetched!r} after the fetch")
    tree = _git(main, "rev-parse", f"{commit}^{{tree}}")
    entry: dict[str, str | None] = {
        "schema": LEDGER_SCHEMA,
        "run": run,
        "clone": clone.as_posix(),
        "base": base,
        "commit": commit,
        "tree": tree,
        "session": session if session else marker["slug"],
        "author_vendor": author_vendor,
    }
    _write_ledger(ledger, entry)
    print(f"fetch_ok {run} commit={commit}")
    return EXIT_OK


def _drop(run_arg: str) -> int:
    """S2 ``drop``: delete the result ref in both repositories; the ledger stays."""
    run = _check_run(run_arg)
    main = Path.cwd()
    ledger = _ledger_path(_common_dir(main), run)
    entry = _read_ledger(ledger)
    ref = f"{RESULT_PREFIX}{run}"
    if _ref(main, ref):
        _git(main, "update-ref", "-d", ref)
    clone_text = entry["clone"]
    if clone_text:
        clone = Path(clone_text)
        if (clone / ".git").is_dir() and _ref(clone, ref):
            _git(clone, "update-ref", "-d", ref)
    print(f"drop_ok {run}")
    return EXIT_OK


def _plan_slug(target: object) -> str | None:
    """The plan slug that a verdict ``target_plan`` names, or None.

    A real review names ``docs/execution/plans/<slug>/implementation-plan.md``; a bare
    ``YYYY-MM-DD-<words>`` slug is accepted too.
    """
    if not isinstance(target, str):
        return None
    text = target.strip().replace("\\", "/")
    named = PLAN_PATH_RE.search(text)
    if named:
        return named.group(1)
    return text if PLAN_SLUG_RE.fullmatch(text) else None


def _review_plans(top: Path, common: Path, run: str, result: Result) -> frozenset[str]:
    """The plan slugs that a review of ``run`` may name (EA-37).

    With a replay batch, the plan of the batch. Without one (a worker review before
    ``land replay``), each plan whose folder the result changes from B to S; none when
    the result changes no plan folder.

    Raises:
        SnapshotRefusal: the ``_replay`` refusals, ``git_failed``.
    """
    if (common / LEDGER_FOLDER / run / REPLAY_BATCH_NAME).is_file():
        return frozenset({_replay(top, common, run).plan})
    found: set[str] = set()
    for rel in _changed_paths(top, result.base, result.commit):
        named = PLAN_PATH_RE.match(rel)
        if named:
            found.add(named.group(1))
    return frozenset(found)


def _read_verdict(
    verdict_arg: str, plans: frozenset[str]
) -> tuple[Path, str, dict[str, object]]:
    """(path, sha256, data) of an ``approved`` ``review-verdict.v1`` file of the plan.

    ``plans`` holds the plan slugs the verdict may name; when it is empty, the verdict
    must still name a plan.

    Raises:
        SnapshotRefusal: ``verdict_bad`` (it cannot be read, is of another schema, is
        not ``approved``, names no plan or names a plan that is not in ``plans``).
    """
    path = Path(verdict_arg).resolve()
    try:
        raw = path.read_bytes()
        data: object = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _refuse("verdict_bad", f"cannot read the verdict {path}: {exc}")
    verdict = cast(dict[str, object], data) if isinstance(data, dict) else {}
    if verdict.get("schema_version") != VERDICT_SCHEMA:
        _refuse("verdict_bad", f"{path} is not a {VERDICT_SCHEMA} file")
    if verdict.get("verdict") != VERDICT_APPROVED:
        _refuse(
            "verdict_bad",
            f"{path} has the verdict {verdict.get('verdict')!r}; only an "
            f"{VERDICT_APPROVED!r} verdict records a review",
        )
    target = verdict.get("target_plan")
    slug = _plan_slug(target)
    if slug is None:
        _refuse("verdict_bad", f"{path} names no plan in target_plan ({target!r})")
    if plans and slug not in plans:
        _refuse(
            "verdict_bad",
            f"{path} is a verdict of the plan {slug}; this review is of "
            f"{', '.join(sorted(plans))}",
        )
    return path, hashlib.sha256(raw).hexdigest(), verdict


def _bound_review(
    common: Path, session: str, kind: str, path: Path, digest: str
) -> Review | None:
    """The first review of ``kind`` in ``session`` that recorded this verdict file.

    The verdict is the same when both its path and its sha256 are the same. A verdict
    is bound to the key it was first recorded with (EA-37): recording the same file
    again keeps that key, so only new review evidence moves W or the integration key.

    Raises:
        SnapshotRefusal: ``ledger_bad`` or ``events_bad``.
    """
    first: Review | None = None
    for result in _session_results(common, session):
        for event in _read_events(common, result.run):
            if event.get("event") != EVENT_REVIEW or event.get("kind") != kind:
                continue
            held = event.get("verdict")
            if not isinstance(held, dict):
                continue
            seen = cast(dict[str, object], held)
            same_path = os.path.normcase(str(seen.get("path"))) == os.path.normcase(
                path.as_posix()
            )
            if seen.get("sha256") != digest or not same_path:
                continue
            review = _review_of(event, result.run)
            if first is None or (review.recorded, review.run) < (
                first.recorded,
                first.run,
            ):
                first = review
    return first


def _read_seen(seen_arg: str) -> tuple[Path, str, dict[str, object]]:
    """(path, sha256, data) of a ``review-seen.v1`` record.

    Raises:
        SnapshotRefusal: ``seen_bad`` (it cannot be read or is of another schema).
    """
    path = Path(seen_arg).resolve()
    try:
        raw = path.read_bytes()
        data: object = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _refuse("seen_bad", f"cannot read the seen record {path}: {exc}")
    record = cast(dict[str, object], data) if isinstance(data, dict) else {}
    if record.get("schema_version") != SEEN_SCHEMA:
        _refuse("seen_bad", f"{path} is not a {SEEN_SCHEMA} record")
    if record.get("kind") not in REVIEW_KINDS or not isinstance(
        record.get("taken"), str
    ):
        _refuse("seen_bad", f"{path} names no review kind and time")
    return path, hashlib.sha256(raw).hexdigest(), record


def _same_file(held: object, path: Path, digest: str) -> bool:
    """True when the event field ``held`` names ``path`` with the sha256 ``digest``."""
    if not isinstance(held, dict):
        return False
    named = cast(dict[str, object], held)
    same_path = os.path.normcase(str(named.get("path"))) == os.path.normcase(
        path.as_posix()
    )
    return same_path and named.get("sha256") == digest


def _seen_use(
    common: Path, session: str, path: Path, digest: str
) -> tuple[Review, dict[str, Any]] | None:
    """The first review of ``session`` that used the seen record, with its event.

    Raises:
        SnapshotRefusal: ``ledger_bad`` or ``events_bad``.
    """
    first: tuple[Review, dict[str, Any]] | None = None
    for result in _session_results(common, session):
        for event in _read_events(common, result.run):
            if event.get("event") != EVENT_REVIEW:
                continue
            if not _same_file(event.get("seen"), path, digest):
                continue
            review = _review_of(event, result.run)
            if first is None or (review.recorded, review.run) < (
                first[0].recorded,
                first[0].run,
            ):
                first = (review, event)
    return first


def _same_folder(left: object, right: object) -> bool:
    """True when both are folder names of the same resolved folder."""
    if not isinstance(left, str) or not isinstance(right, str) or not left or not right:
        return False
    return os.path.normcase(Path(left).resolve().as_posix()) == os.path.normcase(
        Path(right).resolve().as_posix()
    )


def _seen_key(
    top: Path,
    common: Path,
    run: str,
    kind: str,
    result: Result,
    seen: Mapping[str, object],
) -> dict[str, str]:
    """The review key that an unused seen record gives, after its checks (EA-39).

    A worker record must be of the run's clone and B, and its commit must be in the
    main repository with the recorded tree on B. An integration record must be of
    the run and of the plan of its replay batch.

    Raises:
        SnapshotRefusal: ``seen_bad``, the ``_replay`` refusals, ``git_failed``.
    """
    where = f"the seen record of a {seen.get('kind')} review"
    if seen.get("kind") != kind:
        _refuse("seen_bad", f"{where} is not the input of a {kind} review")
    if kind == "integration":
        replay = _replay(top, common, run)
        parent, tree = seen.get("parent"), seen.get("tree")
        if seen.get("run") != run or seen.get("plan") != replay.plan:
            _refuse("seen_bad", f"{where} is not of run {run} and plan {replay.plan}")
        if not (
            isinstance(parent, str)
            and isinstance(tree, str)
            and OID_RE.fullmatch(parent)
            and OID_RE.fullmatch(tree)
        ):
            _refuse("seen_bad", f"{where} names no 40-hex parent and tree")
        return {"parent": parent, "tree": tree}
    ledger = _read_ledger(_ledger_path(common, run))
    if not _same_folder(seen.get("clone"), ledger["clone"]):
        _refuse(
            "seen_bad", f"{where} is of {seen.get('clone')}, not of the run's clone"
        )
    if seen.get("base") != result.base:
        _refuse("seen_bad", f"{where} is on {seen.get('base')}, not on B {result.base}")
    commit, tree = seen.get("commit"), seen.get("tree")
    if not (
        isinstance(commit, str)
        and isinstance(tree, str)
        and OID_RE.fullmatch(commit)
        and OID_RE.fullmatch(tree)
    ):
        _refuse("seen_bad", f"{where} names no 40-hex commit and tree")
    ref = f"{SEEN_PREFIX}{commit}"
    if _ref(top, ref) != commit:
        _refuse("seen_bad", f"{ref} is not in the main repository (run seen again)")
    held_tree = _git(top, "rev-parse", f"{commit}^{{tree}}")
    parents = _git(top, "rev-list", "--parents", "-n", "1", commit).split()[1:]
    if held_tree != tree or parents != [result.base]:
        _refuse("seen_bad", f"{ref} is not the tree {tree} on B {result.base}")
    return {"tree": tree}


def _dispatch_use(common: Path, path: Path) -> str | None:
    """The run of the first review event, in any session, that recorded ``path``.

    Raises:
        SnapshotRefusal: ``ledger_bad`` or ``events_bad``.
    """
    folder = common / LEDGER_FOLDER
    if not folder.is_dir():
        return None
    wanted = os.path.normcase(path.as_posix())
    for entry_path in sorted(folder.glob("*.json")):
        run = _read_ledger(entry_path)["run"]
        if not isinstance(run, str):
            continue
        for event in _read_events(common, run):
            held = event.get("verdict")
            if event.get("event") != EVENT_REVIEW or not isinstance(held, dict):
                continue
            named = cast(dict[str, object], held).get("path")
            if os.path.normcase(str(named)) == wanted:
                return run
    return None


def _check_dispatch(
    common: Path, seen: Mapping[str, object], path: Path, seen_path: Path
) -> None:
    """EA-40 (review R1-F1): the verdict is the one the seen record's dispatch wrote.

    A new seen record keys only the ``final.json`` of the dispatch folder that it
    names, written after the record was taken, in a folder that no other seen record
    used. So an old approval, given with a new seen record, does not move the key to
    a correction that no reviewer read. The record must also hold the one claim of
    that folder (EA-42, review R1-F1 round 5): two claims of one folder, made with
    two spellings of it, refuse both records, as the review cannot tell which one
    its dispatch read.

    Raises:
        SnapshotRefusal: ``seen_bad`` (the record names no dispatch folder or time),
        ``seen_dispatch`` (the verdict is not that ``final.json``), ``dispatch_used``
        (another seen record used the folder), ``seen_stale`` (the verdict is older
        than the record), ``verdict_bad`` (its time cannot be read), ``seen_bad`` (no
        claim names the folder), ``dispatch_claimed`` (two claims name it, or its
        claim is of another record), ``ledger_bad`` (a claim cannot be read).
    """
    folder = seen.get("dispatch_dir")
    if not isinstance(folder, str) or not folder:
        _refuse(
            "seen_bad",
            "the seen record names no dispatch_dir; take it again with --dispatch-dir",
        )
    expected = Path(folder).resolve() / DISPATCH_VERDICT
    if os.path.normcase(expected.as_posix()) != os.path.normcase(path.as_posix()):
        _refuse(
            "seen_dispatch",
            f"the verdict {path} is not {expected.as_posix()}, the verdict of the "
            "dispatch that read this seen record",
        )
    used = _dispatch_use(common, path)
    if used is not None:
        _refuse(
            "dispatch_used",
            f"{expected.parent.as_posix()} keyed a review of run {used} with another "
            "seen record; each review dispatch has its own folder",
        )
    try:
        taken = datetime.fromisoformat(str(seen["taken"])).timestamp()
    except ValueError as exc:
        _refuse("seen_bad", f"the seen record time {seen['taken']!r} is bad: {exc}")
    try:
        written = path.stat().st_mtime
    except OSError as exc:
        _refuse("verdict_bad", f"cannot read the time of the verdict {path}: {exc}")
    if written < taken - MTIME_SLACK_S:
        _refuse(
            "seen_stale",
            f"the verdict {path} was written before its seen record was taken "
            f"({seen['taken']}); it is not the verdict of that dispatch",
        )
    _check_claim(common, expected.parent, seen_path)  # EA-42


def _one_folder(named: str, folder: Path) -> bool:
    """True when the claimed name ``named`` is the folder ``folder`` (EA-42).

    The file system decides when it can (``samefile``); a name that is not there is
    compared by its identity key.
    """
    try:
        return os.path.samefile(named, folder)
    except OSError:
        return _folder_key(Path(named).resolve()) == _folder_key(folder)


def _check_claim(common: Path, folder: Path, seen_path: Path) -> None:
    """EA-42 (review R1-F1, round 5): ``seen_path`` holds the one claim of ``folder``.

    Raises:
        SnapshotRefusal: ``ledger_bad`` (a claim file cannot be read), ``seen_bad``
        (no claim names the folder), ``dispatch_claimed`` (two or more claims name
        it, or its claim is of another seen record).
    """
    claims = common / LEDGER_FOLDER / SEEN_CLAIMS
    named: list[tuple[Path, dict[str, object]]] = []
    files = sorted(claims.glob("*.json")) if claims.is_dir() else []
    for claim_path in files:
        try:
            data: object = json.loads(claim_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            _refuse("ledger_bad", f"cannot read the dispatch claim {claim_path}: {exc}")
        if not isinstance(data, dict):
            _refuse("ledger_bad", f"the dispatch claim {claim_path} is not an object")
        claim = cast(dict[str, object], data)
        held = claim.get("dispatch_dir")
        if isinstance(held, str) and held and _one_folder(held, folder):
            named.append((claim_path, claim))
    if not named:
        _refuse(
            "seen_bad",
            f"no seen record claimed {folder.as_posix()}; take a new seen record with "
            "a new -DispatchId before the dispatch starts",
        )
    if len(named) > 1:
        shown = ", ".join(claim_path.name for claim_path, _claim in named)
        _refuse(
            "dispatch_claimed",
            f"{len(named)} seen records claimed {folder.as_posix()} ({shown}), so the "
            "review cannot tell which one its dispatch read; take a new seen record "
            "with a new -DispatchId",
        )
    if not _same_folder(named[0][1].get("seen"), seen_path.as_posix()):
        _refuse(
            "dispatch_claimed",
            f"{folder.as_posix()} is claimed by another seen record "
            f"({named[0][0].name}), not by {seen_path.name}",
        )


def _review(
    run_arg: str, kind: str, verdict_arg: str, seen_arg: str | None = None
) -> int:
    """I3 ``review``: record a verdict read from disk as a review of the run.

    The key is the input that the review saw, from its seen record (EA-39); a seen
    record keys one verdict, the ``final.json`` of its dispatch folder (EA-40). Without
    a seen record, only a verdict recorded before in the session is taken, with its
    first key (EA-37).
    """
    run = _check_run(run_arg)
    if kind not in REVIEW_KINDS:
        _refuse("kind", f"the review kind {kind!r} is not one of {REVIEW_KINDS}")
    main = Path.cwd()
    top, common = _top_dir(main), _common_dir(main)
    result = _result(common, run)
    if kind == "worker":
        plans = _review_plans(top, common, run, result)
    else:
        plans = frozenset({_replay(top, common, run).plan})
    path, digest, verdict = _read_verdict(verdict_arg, plans)
    seen_field: dict[str, str] | None = None
    key: dict[str, str]
    reviewed_at: str | None
    if seen_arg is not None:
        seen_path, seen_digest, seen = _read_seen(seen_arg)
        seen_field = {"path": seen_path.as_posix(), "sha256": seen_digest}
        used = _seen_use(common, result.session, seen_path, seen_digest)
        if used is None:
            key = _seen_key(top, common, run, kind, result, seen)
            _check_dispatch(common, seen, path, seen_path)  # EA-40, EA-42
            reviewed_at = str(seen["taken"])
        elif used[0].kind == kind and _same_file(used[1].get("verdict"), path, digest):
            key, reviewed_at = dict(used[0].key), used[0].reviewed_at
        else:
            _refuse(
                "seen_used",
                f"the seen record {seen_path.name} keys another verdict, recorded for "
                f"run {used[0].run}; each review dispatch writes its own seen record",
            )
    else:
        bound = _bound_review(common, result.session, kind, path, digest)
        if bound is None:
            _refuse(
                "seen_missing",
                f"--seen <file> names the input that the {kind} review read; run "
                "result_snapshot.py seen (worker) or brief (integration) before the "
                "review dispatch",
            )
        key, reviewed_at = dict(bound.key), bound.reviewed_at
        print(
            f"review_kept {run} {kind}: the verdict {path.name} was recorded for run "
            f"{bound.run}; its key stays until a new verdict is recorded",
            file=sys.stderr,
            flush=True,
        )
    _append_event(
        common,
        run,
        {
            "event": EVENT_REVIEW,
            "kind": kind,
            "run": run,
            "session": result.session,
            "key": key,
            "author_vendor": result.author_vendor,
            "seen": seen_field,
            "reviewed_at": reviewed_at,
            "verdict": {
                "path": path.as_posix(),
                "sha256": digest,
                "verdict": verdict.get("verdict"),
                "agent": verdict.get("agent"),
                "target_plan": verdict.get("target_plan"),
            },
            "recorded": _now(),
        },
    )
    shown = " ".join(f"{name}={value}" for name, value in key.items())
    print(f"review_ok {run} {kind} {shown}")
    return EXIT_OK


def _scope(run_arg: str, gate_arg: str | None) -> int:
    """I1 ``scope``: print the items and the void reviews, or ``integration_review:none``."""
    scope = _scope_of(run_arg)
    voids = _voids(scope, Path(gate_arg) if gate_arg else None)
    _log_voids(scope, voids)
    lines = scope.item_lines() + [void.line() for void in voids]
    for line in lines or [NO_SCOPE]:
        print(line)
    return EXIT_OK


def _brief(run_arg: str, out_arg: str, dispatch_arg: str | None = None) -> int:
    """I2 and I4 ``brief``: write the review prompt; one dispatch line per vendor.

    The seen record names the dispatch folder of the integration review (EA-40) and
    claims it before that dispatch starts (EA-41).
    """
    scope = _scope_of(run_arg)
    c_commit = _c_commit(scope)
    range_diff = _git(
        scope.top,
        "range-diff",
        "--no-color",
        f"{scope.result.base}..{scope.result.commit}",
        f"{scope.replay.parent}..{c_commit}",
    )
    out = Path(out_arg).resolve()
    seen_path = Path(f"{out}{SEEN_SUFFIX}")
    if seen_path.exists():
        _refuse(
            "exists",
            f"the seen record {seen_path} is already there; write each brief to a new "
            "file",
        )
    dispatch = _dispatch_dir(dispatch_arg)
    claim = _claim_dispatch(scope.common, dispatch, seen_path)  # EA-41
    try:
        _write_brief(out, seen_path, scope, c_commit, range_diff, dispatch)
    except SnapshotRefusal:
        _release_claim(claim)
        raise
    print(f"brief_ok {scope.result.run} out={out.as_posix()}")
    print(f"brief_seen {scope.result.run} seen={seen_path.as_posix()}")
    grouped: dict[str, list[str]] = {}
    for delta, vendor in _deltas(scope):
        grouped.setdefault(vendor or NO_VENDOR, []).append(delta)
    for vendor, deltas in grouped.items():
        if vendor == NO_VENDOR:
            print(
                f"brief_warn author_vendor_unknown {','.join(deltas)}: fetch the run "
                "with --status or --author-vendor",
                file=sys.stderr,
            )
        print(f"dispatch {','.join(deltas)} -AuthorVendor {vendor}")
    return EXIT_OK


def _write_brief(
    out: Path,
    seen_path: Path,
    scope: Scope,
    c_commit: str,
    range_diff: str,
    dispatch: Path,
) -> None:
    """Write the integration prompt ``out`` and its seen record ``seen_path``.

    Raises:
        SnapshotRefusal: ``out_bad`` (the prompt cannot be written), ``exists`` or
        ``out_bad`` from the seen record.
    """
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(_prompt(scope, c_commit, range_diff))
    except OSError as exc:
        _refuse("out_bad", f"cannot write the prompt {out}: {exc}")
    record = {
        "schema_version": SEEN_SCHEMA,
        "kind": "integration",
        "run": scope.result.run,
        "parent": scope.replay.parent,
        "tree": scope.replay.tree,
        "plan": scope.replay.plan,
        "dispatch_dir": dispatch.as_posix(),
        "taken": _now(),
    }
    _write_new(seen_path, json.dumps(record, indent=2) + "\n", "seen record")


# ---------------------------------------------------------------------------
# the process seam of tools/orch.py (MEU-951, EA-7)
# ---------------------------------------------------------------------------


def run_tool(argv: Sequence[str], *, cwd: Path, wait: bool) -> tuple[int, str]:
    """Run one command without a shell, for ``orch.py`` (the one process seam).

    ``wait=True`` runs ``argv`` in ``cwd`` and returns ``(exit code, stdout)``; the
    stderr of the command goes to this process's stderr. ``wait=False`` starts a
    process in its own process group with a hidden console (no window, no inherited
    handles) that outlives this one, and returns ``(0, "")`` at once. It does not use
    the Windows ``DETACHED_PROCESS`` flag: PowerShell 7, which runs each worker
    launch, exits at once with no output when it has no console.

    Raises:
        SnapshotRefusal: ``tool_empty`` for an empty ``argv``, ``tool_cwd`` when
            ``cwd`` is not a folder, ``tool_failed`` when the process cannot start.
    """
    command = [str(arg) for arg in argv]
    if not command:
        _refuse("tool_empty", "no command to run")
    folder = Path(cwd)
    if not folder.is_dir():
        _refuse("tool_cwd", f"{folder} is not a folder (command: {command[0]})")
    if not wait:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        try:
            subprocess.Popen(
                command,
                cwd=folder,
                env=_git_env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=flags,
                start_new_session=sys.platform != "win32",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            _refuse("tool_failed", f"cannot start {command[0]} in {folder}: {exc}")
        return 0, ""
    try:
        done = subprocess.run(
            command,
            cwd=folder,
            env=_git_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _refuse("tool_failed", f"cannot run {command[0]} in {folder}: {exc}")
    if done.stderr:
        print(done.stderr, end="", file=sys.stderr, flush=True)
    return done.returncode, done.stdout


def ledger_entries(common: Path) -> list[dict[str, str | None]]:
    """Every ledger entry of ``<common>/{{PROJECT_NAME}}-results/*.json``, sorted by file name.

    Raises:
        SnapshotRefusal: ``ledger_bad`` (an entry cannot be read).
    """
    folder = common / LEDGER_FOLDER
    if not folder.is_dir():
        return []
    return [_read_ledger(path) for path in sorted(folder.glob("*.json"))]


def recorded_reviews(common: Path, session: str) -> dict[str, dict[str, str]]:
    """The key of the latest recorded (approved) review of each kind of ``session``.

    Raises:
        SnapshotRefusal: ``ledger_bad`` or ``events_bad``.
    """
    return {
        kind: dict(review.key)
        for kind, review in _session_reviews(common, session).items()
    }


def run_voids(common: Path, run: str) -> list[str]:
    """``<kind>:<reason>`` of each void event of ``run``, sorted and without repeats.

    Raises:
        SnapshotRefusal: ``events_bad``.
    """
    found = {
        f"{event.get('kind')}:{event.get('reason')}"
        for event in _read_events(common, run)
        if event.get("event") == EVENT_VOID
    }
    return sorted(found)


def _parser() -> argparse.ArgumentParser:
    """The command-line parser of the seven commands."""
    parser = argparse.ArgumentParser(
        prog="result_snapshot.py",
        description="Snapshot a scratch clone's working tree as a result commit.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    take = sub.add_parser("take", help="snapshot the clone as refs/fleet/result/<run>")
    take.add_argument("--clone", required=True)
    take.add_argument("--run", required=True)
    fetch = sub.add_parser("fetch", help="fetch the result into the main repository")
    fetch.add_argument("--clone", required=True)
    fetch.add_argument("--run", required=True)
    fetch.add_argument("--session", default=None, help="default: the clone slug")
    fetch.add_argument(
        "--author-vendor",
        default=None,
        choices=AUTHOR_VENDORS,
        help="the vendor of the worker that wrote the delta",
    )
    fetch.add_argument(
        "--status",
        default=None,
        help="the worker dispatch's status.json; its cli sets the author vendor",
    )
    drop = sub.add_parser("drop", help="delete the result ref in both repositories")
    drop.add_argument("--run", required=True)
    review = sub.add_parser("review", help="record an approved review of the run")
    review.add_argument("--run", required=True)
    review.add_argument("--kind", required=True, choices=REVIEW_KINDS)
    review.add_argument("--verdict", required=True, help="a review-verdict.v1 file")
    review.add_argument(
        "--seen",
        default=None,
        help="the review-seen.v1 record of the input that the review read",
    )
    seen = sub.add_parser(
        "seen", help="record the clone's working tree before a worker review"
    )
    seen.add_argument("--clone", required=True)
    seen.add_argument("--out", required=True, help="the seen record to write")
    seen.add_argument(
        "--dispatch-dir",
        default=None,
        help="the review dispatch folder (<OutputDir>/<DispatchId>); EA-40",
    )
    scope = sub.add_parser("scope", help="list what of the replay no reviewer read")
    scope.add_argument("--run", required=True)
    scope.add_argument(
        "--gate-run", default=None, help="the gate run folder that holds gate.json"
    )
    brief = sub.add_parser("brief", help="write the integration review prompt")
    brief.add_argument("--run", required=True)
    brief.add_argument("--out", required=True, help="the prompt file to write")
    brief.add_argument(
        "--dispatch-dir",
        default=None,
        help="the integration review dispatch folder (<OutputDir>/<DispatchId>); EA-40",
    )
    return parser


def _bind_values(argv: Sequence[str]) -> list[str]:
    """``argv`` with each value option joined to its value (``--run=<value>``).

    argparse reads a value that starts with ``-`` (``--run -lead``) as an option and
    exits 2; joined, the value reaches ``_check_run``, which refuses it as ``run``.
    """
    out: list[str] = []
    tokens = list(argv)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in VALUE_OPTIONS and index + 1 < len(tokens):
            out.append(f"{token}={tokens[index + 1]}")
            index += 2
            continue
        out.append(token)
        index += 1
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command; 0 on success, 1 on a refusal (``snapshot_bad:<reason>``)."""
    raw = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(_bind_values(raw))
    try:
        if args.command == "take":
            return _take(args.clone, args.run)
        if args.command == "fetch":
            return _fetch(
                args.clone, args.run, args.session, args.author_vendor, args.status
            )
        if args.command == "review":
            return _review(args.run, args.kind, args.verdict, args.seen)
        if args.command == "seen":
            return _seen(args.clone, args.out, args.dispatch_dir)
        if args.command == "scope":
            return _scope(args.run, args.gate_run)
        if args.command == "brief":
            return _brief(args.run, args.out, args.dispatch_dir)
        return _drop(args.run)
    except SnapshotRefusal as refusal:
        print(f"{REFUSAL_PREFIX}{refusal.reason}", flush=True)
        print(refusal.detail, file=sys.stderr, flush=True)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
