"""Read-only scheduler views of the session groupings (MEU-925, AO1).

``python tools/orch.py simulate`` replays the greedy lane schedule of the grouping
guide on a spec fixture (``--spec``) or on grouping files (``--grouping``) and prints
the makespan. ``python tools/orch.py eligible`` reads the Session Progress tables of
the groupings and the lane cards, and prints the sessions that can start now and the
reasons of each session that cannot.

The tool only reads files. It has the two verbs and no other: it never commits,
lands, reviews, rules or starts a process. A refused input prints
``<verb>_bad:<reason>`` on stdout line 1 and the detail on stderr, and exits 1. An
argument error exits 2.

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
import io
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from . import lanes
else:  # run as a script, or imported with tools/ on sys.path
    import lanes

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
) -> tuple[list[str], dict[str, Session], list[tuple[Path, str, list[str]]]]:
    """The lanes and sessions of the grouping files, and each file's text and ids.

    Every key of a block is optional: a session with no ``size`` has ``size`` None,
    and ``simulate`` refuses it (``eligible`` does not).

    Raises:
        lanes.Refusal: ``grouping:read``, ``grouping:<lanes reason>`` for a
            Session Ownership block that ``lanes.parse_session_spec`` refuses,
            ``sid:<sid>``, ``duplicate:<sid>``, or a ``_check_graph`` reason.
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orch.py",
        description="Read-only scheduler views of the session groupings (MEU-925).",
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run one verb: 0 for a result, 1 for a refused input, 2 for an argument error."""
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    try:
        result = _run_eligible(args) if args.verb == "eligible" else _run_simulate(args)
    except lanes.Refusal as exc:
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
