"""Plan-local checks for the USB kit usability plan (WP-K0).

Modes (one per run):
  --backup                        copy the four uncommitted kit files and their diff to $RECEIPTS_DIR/uk2-backup/
  --baseline                      save the refcheck and sanitize failure lines and HEAD
  --pytest <receipt> --exit <n>   the pytest gate, with the KNOWN_FAILURES entries
  --red <receipt>... --acs <n,..> every listed AC has a failing test body in the red receipts
  --gates                         no new gate failure, AC-to-test coverage, then the Privacy scan
  --privacy                       the Privacy scan alone
  --state                         print the state id
  hub                             the hub checks of row 11a
  live <name> --mode fresh|rerun --receive <receipt>   the live checks of WP-K7
  --selftest                      each mode's pass and fail cases on temporary files

The only git commands are `git diff` and `git status`. Nothing here changes the index or the working tree.
The Privacy scan prints a file, a line number and a class number, never the text it matched.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit

PLAN = Path(__file__).resolve().parent
REPO = PLAN.parents[3]
SLUG = PLAN.name

KNOWN_FAILURES = (
    "scripts/tests/test_fleet_agent.py::test_ac38_the_skills_hold_the_member_route_and_the_billing_rule",
    "scripts/tests/test_instantiate_credits_nonwin.py::test_no_retained_python_file_needs_a_removed_tool",
    "scripts/tests/test_instantiate_credits_nonwin.py::test_retained_python_tests_collect",
)

# The known issue that each excused test belongs to (EA-2 added the last two).
KNOWN_ISSUE = {
    KNOWN_FAILURES[0]: "FLEET-AC38-BILLING-LINE-PIN",
    KNOWN_FAILURES[1]: "FLEET-INSTALL-RETAINED-CREDITS-TESTS",
    KNOWN_FAILURES[2]: "FLEET-INSTALL-RETAINED-CREDITS-TESTS",
}

BACKUP_FILES = (
    ".agent/fleet/install-usb/README.md",
    ".agent/fleet/usb/README.md",
    ".agent/fleet/usb/setup-unix.sh",
    ".agent/fleet/usb/setup-windows.ps1",
)

FILES_MODIFIED = (
    ".agent/fleet/usb/setup-unix.sh",
    ".agent/fleet/usb/setup-windows.ps1",
    ".agent/fleet/usb/fleet_usb.py",
    ".agent/fleet/usb/Setup Windows.cmd",
    ".agent/fleet/usb/Setup Linux.desktop",
    ".agent/fleet/usb/Setup Mac.command",
    ".agent/fleet/usb/README.md",
    ".agent/fleet/install-usb/README.md",
    ".agent/fleet/bootstrap.md",
    "core/MANIFEST.md",
    "scripts/tests/test_fleet_usb.py",
    "scripts/tests/SetupWindowsUsb.Tests.ps1",
    ".agent/context/known-issues.yaml",
    ".agent/context/known-issues.md",
    f"docs/execution/plans/{SLUG}/",
)

CLOSEOUT_FILES = (
    f".agent/context/handoffs/{SLUG}-handoff.md",
    f"docs/execution/reflections/{SLUG}-reflection.md",
    f".agent/context/handoffs/{SLUG}-plan-critical-review.md",
    f".agent/context/handoffs/{SLUG}-implementation-critical-review.md",
)
METRICS = "docs/execution/metrics.md"

# Every AC of the plan except AC-22 (proved by --gates and --selftest) and the live AC-23 to AC-26.
COVERED_ACS = tuple(range(1, 22))
PYTEST_FILE = "scripts/tests/test_fleet_usb.py"
PESTER_FILE = "scripts/tests/SetupWindowsUsb.Tests.ps1"

GUIDE_URL = "https://matbanik.info/hobbies/systems/posts/rustdesk-server-on-windows-without-docker/"
GUIDE_HOST = urlsplit(GUIDE_URL).hostname or ""

FIREWALL_RULE = "Fleet USB receive 8771"
RUSTDESK_KEY = re.compile(r"[A-Za-z0-9+/=]{40,64}\Z")
RUN_ID = re.compile(r"[a-z0-9]{8,32}\Z")
TOOLS = ("git", "python", "pwsh", "uv", "claude", "codex")


class CheckError(Exception):
    """A check failed; the message says which and why."""


# ----------------------------------------------------------------------------------------------- helpers

def receipts_dir() -> Path:
    value = os.environ.get("RECEIPTS_DIR", "").strip()
    if not value:
        raise CheckError("RECEIPTS_DIR is not set")
    path = Path(value)
    path.mkdir(parents=True, exist_ok=True)
    return path


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def read_text(path: Path) -> str:
    """A receipt or a scope file, as text. PowerShell 5 receipts are UTF-16; pwsh 7 receipts are UTF-8.
    Colour escapes are removed: Pester colours its failure lines even in a file."""
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return ANSI.sub("", data.decode("utf-16", errors="replace"))
    return ANSI.sub("", data.decode("utf-8-sig", errors="replace"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(cmd: list[str], cwd: Path = REPO, timeout: int = 600) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout, env=env)
    except FileNotFoundError as e:
        raise CheckError(f"{cmd[0]} is not on PATH: {e}") from None
    except subprocess.TimeoutExpired:
        raise CheckError(f"{' '.join(cmd[:3])} gave no answer in {timeout} s") from None


def out_text(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout or b"").decode("utf-8", errors="replace") + (proc.stderr or b"").decode("utf-8", errors="replace")


def git(args: list[str], cwd: Path = REPO) -> bytes:
    if args[0] not in ("diff", "status"):
        raise CheckError(f"git {args[0]} is not allowed here")
    proc = run(["git", *args], cwd=cwd)
    if proc.returncode != 0:
        raise CheckError(f"git {args[0]} exit {proc.returncode}: {out_text(proc).strip()[-300:]}")
    return proc.stdout


def head_commit(cwd: Path = REPO) -> str:
    """HEAD's commit id, read through `git status` (porcelain v2 prints `# branch.oid`)."""
    for line in git(["status", "--porcelain=v2", "--branch", "--untracked-files=no"], cwd).decode().splitlines():
        if line.startswith("# branch.oid "):
            return line.split()[2]
    raise CheckError("git status printed no branch.oid")


