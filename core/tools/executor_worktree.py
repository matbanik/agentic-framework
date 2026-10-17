"""Executor worktree: an isolated tree of record for one execution session.

GT-6 MEU-642 (predicates ``EXECUTOR_WORKTREE`` and ``WORKTREE_LAND`` in
``docs/execution/plans/2026-10-01-gt6-shared-tree-session-concurrency/``).

Two execution sessions on one working tree void each other's gates. This tool
gives a session its own tree beside the repository and moves its work back
without a commit::

    uv run python tools/executor_worktree.py create <slug> [--branch NAME] [--base REV] [--carry PATH]...
    uv run python tools/executor_worktree.py check <path>
    uv run python tools/executor_worktree.py land <path>
    uv run python tools/executor_worktree.py sync <path> <rel>...
    uv run python tools/executor_worktree.py remove <path> [--discard]

``create`` checks the base out with LF endings into ``<root>-<slug>``, carries
the named planning inputs across, links the dependency trees, copies the env
files and the frozen directories, builds the worktree's own ``.venv`` and pins
a baseline tree as ``refs/executor-worktrees/<slug>``. The project parts come
from ``.agent/credits/worktree.json`` in the main tree (``load_worktree_config``):

* ``env_files``: ignored files copied into the worktree (``[".env"]``);
* ``frozen_dirs``: ignored directories copied as bytes, never linked;
* ``venv_build``: the command that builds the worktree's ``.venv``, or null
  for a project without one. When it starts with ``uv``, ``--python`` and the
  main tree's interpreter version are added;
* ``linked_trees``: ignored directory names linked back to the main tree. ``land`` writes every file that
differs from that baseline onto the main tree, uncommitted, under the main
tree's gate lease, after checking that no sibling session changed the same
file. ``sync`` refreshes one file from the main tree after such a refusal.
``remove`` deletes the worktree once everything in it has landed.

The base is ``--base``, else ``CREDITS_BASE_COMMIT`` (the commit B that a
credits run's admission recorded, R§5.4), else ``HEAD``. A base that does not
name a commit is refused with ``worktree_bad:base_unknown`` before anything is
made. The baseline is the base's tree plus the carried files, so ``land``
writes only what the session changed, never the main tree's commits after B.
While ``CREDITS_BASE_COMMIT`` is set ``sync`` is refused with
``worktree_bad:base_bound``: a run bound to B never pulls main-tree content in.

Every outcome is one line on stdout (``worktree_ready:<path>``, ``worktree_ok``,
``land_ok:<A>:<M>:<D>``, ``sync_ok:<rel>``, ``worktree_removed:<path>``, or a
``worktree_bad:`` / ``land_fail:`` / ``sync_fail:`` refusal). A failing git
call prints ``git_error:<subcommand>``, forwards git's stderr and stops; a
filesystem failure prints ``io_error:<type>:<path>``. Exit 0 on success, 1 on
a refusal or failure, 2 on a usage error.

A missing or invalid config refuses ``create`` and ``check`` with
``worktree_bad:config`` and the reason on stderr.

``check``, ``land``, ``sync`` and ``remove`` take the main tree from the
worktree's manifest, so they work from either tree. ``land`` and ``sync``
never commit, never run hooks and never touch the real index. Two changes
cannot land through a tree diff and are made on the main tree itself: a
case-only rename (refused with a ``case`` line) and a file-mode change.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# The default ``--root``: the tree that holds ``tools/``.
_REPO_ROOT = Path(os.path.abspath(__file__)).parent.parent

WORKTREE_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,40}")
WORKTREE_REF_PREFIX = "refs/executor-worktrees/"
TEMP_INDEX = "executor-index.tmp"
OVERLAY_FILE = ".agent/model-registry.local.json"
VENV_MARKER = ".venv/pyvenv.cfg"
ENV_BASE_COMMIT = "CREDITS_BASE_COMMIT"
# The adopter config: the project parts of a worktree (AC-J.2).
WORKTREE_CONFIG = ".agent/credits/worktree.json"
WORKTREE_CONFIG_LISTS = ("env_files", "frozen_dirs", "linked_trees")
WORKTREE_CONFIG_KEYS = frozenset({*WORKTREE_CONFIG_LISTS, "venv_build"})
# ``create`` writes this file in a worktree's git dir; its ``links`` are the
# dependency trees linked back to ``source_root``.
WORKTREE_MANIFEST = "executor-worktree.json"
# The main tree's gate lease: ``<git rev-parse --absolute-git-dir>/LEASE_NAME``,
# one file per working tree, never deleted. A project gate that takes the same
# lease cannot run while ``land`` writes the main tree.
LEASE_NAME = "{{PROJECT_NAME}}-gate.lock"
LEASE_TOKEN_ENV = "{{PROJECT_NAME_UPPER}}_GATE_LEASE_TOKEN"
# Windows byte-range locks are mandatory, so the lock sits on one byte far past
# any body; the body stays readable through other handles.
LEASE_LOCK_OFFSET = 2**20
LEASE_BODY_SCHEMA = 1

_LF_CHECKOUT = ("-c", "core.autocrlf=false")
# Every git call here that hashes working-tree bytes runs with this pin: the
# clean filter turns a CRLF working copy of an LF blob back into LF, so a
# CRLF-only rewrite is never captured or refused as a content change. A path
# whose index blob already holds CRLF is not converted (convert.c
# ``has_crlf_in_index``), and ``.gitattributes`` text/eol rules still win.
EOL_PIN = ("-c", "core.autocrlf=true", "-c", "core.safecrlf=false")
_GIT_ENV_DROPPED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
_VENV_ENV_DROPPED = ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
_PY_VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+)")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class _Refusal(Exception):
    """The command refuses; ``lines`` are printed and the exit code is 1."""

    def __init__(self, lines: Sequence[str]) -> None:
        self.lines = list(lines)
        super().__init__("; ".join(self.lines))


class _GitFailure(Exception):
    """A git invocation exited non-zero; nothing after it runs."""

    def __init__(self, subcommand: str, stderr: bytes) -> None:
        self.subcommand = subcommand
        self.stderr = stderr
        super().__init__(f"git {subcommand} failed")


class _CaseRefusal(Exception):
    """The captured tree holds ``paths`` that the disk spells differently."""

    def __init__(self, paths: Sequence[str]) -> None:
        self.paths = list(paths)
        super().__init__(f"{len(self.paths)} path(s) differ only by case")


class _ShapeError(Exception):
    """A main-tree path is a directory, or one of its components is a file."""


@dataclass(frozen=True)
class _Worktree:
    """A listed executor worktree whose manifest and baseline ref were read."""

    path: Path
    main: Path
    slug: str
    ref: str
    links: tuple[str, ...]
    git_dir: Path
    baseline: str


@dataclass
class _Build:
    """What ``create`` has made so far, for the teardown of a refused build."""

    root: Path
    path: Path
    ref: str
    branch: str | None
    config: dict[str, object] = field(default_factory=dict)
    links: list[Path] = field(default_factory=list)
    ref_written: bool = False


class WorktreeConfigError(ValueError):
    """The adopter's ``.agent/credits/worktree.json`` is missing or invalid."""


