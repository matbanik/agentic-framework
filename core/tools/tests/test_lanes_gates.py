"""MEU-785 AC-785.29, .30, .40: gate registration, the deps sequence and ``gate run`` — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.29 (design D:288, §5.8), AC-785.30 (D:289, §10b N-5 D:421) and AC-785.40
(D:288-289 PR-8, D:421, D:369-386), with the boundary rows IP:148-151 and EA-2.

Contracts the tests pin:

- ``lanes.gate_register(worktree) -> entry`` and ``lanes.gate_unregister(entry)``
  write and remove one ``{pid, lease, started, workload}`` item (EA-2) in the
  reserving card's ``gates``. The caller holds the gate lease of the worktree
  (``<git dir of W>/{{PROJECT_NAME}}-gate.lock``, EA-26), as ``tools/lanes.py gate run`` does,
  so the entry names that lease. A pending ``deps`` claim on any card refuses the
  registration with ``Refusal`` reason ``deps_pending``.
- Drained rule: an entry is drained only when its lease is free AND every workload
  process is gone. The tests make each half true on its own with real processes.
- ``lanes.deps_begin(worktree, *, wait_s, poll_s)`` sets the caller's
  ``{kind: deps, state: pending}`` claim, prints ``deps_wait:<lane>:<pid>`` on each
  poll, and sets ``exclusive``, or clears the claim and refuses
  ``deps_drain_timeout:<count>``. The CLI is ``lanes.py deps begin|end --worktree PATH
  [--wait-s N]`` (``N`` integer 0-3600, argparse exit 2).
- ``lanes.py gate run --worktree PATH -- ARGV...`` and its seam
  ``lanes._gate_run(worktree, argv, *, contain=True)``: a refusal prints
  ``refused: <reason>`` and exits 1 (stage-1 contract); the adapter exits with the
  child's code. The exit code of the adapter's ``deps_pending`` refusal is not fixed
  by the plan, so that case pins a nonzero exit and the token.

The adapter, the gate stand-ins and the workload children run on the base
interpreter (``sys._base_executable``): a Windows venv ``python.exe`` is a launcher
that starts the interpreter as a second process, so its Popen pid is not the pid that
a card or a workload records. Every repository is disposable, in ``tmp_path``. The
lane rig is the A-R rig of ``test_lanes_commit.py``; the land candidate comes from the
B-R rig of ``test_lanes_land.py``. The in-process registration of the adopter's
gate script (``validate_codebase.py``, AC-785.29) is tested in the adopter, which
owns that script. Tests reach new symbols at run time. A skipped test
is a Red failure (``red_check.py``), so the POSIX process-group case runs as a branch
of the wrapper-loss test on POSIX hosts. Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import ctypes
import importlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, TextIO

import pytest

from tools.tests import test_lanes_commit as lc
from tools.tests import test_lanes_land as ll

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
LANES = TOOLS / "lanes.py"
BASE_PY = str(getattr(sys, "_base_executable", "") or sys.executable)
SLUG = lc.SLUG
OTHER_SLUG = lc.OTHER_SLUG
PLANS = lc.PLANS
GATE_LOCK = lc.GATE_LOCK
OTHER_GENERATION = "fedcba9876543210"
ENTRY_KEYS = {"pid", "lease", "started", "workload"}
WAIT_S = 0.2
POLL_S = 0.01
CLI_TIMEOUT_S = 120
SETTLE_S = 60.0
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# The A-R lane fixture: one repository on ``main`` and the worktree ``lane/<SLUG>``.
lane = lc.lane

# A gate stand-in: argv = [tools dir, worktree, lease path]. It holds the worktree's
# gate lease, registers, prints ``registered <entry json>`` and, when its stdin
# closes, unregisters, releases and prints ``unregistered``.
REGISTRAR = """
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import lanes
import os_lease

body = json.dumps({"pid": os.getpid(), "argv": ["registrar"]}).encode("utf-8")
lease = os_lease.acquire(Path(sys.argv[3]), wait_s=10.0, body=body)
try:
    entry = lanes.gate_register(Path(sys.argv[2]))
except lanes.Refusal as exc:
    os_lease.release(lease)
    print(f"refused {exc.reason}", flush=True)
    sys.exit(1)
