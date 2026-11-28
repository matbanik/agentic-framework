"""Scheduler views and pilot actions of the session groupings (MEU-925, MEU-951).

``python tools/orch.py simulate`` replays the greedy lane schedule of the grouping
guide on a spec fixture (``--spec``) or on grouping files (``--grouping``) and prints
the makespan. ``python tools/orch.py eligible`` reads the Session Progress tables of
the groupings and the lane cards, and prints the sessions that can start now and the
reasons of each session that cannot.

The pilot verbs (MEU-951) serve the replay route of two parallel sessions:
``facts <sessions|claims|land-queue>`` prints one JSON object with a ``rev`` (the
SHA-256 of the canonical JSON of the three facts); ``start`` makes one scratch clone
and one worker launch per session after the pilot-fit checks and the typed start
sentence; ``land --stage prepare|commit`` runs the snapshot, the replay, the gate
candidate and the commit; ``report`` writes the pilot report. Each action takes a
``--key`` (one action per key) and a ``--rev`` (a stale rev refuses) and appends one
line to the actions log of the git common dir.

The read verbs (``eligible``, ``simulate``, ``facts``, ``report``) change nothing but
the report file. ``start`` and ``land`` start a process only through the seam of
``result_snapshot.py`` (``run_tool``, bound here as ``_invoke``): this file imports no
process module and calls no process function (AC-925.7, AC-951.4). It never commits
on its own account, never reviews, never rules and never pushes; a land commit goes
through ``commit_batch.py`` under the user's typed direction or the standing grant. A
refused input prints ``<verb>_bad:<reason>`` on stdout line 1 and the detail on
stderr, and exits 1. An argument error exits 2.

Order rules (``must_follow``): the ``after`` ids of a session, and each session of the
same grouping with a lower tier that shares an ``owns`` entry. Two sessions conflict
when they share an ``owns`` entry or both use the test VM. ``eligible`` compares the
entries of a busy session or a reserving card as ``lanes.py`` admits a lane
(``live_overlap``): NFC text, case-folded when the repository's ``core.ignorecase``
is true, and component-aware. The order rules and the replay keep the guide rule
(``overlap``). The schedule does not
model the review cap or the plan-commit cap (``CAPS_NOT_MODELED``); ``eligible``
reports both as resources from the counts that the caller gives.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if __package__:
    from . import executor_worktree as ew
    from . import lanes, result_snapshot
    from . import run_parameters as rp
else:  # run as a script, or imported with tools/ on sys.path
    import executor_worktree as ew
    import lanes
    import result_snapshot
    import run_parameters as rp

# The one process seam (EA-7): the tests replace both names. ``DISPATCH_ROOT`` is the
# receipts root of the dispatch wrapper; the briefs go under ``<root>/<key>/`` and the
# worker status of a launch is ``<root>/dispatch/<id>/status.json``.
_invoke: Callable[..., tuple[int, str]] = result_snapshot.run_tool
DISPATCH_ROOT: Path = result_snapshot.RECEIPTS_ROOT
# The time limit of one worker launch. A worker runs a whole plan session, so it
# takes the workflow-run limit of the credits wrapper (14400-43200 s,
# .agent/skills/claude-credits/SKILL.md "Choose the flags"), not the effort
# default of 1800 s, which stopped both pilot B workers in mid-plan (EA-15).
WORKER_TIMEOUT_SEC = 43200

WEIGHTS: dict[str, float] = dict(
    zip(lanes.SIZE_VALUES, (1.0, 1.5, 2.0, 2.5, 3.0), strict=True)
)
REVIEW_CAP = 3
PLAN_COMMIT_CAP = 1
VM_CAP = 1
E2E_CAP = 1
CAPS_NOT_MODELED = (f"reviews:{REVIEW_CAP}", f"plan_commits:{PLAN_COMMIT_CAP}")
SPEC_SCHEMA = "orch-spec/1"
SPEC_TOP_KEYS = ("schema", "lanes", "sessions")
SPEC_KEYS = ("lane", "size", "tier", "owns", "after", "vm")
ORDERS = ("critical-path", "guide")
TREES = ("main", "lanes")
PROGRESS_HEADING = "## Session Progress"
CANDIDATE_STATUSES = ("pending", "▶ NEXT")
RUNNING_STATUS = "in-progress"
FINISHED_WORDS = ("done", "skipped")
STOPPED_WORDS = ("blocked", "split")
WINDOW = "concurrent"
EXIT_OK = 0
EXIT_REFUSED = lanes.EXIT_REFUSED
EXIT_USAGE = 2

_SID_RE = re.compile(r"([A-Z]+)([0-9]+)([a-z]?)")
_STATUS_WORD_RE = re.compile(r"(done|skipped|blocked|split)(?![A-Za-z0-9_-])")
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
_SEPARATOR_RE = re.compile(r"\|(?:\s*:?-+:?\s*\|)+")
_FRONT_KEY_RE = re.compile(r"(grouping_source|grouping_session):(.*)")
_GITDIR_PREFIX = "gitdir:"
_SECTION_RE = re.compile(r"\s*\[([^\]]*)\](.*)")
_IGNORECASE_RE = re.compile(r"\s*ignorecase\s*(?:=(.*))?", re.IGNORECASE)
_COMMENT_RE = re.compile(r"[#;]")
_GIT_TRUE = ("true", "yes", "on")
_GIT_FALSE = ("false", "no", "off", "")
_NULL_VALUES = ("", "null", "~")
_MAIN_QUEUE = "*"

# MEU-951: the pilot verbs.
FACT_KINDS = ("sessions", "claims", "land-queue")
STAGES = ("prepare", "commit")
REPORT_COLUMNS = (
    "Session",
    "Wait to start",
    "Wait to land",
    "Review queue",
    "Gate at first run",
)
# The gate records the report reads (EA-34): ``tools/validate_codebase.py`` writes each
# run's ``gate.json`` under its runs root. The report reads this root and the folder of
# each gate run that a land commit names (a run under an override root); the tests
# replace this name, as they replace ``DISPATCH_ROOT``.
GATE_RUNS_ROOT: Path = result_snapshot.RECEIPTS_ROOT / "gate-runs"
GATE_RECORD_NAME = "gate.json"
GATE_NAME_SLACK = timedelta(minutes=5)
ACTIONS_NAME = "actions.jsonl"
DISPATCH_FOLDER = "dispatch"
STATUS_NAME = "status.json"
PILOT_SIZES = ("small", "small-to-medium")
PILOT_SCHEMA = "ag3-pilots/1"
POLICY_PATH = ".agent/run-parameters.policy.json"
PLANS_DIR = "docs/execution/plans"
HANDOFFS_DIR = ".agent/context/handoffs"
REVIEW_SUFFIX = "-plan-critical-review.md"
LOCK_NAMES = ("uv.lock", "package-lock.json")
# AC-933.2: the agent-configuration files and folders (the integrity set) and the
# governance documents; a pilot session never owns one of them. The plan's PILOT_FIT
# names the whole ``.agent/docs/`` and ``.claude/`` prefixes (EA-37, review R1-F3);
# the narrower ``.claude/`` entries below stay as the integrity set names them.
GOVERNANCE_PATHS = (
    "AGENTS.md",
    "GUARDRAILS.md",
    "CLAUDE.md",
    ".agent/docs/",
    ".claude/",
    ".mcp.json",
    ".pre-commit-config.yaml",
    ".claude/settings.json",
    ".claude/settings.local.json",
    "tools/Invoke-CodexDispatch.ps1",
    "tools/Invoke-ClaudeDispatch.ps1",
    "tools/agent_config_integrity.py",
    ".agent/skills/",
    ".agent/workflows/",
    ".agent/roles/",
    ".claude/hooks/",
    ".claude/agents/",
    ".codex/",
    ".cursor/",
    ".vscode/",
    ".github/",
)
START_SENTENCE_RE = re.compile(
    r"start pilot b with ([A-Za-z0-9]+) and ([A-Za-z0-9]+)\.?", re.IGNORECASE
)
_KEY_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_REV_RE = re.compile(r"[0-9a-f]{64}")
_DISPATCH_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
_CLONE_READY_RE = re.compile(r"clone_ready (.+) parent=([0-9a-f]{40})")
_CANDIDATE_READY_RE = re.compile(r"gate_candidate_ready (.+) parent=\S+ tree=\S+")
_FRONT_STATUS_RE = re.compile(r"status:\s*[\"']?([A-Za-z-]+)[\"']?\s*(?:#.*)?")
_CD_RE = re.compile(r"\bcd\s+(?:/d\s+)?[\"']?([^\s\"';&|]+)")
_MSYS_DRIVE_RE = re.compile(r"/([a-z])/(.*)")


@dataclass(frozen=True)
class Session:
    """One session to schedule: its spec values and the grouping it comes from.

    ``lane`` is the fixture lane, or the letter prefix of the id for a grouping.
    ``group`` is the fixture lane, or the grouping file: the tier order applies
    inside one group only. ``size`` is None when a grouping states no size:
    ``simulate`` refuses it, and the critical-path order gives it no weight.
    """

    sid: str
    lane: str
    group: str
    size: str | None
    tier: int
    owns: tuple[str, ...]
    after: tuple[str, ...]
    vm: bool = False
    e2e: bool = False
    hold: lanes.Hold | None = None


@dataclass(frozen=True)
class Conflict:
    """Why two sessions cannot run at the same time.

    ``entries`` are the shared ``owns`` entries (``overlap``); ``vm`` is True when
    both sessions use the test VM.
    """

    entries: tuple[str, ...]
    vm: bool


@dataclass(frozen=True)
class Reservation:
    """A reserving lane card (``active`` or ``landing``).

    ``worktree`` is the normalized worktree path. ``session`` is the grouping session
    that the card's plan names, or None for a card that maps to no session on the
    command line.
    """

    lane: str
    worktree: str
    owns: tuple[str, ...]
    session: str | None


# ---------------------------------------------------------------------------
# The order rules
# ---------------------------------------------------------------------------


def overlap(a: Sequence[str], b: Sequence[str]) -> list[str]:
    """The entries that ``a`` and ``b`` share, as the grouping guide counts them.

    Two entries overlap when they are equal, or when one ends in ``/`` and is a
    prefix of the other. Each hit is the longer entry, once, in the order found.
    """
    hits: list[str] = []
    for x in a:
        for y in b:
            if (
                x == y
                or (x.endswith("/") and y.startswith(x))
                or (y.endswith("/") and x.startswith(y))
            ):
                hit = x if len(x) >= len(y) else y
                if hit not in hits:
                    hits.append(hit)
    return hits


def live_overlap(a: Sequence[str], b: Sequence[str], *, ignorecase: bool) -> list[str]:
    """The entries of ``a`` and ``b`` that collide as ``lanes.py`` reserves them.

    Each entry is compared in NFC, case-folded when ``ignorecase`` is true
    (``lanes._normalize``), by the component-aware rule (``lanes._overlaps``).
    Each hit is the longer entry as written (the entry of ``a`` on a tie), once, in
    the order found.
    """
    hits: list[str] = []
    for x in a:
        mine = lanes._normalize(x, ignorecase)
        for y in b:
            theirs = lanes._normalize(y, ignorecase)
            if lanes._overlaps(mine, theirs):
                hit = x if len(mine) >= len(theirs) else y
                if hit not in hits:
                    hits.append(hit)
    return hits


def must_follow(session: Session, sessions: Mapping[str, Session]) -> list[str]:
    """The sessions that must land before ``session`` starts, in input order.

    They are the ``after`` ids, and each session of the same group with a lower
    tier that shares an ``owns`` entry with ``session``.

    Raises:
        ValueError: an ``after`` id is not a key of ``sessions``.
    """
    index = {sid: i for i, sid in enumerate(sessions)}
    unknown = sorted(sid for sid in session.after if sid not in index)
    if unknown:
        raise ValueError(f"{session.sid}: after names unknown sessions {unknown}")
    found = set(session.after)
    for other in sessions.values():
        if (
            other.sid != session.sid
            and other.group == session.group
            and other.tier < session.tier
            and overlap(session.owns, other.owns)
        ):
            found.add(other.sid)
    return sorted(found, key=index.__getitem__)


def conflicts(session: Session, sessions: Mapping[str, Session]) -> dict[str, Conflict]:
    """The other sessions that cannot run at the same time as ``session``.

    A session that shares no ``owns`` entry and does not use the VM with
    ``session`` is not in the map.
    """
    out: dict[str, Conflict] = {}
    for other in sessions.values():
        if other.sid == session.sid:
            continue
        entries = tuple(overlap(session.owns, other.owns))
        vm = session.vm and other.vm
        if entries or vm:
            out[other.sid] = Conflict(entries, vm)
    return out


def _weight(session: Session) -> float:
    """The size weight of ``session`` (``WEIGHTS``); 0.0 when it states no size."""
    return 0.0 if session.size is None else WEIGHTS[session.size]


def critical_path(
    sessions: Mapping[str, Session], follow: Mapping[str, Sequence[str]]
) -> dict[str, float]:
    """The weighted length of the longest chain that starts at each session of ``follow``.

    A chain runs from a session through the sessions that must follow it; the length
    is the sum of the size weights (``_weight``: a session with no size adds 0).
    ``follow`` maps each session in scope to its ``must_follow`` list. A member
    outside the scope is in no chain.

    Raises:
        ValueError: ``follow`` has a cycle.
    """
    dependents: dict[str, list[str]] = {sid: [] for sid in follow}
    waiting: dict[str, int] = {}
    for sid, members in follow.items():
        inside = [member for member in members if member in dependents]
        waiting[sid] = len(inside)
        for member in inside:
            dependents[member].append(sid)
    ready = [sid for sid in follow if waiting[sid] == 0]
    order: list[str] = []
    while ready:
        sid = ready.pop()
        order.append(sid)
        for dependent in dependents[sid]:
            waiting[dependent] -= 1
            if waiting[dependent] == 0:
                ready.append(dependent)
    if len(order) != len(follow):
        raise ValueError("the must_follow lists have a cycle")
    length: dict[str, float] = {}
    for sid in reversed(order):
        tail = max((length[dependent] for dependent in dependents[sid]), default=0.0)
        length[sid] = _weight(sessions[sid]) + tail
    return length


def _follow_map(sessions: Mapping[str, Session]) -> dict[str, list[str]]:
    """``must_follow`` of every session, in input order."""
    return {sid: must_follow(session, sessions) for sid, session in sessions.items()}


def _cycle_members(follow: Mapping[str, Sequence[str]]) -> list[str]:
    """The sessions that are on a ``must_follow`` cycle, in input order."""
    members: list[str] = []
    for sid in follow:
        seen: set[str] = set()
        stack = list(follow[sid])
        while stack:
            current = stack.pop()
            if current == sid:
                members.append(sid)
                break
            if current in seen:
                continue
            seen.add(current)
            stack.extend(follow[current])
    return members


def _sid_order(sid: str) -> tuple[int, str]:
    """The number and the letter suffix of a session id, for the tie order.

    Raises:
        ValueError: ``sid`` is not a session id.
    """
    match = _SID_RE.fullmatch(sid)
    if match is None:
        raise ValueError(f"not a session id: {sid!r}")
    return int(match.group(2)), match.group(3)


def _rank(
    sessions: Mapping[str, Session],
    lane_list: Sequence[str],
    follow: Mapping[str, Sequence[str]],
    order: str,
) -> list[str]:
    """The sessions of ``follow`` in queue order.

    ``guide`` keeps the input order. ``critical-path`` puts the longest chain first,
    then the lane order, then the id number, then the id suffix.
    """
    if order == "guide":
        return list(follow)
    length = critical_path(sessions, follow)
    lane_index = {lane: i for i, lane in enumerate(lane_list)}
    return sorted(
        follow,
        key=lambda sid: (
            -length[sid],
            lane_index[sessions[sid].lane],
            *_sid_order(sid),
        ),
    )


# ---------------------------------------------------------------------------
# The inputs
# ---------------------------------------------------------------------------


def _lane_of(sid: object) -> str:
    """The letter prefix of a session id.

    Raises:
        lanes.Refusal: ``sid:<sid>`` for an id that is not capital letters, a
            number and an optional lowercase letter.
    """
    match = _SID_RE.fullmatch(sid) if isinstance(sid, str) else None
    if match is None:
        raise lanes.Refusal(
            f"sid:{sid}",
            "a session id is capital letters, a number and an optional lowercase letter",
        )
    return match.group(1)


def _check_graph(sessions: Mapping[str, Session]) -> None:
    """Refuse an ``after`` id that is not a session, and a ``must_follow`` cycle.

    Raises:
        lanes.Refusal: ``after:<sid>:<id>`` or ``cycle:<ids>``.
    """
    for session in sessions.values():
        for other in session.after:
            if other not in sessions:
                raise lanes.Refusal(
                    f"after:{session.sid}:{other}",
                    f"{session.sid} must follow {other}, which no input names",
                )
    members = _cycle_members(_follow_map(sessions))
    if members:
        raise lanes.Refusal(
            "cycle:" + ",".join(members),
            "these sessions must each land before another of them starts",
        )


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """A JSON object hook that refuses a repeated key.

    Raises:
        ValueError: a key is in the object twice.
    """
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"the key {key!r} is in one object twice")
        out[key] = value
    return out


def _spec_session(sid: str, value: object, lane_list: Sequence[str]) -> Session:
    """One fixture session, with each field checked.

    Raises:
        lanes.Refusal: ``key:<sid>:<key>`` for an unknown key, else
            ``<field>:<sid>`` for the first missing or bad field.
    """
    if not isinstance(value, dict):
        raise lanes.Refusal(f"session:{sid}", "a session is one JSON object")
    extra = [str(key) for key in value if key not in SPEC_KEYS]
    if extra:
        raise lanes.Refusal(f"key:{sid}:{extra[0]}", f"the keys are {list(SPEC_KEYS)}")
    for key in SPEC_KEYS:
        if key not in value:
            raise lanes.Refusal(f"{key}:{sid}", "missing")
    lane, size, tier = value["lane"], value["size"], value["tier"]
    owns, after, vm = value["owns"], value["after"], value["vm"]
    if not isinstance(lane, str) or lane not in lane_list:
        raise lanes.Refusal(f"lane:{sid}", f"one of {list(lane_list)}")
    if not isinstance(size, str) or size not in WEIGHTS:
        raise lanes.Refusal(f"size:{sid}", f"one of {list(WEIGHTS)}")
    if not isinstance(tier, int) or isinstance(tier, bool) or tier < 1:
        raise lanes.Refusal(f"tier:{sid}", "a whole number of 1 or more")
    if not isinstance(owns, list) or not all(
        isinstance(entry, str) and entry for entry in owns
    ):
        raise lanes.Refusal(f"owns:{sid}", "a list of non-empty strings")
    if not isinstance(after, list) or not all(
        isinstance(other, str) for other in after
    ):
        raise lanes.Refusal(f"after:{sid}", "a list of session ids")
    if not isinstance(vm, bool):
        raise lanes.Refusal(f"vm:{sid}", "true or false")
    return Session(
        sid=sid,
        lane=lane,
        group=lane,
        size=size,
        tier=tier,
        owns=tuple(owns),
        after=tuple(dict.fromkeys(after)),
        vm=vm,
    )


def load_spec(path: Path) -> tuple[list[str], dict[str, Session]]:
    """The lanes and the sessions of an ``orch-spec/1`` fixture, in file order.

    Raises:
        lanes.Refusal: ``spec:<part>`` for a file that is not the schema,
            ``sid:<sid>``, a ``_spec_session`` reason, or a ``_check_graph`` reason.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise lanes.Refusal("spec:read", f"{path}: {exc}") from None
    try:
        data = json.loads(raw, object_pairs_hook=_unique_pairs)
    except ValueError as exc:
        raise lanes.Refusal("spec:json", f"{path}: {exc}") from None
    if not isinstance(data, dict) or data.get("schema") != SPEC_SCHEMA:
        raise lanes.Refusal("spec:schema", f"{path}: want schema {SPEC_SCHEMA!r}")
    if sorted(data) != sorted(SPEC_TOP_KEYS):
        raise lanes.Refusal("spec:keys", f"{path}: the keys are {list(SPEC_TOP_KEYS)}")
    lane_list = data["lanes"]
    if (
        not isinstance(lane_list, list)
        or not lane_list
        or not all(isinstance(lane, str) and lane for lane in lane_list)
        or len(set(lane_list)) != len(lane_list)
    ):
        raise lanes.Refusal("spec:lanes", f"{path}: a list of unique lane names")
    raw_sessions = data["sessions"]
    if not isinstance(raw_sessions, dict):
        raise lanes.Refusal("spec:sessions", f"{path}: a map of session id to session")
    sessions: dict[str, Session] = {}
    for sid, value in raw_sessions.items():
        _lane_of(sid)
        sessions[sid] = _spec_session(sid, value, lane_list)
    _check_graph(sessions)
    return [str(lane) for lane in lane_list], sessions


