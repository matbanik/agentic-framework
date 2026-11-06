#!/usr/bin/env python3
"""Install and gate the credits kit on a fleet member. A fleet ``run`` task starts it in a slot.

``install`` builds FLEET_HOME/kit from the slot's ``core/`` and swaps it in. ``gate`` runs the M-1 gate on the
subscription token, in the environment a scheduled run gets. Refusals print ``<reason>: <detail>`` on stderr and
exit 1. Plan: docs/execution/plans/2026-11-04-fleet-agents/implementation-plan.md
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SLOT = Path(__file__).resolve().parents[2]
TASK_QUERY = (
    "Get-ScheduledTask -TaskPath '\\Fleet\\*' -ErrorAction SilentlyContinue"
    " | Where-Object State -eq 'Running'"
    " | ForEach-Object { $_.TaskPath + $_.TaskName }"
)
MONITOR_TASK = "\\Fleet\\Credits\\Monitor"
TASK_QUERY_TIMEOUT_S = 60
HOOK_EVENTS = (("PostToolUse", "*"), ("Stop", None))
INBOX_HOOK = ".claude/hooks/credits_inbox.py"
GATE_SCRIPT = ".agent/skills/claude-credits/probes/run_gate.py"
REMOVED_FROM_GATE = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
REDACTED = b"[redacted]"


class KitRefusal(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)


def fleet_home() -> Path:
    return Path(os.environ.get("FLEET_HOME") or Path.home() / ".agent" / "fleet")


def refuse_active_run() -> None:
    """Refuse if a run's task is Running. A task list that can't be read counts as a running task."""
    pwsh = shutil.which("pwsh")
    if not pwsh:
        raise KitRefusal("run_active", "pwsh is missing, so the task list can't be read")
    try:
        r = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-Command", TASK_QUERY],
            capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=TASK_QUERY_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise KitRefusal("run_active", "the task list timed out") from None
    if r.returncode:
        raise KitRefusal("run_active", f"the task list failed with exit {r.returncode}")
    tasks = [line.strip() for line in r.stdout.splitlines() if line.strip()]
    running = [t for t in tasks if t.casefold() != MONITOR_TASK.casefold()]
    if running:
        raise KitRefusal("run_active", ", ".join(running))


def read_json(path: Path, refusal: str) -> dict:
    """A JSON object from a file, or {} if there is no file."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise KitRefusal(refusal, f"{path}: {e}") from None
    if not isinstance(doc, dict):
        raise KitRefusal(refusal, f"{path}: the top level is not an object")
    return doc


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def settings_path() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def read_settings(path: Path) -> dict:
    settings = read_json(path, "settings_invalid")
    hooks = settings.get("hooks", {})
    if not (isinstance(hooks, dict) and all(isinstance(entries, list) for entries in hooks.values())):
        raise KitRefusal("settings_invalid", f"{path}: hooks is not an object of lists")
    return settings


def merge_hooks(path: Path, settings: dict, kit: Path) -> None:
    """Add the inbox hook at user level: a slot has no settings of its own. Repeating this adds nothing."""
    command = f'"{Path(sys.executable).as_posix()}" "{(kit / INBOX_HOOK).as_posix()}"'
    hooks = settings.setdefault("hooks", {})
    changed = False
    for event, matcher in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        have = [h.get("command") for e in entries if isinstance(e, dict) for h in e.get("hooks", []) if isinstance(h, dict)]
        if command not in have:
            entries.append({**({"matcher": matcher} if matcher else {}), "hooks": [{"type": "command", "command": command}]})
            changed = True
    if changed:
        write_json(path, settings)


