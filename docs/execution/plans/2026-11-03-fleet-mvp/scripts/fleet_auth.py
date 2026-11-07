#!/usr/bin/env python3
"""Issue Claude and Codex logins on the hub and store them on the member, with no sign-in there. Quick experiment.

Run through: uv run --no-project --with pywinrm python fleet_auth.py <command>

  dry-run  sends a random throwaway value, checks it arrived and its permissions, then deletes it
  issue    for a human in a real terminal: browser approvals, then stores both logins on the member
           (--claude-only or --codex-only redoes one; --token-file PATH takes an already issued
           Claude token from a file instead, skips the browser for it, and deletes the file once stored)
  test     runs one real call per CLI on the member, in a WinRM shell and in an S4U task like the member
  remove   deletes the stored logins from the member

No credential is printed, put in an argument, or put in a script body. Values travel over WinRM stdin with
message encryption forced on, and the WinRM login comes from the local WinRM helper that FLEET_WINRM_HELPER names.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import importlib.util
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import winrm

REMOTE_RUN = os.environ.get("FLEET_WINRM_HELPER", "")
CLAUDE_TOKEN = r"$HOME\.agent\fleet\credentials\claude-oauth-token"
CODEX_AUTH = r"$HOME\.codex\auth.json"
CODEX_CONFIG_LINE = 'cli_auth_credentials_store = "file"'
TEST_DIR = r"$HOME\.agent\fleet-auth-test"
TEST_TASK = "Fleet auth test"
TEST_WAIT_SECONDS = 300

STORE = r"""
$ErrorActionPreference = 'Stop'
$path = "__PATH__"
New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
[IO.File]::WriteAllBytes($path, [byte[]]@())
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls $path /inheritance:r /grant:r "${me}:F" | Out-Null
if ($LASTEXITCODE -ne 0) { Remove-Item $path; throw "icacls exit $LASTEXITCODE" }
[IO.File]::WriteAllBytes($path, [Convert]::FromBase64String([Console]::In.ReadToEnd().Trim()))
Write-Output ('SHA256=' + (Get-FileHash $path -Algorithm SHA256).Hash.ToLower())
Write-Output ('ACL=' + (((Get-Acl $path).Access | ForEach-Object { "$($_.IdentityReference):$($_.FileSystemRights)" }) -join ','))
"""

# Runs on the member. Sets the token in this process only, so nothing else on the machine inherits it.
INNER_TEST = r"""
$ErrorActionPreference = 'Continue'
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
Set-Location (Split-Path $PSCommandPath)
function Short($lines) { (($lines | ForEach-Object { "$_" }) -join ' ') -replace '\s+', ' ' | ForEach-Object { $_.Substring(0, [Math]::Min(300, $_.Length)) } }
"identity=$([Security.Principal.WindowsIdentity]::GetCurrent().Name) home=$HOME"
"inherited: OAUTH=$([bool]$env:CLAUDE_CODE_OAUTH_TOKEN) ANTHROPIC_API_KEY=$([bool]$env:ANTHROPIC_API_KEY) OPENAI_API_KEY=$([bool]$env:OPENAI_API_KEY) CODEX_API_KEY=$([bool]$env:CODEX_API_KEY)"
$tokenPath = "__CLAUDE_TOKEN__"
if (Test-Path $tokenPath) {
    $env:CLAUDE_CODE_OAUTH_TOKEN = (Get-Content $tokenPath -Raw).Trim()
    Remove-Item Env:\ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
    try {
        $s = (& claude auth status 2>$null | Out-String | ConvertFrom-Json)
        "claude auth: loggedIn=$($s.loggedIn) authMethod=$($s.authMethod) apiProvider=$($s.apiProvider) subscriptionType=$($s.subscriptionType)"
    } catch { "claude auth status unreadable" }
    $out = $null | & claude -p 'Reply with exactly: CLAUDE-OK' --model haiku --max-turns 1 --output-format text 2>&1
    "claude call: exit=$LASTEXITCODE output=$(Short $out)"
    Remove-Item Env:\CLAUDE_CODE_OAUTH_TOKEN
} else { 'claude: no stored token' }
if (Test-Path "__CODEX_AUTH__") {
    "codex auth: $(Short (& codex login status 2>&1))"
    $out = $null | & codex exec --skip-git-repo-check --sandbox read-only 'Reply with exactly: CODEX-OK' 2>&1
    "codex call: exit=$LASTEXITCODE output=$(Short ($out | Select-Object -Last 3))"
} else { 'codex: no stored login' }
"""

TASK_RUN = r"""
$ErrorActionPreference = 'Stop'
$dir = "__TEST_DIR__"
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$dir\inner.ps1`" > `"$dir\s4u.txt`" 2>&1 & echo done> `"$dir\s4u.done`""
$principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType S4U
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds __WAIT__) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName '__TASK__' -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName '__TASK__'
$deadline = (Get-Date).AddSeconds(__WAIT__)
while (-not (Test-Path "$dir\s4u.done") -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 3 }
if (-not (Test-Path "$dir\s4u.done")) { Write-Output 'S4U task did not finish in time' }
Unregister-ScheduledTask -TaskName '__TASK__' -Confirm:$false
Get-Content "$dir\s4u.txt" -ErrorAction SilentlyContinue
"""

REDACT = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "[token]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-.]{16,}"), "[token]"),
    (re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+"), "[address]"),
]


def redacted(text: str) -> str:
    for pattern, mark in REDACT:
        text = pattern.sub(mark, text)
    return text


def connect() -> winrm.Session:
    if not REMOTE_RUN:
        raise RuntimeError("set FLEET_WINRM_HELPER to the WinRM helper's path")
    spec = importlib.util.spec_from_file_location("winrm_helper", REMOTE_RUN)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return winrm.Session(
        f"http://{runner.DEFAULT_HOST}:5985/wsman",
        auth=(runner.DEFAULT_USER, runner.DEFAULT_PASS),
        transport="ntlm",
        message_encryption="always",
    )


def run_with_stdin(session: winrm.Session, script: str, stdin: bytes = b"") -> tuple[int, str, str]:
    encoded = base64.b64encode(script.encode("utf_16_le")).decode("ascii")
    protocol = session.protocol
    shell = protocol.open_shell()
    try:
        command = protocol.run_command(shell, "powershell", ["-NoProfile", "-NonInteractive", "-EncodedCommand", encoded])
        protocol.send_command_input(shell, command, stdin + b"\r\n", end=True)
        out, err, code = protocol.get_command_output(shell, command)
        protocol.cleanup_command(shell, command)
    finally:
        protocol.close_shell(shell)
    return code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def run_ps(session: winrm.Session, script: str) -> str:
    code, out, err = run_with_stdin(session, script)
    if code != 0:
        raise RuntimeError(f"remote script exited {code}: {redacted(err)[:400]}")
    return out


def store(session: winrm.Session, remote_path: str, data: bytes) -> str:
    """Writes data to a user-only file on the member, checks its hash, and returns the file's permissions."""
    script = STORE.replace("__PATH__", remote_path)
    code, out, err = run_with_stdin(session, script, base64.b64encode(data))
    if code != 0:
        raise RuntimeError(f"store exited {code}: {redacted(err)[:400]}")
    fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if fields.get("SHA256") != hashlib.sha256(data).hexdigest():
        raise RuntimeError("the stored file's hash does not match what was sent")
    return fields.get("ACL", "unknown")


