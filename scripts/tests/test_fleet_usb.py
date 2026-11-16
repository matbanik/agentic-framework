"""The USB kit usability plan's ACs for setup-unix.sh and fleet_usb.py, numbered as in the plan
(docs/execution/plans/2026-11-15-usb-kit-usability/implementation-plan.md).

setup-unix.sh runs as a file under the Git bash on Windows (or /bin/bash elsewhere), with a stub folder
first on PATH and FLEET_ROOT set to a temp folder, so no test touches the system it runs on.
"""
from __future__ import annotations

import hashlib
import http.client
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
USB = REPO / ".agent" / "fleet" / "usb"
SCRIPT = USB / "setup-unix.sh"

_spec = importlib.util.spec_from_file_location("fleet_usb", USB / "fleet_usb.py")
fleet_usb = importlib.util.module_from_spec(_spec)
sys.modules["fleet_usb"] = fleet_usb
_spec.loader.exec_module(fleet_usb)

STEP_LIST = ("elevate", "account", "packages", "ssh_server", "firewall", "hub_key", "admin_rights", "linger",
             "homebrew", "pwsh", "uv", "claude", "codex", "tool_links", "rustdesk", "host_key")
HUB_PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGb0m2nJ7tq1oQxkO6sVhJmXvGQ3tGx1rW2c8yYhCq3d fleet-admin\n"
HOST_PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHk2mQ7c9fV1pXw3sLr8tN0bYc4eZq6uJd5aGh2iKo1m root@member\n"
ACCOUNT = "lab"
HOSTNAME = "Lab_Mini07"


# ----------------------------------------------------------------------------------------------- bash

def git_bash() -> str | None:
    """Git's bash on Windows: walk up from git to the Git root and take its bin/bash.exe, never a WSL bash."""
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if not git:
        return None
    start = Path(git).resolve().parent
    for folder in (start, *start.parents):
        candidate = folder / "bin" / "bash.exe"
        if candidate.is_file() and (folder / "usr" / "bin").is_dir():
            return str(candidate)
    return None


def need_bash() -> str:
    bash = git_bash()
    assert bash, "no Git bash was found (walked up from git); these tests need it and never skip"
    return bash


# Each stub logs its arguments, then runs its body. A test replaces a body to change one command.
STUB_BODIES = {
    "id": 'case "$1" in -u) echo "${STUB_UID:-0}";; -un) echo "$STUB_ACCOUNT";; -gn) echo "${2:-root}";; *) echo 0;; esac',
    "uname": 'case "$1" in -m) echo "${STUB_MACHINE:-x86_64}";; *) echo "${STUB_UNAME:-Linux}";; esac',
    "hostname": 'echo "$STUB_HOSTNAME"',
    "scutil": 'echo "$STUB_HOSTNAME"',
    # A name gives its own home; a numeric id (PKEXEC_UID) gives the account "uid<number>".
    "getent": ('case "$2" in [0-9]*) echo "uid$2:x:$2:$2::/home/uid$2:/bin/bash";; '
               '*) echo "$2:x:1000:1000::/home/$2:/bin/bash";; esac'),
    "dscl": ('case "$2" in -search) echo "uid$5 UniqueID = ($5)";; '
             '*) echo "NFSHomeDirectory: /Users/$STUB_ACCOUNT";; esac'),
    "apt-get": "exit 0",
    "systemctl": "exit 0",
    "loginctl": 'case "$1" in show-user) echo Linger=yes;; esac',
    "ip": 'echo "2: eth0    inet 192.0.2.10/24 brd 192.0.2.255 scope global eth0"',
    "ssh-keygen": ('case "$1" in -A) mkdir -p "$FLEET_ROOT/etc/ssh"; '
                   'printf "%s\\n" "$STUB_HOST_PUB" > "$FLEET_ROOT/etc/ssh/ssh_host_ed25519_key.pub";; '
                   '-lf) echo "256 SHA256:stubfingerprint fleet-admin (ED25519)";; esac'),
    # install writes only below FLEET_ROOT, so a script that forgets FLEET_ROOT fails instead of writing the system.
    "install": r'''dir=0; args=()
while [ $# -gt 0 ]; do case "$1" in -d) dir=1;; -m|-o|-g) shift;; *) args+=("$1");; esac; shift; done
inside() { case "$1" in "$FLEET_ROOT"/*) return 0;; esac; echo "install stub: $1 is outside FLEET_ROOT" >&2; return 1; }
if [ $dir = 1 ]; then for a in "${args[@]}"; do inside "$a" || exit 1; mkdir -p "$a"; done
else inside "${args[1]}" || exit 1; cp "${args[0]}" "${args[1]}"; fi''',
    "chown": "exit 0",
    "visudo": "exit 0",
    "sudo": "exit 0",
    "runuser": "exit 0",
    "curl": "exit 0",
    "sync": "exit 0",
    "launchctl": "exit 0",
    "systemsetup": "exit 0",
}


def stub_text(name: str, body: str) -> str:
    return f'#!/bin/bash\nprintf "%s\\n" "{name} $*" >> "$STUB_LOG"\n{body}\n'


class Kit:
    """A drive folder with the script and hub.pub, a FLEET_ROOT and a stub folder."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.drive = tmp / "drive" / "fleet-usb"
        self.root = tmp / "root"
        self.stubs = tmp / "stubs"
        self.log = tmp / "stub.log"
        for folder in (self.drive, self.root, self.stubs):
            folder.mkdir(parents=True)
        (self.root / "home" / ACCOUNT).mkdir(parents=True)
        (self.drive / "setup-unix.sh").write_bytes(SCRIPT.read_bytes().replace(b"\r\n", b"\n"))
        (self.drive / "hub.pub").write_text(HUB_PUB, encoding="ascii", newline="\n")
        self.bodies = dict(STUB_BODIES)
        # The PATH that the stub folder is put in front of. A test of the installers sets a minimal one.
        self.base_path = "$PATH"

    def write_stubs(self) -> None:
        for name, body in self.bodies.items():
            stub = self.stubs / name
            stub.write_bytes(stub_text(name, body).encode("utf-8"))
            stub.chmod(0o755)

    def env(self, **extra: str) -> dict:
        env = dict(os.environ)
        env.update({
            "FLEET_ROOT": self.root.as_posix(),
            "STUB_BIN": self.stubs.as_posix(),
            "STUB_LOG": self.log.as_posix(),
            "STUB_ACCOUNT": ACCOUNT,
            "STUB_HOSTNAME": HOSTNAME,
            "STUB_HOST_PUB": HOST_PUB.strip(),
            "SUDO_USER": ACCOUNT,
        })
        env.update(extra)
        return env

    def run(self, *args: str, timeout: int = 180, **extra: str) -> subprocess.CompletedProcess:
        self.write_stubs()
        bash = need_bash()
        # Git's bash.exe puts its own folders first on PATH; the stub folder goes first only after it starts.
        # FLEET_TOOL_PATH keeps the lookup of sudo, pkexec and visudo to the stubs: a host may have real ones.
        launcher = ('PATH="$(cygpath -u "$STUB_BIN" 2>/dev/null || echo "$STUB_BIN"):' + self.base_path + '"; export PATH; '
                    'FLEET_TOOL_PATH="$(cygpath -u "$STUB_BIN" 2>/dev/null || echo "$STUB_BIN")"; export FLEET_TOOL_PATH; '
                    'exec "$BASH" "$@"')
        return subprocess.run([bash, "-c", launcher, "_", (self.drive / "setup-unix.sh").as_posix(), *args],
                              capture_output=True, timeout=timeout, env=self.env(**extra))

    def record_path(self) -> Path:
        return self.drive / "members" / "lab-mini07.json"

    def record(self) -> dict:
        path = self.record_path()
        assert path.is_file(), f"no record at {path}"
        return json.loads(path.read_text(encoding="utf-8"))


def ids(record: dict) -> list[str]:
    return [s["step"] for s in record["steps"]]


def status(record: dict, step: str) -> dict:
    found = [s for s in record["steps"] if s["step"] == step]
    assert found, f"step {step} is not in the record: {ids(record)}"
    return found[0]


def in_step_order(record: dict) -> bool:
    order = [STEP_LIST.index(s) for s in ids(record)]
    return order == sorted(order) and len(set(order)) == len(order)


@pytest.fixture
def kit(tmp_path: Path) -> Kit:
    return Kit(tmp_path)


def output(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")[-3000:]


# ----------------------------------------------------------------------------------------------- AC-1

def test_ac01_all_steps_ok_writes_a_final_record_and_checkpoints(kit: Kit):
    snapshot = kit.tmp / "snapshot.json"
    # The linger step's stub reads the drive file: it must already hold the steps before linger.
    kit.bodies["loginctl"] = (f'case "$1" in show-user) cp "{kit.record_path().as_posix()}" "{snapshot.as_posix()}"; '
                              'echo Linger=yes;; esac')
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    record = kit.record()
    assert record["v"] == 2 and record["final"] is True and record["ok"] is True
    assert all(s["status"] in ("ok", "skipped") for s in record["steps"]), record["steps"]
    for step in ("elevate", "account", "packages", "ssh_server", "hub_key", "admin_rights", "linger", "host_key"):
        assert status(record, step)["status"] == "ok", record["steps"]
    assert in_step_order(record)
    assert record["host_key"] == " ".join(HOST_PUB.split()[:2])
    assert record["port"] == 22 and record["addresses"] == ["192.0.2.10"]
    fleet_usb.read_record(kit.record_path())
    assert snapshot.is_file(), "the linger stub found no checkpoint on the drive"
    checkpoint = json.loads(snapshot.read_text(encoding="utf-8"))
    assert checkpoint["final"] is False and checkpoint["ok"] is False
    assert ids(checkpoint) == ids(record)[:ids(record).index("linger")]
    assert checkpoint["run_id"] == record["run_id"]


def test_ac01_a_failed_step_ends_that_step_and_the_later_steps_still_run(kit: Kit):
    kit.bodies["apt-get"] = "exit 100"
    proc = kit.run()
    assert proc.returncode == 1, output(proc)
    record = kit.record()
    assert record["final"] is True and record["ok"] is False
    packages = status(record, "packages")
    assert packages["status"] == "failed" and "100" in packages["detail"]
    later = ids(record)[ids(record).index("packages") + 1:]
    assert "ssh_server" in later and "host_key" in later
    assert status(record, "host_key")["status"] == "ok"
    fleet_usb.read_record(kit.record_path())


def test_ac01_an_unexpected_error_outside_any_step_still_writes_the_final_record(kit: Kit):
    # sync runs after each record write, outside every step; its third call fails, as a drive I/O error would.
    counter = (kit.tmp / "sync.count").as_posix()
    kit.bodies["sync"] = (f'n=$(( $(cat "{counter}" 2>/dev/null || echo 0) + 1 )); echo $n > "{counter}"; '
                          '[ $n -ne 3 ]')
    proc = kit.run()
    assert proc.returncode == 1, output(proc)
    record = kit.record()
    assert record["final"] is True and record["ok"] is False
    assert all(s["status"] != "failed" for s in record["steps"]), record["steps"]
    fleet_usb.read_record(kit.record_path())


@pytest.mark.parametrize("signal", ["INT", "HUP"])
def test_ac01_a_signal_ends_the_running_step_interrupted_and_finalizes(kit: Kit, signal: str):
    kit.bodies["loginctl"] = (f'case "$1" in show-user) kill -{signal} "$FLEET_SETUP_PID"; sleep 2; '
                              'echo Linger=yes;; esac')
    proc = kit.run()
    assert proc.returncode != 0, output(proc)
    record = kit.record()
    assert record["final"] is True and record["ok"] is False
    linger = status(record, "linger")
    assert linger["status"] == "failed" and linger["detail"] == "interrupted"
    assert ids(record)[-1] == "linger", ids(record)
    fleet_usb.read_record(kit.record_path())


def test_ac01_a_forced_kill_leaves_the_last_checkpoint(kit: Kit):
    kit.bodies["loginctl"] = 'case "$1" in show-user) kill -KILL "$FLEET_SETUP_PID"; sleep 2;; esac'
    proc = kit.run()
    assert proc.returncode != 0, output(proc)
    record = kit.record()
    assert record["final"] is False and record["ok"] is False
    assert "linger" not in ids(record) and ids(record)[-1] == "admin_rights", ids(record)
    fleet_usb.read_record(kit.record_path())


# ----------------------------------------------------------------------------------------------- AC-3

NAME_CASES = {
    "Lab_Mini07": "lab-mini07",
    "--Lab PC__2--": "lab-pc-2",
    "___": "member",
    "a" * 62 + "_" + "b" * 7: "a" * 62,
    "LAB-PC": "lab-pc",
}


def test_ac03_the_bash_name_rule(tmp_path: Path):
    bash = need_bash()
    script = tmp_path / "setup-unix.sh"
    script.write_bytes(SCRIPT.read_bytes().replace(b"\r\n", b"\n"))
    got = {}
    for raw, want in NAME_CASES.items():
        proc = subprocess.run([bash, "-c", 'source "$1" && name_rule "$2"', "_", script.as_posix(), raw],
                              capture_output=True, timeout=60)
        got[raw] = proc.stdout.decode("utf-8", errors="replace").strip()
    assert got == NAME_CASES
    assert all(fleet_usb.NAME.match(v) for v in got.values())
    assert got["Lab_Mini07"] != "lab_mini07"


# ----------------------------------------------------------------------------------------------- AC-4

def v2(**changes) -> dict:
    record = {
        "v": 2, "run_id": "abcd1234efgh5678", "final": True, "name": "lab-mini07", "os": "linux", "user": ACCOUNT,
        "ok": True,
        "steps": [{"step": "elevate", "status": "ok", "detail": ""},
                  {"step": "ssh_server", "status": "ok", "detail": "already on"},
                  {"step": "host_key", "status": "ok", "detail": ""}],
        "tools": {"git": "git version 2.43.0"}, "gui": True, "session_type": "wayland", "rustdesk_id": "123456789",
        "port": 22, "host_key": " ".join(HOST_PUB.split()[:2]), "addresses": ["192.0.2.10"], "delivery": None,
    }
    record.update(changes)
    return record


V1 = {"v": 1, "name": "lab-mini07", "os": "linux", "user": ACCOUNT, "port": 22, "addresses": ["192.0.2.10"],
      "host_key": " ".join(HOST_PUB.split()[:2]), "changed": [], "created": "2026-11-15T00:00:00Z"}


def write(tmp_path: Path, record: dict, name: str = "lab-mini07.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


ACCEPTED = {
    "v1": V1,
    "v2": v2(),
    "checkpoint": v2(final=False, ok=False, steps=[{"step": "elevate", "status": "ok", "detail": ""}],
                     port=None, host_key=None, addresses=[]),
    "delivery pending": v2(delivery={"status": "pending", "detail": ""}),
    "delivery sent": v2(delivery={"status": "sent", "detail": "http://192.0.2.1:8771"}),
    "delivery failed": v2(delivery={"status": "failed", "detail": "http://192.0.2.1:8771: timed out"}),
}

REFUSED = {
    "unknown key": v2(extra=1),
    "missing key": {k: v for k, v in v2().items() if k != "gui"},
    "bad status": v2(steps=[{"step": "elevate", "status": "done", "detail": ""}], port=None, host_key=None,
                     addresses=[]),
    "bad rustdesk_id": v2(rustdesk_id="12ab"),
    "ok beside a failed step": v2(steps=[{"step": "elevate", "status": "failed", "detail": "x"},
                                         {"step": "ssh_server", "status": "ok", "detail": ""},
                                         {"step": "host_key", "status": "ok", "detail": ""}]),
    "ok with final false": v2(final=False),
    "bad delivery status": v2(delivery={"status": "lost", "detail": ""}),
    "host_key ok without a host key": v2(host_key=None),
    "v3": v2(v=3),
}


@pytest.mark.parametrize("case", list(ACCEPTED))
def test_ac04_read_record_accepts(tmp_path: Path, case: str):
    got = fleet_usb.read_record(write(tmp_path, ACCEPTED[case]))
    assert got["name"] == "lab-mini07" and got["v"] == ACCEPTED[case]["v"]


@pytest.mark.parametrize("case", list(REFUSED))
def test_ac04_read_record_refuses(tmp_path: Path, case: str):
    with pytest.raises(ValueError):
        fleet_usb.read_record(write(tmp_path, REFUSED[case]))


def test_ac04_the_bash_json_writer_round_trips_a_hard_detail(tmp_path: Path):
    bash = need_bash()
    script = tmp_path / "setup-unix.sh"
    script.write_bytes(SCRIPT.read_bytes().replace(b"\r\n", b"\n"))
    detail = 'a "quoted" C:\\path\\x\ttab\nnew line \u00e9\u2014\u4e2d \x01 end'
    (tmp_path / "detail.txt").write_bytes(detail.encode("utf-8"))
    drive = tmp_path / "drive"
    (drive / "members").mkdir(parents=True)
    code = ('source "$1" && usb="$2" && name=lab-mini07 && os=linux && user=lab && run_id=abcd1234efgh5678 '
            '&& add_step elevate failed "$(cat "$3")" && write_record true')
    proc = subprocess.run([bash, "-c", code, "_", script.as_posix(), drive.as_posix(),
                           (tmp_path / "detail.txt").as_posix()], capture_output=True, timeout=60)
    assert proc.returncode == 0, output(proc)
    path = drive / "members" / "lab-mini07.json"
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    record = json.loads(raw.decode("utf-8"))
    assert record["steps"][0]["detail"] == detail
    assert record["ok"] is False and record["final"] is True
    fleet_usb.read_record(path)


# ----------------------------------------------------------------------------------------------- AC-6

KEY_B = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBq7Yt2vK9mRw4xLc1sNf8jDh3gUe5oPa6zXiT0yVbWk"
FAILED_DELIVERY = {"status": "failed", "detail": "http://192.0.2.1:8771: timed out"}


class FakeSsh:
    """fleet_usb.ssh_run, replaced: it records each call (name, remote command, standard input) and answers."""

    def __init__(self):
        self.calls: list[dict] = []
        self.code = 0
        self.stderr = ""

    def __call__(self, name: str, command: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        self.calls.append({"name": name, "command": command, "stdin": stdin})
        return subprocess.CompletedProcess(["ssh", name, command], self.code, "", self.stderr)


class Hub:
    """import_records run in this process with a temp ~/.ssh, a fake reachability probe and a fake SSH test."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
        self.ssh = tmp_path / "home" / ".ssh"
        self.ssh.mkdir(parents=True)
        (self.ssh / fleet_usb.KEY_NAME).write_text("stub private key\n", encoding="ascii")
        self.folder = tmp_path / "drive"
        (self.folder / "members").mkdir(parents=True)
        self.capsys = capsys
        monkeypatch.setattr(fleet_usb, "ssh_dir", lambda: self.ssh)
        monkeypatch.setattr(fleet_usb, "reachable", lambda addresses, port: addresses[0])
        monkeypatch.setattr(fleet_usb, "test_connection", lambda name, system: "full access")
        # The RustDesk password step of import (AC-19) runs through ssh_run, so no test reaches a real ssh.
        self.remote = FakeSsh()
        monkeypatch.setattr(fleet_usb, "ssh_run", self.remote, raising=False)

    def put(self, record: dict) -> None:
        (self.folder / "members" / f"{record['name']}.json").write_text(json.dumps(record), encoding="utf-8")

    def run(self) -> tuple[int, dict[str, str]]:
        """The exit code and the output line of each record, keyed by the record's name (the line's first word)."""
        code = fleet_usb.import_records(self.folder, test=True)
        lines = self.capsys.readouterr().out.splitlines()
        return code, {line.split(":", 1)[0]: line for line in lines if ":" in line}

    def pinned(self) -> dict:
        state = self.ssh / "fleet_members.json"
        return json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> Hub:
    return Hub(tmp_path, monkeypatch, capsys)


