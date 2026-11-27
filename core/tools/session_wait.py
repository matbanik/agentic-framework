"""One wait script with named conditions and one wait record per wait.

Usage::

    session_wait.py [--repo PATH] check --cond COND [--cond ...] [--exempt LANE:RULING ...]
                                        [--credits-db PATH] [--credits-lane LANE]
    session_wait.py [--repo PATH] wait --name N --plan SLUG --owner SESSION --cond COND ...
                                       --direction-session S --direction-message M
                                       --direction-quote Q [--poll-s N] [--stable-s N]
                                       [--cap-s N] [--receipt FILE] [--exempt ...]
                                       [--credits-db PATH] [--credits-lane LANE]
    session_wait.py [--repo PATH] list [--json]
    session_wait.py [--repo PATH] use --name N

The conditions are a closed set: ``plan_done:<slug>``, ``plan_idle:<slug>``,
``lanes_free``, ``paths_clean:<path>[,<path>...]`` and ``no_busy_run``. ``check``
evaluates each condition one time and prints one line: ``hold``, or ``wait`` and
each reason why not. ``wait`` runs as a background command of the session that
holds the parked plan. It polls until the conditions hold for a stable time, or
until the cap. Its exit wakes that session. A wake-up carries no authority.

The records live in ``<git-common-dir>/session-wait/<name>.json``. One kernel
lease on ``<name>.lock`` (``os_lease``) keeps one runner for each wait.

Exit codes: 0 hold, ``wait_ok`` or ``used``; 1 no hold or a refusal; 2 a usage
error; 5 ``wait_timeout``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

if __package__:
    from . import os_lease
else:  # run as a script, or imported with tools/ on sys.path
    import os_lease

TOOLS_DIR = Path(__file__).resolve().parent

SCHEMA = "session-wait/1"
WAIT_DIR = "session-wait"
POLL_S = 120
STABLE_S = 300
CAP_S = 72 * 3600
READER_TIMEOUT_S = 120
LEASE_WAIT_S: float = 5

EXIT_OK = 0
EXIT_NO = 1
EXIT_USAGE = 2
EXIT_TIMEOUT = 5

VERBS = ("check", "wait", "list", "use")
CONDITIONS = ("plan_done", "plan_idle", "lanes_free", "paths_clean", "no_busy_run")
NO_ARGUMENT = frozenset({"lanes_free", "no_busy_run"})
STATES = frozenset({"armed", "fired", "used", "timeout"})
BUSY_CARD_STATES = frozenset({"active", "landing", "bad"})
# The idle run states of the credits store: its terminal and halted states and
# ``registered``. A state that starts with ``parked`` is idle too; ``waiting`` is busy.
IDLE_RUN_STATES = frozenset(
    {
        "registered",
        "stopped",
        "done",
        "done_unverified",
        "failed",
        "cancelled",
        "parked",
    }
)
FINAL_SEGMENT = "finalized"
RECORD_KEYS = frozenset(
    {
        "schema",
        "name",
        "plan",
        "conditions",
        "exemptions",
        "owner",
        "pid",
        "state",
        "direction",
        "poll_s",
        "stable_s",
        "cap_s",
        "armed_utc",
        "stable_since_utc",
        "last_check",
        "ended_utc",
        "timeout",
    }
)
DIRECTION_KEYS = frozenset({"session", "message", "quote"})
LAST_CHECK_KEYS = frozenset({"line", "utc", "hold"})
# The fixed order of the plan_done reasons; a reason sorts by its first matching prefix.
DONE_ORDER = (
    "not_done",
    "disabled",
    "no_verdict",
    "preflight:",
    "not_landed",
    "reader_failed:",
    "reader_timeout:",
)

# Each pattern is used with fullmatch: "$" of match also accepts a line break at the end.
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
EXEMPT_RE = re.compile(r"([^\s:]+):(\S+)")
DRIVE_RE = re.compile(r"^[A-Za-z]:")
FRONT_LINE_RE = re.compile(r"([A-Za-z_]+):(.*)")
FRONT_COMMENT_RE = re.compile(r"\s#")


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def real_run(
    argv: Sequence[str], *, cwd: Path, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one reader command and capture its text output.

    ``GIT_OPTIONAL_LOCKS=0`` keeps ``git status`` from a write of the index, so a
    check writes nothing.

    Raises:
        subprocess.TimeoutExpired: the command ran past ``timeout``.
        OSError: the command could not start.
    """
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        check=False,
    )


