---
project: "2026-11-15-usb-kit-usability"
date: "2026-11-15"
source: "docs/execution/plans/2026-11-15-usb-kit-usability/implementation-plan.md (user request of 2026-11-15; no build-plan section)"
meus: []
status: "complete"
template_version: "2.4"
---

# Implementation Plan: USB Kit Usability

> **Project**: `2026-11-15-usb-kit-usability`
> **Build Plan Section(s)**: none. This package has no `docs/BUILD_PLAN.md`; the source is the human's request of 2026-11-15.
> **Status**: `draft`

---

## Goal

The USB kit (`.agent/fleet/usb/`) gives the hub machine an SSH admin connection to a new machine. The
human tested it on Windows and Linux hardware and found four problems that cost manual work on every
machine:

1. **No record comes back.** Both setup scripts write the member record last. Any stop before that
   point (`die` in `setup-unix.sh`, a `throw` under `$ErrorActionPreference='Stop'` in
   `setup-windows.ps1`) leaves no record on the drive. Two known causes: on Windows, `Install-Cli`
   throws when `%USERPROFILE%\.local\bin` is not on `PATH` after the Claude installer runs; and a
   Windows computer name with an underscore (`Lab_Mini07`) gives a record name that `read_record`
   refuses, so `import` skips it.
2. **The record goes only to the drive.** The human wants members to send their record to the hub over
   the network, where it can be reviewed, with the drive as the second copy.
3. **sudo on new Ubuntu.** On Ubuntu 25.10 and later, `/usr/bin/sudo` is an alternatives link to
   sudo-rs, and the original sudo is `/usr/bin/sudo.ws`. The human had to repair the link by hand on a
   fresh install before `sudo bash setup-unix.sh` ran. The launchers and the README assume a working
   `sudo`.
4. **Prerequisites are missing.** The scripts set up SSH (and, in the human's uncommitted edits, Claude
   Code and Codex), but not Git, Python, PowerShell or uv, so the hub's agent installs them by hand.

The human also asked for **RustDesk** on every member with a desktop, configured for the hub's own
RustDesk ID server, and for the framework docs to point the human to the published guide
<https://matbanik.info/hobbies/systems/posts/rustdesk-server-on-windows-without-docker/> to build that
server on the hub.

The human ruled out a security-hardening scope: "i don't have issue with full admin access on these
computers". This plan **supersedes** the unexecuted plan `docs/execution/plans/2026-11-07-usb-kit-hardening/`
(approved at round 10, never started, never committed). That plan's folder and review file stay
untracked and unchanged; no row of this plan reads or edits them, and the commit manifest excludes them.

**Standing directive (human, 2026-11-15):** every fleet and kit fix lands in this repository. The live
fixes made by hand on an earlier member (the PATH fix and the name fix) are rows here.

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning_and_execution
  eligible_tools: []
  decision: not_applicable
  eligibility_basis: "graphify-out/graph.json is absent in this repository. Headroom is installed, but the payloads here are source code and exact evidence, which are bypass classes in core/.agent/docs/context-tool-decision-gate.md."
  human_message_reference: null
```

## Handoff Set

| Scope | Canonical handoff |
|---|---|
| project (`meus: []`) | `.agent/context/handoffs/2026-11-15-usb-kit-usability-handoff.md` |

The rolling reviews are `.agent/context/handoffs/2026-11-15-usb-kit-usability-plan-critical-review.md`
and `.agent/context/handoffs/2026-11-15-usb-kit-usability-implementation-critical-review.md`.

## Work Packages and Context Lifecycle

| ID | Work | depends_on | context_strategy | durable_outputs |
|---|---|---|---|---|
| WP-K0 | Backup of the four uncommitted kit files, baseline, plan-local checkers | — | `shared` | `C:/Temp/agentic-framework/receipts/uk2-backup/`; `uk2-*-baseline.*`; `check_kit.py`, `run_pester.ps1` in the plan folder |
| WP-K1 | Record v2 that is always written; the name rule; non-fatal steps; testable scripts | WP-K0 | `compact_continue` | Both setup scripts, `fleet_usb.py`, `scripts/tests/test_fleet_usb.py`, `scripts/tests/SetupWindowsUsb.Tests.ps1` |
| WP-K2 | Unix elevation without a working `sudo`; launchers run `bash` | WP-K1 | `shared` | `setup-unix.sh`, both Unix launchers, tests |
| WP-K3 | Prerequisites: Git, Python, PowerShell, uv, Claude Code, Codex | WP-K2 | `compact_continue` | Both setup scripts, tests |
| WP-K4 | Network write-back: `hub.txt`, `fleet_usb.py receive`, the member send | WP-K3 | `shared` | `fleet_usb.py`, both setup scripts, tests |
| WP-K5 | RustDesk on members with a desktop | WP-K4 | `compact_continue` | `fleet_usb.py`, both setup scripts, tests |
| WP-K6 | Docs and known issues | WP-K5 | `shared` | `usb/README.md`, `core/MANIFEST.md`, `.agent/fleet/bootstrap.md`, known-issues pair |
| WP-K7 | Gates, then live members | WP-K6 | `shared` | Receipts; the handoff |

`isolated` is not used. **Lane ownership is omitted:** this is a main-tree plan, started by a human
session, and the repository has no `.agent/credits/worktree.json` (no executor worktree route exists
here). Rows run in order on `main` in the main tree.

---

## User Review Required

> [!IMPORTANT]
> **Run parameters (v2.3):** `manual`. Run parameters are disabled in this repository
> (`policy_missing`), so the earlier rules apply: execution starts only on the human's typed
> "proceed" after `approved`; every commit needs the human's typed direction; nothing is pushed.
>
> **Review limits (v2.4):** `repo` (`core/.agent/review-limits.json`: plan 3 rounds, execution 6).
>
> **Decisions:** D-1 to D-7 in the Decision Log are decided by the planner (all two-way doors). No
> decision waits for the human. The human's review points:
>
> - **D-1:** the four uncommitted kit files (the human's Claude Code and Codex install edits) become
>   this plan's baseline. Row 1 copies them to a backup first; the final commit includes them.
> - **D-6:** the network send uses plain HTTP on the LAN, gated by a random token on the drive. This
>   follows the human's ruling against a security scope.
> - **D-7:** RustDesk 1.5.3 takes the permanent password only as an argument, so on the member the
>   password is in the argument list of that one RustDesk child while it runs. It never appears on
>   the hub's command line, in the ssh remote command string, in a receipt, on the drive, in the
>   inbox, in a record or in a log.
> - **Live rows** need the human at the member's screen: the new mini PC (rows 12 and 13), a member of
>   the other OS family if the human names one (row 14), and a Mac (row 15, `[B]` without one).
> - **Hub firewall:** row 11a is a human step that opens TCP 8771 inbound on the hub for the receiver.

---

## Proposed Changes

### Named definitions

- **Account.** The user account that the hub's agent will use on the member. Unix: the `--for-user`
  argument if given, else `SUDO_USER`, else the name of `PKEXEC_UID` (`getent passwd` on Linux,
  `dscl` on macOS), else the invoking user when the script was started without root. It must match
  `^[A-Za-z_][A-Za-z0-9_.-]*$` and must not be `root`. Windows: the `-ForUser` value that the first,
  unelevated process passes to its elevated child (WP-K1, Windows elevation), else `$env:USERNAME`.
- **Name rule.** The record name: the host name (Windows `$env:COMPUTERNAME`; Linux `hostname -s`;
  macOS `scutil --get LocalHostName`), lowercased; each character outside `[a-z0-9-]` becomes `-`;
  runs of `-` collapse to one; leading and trailing `-` are removed; the result is cut to 63
  characters (then trailing `-` removed again). An empty result becomes `member`. Both scripts
  implement the same rule; the result always matches `fleet_usb.py`'s `NAME`.
  Examples: `Lab_Mini07` → `lab-mini07`; `--Lab PC__2--` → `lab-pc-2`; `___` → `member`.
- **Step.** One unit of setup work with a fixed id from the Step list. Each step ends with one
  **step status**: `ok`, `failed` or `skipped` (this is the only definition of the three values), with
  a detail string (at most 300 characters; longer text is cut). A failed step never stops the script,
  except where the Step list says a later step `needs` it; such a later step ends `skipped` with
  detail `needs <step>`.
- **Step list.** In order: `elevate`, `account`, `packages`, `ssh_server`, `firewall`, `hub_key`,
  `admin_rights`, `linger` (Linux only), `homebrew` (macOS only), `pwsh`, `uv`, `claude`, `codex`,
  `tool_links` (Linux and macOS), `rustdesk`, `host_key`. `hub_key`, `admin_rights` and `host_key`
  need `ssh_server`; `pwsh`, `uv`, `claude`, `codex` and `tool_links` need `account`; on macOS
  `homebrew` needs `admin_rights`, and `pwsh` needs `homebrew`. `packages` on Windows is the winget
  step (Git and Python). A step that does not apply to the system ends `skipped` with detail
  `not on <os>`. Sending the record is not a step (see Delivery).
- **Run id.** `^[a-z0-9]{8,32}$`, made once per run by the first process (16 random lowercase
  letters and digits) and passed to an elevated child with `--run-id` (Unix) or `-RunId` (Windows).
  Every other mention of a run id in this plan means this definition.
- **Record v2.** A JSON object with exactly these keys:
  `v` (2), `run_id` (Run id), `final` (boolean: false for a checkpoint, true once the run ended),
  `name` (Name rule), `os` (`windows|macos|linux`), `user` (`fleet_usb.py`'s `USER`), `ok` (true
  only when `final` is true and no step has status `failed`), `steps` (a list of
  `{step, status, detail}` objects, one per Step-list id that ran, in order; `status` is a step
  status), `tools` (an object of tool id → version string, at most 200 characters each, for the tools
  found at the end: `git`, `python`, `pwsh`, `uv`, `claude`, `codex`, `rustdesk`), `gui` (boolean),
  `session_type` (`x11|wayland|tty|windows|macos|unknown`), `rustdesk_id` (`null` or
  `^[0-9]{6,12}$`), `port` (null or 1–65535), `host_key` (null or `HOST_KEY`), `addresses` (a list,
  possibly empty, of IPv4 strings), and `delivery` (Delivery). `port`, `host_key` and a non-empty
  `addresses` are required when the `host_key` step is `ok`. Unknown keys are refused. `ok` never
  depends on `delivery`.
- **Delivery.** `null` in the record that the member sends to the hub. In the drive copy, an object
  `{status, detail}` with `status` `pending` (written before the send starts), `sent` (detail: the URL
  that answered 200) or `failed` (detail: each URL's result, cut to 300 characters). `read_record`
  accepts all four forms; `import` prints the delivery status and never fails a record for it.
- **Record write.** The record goes to `<drive>/members/<name>.json` as UTF-8 without a BOM, through a
  temp file and a rename in the same folder, then `sync` on Unix. **Checkpoints:** the script writes a
  record with `final` false as soon as the name is known (before the `elevate` step), and again after
  each step ends, so the drive holds the steps done so far at every moment. **Finalize:** the last
  write sets `final` true; it runs from the exit handler on every exit path that a script can catch:
  normal end, a failed step, an error the script did not expect, Ctrl+C, and a closed terminal window
  (bash: `trap finalize EXIT`, plus `trap 'mark_interrupted; exit 130' INT TERM HUP`, so a signal
  ends the running step `failed` with detail `interrupted` and then runs the EXIT trap; PowerShell:
  `try/finally` around `Invoke-Setup`, which runs on Ctrl+C, and a `[Console]::CancelKeyPress`
  handler that ends the running step `failed` with detail `interrupted`). **Boundary:** a forced kill (`kill -9`, End task
  in Task Manager, power loss) runs no handler; the drive then holds the last checkpoint, with
  `final` false, and `import` reports it as `incomplete after <last step>`. The script exits 0 when
  `ok` is true, else 1.
- **Account environment.** The environment for every command that runs as the Account, for installs
  and for version discovery alike: `env -i HOME=<home> USER=<account> LOGNAME=<account>
  PATH=<home>/.local/bin:<home>/.cargo/bin:<brew>/bin:<brew>/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`,
  where `<brew>` is `/opt/homebrew` on Apple silicon and `/usr/local` on Intel macOS (Linux: the two
  `<brew>` entries are left out). Linux runs it as `runuser -u <account> -- env -i …`; macOS as
  `sudo -u <account> -H env -i …`. Windows: after each install, `$env:Path` is rebuilt from the
  Machine and User registry values (Windows PATH fix), which is also what an SSH session of the
  Account reads at logon.
- **Tool links.** The SSH command environment of a Unix member does not read the Account's shell
  profile: on Linux, sshd's `PATH` holds `/usr/local/bin` (its compiled default, or `/etc/environment`
  through `pam_env` on Ubuntu, which also adds `/snap/bin`) but never `~/.local/bin`; on macOS it is
  `/usr/bin:/bin:/usr/sbin:/sbin`. So the `tool_links` step makes each tool reachable there: Linux
  links `/usr/local/bin/<tool>` to the Account's `uv`, `uvx`, `claude` and `codex` when no such file
  exists there (an existing link to the same target is left as it is); macOS adds one marked block
  (`# fleet-usb PATH` … `# end fleet-usb PATH`) to the Account's `~/.zshenv` that puts the Account
  environment's `PATH` entries first, written once and replaced in place on a rerun; when the
  Account's login shell (`dscl . -read /Users/<account> UserShell`) is not zsh, the step ends
  `failed` with detail `login shell is <shell>, not zsh`. The live check
  runs `ssh <member> '<tool> --version'` with no login shell, so it proves this environment.