def _normalized(path: Path) -> str:
    """``path`` resolved and case-normalized, for a compare of two paths."""
    return os.path.normcase(str(Path(path).resolve()))


def _read_groupings(
    paths: Sequence[Path],
    *,
    check_graph: bool = True,
) -> tuple[list[str], dict[str, Session], list[tuple[Path, str, list[str]]]]:
    """The lanes and sessions of the grouping files, and each file's text and ids.

    Every key of a block is optional: a session with no ``size`` has ``size`` None,
    and ``simulate`` refuses it (``eligible`` does not). With ``check_graph`` False
    (the facts read) the ``after`` and cycle checks of ``_check_graph`` do not run.

    Raises:
        lanes.Refusal: ``grouping:read``, ``grouping:<lanes reason>`` for a
            Session Ownership block that ``lanes.parse_session_spec`` refuses,
            ``sid:<sid>``, ``duplicate:<sid>``, or (with ``check_graph``) a
            ``_check_graph`` reason.
    """
    lane_list: list[str] = []
    sessions: dict[str, Session] = {}
    files: list[tuple[Path, str, list[str]]] = []
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise lanes.Refusal("grouping:read", f"{path}: {exc}") from None
        try:
            specs = lanes.parse_session_spec(
                lanes._ownership_block(
                    text, Path(path), lanes.SESSION_OWNERSHIP_HEADING
                )
            )
        except lanes.Refusal as exc:
            raise lanes.Refusal(
                f"grouping:{exc.reason}", f"{path}: {exc.detail}"
            ) from None
        group = _normalized(Path(path))
        sids: list[str] = []
        for spec in specs:
            lane = _lane_of(spec.session)
            if spec.session in sessions:
                raise lanes.Refusal(
                    f"duplicate:{spec.session}", f"{path} and an earlier file name it"
                )
            if lane not in lane_list:
                lane_list.append(lane)
            sessions[spec.session] = Session(
                sid=spec.session,
                lane=lane,
                group=group,
                size=spec.size,
                tier=spec.tier,
                owns=spec.owns,
                after=spec.after,
                vm=spec.vm,
                e2e=spec.e2e,
                hold=spec.hold,
            )
            sids.append(spec.session)
        files.append((Path(path), text, sids))
    if check_graph:
        _check_graph(sessions)
    return lane_list, sessions, files


def load_groupings(paths: Sequence[Path]) -> tuple[list[str], dict[str, Session]]:
    """The lanes (in order of first use) and the sessions of the grouping files.

    Raises:
        lanes.Refusal: a ``_read_groupings`` reason.
    """
    lane_list, sessions, _files = _read_groupings(paths)
    return lane_list, sessions


