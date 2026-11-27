"""The land journal: one line per land step, crash recovery, and the final-validation slot.

MEU-953 (plan ``2026-11-11-ag4-pilot-c-reconcile-crash-states``, design §9.7). A land that
publishes a candidate to ``main`` writes one JSON line per step to
``<git common dir>/{{PROJECT_NAME}}-land-journal/<run>.jsonl``, so a crash at any point leaves a
journal from which ``recover`` does the one missing action, once:

=========  =====================================================  ======================
state      journal and ref                                        action
=========  =====================================================  ======================
1          no publication and no consumption                      land again
2          consumed, the ref still at P, no (P, C) reflog entry    move the ref once
3          published (the ref at C with a (P, C) reflog entry)     record the facts
4          the reflog cannot answer, or the ref is neither P nor C STOP, wait for a human
5          ``ref_moved`` without ``sync_done``                     sync the index
6          ``sync_done`` without a terminal step                   records, audit, close
=========  =====================================================  ======================

``FINAL_SLOT``: one run at a time holds ``final-validation.json`` of the common dir from its
claim (before the final gate) to its terminal step. ``STOP`` (``CRASH_AMBIGUOUS``) blocks
every land route until a typed human ruling ``Clear the land stop of <run>.`` clears it.

Every step write goes through the module name ``append`` and every process through
``_invoke``; a test bootstrap wraps them (there is no production crash switch).

Exit codes of ``main``: 0 done, 1 refused, 2 bad input or a bad journal, 3 STOP.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

if not __package__:
    # Script mode (``python tools/land_journal.py``): the repository root holds ``tools``.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import commit_batch as cb  # noqa: E402
from tools import os_lease  # noqa: E402
from tools import run_parameters as rp  # noqa: E402

SCHEMA = "land-journal/1"
FOLDER = "{{PROJECT_NAME}}-land-journal"
STOP_NAME = "STOP"
SLOT_NAME = "final-validation.json"
SLOT_LOCK_NAME = "final-validation.lock"
CLEARED_NAME = "cleared.jsonl"
LEDGER_FOLDER = "{{PROJECT_NAME}}-results"
LEDGER_NAME = "landed.jsonl"
ACTIONS_FOLDER = "{{PROJECT_NAME}}-orch"
ACTIONS_NAME = "actions.jsonl"
RESULT_REF_PREFIX = "refs/fleet/result/"

STEPS = (
    "validation_claimed",
    "intent",
    "authority_checked",
    "authority_consumed",
    "ref_moved",
    "sync_done",
    "records_done",
    "audit_done",
)
TERMINAL = ("closed", "parked", "abandoned")
ALL_STEPS = (*STEPS, *TERMINAL)
PRE_PUBLISH = frozenset({"validation_claimed", "intent", "authority_checked"})
CARRIERS = ("grant", "human_directed")
LINE_KEYS = ("run", "session", "op", "step", "at", "facts")
INTENT_KEYS = (
    "ref",
    "parent",
    "tree",
    "candidate",
    "op",
    "carrier",
    "plan",
    "paths",
    "direction",
)
HUMAN_CHECKS = ("ancestor", "tree", "consumption", "paths")
RUN_RE = re.compile(r"[A-Za-z0-9._-]{1,80}")
# The reflog message of a commit_batch op: ``<op>``, a retry ``-r<n>``, a sub-op ``/<n>``.
OP_SUFFIX = r"(-r[0-9]+)?(/[0-9]+)?"
SHA_RE = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
REASON_MAX = 200
CLEAR_TEXT = "Clear the land stop of {run}."
LEASE_WAIT_S = 30.0
DRIVE_LOCK_SUFFIX = ".drive.lock"
LEGACY_REASON = "legacy"
EXPIRED_REASON = "expired"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_BAD = 2
EXIT_STOP = 3
EXIT_BUSY = 4

TOOLS = Path(__file__).resolve().parent


class JournalRefusal(Exception):
    """A journal rule refused; ``reason`` is the stdout code, ``code`` the exit code."""

    def __init__(self, reason: str, detail: str = "", code: int = EXIT_REFUSED) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.code = code


def warn(
    event: str,
    *,
    limit_name: str,
    configured_value: object,
    observed_value: object,
    window: str,
) -> None:
    """Print one WARN record (``event`` and the four limit fields) to stderr."""
    record = {
        "level": "WARN",
        "event": event,
        "limit_name": limit_name,
        "configured_value": configured_value,
        "observed_value": observed_value,
        "window": window,
    }
    print(json.dumps(record, sort_keys=True), file=sys.stderr)


def _slot_warn(observed: object) -> None:
    """The WARN record of a refused final-validation slot."""
    warn(
        "final_validation_refused",
        limit_name="final_validation_slot",
        configured_value=1,
        observed_value=observed,
        window="per common dir",
    )


# ---------------------------------------------------------------------------
# paths, time, git, processes
# ---------------------------------------------------------------------------


def _repo(repo: Path | str) -> rp.Repo:
    """The repository that holds ``repo``.

    Raises:
        JournalRefusal: ``not_a_repository`` (exit 2).
    """
    try:
        return rp._open_repo(Path(repo))
    except rp.Refusal as exc:
        raise JournalRefusal("not_a_repository", exc.detail, EXIT_BAD) from exc


def _folder(r: rp.Repo) -> Path:
    return r.common / FOLDER


def _journal_path(r: rp.Repo, run: str) -> Path:
    return _folder(r) / f"{run}.jsonl"


def _now() -> str:
    """The UTC time, ISO 8601 with microseconds and ``Z``."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _check_run(run: object) -> str:
    """``run`` when it is a run name.

    Raises:
        JournalRefusal: ``land_journal_bad:run`` (exit 2).
    """
    if not isinstance(run, str) or RUN_RE.fullmatch(run) is None or run in (".", ".."):
        warn(
            "land_journal_refused",
            limit_name="run_id_length",
            configured_value=80,
            observed_value=len(run) if isinstance(run, str) else repr(run),
            window="per call",
        )
        raise JournalRefusal("land_journal_bad:run", repr(run), EXIT_BAD)
    return run


