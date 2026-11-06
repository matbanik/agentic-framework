"""Test harness for the fleet: real hub and member subprocesses with temporary homes.

Approval calls ``approve_member`` directly, because the ``approve`` CLI requires a TTY.
"""
from __future__ import annotations

import importlib.util
import os
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLEET_PY = ROOT / ".agent" / "fleet" / "fleet.py"
FAST_POLL = "0.1"


def load_fleet():
    if "fleet" in sys.modules:
        return sys.modules["fleet"]
    spec = importlib.util.spec_from_file_location("fleet", FLEET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fleet"] = mod
    spec.loader.exec_module(mod)
    return mod


fleet = load_fleet()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_cli(home: Path, *args: str, timeout: float = 60, env: dict | None = None):
    full = {**os.environ, "FLEET_HOME": str(home), **(env or {})}
    return subprocess.run(
        [sys.executable, str(FLEET_PY), *args],
        env=full,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def new_envelope(sender: str, to: str, kind: str = "ping", **over) -> dict:
    task = fleet.new_id()
    env = {
        "v": fleet.ENVELOPE_VERSION,
        "id": task,
        "task_id": task,
        "from": sender,
        "to": to,
        "kind": kind,
        "created": "2026-11-03T00:00:00Z",
        "body": {},
        "refs": {},
        "reply_to": None,
        "requires_human": False,
        "start_quote": None,
    }
    env.update(over)
    return env


def wait_until(predicate, timeout: float = 20, step: float = 0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    raise AssertionError(f"condition not met within {timeout}s")


class Member:
    def __init__(self, hub: "Hub", name: str, home: Path, code: str):
        self.hub, self.name, self.home, self.code = hub, name, home, code
        self.proc: subprocess.Popen | None = None

    def client(self):
        return fleet.load_member_client(self.home)

    def key(self) -> str:
        return self.client().key

    def hello(self) -> str:
        """Open a session as this member, without starting a member process."""
        client = self.client()
        status, reply = fleet.hub_request(client, "POST", "/v1/hello", {"capabilities": {}})
        assert status == 200, reply
        client.session = reply["session"]
        return client

    def start(self, *extra: str, env: dict | None = None) -> subprocess.Popen:
        full = {**os.environ, "FLEET_HOME": str(self.home), **(env or {})}
        log = open(self.home / "member-test.log", "ab")
        self.proc = subprocess.Popen(
            [sys.executable, str(FLEET_PY), "member", "--poll", FAST_POLL, *extra],
            env=full,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        log.close()
        self.hub.procs.append(self.proc)
        return self.proc

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)


class Hub:
    def __init__(self, tmp: Path, offline_after: float | None = None):
        self.tmp = Path(tmp)
        self.home = self.tmp / "hub-home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.port = free_port()
        self.offline_after = offline_after
        self.proc: subprocess.Popen | None = None
        self.procs: list[subprocess.Popen] = []

    @property
    def hub_dir(self) -> Path:
        return self.home / "hub"

    @property
    def db(self) -> Path:
        return self.hub_dir / "hub.db"

    @property
    def stdout_path(self) -> Path:
        return self.tmp / "hub-stdout.txt"

    def start(self) -> None:
        args = [sys.executable, str(FLEET_PY), "hub", "--port", str(self.port)]
        if self.offline_after is not None:
            args += ["--offline-after", str(self.offline_after)]
        out = open(self.stdout_path, "ab")
        self.proc = subprocess.Popen(
            args,
            env={**os.environ, "FLEET_HOME": str(self.home)},
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        out.close()
        self.procs.append(self.proc)
        wait_until(self._answers, timeout=30)

    def _answers(self) -> bool:
        if self.proc.poll() is not None:
            raise AssertionError(f"hub exited: {self.stdout_path.read_text(errors='replace')}")
        if not (self.hub_dir / "hub.json").exists():
            return False
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with socket.create_connection(("127.0.0.1", self.port), 1) as raw:
                with ctx.wrap_socket(raw):
                    return True
        except OSError:
            return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)

    def close(self) -> None:
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait(10)

    def client(self):
        return fleet.load_hub_client(self.home)

    def pin(self) -> str:
        return self.client().pin

    def url(self) -> str:
        return self.client().url

    def store(self):
        return fleet.Store(self.db)

    def cli(self, *args: str, timeout: float = 60, env: dict | None = None):
        return run_cli(self.home, *args, timeout=timeout, env=env)

    def pair(self, name: str, approve: bool = True) -> Member:
        home = self.tmp / f"member-{name}"
        home.mkdir(parents=True, exist_ok=True)
        r = run_cli(home, "pair", "--hub", self.url(), "--pin", self.pin(), "--name", name)
        assert r.returncode == 0, r.stdout + r.stderr
        code = fleet.json.loads(r.stdout.strip().splitlines()[-1])["code"]
        member = Member(self, name, home, code)
        if approve:
            fleet.approve_member(self.store(), name, code)
        return member

    def request(self, method: str, path: str, body=None, key: str | None = None):
        client = self.client()
        client.key = key
        return fleet.hub_request(client, method, path, body)

    def rows(self) -> int:
        return self.store().count_messages()
