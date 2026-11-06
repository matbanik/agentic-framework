"""AC-1 to AC-15 of the fleet MVP plan: store, authentication, pairing and the walking skeleton."""
from __future__ import annotations

import ast
import itertools
import json
import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import fleet_harness  # noqa: E402
from fleet_harness import FLEET_PY, Hub, fleet, new_envelope, run_cli, wait_until  # noqa: E402

# Built by concatenation so the repo holds no value that looks like a secret.
FAKE_SECRETS = [
    "sk-" + "ant-" + "abcdef",
    "gh" + "p_" + "abcdef",
    "github" + "_pat_" + "abcdef",
    "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "-----BEGIN " + "RSA PRIVATE" + " KEY",
]


@pytest.fixture
def hub(tmp_path):
    h = Hub(tmp_path)
    h.start()
    yield h
    h.close()


def valid_envelope(**over) -> dict:
    return {**new_envelope("orchestrator", "local"), **over}


# AC-1: envelope validation


def test_ac01_accepts_a_complete_envelope():
    assert fleet.validate_envelope(valid_envelope()) is None


def test_ac01_refuses_an_extra_field():
    assert fleet.validate_envelope({**valid_envelope(), "x": 1}) == "unknown_field:x"


def test_ac01_refuses_a_wrong_version():
    assert fleet.validate_envelope(valid_envelope(v=2)) == "bad_version"


@pytest.mark.parametrize("name", fleet.ENVELOPE_FIELDS)
def test_ac01_refuses_each_missing_field(name):
    env = valid_envelope()
    del env[name]
    assert fleet.validate_envelope(env) == f"missing_field:{name}"


@pytest.mark.parametrize(
    "over,code",
    [
        ({"id": "short"}, "bad_field:id"),
        ({"task_id": "Z" * 32}, "bad_field:task_id"),
        ({"to": "../x"}, "bad_field:to"),
        ({"body": []}, "bad_field:body"),
        ({"refs": "x"}, "bad_field:refs"),
        ({"requires_human": "no"}, "bad_field:requires_human"),
        ({"start_quote": 1}, "bad_field:start_quote"),
        ({"kind": "commit"}, "unknown_kind"),
    ],
)
def test_ac01_refuses_wrong_types(over, code):
    assert fleet.validate_envelope(valid_envelope(**over)) == code


def test_ac01_refuses_a_non_object():
    assert fleet.validate_envelope([]) == "bad_json"


# AC-2: state transitions


def test_ac02_transitions_are_total_over_states():
    for a, b in itertools.product(fleet.TASK_STATES, fleet.TASK_STATES):
        assert fleet.next_state_allowed(a, b) == ((a, b) in fleet.TRANSITIONS), (a, b)


def test_ac02_terminal_states_have_no_exit():
    for a, b in itertools.product(fleet.TERMINAL_STATES, fleet.TASK_STATES):
        assert not fleet.next_state_allowed(a, b)


def test_ac02_unknown_state_fails_closed():
    assert not fleet.next_state_allowed("bogus", "working")
    assert not fleet.next_state_allowed("working", "bogus")
    assert not fleet.next_state_allowed("completed", "working")


# AC-3: append-only store


def _append(store, **over):
    env = valid_envelope(**over)
    with store.tx() as c:
        store.append(c, env)
    return env


def test_ac03_update_and_delete_abort_with_append_only(tmp_path):
    store = fleet.Store(tmp_path / "hub.db")
    _append(store)
    before = store.count_messages()
    for sql in ("UPDATE messages SET sender='x'", "DELETE FROM messages"):
        conn = sqlite3.connect(tmp_path / "hub.db")
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            conn.execute(sql)
        conn.close()
    assert store.count_messages() == before


def test_ac03_append_adds_exactly_one_row_and_changes_none(tmp_path):
    store = fleet.Store(tmp_path / "hub.db")
    first = _append(store)
    snapshot = store.dump_messages()
    second = _append(store)
    after = store.dump_messages()
    assert after[: len(snapshot)] == snapshot
    assert len(after) == len(snapshot) + 1
    assert first["id"] != second["id"]