def failed_host_key(name: str) -> dict:
    return v2(name=name, ok=False, port=None, host_key=None, addresses=[], delivery=FAILED_DELIVERY,
              steps=[{"step": "elevate", "status": "ok", "detail": ""},
                     {"step": "ssh_server", "status": "failed", "detail": "sshd would not start"},
                     {"step": "host_key", "status": "failed", "detail": "no host key file"}])


def test_ac06_a_good_record_with_a_failed_delivery_imports_and_exits_0(hub: Hub):
    hub.put(v2(delivery=FAILED_DELIVERY))
    code, lines = hub.run()
    assert code == 0, lines
    assert lines["lab-mini07"].startswith("lab-mini07: ok, delivery failed, ssh lab-mini07 -> lab@192.0.2.10"), lines
    assert hub.pinned()["lab-mini07"]["host_key"] == v2()["host_key"]


def test_ac06_a_record_without_a_host_key_is_reported_and_skipped(hub: Hub):
    hub.put(v2(delivery=FAILED_DELIVERY))
    hub.put(failed_host_key("lab-mini08"))
    code, lines = hub.run()
    assert code == 1
    assert lines["lab-mini08"].startswith("lab-mini08: failed: ssh_server, host_key, delivery failed"), lines
    assert "lab-mini07: ok, delivery failed" in lines["lab-mini07"]
    assert set(hub.pinned()) == {"lab-mini07"}
    assert "lab-mini08" not in (hub.ssh / "fleet_known_hosts").read_text(encoding="utf-8")
    assert "lab-mini08" not in (hub.ssh / fleet_usb.CONFIG_NAME).read_text(encoding="utf-8")


def test_ac06_a_checkpoint_with_a_host_key_is_incomplete_and_still_imported(hub: Hub):
    hub.put(v2(final=False, ok=False,
               steps=[{"step": "elevate", "status": "ok", "detail": ""},
                      {"step": "ssh_server", "status": "ok", "detail": ""},
                      {"step": "host_key", "status": "ok", "detail": ""}]))
    code, lines = hub.run()
    assert code == 1
    assert lines["lab-mini07"].startswith("lab-mini07: incomplete after host_key, delivery none, ssh lab-mini07 -> "), lines
    assert "lab-mini07" in hub.pinned()


def test_ac06_a_checkpoint_without_a_host_key_is_incomplete_and_not_pinned(hub: Hub):
    hub.put(v2(final=False, ok=False, port=None, host_key=None, addresses=[],
               steps=[{"step": "elevate", "status": "ok", "detail": ""},
                      {"step": "account", "status": "ok", "detail": ""}]))
    code, lines = hub.run()
    assert code == 1
    assert lines["lab-mini07"].startswith("lab-mini07: incomplete after account, delivery none, "), lines
    assert hub.pinned() == {}


def test_ac06_a_v1_record_imports_as_before(hub: Hub):
    hub.put(V1)
    code, lines = hub.run()
    assert code == 0, lines
    assert lines["lab-mini07"] == "lab-mini07: ssh lab-mini07 -> lab@192.0.2.10, full access"
    assert hub.pinned()["lab-mini07"]["port"] == 22


# ----------------------------------------------------------------------------------------------- AC-7

ELEVATORS = ("sudo", "sudo-rs", "sudo.ws", "pkexec")
ELEVATE = 'STUB_UID=0 "$@"'  # the elevated child sees user id 0 through the stub id


def set_elevators(kit: Kit, bodies: dict[str, str]) -> None:
    """Only these elevators exist on the stub PATH, each with the given body."""
    for name in ELEVATORS:
        kit.bodies.pop(name, None)
    kit.bodies.update(bodies)


def parent_run(kit: Kit, *args: str, **extra: str) -> subprocess.CompletedProcess:
    """The script started by an ordinary user: the stub id says 1000 and no sudo variable names the Account."""
    return kit.run(*args, STUB_UID="1000", SUDO_USER="", **extra)


def log_lines(kit: Kit) -> list[str]:
    return kit.log.read_text(encoding="utf-8").splitlines() if kit.log.exists() else []


def elevated_calls(kit: Kit) -> list[str]:
    return [line for line in log_lines(kit) if line.split(" ", 1)[0] in ELEVATORS and " bash " in line]


def track_finals(kit: Kit) -> Path:
    """Each record write ends with sync; this sync stub copies the record's final line, so every write is counted."""
    finals = kit.tmp / "finals.log"
    kit.bodies["sync"] = (f'grep -h \'"final"\' "{kit.record_path().as_posix()}" >> "{finals.as_posix()}" '
                          '2>/dev/null; exit 0')
    return finals


def final_writes(finals: Path) -> int:
    return finals.read_text(encoding="utf-8").count('"final": true') if finals.exists() else 0


def test_ac07_without_sudo_the_script_reruns_through_sudo_rs(kit: Kit):
    set_elevators(kit, {"sudo-rs": ELEVATE})
    proc = parent_run(kit)
    assert proc.returncode == 0, output(proc)
    calls = elevated_calls(kit)
    assert len(calls) == 1, calls
    match = re.fullmatch(r"sudo-rs bash (\S+setup-unix\.sh) --for-user lab --run-id ([a-z0-9]{16})", calls[0])
    assert match, calls
    record = kit.record()
    assert match.group(2) == record["run_id"]
    assert record["final"] is True and record["ok"] is True
    assert status(record, "elevate")["status"] == "ok"
    fleet_usb.read_record(kit.record_path())


def test_ac07_a_dangling_sudo_link_is_repaired_before_the_chain(kit: Kit):
    link = kit.root / "usr" / "bin" / "sudo"
    link.parent.mkdir(parents=True)
    os.symlink("no-such-target", link)
    # After the repair call, a working sudo exists on the stub PATH.
    after = kit.tmp / "sudo-after-repair"
    after.write_bytes(stub_text("sudo", ELEVATE).encode("utf-8"))
    set_elevators(kit, {"pkexec": (f'case "$1" in update-alternatives) cp "{after.as_posix()}" "$STUB_BIN/sudo";; '
                                   f'bash) {ELEVATE};; esac')})
    kit.bodies["update-alternatives"] = "exit 0"
    proc = parent_run(kit)
    assert proc.returncode == 0, output(proc)
    lines = log_lines(kit)
    repair = [i for i, line in enumerate(lines) if line == "pkexec update-alternatives --auto sudo"]
    chain = [i for i, line in enumerate(lines) if line.startswith("sudo bash ")]
    assert len(repair) == 1 and len(chain) == 1 and repair[0] < chain[0], lines
    assert not any(line.startswith("pkexec bash ") for line in lines), lines
    assert "update-alternatives" in (proc.stderr + proc.stdout).decode("utf-8", errors="replace")


def test_ac07_with_every_elevator_missing_the_parent_writes_one_final_record(kit: Kit):
    set_elevators(kit, {})
    finals = track_finals(kit)
    proc = parent_run(kit)
    assert proc.returncode == 1, output(proc)
    record = kit.record()
    assert record["final"] is True and record["ok"] is False and record["user"] == ACCOUNT
    elevate = status(record, "elevate")
    assert elevate["status"] == "failed" and elevate["detail"].startswith("elevation failed"), elevate
    others = [s for s in record["steps"] if s["step"] != "elevate"]
    assert others and all(s["status"] == "skipped" for s in others), record["steps"]
    assert final_writes(finals) == 1
    fleet_usb.read_record(kit.record_path())


def test_ac07_an_elevated_run_that_wrote_a_final_record_adds_no_second_record(kit: Kit):
    set_elevators(kit, {"sudo": ELEVATE})
    kit.bodies["apt-get"] = "exit 100"
    finals = track_finals(kit)
    proc = parent_run(kit)
    assert proc.returncode == 1, output(proc)
    record = kit.record()
    assert status(record, "elevate")["status"] == "ok"
    assert status(record, "packages")["status"] == "failed"
    assert final_writes(finals) == 1
    assert len(elevated_calls(kit)) == 1


def test_ac07_an_elevated_run_that_left_only_a_checkpoint_is_finalized_by_the_parent(kit: Kit):
    set_elevators(kit, {"sudo": ELEVATE})
    kit.bodies["loginctl"] = 'case "$1" in show-user) kill -KILL "$FLEET_SETUP_PID"; sleep 2;; esac'
    finals = track_finals(kit)
    proc = parent_run(kit)
    assert proc.returncode == 1, output(proc)
    run_id = re.fullmatch(r".*--run-id ([a-z0-9]{16})", elevated_calls(kit)[0]).group(1)
    record = kit.record()
    assert record["final"] is True and record["ok"] is False and record["run_id"] == run_id
    elevate = status(record, "elevate")
    assert elevate["status"] == "failed" and "sudo" in elevate["detail"], elevate
    assert final_writes(finals) == 1
    fleet_usb.read_record(kit.record_path())


@pytest.mark.parametrize("code", [126, 127])
def test_ac07_a_fallback_code_tries_the_next_elevator(kit: Kit, code: int):
    set_elevators(kit, {"sudo": f"exit {code}", "sudo-rs": ELEVATE})
    proc = parent_run(kit)
    assert proc.returncode == 0, output(proc)
    assert [call.split(" ", 1)[0] for call in elevated_calls(kit)] == ["sudo", "sudo-rs"]


def test_ac07_an_elevator_exit_that_is_not_a_fallback_code_ends_the_chain(kit: Kit):
    set_elevators(kit, {"sudo": "exit 1", "sudo-rs": ELEVATE})
    proc = parent_run(kit)
    assert proc.returncode == 1, output(proc)
    assert [call.split(" ", 1)[0] for call in elevated_calls(kit)] == ["sudo"]
    record = kit.record()
    elevate = status(record, "elevate")
    assert record["final"] is True and elevate["status"] == "failed" and "sudo exited 1" in elevate["detail"], elevate


def test_ac07_the_account_comes_from_for_user_before_sudo_user(kit: Kit):
    proc = kit.run("--for-user", ACCOUNT, SUDO_USER="mallory")
    assert proc.returncode == 0, output(proc)
    record = kit.record()
    assert record["user"] == ACCOUNT and status(record, "account")["detail"] == ACCOUNT


def test_ac07_the_account_comes_from_pkexec_uid_when_no_sudo_user_is_set(kit: Kit):
    proc = kit.run(SUDO_USER="", PKEXEC_UID="1000")
    assert status(kit.record(), "account")["detail"] == "uid1000", output(proc)
    assert kit.record()["user"] == "uid1000"


def test_ac07_as_root_with_no_named_account_the_account_step_fails(kit: Kit):
    proc = kit.run(SUDO_USER="")
    assert proc.returncode == 1, output(proc)
    assert status(kit.record(), "account")["status"] == "failed"


def test_ac07_as_root_the_script_does_not_elevate(kit: Kit):
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    assert elevated_calls(kit) == []


# ----------------------------------------------------------------------------------------------- AC-8

ACCOUNT_PATH_TAIL = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def account_command(kit: Kit, prefix: str) -> str:
    """The first logged line that starts with prefix, or a failure that lists what was logged."""
    lines = [line for line in log_lines(kit) if line.startswith(prefix)]
    assert lines, f"no logged command starts with {prefix!r}: {log_lines(kit)}"
    return lines[0]


def test_ac08_on_linux_account_commands_run_with_runuser_and_the_account_environment(kit: Kit):
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    home = f"{kit.root.as_posix()}/home/{ACCOUNT}"
    line = account_command(kit, f"runuser -u {ACCOUNT} -- env -i ")
    want = (f"runuser -u {ACCOUNT} -- env -i HOME={home} USER={ACCOUNT} LOGNAME={ACCOUNT} "
            f"PATH={home}/.local/bin:{home}/.cargo/bin:{ACCOUNT_PATH_TAIL} ")
    assert line.startswith(want), line


@pytest.mark.parametrize("machine, brew", [("arm64", "/opt/homebrew"), ("x86_64", "/usr/local")])
def test_ac08_on_macos_account_commands_run_with_sudo_u_h_and_the_account_environment(kit: Kit, machine: str, brew: str):
    proc = kit.run(STUB_UNAME="Darwin", STUB_MACHINE=machine)
    assert "account" in ids(kit.record()), output(proc)
    home = f"{kit.root.as_posix()}/Users/{ACCOUNT}"
    line = account_command(kit, f"sudo -u {ACCOUNT} -H env -i ")
    want = (f"sudo -u {ACCOUNT} -H env -i HOME={home} USER={ACCOUNT} LOGNAME={ACCOUNT} "
            f"PATH={home}/.local/bin:{home}/.cargo/bin:{brew}/bin:{brew}/sbin:{ACCOUNT_PATH_TAIL} ")
    assert line.startswith(want), line


def test_ac08_no_command_line_and_no_script_text_holds_sudo_e(kit: Kit):
    set_elevators(kit, {"sudo": ELEVATE})
    proc = parent_run(kit)
    assert proc.returncode == 0, output(proc)
    assert not [line for line in log_lines(kit) if re.match(r"(sudo|sudo-rs|sudo\.ws|pkexec) ", line)
                and re.search(r" -E\b", line)]
    assert not re.search(r"sudo\S* +(-\S+ +)*-E\b", SCRIPT.read_text(encoding="utf-8"))


def test_ac08_the_sudoers_check_uses_visudo_ws_when_visudo_is_missing(kit: Kit):
    kit.bodies.pop("visudo")
    kit.bodies["visudo.ws"] = "exit 0"
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    assert any(line.startswith("visudo.ws -cf ") for line in log_lines(kit)), log_lines(kit)
    assert not any(line.startswith("visudo -cf ") for line in log_lines(kit))
    assert (kit.root / "etc" / "sudoers.d" / "fleet-agent").is_file()


def test_ac08_without_visudo_or_visudo_ws_admin_rights_fails_and_leaves_no_sudoers_file(kit: Kit):
    kit.bodies.pop("visudo")
    proc = kit.run()
    assert proc.returncode == 1, output(proc)
    assert status(kit.record(), "admin_rights")["status"] == "failed"
    assert not (kit.root / "etc" / "sudoers.d" / "fleet-agent").exists()


# ----------------------------------------------------------------------------------------------- AC-9

def test_ac09_no_launcher_and_no_guide_runs_the_script_with_sudo_bash():
    for name in ("Setup Linux.desktop", "Setup Mac.command", "README.md"):
        text = (USB / name).read_text(encoding="utf-8")
        assert not re.search(r"\bsudo\s+bash\b", text), f"{name} holds 'sudo bash'"


def test_ac09_each_launcher_runs_the_script_with_bash():
    linux = (USB / "Setup Linux.desktop").read_text(encoding="utf-8")
    mac = (USB / "Setup Mac.command").read_text(encoding="utf-8")
    assert 'bash "$f"' in linux and not re.search(r"\bsudo\b", linux)
    assert "bash ./setup-unix.sh" in mac and not re.search(r"^\s*sudo\b", mac, re.MULTILINE)


# ----------------------------------------------------------------------------------------------- AC-10 and AC-12
# The installers are stubs that place stub tools. The stub that stands in for runuser (Linux) and for sudo (macOS)
# runs the Account's command, in the environment of the call and nothing else, so an installer writes to the
# Account's home and the tests see where each tool landed. /opt/homebrew and /usr/local are put under FLEET_ROOT.

VERSIONS = {"git": "git version 2.51.0", "python3": "Python 3.13.7", "pwsh": "PowerShell 7.5.4", "uv": "uv 0.9.1",
            "uvx": "uvx 0.9.1", "claude": "2.0.1 (Claude Code)", "codex": "codex-cli 0.5.0"}
