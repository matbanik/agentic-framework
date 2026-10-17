"""Shared plumbing for the messaging probe kit.

Every path to kit code comes from KIT_DIR (the directory that holds this file).
Every output goes under OUT, which the caller chooses. The kit never writes to KIT_DIR.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # imports must not create __pycache__ inside the kit

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

KIT_DIR = Path(__file__).resolve().parent


class ConfigError(Exception):
    """Usage or configuration problem (missing claude, unwritable OUT, bad interpreter)."""


@dataclass(frozen=True)
class Config:
    out: Path
    project: Path
    python: str
    claude: str | None

    def require_claude(self) -> str:
        if not self.claude:
            raise ConfigError("claude not found: pass --claude, set MSG_PROBE_CLAUDE, or put it on PATH")
        return self.claude


def add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", help="scratch output dir (or env MSG_PROBE_OUT); required")
    parser.add_argument("--project", help="project dir for claude (or env MSG_PROBE_PROJECT); default cwd")
    parser.add_argument("--python", help="interpreter for hook commands (or env MSG_PROBE_PYTHON); default sys.executable")
    parser.add_argument("--claude", help="claude executable (or env MSG_PROBE_CLAUDE); default from PATH")


def config_from_args(args: argparse.Namespace, need_claude: bool = True) -> Config:
    out_raw = args.out or os.environ.get("MSG_PROBE_OUT")
    if not out_raw:
        raise ConfigError("no output dir: pass --out or set MSG_PROBE_OUT")
    out = Path(os.path.abspath(out_raw))
    resolved = out.resolve()
    if resolved == KIT_DIR or KIT_DIR in resolved.parents:
        raise ConfigError(f"OUT must not be inside the kit dir: {out}")
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ConfigError(f"OUT is not writable: {out} ({exc})") from exc

    proj_raw = args.project or os.environ.get("MSG_PROBE_PROJECT") or os.getcwd()
    project = Path(os.path.abspath(proj_raw))
    if not project.is_dir():
        raise ConfigError(f"project dir does not exist: {project}")

    python = resolve_python(args.python or os.environ.get("MSG_PROBE_PYTHON") or sys.executable)

    claude_raw = args.claude or os.environ.get("MSG_PROBE_CLAUDE") or shutil.which("claude")
    claude = None
    if claude_raw:
        claude = shutil.which(claude_raw) or (claude_raw if Path(claude_raw).is_file() else None)
        if claude is None:
            raise ConfigError(f"claude not found: {claude_raw}")
    if need_claude and not claude:
        raise ConfigError("claude not found: pass --claude, set MSG_PROBE_CLAUDE, or put it on PATH")
    return Config(out=out, project=project, python=python, claude=claude)


def resolve_python(py_raw: str) -> str:
    """The resolved forward-slash path of an interpreter, from a path or a name on PATH.

    resolve() gives the on-disk spelling, so two spellings of one file compare equal.
    """
    if Path(py_raw).is_file():
        return Path(py_raw).resolve().as_posix()
    found = shutil.which(py_raw)
    if not found:
        raise ConfigError(f"interpreter not found: {py_raw}")
    return Path(found).resolve().as_posix()


def kit_script(name: str) -> Path:
    path = KIT_DIR / name
    if not path.is_file():
        raise ConfigError(f"kit script missing: {path}")
    return path


def hook_command(cfg: Config, script: str) -> str:
    """One hook command line. Interpreter and script are both quoted; slashes are forward."""
    return f'"{cfg.python}" "{kit_script(script).as_posix()}"'


def render_settings(cfg: Config, name: str = "settings.json",
                    post_hooks: tuple[str, ...] = ("inbox_hook.py",),
                    stop_hooks: tuple[str, ...] = ("inbox_hook.py",)) -> Path:
    """Render a hook settings file into OUT and return its path."""
    hooks: dict[str, Any] = {}
    if post_hooks:
        hooks["PostToolUse"] = [{"matcher": "*", "hooks": [
            {"type": "command", "command": hook_command(cfg, s)} for s in post_hooks]}]
    if stop_hooks:
        hooks["Stop"] = [{"hooks": [
            {"type": "command", "command": hook_command(cfg, s)} for s in stop_hooks]}]
    path = cfg.out / name
    path.write_text(json.dumps({"hooks": hooks}, indent=2), encoding="utf-8")
    return path


def render_empty_settings(cfg: Config, name: str = "settings-empty.json") -> Path:
    path = cfg.out / name
    path.write_text("{}", encoding="utf-8")
    return path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def kit_hashes() -> dict[str, str]:
    return {p.name: sha256_file(p) for p in sorted(KIT_DIR.glob("*.py"))}


def kit_revision() -> str:
    """One hash over every kit .py file (name and content), so a receipt names the kit it ran."""
    return hashlib.sha256(json.dumps(kit_hashes(), sort_keys=True).encode("utf-8")).hexdigest()


_VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+)(?![\d.])")


def cli_version(claude: str) -> str | None:
    """The parsed `claude --version` (for example "2.1.296"), or None.

    None when the command cannot start, times out, exits nonzero, or prints no leading
    MAJOR.MINOR.PATCH. A receipt with None can never qualify.
    """
    try:
        proc = subprocess.run([claude, "--version"], capture_output=True, text=True,
                              encoding="utf-8", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    match = _VERSION_RE.match(proc.stdout.strip())
    return match.group(1) if match else None


def _run_text(argv: list[str]) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ERROR {type(exc).__name__}: {exc}"
    return (proc.stdout + proc.stderr).strip()


# Keys that select, add or suppress hook sources but have no "hook" in their name. Every key
# whose name contains "hook" (any case) is also hashed, so a new hook-policy key fails closed
# (round-6 finding 3: allowManagedHooksOnly was outside the old whitelist).
HOOK_SETTING_KEYS = ("env", "enabledPlugins", "disableCommandPluginSources")


def hook_setting_keys(data: dict[str, Any]) -> list[str]:
    """The keys of one settings object that can change which hooks run, or how."""
    return sorted(k for k in data if "hook" in k.lower() or k in HOOK_SETTING_KEYS)


def settings_sources(project: Path) -> dict[str, Path]:
    """The settings files that the CLI merges into the hooks of a run in PROJECT."""
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    sources = {
        "user": config_dir / "settings.json",
        "project": project / ".claude" / "settings.json",
        "project_local": project / ".claude" / "settings.local.json",
    }
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles") or "C:/Program Files")
        sources["managed"] = program_files / "ClaudeCode" / "managed-settings.json"
    return sources


def hook_settings_digest(path: Path) -> str:
    """SHA-256 of the hook-relevant keys of one settings file; "absent" or "unreadable" else."""
    if not path.is_file():
        return "absent"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"
    if not isinstance(data, dict):
        return "unreadable"
    part = {k: data[k] for k in hook_setting_keys(data)}
    return hashlib.sha256(json.dumps(part, sort_keys=True).encode("utf-8")).hexdigest()


def launch_profile(project: Path, python: str) -> dict[str, Any]:
    """The hook interpreter and the effective hook settings that a run in PROJECT gets.

    A receipt is valid only for the profile it was made with (report.md section 4.6.6).
    """
    profile: dict[str, Any] = {
        "hook_python": python,
        "hook_python_version": _run_text([python, "--version"]),
        "hook_settings": {name: hook_settings_digest(p)
                          for name, p in settings_sources(project).items()},
    }
    profile["profile_sha256"] = hashlib.sha256(
        json.dumps(profile, sort_keys=True).encode("utf-8")).hexdigest()
    return profile


def identity(cfg: Config, settings: list[Path], live: bool) -> dict[str, Any]:
    """Who ran this: kit code hashes, rendered settings hashes, interpreter, project, claude."""
    info: dict[str, Any] = {
        "kit_dir": KIT_DIR.as_posix(),
        "kit_sha256": kit_hashes(),
        "kit_revision": kit_revision(),
        "settings_sha256": {p.name: sha256_file(p) for p in settings if p.is_file()},
        "python": cfg.python,
        "python_version": _run_text([cfg.python, "--version"]),
        "project": cfg.project.as_posix(),
        "out": cfg.out.as_posix(),
        "launch_profile": launch_profile(cfg.project, cfg.python),
    }
    if live:
        claude = cfg.require_claude()
        info["claude"] = claude
        info["claude_version_raw"] = _run_text([claude, "--version"])
        info["claude_version"] = cli_version(claude)
    return info


def fresh_inbox(cfg: Config, name: str) -> Path:
    inbox = cfg.out / "inboxes" / name
    if inbox.exists():
        shutil.rmtree(inbox)
    inbox.mkdir(parents=True)
    return inbox


def post(inbox: Path, msg_id: str, text: str, suffix: str = ".msg") -> None:
    tmp = inbox / f"{msg_id}.tmp"
    tmp.write_text(text, encoding="utf-8")
    tmp.rename(inbox / f"{msg_id}{suffix}")


def hook_events(inbox: Path) -> list[dict]:
    path = inbox / "hook-log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def base_cmd(cfg: Config, settings_path: Path) -> list[str]:
    return [cfg.require_claude(), "-p", "--model", "haiku", "--setting-sources", "user",  #  <!-- model-slug-ok: the probe's own fixed CLI alias for the cheapest model, not a routing pin -->
            "--settings", str(settings_path), "--permission-mode", "dontAsk",
            "--allowedTools", "Bash(sleep *)", "--no-session-persistence"]


def communicate(proc: subprocess.Popen, timeout: float = 60) -> tuple[str, str]:
    """communicate() that kills the child instead of leaking it on timeout."""
    try:
        return proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.communicate()


def parse_json_result(out: str) -> dict:
    return json.loads(out) if out.strip().startswith("{") else {"raw": out[-2000:]}


def write_results(cfg: Config, filename: str, data: Any) -> Path:
    path = cfg.out / filename
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def guarded(name: str, fn: Callable[[Config], dict], cfg: Config) -> dict:
    """Run one case. An exception, or a missing boolean, is passed=false with the error recorded."""
    t0 = time.time()
    try:
        result = fn(cfg)
    except Exception as exc:  # noqa: BLE001 - a gate must record every failure as a fail
        return {"test": name, "passed": False, "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.time() - t0, 1)}
    if not isinstance(result.get("passed"), bool):
        result["passed"] = False
        result["error"] = "case returned no boolean 'passed'"
    return result


def probe_main(description: str, cases: dict[str, Callable[[Config], dict]],
               results_file: str) -> int:
    """Shared CLI entry for the standalone probe scripts. Exit 0 only if every case passed."""
    parser = argparse.ArgumentParser(description=description)
    add_args(parser)
    args = parser.parse_args()
    try:
        cfg = config_from_args(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    results = {name: guarded(name, fn, cfg) for name, fn in cases.items()}
    write_results(cfg, results_file, results)
    print(json.dumps({k: v["passed"] for k, v in results.items()}))
    return 0 if all(v["passed"] for v in results.values()) else 1
