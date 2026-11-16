"""The shared OS lease core: one kernel lock on one byte of a persistent file.

``tools/lanes.py`` (the registry lock, MEU-784 design §5.2) holds its lock
through this module, and a project gate runner that takes the gate lease can
use it too; ``tools/executor_worktree.py``'s gate lease uses the same byte, so
all of them speak one on-disk protocol (design §10b):

- the lock is one byte at ``LOCK_OFFSET``: ``msvcrt.locking`` on Windows,
  ``flock`` elsewhere. Windows byte-range locks are mandatory, so the byte sits
  far past any body; the body stays readable through other handles, and
  LockFile allows locking past end-of-file;
- the kernel lock alone decides who holds the lease; the body is written only
  after the lock is taken and is display data for contenders;
- the file is never deleted: a contender could lock the unlinked file while a
  third process created and locked a new one, giving two holders.
"""

from __future__ import annotations

import errno
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

LOCK_OFFSET = 2**20
POLL_S = 0.05


class Busy(RuntimeError):
    """Another handle holds the lock on ``path``.

    ``holder_body`` is the body as read through the contender's own handle,
    raw bytes (the contender never writes).
    """

    def __init__(self, path: Path, holder_body: bytes) -> None:
        self.path = path
        self.holder_body = holder_body
        super().__init__(f"lease busy: {path}")


@dataclass
class Lease:
    """A held lease: the lock file and its open, locked handle."""

    path: Path
    fd: int
    released: bool = False


def _open_lease_file(path: Path) -> int:
    """Open LEASE_PATH read-write, creating it, never truncating; not inheritable."""
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOINHERIT", 0)
    )
    return os.open(path, flags, 0o644)


def _lease_lock(fd: int) -> bool:
    """One non-blocking exclusive lock attempt (LEASE_LOCK); True when acquired.

    Only lock contention reads as False; any other OSError propagates.
    """
    if sys.platform == "win32":
        os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except PermissionError:
            return False
        except OSError as exc:
            # EDEADLOCK: the CRT's "resource deadlock" for a held region.
            if exc.errno == getattr(errno, "EDEADLOCK", 36):
                return False
            raise
        return True
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _lease_unlock(fd: int) -> None:
    """Release the lock this handle holds."""
    if sys.platform == "win32":
        os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_lease_fd(fd: int) -> bytes:
    """The body as it is now, read through ``fd`` without writing."""
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while total < LOCK_OFFSET:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _write_body(fd: int, body: bytes) -> None:
    """Replace the body under the lock ``fd`` holds: truncate, then write all."""
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    view = memoryview(body)
    while view:
        written = os.write(fd, view)
        view = view[written:]


_CE_FILE = "coordination_events.py"
_ce_cache: list[ModuleType | None] = []


def _load_ce() -> ModuleType | None:
    """The coordination-event writer, loaded by file path; ``None`` when it cannot load.

    No module-level import and no ``sys.path`` change (MEU-943 design item 3a): a copy
    of this file without the writer beside it behaves as before.
    """
    path = Path(__file__).with_name(_CE_FILE)
    try:
        if not path.is_file():
            return None
        spec = importlib.util.spec_from_file_location(
            "_os_lease_coordination_events", path
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - a writer that cannot load writes nothing (§5.4)
        return None
    return module


def _record_event(**fields: Any) -> None:
    """Write one coordination-event record; never raises, and the result is ignored."""
    if not _ce_cache:
        _ce_cache.append(_load_ce())
    module = _ce_cache[0]
    if module is None:
        return
    try:
        fields["blocker"] = module.token(fields.get("blocker"))
        module.record(**fields)
    except Exception:  # noqa: BLE001 - a record never changes the caller (§5.4)
        return


def _holder_pid(body: bytes) -> str | None:
    """The ``pid`` of a holder body as text, or ``None`` when the body names none."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    pid = data.get("pid") if isinstance(data, dict) else None
    if isinstance(pid, int) and not isinstance(pid, bool):
        return str(pid)
    return None


def acquire(
    path: Path,
    *,
    wait_s: float,
    body: bytes,
    poll_s: float = POLL_S,
    record: bool = True,
) -> Lease:
    """Take the lock on ``path``, polling up to ``wait_s``, then write ``body``.

    ``wait_s`` 0 is one attempt. The body is written only after the lock is
    held; no token is exported and the environment is not changed. A busy
    result writes one ``busy_observed`` record (``os_lease_busy``, MEU-943 S4)
    unless ``record`` is ``False``: a probe that finds the lease busy is not a
    wait.

    Raises:
        ValueError: ``wait_s`` is negative or not finite, ``poll_s`` is not
            positive, or ``body`` is not bytes or would reach ``LOCK_OFFSET``.
        Busy: the lock was still held when ``wait_s`` ran out. Nothing was
            written.
        OSError: the file could not be opened, locked or written.
    """
    if not isinstance(wait_s, (int, float)) or not 0 <= wait_s < float("inf"):
        raise ValueError(
            f"os_lease.acquire: wait_s must be a finite number >= 0, got {wait_s!r}"
        )
    if not isinstance(poll_s, (int, float)) or not 0 < poll_s < float("inf"):
        raise ValueError(
            f"os_lease.acquire: poll_s must be a finite number > 0, got {poll_s!r}"
        )
    if not isinstance(body, bytes):
        raise ValueError(
            f"os_lease.acquire: body must be bytes, got {type(body).__name__}"
        )
    if len(body) >= LOCK_OFFSET:
        raise ValueError(
            f"os_lease.acquire: body is {len(body)} bytes; it must stay below LOCK_OFFSET ({LOCK_OFFSET})"
        )
    fd = _open_lease_file(path)
    deadline = time.monotonic() + wait_s
    try:
        while True:
            if _lease_lock(fd):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                holder = _read_lease_fd(fd)
                if record:
                    _record_event(
                        kind="busy_observed",
                        writer="os_lease",
                        reason="os_lease_busy",
                        scope=Path(path).name,
                        blocker=_holder_pid(holder),
                    )
                raise Busy(path, holder)
            time.sleep(min(poll_s, remaining))
    except BaseException:
        os.close(fd)
        raise
    lease = Lease(path=path, fd=fd)
    try:
        _write_body(fd, body)
    except BaseException:
        release(lease)
        raise
    return lease


def release(lease: Lease) -> None:
    """Truncate the body, unlock, close; idempotent. The file is never deleted."""
    if lease.released:
        return
    lease.released = True
    try:
        os.ftruncate(lease.fd, 0)
    finally:
        try:
            _lease_unlock(lease.fd)
        finally:
            os.close(lease.fd)