URL_UV = "https://astral.sh/uv/install.sh"
URL_CLAUDE = "https://claude.ai/install.sh"
URL_CODEX = "https://chatgpt.com/codex/install.sh"
URL_BREW = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
URL_PWSH_LATEST = "https://github.com/PowerShell/PowerShell/releases/latest"
URL_PWSH_TAR = "https://github.com/PowerShell/PowerShell/releases/download/v7.5.4/powershell-7.5.4-linux-{arch}.tar.gz"
BLOCK_BEGIN = "# >>> fleet-usb tools >>>"
BLOCK_END = "# <<< fleet-usb tools <<<"

RUNNER = r'''case "$1" in -u) shift 2;; esac
[ "$1" != -H ] || shift
[ "$1" != -- ] || shift
[ "$1" = env ] || exit 0
shift 2
vars=()
while [ $# -gt 0 ]; do
  case "$1" in
    PATH=*)
      fixed=""; old=$IFS; IFS=:
      for d in ${1#PATH=}; do case "$d" in /opt/homebrew*|/usr/local*) d="$FLEET_ROOT$d";; esac; fixed="$fixed:$d"; done
      IFS=$old
      vars+=("PATH=$(cygpath -u "$STUB_BIN" 2>/dev/null || echo "$STUB_BIN")$fixed");;
    [A-Za-z_]*=*) vars+=("$1");;
    *) break;;
  esac
  shift
done
pass=(); while IFS= read -r line; do pass+=("$line"); done < <(env | grep -E '^(STUB_|FLEET_ROOT=)')
exec env -i "${vars[@]}" "${pass[@]}" "$@"'''

CURL = r'''out=""; url=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; -w) shift;; -*) ;; *) url="$1";; esac; shift; done
case "$url" in
  *astral.sh/uv/install.sh) f=uv.sh;;
  *claude.ai/install.sh) f=claude.sh;;
  *codex/install.sh) f=codex.sh;;
  *Homebrew/install/HEAD/install.sh) f=brew.sh;;
  *PowerShell/releases/latest) f=latest;;
  *powershell-*-linux-*.tar.gz) f=pwsh.tar.gz;;
  *) echo "curl stub: no payload for $url" >&2; exit 22;;
esac
[ -f "$STUB_PAYLOADS/$f" ] || exit 22
if [ "$f" = latest ] || [ -z "$out" ]; then cat "$STUB_PAYLOADS/$f"; else cp "$STUB_PAYLOADS/$f" "$out"; fi'''

BREW = r'''d=$(dirname "$0")
case "$1" in install)
  shift
  for f in "$@"; do
    case "$f" in powershell) t=pwsh;; python) t=python3;; git|uv) t=$f;; *) continue;; esac
    cp "$STUB_PAYLOADS/tools/$t" "$d/$t"; chmod +x "$d/$t"
  done;;
esac'''

SNAP = r'''case "$1" in install)
  mkdir -p "$FLEET_ROOT/snap/bin"; cp "$STUB_PAYLOADS/tools/pwsh" "$FLEET_ROOT/snap/bin/pwsh"; chmod +x "$FLEET_ROOT/snap/bin/pwsh";;
esac'''

DSCL = ('case "$2" in -search) echo "uid$5 UniqueID = ($5)";; '
        '*) case "$4" in UserShell) echo "UserShell: ${STUB_SHELL:-/bin/zsh}";; '
        '*) echo "NFSHomeDirectory: /Users/$STUB_ACCOUNT";; esac;; esac')


def msys(path: Path) -> str:
    """The path as Git bash writes it (/c/Users/...), so that a PATH list built from it has no colon in an entry."""
    posix = path.as_posix()
    if os.name == "nt" and re.match(r"^[A-Za-z]:/", posix):
        return f"/{posix[0].lower()}{posix[2:]}"
    return posix


def tool_stub(name: str) -> str:
    return stub_text(name, f'echo "{VERSIONS[name]}"')


def place(folder: str, *names: str) -> str:
    """Shell text that copies stub tools into folder."""
    lines = [f'mkdir -p "{folder}"']
    lines += [f'cp "$STUB_PAYLOADS/tools/{n}" "{folder}/{n}"; chmod +x "{folder}/{n}"' for n in names]
    return "\n".join(lines) + "\n"


def pwsh_tarball() -> bytes:
    data = tool_stub("pwsh").encode("utf-8")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("./pwsh")
        info.size, info.mode = len(data), 0o755
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class Prereq:
    """A Kit whose Account runner executes, with installer payloads that place stub tools, and msys-form paths."""

    def __init__(self, kit: Kit, macos: bool = False, machine: str = "x86_64"):
        self.kit, self.macos, self.machine = kit, macos, machine
        self.brew = "opt/homebrew" if machine == "arm64" else "usr/local"
        self.home = kit.root / ("Users" if macos else "home") / ACCOUNT
        self.home.mkdir(parents=True, exist_ok=True)
        self.payloads = kit.tmp / "payloads"
        (self.payloads / "tools").mkdir(parents=True)
        for name in VERSIONS:
            (self.payloads / "tools" / name).write_bytes(tool_stub(name).encode("utf-8"))
        (self.payloads / "tools" / "brew").write_bytes(stub_text("brew", BREW).encode("utf-8"))
        home_bin = '$HOME/.local/bin'
        scripts = {"uv.sh": place(home_bin, "uv", "uvx"), "claude.sh": place(home_bin, "claude"),
                   "codex.sh": place(home_bin, "codex"),
                   "brew.sh": place(f'$FLEET_ROOT/{self.brew}/bin', "brew")}
        for name, text in scripts.items():
            (self.payloads / name).write_bytes(text.encode("utf-8"))
        (self.payloads / "latest").write_text("https://github.com/PowerShell/PowerShell/releases/tag/v7.5.4",
                                              encoding="ascii")
        (self.payloads / "pwsh.tar.gz").write_bytes(pwsh_tarball())
        kit.base_path = "/usr/bin:/bin:/usr/sbin:/sbin"
        kit.bodies["sudo" if macos else "runuser"] = RUNNER
        kit.bodies["curl"] = CURL
        if macos:
            kit.bodies["dscl"] = DSCL
        else:
            # What apt installs is on the stub PATH from the start.
            kit.bodies["git"] = f'echo "{VERSIONS["git"]}"'
            kit.bodies["python3"] = f'echo "{VERSIONS["python3"]}"'

    def run(self, **extra: str) -> subprocess.CompletedProcess:
        env = {"FLEET_ROOT": msys(self.kit.root), "STUB_PAYLOADS": msys(self.payloads),
               "STUB_MACHINE": self.machine, "MSYS": "winsymlinks:nativestrict"}
        if self.macos:
            env["STUB_UNAME"] = "Darwin"
        env.update(extra)
        return self.kit.run(**env)

    @property
    def home_bin(self) -> Path:
        return self.home / ".local" / "bin"

    @property
    def local_bin(self) -> Path:
        return self.kit.root / "usr" / "local" / "bin"


@pytest.fixture
def linux(kit: Kit) -> Prereq:
    return Prereq(kit)


@pytest.fixture
def mac(kit: Kit) -> Prereq:
    return Prereq(kit, macos=True)


def lines_with(kit: Kit, text: str) -> list[str]:
    return [line for line in log_lines(kit) if text in line]


def account_prefix(prereq: Prereq) -> str:
    """The start of every logged Account command: the elevator, the account, then env -i and the whole environment."""
    home = f"{msys(prereq.kit.root)}/{'Users' if prereq.macos else 'home'}/{ACCOUNT}"
    elevator = f"sudo -u {ACCOUNT} -H" if prereq.macos else f"runuser -u {ACCOUNT} --"
    brew = "" if not prereq.macos else f"/{prereq.brew}/bin:/{prereq.brew}/sbin:"
    return (f"{elevator} env -i HOME={home} USER={ACCOUNT} LOGNAME={ACCOUNT} "
            f"PATH={home}/.local/bin:{home}/.cargo/bin:{brew}{ACCOUNT_PATH_TAIL}")


def run_shell(command: str) -> subprocess.CompletedProcess:
    return subprocess.run([need_bash(), "-c", command], capture_output=True, timeout=60)


# ----------------------------------------------------------------------------------------------- AC-10

def test_ac10_the_apt_branch_installs_the_package_list_with_the_lock_timeout(linux: Prereq):
    proc = linux.run()
    assert proc.returncode == 0, output(proc)
    lines = log_lines(linux.kit)
    assert "apt-get -o DPkg::Lock::Timeout=600 update -qq" in lines
    assert ("apt-get -o DPkg::Lock::Timeout=600 install -y -qq openssh-server curl git python3 python3-venv "
            "ca-certificates") in lines
    assert status(linux.kit.record(), "packages")["status"] == "ok"


def test_ac10_the_dnf_branch_installs_its_list(linux: Prereq):
    linux.kit.bodies.pop("apt-get")
    linux.kit.bodies["dnf"] = "exit 0"
    proc = linux.run()
    assert proc.returncode == 0, output(proc)
    lines = log_lines(linux.kit)
    assert "dnf install -y -q openssh-server curl git python3 ca-certificates" in lines
    assert not [line for line in lines if line.startswith("apt-get ")]
    assert status(linux.kit.record(), "packages")["status"] == "ok"


def test_ac10_pwsh_uses_snap_when_snap_is_present(linux: Prereq):
    linux.kit.bodies["snap"] = SNAP
    proc = linux.run()
    assert proc.returncode == 0, output(proc)
    assert "snap install powershell --classic" in log_lines(linux.kit)
    assert not lines_with(linux.kit, "PowerShell/releases")
    record = linux.kit.record()
    assert status(record, "pwsh")["status"] == "ok"
    assert record["tools"]["pwsh"] == VERSIONS["pwsh"]


def test_ac10_a_snap_pwsh_that_is_already_there_gets_the_link_an_ssh_command_finds(linux: Prereq):
    snap_pwsh = linux.kit.root / "snap" / "bin" / "pwsh"
    snap_pwsh.parent.mkdir(parents=True)
    shutil.copy(linux.payloads / "tools" / "pwsh", snap_pwsh)
    snap_pwsh.chmod(0o755)
    link = linux.local_bin / "pwsh"
    assert not link.exists() and not link.is_symlink()
    proc = linux.run()
    assert proc.returncode == 0, output(proc)
    assert "snap install powershell --classic" not in log_lines(linux.kit)
    assert link.is_symlink() and link.resolve() == snap_pwsh.resolve(), "/usr/local/bin/pwsh must lead to the snap pwsh"
    assert status(linux.kit.record(), "pwsh")["status"] == "ok"


@pytest.mark.parametrize("machine, arch", [("x86_64", "x64"), ("aarch64", "arm64")])
def test_ac10_pwsh_uses_the_tarball_when_there_is_no_snap(kit: Kit, machine: str, arch: str):
    linux = Prereq(kit, machine=machine)
    proc = linux.run()
    assert proc.returncode == 0, output(proc)
    url = URL_PWSH_TAR.format(arch=arch)
    assert [line for line in log_lines(kit) if line.startswith("curl ") and line.endswith(url)], log_lines(kit)
    target = kit.root / "opt" / "microsoft" / "powershell" / "7" / "pwsh"
    link = linux.local_bin / "pwsh"
    assert target.is_file() and link.is_symlink() and link.resolve() == target.resolve()
    record = kit.record()
    assert status(record, "pwsh")["status"] == "ok" and record["tools"]["pwsh"] == VERSIONS["pwsh"]


def test_ac10_a_failed_snap_install_falls_back_to_the_tarball(linux: Prereq):
    linux.kit.bodies["snap"] = "exit 1"
    proc = linux.run()
    assert proc.returncode == 0, output(proc)
    lines = log_lines(linux.kit)
    assert "snap install powershell --classic" in lines
    assert [line for line in lines if line.endswith(URL_PWSH_TAR.format(arch="x64"))]
    assert status(linux.kit.record(), "pwsh")["status"] == "ok"


def test_ac10_a_failed_tarball_ends_pwsh_failed_and_uv_still_runs(linux: Prereq):
    (linux.payloads / "pwsh.tar.gz").unlink()
    proc = linux.run()
    assert proc.returncode == 1, output(proc)
    record = linux.kit.record()
    assert status(record, "pwsh")["status"] == "failed"
    assert status(record, "uv")["status"] == "ok" and (linux.home_bin / "uv").is_file()
    assert "pwsh" not in record["tools"]


def test_ac10_uv_claude_and_codex_run_as_the_account_in_the_account_environment(linux: Prereq):
    proc = linux.run()
    assert proc.returncode == 0, output(proc)
    for url in (URL_UV, URL_CLAUDE, URL_CODEX):
        runs = [line for line in lines_with(linux.kit, url) if line.startswith("runuser ")]
        assert len(runs) == 1, runs
        assert runs[0].startswith(account_prefix(linux) + " "), runs[0]
    for tool in ("uv", "claude", "codex"):
        assert (linux.home_bin / tool).is_file(), tool


def test_ac10_tools_installed_only_under_local_bin_are_found_and_their_versions_recorded(linux: Prereq):
    proc = linux.run()
    assert proc.returncode == 0, output(proc)
    record = linux.kit.record()
    assert record["tools"] == {"git": VERSIONS["git"], "python": VERSIONS["python3"], "pwsh": VERSIONS["pwsh"],
                               "uv": VERSIONS["uv"], "claude": VERSIONS["claude"], "codex": VERSIONS["codex"]}
    fleet_usb.read_record(linux.kit.record_path())


def test_ac10_a_tool_that_cannot_be_installed_has_no_tools_key(linux: Prereq):
    (linux.payloads / "codex.sh").unlink()
    proc = linux.run()
    assert proc.returncode == 1, output(proc)
    record = linux.kit.record()
    assert status(record, "codex")["status"] == "failed"
    assert "codex" not in record["tools"] and record["tools"]["claude"] == VERSIONS["claude"]


def test_ac10_tool_links_make_usr_local_bin_links_and_a_rerun_leaves_them_as_they_are(linux: Prereq):
    proc = linux.run()
    assert proc.returncode == 0, output(proc)
    for tool in ("claude", "codex", "uv", "uvx"):
        link = linux.local_bin / tool
        assert link.is_symlink() and link.resolve() == (linux.home_bin / tool).resolve(), tool
    assert (linux.local_bin / "pwsh").is_symlink()
    found = run_shell(f'env -i PATH="{msys(linux.local_bin)}:/usr/bin:/bin" bash -c "command -v claude codex uv pwsh"')
    paths = found.stdout.decode("utf-8", errors="replace").split()
    assert [p.rsplit("/", 1)[-1] for p in paths] == ["claude", "codex", "uv", "pwsh"], found.stderr
    before = {t: (os.readlink(linux.local_bin / t), (linux.local_bin / t).lstat().st_mtime_ns)
              for t in ("claude", "codex", "uv", "uvx", "pwsh")}
    again = linux.run()
    assert again.returncode == 0, output(again)
    after = {t: (os.readlink(linux.local_bin / t), (linux.local_bin / t).lstat().st_mtime_ns) for t in before}
    assert after == before
    assert status(linux.kit.record(), "tool_links")["status"] == "ok"


def test_ac10_an_existing_file_of_another_target_at_a_link_path_is_left_alone_and_named(linux: Prereq):
    linux.home_bin.mkdir(parents=True)
    (linux.home_bin / "uv").write_bytes((linux.payloads / "tools" / "uv").read_bytes())
    (linux.home_bin / "uv").chmod(0o755)
    foreign = linux.local_bin / "uv"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"#!/bin/bash\necho mine\n")
    proc = linux.run()
    assert proc.returncode == 0, output(proc)
    assert foreign.read_bytes() == b"#!/bin/bash\necho mine\n" and not foreign.is_symlink()
    step = status(linux.kit.record(), "tool_links")
    assert step["status"] == "ok" and "/usr/local/bin/uv" in step["detail"], step
    assert (linux.local_bin / "claude").is_symlink()


# ----------------------------------------------------------------------------------------------- AC-12

def as_account(kit: Kit, command: str) -> None:
    """Every logged command that starts with command ran as a child of an Account line, never as the caller."""
    lines = log_lines(kit)
    hits = [i for i, line in enumerate(lines) if line.startswith(command)]
    assert hits, f"nothing logged starts with {command!r}: {lines}"
    for i in hits:
        assert lines[i - 1].startswith(f"sudo -u {ACCOUNT} -H env -i ") and lines[i - 1].endswith(" " + lines[i]), \
            (lines[i - 1], lines[i])


def test_ac12_the_order_is_admin_rights_homebrew_pwsh(mac: Prereq):
    mac.run()
    record = mac.kit.record()
    order = ids(record)
    assert order.index("admin_rights") < order.index("homebrew") < order.index("pwsh"), order
    assert in_step_order(record)


@pytest.mark.parametrize("machine", ["arm64", "x86_64"])
def test_ac12_homebrew_runs_as_the_account_with_a_noninteractive_installer(kit: Kit, machine: str):
    mac = Prereq(kit, macos=True, machine=machine)
    mac.run()
    installer = [line for line in lines_with(kit, URL_BREW) if not line.startswith("curl ")]
    assert len(installer) == 1, installer
    assert installer[0].startswith(account_prefix(mac) + " "), installer[0]
    assert " NONINTERACTIVE=1 " in installer[0]
    assert (kit.root / mac.brew / "bin" / "brew").is_file()
    assert status(kit.record(), "homebrew")["status"] == "ok"
    as_account(kit, "brew install")