def test_ac03_tx_rolls_back_on_error(tmp_path):
    store = fleet.Store(tmp_path / "hub.db")
    env = valid_envelope()
    with pytest.raises(RuntimeError):
        with store.tx() as c:
            store.append(c, env)
            raise RuntimeError("stop")
    assert store.count_messages() == 0


# AC-4: source rules


FORBIDDEN_TEXT = ("CLAUDE_CODE_" + "ENTRYPOINT", "CLAUDE" + "CODE", "cs" + "wap")


def source_problems(text: str) -> list[str]:
    tree = ast.parse(text, feature_version=(3, 11))
    problems = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        problems += [n for n in names if n.split(".")[0] not in sys.stdlib_module_names]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if len(node.value) >= 3 and node.value[1:3] in (":/", ":\\") and node.value[0].isalpha():
                problems.append(f"drive path: {node.value}")
    problems += [t for t in FORBIDDEN_TEXT if t in text]
    if "Path.home()" not in text:
        problems.append("home is not derived from Path.home()")
    return problems


def test_ac04_source_rules_hold():
    assert source_problems(FLEET_PY.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("line", ["import requests", 'X = "P:/x"', "Y = '" + FORBIDDEN_TEXT[2] + "'"])
def test_ac04_checker_can_fail(line):
    assert source_problems(FLEET_PY.read_text(encoding="utf-8") + "\n" + line + "\n")


# AC-5: pin check comes before any write


class ByteCountingServer:
    """A TLS server using the hub's certificate that counts application bytes after the handshake."""

    def __init__(self, hub_dir: Path):
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(hub_dir / "hub.crt", hub_dir / "hub.key")
        # With no session tickets a client has nothing unread when it closes. An unread ticket
        # would make Windows reset the connection and drop bytes this server is here to count.
        self.ctx.num_tickets = 0
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.received = 0
        self.handshakes = 0
        self.stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self.stop:
            try:
                raw, _ = self.sock.accept()
            except OSError:
                continue
            threading.Thread(target=self._read, args=(raw,), daemon=True).start()

    def _read(self, raw):
        raw.settimeout(5)
        try:
            with self.ctx.wrap_socket(raw, server_side=True) as tls:
                self.handshakes += 1
                while True:
                    data = tls.recv(4096)
                    if not data:
                        return
                    self.received += len(data)
        except OSError:
            return

    def close(self):
        self.stop = True
        self.thread.join(5)
        self.sock.close()


@pytest.fixture
def byte_server(hub):
    server = ByteCountingServer(hub.hub_dir)
    yield server
    server.close()


def test_ac05_wrong_pin_stops_status_before_any_byte(hub, byte_server, tmp_path):
    home = tmp_path / "other-home"
    (home / "hub").mkdir(parents=True)
    (home / "hub" / "hub.json").write_text(
        json.dumps({"url": f"https://127.0.0.1:{byte_server.port}", "pin": "0" * 64}), encoding="utf-8"
    )
    (home / "hub" / "orchestrator.key").write_text("not-the-key", encoding="utf-8")
    r = run_cli(home, "status")
    assert r.returncode == 2
    assert "pin_mismatch" in r.stdout + r.stderr
    wait_until(lambda: byte_server.handshakes >= 1)
    time.sleep(0.3)
    assert byte_server.received == 0


def test_ac05_wrong_pin_stops_pair_before_any_byte(hub, byte_server, tmp_path):
    home = tmp_path / "pair-home"
    home.mkdir()
    r = run_cli(
        home, "pair", "--hub", f"https://127.0.0.1:{byte_server.port}", "--pin", "0" * 64, "--name", "x"
    )
    assert r.returncode == 2
    assert "pin_mismatch" in r.stdout + r.stderr
    wait_until(lambda: byte_server.handshakes >= 1)
    time.sleep(0.3)
    assert byte_server.received == 0
    assert not (home / "member.json").exists()


def test_ac05_oracle_a_client_that_writes_first_is_seen(hub, byte_server):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection(("127.0.0.1", byte_server.port), 5) as raw:
        with ctx.wrap_socket(raw) as tls:
            tls.sendall(b"GET / HTTP/1.0\r\nAuthorization: Bearer fake\r\n\r\n")
            tls.getpeercert(True)
    wait_until(lambda: byte_server.received > 0)


# AC-6: authentication


def test_ac06_no_key_and_wrong_key_are_unauthorized(hub):
    for key in (None, "wrong"):
        status, reply = hub.request("GET", "/v1/members", key=key)
        assert (status, reply["error"]) == (401, "unauthorized")


def test_ac06_pending_member_is_not_approved(hub):
    member = hub.pair("pend", approve=False)
    status, reply = hub.request("GET", "/v1/members", key=member.key())
    assert (status, reply["error"]) == (401, "not_approved")


def test_ac06_revoked_member_is_revoked(hub):
    member = hub.pair("rev")
    key = member.key()
    status, _ = hub.request("POST", "/v1/hello", {"capabilities": {}}, key=key)
    assert status == 200
    fleet.revoke_member(hub.store(), "rev")
    status, reply = hub.request("POST", "/v1/hello", {"capabilities": {}}, key=key)
    assert (status, reply["error"]) == (401, "revoked")


def test_ac06_raw_key_is_not_in_the_database(hub):
    member = hub.pair("keyed")
    raw = member.key().encode()
    for path in hub.hub_dir.glob("hub.db*"):
        assert raw not in path.read_bytes()


# AC-7: pairing and approval


def test_ac07_approve_needs_a_tty_and_adds_no_row(hub):
    member = hub.pair("tty", approve=False)
    before = hub.rows()
    r = hub.cli("approve", "tty", member.code)
    assert r.returncode == 2
    assert "approve_requires_tty" in r.stdout + r.stderr
    assert hub.rows() == before


def test_ac07_approve_refuses_piped_stdin(hub):
    member = hub.pair("piped", approve=False)
    before = hub.rows()
    r = subprocess.run(
        [sys.executable, str(FLEET_PY), "approve", "piped", member.code],
        env={**os.environ, "FLEET_HOME": str(hub.home)},
        input="y",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 2
    assert "approve_requires_tty" in r.stdout + r.stderr
    assert hub.rows() == before


def test_ac07_revoke_needs_a_tty_too(hub):
    hub.pair("stays")
    before = hub.rows()
    r = hub.cli("revoke", "stays")
    assert r.returncode == 2
    assert "approve_requires_tty" in r.stdout + r.stderr
    assert hub.rows() == before


def test_ac07_wrong_code_is_refused_and_adds_no_row(hub):
    hub.pair("code", approve=False)
    before = hub.rows()
    with pytest.raises(fleet.Refuse) as e:
        fleet.approve_member(hub.store(), "code", "0" * 12)
    assert e.value.code == "bad_code"
    assert hub.rows() == before


def test_ac07_right_code_approves(hub):
    member = hub.pair("good", approve=False)
    fleet.approve_member(hub.store(), "good", member.code)
    status, _ = hub.request("POST", "/v1/hello", {"capabilities": {}}, key=member.key())
    assert status == 200


def test_ac07_no_http_route_approves(hub):
    assert hub.request("POST", "/v1/approve", {"name": "x"})[0] == 404
    assert hub.request("POST", "/v1/approve", {"name": "x"}, key=hub.client().key)[0] == 404


def _pair_raw(hub, name, digest="a" * 64):
    return hub.request("POST", "/v1/pair", {"name": name, "key_sha256": digest})


def test_ac07_reused_name_is_taken_until_revoked(hub):
    hub.pair("dup", approve=False)
    status, reply = _pair_raw(hub, "dup")
    assert (status, reply["error"]) == (409, "name_taken")
    member = hub.pair("dup2")
    status, reply = _pair_raw(hub, "dup2")
    assert (status, reply["error"]) == (409, "name_taken")
    fleet.revoke_member(hub.store(), "dup2")
    assert _pair_raw(hub, "dup2", "b" * 64)[0] == 200
    assert member.key()


@pytest.mark.parametrize("name", ["orchestrator", "hub", "../x", "UPPER", "", "name\n"])
def test_ac07_bad_names_are_refused(hub, name):
    before = hub.rows()
    status, reply = _pair_raw(hub, name)
    assert (status, reply["error"]) == (400, "bad_name")
    assert hub.rows() == before


def test_ac07_pair_validates_its_fields(hub):
    assert hub.request("POST", "/v1/pair", {"name": "x", "key_sha256": "a" * 64, "y": 1})[1]["error"] == "unknown_field:y"
    assert hub.request("POST", "/v1/pair", {"name": "x", "key_sha256": "short"})[1]["error"] == "bad_field:key_sha256"


def test_ac07_pending_is_limited(hub):
    for i in range(fleet.MAX_PENDING):
        assert _pair_raw(hub, f"m{i}")[0] == 200
    status, reply = _pair_raw(hub, "over")
    assert (status, reply["error"]) == (429, "pending_full")


def test_ac07_pair_never_prints_the_key(hub, tmp_path):
    home = tmp_path / "quiet"
    home.mkdir()
    r = run_cli(home, "pair", "--hub", hub.url(), "--pin", hub.pin(), "--name", "quiet")
    assert r.returncode == 0, r.stdout + r.stderr
    key = fleet.load_member_client(home).key
    assert key not in r.stdout + r.stderr
    code = json.loads(r.stdout.strip().splitlines()[-1])["code"]
    assert len(code) == 12 and fleet.sha256_text(key).startswith(code)


# AC-8: who may send what


@pytest.mark.parametrize("kind", ["ping", "run", "agent"])
def test_ac08_members_cannot_send_tasks(hub, kind):
    member = hub.pair("sender")
    hub.pair("target")
    before = hub.rows()
    status, reply = hub.request("POST", "/v1/tasks", new_envelope("sender", "target", kind), key=member.key())
    assert (status, reply["error"]) == (403, "sender_not_allowed")
    assert hub.rows() == before


@pytest.mark.parametrize("kind", ["commit", "push", "merge", "tag", "release"])
def test_ac08_landing_kinds_do_not_exist(hub, kind):
    hub.pair("local")
    before = hub.rows()
    status, reply = hub.request("POST", "/v1/tasks", valid_envelope(kind=kind), key=hub.client().key)
    assert (status, reply["error"]) == (422, "unknown_kind")
    assert hub.rows() == before


def test_ac08_from_must_match_the_key(hub):
    hub.pair("local")
    before = hub.rows()
    env = new_envelope("local", "local")
    status, reply = hub.request("POST", "/v1/tasks", env, key=hub.client().key)
    assert (status, reply["error"]) == (403, "from_mismatch")
    assert hub.rows() == before


def test_ac08_task_needs_an_approved_member(hub):
    hub.pair("waiting", approve=False)
    before = hub.rows()
    for to in ("waiting", "nobody"):
        status, reply = hub.request(
            "POST", "/v1/tasks", new_envelope("orchestrator", to), key=hub.client().key
        )
        assert (status, reply["error"]) == (422, "unknown_member")
    assert hub.rows() == before


def test_ac08_executors_match_the_send_policy():
    assert set(fleet.EXECUTORS) == set().union(*fleet.SEND_POLICY.values())


# AC-12: no secret value in a message


@pytest.mark.parametrize("value", FAKE_SECRETS)
@pytest.mark.parametrize("field", ["body", "refs", "start_quote"])
def test_ac12_secret_values_are_refused(hub, field, value):
    hub.pair("local")
    before = hub.rows()
    over = {field: value} if field == "start_quote" else {field: {"x": value}}
    status, reply = hub.request("POST", "/v1/tasks", valid_envelope(**over), key=hub.client().key)
    assert (status, reply["error"]) == (422, "secret_in_message")
    assert hub.rows() == before
    for path in hub.hub_dir.glob("hub.db*"):
        assert value.encode() not in path.read_bytes()


@pytest.mark.parametrize("value", FAKE_SECRETS)
@pytest.mark.parametrize("field", ["created", "reply_to"])
def test_ac12_secret_values_in_other_fields_are_refused(hub, field, value):
    hub.pair("local")
    before = hub.rows()
    status, reply = hub.request("POST", "/v1/tasks", valid_envelope(**{field: value}), key=hub.client().key)
    assert (status, reply["error"]) == (422, "secret_in_message")
    assert hub.rows() == before
    for path in hub.hub_dir.glob("hub.db*"):
        assert value.encode() not in path.read_bytes()


@pytest.mark.parametrize("field", ["created", "reply_to", "body", "refs", "start_quote"])
def test_ac12_a_status_message_is_scanned_the_same_way(hub, field):
    value = FAKE_SECRETS[1]
    client = hub.pair("local").hello()
    task = send_ping(hub, "local")
    assert next_task(client)["task_id"] == task
    before = hub.rows()
    over = {"state": "completed", "x": value} if field == "body" else {"x": value} if field == "refs" else value
    status, reply = post(client, status_message("local", task, **{field: over}))
    assert (status, reply["error"]) == (422, "secret_in_message")
    assert hub.rows() == before
    for path in hub.hub_dir.glob("hub.db*"):
        assert value.encode() not in path.read_bytes()


@pytest.mark.parametrize("field", fleet.ENVELOPE_FIELDS)
def test_ac12_no_envelope_field_can_carry_a_secret(field):
    assert fleet.validate_envelope(valid_envelope(**{field: FAKE_SECRETS[1]})) is not None


def test_ac12_a_capability_version_is_scanned_too(hub):
    value = FAKE_SECRETS[1]
    member = hub.pair("local")
    status, reply = hub.request("POST", "/v1/hello", {"capabilities": {"python": value}}, key=member.key())
    assert (status, reply["error"]) == (422, "secret_in_message")
    for path in hub.hub_dir.glob("hub.db*"):
        assert value.encode() not in path.read_bytes()


# AC-15: resource limits


def test_ac15_raw_client_does_not_stop_requests(hub):
    idle = [socket.create_connection(("127.0.0.1", hub.port), 5) for _ in range(3)]
    try:
        status, _ = hub.request("GET", "/v1/members", key=hub.client().key)
        assert status == 200
    finally:
        for s in idle:
            s.close()


def test_ac15_oversized_json_is_refused(hub):
    hub.pair("local")
    before = hub.rows()
    env = valid_envelope(body={"x": "y" * (fleet.MAX_JSON_BYTES + 1)})
    status, reply = hub.request("POST", "/v1/tasks", env, key=hub.client().key)
    assert (status, reply["error"]) == (413, "too_large")
    assert hub.rows() == before


# Row 3 helpers


def member_row(hub, name) -> dict:
    status, reply = hub.request("GET", "/v1/members", key=hub.client().key)
    assert status == 200, reply
    return next((m for m in reply["members"] if m["name"] == name), {})


def wait_online(hub, name):
    wait_until(lambda: member_row(hub, name).get("online"), timeout=40)


def last_json(r) -> dict:
    return json.loads(r.stdout.strip().splitlines()[-1])


def send_ping(hub, to) -> str:
    r = hub.cli("send", to, "ping")
    assert r.returncode == 0, r.stdout + r.stderr
    return last_json(r)["task"]


def task_info(hub, task) -> dict:
    status, reply = hub.request("GET", f"/v1/tasks/{task}", key=hub.client().key)
    assert status == 200, reply
    return reply


def status_rows(hub, task, state) -> int:
    with hub.store().read() as c:
        rows = c.execute(
            "SELECT envelope FROM messages WHERE task_id=? AND kind='status'", (task,)
        ).fetchall()
    return sum(json.loads(r["envelope"])["body"]["state"] == state for r in rows)


def next_task(client):
    status, reply = fleet.hub_request(client, "GET", "/v1/tasks/next")
    assert status == 200, reply
    return reply["task"]


def status_message(sender, task, state="completed", **over) -> dict:
    body = over.pop("body", {"state": state})
    return new_envelope(sender, "orchestrator", "status", id=fleet.new_id(), task_id=task, body=body, **over)


def post(client, env):
    return fleet.hub_request(client, "POST", f"/v1/tasks/{env['task_id']}/status", env)


# AC-3, over a full task on the hub's real database


def test_ac03_full_task_leaves_earlier_rows_unchanged(hub):
    member = hub.pair("local")
    client = member.hello()
    task = send_ping(hub, "local")
    assert next_task(client)["task_id"] == task
    before = hub.store().dump_messages()
    assert post(client, status_message("local", task))[0] == 200
    after = hub.store().dump_messages()
    assert after[: len(before)] == before
    assert len(after) == len(before) + 1
    for sql in ("UPDATE messages SET sender='x'", "DELETE FROM messages"):
        conn = sqlite3.connect(hub.db)
        with pytest.raises(sqlite3.DatabaseError, match="append_only"):
            conn.execute(sql)
        conn.close()
    assert hub.store().dump_messages() == after


# AC-9: walking skeleton


def test_ac09_ping_round_trip_with_real_processes(hub):
    member = hub.pair("local")
    member.start()
    wait_online(hub, "local")
    task = send_ping(hub, "local")
    r = hub.cli("wait", task, "--timeout", "30")
    assert r.returncode == 0, r.stdout + r.stderr
    out = last_json(r)
    assert out["task"] == task and out["state"] == "completed"
    assert {"reason", "exit_code", "tree", "log", "duration_s"} <= set(out)
    assert out["capabilities"]["python"]
    assert set(out["capabilities"]) == set(fleet.CAPABILITY_TOOLS)
    listed = json.loads(hub.cli("status").stdout.strip().splitlines()[-1])["members"]
    assert [(m["name"], m["online"]) for m in listed] == [("local", True)]


def test_ac09_stopped_member_makes_wait_exit_5(tmp_path):
    hub = Hub(tmp_path, offline_after=1)
    hub.start()
    try:
        member = hub.pair("local")
        member.start()
        wait_until(lambda: member_row(hub, "local").get("online"), timeout=40)
        member.stop()
        task = send_ping(hub, "local")
        time.sleep(1.5)
        r = hub.cli("wait", task, "--timeout", "5")
        assert r.returncode == 5, r.stdout + r.stderr
        assert last_json(r)["state"] == "submitted"
    finally:
        hub.close()


# AC-10: atomic claim


def test_ac10_concurrent_claims_give_one_working_row(hub):
    member = hub.pair("local")
    client = member.hello()
    task = send_ping(hub, "local")
    results = []

    threads = [threading.Thread(target=lambda: results.append(next_task(client))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert [r["task_id"] for r in results] == [task] * 8
    assert status_rows(hub, task, "working") == 1


def test_ac10_repeat_next_returns_the_same_task_and_adds_no_row(hub):
    client = hub.pair("local").hello()
    task = send_ping(hub, "local")
    assert next_task(client)["task_id"] == task
    before = hub.rows()
    assert next_task(client)["task_id"] == task
    assert hub.rows() == before


def test_ac10_next_with_no_task_is_null(hub):
    assert next_task(hub.pair("local").hello()) is None


# AC-11: status posts


def test_ac11_status_posts_are_owner_transition_and_id_checked(hub):
    a = hub.pair("a").hello()
    b = hub.pair("b").hello()
    task = send_ping(hub, "a")
    assert next_task(a)["task_id"] == task

    before = hub.rows()
    status, reply = post(b, status_message("b", task))
    assert (status, reply["error"]) == (403, "not_your_task")
    status, reply = post(b, status_message("a", task))
    assert (status, reply["error"]) == (403, "from_mismatch")
    assert hub.rows() == before

    first = status_message("a", task)
    assert post(a, first)[0] == 200
    recorded = hub.rows()

    status, reply = post(a, status_message("a", task, "failed"))
    assert (status, reply["error"]) == (409, "bad_transition")
    status, reply = post(a, first)
    assert (status, reply.get("result")) == (200, "already_recorded")
    status, reply = post(a, {**first, "created": "2026-11-04T00:00:00Z"})
    assert (status, reply["error"]) == (409, "duplicate_id")
    assert hub.rows() == recorded


def test_ac11_status_needs_a_string_state_and_a_status_kind(hub):
    a = hub.pair("a").hello()
    task = send_ping(hub, "a")
    next_task(a)
    before = hub.rows()
    status, reply = post(a, status_message("a", task, body={"state": ["x"]}))
    assert (status, reply["error"]) == (400, "bad_field:body")
    status, reply = post(a, {**status_message("a", task), "kind": "ping"})
    assert (status, reply["error"]) == (400, "bad_field:kind")
    assert hub.rows() == before


# AC-13: offline delivery and restarts


def test_ac13_task_sent_while_off_reaches_the_member_on_start(hub):
    member = hub.pair("local")
    task = send_ping(hub, "local")
    member.start()
    wait_until(lambda: task_info(hub, task)["state"] == "completed", timeout=40)


def test_ac13_hub_restart_keeps_pin_and_tasks(hub):
    hub.pair("local")
    pin = hub.pin()
    task = send_ping(hub, "local")
    hub.stop()
    hub.start()
    assert hub.pin() == pin
    assert task_info(hub, task)["state"] == "submitted"


def test_ac13_result_lands_across_a_hub_restart(hub):
    client = hub.pair("local").hello()
    task = send_ping(hub, "local")
    claimed = next_task(client)
    hub.stop()
    thread = threading.Thread(target=fleet.post_status, args=(client, claimed, {"state": "completed"}))
    thread.start()
    time.sleep(1)
    assert thread.is_alive()
    hub.start()
    thread.join(60)
    assert not thread.is_alive()
    assert task_info(hub, task)["state"] == "completed"


def test_ac13_busy_member_makes_wait_exit_4(hub):
    client = hub.pair("local").hello()
    send_ping(hub, "local")
    next_task(client)
    second = send_ping(hub, "local")
    r = hub.cli("wait", second, "--timeout", "1")
    assert r.returncode == 4, r.stdout + r.stderr
    assert last_json(r)["state"] == "submitted"


def test_ac13_hub_down_makes_status_exit_2(hub):
    hub.stop()
    r = hub.cli("status")
    assert r.returncode == 2
    assert "hub_unreachable" in r.stdout + r.stderr


# AC-14: member restart and stale sessions


def test_ac14_restart_fails_the_members_working_task(hub):
    member = hub.pair("local")
    client = member.hello()
    task = send_ping(hub, "local")
    next_task(client)
    member.start()
    wait_until(lambda: task_info(hub, task)["state"] == "failed", timeout=40)
    assert task_info(hub, task)["status"]["reason"] == "member_restarted"


def test_ac14_second_process_makes_the_first_exit_2(hub):
    member = hub.pair("local")
    first = member.start()
    wait_online(hub, "local")
    second = member.start()
    assert first.wait(60) == 2
    assert second.poll() is None
    assert "stale_session" in (member.home / "member-test.log").read_text(errors="replace")


# AC-15, the plan's concurrent ping


def test_ac15_raw_client_does_not_stop_a_concurrent_ping(hub):
    member = hub.pair("local")
    member.start()
    wait_online(hub, "local")
    idle = [socket.create_connection(("127.0.0.1", hub.port), 5) for _ in range(3)]
    try:
        r = hub.cli("wait", send_ping(hub, "local"), "--timeout", "30")
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        for s in idle:
            s.close()