def remove_tree(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise KitRefusal("kit_busy", f"can't delete {path}: {e}") from None


def run_instantiate(reason: str, *args: str) -> None:
    code = subprocess.run([sys.executable, str(SLOT / "scripts" / "instantiate.py"), *args], stdin=subprocess.DEVNULL).returncode
    if code:
        raise KitRefusal(reason, f"instantiate.py exit {code}")


def build_kit(home: Path, new: Path) -> None:
    """Fill kit-new. The project root is FLEET_HOME, so the Codex wrapper accepts a slot as its working folder."""
    tasks = SLOT / ".agent" / "fleet" / "fleet-tasks.ps1"
    if not tasks.is_file():
        raise KitRefusal("tasks_missing", f"no {tasks.as_posix()}")
    shutil.copytree(SLOT / "core", new, ignore=shutil.ignore_patterns("__pycache__"))
    receipts = (home / "receipts").as_posix()
    with tempfile.TemporaryDirectory(prefix="fleet-kit-") as tmp:
        config = Path(tmp) / "kit.vars"
        config.write_text(
            "PROJECT_NAME=fleet\n"
            f"PROJECT_ROOT={home.as_posix()}\n"
            f"RECEIPTS_DIR={receipts}\n"
            "REPO_URL=fleet.invalid/fleet\n"
            "CREDITS_START_POLICY=agent-on-user-chat\n",
            encoding="utf-8",
        )
        run_instantiate("kit_build_failed", "--root", str(new), "--config", str(config))
    run_instantiate("kit_verify_failed", "--root", str(new), "--verify", "--receipts-dir", receipts)
    (new / "fleet").mkdir(exist_ok=True)
    shutil.copyfile(tasks, new / "fleet" / tasks.name)


def swap_kit(home: Path) -> None:
    """Rename kit aside, kit-new to kit, and delete the old copy. A rename failing on a held file restores kit."""
    kit, new, old = home / "kit", home / "kit-new", home / "kit-old"
    had_kit = kit.exists()
    try:
        if had_kit:
            os.rename(kit, old)
        try:
            os.rename(new, kit)
        except OSError:
            if had_kit:
                os.rename(old, kit)
            raise
    except OSError as e:
        raise KitRefusal("kit_busy", str(e)) from None
    shutil.rmtree(old, ignore_errors=True)


def install() -> int:
    home = fleet_home()
    kit, new = home / "kit", home / "kit-new"
    refuse_active_run()
    # Both files are read before anything changes, so a bad one leaves the old kit in place.
    user_settings = settings_path()
    settings = read_settings(user_settings)
    launcher_path = home / "receipts" / "credits" / "launcher.env.json"
    launcher = read_json(launcher_path, "launcher_env_invalid")
    home.mkdir(parents=True, exist_ok=True)
    remove_tree(home / "kit-old")
    remove_tree(new)
    try:
        build_kit(home, new)
        swap_kit(home)
    finally:
        shutil.rmtree(new, ignore_errors=True)
    tools = Path.home() / ".agent" / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SLOT / ".agent" / "tools" / "ModelRegistry.psm1", tools / "ModelRegistry.psm1")
    launcher.setdefault("env", {})["FLEET_CODEX_LOCK"] = (home / "codex.lock").as_posix()
    write_json(launcher_path, launcher)
    merge_hooks(user_settings, settings, kit)
    print(f"kit installed: {kit.as_posix()}", flush=True)
    return 0


def read_token(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8-sig").strip()
    except (OSError, ValueError):
        token = ""
    if not token:
        raise KitRefusal("token_missing", f"no token in {path}")
    return token


def gate() -> int:
    """Run the gate with the token, then check that nothing it left behind holds the token's bytes."""
    home = fleet_home()
    script = home / "kit" / GATE_SCRIPT
    if not script.is_file():
        raise KitRefusal("kit_missing", f"no {script}")
    token = read_token(home / "credentials" / "claude-oauth-token")
    claude = shutil.which("claude")
    if not claude:
        raise KitRefusal("tool_missing:claude")
    receipts, project = home / "receipts" / "gate", home / "gate-project"
    for folder in (receipts, project):
        remove_tree(folder)
        folder.mkdir(parents=True)
    env = {name: value for name, value in os.environ.items() if name not in REMOVED_FROM_GATE}
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] = "1"
    argv = [
        sys.executable, str(script), "--out", str(receipts), "--project", str(project),
        "--python", sys.executable, "--claude", claude,
    ]
    r = subprocess.run(argv, env=env, cwd=project, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    needle = token.encode()
    # The log goes to the hub as a blob.
    sys.stdout.buffer.write(r.stdout.replace(needle, REDACTED))
    sys.stdout.buffer.flush()
    held = [p for folder in (receipts, project) for p in folder.rglob("*") if p.is_file() and needle in p.read_bytes()]
    if held:
        for folder in (receipts, project):
            shutil.rmtree(folder, ignore_errors=True)
        left = [p for p in held if p.exists()]
        raise KitRefusal("gate_token_leak", f"{len(held)} files held the token, {len(left)} could not be deleted")
    return r.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install and gate the credits kit on a fleet member.")
    parser.add_argument("action", choices=("install", "gate"))
    args = parser.parse_args(argv)
    try:
        return install() if args.action == "install" else gate()
    except KitRefusal as e:
        print(e, file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
