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
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import stat
import subprocess
import sys
import time
import traceback
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast

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
# The human route's op is ``human-<message uuid>``; its folder holds the direction claim that
# spends the sentence once across ``commit_batch.py`` and ``lanes.py land publish`` (EA-58 (3)).
HUMAN_OP_PREFIX = "human-"
DIRECTION_CLAIM_NAME = "direction.json"
DIRECTION_CLAIM_SCHEMA = "direction-claim/1"
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
    "gate": frozenset({"tree", "result"}),
    "verdict": frozenset({"tree", "verdict"}),
}
LAND_NESTED_OBJECTS = {
    "carrier": frozenset({"task", "plan", "grouping"}),
    "gate": frozenset({"tree"}),
    "verdict": frozenset({"tree"}),
}
# The publication intent and its ``done`` evidence (``_step_published``).
PUBLISHED_KEYS = frozenset({"repo", "ref", "ref_old", "ref_new", "op", "candidate"})
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
ATTRIBUTION_RE = re.compile(
    r"(?i)(co-authored-by:\s*(claude|anthropic)|generated\s+(with|by)\s+(claude|anthropic)"
    r"|authored\s+(with|by)\s+(claude|anthropic))"
)
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
WITHDRAWERS = frozenset(
    {"wait", "hold", "stop", "cancel", "nevermind", "if", "unless", "once", "when"}
    | {"after", "before", "until"}
)
WITHDRAW_LEADS = frozenset({"no", "nope", "actually"})
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
    _schema(rp._match(rp.SLUG_RE, raw["plan"]), "plan")
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
    if ATTRIBUTION_RE.search(message.decode("utf-8")):
        raise rp.Refusal("attribution")
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
) -> Op:
    """The op's context: an existing op must carry this packet; a new op binds its parent."""
    folder = repo.store / "ops" / packet.plan / run / op
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
    """Publication time: re-run V-A to V-10 and the reservation (a closure since prepared)."""
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
    """R4-F1: whether the rest of the message withdraws, conditions or reports a direction.

    Another sentence withdraws it when it holds a withdrawing word ("wait", "if", "until"),
    starts with "no" or "actually", or talks of committing in a negated, questioning or
    conditional form. A request question also needs to open the message, to name no
    alternative ("or", "whether") and to stand as its only question. A scoping sentence
    such as "Do not push." withdraws nothing.
    """
    if question:
        if position != 0:
            return True
        if set(WORD_RE.findall(sentences[position].lower())) & ALTERNATIVES:
            return True
    for index, other in enumerate(sentences):
        if index == position:
            continue
        lowered = PUSH_ONLY_RE.sub("", other).lower()
        words = WORD_RE.findall(lowered)
        if not words:
            continue
        asks = other.endswith("?")
        if question and asks:
            return True
        if set(words) & WITHDRAWERS or (words and words[0] in WITHDRAW_LEADS):
            return True
        if any(word.startswith("commit") for word in words) and (
            asks or "n't" in lowered or set(words) & NEGATORS
        ):
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
        named = PLAN_THE_RE.search(rest) or PLAN_NAMED_RE.search(rest)
        if named is not None:
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
    path = repo.store / "ops" / plan / run / op / "batch.json"
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


