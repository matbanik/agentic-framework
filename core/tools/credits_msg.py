"""Run-side message tool of a credits run (S1b, Component C; R§4.3, R§4.6.4, R§4.6.5, R§5.4).

The executing agent of a credits run calls this tool. Each verb is one store
transaction and prints one JSON object on stdout::

    python tools/credits_msg.py [--now-utc T] ack <msg_id> <text>
    python tools/credits_msg.py [--now-utc T] applied <msg_id>
    python tools/credits_msg.py [--now-utc T] report <text>
    python tools/credits_msg.py [--now-utc T] decision <D-n> <question and options>
    python tools/credits_msg.py [--now-utc T] wait [--max-wait-ms MS] [--poll-ms MS]
    python tools/credits_msg.py [--now-utc T] tree <path>
    python tools/credits_msg.py [--now-utc T] landing --part product
        --changed-files <file> --closeout <path> [--closeout <path> ...]
    python tools/credits_msg.py [--now-utc T] landing --part closeout
    python tools/credits_msg.py authority [--quote <words>]
    python tools/credits_msg.py locate --session <id> --quote <text>

Environment: ``CREDITS_RUN_ID``, ``CREDITS_SEGMENT`` and ``CREDITS_STATE_DB``
are required (a missing value is a usage error, exit 2, and no store is
opened). ``CREDITS_CONFIG`` names the config file (default
``.agent/credits/config.json`` of this repository). ``tree`` also reads the
optional ``CREDITS_BASE_COMMIT``. ``locate`` needs none of them.

``authority`` is a read-only verb (EA-90): it opens the store with
``mode=ro``, reads no config, and shows the start request that launched this
segment (segment → attempt → request). ``--quote`` checks the human's words
against the recorded quote, normalized as the ruling verifier does.

``locate`` (R§4.6.3) is the interactive agent's read-only helper. It opens no
store. It reads the session's transcript (``CLAUDE_CONFIG_DIR``, else
``~/.claude``, then ``projects/<slug>/<session>.jsonl``) and proposes the uuid of
the one typed human entry whose normalized text equals the quote (``not_found``
or ``ambiguous`` otherwise). The inbox hook checks the entry again.

The first ``tree`` of a run checks the base and pins the start tree S. A later
``tree`` of the same run (a resume) keeps B, S and the retained edits; it checks
that HEAD is still B, that the tree is the recorded one and that the start ref
still names S (R1-F4).

Exit codes are the store's: 0 changed, no_change or ok; 2 usage; 3 refused;
9 crash (test seam ``CREDITS_TEST_CRASH_AT=ack:<point>``); 75 busy.

An outbox event has the unique ``semantic_key`` of R§4.6.5. A retry of the
same semantic event writes nothing and returns the existing ``event_id``
(``<run_id>-<event_seq>``).

``tree`` and ``landing`` cover the main tree in S1b. The worktree checks
(``capture_main_mismatch``, ``start_tree_mismatch``) and the carry check
against the prerequisite set D (``base_carry_mismatch``) are S5.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import credits_state as cs

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / ".agent" / "credits" / "config.json"

REQUIRED_ENV = ("CREDITS_RUN_ID", "CREDITS_SEGMENT", "CREDITS_STATE_DB")
MSG_CRASH_POINTS: dict[str, tuple[str, ...]] = {"ack": cs.BASE_POINTS}

CONFIG_KEYS = frozenset(
    {"ruling_enabled", "gate_wait_max_min", "cache_ttl", "credits_start_policy"}
)
CACHE_TTLS = frozenset({"5m", "1h"})
# Who may start a scheduled run (Start-CreditsRunTask.ps1 enforces it); human-only is
# the template default.
START_POLICIES = frozenset({"human-only", "agent-on-user-chat"})

# Kinds that ``applied`` closes; ``ack`` closes the others.
APPLIED_KINDS = frozenset({"stop-after-row", "ruling"})
ACK_CLOSES_KINDS = frozenset({"info", "query"})

DECISION_RE = re.compile(r"^D-[0-9]{1,6}$")

# R§4.6.5 ``wait``: the store is read every 2 s, for at most 540 s.
WAIT_POLL_S = 2.0
WAIT_MAX_S = 540
# Test seam: each poll of ``wait`` moves the injected clock on by this many ms.
CLOCK_STEP_ENV = "CREDITS_TEST_CLOCK_STEP_MS"
# R§4.6.5 ``decision``: a gate ends 15 minutes before the segment deadline.
GATE_DEADLINE_MARGIN_MIN = 15

# The three shared status files that a run carries from the main tree (R§4.3).
STATUS_FILES = (
    ".agent/context/meu-status.yaml",
    ".agent/context/meu-registry.md",
    ".agent/context/current-focus.md",
)

# R§4.3 helper settings: the clean filter pins LF, so a CRLF-only rewrite is no change.
EOL_PIN = ("-c", "core.autocrlf=true", "-c", "core.safecrlf=false")
GIT_ENV_DROPPED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
GIT_TIMEOUT_S = 300
# The landing blob of a deleted product path and of a missing closeout file; the
# predicates of a successor read the same values (credits_state.py).
DELETED = cs.DELETED_BLOB
ABSENT = cs.ABSENT_BLOB
# R§5.4: the executor-worktree helper's manifest in the worktree's git folder, and the
# ref of its baseline (then landed) tree in the main tree.
WORKTREE_MANIFEST = "executor-worktree.json"
WORKTREE_REF_PREFIX = "refs/executor-worktrees/"


# --- arguments ----------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    """An argument parser that raises ``UsageError`` instead of exiting."""

    def error(self, message: str) -> NoReturn:
        raise cs.UsageError(message)


def _arg_decision(text: str) -> str:
    if not DECISION_RE.match(text):
        raise argparse.ArgumentTypeError(f"not a decision id D-<n>: {text!r}")
    return text


def _arg_ms(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"not a time in ms > 0: {text!r}")
    return value


def _arg_rel(text: str) -> str:
    rel = text.strip().replace("\\", "/")
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise argparse.ArgumentTypeError(f"not a repository-relative path: {text!r}")
    if ".." in rel.split("/"):
        raise argparse.ArgumentTypeError(f"a path must not hold '..': {text!r}")
    return rel


def build_parser() -> _Parser:
    """Return the parser of every verb."""
    parser = _Parser(prog="credits_msg.py", description=__doc__)
    parser.add_argument("--now-utc", type=cs._arg_utc)  # pyright: ignore[reportPrivateUsage]
    verbs = parser.add_subparsers(dest="verb", required=True, parser_class=_Parser)

    p = verbs.add_parser("ack", help="record receipt of a message")
    p.add_argument("msg_id", type=cs._arg_key)  # pyright: ignore[reportPrivateUsage]
    p.add_argument("text", type=cs._arg_text)  # pyright: ignore[reportPrivateUsage]

    p = verbs.add_parser("applied", help="record the effect of a message")
    p.add_argument("msg_id", type=cs._arg_key)  # pyright: ignore[reportPrivateUsage]

    p = verbs.add_parser("report", help="send a report event")
    p.add_argument("text", type=cs._arg_text)  # pyright: ignore[reportPrivateUsage]

    p = verbs.add_parser("decision", help="open the run's one gate")
    p.add_argument("decision_id", type=_arg_decision)
    p.add_argument("question", type=cs._arg_text)  # pyright: ignore[reportPrivateUsage]

    p = verbs.add_parser("wait", help="wait at the open gate")
    # Seams of the wait (the code uses min(value, WAIT_MAX_S), so a seam only lowers the cap).
    p.add_argument("--max-wait-ms", type=_arg_ms)
    p.add_argument("--poll-ms", type=_arg_ms)

    p = verbs.add_parser("tree", help="check the base and pin the start tree")
    p.add_argument("path")

    p = verbs.add_parser(
        "landing", help="capture the product part or seal the closeout"
    )
    p.add_argument("--part", choices=("product", "closeout"), required=True)
    p.add_argument("--changed-files")
    p.add_argument("--closeout", action="append", type=_arg_rel, default=[])

    p = verbs.add_parser(
        "authority", help="show the start record of this segment (read-only)"
    )
    p.add_argument("--quote", type=cs._arg_text)  # pyright: ignore[reportPrivateUsage]

    p = verbs.add_parser(
        "locate", help="propose the transcript uuid of a quoted entry (read-only)"
    )
    p.add_argument("--session", required=True, type=cs._arg_key)  # pyright: ignore[reportPrivateUsage]
    p.add_argument("--quote", required=True, type=cs._arg_text)  # pyright: ignore[reportPrivateUsage]
    return parser


def parse_msg_crash(raw: str | None) -> tuple[str, str] | None:
    """Validate ``CREDITS_TEST_CRASH_AT`` against this tool's crash points."""
    if raw is None or raw == "":
        return None
    verb, sep, point = raw.partition(":")
    if not sep or point not in MSG_CRASH_POINTS.get(verb, ()):
        raise cs.UsageError(
            f"CREDITS_TEST_CRASH_AT={raw!r} is not a declared <verb>:<point>"
        )
    return verb, point


