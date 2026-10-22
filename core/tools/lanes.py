"""Lane cards: admission, heartbeat, release and ownership checks for parallel lanes.

Design: ``docs/execution/plans/2026-10-20-multi-agent-lanes/design/design.md``
§5.2 "Lane cards", §5.3 "Ownership in the plan", §5.7 "Messages and halts";
plan ``implementation-plan.md`` §MEU-784 (AC-784.2–AC-784.9, EA-8).

Coordination state lives in the git common directory, which git does not
track: one card per lane at ``<common>/lanes/<lane>.json``, the registry lock
``<common>/lanes/registry.lock`` (the shared OS lease, ``tools/os_lease.py``)
and the human's halt file ``<common>/lanes/HALT``.

- Every card write happens under the registry lock, compares ``session``,
  ``generation`` and ``op`` with the caller's expectation, and replaces the
  card through a temporary file and ``os.replace``.
- A card in ``active`` or ``landing`` reserves its worktree, branch, ``owns``
  and claims. A card with no ``updated`` change for 6 hours is stale; stale
  does not mean dead, and only the human frees it.
- Ownership compares the repository-relative paths git prints, after NFC and,
  when ``core.ignorecase`` is true, case folding. A path through a symbolic
  link, junction or other reparse point is refused (filesystem metadata).

Commands (stdout; a refusal prints ``refused: <reason>`` and exits 1):

    lanes.py claim   --plan <dir> --worktree <path> [--session S]
    lanes.py beat    --plan <dir> [--session S] [--generation G]   # exit 3 under HALT
    lanes.py release --plan <dir> [--session S] [--generation G]
    lanes.py list    [--json]
    lanes.py check   --plan <dir> [--base <rev>]

The lane slug is the plan folder name. The session comes from ``--session``,
else ``{{PROJECT_NAME_UPPER}}_SESSION``. The junction files come from the
``junction_files`` key of ``.agent/credits/worktree.json``; a missing or
invalid config refuses ``claim`` with ``worktree_bad:config``. Python standard
library only.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

if __package__:
    from . import executor_worktree, os_lease
else:  # run as a script, or imported with tools/ on sys.path
    import executor_worktree
    import os_lease

Card = dict[str, Any]

STALE_S = 21600
REGISTRY_WAIT_S = 10.0
POLL_S = 0.05
# Design §2.4, §9.2: the junction files only the integrator edits are project data,
# the ``junction_files`` key of ``.agent/credits/worktree.json`` (D-P10, §5.4).
JUNCTION_KEY = "junction_files"

LANES_DIR = "lanes"
REGISTRY_LOCK = "registry.lock"
HALT_FILE = "HALT"
# The ref guard's install inventory (``tools/ref_guard.py``) sits beside the cards;
# it is not a card, and no lane may take its name.
GUARD_INVENTORY = "ref-guard.json"
SESSION_ENV = "{{PROJECT_NAME_UPPER}}_SESSION"
OWNERSHIP_HEADING = "## Lane Ownership"
LOCK_BODY_SCHEMA = "lanes-registry/1"
UPDATED_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
CARD_KEYS = (
    "lane",
    "generation",
    "session",
    "state",
    "op",
    "worktree",
    "branch",
    "plan",
    "owns",
    "claims",
    "gates",
    "updated",
)
CARD_STATES = ("active", "landing", "released")
RESERVING_STATES = ("active", "landing")
OWNERSHIP_KEYS = ("owns", "must_not_touch")
EXIT_REFUSED = 1
EXIT_HALT = 3

_LANE_RE = re.compile(r"[a-z0-9-]+")
_GENERATION_RE = re.compile(r"[0-9a-f]{16}")
_UPDATED_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
_DRIVE_RE = re.compile(r"[A-Za-z]:")
_GLOB_CHARS = frozenset("*?[]")
_KEY_LINE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*):(.*)")
_ITEM_LINE_RE = re.compile(r"\s+-(\s.*)?")


class Refusal(Exception):
    """A refused lane operation: ``reason`` is the stable token, ``detail`` the advice."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def _utc_text(moment: datetime) -> str:
    """``moment`` as the card's ``updated`` text (UTC, whole seconds, ``Z``)."""
    return moment.astimezone(timezone.utc).strftime(UPDATED_FORMAT)