def dry_run() -> int:
    session = connect()
    path = r"$HOME\.agent\fleet\credentials\dry-run-canary"
    acl = store(session, path, secrets.token_bytes(64))
    print("encryption forced, stdin transfer OK, hash matches")
    print("permissions:", acl)
    print(run_ps(session, f'Remove-Item "{path}"; "canary removed: $(-not (Test-Path "{path}"))"').strip())
    return 0


def clean_token(text: str) -> str:
    token = re.sub(r"\s+", "", text)
    if len(token) < 20 or not token.isascii() or not token.isprintable():
        raise RuntimeError(f"got {len(token)} characters, which doesn't look like a whole token; nothing was stored")
    return token


def read_token_file(path: Path) -> str:
    raw = path.read_bytes()
    return raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")


def issue_claude(session: winrm.Session, token_file: Path | None = None) -> None:
    if token_file:
        print("\n=== Claude: using the token in the file you named.")
        token = clean_token(read_token_file(token_file))
    else:
        print("\n=== Claude: approve in the browser. It prints a token here.")
        done = subprocess.run([shutil.which("claude") or "claude", "setup-token"])
        if done.returncode != 0:
            raise RuntimeError(f"claude setup-token exited {done.returncode}")
        token = clean_token(getpass.getpass("\nPaste the whole token (hidden), then press Enter: "))
    print("Claude login stored. Permissions:", store(session, CLAUDE_TOKEN, token.encode("ascii")))
    if token_file:
        token_file.unlink()
        print("Token file deleted.")