- **Test root.** Every absolute system path that the Unix script reads or writes (`/etc`, `/usr`,
  `/opt`, `/Applications`, `/Library`, the Account's home) is built as `${FLEET_ROOT}<path>`, where
  `FLEET_ROOT` is empty on a member; tests set it to a temp folder. The Windows script takes the same
  seam as a `-Root` parameter of `Invoke-Setup`.
- **Hub file.** `<drive>/hub.txt`, written by `prepare`: lines `url=<http URL>` (one or more) and one
  line `token=<token>`. Members read it line by line and never source or evaluate it. The token
  matches `^[A-Za-z0-9_-]{32,64}$`.
- **RustDesk file.** `<drive>/rustdesk.txt`, written by `prepare` only when a RustDesk server is
  configured: `version=<x.y.z>`, `host=<host>`, `key=<public key>`, and one `file=<name> <sha256>`
  line per downloaded asset in `<drive>/rustdesk/`. Members read it line by line.
- **Send.** After the finalize write (which leaves the drive copy with `delivery` `pending`), the
  member POSTs the record with `delivery` null to each `url` of the Hub file in order with `curl`
  (`curl.exe` on Windows): `POST <url>/v1/usb-record`, header `X-Fleet-Token: <token>`, body the
  record, a 5 s connect timeout and a 20 s total timeout. It stops at the first HTTP 200. Then it
  rewrites the drive copy with `delivery` `sent` or `failed`. With no `hub.txt`, no `curl` or no
  valid token line, `delivery` is `failed` with that reason. A run that is stopped during the send
  leaves `delivery` `pending`; the record is still complete. The exit code comes from `ok` only.
- **GUI rule.** Windows: `gui` true. macOS: true. Linux: true when `systemctl get-default` prints
  `graphical.target`, or when `display-manager.service` is active. `session_type` comes from
  `loginctl show-session` of the Account's newest session (`Type=`) on Linux, else `unknown`.

### WP-K0: Backup, baseline and plan-local checkers

1. Write `check_kit.py` in the plan folder, with these modes:
   - `--backup`: copy the four uncommitted kit files (`.agent/fleet/install-usb/README.md`,
     `.agent/fleet/usb/README.md`, `.agent/fleet/usb/setup-unix.sh`,
     `.agent/fleet/usb/setup-windows.ps1`) to `$RECEIPTS_DIR/uk2-backup/`, with their
     `git diff HEAD --` output in `uk2-backup/baseline.diff` and a `sha256.txt` of the four copies
     (D-1). It refuses to replace a backup whose bytes differ from the working tree, so a rerun after
     row 2 cannot overwrite the human's edits with this plan's. Its only git command is `git diff`;
     nothing changes the index or the working tree.
   - `--baseline`: save the failure lines of `python scripts/refcheck.py` and
     `python scripts/sanitize.py --verify` (line numbers removed) and HEAD to
     `$RECEIPTS_DIR/uk2-gates-baseline.json`.
   - `--pytest <receipt> --exit <code>`: the pytest gate. `<code>` is pytest's own exit code, which
     the row captures right after pytest. The gate passes when the code is 0 with no `FAILED` line,
     or 1 with every `FAILED` test id in `KNOWN_FAILURES`; any other code (2 interrupted, 3 internal
     error, 4 usage, 5 no tests) fails. It also needs the receipt to end with pytest's summary line,
     that line to count no `error`, and the receipt to have no `ERROR ` line. `KNOWN_FAILURES` is one constant in `check_kit.py` that holds only
     the test id of `test_ac38_the_skills_hold_the_member_route_and_the_billing_rule` in `scripts/tests/test_fleet_agent.py`
     (known issue `FLEET-AC38-BILLING-LINE-PIN`: the test compares the fixed lines 340–343 of
     `core/.agent/skills/claude-credits/SKILL.md` with its `BILLING_RULE`; commit `fb2d26d` added lines
     above it, so the unchanged rule now starts at line 362) and, added by EA-2 on 2026-11-15 with the
     human's ruling, `test_no_retained_python_file_needs_a_removed_tool` and `test_retained_python_tests_collect`
     in `scripts/tests/test_instantiate_credits_nonwin.py` (known issue
     `FLEET-INSTALL-RETAINED-CREDITS-TESTS`: the Linux install keeps retained `test_credits_*`
     and `test_lanes_recover_standing.py` files that import tests the install removes, since commit
     `fb00d40`; both tests fail the same way on a clean `HEAD`). This plan does not edit those tests, the
     skill or the instantiate script (G36). The gate prints each known failure that it excused, and it
     fails when a known failure passes or does not run, so the excuse cannot outlive the issue unseen.
   - `--red <receipt>... --acs <n,...>`: pass only when every listed AC has at least one failing test
     in the receipts, and the failure is in the test body, not in its setup. pytest (`-rA`): a
     `FAILED …::test_acNN_…` line counts; the check refuses the whole receipt set when any receipt
     has an `ERROR ` line, `ERROR collecting` or a summary that counts an `error` (a fixture, setup,
     teardown or collection error), and names the receipt. A test body that fails because the row's
     function does not exist yet (`AttributeError` on the module) is a valid red; so that this stays a
     body failure, the test files import `fleet_usb` as a module and reach every new name through it,
     never with `from fleet_usb import <new name>`. Pester: a `[-] AC-N:` line counts only when the
     same receipt's `Pester gate` summary line shows `FailedBlocks=0` and `FailedContainers=0`; a
     `BeforeAll`, `AfterAll` or discovery failure marks every test under it failed, so such a receipt
     is refused. Passing lines of the same AC are allowed, because an AC's refusal cases can pass on
     the old code. A receipt set with no counted failure for a listed AC fails the check and names
     that AC.
   - `--gates`: no new refcheck or sanitize failure line against the baseline; every AC of this plan
     except the live ACs (AC-23 to AC-26) and AC-22 (which `--gates` and `--selftest` prove
     themselves) has a `test_acNN_` function in `scripts/tests/test_fleet_usb.py` or an `It 'AC-N:`
     block in `scripts/tests/SetupWindowsUsb.Tests.ps1`; then the Privacy scan.
   - `--privacy`: the Privacy scan alone.
   - `--state`: print the state id (Validation stage contract).
   - `hub`: the hub checks of row 11a: an enabled inbound rule named `Fleet USB receive 8771` for
     TCP 8771 (read with `Get-NetFirewallRule` through `pwsh`); the file `$env:FLEET_RUSTDESK_KEY_FILE`
     holds one key that matches the `fleet_rustdesk.json` key rule; and TCP 21116 answers at
     `$env:FLEET_RUSTDESK_HOST`. It prints pass or fail per check, never the host or the key.
   - `live <name> --mode fresh|rerun --receive <receipt>`: the live checks of WP-K7 (AC-23 to AC-26).
   - `--selftest`: each mode's pass and fail cases on temporary files, with no network and no member.
     It includes at least: `--red` refusing a pytest receipt whose only failures are fixture `ERROR`
     lines, a collection error, and a Pester receipt with `FailedBlocks=1`; `--pytest` excusing the
     known failure, refusing any other failure, and failing when the known failure passes; one
     planted hit per Privacy scan class, each found; the guide URL passing and the same host on
     another path found; and `live` refusing a stale inbox record (a `run_id` that is not the one in
     the receive receipt), a receive receipt that took zero records, and a rerun whose `run_id`
     equals the fresh run's.
2. Run `check_kit.py --backup` before any kit file changes.
3. Copy `docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1` unchanged into the plan folder.
4. Run the baseline: `check_kit.py --baseline`, the Pester gate on `scripts/tests/SetupMember.Tests.ps1`,
   and `python -m pytest core/tools/tests scripts/tests -q -rA` checked by `check_kit.py --pytest`.
   On 2026-11-15 the full run on the tree with the human's four uncommitted kit edits gave
   `3 failed, 4873 passed, 1 skipped` (EA-2 corrects the first note of `1 failed, 322 passed`, which came from a
   narrower run), and the three failures are the three `KNOWN_FAILURES` entries. A baseline with any other
   failure is stop condition 2.

**Privacy scan.** **Scope:** every file this plan adds or changes (the Files Modified table and the
plan folder), the handoff, the reflection, both rolling review files, and `docs/execution/metrics.md`
(the scan reads only the lines that name `2026-11-15-usb-kit-usability`); a scope file that does not
exist yet is skipped and named. **Classes:**

1. an IPv4 literal outside `127.0.0.0/8`, `0.0.0.0`, the one link-local test address `169.254.7.7` (EA-12, EA-14) and
   the documentation ranges `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`;
2. an e-mail address other than a `noreply` address;
3. a literal user path: `<drive>:\Users\<name>` or `<drive>:/Users/<name>` (any slash, any case),
   `/home/<name>` and `/Users/<name>`, where `<name>` is not a placeholder (`<…>`, `$…`, `%…%`, `~`)
   and not `Public`, `Shared` or `Default`;
4. a MAC address (`xx:xx:xx:xx:xx:xx` or with `-`);
5. a deny term, read at run time and never written to a tracked file, matched case-insensitively on
   word boundaries: the hub's member names from `~/.ssh/fleet_members.json` and the `Host` names of
   `~/.ssh/config`; the record names, `rustdesk_id`, `host_key` and `addresses` values of every record
   under `$env:FLEET_INBOX/members/` and `$env:FLEET_USB_FOLDER/members/` when those are set; the
   hub's host name; the local account name (`getpass.getuser()`); the global `git config user.name`
   and `user.email`, unless the address is a `noreply` address.

**The one exception** is the exact guide URL
`https://matbanik.info/hobbies/systems/posts/rustdesk-server-on-windows-without-docker/`, which the
scan removes from a line before it checks the line; the same host on any other path is still a hit.
The scan prints only the file, the line number and the class number of a hit, never the matched text.
A hit is stop condition 6.

### WP-K1: Record v2, the Name rule and non-fatal steps

**Testable scripts.** `setup-unix.sh` becomes functions plus `main "$@"`, called only when the file
is run, not sourced (`[ "${BASH_SOURCE[0]}" = "$0" ] && main "$@"`). `set -euo pipefail` stays, and
each step runs in a function whose failure is caught and recorded (`run_step <id> <function>`), so a
failing command inside a step ends that step, not the script. `setup-windows.ps1` gets a
`-LibraryOnly` switch that defines the functions and returns; `#Requires -RunAsAdministrator` is
replaced by the `elevate` step's `IsInRole` check, so the script loads in tests and still writes a
record when it is not elevated. Every external command that a test must replace goes through one
small wrapper function per command family (`Invoke-Native` in PowerShell, `run` in bash), so Pester
`Mock` and bash stub folders on `PATH` can replace it.

**Windows elevation.** `Setup Windows.cmd` no longer elevates and no longer exits before the script
runs. It runs `powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-windows.ps1"`
unelevated, then `pause`. When `setup-windows.ps1` starts without admin rights, it makes the Run id,
writes the first checkpoint, and starts itself elevated:
`Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList (Get-ElevatedArgs $PSCommandPath $id $user)`.
**Elevated arguments.** `Start-Process` joins an `-ArgumentList` array with spaces and does not quote
its elements, so a drive folder such as `E:\Fleet Kit\` or an Account such as `Lab User` would split.
`Get-ElevatedArgs` therefore returns one string,
`-NoProfile -ExecutionPolicy Bypass -File "<self>" -RunId <id> -ForUser "<user>"`, with literal double
quotes around the script path and the Account (a Windows path and a Windows account name cannot hold
`"`; the Run id has no spaces by its definition). After the child exits, it reads `members/<name>.json`. If the `run_id` there is this run's and
`final` is true, the elevated run wrote the record, and the parent only prints its summary. In every
other case, which includes a UAC prompt that the human cancels or denies (`Start-Process` throws;
Win32 error 1223) and an elevated child that died before its finalize, the parent finalizes the
record itself: `elevate` `failed` with detail `elevation cancelled or failed: <reason>`, every step
that needs admin `skipped`, and then the Send. The record therefore comes back even when the human
says no at the UAC prompt.

**Record v2 on both sides.** Both scripts build the record per Record v2. The bash JSON writer escapes
`\`, `"` and every control character (`\n`, `\r`, `\t` as escapes; other control characters as
`\u00XX`). `fleet_usb.py read_record` accepts v1 records unchanged and v2 records per Record v2
(checkpoints included), and refuses any other `v`.

