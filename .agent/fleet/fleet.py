#!/usr/bin/env python3
"""Fleet MVP: one stdlib-only file that is the hub, the member and the CLI.

SUPER runs ``hub``. Each member runs ``member``, which polls the hub, runs one task at a time and
posts the result. Members never accept connections. Plan:
docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import fnmatch
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ENVELOPE_VERSION = 1
MANIFEST_VERSION = 1
MANIFEST_FIELDS = ("v", "project", "requires", "commands")
ENVELOPE_FIELDS = (
    "v", "id", "task_id", "from", "to", "kind", "created",
    "body", "refs", "reply_to", "requires_human", "start_quote",
)
TASK_STATES = ("submitted", "working", "input-required", "completed", "failed", "canceled", "rejected")
TERMINAL_STATES = ("completed", "failed", "canceled", "rejected")
TRANSITIONS = frozenset({
    ("submitted", "working"),
    ("working", "completed"),
    ("working", "failed"),
    ("working", "rejected"),
})
TASK_KINDS = ("ping", "run", "agent")
SEND_POLICY = {"orchestrator": frozenset({"ping", "run"}), "member": frozenset()}
RESERVED_NAMES = ("orchestrator", "hub")
OPEN_ROUTES = frozenset({"GET /bootstrap/fleet.py", "GET /bootstrap/bootstrap.md", "POST /v1/pair"})
NAME_RE = re.compile(r"^[a-z0-9-]{1,32}$")
HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_VALUE_PATTERNS = tuple(re.compile(p) for p in (
    r"sk-ant-", r"ghp_", r"github_pat_", r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY",
))
SECRET_PATH_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "id_rsa*", "id_ed25519*", "*credentials*",
)
SECRET_PATH_ALLOW = ("*.example", "*.sample", "*.template")
CAPABILITY_TOOLS = ("python", "git", "uv", "node", "npm", "go", "claude", "codex", "agent", "agy")
FORBIDDEN_COMMANDS = frozenset({
    "git", "gh", "claude", "codex", "agent", "agy", "cmd", "powershell", "pwsh", "sh", "bash",
})
FIREWALL_RULE = "Fleet hub 8770"
BOOTSTRAP_STOPS = ("install-agent-cli", "run-pair", "confirm-fingerprint", "run-approve", "firewall-rule")
EXIT_CODES = {
    "ok": 0, "failed": 1, "refused": 2, "rejected": 3, "timeout": 4, "offline": 5, "tools_missing": 6,
}
MAX_JSON_BYTES = 1024 * 1024
MAX_BLOB_BYTES = 256 * 1024 * 1024
MAX_DRAIN_BYTES = 2 * MAX_JSON_BYTES
MAX_PENDING = 8
POLL_S = 5
OFFLINE_AFTER_S = 30
HANDLER_TIMEOUT_S = 30
REQUEST_TIMEOUT_S = 30
RETRY_S = 1
WAIT_POLL_S = 0.5
CAPABILITY_TIMEOUT_S = 10
DEFAULT_PORT = 8770
DEFAULT_RUN_TIMEOUT_S = 1800
MAX_RUN_TIMEOUT_S = 86400
RUN_BODY_FIELDS = ("project", "command", "timeout_s")
RUN_REFS_FIELDS = ("commit", "tree", "bundle")
SNAPSHOT_IDENTITY = {
    "GIT_AUTHOR_NAME": "fleet", "GIT_AUTHOR_EMAIL": "fleet@fleet.invalid",
    "GIT_COMMITTER_NAME": "fleet", "GIT_COMMITTER_EMAIL": "fleet@fleet.invalid",
}
REFUSALS = {
    "bad_json": 400, "unknown_field": 400, "missing_field": 400, "bad_field": 400, "bad_version": 400,
    "bad_name": 400,
    "unauthorized": 401, "not_approved": 401, "revoked": 401,
    "role_not_allowed": 403, "sender_not_allowed": 403, "from_mismatch": 403, "not_your_task": 403,
    "blob_not_yours": 403,
    "not_found": 404,
    "duplicate_id": 409, "name_taken": 409, "bad_transition": 409, "stale_session": 409,
    "too_large": 413,
    "unknown_kind": 422, "kind_not_enabled": 422, "secret_in_message": 422, "missing_blob": 422,
    "blob_hash_mismatch": 422, "bad_manifest": 422, "unknown_member": 422,
    "pending_full": 429,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    kind TEXT NOT NULL,
    envelope TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_task ON messages (task_id, seq);
CREATE INDEX IF NOT EXISTS messages_recipient ON messages (recipient, kind, seq);
CREATE TRIGGER IF NOT EXISTS messages_no_update BEFORE UPDATE ON messages
    BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TRIGGER IF NOT EXISTS messages_no_delete BEFORE DELETE ON messages
    BEGIN SELECT RAISE(ABORT, 'append_only'); END;
CREATE TABLE IF NOT EXISTS members (
    name TEXT PRIMARY KEY,
    key_sha256 TEXT NOT NULL,
    session TEXT,
    last_seen REAL,
    capabilities TEXT
);
CREATE TABLE IF NOT EXISTS task_blobs (
    sha256 TEXT NOT NULL,
    member TEXT NOT NULL,
    PRIMARY KEY (sha256, member)
);
"""


def new_id() -> str:
    return uuid.uuid4().hex


def fleet_home() -> Path:
    return Path(os.environ.get("FLEET_HOME") or Path.home() / ".agent" / "fleet")


def has_secret(value) -> bool:
    text = json.dumps(value)
    return any(p.search(text) for p in SECRET_VALUE_PATTERNS)


def validate_envelope(env) -> str | None:
    """Return the refusal code for a message, or None when it is acceptable."""
    if not isinstance(env, dict):
        return "bad_json"
    for name in env:
        if name not in ENVELOPE_FIELDS:
            return f"unknown_field:{name}"
    for name in ENVELOPE_FIELDS:
        if name not in env:
            return f"missing_field:{name}"
    if env["v"] != ENVELOPE_VERSION:
        return "bad_version"
    for name in ("id", "task_id"):
        if not (isinstance(env[name], str) and HEX32_RE.fullmatch(env[name])):
            return f"bad_field:{name}"
    if not (isinstance(env["from"], str) and NAME_RE.fullmatch(env["from"])):
        return "bad_field:from"
    if not (isinstance(env["to"], str) and NAME_RE.fullmatch(env["to"])):
        return "bad_field:to"
    if not isinstance(env["created"], str):
        return "bad_field:created"
    for name in ("body", "refs"):
        if not isinstance(env[name], dict):
            return f"bad_field:{name}"
    if not (env["reply_to"] is None or isinstance(env["reply_to"], str)):
        return "bad_field:reply_to"
    if not isinstance(env["requires_human"], bool):
        return "bad_field:requires_human"
    if not (env["start_quote"] is None or isinstance(env["start_quote"], str)):
        return "bad_field:start_quote"
    if env["kind"] != "status" and env["kind"] not in TASK_KINDS:
        return "unknown_kind"
    if has_secret(env):
        return "secret_in_message"
    return None


