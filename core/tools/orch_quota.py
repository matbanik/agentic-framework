#!/usr/bin/env python3
"""The quota governor of the subscription runs.

Commands::

    orch_quota.py state
    orch_quota.py admit --kind claude [--run-id <id>]
    orch_quota.py admit --kind codex [--running <n>]
    orch_quota.py record --event codex_limit|codex_ok|probe_ok|probe_fail [--run-id] [--detail]
    orch_quota.py tick
    orch_quota.py breaker-reset --by <words>

The events and the rules are in the run store: ``tools/credits_state.py`` computes the window,
the limit and the breaker, and ``admit`` of the store makes the Claude decision in its
transaction. This tool reads that state with ``quota_view`` and adds its own events with
``quota_event``. The store call is the only process that it starts. ``admit --kind claude`` is a
preview: it writes nothing and admits nothing. The Codex wait is here, because a Codex review has
no run in the store.

``--now-utc`` sets the clock of a test store. The production store refuses it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import credits_state as cs  # noqa: E402

STATE_TOOL = ROOT / "tools" / "credits_state.py"
# I: a store call that hangs is a fault. The store waits for a busy writer for much less time.
STORE_TIMEOUT_S = 120
RUNNING_MAX = 64
RECORD_EVENTS = ("codex_limit", "codex_ok", "probe_ok", "probe_fail")
RESUME_COMMAND = (
    "pwsh -NoProfile -File .agent/skills/claude-credits/Start-CreditsRunTask.ps1"
    " -RunId {run_id} -StartedBy human-command -Resume -ResumeMode session"
)


class QuotaError(Exception):
    """A refusal of this tool, or an error of the store call; exit 3."""

    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message


def log(level: str, event: str, **fields: Any) -> None:
    """Write one JSON log line to stderr."""
    record = {"level": level, "event": event, **fields}
    sys.stderr.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def emit(payload: dict[str, Any], code: int) -> int:
    """Print one JSON object and return the exit code."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return code