**Windows PATH fix.** After each tool install the script rebuilds `$env:Path` from the Machine and
User registry values, and it adds `%USERPROFILE%\.local\bin` to the User `Path` once (no second copy
on a rerun). A tool that is still not found ends its step `failed` with detail `not on PATH after
install`; it never throws out of the script.

**Name.** Both scripts use the Name rule (the name fix made by hand on an earlier member).

**Import of v2.** `import` prints one line per record: name, `ok`, `failed: <ids of failed steps>`
or `incomplete after <last step>` (a record with `final` false), the delivery status, then the SSH
result. A v2 record without a host key (its `host_key` step not `ok`) is reported and skipped, and it
counts as a failure for the exit code. A record with `final` false but an `ok` `host_key` step is
imported (the SSH admin access exists) and still counts as a failure for the exit code. The delivery
status never changes the result. A record that passes keeps the existing behavior (pin, config, test
connection).

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-1 | unit | `setup-unix.sh`, run as a file under bash with stub commands and `FLEET_ROOT` set, writes `members/<name>.json` on every exit path: all steps ok (exit 0, `ok` true, `final` true); one step's command fails (exit 1, that step `failed`, the later steps still run, `ok` false); an unexpected error outside any step (exit 1, record still written with `final` true); a stub step that sends the script `SIGINT`, and one that sends `SIGHUP` (record `final` true, that step `failed` with detail `interrupted`, exit non-zero); a stub step that sends itself `SIGKILL` (the drive holds the checkpoint of the steps before it, `final` false). The interruption during the Send is AC-15's case, because row 9 writes the Send. After each step a checkpoint exists (a stub step reads the drive file and sees the steps before it). | Human-approved (2026-11-15: "nothing is being written back") | A stub `apt-get` that exits 100 must not leave the drive without a record. |
| AC-2 | unit | `setup-windows.ps1 -LibraryOnly` with mocked commands: `Invoke-Setup` writes the record when every step is ok, when one step throws (that step `failed`, `ok` false, later steps run), and when a step raises `PipelineStoppedException` (Ctrl+C: `final` true, that step `failed` with detail `interrupted`). Windows elevation: a mocked `Start-Process` that throws error 1223 → the unelevated parent finalizes the record (`elevate` `failed`, the admin steps `skipped`) and sends it; a child that wrote a final record with this `run_id` → the parent writes no second record; a child that left only a checkpoint → the parent finalizes it. Elevated arguments: the string from `Get-ElevatedArgs` for a script in a temp folder whose name holds a space and the Account `Lab User`, passed to an unelevated `Start-Process powershell -Wait -PassThru -ArgumentList` on a probe script at that path, makes the probe receive `-RunId` and `-ForUser` with exactly those values. Static: `Setup Windows.cmd` holds no `exit /b` and no `-Verb RunAs`, and runs `setup-windows.ps1`. | Human-approved | A mocked `Add-WindowsCapability` that throws must not stop the record; a cancelled UAC prompt must not leave the drive without a final record; a script path with a space must not reach the child split. |
| AC-3 | unit | The Name rule gives the same result in bash and PowerShell for `Lab_Mini07`, `--Lab PC__2--`, `___`, a 70-character name and `LAB-PC`, and each result matches `NAME`. | Local Canon (`fleet_usb.py:35`; the name fix made by hand on an earlier member) | `Lab_Mini07` must not give `lab_mini07`. |
| AC-4 | unit | `read_record` accepts a valid v1 record, a valid v2 record, a v2 checkpoint (`final` false), and each `delivery` form (null, `pending`, `sent`, `failed`); refuses a v2 record with an unknown key, a bad `status`, a bad `rustdesk_id`, an `ok` true beside a failed step, an `ok` true with `final` false, a bad `delivery` status, and a `host_key` step `ok` without a host key; refuses `v` 3. A v2 record written by the bash JSON writer with quotes, backslashes, tabs, newlines and non-ASCII text in a detail parses and passes. | Local Canon (`fleet_usb.py:92-120`) | Each refused case raises `ValueError`. |
| AC-5 | unit | Windows PATH fix: `%USERPROFILE%\.local\bin` is in the User `Path` once after two runs, and a tool missing after its install ends `failed` with `not on PATH after install`. | Human-approved (the PATH fix made by hand on an earlier member) | A missing `claude` after install must not throw. |
| AC-6 | unit | `import` of a folder with one good v2 record (`delivery` `failed`, as an offline member leaves it) and one v2 record whose `host_key` step failed: prints the failed step ids and the delivery status, imports the first, exits 1. A checkpoint with an `ok` `host_key` step prints `incomplete after <step>`, is imported, and exits 1. A v1 record imports as before. | Local Canon (`fleet_usb.py:162-201`) | The failed record must not be pinned; a `delivery` `failed` must not fail the good record. |