def require_env() -> dict[str, str]:
    """Return the required ``CREDITS_*`` values; a missing one is a usage error."""
    values = {name: os.environ.get(name, "") for name in REQUIRED_ENV}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise cs.UsageError(f"missing environment: {', '.join(missing)}")
    return values


# --- config ---------------------------------------------------------------------------------


def load_config() -> dict[str, Any]:
    """Read and check ``config.json``: exactly the four keys with valid values."""
    path = Path(os.environ.get("CREDITS_CONFIG") or DEFAULT_CONFIG)
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise cs.Refusal(
            "config_invalid", f"the config {path} cannot be read: {exc}"
        ) from exc
    if not isinstance(loaded, dict):
        raise cs.Refusal("config_invalid", "the config is not a JSON object")
    config: dict[str, Any] = {str(k): v for k, v in loaded.items()}  # pyright: ignore[reportUnknownVariableType]
    if set(config) != CONFIG_KEYS:
        raise cs.Refusal(
            "config_invalid",
            f"the config keys must be exactly {sorted(CONFIG_KEYS)}",
            keys=sorted(config),
        )
    if not isinstance(config["ruling_enabled"], bool):
        raise cs.Refusal("config_invalid", "ruling_enabled must be true or false")
    wait = config["gate_wait_max_min"]
    if isinstance(wait, bool) or not isinstance(wait, int) or wait < 0:
        raise cs.Refusal("config_invalid", "gate_wait_max_min must be an integer >= 0")
    if config["cache_ttl"] not in CACHE_TTLS:
        raise cs.Refusal(
            "config_invalid", f"cache_ttl must be one of {sorted(CACHE_TTLS)}"
        )
    if config["credits_start_policy"] not in START_POLICIES:
        raise cs.Refusal(
            "config_invalid",
            f"credits_start_policy must be one of {sorted(START_POLICIES)}",
        )
    return config


# --- store helpers --------------------------------------------------------------------------