# ----------------------------------------------------------------------------------------------- --backup

def backup(root: Path, dest: Path, diff: Callable[[list[str]], bytes]) -> list[str]:
    """Copy BACKUP_FILES from root to dest with their diff and a sha256 list. Returns the report lines."""
    report: list[str] = []
    sources = {rel: root / rel for rel in BACKUP_FILES}
    missing = [rel for rel, path in sources.items() if not path.is_file()]
    if missing:
        raise CheckError(f"kit files missing: {', '.join(missing)}")
    existing = [rel for rel in BACKUP_FILES if (dest / rel).exists()]
    if existing:
        changed = [rel for rel in existing if (dest / rel).read_bytes() != sources[rel].read_bytes()]
        if changed:
            raise CheckError("the backup exists and differs from the working tree for "
                             f"{', '.join(changed)}; it is not replaced (D-1)")
        if len(existing) == len(BACKUP_FILES) and (dest / "baseline.diff").is_file() and (dest / "sha256.txt").is_file():
            report.append(f"backup unchanged: {len(existing)} files match the working tree")
            return report
    for rel, path in sources.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (dest / "baseline.diff").write_bytes(diff(["diff", "HEAD", "--", *BACKUP_FILES]))
    lines = [f"{sha256_bytes((dest / rel).read_bytes())}  {rel}" for rel in BACKUP_FILES]
    (dest / "sha256.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report += [f"backed up {rel}" for rel in BACKUP_FILES]
    report.append(f"baseline.diff: {(dest / 'baseline.diff').stat().st_size} bytes")
    report += lines
    return report


def cmd_backup() -> int:
    dest = receipts_dir() / "uk2-backup"
    for line in backup(REPO, dest, lambda a: git(a)):
        print(line)
    print(f"backup: {dest}")
    return 0


# ----------------------------------------------------------------------------------------------- gate lines

FAIL_TOKEN = re.compile(r"^\s*([A-Z][A-Z]+(?:-[A-Z]+)*)\s{2,}(\S.*)$")
LINE_REF = re.compile(r"(\.[A-Za-z0-9]+):[0-9][0-9,\-–]*")
COUNT = re.compile(r"\b\d+ (failure|hit|file|site)\(s\)")


def failure_lines(text: str) -> set[str]:
    """The failure lines of a refcheck or sanitize run, with line numbers and counts removed."""
    found: set[str] = set()
    in_verify = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or set(line.strip()) <= set("=-"):
            in_verify = False
            continue
        norm = COUNT.sub(r"N \1(s)", LINE_REF.sub(r"\1", line.strip()))
        if "VERIFY FAILED:" in line:
            found.add(norm)
            in_verify = True
            continue
        m = FAIL_TOKEN.match(line)
        if m and ":" not in m.group(1):
            found.add(norm)
            continue
        if in_verify and raw.startswith("      "):
            found.add(re.sub(r"^\d+\s+", "", norm))
            continue
        in_verify = False
    return found


def gate_outputs() -> dict:
    result = {}
    for key, cmd in (("refcheck", [sys.executable, "scripts/refcheck.py"]),
                     ("sanitize", [sys.executable, "scripts/sanitize.py", "--verify"])):
        proc = run(cmd)
        text = out_text(proc)
        result[key] = {"exit": proc.returncode, "lines": sorted(failure_lines(text))}
    return result


def cmd_baseline() -> int:
    data = {"head": head_commit(), **gate_outputs()}
    path = receipts_dir() / "uk2-gates-baseline.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"HEAD {data['head']}")
    for key in ("refcheck", "sanitize"):
        print(f"{key}: exit {data[key]['exit']}, {len(data[key]['lines'])} failure lines saved")
    print(f"baseline: {path}")
    return 0


def new_gate_lines(baseline: dict, current: dict) -> list[str]:
    new: list[str] = []
    for key in ("refcheck", "sanitize"):
        old = set(baseline.get(key, {}).get("lines", []))
        new += [f"{key}: {line}" for line in current[key]["lines"] if line not in old]
    return new


# ----------------------------------------------------------------------------------------------- --pytest

SUMMARY = re.compile(
    r"^=*\s*(?:(?:\d+ (?:failed|passed|skipped|deselected|xfailed|xpassed|warnings?|errors?|rerun)(?:, )?)+|no tests ran)"
    r"(?: in [0-9.]+s(?: \([0-9:]+\))?)?\s*=*$")
FAILED = re.compile(r"^FAILED (\S+?)(?: - .*)?$")
PASSED = re.compile(r"^PASSED (\S+)")


def summary_line(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and SUMMARY.match(lines[-1]):
        return lines[-1]
    return None


def pytest_gate(text: str, code: int, known: Iterable[str] = KNOWN_FAILURES) -> list[str]:
    """Returns the report lines; raises CheckError when the gate fails."""
    known = tuple(known)
    report: list[str] = []
    summary = summary_line(text)
    if summary is None:
        raise CheckError("the receipt does not end with pytest's summary line")
    if re.search(r"\berrors?\b", summary):
        raise CheckError(f"the summary counts an error: {summary}")
    lines = text.splitlines()
    if any(line.startswith("ERROR ") for line in lines):
        raise CheckError("the receipt has an ERROR line")
    failed = [m.group(1) for m in map(FAILED.match, lines) if m]
    passed = {m.group(1) for m in map(PASSED.match, lines) if m}
    if code not in (0, 1):
        raise CheckError(f"pytest exit {code} (only 0 or 1 can pass)")
    if code == 0 and failed:
        raise CheckError("pytest exit 0 with a FAILED line")
    if code == 1 and not failed:
        raise CheckError("pytest exit 1 with no FAILED line")
    other = [t for t in failed if t not in known]
    if other:
        raise CheckError("failures outside KNOWN_FAILURES: " + ", ".join(other))
    for test in known:
        if test in passed:
            raise CheckError(f"a known failure now passes, so its excuse must go: {test}")
        if test not in failed:
            raise CheckError(f"a known failure did not run: {test}")
        report.append(f"excused known failure: {test} (KI {KNOWN_ISSUE.get(test, 'unlisted')})")
    report.append(f"pytest gate PASS: exit {code}; {summary}")
    return report


def cmd_pytest(receipt: Path, code: int) -> int:
    for line in pytest_gate(read_text(receipt), code):
        print(line)
    return 0


# ----------------------------------------------------------------------------------------------- --red

PESTER_LINE = re.compile(r"^\s*\[[-+!?]\] ")
# Normal verbosity prints "[-] <Describe>.<It name>"; the Describe text holds no colon.
PESTER_FAIL = re.compile(r"^\s*\[-\] (?:[^:]*?\.)?AC-0?(\d+):")
PESTER_GATE = re.compile(r"Pester gate (?:PASS|FAIL):.*\bFailedBlocks=(\d+) FailedContainers=(\d+)")
PYTEST_FAIL = re.compile(r"^FAILED \S+::test_ac(\d{2})_")


def is_pester(text: str) -> bool:
    return "Pester gate" in text or "self-check" in text or any(PESTER_LINE.match(x) for x in text.splitlines())


def red_check(receipts: dict[str, str], acs: list[int]) -> list[str]:
    """receipts maps a receipt name to its text. Returns the report; raises CheckError when it fails."""
    counted: dict[int, int] = {ac: 0 for ac in acs}
    report: list[str] = []
    for name, text in receipts.items():
        lines = text.splitlines()
        if is_pester(text):
            gates = [PESTER_GATE.search(x) for x in lines]
            gates = [g for g in gates if g]
            if not gates:
                raise CheckError(f"{name}: no Pester gate summary line (the run did not finish)")
            blocks, containers = int(gates[-1].group(1)), int(gates[-1].group(2))
            if blocks or containers:
                raise CheckError(f"{name}: FailedBlocks={blocks} FailedContainers={containers}; "
                                 "a setup, teardown or discovery failure is not a red test body")
            hits = [int(m.group(1)) for m in map(PESTER_FAIL.match, lines) if m]
        else:
            summary = summary_line(text) or ""
            if (any(x.startswith("ERROR ") for x in lines) or "ERROR collecting" in text
                    or re.search(r"\berrors?\b", summary)):
                raise CheckError(f"{name}: a fixture, setup, teardown or collection error; the red set is refused")
            hits = [int(m.group(1)) for m in map(PYTEST_FAIL.match, lines) if m]
        for ac in hits:
            if ac in counted:
                counted[ac] += 1
    missing = [ac for ac, n in counted.items() if n == 0]
    for ac in acs:
        report.append(f"AC-{ac}: {counted[ac]} failing test(s)")
    if missing:
        raise CheckError("no failing test body for " + ", ".join(f"AC-{ac}" for ac in missing))
    report.append(f"red PASS: {', '.join(f'AC-{ac}' for ac in acs)}")
    return report


def cmd_red(paths: list[Path], acs: list[int]) -> int:
    for line in red_check({str(p): read_text(p) for p in paths}, acs):
        print(line)
    return 0


# ----------------------------------------------------------------------------------------------- coverage

def ac_coverage(pytest_text: str, pester_text: str, acs: Iterable[int] = COVERED_ACS) -> list[int]:
    """The ACs with neither a test_acNN_ function nor an It 'AC-N: block."""
    have = {int(n) for n in re.findall(r"^\s*def test_ac(\d{2})_", pytest_text, re.M)}
    have |= {int(n) for n in re.findall(r"""^\s*It\s+['"]AC-0?(\d+):""", pester_text, re.M)}
    return [ac for ac in acs if ac not in have]


# ----------------------------------------------------------------------------------------------- privacy

IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d]|\.\d)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
WIN_USER = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s'\"`<>|,;)\]]+)", re.I)
NIX_USER = re.compile(r"(?<![\w.~:])/(?:home|Users)/([^/\s'\"`<>|,;)\]]+)")
MAC = re.compile(r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}(?![0-9A-Fa-f:-])")
ALLOWED_NETS = tuple(ipaddress.ip_network(n) for n in
                     ("127.0.0.0/8", "169.254.7.7/32", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))