def next_state_allowed(current: str, new: str) -> bool:
    return (current, new) in TRANSITIONS


def command_tool(argv0: str) -> str:
    """The tool an argv's first element names: basename, no extension, lower case."""
    return os.path.splitext(re.split(r"[\\/]", argv0)[-1])[0].lower()


def validate_manifest(obj) -> str | None:
    """Return the refusal code for a project manifest, or None when it is acceptable."""
    if not isinstance(obj, dict):
        return "bad_manifest:not_object"
    for name in obj:
        if name not in MANIFEST_FIELDS:
            return f"bad_manifest:unknown_key:{name}"
    for name in MANIFEST_FIELDS:
        if name not in obj:
            return f"bad_manifest:missing_key:{name}"
    if type(obj["v"]) is not int or obj["v"] != MANIFEST_VERSION:
        return "bad_manifest:version"
    if not (isinstance(obj["project"], str) and NAME_RE.fullmatch(obj["project"])):
        return "bad_manifest:project"
    requires = obj["requires"]
    if not (isinstance(requires, list) and all(isinstance(t, str) and t in CAPABILITY_TOOLS for t in requires)):
        return "bad_manifest:requires"
    commands = obj["commands"]
    if not (isinstance(commands, dict) and commands):
        return "bad_manifest:commands"
    for name, steps in commands.items():
        if not NAME_RE.fullmatch(name):
            return "bad_manifest:command_name"
        if not (isinstance(steps, list) and steps):
            return "bad_manifest:argv"
        for argv in steps:
            if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv) and argv[0]):
                return "bad_manifest:argv"
            tool = command_tool(argv[0])
            if tool in FORBIDDEN_COMMANDS:
                return f"bad_manifest:forbidden_command:{tool}"
    return None


class Store:
    """The hub's SQLite file. Every read-then-write runs inside ``tx()``."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @contextlib.contextmanager
    def tx(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    @contextlib.contextmanager
    def read(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def append(conn: sqlite3.Connection, env: dict) -> None:
        conn.execute(
            "INSERT INTO messages (id, task_id, sender, recipient, kind, envelope)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (env["id"], env["task_id"], env["from"], env["to"], env["kind"], json.dumps(env, sort_keys=True)),
        )

    def count_messages(self) -> int:
        with self.read() as c:
            return c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    def dump_messages(self) -> list[tuple]:
        with self.read() as c:
            return [tuple(r) for r in c.execute("SELECT * FROM messages ORDER BY seq")]


class Refuse(Exception):
    """A refusal with a closed code. The hub maps it to HTTP; the CLI prints it and exits 2."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def refusal_status(code: str) -> int:
    return REFUSALS[code.split(":", 1)[0]]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_message(sender: str, to: str, kind: str, body: dict, task_id: str | None = None) -> dict:
    return {
        "v": ENVELOPE_VERSION, "id": new_id(), "task_id": task_id or new_id(), "from": sender, "to": to,
        "kind": kind, "created": now_iso(), "body": body, "refs": {}, "reply_to": None,
        "requires_human": False, "start_quote": None,
    }


def hub_message(to: str, kind: str, body: dict, task_id: str | None = None) -> dict:
    return new_message("hub", to, kind, body, task_id)


TASK_KINDS_SQL = ", ".join(f"'{k}'" for k in TASK_KINDS)


def get_task(conn: sqlite3.Connection, task_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT envelope FROM messages WHERE task_id=? AND kind IN ({TASK_KINDS_SQL})", (task_id,)
    ).fetchone()
    return json.loads(row["envelope"]) if row else None