### WP-K2: Unix elevation without a working `sudo`

The launchers and the README run the script with `bash`, never with `sudo`:
`Setup Linux.desktop` runs `bash "$f"`, `Setup Mac.command` runs `bash ./setup-unix.sh`, and the
README's terminal line is `bash /media/$USER/*/fleet-usb/setup-unix.sh` (Linux) and
`bash /Volumes/*/fleet-usb/setup-unix.sh` (macOS). `bash <file>` needs no exec bit, which FAT and
exFAT drives lack.

When `setup-unix.sh` starts without root, it makes a `run_id`, then re-runs itself as root through the
first elevator that works, in this order:

1. **Repair.** On Linux, when `/usr/bin/sudo` is a dangling link and `update-alternatives` exists, it
   first runs `pkexec update-alternatives --auto sudo` (one prompt), and prints what it did.
2. `sudo bash <abs-script> --for-user <account> --run-id <id>`; then `sudo-rs …`; then
   `sudo.ws …`; then `pkexec bash <abs-script> --for-user <account> --run-id <id>`. An elevator
   counts only if it is on `PATH` or in `/usr/bin`. **Fallback codes:** the next elevator is tried
   only when the previous one is missing or exits 126 or 127 (it could not run); any other exit
   ends the chain. This is the only statement of these codes. No elevator uses `-E`, which sudo-rs
   lacks.
3. After the elevated run exits, the script reads `members/<name>.json`. If its `run_id` is this
   run's and `final` is true, the parent only prints the summary. Otherwise (a wrong password, no
   elevator, or an elevated run that died before its finalize) the parent finalizes the record
   itself, as the Account, with `elevate` `failed` and every root step `skipped`, and sends it.

As root, every command that runs as the Account uses the Account environment. The sudoers file is
checked with `visudo -cf`, or with `visudo.ws -cf` when `visudo` is missing. The script never switches
the system's sudo alternative (D-4).

Row 5 changes the launch line in the README's "If a double-click does nothing" block (the `bash`
forms above) together with the launchers, so AC-9's README check passes in row 5; row 11 rewrites
the rest of the README.

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-7 | unit | With stubs: no `sudo` on `PATH` but `sudo-rs` present → re-run through `sudo-rs` with `--for-user` and `--run-id`; a dangling `sudo` link → the repair runs before the chain; every elevator missing → a final record as the Account with `elevate` `failed`, written once; an elevated run that wrote a final record with this `run_id` → no second record; an elevated run that left only a checkpoint → the parent finalizes it. | Research-backed (Ubuntu sudo-rs docs; LP 2130973) | An elevator exit that is not a fallback code (WP-K2) must not try the next one. |
| AC-8 | unit | As root, Account commands run with the Account environment: `runuser -u <account> -- env -i …` on Linux and `sudo -u <account> -H env -i …` on macOS, with the exact `PATH` of that definition; the sudoers check uses `visudo.ws` when `visudo` is missing; no command line holds `sudo -E`. | Research-backed | A missing `visudo` and `visudo.ws` ends `admin_rights` `failed`, and the sudoers file is not left in place. |
| AC-9 | unit | Static: `Setup Linux.desktop`, `Setup Mac.command` and `usb/README.md` hold no `sudo bash`; each launcher runs the script with `bash`. | Human-approved (2026-11-15 sudo report) | A `sudo bash` line fails the test. |

### WP-K3: Prerequisites

| System | Step `packages` | Step `pwsh` | Steps `uv`, `claude`, `codex` (as the Account) |
|---|---|---|---|
| Windows | `winget install --id <id> -e --silent --accept-package-agreements --accept-source-agreements` for `Git.Git` and `Python.Python.3.14`; with no `winget`, `failed` with detail `install App Installer from the Microsoft Store` | winget `Microsoft.PowerShell` | `irm https://astral.sh/uv/install.ps1 \| iex`; the existing `claude` and `codex` installers (D-1) |
| Linux (apt) | `apt-get install -y` of `openssh-server curl git python3 python3-venv ca-certificates`, with `DPkg::Lock::Timeout=600` | `snap install powershell --classic` when `snap` exists; else the newest stable `powershell-<v>-linux-<x64\|arm64>.tar.gz` from GitHub into `/opt/microsoft/powershell/7`, linked from `/usr/local/bin/pwsh` | `curl -LsSf https://astral.sh/uv/install.sh \| sh`; the existing installers |
| Linux (dnf) | `dnf install -y` of `openssh-server curl git python3 ca-certificates` | as apt | as apt |
| macOS | none (`skipped`, `not on macos`); the `homebrew` step (before `pwsh`, after `admin_rights`) installs Homebrew as the Account with `NONINTERACTIVE=1` in the Account environment, then `brew install git python uv` | `brew install powershell` (the formula, as the Account; the cask is gone, `core/.agent/docs/macos-setup.md` §8) | `uv` from brew; the existing installers |