def get_run(tx: cs.Tx, run_id: str) -> sqlite3.Row:
    """Return the run row, or refuse ``unknown_run``."""
    run = tx.row("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    if run is None:
        raise cs.Refusal("unknown_run", f"no run {run_id}")
    return run


def segment_ordinal(tx: cs.Tx, run_id: str, segment_id: str) -> int:
    """Return the 1-based place of the segment in its run, or refuse ``unknown_segment``."""
    found = tx.row(
        "SELECT rowid FROM segments WHERE segment_id = ? AND run_id = ?",
        (segment_id, run_id),
    )
    if found is None:
        raise cs.Refusal(
            "unknown_segment", f"segment {segment_id} is not a segment of run {run_id}"
        )
    counted = tx.row(
        "SELECT COUNT(*) AS n FROM segments WHERE run_id = ? AND rowid <= ?",
        (run_id, found["rowid"]),
    )
    return 0 if counted is None else int(counted["n"])


def get_message(tx: cs.Tx, run_id: str, msg_id: str) -> sqlite3.Row:
    """Return a message of this run, or refuse ``unknown_msg``."""
    message = tx.row(
        "SELECT * FROM messages WHERE msg_id = ? AND run_id = ?", (msg_id, run_id)
    )
    if message is None:
        raise cs.Refusal("unknown_msg", f"run {run_id} has no message {msg_id}")
    return message


def existing_event(tx: cs.Tx, semantic_key: str) -> str | None:
    """Return the ``event_id`` of the event with this key, or None."""
    found = tx.row(
        "SELECT run_id, event_seq FROM outbox_events WHERE semantic_key = ?",
        (semantic_key,),
    )
    if found is None:
        return None
    return f"{found['run_id']}-{found['event_seq']}"


def insert_event(
    tx: cs.Tx,
    run_id: str,
    ordinal: int,
    kind: str,
    semantic_key: str,
    *,
    msg_id: str | None = None,
    decision_id: str | None = None,
    gate_id: str | None = None,
    text: str | None = None,
) -> tuple[str, bool]:
    """Insert one ``credits-outbox.v1`` event once; return its id and True when new."""
    payload = {
        "schema": "credits-outbox.v1",
        "semantic_key": semantic_key,
        "utc": tx.ctx.now_utc,
        "run_id": run_id,
        "segment": ordinal,
        "kind": kind,
        "msg_id": msg_id,
        "decision_id": decision_id,
        "gate_id": gate_id,
        "text": text,
    }
    cursor = tx.con.execute(
        "INSERT INTO outbox_events (run_id, kind, semantic_key, payload_json, created_utc)"
        " VALUES (?, ?, ?, ?, ?) ON CONFLICT (semantic_key) DO NOTHING",
        (
            run_id,
            kind,
            semantic_key,
            json.dumps(payload, sort_keys=True),
            tx.ctx.now_utc,
        ),
    )
    event_id = existing_event(tx, semantic_key)
    if event_id is None:
        raise cs.Refusal("event_missing", f"the event {semantic_key} was not stored")
    return event_id, cursor.rowcount == 1


def close_message(tx: cs.Tx, msg_id: str, reason: str) -> None:
    """Close an open message with ``reason``; a closed message stays as it is."""
    cursor = tx.con.execute(
        "UPDATE messages SET state = 'closed', closed_utc = ?, closed_reason = ?"
        " WHERE msg_id = ? AND state = 'open'",
        (tx.ctx.now_utc, reason, msg_id),
    )
    if cursor.rowcount == 1:
        tx.transition("message", msg_id, "open", "closed")


def body_field(message: sqlite3.Row, name: str) -> str | None:
    """Return one field of the message's stored document, or None."""
    try:
        doc: Any = json.loads(str(message["body_json"] or "{}"))
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    value: Any = doc.get(name)  # pyright: ignore[reportUnknownMemberType]
    return value if isinstance(value, str) else None


# --- verbs: messages, reports and gates (R§4.6.5) -------------------------------------------


def verb_ack(tx: cs.Tx, env: dict[str, str], msg_id: str, text: str) -> cs.Outcome:
    """Record receipt; close an ``info`` or ``query`` as ``done``; write ``ack:<msg_id>``."""
    run_id = env["CREDITS_RUN_ID"]
    get_run(tx, run_id)
    ordinal = segment_ordinal(tx, run_id, env["CREDITS_SEGMENT"])
    message = get_message(tx, run_id, msg_id)
    key = f"ack:{msg_id}"
    found = existing_event(tx, key)
    if found is not None:
        return cs.Outcome("no_change", {"msg_id": msg_id, "event_id": found})
    if message["acked_utc"] is None:
        tx.con.execute(
            "UPDATE messages SET acked_utc = ? WHERE msg_id = ? AND acked_utc IS NULL",
            (tx.ctx.now_utc, msg_id),
        )
    if message["kind"] in ACK_CLOSES_KINDS:
        close_message(tx, msg_id, "done")
    event_id, _ = insert_event(
        tx, run_id, ordinal, "ack", key, msg_id=msg_id, text=text
    )
    return cs.Outcome("changed", {"msg_id": msg_id, "event_id": event_id})


def verb_applied(tx: cs.Tx, env: dict[str, str], msg_id: str) -> cs.Outcome:
    """Record the effect of a ``stop-after-row`` or ``ruling``; write ``applied:<msg_id>``."""
    run_id = env["CREDITS_RUN_ID"]
    get_run(tx, run_id)
    ordinal = segment_ordinal(tx, run_id, env["CREDITS_SEGMENT"])
    message = get_message(tx, run_id, msg_id)
    kind = str(message["kind"])
    if kind not in APPLIED_KINDS:
        raise cs.Refusal(
            "kind_mismatch",
            f"applied names a stop-after-row or a ruling; {msg_id} is {kind}",
        )
    key = f"applied:{msg_id}"
    found = existing_event(tx, key)
    if found is not None:
        return cs.Outcome("no_change", {"msg_id": msg_id, "event_id": found})
    if message["applied_utc"] is None:
        tx.con.execute(
            "UPDATE messages SET applied_utc = ? WHERE msg_id = ? AND applied_utc IS NULL",
            (tx.ctx.now_utc, msg_id),
        )
    close_message(tx, msg_id, "applied")
    event_id, _ = insert_event(tx, run_id, ordinal, "applied", key, msg_id=msg_id)
    payload: dict[str, Any] = {"msg_id": msg_id, "event_id": event_id}
    gate_id = body_field(message, "gate_id")
    if kind == "ruling" and gate_id is not None:
        cursor = tx.con.execute(
            "UPDATE gates SET state = 'resolved', closed_utc = ?, closed_reason = 'ruling'"
            " WHERE gate_id = ? AND run_id = ? AND state = 'open'",
            (tx.ctx.now_utc, gate_id, run_id),
        )
        if cursor.rowcount == 1:
            tx.transition("gate", gate_id, "open", "resolved")
        resolved, _ = insert_event(
            tx,
            run_id,
            ordinal,
            "decision_resolved",
            f"decision_resolved:{gate_id}",
            msg_id=msg_id,
            decision_id=body_field(message, "decision_id"),
            gate_id=gate_id,
        )
        payload["decision_resolved_event_id"] = resolved
    return cs.Outcome("changed", payload)


def verb_report(tx: cs.Tx, env: dict[str, str], text: str) -> cs.Outcome:
    """Write one ``report`` event with a new ``report_id``."""
    run_id = env["CREDITS_RUN_ID"]
    get_run(tx, run_id)
    ordinal = segment_ordinal(tx, run_id, env["CREDITS_SEGMENT"])
    report_id = uuid.uuid4().hex
    event_id, _ = insert_event(
        tx, run_id, ordinal, "report", f"report:{report_id}", text=text
    )
    return cs.Outcome("changed", {"report_id": report_id, "event_id": event_id})


def gate_deadline(
    opened: datetime, wait_min: int, segment_deadline: str | None
) -> str | None:
    """Return the earlier of ``opened + wait_min`` and the segment deadline less 15 minutes."""
    if wait_min <= 0:
        return None
    deadline = opened + timedelta(minutes=wait_min)
    if segment_deadline:
        margin = cs.parse_utc(segment_deadline) - timedelta(
            minutes=GATE_DEADLINE_MARGIN_MIN
        )
        deadline = min(deadline, margin)
    return cs.format_utc(deadline)


def verb_decision(
    tx: cs.Tx,
    env: dict[str, str],
    config: dict[str, Any],
    decision_id: str,
    question: str,
) -> cs.Outcome:
    """Open the run's one gate and write the ``decision`` event."""
    run_id = env["CREDITS_RUN_ID"]
    segment_id = env["CREDITS_SEGMENT"]
    get_run(tx, run_id)
    ordinal = segment_ordinal(tx, run_id, segment_id)
    open_gate = tx.row(
        "SELECT gate_id FROM gates WHERE run_id = ? AND state = 'open'", (run_id,)
    )
    if open_gate is not None:
        raise cs.Refusal(
            "gate_open",
            f"run {run_id} has the open gate {open_gate['gate_id']}",
            gate_id=open_gate["gate_id"],
        )
    counted = tx.row("SELECT COUNT(*) AS n FROM gates WHERE run_id = ?", (run_id,))
    number = 1 + (0 if counted is None else int(counted["n"]))
    gate_id = f"g-{run_id}-{ordinal}-{number}"
    segment = tx.row(
        "SELECT segment_deadline_utc FROM segments WHERE segment_id = ?", (segment_id,)
    )
    deadline = gate_deadline(
        tx.ctx.now,
        int(config["gate_wait_max_min"]),
        None if segment is None else segment["segment_deadline_utc"],
    )
    tx.con.execute(
        "INSERT INTO gates (gate_id, run_id, segment_id, state, question, opened_utc,"
        " decision_id, deadline_utc) VALUES (?, ?, ?, 'open', ?, ?, ?, ?)",
        (gate_id, run_id, segment_id, question, tx.ctx.now_utc, decision_id, deadline),
    )
    tx.created("gate", gate_id, "open")
    event_id, _ = insert_event(
        tx,
        run_id,
        ordinal,
        "decision",
        f"decision:{gate_id}",
        decision_id=decision_id,
        gate_id=gate_id,
        text=question,
    )
    tx.effect(f"rescan:decision:{gate_id}", "rescan", gate_id)
    return cs.Outcome(
        "changed",
        {
            "gate_id": gate_id,
            "decision_id": decision_id,
            "deadline_utc": deadline,
            "event_id": event_id,
        },
    )


def pending_for_segment(con: sqlite3.Connection, run_id: str, segment_id: str) -> bool:
    """True when a message of the run waits for this segment's delivery generation.

    A ``ruling`` that was acked but not applied waits for each new generation
    too (R§10.2 M-5b), as in the inbox hook.
    """
    found = con.execute(
        "SELECT 1 FROM messages m WHERE m.run_id = ? AND m.state = 'open'"
        " AND (m.acked_utc IS NULL OR (m.kind = 'ruling' AND m.applied_utc IS NULL))"
        " AND NOT EXISTS (SELECT 1 FROM deliveries d"
        " WHERE d.msg_id = m.msg_id AND d.segment_id = ? AND d.emit_count > 0)",
        (run_id, segment_id),
    ).fetchone()
    return found is not None


def expire_gate(ctx: cs.Context, env: dict[str, str], gate_id: str) -> cs.Outcome:
    """Compare-and-set the gate from open to expired and write ``gate_expired``."""
    run_id = env["CREDITS_RUN_ID"]

    def body(tx: cs.Tx) -> cs.Outcome:
        ordinal = segment_ordinal(tx, run_id, env["CREDITS_SEGMENT"])
        cursor = tx.con.execute(
            "UPDATE gates SET state = 'expired', closed_utc = ?, closed_reason = 'deadline'"
            " WHERE gate_id = ? AND state = 'open'",
            (tx.ctx.now_utc, gate_id),
        )
        if cursor.rowcount != 1:
            return cs.Outcome(
                "no_change", {"status": "GATE_CLOSED", "gate_id": gate_id}
            )
        tx.transition("gate", gate_id, "open", "expired")
        event_id, _ = insert_event(
            tx,
            run_id,
            ordinal,
            "gate_expired",
            f"gate_expired:{gate_id}",
            gate_id=gate_id,
        )
        return cs.Outcome(
            "changed",
            {"status": "GATE_EXPIRED", "gate_id": gate_id, "event_id": event_id},
        )

    return cs.transact(ctx, body)


def clock_step_ms() -> int:
    """Return the ``CREDITS_TEST_CLOCK_STEP_MS`` seam (0 when unset)."""
    raw = os.environ.get(CLOCK_STEP_ENV)
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError as exc:
        raise cs.UsageError(f"{CLOCK_STEP_ENV}={raw!r} is not an integer") from exc
    if value < 0:
        raise cs.UsageError(f"{CLOCK_STEP_ENV}={raw!r} is below 0")
    return value


def warn_gate_deadline(run_id: str, gate_id: str, reason: str) -> None:
    """Log the one ``credits_limit_tripped`` WARN record of a lost deadline race."""
    cs.log(
        "credits_limit_tripped",
        level="WARN",
        window="gate_deadline",
        run_id=run_id,
        gate_id=gate_id,
        reason=reason,
    )


def ruling_won_race(con: sqlite3.Connection, run_id: str, now: datetime) -> str | None:
    """Return the run's last gate when a verified ruling closed it and its deadline has passed.

    The expiry of the wait lost the race to the ruling (R§4.6.3 "Expiry").
    """
    last = con.execute(
        "SELECT gate_id, deadline_utc, resolved_by_msg FROM gates WHERE run_id = ?"
        " ORDER BY opened_utc DESC, rowid DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if last is None or last["resolved_by_msg"] is None or last["deadline_utc"] is None:
        return None
    if cs.parse_utc(str(last["deadline_utc"])) > now:
        return None
    return str(last["gate_id"])


def verb_wait(
    ctx: cs.Context,
    env: dict[str, str],
    config: dict[str, Any],
    max_wait_ms: int | None,
    poll_ms: int | None,
) -> cs.Outcome:
    """Wait at the open gate for a message, the gate's end or the deadline (R§4.6.5).

    The wait returns within ``WAIT_MAX_S`` of store time: a seam only lowers the
    cap. Each poll checks, in order: no open gate (GATE_CLOSED), the deadline
    (the expiry compare-and-set: GATE_EXPIRED), a pending message
    (MESSAGE_WAITING), then the cap (WAIT_TIMEOUT with ``remaining_s``).
    """
    wait_min = int(config["gate_wait_max_min"])
    if wait_min == 0:
        raise cs.Refusal(
            "wait_disabled", "gate_wait_max_min is 0: the run does not wait at a gate"
        )
    run_id = env["CREDITS_RUN_ID"]
    segment_id = env["CREDITS_SEGMENT"]
    cap_s = min(WAIT_MAX_S * 1000, max_wait_ms or WAIT_MAX_S * 1000) / 1000.0
    poll_s = WAIT_POLL_S if poll_ms is None else poll_ms / 1000.0
    step_ms = clock_step_ms()
    began = time.monotonic()
    started = ctx.now
    polls = 0
    while True:
        elapsed = max(time.monotonic() - began, step_ms * polls / 1000.0)
        now = started + timedelta(seconds=elapsed)
        gate = ctx.con.execute(
            "SELECT gate_id, opened_utc, deadline_utc FROM gates"
            " WHERE run_id = ? AND state = 'open'",
            (run_id,),
        ).fetchone()
        if gate is None:
            won = ruling_won_race(ctx.con, run_id, now)
            if won is not None:
                warn_gate_deadline(run_id, won, "ruling_closed_the_gate")
            return cs.Outcome("ok", {"status": "GATE_CLOSED"})
        gate_id = str(gate["gate_id"])
        deadline_text = gate["deadline_utc"] or cs.format_utc(
            cs.parse_utc(str(gate["opened_utc"])) + timedelta(minutes=wait_min)
        )
        deadline = cs.parse_utc(str(deadline_text))
        if now >= deadline:
            ctx.now = now.replace(microsecond=0)
            expired = expire_gate(ctx, env, gate_id)
            if expired.payload.get("status") == "GATE_CLOSED":
                warn_gate_deadline(run_id, gate_id, "ruling_closed_the_gate")
            return expired
        if pending_for_segment(ctx.con, run_id, segment_id):
            return cs.Outcome("ok", {"status": "MESSAGE_WAITING", "gate_id": gate_id})
        remaining = (deadline - now).total_seconds()
        if elapsed >= cap_s:
            return cs.Outcome(
                "ok",
                {
                    "status": "WAIT_TIMEOUT",
                    "gate_id": gate_id,
                    "remaining_s": max(0, int(remaining)),
                },
            )
        time.sleep(min(poll_s, max(0.0, cap_s - elapsed)) if step_ms == 0 else poll_s)
        polls += 1


# --- git ------------------------------------------------------------------------------------


class GitError(Exception):
    """A git call failed."""


def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return the environment of a git call: no inherited repository overrides."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROPPED}
    env.update(extra or {})
    return env


def git(repo: Path, args: Sequence[str], extra: dict[str, str] | None = None) -> bytes:
    """Run one git command in ``repo`` and return its stdout bytes."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            env=git_env(extra),
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git {' '.join(args[:3])}: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(args[:3])} exit {proc.returncode}: {detail}")
    return proc.stdout


def git_text(
    repo: Path, args: Sequence[str], extra: dict[str, str] | None = None
) -> str:
    """Run one git command and return its stripped text."""
    return git(repo, args, extra).decode("utf-8", "replace").strip()


def z_split(data: bytes) -> list[str]:
    """Split NUL-terminated git output into paths."""
    return [part.decode("utf-8", "replace") for part in data.split(b"\0") if part]


def snapshot(repo: Path, base: str = "HEAD", drop: Sequence[str] = ()) -> str:
    """Return the tree of the tracked and untracked files that are not ignored.

    A temporary index seeded from ``base`` holds the work, so the repository's
    own index never changes (R§4.3 step 4, the helper's rules). ``drop`` names the
    executor worktree's links, which never enter a tree (as the helper's baseline).
    """
    with tempfile.TemporaryDirectory(prefix="credits-msg-") as scratch:
        extra = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(repo, ["read-tree", base], extra)
        git(repo, [*EOL_PIN, "add", "-A", "--", "."], extra)
        if drop:
            git(
                repo,
                ["rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", *drop],
                extra,
            )
        return git_text(repo, ["write-tree"], extra)


def tree_blobs(repo: Path, tree: str) -> dict[str, str]:
    """Return every file path of ``tree`` with its object id."""
    blobs: dict[str, str] = {}
    for entry in z_split(git(repo, ["ls-tree", "-r", "-z", "--full-tree", tree])):
        meta, _, path = entry.partition("\t")
        fields = meta.split()
        if len(fields) == 3:
            blobs[path] = fields[2]
    return blobs


def diff_paths(repo: Path, old: str, new: str) -> set[str]:
    """Return every path whose entry differs between two trees."""
    out = git(repo, ["diff-tree", "-r", "-z", "--no-renames", "--name-only", old, new])
    return set(z_split(out))


def pin(repo: Path, run_id: str, name: str, tree: str) -> None:
    """Pin ``tree`` as ``refs/credits/<run_id>/<name>``."""
    git(repo, ["update-ref", f"refs/credits/{run_id}/{name}", tree])


def is_closeout(path: str, closeout: Sequence[str]) -> bool:
    """True when ``path`` is a closeout path: a named file or a path under a named folder."""
    for entry in closeout:
        if entry.endswith("/"):
            if path.startswith(entry):
                return True
        elif path == entry:
            return True
    return False


def joined(paths: set[str] | list[str]) -> str:
    """Return the sorted paths as one comma-separated text."""
    return ",".join(sorted(paths))


# --- verbs: tree, capture and seal (R§4.3, R§5.4) -------------------------------------------


def repo_root(path: str) -> Path:
    """Return the top folder of the git tree that holds ``path``."""
    target = Path(path)
    if not target.is_dir():
        raise cs.Refusal("tree_not_found", f"{path} is not a folder")
    try:
        return Path(git_text(target, ["rev-parse", "--show-toplevel"])).resolve()
    except GitError as exc:
        raise cs.Refusal("tree_not_git", f"{path} is not in a git tree: {exc}") from exc


def worktree_facts(repo: Path) -> tuple[Path, dict[str, Any] | None]:
    """(main tree, helper manifest) of the git tree at ``repo`` (R§5.4).

    A main tree is its own main tree and has no manifest; a linked worktree names the
    main tree through its common git folder, and the manifest is None when the helper
    did not make it (or its manifest cannot be read).
    """
    git_dir = Path(git_text(repo, ["rev-parse", "--path-format=absolute", "--git-dir"]))
    common = Path(
        git_text(repo, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    )
    if git_dir.resolve() == common.resolve():
        return repo, None
    main = common.parent.resolve()
    try:
        raw: Any = json.loads((git_dir / WORKTREE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return main, None
    if not isinstance(raw, dict):
        return main, None
    helper: dict[str, Any] = {str(k): v for k, v in raw.items()}  # pyright: ignore[reportUnknownVariableType]
    slug, links, carry = helper.get("slug"), helper.get("links"), helper.get("carry")
    if (
        not isinstance(slug, str)
        or not slug
        or not isinstance(links, list)
        or not isinstance(carry, list)
        or not all(isinstance(e, str) for e in [*links, *carry])  # pyright: ignore[reportUnknownVariableType]
    ):
        return main, None
    return main, helper


def under(path: str, entries: Sequence[str]) -> bool:
    """True when ``path`` is a named entry or sits under a named folder."""
    for entry in entries:
        stem = entry.rstrip("/")
        if stem and (path == stem or path.startswith(stem + "/")):
            return True
    return False


def prerequisite_paths(ctx: cs.Context, doc: dict[str, Any], run_id: str) -> set[str]:
    """D: every landing path of every predecessor in the run's ``depends_on``."""
    paths: set[str] = set()
    for predecessor, _ in cs.parse_depends_on(doc.get("depends_on", []), run_id):
        for row in ctx.con.execute(
            "SELECT path FROM landings WHERE run_id = ?", (predecessor,)
        ):
            paths.add(str(row["path"]))
    return paths


def check_base(
    repo: Path,
    base: str,
    carried: Sequence[str] = (),
    permitted: Callable[[str], bool] | None = None,
    prerequisites: set[str] | None = None,
) -> list[dict[str, str]]:
    """Run the R§4.3 checks (a) and (b) and return the carry manifest of check (c).

    In an executor worktree (``permitted`` given) the helper's carried files join the
    status files. A carried file that differs from B is a successor input only when it
    is outside D (``prerequisites``) and is a status file or ``permitted``; any other
    is ``base_carry_mismatch`` (R§5.4.3, MX-37).
    """
    try:
        want = git_text(
            repo, ["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"]
        )
    except GitError as exc:
        raise cs.Refusal("base_moved", f"the base {base} is not a commit") from exc
    head = git_text(repo, ["rev-parse", "HEAD"])
    if head != want:
        raise cs.Refusal("base_moved", f"HEAD is {head}, not the base {want}")
    status = git(
        repo,
        [
            *EOL_PIN,
            "status",
            "--porcelain",
            "-z",
            "--no-renames",
            "--untracked-files=no",
        ],
    )
    changed = {entry[3:] for entry in z_split(status) if len(entry) > 3}
    stray = {path for path in changed if path not in STATUS_FILES} - set(carried)
    if stray:
        raise cs.Refusal(
            f"base_content_mismatch:{joined(stray)}",
            "a tracked path that is not carried differs from the base",
            paths=sorted(stray),
        )
    base_blobs = tree_blobs(repo, want)
    work = tree_blobs(repo, snapshot(repo, want))
    manifest: list[dict[str, str]] = []
    mismatch: set[str] = set()
    paths = [*STATUS_FILES, *sorted(set(carried) - set(STATUS_FILES))]
    for path in paths:
        blob = work.get(path, ABSENT)
        if blob == ABSENT and path not in base_blobs:
            continue
        if base_blobs.get(path, ABSENT) == blob:
            kind = "equal_to_base"
        elif permitted is None:
            kind = "successor_input"
        elif path in (prerequisites or set()) or not (
            path in STATUS_FILES or permitted(path)
        ):
            mismatch.add(path)
            continue
        else:
            kind = "successor_input"
        manifest.append({"path": path, "blob": blob, "class": kind})
    if mismatch:
        raise cs.Refusal(
            f"base_carry_mismatch:{joined(mismatch)}",
            "a carried file differs from B and is not a permitted successor input",
            paths=sorted(mismatch),
        )
    return manifest


def verb_tree(ctx: cs.Context, env: dict[str, str], path: str) -> cs.Outcome:
    """Check the base, pin the start tree S and record it with the carry manifest.

    An executor-worktree run (R§5.4) needs the helper's worktree and B. Its carried
    files are checked against D and the permitted inputs, and its first S must equal
    the helper's baseline tree (``start_tree_mismatch``). Every check runs before any
    pin or write; the refs are pinned in the main tree, which the run records.

    These are the checks of the first start. A run that has fixed B and pinned S
    continues through ``tree_continue`` (R1-F4).
    """
    run_id = env["CREDITS_RUN_ID"]
    segment_id = env["CREDITS_SEGMENT"]
    repo = repo_root(path)
    base = os.environ.get("CREDITS_BASE_COMMIT") or None
    found = ctx.con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if found is None:
        raise cs.Refusal("unknown_run", f"no run {run_id}")
    doc = cs.manifest_doc(found)
    if found["base_fixed"] == 1 and found["start_tree"] is not None:
        return tree_continue(ctx, env, found, doc, repo, base)
    try:
        main = repo
        links: list[str] = []
        if doc.get("executor_worktree") is True:
            main, helper = worktree_facts(repo)
            if helper is None:
                raise cs.Refusal(
                    "worktree_required",
                    f"run {run_id} runs in an executor worktree; {repo} is not one",
                )
            if not base:
                raise cs.Refusal(
                    "base_required",
                    "an executor-worktree run needs CREDITS_BASE_COMMIT",
                )
            links = [str(e) for e in helper["links"]]
            allowed = [str(e) for e in doc.get("carry_allowed", [])]
            folder = str(doc.get("plan_folder") or "")
            manifest = check_base(
                repo,
                base,
                carried=[str(e) for e in helper["carry"]],
                permitted=lambda rel: under(rel, [*allowed, folder]),
                prerequisites=prerequisite_paths(ctx, doc, run_id),
            )
            start = snapshot(repo, drop=links)
            if found["start_tree"] is None:
                ref = f"{WORKTREE_REF_PREFIX}{helper['slug']}^{{tree}}"
                try:
                    baseline = git_text(main, ["rev-parse", "--verify", ref])
                except GitError:
                    baseline = ""
                if start != baseline:
                    raise cs.Refusal(
                        "start_tree_mismatch",
                        "the worktree's start tree is not the helper's baseline tree",
                        start_tree=start,
                        baseline=baseline or None,
                    )
        else:
            manifest = check_base(repo, base) if base else None
            start = snapshot(repo)
    except GitError as exc:
        raise cs.Refusal("git_failed", str(exc)) from exc

    def body(tx: cs.Tx) -> cs.Outcome:
        run = get_run(tx, run_id)
        segment_ordinal(tx, run_id, segment_id)
        sets: dict[str, Any] = {"active_tree": str(repo), "main_tree": str(main)}
        kept = run["start_tree"]
        if kept is None:
            sets["start_tree"] = start
        if base:
            sets["base_commit"] = base
            sets["base_fixed"] = 1
        changed = any(run[name] != value for name, value in sets.items())
        if changed:
            assignments = ", ".join(f"{name} = ?" for name in sets)
            tx.con.execute(
                f"UPDATE runs SET {assignments}, updated_utc = ? WHERE run_id = ?",
                (*sets.values(), tx.ctx.now_utc, run_id),
            )
        if manifest is not None:
            text = json.dumps(manifest, sort_keys=True)
            cursor = tx.con.execute(
                "UPDATE segments SET carry_manifest_json = ?, updated_utc = ?"
                " WHERE segment_id = ? AND (carry_manifest_json IS NOT ?)",
                (text, tx.ctx.now_utc, segment_id, text),
            )
            changed = changed or cursor.rowcount == 1
        return cs.Outcome(
            "changed" if changed else "no_change",
            {
                "active_tree": str(repo),
                "start_tree": kept or start,
                "carry_manifest": manifest,
            },
        )

    try:
        if run_start_tree(ctx, run_id) is None:
            pin(main, run_id, "start", start)
    except GitError as exc:
        raise cs.Refusal("git_failed", str(exc)) from exc
    return cs.transact(ctx, body)


def same_path(path: Path, recorded: object) -> bool:
    """True when ``recorded`` names the folder ``path`` (case and separators folded)."""
    if recorded is None:
        return False
    return os.path.normcase(os.path.normpath(str(path))) == os.path.normcase(
        os.path.normpath(str(recorded))
    )


def tree_continue(
    ctx: cs.Context,
    env: dict[str, str],
    found: sqlite3.Row,
    doc: dict[str, Any],
    repo: Path,
    base: str | None,
) -> cs.Outcome:
    """Continue a run that has fixed B and pinned S (AC-F.2, AC-G.2; R1-F4).

    The tree now holds the run's own retained work, so the first-start checks do not
    apply: no content check (b), no carry check (c) and no baseline check. B, S and
    the recorded carry manifest stay. The checks: HEAD is still B (``base_moved``),
    ``CREDITS_BASE_COMMIT`` names the fixed B (``base_fixed``), the tree is the
    recorded one (``active_tree_mismatch``) and the pinned start ref is S
    (``start_ref_mismatch``; a missing ref is pinned again).
    """
    run_id = env["CREDITS_RUN_ID"]
    segment_id = env["CREDITS_SEGMENT"]
    fixed = str(found["base_commit"])
    start = str(found["start_tree"])
    ref = f"refs/credits/{run_id}/start"
    try:
        main = repo
        if doc.get("executor_worktree") is True:
            main, helper = worktree_facts(repo)
            if helper is None:
                raise cs.Refusal(
                    "worktree_required",
                    f"run {run_id} runs in an executor worktree; {repo} is not one",
                )
            if not base:
                raise cs.Refusal(
                    "base_required",
                    "an executor-worktree run needs CREDITS_BASE_COMMIT",
                )
        if not same_path(repo, found["active_tree"]) or not same_path(
            main, found["main_tree"]
        ):
            raise cs.Refusal(
                "active_tree_mismatch",
                f"run {run_id} works in {found['active_tree']}, not {repo}",
                active_tree=found["active_tree"],
            )
        try:
            want = git_text(
                repo, ["rev-parse", "--verify", "--quiet", f"{fixed}^{{commit}}"]
            )
        except GitError as exc:
            raise cs.Refusal(
                "base_moved", f"the fixed base {fixed} is not a commit"
            ) from exc
        if base:
            try:
                given = git_text(
                    repo, ["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"]
                )
            except GitError:
                given = ""
            if given != want:
                raise cs.Refusal(
                    "base_fixed", f"run {run_id} is fixed at {fixed}, not {base}"
                )
        head = git_text(repo, ["rev-parse", "HEAD"])
        if head != want:
            raise cs.Refusal("base_moved", f"HEAD is {head}, not the base {want}")
        try:
            pinned = git_text(
                main, ["rev-parse", "--verify", "--quiet", f"{ref}^{{tree}}"]
            )
        except GitError:
            pinned = ""
        if pinned and pinned != start:
            raise cs.Refusal(
                "start_ref_mismatch",
                f"{ref} names {pinned}, not the start tree {start}",
                start_tree=start,
                pinned=pinned,
            )
        if not pinned:
            pin(main, run_id, "start", start)
    except GitError as exc:
        raise cs.Refusal("git_failed", str(exc)) from exc

    def body(tx: cs.Tx) -> cs.Outcome:
        get_run(tx, run_id)
        segment_ordinal(tx, run_id, segment_id)
        first = tx.row(
            "SELECT carry_manifest_json FROM segments WHERE run_id = ?"
            " AND carry_manifest_json IS NOT NULL ORDER BY rowid LIMIT 1",
            (run_id,),
        )
        if first is None:
            raise cs.Refusal(
                "carry_manifest_missing",
                f"run {run_id} has a fixed base but no recorded carry manifest",
            )
        text = str(first["carry_manifest_json"])
        cursor = tx.con.execute(
            "UPDATE segments SET carry_manifest_json = ?, updated_utc = ?"
            " WHERE segment_id = ? AND (carry_manifest_json IS NOT ?)",
            (text, tx.ctx.now_utc, segment_id, text),
        )
        manifest: Any = json.loads(text)
        return cs.Outcome(
            "changed" if cursor.rowcount == 1 else "no_change",
            {"active_tree": str(repo), "start_tree": start, "carry_manifest": manifest},
        )

    return cs.transact(ctx, body)


def run_start_tree(ctx: cs.Context, run_id: str) -> str | None:
    """Return the run's pinned start tree, or None (refuse an unknown run)."""
    run = ctx.con.execute(
        "SELECT start_tree FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if run is None:
        raise cs.Refusal("unknown_run", f"no run {run_id}")
    return None if run["start_tree"] is None else str(run["start_tree"])


def read_changed_files(path: str) -> set[str]:
    """Read the handoff's changed-file list: one repository-relative path per line."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise cs.Refusal(
            "changed_files_unreadable", f"the list {path} cannot be read: {exc}"
        ) from exc
    listed: set[str] = set()
    for line in text.splitlines():
        if line.strip():
            try:
                listed.add(_arg_rel(line))
            except argparse.ArgumentTypeError as exc:
                raise cs.Refusal("changed_files_invalid", str(exc)) from exc
    return listed


def verb_capture(
    ctx: cs.Context, env: dict[str, str], changed_files: str, closeout: list[str]
) -> cs.Outcome:
    """Capture the product part: the inventory and its blobs (R§5.4.1).

    A main-tree run's landed tree L is its tree now. An executor-worktree run's L is the
    helper's landed tree; the main tree must hold L's blob on every product path
    (``capture_main_mismatch``), and its tree now is the capture tree C that the seal
    compares with. Both refs are pinned in the main tree.
    """
    run_id = env["CREDITS_RUN_ID"]
    run = ctx.con.execute(
        "SELECT active_tree, start_tree, capture_tree, main_tree FROM runs"
        " WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        raise cs.Refusal("unknown_run", f"no run {run_id}")
    if run["start_tree"] is None or run["active_tree"] is None:
        raise cs.Refusal("no_start_tree", "run tree before the capture")
    active = Path(str(run["active_tree"]))
    repo = Path(str(run["main_tree"] or run["active_tree"]))
    in_worktree = str(repo) != str(active)
    start = str(run["start_tree"])
    listed = {
        p for p in read_changed_files(changed_files) if not is_closeout(p, closeout)
    }
    try:
        if in_worktree:
            if not active.is_dir():
                raise cs.Refusal(
                    "worktree_missing",
                    f"the worktree {active} is gone before the capture",
                )
            _, helper = worktree_facts(active)
            if helper is None:
                raise cs.Refusal(
                    "worktree_required", f"{active} is not the run's worktree"
                )
            ref = f"{WORKTREE_REF_PREFIX}{helper['slug']}^{{tree}}"
            landed = git_text(repo, ["rev-parse", "--verify", ref])
            capture = snapshot(repo)
            main_blobs = tree_blobs(repo, capture)
        else:
            landed = capture = snapshot(repo)
            main_blobs = {}
        diff = {
            p for p in diff_paths(repo, start, landed) if not is_closeout(p, closeout)
        }
        blobs = tree_blobs(repo, landed)
    except GitError as exc:
        raise cs.Refusal("git_failed", str(exc)) from exc
    unlisted = diff - listed
    not_changed = listed - diff
    if unlisted or not_changed:
        raise cs.Refusal(
            f"capture_inventory_mismatch:{joined(unlisted | not_changed)}",
            "the changed-file list must equal the start-to-landed diff less the closeout set",
            unlisted=sorted(unlisted),
            not_in_diff=sorted(not_changed),
        )
    if in_worktree:
        off = {path for path in diff if main_blobs.get(path) != blobs.get(path)}
        if off:
            raise cs.Refusal(
                f"capture_main_mismatch:{joined(off)}",
                "the main tree does not hold the landed blob of a product path",
                paths=sorted(off),
            )
    rows = {path: blobs.get(path, DELETED) for path in diff}

    def body(tx: cs.Tx) -> cs.Outcome:
        segment_ordinal(tx, run_id, env["CREDITS_SEGMENT"])
        current = tx.row("SELECT capture_tree FROM runs WHERE run_id = ?", (run_id,))
        stored = {
            str(r["path"]): str(r["blob"])
            for r in tx.rows(
                "SELECT path, blob FROM landings WHERE run_id = ? AND part = 'product'",
                (run_id,),
            )
        }
        if current is not None and current["capture_tree"] is not None:
            if stored == rows:
                return cs.Outcome(
                    "no_change", {"capture_tree": current["capture_tree"]}
                )
            raise cs.Refusal(
                "product_part_exists", f"run {run_id} has a different product part"
            )
        for path, blob in sorted(rows.items()):
            tx.con.execute(
                "INSERT INTO landings (run_id, part, path, blob) VALUES (?, 'product', ?, ?)",
                (run_id, path, blob),
            )
        tx.con.execute(
            "UPDATE runs SET landed_tree = ?, capture_tree = ?, closeout_paths_json = ?,"
            " updated_utc = ? WHERE run_id = ?",
            (landed, capture, json.dumps(sorted(closeout)), tx.ctx.now_utc, run_id),
        )
        return cs.Outcome(
            "changed",
            {"landed_tree": landed, "capture_tree": capture, "paths": sorted(rows)},
        )

    try:
        pin(repo, run_id, "landed", landed)
        pin(repo, run_id, "capture", capture)
    except GitError as exc:
        raise cs.Refusal("git_failed", str(exc)) from exc
    return cs.transact(ctx, body)


def verb_seal(ctx: cs.Context, env: dict[str, str]) -> cs.Outcome:
    """Seal the closeout part: every product row holds, only closeout paths changed (R§5.4.2).

    The seal reads the main tree, so an executor-worktree run seals after its worktree
    is removed (MX-36).
    """
    run_id = env["CREDITS_RUN_ID"]
    run = ctx.con.execute(
        "SELECT active_tree, main_tree, capture_tree, closeout_paths_json FROM runs"
        " WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        raise cs.Refusal("unknown_run", f"no run {run_id}")
    if run["capture_tree"] is None or run["active_tree"] is None:
        raise cs.Refusal("no_product_part", "the seal needs the product part")
    repo = Path(str(run["main_tree"] or run["active_tree"]))
    capture = str(run["capture_tree"])
    closeout = [str(p) for p in json.loads(str(run["closeout_paths_json"] or "[]"))]
    product = {
        str(r["path"]): str(r["blob"])
        for r in ctx.con.execute(
            "SELECT path, blob FROM landings WHERE run_id = ? AND part = 'product'",
            (run_id,),
        )
    }
    try:
        now_tree = snapshot(repo)
        blobs = tree_blobs(repo, now_tree)
        moved = diff_paths(repo, capture, now_tree)
    except GitError as exc:
        raise cs.Refusal("git_failed", str(exc)) from exc
    changed = {
        path for path, blob in product.items() if blobs.get(path, DELETED) != blob
    }
    if changed:
        raise cs.Refusal(
            f"product_changed_after_land:{joined(changed)}",
            "a captured product path differs from its stored row",
            paths=sorted(changed),
        )
    added = {path for path in moved if not is_closeout(path, closeout)}
    if added:
        raise cs.Refusal(
            f"path_added_after_land:{joined(added)}",
            "a path outside the closeout set changed after the capture",
            paths=sorted(added),
        )
    rows: dict[str, str] = {}
    for entry in closeout:
        if entry.endswith("/"):
            rows.update({p: b for p, b in blobs.items() if p.startswith(entry)})
        else:
            rows[entry] = blobs.get(entry, ABSENT)

    def body(tx: cs.Tx) -> cs.Outcome:
        stored = {
            str(r["path"]): str(r["blob"])
            for r in tx.rows(
                "SELECT path, blob FROM landings WHERE run_id = ? AND part = 'closeout'",
                (run_id,),
            )
        }
        if stored:
            if stored == rows:
                return cs.Outcome("no_change", {"sealed_tree": now_tree})
            raise cs.Refusal(
                "closeout_changed_after_seal",
                f"run {run_id} is sealed and a closeout path changed",
            )
        for path, blob in sorted(rows.items()):
            tx.con.execute(
                "INSERT INTO landings (run_id, part, path, blob, sealed_utc)"
                " VALUES (?, 'closeout', ?, ?, ?)",
                (run_id, path, blob, tx.ctx.now_utc),
            )
        return cs.Outcome("changed", {"sealed_tree": now_tree, "paths": sorted(rows)})

    try:
        pin(repo, run_id, "sealed", now_tree)
    except GitError as exc:
        raise cs.Refusal("git_failed", str(exc)) from exc
    return cs.transact(ctx, body)


# --- main -----------------------------------------------------------------------------------


# --- authority (EA-90) ----------------------------------------------------------------------

# The request states of a live segment: the launcher sets the environment before it records
# ``launched``, so a session may read its record while the request is still ``admitted``.
AUTHORITY_REQUEST_STATES = frozenset({"admitted", "launched"})


def chain_authorization(run: sqlite3.Row) -> dict[str, Any] | None:
    """Return the manifest chain's ``chain_id``, ``quote`` and ``given_at``, or None."""
    try:
        loaded: Any = json.loads(str(run["manifest_json"] or "{}"))
    except ValueError as exc:
        raise cs.Refusal(
            "manifest_invalid", f"the run's manifest is not JSON: {exc}"
        ) from exc
    doc = cs.as_dict(loaded)
    chain = None if doc is None else cs.as_dict(doc.get("chain"))
    if chain is None:
        return None
    return {key: chain.get(key) for key in ("chain_id", "quote", "given_at")}


def authority_record(
    tx: cs.Tx, run_id: str, segment_id: str, quote: str | None
) -> dict[str, Any]:
    """Follow segment → attempt → request and return the start record, or refuse."""
    run = get_run(tx, run_id)
    ordinal = segment_ordinal(tx, run_id, segment_id)
    segment = tx.row(
        "SELECT request_id, attempt_id, finalized_utc FROM segments"
        " WHERE segment_id = ? AND run_id = ?",
        (segment_id, run_id),
    )
    if segment is None:
        raise cs.Refusal(
            "unknown_segment", f"segment {segment_id} is not a segment of run {run_id}"
        )
    if segment["request_id"] is None or segment["attempt_id"] is None:
        raise cs.Refusal(
            "authority_no_request",
            f"segment {segment_id} has no start request (a manual run)",
        )
    if segment["finalized_utc"] is not None:
        raise cs.Refusal("authority_segment_ended", f"segment {segment_id} has ended")
    attempt = tx.row(
        "SELECT request_id, dispatch_id FROM attempts WHERE attempt_id = ? AND run_id = ?",
        (segment["attempt_id"], run_id),
    )
    if attempt is None or attempt["request_id"] != segment["request_id"]:
        raise cs.Refusal(
            "authority_link_mismatch",
            f"segment {segment_id} and its attempt name different start requests",
        )
    request = tx.row(
        "SELECT * FROM requests WHERE request_id = ? AND run_id = ?",
        (segment["request_id"], run_id),
    )
    if request is None:
        raise cs.Refusal(
            "authority_no_request",
            f"the start request of segment {segment_id} is not in the store",
        )
    state = str(request["state"])
    if state not in AUTHORITY_REQUEST_STATES:
        raise cs.Refusal(
            "authority_not_launched",
            f"the start request {request['request_id']} is {state}",
            request_state=state,
        )
    started_by = str(request["started_by"])
    recorded = request["start_quote"]
    if started_by == "agent-on-user-chat" and not recorded:
        raise cs.Refusal(
            "authority_no_quote",
            "an agent-on-user-chat start request carries no quote of the user's words",
        )
    checked = False
    if quote is not None:
        if recorded is None or cs.normalize_text(str(recorded)) != cs.normalize_text(
            quote
        ):
            raise cs.Refusal(
                "authority_quote_mismatch",
                "the given words are not the quote of the start request",
            )
        checked = True
    return {
        "authorized": True,
        "run_id": run_id,
        "segment_id": segment_id,
        "segment_ordinal": ordinal,
        "request_id": str(request["request_id"]),
        "request_state": state,
        "attempt_id": str(segment["attempt_id"]),
        "dispatch_id": attempt["dispatch_id"],
        "started_by": started_by,
        "quote": recorded,
        "requested_by": request["requested_by"],
        "chain": chain_authorization(run) if started_by == "monitor-chain" else None,
        "resume": bool(request["resume"]),
        "resume_mode": request["resume_mode"],
        "brief": request["brief"],
        "requested_utc": request["created_utc"],
        "quote_checked": checked,
    }


def verb_authority(
    ctx: cs.Context, env: dict[str, str], quote: str | None
) -> cs.Outcome:
    """Show the start request that launched this segment, in one read transaction.

    The store is open with ``mode=ro`` and the transaction ends with ROLLBACK, so the
    verb writes nothing. The human's start or resume words reach a headless run here,
    as the record the launcher consumed, not as text in its prompt (EA-89, D-14 B).
    """
    ctx.con.execute("BEGIN")
    try:
        payload = authority_record(
            cs.Tx(ctx), env["CREDITS_RUN_ID"], env["CREDITS_SEGMENT"], quote
        )
    finally:
        ctx.con.execute("ROLLBACK")
    return cs.Outcome("ok", payload)


# --- locate (read only; R§4.6.3) ------------------------------------------------------------


def claude_dir() -> Path:
    """The CLI's config folder: ``CLAUDE_CONFIG_DIR``, else ``~/.claude`` (as the verifier)."""
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    if config:
        return Path(config)
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    return (Path(home) if home else Path.home()) / ".claude"


def session_transcript(session: str) -> Path:
    """Return the one ``projects/<slug>/<session>.jsonl``, or refuse."""
    projects = claude_dir() / "projects"
    found = sorted(projects.glob(f"*/{session}.jsonl")) if projects.is_dir() else []
    found = [path for path in found if path.is_file()]
    if not found:
        raise cs.Refusal(
            "transcript_missing",
            f"no transcript of session {session} under {projects}",
        )
    if len(found) > 1:
        raise cs.Refusal(
            "transcript_ambiguous",
            f"session {session} has {len(found)} transcripts",
            transcripts=[str(path) for path in found],
        )
    return found[0]


def verb_locate(session: str, quote: str) -> cs.Outcome:
    """Propose the uuid of the typed human entry whose text is ``quote`` (R§4.6.3).

    A candidate is a typed human entry of the session (step 4) whose normalized full
    text equals the normalized quote (step 6). The verb reads the transcript only. It
    opens no store and writes nothing. It only proposes: the inbox hook checks the
    named entry again, so a wrong pick fails closed.
    """
    path = session_transcript(session)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise cs.Refusal("transcript_unreadable", f"cannot read {path}: {exc}") from exc
    want = cs.normalize_text(quote)
    candidates: list[dict[str, Any]] = []
    for line in cs.parse_lines(data):
        record = line.record
        uid = record.get("uuid")
        if not (
            isinstance(uid, str)
            and uid
            and cs.is_human_entry(record, session)
            and cs.is_typed_turn(record)
        ):
            continue
        text = cs.text_blocks(cs.message_content(record))
        if text is None or cs.normalize_text(text) != want:
            continue
        candidates.append(
            {
                "user_message_uuid": uid,
                "prompt_id": record.get("promptId"),
                "timestamp": record.get("timestamp"),
                "line": line.number,
            }
        )
    if not candidates:
        raise cs.Refusal(
            "not_found",
            f"no typed entry of session {session} has the quoted text",
            transcript=str(path),
        )
    if len(candidates) > 1:
        raise cs.Refusal(
            "ambiguous",
            f"{len(candidates)} typed entries of session {session} have the quoted text",
            transcript=str(path),
            candidates=candidates,
        )
    return cs.Outcome(
        "ok", {"session": session, "transcript": str(path), **candidates[0]}
    )


def main_locate(args: argparse.Namespace) -> int:
    """Run ``locate``: no ``CREDITS_*`` value, no config and no store."""
    try:
        outcome = verb_locate(args.session, args.quote)
    except cs.Refusal as exc:
        return cs.emit({**exc.payload(), "verb": "locate"}, cs.EXIT_REFUSED)
    return cs.emit(
        {"result": outcome.result, "verb": "locate", **outcome.payload}, cs.EXIT_OK
    )


def run_verb(
    ctx: cs.Context, args: argparse.Namespace, env: dict[str, str]
) -> cs.Outcome:
    """Dispatch one verb."""
    verb = str(args.verb)
    if verb == "ack":
        return cs.transact(ctx, lambda tx: verb_ack(tx, env, args.msg_id, args.text))
    if verb == "applied":
        return cs.transact(ctx, lambda tx: verb_applied(tx, env, args.msg_id))
    if verb == "report":
        return cs.transact(ctx, lambda tx: verb_report(tx, env, args.text))
    if verb == "decision":
        config = load_config()
        return cs.transact(
            ctx,
            lambda tx: verb_decision(tx, env, config, args.decision_id, args.question),
        )
    if verb == "wait":
        return verb_wait(ctx, env, load_config(), args.max_wait_ms, args.poll_ms)
    if verb == "tree":
        return verb_tree(ctx, env, args.path)
    if verb == "landing":
        if args.part == "product":
            return verb_capture(ctx, env, args.changed_files, args.closeout)
        return verb_seal(ctx, env)
    if verb == "authority":
        return verb_authority(ctx, env, args.quote)
    raise cs.UsageError(f"unknown verb {verb!r}")


def check_landing_args(args: argparse.Namespace) -> None:
    """The path flags belong to the product part, which needs both."""
    if args.verb != "landing":
        return
    if args.part == "closeout" and (args.changed_files or args.closeout):
        raise cs.UsageError("--changed-files and --closeout belong to --part product")
    if args.part == "product" and (not args.changed_files or not args.closeout):
        raise cs.UsageError("--part product needs --changed-files and --closeout")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one verb and return the exit code."""
    try:
        args = build_parser().parse_args(argv)
        check_landing_args(args)
        if args.verb == "locate":
            return main_locate(args)
        env = require_env()
        crash_at = parse_msg_crash(os.environ.get("CREDITS_TEST_CRASH_AT"))
        busy_ms = cs.busy_timeout_ms("cli")
        now = (
            cs.parse_utc(args.now_utc)
            if args.now_utc
            else datetime.now(UTC).replace(microsecond=0)
        )
    except cs.UsageError as exc:
        return cs.emit(
            {"result": "usage_error", "error": "usage", "message": str(exc)},
            cs.EXIT_USAGE,
        )
    verb = str(args.verb)
    db = env["CREDITS_STATE_DB"]
    if not Path(db).is_file():
        return cs.emit(
            {
                "result": "refused",
                "error": "store_missing",
                "message": f"no store at {db}",
            },
            cs.EXIT_REFUSED,
        )
    reason = cs.store_not_local_reason(db)
    if reason is not None:
        return cs.emit(
            {"result": "refused", "error": "store_not_local", "message": reason},
            cs.EXIT_REFUSED,
        )
    con: sqlite3.Connection | None = None
    try:
        con = (
            cs.open_store_read_only(db, busy_ms)
            if verb == "authority"
            else cs.open_store(db, busy_ms)
        )
        version = cs.user_version(con)
        if version != cs.SCHEMA_VERSION:
            return cs.emit(
                {
                    "result": "refused",
                    "error": "schema_mismatch",
                    "message": f"store schema {version} is not {cs.SCHEMA_VERSION}",
                },
                cs.EXIT_REFUSED,
            )
        ctx = cs.Context(
            con=con,
            db=Path(db),
            verb=verb,
            profile="cli",
            now=now,
            crash_at=crash_at,
            busy_tries=cs.BUSY_TRIES["cli"],
        )
        outcome = run_verb(ctx, args, env)
        payload = {"result": outcome.result, "verb": verb, **outcome.payload}
        return cs.emit(payload, cs.EXIT_OK)
    except cs.UsageError as exc:
        return cs.emit(
            {"result": "usage_error", "error": "usage", "message": str(exc)},
            cs.EXIT_USAGE,
        )
    except cs.Refusal as exc:
        return cs.emit({**exc.payload(), "verb": verb}, cs.EXIT_REFUSED)
    except cs.StoreBusy as exc:
        cs.log("store_busy_exit", verb=verb, error=str(exc))
        return cs.emit(
            {"result": "busy", "error": "store_busy", "message": str(exc)}, cs.EXIT_BUSY
        )
    except sqlite3.Error as exc:
        if cs.sqlite_code(exc) in cs.SQLITE_BUSY_CODES:
            cs.log("store_busy_exit", verb=verb, error=str(exc))
            return cs.emit(
                {"result": "busy", "error": "store_busy", "message": str(exc)},
                cs.EXIT_BUSY,
            )
        cs.log("store_error", verb=verb, error=str(exc))
        return cs.emit(
            {"result": "refused", "error": "store_error", "message": str(exc)},
            cs.EXIT_REFUSED,
        )
    finally:
        if con is not None:
            con.close()


if __name__ == "__main__":
    sys.exit(main())