def latest_status(conn: sqlite3.Connection, task_id: str) -> dict:
    row = conn.execute(
        "SELECT envelope FROM messages WHERE task_id=? AND kind='status' ORDER BY seq DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return json.loads(row["envelope"])["body"] if row else {"state": "submitted"}


def tasks_in_state(conn: sqlite3.Connection, member: str, state: str) -> list[dict]:
    """Tasks addressed to a member whose latest status is ``state``, oldest first."""
    rows = conn.execute(
        f"""SELECT t.envelope FROM messages t
            WHERE t.recipient=? AND t.kind IN ({TASK_KINDS_SQL})
            AND COALESCE((SELECT json_extract(s.envelope, '$.body.state') FROM messages s
                          WHERE s.task_id=t.task_id AND s.kind='status' ORDER BY s.seq DESC LIMIT 1),
                         'submitted')=?
            ORDER BY t.seq""",
        (member, state),
    ).fetchall()
    return [json.loads(r["envelope"]) for r in rows]


def member_state(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT envelope FROM messages WHERE recipient=? AND kind='member' ORDER BY seq DESC LIMIT 1",
        (name,),
    ).fetchone()
    return json.loads(row["envelope"])["body"]["state"] if row else None


def approve_member(store: Store, name: str, code: str) -> None:
    with store.tx() as c:
        row = c.execute("SELECT key_sha256 FROM members WHERE name=?", (name,)).fetchone()
        if not row or member_state(c, name) != "pending" or not hmac.compare_digest(row["key_sha256"][:12], code):
            raise Refuse("bad_code")
        store.append(c, hub_message(name, "member", {"state": "approved"}))


def revoke_member(store: Store, name: str) -> None:
    with store.tx() as c:
        if member_state(c, name) not in ("pending", "approved"):
            raise Refuse("not_found")
        store.append(c, hub_message(name, "member", {"state": "revoked"}))


# Hub


@dataclass
class HubState:
    store: Store
    orchestrator_sha256: str
    offline_after: float
    bootstrap: dict[str, bytes]
    blobs: Path


@dataclass
class Request:
    hub: HubState
    method: str
    path: str
    params: dict[str, str]
    headers: dict
    rfile: object
    identity: str = ""
    role: str = ""
    body_read: bool = False

    def content_length(self) -> int:
        try:
            return max(int(self.headers.get("Content-Length", 0)), 0)
        except ValueError:
            raise Refuse("bad_json") from None

    def json(self):
        size = self.content_length()
        if size > MAX_JSON_BYTES:
            raise Refuse("too_large")
        self.body_read = True
        try:
            return json.loads(self.rfile.read(size))
        except (ValueError, UnicodeDecodeError):
            raise Refuse("bad_json") from None

    def drain(self) -> None:
        """Read an unread body, so that closing does not reset the reply in flight."""
        if self.body_read:
            return
        try:
            size = self.content_length()
            if 0 < size <= MAX_DRAIN_BYTES:
                self.rfile.read(size)
        except (Refuse, OSError):
            pass


def require_fields(obj, schema_fields: tuple[str, ...]) -> None:
    if not isinstance(obj, dict):
        raise Refuse("bad_json")
    for name in obj:
        if name not in schema_fields:
            raise Refuse(f"unknown_field:{name}")
    for name in schema_fields:
        if name not in obj:
            raise Refuse(f"missing_field:{name}")


def validate_pair(obj) -> None:
    require_fields(obj, ("name", "key_sha256"))
    name = obj["name"]
    if not (isinstance(name, str) and NAME_RE.fullmatch(name)) or name in RESERVED_NAMES:
        raise Refuse("bad_name")
    if not (isinstance(obj["key_sha256"], str) and HEX64_RE.fullmatch(obj["key_sha256"])):
        raise Refuse("bad_field:key_sha256")


def validate_hello(obj) -> None:
    require_fields(obj, ("capabilities",))
    caps = obj["capabilities"]
    if not isinstance(caps, dict):
        raise Refuse("bad_field:capabilities")
    for tool, version in caps.items():
        if tool not in CAPABILITY_TOOLS or not (version is None or isinstance(version, str)):
            raise Refuse("bad_field:capabilities")
    if has_secret(caps):
        raise Refuse("secret_in_message")


def validate_run_task(env: dict, blobs: Path) -> None:
    body, refs = env["body"], env["refs"]
    require_fields(body, RUN_BODY_FIELDS)
    require_fields(refs, RUN_REFS_FIELDS)
    for name in ("project", "command"):
        if not (isinstance(body[name], str) and NAME_RE.fullmatch(body[name])):
            raise Refuse(f"bad_field:{name}")
    if not (type(body["timeout_s"]) is int and 1 <= body["timeout_s"] <= MAX_RUN_TIMEOUT_S):
        raise Refuse("bad_field:timeout_s")
    for name, pattern in (("commit", HEX40_RE), ("tree", HEX40_RE), ("bundle", HEX64_RE)):
        if not (isinstance(refs[name], str) and pattern.fullmatch(refs[name])):
            raise Refuse(f"bad_field:{name}")
    if not (blobs / refs["bundle"]).exists():
        raise Refuse("missing_blob")


def route_pair(req: Request):
    obj = req.json()
    validate_pair(obj)
    with req.hub.store.tx() as c:
        state = member_state(c, obj["name"])
        if state in ("pending", "approved"):
            raise Refuse("name_taken")
        names = [r["name"] for r in c.execute("SELECT name FROM members")]
        if sum(member_state(c, n) == "pending" for n in names) >= MAX_PENDING:
            raise Refuse("pending_full")
        c.execute(
            "INSERT INTO members (name, key_sha256) VALUES (?, ?) ON CONFLICT (name) DO UPDATE"
            " SET key_sha256=excluded.key_sha256, session=NULL, last_seen=NULL, capabilities=NULL",
            (obj["name"], obj["key_sha256"]),
        )
        req.hub.store.append(c, hub_message(obj["name"], "member", {"state": "pending"}))
    return 200, {"state": "pending"}


def route_post_task(req: Request):
    env = req.json()
    code = validate_envelope(env)
    if code:
        raise Refuse(code)
    if env["kind"] == "status":
        raise Refuse("unknown_kind")
    if env["from"] != req.identity:
        raise Refuse("from_mismatch")
    allowed = SEND_POLICY[req.role]
    if env["kind"] not in allowed:
        raise Refuse("kind_not_enabled" if allowed else "sender_not_allowed")
    if env["kind"] == "run":
        validate_run_task(env, req.hub.blobs)
    with req.hub.store.tx() as c:
        if member_state(c, env["to"]) != "approved":
            raise Refuse("unknown_member")
        if c.execute(
            "SELECT 1 FROM messages WHERE id=? OR task_id=?", (env["id"], env["task_id"])
        ).fetchone():
            raise Refuse("duplicate_id")
        req.hub.store.append(c, env)
        if env["kind"] == "run":
            c.execute(
                "INSERT OR IGNORE INTO task_blobs (sha256, member) VALUES (?, ?)",
                (env["refs"]["bundle"], env["to"]),
            )
    return 200, {"task": env["task_id"], "state": "submitted"}


def route_members(req: Request):
    now = time.time()
    members = []
    with req.hub.store.read() as c:
        for r in c.execute("SELECT * FROM members ORDER BY name").fetchall():
            seen = r["last_seen"]
            members.append({
                "name": r["name"],
                "state": member_state(c, r["name"]),
                "online": seen is not None and now - seen <= req.hub.offline_after,
                "last_seen": seen,
                "capabilities": json.loads(r["capabilities"]) if r["capabilities"] else None,
            })
    return 200, {"members": members}


def route_hello(req: Request):
    obj = req.json()
    validate_hello(obj)
    session = new_id()
    with req.hub.store.tx() as c:
        c.execute(
            "UPDATE members SET session=?, last_seen=?, capabilities=? WHERE name=?",
            (session, time.time(), json.dumps(obj["capabilities"]), req.identity),
        )
        for task in tasks_in_state(c, req.identity, "working"):
            body = {"state": "failed", "reason": "member_restarted"}
            req.hub.store.append(c, hub_message(task["from"], "status", body, task["task_id"]))
    return 200, {"session": session}


def touch_session(conn: sqlite3.Connection, req: Request) -> None:
    row = conn.execute("SELECT session FROM members WHERE name=?", (req.identity,)).fetchone()
    given = req.headers.get("X-Fleet-Session", "")
    if not row["session"] or not hmac.compare_digest(row["session"], given):
        raise Refuse("stale_session")
    conn.execute("UPDATE members SET last_seen=? WHERE name=?", (time.time(), req.identity))


def route_heartbeat(req: Request):
    with req.hub.store.tx() as c:
        touch_session(c, req)
    return 200, {"ok": True}


def route_next(req: Request):
    with req.hub.store.tx() as c:
        touch_session(c, req)
        working = tasks_in_state(c, req.identity, "working")
        if working:
            # An idle member polling while it has a working task means the claim reply was lost.
            return 200, {"task": working[0]}
        waiting = tasks_in_state(c, req.identity, "submitted")
        if not waiting:
            return 200, {"task": None}
        task = waiting[0]
        req.hub.store.append(c, hub_message(task["from"], "status", {"state": "working"}, task["task_id"]))
    return 200, {"task": task}


def route_post_status(req: Request):
    env = req.json()
    code = validate_envelope(env)
    if code:
        raise Refuse(code)
    if env["from"] != req.identity:
        raise Refuse("from_mismatch")
    if env["kind"] != "status":
        raise Refuse("bad_field:kind")
    if env["task_id"] != req.params["id"]:
        raise Refuse("bad_field:task_id")
    new_state = env["body"].get("state")
    if not isinstance(new_state, str):
        raise Refuse("bad_field:body")
    with req.hub.store.tx() as c:
        touch_session(c, req)
        task = get_task(c, env["task_id"])
        if not task:
            raise Refuse("not_found")
        if task["to"] != req.identity:
            raise Refuse("not_your_task")
        row = c.execute("SELECT envelope FROM messages WHERE id=?", (env["id"],)).fetchone()
        if row:
            if row["envelope"] != json.dumps(env, sort_keys=True):
                raise Refuse("duplicate_id")
            return 200, {"result": "already_recorded"}
        if not next_state_allowed(latest_status(c, env["task_id"])["state"], new_state):
            raise Refuse("bad_transition")
        req.hub.store.append(c, env)
    return 200, {"result": "recorded"}


def route_get_task(req: Request):
    with req.hub.store.read() as c:
        task = get_task(c, req.params["id"])
        if not task:
            raise Refuse("not_found")
        status = latest_status(c, req.params["id"])
        row = c.execute("SELECT last_seen FROM members WHERE name=?", (task["to"],)).fetchone()
    seen = row["last_seen"] if row else None
    return 200, {
        "task": task["task_id"],
        "to": task["to"],
        "state": status["state"],
        "status": status,
        "member_online": seen is not None and time.time() - seen <= req.hub.offline_after,
    }


def route_bootstrap(req: Request):
    return 200, req.hub.bootstrap[req.path.rsplit("/", 1)[1]]


def route_put_project(req: Request):
    manifest = req.json()
    code = validate_manifest(manifest)
    if code:
        raise Refuse(code)
    if manifest["project"] != req.params["name"]:
        raise Refuse("bad_manifest:project_mismatch")
    if has_secret(manifest):
        raise Refuse("secret_in_message")
    with req.hub.store.tx() as c:
        req.hub.store.append(c, hub_message(req.params["name"], "project", manifest))
    return 200, {"project": req.params["name"]}


def route_get_project(req: Request):
    with req.hub.store.read() as c:
        row = c.execute(
            "SELECT envelope FROM messages WHERE recipient=? AND kind='project' ORDER BY seq DESC LIMIT 1",
            (req.params["name"],),
        ).fetchone()
    if not row:
        raise Refuse("not_found")
    return 200, json.loads(row["envelope"])["body"]


def route_put_blob(req: Request):
    sha = req.params["sha256"]
    size = req.content_length()
    if size > MAX_BLOB_BYTES:
        raise Refuse("too_large")
    req.body_read = True
    data = req.rfile.read(size)
    if hashlib.sha256(data).hexdigest() != sha:
        raise Refuse("blob_hash_mismatch")
    target = req.hub.blobs / sha
    if not target.exists():
        temp = req.hub.blobs / f"{sha}.{new_id()}.tmp"
        temp.write_bytes(data)
        os.replace(temp, target)
    return 200, {"blob": sha}


def route_get_blob(req: Request):
    sha = req.params["sha256"]
    if req.role == "member":
        with req.hub.store.read() as c:
            if not c.execute(
                "SELECT 1 FROM task_blobs WHERE sha256=? AND member=?", (sha, req.identity)
            ).fetchone():
                raise Refuse("blob_not_yours")
    try:
        return 200, (req.hub.blobs / sha).read_bytes()
    except OSError:
        raise Refuse("not_found") from None


def authenticate(req: Request) -> None:
    header = req.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise Refuse("unauthorized")
    digest = sha256_text(header[len("Bearer "):])
    if hmac.compare_digest(digest, req.hub.orchestrator_sha256):
        req.identity, req.role = "orchestrator", "orchestrator"
        return
    with req.hub.store.read() as c:
        for r in c.execute("SELECT name, key_sha256 FROM members").fetchall():
            if hmac.compare_digest(digest, r["key_sha256"]):
                state = member_state(c, r["name"])
                if state == "pending":
                    raise Refuse("not_approved")
                if state != "approved":
                    raise Refuse("revoked")
                req.identity, req.role = r["name"], "member"
                return
    raise Refuse("unauthorized")


ROUTES = {
    "GET /bootstrap/fleet.py": ((), route_bootstrap),
    "GET /bootstrap/bootstrap.md": ((), route_bootstrap),
    "POST /v1/pair": ((), route_pair),
    "POST /v1/hello": (("member",), route_hello),
    "POST /v1/heartbeat": (("member",), route_heartbeat),
    "GET /v1/tasks/next": (("member",), route_next),
    "POST /v1/tasks/<id>/status": (("member",), route_post_status),
    "POST /v1/tasks": (("orchestrator", "member"), route_post_task),
    "GET /v1/tasks/<id>": (("orchestrator",), route_get_task),
    "GET /v1/members": (("orchestrator",), route_members),
    "PUT /v1/projects/<name>": (("orchestrator",), route_put_project),
    "GET /v1/projects/<name>": (("orchestrator", "member"), route_get_project),
    "PUT /v1/blobs/<sha256>": (("orchestrator", "member"), route_put_blob),
    "GET /v1/blobs/<sha256>": (("orchestrator", "member"), route_get_blob),
}
ROUTE_PARAM_RES = {"id": "[0-9a-f]{32}", "sha256": "[0-9a-f]{64}", "name": "[a-z0-9-]{1,32}"}


def route_pattern(template: str) -> re.Pattern:
    def part(m: re.Match) -> str:
        return f"(?P<{m.group(1)}>{ROUTE_PARAM_RES[m.group(1)]})"

    return re.compile(re.sub(r"<(\w+)>", part, re.escape(template)))


ROUTE_TABLE = [(t, route_pattern(t), roles, fn) for t, (roles, fn) in ROUTES.items()]


def dispatch(req: Request):
    target = f"{req.method} {req.path}"
    for template, pattern, roles, fn in ROUTE_TABLE:
        m = pattern.fullmatch(target)
        if not m:
            continue
        req.params = m.groupdict()
        if template not in OPEN_ROUTES:
            authenticate(req)
            if req.role not in roles:
                raise Refuse("role_not_allowed")
        return fn(req)
    raise Refuse("not_found")


class HubServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
    # On Windows this option would let a second hub share the port without an error.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address, state: HubState, ssl_context: ssl.SSLContext):
        self.state = state
        self.ssl_context = ssl_context
        super().__init__(address, HubHandler)

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], OSError):
            traceback.print_exc()