def load_worktree_config(root: Path | str) -> dict[str, object]:
    """The project parts of a worktree, read from ``<root>/WORKTREE_CONFIG``.

    The file is one JSON object with exactly the keys ``env_files``,
    ``frozen_dirs`` and ``linked_trees`` (lists of strings) and ``venv_build``
    (a non-empty list of strings, or null).

    Raises:
        WorktreeConfigError: the file is missing or unreadable, is not JSON, is
            not an object, has an unknown or a missing key, or a value has the
            wrong type.
    """
    path = Path(root) / WORKTREE_CONFIG
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise WorktreeConfigError(
            f"{WORKTREE_CONFIG}: cannot read ({type(error).__name__})"
        ) from error
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise WorktreeConfigError(f"{WORKTREE_CONFIG}: not JSON ({error})") from error
    if not isinstance(data, dict):
        raise WorktreeConfigError(f"{WORKTREE_CONFIG}: not a JSON object")
    unknown = sorted(set(data) - WORKTREE_CONFIG_KEYS)
    missing = sorted(WORKTREE_CONFIG_KEYS - set(data))
    if unknown or missing:
        raise WorktreeConfigError(
            f"{WORKTREE_CONFIG}: unknown keys {unknown}, missing keys {missing}"
        )
    for key in WORKTREE_CONFIG_LISTS:
        if not _is_str_list(data[key]):
            raise WorktreeConfigError(f"{WORKTREE_CONFIG}: {key} is not a list of strings")
    build = data["venv_build"]
    if build is not None and not (_is_str_list(build) and build):
        raise WorktreeConfigError(
            f"{WORKTREE_CONFIG}: venv_build is not a non-empty list of strings or null"
        )
    return data


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _config(root: Path) -> dict[str, object]:
    """``load_worktree_config`` as a ``worktree_bad:config`` refusal."""
    try:
        return load_worktree_config(root)
    except WorktreeConfigError as error:
        sys.stderr.write(f"{error}\n")
        raise _Refusal(["worktree_bad:config"]) from None


def _strings(config: dict[str, object], key: str) -> list[str]:
    value = config[key]
    return list(value) if isinstance(value, list) else []


# ------------------------------------------------------------- gate lease


class LeaseBusy(RuntimeError):
    """Another process holds this tree's gate lease.

    ``raw`` is the body read through the contender's own handle (never
    written); ``holder`` is its display fields, each None when unknown.
    """

    def __init__(self, path: Path, raw: bytes) -> None:
        self.path = path
        self.raw = raw
        self.holder = _lease_holder_fields(_parse_lease_body(raw))
        super().__init__(f"gate lease busy: {path}")


@dataclass
class GateLease:
    """A held lease: the open handle, its body, and the token env it replaced."""

    path: Path
    fd: int
    body: dict[str, object]
    previous_token: str | None
    released: bool = False


