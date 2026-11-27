#!/usr/bin/env python3
"""The stream-json capture of a credits dispatch.

``Invoke-ClaudeCredits.ps1`` runs the CLI with ``--output-format stream-json`` into a stream file
and then runs this tool::

    credits_stream.py split --from-stream --out <output.json> --stream <stream.jsonl>
    credits_stream.py split --out <output.json> --stream <stream.jsonl>
    credits_stream.py signals --stream <stream.jsonl> [--max-bytes <n>]

``split`` reads the stream file (``--from-stream``), or copies each line of standard input to
``--stream`` at once, so a killed run keeps the lines that arrived. It writes the last ``type:
result`` object to ``--out`` (UTF-8, no BOM), which is the file that the dispatcher reads. It exits
0 or 1 by the ``is_error`` of that object, and 3 when no result line arrived; then it writes no
``--out`` file. A rejected rate limit event after the last result line starts a turn that has no
result, so that result does not count. With ``--from-stream``, a nonzero CLI exit code in
``{{PROJECT_NAME_UPPER}}_CREDITS_CLI_EXIT`` replaces the exit code of this tool, so a failed CLI
stays a failed dispatch.

``signals`` prints one JSON object with the rate limit and result facts of a stream. It prints no
message text. It exits 3 when the file is missing (``stream_missing``) or above ``--max-bytes``
(``stream_too_large``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, BinaryIO

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NO_RESULT = 3
EXIT_REFUSED = 3

# The variable in which the launch line keeps a nonzero exit code of the CLI.
CLI_EXIT_ENV = "{{PROJECT_NAME_UPPER}}_CREDITS_CLI_EXIT"

# STREAM_MAX_BYTES: the largest stream that ``signals`` reads.
STREAM_MAX_BYTES = 64 * 1024 * 1024


def parse_line(raw: bytes) -> dict[str, Any] | None:
    """Return the JSON object of one stream line, or None."""
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def is_rejected(line: dict[str, Any]) -> bool:
    """Return whether a stream line is a rejected rate limit event."""
    info = line.get("rate_limit_info")
    return (
        line.get("type") == "rate_limit_event"
        and isinstance(info, dict)
        and info.get("status") == "rejected"
    )


def cli_exit() -> int:
    """Return the exit code of a failed CLI, or 0; an unreadable value is a failure."""
    text = os.environ.get(CLI_EXIT_ENV, "").strip()
    if not text:
        return EXIT_OK
    try:
        return int(text)
    except ValueError:
        return EXIT_ERROR


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write one JSON file through a partial file, so a reader never sees half of it."""
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    os.replace(partial, path)


def copied(source: BinaryIO, stream: Path) -> Iterator[bytes]:
    """Yield each line of the source after its copy is in the stream file."""
    with open(stream, "ab") as copy:
        for raw in iter(source.readline, b""):
            copy.write(raw)
            copy.flush()
            yield raw


def split(lines: Iterable[bytes], out: Path) -> int:
    """Write the last result line of the stream; return the exit code."""
    last: dict[str, Any] | None = None
    bad = 0
    for raw in lines:
        if not raw.strip():
            continue
        parsed = parse_line(raw)
        if parsed is None:
            bad += 1
        elif parsed.get("type") == "result":
            last = parsed
        elif is_rejected(parsed):
            last = None  # the result of an earlier turn
    if bad:
        sys.stderr.write(f"credits_stream: {bad} lines are not JSON objects\n")
    if last is None:
        sys.stderr.write("credits_stream: no_result_line\n")
        return EXIT_NO_RESULT
    write_json(out, last)
    return EXIT_ERROR if last.get("is_error") else EXIT_OK


def denial_count(value: Any) -> int:
    """Count the permission denials: a list by its length, any other value as one."""
    if value is None:
        return 0
    return len(value) if isinstance(value, list) else 1


def reset_time(info: Any) -> int | None:
    """Return the reset time of a rate limit record, or None."""
    value = info.get("resetsAt") if isinstance(info, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def signals(source: BinaryIO) -> dict[str, Any]:
    """Return the rate limit and result facts of a stream."""
    events = 0
    lines = 0
    bad = 0
    last_info: dict[str, Any] | None = None
    last_rejected: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    for raw in iter(source.readline, b""):
        if not raw.strip():
            continue
        lines += 1
        parsed = parse_line(raw)
        if parsed is None:
            bad += 1
            continue
        kind = parsed.get("type")
        if kind == "rate_limit_event":
            events += 1
            info = parsed.get("rate_limit_info")
            last_info = info if isinstance(info, dict) else {}
            if is_rejected(parsed):
                last_rejected = last_info
                result = None  # the result of an earlier turn
        elif kind == "result":
            result = parsed
    reset_source = last_rejected if last_rejected is not None else last_info
    return {
        "rate_limit_events": events,
        "last_rate_limit": None
        if last_info is None
        else {
            "status": last_info.get("status"),
            "resetsAt": reset_time(last_info),
            "rateLimitType": last_info.get("rateLimitType"),
            "overageStatus": last_info.get("overageStatus"),
        },
        "rejected": last_rejected is not None,
        "resets_at": reset_time(reset_source),
        "result": None
        if result is None
        else {
            "subtype": result.get("subtype"),
            "is_error": result.get("is_error"),
            "stop_reason": result.get("stop_reason"),
            "permission_denials": denial_count(result.get("permission_denials")),
            "total_cost_usd": result.get("total_cost_usd"),
        },
        "lines": lines,
        "bad_lines": bad,
    }


def refuse(record: dict[str, Any]) -> int:
    """Print the record of a refusal and return its exit code."""
    sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")
    sys.stderr.write(f"credits_stream: {record['error']}\n")
    return EXIT_REFUSED


def read_signals(stream: Path, max_bytes: int) -> int:
    """Print the facts of a stream file, or refuse a missing or large file."""
    if not stream.is_file():
        return refuse({"error": "stream_missing"})
    with open(stream, "rb") as source:
        size = os.fstat(source.fileno()).st_size
        if size > max_bytes:
            return refuse(
                {
                    "error": "stream_too_large",
                    "limit_name": "stream_max_bytes",
                    "configured_value": max_bytes,
                    "observed_value": size,
                    "window": "one stream",
                }
            )
        found = signals(source)
    sys.stdout.write(json.dumps(found, separators=(",", ":")) + "\n")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Return the command line parser."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    verbs = parser.add_subparsers(dest="verb", required=True)
    split_verb = verbs.add_parser("split", help="copy a stream and keep its result")
    split_verb.add_argument("--out", type=Path, required=True)
    split_verb.add_argument("--stream", type=Path, required=True)
    split_verb.add_argument(
        "--from-stream", action="store_true", help="read --stream, not standard input"
    )
    signals_verb = verbs.add_parser("signals", help="print the facts of a stream")
    signals_verb.add_argument("--stream", type=Path, required=True)
    signals_verb.add_argument("--max-bytes", type=int, default=STREAM_MAX_BYTES)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one verb and return its exit code."""
    args = build_parser().parse_args(argv)
    try:
        if args.verb == "split":
            if not args.from_stream:
                return split(copied(sys.stdin.buffer, args.stream), args.out)
            with open(args.stream, "rb") as kept:
                code = split(kept, args.out)
            return cli_exit() or code
        return read_signals(args.stream, args.max_bytes)
    except OSError as error:
        sys.stderr.write(f"credits_stream: {type(error).__name__}: {error}\n")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