class HubHandler(BaseHTTPRequestHandler):
    server_version = "fleet"
    sys_version = ""

    def setup(self):
        # The handshake runs on this connection's own thread, so a client that never does it
        # holds one thread until the timeout and nothing else.
        self.request.settimeout(HANDLER_TIMEOUT_S)
        self.request = self.server.ssl_context.wrap_socket(self.request, server_side=True)
        super().setup()

    def finish(self):
        try:
            super().finish()
        finally:
            self.request.close()

    def log_message(self, format, *args):
        pass

    def _serve(self):
        path = self.path.split("?", 1)[0]
        req = Request(self.server.state, self.command, path, {}, self.headers, self.rfile)
        try:
            status, payload = dispatch(req)
        except Refuse as e:
            status, payload = refusal_status(e.code), {"error": e.code}
        req.drain()
        if isinstance(payload, (bytes, bytearray)):
            data, ctype = bytes(payload), "application/octet-stream"
        else:
            data, ctype = json.dumps(payload).encode("utf-8"), "application/json"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = _serve


def find_openssl() -> str:
    found = shutil.which("openssl")
    if found:
        return found
    git = shutil.which("git")
    if git:
        root = Path(git).resolve().parent.parent
        for rel in ("usr/bin/openssl.exe", "mingw64/bin/openssl.exe"):
            if (root / rel).exists():
                return str(root / rel)
    raise Refuse("openssl_missing")


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def certificate_pin(cert_path: Path) -> str:
    der = ssl.PEM_cert_to_DER_cert(cert_path.read_text(encoding="ascii"))
    return hashlib.sha256(der).hexdigest()


