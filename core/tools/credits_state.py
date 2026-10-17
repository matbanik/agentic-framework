"""The credits run store: one SQLite database for all mutable run state.

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component B, phase
S2a; the message verbs and the schema version 2 of phase S1b; the monitor verbs
and the schema version 3 of phase S3; the read-only ``view`` and the schema
version 4 of phase S4). Report:
``_inspiration/scheduled-credits-runs/report.md`` R§4.1 (manifest, spend and
exposures), R§4.6.2 (orchestrator messages), R§4.7 (store, transaction rules,
invariants, state machine and kill tests), R§4.4 (the monitor: lease, liveness,
outbox cursor and notices) and R§7.2 (manual supervision).

Usage::

    credits_state.py --db <path> [--now-utc <YYYY-MM-DDTHH:MM:SSZ>]
                     [--profile cli|launcher|monitor|hook] <verb> [flags]

Each verb is one ``BEGIN IMMEDIATE`` transaction (R§4.7 rule 1), except ``view``: it
opens the store with ``mode=ro`` and reads in one read transaction (R§4.5). Every state
change is a compare-and-set that also appends one ``transitions`` row (rule 2).
External work happens only after the commit, through keyed ``effects`` rows
that are marked ``done`` in a second transaction (rules 3 and 4).

stdout is one JSON object. ``result`` is ``changed``, ``no_change``, ``ok``,
``failed``, ``refused``, ``conflict``, ``busy`` or ``usage_error``; ``error``
holds the code of a refusal. Exit codes:

* 0: ``changed``, ``no_change`` or ``ok``;
* 1: ``check`` found a failure;
* 2: usage error (unknown verb, flag, value or crash point); the store is not
  opened;
* 3: refused or conflict;
* 9: a test crash point fired;
* 75: the store stayed busy after the retries.

Test seams (read only from the environment; each is inert when unset):

* ``CREDITS_TEST_CRASH_AT=<verb>:<point>`` ends the process with exit 9 at a
  declared point (``CRASH_POINTS``). An undeclared value is a usage error.
* ``CREDITS_TEST_EFFECT_LOG=<file>`` appends one JSON line per performed effect
  in place of the real effect.
* ``CREDITS_TEST_BUSY_TIMEOUT_MS=<n>`` replaces the profile busy timeout.
"""

from __future__ import annotations

import argparse
import ctypes
import getpass
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import unicodedata
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn, cast

SCHEMA_VERSION = 6

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_USAGE = 2
EXIT_REFUSED = 3
EXIT_CRASH = 9
EXIT_BUSY = 75

FLOOR_USD = 5.0
ACCEPT_MAX_AGE_S = 120
CALLER_TIMEOUT_S = 120
ORPHAN_AGE_S = 150
STALE_PENDING_S = 600
REGISTRATION_STUCK_S = 600
IDENTITY_STUCK_S = 600
EFFECT_RETRY_S = 300
# R§4.4: a monitor pass holds the lease at most this long; an expired lease is free.
LEASE_TTL_S = 900
# R§4.4 step 5: after this many failed sends, the monitor tries a notice once an hour.
NOTICE_SLOW_AFTER = 3
NOTICE_SLOW_RETRY_S = 3600

BUSY_TIMEOUT_MS = {"cli": 30000, "launcher": 30000, "monitor": 30000, "hook": 5000}
# R§4.7 rule 5: the hook skips a busy fire; every other caller tries 3 times.
BUSY_TRIES = {"cli": 3, "launcher": 3, "monitor": 3, "hook": 1}
PROFILES = tuple(BUSY_TIMEOUT_MS)

SQLITE_BUSY_CODES = frozenset({5, 6})  # SQLITE_BUSY, SQLITE_LOCKED
SQLITE_CORRUPT_CODES = frozenset({11, 26})  # SQLITE_CORRUPT, SQLITE_NOTADB

UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# A boot id as the dispatch writes it to running.json: "bootid:<n>" (a key plus ":").
BOOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CLASS_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# R§4.6.2: the kinds of an orchestrator message. S6b enables ``ruling``; a ruling
# must name its decision, gate, orchestrator session, user message and quote.
MESSAGE_KINDS = ("info", "query", "stop-after-row", "ruling")
ENABLED_MESSAGE_KINDS = frozenset({"info", "query", "stop-after-row", "ruling"})
RULING_FIELDS = (
    "decision_id",
    "gate_id",
    "orchestrator_session_id",
    "user_message_uuid",
    "human_quote",
)
# The body cap of one message; well under the 10,000-character hook output cap.
MESSAGE_BODY_MAX = 4000
JOB_NAME_PREFIX = "Local\\{{PROJECT_NAME_UPPER}}Credits-"
EVENT_SOURCE = "{{PROJECT_NAME_TITLE}}/Credits"

PROOF_VALUES = frozenset({"empty", "gone", "live", "unknown"})
FINAL_PROOFS = frozenset({"empty", "gone"})
STARTED_BY = ("human-command", "agent-on-user-chat", "monitor-chain")
FINALIZERS = ("launcher", "monitor", "wrapper")
CLASSIFY_TARGETS = ("stopped", "parked", "done", "done_unverified")
# A resume continues the source session (the default, D-4 A) or starts a new one (R§5.3).
RESUME_MODES = ("session", "fresh")
# R§5.2: the run stop classes that the monitor writes with classify.
STOP_CLASSES = (
    "done",
    "done_unverified",
    "parked",
    "decision",
    "handback",
    "round_cap",
    "reviewer_unavailable",
    "reboot",
    "sleep_death",
    "death_unknown",
    "background_wait_exit",
    "transient_api",
    "billing",
    "auth_config",
    "budget_cap",
    "timeout",
    "launch_failed",
    "base_moved",
    "cancelled",
    "unknown",
)
# The notices that the monitor files with the notice verb (R§7.2 manual proof).
MONITOR_NOTICE_KINDS = ("manual_child_alive",)
# R§4.4 step 2: the outbox kinds that open a notice; report, ack and applied do not.
OUTBOX_NOTICE_KINDS = frozenset({"decision", "decision_resolved", "gate_expired"})
OUTBOX_CURSOR = "outbox"
TERMINAL_RUN_STATES = frozenset(
    {"parked", "done", "done_unverified", "failed", "cancelled"}
)
FIRST_START_FROM = frozenset({"registered", "waiting"})
MANIFEST_KEYS = frozenset(
    {
        "schema",
        "run_id",
        "kind",
        "project_root",
        "plan_folder",
        "brief",
        "launch",
        "budget",
        "messaging",
        "depends_on",
        "lane",
        "chain",
        "executor_worktree",
        "carry_allowed",
    }
)
# R§5.4.3: the predicates a ``depends_on`` item can require.
PREDICATES = ("done_verified", "parked_verified", "landed", "committed")
# R§5.4.3: a predecessor in one of these states makes every predicate false.
HALTED_RUN_STATES = frozenset({"stopped", "done_unverified", "failed", "cancelled"})
CHAIN_KEYS = frozenset({"chain_id", "quote", "given_at", "chain_cap_usd"})
# The landing blobs of a path that is not in the tree: a product row of a deleted
# path and a closeout row of a missing file (credits_msg.py writes both).
DELETED_BLOB = "deleted"
ABSENT_BLOB = "ABSENT"
MISSING_BLOBS = frozenset({DELETED_BLOB, ABSENT_BLOB})
# The predicate checks read git as credits_msg.py does: the same line-ending pin and no
# inherited repository overrides.
EOL_PIN = ("-c", "core.autocrlf=true", "-c", "core.safecrlf=false")
GIT_ENV_DROPPED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
GIT_TIMEOUT_S = 300

BASE_POINTS = ("before_begin", "before_commit", "after_commit")
EFFECT_POINTS = (*BASE_POINTS, "after_effect")
# Every point a test may name. A verb listed with EFFECT_POINTS can insert
# effects; ``scan_effects`` only performs them; ``spend`` and ``run_status``
# write nothing.
CRASH_POINTS: dict[str, tuple[str, ...]] = {
    "init": BASE_POINTS,
    "check": EFFECT_POINTS,
    "clear_check": BASE_POINTS,
    "register": BASE_POINTS,
    "registered": BASE_POINTS,
    "registration_failed": BASE_POINTS,
    "request": BASE_POINTS,
    "not_started": EFFECT_POINTS,
    "accept": EFFECT_POINTS,
    "admit": EFFECT_POINTS,
    "launched": BASE_POINTS,
    "complete_segment": EFFECT_POINTS,
    "classify": EFFECT_POINTS,
    "cancel": BASE_POINTS,
    "register_minimal": BASE_POINTS,
    "manual_identity": BASE_POINTS,
    "settle": BASE_POINTS,
    "send": BASE_POINTS,
    "scan_requests": EFFECT_POINTS,
    "scan_attempts": EFFECT_POINTS,
    "scan_segments": EFFECT_POINTS,
    "scan_effects": ("after_effect",),
    "spend": (),
    "run_status": (),
    "termination_pending": BASE_POINTS,
    "lease": BASE_POINTS,
    "lease_release": BASE_POINTS,
    "alive": BASE_POINTS,
    "notice": EFFECT_POINTS,
    "notices_due": (),
    "monitor_view": (),
    "view": (),
    "notice_sent": BASE_POINTS,
    "notice_failed": EFFECT_POINTS,
    "outbox_scan": EFFECT_POINTS,
    "predicates": (),
    "chain_candidates": (),
    "accept_drift": BASE_POINTS,
    "prune": BASE_POINTS,
    "scan_transcript": EFFECT_POINTS,
    "attach": BASE_POINTS,
    "orchestrator_sessions": (),
}
# The verbs that R§4.7 and its transition table name, the S2a scan verbs, the S3
# monitor verbs and the S4 check view (read only, outside ``run_verb``).
STORE_VERBS = tuple(CRASH_POINTS)


# --- schema (versions 1 to 5) ---------------------------------------------------

SCHEMA_V1: tuple[str, ...] = (
    """CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        state TEXT NOT NULL,
        previous_state TEXT,
        kind TEXT NOT NULL,
        supervision TEXT NOT NULL CHECK (supervision IN ('job', 'manual')),
        lane TEXT,
        manifest_json TEXT,
        manifest_sha256 TEXT,
        segment_cap_usd REAL,
        run_cap_usd REAL,
        timeout_sec INTEGER,
        cli_version TEXT,
        kit_revision TEXT,
        task_hash TEXT,
        registration_reason TEXT,
        active_tree TEXT,
        base_commit TEXT,
        base_fixed INTEGER NOT NULL DEFAULT 0,
        start_tree TEXT,
        landed_tree TEXT,
        capture_tree TEXT,
        stop_class TEXT,
        created_utc TEXT NOT NULL,
        updated_utc TEXT NOT NULL
    )""",
    """CREATE TABLE requests (
        request_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs (run_id),
        state TEXT NOT NULL,
        previous_state TEXT NOT NULL,
        started_by TEXT NOT NULL,
        start_quote TEXT,
        chain_id TEXT,
        resume INTEGER NOT NULL,
        requested_by TEXT,
        reason TEXT,
        created_utc TEXT NOT NULL,
        updated_utc TEXT NOT NULL
    )""",
    """CREATE TABLE attempts (
        attempt_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL UNIQUE REFERENCES requests (request_id),
        run_id TEXT NOT NULL REFERENCES runs (run_id),
        dispatch_id TEXT NOT NULL,
        expected_session_id TEXT NOT NULL,
        launcher_pid INTEGER NOT NULL,
        launcher_created TEXT NOT NULL,
        boot_id TEXT NOT NULL,
        win_session INTEGER NOT NULL,
        state TEXT NOT NULL,
        reason TEXT,
        created_utc TEXT NOT NULL,
        updated_utc TEXT NOT NULL
    )""",
    """CREATE TABLE segments (
        segment_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs (run_id),
        attempt_id TEXT UNIQUE REFERENCES attempts (attempt_id),
        request_id TEXT REFERENCES requests (request_id),
        dispatch_id TEXT,
        expected_session_id TEXT,
        supervision TEXT NOT NULL CHECK (supervision IN ('job', 'manual')),
        job INTEGER NOT NULL,
        lane TEXT,
        reservation_usd REAL NOT NULL DEFAULT 0,
        reservation_released_utc TEXT,
        state TEXT NOT NULL,
        launcher_pid INTEGER,
        launcher_created TEXT,
        wrapper_pid INTEGER,
        wrapper_created TEXT,
        boot_id TEXT,
        win_session INTEGER,
        job_name TEXT,
        pid INTEGER,
        created TEXT,
        session_total_usd REAL,
        segment_delta_usd REAL,
        cost_known INTEGER NOT NULL DEFAULT 0,
        resume TEXT,
        base_commit TEXT,
        carry_manifest_json TEXT,
        profile_sha256 TEXT,
        brief TEXT,
        segment_deadline_utc TEXT,
        last_alive_utc TEXT,
        cancel_requested_utc TEXT,
        finalized_utc TEXT,
        finalized_by TEXT,
        stop_class TEXT,
        exit_code INTEGER,
        handled INTEGER NOT NULL DEFAULT 0,
        created_utc TEXT NOT NULL,
        updated_utc TEXT NOT NULL
    )""",
    """CREATE TABLE lanes (
        lane TEXT PRIMARY KEY,
        segment_id TEXT REFERENCES segments (segment_id),
        claimed_utc TEXT
    )""",
    """CREATE TABLE exposures (
        segment_id TEXT PRIMARY KEY REFERENCES segments (segment_id),
        run_id TEXT NOT NULL REFERENCES runs (run_id),
        exposed_usd REAL NOT NULL,
        amount_usd REAL NOT NULL,
        state TEXT NOT NULL,
        note TEXT,
        settled_by TEXT,
        settled_utc TEXT,
        created_utc TEXT NOT NULL,
        updated_utc TEXT
    )""",
    """CREATE TABLE gates (
        gate_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs (run_id),
        segment_id TEXT REFERENCES segments (segment_id),
        state TEXT NOT NULL,
        msg_id TEXT,
        question TEXT,
        opened_utc TEXT NOT NULL,
        closed_utc TEXT,
        closed_reason TEXT
    )""",
    "CREATE UNIQUE INDEX gates_one_open_per_run ON gates (run_id) WHERE state = 'open'",
    """CREATE TABLE messages (
        msg_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs (run_id),
        seq INTEGER NOT NULL,
        kind TEXT NOT NULL,
        body_json TEXT,
        state TEXT NOT NULL,
        created_utc TEXT NOT NULL,
        closed_utc TEXT,
        closed_reason TEXT,
        UNIQUE (run_id, seq)
    )""",
    """CREATE TABLE deliveries (
        msg_id TEXT NOT NULL REFERENCES messages (msg_id),
        segment_id TEXT NOT NULL REFERENCES segments (segment_id),
        generation INTEGER NOT NULL DEFAULT 1,
        state TEXT NOT NULL,
        delivered_utc TEXT,
        PRIMARY KEY (msg_id, segment_id)
    )""",
    """CREATE TABLE outbox_events (
        event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT REFERENCES runs (run_id),
        kind TEXT NOT NULL,
        semantic_key TEXT NOT NULL UNIQUE,
        payload_json TEXT,
        created_utc TEXT NOT NULL
    )""",
    """CREATE TABLE consumed_rulings (
        orchestrator_session TEXT NOT NULL,
        user_message_uuid TEXT NOT NULL,
        prompt_id TEXT NOT NULL,
        run_id TEXT REFERENCES runs (run_id),
        gate_id TEXT REFERENCES gates (gate_id),
        msg_id TEXT,
        ruling_json TEXT,
        consumed_utc TEXT NOT NULL,
        PRIMARY KEY (orchestrator_session, user_message_uuid),
        UNIQUE (orchestrator_session, prompt_id)
    )""",
    """CREATE TABLE attaches (
        orchestrator_session TEXT NOT NULL,
        user_message_uuid TEXT NOT NULL,
        prompt_id TEXT NOT NULL,
        run_id TEXT REFERENCES runs (run_id),
        attached_utc TEXT NOT NULL,
        PRIMARY KEY (orchestrator_session, user_message_uuid),
        UNIQUE (orchestrator_session, prompt_id)
    )""",
    """CREATE TABLE orchestrator_sessions (
        run_id TEXT NOT NULL REFERENCES runs (run_id),
        session TEXT NOT NULL,
        history_state TEXT NOT NULL DEFAULT 'ok',
        attached_utc TEXT NOT NULL,
        PRIMARY KEY (run_id, session)
    )""",
    """CREATE TABLE transcript_marks (
        session TEXT PRIMARY KEY,
        byte_length INTEGER NOT NULL,
        prefix_sha256 TEXT NOT NULL,
        line_count INTEGER NOT NULL,
        updated_utc TEXT NOT NULL
    )""",
    """CREATE TABLE queue_chains (
        session TEXT NOT NULL,
        chain_id TEXT NOT NULL,
        delivery_id TEXT NOT NULL,
        command_uuid TEXT,
        lines_json TEXT,
        remove_reason TEXT,
        text_hashes_json TEXT,
        state TEXT NOT NULL,
        updated_utc TEXT NOT NULL,
        PRIMARY KEY (session, chain_id),
        UNIQUE (session, delivery_id)
    )""",
    """CREATE TABLE landings (
        run_id TEXT NOT NULL REFERENCES runs (run_id),
        part TEXT NOT NULL,
        path TEXT NOT NULL,
        blob TEXT,
        sealed_utc TEXT,
        PRIMARY KEY (run_id, part, path)
    )""",
    """CREATE TABLE drift_accepts (
        successor TEXT NOT NULL,
        predecessor TEXT NOT NULL,
        commit_id TEXT NOT NULL,
        words TEXT NOT NULL,
        paths_json TEXT,
        accepted_utc TEXT NOT NULL,
        PRIMARY KEY (successor, predecessor, commit_id)
    )""",
    """CREATE TABLE notices (
        notice_key TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        run_id TEXT,
        ref TEXT,
        subject TEXT NOT NULL,
        body_json TEXT,
        state TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        created_utc TEXT NOT NULL,
        sent_utc TEXT
    )""",
    """CREATE TABLE effects (
        effect_key TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        ref TEXT,
        state TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_utc TEXT NOT NULL,
        done_utc TEXT
    )""",
    """CREATE TABLE transitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        from_state TEXT,
        to_state TEXT NOT NULL,
        verb TEXT NOT NULL,
        owner TEXT NOT NULL,
        at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE monitor_lease (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        holder TEXT,
        pid INTEGER,
        expires_utc TEXT
    )""",
    """CREATE TABLE cursors (
        name TEXT PRIMARY KEY,
        value TEXT,
        updated_utc TEXT NOT NULL
    )""",
    """CREATE TABLE store_flags (
        flag TEXT PRIMARY KEY,
        value_json TEXT,
        set_utc TEXT NOT NULL,
        note TEXT
    )""",
)

# Version 2 (S1b, R§4.6.2 and R§4.6.4): the message, delivery and gate columns,
# the reminder mark of a segment, the stored closeout set and the hook skips.
SCHEMA_V2: tuple[str, ...] = (
    "ALTER TABLE runs ADD COLUMN closeout_paths_json TEXT",
    "ALTER TABLE segments ADD COLUMN stop_reminded_utc TEXT",
    "ALTER TABLE gates ADD COLUMN decision_id TEXT",
    "ALTER TABLE gates ADD COLUMN deadline_utc TEXT",
    "ALTER TABLE messages ADD COLUMN acked_utc TEXT",
    "ALTER TABLE messages ADD COLUMN applied_utc TEXT",
    "ALTER TABLE messages ADD COLUMN payload_hash TEXT",
    "ALTER TABLE deliveries ADD COLUMN claimed_utc TEXT",
    "ALTER TABLE deliveries ADD COLUMN emit_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE deliveries ADD COLUMN last_emit_utc TEXT",
    "ALTER TABLE deliveries ADD COLUMN fires_since_emit INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE deliveries ADD COLUMN confirmed_utc TEXT",
    "ALTER TABLE deliveries ADD COLUMN failed_utc TEXT",
    """CREATE TABLE hook_skips (
        skip_id INTEGER PRIMARY KEY AUTOINCREMENT,
        reason TEXT NOT NULL,
        run_id TEXT,
        segment_id TEXT,
        session_id TEXT,
        hook_event TEXT,
        created_utc TEXT NOT NULL
    )""",
)

# Version 3 (S3, R§4.4 step 5): the last send attempt and error of a notice, for the
# hourly retry after NOTICE_SLOW_AFTER failed sends.
SCHEMA_V3: tuple[str, ...] = (
    "ALTER TABLE notices ADD COLUMN last_attempt_utc TEXT",
    "ALTER TABLE notices ADD COLUMN last_error TEXT",
)

# Version 4 (S4, R§5.3): the resume mode (session or fresh) and the resume brief of a
# resume request. Admission copies the brief to the new segment.
SCHEMA_V4: tuple[str, ...] = (
    "ALTER TABLE requests ADD COLUMN resume_mode TEXT",
    "ALTER TABLE requests ADD COLUMN brief TEXT",
)

# Version 5 (S5, R§5.4): the main tree of a run, where an executor-worktree run
# captures, seals and pins.
SCHEMA_V5: tuple[str, ...] = ("ALTER TABLE runs ADD COLUMN main_tree TEXT",)

# Version 6 (S6b, R§4.6.3): the attach watermark of a transcript mark, the decision and
# payload hash of a consumed ruling, and the message that resolved a gate.
SCHEMA_V6: tuple[str, ...] = (
    "ALTER TABLE transcript_marks ADD COLUMN watermark_bytes INTEGER",
    "ALTER TABLE consumed_rulings ADD COLUMN decision_id TEXT",
    "ALTER TABLE consumed_rulings ADD COLUMN payload_hash TEXT",
    "ALTER TABLE gates ADD COLUMN resolved_by_msg TEXT",
)

# The statements that bring a store from version n - 1 to version n.
SCHEMA_STEPS: dict[int, tuple[str, ...]] = {
    1: SCHEMA_V1,
    2: SCHEMA_V2,
    3: SCHEMA_V3,
    4: SCHEMA_V4,
    5: SCHEMA_V5,
    6: SCHEMA_V6,
}


# --- errors and results ---------------------------------------------------------


class UsageError(Exception):
    """A bad verb, flag, value or crash point: exit 2, the store is not opened."""


class Refusal(Exception):
    """A verb refuses (``refused``) or loses a compare-and-set (``conflict``); exit 3."""

    def __init__(
        self, error: str, message: str, *, result: str = "refused", **extra: Any
    ) -> None:
        super().__init__(message)
        self.error = error
        self.message = message
        self.result = result
        self.extra = extra

    def payload(self) -> dict[str, Any]:
        """Return the stdout object of this refusal."""
        return {
            "result": self.result,
            "error": self.error,
            "message": self.message,
            **self.extra,
        }


class StoreBusy(Exception):
    """The write lock stayed taken after every try: exit 75."""


@dataclass
class Outcome:
    """What a verb body returns: the ``result`` and the rest of the payload."""

    result: str
    payload: dict[str, Any] = field(default_factory=dict)


# --- small helpers --------------------------------------------------------------


def parse_utc(text: str) -> datetime:
    """Parse ``YYYY-MM-DDTHH:MM:SSZ``; raise ``ValueError`` on any other form."""
    if not UTC_RE.match(text):
        raise ValueError(f"not a UTC time of the form YYYY-MM-DDTHH:MM:SSZ: {text!r}")
    return datetime.strptime(text, UTC_FORMAT).replace(tzinfo=UTC)


