"""The commit transaction driver (R§4.5, EA-8): one packet or one batch to signed, published commits.

``python -m tools.commit_batch --repo R`` takes the grant route ``--phase plan|exec|finalize
--op <id> --packet <file> [--run <run_id>]`` or the human route ``--human-directed --session <s>
--message-uuid <u> --packet <file>``. ``agent-commit.ps1`` runs one phase of a granted op with
``--step candidate|publish|index`` and the op id in ``{{PROJECT_NAME_UPPER}}_COMMIT_GRANT`` (EA-10).

Every op journals ``started`` and ``done`` around each phase in
``<store>/ops/<plan>/<run>/<op>/op.json``: ``prepared``, ``blobs_stored``, ``candidate_built``,
``candidate_verified``, ``published``, ``index_reconciled``, ``cleanup_done`` and ``reconciled``.
A land op of ``tools/lanes.py`` (MEU-785 AC-785.11) journals in the same op store through the
same writer: ``open_land_op``, ``land_start`` / ``land_finish`` write the ``LAND_PHASES``
entries of a ``land-op/1`` record, and ``land_journal`` reads one back (it refuses an unknown key
``journal_schema:<key>``); ``tools/lanes.py`` never writes an op file itself.
A rerun of the same op resumes from its last record by the R§4.5 recovery table. Every packet
refusal and the reservation check happen before the op file and any Git object are written.
The driver prints one JSON object and exits 0 ``reconciled``, 1 ``refused`` / ``stopped`` /
``failed``, 2 on a usage error and 97 at the crash seam.

A human direction survives an attempt that published nothing (MEU-813): a rerun with the same
bytes on a moved base opens the flat op ``human-<uid>-r<n>``. The attempt's ``retry`` record holds
the identity, ``_select_attempt`` chooses the op under a one-driver lease, and any other case keeps
the refusal of the op it resolves to.

The lane route: ``lane_route`` reads ``.agent/lane-route.json`` of the main tree
(``LANE_ROUTE_FILE``, schema ``lane-route/1``) and is the one owner of its shape;
``tools/executor_worktree.py`` reads it through this module. When the file says ``required``,
the command line refuses ``lane_worktree`` in a linked worktree on ``lane/<slug>`` whose slug
is not ``exempt``: that lane commits with ``tools/lanes.py commit``. The tree adapter that
``tools/lanes.py land publish`` calls does not read the policy.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, TypedDict, cast

from tools import os_lease
from tools import run_parameters as rp

PACKET_SCHEMA = "commit-packet/1"
BATCH_SCHEMA = "commit-batch/1"
OP_SCHEMA = "commit-op/1"
BATCH_OP_SCHEMA = "commit-batch-op/1"
MANIFEST_SCHEMA = "candidate-worktree/1"
MANIFEST_NAME = "candidate-worktree.json"
# Every git call carries core.longpaths: a candidate under a deep candidate root can pass
# MAX_PATH on Windows, and `_git_env` drops the system config that may enable it. Git
# exports `-c` to its children (GIT_CONFIG_PARAMETERS), so hook git calls inherit it.
GIT_LONGPATHS = ("-c", "core.longpaths=true")
PACKET_KEYS = frozenset(
    {
        "schema",
        "plan",
        "branch",
        "parent",
        "message",
        "author",
        "signing_fingerprint",
        "entries",
    }
)
BATCH_KEYS = frozenset({"schema", "plan", "branch", "count", "packets"})
AUTHOR_KEYS = frozenset({"name", "email"})
FILE_KEYS = frozenset({"path", "mode", "data"})
DELETE_KEYS = frozenset({"path", "delete"})
MODES = frozenset({"100644", "100755"})
ACT_FOR_PHASE = {"plan": "plan_commit", "exec": "exec_commit", "finalize": "finalize"}
HUMAN_ACT = "human_directed"
# The lane-route policy: absent, or ``required: false``, keeps the old route.
LANE_ROUTE_FILE = ".agent/lane-route.json"
LANE_ROUTE_SCHEMA = "lane-route/1"
LANE_ROUTE_KEYS = ("schema", "required", "exempt")
LANE_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,40}")
LANE_BRANCH_PREFIX = "refs/heads/lane/"
# The human route's op is ``human-<message uuid>``; its folder holds the direction claim that
# spends the sentence once across ``commit_batch.py`` and ``lanes.py land publish`` (EA-58 (3)).
HUMAN_OP_PREFIX = "human-"
DIRECTION_CLAIM_NAME = "direction.json"
DIRECTION_CLAIM_SCHEMA = "direction-claim/1"
DIRECTION_LEASE_DIR = "direction-leases"
PUBLISH_REFUSED = "refused:publish_refused"
CANDIDATE_FAILED = "failed:candidate:"
OID_RE = re.compile(r"[0-9a-f]{40}")
DEFAULT_RUN = "interactive"
PHASES = (
    "prepared",
    "blobs_stored",
    "candidate_built",
    "candidate_verified",
    "published",
    "index_reconciled",
    "cleanup_done",
    "reconciled",
)
# The land journal (MEU-785 AC-785.11, IP boundary row "Land journal entries"): a land op of
# ``tools/lanes.py`` journals in this op store through ``_append``; there is no second journal.
LAND_OP_SCHEMA = "land-op/1"
LAND_ACT = "land"
LAND_PHASES = (
    "land:freeze",
    "land:rebase",
    "land:conflict",
    "land:integrate",
    "land:kept",
    "land:ready",
    "land:authorized",
    "published",
    "land:sync",
    "land:closed",
)
# ``published`` is written by the publication step (``_step_published``), never by ``land_start``.
LAND_WRITER_PHASES = tuple(phase for phase in LAND_PHASES if phase != "published")
LAND_RECORD_KEYS = frozenset({"schema", "identity", "journal"})
LAND_IDENTITY_KEYS = frozenset(
    {"op", "run_id", "plan", "act", "lane", "generation", "session"}
)
LAND_ENTRY_KEYS = frozenset({"phase", "status", "evidence", "identity", "seq", "ts"})
LAND_FIELDS = frozenset(
    {
        "op",
        "lane",
        "generation",
        "session",
        "P",
        "L0",
        "L1",
        "T",
        "request_ids",
        "carrier",
        "gate",
        "verdict",
        "secrets",
    }
)
LAND_OBJECT_FIELDS = frozenset({"P", "L0", "L1", "T"})
# Step 7 (AC-785.19): a land publishes on main with the message kept beside its journal;
# step 8 (AC-785.21) reads index and tree entries in chunks of this many paths.
LAND_BRANCH = "main"
LAND_MESSAGE_NAME = "message.txt"
SYNC_CHUNK = 200
# The frontmatter lines run_parameters itself writes into a plan's task.md in the main
# checkout (``run_parameters._edit_frontmatter``: bind and the stop gate). Steps 7 and 8
# treat a change confined to them in the land plan's own task.md as live carrier state.
PLANS_DIR = "docs/execution/plans"
LIVE_TASK_FIELDS = ("store_seq:", "bound_sessions:", "stop_gate:")
LAND_NESTED_KEYS = {
    "carrier": frozenset({"task", "plan", "grouping"}),
    "gate": frozenset({"tree", "result", "base"}),
    "verdict": frozenset({"tree", "verdict"}),
}
LAND_NESTED_OBJECTS = {
    "carrier": frozenset({"task", "plan", "grouping"}),
    "gate": frozenset({"tree"}),
    "verdict": frozenset({"tree"}),
}
# The publication intent and its ``done`` evidence (``_step_published``). ``standing`` is
# the message uuid of the standing grant of a standing op (R3-F1), absent on other routes.
PUBLISHED_KEYS = frozenset(
    {"repo", "ref", "ref_old", "ref_new", "op", "candidate", "standing"}
)
OBJECT_ID_RE = re.compile(r"[0-9a-f]{40}")
STEP_TARGET = {
    "candidate": "candidate_verified",
    "publish": "published",
    "index": "index_reconciled",
}
STEP_NEEDS = {
    "candidate": "blobs_stored",
    "publish": "candidate_verified",
    "index": "published",
}
CANDIDATE_ROOT_KEY = "run-parameters.candidateRoot"
DEFAULT_CANDIDATE_ROOT = "{{PROJECT_ROOT}}-wt/.candidates"
GRANT_ENV = "{{PROJECT_NAME_UPPER}}_COMMIT_GRANT"
SCRUBBED_ENV = frozenset({"{{PROJECT_NAME_UPPER}}_COMMIT_APPROVED"})
RESIDUE_ALLOWED = (
    "__pycache__/",
    ".ruff_cache/",
    ".pytest_cache/",
    "node_modules/.cache/",
)
# MEU-939 AC-939.5 (D-5): a commit names no co-author and credits no AI tool. Any co-author
# trailer refuses (a human one too); a "generated/authored with|by <AI tool>" line refuses.
# A message that only names a tool in prose ("names Claude Code") passes.
AI_NAMES = (
    "claude",
    "anthropic",
    "codex",
    "openai",
    "chatgpt",
    "gpt",
    "copilot",
    "gemini",
    "cursor",
    "devin",
    "windsurf",
    "aider",
)
_TRAILER_KEY = "co-authored" + "-by"
ATTRIBUTION_RE = re.compile(
    r"(?i)(?:\b" + re.escape(_TRAILER_KEY) + r"\s*:"
    r"|\b(?:generated|authored)\s+(?:with|by)\s+(?:the\s+)?\[?(?:"
    + "|".join(AI_NAMES)
    + r")\b)"
)
# D-5: the commit identity is a GitHub noreply address; no personal address is ever written.
NOREPLY_RE = re.compile(r"^\d+\+[A-Za-z0-9-]+@users\.noreply\.github\.com$")
IDENTITY_ENV_KEYS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
)
# The D-3 stop list: the planless op tree and the lane cards that own a foreign hunk.
PLANLESS = "none"
PLANLESS_DIR = "planless"
PLANLESS_PREFIX = "planless:"
PLANLESS_RE = re.compile(r"\bplanless:([0-9a-f]{8})\b", re.IGNORECASE)
OWNING_PLAN_STATUS = "in_progress"
OWNING_LANE_STATES = ("active", "landing")
# D-1: the plan-grant refusals that mean "this plan has no grant for the op", so the
# standing grant is asked next; every other plan-grant refusal stands.
STANDING_FALLTHROUGH = frozenset({"not_reserved", "not_granted", "binding"})
# The direction claim lifecycle (D-2): pending until the attempt settles, then spent (the
# direction made a commit) or released (it made none, so a retry may spend it).
CLAIM_PENDING = "pending"
CLAIM_RELEASED = "released"
CLAIM_SPENT = "spent"
CLAIM_STATES = frozenset({CLAIM_PENDING, CLAIM_RELEASED, CLAIM_SPENT})
LANE_LEASE_DIR = ("lanes", "ops")
LANE_LEASE_SUFFIX = ".lease"
# D-4: the land sync's snapshot of the foreign dirt in the main checkout.
SYNC_DIRT_NAME = "sync-dirt.json"
SYNC_DIRT_SCHEMA = "sync-dirt/1"
SUBJECT_RE = re.compile(r"([a-z]+)(?:\(([^)]*)\))?!?:")
GITDIR_RE = re.compile(r"gitdir: (.+)")
ZERO_OID = "0" * 40

# D-34 commit consent: a sentence that starts with "commit" after an optional lead-in.
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]*")
DIRECT_RE = re.compile(
    r"\s*(?:(?:please|ok|okay|yes|now|let'?s|go\s+ahead\s+and)\b[\s,]*)*commit\b(?P<rest>.*)",
    re.IGNORECASE | re.DOTALL,
)
# A request put as a question ("can you commit now?") directs as the plain form does.
REQUEST_RE = re.compile(
    r"\s*(?:can|could|would|will)\s+you\s+(?P<ask>.*)", re.IGNORECASE | re.DOTALL
)
# The answered turn: how many records the walk up from a direction reads at most.
MAX_ANSWER_WALK = 2000
WORD_RE = re.compile(r"[a-z']+")
NEGATORS = frozenset(
    {"not", "never", "no", "nothing", "if", "when", "once", "after", "unless", "before"}
)
# A phrase that only rules out a push ("..., with no push", "but do not push") negates
# nothing; this tool never pushes. Removed before the negator checks.
PUSH_ONLY_RE = re.compile(
    r"[\s,;]*(?:\b(?:and|but|with|then)\s+)?"
    r"(?:\bdo\s+not\b|\bdon'?t\b|\b(?:no|not|never|without)\b)\s+"
    r"(?:(?:a|any)\s+)?push(?:es|ed|ing)?\b",
    re.IGNORECASE,
)
# R4-F1: words of another sentence that withdraw or condition the direction ("No, wait.",
# "Only if the tests pass."), and the words that make a request question an alternative.
# AC-939.13: another sentence withdraws a direction only by its leading word, an opening
# conditional or a negator directly before a word of committing (``_withdrawn``).
WITHDRAW_LEADS = frozenset(
    {"no", "nope", "actually", "wait", "hold", "stop", "cancel", "nevermind"}
)
CONDITIONALS = frozenset({"if", "unless", "when", "once", "after", "before", "until"})
SOFT_LEADS = frozenset({"please", "but"})
COMMIT_NEGATORS = frozenset({"not", "never", "no"})
ALTERNATIVES = frozenset({"or", "whether"})
BRANCH_SCOPE_RE = re.compile(r"\b(on|to)\s+([A-Za-z0-9._/-]+)", re.IGNORECASE)
REPO_SCOPE_RE = re.compile(r"\bin\s+([A-Za-z0-9._-]+)", re.IGNORECASE)
PLAN_THE_RE = re.compile(r"\bthe\s+([a-z0-9-]+)\s+plan\b", re.IGNORECASE)
PLAN_NAMED_RE = re.compile(r"^\s*(?:the\s+)?plan\s+([a-z0-9-]+)", re.IGNORECASE)

Outcome = tuple[int, dict[str, Any]]


class Stopped(Exception):
    """Recovery cannot tell what happened: stop with the journal and the files kept."""


class Failed(Exception):
    """A candidate check failed; the op is terminal."""

    def __init__(self, check: str) -> None:
        super().__init__(check)
        self.check = check


# -- the shared commit checks (MEU-939 AC-939.5, D-5) -----------------------------------------
# One owner for the identity, message and secret rules: ``commit_batch.py`` itself, and later
# ``tools/lanes.py``, call these functions.


def check_message(text: str) -> None:
    """Refuse ``attribution`` when ``text`` holds a co-author trailer or credits an AI tool.

    Args:
        text: the commit message as written (the canonical form or the raw text).

    Raises:
        rp.Refusal: ``attribution`` for any ``Co-Authored-By:`` trailer, whoever it names,
            and for a "generated|authored with|by <AI tool>" credit (``AI_NAMES``).
    """
    if not isinstance(text, str):
        raise rp.Refusal("message", "not_text")
    if ATTRIBUTION_RE.search(text):
        raise rp.Refusal("attribution")


def _configured_email(top: Path) -> str:
    """The ``user.email`` that git resolves in ``top``; empty when none is set."""
    proc = _run_git(top, "config", "--get", "user.email")
    if proc.returncode not in (0, 1):
        raise rp.Refusal(
            "git_failed",
            "git config --get user.email exited "
            f"{proc.returncode}: {proc.stderr.decode('utf-8', 'replace').strip()}",
        )
    return proc.stdout.decode("utf-8", errors="replace").strip()


def check_identity(repo: Path, identity: Mapping[str, str]) -> None:
    """Refuse ``author_not_noreply`` unless the identity is the configured noreply address.

    The address must match ``NOREPLY_RE`` (a GitHub noreply with its ``<id>+`` prefix) and
    equal the repository's ``user.email``. The detail never echoes the address.

    Args:
        repo: the repository top whose ``user.email`` is the configured identity.
        identity: ``{"name": ..., "email": ...}``.

    Raises:
        rp.Refusal: ``author_not_noreply`` (detail ``pattern``, ``unconfigured`` or
            ``config_mismatch``); ``author_not_noreply:shape`` for a malformed identity;
            ``git_failed`` when git cannot read the configuration.
    """
    name = identity.get("name")
    email = identity.get("email")
    if not isinstance(name, str) or not name or not isinstance(email, str):
        raise rp.Refusal("author_not_noreply", "shape")
    if not NOREPLY_RE.match(email):
        raise rp.Refusal("author_not_noreply", "pattern")
    configured = _configured_email(Path(repo))
    if not configured:
        raise rp.Refusal("author_not_noreply", "unconfigured")
    if configured != email:
        raise rp.Refusal("author_not_noreply", "config_mismatch")


def commit_identity_env(
    env: Mapping[str, str], name: str, email: str
) -> dict[str, str]:
    """A copy of ``env`` with the four git identity variables bound to ``name`` / ``email``.

    An inherited ``GIT_AUTHOR_EMAIL`` or ``GIT_COMMITTER_EMAIL`` that differs from ``email``
    is an override that would change the recorded identity, so it refuses.

    Raises:
        rp.Refusal: ``identity_env`` with the variable name as detail; ``author_not_noreply``
            with detail ``shape`` for an empty name or email.
    """
    if not name or not email:
        raise rp.Refusal("author_not_noreply", "shape")
    for var in IDENTITY_ENV_KEYS:
        if var.endswith("_EMAIL") and var in env and env[var] != email:
            raise rp.Refusal("identity_env", var)
    # An inherited name variable is overwritten, not refused: only the address is the
    # identity rule (D-5), and the bound name is the configured one.
    bound = dict(env)
    bound.update(
        {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
    )
    return bound


def _lanes_refusal(exc: Exception) -> rp.Refusal:
    """A ``tools.lanes`` refusal of the scan helpers as ``secret_scan:<reason>``."""
    reason = str(getattr(exc, "reason", "") or type(exc).__name__)
    detail = str(getattr(exc, "detail", "") or exc)
    return rp.Refusal("secret_scan", f"{reason}: {detail}")


def secret_findings(
    top: Path,
    files: Mapping[str, bytes],
    rev: str,
    scratch_root: Path | None = None,
) -> list[str]:
    """The paths of ``files`` in which the secrets scanner finds a secret not in the baseline.

    The scanner entry, the baseline and the config rules are those of the lane land scan
    (``tools/lanes.py``, AC-827.7): the entry is ``{{PROJECT_NAME_UPPER}}_LANES_SCAN_ENTRY`` or the
    pre-commit detect-secrets hook; the baseline and the config are read from ``rev``. With
    no baseline at ``rev`` (or a config the entry needs and ``rev`` lacks) there is nothing
    to scan against, so the result is empty. The files are written to a scratch git
    repository (the hook needs one), which is removed afterwards.

    Args:
        top: the repository top that holds ``rev``.
        files: ``{repository-relative path: bytes}`` of the content to scan.
        rev: the revision whose ``.secrets.baseline`` and pre-commit config apply.
        scratch_root: the folder for the scratch repository (the system temp folder if None).

    Returns:
        The sorted unique paths with a finding (a new baseline hash counts as one).

    Raises:
        rp.Refusal: ``containment`` for a path outside the repository;
            ``secret_scan`` when the scanner, the baseline or git fails.
    """
    from tools import lanes  # noqa: PLC0415 - lanes imports this module

    for rel in files:
        if not _contained(rel):
            raise rp.Refusal("containment", rel)
    if not files:
        return []
    try:
        baseline = lanes._tree_blob(top, rev, lanes.SCAN_BASELINE)
        if baseline is None:
            return []
        before = lanes._baseline_entries(baseline, f"{lanes.SCAN_BASELINE} of {rev}")
        entry = lanes._scan_entry()
        wants_config = lanes.SCAN_CONFIG_ARG in entry
        config = lanes._tree_blob(top, rev, lanes.SCAN_CONFIG) if wants_config else None
    except lanes.Refusal as exc:
        raise _lanes_refusal(exc) from None
    if wants_config and config is None:
        return []
    if scratch_root is not None:
        scratch_root.mkdir(parents=True, exist_ok=True)
    try:
        holder = Path(
            tempfile.mkdtemp(
                prefix="commit-scan-",
                dir=None if scratch_root is None else str(scratch_root),
            )
        )
    except OSError as exc:
        raise rp.Refusal("secret_scan", f"cannot make the scan folder: {exc}") from None
    try:
        scratch = holder / "tree"
        config_file = holder / "scan-config.yaml"
        try:
            scratch.mkdir()
            for rel, data in files.items():
                target = scratch.joinpath(*rel.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            (scratch / lanes.SCAN_BASELINE).write_bytes(baseline)
            if config is not None:
                config_file.write_bytes(config)
        except OSError as exc:
            raise rp.Refusal(
                "secret_scan", f"cannot seed the scan folder: {exc}"
            ) from None
        init = _run_git(scratch, "init", "-q")
        if init.returncode != 0:
            raise rp.Refusal(
                "secret_scan",
                "git init of the scan folder failed: "
                + init.stderr.decode("utf-8", "replace").strip(),
            )
        argv = [
            config_file.as_posix() if item == lanes.SCAN_CONFIG_ARG else item
            for item in entry
        ]
        try:
            named, scanned = lanes._run_scanner(scratch, argv, sorted(files), baseline)
            found = set(named)
            if scanned != baseline:
                after = lanes._baseline_entries(scanned, "the scanned baseline")
                path, _moved = lanes._baseline_change(before, after)
                if path is not None:
                    found.add(path)
        except lanes.Refusal as exc:
            raise _lanes_refusal(exc) from None
    finally:
        shutil.rmtree(holder, ignore_errors=True)
    return sorted(found)


# -- packets (EA-8 (b), (c)) ----------------------------------------------------------------


def canonical_message(text: str) -> bytes:
    """The D-32 byte form of a commit message; ``message`` when it has none.

    CRLF becomes LF, each line loses its trailing whitespace, leading blank lines go, runs of
    blank lines collapse to one, and the message ends in exactly one LF. ``#`` lines stay.
    """
    if "\x00" in text:
        raise rp.Refusal("message", "nul")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise rp.Refusal("message", "surrogate") from exc
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if line:
            lines.append(line)
        elif lines and lines[-1]:
            lines.append("")
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        raise rp.Refusal("message", "empty")
    return ("\n".join(lines) + "\n").encode("utf-8")


@dataclass(frozen=True)
class Packet:
    """One validated ``commit-packet/1``."""

    raw: dict[str, Any]
    plan: str
    branch: str
    parent: str
    message: bytes
    author: tuple[str, str]
    fingerprint: str
    files: dict[str, tuple[str, bytes]]
    deletes: tuple[str, ...]
    paths: tuple[str, ...]
    digest: str


def _schema(ok: bool, detail: str) -> None:
    """Refuse ``packet_schema`` unless ``ok``."""
    if not ok:
        raise rp.Refusal("packet_schema", detail)


def _text(value: object) -> bool:
    """A non-empty single-line string."""
    return isinstance(value, str) and bool(value) and "\n" not in value


def _contained(path: str) -> bool:
    """A repository-relative path that stays out of ``.git`` (no drive, backslash or ``..``)."""
    if not path or "\x00" in path or not rp.REL_RE.fullmatch(path):
        return False
    parts = path.split("/")
    return all(part not in ("", ".", "..") for part in parts) and all(
        part.lower() != ".git" for part in parts
    )


def _packet_digest(value: Mapping[str, Any]) -> str:
    """The sha256 hex of the packet's canonical JSON."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return rp._sha256(data.encode("ascii"))