A winget exit that means "already installed" (`0x8A15002B`) counts as `ok`. A package step that
installs nothing because everything is present ends `ok`. At the end, the script records each tool's
version (`git --version`, `python3 --version` or `python --version`, `pwsh --version`, `uv --version`,
`claude --version`, `codex --version`) in `tools`, each run in the Account environment (Unix) or
after the PATH rebuild (Windows), so a tool installed earlier in the same run is found; a missing
tool has no key. Then `tool_links` (Unix) makes the same tools reachable from an SSH command.

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-10 | unit | Linux with stubs, started from a minimal `PATH` (`/usr/bin:/bin` plus the stub folder): the apt branch installs the package list with the lock timeout; the dnf branch its list; `pwsh` uses snap when present, else the tarball path; `uv`, `claude` and `codex` run as the Account in the Account environment; stub installers that place `uv`, `claude` and `codex` only under `<home>/.local/bin` are still found, and `tools` holds their versions; `tool_links` makes `/usr/local/bin` links under `FLEET_ROOT`, and a shell with sshd's `PATH` finds each tool; a rerun leaves the links as they are. | Human-approved ("No powershell, git etc are being loaded") | A failed snap install falls back to the tarball; a failed tarball ends `pwsh` `failed` and `uv` still runs; an existing file of another target at a link path is left alone and named in the detail. |
| AC-11 | unit | Windows with mocks: winget runs for the three ids; `0x8A15002B` counts as `ok`; no winget ends `packages` and `pwsh` `failed` with the App Installer detail; a tool that the mocked installer adds only to the User `Path` registry value is found after the PATH rebuild; `tools` holds the versions. | Human-approved | No winget must not throw. |
| AC-12 | unit | macOS with stubs, from a minimal `PATH`: the order is `admin_rights`, `homebrew`, `pwsh`; `homebrew` runs as the Account; `pwsh` runs `brew install powershell` (no `--cask`) and `pwsh --version` is found under `<brew>/bin` in the same run; `pwsh` is `skipped` with `needs homebrew` when Homebrew failed; `tool_links` writes the `~/.zshenv` block once over two runs; the block is POSIX `sh` text, and `env -i HOME=<home> PATH=/usr/bin:/bin:/usr/sbin:/sbin bash -c '. <home>/.zshenv; command -v pwsh uv claude codex'` (bash stands in for zsh, which the Windows test host lacks) finds all four. | Research-backed (Homebrew install docs; `core/.agent/docs/macos-setup.md` §8) | Homebrew must not run as root; a login shell other than zsh ends `tool_links` `failed`. |

### WP-K4: Network write-back

**`prepare`** gains `--hub-url URL` (repeatable). Without it, the URLs are `http://<a>:8771` for each
IPv4 address of the hub from `socket.getaddrinfo(socket.gethostname(), None, AF_INET)`, without
loopback and link-local addresses (`ipaddress` `is_loopback`, `is_link_local`), in that order. The token is read from `~/.ssh/fleet_usb_token`, or
made with `secrets.token_urlsafe(32)` and saved there (mode 600 on POSIX). `prepare` writes the Hub
file and prints the URLs, never the token.

**`receive <folder> [--port 8771] [--bind 0.0.0.0] [--count N] [--timeout S]`** runs a stdlib
`http.server` that serves one route, `POST /v1/usb-record`:

| Case | Answer | Effect |
|---|---|---|
| Header `X-Fleet-Token` missing or not equal to the saved token (`hmac.compare_digest`) | 403 | nothing written |
| `Content-Length` missing or above 65536 | 413 | nothing written |
| Body that `read_record` refuses (it is written to a temp file and checked) | 422, with the reason | nothing written |
| Valid record | 200 | written to `<folder>/members/<name>.json` through a temp file and a rename; one summary line printed: name, os, `ok` or the failed step ids, `rustdesk_id` |
| Any other method or path | 404 | nothing written |

It stops after `--count` distinct names were written, or after `--timeout` seconds. Its summary
line per accepted record also holds `run_id=<id>`, and its last line is `received <N>`. It exits 0
when it took at least one record and 1 when it took none (a timeout with no record). The folder has
the drive's layout, so `import <folder>` works on it unchanged.

**Member send** per the Send definition. The Windows script uses `curl.exe`. The Unix script uses
`curl`; when `curl` is missing (the `packages` step failed), `delivery` is `failed` with `no curl`.

**Hub firewall.** The receiver needs an inbound rule for TCP 8771 on the hub. Row 11a is a human step,
like the `Fleet hub 8770` rule in `bootstrap.md`; the README gives the PowerShell line, which makes a
rule named `Fleet USB receive 8771` on the Private profile.

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-13 | unit | `prepare` with a temp home: makes and reuses the token file, writes `hub.txt` with the `--hub-url` URLs or the computed ones, and never prints the token. | Human-approved (2026-11-15: "sending some kind of message that can reviewed on [the hub]") | A second `prepare` must not change the token. |
| AC-14 | integration | `receive` on an ephemeral port in a thread, with real HTTP requests: a valid record → 200, the file, and a summary line with its `run_id`; wrong token → 403; a 70 000-byte body → 413; a refused record → 422 and no file; `GET /` → 404; `--count 2` stops after two names and prints `received 2`; `--timeout 1` stops with none, prints `received 0` and exits 1; then `import --no-test` on the folder reads the received record. | Human-approved | Each refused request leaves `members/` unchanged. |
| AC-15 | unit | The Unix and Windows send, with a stub `curl`: the drive copy holds `delivery` `pending` before the first POST; tries each URL in order and stops at the first 200; the POSTed body has `delivery` null; the drive copy ends `sent` with that URL, or `failed` with each URL's result when every URL fails or `hub.txt` is missing; end to end, an offline run (every URL fails) with all steps ok exits 0, and its drive copy passes `read_record` with `ok` true and imports with `import --no-test`; a stub `curl` that sends the Unix script `SIGTERM` during the Send leaves the drive copy complete, with `final` true and `delivery` `pending`. | Human-approved | A send failure must not change the exit code that `ok` gives. |

### WP-K5: RustDesk on members with a desktop

**Server (human).** The human builds the RustDesk ID and relay server on the hub from the published
guide <https://matbanik.info/hobbies/systems/posts/rustdesk-server-on-windows-without-docker/>. The
README links it and names the two values that `prepare` needs: the server's host address and its
public key (`id_ed25519.pub` in the server folder).

**`prepare`** gains `--rustdesk-host HOST` and `--rustdesk-key KEY | --rustdesk-key-file FILE`. The
values are saved to `~/.ssh/fleet_rustdesk.json` and reused by a later `prepare` without them. With a
server configured, `prepare` reads the newest stable release from
`https://api.github.com/repos/rustdesk/rustdesk/releases/latest`, picks one asset per platform by
these name patterns, downloads each into `<drive>/rustdesk/`, and writes the RustDesk file:

| Platform | Asset name pattern |
|---|---|
| windows-x86_64 | `^rustdesk-[0-9.]+-x86_64\.msi$` |
| linux-x86_64 deb | `^rustdesk-[0-9.]+-x86_64\.deb$` |
| linux-aarch64 deb | `^rustdesk-[0-9.]+-aarch64\.deb$` |
| linux-x86_64 rpm | `^rustdesk-[0-9.]+-0\.x86_64\.rpm$` |
| macos-x86_64 | `^rustdesk-[0-9.]+-x86_64\.dmg$` |
| macos-aarch64 | `^rustdesk-[0-9.]+-aarch64\.dmg$` |

A platform with no matching asset is printed and left out. An asset already on the drive with the
same sha256 is not downloaded again. Without a configured server, `prepare` writes no RustDesk file,
and the members' `rustdesk` step ends `skipped` with `no server configured`. The network calls go
through one function, so tests pass a fixture release and fake downloads.

**Member step `rustdesk`.** Skipped with `no desktop` when `gui` is false, and with `no asset for
<platform>` when the RustDesk file has none. Otherwise:

1. Check the asset's sha256 against the RustDesk file; a mismatch ends the step `failed` and installs
   nothing.
2. Install: Windows `msiexec /i <msi> /qn /norestart` (waited for); Linux `apt-get install -y ./<deb>`
   or `dnf install -y ./<rpm>`, then `systemctl enable --now rustdesk`; macOS: `hdiutil attach
   -nobrowse -readonly` the dmg, `ditto` `RustDesk.app` to `/Applications`, `hdiutil detach`. An
   installed version equal to the file's `version` skips the install.
3. **Start (macOS).** The GUI installer of RustDesk asks for a password and writes two launchd jobs
   (RustDesk 1.5.3 `src/platform/privileges_scripts/install.scpt`, `daemon.plist`, `agent.plist`).
   The script does the same as root, with no prompt: it writes
   `/Library/LaunchDaemons/com.carriez.RustDesk_service.plist` (label
   `com.carriez.RustDesk_service`, program `/Applications/RustDesk.app/Contents/MacOS/service`,
   `RunAtLoad` and `KeepAlive` true) and `/Library/LaunchAgents/com.carriez.RustDesk_server.plist`
   (label `com.carriez.RustDesk_server`, program arguments
   `/Applications/RustDesk.app/Contents/MacOS/RustDesk --server`, `LimitLoadToSessionType`
   `LoginWindow` and `Aqua`, `RunAtLoad` true), owner `root:wheel`, mode 644, with the same keys as
   those two 1.5.3 files. It then runs `launchctl bootout system/com.carriez.RustDesk_service`
   (errors ignored) and `launchctl bootstrap system <daemon plist>`, and, when the Account has a GUI
   session (`launchctl print gui/<uid>` succeeds), `launchctl bootout gui/<uid>/com.carriez.RustDesk_server`
   (errors ignored) and then `launchctl bootstrap gui/<uid> <agent plist>`; without one, the agent
   starts at the next login. Each job is booted out before its bootstrap, because `bootstrap` fails
   on a label that is already loaded (RustDesk 1.5.3 `src/platform/macos.rs` boots out the GUI agent
   and the system daemon separately for the same reason). This is the **macOS restart**: step 5 and
   every rerun use the same bootout-then-bootstrap pair for both jobs, so a second setup and a restart
   in the same run both reload the running processes.