def format_utc(moment: datetime) -> str:
    """Format a UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return moment.astimezone(UTC).strftime(UTC_FORMAT)


def production_clock() -> datetime:
    """Return the UTC time now, in whole seconds (the store clock without ``--now-utc``)."""
    return datetime.now(UTC).replace(microsecond=0)


def money(value: float) -> float:
    """Round a dollar amount so sums do not carry binary noise."""
    return round(value, 6)


def log(event: str, **fields: Any) -> None:
    """Write one structured log line to stderr."""
    sys.stderr.write(json.dumps({"event": event, **fields}, sort_keys=True) + "\n")


def _arg_key(text: str) -> str:
    if not KEY_RE.match(text) or ".." in text:
        raise argparse.ArgumentTypeError(
            f"not a key ([A-Za-z0-9][A-Za-z0-9._-]{{0,127}}, no '..'): {text!r}"
        )
    return text


def _arg_boot_id(text: str) -> str:
    if not BOOT_ID_RE.match(text) or ".." in text:
        raise argparse.ArgumentTypeError(
            f"not a boot id ([A-Za-z0-9][A-Za-z0-9._:-]{{0,127}}, no '..'): {text!r}"
        )
    return text


def _arg_utc(text: str) -> str:
    try:
        parse_utc(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return text


def _arg_money(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from exc
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(f"not a finite amount >= 0: {text!r}")
    return value


def _arg_pid(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"not a pid > 0: {text!r}")
    return value


def _arg_win_session(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc
    if value < 0:
        raise argparse.ArgumentTypeError(f"not a session id >= 0: {text!r}")
    return value


def _arg_int(text: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc


def _arg_class(text: str) -> str:
    if not CLASS_RE.match(text):
        raise argparse.ArgumentTypeError(
            f"not a class name ([a-z][a-z0-9_]*): {text!r}"
        )
    return text


def _arg_text(text: str) -> str:
    if not text.strip() or len(text) > 4000:
        raise argparse.ArgumentTypeError("text must be 1 to 4000 characters")
    return text


def _arg_body(text: str) -> str:
    # The cap is a refusal of the verb (body_too_long), not a usage error.
    if not text.strip():
        raise argparse.ArgumentTypeError("the body is empty")
    return text


def _arg_proofs(text: str) -> dict[str, str]:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"proofs are not JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise argparse.ArgumentTypeError("proofs must be a JSON object")
    proofs: dict[str, str] = {}
    for key, value in loaded.items():
        _arg_key(str(key))
        if value not in PROOF_VALUES:
            raise argparse.ArgumentTypeError(
                f"proof of {key!r} must be one of {sorted(PROOF_VALUES)}: {value!r}"
            )
        proofs[str(key)] = str(value)
    return proofs


def _arg_json_object(text: str) -> dict[str, Any]:
    """A JSON object of at most ``MESSAGE_BODY_MAX`` characters (a notice body)."""
    if len(text) > MESSAGE_BODY_MAX:
        raise argparse.ArgumentTypeError(f"longer than {MESSAGE_BODY_MAX} characters")
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"not JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise argparse.ArgumentTypeError("not a JSON object")
    return loaded


def _arg_ttl(text: str) -> int:
    value = _arg_int(text)
    if not 1 <= value <= 86400:
        raise argparse.ArgumentTypeError("the lease time must be 1 to 86400 seconds")
    return value


# --- CLI ------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    """An argument parser that raises ``UsageError`` in place of printing and exiting."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def build_parser() -> _Parser:
    """Return the parser of the global options and every verb."""
    parser = _Parser(prog="credits_state.py", allow_abbrev=False)
    parser.add_argument("--db", required=True, help="path of the store file")
    parser.add_argument("--now-utc", type=_arg_utc, help="store clock (test seam)")
    parser.add_argument("--profile", choices=PROFILES, default="cli")
    verbs = parser.add_subparsers(dest="verb", required=True, parser_class=_Parser)

    def verb(name: str) -> _Parser:
        return verbs.add_parser(name, allow_abbrev=False)

    verb("init")
    verb("check")
    p = verb("clear_check")
    p.add_argument("--note", required=True, type=_arg_text)

    p = verb("register")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--manifest", required=True)
    p.add_argument("--cli-version", required=True, type=_arg_text)
    p.add_argument("--kit-revision", required=True, type=_arg_text)
    p = verb("registered")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--task-hash", required=True, type=_arg_text)
    p = verb("registration_failed")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--reason", required=True, type=_arg_text)

    p = verb("request")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--started-by", required=True, choices=STARTED_BY)
    p.add_argument("--request-id", type=_arg_key)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--resume-mode", choices=RESUME_MODES)
    p.add_argument("--brief", type=_arg_text)
    p.add_argument("--quote", type=_arg_text)
    p.add_argument("--chain-id", type=_arg_key)
    p.add_argument("--requested-by", type=_arg_text)
    p = verb("not_started")
    p.add_argument("--request-id", required=True, type=_arg_key)
    p.add_argument("--reason", required=True, choices=("caller_timeout", "orphan"))

    p = verb("accept")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--launcher-pid", required=True, type=_arg_pid)
    p.add_argument("--launcher-created", required=True, type=_arg_utc)
    p.add_argument("--boot-id", required=True, type=_arg_boot_id)
    p.add_argument("--win-session", required=True, type=_arg_win_session)
    p.add_argument("--attempt-id", type=_arg_key)
    p.add_argument("--dispatch-id", type=_arg_key)
    p.add_argument("--expected-session-id", type=_arg_key)
    p = verb("admit")
    p.add_argument("--attempt-id", required=True, type=_arg_key)
    p.add_argument("--segment-id", type=_arg_key)
    p.add_argument("--base", type=_arg_key)
    p = verb("launched")
    p.add_argument("--segment-id", required=True, type=_arg_key)
    p.add_argument("--pid", required=True, type=_arg_pid)
    p.add_argument("--created", required=True, type=_arg_utc)
    p.add_argument("--boot-id", required=True, type=_arg_boot_id)
    p = verb("complete_segment")
    p.add_argument("--segment-id", required=True, type=_arg_key)
    p.add_argument("--finalized-by", required=True, choices=FINALIZERS)
    p.add_argument("--class", dest="stop_class", required=True, type=_arg_class)
    p.add_argument("--session-total-usd", type=_arg_money)
    p.add_argument("--exit-code", type=_arg_int)
    p = verb("classify")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--to", required=True, choices=CLASSIFY_TARGETS)
    p.add_argument("--class", dest="stop_class", required=True, type=_arg_class)
    p.add_argument("--notice-ref", type=_arg_key)
    p.add_argument("--notice-json", type=_arg_json_object)
    p = verb("cancel")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--reason", type=_arg_text)

    p = verb("register_minimal")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--segment-id", required=True, type=_arg_key)
    p.add_argument("--wrapper-pid", required=True, type=_arg_pid)
    p.add_argument("--wrapper-created", required=True, type=_arg_utc)
    p.add_argument("--boot-id", required=True, type=_arg_boot_id)
    p.add_argument("--win-session", required=True, type=_arg_win_session)
    p.add_argument("--job-name", required=True, type=_arg_text)
    p.add_argument("--expected-session-id", required=True, type=_arg_key)
    p.add_argument("--dispatch-id", type=_arg_key)
    p.add_argument("--resume", action="store_true")
    p = verb("manual_identity")
    p.add_argument("--segment-id", required=True, type=_arg_key)
    p.add_argument("--pid", required=True, type=_arg_pid)
    p.add_argument("--created", required=True, type=_arg_utc)

    p = verb("settle")
    p.add_argument("--segment-id", required=True, type=_arg_key)
    p.add_argument(
        "--source", required=True, choices=("console", "human", "transcript")
    )
    p.add_argument("--amount-usd", required=True, type=_arg_money)
    p.add_argument("--note", type=_arg_text)
    p.add_argument(
        "--started-by",
        choices=("human-command", "agent-on-user-chat"),
        default="human-command",
    )
    p.add_argument("--quote", type=_arg_text)
    p = verb("spend")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p = verb("run_status")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p = verb("termination_pending")
    p.add_argument("--segment-id", required=True, type=_arg_key)

    p = verb("send")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--kind", required=True, choices=MESSAGE_KINDS)
    p.add_argument("--body", required=True, type=_arg_body)
    p.add_argument("--human-quote", type=_arg_text)
    p.add_argument("--decision-id", type=_arg_key)
    p.add_argument("--gate-id", type=_arg_key)
    p.add_argument("--orchestrator-session", type=_arg_key)
    p.add_argument("--user-message-uuid", type=_arg_key)

    verb("scan_requests")
    p = verb("scan_attempts")
    p.add_argument("--proofs-json", required=True, type=_arg_proofs)
    p = verb("scan_segments")
    p.add_argument("--proofs-json", required=True, type=_arg_proofs)
    verb("scan_effects")

    p = verb("lease")
    p.add_argument("--pid", required=True, type=_arg_pid)
    p.add_argument("--created", required=True, type=_arg_utc)
    p.add_argument("--boot-id", required=True, type=_arg_boot_id)
    p.add_argument("--ttl-s", type=_arg_ttl, default=LEASE_TTL_S)
    p.add_argument("--takeover", type=_arg_text)
    p = verb("lease_release")
    p.add_argument("--pid", required=True, type=_arg_pid)
    p.add_argument("--created", required=True, type=_arg_utc)
    p.add_argument("--boot-id", required=True, type=_arg_boot_id)
    p = verb("alive")
    p.add_argument("--segment-id", required=True, type=_arg_key)
    p = verb("notice")
    p.add_argument("--kind", required=True, choices=MONITOR_NOTICE_KINDS)
    p.add_argument("--ref", required=True, type=_arg_key)
    p.add_argument("--run-id", type=_arg_key)
    p.add_argument("--body-json", type=_arg_json_object)
    verb("notices_due")
    verb("monitor_view")
    p = verb("notice_sent")
    p.add_argument("--key", required=True, type=_arg_text)
    p = verb("notice_failed")
    p.add_argument("--key", required=True, type=_arg_text)
    p.add_argument("--error", required=True, type=_arg_text)
    verb("outbox_scan")
    p = verb("view")
    p.add_argument("--run-id", type=_arg_key)
    p.add_argument("--output-dir", type=_arg_text)

    p = verb("predicates")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--base", type=_arg_key)
    verb("chain_candidates")
    p = verb("accept_drift")
    p.add_argument("--successor", required=True, type=_arg_key)
    p.add_argument("--predecessor", required=True, type=_arg_key)
    p.add_argument("--quote", required=True, type=_arg_text)
    p.add_argument("--base", type=_arg_key)
    p = verb("prune")
    p.add_argument("--run-id", required=True, type=_arg_key)

    p = verb("scan_transcript")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--session", required=True, type=_arg_key)
    p = verb("attach")
    p.add_argument("--run-id", required=True, type=_arg_key)
    p.add_argument("--session", required=True, type=_arg_key)
    p.add_argument("--uuid", required=True, type=_arg_key)
    p = verb("orchestrator_sessions")
    p.add_argument("--run-id", type=_arg_key)
    return parser


def parse_crash_at(raw: str | None) -> tuple[str, str] | None:
    """Validate ``CREDITS_TEST_CRASH_AT``; an undeclared ``<verb>:<point>`` is a usage error."""
    if raw is None or raw == "":
        return None
    verb, sep, point = raw.partition(":")
    if not sep or point not in CRASH_POINTS.get(verb, ()):
        raise UsageError(
            f"CREDITS_TEST_CRASH_AT={raw!r} is not a declared <verb>:<point>"
        )
    return verb, point


def busy_timeout_ms(profile: str) -> int:
    """Return the busy timeout of a profile, or the test override."""
    raw = os.environ.get("CREDITS_TEST_BUSY_TIMEOUT_MS")
    if raw is None or raw == "":
        return BUSY_TIMEOUT_MS[profile]
    try:
        value = int(raw)
    except ValueError as exc:
        raise UsageError(
            f"CREDITS_TEST_BUSY_TIMEOUT_MS={raw!r} is not an integer"
        ) from exc
    if value <= 0:
        raise UsageError(f"CREDITS_TEST_BUSY_TIMEOUT_MS={raw!r} must be > 0")
    return value


# --- store location -------------------------------------------------------------


def store_not_local_reason(db: str) -> str | None:
    """Return why ``db`` is not on a local NTFS volume, or None when it is (R§4.7 settings)."""
    if db.startswith(("\\\\", "//")):
        return "the store path is a UNC path"
    if sys.platform != "win32":
        return None
    resolved = os.path.abspath(db)
    if resolved.startswith("\\\\"):
        return "the store path resolves to a UNC path"
    drive = os.path.splitdrive(resolved)[0]
    if not drive:
        return "the store path has no drive letter"
    root = drive + "\\"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    drive_type = int(kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))
    if drive_type == 4:  # DRIVE_REMOTE
        return f"{root} is a network drive"
    if drive_type in (0, 1):  # DRIVE_UNKNOWN, DRIVE_NO_ROOT_DIR
        return f"{root} is not a mounted volume"
    fs_name = ctypes.create_unicode_buffer(64)
    ok = kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root), None, 0, None, None, None, fs_name, len(fs_name)
    )
    if not ok:
        return f"the file system of {root} cannot be read (error {ctypes.get_last_error()})"
    if fs_name.value.upper() != "NTFS":
        return f"{root} is {fs_name.value or 'an unknown file system'}, not NTFS"
    return None


# --- context, transactions and effects -------------------------------------------


def sqlite_code(exc: sqlite3.Error) -> int:
    """Return the primary SQLite result code of an error (0 when unknown)."""
    return int(getattr(exc, "sqlite_errorcode", 0) or 0) & 0xFF


@dataclass
class Context:
    """One CLI call: the open store, the clock, the profile and the crash seam."""

    con: sqlite3.Connection
    db: Path
    verb: str
    profile: str
    now: datetime
    crash_at: tuple[str, str] | None
    busy_tries: int
    # The production clock; None under the ``--now-utc`` test clock. ``transact`` reads
    # it again after it takes the writer lock.
    clock: Callable[[], datetime] | None = None

    @property
    def now_utc(self) -> str:
        return format_utc(self.now)

    def ago(self, seconds: int) -> str:
        """Return the UTC text of ``now - seconds``."""
        return format_utc(self.now - timedelta(seconds=seconds))

    def crash(self, point: str) -> None:
        """End the process with exit 9 when the test seam names this verb and point."""
        if self.crash_at == (self.verb, point):
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(EXIT_CRASH)


class Tx:
    """Write helpers for one open transaction: compare-and-set, transitions, effects."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.con = ctx.con
        self.effects: list[str] = []

    def row(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        """Return the first row of a query, or None."""
        found: sqlite3.Row | None = self.con.execute(sql, tuple(params)).fetchone()
        return found

    def rows(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        """Return every row of a query."""
        return list(self.con.execute(sql, tuple(params)).fetchall())

    def transition(
        self,
        entity: str,
        entity_id: str,
        from_state: str | None,
        to_state: str,
        owner: str | None = None,
    ) -> None:
        """Append one audit row for a state change."""
        self.con.execute(
            "INSERT INTO transitions (entity, entity_id, from_state, to_state, verb, owner, at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entity,
                entity_id,
                from_state,
                to_state,
                self.ctx.verb,
                owner or self.ctx.profile,
                self.ctx.now_utc,
            ),
        )

    def move(
        self,
        entity: str,
        key: str,
        expected: str,
        new: str,
        sets: dict[str, Any] | None = None,
        owner: str | None = None,
    ) -> None:
        """Compare-and-set ``entity`` from ``expected`` to ``new``; a lost race is a conflict."""
        table, key_col = ENTITY_TABLES[entity]
        columns = {"state": new, "updated_utc": self.ctx.now_utc, **(sets or {})}
        assignments = ", ".join(f"{name} = ?" for name in columns)
        cursor = self.con.execute(
            f"UPDATE {table} SET {assignments} WHERE {key_col} = ? AND state = ?",
            (*columns.values(), key, expected),
        )
        if cursor.rowcount != 1:
            current = self.row(f"SELECT state FROM {table} WHERE {key_col} = ?", (key,))
            raise Refusal(
                "conflict",
                f"{entity} {key} is not {expected}",
                result="conflict",
                entity=entity,
                state=None if current is None else current["state"],
            )
        self.transition(entity, key, expected, new, owner)

    def created(
        self, entity: str, key: str, state: str, owner: str | None = None
    ) -> None:
        """Record the first state of a new row."""
        self.transition(entity, key, None, state, owner)

    def effect(self, key: str, kind: str, ref: str) -> None:
        """Insert a pending effect once per key; this call performs it after the commit."""
        cursor = self.con.execute(
            "INSERT OR IGNORE INTO effects (effect_key, kind, ref, state, created_utc) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (key, kind, ref, self.ctx.now_utc),
        )
        if cursor.rowcount == 1:
            self.effects.append(key)

    def notice(
        self, kind: str, ref: str, run_id: str | None, body: dict[str, Any]
    ) -> bool:
        """Insert notice ``<kind>:<ref>`` once, with its ``notice:`` effect; True when new."""
        notice_key = f"{kind}:{ref}"
        cursor = self.con.execute(
            "INSERT OR IGNORE INTO notices (notice_key, kind, run_id, ref, subject, body_json, state, created_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                notice_key,
                kind,
                run_id,
                ref,
                f"[credits] {kind} {ref} ({notice_key})",
                json.dumps(body, sort_keys=True),
                self.ctx.now_utc,
            ),
        )
        if cursor.rowcount != 1:
            return False
        self.effect(f"notice:{notice_key}", "notice", notice_key)
        return True


ENTITY_TABLES: dict[str, tuple[str, str]] = {
    "run": ("runs", "run_id"),
    "request": ("requests", "request_id"),
    "attempt": ("attempts", "attempt_id"),
    "segment": ("segments", "segment_id"),
    "exposure": ("exposures", "segment_id"),
}


def begin_immediate(ctx: Context) -> None:
    """Take the write lock, retrying a busy store up to the profile's tries."""
    for attempt in range(1, ctx.busy_tries + 1):
        try:
            ctx.con.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as exc:
            if sqlite_code(exc) not in SQLITE_BUSY_CODES:
                raise
            log("store_busy", verb=ctx.verb, attempt=attempt, tries=ctx.busy_tries)
    raise StoreBusy(f"the store stayed busy after {ctx.busy_tries} tries")


def rollback(ctx: Context) -> None:
    """Roll back an open transaction; a failed rollback is logged, never hidden."""
    if not ctx.con.in_transaction:
        return
    try:
        ctx.con.execute("ROLLBACK")
    except sqlite3.Error as exc:
        log("rollback_failed", verb=ctx.verb, error=str(exc))


def transact(ctx: Context, body: Callable[[Tx], Outcome]) -> Outcome:
    """Run ``body`` as one ``BEGIN IMMEDIATE`` transaction, then perform its effects.

    With a production clock, the store clock is read again after the writer lock is
    taken: a verb that waited for the lock checks its deadlines at the time it writes
    (MX-31). The clock never moves back.
    """
    ctx.crash("before_begin")
    begin_immediate(ctx)
    if ctx.clock is not None:
        ctx.now = max(ctx.now, ctx.clock())
    tx = Tx(ctx)
    try:
        outcome = body(tx)
        ctx.crash("before_commit")
        ctx.con.execute("COMMIT")
    except BaseException:
        rollback(ctx)
        raise
    ctx.crash("after_commit")
    failed = perform_effects(ctx, sorted(tx.effects))
    if failed:
        outcome.payload["effects_pending"] = failed
    return outcome


def perform_effects(ctx: Context, keys: list[str]) -> list[str]:
    """Perform each effect, then mark it done; return the keys left pending."""
    pending: list[str] = []
    for key in keys:
        found = ctx.con.execute(
            "SELECT kind, ref FROM effects WHERE effect_key = ?", (key,)
        ).fetchone()
        if found is None:
            log("effect_missing", key=key)
            pending.append(key)
            continue
        error = run_effect(ctx, key, str(found["kind"]), found["ref"])
        ctx.crash("after_effect")
        if not mark_effect(ctx, key, error):
            pending.append(key)
    return pending


def run_effect(ctx: Context, key: str, kind: str, ref: str | None) -> str | None:
    """Perform one effect; return an error text, or None when it ran."""
    log_path = os.environ.get("CREDITS_TEST_EFFECT_LOG")
    try:
        if log_path:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"key": key, "kind": kind}) + "\n")
            return None
        if kind in ("rescan", "notice"):
            request_rescan(ctx, key)
            return None
        if kind == "evtlog":
            write_event_log(f"{{PROJECT_NAME_TITLE}} credits {key}: segment {ref} finalized.")
            return None
        if kind == "notice_slow":
            write_event_log(
                f"{{PROJECT_NAME_TITLE}} credits {key}: notice {ref} failed {NOTICE_SLOW_AFTER} sends;"
                " the monitor tries it once an hour."
            )
            return None
        return f"unknown effect kind {kind!r}"
    except OSError as exc:
        log("effect_failed", key=key, error=str(exc))
        return f"{type(exc).__name__}: {exc}"


def request_rescan(ctx: Context, key: str) -> None:
    """Ask the monitor for a pass: replace ``rescan.request`` next to the store."""
    target = ctx.db.parent / "rescan.request"
    temp = target.with_name(f"rescan.request.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps({"key": key, "at_utc": ctx.now_utc}) + "\n", encoding="utf-8"
    )
    os.replace(temp, target)


def write_event_log(message: str) -> None:
    """Write one information event to the Windows Application log (source ``{{PROJECT_NAME_TITLE}}/Credits``)."""
    if sys.platform != "win32":
        raise OSError("the Windows event log does not exist on this host")
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.RegisterEventSourceW.restype = ctypes.c_void_p
    advapi32.RegisterEventSourceW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    advapi32.ReportEventW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ushort,
        ctypes.c_ushort,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ushort,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.c_void_p,
    ]
    advapi32.DeregisterEventSource.argtypes = [ctypes.c_void_p]
    handle = advapi32.RegisterEventSourceW(None, EVENT_SOURCE)
    if not handle:
        raise OSError(f"RegisterEventSourceW failed (error {ctypes.get_last_error()})")
    try:
        strings = (ctypes.c_wchar_p * 1)(message)
        ok = advapi32.ReportEventW(handle, 4, 0, 1000, None, 1, 0, strings, None)
        if not ok:
            raise OSError(f"ReportEventW failed (error {ctypes.get_last_error()})")
    finally:
        advapi32.DeregisterEventSource(handle)


def mark_effect(ctx: Context, key: str, error: str | None) -> bool:
    """Mark an effect done, or record its error; return True when it is done."""
    try:
        begin_immediate(ctx)
    except (StoreBusy, sqlite3.Error) as exc:
        log("effect_mark_failed", key=key, error=str(exc))
        return False
    try:
        if error is None:
            ctx.con.execute(
                "UPDATE effects SET state = 'done', done_utc = ?, attempts = attempts + 1, last_error = NULL "
                "WHERE effect_key = ? AND state = 'pending'",
                (ctx.now_utc, key),
            )
        else:
            ctx.con.execute(
                "UPDATE effects SET attempts = attempts + 1, last_error = ? "
                "WHERE effect_key = ? AND state = 'pending'",
                (error, key),
            )
        ctx.con.execute("COMMIT")
    except sqlite3.Error as exc:
        rollback(ctx)
        log("effect_mark_failed", key=key, error=str(exc))
        return False
    return error is None


