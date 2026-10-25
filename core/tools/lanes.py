"""Lane cards: admission, heartbeat, release and ownership checks for parallel lanes.

Design: ``docs/execution/plans/2026-10-20-multi-agent-lanes/design/design.md``
§5.2 "Lane cards", §5.3 "Ownership in the plan", §5.7 "Messages and halts";
plan ``implementation-plan.md`` §MEU-784 (AC-784.2–AC-784.9, EA-8).

Coordination state lives in the git common directory, which git does not
track: one card per lane at ``<common>/lanes/<lane>.json``, the registry lock
``<common>/lanes/registry.lock`` (the shared OS lease, ``tools/os_lease.py``)
and the human's halt file ``<common>/lanes/HALT``.

- Every card write happens under the registry lock, compares ``session``,
  ``generation`` and ``op`` with the caller's expectation, and replaces the
  card through a temporary file and ``os.replace``.
- A card in ``active`` or ``landing`` reserves its worktree, branch, ``owns``
  and claims. A card with no ``updated`` change for 6 hours is stale; stale
  does not mean dead, and only the human frees it.
- Ownership compares the repository-relative paths git prints, after NFC and,
  when ``core.ignorecase`` is true, case folding. A path through a symbolic
  link, junction or other reparse point is refused (filesystem metadata).

Commands (stdout; a refusal prints ``refused: <reason>`` and exits 1):

    lanes.py claim   --plan <dir> --worktree <path> [--session S]
    lanes.py beat    --plan <dir> [--session S] [--generation G]   # exit 3 under HALT
    lanes.py release (--plan <dir> | --worktree <path> [--reset]) [--session S] [--generation G]
    lanes.py commit  --worktree <path> --message-file <file> [--generation G]
    lanes.py land prepare --worktree <path> --l0 <sha> --message-file <file> [--op <id>]
    lanes.py land prepare --op <id> --verdict <file>             # bound to tree(T)
    lanes.py land recover --op <id>                              # exit 3 op_busy
    lanes.py list    [--json]
    lanes.py check   --plan <dir> [--base <rev>]
    lanes.py gate run --worktree <path> -- <argv...>             # exits with the child's code
    lanes.py deps begin --worktree <path> [--wait-s N]           # N: 0-3600, default 600
    lanes.py deps end   --worktree <path>

The lane slug is the plan folder name. The session comes from ``--session``,
else ``{{PROJECT_NAME_UPPER}}_SESSION`` (the commit helper reads only
``{{PROJECT_NAME_UPPER}}_SESSION``). The junction files come from the
``junction_files`` key of ``.agent/credits/worktree.json``; a missing or
invalid config refuses ``claim`` with ``worktree_bad:config``. Python standard
library only, except the ``land`` verbs: they import ``tools/commit_batch.py``
(and so the run-parameters store) when they run.

Stage 2 (MEU-785, design §5.1, AC-785.2–AC-785.8): a lane works on its own
branch ``lane/<slug>``. ``claim`` records that branch from the worktree's
symbolic HEAD and refuses the main tree (``main_reserved``) and any other HEAD
(``head_not_lane``). ``commit`` is the lane commit helper: under the worktree
lease and the registry lock it checks the caller's card and HEAD, then runs
``git commit -F <file>`` with a fixed argument list, the hooks and a cleaned
git environment, and prints ``commit_ok:<sha>``. ``release`` refuses a
``landing`` card while its worktree is still live (``release_unreset``).
``release --reset`` (AC-785.8) moves ``lane/<slug>`` from ``L0`` to the landed
commit ``C`` of a closed land (``read-tree -m -u L0 C``, then ``update-ref`` with
the old-value check) and releases the card; ``release`` also accepts a
``landing`` card whose branch already equals ``C``.
``check`` reports a linked worktree that has ``main`` checked out
(``main_reserved:<path>``). Every git call of this module runs without the
caller's repository-redirecting git variables (``_git_env``).

The land journal (AC-785.11, AC-785.12) lives in the commit_batch op store and
only commit_batch's journal writer writes it; this module never writes an op
file. ``land recover --op <id>`` takes the per-op recovery lease
``<common>/lanes/ops/<op>.lease`` in one attempt (held: ``op_busy``, exit 3,
nothing written), then reads the journal and the card again
(``op_unknown``, ``journal_moved``, ``card_superseded``).

``land prepare`` (design §5.5 steps 1-2, AC-785.13, AC-785.14) holds the same op
lease. Step 1 (freeze) takes the lane worktree lease, checks the card, a clean
lane worktree and ``lane/<slug> == L0``, writes the journal entry
``{op, lane, generation, session, P, L0}`` first and then sets the card to
``landing`` with ``op``. Step 2 rebases ``L0`` onto ``P`` in a disposable
detached candidate under the candidate root
(``git -c rebase.updateRefs=false rebase --onto P <merge-base(P, L0)>``); the
owner's worktree and branch never move. A conflict journals ``land:conflict``,
removes the candidate, sets the card back to ``active`` and refuses
``land_conflict:<paths>``; a change of ``P -> L1`` outside the card's ``owns``
(a rename counts both paths; ``must_not_touch`` wins) refuses
``owns_violation:<path>`` the same way.

Steps 3-5 (design §5.4 and §5.5, AC-785.15 to AC-785.17). Step 3 reads the
lane handoff ``.agent/context/handoffs/<slug>-handoff.md`` of L1, checks every
``## Integration requests`` row against the closed forms (``meu-status``,
``grouping-cursor``, ``ki-file``, ``ki-close``, ``metrics-row``), applies each
once with the candidate's own tools, lists a conflict as
``request_conflict:<id>``, regenerates the derived files and commits T on L1;
the baselines and ``current-focus.md`` stay as they are. Step 4 writes the
kept refs ``refs/lanes/<slug>/<op>/{L0,L1,T}``. Step 5 runs the gate on T,
journals ``gate{tree, result}``, prints the report and ends
``land_ready:<op>:<tree of T>``. ``land prepare --op ID --verdict FILE``
records an approved ``land-verdict/1`` file for that tree (``verdict_stale``,
``verdict_not_approved`` otherwise). ``land recover`` after step 3 re-runs
steps 4-5 from the kept objects.

Step 6 (design §5.5, AC-785.18, AC-785.20). Step 5 also journals
``carrier{task, plan, grouping}``, the blob ids of the lane plan's carriers at
L1. ``land publish --op ID`` decides the authority for that ready land without
holding a lease: ``--grant`` verifies and reserves the lane plan's
``exec_commit`` grant over the committed carriers (``_check_scope`` refuses
``scope_branch_mismatch`` unless ``scope.branch`` is ``main``);
``--human-directed --session S --message-uuid U`` resolves the typed record
through commit_batch's ``_consent`` to "the <slug> plan" on ``main``; with
neither it refuses ``needs_human_publish`` and prints the sentence
``Commit the <slug> plan on main.``. A lane worktree carrier that no longer
hashes to the recorded blob refuses ``carrier_mismatch``. With authority it
journals ``land:authorized`` and ends ``land_authorized:<op>:<tree>:<route>``.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import io
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Callable, Iterator, Mapping, Sequence, cast

if sys.platform == "win32":
    from ctypes import wintypes

if __package__:
    from . import executor_worktree, os_lease
else:  # run as a script, or imported with tools/ on sys.path
    import executor_worktree
    import os_lease

if TYPE_CHECKING:
    from tools.commit_batch import LandOp
    from tools.run_parameters import Repo as RpRepo

Card = dict[str, Any]

STALE_S = 21600
REGISTRY_WAIT_S = 10.0
POLL_S = 0.05
# Design §2.4, §9.2: the junction files only the integrator edits are project data,
# the ``junction_files`` key of ``.agent/credits/worktree.json`` (D-P10, §5.4).
JUNCTION_KEY = "junction_files"

LANES_DIR = "lanes"
REGISTRY_LOCK = "registry.lock"
HALT_FILE = "HALT"
# The ref guard's install inventory (``tools/ref_guard.py``) sits beside the cards;
# it is not a card, and no lane may take its name.
GUARD_INVENTORY = "ref-guard.json"
SESSION_ENV = "{{PROJECT_NAME_UPPER}}_SESSION"
OWNERSHIP_HEADING = "## Lane Ownership"
LOCK_BODY_SCHEMA = "lanes-registry/1"
UPDATED_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
CARD_KEYS = (
    "lane",
    "generation",
    "session",
    "state",
    "op",
    "worktree",
    "branch",
    "plan",
    "owns",
    "claims",
    "gates",
    "updated",
)
CARD_STATES = ("active", "landing", "released")
RESERVING_STATES = ("active", "landing")
OWNERSHIP_KEYS = ("owns", "must_not_touch")
EXIT_REFUSED = 1
EXIT_HALT = 3
# AC-785.12: a second recovery of one op is an ordering wait, not a refusal.
EXIT_BUSY = 3
# The per-op recovery lease ``<common>/lanes/ops/<op>.lease`` (design §10b N-6):
# one attempt, no wait (IP Constant Classification "op recovery lease wait").
OPS_DIR = "ops"
OP_LEASE_SUFFIX = ".lease"
OP_LEASE_WAIT_S = 0.0
# The commit helper's worktree lease: one attempt, no wait (IP Constant
# Classification "helper lease wait", D:171); the registry lock keeps its wait.
HELPER_LEASE_WAIT_S = 0.0
# The worktree lease: the gate lease file of ``tools/executor_worktree.py``
# (``LEASE_NAME``) inside ``git rev-parse --absolute-git-dir`` of the worktree.
GATE_LEASE_NAME = executor_worktree.LEASE_NAME
# Gate registration and the deps sequence (design §5.8, §10b N-5; AC-785.29,
# AC-785.30, AC-785.40): a card's ``gates`` items and its one ``deps`` claim.
GATE_ENTRY_KEYS = ("pid", "lease", "started", "workload")
GATE_STARTED_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
DEPS_KIND = "deps"
DEPS_PENDING = "pending"
DEPS_EXCLUSIVE = "exclusive"
DEPS_STATES = (DEPS_PENDING, DEPS_EXCLUSIVE)
# ``deps begin --wait-s N``: an integer number of seconds, 0 to 3600.
DEPS_DRAIN_WAIT_S = 600
DEPS_DRAIN_WAIT_MAX_S = 3600
MESSAGE_MAX_BYTES = 64 * 1024
LANE_REF_PREFIX = "refs/heads/lane/"
MAIN_REF = "refs/heads/main"
# The land (design §5.5): its journal phases are commit_batch's ``LAND_PHASES``.
LAND_FREEZE = "land:freeze"
LAND_REBASE = "land:rebase"
LAND_CONFLICT = "land:conflict"
LAND_INTEGRATE = "land:integrate"
LAND_KEPT = "land:kept"
LAND_READY = "land:ready"
LAND_AUTHORIZED = "land:authorized"
# Step 6 (design §5.5, D:248, AC-785.18): the publication branch, the act a grant
# must hold for it, and the sentence the human types for the human-directed route.
PUBLISH_BRANCH = MAIN_REF.removeprefix("refs/heads/")
PUBLISH_ACT = "exec_commit"
HUMAN_PUBLISH_SENTENCE = "Commit the {plan} plan on main."
# The journal points ``land recover`` resumes at step 4 (D:262 "Steps 4-5", EA-25).
RECOVER_READY_POINTS = frozenset(
    {
        f"{LAND_INTEGRATE}:done",
        f"{LAND_KEPT}:started",
        f"{LAND_KEPT}:done",
        f"{LAND_READY}:started",
    }
)
LAND_CLOSED = "land:closed"
LAND_PUBLISHED = "published"
# D:263-264 "Step 7": a publication whose ``published`` entry is still ``started``.
RECOVER_PUBLISH_POINT = f"{LAND_PUBLISHED}:started"
# Step 8 (AC-785.21): the sync of the main checkout is its own journal phase.
LAND_SYNC = "land:sync"
# D:260 "Step 1 done, before step 4": the phases whose recovery removes the candidate and
# sets the card back to ``active`` (AC-785.23); ``land:integrate:started`` is the same row.
RECOVER_ABANDON_PHASES = frozenset({LAND_FREEZE, LAND_REBASE, LAND_CONFLICT})
RECOVER_ABANDON_POINT = f"{LAND_INTEGRATE}:started"
# D:262 "Step 6": nothing to recover, the land waits for authority without a lock.
RECOVER_WAIT_POINTS = frozenset(
    {f"{LAND_READY}:done", f"{LAND_AUTHORIZED}:started", f"{LAND_AUTHORIZED}:done"}
)
# The journal points ``land recover`` resumes at step 8 or 9 (EA-60).
RECOVER_CLOSE_POINTS = frozenset(
    {f"{LAND_PUBLISHED}:done", f"{LAND_SYNC}:done", f"{LAND_CLOSED}:started"}
)
# Step 4 (design §5.5, N-3): the kept refs ``refs/lanes/<slug>/<op>/{L0,L1,T}``.
KEPT_REF_PREFIX = "refs/lanes"
KEPT_NAMES = ("L0", "L1", "T")
# Step 3 (design §5.4, AC-785.15): the lane handoff and its requests table.
HANDOFFS_DIR = ".agent/context/handoffs"
REQUESTS_HEADING = "## Integration requests"
# The one grammar of the integration requests (IP "Integration request grammar").
REQUEST_FORMS: dict[str, str] = {
    "meu-status": "meu-status <MEU-ID> -> <status> [reason=<text>]",
    "grouping-cursor": "grouping-cursor <grouping-file> -> <session-id>",
    "ki-file": "ki-file <KI-ID> <payload-path>",
    "ki-close": "ki-close <KI-ID> -> <text>",
    "metrics-row": "metrics-row <row>",
}
MEU_STATUS_FILE = ".agent/context/meu-status.yaml"
KI_YAML_FILE = ".agent/context/known-issues.yaml"
KI_MD_FILE = ".agent/context/known-issues.md"
METRICS_FILE = "docs/execution/metrics.md"
# Step 3 (D:237, AC-785.15, R1-F8): current-focus.md is P's text plus the landed lane.
CURRENT_FOCUS_FILE = ".agent/context/current-focus.md"
FOCUS_LANDED_HEADING = "## Landed lanes"
MEU_STATUSES = frozenset(
    {
        "approved",
        "changes_required",
        "closed",
        "deferred",
        "in_progress",
        "pending",
        "ready_for_review",
    }
)
KI_REQUIRED_KEYS = ("title", "severity", "component")
KI_OPTIONAL_KEYS = ("status", "discovered", "root_cause", "blast_radius")
KI_SEVERITIES = frozenset({"critical", "high", "low", "medium"})
KI_COMPONENTS = frozenset({"api", "core", "infrastructure", "mcp-server", "ui"})
# The ``--add-status`` choices of ``issue_triage.py add``.
KI_STATUSES = frozenset(
    {
        "candidate",
        "dismissed",
        "in_progress",
        "mitigated",
        "open",
        "resolved",
        "workaround",
    }
)
# The integrator never changes these; it never stages them (AC-785.15).
BASELINE_FILES = (".secrets.baseline", "tools/temp_citation_baseline.json")
# Step 5 (AC-785.17, EA-18): the gate runs in the candidate; its output goes to a
# log in the candidate's git dir. The gate script is adopter-supplied: the package
# ships no ``tools/validate_codebase.py`` (PROFILE D6, ``scripts/refcheck.py``); a
# project without one gets the failed gate ``fail:2`` in the report.
GATE_SCRIPT = "tools/validate_codebase.py"
GATE_LOG_NAME = "land-gate.txt"
GATE_PASS = "pass"
# R1-F6: the gate runs with the candidate's runtime; a caller's venv variables
# would point its ``uv run`` at another tree's venv (executor_worktree's list).
GATE_ENV_DROPPED = ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
# ``land prepare --op ID --verdict FILE`` (IP boundary row "Verdict file").
VERDICT_SCHEMA = "land-verdict/1"
VERDICT_KEYS = ("schema", "op", "tree", "verdict", "review")
VERDICT_VALUES = ("approved", "changes_required")
VERDICT_APPROVED = "approved"
# The land candidate ``<candidate root>/land-<op>`` and its manifest, written into
# the candidate's git dir like commit_batch's ``candidate-worktree.json``.
LAND_CANDIDATE_PREFIX = "land-"
LAND_MANIFEST_NAME = "candidate-worktree.json"
LAND_MANIFEST_SCHEMA = "candidate-worktree/1"
LAND_OP_PREFIX = "land-"
# Every git call that adds or removes a candidate passes this: the candidate root
# plus a deep repository path can pass the Windows MAX_PATH (EA-50).
GIT_LONGPATHS = ("-c", "core.longpaths=true")
# AC-785.5: the git variables that redirect a git call to another repository,
# index or configuration. They never reach a git child of this module.
SCRUBBED_GIT_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
)
SCRUBBED_GIT_ENV_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")

_LANE_RE = re.compile(r"[a-z0-9-]+")
_GENERATION_RE = re.compile(r"[0-9a-f]{16}")
_OBJECT_ID_RE = re.compile(r"[0-9a-f]{40}")
_UPDATED_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
_DRIVE_RE = re.compile(r"[A-Za-z]:")
_GLOB_CHARS = frozenset("*?[]")
_KEY_LINE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*):(.*)")
_ITEM_LINE_RE = re.compile(r"\s+-(\s.*)?")
_REQUEST_SYNTAX = {
    "meu-status": re.compile(
        r"meu-status (?P<meu>\S+) -> (?P<status>\S+)(?: reason=(?P<reason>.+))?"
    ),
    "grouping-cursor": re.compile(r"grouping-cursor (?P<file>\S+) -> (?P<session>\S+)"),
    "ki-file": re.compile(r"ki-file (?P<ki>\S+) (?P<payload>\S+)"),
    "ki-close": re.compile(r"ki-close (?P<ki>\S+) -> (?P<text>.*)"),
    "metrics-row": re.compile(r"metrics-row (?P<row>\|.*)"),
}
_KI_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_DATE_RE = re.compile(r"\d{4}-\d\d-\d\d")
_CURSOR_RE = re.compile(r"^(Global cursor: \*\*)([^*\r\n]+)(\*\*)", re.MULTILINE)
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
_SEPARATOR_RE = re.compile(r"\|(?:\s*:?-+:?\s*\|)+")


class Refusal(Exception):
    """A refused lane operation: ``reason`` is the stable token, ``detail`` the advice."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def _utc_text(moment: datetime) -> str:
    """``moment`` as the card's ``updated`` text (UTC, whole seconds, ``Z``)."""
    return moment.astimezone(timezone.utc).strftime(UPDATED_FORMAT)


def _parse_updated(text: str) -> datetime:
    """The aware UTC datetime of an ``updated`` value.

    Raises:
        ValueError: ``text`` is not ``YYYY-MM-DDTHH:MM:SSZ``.
    """
    if not _UPDATED_RE.fullmatch(text):
        raise ValueError(f"not {UPDATED_FORMAT}: {text!r}")
    return datetime.strptime(text, UPDATED_FORMAT).replace(tzinfo=timezone.utc)


def _is_stale(card: Card, now: datetime) -> bool:
    """True when ``card`` has had no ``updated`` change for more than STALE_S."""
    return (now - _parse_updated(card["updated"])).total_seconds() > STALE_S


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def _bad(key: str, detail: str) -> Refusal:
    return Refusal(f"card_bad:{key}", detail)


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_count(value: object) -> bool:
    """A positive int that is not a bool (a pid, a pgid)."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_deps_claim(value: object) -> bool:
    """``{kind: deps, state: pending|exclusive}`` (AC-785.30), exactly."""
    return (
        isinstance(value, dict)
        and set(value) == {"kind", "state"}
        and value["kind"] == DEPS_KIND
        and value["state"] in DEPS_STATES
    )


def _is_workload_item(value: object) -> bool:
    """``{pid, created}`` (Windows) or ``{pgid}`` (POSIX), AC-785.29."""
    if not isinstance(value, dict):
        return False
    if set(value) == {"pgid"}:
        return _is_count(value["pgid"])
    return (
        set(value) == {"pid", "created"}
        and _is_count(value["pid"])
        and isinstance(value["created"], int)
        and not isinstance(value["created"], bool)
    )


def _is_gate_entry(value: object) -> bool:
    """One ``gates`` item ``{pid, lease, started, workload}`` (AC-785.29, EA-2)."""
    if not isinstance(value, dict) or set(value) != set(GATE_ENTRY_KEYS):
        return False
    workload = value["workload"]
    return (
        _is_count(value["pid"])
        and isinstance(value["lease"], str)
        and bool(value["lease"])
        and isinstance(value["started"], str)
        and bool(value["started"])
        and isinstance(workload, list)
        and all(_is_workload_item(item) for item in workload)
    )


def _str_claims(card: Card) -> set[str]:
    """The card's named claims; the ``deps`` claim is not a reservation name."""
    return {claim for claim in card["claims"] if isinstance(claim, str)}


def _canonical_abs_posix(value: str) -> bool:
    """True for an absolute path in canonical forward-slash form."""
    if not value or "\\" in value or not Path(value).is_absolute():
        return False
    if Path(value).as_posix() != value:
        return False
    return not any(part in (".", "..") for part in PurePosixPath(value).parts)


def _validate_card(card: object) -> Card:
    """``card`` when it has exactly the card fields with valid values.

    Raises:
        Refusal: ``card_bad:extra`` for an unknown key, else
            ``card_bad:<key>`` for the first missing or invalid field.
    """
    if not isinstance(card, dict):
        raise _bad("json", "a card is one JSON object")
    extra = sorted(str(key) for key in card if key not in CARD_KEYS)
    if extra:
        raise _bad("extra", f"unknown keys {extra}")
    for key in CARD_KEYS:
        if key not in card:
            raise _bad(key, "missing")
    if not isinstance(card["lane"], str) or not _LANE_RE.fullmatch(card["lane"]):
        raise _bad("lane", "lowercase letters, digits and '-' only")
    generation = card["generation"]
    if not isinstance(generation, str) or not _GENERATION_RE.fullmatch(generation):
        raise _bad("generation", "16 lowercase hex digits")
    if not isinstance(card["session"], str) or not card["session"]:
        raise _bad("session", "a non-empty string")
    if card["state"] not in CARD_STATES:
        raise _bad("state", f"one of {list(CARD_STATES)}")
    op = card["op"]
    if card["state"] == "landing":
        if not isinstance(op, str) or not op:
            raise _bad("op", "a landing card names its land operation")
    elif op is not None:
        raise _bad("op", "op is null unless the card is landing")
    worktree = card["worktree"]
    if not isinstance(worktree, str) or not _canonical_abs_posix(worktree):
        raise _bad("worktree", "an absolute canonical forward-slash path")
    branch = card["branch"]
    if branch is not None and (not isinstance(branch, str) or not branch):
        raise _bad("branch", "null or a branch name")
    if not isinstance(card["plan"], str) or not card["plan"]:
        raise _bad("plan", "the plan folder")
    if not _is_str_list(card["owns"]):
        raise _bad("owns", "a list of strings")
    claims = card["claims"]
    if not isinstance(claims, list) or not all(
        isinstance(claim, str) or _is_deps_claim(claim) for claim in claims
    ):
        raise _bad(
            "claims",
            "a list of strings and {kind: deps, state: pending|exclusive} claims",
        )
    if sum(1 for claim in claims if not isinstance(claim, str)) > 1:
        raise _bad("claims", "at most one deps claim")
    gates = card["gates"]
    if not isinstance(gates, list) or not all(_is_gate_entry(item) for item in gates):
        raise _bad("gates", "a list of {pid, lease, started, workload} entries")
    updated = card["updated"]
    try:
        if not isinstance(updated, str):
            raise ValueError("not a string")
        _parse_updated(updated)
    except ValueError as exc:
        raise _bad("updated", str(exc)) from None
    return card


def _load_card(path: Path) -> Card:
    """The validated card at ``path``.

    Raises:
        Refusal: ``card_bad:<key>`` (``card_bad:json`` when the file is not
            one JSON object, ``card_bad:lane`` when the file name and the
            ``lane`` field differ).
        OSError: the file cannot be read.
    """
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _bad("json", f"{path}: {exc}") from None
    card = _validate_card(data)
    if card["lane"] != path.stem:
        raise _bad("lane", f"{path} holds lane {card['lane']!r}")
    return card


def _lanes_dir(common: Path) -> Path:
    return Path(common) / LANES_DIR