def _parse_updated(text: str) -> datetime:
    """The aware UTC datetime of an ``updated`` value.

    Raises:
        ValueError: ``text`` is not ``YYYY-MM-DDTHH:MM:SSZ``.
    """
    if not _UPDATED_RE.fullmatch(text):
        raise ValueError(f"not {UPDATED_FORMAT}: {text!r}")
    return datetime.strptime(text, UPDATED_FORMAT).replace(tzinfo=timezone.utc)


def _is_stale(card: Card, now: datetime) -> bool:
    """True when ``card`` has had no ``updated`` change for more than STALE_S."""
    return (now - _parse_updated(card["updated"])).total_seconds() > STALE_S


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def _bad(key: str, detail: str) -> Refusal:
    return Refusal(f"card_bad:{key}", detail)


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _canonical_abs_posix(value: str) -> bool:
    """True for an absolute path in canonical forward-slash form."""
    if not value or "\\" in value or not Path(value).is_absolute():
        return False
    if Path(value).as_posix() != value:
        return False
    return not any(part in (".", "..") for part in PurePosixPath(value).parts)


def _validate_card(card: object) -> Card:
    """``card`` when it has exactly the card fields with valid values.

    Raises:
        Refusal: ``card_bad:extra`` for an unknown key, else
            ``card_bad:<key>`` for the first missing or invalid field.
    """
    if not isinstance(card, dict):
        raise _bad("json", "a card is one JSON object")
    extra = sorted(str(key) for key in card if key not in CARD_KEYS)
    if extra:
        raise _bad("extra", f"unknown keys {extra}")
    for key in CARD_KEYS:
        if key not in card:
            raise _bad(key, "missing")
    if not isinstance(card["lane"], str) or not _LANE_RE.fullmatch(card["lane"]):
        raise _bad("lane", "lowercase letters, digits and '-' only")
    generation = card["generation"]
    if not isinstance(generation, str) or not _GENERATION_RE.fullmatch(generation):
        raise _bad("generation", "16 lowercase hex digits")
    if not isinstance(card["session"], str) or not card["session"]:
        raise _bad("session", "a non-empty string")
    if card["state"] not in CARD_STATES:
        raise _bad("state", f"one of {list(CARD_STATES)}")
    op = card["op"]
    if card["state"] == "landing":
        if not isinstance(op, str) or not op:
            raise _bad("op", "a landing card names its land operation")
    elif op is not None:
        raise _bad("op", "op is null unless the card is landing")
    worktree = card["worktree"]
    if not isinstance(worktree, str) or not _canonical_abs_posix(worktree):
        raise _bad("worktree", "an absolute canonical forward-slash path")
    branch = card["branch"]
    if branch is not None and (not isinstance(branch, str) or not branch):
        raise _bad("branch", "null or a branch name")
    if not isinstance(card["plan"], str) or not card["plan"]:
        raise _bad("plan", "the plan folder")
    for key in ("owns", "claims"):
        if not _is_str_list(card[key]):
            raise _bad(key, "a list of strings")
    if not isinstance(card["gates"], list):
        raise _bad("gates", "a list")
    updated = card["updated"]
    try:
        if not isinstance(updated, str):
            raise ValueError("not a string")
        _parse_updated(updated)
    except ValueError as exc:
        raise _bad("updated", str(exc)) from None
    return card


def _load_card(path: Path) -> Card:
    """The validated card at ``path``.

    Raises:
        Refusal: ``card_bad:<key>`` (``card_bad:json`` when the file is not
            one JSON object, ``card_bad:lane`` when the file name and the
            ``lane`` field differ).
        OSError: the file cannot be read.
    """
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise _bad("json", f"{path}: {exc}") from None
    card = _validate_card(data)
    if card["lane"] != path.stem:
        raise _bad("lane", f"{path} holds lane {card['lane']!r}")
    return card


def _lanes_dir(common: Path) -> Path:
    return Path(common) / LANES_DIR


def _card_files(lanes_dir: Path) -> list[Path]:
    """The card files of ``lanes_dir``, sorted; the ref guard inventory is not one."""
    if not lanes_dir.is_dir():
        return []
    return sorted(
        path for path in lanes_dir.glob("*.json") if path.name != GUARD_INVENTORY
    )


def _card_path(common: Path, lane: str) -> Path:
    return _lanes_dir(common) / f"{lane}.json"