def read_progress(text: str, source: Path) -> dict[str, str]:
    """Session id to the Status cell of the first table of the Session Progress section.

    Raises:
        lanes.Refusal: ``progress:section``, ``progress:table`` or ``progress:<sid>``
            for an id in two rows.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == PROGRESS_HEADING]
    if len(starts) != 1:
        raise lanes.Refusal(
            "progress:section", f"{source} needs one '{PROGRESS_HEADING}' section"
        )
    rows: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if line.startswith("## "):
            break
        if line.lstrip().startswith("|"):
            rows.append(line.strip())
        elif rows:
            break
    if len(rows) < 2 or not _SEPARATOR_RE.fullmatch(rows[1]):
        raise lanes.Refusal("progress:table", f"{source}: no Session Progress table")
    statuses: dict[str, str] = {}
    for row in rows[2:]:
        cells = [cell.strip() for cell in _CELL_SPLIT_RE.split(row)[1:-1]]
        if len(cells) < 2:
            raise lanes.Refusal("progress:table", f"{source}: a row has no Status cell")
        sid, status = cells[0], cells[1]
        if sid in statuses:
            raise lanes.Refusal(f"progress:{sid}", f"{source}: two rows name {sid}")
        statuses[sid] = status
    return statuses


def _progress(files: Sequence[tuple[Path, str, list[str]]]) -> dict[str, str]:
    """The Status cell of every session, each file's table checked against its block.

    Raises:
        lanes.Refusal: a ``read_progress`` reason, or ``progress:<sid>`` for a
            session in the block and not in the table, or the reverse.
    """
    statuses: dict[str, str] = {}
    for path, text, sids in files:
        table = read_progress(text, path)
        for sid in [*sids, *table]:
            if (sid in sids) != (sid in table):
                raise lanes.Refusal(
                    f"progress:{sid}",
                    f"{path}: the Session Progress table and the block differ",
                )
        statuses.update(table)
    return statuses


def _state(sid: str, status: str) -> str:
    """``candidate``, ``running``, ``finished``, ``blocked`` or ``split``.

    Raises:
        lanes.Refusal: ``status:<sid>:<status>`` for another status.
    """
    if status in CANDIDATE_STATUSES:
        return "candidate"
    if status == RUNNING_STATUS:
        return "running"
    match = _STATUS_WORD_RE.match(status)
    if match is None:
        raise lanes.Refusal(
            f"status:{sid}:{status}",
            "the statuses are pending, ▶ NEXT, in-progress, and a status that "
            "starts with done, skipped, blocked or split",
        )
    word = match.group(1)
    return "finished" if word in FINISHED_WORDS else word


# ---------------------------------------------------------------------------
# The lane cards
# ---------------------------------------------------------------------------


def _common_dir(repo: Path) -> Path:
    """The git common dir of ``repo``, found from the files only.

    Raises:
        lanes.Refusal: ``repo:no_git`` when ``repo`` has no ``.git``, or
            ``repo:git_file`` for a ``.git`` file that names no git dir.
    """
    dot_git = repo / ".git"
    if dot_git.is_dir():
        return dot_git
    if not dot_git.is_file():
        raise lanes.Refusal("repo:no_git", f"{repo} has no .git folder or file")
    try:
        first = dot_git.read_text(encoding="utf-8").strip()
        if not first.startswith(_GITDIR_PREFIX):
            raise lanes.Refusal(
                "repo:git_file", f"{dot_git} has no '{_GITDIR_PREFIX}' line"
            )
        gitdir = Path(first[len(_GITDIR_PREFIX) :].strip())
        if not gitdir.is_absolute():
            gitdir = repo / gitdir
        common = gitdir
        commondir = gitdir / "commondir"
        if commondir.is_file():
            relative = Path(commondir.read_text(encoding="utf-8").strip())
            common = relative if relative.is_absolute() else gitdir / relative
    except (OSError, UnicodeDecodeError) as exc:
        raise lanes.Refusal("repo:git_file", f"{dot_git}: {exc}") from None
    return common.resolve()


def _cards_dir(repo: Path) -> Path:
    """``lanes/`` of the git common dir of ``repo``, found from the files only.

    Raises:
        lanes.Refusal: each refusal of ``_common_dir``.
    """
    return lanes._lanes_dir(_common_dir(repo))


def _git_bool(value: str | None, config: Path) -> bool:
    """A git boolean as ``git config --bool`` reads it: None (no ``=``) is true.

    Raises:
        lanes.Refusal: ``repo:git_config`` for a value that is not a git boolean.
    """
    if value is None:
        return True
    text = value.strip().strip('"').strip().lower()
    if text in _GIT_TRUE:
        return True
    if text in _GIT_FALSE:
        return False
    try:
        return int(text) != 0
    except ValueError:
        raise lanes.Refusal(
            "repo:git_config", f"{config}: core.ignorecase is not a boolean: {value!r}"
        ) from None


def _ignorecase(repo: Path) -> bool:
    """``core.ignorecase`` of the config file of the git common dir of ``repo``.

    The last ``ignorecase`` key of a ``[core]`` section wins, as ``git config
    --get`` reads one file. False when ``repo`` has no ``.git`` or the common dir
    has no config file, as git reads an unset key. The tool starts no process
    (AC-925.7), so it does not run ``git config``; it does not follow ``include``
    sections and does not read the global or system files.

    Raises:
        lanes.Refusal: ``repo:git_file`` (``_common_dir``), or ``repo:git_config``
            for an unreadable file or a value that is not a git boolean.
    """
    if not (repo / ".git").exists():
        return False
    config = _common_dir(repo) / "config"
    if not config.is_file():
        return False
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise lanes.Refusal("repo:git_config", f"{config}: {exc}") from None
    in_core = False
    found = False
    value: str | None = None
    for line in text.splitlines():
        section = _SECTION_RE.match(line)
        if section is not None:
            in_core = section.group(1).strip().lower() == "core"
            line = section.group(2)
        if not in_core:
            continue
        key = _IGNORECASE_RE.fullmatch(_COMMENT_RE.split(line, maxsplit=1)[0])
        if key is not None:
            found = True
            value = key.group(1)
    return _git_bool(value, config) if found else False


def _front_value(raw: str) -> str | None:
    """The value of one frontmatter line: unquoted, with no comment; None for null.

    Raises:
        ValueError: a quoted value has no closing quote.
    """
    text = raw.strip()
    if text[:1] in ('"', "'"):
        end = text.find(text[0], 1)
        if end < 0:
            raise ValueError(f"no closing quote in {raw!r}")
        value = text[1:end]
    else:
        value = text.split(" #", 1)[0].strip()
    return None if value in _NULL_VALUES else value


def _grouping_keys(task_md: Path) -> tuple[str, str] | None:
    """``(grouping_source, grouping_session)`` of a task.md frontmatter.

    None when the file has no frontmatter or states neither key.

    Raises:
        ValueError: the frontmatter is not closed, or states one key only.
        OSError: the file cannot be read.
    """
    lines = task_md.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    values: dict[str, str | None] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = _FRONT_KEY_RE.fullmatch(line)
        if match is not None:
            values[match.group(1)] = _front_value(match.group(2))
    else:
        raise ValueError(f"{task_md}: the frontmatter is not closed")
    source = values.get("grouping_source")
    session = values.get("grouping_session")
    if source is None and session is None:
        return None
    if source is None or session is None:
        raise ValueError(f"{task_md}: states only one of the two grouping keys")
    return source, session


def read_cards(
    cards_dir: Path, repo: Path, groupings: Mapping[str, Sequence[str]]
) -> list[Reservation]:
    """The reserving cards of ``cards_dir``, each mapped to its session when it can be.

    The card's plan is ``<worktree>/<plan>/task.md``, else ``<repo>/<plan>/task.md``.
    Its ``grouping_source`` (relative to ``repo``) and ``grouping_session`` map the
    card to a session when the source is a key of ``groupings`` (normalized
    grouping path to its session ids).

    Raises:
        lanes.Refusal: ``card:<file name>`` for an unreadable card, a card with
            no task.md, a task.md with bad grouping keys, or a session that is not
            in its grouping.
    """
    out: list[Reservation] = []
    for path in lanes._card_files(cards_dir):
        try:
            card = lanes._load_card(path)
        except (lanes.Refusal, OSError) as exc:
            raise lanes.Refusal(f"card:{path.name}", f"{path}: {exc}") from None
        if card["state"] not in lanes.RESERVING_STATES:
            continue
        candidates = [
            Path(card["worktree"]) / card["plan"] / "task.md",
            repo / card["plan"] / "task.md",
        ]
        task_md = next((item for item in candidates if item.is_file()), None)
        if task_md is None:
            raise lanes.Refusal(
                f"card:{path.name}", f"{path}: no task.md for plan {card['plan']!r}"
            )
        try:
            keys = _grouping_keys(task_md)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise lanes.Refusal(f"card:{path.name}", f"{path}: {exc}") from None
        session: str | None = None
        if keys is not None:
            source, sid = keys
            target = _normalized(repo / source)
            if target in groupings:
                if sid not in groupings[target]:
                    raise lanes.Refusal(
                        f"card:{path.name}", f"{path}: {source} has no session {sid}"
                    )
                session = sid
        out.append(
            Reservation(
                lane=card["lane"],
                worktree=_normalized(Path(card["worktree"])),
                owns=tuple(card["owns"]),
                session=session,
            )
        )
    return out


# ---------------------------------------------------------------------------
# simulate
# ---------------------------------------------------------------------------


def _held(
    sessions: Mapping[str, Session], follow: Mapping[str, Sequence[str]]
) -> dict[str, list[str]]:
    """Each held session and each session that must follow one, with the reasons."""
    held = {sid for sid, session in sessions.items() if session.hold is not None}
    changed = True
    while changed:
        changed = False
        for sid in sessions:
            if sid not in held and any(member in held for member in follow[sid]):
                held.add(sid)
                changed = True
    out: dict[str, list[str]] = {}
    for sid, session in sessions.items():
        if sid not in held:
            continue
        reasons: list[str] = []
        if session.hold is not None:
            reasons.append(f"hold:{session.hold.kind}:{session.hold.reason}")
        reasons += [f"after:{member}" for member in follow[sid] if member in held]
        out[sid] = reasons
    return out


def _pick(
    queue: Sequence[str],
    sessions: Mapping[str, Session],
    follow: Mapping[str, Sequence[str]],
    clash: Mapping[str, set[str]],
    landed: set[str],
    busy: Sequence[str],
) -> str | None:
    """The first session of ``queue`` that can start next to ``busy``."""
    for sid in queue:
        if any(member not in landed for member in follow[sid]):
            continue
        if any(other in clash[sid] for other in busy):
            continue
        if sessions[sid].e2e and any(sessions[other].e2e for other in busy):
            continue
        return sid
    return None


def simulate(
    lane_list: Sequence[str],
    sessions: Mapping[str, Session],
    *,
    order: str = "critical-path",
    executors: int = 1,
    borrow: str | None = None,
    workers: int | None = None,
    trees: str = "lanes",
) -> dict[str, Any]:
    """The greedy schedule of the grouping guide, with the limits it does not model.

    Each lane has ``executors`` slots (``trees="lanes"``), or one queue in rank order
    has one slot (``trees="main"``). At each time a free slot takes the first
    session of its queue whose ``must_follow`` sessions have landed and that has no
    conflict with a running session. A free slot of the ``borrow`` lane that finds
    nothing takes from the other lanes, the lane with the most remaining weight
    first. One ``e2e`` session runs at a time, and ``workers`` sessions in all.

    Raises:
        lanes.Refusal: ``size:<sid>`` for the first session with no size (the
            schedule weights each session with it), ``borrow:<lane>`` for a lane
            that is not an input lane, or ``deadlock`` when no session can start
            and none runs.
    """
    for sid, session in sessions.items():
        if session.size is None:
            raise lanes.Refusal(
                f"size:{sid}", f"{session.group} states no size for {sid}"
            )
    if borrow is not None and borrow not in lane_list:
        raise lanes.Refusal(f"borrow:{borrow}", f"the lanes are {list(lane_list)}")
    follow_all = _follow_map(sessions)
    held = _held(sessions, follow_all)
    follow = {sid: members for sid, members in follow_all.items() if sid not in held}
    live = {sid: sessions[sid] for sid in follow}
    clash = {sid: set(conflicts(session, live)) for sid, session in live.items()}
    weight = {sid: _weight(session) for sid, session in live.items()}
    ranked = _rank(sessions, lane_list, follow, order)
    if trees == "main":
        queues = {_MAIN_QUEUE: ranked}
        slots = 1
    else:
        queues = {
            lane: [sid for sid in ranked if sessions[sid].lane == lane]
            for lane in lane_list
        }
        slots = executors
    running: dict[tuple[str, int], tuple[str, float, float]] = {}
    landed: set[str] = set()
    schedule: dict[str, list[dict[str, Any]]] = {lane: [] for lane in lane_list}
    now = 0.0
    while any(queues.values()) or running:
        for name in queues:
            for slot in range(slots):
                if (name, slot) in running:
                    continue
                if workers is not None and len(running) >= workers:
                    continue
                lending = trees == "lanes" and name == borrow
                if not queues[name] and not lending:
                    continue
                sources = [name]
                if lending:
                    remaining = {
                        lane: sum(weight[sid] for sid in queues[lane])
                        for lane in lane_list
                        if lane != name
                    }
                    sources += sorted(
                        remaining, key=remaining.__getitem__, reverse=True
                    )
                busy = [entry[0] for entry in running.values()]
                for source in sources:
                    sid = _pick(queues[source], sessions, follow, clash, landed, busy)
                    if sid is None:
                        continue
                    end = now + weight[sid]
                    running[(name, slot)] = (sid, now, end)
                    queues[source].remove(sid)
                    lane = sessions[sid].lane if trees == "main" else name
                    schedule[lane].append(
                        {"sid": sid, "start": now, "end": end, "slot": slot}
                    )
                    break
        if not running:
            raise lanes.Refusal(
                "deadlock", f"no session can start at t={now}: {dict(queues)}"
            )
        next_end = min(entry[2] for entry in running.values())
        for key in [key for key, entry in running.items() if entry[2] == next_end]:
            landed.add(running.pop(key)[0])
        now = next_end
    makespan = max(
        (entry["end"] for entries in schedule.values() for entry in entries),
        default=0.0,
    )
    return {
        "makespan": makespan,
        "order": order,
        "executors": executors,
        "trees": trees,
        "borrow": borrow,
        "workers": workers,
        "schedule": schedule,
        "held": held,
        "caps_not_modeled": list(CAPS_NOT_MODELED),
    }


# ---------------------------------------------------------------------------
# eligible
# ---------------------------------------------------------------------------


def _record(name: str, configured: int | None, observed: int) -> dict[str, Any]:
    """One resource record; ``free`` is None when the limit is not configured."""
    free = None if configured is None else max(0, configured - observed)
    return {
        "limit_name": name,
        "configured_value": configured,
        "observed_value": observed,
        "window": WINDOW,
        "free": free,
    }


def eligible(
    lane_list: Sequence[str],
    sessions: Mapping[str, Session],
    statuses: Mapping[str, str],
    reservations: Sequence[Reservation],
    *,
    repo: Path,
    trees: str = "main",
    workers: int | None = None,
    reviews_running: int = 0,
    plan_commits_running: int = 0,
    ignorecase: bool = False,
) -> dict[str, Any]:
    """The sessions that can start now, and the reasons of each one that cannot.

    The candidates go in critical-path order. A candidate with no reason is selected
    and then counts as running. ``tree_busy`` applies with ``trees="main"`` only: a
    session runs, or an unmapped reserving card has ``repo`` as its worktree. A
    ``conflict`` with a busy session or a reserving card is a ``live_overlap`` hit
    under ``ignorecase`` (the repository's ``core.ignorecase``); the ``after`` order
    keeps the guide rule (``must_follow``).

    Raises:
        lanes.Refusal: ``status:<sid>:<status>`` for a status outside the
            vocabulary (``_state``).
    """
    states = {sid: _state(sid, statuses[sid]) for sid in sessions}
    repo_key = _normalized(repo)
    card_owns: dict[str, list[str]] = {}
    loose: list[Reservation] = []
    for reservation in reservations:
        if reservation.session is None:
            loose.append(reservation)
        else:
            card_owns.setdefault(reservation.session, []).extend(reservation.owns)
    top_cards = [card for card in loose if card.worktree == repo_key]
    owns = {
        sid: tuple(dict.fromkeys((*session.owns, *card_owns.get(sid, ()))))
        for sid, session in sessions.items()
    }
    running = [sid for sid in sessions if states[sid] == "running" or sid in card_owns]
    finished = {
        sid for sid in sessions if states[sid] == "finished" and sid not in card_owns
    }
    follow_all = _follow_map(sessions)
    follow = {
        sid: members for sid, members in follow_all.items() if sid not in finished
    }
    busy = list(running)
    selected: list[str] = []
    excluded: dict[str, list[str]] = {}
    for sid in _rank(sessions, lane_list, follow, "critical-path"):
        state = states[sid]
        if sid in running or state == "finished":
            continue
        if state in STOPPED_WORDS:
            excluded[sid] = [f"status:{state}"]
            continue
        session = sessions[sid]
        reasons: list[str] = []
        if session.hold is not None:
            reasons.append(f"hold:{session.hold.kind}:{session.hold.reason}")
        reasons += [
            f"after:{member}" for member in follow[sid] if member not in finished
        ]
        if any(sessions[other].lane == session.lane for other in busy):
            reasons.append("lane_busy")
        if trees == "main" and (busy or top_cards):
            reasons.append("tree_busy")
        for other in busy:
            reasons += [
                f"conflict:{other}:{hit}"
                for hit in live_overlap(owns[sid], owns[other], ignorecase=ignorecase)
            ]
        if session.vm and any(sessions[other].vm for other in busy):
            reasons.append("vm_busy")
        for card in loose:
            reasons += [
                f"conflict:{card.lane}:{hit}"
                for hit in live_overlap(owns[sid], card.owns, ignorecase=ignorecase)
            ]
        if session.e2e and any(sessions[other].e2e for other in busy):
            reasons.append("e2e_busy")
        if workers is not None and len(busy) >= workers:
            reasons.append("cap:workers")
        if reasons:
            excluded[sid] = list(dict.fromkeys(reasons))
        else:
            selected.append(sid)
            busy.append(sid)
    if trees == "main":
        trees_record = _record("trees", 1, len(running) + len(top_cards))
    else:
        busy_lanes = {sessions[sid].lane for sid in running}
        trees_record = _record("trees", len(lane_list), len(busy_lanes))
    resources = {
        "reviews": _record("reviews", REVIEW_CAP, reviews_running),
        "plan_commits": _record("plan_commits", PLAN_COMMIT_CAP, plan_commits_running),
        "workers": _record("workers", workers, len(running)),
        "vm": _record("vm", VM_CAP, sum(1 for sid in running if sessions[sid].vm)),
        "e2e": _record("e2e", E2E_CAP, sum(1 for sid in running if sessions[sid].e2e)),
        "trees": trees_record,
    }
    return {
        "eligible": selected,
        "excluded": excluded,
        "running": running,
        "resources": resources,
        "can_dispatch_review": resources["reviews"]["free"] > 0,
        "can_plan_commit": resources["plan_commits"]["free"] > 0,
    }


# ---------------------------------------------------------------------------
# The pilot verbs (MEU-951)
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    """The current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(value: object) -> str:
    """``value`` as canonical JSON: sorted keys, compact separators, ASCII only."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _tools_dir() -> Path:
    """The folder of this file, which holds the tools that the verbs run."""
    return Path(__file__).resolve().parent


def _actions_path(repo: Path) -> Path:
    """The actions log of ``repo``: ``<git common dir>/<orch folder>/actions.jsonl``.

    Raises:
        lanes.Refusal: each refusal of ``_common_dir``.
    """
    return _common_dir(repo) / result_snapshot.ORCH_FOLDER / ACTIONS_NAME


def read_actions(repo: Path) -> list[dict[str, Any]]:
    """The lines of the actions log of ``repo`` (none when the log does not exist).

    Raises:
        lanes.Refusal: ``actions:read`` for an unreadable log or a line that is not a
            JSON object.
    """
    path = _actions_path(repo)
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise lanes.Refusal("actions:read", f"{path}: {exc}") from None
    out: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise lanes.Refusal(
                "actions:read", f"{path} line {number}: {exc}"
            ) from None
        if not isinstance(item, dict):
            raise lanes.Refusal(
                "actions:read", f"{path} line {number}: not a JSON object"
            )
        out.append(item)
    return out


def _append_action(repo: Path, record: Mapping[str, Any]) -> None:
    """Append ``record`` as one JSON line to the actions log of ``repo``.

    Raises:
        lanes.Refusal: ``actions:write`` when the log cannot be written.
    """
    path = _actions_path(repo)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(record) + "\n")
    except OSError as exc:
        raise lanes.Refusal("actions:write", f"{path}: {exc}") from None


# -- facts ------------------------------------------------------------------------------------


def _sessions_fact(
    repo: Path, grouping_args: Sequence[str]
) -> tuple[dict[str, Any], dict[str, Session]]:
    """The ``sessions`` fact of the grouping files, and the parsed sessions.

    A progress table that does not match its block, and an ``after`` id that no named
    file holds, is a ``facts_warn:<reason>:<file>`` entry of ``warnings``, not a
    refusal (plan O1: each named file is read alone).

    Raises:
        lanes.Refusal: a ``_read_groupings`` reason other than a ``_check_graph`` one.
    """
    paths = [repo / item for item in grouping_args]
    _lane_list, sessions, files = _read_groupings(paths, check_graph=False)
    warnings: list[str] = []
    statuses: dict[str, str] = {}
    for path, text, sids in files:
        if any(other not in sessions for sid in sids for other in sessions[sid].after):
            warnings.append(f"facts_warn:after:{path.name}")
        try:
            table = read_progress(text, path)
        except lanes.Refusal as exc:
            warnings.append(f"facts_warn:{exc.reason}:{path.name}")
            continue
        if sorted(table) != sorted(sids):
            warnings.append(f"facts_warn:progress:{path.name}")
        statuses.update(table)
    rows: list[dict[str, Any]] = []
    for (path, _text, sids), arg in zip(files, grouping_args, strict=True):
        for sid in sids:
            item = sessions[sid]
            rows.append(
                {
                    "grouping": arg,
                    "sid": sid,
                    "status": statuses.get(sid),
                    "size": item.size,
                    "tier": item.tier,
                    "owns": list(item.owns),
                    "after": list(item.after),
                    "vm": item.vm,
                    "e2e": item.e2e,
                    "held": item.hold is not None,
                }
            )
    fact = {"kind": "sessions", "sessions": rows, "warnings": sorted(warnings)}
    return fact, sessions


def _claims_fact(repo: Path) -> dict[str, Any]:
    """The ``claims`` fact: scratch clones, lane cards and sessions started by ``start``.

    Raises:
        lanes.Refusal: ``claims:clone`` or ``claims:card`` for an unreadable marker or
            card, or a refusal of ``read_actions`` or ``_common_dir``.
    """
    clones: list[dict[str, str]] = []
    root = ew.clone_root()
    if root.is_dir():
        for marker in sorted(root.glob(f"*/.git/{ew.CLONE_MARKER}")):
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise lanes.Refusal("claims:clone", f"{marker}: {exc}") from None
            if not isinstance(data, dict):
                raise lanes.Refusal("claims:clone", f"{marker}: not a JSON object")
            clones.append(
                {
                    "slug": str(data.get("slug", marker.parent.parent.name)),
                    "parent": str(data.get("parent", "")),
                }
            )
    cards: list[dict[str, Any]] = []
    for path in lanes._card_files(_cards_dir(repo)):
        try:
            card = lanes._load_card(path)
        except (lanes.Refusal, OSError) as exc:
            raise lanes.Refusal("claims:card", f"{path}: {exc}") from None
        cards.append(
            {
                "lane": str(card["lane"]),
                "state": str(card["state"]),
                "worktree": str(card["worktree"]),
                "plan": str(card["plan"]),
                "owns": [str(entry) for entry in card["owns"]],
            }
        )
    started = [
        {"key": item.get("key"), "sessions": list(item.get("sessions", []))}
        for item in read_actions(repo)
        if item.get("action") == "start"
    ]
    return {"kind": "claims", "clones": clones, "cards": cards, "started": started}


def _landed_runs(actions: Sequence[Mapping[str, Any]]) -> set[str]:
    """The runs that the actions log records as committed."""
    return {
        str(item.get("run"))
        for item in actions
        if item.get("action") == "land" and item.get("stage") == "commit"
    }


def _land_queue_fact(repo: Path) -> dict[str, Any]:
    """The ``land-queue`` fact: the ledger entries that are not landed yet.

    Raises:
        lanes.Refusal: a refusal of ``read_actions`` or ``_common_dir``.
        result_snapshot.SnapshotRefusal: ``ledger_bad`` or ``events_bad``.
    """
    common = _common_dir(repo)
    landed = _landed_runs(read_actions(repo))
    queue: list[dict[str, Any]] = []
    for entry in result_snapshot.ledger_entries(common):
        run = str(entry.get("run"))
        if run in landed:
            continue
        session = entry.get("session")
        reviews = result_snapshot.recorded_reviews(common, session) if session else {}
        queue.append(
            {
                "run": run,
                "session": session,
                "clone": entry.get("clone"),
                "base": entry.get("base"),
                "commit": entry.get("commit"),
                "tree": entry.get("tree"),
                "voids": result_snapshot.run_voids(common, run),
                "reviews": reviews,
            }
        )
    return {"kind": "land-queue", "queue": queue}


def compute_facts(
    repo: Path, grouping_args: Sequence[str]
) -> tuple[str, dict[str, dict[str, Any]], dict[str, Session]]:
    """The ``rev``, the three facts (without ``rev``) and the parsed sessions.

    ``rev`` is the SHA-256 of the canonical JSON of the three facts, so it is the same
    for each kind and it changes when any of them changes. A fact holds no timestamp.

    Raises:
        lanes.Refusal: a refusal of one fact.
        result_snapshot.SnapshotRefusal: a refusal of the land queue.
    """
    if grouping_args:
        sessions_fact, sessions = _sessions_fact(repo, grouping_args)
    else:
        sessions_fact, sessions = (
            {"kind": "sessions", "sessions": [], "warnings": []},
            {},
        )
    parts = {
        "sessions": sessions_fact,
        "claims": _claims_fact(repo),
        "land-queue": _land_queue_fact(repo),
    }
    rev = hashlib.sha256(_canonical(parts).encode("utf-8")).hexdigest()
    return rev, parts, sessions


def _run_facts(args: argparse.Namespace) -> int:
    """``facts <kind>``: print one JSON object; it changes nothing."""
    repo = Path(args.repo).resolve()
    rev, parts, _sessions = compute_facts(repo, args.grouping)
    print(json.dumps({**parts[args.kind], "rev": rev}, indent=1))
    return EXIT_OK


# -- the start checks -------------------------------------------------------------------------


def _pinned_paths(repo: Path) -> list[str]:
    """The pinned component paths: the keys of ``components`` in the policy file.

    Raises:
        lanes.Refusal: ``policy`` when the file is missing or has no ``components``.
    """
    path = repo / POLICY_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise lanes.Refusal("policy", f"{path}: {exc}") from None
    components = data.get("components") if isinstance(data, dict) else None
    if not isinstance(components, dict):
        raise lanes.Refusal("policy", f"{path}: no components object")
    return [str(key) for key in components]


def fit_reason(session: Session, pins: Sequence[str]) -> str | None:
    """Why ``session`` does not fit a pilot (PILOT_FIT), or None when it fits.

    The reasons are ``size``, ``vm``, ``e2e``, ``pinned:<entry>``,
    ``governance:<entry>`` and ``lock:<entry>``, checked in that order.
    """
    if session.size not in PILOT_SIZES:
        return "size"
    if session.vm:
        return "vm"
    if session.e2e:
        return "e2e"
    for entry in session.owns:
        if overlap([entry], pins):
            return f"pinned:{entry}"
        if overlap([entry], GOVERNANCE_PATHS):
            return f"governance:{entry}"
        if not entry.endswith("/") and entry.rsplit("/", 1)[-1] in LOCK_NAMES:
            return f"lock:{entry}"
    return None


def _front_status(task_md: Path) -> str | None:
    """The top-level ``status`` of the task.md frontmatter, or None when it has none."""
    return _front_status_text(task_md.read_text(encoding="utf-8"))


def _front_status_text(text: str) -> str | None:
    """The top-level ``status`` of task.md text's frontmatter, or None when it has none."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        match = _FRONT_STATUS_RE.fullmatch(line)
        if match is not None:
            return match.group(1)
    return None


def plan_of(repo: Path, grouping: str, sid: str, *, committed: bool = False) -> Path:
    """The approved ``task.md`` whose grouping keys are (``grouping``, ``sid``).

    A task.md that cannot be read, or that states no grouping keys, names no session
    and is skipped. With ``committed``, the status is read from the task.md at
    ``HEAD``: the sync of a land writes the worker's task.md (status ``complete``)
    into the main tree, and a refused land must stay retryable (AG3 EA-30).

    Raises:
        lanes.Refusal: ``no_plan:<sid>``, ``plan_ambiguous:<sid>`` or
            ``plan_not_approved:<sid>``.
    """
    target = _normalized(repo / grouping)
    plans = repo / PLANS_DIR
    hits: list[Path] = []
    if plans.is_dir():
        for task_md in sorted(plans.glob("*/task.md")):
            try:
                keys = _grouping_keys(task_md)
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            if (
                keys is not None
                and keys[1] == sid
                and _normalized(repo / keys[0]) == target
            ):
                hits.append(task_md)
    if not hits:
        raise lanes.Refusal(f"no_plan:{sid}", f"no task.md names {grouping} and {sid}")
    if len(hits) > 1:
        names = ", ".join(item.parent.name for item in hits)
        raise lanes.Refusal(f"plan_ambiguous:{sid}", names)
    try:
        if committed:
            rel = hits[0].resolve().relative_to(repo.resolve()).as_posix()
            status = _front_status_text(_git_lines(repo, "show", f"HEAD:{rel}"))
        else:
            status = _front_status(hits[0])
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise lanes.Refusal(f"no_plan:{sid}", f"{hits[0]}: {exc}") from None
    except lanes.Refusal as exc:
        raise lanes.Refusal(
            f"plan_not_approved:{sid}", f"{hits[0]} is not at HEAD: {exc}"
        ) from None
    if status != "approved":
        raise lanes.Refusal(
            f"plan_not_approved:{sid}", f"{hits[0]} has status {status!r}"
        )
    return hits[0]


def _cd_target(raw: str) -> str:
    """A ``cd`` target in one comparable form: lower case, ``/``, ``/d/x`` as ``d:/x``."""
    text = raw.replace("\\", "/").rstrip("/").lower()
    match = _MSYS_DRIVE_RE.fullmatch(text)
    if match is not None:
        text = match.group(1) + ":/" + match.group(2)
    return text


def runs_in_main_tree(repo: Path, task_md: Path) -> bool:
    """True when a task-table row of ``task_md`` runs ``cd`` into the main tree ``repo``.

    Only the table rows (the lines that start with ``|``) count, because the worker
    runs the rows (``PILOT_PREP``: a ``cd`` row command). A ``cd`` outside the table,
    such as a terminal step that the decision session runs after the land, does not.

    Raises:
        OSError: the file cannot be read.
    """
    main = repo.resolve().as_posix().lower()
    text = task_md.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        for match in _CD_RE.finditer(line):
            target = _cd_target(match.group(1))
            if target == main or target.startswith(main + "/"):
                return True
    return False


def _git_lines(repo: Path, *args: str) -> str:
    """The stdout of ``git <args>`` in ``repo``, through the process seam.

    Raises:
        lanes.Refusal: ``git:<first argument>`` when git exits non-zero.
    """
    code, out = _invoke(["git", *args], cwd=repo, wait=True)
    if code != 0:
        raise lanes.Refusal(f"git:{args[0]}", f"git {' '.join(args)} exited {code}")
    return out


def plan_committed(repo: Path, task_md: Path) -> bool:
    """True when the plan folder and its plan-critical-review file are tracked and clean.

    Raises:
        lanes.Refusal: a git call fails.
    """
    folder = task_md.parent
    rels = [
        folder.relative_to(repo).as_posix(),
        f"{HANDOFFS_DIR}/{folder.name}{REVIEW_SUFFIX}",
    ]
    for rel in rels:
        status = _git_lines(
            repo, "status", "--porcelain", "--untracked-files=all", "--", rel
        )
        if status.strip():
            return False
        if not _git_lines(repo, "ls-files", "--", rel).strip():
            return False
    return True


def message_form_ok(text: str, sessions: Sequence[str]) -> bool:
    """True when ``text`` is exactly the start sentence for ``sessions`` (either order)."""
    match = START_SENTENCE_RE.fullmatch(text.strip())
    if match is None:
        return False
    return {match.group(1), match.group(2)} == set(sessions)


def _names(text: str, sid: str) -> bool:
    """True when ``text`` holds ``sid`` as a whole word."""
    return (
        re.search(r"(?<![A-Za-z0-9_])" + re.escape(sid) + r"(?![A-Za-z0-9_])", text)
        is not None
    )


def _brief_text(
    sid: str, grouping: str, plan_dir: str, clone: str, parent: str, slug: str
) -> str:
    """The worker brief of one pilot session."""
    return "\n".join(
        [
            f"# Pilot B worker brief: {sid}",
            "",
            f"You run session {sid} of {grouping} in the scratch clone {clone}.",
            f"The clone is at main commit {parent}. Work in the clone only.",
            "",
            f"Plan: {plan_dir} (read its implementation-plan.md and task.md first).",
            "Run the rows of task.md in order, test first, with the receipts form "
            "of AGENTS.md. Edit only the paths that the plan owns.",
            "",
            "Leave your changes uncommitted: do not commit, stash, reset, clean, "
            "push or merge. The coordinator snapshots the clone and lands the "
            "result on the replay route.",
            "",
            "This is a headless run: ending a turn ends the run. Run subagents "
            "and long commands in the foreground. Never end a turn to wait for "
            "a background task or subagent.",
            "",
            "If the plan asks you for an integration request, the id has the form "
            f"`{slug}/<B[:16]>/<n>`: B is the clone parent commit {parent}, B[:16] is "
            "its first 16 hex digits, and n counts up from 1.",
            "",
        ]
    )


def _clone_one(repo: Path, slug: str, sid: str) -> tuple[str, str]:
    """Make the scratch clone ``slug``; its path and its parent commit.

    Raises:
        lanes.Refusal: ``clone:<sid>`` when the clone call fails or prints no
            ``clone_ready`` line.
    """
    argv = [
        sys.executable,
        str(_tools_dir() / "executor_worktree.py"),
        "--root",
        str(repo),
        "clone",
        slug,
    ]
    code, out = _invoke(argv, cwd=repo, wait=True)
    last = [line.strip() for line in out.splitlines() if line.strip()]
    match = _CLONE_READY_RE.fullmatch(last[-1]) if last else None
    if code != 0 or match is None:
        raise lanes.Refusal(f"clone:{sid}", f"clone {slug} exited {code}")
    return match.group(1), match.group(2)


def _launch_one(clone: str, brief: Path, dispatch_id: str, sid: str) -> None:
    """Start the detached worker of one session.

    Raises:
        lanes.Refusal: ``launch:<sid>`` when the launch call fails.
    """
    argv = [
        shutil.which("pwsh") or "pwsh",
        "-NoProfile",
        "-File",
        str(_tools_dir() / "Invoke-ClaudeDispatch.ps1"),
        "-ModelClass",
        "coordinator",
        "-Kind",
        "exec",
        "-PermissionMode",
        "acceptEdits",
        "-WorkingDirectory",
        clone,
        "-PromptFile",
        str(brief),
        "-DispatchId",
        dispatch_id,
        "-TimeoutSec",
        str(WORKER_TIMEOUT_SEC),
    ]
    code, _out = _invoke(argv, cwd=Path(clone), wait=False)
    if code != 0:
        raise lanes.Refusal(f"launch:{sid}", f"launch {dispatch_id} exited {code}")


def _run_start(args: argparse.Namespace) -> int:
    """``start``: the O2 checks, then one clone and one launch per session.

    A key whose latest start line is complete prints ``start_repeat`` and changes
    nothing. A key whose latest start line is incomplete resumes: it runs the checks
    again for the sessions that the line does not show as started, then clones and
    launches only those sessions (EA-37, review R1-F4). A session that the line shows
    as started may have landed since, so its plan, fit and active checks do not run
    again (EA-39, review R2-F1).
    """
    repo = Path(args.repo).resolve()
    actions = read_actions(repo)
    prior = _key_start(actions, args.key)
    if prior is not None and _start_complete(prior):
        print(f"start_repeat {args.key}")
        return EXIT_OK
    ids = [item.strip() for item in args.sessions.split(",")]
    if len(ids) != 2 or not all(ids) or ids[0] == ids[1]:
        raise lanes.Refusal(
            "sessions", f"need two different session ids: {args.sessions}"
        )
    if prior is not None:
        _check_resume(prior, args, ids)
    done = _started_sessions(prior) if prior is not None else []
    pending = [sid for sid in ids if sid not in done]
    rev, _parts, sessions = compute_facts(repo, [args.grouping])
    if rev != args.rev:
        raise lanes.Refusal("stale_rev", f"the facts rev is {rev}")
    for sid in pending:
        if sid not in sessions:
            raise lanes.Refusal(
                f"session:{sid}", f"{args.grouping} has no session {sid}"
            )
    if all(sid in sessions for sid in ids):
        first, second = (sessions[sid] for sid in ids)
        shared = overlap(first.owns, second.owns)
        if shared:
            raise lanes.Refusal(
                f"overlap:{ids[0]}:{ids[1]}:{shared[0]}", "owns overlap"
            )
    pins = _pinned_paths(repo)
    for sid in pending:
        reason = fit_reason(sessions[sid], pins)
        if reason is not None:
            raise lanes.Refusal(f"fit:{sid}:{reason}", "not a pilot session")
    plans: dict[str, Path] = {}
    for sid in pending:
        plans[sid] = plan_of(repo, args.grouping, sid)
        try:
            main_tree = runs_in_main_tree(repo, plans[sid])
        except (OSError, UnicodeDecodeError) as exc:
            raise lanes.Refusal(f"no_plan:{sid}", f"{plans[sid]}: {exc}") from None
        if main_tree:
            raise lanes.Refusal(f"main_tree_plan:{sid}", f"{plans[sid]} runs in main")
    for sid in pending:
        if not plan_committed(repo, plans[sid]):
            raise lanes.Refusal(f"plan_not_committed:{sid}", str(plans[sid].parent))
    try:
        _raw, text = rp._human_record(
            rp._open_repo(repo), args.session, args.message_uuid
        )
    except rp.Refusal as exc:
        raise lanes.Refusal(f"record:{exc.reason}", exc.detail) from None
    for sid in ids:
        if not _names(text, sid):
            raise lanes.Refusal(f"not_named:{sid}", "the message does not name it")
    if not message_form_ok(text, ids):
        raise lanes.Refusal("message_form", "not the start sentence")
    slugs = [f"{sid.lower()}-{args.key}" for sid in ids]
    for sid, slug in zip(ids, slugs, strict=True):
        if ew.WORKTREE_SLUG_RE.fullmatch(slug) is None or not _DISPATCH_ID_RE.fullmatch(
            slug
        ):
            raise lanes.Refusal(f"slug:{sid}", f"{slug} is not a clone name")
    _check_one_operation(actions, args, pending)
    if args.dry_run:
        print("start_dry_ok " + ",".join(ids))
        return EXIT_OK
    clones: list[str] = (
        [str(clone) for clone in prior.get("clones", [])] if prior is not None else []
    )
    started: list[str] = [sid for sid in ids if sid in done]
    launched: list[tuple[str, str, str]] = []
    try:
        for at, (sid, slug) in enumerate(zip(ids, slugs, strict=True)):
            if sid in started:
                continue
            if at < len(clones):
                clone = clones[at]
                parent = _clone_parent(clone, slug, sid)
            else:
                clone, parent = _clone_one(repo, slug, sid)
                clones.append(clone)
            brief = DISPATCH_ROOT / args.key / f"{slug}-brief.md"
            try:
                brief.parent.mkdir(parents=True, exist_ok=True)
                body = _brief_text(
                    sid,
                    args.grouping,
                    plans[sid].parent.relative_to(repo).as_posix() + "/",
                    clone,
                    parent,
                    plans[sid].parent.name,
                )
                brief.write_bytes(body.encode("utf-8"))
            except OSError as exc:
                raise lanes.Refusal(f"brief:{sid}", f"{brief}: {exc}") from None
            _launch_one(clone, brief, slug, sid)
            started.append(sid)
            launched.append((sid, clone, slug))
    except (lanes.Refusal, result_snapshot.SnapshotRefusal):
        if clones:
            _append_action(
                repo, _start_record(args, ids, rev, text, clones, slugs, started)
            )
        raise
    _append_action(repo, _start_record(args, ids, rev, text, clones, slugs, started))
    for sid, clone, slug in launched:
        print(f"start_ok {sid} clone={clone} dispatch={slug}")
    return EXIT_OK


def _key_start(
    actions: Sequence[Mapping[str, Any]], key: str
) -> Mapping[str, Any] | None:
    """The latest start line of ``key``, or None when the log has none."""
    for item in reversed(actions):
        if item.get("action") == "start" and item.get("key") == key:
            return item
    return None


def _start_complete(item: Mapping[str, Any]) -> bool:
    """True when a start line shows every one of its sessions as started.

    A line that holds ``complete`` uses it. An older line without it is complete
    when its ``started`` list holds every session or, without ``started`` too, when
    it has a clone and a dispatch id for every session.
    """
    if "complete" in item:
        return item.get("complete") is True
    sessions = [str(sid) for sid in item.get("sessions", [])]
    started = item.get("started")
    if isinstance(started, list):
        return all(sid in started for sid in sessions)
    return len(item.get("clones", [])) >= len(sessions) and len(
        item.get("dispatch_ids", [])
    ) >= len(sessions)


def _check_resume(
    prior: Mapping[str, Any], args: argparse.Namespace, ids: Sequence[str]
) -> None:
    """An incomplete start resumes only with the same sessions and the same record.

    Raises:
        lanes.Refusal: ``repeat_mismatch`` when ``--sessions``, ``--session`` or
            ``--message-uuid`` differs from the start line of the key.
    """
    message = prior.get("message")
    recorded = message if isinstance(message, Mapping) else {}
    if (
        [str(sid) for sid in prior.get("sessions", [])] != list(ids)
        or recorded.get("session") != args.session
        or recorded.get("uid") != args.message_uuid
    ):
        raise lanes.Refusal(
            "repeat_mismatch",
            f"key {args.key} has an incomplete start with other sessions or another record",
        )


def _started_sessions(item: Mapping[str, Any]) -> list[str]:
    """The sessions that a start line launched.

    A line with a ``started`` list names them. An older line without it launched
    every session it names (EA-39, review R2-F1).
    """
    started = item.get("started")
    if isinstance(started, list):
        return [str(sid) for sid in started]
    return [str(sid) for sid in item.get("sessions", [])]


def _active_start(
    actions: Sequence[Mapping[str, Any]], sid: str, own_key: str
) -> str | None:
    """The key of a start that launched ``sid`` under another key, not ended by a land.

    Only a session that the start launched is active; a session whose clone or
    launch failed is not (EA-39, review R2-F1). A resume line repeats the sessions
    that earlier lines of its key launched, so a line counts only the sessions it
    newly launched; a session that landed before the resume stays inactive
    (EA-40, review R3-F2).
    """
    active: str | None = None
    seen: dict[str, set[str]] = {}
    for item in actions:
        if item.get("action") == "start":
            key = str(item.get("key"))
            started = _started_sessions(item)
            launched = sid in started and sid not in seen.get(key, set())
            seen.setdefault(key, set()).update(started)
            if key != own_key and launched:
                active = key
        elif (
            item.get("action") == "land"
            and item.get("stage") == "commit"
            and item.get("session") == sid
        ):
            active = None
    return active


def _check_one_operation(
    actions: Sequence[Mapping[str, Any]], args: argparse.Namespace, ids: Sequence[str]
) -> None:
    """One typed record starts one operation; a session runs in one start at a time.

    The start lines of ``--key`` itself are left out, so an incomplete start can
    resume on its own key (EA-37, review R1-F2).

    Raises:
        lanes.Refusal: ``record_used:<key>`` when a start line of another key holds
            the record; ``active:<sid>:<key>`` when a start of another key names
            ``sid`` and no later land commit of ``sid`` follows it.
    """
    for item in actions:
        if item.get("action") != "start" or item.get("key") == args.key:
            continue
        message = item.get("message")
        if isinstance(message, Mapping) and message.get("uid") == args.message_uuid:
            raise lanes.Refusal(
                f"record_used:{item.get('key')}",
                "a recorded start used this typed record; type a new start sentence",
            )
    for sid in ids:
        key = _active_start(actions, sid, args.key)
        if key is not None:
            raise lanes.Refusal(
                f"active:{sid}:{key}",
                f"start {key} runs {sid} and has no land commit of it",
            )


def _clone_parent(clone: str, slug: str, sid: str) -> str:
    """The parent commit of the existing clone of ``sid``, from its clone marker.

    Raises:
        lanes.Refusal: ``resume_clone:<sid>`` when ``clone`` is not the scratch
            clone ``slug``.
    """
    marker = ew._clone_marker(Path(clone))
    if marker is None or marker.get("slug") != slug:
        raise lanes.Refusal(f"resume_clone:{sid}", f"{clone} is not the clone {slug}")
    return marker["parent"]


def _start_record(
    args: argparse.Namespace,
    ids: Sequence[str],
    rev: str,
    text: str,
    clones: Sequence[str],
    slugs: Sequence[str],
    started: Sequence[str],
) -> dict[str, Any]:
    """The actions-log line of a start: the sessions that were started so far.

    ``complete`` is true only when every session is started; a repeat of the key
    resumes an incomplete line (EA-37). The line holds no grant: the user's own
    typed record is the only authority, and only its location and digest are kept
    here (AC-951.8).
    """
    in_order = [sid for sid in ids if sid in started]
    return {
        "key": args.key,
        "rev": rev,
        "action": "start",
        "sessions": list(ids),
        "message": {
            "session": args.session,
            "uid": args.message_uuid,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
        "clones": list(clones),
        "dispatch_ids": list(slugs[: len(clones)]),
        "started": in_order,
        "complete": len(in_order) == len(ids),
        "at": _utc_now(),
    }


# -- land -------------------------------------------------------------------------------------


def _json_result(out: str) -> dict[str, Any]:
    """The JSON object that a tool printed: the whole text, else its last ``{`` line."""
    text = out.strip()
    candidates = [
        text,
        *reversed([line for line in text.splitlines() if line.startswith("{")]),
    ]
    for item in candidates:
        try:
            data = json.loads(item)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _bad_reason(out: str) -> str | None:
    """The reason of the first ``<verb>_bad:<reason>`` line of ``out``."""
    for line in out.splitlines():
        if "_bad:" in line:
            return (
                line.split("_bad:", 1)[1].strip().split()[0]
                if line.split("_bad:", 1)[1].strip()
                else None
            )
    return None


def _step(argv: Sequence[str], step: str, repo: Path) -> str:
    """Run one land step through the seam; its stdout.

    Raises:
        lanes.Refusal: ``<step>:<reason>`` when the step exits non-zero.
    """
    code, out = _invoke(argv, cwd=repo, wait=True)
    if code != 0:
        reason = _bad_reason(out) or f"exit{code}"
        raise lanes.Refusal(f"{step}:{reason}", out.strip()[-400:])
    return out


def _started_clone(actions: Sequence[Mapping[str, Any]], sid: str) -> tuple[str, str]:
    """The clone path and the dispatch id of ``sid`` from its start line.

    Raises:
        lanes.Refusal: ``not_started:<sid>`` when the log has no start line for it.
    """
    for item in reversed(actions):
        if item.get("action") != "start":
            continue
        listed = item.get("sessions", [])
        if sid in listed:
            at = list(listed).index(sid)
            clones = item.get("clones", [])
            ids = item.get("dispatch_ids", [])
            if at < len(clones) and at < len(ids):
                return str(clones[at]), str(ids[at])
    raise lanes.Refusal(
        f"not_started:{sid}", "the actions log has no start line for it"
    )


def _scope_items(out: str) -> tuple[int, list[str]]:
    """The count of scope items in ``scope`` output, and its ``void`` lines."""
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    voids = [line for line in lines if line.startswith("void ")]
    items = [
        line
        for line in lines
        if line != result_snapshot.NO_SCOPE and not line.startswith("void ")
    ]
    return len(items), voids


def _land_prepare(
    args: argparse.Namespace,
    repo: Path,
    run: str,
    clone: str,
    dispatch_id: str,
    task_md: Path,
) -> int:
    """``land --stage prepare``: snapshot, fetch, replay check, gate candidate, scope."""
    tools = _tools_dir()
    python = sys.executable
    snap = str(tools / "result_snapshot.py")
    common = _common_dir(repo)
    _step([python, snap, "take", "--clone", clone, "--run", run], "take", repo)
    fetch = [
        python,
        snap,
        "fetch",
        "--clone",
        clone,
        "--run",
        run,
        "--session",
        args.session,
    ]
    status = DISPATCH_ROOT / DISPATCH_FOLDER / dispatch_id / STATUS_NAME
    if status.is_file():
        fetch += ["--status", str(status)]
    _step(fetch, "fetch", repo)
    replay_out = _step(
        [
            python,
            str(tools / "lanes.py"),
            "land",
            "replay",
            "--snapshot",
            f"{lanes.RESULT_REF_PREFIX}{run}",
            "--task",
            str(task_md),
            "--check-only",
        ],
        "replay",
        repo,
    )
    found = re.search(r"batch=(\S+)", replay_out)
    batch = (
        found.group(1)
        if found
        else str(common / result_snapshot.LEDGER_FOLDER / run / "replay-batch.json")
    )
    cand_out = _step(
        [
            python,
            str(tools / "executor_worktree.py"),
            "--root",
            str(repo),
            "gate-candidate",
            Path(clone).name,
            "--packet",
            batch,
        ],
        "candidate",
        repo,
    )
    candidate = ""
    for line in cand_out.splitlines():
        match = _CANDIDATE_READY_RE.fullmatch(line.strip())
        if match is not None:
            candidate = match.group(1)
    if not candidate:
        raise lanes.Refusal(
            "candidate:none", "gate-candidate printed no candidate path"
        )
    scope_out = _step([python, snap, "scope", "--run", run], "scope", repo)
    count, _voids = _scope_items(scope_out)
    scope = str(count) if count else "none"
    _append_action(
        repo,
        {
            "key": args.key,
            "rev": args.rev,
            "action": "land",
            "stage": "prepare",
            "session": args.session,
            "run": run,
            "candidate": candidate,
            "batch": batch,
            "scope": scope,
            "at": _utc_now(),
        },
    )
    print(
        f"land_prepared {args.session} run={run} candidate={candidate} batch={batch} scope={scope}"
    )
    return EXIT_OK


def _land_commit(args: argparse.Namespace, repo: Path, run: str, task_md: Path) -> int:
    """``land --stage commit``: gate check, review check, sync, then one commit route."""
    if not args.gate_run:
        raise lanes.Refusal(
            "gate:missing", "--gate-run is required for the commit stage"
        )
    tools = _tools_dir()
    python = sys.executable
    snap = str(tools / "result_snapshot.py")
    common = _common_dir(repo)
    batch = str(common / result_snapshot.LEDGER_FOLDER / run / "replay-batch.json")
    for item in reversed(read_actions(repo)):
        if (
            item.get("action") == "land"
            and item.get("stage") == "prepare"
            and item.get("run") == run
        ):
            batch = str(item.get("batch", batch))
            break
    commit_batch = str(tools / "commit_batch.py")
    code, out = _invoke(
        [
            python,
            commit_batch,
            "--repo",
            str(repo),
            "--check-gated",
            args.gate_run,
            "--packet",
            batch,
        ],
        cwd=repo,
        wait=True,
    )
    checked = _json_result(out)
    if code != 0 or checked.get("result") != "gated_ok":
        raise lanes.Refusal(
            f"gate:{checked.get('reason') or f'exit{code}'}", out.strip()[-400:]
        )
    scope_out = _step(
        [python, snap, "scope", "--run", run, "--gate-run", args.gate_run],
        "scope",
        repo,
    )
    count, voids = _scope_items(scope_out)
    if voids:
        raise lanes.Refusal("void", "; ".join(voids))
    reviews = result_snapshot.recorded_reviews(common, args.session)
    if "worker" not in reviews:
        raise lanes.Refusal("worker_review", "no recorded worker review")
    if count and "integration" not in reviews:
        raise lanes.Refusal("integration_review", "no recorded integration review")
    _step(
        [
            python,
            str(tools / "lanes.py"),
            "land",
            "replay",
            "--snapshot",
            f"{lanes.RESULT_REF_PREFIX}{run}",
            "--task",
            str(task_md),
            "--sync",
            batch,
        ],
        "sync",
        repo,
    )
    argv = [python, commit_batch, "--repo", str(repo)]
    if args.session_id:
        argv += ["--human-directed", "--gated", args.gate_run, "--packet", batch]
        argv += ["--session", args.session_id, "--message-uuid", args.message_uuid]
    else:
        argv += [
            "--phase",
            "exec",
            "--op",
            run,
            "--gated",
            args.gate_run,
            "--packet",
            batch,
        ]
    code, out = _invoke(argv, cwd=repo, wait=True)
    done = _json_result(out)
    if code != 0 or done.get("result") != "reconciled":
        raise lanes.Refusal(
            f"commit:{done.get('reason') or f'exit{code}'}", out.strip()[-400:]
        )
    sha = str(done.get("commit", "none"))
    _append_action(
        repo,
        {
            "key": args.key,
            "rev": args.rev,
            "action": "land",
            "stage": "commit",
            "session": args.session,
            "run": run,
            "commit": sha,
            "gate_run": args.gate_run,
            "at": _utc_now(),
        },
    )
    print(f"land_done {args.session} commit={sha}")
    return EXIT_OK


def _run_land(args: argparse.Namespace) -> int:
    """``land``: the repeat check, the rev check, then the prepare or commit stage."""
    repo = Path(args.repo).resolve()
    actions = read_actions(repo)
    if any(
        item.get("action") == "land"
        and item.get("key") == args.key
        and item.get("stage") == args.stage
        for item in actions
    ):
        print(f"land_repeat {args.key}")
        return EXIT_OK
    rev, _parts, _sessions = compute_facts(repo, args.grouping or [])
    if rev != args.rev:
        raise lanes.Refusal("stale_rev", f"the facts rev is {rev}")
    if not args.grouping:
        raise lanes.Refusal("grouping", "--grouping is required")
    if (args.session_id is None) != (args.message_uuid is None):
        raise lanes.Refusal(
            "message_flags", "give both --session-id and --message-uuid, or neither"
        )
    clone, dispatch_id = _started_clone(actions, args.session)
    run = f"{args.session.lower()}-{args.key}"
    if result_snapshot.RUN_RE.fullmatch(run) is None:
        raise lanes.Refusal("run_name", f"{run} is not a run name")
    task_md = plan_of(repo, args.grouping[0], args.session, committed=True)
    if args.stage == "prepare":
        return _land_prepare(args, repo, run, clone, dispatch_id, task_md)
    return _land_commit(args, repo, run, task_md)


# -- report -----------------------------------------------------------------------------------


def _parse_time(value: object) -> datetime | None:
    """An ISO 8601 UTC time (``Z`` or an offset), or None when it is not one."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _wait(start: datetime | None, end: datetime | None) -> str:
    """The seconds between two times, or ``n/a`` when one is unknown."""
    if start is None or end is None:
        return "n/a"
    return f"{max(0, int((end - start).total_seconds()))}s"


def _read_pilots(path: Path) -> dict[str, Any]:
    """The pilots file, checked against ``ag3-pilots/1``.

    Raises:
        lanes.Refusal: ``pilots`` for an unreadable file or a wrong shape.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise lanes.Refusal("pilots", f"{path}: {exc}") from None
    message = data.get("message") if isinstance(data, dict) else None
    listed = data.get("pilots") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("schema") != PILOT_SCHEMA
        or not isinstance(message, dict)
        or not isinstance(message.get("session"), str)
        or not isinstance(message.get("uid"), str)
        or not isinstance(listed, list)
        or not listed
        or not all(
            isinstance(p, dict) and isinstance(p.get("session"), str) for p in listed
        )
    ):
        raise lanes.Refusal("pilots", f"{path}: not an {PILOT_SCHEMA} file")
    return data


def _read_object(path: Path) -> dict[str, Any] | None:
    """The JSON object in ``path``, or None when the file is absent or not an object."""
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _same_folder(path: str) -> str:
    """A folder path in one comparable form (case, separators and dots)."""
    return os.path.normcase(os.path.normpath(path))


def _review_queue(actions: Sequence[Mapping[str, Any]], sid: str) -> str:
    """Each review round of the session, as ``worker <times>; integration <times>``.

    A review dispatch writes ``status.json`` with its ``kind``, ``working_directory``,
    ``start_utc`` and ``end_utc`` under ``DISPATCH_ROOT``. A review whose folder is the
    session's clone (from the start action) is a worker review; one whose folder is a
    candidate that a land prepare of the session names is an integration review. Every
    round counts, the rejected ones too, because the dispatch records each one and the
    ledger records only the accepted verdict. A dispatch whose kind does not end in
    ``review`` (the worker itself) is not a review. Each time is dispatch to verdict
    (``start_utc`` to ``end_utc``), in start order (AC-951.7, EA-34). ``n/a`` when the
    session has no review round.
    """
    folders: dict[str, str] = {}
    for item in actions:
        if item.get("action") == "start" and sid in item.get("sessions", []):
            clones = item.get("clones", [])
            at = list(item["sessions"]).index(sid)
            if isinstance(clones, list) and at < len(clones) and clones[at]:
                folders[_same_folder(str(clones[at]))] = "worker"
        elif (
            item.get("action") == "land"
            and item.get("session") == sid
            and item.get("stage") == "prepare"
            and item.get("candidate")
        ):
            folders[_same_folder(str(item["candidate"]))] = "integration"
    if not folders:
        return "n/a"
    root = DISPATCH_ROOT / DISPATCH_FOLDER
    try:
        listed = list(root.iterdir()) if root.is_dir() else []
    except OSError:
        listed = []
    rounds: dict[str, list[tuple[datetime, str]]] = {"worker": [], "integration": []}
    for folder in listed:
        status = _read_object(folder / STATUS_NAME)
        if status is None or not str(status.get("kind", "")).endswith("review"):
            continue
        cwd = status.get("working_directory")
        kind = folders.get(_same_folder(cwd)) if isinstance(cwd, str) and cwd else None
        start = _parse_time(status.get("start_utc"))
        if kind is None or start is None:
            continue
        rounds[kind].append((start, _wait(start, _parse_time(status.get("end_utc")))))
    cells = [
        f"{kind} " + ", ".join(wait for _start, wait in sorted(found))
        for kind, found in rounds.items()
        if found
    ]
    return "; ".join(cells) or "n/a"


def _first_gate(actions: Sequence[Mapping[str, Any]], sid: str) -> str:
    """The result of the first gate run on a candidate that the session prepared.

    A ``land --stage prepare`` action names its replay batch; the gate run of that
    candidate records the batch's sha256 as ``candidate.batch_sha256``. The first run
    is the earliest such record by ``started_utc`` (AC-951.7, ``PILOT_RED``), read
    under ``GATE_RUNS_ROOT`` and the folder of each gate run a land commit of the
    session names. Gate folders named for a time more than ``GATE_NAME_SLACK`` before
    the first prepare are not read. ``n/a`` when no such record exists.
    """
    digests: set[str] = set()
    roots: dict[str, Path] = {str(GATE_RUNS_ROOT): GATE_RUNS_ROOT}
    earliest: datetime | None = None
    for item in actions:
        if item.get("action") != "land" or item.get("session") != sid:
            continue
        if item.get("stage") == "commit" and item.get("gate_run"):
            parent = Path(str(item["gate_run"])).parent
            roots.setdefault(str(parent), parent)
        if item.get("stage") != "prepare":
            continue
        at = _parse_time(item.get("at"))
        if at is not None and (earliest is None or at < earliest):
            earliest = at
        try:
            batch = Path(str(item.get("batch"))).read_bytes()
        except OSError:
            continue
        digests.add(hashlib.sha256(batch).hexdigest())
    if not digests:
        return "n/a"
    folders: dict[str, Path] = {}
    for root in roots.values():
        try:
            listed = list(root.iterdir()) if root.is_dir() else []
        except OSError:
            listed = []
        for folder in listed:
            folders.setdefault(str(folder.resolve()), folder)
    first: tuple[datetime, str, dict[str, Any]] | None = None
    for folder in folders.values():
        try:
            named = datetime.strptime(folder.name[:16], "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            named = None
        if (
            named is not None
            and earliest is not None
            and named < earliest - GATE_NAME_SLACK
        ):
            continue
        record = _read_object(folder / GATE_RECORD_NAME)
        candidate = record.get("candidate") if record is not None else None
        if (
            record is None
            or not isinstance(candidate, dict)
            or candidate.get("batch_sha256") not in digests
        ):
            continue
        started = _parse_time(record.get("started_utc"))
        if started is None:
            continue
        if first is None or (started, folder.name) < (first[0], first[1]):
            first = (started, folder.name, record)
    if first is None:
        return "n/a"
    summary = first[2].get("summary")
    summary = summary if isinstance(summary, dict) else {}
    passed, failed = summary.get("passed"), summary.get("blocking_failed")
    if passed is True:
        result = "pass"
    elif passed is False:
        count = failed if isinstance(failed, int) else "?"
        result = f"fail ({count} blocking failed)"
    else:
        result = "unknown"
    return f"{result}: {first[1]}"


def _ready_to_land(slug: str, landed: datetime) -> datetime | None:
    """The end of the latest successful worker attempt of ``slug`` before the land.

    The attempts are the dispatch folder ``slug`` and its continuations
    ``slug-rN``. Only a worker (``exec``) attempt with exit code 0 that ended no
    later than ``landed`` counts; a failed attempt is never readiness. None when
    no attempt counts (EA-40, review R3-F1).
    """
    folder_re = re.compile(rf"{re.escape(slug)}(?:-r[0-9]+)?")
    root = DISPATCH_ROOT / DISPATCH_FOLDER
    try:
        folders = [
            entry
            for entry in root.iterdir()
            if entry.is_dir() and folder_re.fullmatch(entry.name)
        ]
    except OSError:
        return None
    ready: datetime | None = None
    for folder in folders:
        try:
            loaded = json.loads((folder / STATUS_NAME).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(loaded, dict):
            continue
        exit_code = loaded.get("exit_code")
        if (
            loaded.get("kind") != "exec"
            or isinstance(exit_code, bool)
            or exit_code != 0
        ):
            continue
        end = _parse_time(loaded.get("end_utc"))
        if (
            end is None
            or (end.tzinfo is None) != (landed.tzinfo is None)
            or end > landed
        ):
            continue
        if ready is None or end > ready:
            ready = end
    return ready


def _report_row(
    repo: Path,
    sid: str,
    record_time: datetime | None,
    actions: Sequence[Mapping[str, Any]],
) -> list[str]:
    """The five cells of one pilot session.

    The wait to start runs from the typed record to the first worker attempt's
    start. The wait to land runs from the end of the latest successful worker
    attempt before the land, never from a failed one (EA-40, review R3-F1).
    """
    start_line: Mapping[str, Any] | None = None
    for item in reversed(actions):
        if item.get("action") == "start" and sid in item.get("sessions", []):
            start_line = item
            break
    status: Mapping[str, Any] = {}
    slug = ""
    if start_line is not None:
        listed = list(start_line["sessions"])
        ids = start_line.get("dispatch_ids", [])
        at = listed.index(sid)
        if at < len(ids):
            slug = str(ids[at])
            path = DISPATCH_ROOT / DISPATCH_FOLDER / slug / STATUS_NAME
            try:
                loaded = (
                    json.loads(path.read_text(encoding="utf-8"))
                    if path.is_file()
                    else {}
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                loaded = {}
            status = loaded if isinstance(loaded, dict) else {}
    began = _parse_time(status.get("start_utc")) or (
        _parse_time(start_line.get("at")) if start_line is not None else None
    )
    land_line = next(
        (
            item
            for item in reversed(actions)
            if item.get("action") == "land"
            and item.get("stage") == "commit"
            and item.get("session") == sid
        ),
        None,
    )
    landed = _parse_time(land_line.get("at")) if land_line is not None else None
    if landed is None:
        land_wait = "n/a"
    else:
        ready = _ready_to_land(slug, landed) if slug else None
        land_wait = (
            _wait(ready, landed)
            if ready is not None
            else "unavailable (no successful worker run before the land)"
        )
    queue = _review_queue(actions, sid)
    gate = _first_gate(actions, sid)
    return [
        sid,
        _wait(record_time, began),
        land_wait,
        queue.replace("|", "/"),
        gate.replace("|", "/"),
    ]


def _run_report(args: argparse.Namespace) -> int:
    """``report``: write the pilot report table; only the report file changes."""
    repo = Path(args.repo).resolve()
    pilots = _read_pilots(Path(args.pilot))
    message = pilots["message"]
    try:
        raw, _text = rp._human_record(
            rp._open_repo(repo), message["session"], message["uid"]
        )
        stamp = json.loads(raw).get("timestamp")
    except (rp.Refusal, json.JSONDecodeError, AttributeError):
        stamp = None
    record_time = _parse_time(stamp)
    actions = read_actions(repo)
    rows = [
        _report_row(repo, str(p["session"]), record_time, actions)
        for p in pilots["pilots"]
    ]
    tokens = pilots.get("decision_tokens")
    lines = [
        "# Pilot B report",
        "",
        "| " + " | ".join(REPORT_COLUMNS) + " |",
        "|" + "|".join(" --- " for _ in REPORT_COLUMNS) + "|",
        *("| " + " | ".join(cell or "n/a" for cell in row) + " |" for row in rows),
        "",
        f"Decision-session tokens: {tokens if tokens is not None else 'n/a (not recorded)'}",
        "",
    ]
    out = Path(args.out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes("\n".join(lines).encode("utf-8"))
    except OSError as exc:
        raise lanes.Refusal("write", f"{out}: {exc}") from None
    print(f"report_ok {out.as_posix()}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def _whole(text: str, least: int) -> int:
    """``text`` as a whole number of ``least`` or more, for argparse.

    Raises:
        argparse.ArgumentTypeError: ``text`` is not such a number.
    """
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if value < least:
        raise argparse.ArgumentTypeError(f"must be {least} or more: {value}")
    return value


def _count(text: str) -> int:
    """An argparse type: a whole number of 0 or more."""
    return _whole(text, 0)


def _positive(text: str) -> int:
    """An argparse type: a whole number of 1 or more."""
    return _whole(text, 1)


def _key_arg(text: str) -> str:
    """An argparse type: an action key (``[a-z0-9][a-z0-9-]{0,39}``).

    Raises:
        argparse.ArgumentTypeError: ``text`` is not a key.
    """
    if _KEY_RE.fullmatch(text) is None:
        raise argparse.ArgumentTypeError(f"not an action key: {text!r}")
    return text


def _rev_arg(text: str) -> str:
    """An argparse type: a facts rev (64 lower-case hex digits).

    Raises:
        argparse.ArgumentTypeError: ``text`` is not a rev.
    """
    if _REV_RE.fullmatch(text) is None:
        raise argparse.ArgumentTypeError(f"not a rev: {text!r}")
    return text


def _uuid_arg(text: str) -> str:
    """An argparse type: a message uuid.

    Raises:
        argparse.ArgumentTypeError: ``text`` is not a UUID.
    """
    try:
        uuid.UUID(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a uuid: {text!r}") from None
    return text


def _add_pilot_verbs(sub: Any) -> None:
    """Add the MEU-951 verbs ``facts``, ``start``, ``land`` and ``report``."""
    facts = sub.add_parser(
        "facts", help="print the sessions, claims or land queue and their rev"
    )
    facts.add_argument("kind", choices=FACT_KINDS)
    facts.add_argument(
        "--grouping",
        action="append",
        required=True,
        metavar="FILE",
        help="a grouping file, relative to --repo; give one or more",
    )
    facts.add_argument("--repo", default=".", help="the top of the main worktree")
    start = sub.add_parser(
        "start", help="make a clone and a worker launch for each of two sessions"
    )
    start.add_argument("--sessions", required=True, metavar="A,B")
    start.add_argument("--grouping", required=True, metavar="FILE")
    start.add_argument("--session", required=True, help="the transcript session")
    start.add_argument("--message-uuid", required=True, type=_uuid_arg)
    start.add_argument("--key", required=True, type=_key_arg)
    start.add_argument("--rev", required=True, type=_rev_arg)
    start.add_argument("--repo", default=".", help="the top of the main worktree")
    start.add_argument("--dry-run", action="store_true", help="check, change nothing")
    land = sub.add_parser("land", help="prepare or commit the result of one session")
    land.add_argument("--session", required=True, help="the grouping session id")
    land.add_argument("--stage", required=True, choices=STAGES)
    land.add_argument("--key", required=True, type=_key_arg)
    land.add_argument("--rev", required=True, type=_rev_arg)
    land.add_argument("--repo", default=".", help="the top of the main worktree")
    land.add_argument("--grouping", action="append", metavar="FILE")
    land.add_argument("--gate-run", help="the gate run folder (commit stage)")
    land.add_argument("--session-id", help="the transcript session of the direction")
    land.add_argument("--message-uuid", type=_uuid_arg)
    report = sub.add_parser("report", help="write the pilot report table")
    report.add_argument("--pilot", required=True, metavar="FILE")
    report.add_argument("--out", required=True, metavar="FILE")
    report.add_argument("--repo", default=".", help="the top of the main worktree")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orch.py",
        description=(
            "Scheduler views and pilot actions of the session groupings (MEU-925, "
            "MEU-951). The read verbs change nothing; start and land act only "
            "through the process seam of result_snapshot.py."
        ),
    )
    sub = parser.add_subparsers(dest="verb", required=True)
    elig = sub.add_parser(
        "eligible", help="the sessions that can start now, and why the others wait"
    )
    elig.add_argument(
        "--grouping",
        action="append",
        required=True,
        metavar="FILE",
        help="a grouping file; give one or more",
    )
    elig.add_argument(
        "--repo", default=".", help="the top of the main worktree (default: here)"
    )
    elig.add_argument(
        "--cards-dir",
        help="the lane cards folder (default: the lanes folder of the git common dir)",
    )
    elig.add_argument("--trees", choices=TREES, default="main")
    elig.add_argument("--workers", type=_positive, help="the running sessions in all")
    elig.add_argument("--reviews-running", type=_count, default=0)
    elig.add_argument("--plan-commits-running", type=_count, default=0)
    elig.add_argument("--json", action="store_true", help="print one JSON object")
    sim = sub.add_parser(
        "simulate", help="replay the greedy lane schedule and print the makespan"
    )
    source = sim.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec", metavar="FILE", help="an orch-spec/1 fixture")
    source.add_argument(
        "--grouping",
        action="append",
        metavar="FILE",
        help="a grouping file; give one or more",
    )
    sim.add_argument("--order", choices=ORDERS, default="critical-path")
    sim.add_argument("--executors", type=_positive, default=1)
    sim.add_argument("--borrow", metavar="LANE", help="the lane that takes spare work")
    sim.add_argument("--workers", type=_positive, help="the running sessions in all")
    sim.add_argument("--trees", choices=TREES, default="lanes")
    sim.add_argument("--json", action="store_true", help="print one JSON object")
    _add_pilot_verbs(sub)
    return parser


def _run_simulate(args: argparse.Namespace) -> dict[str, Any]:
    """The ``simulate`` result of the parsed arguments."""
    if args.spec is not None:
        lane_list, sessions = load_spec(Path(args.spec))
    else:
        lane_list, sessions = load_groupings([Path(item) for item in args.grouping])
    return simulate(
        lane_list,
        sessions,
        order=args.order,
        executors=args.executors,
        borrow=args.borrow,
        workers=args.workers,
        trees=args.trees,
    )


def _run_eligible(args: argparse.Namespace) -> dict[str, Any]:
    """The ``eligible`` result of the parsed arguments."""
    lane_list, sessions, files = _read_groupings([Path(item) for item in args.grouping])
    statuses = _progress(files)
    repo = Path(args.repo).resolve()
    cards_dir = Path(args.cards_dir) if args.cards_dir else _cards_dir(repo)
    groupings = {_normalized(path): sids for path, _text, sids in files}
    reservations = read_cards(cards_dir, repo, groupings)
    return eligible(
        lane_list,
        sessions,
        statuses,
        reservations,
        repo=repo,
        trees=args.trees,
        workers=args.workers,
        reviews_running=args.reviews_running,
        plan_commits_running=args.plan_commits_running,
        ignorecase=_ignorecase(repo),
    )


def _text(value: object) -> str:
    """``value`` for the text output; ``none`` for None."""
    return "none" if value is None else str(value)


def _print_simulate(result: Mapping[str, Any]) -> None:
    print(
        f"makespan {result['makespan']} order={result['order']} "
        f"trees={result['trees']} executors={result['executors']} "
        f"borrow={_text(result['borrow'])} workers={_text(result['workers'])}"
    )
    for lane, entries in result["schedule"].items():
        cells = " ".join(
            f"{entry['sid']}@{entry['start']}-{entry['end']}" for entry in entries
        )
        print(f"{lane}: {cells or '-'}")
    for sid, reasons in result["held"].items():
        print(f"held {sid}: {'; '.join(reasons)}")
    print("caps_not_modeled: " + " ".join(result["caps_not_modeled"]))


def _print_eligible(result: Mapping[str, Any]) -> None:
    print("eligible: " + (" ".join(result["eligible"]) or "none"))
    print("running: " + (" ".join(result["running"]) or "none"))
    for sid, reasons in result["excluded"].items():
        print(f"waits {sid}: {'; '.join(reasons)}")
    for name, record in result["resources"].items():
        print(
            f"resource {name}: configured={_text(record['configured_value'])} "
            f"observed={record['observed_value']} free={_text(record['free'])}"
        )
    print(
        f"can_dispatch_review={str(result['can_dispatch_review']).lower()} "
        f"can_plan_commit={str(result['can_plan_commit']).lower()}"
    )


_PILOT_RUNNERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "facts": _run_facts,
    "start": _run_start,
    "land": _run_land,
    "report": _run_report,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run one verb: 0 for a result, 1 for a refused input, 2 for an argument error."""
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    pilot = _PILOT_RUNNERS.get(args.verb)
    try:
        if pilot is not None:
            return pilot(args)
        result = _run_eligible(args) if args.verb == "eligible" else _run_simulate(args)
    except (lanes.Refusal, result_snapshot.SnapshotRefusal) as exc:
        print(f"{args.verb}_bad:{exc.reason}")
        if exc.detail:
            print(exc.detail, file=sys.stderr)
        return EXIT_REFUSED
    except OSError as exc:
        print(f"{args.verb}_bad:io")
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED
    if args.json:
        print(json.dumps(result, indent=1))
    elif args.verb == "eligible":
        _print_eligible(result)
    else:
        _print_simulate(result)
    return EXIT_OK


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