def _claim_direction(
    repo: rp.Repo, *, plan: str, session: str, uid: str, act: str, op: str
) -> None:
    """Spend the human direction ``uid`` on one act: once per message uuid (EA-58 (3)).

    The claim ``ops/<plan>/<session>/human-<uid>/direction.json`` sits in the folder of the
    commit route's op ``human-<uid>``, so one typed sentence authorizes at most one act across
    ``commit_batch.py --human-directed`` and ``lanes.py land publish``. The same act and op
    claim again (a rerun after a crash); any other act or op refuses ``direction_spent``. A
    land also refuses a direction whose commit op folder holds anything but the claim (a
    commit op spent before claims existed). The claim has no ``identity``, so the pending-op
    readers and the ref guard never list it.

    Raises:
        rp.Refusal: ``direction_spent``, or a store lock refusal.
    """
    name = f"{HUMAN_OP_PREFIX}{uid}"
    claim = {
        "schema": DIRECTION_CLAIM_SCHEMA,
        "message_uuid": uid,
        "act": act,
        "op": op,
        "plan": plan,
        "session": session,
    }
    with rp._locked(repo, session):
        for path in sorted(repo.store.glob(f"ops/*/*/{name}/{DIRECTION_CLAIM_NAME}")):
            data = rp._read_bytes(path)
            try:
                held = rp._load_json(data or b"")
            except ValueError:
                held = None
            spent = cast(dict[str, Any], held) if isinstance(held, dict) else {}
            if (spent.get("act"), spent.get("op")) != (act, op):
                raise rp.Refusal(
                    "direction_spent",
                    f"{uid} already directed {spent.get('act')} {spent.get('op')} "
                    f"({rp.display_path(path)})",
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
        target = repo.store / "ops" / plan / session / name / DIRECTION_CLAIM_NAME
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            rp._write_atomic(target, rp._json_bytes(claim))


def spend_direction(repo: rp.Repo, session: str, uid: str, plan: str, op: str) -> None:
    """Spend the ``--human-directed`` direction ``uid`` on the land op ``op``, once.

    ``lanes.py land publish`` calls this after ``human_direction`` and its own checks,
    before the publication: the land and the commit route share one claim per message
    uuid (``_claim_direction``), so a second use of the sentence refuses on either route.

    Raises:
        rp.Refusal: ``containment`` (an unsafe name) or ``direction_spent``.
    """
    for value in (session, uid, plan, op):
        _check_name(value)
    _claim_direction(repo, plan=plan, session=session, uid=uid, act=LAND_ACT, op=op)


def store_land_message(ctx: LandOp, text: str) -> None:
    """Keep the canonical form of the land's commit message beside its journal.

    ``land publish`` commits C with these bytes (``_commit_candidate`` reads the same
    ``message.txt``). The journal folder exists once the first land entry is written.

    Raises:
        rp.Refusal: ``message`` (NUL, surrogate or empty text).
    """
    data = canonical_message(text)
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
    repo: rp.Repo, land: LandOp, *, act: str, reserved: str | None
) -> _LandCandidate:
    """The tree-adapter ``Op`` of a land: its packet, candidate path and journal record.

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
        land_tree=tree,
    )


def land_publish(repo: rp.Repo, land: LandOp, *, act: str, reserved: str | None) -> str:
    """Step 7 (AC-785.19): commit tree(T) on P in a candidate and publish it as C on main.

    ``repo`` is the authority handle of the main repository. The steps are the commit
    route's: ``_build_candidate`` (a detached worktree at P, index and files at T), the
    pre-hook checks, ``git commit -S`` with the stored message, the post-hook checks
    (``hook_drift`` when a hook changes the tree), then ``_step_published``: the intent
    ``{repo, ref, ref_old, ref_new, op, candidate}`` in the land journal and the ref update
    with expected old value P. ``reserved`` is the op of a reserved grant (re-verified at
    publication), None for the human route. The candidate is removed afterwards.

    Returns:
        C, the published commit.

    Raises:
        rp.Refusal: ``message`` (no stored message), ``signing_unconfigured``,
            ``candidate_foreign``, a check (``index_tree``, ``unstaged_drift``,
            ``unlisted_staged``, ``commit``, ``hook_drift``, ``ignored_residue:<path>``,
            ``parent``, ``identity``, ``signature``) or ``publish_refused``.
        Stopped: ``ref_holds_candidate``.
    """
    ctx = _land_context(repo, land, act=act, reserved=reserved)
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
    ``publication_unclear``. The publication was authorized when it started, so no grant is
    re-verified here. The candidate that the crash left is removed afterwards.

    Returns:
        C, the published commit.

    Raises:
        rp.Refusal: ``publication_unclear``, ``message``, ``signing_unconfigured`` or
            ``publish_refused``.
    """
    ctx = _land_context(repo, land, act=act, reserved=None)
    fields = land.fields()
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

    Raises:
        rp.Refusal: ``sync_unexplained:<path>``, ``sync_refused`` (read-tree failed),
            ``sync_incomplete:<path>`` or ``sync_unclear`` (no published C in the journal).
        rp.GitError: a git step failed.
    """
    fields = land.fields()
    parent = str(fields["P"])
    commit = str(fields.get("ref_new", ""))
    if not _land_has(land, "published", ("done",)) or not OBJECT_ID_RE.fullmatch(
        commit
    ):
        raise rp.Refusal("sync_unclear", f"land {land.op} has no published C")
    last = land.journal[-1]
    if (last["phase"], last["status"]) != ("land:sync", "started"):
        land_start(land, "land:sync")
    top = repo.top
    _run_git(top, "update-index", "-q", "--refresh")
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
    paths = sorted(changed - {live})
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
    _run_git(top, "update-index", "-q", "--refresh")
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
) -> Outcome:
    """Drive one op, or each sub-op ``<op>/<n>`` of a batch on the previous sub-op's commit.

    The batch record is written once the first sub-op opens, before any sub-op is driven.
    An op id spent as one form (one packet, or a batch) refuses the other: ``packet_mismatch``.
    A batch is spent from its first sub-op's folder ``<op>/1``, which a crash can leave
    before ``batch.json`` exists (R4-F2).
    """
    root = _candidate_root(repo)
    folder = repo.store / "ops" / packets[0].plan / run / op
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


# -- the routes -----------------------------------------------------------------------------


def _grant_route(repo: rp.Repo, args: argparse.Namespace) -> Outcome:
    """``--phase``: a reserved op of the phase's act."""
    op = cast(str, args.op)
    run = cast(str, args.run or DEFAULT_RUN)
    _check_name(op)
    _check_name(run)
    phase = cast(str, args.phase)
    act = ACT_FOR_PHASE[phase]
    packets, batch = _read_input(Path(cast(str, args.packet)), phase == "exec")
    _candidate_root(repo)
    verified = _reserved(repo, packets[0].plan, act, op, packets[0].branch)
    return _run_packets(
        repo,
        op=op,
        run=run,
        act=act,
        packets=packets,
        batch=batch,
        reserved=op,
        verified=verified,
        consent=None,
    )


def _human_route(repo: rp.Repo, args: argparse.Namespace) -> Outcome:
    """``--human-directed``: a typed human message that directs this commit or batch (D-34)."""
    session = cast(str, args.session)
    uid = cast(str, args.message_uuid)
    _check_name(session)
    _check_name(uid)
    packets, batch = _read_input(Path(cast(str, args.packet)), True)
    _candidate_root(repo)
    _raw, text = rp._human_record(repo, session, uid)
    consent = _consent(repo, session, uid, text, packets[0])
    if not (repo.store / "store.json").exists():
        with rp._locked(repo, session):
            if not (repo.store / "store.json").exists():
                rp._bootstrap(repo)
        repo.refresh()
    _claim_direction(
        repo,
        plan=packets[0].plan,
        session=session,
        uid=uid,
        act=HUMAN_ACT,
        op=f"{HUMAN_OP_PREFIX}{uid}",
    )
    return _run_packets(
        repo,
        op=f"{HUMAN_OP_PREFIX}{uid}",
        run=session,
        act=HUMAN_ACT,
        packets=packets,
        batch=batch,
        reserved=None,
        verified=None,
        consent=consent,
    )


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