def _lease_path(root: Path | str) -> Path:
    """The lease file of the working tree containing ``root``.

    Raises:
        _GitFailure: ``root`` is not inside a git working tree.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(root),
            check=False,
        )
    except OSError as exc:
        raise _GitFailure("rev-parse", f"cannot run git in {root}: {exc}\n".encode()) from exc
    git_dir = proc.stdout.strip()
    if proc.returncode != 0 or not git_dir:
        raise _GitFailure(
            "rev-parse",
            f"{root} is not in a git working tree (exit {proc.returncode})\n".encode(),
        )
    return Path(git_dir) / LEASE_NAME


def _open_lease_file(path: Path) -> int:
    """Open the lease read-write, creating it, never truncating; not inheritable."""
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOINHERIT", 0)
    )
    return os.open(path, flags, 0o644)


def _lease_lock(fd: int) -> bool:
    """One non-blocking exclusive lock attempt; True when acquired.

    Only lock contention reads as False; any other OSError propagates.
    """
    if sys.platform == "win32":
        os.lseek(fd, LEASE_LOCK_OFFSET, os.SEEK_SET)
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
    if sys.platform == "win32":
        os.lseek(fd, LEASE_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_lease_fd(fd: int) -> bytes:
    """The body as it is now, read through ``fd`` without writing."""
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while total < LEASE_LOCK_OFFSET:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _parse_lease_body(raw: bytes) -> dict[str, object] | None:
    """A lease body dict, or None when ``raw`` is empty, unparseable or mistyped."""
    if not raw:
        return None
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(body, dict) or body.get("schema") != LEASE_BODY_SCHEMA:
        return None
    pid = body.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(body.get("token"), str):
        return None
    return body


def _lease_holder_fields(body: dict[str, object] | None) -> dict[str, object]:
    """``holder_pid``/``run_dir``/``started_utc`` of a body; None where unknown."""
    if body is None:
        return {"holder_pid": None, "run_dir": None, "started_utc": None}
    run_dir = body.get("run_dir")
    started = body.get("started_utc")
    return {
        "holder_pid": body["pid"],
        "run_dir": run_dir if isinstance(run_dir, str) else None,
        "started_utc": started if isinstance(started, str) else None,
    }


def _write_lease_body(lease: GateLease) -> None:
    """Replace the body under the lock this handle holds: truncate, then write."""
    data = json.dumps(lease.body, sort_keys=True).encode("utf-8")
    os.ftruncate(lease.fd, 0)
    os.lseek(lease.fd, 0, os.SEEK_SET)
    view = memoryview(data)
    while view:
        written = os.write(lease.fd, view)
        view = view[written:]


def _acquire_lease(path: Path, *, argv: list[str], source_root: str) -> GateLease:
    """Take the lock on ``path``, write the body, export the token.

    Acquisition is the single kernel lock call; the body is written only after
    it and never decides who holds the lease.

    Raises:
        LeaseBusy: another handle holds the lock. Nothing was written.
    """
    fd = _open_lease_file(path)
    raw = b""
    try:
        locked = _lease_lock(fd)
        if not locked:
            raw = _read_lease_fd(fd)
    except BaseException:
        os.close(fd)
        raise
    if not locked:
        os.close(fd)
        raise LeaseBusy(path, raw)
    lease = GateLease(
        path=path,
        fd=fd,
        body={},
        previous_token=os.environ.get(LEASE_TOKEN_ENV),
    )
    try:
        token = secrets.token_hex(16)
        lease.body = {
            "schema": LEASE_BODY_SCHEMA,
            "pid": os.getpid(),
            "create_time": None,
            "argv": list(argv),
            "run_dir": None,
            "source_root": source_root,
            "snapshot": None,
            "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "token": token,
        }
        _write_lease_body(lease)
        os.environ[LEASE_TOKEN_ENV] = token
    except BaseException:
        _release_lease(lease)
        raise
    return lease


def _release_lease(lease: GateLease) -> None:
    """Truncate the body, unlock, close, and restore the previous token env.

    The file is never deleted: a contender could lock the unlinked file while a
    third process created and locked a new one, giving two holders.
    """
    if lease.released:
        return
    lease.released = True
    try:
        try:
            os.ftruncate(lease.fd, 0)
        finally:
            try:
                _lease_unlock(lease.fd)
            finally:
                os.close(lease.fd)
    finally:
        if lease.previous_token is None:
            os.environ.pop(LEASE_TOKEN_ENV, None)
        else:
            os.environ[LEASE_TOKEN_ENV] = lease.previous_token


# ------------------------------------------------------------ directory links


def _make_dir_link(link: Path, target: Path) -> None:
    """A directory junction on Windows, a directory symlink elsewhere."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def _drop_dir_link(path: Path) -> None:
    """Remove a directory link itself, never what it points at."""
    if sys.platform == "win32" and os.path.isjunction(path):
        os.rmdir(path)
    else:
        os.unlink(path)


# ---------------------------------------------------------------- runners