# --- schema version ---------------------------------------------------------------


def user_version(con: sqlite3.Connection) -> int:
    """Return ``PRAGMA user_version``."""
    return int(con.execute("PRAGMA user_version").fetchone()[0])


def migrate(ctx: Context, *, crash_points: bool) -> bool:
    """Bring the store to ``SCHEMA_VERSION``, one step per version; True when it changed."""
    if user_version(ctx.con) == SCHEMA_VERSION:
        return False

    def body(tx: Tx) -> Outcome:
        version = user_version(tx.con)
        if version == SCHEMA_VERSION:
            return Outcome("no_change")
        for step in range(version + 1, SCHEMA_VERSION + 1):
            for statement in SCHEMA_STEPS[step]:
                tx.con.execute(statement)
        tx.con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return Outcome("changed")

    if crash_points:
        return transact(ctx, body).result == "changed"
    begin_immediate(ctx)
    try:
        outcome = body(Tx(ctx))
        ctx.con.execute("COMMIT")
    except BaseException:
        rollback(ctx)
        raise
    return outcome.result == "changed"


def connection_settings(con: sqlite3.Connection) -> dict[str, Any]:
    """Return the connection settings that AC-B.1 asks each verb to set."""
    return {
        "journal_mode": str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
        "synchronous": int(con.execute("PRAGMA synchronous").fetchone()[0]),
        "foreign_keys": int(con.execute("PRAGMA foreign_keys").fetchone()[0]),
        "busy_timeout_ms": int(con.execute("PRAGMA busy_timeout").fetchone()[0]),
    }


# --- shared reads -------------------------------------------------------------------


def get_run(tx: Tx, run_id: str) -> sqlite3.Row:
    """Return the run row; an unknown id is refused."""
    found = tx.row("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    if found is None:
        raise Refusal("unknown_run", f"no run {run_id}")
    return found


def get_segment(tx: Tx, segment_id: str) -> sqlite3.Row:
    """Return the segment row; an unknown id is refused."""
    found = tx.row("SELECT * FROM segments WHERE segment_id = ?", (segment_id,))
    if found is None:
        raise Refusal("unknown_segment", f"no segment {segment_id}")
    return found


def get_request(tx: Tx, request_id: str) -> sqlite3.Row:
    """Return the request row; an unknown id is refused."""
    found = tx.row("SELECT * FROM requests WHERE request_id = ?", (request_id,))
    if found is None:
        raise Refusal("unknown_request", f"no request {request_id}")
    return found


def aggregate(tx: Tx, sql: str, params: Sequence[Any]) -> sqlite3.Row:
    """Return the one row of an aggregate query; no row means a damaged store."""
    found = tx.row(sql, params)
    if found is None:
        raise sqlite3.DatabaseError(f"an aggregate query returned no row: {sql}")
    return found


def run_spend(tx: Tx, run_id: str) -> dict[str, float]:
    """Return the four spend parts of a run (R§4.1)."""
    known = aggregate(
        tx,
        "SELECT COALESCE(SUM(top), 0) AS v FROM ("
        " SELECT MAX(session_total_usd) AS top FROM segments"
        " WHERE run_id = ? AND cost_known = 1 GROUP BY expected_session_id)",
        (run_id,),
    )
    exposures = aggregate(
        tx,
        "SELECT"
        " COALESCE(SUM(CASE WHEN state = 'open' THEN amount_usd END), 0) AS open_usd,"
        " COALESCE(SUM(CASE WHEN state IN ('settled_console', 'human_adjusted')"
        "   THEN amount_usd END), 0) AS settled_usd"
        " FROM exposures WHERE run_id = ?",
        (run_id,),
    )
    reserved = aggregate(
        tx,
        "SELECT COALESCE(SUM(reservation_usd), 0) AS v FROM segments"
        " WHERE run_id = ? AND finalized_utc IS NULL AND reservation_released_utc IS NULL",
        (run_id,),
    )
    return {
        "known_spent_usd": money(float(known["v"])),
        "open_exposures_usd": money(float(exposures["open_usd"])),
        "settled_usd": money(float(exposures["settled_usd"])),
        "open_reservations_usd": money(float(reserved["v"])),
    }


def pending_requests(tx: Tx, run_id: str) -> list[sqlite3.Row]:
    """Return the run's ``pending`` requests, oldest first."""
    return tx.rows(
        "SELECT * FROM requests WHERE run_id = ? AND state = 'pending' ORDER BY created_utc, rowid",
        (run_id,),
    )


def not_start(tx: Tx, request: sqlite3.Row, reason: str) -> None:
    """Move a pending request to ``not_started`` and its run back to the previous state, with a notice."""
    request_id = str(request["request_id"])
    run_id = str(request["run_id"])
    tx.move("request", request_id, "pending", "not_started", {"reason": reason})
    run = get_run(tx, run_id)
    if run["state"] == "requested":
        tx.move("run", run_id, "requested", str(request["previous_state"]))
    tx.notice(
        "request_not_started",
        request_id,
        run_id,
        {"reason": reason, "run_id": run_id},
    )


# --- verbs: store ---------------------------------------------------------------------


def verb_check(tx: Tx) -> Outcome:
    """Run the R§4.7 rule-6 invariants and ``quick_check``; a failure sets the store flag."""
    failures = find_invariant_failures(tx)
    flag = tx.row("SELECT set_utc, note FROM store_flags WHERE flag = 'check_failed'")
    if not failures:
        return Outcome(
            "ok",
            {
                "check_flag": None
                if flag is None
                else {"set_utc": flag["set_utc"], "note": flag["note"]}
            },
        )
    if flag is None:
        names = sorted({f["invariant"] for f in failures})
        tx.con.execute(
            "INSERT INTO store_flags (flag, value_json, set_utc) VALUES ('check_failed', ?, ?)",
            (json.dumps(names), tx.ctx.now_utc),
        )
        tx.notice("check_failed", tx.ctx.now_utc, None, {"invariants": names})
    return Outcome("failed", {"failures": failures, "check_flag": True})


INVARIANTS: tuple[tuple[str, str], ...] = (
    (
        "lane_multi_segment",
        "SELECT lane AS ref FROM segments WHERE lane IS NOT NULL AND finalized_utc IS NULL"
        " GROUP BY lane HAVING COUNT(*) > 1",
    ),
    (
        "lane_held_by_finalized",
        "SELECT l.lane AS ref FROM lanes l JOIN segments s ON s.segment_id = l.segment_id"
        " WHERE s.finalized_utc IS NOT NULL",
    ),
    (
        "reservation_held_by_finalized",
        "SELECT segment_id AS ref FROM segments WHERE finalized_utc IS NOT NULL"
        " AND reservation_released_utc IS NULL AND reservation_usd > 0",
    ),
    (
        "finalized_without_cost",
        "SELECT s.segment_id AS ref FROM segments s WHERE s.finalized_utc IS NOT NULL"
        " AND s.cost_known = 0"
        " AND NOT EXISTS (SELECT 1 FROM exposures e WHERE e.segment_id = s.segment_id)",
    ),
    (
        "gate_multi_open",
        "SELECT run_id AS ref FROM gates WHERE state = 'open' GROUP BY run_id HAVING COUNT(*) > 1",
    ),
    (
        "ruling_gate_not_closed",
        "SELECT c.prompt_id AS ref FROM consumed_rulings c JOIN gates g ON g.gate_id = c.gate_id"
        " WHERE g.state = 'open' OR g.msg_id IS NOT c.msg_id",
    ),
    (
        "message_closed_without_reason",
        "SELECT msg_id AS ref FROM messages WHERE state = 'closed'"
        " AND (closed_reason IS NULL OR closed_reason = '')",
    ),
    (
        "request_stale_pending",
        "SELECT request_id AS ref FROM requests WHERE state = 'pending' AND created_utc < :stale",
    ),
    (
        "requested_without_pending",
        "SELECT r.run_id AS ref FROM runs r WHERE r.state = 'requested' AND"
        " (SELECT COUNT(*) FROM requests q WHERE q.run_id = r.run_id AND q.state = 'pending') != 1",
    ),
    (
        "pending_without_requested",
        "SELECT q.request_id AS ref FROM requests q JOIN runs r ON r.run_id = q.run_id"
        " WHERE q.state = 'pending' AND r.state != 'requested'",
    ),
    (
        "request_before_registered",
        "SELECT DISTINCT r.run_id AS ref FROM runs r JOIN requests q ON q.run_id = r.run_id"
        " WHERE r.state IN ('registering', 'registration_failed')",
    ),
    (
        "segment_supervision_missing",
        "SELECT segment_id AS ref FROM segments WHERE finalized_utc IS NULL"
        " AND (supervision IS NULL OR supervision NOT IN ('job', 'manual'))",
    ),
    (
        "job_session_missing",
        "SELECT segment_id AS ref FROM segments WHERE finalized_utc IS NULL"
        " AND supervision = 'job' AND win_session IS NULL",
    ),
    (
        "manual_identity_missing",
        "SELECT segment_id AS ref FROM segments WHERE supervision = 'manual' AND job = 1"
        " AND (wrapper_pid IS NULL OR wrapper_created IS NULL OR boot_id IS NULL"
        " OR win_session IS NULL OR job_name IS NULL OR job_name = '')",
    ),
    (
        "prompt_in_ruling_and_attach",
        "SELECT DISTINCT c.prompt_id AS ref FROM consumed_rulings c"
        " JOIN attaches a ON a.prompt_id = c.prompt_id",
    ),
)


def find_invariant_failures(tx: Tx) -> list[dict[str, Any]]:
    """Return one entry per broken invariant, with the rows that break it."""
    failures: list[dict[str, Any]] = []
    integrity = [str(r[0]) for r in tx.rows("PRAGMA quick_check")]
    if integrity != ["ok"]:
        failures.append({"invariant": "quick_check", "refs": integrity[:20]})
    params = {"stale": tx.ctx.ago(STALE_PENDING_S)}
    for name, sql in INVARIANTS:
        bound = params if ":stale" in sql else {}
        refs = [str(r["ref"]) for r in tx.con.execute(sql, bound).fetchall()]
        if refs:
            failures.append({"invariant": name, "refs": refs})
    return failures


def verb_clear_check(tx: Tx, note: str) -> Outcome:
    """Clear the ``check_failed`` flag with the human's note."""
    flag = tx.row(
        "SELECT value_json, set_utc FROM store_flags WHERE flag = 'check_failed'"
    )
    if flag is None:
        return Outcome("no_change", {"check_flag": None})
    tx.con.execute("DELETE FROM store_flags WHERE flag = 'check_failed'")
    log(
        "check_flag_cleared",
        note=note,
        set_utc=flag["set_utc"],
        invariants=flag["value_json"],
    )
    return Outcome("changed", {"cleared": json.loads(str(flag["value_json"]))})


# --- verbs: registration --------------------------------------------------------------


@dataclass(frozen=True)
class Manifest:
    """The fields of a validated ``credits-run.v1`` manifest that the store keeps."""

    text: str
    sha256: str
    kind: str
    lane: str
    segment_cap_usd: float
    run_cap_usd: float
    timeout_sec: int
    depends_on: tuple[tuple[str, tuple[str, ...]], ...] = ()


def _positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise Refusal("manifest_invalid", f"{name} must be a number")
    if not math.isfinite(float(value)) or float(value) <= 0:
        raise Refusal("manifest_invalid", f"{name} must be > 0")
    return float(value)


def _repo_relative(value: Any) -> bool:
    """True for a repository-relative POSIX path: no root, no drive, no backslash, no ``..``."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.startswith("/") or "\\" in value or re.match(r"^[A-Za-z]:", value):
        return False
    parts = value.rstrip("/").split("/")
    return all(part not in ("", ".", "..") for part in parts)


def parse_depends_on(
    value: Any, run_id: str
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Validate ``depends_on`` (R§5.4.3): items of exactly ``{run_id, require}``.

    ``require`` is a non-empty list of distinct ``PREDICATES``; a run never depends on
    itself and names a predecessor once. Any defect is ``manifest_invalid``.
    """
    if not isinstance(value, list):
        raise Refusal("manifest_invalid", "depends_on must be a list")
    seen: set[str] = set()
    items: list[tuple[str, tuple[str, ...]]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"run_id", "require"}:
            raise Refusal(
                "manifest_invalid", "each depends_on item is exactly {run_id, require}"
            )
        predecessor = item["run_id"]
        require = item["require"]
        if not isinstance(predecessor, str) or not KEY_RE.match(predecessor):
            raise Refusal("manifest_invalid", "depends_on run_id must be a run id")
        if predecessor == run_id:
            raise Refusal("manifest_invalid", "a run cannot depend on itself")
        if predecessor in seen:
            raise Refusal(
                "manifest_invalid", f"depends_on names {predecessor} more than once"
            )
        if (
            not isinstance(require, list)
            or not require
            or not all(isinstance(name, str) for name in require)
            or len(set(require)) != len(require)
            or any(name not in PREDICATES for name in require)
        ):
            raise Refusal(
                "manifest_invalid",
                f"require must be a non-empty set of {', '.join(PREDICATES)}",
            )
        seen.add(predecessor)
        items.append((predecessor, tuple(require)))
    return tuple(items)


def parse_chain(value: Any) -> tuple[str, float]:
    """Validate a ``chain`` block (R§5.4.4) and return (chain id, chain cap)."""
    if not isinstance(value, dict) or set(value) != CHAIN_KEYS:
        raise Refusal(
            "manifest_invalid",
            "chain is exactly {chain_id, quote, given_at, chain_cap_usd}",
        )
    chain_id = value["chain_id"]
    if not isinstance(chain_id, str) or not KEY_RE.match(chain_id):
        raise Refusal("manifest_invalid", "chain.chain_id must be an id")
    for name in ("quote", "given_at"):
        text = value[name]
        if not isinstance(text, str) or not text.strip():
            raise Refusal("manifest_invalid", f"chain.{name} must be a non-empty text")
    return chain_id, _positive(value["chain_cap_usd"], "chain.chain_cap_usd")


def load_manifest(path: str, run_id: str) -> Manifest:
    """Read and validate a ``credits-run.v1`` manifest (R§4.1); any defect is refused."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise Refusal(
            "manifest_unreadable", f"cannot read the manifest: {exc}"
        ) from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal("manifest_invalid", f"the manifest is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise Refusal("manifest_invalid", "the manifest must be a JSON object")
    unknown = sorted(set(data) - MANIFEST_KEYS)
    if unknown:
        raise Refusal("manifest_invalid", f"unknown manifest keys: {unknown}")
    if data.get("schema") != "credits-run.v1":
        raise Refusal("manifest_invalid", "schema must be credits-run.v1")
    if data.get("run_id") != run_id:
        raise Refusal("manifest_invalid", "the manifest run_id differs from --run-id")
    kind = data.get("kind")
    if kind not in ("plan", "exec"):
        raise Refusal("manifest_invalid", "kind must be plan or exec")
    lane = data.get("lane")
    if not isinstance(lane, str) or not lane.strip():
        raise Refusal("manifest_invalid", "lane must be a non-empty string")
    launch = data.get("launch")
    budget = data.get("budget")
    messaging = data.get("messaging", {})
    if not isinstance(launch, dict) or not isinstance(budget, dict):
        raise Refusal("manifest_invalid", "launch and budget must be objects")
    if not isinstance(messaging, dict):
        raise Refusal("manifest_invalid", "messaging must be an object")
    segment_cap = _positive(launch.get("segment_cap_usd"), "launch.segment_cap_usd")
    run_cap = _positive(budget.get("run_cap_usd"), "budget.run_cap_usd")
    timeout = launch.get("timeout_sec")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise Refusal("manifest_invalid", "launch.timeout_sec must be an integer > 0")
    wait_min = messaging.get("gate_wait_max_min", 0)
    ruling = messaging.get("ruling_enabled", False)
    if isinstance(wait_min, bool) or not isinstance(wait_min, int) or wait_min < 0:
        raise Refusal(
            "manifest_invalid", "messaging.gate_wait_max_min must be an integer >= 0"
        )
    if not isinstance(ruling, bool):
        raise Refusal(
            "manifest_invalid", "messaging.ruling_enabled must be true or false"
        )
    if wait_min > 0 and not ruling:
        raise Refusal(
            "manifest_invalid", "gate_wait_max_min > 0 needs ruling_enabled (R§4.1)"
        )
    if wait_min * 60 + 15 * 60 > timeout:
        raise Refusal(
            "manifest_invalid",
            "gate_wait_max_min plus a 15-minute margin is above launch.timeout_sec",
        )
    worktree = data.get("executor_worktree", False)
    if not isinstance(worktree, bool):
        raise Refusal("manifest_invalid", "executor_worktree must be true or false")
    carry = data.get("carry_allowed", [])
    if not isinstance(carry, list) or not all(_repo_relative(e) for e in carry):
        raise Refusal(
            "manifest_invalid", "carry_allowed must list repository-relative paths"
        )
    if carry and not worktree:
        raise Refusal("manifest_invalid", "carry_allowed needs executor_worktree")
    depends = parse_depends_on(data.get("depends_on", []), run_id)
    if "chain" in data:
        parse_chain(data["chain"])
    required = {name for _, require in depends for name in require}
    if "committed" in required and not worktree:
        raise Refusal(
            "committed_needs_worktree",
            "a committed prerequisite needs executor_worktree (R§5.4.3)",
        )
    if kind == "exec" and "parked_verified" in required:
        raise Refusal(
            "plan_to_exec",
            "an exec run never starts on a parked plan; the human gate stays (R§5.4.3)",
        )
    return Manifest(
        text=raw.decode("utf-8"),
        sha256=hashlib.sha256(raw).hexdigest(),
        kind=str(kind),
        lane=lane,
        segment_cap_usd=segment_cap,
        run_cap_usd=run_cap,
        timeout_sec=timeout,
        depends_on=depends,
    )


def stored_chain_blocks(tx: Tx, chain_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Return (run id, chain block) for each stored run whose manifest names ``chain_id``."""
    found: list[tuple[str, dict[str, Any]]] = []
    for row in tx.rows(
        "SELECT run_id, manifest_json FROM runs WHERE manifest_json IS NOT NULL"
        " ORDER BY run_id"
    ):
        try:
            loaded = json.loads(str(row["manifest_json"]))
        except json.JSONDecodeError:
            continue
        chain = loaded.get("chain") if isinstance(loaded, dict) else None
        if isinstance(chain, dict) and chain.get("chain_id") == chain_id:
            found.append((str(row["run_id"]), chain))
    return found


def check_chain_block(tx: Tx, run_id: str, manifest: Manifest) -> None:
    """Refuse a chain block that differs from the block a run of the chain holds.

    The runs of one chain share one authorization and one cap (R§4.3, R§5.4.4). A run in
    any state counts, because the chain spend counts every run of the chain.
    """
    doc = json.loads(manifest.text)
    block = doc.get("chain") if isinstance(doc, dict) else None
    if not isinstance(block, dict):
        return
    chain_id = str(block["chain_id"])
    for other, held in stored_chain_blocks(tx, chain_id):
        if other != run_id and held != block:
            raise Refusal(
                "chain_conflict",
                f"run {other} holds another chain block for chain {chain_id};"
                " the runs of one chain share one quote, given_at and chain_cap_usd",
            )


def verb_register(
    tx: Tx, run_id: str, manifest: Manifest, args: argparse.Namespace
) -> Outcome:
    """Import a manifest: a new run in ``registering``; a repeat with the same manifest is no change."""
    found = tx.row(
        "SELECT state, manifest_sha256 FROM runs WHERE run_id = ?", (run_id,)
    )
    if found is not None:
        if found["state"] not in ("registering", "registration_failed"):
            raise Refusal("already_started", f"run {run_id} is {found['state']}")
        if found["manifest_sha256"] != manifest.sha256:
            raise Refusal("manifest_changed", f"run {run_id} has another manifest")
        return Outcome("no_change", {"run_id": run_id, "state": found["state"]})
    for predecessor, _ in manifest.depends_on:
        if tx.row("SELECT 1 FROM runs WHERE run_id = ?", (predecessor,)) is None:
            raise Refusal(
                "predecessor_unknown",
                f"depends_on names {predecessor}, which is no run",
            )
    check_chain_block(tx, run_id, manifest)
    now = tx.ctx.now_utc
    tx.con.execute(
        "INSERT INTO runs (run_id, state, kind, supervision, lane, manifest_json, manifest_sha256,"
        " segment_cap_usd, run_cap_usd, timeout_sec, cli_version, kit_revision, created_utc, updated_utc)"
        " VALUES (?, 'registering', ?, 'job', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            manifest.kind,
            manifest.lane,
            manifest.text,
            manifest.sha256,
            manifest.segment_cap_usd,
            manifest.run_cap_usd,
            manifest.timeout_sec,
            args.cli_version,
            args.kit_revision,
            now,
            now,
        ),
    )
    tx.created("run", run_id, "registering")
    return Outcome("changed", {"run_id": run_id, "state": "registering"})


def verb_registered(tx: Tx, run_id: str, task_hash: str) -> Outcome:
    """``registering`` or ``registration_failed`` → ``registered`` (both tasks read back)."""
    run = get_run(tx, run_id)
    state = str(run["state"])
    if state == "registered":
        return Outcome("no_change", {"run_id": run_id, "state": state})
    if state not in ("registering", "registration_failed"):
        raise Refusal("invalid_transition", f"run {run_id} is {state}, not registering")
    tx.move("run", run_id, state, "registered", {"task_hash": task_hash})
    return Outcome("changed", {"run_id": run_id, "state": "registered"})


def verb_registration_failed(tx: Tx, run_id: str, reason: str) -> Outcome:
    """``registering`` → ``registration_failed``; the repair may run again."""
    run = get_run(tx, run_id)
    state = str(run["state"])
    if state == "registration_failed":
        return Outcome("no_change", {"run_id": run_id, "state": state})
    if state != "registering":
        raise Refusal("invalid_transition", f"run {run_id} is {state}, not registering")
    tx.move(
        "run", run_id, state, "registration_failed", {"registration_reason": reason}
    )
    return Outcome("changed", {"run_id": run_id, "state": "registration_failed"})


# --- verbs: start ---------------------------------------------------------------------