# 169.254.7.7 is the one link-local address the fleet_usb tests use; any other link-local address is a hit.
USER_NAMES_OK = {"public", "shared", "default"}


def ip_hit(text: str) -> bool:
    for m in IPV4.finditer(text):
        try:
            addr = ipaddress.IPv4Address(m.group(1))
        except ValueError:
            continue
        if str(addr) == "0.0.0.0" or any(addr in net for net in ALLOWED_NETS):
            continue
        return True
    return False


def email_hit(text: str) -> bool:
    return any("noreply" not in m.group(0).lower() for m in EMAIL.finditer(text))


def placeholder(name: str) -> bool:
    return (name.startswith(("<", "$", "%", "~", "{", "*")) or name.lower() in USER_NAMES_OK)


def user_path_hit(text: str) -> bool:
    return any(not placeholder(m.group(1)) for rx in (WIN_USER, NIX_USER) for m in rx.finditer(text))


def deny_terms(home: Path, env: dict, git_values: Callable[[], list[str]], local_user: str, host: str) -> set[str]:
    terms: set[str] = set()
    ssh = home / ".ssh"
    members = ssh / "fleet_members.json"
    if members.is_file():
        try:
            data = json.loads(members.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                terms |= {str(k) for k in data}
        except ValueError:
            pass
    pending, seen = [ssh / "config"], set()
    while pending:
        cfg = pending.pop()
        if cfg in seen or not cfg.is_file():
            continue
        seen.add(cfg)
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*(Host|Include)\s+(.*)", line, re.I)
            if not m:
                continue
            for word in m.group(2).split():
                if m.group(1).lower() == "include":
                    p = Path(os.path.expanduser(word))
                    pending.append(p if p.is_absolute() else ssh / p)
                elif not any(c in word for c in "*?!"):
                    terms.add(word)
    for var in ("FLEET_INBOX", "FLEET_USB_FOLDER"):
        folder = env.get(var)
        if not folder:
            continue
        for rec in Path(folder, "members").glob("*.json"):
            terms.add(rec.stem)
            try:
                data = json.loads(read_text(rec))
            except ValueError:
                continue
            if isinstance(data, dict):
                for key in ("name", "rustdesk_id"):
                    if data.get(key):
                        terms.add(str(data[key]))
                for addr in data.get("addresses") or []:
                    if isinstance(addr, str):
                        terms.add(addr)
                if isinstance(data.get("host_key"), str):
                    terms |= set(data["host_key"].split()[1:2])
    terms.add(host)
    terms.add(local_user)
    for value in git_values():
        if "@" in value and "noreply" in value.lower():
            continue
        terms.add(value)
    if GUIDE_HOST:
        terms.add(GUIDE_HOST)
    return {t.strip() for t in terms if t and len(t.strip()) >= 2}


def real_git_values() -> list[str]:
    values = []
    for key in ("user.name", "user.email"):
        proc = subprocess.run(["git", "config", "--get", key], capture_output=True, text=True, cwd=REPO)
        if proc.returncode == 0 and proc.stdout.strip():
            values.append(proc.stdout.strip())
    return values


def deny_pattern(terms: set[str]) -> re.Pattern | None:
    if not terms:
        return None
    alts = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9_])(?:{alts})(?![A-Za-z0-9_])", re.I)