print("registered " + json.dumps(entry), flush=True)
sys.stdin.read()
lanes.gate_unregister(entry)
os_lease.release(lease)
print("unregistered", flush=True)
"""

# A card snapshot: argv = [card path, out file, (echo file, echo text, exit code)].
SNAP = """
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    card = json.load(fh)
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump({"pid": os.getpid(), "card": card}, fh)
if len(sys.argv) > 3:
    with open(sys.argv[3], "w", encoding="utf-8") as fh:
        fh.write(sys.argv[4])
    sys.exit(int(sys.argv[5]))
"""

# A workload sleeper: argv = [pid file, heartbeat file, stop file]. It writes its pid,
# rewrites the heartbeat every 50 ms and ends when the stop file exists (cap 180 s).
SLEEPER = """
import os
import sys
import time

pid_file, beat, stop = sys.argv[1:4]
with open(pid_file + ".tmp", "w", encoding="utf-8") as fh:
    fh.write(str(os.getpid()))
os.replace(pid_file + ".tmp", pid_file)
count = 0
deadline = time.monotonic() + 180
while not os.path.exists(stop) and time.monotonic() < deadline:
    count += 1
    with open(beat, "w", encoding="utf-8") as fh:
        fh.write(str(count))
    time.sleep(0.05)
"""

# The adapter on a host where the job assignment fails: argv = [tools dir, worktree,
# child argv...]; it runs the seam with ``contain=False``.
UNCONTAINED_ADAPTER = """
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import lanes

sys.exit(lanes._gate_run(Path(sys.argv[2]), sys.argv[3:], contain=False))
"""

def _lanes() -> ModuleType:
    return importlib.import_module("tools.lanes")


# ---------------------------------------------------------------------------
# The rig
# ---------------------------------------------------------------------------


def _card_path(common: Path, slug: str) -> Path:
    return common / "lanes" / f"{slug}.json"


def _read_card(common: Path, slug: str) -> dict[str, Any]:
    data = json.loads(_card_path(common, slug).read_text(encoding="utf-8"))
    assert isinstance(data, dict), slug
    return data


def _gates(common: Path, slug: str) -> list[Any]:
    gates = _read_card(common, slug)["gates"]
    assert isinstance(gates, list), gates
    return gates


def _deps_states(card: dict[str, Any]) -> list[str]:
    """The ``state`` of every ``kind: deps`` claim on ``card``."""
    return [
        str(claim.get("state"))
        for claim in card["claims"]
        if isinstance(claim, dict) and claim.get("kind") == "deps"
    ]


def _gate_lease(wt: Path) -> Path:
    """The worktree gate lease (EA-26): ``<git dir of W>/{{PROJECT_NAME}}-gate.lock``."""
    git_dir = lc._git(wt, "rev-parse", "--absolute-git-dir").strip()
    return Path(git_dir).resolve() / GATE_LOCK


def _same_path(a: object, b: Path) -> bool:
    return isinstance(a, str) and bool(a) and Path(a).resolve() == b.resolve()


def _lane_b(lane: lc.Lane, *, claims: list[dict[str, str]] | None = None) -> Path:
    """A second lane worktree on ``lane/<OTHER_SLUG>`` with its card."""
    wt_b = lane.scratch.parent / OTHER_SLUG
    lc._git(lane.main, "worktree", "add", "-q", "-b", f"lane/{OTHER_SLUG}", str(wt_b))
    wt_b = wt_b.resolve()
    lc._put_card(
        lane,
        lc._card(
            lane,
            lane=OTHER_SLUG,
            generation=OTHER_GENERATION,
            worktree=wt_b.as_posix(),
            branch=f"lane/{OTHER_SLUG}",
            plan=f"{PLANS}/{OTHER_SLUG}/",
            owns=[f"src/{OTHER_SLUG}/"],
            claims=list(claims or []),
        ),
    )
    return wt_b


def _two_lanes(lane: lc.Lane, *, claims: list[dict[str, str]] | None = None) -> Path:
    """Card A on ``lane.wt`` and card B (the deps lane) on a second worktree."""
    lc._put_card(lane, lc._card(lane))
    return _lane_b(lane, claims=claims)


def _cli(
    cwd: Path, *args: str, timeout: float = CLI_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    """``lanes.py`` on the base interpreter, with the fixture's clean environment."""
    return subprocess.run(
        [BASE_PY, str(LANES), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=lc._clean_env(),
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )


def _wait_until(
    what: str, ready: Callable[[], bool], timeout_s: float = SETTLE_S
) -> None:
    deadline = time.monotonic() + timeout_s
    while not ready():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.02)


