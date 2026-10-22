"""MEU-784 AC-784.1: the shared OS lease core (``tools/os_lease.py``) — red first (G19).

FIC: ``docs/execution/plans/2026-10-20-multi-agent-lanes/implementation-plan.md``
§MEU-784 (AC-784.1; design §5.2 "The registry lock", §10b "Lease extraction").

The lock holder is a separate Python process with this file's own copy of the
lock protocol (one byte at ``2**20``: ``msvcrt.locking`` on Windows, ``flock``
elsewhere), so the tests pin the on-disk protocol that ``executor_worktree.py``'s
gate lease and ``lanes.py`` share. Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK_OFFSET = 2**20
WAIT_S = 0.2
POLL_S = 0.01
# Generous bound for a 0.2 s wait on a loaded host; a blocking acquire never returns.
BUSY_RETURN_MAX_S = 5.0

HOLDER = """
import os
import sys

path, body = sys.argv[1], sys.argv[2]
flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
fd = os.open(path, flags, 0o644)
try:
    if sys.platform == "win32":
        import msvcrt
        os.lseek(fd, 2**20, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print("busy", flush=True)
    sys.exit(1)
os.ftruncate(fd, 0)
os.lseek(fd, 0, os.SEEK_SET)
os.write(fd, body.replace("{pid}", str(os.getpid())).encode("utf-8"))
print(f"held {os.getpid()}", flush=True)
sys.stdin.read()
if sys.platform == "win32":
    os.lseek(fd, 2**20, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    fcntl.flock(fd, fcntl.LOCK_UN)
os.close(fd)
"""


def _os_lease() -> ModuleType:
    return importlib.import_module("tools.os_lease")


class _Holder:
    """A separate process that holds the lock on ``path`` until ``stop``."""

    def __init__(self, path: Path, body: str) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(path), body],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline().strip()
        # The holder reports its own pid: under a venv launcher (uv on Windows)
        # sys.executable is a trampoline whose child is the real interpreter,
        # so Popen.pid is not the process that holds the lock.
        word, _, pid = line.partition(" ")
        assert word == "held" and pid.isdigit(), line
        self._pid = int(pid)

    @property
    def pid(self) -> int:
        return self._pid

    def stop(self) -> None:
        if self.proc.poll() is None:
            assert self.proc.stdin is not None
            self.proc.stdin.close()
            self.proc.wait(timeout=30)


@pytest.fixture
def holder_factory() -> Iterator[list[_Holder]]:
    holders: list[_Holder] = []
    yield holders
    for h in holders:
        h.stop()


def test_ac784_1_the_lease_shares_the_gate_lease_lock_byte() -> None:
    # The framework has no project gate runner; its gate lease is ``executor_worktree``'s,
    # and the lanes registry lock uses the same one-byte protocol (design §10b).
    lease = _os_lease()
    ew = importlib.import_module("tools.executor_worktree")
    assert lease.LOCK_OFFSET == LOCK_OFFSET
    assert ew.LEASE_LOCK_OFFSET == lease.LOCK_OFFSET
    lanes = importlib.import_module("tools.lanes")
    assert lanes.os_lease is lease


def test_ac784_1_constants() -> None:
    lease = _os_lease()
    assert lease.POLL_S == 0.05


def test_ac784_1_acquire_writes_the_body_and_release_keeps_the_file(
    tmp_path: Path,
) -> None:
    lease_mod = _os_lease()
    path = tmp_path / "registry.lock"
    env_before = dict(os.environ)
    body = json.dumps({"pid": os.getpid(), "argv": ["lanes.py", "claim"]}).encode(
        "utf-8"
    )
    lease = lease_mod.acquire(path, wait_s=WAIT_S, body=body, poll_s=POLL_S)
    try:
        assert path.read_bytes()[: len(body)] == body
        # The registry lock exports no token (design §10b).
        assert dict(os.environ) == env_before
        assert not hasattr(lease, "token")
    finally:
        lease_mod.release(lease)
    # Never unlinked: the persistent lock file outlives every holder.
    assert path.is_file()
    # The lock is free again: a second acquire succeeds at once.
    again = lease_mod.acquire(path, wait_s=0, body=b"{}", poll_s=POLL_S)
    lease_mod.release(again)
    assert path.is_file()


def test_ac784_1_held_lock_waits_then_raises_busy_with_the_holder_body(
    tmp_path: Path, holder_factory: list[_Holder]
) -> None:
    lease_mod = _os_lease()
    path = tmp_path / "registry.lock"
    holder = _Holder(path, '{"pid": {pid}, "argv": ["holder.py", "claim"]}')
    holder_factory.append(holder)
    start = time.monotonic()
    with pytest.raises(lease_mod.Busy) as caught:
        lease_mod.acquire(path, wait_s=WAIT_S, body=b'{"pid": 0}', poll_s=POLL_S)
    elapsed = time.monotonic() - start
    assert WAIT_S <= elapsed < BUSY_RETURN_MAX_S, elapsed
    held = json.loads(caught.value.holder_body.decode("utf-8"))
    assert held["pid"] == holder.pid
    assert held["argv"] == ["holder.py", "claim"]
    # The contender never wrote: the holder's body is intact.
    assert json.loads(path.read_bytes().decode("utf-8"))["pid"] == holder.pid
    holder.stop()
    assert path.is_file()
    lease = lease_mod.acquire(path, wait_s=WAIT_S, body=b'{"pid": 1}', poll_s=POLL_S)
    lease_mod.release(lease)


def test_ac784_1_wait_zero_is_one_attempt(
    tmp_path: Path, holder_factory: list[_Holder]
) -> None:
    lease_mod = _os_lease()
    path = tmp_path / "registry.lock"
    holder = _Holder(path, '{"pid": {pid}}')
    holder_factory.append(holder)
    start = time.monotonic()
    with pytest.raises(lease_mod.Busy):
        lease_mod.acquire(path, wait_s=0, body=b"{}", poll_s=POLL_S)
    assert time.monotonic() - start < BUSY_RETURN_MAX_S


def test_ac784_1_busy_carries_the_raw_body_when_it_is_not_json(
    tmp_path: Path, holder_factory: list[_Holder]
) -> None:
    lease_mod = _os_lease()
    path = tmp_path / "registry.lock"
    holder_factory.append(_Holder(path, "not json {pid}"))
    with pytest.raises(lease_mod.Busy) as caught:
        lease_mod.acquire(path, wait_s=0, body=b"{}", poll_s=POLL_S)
    assert caught.value.holder_body.startswith(b"not json ")
    assert caught.value.path == path