def _other_cards(lanes_dir: Path, exclude: str) -> list[Card]:
    """Every card in ``lanes_dir`` except lane ``exclude``.

    Raises:
        Refusal: a card is unreadable; it may reserve something, so admission
            fails closed until the human repairs or removes it.
    """
    cards: list[Card] = []
    for path in _card_files(lanes_dir):
        if path.stem == exclude:
            continue
        try:
            cards.append(_load_card(path))
        except Refusal as exc:
            raise Refusal(
                exc.reason,
                f"{path} is unreadable ({exc.detail}); it may reserve resources, "
                "so admission waits until the human repairs or removes it",
            ) from None
    return cards


def _overlaps(a: str, b: str) -> bool:
    """Component-aware overlap of two entries: one equals or holds the other.

    A trailing ``/`` marks a directory prefix; ``a/b`` holds ``a/b/c`` but not
    ``a/bc``.
    """
    core_a = a.rstrip("/")
    core_b = b.rstrip("/")
    return (
        core_a == core_b
        or core_b.startswith(core_a + "/")
        or core_a.startswith(core_b + "/")
    )


def _covers(entry: str, path: str) -> bool:
    """True when ownership ``entry`` equals ``path`` or is a directory above it."""
    core = entry.rstrip("/")
    return path == core or path.startswith(core + "/")


def _normalize(path: str, ignorecase: bool) -> str:
    """``path`` in NFC, then case-folded when ``ignorecase`` is true."""
    text = unicodedata.normalize("NFC", path)
    return text.casefold() if ignorecase else text


def _same_worktree(a: str, b: str) -> bool:
    return os.path.normcase(a) == os.path.normcase(b)


def _conflict_with(new: Card, other: Card, ignorecase: bool) -> str | None:
    """The first reservation of ``other`` that ``new`` collides with, if any."""
    if new["branch"] is not None and new["branch"] == other["branch"]:
        return "branch_reserved"
    if set(new["claims"]) & set(other["claims"]):
        return "claim_reserved"
    for entry in new["owns"]:
        mine = _normalize(entry, ignorecase)
        for theirs in other["owns"]:
            if _overlaps(mine, _normalize(theirs, ignorecase)):
                return f"owns_overlap:{other['lane']}:{entry}"
    if _same_worktree(new["worktree"], other["worktree"]):
        return "worktree_reserved"
    return None


def _reservation_conflict(
    new: Card, others: Sequence[Card], *, now: datetime, ignorecase: bool
) -> str | None:
    """The refusal reason for admitting ``new`` beside ``others``, or None.

    Only ``active`` and ``landing`` cards reserve. A conflicting card that is
    stale refuses as ``stale_reserving:<lane>``: only the human frees it.
    """
    for other in others:
        if other["lane"] == new["lane"] or other["state"] not in RESERVING_STATES:
            continue
        reason = _conflict_with(new, other, ignorecase)
        if reason is None:
            continue
        if _is_stale(other, now):
            return f"stale_reserving:{other['lane']}"
        return reason
    return None


def _conflict_detail(reason: str, lanes_dir: Path, others: Sequence[Card]) -> str:
    lane = reason.split(":", 2)[1] if ":" in reason else None
    if reason.startswith("stale_reserving:") and lane is not None:
        return (
            f"the card {lanes_dir / f'{lane}.json'} reserves what this lane needs and "
            f"has had no update for over {STALE_S // 3600} hours. Stale does not mean "
            "dead: only the human removes or reassigns that card."
        )
    if lane is not None:
        return f"lane {lane} owns an overlapping path; amend the plan's Lane Ownership"
    holders = [o["lane"] for o in others if o["state"] in RESERVING_STATES]
    return f"another reserving card holds it (reserving lanes: {', '.join(holders)})"


def _lock_body(argv: Sequence[str]) -> bytes:
    body = {
        "schema": LOCK_BODY_SCHEMA,
        "pid": os.getpid(),
        "argv": list(argv),
        "started_utc": _utc_text(datetime.now(timezone.utc)),
    }
    return json.dumps(body, sort_keys=True).encode("utf-8")