def _run_git(
    args: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    data: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``git <args>`` in ``cwd`` and return the finished process.

    The inherited ``GIT_DIR``, ``GIT_WORK_TREE`` and ``GIT_INDEX_FILE`` are
    dropped so the call addresses ``cwd``'s own tree; ``env`` is merged on
    top. ``data`` is fed to stdin. Replaceable (tests inject failures here).

    Raises:
        OSError: git is not installed or ``cwd`` is not a directory.
    """
    merged = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROPPED}
    merged.update(env or {})
    argv = ["git", *args]
    if data is None:
        return subprocess.run(
            argv,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=merged,
            check=False,
        )
    return subprocess.run(
        argv, cwd=str(cwd), input=data, capture_output=True, env=merged, check=False
    )


def _main_root_of(worktree: Path) -> Path:
    """The main tree of ``worktree``: the parent of git's common directory.

    For the main tree itself this is the tree's own root.

    Raises:
        _GitFailure: git cannot resolve the common directory.
    """
    common = _git_text(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=worktree
    )
    return Path(common).parent


def _pinned_python(main_root: Path) -> str:
    """The X.Y.Z interpreter version of ``main_root``'s ``.venv`` (PY_PIN_WORKTREE).

    Reads the first ``version_info`` key of ``<main_root>/.venv/pyvenv.cfg``
    (uv writes ``3.12.12``, the stdlib ``venv`` ``3.12.12.final.0``) and
    returns its leading X.Y.Z, so a worktree venv runs the main tree's version.

    Raises:
        _Refusal: ``worktree_bad:python_pin`` when the file is missing or
            unreadable, holds no ``version_info`` key, or its value does not
            start with X.Y.Z.
    """
    refusal = _Refusal(["worktree_bad:python_pin"])
    try:
        text = (main_root / VENV_MARKER).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise refusal from None
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "version_info":
            found = _PY_VERSION_RE.match(value.strip())
            if found is None:
                raise refusal
            return found.group(1)
    raise refusal


def _build_venv(worktree: Path) -> int:
    """Build the worktree's own ``.venv`` with ``venv_build``; return the exit code.

    Editable installs hold absolute paths, so a venv cannot be shared between
    trees. The caller's ``VIRTUAL_ENV`` is dropped so uv targets the worktree.
    A ``uv`` command gets ``--python`` with the main tree's interpreter version,
    so the worktree gate runs the interpreter the main tree runs (PY_PIN_WORKTREE).
    uv's output goes to stderr. Replaceable (tests stub this step).

    Raises:
        _Refusal: ``worktree_bad:python_pin`` (see ``_pinned_python``), or
            ``worktree_bad:config``.
        _GitFailure: git cannot resolve the worktree's main tree.
        OSError: the command is not installed or ``worktree`` is not a directory.
    """
    main = _main_root_of(worktree)
    command = _strings(_config(main), "venv_build")
    if not command:
        return 0
    if command[0] == "uv":
        command += ["--python", _pinned_python(main)]
    env = {k: v for k, v in os.environ.items() if k not in _VENV_ENV_DROPPED}
    proc = subprocess.run(
        command,
        cwd=str(worktree),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=env,
        check=False,
    )
    for stream in (proc.stdout, proc.stderr):
        if stream:
            sys.stderr.write(stream.decode("utf-8", "replace"))
    return proc.returncode


def _git_subcommand(args: Sequence[str]) -> str:
    """The git subcommand of ``args``: the first word after any ``-c k=v`` pair."""
    index = 0
    while index < len(args):
        if args[index] == "-c":
            index += 2
            continue
        return args[index]
    return "git"


def _git(
    args: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    data: bytes | None = None,
) -> bytes:
    """stdout of a git call that must succeed.

    Raises:
        _GitFailure: git exited non-zero.
    """
    proc = _run_git(args, cwd=cwd, env=env, data=data)
    if proc.returncode != 0:
        raise _GitFailure(_git_subcommand(args), proc.stderr or b"")
    return proc.stdout


def _git_text(
    args: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    data: bytes | None = None,
) -> str:
    """Stripped, decoded stdout of a git call that must succeed."""
    return _git(args, cwd=cwd, env=env, data=data).decode("utf-8", "replace").strip()


def _z(data: bytes) -> list[str]:
    """The paths of a NUL-separated git listing."""
    return [p.decode("utf-8", "surrogateescape") for p in data.split(b"\0") if p]


def _say(line: str) -> None:
    """Print one outcome line; characters the stream cannot encode are escaped."""
    encoding = sys.stdout.encoding or "utf-8"
    safe = line.encode(encoding, "backslashreplace").decode(encoding, "replace")
    sys.stdout.write(safe + "\n")
    sys.stdout.flush()


# ------------------------------------------------------------ small helpers


def _is_link(path: Path) -> bool:
    return os.path.islink(path) or os.path.isjunction(path)


def _drop_links(links: Iterable[Path]) -> None:
    """Drop each directory link that still is one; never what it points at."""
    for link in links:
        if _is_link(link):
            _drop_dir_link(link)


def _same_path(left: str | Path, right: str | Path) -> bool:
    a, b = os.path.abspath(left), os.path.abspath(right)
    if os.path.normcase(a) == os.path.normcase(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _rel_arg(parser: argparse.ArgumentParser, flag: str, value: str) -> str:
    """A root-relative posix path from an argument; a usage error otherwise."""
    text = value.replace("\\", "/")
    parts = PurePosixPath(text).parts
    if (
        not text.strip()
        or text.startswith("/")
        or _DRIVE_RE.match(text)
        or ".." in parts
    ):
        parser.error(f"{flag}: {value!r} is not a path relative to the root")
    return PurePosixPath(text).as_posix()


def _prefixes(rel: str) -> list[str]:
    """``rel`` and each of its directories, shortest first."""
    parts = rel.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


# ``mkstemp`` creates its file owner-only; a newly landed file gets the mode an
# ordinary write would give it instead.
NEW_FILE_MODE = 0o644


def _atomic_write(target: Path, data: bytes) -> None:
    """Write ``data`` to ``target`` through a sibling file and one rename.

    An interrupted write therefore leaves the old bytes, never a truncated
    file that a rerun would have to treat as a sibling's edit. The sibling
    file is created exclusively under a fresh name, so the write never
    replaces or deletes a file that someone else put beside ``target``;
    cleanup removes only the file this call created.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".executor-write.tmp"
    )
    scratch = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        if target.is_file():
            shutil.copymode(target, scratch)
        else:
            scratch.chmod(NEW_FILE_MODE)
        os.replace(scratch, target)
    except BaseException as error:
        # copymode can leave the scratch file read-only, which blocks its
        # unlink on Windows; a failed cleanup must not hide ``error``.
        if os.path.lexists(scratch):
            try:
                os.chmod(scratch, stat.S_IWRITE | stat.S_IREAD)
                scratch.unlink()
            except OSError as cleanup:
                error.add_note(
                    f"_atomic_write: the scratch file {scratch} was not removed: "
                    f"{cleanup}"
                )
        raise


def _worktree_git_dir(path: Path) -> Path | None:
    """The git dir of the working tree at ``path``, or None when git has none."""
    if not path.is_dir():
        return None
    proc = _run_git(["rev-parse", "--git-dir"], cwd=path)
    if proc.returncode != 0:
        return None
    text = proc.stdout.decode("utf-8", "replace").strip()
    if not text:
        return None
    found = Path(text)
    return found if found.is_absolute() else path / found


def _listed(root: Path, path: Path) -> bool:
    """True when ``git worktree list`` of ``root``'s repository names ``path``."""
    listing = _git(["worktree", "list", "--porcelain"], cwd=root)
    for line in listing.decode("utf-8", "replace").splitlines():
        if line.startswith("worktree ") and _same_path(line[len("worktree ") :], path):
            return True
    return False