4. **Ready.** The RustDesk binary is `rustdesk` on Linux, `C:\Program Files\RustDesk\rustdesk.exe`
   on Windows and `/Applications/RustDesk.app/Contents/MacOS/RustDesk` on macOS. Its `--config`,
   `--password` and `--option` forms need an installed copy and root, and they reach the running
   service over IPC (RustDesk 1.5.3 `src/core_main.rs`). So the step waits until `--get-id` prints an
   id, polling every 2 s for up to 60 s (`FLEET_RUSTDESK_WAIT_S` overrides the 60, so a test can use 1); with no id by then, the step ends `failed` with detail
   `service not ready`.
5. Configure: run `<binary> --config "host=<host>,key=<key>"` as root (Windows: the elevated
   process). Then read the service's `RustDesk2.toml` (Windows
   `C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\`, Linux
   `/root/.config/rustdesk/`, macOS `/var/root/Library/Preferences/com.carriez.RustDesk/`, and the
   Account's own config folder); if `custom-rendezvous-server` is not the host, write `[options]`
   `custom-rendezvous-server = '<host>'` and `key = '<key>'` there and in the Account's folder, then
   restart the service (Windows `Restart-Service RustDesk`, Linux `systemctl restart rustdesk`,
   macOS the macOS restart of step 3) and wait for Ready again.
6. Record `rustdesk_id` from `--get-id`; when that prints no id, from the `id` line of
   `RustDesk.toml` in the service config folder. The version goes in `tools.rustdesk`.
7. macOS: the step ends `ok` with detail `grant Screen Recording and Accessibility at the screen`;
   the README tells the human to do that (macOS allows no script to grant them).

**Password (at `import`).** For each v2 record with a `rustdesk_id` and a full-access SSH test,
`import` sets a permanent RustDesk password over SSH (`<binary> --password <pw>`, as admin). The
password goes to the member on ssh's standard input, which the remote command reads into a
variable (PowerShell `[Console]::In.ReadLine()`, bash `read -r`), so it is never in the hub's command
line or in the remote command string that ssh carries. On the member, RustDesk 1.5.3 has no other
way to set the password than its argument (`src/core_main.rs`, the `--password` branch reads
`args[1]`), so the password is in that one child's argument vector while it runs, which is under a
second (D-7). The password is `~/.ssh/<name>-rustdesk-password.txt` on the hub when that file exists
(so a rerun keeps it), else a new `secrets.token_urlsafe(18)` value saved there first (mode 600 on
POSIX). It is never printed, never written to the drive, the inbox, a record or a receipt, and never
logged; `import` prints only `rustdesk: id <id>, password in <path>`.

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-16 | unit | `prepare` with a fixture release and fake downloads: picks the six assets by pattern, writes `rustdesk/` and `rustdesk.txt` with the sha256 lines, saves `fleet_rustdesk.json` and reuses it; with no server, writes no RustDesk file. | Human-approved (2026-11-15: "include rustdesk setup on each member that has GUI") | A release without an `.msi` asset leaves the Windows line out and still writes the rest. |
| AC-17 | unit | Windows `rustdesk` step with mocks: a sha256 mismatch → `failed`, no `msiexec`; a match → `msiexec /qn`, the Ready wait, `--config`, the TOML fallback when the read-back lacks the host, a restart, and the id from the TOML when `--get-id` prints none; a `--get-id` that never prints an id ends `failed` with `service not ready`. | Research-backed (RustDesk client deployment docs; RustDesk 1.5.3 `src/core_main.rs`) | A mismatch must not call `msiexec`. |
| AC-18 | unit | Unix `rustdesk` step with stubs: no desktop → `skipped`; deb via apt and rpm via dnf; the id from `--get-id` after the Ready wait; `session_type` from `loginctl`. Fresh Mac, with stub `hdiutil`, `ditto` and `launchctl` under `FLEET_ROOT`: the app is copied, both plists are written with the labels and program arguments of step 3 and mode 644, `launchctl bootstrap system` runs before the first `--get-id`, `gui/<uid>` is bootstrapped only when `launchctl print gui/<uid>` succeeds, `--config` runs through `/Applications/RustDesk.app/Contents/MacOS/RustDesk`, and the detail names the two grants. Restart: with a stub `launchctl` that keeps a loaded-label list and fails `bootstrap` of a label already loaded, a second setup run on the same `FLEET_ROOT`, and a first run that takes the TOML fallback, both end the `rustdesk` step `ok`, and each `bootstrap` of a job comes after a `bootout` of that job. | Research-backed (RustDesk 1.5.3 `privileges_scripts`, `src/platform/macos.rs`) | `gui` false must not install anything; a Mac run with no `launchctl bootstrap` must not reach `--config`; a rerun must not fail on an already-loaded GUI job. |
| AC-19 | unit | `import` with a fake SSH: makes the password file once (mode 600 on POSIX), reuses it on a second import, sends the password on the fake ssh's standard input, and the password text appears in no output, no argument of the fake ssh (the remote command string included), no state file and no file under the folder. The remote script, run by bash with a stub `rustdesk` that saves its argument vector, passes the password only as the stub's `--password` argument and writes it nowhere else. | Human-approved | A record without `rustdesk_id` sets no password. |

### WP-K6: Docs and known issues

- `.agent/fleet/usb/README.md`: the new flow — (1) on the hub: the RustDesk server from the guide
  (link), `prepare` with the RustDesk options, the firewall line for 8771, and `receive`;
  (2) on each machine: Windows double-click; Linux and macOS: the `bash` terminal line, or the
  launcher; what the human sees when a step fails, and that the record still comes back;
  (3) on the hub: `import` on the receive folder (or on the drive); the RustDesk password file.
  The Undo section gains RustDesk removal and the PATH entry.
- `.agent/fleet/install-usb/README.md`: keep the human's edit (D-1); add one line pointing to the
  `bash` launch form.
- `core/MANIFEST.md:40`: the kit entry names the network send, `receive`, the RustDesk step and
  `check` by `bash`.
- `.agent/fleet/bootstrap.md`: one line under the Windows section's firewall STOP step naming the
  kit's 8771 rule as a separate, kit-only rule.
- Known issues (through `core/tools/issue_triage.py` with
  `--yaml .agent/context/known-issues.yaml --md .agent/context/known-issues.md`):
  `FLEET-AGY-RETIRED-NAME` (`fleet.py` still lists `agy` in `CAPABILITY_TOOLS` and
  `FORBIDDEN_COMMANDS`, and `test_ac32` expects it), `FLEET-UNIX-MEMBER-BOOTSTRAP-EMPTY`
  (`bootstrap.md` has empty Linux and macOS sections), `FLEET-INSTALLERS-UNVERIFIED` (the kit and
  `setup-member.ps1` run downloaded installers with no signature check), and
  `FLEET-RUSTDESK-WAYLAND` (unattended access on a Wayland session is limited in stable RustDesk),
  and `FLEET-AC38-BILLING-LINE-PIN` (`test_ac38_the_skills_hold_the_member_route_and_the_billing_rule`
  pins fixed lines 340–343 of the skill file, while the rule moved to line 362 in fb2d26d; the plan
  does not edit that test, G36, and WP-K0 lists it in `KNOWN_FAILURES`), and
  `FLEET-INSTALL-RETAINED-CREDITS-TESTS` (EA-2: the Linux install keeps retained credits test files that
  import tests it removes, so `test_no_retained_python_file_needs_a_removed_tool` and
  `test_retained_python_tests_collect` fail on a clean `HEAD` since fb00d40; the plan edits neither the
  tests nor the instantiate script, and WP-K0 lists both in `KNOWN_FAILURES`).

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-20 | unit | Docs: `usb/README.md` holds the guide URL, the `receive` and `import` lines, the 8771 firewall line and the `bash` terminal lines; `core/MANIFEST.md` names `receive` and RustDesk; `bootstrap.md` names port 8771. | Human-approved | A README with `sudo bash` fails AC-9. |
| AC-21 | unit | The six known issues are in `known-issues.yaml`, and `issue_triage.py render --check` passes on the pair. | Local Canon (old plan review findings 5 and 7) | A missing id fails. |
| AC-22 | integration | Package gates: `check_kit.py --gates` passes (no new refcheck or sanitize failure, AC-to-test coverage, the Privacy scan). | Local Canon (`2026-11-04-fleet-agents` gates) | A planted IPv4 in a temp copy fails `--selftest`. |

### WP-K7: Live members

The agent runs `prepare` and `receive` on the hub only when the human asks, with
`$env:FLEET_USB_FOLDER` (the drive folder), `$env:FLEET_INBOX` (the receive folder),
`$env:FLEET_HUB_URL`, `$env:FLEET_RUSTDESK_HOST` and `$env:FLEET_RUSTDESK_KEY_FILE` as the human
gives them, set in each command that needs them. `$env:FLEET_MEMBER` is the record name that the
receiver's summary line printed. No value of these goes into a tracked file or a receipt name.
`receive` runs in the background with `--count 1 --timeout 3600` while the human runs the setup at
the member. `import` reads every record in the inbox, so every member recorded there must be on.

`check_kit.py live <name> --mode fresh|rerun --receive <receipt>` passes when: the receive receipt
of this row shows `received` 1 or more and a summary line for `<name>`, and the inbox record for
`<name>` carries the same `run_id` as that line (so an old record left in the inbox cannot pass);
`ok` is true, `final` is true and `v` is 2; `import` reported full access; over SSH with no login shell (`ssh <member> '<tool> --version'`, the
PATH that sshd gives), `git`, `python` (or `python3`), `pwsh`, `uv`, `claude` and `codex` each print
a version as the Account; for a `gui` member, `rustdesk_id` is
set and the hub's password file exists (the checker tests existence and mode only, never reads it
into output). It saves the password file's sha256, the member's `authorized_keys` line count
(`administrators_authorized_keys` on Windows) and the fresh `run_id` to
`$RECEIPTS_DIR/uk2-live-state-<name>.json`, which is outside the repository. `--mode rerun` also
passes only when the record's `run_id` differs from the saved fresh `run_id`, the sha256 and the
line count are unchanged, and the User `Path` (Windows) holds `.local\bin` once.

**Names in closeout files.** The handoff, the reflection and the reviews name members only as
`<member-1>`, `<member-2>` and so on, and the hub as `<hub-host>`; the raw receipts with the real
names stay under `$RECEIPTS_DIR`, outside the repository. The Privacy scan covers those files.

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-23 | integration | The new mini PC: set up from the drive, its record received over the network, imported with full access, tools present, RustDesk id set (live, row 12). | Human-approved ("I have nother mini pc we will test deployment") | Any failed step fails the row. |
| AC-24 | integration | The same mini PC, setup run again: `ok` true, no duplicate key line, the RustDesk password unchanged (row 13). | Local Canon (README: "repeating it changes nothing") | A changed sha256 fails. |
| AC-25 | integration | A member of the other OS family (Windows or Linux, whichever the mini PC is not), named by the human: AC-23's checks (row 14). | Human-approved (both families failed in the human's test) | as AC-23 |
| AC-26 | integration | A Mac: AC-23's checks (row 15). | Spec (the kit supports macOS) | as AC-23 |

### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| Member record file and HTTP body (v1, v2) | `fleet_usb.py read_record` | Record v2 definition; v1 as today | Unknown keys refused (v2); v1 unchanged |
| HTTP `POST /v1/usb-record` | `fleet_usb.py receive` handler | token header, `Content-Length` ≤ 65536, JSON body | Any other route or method 404 |
| `hub.txt`, `rustdesk.txt` on the drive | Both setup scripts (readers); `prepare` (writer) | Line formats in the Hub file and RustDesk file definitions; token regex; sha256 `^[0-9a-f]{64}$`; file names match the asset patterns | Unknown lines ignored and printed |
| GitHub release JSON | `fleet_usb.py` release reader | `tag_name` `^v?[0-9]+\.[0-9]+\.[0-9]+$`; `prerelease` false; asset names per the pattern table; `browser_download_url` on `https://github.com/` | Other fields ignored |
| `fleet_usb.py` arguments | `argparse` | Ports 1–65535; `--count` ≥ 1; `--timeout` ≥ 1; `--hub-url` starts with `http://` | argparse refuses unknown options |
| `setup-unix.sh` arguments | `main` | `--for-user` matches the Account regex; `--run-id` matches the Run id definition | An unknown argument ends the run before any step, with a record whose `elevate` step is `failed` |
| `~/.ssh/fleet_rustdesk.json` | `prepare` | `host` non-empty without spaces; `key` `^[A-Za-z0-9+/=]{40,64}$` | Unknown keys refused |

### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Record comes back on every exit path | Human-approved | Exit trap / `try-finally` (Record write) |
| Network write-back over a share or a message | Human-approved | HTTP message to `receive` (D-2); share not used |
| Run on Ubuntu with sudo-rs | Research-backed | `bash` launch, elevator chain, no `-E` (D-4) |
| Prerequisites | Human-approved ("No powershell, git etc") | WP-K3 table; versions recorded |
| RustDesk on members with a desktop | Human-approved | WP-K5; GUI rule |
| RustDesk server build | Human-approved (the guide URL) | The human follows the guide; the README links it |
| Python version on Windows | Research-backed | `Python.Python.3.14`, the current stable winget id; a later bump is a one-line change |
| Wayland unattended access | Research-backed | Record `session_type`; known issue (D-3) |

### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/usb/setup-unix.sh` | modify | Functions and `main`, steps, Record v2, exit trap, elevator chain, prerequisites, send, RustDesk |
| `.agent/fleet/usb/setup-windows.ps1` | modify | `-LibraryOnly`, `Invoke-Setup`, steps, Record v2, `try/finally`, PATH fix, winget, send, RustDesk |
| `.agent/fleet/usb/fleet_usb.py` | modify | `read_record` v2, `prepare` options and files, `receive`, `import` summary and RustDesk password; `MEMBER_FILES` unchanged |
| `.agent/fleet/usb/Setup Windows.cmd` | modify | Runs `setup-windows.ps1` unelevated with `-NoProfile -ExecutionPolicy Bypass`, then `pause`; no `-Verb RunAs`, no `exit /b` before the script (WP-K1 Windows elevation) |
| `.agent/fleet/usb/Setup Linux.desktop` | modify | `bash "$f"` without `sudo` |
| `.agent/fleet/usb/Setup Mac.command` | modify | `bash ./setup-unix.sh` without `sudo` |
| `.agent/fleet/usb/README.md` | modify | WP-K6 |
| `.agent/fleet/install-usb/README.md` | modify | The human's edit (D-1), plus the `bash` line |
| `.agent/fleet/bootstrap.md` | modify | The 8771 line |
| `core/MANIFEST.md` | modify | Line 40 |
| `scripts/tests/test_fleet_usb.py` | new | AC-1, AC-3, AC-4, AC-6 to AC-10, AC-12 to AC-16, AC-18 to AC-21 |
| `scripts/tests/SetupWindowsUsb.Tests.ps1` | new | AC-2, AC-3 (PowerShell half), AC-5, AC-11, AC-15 (Windows half), AC-17 |
| `.agent/context/known-issues.yaml`, `.agent/context/known-issues.md` | modify | Six new issues |
| `docs/execution/plans/2026-11-15-usb-kit-usability/` | new | This plan, `task.md`, `check_kit.py`, `run_pester.ps1` |

---

## Out of Scope

| Item | Kind | Deferred-to MEU | Basis |
|------|------|-----------------|-------|
| The hardening of the superseded plan (helper, `from=`, password-off, firewall profile checks, image signature check) | out-of-scope | — | Human-approved, 2026-11-15: "the plan is overly security focused … i don't have issue with full admin access on these computers" |
| Removing `agy` from `fleet.py` | out-of-scope | — | Not a kit problem; filed as `FLEET-AGY-RETIRED-NAME` (WP-K6) so it is owned. Human-approved scope: the 2026-11-15 request names only the kit problems |
| Signature checks of downloaded installers | out-of-scope | — | Human-approved (no security scope); filed as `FLEET-INSTALLERS-UNVERIFIED` |
| The empty Linux and macOS sections of `bootstrap.md` (making a Unix machine a `fleet.py` member) | out-of-scope | — | The kit's contract ends at SSH admin access (`core/MANIFEST.md:40`); filed as `FLEET-UNIX-MEMBER-BOOTSTRAP-EMPTY` |
| A network share (SMB) as the write-back path | out-of-scope | — | D-2 (Research-backed): the HTTP message needs no share credentials on each member |
| `UPDATE-CHECKLIST.md` | out-of-scope | — | `UPDATE-CHECKLIST.md:1` covers refreshing the package from the source repo; the kit is authored in this repo, so no sync-map line applies. Its `core/MANIFEST.md` item (`:495`) is covered by WP-K6 |
| Building the RustDesk server | out-of-scope | — | Human-approved, 2026-11-15: the human follows the guide; the plan only links it |

---

## BUILD_PLAN.md Audit

This package has no `docs/BUILD_PLAN.md`; row 16 proves it.

---

## Verification Plan

All commands run from `P:/agentic-framework` in PowerShell 7, with `$env:RECEIPTS_DIR` set to
`C:/Temp/agentic-framework/receipts` and `$env:AGENT_MODEL_REGISTRY_HOME` set to `P:/.agent`.

### 1. Baseline (row 1)
```powershell
python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --baseline *> $env:RECEIPTS_DIR/uk2-gates-baseline.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk2-gates-baseline.txt -Tail 20; exit $code
```

### 2. Targeted tests
```powershell
python -m pytest scripts/tests/test_fleet_usb.py -q -rfE *> $env:RECEIPTS_DIR/uk2-verify-usb.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk2-verify-usb.txt -Tail 25; exit $code
pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 scripts/tests/SetupMember.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-pester.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk2-pester.txt -Tail 20; exit $code
```

