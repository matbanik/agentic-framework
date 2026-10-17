"""M-1 gate runner for the messaging probe kit.

Writes OUT/gate-result.json (identity + per-case results), prints one summary line.
Exit codes: 0 every requested case passed; 1 at least one case failed; 2 usage or config error.

Case ids map to probe functions (research-mid-run-messaging.md Part A):
  T1  probe.run_t1       PostToolUse additionalContext, json output
  T2  probe.run_t2       Stop hook block reason
  T3  probe.run_t3       stream-json stdin second message
  T4  probe2.t4          blocking wait at a decision gate
  T5  probe2.t5          subagent agent_id in -p hooks
  T6b probe3b.run_t6b    additionalContext, stream-json output
  T6c probe3c.run_t6c    additionalContext, stream-json input and output
  T7  probe3.run_t7      updatedToolOutput only
  T8  probe3.run_t8      two additionalContext hooks, prompt on stdin
  T9  probe4.run_t9      durability: T9a (mid-run) plus T9b (resume) in one case; there is no
                         separate T9a or T9b id because T9b needs the session from T9a
Default M-1 set: T1, T2, T6c, T7, T9. (T6 alone is not a case: its first run deadlocked and
T6b is the valid rerun.)

gate-result.json carries "qualifying" and "cli_version". "qualifying" is true only for a live
run of the full default set in which every case passed. A self-test, a --cases subset or a
failed case writes false, and so does a run whose `claude --version` did not exit 0 with a
parsed MAJOR.MINOR.PATCH.

--check-receipt FILE --project DIR --python EXE [--claude EXE] validates a receipt for use
(report.md sections 4.6.6 and 10.2, M-1). It never runs a case. Exit 0 only when: qualifying is
true; mode is live; every default case is present and passed; cli_version equals the parsed
version of the installed CLI; identity.project equals DIR; identity.kit_revision equals this
kit's revision; and the launch profile matches: identity.launch_profile exists, its hook
interpreter and that interpreter's version equal those of EXE now, and the digest of the hook
keys of each settings source (user, project, project local, managed) equals the current file.
The hook keys are every key whose name contains "hook" (hooks, disableAllHooks,
allowManagedHooksOnly, allowedHttpHookUrls, httpHookAllowedEnvVars, and any later one) plus env,
enabledPlugins and disableCommandPluginSources. --python has no default here: the caller passes the
interpreter of its production hook. Else exit 1 with one line per failed check.
Register-CreditsRun.ps1 and admission call it.

--self-test never calls claude. It renders settings into OUT, checks the hook commands point
into KIT_DIR and are quoted, runs inbox_hook.py and wait_msg.py directly, and checks the kit
dir was not written to.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import kit
from kit import KIT_DIR, Config, ConfigError

DEFAULT_CASES = ["T1", "T2", "T6c", "T7", "T9"]


def case_table() -> dict:
    import probe
    import probe2
    import probe3
    import probe3b
    import probe3c
    import probe4
    return {
        "T1": probe.run_t1, "T2": probe.run_t2, "T3": probe.run_t3,
        "T4": probe2.t4, "T5": probe2.t5,
        "T6b": probe3b.run_t6b, "T6c": probe3c.run_t6c,
        "T7": probe3.run_t7, "T8": probe3.run_t8,
        "T9": probe4.run_t9,
    }


def _check(checks: list[dict], name: str, ok: bool, detail: str = "") -> None:
    checks.append({"name": name, "passed": bool(ok), "detail": detail})


def self_test(cfg: Config) -> tuple[dict, list[Path]]:
    checks: list[dict] = []
    before = {p.name for p in KIT_DIR.iterdir()}
    hashes_before = kit.kit_hashes()
    work = cfg.out / "selftest"
    work.mkdir(parents=True, exist_ok=True)
    sub = Config(out=work, project=cfg.project, python=cfg.python, claude=cfg.claude)

    # 1. Rendered settings: commands point into KIT_DIR and are quoted.
    settings = kit.render_settings(sub)
    data = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for ev in data["hooks"].values() for entry in ev
                for h in entry["hooks"]]
    expected = f'"{cfg.python}" "{(KIT_DIR / "inbox_hook.py").as_posix()}"'
    _check(checks, "settings: has PostToolUse and Stop hooks",
           set(data["hooks"]) == {"PostToolUse", "Stop"}, str(sorted(data["hooks"])))
    _check(checks, "settings: commands equal the quoted KIT_DIR form",
           bool(commands) and all(c == expected for c in commands), expected)
    parsed_ok = True
    for c in commands:
        try:
            parts = shlex.split(c, posix=True)
        except ValueError:
            parts = []
        if len(parts) != 2 or not Path(parts[1]).is_file() or not Path(parts[1]).resolve().is_relative_to(KIT_DIR):
            parsed_ok = False
    _check(checks, "settings: each command splits into interpreter + script inside KIT_DIR",
           parsed_ok and bool(commands))
    _check(checks, "settings: no backslashes in commands", all("\\" not in c for c in commands))

    # 2. inbox_hook.py PostToolUse delivery.
    inbox = work / "inbox"
    if inbox.exists():
        import shutil
        shutil.rmtree(inbox)
    inbox.mkdir()
    message = "ORCHESTRATOR-MESSAGE id=st1: self-test codeword SELFTEST-1."
    kit.post(inbox, "st1", message)
    env = dict(os.environ, PROBE_INBOX=str(inbox), PYTHONDONTWRITEBYTECODE="1")
    payload = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                          "session_id": "selftest"})
    hook = subprocess.run([cfg.python, str(KIT_DIR / "inbox_hook.py")], input=payload, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=30)
    ctx = None
    try:
        ctx = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        pass
    _check(checks, "inbox_hook: exits 0", hook.returncode == 0, hook.stderr[-300:])
    _check(checks, "inbox_hook: additionalContext carries the message", ctx == message,
           f"stdout={hook.stdout[:200]!r}")
    _check(checks, "inbox_hook: claims the file (moved to delivered/)",
           not (inbox / "st1.msg").exists() and (inbox / "delivered" / "st1.msg").is_file())

    # 3. inbox_hook.py Stop delivery.
    kit.post(inbox, "st2", "stop-message", suffix=".stopmsg")
    stop = subprocess.run([cfg.python, str(KIT_DIR / "inbox_hook.py")], env=env,
                          input=json.dumps({"hook_event_name": "Stop", "session_id": "selftest"}),
                          capture_output=True, text=True, encoding="utf-8", timeout=30)
    reason = None
    try:
        out = json.loads(stop.stdout)
        reason = out["reason"] if out["decision"] == "block" else None
    except (ValueError, KeyError, TypeError):
        pass
    _check(checks, "inbox_hook: Stop emits decision=block with the reason", reason == "stop-message",
           f"stdout={stop.stdout[:200]!r}")

    # 4. wait_msg.py times out on an empty inbox.
    empty = work / "inbox-empty"
    empty.mkdir(exist_ok=True)
    env2 = dict(env, PROBE_INBOX=str(empty))
    t0 = time.time()
    wait = subprocess.run([cfg.python, str(KIT_DIR / "wait_msg.py"), "2"], env=env2,
                          capture_output=True, text=True, encoding="utf-8", timeout=30)
    took = time.time() - t0
    _check(checks, "wait_msg: reports timeout on an empty inbox",
           wait.returncode == 0 and "timeout after 2s" in wait.stdout, wait.stdout.strip())
    _check(checks, "wait_msg: waited about 2 s", 1.5 <= took < 10, f"{took:.1f}s")

    # 5. The kit dir was not written to.
    after = {p.name for p in KIT_DIR.iterdir()}
    _check(checks, "kit dir: no files added or removed", before == after,
           str(sorted(before ^ after)))
    _check(checks, "kit dir: no .py file changed", hashes_before == kit.kit_hashes())

    return {"mode": "self-test", "checks": checks,
            "passed": all(c["passed"] for c in checks)}, [settings]


def check_profile(ident: dict, project: Path, python: str | None) -> list[str]:
    """Compare the receipt's launch profile with the expected one (report.md section 4.6.6)."""
    if not python:
        return ["expected hook interpreter not given (--python or MSG_PROBE_PYTHON)"]
    try:
        expected = kit.launch_profile(project, kit.resolve_python(python))
    except ConfigError as exc:
        return [f"expected hook interpreter: {exc}"]
    bad = [f"settings source {name} is unreadable now"
           for name, digest in expected["hook_settings"].items() if digest == "unreadable"]
    got = ident.get("launch_profile")
    if not isinstance(got, dict):
        return bad + ["launch_profile missing from the receipt identity"]
    for key in ("hook_python", "hook_python_version"):
        if got.get(key) != expected[key]:
            bad.append(f"launch_profile.{key} {got.get(key)!r} != expected {expected[key]!r}")
    got_settings = got.get("hook_settings") if isinstance(got.get("hook_settings"), dict) else {}
    for name, digest in expected["hook_settings"].items():
        if got_settings.get(name) != digest:
            bad.append(f"launch_profile.hook_settings.{name} differs from the current file")
    for name in sorted(set(got_settings) - set(expected["hook_settings"])):
        bad.append(f"launch_profile.hook_settings.{name} is not an expected source")
    if ident.get("python") != expected["hook_python"]:
        bad.append(f"identity.python {ident.get('python')!r} != expected {expected['hook_python']!r}")
    if ident.get("kit_dir") != KIT_DIR.as_posix():
        bad.append(f"kit_dir {ident.get('kit_dir')!r} != {KIT_DIR.as_posix()!r}")
    if not isinstance(ident.get("settings_sha256"), dict) or not ident["settings_sha256"]:
        bad.append("settings_sha256 missing or empty (no rendered probe settings recorded)")
    return bad


