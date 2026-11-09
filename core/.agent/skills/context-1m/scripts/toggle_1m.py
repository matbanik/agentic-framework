"""Toggle the 1M context window for every Claude Code session on this machine.

Claude Code reads ``env.CLAUDE_CODE_DISABLE_1M_CONTEXT`` from the user settings file
(``~/.claude/settings.json``). When the key is present with value ``"1"`` the 1M
context window is disabled for all models; when the key is absent, the models that
offer a native 1M window run with it.

Usage::

    python toggle_1m.py status          # report the current state, change nothing
    python toggle_1m.py on              # enable 1M  -> remove the key
    python toggle_1m.py off             # disable 1M -> set the key to "1"
    python toggle_1m.py on --settings <path>   # operate on another settings file

Exit codes: 0 success; 2 bad arguments, or the settings file is unreadable, not JSON,
or has an ``env`` value that is not an object (nothing is written in that case).
A missing settings file reads as "on" (no key); ``off`` then creates it.
The file is rewritten with two-space indentation and a trailing newline, which is
the format Claude Code itself writes. A backup ``settings.json.1m-backup`` is
written beside the file before every change to an existing file. New sessions read
settings at start; running sessions have been observed to pick the change up live
as well.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

KEY = "CLAUDE_CODE_DISABLE_1M_CONTEXT"
DISABLED_VALUE = "1"


def default_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{path} top level is not a JSON object")
    return data


def state(data: dict) -> str:
    env = data.get("env")
    if isinstance(env, dict) and str(env.get(KEY, "")).strip() == DISABLED_VALUE:
        return "off"
    return "on"


def save(path: Path, data: dict) -> str:
    """Write ``data``; back up an existing file first. Return a note for the user."""
    if path.exists():
        backup = path.with_name(path.name + ".1m-backup")
        shutil.copyfile(path, backup)
        note = f"backup at {backup.name}"
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        note = "file created"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return note


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("status", "on", "off"))
    parser.add_argument("--settings", type=Path, default=default_settings_path())
    args = parser.parse_args(argv)

    data = load(args.settings)
    current = state(data)

    if args.action == "status":
        detail = 'set to "1"' if current == "off" else "absent"
        print(f"1M context: {current} ({args.settings})")
        print(f"  env.{KEY} is {detail}")
        return 0

    if args.action == current:
        print(f"1M context already {current}; nothing changed ({args.settings})")
        return 0

    env = data.get("env")
    if env is None:
        env = {}
        data["env"] = env
    if not isinstance(env, dict):
        raise SystemExit(f"{args.settings}: 'env' exists but is not an object; fix it by hand")

    if args.action == "off":
        env[KEY] = DISABLED_VALUE
    else:
        env.pop(KEY, None)
        if not env:
            del data["env"]

    note = save(args.settings, data)
    print(f"1M context: {current} -> {args.action} ({args.settings}); {note}")
    print("New sessions pick this up at start; running sessions may pick it up live and compact at once if they are above the new window.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            sys.exit(2)
        raise
