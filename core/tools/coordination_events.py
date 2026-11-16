"""Coordination-event records: the wait, land and refusal records of design §5.2 (MEU-943).

One record is one JSON line in ``coordination-events.jsonl``. The file is in the folder of
``{{PROJECT_NAME_UPPER}}_HOOK_LOG`` (an existing variable; no new variable, AC-943.8), or
at the path that the caller gives. The writers are the coordination tools (through a private loader that
reads this file by path, design item 3a) and a session (through the ``record`` command).

``record`` never raises: a field that fails its rule, no destination or a failed write
returns ``False`` and writes nothing. ``report`` reads the records back into the metrics of
design §5.5.

This module imports only the standard library, so each tool can load it by file path
without a change to ``sys.path`` (AC-943.7).

Commands::

    python tools/coordination_events.py record --kind <kind> --session <id> --plan <plan>
        --row <row> --reason <code> --scope <resource> [--blocker <holder>]
        [--outcome <outcome>] [--log <path>]
    python tools/coordination_events.py report --log <events> [--hook-log <hook log>]
        [--as-of <ISO 8601 UTC>] [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVENT_SCHEMA = "coordination-event/1"
EVENTS_FILE = "coordination-events.jsonl"
HOOK_LOG_ENV = "{{PROJECT_NAME_UPPER}}_HOOK_LOG"
SESSION_ENV = "{{PROJECT_NAME_UPPER}}_SESSION"
NONE_TOKEN = "-"

SESSION_KINDS = ("wait_started", "continued_elsewhere", "parked", "resumed", "ended")
KINDS = (
    "busy_observed",
    *SESSION_KINDS,
    "land_started",
    "land_ended",
    "refused",
    "committed",
    "step_refused",
)
OUTCOMES: dict[str, tuple[str, ...]] = {
    "ended": ("resumed_work", "gave_up", "handed_back"),
    "land_ended": ("closed", "superseded", "abandoned", "refused"),
}
RECORD_KEYS = (
    "schema",
    "id",
    "ts",
    "writer",
    "kind",
    "session",
    "plan",
    "row",
    "reason",
    "scope",
    "blocker",
    "outcome",
)

REASON_RE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")
# No space, quote, ``$``, ``;``, ``|`` or ``&``: a command string cannot pass (design item 3).
TOKEN_RE = re.compile(r"^[A-Za-z0-9_./:@#=+-]{1,200}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
PLAN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]{0,119}$")
ROW_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# The bytes that ``scope_token`` keeps as they are; every other byte becomes ``=XX``.
_PLAIN_BYTES = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:@#+-"
)
_TOKEN_MAX = 200

USAGE_EXIT = 2

# Windows ``CreateFileW`` values of the atomic append (``_append``).
_FILE_APPEND_DATA = 0x0004
_FILE_SHARE_ALL = 0x0001 | 0x0002 | 0x0004
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80


class RecordInvalid(ValueError):
    """A record field that fails its rule; ``field`` names it."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


# --- the writer ------------------------------------------------------------------------


def now_ts() -> str:
    """The current UTC time as ISO 8601 with milliseconds and a ``Z`` suffix."""
    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


def destination(log: str | os.PathLike[str] | None = None) -> Path | None:
    """The record file: ``log``, else beside ``{{PROJECT_NAME_UPPER}}_HOOK_LOG``, else
    ``None``."""
    if log is not None and str(log) != "":
        return Path(log)
    hook_log = os.environ.get(HOOK_LOG_ENV, "")
    if not hook_log:
        return None
    return Path(hook_log).parent / EVENTS_FILE


def tool_session() -> str:
    """The session id of a tool record: ``{{PROJECT_NAME_UPPER}}_SESSION`` when it is
    valid, else ``-``."""
    value = os.environ.get(SESSION_ENV, "")
    return value if SESSION_RE.fullmatch(value) else NONE_TOKEN


def reason_code(text: object, fallback: str = "invalid_reason") -> str:
    """``text`` cut to a reason code: the part before a space, kept when it fits ``REASON_RE``."""
    head = str(text).strip().split(" ", 1)[0] if text is not None else ""
    head = head[:64]
    return head if REASON_RE.fullmatch(head) else fallback