def _busy_detail(busy: os_lease.Busy, wait_s: float) -> str:
    """Who holds the registry lock, from its body, and what a timeout means."""
    try:
        body = json.loads(busy.holder_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        body = None
    if isinstance(body, dict):
        argv = body.get("argv")
        shown_argv = (
            " ".join(str(part) for part in argv)
            if isinstance(argv, list)
            else "unknown"
        )
        holder = (
            f"holder pid {body.get('pid', 'unknown')}, argv {shown_argv}, "
            f"started {body.get('started_utc', 'unknown')}"
        )
    else:
        holder = f"holder body {busy.holder_body[:200]!r}"
    return (
        f"the registry lock {busy.path} is still held after {wait_s:g} s ({holder}).\n"
        "A timeout does not mean the holder died; retry, or ask the human to "
        "check that process."
    )


def _replace_atomically(path: Path, data: bytes) -> None:
    """Write ``data`` to a temporary file beside ``path``, then ``os.replace`` it."""
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _write_card(
    common: Path,
    card: Card,
    *,
    expect: dict[str, str | None] | None,
    wait_s: float,
    poll_s: float,
    ignorecase: bool = False,
    argv: Sequence[str] | None = None,
) -> Path:
    """Write ``card`` under the registry lock; return its path.

    ``expect`` None creates: an existing card of the lane must be
    ``released``, and no other reserving card may conflict
    (``_reservation_conflict``). Otherwise ``expect`` holds the ``session``,
    ``generation`` and ``op`` the current card must carry (the CAS).

    Raises:
        Refusal: ``card_bad:<key>``, ``common_dir_unwritable``,
            ``registry_busy``, ``claim_reserved``, a reservation conflict,
            ``no_card`` or ``card_superseded``. Nothing was written.
        ValueError: ``expect`` lacks one of its three keys.
    """
    card = _validate_card(card)
    if expect is not None and set(expect) != {"session", "generation", "op"}:
        raise ValueError(
            f"_write_card: expect needs session, generation and op, got {sorted(expect)}"
        )
    lanes_dir = _lanes_dir(common)
    try:
        lanes_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Refusal(
            "common_dir_unwritable", f"cannot create {lanes_dir}: {exc}"
        ) from None
    holder_argv = list(sys.argv if argv is None else argv)
    try:
        lease = os_lease.acquire(
            lanes_dir / REGISTRY_LOCK,
            wait_s=wait_s,
            body=_lock_body(holder_argv),
            poll_s=poll_s,
        )
    except os_lease.Busy as busy:
        raise Refusal("registry_busy", _busy_detail(busy, wait_s)) from None
    except OSError as exc:
        raise Refusal(
            "common_dir_unwritable", f"cannot lock {lanes_dir / REGISTRY_LOCK}: {exc}"
        ) from None
    try:
        path = lanes_dir / f"{card['lane']}.json"
        current = _load_card(path) if path.is_file() else None
        if expect is None:
            if current is not None and current["state"] != "released":
                raise Refusal(
                    "claim_reserved",
                    f"lane {card['lane']} already has a {current['state']} card ({path})",
                )
            others = _other_cards(lanes_dir, exclude=card["lane"])
            reason = _reservation_conflict(
                card, others, now=datetime.now(timezone.utc), ignorecase=ignorecase
            )
            if reason is not None:
                raise Refusal(reason, _conflict_detail(reason, lanes_dir, others))
        else:
            if current is None:
                raise Refusal("no_card", f"no card at {path}")
            held = {key: current[key] for key in ("session", "generation", "op")}
            if held != expect:
                raise Refusal(
                    "card_superseded",
                    f"{path} holds session {held['session']}, generation "
                    f"{held['generation']}, op {held['op']}; this caller expected "
                    f"session {expect['session']}, generation {expect['generation']}, "
                    f"op {expect['op']}. Stop and tell the human.",
                )
            # A released card is final: only a new claim replaces it. A beat or
            # release that read the card before an intervening release stops here.
            if current["state"] == "released":
                raise Refusal(
                    "card_superseded",
                    f"{path} is released; this caller read it before the release. "
                    "Stop and tell the human.",
                )
        data = (json.dumps(card, indent=2) + "\n").encode("utf-8")
        try:
            _replace_atomically(path, data)
        except OSError as exc:
            raise Refusal(
                "common_dir_unwritable", f"cannot write {path}: {exc}"
            ) from None
    finally:
        os_lease.release(lease)
    return path


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


def _entry_ok(entry: str) -> bool:
    """True for a repository-relative exact path or directory prefix (``/``)."""
    if not entry or entry.startswith("/") or "\\" in entry:
        return False
    if _DRIVE_RE.match(entry) or any(ch in _GLOB_CHARS for ch in entry):
        return False
    if any(ord(ch) < 32 for ch in entry):
        return False
    core = entry[:-1] if entry.endswith("/") else entry
    return all(part not in ("", ".", "..") for part in core.split("/"))


def _unquote(value: str, key: str) -> str:
    """A YAML item value: plain, or one single- or double-quoted string."""
    if len(value) >= 2 and value[0] == value[-1] == "'":
        inner = value[1:-1]
        if "'" in inner.replace("''", ""):
            raise Refusal(f"ownership_bad:{key}", f"bad single-quoted item {value}")
        return inner.replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        inner = value[1:-1]
        if '"' in inner or "\\" in inner:
            raise Refusal(f"ownership_bad:{key}", f"escapes are not supported: {value}")
        return inner
    return value


def _ownership_block(text: str, source: Path) -> list[str]:
    """The lines inside the ```yaml fence of the Lane Ownership section."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == OWNERSHIP_HEADING]
    if not starts:
        raise Refusal(
            "no_ownership",
            f"{source} has no '{OWNERSHIP_HEADING}' section; a lane needs one",
        )
    if len(starts) > 1:
        raise Refusal("ownership_bad:section", f"{source} has two ownership sections")
    fence: int | None = None
    for i in range(starts[0] + 1, len(lines)):
        if lines[i].startswith("## "):
            break
        if lines[i].strip() == "```yaml":
            fence = i
            break
    if fence is None:
        raise Refusal(
            "ownership_bad:yaml", f"{source}: the section has no ```yaml block"
        )
    for j in range(fence + 1, len(lines)):
        if lines[j].strip() == "```":
            return lines[fence + 1 : j]
    raise Refusal("ownership_bad:yaml", f"{source}: the ```yaml block is not closed")


def _parse_ownership(block: Sequence[str]) -> dict[str, list[str]]:
    """``owns`` and ``must_not_touch`` from the block: block lists or ``[]``."""
    data: dict[str, list[str]] = {}
    current: str | None = None
    last: str | None = None
    for line in block:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key_match = None if line[0].isspace() else _KEY_LINE_RE.fullmatch(line.rstrip())
        if key_match is not None:
            key, rest = key_match.group(1), key_match.group(2).strip()
            last = key
            if key not in OWNERSHIP_KEYS or key in data:
                raise Refusal(f"ownership_bad:{key}", f"unexpected key line {line!r}")
            if rest == "":
                data[key], current = [], key
            elif rest == "[]":
                data[key], current = [], None
            else:
                raise Refusal(
                    f"ownership_bad:{key}", f"{key} must be a list, got {rest!r}"
                )
            continue
        item_match = _ITEM_LINE_RE.fullmatch(line.rstrip())
        if item_match is not None and current is not None:
            data[current].append(_unquote((item_match.group(1) or "").strip(), current))
            continue
        raise Refusal(f"ownership_bad:{last or 'syntax'}", f"unexpected line {line!r}")
    for key in OWNERSHIP_KEYS:
        if key not in data:
            raise Refusal(f"ownership_bad:{key}", f"missing {key}")
    return data


def _load_ownership(
    task_md: Path, *, ignorecase: bool = False
) -> tuple[list[str], list[str]]:
    """``(owns, must_not_touch)`` of the plan's ``## Lane Ownership`` section.

    Raises:
        Refusal: ``no_ownership``, ``ownership_bad:<key>``,
            ``entry_bad:<entry>`` or ``ownership_contradiction:<own>:<mnt>``.
        OSError: ``task_md`` cannot be read.
    """
    text = task_md.read_text(encoding="utf-8")
    data = _parse_ownership(_ownership_block(text, task_md))
    owns, mnt = data["owns"], data["must_not_touch"]
    for entry in (*owns, *mnt):
        if not _entry_ok(entry):
            raise Refusal(
                f"entry_bad:{entry}",
                "entries are repository-relative paths or prefixes ending in '/': "
                "no globs, absolute paths, drive letters, backslashes, '.' or '..'",
            )
    for own in owns:
        for avoid in mnt:
            if _overlaps(_normalize(own, ignorecase), _normalize(avoid, ignorecase)):
                raise Refusal(
                    f"ownership_contradiction:{own}:{avoid}",
                    "an owns entry and a must_not_touch entry overlap",
                )
    return owns, mnt


def _through_link(root: Path, rel: str) -> bool:
    """True when an existing component of ``root/rel`` is a link or reparse point."""
    current = Path(root)
    for part in rel.rstrip("/").split("/"):
        current = current / part
        try:
            info = os.lstat(current)
        except (FileNotFoundError, NotADirectoryError):
            return False
        if stat.S_ISLNK(info.st_mode):
            return True
        if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return True
    return False


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        raise Refusal("git_unavailable", str(exc)) from None


def _git_text(cwd: Path, *args: str) -> str:
    proc = _git(cwd, *args)
    if proc.returncode != 0:
        raise Refusal(
            "git_failed",
            f"git {' '.join(args)} exited {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}",
        )
    return proc.stdout.decode("utf-8", "surrogateescape")


def _repo_dirs(cwd: Path) -> tuple[Path, Path]:
    """``(toplevel, common_dir)`` of the repository at ``cwd``."""
    top = _git_text(cwd, "rev-parse", "--show-toplevel").strip()
    common = _git_text(
        cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"
    ).strip()
    return Path(top).resolve(), Path(common).resolve()


def _ignorecase(cwd: Path) -> bool:
    proc = _git(cwd, "config", "--bool", "--get", "core.ignorecase")
    if proc.returncode == 1:
        return False
    if proc.returncode != 0:
        raise Refusal("git_failed", proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout.decode("utf-8", "replace").strip() == "true"


def _worktrees(cwd: Path) -> list[str]:
    """Every worktree path git lists, the main worktree first, resolved posix."""
    text = _git_text(cwd, "worktree", "list", "--porcelain")
    return [
        Path(line[len("worktree ") :]).resolve().as_posix()
        for line in text.splitlines()
        if line.startswith("worktree ")
    ]


def junction_files(top: Path) -> tuple[str, ...]:
    """The project's junction files: ``junction_files`` of ``top``'s worktree config."""
    try:
        config = executor_worktree.load_worktree_config(top)
    except executor_worktree.WorktreeConfigError as error:
        raise Refusal("worktree_bad:config", str(error)) from None
    value = config[JUNCTION_KEY]
    return tuple(value) if isinstance(value, list) else ()


def _split_z(raw: bytes) -> list[str]:
    return [tok.decode("utf-8", "surrogateescape") for tok in raw.split(b"\0") if tok]


def _changed_paths(top: Path, base: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Paths changed from ``base`` to the working tree, and the renames.

    Tracked changes come from ``git diff -M --name-status -z <base>``
    (committed, staged and unstaged); untracked files from ``git ls-files
    --others --exclude-standard -z``. A rename yields both paths.
    """
    diff = _git(top, "diff", "-M", "--name-status", "-z", base, "--")
    if diff.returncode != 0:
        raise Refusal("git_failed", diff.stderr.decode("utf-8", "replace").strip())
    tokens = _split_z(diff.stdout)
    paths: set[str] = set()
    renames: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        status = tokens[i]
        if status[:1] in ("R", "C"):
            if i + 2 >= len(tokens):
                raise Refusal("git_failed", f"truncated diff record {status}")
            old, new = tokens[i + 1], tokens[i + 2]
            paths.add(new)
            if status[0] == "R":
                paths.add(old)
                renames.append((old, new))
            i += 3
        else:
            if i + 1 >= len(tokens):
                raise Refusal("git_failed", f"truncated diff record {status}")
            paths.add(tokens[i + 1])
            i += 2
    others = _git(top, "ls-files", "--others", "--exclude-standard", "-z")
    if others.returncode != 0:
        raise Refusal("git_failed", others.stderr.decode("utf-8", "replace").strip())
    paths.update(_split_z(others.stdout))
    return sorted(paths), renames


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _plan_lane(raw: str) -> tuple[str, str]:
    """``(plan_dir, lane)`` for a ``--plan`` value; the lane is its folder name."""
    rel = raw.rstrip("/")
    if not _entry_ok(rel):
        raise Refusal(
            "plan_bad", f"--plan must be a repository-relative folder: {raw!r}"
        )
    lane = rel.rsplit("/", 1)[-1]
    if not _LANE_RE.fullmatch(lane):
        raise Refusal("plan_bad", f"the plan folder {lane!r} is not a lane slug")
    if f"{lane}.json" == GUARD_INVENTORY:
        raise Refusal(
            "plan_bad", f"the lane name {lane!r} is the ref guard inventory's name"
        )
    return rel, lane


def _session(raw: str | None) -> str:
    session = raw if raw else os.environ.get(SESSION_ENV, "")
    if not session:
        raise Refusal("no_session", f"pass --session or set {SESSION_ENV}")
    return session


def _halted(common: Path) -> bool:
    return (_lanes_dir(common) / HALT_FILE).exists()


def _cmd_claim(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    session = _session(args.session)
    top, common = _repo_dirs(Path.cwd())
    if _halted(common):
        print("halt")
        return EXIT_HALT
    plan, lane = _plan_lane(args.plan)
    task_md = top / plan / "task.md"
    if not task_md.is_file():
        raise Refusal("no_task", f"{task_md} does not exist")
    ignorecase = _ignorecase(top)
    owns, _ = _load_ownership(task_md, ignorecase=ignorecase)
    junctions = junction_files(top)
    for entry in owns:
        folded = _normalize(entry, True)
        for junction in junctions:
            target = _normalize(junction, True)
            # An entry that is a junction file, or a folder above one: the lane could
            # create the file there, so whether it exists yet does not count (R1-F3).
            if _covers(folded, target):
                raise Refusal(
                    f"owns_junction:{entry}",
                    f"{junction} is a junction file; only the integrator edits it. "
                    "Write an Integration request in the handoff instead.",
                )
    worktree = Path(args.worktree).resolve()
    if not worktree.is_dir():
        raise Refusal("worktree_bad", f"{worktree} is not a directory")
    shown = worktree.as_posix()
    if not any(_same_worktree(shown, listed) for listed in _worktrees(top)):
        raise Refusal("worktree_unknown", f"git worktree list does not name {shown}")
    card: Card = {
        "lane": lane,
        "generation": secrets.token_hex(8),
        "session": session,
        "state": "active",
        "op": None,
        "worktree": shown,
        "branch": None,
        "plan": f"{plan}/",
        "owns": owns,
        "claims": [],
        "gates": [],
        "updated": _utc_text(datetime.now(timezone.utc)),
    }
    _write_card(
        common,
        card,
        expect=None,
        wait_s=wait_s,
        poll_s=poll_s,
        ignorecase=ignorecase,
        argv=argv,
    )
    print(f"claimed {lane} generation={card['generation']}")
    return 0


def _current_card(common: Path, lane: str) -> Card:
    path = _card_path(common, lane)
    if not path.is_file():
        raise Refusal("no_card", f"no card at {path}")
    return _load_card(path)


def _check_identity(
    card: Card, session: str, generation: str | None
) -> dict[str, str | None]:
    """The CAS expectation for the caller; refuses when the card is not theirs."""
    expected = generation if generation else card["generation"]
    if card["session"] != session or card["generation"] != expected:
        raise Refusal(
            "card_superseded",
            f"the card of {card['lane']} belongs to session {card['session']}, "
            f"generation {card['generation']}. Stop and tell the human.",
        )
    return {"session": session, "generation": expected, "op": card["op"]}


def _cmd_beat(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    session = _session(args.session)
    _, common = _repo_dirs(Path.cwd())
    if _halted(common):
        print("halt")
        return EXIT_HALT
    _, lane = _plan_lane(args.plan)
    card = _current_card(common, lane)
    expect = _check_identity(card, session, args.generation)
    if card["state"] == "released":
        raise Refusal(
            "card_superseded",
            f"the card of {lane} is released. Stop and tell the human.",
        )
    beat = dict(card, updated=_utc_text(datetime.now(timezone.utc)))
    _write_card(common, beat, expect=expect, wait_s=wait_s, poll_s=poll_s, argv=argv)
    print(f"beat {lane} updated={beat['updated']}")
    return 0


def _cmd_release(
    args: argparse.Namespace, *, wait_s: float, poll_s: float, argv: Sequence[str]
) -> int:
    session = _session(args.session)
    top, common = _repo_dirs(Path.cwd())
    _, lane = _plan_lane(args.plan)
    card = _current_card(common, lane)
    expect = _check_identity(card, session, args.generation)
    if card["state"] == "released":
        print(f"released {lane} (already)")
        return 0
    listed = _worktrees(top)
    linked = listed[1:]
    is_main = bool(listed) and _same_worktree(card["worktree"], listed[0])
    if not is_main and any(_same_worktree(card["worktree"], wt) for wt in linked):
        raise Refusal(
            "worktree_live",
            f"git worktree list still names {card['worktree']}; remove the lane "
            "worktree first (git worktree remove), then release",
        )
    released = dict(
        card, state="released", op=None, updated=_utc_text(datetime.now(timezone.utc))
    )
    _write_card(
        common, released, expect=expect, wait_s=wait_s, poll_s=poll_s, argv=argv
    )
    print(f"released {lane}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    _, common = _repo_dirs(Path.cwd())
    lanes_dir = _lanes_dir(common)
    now = datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = []
    for path in _card_files(lanes_dir):
        try:
            card = _load_card(path)
        except (Refusal, OSError) as exc:
            reason = exc.reason if isinstance(exc, Refusal) else f"unreadable:{exc}"
            entries.append(
                {"lane": path.stem, "state": "bad", "stale": None, "error": reason}
            )
            continue
        entries.append(dict(card, stale=_is_stale(card, now)))
    halted = _halted(common)
    if args.json:
        if halted:
            print("HALT", file=sys.stderr)
        print(json.dumps(entries, indent=2))
        return 0
    if halted:
        print("HALT")
    for entry in entries:
        if entry["state"] == "bad":
            print(f"{entry['lane']} state=bad stale=unknown error={entry['error']}")
            continue
        stale = "true" if entry["stale"] else "false"
        print(
            f"{entry['lane']} state={entry['state']} stale={stale} "
            f"session={entry['session']} generation={entry['generation']} "
            f"updated={entry['updated']} worktree={entry['worktree']}"
        )
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    top, _ = _repo_dirs(Path.cwd())
    plan, _ = _plan_lane(args.plan)
    task_md = top / plan / "task.md"
    if not task_md.is_file():
        raise Refusal("no_task", f"{task_md} does not exist")
    ignorecase = _ignorecase(top)
    owns, mnt = _load_ownership(task_md, ignorecase=ignorecase)
    base = args.base
    if not base or base.startswith("-"):
        raise Refusal("base_bad", f"--base must name a commit: {base!r}")
    resolved = _git(top, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if resolved.returncode != 0:
        raise Refusal("base_bad", f"{base} is not a commit")
    base_sha = resolved.stdout.decode("ascii", "replace").strip()
    paths, renames = _changed_paths(top, base_sha)
    findings: list[str] = []
    for entry in (*owns, *mnt):
        if _through_link(top, entry):
            findings.append(f"link_path:{entry}")
    owned = [_normalize(e, ignorecase) for e in owns]
    avoided = [_normalize(e, ignorecase) for e in mnt]
    for path in paths:
        norm = _normalize(path, ignorecase)
        if _through_link(top, path):
            findings.append(f"link_path:{path}")
        elif any(_covers(entry, norm) for entry in avoided):
            findings.append(f"must_not_touch:{path}")
        elif not any(_covers(entry, norm) for entry in owned):
            findings.append(f"outside_owns:{path}")
    for old, new in renames:
        print(f"rename:{old} -> {new}")
    for line in findings:
        print(line)
    if findings:
        return EXIT_REFUSED
    print("check_ok")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lanes.py",
        description="Lane cards: admission, heartbeat, release and ownership checks.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    claim = sub.add_parser("claim", help="admit a lane: write its active card")
    claim.add_argument("--plan", required=True)
    claim.add_argument("--worktree", required=True)
    claim.add_argument("--session")
    for name, text in (
        ("beat", "refresh the card's updated time"),
        ("release", "release the card"),
    ):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--plan", required=True)
        cmd.add_argument("--session")
        cmd.add_argument("--generation")
    listing = sub.add_parser("list", help="show every card without the registry lock")
    listing.add_argument("--json", action="store_true")
    check = sub.add_parser(
        "check", help="compare the change set with the plan's ownership"
    )
    check.add_argument("--plan", required=True)
    check.add_argument("--base", default="HEAD")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    wait_s: float = REGISTRY_WAIT_S,
    poll_s: float = POLL_S,
) -> int:
    """Run one lanes command; 0 ok, 1 refused or findings, 2 usage, 3 HALT."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    try:
        args = _parser().parse_args(args_list)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    holder_argv = ["tools/lanes.py", *args_list]
    try:
        if args.command == "claim":
            return _cmd_claim(args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv)
        if args.command == "beat":
            return _cmd_beat(args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv)
        if args.command == "release":
            return _cmd_release(args, wait_s=wait_s, poll_s=poll_s, argv=holder_argv)
        if args.command == "list":
            return _cmd_list(args)
        return _cmd_check(args)
    except Refusal as exc:
        print(f"refused: {exc.reason}")
        if exc.detail:
            print(exc.detail)
        return EXIT_REFUSED
    except OSError as exc:
        print(f"refused: io_error\n{exc}")
        return EXIT_REFUSED


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.exit(main())