def scan_lines(lines: Iterable[tuple[int, str]], deny: re.Pattern | None) -> list[tuple[int, int]]:
    hits = []
    for number, line in lines:
        line = line.replace(GUIDE_URL, " ")
        checks = (ip_hit(line), email_hit(line), user_path_hit(line), bool(MAC.search(line)),
                  bool(deny and deny.search(line)))
        hits += [(number, cls) for cls, hit in enumerate(checks, start=1) if hit]
    return hits


def scope_files(root: Path) -> tuple[list[Path], list[str]]:
    files, skipped = [], []
    for rel in FILES_MODIFIED + CLOSEOUT_FILES:
        path = root / rel
        if rel.endswith("/"):
            if path.is_dir():
                files += sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
            else:
                skipped.append(rel)
        elif path.is_file():
            files.append(path)
        else:
            skipped.append(rel)
    return files, skipped


def privacy_scan(root: Path, deny: re.Pattern | None) -> tuple[list[str], list[str]]:
    """Returns (hit lines, skipped scope files). A hit line names a file, a line number and a class."""
    files, skipped = scope_files(root)
    out: list[str] = []
    for path in files:
        text = read_text(path)
        for number, cls in scan_lines(enumerate(text.splitlines(), start=1), deny):
            out.append(f"{path.relative_to(root).as_posix()}:{number}: class {cls}")
    metrics = root / METRICS
    if metrics.is_file():
        rows = [(n, x) for n, x in enumerate(read_text(metrics).splitlines(), start=1) if SLUG in x]
        out += [f"{METRICS}:{n}: class {c}" for n, c in scan_lines(rows, deny)]
    else:
        skipped.append(METRICS)
    return out, skipped


def cmd_privacy() -> int:
    terms = deny_terms(Path.home(), dict(os.environ), real_git_values, getpass.getuser(), socket.gethostname())
    hits, skipped = privacy_scan(REPO, deny_pattern(terms))
    for rel in skipped:
        print(f"privacy: not there yet, skipped: {rel}")
    print(f"privacy: {len(terms)} deny terms read at run time")
    for hit in hits:
        print(f"PRIVACY HIT {hit}")
    if hits:
        print(f"privacy FAIL: {len(hits)} hit(s)")
        return 1
    print("privacy PASS: no hit")
    return 0


# ----------------------------------------------------------------------------------------------- --gates

def cmd_gates() -> int:
    failed = False
    base_path = receipts_dir() / "uk2-gates-baseline.json"
    if not base_path.is_file():
        raise CheckError(f"no baseline at {base_path}; run --baseline first")
    baseline = json.loads(base_path.read_text(encoding="utf-8"))
    current = gate_outputs()
    new = new_gate_lines(baseline, current)
    for line in new:
        print(f"NEW GATE FAILURE {line}")
    print(f"gates: refcheck exit {current['refcheck']['exit']}, sanitize exit {current['sanitize']['exit']}, "
          f"{len(new)} new failure line(s) against HEAD {baseline.get('head')}")
    failed |= bool(new)
    pytest_text = read_text(REPO / PYTEST_FILE) if (REPO / PYTEST_FILE).is_file() else ""
    pester_text = read_text(REPO / PESTER_FILE) if (REPO / PESTER_FILE).is_file() else ""
    missing = ac_coverage(pytest_text, pester_text)
    print("coverage: " + ("every AC 1-21 has a test" if not missing else
                          "no test for " + ", ".join(f"AC-{ac}" for ac in missing)))
    failed |= bool(missing)
    failed |= cmd_privacy() != 0
    print("gates FAIL" if failed else "gates PASS")
    return 1 if failed else 0


# ----------------------------------------------------------------------------------------------- --state

def state_id(head: str, entries: list[tuple[str, str]]) -> str:
    h = hashlib.sha256(head.encode())
    for path, digest in sorted(entries):
        h.update(f"\n{path}\0{digest}".encode())
    return h.hexdigest()


def status_paths(raw: bytes) -> list[str]:
    """Paths of `git status --porcelain -z`; a rename gives its new path."""
    parts = raw.decode("utf-8", errors="replace").split("\0")
    paths, i = [], 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":
            i += 1
    return paths


def in_files_modified(path: str) -> bool:
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in FILES_MODIFIED)


def in_state(path: str) -> bool:
    """A Files Modified path, except task.md: its status marks change after H1-2 and are no tested input (EA-13)."""
    return in_files_modified(path) and path != f"docs/execution/plans/{SLUG}/task.md"


def cmd_state() -> int:
    head = head_commit()
    entries = []
    for path in status_paths(git(["status", "--porcelain", "-z", "--untracked-files=all"])):
        if not in_state(path):
            continue
        full = REPO / path
        entries.append((path, sha256_bytes(full.read_bytes()) if full.is_file() else "deleted"))
    print(f"state {state_id(head, entries)} (HEAD {head}, {len(entries)} changed paths)")
    return 0


# ----------------------------------------------------------------------------------------------- hub