def _kill(pid: int) -> None:
    """End one process only (TerminateProcess on Windows, SIGKILL on POSIX)."""
    if sys.platform == "win32":
        os.kill(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGKILL)


def _win_created(pid: int) -> int | None:
    """The creation time of a running ``pid``, or None when no live process has it."""
    if sys.platform != "win32":
        raise OSError("win32 only")
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
        ctypes.POINTER(wintypes.FILETIME)
    ] * 4
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        if code.value != STILL_ACTIVE:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        k32.CloseHandle(handle)


def _alive(pid: int, created: int | None = None) -> bool:
    """Whether ``pid`` (with its creation time, on Windows) names a live process."""
    if sys.platform == "win32":
        now = _win_created(pid)
        return now is not None and (created is None or now == created)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _group_alive(pgid: int) -> bool:
    if sys.platform == "win32":
        raise OSError("POSIX only")
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _beat(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _beating(path: Path) -> bool:
    """Whether the heartbeat file changes within 0.5 s."""
    first = _beat(path)
    time.sleep(0.5)
    return _beat(path) != first


class _Registrar:
    """A gate stand-in process (``REGISTRAR``) that holds ``wt``'s lease and registers."""

    def __init__(self, wt: Path, err: Path) -> None:
        self.err = err.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [BASE_PY, "-c", REGISTRAR, str(TOOLS), str(wt), str(_gate_lease(wt))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.err,
            text=True,
            encoding="utf-8",
            env=lc._clean_env(),
        )
        assert self.proc.stdout is not None
        self.line = self.proc.stdout.readline().strip()
        self.entry: dict[str, Any] | None = None
        if self.line.startswith("registered "):
            parsed = json.loads(self.line[len("registered ") :])
            assert isinstance(parsed, dict), self.line
            self.entry = parsed

    def registered(self) -> dict[str, Any]:
        if self.entry is None:
            self.close()
            pytest.fail(
                f"the registrar did not register: {self.line!r}; "
                f"stderr: {self.err.name}: {Path(self.err.name).read_text(encoding='utf-8')[-800:]}"
            )
        return self.entry

    def stop(self) -> str:
        """Close stdin (unregister and release); return the rest of stdout."""
        if self.proc.poll() is None and self.proc.stdin is not None:
            self.proc.stdin.close()
        assert self.proc.stdout is not None
        rest = self.proc.stdout.read()
        self.proc.wait(timeout=30)
        return rest

    def kill(self) -> None:
        _kill(self.proc.pid)
        self.proc.wait(timeout=30)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=30)
        self.err.close()


@contextmanager
def _registrar(wt: Path, err: Path) -> Iterator[_Registrar]:
    reg = _Registrar(wt, err)
    try:
        yield reg
    finally:
        reg.close()


class _Sleeper:
    """The file paths of one workload sleeper."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.script = root / "sleeper.py"
        self.script.write_text(SLEEPER, encoding="utf-8")
        self.pid_file = root / "child.pid"
        self.beat = root / "beat.txt"
        self.stop_file = root / "stop"

    def argv(self) -> list[str]:
        return [
            BASE_PY,
            str(self.script),
            str(self.pid_file),
            str(self.beat),
            str(self.stop_file),
        ]

    def pid(self) -> int:
        _wait_until("the sleeper pid", self.pid_file.is_file)
        return int(self.pid_file.read_text(encoding="utf-8"))

    def stop(self) -> None:
        self.stop_file.write_text("stop", encoding="utf-8")


def _start_adapter(
    lane: lc.Lane, sleeper: _Sleeper, log: Path, *, contain: bool
) -> tuple[subprocess.Popen[str], TextIO]:
    """The adapter on ``lane.wt`` around ``sleeper`` (stdout and stderr to ``log``)."""
    out = log.open("w", encoding="utf-8")
    if contain:
        argv = [BASE_PY, str(LANES), "gate", "run", "--worktree", str(lane.wt), "--"]
    else:
        argv = [BASE_PY, "-c", UNCONTAINED_ADAPTER, str(TOOLS), str(lane.wt)]
    proc = subprocess.Popen(
        [*argv, *sleeper.argv()],
        cwd=str(lane.wt),
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env=lc._clean_env(),
    )
    return proc, out


def _registered_entry(lane: lc.Lane, proc: subprocess.Popen[str]) -> dict[str, Any]:
    """Card A's one gate entry once its workload is recorded."""

    def ready() -> bool:
        if proc.poll() is not None:
            return True
        gates = _gates(lane.common, SLUG)
        return len(gates) == 1 and bool(gates[0].get("workload"))

    _wait_until("the adapter's gate entry with its workload", ready)
    assert proc.poll() is None, f"the adapter ended early: {proc.returncode}"
    entry = _gates(lane.common, SLUG)[0]
    assert isinstance(entry, dict), entry
    return entry