def token(value: object) -> str | None:
    """``value`` as text when it fits ``TOKEN_RE``, else ``None`` (a holder that a site
    cannot name as a token is left out; the record is still written)."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value)
    return text if TOKEN_RE.fullmatch(text) else None


def scope_token(value: object) -> str | None:
    """``value`` as a token that keeps its identity (execution review R1-F4).

    A byte outside ``[A-Za-z0-9_./:@#+-]`` (``=`` included) becomes ``=XX`` of its UTF-8
    byte, so a valid path with a space or a non-ASCII letter still names one resource and
    two values never share a token. A result longer than 200 characters becomes
    ``sha256:<hex>`` of the value. ``None`` for ``None``, a bool or an empty value.
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value)
    if not text:
        return None
    raw = text.encode("utf-8", "surrogatepass")
    out = "".join(chr(b) if b in _PLAIN_BYTES else f"={b:02X}" for b in raw)
    if len(out) > _TOKEN_MAX:
        return "sha256:" + hashlib.sha256(raw).hexdigest()
    return out


def split_code(text: object) -> tuple[str, str | None]:
    """A printed refusal ``code[:rest]``: the reason code and the rest as a ``scope_token``.

    The text is the first line of the refusal code; the rest keeps a space or another
    byte that is not a token byte in its ``=XX`` form, so a path is never cut short.
    """
    raw = (
        str(text).strip().splitlines()[0]
        if text is not None and str(text).strip()
        else ""
    )
    code, _, rest = raw.partition(":")
    reason = reason_code(code)
    return reason, scope_token(rest)


def _check(
    kind: str,
    *,
    writer: str,
    session: str,
    plan: str,
    row: str,
    reason: str,
    scope: str,
    blocker: str | None,
    outcome: str | None,
) -> None:
    """Raise ``RecordInvalid`` for the first field that fails its rule."""
    if kind not in KINDS:
        raise RecordInvalid("kind")
    if not isinstance(writer, str) or not REASON_RE.fullmatch(writer):
        raise RecordInvalid("writer")
    if not isinstance(session, str) or not (
        session == NONE_TOKEN or SESSION_RE.fullmatch(session)
    ):
        raise RecordInvalid("session")
    if not isinstance(plan, str) or not (plan == NONE_TOKEN or PLAN_RE.fullmatch(plan)):
        raise RecordInvalid("plan")
    if not isinstance(row, str) or not (row == NONE_TOKEN or ROW_RE.fullmatch(row)):
        raise RecordInvalid("row")
    if not isinstance(reason, str) or not REASON_RE.fullmatch(reason):
        raise RecordInvalid("reason")
    if not isinstance(scope, str) or not TOKEN_RE.fullmatch(scope):
        raise RecordInvalid("scope")
    if blocker is not None and (
        not isinstance(blocker, str) or not TOKEN_RE.fullmatch(blocker)
    ):
        raise RecordInvalid("blocker")
    allowed = OUTCOMES.get(kind)
    if outcome is not None and (allowed is None or outcome not in allowed):
        raise RecordInvalid("outcome")


def _build(
    kind: str,
    *,
    writer: str,
    session: str | None,
    plan: str | None,
    row: str | None,
    reason: str,
    scope: str,
    blocker: str | None,
    outcome: str | None,
) -> dict[str, Any]:
    """A checked record dict; raises ``RecordInvalid``."""
    fields = {
        "writer": writer,
        "session": tool_session() if session is None else session,
        "plan": NONE_TOKEN if plan is None else plan,
        "row": NONE_TOKEN if row is None else row,
        "reason": reason,
        "scope": scope,
        "blocker": blocker,
        "outcome": outcome,
    }
    _check(kind, **fields)
    return {
        "schema": EVENT_SCHEMA,
        "id": uuid.uuid4().hex,
        "ts": now_ts(),
        "writer": fields["writer"],
        "kind": kind,
        "session": fields["session"],
        "plan": fields["plan"],
        "row": fields["row"],
        "reason": fields["reason"],
        "scope": fields["scope"],
        "blocker": fields["blocker"],
        "outcome": fields["outcome"],
    }