def _git(r: rp.Repo, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Run git in the main tree without inherited ``GIT_*`` values; no check."""
    return subprocess.run(  # noqa: S603 - fixed argv
        ["git", *args],
        cwd=r.main,
        env=rp._git_env(None),
        capture_output=True,
        check=False,
    )


def _ref(r: rp.Repo, ref: str) -> str:
    """The commit of ``ref``, or ``""`` when it does not exist."""
    proc = _git(r, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
    return proc.stdout.decode("utf-8").strip() if proc.returncode == 0 else ""


def _branch(ref: str) -> str:
    """The branch name of ``refs/heads/<b>``.

    Raises:
        JournalRefusal: ``land_journal_bad:ref`` (exit 2).
    """
    prefix = "refs/heads/"
    if not ref.startswith(prefix) or len(ref) == len(prefix):
        raise JournalRefusal("land_journal_bad:ref", ref, EXIT_BAD)
    return ref[len(prefix) :]


def _invoke(argv: Sequence[str], cwd: Path | str) -> tuple[int, str]:
    """Run one tool without a shell; ``(exit code, stdout)`` (the one process seam)."""
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [str(arg) for arg in argv],
        cwd=Path(cwd),
        capture_output=True,
        check=False,
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr.decode("utf-8", errors="replace"))
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace")


def _json_reason(out: str) -> str:
    """The ``reason`` of the last JSON object line of ``out``; ``""`` when none."""
    for line in reversed(out.strip().splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return str(cast(dict[str, Any], value).get("reason") or "")
    return ""


def _lines_with(path: Path, key: str, value: str) -> int:
    """The count of JSON lines of ``path`` whose ``key`` is ``value``."""
    text = rp._read_text(path)
    if text is None:
        return 0
    count = 0
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and cast(dict[str, Any], item).get(key) == value:
            count += 1
    return count


def _append_json(path: Path, body: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rp._append_line(path, json.dumps(dict(body), sort_keys=True))


# ---------------------------------------------------------------------------
# the journal
# ---------------------------------------------------------------------------


def append(
    repo: Path | str,
    run: str,
    session: str,
    op: str,
    step: str,
    facts: Mapping[str, Any],
) -> None:
    """Append one step line with the keys ``LINE_KEYS``, then flush and fsync it.

    Raises:
        JournalRefusal: ``land_journal_bad:run`` or ``land_journal_bad:step`` (exit 2).
    """
    _check_run(run)
    if step not in ALL_STEPS:
        raise JournalRefusal("land_journal_bad:step", step, EXIT_BAD)
    r = _repo(repo)
    path = _journal_path(r, run)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "run": run,
        "session": session,
        "op": op,
        "step": step,
        "at": _now(),
        "facts": dict(facts),
    }
    with path.open("ab") as handle:
        handle.write((json.dumps(line) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def _order_ok(prev: str | None, step: str) -> bool:
    """True when ``step`` may follow ``prev`` (None: the first line)."""
    if prev is None:
        return step == "validation_claimed"
    if prev in TERMINAL:
        return False
    if step in ("validation_claimed", "intent", "abandoned"):
        return prev in PRE_PUBLISH
    if step == "authority_checked":
        return prev == "intent"
    if step == "parked":
        return prev == "records_done"
    if step == "closed":
        return prev == "audit_done"
    return prev == STEPS[STEPS.index(step) - 1]


def _line_ok(item: object, run: str, prev: str | None) -> bool:
    if not isinstance(item, dict):
        return False
    line = cast(dict[str, Any], item)
    if set(line) != set(LINE_KEYS) or line["run"] != run:
        return False
    step, facts = line["step"], line["facts"]
    if step not in ALL_STEPS or not isinstance(facts, dict):
        return False
    if not all(isinstance(line[key], str) for key in ("session", "op", "at")):
        return False
    if step == "intent" and cast(dict[str, Any], facts).get("carrier") not in CARRIERS:
        return False
    return _order_ok(prev, step)


def read(repo: Path | str, run: str) -> list[dict[str, Any]]:
    """The checked lines of the journal of ``run`` (empty when there is none).

    Raises:
        JournalRefusal: ``journal_bad:<n>`` (exit 2) for the first line ``n`` (1-based)
            with an unknown key, an unknown step, an unknown carrier, facts that are not
            an object, or a step out of order.
    """
    _check_run(run)
    text = rp._read_text(_journal_path(_repo(repo), run))
    if text is None:
        return []
    lines: list[dict[str, Any]] = []
    prev: str | None = None
    for n, raw in enumerate(text.split("\n"), start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            item = None
        if not _line_ok(item, run, prev):
            warn(
                "land_journal_refused",
                limit_name="journal_schema",
                configured_value=SCHEMA,
                observed_value=f"line {n}",
                window="per call",
            )
            raise JournalRefusal(f"journal_bad:{n}", raw[:200], EXIT_BAD)
        line = cast(dict[str, Any], item)
        lines.append(line)
        prev = str(line["step"])
    return lines


def _last(lines: Sequence[Mapping[str, Any]], step: str) -> dict[str, Any] | None:
    """The facts of the last line of ``step``; None when there is none."""
    for line in reversed(lines):
        if line["step"] == step:
            return cast(dict[str, Any], line["facts"])
    return None


def _intent_of(lines: Sequence[Mapping[str, Any]], run: str) -> dict[str, Any]:
    """The last intent of the journal.

    Raises:
        JournalRefusal: ``journal_bad:intent`` (exit 2) when it has none.
    """
    intent = _last(lines, "intent")
    if intent is None:
        raise JournalRefusal("journal_bad:intent", run, EXIT_BAD)
    return intent


def _check_intent(intent: Mapping[str, Any]) -> dict[str, Any]:
    """``intent`` when it has the keys ``INTENT_KEYS`` and a known carrier.

    Raises:
        JournalRefusal: ``land_journal_bad:intent`` (exit 2).
    """
    body = dict(intent)
    if set(body) != set(INTENT_KEYS):
        raise JournalRefusal("land_journal_bad:intent", "keys", EXIT_BAD)
    if body["carrier"] not in CARRIERS:
        raise JournalRefusal("land_journal_bad:intent", "carrier", EXIT_BAD)
    for key in ("parent", "tree"):
        if not isinstance(body[key], str) or SHA_RE.fullmatch(body[key]) is None:
            raise JournalRefusal("land_journal_bad:intent", key, EXIT_BAD)
    if not isinstance(body["paths"], list) or not all(
        isinstance(p, str) for p in cast(list[Any], body["paths"])
    ):
        raise JournalRefusal("land_journal_bad:intent", "paths", EXIT_BAD)
    direction = body["direction"]
    if body["carrier"] == "human_directed" and not (
        isinstance(direction, dict)
        and isinstance(cast(dict[str, Any], direction).get("uid"), str)
    ):
        raise JournalRefusal("land_journal_bad:intent", "direction", EXIT_BAD)
    _branch(str(body["ref"]))
    return body


# ---------------------------------------------------------------------------
# STOP
# ---------------------------------------------------------------------------


def write_stop(repo: Path | str, run: str, reason: str, state: int) -> None:
    """Write ``STOP`` (``run``, ``reason``, ``state``, ``at``); it blocks every land route."""
    r = _repo(repo)
    folder = _folder(r)
    folder.mkdir(parents=True, exist_ok=True)
    body = {"run": run, "reason": reason, "state": state, "at": _now()}
    rp._write_atomic(folder / STOP_NAME, (json.dumps(body) + "\n").encode("utf-8"))


def read_stop(repo: Path | str) -> dict[str, Any] | None:
    """The STOP body; None when there is no STOP. A STOP that does not parse has run ``unknown``."""
    data = rp._read_bytes(_folder(_repo(repo)) / STOP_NAME)
    if data is None:
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        value = None
    if not isinstance(value, dict) or not isinstance(
        cast(dict[str, Any], value).get("run"), str
    ):
        return {"run": "unknown", "reason": "unreadable", "state": None, "at": None}
    return cast(dict[str, Any], value)


def _refuse_stop(repo: Path | str) -> None:
    """Refuse while STOP exists.

    Raises:
        JournalRefusal: ``land_blocked:journal_stop:<run>`` (exit 3).
    """
    stop = read_stop(repo)
    if stop is not None:
        warn(
            "land_blocked",
            limit_name="journal_stop",
            configured_value=0,
            observed_value=str(stop["run"]),
            window="per common dir",
        )
        raise JournalRefusal(
            f"land_blocked:journal_stop:{stop['run']}",
            str(stop.get("reason")),
            EXIT_STOP,
        )


def _stop(repo: Path | str, run: str, why: str) -> JournalRefusal:
    """Write STOP for state 4; the refusal to raise (``crash_state:4:<why>``, exit 3)."""
    write_stop(repo, run, why, 4)
    return JournalRefusal(f"crash_state:4:{why}", run, EXIT_STOP)


# ---------------------------------------------------------------------------
# FINAL_SLOT
# ---------------------------------------------------------------------------


def _slot_path(r: rp.Repo) -> Path:
    return _folder(r) / SLOT_NAME


def _slot_body(r: rp.Repo) -> dict[str, Any] | None:
    data = rp._read_bytes(_slot_path(r))
    if data is None:
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        value = None
    if not isinstance(value, dict) or not isinstance(
        cast(dict[str, Any], value).get("run"), str
    ):
        # An unreadable slot is held: only an abandon of ``unknown`` frees it.
        return {
            "run": "unknown",
            "session": None,
            "candidate": None,
            "claimed_at": None,
        }
    return cast(dict[str, Any], value)


class _SlotLock:
    """The ``os_lease`` mutex around a read and write of the slot."""

    def __init__(self, r: rp.Repo, run: str) -> None:
        self._path = _folder(r) / SLOT_LOCK_NAME
        self._body = f"land_journal {run} {os.getpid()}\n".encode()
        self._lease: os_lease.Lease | None = None

    def __enter__(self) -> _SlotLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lease = os_lease.acquire(
                self._path, wait_s=LEASE_WAIT_S, body=self._body, record=False
            )
        except os_lease.Busy as exc:
            raise JournalRefusal("slot_lock_busy", str(exc), EXIT_BUSY) from exc
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._lease is not None:
            os_lease.release(self._lease)


class _DriveLock:
    """The ``os_lease`` of the process that drives the land of ``run``, for any carrier.

    ``commit_land`` holds it from the slot check to the end of ``finish``; ``recover`` and
    ``abandon`` of an open journal take it without a wait. The operating system frees it
    when its process dies, so a busy lease is a live land.
    """

    def __init__(self, r: rp.Repo, run: str) -> None:
        self._run = run
        self._path = _folder(r) / f"{run}{DRIVE_LOCK_SUFFIX}"
        self._lease: os_lease.Lease | None = None

    def __enter__(self) -> _DriveLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        body = f"land_journal {self._run} {os.getpid()}\n".encode()
        try:
            self._lease = os_lease.acquire(
                self._path, wait_s=0, body=body, record=False
            )
        except os_lease.Busy as exc:
            raise JournalRefusal(f"land_live:{self._run}", str(exc), EXIT_BUSY) from exc
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._lease is not None:
            os_lease.release(self._lease)


def read_slot(repo: Path | str) -> dict[str, Any] | None:
    """The slot body (``run``, ``session``, ``candidate``, ``claimed_at``); None when free."""
    return _slot_body(_repo(repo))


def claim(
    repo: Path | str, run: str, *, session: str, candidate: str
) -> dict[str, Any]:
    """Take the one final-validation slot for ``run`` and write ``validation_claimed``.

    A second claim of the same run returns the slot and writes nothing, except that it
    writes a ``validation_claimed`` line that a death after the slot write lost. A run
    whose journal has a terminal step does not claim again: a new land takes a new key.

    Raises:
        JournalRefusal: ``final_validation_busy:<run>`` (exit 4) when another run holds it;
            ``final_validation_ended:<run>`` (exit 1) for a journal with a terminal step;
            ``journal_bad:<n>`` (exit 2).
    """
    _check_run(run)
    r = _repo(repo)
    with _SlotLock(r, run):
        slot = _slot_body(r)
        if slot is not None and slot.get("run") != run:
            _slot_warn(str(slot.get("run")))
            raise JournalRefusal(
                f"final_validation_busy:{slot.get('run')}", "", EXIT_BUSY
            )
        lines = read(r.main, run)
        if lines and lines[-1]["step"] in TERMINAL:
            _slot_warn(f"{run} {lines[-1]['step']}")
            raise JournalRefusal(
                f"final_validation_ended:{run}", str(lines[-1]["step"]), EXIT_REFUSED
            )
        if slot is not None and lines:
            return slot
        body = slot or {
            "schema": SCHEMA,
            "run": run,
            "session": session,
            "candidate": candidate,
            "claimed_at": _now(),
        }
        if slot is None:
            rp._write_atomic(_slot_path(r), (json.dumps(body) + "\n").encode("utf-8"))
        append(
            r.main,
            run,
            session,
            run,
            "validation_claimed",
            {"candidate": body["candidate"], "claimed_at": body["claimed_at"]},
        )
    return body


def release_slot(repo: Path | str, run: str) -> bool:
    """Free the slot when ``run`` holds it; True when it was freed."""
    r = _repo(repo)
    with _SlotLock(r, run):
        slot = _slot_body(r)
        if slot is None or slot.get("run") != run:
            return False
        rp._unlink(_slot_path(r))
    return True


def _own_slot(r: rp.Repo, run: str) -> dict[str, Any]:
    """The slot of ``run``.

    Raises:
        JournalRefusal: ``final_validation_not_owned`` (exit 1).
    """
    slot = _slot_body(r)
    if slot is None or slot.get("run") != run:
        held = "free" if slot is None else str(slot.get("run"))
        _slot_warn(held)
        raise JournalRefusal(
            "final_validation_not_owned", f"slot: {held}", EXIT_REFUSED
        )
    return slot


def abandon(repo: Path | str, run: str, *, session: str, reason: str) -> str:
    """Write ``abandoned`` for a run that has not consumed its authority; free its slot.

    With no ``authority_consumed`` line the branch reflog must prove that the land did not
    publish (state 1), because a stop can come between the publication and that line.

    Raises:
        JournalRefusal: ``abandon_after_consumption`` (exit 1) after ``authority_consumed``
            or a proven publication; ``crash_state:4:<why>`` (exit 3, STOP) when the reflog
            cannot answer; ``land_live:<run>`` (exit 4) while a live process drives the land.
    """
    _check_run(run)
    r = _repo(repo)
    lines = read(r.main, run)
    if not lines:
        release_slot(r.main, run)
        return "abandoned"
    if lines[-1]["step"] in TERMINAL:
        release_slot(r.main, run)
        return str(lines[-1]["step"])
    with _DriveLock(r, run):
        lines = read(r.main, run)
        steps = [str(line["step"]) for line in lines]
        if steps[-1] not in TERMINAL:
            if "authority_consumed" in steps:
                raise JournalRefusal("abandon_after_consumption", run, EXIT_REFUSED)
            state, why, _commit = _state(r, run, lines)
            if state == 4:
                raise _stop(r.main, run, why)
            if state != 1:
                raise JournalRefusal("abandon_after_consumption", run, EXIT_REFUSED)
            op = str(lines[-1]["op"])
            append(r.main, run, session, op, "abandoned", {"reason": reason})
            steps.append("abandoned")
    release_slot(r.main, run)
    return steps[-1]


# ---------------------------------------------------------------------------
# the land
# ---------------------------------------------------------------------------


def _reflog_entries(r: rp.Repo, branch: str) -> list[tuple[str, str, str]] | None:
    """``(old, new, message)`` of the branch reflog; None when there is no reflog file."""
    text = rp._read_text(r.common / "logs" / "refs" / "heads" / branch)
    if text is None:
        return None
    entries: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        head, _tab, message = line.partition("\t")
        parts = head.split()
        if len(parts) >= 2:
            entries.append((parts[0], parts[1], message.strip()))
    return entries


def _shim(
    r: rp.Repo, run: str, intent: Mapping[str, Any], commit: str
) -> SimpleNamespace:
    """The fields of a commit_batch op that ``_reflog`` and ``_reconcile_index`` read."""
    return SimpleNamespace(
        repo=r,
        packet=SimpleNamespace(
            branch=_branch(str(intent["ref"])),
            paths=list(cast(list[str], intent["paths"])),
        ),
        op=str(intent["op"]),
        run=run,
        folder=_folder(r) / f"{run}.sync",
        parent=str(intent["parent"]),
        commit=commit,
    )


def _sync(
    r: rp.Repo, run: str, intent: Mapping[str, Any], commit: str
) -> dict[str, str]:
    """Move the land's own index entries from P to C (commit_batch step 7)."""
    return cb._reconcile_index(cast(Any, _shim(r, run, intent, commit)))


def batch_intent(
    repo: Path | str,
    batch: Path | str,
    *,
    op: str,
    carrier: str,
    plan: str,
    candidate: str,
    direction: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The intent of a land of the packet or batch file ``batch``: P, T and the paths.

    T is the tree that the packets end with on P (``commit_batch.batch_tree``, the tree
    that the gate candidate and the gated land build), so it is known before publication.

    Raises:
        JournalRefusal: ``intent:<reason>`` (exit 1) when the file does not parse or git
            cannot build the tree; ``land_journal_bad:intent`` (exit 2).
    """
    r = _repo(repo)
    try:
        packets, _is_batch = cb._read_input(Path(batch), True)
        parent = packets[0].parent
        tree = cb.batch_tree(r.main, parent, packets)
    except rp.Refusal as exc:
        raise JournalRefusal(f"intent:{exc.reason}", exc.detail, EXIT_REFUSED) from exc
    except (rp.GitError, OSError) as exc:
        raise JournalRefusal("intent:git", str(exc), EXIT_REFUSED) from exc
    return _check_intent(
        {
            "ref": f"refs/heads/{packets[0].branch}",
            "parent": parent,
            "tree": tree,
            "candidate": candidate,
            "op": op,
            "carrier": carrier,
            "plan": plan,
            "paths": sorted({rel for packet in packets for rel in packet.paths}),
            "direction": dict(direction) if direction is not None else None,
        }
    )


def commit_land(
    repo: Path | str,
    run: str,
    *,
    session: str,
    intent: Mapping[str, Any],
    publish: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Journal one land: intent, the authority, ``publish()``, the ref, the sync, ``finish``.

    ``publish`` is the commit_batch route; it returns ``commit`` and, when it synced the
    index, ``index``. Returns ``{"state": "closed"|"parked", "commit": C}``.

    The journal is read before the intent: one that does not read, or that is not open
    for a land, refuses before anything is published.

    Raises:
        JournalRefusal: ``land_blocked:journal_stop:<run>`` (exit 3);
            ``final_validation_not_owned`` (exit 1); ``journal_bad:<n>`` (exit 2);
            ``land_not_open:<run>:<last step>`` (exit 1); ``crash_state:4:<why>``
            (exit 3); ``land_live:<run>`` (exit 4); a bad intent (exit 2).
    """
    _check_run(run)
    body = _check_intent(intent)
    r = _repo(repo)
    _refuse_stop(r.main)
    _own_slot(r, run)
    with _DriveLock(r, run):
        return _drive(r, run, session=session, body=body, publish=publish)


def _drive(
    r: rp.Repo,
    run: str,
    *,
    session: str,
    body: Mapping[str, Any],
    publish: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """``commit_land`` under the drive lock, from the journal read to ``finish``."""
    lines = read(r.main, run)
    last = str(lines[-1]["step"]) if lines else "none"
    if last not in PRE_PUBLISH:
        raise JournalRefusal(f"land_not_open:{run}:{last}", "", EXIT_REFUSED)
    op = str(body["op"])
    append(r.main, run, session, op, "intent", body)
    append(r.main, run, session, op, "authority_checked", {})
    result = dict(publish())
    commit = str(result.get("commit") or "")
    if SHA_RE.fullmatch(commit) is None:
        raise JournalRefusal("publish_result", repr(result.get("commit")), EXIT_REFUSED)
    append(
        r.main,
        run,
        session,
        op,
        "authority_consumed",
        {"commit": commit, "op": str(result.get("op") or op)},
    )
    current = _ref(r, str(body["ref"]))
    if current != commit:
        raise _stop(r.main, run, "publication_unclear")
    append(
        r.main,
        run,
        session,
        op,
        "ref_moved",
        {"ref": body["ref"], "old": body["parent"], "new": commit},
    )
    index = result.get("index")
    if not isinstance(index, dict):
        index = _sync(r, run, body, commit)
    append(
        r.main,
        run,
        session,
        op,
        "sync_done",
        {"index": dict(cast(dict[str, Any], index))},
    )
    return finish(r.main, run)


def _records(
    r: rp.Repo, run: str, session: str, op: str, commit: str
) -> dict[str, str]:
    """Write each record of the land once: the ledger, the actions line, the snapshot drop.

    Raises:
        JournalRefusal: ``records_failed:snapshot`` (exit 1) when the drop fails.
    """
    facts: dict[str, str] = {}
    ledger = r.common / LEDGER_FOLDER / LEDGER_NAME
    if _lines_with(ledger, "run", run):
        facts["ledger"] = "present"
    else:
        _append_json(
            ledger, {"run": run, "session": session, "commit": commit, "at": _now()}
        )
        facts["ledger"] = "written"
    actions = r.common / ACTIONS_FOLDER / ACTIONS_NAME
    key = f"{run}:landed"
    if _lines_with(actions, "key", key):
        facts["actions"] = "present"
    else:
        _append_json(
            actions,
            {
                "key": key,
                "action": "landed",
                "run": run,
                "session": session,
                "commit": commit,
                "at": _now(),
            },
        )
        facts["actions"] = "written"
    if _ref(r, f"{RESULT_REF_PREFIX}{run}"):
        code, out = _invoke(
            [sys.executable, str(TOOLS / "result_snapshot.py"), "drop", "--run", run],
            r.main,
        )
        if code != 0:
            raise JournalRefusal(
                "records_failed:snapshot", out.strip()[-400:], EXIT_REFUSED
            )
        facts["snapshot"] = "dropped"
    else:
        facts["snapshot"] = "absent"
    return facts


def _park(
    r: rp.Repo, run: str, session: str, op: str, commit: str, reason: str
) -> dict[str, Any]:
    """Write ``parked``; the ref stays; the slot is freed."""
    append(r.main, run, session, op, "parked", {"reason": reason, "commit": commit})
    release_slot(r.main, run)
    return {"state": "parked", "commit": commit}


def _claim_spent(r: rp.Repo, intent: Mapping[str, Any]) -> bool:
    """Whether the typed direction of the land has one claim and it is spent."""
    uid = str(cast(dict[str, Any], intent["direction"])["uid"])
    try:
        held = cb._held_claims(r, uid)
    except rp.Refusal:
        return False
    return len(held) == 1 and held[0].state == cb.CLAIM_SPENT


def _path_matches(r: rp.Repo, commit: str, rel: str) -> bool:
    """Whether the worktree holds ``rel`` as ``commit`` does; an absent path must be absent."""
    entry = _git(r, "--literal-pathspecs", "ls-tree", "-z", commit, "--", rel)
    if entry.returncode != 0:
        return False
    if not entry.stdout:
        return not os.path.lexists(r.main / rel)
    blob = _git(r, "cat-file", "blob", f"{commit}:{rel}")
    work = rp._read_bytes(r.main / rel)
    return blob.returncode == 0 and work is not None and work == blob.stdout


def _land_checks(
    r: rp.Repo,
    lines: Sequence[Mapping[str, Any]],
    intent: Mapping[str, Any],
    commit: str,
    spent: Callable[[], bool],
) -> tuple[dict[str, str], str | None]:
    """The four audit checks that J runs; the first failed check name or None.

    ``spent`` answers for the authority: the typed direction.
    """
    checks: dict[str, str] = {}
    ref = str(intent["ref"])
    ancestor = _git(r, "merge-base", "--is-ancestor", commit, ref).returncode == 0
    checks["ancestor"] = "ok" if ancestor else "failed"
    if not ancestor:
        return checks, "ancestor"
    tree = _git(r, "rev-parse", f"{commit}^{{tree}}").stdout.decode("utf-8").strip()
    checks["tree"] = "ok" if tree == intent["tree"] else "failed"
    if tree != intent["tree"]:
        return checks, "tree"
    consumed = sum(1 for line in lines if line["step"] == "authority_consumed")
    checks["consumption"] = "ok" if consumed == 1 and spent() else "failed"
    if checks["consumption"] != "ok":
        return checks, "consumption"
    for rel in cast(list[str], intent["paths"]):
        if not _path_matches(r, commit, rel):
            checks["paths"] = "failed"
            return checks, "paths"
    checks["paths"] = "ok"
    return checks, None


def _sealed_covers(r: rp.Repo, plan: str, commit: str) -> bool:
    """Whether the plan's latest final receipt is sealed and its audit holds ``commit``.

    ``final --produce`` and ``--seal`` refuse a sealed generation as ``expired``: after a
    stop between the seal and ``audit_done`` this receipt is the audit of the land.
    """
    try:
        store = rp._snapshot(r, lambda: rp._load_store(r))
    except (rp.Refusal, rp.GitError, OSError):
        return False
    latest = rp._latest(store, plan)
    if latest is None or latest[1].get("sealed") is not True:
        return False
    audit = latest[1].get("publication_audit")
    found = audit.get("publications") if isinstance(audit, dict) else None
    return isinstance(found, list) and any(
        isinstance(item, dict) and item.get("ref_new") == commit
        for item in cast(list[Any], found)
    )


def finish(repo: Path | str, run: str) -> dict[str, Any]:
    """State 6: the records, the audit of the carrier, then ``closed`` and the slot release.

    A step that the journal holds is not repeated: after ``audit_done`` only ``closed`` is
    missing. A grant audit that refuses as ``expired`` passed before the stop when the
    sealed receipt of the plan holds this commit. A failed audit parks (the ref stays).
    An audit that cannot run (``legacy``) is
    ``audit_unsupported``: STOP with state 4, the slot kept, no park.

    Raises:
        JournalRefusal: ``crash_state:4:audit_unsupported`` (exit 3);
            ``records_failed:snapshot`` (exit 1).
    """
    r = _repo(repo)
    lines = read(r.main, run)
    steps = [str(line["step"]) for line in lines]
    consumed = _last(lines, "authority_consumed")
    if consumed is None or "sync_done" not in steps:
        raise JournalRefusal("finish_early", run, EXIT_REFUSED)
    if steps[-1] in TERMINAL:
        return {"state": steps[-1], "commit": consumed["commit"]}
    intent = _intent_of(lines, run)
    commit = str(consumed["commit"])
    session = str(lines[-1]["session"])
    op = str(intent["op"])
    if "records_done" not in steps:
        append(
            r.main,
            run,
            session,
            op,
            "records_done",
            _records(r, run, session, op, commit),
        )
    if "audit_done" in steps:
        return _close(r, run, session, op, commit)
    if intent["carrier"] == "grant":
        audit: dict[str, Any] = {"carrier": "grant"}
        for flag, name in (("--produce", "produce"), ("--seal", "seal")):
            code, out = _invoke(
                [
                    sys.executable,
                    str(TOOLS / "run_parameters.py"),
                    "--repo",
                    str(r.main),
                    "final",
                    "--plan",
                    str(intent["plan"]),
                    flag,
                ],
                r.main,
            )
            if code != 0:
                reason = _json_reason(out)
                if reason == LEGACY_REASON:
                    raise _stop(r.main, run, "audit_unsupported")
                if reason == EXPIRED_REASON and _sealed_covers(
                    r, str(intent["plan"]), commit
                ):
                    audit.update({"produce": "ok", "seal": "ok", "from": "sealed"})
                    break
                return _park(r, run, session, op, commit, f"audit_failed:{name}")
            audit[name] = "ok"
    else:
        audit = {"carrier": intent["carrier"]}

        def spent() -> bool:
            return _claim_spent(r, intent)

        checks, failed = _land_checks(r, lines, intent, commit, spent)
        if failed is not None:
            return _park(r, run, session, op, commit, f"audit_failed:{failed}")
        audit["checks"] = checks
    append(r.main, run, session, op, "audit_done", audit)
    return _close(r, run, session, op, commit)


def _close(r: rp.Repo, run: str, session: str, op: str, commit: str) -> dict[str, Any]:
    """Write ``closed`` and free the slot."""
    append(r.main, run, session, op, "closed", {"commit": commit})
    release_slot(r.main, run)
    return {"state": "closed", "commit": commit}


# ---------------------------------------------------------------------------
# crash states
# ---------------------------------------------------------------------------


def _chain(pairs: Sequence[tuple[str, str]], parent: str) -> list[str]:
    """The commits that the reflog moves lead through from ``parent``, in order.

    A batch publishes one sub-op ``<op>/<n>`` per packet, each on the commit before, so
    the land's C is the end of the chain, not a single ``(P, C)`` entry.
    """
    chain: list[str] = []
    current = parent
    for old, new in pairs:
        if old == current and new != current:
            chain.append(new)
            current = new
    return chain


def _state(
    r: rp.Repo, run: str, lines: Sequence[Mapping[str, Any]]
) -> tuple[int, str, str]:
    """``(state, why, commit)`` of a journal that has no terminal step.

    With no ``authority_consumed`` line the reflog is the only proof, so state 1 needs a
    reflog that reaches P and ends at the ref. A chain of the op that ends at another tree
    than the intent's T is a batch that published a part of its packets: state 4.
    """
    steps = [str(line["step"]) for line in lines]
    if "sync_done" in steps:
        return 6, "", ""
    if "ref_moved" in steps:
        return 5, "", ""
    if "intent" not in steps:
        return 1, "", ""
    intent = _intent_of(lines, run)
    ref = str(intent["ref"])
    parent = str(intent["parent"])
    current = _ref(r, ref)
    consumed = _last(lines, "authority_consumed")
    if consumed is None:
        entries = _reflog_entries(r, _branch(ref))
        if entries is None:
            return 4, "reflog_cannot_answer", ""
        mark = re.compile(rf"commit_batch: {re.escape(str(intent['op']))}{OP_SUFFIX}")
        hits = _chain(
            [(old, new) for old, new, msg in entries if mark.fullmatch(msg)], parent
        )
        if not hits:
            if all(new != parent for _old, new, _msg in entries):
                return 4, "reflog_cannot_answer", ""
            if entries[-1][1] != current:
                return 4, "publication_unclear", ""
            return 1, "", ""
        tree = _git(r, "rev-parse", "--verify", "-q", f"{hits[-1]}^{{tree}}")
        if (
            current != hits[-1]
            or tree.returncode != 0
            or tree.stdout.decode("utf-8").strip() != intent["tree"]
        ):
            return 4, "publication_unclear", ""
        return 3, "", hits[-1]
    commit = str(consumed["commit"])
    pairs = cb._reflog(cast(Any, _shim(r, run, intent, commit)))
    if pairs is None:
        return 4, "reflog_cannot_answer", ""
    published = commit in _chain(pairs, parent)
    if current == commit and published:
        return 3, "", commit
    if current == parent and not published:
        return 2, "", commit
    return 4, "publication_unclear", ""


def _admin_folders(r: rp.Repo) -> dict[str, Path]:
    """``{worktree path: admin folder}`` of the repository's linked worktrees."""
    found: dict[str, Path] = {}
    base = r.common / "worktrees"
    for admin in sorted(base.iterdir()) if base.is_dir() else []:
        text = rp._read_text(admin / "gitdir")
        if text:
            found[rp.display_path(Path(text.strip()).parent).lower()] = admin
    return found


def _drop_worktree(r: rp.Repo, path: Path, admin: Path) -> None:
    """Remove one half-made worktree: its lock, its folder, then its registration."""
    rp._unlink(admin / "locked")
    if path.exists():
        rp._rmtree(path)
    _git(r, "worktree", "prune")


def _other_ops(r: rp.Repo, run: str, op: str) -> set[str]:
    """The lower-case names of each op that is not the op of ``run`` or a retry of it.

    The sources are the op store (``ops/<plan>/<run>/<op>`` and ``ops/planless/<digest>/<op>``)
    and the intents of the other journals, read without a check: a journal that does not
    read still names its ops.
    """
    own = re.compile(re.escape(op.lower()) + r"(-r[0-9]+)?")
    found = {
        path.name.lower()
        for path in r.store.glob("ops/*/*/*")
        if path.is_dir() and own.fullmatch(path.name.lower()) is None
    }
    for path in _folder(r).glob("*.jsonl"):
        if path.stem == run:
            continue
        for raw in (rp._read_text(path) or "").splitlines():
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            facts = item.get("facts") if isinstance(item, dict) else None
            if isinstance(facts, dict) and item.get("step") == "intent":
                found.add(str(facts.get("op")).lower())
    return found


def _own_manifest(admin: Path, op: str) -> bool:
    """Whether the candidate manifest in ``admin`` names this op, or names none."""
    try:
        body = json.loads(rp._read_text(admin / cb.MANIFEST_NAME) or "")
    except json.JSONDecodeError:
        return False
    if not isinstance(body, dict):
        return False
    named = cast(dict[str, Any], body).get("op")
    own = re.compile(re.escape(op) + OP_SUFFIX)
    return named is None or own.fullmatch(str(named)) is not None


def _holds_work(r: rp.Repo, path: Path, admin: Path, parent: str) -> bool:
    """Whether the worktree holds more than ``git worktree add`` of ``parent`` wrote.

    ``git worktree add`` writes the index last. With an index, each status entry other than
    a missing file is work; without one, each file that the parent's tree does not hold.
    An answer that git cannot give counts as work.
    """
    if not path.is_dir():
        return False
    if (admin / "index").exists():
        status = _git(
            r,
            "--no-optional-locks",
            "-C",
            str(path),
            "status",
            "--porcelain",
            "--ignored",
            "-z",
        )
        entries = [item for item in status.stdout.split(b"\0") if item]
        return status.returncode != 0 or any(
            not item.startswith(b" D ") for item in entries
        )
    listing = _git(r, "ls-tree", "-r", "-z", "--name-only", parent)
    if listing.returncode != 0:
        return True
    known = set(listing.stdout.decode("utf-8", errors="replace").split("\0"))
    return any(
        item.relative_to(path).as_posix() not in known
        for item in path.rglob("*")
        if not item.is_dir() and item != path / ".git"
    )


def _clear_candidate(r: rp.Repo, run: str, intent: Mapping[str, Any]) -> None:
    """Remove what a killed land left at the commit candidate path of its own op.

    The caller holds the drive lock of ``run``, so no land of this run is alive.

    commit_batch writes the candidate's manifest after ``git worktree add``; a kill between
    the two leaves a worktree that its retry refuses as ``candidate_foreign``. Only a linked
    worktree of this repository goes, at a candidate path of this op and of no other op, at
    the intent's parent (or with no HEAD yet), with no manifest, with no lock other than the
    one of ``git worktree add``, and with no file that ``git worktree add`` did not write. A
    candidate that has a manifest belongs to commit_batch: only the lock files of a dead git
    process go, and only when the manifest names this op. Everything else stays, and the
    land refuses it.

    Raises:
        JournalRefusal: ``land_live:<run>`` (exit 4) while a live driver holds the direction.
    """
    direction = intent.get("direction")
    if isinstance(direction, Mapping):
        uid = str(direction["uid"])
        _check_run(uid)
        if cb._direction_lease_live(r.store / cb.DIRECTION_LEASE_DIR / f"{uid}.lock"):
            raise JournalRefusal(f"land_live:{run}", "", EXIT_BUSY)
    root = rp.display_path(cb._candidate_root(r)).lower()
    op = str(intent["op"])
    name = re.compile(re.escape(op.lower()) + r"(-r[0-9]+)?(-[0-9]+)?")
    others = _other_ops(r, run, op)
    admins = _admin_folders(r)
    proc = _git(r, "worktree", "list", "--porcelain")
    for block in proc.stdout.decode("utf-8", errors="replace").split("\n\n"):
        facts: dict[str, str] = {}
        for line in block.splitlines():
            word, _space, value = line.partition(" ")
            facts[word] = value
        path = Path(rp.display_path(facts.get("worktree", "")))
        key = rp.display_path(path).lower()
        admin = admins.get(key)
        if admin is None or rp.display_path(path.parent).lower() != root:
            continue
        mine = path.name.lower()
        if name.fullmatch(mine) is None:
            continue
        # ``<op>-<n>`` is a sub-op candidate of this op, or a candidate of an op of that name.
        if mine in others or re.sub(r"-[0-9]+$", "", mine) in others:
            continue
        if (admin / cb.MANIFEST_NAME).exists():
            if _own_manifest(admin, op):
                for lock in ("index.lock", "HEAD.lock"):
                    rp._unlink(admin / lock)
            continue
        head = facts.get("HEAD", "")
        if head.strip("0") and head != intent["parent"]:
            continue
        if facts.get("locked", "initializing") != "initializing":
            continue
        if _holds_work(r, path, admin, str(intent["parent"])):
            continue
        _drop_worktree(r, path, admin)


def classify(repo: Path | str, run: str) -> str:
    """``crash_state:<1..6>`` of an open journal, or ``closed`` for a terminal one.

    Raises:
        JournalRefusal: ``journal_bad:<n>`` (exit 2); ``journal_missing`` (exit 1).
    """
    r = _repo(repo)
    lines = read(r.main, run)
    if not lines:
        raise JournalRefusal("journal_missing", run, EXIT_REFUSED)
    if lines[-1]["step"] in TERMINAL:
        return "closed"
    return f"crash_state:{_state(r, run, lines)[0]}"


def recover(repo: Path | str, run: str) -> str:
    """Do the one action of the crash state; ``closed``, ``parked`` or ``land_again``.

    Recovery never claims, takes or spends a direction: a consumption that the reflog
    proves is recorded, never repeated.

    Raises:
        JournalRefusal: ``land_blocked:journal_stop:<run>`` (exit 3) while STOP exists;
            ``crash_state:4:<why>`` (exit 3) for an ambiguous state;
            ``journal_bad:<n>`` (exit 2); ``land_live:<run>`` (exit 4).
    """
    r = _repo(repo)
    lines = read(r.main, run)
    if not lines:
        raise JournalRefusal("journal_missing", run, EXIT_REFUSED)
    last = str(lines[-1]["step"])
    if last in TERMINAL:
        release_slot(r.main, run)
        return "parked" if last == "parked" else "closed"
    _refuse_stop(r.main)
    with _DriveLock(r, run):
        return _recover(r, run)


def _recover(r: rp.Repo, run: str) -> str:
    """``recover`` under the drive lock, for the journal as it reads now."""
    lines = read(r.main, run)
    last = str(lines[-1]["step"])
    if last in TERMINAL:
        release_slot(r.main, run)
        return "parked" if last == "parked" else "closed"
    state, why, commit = _state(r, run, lines)
    if state == 1:
        if any(line["step"] == "intent" for line in lines):
            _clear_candidate(r, run, _intent_of(lines, run))
        return "land_again"
    if state == 4:
        raise _stop(r.main, run, why)
    intent = _intent_of(lines, run)
    session = str(lines[-1]["session"])
    op = str(intent["op"])
    ref = str(intent["ref"])
    parent = str(intent["parent"])
    steps = [str(line["step"]) for line in lines]
    if state in (2, 3):
        if state == 2:
            moved = _git(
                r, "update-ref", "-m", f"commit_batch: {op}", ref, commit, parent
            )
            if moved.returncode != 0:
                raise _stop(r.main, run, "publication_unclear")
        if "authority_consumed" not in steps:
            if steps[-1] == "intent":
                append(r.main, run, session, op, "authority_checked", {})
            append(
                r.main,
                run,
                session,
                op,
                "authority_consumed",
                {"commit": commit, "op": op, "from": "reflog"},
            )
        append(
            r.main,
            run,
            session,
            op,
            "ref_moved",
            {"ref": ref, "old": parent, "new": commit},
        )
        state = 5
    if state == 5:
        consumed = _last(read(r.main, run), "authority_consumed")
        commit = str(cast(dict[str, Any], consumed)["commit"])
        append(
            r.main,
            run,
            session,
            op,
            "sync_done",
            {"index": _sync(r, run, intent, commit)},
        )
    return str(finish(r.main, run)["state"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # noqa: D102 - argparse hook
        raise JournalRefusal("land_journal_bad:args", message, EXIT_BAD)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="land_journal.py", description=(__doc__ or "").split("\n", 1)[0]
    )
    parser.add_argument("--repo", default=".", help="a path in the repository")
    sub = parser.add_subparsers(dest="verb", required=True, parser_class=_Parser)
    sub.add_parser("status", help="each journal's last step and state, and STOP")
    rec = sub.add_parser("recover", help="do the one action of a run's crash state")
    rec.add_argument("--run", required=True)
    stop = sub.add_parser("stop", help="write STOP for a run (a human-held stop)")
    stop.add_argument("--run", required=True)
    stop.add_argument("--reason", required=True)
    clear = sub.add_parser("clear-stop", help="remove STOP on a typed human ruling")
    clear.add_argument("--run", required=True)
    clear.add_argument("--session", required=True)
    clear.add_argument("--message-uuid", required=True)
    return parser


def _status(repo: Path | str) -> int:
    r = _repo(repo)
    code = EXIT_OK
    folder = _folder(r)
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        run = path.stem
        if path.name == CLEARED_NAME or RUN_RE.fullmatch(run) is None:
            continue
        try:
            lines = read(r.main, run)
            last = str(lines[-1]["step"]) if lines else "none"
            state = classify(r.main, run) if lines else "none"
        except JournalRefusal as exc:
            if exc.code == EXIT_BAD:
                print(exc.reason)
                print(f"{exc.reason} {run}", file=sys.stderr)
                code = EXIT_BAD
            else:
                print(f"land_journal {run} {exc.reason}")
            continue
        print(f"land_journal {run} {last} {state}")
    stop = read_stop(r.main)
    if stop is not None:
        print(f"journal_stop {stop['run']}")
    slot = _slot_body(r)
    if slot is not None:
        print(f"final_validation {slot.get('run')}")
    return code


def _clear_stop(repo: Path | str, run: str, session: str, uid: str) -> int:
    r = _repo(repo)
    try:
        raw, text = rp._human_record(r, session, uid)
    except rp.Refusal as exc:
        raise JournalRefusal(f"record:{exc.reason}", exc.detail, EXIT_REFUSED) from exc
    if text.strip() != CLEAR_TEXT.format(run=run):
        raise JournalRefusal("ruling_form", text.strip()[:200], EXIT_REFUSED)
    stop = read_stop(r.main)
    if stop is None:
        raise JournalRefusal("no_stop", run, EXIT_REFUSED)
    if stop["run"] not in (run, "unknown"):
        raise JournalRefusal("stop_run", str(stop["run"]), EXIT_REFUSED)
    _append_json(
        _folder(r) / CLEARED_NAME,
        {
            "run": run,
            "session": session,
            "message_uuid": uid,
            "record_digest": rp._digest(raw.encode("utf-8")),
            "stop": stop,
            "at": _now(),
        },
    )
    rp._unlink(_folder(r) / STOP_NAME)
    print(f"stop_cleared {run}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run one verb; see the module docstring for the exit codes."""
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
        if args.verb == "status":
            return _status(args.repo)
        run = _check_run(args.run)
        if args.verb == "recover":
            print(f"land_journal_recovered {run} {recover(args.repo, run)}")
            return EXIT_OK
        if args.verb == "stop":
            reason = str(args.reason)
            if (
                not reason.strip()
                or len(reason) > REASON_MAX
                or "\n" in reason
                or "\r" in reason
            ):
                warn(
                    "land_journal_refused",
                    limit_name="reason_length",
                    configured_value=REASON_MAX,
                    observed_value=len(reason),
                    window="per call",
                )
                raise JournalRefusal("land_journal_bad:reason", "", EXIT_BAD)
            write_stop(args.repo, run, reason, 0)
            print(f"journal_stop {run}")
            return EXIT_OK
        return _clear_stop(args.repo, run, str(args.session), str(args.message_uuid))
    except JournalRefusal as exc:
        bad = exc.reason.startswith(
            ("journal_bad", "land_journal_bad", "land_blocked", "crash_state")
        )
        print(exc.reason if bad else f"land_journal_refused:{exc.reason}")
        if exc.detail:
            print(exc.detail, file=sys.stderr)
        return exc.code
    except OSError as exc:
        print("land_journal_refused:io")
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