def _card_files(lanes_dir: Path) -> list[Path]:
    """The card files of ``lanes_dir``, sorted; the ref guard inventory is not one."""
    if not lanes_dir.is_dir():
        return []
    return sorted(
        path for path in lanes_dir.glob("*.json") if path.name != GUARD_INVENTORY
    )


def _card_path(common: Path, lane: str) -> Path:
    return _lanes_dir(common) / f"{lane}.json"


def _other_cards(lanes_dir: Path, exclude: str) -> list[Card]:
    """Every card in ``lanes_dir`` except lane ``exclude``.

    Raises:
        Refusal: a card is unreadable; it may reserve something, so admission
            fails closed until the human repairs or removes it.
    """
    cards: list[Card] = []
    for path in _card_files(lanes_dir):
        if path.stem == exclude:
            continue
        try:
            cards.append(_load_card(path))
        except Refusal as exc:
            raise Refusal(
                exc.reason,
                f"{path} is unreadable ({exc.detail}); it may reserve resources, "
                "so admission waits until the human repairs or removes it",
            ) from None
    return cards


def _overlaps(a: str, b: str) -> bool:
    """Component-aware overlap of two entries: one equals or holds the other.

    A trailing ``/`` marks a directory prefix; ``a/b`` holds ``a/b/c`` but not
    ``a/bc``.
    """
    core_a = a.rstrip("/")
    core_b = b.rstrip("/")
    return (
        core_a == core_b
        or core_b.startswith(core_a + "/")
        or core_a.startswith(core_b + "/")
    )


def _covers(entry: str, path: str) -> bool:
    """True when ownership ``entry`` equals ``path`` or is a directory above it."""
    core = entry.rstrip("/")
    return path == core or path.startswith(core + "/")


def _normalize(path: str, ignorecase: bool) -> str:
    """``path`` in NFC, then case-folded when ``ignorecase`` is true."""
    text = unicodedata.normalize("NFC", path)
    return text.casefold() if ignorecase else text


def _same_worktree(a: str, b: str) -> bool:
    return os.path.normcase(a) == os.path.normcase(b)


def _conflict_with(new: Card, other: Card, ignorecase: bool) -> str | None:
    """The first reservation of ``other`` that ``new`` collides with, if any."""
    if new["branch"] is not None and new["branch"] == other["branch"]:
        return "branch_reserved"
    if _str_claims(new) & _str_claims(other):
        return "claim_reserved"
    for entry in new["owns"]:
        mine = _normalize(entry, ignorecase)
        for theirs in other["owns"]:
            if _overlaps(mine, _normalize(theirs, ignorecase)):
                return f"owns_overlap:{other['lane']}:{entry}"
    if _same_worktree(new["worktree"], other["worktree"]):
        return "worktree_reserved"
    return None


def _reservation_conflict(
    new: Card, others: Sequence[Card], *, now: datetime, ignorecase: bool
) -> str | None:
    """The refusal reason for admitting ``new`` beside ``others``, or None.

    Only ``active`` and ``landing`` cards reserve. A conflicting card that is
    stale refuses as ``stale_reserving:<lane>``: only the human frees it.
    """
    for other in others:
        if other["lane"] == new["lane"] or other["state"] not in RESERVING_STATES:
            continue
        reason = _conflict_with(new, other, ignorecase)
        if reason is None:
            continue
        if _is_stale(other, now):
            return f"stale_reserving:{other['lane']}"
        return reason
    return None


def _conflict_detail(reason: str, lanes_dir: Path, others: Sequence[Card]) -> str:
    lane = reason.split(":", 2)[1] if ":" in reason else None
    if reason.startswith("stale_reserving:") and lane is not None:
        return (
            f"the card {lanes_dir / f'{lane}.json'} reserves what this lane needs and "
            f"has had no update for over {STALE_S // 3600} hours. Stale does not mean "
            "dead: only the human removes or reassigns that card."
        )
    if lane is not None:
        return f"lane {lane} owns an overlapping path; amend the plan's Lane Ownership"
    holders = [o["lane"] for o in others if o["state"] in RESERVING_STATES]
    return f"another reserving card holds it (reserving lanes: {', '.join(holders)})"


def _lock_body(argv: Sequence[str]) -> bytes:
    body = {
        "schema": LOCK_BODY_SCHEMA,
        "pid": os.getpid(),
        "argv": list(argv),
        "started_utc": _utc_text(datetime.now(timezone.utc)),
    }
    return json.dumps(body, sort_keys=True).encode("utf-8")