def issue_codex(session: winrm.Session) -> None:
    print("\n=== Codex: approve in the browser. This makes a new login just for the member.")
    with tempfile.TemporaryDirectory(prefix="fleet-codex-") as home:
        Path(home, "config.toml").write_text(CODEX_CONFIG_LINE + "\n", encoding="utf-8")
        env = {**os.environ, "CODEX_HOME": home}
        codex = shutil.which("codex") or "codex"
        if subprocess.run([codex, "login"], env=env).returncode != 0:
            raise RuntimeError("codex login failed")
        auth = Path(home, "auth.json")
        if not auth.exists():
            raise RuntimeError("codex login wrote no auth.json")
        run_ps(session, rf"""
$ErrorActionPreference = 'Stop'
$config = "$HOME\.codex\config.toml"
New-Item -ItemType Directory -Force (Split-Path $config) | Out-Null
if (-not (Test-Path $config) -or -not (Select-String -Path $config -SimpleMatch 'cli_auth_credentials_store' -Quiet)) {{
    Add-Content -Path $config -Value '{CODEX_CONFIG_LINE}'
}}
""")
        print("Codex login stored. Permissions:", store(session, CODEX_AUTH, auth.read_bytes()))
    print("The temporary copy on the hub is deleted.")


def issue(args: list[str]) -> int:
    # A file route prints no credential, so only the routes that show one on screen need a human's terminal.
    from_file = "--claude-only" in args and "--token-file" in args
    if not from_file and not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("issue needs a human in a real terminal, so no credential passes through an agent's shell.")
        return 3
    session = connect()
    if "--codex-only" not in args:
        token_file = Path(args[args.index("--token-file") + 1]) if "--token-file" in args else None
        issue_claude(session, token_file)
    if "--claude-only" not in args:
        issue_codex(session)
    print("\nDone. Tell the agent, and clear this terminal's scrollback: it shows the Claude token.")
    return 0


def test() -> int:
    session = connect()
    inner = INNER_TEST.replace("__CLAUDE_TOKEN__", CLAUDE_TOKEN).replace("__CODEX_AUTH__", CODEX_AUTH)
    run_ps(session, f'New-Item -ItemType Directory -Force "{TEST_DIR}" | Out-Null; Remove-Item "{TEST_DIR}\\s4u.*" -ErrorAction SilentlyContinue')
    code, _, err = run_with_stdin(
        session,
        f"""$ErrorActionPreference='Stop'; [IO.File]::WriteAllBytes("{TEST_DIR}\\inner.ps1", [Convert]::FromBase64String([Console]::In.ReadToEnd().Trim()))""",
        base64.b64encode(("\ufeff" + inner).encode("utf-8")),
    )
    if code != 0:
        raise RuntimeError(f"copying the test failed: {redacted(err)[:400]}")
    print("=== in a WinRM shell")
    print(redacted(run_ps(session, f'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{TEST_DIR}\\inner.ps1"')).strip())
    print("\n=== in an S4U scheduled task, the way the member runs")
    started = time.time()
    script = TASK_RUN.replace("__TEST_DIR__", TEST_DIR).replace("__TASK__", TEST_TASK).replace("__WAIT__", str(TEST_WAIT_SECONDS))
    print(redacted(run_ps(session, script)).strip())
    print(f"(took {time.time() - started:.0f} s)")
    run_ps(session, f'Remove-Item "{TEST_DIR}" -Recurse -Force')
    return 0


def remove() -> int:
    session = connect()
    print(run_ps(session, f"""
foreach ($p in "{CLAUDE_TOKEN}", "{CODEX_AUTH}") {{ Remove-Item $p -ErrorAction SilentlyContinue; "$(Split-Path $p -Leaf) present: $(Test-Path $p)" }}
""").strip())
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if command == "dry-run":
            return dry_run()
        if command == "issue":
            return issue(sys.argv[2:])
        if command == "test":
            return test()
        if command == "remove":
            return remove()
    except Exception as exc:  # A traceback could carry values, so only the type and a scrubbed message print.
        print(f"failed: {type(exc).__name__}: {redacted(str(exc))[:500]}")
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