def _read_manifest(path: Path) -> tuple[Path, dict[str, object]] | None:
    """(git dir, manifest) of the worktree at ``path``; None when unusable."""
    git_dir = _worktree_git_dir(path)
    if git_dir is None:
        return None
    try:
        raw = json.loads((git_dir / WORKTREE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    slug, source, links = raw.get("slug"), raw.get("source_root"), raw.get("links")
    if not isinstance(slug, str) or not WORKTREE_SLUG_RE.fullmatch(slug):
        return None
    if not isinstance(source, str) or not os.path.isdir(source):
        return None
    if not isinstance(links, list) or not all(
        isinstance(name, str) and name and ".." not in name.split("/") for name in links
    ):
        return None
    return git_dir, raw


def _baseline(main: Path, ref: str) -> str | None:
    """The tree ``ref`` names, or None when it is missing or not a tree."""
    proc = _run_git(["cat-file", "-t", ref], cwd=main)
    if proc.returncode != 0 or proc.stdout.strip() != b"tree":
        return None
    return _git_text(["rev-parse", "--verify", ref], cwd=main)


def _open_worktree(root: Path, path: Path) -> _Worktree:
    """Resolve a worktree for check, land, sync and remove.

    Raises:
        _Refusal: ``worktree_bad:unlisted``, ``:manifest`` or ``:baseline``,
            in that order.
    """
    if not _listed(root, path):
        raise _Refusal(["worktree_bad:unlisted"])
    found = _read_manifest(path)
    if found is None:
        raise _Refusal(["worktree_bad:manifest"])
    git_dir, manifest = found
    slug = str(manifest["slug"])
    main = Path(os.path.abspath(str(manifest["source_root"])))
    ref = f"{WORKTREE_REF_PREFIX}{slug}"
    baseline = _baseline(main, ref)
    if baseline is None:
        raise _Refusal(["worktree_bad:baseline"])
    links = manifest["links"]
    assert isinstance(links, list)  # _read_manifest validated the shape
    return _Worktree(
        path=path,
        main=main,
        slug=slug,
        ref=ref,
        links=tuple(str(name) for name in links),
        git_dir=git_dir,
        baseline=baseline,
    )


# ----------------------------------------------------------------- capture


def _misspelled(top: Path, names: Iterable[str]) -> list[str]:
    """Tree paths whose exact spelling is absent from their directory listing."""
    listings: dict[str, frozenset[str]] = {}

    def listing(rel_dir: str) -> frozenset[str]:
        if rel_dir not in listings:
            try:
                found = frozenset(os.listdir(top / rel_dir if rel_dir else top))
            except OSError:
                found = frozenset()
            listings[rel_dir] = found
        return listings[rel_dir]

    bad: list[str] = []
    for name in sorted(names):
        parent = ""
        for part in name.split("/"):
            if part not in listing(parent):
                bad.append(name)
                break
            parent = f"{parent}/{part}" if parent else part
    return bad


def _tree_of(path: Path, git_dir: Path, base: str, links: Sequence[str]) -> str:
    """The tree of the worktree's files, captured through a temporary index.

    The index is seeded from ``base``, so every base path keeps its place
    whether or not an ignore rule matches it, and an untracked file enters
    only when it is not ignored. ``links`` are then dropped from the index,
    so a link never enters a tree whatever the ignore rules say: a rule ending
    in ``/`` does not match the symlink that a link is outside Windows, and
    ``git add`` would record it. Plain git, so the repository's own
    end-of-line rules normalise the blobs.

    Raises:
        _CaseRefusal: a path of the tree is spelled differently on disk (a
            case-only rename on a case-insensitive filesystem).
        _GitFailure: a git call failed.
    """
    index = git_dir / TEMP_INDEX
    env = {"GIT_INDEX_FILE": str(index)}
    try:
        if index.exists():
            index.unlink()
        _git(["read-tree", base], cwd=path, env=env)
        _git([*EOL_PIN, "add", "-A", "--", "."], cwd=path, env=env)
        if links:
            drop = ["rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", *links]
            _git(drop, cwd=path, env=env)
        tree = _git_text(["write-tree"], cwd=path, env=env)
    finally:
        if index.exists():
            index.unlink()
    names = _z(_git(["ls-tree", "-r", "-z", "--name-only", tree], cwd=path))
    bad = _misspelled(path, names)
    if bad:
        raise _CaseRefusal(bad)
    return tree


def _blobs(repo: Path, tree: str) -> dict[str, str]:
    """``{path: object id}`` of every entry in ``tree``."""
    result: dict[str, str] = {}
    for record in _git(["ls-tree", "-r", "-z", tree], cwd=repo).split(b"\0"):
        if record:
            meta, _, name = record.partition(b"\t")
            result[name.decode("utf-8", "surrogateescape")] = meta.split()[2].decode(
                "ascii"
            )
    return result


def _check_shape(main: Path, rel: str) -> None:
    """Refuse a main-tree path that cannot hold a file.

    Raises:
        _ShapeError: ``rel`` is a directory, or one of its components is a file.
    """
    prefixes = _prefixes(rel)
    for prefix in prefixes[:-1]:
        component = main / prefix
        if os.path.lexists(component) and not os.path.isdir(component):
            raise _ShapeError(rel)
    if os.path.isdir(main / rel):
        raise _ShapeError(rel)


def _main_blob(main: Path, rel: str) -> str | None:
    """The blob the main tree's file at ``rel`` hashes to; None when absent.

    Raises:
        _ShapeError: see _check_shape.
    """
    _check_shape(main, rel)
    if not os.path.lexists(main / rel):
        return None
    return _added_blob(main, rel, write=False)


def _index_entry(repo: Path, rel: str, env: dict[str, str]) -> tuple[str, str] | None:
    """``(mode, blob)`` of the index entry git reads for ``rel``; None when absent.

    git's CRLF check (``read_blob_data_from_index``) reads ``rel``'s stage 0
    entry, or stage 2 ("ours") in a conflict. A pathspec also matches the
    entries under a directory ``rel/``, which are not ``rel``'s own entry.
    """
    listing = _git(["ls-files", "--stage", "-z", "--", rel], cwd=repo, env=env)
    stages: dict[str, tuple[str, str]] = {}
    for record in listing.split(b"\0"):
        meta, _tab, name = record.partition(b"\t")
        if not record or name.decode("utf-8", "surrogateescape") != rel:
            continue
        mode, blob, stage = meta.decode("ascii").split()
        stages[stage] = (mode, blob)
    return stages.get("0") or stages.get("2")


def _added_blob(repo: Path, rel: str, *, write: bool) -> str:
    """The blob ``git add`` under ``EOL_PIN`` stores for the file ``repo/rel``.

    git keeps a path whose index blob already holds CRLF as it is
    (``has_crlf_in_index``), but ``hash-object`` never reads the index, so
    it would convert that path too and change a committed CRLF file's id. A
    path with an index entry is therefore added to a throwaway index that
    holds only that entry. A link is added to a throwaway index too, so git
    stores its target text as ``add -A`` in ``_tree_of`` does; nothing reads
    through it. Any other path with no entry has nothing to keep and is
    hashed directly, written to the object store only when ``write`` is set
    (the throwaway-index route always writes the blob).

    Raises:
        _GitFailure: a git call fails.
    """
    literal = {"GIT_LITERAL_PATHSPECS": "1"}
    entry = _index_entry(repo, rel, literal)
    if entry is None and not os.path.islink(repo / rel):
        flags = ["-w"] if write else []
        return _git_text(
            [*EOL_PIN, "hash-object", *flags, "--path", rel, "--stdin"],
            cwd=repo,
            data=(repo / rel).read_bytes(),
        )
    with tempfile.TemporaryDirectory(prefix="executor-blob-") as scratch:
        env = {**literal, "GIT_INDEX_FILE": str(Path(scratch).resolve() / "index")}
        if entry is not None:
            cacheinfo = f"{entry[0]},{entry[1]},{rel}"
            _git(["update-index", "--add", "--cacheinfo", cacheinfo], cwd=repo, env=env)
        _git([*EOL_PIN, "add", "-f", "--", rel], cwd=repo, env=env)
        added = _index_entry(repo, rel, env)
    if added is None:
        raise _GitFailure("add", f"{rel} left no index entry".encode())
    return added[1]


# ------------------------------------------------------------------ create


def _linked_trees(root: Path, names: Sequence[str]) -> list[str]:
    """Root-relative directories of the source tree named in ``names``.

    Read from git's ignored listing, which names an ignored directory once
    and never descends it (so neither links nor nested trees are walked).
    """
    entries = _z(
        _git(
            [
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--directory",
                "-z",
            ],
            cwd=root,
        )
    )
    found = {
        entry.rstrip("/")
        for entry in entries
        if entry.endswith("/")
        and entry.rstrip("/").rsplit("/", 1)[-1] in names
        and (root / entry).is_dir()
    }
    return sorted(found)


def _carried_files(root: Path, carries: Sequence[str]) -> list[str]:
    """Expand ``--carry`` paths to the source files they name.

    Raises:
        _Refusal: one ``worktree_bad:carry_missing:<rel>`` per path that names
            no file (absent, or untracked and ignored).
    """
    files: list[str] = []
    missing: list[str] = []
    for rel in carries:
        listed = _z(
            _git(["ls-files", "-co", "--exclude-standard", "-z", "--", rel], cwd=root)
        )
        present = [name for name in listed if (root / name).is_file()]
        if not present:
            missing.append(rel)
        files.extend(name for name in present if name not in files)
    if missing:
        raise _Refusal([f"worktree_bad:carry_missing:{rel}" for rel in missing])
    return files


def _populate(build: _Build, slug: str, carries: Sequence[str]) -> None:
    """Everything ``create`` does after ``git worktree add``.

    Raises:
        _Refusal: bootstrap_dirty, carry_missing, python_pin, venv or case.
        _GitFailure: a git call failed.
        OSError: a copy, link or manifest write failed.
    """
    root, path = build.root, build.path
    config = build.config
    status = _git([*_LF_CHECKOUT, "status", "--porcelain"], cwd=path)
    if status.strip():
        raise _Refusal(["worktree_bad:bootstrap_dirty"])

    carried = _carried_files(root, carries)
    for rel in carried:
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / rel, target)

    copies: list[str] = []
    for rel in _strings(config, "env_files"):
        if (root / rel).is_file():
            (path / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / rel, path / rel)
            copies.append(rel)
    links = _linked_trees(root, _strings(config, "linked_trees"))
    for rel in links:
        _make_dir_link(path / rel, root / rel)
        build.links.append(path / rel)
    for rel in _strings(config, "frozen_dirs"):
        if (root / rel).is_dir():
            shutil.copytree(root / rel, path / rel, symlinks=True, dirs_exist_ok=True)
            copies.append(rel)
    if config["venv_build"] is not None and _build_venv(path) != 0:
        raise _Refusal(["worktree_bad:venv"])

    git_dir = _worktree_git_dir(path)
    if git_dir is None:
        raise _GitFailure("rev-parse", b"the new worktree has no git dir\n")
    try:
        tree = _tree_of(path, git_dir, "HEAD", links)
    except _CaseRefusal as refusal:
        raise _Refusal([f"worktree_bad:case:{rel}" for rel in refusal.paths]) from None
    _git(["update-ref", build.ref, tree], cwd=root)
    build.ref_written = True

    manifest = {
        "source_root": str(root),
        "slug": slug,
        "branch": build.branch,
        "links": links,
        "copies": sorted(copies),
        "carry": carried,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (git_dir / WORKTREE_MANIFEST).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def _teardown(build: _Build) -> None:
    """Remove a half-built worktree: links first, then git's record of it."""
    _drop_links(build.links)
    _git(["worktree", "remove", "--force", str(build.path)], cwd=build.root)
    _git(["worktree", "prune"], cwd=build.root)
    if build.ref_written:
        _git(["update-ref", "-d", build.ref], cwd=build.root)
    if build.branch is not None:
        _git(["branch", "-D", build.branch], cwd=build.root)


def _resolve_base(root: Path, flag: str | None) -> str:
    """The commit ``create`` checks out: ``--base``, the env base, else ``HEAD``.

    Raises:
        _Refusal: ``worktree_bad:base_unknown`` when the base names no commit.
        OSError: git is not installed or ``root`` is not a directory.
    """
    base = flag or os.environ.get(ENV_BASE_COMMIT, "") or "HEAD"
    proc = _run_git(
        ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{base}^{{commit}}"],
        cwd=root,
    )
    commit = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not commit:
        raise _Refusal(["worktree_bad:base_unknown"])
    return commit


def _cmd_create(
    root: Path, ns: argparse.Namespace, parser: argparse.ArgumentParser
) -> int:
    """``create <slug>``: build the worktree, its environment and its baseline."""
    slug: str = ns.slug
    if not WORKTREE_SLUG_RE.fullmatch(slug):
        raise _Refusal(["worktree_bad:slug"])
    carries = [_rel_arg(parser, "--carry", value) for value in ns.carry]
    path = root.parent / f"{root.name}-{slug}"
    if os.path.lexists(path):
        raise _Refusal(["worktree_bad:exists"])
    base = _resolve_base(root, ns.base)
    config = _config(root)

    branch: str | None = ns.branch
    place = ["-b", branch] if branch is not None else ["--detach"]
    _git([*_LF_CHECKOUT, "worktree", "add", *place, str(path), base], cwd=root)
    build = _Build(
        root=root,
        path=path,
        ref=f"{WORKTREE_REF_PREFIX}{slug}",
        branch=branch,
        config=config,
    )
    try:
        _populate(build, slug, carries)
    except _Refusal as refusal:
        for line in refusal.lines:
            _say(line)
        _teardown(build)
        return 1
    except OSError as error:
        _say(f"io_error:{type(error).__name__}:{error.filename}")
        _teardown(build)
        return 1
    except _GitFailure:
        # Nothing after a failed git call runs git again. The links are dropped
        # so that removing the half-built worktree by hand cannot delete
        # through them.
        _drop_links(build.links)
        sys.stderr.write(
            f"half-built worktree left at {path.as_posix()}; remove it with "
            f"`git worktree remove --force` and `git worktree prune`\n"
        )
        raise
    _say(f"worktree_ready:{path.as_posix()}")
    return 0


# ------------------------------------------------------------------- check


def _cmd_check(
    root: Path, ns: argparse.Namespace, parser: argparse.ArgumentParser
) -> int:
    """``check <path>``: validate the environment, never cleanliness."""
    path = Path(os.path.abspath(ns.path))
    wt = _open_worktree(root, path)
    overlay = path / OVERLAY_FILE
    if overlay.is_file() and b"\r" in overlay.read_bytes():
        raise _Refusal(["worktree_bad:overlay_crlf"])
    for name in wt.links:
        if not _is_link(path / name):
            raise _Refusal([f"worktree_bad:link:{name}"])
    config = _config(wt.main)
    if config["venv_build"] is not None and not (path / VENV_MARKER).is_file():
        raise _Refusal(["worktree_bad:venv"])
    for rel in _strings(config, "env_files"):
        if (wt.main / rel).is_file() != (path / rel).is_file():
            raise _Refusal(["worktree_bad:env"])
    _say("worktree_ok")
    return 0


# -------------------------------------------------------------------- land


def _diff_entries(main: Path, base: str, now: str) -> list[tuple[str, str]]:
    """(path, status) of every file that differs between two trees, by path."""
    fields = _z(
        _git(
            ["diff-tree", "-r", "--no-renames", "--name-status", "-z", base, now],
            cwd=main,
        )
    )
    entries = [(fields[i + 1], fields[i]) for i in range(0, len(fields) - 1, 2)]
    return sorted(entries)


def _land_locked(wt: _Worktree) -> int:
    """The landing itself; the caller holds the main tree's gate lease."""
    baseline = _baseline(wt.main, wt.ref)
    if baseline is None:
        raise _Refusal(["worktree_bad:baseline"])
    try:
        now = _tree_of(wt.path, wt.git_dir, baseline, wt.links)
    except _CaseRefusal as refusal:
        raise _Refusal([f"land_fail:case:{rel}" for rel in refusal.paths]) from None
    entries = _diff_entries(wt.main, baseline, now)
    if not entries:
        _say("land_ok:0:0:0")
        return 0

    old_blobs, new_blobs = _blobs(wt.main, baseline), _blobs(wt.main, now)
    refusals: list[str] = []
    plan: list[tuple[str, str, str | None]] = []
    counts = {"A": 0, "M": 0, "D": 0}
    for rel, raw_status in entries:
        status = raw_status if raw_status in ("A", "D") else "M"
        counts[status] += 1
        old, new = old_blobs.get(rel), new_blobs.get(rel)
        try:
            cur = _main_blob(wt.main, rel)
        except _ShapeError:
            refusals.append(f"land_fail:shape:{rel}")
            continue
        if status == "A":
            if cur is not None and cur != new:
                refusals.append(f"land_fail:exists:{rel}")
        elif status == "D":
            if cur is not None and cur != old:
                refusals.append(f"land_fail:changed:{rel}")
        elif cur is None:
            refusals.append(f"land_fail:missing:{rel}")
        elif cur not in (old, new):
            refusals.append(f"land_fail:changed:{rel}")
        plan.append((rel, status, cur))
    if refusals:
        raise _Refusal(refusals)

    for rel, status, cur in plan:
        target = wt.main / rel
        if status == "D":
            if os.path.lexists(target):
                target.unlink()
            continue
        new = new_blobs[rel]
        if cur == new:
            continue
        body = _git(["cat-file", "--filters", f"--path={rel}", new], cwd=wt.main)
        _atomic_write(target, body)
    _git(["update-ref", wt.ref, now], cwd=wt.main)
    _say(f"land_ok:{counts['A']}:{counts['M']}:{counts['D']}")
    return 0


def _cmd_land(
    root: Path, ns: argparse.Namespace, parser: argparse.ArgumentParser
) -> int:
    """``land <path>``: write the worktree's changes onto the main tree."""
    path = Path(os.path.abspath(ns.path))
    wt = _open_worktree(root, path)
    lease_file = _lease_path(wt.main)
    try:
        lease = _acquire_lease(
            lease_file,
            argv=["executor_worktree.py", "land", str(path)],
            source_root=str(wt.main),
        )
    except LeaseBusy as busy:
        holder = busy.holder.get("holder_pid")
        _say(f"land_fail:busy:{holder if holder is not None else 'unknown'}")
        return 1
    try:
        return _land_locked(wt)
    finally:
        _release_lease(lease)


# -------------------------------------------------------------------- sync


def _sync_refusals(wt: _Worktree, rels: Sequence[str]) -> list[str]:
    """Every reason not to sync ``rels``; nothing is written while any exists.

    ``case`` covers a path that would put a second spelling beside one the
    baseline already holds, and a batch that itself names two spellings of
    one path or directory (the first spelling given wins). ``shape`` also
    covers a link at ``rel``: sync writes a regular file, so it cannot carry
    a link.
    """
    paths = set(_blobs(wt.main, wt.baseline))
    known = {prefix for name in paths for prefix in _prefixes(name)}
    folded = {name.casefold() for name in known}
    batch: dict[str, str] = {}
    refusals: list[str] = []
    for rel in rels:
        try:
            _check_shape(wt.main, rel)
        except _ShapeError:
            refusals.append(f"sync_fail:shape:{rel}")
            continue
        if os.path.islink(wt.main / rel):
            refusals.append(f"sync_fail:shape:{rel}")
            continue
        ignored = _run_git(["check-ignore", "-q", "--", rel], cwd=wt.main)
        if ignored.returncode == 0:
            refusals.append(f"sync_fail:ignored:{rel}")
            continue
        if ignored.returncode != 1:
            raise _GitFailure("check-ignore", ignored.stderr or b"")
        prefixes = _prefixes(rel)
        clash = rel not in paths and any(
            prefix not in known and prefix.casefold() in folded for prefix in prefixes
        )
        clash = clash or any(
            batch.get(prefix.casefold(), prefix) != prefix for prefix in prefixes
        )
        if clash:
            refusals.append(f"sync_fail:case:{rel}")
            continue
        for prefix in prefixes:
            batch.setdefault(prefix.casefold(), prefix)
    return refusals


def _sync_one(wt: _Worktree, baseline: str, rel: str) -> str:
    """Refresh ``rel`` in the worktree and the baseline; return the new tree.

    The worktree file is written before the caller moves the ref, so an
    interruption leaves the next ``land`` a no-op for this file.
    """
    source, target = wt.main / rel, wt.path / rel
    index = wt.git_dir / TEMP_INDEX
    env = {"GIT_INDEX_FILE": str(index)}
    if os.path.lexists(source):
        blob = _added_blob(wt.main, rel, write=True)
        body = _git(
            [*_LF_CHECKOUT, "cat-file", "--filters", f"--path={rel}", blob],
            cwd=wt.path,
        )
        _atomic_write(target, body)
        edit = ["update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}"]
    else:
        if os.path.lexists(target):
            target.unlink()
        edit = ["update-index", "--force-remove", "--", rel]
    try:
        if index.exists():
            index.unlink()
        _git(["read-tree", baseline], cwd=wt.path, env=env)
        _git(edit, cwd=wt.path, env=env)
        return _git_text(["write-tree"], cwd=wt.path, env=env)
    finally:
        if index.exists():
            index.unlink()


def _cmd_sync(
    root: Path, ns: argparse.Namespace, parser: argparse.ArgumentParser
) -> int:
    """``sync <path> <rel>...``: refresh shared files from the main tree.

    Refused with ``worktree_bad:base_bound`` while ``CREDITS_BASE_COMMIT`` is
    set: the run's tree stays the admitted base plus its own work.
    """
    if os.environ.get(ENV_BASE_COMMIT):
        raise _Refusal(["worktree_bad:base_bound"])
    path = Path(os.path.abspath(ns.path))
    rels: list[str] = []
    for value in ns.rel:
        rel = _rel_arg(parser, "rel", value)
        if rel not in rels:
            rels.append(rel)
    wt = _open_worktree(root, path)
    refusals = _sync_refusals(wt, rels)
    if refusals:
        raise _Refusal(refusals)
    baseline = wt.baseline
    for rel in rels:
        baseline = _sync_one(wt, baseline, rel)
        _git(["update-ref", wt.ref, baseline], cwd=wt.main)
        _say(f"sync_ok:{rel}")
    return 0


# ------------------------------------------------------------------ remove


def _cmd_remove(
    root: Path, ns: argparse.Namespace, parser: argparse.ArgumentParser
) -> int:
    """``remove <path> [--discard]``: delete a worktree whose work has landed."""
    path = Path(os.path.abspath(ns.path))
    wt = _open_worktree(root, path)
    links = [path / name for name in wt.links]
    for name, link in zip(wt.links, links, strict=True):
        if os.path.lexists(link) and not _is_link(link):
            raise _Refusal([f"worktree_bad:link:{name}"])
    if not ns.discard:
        try:
            now = _tree_of(path, wt.git_dir, wt.baseline, wt.links)
        except _CaseRefusal as refusal:
            raise _Refusal(
                [f"worktree_bad:case:{rel}" for rel in refusal.paths]
            ) from None
        if now != wt.baseline:
            raise _Refusal(["worktree_bad:unlanded"])
    _drop_links(links)
    _git(["worktree", "remove", "--force", str(path)], cwd=wt.main)
    _git(["worktree", "prune"], cwd=wt.main)
    _git(["update-ref", "-d", wt.ref], cwd=wt.main)
    _say(f"worktree_removed:{path.as_posix()}")
    return 0


# -------------------------------------------------------------------- main

_Handler = Callable[[Path, argparse.Namespace, argparse.ArgumentParser], int]
_HANDLERS: dict[str, _Handler] = {
    "create": _cmd_create,
    "check": _cmd_check,
    "land": _cmd_land,
    "sync": _cmd_sync,
    "remove": _cmd_remove,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="executor_worktree.py",
        description="Create, check, land, sync and remove an executor worktree.",
    )
    parser.add_argument(
        "--root",
        default=str(_REPO_ROOT),
        help="the main working tree (default: the repository containing this tool)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="build <root>-<slug> beside the root")
    create.add_argument("slug", help="lowercase letters, digits and dashes")
    create.add_argument("--branch", help="create this branch instead of detaching")
    create.add_argument(
        "--base",
        help=f"the commit to check out (default: ${ENV_BASE_COMMIT}, else HEAD)",
    )
    create.add_argument(
        "--carry",
        action="append",
        default=[],
        metavar="PATH",
        help="root-relative file or directory to copy across (repeatable)",
    )

    check = commands.add_parser("check", help="validate the worktree's environment")
    check.add_argument("path")

    land = commands.add_parser("land", help="write the changes onto the main tree")
    land.add_argument("path")

    sync = commands.add_parser("sync", help="refresh files from the main tree")
    sync.add_argument("path")
    sync.add_argument("rel", nargs="+", help="root-relative file to refresh")

    remove = commands.add_parser("remove", help="delete a landed worktree")
    remove.add_argument("path")
    remove.add_argument(
        "--discard", action="store_true", help="abandon work that has not landed"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand; return the process exit code.

    Raises:
        SystemExit: 2 on a usage error (argparse).
    """
    parser = _parser()
    ns = parser.parse_args(argv)
    root = Path(os.path.abspath(ns.root))
    try:
        return _HANDLERS[ns.command](root, ns, parser)
    except _Refusal as refusal:
        for line in refusal.lines:
            _say(line)
        return 1
    except _GitFailure as failure:
        _say(f"git_error:{failure.subcommand}")
        detail = failure.stderr.decode("utf-8", "replace")
        if detail:
            sys.stderr.write(detail if detail.endswith("\n") else f"{detail}\n")
        return 1
    except OSError as error:
        _say(f"io_error:{type(error).__name__}:{error.filename}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