def verb_request(tx: Tx, args: argparse.Namespace) -> Outcome:
    """Write a ``pending`` start request and move the run to ``requested`` (R§4.2).

    A resume request carries its mode (``session`` unless ``fresh`` is named) and an optional
    brief, an absolute path to an existing file (R§5.3); neither belongs to a first start.
    """
    run = get_run(tx, args.run_id)
    state = str(run["state"])
    if not args.resume and (args.resume_mode or args.brief):
        raise Refusal(
            "resume_only", "--resume-mode and --brief belong to a resume (--resume)"
        )
    if args.brief is not None:
        brief = Path(args.brief)
        if not brief.is_absolute() or not brief.is_file():
            raise Refusal(
                "brief_missing",
                f"the resume brief is not an absolute path to a file: {args.brief}",
            )
    if args.resume:
        if state != "stopped":
            raise Refusal(
                "invalid_transition", f"a resume needs a stopped run; run is {state}"
            )
        if args.started_by == "monitor-chain":
            raise Refusal("resume_needs_human", "a chain never covers a resume (D-2)")
    elif state not in FIRST_START_FROM:
        raise Refusal(
            "invalid_transition",
            f"a first start needs registered or waiting; run is {state}",
        )
    if args.started_by == "agent-on-user-chat" and not args.quote:
        raise Refusal("quote_required", "an agent start needs the user's quote")
    if args.started_by == "monitor-chain":
        chain = json.loads(str(run["manifest_json"] or "{}")).get("chain")
        if (
            not args.chain_id
            or not isinstance(chain, dict)
            or chain.get("chain_id") != args.chain_id
        ):
            raise Refusal("no_chain", "the run's manifest has no such chain")
    request_id = args.request_id or str(uuid.uuid4())
    now = tx.ctx.now_utc
    tx.con.execute(
        "INSERT INTO requests (request_id, run_id, state, previous_state, started_by, start_quote,"
        " chain_id, resume, resume_mode, brief, requested_by, created_utc, updated_utc)"
        " VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            request_id,
            args.run_id,
            state,
            args.started_by,
            args.quote,
            args.chain_id,
            1 if args.resume else 0,
            (args.resume_mode or "session") if args.resume else None,
            args.brief,
            args.requested_by,
            now,
            now,
        ),
    )
    tx.created("request", request_id, "pending")
    tx.move("run", args.run_id, state, "requested", {"previous_state": state})
    return Outcome("changed", {"run_id": args.run_id, "request_id": request_id})


def verb_not_started(tx: Tx, request_id: str, reason: str) -> Outcome:
    """Compare-and-set a ``pending`` request to ``not_started`` (caller timeout or orphan)."""
    request = tx.row("SELECT * FROM requests WHERE request_id = ?", (request_id,))
    if request is None:
        raise Refusal("unknown_request", f"no request {request_id}")
    if request["state"] == "not_started":
        return Outcome("no_change", {"request_id": request_id})
    if request["state"] != "pending":
        raise Refusal(
            "conflict",
            f"request {request_id} is {request['state']}",
            result="conflict",
            state=request["state"],
        )
    wait = CALLER_TIMEOUT_S if reason == "caller_timeout" else ORPHAN_AGE_S + 1
    if str(request["created_utc"]) > tx.ctx.ago(wait):
        raise Refusal("too_early", f"request {request_id} is younger than {wait} s")
    not_start(tx, request, reason)
    return Outcome("changed", {"request_id": request_id, "reason": reason})


def verb_accept(tx: Tx, args: argparse.Namespace) -> Outcome:
    """Accept the run's one pending request (younger than 120 s) and write the attempt."""
    run = get_run(tx, args.run_id)
    pending = pending_requests(tx, args.run_id)
    if not pending:
        raise Refusal("no_request", f"run {args.run_id} has no pending request")
    if len(pending) > 1:
        raise Refusal(
            "request_ambiguous",
            f"run {args.run_id} has {len(pending)} pending requests",
        )
    request = pending[0]
    request_id = str(request["request_id"])
    created = str(request["created_utc"])
    if created <= tx.ctx.ago(ACCEPT_MAX_AGE_S):
        not_start(tx, request, "stale_at_launcher")
        age = int((tx.ctx.now - parse_utc(created)).total_seconds())
        return Outcome(
            "changed",
            {
                "outcome": "stale_at_launcher",
                "request_id": request_id,
                "created_utc": created,
                "age_s": age,
                "limit_s": ACCEPT_MAX_AGE_S,
            },
        )
    if run["state"] != "requested":
        raise Refusal("invalid_transition", f"run {args.run_id} is {run['state']}")
    session = args.expected_session_id
    if session is None and request["resume"] and request["resume_mode"] != "fresh":
        last = tx.row(
            "SELECT expected_session_id FROM segments WHERE run_id = ?"
            " AND expected_session_id IS NOT NULL ORDER BY created_utc DESC, rowid DESC LIMIT 1",
            (args.run_id,),
        )
        session = None if last is None else str(last["expected_session_id"])
    session = session or str(uuid.uuid4())
    attempt_id = args.attempt_id or str(uuid.uuid4())
    dispatch_id = args.dispatch_id or str(uuid.uuid4())
    now = tx.ctx.now_utc
    tx.move("request", request_id, "pending", "accepted")
    tx.con.execute(
        "INSERT INTO attempts (attempt_id, request_id, run_id, dispatch_id, expected_session_id,"
        " launcher_pid, launcher_created, boot_id, win_session, state, created_utc, updated_utc)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'accepted', ?, ?)",
        (
            attempt_id,
            request_id,
            args.run_id,
            dispatch_id,
            session,
            args.launcher_pid,
            args.launcher_created,
            args.boot_id,
            args.win_session,
            now,
            now,
        ),
    )
    tx.created("attempt", attempt_id, "accepted")
    tx.move("run", args.run_id, "requested", "launching")
    return Outcome(
        "changed",
        {
            "outcome": "accepted",
            "request_id": request_id,
            "attempt_id": attempt_id,
            "dispatch_id": dispatch_id,
            "expected_session_id": session,
            "resume": bool(request["resume"]),
        },
    )


def verb_admit(
    tx: Tx, attempt_id: str, segment_id: str | None, base: str | None = None
) -> Outcome:
    """Admit an accepted attempt: lane, run, predicates, budget and floor; then the segment.

    A resumed segment gets the request's brief, and the same transaction closes each open
    ``stop-after-row`` as ``superseded_by_resume`` (R§4.6.4 step 8, MX-19). Every other open
    message stays open: no delivery row exists for the new segment, so it is pending there.

    A run with ``depends_on`` or an executor worktree is bound to a base B (``--base``, else
    the project's HEAD), recorded on the segment and returned as ``base_commit``; an
    unresolvable B is refused and nothing is written. With ``depends_on`` the predicates are
    checked at B (``predicate_false``) and ``carry_allowed`` may not meet a predecessor's
    paths (``carry_overlaps_prerequisite``). A resume of a run whose base is fixed (the
    run-side ``tree`` recorded it) keeps that base and checks nothing again (R§5.4.3).
    """
    flag = tx.row("SELECT set_utc FROM store_flags WHERE flag = 'check_failed'")
    if flag is not None:
        raise Refusal(
            "store_check_failed",
            "the store check failed; a human clears it with clear_check --note",
        )
    attempt = tx.row("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,))
    if attempt is None:
        raise Refusal("unknown_attempt", f"no attempt {attempt_id}")
    if attempt["state"] == "admitted":
        return Outcome("no_change", {"outcome": "admitted", "attempt_id": attempt_id})
    if attempt["state"] != "accepted":
        raise Refusal(
            "invalid_transition", f"attempt {attempt_id} is {attempt['state']}"
        )
    run_id = str(attempt["run_id"])
    run = get_run(tx, run_id)
    if run["state"] != "launching":
        raise Refusal("invalid_transition", f"run {run_id} is {run['state']}")
    request = get_request(tx, str(attempt["request_id"]))
    resume = bool(request["resume"])
    lane = run["lane"]
    doc = manifest_doc(run)
    depends = parse_depends_on(doc.get("depends_on", []), run_id)
    bound = bool(depends) or doc.get("executor_worktree") is True
    base_commit: str | None = None
    root: str | None = None
    if resume and run["base_fixed"] == 1 and run["base_commit"] is not None:
        base_commit = str(run["base_commit"])
        if base is not None and base != base_commit:
            raise Refusal(
                "base_fixed", f"run {run_id} is fixed at {base_commit}, not {base}"
            )
    elif bound:
        root = project_root(doc)
        base_commit = resolve_base(root, base)

    reason: str | None = None
    reservation = 0.0
    if lane is not None and tx.row(
        "SELECT 1 FROM lanes WHERE lane = ? AND segment_id IS NOT NULL", (lane,)
    ):
        reason = "lane_busy"
    elif tx.row(
        "SELECT 1 FROM segments WHERE run_id = ? AND finalized_utc IS NULL", (run_id,)
    ):
        reason = "run_busy"
    else:
        report = (
            check_predicates(tx, run_id, depends, root, base_commit)
            if depends and root is not None and base_commit is not None
            else None
        )
        if report is not None and not report.holds:
            reason = "predicate_false"
        elif report is not None and carry_overlaps(
            doc.get("carry_allowed", []), report.paths
        ):
            reason = "carry_overlaps_prerequisite"
        else:
            spent = run_spend(tx, run_id)
            remaining = float(run["run_cap_usd"]) - sum(spent.values())
            rooms = [float(run["segment_cap_usd"]), remaining]
            if "chain" in doc:
                chain_id, chain_cap = parse_chain(doc["chain"])
                rooms.append(chain_room(tx, chain_id, chain_cap))
            reservation = money(min(rooms))
            if reservation < FLOOR_USD:
                reason = "budget_floor"

    request_id = str(request["request_id"])
    if reason is not None:
        tx.move("request", request_id, "accepted", "rejected", {"reason": reason})
        tx.move("attempt", attempt_id, "accepted", "rejected", {"reason": reason})
        if resume:
            tx.move("run", run_id, "launching", "stopped")
            tx.notice("resume_refused", attempt_id, run_id, {"reason": reason})
        elif reason in ("budget_floor", "carry_overlaps_prerequisite"):
            tx.move("run", run_id, "launching", "failed", {"stop_class": reason})
            tx.notice("start_refused", attempt_id, run_id, {"reason": reason})
        else:
            tx.move("run", run_id, "launching", "waiting")
        return Outcome(
            "changed",
            {"outcome": "rejected", "reason": reason, "attempt_id": attempt_id},
        )

    segment_id = segment_id or str(uuid.uuid4())
    session = str(attempt["expected_session_id"])
    resume_mode: str | None = None
    if resume:
        earlier = tx.row(
            "SELECT 1 FROM segments WHERE run_id = ? AND expected_session_id = ?",
            (run_id, session),
        )
        resume_mode = "session" if earlier else "fresh"
    now = tx.ctx.now_utc
    deadline = format_utc(tx.ctx.now + timedelta(seconds=int(run["timeout_sec"])))
    tx.con.execute(
        "INSERT INTO segments (segment_id, run_id, attempt_id, request_id, dispatch_id,"
        " expected_session_id, supervision, job, lane, reservation_usd, state, launcher_pid,"
        " launcher_created, boot_id, win_session, job_name, resume, brief, base_commit,"
        " segment_deadline_utc, created_utc, updated_utc)"
        " VALUES (?, ?, ?, ?, ?, ?, 'job', 1, ?, ?, 'launching', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            segment_id,
            run_id,
            attempt_id,
            request_id,
            attempt["dispatch_id"],
            session,
            lane,
            reservation,
            attempt["launcher_pid"],
            attempt["launcher_created"],
            attempt["boot_id"],
            attempt["win_session"],
            JOB_NAME_PREFIX + segment_id,
            resume_mode,
            request["brief"],
            base_commit,
            deadline,
            now,
            now,
        ),
    )
    tx.created("segment", segment_id, "launching")
    if lane is not None:
        tx.con.execute(
            "INSERT INTO lanes (lane, segment_id, claimed_utc) VALUES (?, ?, ?)"
            " ON CONFLICT (lane) DO UPDATE SET segment_id = excluded.segment_id,"
            " claimed_utc = excluded.claimed_utc WHERE lanes.segment_id IS NULL",
            (lane, segment_id, now),
        )
        holder = tx.row("SELECT segment_id FROM lanes WHERE lane = ?", (lane,))
        if holder is None or holder["segment_id"] != segment_id:
            raise Refusal(
                "conflict", f"lane {lane} was claimed first", result="conflict"
            )
    superseded = supersede_stop_after_row(tx, run_id) if resume else []
    tx.move("request", request_id, "accepted", "admitted")
    tx.move("attempt", attempt_id, "accepted", "admitted")
    return Outcome(
        "changed",
        {
            "outcome": "admitted",
            "attempt_id": attempt_id,
            "segment_id": segment_id,
            "reservation_usd": reservation,
            "job_name": JOB_NAME_PREFIX + segment_id,
            "resume": resume_mode,
            "brief": request["brief"],
            "superseded": superseded,
            "base_commit": base_commit,
        },
    )


def verb_launched(tx: Tx, args: argparse.Namespace) -> Outcome:
    """``launching`` → ``running``: pid, creation time and boot id recorded."""
    segment = get_segment(tx, args.segment_id)
    if (
        segment["state"] == "running"
        and segment["pid"] == args.pid
        and segment["created"] == args.created
    ):
        return Outcome("no_change", {"segment_id": args.segment_id})
    if segment["state"] != "launching":
        raise Refusal(
            "invalid_transition", f"segment {args.segment_id} is {segment['state']}"
        )
    if segment["boot_id"] != args.boot_id:
        raise Refusal(
            "boot_mismatch", "the boot id differs from the launcher's boot id"
        )
    tx.move(
        "segment",
        args.segment_id,
        "launching",
        "running",
        {"pid": args.pid, "created": args.created, "last_alive_utc": tx.ctx.now_utc},
    )
    for entity, key in (
        ("request", segment["request_id"]),
        ("attempt", segment["attempt_id"]),
    ):
        tx.move(entity, str(key), "admitted", "launched")
    run_id = str(segment["run_id"])
    run = get_run(tx, run_id)
    if run["state"] == "launching":
        tx.move("run", run_id, "launching", "running")
    elif run["state"] != "cancelled":
        raise Refusal("conflict", f"run {run_id} is {run['state']}", result="conflict")
    return Outcome("changed", {"segment_id": args.segment_id})


def finalize_segment(
    tx: Tx,
    segment: sqlite3.Row,
    by: str,
    stop_class: str,
    total: float | None,
    exit_code: int | None,
) -> dict[str, Any]:
    """Finalize a segment in the open transaction (R§4.7 ``Complete-CreditsSegment`` steps 1-6)."""
    segment_id = str(segment["segment_id"])
    run_id = str(segment["run_id"])
    state = str(segment["state"])
    session = segment["expected_session_id"]
    now = tx.ctx.now_utc
    launch_failed = state == "launching"
    if launch_failed:
        stop_class = "launch_failed"

    top = tx.row(
        "SELECT MAX(session_total_usd) AS top FROM segments WHERE run_id = ?"
        " AND expected_session_id IS ? AND cost_known = 1 AND segment_id != ?",
        (run_id, session, segment_id),
    )
    previous = 0.0 if top is None or top["top"] is None else float(top["top"])
    trusted = total is not None and total > 0 and total >= previous
    reservation = float(segment["reservation_usd"])
    sets: dict[str, Any] = {
        "session_total_usd": total,
        "segment_delta_usd": money(total - previous)
        if trusted and total is not None
        else None,
        "cost_known": 1 if trusted else 0,
        "reservation_released_utc": now,
        "finalized_utc": now,
        "finalized_by": by,
        "stop_class": stop_class,
        "exit_code": exit_code,
    }
    tx.move("segment", segment_id, state, "finalized", sets, owner=by)
    if not trusted:
        tx.con.execute(
            "INSERT INTO exposures (segment_id, run_id, exposed_usd, amount_usd, state, created_utc)"
            " VALUES (?, ?, ?, ?, 'open', ?)",
            (segment_id, run_id, reservation, reservation, now),
        )
        tx.created("exposure", segment_id, "open", owner=by)
    tx.con.execute(
        "UPDATE lanes SET segment_id = NULL, claimed_utc = NULL WHERE segment_id = ?",
        (segment_id,),
    )

    gate = tx.row(
        "SELECT gate_id FROM gates WHERE run_id = ? AND state = 'open'", (run_id,)
    )
    if gate is not None:
        gate_id = str(gate["gate_id"])
        tx.con.execute(
            "UPDATE gates SET state = 'abandoned', closed_utc = ?, closed_reason = 'segment_finalized'"
            " WHERE gate_id = ? AND state = 'open'",
            (now, gate_id),
        )
        tx.con.execute(
            "INSERT OR IGNORE INTO outbox_events (run_id, kind, semantic_key, payload_json, created_utc)"
            " VALUES (?, 'gate_expired', ?, ?, ?)",
            (
                run_id,
                f"gate_expired:{gate_id}",
                json.dumps({"segment_id": segment_id}),
                now,
            ),
        )

    for entity, key in (
        ("request", segment["request_id"]),
        ("attempt", segment["attempt_id"]),
    ):
        if key is None:
            continue
        table, key_col = ENTITY_TABLES[entity]
        current = tx.row(f"SELECT state FROM {table} WHERE {key_col} = ?", (key,))
        if current is not None and current["state"] in ("accepted", "admitted"):
            tx.move(entity, str(key), str(current["state"]), "launch_failed", owner=by)

    run = get_run(tx, run_id)
    run_state = str(run["state"])
    if launch_failed and run_state == "launching":
        resume = segment["resume"] is not None
        tx.move(
            "run",
            run_id,
            "launching",
            "stopped" if resume else "failed",
            {"stop_class": "launch_failed"},
            owner=by,
        )
    elif run_state in ("running", "launching"):
        tx.move("run", run_id, run_state, "finalizing", owner=by)

    if by == "launcher":
        tx.effect(f"evtlog:{segment_id}", "evtlog", segment_id)
    tx.effect(f"rescan:{segment_id}", "rescan", segment_id)
    return {
        "segment_id": segment_id,
        "cost_known": trusted,
        "exposure_usd": None if trusted else reservation,
        "stop_class": stop_class,
    }


def verb_complete_segment(tx: Tx, args: argparse.Namespace) -> Outcome:
    """Finalize a segment once; a second call finds ``finalized_utc`` set and changes nothing."""
    segment = get_segment(tx, args.segment_id)
    if segment["finalized_utc"] is not None:
        return Outcome(
            "no_change",
            {"segment_id": args.segment_id, "finalized_by": segment["finalized_by"]},
        )
    supervision = str(segment["supervision"])
    if args.finalized_by == "wrapper" and supervision != "manual":
        raise Refusal(
            "wrong_owner", "only a manual segment is finalized by its wrapper"
        )
    if args.finalized_by == "launcher" and supervision != "job":
        raise Refusal("wrong_owner", "a manual segment has no launcher")
    payload = finalize_segment(
        tx,
        segment,
        args.finalized_by,
        args.stop_class,
        args.session_total_usd,
        args.exit_code,
    )
    return Outcome("changed", payload)


def verb_classify(
    tx: Tx,
    run_id: str,
    target: str,
    stop_class: str,
    notice_ref: str | None = None,
    notice_body: dict[str, Any] | None = None,
) -> Outcome:
    """``finalizing`` → ``stopped``, ``parked``, ``done`` or ``done_unverified``.

    With ``notice_body``, the same transaction files the stop notice ``stop:<ref>`` (the ref
    defaults to the run id), so a class never lands without its notice (R§4.4, AC-E.4).
    """
    run = get_run(tx, run_id)
    state = str(run["state"])
    if state == target:
        return Outcome("no_change", {"run_id": run_id, "state": state})
    if state != "finalizing":
        raise Refusal("invalid_transition", f"run {run_id} is {state}, not finalizing")
    tx.move("run", run_id, "finalizing", target, {"stop_class": stop_class})
    if notice_body is not None:
        body = {**notice_body, "run_id": run_id, "state": target, "class": stop_class}
        tx.notice("stop", notice_ref or run_id, run_id, body)
    return Outcome("changed", {"run_id": run_id, "state": target})


def verb_cancel(tx: Tx, run_id: str, reason: str | None) -> Outcome:
    """Any non-terminal run → ``cancelled``; pending requests end, live segments get the cancel mark."""
    run = get_run(tx, run_id)
    state = str(run["state"])
    if state == "cancelled":
        return Outcome("no_change", {"run_id": run_id})
    if state in TERMINAL_RUN_STATES:
        raise Refusal(
            "invalid_transition", f"run {run_id} is {state}, which is terminal"
        )
    for request in pending_requests(tx, run_id):
        tx.move(
            "request",
            str(request["request_id"]),
            "pending",
            "not_started",
            {"reason": "cancelled"},
        )
    live = tx.rows(
        "SELECT segment_id FROM segments WHERE run_id = ? AND finalized_utc IS NULL",
        (run_id,),
    )
    for segment in live:
        tx.con.execute(
            "UPDATE segments SET cancel_requested_utc = ?, updated_utc = ? WHERE segment_id = ?",
            (tx.ctx.now_utc, tx.ctx.now_utc, segment["segment_id"]),
        )
    tx.move(
        "run",
        run_id,
        state,
        "cancelled",
        {"stop_class": "cancelled", "registration_reason": reason}
        if reason
        else {"stop_class": "cancelled"},
    )
    return Outcome(
        "changed",
        {"run_id": run_id, "cancel_requested": [str(s["segment_id"]) for s in live]},
    )


# --- verbs: chains (S5, R§5.4) ------------------------------------------------------------


def manifest_doc(run: sqlite3.Row) -> dict[str, Any]:
    """The stored manifest of a run; a run without one (manual supervision) gives ``{}``."""
    text = run["manifest_json"]
    if not text:
        return {}
    try:
        loaded = json.loads(str(text))
    except json.JSONDecodeError as exc:
        raise Refusal(
            "manifest_invalid", f"run {run['run_id']} has an unreadable manifest"
        ) from exc
    return loaded if isinstance(loaded, dict) else {}


def project_root(doc: dict[str, Any]) -> str:
    """The manifest's ``project_root``: the main tree the predicates read."""
    root = doc.get("project_root")
    if not isinstance(root, str) or not os.path.isdir(root):
        raise Refusal("project_root_missing", f"project_root {root!r} is not a folder")
    return root


def _git(root: str, args: Sequence[str]) -> bytes:
    """Run one git command in ``root`` and return its stdout; a failure is ``git_failed``."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROPPED}
    try:
        proc = subprocess.run(
            ["git", "--literal-pathspecs", *args],
            cwd=root,
            capture_output=True,
            env=env,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refusal("git_failed", f"git {' '.join(args[:3])}: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise Refusal(
            "git_failed", f"git {' '.join(args[:3])} exit {proc.returncode}: {detail}"
        )
    return proc.stdout


def _z_split(data: bytes) -> list[str]:
    return [part.decode("utf-8", "replace") for part in data.split(b"\0") if part]


def resolve_base(root: str, base: str | None) -> str:
    """Resolve B (``base``, else HEAD) to a commit id; an unknown B is ``base_unknown``."""
    rev = base or "HEAD"
    try:
        found = _git(root, ["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"])
    except Refusal as exc:
        raise Refusal("base_unknown", f"{rev} is not a commit in {root}") from exc
    commit = found.decode("utf-8", "replace").strip()
    if not commit:
        raise Refusal("base_unknown", f"{rev} is not a commit in {root}")
    return commit


def blobs_at(root: str, commit: str) -> dict[str, str]:
    """Every file path of ``commit`` with its object id."""
    blobs: dict[str, str] = {}
    for entry in _z_split(_git(root, ["ls-tree", "-r", "-z", "--full-tree", commit])):
        meta, _, path = entry.partition("\t")
        fields = meta.split()
        if len(fields) == 3:
            blobs[path] = fields[2]
    return blobs


def dirty_paths(root: str) -> set[str]:
    """Every path of the main tree that differs from its index or HEAD, untracked included."""
    out = _git(
        root,
        [
            *EOL_PIN,
            "status",
            "--porcelain",
            "-z",
            "--no-renames",
            "--untracked-files=all",
        ],
    )
    return {entry[3:] for entry in _z_split(out) if len(entry) > 3}


def landing_rows(tx: Tx, run_id: str) -> tuple[dict[str, str], dict[str, str], bool]:
    """(product rows, closeout rows, sealed) of a run's landing."""
    product: dict[str, str] = {}
    closeout: dict[str, str] = {}
    sealed = True
    for row in tx.rows(
        "SELECT part, path, blob, sealed_utc FROM landings WHERE run_id = ?", (run_id,)
    ):
        if row["part"] == "product":
            product[str(row["path"])] = str(row["blob"])
        else:
            closeout[str(row["path"])] = str(row["blob"])
            sealed = sealed and row["sealed_utc"] is not None
    return product, closeout, sealed and bool(closeout)