def _print_line(line: str) -> None:
    """Write one output line to standard output."""
    print(line, flush=True)


@dataclass
class Env:
    """The seams of the tool: the runner, the clock, the sleep, the output and the pid."""

    run: Runner = real_run
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    out: Callable[[str], None] = _print_line
    pid: int = field(default_factory=os.getpid)


class UsageError(Exception):
    """A bad command line; the tool prints ``usage_error:<reason>`` and exits 2."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RecordError(Exception):
    """A wait record that the tool cannot read."""


class _Parser(argparse.ArgumentParser):
    """An argument parser that raises a usage error and never exits."""

    def __init__(self, prog: str) -> None:
        super().__init__(prog=prog, add_help=False, allow_abbrev=False)

    def error(self, message: str) -> NoReturn:
        """Raise the argparse message as a usage error."""
        raise UsageError("bad_option:" + "_".join(message.split()))


@dataclass(frozen=True)
class Condition:
    """One named condition as given on the command line."""

    text: str
    name: str
    slug: str = ""
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class Exemption:
    """One lane that ``lanes_free`` does not count, with the ruling that allows it."""

    lane: str
    ruling: str

    @property
    def text(self) -> str:
        """The exemption as given: ``<lane>:<ruling>``."""
        return f"{self.lane}:{self.ruling}"


@dataclass(frozen=True)
class Checks:
    """The validated condition options of ``check`` and ``wait``."""

    conditions: tuple[Condition, ...]
    exemptions: tuple[Exemption, ...]
    credits_db: Path | None
    credits_lane: str | None


@dataclass
class Context:
    """What the readers need: the repository, the seams and the common dir cache."""

    repo: Path
    env: Env
    common: Path | None = None


# --- time ---------------------------------------------------------------------------


def _utc_now() -> str:
    """The wall time in UTC, to the second."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- parsing ------------------------------------------------------------------------


def _parse_condition(text: str) -> Condition:
    """Parse one ``--cond`` value against the closed set of names.

    Raises:
        UsageError: an unknown name or a bad argument.
    """
    name, colon, arg = text.partition(":")
    if name not in CONDITIONS:
        raise UsageError(f"unknown_condition:{name}")
    if name in NO_ARGUMENT:
        if colon:
            raise UsageError(f"bad_argument:{name}")
        return Condition(text=text, name=name)
    if name in ("plan_done", "plan_idle"):
        if not SLUG_RE.fullmatch(arg):
            raise UsageError(f"bad_slug:{arg}")
        return Condition(text=text, name=name, slug=arg)
    paths = tuple(arg.split(","))
    for item in paths:
        _check_path(item)
    return Condition(text=text, name=name, paths=paths)


def _check_path(item: str) -> None:
    """Refuse a path that is empty, absolute, outside the repository or not plain.

    Raises:
        UsageError: ``bad_path:<item>``.
    """
    bad = (
        not item
        or "\\" in item
        or any(ch.isspace() for ch in item)
        or item.startswith("/")
        or bool(DRIVE_RE.match(item))
        or ".." in item.split("/")
    )
    if bad:
        raise UsageError(f"bad_path:{item}")


def _parse_checks(
    conds: Sequence[str] | None,
    exempts: Sequence[str] | None,
    credits_db: str | None,
    credits_lane: str | None,
) -> Checks:
    """Validate the condition options of ``check`` and ``wait``.

    Raises:
        UsageError: a missing, unknown, duplicate or bad condition, a bad
            exemption, or a missing store path.
    """
    if not conds:
        raise UsageError("missing:--cond")
    seen: set[str] = set()
    parsed: list[Condition] = []
    for text in conds:
        if text in seen:
            raise UsageError(f"duplicate_condition:{text}")
        seen.add(text)
        parsed.append(_parse_condition(text))
    exemptions: list[Exemption] = []
    for text in exempts or ():
        match = EXEMPT_RE.fullmatch(text)
        if not match:
            raise UsageError(f"bad_exempt:{text}")
        exemptions.append(Exemption(lane=match.group(1), ruling=match.group(2)))
    names = {cond.name for cond in parsed}
    if exemptions and "lanes_free" not in names:
        raise UsageError("exempt_needs_lanes_free")
    if "no_busy_run" in names and not credits_db:
        raise UsageError("no_busy_run_needs_credits_db")
    if credits_lane is not None and not credits_lane.strip():
        raise UsageError("bad_value:--credits-lane")
    return Checks(
        conditions=tuple(parsed),
        exemptions=tuple(exemptions),
        credits_db=Path(credits_db) if credits_db else None,
        credits_lane=credits_lane,
    )