def _parse_packet(value: object) -> Packet:
    """Validate a packet: schema, then containment, then the message, then attribution."""
    _schema(isinstance(value, dict), "not_an_object")
    raw = cast(dict[str, Any], value)
    _schema(set(raw) == PACKET_KEYS, "keys")
    _schema(raw["schema"] == PACKET_SCHEMA, "schema")
    # MEU-939 AC-939.6: ``none`` names a planless packet (D-3 standing grant or a direction).
    _schema(raw["plan"] == PLANLESS or rp._match(rp.SLUG_RE, raw["plan"]), "plan")
    _schema(rp._match(rp.BRANCH_RE, raw["branch"]), "branch")
    _schema(rp._match(rp.ROOT_RE, raw["parent"]), "parent")
    _schema(isinstance(raw["message"], str), "message")
    author = raw["author"]
    _schema(isinstance(author, dict) and set(author) == AUTHOR_KEYS, "author")
    names = cast(dict[str, Any], author)
    _schema(
        all(
            _text(names[key]) and not set(cast(str, names[key])) & set("<>")
            for key in AUTHOR_KEYS
        ),
        "author",
    )
    _schema(_text(raw["signing_fingerprint"]), "signing_fingerprint")
    entries = raw["entries"]
    _schema(isinstance(entries, list) and bool(entries), "entries")
    files: dict[str, tuple[str, bytes]] = {}
    deletes: list[str] = []
    paths: list[str] = []
    for item in cast(list[object], entries):
        _schema(isinstance(item, dict), "entry")
        entry = cast(dict[str, Any], item)
        _schema(isinstance(entry.get("path"), str), "entry_path")
        path = cast(str, entry["path"])
        if "delete" in entry:
            _schema(set(entry) == DELETE_KEYS and entry["delete"] is True, "entry")
            deletes.append(path)
        else:
            _schema(set(entry) == FILE_KEYS, "entry")
            _schema(entry["mode"] in MODES, "entry_mode")
            _schema(isinstance(entry["data"], str), "entry_data")
            try:
                data = base64.b64decode(cast(str, entry["data"]), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise rp.Refusal("packet_schema", "entry_data") from exc
            files[path] = (cast(str, entry["mode"]), data)
        paths.append(path)
    _schema(len({path.casefold() for path in paths}) == len(paths), "duplicate_path")
    for path in paths:
        if not _contained(path):
            raise rp.Refusal("containment", path)
    message = canonical_message(cast(str, raw["message"]))
    check_message(message.decode("utf-8"))
    return Packet(
        raw=raw,
        plan=cast(str, raw["plan"]),
        branch=cast(str, raw["branch"]),
        parent=cast(str, raw["parent"]),
        message=message,
        author=(cast(str, names["name"]), cast(str, names["email"])),
        fingerprint=cast(str, raw["signing_fingerprint"]),
        files=files,
        deletes=tuple(deletes),
        paths=tuple(paths),
        digest=_packet_digest(raw),
    )


def _rank(message: bytes) -> int:
    """The COMMIT_RULE rank of a subject: test 0, feat/fix 1, docs(build-plan) 2, other 3."""
    subject = message.split(b"\n", 1)[0].decode("utf-8")
    match = SUBJECT_RE.match(subject)
    if match is None:
        return 3
    kind, scope = match.group(1), match.group(2)
    if kind == "test":
        return 0
    if kind in ("feat", "fix"):
        return 1
    if kind == "docs" and scope == "build-plan":
        return 2
    return 3


def _read_input(path: Path, batch_ok: bool) -> tuple[list[Packet], bool]:
    """The packet, or the batch's packets (when ``batch_ok``), each validated before any write."""
    data = rp._read_bytes(path)
    _schema(data is not None, "packet_file")
    try:
        value = rp._load_json(cast(bytes, data))
    except (ValueError, UnicodeDecodeError) as exc:
        raise rp.Refusal("packet_schema", "json") from exc
    _schema(isinstance(value, dict), "not_an_object")
    top = cast(dict[str, Any], value)
    if top.get("schema") != BATCH_SCHEMA:
        return [_parse_packet(top)], False
    _schema(batch_ok, "batch_phase")
    _schema(set(top) == BATCH_KEYS, "batch_keys")
    _schema(rp._match(rp.SLUG_RE, top["plan"]), "batch_plan")
    _schema(rp._match(rp.BRANCH_RE, top["branch"]), "batch_branch")
    _schema(rp._is_int(top["count"], 1), "batch_count")
    packets = top["packets"]
    _schema(isinstance(packets, list) and bool(packets), "batch_packets")
    items = cast(list[object], packets)
    if top["count"] != len(items):
        raise rp.Refusal("batch_count", f"{top['count']}!={len(items)}")
    parsed = [_parse_packet(item) for item in items]
    for packet in parsed:
        _schema(
            packet.plan == top["plan"]
            and packet.branch == top["branch"]
            and packet.parent == parsed[0].parent,
            "batch_member",
        )
    ranks = [_rank(packet.message) for packet in parsed]
    if ranks != sorted(ranks):
        raise rp.Refusal("batch_order", ",".join(str(rank) for rank in ranks))
    return parsed, True


# -- git ------------------------------------------------------------------------------------


def _run_git(
    cwd: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
    data: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run git with the scrubbed environment and long paths on; never raises on a non-zero exit."""
    return subprocess.run(  # noqa: S603 - fixed argv
        ["git", *GIT_LONGPATHS, *args],
        cwd=cwd,
        env=rp._git_env(env),
        input=data,
        capture_output=True,
        check=False,
    )


def _git_ok(
    cwd: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
    data: bytes | None = None,
) -> str:
    """Run git and return stdout as text; raise ``GitError`` with stderr on failure."""
    proc = _run_git(cwd, *args, env=env, data=data)
    if proc.returncode != 0:
        raise rp.GitError(
            f"git {' '.join(args)} failed in {cwd}: "
            + proc.stderr.decode("utf-8", errors="replace").strip()
        )
    return proc.stdout.decode("utf-8", errors="replace").rstrip("\n")


def _ref(repo: rp.Repo, branch: str) -> str:
    """The OID of ``refs/heads/<branch>``; empty when it does not exist."""
    proc = _run_git(repo.top, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    return proc.stdout.decode("ascii", errors="replace").strip()


def _entries_of(out: bytes, *, tree: bool) -> dict[str, list[dict[str, Any]]]:
    """Parse ``ls-files -s -z`` (or ``ls-tree -r -z``) into ``{path: [{mode, oid, stage}]}``."""
    found: dict[str, list[dict[str, Any]]] = {}
    for record in out.split(b"\0"):
        if not record:
            continue
        meta, _, name = record.decode("utf-8", errors="surrogateescape").partition("\t")
        parts = meta.split()
        if tree:
            if len(parts) != 3 or parts[1] != "blob":
                continue
            item = {"mode": parts[0], "oid": parts[2], "stage": 0}
        else:
            if len(parts) != 3:
                continue
            item = {"mode": parts[0], "oid": parts[1], "stage": int(parts[2])}
        found.setdefault(name, []).append(item)
    return found


def _index_entries(
    repo: rp.Repo, paths: Sequence[str]
) -> dict[str, list[dict[str, Any]]]:
    """The caller's index entries of each path (every stage; an empty list when absent)."""
    out = _run_git(
        repo.top, "--literal-pathspecs", "ls-files", "-s", "-z", "--", *paths
    )
    if out.returncode != 0:
        raise rp.GitError(out.stderr.decode("utf-8", errors="replace").strip())
    found = _entries_of(out.stdout, tree=False)
    return {path: found.get(path, []) for path in paths}


def _tree_entries(
    repo: rp.Repo, commit: str, paths: Sequence[str]
) -> dict[str, list[dict[str, Any]]]:
    """Each path's blob entry in ``commit`` (an empty list when absent)."""
    out = _run_git(
        repo.top, "--literal-pathspecs", "ls-tree", "-r", "-z", commit, "--", *paths
    )
    if out.returncode != 0:
        raise rp.GitError(out.stderr.decode("utf-8", errors="replace").strip())
    found = _entries_of(out.stdout, tree=True)
    return {path: found.get(path, []) for path in paths}


def _status(cwd: Path, *, ignored: bool) -> list[tuple[str, str, str]]:
    """``git status --porcelain=v2 -z`` as ``(kind, xy, path)``; ``kind`` is 1, 2, u, ? or !."""
    args = ["status", "--porcelain=v2", "-z", "--untracked-files=all"]
    if ignored:
        args.append("--ignored")
    proc = _run_git(cwd, *args)
    if proc.returncode != 0:
        raise rp.GitError(proc.stderr.decode("utf-8", errors="replace").strip())
    items = proc.stdout.split(b"\0")
    out: list[tuple[str, str, str]] = []
    index = 0
    while index < len(items):
        record = items[index].decode("utf-8", errors="surrogateescape")
        index += 1
        if not record:
            continue
        kind = record[0]
        if kind == "1":
            parts = record.split(" ", 8)
            out.append((kind, parts[1], parts[8]))
        elif kind == "2":
            parts = record.split(" ", 9)
            out.append((kind, parts[1], parts[9]))
            index += 1
        elif kind == "u":
            parts = record.split(" ", 10)
            out.append((kind, parts[1], parts[10]))
        elif kind in "?!":
            out.append((kind, "", record[2:]))
    return out


def _dirty(cwd: Path) -> bool:
    """The worktree differs from the index (an unstaged change, an untracked path or a conflict)."""
    return any(
        kind in "?u" or (kind in "12" and xy[1:2] != ".")
        for kind, xy, _path in _status(cwd, ignored=False)
    )


def _write_tree(cwd: Path) -> str | None:
    """The tree of the index at ``cwd``; None when it cannot be written (a conflict)."""
    proc = _run_git(cwd, "write-tree")
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("ascii", errors="replace").strip()


# -- the op file (EA-8 (f)) -----------------------------------------------------------------


@dataclass
class Op:
    """One op: its identity, its packet, its effective parent and its journal."""

    repo: rp.Repo
    op: str
    run: str
    act: str
    packet: Packet
    parent: str
    folder: Path
    candidate: Path
    record: dict[str, Any]
    reserved: str | None = None
    verified: rp.Verified | None = None
    consent: dict[str, Any] | None = None
    verify: Callable[[Op], None] | None = field(default=None, repr=False)
    # MEU-939: the uuid of the standing grant this op commits under (grant route only).
    standing: str | None = None

    @property
    def file(self) -> Path:
        return self.folder / "op.json"

    @property
    def journal(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.record["journal"])

    @property
    def manifest(self) -> dict[str, str]:
        """The candidate manifest this op writes into its candidate's git dir."""
        return {
            "schema": MANIFEST_SCHEMA,
            "kind": "candidate",
            "op": self.op,
            "run_id": self.run,
            "plan": self.packet.plan,
        }

    def evidence(self, phase: str) -> dict[str, Any]:
        """The evidence of every journal entry of one phase, merged in order."""
        merged: dict[str, Any] = {}
        for item in self.journal:
            if item["phase"] == phase and isinstance(item.get("evidence"), dict):
                merged.update(cast(dict[str, Any], item["evidence"]))
        return merged

    def done(self) -> set[str]:
        return {str(item["phase"]) for item in self.journal if item["status"] == "done"}

    @property
    def tree(self) -> str:
        return cast(str, self.evidence("blobs_stored")["tree"])

    @property
    def commit(self) -> str:
        return cast(str, self.evidence("candidate_verified")["commit"])


@dataclass
class LandOp:
    """One land op of ``tools/lanes.py``: its folder in this op store and its journal.

    ``raw`` holds the ``op.json`` bytes as read (None for an op not yet written), so a
    caller can tell whether the journal moved between two reads (AC-785.12).
    """

    repo: rp.Repo
    folder: Path
    record: dict[str, Any]
    raw: bytes | None = None

    @property
    def file(self) -> Path:
        return self.folder / "op.json"

    @property
    def journal(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.record["journal"])

    @property
    def identity(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.record["identity"])

    @property
    def op(self) -> str:
        return cast(str, self.identity["op"])

    @property
    def lane(self) -> str:
        return cast(str, self.identity["lane"])

    @property
    def generation(self) -> str:
        return cast(str, self.identity["generation"])

    @property
    def phase(self) -> str | None:
        """The phase of the last journal entry, or None for an empty journal."""
        return str(self.journal[-1]["phase"]) if self.journal else None

    def fields(self) -> dict[str, Any]:
        """The land fields: the identity, then each entry's evidence, merged in order."""
        merged: dict[str, Any] = dict(self.identity)
        for item in self.journal:
            if isinstance(item.get("evidence"), dict):
                merged.update(cast(dict[str, Any], item["evidence"]))
        return merged


def _append(
    ctx: Op | LandOp, phase: str, status: str, evidence: Mapping[str, Any]
) -> None:
    """Append one journal entry (seq = previous + 1) and rewrite ``op.json`` atomically."""
    journal = ctx.journal
    seq = int(journal[-1]["seq"]) + 1 if journal else 1
    journal.append(
        {
            "phase": phase,
            "status": status,
            "evidence": dict(evidence),
            "identity": dict(cast(dict[str, Any], ctx.record["identity"])),
            "seq": seq,
            "ts": rp._ts(ctx.repo),
        }
    )
    ctx.folder.mkdir(parents=True, exist_ok=True)
    rp._write_atomic(ctx.file, rp._json_bytes(ctx.record))


def _start(ctx: Op, phase: str, evidence: Mapping[str, Any] | None = None) -> None:
    """Journal ``<phase>:started``, then the ``started`` crash seam."""
    _append(ctx, phase, "started", evidence or {})
    rp._crash(ctx.repo, f"commit:{phase}:started")


def _effect(ctx: Op, phase: str) -> None:
    """The ``effect`` crash seam: after the side effect, before ``done``."""
    rp._crash(ctx.repo, f"commit:{phase}:effect")


def _finish(ctx: Op, phase: str, evidence: Mapping[str, Any] | None = None) -> None:
    """Journal ``<phase>:done``, then the ``done`` crash seam."""
    _append(ctx, phase, "done", evidence or {})
    rp._crash(ctx.repo, f"commit:{phase}:done")


def _fail(ctx: Op, check: str) -> None:
    """Journal a failed candidate check and end the op."""
    _append(ctx, "candidate_verified", f"failed:candidate:{check}", {"check": check})
    raise Failed(check)


def _check_name(value: str) -> None:
    """An op or run id is one safe path segment; anything else is ``containment``."""
    if not rp.SAFE_NAME_RE.fullmatch(value) or ".." in value:
        raise rp.Refusal("containment", value)


def _candidate_root(repo: rp.Repo) -> Path:
    """``run-parameters.candidateRoot``: absolute, and never a drive root or its child."""
    raw = (repo.get(CANDIDATE_ROOT_KEY) or DEFAULT_CANDIDATE_ROOT).replace("\\", "/")
    path = Path(raw)
    if not path.is_absolute() or len(path.parts) < 3:
        raise rp.Refusal("candidate_root", raw)
    return Path(rp.display_path(raw))


def _bind_parent(repo: rp.Repo, branch: str, parent: str) -> None:
    """Step 1: HEAD is on ``refs/heads/<branch>`` and that ref is the packet parent."""
    proc = _run_git(repo.top, "symbolic-ref", "-q", "HEAD")
    head = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 or head != f"refs/heads/{branch}":
        raise rp.Refusal("detached_head", head or "detached")
    current = _ref(repo, branch)
    if current != parent:
        raise rp.Refusal("parent_moved", f"{parent}!={current}")


def _op_base(repo: rp.Repo, packet: Packet, run: str) -> Path:
    """The folder that holds the ops of ``packet`` for ``run``.

    A plan packet's ops live in ``<store>/ops/<plan>/<run>/``. A planless packet (AC-939.6)
    has no plan to name its tree, so its ops live in ``<store>/ops/planless/<digest>/``, keyed
    by the packet digest: every route and every run of the same bytes meets the same folder.
    """
    if packet.plan == PLANLESS:
        return repo.store / "ops" / PLANLESS_DIR / packet.digest
    return repo.store / "ops" / packet.plan / run


def _open_op(
    repo: rp.Repo,
    *,
    op: str,
    run: str,
    act: str,
    packet: Packet,
    parent: str,
    root: Path,
    reserved: str | None,
    verified: rp.Verified | None,
    consent: dict[str, Any] | None,
    retry: dict[str, Any] | None = None,
    standing: str | None = None,
) -> Op:
    """The op's context: an existing op must carry this packet; a new op binds its parent.

    ``retry`` is the attempt record of the human route (``_select_attempt``). Only a new op
    writes it, and a sub-op after the first of a batch has none.
    """
    folder = _op_base(repo, packet, run) / op
    ctx = Op(
        repo=repo,
        op=op,
        run=run,
        act=act,
        packet=packet,
        parent=parent,
        folder=folder,
        # A batch sub-op ``<op>/<n>`` stays a direct child of the root: hooks reach ``../.agent``.
        candidate=Path(rp.display_path(root / op.replace("/", "-"))),
        record={},
        reserved=reserved,
        verified=verified,
        consent=consent,
        standing=standing,
    )
    data = rp._read_bytes(ctx.file)
    if data is not None:
        try:
            record = cast(dict[str, Any], rp._load_json(data))
            identity = cast(dict[str, Any], record["identity"])
            journal = record["journal"]
        except (ValueError, KeyError, TypeError) as exc:
            raise Stopped("op_file") from exc
        if not isinstance(journal, list) or not journal:
            raise Stopped("op_file")
        if (
            identity.get("packet_digest") != packet.digest
            or identity.get("act") != act
            or identity.get("plan") != packet.plan
        ):
            raise rp.Refusal("packet_mismatch", op)
        ctx.record = record
        ctx.candidate = Path(cast(str, record["candidate_path"]))
        ctx.parent = cast(str, ctx.evidence("prepared").get("parent", parent))
        return ctx
    # D-5 (AC-939.5): a new op commits only as the configured noreply identity. An existing
    # op keeps its packet_mismatch check above, so a changed author never reaches this line.
    check_identity(repo.top, {"name": packet.author[0], "email": packet.author[1]})
    _bind_parent(repo, packet.branch, parent)
    ctx.record = {
        "schema": OP_SCHEMA,
        "identity": {
            "op": op,
            "run_id": run,
            "plan": packet.plan,
            "act": act,
            "packet_digest": packet.digest,
        },
        "packet": packet.raw,
        "candidate_path": rp.display_path(ctx.candidate),
        "journal": [],
    }
    if retry is not None:
        ctx.record["retry"] = retry
    evidence: dict[str, Any] = {
        "message_digest": rp._sha256(packet.message),
        "parent": parent,
    }
    if consent is not None:
        ctx.record["consent"] = consent
        evidence["consent"] = consent
    _start(ctx, "prepared", evidence)
    return ctx


# -- the land journal (MEU-785 AC-785.11) ---------------------------------------------------


def _land_schema(key: str, detail: str) -> rp.Refusal:
    """The land journal reader's refusal of one key: ``journal_schema:<key>``."""
    return rp.Refusal(f"journal_schema:{key}", detail)


def _check_object_id(key: str, value: object, where: str) -> None:
    if not isinstance(value, str) or not OBJECT_ID_RE.fullmatch(value):
        raise _land_schema(key, f"{where}: {key} is not a 40-hex object id")


def _check_land_evidence(phase: str, evidence: Mapping[str, Any], where: str) -> None:
    """Every key is a land field (the publication keys for ``published``); ids are 40-hex.

    Raises:
        rp.Refusal: ``journal_schema:<key>`` for an unknown key, a nested key outside
            ``carrier``/``gate``/``verdict``, an object id that is not 40-hex, or a value
            of the wrong type.
    """
    allowed = PUBLISHED_KEYS if phase == "published" else LAND_FIELDS
    for key, value in evidence.items():
        if key not in allowed:
            raise _land_schema(key, f"{where}: unknown key")
        if phase == "published":
            continue
        if key in LAND_OBJECT_FIELDS:
            _check_object_id(key, value, where)
        elif key in LAND_NESTED_KEYS:
            if not isinstance(value, dict):
                raise _land_schema(key, f"{where}: {key} is not an object")
            for inner, inner_value in cast(dict[str, Any], value).items():
                name = f"{key}.{inner}"
                if inner not in LAND_NESTED_KEYS[key]:
                    raise _land_schema(name, f"{where}: unknown key")
                if inner in LAND_NESTED_OBJECTS[key]:
                    _check_object_id(name, inner_value, where)
        elif key == "request_ids":
            items = cast(list[object], value) if isinstance(value, list) else None
            if items is None or not all(isinstance(item, str) for item in items):
                raise _land_schema(
                    key, f"{where}: request_ids is not a list of strings"
                )
        elif not isinstance(value, str):
            raise _land_schema(key, f"{where}: {key} is not a string")


def _check_land_identity(value: object, where: str) -> dict[str, Any]:
    """The identity holds exactly the land identity keys, each a string, and act ``land``."""
    if not isinstance(value, dict):
        raise _land_schema("identity", f"{where}: identity is not an object")
    identity = cast(dict[str, Any], value)
    for key in identity:
        if key not in LAND_IDENTITY_KEYS:
            raise _land_schema(f"identity.{key}", f"{where}: unknown key")
    for key in sorted(LAND_IDENTITY_KEYS):
        if not isinstance(identity.get(key), str) or not identity[key]:
            raise _land_schema(f"identity.{key}", f"{where}: missing or not a string")
    if identity["act"] != LAND_ACT:
        raise _land_schema("identity.act", f"{where}: act is {identity['act']!r}")
    return identity


def _parse_land(repo: rp.Repo, path: Path, data: bytes) -> LandOp | None:
    """The land op in ``op.json`` bytes; None when the file is another op's (a commit op).

    Raises:
        Stopped: ``op_file`` (not JSON).
        rp.Refusal: ``journal_schema:<key>`` for a land record with an unknown or
            malformed key, in the record, its identity or any entry.
    """
    try:
        value = rp._load_json(data)
    except ValueError as exc:
        raise Stopped("op_file") from exc
    if not isinstance(value, dict):
        return None
    record = cast(dict[str, Any], value)
    if record.get("schema") != LAND_OP_SCHEMA:
        return None
    where = rp.display_path(path)
    for key in record:
        if key not in LAND_RECORD_KEYS:
            raise _land_schema(key, f"{where}: unknown key")
    identity = _check_land_identity(record.get("identity"), where)
    journal = record.get("journal")
    if not isinstance(journal, list) or not journal:
        raise _land_schema("journal", f"{where}: the journal is not a non-empty list")
    for position, raw_entry in enumerate(cast(list[object], journal), start=1):
        at = f"{where} entry {position}"
        if not isinstance(raw_entry, dict):
            raise _land_schema("journal", f"{at}: not an object")
        entry = cast(dict[str, Any], raw_entry)
        for key in entry:
            if key not in LAND_ENTRY_KEYS:
                raise _land_schema(key, f"{at}: unknown key")
        for key in ("phase", "status"):
            if not isinstance(entry.get(key), str):
                raise _land_schema(key, f"{at}: missing or not a string")
        if _check_land_identity(entry.get("identity"), at) != identity:
            raise _land_schema("identity", f"{at}: differs from the record identity")
        evidence = entry.get("evidence", {})
        if not isinstance(evidence, dict):
            raise _land_schema("evidence", f"{at}: not an object")
        _check_land_evidence(str(entry["phase"]), cast(dict[str, Any], evidence), at)
    return LandOp(repo=repo, folder=path.parent, record=record, raw=data)


def _op_files(repo: rp.Repo, op: str) -> list[Path]:
    """Every ``op.json`` of op id ``op`` in the store (any plan, any run), read only."""
    _check_name(op)
    return sorted(repo.store.glob(f"ops/*/*/{op}/op.json"))


def _find_land(repo: rp.Repo, op: str) -> LandOp | None:
    """The land op ``op``, or None when no land journal carries that id.

    Raises:
        rp.Refusal: ``containment`` (``op`` is not one safe segment), ``op_ambiguous``
            (two land journals carry the id), or ``journal_schema:<key>``.
        Stopped: ``op_file`` (an ``op.json`` that is not JSON).
    """
    found: list[LandOp] = []
    for path in _op_files(repo, op):
        data = rp._read_bytes(path)
        if data is None:
            continue
        land = _parse_land(repo, path, data)
        if land is not None:
            found.append(land)
    if len(found) > 1:
        shown = ", ".join(rp.display_path(item.file) for item in found)
        raise rp.Refusal("op_ambiguous", f"{op}: {shown}")
    return found[0] if found else None


def land_journal(path: Path, op: str) -> LandOp | None:
    """The land op ``op`` of the repository that holds ``path``; None when it has none.

    Read only: nothing is created, locked or written. The caller compares ``raw`` of two
    reads to see whether the journal moved (AC-785.12).

    Raises:
        rp.Refusal: ``disabled`` (``path`` is not in a repository), ``containment``,
            ``op_ambiguous`` or ``journal_schema:<key>``.
        Stopped: ``op_file``.
    """
    return _find_land(rp._open_repo(path), op)


def open_land_op(
    repo: rp.Repo,
    *,
    op: str,
    plan: str,
    lane: str,
    generation: str,
    session: str,
    run: str = DEFAULT_RUN,
) -> LandOp:
    """The land op ``op``: an existing land journal, or a new one that its first entry writes.

    An existing land journal must name this plan, lane and generation. A new op lives at
    ``<store>/ops/<plan>/<run>/<op>/op.json``; nothing is written until ``land_start``.

    Raises:
        rp.Refusal: ``containment`` (``op``, ``plan`` or ``run`` is not one safe segment),
            ``op_mismatch`` (the id belongs to another lane, generation or plan, or to a
            commit op), ``op_ambiguous`` or ``journal_schema:<key>``.
        Stopped: ``op_file``.
    """
    for value in (op, plan, run):
        _check_name(value)
    existing = _find_land(repo, op)
    if existing is not None:
        identity = existing.identity
        if (identity["plan"], identity["lane"], identity["generation"]) != (
            plan,
            lane,
            generation,
        ):
            raise rp.Refusal(
                "op_mismatch",
                f"{op} is the land op of lane {identity['lane']} generation "
                f"{identity['generation']} (plan {identity['plan']})",
            )
        return existing
    if _op_files(repo, op):
        raise rp.Refusal("op_mismatch", f"{op} names a commit op, not a land op")
    identity = {
        "op": op,
        "run_id": run,
        "plan": plan,
        "act": LAND_ACT,
        "lane": lane,
        "generation": generation,
        "session": session,
    }
    _check_land_identity(identity, op)
    return LandOp(
        repo=repo,
        folder=repo.store / "ops" / plan / run / op,
        record={"schema": LAND_OP_SCHEMA, "identity": identity, "journal": []},
    )


def _land_entry(
    ctx: LandOp, phase: str, status: str, evidence: Mapping[str, Any] | None
) -> None:
    """Journal one land entry through ``_append``, then the ``<phase>:<status>`` crash seam."""
    if phase not in LAND_WRITER_PHASES:
        raise ValueError(
            f"commit_batch: {phase!r} is not a land phase of the land writer "
            f"(one of {', '.join(LAND_WRITER_PHASES)})"
        )
    payload = dict(evidence or {})
    _check_land_evidence(phase, payload, f"{ctx.op} {phase}")
    _append(ctx, phase, status, payload)
    ctx.raw = rp._json_bytes(ctx.record)
    rp._crash(ctx.repo, f"{phase}:{status}")


def land_start(
    ctx: LandOp, phase: str, evidence: Mapping[str, Any] | None = None
) -> None:
    """Journal ``<phase>:started`` for a land phase, then the ``started`` crash seam.

    Raises:
        ValueError: ``phase`` is not a land writer phase (``published`` belongs to the
            publication step).
        rp.Refusal: ``journal_schema:<key>`` for evidence the reader would refuse.
    """
    _land_entry(ctx, phase, "started", evidence)


def land_finish(
    ctx: LandOp, phase: str, evidence: Mapping[str, Any] | None = None
) -> None:
    """Journal ``<phase>:done`` for a land phase, then the ``done`` crash seam.

    Raises:
        ValueError: ``phase`` is not a land writer phase.
        rp.Refusal: ``journal_schema:<key>`` for evidence the reader would refuse.
    """
    _land_entry(ctx, phase, "done", evidence)


# -- authority ------------------------------------------------------------------------------


def _reserved(
    repo: rp.Repo, plan: str, act: str, op: str, branch: str | None = None
) -> rp.Verified:
    """V-A to V-10 for the act, then ``consumed[plan][act]`` names this op: else ``not_reserved``.

    ``branch`` is the packet branch: the grant's ``scope.branch`` must equal it
    (``scope_branch_mismatch``, MEU-785 AC-785.20).
    """
    rp._gate(repo, act)
    try:
        verified = rp._verify_plan(repo, plan, act, branch=branch)
    except rp.NonAuthorizing as exc:
        raise rp.Refusal("not_reserved", exc.kind) from exc
    _store, grant = rp._store_checks(
        repo, verified, act=act, op=op, reader=False, check_consumed=False
    )
    consumed = cast(dict[str, Any], grant["consumed"]) if grant is not None else {}
    entry = cast(dict[str, Any], consumed.get(plan, {})).get(act)
    if (
        not isinstance(entry, dict)
        or cast(dict[str, Any], entry).get("op_id") != op
        or cast(dict[str, Any], entry).get("state") != "reserved"
    ):
        raise rp.Refusal("not_reserved", f"{plan}:{act}:{op}")
    return verified


def _reverify(ctx: Op) -> None:
    """Publication time: re-run V-A to V-10 and the reservation (a closure since prepared).

    A standing op re-checks the standing grant instead (``_standing_recheck``).
    """
    if ctx.standing is not None:
        _standing_recheck(ctx)
        return
    if ctx.reserved is None:
        return
    ctx.repo.refresh()
    ctx.verified = _reserved(
        ctx.repo, ctx.packet.plan, ctx.act, ctx.reserved, ctx.packet.branch
    )


def _store_or_none(repo: rp.Repo) -> rp.Store | None:
    """The store, or None when it was never created (no folder, or no ``store.json``)."""
    try:
        return rp._load_store(repo)
    except rp.Refusal as exc:
        if exc.reason == "store_missing" and exc.detail in (
            "no_folder",
            "no_store_json",
        ):
            return None
        raise


def _direction_plans(repo: rp.Repo, session: str) -> tuple[list[str], list[str]]:
    """The plans a direction may resolve to: ``(unnamed, named)`` (EA-50).

    The session's open bound plans come from the store. A ``manual`` plan is never bound
    (R§4.1 intake path 3), so an open ``manual`` plan of this repository counts as well; a
    plan without a ``run_parameters`` block (``legacy``) counts only when the message names
    it. A manual plan whose ``task.md`` says ``status: complete`` is not open, so it too counts
    only when named: the closeout commit follows the completion (R2-F1). A granted plan that
    is not bound to the session is neither: its route is ``--reserved``.
    """
    store = _store_or_none(repo)
    record = store.sessions.get(session) if store is not None else None
    bound = [
        cast(str, entry["plan"])
        for entry in cast(list[dict[str, Any]], (record or {}).get("plans", []))
        if entry["state"] in rp.OPEN_STATES
    ]
    manual: list[str] = []
    named_only: list[str] = []
    for task in rp._carrier_tasks(repo):
        plan = task.parent.name
        if plan in bound or not rp.SLUG_RE.fullmatch(plan):
            continue
        try:
            rp._load_carriers(repo, plan)
            continue
        except rp.NonAuthorizing as exc:
            kind = exc.kind
        except rp.Refusal:
            continue
        try:
            meta = rp._frontmatter(rp._carrier_text(repo, task) or "")
        except rp.Refusal:
            continue
        complete = (meta or {}).get("status") == "complete"
        (manual if kind == "manual" and not complete else named_only).append(plan)
    return bound + manual, bound + manual + named_only


def _answered_plans(
    repo: rp.Repo, session: str, uid: str, plans: list[str]
) -> list[str] | None:
    """The plans named by the assistant turn that the direction ``uid`` answers.

    From the direction up its parents, past tool results, hook frames, system and attachment
    records and assistant records without text, to the nearest assistant text that names any
    of ``plans`` by its full slug; the walk stops at the previous typed human turn, a compact
    boundary, a record of another session or a broken chain. None when no text names a plan.
    """
    transcript = rp._load_transcript(repo, session)
    _raw, record = rp._typed_record(transcript, uid, session)
    cs = rp._credits_state()
    patterns = {
        plan: re.compile(
            rf"(?<![a-z0-9-]){re.escape(plan)}(?![a-z0-9-])", re.IGNORECASE
        )
        for plan in plans
    }
    visited = {uid}
    parent = record.get("parentUuid")
    for _step in range(MAX_ANSWER_WALK):
        if not isinstance(parent, str) or parent in visited:
            return None
        hits = transcript.by_uuid.get(parent, [])
        if len(hits) != 1:
            return None
        visited.add(parent)
        current = transcript.records[hits[0]]
        if (
            current.get("sessionId") != session
            or current.get("isSidechain") is not False
        ):
            return None
        kind = current.get("type")
        if kind == "system" and current.get("subtype") == "compact_boundary":
            return None
        if (
            kind == "user"
            and cs.is_human_entry(current, session) is True
            and cs.is_typed_turn(current) is True
        ):
            return None
        if kind == "assistant":
            text = rp._assistant_text(current)
            named = [plan for plan, rx in patterns.items() if rx.search(text)]
            if named:
                return named
        parent = current.get("parentUuid")
    return None


def _withdrawn(sentences: list[str], position: int, question: bool) -> bool:
    """R4-F1, narrowed by AC-939.13: whether another sentence withdraws or conditions it.

    Another sentence withdraws the direction only by its form, never by a word in its
    middle. After a scoping phrase ("do not push") and a leading "please" or "but" are
    dropped, it withdraws when its first word is a withdrawing lead ("no", "actually",
    "wait", "stop") or a conditional ("if", "unless", "until"), when it opens with
    "only if", when a negator ("not", "never", "no", a "n't" form) stands directly before a
    word of committing ("don't commit the tests"), or when it asks about committing. So
    "file an issue about commit not being auto executed" and "the tests pass if you run them
    twice" withdraw nothing. A request question also needs to open the message, to name no
    alternative ("or", "whether") and to stand as its only question.
    """
    if question:
        if position != 0:
            return True
        if set(WORD_RE.findall(sentences[position].lower())) & ALTERNATIVES:
            return True
    for index, other in enumerate(sentences):
        if index == position:
            continue
        words = WORD_RE.findall(PUSH_ONLY_RE.sub("", other).lower())
        while words and words[0] in SOFT_LEADS:
            words = words[1:]
        if not words:
            continue
        asks = other.rstrip().endswith("?")
        if question and asks:
            return True
        if words[0] in WITHDRAW_LEADS or words[0] in CONDITIONALS:
            return True
        if words[:2] == ["only", "if"]:
            return True
        commits = [word.startswith("commit") for word in words]
        if asks and any(commits):
            return True
        for word, following in zip(words, commits[1:], strict=False):
            if following and (word in COMMIT_NEGATORS or word.endswith("n't")):
                return True
    return False


def _branch_scope(repo: rp.Repo, rest: str, current: str) -> str:
    """The branch a direction names: "on <name>" always, "to <name>" only for an existing
    branch ("commit to land ..." names none); else the current branch."""
    for match in BRANCH_SCOPE_RE.finditer(rest):
        name = match.group(2)
        if match.group(1).lower() == "on":
            return name
        proc = _run_git(repo.top, "show-ref", "--verify", "-q", f"refs/heads/{name}")
        if proc.returncode == 0:
            return name
    return current


class _Scoped(Protocol):
    """What a direction is checked against: a plan and a branch (a packet, or a land)."""

    @property
    def plan(self) -> str: ...

    @property
    def branch(self) -> str: ...


@dataclass(frozen=True)
class DirectionScope:
    """The plan and branch of a land publication (MEU-785 AC-785.18): no packet exists yet."""

    plan: str
    branch: str


def human_direction(
    repo: rp.Repo, session: str, uid: str, plan: str, branch: str
) -> dict[str, Any]:
    """The ``--human-directed`` check without a packet: the consent for ``plan`` on ``branch``.

    The same rules as the commit route (D-34): ``session`` and ``uid`` are safe names, the
    record is a typed human record of that session (V-1, V-2) and ``_consent`` resolves one
    directing sentence to exactly this plan, branch and repository.

    Raises:
        rp.Refusal: ``containment`` (an unsafe name), the transcript reader's reasons, or
            ``no_commit_direction``.
    """
    _check_name(session)
    _check_name(uid)
    _raw, text = rp._human_record(repo, session, uid)
    return _consent(repo, session, uid, text, DirectionScope(plan=plan, branch=branch))


def _names_planless(rest: str, packet: _Scoped) -> bool:
    """AC-939.6: whether a direction's words name this planless packet's id.

    The id is ``planless:<digest8>``, the first eight hex of the packet digest. A land scope
    (``DirectionScope``) has no packet digest, so no direction names it.
    """
    digest = packet.digest if isinstance(packet, Packet) else ""
    if not digest:
        return False
    return any(
        match.group(1).lower() == digest[:8] for match in PLANLESS_RE.finditer(rest)
    )


def _consent(
    repo: rp.Repo, session: str, uid: str, text: str, packet: _Scoped
) -> dict[str, Any]:
    """D-34: the first directing sentence whose scope is this packet's plan, branch and repo.

    A request put as a question ("can you commit now?") counts as the plain form. A sentence
    that names no plan resolves to the plan that the answered assistant turn names, when the
    nearest naming text names exactly one (2026-10-21, the user's direction); else only to the
    one plan of ``_direction_plans`` (R§4.5 "resolves only to ... one ..., never to more").
    The direction holds only when no other sentence of the message withdraws it (R4-F1,
    ``_withdrawn``).
    """
    unnamed, named_plans = _direction_plans(repo, session)
    answered: list[str] | None | bool = False
    proc = _run_git(repo.top, "symbolic-ref", "-q", "--short", "HEAD")
    current = proc.stdout.decode("utf-8", errors="replace").strip()
    repo_name = Path(repo.main_display).name.lower()
    sentences = [
        sentence
        for sentence in (match.group(0).strip() for match in SENTENCE_RE.finditer(text))
        if WORD_RE.search(sentence.lower())
    ]
    for position, sentence in enumerate(sentences):
        clause = sentence.rstrip(".!?").strip()
        body = clause
        question = sentence.endswith("?")
        if question:
            request = REQUEST_RE.fullmatch(clause)
            if request is None:
                continue
            body = request.group("ask")
        direct = DIRECT_RE.fullmatch(PUSH_ONLY_RE.sub("", body))
        if direct is None:
            continue
        lowered = PUSH_ONLY_RE.sub("", clause).lower()
        if "n't" in lowered or set(WORD_RE.findall(lowered)) & NEGATORS:
            continue
        if _withdrawn(sentences, position, question):
            continue
        rest = direct.group("rest")
        if packet.plan == PLANLESS:
            # AC-939.6: a planless packet is named by ``planless:<digest8>``, never resolved.
            if not _names_planless(rest, packet):
                continue
            hits = [PLANLESS]
        elif (
            named := PLAN_THE_RE.search(rest) or PLAN_NAMED_RE.search(rest)
        ) is not None:
            name = named.group(1).lower()
            hits = [plan for plan in named_plans if name in (plan, plan[11:])]
        else:
            if answered is False:
                answered = _answered_plans(repo, session, uid, named_plans)
            hits = list(answered) if answered else list(unnamed)
        if len(hits) != 1 or hits[0] != packet.plan:
            continue
        branch = _branch_scope(repo, rest, current)
        if branch != packet.branch:
            continue
        place = REPO_SCOPE_RE.search(rest)
        if place is not None and place.group(1).lower() != repo_name:
            continue
        return {
            "message_uuid": uid,
            "clause": clause,
            "scope": {"plan": packet.plan, "branch": branch, "repo": repo.main_display},
        }
    raise rp.Refusal("no_commit_direction", uid)


# -- the steps (R§4.5) ----------------------------------------------------------------------


def _step_prepared(ctx: Op, resume: bool) -> None:
    """Step 1: the canonical message file in the op folder."""
    if not resume:
        _start(ctx, "prepared", {"message_digest": rp._sha256(ctx.packet.message)})
    rp._write_atomic(ctx.folder / "message.txt", ctx.packet.message)
    _effect(ctx, "prepared")
    _finish(ctx, "prepared", {"message_digest": rp._sha256(ctx.packet.message)})


def _hash_blob(repo: rp.Repo, data: bytes) -> str:
    """Store one blob with exact bytes (no filters) and return its OID."""
    return _git_ok(repo.top, "hash-object", "-w", "--no-filters", "--stdin", data=data)


def _step_blobs(ctx: Op, resume: bool) -> None:
    """Step 2: store every blob, then build tree T from P and the manifest in a temp index."""
    if not resume:
        _start(ctx, "blobs_stored")
    oids = {
        path: _hash_blob(ctx.repo, data)
        for path, (_mode, data) in ctx.packet.files.items()
    }
    temp = ctx.folder / "tree.index"
    rp._unlink(temp)
    env = {"GIT_INDEX_FILE": str(temp)}
    try:
        _git_ok(ctx.repo.top, "read-tree", ctx.parent, env=env)
        lines = [
            f"{ctx.packet.files[path][0]} {oid}\t{path}\0" for path, oid in oids.items()
        ] + [f"0 {ZERO_OID}\t{path}\0" for path in ctx.packet.deletes]
        _git_ok(
            ctx.repo.top,
            "update-index",
            "-z",
            "--index-info",
            env=env,
            data="".join(lines).encode("utf-8"),
        )
        tree = _git_ok(ctx.repo.top, "write-tree", env=env)
    finally:
        rp._unlink(temp)
    _effect(ctx, "blobs_stored")
    _finish(ctx, "blobs_stored", {"oids": oids, "tree": tree})


def _recheck_blobs(ctx: Op) -> None:
    """Every manifest OID exists (``cat-file -e``); a missing blob is stored again."""
    oids = cast(dict[str, str], ctx.evidence("blobs_stored").get("oids", {}))
    for path, oid in oids.items():
        if _run_git(ctx.repo.top, "cat-file", "-e", oid).returncode != 0:
            _hash_blob(ctx.repo, ctx.packet.files[path][1])


def _candidate_state(ctx: Op) -> str:
    """``absent``, ``owned`` (this op's manifest) or ``foreign`` (anything else at the path)."""
    path = ctx.candidate
    if not path.exists():
        return "absent"
    text = rp._read_text(path / ".git")
    match = GITDIR_RE.match(text.strip()) if text else None
    if match is None:
        return "foreign"
    gitdir = Path(match.group(1))
    if not gitdir.is_absolute():
        gitdir = path / gitdir
    data = rp._read_bytes(gitdir / MANIFEST_NAME)
    try:
        manifest = rp._load_json(data) if data else None
    except (ValueError, UnicodeDecodeError):
        manifest = None
    return "owned" if manifest == ctx.manifest else "foreign"


def _listed(repo: rp.Repo, path: Path) -> bool:
    """``path`` is a worktree in ``git worktree list``."""
    target = rp.display_path(path).lower()
    out = _git_ok(repo.top, "worktree", "list", "--porcelain")
    return any(
        rp.display_path(line[len("worktree ") :]).lower() == target
        for line in out.splitlines()
        if line.startswith("worktree ")
    )


def _remove_candidate(ctx: Op) -> None:
    """Remove an owned candidate (``worktree remove --force`` + ``prune``); idempotent."""
    path = ctx.candidate
    if _listed(ctx.repo, path):
        proc = _run_git(
            ctx.repo.top, "worktree", "remove", "--force", rp.display_path(path)
        )
        if proc.returncode != 0:
            rp._log(
                "candidate_remove_retry",
                path=str(path),
                error=proc.stderr.decode("utf-8", errors="replace").strip(),
            )
    if path.exists():
        rp._rmtree(path)
    _git_ok(ctx.repo.top, "worktree", "prune")


def _build_candidate(ctx: Op) -> None:
    """A detached worktree at P with this op's manifest, then ``read-tree --reset -u T``."""
    path = ctx.candidate
    _git_ok(ctx.repo.top, "worktree", "prune")
    path.parent.mkdir(parents=True, exist_ok=True)
    _git_ok(
        ctx.repo.top, "worktree", "add", "--detach", rp.display_path(path), ctx.parent
    )
    gitdir = Path(_git_ok(path, "rev-parse", "--absolute-git-dir"))
    rp._write_atomic(gitdir / MANIFEST_NAME, rp._json_bytes(ctx.manifest))
    _git_ok(path, "read-tree", "--reset", "-u", ctx.tree)


def _step_candidate_built(ctx: Op, resume: bool) -> None:
    """Step 3: the candidate worktree; an owned one that is not at P with index T is rebuilt."""
    _recheck_blobs(ctx)
    if not resume:
        _start(
            ctx, "candidate_built", {"candidate_path": rp.display_path(ctx.candidate)}
        )
    state = _candidate_state(ctx)
    if state == "foreign":
        raise Stopped("candidate_foreign")
    if state == "owned":
        head = _git_ok(ctx.candidate, "rev-parse", "HEAD")
        if head == ctx.parent and _write_tree(ctx.candidate) == ctx.tree:
            _effect(ctx, "candidate_built")
            _finish(ctx, "candidate_built")
            return
        _remove_candidate(ctx)
    _build_candidate(ctx)
    _effect(ctx, "candidate_built")
    _finish(ctx, "candidate_built")


def _pre_hook_check(ctx: Op) -> str | None:
    """Before any hook runs: the index is T, the worktree is the index, only manifest paths staged."""
    if _write_tree(ctx.candidate) != ctx.tree:
        return "index_tree"
    if _dirty(ctx.candidate):
        return "unstaged_drift"
    staged = _names(
        ctx.candidate, "diff-index", "--cached", "-z", "--name-only", ctx.parent
    )
    if not staged <= set(ctx.packet.paths):
        return "unlisted_staged"
    return None


def _residue_allowed(path: str) -> bool:
    """An ignored path under one of the allow-listed cache folders."""
    probe = "/" + path
    return any(f"/{allowed}" in probe + "/" for allowed in RESIDUE_ALLOWED)


def _post_hook_check(ctx: Op, commit: str) -> tuple[str | None, list[str]]:
    """After the commit: drift, ignored residue, message, parent, identity, then the signature."""
    cand = ctx.candidate
    tree = _git_ok(cand, "rev-parse", f"{commit}^{{tree}}")
    if tree != ctx.tree or _write_tree(cand) != ctx.tree or _dirty(cand):
        return "hook_drift", []
    residue = [path for kind, _xy, path in _status(cand, ignored=True) if kind == "!"]
    for path in residue:
        if not _residue_allowed(path):
            return f"ignored_residue:{path.rstrip('/')}", residue
    raw = _run_git(cand, "cat-file", "commit", commit).stdout
    if raw.split(b"\n\n", 1)[1:] != [ctx.packet.message]:
        return "message", residue
    parents = _git_ok(cand, "rev-list", "--parents", "-n", "1", commit).split()[1:]
    if parents != [ctx.parent]:
        return "parent", residue
    name, email = ctx.packet.author
    who = _git_ok(cand, "show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce", commit)
    if who.split("\x00") != [name, email, name, email]:
        return "identity", residue
    proc = _run_git(cand, "verify-commit", "--raw", commit)
    said = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    signer = _git_ok(cand, "show", "-s", "--format=%GF", commit)
    if proc.returncode != 0 or (
        ctx.packet.fingerprint not in said and signer != ctx.packet.fingerprint
    ):
        return "signature", residue
    return None, residue


def _commit_candidate(ctx: Op) -> bool:
    """``git commit -S`` in the candidate with the packet's identity and canonical message."""
    name, email = ctx.packet.author
    env = {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }
    venv = ctx.repo.top / ".venv"
    if venv.is_dir():
        # Hooks' ``uv run`` use the repository environment; never sync a candidate ``.venv``.
        env.update({"UV_PROJECT_ENVIRONMENT": str(venv), "UV_NO_SYNC": "1"})
    message = ctx.folder / "message.txt"
    if rp._read_bytes(message) != ctx.packet.message:
        rp._write_atomic(message, ctx.packet.message)
    proc = _run_git(
        ctx.candidate,
        "-c",
        "commit.cleanup=verbatim",
        "commit",
        "-q",
        "-S",
        "-F",
        str(message),
        env=env,
    )
    if proc.returncode != 0:
        rp._log(
            "candidate_commit_failed",
            op=ctx.op,
            error=proc.stderr.decode("utf-8", errors="replace").strip(),
        )
    return proc.returncode == 0


def _step_candidate_verified(ctx: Op, resume: bool) -> None:
    """Step 4: the pre-hook checks, the signed commit C, then the post-hook checks."""
    if _candidate_state(ctx) != "owned":
        raise Stopped("candidate_missing")
    if not resume:
        _start(ctx, "candidate_verified")
    head = _git_ok(ctx.candidate, "rev-parse", "HEAD")
    if head == ctx.parent:
        check = _pre_hook_check(ctx)
        if check is not None:
            _fail(ctx, check)
        if not _commit_candidate(ctx):
            _fail(ctx, "commit")
        _effect(ctx, "candidate_verified")
        head = _git_ok(ctx.candidate, "rev-parse", "HEAD")
    if _ref(ctx.repo, ctx.packet.branch) == head:
        raise Stopped("ref_holds_unverified_candidate")
    check, residue = _post_hook_check(ctx, head)
    if check is not None:
        _fail(ctx, check)
    _finish(ctx, "candidate_verified", {"commit": head, "residue": residue})


def _update_ref(ctx: Op, commit: str) -> None:
    """Under ``store.lock``: re-verify, then ``update-ref refs/heads/<b> C P``."""
    ref = f"refs/heads/{ctx.packet.branch}"
    with rp._locked(ctx.repo, ctx.run):
        _reverify(ctx)
        proc = _run_git(
            ctx.repo.top,
            "update-ref",
            "-m",
            f"commit_batch: {ctx.op}",
            ref,
            commit,
            ctx.parent,
        )
    if proc.returncode != 0:
        current = _ref(ctx.repo, ctx.packet.branch)
        _append(ctx, "published", "refused:publish_refused", {"ref": current})
        raise rp.Refusal("publish_refused", current)


def _reflog(ctx: Op) -> list[tuple[str, str]] | None:
    """``(old, new)`` of the branch reflog; None when it cannot answer (no entry reaching P)."""
    path = ctx.repo.common / "logs" / "refs" / "heads" / ctx.packet.branch
    text = rp._read_text(path)
    if text is None:
        return None
    pairs = [
        (parts[0], parts[1])
        for parts in (line.split() for line in text.splitlines())
        if len(parts) >= 2
    ]
    if not any(new == ctx.parent for _old, new in pairs):
        return None
    return pairs


def _step_published(ctx: Op, resume: bool) -> None:
    """Step 5: publish C with expected old P; a started record is resolved by the reflog."""
    commit = ctx.commit
    evidence = {"ref_old": ctx.parent, "ref_new": commit}
    if resume:
        pairs = _reflog(ctx)
        if pairs is None:
            raise Stopped("reflog_cannot_answer")
        published = (ctx.parent, commit) in pairs
        current = _ref(ctx.repo, ctx.packet.branch)
        if current == commit and published:
            _finish(ctx, "published", evidence)
            return
        if current != ctx.parent or published:
            raise Stopped("publication_unclear")
        _update_ref(ctx, commit)
        _effect(ctx, "published")
        _finish(ctx, "published", evidence)
        return
    _reverify(ctx)
    if _ref(ctx.repo, ctx.packet.branch) == commit:
        raise Stopped("ref_holds_candidate")
    # The publication intent the main ref guard reads (tools/ref_guard.py, AC-784.13).
    intent = {
        "repo": ctx.repo.common.as_posix(),
        "ref": f"refs/heads/{ctx.packet.branch}",
        "ref_old": ctx.parent,
        "ref_new": commit,
        "op": ctx.op,
        "candidate": commit,
    }
    if ctx.standing is not None:
        # R3-F1: a recovery that must still move the ref re-checks this grant.
        intent["standing"] = ctx.standing
    _start(ctx, "published", intent)
    _update_ref(ctx, commit)
    _effect(ctx, "published")
    _finish(ctx, "published", evidence)


def _classify(
    entries: list[dict[str, Any]],
    parent: list[dict[str, Any]],
    committed: list[dict[str, Any]],
) -> str:
    """The R§4.5 step-7 status of one path's index entries."""
    if any(int(item["stage"]) != 0 for item in entries):
        return "conflicted"
    if entries == committed:
        return "current"
    if entries == parent:
        return "updated"
    return "foreign_staged"


def _acquire_index_lock(ctx: Op, lock: Path, body: bytes) -> None:
    """O_EXCL ``index.lock`` with the op id; our own lock is resumed, a foreign one waited on."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    wait = rp._lock_wait(ctx.repo)
    started = time.monotonic()
    while True:
        try:
            fd = os.open(lock, flags, 0o644)
        except (FileExistsError, PermissionError):
            if rp._read_bytes(lock) == body:
                return
            if time.monotonic() - started >= wait:
                raise rp.Refusal("stale_lock", "index_lock") from None
            time.sleep(rp.LOCK_POLL_S)
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        return


def _apply_index(
    ctx: Op, index: Path, changes: Mapping[str, list[dict[str, Any]]]
) -> None:
    """Rewrite the changed paths in a copy of the index, then replace the index with it."""
    copy = index.with_name(f"{index.name}.commit-batch-{uuid.uuid4().hex}")
    current = rp._read_bytes(index)
    if current is not None:
        rp._write_durable(copy, current)
    lines = [
        f"{items[0]['mode']} {items[0]['oid']}\t{path}\0"
        if items
        else f"0 {ZERO_OID}\t{path}\0"
        for path, items in changes.items()
    ]
    try:
        _git_ok(
            ctx.repo.top,
            "update-index",
            "-z",
            "--index-info",
            env={"GIT_INDEX_FILE": str(copy)},
            data="".join(lines).encode("utf-8"),
        )
        rp._replace(copy, index)
    finally:
        rp._unlink(copy)


def _reconcile_index(ctx: Op) -> dict[str, str]:
    """Step 7 under ``index.lock``: each manifest path at P moves to C; others are reported."""
    repo = ctx.repo
    paths = list(ctx.packet.paths)
    index = Path(
        _git_ok(repo.top, "rev-parse", "--path-format=absolute", "--git-path", "index")
    )
    lock = index.with_name(index.name + ".lock")
    body = f"commit_batch {ctx.op}\n".encode()
    work = ctx.folder / "index"
    _acquire_index_lock(ctx, lock, body)
    try:
        parent = _tree_entries(repo, ctx.parent, paths)
        committed = _tree_entries(repo, ctx.commit, paths)
        current = _index_entries(repo, paths)
        before_data = rp._read_bytes(work / "before.json")
        after_data = rp._read_bytes(work / "after.json")
        changes: dict[str, list[dict[str, Any]]] = {}
        if before_data is not None and after_data is not None:
            before = cast(dict[str, Any], rp._load_json(before_data))["entries"]
            after = cast(dict[str, Any], rp._load_json(after_data))["entries"]
            statuses = {
                path: _classify(before[path], parent[path], committed[path])
                for path in paths
            }
            for path in paths:
                if current[path] == after[path]:
                    continue
                if current[path] == before[path]:
                    changes[path] = after[path]
                else:
                    statuses[path] = "foreign_staged"
        else:
            statuses = {
                path: _classify(current[path], parent[path], committed[path])
                for path in paths
            }
            planned = {
                path: committed[path] if statuses[path] == "updated" else current[path]
                for path in paths
            }
            work.mkdir(parents=True, exist_ok=True)
            rp._write_atomic(
                work / "before.json", rp._json_bytes({"op": ctx.op, "entries": current})
            )
            rp._write_atomic(
                work / "after.json", rp._json_bytes({"op": ctx.op, "entries": planned})
            )
            changes = {
                path: planned[path] for path in paths if statuses[path] == "updated"
            }
        rp._crash(repo, "commit:index_reconciled:locked")
        if changes:
            _apply_index(ctx, index, changes)
    finally:
        if rp._read_bytes(lock) == body:
            rp._unlink(lock)
    return statuses


def _step_index(ctx: Op, resume: bool) -> None:
    """Step 7: after a recorded publication the ref must still be C, then reconcile the index."""
    if not resume:
        published = ctx.evidence("published")
        if _ref(ctx.repo, ctx.packet.branch) != published.get("ref_new"):
            raise Stopped("ref_moved_after_publication")
        _start(ctx, "index_reconciled", {"paths": list(ctx.packet.paths)})
    statuses = _reconcile_index(ctx)
    _effect(ctx, "index_reconciled")
    _finish(ctx, "index_reconciled", {"index": statuses})


def _step_cleanup(ctx: Op, resume: bool) -> None:
    """Step 8: remove the candidate worktree; the evidence stays in the journal."""
    if not resume:
        _start(ctx, "cleanup_done")
    if _candidate_state(ctx) == "foreign":
        raise Stopped("candidate_foreign")
    _remove_candidate(ctx)
    _effect(ctx, "cleanup_done")
    _finish(ctx, "cleanup_done")


def _summary(ctx: Op) -> dict[str, Any]:
    """The reconciled result of an op."""
    return {
        "result": "reconciled",
        "op": ctx.op,
        "commit": ctx.commit,
        "parent": ctx.parent,
        "tree": ctx.tree,
        "index": cast(
            dict[str, str], ctx.evidence("index_reconciled").get("index", {})
        ),
    }


def _step_reconciled(ctx: Op, resume: bool) -> None:
    """The terminal record: a rerun returns it and writes nothing."""
    if not resume:
        _start(ctx, "reconciled")
    _effect(ctx, "reconciled")
    summary = _summary(ctx)
    _finish(
        ctx,
        "reconciled",
        {key: summary[key] for key in ("commit", "parent", "tree", "index")},
    )


STEPS: dict[str, Callable[[Op, bool], None]] = {
    "prepared": _step_prepared,
    "blobs_stored": _step_blobs,
    "candidate_built": _step_candidate_built,
    "candidate_verified": _step_candidate_verified,
    "published": _step_published,
    "index_reconciled": _step_index,
    "cleanup_done": _step_cleanup,
    "reconciled": _step_reconciled,
}


def _failure(ctx: Op) -> str | None:
    """The failed check of a terminal failed op, or None."""
    for item in ctx.journal:
        status = str(item["status"])
        if status.startswith("failed:candidate:"):
            return status[len("failed:candidate:") :]
    return None


def _drive(ctx: Op, until: str) -> None:
    """Run the first phase without ``done`` until ``until`` is done (a ``started`` one resumes)."""
    target = PHASES.index(until)
    while True:
        check = _failure(ctx)
        if check is not None:
            raise Failed(check)
        done = ctx.done()
        pending = next((phase for phase in PHASES if phase not in done), None)
        if pending is None or PHASES.index(pending) > target:
            return
        last = ctx.journal[-1]
        resume = last["phase"] == pending and last["status"] == "started"
        STEPS[pending](ctx, resume)


def _open_batch(
    repo: rp.Repo, *, op: str, run: str, act: str, packets: list[Packet]
) -> None:
    """The batch's own record ``<op>/batch.json``: its identity and packet count (R2-F2).

    The run's pending-op reader keeps the batch pending until ``count`` sub-ops are
    reconciled, so a crash between packets still names the batch. A rerun of the batch must
    carry the same act, plan and packets as the record, else ``packet_mismatch``.
    """
    plan = packets[0].plan
    path = _op_base(repo, packets[0], run) / op / "batch.json"
    identity = {
        "op": op,
        "run_id": run,
        "plan": plan,
        "act": act,
        "count": len(packets),
        "packet_digests": [packet.digest for packet in packets],
    }
    data = rp._read_bytes(path)
    if data is not None:
        try:
            prior = cast(dict[str, Any], rp._load_json(data))["identity"]
        except (ValueError, KeyError, TypeError) as exc:
            raise Stopped("op_file") from exc
        if prior != identity:
            raise rp.Refusal("packet_mismatch", op)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    rp._write_atomic(
        path, rp._json_bytes({"schema": BATCH_OP_SCHEMA, "identity": identity})
    )


# -- the land publication, sync and blockers (MEU-785 AC-785.19, AC-785.21) ------------------


def _claim_plan_differs(record: Mapping[str, Any], plan: str) -> bool:
    """D-MFU2-6: whether a held claim names another plan than ``plan``."""
    held = record.get("plan")
    return isinstance(held, str) and held != plan


@dataclass
class _HeldClaim:
    """One ``direction.json`` claim as read: its path, its body and its effective state."""

    path: Path
    body: dict[str, Any]
    state: str


def _held_claims(repo: rp.Repo, uid: str) -> list[_HeldClaim]:
    """Every claim of the direction ``uid`` in the op tree (one is expected).

    A claim with no ``state`` was written before the lifecycle existed (AC-939.15) and
    reads as ``spent``; so does a claim that is not a JSON object, which no act and op can
    match. A ``state`` outside ``CLAIM_STATES`` refuses.

    Raises:
        rp.Refusal: ``claim_malformed`` (``<path>:state``).
    """
    name = f"{HUMAN_OP_PREFIX}{uid}"
    found: list[_HeldClaim] = []
    for path in sorted(repo.store.glob(f"ops/*/*/{name}/{DIRECTION_CLAIM_NAME}")):
        try:
            value = rp._load_json(rp._read_bytes(path) or b"")
        except ValueError:
            value = None
        body = cast(dict[str, Any], value) if isinstance(value, dict) else {}
        state = body.get("state", CLAIM_SPENT)
        if state not in CLAIM_STATES:
            raise rp.Refusal("claim_malformed", f"{rp.display_path(path)}:state")
        found.append(_HeldClaim(path=path, body=body, state=cast(str, state)))
    return found


def _write_claim(path: Path, body: Mapping[str, Any]) -> None:
    """Write one claim atomically (the caller holds ``store.lock``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rp._write_atomic(path, rp._json_bytes(dict(body)))


def _os_lease_held(path: Path) -> bool:
    """Whether another handle holds the OS lease ``path`` (``tools/os_lease.py``).

    One attempt with no wait. A missing file is no lease, and the file is never created
    here. A free lease is released at once; its body is display data only.

    Raises:
        rp.Refusal: ``lease_unreadable`` when the file cannot be opened or locked.
    """
    if not path.is_file():
        return False
    try:
        lease = os_lease.acquire(path, wait_s=0, body=b"")
    except os_lease.Busy:
        return True
    except OSError as exc:
        raise rp.Refusal(
            "lease_unreadable", f"{rp.display_path(path)}: {exc}"
        ) from None
    os_lease.release(lease)
    return False


def _own_direction_lease(body: Mapping[str, Any]) -> bool:
    """Whether a direction lease body names this process (the caller holds the lease)."""
    return body.get("pid") == os.getpid() and body.get("host") == socket.gethostname()


def _claim_busy(repo: rp.Repo, uid: str, op: str) -> bool:
    """Whether the op of a pending claim is still live (AC-939.15, W6).

    Live means the lanes op lease ``<common>/lanes/ops/<op>.lease`` is held, or another
    process holds the direction lease ``direction-leases/<uid>.lock`` of the commit route.
    """
    if rp.SAFE_NAME_RE.fullmatch(op) and ".." not in op:
        lane_lease = repo.common.joinpath(*LANE_LEASE_DIR) / f"{op}{LANE_LEASE_SUFFIX}"
        if _os_lease_held(lane_lease):
            return True
    path = repo.store / DIRECTION_LEASE_DIR / f"{uid}.lock"
    if not _direction_lease_live(path):
        return False
    body = rp._read_lock(path) or {}
    return not _own_direction_lease(body)


def _current_branch(repo: rp.Repo) -> str | None:
    """The branch the main checkout has out, or None for a detached HEAD."""
    proc = _run_git(repo.top, "symbolic-ref", "-q", "--short", "HEAD")
    name = proc.stdout.decode("utf-8", errors="replace").strip()
    return name if proc.returncode == 0 and name else None


def _claim_landed(repo: rp.Repo, held: _HeldClaim) -> bool:
    """Whether the dead op of a pending claim made its commit (AC-939.15).

    Yes when the claim's ``target`` commit is on its branch (``branch``, else the branch
    the main checkout has out), or when a journal of the op says ``published:done``: the
    commit route's attempt folders ``human-<uid>`` and ``human-<uid>-r<n>`` beside the
    claim, or a land op folder named by the claim's ``op``.
    """
    body = held.body
    target = body.get("target")
    branch = body.get("branch")
    if not isinstance(branch, str) or not rp.SAFE_NAME_RE.fullmatch(branch):
        branch = _current_branch(repo)
    if isinstance(target, str) and OID_RE.fullmatch(target) and branch is not None:
        if _attempt_commit_reachable(repo, branch, [target]):
            return True
    folder = held.path.parent
    if _direction_published(folder.parent, folder.name):
        return True
    op = body.get("op")
    if not isinstance(op, str) or not rp.SAFE_NAME_RE.fullmatch(op) or ".." in op:
        return False
    return any(
        _direction_published(path.parent.parent, op)
        for path in repo.store.glob(f"ops/*/*/{op}/op.json")
    )


def claim_direction(
    repo: rp.Repo,
    *,
    plan: str,
    session: str,
    uid: str,
    act: str,
    op: str,
    target: str | None = None,
    branch: str | None = None,
    base: Path | None = None,
) -> None:
    """Claim the human direction ``uid`` for one act: the claim reads ``pending`` (D-2).

    The claim ``<base>/human-<uid>/direction.json`` (``base`` defaults to
    ``ops/<plan>/<session>``; a planless packet passes its digest folder) sits in the folder
    of the commit route's op ``human-<uid>``, so one typed sentence authorizes at most one
    act across ``commit_batch.py --human-directed`` and ``lanes.py land publish``. ``target``
    is the commit the op will publish and ``branch`` the branch it moves; both help a later
    run resolve a stale claim. The caller settles the claim with ``settle_direction``.

    An existing claim decides (AC-939.15):

    - ``spent``, or no ``state``: the same act, op and plan go on (a rerun reads its own
      op's state); anything else refuses ``direction_spent``. The claim is not rewritten.
    - ``released``: the same act and plan claim it again with any op; another act or plan
      refuses ``direction_spent`` and the claim keeps its act.
    - ``pending`` of the same act, op and plan: a rerun after a crash goes on.
    - ``pending`` of another op: a live op refuses ``direction_busy:<op>`` and the claim is
      left as it was; a dead op whose commit landed makes the claim ``spent`` and refuses
      ``direction_spent``; else the claim is ``released`` and the rule above applies.

    A land also refuses a direction whose commit op folder holds anything but the claim (a
    commit op spent before claims existed). The claim has no ``identity``, so the pending-op
    readers and the ref guard never list it.

    Raises:
        rp.Refusal: ``containment``; ``direction_spent``; ``direction_busy``;
            ``claim_malformed``; ``lease_unreadable``; a store lock refusal.
    """
    for value in (plan, session, uid, op):
        _check_name(value)
    name = f"{HUMAN_OP_PREFIX}{uid}"
    claim: dict[str, Any] = {
        "schema": DIRECTION_CLAIM_SCHEMA,
        "message_uuid": uid,
        "act": act,
        "op": op,
        "plan": plan,
        "session": session,
        "state": CLAIM_PENDING,
    }
    if target is not None:
        claim["target"] = target
    if branch is not None:
        claim["branch"] = branch
    with rp._locked(repo, session):
        held = _held_claims(repo, uid)
        if len(held) > 1:
            raise rp.Refusal(
                "claim_malformed", f"{uid}: {len(held)} claims in the op tree"
            )
        if act == LAND_ACT:
            used = [
                path
                for path in sorted(repo.store.glob(f"ops/*/*/{name}/*"))
                if path.name != DIRECTION_CLAIM_NAME
            ]
            if used:
                raise rp.Refusal(
                    "direction_spent",
                    f"{uid} already directed a commit ({rp.display_path(used[0])})",
                )
        if not held:
            folder = base if base is not None else repo.store / "ops" / plan / session
            _write_claim(folder / name / DIRECTION_CLAIM_NAME, claim)
            return
        current = held[0]
        body = current.body
        same_act = body.get("act") == act and not _claim_plan_differs(body, plan)
        same_op = same_act and body.get("op") == op
        spent = rp.Refusal(
            "direction_spent",
            f"{uid} already directed {body.get('act')} {body.get('op')} "
            f"({rp.display_path(current.path)})",
        )
        if current.state == CLAIM_PENDING and not same_op:
            other = str(body.get("op", ""))
            if _claim_busy(repo, uid, other):
                raise rp.Refusal("direction_busy", other)
            if _claim_landed(repo, current):
                _write_claim(current.path, {**body, "state": CLAIM_SPENT})
                raise spent
            body = {**body, "state": CLAIM_RELEASED}
            _write_claim(current.path, body)
            current = _HeldClaim(path=current.path, body=body, state=CLAIM_RELEASED)
        if current.state == CLAIM_SPENT:
            if same_op:
                return
            raise spent
        if current.state == CLAIM_RELEASED:
            if not same_act:
                raise spent
            _write_claim(current.path, claim)
            return
        # The same op's pending claim: a rerun after a crash resumes it.


def settle_direction(
    repo: rp.Repo, *, session: str, uid: str, op: str, state: str
) -> None:
    """Settle this op's ``pending`` claim of ``uid`` as ``spent`` or ``released`` (D-2).

    Only a ``pending`` claim of ``op`` changes: a claim that is already settled, or that
    names another op, is left as it is, so a rerun of a spent direction never reopens it.

    Raises:
        ValueError: ``state`` is not ``spent`` or ``released``.
        rp.Refusal: ``containment``; ``claim_malformed``; a store lock refusal.
    """
    if state not in (CLAIM_SPENT, CLAIM_RELEASED):
        raise ValueError(
            f"settle_direction: state must be spent or released, got {state!r}"
        )
    for value in (session, uid, op):
        _check_name(value)
    with rp._locked(repo, session):
        for held in _held_claims(repo, uid):
            if held.state == CLAIM_PENDING and held.body.get("op") == op:
                _write_claim(held.path, {**held.body, "state": state})


def release_direction(repo: rp.Repo, *, session: str, uid: str, op: str) -> None:
    """Release this op's ``pending`` claim of ``uid``: it made no commit (AC-939.15).

    Raises:
        rp.Refusal: ``containment``; ``claim_malformed``; a store lock refusal.
    """
    settle_direction(repo, session=session, uid=uid, op=op, state=CLAIM_RELEASED)


def _claim_direction(
    repo: rp.Repo, *, plan: str, session: str, uid: str, act: str, op: str
) -> None:
    """``claim_direction`` with the default claim folder (the land and older callers)."""
    claim_direction(repo, plan=plan, session=session, uid=uid, act=act, op=op)


def spend_direction(repo: rp.Repo, session: str, uid: str, plan: str, op: str) -> None:
    """Spend the ``--human-directed`` direction ``uid`` on the land op ``op``, once.

    ``lanes.py land publish`` calls this after ``human_direction`` and its own checks,
    before the publication: the land and the commit route share one claim per message
    uuid (``claim_direction``), so a second use of the sentence refuses on either route.
    The claim is written ``pending`` and settled ``spent`` at once; the land's own
    pending-then-settle lifecycle (``claim_direction``, ``settle_direction``) is the
    lanes side of AC-939.15.

    Raises:
        rp.Refusal: ``containment``, ``direction_spent`` or ``direction_busy``.
    """
    for value in (session, uid, plan, op):
        _check_name(value)
    claim_direction(repo, plan=plan, session=session, uid=uid, act=LAND_ACT, op=op)
    settle_direction(repo, session=session, uid=uid, op=op, state=CLAIM_SPENT)


def store_land_message(ctx: LandOp, text: str) -> None:
    """Keep the canonical form of the land's commit message beside its journal.

    ``land publish`` commits C with these bytes (``_commit_candidate`` reads the same
    ``message.txt``). The journal folder exists once the first land entry is written.

    Raises:
        rp.Refusal: ``message`` (NUL, surrogate or empty text); ``attribution`` (a
            co-author trailer or an AI credit, AC-939.5).
    """
    data = canonical_message(text)
    check_message(data.decode("utf-8"))
    path = ctx.folder / LAND_MESSAGE_NAME
    if rp._read_bytes(path) != data:
        ctx.folder.mkdir(parents=True, exist_ok=True)
        rp._write_atomic(path, data)


def _lands(repo: rp.Repo) -> list[LandOp]:
    """Every land op of the store, read only; a file that is not JSON is not a land."""
    found: list[LandOp] = []
    for path in sorted(repo.store.glob("ops/*/*/*/op.json")):
        data = rp._read_bytes(path)
        if data is None:
            continue
        try:
            land = _parse_land(repo, path, data)
        except Stopped:
            continue
        if land is not None:
            found.append(land)
    return found


def _land_has(land: LandOp, phase: str, statuses: Sequence[str]) -> bool:
    return any(
        item["phase"] == phase and item["status"] in statuses for item in land.journal
    )


def _land_open(land: LandOp) -> bool:
    """The land is between publication (``published`` started or done) and close."""
    return _land_has(land, "published", ("started", "done")) and not _land_has(
        land, "land:closed", ("done",)
    )


def land_blocker(repo: rp.Repo, op: str) -> rp.Refusal | None:
    """Why another land blocks the publication of ``op`` (AC-785.19, AC-785.21), or None.

    A land whose last entry is a refused ``land:sync`` blocks every publication
    (``sync_pending:<op>``); any other land between publication and close is
    ``land_busy:<op>``. A sync refusal wins over a busy land.
    """
    busy: rp.Refusal | None = None
    for land in _lands(repo):
        if land.op == op or not _land_open(land):
            continue
        last = land.journal[-1]
        if last["phase"] == "land:sync" and str(last["status"]).startswith("refused:"):
            return rp.Refusal(
                f"sync_pending:{land.op}",
                f"the main checkout sync of land {land.op} refused ({last['status']}); "
                f"run lanes.py land recover --op {land.op} once the path is explained",
            )
        if busy is None:
            busy = rp.Refusal(
                f"land_busy:{land.op}",
                f"land {land.op} is between publication and close; run lanes.py land "
                f"recover --op {land.op}",
            )
    return busy


def _check_sync_pending(repo: rp.Repo) -> None:
    """A published land whose main checkout is not synced blocks this publication.

    Raises:
        rp.Refusal: ``sync_pending:<op>`` (AC-785.21).
    """
    for land in _lands(repo):
        if _land_open(land) and not _land_has(land, "land:sync", ("done",)):
            raise rp.Refusal(
                f"sync_pending:{land.op}",
                f"land {land.op} is published but the main checkout is not synced; "
                f"run lanes.py land recover --op {land.op}",
            )


def _git_config(repo: rp.Repo, key: str) -> str | None:
    """One git config value of the repository, or None when it is not set."""
    proc = _run_git(repo.top, "config", "--get", key)
    if proc.returncode != 0:
        return None
    value = proc.stdout.decode("utf-8", errors="replace").strip()
    return value or None


def _ssh_fingerprint(repo: rp.Repo, key: str) -> str:
    """The ``SHA256:`` fingerprint of an ssh ``user.signingkey`` (a file or a literal key).

    Raises:
        rp.Refusal: ``signing_unconfigured`` when ``ssh-keygen`` gives no fingerprint.
    """
    literal = key[len("key::") :] if key.startswith("key::") else None
    if literal is None and key.startswith("ssh-"):
        literal = key
    if literal is not None:
        argv = ["ssh-keygen", "-l", "-E", "sha256", "-f", "-"]
        data: bytes | None = literal.encode("utf-8")
    else:
        path = Path(key).expanduser()
        if not path.is_absolute():
            path = repo.top / path
        public = path if path.name.endswith(".pub") else Path(f"{path}.pub")
        argv = [
            "ssh-keygen",
            "-l",
            "-E",
            "sha256",
            "-f",
            str(public if public.is_file() else path),
        ]
        data = None
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            argv, input=data, capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise rp.Refusal("signing_unconfigured", f"ssh-keygen: {exc}") from exc
    out = proc.stdout.decode("utf-8", errors="replace").split()
    token = next((part for part in out if part.startswith("SHA256:")), None)
    if proc.returncode != 0 or token is None:
        raise rp.Refusal(
            "signing_unconfigured",
            "gpg.format is ssh but ssh-keygen gives no fingerprint for user.signingkey",
        )
    return token


def _signing_identity(repo: rp.Repo) -> tuple[tuple[str, str], str]:
    """The author (``user.name``, ``user.email``) and signing fingerprint of a land's C.

    The land has no packet, so C carries the main repository's configured identity and
    key; ``_post_hook_check`` then checks C against them as it checks a packet's.

    Raises:
        rp.Refusal: ``signing_unconfigured`` naming each missing key.
    """
    name = _git_config(repo, "user.name")
    email = _git_config(repo, "user.email")
    key = _git_config(repo, "user.signingkey")
    if name is None or email is None or key is None:
        missing = [
            label
            for label, value in (
                ("user.name", name),
                ("user.email", email),
                ("user.signingkey", key),
            )
            if value is None
        ]
        raise rp.Refusal("signing_unconfigured", ", ".join(missing))
    if (_git_config(repo, "gpg.format") or "openpgp").lower() != "ssh":
        return (name, email), key
    return (name, email), _ssh_fingerprint(repo, key)


@dataclass
class _LandCandidate(Op):
    """The commit_batch tree adapter for a land (AC-785.19): an ``Op`` fed by T, not a packet.

    It journals into the land's own record (``record`` is the land journal), so the
    ``published`` intent the ref guard reads is the land's. ``tree`` is tree(T) and
    ``commit`` is the verified C; the candidate steps read them through these properties.
    """

    land_tree: str = ""
    land_commit: str = ""

    @property
    def tree(self) -> str:
        return self.land_tree

    @property
    def commit(self) -> str:
        return self.land_commit


def _names(cwd: Path, *args: str) -> set[str]:
    """The NUL-separated path names that one ``git`` name listing prints."""
    proc = _run_git(cwd, *args)
    if proc.returncode != 0:
        raise rp.GitError(
            f"git {' '.join(args)} failed in {cwd}: "
            + proc.stderr.decode("utf-8", errors="replace").strip()
        )
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in proc.stdout.split(b"\0")
        if item
    }


def _land_context(
    repo: rp.Repo,
    land: LandOp,
    *,
    act: str,
    reserved: str | None,
    standing: str | None = None,
) -> _LandCandidate:
    """The tree-adapter ``Op`` of a land: its packet, candidate path and journal record.

    ``standing`` is the message uuid of the standing grant that authorizes the land, so
    publication re-checks that grant (``_reverify``); None on the other routes.

    Raises:
        rp.Refusal: ``message`` (no stored message) or ``signing_unconfigured``.
    """
    fields = land.fields()
    parent = str(fields["P"])
    integrated = str(fields["T"])
    message = rp._read_bytes(land.folder / LAND_MESSAGE_NAME)
    if not message:
        raise rp.Refusal("message", f"land {land.op} has no stored commit message")
    author, fingerprint = _signing_identity(repo)
    tree = _git_ok(repo.top, "rev-parse", f"{integrated}^{{tree}}")
    paths = _names(
        repo.top, "diff-tree", "-r", "-z", "--no-renames", "--name-only", parent, tree
    )
    packet = Packet(
        raw={},
        plan=str(land.identity["plan"]),
        branch=LAND_BRANCH,
        parent=parent,
        message=message,
        author=author,
        fingerprint=fingerprint,
        files={},
        deletes=(),
        paths=tuple(sorted(paths)),
        digest="",
    )
    return _LandCandidate(
        repo=repo,
        op=land.op,
        run=str(land.identity["run_id"]),
        act=act,
        packet=packet,
        parent=parent,
        folder=land.folder,
        candidate=Path(rp.display_path(_candidate_root(repo) / land.op)),
        record=land.record,
        reserved=reserved,
        standing=standing,
        land_tree=tree,
    )


def land_publish(
    repo: rp.Repo,
    land: LandOp,
    *,
    act: str,
    reserved: str | None,
    standing: str | None = None,
) -> str:
    """Step 7 (AC-785.19): commit tree(T) on P in a candidate and publish it as C on main.

    ``repo`` is the authority handle of the main repository. The steps are the commit
    route's: ``_build_candidate`` (a detached worktree at P, index and files at T), the
    pre-hook checks, ``git commit -S`` with the stored message, the post-hook checks
    (``hook_drift`` when a hook changes the tree), then ``_step_published``: the intent
    ``{repo, ref, ref_old, ref_new, op, candidate}`` in the land journal and the ref update
    with expected old value P. ``reserved`` is the op of a reserved grant (re-verified at
    publication), None for the human route. ``standing`` is the message uuid of a standing
    grant (re-checked at publication by ``_standing_recheck``), None otherwise. The
    candidate is removed afterwards.

    Returns:
        C, the published commit.

    Raises:
        rp.Refusal: ``message`` (no stored message), ``signing_unconfigured``,
            ``candidate_foreign``, a check (``index_tree``, ``unstaged_drift``,
            ``unlisted_staged``, ``commit``, ``hook_drift``, ``ignored_residue:<path>``,
            ``parent``, ``identity``, ``signature``) or ``publish_refused``.
        Stopped: ``ref_holds_candidate``.
    """
    ctx = _land_context(repo, land, act=act, reserved=reserved, standing=standing)
    state = _candidate_state(ctx)
    if state == "foreign":
        raise rp.Refusal("candidate_foreign", rp.display_path(ctx.candidate))
    if state == "owned":
        _remove_candidate(ctx)
    _build_candidate(ctx)
    try:
        check = _pre_hook_check(ctx)
        if check is not None:
            raise rp.Refusal(check, f"the land candidate of {land.op} before the hooks")
        if not _commit_candidate(ctx):
            raise rp.Refusal(
                "commit", f"git commit failed in the land candidate of {land.op}"
            )
        head = _git_ok(ctx.candidate, "rev-parse", "HEAD")
        check, _residue = _post_hook_check(ctx, head)
        if check is not None:
            raise rp.Refusal(check, f"the land candidate of {land.op} after the hooks")
        ctx.land_commit = head
        _step_published(ctx, resume=False)
    finally:
        _remove_candidate(ctx)
    land.raw = rp._json_bytes(land.record)
    return head


def land_publish_again(repo: rp.Repo, land: LandOp, *, act: str) -> str:
    """Recovery of step 7 (D:263-264): finish a publication whose record is at ``started``.

    The journal's last entry is ``published:started`` with the intent ``{ref_old, ref_new}``.
    The commit C of that intent must still be the commit of tree(T) on P; then
    ``_step_published`` resumes: the reflog and the ref decide. ``main`` at C with ``P -> C``
    in the reflog only journals ``done``; ``main`` at P with no ``P -> C`` publishes again with
    expected old value P; any other state, or a reflog that cannot answer, is
    ``publication_unclear``. A reserved plan grant or a human direction authorized the
    publication when it started, so neither is verified again. A standing grant is
    different (R3-F1): the intent names its message uuid, and when ``main`` is still at P the
    publication re-checks that grant under ``store.lock`` up to the swap
    (``_update_ref``/``_standing_recheck``), so a revoke or an opt-out since the start
    refuses and ``main`` stays at P. ``main`` already at C needs no live authority. The
    candidate that the crash left is removed afterwards.

    Returns:
        C, the published commit.

    Raises:
        rp.Refusal: ``publication_unclear``, ``message``, ``signing_unconfigured``,
            ``publish_refused``, or on a standing land ``revoked:<uuid>``,
            ``no_authority`` or ``standing_opt_out``.
    """
    fields = land.fields()
    standing = fields.get("standing")
    if standing is not None and not isinstance(standing, str):
        raise rp.Refusal(
            "publication_unclear",
            f"land {land.op} names a standing grant that is not a message uuid",
        )
    ctx = _land_context(repo, land, act=act, reserved=None, standing=standing)
    commit = str(fields.get("ref_new", ""))
    started = land.journal[-1] if land.journal else None
    if (
        started is None
        or (started["phase"], started["status"]) != ("published", "started")
        or fields.get("ref_old") != ctx.parent
        or not OBJECT_ID_RE.fullmatch(commit)
    ):
        raise rp.Refusal(
            "publication_unclear",
            f"land {land.op} has no published:started intent of P to a commit",
        )
    proc = _run_git(
        repo.top, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"
    )
    if (
        proc.returncode != 0
        or _git_ok(repo.top, "rev-parse", f"{commit}^{{tree}}") != ctx.land_tree
        or _git_ok(repo.top, "rev-parse", f"{commit}^") != ctx.parent
    ):
        raise rp.Refusal(
            "publication_unclear",
            f"the commit {commit} of land {land.op} is not tree(T) on P",
        )
    ctx.land_commit = commit
    try:
        _step_published(ctx, resume=True)
    except Stopped as exc:
        raise rp.Refusal(
            "publication_unclear",
            f"land {land.op}: {exc}; main and the journal are unchanged",
        ) from None
    finally:
        _remove_candidate(ctx)
    land.raw = rp._json_bytes(land.record)
    return commit


#: A working file's physical identity: its device and its file index.
FileId = tuple[int, int]


def _file_id(full: Path) -> FileId | None:
    """The physical identity of the file or symlink at ``full``, or None.

    None when nothing is there, when it is a folder, when it has more than one link, or when
    the filesystem gives no file index (``st_ino`` 0); an error of the stat is the same
    answer, because None only ever leaves a name to its exact spelling. Two Git names are
    one working file only when both have one identity (R5-F1): a filesystem that folds case
    opens ``Widget.py`` and ``widget.py`` as one file, but ``strasse.py`` and ``straße.py``,
    or a composed and a decomposed ``Café.py``, are two files although they fold to one
    string.
    """
    try:
        info = os.stat(full, follow_symlinks=False)
    except OSError:
        return None
    if stat.S_ISDIR(info.st_mode) or info.st_ino == 0 or info.st_nlink != 1:
        return None
    return (info.st_dev, info.st_ino)


def _work_ids(top: Path, paths: Sequence[str]) -> dict[FileId, list[str]]:
    """The names of ``paths`` that each existing working file answers to (``_file_id``)."""
    found: dict[FileId, list[str]] = {}
    for path in paths:
        ident = _file_id(top / path)
        if ident is not None:
            found.setdefault(ident, []).append(path)
    return found


def _alias_blobs(
    repo: rp.Repo, parent: str, commit: str, ids: Mapping[FileId, list[str]]
) -> dict[str, list[str | None]]:
    """The P and C blob ids of the working file that a path shares with others of ``ids``.

    Names of one physical file are separate index entries but one working file (R4-F1: P
    has ``Widget.py``, C has ``widget.py``, and the filesystem folds case). That file is at
    P when it holds the blob of the one name P has (absent when P has none), and at C
    likewise. A name that shares no file, or a group with two names on one side, is left
    out and keeps its own blobs; so does every name whose file is absent or distinct
    (R5-F2: a composed ``Café.py`` and a decomposed ``café.py`` are two files).

    Raises:
        rp.GitError: a git read failed.
    """
    groups = [group for group in ids.values() if len(group) > 1]
    if not groups:
        return {}
    shared = [path for group in groups for path in group]
    sides = [_tree_entries(repo, side, shared) for side in (parent, commit)]
    found: dict[str, list[str | None]] = {}
    for group in groups:
        present = [
            [side[path][0]["oid"] for path in group if side[path]] for side in sides
        ]
        if any(len(names) > 1 for names in present):
            continue
        blobs: list[str | None] = [names[0] if names else None for names in present]
        found.update((path, blobs) for path in group)
    return found


def _explained(
    full: Path, rel: str, explained: frozenset[str], ids: Mapping[FileId, list[str]]
) -> bool:
    """Whether the working file ``full`` (at ``rel``) is the file of a classified path.

    It is when ``rel`` is one of the ``explained`` paths, or when it is the same physical
    file as one of them (``ids``); that path's own bytes are then checked at P and at C. A
    name that only folds to a classified path's name is another file (R5-F1).
    """
    return rel in explained or _file_id(full) in ids


def _is_dir_link(full: Path) -> bool:
    """Whether ``full`` is a symlink or an NTFS junction (``Path.is_symlink`` misses one)."""
    return os.path.islink(full) or os.path.isjunction(full)


def _walk_error(top: Path, path: str, error: OSError) -> str:
    """The folder that the walk of ``path`` could not list, relative to ``top``.

    It is ``error.filename`` when that names a folder under ``top``, else ``path`` itself.
    """
    try:
        return Path(os.fsdecode(error.filename)).relative_to(top).as_posix()
    except (TypeError, ValueError):
        return path


def _stray_below(
    top: Path,
    path: str,
    explained: frozenset[str],
    ids: Mapping[FileId, list[str]],
) -> str | None:
    """The first entry under the folder ``path`` that is not the file of a classified path
    (``_explained``), or None.

    A folder whose every file is a classified path holds only tracked content at P or at
    C, so the sync may replace it with a file or fill it (R3-F1). Any other file in it is
    nobody's tracked content. A directory link (``_is_dir_link``) is never walked: a file
    reached through it has the identity of its target, but the sync would remove it
    through the link, so the link itself is the stray (EA-121). A folder that the walk
    cannot list may hold anything, so it is the stray too (EA-121).
    """
    if _is_dir_link(top / path):
        return path
    errors: list[OSError] = []
    for folder, dirs, names in os.walk(top / path, onerror=errors.append):
        if errors:
            break
        here = Path(folder)
        links = [name for name in dirs if _is_dir_link(here / name)]
        dirs[:] = sorted(name for name in dirs if name not in links)
        for name in sorted(names + links):
            full = here / name
            rel = full.relative_to(top).as_posix()
            if not _explained(full, rel, explained, ids):
                return rel
    if errors:
        return _walk_error(top, path, errors[0])
    return None


def _stdin_path_ok(path: str) -> bool:
    """Whether ``hash-object --stdin-paths`` reads ``path`` as it is.

    It C-unquotes a line that starts with a double quote and splits the input at line
    ends, so such a name goes on the command line instead (EA-121).
    """
    return not path.startswith('"') and "\n" not in path and "\r" not in path


def _link_oid(top: Path, path: str) -> str:
    """The blob id of the symlink at ``path`` as Git stores it: the blob of its link text.

    Git for Windows writes the text with ``/`` separators. A link that cannot be read
    gets the empty id, which matches no blob (EA-121).

    Raises:
        rp.GitError: ``hash-object`` failed.
    """
    try:
        text = os.readlink(top / path)
    except OSError:
        return ""
    if os.name == "nt":
        text = text.replace("\\", "/")
    return _git_ok(top, "hash-object", "--stdin", data=os.fsencode(text))


def _work_oids(
    top: Path, paths: Sequence[str], ids: Mapping[FileId, list[str]]
) -> dict[str, str | None]:
    """The blob id each path's working file would have (clean filters on); None when absent.

    A folder at a path counts as absent when every file in it is the file of one of
    ``paths`` (``_stray_below``); any other folder gets the empty id, which matches no blob.
    A symlink gets the blob of its link text (``_link_oid``), never its target's (EA-121).

    Raises:
        rp.GitError: ``hash-object`` failed.
    """
    explained = frozenset(paths)
    found: dict[str, str | None] = {}
    files: list[str] = []
    for path in paths:
        full = top / path
        if full.is_symlink():
            found[path] = _link_oid(top, path)
        elif full.is_file() and not _stdin_path_ok(path):
            found[path] = _git_ok(top, "hash-object", "--", path)
        elif full.is_file():
            files.append(path)
        elif full.is_dir():
            stray = _stray_below(top, path, explained, ids)
            found[path] = None if stray is None else ""
        else:
            found[path] = "" if full.exists() else None
    for start in range(0, len(files), SYNC_CHUNK):
        chunk = files[start : start + SYNC_CHUNK]
        out = _git_ok(
            top, "hash-object", "--stdin-paths", data=("\n".join(chunk) + "\n").encode()
        )
        found.update(zip(chunk, out.splitlines(), strict=True))
    return found


def _obstruction(
    top: Path,
    path: str,
    explained: frozenset[str],
    ids: Mapping[FileId, list[str]],
) -> str | None:
    """The untracked file or symlink that sits where ``path``'s folders go, or None.

    Only for a path whose working file is absent. An ancestor that is one of the classified
    ``explained`` paths, or the same physical file as one (``_explained``), is at P or at C
    already. Any other non-folder ancestor is nobody's tracked content, and ``read-tree
    -u`` would replace it (R1-F1). A directory link at an ancestor (``_is_dir_link``) is
    one too: ``read-tree -u`` would write through it (EA-121).
    """
    for ancestor in PurePosixPath(path).parents:
        name = ancestor.as_posix()
        if name == "." or name in explained:
            return None
        full = top / name
        if _is_dir_link(full) or (full.exists() and not full.is_dir()):
            return None if _explained(full, name, explained, ids) else name
        if full.is_dir():
            return None
    return None


def _sync_unexplained(
    repo: rp.Repo, parent: str, commit: str, paths: Sequence[str]
) -> str | None:
    """The first path whose index entry or working file is at neither P nor C, or None.

    An absent working file also needs its folders free: an untracked file at one of them
    is returned as that folder's path (``_obstruction``). A folder at a path that holds a
    file of no classified path is returned as that file (``_stray_below``, R3-F1, R5-F1).
    A working file that several names share is compared with its blobs at P and at C
    (``_alias_blobs``, R4-F1); every other name is its own file (R5-F2).

    Raises:
        rp.GitError: a git read failed.
    """
    ids = _work_ids(repo.top, paths)
    work = _work_oids(repo.top, paths, ids)
    explained = frozenset(paths)
    aliases = _alias_blobs(repo, parent, commit, ids)
    for start in range(0, len(paths), SYNC_CHUNK):
        chunk = list(paths[start : start + SYNC_CHUNK])
        index = _index_entries(repo, chunk)
        at_p = _tree_entries(repo, parent, chunk)
        at_c = _tree_entries(repo, commit, chunk)
        for path in chunk:
            sides = [
                [(item["mode"], item["oid"]) for item in side[path]]
                for side in (at_p, at_c)
            ]
            staged = [(item["mode"], item["oid"]) for item in index[path]]
            if any(item["stage"] != 0 for item in index[path]) or staged not in sides:
                return path
            blobs = aliases.get(path, [side[0][1] if side else None for side in sides])
            if work[path] not in blobs:
                if work[path] == "" and (Path(repo.top) / path).is_dir():
                    return _stray_below(Path(repo.top), path, explained, ids) or path
                return path
            if work[path] is None:
                blocked = _obstruction(Path(repo.top), path, explained, ids)
                if blocked is not None:
                    return blocked
    return None


def _without_live_fields(data: bytes) -> bytes | None:
    """task.md bytes without the ``LIVE_TASK_FIELDS`` lines, or None without a frontmatter."""
    try:
        text = data.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        return None
    end = text.find("\n---\n", 3)
    if not text.startswith("---\n") or end < 0:
        return None
    kept: list[str] = []
    listing = False
    for line in text[4:end].split("\n"):
        if line.startswith(LIVE_TASK_FIELDS):
            listing = line.startswith("bound_sessions:")
            continue
        if listing and (line.startswith("- ") or line.startswith("  - ")):
            continue
        listing = False
        kept.append(line)
    return ("\n".join(kept) + text[end:]).encode("utf-8")


def live_task_dirt(repo: rp.Repo, land: LandOp, target: str) -> str | None:
    """The land plan's ``task.md`` when the main checkout's change to it is run_parameters' own.

    That is: P and ``target`` hold the same blob of it, its index entry is P's (stage 0),
    and its working bytes differ from that blob only in the ``LIVE_TASK_FIELDS`` lines. Any
    other change stays dirt (``main_dirty:<path>`` at step 7, ``sync_unexplained:<path>``
    at step 8). None when there is no such change.

    Raises:
        rp.GitError: a git read failed.
    """
    rel = f"{PLANS_DIR}/{land.identity['plan']}/task.md"
    parent = str(land.fields()["P"])
    at_p = _tree_entries(repo, parent, [rel])[rel]
    if not at_p or at_p != _tree_entries(repo, target, [rel])[rel]:
        return None
    staged = _index_entries(repo, [rel])[rel]
    if any(int(item["stage"]) != 0 for item in staged) or [
        (item["mode"], item["oid"]) for item in staged
    ] != [(item["mode"], item["oid"]) for item in at_p]:
        return None
    blob = _run_git(repo.top, "cat-file", "blob", str(at_p[0]["oid"]))
    if blob.returncode != 0:
        raise rp.GitError(blob.stderr.decode("utf-8", errors="replace").strip())
    work = rp._read_bytes(Path(repo.top) / rel)
    if work is None or work == blob.stdout:
        return None
    base = _without_live_fields(blob.stdout)
    if base is None or _without_live_fields(work) != base:
        return None
    return rel


@dataclass(frozen=True)
class SyncDirt:
    """The foreign dirt of the main checkout that a land sync must keep (D-4, AC-939.9).

    ``tracked`` maps each tracked path outside ``diff-tree P C`` whose working file differs
    from its index entry, while that entry is C's (stage 0), to the working file's blob id
    (None for an absent file, the empty id for a folder). ``untracked`` lists the untracked
    paths outside ``diff-tree P C`` (``ls-files --others --exclude-standard --directory``);
    the sync never touches them, so they are evidence only.
    """

    tracked: dict[str, str | None]
    untracked: list[str]


def _stage0_pairs(entries: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]] | None:
    """The ``(mode, oid)`` pairs of index or tree entries; None when an entry is not stage 0."""
    if any(int(item.get("stage", 0)) != 0 for item in entries):
        return None
    return [(str(item["mode"]), str(item["oid"])) for item in entries]


def _at_commit_in_index(repo: rp.Repo, commit: str, paths: Sequence[str]) -> set[str]:
    """The ``paths`` whose index entry is exactly ``commit``'s entry, at stage 0.

    Raises:
        rp.GitError: a git read failed.
    """
    kept: set[str] = set()
    for start in range(0, len(paths), SYNC_CHUNK):
        chunk = list(paths[start : start + SYNC_CHUNK])
        index = _index_entries(repo, chunk)
        at_c = _tree_entries(repo, commit, chunk)
        kept.update(
            path
            for path in chunk
            if index[path] and _stage0_pairs(index[path]) == _stage0_pairs(at_c[path])
        )
    return kept


def _scan_sync_dirt(
    repo: rp.Repo, parent: str, commit: str, live: str | None
) -> SyncDirt:
    """Read the foreign dirt of the main checkout now (``SyncDirt``).

    The land plan's live task.md (``live_task_dirt``) is not foreign dirt: the sync keeps
    its bytes by its own rule (EA-60). A path that ``diff-files`` lists only for stale stat
    data (its working blob equals its index blob) is not dirt either, so the scan needs no
    ``update-index --refresh`` (which would rewrite the index before ``land:sync`` starts).

    Raises:
        rp.GitError: a git read failed.
    """
    top = repo.top
    landed = _names(
        top, "diff-tree", "-r", "-z", "--no-renames", "--name-only", parent, commit
    )
    listed = sorted(_names(top, "diff-files", "-z", "--name-only") - landed - {live})
    candidates = sorted(_at_commit_in_index(repo, commit, listed)) if listed else []
    tracked: dict[str, str | None] = {}
    if candidates:
        work = _work_oids(Path(top), candidates, _work_ids(Path(top), candidates))
        for start in range(0, len(candidates), SYNC_CHUNK):
            chunk = candidates[start : start + SYNC_CHUNK]
            index = _index_entries(repo, chunk)
            for path in chunk:
                if work[path] != str(index[path][0]["oid"]):
                    tracked[path] = work[path]
    untracked = sorted(
        _names(top, "ls-files", "-z", "--others", "--exclude-standard", "--directory")
        - landed
    )
    return SyncDirt(tracked=tracked, untracked=untracked)


def _read_sync_dirt(path: Path) -> SyncDirt | None:
    """The stored snapshot ``sync-dirt.json``, or None when the land has none.

    Raises:
        rp.Refusal: ``sync_dirt_malformed`` for a file that is not a ``sync-dirt/1`` record.
    """
    data = rp._read_bytes(path)
    if data is None:
        return None
    try:
        value = rp._load_json(data)
    except ValueError as exc:
        raise rp.Refusal(
            "sync_dirt_malformed", f"{rp.display_path(path)}: {exc}"
        ) from None
    body = cast(dict[str, Any], value) if isinstance(value, dict) else None
    tracked = body.get("tracked") if body is not None else None
    untracked = body.get("untracked") if body is not None else None
    if (
        body is None
        or body.get("schema") != SYNC_DIRT_SCHEMA
        or not isinstance(tracked, dict)
        or not isinstance(untracked, list)
        or not all(
            isinstance(key, str) and (oid is None or isinstance(oid, str))
            for key, oid in cast(dict[Any, Any], tracked).items()
        )
        or not all(isinstance(item, str) for item in cast(list[Any], untracked))
    ):
        raise rp.Refusal(
            "sync_dirt_malformed",
            f"{rp.display_path(path)} is not a {SYNC_DIRT_SCHEMA} record",
        )
    return SyncDirt(
        tracked=cast(dict[str, str | None], dict(cast(dict[Any, Any], tracked))),
        untracked=cast(list[str], list(cast(list[Any], untracked))),
    )


def snapshot_sync_dirt(
    repo: rp.Repo, land: LandOp, parent: str, commit: str
) -> SyncDirt:
    """The land's foreign-dirt snapshot (D-4): the stored one, else a new one written now.

    ``lanes.py land publish`` may take it at publication; ``land_sync`` takes it before
    ``land:sync`` starts when the land has none, so a crash in the sync leaves the snapshot
    of the state before it. A snapshot once written is never replaced here: a later run
    compares the main checkout with it (``sync_dirt_changed:<path>``).

    Raises:
        ValueError: ``parent`` or ``commit`` is not an object id.
        rp.Refusal: ``sync_dirt_malformed``.
        rp.GitError: a git read failed.
    """
    for oid in (parent, commit):
        if not OBJECT_ID_RE.fullmatch(oid):
            raise ValueError(f"snapshot_sync_dirt: {oid!r} is not an object id")
    path = land.folder / SYNC_DIRT_NAME
    stored = _read_sync_dirt(path)
    if stored is not None:
        return stored
    dirt = _scan_sync_dirt(repo, parent, commit, live_task_dirt(repo, land, commit))
    land.folder.mkdir(parents=True, exist_ok=True)
    rp._write_atomic(
        path,
        rp._json_bytes(
            {
                "schema": SYNC_DIRT_SCHEMA,
                "P": parent,
                "C": commit,
                "tracked": dirt.tracked,
                "untracked": dirt.untracked,
            }
        ),
    )
    return dirt


def _sync_dirt_moved(repo: rp.Repo, dirt: SyncDirt) -> str | None:
    """The first snapshot path whose working file no longer has its snapshot blob, or None.

    Raises:
        rp.GitError: ``hash-object`` failed.
    """
    paths = sorted(dirt.tracked)
    if not paths:
        return None
    work = _work_oids(Path(repo.top), paths, _work_ids(Path(repo.top), paths))
    return next((path for path in paths if work[path] != dirt.tracked[path]), None)


def _refuse_sync_dirt_moved(land: LandOp, moved: str) -> rp.Refusal:
    """Journal a refused sync for a changed foreign file; the refusal to raise (D-4)."""
    _land_entry(land, "land:sync", "refused:sync_dirt_changed", {})
    return rp.Refusal(
        f"sync_dirt_changed:{moved}",
        f"{moved} in the main checkout changed after the land took its snapshot "
        f"{rp.display_path(land.folder / SYNC_DIRT_NAME)}; restore its bytes, or remove "
        "the snapshot to take a new one, then run lanes.py land recover",
    )


def land_sync(repo: rp.Repo, land: LandOp) -> None:
    """Step 8 (AC-785.21): the main checkout's index and tracked files from P to C.

    Its own journal phase ``land:sync``. Each path of P..C, of the index against C and of
    the files against the index is classified: its index entry and its working file are each
    at P or at C, or the path is unexplained (``sync_unexplained:<path>``, journaled as a
    refused sync; the land stops and ``land_blocker`` / ``_check_sync_pending`` block every
    other publication). A path whose working file is absent is unexplained also when an
    untracked file sits at one of its folders (R1-F1). A folder at a path (a file and a
    folder swapped between P and C) counts as an absent file when every file in it is a
    classified path; otherwise its first other file is unexplained (R3-F1), and so is a
    directory link in it or a folder in it that cannot be listed (EA-121). A file is a
    classified path's file only by its exact name or by its physical identity, never by a
    folded name (R5-F1). Names that the filesystem opens as one working file (a case-only
    rename) are compared as that one file, at P's blob or at C's (R4-F1); every other name
    is its own file (R5-F2). An index and working files all at
    P take ``git read-tree -m -u P C``; any other explained state (an index entry or a
    working file already at C: the step crashed part way, R2-F1) takes ``git read-tree
    --reset -u C`` (every path and every folder it needs is explained, so nothing else is
    lost). A failed
    read-tree is never retried with ``--reset``: it is journaled as a refused sync
    (``sync_refused``, git's message kept) and the main checkout stays as git left it
    (R1-F1). The step is done only when ``diff-index --cached C`` and ``diff-files``
    are both empty. ``_reconcile_index`` is never used for a land. The land plan's own
    task.md, changed only in run_parameters' live fields (``live_task_dirt``), keeps
    those bytes and is left out of both checks (EA-60).

    D-4 (AC-939.9): before ``land:sync`` starts the land snapshots the foreign dirt
    (``snapshot_sync_dirt``, kept in ``sync-dirt.json``). A snapshot path whose index entry
    is still C's is left out of the classification, of the read-tree choice and of the
    final check, so ``read-tree -m -u`` keeps its bytes. Its working file must keep the
    snapshot blob before and after the read-tree (``sync_dirt_changed:<path>``), and the
    ``--reset`` branch is never taken while the snapshot holds a tracked path
    (``sync_reset_with_dirt``). Each of these refusals is journaled as a refused sync.

    Raises:
        rp.Refusal: ``sync_unexplained:<path>``, ``sync_refused`` (read-tree failed),
            ``sync_incomplete:<path>``, ``sync_unclear`` (no published C in the journal),
            ``sync_dirt_changed:<path>``, ``sync_reset_with_dirt`` or
            ``sync_dirt_malformed``.
        rp.GitError: a git step failed.
    """
    fields = land.fields()
    parent = str(fields["P"])
    commit = str(fields.get("ref_new", ""))
    if not _land_has(land, "published", ("done",)) or not OBJECT_ID_RE.fullmatch(
        commit
    ):
        raise rp.Refusal("sync_unclear", f"land {land.op} has no published C")
    dirt = snapshot_sync_dirt(repo, land, parent, commit)
    last = land.journal[-1]
    if (last["phase"], last["status"]) != ("land:sync", "started"):
        land_start(land, "land:sync")
    moved = _sync_dirt_moved(repo, dirt)
    if moved is not None:
        raise _refuse_sync_dirt_moved(land, moved)
    top = repo.top
    _run_git(top, "update-index", "-q", "--refresh")
    foreign = (
        _at_commit_in_index(repo, commit, sorted(dirt.tracked))
        if dirt.tracked
        else set()
    )
    changed = (
        _names(
            top, "diff-tree", "-r", "-z", "--no-renames", "--name-only", parent, commit
        )
        | _names(
            top, "diff-index", "--cached", "-z", "--no-renames", "--name-only", commit
        )
        | _names(top, "diff-files", "-z", "--name-only")
    )
    live = live_task_dirt(repo, land, commit)
    live_bytes = rp._read_bytes(Path(top) / live) if live is not None else None
    paths = sorted(changed - {live} - foreign)
    stray = _sync_unexplained(repo, parent, commit, paths)
    if stray is not None:
        _land_entry(land, "land:sync", "refused:sync_unexplained", {})
        raise rp.Refusal(
            f"sync_unexplained:{stray}",
            f"{stray} in the main checkout is at neither P nor C; the land stops and "
            "every publication waits until it is explained",
        )
    index = _index_entries(repo, paths) if paths else {}
    at_p = _tree_entries(repo, parent, paths) if paths else {}
    ids = _work_ids(top, paths) if paths else {}
    work = _work_oids(top, paths, ids) if paths else {}
    aliases = _alias_blobs(repo, parent, commit, ids) if paths else {}
    if all(
        index[path] == at_p[path]
        and work[path]
        == (
            aliases[path][0]
            if path in aliases
            else (at_p[path][0]["oid"] if at_p[path] else None)
        )
        for path in paths
    ):
        proc = _run_git(top, "read-tree", "-m", "-u", parent, commit)
    elif dirt.tracked:
        _land_entry(land, "land:sync", "refused:sync_reset_with_dirt", {})
        raise rp.Refusal(
            "sync_reset_with_dirt",
            "the main checkout is part way between P and C, and git read-tree --reset "
            f"would overwrite {len(dirt.tracked)} foreign dirty files (first "
            f"{min(dirt.tracked)}); the land stops until they are committed or restored",
        )
    else:
        proc = _run_git(top, "read-tree", "--reset", "-u", commit)
    if proc.returncode != 0:
        _land_entry(land, "land:sync", "refused:sync_refused", {})
        raise rp.Refusal(
            "sync_refused",
            "git read-tree refused to move the main checkout to C: "
            + proc.stderr.decode("utf-8", errors="replace").strip(),
        )
    if live is not None and live_bytes is not None:
        # P and C hold the same blob of it, so a --reset can only have dropped the
        # live fields: write back the bytes run_parameters left there.
        if rp._read_bytes(Path(top) / live) != live_bytes:
            rp._write_durable(Path(top) / live, live_bytes)
    moved = _sync_dirt_moved(repo, dirt)
    if moved is not None:
        raise _refuse_sync_dirt_moved(land, moved)
    _run_git(top, "update-index", "-q", "--refresh")
    kept = (
        _at_commit_in_index(repo, commit, sorted(dirt.tracked))
        if dirt.tracked
        else set()
    )
    left = sorted(
        (
            _names(
                top,
                "diff-index",
                "--cached",
                "-z",
                "--no-renames",
                "--name-only",
                commit,
            )
            | _names(top, "diff-files", "-z", "--name-only")
        )
        - {live_task_dirt(repo, land, commit)}
        - kept
    )
    if left:
        _land_entry(land, "land:sync", "refused:sync_incomplete", {})
        raise rp.Refusal(
            f"sync_incomplete:{left[0]}",
            f"after read-tree the main checkout still differs from C at {len(left)} paths",
        )
    land_finish(land, "land:sync")


def _run_packets(
    repo: rp.Repo,
    *,
    op: str,
    run: str,
    act: str,
    packets: list[Packet],
    batch: bool,
    reserved: str | None,
    verified: rp.Verified | None,
    consent: dict[str, Any] | None,
    retry: dict[str, Any] | None = None,
    standing: str | None = None,
) -> Outcome:
    """Drive one op, or each sub-op ``<op>/<n>`` of a batch on the previous sub-op's commit.

    ``standing`` is the uuid of the standing grant a grant-route op commits under
    (MEU-939); publication re-checks it as ``reserved`` re-checks a plan grant.

    The batch record is written once the first sub-op opens, before any sub-op is driven.
    An op id spent as one form (one packet, or a batch) refuses the other: ``packet_mismatch``.
    A batch is spent from its first sub-op's folder ``<op>/1``, which a crash can leave
    before ``batch.json`` exists (R4-F2).
    """
    root = _candidate_root(repo)
    folder = _op_base(repo, packets[0], run) / op
    spent = (
        (folder / "op.json").exists()
        if batch
        else (folder / "batch.json").exists() or (folder / "1").exists()
    )
    if spent:
        raise rp.Refusal("packet_mismatch", op)
    if not batch:
        packet = packets[0]
        ctx = _open_op(
            repo,
            op=op,
            run=run,
            act=act,
            packet=packet,
            parent=packet.parent,
            root=root,
            reserved=reserved,
            verified=verified,
            consent=consent,
            retry=retry,
            standing=standing,
        )
        _drive(ctx, "reconciled")
        return rp.EXIT_OK, _summary(ctx)
    commits: list[str] = []
    index: dict[str, str] = {}
    parent = packets[0].parent
    tree = ""
    for number, packet in enumerate(packets, 1):
        ctx = _open_op(
            repo,
            op=f"{op}/{number}",
            run=run,
            act=act,
            packet=packet,
            parent=parent,
            root=root,
            reserved=reserved,
            verified=verified,
            consent=consent,
            retry=retry if number == 1 else None,
            standing=standing,
        )
        if number == 1:
            _open_batch(repo, op=op, run=run, act=act, packets=packets)
        _drive(ctx, "reconciled")
        summary = _summary(ctx)
        commits.append(cast(str, summary["commit"]))
        index.update(cast(dict[str, str], summary["index"]))
        parent, tree = commits[-1], cast(str, summary["tree"])
    return rp.EXIT_OK, {
        "result": "reconciled",
        "op": op,
        "commit": commits[-1],
        "commits": commits,
        "parent": packets[0].parent,
        "tree": tree,
        "index": index,
    }


# -- the retry of a human direction (MEU-813) ------------------------------------------------


def _retry_identity(act: str, packets: Sequence[Packet], batch: bool) -> str:
    """D-MFU2-3: the digest of what a retry must repeat; only each packet's parent may differ."""
    items: list[dict[str, Any]] = []
    for packet in packets:
        raw = {key: value for key, value in packet.raw.items() if key != "parent"}
        entries = cast(list[dict[str, Any]], raw["entries"])
        raw["entries"] = sorted(entries, key=lambda entry: cast(str, entry["path"]))
        items.append(raw)
    return _packet_digest(
        {"act": act, "form": "batch" if batch else "one", "packets": items}
    )


def _attempt_exists(folder: Path) -> bool:
    """Whether an op folder holds an attempt: the claim alone, or an empty folder, is none."""
    return (folder / "op.json").exists() or (folder / "1" / "op.json").exists()


def _attempt_records(folder: Path) -> list[dict[str, Any]] | None:
    """An attempt's op records, batch sub-ops in number order; None when one cannot be read."""
    paths = [folder / "op.json"]
    if not paths[0].exists():
        names = (path.parent.name for path in folder.glob("*/op.json"))
        numbers = sorted(
            int(name) for name in names if name.isascii() and name.isdigit()
        )
        paths = [folder / str(number) / "op.json" for number in numbers]
    records: list[dict[str, Any]] = []
    for path in paths:
        try:
            value = rp._load_json(rp._read_bytes(path) or b"")
        except ValueError:
            return None
        if not isinstance(value, dict):
            return None
        record = cast(dict[str, Any], value)
        journal = record.get("journal")
        if not isinstance(journal, list) or not journal:
            return None
        if not all(isinstance(entry, dict) for entry in cast(list[object], journal)):
            return None
        if not isinstance(record.get("identity"), dict):
            return None
        records.append(record)
    return records


def _journal_entries(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The journal of a record that ``_attempt_records`` read."""
    return cast(list[dict[str, Any]], record["journal"])


def _attempt_published(records: Sequence[Mapping[str, Any]]) -> bool:
    """Whether the journal of any sub-op holds ``published:done``."""
    return any(
        (entry.get("phase"), entry.get("status")) == ("published", "done")
        for record in records
        for entry in _journal_entries(record)
    )


def _direction_published(base: Path, name: str) -> bool:
    """Whether any attempt of a direction (``<name>``, ``<name>-r<n>``) holds ``published:done``."""
    for folder in [base / name, *sorted(base.glob(f"{name}-r*"))]:
        records = _attempt_records(folder) if folder.is_dir() else None
        if records and _attempt_published(records):
            return True
    return False


def _attempt_commits(records: Sequence[Mapping[str, Any]]) -> list[str]:
    """The commits an attempt built: the ``candidate_verified`` evidence of each sub-op."""
    commits: list[str] = []
    for record in records:
        for entry in _journal_entries(record):
            evidence = entry.get("evidence")
            if entry.get("phase") != "candidate_verified" or not isinstance(
                evidence, dict
            ):
                continue
            commit = cast(dict[str, Any], evidence).get("commit")
            if isinstance(commit, str):
                commits.append(commit)
    return commits


def _attempt_commit_reachable(
    repo: rp.Repo, branch: str, commits: Sequence[str]
) -> bool:
    """RULE-1: whether git says the branch tip holds one of the attempt's commits."""
    ref = f"refs/heads/{branch}"
    return any(
        _run_git(repo.top, "merge-base", "--is-ancestor", commit, ref).returncode == 0
        for commit in commits
    )


def _attempt_in_reflog(repo: rp.Repo, branch: str, commit: str) -> bool:
    """RULE-1: whether the branch reflog shows a move to ``commit``; no reflog file says no."""
    text = rp._read_text(repo.common / "logs" / "refs" / "heads" / branch)
    if text is None:
        return False
    return any(
        len(parts) >= 2 and parts[1] == commit
        for parts in (line.split() for line in text.splitlines())
    )


def _attempt_terminal(records: Sequence[Mapping[str, Any]]) -> bool:
    """D-MFU2-4: sub-op 1 ended refused or failed, and no sub-op stopped in a publication."""
    for record in records:
        last = _journal_entries(record)[-1]
        if (last.get("phase"), last.get("status")) == ("published", "started"):
            return False
    journal = _journal_entries(records[0])
    if journal[-1].get("status") == PUBLISH_REFUSED:
        return True
    return any(
        str(entry.get("status", "")).startswith(CANDIDATE_FAILED) for entry in journal
    )


def _retry_identity_same(record: Mapping[str, Any], identity: str) -> bool:
    """D-MFU2-3: the record holds a well-formed ``retry`` of this identity; else no retry."""
    value = record.get("retry")
    if not isinstance(value, dict):
        return False
    retry = cast(dict[str, Any], value)
    attempt = retry.get("attempt")
    parent = retry.get("first_parent")
    return (
        retry.get("identity") == identity
        and isinstance(attempt, int)
        and not isinstance(attempt, bool)
        and attempt >= 1
        and isinstance(parent, str)
        and OID_RE.fullmatch(parent) is not None
    )


def _retry_base_conflict(
    repo: rp.Repo, first_parent: str, new_parent: str, paths: Sequence[str]
) -> str | None:
    """D-MFU2-5: why the move from the first parent could lose an update; None when it cannot."""
    proc = _run_git(repo.top, "merge-base", "--is-ancestor", first_parent, new_parent)
    if proc.returncode != 0:
        return f"{first_parent} is not an ancestor of {new_parent}"
    moved = _names(
        repo.top, "diff", "--name-only", "--no-renames", "-z", first_parent, new_parent
    )
    touched = sorted(moved & set(paths))
    return f"the base moved {touched[0]}" if touched else None


def _select_attempt(
    repo: rp.Repo,
    session: str,
    uid: str,
    act: str,
    packets: Sequence[Packet],
    batch: bool,
) -> tuple[str, dict[str, Any] | None]:
    """D-MFU2-4: the op this direction runs as, and the retry record a new op writes.

    A published attempt, by the journal or by git (RULE-1), and a last attempt that is not
    terminal, resolve to the last op, so that op's own rules decide. So do changed bytes and
    a rerun of the same packet after ``publish_refused`` (the ABA rule of the first op).
    Everything else is a fresh ``-r<n>``, unless the lost-update guard refuses.

    Raises:
        rp.Refusal: ``retry_base_conflict``.
    """
    first = packets[0]
    base = f"{HUMAN_OP_PREFIX}{uid}"
    root = _op_base(repo, first, session)
    names: list[str] = []
    while True:
        number = len(names) + 1
        name = base if number == 1 else f"{base}-r{number}"
        if not _attempt_exists(root / name):
            break
        names.append(name)
    identity = _retry_identity(act, packets, batch)
    if not names:
        return base, {
            "identity": identity,
            "attempt": 1,
            "retry_of": None,
            "first_parent": first.parent,
        }
    last_op = names[-1]
    attempts: list[list[dict[str, Any]]] = []
    for name in names:
        records = _attempt_records(root / name)
        if not records:
            return last_op, None
        attempts.append(records)
    for records in attempts:
        commits = _attempt_commits(records)
        if (
            _attempt_published(records)
            or _attempt_commit_reachable(repo, first.branch, commits)
            or any(_attempt_in_reflog(repo, first.branch, item) for item in commits)
        ):
            return last_op, None
    records = attempts[-1]
    head = records[0]
    if not _attempt_terminal(records) or not _retry_identity_same(head, identity):
        return last_op, None
    digest = cast(dict[str, Any], head["identity"]).get("packet_digest")
    if (
        _journal_entries(head)[-1].get("status") == PUBLISH_REFUSED
        and digest == first.digest
    ):
        return last_op, None
    first_parent = cast(str, cast(dict[str, Any], head["retry"])["first_parent"])
    paths = sorted({path for packet in packets for path in packet.paths})
    conflict = _retry_base_conflict(repo, first_parent, first.parent, paths)
    if conflict is not None:
        raise rp.Refusal("retry_base_conflict", conflict)
    return f"{base}-r{len(names) + 1}", {
        "identity": identity,
        "attempt": len(names) + 1,
        "retry_of": last_op,
        "first_parent": first_parent,
    }


def _direction_lease_live(path: Path) -> bool:
    """D-MFU2-7: a readable lease whose holder has not exited; a holder on another host counts."""
    body = rp._read_lock(path)
    return body is not None and not rp._holder_dead(body)


@contextlib.contextmanager
def _direction_lease(repo: rp.Repo, session: str, uid: str) -> Iterator[None]:
    """D-MFU2-7: one live driver holds a direction; there is no wait, because a rerun retries.

    ``store.lock`` covers only the acquire and the takeover, so hooks never block other lanes.
    The file sits outside ``ops/``, so the op readers and the ref guard do not see it. A
    crashed holder's file stays until the next driver takes it over.

    Raises:
        rp.Refusal: ``direction_busy``, or a store lock refusal.
    """
    path = repo.store / DIRECTION_LEASE_DIR / f"{uid}.lock"
    token = uuid.uuid4().hex
    body = {
        "pid": os.getpid(),
        "pid_start": rp._pid_start(os.getpid()) or "unknown",
        "host": socket.gethostname(),
        "session": session or "unknown",
        "token": token,
        "ts": rp._ts(repo),
    }
    with rp._locked(repo, session):
        if _direction_lease_live(path):
            holder = rp._read_lock(path) or {}
            raise rp.Refusal("direction_busy", str(holder.get("pid")))
        path.parent.mkdir(parents=True, exist_ok=True)
        rp._write_atomic(path, rp._json_bytes(body))
    try:
        yield
    finally:
        current = rp._read_lock(path)
        if current is not None and current["token"] == token:
            # The outcome of the attempt stands: the next driver takes a dead lease over.
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)


# -- the routes -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Authority:
    """What authorizes one grant-route op: the plan's reserved grant, or the standing grant."""

    verified: rp.Verified | None
    standing: str | None


def _plan_grant_kept(exc: rp.Refusal) -> bool:
    """Whether the plan grant's refusal stands when no standing grant covers the act.

    A plan with a grant of its own that does not grant the act (``not_granted``) or did not
    reserve this op (``not_reserved:<plan>:<act>:<op>``) keeps that refusal. A plan with no
    grant at all (``not_reserved:legacy``, ``not_reserved:manual``, ``binding``) refuses
    ``no_authority`` instead.
    """
    return exc.reason == "not_granted" or (
        exc.reason == "not_reserved" and ":" in exc.detail
    )


def _grant_authority(repo: rp.Repo, packet: Packet, act: str, op: str) -> _Authority:
    """D-1 order (AC-939.3): the plan's reserved grant, then the standing grant.

    A planless packet has no plan grant, so only the standing grant can authorize it. The
    standing grant's branch must be the packet's branch: ``standing_authority`` checks the
    project only.

    Raises:
        rp.Refusal: the plan grant's own refusal when it stands (``_plan_grant_kept``);
            ``no_authority`` (detail ``<plan>:<act>``) when neither grant covers the act;
            ``standing_opt_out``; ``scope`` or ``scope_branch_mismatch``; the V-A and
            store refusals.
    """
    plan = packet.plan
    first: rp.Refusal | None = None
    if plan != PLANLESS:
        try:
            return _Authority(_reserved(repo, plan, act, op, packet.branch), None)
        except rp.Refusal as exc:
            if exc.reason not in STANDING_FALLTHROUGH:
                raise
            first = exc
    live = rp.standing_authority(repo, plan, act)
    if live is None:
        if first is not None and _plan_grant_kept(first):
            raise first
        raise rp.Refusal("no_authority", f"{plan}:{act}")
    rp._check_scope(repo, cast(dict[str, Any], live["offer"]), plan, packet.branch)
    return _Authority(None, cast(str, live["message_uuid"]))


def _op_started(folder: Path) -> bool:
    """Whether an op folder already holds the op as one packet or as a batch (R4-F2)."""
    return (
        (folder / "op.json").exists()
        or (folder / "batch.json").exists()
        or (folder / "1").exists()
    )


def _plan_owns(repo: rp.Repo, plan: str) -> list[str] | None:
    """The ``owns`` entries of the plan's ``## Lane Ownership`` block; None without a block.

    Raises:
        rp.Refusal: ``ownership_bad`` (``<plan>:<reason>``) for a malformed or unreadable
            block.
    """
    from tools import lanes  # noqa: PLC0415 - lanes imports this module

    task = rp._plan_dir(repo, plan) / "task.md"
    if not task.is_file():
        return None
    try:
        owns, _avoid = lanes._read_ownership(task)
    except lanes.Refusal as exc:
        if exc.reason == "no_ownership":
            return None
        raise rp.Refusal("ownership_bad", f"{plan}:{exc.reason}") from None
    except OSError as exc:
        raise rp.Refusal("ownership_bad", f"{plan}:unreadable:{exc}") from None
    return list(owns)


def _foreign_owner(repo: rp.Repo, plan: str, path: str) -> str | None:
    """The other in-progress plan, or the active lane, whose ownership covers ``path``.

    An in-progress plan is a ``task.md`` whose frontmatter says ``status: in_progress``; a
    plan without a readable ownership block owns nothing. A lane owns paths while its card
    is ``active`` or ``landing``. The packet's own plan, and the lane that runs it, are never
    foreign.

    Raises:
        rp.Refusal: ``ownership_bad`` when the lane registry cannot be read.
    """
    from tools import lanes  # noqa: PLC0415 - lanes imports this module

    for task in rp._carrier_tasks(repo):
        other = task.parent.name
        if other == plan:
            continue
        try:
            meta = rp._frontmatter(rp._carrier_text(repo, task) or "")
        except rp.Refusal:
            continue
        if meta is None or meta.get("status") != OWNING_PLAN_STATUS:
            continue
        try:
            owns, _avoid = lanes._read_ownership(task)
        except (lanes.Refusal, OSError):
            continue
        if any(lanes._covers(entry, path) for entry in owns):
            return other
    own_dir = f"{PLANS_DIR}/{plan}/"
    try:
        cards = lanes._all_cards(repo.common)
    except lanes.Refusal as exc:
        raise rp.Refusal("ownership_bad", f"lanes:{exc.reason}") from None
    except OSError as exc:
        raise rp.Refusal("ownership_bad", f"lanes:unreadable:{exc}") from None
    for card in cards:
        if card["state"] not in OWNING_LANE_STATES or card["plan"] == own_dir:
            continue
        if any(lanes._covers(entry, path) for entry in card["owns"]):
            return str(card["lane"])
    return None


def _foreign_hunk(repo: rp.Repo, packets: Sequence[Packet]) -> tuple[str, str] | None:
    """The first ``(path, owner)`` among the packets' paths that another owner is editing.

    SG-D4 and D-4 ("foreign hunks stop the commit"): a path is edited when its working file
    (a missing file counts as none) is not at the parent's blob. It is a foreign hunk when
    another in-progress plan or an active lane owns it (``_foreign_owner``), even when the
    working bytes are the very bytes a packet commits (R1-F5): a packet built from the shared
    working file would otherwise carry another owner's edit unchecked. The packet's own plan,
    and the lane that runs it, are never foreign, so the plan's own dirty files pass; an
    unowned dirty path is left to the op's own index and work-tree rules.

    Raises:
        rp.GitError: a git read failed.
        rp.Refusal: ``ownership_bad``.
    """
    paths = sorted({path for packet in packets for path in packet.paths})
    work = _work_oids(repo.top, paths, _work_ids(repo.top, paths))
    for start in range(0, len(paths), SYNC_CHUNK):
        chunk = paths[start : start + SYNC_CHUNK]
        at_parent = _tree_entries(repo, packets[0].parent, chunk)
        for path in chunk:
            entries = at_parent[path]
            base = cast(str, entries[0]["oid"]) if entries else None
            if work[path] == base:
                continue
            owner = _foreign_owner(repo, packets[0].plan, path)
            if owner is not None:
                return path, owner
    return None


def _packet_scan_sets(packets: Sequence[Packet]) -> list[dict[str, bytes]]:
    """Every distinct ``(path, bytes)`` that the packets write, grouped into scan sets.

    R1-F4: a batch commits each packet, so every version a packet writes enters history,
    including one that a later packet replaces or deletes. A scan set holds at most one
    version of a path; a version already in a set is not repeated. The sets therefore number
    the most distinct versions any one path has (one for a batch whose packets write disjoint
    paths), and together they hold every written version. Each set keeps the repository paths
    unchanged, so the scanner's path-based config rules apply as they do to a commit.
    """
    sets: list[dict[str, bytes]] = []
    for packet in packets:
        for path, (_mode, data) in packet.files.items():
            if any(scan.get(path) == data for scan in sets):
                continue
            for scan in sets:
                if path not in scan:
                    scan[path] = data
                    break
            else:
                sets.append({path: data})
    return sets


def _scan_packets(repo: rp.Repo, packets: Sequence[Packet]) -> None:
    """AC-939.5: refuse ``secret:<path>`` when a blob that any packet writes holds a new secret.

    The shared scan of every commit route (the grant route's stop list and the human route,
    R1-F3), run before any reservation, claim or write, and independent of the pre-commit
    hooks, so ``SKIP=detect-secrets`` or a missing hook does not bypass it. Each packet's
    written files are scanned, not the batch's final state (R1-F4, ``_packet_scan_sets``).

    The baseline and the scanner config are those at the batch parent for every packet. A
    batch's packets all carry that parent (``_read_input``), and a commit's secrets stop is
    judged against the reviewed baseline already on the branch: a ``.secrets.baseline`` that a
    packet writes never admits that batch's own secrets, as in the lane land scan.

    Raises:
        rp.Refusal: ``secret`` (``<path>``); ``containment``; ``secret_scan`` when the
            scanner, the baseline or git fails.
    """
    rev = packets[0].parent
    for scan in _packet_scan_sets(packets):
        found = secret_findings(repo.top, scan, rev)
        if found:
            rp._log("commit_secret_findings", paths=found, parent=rev)
            raise rp.Refusal("secret", found[0])


def _stop_list(repo: rp.Repo, packets: Sequence[Packet]) -> None:
    """D-3 (AC-939.4): the checks a new grant-route op passes before any write.

    In order: a planless delete (``foreign_delete:<path>``); a delete that the plan's
    ownership block does not cover (``foreign_delete:<path>``; a plan without a block
    declares no ownership, so its deletes pass); a path that another owner is editing
    (``foreign_hunks:<path>:<owner>``, ``_foreign_hunk``); each packet's identity
    (``author_not_noreply``); a new secret in any file a packet writes (``secret:<path>``,
    ``_scan_packets``).

    Raises:
        rp.Refusal: the refusals above; ``ownership_bad``; ``secret_scan``; ``git_failed``.
    """
    from tools import lanes  # noqa: PLC0415 - lanes imports this module

    first = packets[0]
    deletes = [path for packet in packets for path in packet.deletes]
    if deletes and first.plan == PLANLESS:
        raise rp.Refusal("foreign_delete", sorted(deletes)[0])
    if deletes:
        owns = _plan_owns(repo, first.plan)
        if owns is not None:
            for path in deletes:
                if not any(lanes._covers(entry, path) for entry in owns):
                    raise rp.Refusal("foreign_delete", path)
    try:
        hunk = _foreign_hunk(repo, packets)
    except rp.GitError as exc:
        raise rp.Refusal("git_failed", str(exc)) from None
    if hunk is not None:
        raise rp.Refusal("foreign_hunks", f"{hunk[0]}:{hunk[1]}")
    for packet in packets:
        check_identity(repo.top, {"name": packet.author[0], "email": packet.author[1]})
    _scan_packets(repo, packets)


def _planless_unspent(repo: rp.Repo, packet: Packet, op: str, session: str) -> None:
    """AC-939.6: no other op made these planless bytes; else ``already_consumed``.

    A planless packet has no ``consumed`` entry: its digest folder
    ``ops/planless/<sha256>/`` is the record, and any op folder there other than ``op``
    that holds an attempt spends it.

    Raises:
        rp.Refusal: ``already_consumed`` (``planless:<digest8>:<op>``); a store lock refusal.
    """
    base = repo.store / "ops" / PLANLESS_DIR / packet.digest
    with rp._locked(repo, session):
        if not base.is_dir():
            return
        for other in sorted(base.iterdir()):
            if other.name == op or not other.is_dir():
                continue
            if _attempt_exists(other) or (other / "batch.json").exists():
                raise rp.Refusal(
                    "already_consumed",
                    f"{PLANLESS_PREFIX}{packet.digest[:8]}:{other.name}",
                )


def _standing_reserve(
    repo: rp.Repo, uid: str, plan: str, act: str, op: str, session: str
) -> None:
    """Reserve ``consumed[plan][act]`` for ``op`` in the live standing envelope.

    The standing grant authorizes each act of a plan once (AC-939.3). The same op finds its
    own entry and goes on, so a rerun resumes; another op refuses.

    Raises:
        rp.Refusal: ``consumed`` (``<plan>:<act>``); ``no_authority`` when the standing
            grant ended since the authority check; the store refusals.
    """
    with rp._locked(repo, session):
        rp._recover(repo)
        repo.refresh()
        store = rp._load_store(repo)
        rp._check_history(repo, store, None, check_grant=False)
        live = rp._standing_live(store)
        if live is None or live["message_uuid"] != uid:
            raise rp.Refusal("no_authority", f"standing:{uid}")
        consumed = cast(dict[str, Any], json.loads(json.dumps(live["consumed"])))
        existing = cast(dict[str, Any], consumed.get(plan, {})).get(act)
        if existing is not None:
            if cast(dict[str, Any], existing).get("op_id") != op:
                raise rp.Refusal("consumed", f"{plan}:{act}")
            return
        consumed.setdefault(plan, {})[act] = {
            "op_id": op,
            "state": "reserved",
            "ts": rp._ts(repo),
            "seq": rp._txn_log(repo.store).next_seq,
        }
        rp._txn(
            repo, {f"grants/{uid}.json": rp._json_bytes({**live, "consumed": consumed})}
        )


def _standing_recheck(ctx: Op) -> None:
    """Publication time for a standing op: the grant is live and still reserves this op.

    It reads the store without the lock, because ``_update_ref`` holds ``store.lock`` when
    it calls ``_reverify`` and the lock is not reentrant.

    Raises:
        rp.Refusal: ``revoked:<uuid>``; ``no_authority`` (superseded, or the reservation is
            not this op's); ``standing_opt_out``; the store refusals.
    """
    repo = ctx.repo
    uid = cast(str, ctx.standing)
    repo.refresh()
    store = rp._load_store(repo)
    if any(line.get("revoked") == uid for line in store.revocations):
        raise rp.Refusal(f"revoked:{uid}", "standing")
    live = rp._standing_live(store)
    if live is None or live["message_uuid"] != uid:
        raise rp.Refusal("no_authority", f"standing:{uid}")
    plan = ctx.packet.plan
    rp._standing_opt_out(repo, plan, ctx.act)
    if plan == PLANLESS:
        return
    consumed = cast(dict[str, Any], live["consumed"])
    entry = cast(dict[str, Any], consumed.get(plan, {})).get(ctx.act)
    root_op = ctx.op.split("/", 1)[0]
    if (
        not isinstance(entry, dict)
        or cast(dict[str, Any], entry).get("op_id") != root_op
    ):
        raise rp.Refusal("no_authority", f"{plan}:{ctx.act}:{root_op}")


def _grant_route(repo: rp.Repo, args: argparse.Namespace) -> Outcome:
    """``--phase``: an op of the phase's act under the plan's grant or the standing grant.

    D-1 order (``_grant_authority``). A new op then passes the D-3 stop list
    (``_stop_list``) before any write; a rerun of a started op goes straight on, so a crash
    after the commit never refuses its own dirt. Under the standing grant a planless packet
    is spent by its digest folder (``_planless_unspent``) and a plan's act by its
    ``consumed`` entry (``_standing_reserve``).
    """
    op = cast(str, args.op)
    run = cast(str, args.run or DEFAULT_RUN)
    _check_name(op)
    _check_name(run)
    phase = cast(str, args.phase)
    act = ACT_FOR_PHASE[phase]
    packets, batch = _read_input(Path(cast(str, args.packet)), phase == "exec")
    _candidate_root(repo)
    first = packets[0]
    if first.plan == PLANLESS and batch:
        raise rp.Refusal("planless_batch", f"{PLANLESS_PREFIX}{first.digest[:8]}")
    authority = _grant_authority(repo, first, act, op)
    if not _op_started(_op_base(repo, first, run) / op):
        _stop_list(repo, packets)
    if authority.standing is not None:
        if first.plan == PLANLESS:
            _planless_unspent(repo, first, op, run)
        else:
            _standing_reserve(repo, authority.standing, first.plan, act, op, run)
    return _run_packets(
        repo,
        op=op,
        run=run,
        act=act,
        packets=packets,
        batch=batch,
        reserved=op if authority.verified is not None else None,
        verified=authority.verified,
        consent=None,
        standing=authority.standing,
    )


def _human_route(repo: rp.Repo, args: argparse.Namespace) -> Outcome:
    """``--human-directed``: a typed human message that directs this commit or batch (D-34).

    After the direction is read (``_consent``) and before the store is bootstrapped, the
    direction claimed or anything written, every packet passes the shared secret scan
    (``_scan_packets``, R1-F3), so a refused secret leaves the direction unclaimed. The scan
    reads only the packets' bytes and the parent's baseline, so a rerun of a pending attempt
    repeats it with the same result. The grant route's ownership stops (``foreign_delete``,
    ``foreign_hunks``) do not apply: a typed direction names this commit.
    """
    session = cast(str, args.session)
    uid = cast(str, args.message_uuid)
    _check_name(session)
    _check_name(uid)
    packets, batch = _read_input(Path(cast(str, args.packet)), True)
    _candidate_root(repo)
    if packets[0].plan == PLANLESS and batch:
        raise rp.Refusal("planless_batch", f"{PLANLESS_PREFIX}{packets[0].digest[:8]}")
    _raw, text = rp._human_record(repo, session, uid)
    consent = _consent(repo, session, uid, text, packets[0])
    _scan_packets(repo, packets)
    if not (repo.store / "store.json").exists():
        with rp._locked(repo, session):
            if not (repo.store / "store.json").exists():
                rp._bootstrap(repo)
        repo.refresh()
    first = packets[0]
    claim_op = f"{HUMAN_OP_PREFIX}{uid}"
    base = _op_base(repo, first, session)
    with _direction_lease(repo, session, uid):
        claim_direction(
            repo,
            plan=first.plan,
            session=session,
            uid=uid,
            act=HUMAN_ACT,
            op=claim_op,
            branch=first.branch,
            base=base,
        )
        try:
            op, retry = _select_attempt(repo, session, uid, HUMAN_ACT, packets, batch)
            outcome = _run_packets(
                repo,
                op=op,
                run=session,
                act=HUMAN_ACT,
                packets=packets,
                batch=batch,
                reserved=None,
                verified=None,
                consent=consent,
                retry=retry,
            )
        except (rp.Refusal, Failed):
            # D-2: a refused or failed attempt spends the direction only when one of its
            # attempts published; else it is released for a retry. A stop or a crash
            # leaves it pending, and the rerun resumes it.
            settle_direction(
                repo,
                session=session,
                uid=uid,
                op=claim_op,
                state=CLAIM_SPENT
                if _direction_published(base, claim_op)
                else CLAIM_RELEASED,
            )
            raise
        settle_direction(repo, session=session, uid=uid, op=claim_op, state=CLAIM_SPENT)
        return outcome


def _granted_op(repo: rp.Repo) -> Op:
    """The op named by ``{{PROJECT_NAME_UPPER}}_COMMIT_GRANT``: one safe id, one op file, one reservation."""
    grant = os.environ.get(GRANT_ENV, "")
    if not rp.SAFE_NAME_RE.fullmatch(grant) or ".." in grant:
        raise rp.Refusal("grant", "grant_id")
    hits = sorted((repo.store / "ops").glob(f"*/*/{grant}/op.json"))
    if len(hits) != 1:
        raise rp.Refusal("grant", f"op_files:{len(hits)}")
    data = rp._read_bytes(hits[0])
    try:
        record = cast(dict[str, Any], rp._load_json(data or b""))
        identity = cast(dict[str, Any], record["identity"])
        plan = cast(str, identity["plan"])
        run = cast(str, identity["run_id"])
        act = cast(str, identity["act"])
    except (ValueError, KeyError, TypeError) as exc:
        raise rp.Refusal("grant", "op_file") from exc
    if act not in ACT_FOR_PHASE.values() or identity.get("op") != grant:
        raise rp.Refusal("grant", "op_identity")
    if plan == PLANLESS:
        # The hook grant names a plan grant's reservation; a planless op has none.
        raise rp.Refusal("grant", "planless")
    verified = _reserved(repo, plan, act, grant)
    packet = _parse_packet(record.get("packet"))
    if packet.digest != identity.get("packet_digest") or packet.plan != plan:
        raise rp.Refusal("packet_mismatch", "op_packet")
    rp._check_branch(verified.reference.auth, packet.branch)
    ctx = Op(
        repo=repo,
        op=grant,
        run=run,
        act=act,
        packet=packet,
        parent=packet.parent,
        folder=hits[0].parent,
        candidate=Path(cast(str, record["candidate_path"])),
        record=record,
        reserved=grant,
        verified=verified,
    )
    ctx.parent = cast(str, ctx.evidence("prepared").get("parent", packet.parent))
    return ctx


def _expect(ctx: Op, args: argparse.Namespace) -> None:
    """The script's exact parameters must name the granted op's packet: else ``packet_mismatch``."""
    tree = cast(str | None, ctx.evidence("blobs_stored").get("tree"))
    base = cast(str | None, args.expect_base)
    if base and base != ctx.parent:
        raise rp.Refusal("packet_mismatch", "expected_base")
    expected_tree = cast(str | None, args.expect_tree)
    if expected_tree:
        if tree is None:
            raise rp.Refusal("phase_order", "blobs_stored")
        if expected_tree != tree:
            raise rp.Refusal("packet_mismatch", "expected_tree")
    if args.scope_manifest:
        text = rp._read_text(Path(cast(str, args.scope_manifest)))
        scope = {
            line.strip()
            for line in (text or "").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        if scope != set(ctx.packet.paths):
            raise rp.Refusal("packet_mismatch", "scope_manifest")
    message_bytes: bytes | None = None
    if args.message_file:
        message_bytes = rp._read_bytes(Path(cast(str, args.message_file)))
        try:
            same = (
                canonical_message((message_bytes or b"").decode("utf-8"))
                == ctx.packet.message
            )
        except (rp.Refusal, UnicodeDecodeError):
            same = False
        if not same:
            raise rp.Refusal("packet_mismatch", "message_file")
    if args.descriptor:
        data = rp._read_bytes(Path(cast(str, args.descriptor)))
        try:
            descriptor = cast(dict[str, Any], rp._load_json(data or b""))
        except (ValueError, UnicodeDecodeError) as exc:
            raise rp.Refusal("packet_mismatch", "descriptor") from exc
        name, email = ctx.packet.author
        wanted: dict[str, Any] = {
            "parent": ctx.parent,
            "tree": tree,
            "author_name": name,
            "author_email": email,
            "signing_fingerprint": ctx.packet.fingerprint,
        }
        if message_bytes is not None:
            wanted["message_sha256"] = rp._sha256(message_bytes)
        if not isinstance(descriptor, dict) or any(
            descriptor.get(key) != value for key, value in wanted.items()
        ):
            raise rp.Refusal("packet_mismatch", "descriptor")


def _step_route(repo: rp.Repo, args: argparse.Namespace) -> Outcome:
    """``--step``: one phase of the granted op, after its predecessor (else ``phase_order``)."""
    ctx = _granted_op(repo)
    _expect(ctx, args)
    step = cast(str, args.step)
    check = _failure(ctx)
    if check is not None:
        raise Failed(check)
    done = ctx.done()
    target = STEP_TARGET[step]
    if target not in done:
        if STEP_NEEDS[step] not in done:
            raise rp.Refusal("phase_order", STEP_NEEDS[step])
        _drive(ctx, target)
    out: dict[str, Any] = {
        "result": "done",
        "op": ctx.op,
        "phase": step,
        "parent": ctx.parent,
        "tree": ctx.tree,
        "paths": list(ctx.packet.paths),
    }
    if "published" in ctx.done():
        out["commit"] = ctx.commit
    return rp.EXIT_OK, out


# -- the lane-route policy --------------------------------------------------------


class LaneRoute(TypedDict):
    """The lane-route policy: ``required`` turns the refusals on; ``exempt`` slugs keep the old route."""

    required: bool
    exempt: tuple[str, ...]


def _route_bad(why: str, detail: str) -> rp.Refusal:
    return rp.Refusal(f"lane_route_bad:{why}", detail)


def lane_route(main: Path) -> LaneRoute:
    """The policy in ``main``/``LANE_ROUTE_FILE``; a missing file is not required, no exempt slug.

    The file is one JSON object with exactly the keys ``schema`` (``lane-route/1``),
    ``required`` (a JSON bool: ``1`` and ``"true"`` are refused) and ``exempt`` (a list of
    unique slugs that match ``LANE_SLUG_RE``). A key may occur once: JSON keeps the
    last of repeated keys, so ``"required": true, "required": false`` would turn the
    refusals off without a word.

    Raises:
        rp.Refusal: ``lane_route_bad:<why>``, with ``<why>`` one of ``unreadable``,
            ``json``, ``key_repeated:<key>``, ``extra_key:<key>``, ``schema``,
            ``required``, ``exempt``, ``exempt_slug`` and ``exempt_repeated``.
    """
    path = main / LANE_ROUTE_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"required": False, "exempt": ()}
    except OSError as exc:
        raise _route_bad("unreadable", f"cannot read {path}: {exc}") from None

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: dict[str, object] = {}
        for key, value in pairs:
            if key in seen:
                raise _route_bad(
                    f"key_repeated:{key}", f"{path}: key {key!r} is repeated"
                )
            seen[key] = value
        return seen

    try:
        data: object = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _route_bad("json", f"{path}: {exc}") from None
    if not isinstance(data, dict):
        raise _route_bad("json", f"{path} is not one JSON object")
    policy = cast(dict[str, object], data)
    extra = sorted(key for key in policy if key not in LANE_ROUTE_KEYS)
    if extra:
        raise _route_bad(f"extra_key:{extra[0]}", f"{path}: unknown key {extra[0]!r}")
    if policy.get("schema") != LANE_ROUTE_SCHEMA:
        raise _route_bad("schema", f"{path}: schema is not {LANE_ROUTE_SCHEMA!r}")
    required = policy.get("required")
    if not isinstance(required, bool):
        raise _route_bad("required", f"{path}: required is not a JSON bool")
    exempt = policy.get("exempt")
    if not isinstance(exempt, list):
        raise _route_bad("exempt", f"{path}: exempt is not a list")
    slugs: list[str] = []
    for item in cast(list[object], exempt):
        if not isinstance(item, str) or not LANE_SLUG_RE.fullmatch(item):
            raise _route_bad("exempt_slug", f"{path}: {item!r} is not a worktree slug")
        if item in slugs:
            raise _route_bad("exempt_repeated", f"{path}: {item!r} is listed twice")
        slugs.append(item)
    return {"required": required, "exempt": tuple(slugs)}


def _refuse_lane_worktree(repo: rp.Repo) -> None:
    """The command line in a non-exempt lane worktree under ``required``: ``lane_worktree``.

    A lane worktree is a linked worktree (``top`` is not ``main``) whose HEAD is
    ``lane/<slug>``. The main tree, a detached candidate and an exempt slug pass.

    Raises:
        rp.Refusal: ``lane_worktree``, a ``lane_route_bad:<why>`` of ``lane_route``, or
            ``disabled`` when git cannot name the worktree's branch.
    """
    policy = lane_route(repo.main)
    if not policy["required"]:
        return
    try:
        if os.path.samefile(repo.top, repo.main):
            return
    except OSError as exc:
        raise rp.Refusal(
            "disabled", f"cannot compare {repo.top} with {repo.main}: {exc}"
        ) from exc
    try:
        head = rp._git(repo.top, "symbolic-ref", "--quiet", "HEAD", check=False)
    except (rp.GitError, OSError, UnicodeDecodeError) as exc:
        raise rp.Refusal("disabled", f"symbolic-ref HEAD in {repo.top}: {exc}") from exc
    if not head.startswith(LANE_BRANCH_PREFIX):
        return
    slug = head[len(LANE_BRANCH_PREFIX) :]
    if slug in policy["exempt"]:
        return
    raise rp.Refusal(
        "lane_worktree",
        f"{repo.display} is the lane worktree of {slug} and {LANE_ROUTE_FILE} requires "
        "the lane route: commit there with tools/lanes.py commit, and land with "
        "tools/lanes.py land prepare",
    )


# -- the command line -----------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    """The driver's command line (EA-8 (a), EA-10)."""
    parser = argparse.ArgumentParser(
        prog="commit_batch",
        description="Commit one packet or batch as signed, published commits (R§4.5).",
        allow_abbrev=False,
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--phase", choices=sorted(ACT_FOR_PHASE))
    parser.add_argument("--op")
    parser.add_argument("--packet")
    parser.add_argument("--run")
    parser.add_argument("--human-directed", action="store_true")
    parser.add_argument("--session")
    parser.add_argument("--message-uuid")
    parser.add_argument("--step", choices=sorted(STEP_TARGET))
    parser.add_argument("--expect-base")
    parser.add_argument("--expect-tree")
    parser.add_argument("--scope-manifest")
    parser.add_argument("--message-file")
    parser.add_argument("--descriptor")
    return parser


Handler = Callable[[rp.Repo, argparse.Namespace], Outcome]


def _route(parser: argparse.ArgumentParser, args: argparse.Namespace) -> Handler:
    """Exactly one complete route; anything else is a usage error (exit 2)."""
    grant = args.phase is not None or args.op is not None or args.run is not None
    human = (
        bool(args.human_directed)
        or args.session is not None
        or args.message_uuid is not None
    )
    step = args.step is not None
    exact = any(
        value is not None
        for value in (
            args.expect_base,
            args.expect_tree,
            args.scope_manifest,
            args.message_file,
            args.descriptor,
        )
    )
    if [grant, human, step].count(True) != 1:
        parser.error("choose exactly one route: --phase, --human-directed or --step")
    if exact and not step:
        parser.error("the exact parameters belong to --step")
    if grant:
        if args.phase is None or args.op is None or args.packet is None:
            parser.error("--phase needs --op and --packet")
        return _grant_route
    if human:
        if not (
            args.human_directed and args.session and args.message_uuid and args.packet
        ):
            parser.error(
                "--human-directed needs --session, --message-uuid and --packet"
            )
        return _human_route
    if args.packet is not None:
        parser.error("--step reads the op's own packet")
    return _step_route


def _emit(out: Mapping[str, Any]) -> None:
    """One JSON object on stdout."""
    sys.stdout.write(json.dumps(out, sort_keys=True, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    """Scrub the inherited Git environment, run one route, print one JSON object."""
    for key in list(os.environ):
        if key.upper().startswith("GIT_") or key in SCRUBBED_ENV:
            del os.environ[key]
    parser = _parser()
    args = parser.parse_args(argv)
    handler = _route(parser, args)
    try:
        repo = rp._open_repo(Path(cast(str, args.repo)))
        _refuse_lane_worktree(repo)
        _check_sync_pending(repo)
        code, out = handler(repo, args)
    except rp.Refusal as exc:
        rp._log("commit_refused", reason=exc.reason, detail=exc.detail)
        _emit({"result": "refused", "reason": exc.reason})
        return rp.EXIT_REFUSED
    except Stopped as exc:
        rp._log("commit_stopped", detail=str(exc))
        _emit({"result": "stopped", "reason": "ambiguous"})
        return rp.EXIT_REFUSED
    except Failed as exc:
        _emit({"result": "failed", "reason": f"candidate:{exc.check}"})
        return rp.EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 - the last guard prints one JSON object
        rp._log("internal_error", error=repr(exc), trace=traceback.format_exc())
        _emit({"result": "error", "reason": "internal"})
        return rp.EXIT_CRASH
    _emit(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
