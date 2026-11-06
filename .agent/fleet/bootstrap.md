# Fleet member setup

You are the setup agent on the orchestrator machine, and you are adding a machine to the fleet. You run the
setup as a script from the orchestrator machine, over a local connection to the new machine. Follow this file
in order. A line that starts `STOP FOR HUMAN` is a stop: tell the human what the step needs, and wait until
they say it is done.

Your one input is the pairing line that the hub printed on the orchestrator machine:

```text
fleet-pairing url=<hub url> pin=<64 hex> fleet_py=<64 hex> bootstrap_md=<64 hex>
```

Rules for the whole setup:

- You must never read `member.json`. It holds the member's key, and only the fleet tool opens it.
- No secret, cookie, key or login goes into a message, a report, a chat or the hub. Each sign-in is issued
  on the orchestrator machine, on the human's browser approval, and stored on the member in a file only the
  member's user can read. This holds for the owner's own account on the owner's own machines only.
- Never print, read or parse a stored sign-in file, and never run a sign-in command yourself.
- The connection details and the sign-in script stay on the orchestrator machine. No host, address or
  credential goes into a tracked file.
- Put no GitHub credential and no signing key on the member. Only the orchestrator machine reaches GitHub.
- Open no port on the member. A member only makes outgoing connections.

## Windows

On the member, `$FleetHome` is `$HOME\.agent\fleet`, for the user the member runs as.

1. Carry `.agent/fleet/setup-member.ps1` to the member and run it there. It installs what is missing for
   the current user, sets Codex's config lines, chooses the Codex sandbox by a real write test, tests a
   full-access Codex write the way a Codex job runs, and writes `setup-report.json`. A sandbox that can't
   write is recorded, not a failure: Codex jobs run with full access. Run it a second time: the second report must have an empty `changed`. Install
   Python 3.11 or later and git too, if either is missing. Start your report with what was installed. Each
   write test needs that CLI's sign-in, so on a new machine setup reports `claude_no_write` or
   `codex_no_write` until step 6 is done. Run it again after step 6.

2. On the member, fetch both files and check each hash against the pairing line. `-k` is safe here,
   because the hash does the verifying and neither file holds a secret. If a hash differs, delete the file
   and stop.

   ```powershell
   New-Item -ItemType Directory -Force $FleetHome | Out-Null
   curl.exe -k -sS -o "$FleetHome\fleet.py" "<url>/bootstrap/fleet.py"
   curl.exe -k -sS -o "$FleetHome\bootstrap.md" "<url>/bootstrap/bootstrap.md"
   (Get-FileHash "$FleetHome\fleet.py" -Algorithm SHA256).Hash.ToLower()
   (Get-FileHash "$FleetHome\bootstrap.md" -Algorithm SHA256).Hash.ToLower()
   ```

3. **STOP FOR HUMAN: firewall-rule.** Only on the first machine, if the rule `Fleet hub 8770` is absent on
   the orchestrator machine. The human accepts the UAC prompt for the script that creates it, with the local
   subnet as the remote address:

   ```powershell
   New-NetFirewallRule -DisplayName 'Fleet hub 8770' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8770 -RemoteAddress <local subnet> -Profile Private
   ```

4. On the member, pair it with the pin from the pairing line and a name for the machine. This writes
   `member.json` without printing the key, and prints a code.

   ```powershell
   python "$FleetHome\fleet.py" pair --hub <url> --pin <pin> --name <name>
   ```

5. **STOP FOR HUMAN: run-approve.** On the orchestrator machine, in a real terminal, the human runs:

   ```powershell
   python .agent/fleet/fleet.py approve <name> <code>
   ```

6. **STOP FOR HUMAN: browser-approval.** For each agent CLI the member will run, the human runs the
   sign-in script on the orchestrator machine and approves the sign-in in the browser there. The script
   stores the sign-in on the member. Claude gets a long-lived token, and Codex gets a new login for each
   machine. A machine that takes only `ping` and `run` tasks needs neither yet, and the human may skip this.

7. Run `python "$FleetHome\fleet.py" check` on the member, and add its report to yours. If the member will
   work on a project, follow the Project part below.

8. **Handshake.** Start `python "$FleetHome\fleet.py" member` on the member and leave it running. The
   orchestrator machine sends `ping`. Then finish your report: what you installed, each version, and what
   still needs a human.

## Linux

## macOS

## Project part

The project's manifest is `<project>/.agent/fleet.json`, published to the hub from the orchestrator machine.

1. Run `python "$FleetHome\fleet.py" check --project <project>` on the member. It exits `6` and lists under
   `missing` each tool the project requires that the member lacks.
2. Install what it lists, for the current user where you can, then run it again until it exits `0`.
3. Restart the member, so that its report shows the new tools.

## Update

1. Stop the member.
2. Take the new pairing line from the hub, which prints it each time it starts. Fetch `fleet.py` again as
   in step 2 and check its hash. If it differs, delete the file and stop.
3. Start the member again.