def _assert_workload(entry: dict[str, Any], child_pid: int) -> None:
    """The workload of one adapter child: ``{pid, created}`` (Windows) or ``{pgid}``."""
    workload = entry["workload"]
    assert isinstance(workload, list) and len(workload) == 1, workload
    item = workload[0]
    assert isinstance(item, dict), workload
    if sys.platform == "win32":
        assert set(item) == {"pid", "created"}, item
        assert item["pid"] == child_pid, (item, child_pid)
    else:
        assert item == {"pgid": child_pid}, (item, child_pid)


# ---------------------------------------------------------------------------
# AC-785.29 — gate registration API and the drained rule
# ---------------------------------------------------------------------------


def test_gate_register_writes_one_entry_and_unregister_removes_it(
    lane: lc.Lane, tmp_path: Path
) -> None:
    lc._put_card(lane, lc._card(lane))
    with _registrar(lane.wt, tmp_path / "reg.err") as reg:
        entry = reg.registered()
        gates = _gates(lane.common, SLUG)
        assert gates == [entry], gates
        assert set(entry) == ENTRY_KEYS, entry
        assert entry["pid"] == reg.proc.pid, (entry, reg.proc.pid)
        assert _same_path(entry["lease"], _gate_lease(lane.wt)), entry
        assert isinstance(entry["started"], str) and entry["started"], entry
        assert isinstance(entry["workload"], list), entry
        rest = reg.stop()
        assert "unregistered" in rest, rest
    assert _gates(lane.common, SLUG) == []


def test_gate_register_refuses_while_a_deps_claim_is_pending(lane: lc.Lane) -> None:
    lanes = _lanes()
    _two_lanes(lane, claims=[{"kind": "deps", "state": "pending"}])
    before = _card_path(lane.common, SLUG).read_bytes()
    with pytest.raises(lanes.Refusal) as caught:
        lanes.gate_register(lane.wt)
    assert caught.value.reason == "deps_pending", caught.value
    assert _card_path(lane.common, SLUG).read_bytes() == before