def call_store(args: argparse.Namespace, *words: str) -> dict[str, Any]:
    """Run one store verb in its own process and return its answer."""
    argv = [sys.executable, "-I", str(STATE_TOOL), "--db", str(args.db)]
    if args.now_utc is not None:
        argv += ["--now-utc", str(args.now_utc)]
    try:
        proc = subprocess.run(
            [*argv, *words],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=STORE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QuotaError("store_call_failed", f"the store call failed: {exc}") from exc
    try:
        answer = json.loads(proc.stdout)
    except ValueError as exc:
        raise QuotaError(
            "store_call_failed",
            f"the store call gave no JSON (exit {proc.returncode}): {proc.stderr[-400:]}",
        ) from exc
    if not isinstance(answer, dict):
        raise QuotaError("store_call_failed", "the store answer is not an object")
    if proc.returncode != 0:
        raise QuotaError(
            str(answer.get("error") or "store_call_failed"),
            str(answer.get("message") or f"the store exited {proc.returncode}"),
        )
    return answer


def open_breaker(state: dict[str, Any]) -> bool:
    """True when the breaker of the state is open."""
    return bool(state["breaker"]["open"])


def answer_of(
    verdict: str,
    state: dict[str, Any],
    *,
    window: int,
    running: int,
    retry_after: str | None = None,
) -> dict[str, Any]:
    """The answer of ``admit``."""
    return {
        "verdict": verdict,
        "window": window,
        "running": running,
        "limited": state["limited"],
        "resets_at_utc": state["resets_at_utc"],
        "retry_after_utc": retry_after,
    }


def claude_verdict(view: dict[str, Any], run_id: str | None) -> dict[str, Any]:
    """The verdict that the store admit of a subscription run would give now."""
    state = view["state"]
    running = int(view["open_segments"])
    window = int(state["window"])
    verdict, retry = "allow", None
    if run_id is not None and run_id not in view["routes"]:
        raise QuotaError("unknown_run", f"no run {run_id!r} in the store")
    if run_id is None or view["routes"][run_id] == "subscription":
        if open_breaker(state):
            verdict = "breaker_open"
        elif state["limited"]:
            verdict, retry = "parked_quota", state["limit_ends_utc"]
        elif running >= window:
            verdict = "at_capacity"
    return answer_of(verdict, state, window=window, running=running, retry_after=retry)


def codex_wait(
    events: Sequence[dict[str, Any]],
) -> tuple[int, int, datetime | None]:
    """The limit replies since the last good one, the wait in seconds, and the time it ends."""
    count = 0
    last: datetime | None = None
    for event in events:
        if event["kind"] == "codex_ok":
            count, last = 0, None
        elif event["kind"] == "codex_limit":
            count, last = count + 1, cs.parse_utc(str(event["at_utc"]))
    if last is None:
        return 0, 0, None
    # The exponent is bounded, so a long log gives no large number.
    wait = min(
        cs.CODEX_BACKOFF_MAX_S, cs.CODEX_BACKOFF_BASE_S * 2 ** min(count - 1, 16)
    )
    return count, wait, last + timedelta(seconds=wait)


def log_codex_refusal(
    reason: str, limit_name: str, configured: int, observed: int, window: str
) -> None:
    """Write the refusal of one Codex review with its limit facts."""
    log(
        "warning",
        "codex_review_refused",
        reason=reason,
        limit_name=limit_name,
        configured_value=configured,
        observed_value=observed,
        window=window,
    )


def codex_verdict(view: dict[str, Any], running: int) -> dict[str, Any]:
    """The verdict for one more Codex review while ``running`` reviews run."""
    from tools import orch

    state = view["state"]
    now = cs.parse_utc(str(view["now_utc"]))
    limits, wait, free_at = codex_wait(view["events"])
    verdict, retry = "allow", None
    if open_breaker(state):
        verdict = "breaker_open"
        cause = len(state["breaker"]["cause"])
        window = f"{cs.BREAKER_WINDOW_S} s"
        log_codex_refusal(
            verdict, "restarts_per_hour", cs.BREAKER_RESTARTS, cause, window
        )
    elif free_at is not None and now < free_at:
        verdict, retry = "codex_backoff", cs.format_utc(free_at)
        log_codex_refusal(
            verdict, "codex_backoff_s", wait, limits, "since the last codex_ok"
        )
    elif running >= orch.REVIEW_CAP:
        verdict = "at_capacity"
        log_codex_refusal(verdict, "reviews", orch.REVIEW_CAP, running, "now")
    return answer_of(
        verdict, state, window=orch.REVIEW_CAP, running=running, retry_after=retry
    )


def probe_due(view: dict[str, Any], now: datetime) -> bool:
    """True when no reset time is known and the last probe is ``PROBE_EVERY_S`` ago."""
    state = view["state"]
    if open_breaker(state) or not state["limited"] or state["resets_at_utc"]:
        return False
    times = [
        cs.parse_utc(str(limit["at_utc"]))
        for limit in state["limits"]
        if limit["ended_utc"] is None
    ]
    times += [
        cs.parse_utc(str(event["at_utc"]))
        for event in view["events"]
        if event["kind"] in ("probe_ok", "probe_fail")
    ]
    return now - max(times) >= timedelta(seconds=cs.PROBE_EVERY_S)


def resumes_due(view: dict[str, Any]) -> list[dict[str, Any]]:
    """Each stopped run whose own usage limit has ended and that has no later segment."""
    ended = {
        limit["segment_id"]: limit["ended_utc"]
        for limit in view["state"]["limits"]
        if limit["ended_utc"] is not None
    }
    return [
        {
            "run_id": row["run_id"],
            "segment_id": row["segment_id"],
            "resets_at_utc": row["resets_at_utc"],
            "due_utc": ended[row["segment_id"]],
            "command": RESUME_COMMAND.format(run_id=row["run_id"]),
        }
        for row in view["limit_segments"]
        if row["segment_id"] in ended and row["run_state"] == "stopped"
    ]


def tick_of(view: dict[str, Any]) -> dict[str, Any]:
    """What is due now. It starts nothing."""
    state = view["state"]
    return {
        "window": state["window"],
        "limited": state["limited"],
        "probe_due": probe_due(view, cs.parse_utc(str(view["now_utc"]))),
        "resumes_due": resumes_due(view),
        "parked_starts": view["parked_starts"],
        "breaker": state["breaker"],
    }


def record(args: argparse.Namespace) -> dict[str, Any]:
    """Add one event of this tool to the store."""
    if args.event in cs.QUOTA_OWNED_KINDS:
        raise QuotaError(
            "event_owned_by_store",
            f"{args.event} is written by the store verb that makes the move",
        )
    words = ["--kind", str(args.event)]
    if args.run_id is not None:
        words += ["--run-id", str(args.run_id)]
    if args.detail is not None:
        words.append(f"--detail={args.detail}")
    return call_store(args, "quota_event", *words)


def breaker_reset(args: argparse.Namespace) -> dict[str, Any]:
    """Close the breaker; ``--by`` names the human who decided."""
    by = str(args.by).strip()
    if not by:
        raise QuotaError("by_missing", "--by names the human who closes the breaker")
    log("warning", "quota_breaker_reset", by=by)
    return call_store(args, "quota_event", "--kind", "breaker_reset", f"--detail={by}")


def running_count(text: str) -> int:
    """The ``--running`` value: 0 to ``RUNNING_MAX``."""
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from exc
    if not 0 <= value <= RUNNING_MAX:
        raise argparse.ArgumentTypeError(f"not in 0..{RUNNING_MAX}: {value}")
    return value


def detail_text(text: str) -> str:
    """The ``--detail`` value: one line, at most ``QUOTA_DETAIL_MAX`` characters."""
    if len(text) > cs.QUOTA_DETAIL_MAX or len(text.splitlines()) != 1:
        raise argparse.ArgumentTypeError(
            f"not one line of 1 to {cs.QUOTA_DETAIL_MAX} characters"
        )
    return text


def build_parser() -> argparse.ArgumentParser:
    """The command line."""
    parser = argparse.ArgumentParser(
        prog="orch_quota.py", allow_abbrev=False, description="The quota governor."
    )
    parser.add_argument("--db", default=cs.PRODUCTION_DB)
    parser.add_argument("--now-utc")
    verbs = parser.add_subparsers(dest="verb", required=True)
    verbs.add_parser("state", allow_abbrev=False)
    verbs.add_parser("tick", allow_abbrev=False)
    admit = verbs.add_parser("admit", allow_abbrev=False)
    admit.add_argument("--kind", required=True, choices=("claude", "codex"))
    admit.add_argument("--run-id")
    admit.add_argument("--running", type=running_count)
    event = verbs.add_parser("record", allow_abbrev=False)
    event.add_argument(
        "--event", required=True, choices=(*RECORD_EVENTS, *cs.QUOTA_OWNED_KINDS)
    )
    event.add_argument("--run-id")
    event.add_argument("--detail", type=detail_text)
    reset = verbs.add_parser("breaker-reset", allow_abbrev=False)
    reset.add_argument("--by", required=True, type=detail_text)
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Run one verb and return its answer."""
    if args.now_utc is not None and cs.is_production_db(Path(args.db)):
        raise QuotaError(
            "clock_seam_refused", "--now-utc is not read for the production store"
        )
    verb = str(args.verb)
    if verb == "record":
        return record(args)
    if verb == "breaker-reset":
        return breaker_reset(args)
    if verb == "admit" and args.kind == "claude" and args.running is not None:
        raise QuotaError("running_refused", "--running is for --kind codex only")
    if verb == "admit" and args.kind == "codex" and args.run_id is not None:
        raise QuotaError("run_id_refused", "--run-id is for --kind claude only")
    view = call_store(args, "quota_view")
    if verb == "state":
        return {
            **view["state"],
            "open_segments": view["open_segments"],
            "now_utc": view["now_utc"],
        }
    if verb == "tick":
        return tick_of(view)
    if args.kind == "claude":
        return claude_verdict(view, args.run_id)
    return codex_verdict(view, args.running or 0)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return the exit code."""
    args = build_parser().parse_args(argv)
    try:
        return emit(run(args), cs.EXIT_OK)
    except QuotaError as exc:
        log("error", "quota_refused", error=exc.error, message=exc.message)
        return emit({"error": exc.error, "message": exc.message}, cs.EXIT_REFUSED)


if __name__ == "__main__":
    sys.exit(main())
