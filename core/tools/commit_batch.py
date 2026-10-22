"""The commit transaction driver (R§4.5, EA-8): one packet or one batch to signed, published commits.

``python -m tools.commit_batch --repo R`` takes the grant route ``--phase plan|exec|finalize
--op <id> --packet <file> [--run <run_id>]`` or the human route ``--human-directed --session <s>
--message-uuid <u> --packet <file>``. ``agent-commit.ps1`` runs one phase of a granted op with
``--step candidate|publish|index`` and the op id in ``{{PROJECT_NAME_UPPER}}_COMMIT_GRANT`` (EA-10).

Every op journals ``started`` and ``done`` around each phase in
``<store>/ops/<plan>/<run>/<op>/op.json``: ``prepared``, ``blobs_stored``, ``candidate_built``,
``candidate_verified``, ``published``, ``index_reconciled``, ``cleanup_done`` and ``reconciled``.
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
import subprocess
import sys
import time
import traceback
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from tools import run_parameters as rp

PACKET_SCHEMA = "commit-packet/1"
BATCH_SCHEMA = "commit-batch/1"
OP_SCHEMA = "commit-op/1"
BATCH_OP_SCHEMA = "commit-batch-op/1"
MANIFEST_SCHEMA = "candidate-worktree/1"
MANIFEST_NAME = "candidate-worktree.json"
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
    r"\s*(?:(?:please|ok|okay|yes|now|go\s+ahead\s+and)\b[\s,]*)*commit\b(?P<rest>.*)",
    re.IGNORECASE | re.DOTALL,
)
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


def _read_input(path: Path, phase: str | None) -> tuple[list[Packet], bool]:
    """The packet, or the batch's packets (``exec`` only), each validated before any write."""
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
    _schema(phase == "exec", "batch_phase")
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
    """Run git with the scrubbed environment; never raises on a non-zero exit."""
    return subprocess.run(  # noqa: S603 - fixed argv
        ["git", *args],
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


def _append(ctx: Op, phase: str, status: str, evidence: Mapping[str, Any]) -> None:
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


# -- authority ------------------------------------------------------------------------------


def _reserved(repo: rp.Repo, plan: str, act: str, op: str) -> rp.Verified:
    """V-A to V-10 for the act, then ``consumed[plan][act]`` names this op: else ``not_reserved``."""
    rp._gate(repo, act)
    try:
        verified = rp._verify_plan(repo, plan, act)
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
    ctx.verified = _reserved(ctx.repo, ctx.packet.plan, ctx.act, ctx.reserved)


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
    plans = repo.top / "docs" / "execution" / "plans"
    for task in sorted(plans.glob("*/task.md")):
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
            meta = rp._frontmatter(rp._read_text(task) or "")
        except rp.Refusal:
            continue
        complete = (meta or {}).get("status") == "complete"
        (manual if kind == "manual" and not complete else named_only).append(plan)
    return bound + manual, bound + manual + named_only


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


def _consent(
    repo: rp.Repo, session: str, uid: str, text: str, packet: Packet
) -> dict[str, Any]:
    """D-34: the first directing sentence whose scope is this packet's plan, branch and repo.

    A sentence that names no plan resolves only to the one plan of ``_direction_plans``
    (R§4.5 "resolves only to ... one ..., never to more").
    """
    unnamed, named_plans = _direction_plans(repo, session)
    proc = _run_git(repo.top, "symbolic-ref", "-q", "--short", "HEAD")
    current = proc.stdout.decode("utf-8", errors="replace").strip()
    repo_name = Path(repo.main_display).name.lower()
    for match in SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        if not sentence or sentence.endswith("?"):
            continue
        clause = sentence.rstrip(".!").strip()
        stripped = PUSH_ONLY_RE.sub("", clause)
        direct = DIRECT_RE.fullmatch(stripped)
        if direct is None:
            continue
        lowered = stripped.lower()
        if "n't" in lowered or set(WORD_RE.findall(lowered)) & NEGATORS:
            continue
        rest = direct.group("rest")
        named = PLAN_THE_RE.search(rest) or PLAN_NAMED_RE.search(rest)
        if named is not None:
            name = named.group(1).lower()
            hits = [plan for plan in named_plans if name in (plan, plan[11:])]
        else:
            hits = list(unnamed)
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
    staged = _git_ok(ctx.candidate, "diff-index", "--cached", "--name-only", ctx.parent)
    if not set(staged.splitlines()) <= set(ctx.packet.paths):
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
    # Hooks in the candidate run on the repository's environment: a ``uv run`` there would
    # otherwise build ``<candidate>/.venv`` (``ignored_residue``).
    venv = ctx.repo.top / ".venv"
    if venv.is_dir():
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
    """
    root = _candidate_root(repo)
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
    packets, batch = _read_input(Path(cast(str, args.packet)), phase)
    _candidate_root(repo)
    verified = _reserved(repo, packets[0].plan, act, op)
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
    """``--human-directed``: a typed human message that directs this commit (D-34)."""
    session = cast(str, args.session)
    uid = cast(str, args.message_uuid)
    _check_name(session)
    _check_name(uid)
    packets, _batch = _read_input(Path(cast(str, args.packet)), None)
    _candidate_root(repo)
    _raw, text = rp._human_record(repo, session, uid)
    consent = _consent(repo, session, uid, text, packets[0])
    if not (repo.store / "store.json").exists():
        with rp._locked(repo, session):
            if not (repo.store / "store.json").exists():
                rp._bootstrap(repo)
        repo.refresh()
    return _run_packets(
        repo,
        op=f"human-{uid}",
        run=session,
        act=HUMAN_ACT,
        packets=packets,
        batch=False,
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