def ensure_hub_files(hub_dir: Path, host: str, port: int) -> str:
    hub_dir.mkdir(parents=True, exist_ok=True)
    (hub_dir / "blobs").mkdir(exist_ok=True)
    cert, key = hub_dir / "hub.crt", hub_dir / "hub.key"
    if not cert.exists():
        subprocess.run(
            [find_openssl(), "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
             "-subj", "/CN=fleet-hub", "-keyout", str(key), "-out", str(cert)],
            check=True, capture_output=True,
        )
    if not (hub_dir / "orchestrator.key").exists():
        write_private(hub_dir / "orchestrator.key", secrets.token_urlsafe(32))
    pin = certificate_pin(cert)
    (hub_dir / "hub.json").write_text(
        json.dumps({"url": f"https://{host}:{port}", "pin": pin}), encoding="utf-8"
    )
    return pin


def bootstrap_files() -> dict[str, bytes]:
    here = Path(__file__).resolve().parent
    try:
        return {name: (here / name).read_bytes() for name in ("fleet.py", "bootstrap.md")}
    except OSError as e:
        raise Refuse(f"no_config:{Path(e.filename).name}") from None


def cmd_hub(args) -> int:
    hub_dir = fleet_home() / "hub"
    pin = ensure_hub_files(hub_dir, args.host, args.port)
    files = bootstrap_files()
    state = HubState(
        store=Store(hub_dir / "hub.db"),
        orchestrator_sha256=sha256_text((hub_dir / "orchestrator.key").read_text(encoding="utf-8")),
        offline_after=args.offline_after,
        bootstrap=files,
        blobs=hub_dir / "blobs",
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(hub_dir / "hub.crt", hub_dir / "hub.key")
    server = HubServer((args.host, args.port), state, ctx)
    # The one input a setup agent needs. Saved too, for a hub started in a terminal the agent cannot read.
    pairing = (
        f"fleet-pairing url=https://{args.host}:{args.port} pin={pin}"
        f" fleet_py={hashlib.sha256(files['fleet.py']).hexdigest()}"
        f" bootstrap_md={hashlib.sha256(files['bootstrap.md']).hexdigest()}"
    )
    (hub_dir / "pairing.txt").write_text(pairing + "\n", encoding="utf-8")
    print(pairing, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


# Client


@dataclass
class Client:
    url: str
    pin: str
    key: str | None
    session: str | None = None
    name: str = "orchestrator"
    capabilities: dict | None = None
    poll: float = POLL_S


def load_config(path: Path, fields: tuple[str, ...]) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refuse(f"no_config:{path.name}") from None
    if not isinstance(data, dict) or set(data) != set(fields):
        raise Refuse(f"no_config:{path.name}")
    return data


def load_hub_client(home: Path | None = None) -> Client:
    hub_dir = Path(home or fleet_home()) / "hub"
    cfg = load_config(hub_dir / "hub.json", ("url", "pin"))
    try:
        key = (hub_dir / "orchestrator.key").read_text(encoding="utf-8")
    except OSError:
        raise Refuse("no_config:orchestrator.key") from None
    return Client(cfg["url"], cfg["pin"], key)


def load_member_client(home: Path | None = None) -> Client:
    cfg = load_config(Path(home or fleet_home()) / "member.json", ("hub", "pin", "name", "key"))
    return Client(cfg["hub"], cfg["pin"], cfg["key"], name=cfg["name"])


def hub_request(client: Client, method: str, path: str, body=None, raw: bytes | None = None):
    """Check the pin, then send one request. Returns (status, parsed JSON or bytes)."""
    parts = urlsplit(client.url)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        sock = socket.create_connection((parts.hostname, parts.port), timeout=REQUEST_TIMEOUT_S)
        tls = ctx.wrap_socket(sock)
    except (OSError, ssl.SSLError):
        raise Refuse("hub_unreachable") from None
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=REQUEST_TIMEOUT_S)
    conn.sock = tls
    try:
        if hashlib.sha256(tls.getpeercert(True)).hexdigest() != client.pin:
            raise Refuse("pin_mismatch")
        headers = {}
        if client.key:
            headers["Authorization"] = f"Bearer {client.key}"
        if client.session:
            headers["X-Fleet-Session"] = client.session
        data = raw
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if data is not None:
            headers["Content-Length"] = str(len(data))
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
    except (OSError, http.client.HTTPException, ssl.SSLError):
        raise Refuse("hub_unreachable") from None
    finally:
        conn.close()
    if resp.getheader("Content-Type") == "application/json":
        return resp.status, json.loads(payload)
    return resp.status, payload


def api(client: Client, method: str, path: str, body=None, raw: bytes | None = None):
    """hub_request for the CLI: an HTTP refusal becomes a Refuse."""
    status, reply = hub_request(client, method, path, body, raw)
    if status >= 400:
        raise Refuse(reply["error"] if isinstance(reply, dict) else "not_found")
    return reply


def print_json(obj) -> None:
    print(json.dumps(obj, indent=None, sort_keys=True), flush=True)


def cmd_pair(args) -> int:
    key = secrets.token_urlsafe(32)
    digest = sha256_text(key)
    client = Client(args.hub, args.pin, None)
    api(client, "POST", "/v1/pair", {"name": args.name, "key_sha256": digest})
    home = fleet_home()
    home.mkdir(parents=True, exist_ok=True)
    write_private(
        home / "member.json",
        json.dumps({"hub": args.hub, "pin": args.pin, "name": args.name, "key": key}),
    )
    print_json({"name": args.name, "code": digest[:12]})
    return 0


def read_manifest(repo: Path) -> dict:
    try:
        manifest = json.loads((repo / ".agent" / "fleet.json").read_text(encoding="utf-8"))
    except OSError:
        raise Refuse("no_manifest") from None
    except ValueError:
        raise Refuse("bad_manifest:bad_json") from None
    code = validate_manifest(manifest)
    if code:
        raise Refuse(code)
    return manifest


def cmd_publish(args) -> int:
    manifest = read_manifest(Path(args.repo))
    print_json(api(load_hub_client(), "PUT", f"/v1/projects/{manifest['project']}", manifest))
    return 0


def git(cwd: Path, *args: str, env: dict | None = None, refuse: str | None = None) -> str:
    """Run git and return its stdout. Found with which, so a shim on PATH is honoured."""
    tool = shutil.which("git")
    if not tool:
        raise Refuse("tool_missing:git")
    r = subprocess.run([tool, *args], cwd=cwd, env=env, capture_output=True, stdin=subprocess.DEVNULL)
    if r.returncode:
        detail = r.stderr.decode("utf-8", "replace").strip()
        if detail:
            print(f"git {args[0]}: {detail}", file=sys.stderr, flush=True)
        raise Refuse(refuse or f"git_failed:{args[0]}")
    return r.stdout.decode("utf-8", "replace").strip()


def is_secret_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    if any(fnmatch.fnmatchcase(name, p) for p in SECRET_PATH_ALLOW):
        return False
    return any(fnmatch.fnmatchcase(name, p) for p in SECRET_PATH_PATTERNS)


def bundle_paths(repo: Path, commit: str) -> list[str]:
    """Every path the bundle carries: a path in any tree of the history is new in some commit's diff."""
    return git(
        repo, "log", "--root", "--diff-merges=first-parent", "--no-renames", "--name-only", "--format=", "-z", commit,
    ).split("\0")


def make_snapshot(repo: Path, task: str) -> tuple[dict, bytes]:
    """Bundle the working tree through a copy of the index. Returns the task's refs and the bundle.

    The repo's index, HEAD, files and branches stay as they are. The only trace is dangling objects.
    """
    head = git(repo, "rev-parse", "--verify", "-q", "HEAD", refuse="no_head")
    index = repo / git(repo, "rev-parse", "--git-path", "index")
    ref = f"refs/fleet/snap/{task}"
    with tempfile.TemporaryDirectory(prefix="fleet-snap-") as tmp:
        temp_index, bundle = Path(tmp) / "index", Path(tmp) / "snapshot.bundle"
        if index.exists():
            shutil.copyfile(index, temp_index)
        env = {**os.environ, **SNAPSHOT_IDENTITY, "GIT_INDEX_FILE": str(temp_index)}
        git(repo, "add", "-A", env=env)
        # The slot reads the manifest from the snapshot, so it travels even if the repo ignores it.
        if (repo / ".agent" / "fleet.json").exists():
            git(repo, "add", "-f", "--", ".agent/fleet.json", env=env)
        tree = git(repo, "write-tree", env=env)
        commit = git(repo, "commit-tree", tree, "-p", head, "--no-gpg-sign", "-m", f"fleet snapshot {task}", env=env)
        for path in bundle_paths(repo, commit):
            if is_secret_path(path):
                raise Refuse(f"snapshot_secret_risk:{path}")
        git(repo, "update-ref", ref, commit)
        try:
            git(repo, "bundle", "create", "-q", str(bundle), ref)
        finally:
            git(repo, "update-ref", "-d", ref)
        if bundle.stat().st_size > MAX_BLOB_BYTES:
            raise Refuse("too_large")
        data = bundle.read_bytes()
    return {"commit": commit, "tree": tree, "bundle": hashlib.sha256(data).hexdigest()}, data


def cmd_run(args) -> int:
    client = load_hub_client()
    repo = Path(args.repo)
    manifest = read_manifest(repo)
    task = new_id()
    refs, data = make_snapshot(repo, task)
    api(client, "PUT", f"/v1/blobs/{refs['bundle']}", raw=data)
    body = {"project": manifest["project"], "command": args.command, "timeout_s": args.timeout}
    env = new_message("orchestrator", args.member, "run", body, task)
    env["refs"] = refs
    print_json({**api(client, "POST", "/v1/tasks", env), **refs})
    return 0


def load_local_client() -> Client:
    """A member's own key, or the orchestrator's on the hub machine."""
    if (fleet_home() / "member.json").exists():
        return load_member_client()
    return load_hub_client()


def cmd_check(args) -> int:
    report = {"capabilities": capability_report()}
    if not args.project:
        print_json(report)
        return 0
    manifest = api(load_local_client(), "GET", f"/v1/projects/{args.project}")
    report["project"] = args.project
    report["missing"] = [t for t in manifest["requires"] if not report["capabilities"].get(t)]
    print_json(report)
    return EXIT_CODES["tools_missing"] if report["missing"] else 0


def stdin_is_terminal() -> bool:
    if not sys.stdin.isatty():
        return False
    if os.name != "nt":
        return True
    # On Windows isatty() is also true for NUL, so ask the console itself.
    import ctypes.wintypes
    import msvcrt

    mode = ctypes.wintypes.DWORD()
    handle = ctypes.wintypes.HANDLE(msvcrt.get_osfhandle(sys.stdin.fileno()))
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


def cmd_approve(args) -> int:
    if not stdin_is_terminal():
        raise Refuse("approve_requires_tty")
    approve_member(Store(fleet_home() / "hub" / "hub.db"), args.name, args.code)
    print_json({"name": args.name, "state": "approved"})
    return 0


def cmd_revoke(args) -> int:
    if not stdin_is_terminal():
        raise Refuse("approve_requires_tty")
    revoke_member(Store(fleet_home() / "hub" / "hub.db"), args.name)
    print_json({"name": args.name, "state": "revoked"})
    return 0


def cmd_status(args) -> int:
    path = f"/v1/tasks/{args.task}" if args.task else "/v1/members"
    print_json(api(load_hub_client(), "GET", path))
    return 0


def cmd_send(args) -> int:
    env = new_message("orchestrator", args.member, args.kind, {})
    print_json(api(load_hub_client(), "POST", "/v1/tasks", env))
    return 0


def wait_result(info: dict) -> dict:
    status = info["status"]
    result = {"task": info["task"], "state": info["state"]}
    for field in ("reason", "exit_code", "tree", "log", "duration_s"):
        result[field] = status.get(field)
    if "capabilities" in status:
        result["capabilities"] = status["capabilities"]
    return result


def cmd_wait(args) -> int:
    client = load_hub_client()
    end = time.monotonic() + args.timeout
    while True:
        info = api(client, "GET", f"/v1/tasks/{args.task}")
        if info["state"] in TERMINAL_STATES:
            if args.log and info["status"].get("log"):
                Path(args.log).write_bytes(api(client, "GET", f"/v1/blobs/{info['status']['log']}"))
            print_json(wait_result(info))
            return {"completed": EXIT_CODES["ok"], "rejected": EXIT_CODES["rejected"]}.get(
                info["state"], EXIT_CODES["failed"]
            )
        if not info["member_online"]:
            print_json(wait_result(info))
            return EXIT_CODES["offline"]
        if time.monotonic() >= end:
            print_json(wait_result(info))
            return EXIT_CODES["timeout"]
        time.sleep(WAIT_POLL_S)


# Member


def tool_version(tool: str) -> str | None:
    found = shutil.which(tool) or (sys.executable if tool == "python" else None)
    if not found:
        return None
    try:
        r = subprocess.run(
            [found, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=CAPABILITY_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = (r.stdout or r.stderr or "").strip().splitlines()
    return lines[0][:200] if r.returncode == 0 and lines else None


def capability_report() -> dict:
    with concurrent.futures.ThreadPoolExecutor(len(CAPABILITY_TOOLS)) as pool:
        return dict(zip(CAPABILITY_TOOLS, pool.map(tool_version, CAPABILITY_TOOLS)))


def member_call(client: Client, method: str, path: str, body=None, raw: bytes | None = None):
    """api() that waits out network errors, so a result survives a Wi-Fi drop or a hub restart."""
    while True:
        try:
            return api(client, method, path, body, raw)
        except Refuse as e:
            if e.code != "hub_unreachable":
                raise
        time.sleep(RETRY_S)


def post_status(client: Client, task: dict, body: dict) -> None:
    # The message is built once: a retry carries the same id and gets already_recorded.
    env = new_message(client.name, task["from"], "status", body, task["task_id"])
    member_call(client, "POST", f"/v1/tasks/{task['task_id']}/status", env)


def execute_ping(client: Client, task: dict) -> dict:
    return {"state": "completed", "capabilities": client.capabilities}


def prepare_slot(client: Client, task: dict) -> Path:
    """Put a task's snapshot in its project's slot, or refuse with the rejection reason.

    The slot comes from git init, never a clone, so it has no remote. Ignored files stay.
    """
    refs, task_id = task["refs"], task["task_id"]
    slot = fleet_home() / "slots" / task["body"]["project"]
    slot.mkdir(parents=True, exist_ok=True)
    git(slot, "init", "-q")
    try:
        data = member_call(client, "GET", f"/v1/blobs/{refs['bundle']}")
    except Refuse:
        raise Refuse("bundle_bad") from None
    if hashlib.sha256(data).hexdigest() != refs["bundle"]:
        raise Refuse("bundle_bad")
    bundle = slot / ".git" / "fleet-task.bundle"
    bundle.write_bytes(data)
    git(slot, "bundle", "verify", "-q", str(bundle), refuse="bundle_bad")
    ref = f"refs/fleet/task/{task_id}"
    git(slot, "fetch", "-q", str(bundle), f"refs/fleet/snap/{task_id}:{ref}", refuse="bundle_bad")
    bundle.unlink()
    git(slot, "checkout", "-q", "--force", "--detach", ref, refuse="tree_mismatch")
    git(slot, "clean", "-fdq", refuse="tree_mismatch")
    if git(slot, "rev-parse", "HEAD^{tree}") != refs["tree"]:
        raise Refuse("tree_mismatch")
    return slot


def resolve_command(slot: Path, task: dict) -> list[list[str]]:
    """The named command's steps with each tool resolved, or refuse with the rejection reason."""
    manifest = read_manifest(slot)
    if manifest["project"] != task["body"]["project"]:
        raise Refuse("project_mismatch")
    steps = manifest["commands"].get(task["body"]["command"])
    if steps is None:
        raise Refuse("unknown_command")
    resolved = []
    for argv in steps:
        found = shutil.which(argv[0])
        if not found:
            raise Refuse(f"tool_missing:{command_tool(argv[0])}")
        resolved.append([found, *argv[1:]])
    return resolved


def kill_tree(proc: subprocess.Popen, log) -> None:
    """End a timed-out step and its children. A failed tree kill goes in the log, since children may survive."""
    r = subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    proc.kill()
    if r.returncode:
        detail = (r.stderr or r.stdout).decode("utf-8", "replace").strip()
        log.write(f"\nfleet: taskkill exit {r.returncode}, child processes may survive: {detail}\n".encode())


def run_steps(steps: list[list[str]], cwd: Path, log_path: Path, timeout_s: int) -> tuple[int, str | None]:
    """Run each step in order, with no shell and the member's environment. Returns exit code and reason."""
    deadline = time.monotonic() + timeout_s
    with log_path.open("wb") as log:
        for argv in steps:
            proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = proc.wait(max(deadline - time.monotonic(), 0))
            except subprocess.TimeoutExpired:
                kill_tree(proc, log)
                return proc.wait(), "timeout"
            if code:
                return code, "nonzero_exit"
    return 0, None


def log_tail(path: Path) -> bytes:
    with path.open("rb") as f:
        f.seek(max(path.stat().st_size - MAX_BLOB_BYTES, 0))
        return f.read()


def execute_run(client: Client, task: dict) -> dict:
    started = time.monotonic()
    try:
        slot = prepare_slot(client, task)
        steps = resolve_command(slot, task)
    except Refuse as e:
        return {"state": "rejected", "reason": e.code}
    logs = fleet_home() / "logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / f"{task['task_id']}.log"
    exit_code, reason = run_steps(steps, slot, log_path, task["body"]["timeout_s"])
    data = log_tail(log_path)
    sha = hashlib.sha256(data).hexdigest()
    member_call(client, "PUT", f"/v1/blobs/{sha}", raw=data)
    # A process the command left running can still hold the file open.
    with contextlib.suppress(OSError):
        log_path.unlink()
    return {
        "state": "failed" if reason else "completed",
        "reason": reason,
        "exit_code": exit_code,
        "log": sha,
        "tree": task["refs"]["tree"],
        "duration_s": round(time.monotonic() - started, 3),
    }


EXECUTORS = {"ping": execute_ping, "run": execute_run}


@contextlib.contextmanager
def heartbeats(client: Client):
    """Keep the member online while a task runs, from download to log upload."""
    stop = threading.Event()

    def beat():
        while not stop.wait(client.poll):
            with contextlib.suppress(Refuse):
                hub_request(client, "POST", "/v1/heartbeat")

    threading.Thread(target=beat, daemon=True).start()
    try:
        yield
    finally:
        stop.set()


def execute_task(client: Client, task: dict) -> None:
    with heartbeats(client):
        body = EXECUTORS[task["kind"]](client, task)
    post_status(client, task, body)


def member_loop(client: Client, poll: float) -> int:
    client.poll = poll
    client.capabilities = capability_report()
    reply = member_call(client, "POST", "/v1/hello", {"capabilities": client.capabilities})
    client.session = reply["session"]
    print(f"fleet member {client.name} online", flush=True)
    while True:
        task = member_call(client, "GET", "/v1/tasks/next")["task"]
        if task:
            execute_task(client, task)
        else:
            time.sleep(poll)


def cmd_member(args) -> int:
    return member_loop(load_member_client(), args.poll)


def parse_name(value: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("bad_name")
    return value


def parse_pin(value: str) -> str:
    if not HEX64_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("the pin is 64 hex digits")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fleet.py", description="LAN fleet: hub, member and CLI")
    sub = p.add_subparsers(dest="verb", required=True)
    hub = sub.add_parser("hub", help="Run the hub (SUPER)")
    hub.add_argument("--host", default="127.0.0.1")
    hub.add_argument("--port", type=int, default=DEFAULT_PORT)
    hub.add_argument("--offline-after", type=float, default=OFFLINE_AFTER_S)
    hub.set_defaults(fn=cmd_hub)
    pair = sub.add_parser("pair", help="Register this machine as a pending member")
    pair.add_argument("--hub", required=True)
    pair.add_argument("--pin", required=True, type=parse_pin)
    pair.add_argument("--name", required=True, type=parse_name)
    pair.set_defaults(fn=cmd_pair)
    approve = sub.add_parser("approve", help="Approve a pending member (real terminal only)")
    approve.add_argument("name", type=parse_name)
    approve.add_argument("code")
    approve.set_defaults(fn=cmd_approve)
    revoke = sub.add_parser("revoke", help="Revoke a member (real terminal only)")
    revoke.add_argument("name", type=parse_name)
    revoke.set_defaults(fn=cmd_revoke)
    status = sub.add_parser("status", help="List members, or show one task")
    status.add_argument("task", nargs="?")
    status.set_defaults(fn=cmd_status)
    send = sub.add_parser("send", help="Send a task to a member")
    send.add_argument("member", type=parse_name)
    send.add_argument("kind")
    send.set_defaults(fn=cmd_send)
    wait = sub.add_parser("wait", help="Wait for a task; the last line is its JSON result")
    wait.add_argument("task")
    wait.add_argument("--timeout", type=float, default=DEFAULT_RUN_TIMEOUT_S)
    wait.add_argument("--log", help="Write the task's log to this file")
    wait.set_defaults(fn=cmd_wait)
    run = sub.add_parser("run", help="Snapshot a repo's working tree and run a named command on a member")
    run.add_argument("member", type=parse_name)
    run.add_argument("--repo", required=True)
    run.add_argument("command", type=parse_name)
    run.add_argument("--timeout", type=int, default=DEFAULT_RUN_TIMEOUT_S)
    run.set_defaults(fn=cmd_run)
    publish = sub.add_parser("publish", help="Store a repo's .agent/fleet.json in the hub")
    publish.add_argument("--repo", required=True)
    publish.set_defaults(fn=cmd_publish)
    check = sub.add_parser("check", help="Report this machine's tools, and what a project still needs")
    check.add_argument("--project", type=parse_name)
    check.set_defaults(fn=cmd_check)
    member = sub.add_parser("member", help="Run this machine's member loop")
    member.add_argument("--poll", type=float, default=POLL_S)
    member.set_defaults(fn=cmd_member)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except Refuse as e:
        print(e.code, file=sys.stderr, flush=True)
        return EXIT_CODES["refused"]


if __name__ == "__main__":
    raise SystemExit(main())