def blob_mismatches(at_base: dict[str, str], rows: dict[str, str]) -> set[str]:
    """The row paths whose blob B does not hold; a deleted or absent row needs no path."""
    return {
        path
        for path, blob in rows.items()
        if at_base.get(path) != (None if blob in MISSING_BLOBS else blob)
    }


def accepted_drift(tx: Tx, successor: str, predecessor: str, base: str) -> set[str]:
    """The paths that an ``accept_drift`` record covers for (S, P, B)."""
    paths: set[str] = set()
    for row in tx.rows(
        "SELECT paths_json FROM drift_accepts"
        " WHERE successor = ? AND predecessor = ? AND commit_id = ?",
        (successor, predecessor, base),
    ):
        loaded = json.loads(str(row["paths_json"] or "[]"))
        paths.update(str(p) for p in loaded if isinstance(p, str))
    return paths


@dataclass(frozen=True)
class PredicateReport:
    """The predicates of a run's ``depends_on`` at one base B (R§5.4.3)."""

    holds: bool
    halted: bool
    entries: list[dict[str, Any]]
    # D: every path of every predecessor's landing (AC-G.3).
    paths: frozenset[str]


def check_predicates(
    tx: Tx,
    successor: str,
    depends: Sequence[tuple[str, tuple[str, ...]]],
    root: str,
    base: str,
) -> PredicateReport:
    """Evaluate each predecessor's required predicates at B (R§5.4.3, AC-G.1).

    A predecessor that is stopped, done_unverified, failed or cancelled, or an exec run done
    with no product part or no seal, is halted: every predicate is false. ``committed``
    needs the landing and the seal, B holding every product and closeout blob (a deleted or
    absent row: no such path), less what an ``accept_drift`` record for (S, P, B) covers,
    and a clean main tree on those paths.
    """
    entries: list[dict[str, Any]] = []
    paths: set[str] = set()
    holds = True
    halted_any = False
    at_base: dict[str, str] | None = None
    dirty: set[str] | None = None
    for predecessor, require in depends:
        run = get_run(tx, predecessor)
        product, closeout, sealed = landing_rows(tx, predecessor)
        state = str(run["state"])
        kind = str(run["kind"])
        landed = run["capture_tree"] is not None and bool(product)
        halted = state in HALTED_RUN_STATES or (
            kind == "exec" and state == "done" and not (product and sealed)
        )
        rows = {**product, **closeout}
        paths.update(rows)
        failing: list[str] = []
        committed = False
        if "committed" in require:
            if at_base is None:
                at_base = blobs_at(root, base)
            if dirty is None:
                dirty = dirty_paths(root)
            drift = blob_mismatches(at_base, rows) - accepted_drift(
                tx, successor, predecessor, base
            )
            failing = sorted(drift | (dirty & set(rows)))
            committed = landed and sealed and not failing
        values = {
            "done_verified": state == "done"
            and run["stop_class"] == "done"
            and (kind != "exec" or sealed),
            "parked_verified": kind == "plan"
            and state == "parked"
            and run["stop_class"] == "parked",
            "landed": landed,
            "committed": committed,
        }
        results = {name: (values[name] and not halted) for name in require}
        holds = holds and all(results.values())
        halted_any = halted_any or halted
        entries.append(
            {
                "run_id": predecessor,
                "require": list(require),
                "results": results,
                "failing_paths": failing,
                "halted": halted,
            }
        )
    return PredicateReport(holds, halted_any, entries, frozenset(paths))


def carry_overlaps(carry_allowed: Any, paths: frozenset[str]) -> bool:
    """True when a ``carry_allowed`` entry names, holds or sits under a path of D."""
    entries = [e for e in carry_allowed if isinstance(e, str)] if carry_allowed else []
    for entry in entries:
        stem = entry.rstrip("/")
        for path in paths:
            if (
                path == stem
                or path.startswith(stem + "/")
                or stem.startswith(path + "/")
            ):
                return True
    return False


def chain_room(tx: Tx, chain_id: str, cap: float) -> float:
    """The chain cap less the spend of every run of the chain (R§5.4.4).

    The cap is the smallest cap that a run of the chain holds: ``register`` keeps one
    block per chain, and a store that holds two caps never reserves above the smaller
    one.
    """
    spent = 0.0
    for other, block in stored_chain_blocks(tx, chain_id):
        spent += sum(run_spend(tx, other).values())
        held = block.get("chain_cap_usd")
        if isinstance(held, (int, float)) and not isinstance(held, bool) and held > 0:
            cap = min(cap, float(held))
    return money(cap - spent)


def verb_predicates(tx: Tx, run_id: str, base: str | None) -> Outcome:
    """Report the predicates of a run's ``depends_on`` at B (read only; AC-G.1)."""
    run = get_run(tx, run_id)
    doc = manifest_doc(run)
    depends = parse_depends_on(doc.get("depends_on", []), run_id)
    root = project_root(doc)
    commit = resolve_base(root, base)
    report = check_predicates(tx, run_id, depends, root, commit)
    return Outcome(
        "ok",
        {
            "run_id": run_id,
            "base_commit": commit,
            "holds": report.holds,
            "predecessors": report.entries,
        },
    )


def verb_accept_drift(tx: Tx, args: argparse.Namespace) -> Outcome:
    """Record the human's acceptance of P's drift at B for S, with the words (MX-15)."""
    successor, predecessor = str(args.successor), str(args.predecessor)
    run = get_run(tx, successor)
    doc = manifest_doc(run)
    require = dict(parse_depends_on(doc.get("depends_on", []), successor)).get(
        predecessor
    )
    if require is None or "committed" not in require:
        raise Refusal(
            "not_a_prerequisite",
            f"run {successor} does not require {predecessor} committed",
        )
    root = project_root(doc)
    commit = resolve_base(root, args.base)
    found = tx.row(
        "SELECT paths_json FROM drift_accepts"
        " WHERE successor = ? AND predecessor = ? AND commit_id = ?",
        (successor, predecessor, commit),
    )
    if found is not None:
        return Outcome(
            "no_change",
            {
                "successor": successor,
                "predecessor": predecessor,
                "base_commit": commit,
                "paths": json.loads(str(found["paths_json"] or "[]")),
            },
        )
    product, closeout, _ = landing_rows(tx, predecessor)
    drift = sorted(blob_mismatches(blobs_at(root, commit), {**product, **closeout}))
    if not drift:
        raise Refusal("no_drift", f"{commit} holds every blob of {predecessor}")
    tx.con.execute(
        "INSERT INTO drift_accepts (successor, predecessor, commit_id, words, paths_json,"
        " accepted_utc) VALUES (?, ?, ?, ?, ?, ?)",
        (successor, predecessor, commit, args.quote, json.dumps(drift), tx.ctx.now_utc),
    )
    return Outcome(
        "changed",
        {
            "successor": successor,
            "predecessor": predecessor,
            "base_commit": commit,
            "paths": drift,
        },
    )


def verb_prune(tx: Tx, run_id: str) -> Outcome:
    """Delete ``refs/credits/<run>/*`` of a final run (AC-G.7)."""
    run = get_run(tx, run_id)
    if run["state"] not in TERMINAL_RUN_STATES:
        raise Refusal("run_not_final", f"run {run_id} is {run['state']}")
    root = project_root(manifest_doc(run))
    listing = _git(
        root, ["for-each-ref", "--format=%(refname)", f"refs/credits/{run_id}/"]
    )
    names = [line for line in listing.decode("utf-8", "replace").splitlines() if line]
    for name in names:
        _git(root, ["update-ref", "-d", name])
    return Outcome(
        "changed" if names else "no_change", {"run_id": run_id, "deleted": names}
    )


def verb_chain_candidates(tx: Tx) -> Outcome:
    """The chained runs that wait for a start, each with its predicates at HEAD (AC-G.4).

    A candidate is a run with a ``chain`` block, state ``registered`` or ``waiting``, no
    segment and no ``pending`` or ``accepted`` request (R§4.4 step 4). It is ``ready`` when
    its predicates hold, no predecessor is halted and the chain room is at least
    ``FLOOR_USD``. The monitor starts only ready candidates.
    """
    candidates: list[dict[str, Any]] = []
    for run in tx.rows(
        "SELECT * FROM runs r WHERE r.state IN ('registered', 'waiting')"
        " AND NOT EXISTS (SELECT 1 FROM segments s WHERE s.run_id = r.run_id)"
        " AND NOT EXISTS (SELECT 1 FROM requests q WHERE q.run_id = r.run_id"
        " AND q.state IN ('pending', 'accepted'))"
        " ORDER BY r.run_id"
    ):
        run_id = str(run["run_id"])
        doc = manifest_doc(run)
        if "chain" not in doc:
            continue
        chain_id, chain_cap = parse_chain(doc["chain"])
        depends = parse_depends_on(doc.get("depends_on", []), run_id)
        commit: str | None = None
        error: str | None = None
        holds = not depends
        halted = False
        try:
            root = project_root(doc)
            commit = resolve_base(root, None)
            if depends:
                report = check_predicates(tx, run_id, depends, root, commit)
                holds, halted = report.holds, report.halted
        except Refusal as exc:
            error, holds = exc.error, False
        room = chain_room(tx, chain_id, chain_cap)
        candidates.append(
            {
                "run_id": run_id,
                "chain_id": chain_id,
                "state": run["state"],
                "base_commit": commit,
                "holds": holds,
                "halted": halted,
                "chain_room_usd": room,
                "ready": holds and not halted and room >= FLOOR_USD,
                "error": error,
            }
        )
    return Outcome("ok", {"candidates": candidates})


# --- verbs: manual supervision (R§7.2) ---------------------------------------------------


def verb_register_minimal(tx: Tx, args: argparse.Namespace) -> Outcome:
    """A manual run and one ``identity_pending`` job segment with the wrapper's identity.

    With ``--resume`` the run exists and gets a new segment: a new delivery
    generation (R§4.6.4, R§10.2 M-5a).
    """
    if args.job_name != JOB_NAME_PREFIX + args.segment_id:
        raise Refusal(
            "job_name_mismatch", f"the job name must be {JOB_NAME_PREFIX}<segment id>"
        )
    found = tx.row("SELECT * FROM segments WHERE segment_id = ?", (args.segment_id,))
    if found is not None:
        same = (
            found["run_id"] == args.run_id
            and found["wrapper_pid"] == args.wrapper_pid
            and found["wrapper_created"] == args.wrapper_created
        )
        if same:
            return Outcome("no_change", {"segment_id": args.segment_id})
        raise Refusal("segment_exists", f"segment {args.segment_id} exists")
    run = tx.row("SELECT * FROM runs WHERE run_id = ?", (args.run_id,))
    if args.resume:
        return resume_minimal(tx, args, run)
    if run is not None:
        raise Refusal("run_exists", f"run {args.run_id} exists")
    now = tx.ctx.now_utc
    tx.con.execute(
        "INSERT INTO runs (run_id, state, kind, supervision, created_utc, updated_utc)"
        " VALUES (?, 'running', 'manual', 'manual', ?, ?)",
        (args.run_id, now, now),
    )
    tx.created("run", args.run_id, "running")
    insert_manual_segment(tx, args, None)
    return Outcome("changed", {"run_id": args.run_id, "segment_id": args.segment_id})


def insert_manual_segment(
    tx: Tx, args: argparse.Namespace, resume_mode: str | None
) -> None:
    """Insert one ``identity_pending`` manual segment with the wrapper's identity."""
    now = tx.ctx.now_utc
    tx.con.execute(
        "INSERT INTO segments (segment_id, run_id, dispatch_id, expected_session_id, supervision,"
        " job, reservation_usd, state, wrapper_pid, wrapper_created, boot_id, win_session,"
        " job_name, resume, created_utc, updated_utc)"
        " VALUES (?, ?, ?, ?, 'manual', 1, 0, 'identity_pending', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            args.segment_id,
            args.run_id,
            args.dispatch_id,
            args.expected_session_id,
            args.wrapper_pid,
            args.wrapper_created,
            args.boot_id,
            args.win_session,
            args.job_name,
            resume_mode,
            now,
            now,
        ),
    )
    tx.created("segment", args.segment_id, "identity_pending")


def supersede_stop_after_row(tx: Tx, run_id: str) -> list[str]:
    """Close each open ``stop-after-row`` of a run as ``superseded_by_resume`` (MX-19).

    A resume is a new human instruction, so an older stop request no longer applies.
    Returns the closed message ids in ``seq`` order.
    """
    now = tx.ctx.now_utc
    superseded = [
        str(r["msg_id"])
        for r in tx.rows(
            "SELECT msg_id FROM messages WHERE run_id = ? AND kind = 'stop-after-row'"
            " AND state = 'open' ORDER BY seq",
            (run_id,),
        )
    ]
    for msg_id in superseded:
        tx.con.execute(
            "UPDATE messages SET state = 'closed', closed_utc = ?,"
            " closed_reason = 'superseded_by_resume' WHERE msg_id = ? AND state = 'open'",
            (now, msg_id),
        )
        tx.transition("message", msg_id, "open", "closed")
    return superseded


def resume_minimal(
    tx: Tx, args: argparse.Namespace, run: sqlite3.Row | None
) -> Outcome:
    """Add a new segment to a manual run when every older segment is finalized.

    The same transaction closes each open ``stop-after-row`` as
    ``superseded_by_resume`` (MX-19): a resume is a new human instruction.
    """
    run_id = str(args.run_id)
    if run is None:
        raise Refusal("unknown_run", f"no run {run_id}")
    if run["supervision"] != "manual":
        raise Refusal("not_manual", f"run {run_id} is not a manual run")
    state = str(run["state"])
    if state in TERMINAL_RUN_STATES:
        raise Refusal("run_terminal", f"run {run_id} is {state}")
    live = [
        str(r["segment_id"])
        for r in tx.rows(
            "SELECT segment_id FROM segments WHERE run_id = ? AND finalized_utc IS NULL"
            " ORDER BY created_utc, rowid",
            (run_id,),
        )
    ]
    if live:
        raise Refusal(
            "segment_live",
            f"run {run_id} has a segment that is not finalized",
            segments=live,
        )
    earlier = tx.row(
        "SELECT 1 FROM segments WHERE run_id = ? AND expected_session_id = ?",
        (run_id, args.expected_session_id),
    )
    resume_mode = "session" if earlier is not None else "fresh"
    insert_manual_segment(tx, args, resume_mode)
    superseded = supersede_stop_after_row(tx, run_id)
    if state != "running":
        tx.move("run", run_id, state, "running")
    return Outcome(
        "changed",
        {
            "run_id": run_id,
            "segment_id": args.segment_id,
            "resume": resume_mode,
            "superseded": superseded,
        },
    )


def verb_manual_identity(tx: Tx, args: argparse.Namespace) -> Outcome:
    """``identity_pending`` → ``running``: the suspended child's pid and creation time."""
    segment = get_segment(tx, args.segment_id)
    if (
        segment["state"] == "running"
        and segment["pid"] == args.pid
        and segment["created"] == args.created
    ):
        return Outcome("no_change", {"segment_id": args.segment_id})
    if segment["state"] != "identity_pending" or segment["supervision"] != "manual":
        raise Refusal(
            "invalid_transition", f"segment {args.segment_id} is {segment['state']}"
        )
    tx.move(
        "segment",
        args.segment_id,
        "identity_pending",
        "running",
        {"pid": args.pid, "created": args.created, "last_alive_utc": tx.ctx.now_utc},
    )
    return Outcome("changed", {"segment_id": args.segment_id})


# --- verbs: cost ------------------------------------------------------------------------


def verb_settle(tx: Tx, args: argparse.Namespace) -> Outcome:
    """Release an open exposure on Console evidence or a noted human adjustment (R§4.1)."""
    if args.source == "transcript":
        raise Refusal(
            "transcript_not_evidence",
            "the transcript sum is a lower bound and never settles an exposure",
        )
    if args.source == "human" and not args.note:
        raise Refusal("note_required", "a human settle needs --note")
    if args.started_by == "agent-on-user-chat" and not args.quote:
        raise Refusal(
            "quote_required",
            "an agent settles only on the user's chat words; pass them in --quote",
        )
    exposure = tx.row(
        "SELECT state FROM exposures WHERE segment_id = ?", (args.segment_id,)
    )
    if exposure is None or exposure["state"] != "open":
        raise Refusal("no_exposure", f"segment {args.segment_id} has no open exposure")
    target = "settled_console" if args.source == "console" else "human_adjusted"
    settled_by = f"{args.source}:{getpass.getuser()}"
    if args.started_by == "agent-on-user-chat":
        settled_by = f"{settled_by}:agent-on-user-chat:{args.quote}"
    tx.move(
        "exposure",
        args.segment_id,
        "open",
        target,
        {
            "amount_usd": money(args.amount_usd),
            "note": args.note,
            "settled_by": settled_by,
            "settled_utc": tx.ctx.now_utc,
        },
    )
    return Outcome("changed", {"segment_id": args.segment_id, "state": target})


def verb_spend(tx: Tx, run_id: str) -> Outcome:
    """Return the run's spend: known, open exposures, settled and open reservations."""
    run = get_run(tx, run_id)
    return Outcome(
        "ok",
        {"run_id": run_id, "run_cap_usd": run["run_cap_usd"], **run_spend(tx, run_id)},
    )