def _add_check_options(parser: argparse.ArgumentParser) -> None:
    """The condition options that ``check`` and ``wait`` share."""
    parser.add_argument("--cond", action="append")
    parser.add_argument("--exempt", action="append")
    parser.add_argument("--credits-db")
    parser.add_argument("--credits-lane")


def _int_option(value: str | None, option: str, default: int, minimum: int) -> int:
    """Parse one whole-second option.

    Raises:
        UsageError: ``bad_value:<option>`` for text that is not a whole number at
            or above ``minimum``.
    """
    if value is None:
        return default
    if not re.fullmatch(r"[0-9]+", value) or int(value) < minimum:
        raise UsageError(f"bad_value:{option}")
    return int(value)


def _split_repo(argv: Sequence[str]) -> tuple[Path, list[str]]:
    """Take the leading ``--repo PATH`` off the command line.

    Raises:
        UsageError: ``--repo`` with no value.
    """
    rest = list(argv)
    repo = Path(".")
    if rest and rest[0] == "--repo":
        if len(rest) < 2:
            raise UsageError("missing:--repo")
        repo = Path(rest[1])
        rest = rest[2:]
    elif rest and rest[0].startswith("--repo="):
        repo = Path(rest[0].split("=", 1)[1])
        rest = rest[1:]
    return repo, rest


# --- readers ------------------------------------------------------------------------