### 3. Fleet regression and full gate
```powershell
python -m pytest core/tools/tests scripts/tests -q -rA *> $env:RECEIPTS_DIR/uk2-full-pytest.txt; $code=$LASTEXITCODE; python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --pytest $env:RECEIPTS_DIR/uk2-full-pytest.txt --exit $code *> $env:RECEIPTS_DIR/uk2-full-pytest-check.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk2-full-pytest-check.txt -Tail 25; exit $code
```

### 4. Package gates
```powershell
python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --gates *> $env:RECEIPTS_DIR/uk2-package-gates.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk2-package-gates.txt -Tail 30; exit $code
```

### 5. Live checks (rows 12 to 15)
```powershell
python .agent/fleet/usb/fleet_usb.py import $env:FLEET_INBOX *> $env:RECEIPTS_DIR/uk2-import-fresh.txt; $code=$LASTEXITCODE; if ($code -ne 0) { Get-Content $env:RECEIPTS_DIR/uk2-import-fresh.txt -Tail 20; exit $code }; python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py live $env:FLEET_MEMBER --mode fresh --receive $env:RECEIPTS_DIR/uk2-receive-fresh.txt *> $env:RECEIPTS_DIR/uk2-live-fresh.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk2-live-fresh.txt -Tail 30; exit $code
```
Rows 13 to 15 use the same form with their own receipt suffix (`rerun`, `other`, `macos`) and mode;
each row starts its own `receive` with the receipt `uk2-receive-<suffix>.txt` and passes that receipt
to `--receive`. The pytest result of the full run (§3) passes only through
`check_kit.py --pytest`, never by the exit code of pytest alone.
`$env:FLEET_MEMBER` is the record name from the receiver's summary line (WP-K7).

### Stop conditions

1. A git command would stage, stash, restore or commit a file outside a COMMIT row the human directed.
2. The baseline (row 1) is red: a gate fails, or pytest has a failure that is not in `KNOWN_FAILURES`.
3. A script that changes a machine (the hub's firewall, a member) would run without the human asking.
4. A live row fails twice on the same step after a fix: stop with the record and the step detail.
5. A row's red receipts hold no failing test for one of the row's listed ACs.
6. A Privacy scan hit.

---

## Decision Log

```yaml
decision_log:
  - id: D-1
    stage: planning
    question: "What happens to the human's four uncommitted kit edits?"
    resolution: autonomous
    class: two-way
    chosen: "A: they become this plan's baseline; row 1 copies them and their diff to uk2-backup/ first, and the final commit carries them"
    source_tag: Local Canon
    precedents: ["2026-11-07-usb-kit-hardening task.md row 0 — waited for the human to commit or discard the same files; the human then tested that state and asked for fixes on top of it"]
    research: { engine: none, sources: [] }
    reasoning: "The human tested the kit with these edits and asked for this plan to fix what they saw, so the edits are the state to build on. The backup makes the choice reversible. Waiting for a separate commit (B) adds a human step for no gain."
  - id: D-2
    stage: planning
    question: "How do members send their record to the hub?"
    resolution: autonomous
    class: two-way
    chosen: "A: an HTTP POST to a new 'fleet_usb.py receive' on port 8771, with a token from the drive"
    source_tag: Research-backed
    precedents: [".agent/fleet/fleet.py — the hub is already a stdlib HTTP server; it was not running on 2026-11-14, so the kit must not depend on it"]
    research: { engine: native, sources: ["https://learn.microsoft.com/windows/win32/fileio/microsoft-smb-protocol-and-cifs-protocol-overview — an SMB write needs a share and credentials on every member; curl is built into Windows 10+, macOS and most Linux"] }
    reasoning: "A message needs no share, no credentials on the member and no fleet.py service; curl exists on all three systems before any install. A fleet.py route (B) ties the kit to the hub service; SMB (C) needs share setup and credentials per member."
  - id: D-3
    stage: planning
    question: "How does the kit handle Wayland sessions for RustDesk?"
    resolution: autonomous
    class: two-way
    chosen: "A: install the stable release, record session_type, check it live, and file FLEET-RUSTDESK-WAYLAND"
    source_tag: Research-backed
    precedents: []
    research: { engine: native, sources: ["https://rustdesk.com/docs/en/client/linux/ — Wayland support is limited in stable releases; X11 login is the documented workaround"] }
    reasoning: "A preview build (B) adds churn on every member; forcing X11 (C) changes the member's login without the human asking. Recording the session type shows where a human step is needed."
  - id: D-4
    stage: planning
    question: "Does the kit switch Ubuntu's sudo back to sudo.ws?"
    resolution: autonomous
    class: two-way
    chosen: "A: no; the script finds a working elevator, and repairs only a dangling sudo link"
    source_tag: Research-backed
    precedents: []
    research: { engine: native, sources: ["https://documentation.ubuntu.com/ — sudo-rs is the default from 25.10; update-alternatives selects sudo.ws when needed", "https://bugs.launchpad.net/ubuntu/+source/rust-sudo-rs/+bug/2130973 — sudo-rs failed on a script without the exec bit"] }
    reasoning: "Switching the system default (B) changes the member beyond what the kit needs; running the script with bash avoids the exec-bit failure, and the chain covers both binaries."
  - id: D-5
    stage: planning
    question: "Where is the RustDesk permanent password made and kept?"
    resolution: autonomous
    class: two-way
    chosen: "A: at import on the hub, set over SSH, kept only in ~/.ssh/<name>-rustdesk-password.txt and reused on later imports"
    source_tag: Local Canon
    precedents: ["the setup of an earlier member in 2026-11 — its RustDesk password file sits in the hub's ~/.ssh under this name"]
    research: { engine: none, sources: [] }
    reasoning: "The drive and the inbox are not secret stores, so the password must not pass through them. Reusing an existing file keeps that member's password."
  - id: D-6
    stage: planning
    question: "Does the record send need TLS?"
    resolution: autonomous
    class: two-way
    chosen: "A: no; plain HTTP on the LAN with the drive's token"
    source_tag: Human-approved
    precedents: []
    research: { engine: none, sources: [] }
    reasoning: "The human ruled out a security scope on 2026-11-15. The record holds no secret (the host key is public), and the token stops stray writes. TLS (B) would need a certificate pin on every member."
    human_message_reference: "USER_EXPLICIT 2026-11-15 'i don't have issue with full admin access on these computers'"
  - id: D-7
    stage: planning
    question: "May the RustDesk password be an argument of the RustDesk process on the member?"
    resolution: autonomous
    class: two-way
    chosen: "A: yes, for the one `--password` child only; never on the hub command line, in the ssh remote command string, a receipt, the drive, the inbox, a record or a log"
    source_tag: Research-backed
    precedents: []
    research: { engine: native, sources: ["RustDesk 1.5.3 src/core_main.rs — the --password branch reads args[1] and sends it to the service over IPC; the client has no stdin or file form"] }
    reasoning: "RustDesk 1.5.3 gives no other interface. Only local processes on the member can see the argument, for the life of that child, and the human ruled out a security scope on 2026-11-15. Writing the password into RustDesk2.toml (B) bypasses the service's hashing and breaks on a version change."
    human_message_reference: "USER_EXPLICIT 2026-11-15 'i don't have issue with full admin access on these computers'"
```

---

## Research References

- Ubuntu sudo-rs: Ubuntu 25.10 release notes and the sudo-rs documentation (sudo-rs default,
  `sudo.ws` alternative, no `-E`); Launchpad bug 2130973.
- RustDesk client deployment docs (`--config`, `--password`, `--get-id`, `RustDesk2.toml`), the
  RustDesk Linux docs (Wayland), and the releases API
  `https://api.github.com/repos/rustdesk/rustdesk/releases/latest`.
- RustDesk 1.5.3 source (tag `1.5.3`): `src/core_main.rs` (the `--password`, `--config` and
  `--get-id` branches, the installed and root checks), `src/platform/macos.rs` (`is_installed`, the
  app path), `src/platform/privileges_scripts/install.scpt`, `daemon.plist` and `agent.plist` (the
  launchd labels and program arguments).
- RustDesk server on Windows without Docker:
  <https://matbanik.info/hobbies/systems/posts/rustdesk-server-on-windows-without-docker/>.
- winget install arguments and exit codes (`0x8A15002B` already installed).
- PowerShell on Linux: the snap package and the GitHub release tarballs.

## Validation stage contract

- **Static:** `bash -n` and the PowerShell parser run inside the test files; `lint_task_contract.py`
  on `task.md`.
- **Targeted:** §2, per row, after the row's red receipt.
- **Fresh full:** §3 and §4 at H1-2, after the last code change, then H1-6b.
- **Runtime:** §5, on real members, rows 12 to 15.
- **State id** (`check_kit.py --state`): the sha256 of HEAD's commit id plus, for each path in
  `git status --porcelain --untracked-files=all` under the Files Modified paths, the path and the
  sha256 of its bytes, sorted by path, leaving out this plan's `task.md`, whose row marks change after
  H1-2 and are no tested input (EA-13). The handoff's `tested_state` is this id at H1-2; H1-6b
  recomputes it and reruns §3 and §4 if it changed.
- Native shell: PowerShell 7; every command redirects all streams to `$env:RECEIPTS_DIR` and keeps
  the exit code.