def check_receipt(path: Path, project: Path, claude: str | None,
                  python: str | None = None) -> list[str]:
    """Return the failed checks of one receipt; an empty list means the receipt may be used."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"receipt unreadable: {type(exc).__name__}: {exc}"]
    if not isinstance(data, dict):
        return ["receipt is not a JSON object"]
    bad: list[str] = []
    ident = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    cases = data.get("cases") if isinstance(data.get("cases"), dict) else {}
    if data.get("qualifying") is not True:
        bad.append("qualifying is not true")
    if data.get("mode") != "live":
        bad.append(f"mode is {data.get('mode')!r}, not 'live'")
    for cid in DEFAULT_CASES:
        case = cases.get(cid)
        if not isinstance(case, dict) or case.get("passed") is not True:
            bad.append(f"default case {cid} missing or not passed")
    installed = kit.cli_version(claude) if claude else None
    if installed is None:
        bad.append("installed CLI version unknown (claude --version failed or did not parse)")
    elif data.get("cli_version") != installed:
        bad.append(f"cli_version {data.get('cli_version')!r} != installed {installed!r}")
    if ident.get("project") != project.as_posix():
        bad.append(f"project {ident.get('project')!r} != {project.as_posix()!r}")
    if ident.get("kit_revision") != kit.kit_revision():
        bad.append("kit_revision differs from this kit")
    bad.extend(check_profile(ident, project, python))
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description="M-1 gate runner for the messaging probe kit.")
    kit.add_args(parser)
    parser.add_argument("--cases", default=",".join(DEFAULT_CASES),
                        help="comma list of case ids (default: %(default)s)")
    parser.add_argument("--self-test", action="store_true",
                        help="offline checks only; never calls claude")
    parser.add_argument("--check-receipt", metavar="FILE",
                        help="validate a gate-result.json for scheduler use; runs no case")
    args = parser.parse_args()

    if args.check_receipt:
        proj_raw = args.project or os.environ.get("MSG_PROBE_PROJECT") or os.getcwd()
        claude = args.claude or os.environ.get("MSG_PROBE_CLAUDE") or shutil.which("claude")
        # No default interpreter here: the caller names the one its production hook uses.
        python = args.python or os.environ.get("MSG_PROBE_PYTHON")
        bad = check_receipt(Path(args.check_receipt), Path(os.path.abspath(proj_raw)), claude,
                            python)
        for line in bad:
            print(f"RECEIPT FAIL: {line}")
        print(f"RECEIPT {'OK' if not bad else 'REJECTED'}: {Path(args.check_receipt).as_posix()}")
        return 0 if not bad else 1

    # The self-test writes only scratch files, so it needs no named output dir.
    if args.self_test and not (args.out or os.environ.get("MSG_PROBE_OUT")):
        args.out = tempfile.mkdtemp(prefix="probe-selftest-")

    try:
        cfg = kit.config_from_args(args, need_claude=not args.self_test)
        table = case_table()
        case_ids = [c.strip() for c in args.cases.split(",") if c.strip()]
        if not args.self_test:
            if not case_ids:
                raise ConfigError("no cases requested")
            unknown = [c for c in case_ids if c not in table]
            if unknown:
                raise ConfigError(f"unknown case id(s): {', '.join(unknown)}; known: {', '.join(table)}")
        gate_file = cfg.out / "gate-result.json"
    except ConfigError as exc:
        print(f"GATE ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        if args.self_test:
            body, settings = self_test(cfg)
            result = {"identity": kit.identity(cfg, settings, live=False)} | body
            result["cli_version"] = None
            result["qualifying"] = False
        else:
            ident = kit.identity(cfg, [], live=True)
            cases = {}
            for cid in case_ids:
                cases[cid] = kit.guarded(cid, table[cid], cfg)
                kit.write_results(cfg, "gate-result.json", {"identity": ident, "mode": "live",
                                                            "cases": cases, "passed": None})
            ident["settings_sha256"] = {p.name: kit.sha256_file(p)
                                        for p in sorted(cfg.out.glob("settings*.json"))}
            passed = all(c["passed"] for c in cases.values())
            result = {"identity": ident, "mode": "live", "cases": cases, "passed": passed,
                      "cli_version": ident.get("claude_version"),
                      "qualifying": bool(passed and sorted(case_ids) == sorted(DEFAULT_CASES)
                                         and ident.get("claude_version"))}
        gate_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except ConfigError as exc:
        print(f"GATE ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"GATE ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.self_test:
        bad = [c["name"] for c in result["checks"] if not c["passed"]]
        print(f"GATE self-test {'PASS' if result['passed'] else 'FAIL'}: "
              f"{len(result['checks']) - len(bad)}/{len(result['checks'])} checks"
              + (f"; failed: {'; '.join(bad)}" if bad else "") + f" -> {gate_file.as_posix()}")
    else:
        bad = [k for k, v in result["cases"].items() if not v["passed"]]
        print(f"GATE live {'PASS' if result['passed'] else 'FAIL'}: "
              f"{len(case_ids) - len(bad)}/{len(case_ids)} cases"
              + (f"; failed: {', '.join(bad)}" if bad else "")
              + f"; qualifying={str(result['qualifying']).lower()} -> {gate_file.as_posix()}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