def _call(
    ctx: Context, reader: str, argv: Sequence[str]
) -> subprocess.CompletedProcess[str] | str:
    """Run one reader; give the result, or the reason when it did not run."""
    try:
        return ctx.env.run(list(argv), cwd=ctx.repo, timeout=READER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"reader_timeout:{reader}"
    except OSError:
        return f"reader_failed:{reader}"


def _tool_argv(tool: str, *args: str) -> list[str]:
    """A sibling tool command line with the running interpreter."""
    return [sys.executable, str(TOOLS_DIR / tool), *args]


def _last_object(text: str) -> dict[str, object] | None:
    """The last output line that starts with ``{``, parsed as a JSON object."""
    for line in reversed(text.splitlines()):
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                return None
            if isinstance(data, dict):
                return {str(key): value for key, value in data.items()}  # pyright: ignore[reportUnknownVariableType]
            return None
    return None


def _front_value(raw: str) -> str | None:
    """The value of one frontmatter line, or None when its quotes are broken.

    A value in double quotes runs to the next double quote; a backslash in it is
    refused, because no task.md value needs an escape. A value in single quotes
    reads ``''`` as one quote. A plain value stops at a ``#`` after a space. After
    a closing quote, only a comment can follow. A broken value gives None, so the
    caller does not see the key and its check fails closed.
    """
    value = raw.strip()
    if value.startswith('"'):
        end = value.find('"', 1)
        if end < 0 or "\\" in value[1:end]:
            return None
        body, rest = value[1:end], value[end + 1 :]
    elif value.startswith("'"):
        parts: list[str] = []
        index = 1
        while True:
            if index >= len(value):
                return None
            char = value[index]
            if char != "'":
                parts.append(char)
                index += 1
            elif value[index + 1 : index + 2] == "'":
                parts.append("'")
                index += 2
            else:
                break
        body, rest = "".join(parts), value[index + 1 :]
    else:
        if value.startswith("#"):
            return ""
        comment = FRONT_COMMENT_RE.search(value)
        return (value[: comment.start()] if comment else value).strip()
    rest = rest.strip()
    if rest and not rest.startswith("#"):
        return None
    return body


def _frontmatter(text: str) -> dict[str, str] | None:
    """The ``key: value`` lines of a task.md frontmatter, or None when there is none.

    A line with broken quotes is left out (``_front_value``).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return values
        match = FRONT_LINE_RE.fullmatch(line)
        if match:
            value = _front_value(match.group(2))
            if value is not None:
                values[match.group(1)] = value
    return None


def _common_dir(ctx: Context) -> Path | str:
    """The git common dir of the repository, or the reason when git cannot say."""
    if ctx.common is not None:
        return ctx.common
    result = _call(
        ctx, "git", ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"]
    )
    if isinstance(result, str):
        return result
    text = result.stdout.strip()
    if result.returncode != 0 or not text:
        return "reader_failed:git"
    common = Path(text)
    if not common.is_absolute():
        common = ctx.repo / common
    ctx.common = common.resolve()
    return ctx.common


def _plan_done(ctx: Context, slug: str) -> list[str]:
    """The four facts of a finished plan, each read every time, with no short circuit."""
    reasons: list[str] = []
    status = _call(
        ctx,
        "status",
        _tool_argv(
            "run_parameters.py",
            "--repo",
            str(ctx.repo),
            "status",
            "--json",
            "--plan",
            slug,
        ),
    )
    if isinstance(status, str):
        reasons.append(status)
    else:
        body = _last_object(status.stdout)
        done = body.get("done") if body is not None else None
        if body is None or not isinstance(done, bool):
            reasons.append("reader_failed:status")
        elif not done:
            given = body.get("reasons")
            listed = given if isinstance(given, list) else []
            disabled = "disabled" in listed or body.get("enabled") is False
            reasons.append("disabled" if disabled else "not_done")
    preflight = _call(
        ctx,
        "preflight",
        _tool_argv(
            "completion_preflight.py",
            "--plan",
            f"docs/execution/plans/{slug}",
            "--tree",
            str(ctx.repo),
            "--json",
        ),
    )
    if isinstance(preflight, str):
        reasons.append(preflight)
    else:
        body = _last_object(preflight.stdout)
        missing = body.get("missing") if body is not None else None
        valid = (
            preflight.returncode in (0, 1)
            and isinstance(missing, list)
            and all(isinstance(item, str) for item in missing)  # pyright: ignore[reportUnknownVariableType]
        )
        if not valid or not isinstance(missing, list):
            reasons.append("reader_failed:preflight")
        else:
            ids = [str(item) for item in missing]  # pyright: ignore[reportUnknownVariableType]
            if "approved_verdict" in ids:
                reasons.append("no_verdict")
            others = [item for item in ids if item != "approved_verdict"]
            if others:
                reasons.append("preflight:" + "+".join(others))
    shown = _call(
        ctx, "git", ["git", "show", f"main:docs/execution/plans/{slug}/task.md"]
    )
    if isinstance(shown, str) and shown.startswith("reader_timeout"):
        reasons.append(shown)
    else:
        front = (
            _frontmatter(shown.stdout)
            if not isinstance(shown, str) and shown.returncode == 0
            else None
        )
        landed = (
            front is not None
            and front.get("status") == "complete"
            and front.get("stop_gate") == "released:done"
        )
        if not landed:
            reasons.append("not_landed")
    return sorted(reasons, key=_done_rank)


def _done_rank(reason: str) -> int:
    """The place of one plan_done reason in the fixed order."""
    for index, prefix in enumerate(DONE_ORDER):
        if reason == prefix or (prefix.endswith(":") and reason.startswith(prefix)):
            return index
    return len(DONE_ORDER)


def _plan_idle(ctx: Context, slug: str) -> list[str]:
    """No reason when the plan's task.md status is not ``in_progress``."""
    task = ctx.repo / "docs" / "execution" / "plans" / slug / "task.md"
    if not task.is_file():
        return ["no_task"]
    try:
        front = _frontmatter(task.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return ["unreadable"]
    if front is None or not front.get("status"):
        return ["unreadable"]
    status = front["status"]
    return [status] if status == "in_progress" else []


def _lanes_free(ctx: Context, exemptions: Sequence[Exemption]) -> list[str]:
    """No reason when no lane card is busy outside the exemptions and there is no HALT."""
    result = _call(ctx, "lanes", _tool_argv("lanes.py", "list", "--json"))
    if isinstance(result, str):
        return [result]
    if result.returncode != 0:
        return ["reader_failed"]
    try:
        data: object = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ["reader_failed:shape"]
    if not isinstance(data, list):
        return ["reader_failed:shape"]
    reasons: list[str] = []
    if any(line.strip() == "HALT" for line in result.stderr.splitlines()):
        reasons.append("halt")
    exempt = {item.lane for item in exemptions}
    for entry in data:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(entry, dict):
            return ["reader_failed:shape"]
        lane = entry.get("lane")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        state = entry.get("state")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(lane, str) or not isinstance(state, str):
            return ["reader_failed:shape"]
        if state in BUSY_CARD_STATES and lane not in exempt:
            reasons.append(f"{state}:{lane}")
    return reasons


def _paths_clean(ctx: Context, paths: Sequence[str]) -> list[str]:
    """No reason when ``git status --porcelain`` shows nothing under the paths."""
    result = _call(
        ctx,
        "git",
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
    )
    if isinstance(result, str):
        return [result]
    if result.returncode != 0:
        return ["reader_failed:git"]
    count = sum(1 for line in result.stdout.splitlines() if line.strip())
    return [f"dirty:{count}"] if count else []


def _run_idle(state: str) -> bool:
    """Whether a credits run in ``state`` holds no lane."""
    return state in IDLE_RUN_STATES or state.startswith("parked")


def _no_busy_run(ctx: Context, db: Path, lane: str | None) -> list[str]:
    """No reason when the credits store shows no busy work on the tree lane.

    The open is read only. The lane match covers the lane and every lane under it.
    """
    if lane is None:
        common = _common_dir(ctx)
        if isinstance(common, str):
            return [common]
        lane = "tree:" + common.parent.as_posix()
    if not db.is_file():
        return ["store_missing"]
    match = "(lane = ? OR lane LIKE ? ESCAPE '\\')"
    under = lane.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
    reasons: list[str] = []
    try:
        con = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
        try:
            for run_id, state in con.execute(
                f"SELECT run_id, state FROM runs WHERE {match} ORDER BY run_id",
                (lane, under),
            ):
                if not _run_idle(str(state or "")):
                    reasons.append(f"run:{run_id}={state}")
            for segment_id, state, finalized in con.execute(
                "SELECT segment_id, state, finalized_utc FROM segments "
                f"WHERE {match} ORDER BY segment_id",
                (lane, under),
            ):
                if state != FINAL_SEGMENT or finalized is None:
                    reasons.append(f"segment:{segment_id}={state}")
            for claimed, segment_id in con.execute(
                "SELECT lane, segment_id FROM lanes "
                f"WHERE {match} AND segment_id IS NOT NULL ORDER BY lane",
                (lane, under),
            ):
                reasons.append(f"lane:{claimed}={segment_id}")
        finally:
            con.close()
    except sqlite3.Error:
        return ["store_unreadable"]
    return reasons


def _evaluate(ctx: Context, checks: Checks) -> tuple[bool, str]:
    """Evaluate each condition one time; give the hold flag and the check line."""
    tokens: list[str] = []
    for cond in checks.conditions:
        if cond.name == "plan_done":
            reasons = _plan_done(ctx, cond.slug)
        elif cond.name == "plan_idle":
            reasons = _plan_idle(ctx, cond.slug)
        elif cond.name == "lanes_free":
            reasons = _lanes_free(ctx, checks.exemptions)
        elif cond.name == "paths_clean":
            reasons = _paths_clean(ctx, cond.paths)
        else:
            assert (
                checks.credits_db is not None
            )  # _parse_checks refuses no_busy_run with no store
            reasons = _no_busy_run(ctx, checks.credits_db, checks.credits_lane)
        if reasons:
            tokens.append(f"{cond.text}:{','.join(reasons)}")
    suffix = "".join(f" exempt={item.text}" for item in checks.exemptions)
    if tokens:
        return False, "wait " + " ".join(tokens) + suffix
    return True, "hold" + suffix


# --- records ------------------------------------------------------------------------


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)  # pyright: ignore[reportUnknownVariableType]


def _str_keyed(value: object) -> dict[str, object] | None:
    """``value`` as a dict with text keys, or None."""
    if not isinstance(value, dict):
        return None
    out: dict[str, object] = {}
    for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(key, str):
            return None
        out[key] = item
    return out


def _validate_record(data: object, name: str) -> dict[str, object]:
    """Check one record against schema ``session-wait/1``.

    Raises:
        RecordError: a missing or unknown key, or a value of the wrong type.
    """
    record = _str_keyed(data)
    if record is None or set(record) != RECORD_KEYS:
        raise RecordError("keys")
    direction = _str_keyed(record["direction"])
    last = record["last_check"]
    last_dict = _str_keyed(last)
    checks = (
        record["schema"] == SCHEMA,
        record["name"] == name,
        isinstance(record["plan"], str),
        _is_str_list(record["conditions"]),
        _is_str_list(record["exemptions"]),
        isinstance(record["owner"], str),
        _is_int(record["pid"]),
        isinstance(record["state"], str) and record["state"] in STATES,
        direction is not None
        and set(direction) == DIRECTION_KEYS
        and all(isinstance(item, str) for item in direction.values()),
        _is_int(record["poll_s"]),
        _is_int(record["stable_s"]),
        _is_int(record["cap_s"]),
        isinstance(record["armed_utc"], str),
        record["stable_since_utc"] is None
        or isinstance(record["stable_since_utc"], str),
        last is None
        or (
            last_dict is not None
            and set(last_dict) == LAST_CHECK_KEYS
            and isinstance(last_dict["line"], str)
            and isinstance(last_dict["utc"], str)
            and isinstance(last_dict["hold"], bool)
        ),
        record["ended_utc"] is None or isinstance(record["ended_utc"], str),
        record["timeout"] is None or _str_keyed(record["timeout"]) is not None,
    )
    if not all(checks):
        raise RecordError("types")
    return record


def _read_record(path: Path) -> dict[str, object] | None:
    """The record at ``path``; None when there is no file.

    Raises:
        RecordError: the file is not a valid record.
    """
    if not path.exists():
        return None
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecordError("unreadable") from exc
    return _validate_record(data, path.stem)


def _write_record(path: Path, record: dict[str, object]) -> None:
    """Write a record atomically: a temporary file, fsync and ``os.replace``.

    Raises:
        OSError: the write failed; the old record stays.
    """
    data = (json.dumps(record, indent=2) + "\n").encode("utf-8")
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


def _holder(busy: os_lease.Busy) -> str:
    """The holder text of a held lease."""
    text = busy.holder_body.decode("utf-8", "replace").strip()
    return text or "unknown"


def _wait_folder(ctx: Context) -> Path | str:
    """The wait record folder, or the reason when the common dir is unknown."""
    common = _common_dir(ctx)
    if isinstance(common, str):
        return common
    return common / WAIT_DIR


# --- verbs --------------------------------------------------------------------------


def _cmd_check(ctx: Context, rest: Sequence[str]) -> int:
    """Evaluate the conditions one time; exit 0 on hold, 1 when not."""
    parser = _Parser("session_wait.py check")
    _add_check_options(parser)
    args = parser.parse_args(list(rest))
    checks = _parse_checks(args.cond, args.exempt, args.credits_db, args.credits_lane)
    hold, line = _evaluate(ctx, checks)
    ctx.env.out(line)
    return EXIT_OK if hold else EXIT_NO


@dataclass(frozen=True)
class WaitArgs:
    """The validated options of ``wait``."""

    name: str
    plan: str
    owner: str
    direction: dict[str, str]
    poll_s: int
    stable_s: int
    cap_s: int
    receipt: Path | None
    checks: Checks


def _parse_wait(rest: Sequence[str]) -> WaitArgs:
    """Validate the options of ``wait``.

    Raises:
        UsageError: a missing or bad option.
    """
    parser = _Parser("session_wait.py wait")
    for option in (
        "--name",
        "--plan",
        "--owner",
        "--direction-session",
        "--direction-message",
        "--direction-quote",
        "--poll-s",
        "--stable-s",
        "--cap-s",
        "--receipt",
    ):
        parser.add_argument(option)
    _add_check_options(parser)
    args = parser.parse_args(list(rest))
    required = (
        ("--name", args.name),
        ("--plan", args.plan),
        ("--owner", args.owner),
        ("--cond", args.cond),
        ("--direction-session", args.direction_session),
        ("--direction-message", args.direction_message),
        ("--direction-quote", args.direction_quote),
    )
    for option, value in required:
        if value is None:
            raise UsageError(f"missing:{option}")
    if not NAME_RE.fullmatch(args.name):
        raise UsageError(f"bad_name:{args.name}")
    if not SLUG_RE.fullmatch(args.plan):
        raise UsageError(f"bad_slug:{args.plan}")
    if not args.owner.strip() or any(ch.isspace() for ch in args.owner):
        raise UsageError("bad_value:--owner")
    direction = {
        "session": str(args.direction_session),
        "message": str(args.direction_message),
        "quote": str(args.direction_quote),
    }
    for key, value in direction.items():
        if not value.strip():
            raise UsageError(f"bad_value:--direction-{key}")
    checks = _parse_checks(args.cond, args.exempt, args.credits_db, args.credits_lane)
    return WaitArgs(
        name=args.name,
        plan=args.plan,
        owner=args.owner,
        direction=direction,
        poll_s=_int_option(args.poll_s, "--poll-s", POLL_S, 1),
        stable_s=_int_option(args.stable_s, "--stable-s", STABLE_S, 0),
        cap_s=_int_option(args.cap_s, "--cap-s", CAP_S, 1),
        receipt=Path(args.receipt) if args.receipt else None,
        checks=checks,
    )


def _cmd_wait(ctx: Context, rest: Sequence[str]) -> int:
    """Arm one wait and poll until a stable hold (0) or the cap (5); 1 on a refusal."""
    opts = _parse_wait(rest)
    folder = _wait_folder(ctx)
    if isinstance(folder, str):
        ctx.env.out(f"wait_refused:{folder}")
        return EXIT_NO
    try:
        folder.mkdir(parents=True, exist_ok=True)
        lease = os_lease.acquire(
            folder / f"{opts.name}.lock",
            wait_s=LEASE_WAIT_S,
            body=f"{opts.owner}:{ctx.env.pid}".encode(),
        )
    except os_lease.Busy as busy:
        ctx.env.out(f"wait_refused:busy:{_holder(busy)}")
        return EXIT_NO
    except OSError:
        ctx.env.out("wait_refused:io_error")
        return EXIT_NO
    try:
        return _wait_held(ctx, opts, folder)
    finally:
        os_lease.release(lease)


def _wait_held(ctx: Context, opts: WaitArgs, folder: Path) -> int:
    """The body of ``wait`` while this process holds the lease."""
    path = folder / f"{opts.name}.json"
    try:
        old = _read_record(path)
    except RecordError:
        ctx.env.out(f"wait_refused:record_unreadable:{opts.name}")
        return EXIT_NO
    if old is not None and old["state"] in ("fired", "used"):
        ctx.env.out(f"wait_refused:{old['state']}")
        return EXIT_NO
    armed_utc = _utc_now()
    record: dict[str, object] = {
        "schema": SCHEMA,
        "name": opts.name,
        "plan": opts.plan,
        "conditions": [cond.text for cond in opts.checks.conditions],
        "exemptions": [item.text for item in opts.checks.exemptions],
        "owner": opts.owner,
        "pid": ctx.env.pid,
        "state": "armed",
        "direction": dict(opts.direction),
        "poll_s": opts.poll_s,
        "stable_s": opts.stable_s,
        "cap_s": opts.cap_s,
        "armed_utc": armed_utc,
        "stable_since_utc": None,
        "last_check": None,
        "ended_utc": None,
        "timeout": None,
    }
    receipt_path = (
        opts.receipt if opts.receipt is not None else folder / f"{opts.name}.log"
    )
    try:
        _write_record(path, record)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with receipt_path.open("w", encoding="utf-8", newline="\n") as receipt:
            return _poll(ctx, opts, path, record, receipt.write, receipt.flush)
    except OSError:
        ctx.env.out("wait_failed:io_error")
        return EXIT_NO


def _poll(
    ctx: Context,
    opts: WaitArgs,
    path: Path,
    record: dict[str, object],
    write: Callable[[str], object],
    flush: Callable[[], None],
) -> int:
    """The wait loop: check, record, then fire, time out or sleep.

    Raises:
        OSError: a record or receipt write failed.
    """

    def emit(line: str) -> None:
        write(line + "\n")
        flush()
        ctx.env.out(line)

    env = ctx.env
    start = env.clock()
    since: float | None = None
    previous: str | None = None
    while True:
        now = env.clock()
        hold, line = _evaluate(ctx, opts.checks)
        utc = _utc_now()
        if line != previous:
            emit(f"{utc} {line}")
            previous = line
        record["last_check"] = {"line": line, "utc": utc, "hold": hold}
        if hold:
            if since is None:
                since = now
                record["stable_since_utc"] = utc
        else:
            since = None
            record["stable_since_utc"] = None
        if since is not None and now - since >= opts.stable_s:
            record["state"] = "fired"
            record["ended_utc"] = utc
            _write_record(path, record)
            emit(f"wait_ok {line}")
            return EXIT_OK
        if now - start >= opts.cap_s:
            record["state"] = "timeout"
            record["ended_utc"] = utc
            record["timeout"] = {
                "limit_name": "cap_s",
                "configured_value": opts.cap_s,
                "observed_value": int(now - start),
                "window": {"from_utc": record["armed_utc"], "to_utc": utc},
            }
            _write_record(path, record)
            emit(f"wait_timeout last: {line}")
            return EXIT_TIMEOUT
        _write_record(path, record)
        env.sleep(opts.poll_s)


def _runner_state(lock: Path) -> str:
    """``alive`` when another process holds the lease, else ``dead``."""
    if not lock.exists():
        return "dead"
    try:
        lease = os_lease.acquire(lock, wait_s=0, body=b"")
    except os_lease.Busy:
        return "alive"
    except OSError:
        return "unknown"
    os_lease.release(lease)
    return "dead"


def _cmd_list(ctx: Context, rest: Sequence[str]) -> int:
    """Show each wait record: who waits for what, the state and the runner."""
    parser = _Parser("session_wait.py list")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(rest))
    folder = _wait_folder(ctx)
    paths = (
        sorted(folder.glob("*.json"))
        if isinstance(folder, Path) and folder.is_dir()
        else []
    )
    items: list[dict[str, object]] = []
    for path in paths:
        try:
            record = _read_record(path)
        except RecordError:
            items.append({"name": path.stem, "state": "unreadable"})
            continue
        if record is None:
            continue
        last = _str_keyed(record["last_check"])
        items.append(
            {
                "name": path.stem,
                "plan": record["plan"],
                "state": record["state"],
                "owner": record["owner"],
                "runner": _runner_state(path.with_suffix(".lock")),
                "conditions": record["conditions"],
                "last": last["line"] if last is not None else None,
            }
        )
    if args.json:
        ctx.env.out(json.dumps(items, indent=2))
        return EXIT_OK
    if not items:
        ctx.env.out("none")
    for item in items:
        if item["state"] == "unreadable":
            ctx.env.out(f"{item['name']} unreadable")
            continue
        conds = item["conditions"]
        joined = ",".join(str(c) for c in conds) if isinstance(conds, list) else ""  # pyright: ignore[reportUnknownVariableType]
        ctx.env.out(
            f"{item['name']} plan={item['plan']} state={item['state']} owner={item['owner']} "
            f"runner={item['runner']} conds={joined} last={item['last'] or 'none'}"
        )
    return EXIT_OK