def hub_checks(firewall: Callable[[], str], key_file: str | None, host: str | None,
               connect: Callable[[str, int], bool]) -> list[tuple[str, bool]]:
    results = []
    try:
        rules = json.loads(firewall() or "null")
    except ValueError:
        rules = None
    rules = rules if isinstance(rules, list) else [rules] if isinstance(rules, dict) else []
    ok = any(str(r.get("Enabled")) == "True" and str(r.get("Direction")) == "Inbound"
             and str(r.get("Action")) == "Allow" and str(r.get("Protocol")).upper() == "TCP"
             and "8771" in [str(p) for p in (r.get("LocalPort") or [])] for r in rules)
    results.append((f"firewall rule '{FIREWALL_RULE}' allows inbound TCP 8771", ok))
    key_ok = False
    if key_file and Path(key_file).is_file():
        lines = [x.strip() for x in read_text(Path(key_file)).splitlines() if x.strip()]
        key_ok = len(lines) == 1 and bool(RUSTDESK_KEY.match(lines[0]))
    results.append(("FLEET_RUSTDESK_KEY_FILE holds one RustDesk key", key_ok))
    results.append(("TCP 21116 answers at FLEET_RUSTDESK_HOST", bool(host) and connect(host, 21116)))
    return results


def real_firewall() -> str:
    script = (
        f"$n = '{FIREWALL_RULE}'; "
        "$r = @(Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue) + "
        "@(Get-NetFirewallRule -Name $n -ErrorAction SilentlyContinue); "
        "@($r | Where-Object { $_ } | ForEach-Object { $p = $_ | Get-NetFirewallPortFilter; "
        "[pscustomobject]@{ Enabled = [string]$_.Enabled; Direction = [string]$_.Direction; "
        "Action = [string]$_.Action; Protocol = [string]$p.Protocol; LocalPort = @($p.LocalPort | ForEach-Object { [string]$_ }) } }) "
        "| ConvertTo-Json -Compress -Depth 3 -AsArray")
    proc = run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script], timeout=120)
    return (proc.stdout or b"").decode("utf-8", errors="replace").strip()