@pytest.mark.parametrize("machine", ["arm64", "x86_64"])
def test_ac12_pwsh_runs_brew_install_powershell_and_is_found_in_the_same_run(kit: Kit, machine: str):
    mac = Prereq(kit, macos=True, machine=machine)
    mac.run()
    lines = log_lines(kit)
    assert "brew install powershell" in lines and "brew install git python uv" in lines
    assert not [line for line in lines if "--cask" in line]
    assert (kit.root / mac.brew / "bin" / "pwsh").is_file()
    record = kit.record()
    assert status(record, "pwsh")["status"] == "ok"
    assert record["tools"]["pwsh"] == VERSIONS["pwsh"] and record["tools"]["uv"] == VERSIONS["uv"]


def test_ac12_a_rerun_does_not_run_the_homebrew_installer_again(mac: Prereq):
    mac.run()
    again = mac.run()
    assert [line for line in lines_with(mac.kit, URL_BREW) if line.startswith("sudo ")] != []
    assert len([line for line in lines_with(mac.kit, URL_BREW) if line.startswith("sudo ")]) == 1, output(again)
    assert status(mac.kit.record(), "homebrew")["status"] == "ok"


def test_ac12_pwsh_is_skipped_with_needs_homebrew_when_homebrew_failed(mac: Prereq):
    (mac.payloads / "brew.sh").unlink()
    mac.run()
    record = mac.kit.record()
    assert status(record, "homebrew")["status"] == "failed"
    pwsh = status(record, "pwsh")
    assert pwsh["status"] == "skipped" and pwsh["detail"] == "needs homebrew", pwsh
    assert status(record, "uv")["status"] == "ok" and (mac.home_bin / "uv").is_file()


def test_ac12_tool_links_writes_the_zshenv_block_once_over_two_runs(mac: Prereq):
    zshenv = mac.home / ".zshenv"
    zshenv.write_text("export KEEP=1\n", encoding="utf-8", newline="\n")
    mac.run()
    mac.run()
    text = zshenv.read_text(encoding="utf-8")
    assert text.startswith("export KEEP=1\n")
    assert text.count(BLOCK_BEGIN) == 1 and text.count(BLOCK_END) == 1, text
    assert status(mac.kit.record(), "tool_links")["status"] == "ok"


def test_ac12_the_zshenv_block_is_posix_sh_and_finds_all_four_tools(mac: Prereq):
    mac.run()
    zshenv = mac.home / ".zshenv"
    block = zshenv.read_text(encoding="utf-8")
    assert "[[" not in block and "source " not in block
    syntax = run_shell(f'sh -n "{msys(zshenv)}"')
    assert syntax.returncode == 0, syntax.stderr
    found = run_shell(f"env -i HOME={msys(mac.home)} PATH=/usr/bin:/bin:/usr/sbin:/sbin "
                      f"bash -c '. {msys(zshenv)}; command -v pwsh uv claude codex'")
    names = [p.rsplit("/", 1)[-1] for p in found.stdout.decode("utf-8", errors="replace").split()]
    assert names == ["pwsh", "uv", "claude", "codex"], (found.stdout, found.stderr)


def test_ac12_a_login_shell_other_than_zsh_ends_tool_links_failed(mac: Prereq):
    mac.run(STUB_SHELL="/bin/bash")
    step = status(mac.kit.record(), "tool_links")
    assert step["status"] == "failed" and "zsh" in step["detail"], step
    assert not (mac.home / ".zshenv").exists()


# ---------------------------------------------------------------------------------------------- AC-13

TOKEN_NAME = "fleet_usb_token"
TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{32,64}\Z")
GIVEN_URLS = ["http://192.0.2.50:8771", "http://hub.example.test:9000"]


def addrinfo(*addresses: str):
    """A socket.getaddrinfo stand-in that answers with these IPv4 addresses, in this order."""
    def fake(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0)) for address in addresses]
    return fake


class Prep:
    """fleet_usb.main(['prepare', ...]) with a temp ~/.ssh (the hub's admin key is made by ssh-keygen)."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
        self.ssh = tmp_path / "home" / ".ssh"
        self.ssh.mkdir(parents=True)
        self.drive = tmp_path / "drive"
        self.capsys = capsys
        monkeypatch.setattr(fleet_usb, "ssh_dir", lambda: self.ssh)

    def prepare(self, *args: str) -> tuple[int, str]:
        code = fleet_usb.main(["prepare", str(self.drive), *args])
        captured = self.capsys.readouterr()
        return code, captured.out + captured.err

    @property
    def token_file(self) -> Path:
        return self.ssh / TOKEN_NAME

    def hub_lines(self) -> list[str]:
        raw = (self.drive / "hub.txt").read_bytes()
        assert b"\r" not in raw and raw.endswith(b"\n"), raw
        return raw.decode("ascii").splitlines()

    def rustdesk_lines(self) -> list[str]:
        raw = (self.drive / "rustdesk.txt").read_bytes()
        assert b"\r" not in raw and raw.endswith(b"\n"), raw
        return raw.decode("ascii").splitlines()


@pytest.fixture
def prep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> Prep:
    return Prep(tmp_path, monkeypatch, capsys)


def test_ac13_prepare_makes_the_token_file_and_hub_txt_with_the_given_urls(prep: Prep, monkeypatch):
    def no_lookup(*args, **kwargs):
        raise AssertionError("the hub's addresses are looked up although --hub-url was given")
    monkeypatch.setattr(fleet_usb.socket, "getaddrinfo", no_lookup)
    code, out = prep.prepare("--hub-url", GIVEN_URLS[0], "--hub-url", GIVEN_URLS[1] + "/")
    assert code == 0, out
    token = prep.token_file.read_text(encoding="ascii").strip()
    assert TOKEN_SHAPE.match(token), "the token file does not hold a 32 to 64 character token"
    if os.name != "nt":
        assert prep.token_file.stat().st_mode & 0o777 == 0o600
    assert prep.hub_lines() == [f"url={GIVEN_URLS[0]}", f"url={GIVEN_URLS[1]}", f"token={token}"]
    assert all(url in out for url in GIVEN_URLS), out
    assert token not in out, "prepare printed the token"


def test_ac13_the_computed_urls_skip_loopback_and_link_local_addresses_and_keep_order(prep: Prep, monkeypatch):
    monkeypatch.setattr(fleet_usb.socket, "getaddrinfo",
                        addrinfo("127.0.0.1", "192.0.2.10", "169.254.7.7", "198.51.100.7", "192.0.2.10", "127.0.1.1"))
    code, out = prep.prepare()
    assert code == 0, out
    token = prep.token_file.read_text(encoding="ascii").strip()
    assert prep.hub_lines() == ["url=http://192.0.2.10:8771", "url=http://198.51.100.7:8771", f"token={token}"]
    assert "http://192.0.2.10:8771" in out and "http://198.51.100.7:8771" in out and token not in out


def test_ac13_with_no_usable_address_hub_txt_holds_only_the_token_and_the_run_says_so(prep: Prep, monkeypatch):
    monkeypatch.setattr(fleet_usb.socket, "getaddrinfo", addrinfo("127.0.0.1", "169.254.7.7"))
    code, out = prep.prepare()
    assert code == 0, out
    token = prep.token_file.read_text(encoding="ascii").strip()
    assert prep.hub_lines() == [f"token={token}"]
    assert "--hub-url" in out, out


def test_ac13_a_second_prepare_keeps_the_token(prep: Prep, monkeypatch):
    monkeypatch.setattr(fleet_usb.socket, "getaddrinfo", addrinfo("192.0.2.10"))
    prep.prepare()
    first = prep.token_file.read_bytes()
    first_lines = prep.hub_lines()
    code, out = prep.prepare("--hub-url", GIVEN_URLS[0])
    assert code == 0, out
    assert prep.token_file.read_bytes() == first
    assert prep.hub_lines() == [f"url={GIVEN_URLS[0]}", first_lines[-1]]


def test_ac13_a_token_file_that_holds_no_token_is_refused_and_left_as_it_is(prep: Prep):
    prep.token_file.write_text("not a token\n", encoding="ascii")
    with pytest.raises(SystemExit) as stop:
        fleet_usb.main(["prepare", str(prep.drive), "--hub-url", GIVEN_URLS[0]])
    assert TOKEN_NAME in str(stop.value)
    assert prep.token_file.read_text(encoding="ascii") == "not a token\n"
    assert not (prep.drive / "hub.txt").exists()


@pytest.mark.parametrize("url", ["ftp://192.0.2.50:8771", "192.0.2.50:8771", "http://192.0.2.50:8771/ x",
                                 "http://192.0.2.50\nurl=http://evil.test", "http://"])
def test_ac13_a_hub_url_that_is_not_an_http_url_is_refused(prep: Prep, url: str):
    with pytest.raises(SystemExit) as stop:
        fleet_usb.main(["prepare", str(prep.drive), "--hub-url", url])
    assert "--hub-url" in str(stop.value)
    assert not (prep.drive / "hub.txt").exists()
    assert not prep.token_file.exists()


# ---------------------------------------------------------------------------------------------- AC-14

RECEIVE_TOKEN = "fleet-test_token-0123456789ABCDEFabcdef"
ROUTE = "/v1/usb-record"
OTHER = "lab-mini08"


class Receiver:
    """fleet_usb.receive on an ephemeral loopback port in a thread, with the hub's token in the temp ~/.ssh."""

    def __init__(self, hub: Hub, count: int | None = 1, timeout: float = 30.0):
        self.hub, self.count, self.timeout = hub, count, timeout
        self.code: int | None = None
        self.error: BaseException | None = None
        self.port = 0
        (hub.ssh / TOKEN_NAME).write_text(RECEIVE_TOKEN + "\n", encoding="ascii")
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        try:
            self.code = fleet_usb.receive(self.hub.folder, 0, "127.0.0.1", self.count, self.timeout, self.listening)
        except BaseException as e:  # reported by start() or finish(), never lost in the thread
            self.error = e

    def listening(self, port: int) -> None:
        self.port = port

    def start(self) -> "Receiver":
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.port:
            assert self.error is None, f"receive failed: {self.error!r}"
            assert time.monotonic() < deadline, "receive did not start listening in 10 s"
            time.sleep(0.02)
        return self

    def send(self, body: bytes, token: str | None = RECEIVE_TOKEN, path: str = ROUTE, method: str = "POST",
             drop_length: bool = False) -> tuple[int, str]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            conn.putrequest(method, path)
            if token is not None:
                conn.putheader("X-Fleet-Token", token)
            conn.putheader("Content-Type", "application/json")
            if not drop_length:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(None if drop_length else body)
            answer = conn.getresponse()
            return answer.status, answer.read().decode("utf-8", errors="replace")
        finally:
            conn.close()

    def send_record(self, record: dict, **extra) -> tuple[int, str]:
        return self.send(json.dumps(record).encode("utf-8"), **extra)

    def finish(self) -> int:
        """Wait for the receiver to stop on its own (count or timeout) and return its exit code."""
        self.thread.join(30)
        assert not self.thread.is_alive(), "receive did not stop"
        assert self.error is None, f"receive failed: {self.error!r}"
        assert self.code is not None
        return self.code

    def members(self) -> list[str]:
        return sorted(p.name for p in (self.hub.folder / "members").iterdir())


def stop_with_a_record(rx: Receiver) -> None:
    """End a one-record receiver with a valid record from another machine."""
    status, body = rx.send_record(v2(name=OTHER))
    assert status == 200, body


def test_ac14_a_valid_record_gets_200_a_file_and_a_summary_line_with_its_run_id(hub: Hub, capsys):
    rx = Receiver(hub).start()
    record = v2()
    status, body = rx.send_record(record)
    assert status == 200, body
    assert rx.finish() == 0
    assert rx.members() == ["lab-mini07.json"]
    raw = (hub.folder / "members" / "lab-mini07.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8")) == record
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    summary = [line for line in lines if "run_id=" in line]
    assert len(summary) == 1, lines
    for part in ("lab-mini07", "linux", "ok", "123456789", "run_id=abcd1234efgh5678"):
        assert part in summary[0], summary[0]
    assert lines[-1] == "received 1"
    assert RECEIVE_TOKEN not in captured.out + captured.err


def test_ac14_a_failed_run_is_summarised_with_its_failed_step_ids(hub: Hub, capsys):
    rx = Receiver(hub).start()
    status, body = rx.send_record(failed_host_key("lab-mini09"))
    assert status == 200, body
    assert rx.finish() == 0
    summary = [line for line in capsys.readouterr().out.splitlines() if "lab-mini09" in line]
    assert len(summary) == 1 and "failed: ssh_server, host_key" in summary[0] and "run_id=" in summary[0], summary


@pytest.mark.parametrize("token", [None, "", "wrong-token", RECEIVE_TOKEN + "x", RECEIVE_TOKEN[:-1]])
def test_ac14_a_missing_or_wrong_token_gets_403_and_writes_nothing(hub: Hub, capsys, token: str | None):
    rx = Receiver(hub).start()
    before = rx.members()
    status, body = rx.send_record(v2(), token=token)
    assert status == 403, body
    assert rx.members() == before == []
    stop_with_a_record(rx)
    assert rx.finish() == 0
    captured = capsys.readouterr()
    assert "403" in captured.err
    assert RECEIVE_TOKEN not in captured.out + captured.err


def test_ac14_a_body_of_70000_bytes_gets_413_and_writes_nothing(hub: Hub):
    rx = Receiver(hub).start()
    status, body = rx.send(b"x" * 70_000)
    assert status == 413, body
    assert rx.members() == []
    stop_with_a_record(rx)
    assert rx.finish() == 0


def test_ac14_a_request_with_no_content_length_gets_413_and_writes_nothing(hub: Hub):
    rx = Receiver(hub).start()
    status, body = rx.send(b"", drop_length=True)
    assert status == 413, body
    assert rx.members() == []
    stop_with_a_record(rx)
    assert rx.finish() == 0


def test_ac14_a_body_of_exactly_65536_bytes_is_read_and_refused_as_a_record_not_as_too_large(hub: Hub):
    rx = Receiver(hub).start()
    status, body = rx.send(b" " * 65_536)
    assert status == 422, body
    assert rx.members() == []
    stop_with_a_record(rx)
    assert rx.finish() == 0


RECEIVE_REFUSED = {**REFUSED, "a v1 record": V1, "a name that climbs out of the folder": v2(name="../evil"),
                   "a name with a slash": v2(name="a/b"), "a JSON list": [1, 2]}


@pytest.mark.parametrize("case", list(RECEIVE_REFUSED))
def test_ac14_a_refused_record_gets_422_with_the_reason_and_writes_nothing(hub: Hub, case: str):
    rx = Receiver(hub).start()
    status, body = rx.send_record(RECEIVE_REFUSED[case])
    assert status == 422, body
    assert json.loads(body)["error"], body
    assert rx.members() == []
    assert not list(hub.folder.parent.glob("evil*")) and not list(hub.folder.glob("evil*"))
    stop_with_a_record(rx)
    assert rx.finish() == 0
    assert rx.members() == [f"{OTHER}.json"]


def test_ac14_a_body_that_is_not_json_gets_422_and_writes_nothing(hub: Hub):
    rx = Receiver(hub).start()
    status, body = rx.send(b"\xff\xfe not json")
    assert status == 422, body
    assert rx.members() == []
    stop_with_a_record(rx)
    assert rx.finish() == 0


def test_ac14_a_record_that_cannot_be_stored_gets_500_and_leaves_no_temp_file(hub: Hub, monkeypatch):
    def locked(src, dst):
        raise PermissionError("locked by another process")
    rx = Receiver(hub).start()
    with monkeypatch.context() as patch:
        patch.setattr(fleet_usb.os, "replace", locked)
        status, body = rx.send_record(v2())
    assert status == 500, body
    assert "locked" in json.loads(body)["error"], body
    assert rx.members() == []
    stop_with_a_record(rx)
    assert rx.finish() == 0
    assert rx.members() == [f"{OTHER}.json"]


@pytest.mark.parametrize("method, path", [("GET", "/"), ("GET", ROUTE), ("POST", "/"), ("POST", ROUTE + "/x"),
                                          ("POST", "/v1/other"), ("PUT", ROUTE), ("DELETE", ROUTE),
                                          ("HEAD", ROUTE), ("FETCH", ROUTE)])
def test_ac14_any_other_method_or_path_gets_404_and_writes_nothing(hub: Hub, method: str, path: str):
    rx = Receiver(hub).start()
    status, body = rx.send(json.dumps(v2()).encode("utf-8"), path=path, method=method)
    assert status == 404, body
    assert rx.members() == []
    stop_with_a_record(rx)
    assert rx.finish() == 0


def test_ac14_count_2_stops_after_two_names_and_prints_received_2(hub: Hub, capsys):
    rx = Receiver(hub, count=2).start()
    for name in ("lab-mini07", "lab-mini07", OTHER):
        status, body = rx.send_record(v2(name=name))
        assert status == 200, body
    assert rx.finish() == 0
    assert rx.members() == ["lab-mini07.json", f"{OTHER}.json"]
    assert capsys.readouterr().out.splitlines()[-1] == "received 2"


def test_ac14_timeout_1_with_no_record_prints_received_0_and_exits_1(hub: Hub, capsys):
    (hub.ssh / TOKEN_NAME).write_text(RECEIVE_TOKEN + "\n", encoding="ascii")
    started = time.monotonic()
    code = fleet_usb.main(["receive", str(hub.folder), "--port", "0", "--bind", "127.0.0.1", "--timeout", "1"])
    elapsed = time.monotonic() - started
    assert code == 1
    assert 0.9 <= elapsed < 10, elapsed
    assert capsys.readouterr().out.splitlines()[-1] == "received 0"