def verb_run_status(tx: Tx, run_id: str) -> Outcome:
    """Return the run row, manifest, segments, requests and attempts (or ``exists: false``)."""
    run = tx.row("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    if run is None:
        return Outcome("ok", {"run_id": run_id, "exists": False})
    try:
        manifest = json.loads(str(run["manifest_json"] or "null"))
    except json.JSONDecodeError:
        manifest = None
    segments = [
        {
            "segment_id": str(s["segment_id"]),
            "state": str(s["state"]),
            "cancel_requested_utc": s["cancel_requested_utc"],
            "finalized_utc": s["finalized_utc"],
            "finalized_by": s["finalized_by"],
            "stop_class": s["stop_class"],
        }
        for s in tx.rows(
            "SELECT * FROM segments WHERE run_id = ? ORDER BY created_utc, rowid",
            (run_id,),
        )
    ]
    requests = [
        {
            "request_id": str(q["request_id"]),
            "state": str(q["state"]),
            "reason": q["reason"],
            "resume": bool(q["resume"]),
            "created_utc": q["created_utc"],
        }
        for q in tx.rows(
            "SELECT * FROM requests WHERE run_id = ? ORDER BY created_utc, rowid",
            (run_id,),
        )
    ]
    attempts = [
        {
            "attempt_id": str(a["attempt_id"]),
            "request_id": str(a["request_id"]),
            "dispatch_id": a["dispatch_id"],
            "state": str(a["state"]),
            "reason": a["reason"],
        }
        for a in tx.rows(
            "SELECT * FROM attempts WHERE run_id = ? ORDER BY created_utc, rowid",
            (run_id,),
        )
    ]
    return Outcome(
        "ok",
        {
            "run_id": run_id,
            "exists": True,
            "state": str(run["state"]),
            "manifest": manifest,
            "manifest_sha256": run["manifest_sha256"],
            "task_hash": run["task_hash"],
            "cli_version": run["cli_version"],
            "kit_revision": run["kit_revision"],
            "segments": segments,
            "requests": requests,
            "attempts": attempts,
        },
    )


def verb_termination_pending(tx: Tx, segment_id: str) -> Outcome:
    """``launching`` or ``running`` → ``termination_pending``: a descendant outlived the terminate.

    The segment stays open: the lane and the reservation are held until the monitor's job
    proof says ``empty`` or ``gone`` (MX-20).
    """
    segment = get_segment(tx, segment_id)
    state = str(segment["state"])
    if state == "termination_pending":
        return Outcome("no_change", {"segment_id": segment_id, "state": state})
    if segment["finalized_utc"] is not None or state not in ("launching", "running"):
        raise Refusal("invalid_transition", f"segment {segment_id} is {state}")
    tx.move("segment", segment_id, state, "termination_pending")
    return Outcome(
        "changed", {"segment_id": segment_id, "state": "termination_pending"}
    )


# --- verbs: orchestrator messages (R§4.6.2) -------------------------------------------------


def payload_hash(identity: dict[str, Any]) -> str:
    """Return the SHA-256 of the canonical JSON of a message's identity fields."""
    canonical = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verb_send(tx: Tx, args: argparse.Namespace) -> Outcome:
    """Write one orchestrator message with the run's next ``seq`` (R§4.6.2)."""
    if args.kind not in ENABLED_MESSAGE_KINDS:
        raise Refusal(
            "kind_not_enabled", f"kind {args.kind} is not enabled in this phase"
        )
    if args.kind == "ruling":
        given = {
            "decision_id": args.decision_id,
            "gate_id": args.gate_id,
            "orchestrator_session_id": args.orchestrator_session,
            "user_message_uuid": args.user_message_uuid,
            "human_quote": args.human_quote,
        }
        missing = [name for name in RULING_FIELDS if not given[name]]
        if missing:
            # R§4.6.2: credits-msg.v1 requires every ruling field of a ruling.
            raise Refusal(
                "schema_invalid",
                f"a ruling needs {', '.join(missing)}",
                missing=missing,
            )
    run_id = str(args.run_id)
    if tx.row("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)) is None:
        raise Refusal("unknown_run", f"no run {run_id}")
    if len(args.body) > MESSAGE_BODY_MAX:
        raise Refusal(
            "body_too_long",
            f"the body has {len(args.body)} characters; the cap is {MESSAGE_BODY_MAX}",
            limit=MESSAGE_BODY_MAX,
        )
    top = tx.row(
        "SELECT COALESCE(MAX(seq), 0) AS top FROM messages WHERE run_id = ?", (run_id,)
    )
    seq = 1 + (0 if top is None else int(top["top"]))
    msg_id = f"{run_id}-m{seq}"
    identity: dict[str, Any] = {
        "run_id": run_id,
        "kind": args.kind,
        "decision_id": args.decision_id,
        "gate_id": args.gate_id,
        "orchestrator_session_id": args.orchestrator_session,
        "user_message_uuid": args.user_message_uuid,
        "human_quote": args.human_quote or None,
    }
    digest = payload_hash(identity)
    tx.con.execute(
        "INSERT INTO messages (msg_id, run_id, seq, kind, body_json, state, created_utc,"
        " payload_hash) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)",
        (
            msg_id,
            run_id,
            seq,
            args.kind,
            json.dumps({**identity, "body": args.body}, sort_keys=True),
            tx.ctx.now_utc,
            digest,
        ),
    )
    tx.created("message", msg_id, "open")
    tx.effect(f"rescan:message:{msg_id}", "rescan", msg_id)
    return Outcome(
        "changed",
        {"run_id": run_id, "msg_id": msg_id, "seq": seq, "payload_hash": digest},
    )


# --- verbs: monitor scans (the S2a test driver of R§4.7) ------------------------------------


def verb_scan_requests(tx: Tx) -> Outcome:
    """Orphan pending requests older than 150 s; notify runs stuck in ``registering``."""
    changed = False
    orphans = tx.rows(
        "SELECT * FROM requests WHERE state = 'pending' AND created_utc < ? ORDER BY created_utc, rowid",
        (tx.ctx.ago(ORPHAN_AGE_S),),
    )
    for request in orphans:
        not_start(tx, request, "orphan")
        changed = True
    stuck = tx.rows(
        "SELECT run_id FROM runs WHERE state = 'registering' AND created_utc < ?",
        (tx.ctx.ago(REGISTRATION_STUCK_S),),
    )
    for run in stuck:
        if tx.notice(
            "registration_incomplete", str(run["run_id"]), str(run["run_id"]), {}
        ):
            changed = True
    return Outcome(
        "changed" if changed else "no_change",
        {"orphaned": [str(r["request_id"]) for r in orphans]},
    )


def verb_scan_attempts(tx: Tx, proofs: dict[str, str]) -> Outcome:
    """Resolve accepted or admitted attempts from the job adapter's proofs (MX-3)."""
    changed = False
    resolved: list[str] = []
    for attempt_id, proof in sorted(proofs.items()):
        attempt = tx.row("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,))
        if attempt is None or attempt["state"] not in ("accepted", "admitted"):
            continue
        run_id = str(attempt["run_id"])
        if proof == "unknown":
            changed |= tx.notice(
                "job_proof_unknown", attempt_id, run_id, {"proof": proof}
            )
            continue
        if proof not in FINAL_PROOFS:
            continue
        segment = tx.row("SELECT * FROM segments WHERE attempt_id = ?", (attempt_id,))
        if segment is not None and segment["finalized_utc"] is None:
            finalize_segment(tx, segment, "monitor", "launch_failed", None, None)
        elif segment is None:
            request = get_request(tx, str(attempt["request_id"]))
            tx.move("attempt", attempt_id, "accepted", "launch_failed", owner="monitor")
            if request["state"] == "accepted":
                tx.move(
                    "request",
                    str(request["request_id"]),
                    "accepted",
                    "launch_failed",
                    owner="monitor",
                )
            run = get_run(tx, run_id)
            if run["state"] == "launching":
                tx.move(
                    "run",
                    run_id,
                    "launching",
                    "stopped" if request["resume"] else "failed",
                    {"stop_class": "launch_failed"},
                    owner="monitor",
                )
            tx.effect(f"rescan:{attempt_id}", "rescan", attempt_id)
        resolved.append(attempt_id)
        changed = True
    return Outcome("changed" if changed else "no_change", {"resolved": resolved})


def verb_scan_segments(tx: Tx, proofs: dict[str, str]) -> Outcome:
    """Finalize segments on ``empty`` or ``gone``; hold them on ``live`` or ``unknown`` (MX-30, MX-35)."""
    changed = False
    finalized: list[str] = []
    for segment_id, proof in sorted(proofs.items()):
        segment = tx.row("SELECT * FROM segments WHERE segment_id = ?", (segment_id,))
        if segment is None or segment["finalized_utc"] is not None:
            continue
        run_id = str(segment["run_id"])
        if proof in FINAL_PROOFS:
            finalize_segment(tx, segment, "monitor", f"job_{proof}", None, None)
            finalized.append(segment_id)
            changed = True
            continue
        if proof == "unknown":
            changed |= tx.notice(
                "job_proof_unknown", segment_id, run_id, {"proof": proof}
            )
        if segment["state"] == "identity_pending" and str(
            segment["created_utc"]
        ) < tx.ctx.ago(IDENTITY_STUCK_S):
            changed |= tx.notice("identity_stuck", segment_id, run_id, {"proof": proof})
    return Outcome("changed" if changed else "no_change", {"finalized": finalized})


# --- verbs: the monitor (S3, R§4.4) ----------------------------------------------------


def lease_holder(args: argparse.Namespace) -> str:
    """The lease owner text: ``<pid>|<creation>|<boot id>``."""
    return f"{args.pid}|{args.created}|{args.boot_id}"


def lease_payload(row: sqlite3.Row) -> dict[str, Any]:
    """The holder of a lease row, split into its identity parts."""
    holder = str(row["holder"])
    parts = holder.split("|", 2)
    created = parts[1] if len(parts) == 3 else None
    boot_id = parts[2] if len(parts) == 3 else None
    return {
        "holder": holder,
        "pid": row["pid"],
        "created": created,
        "boot_id": boot_id,
        "expires_utc": row["expires_utc"],
    }


def verb_lease(tx: Tx, args: argparse.Namespace) -> Outcome:
    """Take the monitor lease (R§4.4 step 1).

    The lease is free when it has no holder, when it has expired, when the caller holds it, or
    when ``--takeover`` names the current holder (the caller proved that holder dead). Else the
    result is ``held`` with the holder identity, and nothing is written.
    """
    holder = lease_holder(args)
    current = tx.row("SELECT holder, pid, expires_utc FROM monitor_lease WHERE id = 1")
    now = tx.ctx.now_utc
    if (
        current is not None
        and current["holder"] is not None
        and current["holder"] != holder
        and current["expires_utc"] is not None
        and str(current["expires_utc"]) > now
        and args.takeover != current["holder"]
    ):
        return Outcome("no_change", {"outcome": "held", **lease_payload(current)})
    previous = None if current is None else current["holder"]
    expires = format_utc(parse_utc(now) + timedelta(seconds=args.ttl_s))
    tx.con.execute(
        "INSERT INTO monitor_lease (id, holder, pid, expires_utc) VALUES (1, ?, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET holder = excluded.holder, pid = excluded.pid, "
        "expires_utc = excluded.expires_utc",
        (holder, args.pid, expires),
    )
    if previous is not None and previous != holder:
        log("lease_taken_over", holder=holder, previous=previous)
    return Outcome(
        "changed",
        {
            "outcome": "taken",
            "holder": holder,
            "expires_utc": expires,
            "previous": previous,
        },
    )


def verb_lease_release(tx: Tx, args: argparse.Namespace) -> Outcome:
    """Give the lease back; a lease that another holder has is left as it is."""
    cursor = tx.con.execute(
        "UPDATE monitor_lease SET holder = NULL, pid = NULL, expires_utc = NULL "
        "WHERE id = 1 AND holder = ?",
        (lease_holder(args),),
    )
    return Outcome("changed" if cursor.rowcount == 1 else "no_change")


def verb_alive(tx: Tx, segment_id: str) -> Outcome:
    """Record that the processes of an open segment were alive at this pass (last_alive_utc)."""
    get_segment(tx, segment_id)
    cursor = tx.con.execute(
        "UPDATE segments SET last_alive_utc = ? WHERE segment_id = ? AND finalized_utc IS NULL",
        (tx.ctx.now_utc, segment_id),
    )
    return Outcome(
        "changed" if cursor.rowcount == 1 else "no_change", {"segment_id": segment_id}
    )


def verb_notice(tx: Tx, args: argparse.Namespace) -> Outcome:
    """File one monitor notice ``<kind>:<ref>``; the same key again is ``no_change``."""
    new = tx.notice(args.kind, args.ref, args.run_id, args.body_json or {})
    return Outcome(
        "changed" if new else "no_change", {"notice_key": f"{args.kind}:{args.ref}"}
    )


def verb_notices_due(tx: Tx) -> Outcome:
    """The notices to send now: pending, retry under the slow limit, or slow and an hour old."""
    rows = tx.rows(
        "SELECT * FROM notices WHERE state = 'pending'"
        " OR (state = 'retry' AND attempts < ?)"
        " OR (state = 'retry' AND attempts >= ? AND (last_attempt_utc IS NULL OR last_attempt_utc <= ?))"
        " ORDER BY created_utc, notice_key",
        (NOTICE_SLOW_AFTER, NOTICE_SLOW_AFTER, tx.ctx.ago(NOTICE_SLOW_RETRY_S)),
    )
    notices: list[dict[str, Any]] = []
    for row in rows:
        try:
            body = json.loads(row["body_json"]) if row["body_json"] else {}
        except json.JSONDecodeError:
            body = {"unreadable_body": True}
        notices.append(
            {
                "notice_key": row["notice_key"],
                "kind": row["kind"],
                "run_id": row["run_id"],
                "ref": row["ref"],
                "subject": row["subject"],
                "body": body,
                "state": row["state"],
                "attempts": row["attempts"],
            }
        )
    return Outcome("no_change", {"notices": notices})


def get_notice(tx: Tx, key: str) -> sqlite3.Row:
    """The notice row, or the refusal ``not_found``."""
    row = tx.row("SELECT * FROM notices WHERE notice_key = ?", (key,))
    if row is None:
        raise Refusal("not_found", f"no notice {key}")
    return row


def verb_notice_sent(tx: Tx, key: str) -> Outcome:
    """Mark a notice sent; a notice that is already sent is ``no_change`` (never sent again)."""
    notice = get_notice(tx, key)
    if notice["state"] == "sent":
        return Outcome("no_change", {"notice_key": key, "state": "sent"})
    now = tx.ctx.now_utc
    tx.con.execute(
        "UPDATE notices SET state = 'sent', sent_utc = ?, attempts = attempts + 1,"
        " last_attempt_utc = ?, last_error = NULL WHERE notice_key = ?",
        (now, now, key),
    )
    return Outcome("changed", {"notice_key": key, "state": "sent"})


def verb_notice_failed(tx: Tx, key: str, error: str) -> Outcome:
    """Mark a failed send ``retry``; at NOTICE_SLOW_AFTER failures, write one event-log entry."""
    notice = get_notice(tx, key)
    if notice["state"] == "sent":
        return Outcome("no_change", {"notice_key": key, "state": "sent"})
    attempts = int(notice["attempts"]) + 1
    tx.con.execute(
        "UPDATE notices SET state = 'retry', attempts = ?, last_attempt_utc = ?,"
        " last_error = ? WHERE notice_key = ?",
        (attempts, tx.ctx.now_utc, error[:1000], key),
    )
    log("notice_send_failed", notice_key=key, attempts=attempts, error=error[:200])
    if attempts == NOTICE_SLOW_AFTER:
        tx.effect(f"notice_slow:{key}", "notice_slow", key)
    return Outcome(
        "changed", {"notice_key": key, "state": "retry", "attempts": attempts}
    )


def verb_outbox_scan(tx: Tx) -> Outcome:
    """Read the outbox past the cursor: decision, decision_resolved and gate_expired open a
    notice; other kinds only move the cursor. The cursor moves in the same transaction."""
    cursor_row = tx.row("SELECT value FROM cursors WHERE name = ?", (OUTBOX_CURSOR,))
    start = 0
    if cursor_row is not None and cursor_row["value"] is not None:
        start = int(cursor_row["value"])
    events = tx.rows(
        "SELECT * FROM outbox_events WHERE event_seq > ? ORDER BY event_seq", (start,)
    )
    if not events:
        return Outcome("no_change", {"cursor": start, "noticed": []})
    noticed: list[str] = []
    for event in events:
        kind = str(event["kind"])
        if kind not in OUTBOX_NOTICE_KINDS:
            continue
        seq = str(event["event_seq"])
        try:
            payload: Any = (
                json.loads(event["payload_json"]) if event["payload_json"] else {}
            )
        except json.JSONDecodeError:
            payload = {"unreadable_payload": True}
        body = {
            "semantic_key": event["semantic_key"],
            "event_seq": int(seq),
            "payload": payload,
        }
        run_id = None if event["run_id"] is None else str(event["run_id"])
        if tx.notice(kind, seq, run_id, body):
            noticed.append(f"{kind}:{seq}")
    last = int(events[-1]["event_seq"])
    tx.con.execute(
        "INSERT INTO cursors (name, value, updated_utc) VALUES (?, ?, ?) "
        "ON CONFLICT (name) DO UPDATE SET value = excluded.value, updated_utc = excluded.updated_utc",
        (OUTBOX_CURSOR, str(last), tx.ctx.now_utc),
    )
    return Outcome("changed", {"cursor": last, "noticed": noticed})


def manifest_fields(text: str | None) -> dict[str, Any]:
    """The manifest fields that the classification reads; an unreadable manifest gives none."""
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {
        key: loaded.get(key)
        for key in ("kind", "project_root", "plan_folder")
        if isinstance(loaded.get(key), str)
    }


def verb_monitor_view(tx: Tx) -> Outcome:
    """Read only: the open attempts, the open segments and the finalizing runs (R§4.4).

    The monitor reads the process identities from this view, proves each one, and gives the
    proofs back to ``scan_attempts`` and ``scan_segments``. For a finalizing run, the view adds
    its last segment, its manifest fields and its landings (the R§5.4 capture and seal).
    """
    attempts = [
        dict(row)
        for row in tx.rows(
            "SELECT a.attempt_id, a.run_id, a.state, a.dispatch_id, a.launcher_pid,"
            " a.launcher_created, a.boot_id, a.win_session, s.segment_id, s.job_name,"
            " s.wrapper_pid, s.wrapper_created"
            " FROM attempts a LEFT JOIN segments s ON s.attempt_id = a.attempt_id"
            " WHERE a.state IN ('accepted', 'admitted') ORDER BY a.created_utc, a.attempt_id"
        )
    ]
    segments = [
        dict(row)
        for row in tx.rows(
            "SELECT segment_id, run_id, attempt_id, dispatch_id, supervision, job, state,"
            " launcher_pid, launcher_created, wrapper_pid, wrapper_created, pid, created,"
            " boot_id, win_session, job_name, last_alive_utc, cancel_requested_utc, created_utc"
            " FROM segments WHERE finalized_utc IS NULL ORDER BY created_utc, segment_id"
        )
    ]
    runs: list[dict[str, Any]] = []
    for run in tx.rows(
        "SELECT run_id, kind, supervision, manifest_json FROM runs"
        " WHERE state = 'finalizing' ORDER BY run_id"
    ):
        run_id = str(run["run_id"])
        last = tx.row(
            "SELECT segment_id, dispatch_id, boot_id, pid, created, created_utc, last_alive_utc,"
            " finalized_utc, finalized_by, stop_class, exit_code, session_total_usd,"
            " cancel_requested_utc FROM segments WHERE run_id = ?"
            " ORDER BY created_utc DESC, rowid DESC LIMIT 1",
            (run_id,),
        )
        landings = [
            dict(row)
            for row in tx.rows(
                "SELECT part, path, sealed_utc FROM landings WHERE run_id = ? ORDER BY part, path",
                (run_id,),
            )
        ]
        runs.append(
            {
                "run_id": run_id,
                "kind": run["kind"],
                "supervision": run["supervision"],
                "manifest": manifest_fields(run["manifest_json"]),
                "segment": None if last is None else dict(last),
                "landings": landings,
            }
        )
    return Outcome(
        "no_change", {"attempts": attempts, "segments": segments, "runs": runs}
    )


def verb_scan_effects(ctx: Context) -> Outcome:
    """Perform every pending effect older than 5 minutes, then mark it done (R§4.7 rule 4)."""
    keys = [
        str(r["effect_key"])
        for r in ctx.con.execute(
            "SELECT effect_key FROM effects WHERE state = 'pending' AND created_utc < ?"
            " ORDER BY effect_key",
            (ctx.ago(EFFECT_RETRY_S),),
        ).fetchall()
    ]
    if not keys:
        return Outcome("no_change", {"performed": []})
    pending = perform_effects(ctx, keys)
    return Outcome(
        "changed",
        {
            "performed": [k for k in keys if k not in pending],
            "effects_pending": pending,
        },
    )


# --- the check view (R§4.5, read only) --------------------------------------------------

# The status.json fields (dispatch-status.v1) that the check shows for a segment.
STATUS_SIGNALS = (
    "session_id",
    "session_mode",
    "end_utc",
    "exit_code",
    "child_exit_code",
    "timed_out",
    "is_error",
    "error_summary",
)
# The last ``Status:`` line of a dispatch's final.md; terminal only in the R§7.3 grammar.
STATUS_LINE_RE = re.compile(r"^Status:[ \t]*(\S.*?)[ \t]*$", re.MULTILINE)
TERMINAL_STATUS_RE = re.compile(
    r"^(DONE|PARKED:approved|STOPPED:[a-z][a-z0-9_]{0,63})$"
)
VIEW_OUTBOX_LIMIT = 10
# The view reads the delivery confirmations of schema version 2. It never migrates, so a
# version 3 store (no resume mode or brief yet) still reads, with those fields empty.
VIEW_MIN_SCHEMA = 2
STOP_GATE_RE = re.compile(r"^stop_gate:[ \t]*\"?([^\"\r\n]*)\"?[ \t]*$", re.MULTILINE)


def read_json_file(path: Path) -> dict[str, Any] | None:
    """Return a JSON object file, or None when it is missing, unreadable or not an object."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def dispatch_signals(output_dir: Path | None, dispatch_id: Any) -> dict[str, Any]:
    """Return what a dispatch folder holds: status.json signals and the final.md status."""
    if output_dir is None or not dispatch_id:
        return {"status_json": False, "status": None, "final_status": None}
    folder = output_dir / str(dispatch_id)
    status = read_json_file(folder / "status.json")
    final_status: str | None = None
    try:
        lines = STATUS_LINE_RE.findall(
            (folder / "final.md").read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError):
        lines = []
    if lines:
        final_status = str(lines[-1])
    return {
        "status_json": status is not None,
        "status": None
        if status is None
        else {key: status.get(key) for key in STATUS_SIGNALS if key in status},
        "final_status": final_status,
        "final_status_terminal": final_status is not None
        and TERMINAL_STATUS_RE.match(final_status) is not None,
    }


def task_signals(run: dict[str, Any]) -> dict[str, Any] | None:
    """Return the run's task.md stop gate and open rows (best effort), or None."""
    manifest = manifest_fields(run.get("manifest_json"))
    root = run.get("active_tree") or manifest.get("project_root")
    folder = manifest.get("plan_folder")
    if not isinstance(root, str) or not isinstance(folder, str):
        return None
    path = Path(root) / folder / "task.md"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        return {"path": str(path), "readable": False}
    gate = STOP_GATE_RE.search(text)
    open_rows: list[str] = []
    for line in text.splitlines():
        cells = [cell.strip().strip("`").strip() for cell in line.strip().split("|")]
        cells = [cell for cell in cells if cell]
        if line.lstrip().startswith("|") and len(cells) >= 2 and cells[-1] == "[ ]":
            open_rows.append(cells[0])
    return {
        "path": str(path),
        "readable": True,
        "stop_gate": None if gate is None else gate.group(1).strip(),
        "open_rows": open_rows,
    }


def view_list(tx: Tx) -> dict[str, Any]:
    """One summary per run: state, class, segments, spend, heartbeat age and pending messages."""
    runs: list[dict[str, Any]] = []
    for row in tx.rows("SELECT * FROM runs ORDER BY created_utc, run_id"):
        run = dict(row)
        run_id = str(run["run_id"])
        segments = tx.rows(
            "SELECT * FROM segments WHERE run_id = ? ORDER BY created_utc, rowid",
            (run_id,),
        )
        alive = [str(s["last_alive_utc"]) for s in segments if s["last_alive_utc"]]
        last = segments[-1] if segments else None
        runs.append(
            {
                "run_id": run_id,
                "state": run.get("state"),
                "class": run.get("stop_class"),
                "segments": len(segments),
                "cost": run_spend(tx, run_id),
                "heartbeat_age_s": None
                if not alive
                else int((tx.ctx.now - parse_utc(max(alive))).total_seconds()),
                "pending_messages": len(pending_messages(tx, run_id, last)),
            }
        )
    return {"runs": runs}


def pending_messages(
    tx: Tx, run_id: str, segment: sqlite3.Row | None
) -> list[sqlite3.Row]:
    """The run's open messages with no confirmed delivery to its newest segment."""
    if segment is None:
        return tx.rows(
            "SELECT * FROM messages WHERE run_id = ? AND state = 'open' ORDER BY seq",
            (run_id,),
        )
    return tx.rows(
        "SELECT m.* FROM messages m WHERE m.run_id = ? AND m.state = 'open' AND NOT EXISTS ("
        " SELECT 1 FROM deliveries d WHERE d.msg_id = m.msg_id AND d.segment_id = ?"
        " AND d.confirmed_utc IS NOT NULL) ORDER BY m.seq",
        (run_id, str(segment["segment_id"])),
    )


def view_run(tx: Tx, run_id: str, output_dir: Path | None) -> dict[str, Any]:
    """The full check view of one run (R§4.5); an unknown id is refused."""
    found = tx.row("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    if found is None:
        raise Refusal("unknown_run", f"no run {run_id}", run_id=run_id)
    run = dict(found)
    segment_rows = tx.rows(
        "SELECT * FROM segments WHERE run_id = ? ORDER BY created_utc, rowid", (run_id,)
    )
    newest = segment_rows[-1] if segment_rows else None
    segments: list[dict[str, Any]] = []
    for row in segment_rows:
        seg = dict(row)
        segments.append(
            {
                "segment_id": seg.get("segment_id"),
                "dispatch_id": seg.get("dispatch_id"),
                "expected_session_id": seg.get("expected_session_id"),
                "resume": seg.get("resume"),
                "brief": seg.get("brief"),
                "state": seg.get("state"),
                "supervision": seg.get("supervision"),
                "created_utc": seg.get("created_utc"),
                "last_alive_utc": seg.get("last_alive_utc"),
                "finalized_utc": seg.get("finalized_utc"),
                "finalized_by": seg.get("finalized_by"),
                "stop_class": seg.get("stop_class"),
                "exit_code": seg.get("exit_code"),
                "cost_known": seg.get("cost_known"),
                "session_total_usd": seg.get("session_total_usd"),
                "segment_delta_usd": seg.get("segment_delta_usd"),
                "reservation_usd": seg.get("reservation_usd"),
                "dispatch": dispatch_signals(output_dir, seg.get("dispatch_id")),
            }
        )
    requests = [
        {
            key: dict(q).get(key)
            for key in (
                "request_id",
                "state",
                "started_by",
                "requested_by",
                "resume",
                "resume_mode",
                "brief",
                "reason",
                "created_utc",
            )
        }
        for q in tx.rows(
            "SELECT * FROM requests WHERE run_id = ? ORDER BY created_utc, rowid",
            (run_id,),
        )
    ]
    attempts = [
        {
            key: dict(a).get(key)
            for key in (
                "attempt_id",
                "request_id",
                "dispatch_id",
                "expected_session_id",
                "state",
                "reason",
                "created_utc",
            )
        }
        for a in tx.rows(
            "SELECT * FROM attempts WHERE run_id = ? ORDER BY created_utc, rowid",
            (run_id,),
        )
    ]
    pending_ids = {str(m["msg_id"]) for m in pending_messages(tx, run_id, newest)}
    messages: list[dict[str, Any]] = []
    for row in tx.rows(
        "SELECT * FROM messages WHERE run_id = ? ORDER BY seq", (run_id,)
    ):
        msg = dict(row)
        try:
            body = json.loads(str(msg.get("body_json") or "{}")).get("body")
        except (ValueError, AttributeError):
            body = None
        msg_id = str(msg["msg_id"])
        messages.append(
            {
                "msg_id": msg_id,
                "seq": msg.get("seq"),
                "kind": msg.get("kind"),
                "state": msg.get("state"),
                "closed_reason": msg.get("closed_reason"),
                "body": body,
                "pending": msg_id in pending_ids,
                "deliveries": [
                    {
                        key: dict(d).get(key)
                        for key in (
                            "segment_id",
                            "state",
                            "delivered_utc",
                            "confirmed_utc",
                            "failed_utc",
                        )
                    }
                    for d in tx.rows(
                        "SELECT * FROM deliveries WHERE msg_id = ? ORDER BY rowid",
                        (msg_id,),
                    )
                ],
            }
        )
    outbox = [
        dict(e)
        for e in tx.rows(
            "SELECT event_seq, kind, semantic_key, created_utc FROM outbox_events"
            " WHERE run_id = ? ORDER BY event_seq DESC LIMIT ?",
            (run_id, VIEW_OUTBOX_LIMIT),
        )
    ]
    gate_row = tx.row(
        "SELECT * FROM gates WHERE run_id = ? AND state = 'open' ORDER BY opened_utc DESC LIMIT 1",
        (run_id,),
    )
    gate = (
        None
        if gate_row is None
        else {
            key: dict(gate_row).get(key)
            for key in (
                "gate_id",
                "segment_id",
                "question",
                "decision_id",
                "deadline_utc",
            )
        }
    )
    exposures = [
        {
            **dict(e),
            "settle_command": None
            if e["state"] != "open"
            else "pwsh -File .agent/skills/claude-credits/Get-CreditsRun.ps1"
            f" -Settle {e['segment_id']} -Source console -AmountUsd <usd>",
        }
        for e in tx.rows(
            "SELECT * FROM exposures WHERE run_id = ? ORDER BY rowid", (run_id,)
        )
    ]
    newest_dispatch = None if newest is None else newest["dispatch_id"]
    newest_signals = dispatch_signals(output_dir, newest_dispatch)
    has_status = bool(newest_signals["status_json"])
    recovery = None
    if newest_dispatch and not has_status:
        recovery = (
            f"pwsh -File tools/Get-ClaudeDispatch.ps1 {newest_dispatch}"
            f" -OutputDir {output_dir} -RecoverStatus"
        )
    return {
        "run_id": run_id,
        "state": run.get("state"),
        "class": run.get("stop_class"),
        "kind": run.get("kind"),
        "supervision": run.get("supervision"),
        "lane": run.get("lane"),
        "generation": len(segment_rows),
        "segments": segments,
        "requests": requests,
        "attempts": attempts,
        "messages": messages,
        "outbox": outbox,
        "gate": gate,
        "exposures": exposures,
        "cost": {
            "segment_cap_usd": run.get("segment_cap_usd"),
            "run_cap_usd": run.get("run_cap_usd"),
            **run_spend(tx, run_id),
        },
        "task": task_signals(run),
        "final_status": newest_signals.get("final_status"),
        "final_status_terminal": bool(newest_signals.get("final_status_terminal")),
        "resume": {
            "source_dispatch_id": newest_dispatch,
            "recovery_status_needed": bool(newest_dispatch) and not has_status,
            "recovery_command": recovery,
            "ruling_pending": gate is not None,
            "session_resume_possible": has_status,
            "command": "pwsh -File .agent/skills/claude-credits/Start-CreditsRunTask.ps1"
            f" -RunId {run_id} -StartedBy human-command -Resume -Brief <resume brief>",
        },
    }


def open_store_read_only(db: str, busy_ms: int) -> sqlite3.Connection:
    """Open the store with ``mode=ro``: no WAL switch, no migration, no write (R§4.5)."""
    con = sqlite3.connect(
        Path(db).resolve().as_uri() + "?mode=ro",
        uri=True,
        isolation_level=None,
        timeout=busy_ms / 1000,
    )
    con.row_factory = sqlite3.Row
    try:
        con.execute(f"PRAGMA busy_timeout = {int(busy_ms)}")
    except BaseException:
        con.close()
        raise
    return con


def verb_view(ctx: Context, args: argparse.Namespace) -> Outcome:
    """Read the check view in one read transaction: every run, or one run in full."""
    version = user_version(ctx.con)
    if version < VIEW_MIN_SCHEMA:
        raise Refusal(
            "schema_too_old",
            f"the store {ctx.db} has schema {version}; the view reads {VIEW_MIN_SCHEMA}"
            " or newer, and any store verb (for example init) migrates it",
        )
    output_dir = Path(args.output_dir) if args.output_dir else None
    ctx.con.execute("BEGIN")
    try:
        tx = Tx(ctx)
        if args.run_id is None:
            payload = view_list(tx)
        else:
            payload = view_run(tx, str(args.run_id), output_dir)
    finally:
        ctx.con.execute("ROLLBACK")
    return Outcome("ok", {"schema_version": version, **payload})


# --- verbs: rulings and the history check (S6b, R§4.6.3) -----------------------------------

# R§4.6.3 history check step 3: the record types of a CLI transcript. Any other type, a
# line that is not JSON, or a line that is not an object fails as transcript_unknown.
KNOWN_RECORD_TYPES = frozenset(
    {
        "user",
        "assistant",
        "attachment",
        "queue-operation",
        "system",
        "summary",
        "atis-latch",
        "last-prompt",
        "cost-state",
        "ai-title",
        "custom-title",
        "agent-name",
        "mode",
        "file-history-delta",
        "file-history-snapshot",
        "pr-link",
        "permission-mode",
    }
)
# R§4.6.3 step 6: a token is a run of letters and digits, joined by one "-", "_" or ".".
TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*")
WHITESPACE_RE = re.compile(r"\s+")
SLUG_RE = re.compile(r"[^A-Za-z0-9]")
# R§4.6.3 step 4: the prompt sources of a typed turn.
TYPED_PROMPT_SOURCES = frozenset({"sdk", "typed"})
# The provenance verdicts of the queue replay (R§4.6.3 step 5, D-8).
QUEUED_ORIGIN = "queued_origin"
PROVENANCE_UNKNOWN = "provenance_unknown"
# The scan errors that the ruling verifier reports under another reason.
SCAN_ERROR_REASONS = {
    "transcript_missing": "transcript_unknown",
    "transcript_unknown": "transcript_unknown",
    "transcript_discontinuity": "transcript_discontinuity",
    "conflict": "transcript_discontinuity",
    "manifest_invalid": "malformed",
}


def normalize_text(text: str) -> str:
    """R§4.6.3 step 6: NFC, CRLF → LF, trim, and each whitespace run as one space."""
    folded = unicodedata.normalize("NFC", text).replace("\r\n", "\n")
    return WHITESPACE_RE.sub(" ", folded.strip())


def text_hash(text: str) -> str:
    """Return the SHA-256 of a normalized text (the ``queue_chains`` text hashes)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def entry_time(value: object) -> datetime | None:
    """Parse a transcript timestamp (ISO 8601, milliseconds, ``Z``); None when absent or bad."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def as_dict(value: object) -> dict[str, Any] | None:
    """Return a JSON object with string keys, or None for any other value."""
    if not isinstance(value, dict):
        return None
    source = cast("dict[object, object]", value)
    return {str(key): item for key, item in source.items()}


def text_blocks(value: object) -> str | None:
    """Return the text of a content value made only of text; None for any other block.

    A string is its own text; a list must hold only ``{"type": "text", "text": str}``
    blocks, joined with a newline (R§4.6.3 step 4: no tool result, no image).
    """
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return None
    texts: list[str] = []
    for item in cast("list[object]", value):
        block = as_dict(item)
        if block is None or block.get("type") != "text":
            return None
        text = block.get("text")
        if not isinstance(text, str):
            return None
        texts.append(text)
    return "\n".join(texts) if texts else None


def message_content(record: dict[str, Any]) -> object:
    """Return ``message.content`` of a record, or None."""
    message = as_dict(record.get("message"))
    return None if message is None else message.get("content")


def has_tool_result(record: dict[str, Any]) -> bool:
    """Return True when the record's content holds a ``tool_result`` block."""
    content = message_content(record)
    if not isinstance(content, list):
        return False
    for item in cast("list[object]", content):
        block = as_dict(item)
        if block is not None and block.get("type") == "tool_result":
            return True
    return False


def is_prompt_entry(record: dict[str, Any]) -> bool:
    """A user record that a prompt wrote: no meta line, no tool result (D-8)."""
    return (
        record.get("type") == "user"
        and record.get("isMeta") is not True
        and "toolUseResult" not in record
        and not has_tool_result(record)
    )


def is_human_entry(record: dict[str, Any], session: str) -> bool:
    """R§4.6.3 step 4: a ``type: user`` entry of this session that a human typed as text."""
    origin = as_dict(record.get("origin"))
    return (
        record.get("type") == "user"
        and record.get("sessionId") == session
        and origin is not None
        and origin.get("kind") == "human"
        and record.get("userType") == "external"
        and record.get("isMeta") is not True
        and record.get("isCompactSummary") is not True
        and "toolUseResult" not in record
        and text_blocks(message_content(record)) is not None
    )


def is_typed_turn(record: dict[str, Any]) -> bool:
    """R§4.6.3 step 4 (MX-41): ``turnOrigin`` human, a typed source and a ``promptId``."""
    prompt_id = record.get("promptId")
    return (
        record.get("turnOrigin") == "human"
        and record.get("promptSource") in TYPED_PROMPT_SOURCES
        and isinstance(prompt_id, str)
        and bool(prompt_id)
    )


def transcript_path(doc: dict[str, Any], session: str) -> Path:
    """R§4.6.3 step 2: ``~/.claude/projects/<slug of project_root>/<session>.jsonl``.

    ``CLAUDE_CONFIG_DIR`` replaces ``~/.claude`` as it does for the CLI; ``~`` is
    ``USERPROFILE``, then ``HOME``.
    """
    project = doc.get("project_root")
    if not isinstance(project, str) or not project:
        raise Refusal("manifest_invalid", "the run's manifest has no project_root")
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    if config:
        base = Path(config)
    else:
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
        base = (Path(home) if home else Path.home()) / ".claude"
    return base / "projects" / SLUG_RE.sub("-", project) / f"{session}.jsonl"


@dataclass
class Line:
    """One complete transcript line: its 1-based number, byte offset and record."""

    number: int
    offset: int
    record: dict[str, Any]


def parse_lines(data: bytes) -> list[Line]:
    """Parse the complete lines of a transcript; a bad line fails as transcript_unknown."""
    lines: list[Line] = []
    offset = 0
    number = 0
    for raw in data.split(b"\n")[:-1]:
        number += 1
        start = offset
        offset += len(raw) + 1
        if not raw.strip():
            continue
        try:
            loaded: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Refusal(
                "transcript_unknown", f"line {number} is not JSON: {exc}", line=number
            ) from exc
        record = as_dict(loaded)
        if record is None:
            raise Refusal(
                "transcript_unknown", f"line {number} is not an object", line=number
            )
        kind = record.get("type")
        if kind not in KNOWN_RECORD_TYPES:
            raise Refusal(
                "transcript_unknown",
                f"line {number} has the unknown record type {kind!r}",
                line=number,
            )
        lines.append(Line(number, start, record))
    return lines


def check_chain(lines: list[Line]) -> None:
    """R§4.6.3 history check step 1: every parent link resolves to an earlier line.

    Only the first chained record may have no parent, unless its
    ``logicalParentUuid`` (a compaction boundary) resolves.
    """
    seen: set[str] = set()
    first = True
    for line in lines:
        uid = line.record.get("uuid")
        if not isinstance(uid, str) or not uid:
            continue
        parent = line.record.get("parentUuid")
        if parent is None:
            logical = line.record.get("logicalParentUuid")
            linked = first or (isinstance(logical, str) and logical in seen)
        else:
            linked = isinstance(parent, str) and parent in seen
        if not linked:
            raise Refusal(
                "transcript_discontinuity",
                f"line {line.number} has a parent that no earlier line holds",
                line=line.number,
            )
        seen.add(uid)
        first = False


@dataclass
class QueueItem:
    """One ``enqueue`` record of the replay."""

    line: int
    text: str | None
    bound: bool = False
    dequeued: bool = False


@dataclass
class QueueChain:
    """The records of one queue delivery, joined by the CLI's ``deliveryId``."""

    delivery_id: str
    lines: list[int] = field(default_factory=lambda: list[int]())
    texts: set[str] = field(default_factory=lambda: set[str]())
    command_uuid: str | None = None
    remove_reason: str | None = None
    state: str = "open"
    attached: bool = False


@dataclass
class Replay:
    """The D-8 replay of a transcript: a verdict per prompt entry and the chains."""

    verdicts: dict[int, str | None]
    chains: dict[str, QueueChain]


def _record_text(value: object) -> str | None:
    """Return the normalized text of a queue record's content, or None when it has none."""
    text = text_blocks(value)
    if text is None:
        return None
    folded = normalize_text(text)
    return folded or None


def _bind(items: list[QueueItem], text: str | None) -> None:
    """Bind the earliest free enqueue whose text is unknown or equal (D-8)."""
    for item in items:
        if item.bound or item.dequeued:
            continue
        if item.text is None or item.text == text:
            item.bound = True
            return


def replay_queue(lines: list[Line]) -> Replay:
    """D-8 (R§4.6.3 step 5): replay the queue records from line 1.

    The verdict of a prompt entry, in order: its text is a queued text →
    ``queued_origin``; a dequeue with no free enqueue, or more than one pending
    dequeue → ``provenance_unknown``; one pending dequeue whose enqueue came before
    the last assistant line (typed while the model streamed) → ``queued_origin``, and
    its text becomes a queued text (R6-a); its
    text is the text of a queue record that could not be joined →
    ``provenance_unknown``; else None.
    """
    items: list[QueueItem] = []
    pending: list[QueueItem | None] = []
    chains: dict[str, QueueChain] = {}
    queued: set[str] = set()
    unjoinable: set[str] = set()
    last_assistant = 0
    verdicts: dict[int, str | None] = {}

    def chain_for(delivery_id: str) -> QueueChain:
        found = chains.get(delivery_id)
        if found is None:
            found = QueueChain(delivery_id)
            chains[delivery_id] = found
        return found

    for line in lines:
        record = line.record
        kind = record.get("type")
        if kind == "queue-operation":
            operation = record.get("operation")
            text = _record_text(record.get("content"))
            delivery = record.get("deliveryId")
            if operation == "enqueue":
                items.append(QueueItem(line.number, text))
                if text:
                    queued.add(text)
            elif operation == "dequeue":
                free = next((i for i in items if not i.bound and not i.dequeued), None)
                if free is not None:
                    free.dequeued = True
                pending.append(free)
            elif operation == "remove" and isinstance(delivery, str) and delivery:
                chain = chain_for(delivery)
                chain.lines.append(line.number)
                command = record.get("commandUuid")
                reason = record.get("reason")
                chain.command_uuid = command if isinstance(command, str) else None
                chain.remove_reason = reason if isinstance(reason, str) else None
                chain.state = "closed" if chain.state != "unjoined" else chain.state
                if text:
                    chain.texts.add(text)
                    queued.add(text)
                _bind(items, text)
            elif text:
                unjoinable.add(text)
        elif kind == "attachment":
            attachment = as_dict(record.get("attachment"))
            if attachment is None or attachment.get("type") != "queued_command":
                continue
            text = _record_text(attachment.get("prompt"))
            delivery = attachment.get("delivery_id")
            if not isinstance(delivery, str) or not delivery:
                if text:
                    unjoinable.add(text)
                continue
            chain = chain_for(delivery)
            chain.lines.append(line.number)
            if chain.attached:
                chain.state = "unjoined"
                if text:
                    unjoinable.add(text)
                continue
            chain.attached = True
            if text:
                chain.texts.add(text)
                queued.add(text)
            _bind(items, text)
        elif kind == "assistant":
            last_assistant = line.number
        elif is_prompt_entry(record):
            text = text_blocks(message_content(record))
            folded = normalize_text(text) if text is not None else ""
            verdict: str | None = None
            if folded and folded in queued:
                verdict = QUEUED_ORIGIN
            elif None in pending or len(pending) > 1:
                verdict = PROVENANCE_UNKNOWN
            elif (
                len(pending) == 1
                and (pending[0] is not None)
                and (pending[0].line < last_assistant)
            ):
                verdict = QUEUED_ORIGIN
                # R6-a: the text of an entry queued during a turn stays a queued text,
                # so an exact resend fails too.
                if folded:
                    queued.add(folded)
            elif folded and folded in unjoinable:
                verdict = PROVENANCE_UNKNOWN
            verdicts[line.number] = verdict
            pending.clear()
    return Replay(verdicts, chains)


@dataclass
class Scan:
    """The result of one history check: the lines read, the mark and the replay."""

    result: str
    lines: list[Line]
    byte_length: int
    line_count: int
    watermark: int
    replay: Replay


@dataclass
class ScanBroken:
    """A later scan found a changed prefix: the session is now ``broken``."""

    message: str


def read_transcript(path: Path) -> bytes:
    """Return the complete lines of a transcript: the bytes up to the last newline."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise Refusal("transcript_missing", f"no transcript at {path}") from exc
    except OSError as exc:
        raise Refusal(
            "transcript_unknown", f"the transcript {path} cannot be read: {exc}"
        ) from exc
    return raw[: raw.rfind(b"\n") + 1]


def store_chains(tx: Tx, session: str, chains: dict[str, QueueChain]) -> None:
    """Insert or update the ``queue_chains`` rows of a session (chain id = delivery id)."""
    for chain in chains.values():
        tx.con.execute(
            "INSERT INTO queue_chains (session, chain_id, delivery_id, command_uuid, lines_json,"
            " remove_reason, text_hashes_json, state, updated_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (session, chain_id) DO UPDATE SET command_uuid = excluded.command_uuid,"
            " lines_json = excluded.lines_json, remove_reason = excluded.remove_reason,"
            " text_hashes_json = excluded.text_hashes_json, state = excluded.state,"
            " updated_utc = excluded.updated_utc",
            (
                session,
                chain.delivery_id,
                chain.delivery_id,
                chain.command_uuid,
                json.dumps(chain.lines),
                chain.remove_reason,
                json.dumps(sorted(text_hash(text) for text in chain.texts)),
                chain.state,
                tx.ctx.now_utc,
            ),
        )


def mark_broken(tx: Tx, run_id: str, session: str, message: str) -> ScanBroken:
    """R§4.6.3 (MX-28): set ``history_state`` broken for the session and send one notice."""
    tx.con.execute(
        "INSERT INTO orchestrator_sessions (run_id, session, history_state, attached_utc)"
        " VALUES (?, ?, 'broken', ?) ON CONFLICT (run_id, session)"
        " DO UPDATE SET history_state = 'broken'",
        (run_id, session, tx.ctx.now_utc),
    )
    tx.con.execute(
        "UPDATE orchestrator_sessions SET history_state = 'broken' WHERE session = ?",
        (session,),
    )
    tx.notice(
        "transcript_discontinuity",
        session,
        run_id,
        {"run_id": run_id, "session": session, "message": message},
    )
    log("transcript_discontinuity", run_id=run_id, session=session, message=message)
    return ScanBroken(message)


def scan_session(
    tx: Tx, run_id: str, doc: dict[str, Any], session: str, *, first: bool
) -> Scan | ScanBroken:
    """The history check of R§4.6.3 for one orchestrator session.

    A first scan (no mark, or ``first`` for an attach) checks the whole parent chain
    and writes the mark with the attach watermark; any failure is a refusal and writes
    nothing. A later scan needs the old bytes as a prefix (byte length and SHA-256) and
    a whole chain, else the session is broken; a longer file moves the mark by a
    compare-and-set on the old mark.
    """
    if not first:
        broken = tx.row(
            "SELECT 1 FROM orchestrator_sessions WHERE run_id = ? AND session = ?"
            " AND history_state = 'broken'",
            (run_id, session),
        )
        if broken is not None:
            return ScanBroken("the session is broken until a new attach")
    data = read_transcript(transcript_path(doc, session))
    digest = hashlib.sha256(data).hexdigest()
    count = data.count(b"\n")
    mark = (
        None
        if first
        else tx.row("SELECT * FROM transcript_marks WHERE session = ?", (session,))
    )
    if mark is None:
        lines = parse_lines(data)
        check_chain(lines)
        replay = replay_queue(lines)
        tx.con.execute(
            "INSERT INTO transcript_marks (session, byte_length, prefix_sha256, line_count,"
            " updated_utc, watermark_bytes) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (session) DO UPDATE SET byte_length = excluded.byte_length,"
            " prefix_sha256 = excluded.prefix_sha256, line_count = excluded.line_count,"
            " updated_utc = excluded.updated_utc, watermark_bytes = excluded.watermark_bytes",
            (session, len(data), digest, count, tx.ctx.now_utc, len(data)),
        )
        store_chains(tx, session, replay.chains)
        return Scan("changed", lines, len(data), count, len(data), replay)
    old_length = int(mark["byte_length"])
    old_digest = str(mark["prefix_sha256"])
    watermark = (
        len(data) if mark["watermark_bytes"] is None else int(mark["watermark_bytes"])
    )
    if (
        len(data) < old_length
        or hashlib.sha256(data[:old_length]).hexdigest() != old_digest
    ):
        return mark_broken(tx, run_id, session, "the scanned prefix changed")
    lines = parse_lines(data)
    try:
        check_chain(lines)
    except Refusal as exc:
        return mark_broken(tx, run_id, session, exc.message)
    replay = replay_queue(lines)
    if len(data) == old_length:
        return Scan("no_change", lines, len(data), count, watermark, replay)
    cursor = tx.con.execute(
        "UPDATE transcript_marks SET byte_length = ?, prefix_sha256 = ?, line_count = ?,"
        " updated_utc = ? WHERE session = ? AND byte_length = ? AND prefix_sha256 = ?",
        (len(data), digest, count, tx.ctx.now_utc, session, old_length, old_digest),
    )
    if cursor.rowcount != 1:
        raise Refusal(
            "conflict", f"the mark of {session} moved", result="conflict", entity="mark"
        )
    store_chains(tx, session, replay.chains)
    return Scan("changed", lines, len(data), count, watermark, replay)


def session_listed(tx: Tx, run_id: str, doc: dict[str, Any], session: str) -> bool:
    """R§4.6.3 step 2: the manifest lists the session, or an attach recorded it."""
    if not KEY_RE.match(session) or ".." in session:
        return False
    messaging = as_dict(doc.get("messaging")) or {}
    listed = messaging.get("orchestrator_sessions")
    if isinstance(listed, list) and session in cast("list[object]", listed):
        return True
    found = tx.row(
        "SELECT 1 FROM orchestrator_sessions WHERE run_id = ? AND session = ?",
        (run_id, session),
    )
    return found is not None


def verb_scan_transcript(tx: Tx, run_id: str, session: str) -> Outcome:
    """R§4.6.3 history check of one session; a changed prefix commits ``broken``, exit 3."""
    run = get_run(tx, run_id)
    doc = manifest_doc(run)
    if not session_listed(tx, run_id, doc, session):
        raise Refusal("session_not_listed", f"run {run_id} does not list {session}")
    found = scan_session(tx, run_id, doc, session, first=False)
    if isinstance(found, ScanBroken):
        return Outcome(
            "refused",
            {
                "error": "transcript_discontinuity",
                "message": found.message,
                "run_id": run_id,
                "session": session,
            },
        )
    return Outcome(
        found.result,
        {
            "run_id": run_id,
            "session": session,
            "byte_length": found.byte_length,
            "line_count": found.line_count,
        },
    )


@dataclass
class RulingVerdict:
    """The result of the ruling verifier for one delivered ``ruling`` message."""

    verified: bool
    reason: str | None = None
    warn: bool = False
    session: str = ""
    uid: str = ""
    quote: str = ""
    gate_id: str = ""
    decision_id: str = ""


class Unverified(Exception):
    """A step of R§4.6.3 failed: the ruling is framed as ``info``."""

    def __init__(self, reason: str, *, warn: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.warn = warn


def _single_entry(scan: Scan, uid: str) -> Line:
    """R§4.6.3 step 3: exactly one line of the session holds the uuid."""
    matches = [line for line in scan.lines if line.record.get("uuid") == uid]
    if len(matches) != 1:
        raise Unverified("uuid_not_found")
    return matches[0]


def _check_entry(scan: Scan, entry: Line, session: str) -> tuple[str, str, datetime]:
    """R§4.6.3 steps 4 and 5 for an entry; return its prompt id, its text and its time."""
    record = entry.record
    text = text_blocks(message_content(record))
    moment = entry_time(record.get("timestamp"))
    if not is_human_entry(record, session) or text is None or moment is None:
        raise Unverified("not_human_entry")
    if not is_typed_turn(record):
        raise Unverified("not_typed_turn")
    prompt_id = str(record["promptId"])
    for line in scan.lines:
        if line.number >= entry.number:
            break
        if line.record.get("promptId") == prompt_id:
            raise Unverified("replay")
    return prompt_id, normalize_text(text), moment


def _check_provenance(tx: Tx, scan: Scan, entry: Line, session: str, text: str) -> None:
    """R§4.6.3 step 5 (D-8): the replay verdict, then the stored chains of earlier lines."""
    verdict = scan.replay.verdicts.get(entry.number)
    if verdict is not None:
        raise Unverified(verdict)
    digest = text_hash(text)
    for row in tx.rows(
        "SELECT lines_json, text_hashes_json FROM queue_chains WHERE session = ?",
        (session,),
    ):
        try:
            lines: object = json.loads(str(row["lines_json"] or "[]"))
            hashes: object = json.loads(str(row["text_hashes_json"] or "[]"))
        except json.JSONDecodeError as exc:
            raise Unverified(PROVENANCE_UNKNOWN) from exc
        numbers = (
            [n for n in cast("list[object]", lines) if isinstance(n, int)]
            if isinstance(lines, list)
            else []
        )
        if (
            numbers
            and min(numbers) < entry.number
            and isinstance(hashes, list)
            and digest in cast("list[object]", hashes)
        ):
            raise Unverified(QUEUED_ORIGIN)


def _gate_open_at(gate: sqlite3.Row, moment: datetime) -> bool:
    """Return True when the gate was open at ``moment``."""
    if parse_utc(str(gate["opened_utc"])) >= moment:
        return False
    closed = gate["closed_utc"]
    return closed is None or parse_utc(str(closed)) > moment


def _redelivered(
    tx: Tx, run_id: str, message: sqlite3.Row, verdict: RulingVerdict
) -> RulingVerdict | None:
    """R§4.6.3 Redelivery: a consumed ``msg_id`` is verified again only on a whole match."""
    prior = tx.row(
        "SELECT * FROM consumed_rulings WHERE msg_id = ?", (str(message["msg_id"]),)
    )
    if prior is None:
        return None
    gate = tx.row(
        "SELECT resolved_by_msg FROM gates WHERE gate_id = ?", (verdict.gate_id,)
    )
    same = (
        prior["orchestrator_session"] == verdict.session
        and prior["user_message_uuid"] == verdict.uid
        and prior["run_id"] == run_id
        and prior["decision_id"] == verdict.decision_id
        and prior["gate_id"] == verdict.gate_id
        and prior["payload_hash"] == message["payload_hash"]
        and gate is not None
        and gate["resolved_by_msg"] == message["msg_id"]
    )
    if not same:
        raise Unverified("replay")
    return verdict


def _verify(
    tx: Tx,
    run: sqlite3.Row,
    message: sqlite3.Row,
    clock: Callable[[], datetime] | None,
) -> RulingVerdict:
    """R§4.6.3 Part A and Part B for one ruling; raise ``Unverified`` at a failed step."""
    run_id = str(run["run_id"])
    msg_id = str(message["msg_id"])
    try:
        body = as_dict(json.loads(str(message["body_json"] or "{}")))
    except json.JSONDecodeError as exc:
        raise Unverified("malformed") from exc
    if body is None:
        raise Unverified("malformed")
    fields = {
        name: body.get(name)
        for name in (
            "orchestrator_session_id",
            "user_message_uuid",
            "human_quote",
            "decision_id",
            "gate_id",
        )
    }
    if not all(isinstance(value, str) and value for value in fields.values()):
        raise Unverified("malformed")
    verdict = RulingVerdict(
        verified=False,
        session=str(fields["orchestrator_session_id"]),
        uid=str(fields["user_message_uuid"]),
        quote=normalize_text(str(fields["human_quote"])),
        gate_id=str(fields["gate_id"]),
        decision_id=str(fields["decision_id"]),
    )
    session = verdict.session
    doc = manifest_doc(run)
    messaging = as_dict(doc.get("messaging")) or {}
    # Step 1: the switch.
    if messaging.get("ruling_enabled") is not True:
        raise Unverified("ruling_disabled")
    # Step 2: the session.
    if not session_listed(tx, run_id, doc, session):
        raise Unverified("session_not_listed")
    again = _redelivered(tx, run_id, message, verdict)
    if again is not None:
        return RulingVerdict(**{**again.__dict__, "verified": True})
    # Step 3: the history check and the attach watermark.
    scanned = scan_session(tx, run_id, doc, session, first=False)
    if isinstance(scanned, ScanBroken):
        raise Unverified("transcript_discontinuity")
    entry = _single_entry(scanned, verdict.uid)
    if entry.offset < scanned.watermark:
        raise Unverified("before_watermark")
    # Steps 4 and 5: the typed human entry and its provenance.
    prompt_id, text, moment = _check_entry(scanned, entry, session)
    gate = tx.row("SELECT * FROM gates WHERE gate_id = ?", (verdict.gate_id,))
    if gate is None:
        raise Unverified("gate_closed")
    if moment <= parse_utc(str(gate["opened_utc"])):
        raise Unverified("entry_before_gate")
    _check_provenance(tx, scanned, entry, session, text)
    # Step 6: the quote and its tokens.
    if verdict.quote != text:
        raise Unverified("quote_mismatch")
    tokens = TOKEN_RE.findall(text)
    if verdict.decision_id not in tokens:
        raise Unverified("decision_missing")
    others = {
        str(row["run_id"])
        for row in tx.rows("SELECT run_id FROM runs WHERE run_id != ?", (run_id,))
    }
    if any(token in others for token in tokens):
        raise Unverified("wrong_run")
    # Step 7: the gate is this run's open gate of the decision, before its deadline.
    # Read the clock again here, inside the consuming transaction: the caller read it
    # before it waited for the writer lock. The clock never moves back.
    if clock is not None:
        tx.ctx.now = max(tx.ctx.now, clock())
    deadline_text = gate["deadline_utc"]
    late = deadline_text is not None and tx.ctx.now >= parse_utc(str(deadline_text))
    ours = gate["run_id"] == run_id and gate["decision_id"] == verdict.decision_id
    if not ours or gate["state"] != "open" or late:
        raise Unverified(
            "gate_closed",
            warn=ours
            and (gate["state"] == "expired" or (gate["state"] == "open" and late)),
        )
    # Step 8: one decision open in two runs that list the session needs the run token.
    manifests: dict[str, dict[str, Any]] = {run_id: doc}
    open_runs = 0
    for other in tx.rows(
        "SELECT g.run_id, g.opened_utc, g.closed_utc, r.manifest_json, r.run_id AS rid"
        " FROM gates g JOIN runs r ON r.run_id = g.run_id WHERE g.decision_id = ?",
        (verdict.decision_id,),
    ):
        if not _gate_open_at(other, moment):
            continue
        other_id = str(other["run_id"])
        if other_id not in manifests:
            manifests[other_id] = manifest_doc(other)
        if session_listed(tx, other_id, manifests[other_id], session):
            open_runs += 1
    if open_runs > 1 and run_id not in tokens:
        raise Unverified("ambiguous")
    # Step 9: a single use of the entry and of its prompt.
    used = tx.row(
        "SELECT 1 FROM consumed_rulings WHERE orchestrator_session = ?"
        " AND (user_message_uuid = ? OR prompt_id = ?)"
        " UNION ALL SELECT 1 FROM attaches WHERE orchestrator_session = ?"
        " AND (user_message_uuid = ? OR prompt_id = ?)",
        (session, verdict.uid, prompt_id, session, verdict.uid, prompt_id),
    )
    if used is not None:
        raise Unverified("replay")
    # Step 10: close the gate and consume the tuple in this transaction.
    closed = tx.con.execute(
        "UPDATE gates SET state = 'closed', resolved_by_msg = ?, msg_id = ?, closed_utc = ?,"
        " closed_reason = 'ruling' WHERE gate_id = ? AND state = 'open'",
        (msg_id, msg_id, tx.ctx.now_utc, verdict.gate_id),
    )
    if closed.rowcount != 1:
        raise Unverified("gate_closed")
    tx.transition("gate", verdict.gate_id, "open", "closed")
    tx.con.execute(
        "INSERT INTO consumed_rulings (orchestrator_session, user_message_uuid, prompt_id,"
        " run_id, gate_id, msg_id, ruling_json, consumed_utc, decision_id, payload_hash)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session,
            verdict.uid,
            prompt_id,
            run_id,
            verdict.gate_id,
            msg_id,
            json.dumps(
                {
                    "msg_id": msg_id,
                    "run_id": run_id,
                    "gate_id": verdict.gate_id,
                    "decision_id": verdict.decision_id,
                    "payload_hash": message["payload_hash"],
                    "quote": text,
                    "entry_line": entry.number,
                },
                sort_keys=True,
            ),
            tx.ctx.now_utc,
            verdict.decision_id,
            message["payload_hash"],
        ),
    )
    return RulingVerdict(**{**verdict.__dict__, "verified": True, "quote": text})


def verify_ruling(
    tx: Tx,
    run: sqlite3.Row,
    message: sqlite3.Row,
    clock: Callable[[], datetime] | None = None,
) -> RulingVerdict:
    """R§4.6.3: verify one delivered ruling inside the hook's claim transaction.

    A failed step returns an unverified verdict with its reason; the writes of the
    history check (the mark, the chains and a ``broken`` session) stay. ``clock`` is
    read again right before the deadline check (step 7), so a wait for the writer
    lock counts against the deadline; with None the transaction's clock is used.
    """
    try:
        return _verify(tx, run, message, clock)
    except Unverified as exc:
        return RulingVerdict(False, exc.reason, exc.warn)
    except Refusal as exc:
        return RulingVerdict(
            False, SCAN_ERROR_REASONS.get(exc.error, "transcript_unknown")
        )


def verb_attach(tx: Tx, run_id: str, session: str, uid: str) -> Outcome:
    """R§4.6.3 attach: a typed ``attach <run_id>`` entry records the session for the run.

    The attach scans the whole transcript again and moves the watermark to its end, so
    only later entries can be rulings. Any failed check is a refusal and writes nothing.
    The session need not be listed yet: the attach is how a new IDE session is added
    (R§4.5), so only the checks below decide.
    """
    run = get_run(tx, run_id)
    doc = manifest_doc(run)
    # The session id names the transcript file; it must be a plain key.
    if not KEY_RE.match(session) or ".." in session:
        raise Refusal("session_invalid", f"not a session id: {session!r}")
    scanned = scan_session(tx, run_id, doc, session, first=True)
    if isinstance(scanned, ScanBroken):
        raise Refusal("transcript_discontinuity", scanned.message)
    try:
        entry = _single_entry(scanned, uid)
        prompt_id, text, moment = _check_entry(scanned, entry, session)
        _check_provenance(tx, scanned, entry, session, text)
    except Unverified as exc:
        raise Refusal(
            exc.reason, f"the attach entry {uid} fails: {exc.reason}"
        ) from exc
    created = parse_utc(str(run["created_utc"]))
    last = tx.row(
        "SELECT MAX(attached_utc) AS last FROM attaches WHERE run_id = ?", (run_id,)
    )
    floor = created
    if last is not None and last["last"] is not None:
        floor = max(floor, parse_utc(str(last["last"])))
    if moment <= floor:
        raise Refusal(
            "entry_too_old",
            f"the attach entry {uid} is not later than {format_utc(floor)}",
        )
    tokens = TOKEN_RE.findall(text)
    named = any(
        tokens[i].lower() == "attach" and tokens[i + 1] == run_id
        for i in range(len(tokens) - 1)
    )
    if not named:
        raise Refusal(
            "attach_words_missing", f"the entry does not say: attach {run_id}"
        )
    used = tx.row(
        "SELECT 1 FROM consumed_rulings WHERE orchestrator_session = ?"
        " AND (user_message_uuid = ? OR prompt_id = ?)"
        " UNION ALL SELECT 1 FROM attaches WHERE orchestrator_session = ?"
        " AND (user_message_uuid = ? OR prompt_id = ?)",
        (session, uid, prompt_id, session, uid, prompt_id),
    )
    if used is not None:
        raise Refusal("replay", f"the entry {uid} or its prompt was used before")
    tx.con.execute(
        "INSERT INTO orchestrator_sessions (run_id, session, history_state, attached_utc)"
        " VALUES (?, ?, 'ok', ?) ON CONFLICT (run_id, session)"
        " DO UPDATE SET history_state = 'ok', attached_utc = excluded.attached_utc",
        (run_id, session, tx.ctx.now_utc),
    )
    tx.con.execute(
        "INSERT INTO attaches (orchestrator_session, user_message_uuid, prompt_id, run_id,"
        " attached_utc) VALUES (?, ?, ?, ?, ?)",
        (session, uid, prompt_id, run_id, tx.ctx.now_utc),
    )
    tx.transition("orchestrator_session", f"{run_id}/{session}", None, "ok")
    return Outcome(
        "changed",
        {
            "run_id": run_id,
            "session": session,
            "user_message_uuid": uid,
            "byte_length": scanned.byte_length,
            "line_count": scanned.line_count,
        },
    )


def verb_orchestrator_sessions(tx: Tx, run_id: str | None) -> Outcome:
    """List the attached orchestrator sessions (the monitor scans each one)."""
    if run_id is None:
        rows = tx.rows(
            "SELECT run_id, session, history_state FROM orchestrator_sessions"
            " ORDER BY run_id, session"
        )
    else:
        rows = tx.rows(
            "SELECT run_id, session, history_state FROM orchestrator_sessions"
            " WHERE run_id = ? ORDER BY session",
            (run_id,),
        )
    return Outcome(
        "ok",
        {
            "sessions": [
                {
                    "run_id": str(row["run_id"]),
                    "session": str(row["session"]),
                    "history_state": str(row["history_state"]),
                }
                for row in rows
            ]
        },
    )


# --- dispatch ---------------------------------------------------------------------------


def run_verb(ctx: Context, args: argparse.Namespace) -> Outcome:
    """Dispatch one verb to its transaction."""
    verb = args.verb
    if verb == "init":
        changed = migrate(ctx, crash_points=True)
        return Outcome("changed" if changed else "no_change")
    migrate(ctx, crash_points=False)
    if verb == "scan_effects":
        return verb_scan_effects(ctx)
    if verb == "register":
        manifest = load_manifest(args.manifest, args.run_id)
        return transact(ctx, lambda tx: verb_register(tx, args.run_id, manifest, args))
    bodies: dict[str, Callable[[Tx], Outcome]] = {
        "check": verb_check,
        "clear_check": lambda tx: verb_clear_check(tx, args.note),
        "registered": lambda tx: verb_registered(tx, args.run_id, args.task_hash),
        "registration_failed": lambda tx: verb_registration_failed(
            tx, args.run_id, args.reason
        ),
        "request": lambda tx: verb_request(tx, args),
        "not_started": lambda tx: verb_not_started(tx, args.request_id, args.reason),
        "accept": lambda tx: verb_accept(tx, args),
        "admit": lambda tx: verb_admit(tx, args.attempt_id, args.segment_id, args.base),
        "launched": lambda tx: verb_launched(tx, args),
        "complete_segment": lambda tx: verb_complete_segment(tx, args),
        "classify": lambda tx: verb_classify(
            tx, args.run_id, args.to, args.stop_class, args.notice_ref, args.notice_json
        ),
        "cancel": lambda tx: verb_cancel(tx, args.run_id, args.reason),
        "register_minimal": lambda tx: verb_register_minimal(tx, args),
        "manual_identity": lambda tx: verb_manual_identity(tx, args),
        "settle": lambda tx: verb_settle(tx, args),
        "spend": lambda tx: verb_spend(tx, args.run_id),
        "run_status": lambda tx: verb_run_status(tx, args.run_id),
        "termination_pending": lambda tx: verb_termination_pending(tx, args.segment_id),
        "send": lambda tx: verb_send(tx, args),
        "scan_requests": verb_scan_requests,
        "scan_attempts": lambda tx: verb_scan_attempts(tx, args.proofs_json),
        "scan_segments": lambda tx: verb_scan_segments(tx, args.proofs_json),
        "lease": lambda tx: verb_lease(tx, args),
        "lease_release": lambda tx: verb_lease_release(tx, args),
        "alive": lambda tx: verb_alive(tx, args.segment_id),
        "notice": lambda tx: verb_notice(tx, args),
        "notices_due": verb_notices_due,
        "monitor_view": verb_monitor_view,
        "notice_sent": lambda tx: verb_notice_sent(tx, args.key),
        "notice_failed": lambda tx: verb_notice_failed(tx, args.key, args.error),
        "outbox_scan": verb_outbox_scan,
        "predicates": lambda tx: verb_predicates(tx, args.run_id, args.base),
        "chain_candidates": verb_chain_candidates,
        "accept_drift": lambda tx: verb_accept_drift(tx, args),
        "prune": lambda tx: verb_prune(tx, args.run_id),
        "scan_transcript": lambda tx: verb_scan_transcript(
            tx, args.run_id, args.session
        ),
        "attach": lambda tx: verb_attach(tx, args.run_id, args.session, args.uuid),
        "orchestrator_sessions": lambda tx: verb_orchestrator_sessions(tx, args.run_id),
    }
    body = bodies.get(verb)
    if body is None:
        raise UsageError(f"unknown verb {verb!r}")
    return transact(ctx, body)


def open_store(db: str, busy_ms: int) -> sqlite3.Connection:
    """Open the store with the R§4.7 connection settings."""
    con = sqlite3.connect(db, isolation_level=None, timeout=busy_ms / 1000)
    con.row_factory = sqlite3.Row
    try:
        con.execute(f"PRAGMA busy_timeout = {int(busy_ms)}")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = FULL")
        con.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        con.close()
        raise
    return con


def emit(payload: dict[str, Any], code: int) -> int:
    """Print the one JSON object and return the exit code."""
    sys.stdout.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
    sys.stdout.flush()
    return code


def outcome_code(outcome: Outcome) -> int:
    """Map a verb result to its exit code."""
    if outcome.result == "failed":
        return EXIT_CHECK_FAILED
    if outcome.result == "refused":
        # A verb that commits a record and then refuses (scan_transcript).
        return EXIT_REFUSED
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run one verb and return the exit code."""
    try:
        args = build_parser().parse_args(argv)
        crash_at = parse_crash_at(os.environ.get("CREDITS_TEST_CRASH_AT"))
        busy_ms = busy_timeout_ms(args.profile)
        clock = None if args.now_utc else production_clock
        now = parse_utc(args.now_utc) if args.now_utc else production_clock()
    except UsageError as exc:
        return emit(
            {"result": "usage_error", "error": "usage", "message": str(exc)}, EXIT_USAGE
        )
    verb = str(args.verb)

    reason = store_not_local_reason(args.db)
    if reason is not None:
        return emit(
            {"result": "refused", "error": "store_not_local", "message": reason},
            EXIT_REFUSED,
        )

    con: sqlite3.Connection | None = None
    try:
        # The check view opens the store read only (R§4.5); every other verb writes.
        con = (
            open_store_read_only(args.db, busy_ms)
            if verb == "view"
            else open_store(args.db, busy_ms)
        )
        ctx = Context(
            con=con,
            db=Path(args.db),
            verb=verb,
            profile=args.profile,
            now=now,
            crash_at=crash_at,
            busy_tries=BUSY_TRIES[args.profile],
            clock=clock,
        )
        version = user_version(con)
        if version > SCHEMA_VERSION:
            return emit(
                {
                    "result": "refused",
                    "error": "schema_too_new",
                    "message": f"store schema {version} is newer than {SCHEMA_VERSION}",
                },
                EXIT_REFUSED,
            )
        outcome = verb_view(ctx, args) if verb == "view" else run_verb(ctx, args)
        payload = {"result": outcome.result, "verb": verb, **outcome.payload}
        if verb in ("init", "check"):
            payload["connection"] = connection_settings(con)
        return emit(payload, outcome_code(outcome))
    except UsageError as exc:
        return emit(
            {"result": "usage_error", "error": "usage", "message": str(exc)}, EXIT_USAGE
        )
    except Refusal as exc:
        return emit({**exc.payload(), "verb": verb}, EXIT_REFUSED)
    except StoreBusy as exc:
        log("store_busy_exit", verb=verb, error=str(exc))
        return emit(
            {"result": "busy", "error": "store_busy", "message": str(exc)}, EXIT_BUSY
        )
    except sqlite3.Error as exc:
        code = sqlite_code(exc)
        if code in SQLITE_BUSY_CODES:
            log("store_busy_exit", verb=verb, error=str(exc))
            return emit(
                {"result": "busy", "error": "store_busy", "message": str(exc)},
                EXIT_BUSY,
            )
        if (
            code in SQLITE_CORRUPT_CODES
            or isinstance(exc, sqlite3.DatabaseError)
            and "not a database" in str(exc)
        ):
            result = "failed" if verb == "check" else "refused"
            return emit(
                {
                    "result": result,
                    "error": "store_corrupt",
                    "message": str(exc),
                    "verb": verb,
                },
                EXIT_CHECK_FAILED if verb == "check" else EXIT_REFUSED,
            )
        if isinstance(exc, sqlite3.IntegrityError):
            return emit(
                {
                    "result": "refused",
                    "error": "constraint_violation",
                    "message": str(exc),
                    "verb": verb,
                },
                EXIT_REFUSED,
            )
        log("store_error", verb=verb, code=code, error=str(exc))
        return emit(
            {
                "result": "refused",
                "error": "store_unavailable",
                "message": str(exc),
                "verb": verb,
            },
            EXIT_REFUSED,
        )
    finally:
        if con is not None:
            con.close()


if __name__ == "__main__":
    sys.exit(main())
