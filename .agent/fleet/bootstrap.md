# Fleet member setup

You are the setup agent on a machine that is joining the fleet. Follow this file in order. A line that
starts `STOP FOR HUMAN` is a stop: tell the human what the step needs, and wait until they say it is done.

Your one input is the pairing line that the hub printed on the orchestrator machine:

```text
fleet-pairing url=<hub url> pin=<64 hex> fleet_py=<64 hex> bootstrap_md=<64 hex>
```

Rules for the whole setup:

- You must never read `member.json`. It holds this machine's key, and only the fleet tool opens it.
- No secret, cookie, key or login goes into a message, a report or a chat. A human creates each login at
  this machine's console. Nothing is copied from another machine.
- Put no GitHub credential and no signing key on this machine. Only the orchestrator machine reaches
  GitHub.
- Open no port on this machine. A member only makes outgoing connections.
- Install a tool for the current user where the tool allows it, and note each install for your report.

## Windows

Run these in PowerShell, after setting `$FleetHome = "$HOME\.agent\fleet"`.

1. **STOP FOR HUMAN: install-agent-cli.** A human installs one agent CLI on this machine and signs in. A
   machine that takes only `ping` and `run` tasks does not need one yet, and the human may skip this.

2. Fetch both files, and check each hash against the pairing line. `-k` is safe here, because the hash
   does the verifying and neither file holds a secret. If a hash differs, delete the file and stop.

   ```powershell
   New-Item -ItemType Directory -Force $FleetHome | Out-Null
   curl.exe -k -sS -o "$FleetHome\fleet.py" "<url>/bootstrap/fleet.py"
   curl.exe -k -sS -o "$FleetHome\bootstrap.md" "<url>/bootstrap/bootstrap.md"
   (Get-FileHash "$FleetHome\fleet.py" -Algorithm SHA256).Hash.ToLower()
   (Get-FileHash "$FleetHome\bootstrap.md" -Algorithm SHA256).Hash.ToLower()
   ```

3. Install Python 3.11 or later and git if either is missing, for the current user where you can. Start
   the report you will finish in step 9 with what you did.

4. **STOP FOR HUMAN: confirm-fingerprint.** The human compares the `pin` in the pairing line with the pin
   on the orchestrator machine's screen.

5. **STOP FOR HUMAN: firewall-rule.** Only if the rule `Fleet hub 8770` is absent on the orchestrator
   machine. A human creates it there, in an elevated prompt, with the local subnet as the remote address:

   ```powershell
   New-NetFirewallRule -DisplayName 'Fleet hub 8770' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8770 -RemoteAddress <local subnet> -Profile Private
   ```

6. **STOP FOR HUMAN: run-pair.** The human runs this in their own terminal, with a name for this machine.
   It writes `member.json` without printing the key, and prints an approval code.

   ```powershell
   python "$FleetHome\fleet.py" pair --hub <url> --pin <pin> --name <name>
   ```

7. **STOP FOR HUMAN: run-approve.** On the orchestrator machine, in a real terminal, the human runs:

   ```powershell
   python .agent/fleet/fleet.py approve <name> <code>
   ```

8. Run `python "$FleetHome\fleet.py" check`, and add its report to yours. If this machine will work on a
   project, follow the Project part below.

9. **Handshake.** A human starts `python "$FleetHome\fleet.py" member` and leaves it running. The
   orchestrator machine sends `ping`. Then finish your report: what you installed, each version, and what
   still needs a human.

## Linux

## macOS

## Project part

The project's manifest is `<project>/.agent/fleet.json`, published to the hub from the orchestrator machine.

1. Run `python "$FleetHome\fleet.py" check --project <project>`. It exits `6` and lists under `missing`
   each tool the project requires that this machine lacks.
2. Install what it lists, for the current user where you can, then run it again until it exits `0`.
3. A human restarts the member, so that its report shows the new tools.

## Update

1. A human stops the member.
2. Take the new pairing line from the hub, which prints it each time it starts. Fetch `fleet.py` again as
   in step 2 and check its hash. If it differs, delete the file and stop.
3. A human starts the member again.