def tcp_connect(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def cmd_hub() -> int:
    results = hub_checks(real_firewall, os.environ.get("FLEET_RUSTDESK_KEY_FILE"),
                         os.environ.get("FLEET_RUSTDESK_HOST"), tcp_connect)
    for label, ok in results:
        print(f"{'pass' if ok else 'FAIL'}: {label}")
    return 0 if all(ok for _, ok in results) else 1


# ----------------------------------------------------------------------------------------------- live

RECEIVE_LINE = re.compile(r"^(?P<name>[a-z0-9][a-z0-9-]*) .*\brun_id=(?P<run>[a-z0-9]{8,32})\s*$")
RECEIVED = re.compile(r"^received (\d+)\s*$")


def receive_run_id(text: str, name: str) -> str:
    lines = [x.strip() for x in text.splitlines()]
    counts = [int(m.group(1)) for m in map(RECEIVED.match, lines) if m]
    if not counts or counts[-1] < 1:
        raise CheckError("the receive receipt took no record")
    runs = [m.group("run") for m in map(RECEIVE_LINE.match, lines) if m and m.group("name") == name]
    if not runs:
        raise CheckError(f"the receive receipt has no summary line for {name}")
    return runs[-1]


SshRunner = Callable[[str, str], tuple[int, str]]


def real_ssh(name: str, command: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(["ssh", name, command], capture_output=True, timeout=90)
    except subprocess.TimeoutExpired:
        return 124, "no answer in 90 s"
    except FileNotFoundError:
        return 127, "ssh is not on PATH"
    return proc.returncode, out_text(proc)


def live_checks(name: str, mode: str, receive_text: str, inbox: Path, import_text: str, ssh: SshRunner,
                password_file: Path, state_file: Path) -> list[str]:
    """Raises CheckError at the first failed check; returns the report lines when all pass."""
    report: list[str] = []
    run_id = receive_run_id(receive_text, name)
    report.append(f"receive: a record for {name} with run_id {run_id}")
    rec_path = inbox / "members" / f"{name}.json"
    if not rec_path.is_file():
        raise CheckError(f"no inbox record members/{name}.json")
    record = json.loads(read_text(rec_path))
    if record.get("run_id") != run_id:
        raise CheckError("the inbox record's run_id is not the one this receive took (a stale record)")
    for key, want in (("v", 2), ("final", True), ("ok", True)):
        if record.get(key) != want:
            failed = [s.get("step") for s in record.get("steps", []) if s.get("status") == "failed"]
            raise CheckError(f"record {key} is {record.get(key)!r}, not {want!r}; failed steps: {failed}")
    report.append("record: v 2, final, ok")
    hit = [x for x in import_text.splitlines() if x.startswith(f"{name}:") and "full access" in x
           and "without full access" not in x]
    if not hit:
        raise CheckError(f"import did not report full access for {name}")
    report.append("import: full access")
    for tool in TOOLS:
        candidates = ("python", "python3") if tool == "python" else (tool,)
        for cand in candidates:
            code, out = ssh(name, f"{cand} --version")
            first = next((x.strip() for x in out.splitlines() if x.strip()), "")
            if code == 0 and first:
                report.append(f"tool {cand}: {first[:120]}")
                break
        else:
            raise CheckError(f"tool {tool} gave no version over SSH without a login shell")
    pw_sha = None
    if record.get("gui"):
        if not record.get("rustdesk_id"):
            raise CheckError("a gui member without rustdesk_id")
        if not password_file.is_file():
            raise CheckError("the hub has no RustDesk password file for this member")
        if os.name == "posix" and stat.S_IMODE(password_file.stat().st_mode) != 0o600:
            raise CheckError("the RustDesk password file is not mode 600")
        pw_sha = sha256_bytes(password_file.read_bytes())
        report.append(f"rustdesk: id set, password file present")
    windows = record.get("os") == "windows"
    count_cmd = ("(Get-Content -LiteralPath (Join-Path $env:ProgramData 'ssh\\administrators_authorized_keys') "
                 "| Where-Object { $_.Trim() }).Count") if windows else "grep -c . ~/.ssh/authorized_keys"
    code, out = ssh(name, count_cmd)
    digits = re.findall(r"^\s*(\d+)\s*$", out, re.M)
    if code != 0 or not digits:
        raise CheckError("could not count the member's authorized key lines")
    key_lines = int(digits[-1])
    report.append(f"authorized key lines: {key_lines}")
    if mode == "fresh":
        state_file.write_text(json.dumps({"run_id": run_id, "password_sha256": pw_sha, "key_lines": key_lines},
                                         indent=2) + "\n", encoding="utf-8")
        report.append(f"state saved: {state_file.name}")
        return report
    if not state_file.is_file():
        raise CheckError("no saved fresh state for a rerun")
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    if saved.get("run_id") == run_id:
        raise CheckError("the rerun's run_id equals the fresh run's")
    if saved.get("password_sha256") != pw_sha:
        raise CheckError("the RustDesk password file changed")
    if saved.get("key_lines") != key_lines:
        raise CheckError(f"the authorized key line count changed ({saved.get('key_lines')} -> {key_lines})")
    if windows:
        code, out = ssh(name, "[Environment]::GetEnvironmentVariable('Path', 'User')")
        entries = [p.strip().rstrip("\\").lower() for p in out.strip().split(";") if p.strip()]
        n = sum(1 for p in entries if p.endswith("\\.local\\bin"))
        if code != 0 or n != 1:
            raise CheckError(f"the User Path holds .local\\bin {n} times, not once")
        report.append("User Path: .local\\bin once")
    report.append("rerun: new run_id, password and key lines unchanged")
    return report


def cmd_live(name: str, mode: str, receive: Path, import_receipt: Path | None) -> int:
    inbox = os.environ.get("FLEET_INBOX")
    if not inbox:
        raise CheckError("FLEET_INBOX is not set")
    if import_receipt is None:
        import_receipt = receive.with_name(receive.name.replace("uk2-receive-", "uk2-import-"))
    state = receipts_dir() / f"uk2-live-state-{name}.json"
    report = live_checks(name, mode, read_text(receive), Path(inbox), read_text(import_receipt), real_ssh,
                         Path.home() / ".ssh" / f"{name}-rustdesk-password.txt", state)
    for line in report:
        print(line)
    print(f"live PASS ({mode})")
    return 0


# ----------------------------------------------------------------------------------------------- --selftest

def selftest() -> int:
    results: list[tuple[str, bool]] = []

    def expect(label: str, fn: Callable[[], object], passes: bool) -> None:
        try:
            fn()
            got = True
        except CheckError:
            got = False
        results.append((label, got == passes))

    count = len(KNOWN_FAILURES)
    known = KNOWN_FAILURES[0]
    other = "scripts/tests/test_other.py::test_x"
    every = "".join(f"FAILED {k} - AssertionError\n" for k in KNOWN_FAILURES)
    rest = "".join(f"FAILED {k} - AssertionError\n" for k in KNOWN_FAILURES[1:])
    good = f"..F\nPASSED {other}\n{every}{count} failed, 2 passed in 1.00s\n"
    expect("--pytest excuses every known failure", lambda: pytest_gate(good, 1), True)
    expect("--pytest refuses another failure",
           lambda: pytest_gate(f"{every}FAILED {other} - y\n{count + 1} failed, 1 passed in 1.0s\n", 1), False)
    expect("--pytest fails when a known failure passes",
           lambda: pytest_gate(f"PASSED {known}\n{rest}{count - 1} failed, 3 passed in 1.0s\n", 1), False)
    expect("--pytest fails when a known failure did not run",
           lambda: pytest_gate(f"{rest}{count - 1} failed, 3 passed in 1.0s\n", 1), False)
    expect("--pytest refuses exit 2", lambda: pytest_gate(good, 2), False)
    expect("--pytest refuses an ERROR line",
           lambda: pytest_gate(f"ERROR {other} - fixture\n{every}{count} failed, 1 passed in 1s\n", 1), False)
    expect("--pytest refuses an error in the summary",
           lambda: pytest_gate(f"{every}{count} failed, 1 passed, 1 error in 1.0s\n", 1), False)
    expect("--pytest refuses a receipt without its summary", lambda: pytest_gate(every, 1), False)

    red_ok = "FAILED scripts/tests/test_fleet_usb.py::test_ac01_record - AttributeError: module has no attribute\n" \
             "PASSED scripts/tests/test_fleet_usb.py::test_ac01_refusal\n1 failed, 1 passed in 1.0s\n"
    expect("--red counts a failing test body", lambda: red_check({"r": red_ok}, [1]), True)
    expect("--red names an AC with no failure", lambda: red_check({"r": red_ok}, [1, 3]), False)
    expect("--red refuses fixture ERROR lines",
           lambda: red_check({"r": "ERROR scripts/tests/test_fleet_usb.py::test_ac01_x - fixture\n"
                                   "1 error in 1.0s\n"}, [1]), False)
    expect("--red refuses a collection error",
           lambda: red_check({"r": red_ok, "c": "ERROR collecting scripts/tests/test_fleet_usb.py\n"
                                               "1 error in 1.0s\n"}, [1]), False)
    pester_red = "  [-] AC-2: writes the record 10ms (9ms|1ms)\n  [+] AC-2: refuses 5ms\n" \
                 "Pester gate FAIL: Result=Failed Passed=1 Failed=1 FailedBlocks={b} FailedContainers=0 Skipped=0 Uncovered=0\n"
    expect("--red counts a Pester test body", lambda: red_check({"p": pester_red.format(b=0)}, [2]), True)
    expect("--red refuses a Pester receipt with FailedBlocks=1",
           lambda: red_check({"p": pester_red.format(b=1)}, [2]), False)
    expect("--red refuses a Pester receipt with no gate line",
           lambda: red_check({"p": "  [-] AC-2: x 1ms\n"}, [2]), False)
    described = "[-] setup-windows.ps1 Invoke-Setup.AC-5: a failing body, it says AC-3: inside 1ms\n" \
                "Pester gate FAIL: Result=Failed Passed=0 Failed=1 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0\n"
    expect("--red counts a Pester failure printed with its Describe name",
           lambda: red_check({"p": described}, [5]), True)
    expect("--red does not count an AC named inside the test text",
           lambda: red_check({"p": described}, [3]), False)
    with tempfile.TemporaryDirectory(prefix="uk2-ansi-") as tmp:
        coloured = Path(tmp) / "coloured.txt"
        coloured.write_bytes(("\x1b[91m" + described.splitlines()[0] + "\x1b[0m\n" + described.splitlines()[1] + "\n").encode())
        expect("--red reads a receipt with colour escapes", lambda: red_check({"p": read_text(coloured)}, [5]), True)

    expect("coverage finds every AC", lambda: _raise_if(ac_coverage(
        "".join(f"def test_ac{n:02d}_x():\n" for n in range(1, 22) if n not in (2, 5)),
        "It 'AC-2: a' {}\nIt 'AC-5: b' {}\n")), True)
    expect("coverage names a missing AC",
           lambda: _raise_if(ac_coverage("def test_ac01_x():\n", "")), False)

    base = {"refcheck": {"lines": ["UNRESOLVED  a.md  ->  b.md"]}, "sanitize": {"lines": []}}
    cur_same = {"refcheck": {"lines": sorted(failure_lines("UNRESOLVED  a.md:12  ->  b.md\n"))},
                "sanitize": {"lines": []}}
    cur_new = {"refcheck": {"lines": sorted(failure_lines("UNRESOLVED  a.md:9  ->  b.md\nUNRESOLVED  c.md:1  ->  d.md\n"))},
               "sanitize": {"lines": []}}
    expect("--gates ignores a moved line number", lambda: _raise_if(new_gate_lines(base, cur_same)), True)
    expect("--gates finds a new failure line", lambda: _raise_if(new_gate_lines(base, cur_new)), False)

    with tempfile.TemporaryDirectory(prefix="uk2-selftest-") as tmp:
        t = Path(tmp)
        # Privacy: one planted hit per class, each found; the guide URL passes; the same host elsewhere is found.
        home = t / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "fleet_members.json").write_text(json.dumps({"selftest-member-zz": {}}), encoding="utf-8")
        (home / ".ssh" / "config").write_text("Include fleet_config\n", encoding="utf-8")
        (home / ".ssh" / "fleet_config").write_text("Host selftest-host-qq\n", encoding="utf-8")
        inbox = t / "inbox"
        (inbox / "members").mkdir(parents=True)
        (inbox / "members" / "selftest-rec-yy.json").write_text(
            json.dumps({"name": "selftest-rec-yy", "rustdesk_id": "987654321",
                        "addresses": ["fe80::5e1f:7e57", ".".join(["169", "254", "33", "44"])]}), encoding="utf-8")
        terms = deny_terms(home, {"FLEET_INBOX": str(inbox)}, lambda: ["Selftest Gituser"], "selftestacct", "SELFTESTHUB")
        deny = deny_pattern(terms)
        planted = {
            1: "x " + ".".join(["10", "20", "30", "40"]) + " y",
            2: "mail " + "someone" + "@" + "example.org",
            3: "C:" + "\\Users\\" + "alice" + "\\x",
            4: "mac " + ":".join(["0a"] * 6),
            5: "see selftest-member-zz here",
        }
        for cls, line in planted.items():
            found = [c for _, c in scan_lines([(1, line)], deny)]
            results.append((f"privacy finds a planted class {cls} hit", cls in found))
        for label, line in (("an SSH config Host", "selftest-host-qq"), ("an inbox rustdesk_id", "id 987654321"),
                            ("the git name", "by selftest gituser"), ("the hub host", "on selftesthub"),
                            ("the account", "as selftestacct"),
                            ("an inbox IPv6 address", "addr fe80::5e1f:7e57"),
                            ("an inbox link-local address", "addr " + ".".join(["169", "254", "33", "44"])),
                            ("a link-local address that is not the fixture", "x " + ".".join(["169", "254", "1", "2"]))):
            results.append((f"privacy finds {label}", bool(scan_lines([(1, line)], deny))))
        clean = ["0.0.0.0 and 127.0.0.1 and " + ".".join(["192", "0", "2", "7"]),
                 "fixture " + ".".join(["169", "254", "7", "7"]),
                 "a/b noreply" + "@" + "users.noreply.github.com",
                 "C:" + "\\Users\\" + "<name>" + " and /home/$USER and /Users/Shared",
                 "guide " + GUIDE_URL]
        for line in clean:
            results.append((f"privacy passes a clean line ({line[:14]}...)", not scan_lines([(1, line)], deny)))
        other_path = "https://" + GUIDE_HOST + "/other/page/"
        results.append(("privacy finds the guide host on another path", bool(scan_lines([(1, other_path)], deny))))

        # Backup: copies, then refuses to replace a backup that differs from the working tree.
        root, dest = t / "repo", t / "backup"
        for rel in BACKUP_FILES:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(f"orig {rel}\n", encoding="utf-8")
        fake_diff = lambda a: b"diff --git a b\n"
        expect("--backup copies the four files", lambda: backup(root, dest, fake_diff), True)
        results.append(("--backup wrote sha256.txt", (dest / "sha256.txt").is_file()))
        expect("--backup reruns on an unchanged tree", lambda: backup(root, dest, fake_diff), True)
        (root / BACKUP_FILES[2]).write_text("changed by row 2\n", encoding="utf-8")
        expect("--backup refuses to replace a differing backup", lambda: backup(root, dest, fake_diff), False)
        results.append(("--backup kept the human's copy",
                        (dest / BACKUP_FILES[2]).read_text(encoding="utf-8").startswith("orig")))

        # State id: stable under order, changed by bytes.
        a = state_id("h", [("x", "1"), ("y", "2")])
        results.append(("--state is order independent", a == state_id("h", [("y", "2"), ("x", "1")])))
        results.append(("--state changes with a file", a != state_id("h", [("x", "1"), ("y", "3")])))
        results.append(("--state reads renames",
                        status_paths(b"R  new.md\0old.md\0?? a b.txt\0") == ["new.md", "a b.txt"]))

        results.append(("--state leaves out task.md only",
                        not in_state(f"docs/execution/plans/{SLUG}/task.md")
                        and in_state(f"docs/execution/plans/{SLUG}/check_kit.py")
                        and in_state(f"docs/execution/plans/{SLUG}/implementation-plan.md")
                        and in_state(".agent/fleet/usb/fleet_usb.py")))

        # Hub: pass and fail cases, on loopback only.
        key = t / "key.txt"
        key.write_text("A" * 43 + "=\n", encoding="utf-8")
        rule = json.dumps([{"Enabled": "True", "Direction": "Inbound", "Action": "Allow", "Protocol": "TCP",
                            "LocalPort": ["8771"]}])
        res = hub_checks(lambda: rule, str(key), "h", lambda h, p: True)
        results.append(("hub passes a good rule, key and port", all(ok for _, ok in res)))
        res = hub_checks(lambda: rule.replace("True", "False"), str(key), "h", lambda h, p: True)
        results.append(("hub fails a disabled rule", not res[0][1]))
        key.write_text("short\n", encoding="utf-8")
        res = hub_checks(lambda: rule, str(key), "h", lambda h, p: False)
        results.append(("hub fails a bad key and a closed port", not res[1][1] and not res[2][1]))
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            results.append(("hub connect sees a loopback listener", tcp_connect("127.0.0.1", srv.getsockname()[1])))

        # Live: pass, stale record, zero records, rerun with the fresh run_id.
        name, run1, run2 = "selftest-m", "abcd1234efgh5678", "zz99yy88xx77ww66"
        lin = t / "linbox"
        (lin / "members").mkdir(parents=True)
        rec = {"v": 2, "run_id": run1, "final": True, "ok": True, "os": "linux", "gui": True,
               "rustdesk_id": "123456789", "steps": []}
        (lin / "members" / f"{name}.json").write_text(json.dumps(rec), encoding="utf-8")
        pw = t / "pw.txt"
        pw.write_bytes(b"x")
        if os.name == "posix":
            pw.chmod(0o600)
        state = t / "state.json"
        receive_ok = f"{name} linux ok rustdesk_id=123456789 run_id={run1}\nreceived 1\n"
        imp = f"{name}: ok, delivery sent, ssh {name} -> u@h, full access\n"
        ssh_ok = lambda n, c: (0, "3\n" if "authorized_keys" in c else "tool 1.0\n")
        expect("live passes a fresh run", lambda: live_checks(name, "fresh", receive_ok, lin, imp, ssh_ok, pw, state), True)
        expect("live refuses a stale inbox record",
               lambda: live_checks(name, "fresh", receive_ok.replace(run1, run2), lin, imp, ssh_ok, pw, t / "s2.json"),
               False)
        expect("live refuses a receipt that took zero records",
               lambda: live_checks(name, "fresh", "received 0\n", lin, imp, ssh_ok, pw, t / "s3.json"), False)
        expect("live refuses a rerun with the fresh run_id",
               lambda: live_checks(name, "rerun", receive_ok, lin, imp, ssh_ok, pw, state), False)
        rec2 = dict(rec, run_id=run2)
        (lin / "members" / f"{name}.json").write_text(json.dumps(rec2), encoding="utf-8")
        expect("live passes a rerun with a new run_id",
               lambda: live_checks(name, "rerun", receive_ok.replace(run1, run2), lin, imp, ssh_ok, pw, state), True)
        ssh_more = lambda n, c: (0, "4\n" if "authorized_keys" in c else "tool 1.0\n")
        expect("live refuses a rerun that added a key line",
               lambda: live_checks(name, "rerun", receive_ok.replace(run1, run2), lin, imp, ssh_more, pw, state), False)
        expect("live refuses a missing tool",
               lambda: live_checks(name, "fresh", receive_ok.replace(run1, run2), lin, imp,
                                   lambda n, c: (127, "") if c.startswith("uv ") else ssh_ok(n, c), pw, t / "s4.json"),
               False)

    bad = [label for label, ok in results if not ok]
    for label, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {label}")
    print(f"selftest: {len(results) - len(bad)} of {len(results)} cases as expected")
    return 1 if bad else 0


def _raise_if(items: list) -> None:
    if items:
        raise CheckError(f"{len(items)} item(s)")


# ----------------------------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cmd", nargs="?", choices=("hub", "live"))
    parser.add_argument("name", nargs="?")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--backup", action="store_true")
    group.add_argument("--baseline", action="store_true")
    group.add_argument("--pytest", type=Path, metavar="RECEIPT")
    group.add_argument("--red", type=Path, nargs="+", metavar="RECEIPT")
    group.add_argument("--gates", action="store_true")
    group.add_argument("--privacy", action="store_true")
    group.add_argument("--state", action="store_true")
    group.add_argument("--selftest", action="store_true")
    parser.add_argument("--exit", type=int, dest="exit_code")
    parser.add_argument("--acs")
    parser.add_argument("--mode", choices=("fresh", "rerun"))
    parser.add_argument("--receive", type=Path)
    parser.add_argument("--import-receipt", type=Path)
    args = parser.parse_args(argv)
    flags = [args.backup, args.baseline, args.pytest, args.red, args.gates, args.privacy, args.state, args.selftest]
    if args.cmd and any(flags):
        parser.error("give one mode")
    try:
        if args.cmd == "hub":
            return cmd_hub()
        if args.cmd == "live":
            if not (args.name and args.mode and args.receive):
                parser.error("live needs <name> --mode fresh|rerun --receive <receipt>")
            return cmd_live(args.name, args.mode, args.receive, args.import_receipt)
        if args.backup:
            return cmd_backup()
        if args.baseline:
            return cmd_baseline()
        if args.pytest:
            if args.exit_code is None:
                parser.error("--pytest needs --exit <code>")
            return cmd_pytest(args.pytest, args.exit_code)
        if args.red:
            if not args.acs:
                parser.error("--red needs --acs <n,...>")
            return cmd_red(args.red, [int(x) for x in args.acs.split(",") if x.strip()])
        if args.gates:
            return cmd_gates()
        if args.privacy:
            return cmd_privacy()
        if args.state:
            return cmd_state()
        if args.selftest:
            return selftest()
        parser.error("give one mode")
    except CheckError as e:
        print(f"check_kit FAIL: {e}")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