def test_a_gate_whose_lease_is_held_is_not_drained(
    lane: lc.Lane, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lanes = _lanes()
    wt_b = _two_lanes(lane)
    with _registrar(lane.wt, tmp_path / "reg.err") as reg:
        entry = reg.registered()
        start = time.monotonic()
        with pytest.raises(lanes.Refusal) as caught:
            lanes.deps_begin(wt_b, wait_s=WAIT_S, poll_s=POLL_S)
        elapsed = time.monotonic() - start
        assert (
            "deps_drain_timeout:1"
            in f"{caught.value.reason}:{caught.value.detail} {caught.value}"
        ), caught.value
        assert WAIT_S <= elapsed < 30, elapsed
        waits = [
            line
            for line in capsys.readouterr().out.splitlines()
            if line.strip() == f"deps_wait:{SLUG}:{entry['pid']}"
        ]
        assert len(waits) >= 2, waits
        assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == [], "claim cleared"
        assert _gates(lane.common, SLUG) == [entry], "a live gate is not cleaned"
        reg.stop()


def test_a_dead_gate_with_a_free_lease_and_no_workload_is_drained_and_cleaned(
    lane: lc.Lane, tmp_path: Path
) -> None:
    lanes = _lanes()
    wt_b = _two_lanes(lane)
    with _registrar(lane.wt, tmp_path / "reg.err") as reg:
        reg.registered()
        reg.kill()
    assert len(_gates(lane.common, SLUG)) == 1, "the killed gate left its entry"
    lanes.deps_begin(wt_b, wait_s=WAIT_S, poll_s=POLL_S)
    assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == ["exclusive"]
    assert _gates(lane.common, SLUG) == [], "the dead entry is cleaned"


# ---------------------------------------------------------------------------
# AC-785.30 — the deps sequence
# ---------------------------------------------------------------------------


def test_deps_begin_with_no_wait_makes_one_check_and_no_sleep(
    lane: lc.Lane,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lanes = _lanes()
    wt_b = _two_lanes(lane)
    with _registrar(lane.wt, tmp_path / "reg.err") as reg:
        entry = reg.registered()
        slept: list[float] = []
        real_sleep = time.sleep
        monkeypatch.setattr(time, "sleep", slept.append)
        try:
            with pytest.raises(lanes.Refusal) as caught:
                lanes.deps_begin(wt_b, wait_s=0, poll_s=POLL_S)
        finally:
            monkeypatch.setattr(time, "sleep", real_sleep)
        assert (
            "deps_drain_timeout:1"
            in f"{caught.value.reason}:{caught.value.detail} {caught.value}"
        )
        assert slept == [], slept
        waits = [
            line
            for line in capsys.readouterr().out.splitlines()
            if line.strip() == f"deps_wait:{SLUG}:{entry['pid']}"
        ]
        assert len(waits) == 1, waits
        assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == []
        reg.stop()


def test_deps_cli_wait_bound_is_an_integer_from_0_to_3600(lane: lc.Lane) -> None:
    wt_b = _two_lanes(lane)
    before = _card_path(lane.common, OTHER_SLUG).read_bytes()
    for bad in ("3601", "-1", "1.5", "x"):
        proc = _cli(wt_b, "deps", "begin", "--worktree", str(wt_b), "--wait-s", bad)
        assert proc.returncode == 2, (bad, proc.returncode, proc.stdout, proc.stderr)
        assert _card_path(lane.common, OTHER_SLUG).read_bytes() == before, bad
    lc._ok(_cli(wt_b, "deps", "begin", "--worktree", str(wt_b), "--wait-s", "0"))
    assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == ["exclusive"]
    lc._ok(_cli(wt_b, "deps", "end", "--worktree", str(wt_b)))
    assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == []


def test_deps_begin_is_pending_while_it_drains_then_exclusive_until_end(
    lane: lc.Lane, tmp_path: Path
) -> None:
    lanes = _lanes()
    wt_b = _two_lanes(lane)
    with _registrar(lane.wt, tmp_path / "reg.err") as reg:
        entry = reg.registered()
        out = (tmp_path / "deps.out").open("w", encoding="utf-8")
        begin = subprocess.Popen(
            [
                BASE_PY,
                str(LANES),
                "deps",
                "begin",
                "--worktree",
                str(wt_b),
                "--wait-s",
                "60",
            ],
            cwd=str(wt_b),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=lc._clean_env(),
        )
        try:
            _wait_until(
                "the pending deps claim",
                lambda: (
                    begin.poll() is not None
                    or _deps_states(_read_card(lane.common, OTHER_SLUG)) == ["pending"]
                ),
            )
            assert begin.poll() is None, (tmp_path / "deps.out").read_text(
                encoding="utf-8"
            )
            with pytest.raises(lanes.Refusal) as caught:
                lanes.gate_register(lane.wt)
            assert caught.value.reason == "deps_pending", caught.value
            reg.stop()
            assert begin.wait(timeout=60) == 0, (tmp_path / "deps.out").read_text(
                encoding="utf-8"
            )
        finally:
            if begin.poll() is None:
                begin.kill()
                begin.wait(timeout=30)
            out.close()
    text = (tmp_path / "deps.out").read_text(encoding="utf-8")
    assert f"deps_wait:{SLUG}:{entry['pid']}" in text, text
    assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == ["exclusive"]
    # While exclusive: an unrelated gate is refused; the owner's worktree registers.
    with pytest.raises(lanes.Refusal) as unrelated:
        lanes.gate_register(lane.wt)
    assert unrelated.value.reason == "deps_pending", unrelated.value
    own = lanes.gate_register(wt_b)
    assert _gates(lane.common, OTHER_SLUG) == [own]
    lanes.gate_unregister(own)
    assert _gates(lane.common, OTHER_SLUG) == []
    lc._ok(_cli(wt_b, "deps", "end", "--worktree", str(wt_b)))
    assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == []
    again = lanes.gate_register(lane.wt)
    lanes.gate_unregister(again)
    assert _gates(lane.common, SLUG) == []


# ---------------------------------------------------------------------------
# AC-785.40 — the gate adapter ``lanes.py gate run``
# ---------------------------------------------------------------------------


def test_gate_run_in_an_unreserved_worktree_starts_nothing(
    lane: lc.Lane, tmp_path: Path
) -> None:
    marker = tmp_path / "started.txt"
    argv = [BASE_PY, "-c", "import sys; open(sys.argv[1], 'w').write('x')", str(marker)]
    # No card at all, then the main tree (which no card reserves) beside card A.
    proc = _cli(lane.wt, "gate", "run", "--worktree", str(lane.wt), "--", *argv)
    lc._refused(proc, "gate_unreserved")
    assert not marker.exists()
    lc._put_card(lane, lc._card(lane))
    proc = _cli(lane.main, "gate", "run", "--worktree", str(lane.main), "--", *argv)
    lc._refused(proc, "gate_unreserved")
    assert not marker.exists()
    assert _gates(lane.common, SLUG) == []


def test_gate_run_refuses_deps_pending_before_it_starts_anything(
    lane: lc.Lane, tmp_path: Path
) -> None:
    _two_lanes(lane, claims=[{"kind": "deps", "state": "pending"}])
    marker = tmp_path / "started.txt"
    argv = [BASE_PY, "-c", "import sys; open(sys.argv[1], 'w').write('x')", str(marker)]
    proc = _cli(lane.wt, "gate", "run", "--worktree", str(lane.wt), "--", *argv)
    assert proc.returncode != 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "deps_pending" in proc.stdout, (proc.stdout, proc.stderr)
    assert not marker.exists()
    assert _gates(lane.common, SLUG) == []


def test_gate_run_needs_an_argv(lane: lc.Lane, tmp_path: Path) -> None:
    lc._put_card(lane, lc._card(lane))
    marker = tmp_path / "started.txt"
    argv = [BASE_PY, "-c", "import sys; open(sys.argv[1], 'w').write('x')", str(marker)]
    lc._ok(_cli(lane.wt, "gate", "run", "--worktree", str(lane.wt), "--", *argv))
    assert marker.read_text(encoding="utf-8") == "x", "a non-empty argv runs"
    proc = _cli(lane.wt, "gate", "run", "--worktree", str(lane.wt), "--")
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert _gates(lane.common, SLUG) == []


def test_gate_run_exits_with_the_child_code_and_empties_gates(
    lane: lc.Lane, tmp_path: Path
) -> None:
    lc._put_card(lane, lc._card(lane))
    snap_file = tmp_path / "snap.json"
    echo = tmp_path / "echo.txt"
    text = "a && b | c > d"
    proc = _cli(
        lane.wt,
        "gate",
        "run",
        "--worktree",
        str(lane.wt),
        "--",
        BASE_PY,
        "-c",
        SNAP,
        str(_card_path(lane.common, SLUG)),
        str(snap_file),
        str(echo),
        text,
        "3",
    )
    assert proc.returncode == 3, (proc.returncode, proc.stdout, proc.stderr)
    assert echo.read_text(encoding="utf-8") == text, "the argv runs with no shell"
    snap = json.loads(snap_file.read_text(encoding="utf-8"))
    gates = snap["card"]["gates"]
    assert isinstance(gates, list) and len(gates) == 1, gates
    entry = gates[0]
    assert set(entry) == ENTRY_KEYS, entry
    assert entry["pid"] != snap["pid"], "the entry names the adapter, not the child"
    assert isinstance(entry["lease"], str) and entry["lease"], entry
    _assert_workload(entry, snap["pid"])
    assert _gates(lane.common, SLUG) == []


def test_gate_run_in_a_land_candidate_registers_in_the_lane_card(
    tmp_path: Path,
) -> None:
    land = ll._one(tmp_path)
    ll._ready_tree(ll._prepare(land))
    candidates = ll._candidates(land)
    assert len(candidates) == 1, candidates
    candidate = candidates[0]
    snap_file = tmp_path / "snap.json"
    proc = ll._cli(
        land,
        "gate",
        "run",
        "--worktree",
        str(candidate),
        "--",
        sys.executable,
        "-c",
        SNAP,
        str(land.card_path),
        str(snap_file),
        cwd=candidate,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    snap = json.loads(snap_file.read_text(encoding="utf-8"))
    assert snap["card"]["lane"] == land.slug
    gates = snap["card"]["gates"]
    assert isinstance(gates, list) and len(gates) == 1, gates
    assert set(gates[0]) == ENTRY_KEYS, gates
    assert land.card()["gates"] == []


def _wrapper_loss_orphan(
    lane: lc.Lane, wt_b: Path, root: Path, *, contain: bool
) -> None:
    """Kill only the adapter: the live child keeps the entry until it ends."""
    sleeper = _Sleeper(root)
    log = root / "adapter.log"
    adapter, out = _start_adapter(lane, sleeper, log, contain=contain)
    child_pid: int | None = None
    try:
        entry = _registered_entry(lane, adapter)
        child_pid = sleeper.pid()
        assert entry["pid"] == adapter.pid, (entry, adapter.pid)
        _assert_workload(entry, child_pid)
        _kill(adapter.pid)
        adapter.wait(timeout=30)
        assert _alive(child_pid), "the uncontained child outlives the adapter"
        if sys.platform != "win32":
            assert _group_alive(child_pid), (
                "the child's process group outlives the adapter"
            )
        assert _beating(sleeper.beat), "the child still beats"
        proc = _cli(wt_b, "deps", "begin", "--worktree", str(wt_b), "--wait-s", "0")
        lc._refused(proc, "deps_drain_timeout:1")
        assert f"gate_orphan:{SLUG}:{entry['pid']}" in proc.stdout, proc.stdout
        assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == [], "claim cleared"
        if not contain and sys.platform == "win32":
            out.flush()
            assert "gate_uncontained:" in log.read_text(encoding="utf-8")
        sleeper.stop()
        _wait_until("the child to end", lambda: not _alive(child_pid or -1))
        lc._ok(_cli(wt_b, "deps", "begin", "--worktree", str(wt_b), "--wait-s", "0"))
        assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == ["exclusive"]
        assert _gates(lane.common, SLUG) == [], "the drained entry is cleaned"
        lc._ok(_cli(wt_b, "deps", "end", "--worktree", str(wt_b)))
    finally:
        sleeper.stop()
        if adapter.poll() is None:
            adapter.kill()
            adapter.wait(timeout=30)
        if child_pid is not None and _alive(child_pid):
            _kill(child_pid)
        out.close()


def test_a_killed_uncontained_adapter_leaves_an_orphan_until_the_child_ends(
    lane: lc.Lane, tmp_path: Path
) -> None:
    wt_b = _two_lanes(lane)
    # (1) the job assignment fails (``contain=False``).
    _wrapper_loss_orphan(lane, wt_b, tmp_path / "uncontained", contain=False)
    if os.name == "posix":
        # (3) POSIX: the adapter's own process group, which has no kill-on-close.
        _wrapper_loss_orphan(lane, wt_b, tmp_path / "group", contain=True)


@pytest.mark.skipif(
    sys.platform != "win32", reason="the kill-on-close Job Object is Windows only"
)
def test_a_killed_contained_adapter_takes_its_child_down(
    lane: lc.Lane, tmp_path: Path
) -> None:
    wt_b = _two_lanes(lane)
    sleeper = _Sleeper(tmp_path / "contained")
    adapter, out = _start_adapter(lane, sleeper, tmp_path / "adapter.log", contain=True)
    child_pid: int | None = None
    try:
        entry = _registered_entry(lane, adapter)
        child_pid = sleeper.pid()
        _assert_workload(entry, child_pid)
        created = _win_created(child_pid)
        assert created is not None, "the child runs"
        _kill(adapter.pid)
        adapter.wait(timeout=30)
        deadline = time.monotonic() + SETTLE_S
        exclusive = False
        while time.monotonic() < deadline:
            proc = _cli(wt_b, "deps", "begin", "--worktree", str(wt_b), "--wait-s", "0")
            if proc.returncode == 0:
                assert not _alive(child_pid, created), "exclusive while the child lives"
                assert not _beating(sleeper.beat), "exclusive while the heartbeat moves"
                exclusive = True
                break
            lc._refused(proc, "deps_drain_timeout:1")
            assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == []
            time.sleep(0.1)
        assert exclusive, "deps begin never reached exclusive after the adapter died"
        assert _deps_states(_read_card(lane.common, OTHER_SLUG)) == ["exclusive"]
        assert _gates(lane.common, SLUG) == []
    finally:
        sleeper.stop()
        if adapter.poll() is None:
            adapter.kill()
            adapter.wait(timeout=30)
        if child_pid is not None and _alive(child_pid):
            _kill(child_pid)
        out.close()