def _append_bytes(path: Path, data: bytes) -> bool:
    """One atomic append of ``data`` at the end of ``path``; ``True`` when all of it went in.

    Execution review R1-F1: a buffered ``open("ab")`` on Windows moves to the end and then
    writes, so two processes can write at the same offset and one line is lost. Windows
    opens the file with ``FILE_APPEND_DATA`` only, so the system puts each ``WriteFile`` at
    the end of the file; POSIX uses ``O_APPEND`` with one ``write``.
    """
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateFileW
        create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create.restype = wintypes.HANDLE
        write = kernel32.WriteFile
        write.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        write.restype = wintypes.BOOL
        close = kernel32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        handle = create(
            str(path),
            _FILE_APPEND_DATA,
            _FILE_SHARE_ALL,
            None,
            _OPEN_ALWAYS,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if handle is None or handle == ctypes.c_void_p(-1).value:
            return False
        try:
            written = wintypes.DWORD(0)
            done = write(handle, data, len(data), ctypes.byref(written), None)
            return bool(done) and written.value == len(data)
        finally:
            close(handle)
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        return os.write(fd, data) == len(data)
    finally:
        os.close(fd)


def _append(path: Path, rec: dict[str, Any]) -> bool:
    """Append one line with one atomic write; ``False`` on any error (design §5.4)."""
    data = (json.dumps(rec, ensure_ascii=True, separators=(", ", ": ")) + "\n").encode(
        "utf-8"
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return _append_bytes(path, data)
    except (OSError, ValueError, AttributeError):
        return False


def _land_ended_exists(path: Path, op: str) -> bool:
    """``True`` when ``path`` already holds a ``land_ended`` record of the op ``op``.

    Execution review R1-F3/R1-F6: a land op ends once. A recovery that runs again (a
    superseded op refused at each recovery, or an abandon after an ``owns_violation``)
    finds the record and writes no second one. The op lease serializes the writers of one
    op. A file that cannot be read counts as no record.
    """
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"land_ended"' not in line:
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if (
                    isinstance(item, dict)
                    and item.get("kind") == "land_ended"
                    and item.get("scope") == op
                ):
                    return True
    except OSError:
        return False
    return False


def record(
    kind: str,
    *,
    writer: str,
    reason: str,
    scope: str,
    session: str | None = None,
    plan: str | None = None,
    row: str | None = None,
    blocker: str | None = None,
    outcome: str | None = None,
    log: str | os.PathLike[str] | None = None,
) -> bool:
    """Append one record; ``False`` (and no line) when a field fails, or with no destination
    or a failed write. Never raises (design §5.4).

    ``session`` defaults to the tool session (``tool_session``), ``plan`` and ``row`` to ``-``.
    A ``land_ended`` of an op that already has one writes nothing and returns ``True``
    (``_land_ended_exists``).
    """
    try:
        rec = _build(
            kind,
            writer=writer,
            session=session,
            plan=plan,
            row=row,
            reason=reason,
            scope=scope,
            blocker=blocker,
            outcome=outcome,
        )
        path = destination(log)
        if path is None:
            return False
        if kind == "land_ended" and _land_ended_exists(path, scope):
            return True
        return _append(path, rec)
    except Exception:  # noqa: BLE001 - the contract of design §5.4: a record never raises
        return False


# --- the report ------------------------------------------------------------------------


def _parse_ts(value: object) -> datetime | None:
    """An ISO 8601 UTC time (``Z`` or ``+00:00``); ``None`` when it is not one."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(None):
        return None
    return stamp


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """The JSON object lines of ``path`` and the count of the other non-empty lines."""
    good: list[dict[str, Any]] = []
    bad = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(item, dict):
                good.append(item)
            else:
                bad += 1
    return good, bad


def _split_events(
    items: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """(complete records, all records of the schema, malformed count)."""
    complete: list[dict[str, Any]] = []
    known: list[dict[str, Any]] = []
    malformed = 0
    for item in items:
        if item.get("schema") != EVENT_SCHEMA:
            malformed += 1
            continue
        known.append(item)
        if all(key in item for key in RECORD_KEYS) and _parse_ts(item["ts"]):
            complete.append(item)
    return complete, known, malformed


def _episodes(events: list[dict[str, Any]], as_of: datetime) -> list[dict[str, Any]]:
    """The wait episodes of design item 9, in the order they start."""
    out: list[dict[str, Any]] = []
    open_eps: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rec in events:
        key = (str(rec["session"]), str(rec["plan"]), str(rec["scope"]))
        kind = rec["kind"]
        stamp = _parse_ts(rec["ts"])
        if stamp is None:
            continue
        episode = open_eps.get(key)
        if kind == "wait_started" or (kind == "busy_observed" and episode is None):
            if episode is None:
                episode = {
                    "session": key[0],
                    "plan": key[1],
                    "scope": key[2],
                    "start": stamp,
                    "continued_elsewhere": 0,
                    "parked": 0,
                    "outcome": None,
                    "end": None,
                }
                open_eps[key] = episode
                out.append(episode)
        elif episode is None:
            continue
        elif kind == "continued_elsewhere":
            episode["continued_elsewhere"] += 1
        elif kind == "parked":
            episode["parked"] += 1
        elif kind == "ended":
            episode["end"] = stamp
            episode["outcome"] = rec.get("outcome")
            del open_eps[key]
    result = []
    for episode in out:
        end = episode["end"]
        censored = end is None
        stop = as_of if censored else end
        result.append(
            {
                "session": episode["session"],
                "plan": episode["plan"],
                "scope": episode["scope"],
                "start": episode["start"]
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                "continued_elsewhere": episode["continued_elsewhere"],
                "parked": episode["parked"],
                "outcome": episode["outcome"],
                "censored": censored,
                "wait_s": round((stop - episode["start"]).total_seconds(), 3),
            }
        )
    return result


def build_report(
    events_items: list[dict[str, Any]],
    events_bad: int,
    hook_items: list[dict[str, Any]],
    hook_bad: int,
    as_of: datetime | None,
) -> dict[str, Any]:
    """The metrics of design §5.5 from the parsed lines."""
    events, known, malformed = _split_events(events_items)
    # Execution review R1-F7: the time alone; the stable sort keeps the append order of
    # records with the same time, and the id (random, perhaps malformed) plays no part.
    events.sort(key=lambda rec: _parse_ts(rec["ts"]) or datetime.min)
    if as_of is None:
        stamps = [_parse_ts(rec["ts"]) for rec in events]
        valid = [s for s in stamps if s is not None]
        as_of = max(valid) if valid else datetime.now(timezone.utc)

    asks = sum(1 for rec in hook_items if rec.get("decision") == "ask")
    commit_ops = {str(rec["scope"]) for rec in events if rec["kind"] == "committed"}
    land_closed = {
        str(rec["scope"])
        for rec in events
        if rec["kind"] == "land_ended" and rec["outcome"] == "closed"
    }
    commits = len(commit_ops) + len(land_closed)
    per_commit: float | str = round(asks / commits, 6) if commits else "n/a"

    handbacks = sum(
        1
        for rec in events
        if rec["kind"] == "parked" and rec["reason"] != "human_decision"
    )
    collisions = sum(
        1
        for rec in events
        if (
            rec["kind"] == "busy_observed"
            and rec["reason"] in ("parent_moved", "claim_overlap")
        )
        or (rec["kind"] == "refused" and rec["reason"] == "parent_moved")
    )
    foreign = sum(
        1
        for rec in events
        if rec["kind"] == "refused" and rec["reason"] == "foreign_edit"
    )

    started: dict[str, datetime] = {}
    ended: dict[str, tuple[str, datetime]] = {}
    step_refusals: dict[str, int] = {}
    for rec in events:
        stamp = _parse_ts(rec["ts"])
        if stamp is None:
            continue
        op = str(rec["scope"])
        if rec["kind"] == "land_started":
            started.setdefault(op, stamp)
        elif rec["kind"] == "land_ended" and op not in ended:
            ended[op] = (str(rec["outcome"]), stamp)
        elif rec["kind"] == "step_refused":
            step_refusals[str(rec["reason"])] = (
                step_refusals.get(str(rec["reason"]), 0) + 1
            )
    land_times = {
        op: round((stamp - started[op]).total_seconds(), 3)
        for op, (outcome, stamp) in sorted(ended.items())
        if outcome == "closed" and op in started
    }
    mix = {name: 0 for name in OUTCOMES["land_ended"]}
    mix["open"] = 0
    for op in set(started) | set(ended):
        if op in ended:
            outcome = ended[op][0]
            if outcome in mix:
                mix[outcome] += 1
        else:
            mix["open"] += 1

    per_writer: dict[str, int] = {}
    for rec in known:
        name = str(rec.get("writer"))
        per_writer[name] = per_writer.get(name, 0) + 1
    missing = len(known) - len(events)
    test_records = sum(
        1 for rec in hook_items if not UUID_RE.fullmatch(str(rec.get("session_id", "")))
    ) + sum(1 for rec in known if not UUID_RE.fullmatch(str(rec.get("session", ""))))

    return {
        "as_of": as_of.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "asks": asks,
        "commits": commits,
        "prompts_per_commit": per_commit,
        "handbacks_no_decision": handbacks,
        "episodes": _episodes(events, as_of),
        "collisions_caught": collisions,
        "foreign_edit_failures": foreign,
        "land_times": land_times,
        "outcome_mix": mix,
        "step_refusals": dict(sorted(step_refusals.items())),
        "records_per_writer": per_writer,
        "missing_fields": missing,
        "malformed_lines": malformed + events_bad + hook_bad,
        "test_records": test_records,
    }


def _report_text(data: dict[str, Any]) -> str:
    """One ``<metric>: <value>`` line for each metric."""
    lines = []
    for key, value in data.items():
        shown = value if isinstance(value, str | int | float) else json.dumps(value)
        lines.append(f"{key}: {shown}")
    return "\n".join(lines) + "\n"


# --- the commands ----------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coordination_events.py",
        description="Write or report the coordination-event records (MEU-943).",
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", allow_abbrev=False, help="append one record")
    rec.add_argument("--kind", required=True)
    rec.add_argument("--session", required=True)
    rec.add_argument("--plan", required=True)
    rec.add_argument("--row", required=True)
    rec.add_argument("--reason", required=True)
    rec.add_argument("--scope", required=True)
    rec.add_argument("--blocker")
    rec.add_argument("--outcome")
    rec.add_argument("--log")
    rep = sub.add_parser("report", allow_abbrev=False, help="print the metrics")
    rep.add_argument("--log", required=True)
    rep.add_argument("--hook-log")
    rep.add_argument("--as-of")
    rep.add_argument("--json", action="store_true")
    return parser


def _cmd_record(args: argparse.Namespace) -> int:
    try:
        rec = _build(
            args.kind,
            writer="session",
            session=args.session,
            plan=args.plan,
            row=args.row,
            reason=args.reason,
            scope=args.scope,
            blocker=args.blocker,
            outcome=args.outcome,
        )
    except RecordInvalid as exc:
        print(f"record_invalid {exc.field}", file=sys.stderr)
        return USAGE_EXIT
    path = destination(args.log)
    if path is None:
        print("record_skipped no_destination", file=sys.stderr)
        return 0
    if not _append(path, rec):
        print("record_skipped write_failed", file=sys.stderr)
        return 0
    print(f"recorded {rec['kind']} {rec['id']}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    as_of = None
    if args.as_of is not None:
        as_of = _parse_ts(args.as_of)
        if as_of is None:
            print("report_invalid as_of", file=sys.stderr)
            return USAGE_EXIT
    events_path = Path(args.log)
    if not events_path.is_file():
        print("report_invalid log_missing", file=sys.stderr)
        return USAGE_EXIT
    hook_items: list[dict[str, Any]] = []
    hook_bad = 0
    if args.hook_log is not None:
        hook_path = Path(args.hook_log)
        if not hook_path.is_file():
            print("report_invalid hook_log_missing", file=sys.stderr)
            return USAGE_EXIT
        hook_items, hook_bad = _read_jsonl(hook_path)
    try:
        events_items, events_bad = _read_jsonl(events_path)
    except OSError as exc:
        print(f"report_invalid log_unreadable {type(exc).__name__}", file=sys.stderr)
        return USAGE_EXIT
    data = build_report(events_items, events_bad, hook_items, hook_bad, as_of)
    if args.json:
        print(json.dumps(data, sort_keys=False))
    else:
        sys.stdout.write(_report_text(data))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """``record`` or ``report``; exit 0, or 2 on a usage error or an invalid field."""
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "record":
        return _cmd_record(args)
    return _cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