def test_ac14_receive_without_a_token_file_stops_and_names_prepare(hub: Hub):
    with pytest.raises(SystemExit) as stop:
        fleet_usb.receive(hub.folder, 0, "127.0.0.1", 1, 1.0)
    assert "prepare" in str(stop.value)


def test_ac14_the_import_command_reads_the_received_record_unchanged(hub: Hub, capsys):
    rx = Receiver(hub).start()
    status, body = rx.send_record(v2())
    assert status == 200, body
    assert rx.finish() == 0
    capsys.readouterr()
    code = fleet_usb.main(["import", str(hub.folder), "--no-test"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "lab-mini07: ok, delivery none, ssh lab-mini07 -> lab@192.0.2.10, not tested" in out
    assert hub.pinned()["lab-mini07"]["host_key"] == v2()["host_key"]


# ----------------------------------------------------------------------------------------------- AC-15

SEND_TOKEN = "abcdefghij0123456789ABCDEFGHIJ_-"
SEND_URLS = ["http://192.0.2.1:8771", "http://192.0.2.2:8771", "http://192.0.2.3:8771"]
SEND_ROUTE = "/v1/usb-record"
PENDING = {"status": "pending", "detail": ""}


def write_hub_file(kit: Kit, urls=SEND_URLS, token: str | None = SEND_TOKEN, extra=(), eol: str = "\n") -> None:
    """hub.txt as `prepare` writes it: the url lines, then the token line; `extra` lines go between them."""
    lines = [f"url={u}" for u in urls] + list(extra)
    if token is not None:
        lines.append(f"token={token}")
    (kit.drive / "hub.txt").write_bytes((eol.join(lines) + eol).encode("ascii"))


def send_stub(kit: Kit, answers: dict[str, tuple[str, int]], during: str = "") -> Path:
    """A curl that keeps every POST to the hub route as sends/<n>.args, .body and .drive (the drive copy as it was at
    the call). `answers` maps a URL to (the HTTP code it prints, its exit code); a URL it does not name fails with 7.
    `during` is shell run while the POST is in flight. A call to any other route does nothing."""
    folder = kit.tmp / "sends"
    folder.mkdir(exist_ok=True)
    cases = "".join(f'"{url}") printf "%s" "{code}"; rc={rc};;\n' for url, (code, rc) in answers.items())
    kit.bodies["curl"] = (
        f'out="{folder.as_posix()}"; url=""; body=""; prev=""\n'
        'for a in "$@"; do case "$prev" in --data-binary) body="${a#@}";; esac; prev="$a"; url="$a"; done\n'
        'case "$url" in */v1/usb-record) ;; *) exit 0;; esac\n'
        'n=$(( $(cat "$out/count" 2>/dev/null || echo 0) + 1 )); echo $n > "$out/count"\n'
        'printf "%s\\n" "$*" > "$out/$n.args"\n'
        'cp "$body" "$out/$n.body"\n'
        f'cp "{kit.record_path().as_posix()}" "$out/$n.drive"\n'
        f"{during}\n"
        "rc=7\n"
        'case "${url%/v1/usb-record}" in\n'
        f"{cases}"
        '*) printf "000";;\n'
        "esac\n"
        "exit $rc")
    return folder


def sent_posts(kit: Kit) -> list[dict]:
    folder = kit.tmp / "sends"
    counter = folder / "count"
    count = int(counter.read_text(encoding="ascii")) if counter.exists() else 0
    return [{"args": (folder / f"{n}.args").read_text(encoding="utf-8").strip(),
             "body": json.loads((folder / f"{n}.body").read_text(encoding="utf-8")),
             "drive": json.loads((folder / f"{n}.drive").read_text(encoding="utf-8"))} for n in range(1, count + 1)]


def all_urls_answer(code: str, rc: int, urls=SEND_URLS) -> dict[str, tuple[str, int]]:
    return {url: (code, rc) for url in urls}


def test_ac15_each_url_is_tried_in_order_and_the_send_stops_at_the_first_200(kit: Kit):
    write_hub_file(kit)
    send_stub(kit, {SEND_URLS[0]: ("503", 0), SEND_URLS[1]: ("200", 0), SEND_URLS[2]: ("200", 0)})
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    posts = sent_posts(kit)
    assert len(posts) == 2, posts
    assert posts[0]["args"].endswith(SEND_URLS[0] + SEND_ROUTE), posts[0]["args"]
    assert posts[1]["args"].endswith(SEND_URLS[1] + SEND_ROUTE), posts[1]["args"]
    assert kit.record()["delivery"] == {"status": "sent", "detail": SEND_URLS[1]}
    fleet_usb.read_record(kit.record_path())


def test_ac15_the_request_carries_the_token_header_the_timeouts_and_the_record_file(kit: Kit):
    write_hub_file(kit)
    send_stub(kit, {SEND_URLS[0]: ("200", 0)})
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    args = sent_posts(kit)[0]["args"]
    assert f"X-Fleet-Token: {SEND_TOKEN}" in args, args
    assert "--connect-timeout 5" in args and "--max-time 20" in args, args
    assert "--data-binary @" in args, args
    assert "-X POST" in args, args
    everything = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    assert SEND_TOKEN not in everything, "the script printed the token"


def test_ac15_the_drive_copy_is_pending_before_the_first_post_and_the_body_has_delivery_null(kit: Kit):
    write_hub_file(kit)
    send_stub(kit, all_urls_answer("503", 0))
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    first = sent_posts(kit)[0]
    assert first["drive"]["delivery"] == PENDING, first["drive"]
    assert first["drive"]["final"] is True and first["drive"]["ok"] is True
    assert first["body"]["delivery"] is None
    # the body is the final record and nothing else changed
    assert first["body"] == {**first["drive"], "delivery": None}


def test_ac15_when_every_url_fails_the_copy_ends_failed_with_each_result(kit: Kit):
    write_hub_file(kit)
    send_stub(kit, {SEND_URLS[0]: ("503", 0), SEND_URLS[1]: ("000", 7), SEND_URLS[2]: ("403", 0)})
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    delivery = kit.record()["delivery"]
    assert delivery["status"] == "failed", delivery
    for result in (f"{SEND_URLS[0]} HTTP 503", f"{SEND_URLS[1]} curl exit 7", f"{SEND_URLS[2]} HTTP 403"):
        assert result in delivery["detail"], delivery
    assert len(sent_posts(kit)) == 3
    fleet_usb.read_record(kit.record_path())


def test_ac15_the_failed_detail_is_cut_to_300_characters(kit: Kit):
    urls = [f"http://192.0.2.{n}:8771" for n in range(1, 13)]
    write_hub_file(kit, urls=urls)
    send_stub(kit, all_urls_answer("503", 0, urls))
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    delivery = kit.record()["delivery"]
    assert delivery["status"] == "failed" and len(delivery["detail"]) == 300, delivery
    assert delivery["detail"].startswith(f"{urls[0]} HTTP 503; {urls[1]} HTTP 503")
    assert len(sent_posts(kit)) == 12
    fleet_usb.read_record(kit.record_path())


def test_ac15_with_no_hub_file_the_copy_is_failed_after_one_final_write_and_nothing_is_sent(kit: Kit):
    send_stub(kit, all_urls_answer("200", 0))
    finals = track_finals(kit)
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    assert kit.record()["delivery"] == {"status": "failed", "detail": "no hub.txt"}
    assert sent_posts(kit) == []
    assert final_writes(finals) == 1
    fleet_usb.read_record(kit.record_path())


def test_ac15_with_no_curl_the_copy_is_failed_with_no_curl(kit: Kit):
    write_hub_file(kit)
    del kit.bodies["curl"]
    finals = track_finals(kit)
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    assert kit.record()["delivery"] == {"status": "failed", "detail": "no curl"}
    assert final_writes(finals) == 1
    fleet_usb.read_record(kit.record_path())


@pytest.mark.parametrize("token", [None, "short", "a" * 31 + "!", "a" * 65], ids=["missing", "short", "bad-char", "too-long"])
def test_ac15_with_no_valid_token_line_the_copy_is_failed_and_nothing_is_sent(kit: Kit, token):
    write_hub_file(kit, token=token)
    send_stub(kit, all_urls_answer("200", 0))
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    assert kit.record()["delivery"] == {"status": "failed", "detail": "no valid token line in hub.txt"}
    assert sent_posts(kit) == []
    fleet_usb.read_record(kit.record_path())


def test_ac15_with_no_url_line_the_copy_is_failed_and_nothing_is_sent(kit: Kit):
    write_hub_file(kit, urls=[])
    send_stub(kit, all_urls_answer("200", 0))
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    assert kit.record()["delivery"] == {"status": "failed", "detail": "no url line in hub.txt"}
    assert sent_posts(kit) == []


def test_ac15_a_url_line_that_is_not_a_plain_http_url_is_ignored_and_hub_txt_is_never_evaluated(kit: Kit):
    marker = kit.tmp / "evaluated"
    touch = f'touch "{marker.as_posix()}"'
    urls = ["file:///etc/passwd", "http://192.0.2.1:8771/extra", f"http://192.0.2.1:8771;{touch}",
            f"http://$({touch})", SEND_URLS[1]]
    write_hub_file(kit, urls=urls, extra=[f"$({touch})", f"`{touch}`", f"; {touch}"])
    send_stub(kit, {SEND_URLS[1]: ("200", 0)})
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    assert not marker.exists(), "hub.txt was evaluated"
    posts = sent_posts(kit)
    assert len(posts) == 1 and posts[0]["args"].endswith(SEND_URLS[1] + SEND_ROUTE), posts
    assert kit.record()["delivery"] == {"status": "sent", "detail": SEND_URLS[1]}


def test_ac15_a_hub_file_with_windows_line_ends_is_read(kit: Kit):
    write_hub_file(kit, eol="\r\n")
    send_stub(kit, {SEND_URLS[0]: ("200", 0)})
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    assert kit.record()["delivery"] == {"status": "sent", "detail": SEND_URLS[0]}
    assert f"X-Fleet-Token: {SEND_TOKEN}" in sent_posts(kit)[0]["args"]


def test_ac15_an_offline_run_exits_0_and_its_drive_copy_validates_and_imports(kit: Kit, hub: Hub, capsys):
    write_hub_file(kit)
    send_stub(kit, all_urls_answer("000", 7))
    proc = kit.run()
    assert proc.returncode == 0, output(proc)
    record = kit.record()
    assert record["final"] is True and record["ok"] is True
    assert record["delivery"]["status"] == "failed" and len(sent_posts(kit)) == 3
    assert fleet_usb.read_record(kit.record_path())["ok"] is True
    shutil.copy(kit.record_path(), hub.folder / "members" / kit.record_path().name)
    capsys.readouterr()
    code = fleet_usb.main(["import", str(hub.folder), "--no-test"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "lab-mini07: ok, delivery failed," in out, out


def test_ac15_a_send_never_changes_the_exit_code_that_ok_gives(kit: Kit):
    write_hub_file(kit)
    kit.bodies["apt-get"] = "exit 100"
    send_stub(kit, {SEND_URLS[0]: ("200", 0)})
    proc = kit.run()
    assert proc.returncode == 1, output(proc)
    record = kit.record()
    assert record["ok"] is False and record["delivery"] == {"status": "sent", "detail": SEND_URLS[0]}


def test_ac15_a_sigterm_during_the_send_leaves_a_complete_copy_with_delivery_pending(kit: Kit):
    write_hub_file(kit)
    send_stub(kit, all_urls_answer("200", 0), during='kill -TERM "$FLEET_SETUP_PID"; sleep 3')
    proc = kit.run()
    assert proc.returncode != 0, output(proc)
    record = kit.record()
    assert record["final"] is True and record["ok"] is True
    assert record["delivery"] == PENDING
    assert len(sent_posts(kit)) == 1
    fleet_usb.read_record(kit.record_path())


def test_ac15_an_elevated_run_sends_once(kit: Kit):
    set_elevators(kit, {"sudo": ELEVATE})
    write_hub_file(kit)
    send_stub(kit, {SEND_URLS[0]: ("200", 0)})
    proc = parent_run(kit)
    assert proc.returncode == 0, output(proc)
    assert len(sent_posts(kit)) == 1
    assert kit.record()["delivery"] == {"status": "sent", "detail": SEND_URLS[0]}


def test_ac15_a_parent_that_finalizes_after_a_failed_elevation_sends_its_record(kit: Kit):
    set_elevators(kit, {})
    write_hub_file(kit)
    send_stub(kit, {SEND_URLS[0]: ("200", 0)})
    proc = parent_run(kit)
    assert proc.returncode == 1, output(proc)
    posts = sent_posts(kit)
    assert len(posts) == 1 and posts[0]["body"]["ok"] is False, posts
    assert kit.record()["delivery"] == {"status": "sent", "detail": SEND_URLS[0]}


# ---------------------------------------------------------------------------------------------- AC-16

RD_API = "https://api.github.com/repos/rustdesk/rustdesk/releases/latest"
RD_HOST = "hub.example.test"
RD_KEY = "Xq3b9mYtL2vKd8WcN1sPz7RfH4jGa6UeO0iT5yBnM2k="
RD_VERSION = "1.4.1"
RD_SAVED = "fleet_rustdesk.json"


def rd_download(version: str = RD_VERSION) -> str:
    return f"https://github.com/rustdesk/rustdesk/releases/download/{version}/"


def rd_names(version: str = RD_VERSION) -> tuple[list[str], list[str]]:
    """The six assets that the plan's pattern table wants, in table order, and names that no pattern wants."""
    wanted = [f"rustdesk-{version}-x86_64.msi", f"rustdesk-{version}-x86_64.deb", f"rustdesk-{version}-aarch64.deb",
              f"rustdesk-{version}-0.x86_64.rpm", f"rustdesk-{version}-x86_64.dmg", f"rustdesk-{version}-aarch64.dmg"]
    other = [f"rustdesk-{version}-x86_64.exe", f"rustdesk-{version}-0.aarch64.rpm", f"rustdesk-{version}-suse-0.x86_64.rpm",
             f"rustdesk-{version}-armv7-sciter.deb", f"rustdesk-{version}.sha256"]
    return wanted, other


def rd_body(name: str) -> bytes:
    return f"fake download of {name}".encode("ascii")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Net:
    """fleet_usb.fetch, replaced: the release answer and the download bytes, with a log of every URL asked for."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, version: str = RD_VERSION, skip: tuple[str, ...] = (),
                 changed: tuple[str, ...] = (), url_base: str | None = None, **top):
        wanted, other = rd_names(version)
        base = url_base or rd_download(version)
        self.data: dict[str, bytes] = {}
        assets = []
        for name in [*other, *wanted]:
            if any(name.endswith(suffix) for suffix in skip):
                continue
            self.data[name] = rd_body(name) + (b" changed" if name in changed else b"")
            assets.append({"name": name, "browser_download_url": base + name, "size": len(self.data[name]),
                           "digest": "sha256:" + sha(self.data[name])})
        self.release = {"tag_name": version, "name": f"RustDesk {version}", "prerelease": False, "draft": False,
                        "body": "notes", "assets": assets, **top}
        self.calls: list[str] = []
        self.fail: dict[str, Exception] = {}
        monkeypatch.setattr(fleet_usb, "fetch", self)

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if url in self.fail:
            raise self.fail[url]
        if url == RD_API:
            return json.dumps(self.release).encode("utf-8")
        for asset in self.release["assets"]:
            if asset["browser_download_url"] == url:
                return self.data[asset["name"]]
        raise AssertionError(f"fleet_usb asked for a URL that the release does not hold: {url}")


def rd_args(*extra: str) -> list[str]:
    return ["--hub-url", GIVEN_URLS[0], "--rustdesk-host", RD_HOST, "--rustdesk-key", RD_KEY, *extra]


def test_ac16_prepare_picks_the_six_assets_by_pattern_and_writes_the_rustdesk_file(prep: Prep, monkeypatch):
    net = Net(monkeypatch)
    code, out = prep.prepare(*rd_args())
    assert code == 0, out
    wanted, _ = rd_names()
    assert sorted(p.name for p in (prep.drive / "rustdesk").iterdir()) == sorted(wanted)
    for name in wanted:
        assert (prep.drive / "rustdesk" / name).read_bytes() == rd_body(name)
    assert prep.rustdesk_lines() == [f"version={RD_VERSION}", f"host={RD_HOST}", f"key={RD_KEY}",
                                     *[f"file={name} {sha(rd_body(name))}" for name in wanted]]
    assert net.calls == [RD_API, *[rd_download() + name for name in wanted]]
    assert json.loads((prep.ssh / RD_SAVED).read_text(encoding="utf-8")) == {"host": RD_HOST, "key": RD_KEY}


def test_ac16_a_tag_with_a_v_gives_the_version_without_it(prep: Prep, monkeypatch):
    Net(monkeypatch, tag_name=f"v{RD_VERSION}")
    code, out = prep.prepare(*rd_args())
    assert code == 0, out
    assert prep.rustdesk_lines()[0] == f"version={RD_VERSION}"


def test_ac16_a_later_prepare_without_the_options_reuses_the_saved_server_and_downloads_nothing_again(prep, monkeypatch):
    net = Net(monkeypatch)
    prep.prepare(*rd_args())
    first = prep.rustdesk_lines()
    net.calls.clear()
    code, out = prep.prepare("--hub-url", GIVEN_URLS[0])
    assert code == 0, out
    assert net.calls == [RD_API]
    assert prep.rustdesk_lines() == first


def test_ac16_an_asset_whose_sha256_changed_is_downloaded_again(prep: Prep, monkeypatch):
    Net(monkeypatch)
    prep.prepare(*rd_args())
    msi = rd_names()[0][0]
    net = Net(monkeypatch, changed=(msi,))
    code, out = prep.prepare("--hub-url", GIVEN_URLS[0])
    assert code == 0, out
    assert net.calls == [RD_API, rd_download() + msi]
    assert (prep.drive / "rustdesk" / msi).read_bytes() == rd_body(msi) + b" changed"
    assert f"file={msi} {sha(rd_body(msi) + b' changed')}" in prep.rustdesk_lines()


def test_ac16_a_drive_file_that_no_longer_matches_its_sha256_is_downloaded_again(prep: Prep, monkeypatch):
    net = Net(monkeypatch)
    prep.prepare(*rd_args())
    deb = rd_names()[0][1]
    (prep.drive / "rustdesk" / deb).write_bytes(b"cut short")
    net.calls.clear()
    code, out = prep.prepare("--hub-url", GIVEN_URLS[0])
    assert code == 0, out
    assert net.calls == [RD_API, rd_download() + deb]
    assert (prep.drive / "rustdesk" / deb).read_bytes() == rd_body(deb)


def test_ac16_with_no_server_prepare_writes_no_rustdesk_file_and_calls_no_network(prep: Prep, monkeypatch):
    def no_network(url: str) -> bytes:
        raise AssertionError(f"fleet_usb used the network with no RustDesk server configured: {url}")
    monkeypatch.setattr(fleet_usb, "fetch", no_network)
    code, out = prep.prepare("--hub-url", GIVEN_URLS[0])
    assert code == 0, out
    assert not (prep.drive / "rustdesk.txt").exists() and not (prep.drive / "rustdesk").exists()
    assert not (prep.ssh / RD_SAVED).exists()


def test_ac16_a_release_without_an_msi_asset_leaves_the_windows_line_out_and_still_writes_the_rest(prep, monkeypatch):
    Net(monkeypatch, skip=(".msi",))
    code, out = prep.prepare(*rd_args())
    assert code == 0, out
    wanted, _ = rd_names()
    assert sorted(p.name for p in (prep.drive / "rustdesk").iterdir()) == sorted(wanted[1:])
    assert prep.rustdesk_lines() == [f"version={RD_VERSION}", f"host={RD_HOST}", f"key={RD_KEY}",
                                     *[f"file={name} {sha(rd_body(name))}" for name in wanted[1:]]]
    assert "windows" in out.lower(), out


def test_ac16_the_key_can_come_from_a_file(prep: Prep, monkeypatch, tmp_path: Path):
    Net(monkeypatch)
    key_file = tmp_path / "id_ed25519.pub"
    key_file.write_text(RD_KEY + "\r\n", encoding="ascii", newline="")
    code, out = prep.prepare("--hub-url", GIVEN_URLS[0], "--rustdesk-host", RD_HOST, "--rustdesk-key-file", str(key_file))
    assert code == 0, out
    assert json.loads((prep.ssh / RD_SAVED).read_text(encoding="utf-8")) == {"host": RD_HOST, "key": RD_KEY}
    assert f"key={RD_KEY}" in prep.rustdesk_lines()


def test_ac16_a_new_host_alone_keeps_the_saved_key(prep: Prep, monkeypatch):
    Net(monkeypatch)
    prep.prepare(*rd_args())
    code, out = prep.prepare("--hub-url", GIVEN_URLS[0], "--rustdesk-host", "other.example.test")
    assert code == 0, out
    assert json.loads((prep.ssh / RD_SAVED).read_text(encoding="utf-8")) == {"host": "other.example.test", "key": RD_KEY}
    assert prep.rustdesk_lines()[1:3] == ["host=other.example.test", f"key={RD_KEY}"]


def test_ac16_a_key_and_a_key_file_together_are_refused(prep: Prep, tmp_path: Path):
    with pytest.raises(SystemExit) as stop:
        fleet_usb.main(["prepare", str(prep.drive), "--hub-url", GIVEN_URLS[0], "--rustdesk-host", RD_HOST,
                        "--rustdesk-key", RD_KEY, "--rustdesk-key-file", str(tmp_path / "k.pub")])
    assert stop.value.code == 2
    assert not prep.token_file.exists()


RD_REFUSED = {
    "a host with a space": ["--rustdesk-host", "hub example", "--rustdesk-key", RD_KEY],
    "a host with a comma": ["--rustdesk-host", "hub.example.test,key=x", "--rustdesk-key", RD_KEY],
    "an empty host": ["--rustdesk-host", "", "--rustdesk-key", RD_KEY],
    "a key that is too short": ["--rustdesk-host", RD_HOST, "--rustdesk-key", "abc"],
    "a key with a bad character": ["--rustdesk-host", RD_HOST, "--rustdesk-key", RD_KEY[:-1] + "!"],
    "a host and no key": ["--rustdesk-host", RD_HOST],
    "a key and no host": ["--rustdesk-key", RD_KEY],
    "a key file that is missing": ["--rustdesk-host", RD_HOST, "--rustdesk-key-file", "<missing>"],
}


@pytest.mark.parametrize("case", list(RD_REFUSED))
def test_ac16_a_bad_server_option_stops_prepare_before_it_writes_anything(prep: Prep, monkeypatch, tmp_path, case: str):
    def no_network(url: str) -> bytes:
        raise AssertionError(f"fleet_usb used the network after a refused option: {url}")
    monkeypatch.setattr(fleet_usb, "fetch", no_network)
    args = [str(tmp_path / "missing.pub") if a == "<missing>" else a for a in RD_REFUSED[case]]
    with pytest.raises(SystemExit) as stop:
        fleet_usb.main(["prepare", str(prep.drive), "--hub-url", GIVEN_URLS[0], *args])
    assert "--rustdesk" in str(stop.value), stop.value
    assert not prep.drive.exists() and not prep.token_file.exists() and not (prep.ssh / RD_SAVED).exists()


def test_ac16_a_saved_server_file_with_an_unknown_key_is_refused_and_left_as_it_is(prep: Prep, monkeypatch):
    monkeypatch.setattr(fleet_usb, "fetch", lambda url: pytest.fail(f"fetched {url}"))
    saved = prep.ssh / RD_SAVED
    saved.write_text(json.dumps({"host": RD_HOST, "key": RD_KEY, "extra": 1}), encoding="utf-8")
    before = saved.read_bytes()
    with pytest.raises(SystemExit) as stop:
        fleet_usb.main(["prepare", str(prep.drive), "--hub-url", GIVEN_URLS[0]])
    assert RD_SAVED in str(stop.value), stop.value
    assert saved.read_bytes() == before and not prep.token_file.exists()


RD_BAD_RELEASES = {
    "a prerelease": {"prerelease": True},
    "a tag that is not a version": {"tag_name": "nightly"},
    "a tag with four numbers": {"tag_name": "1.4.1.999"},
    "a download URL outside github.com": {"url_base": "https://downloads.example.test/rustdesk/"},
}


@pytest.mark.parametrize("case", list(RD_BAD_RELEASES))
def test_ac16_a_release_that_fails_its_checks_writes_no_rustdesk_file_and_the_rest_of_prepare_runs(prep, monkeypatch, case):
    net = Net(monkeypatch, **RD_BAD_RELEASES[case])
    code, out = prep.prepare(*rd_args())
    assert code == 1, out
    assert "rustdesk" in out.lower(), out
    assert not (prep.drive / "rustdesk.txt").exists()
    assert not list((prep.drive / "rustdesk").glob("*")), "an asset was downloaded from a release that failed its checks"
    assert net.calls == [RD_API]
    assert (prep.drive / "hub.txt").is_file() and (prep.drive / "hub.pub").is_file()
    assert (prep.ssh / RD_SAVED).is_file()


def test_ac16_a_release_that_cannot_be_read_removes_an_old_rustdesk_file_and_the_rest_of_prepare_runs(prep, monkeypatch):
    net = Net(monkeypatch)
    prep.prepare(*rd_args())
    assert (prep.drive / "rustdesk.txt").is_file()
    net.fail[RD_API] = OSError("offline")
    code, out = prep.prepare("--hub-url", GIVEN_URLS[0])
    assert code == 1, out
    assert not (prep.drive / "rustdesk.txt").exists()
    assert "offline" in out and (prep.drive / "hub.txt").is_file()


def test_ac16_a_download_that_fails_leaves_that_platform_out_and_the_rest_in(prep: Prep, monkeypatch):
    net = Net(monkeypatch)
    wanted, _ = rd_names()
    net.fail[rd_download() + wanted[2]] = OSError("connection reset")
    code, out = prep.prepare(*rd_args())
    assert code == 1, out
    assert wanted[2] in out and "connection reset" in out
    assert sorted(p.name for p in (prep.drive / "rustdesk").iterdir()) == sorted(wanted[:2] + wanted[3:])
    assert not any(wanted[2] in line for line in prep.rustdesk_lines())


def test_ac16_a_download_that_does_not_match_its_digest_is_not_kept(prep: Prep, monkeypatch):
    net = Net(monkeypatch)
    wanted, _ = rd_names()
    net.data[wanted[0]] = b"tampered"
    code, out = prep.prepare(*rd_args())
    assert code == 1, out
    assert wanted[0] in out
    assert not (prep.drive / "rustdesk" / wanted[0]).exists()
    assert not any(wanted[0] in line for line in prep.rustdesk_lines())


# ---------------------------------------------------------------------------------------------- AC-19

PASSWORD_FILE = "lab-mini07-rustdesk-password.txt"
PASSWORD_SHAPE = re.compile(r"[A-Za-z0-9_-]{24}\Z")
REMOTE_BINARY = {"linux": "rustdesk", "macos": "/Applications/RustDesk.app/Contents/MacOS/RustDesk",
                 "windows": r"C:\Program Files\RustDesk\rustdesk.exe"}


def run_import(hub: Hub) -> tuple[int, str]:
    code = fleet_usb.import_records(hub.folder, test=True)
    captured = hub.capsys.readouterr()
    return code, captured.out + captured.err


def password_file(hub: Hub) -> Path:
    return hub.ssh / PASSWORD_FILE


def files_other_than_the_password_file(hub: Hub) -> list[Path]:
    return [p for root in (hub.folder, hub.ssh) for p in root.rglob("*") if p.is_file() and p != password_file(hub)]


def test_ac19_import_makes_the_password_file_once_and_sends_the_password_on_standard_input(hub: Hub):
    hub.put(v2())
    code, out = run_import(hub)
    assert code == 0, out
    path = password_file(hub)
    raw = path.read_text(encoding="ascii")
    password = raw.strip()
    assert raw == password + "\n" and PASSWORD_SHAPE.match(password), "the file is not one password and a line end"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    assert len(hub.remote.calls) == 1
    call = hub.remote.calls[0]
    assert call["name"] == "lab-mini07" and call["stdin"] == password + "\n"
    assert f"rustdesk: id 123456789, password in {path}" in out, out


def test_ac19_a_second_import_reuses_the_password_file(hub: Hub):
    hub.put(v2())
    run_import(hub)
    first = password_file(hub).read_bytes()
    code, out = run_import(hub)
    assert code == 0, out
    assert password_file(hub).read_bytes() == first
    assert [call["stdin"] for call in hub.remote.calls] == [first.decode("ascii")] * 2


def test_ac19_the_password_text_appears_in_no_output_no_argument_and_no_other_file(hub: Hub):
    hub.put(v2())
    code, out = run_import(hub)
    assert code == 0, out
    password = password_file(hub).read_text(encoding="ascii").strip()
    assert password not in out
    for call in hub.remote.calls:
        assert password not in call["name"] and password not in call["command"], call
    for path in files_other_than_the_password_file(hub):
        assert password.encode("ascii") not in path.read_bytes(), path


@pytest.mark.parametrize("case", ["a record without rustdesk_id", "import with --no-test",
                                  "an ssh test without full access", "a v1 record"])
def test_ac19_no_password_is_set_when_a_condition_is_missing(hub: Hub, monkeypatch, case: str):
    hub.put({"a record without rustdesk_id": v2(rustdesk_id=None), "a v1 record": V1}.get(case, v2()))
    if case == "an ssh test without full access":
        monkeypatch.setattr(fleet_usb, "test_connection", lambda name, system: "connected, without full access")
    fleet_usb.import_records(hub.folder, test=case != "import with --no-test")
    assert hub.remote.calls == [] and not password_file(hub).exists()


@pytest.mark.parametrize("system", ["linux", "macos", "windows"])
def test_ac19_each_system_reads_the_password_from_standard_input_into_a_variable(hub: Hub, system: str):
    hub.put(v2(os=system))
    run_import(hub)
    command = hub.remote.calls[0]["command"]
    assert REMOTE_BINARY[system] in command and "--password" in command, command
    assert ("[Console]::In.ReadLine()" if system == "windows" else "read -r") in command, command


def test_ac19_the_remote_script_passes_the_password_only_as_the_rustdesk_argument(hub: Hub, tmp_path: Path):
    hub.put(v2())
    run_import(hub)
    command = hub.remote.calls[0]["command"]
    password = password_file(hub).read_text(encoding="ascii").strip()
    stubs = tmp_path / "member-stubs"
    stubs.mkdir()
    saved = tmp_path / "rustdesk-args.txt"
    (stubs / "sudo").write_bytes(b'#!/bin/bash\nif [ "$1" = -n ]; then shift; fi\nexec "$@"\n')
    (stubs / "rustdesk").write_bytes(b'#!/bin/bash\nprintf "%s\\n" "$@" > "$STUB_ARGS"\n')
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    launcher = ('PATH="$(cygpath -u "$STUB_BIN" 2>/dev/null || echo "$STUB_BIN"):$PATH"; export PATH; '
                'exec "$BASH" -c "$REMOTE"')
    env = dict(os.environ, STUB_BIN=stubs.as_posix(), STUB_ARGS=saved.as_posix(), REMOTE=command)
    proc = subprocess.run([need_bash(), "-c", launcher], input=(password + "\n").encode("ascii"),
                          capture_output=True, timeout=60, env=env)
    assert proc.returncode == 0, output(proc)
    assert saved.read_text(encoding="ascii").splitlines() == ["--password", password]
    assert password not in (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    for path in [*files_other_than_the_password_file(hub), *stubs.iterdir()]:
        assert password.encode("ascii") not in path.read_bytes(), path


def test_ac19_a_failed_set_is_reported_without_the_password_and_fails_the_import(hub: Hub):
    known = "known-Password_0123456789"
    password_file(hub).write_text(known + "\n", encoding="ascii", newline="")
    hub.put(v2())
    hub.remote.code = 1
    hub.remote.stderr = f"sudo: rustdesk --password {known}: command failed"
    code, out = run_import(hub)
    assert code == 1, out
    assert "lab-mini07" in out and "password not set" in out, out
    assert known not in out
    assert hub.remote.calls[0]["stdin"] == known + "\n"


def test_ac19_a_password_file_with_unusable_content_fails_that_record_and_names_the_file(hub: Hub):
    password_file(hub).write_text("two words\n", encoding="ascii", newline="")
    hub.put(v2())
    code, out = run_import(hub)
    assert code == 1, out
    assert PASSWORD_FILE in out, out
    assert hub.remote.calls == []
    assert password_file(hub).read_text(encoding="ascii") == "two words\n"


# ---------------------------------------------------------------------------------------------- AC-18

RD_ID = "123456789"
RD_TOML_ID = "987654321"
RD_DEB, RD_ARM_DEB, RD_RPM = (f"rustdesk-{RD_VERSION}-x86_64.deb", f"rustdesk-{RD_VERSION}-aarch64.deb",
                              f"rustdesk-{RD_VERSION}-0.x86_64.rpm")
RD_MSI = f"rustdesk-{RD_VERSION}-x86_64.msi"
RD_DMG_X, RD_DMG_A = f"rustdesk-{RD_VERSION}-x86_64.dmg", f"rustdesk-{RD_VERSION}-aarch64.dmg"
RD_DAEMON, RD_AGENT = "com.carriez.RustDesk_service", "com.carriez.RustDesk_server"
RD_APP = "/Applications/RustDesk.app/Contents/MacOS"
RD_GRANTS = "grant Screen Recording and Accessibility at the screen"
RD_CONFIG_ARGS = f"--config host={RD_HOST},key={RD_KEY}"

# The RustDesk program as a stub. It logs the path that ran it, then acts from files in $STUB_RD_DIR: version (what
# --version prints), id, not_ready (the number of --get-id calls that print nothing first), id_limit (the last
# --get-id call that prints the id), needs_service (--get-id prints only while the system job is loaded, on a Mac),
# persist (a file that --config writes the host to, as the real program does in the service's config folder).
RD_PROGRAM = r'''printf "%s\n" "$0 $*" >> "$STUB_LOG"
d="$STUB_RD_DIR"
case "$1" in
  --version) cat "$d/version" 2>/dev/null; exit 0;;
  --get-id)
    n=$(( $(cat "$d/calls" 2>/dev/null || echo 0) + 1 )); echo $n > "$d/calls"
    [ -f "$d/id" ] || exit 0
    [ "$n" -gt "$(cat "$d/not_ready" 2>/dev/null || echo 0)" ] || exit 0
    [ "$n" -le "$(cat "$d/id_limit" 2>/dev/null || echo 9999)" ] || exit 0
    [ ! -f "$d/needs_service" ] || grep -qxF "system/com.carriez.RustDesk_service" "$d/loaded" 2>/dev/null || exit 0
    cat "$d/id"; exit 0;;
  --config)
    if [ -f "$d/persist" ]; then
      h=${2#host=}; h=${h%%,*}; f=$(cat "$d/persist"); mkdir -p "$(dirname "$f")"
      printf "[options]\ncustom-rendezvous-server = '%s'\n" "$h" >> "$f"
    fi
    exit "$(cat "$d/config_exit" 2>/dev/null || echo 0)";;
esac
exit 0'''

# What a package install leaves behind: the program in the stub folder, and the version it reports.
RD_PACKAGE = r'''for a in "$@"; do case "$a" in ./rustdesk-*)
  v=${a#./rustdesk-}; v=${v%%-*}
  cp "$STUB_RD_PAYLOAD" "$STUB_BIN/rustdesk"; chmod +x "$STUB_BIN/rustdesk"; echo "$v" > "$STUB_RD_DIR/version";;
esac; done
exit 0'''
RD_SYSTEMCTL = '''case "$1" in
  get-default) echo "${STUB_DEFAULT_TARGET:-graphical.target}";;
  is-active) echo "${STUB_DM_STATE:-inactive}"; [ "${STUB_DM_STATE:-inactive}" = active ] || exit 3;;
esac
exit 0'''
# Sessions 3 and 7 belong to the Account; STUB_TYPE_3 and STUB_TYPE_7 are their types.
RD_LOGINCTL = r'''case "$1" in
  show-user) case "$4" in Sessions) echo "Sessions=${STUB_SESSIONS:-}";; *) echo Linger=yes;; esac;;
  show-session) case "$2" in 3) echo "Type=${STUB_TYPE_3:-tty}";; 7) echo "Type=${STUB_TYPE_7:-tty}";; *) echo "Type=tty";; esac;;
esac
exit 0'''
RD_HDIUTIL = r'''case "$1" in attach)
  mp=""; prev=""; dmg=""
  for a in "$@"; do [ "$prev" != -mountpoint ] || mp="$a"; prev="$a"; dmg="$a"; done
  d="$mp/RustDesk.app/Contents/MacOS"; mkdir -p "$d"
  cp "$STUB_RD_PAYLOAD" "$d/RustDesk"; cp "$STUB_RD_PAYLOAD" "$d/service"; chmod +x "$d/RustDesk" "$d/service"
  v=${dmg##*/rustdesk-}; echo "${v%%-*}" > "$mp/.version";;
esac
exit 0'''
RD_DITTO = r'''mkdir -p "$2"; cp -R "$1/." "$2/"
[ ! -f "$(dirname "$1")/.version" ] || cp "$(dirname "$1")/.version" "$STUB_RD_DIR/version"
exit 0'''
# A launchctl that keeps the loaded jobs in $STUB_RD_DIR/loaded and fails bootstrap of a job that is already loaded.
RD_LAUNCHCTL = r'''L="$STUB_RD_DIR/loaded"; touch "$L"
case "$1" in
  print) case "$2" in gui/*) [ -n "${STUB_GUI:-}" ] || { echo "Could not find domain for $2" >&2; exit 113; };; esac; exit 0;;
  bootout)
    grep -qxF "$2" "$L" || { echo "Boot-out failed: 3: No such process" >&2; exit 3; }
    grep -vxF "$2" "$L" > "$L.new" || true; mv "$L.new" "$L"; exit 0;;
  bootstrap)
    key="$2/$(basename "$3" .plist)"
    if grep -qxF "$key" "$L"; then echo "Bootstrap failed: 5: Input/output error" >&2; exit 5; fi
    echo "$key" >> "$L"; exit 0;;
esac
exit 0'''
RD_UID = r'''case "$1" in -u) if [ -n "${2:-}" ]; then echo "${STUB_ACCOUNT_UID:-501}"; else echo "${STUB_UID:-0}"; fi;;
-un) echo "$STUB_ACCOUNT";; -gn) echo "${2:-root}";; *) echo 0;; esac'''


class Rd:
    """A Prereq set up for the rustdesk step: the stub program, the files on the drive and the folder the stubs read."""

    def __init__(self, prereq: Prereq, gui: bool = True):
        self.p, self.kit, self.mac = prereq, prereq.kit, prereq.macos
        self.dir = self.kit.tmp / "rd"
        self.dir.mkdir()
        self.payload = self.kit.tmp / "rd-payload.sh"
        self.payload.write_bytes(("#!/bin/bash\n" + RD_PROGRAM + "\n").encode("utf-8"))
        (self.dir / "id").write_text(RD_ID + "\n", encoding="ascii")
        self.env = {"STUB_RD_DIR": msys(self.dir), "STUB_RD_PAYLOAD": msys(self.payload), "FLEET_RUSTDESK_WAIT_S": "1"}
        bodies = self.kit.bodies
        if self.mac:
            bodies.update(hdiutil=RD_HDIUTIL, ditto=RD_DITTO, launchctl=RD_LAUNCHCTL, id=RD_UID)
            (self.dir / "needs_service").write_text("1", encoding="ascii")
            self.env["STUB_GUI"] = "1"
        else:
            bodies["systemctl"] = RD_SYSTEMCTL
            bodies["loginctl"] = RD_LOGINCTL
            bodies["apt-get"] = RD_PACKAGE
            if not gui:
                self.env["STUB_DEFAULT_TARGET"] = "multi-user.target"

    @property
    def service_config(self) -> Path:
        root = self.kit.root
        return root / "var/root/Library/Preferences/com.carriez.RustDesk" if self.mac else root / "root/.config/rustdesk"

    @property
    def account_config(self) -> Path:
        home = self.p.home
        return home / "Library/Preferences/com.carriez.RustDesk" if self.mac else home / ".config/rustdesk"

    def put(self, name: str, text: str) -> None:
        (self.dir / name).write_text(text, encoding="ascii")

    def write_drive(self, names=None, host: str = RD_HOST, key: str = RD_KEY, version: str = RD_VERSION,
                    tamper: tuple[str, ...] = (), eol: str = "\n", extra: tuple[str, ...] = ()) -> None:
        """rustdesk.txt as `prepare` writes it, and the files in rustdesk/; a tampered file differs from its line."""
        names = rd_names()[0] if names is None else names
        folder = self.kit.drive / "rustdesk"
        folder.mkdir(exist_ok=True)
        lines = [f"version={version}", f"host={host}", f"key={key}", *extra]
        for name in names:
            (folder / name).write_bytes(rd_body(name) + (b" tampered" if name in tamper else b""))
            lines.append(f"file={name} {sha(rd_body(name))}")
        (self.kit.drive / "rustdesk.txt").write_bytes((eol.join(lines) + eol).encode("ascii"))

    def persist(self) -> None:
        """--config writes the host to the service's RustDesk2.toml, as the real program does."""
        self.put("persist", (self.service_config / "RustDesk2.toml").as_posix())

    def installed(self, version: str = RD_VERSION) -> None:
        """The program is already on the system, at this version."""
        if self.mac:
            folder = self.kit.root / "Applications/RustDesk.app/Contents/MacOS"
            folder.mkdir(parents=True)
            for name in ("RustDesk", "service"):
                shutil.copyfile(self.payload, folder / name)
                (folder / name).chmod(0o755)
        else:
            shutil.copyfile(self.payload, self.kit.stubs / "rustdesk")
            (self.kit.stubs / "rustdesk").chmod(0o755)
        self.put("version", version + "\n")

    def run(self, **extra: str) -> subprocess.CompletedProcess:
        return self.p.run(**{**self.env, **extra})

    def step(self, **extra: str) -> dict:
        proc = self.run(**extra)
        assert proc.returncode in (0, 1), output(proc)
        return status(self.kit.record(), "rustdesk")

    def calls(self) -> list[tuple[str, str]]:
        """Every call of the stub program as (the path that ran it, its arguments)."""
        found = []
        for line in log_lines(self.kit):
            head, _, args = line.partition(" ")
            if head.rsplit("/", 1)[-1] in ("rustdesk", "RustDesk"):
                found.append((head, args))
        return found

    def at(self, args: str) -> list[int]:
        """The positions in the log of the calls of the program whose arguments start with args."""
        return [i for i, line in enumerate(log_lines(self.kit))
                if line.partition(" ")[0].rsplit("/", 1)[-1] in ("rustdesk", "RustDesk") and line.partition(" ")[2].startswith(args)]


def log_at(kit: Kit, start: str) -> list[int]:
    return [i for i, line in enumerate(log_lines(kit)) if line.startswith(start)]


def package_installs(kit: Kit) -> list[str]:
    """The log lines of a RustDesk package or disk image being installed."""
    return [line for line in log_lines(kit) if line.startswith(("apt-get install -y ./", "dnf install -y ./", "hdiutil attach", "ditto "))]


@pytest.fixture
def lrd(linux: Prereq) -> Rd:
    return Rd(linux)


@pytest.fixture
def mrd(mac: Prereq) -> Rd:
    return Rd(mac)


def test_ac18_with_no_desktop_the_step_is_skipped_and_nothing_is_installed(linux: Prereq):
    rd = Rd(linux, gui=False)
    rd.write_drive()
    step = rd.step()
    record = linux.kit.record()
    assert step["status"] == "skipped" and step["detail"] == "no desktop"
    assert record["gui"] is False and record["rustdesk_id"] is None
    assert package_installs(linux.kit) == [] and rd.calls() == [], log_lines(linux.kit)


def test_ac18_a_display_manager_that_is_active_counts_as_a_desktop(lrd: Rd):
    lrd.write_drive()
    step = lrd.step(STUB_DEFAULT_TARGET="multi-user.target", STUB_DM_STATE="active")
    assert step["status"] == "ok", step
    assert lrd.kit.record()["gui"] is True


def test_ac18_with_a_desktop_and_no_rustdesk_file_the_step_is_skipped_with_no_server_configured(lrd: Rd):
    step = lrd.step()
    assert step["status"] == "skipped" and step["detail"] == "no server configured"
    assert lrd.kit.record()["gui"] is True
    assert package_installs(lrd.kit) == []


@pytest.mark.parametrize("machine,label", [("x86_64", "linux x86_64 (deb)"), ("aarch64", "linux aarch64 (deb)")])
def test_ac18_a_file_with_no_asset_for_this_system_skips_with_no_asset_for_the_platform(kit: Kit, machine, label):
    rd = Rd(Prereq(kit, machine=machine))
    rd.write_drive(names=[RD_MSI, RD_DMG_X])
    step = rd.step()
    assert step["status"] == "skipped" and step["detail"] == f"no asset for {label}", step
    assert package_installs(kit) == []


def test_ac18_a_deb_is_installed_with_apt_and_the_service_is_started_before_the_first_id_call(lrd: Rd):
    lrd.write_drive()
    step = lrd.step()
    assert step["status"] == "ok", step
    lines = log_lines(lrd.kit)
    install = log_at(lrd.kit, f"apt-get install -y ./{RD_DEB}")
    enable = log_at(lrd.kit, "systemctl enable --now rustdesk")
    first_id = lrd.at("--get-id")[0]
    assert len(install) == 1 and len(enable) == 1, lines
    assert install[0] < enable[0] < first_id
    assert not [line for line in lines if line.startswith("dnf install -y ./")]


def test_ac18_a_deb_for_aarch64_is_picked_on_an_arm_system(kit: Kit):
    rd = Rd(Prereq(kit, machine="aarch64"))
    rd.write_drive()
    assert rd.step()["status"] == "ok"
    assert log_at(kit, f"apt-get install -y ./{RD_ARM_DEB}") and not log_at(kit, f"apt-get install -y ./{RD_DEB}")


def test_ac18_an_rpm_is_installed_with_dnf(lrd: Rd):
    lrd.kit.bodies.pop("apt-get")
    lrd.kit.bodies["dnf"] = RD_PACKAGE
    lrd.write_drive()
    step = lrd.step()
    assert step["status"] == "ok", step
    assert len(log_at(lrd.kit, f"dnf install -y ./{RD_RPM}")) == 1
    assert log_at(lrd.kit, "systemctl enable --now rustdesk")
    assert not log_at(lrd.kit, "apt-get install -y ./")


def test_ac18_the_id_comes_from_get_id_after_the_ready_wait_and_config_follows_it(lrd: Rd):
    lrd.put("not_ready", "1")
    lrd.persist()
    lrd.write_drive()
    step = lrd.step()
    assert step["status"] == "ok", step
    ids = lrd.at("--get-id")
    config = lrd.at("--config")
    assert len(ids) >= 2 and len(config) == 1, log_lines(lrd.kit)
    assert ids[1] < config[0], "--config must wait for the id"
    record = lrd.kit.record()
    assert record["rustdesk_id"] == RD_ID
    fleet_usb.read_record(lrd.kit.record_path())


def test_ac18_config_gets_the_host_and_the_key_of_the_file(lrd: Rd):
    lrd.persist()
    lrd.write_drive()
    assert lrd.step()["status"] == "ok"
    configs = [args for _, args in lrd.calls() if args.startswith("--config")]
    assert configs == [RD_CONFIG_ARGS], configs


def test_ac18_session_type_comes_from_the_newest_session_of_the_account(lrd: Rd):
    lrd.persist()
    lrd.write_drive()
    assert lrd.step(STUB_SESSIONS="7 3", STUB_TYPE_3="x11", STUB_TYPE_7="wayland")["status"] == "ok"
    record = lrd.kit.record()
    assert record["session_type"] == "wayland" and record["gui"] is True
    assert log_at(lrd.kit, "loginctl show-session 7") and not log_at(lrd.kit, "loginctl show-session 3")


@pytest.mark.parametrize("sessions,kind", [("", "unknown"), ("3", "unspecified"), ("3", "x11 ; touch pwn"), ("3", "tty")])
def test_ac18_a_missing_or_unknown_session_type_is_recorded_as_unknown_or_tty(lrd: Rd, sessions, kind):
    lrd.persist()
    lrd.write_drive()
    lrd.step(STUB_SESSIONS=sessions, STUB_TYPE_3=kind)
    assert lrd.kit.record()["session_type"] == ("tty" if kind == "tty" else "unknown")


def test_ac18_the_record_holds_the_installed_version_in_tools(lrd: Rd):
    lrd.persist()
    lrd.write_drive()
    assert lrd.step()["status"] == "ok"
    assert lrd.kit.record()["tools"]["rustdesk"] == RD_VERSION


def test_ac18_an_installed_version_equal_to_the_file_skips_the_install_but_still_configures(lrd: Rd):
    lrd.installed(RD_VERSION)
    lrd.persist()
    lrd.write_drive()
    step = lrd.step()
    assert step["status"] == "ok", step
    assert package_installs(lrd.kit) == []
    assert len(lrd.at("--config")) == 1 and lrd.kit.record()["rustdesk_id"] == RD_ID


def test_ac18_an_older_installed_version_is_installed_over(lrd: Rd):
    lrd.installed("1.3.0")
    lrd.persist()
    lrd.write_drive()
    assert lrd.step()["status"] == "ok"
    assert len(log_at(lrd.kit, f"apt-get install -y ./{RD_DEB}")) == 1


def test_ac18_a_file_that_does_not_match_its_sha256_fails_the_step_and_installs_nothing(lrd: Rd):
    lrd.write_drive(tamper=(RD_DEB,))
    step = lrd.step()
    assert step["status"] == "failed" and RD_DEB in step["detail"] and "sha256" in step["detail"], step
    assert package_installs(lrd.kit) == [] and lrd.calls() == []
    assert not log_at(lrd.kit, "systemctl enable --now rustdesk")


def test_ac18_a_file_that_is_missing_from_the_drive_fails_the_step_and_installs_nothing(lrd: Rd):
    lrd.write_drive()
    (lrd.kit.drive / "rustdesk" / RD_DEB).unlink()
    step = lrd.step()
    assert step["status"] == "failed" and RD_DEB in step["detail"], step
    assert package_installs(lrd.kit) == []


def test_ac18_a_service_that_never_prints_an_id_fails_the_step_with_service_not_ready(lrd: Rd):
    lrd.put("not_ready", "999")
    lrd.write_drive()
    step = lrd.step()
    assert step["status"] == "failed" and step["detail"] == "service not ready", step
    assert lrd.at("--config") == [] and lrd.kit.record()["rustdesk_id"] is None


def test_ac18_when_config_reaches_the_service_nothing_is_rewritten_and_nothing_restarts(lrd: Rd):
    lrd.persist()
    lrd.write_drive()
    assert lrd.step()["status"] == "ok"
    assert not log_at(lrd.kit, "systemctl restart rustdesk")
    assert not (lrd.account_config / "RustDesk2.toml").exists()


def test_ac18_when_the_service_config_lacks_the_host_both_files_are_written_and_the_service_restarts(lrd: Rd):
    lrd.write_drive()
    step = lrd.step()
    assert step["status"] == "ok", step
    for folder in (lrd.service_config, lrd.account_config):
        text = (folder / "RustDesk2.toml").read_text(encoding="utf-8")
        assert "[options]" in text
        assert f"custom-rendezvous-server = '{RD_HOST}'" in text and f"key = '{RD_KEY}'" in text, text
    config, restart = lrd.at("--config")[0], log_at(lrd.kit, "systemctl restart rustdesk")
    assert len(restart) == 1 and config < restart[0]
    assert len([i for i in lrd.at("--get-id") if i > restart[0]]) >= 1, "the step waits for Ready again"


def test_ac18_a_config_call_that_exits_nonzero_leaves_the_read_back_and_the_toml_fallback_to_decide(lrd: Rd):
    lrd.put("config_exit", "1")
    lrd.write_drive()
    step = lrd.step()
    assert step["status"] == "ok", step
    assert len(lrd.at("--config")) == 1
    for folder in (lrd.service_config, lrd.account_config):
        assert f"custom-rendezvous-server = '{RD_HOST}'" in (folder / "RustDesk2.toml").read_text(encoding="utf-8")
    assert len(log_at(lrd.kit, "systemctl restart rustdesk")) == 1
    assert lrd.kit.record()["rustdesk_id"] == RD_ID


def test_ac18_the_toml_fallback_keeps_the_other_settings_and_replaces_an_old_server(lrd: Rd):
    old = ("rendezvous_server = 'old.example.test:21116'\nnat_type = 1\n\n[options]\n"
           "custom-rendezvous-server = 'old.example.test'\nkey = 'oldoldoldoldoldoldoldoldoldoldoldoldoldoldoldold'\n"
           "theme = 'dark'\n")
    lrd.service_config.mkdir(parents=True)
    (lrd.service_config / "RustDesk2.toml").write_text(old, encoding="utf-8")
    lrd.write_drive()
    assert lrd.step()["status"] == "ok"
    text = (lrd.service_config / "RustDesk2.toml").read_text(encoding="utf-8")
    assert "nat_type = 1" in text and "theme = 'dark'" in text and "rendezvous_server = 'old.example.test:21116'" in text
    assert "old.example.test'" not in text.replace("rendezvous_server = 'old.example.test:21116'", "")
    assert "oldoldold" not in text, "the old key stays"
    assert text.count("custom-rendezvous-server") == 1 and text.count("key = ") == 1
    assert f"custom-rendezvous-server = '{RD_HOST}'" in text


def test_ac18_when_get_id_prints_none_the_id_comes_from_the_service_toml(lrd: Rd):
    lrd.put("id_limit", "1")
    lrd.persist()
    lrd.service_config.mkdir(parents=True)
    (lrd.service_config / "RustDesk.toml").write_text(f"enc_id = 'x'\nid = '{RD_TOML_ID}'\n", encoding="utf-8")
    lrd.write_drive()
    step = lrd.step()
    assert step["status"] == "ok", step
    assert lrd.kit.record()["rustdesk_id"] == RD_TOML_ID


def test_ac18_with_no_id_from_get_id_and_none_in_the_toml_the_step_fails(lrd: Rd):
    lrd.put("id_limit", "1")
    lrd.persist()
    lrd.write_drive()
    step = lrd.step()
    assert step["status"] == "failed" and "id" in step["detail"], step
    assert lrd.kit.record()["rustdesk_id"] is None


def test_ac18_a_rustdesk_file_with_no_valid_host_fails_the_step_and_installs_nothing(lrd: Rd):
    lrd.write_drive(host="hub example")
    step = lrd.step()
    assert step["status"] == "failed" and "rustdesk.txt" in step["detail"], step
    assert package_installs(lrd.kit) == [] and lrd.calls() == []


def test_ac18_the_rustdesk_file_is_read_as_data_and_a_windows_line_end_is_read(lrd: Rd):
    marker = lrd.kit.tmp / "pwned"
    extra = (f"$(touch {marker.as_posix()})", f"`touch {marker.as_posix()}`", f"file=../x.deb {'0' * 64}", "unknown=1")
    lrd.persist()
    lrd.write_drive(extra=extra, eol="\r\n")
    step = lrd.step()
    assert step["status"] == "ok", step
    assert not marker.exists()
    assert not [line for line in log_lines(lrd.kit) if "x.deb" in line]


# A Mac: the stub dmg holds RustDesk.app; launchctl keeps the loaded jobs; the Account has user id 501.

def test_ac18_a_fresh_mac_copies_the_app_from_the_disk_image_with_hdiutil_and_ditto(mrd: Rd):
    mrd.write_drive()
    step = mrd.step()
    assert step["status"] == "ok", step
    lines = log_lines(mrd.kit)
    attach = [i for i, line in enumerate(lines) if line.startswith("hdiutil attach -nobrowse -readonly ")]
    dittos = [i for i, line in enumerate(lines) if line.startswith("ditto ")]
    detach = [i for i, line in enumerate(lines) if line.startswith("hdiutil detach")]
    assert len(attach) == len(dittos) == len(detach) == 1, lines
    assert attach[0] < dittos[0] < detach[0]
    assert lines[attach[0]].endswith(f"/rustdesk/{RD_DMG_X}") and lines[dittos[0]].endswith("/Applications/RustDesk.app")
    assert (mrd.kit.root / "Applications/RustDesk.app/Contents/MacOS/RustDesk").is_file()


def test_ac18_an_arm_mac_picks_the_aarch64_disk_image(kit: Kit):
    rd = Rd(Prereq(kit, macos=True, machine="arm64"))
    rd.write_drive()
    assert rd.step()["status"] == "ok"
    assert [line for line in log_lines(kit) if line.startswith("hdiutil attach")][0].endswith(f"/rustdesk/{RD_DMG_A}")


def test_ac18_a_fresh_mac_writes_both_launchd_jobs_as_root_wheel_mode_644(mrd: Rd):
    import plistlib
    mrd.write_drive()
    assert mrd.step()["status"] == "ok"
    daemon = mrd.kit.root / f"Library/LaunchDaemons/{RD_DAEMON}.plist"
    agent = mrd.kit.root / f"Library/LaunchAgents/{RD_AGENT}.plist"
    service = plistlib.loads(daemon.read_bytes())
    assert service["Label"] == RD_DAEMON and service["ProgramArguments"] == [f"{RD_APP}/service"]
    assert service["RunAtLoad"] is True and service["KeepAlive"] is True
    server = plistlib.loads(agent.read_bytes())
    assert server["Label"] == RD_AGENT and server["ProgramArguments"] == [f"{RD_APP}/RustDesk", "--server"]
    assert server["RunAtLoad"] is True and sorted(server["LimitLoadToSessionType"]) == ["Aqua", "LoginWindow"]
    lines = log_lines(mrd.kit)
    for folder, label in (("LaunchDaemons", RD_DAEMON), ("LaunchAgents", RD_AGENT)):
        placed = [line for line in lines if line.startswith("install -m 644 -o root -g wheel ")
                  and line.endswith(f"/Library/{folder}/{label}.plist")]
        assert len(placed) == 1, (folder, lines)


def test_ac18_the_system_job_is_bootstrapped_before_the_first_id_call(mrd: Rd):
    mrd.persist()  # --config sticks, so the TOML fallback and its second bootstrap (the fallback test) do not run
    mrd.write_drive()
    assert mrd.step()["status"] == "ok"
    daemon = f"launchctl bootstrap system {msys(mrd.kit.root)}/Library/LaunchDaemons/{RD_DAEMON}.plist"
    boot = log_at(mrd.kit, daemon)
    assert len(boot) == 1, log_lines(mrd.kit)
    assert boot[0] < mrd.at("--get-id")[0]
    assert log_at(mrd.kit, f"launchctl bootout system/{RD_DAEMON}")[0] < boot[0]


@pytest.mark.parametrize("session", [True, False])
def test_ac18_the_gui_job_is_bootstrapped_only_when_the_account_has_a_gui_session(mrd: Rd, session: bool):
    mrd.write_drive()
    if not session:
        mrd.env.pop("STUB_GUI")
    assert mrd.step()["status"] == "ok"
    agent = f"launchctl bootstrap gui/501 {msys(mrd.kit.root)}/Library/LaunchAgents/{RD_AGENT}.plist"
    assert log_at(mrd.kit, "launchctl print gui/501")
    assert bool(log_at(mrd.kit, agent)) is session, log_lines(mrd.kit)
    assert bool(log_at(mrd.kit, f"launchctl bootout gui/501/{RD_AGENT}")) is session


def test_ac18_config_runs_through_the_app_binary_and_the_detail_names_the_two_grants(mrd: Rd):
    mrd.persist()
    mrd.write_drive()
    step = mrd.step()
    assert step["status"] == "ok" and step["detail"] == RD_GRANTS, step
    binary = f"{msys(mrd.kit.root)}{RD_APP}/RustDesk"
    configs = [(path, args) for path, args in mrd.calls() if args.startswith("--config")]
    assert configs == [(binary, RD_CONFIG_ARGS)], configs
    record = mrd.kit.record()
    assert record["gui"] is True and record["rustdesk_id"] == RD_ID and record["session_type"] == "unknown"
    assert record["tools"]["rustdesk"] == RD_VERSION


def test_ac18_a_mac_run_where_bootstrap_loads_nothing_never_reaches_config(mrd: Rd):
    mrd.kit.bodies["launchctl"] = 'case "$1" in print) exit 0;; esac\nexit 0'
    mrd.write_drive()
    step = mrd.step()
    assert step["status"] == "failed" and step["detail"] == "service not ready", step
    assert log_at(mrd.kit, "launchctl bootstrap system") and mrd.at("--config") == []


def test_ac18_a_failed_system_bootstrap_fails_the_step_and_never_reaches_config(mrd: Rd):
    mrd.kit.bodies["launchctl"] = 'case "$1" in bootstrap) echo "Bootstrap failed: 5" >&2; exit 5;; esac\nexit 0'
    mrd.write_drive()
    step = mrd.step()
    assert step["status"] == "failed" and "launchctl" in step["detail"], step
    assert mrd.at("--config") == []


def jobs_boot_after_a_bootout(kit: Kit) -> None:
    """Each bootstrap in the log follows a bootout of the same job, with no other bootstrap of it in between."""
    last: dict[str, str] = {}
    seen = 0
    for line in log_lines(kit):
        words = line.split()
        if len(words) < 3 or words[0] != "launchctl" or words[1] not in ("bootout", "bootstrap"):
            continue
        if words[1] == "bootout":
            job = words[2]
        else:
            job = f"{words[2]}/{words[3].rsplit('/', 1)[-1][:-len('.plist')]}"
            seen += 1
            assert last.get(job) == "bootout", f"{job} was bootstrapped without a bootout before it: {line}"
        last[job] = words[1]
    assert seen >= 2, "the run bootstrapped no job"


def test_ac18_a_second_setup_run_on_the_same_root_ends_ok_and_every_bootstrap_follows_a_bootout(mrd: Rd):
    mrd.persist()
    mrd.write_drive()
    assert mrd.step()["status"] == "ok"
    loaded = (mrd.dir / "loaded").read_text(encoding="ascii").split()
    assert sorted(loaded) == sorted([f"system/{RD_DAEMON}", f"gui/501/{RD_AGENT}"])
    first_installs = package_installs(mrd.kit)
    assert len(first_installs) == 2, first_installs
    second = mrd.step()
    assert second["status"] == "ok", second
    assert package_installs(mrd.kit) == first_installs, "the second run installs again"
    jobs_boot_after_a_bootout(mrd.kit)
    assert sorted((mrd.dir / "loaded").read_text(encoding="ascii").split()) == sorted(loaded)


def test_ac18_a_first_run_that_takes_the_toml_fallback_reloads_both_jobs_after_a_bootout(mrd: Rd):
    mrd.write_drive()
    step = mrd.step()
    assert step["status"] == "ok", step
    for folder in (mrd.service_config, mrd.account_config):
        assert f"custom-rendezvous-server = '{RD_HOST}'" in (folder / "RustDesk2.toml").read_text(encoding="utf-8")
    config = mrd.at("--config")[0]
    for job, domain in ((RD_DAEMON, "system"), (RD_AGENT, "gui/501")):
        assert [i for i in log_at(mrd.kit, f"launchctl bootstrap {domain} ") if i > config], f"{job} was not reloaded"
    jobs_boot_after_a_bootout(mrd.kit)
    assert len([i for i in mrd.at("--get-id") if i > config]) >= 1, "the step waits for Ready again"


def test_ac18_a_rerun_does_not_fail_on_a_gui_job_that_is_already_loaded(mrd: Rd):
    mrd.persist()
    mrd.write_drive()
    (mrd.dir / "loaded").write_text(f"gui/501/{RD_AGENT}\nsystem/{RD_DAEMON}\n", encoding="ascii")
    mrd.installed(RD_VERSION)
    step = mrd.step()
    assert step["status"] == "ok", step
    assert package_installs(mrd.kit) == []
    jobs_boot_after_a_bootout(mrd.kit)


# ---------------------------------------------------------------------------------------------- AC-20 and AC-21

GUIDE_URL = "https://matbanik.info/hobbies/systems/posts/rustdesk-server-on-windows-without-docker/"
FLEET = REPO / ".agent" / "fleet"
SIX_ISSUES = ("FLEET-AGY-RETIRED-NAME", "FLEET-UNIX-MEMBER-BOOTSTRAP-EMPTY", "FLEET-INSTALLERS-UNVERIFIED",
              "FLEET-RUSTDESK-WAYLAND", "FLEET-AC38-BILLING-LINE-PIN", "FLEET-INSTALL-RETAINED-CREDITS-TESTS")
KNOWN_ISSUES_YAML = REPO / ".agent" / "context" / "known-issues.yaml"
KNOWN_ISSUES_MD = REPO / ".agent" / "context" / "known-issues.md"
TRIAGE = REPO / "core" / "tools" / "issue_triage.py"


def doc(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ac20_the_usb_readme_gives_the_hub_steps_and_the_guide_link():
    text = doc(USB / "README.md")
    assert GUIDE_URL in text
    for needle in ("fleet_usb.py prepare", "--hub-url", "--rustdesk-host", "--rustdesk-key-file",
                   "fleet_usb.py receive", "fleet_usb.py import", "hub.txt"):
        assert needle in text, f"README.md lacks {needle}"


def test_ac20_the_usb_readme_gives_the_firewall_line_for_port_8771():
    line = next((row for row in doc(USB / "README.md").splitlines() if "New-NetFirewallRule" in row), "")
    for needle in ("'Fleet USB receive 8771'", "-Direction Inbound", "-Protocol TCP", "-LocalPort 8771", "-Profile Private"):
        assert needle in line, f"the firewall line lacks {needle}: {line!r}"


def test_ac20_the_usb_readme_gives_the_bash_terminal_lines_and_never_sudo_bash():
    text = doc(USB / "README.md")
    assert re.search(r"^macOS:\s+bash /Volumes/\S+/setup-unix\.sh", text, re.MULTILINE)
    assert re.search(r"^Linux:\s+bash /media/\S+/setup-unix\.sh", text, re.MULTILINE)
    for path in (USB / "README.md", FLEET / "install-usb" / "README.md", REPO / "core" / "MANIFEST.md",
                 FLEET / "bootstrap.md", USB / "fleet_usb.py"):
        assert not re.search(r"\bsudo\s+bash\b", doc(path)), f"{path.name} holds 'sudo bash'"


def test_ac20_the_usb_readme_names_the_member_side_of_rustdesk_and_the_macos_grants():
    text = doc(USB / "README.md")
    for needle in ("Screen Recording", "Accessibility", "-rustdesk-password.txt"):
        assert needle in text, f"README.md lacks {needle}"
    assert "wayland" in text.lower(), "the README does not say that a Wayland session limits unattended access"


def test_ac20_the_usb_readme_undo_section_removes_rustdesk_and_the_path_entry():
    text = doc(USB / "README.md")
    assert "## Undo" in text
    undo = text.split("## Undo", 1)[1]
    assert "RustDesk" in undo and "PATH" in undo, undo


def test_ac20_the_usb_readme_no_longer_says_that_each_run_rewrites_the_drive_record_only():
    text = doc(USB / "README.md")
    assert "sends its record to the hub" in text or "send its record to the hub" in text
    assert "Each run rewrites that machine's record on the drive." not in text


def test_ac20_the_install_usb_readme_points_to_the_bash_launch_form():
    lines = doc(FLEET / "install-usb" / "README.md").splitlines()
    assert any("../usb/README.md" in row and "`bash`" in row for row in lines), "no line names the bash launch form"


def test_ac20_the_manifest_entry_names_the_send_receive_rustdesk_and_bash():
    entry = next(row for row in doc(REPO / "core" / "MANIFEST.md").splitlines() if row.startswith("- `.agent/fleet/usb/`"))
    for needle in ("receive", "RustDesk", "`bash`", "network"):
        assert needle in entry, f"the MANIFEST entry lacks {needle}: {entry}"


def test_ac20_bootstrap_names_port_8771_inside_the_firewall_step_as_a_separate_kit_rule():
    text = doc(FLEET / "bootstrap.md")
    step = text.split("**STOP FOR HUMAN: firewall-rule.**", 1)[1].split("\n4. ", 1)[0]
    assert "Fleet hub 8770" in step and "8771" in step and "Fleet USB receive 8771" in step, step


def test_ac20_the_fleet_usb_docstring_names_receive_hub_txt_and_rustdesk():
    docstring = fleet_usb.__doc__ or ""
    for needle in ("receive", "hub.txt", "--rustdesk-host", "import"):
        assert needle in docstring, needle


def issue_ids(text: str) -> list[str]:
    return re.findall(r"^- id: (\S+)\s*$", text, re.MULTILINE)


def test_ac21_the_six_known_issues_are_in_the_yaml_once_each_and_open():
    text = doc(KNOWN_ISSUES_YAML)
    ids = issue_ids(text)
    for name in SIX_ISSUES:
        assert ids.count(name) == 1, f"{name} appears {ids.count(name)} times"
        block = text.split(f"- id: {name}\n", 1)[1].split("\n- id: ", 1)[0]
        assert re.search(r"^  status: open$", block, re.MULTILINE), f"{name} is not open"
        assert re.search(r"^  (root_cause|blast_radius):", block, re.MULTILINE), f"{name} has no cause or radius"


def test_ac21_the_markdown_lists_the_six_known_issues():
    text = doc(KNOWN_ISSUES_MD)
    for name in SIX_ISSUES:
        assert name in text, f"{name} is not in known-issues.md"


def test_ac21_render_check_passes_on_the_pair():
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([sys.executable, str(TRIAGE), "--yaml", str(KNOWN_ISSUES_YAML), "--md", str(KNOWN_ISSUES_MD),
                           "render", "--check"], capture_output=True, text=True, encoding="utf-8", env=env, cwd=REPO, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "up-to-date" in proc.stdout