def _cmd_use(ctx: Context, rest: Sequence[str]) -> int:
    """Change a ``fired`` record to ``used`` one time; 1 on a refusal."""
    parser = _Parser("session_wait.py use")
    parser.add_argument("--name")
    args = parser.parse_args(list(rest))
    if args.name is None:
        raise UsageError("missing:--name")
    if not NAME_RE.fullmatch(args.name):
        raise UsageError(f"bad_name:{args.name}")
    folder = _wait_folder(ctx)
    if isinstance(folder, str):
        ctx.env.out(f"use_refused:{folder}")
        return EXIT_NO
    path = folder / f"{args.name}.json"
    if not path.exists():
        ctx.env.out("use_refused:missing")
        return EXIT_NO
    try:
        lease = os_lease.acquire(
            folder / f"{args.name}.lock",
            wait_s=LEASE_WAIT_S,
            body=f"use:{ctx.env.pid}".encode(),
        )
    except os_lease.Busy as busy:
        ctx.env.out(f"use_refused:busy:{_holder(busy)}")
        return EXIT_NO
    except OSError:
        ctx.env.out("use_refused:io_error")
        return EXIT_NO
    try:
        try:
            record = _read_record(path)
        except RecordError:
            ctx.env.out(f"use_refused:record_unreadable:{args.name}")
            return EXIT_NO
        if record is None:
            ctx.env.out("use_refused:missing")
            return EXIT_NO
        if record["state"] != "fired":
            ctx.env.out(f"use_refused:{record['state']}")
            return EXIT_NO
        record["state"] = "used"
        try:
            _write_record(path, record)
        except OSError:
            ctx.env.out("use_refused:io_error")
            return EXIT_NO
        ctx.env.out(f"used {args.name}")
        return EXIT_OK
    finally:
        os_lease.release(lease)


def main(argv: Sequence[str] | None = None, *, env: Env | None = None) -> int:
    """Run one verb; 0 hold or done, 1 no hold or refused, 2 usage, 5 timeout."""
    seams = env if env is not None else Env()
    try:
        repo, rest = _split_repo(sys.argv[1:] if argv is None else argv)
        if not rest:
            raise UsageError("missing:verb")
        verb, rest = rest[0], rest[1:]
        if verb not in VERBS:
            raise UsageError(f"unknown_verb:{verb}")
        ctx = Context(repo=repo.resolve(), env=seams)
        if verb == "check":
            return _cmd_check(ctx, rest)
        if verb == "wait":
            return _cmd_wait(ctx, rest)
        if verb == "list":
            return _cmd_list(ctx, rest)
        return _cmd_use(ctx, rest)
    except UsageError as exc:
        seams.out(f"usage_error:{exc.reason}")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