def _busy_detail(
    busy: os_lease.Busy, wait_s: float, what: str = "the registry lock"
) -> str:
    """Who holds the lock ``what``, from its body, and what a timeout means."""
    try:
        body = json.loads(busy.holder_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        body = None
    if isinstance(body, dict):
        argv = body.get("argv")
        shown_argv = (
            " ".join(str(part) for part in argv)
            if isinstance(argv, list)
            else "unknown"
        )
        holder = (
            f"holder pid {body.get('pid', 'unknown')}, argv {shown_argv}, "
            f"started {body.get('started_utc', 'unknown')}"
        )
    else:
        holder = f"holder body {busy.holder_body[:200]!r}"
    return (
        f"{what} {busy.path} is still held after {wait_s:g} s ({holder}).\n"
        "A timeout does not mean the holder died; retry, or ask the human to "
        "check that process."
    )


def _replace_atomically(path: Path, data: bytes) -> None:
    """Write ``data`` to a temporary file beside ``path``, then ``os.replace`` it."""
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def _registry_lock(
    common: Path,
    *,
    wait_s: float,
    poll_s: float,
    argv: Sequence[str] | None = None,
) -> Iterator[Path]:
    """Hold the registry lock for the ``with`` body; yield the lanes directory.

    The lock is the OS lease ``<common>/lanes/registry.lock``
    (``tools/os_lease.py``); its body names this process for a contender.

    Raises:
        Refusal: ``common_dir_unwritable`` (the lanes directory cannot be
            made or locked) or ``registry_busy`` (still held after ``wait_s``).
    """
    lanes_dir = _lanes_dir(common)
    try:
        lanes_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Refusal(
            "common_dir_unwritable", f"cannot create {lanes_dir}: {exc}"
        ) from None
    holder_argv = list(sys.argv if argv is None else argv)
    try:
        lease = os_lease.acquire(
            lanes_dir / REGISTRY_LOCK,
            wait_s=wait_s,
            body=_lock_body(holder_argv),
            poll_s=poll_s,
        )
    except os_lease.Busy as busy:
        raise Refusal("registry_busy", _busy_detail(busy, wait_s)) from None
    except OSError as exc:
        raise Refusal(
            "common_dir_unwritable", f"cannot lock {lanes_dir / REGISTRY_LOCK}: {exc}"
        ) from None
    try:
        yield lanes_dir
    finally:
        os_lease.release(lease)


def _write_card(
    common: Path,
    card: Card,
    *,
    expect: dict[str, str | None] | None,
    wait_s: float,
    poll_s: float,
    ignorecase: bool = False,
    argv: Sequence[str] | None = None,
) -> Path:
    """Write ``card`` under the registry lock; return its path.

    ``expect`` None creates: an existing card of the lane must be
    ``released``, and no other reserving card may conflict
    (``_reservation_conflict``). Otherwise ``expect`` holds the ``session``,
    ``generation`` and ``op`` the current card must carry (the CAS).

    Raises:
        Refusal: ``card_bad:<key>``, ``common_dir_unwritable``,
            ``registry_busy``, ``claim_reserved``, a reservation conflict,
            ``no_card`` or ``card_superseded``. Nothing was written.
        ValueError: ``expect`` lacks one of its three keys.
    """
    card = _validate_card(card)
    if expect is not None and set(expect) != {"session", "generation", "op"}:
        raise ValueError(
            f"_write_card: expect needs session, generation and op, got {sorted(expect)}"
        )
    with _registry_lock(common, wait_s=wait_s, poll_s=poll_s, argv=argv) as lanes_dir:
        path = lanes_dir / f"{card['lane']}.json"
        current = _load_card(path) if path.is_file() else None
        if expect is None:
            if current is not None and current["state"] != "released":
                raise Refusal(
                    "claim_reserved",
                    f"lane {card['lane']} already has a {current['state']} card ({path})",
                )
            others = _other_cards(lanes_dir, exclude=card["lane"])
            reason = _reservation_conflict(
                card, others, now=datetime.now(timezone.utc), ignorecase=ignorecase
            )
            if reason is not None:
                raise Refusal(reason, _conflict_detail(reason, lanes_dir, others))
        else:
            if current is None:
                raise Refusal("no_card", f"no card at {path}")
            held = {key: current[key] for key in ("session", "generation", "op")}
            if held != expect:
                raise Refusal(
                    "card_superseded",
                    f"{path} holds session {held['session']}, generation "
                    f"{held['generation']}, op {held['op']}; this caller expected "
                    f"session {expect['session']}, generation {expect['generation']}, "
                    f"op {expect['op']}. Stop and tell the human.",
                )
            # A released card is final: only a new claim replaces it. A beat or
            # release that read the card before an intervening release stops here.
            if current["state"] == "released":
                raise Refusal(
                    "card_superseded",
                    f"{path} is released; this caller read it before the release. "
                    "Stop and tell the human.",
                )
            # Only the gate API writes ``gates`` and only ``deps begin``/``end``
            # write the deps claim, each under this lock (AC-785.29, AC-785.30);
            # a caller that read the card earlier keeps the current ones.
            card = dict(
                card,
                gates=list(current["gates"]),
                claims=[
                    *(claim for claim in card["claims"] if isinstance(claim, str)),
                    *(
                        claim
                        for claim in current["claims"]
                        if not isinstance(claim, str)
                    ),
                ],
            )
        data = (json.dumps(card, indent=2) + "\n").encode("utf-8")
        try:
            _replace_atomically(path, data)
        except OSError as exc:
            raise Refusal(
                "common_dir_unwritable", f"cannot write {path}: {exc}"
            ) from None
    return path


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


def _entry_ok(entry: str) -> bool:
    """True for a repository-relative exact path or directory prefix (``/``)."""
    if not entry or entry.startswith("/") or "\\" in entry:
        return False
    if _DRIVE_RE.match(entry) or any(ch in _GLOB_CHARS for ch in entry):
        return False
    if any(ord(ch) < 32 for ch in entry):
        return False
    core = entry[:-1] if entry.endswith("/") else entry
    return all(part not in ("", ".", "..") for part in core.split("/"))


def _unquote(value: str, key: str) -> str:
    """A YAML item value: plain, or one single- or double-quoted string."""
    if len(value) >= 2 and value[0] == value[-1] == "'":
        inner = value[1:-1]
        if "'" in inner.replace("''", ""):
            raise Refusal(f"ownership_bad:{key}", f"bad single-quoted item {value}")
        return inner.replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        inner = value[1:-1]
        if '"' in inner or "\\" in inner:
            raise Refusal(f"ownership_bad:{key}", f"escapes are not supported: {value}")
        return inner
    return value


def _ownership_block(text: str, source: Path) -> list[str]:
    """The lines inside the ```yaml fence of the Lane Ownership section."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == OWNERSHIP_HEADING]
    if not starts:
        raise Refusal(
            "no_ownership",
            f"{source} has no '{OWNERSHIP_HEADING}' section; a lane needs one",
        )
    if len(starts) > 1:
        raise Refusal("ownership_bad:section", f"{source} has two ownership sections")
    fence: int | None = None
    for i in range(starts[0] + 1, len(lines)):
        if lines[i].startswith("## "):
            break
        if lines[i].strip() == "```yaml":
            fence = i
            break
    if fence is None:
        raise Refusal(
            "ownership_bad:yaml", f"{source}: the section has no ```yaml block"
        )
    for j in range(fence + 1, len(lines)):
        if lines[j].strip() == "```":
            return lines[fence + 1 : j]
    raise Refusal("ownership_bad:yaml", f"{source}: the ```yaml block is not closed")


def _parse_ownership(block: Sequence[str]) -> dict[str, list[str]]:
    """``owns`` and ``must_not_touch`` from the block: block lists or ``[]``."""
    data: dict[str, list[str]] = {}
    current: str | None = None
    last: str | None = None
    for line in block:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key_match = None if line[0].isspace() else _KEY_LINE_RE.fullmatch(line.rstrip())
        if key_match is not None:
            key, rest = key_match.group(1), key_match.group(2).strip()
            last = key
            if key not in OWNERSHIP_KEYS or key in data:
                raise Refusal(f"ownership_bad:{key}", f"unexpected key line {line!r}")
            if rest == "":
                data[key], current = [], key
            elif rest == "[]":
                data[key], current = [], None
            else:
                raise Refusal(
                    f"ownership_bad:{key}", f"{key} must be a list, got {rest!r}"
                )
            continue
        item_match = _ITEM_LINE_RE.fullmatch(line.rstrip())
        if item_match is not None and current is not None:
            data[current].append(_unquote((item_match.group(1) or "").strip(), current))
            continue
        raise Refusal(f"ownership_bad:{last or 'syntax'}", f"unexpected line {line!r}")
    for key in OWNERSHIP_KEYS:
        if key not in data:
            raise Refusal(f"ownership_bad:{key}", f"missing {key}")
    return data


def _load_ownership(
    task_md: Path, *, ignorecase: bool = False
) -> tuple[list[str], list[str]]:
    """``(owns, must_not_touch)`` of the plan's ``## Lane Ownership`` section.

    Raises:
        Refusal: ``no_ownership``, ``ownership_bad:<key>``,
            ``entry_bad:<entry>`` or ``ownership_contradiction:<own>:<mnt>``.
        OSError: ``task_md`` cannot be read.
    """
    text = task_md.read_text(encoding="utf-8")
    data = _parse_ownership(_ownership_block(text, task_md))
    owns, mnt = data["owns"], data["must_not_touch"]
    for entry in (*owns, *mnt):
        if not _entry_ok(entry):
            raise Refusal(
                f"entry_bad:{entry}",
                "entries are repository-relative paths or prefixes ending in '/': "
                "no globs, absolute paths, drive letters, backslashes, '.' or '..'",
            )
    for own in owns:
        for avoid in mnt:
            if _overlaps(_normalize(own, ignorecase), _normalize(avoid, ignorecase)):
                raise Refusal(
                    f"ownership_contradiction:{own}:{avoid}",
                    "an owns entry and a must_not_touch entry overlap",
                )
    return owns, mnt


def _through_link(root: Path, rel: str) -> bool:
    """True when an existing component of ``root/rel`` is a link or reparse point."""
    current = Path(root)
    for part in rel.rstrip("/").split("/"):
        current = current / part
        try:
            info = os.lstat(current)
        except (FileNotFoundError, NotADirectoryError):
            return False
        if stat.S_ISLNK(info.st_mode):
            return True
        if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return True
    return False


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    """``os.environ`` without the variables of ``SCRUBBED_GIT_ENV`` (AC-785.5).

    A git child then finds its repository, index and configuration from its
    ``cwd`` alone, so a caller's ``GIT_DIR`` or ``GIT_CONFIG_*`` override cannot
    move a lane operation into another repository or past the hooks.
    """
    return {
        key: value
        for key, value in os.environ.items()
        if key not in SCRUBBED_GIT_ENV and not key.startswith(SCRUBBED_GIT_ENV_PREFIXES)
    }


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Run ``git <args>`` in ``cwd`` with the cleaned environment; never raises on exit."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=_git_env(),
            check=False,
        )
    except OSError as exc:
        raise Refusal("git_unavailable", str(exc)) from None


def _git_text(cwd: Path, *args: str) -> str:
    proc = _git(cwd, *args)
    if proc.returncode != 0:
        raise Refusal(
            "git_failed",
            f"git {' '.join(args)} exited {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}",
        )
    return proc.stdout.decode("utf-8", "surrogateescape")


def _repo_dirs(cwd: Path) -> tuple[Path, Path]:
    """``(toplevel, common_dir)`` of the repository at ``cwd``."""
    top = _git_text(cwd, "rev-parse", "--show-toplevel").strip()
    common = _git_text(
        cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"
    ).strip()
    return Path(top).resolve(), Path(common).resolve()


def _ignorecase(cwd: Path) -> bool:
    proc = _git(cwd, "config", "--bool", "--get", "core.ignorecase")
    if proc.returncode == 1:
        return False
    if proc.returncode != 0:
        raise Refusal("git_failed", proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout.decode("utf-8", "replace").strip() == "true"


def _worktree_entries(cwd: Path) -> list[tuple[str, str | None]]:
    """``(path, branch ref)`` of every worktree git lists, the main worktree first.

    The path is resolved posix; the branch ref is ``refs/heads/...``, or None
    for a detached or bare entry.
    """
    text = _git_text(cwd, "worktree", "list", "--porcelain")
    entries: list[tuple[str, str | None]] = []
    for line in text.splitlines():
        if line.startswith("worktree "):
            entries.append((Path(line[len("worktree ") :]).resolve().as_posix(), None))
        elif line.startswith("branch ") and entries:
            entries[-1] = (entries[-1][0], line[len("branch ") :].strip())
    return entries


def _worktrees(cwd: Path) -> list[str]:
    """Every worktree path git lists, the main worktree first, resolved posix."""
    return [path for path, _ in _worktree_entries(cwd)]


def _head_ref(worktree: Path) -> str | None:
    """The ref HEAD of ``worktree`` points at, or None when HEAD is detached."""
    proc = _git(worktree, "symbolic-ref", "-q", "HEAD")
    if proc.returncode == 1:
        return None
    if proc.returncode != 0:
        raise Refusal(
            "git_failed",
            f"git symbolic-ref HEAD in {worktree} exited {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}",
        )
    return proc.stdout.decode("utf-8", "surrogateescape").strip()


def _lane_branch(worktree: Path, *, is_main: bool) -> str:
    """The lane branch ``lane/<slug>`` that HEAD of ``worktree`` is on (D:170).

    Raises:
        Refusal: ``main_reserved`` for the main tree or a HEAD on ``main``;
            ``head_not_lane`` for a detached HEAD or a branch outside ``lane/``.
    """
    head = _head_ref(worktree)
    if is_main or head == MAIN_REF:
        raise Refusal(
            "main_reserved",
            f"{worktree.as_posix()} is the main tree or has main checked out; a lane "
            "works in its own worktree on lane/<slug> (executor_worktree.py create)",
        )
    if head is None or not head.startswith(LANE_REF_PREFIX):
        shown = "a detached HEAD" if head is None else head
        raise Refusal(
            "head_not_lane",
            f"{worktree.as_posix()} is on {shown}; a lane worktree's HEAD is the "
            "symbolic ref refs/heads/lane/<slug>",
        )
    return head[len("refs/heads/") :]


def junction_files(top: Path) -> tuple[str, ...]:
    """The project's junction files: ``junction_files`` of ``top``'s worktree config."""
    try:
        config = executor_worktree.load_worktree_config(top)
    except executor_worktree.WorktreeConfigError as error:
        raise Refusal("worktree_bad:config", str(error)) from None
    value = config[JUNCTION_KEY]
    return tuple(value) if isinstance(value, list) else ()


def _split_z(raw: bytes) -> list[str]:
    return [tok.decode("utf-8", "surrogateescape") for tok in raw.split(b"\0") if tok]


def _changed_paths(top: Path, base: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Paths changed from ``base`` to the working tree, and the renames.

    Tracked changes come from ``git diff -M --name-status -z <base>``
    (committed, staged and unstaged); untracked files from ``git ls-files
    --others --exclude-standard -z``. A rename yields both paths.
    """
    diff = _git(top, "diff", "-M", "--name-status", "-z", base, "--")
    if diff.returncode != 0:
        raise Refusal("git_failed", diff.stderr.decode("utf-8", "replace").strip())
    found, renames = _name_status_paths(diff.stdout)
    paths = set(found)
    others = _git(top, "ls-files", "--others", "--exclude-standard", "-z")
    if others.returncode != 0:
        raise Refusal("git_failed", others.stderr.decode("utf-8", "replace").strip())
    paths.update(_split_z(others.stdout))
    return sorted(paths), renames


def _commit_change_set(
    cwd: Path, base: str, tip: str
) -> tuple[list[str], list[tuple[str, str]]]:
    """Paths changed from commit ``base`` to commit ``tip``, and the renames.

    ``git diff -M --name-status -z <base> <tip>``; a rename yields both paths.
    """
    diff = _git(cwd, "diff", "-M", "--name-status", "-z", base, tip, "--")
    if diff.returncode != 0:
        raise Refusal("git_failed", diff.stderr.decode("utf-8", "replace").strip())
    return _name_status_paths(diff.stdout)


def _name_status_paths(raw: bytes) -> tuple[list[str], list[tuple[str, str]]]:
    """The paths and renames of ``git diff -M --name-status -z`` output.

    Raises:
        Refusal: ``git_failed`` for a truncated record.
    """
    tokens = _split_z(raw)
    paths: set[str] = set()
    renames: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        status = tokens[i]
        if status[:1] in ("R", "C"):
            if i + 2 >= len(tokens):
                raise Refusal("git_failed", f"truncated diff record {status}")
            old, new = tokens[i + 1], tokens[i + 2]
            paths.add(new)
            if status[0] == "R":
                paths.add(old)
                renames.append((old, new))
            i += 3
        else:
            if i + 1 >= len(tokens):
                raise Refusal("git_failed", f"truncated diff record {status}")
            paths.add(tokens[i + 1])
            i += 2
    return sorted(paths), renames


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _plan_lane(raw: str) -> tuple[str, str]:
    """``(plan_dir, lane)`` for a ``--plan`` value; the lane is its folder name."""
    rel = raw.rstrip("/")
    if not _entry_ok(rel):
        raise Refusal(
            "plan_bad", f"--plan must be a repository-relative folder: {raw!r}"
        )
    lane = rel.rsplit("/", 1)[-1]
    if not _LANE_RE.fullmatch(lane):
        raise Refusal("plan_bad", f"the plan folder {lane!r} is not a lane slug")
    if f"{lane}.json" == GUARD_INVENTORY:
        raise Refusal(
            "plan_bad", f"the lane name {lane!r} is the ref guard inventory's name"
        )
    return rel, lane


def _session(raw: str | None) -> str:
    session = raw if raw else os.environ.get(SESSION_ENV, "")
    if not session:
        raise Refusal("no_session", f"pass --session or set {SESSION_ENV}")
    return session


def _halted(common: Path) -> bool:
    return (_lanes_dir(common) / HALT_FILE).exists()


def _cmd_claim(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    session = _session(args.session)
    top, common = _repo_dirs(Path.cwd())
    if _halted(common):
        print("halt")
        return EXIT_HALT
    plan, lane = _plan_lane(args.plan)
    task_md = top / plan / "task.md"
    if not task_md.is_file():
        raise Refusal("no_task", f"{task_md} does not exist")
    ignorecase = _ignorecase(top)
    owns, _ = _load_ownership(task_md, ignorecase=ignorecase)
    junctions = junction_files(top)
    for entry in owns:
        folded = _normalize(entry, True)
        for junction in junctions:
            target = _normalize(junction, True)
            # An entry that is a junction file, or a folder above one: the lane could
            # create the file there, so whether it exists yet does not count (R1-F3).
            if _covers(folded, target):
                raise Refusal(
                    f"owns_junction:{entry}",
                    f"{junction} is a junction file; only the integrator edits it. "
                    "Write an Integration request in the handoff instead.",
                )
    worktree = Path(args.worktree).resolve()
    if not worktree.is_dir():
        raise Refusal("worktree_bad", f"{worktree} is not a directory")
    shown = worktree.as_posix()
    listed = _worktrees(top)
    if not any(_same_worktree(shown, path) for path in listed):
        raise Refusal("worktree_unknown", f"git worktree list does not name {shown}")
    # AC-785.7: the card records the branch from the worktree's symbolic HEAD.
    branch = _lane_branch(worktree, is_main=_same_worktree(shown, listed[0]))
    card: Card = {
        "lane": lane,
        "generation": secrets.token_hex(8),
        "session": session,
        "state": "active",
        "op": None,
        "worktree": shown,
        "branch": branch,
        "plan": f"{plan}/",
        "owns": owns,
        "claims": [],
        "gates": [],
        "updated": _utc_text(datetime.now(timezone.utc)),
    }
    _write_card(
        common,
        card,
        expect=None,
        wait_s=wait_s,
        poll_s=poll_s,
        ignorecase=ignorecase,
        argv=argv,
    )
    print(f"claimed {lane} generation={card['generation']}")
    return 0


def _current_card(common: Path, lane: str) -> Card:
    path = _card_path(common, lane)
    if not path.is_file():
        raise Refusal("no_card", f"no card at {path}")
    return _load_card(path)


def _check_identity(
    card: Card, session: str, generation: str | None
) -> dict[str, str | None]:
    """The CAS expectation for the caller; refuses when the card is not theirs."""
    expected = generation if generation else card["generation"]
    if card["session"] != session or card["generation"] != expected:
        raise Refusal(
            "card_superseded",
            f"the card of {card['lane']} belongs to session {card['session']}, "
            f"generation {card['generation']}. Stop and tell the human.",
        )
    return {"session": session, "generation": expected, "op": card["op"]}


def _cmd_beat(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    session = _session(args.session)
    _, common = _repo_dirs(Path.cwd())
    if _halted(common):
        print("halt")
        return EXIT_HALT
    _, lane = _plan_lane(args.plan)
    card = _current_card(common, lane)
    expect = _check_identity(card, session, args.generation)
    if card["state"] == "released":
        raise Refusal(
            "card_superseded",
            f"the card of {lane} is released. Stop and tell the human.",
        )
    beat = dict(card, updated=_utc_text(datetime.now(timezone.utc)))
    _write_card(common, beat, expect=expect, wait_s=wait_s, poll_s=poll_s, argv=argv)
    print(f"beat {lane} updated={beat['updated']}")
    return 0


def _all_cards(common: Path) -> list[Card]:
    """Every card of the registry, validated.

    Raises:
        Refusal: a card is unreadable (``card_bad:<key>``); it may name the
            caller's worktree, so the caller stops until the human repairs it.
        OSError: a card file cannot be read.
    """
    cards: list[Card] = []
    for path in _card_files(_lanes_dir(common)):
        try:
            cards.append(_load_card(path))
        except Refusal as exc:
            raise Refusal(
                exc.reason,
                f"{path} is unreadable ({exc.detail}); stop and tell the human",
            ) from None
    return cards


def _card_for_worktree(common: Path, worktree: str) -> Card:
    """The card that names ``worktree``: a reserving one first, else a released one.

    Raises:
        Refusal: ``no_card`` when no card names it, or an unreadable card.
    """
    naming = [c for c in _all_cards(common) if _same_worktree(c["worktree"], worktree)]
    for card in naming:
        if card["state"] in RESERVING_STATES:
            return card
    if naming:
        return naming[0]
    raise Refusal("no_card", f"no lane card names the worktree {worktree}")


def _cmd_release(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    session = _session(args.session)
    top, common = _repo_dirs(Path.cwd())
    if args.plan is not None:
        _, lane = _plan_lane(args.plan)
        card = _current_card(common, lane)
    else:
        # ``--worktree`` (boundary row IP:143): the path may already be removed.
        card = _card_for_worktree(common, Path(args.worktree).resolve().as_posix())
        lane = card["lane"]
    expect = _check_identity(card, session, args.generation)
    if card["state"] == "released":
        print(f"released {lane} (already)")
        return 0
    listed = _worktrees(top)
    linked = listed[1:]
    is_main = bool(listed) and _same_worktree(card["worktree"], listed[0])
    if not is_main and any(_same_worktree(card["worktree"], wt) for wt in linked):
        if args.reset:
            if card["state"] != "landing":
                raise Refusal(
                    "land_open",
                    f"the card of {lane} is {card['state']}; release --reset needs "
                    "a landing card whose land op is closed",
                )
            _reset_lane(card, top, wait_s=wait_s, poll_s=poll_s, argv=argv)
        elif card["state"] == "landing":
            # AC-785.8 (D:217): a landing card is released only after the lane
            # branch is reset to the landed commit or the worktree is removed.
            landed, why = _landed_commit(top, card)
            tip = _branch_tip(top, card["branch"])
            if landed is None or tip != landed:
                raise Refusal(
                    "release_unreset",
                    f"the card of {lane} is landing (op {card['op']}) and git "
                    f"worktree list still names {card['worktree']}; reset "
                    f"{card['branch']} to the landed commit (release --reset) or "
                    f"remove the lane worktree, then release ({why or 'at ' + tip})",
                )
        else:
            raise Refusal(
                "worktree_live",
                f"git worktree list still names {card['worktree']}; remove the lane "
                "worktree first (git worktree remove), then release",
            )
    released = dict(
        card, state="released", op=None, updated=_utc_text(datetime.now(timezone.utc))
    )
    _write_card(
        common, released, expect=expect, wait_s=wait_s, poll_s=poll_s, argv=argv
    )
    print(f"released {lane}")
    return 0


def _closed_land(top: Path, card: Card) -> tuple[LandOp, str]:
    """The closed land op of a ``landing`` card and its landed commit C.

    C is ``ref_new`` of the op's ``published`` entry (the publication intent
    ``{repo, ref, ref_old, ref_new, op, candidate}`` of commit_batch).

    Raises:
        Refusal: ``land_open`` (no op, no journal, or its last entry is not
            ``land:closed:done``), ``card_superseded`` (the journal names another
            lane or generation), ``journal_schema:published.ref_new``, or the
            journal reader's reasons.
    """
    op = card["op"]
    if not isinstance(op, str) or not op:
        raise Refusal("land_open", f"the card of {card['lane']} names no land op")
    land = _land_journal(top, op)
    if land is None:
        raise Refusal("land_open", f"land op {op} has no journal")
    if land.lane != card["lane"] or land.generation != card["generation"]:
        raise Refusal(
            "card_superseded",
            f"the journal of {op} names lane {land.lane} generation "
            f"{land.generation}; the card is {card['lane']} generation "
            f"{card['generation']}",
        )
    last = land.journal[-1] if land.journal else {}
    if (last.get("phase"), last.get("status")) != (LAND_CLOSED, "done"):
        raise Refusal(
            "land_open",
            f"land op {op} is at {land.phase or 'nothing'} "
            f"({last.get('status', '-')}), not {LAND_CLOSED} done",
        )
    landed: object = None
    for entry in land.journal:
        evidence = entry.get("evidence")
        if entry.get("phase") == LAND_PUBLISHED and isinstance(evidence, dict):
            landed = cast(dict[str, Any], evidence).get("ref_new", landed)
    if not isinstance(landed, str) or not _OBJECT_ID_RE.fullmatch(landed):
        raise Refusal(
            "journal_schema:published.ref_new",
            f"the closed land op {op} records no 40-hex published ref_new",
        )
    return land, landed


def _landed_commit(top: Path, card: Card) -> tuple[str | None, str]:
    """``(C, "")`` for a landing card whose op is closed, else ``(None, why)``.

    The release escape of AC-785.8: a lane already reset to C is released.
    A journal that cannot be read keeps the refusal and names the reason.
    """
    try:
        _, landed = _closed_land(top, card)
    except Refusal as exc:
        return None, f"{exc.reason}: {exc.detail}"
    return landed, ""


def _reset_lane(
    card: Card, top: Path, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> None:
    """``release --reset`` (D:217, D:252, AC-785.8): move ``lane/<slug>`` from L0 to C.

    Under the lane worktree lease: the worktree is clean (``lane_dirty``), on the
    card's branch, and the branch is at L0 of the closed op (``lane_moved``).
    Then ``read-tree -m -u L0 C`` in the lane worktree and ``update-ref
    refs/heads/lane/<slug> C L0`` (the old-value check). A failed ``update-ref``
    puts the files back (``read-tree -m -u C L0``) and refuses ``lane_moved``.
    Every refusal before ``read-tree`` changes no ref and no file.

    Raises:
        Refusal: ``land_open``, ``lane_dirty``, ``lane_moved``,
            ``branch_mismatch``, ``card_superseded``, ``git_failed``.
    """
    land, landed = _closed_land(top, card)
    l0 = land.fields().get("L0")
    if not isinstance(l0, str) or not _OBJECT_ID_RE.fullmatch(l0):
        raise Refusal(
            "journal_schema:L0", f"the closed land op {land.op} records no 40-hex L0"
        )
    worktree = Path(card["worktree"])
    branch = card["branch"]
    lease = _worktree_lease(worktree, wait_s=wait_s, poll_s=poll_s, argv=argv)
    try:
        dirty = _dirty_lines(worktree)
        if dirty:
            raise Refusal(
                "lane_dirty",
                f"{card['worktree']} has uncommitted changes ({len(dirty)}): "
                f"{dirty[0]}",
            )
        on = _lane_branch(worktree, is_main=False)
        if on != branch:
            raise Refusal(
                "branch_mismatch",
                f"the card of {card['lane']} names branch {branch}; "
                f"{card['worktree']} is on {on}",
            )
        tip = _branch_tip(worktree, branch)
        if tip != l0:
            raise Refusal(
                "lane_moved",
                f"{branch} is at {tip or 'nothing'}, not L0 {l0} of {land.op}; "
                "release --reset moves only L0 to C",
            )
        read = _git(worktree, "read-tree", "-m", "-u", l0, landed)
        if read.returncode != 0:
            raise Refusal(
                "git_failed",
                f"git read-tree -m -u {l0} {landed} exited {read.returncode}: "
                f"{read.stderr.decode('utf-8', 'replace').strip()}",
            )
        moved = _git(
            worktree,
            "update-ref",
            "-m",
            f"lanes: release --reset {land.op}",
            f"refs/heads/{branch}",
            landed,
            l0,
        )
        if moved.returncode != 0:
            _git(worktree, "read-tree", "-m", "-u", landed, l0)
            raise Refusal(
                "lane_moved",
                f"update-ref {branch} {landed} {l0} failed: "
                f"{moved.stderr.decode('utf-8', 'replace').strip()}",
            )
    finally:
        os_lease.release(lease)
    print(f"reset {branch} {l0} -> {landed}")


def _checked_message_file(raw: str) -> Path:
    """The absolute path of a valid commit message file (AC-785.4 ``message_file``).

    Valid: a regular file of 1 to ``MESSAGE_MAX_BYTES`` bytes of UTF-8 text
    with no NUL byte.

    Raises:
        Refusal: ``message_file`` naming the defect.
    """
    path = Path(raw).resolve()
    try:
        with path.open("rb") as handle:
            data = handle.read(MESSAGE_MAX_BYTES + 1)
    except OSError as exc:
        raise Refusal("message_file", f"cannot read {path}: {exc}") from None
    if not data:
        raise Refusal("message_file", f"{path} is empty")
    if len(data) > MESSAGE_MAX_BYTES:
        raise Refusal(
            "message_file", f"{path} is larger than {MESSAGE_MAX_BYTES} bytes"
        )
    if b"\0" in data:
        raise Refusal("message_file", f"{path} holds a NUL byte")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal("message_file", f"{path} is not UTF-8: {exc}") from None
    return path


def _helper_card(
    common: Path, worktree: str, session: str, generation: str | None
) -> Card:
    """The caller's active card for ``worktree``, read under the registry lock.

    Raises:
        Refusal: ``session_mismatch`` (the card for the worktree has another
            session), ``worktree_mismatch`` (the caller's card names another
            worktree), ``card_superseded`` (released, or another generation),
            ``card_landing``, ``no_card``, or an unreadable card.
    """
    cards = _all_cards(common)
    naming = [c for c in cards if _same_worktree(c["worktree"], worktree)]
    reserving = [c for c in naming if c["state"] in RESERVING_STATES]
    if reserving:
        card = reserving[0]
        if card["session"] != session:
            raise Refusal(
                "session_mismatch",
                f"the card of {card['lane']} for {worktree} belongs to session "
                f"{card['session']}, not {session}. Stop and tell the human.",
            )
    else:
        mine = [
            c
            for c in cards
            if c["session"] == session and c["state"] in RESERVING_STATES
        ]
        if mine:
            raise Refusal(
                "worktree_mismatch",
                f"session {session} holds the card of {mine[0]['lane']} for "
                f"{mine[0]['worktree']}, not {worktree}",
            )
        if naming:
            raise Refusal(
                "card_superseded",
                f"the card of {naming[0]['lane']} for {worktree} is released. "
                "Stop and tell the human.",
            )
        raise Refusal("no_card", f"no lane card names the worktree {worktree}")
    if generation and card["generation"] != generation:
        raise Refusal(
            "card_superseded",
            f"the card of {card['lane']} has generation {card['generation']}, not "
            f"{generation}. Stop and tell the human.",
        )
    if card["state"] == "landing":
        raise Refusal(
            "card_landing",
            f"the card of {card['lane']} is landing (op {card['op']}); the lane "
            "commits again after the land closes and the card is active",
        )
    return card


def _worktree_lease(
    worktree: Path, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> os_lease.Lease:
    """The worktree lease ``<git rev-parse --absolute-git-dir>/{{PROJECT_NAME}}-gate.lock``.

    Raises:
        Refusal: ``lease_busy`` (still held after ``wait_s``) or ``worktree_bad``
            (the lease file cannot be locked).
    """
    git_dir = Path(_git_text(worktree, "rev-parse", "--absolute-git-dir").strip())
    lease_file = git_dir.resolve() / GATE_LEASE_NAME
    try:
        return os_lease.acquire(
            lease_file, wait_s=wait_s, body=_lock_body(argv), poll_s=poll_s
        )
    except os_lease.Busy as busy:
        raise Refusal(
            "lease_busy", _busy_detail(busy, wait_s, "the worktree lease")
        ) from None
    except OSError as exc:
        raise Refusal("worktree_bad", f"cannot lock {lease_file}: {exc}") from None


def _dirty_lines(worktree: Path) -> list[str]:
    """``git status --porcelain`` of ``worktree``, untracked files included.

    ``--no-optional-locks``: the check never rewrites the index, so a refusal
    leaves the lane's index bytes as they were.
    """
    out = _git_text(
        worktree,
        "--no-optional-locks",
        "status",
        "--porcelain",
        "--untracked-files=all",
    )
    return [line for line in out.splitlines() if line.strip()]


def _branch_tip(worktree: Path, branch: str) -> str:
    return _git_text(
        worktree, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}"
    ).strip()


def _commit_failure(worktree: Path, proc: subprocess.CompletedProcess[bytes]) -> str:
    """Why ``git commit`` exited nonzero: ``git``, ``nothing_staged`` or ``hook``.

    ``git`` when git printed a ``fatal:`` line; ``nothing_staged`` when the
    index equals HEAD (``git diff --cached --quiet`` exits 0); else a hook
    (``pre-commit``, ``commit-msg``) refused, since git prints nothing itself then.
    """
    for stream in (proc.stderr, proc.stdout):
        for line in stream.decode("utf-8", "replace").splitlines():
            if line.startswith("fatal:"):
                return "git"
    if _git(worktree, "diff", "--cached", "--quiet").returncode == 0:
        return "nothing_staged"
    return "hook"


def _cmd_commit(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    """The lane commit helper (design §5.1, AC-785.3–AC-785.5).

    Order: HALT, the message file, the worktree lease (held for the check and
    the commit), the card under the registry lock (released before git runs,
    lock order D:165), the symbolic HEAD, then ``git commit -F <file>``.
    """
    session = _session(None)
    worktree = Path(args.worktree).resolve()
    if not worktree.is_dir():
        raise Refusal("worktree_bad", f"{worktree} is not a directory")
    shown = worktree.as_posix()
    top, common = _repo_dirs(worktree)
    if _halted(common):
        print("halt")
        return EXIT_HALT
    message = _checked_message_file(args.message_file)
    lease = _worktree_lease(
        worktree, wait_s=HELPER_LEASE_WAIT_S, poll_s=poll_s, argv=argv
    )
    try:
        with _registry_lock(common, wait_s=wait_s, poll_s=poll_s, argv=argv):
            card = _helper_card(common, shown, session, args.generation)
        listed = _worktrees(top)
        branch = _lane_branch(worktree, is_main=_same_worktree(shown, listed[0]))
        if card["branch"] != branch:
            raise Refusal(
                "branch_mismatch",
                f"the card of {card['lane']} names branch {card['branch']}; "
                f"{shown} is on {branch}",
            )
        before = _branch_tip(worktree, branch)
        proc = _git(worktree, "commit", "-F", str(message))
        after = _branch_tip(worktree, branch)
        if proc.returncode != 0 or after == before:
            kind = _commit_failure(worktree, proc) if proc.returncode != 0 else "git"
            print(f"commit_fail:{kind}")
            for stream in (proc.stdout, proc.stderr):
                text = stream.decode("utf-8", "replace").strip()
                if text:
                    print(text)
            print(f"{branch} stays at {before}")
            return EXIT_REFUSED
    finally:
        os_lease.release(lease)
    print(f"commit_ok:{after}")
    return 0


# ---------------------------------------------------------------------------
# The land journal and the per-op recovery lease (AC-785.11, AC-785.12)
# ---------------------------------------------------------------------------


def _land_journal(top: Path, op: str) -> LandOp | None:
    """The land op ``op`` read through ``tools/commit_batch.py``; None when it has none.

    The land journal lives in the commit_batch op store and only commit_batch's
    journal writer writes it (AC-785.11); this module reads it through
    ``commit_batch.land_journal``. commit_batch is imported here, not at the top,
    so the stage-1 commands stay standard library only.

    Raises:
        Refusal: the commit_batch reader's reason (``containment``,
            ``op_ambiguous``, ``journal_schema:<key>``, ``op_file``, ``disabled``).
    """
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only

    try:
        return commit_batch.land_journal(top, op)
    except _batch_errors() as exc:
        raise _as_refusal(exc, op) from None


def _batch_path() -> None:
    """Put the repository root on ``sys.path`` so ``tools.commit_batch`` imports.

    The land verbs import commit_batch inside their functions, so the stage-1
    commands stay standard library only.
    """
    root = str(Path(__file__).resolve().parent.parent)
    if not __package__ and root not in sys.path:
        sys.path.insert(0, root)


def _batch_errors() -> tuple[type[Exception], ...]:
    """The commit_batch exceptions a land verb turns into a lanes ``Refusal``."""
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only

    return (commit_batch.rp.Refusal, commit_batch.Stopped)


def _as_refusal(exc: Exception, op: str) -> Refusal:
    """A commit_batch refusal (its reason) or stop (``op_file``) as a lanes ``Refusal``."""
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only

    if isinstance(exc, commit_batch.rp.Refusal):
        return Refusal(exc.reason, exc.detail)
    return Refusal(str(exc), f"the op file of {op} cannot be read; it is left as it is")


def _op_lease_path(common: Path, op: str) -> Path:
    return _lanes_dir(common) / OPS_DIR / f"{op}{OP_LEASE_SUFFIX}"


def _op_lease(
    common: Path, op: str, *, poll_s: float, argv: Sequence[str]
) -> os_lease.Lease | None:
    """The per-op lease ``<common>/lanes/ops/<op>.lease`` in one attempt.

    Returns None when another process holds it: ``op_busy`` and the holder are
    printed, and the caller exits ``EXIT_BUSY`` with nothing written. The lease
    file stays on disk after release (D:425).

    Raises:
        Refusal: ``common_dir_unwritable`` (the folder cannot be made or locked).
    """
    lease_file = _op_lease_path(common, op)
    try:
        lease_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Refusal(
            "common_dir_unwritable", f"cannot create {lease_file.parent}: {exc}"
        ) from None
    try:
        return os_lease.acquire(
            lease_file,
            wait_s=OP_LEASE_WAIT_S,
            body=_lock_body(argv),
            poll_s=poll_s,
        )
    except os_lease.Busy as busy:
        print("op_busy")
        print(_busy_detail(busy, OP_LEASE_WAIT_S, f"the op lease of {op}"))
        return None
    except OSError as exc:
        raise Refusal(
            "common_dir_unwritable", f"cannot lock {lease_file}: {exc}"
        ) from None


def _recovery_card(common: Path, land: LandOp) -> Card:
    """The card the land journal names, read again under the registry lock.

    Raises:
        Refusal: ``journal_schema:identity.lane`` (the journal names no lane
            slug), ``card_superseded`` (no card, or a card with another
            generation or ``op``), or the card reader's ``card_bad:<key>``.
    """
    if not _LANE_RE.fullmatch(land.lane):
        raise Refusal(
            "journal_schema:identity.lane",
            f"the journal of {land.op} names lane {land.lane!r}",
        )
    path = _card_path(common, land.lane)
    if not path.is_file():
        raise Refusal(
            "card_superseded",
            f"the journal of {land.op} names lane {land.lane}, which has no card",
        )
    card = _load_card(path)
    if card["generation"] != land.generation or card["op"] not in (None, land.op):
        raise Refusal(
            "card_superseded",
            f"the card of {land.lane} is generation {card['generation']} with op "
            f"{card['op']}; the journal of {land.op} names generation "
            f"{land.generation}. Recovery never touches another generation or op.",
        )
    return card


def _cmd_land_recover(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    """Re-run land op ``--op`` (design §5.5 "Recovery", §10b N-6, AC-785.12).

    Order: a first read of the journal (it also checks the op id), the per-op
    lease ``<common>/lanes/ops/<op>.lease`` in one attempt (held by another
    process: ``op_busy``, exit 3, nothing written), then, under that lease, the
    journal again (``op_unknown``, ``journal_moved``) and the card under the
    registry lock (``card_superseded``). The op lease is taken before any lock
    of the design order (D:166), and the registry lock is never held while a
    lease is awaited. A journal phase that no recovery rule covers refuses
    ``recovery_unclear:<phase>`` and changes nothing: uncertainty refuses
    rather than guesses. The rows of D:258-266 map to: an exited holder (the OS
    released it, nothing to do); step 1 or 2 up to ``land:integrate:started``
    (``_recover_abandon``: the candidate is removed and the card goes back to
    ``active``, idempotently); ``RECOVER_READY_POINTS`` (after step 3) re-runs
    steps 4-5 from the kept objects (``_recover_ready``, EA-25) and ends
    ``land_ready:<op>:<tree>``; step 6 (``_recover_wait``) changes nothing;
    ``published:started`` publishes again or finishes through
    ``commit_batch.land_publish_again`` and then runs steps 8-9, never step 1;
    ``published:done``, any ``land:sync`` entry and ``land:closed:started`` re-run
    steps 8-9 (``_recover_close``, EA-60). A closed op prints ``land_closed:<op>``,
    exits 0 and changes nothing (AC-785.22).
    """
    op = str(args.op)
    top, common = _repo_dirs(Path.cwd())
    before = _land_journal(top, op)
    lease = _op_lease(common, op, poll_s=poll_s, argv=argv)
    if lease is None:
        return EXIT_BUSY
    try:
        land = _land_journal(top, op)
        if land is None:
            raise Refusal(
                "op_unknown",
                f"no land journal carries op {op} in {common / 'run-parameters'}",
            )
        if before is None or before.raw != land.raw:
            raise Refusal(
                "journal_moved",
                f"the journal of {op} changed while the op lease was taken; "
                "run land recover again",
            )
        status = land.journal[-1]["status"] if land.journal else None
        if (land.phase, status) == (LAND_CLOSED, "done"):
            print(f"land_closed:{op}")
            return 0
        point = f"{land.phase}:{status}"
        if point in RECOVER_CLOSE_POINTS or land.phase == LAND_SYNC:
            # After publication the close never writes the card, so a card of another
            # generation or op does not stop it (D:266); it is left as it is.
            return _recover_close(
                top, common, land, wait_s=wait_s, poll_s=poll_s, argv=argv
            )
        with _registry_lock(common, wait_s=wait_s, poll_s=poll_s, argv=argv):
            card = _recovery_card(common, land)
        if land.phase in RECOVER_ABANDON_PHASES or point == RECOVER_ABANDON_POINT:
            return _recover_abandon(
                top, common, land, card, wait_s=wait_s, poll_s=poll_s, argv=argv
            )
        if point in RECOVER_READY_POINTS:
            return _recover_ready(top, land, card)
        if point in RECOVER_WAIT_POINTS:
            return _recover_wait(top, land, card)
        if point == RECOVER_PUBLISH_POINT:
            _landing_card(card, land)
            return _recover_close(
                top, common, land, wait_s=wait_s, poll_s=poll_s, argv=argv, again=True
            )
        raise Refusal(
            f"recovery_unclear:{land.phase}",
            f"no recovery rule covers phase {land.phase} of op {op}; the journal "
            "and the card are unchanged. Ask the human.",
        )
    finally:
        os_lease.release(lease)


def _main_repo(top: Path) -> RpRepo:
    """The run-parameters handle of the main repository, whatever worktree holds ``top``.

    Raises:
        Refusal: run_parameters' reason (``disabled``) or ``git_failed``.
    """
    _batch_path()
    from tools import run_parameters as rp  # noqa: PLC0415 - the land verbs only

    try:
        opened = rp._open_repo(top)
        return opened if opened.main == opened.top else rp._open_repo(opened.main)
    except _batch_errors() as exc:
        raise _as_refusal(exc, "the land") from None
    except rp.GitError as exc:
        raise Refusal("git_failed", str(exc)) from None


def _recover_close(
    top: Path,
    common: Path,
    land: LandOp,
    *,
    wait_s: float,
    poll_s: float,
    argv: Sequence[str],
    again: bool = False,
) -> int:
    """Recovery of steps 7-9 (AC-785.21, AC-785.22, AC-785.23) from the publication on.

    ``published:done`` or a ``land:sync`` entry other than done re-runs the sync
    (``commit_batch.land_sync``) and then the close; ``land:sync:done`` and
    ``land:closed:started`` run the close only. With ``again`` the journal is at
    ``published:started``: ``commit_batch.land_publish_again`` publishes again or
    finishes (the reflog decides) and the sync and the close follow. HALT is checked
    before and after the main-tree lease is taken, and the lease is released on
    every path. It ends ``land_closed:<op>``.

    Raises:
        Refusal: ``sync_unexplained:<path>``, ``sync_incomplete:<path>`` or a
            ``_close`` reason; the sync refusal stays journaled and blocks every
            other publication (``sync_pending:<op>``).
    """
    if _halted(common):
        print("halt")
        return EXIT_HALT
    main_top = _main_tree(top)
    lease = _worktree_lease(main_top, wait_s=wait_s, poll_s=poll_s, argv=argv)
    try:
        if _halted(common):
            print("halt")
            return EXIT_HALT
        status = land.journal[-1]["status"] if land.journal else None
        sync = land.phase == LAND_PUBLISHED or (
            land.phase == LAND_SYNC and status != "done"
        )
        handle = _main_repo(top)
        if again:
            _batch_path()
            from tools import commit_batch  # noqa: PLC0415 - the land verbs only

            try:
                commit = commit_batch.land_publish_again(handle, land, act=PUBLISH_ACT)
            except _batch_errors() as exc:
                raise _as_refusal(exc, land.op) from None
            except commit_batch.rp.GitError as exc:
                raise Refusal("git_failed", str(exc)) from None
            print(f"land_published:{land.op}:{commit}")
            sync = True
        _sync_and_close(top, land, handle, sync=sync)
    finally:
        os_lease.release(lease)
    print(f"land_closed:{land.op}")
    return 0


def _recover_abandon(
    top: Path,
    common: Path,
    land: LandOp,
    card: Card,
    *,
    wait_s: float,
    poll_s: float,
    argv: Sequence[str],
) -> int:
    """Recovery of "Step 1 done, before step 4" (D:260, AC-785.23, EA-53).

    The journal is at step 1, step 2 or the start of step 3: nothing in the lane
    changed. The land candidate is removed and a card ``landing`` with this op goes
    back to ``active`` with no op. It is idempotent: with the candidate gone and the
    card already ``active`` (also a card that never got the op, "Step 1, journal
    written, card still active", D:259) nothing is written. The journal keeps its
    last entry; the abandoned op is not resumed, a new land starts at step 1.

    Raises:
        Refusal: ``candidate_remove``, ``git_failed`` or a card writer's reason.
    """
    _remove_candidate(top, _land_candidate_path(land))
    if card["state"] == "landing" and card["op"] == land.op:
        _set_card(
            common,
            card,
            state="active",
            op=None,
            expect_op=land.op,
            wait_s=wait_s,
            poll_s=poll_s,
            argv=argv,
        )
    print(f"land_abandoned:{land.op}")
    return 0


def _recover_wait(top: Path, land: LandOp, card: Card) -> int:
    """Recovery of step 6 (D:262, AC-785.23): nothing to recover, no lock, no write.

    The land waits for authority; the ready line is printed again so a verdict can
    bind to it. The kept objects and the card stay as they are.

    Raises:
        Refusal: ``card_superseded``, ``git_failed`` or ``recovery_unclear:<phase>``.
    """
    _landing_card(card, land)
    objects = _journal_objects(land)
    tree = _git_text(top, "rev-parse", "--verify", f"{objects['T']}^{{tree}}").strip()
    print(f"land_ready:{land.op}:{tree}")
    return 0


# ---------------------------------------------------------------------------
# land prepare: step 1 freeze and step 2 rebase (design §5.5, AC-785.13/.14)
# ---------------------------------------------------------------------------


def _object_id(raw: str) -> str:
    """The argparse type of ``--l0``: a full 40-hex commit id (exit 2 otherwise)."""
    if not _OBJECT_ID_RE.fullmatch(raw):
        raise argparse.ArgumentTypeError(f"{raw!r} is not a 40-hex commit id")
    return raw


def _open_land(top: Path, op: str, card: Card) -> LandOp:
    """The new land op ``op`` of ``card``; commit_batch writes nothing until its first entry.

    The op lives at ``<store>/ops/<lane>/interactive/<op>/op.json`` (the lane slug
    is the plan slug, AC-785.11).

    Raises:
        Refusal: the commit_batch reason (``containment``, ``op_mismatch``,
            ``op_ambiguous``, ``journal_schema:<key>``, ``disabled``, ``op_file``).
    """
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only

    try:
        repo = commit_batch.rp._open_repo(top)
        return commit_batch.open_land_op(
            repo,
            op=op,
            plan=card["lane"],
            lane=card["lane"],
            generation=card["generation"],
            session=card["session"],
        )
    except _batch_errors() as exc:
        raise _as_refusal(exc, op) from None


def _journal(
    land: LandOp,
    phase: str,
    *,
    done: bool,
    evidence: Mapping[str, Any] | None = None,
) -> None:
    """One entry ``<phase>:started`` or ``<phase>:done`` through commit_batch's writer.

    commit_batch fires the ``<phase>:<status>`` crash seam after the entry.

    Raises:
        Refusal: the commit_batch reason (``journal_schema:<key>``, ``op_file``).
    """
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only

    try:
        if done:
            commit_batch.land_finish(land, phase, evidence)
        else:
            commit_batch.land_start(land, phase, evidence)
    except _batch_errors() as exc:
        raise _as_refusal(exc, land.op) from None


def _store_message(land: LandOp, message: str) -> None:
    """The commit message of the land, kept beside its journal for step 7.

    Raises:
        Refusal: commit_batch's reason (``message``, ``op_file``).
    """
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only

    try:
        commit_batch.store_land_message(land, message)
    except _batch_errors() as exc:
        raise _as_refusal(exc, land.op) from None


def _land_candidate_path(land: LandOp) -> Path:
    """``<run-parameters.candidateRoot>/land-<op>``: the disposable land candidate.

    Raises:
        Refusal: ``candidate_root`` (the configured root is not a safe absolute path).
    """
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only

    try:
        root = commit_batch._candidate_root(land.repo)
    except _batch_errors() as exc:
        raise _as_refusal(exc, land.op) from None
    return root / f"{LAND_CANDIDATE_PREFIX}{land.op}"


def _listed(top: Path, path: Path) -> bool:
    """True when ``git worktree list`` names ``path``."""
    shown = path.resolve().as_posix()
    return any(_same_worktree(shown, wt) for wt in _worktrees(top))


def _add_candidate(top: Path, path: Path, land: LandOp, commit: str) -> None:
    """A detached worktree at ``commit`` with the op's manifest in its git dir.

    The manifest has commit_batch's shape (``candidate-worktree/1``) with kind
    ``land``, so a reader can tell whose candidate a folder is.

    Raises:
        Refusal: ``candidate_root`` (the root cannot be made) or ``git_failed``.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Refusal("candidate_root", f"cannot create {path.parent}: {exc}") from None
    _git_text(top, *GIT_LONGPATHS, "worktree", "prune")
    _git_text(
        top, *GIT_LONGPATHS, "worktree", "add", "--detach", path.as_posix(), commit
    )
    git_dir = Path(_git_text(path, "rev-parse", "--absolute-git-dir").strip())
    manifest = {
        "schema": LAND_MANIFEST_SCHEMA,
        "kind": "land",
        "op": land.op,
        "run_id": str(land.identity["run_id"]),
        "plan": str(land.identity["plan"]),
    }
    _replace_atomically(
        git_dir / LAND_MANIFEST_NAME,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _remove_candidate(top: Path, path: Path) -> None:
    """Remove the land candidate (``worktree remove --force``, then ``prune``); idempotent.

    The candidate's directory links (the lane's dependency trees, R1-F6) are
    dropped as links first, so neither git nor ``rmtree`` deletes through them.

    Raises:
        Refusal: ``candidate_remove`` (the folder stays on disk) or ``git_failed``.
    """
    if path.is_dir():
        try:
            executor_worktree._drop_tree_links(path)
        except OSError as exc:
            raise Refusal(
                "candidate_remove",
                f"cannot drop a dependency link in the land candidate {path}: {exc}",
            ) from None
    removed = ""
    if _listed(top, path):
        proc = _git(
            top, *GIT_LONGPATHS, "worktree", "remove", "--force", path.as_posix()
        )
        removed = proc.stderr.decode("utf-8", "replace").strip()
    if path.exists():
        try:
            shutil.rmtree(path)
        except OSError as exc:
            raise Refusal(
                "candidate_remove",
                f"cannot remove the land candidate {path}: {exc} {removed}".strip(),
            ) from None
    _git_text(top, *GIT_LONGPATHS, "worktree", "prune")


def _set_card(
    common: Path,
    card: Card,
    *,
    state: str,
    op: str | None,
    expect_op: str | None,
    wait_s: float,
    poll_s: float,
    argv: Sequence[str],
) -> Card:
    """Write ``card`` with ``state`` and ``op`` (CAS on session, generation, ``expect_op``).

    Raises:
        Refusal: ``card_superseded`` and the other ``_write_card`` refusals.
    """
    new = dict(card, state=state, op=op, updated=_utc_text(datetime.now(timezone.utc)))
    _write_card(
        common,
        new,
        expect={
            "session": card["session"],
            "generation": card["generation"],
            "op": expect_op,
        },
        wait_s=wait_s,
        poll_s=poll_s,
        argv=argv,
    )
    return new


def _owns_violation(
    candidate: Path,
    base: str,
    tip: str,
    *,
    owns: Sequence[str],
    mnt: Sequence[str],
    ignorecase: bool,
) -> Refusal | None:
    """The first path of the change set ``base``..``tip`` outside ``owns``, as a refusal.

    The stage-1 rules (``lanes.py check``, §10b N-4): a rename counts both
    paths, ``must_not_touch`` wins over ``owns``, and a path through a link
    or reparse point of the candidate is ``link_path``.
    """
    paths, _ = _commit_change_set(candidate, base, tip)
    owned = [_normalize(entry, ignorecase) for entry in owns]
    avoided = [_normalize(entry, ignorecase) for entry in mnt]
    for path in paths:
        norm = _normalize(path, ignorecase)
        if _through_link(candidate, path):
            return Refusal(
                f"link_path:{path}",
                f"{path} of {base}..{tip} passes a link or reparse point",
            )
        if any(_covers(entry, norm) for entry in avoided) or not any(
            _covers(entry, norm) for entry in owned
        ):
            return Refusal(
                f"owns_violation:{path}",
                f"{base}..{tip} changes {path}, which the lane does not own "
                f"(owns {', '.join(owns) or '-'}; must_not_touch "
                f"{', '.join(mnt) or '-'})",
            )
    return None


def _freeze(
    args: argparse.Namespace,
    worktree: Path,
    top: Path,
    common: Path,
    op: str,
    *,
    message: str,
    wait_s: float,
    poll_s: float,
    argv: Sequence[str],
) -> tuple[LandOp, Card, str, list[str], list[str]]:
    """Step 1 (D:244, AC-785.13): the checks, the journal FIRST, then the card ``landing``.

    Order: the lane worktree lease; the card under the registry lock (``active``,
    this session); the symbolic HEAD; a clean worktree (``lane_dirty``); the
    tip == ``--l0`` (``lane_moved``); the candidate path is free; the commit
    message stored beside the journal (``_store_message``, the message of C
    at step 7, EA-60); then the
    ``land:freeze`` entry ``{op, lane, generation, session, P, L0}``, the card
    ``landing`` + ``op`` (CAS, op None) and ``land:freeze:done``. The lease is
    released on every path. A refusal before the entry writes nothing.

    Returns:
        ``(land op, landing card, P, owns, must_not_touch)``.
    """
    session = _session(None)
    shown = worktree.as_posix()
    l0 = str(args.l0)
    lease = _worktree_lease(worktree, wait_s=wait_s, poll_s=poll_s, argv=argv)
    try:
        with _registry_lock(common, wait_s=wait_s, poll_s=poll_s, argv=argv):
            card = _helper_card(common, shown, session, None)
        listed = _worktrees(top)
        branch = _lane_branch(worktree, is_main=_same_worktree(shown, listed[0]))
        if card["branch"] != branch:
            raise Refusal(
                "branch_mismatch",
                f"the card of {card['lane']} names branch {card['branch']}; "
                f"{shown} is on {branch}",
            )
        dirty = _dirty_lines(worktree)
        if dirty:
            raise Refusal(
                "lane_dirty",
                f"{shown} has uncommitted changes ({len(dirty)}): {dirty[0]}",
            )
        tip = _branch_tip(worktree, branch)
        if tip != l0:
            raise Refusal(
                "lane_moved", f"{branch} is at {tip or 'nothing'}, not --l0 {l0}"
            )
        parent = _git_text(
            top, "rev-parse", "--verify", "--quiet", f"{MAIN_REF}^{{commit}}"
        ).strip()
        # The owns of the reservation (the card) and the must_not_touch of the
        # plan's task.md at L0 (the worktree is clean at L0 here).
        _, mnt = _load_ownership(
            top / card["plan"] / "task.md", ignorecase=_ignorecase(top)
        )
        owns = [str(entry) for entry in card["owns"]]
        land = _open_land(top, op, card)
        candidate = _land_candidate_path(land)
        if candidate.exists() or _listed(top, candidate):
            raise Refusal(
                "candidate_exists",
                f"the land candidate {candidate.as_posix()} already exists; "
                "remove it (git worktree remove) before a new land",
            )
        _store_message(land, message)
        _journal(
            land,
            LAND_FREEZE,
            done=False,
            evidence={
                "op": op,
                "lane": card["lane"],
                "generation": card["generation"],
                "session": card["session"],
                "P": parent,
                "L0": l0,
            },
        )
        landing = _set_card(
            common,
            card,
            state="landing",
            op=op,
            expect_op=None,
            wait_s=wait_s,
            poll_s=poll_s,
            argv=argv,
        )
        _journal(land, LAND_FREEZE, done=True)
    finally:
        os_lease.release(lease)
    return land, landing, parent, owns, mnt


def _rebase(
    land: LandOp,
    card: Card,
    top: Path,
    common: Path,
    parent: str,
    l0: str,
    *,
    owns: Sequence[str],
    mnt: Sequence[str],
    wait_s: float,
    poll_s: float,
    argv: Sequence[str],
) -> str:
    """Step 2 (D:245, AC-785.14): rebase L0 onto P in a disposable detached candidate.

    ``git -c rebase.updateRefs=false rebase --onto P <merge-base(P, L0)>`` runs
    in ``<candidate root>/land-<op>``, so the lane worktree and ``lane/<slug>``
    never move. A conflict journals ``land:conflict``; a conflict, an
    ``owns_violation`` or any other failure removes the candidate and sets the
    card back to ``active`` (recovery row "Step 1 done, before step 4", D:259).

    Returns:
        L1, the rebased commit (journaled as ``land:rebase:done``).
    """
    candidate = _land_candidate_path(land)
    _journal(land, LAND_REBASE, done=False)
    conflicted: list[str] = []
    try:
        _add_candidate(top, candidate, land, l0)
        base = _git_text(candidate, "merge-base", parent, l0).strip()
        proc = _git(
            candidate,
            *GIT_LONGPATHS,
            "-c",
            "rebase.updateRefs=false",
            "rebase",
            "--onto",
            parent,
            base,
        )
        if proc.returncode != 0:
            unmerged = _git(candidate, "diff", "--name-only", "--diff-filter=U", "-z")
            if unmerged.returncode == 0:
                conflicted = sorted(_split_z(unmerged.stdout))
            _git(candidate, "rebase", "--abort")
            if conflicted:
                _journal(land, LAND_CONFLICT, done=False)
                raise Refusal(
                    f"land_conflict:{','.join(conflicted)}",
                    f"rebasing {l0} onto {parent} conflicts; the lane stays at "
                    f"{l0} and the card is active again. Bring main into the "
                    "lane, commit, and land again.",
                )
            output = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip()
            raise Refusal(
                "git_failed", f"git rebase exited {proc.returncode}: {output}"
            )
        rebased = _git_text(candidate, "rev-parse", "--verify", "HEAD").strip()
        _journal(land, LAND_REBASE, done=True, evidence={"L1": rebased})
        violation = _owns_violation(
            candidate,
            parent,
            rebased,
            owns=owns,
            mnt=mnt,
            ignorecase=_ignorecase(top),
        )
        if violation is not None:
            raise violation
    except Refusal:
        _remove_candidate(top, candidate)
        _set_card(
            common,
            card,
            state="active",
            op=None,
            expect_op=land.op,
            wait_s=wait_s,
            poll_s=poll_s,
            argv=argv,
        )
        if conflicted:
            _journal(land, LAND_CONFLICT, done=True)
        raise
    return rebased


# ---------------------------------------------------------------------------
# land prepare: step 3 integrate (design §5.4, AC-785.15)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Request:
    """One row of the lane handoff's ``## Integration requests`` table, parsed."""

    rid: str
    form: str
    fields: dict[str, str]


def _safe_repo_path(rel: str) -> bool:
    """True for a repository-relative POSIX path: no drive, root, ``..``, ``.`` or backslash."""
    if not rel or "\\" in rel or "\0" in rel or _DRIVE_RE.match(rel):
        return False
    if PurePosixPath(rel).is_absolute():
        return False
    return all(part not in ("", ".", "..") for part in rel.split("/"))


def _repo_file(root: Path, rel: str) -> Path | None:
    """``root/rel`` when ``rel`` is a safe repository path to a file, not through a link."""
    if not _safe_repo_path(rel) or _through_link(root, rel):
        return None
    path = root / rel
    return path if path.is_file() else None


def _request_rows(text: str) -> list[tuple[str, str]]:
    """``(Id cell, Request cell)`` of each body row of the ``## Integration requests`` table.

    The section runs from its heading to the next ``#`` or ``##`` heading. The
    first table row is the header and a ``|---|`` row is the separator; both
    are skipped. The Id cell is the text between the first two pipes with its
    backticks stripped; the Request cell runs from the first to the last
    backtick after the Id cell, so a metrics row keeps its pipes; a GFM-escaped
    ``\\|`` in that cell reads as ``|``. A row with no code span gives an empty
    Request (``request_unknown``).
    """
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == REQUESTS_HEADING), None
    )
    if start is None:
        return []
    rows: list[tuple[str, str]] = []
    header_seen = False
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith(("# ", "## ")):
            break
        if not stripped.startswith("|") or _SEPARATOR_RE.fullmatch(stripped):
            continue
        if not header_seen:
            header_seen = True
            continue
        cell, _, tail = stripped[1:].partition("|")
        first, last = tail.find("`"), tail.rfind("`")
        request = tail[first + 1 : last] if 0 <= first < last else ""
        rows.append((cell.strip().strip("`").strip(), request.replace("\\|", "|")))
    return rows


def _parse_requests(
    rows: Sequence[tuple[str, str]], *, lane: str, generation: str
) -> list[_Request]:
    """The rows as requests: the id shape and uniqueness, the form, then its syntax.

    Raises:
        Refusal: ``request_id:<row>`` (not ``<lane>/<generation>/<n>``, or a
            repeated id), ``request_unknown:<id>`` (not a form of
            ``REQUEST_FORMS``; the land stops), ``request_field:<id>:syntax``
            (a known form that does not match its syntax).
    """
    id_re = re.compile(rf"{re.escape(lane)}/{re.escape(generation)}/\d+")
    seen: set[str] = set()
    requests: list[_Request] = []
    for rid, request in rows:
        if not id_re.fullmatch(rid) or rid in seen:
            raise Refusal(
                f"request_id:{rid}",
                f"each request id is {lane}/{generation}/<n> and appears once; "
                f"the handoff row {rid!r} is not",
            )
        seen.add(rid)
        form = request.split(" ", 1)[0]
        if form not in REQUEST_FORMS:
            raise Refusal(
                f"request_unknown:{rid}",
                f"{request!r} is not a form of the integration request grammar "
                f"({', '.join(REQUEST_FORMS)}); the land stops",
            )
        match = _REQUEST_SYNTAX[form].fullmatch(request)
        if match is None:
            raise Refusal(
                f"request_field:{rid}:syntax",
                f"{request!r} does not match {REQUEST_FORMS[form]}",
            )
        fields = {key: value for key, value in match.groupdict().items() if value}
        requests.append(_Request(rid=rid, form=form, fields=fields))
    return requests


def _yaml_file(path: Path) -> object:
    """``yaml.safe_load`` of a UTF-8 file.

    Raises:
        Refusal: ``junction_unreadable:<file>`` (unreadable, not UTF-8, or not YAML).
    """
    import yaml  # noqa: PLC0415 - the land verbs only

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise Refusal(
            f"junction_unreadable:{path.name}", f"cannot read {path}: {exc}"
        ) from None


def _meu_row_keys(candidate: Path) -> set[str]:
    """The ``row_key`` of every MEU in the candidate's ``meu-status.yaml`` (empty when absent)."""
    path = candidate / MEU_STATUS_FILE
    if not path.is_file():
        return set()
    data = _yaml_file(path)
    meus = cast(dict[str, Any], data).get("meus") if isinstance(data, dict) else None
    if not isinstance(meus, list):
        return set()
    return {
        str(cast(dict[str, Any], item)["row_key"])
        for item in cast(list[object], meus)
        if isinstance(item, dict) and "row_key" in item
    }


def _ki_states(candidate: Path) -> dict[str, str]:
    """Top-level issue id -> status of the candidate's ``known-issues.yaml``.

    Only the top-level entries count (a nested ``- id:`` is not an issue).
    """
    path = candidate / KI_YAML_FILE
    if not path.is_file():
        return {}
    data = _yaml_file(path)
    if isinstance(data, dict):
        data = cast(dict[str, Any], data).get("issues")
    if not isinstance(data, list):
        return {}
    states: dict[str, str] = {}
    for item in cast(list[object], data):
        if isinstance(item, dict) and "id" in item:
            entry = cast(dict[str, Any], item)
            states[str(entry["id"])] = str(entry.get("status", ""))
    return states


def _cell_count(row: str) -> int:
    """The cells of one Markdown table row (an escaped ``\\|`` is not a separator)."""
    return len(_CELL_SPLIT_RE.split(row.strip())) - 2


def _metrics_anchor(lines: Sequence[str]) -> tuple[int, int] | None:
    """``(index of the last table line, column count of the last table's header)``.

    A metrics row goes after the last line that starts with ``|``; its column
    count must be the one of the header above the last ``|---|`` separator.
    """
    rows = [i for i, line in enumerate(lines) if line.lstrip().startswith("|")]
    separators = [i for i in rows if _SEPARATOR_RE.fullmatch(lines[i].strip())]
    if not rows or not separators or separators[-1] == 0:
        return None
    header = lines[separators[-1] - 1]
    if not header.lstrip().startswith("|"):
        return None
    return rows[-1], _cell_count(header)


def _checked_payload(rid: str, path: Path) -> dict[str, str]:
    """The fields of a ``ki-file`` payload, checked against the grammar's key set.

    Raises:
        Refusal: ``request_payload:<id>:<key>`` (an unknown key or a bad value),
            ``request_payload:<id>:missing:<key>`` (a required key is absent),
            ``request_payload:<id>:yaml`` (not a YAML mapping).
    """
    try:
        data = _yaml_file(path)
    except Refusal:
        raise Refusal(
            f"request_payload:{rid}:yaml", f"cannot read the payload {path}"
        ) from None
    if not isinstance(data, dict):
        raise Refusal(f"request_payload:{rid}:yaml", f"{path} is not a YAML mapping")
    raw = cast(dict[object, object], data)
    allowed = (*KI_REQUIRED_KEYS, *KI_OPTIONAL_KEYS)
    for key in sorted(str(item) for item in raw):
        if key not in allowed:
            raise Refusal(
                f"request_payload:{rid}:{key}",
                f"{path} has the unknown key {key} (keys: {', '.join(allowed)})",
            )
    for key in KI_REQUIRED_KEYS:
        if key not in raw:
            raise Refusal(
                f"request_payload:{rid}:missing:{key}", f"{path} has no {key}"
            )
    payload: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key)
        text = value.isoformat() if isinstance(value, date) else value
        if not isinstance(text, str) or not text.strip():
            raise Refusal(
                f"request_payload:{rid}:{name}",
                f"{path}: {name} is not a non-empty string",
            )
        payload[name] = text
    checks = (
        ("severity", payload["severity"] in KI_SEVERITIES),
        ("component", payload["component"] in KI_COMPONENTS),
        ("status", payload.get("status", "open") in KI_STATUSES),
        ("discovered", _valid_date(payload.get("discovered"))),
    )
    for name, ok in checks:
        if not ok:
            raise Refusal(
                f"request_payload:{rid}:{name}",
                f"{path}: {name} {payload.get(name)!r} is outside the grammar",
            )
    return payload


def _valid_date(text: str | None) -> bool:
    """True for None (the key is optional) or a real ``YYYY-MM-DD`` date."""
    if text is None:
        return True
    if not _DATE_RE.fullmatch(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _check_request(
    candidate: Path, request: _Request, plan: str
) -> dict[str, str] | None:
    """Check one request against the grammar's field constraints at the candidate's state.

    Returns:
        The checked payload of a ``ki-file`` request, else None.

    Raises:
        Refusal: ``request_field:<id>:<field>`` and, for ``ki-file``,
            ``request_payload:<id>:...``.
    """
    rid, fields = request.rid, request.fields

    def field(name: str, detail: str) -> Refusal:
        return Refusal(f"request_field:{rid}:{name}", detail)

    if request.form == "meu-status":
        status = fields["status"]
        if status not in MEU_STATUSES:
            raise field(
                "status",
                f"{status!r} is not one of {', '.join(sorted(MEU_STATUSES))}",
            )
        if status == "closed" and not fields.get("reason", "").strip():
            raise field("reason", "status closed needs reason=<text>")
        if fields["meu"] not in _meu_row_keys(candidate):
            raise field("meu", f"{fields['meu']} is not a row_key of {MEU_STATUS_FILE}")
        return None
    if request.form == "grouping-cursor":
        path = _repo_file(candidate, fields["file"])
        if path is None:
            raise field("file", f"{fields['file']} is not a file of the repository")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise field("file", f"cannot read {fields['file']}: {exc}") from None
        session = re.escape(fields["session"])
        if not re.search(rf"^#+ Session {session}(?:\s|$)", text, re.MULTILINE):
            raise field(
                "session", f"{fields['file']} names no session {fields['session']}"
            )
        if _CURSOR_RE.search(text) is None:
            raise field("cursor", f"{fields['file']} has no 'Global cursor: **<id>**'")
        return None
    if request.form == "ki-file":
        ki = fields["ki"]
        if not _KI_ID_RE.fullmatch(ki):
            raise field("ki", f"{ki!r} is not a known-issue id")
        expected = f"{plan}/artifacts/ki/{ki}.yaml"
        path = _repo_file(candidate, expected)
        if fields["payload"] != expected or path is None:
            raise field(
                "payload", f"the payload of {ki} is the lane file {expected} at L1"
            )
        return _checked_payload(rid, path)
    if request.form == "ki-close":
        if not _KI_ID_RE.fullmatch(fields["ki"]):
            raise field("ki", f"{fields['ki']!r} is not a known-issue id")
        if not fields.get("text", "").strip():
            raise field("text", "ki-close needs a non-empty resolution text")
        return None
    path = _repo_file(candidate, METRICS_FILE)
    if path is None:
        raise field("metrics", f"{METRICS_FILE} is not a file of the repository")
    anchor = _metrics_anchor(path.read_bytes().decode("utf-8").splitlines())
    row = fields["row"].strip()
    if anchor is None or not row.endswith("|") or _cell_count(row) != anchor[1]:
        raise field(
            "columns",
            f"the row has {_cell_count(row)} cells; the {METRICS_FILE} header has "
            f"{anchor[1] if anchor else 'no'} columns",
        )
    return None


def _run_tool(candidate: Path, rid: str, tool: str, *args: str) -> None:
    """Run the candidate's own ``tools/<tool>`` in the candidate (it edits the candidate).

    Raises:
        Refusal: ``integrate_failed:<id>`` (the tool cannot start or exits nonzero).
    """
    env = dict(_git_env(), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    command = [sys.executable, str(candidate / "tools" / tool), *args]
    try:
        proc = subprocess.run(
            command,
            cwd=str(candidate),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=env,
            check=False,
        )
    except OSError as exc:
        raise Refusal(f"integrate_failed:{rid}", f"cannot run {tool}: {exc}") from None
    if proc.returncode != 0:
        output = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip()
        raise Refusal(
            f"integrate_failed:{rid}",
            f"{tool} {' '.join(args)} exited {proc.returncode}: {output}",
        )


def _conflict(rid: str, detail: str) -> bool:
    """Print a left-out request (``request_conflict:<id>``); the land continues."""
    print(f"request_conflict:{rid}")
    print(f"  {detail}")
    return False


def _rewrite_text(path: Path, text: str) -> None:
    """Write ``text`` back as UTF-8 bytes (the newlines it already has are kept)."""
    _replace_atomically(path, text.encode("utf-8"))


def _apply_request(
    candidate: Path, request: _Request, payload: dict[str, str] | None
) -> bool:
    """Apply one checked request in the candidate; False for a listed conflict.

    ``meu-status`` and the two known-issue forms run the existing verbs of
    ``tools/meu_status.py`` and ``tools/issue_triage.py``; ``grouping-cursor``
    rewrites the ``Global cursor: **<id>**`` line; ``metrics-row`` adds the row
    after the last table line of ``docs/execution/metrics.md``.

    Raises:
        Refusal: ``integrate_failed:<id>`` (a verb failed).
    """
    rid, fields = request.rid, request.fields
    ki_files = (
        "--yaml",
        str(candidate / KI_YAML_FILE),
        "--md",
        str(candidate / KI_MD_FILE),
    )
    if request.form == "meu-status":
        reason = fields.get("reason", "").strip()
        extra = ("--reason", reason) if reason else ()
        _run_tool(
            candidate,
            rid,
            "meu_status.py",
            "update",
            fields["meu"],
            fields["status"],
            *extra,
        )
        return True
    if request.form == "grouping-cursor":
        path = candidate / fields["file"]
        text = path.read_bytes().decode("utf-8")
        session = fields["session"]
        _rewrite_text(
            path,
            _CURSOR_RE.sub(
                lambda m: f"{m.group(1)}{session}{m.group(3)}", text, count=1
            ),
        )
        return True
    if request.form == "ki-file":
        ki = fields["ki"]
        if ki in _ki_states(candidate):
            return _conflict(rid, f"{ki} is already a known issue; ki-file left out")
        if payload is None:
            raise Refusal(
                f"integrate_failed:{rid}", f"the payload of {ki} was not checked"
            )
        options: list[str] = []
        for key, flag in (
            ("status", "--add-status"),
            ("discovered", "--discovered"),
            ("root_cause", "--root-cause"),
            ("blast_radius", "--blast-radius"),
        ):
            if key in payload:
                options += [flag, payload[key]]
        _run_tool(
            candidate,
            rid,
            "issue_triage.py",
            *ki_files,
            "add",
            "--id",
            ki,
            "--title",
            payload["title"],
            "--severity",
            payload["severity"],
            "--component",
            payload["component"],
            *options,
        )
        return True
    if request.form == "ki-close":
        ki = fields["ki"]
        state = _ki_states(candidate).get(ki)
        if state is None:
            return _conflict(rid, f"{ki} is not a known issue; ki-close left out")
        if state == "resolved":
            return _conflict(rid, f"{ki} is already resolved; ki-close left out")
        _run_tool(
            candidate,
            rid,
            "issue_triage.py",
            *ki_files,
            "resolve",
            ki,
            "--resolution",
            fields["text"].strip(),
        )
        return True
    path = candidate / METRICS_FILE
    text = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    anchor = _metrics_anchor([line.rstrip("\r\n") for line in lines])
    if anchor is None:
        raise Refusal(f"integrate_failed:{rid}", f"{METRICS_FILE} lost its table")
    last = anchor[0]
    if not lines[last].endswith(("\n", "\r")):
        lines[last] += newline
    lines.insert(last + 1, fields["row"].strip() + newline)
    _rewrite_text(path, "".join(lines))
    return True


def _regenerate(candidate: Path, tools: set[str]) -> None:
    """Regenerate the derived files of the junction sources the requests changed.

    ``meu_status.py render`` rewrites the generated regions of the MEU registry
    and the build plan; ``issue_triage.py render`` rewrites ``known-issues.md``.

    Raises:
        Refusal: ``integrate_failed:render`` (a render failed).
    """
    if "meu_status.py" in tools:
        _run_tool(candidate, "render", "meu_status.py", "render")
    if "issue_triage.py" in tools:
        _run_tool(
            candidate,
            "render",
            "issue_triage.py",
            "--yaml",
            str(candidate / KI_YAML_FILE),
            "--md",
            str(candidate / KI_MD_FILE),
            "render",
        )


def _commit_t(candidate: Path, land: LandOp, l1: str) -> str:
    """Build T: the candidate's tree, with the baselines as L1 has them, as a commit on L1.

    ``git add -A`` stages every path except ``BASELINE_FILES``, so the
    integrator never changes a baseline. ``commit-tree`` makes T (parent L1,
    unsigned: T is never published as it is), and the candidate's HEAD moves
    from L1 to T.

    Returns:
        T, the integrated commit.

    Raises:
        Refusal: ``git_failed``.
    """
    excludes = [f":(exclude){path}" for path in BASELINE_FILES]
    _git_text(candidate, *GIT_LONGPATHS, "add", "-A", "--", ".", *excludes)
    tree = _git_text(candidate, "write-tree").strip()
    integrated = _git_text(
        candidate,
        "-c",
        "commit.gpgsign=false",
        "commit-tree",
        tree,
        "-p",
        l1,
        "-m",
        f"land({land.lane}): integrate the requests of {land.op}",
    ).strip()
    _git_text(
        candidate,
        "update-ref",
        "--no-deref",
        "-m",
        f"land {land.op}: T",
        "HEAD",
        integrated,
        l1,
    )
    return integrated


def _handoff_set(candidate: Path, plan: str) -> list[str]:
    """The canonical handoffs of the plan in the candidate (AC-785.15, AC-785.41).

    The ``meus`` of the committed ``task.md`` name one ``<plan>-<MEU>-handoff.md``
    each, in ``meus`` order; an empty ``meus`` names the project handoff
    ``<plan>-handoff.md``. The run_parameters helpers own the rule
    (``completion_preflight.check_handoffs`` reads the same set).

    Raises:
        Refusal: ``binding`` (``task_meus``: ``meus`` is not a list of MEU ids)
            or ``schema`` (the frontmatter is not strict YAML).
    """
    _batch_path()
    from tools import run_parameters as rp  # noqa: PLC0415 - the land verbs only

    name = plan.rsplit("/", 1)[-1]
    try:
        return rp._handoff_paths(name, rp._plan_meus(candidate, name))
    except _batch_errors() as exc:
        raise _as_refusal(exc, plan) from None


def _focus_with_landed(text: str, *, lane: str, op: str, l0: str) -> str:
    """``current-focus.md`` text plus the landed lane (D:237, AC-785.15).

    The ``## Landed lanes`` section holds one line per lane,
    ``- `<lane>`: landed by op `<op>` from L0 `<l0[:12]>`.``; a lane that lands
    again replaces its line. A missing section is added at the end of the file,
    with no line before it changed, so the current priority and the other
    lanes stay byte-equal.
    """
    entry = f"- `{lane}`: landed by op `{op}` from L0 `{l0[:12]}`."
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    try:
        start = lines.index(FOCUS_LANDED_HEADING)
    except ValueError:
        tail = "" if not text or text.endswith(("\n", "\r")) else newline
        return text + tail + newline.join([FOCUS_LANDED_HEADING, "", entry]) + newline
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    body = [
        line for line in lines[start + 1 : end] if not line.startswith(f"- `{lane}`")
    ]
    last = max(
        (i for i, line in enumerate(body) if line.startswith("- `")), default=None
    )
    if last is None:
        body = ["", entry, *[line for line in body if line.strip()]]
        if end < len(lines):
            body.append("")
    else:
        body.insert(last + 1, entry)
    out = [*lines[: start + 1], *body, *lines[end:]]
    return newline.join(out) + newline


def _land_focus(candidate: Path, land: LandOp) -> None:
    """Write the landed lane into the candidate's ``current-focus.md`` (D:237).

    A lane never edits the junction files, so the candidate has P's text; a
    repository without the file has no focus to update.

    Raises:
        Refusal: ``junction_unreadable:current-focus`` (the file cannot be read).
    """
    path = _repo_file(candidate, CURRENT_FOCUS_FILE)
    if path is None or not path.is_file():
        return
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal(
            "junction_unreadable:current-focus", f"cannot read {path}: {exc}"
        ) from None
    l0 = str(land.fields().get("L0", ""))
    _rewrite_text(path, _focus_with_landed(text, lane=land.lane, op=land.op, l0=l0))


def _integrate(
    land: LandOp,
    card: Card,
    top: Path,
    common: Path,
    l1: str,
    *,
    wait_s: float,
    poll_s: float,
    argv: Sequence[str],
) -> str:
    """Step 3 (D:246, AC-785.15): apply the lane's integration requests on L1 and build T.

    The canonical handoff set of L1 (``_handoff_set``: one handoff per MEU of
    the committed ``task.md``, or the project handoff for a plan with no MEUs;
    a handoff that is not there has no requests) is read in the candidate, in
    order, as one table: an id repeats across the set as it would in one
    handoff. Every row is parsed and checked first, so a bad request refuses
    before anything changes; then each request is applied once, in order. A
    conflict is left out and listed (``request_conflict:<id>``). The derived
    files regenerate, ``current-focus.md`` becomes P's text plus the landed
    lane (``_focus_with_landed``) and T is built. A refusal removes the
    candidate and sets the card back to ``active``, as in step 2.

    Returns:
        T. ``land:integrate:done`` journals L1, T and the applied request ids.
    """
    candidate = _land_candidate_path(land)
    _journal(land, LAND_INTEGRATE, done=False)
    try:
        plan = str(card["plan"]).rstrip("/")
        rows: list[tuple[str, str]] = []
        for rel in _handoff_set(candidate, plan):
            handoff = _repo_file(candidate, rel)
            if handoff is None:
                continue
            try:
                rows += _request_rows(handoff.read_bytes().decode("utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                raise Refusal(
                    "junction_unreadable:handoff", f"cannot read {handoff}: {exc}"
                ) from None
        requests = _parse_requests(rows, lane=land.lane, generation=land.generation)
        payloads = {
            request.rid: _check_request(candidate, request, plan)
            for request in requests
        }
        applied: list[str] = []
        derived: set[str] = set()
        for request in requests:
            if not _apply_request(candidate, request, payloads[request.rid]):
                continue
            applied.append(request.rid)
            if request.form == "meu-status":
                derived.add("meu_status.py")
            elif request.form in ("ki-file", "ki-close"):
                derived.add("issue_triage.py")
        _regenerate(candidate, derived)
        _land_focus(candidate, land)
        integrated = _commit_t(candidate, land, l1)
    except Refusal:
        _remove_candidate(top, candidate)
        _set_card(
            common,
            card,
            state="active",
            op=None,
            expect_op=land.op,
            wait_s=wait_s,
            poll_s=poll_s,
            argv=argv,
        )
        raise
    _journal(
        land,
        LAND_INTEGRATE,
        done=True,
        evidence={"L1": l1, "T": integrated, "request_ids": applied},
    )
    return integrated


# ---------------------------------------------------------------------------
# land prepare: step 4 kept refs and step 5 gate (design §5.5, AC-785.16/.17)
# ---------------------------------------------------------------------------


def _kept_ref(land: LandOp, name: str) -> str:
    """``refs/lanes/<slug>/<op>/<name>``: one kept ref of the land."""
    return f"{KEPT_REF_PREFIX}/{land.lane}/{land.op}/{name}"


def _kept_value(top: Path, ref: str) -> str:
    """The object id ``ref`` names; empty when the ref does not exist."""
    proc = _git(top, "rev-parse", "-q", "--verify", ref)
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("ascii", "replace").strip()


def _missing_kept(top: Path, land: LandOp, objects: Mapping[str, str]) -> list[str]:
    """The names of the kept refs not yet written.

    Raises:
        Refusal: ``kept_moved:<name>`` (a kept ref names another object than
            the journal; a kept ref is never moved and L1 or T never rebuilt).
    """
    missing: list[str] = []
    for name in KEPT_NAMES:
        ref = _kept_ref(land, name)
        have = _kept_value(top, ref)
        if not have:
            missing.append(name)
        elif have != objects[name]:
            raise Refusal(
                f"kept_moved:{name}",
                f"{ref} is {have}; the journal of {land.op} names {objects[name]}. "
                "Ask the human.",
            )
    return missing


def _keep(top: Path, land: LandOp, objects: Mapping[str, str]) -> None:
    """Step 4 (D:247, AC-785.16): write the kept refs L0, L1 and T.

    Each ref is created with the "must not exist" old value, so a kept ref is
    never moved. Journaled as ``land:kept`` started and done.

    Raises:
        Refusal: ``kept_moved:<name>`` or ``git_failed``.
    """
    _journal(land, LAND_KEPT, done=False)
    for name in _missing_kept(top, land, objects):
        _git_text(
            top,
            "update-ref",
            "-m",
            f"land {land.op}: keep {name}",
            _kept_ref(land, name),
            objects[name],
            "",
        )
    _journal(land, LAND_KEPT, done=True)


def _gate_python(candidate: Path) -> str:
    """The gate's interpreter: the candidate's ``.venv`` one, else this one (R1-F6)."""
    folder, name = (
        ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    )
    python = candidate / ".venv" / folder / name
    return str(python) if python.is_file() else sys.executable


def _gate_env() -> dict[str, str]:
    """The gate's environment: ``_git_env()`` without GATE_ENV_DROPPED (R1-F6)."""
    env = {
        key: value for key, value in _git_env().items() if key not in GATE_ENV_DROPPED
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _recorded_links(lane: Path) -> list[str]:
    """The links the lane's ``executor-worktree.json`` records; none without one.

    Raises:
        Refusal: ``candidate_runtime:manifest`` (the file is there but invalid).
        executor_worktree._GitFailure: git cannot resolve the lane's git dir.
    """
    git_dir = executor_worktree._worktree_git_dir(lane)
    if git_dir is None or not (git_dir / executor_worktree.WORKTREE_MANIFEST).is_file():
        return []
    read = executor_worktree._read_manifest(lane)
    if read is None:
        raise Refusal(
            "candidate_runtime:manifest",
            f"the {executor_worktree.WORKTREE_MANIFEST} of the lane {lane} is invalid",
        )
    return [str(rel) for rel in cast("list[object]", read[1]["links"])]


def _provision_candidate(candidate: Path, lane: Path) -> None:
    """Give the candidate the lane's runtime before the gate (R1-F6, AC-785.17).

    As ``executor_worktree.py create`` provisions a worktree from the project
    parts of the worktree config (``load_worktree_config``) of T, the tree the
    candidate holds and the review binds to, never main's (R2-F2): each dependency
    tree of the lane (the links its ``executor-worktree.json`` records and its
    ignored ``linked_trees`` folders) is linked, never copied, at the same path
    to the folder it resolves to; the lane's ``env_files`` and ``frozen_dirs``
    are copied; when ``venv_build`` is set, a lane with a ``.venv`` gives the
    candidate its own venv (editable installs hold absolute paths, so a venv is
    never shared). A project without the config file has no project parts, so
    only the recorded links are made. What the lane lacks, the candidate lacks.
    A path T already holds is never replaced.

    Raises:
        Refusal: ``candidate_runtime:config`` (the config file is invalid),
            ``candidate_runtime:<rel>`` (T holds the path, the lane's manifest
            cannot be read, or a link or copy fails) or
            ``candidate_runtime:venv`` (the venv build failed).
    """
    config: dict[str, object] = {}
    if (candidate / executor_worktree.WORKTREE_CONFIG).is_file():
        try:
            config = executor_worktree.load_worktree_config(candidate)
        except executor_worktree.WorktreeConfigError as exc:
            raise Refusal("candidate_runtime:config", str(exc)) from None

    def parts(key: str) -> list[str]:
        return executor_worktree._strings(config, key) if config else []

    try:
        recorded = _recorded_links(lane)
        found = executor_worktree._linked_trees(lane, parts("linked_trees"))
    except (executor_worktree._GitFailure, OSError) as exc:
        raise Refusal(
            "candidate_runtime:manifest",
            f"cannot list the dependency trees of the lane {lane}: {exc}",
        ) from None
    for rel in sorted({*recorded, *found}):
        source = lane / rel
        if not source.is_dir():
            continue
        target = os.path.realpath(source)
        link = candidate / rel
        if os.path.lexists(link):
            if executor_worktree._is_link(link) and executor_worktree._same_path(
                os.path.realpath(link), target
            ):
                continue
            raise Refusal(
                f"candidate_runtime:{rel}",
                f"T holds {rel}; the lane's dependency tree cannot be linked there",
            )
        try:
            executor_worktree._make_dir_link(link, Path(target))
        except OSError as exc:
            raise Refusal(
                f"candidate_runtime:{rel}", f"cannot link {link} to {target}: {exc}"
            ) from None
    for rel in (*parts("env_files"), *parts("frozen_dirs")):
        source = lane / rel
        if not (source.is_file() or source.is_dir()):
            continue
        copy = candidate / rel
        if os.path.lexists(copy):
            raise Refusal(
                f"candidate_runtime:{rel}",
                f"T holds {rel}; the lane's copy cannot be put there",
            )
        try:
            copy.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, copy, symlinks=True)
            else:
                shutil.copyfile(source, copy)
        except OSError as exc:
            raise Refusal(
                f"candidate_runtime:{rel}", f"cannot copy {source} to {copy}: {exc}"
            ) from None
    if (
        config.get("venv_build") is None
        or not (lane / executor_worktree.VENV_MARKER).is_file()
    ):
        return
    try:
        code = executor_worktree._build_venv(candidate, config)
    except (executor_worktree._Refusal, executor_worktree._GitFailure, OSError) as exc:
        raise Refusal(
            "candidate_runtime:venv", f"cannot build the venv of {candidate}: {exc!r}"
        ) from None
    if code != 0:
        raise Refusal(
            "candidate_runtime:venv", f"venv_build exited {code} in {candidate}"
        )


def _run_gate(candidate: Path, parent: str, integrated: str) -> tuple[str, Path]:
    """Run the gate on T in the candidate: ``tools/validate_codebase.py --scope meu``.

    The gate runs the candidate's interpreter with ``_gate_env()`` (R1-F6).
    ``--files`` lists the paths of ``P..T`` that T keeps. All output goes to
    ``<candidate git dir>/land-gate.txt``. A failed gate is a result, not a
    refusal: the report shows it to the reviewer.

    Returns:
        ``(result, log)``: the result is ``pass`` or ``fail:<exit code>``.

    Raises:
        Refusal: ``gate_unavailable`` (the gate cannot start or its log cannot
            be written) or ``git_failed``.
    """
    diff = _git(
        candidate,
        "diff",
        "--name-only",
        "--diff-filter=d",
        "-z",
        parent,
        integrated,
        "--",
    )
    if diff.returncode != 0:
        raise Refusal("git_failed", diff.stderr.decode("utf-8", "replace").strip())
    files = _split_z(diff.stdout)
    command = [_gate_python(candidate), GATE_SCRIPT, "--scope", "meu"]
    if files:
        command += ["--files", *files]
    git_dir = _git_text(candidate, "rev-parse", "--absolute-git-dir").strip()
    log = Path(git_dir) / GATE_LOG_NAME
    env = _gate_env()
    try:
        with log.open("wb") as out:
            proc = subprocess.run(
                command,
                cwd=str(candidate),
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                check=False,
            )
    except OSError as exc:
        raise Refusal(
            "gate_unavailable", f"cannot run the gate in {candidate}: {exc}"
        ) from None
    result = GATE_PASS if proc.returncode == 0 else f"fail:{proc.returncode}"
    return result, log


def _tested_tree(candidate: Path, integrated: str) -> None:
    """After the gate (R1-F3, AC-785.17/.33): the candidate still holds exactly T.

    The gate result binds to T only when the gate tested T: HEAD is still T, and
    the index and every tracked working file still equal T. Untracked output (a
    report, a cache) is not compared.

    Raises:
        Refusal: ``gate_tree_drift`` (the gate moved HEAD or changed a tracked
            path; the paths are listed) or ``git_failed``.
    """
    head = _git_text(candidate, "rev-parse", "--verify", "HEAD").strip()
    if head != integrated:
        raise Refusal(
            "gate_tree_drift",
            f"the gate moved HEAD of {candidate} from T {integrated} to {head}; "
            "the gate result is not recorded. Make the gate leave HEAD at T, "
            "then run land prepare again.",
        )
    changed: set[str] = set()
    for staged in (("--cached",), ()):
        proc = _git(candidate, "diff", "--name-only", "-z", *staged, integrated, "--")
        if proc.returncode != 0:
            raise Refusal("git_failed", proc.stderr.decode("utf-8", "replace").strip())
        changed.update(_split_z(proc.stdout))
    if changed:
        raise Refusal(
            "gate_tree_drift",
            f"the gate changed tracked paths of T in {candidate}: "
            f"{', '.join(sorted(changed))}; the gate result is not recorded. "
            "Commit what the gate generates in the lane, then land again.",
        )


def _ready(
    top: Path, land: LandOp, objects: Mapping[str, str], lane_worktree: Path
) -> str:
    """Step 5 (D:248, AC-785.17): the gate on T, ``gate{tree, result}``, the report.

    The candidate gets the runtime of ``lane_worktree`` after the started entry
    and before the gate (R1-F6), so a failed provision leaves ``land:ready``
    started and recovery provisions the candidate it makes again.

    The same entry records ``carrier{task, plan, grouping}``, the blob ids of the
    lane plan's carriers at L1 (AC-785.20), which ``land publish`` binds to.

    The report names P, L0, L1, T, the gate result and its log, and the two
    review inputs: the rebase resolutions ``git range-diff <merge-base>..L0
    P..L1`` and the integration changes ``git diff L1 T`` (with its stat). The
    last line is ``land_ready:<op>:<tree of T>``; the verdict binds to that tree.

    Returns:
        The tree id of T.

    Raises:
        Refusal: ``candidate_runtime:<rel>`` (see ``_provision_candidate``),
            ``gate_unavailable``, ``gate_tree_drift`` (the gate changed the
            candidate, so it did not test T; ``land:ready`` stays started),
            ``git_failed`` or a journal refusal.
    """
    candidate = _land_candidate_path(land)
    tree = _git_text(top, "rev-parse", "--verify", f"{objects['T']}^{{tree}}").strip()
    carrier = _carrier_record(top, land, objects["L1"])
    _journal(land, LAND_READY, done=False)
    _provision_candidate(candidate, lane_worktree)
    result, log = _run_gate(candidate, objects["P"], objects["T"])
    _tested_tree(candidate, objects["T"])
    _journal(
        land,
        LAND_READY,
        done=True,
        evidence={"gate": {"tree": tree, "result": result}, "carrier": carrier},
    )
    base = _git_text(top, "merge-base", objects["P"], objects["L0"]).strip()
    stat = _git_text(top, "diff", "--stat", objects["L1"], objects["T"], "--")
    for name in ("P", *KEPT_NAMES):
        print(f"land_report:{name}:{objects[name]}")
    print(f"land_report:gate:{result}")
    print(f"land_report:gate_log:{log.as_posix()}")
    print(
        f"land_review:rebase:git range-diff {base}..{objects['L0']} "
        f"{objects['P']}..{objects['L1']}"
    )
    print(f"land_review:integration:git diff {objects['L1']} {objects['T']}")
    for line in stat.splitlines():
        print(f"  {line}")
    print(f"land_ready:{land.op}:{tree}")
    return tree


def _landing_card(card: Card, land: LandOp) -> None:
    """A step after step 3 needs the card ``landing`` with this op.

    Raises:
        Refusal: ``card_superseded``.
    """
    if card["state"] != "landing" or card["op"] != land.op:
        raise Refusal(
            "card_superseded",
            f"the card of {land.lane} is {card['state']} with op {card['op']}; "
            f"op {land.op} needs it landing with that op",
        )


def _journal_objects(land: LandOp) -> dict[str, str]:
    """P, L0, L1 and T as the journal names them.

    Raises:
        Refusal: ``recovery_unclear:<phase>`` (one is missing or not 40-hex).
    """
    fields = land.fields()
    objects = {name: str(fields.get(name, "")) for name in ("P", *KEPT_NAMES)}
    absent = [
        name for name, value in objects.items() if not _OBJECT_ID_RE.fullmatch(value)
    ]
    if absent:
        raise Refusal(
            f"recovery_unclear:{land.phase}",
            f"the journal of {land.op} names no {', '.join(absent)}; nothing "
            "changed. Ask the human.",
        )
    return objects


def _recover_ready(top: Path, land: LandOp, card: Card) -> int:
    """Recovery of steps 4-5 (D:262 "Steps 4-5", EA-25): reuse the kept objects.

    After ``land:integrate:done`` or ``land:kept:started`` the missing kept refs
    are written from the journal; after ``land:kept:done`` or
    ``land:ready:started`` every kept ref must equal the journal. L1 and T are
    never rebuilt: the candidate is made again at the kept T (a changed
    candidate is discarded), and step 5 runs again.

    Raises:
        Refusal: ``card_superseded``, ``kept_moved:<name>`` or
            ``recovery_unclear:<phase>``.
    """
    _landing_card(card, land)
    objects = _journal_objects(land)
    status = land.journal[-1]["status"]
    if land.phase == LAND_INTEGRATE or (
        land.phase == LAND_KEPT and status == "started"
    ):
        _keep(top, land, objects)
    elif _missing_kept(top, land, objects):
        raise Refusal(
            f"recovery_unclear:{land.phase}",
            f"the journal of {land.op} is past step 4 but a kept ref is missing; "
            "nothing changed. Ask the human.",
        )
    candidate = _land_candidate_path(land)
    _remove_candidate(top, candidate)
    _add_candidate(top, candidate, land, objects["T"])
    _ready(top, land, objects, Path(str(card["worktree"])))
    return 0


# ---------------------------------------------------------------------------
# land prepare --op ID --verdict FILE (design §5.5 step 5, AC-785.17)
# ---------------------------------------------------------------------------


def _read_verdict(path: Path, op: str) -> dict[str, str]:
    """The ``land-verdict/1`` file ``{schema, op, tree, verdict, review}``, checked.

    Raises:
        Refusal: ``verdict_file`` (unreadable) or ``verdict_schema:<key>`` (an
            unknown or missing key, or a value outside the schema; ``json``
            when the file is not one JSON object).
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Refusal("verdict_file", f"cannot read {path}: {exc}") from None
    try:
        data: object = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal("verdict_schema:json", f"{path}: {exc}") from None
    if not isinstance(data, dict):
        raise Refusal("verdict_schema:json", f"{path} is not one JSON object")
    record = cast(dict[str, object], data)
    for key in sorted(record):
        if key not in VERDICT_KEYS:
            raise Refusal(f"verdict_schema:{key}", f"{path}: unknown key {key}")
    for key in VERDICT_KEYS:
        if not isinstance(record.get(key), str):
            raise Refusal(f"verdict_schema:{key}", f"{path}: {key} is not a string")
    verdict = {key: cast(str, record[key]) for key in VERDICT_KEYS}
    checks = (
        ("schema", verdict["schema"] == VERDICT_SCHEMA),
        ("op", verdict["op"] == op),
        ("tree", bool(_OBJECT_ID_RE.fullmatch(verdict["tree"]))),
        ("verdict", verdict["verdict"] in VERDICT_VALUES),
        ("review", _safe_repo_path(verdict["review"])),
    )
    for key, ok in checks:
        if not ok:
            raise Refusal(
                f"verdict_schema:{key}",
                f"{path}: {key} {verdict[key]!r} is not valid",
            )
    return verdict


def _cmd_land_verdict(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    """Record the reviewer's verdict on a ready land, bound to the tree id of T.

    Order: the verdict file (``verdict_file``, ``verdict_schema:<key>``); a
    first read of the journal (``op_unknown``); the per-op lease in one attempt
    (``op_busy``, exit 3); under it the journal again (``journal_moved``), the
    phase ``land:ready:done`` (``land_not_ready:<phase>``) and the card under
    the registry lock (``card_superseded``); then the tree (``verdict_stale``)
    and the verdict (``verdict_not_approved``). An approved verdict is
    journaled as a second ``land:ready:done`` entry with
    ``verdict{tree, verdict}``; a refusal writes nothing. Prints
    ``land_verdict:<op>:<tree>:approved``.
    """
    op = str(args.op)
    verdict = _read_verdict(Path(args.verdict), op)
    top, common = _repo_dirs(Path.cwd())
    before = _land_journal(top, op)
    if before is None:
        raise Refusal(
            "op_unknown",
            f"no land journal carries op {op} in {common / 'run-parameters'}",
        )
    lease = _op_lease(common, op, poll_s=poll_s, argv=argv)
    if lease is None:
        return EXIT_BUSY
    try:
        land = _land_journal(top, op)
        if land is None or before.raw != land.raw:
            raise Refusal(
                "journal_moved",
                f"the journal of {op} changed while the op lease was taken; "
                "record the verdict again",
            )
        status = land.journal[-1]["status"] if land.journal else None
        if land.phase != LAND_READY or status != "done":
            raise Refusal(
                f"land_not_ready:{land.phase}",
                f"op {op} is at {land.phase}:{status}; a verdict needs "
                f"{LAND_READY}:done",
            )
        with _registry_lock(common, wait_s=wait_s, poll_s=poll_s, argv=argv):
            _landing_card(_recovery_card(common, land), land)
        integrated = str(land.fields().get("T", ""))
        tree = _git_text(top, "rev-parse", "--verify", f"{integrated}^{{tree}}").strip()
        if verdict["tree"] != tree:
            raise Refusal(
                "verdict_stale",
                f"the verdict is for tree {verdict['tree']}; T of {op} has tree "
                f"{tree}. Review the land again.",
            )
        if verdict["verdict"] != VERDICT_APPROVED:
            raise Refusal(
                "verdict_not_approved",
                f"the verdict for tree {tree} is {verdict['verdict']}; fix the "
                "lane and land again",
            )
        _journal(
            land,
            LAND_READY,
            done=True,
            evidence={"verdict": {"tree": tree, "verdict": VERDICT_APPROVED}},
        )
    finally:
        os_lease.release(lease)
    print(f"land_verdict:{op}:{tree}:{VERDICT_APPROVED}")
    return 0


def _carrier_paths(top: Path, plan: str, l1: str) -> dict[str, str]:
    """The carrier paths of the lane plan at L1 (D:268): ``task``, ``plan``, ``grouping``.

    The grouping file is the one the task block's ``scope.grouping`` names at L1; a plan
    with no grouping (``none``, a manual or legacy plan, or a block that does not parse)
    has no grouping carrier. The run_parameters helpers name the paths, read at L1
    through the committed-carrier adapter.

    Raises:
        Refusal: a commit_batch/run_parameters refusal opening the repository.
    """
    _batch_path()
    from tools import run_parameters as rp  # noqa: PLC0415 - the land verbs only

    try:
        handle = rp.bind_carrier(rp._open_repo(top), l1, {})
        folder = rp._plan_dir(handle, plan)
        paths = {
            "task": folder / "task.md",
            "plan": folder / "implementation-plan.md",
        }
        try:
            grouping = rp._plan_grouping(handle, plan)
        except rp.Refusal:
            grouping = None
        if grouping is not None:
            paths["grouping"] = rp._grouping_path(handle, grouping)
    except _batch_errors() as exc:
        raise _as_refusal(exc, plan) from None
    except rp.GitError as exc:
        raise Refusal("git_failed", str(exc)) from None
    return {key: path.relative_to(handle.top).as_posix() for key, path in paths.items()}


def _blob_at(top: Path, commit: str, rel: str) -> str | None:
    """The blob id of ``rel`` at ``commit``, or None when it is not a file there.

    ``<commit>:<path>`` takes the rest of the argument as the path, so the type is
    checked with ``cat-file -t`` rather than a ``^{blob}`` suffix.
    """
    proc = _git(top, "rev-parse", "-q", "--verify", f"{commit}:{rel}")
    if proc.returncode != 0:
        return None
    oid = proc.stdout.decode("ascii", "replace").strip()
    kind = _git(top, "cat-file", "-t", oid)
    if kind.returncode != 0 or kind.stdout.decode("ascii", "replace").strip() != "blob":
        return None
    return oid


def _carrier_record(top: Path, land: LandOp, l1: str) -> dict[str, str]:
    """``carrier{task, plan, grouping}``: the blob ids of the carriers at L1 (AC-785.20).

    A carrier path that is not a file at L1 is left out; publish then reads that
    path as absent too.

    Raises:
        Refusal: from ``_carrier_paths``.
    """
    plan = str(land.identity["plan"])
    record: dict[str, str] = {}
    for key, rel in _carrier_paths(top, plan, l1).items():
        oid = _blob_at(top, l1, rel)
        if oid is not None:
            record[key] = oid
    return record


def _check_carrier(top: Path, land: LandOp, worktree: Path) -> dict[str, str]:
    """The carriers still match the bytes recorded at ready (D:268, AC-785.20).

    Each carrier path at L1 must have exactly the recorded blob id, and the lane
    worktree copy must hash (``git hash-object``, the path's attributes) to the same
    id; a recorded path must exist in both. Returns ``{path: blob id}`` for the
    committed-carrier adapter.

    Raises:
        Refusal: ``carrier_mismatch`` (the detail names the carrier and both sides).
    """
    fields = land.fields()
    l1 = str(fields.get("L1", ""))
    raw = fields.get("carrier")
    recorded = cast(dict[str, str], raw) if isinstance(raw, dict) else None
    if not _OBJECT_ID_RE.fullmatch(l1) or recorded is None:
        raise Refusal(
            "carrier_mismatch",
            f"the journal of {land.op} records no carrier commit or carrier blobs; "
            "run land prepare again",
        )
    paths = _carrier_paths(top, str(land.identity["plan"]), l1)
    extra = sorted(set(recorded) - set(paths))
    if extra:
        raise Refusal(
            "carrier_mismatch",
            f"the journal records carriers {', '.join(extra)} that L1 does not name",
        )
    blobs: dict[str, str] = {}
    for key, rel in paths.items():
        committed = _blob_at(top, l1, rel)
        if recorded.get(key) != committed:
            raise Refusal(
                "carrier_mismatch",
                f"{key} {rel}: the journal records {recorded.get(key)}, L1 {l1} "
                f"holds {committed}",
            )
        if committed is None:
            continue
        if not (worktree / rel).is_file():
            raise Refusal(
                "carrier_mismatch",
                f"{key} {rel}: the lane worktree {worktree.as_posix()} has no such "
                f"file; L1 holds {committed}",
            )
        hashed = _git_text(worktree, "hash-object", "--", rel).strip()
        if hashed != committed:
            raise Refusal(
                "carrier_mismatch",
                f"{key} {rel}: the lane worktree copy is {hashed}; the land recorded "
                f"{committed} at L1. Commit or revert the change and land again.",
            )
        blobs[rel] = committed
    return blobs


def _approved_tree(top: Path, land: LandOp) -> str:
    """The tree id of T, which an approved ``land-verdict/1`` recorded (AC-785.17).

    Raises:
        Refusal: ``land_not_ready:<phase>`` (no T), ``verdict_missing`` (no
            approved verdict for this tree of T).
    """
    fields = land.fields()
    integrated = str(fields.get("T", ""))
    if not _OBJECT_ID_RE.fullmatch(integrated):
        raise Refusal(
            f"land_not_ready:{land.phase}",
            f"the journal of {land.op} names no T",
        )
    tree = _git_text(top, "rev-parse", "--verify", f"{integrated}^{{tree}}").strip()
    raw = fields.get("verdict")
    verdict = cast(dict[str, str], raw) if isinstance(raw, dict) else {}
    if verdict.get("tree") != tree or verdict.get("verdict") != VERDICT_APPROVED:
        raise Refusal(
            "verdict_missing",
            f"op {land.op} has no approved verdict for tree {tree}; record it with "
            f"land prepare --op {land.op} --verdict FILE",
        )
    return tree


def _needs_human(plan: str, why: str) -> Refusal:
    """``needs_human_publish``: the detail ends with the exact sentence the human types."""
    return Refusal(
        "needs_human_publish",
        f"{why}. Post this sentence for the human to type in chat, end the turn, "
        "then run land publish again with --human-directed --session S "
        "--message-uuid U:\n" + HUMAN_PUBLISH_SENTENCE.format(plan=plan),
    )


def _authority(
    args: argparse.Namespace,
    top: Path,
    land: LandOp,
    blobs: Mapping[str, str],
    lane_worktree: Path,
) -> tuple[str, RpRepo]:
    """Step 6 (D:248, AC-785.18): the authority for this op, decided without a lock.

    ``--grant`` verifies the lane plan's ``exec_commit`` grant over the committed
    carriers (L1 and the recorded blobs) with ``scope.branch`` equal to ``main``
    and reserves it for this op (idempotent for the same op, V-8).
    ``--human-directed`` resolves the typed record through commit_batch's
    ``_consent`` to this plan on ``main``. Repository identity, store and
    target are those of the main repository; the transcript lookup also maps
    the reserving lane worktree's folder (``rp.with_lane``, R1-F4, D:268).

    Returns:
        ``(grant | human:<message uuid>, the carrier-bound main handle)``. The
        human direction is only resolved here; ``_publish`` spends it once
        (``commit_batch.spend_direction``) just before the publication.

    Raises:
        Refusal: ``needs_human_publish`` (no authority form, or a ``manual`` or
            ``legacy`` plan under ``--grant``), or the verifier's reason
            (``scope_branch_mismatch``, ``no_commit_direction``, ...).
    """
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only
    from tools import run_parameters as rp  # noqa: PLC0415 - the land verbs only

    plan = str(land.identity["plan"])
    l1 = str(land.fields()["L1"])
    main_repo = rp.with_lane(_main_repo(top), lane_worktree)
    try:
        handle = rp.bind_carrier(main_repo, l1, blobs)
        if args.grant:
            try:
                rp.reserve_act(
                    handle, plan, PUBLISH_ACT, land.op, branch=PUBLISH_BRANCH
                )
            except rp.NonAuthorizing as exc:
                raise _needs_human(
                    plan, f"the plan's authorization is {exc.kind}; it holds no grant"
                ) from None
            return "grant", handle
        if args.human_directed:
            consent = commit_batch.human_direction(
                handle,
                str(args.session),
                str(args.message_uuid),
                plan,
                PUBLISH_BRANCH,
            )
            return f"human:{consent['message_uuid']}", handle
    except _batch_errors() as exc:
        raise _as_refusal(exc, land.op) from None
    except rp.GitError as exc:
        raise Refusal("git_failed", str(exc)) from None
    raise _needs_human(plan, "no --grant and no --human-directed direction was given")


def _main_tree(top: Path) -> Path:
    """The main worktree (the first entry of ``git worktree list``), whatever the cwd."""
    return Path(_worktrees(top)[0])


def _land_message(path: Path) -> str:
    """The text of a checked message file, refused now if its canonical form is empty.

    Raises:
        Refusal: ``message_file`` (not UTF-8) or commit_batch's ``message``.
    """
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only

    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal("message_file", f"cannot read {path} as UTF-8: {exc}") from None
    try:
        commit_batch.canonical_message(text)
    except _batch_errors() as exc:
        raise _as_refusal(exc, "the land") from None
    return text


def _close(top: Path, land: LandOp) -> None:
    """Step 9 (D:252, AC-785.22): delete the kept refs, journal ``land:closed``.

    ``land:closed:started``, the kept refs ``refs/lanes/<slug>/<op>/*`` and the
    disposable land candidate removed, then ``land:closed:done``. A journal
    already at ``land:closed:started`` resumes without a second entry. The card
    stays ``landing`` until ``release --reset`` or ``remove``.

    Raises:
        Refusal: ``git_failed``, ``candidate_remove`` or the journal writer's reason.
    """
    if land.phase != LAND_CLOSED:
        _journal(land, LAND_CLOSED, done=False)
    for name in KEPT_NAMES:
        ref = _kept_ref(land, name)
        if _kept_value(top, ref):
            _git_text(top, "update-ref", "-d", ref)
    _remove_candidate(top, _land_candidate_path(land))
    _journal(land, LAND_CLOSED, done=True)


def _sync_and_close(
    top: Path,
    land: LandOp,
    repo: RpRepo,
    *,
    sync: bool,
) -> None:
    """Step 8 (``commit_batch.land_sync`` on the main tree) when ``sync``, then step 9.

    The caller holds the main-tree lease.

    Raises:
        Refusal: ``sync_unexplained:<path>``, ``sync_incomplete:<path>``,
            ``git_failed`` or a ``_close`` reason.
    """
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only

    if sync:
        try:
            commit_batch.land_sync(repo, land)
        except _batch_errors() as exc:
            raise _as_refusal(exc, land.op) from None
        except commit_batch.rp.GitError as exc:
            raise Refusal("git_failed", str(exc)) from None
    _close(top, land)


def _publish(
    args: argparse.Namespace,
    land: LandOp,
    *,
    top: Path,
    common: Path,
    main_top: Path,
    handle: RpRepo,
    route: str,
    blobs: Mapping[str, str],
    wait_s: float,
    poll_s: float,
    argv: Sequence[str],
) -> str:
    """Steps 7 to 9 (D:250-252, AC-785.19, AC-785.21, AC-785.22) under the main-tree lease.

    Under the registry lock: the card ``landing`` with this op, session and
    generation (``card_superseded``) and no other land between publication and
    close (``commit_batch.land_blocker``: ``sync_pending:<op>``, ``land_busy:<op>``).
    Then main == P, else the card goes back to ``active`` with op None and the
    verdict is void (``main_moved``: land again from step 1); a clean main tree
    (``main_dirty:<path>``; the land plan's own task.md changed only in
    run_parameters' live fields is carrier state, ``commit_batch.live_task_dirt``,
    EA-60); the carriers again (``carrier_mismatch``); the human
    direction spent once (``commit_batch.spend_direction``); the publication
    through commit_batch's tree adapter (``commit_batch.land_publish``); the
    sync and the close.

    Returns:
        C, the published commit.

    Raises:
        Refusal: each reason above, or commit_batch's (``hook_drift``,
            ``publish_refused``, ``direction_spent``, ...).
    """
    _batch_path()
    from tools import commit_batch  # noqa: PLC0415 - the land verbs only

    parent = str(land.fields()["P"])
    try:
        with _registry_lock(common, wait_s=wait_s, poll_s=poll_s, argv=argv):
            card = _recovery_card(common, land)
            _landing_card(card, land)
            blocker = commit_batch.land_blocker(handle, land.op)
    except _batch_errors() as exc:
        raise _as_refusal(exc, land.op) from None
    if blocker is not None:
        raise Refusal(blocker.reason, blocker.detail)
    main = _git_text(
        main_top, "rev-parse", "--verify", "--quiet", f"{MAIN_REF}^{{commit}}"
    ).strip()
    if main != parent:
        _set_card(
            common,
            card,
            state="active",
            op=None,
            expect_op=land.op,
            wait_s=wait_s,
            poll_s=poll_s,
            argv=argv,
        )
        raise Refusal(
            "main_moved",
            f"main is at {main or 'nothing'}, not P {parent}; the card of "
            f"{land.lane} is active again and the verdict of {land.op} is void. "
            "Land again from step 1 (land prepare).",
        )
    try:
        live = commit_batch.live_task_dirt(handle, land, str(land.fields()["T"]))
    except commit_batch.rp.GitError as exc:
        raise Refusal("git_failed", str(exc)) from None
    dirty = [line for line in _dirty_lines(main_top) if line[3:] != live]
    if dirty:
        raise Refusal(
            f"main_dirty:{dirty[0][3:]}",
            f"the main tree {main_top.as_posix()} has uncommitted changes "
            f"({len(dirty)}); a land publishes only onto a clean main tree at P",
        )
    if dict(_check_carrier(top, land, Path(str(card["worktree"])))) != dict(blobs):
        raise Refusal(
            "carrier_mismatch",
            f"the carriers of {land.op} changed while publish took its leases",
        )
    try:
        if route != "grant":
            commit_batch.spend_direction(
                handle,
                str(args.session),
                str(args.message_uuid),
                str(land.identity["plan"]),
                land.op,
            )
        commit = commit_batch.land_publish(
            handle,
            land,
            act=PUBLISH_ACT,
            reserved=land.op if route == "grant" else None,
        )
    except _batch_errors() as exc:
        raise _as_refusal(exc, land.op) from None
    except commit_batch.rp.GitError as exc:
        raise Refusal("git_failed", str(exc)) from None
    _sync_and_close(top, land, handle, sync=True)
    return commit


def _cmd_land_publish(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    """``land publish``: steps 6 to 9 of design §5.5 (D:248-252, AC-785.18 to AC-785.22).

    Step 6, holding no lease while it decides: the journal (``op_unknown``) at
    ``land:ready:done`` or ``land:authorized:done`` (``land_not_ready:<phase>``);
    an approved verdict for tree(T) (``verdict_missing``); HALT (``halt``, exit
    3, nothing written); the card ``landing`` with this op, read under the
    registry lock (``card_superseded``); the carriers (``carrier_mismatch``);
    then the authority (``_authority``). With no authority it refuses
    ``needs_human_publish`` and prints the sentence; nothing is written and no
    lease or lock stays held. With authority it takes the per-op lease in one
    attempt (``op_busy``, exit 3), checks the journal again (``journal_moved``)
    and journals ``land:authorized`` with ``T`` and the carrier binding, once
    per op. Steps 7 to 9 (``_publish``) run under the main-tree lease of the
    main worktree, whatever the cwd, after HALT is checked again. The leases
    are released on every path. It ends ``land_published:<op>:<C>`` and
    ``land_closed:<op>``.
    """
    op = str(args.op)
    top, common = _repo_dirs(Path.cwd())
    land = _land_journal(top, op)
    if land is None:
        raise Refusal(
            "op_unknown",
            f"no land journal carries op {op} in {common / 'run-parameters'}",
        )
    status = land.journal[-1]["status"] if land.journal else None
    if land.phase not in (LAND_READY, LAND_AUTHORIZED) or status != "done":
        raise Refusal(
            f"land_not_ready:{land.phase}",
            f"op {op} is at {land.phase}:{status}; publish needs {LAND_READY}:done "
            "with an approved verdict",
        )
    _approved_tree(top, land)
    if _halted(common):
        print("halt")
        return EXIT_HALT
    with _registry_lock(common, wait_s=wait_s, poll_s=poll_s, argv=argv):
        card = _recovery_card(common, land)
        _landing_card(card, land)
    lane_worktree = Path(str(card["worktree"]))
    blobs = _check_carrier(top, land, lane_worktree)
    route, handle = _authority(args, top, land, blobs, lane_worktree)
    lease = _op_lease(common, op, poll_s=poll_s, argv=argv)
    if lease is None:
        return EXIT_BUSY
    try:
        again = _land_journal(top, op)
        if again is None or again.raw != land.raw:
            raise Refusal(
                "journal_moved",
                f"the journal of {op} changed while publish decided its authority; "
                "run land publish again",
            )
        if again.phase != LAND_AUTHORIZED:
            fields = again.fields()
            evidence = {
                "T": str(fields["T"]),
                "carrier": dict(cast(dict[str, str], fields["carrier"])),
            }
            _journal(again, LAND_AUTHORIZED, done=False, evidence=evidence)
            _journal(again, LAND_AUTHORIZED, done=True, evidence=evidence)
        main_top = _main_tree(top)
        main_lease = _worktree_lease(main_top, wait_s=wait_s, poll_s=poll_s, argv=argv)
        try:
            if _halted(common):
                print("halt")
                return EXIT_HALT
            commit = _publish(
                args,
                again,
                top=top,
                common=common,
                main_top=main_top,
                handle=handle,
                route=route,
                blobs=blobs,
                wait_s=wait_s,
                poll_s=poll_s,
                argv=argv,
            )
        finally:
            os_lease.release(main_lease)
    finally:
        os_lease.release(lease)
    print(f"land_published:{op}:{commit}")
    print(f"land_closed:{op}")
    return 0


def _cmd_land_prepare(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    """``land prepare`` steps 1 to 5 of design §5.5 (AC-785.13 to AC-785.17).

    Order: the message file; a first read of the journal (an existing op is
    ``op_exists``: ``land recover`` re-runs it); the per-op lease in one
    attempt (``op_busy``, exit 3); step 1 freeze (``_freeze``); step 2 rebase
    in the candidate (``_rebase``); step 3 the integration requests and T
    (``_integrate``); step 4 the kept refs (``_keep``); step 5 the gate on T
    and the report (``_ready``). Lock order D:165/166: the op lease, then the
    worktree lease, then the registry lock. The last line is
    ``land_ready:<op>:<tree of T>``.
    """
    worktree = Path(args.worktree).resolve()
    if not worktree.is_dir():
        raise Refusal("worktree_bad", f"{worktree} is not a directory")
    top, common = _repo_dirs(worktree)
    message = _land_message(_checked_message_file(args.message_file))
    op = str(args.op) if args.op else ""
    if not op:
        lane = _card_for_worktree(common, worktree.as_posix())["lane"]
        op = f"{LAND_OP_PREFIX}{lane}-{secrets.token_hex(6)}"

    def _fresh() -> None:
        if _land_journal(top, op) is not None:
            raise Refusal(
                "op_exists",
                f"land op {op} already has a journal; run lanes.py land recover "
                f"--op {op}, or land again with a new op id",
            )

    _fresh()
    lease = _op_lease(common, op, poll_s=poll_s, argv=argv)
    if lease is None:
        return EXIT_BUSY
    try:
        _fresh()
        land, card, parent, owns, mnt = _freeze(
            args,
            worktree,
            top,
            common,
            op,
            message=message,
            wait_s=wait_s,
            poll_s=poll_s,
            argv=argv,
        )
        rebased = _rebase(
            land,
            card,
            top,
            common,
            parent,
            str(args.l0),
            owns=owns,
            mnt=mnt,
            wait_s=wait_s,
            poll_s=poll_s,
            argv=argv,
        )
        integrated = _integrate(
            land,
            card,
            top,
            common,
            rebased,
            wait_s=wait_s,
            poll_s=poll_s,
            argv=argv,
        )
        objects = {"P": parent, "L0": str(args.l0), "L1": rebased, "T": integrated}
        _keep(top, land, objects)
        _ready(top, land, objects, Path(str(card["worktree"])))
    finally:
        os_lease.release(lease)
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    _, common = _repo_dirs(Path.cwd())
    lanes_dir = _lanes_dir(common)
    now = datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = []
    for path in _card_files(lanes_dir):
        try:
            card = _load_card(path)
        except (Refusal, OSError) as exc:
            reason = exc.reason if isinstance(exc, Refusal) else f"unreadable:{exc}"
            entries.append(
                {"lane": path.stem, "state": "bad", "stale": None, "error": reason}
            )
            continue
        entries.append(dict(card, stale=_is_stale(card, now)))
    halted = _halted(common)
    if args.json:
        if halted:
            print("HALT", file=sys.stderr)
        print(json.dumps(entries, indent=2))
        return 0
    if halted:
        print("HALT")
    for entry in entries:
        if entry["state"] == "bad":
            print(f"{entry['lane']} state=bad stale=unknown error={entry['error']}")
            continue
        stale = "true" if entry["stale"] else "false"
        print(
            f"{entry['lane']} state={entry['state']} stale={stale} "
            f"session={entry['session']} generation={entry['generation']} "
            f"updated={entry['updated']} worktree={entry['worktree']}"
        )
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    top, _ = _repo_dirs(Path.cwd())
    plan, _ = _plan_lane(args.plan)
    task_md = top / plan / "task.md"
    if not task_md.is_file():
        raise Refusal("no_task", f"{task_md} does not exist")
    ignorecase = _ignorecase(top)
    owns, mnt = _load_ownership(task_md, ignorecase=ignorecase)
    base = args.base
    if not base or base.startswith("-"):
        raise Refusal("base_bad", f"--base must name a commit: {base!r}")
    resolved = _git(top, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if resolved.returncode != 0:
        raise Refusal("base_bad", f"{base} is not a commit")
    base_sha = resolved.stdout.decode("ascii", "replace").strip()
    paths, renames = _changed_paths(top, base_sha)
    findings: list[str] = []
    # AC-785.2 (D:270): no linked worktree may have main checked out.
    for path, branch in _worktree_entries(top)[1:]:
        if branch == MAIN_REF:
            findings.append(f"main_reserved:{path}")
    for entry in (*owns, *mnt):
        if _through_link(top, entry):
            findings.append(f"link_path:{entry}")
    owned = [_normalize(e, ignorecase) for e in owns]
    avoided = [_normalize(e, ignorecase) for e in mnt]
    for path in paths:
        norm = _normalize(path, ignorecase)
        if _through_link(top, path):
            findings.append(f"link_path:{path}")
        elif any(_covers(entry, norm) for entry in avoided):
            findings.append(f"must_not_touch:{path}")
        elif not any(_covers(entry, norm) for entry in owned):
            findings.append(f"outside_owns:{path}")
    for old, new in renames:
        print(f"rename:{old} -> {new}")
    for line in findings:
        print(line)
    if findings:
        return EXIT_REFUSED
    print("check_ok")
    return 0


# ---------------------------------------------------------------------------
# Gates and deps (design §5.8 and §10b N-5; AC-785.29, AC-785.30, AC-785.40)
# ---------------------------------------------------------------------------

# Win32 values for the adapter's kill-on-close Job Object (AC-785.40) and the
# drained rule's process checks (AC-785.29).
_CREATE_SUSPENDED = 0x00000004
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004
_INVALID_HANDLE_VALUE = -1
_RESUME_FAILED = 0xFFFFFFFF
_STILL_ACTIVE = 259
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

if sys.platform == "win32":

    class _IoCounters(ctypes.Structure):
        """IO_COUNTERS (winnt.h)."""

        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JobBasicLimit(ctypes.Structure):
        """JOBOBJECT_BASIC_LIMIT_INFORMATION (winnt.h)."""

        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JobExtendedLimit(ctypes.Structure):
        """JOBOBJECT_EXTENDED_LIMIT_INFORMATION (winnt.h)."""

        _fields_ = [
            ("BasicLimitInformation", _JobBasicLimit),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _ThreadEntry32(ctypes.Structure):
        """THREADENTRY32 (tlhelp32.h)."""

        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    def _load_kernel32() -> ctypes.WinDLL:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, dword, boolean = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
        filetime = ctypes.POINTER(wintypes.FILETIME)
        signatures: dict[str, tuple[list[object], object]] = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], handle),
            "SetInformationJobObject": (
                [handle, ctypes.c_int, ctypes.c_void_p, dword],
                boolean,
            ),
            "AssignProcessToJobObject": ([handle, handle], boolean),
            "OpenProcess": ([dword, boolean, dword], handle),
            "GetProcessTimes": (
                [handle, filetime, filetime, filetime, filetime],
                boolean,
            ),
            "GetExitCodeProcess": ([handle, ctypes.POINTER(dword)], boolean),
            "CreateToolhelp32Snapshot": ([dword, dword], handle),
            "Thread32First": ([handle, ctypes.POINTER(_ThreadEntry32)], boolean),
            "Thread32Next": ([handle, ctypes.POINTER(_ThreadEntry32)], boolean),
            "OpenThread": ([dword, boolean, dword], handle),
            "ResumeThread": ([handle], dword),
            "CloseHandle": ([handle], boolean),
        }
        for name, (argtypes, restype) in signatures.items():
            func = getattr(k, name)
            func.argtypes = argtypes
            func.restype = restype
        return k

    _KERNEL32 = _load_kernel32()

    def _win_error(what: str) -> OSError:
        """An OSError carrying the calling thread's last Win32 error code."""
        code = ctypes.get_last_error()
        return OSError(code, f"{what} failed (Win32 error {code})")

    def _win_close(handle: int | None) -> None:
        if handle:
            _KERNEL32.CloseHandle(handle)

    def _win_times(pid: int) -> tuple[bool, int | None]:
        """``(opened, created)`` for ``pid``: the creation time in FILETIME ticks.

        ``opened`` is False when ``OpenProcess`` fails (the process is gone, or
        it cannot be opened); ``created`` is None when it opened but
        ``GetProcessTimes`` failed.
        """
        process = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            return False, None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not _KERNEL32.GetProcessTimes(
                process, *(ctypes.byref(item) for item in times)
            ):
                return True, None
            return True, (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            _win_close(process)

    def _win_alive(pid: int, created: int) -> bool:
        """The drained rule's Windows check (AC-785.29) for one workload process.

        Gone when ``OpenProcess`` fails, the creation time differs (a reused
        pid) or the exit code is not ``STILL_ACTIVE``. A process that opens
        but cannot be read counts as alive: it is never drained by a guess.
        """
        process = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            return False
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not _KERNEL32.GetProcessTimes(
                process, *(ctypes.byref(item) for item in times)
            ):
                return True
            if (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime != created:
                return False
            code = wintypes.DWORD()
            if not _KERNEL32.GetExitCodeProcess(process, ctypes.byref(code)):
                return True
            return code.value == _STILL_ACTIVE
        finally:
            _win_close(process)

    def _win_kill_job() -> int:
        """A new unnamed Job Object with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``.

        The handle has no inheritable security attributes, so only this
        process holds it; when this process dies the kernel closes it and
        ends every process in the job (AC-785.40).

        Raises:
            OSError: ``CreateJobObjectW`` or ``SetInformationJobObject`` failed.
        """
        job = _KERNEL32.CreateJobObjectW(None, None)
        if not job:
            raise _win_error("CreateJobObjectW")
        info = _JobExtendedLimit()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _KERNEL32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = _win_error("SetInformationJobObject")
            _win_close(int(job))
            raise error
        return int(job)

    def _win_job_assign(job: int, pid: int) -> None:
        """Put the still-suspended child ``pid`` in ``job``.

        Raises:
            OSError: ``OpenProcess`` or ``AssignProcessToJobObject`` failed.
        """
        process = _KERNEL32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid
        )
        if not process:
            raise _win_error("OpenProcess")
        try:
            if not _KERNEL32.AssignProcessToJobObject(job, process):
                raise _win_error("AssignProcessToJobObject")
        finally:
            _win_close(process)

    def _win_resume(pid: int) -> None:
        """Resume every thread of the suspended child ``pid``.

        A Toolhelp32 walk over the threads of ``pid`` (``CreateToolhelp32Snapshot``).

        Raises:
            OSError: the snapshot failed, the child has no thread, a
                ``ResumeThread`` failed, or no thread was suspended.
        """
        snapshot = _KERNEL32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
        # The HANDLE restype gives INVALID_HANDLE_VALUE as c_void_p(-1).value.
        if not snapshot or snapshot == ctypes.c_void_p(_INVALID_HANDLE_VALUE).value:
            raise _win_error("CreateToolhelp32Snapshot")
        threads: list[int] = []
        try:
            entry = _ThreadEntry32()
            entry.dwSize = ctypes.sizeof(_ThreadEntry32)
            more = _KERNEL32.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32OwnerProcessID == pid:
                    threads.append(int(entry.th32ThreadID))
                more = _KERNEL32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            _win_close(snapshot)
        if not threads:
            raise OSError(0, f"gate child {pid} has no thread")
        suspended = False
        for thread_id in threads:
            thread = _KERNEL32.OpenThread(_THREAD_SUSPEND_RESUME, False, thread_id)
            if not thread:
                raise _win_error("OpenThread")
            try:
                previous = _KERNEL32.ResumeThread(thread)
                if previous == _RESUME_FAILED:
                    raise _win_error("ResumeThread")
                suspended = suspended or previous >= 1
            finally:
                _win_close(thread)
        if not suspended:
            raise OSError(0, f"gate child {pid} had no suspended thread")


GateEntry = dict[str, Any]
WorkloadItem = dict[str, int]
_GATE_ARGV = ["tools/lanes.py", "gate"]
_DEPS_ARGV = ["tools/lanes.py", "deps"]


def _gate_started() -> str:
    """An entry's ``started`` text: UTC with microseconds, so two entries differ."""
    return datetime.now(timezone.utc).strftime(GATE_STARTED_FORMAT)


def _gate_lease_path(top: Path) -> Path:
    """The worktree's gate lease ``<git rev-parse --absolute-git-dir>/{{PROJECT_NAME}}-gate.lock``."""
    git_dir = Path(_git_text(top, "rev-parse", "--absolute-git-dir").strip())
    return git_dir.resolve() / GATE_LEASE_NAME


def _candidate_lane(top: Path) -> str | None:
    """The lane of the land candidate ``top`` (AC-785.40), else None.

    The candidate's git dir holds the manifest ``candidate-worktree.json``
    (kind ``land``, ``op``); the op journal names the lane, and the journal's
    candidate path must be ``top`` itself.

    Raises:
        Refusal: the journal reader's reason (``_land_journal``).
    """
    git_dir = Path(_git_text(top, "rev-parse", "--absolute-git-dir").strip())
    manifest_path = git_dir / LAND_MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Refusal(
            "gate_unreserved",
            f"cannot read the candidate manifest {manifest_path}: {exc}",
        ) from None
    if not isinstance(manifest, dict) or manifest.get("kind") != "land":
        return None
    op = manifest.get("op")
    if not isinstance(op, str) or not op:
        return None
    land = _land_journal(_main_tree(top), op)
    if land is None:
        return None
    candidate = _land_candidate_path(land).resolve().as_posix()
    if not _same_worktree(candidate, top.as_posix()):
        return None
    return str(land.lane)


def _gate_lane(
    worktree: Path, *, unreserved: str = "gate_unreserved"
) -> tuple[Path, Path, str]:
    """``(top, common, lane)``: the lane whose reserving card covers ``worktree``.

    A listed lane worktree with a reserving card that names it gives that
    card's lane; a land candidate gives its op journal's lane when that lane
    has a reserving card (AC-785.40). Nothing is written, and no lanes
    directory is created.

    Raises:
        Refusal: ``unreserved`` (default ``gate_unreserved``) for any other
            path; an unreadable card (``card_bad:<key>``); a journal reason.
    """
    path = Path(worktree).resolve()
    if not path.is_dir():
        raise Refusal(unreserved, f"{path} is not a directory")
    top, common = _repo_dirs(path)
    top = top.resolve()
    shown = top.as_posix()
    lanes_dir = _lanes_dir(common)
    if not _card_files(lanes_dir):
        raise Refusal(
            unreserved, f"no lane card in {lanes_dir}; {shown} is not a lane worktree"
        )
    reserving = [
        card for card in _all_cards(common) if card["state"] in RESERVING_STATES
    ]
    for card in reserving:
        if _same_worktree(card["worktree"], shown) and _listed(top, top):
            return top, common, str(card["lane"])
    lane = _candidate_lane(top)
    if lane is not None and any(card["lane"] == lane for card in reserving):
        return top, common, lane
    raise Refusal(
        unreserved,
        f"{shown} is neither a listed lane worktree that a reserving card names "
        "nor the land candidate of one; nothing was started",
    )


def _entry_common(entry: Mapping[str, Any]) -> Path:
    """The git common dir of a gate entry, from its lease path.

    The lease sits in the worktree's git dir; a linked worktree's git dir
    names the common dir in its ``commondir`` file (gitrepository-layout),
    and the main worktree's git dir is the common dir.

    Raises:
        Refusal: ``gate_entry`` (the entry has no lease path, or ``commondir``
            cannot be read).
    """
    lease = entry.get("lease")
    if not isinstance(lease, str) or not lease:
        raise Refusal("gate_entry", f"the gate entry {dict(entry)} has no lease path")
    git_dir = Path(lease).parent
    pointer = git_dir / "commondir"
    try:
        text = pointer.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return git_dir.resolve()
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal("gate_entry", f"cannot read {pointer}: {exc}") from None
    common = Path(text)
    return (common if common.is_absolute() else git_dir / common).resolve()


def _same_entry(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """One gate run: the same ``pid``, ``lease`` and ``started``."""
    return all(a.get(key) == b.get(key) for key in ("pid", "lease", "started"))


def _deps_claim(card: Card) -> dict[str, str] | None:
    for claim in card["claims"]:
        if not isinstance(claim, str):
            return cast(dict[str, str], claim)
    return None


def _with_deps(card: Card, state: str | None) -> list[Any]:
    """The card's claims with its deps claim set to ``state`` (None removes it)."""
    claims: list[Any] = [claim for claim in card["claims"] if isinstance(claim, str)]
    if state is not None:
        claims.append({"kind": DEPS_KIND, "state": state})
    return claims


def _deps_admission(cards: Sequence[Card], lane: str) -> None:
    """Refuse a gate registration of ``lane`` that a deps claim forbids (AC-785.30).

    A pending claim refuses every registration; an exclusive claim refuses
    every lane but its owner (the owner's worktree and its candidates).

    Raises:
        Refusal: ``deps_pending``.
    """
    for card in cards:
        if card["state"] not in RESERVING_STATES:
            continue
        claim = _deps_claim(card)
        if claim is None:
            continue
        if claim["state"] == DEPS_PENDING:
            raise Refusal(
                "deps_pending",
                f"lane {card['lane']} is draining the gates for a dependency "
                "change (its deps claim is pending); run the gate after its "
                "`lanes.py deps end`",
            )
        if card["lane"] != lane:
            raise Refusal(
                "deps_pending",
                f"lane {card['lane']} holds the exclusive deps claim; only its "
                "worktree and its land candidates run gates until its "
                "`lanes.py deps end`",
            )


def _put_locked(lanes_dir: Path, card: Card) -> None:
    """Write ``card`` to its file; the caller holds the registry lock.

    Raises:
        Refusal: ``card_bad:<key>`` or ``common_dir_unwritable``.
    """
    card = _validate_card(card)
    path = lanes_dir / f"{card['lane']}.json"
    try:
        _replace_atomically(path, (json.dumps(card, indent=2) + "\n").encode("utf-8"))
    except OSError as exc:
        raise Refusal("common_dir_unwritable", f"cannot write {path}: {exc}") from None


def _reserving_card(cards: Sequence[Card], lane: str) -> Card | None:
    for card in cards:
        if card["lane"] == lane and card["state"] in RESERVING_STATES:
            return card
    return None


def gate_register(
    worktree: Path,
    *,
    workload: Sequence[Mapping[str, int]] = (),
    wait_s: float = REGISTRY_WAIT_S,
    poll_s: float = POLL_S,
) -> GateEntry:
    """Register this process's gate run in the reserving card of ``worktree``.

    AC-785.29: the entry ``{pid, lease, started, workload}`` (``pid`` is this
    process, ``lease`` the worktree's gate lease path) is appended to the
    card's ``gates`` under the registry lock, after the deps admission check.
    The caller takes the worktree lease itself (lock order AC-785.12: the
    lease before the registry lock).

    Returns:
        The entry as written; pass it to ``gate_unregister`` and the
        ``gate_workload_*`` functions.

    Raises:
        Refusal: ``gate_unreserved``, ``deps_pending``, ``gate_entry`` (a bad
            workload item), ``registry_busy``, ``card_bad:<key>`` or
            ``common_dir_unwritable``.
    """
    top, common, lane = _gate_lane(worktree)
    entry: GateEntry = {
        "pid": os.getpid(),
        "lease": _gate_lease_path(top).as_posix(),
        "started": _gate_started(),
        "workload": [dict(item) for item in workload],
    }
    if not _is_gate_entry(entry):
        raise Refusal("gate_entry", f"invalid workload {entry['workload']}")
    with _registry_lock(
        common, wait_s=wait_s, poll_s=poll_s, argv=[*_GATE_ARGV, "register"]
    ) as lanes_dir:
        cards = _all_cards(common)
        _deps_admission(cards, lane)
        card = _reserving_card(cards, lane)
        if card is None:
            raise Refusal(
                "gate_unreserved", f"lane {lane} no longer has a reserving card"
            )
        card["gates"] = [*card["gates"], entry]
        _put_locked(lanes_dir, card)
    return entry


def _rewrite_gate(
    entry: Mapping[str, Any],
    change: Callable[[list[WorkloadItem]], list[WorkloadItem]] | None,
    *,
    wait_s: float,
    poll_s: float,
) -> list[WorkloadItem] | None:
    """Change (``change``) or remove (None) ``entry`` in the card that holds it.

    Returns:
        The new workload, or None when no card holds the entry (or it was
        removed).

    Raises:
        Refusal: ``gate_entry``, ``registry_busy``, ``card_bad:<key>`` or
            ``common_dir_unwritable``.
    """
    common = _entry_common(entry)
    if not _card_files(_lanes_dir(common)):
        return None
    with _registry_lock(
        common, wait_s=wait_s, poll_s=poll_s, argv=[*_GATE_ARGV, "update"]
    ) as lanes_dir:
        for card in _all_cards(common):
            gates: list[GateEntry] = list(card["gates"])
            for index, item in enumerate(gates):
                if not _same_entry(item, entry):
                    continue
                if change is None:
                    del gates[index]
                    result = None
                else:
                    result = change(list(item["workload"]))
                    gates[index] = dict(item, workload=result)
                card["gates"] = gates
                _put_locked(lanes_dir, card)
                return result
    return None


def gate_unregister(
    entry: Mapping[str, Any], *, wait_s: float = REGISTRY_WAIT_S, poll_s: float = POLL_S
) -> None:
    """Remove ``entry`` from whichever card holds it, under the registry lock.

    Idempotent: an entry that no card holds (already removed, or cleaned by
    a drain) is not an error (AC-785.29).

    Raises:
        Refusal: ``gate_entry``, ``registry_busy``, ``card_bad:<key>`` or
            ``common_dir_unwritable``.
    """
    _rewrite_gate(entry, None, wait_s=wait_s, poll_s=poll_s)


def gate_workload_item(pid: int) -> WorkloadItem:
    """The workload identity of the process ``pid`` (AC-785.29).

    Windows: ``{pid, created}`` (``created`` = the creation time from
    ``GetProcessTimes``, FILETIME ticks, so a reused pid never matches).
    POSIX: ``{pgid}``; the caller started ``pid`` with ``start_new_session``,
    so it leads its own process group.

    Raises:
        OSError: the process cannot be opened or its times cannot be read.
    """
    if sys.platform == "win32":
        opened, created = _win_times(pid)
        if not opened or created is None:
            raise OSError(0, f"cannot read the creation time of process {pid}")
        return {"pid": pid, "created": created}
    return {"pgid": pid}


def gate_workload_add(
    entry: GateEntry,
    item: Mapping[str, int],
    *,
    wait_s: float = REGISTRY_WAIT_S,
    poll_s: float = POLL_S,
) -> None:
    """Add ``item`` to the registered ``entry``'s workload, under the registry lock.

    ``entry["workload"]`` is updated in place to the card's new value.

    Raises:
        Refusal: ``gate_entry`` (a bad item), ``gate_unregistered`` (no card
            holds the entry), ``registry_busy``, ``card_bad:<key>`` or
            ``common_dir_unwritable``.
    """
    new = dict(item)
    if not _is_workload_item(new):
        raise Refusal("gate_entry", f"invalid workload item {new}")
    result = _rewrite_gate(
        entry, lambda current: [*current, new], wait_s=wait_s, poll_s=poll_s
    )
    if result is None:
        raise Refusal(
            "gate_unregistered",
            f"no card holds the gate entry pid {entry.get('pid')} started "
            f"{entry.get('started')}",
        )
    entry["workload"] = result


def gate_workload_remove(
    entry: GateEntry,
    item: Mapping[str, int],
    *,
    wait_s: float = REGISTRY_WAIT_S,
    poll_s: float = POLL_S,
) -> None:
    """Remove ``item`` from the registered ``entry``'s workload; idempotent.

    Raises:
        Refusal: ``gate_entry``, ``registry_busy``, ``card_bad:<key>`` or
            ``common_dir_unwritable``.
    """
    gone = dict(item)
    result = _rewrite_gate(
        entry,
        lambda current: [held for held in current if held != gone],
        wait_s=wait_s,
        poll_s=poll_s,
    )
    entry["workload"] = (
        result
        if result is not None
        else [held for held in entry.get("workload", []) if held != gone]
    )


def _lease_free(lease: str) -> bool:
    """True when nobody holds the gate lease ``lease`` (one attempt, no wait).

    A lease whose directory is gone (a removed worktree) is free. A lease
    that cannot be locked for another reason counts as held.
    """
    path = Path(lease)
    if not path.parent.is_dir():
        return True
    try:
        probe = os_lease.acquire(
            path, wait_s=0.0, body=_lock_body([*_DEPS_ARGV, "probe"])
        )
    except os_lease.Busy:
        return False
    except OSError:
        return False
    os_lease.release(probe)
    return True


def _item_alive(item: Mapping[str, int]) -> bool:
    """The drained rule's process check for one workload item (AC-785.29).

    An item of the other platform cannot be checked here and counts as alive.
    """
    if sys.platform == "win32":
        if "pid" not in item:
            return True
        return _win_alive(item["pid"], item["created"])
    if "pgid" not in item:
        return True
    try:
        os.killpg(item["pgid"], 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _drain_pass(common: Path, lane: str, *, wait_s: float, poll_s: float) -> int:
    """One drain check of every registered gate; the count still registered.

    The entries are read under the registry lock; each lease and workload is
    checked with no lock held (lock order AC-785.12); the drained entries
    are removed under the lock again. An undrained entry prints
    ``deps_wait:<lane>:<pid>``, and also ``gate_orphan:<lane>:<pid>`` when its
    lease is free while a workload process lives. With none left, the
    caller's pending claim becomes ``exclusive`` in the same lock.

    Raises:
        Refusal: ``deps_cleared`` (the claim was removed meanwhile), or a
            registry reason.
    """
    argv = [*_DEPS_ARGV, "begin"]
    with _registry_lock(common, wait_s=wait_s, poll_s=poll_s, argv=argv):
        snapshot = [
            (str(card["lane"]), dict(entry))
            for card in _all_cards(common)
            for entry in card["gates"]
        ]
    drained: list[GateEntry] = []
    for owner, entry in snapshot:
        free = _lease_free(str(entry["lease"]))
        alive = any(_item_alive(item) for item in entry["workload"])
        if free and not alive:
            drained.append(entry)
            continue
        print(f"deps_wait:{owner}:{entry['pid']}", flush=True)
        if free:
            print(f"gate_orphan:{owner}:{entry['pid']}", flush=True)
    with _registry_lock(common, wait_s=wait_s, poll_s=poll_s, argv=argv) as lanes_dir:
        cards = _all_cards(common)
        left = 0
        for card in cards:
            kept = [
                entry
                for entry in card["gates"]
                if not any(_same_entry(entry, gone) for gone in drained)
            ]
            if len(kept) != len(card["gates"]):
                card["gates"] = kept
                _put_locked(lanes_dir, card)
            left += len(kept)
        own = _reserving_card(cards, lane)
        if own is None or _deps_claim(own) is None:
            raise Refusal(
                "deps_cleared",
                f"the deps claim of lane {lane} was removed while it drained",
            )
        if left == 0:
            own["claims"] = _with_deps(own, DEPS_EXCLUSIVE)
            _put_locked(lanes_dir, own)
    return left


def _clear_deps(common: Path, lane: str, *, wait_s: float, poll_s: float) -> bool:
    """Remove the deps claim of ``lane``; True when it had one.

    Raises:
        Refusal: ``no_card`` or a registry reason.
    """
    with _registry_lock(
        common, wait_s=wait_s, poll_s=poll_s, argv=[*_DEPS_ARGV, "end"]
    ) as lanes_dir:
        own = _reserving_card(_all_cards(common), lane)
        if own is None:
            raise Refusal("no_card", f"lane {lane} has no reserving card")
        if _deps_claim(own) is None:
            return False
        own["claims"] = _with_deps(own, None)
        _put_locked(lanes_dir, own)
    return True


def deps_begin(
    worktree: Path,
    *,
    wait_s: float,
    poll_s: float,
    registry_wait_s: float = REGISTRY_WAIT_S,
) -> str:
    """The deps sequence's first half (§10b N-5, AC-785.30).

    Sets the lane's ``deps`` claim to ``pending`` (refused ``claim_reserved``
    when another reserving card holds one), then checks every registered
    gate by the drained rule until none is left, and sets ``exclusive``.
    Each check prints ``deps_wait:<lane>:<pid>`` per undrained entry.
    ``wait_s`` 0 makes one check and no sleep; a positive ``wait_s`` always
    checks again after one sleep, so a slow first check never ends the wait.
    When the monotonic time since the wait started reaches ``wait_s`` with
    gates still registered, the claim is cleared and the call refuses
    ``deps_drain_timeout:<count>``; any other failure also clears the claim.

    Returns:
        The lane that now holds the exclusive deps claim.

    Raises:
        Refusal: ``no_card``, ``claim_reserved``, ``deps_drain_timeout:<n>``,
            ``deps_cleared`` or a registry reason.
    """
    _, common, lane = _gate_lane(worktree, unreserved="no_card")
    with _registry_lock(
        common, wait_s=registry_wait_s, poll_s=poll_s, argv=[*_DEPS_ARGV, "begin"]
    ) as lanes_dir:
        cards = _all_cards(common)
        for card in cards:
            if (
                card["lane"] != lane
                and card["state"] in RESERVING_STATES
                and _deps_claim(card) is not None
            ):
                raise Refusal(
                    "claim_reserved",
                    f"lane {card['lane']} holds the deps claim; one lane changes "
                    "dependencies at a time",
                )
        own = _reserving_card(cards, lane)
        if own is None:
            raise Refusal("no_card", f"lane {lane} has no reserving card")
        own["claims"] = _with_deps(own, DEPS_PENDING)
        _put_locked(lanes_dir, own)
    start = time.monotonic()
    checks = 0
    try:
        while True:
            left = _drain_pass(common, lane, wait_s=registry_wait_s, poll_s=poll_s)
            checks += 1
            if left == 0:
                return lane
            elapsed = time.monotonic() - start
            if elapsed >= wait_s and (wait_s <= 0 or checks >= 2):
                raise Refusal(
                    f"deps_drain_timeout:{left}",
                    f"{left} gate(s) still registered after {wait_s:g} s; the deps "
                    "claim is cleared. Run deps begin again when they end.",
                )
            time.sleep(max(0.0, min(poll_s, wait_s - elapsed)))
    except BaseException:
        try:
            _clear_deps(common, lane, wait_s=registry_wait_s, poll_s=poll_s)
        except (Refusal, OSError) as exc:
            print(
                f"deps_clear_failed:{lane}: {exc}; the pending deps claim stays, "
                "run `lanes.py deps end`",
                file=sys.stderr,
                flush=True,
            )
        raise


def deps_end(
    worktree: Path, *, wait_s: float = REGISTRY_WAIT_S, poll_s: float = POLL_S
) -> tuple[str, bool]:
    """``lanes.py deps end``: clear the lane's deps claim; idempotent.

    Returns:
        ``(lane, had)``: ``had`` is True when the lane held a deps claim.

    Raises:
        Refusal: ``no_card`` or a registry reason.
    """
    _, common, lane = _gate_lane(worktree, unreserved="no_card")
    return lane, _clear_deps(common, lane, wait_s=wait_s, poll_s=poll_s)


def _child_code(code: int) -> int:
    """The adapter's exit code for the child's: a POSIX signal ``-n`` is ``128+n``."""
    return code if code >= 0 else 128 - code


def _unregister_quietly(entry: GateEntry) -> None:
    """``gate_unregister`` at the adapter's exit; a failure is printed, not raised.

    The child's exit code stays the adapter's result; a left entry is cleaned
    by the next drain (its lease is free and its workload gone).
    """
    try:
        gate_unregister(entry)
    except (Refusal, OSError) as exc:
        print(f"gate_unregister_failed: {exc}", file=sys.stderr, flush=True)


def _gate_run(worktree: Path, argv: Sequence[str], *, contain: bool = True) -> int:
    """``lanes.py gate run --worktree PATH -- ARGV...`` (AC-785.40); the child's code.

    Resolves the reserving card (``_gate_lane``) and refuses ``deps_pending``
    before it starts anything; takes the worktree's gate lease (the entry's
    ``lease``); starts ``ARGV`` with no shell and inherited stdio and cwd.
    Windows: the child starts suspended in the adapter's own kill-on-close Job
    Object, is registered with ``workload = [{pid, created}]``, then resumes;
    a job that cannot be made or assigned (or ``contain=False``, the test
    seam) prints ``gate_uncontained:<reason>`` and the run goes on. POSIX: the
    child leads its own process group; ``workload = [{pgid}]``. The entry is
    removed in a ``finally``.

    Raises:
        Refusal: ``gate_argv``, ``gate_unreserved``, ``deps_pending``,
            ``lease_busy``, ``worktree_bad`` or a registry reason.
        OSError: the child cannot start.
    """
    command = list(argv)
    if not command:
        raise Refusal("gate_argv", "gate run needs the gate's argv after --")
    top, common, lane = _gate_lane(worktree)
    with _registry_lock(
        common, wait_s=REGISTRY_WAIT_S, poll_s=POLL_S, argv=[*_GATE_ARGV, "run"]
    ):
        _deps_admission(_all_cards(common), lane)
    lease = _worktree_lease(
        top, wait_s=REGISTRY_WAIT_S, poll_s=POLL_S, argv=[*_GATE_ARGV, "run", *command]
    )
    try:
        if sys.platform == "win32":
            return _gate_run_windows(worktree, command, contain=contain)
        return _gate_run_posix(worktree, command)
    finally:
        os_lease.release(lease)


def _wait_child(proc: subprocess.Popen[bytes], entry: GateEntry) -> int:
    """Wait for the registered child; an interrupt kills it before the entry goes."""
    try:
        code = proc.wait()
    except BaseException:
        with contextlib.suppress(OSError):
            proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=30)
        _unregister_quietly(entry)
        raise
    _unregister_quietly(entry)
    return _child_code(code)


if sys.platform == "win32":

    def _gate_run_windows(worktree: Path, command: list[str], *, contain: bool) -> int:
        """The Windows half of ``_gate_run``: suspend, assign, register, resume."""
        job: int | None = None
        uncontained = "" if contain else "contain_disabled"
        if contain:
            try:
                job = _win_kill_job()
            except OSError as exc:
                uncontained = f"job_create:{exc}"
        try:
            proc = subprocess.Popen(command, creationflags=_CREATE_SUSPENDED)
        except BaseException:
            _win_close(job)
            raise
        entry: GateEntry | None = None
        try:
            if job is not None:
                try:
                    _win_job_assign(job, proc.pid)
                except OSError as exc:
                    uncontained = f"job_assign:{exc}"
                    _win_close(job)
                    job = None
            if job is None:
                print(f"gate_uncontained:{uncontained}", flush=True)
            entry = gate_register(worktree, workload=[gate_workload_item(proc.pid)])
            _win_resume(proc.pid)
        except BaseException:
            with contextlib.suppress(OSError):
                proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=30)
            if entry is not None:
                _unregister_quietly(entry)
            _win_close(job)
            raise
        try:
            return _wait_child(proc, entry)
        finally:
            _win_close(job)

else:

    def _gate_run_posix(worktree: Path, command: list[str]) -> int:
        """The POSIX half of ``_gate_run``: the child leads its own process group."""
        proc = subprocess.Popen(command, start_new_session=True)
        try:
            entry = gate_register(worktree, workload=[gate_workload_item(proc.pid)])
        except BaseException:
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=30)
            raise
        return _wait_child(proc, entry)


def _wait_bound(text: str) -> int:
    """``--wait-s``: an integer number of seconds from 0 to 3600 (AC-785.30)."""
    if not re.fullmatch(r"[0-9]+", text) or int(text) > DEPS_DRAIN_WAIT_MAX_S:
        raise argparse.ArgumentTypeError(
            f"an integer from 0 to {DEPS_DRAIN_WAIT_MAX_S}, got {text!r}"
        )
    return int(text)


def _cmd_gate_run(args: argparse.Namespace, command: Sequence[str]) -> int:
    return _gate_run(Path(args.worktree), command)


def _cmd_deps(args: argparse.Namespace, *, wait_s: float, poll_s: float) -> int:
    worktree = Path(args.worktree)
    if args.deps_command == "begin":
        lane = deps_begin(
            worktree, wait_s=float(args.wait_s), poll_s=poll_s, registry_wait_s=wait_s
        )
        print(f"deps_exclusive:{lane}")
        return 0
    lane, had = deps_end(worktree, wait_s=wait_s, poll_s=poll_s)
    print(f"deps_end:{lane}" if had else f"deps_end:{lane} (no deps claim)")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lanes.py",
        description=(
            "Lane cards: admission, heartbeat, release, ownership checks and the "
            "lane commit helper."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    claim = sub.add_parser("claim", help="admit a lane: write its active card")
    claim.add_argument("--plan", required=True)
    claim.add_argument("--worktree", required=True)
    claim.add_argument("--session")
    beat = sub.add_parser("beat", help="refresh the card's updated time")
    beat.add_argument("--plan", required=True)
    beat.add_argument("--session")
    beat.add_argument("--generation")
    release = sub.add_parser("release", help="release the card")
    which = release.add_mutually_exclusive_group(required=True)
    which.add_argument("--plan")
    which.add_argument(
        "--worktree", help="the lane worktree the card names (it may be removed)"
    )
    release.add_argument("--session")
    release.add_argument("--generation")
    release.add_argument(
        "--reset",
        action="store_true",
        help="move lane/<slug> from L0 to the closed land's C, then release "
        "(needs --worktree)",
    )
    commit = sub.add_parser(
        "commit",
        help="the lane commit helper: commit the staged change on lane/<slug>",
    )
    commit.add_argument("--worktree", required=True, help="the lane worktree")
    commit.add_argument(
        "--message-file",
        required=True,
        help=f"the commit message (UTF-8, no NUL, 1 to {MESSAGE_MAX_BYTES} bytes)",
    )
    commit.add_argument("--generation")
    land = sub.add_parser(
        "land", help="the governed land of a lane (journal in commit_batch)"
    )
    land_sub = land.add_subparsers(dest="land_command", required=True)
    recover = land_sub.add_parser(
        "recover",
        help="re-run a land op under its per-op recovery lease",
    )
    recover.add_argument(
        "--op", required=True, help="the land op id (its journal must exist)"
    )
    prepare = land_sub.add_parser(
        "prepare",
        help="land steps 1-5: freeze, rebase, integrate, keep and gate the lane; "
        "or --op ID --verdict FILE: record the verdict on the ready land",
    )
    prepare.add_argument("--worktree", help="the lane worktree")
    prepare.add_argument("--l0", type=_object_id, help="the lane tip to land (40-hex)")
    prepare.add_argument(
        "--message-file",
        help=f"the land message (UTF-8, no NUL, 1 to {MESSAGE_MAX_BYTES} bytes)",
    )
    prepare.add_argument("--op", help="the land op id (default land-<lane>-<hex>)")
    prepare.add_argument(
        "--verdict",
        help=f"a {VERDICT_SCHEMA} file for the ready land --op (bound to tree(T))",
    )
    publish = land_sub.add_parser(
        "publish",
        help="land step 6: the authority for a ready land (--grant, or "
        "--human-directed --session S --message-uuid U; neither refuses "
        "needs_human_publish)",
    )
    publish.add_argument("--op", required=True, help="the ready land op id")
    authority = publish.add_mutually_exclusive_group()
    authority.add_argument(
        "--grant",
        action="store_true",
        help=f"the lane plan's verified {PUBLISH_ACT} grant scoped to {PUBLISH_BRANCH}",
    )
    authority.add_argument(
        "--human-directed",
        action="store_true",
        help="the human's typed direction for this plan on main (commit_batch rules)",
    )
    publish.add_argument("--session", help="the session of the typed direction")
    publish.add_argument("--message-uuid", help="the typed direction's message uuid")
    listing = sub.add_parser("list", help="show every card without the registry lock")
    listing.add_argument("--json", action="store_true")
    check = sub.add_parser(
        "check", help="compare the change set with the plan's ownership"
    )
    check.add_argument("--plan", required=True)
    check.add_argument("--base", default="HEAD")
    gate = sub.add_parser("gate", help="run a gate registered in the lane card")
    gate_sub = gate.add_subparsers(dest="gate_command", required=True)
    gate_run = gate_sub.add_parser(
        "run", help="run ARGV (after --) as a registered, contained gate"
    )
    gate_run.add_argument("--worktree", required=True)
    deps = sub.add_parser("deps", help="drain the gates around a dependency change")
    deps_sub = deps.add_subparsers(dest="deps_command", required=True)
    begin = deps_sub.add_parser(
        "begin", help="set the pending deps claim, drain every gate, then exclusive"
    )
    begin.add_argument("--worktree", required=True)
    begin.add_argument(
        "--wait-s",
        type=_wait_bound,
        default=DEPS_DRAIN_WAIT_S,
        help=f"drain wait in whole seconds, 0-{DEPS_DRAIN_WAIT_MAX_S}",
    )
    end = deps_sub.add_parser("end", help="clear the lane's deps claim")
    end.add_argument("--worktree", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    wait_s: float = REGISTRY_WAIT_S,
    poll_s: float = POLL_S,
) -> int:
    """Run one lanes command; 0 ok, 1 refused or findings, 2 usage, 3 HALT or op_busy."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    gate_argv: list[str] = []
    try:
        if args_list[:2] == ["gate", "run"]:
            if "--" not in args_list:
                parser.error("gate run needs -- followed by the gate's argv")
            split = args_list.index("--")
            gate_argv = args_list[split + 1 :]
            args_list = args_list[:split]
            if not gate_argv:
                parser.error("gate run needs the gate's argv after --")
        args = parser.parse_args(args_list)
        if args.command == "release" and args.reset and args.worktree is None:
            parser.error("release --reset needs --worktree <lane worktree>")
        if args.command == "land" and args.land_command == "prepare":
            steps = (args.worktree, args.l0, args.message_file)
            if args.verdict is not None and (
                args.op is None or any(value is not None for value in steps)
            ):
                parser.error(
                    "land prepare --verdict needs --op and takes no --worktree, "
                    "--l0 or --message-file"
                )
            if args.verdict is None and any(value is None for value in steps):
                parser.error(
                    "land prepare needs --worktree, --l0 and --message-file "
                    "(or --op ID --verdict FILE)"
                )
        if args.command == "land" and args.land_command == "publish":
            named = (args.session, args.message_uuid)
            if args.human_directed and any(value is None for value in named):
                parser.error(
                    "land publish --human-directed needs --session and --message-uuid"
                )
            if not args.human_directed and any(value is not None for value in named):
                parser.error(
                    "land publish takes --session and --message-uuid only with "
                    "--human-directed"
                )
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    holder_argv = ["tools/lanes.py", *args_list]
    try:
        if args.command == "land" and sys.platform != "win32":
            raise Refusal(
                "land_unsupported_platform",
                "the governed land is Windows-only in stage 2 (the main-tree lease "
                f"is an msvcrt byte-range lock); this platform is {sys.platform}. "
                "Nothing was written.",
            )
        if args.command == "claim":
            return _cmd_claim(args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv)
        if args.command == "beat":
            return _cmd_beat(args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv)
        if args.command == "release":
            return _cmd_release(args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv)
        if args.command == "commit":
            return _cmd_commit(args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv)
        if args.command == "land" and args.land_command == "publish":
            return _cmd_land_publish(
                args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv
            )
        if args.command == "land" and args.land_command == "prepare" and args.verdict:
            return _cmd_land_verdict(
                args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv
            )
        if args.command == "land" and args.land_command == "prepare":
            return _cmd_land_prepare(
                args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv
            )
        if args.command == "land":
            return _cmd_land_recover(
                args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv
            )
        if args.command == "list":
            return _cmd_list(args)
        if args.command == "gate":
            return _cmd_gate_run(args, gate_argv)
        if args.command == "deps":
            return _cmd_deps(args, wait_s=wait_s, poll_s=poll_s)
        return _cmd_check(args)
    except Refusal as exc:
        print(f"refused: {exc.reason}")
        if exc.detail:
            print(exc.detail)
        return EXIT_REFUSED
    except OSError as exc:
        print(f"refused: io_error\n{exc}")
        return EXIT_REFUSED


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.exit(main())
