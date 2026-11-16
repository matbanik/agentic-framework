---
project: "2026-11-07-usb-kit-hardening"
date: "2026-11-07"
source: "USER_EXPLICIT 2026-11-07 direction on the fleet USB kit review (seven findings, restated in Goal)"
meus: []
run_parameters: "absent — run parameters are disabled in this repo (run_parameters.py status: policy_missing); Step 0 resolved manual"
status: "in_progress"
template_version: "2.4"
---

# Implementation Plan: USB Kit Hardening

> **Project**: `2026-11-07-usb-kit-hardening`
> **Build Plan Section(s)**: none. This framework package has no `docs/BUILD_PLAN.md` hub. The scope source is the review of commits `28f76e0` (the fleet USB drive kit) and `f8ce76e` (the Ubuntu installer drive), which the human directed on 2026-11-07: "do all 3 as you recommended and proceed".
> **Status**: `in_progress`

---

## Goal

The USB drive kit gives <hub-host> an SSH admin connection to a new Windows, macOS or Linux member. The installer
drive installs Ubuntu on a new Linux member. A review of both kits found seven gaps. This plan closes them:

1. **Finding 1.** `setup-unix.sh:107` gives the member account `NOPASSWD: ALL`. A stolen hub key is root on every
   macOS and Linux member.
2. **Finding 2.** `setup-windows.ps1:76` and `:81` open port 22 with `-Profile Any`, so it also answers on a Public
   network, where "the local subnet" is a stranger's network.
3. **Finding 3.** The Unix setup enables no firewall when `ufw` is off, and no setup turns off password sign-in over
   SSH. The fix must keep an order that cannot lock the admin out.
4. **Finding 4.** Nothing checks a download against the publisher's signature. `write-installer-usb.ps1:32` matches
   `SHA256SUMS` loosely and runs no `gpg`, and the uncommitted CLI step pipes a download into a shell.
5. **Finding 5.** `fleet.py:69` and `:71` still name the retired `agy` CLI, which the source repo's retired-surface
   scan refuses.
6. **Finding 6.** `UPDATE-CHECKLIST.md` has no step for the kits, and `core/MANIFEST.md:35-42` lists the fleet files
   under the registry-home section, beside broken text at `:21-22`.
7. **Finding 7.** The kits have no tests.

It is done when every finding has a test that failed first, the package gates show no new failure, and each live
member, set up from the drive, passes the hub's import with password sign-in refused.

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning_and_execution
  eligible_tools: []
  decision: not_applicable
  eligibility_basis: "graphify-out/graph.json is absent. Headroom 0.24.0 is installed, but the payloads here are source code and exact evidence, which are bypass classes in core/.agent/docs/context-tool-decision-gate.md."
  human_message_reference: null
```

## Handoff Set

`meus: []`, so there is one project handoff and one rolling review.

| Scope | Canonical path |
|---|---|
| Project handoff | `.agent/context/handoffs/2026-11-07-usb-kit-hardening-handoff.md` |
| Plan review | `.agent/context/handoffs/2026-11-07-usb-kit-hardening-plan-critical-review.md` |
| Rolling execution review | `.agent/context/handoffs/2026-11-07-usb-kit-hardening-implementation-critical-review.md` |

## Work Packages and Context Lifecycle

| ID | Work | depends_on | context_strategy | durable_outputs |
|---|---|---|---|---|
| WP-U1 | Remove the retired CLI's name from `fleet.py` (finding 5), then the live hello | — | `shared` | `.agent/fleet/fleet.py`; `scripts/tests/test_fleet_usb.py`; live receipt |
| WP-U2 | Testable kit scripts: load guards, `-LibraryOnly`, the bash-stub harness, static checks, characterization (finding 7) | WP-U1 | `shared` | The three kit scripts; `.gitattributes`; the three new test files |
| WP-U3 | The admin helper and one exact sudoers line; the hub's admin check (finding 1) | WP-U2 | `compact_continue` | `.agent/fleet/usb/fleet-admin.sh`; `setup-unix.sh`; `fleet_usb.py`. After compaction, re-read `task.md`, D-1 and these outputs |
| WP-U4 | The Windows firewall rule on the Domain and Private profiles only (finding 2) | WP-U3 | `shared` | `setup-windows.ps1`; `SetupWindowsUsb.Tests.ps1` |
| WP-U5 | Unix: console guard, subnet firewall, `from=`, password off, in a safe order (finding 3) | WP-U4 | `compact_continue` | `setup-unix.sh`; `test_fleet_usb.py`. After compaction, re-read `task.md`, the Named definitions and these outputs |
| WP-U5w | Windows: console guard and password off, with restore on a bad config (finding 3) | WP-U5 | `compact_continue` | `setup-windows.ps1`; `SetupWindowsUsb.Tests.ps1`. After compaction, re-read `task.md` and these outputs |
| WP-U5b | The hub's password probe in `fleet_usb.py import` (finding 3), with the fingerprint lines and the pin refusal (scope addition) | WP-U5w | `shared` | `fleet_usb.py`; `test_fleet_usb.py` |
| WP-U6 | Signature checks: the Ubuntu image, and the CLIs if row 0 keeps that step (finding 4) | WP-U5b | `compact_continue` | `write-installer-usb.ps1`; the CLI step; the two Pester files. After compaction, re-read `task.md`, D-2 and these outputs |
| WP-U6p | PowerShell on macOS and Linux members: the pin that `prepare` writes, and the hash-checked install in `setup-unix.sh` (amendment, D-3); the clean start, the Root tool check and the launch form (review F-037) | WP-U6 | `compact_continue` | `fleet_usb.py`; `setup-unix.sh`; the two Unix launchers; `test_fleet_usb.py`; Probe-3 receipt. After compaction, re-read `task.md`, D-3, A-19 to A-22, the Root tool path definition, the WP-U6p section, AC-32 and these outputs |
| WP-U7 | Docs: `MANIFEST.md`, `UPDATE-CHECKLIST.md`, `bootstrap.md`, both READMEs (finding 6) | WP-U6p | `shared` | The five doc files |
| WP-U8 | Package gates, then the live Windows, Linux and macOS members | WP-U7 | `shared` | Gate and live receipts |

**Lane ownership: omitted.** This is a main-tree plan. The package repo is not instantiated: it has no
`.agent/credits/worktree.json`, so `executor_worktree.py` has no lane configuration here, and the precedent plan
`docs/execution/plans/2026-11-04-fleet-agents/` ran on the main tree.

---

## User Review Required

> [!IMPORTANT]
> **Run parameters:** `manual`. They are disabled in this repo (`policy_missing`). Execution starts only when the
> human says proceed after the plan is approved. Every commit needs the human's word, and nothing is pushed.
>
> **Review limits:** `repo` (no `review_limits` block). Plan loop 10 rounds: 3 from `core/.agent/review-limits.json`,
> 3 that the human added on 2026-11-08 ("Add 3 more rounds"), 1 for the amendment of 2026-11-14 (D-3 A), 1 that
> the human added on 2026-11-14 after round 7 ("fix all findings and run more review round", for this plan), 1
> that the human added on 2026-11-14 after round 8 ("add round 9"), and 1 that the human added on 2026-11-14 after
> round 9 ("fix and add round 10"), with 10,500,000 tokens. Execution loop 6 rounds and
> 21,000,000 tokens, from the same file.
>
> **Row 0 is the human's.** Four kit files have uncommitted changes: both READMEs, `setup-unix.sh` and
> `setup-windows.ps1`. They add a step that installs Claude Code and Codex. The human commits or discards them before
> execution starts. The agent never stages, stashes, restores or commits them. The diff fixes none of the seven
> findings. It adds to finding 4 (`setup-unix.sh:125` pipes a download into a shell; `setup-windows.ps1:35-37`
> downloads and runs an installer with no check). D-2 applies if either script keeps its step; row 0 records each.
>
> **Rows that change a member run when the human asks.** They are rows 2a, 12, 13 and 14. The human can name them all
> in one message when saying proceed. Row 14 needs a macOS machine. Without one it is `[B]` with a follow-up.
>
> **D-1 (admin rights on macOS and Linux) and D-2 (the CLI check) are ruled A.** The human typed "recoomendations for
> D-1 D-2 accepted" on 2026-11-08, as the coordinator relayed it. Row 3a checks the D-1 line before row 4, and row 7a
> the D-2 line before row 8a; each passes only on that typed A. The round-3 corrections made option A stricter, not
> different (D-1 reasoning in the Decision Log).
>
> **Scope addition, typed by the human on 2026-11-08 ("add it", relayed by the coordinator).** Each setup and `import`
> print host key fingerprints, `import` refuses a changed key for a pinned name (WP-U5b, AC-31), the setup stops on a
> name clash (Record retire), and the README says to compare them (WP-U7). No `--expect` lists and no signing.
>
> **Amendment, typed by the human on 2026-11-14 (D-3 A).** The human asked to "add PowerShell to the fleet
> requirments to be deployed on new members", then chose A: add the macOS and Linux install to this parked plan, with
> one more plan-review round, landing after row 0. WP-U6p, row 8b and AC-32 add it. `prepare` pins the newest stable
> PowerShell release that is at least 14 days old (A-21), only when the release notes' SHA-256 and GitHub's asset
> digest agree (A-20); `setup-unix.sh` installs that build as root after a hash check (A-19). The step is not tied to
> row 0. The amendment adds nothing to the Windows kit or to `bootstrap.md` (Out of Scope). The plan loop gets a seventh round for this
> amendment, by the same typed A. After round 7, the human typed "fix all findings and run more review round" on
> 2026-11-14 and confirmed that it is for this plan, so the plan loop gets an eighth round. Round 8 refused to recheck,
> because the round-7 corrections had no blast-radius census (review F-036). The human then typed "add round 9" on
> 2026-11-14, so the plan loop gets a ninth round. Round 9 found the setup's root tools unbound to system folders
> (review F-037). The human then typed "fix and add round 10" on 2026-11-14, so the plan loop gets a tenth round.
> Round 10 is the next review.
>
> **Planning found these, and each is reversible here:**
>
> 1. **`agy` leaves `FORBIDDEN_COMMANDS` too, not only `CAPABILITY_TOOLS` (A-1).** A manifest that names an `agy`
>    binary is then accepted by first word. The CLI is retired, and the source repo's scan refuses the word.
> 2. **The hub restarts first, and an old member is refused until it updates (A-2).** `validate_hello`
>    (`fleet.py:493-494`) refuses a key it doesn't know, so a member that still reports `agy` gets
>    `bad_field:capabilities` until row 2a updates it.
> 3. **After setup, no one can sign in to a member over SSH with a password, not only the hub (A-12).** Undo is one
>    file on macOS and Linux, and one marked block on Windows.
> 4. **The setup refuses to run over SSH (A-5).** It changes SSH itself, so it runs at the machine's own screen. A
>    session inside `tmux` that was started at the screen still passes.
> 5. **A Linux firewall that was off stays off if another service listens on the network (A-11).** Only when the
>    setup itself would turn the firewall on (`ufw` inactive, or `firewalld` stopped), any TCP or UDP listener off
>    loopback, except TCP 22, stops it before the enable. That includes the mDNS and DHCP client sockets of a stock
>    Ubuntu Desktop, whose `ufw` is off by default. The setup prints each listener and the enable command; the human
>    checks those services, runs the command at the screen and runs the setup again. The rerun finds the firewall on,
>    so the check does not run, and the live check (row 13) reads the sockets only for their form.
> 6. **Every SSH firewall rule that the kit did not make is reported, not deleted (A-4).** This holds on `ufw`,
>    `firewalld` and Windows (SSH rule report), and a Windows firewall profile that is off is reported the same way.
>    The live check fails on each one, so the human decides. The kit replaces only its own two things: the stock
>    `firewalld` `ssh` service in each target zone (A-10), and the Windows rule `OpenSSH-Server-In-TCP`.
> 7. **The subnets are fixed at setup time (A-6).** A member that moves to another network needs the setup again at
>    its screen.
> 8. **Windows gets no `from=` on its key (A-3).** Its firewall rule already limits port 22 to the local subnet, on
>    the Domain and Private profiles only. A Public network on a physical adapter stops the setup; a Public `vEthernet`
>    or host-only adapter is printed and does not stop.
> 9. **`setup-member.ps1:41` has the same unchecked download (A-9).** This plan files a known issue for it and does
>    not change that file.
> 10. **The setup stops on a sudoers line that it cannot prove harmless to the helper (A-18).** It names the line and
>     leaves no new rule. The human fixes that policy and runs the setup again.
> 11. **A failed rerun retires the member's old record (A-12, Record retire).** The member is then not importable
>     until a setup passes. A record with this machine's host key under another name is retired too, and printed.
> 12. **The PowerShell step stops when a folder that it writes in is not root-only (A-19, round 7 review).** On an
>     Intel Mac with Homebrew, `/usr/local/bin` belongs to the account, so the step stops there and changes nothing.
>     The human chooses: install PowerShell 7 as the account first, so the rerun leaves it alone, or change the plan.
> 13. **The Unix setup starts over in a clean environment, and the launchers name full paths (A-22, round 9 review).**
>     The setup runs again under `/bin/bash -p` with only the variables it needs and a fixed `PATH`, and stops if a
>     tool that it runs as root is not in a system folder. `Setup Mac.command` and `Setup Linux.desktop` change to
>     `/usr/bin/sudo /bin/bash -p`, which adds two changed kit files to the scope. A typed `sudo bash setup-unix.sh`
>     still works, but then the bash that starts it comes from the account's `PATH`, so the README gives the full form.
>
> **Risks that stay after this plan, stated so they aren't assumed away:**
>
> - With D-1 ruled A, the helper's `install` verb installs any package from the member's configured
>   repositories. A package's install scripts run as root, so the hub can still get root through a package it chooses
>   from those repositories. It cannot install a local file or a URL, and no caller variable such as `APT_CONFIG`
>   reaches the package tool. A sudoers policy that a later tool changes after setup can undo the clean environment;
>   the setup checks the policy only when it runs (A-18).
> - The Windows account stays a full administrator over SSH. Constrained Windows admin (JEA) is out of scope.
> - With D-2 ruled A, each vendor's installer script runs before any check. The check covers the binary it
>   installed. The image check accepts only a good signature from the pinned key and fails closed on any other
>   status (WP-U6).
> - macOS has no firewall change. `from=` on the hub's key is its only network limit.
> - `sshd -T -C` shows the settings for the member's account at the member's own address. A `Match` block for the
>   hub's own name or address is not evaluated by the setup, so the hub's probe (AC-18) catches it. The probe tests
>   only the account in the record.
> - The Key-auth check cannot test `from=`. It does not know the hub's address, because the drive holds no hosts. A hub
>   on another routed subnet is refused by `from=` while the check passes. Password sign-in is off by then, so the way
>   back is the member's own screen. The setup prints the subnets so that the human can compare them first.
> - The `firewalld` pass changes runtime and permanent state with no reload, so it keeps the human's runtime-only
>   changes. A later zone move is not watched after setup; the live check reads the zones when it runs. Policy objects
>   and direct rules are not read, so one that drops the hub's packets shows only as a failed `import` connection.
> - The guard walks process parents. A tool that hides them can get past it.
> - The drive is not signed. A record that another machine wrote or changed is caught only when the human compares its
>   fingerprints, as the setup and `import` print them; a first `import` pins what the drive holds (WP-U5b).
> - The drive also carries the code that runs as administrator or root: the setup scripts, the launchers and the
>   helper. A machine that the drive visits can change that code for the next member and still print the expected
>   fingerprints, and the kit does not check it. So one drive serves several members only when every member is
>   equally trusted. For a member that is not, the human imports the records so far on the hub and runs `prepare`
>   onto a new drive, or one freshly formatted on the hub, so that only the hub has written it (WP-U7). A `prepare`
>   into a folder that already holds files is not a reset: it rewrites the kit's own files and keeps every other
>   file, and the Windows launcher can run a planted `powershell.cmd` from the drive in place of Windows PowerShell.
> - Rows 13 and 14 prove that `pwsh` 7 is installed, not that a Unix member process finds it on its own `PATH`. That
>   lookup is a prerequisite of the later Unix member plan (WP-U6p, Out of Scope).
>
> **Existing tests this plan changes, by name:**
>
> - `scripts/tests/test_fleet_agent.py::test_ac32_forbidden_commands_are_unchanged` (`:1912-1913`): its expected set
>   loses `"agy"`. The rest of the set stays.
> - `scripts/tests/test_fleet_run.py:80-85` is not edited. It is parametrized over `sorted(FORBIDDEN_COMMANDS)`, so it
>   runs four fewer cases.

---

## Proposed Changes

### Named definitions

- **Kit:** the files under `.agent/fleet/usb/` and `.agent/fleet/install-usb/`.
- **Drive folder:** the folder that `fleet_usb.py prepare` writes on the drive, such as `E:\fleet-usb`.
- **Helper:** `/opt/fleet-admin/fleet-admin`, installed from the new tracked file `.agent/fleet/usb/fleet-admin.sh`.
  The file and its folder are owned by owner 0 and group 0, with mode 0755. This is the one place that states them.
  Its folder must pass the Parent walk, because an account that can write a parent can rename the folder and put a
  script at the sudo path. `install_helper` and the helper's self-check both run the walk. A failed walk stops the
  setup with the path named, and the helper exits 3.
  The first line is `#!/bin/bash -p`, so bash reads no `BASH_ENV` or `ENV` file, imports no function, and ignores
  `SHELLOPTS`, `BASHOPTS`, `CDPATH` and `GLOBIGNORE`. The helper starts each tool as
  `/usr/bin/env -i PATH=<tool path> LC_ALL=C <absolute tool> <fixed argv>`, and adds `DEBIAN_FRONTEND=noninteractive`
  for `apt-get`. It finds the absolute tool with `command -v` under the tool path. `main` sets the tool path to the
  Root tool path; the tests set it to the stub folder. No other variable reaches a tool.
- **Parent walk:** the check that a folder is safe for root to write in or run from. The folder and each parent
  folder up to `/`, on the physical path (`cd -P`, `pwd -P`), must have owner 0 and no group or other write bit. The
  Mode reader gives the owner and mode. A sticky bit does not excuse a write bit, so a `/tmp`-style folder fails. A
  failed walk names the path. The Helper and the PowerShell step use it. This is the one place that states it.
- **Mode reader:** one bash function that prints a path's owner, group and mode. It picks the form by `uname -s`:
  `stat -c '%u %g %a'` on Linux and `stat -f '%u %g %Lp'` on macOS, whose BSD `stat` has no `-c`. The Helper, the
  Parent walk, the Drop-in snapshot and the Key-auth check all use it.
- **Root tool path:** `/usr/sbin:/usr/bin:/sbin:/bin`. This is the one place that states the folder list. The Helper's
  `main`, the Sudoers file's `secure_path` and the setup's clean start use it. Only root can write these folders on a
  supported member, so the setup does not walk them: an account that can write `/usr/bin` already has root.
  The setup runs as root, but its caller's environment comes through `sudo` (review F-037). So the first statement of
  `setup-unix.sh` `main`, which the Load guard calls only when the file runs, is the **clean start**:
  - With `FLEET_USB_CLEAN` not set to 1, it runs `exec /usr/bin/env -i FLEET_USB_CLEAN=1 PATH=<Root tool path>
    LC_ALL=C TERM=dumb SUDO_USER=<the caller's value> /bin/bash -p "$0" "$@"`. No other variable passes. `HOME` is
    left out, because macOS sudo keeps the account's `HOME` and `curl` reads files there. `SUDO_USER` is checked
    next by `setup-unix.sh:16-19`. Under `-p`, bash reads no `BASH_ENV` or `ENV` file, imports no function, and
    ignores `SHELLOPTS`, `BASHOPTS`, `CDPATH` and `GLOBIGNORE`.
  - With the marker set, it continues only if `$-` holds `p` and each name from `compgen -e` is one that it passed
    or one that bash adds (`PWD`, `OLDPWD`, `SHLVL`), or, only when bash's own `OSTYPE` is `msys` or `cygwin` (Git
    bash, where the tests run), one that its runtime adds (`MSYSTEM`, `SYSTEMROOT`, `WINDIR`). Any other case stops
    with "the clean start failed", so a forged marker gets a stop, not a skip.
  - It then sets `IFS` to space, tab and newline, exports `PATH` as the Root tool path, and runs `hash -r` and
    `unalias -a`.

  Then the **Root tool check** `check_root_tools <Root tool path> <name>...` runs, before any other external command,
  `uname` and `stat` included; the only earlier one is the absolute `/usr/bin/env`. It reads the constant list
  `root_tools` in `setup-unix.sh`, which names each external command that the setup runs as root, and holds at least
  `id`, `uname`, `dirname`, `stat`, `install`, `tar`, `sudo`, `curl`, `sha256sum`, `shasum`, `chown`, `chmod`, `mv`,
  `ln`, `rm`, `mkdir`, `mktemp`, `visudo` and `sshd`. This is the one place that states that floor. For each name,
  `command -v` must print `<folder>/<name>` for a folder of the Root tool path. It prints `name=path`. An absent name
  passes here; WP-U5 step 3 runs the check again after it installs a package. A function, an alias, a builtin or any
  other path stops the setup before any write, with the name and its lookup named (stop condition 6). The clean start
  is the guard; the check proves that it held, and it catches a later function in the file that takes a tool's name.
  Commands that run as the account (`sudo -u "$user" -i`) keep the account's own lookup.

  The **launch form** is `/usr/bin/sudo /bin/bash -p <setup-unix.sh>`. `Setup Mac.command:5`, `Setup Linux.desktop:7`,
  the header comment at `setup-unix.sh:6-7` and the run lines at `usb/README.md:57-58` use it, with no bare `sudo bash`. With
  no `secure_path` in the sudoers policy, sudo finds a bare `bash` on the caller's `PATH`, so an account-owned bash
  such as Homebrew's `/opt/homebrew/bin/bash` would run as root before the clean start; and a bare `sudo` on the
  account's `PATH` can be a fake that reads the password (sudoers(5), `secure_path`).
- **Sudoers file:** `/etc/sudoers.d/fleet-agent`, mode 0440, holding exactly two lines:
  `<user> ALL=(root) NOPASSWD: NOSETENV: /opt/fleet-admin/fleet-admin` and
  `Defaults!/opt/fleet-admin/fleet-admin env_reset, !env_keep, !env_check, secure_path="/usr/sbin:/usr/bin:/sbin:/bin"`,
  whose `secure_path` is the Root tool path.
  sudo applies a rule's tags after every `Defaults` line, so `NOSETENV:` keeps `setenv` off whatever a `Defaults` line
  sets, and sudo refuses `-E` and any `VAR=value` (sudo 1.9.15p5 sudoers.c, lookup.c, env.c). The `Defaults!` line
  clears the kept and checked lists and replaces `PATH`. `visudo -cf` checks both lines before the file is installed.
- **Drop-in:** `/etc/ssh/sshd_config.d/01-fleet-usb.conf`, holding `PasswordAuthentication no`,
  `KbdInteractiveAuthentication no` and `ChallengeResponseAuthentication no`. sshd keeps the first value it reads, and
  `01-` sorts before `50-cloud-init.conf` on Ubuntu and `100-macos.conf` on macOS. Before it writes the drop-in, the
  setup saves a snapshot: the old drop-in's bytes, owner and mode (from the Mode reader), or the fact that there was
  none. A failure before the reload restores the snapshot (the old file with its owner and mode, or no file), runs
  `sshd -t` on the restored state, and stops with no reload. A failed reload does the same restore, reloads once more
  on the restored state, and stops. After a reload passes, a later failure keeps the drop-in, because the running sshd
  already uses it, so the file and the running sshd agree. The setup then stops with the step named, and the record
  stays retired. This is the one place that states the Unix password-off sequence.
- **Marked block:** the lines from `# BEGIN fleet-usb` to `# END fleet-usb` at the top of
  `%ProgramData%\ssh\sshd_config`, holding `PasswordAuthentication no` and `KbdInteractiveAuthentication no`. A failure
  before the restart writes the file's old bytes back. A failed `Restart-Service` writes them back, restarts once more
  and stops. After a restart passes, a later failure keeps the block (WP-U5w).
- **Key-auth check:** a check that the hub's key can sign in, run before password sign-in is turned off. For each member
  address, the setup runs `sshd -T -C user=<user>,host=<member address>,addr=<member address>,laddr=<member address>,lport=22`
  (on Windows `sshd.exe -T -C` with the same spec) on the live config. It compares whole tokens, never substrings. It
  requires all of these:
  - `pubkeyauthentication yes`.
  - `authorizedkeysfile`, split on whitespace, with a token that names a file the setup wrote: `.ssh/authorized_keys` or
    `%h/.ssh/authorized_keys` for the account's home or, for a Windows administrator,
    `__PROGRAMDATA__/ssh/administrators_authorized_keys` or the same path under `%ProgramData%`, compared with `\` as
    `/` and without case. The hub has no `sshd.exe` to show which form Windows prints, so both pass, and row 12 captures
    the real text. A value of `none` fails.
  - `authenticationmethods any`, or one listed method set that is exactly `publickey`.
  - `ssh-ed25519` as one comma-separated token of `pubkeyacceptedalgorithms` (`pubkeyacceptedkeytypes` before OpenSSH
    8.5). A list that holds only `ssh-ed25519-cert-v01@openssh.com` fails.
  - **Account filters.** No `denyusers` entry matches the account, and no `denygroups` entry names one of its groups
    (`id -Gn`). If any `allowusers` line exists, one entry matches the account. If any `allowgroups` line exists, one
    entry names one of its groups. An `allowusers` or `denyusers` entry in `user@host` form whose user part matches
    fails closed, because the setup cannot prove the host part. On Windows, an `allowgroups` or `denygroups` line, or a
    user entry that holds `\` or `@`, fails closed, because Windows group and domain names need a lookup.
  - **Strict modes (Unix).** When the output shows `strictmodes yes`, the home folder, `.ssh` and `authorized_keys` are
    each owned by the account or by owner 0, with no group or other write bit. This is upstream OpenSSH's `safe_path()`
    rule, minus symlinks: upstream checks a link's target, and the kit stops on any link at step 1 (WP-U5). A distro
    patch may relax the rest, so the check can stop a setup that would have worked; the human then fixes the mode.

  A failed item stops the setup with the key, line or path named, before any change to the sshd config. The check has
  two limits. It cannot see a `Match` block for the hub's own name or address; the hub's probe (AC-18) covers that. It
  cannot test `from=`, because `sshd -T` does not read `authorized_keys` and the drive holds no hub address
  (`core/MANIFEST.md:40`). So the hub must sit on a member subnet. Unix setup prints those subnets for the human to
  compare. A hub outside them is refused by `from=`, and `import` reports the failed connection (AC-18).
- **Password-off check:** after the drop-in or the marked block is written, `sshd -t` passes (Unix), and
  `sshd -T -C` with each Key-auth check spec shows `passwordauthentication no` and
  `kbdinteractiveauthentication no`, and still passes the Key-auth check.
- **Record retire:** after the console guard and before any system change, each setup computes the member name as its
  record step does. If `members/<name>.json` exists on the drive and this machine has no host key file yet, or that
  record's `host_key` is not this machine's host key (`setup-unix.sh:134-136`, `setup-windows.ps1:103-106`), the setup
  stops with no change (name clash). It names the record and tells the human to rename this machine, or to delete the
  record if it is this machine's own from before a reinstall. Otherwise it renames `members/<name>.json` to
  `<name>.json.old`, over an older `.old` file, and retires, and prints, any other `members/*.json` whose `host_key`
  equals this machine's host key; that covers a machine renamed since its last setup. Only a record with this
  machine's own host key is retired. A clone that shares the key also retires its twin's record; the printed line
  names it, and the rename is reversible. A renamed machine with a new key leaves its old-name record, which `import`
  then reports as a failed connection (`fleet_usb.py:206-214`). The setup writes a new `<name>.json` only after every
  other step passes. `import` reads only `members/*.json` (`fleet_usb.py:177`), so it never reads a `.old` file.
- **Listener check:** it runs only when the setup itself turns the firewall on: right before `ufw --force enable` on
  an inactive `ufw`, and right before `systemctl enable --now firewalld` on a stopped `firewalld`. An active `ufw` and
  a running `firewalld` get no Listener check. Its parser, `parse_listeners`, reads `ss -ltnuH`: it parses the Netid
  column, removes any `%<interface>` from the address, and takes the port after the last colon. A line it cannot read
  stops the setup. `check_listeners` calls the parser, and any `tcp` or `udp` socket on an address other than loopback
  stops the setup, except a `tcp` listener on port 22. No other port is excepted: the kit does not prove which traffic
  a firewall keeps, so the mDNS socket of `avahi-daemon` on UDP 5353 and a DHCP client socket stop it too, as they do
  on a stock Ubuntu Desktop. The stop comes in step 7, before step 8, so the hub's key, the password change and the
  new record are not yet done; the kit's firewall rules are already in place, and a rerun finds them and adds nothing.
  The stop prints each socket's Netid, address and port, and the command that turns the firewall on: `sudo ufw enable`,
  or `sudo systemctl enable --now firewalld`. The human checks those services, runs that command at the screen and
  runs the setup again. The rerun finds the firewall active, so no Listener check runs. The live check (row 13) uses
  only `parse_listeners`, as a format check: every line parses and names its Netid and port. It makes no enable
  decision, so a listener on an active firewall, such as the mDNS and DHCP client sockets, does not fail it.
- **Firewalld rules:** the setup resolves zones at runtime, because NetworkManager binds a connection's zone at runtime
  and writes no permanent binding (firewalld, "Connections, Interfaces and Sources"). Each interface that carries a
  member subnet is field 2 of `ip -o -4 addr show scope global`. Its zone is what `firewall-cmd
  --get-zone-of-interface=<if>` prints with no `--permanent`, or `--get-default-zone` for an interface with none. These
  zones are the target zones. Before any firewall change, the setup reads `--zone=<zone> --list-sources` for each
  zone of `--get-zones`, at runtime and with `--permanent` when firewalld runs, or with `firewall-offline-cmd` when it is
  stopped. It also reads each target zone's target from each store on its own. The runtime target is the one line of
  `firewall-cmd --zone=<zone> --list-all` whose first word is `target:`, because `--get-target` works only with
  `--permanent` (`firewall-cmd.in`), and `--list-all` without `--permanent` prints the target of the zone as the daemon
  loaded it at its last start or reload. The permanent target is `firewall-cmd --permanent --zone=<zone> --get-target`.
  With the daemon stopped, it is `firewall-offline-cmd --zone=<zone> --get-target`, and there is no runtime target yet.
  A source in a zone that is not a target zone stops the setup with both named, at any priority, because firewalld can
  classify the hub's packets by source before interface ("Zone Priorities"). A target zone stops it too, with the zone
  and each target named, unless every target read for it is `default`. So the kit does not override a `DROP` or
  `%%REJECT%%` zone with an allow, does not leave an `ACCEPT` zone, which accepts all traffic, under a subnet rule that
  limits nothing, and does not act on a runtime target that differs from the permanent one, as a
  `--permanent --set-target` without `--reload` leaves it. A `--list-all` with no `target:` line, or with more than one,
  stops it. Only `default` passes, so the `REJECT` and `%%REJECT%%` spellings need no map. In each
  target zone Z, for each member subnet S, the setup adds
  `--zone=Z --add-rich-rule='rule family="ipv4" source address="S" port port="22" protocol="tcp" accept'` when
  `--query-rich-rule` lacks it. Then it runs `--zone=Z --remove-service=ssh` when `--query-service=ssh` shows the
  service. The running branch runs each of these changes twice, once at runtime and once with `--permanent`, each after
  its own query. It never runs `--reload`, because a reload drops the human's runtime-only changes, and it never runs
  `--runtime-to-permanent`, because that would save them. The stopped branch has no runtime bindings yet, so it takes
  the zones from `firewall-offline-cmd --get-zone-of-interface=<if>` or `--get-default-zone`, and runs the same rich-rule
  calls with `firewall-offline-cmd`, which changes only the permanent config and takes no `--permanent`. It removes the
  service with `--zone=Z --remove-service-from-zone=ssh`, because the `--remove-service` of `firewall-offline-cmd` is a
  lokkit option that acts on the default zone only. After the start, the setup resolves the runtime zones again. A zone
  that was not in the offline set joins the target zones and gets the running-branch pass.
- **Firewalld checks:** after the rule pass or the start, the setup resolves each member interface's runtime zone again.
  A zone that is not a target zone stops the setup with the interface and zone named. For each target zone Z and subnet
  S, `firewall-cmd --zone=Z --query-rich-rule=<rule>` exits 0 and `firewall-cmd --zone=Z --query-service=ssh` exits 1,
  both at runtime and with `--permanent`. Any other result stops the setup with the zone named. The source and target
  stops of Firewalld rules run again here, on the runtime zones, with each target read from both stores as above.
- **SSH rule report:** read only (A-4); the setup prints it, and the live check fails on it. It lists each rule that may
  let a packet reach port 22 and that the kit did not make, as `other SSH rule, not changed by the kit: <zone>: <rule>`.
  It never calls a Unix rule broader, because the kit does not compare source sets. An unreadable rule is listed too.
  - `firewalld`, in each zone of `--get-active-zones`: a `--list-ports` entry or range that covers `22/tcp`; a
    `--list-services` entry whose `--info-service` ports cover `22/tcp`; any other `--list-rich-rules` line whose action
    is `accept`, unless it names a port, service or protocol and each one leaves out `22/tcp` (a service by its
    `--info-service` ports); a zone whose runtime target (the `target:` line of `--list-all`) or permanent target
    (`--permanent --get-target`) is `ACCEPT`.
  - `ufw`: each other `ufw status` rule whose action is `ALLOW` or `LIMIT` (not `OUT`), unless its `To` field names only
    `udp` or only ports that leave out 22 (so a profile such as `OpenSSH` is listed); a `ufw status verbose` incoming
    default other than `deny` or `reject`.
  - Windows: the rules that `Find-BroaderSshRule` lists (WP-U4); its subnet test proves each one broader.
- **Member subnets:** the IPv4 networks of the member's own addresses, in CIDR form. Loopback and link-local
  (RFC 3927) addresses are left out. So are interfaces named `docker*`, `br-*`, `virbr*`, `veth*`, `lxc*`, `lxd*` and
  `podman*`, and on macOS `bridge*` and `vmnet*`, because those networks hold local containers and guests, and the same
  rule that `setup-windows.ps1:109` applies to `vEthernet` keeps them out. An overlay VPN interface stays, because the
  hub may reach the member through it. The record's `addresses` use the same left-out rule, so `from=`, the firewall and
  the record agree. No subnet left stops the setup. Linux reads `ip -o -4 addr show scope global`. macOS reads
  `ifconfig`, whose netmask is hex. The math is pure bash 3.2 and replaces the `python3` call at `setup-unix.sh:57`.
- **Load guard:** the last line of a bash file. It returns when the file is sourced and calls `main` when the file
  is run:

  ```bash
  [ "$BASH_SOURCE" = "$0" ] || return 0; main "$@"
  ```

  Only `main` names `/etc`, `/opt` or the drive folder. Every other function takes its paths as arguments.
- **Git bash:** the `bash.exe` that the Git bash locator returns. The locator starts from the folder that
  `git --exec-path` prints and from `shutil.which("git")`. From each, it walks up to the first folder that holds
  `git-cmd.exe` or `usr/bin/bash.exe`; that folder is the Git root. This walk is the Git root rule, and this is the one
  place that states it. It returns the first of `<root>/bin/bash.exe` and
  `<root>/usr/bin/bash.exe` that exists. It refuses a path under `%SystemRoot%` or under
  `%LOCALAPPDATA%\Microsoft\WindowsApps`, where WSL's `bash.exe` lives, and it holds no fixed install path. So it works
  when `git.exe` is in `cmd/`, `mingw64/bin/` or `ucrt64/bin/`. Tests never use WSL's `bash`. A missing Git bash fails
  the tests on Windows, with the folders tried. The kit cannot call a Python test helper, so `Find-GitRoot` in
  `write-installer-usb.ps1` applies the same rule in PowerShell, and both are tested over the same synthetic layouts
  (AC-19).
- **Stub folder:** a temp folder put at the front of `PATH`, with fake `visudo`, `install`, `chown`, `apt-get`, `dnf`,
  `systemctl`, `ufw`, `firewall-cmd`, `firewall-offline-cmd`, `ss`, `sshd`, `sudo`, `ip`, `ifconfig`, `ps`, `stat`,
  `uname`, `id` and `shutdown`. The rest of `PATH` stays. Each stub starts with `#!/bin/bash` and logs with bash builtins
  only (`export -p` for its environment), to a log path fixed in the stub's text, because the helper starts tools with an
  empty environment and only the tool path. Each stub writes its argv to that log, and the tool stubs that the
  helper runs also log their environment. Each prints the reply that the test sets. The `stat` stub answers both Mode
  reader forms, and the `uname` stub picks one. In its stopped mode, the
  `firewall-cmd` stub exits 252 with `NOT_RUNNING` until the log holds `systemctl enable --now firewalld`.
- **Admin check:** the command `fleet_usb.py` runs on a member after it connects. On macOS and Linux it is:

  ```bash
  if sudo -n true 2>/dev/null; then echo full=True; else echo full=False; fi
  if sudo -n /opt/fleet-admin/fleet-admin check >/dev/null 2>&1; then echo helper=True; else echo helper=False; fi
  ```

  Windows keeps today's `IsInRole` check (`fleet_usb.py:40-45`).
- **Outcomes:** what the admin check reports, and whether `import` passes:

  | Report | Meaning | import |
  |---|---|---|
  | `full access` | Windows administrator | pass |
  | `admin helper` | `helper=True`, `full=False` | pass |
  | `admin helper, and another rule gives full sudo without a password; remove the other rule` | both true | fail |
  | `full sudo without a password; rerun the kit` | `full=True`, `helper=False` | fail |
  | `connected, without admin access` | both false | fail |

- **Probe:** a hub-side `ssh` call with `BatchMode=yes` and `PubkeyAuthentication`, `PasswordAuthentication`,
  `KbdInteractiveAuthentication`, `GSSAPIAuthentication` and `HostbasedAuthentication` all `no`. The server then
  answers `Permission denied (` with the list of methods that can continue (RFC 4252 §5.1 and §5.2).
- **Console guard:** a check at the start of each setup that refuses to run when a process parent is an SSH server.
  Unix walks `ps` parents and refuses a name that starts with `sshd`, which also covers `sshd-session` (OpenSSH 9.8).
  Windows walks `Win32_Process.ParentProcessId` and refuses `sshd*.exe` or `wsmprovhost.exe`. Each walk stops after 32
  steps or at a repeated process id, and then passes (A-5). This is the one place that states the bound.
- **PowerShell pin:** the file `pwsh-pin.txt` that `fleet_usb.py prepare` writes in the drive folder: one line
  `<version> <platform> <sha256>` for each of `linux-x64`, `linux-arm64`, `osx-x64` and `osx-arm64`, for the release
  that the selection predicate of A-21 picks and A-20 checks (WP-U6p).
- **PowerShell step:** `install_pwsh` in `setup-unix.sh`, which runs a `pwsh` that it finds only as the account and
  leaves one of 7 or later alone. Otherwise it installs the pinned build under a versioned root-owned folder, after
  the Parent walk and its hash and version checks, and links `/usr/local/bin/pwsh` to it (A-19, WP-U6p).

### WP-U1: Remove the retired CLI's name

`CAPABILITY_TOOLS` (`fleet.py:69`) and `FORBIDDEN_COMMANDS` (`fleet.py:70-72`) both list `agy`. `validate_manifest`
reads them at `:252` (manifest `requires`) and `:265-267` (a command's forbidden first word), `validate_hello` at
`:493`, and `capability_report` at `:1480-1482`, which builds the report a member sends. The change removes `agy`
from both and keeps every other member in its order, so a new member stops reporting the key.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `hello` capabilities | `validate_hello` (`fleet.py:487-497`) | Keys from `CAPABILITY_TOOLS`; values a string or null | An unknown key is refused with `bad_field:capabilities` |
| `.agent/fleet.json` `requires` and command argv | `validate_manifest` (`fleet.py:237-268`) | `requires` from `CAPABILITY_TOOLS`; first word not in `FORBIDDEN_COMMANDS` | Unchanged |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-1 | unit | `CAPABILITY_TOOLS` and `FORBIDDEN_COMMANDS` hold no `agy`, and every other member stays in its order. `test_ac32_forbidden_commands_are_unchanged` asserts the new set. | Human-approved (2026-11-07 direction, finding 5); Local Canon (the source repo's `tests/tooling/test_retired_surfaces_absent.py` refuses the word) | A `hello` whose capabilities hold the `agy` key is refused with `bad_field:capabilities` |
| AC-2 | unit | A word scan over `core/`, `.agent/` without `.agent/context/`, the root `*.md` files and `scripts/tests/` finds no `agy` word. Text files only. The test builds its needle from two parts, so the test file holds no hit. | Local Canon (the source repo's framework scan group: dirs `core` and `.agent`, glob `*.md`, `.agent/context/` left out) | A temp file holding the word fails the scan; a file holding `Magyar` passes |
| AC-3 | integration | **Live, human row 2a.** After the hub restarts and each member updates, `check_live.py hello` reads `fleet.py status` (`cmd_status`, `fleet.py:1300-1303`): every member is online and reports no `agy` key. | Local Canon (`bootstrap.md` §Update, `:96-101`) | `--selftest` feeds a member that is offline and one that reports the key, and each must fail |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Which constants lose the name | Local Canon | A-1 |
| Update order across hub and members | Local Canon | A-2, `bootstrap.md:96-101` |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/fleet.py` | modify | `agy` out of both constants |
| `scripts/tests/test_fleet_agent.py` | modify | The expected set in `test_ac32_forbidden_commands_are_unchanged` |
| `scripts/tests/test_fleet_usb.py` | new | AC-1, AC-2 |

### WP-U2: Testable kit scripts

Today no kit file can be loaded by a test without running it. `setup-unix.sh` runs top to bottom.
`setup-windows.ps1:7` holds `#Requires -RunAsAdministrator`, which refuses a dot-source in a non-elevated Pester run.
`write-installer-usb.ps1:8` computes the `$Log` default from a mandatory `-Iso`. This package restructures each file
without changing what it does, adds the static checks the review asked for, and pins `fleet_usb.py`'s behavior before
later rows change it.

- `setup-unix.sh`: functions with explicit path arguments, then `main`, then the load guard. `set -euo pipefail` stays
  at the top. The drive folder is computed in `main` from `$BASH_SOURCE`.
- `setup-windows.ps1`: `param([switch]$LibraryOnly)`, the body in `Invoke-Setup`, and a runtime `IsInRole` check at the
  start of `Invoke-Setup` in place of `#Requires`. With `-LibraryOnly` the file defines its functions and returns, as
  `setup-member.ps1:6` and `:276` do.
- `write-installer-usb.ps1`: `-LibraryOnly` in its own parameter set, so `-Iso` stays mandatory in the other, and the
  `$Log` default moves into the body.
- `.gitattributes`: `*.command text eol=lf` and `*.desktop text eol=lf`. `prepare` already writes LF launchers to the
  drive (`fleet_usb.py:75-81`), so this guards the checkout only.
- The AC-4 and AC-5 bash checks run over each `*.sh` file in `.agent/fleet/usb/`, so `fleet-admin.sh` joins them
  when WP-U3 adds it.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `setup-windows.ps1` parameters | PowerShell `param` block | `-LibraryOnly` switch only | PowerShell binding error |
| `write-installer-usb.ps1` parameters | PowerShell `param` block | Set `Write`: `-Iso` (mandatory), `-Serial`, `-VerifyOnly`, `-Log`, `-KeyFile`. Set `Library`: `-LibraryOnly` | PowerShell binding error |
| `setup-unix.sh` arguments | `main` | None | Ignored, as today |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-4 | unit | Loading a kit file has no side effect. Sourcing `setup-unix.sh` and `fleet-admin.sh` in Git bash with the stub folder leaves the stub log empty and the temp root unchanged. Dot-sourcing `setup-windows.ps1 -LibraryOnly` and `write-installer-usb.ps1 -LibraryOnly` calls no state-changing cmdlet (Pester mocks of `Add-WindowsCapability`, `Start-Service`, `Set-Service`, `New-NetFirewallRule`, `Start-Transcript`, `Get-Disk` and `Clear-Disk` called zero times). `fleet_usb.py` imports only the standard library and parses at `feature_version=(3, 11)`. | Human-approved (finding 7); Research-backed (https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_requires) | A copy of `setup-unix.sh` with a top-level `touch` outside `main` fails; a copy of `fleet_usb.py` with `import requests` fails |
| AC-5 | unit | `setup-unix.sh` and `fleet-admin.sh` keep to bash 3.2: no associative array, `mapfile`, `readarray`, case-changing expansion, pipe-ampersand, `coproc` or `-v` test, and `bash -n` passes. `.gitattributes` holds the two new LF lines, and `prepare` writes `.sh`, `.command` and `.desktop` files with LF only. | Local Canon (`setup-unix.sh:8`, "It keeps to bash 3.2, which macOS ships"; `.gitattributes:16`) | A copy with `declare -A` fails; a CRLF `.command` source still lands LF on the drive |
| AC-6 | unit | Each kit `.ps1` file is ASCII or starts with a UTF-8 BOM. `setup-windows.ps1` parses with zero errors under Windows PowerShell 5.1, which `Setup Windows.cmd` starts. Skipped with a reason off Windows. | Research-backed (https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_character_encoding) | A copy using the `??` operator fails the 5.1 parse; a BOM-less copy with a non-ASCII character fails |
| AC-7 | unit | The kit holds no IPv4 literal except the loopback address in `setup-unix.sh`'s port check, no literal home-folder path with a fixed user name, and no email address. | Local Canon (commit `6e679e9` removed such names; `MANIFEST.md:40`, "Holds no hosts or credentials") | Copies with an RFC 5737 documentation address, a fixed-name home path, or an email address each fail; the clean kit passes |
| AC-12 | unit | Characterization of `fleet_usb.py`: `prepare` makes the key once and copies `MEMBER_FILES` with the line-end rule; `read_record` accepts a valid record; `render_config` gives today's text for a sample record; `include_config` adds its line once. A guard test: green on its first run, by design (A-13). | Local Canon (`fleet_usb.py:66-162`) | Records with a bad name, user or host key are each refused; a second `include_config` adds nothing |
| AC-28 | unit | The Git bash locator (Named definitions) finds the Git root and its bash on each Git for Windows layout, and never returns a WSL bash. On this hub it returns an existing `bash.exe` under the Git root. | Local Canon (the hub's Git for Windows install: `git.exe` in `cmd/` and `ucrt64/bin/`, `bash.exe` in `bin/` and `usr/bin/`, no `mingw64/`); Research-backed (https://git-scm.com/docs/git); Human-approved (review F-009) | Synthetic temp roots with `git.exe` in `cmd/`, in `mingw64/bin/` and in `ucrt64/bin/` each give `<root>/bin/bash.exe`; a root with only `usr/bin/bash.exe` gives that path; a root with no bash fails with the folders it tried; a `which` result under `%SystemRoot%` or under `WindowsApps` is refused; the locator source holds no `C:/Users` or `Program Files` literal |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| How tests run bash on the hub | Local Canon | A-14: Git bash from the Git bash locator, never WSL |
| `-LibraryOnly` form | Local Canon | `setup-member.ps1:6,276`; `SetupMember.Tests.ps1:17` |
| No shellcheck or PSScriptAnalyzer | Local Canon | Out of Scope: neither is installed on the hub |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/usb/setup-unix.sh` | modify | Functions, `main`, load guard |
| `.agent/fleet/usb/setup-windows.ps1` | modify | `-LibraryOnly`, `Invoke-Setup`, runtime admin check |
| `.agent/fleet/install-usb/write-installer-usb.ps1` | modify | `-LibraryOnly` parameter set; `$Log` default in the body |
| `.gitattributes` | modify | Two LF lines |
| `scripts/tests/test_fleet_usb.py` | modify | The Git bash locator, bash-stub fixtures; AC-4 to AC-7, AC-12, AC-28 |
| `scripts/tests/SetupWindowsUsb.Tests.ps1` | new | AC-4 cases |
| `scripts/tests/WriteInstallerUsb.Tests.ps1` | new | AC-4 cases |

### WP-U3: The admin helper and its sudoers rule

This package is written with D-1 ruled A (row 3a checks the typed ruling). Another ruling sends it back to planning.
Under A, the hub gets root on a macOS or Linux member only through the helper's fixed verbs, in a clean environment.
The verbs cover what the kit's docs ask the hub to do after setup (`install-usb/README.md:116-125`), plus a read-only
status.

| Verb | System | What it runs |
|---|---|---|
| `check` | both | Prints `fleet-admin ok` |
| `status` | both | Read-only: the firewall tool and its state, the SSH rules, on `firewalld` each member interface's runtime zone with the kit's rule for each subnet, each zone's sources and each target zone's runtime and permanent target, the SSH rule report, and the `passwordauthentication` and `kbdinteractiveauthentication` lines of `sshd -T` |
| `install <pkg>` | Linux | `apt-get update` then `apt-get install -y <pkg>`, or `dnf install -y <pkg>`, with fixed argv |
| `no-sleep` | Linux | `systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target` |
| `lid-ignore` | Linux | Writes `/etc/systemd/logind.conf.d/fleet-lid.conf` with `HandleLidSwitch`, `HandleLidSwitchExternalPower` and `HandleLidSwitchDocked` set to `ignore`; it takes effect at the next boot |
| `boot-text`, `boot-desktop` | Linux | `systemctl set-default multi-user.target`, or `graphical.target` |
| `reboot` | both | `shutdown -r now` |

A package name must start and end with a lowercase letter or digit, and hold only lowercase letters, digits, `.`,
`+` and `-` between them. So it cannot be an option, a path, a URL, a version pin (`=`), a group (`@`), or a name with
a trailing `-`, which `apt-get install` reads as "remove". A name ending in `.deb` or `.rpm` is refused, because both
tools read it as a local file. A bad verb or argument exits 2. The helper refuses to run (exit 3) when it or its
folder does not have the owner and mode in the Helper definition, or when its folder fails the Parent walk.

The environment has three layers, each in the Named definitions. The Sudoers file's `NOSETENV:` tag makes sudo refuse
`-E` and any `VAR=value`, and its `Defaults!` line makes sudo drop every caller variable and set a fixed `PATH`, so no
`LD_PRELOAD` reaches the helper's interpreter. The helper's `#!/bin/bash -p` line makes bash skip `BASH_ENV` and
`ENV` and import no function. Each tool runs under `env -i` with a fixed `PATH`, `LC_ALL=C` and, for `apt-get`,
`DEBIAN_FRONTEND=noninteractive`, by its absolute path. So `APT_CONFIG`, `LD_PRELOAD`, `BASH_ENV` or a `PATH` from
the caller never reaches `apt-get`, `dnf`, `systemctl` or `shutdown`. Before and after it writes the sudoers file, the
setup runs the sudoers policy check, and then the `LD_PRELOAD=` probe (A-18).

`fleet_usb.py` adds `fleet-admin.sh` to `MEMBER_FILES`, so `prepare` copies it to the drive with LF line ends, and
the admin check and outcomes replace today's `sudo -n true` check (`fleet_usb.py:40-45`, `:165-173`). `import`
passes on `full access` or `admin helper`.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| Helper argv | `fleet-admin.sh` `main` | One verb from the table; `install` takes exactly one package name as above; other verbs take none | Exit 2, nothing run |
| Sudoers file | `install_sudoers` in `setup-unix.sh` | Exactly the two lines of the Sudoers file definition; user name from `setup-unix.sh:18-19`; mode 0440; `visudo -cf` passes first | An old file is replaced whole |
| `LC_ALL=C sudo -l -U <user>` output, captured | `check_sudo_policy` in `setup-unix.sh` | The three sections that `display.c` prints, read per A-18 | A-18: a line it lists, or a probe that sudo does not refuse, stops the setup with no change; on the second read and the probe it also removes the file that `install_sudoers` wrote; the kit's own `Defaults!` line, compared token by token with double quotes and backslashes removed, is ignored |
| Helper environment | `fleet-admin.sh`, and the sudoers `NOSETENV:` tag and `Defaults!` line | Only the variables of the Helper definition reach a tool | All other variables dropped |
| Admin check output | `fleet_usb.py` | Exactly the lines `full=True` or `full=False`, and `helper=True` or `helper=False` | Any other output is `connected, without admin access` |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-8 | unit | No file under `.agent/fleet/` grants `NOPASSWD` for `ALL` (regex `NOPASSWD:\s*ALL`). | Human-approved (finding 1) | A temp copy of the kit with today's line fails |
| AC-9 | integration | `install_sudoers <user> <dir> <helper>` writes the two lines of the Sudoers file definition after `visudo -cf` passes on a temp file, with the mode in that definition, and replaces an old file that holds the `ALL` line. `install_helper` installs the helper with the owner and modes in the Helper definition, after the Parent walk passes. | Research-backed (https://www.sudo.ws/docs/man/sudoers.man/, https://www.sudo.ws/docs/man/visudo.man/); cases from the advisory read (N8, N9) | A failing `visudo` stub leaves the old file and stops the setup; a user name with a space is refused; a candidate without the `Defaults!` line or without `NOSETENV:` fails the test; a stub `stat` that reports `/opt` with a user owner, and one that reports `/opt` with mode 0775, each stop the setup with the path named before `install` is called; a `uname` stub of `Linux` makes the Mode reader call `stat -c` and one of `Darwin` makes it call `stat -f` |
| AC-10 | unit | Each verb runs its fixed argv on the stubs. | Research-backed (https://gtfobins.github.io/gtfobins/apt-get/, https://gtfobins.github.io/gtfobins/dnf/) | `install` with `-o`, `x.deb`, `x.rpm`, `../x`, `foo-`, `foo=1`, `@grp`, a URL, no name or two names exits 2 with no `apt-get` or `dnf` call; an unknown verb exits 2; a stub `stat` that reports a user owner or mode 0775 on the helper, on its folder, or on a parent such as `/opt` exits 3 with no tool call |
| AC-11 | unit | The admin check maps its two lines to the outcomes in the Named definitions, and `import` passes only on `full access` or `admin helper`. | Human-approved (finding 1); Local Canon (`fleet_usb.py:213`) | Each failing outcome makes `import` count a failure and exit non-zero; unknown output reads as `connected, without admin access` |
| AC-26 | unit | No caller variable reaches a tool that the helper runs. The helper's first line is `#!/bin/bash -p`, each tool call is `/usr/bin/env -i` with the Helper definition's variables and an absolute path, and the sudoers check of A-18 runs before the sudoers file is written and again right after it, followed by the `LD_PRELOAD=` probe. A static test reads the helper's `main` and finds the Root tool path (Named definitions) as its tool path. The A-18 parser passes its stock samples, and rows 13 and 14 feed each member's real `LC_ALL=C sudo -n -l` output through it, because `sudo -l -U` needs root and the hub's account does not hold it. | Research-backed (https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudoers.man.in, https://raw.githubusercontent.com/sudo-project/sudo/main/plugins/sudoers/display.c, https://raw.githubusercontent.com/sudo-project/sudo/main/plugins/sudoers/fmtsudoers.c, https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/sudoers.c, https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/lookup.c, https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/env.c, https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/gram.y, https://man7.org/linux/man-pages/man8/ld.so.8.html, https://manpages.debian.org/bookworm/apt/apt.conf.5.en.html, https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html); Human-approved (review F-001); Local Canon (the names and the fatal error, measured under the hub's Git bash); cases from the advisory read (N2, N11) | With `APT_CONFIG`, `BASH_ENV`, `LD_PRELOAD` and a stub-first `PATH` set in the caller, `install curl` makes a stub `apt-get` log an environment that holds none of them and whose `PATH` equals the tool path the test set. That log holds only `PATH`, `LC_ALL` and `DEBIAN_FRONTEND`, the `PWD`, `OLDPWD` and `SHLVL` that the stub's own bash sets and, only under Git bash, the `MSYSTEM`, `SYSTEMROOT` and `WINDIR` that its runtime adds. Under Git bash the test sets `LD_PRELOAD` to `/usr/bin/msys-2.0.dll`, because that runtime loads the value when a process starts, and a missing path ends bash with a fatal error before the helper runs. A copy of the helper without `-p` or without `env -i` fails. The stub `sudo` logs `LC_ALL=C` on each read. Each of these `sudo -l -U` samples stops the setup before `visudo` or `install` is called for the sudoers file, with the line named: output with no known header and no not-allowed line; a `SETENV:` tag on a command line; `setenv` in a Defaults line; `!env_reset`; `env_keep+=APT_CONFIG`; `env_keep+=LD_*`; `env_keep+=LD_BIND_NOW`; `env_keep+=L*`; `env_keep+=*`; `env_keep="HOME LD_PRELOAD"`; each of these in the Runas and Command-specific defaults section: `Defaults>root !env_reset`, a second `Defaults!/opt/fleet-admin/fleet-admin` line with other text, `Defaults!ALL setenv`, `Defaults!FLEET_CMDS setenv`, `Defaults!/opt/fleet-admin/* setenv` (a wildcard), `Defaults!/opt/fleet-admin/ setenv` (a directory), `Defaults!/usr/bin/other, /opt/fleet-admin/fleet-admin` with other text, and `Defaults!/usr/bin/other env_keep+=LD_PRELOAD`, which the kit does not prove unrelated. A stub `sudo` that prints the not-allowed line on the first read and `Defaults setenv` on the second stops the setup with the line named and no kit sudoers file left, and so does a second read whose last command entry is `(ALL) SETENV: ALL`, `(ALL) ALL`, or `(root) NOPASSWD: /opt/fleet-admin/fleet-admin` without `NOSETENV:`. A stub `sudo` whose `LD_PRELOAD=/nonexistent.so` probe runs the helper, with no not-allowed line, stops the setup and removes the kit's sudoers file. None of these stops the setup: a `NOSETENV:` tag on a command line; a rerun sample that lists the kit's own `Defaults!` line with its quotes and its rule as `sudoers_format_cmndspec()` in `fmtsudoers.c` prints it, `(root) NOSETENV: NOPASSWD: /opt/fleet-admin/fleet-admin`; the same entry with its tags in the sudoers file's order, `NOPASSWD: NOSETENV:`, because A-18 compares the tags as a set and not in their printed order; the same line as `fmtsudoers.c` prints it, `secure_path=/usr/sbin\:/usr/bin\:/sbin\:/bin`, with no quotes and each colon escaped; `env_keep-=LD_PRELOAD`; a probe that prints sudo's not-allowed line for `LD_PRELOAD`; `XENVIRONMENT` and `OLD_PWD` in `env_keep`, which only a substring match would hit; the line `User <user> is not allowed to run sudo on <host>.`; a stock Ubuntu sample; a stock Fedora sample with its `env_keep` names; a stock macOS sample with `HOME`, `MAIL` and `SSH_AUTH_SOCK` in `env_keep` |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Helper versus other designs | Human-approved | D-1 ruled A by the human on 2026-11-08; row 3a checks the typed ruling |
| Verb list | Local Canon | `install-usb/README.md:116-125` |
| Helper as a separate file | Local Canon | A-7 |
| The helper's environment | Research-backed | D-1 A brief: `NOSETENV:`, the `Defaults!` line, `bash -p`, `env -i` |
| A sudoers line that may undo the clean environment | Research-backed | A-18, with the `LD_PRELOAD=` probe |
| A helper parent folder that the account can write | Research-backed | The Helper definition and the Parent walk, with the sudoers(5) rule that a command is matched by its path |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/usb/fleet-admin.sh` | new | The helper, with `bash -p`, `env -i`, the Parent walk, `status` and its `report_ssh_rules`, and the load guard |
| `.agent/fleet/usb/setup-unix.sh` | modify | `check_sudo_policy`, `install_helper`, `install_sudoers` |
| `.agent/fleet/usb/fleet_usb.py` | modify | `MEMBER_FILES`, admin check, outcomes, import rule |
| `scripts/tests/test_fleet_usb.py` | modify | AC-8 to AC-11, AC-26 |

### WP-U4: The Windows firewall profile

The rule `OpenSSH-Server-In-TCP` keeps `-RemoteAddress LocalSubnet` and moves from `-Profile Any` to
`-Profile Domain, Private`. An existing rule on any other profile set is changed to that set. Before it changes
anything, the setup reads `Get-NetConnectionProfile` and joins it on `InterfaceIndex` to `Get-NetAdapter -Physical`.
A connected network counts only when its adapter is physical and its alias does not match `^vEthernet`, the same filter
as `setup-windows.ps1:109`. A Public network on a counted adapter stops the setup, which names the network and tells the
human to set it to Private in Settings. A setup with no Private or Domain network on a counted adapter also stops,
because the rule then reaches no network the hub can use. A Public network on any other adapter, such as a Hyper-V or
WSL switch or a host-only adapter, is printed by name and does not stop, because the rule keeps port 22 closed on it. A
guest machine's adapter is physical from the guest's view, and row 12 confirms that on its guest. The script never
changes a network's category (A-15).

This section is the one place that states the Windows profile policy. Other sections refer to it.

After the kit's own rule is in place, `Find-BroaderSshRule` reads the effective rules:
`Get-NetFirewallRule -PolicyStore ActiveStore -Direction Inbound -Action Allow -Enabled True`, and each rule's filters
with `-PolicyStore ActiveStore`. The default store is the persistent one and leaves out rules from Group Policy.

A rule covers SSH when all of these hold:

- Its application filter is `Any` or ends in `sshd.exe`.
- Its service filter is `Any` or `sshd`. A rule for another service does not reach SSH.
- Its protocol is `TCP`, `6` or `Any`.
- Its local port is `Any`, or a list entry that is `22` or a range `a-b` with `a <= 22 <= b`. The keywords `RPC`,
  `RPCEPMap`, `Teredo`, `IPHTTPSIn`, `IPHTTPSOut` and `PlayToDiscovery` do not cover 22.

A covering rule is broader when its profile includes `Public` or is `Any`, or when any remote entry is one of these: `Any`;
a keyword other than `LocalSubnet`, `LocalSubnet4` or `LocalSubnet6`; or an IPv4 address, `/bits` subnet, `/mask` subnet
or `a-b` range that is not inside one of the member's subnets, or an IPv6 entry. A narrow entry inside those subnets on
Domain and Private is not listed. The rule `OpenSSH-Server-In-TCP` is left out only when its active form matches this
section's policy, so a same-named Group Policy rule with a broader scope is listed.

`Get-NetFirewallProfile -PolicyStore ActiveStore` is read too. A profile whose `Enabled` is not `True` is reported the
same way, because the rule then limits nothing on that profile.

The setup prints each one by name and display name and changes nothing (A-4). The function and its subnet reader sit
between the marker lines `# BEGIN broader-rule-report` and `# END broader-rule-report` in `setup-windows.ps1`, and
return JSON. `check_live.py windows` reads that text, sends it with `powershell -NoProfile -EncodedCommand` (UTF-16LE,
base64) over the row's SSH call, and reads the JSON back, so the hub and the member run the same code. Any listed item
fails AC-23. `--selftest` covers the text extraction, the encode round trip and an encoded length under 8000
characters.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| Connection profiles | `Get-NetConnectionProfile` joined to `Get-NetAdapter -Physical` | `NetworkCategory` Private or DomainAuthenticated on every counted adapter; at least one such network | Public or none on a counted adapter stops the setup; Public on another adapter is printed |
| Inbound allow rules | `Find-BroaderSshRule` | From `ActiveStore`: `Name`, `DisplayName`, `Profile`, and the rule's application, service, port and address filters | Rules that do not cover SSH are ignored; covering rules are reported, never changed |
| Firewall profiles | `Find-BroaderSshRule` | From `ActiveStore`: `Name`, `Enabled` | A profile that is off is reported, never changed |
| Report sent to a member | `check_live.py windows` | The text between the two marker lines; encoded length under 8000 characters | A missing marker or a longer text fails the row |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-13 | integration | With a Private network, `New-NetFirewallRule` gets `-Profile Domain, Private` and `-RemoteAddress LocalSubnet`, and an existing rule on `Any` is set to `Domain, Private`. No kit file holds `-Profile Any`. `Find-BroaderSshRule` lists each broader rule and each off profile as this section defines them, and the setup changes none of them. | Human-approved (finding 2); Research-backed (https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule, https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallrule, https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallportfilter, https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallservicefilter, https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallprofile, https://learn.microsoft.com/en-us/powershell/module/netadapter/get-netadapter, https://learn.microsoft.com/en-us/powershell/module/netconnection/get-netconnectionprofile); Local Canon (`setup-windows.ps1:109`); Human-approved (review F-006); cases from the advisory read (N4, N5) | A Public network on a physical adapter stops the setup before any firewall, service or file change, and `Set-NetConnectionProfile` is never called; a setup whose only Private network is on a `vEthernet` adapter stops the same way; a Public `vEthernet` adapter and a Public adapter that `-Physical` does not return are each printed by name and do not stop; a temp copy with `-Profile Any` fails the static check. A mocked second rule `Custom SSH` (TCP 22, profile `Any`) beside the kit's rule is listed by name, and `Set-NetFirewallRule`, `Disable-NetFirewallRule` and `Remove-NetFirewallRule` are never called for it. These are also listed: local port `1-1024`; the list `22,3389`; a rule the mock returns only for `-PolicyStore ActiveStore`; remote `Any`; remote keyword `Internet`; a remote subnet outside the member's subnets; an IPv6 remote entry; a same-named `OpenSSH-Server-In-TCP` whose active form has profile `Any`; a profile with `Enabled` `False`. These are not listed: a second rule on `Domain, Private` with `LocalSubnet`; one with a remote subnet inside the member's subnets; a rule for TCP 3389; local port `5000-5020`; local port keyword `RPC`; a rule whose service filter is `Spooler` |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Which profiles | Research-backed | A-15 |
| Changing the category | Research-backed | A-15: never; the human decides |
| Another broader SSH rule | Research-backed | A-4: reported by name, never changed; AC-23 fails on it |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/usb/setup-windows.ps1` | modify | Profile set, preflight, `Find-BroaderSshRule` |
| `scripts/tests/SetupWindowsUsb.Tests.ps1` | modify | AC-13 |
| `scripts/tests/test_fleet_usb.py` | modify | AC-13 static check |

### WP-U5: Unix firewall, `from=` and password off

`main` runs in this order, so a failure at any step leaves the hub's key sign-in working (A-12). Before step 1, `main`
makes the clean start and the Root tool check (Root tool path, Named definitions; A-22), then the root, account and
drive-folder lines of `setup-unix.sh:15-21`. These come first, because each later step runs external commands as
root. Row 8b adds the clean start and the check (WP-U6p).

1. The console guard, then the link stop: a symlink at the home folder, `.ssh` or `authorized_keys` (`test -L`) stops
   the setup with the path named, because the Mode reader reads a link, not its target, and step 8 writes as root.
2. The Record retire step (Named definitions). From here on, a failed run leaves no `<name>.json` for `import`.
3. Packages (`openssh-server`, `curl`, and a firewall tool when none is installed: `ufw` with `apt-get`, `firewalld`
   with `dnf`). After an install, the Root tool check runs again.
4. The sudoers policy check (A-18), then the helper and the sudoers file (WP-U3), then the check's second read and
   the `LD_PRELOAD=` probe. If the first read stops the setup, the old sudoers file stays as it was. If the second
   read or the probe stops it, the setup removes the file it just wrote.
5. sshd enabled and running (`setup-unix.sh:48-53`; Remote Login on macOS). The setup finds the unit name (`ssh` or
   `sshd`) whether or not sshd already listens, because step 10 reloads that unit. Today the name is set only when
   sshd is not listening.
6. The member subnets. With no subnet left the setup stops here. It prints the subnets, because the hub must sit on
   one of them (Key-auth check).
7. Linux firewall. macOS has no firewall step. After the rules, the SSH rule report (Named definitions) names any
   other rule that may reach port 22, and deletes nothing (A-4).
   - `ufw`: an `allow from <subnet> to any port 22 proto tcp` rule for each subnet that `ufw status` lacks. If `ufw`
     was inactive, the Listener check (Named definitions) runs next, then `ufw --force enable`; a Listener stop prints
     `sudo ufw enable` for the human's rerun. An active `ufw` gets neither the Listener check nor the enable.
   - `firewalld`, running (`firewall-cmd --state` exits 0): the Firewalld rules (Named definitions), each change at
     runtime and with `--permanent`, with no `--reload`, then the Firewalld checks. No Listener check runs, because
     the setup does not turn the firewall on.
   - `firewalld`, stopped (`firewall-cmd --state` exits 252, NOT_RUNNING): the same rules with
     `firewall-offline-cmd`, then the Listener check (a stop prints `sudo systemctl enable --now firewalld` for the
     human's rerun), then `systemctl enable --now firewalld`, then the runtime zones again with the running-branch pass
     on any new zone, then the Firewalld checks. No `firewall-cmd` call that needs the daemon runs before the start.
8. The hub's key with `from="<subnets>"`. The line replaces any line that holds the same key body, and the file is
   written to a temp file and moved into place with mode 600.
9. The Key-auth check (Named definitions). If it fails, the setup stops before the drop-in is written, and password
   sign-in stays as it was.
10. The drop-in, per the Drop-in definition: the snapshot, the new file, `sshd -t`, then `sshd -T -C`. If a check
    fails, or a value is not `no`, the setup restores the snapshot, runs `sshd -t` on the restored state, and stops
    with no reload. Linux then runs `systemctl try-reload-or-restart` on the unit from step 5. If that reload fails, the
    setup restores the snapshot, reloads once more on the restored state, and stops. macOS starts `sshd` per
    connection, so it needs no reload.
11. The PowerShell step (WP-U6p, AC-32), then the CLI step, if row 0 kept it in this script; D-2 is ruled A
    (WP-U6). A failure in either keeps the drop-in, per the Drop-in definition, and leaves no record.
12. This machine's host key fingerprint, in the `SHA256:` form that `ssh-keygen -lf` prints, then the new record.
    Both run only after every step above passes; a fingerprint that cannot be read stops the setup with no record.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `ip -o -4 addr show scope global` output | `member_subnets` | Interface name, `inet` address and prefix length per line | Other lines ignored; left-out interfaces dropped per the Member subnets definition |
| `ifconfig` output | `member_subnets` | Interface name, `inet` address and hex `netmask` | Other lines ignored; left-out interfaces dropped per the Member subnets definition |
| `ss -ltnuH` output, read only when the setup turns the firewall on, and by the live check | `parse_listeners`, called by `check_listeners` | Netid, state, and local address and port per line | A line the parser cannot read stops the setup, or fails the live check |
| `ps` parent chain | `refuse_remote` | Process id and command name | A missing `ps` ends the walk |
| `sshd -T -C` output | `check_key_auth`, `install_dropin` | Lower-case key and value per line, read per the Key-auth check | Other keys ignored |
| `firewall-cmd` exit codes and runtime `--get-zone-of-interface`, `--get-default-zone`, `--get-zones`, `--list-sources`, `--list-all`, `--query-*` output, `--permanent --get-target`, and `firewall-offline-cmd --zone=<zone> --get-target` | `firewall_firewalld` | Exit 0, 1 and 252 (NOT_RUNNING); one zone name per line. An interface with no zone prints `no zone`, whatever its exit code, and then `--get-default-zone` names it. The runtime target is the one `--list-all` line whose first word is `target:` | Any other exit stops the setup; so does a source outside the target zones, a target zone with any target read other than `default`, or a `--list-all` with no `target:` line or more than one |
| `--list-ports`, `--list-services`, `--info-service`, `--list-rich-rules`, `--list-all`, `--permanent --get-target`, `--get-active-zones`, `ufw status verbose` output | `report_ssh_rules` in `fleet-admin.sh`; the setup and the live check both read it through `status` | Space-separated ports and services; one rich rule per line; `ports:` line of `--info-service`; `sources:` line of `--get-active-zones`; `target:` line of `--list-all` | Read only; a rule that may reach port 22 is reported |
| `LC_ALL=C sudo -l -U <user>` output, captured | `check_sudo_policy` | The three sections that `display.c` prints, read per A-18 | A-18 names the line it stops on, or the probe that sudo did not refuse; a stop on the second read or the probe also removes the file that `install_sudoers` wrote; the kit's own `Defaults!` line, compared token by token with double quotes and backslashes removed, is ignored |
| `authorized_keys` | `install_key` | One line per key; the hub's line carries `from=` | Other lines kept byte for byte |
| `members/*.json` on the drive | `retire_record` | The member's own name (a name clash stops the setup), and any record whose `host_key` equals this machine's host key | Other members' records unchanged |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-14 | unit | Unix half: `refuse_remote` stops the setup per the Console guard definition, with a message to run it at the machine's screen. | Human-approved (finding 3: an order that cannot lock the admin out); Research-backed (https://www.openssh.com/txt/release-9.8) | A stub chain `bash`, `sshd-session`, `sshd` stops; a chain `bash`, `gnome-terminal`, `systemd` passes; a looping chain passes at the Console guard bound |
| AC-15 | integration | The member subnets come from the stub `ip` and `ifconfig` output, with loopback, link-local and the left-out interfaces omitted, and the record's `addresses` follow the same rule. The `ufw` and `firewalld` argv follow step 7 and the Firewalld rules, and the key line follows step 8. Every running-branch `firewall-cmd` change appears twice, at runtime and with `--permanent`, with `--zone=<zone>` for a target zone, and every `firewall-offline-cmd` removal is `--zone=<zone> --remove-service-from-zone=ssh` for a target zone. No run calls `firewall-cmd --reload` or `--runtime-to-permanent`. After the rule pass or the start, the Firewalld checks pass for both the runtime and the permanent state. The Listener check runs only when the setup turns the firewall on and reads both protocols, and the SSH rule report lists each rule it defines and deletes none. A second run adds no rule, removes nothing more, and leaves `authorized_keys` byte-identical. On a member where sshd already listens, step 10 reloads the unit found in step 5. The `ss` output form is confirmed by row 13, which feeds real output through `parse_listeners` as a format check. | Human-approved (finding 3); Research-backed (https://manpages.ubuntu.com/manpages/noble/man8/ufw.8.html, https://firewalld.org/documentation/man-pages/firewalld.richlanguage.html, https://firewalld.org/documentation/man-pages/firewall-cmd.html, https://firewalld.org/documentation/man-pages/firewall-offline-cmd.html, https://firewalld.org/documentation/zone/connections-interfaces-and-sources.html, https://firewalld.org/documentation/concepts.html, https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall-cmd.in, https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall/command.py, https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/public.xml, https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/drop.xml, https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/block.xml, https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/dmz.xml, https://raw.githubusercontent.com/firewalld/firewalld/main/config/services/dhcpv6-client.xml, https://firewalld.org/2023/04/zone-priorities, https://git.launchpad.net/ufw/plain/conf/before.rules, https://git.launchpad.net/ufw/plain/conf/before6.rules, https://man7.org/linux/man-pages/man8/ss.8.html, https://raw.githubusercontent.com/iproute2/iproute2/main/misc/ss.c, https://man7.org/linux/man-pages/man7/udp.7.html, https://raw.githubusercontent.com/avahi/avahi/master/avahi-core/socket.c, https://documentation.ubuntu.com/security/security-features/network/firewall/, https://man.openbsd.org/sshd.8); Human-approved (review F-004, F-005, F-016, F-017, F-018, F-022, F-023); cases from the advisory read (N1, N6, N12, N13) | An inactive `ufw` with a stub listener on another port stops before `enable` and prints `sudo ufw enable`; no subnet left stops before the firewall; another port 22 rule is reported and no `delete` is called; an old key line without `from=` is replaced, not doubled; other keys stay. Argv checks fail on: a `firewall-cmd --remove-service=ssh` call without its `--permanent` twin; any `--reload` call; a stopped-daemon `firewall-offline-cmd` removal that uses `--remove-service=ssh`. A stub `firewall-cmd --permanent --query-service=ssh` that still exits 0 after the rule pass stops the setup; a stopped-daemon stub, whose `firewall-cmd` exits 252 until `systemctl enable --now firewalld` is logged, gets its rules through `firewall-offline-cmd` and no `firewall-cmd` change call before the start; the same stub with a listener on another port stops before the start and prints `sudo systemctl enable --now firewalld`. Zones: an interface whose runtime zone is `home` with no permanent binding gets its rules in `home`; a stopped-daemon stub that answers `home` only after the start gets the running-branch pass in `home`; a stub whose runtime zone moves outside the target set after the pass stops the setup with the interface and zone named. A source binding for the hub's subnet in `drop`, with the member interface in `public`, stops the setup before any firewall change or start, in both branches; a target zone with target `DROP`, `%%REJECT%%` or `ACCEPT` stops it; a running-daemon target zone whose `--list-all` shows `target: ACCEPT` while `--permanent --get-target` prints `default`, and one whose `--list-all` shows `target: DROP` while `--permanent --get-target` prints `default`, each with no `--reload` in the stub log, stop the setup before any runtime change, with the zone and both targets named; a `--list-all` with no `target:` line stops it; a target zone whose runtime and permanent targets are both `default` passes; a source in a target zone passes. Listeners, on a first enable (an inactive `ufw`, or a stopped `firewalld`): a `udp UNCONN` socket on 51820, UDP 22, a unicast UDP 5353 socket on the member's address under `ufw`, UDP 68 under `ufw`, and UDP 546 on a member interface in `dmz` (no `dhcpv6-client`) under `firewalld` each stop the setup; so do `udp UNCONN 0 0 0.0.0.0:5353 0.0.0.0:*` (`avahi-daemon`) and a DHCP client socket on `0.0.0.0%wlan0:68`, under an inactive `ufw` and under a stopped `firewalld`, each with the enable command printed; only a `tcp` listener on 22 and loopback sockets pass. On a rerun after that stop, an active `ufw` with the same two sockets, and a running `firewalld` with them, make no `ss` call and pass; the address forms `0.0.0.0:p`, `[::]:p`, `*:p`, `127.0.0.53%lo:53`, `[::1]:p`, `0.0.0.0%wlan0:68` and `[fe80::1]%eth0:546` each parse to the right port. SSH rule report: a zone with port `22/tcp`, a range `20-30/tcp`, a custom service on 22, a rich rule that accepts port 22, a rich rule that names a custom service on 22, a rich rule that accepts all traffic from a source, an active zone whose `--list-all` shows `target: ACCEPT` while its permanent target is `default`, one with the two targets the other way round, and a source-bound active zone with service `ssh` are each listed; a `ufw` rule that allows 22 from `192.0.2.0/24` with member subnet `192.0.2.0/25` (wider) and a rich rule that accepts port 22 from `192.0.2.0/26` (narrower) are each listed with the neutral line, and the word broader appears in neither; a `ufw` `ALLOW` from a network with To `Anywhere`, an `OpenSSH` profile, `20:30/tcp`, and `Default: allow (incoming)` are each listed; `1025-65535/tcp`, `53/udp`, a rich rule that rejects port 22 and a `ufw` `DENY` on 22 are not. Left-out interfaces: `docker0` and `virbr0` appear in no subnet, `from=` or record address; `wg0` stays |
| AC-16 | integration | The drop-in follows the Drop-in definition. The Key-auth check runs before the drop-in is written, once for each member address, and compares whole tokens. A failing `sshd -t`, a failing `sshd -T -C`, or a value other than `no` restores the snapshot and stops before any reload. A failed reload restores the snapshot, reloads once more and stops. A failure after a passing reload keeps the drop-in and makes no second reload. On success, Linux calls `try-reload-or-restart` once. Step 8 runs before step 9, and step 9 before step 10. | Research-backed (https://man.openbsd.org/sshd_config, https://man.openbsd.org/sshd.8, https://www.openssh.com/txt/release-8.7, https://raw.githubusercontent.com/openssh/openssh-portable/master/misc.c, https://man.freebsd.org/cgi/man.cgi?query=stat&sektion=1&format=html); Human-approved (review F-002, F-003, F-019); cases from the advisory read (N3, N7, N9) | On a first run, each of the three failures leaves no drop-in and no `systemctl` reload call; on a rerun with an old drop-in, each failure leaves the old file byte-identical with the same owner and mode, and no reload; an `sshd -T -C` stub that shows `passwordauthentication yes` stops; a failing reload stub leaves the old bytes and logs a second reload; a failing fingerprint step after a passing reload leaves the new drop-in, logs one reload and writes no record. Each of these Key-auth stubs stops before the drop-in is written, with no reload, and with the key, line or path named: `pubkeyauthentication no`; `authenticationmethods publickey,password`; an `authorizedkeysfile` that does not cover the file the setup wrote; one that holds only `.ssh/authorized_keys2`; one of `none`; a `pubkeyacceptedalgorithms` with only `ssh-ed25519-cert-v01@openssh.com`; `allowusers other`; `allowusers <user>@<pattern>`; `denyusers <user>`; `allowgroups other`; `denygroups` with a group that `id -Gn` lists; `strictmodes yes` with a group-writable home; `strictmodes yes` with a `.ssh` that another account owns; a good first address and a bad second one. A symlink at the home folder, at `.ssh` or at `authorized_keys` stops the setup at step 1 with the path named, before any change. These pass: `strictmodes no` with the same home; `authorizedkeysfile` with two tokens whose second is the file the setup wrote; `allowusers` with a `*` pattern that matches the account; a mode that the BSD form of the Mode reader prints |
| AC-27 | integration | Unix half of the Record retire rule (Named definitions): before any system change, the setup stops on a name clash, or renames `members/<name>.json` to `<name>.json.old` and retires any record with this machine's `host_key`; it prints this machine's fingerprint and writes a new record only after every step passes. `import` reads only `*.json`, so it ignores the `.old` file. | Human-approved (review F-008; scope addition, 2026-11-08); cases from the advisory read (its note on F-008); Local Canon (`fleet_usb.py:73-74`, `:176-177`; `setup-unix.sh:134-136`); Research-backed (https://raw.githubusercontent.com/openssh/openssh-portable/master/sshkey.c) | A temp drive with an old success record that holds this machine's `host_key`, and a failing fingerprint step, ends with no `<name>.json`, and `import --no-test` on that folder, with a temp SSH folder, does not list the member; a second member's record, with another `host_key`, is byte-identical; a record `oldname.json` with this machine's `host_key` is renamed and printed; a `<name>.json` with another `host_key`, and a `<name>.json` on a machine with no host key file, each stop the setup before any system change with the rename-or-delete message, and leave the drive byte-identical; a passing run prints the `SHA256:` fingerprint of this machine's key and writes `<name>.json` |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Step order | Research-backed | A-12 |
| Enabling a firewall that was off | Research-backed | A-11 |
| A stopped firewalld | Research-backed | A-11: `firewall-offline-cmd` |
| Another existing SSH rule | Research-backed | A-4: the SSH rule report |
| Drop-in name, checks and rollback | Research-backed | A-16 |
| Key sign-in proven before password off | Research-backed | A-16: the Key-auth check |
| Fedora's zone ports | Research-backed | A-10 |
| A zone that NetworkManager binds at runtime | Research-backed | The Firewalld rules and checks (Named definitions) |
| A listener when a firewall is first enabled | Research-backed | A-11: only on a first enable, the Listener check stops on any listener but TCP 22 and prints the enable command; the human enables the firewall at the screen and reruns |
| A runtime firewalld target that differs from the permanent one | Research-backed | The Firewalld rules: both targets are read, and any target other than `default` stops the setup |
| The human's runtime-only firewalld changes | Research-backed | A-10: no `--reload` |
| An old record on a failed rerun | Local Canon | A-12: the Record retire step |
| A record from this machine under an old name | Local Canon | The Record retire step: the `host_key` match |
| A record of this name with another host key, or none to compare (both setups) | Human-approved | The scope addition of 2026-11-08: the name-clash stop |
| Network move | Local Canon | A-6 |
| Remote run | Research-backed | A-5 |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/usb/setup-unix.sh` | modify | Guard, record retire with the name-clash stop, subnets, listener check, firewall, key line, key-auth check, drop-in with rollback, fingerprint, order |
| `.agent/fleet/usb/fleet-admin.sh` | modify | Add `report_ssh_rules`, the runtime-zone lines, and the source and target lines to `status`, if row 4 did not write them |
| `scripts/tests/test_fleet_usb.py` | modify | AC-14 Unix half, AC-15, AC-16, AC-27 Unix half; stub `firewall-offline-cmd` and the NOT_RUNNING stub |

### WP-U5w: Windows guard and password off

`Invoke-Setup` runs: the console guard and the network preflight (WP-U4); the Record retire step (Named
definitions); the OpenSSH capability; `Start-Service`; the firewall rule and the broader-rule report (WP-U4); the
keys; the Key-auth check; the marked block; `sshd.exe -T -C`; `Restart-Service sshd`; the CLI step if row 0 kept it
in this script; the fingerprint, as in WP-U5 step 12; the new record. The Key-auth check runs on the live
`sshd_config` before the marked block is written. If it fails, the setup
stops with no change to `sshd_config` and no restart. The marked block goes at the top of `sshd_config`, before the
shipped `Match Group administrators` block, and a rerun leaves exactly one. The setup keeps the file's old bytes. If
`sshd.exe -T -C` fails, or does not give the Password-off values (Named definitions), it writes the old bytes back and
stops before `Restart-Service`. If `Restart-Service` fails, it writes the old bytes back, restarts once more and stops.
After a restart passes, a later failure keeps the block, so the file and the running sshd agree.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `%ProgramData%\ssh\sshd_config` | `Set-SshdPasswordOff` | One marked block at the top; other bytes unchanged | Kept |
| `sshd.exe -T -C` output | `Test-KeyAuth`, `Set-SshdPasswordOff` | Lower-case key and value per line, per the Key-auth check | Other keys ignored |
| Parent chain | `Assert-ConsoleSession` | `ProcessId`, `ParentProcessId`, `Name` | A missing parent ends the walk |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-14 | unit | Windows half: `Assert-ConsoleSession` stops the setup per the Console guard definition. | Research-backed (https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-process) | A mocked chain through `sshd.exe` stops; one through `sshd-session.exe` stops; one through `wsmprovhost.exe` stops; one through `explorer.exe` passes; a chain that repeats a process id passes |
| AC-17 | integration | The keys are written before the marked block, the Key-auth check passes before the block is written, once for each member address and by whole tokens, the block sits at the top once after two runs, and `Restart-Service` runs once after a passing `sshd.exe -T -C`. A failed `Restart-Service` writes the old bytes back, restarts once more and stops. A failure after a passing restart keeps the block. | Human-approved (finding 3); Research-backed (https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration, https://man.openbsd.org/sshd.8); Human-approved (review F-002); cases from the advisory read (N3, N7) | A failing `sshd.exe -T -C` writes the old bytes back and `Restart-Service` is never called; a `-T` value `yes` does the same; a failing `Restart-Service` mock leaves the old bytes and logs a second call; a failing fingerprint step after a passing restart leaves the block and writes no record. Each of these mocked `-T -C` outputs stops before the marked block, leaves `sshd_config` byte-identical, makes no `Restart-Service` call, and names the key or line: `pubkeyauthentication no`; `authenticationmethods publickey,password`; an `authorizedkeysfile` that does not cover the file the setup wrote; a `pubkeyacceptedalgorithms` with only the cert algorithm; `allowusers other`; a user entry that holds `\`; `allowgroups administrators`; `denygroups users`. Both key-file forms pass: `__PROGRAMDATA__/ssh/administrators_authorized_keys`, and the same path under `%ProgramData%` with `\` and other case |
| AC-27 | integration | Windows half of the Record retire rule (Named definitions): before any system change, the setup stops on a name clash, or renames `members/<name>.json` to `<name>.json.old` and retires any record with this machine's `host_key`; it prints this machine's fingerprint and writes a new record only after every step passes. | Human-approved (review F-008; scope addition, 2026-11-08); cases from the advisory read (its note on F-008); Local Canon (`fleet_usb.py:73-74`, `:176-177`; `setup-windows.ps1:103-106`); Research-backed (https://raw.githubusercontent.com/openssh/openssh-portable/master/sshkey.c) | A temp drive with an old success record that holds this machine's `host_key`, and a mocked fingerprint failure, ends with no `<name>.json`; a second member's record, with another `host_key`, is byte-identical; a record `oldname.json` with this machine's `host_key` is renamed and printed; a `<name>.json` with another `host_key`, and a `<name>.json` with no host key file, each stop the setup before any system change with the rename-or-delete message, and leave the drive byte-identical; a passing run prints the `SHA256:` fingerprint of this machine's key and writes `<name>.json` |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Block place and restore | Research-backed | A-16 |
| Key sign-in proven before password off | Research-backed | A-16: the Key-auth check |
| An old record on a failed rerun | Local Canon | A-12: the Record retire step |
| No `from=` on Windows | Local Canon | A-3 |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/usb/setup-windows.ps1` | modify | Guard, record retire with the name-clash stop, key-auth check, marked block, restore, fingerprint, order |
| `scripts/tests/SetupWindowsUsb.Tests.ps1` | modify | AC-14 Windows half, AC-17, AC-27 Windows half |

### WP-U5b: The hub's password probe and pin refusal

After the admin check passes, `import` runs the probe for that member through its `fleet_config` entry and reads the
list after `Permission denied (`. `--no-test` skips the probe with the admin check (A-8).

Before it pins, `import` prints each record's name and host key fingerprint, in the `SHA256:` form that
`ssh-keygen -lf` prints. A record whose name `fleet_members.json` already pins with another `host_key` changes nothing:
its entry there, its `Host` block in `fleet_config` and its line in `fleet_known_hosts` stay. `import` prints the old
and new fingerprints and the Undo steps, counts that record as failed, and imports the other records. The Undo steps
are the hub's steps of the README's Undo section (`usb/README.md:93-94`): after checking the new fingerprint at the
member's screen, delete that name's entry, block and line from the three files, then run `import` again. The same key
imports again, and a new name imports. This replaces today's re-pin (`fleet_usb.py:195-197`).

The probe is the hub's last check, not the setup's guard. The setup's own guard is the Key-auth check (Named
definitions), which runs before password sign-in is turned off. The probe tests only the account in the member's
record, from the hub's address. It does not prove the policy for another account or another source address. The Key-auth
check cannot test `from=` (Named definitions). A hub outside the member subnets is refused at `import`'s key connection
(`fleet_usb.py:165-173`), before the probe runs, and that member counts as a failure. The human then reruns the setup at
the member's screen with the hub on a member subnet.

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-18 | unit | The probe passes only on the list `publickey`, and `import` counts any other result as a failure, with the member named. | Research-backed (https://www.rfc-editor.org/rfc/rfc4252, https://man.openbsd.org/ssh_config) | Lists `publickey,password` and `publickey,keyboard-interactive` fail; output with no list (refused or timed out) fails; `--no-test` makes no `ssh` call |
| AC-31 | unit | Before it pins, `import` prints each record's name and fingerprint. A name that `fleet_members.json` pins with another `host_key` is refused: the three files keep that name's entry, block and line, the old and new fingerprints and the Undo steps print, and the record counts as failed while the other records import. | Human-approved (scope addition, 2026-11-08); Local Canon (`fleet_usb.py:183-203`, `usb/README.md:93-94`); Research-backed (https://raw.githubusercontent.com/openssh/openssh-portable/master/sshkey.c, https://raw.githubusercontent.com/openssh/openssh-portable/master/ssh-keygen.1) | With a temp SSH folder, a changed key for a pinned name makes `import --no-test` exit 1 and leaves that name's `fleet_members.json` entry, `fleet_config` block and `fleet_known_hosts` line byte-identical, while a second member's record imports in the same run; the same key imports again; a new name imports; the printed fingerprint of a sample ed25519 key equals the `SHA256:` value that `ssh-keygen -lf` printed for it, held in the test as a literal |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/usb/fleet_usb.py` | modify | The probe, the fingerprint lines, the pin refusal |
| `scripts/tests/test_fleet_usb.py` | modify | AC-18, AC-31 |

### WP-U6: Signature checks

**The Ubuntu image.** `write-installer-usb.ps1` gets `Get-ExpectedHash`, `Find-Gpg`, `Invoke-Gpg` and
`Test-SumsSignature`. All of them run before `Clear-Disk` (`:44`), in this order:

1. `Find-Gpg` takes `gpg` from `PATH`, else `usr/bin/gpg.exe` under the Git root that `Find-GitRoot` finds (the Git
   root rule, Named definitions), else stops.
2. In a new temp `GNUPGHOME`, the key comes from `-KeyFile` or from
   `--keyserver hkps://keyserver.ubuntu.com --recv-keys 843938DF228D22F7B3742BC0D94AA3F0EFE21092`.
3. `gpg --batch --status-fd 1 --verify SHA256SUMS.gpg SHA256SUMS` passes only when all of these hold (gnupg
   `DETAILS`): the exit code is 0; there is a `GOODSIG` line; there is a `VALIDSIG` line whose first field (the
   signing-key fingerprint) or last field (the primary-key fingerprint) is that key; and there is no `BADSIG`,
   `ERRSIG`, `EXPSIG`, `EXPKEYSIG`, `REVKEYSIG` or `NO_PUBKEY` line. A `VALIDSIG` alone proves only that the
   signature is cryptographically sound, and it can come with a revoked or expired key, so it is not enough. The
   check fails closed: a file that also carries a second signature by an unknown key gives `NO_PUBKEY` and is
   refused.
4. `Get-ExpectedHash` reads each `SHA256SUMS` line as 64 lowercase hex digits, one space, an optional `*`, and a
   name. Exactly one line's name must equal the image's file name.
5. The image's SHA-256 must equal it, as today (`:37`).

Probe-2 runs `check_live.py keyfetch` on the hub: it fetches the key into a temp `GNUPGHOME` under the receipts folder
and prints its fingerprint. No drive is touched.

**The CLIs, only in a setup script where row 0 kept that step, with D-2 ruled A (row 7a checks it).** Probe-1 runs first. It reads each vendor's current install docs,
runs `check_live.py clisig` on the hub's own installed `claude` and `codex` binaries, and records the Authenticode
signer names, the macOS signing team, the Linux manifest key (`31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE` in
the Claude Code setup docs today), and whether Codex has a release digest or attestation to check. Then
`install_cli` and `Install-Cli`, each only in the script that kept the step, download each installer to a file, run it,
and verify the installed binary: Windows by
`Get-AuthenticodeSignature` status `Valid` and the signer from Probe-1; macOS by `codesign --verify --strict` and the
team from Probe-1; Linux by the signed manifest and the binary's SHA-256. A mismatch stops the setup, names the file,
and writes no new record. The record that an earlier run left is already retired at the start of the run (Named
definitions, Record retire, AC-27), so `import` never sees that member as set up. If Probe-1 finds nothing to check
for one CLI, execution stops for the human (stop condition 4).

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `SHA256SUMS` | `Get-ExpectedHash` | One exact-name line | Other lines ignored; two matches refused |
| `gpg --status-fd 1` and its exit code | `Test-SumsSignature` | Exit 0, `GOODSIG`, and a `VALIDSIG` whose first or last field is the key | Any `BADSIG`, `ERRSIG`, `EXPSIG`, `EXPKEYSIG`, `REVKEYSIG` or `NO_PUBKEY` line refuses; other status lines are ignored |
| `-KeyFile` | `param` block | A readable file | Binding error |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-19 | integration | With `Invoke-Gpg` mocked, the write runs only after the step 3 rule passes for the Ubuntu key and an exact, single hash line is found, and every refusal comes before `Clear-Disk`. `Find-Gpg` takes `PATH` first, then `Find-GitRoot`, whose rule and synthetic layouts are the ones AC-28 tests in Python. | Human-approved (finding 4); Research-backed (https://ubuntu.com/tutorials/how-to-verify-ubuntu, https://github.com/gpg/gnupg/blob/master/doc/DETAILS); Local Canon (the Git root rule, Named definitions); cases from the advisory read (its note on F-009) | Each refuses with `Clear-Disk` called zero times: a `kubuntu-` line whose name ends with the image's name; two matching lines; `GOODSIG` with no `VALIDSIG`; a `VALIDSIG` with another fingerprint; a matching `VALIDSIG` with `REVKEYSIG`; a matching `VALIDSIG` and `GOODSIG` with exit code 1; a matching `VALIDSIG` with `EXPKEYSIG`; a matching `VALIDSIG` with `EXPSIG`; a matching `VALIDSIG` with a second `NO_PUBKEY` line; no `gpg` found; a missing `SHA256SUMS.gpg`. `Find-Gpg`: a `gpg` on `PATH` wins over the Git root; with none on `PATH`, synthetic roots with `git.exe` in `cmd/`, in `mingw64/bin/` and in `ucrt64/bin/` each give `<root>/usr/bin/gpg.exe`; a `git` under `%SystemRoot%` or `WindowsApps` is refused; a root with no `gpg.exe` stops before `Clear-Disk` |
| AC-20 | unit | No kit file pipes a download into a shell. In each setup script where row 0 kept the CLI step, each installed binary is verified as above before the record is written. | Human-approved (finding 4); Research-backed (https://code.claude.com/docs/en/setup, https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-authenticodesignature) | A temp copy with a `curl` output piped to `sh` fails; in a script that kept the step, a mocked `NotSigned` or wrong-signer result stops the setup with the file named and no record written, and an old record for that member is not left importable (AC-27) |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Key, fingerprint, exit code and status lines | Research-backed | Ubuntu tutorial; gnupg `DETAILS` (`VALIDSIG` can come with `REVKEYSIG` or an expiry status) |
| Where `gpg` comes from | Local Canon | A-17; `install-usb/README.md:25`; the Git root rule, through `Find-GitRoot` |
| CLI check | Human-approved | D-2 ruled A by the human on 2026-11-08; row 7a checks it, and row 8a waits for it |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/install-usb/write-installer-usb.ps1` | modify | Signature and exact-name checks, `Find-GitRoot`, `-KeyFile` |
| `.agent/fleet/usb/setup-unix.sh` | modify | `install_cli` verification, only if row 0 kept it in this script |
| `.agent/fleet/usb/setup-windows.ps1` | modify | `Install-Cli` verification, only if row 0 kept it in this script |
| `scripts/tests/WriteInstallerUsb.Tests.ps1` | modify | AC-19 |
| `scripts/tests/SetupWindowsUsb.Tests.ps1` | modify | AC-20 Windows half, if row 0 kept it |
| `scripts/tests/test_fleet_usb.py` | modify | AC-20 |

### WP-U6p: PowerShell on macOS and Linux members (amendment, D-3)

The fleet runs kit scripts with `pwsh` (`fleet.py:1641-1643` and `:1788-1789` refuse with `tool_missing:pwsh`), and
this repo's manifest requires it (`.agent/fleet.json`, `"requires": ["python", "pwsh", "claude"]`). Windows members
get it from `setup-member.ps1`; nothing installs it on macOS or Linux. The human chose A on 2026-11-14 (D-3).

**The pin, on the hub.** `prepare` computes the pin before it writes any file, so a failure leaves the folder as it
was and exits 1 with the reason.

1. `fetch_releases()` reads `https://api.github.com/repos/PowerShell/PowerShell/releases?per_page=100` with
   `urllib.request`, a 30 s timeout, `Accept: application/vnd.github+json`, the User-Agent `fleet-usb`, and no token
   (the hub's GitHub sign-in is not used). It follows the `Link` header's `rel="next"` URL, which must stay on
   `https://api.github.com/`, page by page until a page has no `rel="next"`, and it reads at most `RELEASE_PAGE_LIMIT = 10`
   pages, the page limit, a constant in `fleet_usb.py`. This is the one place that states the limit. It returns the
   releases of all pages. If the last page that the limit allows still has a `rel="next"`, the list is not complete,
   so `prepare` stops with "the PowerShell release list is longer than the page limit" (stop condition 13) and
   chooses no pin. A network or JSON
   error, or a `rel="next"` URL on another host, stops `prepare` with the error named.
2. `pwsh_pin(releases, now)` is pure. It takes the releases that pass the selection predicate of A-21, in A-21's
   order, highest version first. For each of the four platforms `linux-x64`, `linux-arm64`, `osx-x64` and
   `osx-arm64`, exactly one asset must be named `powershell-<version>-<platform>.tar.gz`, its `digest` must be
   `sha256:` and 64 hex digits, and the release notes must list that name with the same hash, ignoring case, on the
   next line (A-20). The first release that passes is the pin. Each release that fails prints one line with its
   version and reason. With no pin, `prepare` stops.
3. `prepare` writes `pwsh-pin.txt` in the drive folder, LF line ends: four lines `<version> <platform> <sha256>`,
   the hash in lower case. It prints `PowerShell pin: <version> (published <date>)`.

**The PowerShell step, on the member.** `install_pwsh <pin file> <install root> <bin dir> <os> <arch> <user>` is
called by root in WP-U5 step 11. `main` passes `/opt/microsoft/powershell` on Linux and
`/usr/local/microsoft/powershell` on macOS, `/usr/local/bin`, `uname -s` and `uname -m`, and the account (A-19).

**Execution identity.** Each program that the step runs has one fixed identity. This is the one place that states
them.

- A `pwsh` that the step finds and did not install runs only as the account, through `sudo -u "$user" -i`, as
  `has_cli` does (`setup-unix.sh:122`). Root never runs it, and root never runs `command -v pwsh` in its own shell.
- `curl`, `sha256sum` or `shasum`, `tar`, `install`, `chmod`, `mv`, `ln` and `rm` run as root, as every other step of
  the setup does, each from the Root tool path after the Root tool check (Named definitions). They write only inside
  the folders that pass the Parent walk in step 4.
- Root runs one `pwsh` only: `<install root>/<version>/pwsh`, after its hash check (step 5) and after the Parent walk
  of its folder passes again (step 7).

1. Find an existing `pwsh`. The step asks the account's login shell, `sudo -u "$user" -i command -v pwsh`, and also
   tests whether `<bin dir>/pwsh` exists, with a file test and no run. Each path found runs as the account:
   `sudo -u "$user" -i <path> -NoLogo -NoProfile -NonInteractive -Command '$PSVersionTable.PSVersion.Major'`. A major
   of 7 or more leaves it alone, and the step prints its path and version and ends. A lower major, or a `pwsh` that
   does not run as the account, stops the setup with the path named, and nothing is changed: the kit never replaces
   a `pwsh` that it did not install.
2. The platform: `Linux` gives `linux`, `Darwin` gives `osx`; `x86_64` gives `x64`, `aarch64` and `arm64` give
   `arm64`. Any other value stops the setup with the value named.
3. `read_pwsh_pin` takes the one line for the platform. A missing file, a line count other than four, a version that
   does not match `^[0-9]+\.[0-9]+\.[0-9]+$`, an unknown platform word, a hash that is not 64 lower-case hex digits,
   or two lines for one platform stops the setup with "run fleet_usb.py prepare again on the hub".
4. The Parent walk (Named definitions) runs on `<install root>` and on `<bin dir>` before any write. Each path must
   also be equal to its physical path (`pwd -P`), so no part of it is a symlink. If part of `<install root>` does not
   exist yet, the walk runs on the deepest part that exists, then root makes the missing folders with
   `install -d -m 755 -o 0 -g 0`, and the walk runs again on `<install root>`. A failed walk stops the setup with the
   path named, before any download, unpack, root run or link (stop condition 6). The kit never changes the owner or
   mode of a folder that it did not make. So a `<bin dir>` that a package manager gave to the account, such as
   `/usr/local/bin` under Homebrew on an Intel Mac, stops the setup, and the human chooses what to do.
5. The download folder is `<install root>/.dl-<pid>`, made with `install -d -m 700 -o 0 -g 0`; an old folder with
   that name is removed first. No file goes in a world-writable temp folder. `curl -fsSL --retry 3 --proto '=https'`
   writes
   `https://github.com/PowerShell/PowerShell/releases/download/v<version>/powershell-<version>-<platform>.tar.gz` to
   `"$archive"` in that folder. Nothing is piped into a shell (AC-20). `sha256sum` on Linux, or `shasum -a 256` on
   macOS, must print the pin's hash; a mismatch deletes the file and stops the setup with the file name and both
   hashes.
6. The stage `"$stage"` is the folder `<install root>/<version>.new` (removed first if it exists), made with
   `install -d -m 755 -o 0 -g 0`. The file is unpacked with `tar --no-same-owner -xzf "$archive" -C "$stage"`. The
   tree is then owned by 0:0 with no group or other write bit, `pwsh` mode 755, and is moved to
   `<install root>/<version>`, which replaces a folder of that name that an earlier failed run left.
7. The Parent walk runs again on `<install root>/<version>`, and `<install root>/<version>/pwsh` must be a regular
   file, not a symlink, with owner 0 and no group or other write bit. A failure removes the folder and stops the
   setup. Then root runs `<install root>/<version>/pwsh` with `HOME` set to the download folder, so it writes nothing
   in root's home, and it must print exactly the pin's version for `$PSVersionTable.PSVersion.ToString()`. Otherwise
   the step removes the folder and stops the setup with what `pwsh` printed; on Linux, a missing ICU library is the
   usual cause, and the human installs it and runs the setup again.
8. The Parent walk runs again on `<bin dir>`. Only then `ln -sfn` points `<bin dir>/pwsh` at
   `<install root>/<version>/pwsh`, and the step notes `pwsh-<version>`. The download folder is removed on every exit.
   A failure at any step leaves no link, so a rerun starts clean.

The pin on the drive has the same trust as the script that reads it (the one-drive trust rule, WP-U7); it checks the
download, not the drive.

**The clean start and the Root tool check (review F-037, A-22).** Row 8b adds to `setup-unix.sh` the constant
`root_tools`, `clean_start` and `check_root_tools`, per the Root tool path definition, and makes them the first
statements of `main` (WP-U5, before step 1). It changes the launch form in `Setup Mac.command:5`,
`Setup Linux.desktop:7` and the header comment at `setup-unix.sh:6-7`; row 9 changes the run lines in `usb/README.md`
(WP-U7). The definition is the rule; this sketch shows its shape, and `bash -n` passes on it:

```bash
clean_start() {
    local tool_path=$1 name extra=""
    shift
    IFS=$' \t\n'
    if [ "${FLEET_USB_CLEAN:-}" != 1 ]; then
        exec /usr/bin/env -i FLEET_USB_CLEAN=1 PATH="$tool_path" LC_ALL=C TERM=dumb \
            SUDO_USER="${SUDO_USER:-}" /bin/bash -p "$0" "$@"
    fi
    case $- in *p*) ;; *) die "the clean start failed: bash runs without -p" ;; esac
    case ${OSTYPE:-} in msys* | cygwin*) extra=" MSYSTEM SYSTEMROOT WINDIR" ;; esac
    for name in $(compgen -e); do
        case " FLEET_USB_CLEAN PATH LC_ALL TERM SUDO_USER PWD OLDPWD SHLVL$extra " in
        *" $name "*) ;;
        *) die "the clean start failed: $name is set" ;;
        esac
    done
    PATH=$tool_path
    export PATH
    hash -r
    unalias -a
}

check_root_tools() {
    local tool_path=$1 name found dir ok
    shift
    for name in "$@"; do
        found="$(command -v "$name" || true)"
        [ -n "$found" ] || continue
        ok=""
        IFS=:
        for dir in $tool_path; do
            case $found in "$dir/$name") ok=1 ;; esac
        done
        IFS=$' \t\n'
        [ -n "$ok" ] || die "the root tool $name resolves to $found, not to a folder of $tool_path"
        printf '%s=%s\n' "$name" "$found"
    done
}
```

`main` then calls `check_root_tools "$tool_path" $root_tools`. The hub's Git bash 5.3 ran this sketch with a hostile
`PATH` folder and exported functions: no fake ran, the lookups printed `/usr/bin` paths, and the run stopped at
"run it with sudo". A forged marker, with or without `-p`, stopped at the clean start.

**Probe-3.** Row 8b runs `check_live.py pwshpin` on the hub after `fetch_releases` and `pwsh_pin` exist and their
AC-32 tests pass, and before any drive folder or member is written. It calls the real releases list, all pages, and
prints the pin that `pwsh_pin` would take today, and each release it skips with the reason. It is read-only and writes
no drive folder. `check_live.py` imports a mode's functions only when that mode runs, so its other modes and
`--selftest` run before row 8b. No pin, or a list longer than the page limit of WP-U6p step 1, is stop condition 13.

**The member process's `PATH`.** A `pwsh` that the step installs is in `/usr/local/bin`. That folder is on `PATH` for a
login shell and for systemd services on Linux, but not for a non-interactive SSH command on macOS. The fleet finds
`pwsh` with `shutil.which` in the member process's own environment (`fleet.py:1466`, `:1641-1643`,
`:1788-1789`). The live checks of rows 13 and 14 run `pwsh` in a non-interactive SSH command, with the absolute path
as the fallback (WP-U8), so they are installation evidence only; they do not prove that a member process finds `pwsh`. That lookup is a prerequisite of the Unix member process. When a later
plan builds Unix member provisioning (Out of Scope here), it must check that `pwsh` is found in that process's own
environment.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| GitHub releases JSON | `pwsh_pin` | `tag_name`, `draft`, `prerelease`, `published_at`, `body`, and each asset's `name` and `digest`, per step 2 and the selection predicate of A-21 | Other fields ignored; a release that fails a rule is skipped with its reason; none left stops `prepare` |
| The `Link` header of each releases page | `fetch_releases` | A `rel="next"` URL on `https://api.github.com/`; no more pages than the page limit of step 1 | Other links ignored; a next URL on another host, or a next link on the last page that the limit allows, stops `prepare` |
| `pwsh-pin.txt` on the drive | `read_pwsh_pin` | Four lines, `<version> <platform> <sha256>`, per step 3 | Any other line stops the setup |
| `uname -s`, `uname -m` | `install_pwsh` | The values in step 2 | Any other value stops the setup |
| The output of an existing or new `pwsh` | `install_pwsh` | One version line. An existing `pwsh` runs only as the account; root runs only the `pwsh` that it installed (Execution identity) | A major below 7, a run that fails, or a version other than the pin's stops the setup |
| The folders that the step writes, runs or links in: `<install root>`, `<install root>/<version>` and `<bin dir>` | `install_pwsh`, with the Parent walk | The Parent walk (Named definitions) on each folder, and the path equal to its physical path, per steps 4, 7 and 8; `<install root>/<version>/pwsh` a regular root file, per step 7 | A failed Parent walk or a symlink stops the setup before the write, root run or link |
| The setup's environment and its root command lookup | `clean_start` and `check_root_tools` in `setup-unix.sh` | The variables that the clean start passes or allows, and each `root_tools` name at `<folder>/<name>` for a folder of the Root tool path (Named definitions) | Any other variable, a forged marker, or a function, alias, builtin or other path stops the setup before any write (stop condition 6) |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-32 | integration | `prepare` reads every page of the releases list, up to the page limit of WP-U6p step 1, and writes `pwsh-pin.txt` for the release that the selection predicate of A-21 picks and whose four tarball digests equal its notes' hashes (A-20), before any other file, and writes nothing when there is no pin or the list is longer than that limit. `install_pwsh` runs a `pwsh` that it did not install only as the account, and leaves one of 7 or later alone. It passes the Parent walk on `<install root>` and `<bin dir>` before any write, stages inside `<install root>`, installs that platform's build only after its SHA-256 matches, and walks again before root runs the new `pwsh` and before it links `<bin dir>/pwsh`. `setup-unix.sh` `main` makes the clean start and the Root tool check (Root tool path, Named definitions) before any other external command, and both Unix launchers and the header comment use its launch form. | Human-approved (D-3 A, 2026-11-14; review F-037, "fix and add round 10", 2026-11-14); Research-backed (https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html, https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files.html, https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudoers.man.in, https://learn.microsoft.com/en-us/powershell/scripting/install/alternate-install-methods, https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-macos, https://docs.github.com/en/rest/releases/releases); Local Canon (`fleet.py:1641-1643`, `.agent/fleet.json`) | `pwsh_pin` with a fixed `now` and a release list held in the test: a newer release 13 days 23 hours old, a prerelease and a draft are passed over, and one exactly 14 days old qualifies; 7.10.0 wins over 7.9.0; a candidate whose digest differs from its notes' hash, and one with no `osx-arm64` asset, are skipped with their versions printed and the next one is taken; a list with no qualifying release makes `prepare` exit 1 and leaves the folder byte-identical, as does a mocked `URLError`. Paged lists held in the test, with mocked `Link` headers: when page 1 holds only younger or prerelease entries and the winner is on page 2, the page-2 release is the pin; a list whose page number `RELEASE_PAGE_LIMIT` (the test reads the constant, and holds no literal limit) still has a `rel="next"` makes `prepare` exit 1 with the page-limit message and leaves the folder byte-identical; a `rel="next"` URL on another host does the same. `install_pwsh` with stub `curl`, `uname`, `stat` (the Mode reader, as in AC-9), `sudo` and hash tools on `PATH` and a real tar.gz made in the test, holding a stub `pwsh` script: with `stat` reporting owner 0 and mode 755 on every folder, a right hash on `Linux x86_64` installs under the temp install root, the `curl` log shows its output file under `<install root>/.dl-<pid>` and not under `$TMPDIR` or `/tmp`, and the step links the temp bin dir; a fake account-owned `pwsh` that the account's login shell finds, whose body writes a marker with `id -u` and the identity that the stub `sudo` stands for, is run only through the stub `sudo` with `-u <user> -i` (its log shows that call), and the marker names the account and never uid 0 or root, so a run of it outside `sudo` fails the test; a `stat` that reports a parent of the install root with a user owner, one with mode 0777, one with mode 1777 (sticky), and a bin dir with a user owner (the Homebrew case) each stop with the path named before `curl`, `tar`, the new `pwsh` or `ln` is called; an install root and a bin dir that are symlinks to folders that pass each stop the same way; `Darwin arm64` reads the `osx-arm64` line and calls `shasum`; a wrong hash stops with the file named and leaves no folder and no link; a stub that prints another version stops and leaves no folder and no link; an existing `pwsh` 7.4 means `curl` is never called; an existing `pwsh` 6.2 stops with its path and changes nothing; `riscv64` stops with the value named; a missing pin file, a three-line file and an upper-case hash each stop with the prepare message. The F-037 cases run `setup-unix.sh` as a file in Git bash, without root, with a hostile `PATH` folder first that holds a fake `id` (it prints 0), `uname`, `dirname`, `stat`, `tar` and `install`, and with the exported functions `id`, `stat` and `tar` (`export -f`); each fake writes a marker. The run passes only if no marker exists, the output prints `stat`, `tar` and `install` at a folder of the Root tool path, and the run ends at the root check (`setup-unix.sh:15` today) with "run it with sudo". The same run in the launch form's `/bin/bash -p`, with `BASH_ENV` naming a marker script, leaves no marker. A forged `FLEET_USB_CLEAN=1` with an extra exported variable under `bash -p`, and one without `-p`, each stop with "the clean start failed". A copy with its own `stat` function stops at the Root tool check with `stat` named; a copy without the clean start stops there with the hostile path named; a copy without both leaves a marker, so the test fails on it. A static check finds `/usr/bin/sudo /bin/bash -p` in `Setup Mac.command`, `Setup Linux.desktop` and the header comment of `setup-unix.sh`, and no bare `sudo bash` in them, and finds each name of the floor in the Root tool path definition on `root_tools` |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Install PowerShell on macOS and Linux members from the kit | Human-approved | D-3 A, 2026-11-14 |
| The release rule and its 14 days | Human-approved | D-3 A: the human accepted "the newest stable PowerShell release that is at least 14 days old" (A-21) |
| How the hash is checked | Research-backed | The release notes list each asset's SHA-256; GitHub's REST API gives each asset's `digest` (A-20) |
| Folders and link | Research-backed | Microsoft's binary-archive steps (A-19) |
| Every page of the release list | Research-backed | GitHub's REST list takes `per_page` up to 100 and gives the next page in the `Link` header (https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api); the page limit of WP-U6p step 1 is stop condition 13 |
| Who runs a found `pwsh`, and the owners of the install folders | Local Canon | `has_cli` runs the account's lookup through `sudo -u "$user" -i` (`setup-unix.sh:122`); the Helper's parent walk, now the Parent walk (Named definitions) |
| How root finds the tools that it runs, and how the setup starts | Research-backed | A-22: the bash manual for `-p` (no `BASH_ENV` or `ENV`, no imported functions, `SHELLOPTS`, `BASHOPTS`, `CDPATH` and `GLOBIGNORE` ignored) and `command -v`; sudoers(5) for `env_reset`, `secure_path` and the variables it removes; Local Canon `setup-unix.sh:1,9,15-21` and the launchers `Setup Mac.command:5`, `Setup Linux.desktop:7`; review F-037 |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/usb/fleet_usb.py` | modify | `fetch_releases` with its page limit, `pwsh_pin`, and the pin in `prepare` |
| `.agent/fleet/usb/setup-unix.sh` | modify | `read_pwsh_pin` and `install_pwsh` with the Execution identity and the Parent walk, called in WP-U5 step 11; `root_tools`, `clean_start` and `check_root_tools` at the start of `main`; the launch form in the header comment |
| `.agent/fleet/usb/Setup Mac.command` | modify | `:5` in the launch form of the Root tool path definition |
| `.agent/fleet/usb/Setup Linux.desktop` | modify | The `sudo bash` call in `:7` in the launch form |
| `scripts/tests/test_fleet_usb.py` | modify | AC-32 |

### WP-U7: Docs

- `core/MANIFEST.md`: fix `:21-22` to "Both exist; neither replaces the other." Move the fleet entries (`:35-42`)
  out of the registry-home section into a new section after it. The `usb/` entry names the helper, the subnet
  firewall, password off and `from=`. The `install-usb/` entry names the signature check.
- `UPDATE-CHECKLIST.md`: a sync-map item "Fleet and USB kits (written in this package; no source copy)", and a
  post-refresh smoke step that runs `scripts/tests/test_fleet_usb.py` and the two new Pester files and confirms
  `NOPASSWD: ALL` and `-Profile Any` are absent from `.agent/fleet/`.
- `.agent/fleet/bootstrap.md:24`: scoped to `fleet.py`'s own port. The SSH kit's port 22 rule is the one inbound rule,
  limited to the local subnet.
- Both READMEs: the new behavior, the console-only rule, the Undo steps (helper folder, sudoers file, drop-in,
  firewall rules, the key line; on Windows, the rule and the marked block), and the helper's verbs in place of the raw
  `sudo` lines at `install-usb/README.md:116-125`.
- `usb/README.md`, the drive and `import` (scope addition, 2026-11-08): compare the fingerprint that each setup prints
  with the one that `import` prints for that name, and treat an unknown name as tampering. One drive may serve several
  members before one `import`; names must differ; every member must be reachable at `import`, which can run again.
  Every machine the drive visits can write to it, so compare on every machine and keep the drive with you. A changed
  key is refused, and its Undo steps print with it. The drive also carries the setup scripts, the launchers and the
  helper, which run as administrator or root, and a machine that the drive visits can change them. So one drive
  serves several members only when every member is equally trusted. For a member that is not, use a drive that only
  the hub has written: run `import` on the hub for the records collected so far, then run `prepare` onto a new drive,
  or onto one freshly formatted on the hub. `import` reads only `members/*.json` (`fleet_usb.py:177`). It writes the
  entry of each name that it takes, keeps every other name in the hub's `fleet_members.json`, and writes
  `fleet_config` and `fleet_known_hosts` from that whole file (`:183-203`), so a format after an `import` loses no
  record that it took. It takes each valid record, also one whose member does not answer (`:194-200`), except one that
  the pin refusal refuses (WP-U5b). A record that it skips as unreadable or invalid (`:188-192`) or refuses, and a
  record written after the last `import`, exist only on the old drive: a format loses them, and that member then runs
  its setup again from a drive that the hub wrote. Until then, keep the old drive away from every member, since
  `import` can read it again. On a new drive, the name-clash stop of Record retire sees no earlier member's record,
  but the pin refusal still refuses a pinned name with another host key. A `prepare` into a folder that already holds
  files is not a reset: it rewrites the setup scripts, the launchers, the helper, the README, `hub.pub` and
  `pwsh-pin.txt` from the hub's copy, and keeps the records in `members/`, which still need the fingerprint compare, and every other file.
  `Setup Windows.cmd` calls `net` and `powershell` by bare name (`:4`, `:6`, `:9`), and `cmd.exe` searches the current
  directory before `PATH` unless `NoDefaultCurrentDirectoryInExePath` is set. So when the launcher runs with the drive
  folder as its current directory, a `powershell.cmd` that a visited member left there can run in place of Windows
  PowerShell, before the trusted setup, and can raise the elevation prompt for its own code.
- `usb/README.md`, a Listener stop on Linux: the setup prints the listening sockets and the command that turns the
  firewall on (`sudo ufw enable`, or `sudo systemctl enable --now firewalld`). Check those services, run that command
  at the screen, then run the setup again.
- `usb/README.md`, PowerShell (amendment, D-3): `prepare` pins the newest stable release that is at least 14 days old
  and needs the hub to reach GitHub; the setup installs it under `/opt/microsoft/powershell/<version>` on Linux or
  `/usr/local/microsoft/powershell/<version>` on macOS and links `/usr/local/bin/pwsh`, only after the hash check; a
  `pwsh` 7 or later that is already there is left alone, and the setup runs it only as the account. A folder that
  another user can change stops the setup; on an Intel Mac with Homebrew, `/usr/local/bin` belongs to the account, so
  install PowerShell 7 as the account first, and the rerun leaves it alone. A version stop on Linux usually means a missing ICU library:
  install the distribution's `libicu` package and run the setup again. Undo:
  `sudo rm -f /usr/local/bin/pwsh` and `sudo rm -rf` the version folder.
- `usb/README.md`, the run lines at `:57-58` (review F-037): the launch form of the Root tool path definition, with
  one sentence on why the full paths matter: a bare `sudo` or `bash` can be a program that the account put first on
  its `PATH`.

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-21 | unit | The text checks above pass, and `test_fleet_bootstrap.py` stays green: `bootstrap.md` still says a member must never read `member.json`, keeps "hash" in §Update and `FIREWALL_RULE`, has no "approve" before `run-approve`, and holds no IPv4 literal. | Human-approved (finding 6; scope addition, 2026-11-08; review F-024; review F-037); Local Canon (`core/MANIFEST.md:16-42`, `UPDATE-CHECKLIST.md:63,569`, `bootstrap.md:24,96-101`, `fleet_usb.py:66-89,176-203`, `Setup Windows.cmd:4-9`); Research-backed (https://learn.microsoft.com/en-us/windows/win32/api/processenv/nf-processenv-needcurrentdirectoryforexepatha) | A copy of `MANIFEST.md` with the fleet entries under registry-home fails; a README that still holds `sudo systemctl mask` fails; `UPDATE-CHECKLIST.md` without the smoke step fails; a `usb/README.md` without the fingerprint compare, without the words `equally trusted`, without the words `not a reset`, without the ordered steps (`import` on the hub, then a new or freshly formatted drive, then `prepare`), without the warning that a format loses a record that `import` skipped or refused or that was written after the last `import`, without `sudo ufw enable`, without the PowerShell paragraph (the words `14 days`, `/usr/local/bin/pwsh` and `libicu`), or with a bare `sudo bash` in place of the launch form of the Root tool path definition fails |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `core/MANIFEST.md` | modify | New fleet section; `:21-22` text |
| `UPDATE-CHECKLIST.md` | modify | Sync-map item and smoke step |
| `.agent/fleet/bootstrap.md` | modify | `:24` scoped |
| `.agent/fleet/usb/README.md` | modify | Behavior, console rule, Undo, the fingerprint compare, the drive points with the one-drive trust rule, the hub-written drive and the not-a-reset note, the Listener-stop rerun, the PowerShell paragraph, and the launch form in the run lines |
| `.agent/fleet/install-usb/README.md` | modify | Signature check, helper verbs |
| `scripts/tests/test_fleet_usb.py` | modify | AC-21 |

### WP-U8: Gates and live members

`check_package_gates.py` is copied from the fleet-agents plan and adapted: `LIVE_ACS` 3, 22, 23, 24, 25, 29 and 30
(the ACs that live rows or the checker's own `--selftest` prove); `AC_COUNT` 32; `MANIFEST_ENTRIES`
`.agent/fleet/usb/` and `.agent/fleet/install-usb/`; `PYTEST_FILES` `scripts/tests/test_fleet_usb.py`;
`PESTER_FILES` the two new Pester files; baseline `uk-gates-baseline.json`, which also holds the row 1 state id and the row 1 HEAD.
`check_live.py` reads the drive records from `$env:FLEET_USB_FOLDER` and picks the one member of each system, so it
names no host. Its modes are `hello`, `keyfetch`, `clisig`, `pwshpin`, `windows`, `linux` and `macos`, and
`--selftest` feeds each mode the bad samples its AC names. Each mode imports its functions only when it runs, so
`pwshpin` imports `fetch_releases` and `pwsh_pin` from `fleet_usb.py` only in its own run (Probe-3), and the other
modes and `--selftest` run before those functions exist. The `linux` and `macos` modes also print a `pwsh:` line: over
the row's SSH call they run `command -v pwsh`, else `/usr/local/bin/pwsh`, with `-NoLogo -NoProfile -NonInteractive
-Command '$PSVersionTable.PSVersion.ToString()'`, and print the path and version. No `pwsh`, or a major below 7, fails
the mode. The `pwsh:` line is installation evidence only: it does not prove that a member process finds `pwsh` on its
own `PATH` (WP-U6p, The member process's `PATH`). `$env:FLEET_USB_FOLDER` is the drive folder that
`fleet_usb.py prepare` wrote; the human sets it before rows 12 to 14.

Stock samples of `sudo -l` and `ss` are written from the sources this plan cites, not from a live machine, so the live
modes test the parsers against real text. The `linux` and `macos` modes read `LC_ALL=C sudo -n -l` over the row's SSH
call. That call needs no password, because the account's one rule is `NOPASSWD` and `listpw` defaults to `any`. They
feed the text through `check_sudo_policy` in Git bash on the hub, as a rerun. The `linux` mode also feeds `ss -ltnuH`
through `parse_listeners`, the Listener check's parser, as a format check only: each line must parse and name its
Netid and port. A listener does not fail it, because the firewall is already active and the enable decision of
`check_listeners` applies only when the setup turns the firewall on. The
`windows` mode reads `sshd.exe -T` and saves its `authorizedkeysfile` line. Each text goes in the row's receipt.

`check_package_gates.py` also has a `--red` mode, which each coder row runs on its red receipts before it writes code:
`--red <receipt> [<receipt> ...] [--acs N,N] [--guards N,N] [--acs-if-cli-kept N]`, which must name at least one AC.

- Each AC in `--acs` needs a failed test in one of the named receipts: a pytest `FAILED` line for
  `scripts/tests/test_fleet_usb.py::test_acNN_`, or a Pester `[-]` line that holds `AC-N:`. A run where the AC's tests
  are absent or green fails the check. pytest lines for other files do not count.
- Each AC in `--guards` needs a pytest `PASSED` line for `scripts/tests/test_fleet_usb.py::test_acNN_` and no `FAILED`
  or `ERROR` line for it (A-13). AC-6, AC-7 and AC-12 are pytest tests, because `run_pester.ps1` prints only failed
  Pester tests.
- `--acs-if-cli-kept N` reads both lines of `uk-tree-clean.txt`; a missing line fails the check. Only when both say
  `False` (`install_cli kept: False`, `Install-Cli kept: False`) does AC-N move from `--acs` to `--guards`, because row
  0 then discarded the CLI step in both scripts.
- Red runs use `python -m pytest <file> -q -rA -k <expression>`, so pytest prints a `PASSED` or `FAILED` line for each
  test. Each Pester `Describe` and `It` name starts with its AC id, and each file loads the kit script in a
  `BeforeAll` inside its `Describe`, so a failed load also names its AC.
- `--selftest` also proves that `--red` refuses a receipt with no failure, a failure under another AC id, and a guard
  AC with a failed line, and that it accepts each matching sample.

`check_package_gates.py` has two more modes. `--selftest` prints one `PASS AC-N: <case>` or `FAIL AC-N: <case>` line
for each case, and exits 1 on any `FAIL`.

- `--state` prints the state id (AC-30). The inventory is every path that
  `git status --porcelain=v1 -z --untracked-files=all` names, except the files that the closeout writes after H1-2:
  this plan's `task.md` and `implementation-plan.md`, and the files under `.agent/context/handoffs/`,
  `docs/execution/reflections/` and `docs/execution/metrics.md`. The id is the SHA-256 over `git rev-parse HEAD`,
  then each inventory path in sorted order with the SHA-256 of its bytes (the word `deleted` for a deleted file), then
  `sys.version`. The receipts folder is outside the repository, so it never enters the id.
- `--privacy` (AC-29) scans the added lines of `git diff -U0 <baseline HEAD>`, every untracked file, both plan files,
  and the closeout artifacts (the handoff, the review files, the reflection and the metrics row). The baseline HEAD is
  the commit that row 1 stores in `uk-gates-baseline.json`, so a commit in the middle of the plan drops no line from the
  scan. It reports five classes: an email address that does not contain `noreply` and is not at `example.com`,
  `example.org`, `example.net` or `openssh.com` (sshd_config(5) lists algorithm names in that form, such as
  `ssh-ed25519-cert-v01@openssh.com`); an IPv4 address outside `0.0.0.0/8`, `127.0.0.0/8`, `169.254.0.0/16`, the three RFC
  5737 blocks, `198.18.0.0/15` (RFC 2544, for test networks wider than a /24), `224.0.0.0/4` (multicast) and
  `255.0.0.0/8`; a `C:/Users/`, `C:\Users\`, `/home/` or `/Users/` path whose next segment does not start with `<`, `{`,
  `$`, `%` or `*`; this machine's `USERNAME` or `USER`, `COMPUTERNAME`, host name, or a non-loopback address of its own;
  and a member name from the hub's `fleet_members.json` or from `$env:UK_PRIVACY_TERMS` (semicolon-separated, set by the
  human). A name or term matches as a whole word, ignoring case, when it has at least three characters. The human can
  set `$env:UK_PRIVACY_ALLOW` (semicolon-separated) for a machine value or term that is also a common word. The scan
  skips those values and prints only how many it skipped, never the values. Each hit prints only `file:line` and the
  class, never the text, and any hit exits 1. The no-flag mode runs the same scan, so rows 11 and H1-2 run it, and H2-4
  runs `--privacy` again after the reflection and the metrics row exist.
- Row 1 writes the `--selftest` cases for AC-29 and AC-30 before the code of the two modes, and saves that first run
  to `uk-red-gates-selftest.txt`. Each of those cases must print `FAIL` there; an absent function counts as a failed
  case.

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-22 | integration | `refcheck` and `sanitize --verify` show no failure line that the row 1 baseline lacks; both kit folders have `MANIFEST.md` entries; every AC outside `LIVE_ACS` has a `test_acNN_` test or a Pester `It 'AC-N:` case in this plan's test files. | Local Canon (the fleet-agents plan's gate) | `--selftest` drops a baseline line and requires a failure |
| AC-23 | integration | **Live, human row 12.** A Windows member set up from the drive: `import` reports `full access`, the probe passes, and over SSH the rule shows `Domain, Private` and `LocalSubnet`, `sshd -T` shows `passwordauthentication no`, and the report of WP-U4 is empty. A listed item fails this AC, and the human decides what to do with it (A-4). The row's receipt holds the real `authorizedkeysfile` line, and the Key-auth check's parser accepts it. | Human-approved (findings 2, 3); Research-backed (https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallrule, https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallprofile) | `--selftest`: a rule on `Any`, a probe list with `password`, a missing record, a second enabled allow rule for TCP 22 on `Public`, a rule on local port `1-1024`, and a profile that is off each fail; a missing marker line and an encoded text of 8000 characters or more each fail; the encode round trip gives back the same text |
| AC-24 | integration | **Live, human row 13.** A Linux member: `import` reports `admin helper`, the probe passes, `fleet-admin status` shows the firewall active with only subnet rules for port 22 and an empty SSH rule report, both `sshd -T` lines `no`, and `sudo -n true` fails. On firewalld, `status` shows each member interface's runtime zone with the kit's rule for each subnet and no source outside the target zones, each target zone's runtime target (`--list-all`) and permanent target are `default`, and `--query-service=ssh` is 1 for each target zone both at runtime and with `--permanent`. The real `LC_ALL=C sudo -n -l` text in the row's receipt passes `check_sudo_policy` as a rerun. The real `ss -ltnuH` text passes `parse_listeners` as a format check: every line parses. Its listeners, such as the desktop's mDNS and DHCP client sockets, do not fail this AC, because the enable decision of the Listener check applies only when the setup turns the firewall on; an inactive firewall still fails it. The `pwsh:` line shows a version of 7 or later (WP-U6p); it is installation evidence only, not proof of the member process's `PATH` lookup. | Human-approved (findings 1, 3; review F-022, F-023; D-3 A for the `pwsh:` line); Research-backed (https://firewalld.org/documentation/man-pages/firewall-cmd.html, https://firewalld.org/documentation/zone/connections-interfaces-and-sources.html, https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall-cmd.in, https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall/command.py, https://raw.githubusercontent.com/avahi/avahi/master/avahi-core/socket.c); cases from the advisory read (N1, N2, N6, N13) | `--selftest`: `full=True`, an inactive firewall, two Linux records, an ssh service still present in the permanent config, a source binding in a zone that is not a target zone, a target zone with target `DROP`, a target zone whose `--list-all` shows `target: ACCEPT` while its permanent target is `default`, a runtime zone without the kit's rule, an open `22/tcp` port in a target zone, and an `ss` line that `parse_listeners` cannot read, no `pwsh:` line, and a `pwsh:` line with `6.2.7` each fail; an `ss` text in the real form with `udp UNCONN 0 0 0.0.0.0:5353 0.0.0.0:*`, a DHCP client socket on `0.0.0.0%wlan0:68` and a `tcp` listener on 22, on an active firewall, passes |
| AC-25 | integration | **Live, human row 14.** A macOS member: as AC-24 without the firewall and without `ss`, plus the key line carries `from=`. The `pwsh:` line is installation evidence only, as in AC-24. | Human-approved (findings 1, 3; D-3 A for the `pwsh:` line) | `--selftest`: a key line without `from=` fails; no `pwsh:` line, and a `pwsh:` line with `6.2.7`, each fail |
| AC-29 | integration | `check_package_gates.py --privacy` and its no-flag mode report no hit in the scanned files, by the five classes above, and print only `file:line` and the class. | Local Canon (commit `6e679e9` removed such names; `core/MANIFEST.md:40`, "Holds no hosts or credentials"; `scripts/sanitize.py:24,53` skips `scripts/`, `.agent/context/` and `docs/execution/`, so it cannot catch them); Human-approved (the public-package rule that finding F-010 of the round 1 plan review cites); Research-backed (https://man.openbsd.org/sshd_config); cases from the advisory read (N10) | `--selftest` puts one synthetic sample of each class into a temp copy of each file kind (a tracked-diff line, an untracked file, a plan file, a closeout artifact), built at run time so no sample is in the repository; each must be reported with its class and without its text. A noreply address, `ssh-ed25519-cert-v01@openssh.com`, `127.0.0.1`, `192.0.2.10`, one run-time address from `198.18.0.0/15`, one from `224.0.0.0/4`, `<hub-host>`, `%USERPROFILE%`, `$HOME` and `/home/<user>` must give no hit. In a temp repository, a line added after a mid-plan commit is still reported, because the diff starts at the baseline HEAD. A sample term listed in `UK_PRIVACY_ALLOW` gives no hit, and the output holds the skip count and not the term |
| AC-30 | integration | `check_package_gates.py --state` prints the state id of WP-U8, and H1-6b passes only when the id of the tested tree equals the id at review time. | Research-backed (`core/tools/durable_evidence.py:131-136` compares `tested_state` with `--expected-state`); Human-approved (finding F-011 of the round 1 plan review) | `--selftest`, in a temp repository under the receipts folder: a second byte change to a file that is already modified changes the id, though `git status --porcelain` stays the same; a new untracked file changes the id; a change to an excluded closeout file does not; two runs on the same tree give the same id |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `docs/execution/plans/2026-11-07-usb-kit-hardening/check_package_gates.py` | new | Plan-local gate checker, with `--red`, `--state` and `--privacy` |
| `docs/execution/plans/2026-11-07-usb-kit-hardening/run_pester.ps1` | new | Copied unchanged from the fleet-agents plan |
| `docs/execution/plans/2026-11-07-usb-kit-hardening/check_live.py` | new | Live checks and `--selftest` |
| `.agent/context/known-issues.yaml`, `.agent/context/known-issues.md` | modify | H2-3b: `FLEET-SETUP-MEMBER-UNVERIFIED-INSTALLERS` (A-9) |

### Stop conditions

Execution stops and asks the human when:

1. Row 0 is not done: `.agent/fleet/` still has uncommitted changes.
2. The row 1 baseline is red.
3. A step would run a kit script on a real machine outside a human row.
4. Probe-1 finds nothing to verify for a CLI that the kept step installs.
5. A live row cannot reach the member by key, the probe shows password sign-in still on after the setup, or `import`
   refuses a changed host key (AC-31).
6. A setup on a live member stops on its own check (the clean start or the Root tool check of the Root tool path
   definition, a Public network or no Private or Domain network on a physical adapter, a listener on a first enable,
   no subnet, a runtime zone outside the target zones, a firewalld source, a runtime or permanent zone target other
   than `default`, a name clash, a symlink, a parent folder of the helper, the sudoers policy check or probe of A-18,
   the Key-auth check, an `sshd -T -C` refusal, or the PowerShell step: a found `pwsh` older than 7 or one that does
   not run as the account, an unknown platform, a bad pin file, a failed Parent walk or a symlink on the install root,
   the bin dir or the version folder, a bin dir that a package manager gave to the account (such as Homebrew's
   `/usr/local/bin` on an Intel Mac), an installed `pwsh` that is not a regular root file, or a hash or version that
   differs). The human decides the next step. After a Listener stop, that is the printed enable command at the
   member's screen and a rerun.
7. `fleet.py` or `fleet_usb.py` would need a non-stdlib import.
8. A secret value appears in a receipt or a log.
9. A step would change a file in the source repo.
10. The review cap is reached.
11. Row 3a or row 7a fails. Row 4 waits for row 3a's check of the typed D-1 ruling, and row 8a for row 7a's check of
    the D-2 ruling. Both pass only on a typed A (row 7a also on `not applicable`). A ruling other than A fails that row
    and sends that work back to planning before any code for it is written.
12. The privacy scan (AC-29) reports a hit. The agent removes the literal from text it wrote; a hit in text that
    another author wrote goes to the human. A machine value or term that is also a common word goes to the human too,
    who can set `$env:UK_PRIVACY_ALLOW`.
13. Probe-3 finds no qualifying PowerShell release (A-20, A-21), GitHub's releases list cannot be read, the list is
    longer than the page limit of WP-U6p step 1, or a `rel="next"` link points to another host. The human decides
    whether to wait, or to change the 14-day rule or the page limit at a plan gate.

---

## Out of Scope

| Item | Kind | Deferred-to MEU | Basis |
|------|------|-----------------|-------|
| Constrained Windows admin (JEA) | out-of-scope | — | D-1 brief: Windows keeps a full administrator |
| `setup-member.ps1:41` unchecked installer | out-of-scope | — | A-9: that file belongs to the agent kit. The follow-up is the known issue `FLEET-SETUP-MEMBER-UNVERIFIED-INSTALLERS`, which H2-3b files |
| A macOS `pf` rule | out-of-scope | — | `from=` limits the key; a `pf` change can cut off other services on the human's Mac |
| IPv6 subnets in `from=` and the firewall | out-of-scope | — | The records and the hub use IPv4 (`fleet_usb.py:92-118`). `from=` and the firewall defaults refuse what they don't list |
| shellcheck and PSScriptAnalyzer | out-of-scope | — | Neither is installed on the hub; the static checks here cover the review's findings |
| CI for these tests | out-of-scope | — | The repo has no CI |
| History files that name `agy` | out-of-scope | — | `docs/proposals/2026-11-03-fleet-mvp-outline.md` and one `.agent/context/` handoff are history, outside the scan |
| Closing the source repo's known issue for the residue | out-of-scope | — | A-10 |
| Writing a live installer drive | out-of-scope | — | A human action whenever a new Linux machine comes; AC-19 is tested with mocks |
| `--expect` fingerprint lists, signed records, and signed or hash-checked code on the drive | out-of-scope | — | The scope addition of 2026-11-08: the human compares the printed fingerprints. A hash list or self-check on the same writable drive is no independent reference (round 4 review). The kit does not authenticate the code on the drive; the one-drive trust rule and, for a member that is not equally trusted, a drive that only the hub has written stand in (WP-U7). A `prepare` into a used folder keeps a planted file (round 5 review) |
| PowerShell in `setup-windows.ps1` | out-of-scope | — | D-3 A covers macOS and Linux. A Windows member gets `pwsh` from `setup-member.ps1`, whose unchecked installer is `FLEET-SETUP-MEMBER-UNVERIFIED-INSTALLERS` (A-9) |
| The Linux and macOS sections of `bootstrap.md`, and how a Unix member process finds `pwsh` | out-of-scope | — | Those sections stay empty under the fleet-mvp plan (AC-19 of `test_fleet_bootstrap.py`); the member process on Unix is not defined yet. Its `PATH` lookup (`shutil.which`, `fleet.py:1466`, `:1641-1643`, `:1788-1789`) is a prerequisite that the later plan must check; rows 13 and 14 prove the installation only (WP-U6p) |
| Removing older PowerShell version folders | out-of-scope | — | The link names one version; an old folder is inert and the README's Undo removes it |
| PowerShell on musl, 32-bit ARM or other platforms | out-of-scope | — | The kit supports `x86_64` and `arm64` on glibc Linux and macOS. Another `uname -m` value stops the step with its value; on musl the glibc build fails the version run, so the step stops there and removes the folder |
| Pushing | out-of-scope | — | Only on the human's typed word |

---

## BUILD_PLAN.md Audit

This project does not modify build-plan sections, because this package has no `docs/BUILD_PLAN.md` hub. Task row 15
proves the file is absent:

```powershell
python -c "import pathlib,sys; sys.exit(0 if not pathlib.Path('docs/BUILD_PLAN.md').exists() else 1)" *> $env:RECEIPTS_DIR/build-plan-audit.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/build-plan-audit.txt; exit $code
```

---

## Verification Plan

`$env:RECEIPTS_DIR` is `C:/Temp/agentic-framework/receipts`, and `$env:AGENT_MODEL_REGISTRY_HOME` is `P:/.agent`. Set
both before every row. These commands capture exact evidence, so they use no output filter.

### 1. Baseline, row 1

Records the state id (AC-30), the `refcheck` and `sanitize` failure lines, both selftests, the full pytest gate and
the existing Pester suite, on the clean tree row 0 leaves.

### 2. Targeted tests

```powershell
python -m pytest scripts/tests/test_fleet_usb.py -q -rfE *> $env:RECEIPTS_DIR/uk-targeted.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk-targeted.txt -Tail 25; exit $code
```

```powershell
pwsh -NoProfile -File docs/execution/plans/2026-11-07-usb-kit-hardening/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 scripts/tests/WriteInstallerUsb.Tests.ps1 scripts/tests/SetupMember.Tests.ps1 *> $env:RECEIPTS_DIR/uk-pester.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk-pester.txt -Tail 20; exit $code
```

### 3. Fleet regression

```powershell
python -m pytest scripts/tests/test_fleet_agent.py scripts/tests/test_fleet_hub.py scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_run.py -q -rfE *> $env:RECEIPTS_DIR/uk-fleet-regression.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk-fleet-regression.txt -Tail 25; exit $code
```

### 4. Package gates, compared with the baseline

The no-flag mode also runs the privacy scan (AC-29).

```powershell
python docs/execution/plans/2026-11-07-usb-kit-hardening/check_package_gates.py *> $env:RECEIPTS_DIR/uk-package-gates.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk-package-gates.txt -Tail 30; exit $code
```

### 5. Live checks, after the human rows

`python docs/execution/plans/2026-11-07-usb-kit-hardening/check_live.py <mode>`, for `hello`, `windows`, `linux` and
`macos`, each with a receipt named in its row. The `windows`, `linux` and `macos` rows first run
`fleet_usb.py import` on the drive folder into their own receipt. `--selftest` proves each mode can fail.

### 6. Fresh full gate, H1-2

H1-2 first writes the state id of the tree under test to `uk-state-tested.txt` with `check_package_gates.py --state`.

```powershell
python -m pytest core/tools/tests scripts/tests -q -rfE *> $env:RECEIPTS_DIR/uk-full-pytest.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/uk-full-pytest.txt -Tail 25; exit $code
```

---

## Decision Log

D-1 and D-2 were the human's; the human ruled A on both on 2026-11-08, and their briefs follow the log. A-1 onward
were decided while planning, after a precedent sweep and research.

```yaml
decision_log:
  - id: D-1
    stage: planning
    question: "How does the hub get admin rights on a macOS or Linux member without passwordless sudo for every command?"
    resolution: human
    class: governance-value
    chosen: "A — USER_EXPLICIT 2026-11-08: recoomendations for D-1 D-2 accepted (relayed by the coordinator; the recommendation was A for both). Option A: a root-owned helper with fixed verbs, a sudoers rule that allows only that helper without a password, and a clean environment for it (env_reset, !env_keep, secure_path, bash -p, env -i)"
    source_tag: Human-approved
    precedents: [".agent/fleet/usb/setup-unix.sh:105-116 — today's sudoers block", ".agent/fleet/install-usb/README.md:116-125 — the admin steps the hub runs after setup"]
    research: { engine: native, sources: ["https://www.sudo.ws/docs/man/sudoers.man/ — a command with no argument list allows any arguments; argument wildcards are unsafe", "https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudoers.man.in — Defaults! lines, env_reset, env_keep, secure_path, SETENV", "https://raw.githubusercontent.com/sudo-project/sudo/main/plugins/sudoers/display.c — what sudo -l prints", "https://manpages.debian.org/bookworm/apt/apt.conf.5.en.html — APT_CONFIG and DPkg::Pre-Invoke", "https://gtfobins.github.io/gtfobins/apt-get/ — apt-get under sudo with free arguments gives a root shell", "https://gtfobins.github.io/gtfobins/dnf/ — dnf can install a crafted local package"] }
    reasoning: "How much root the hub holds on a member is a governance value, so the human decides; row 3a checks the typed ruling. After the ruling, the round-3 corrections made option A stricter, not different: the rule gained NOSETENV:, the Defaults! line gained !env_check, A-18 now stops on any other runas or command-specific line and on a later command entry, and setup probes that sudo refuses LD_PRELOAD. The access granted is the same, so the option stays as ruled. See the brief."
  - id: D-2
    stage: planning
    question: "If either setup script keeps the CLI install step, how does the kit check what it installs?"
    resolution: human
    class: governance-value
    chosen: "A — USER_EXPLICIT 2026-11-08: recoomendations for D-1 D-2 accepted (relayed by the coordinator; the recommendation was A for both). Option A: download each installer to a file, run it, then verify the installed binary before the record is written, after Probe-1"
    source_tag: Human-approved
    precedents: ["working-tree .agent/fleet/usb/setup-unix.sh:122-131 — a download piped into a shell", "working-tree .agent/fleet/usb/setup-windows.ps1:28-44 — download and run with no check", ".agent/fleet/install-usb/README.md:23-40 — the image is checked before use"]
    research: { engine: native, sources: ["https://code.claude.com/docs/en/setup — signed release manifest and code-signed binaries", "https://github.com/openai/codex/releases — release assets", "https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations — attestations"] }
    reasoning: "Which install route the kit trusts is a governance value, so the human decides; row 7a checks the typed ruling. It applies if either setup script keeps the step (row 0). See the brief."
  - id: A-1
    stage: planning
    question: "Does the retired CLI's name leave only CAPABILITY_TOOLS, or FORBIDDEN_COMMANDS too?"
    resolution: autonomous
    class: two-way
    chosen: "Both constants"
    source_tag: Local Canon
    precedents: ["the source repo's tests/tooling/test_retired_surfaces_absent.py — RESIDUE holds the word and the framework group scans core and .agent", ".agent/fleet/fleet.py:69-72,252,265-267,493"]
    research: { engine: none, sources: ["unavailable — local canon decides; no external fact is in doubt"] }
    reasoning: "The scan refuses the word in either constant, and an allowlist entry would keep a retired name alive. The cost is that a manifest naming that binary is accepted by first word. The CLI is retired, so no member has it. Flagged to the human"
  - id: A-2
    stage: planning
    question: "In which order do the hub and the members take the new fleet.py?"
    resolution: autonomous
    class: two-way
    chosen: "The hub restarts first, then each member updates per bootstrap.md Update. An old member is refused with bad_field:capabilities until it updates"
    source_tag: Local Canon
    precedents: [".agent/fleet/bootstrap.md:96-101 — stop, new pairing line, refetch with the hash check, start", ".agent/fleet/fleet.py:487-497 — an unknown capability key is refused"]
    research: { engine: none, sources: ["unavailable — local canon decides"] }
    reasoning: "Members fetch fleet.py from the hub, so the hub must serve the new file first. The refusal is short and names its cause. Flagged to the human"
  - id: A-3
    stage: planning
    question: "Does the Windows member's key line get from= too?"
    resolution: autonomous
    class: two-way
    chosen: "No. Windows keeps its LocalSubnet firewall rule on the Domain and Private profiles"
    source_tag: Local Canon
    precedents: [".agent/fleet/usb/setup-windows.ps1:71-94 — the rule and both key files"]
    research: { engine: native, sources: ["https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule — LocalSubnet and Profile"] }
    reasoning: "The firewall already gives the network limit on Windows, and the key goes into two files there, one shared by every administrator. One limit in one place is simpler to undo"
  - id: A-4
    stage: planning
    question: "What happens to another port 22 firewall rule that exists already?"
    resolution: autonomous
    class: two-way
    chosen: "The setup reports it by name and does not delete it, on ufw, firewalld and Windows, under the SSH rule report (Named definitions). On ufw and firewalld every other rule that may reach port 22 is listed with a neutral line, because the kit does not compare source sets; Windows lists only a rule that its subnet test proves broader. Windows reads the active policy store, so a Group Policy rule counts, and a firewall profile that is off is reported too. Two things are the kit's own and are replaced: the stock firewalld ssh service in each target zone, and the Windows rule OpenSSH-Server-In-TCP in the local store. check_live.py lists every reported item, and a listed item fails AC-23 or AC-24, so the human decides"
    source_tag: Research-backed
    precedents: [".agent/fleet/usb/setup-unix.sh:54-63 — today's ufw block adds rules only", ".agent/fleet/usb/setup-windows.ps1:72-84 — today's block handles only OpenSSH-Server-In-TCP"]
    research: { engine: native, sources: ["https://manpages.ubuntu.com/manpages/noble/man8/ufw.8.html — rules are listed by ufw status and removed by delete", "https://firewalld.org/documentation/man-pages/firewall-cmd.html — --query-service, --remove-service, --list-ports, --list-services, --info-service and --list-rich-rules", "https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallrule — rules, their filters and profiles; with no policy store it reads the persistent store only", "https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallportfilter — the ActiveStore port conditions", "https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallservicefilter — a rule with no service matches any program or service", "https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallprofile — the ActiveStore profile state"] }
    reasoning: "The human or another tool made that rule, maybe for a reason the kit cannot see. Reporting keeps the setup from removing access the human relies on. A report alone would let the network limit look done while another rule still answers, so the live check fails on it. Flagged to the human"
  - id: A-5
    stage: planning
    question: "Can the setup run over SSH?"
    resolution: autonomous
    class: two-way
    chosen: "No. A console guard refuses an SSH server among the process parents; a walk that loops or ends early passes"
    source_tag: Research-backed
    precedents: [".agent/fleet/usb/README.md:31-32 — each setup starts from a double-click at the machine"]
    research: { engine: native, sources: ["https://www.openssh.com/txt/release-9.8 — per-session sshd-session process", "https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-process — ParentProcessId"] }
    reasoning: "The setup changes the firewall and sshd, so a run over SSH can cut its own session. The kit is a screen tool, so the guard costs nothing in normal use. It fails open on a strange chain so a real console run is never blocked. Its limit is a tmux session started at the screen. Flagged to the human"
  - id: A-6
    stage: planning
    question: "What happens when a member moves to another network?"
    resolution: autonomous
    class: two-way
    chosen: "The subnets in from= and the firewall rules are fixed at setup; the human runs the setup again at the member's screen"
    source_tag: Local Canon
    precedents: [".agent/fleet/usb/README.md:65-66 — a repeat run is safe and rewrites the record"]
    research: { engine: none, sources: ["unavailable — local canon decides"] }
    reasoning: "The records already hold addresses from setup time, so a move already needs a rerun and a new import. Flagged to the human"
  - id: A-7
    stage: planning
    question: "Where does the helper's code live?"
    resolution: autonomous
    class: two-way
    chosen: "A new tracked file .agent/fleet/usb/fleet-admin.sh in MEMBER_FILES, installed by setup-unix.sh"
    source_tag: Local Canon
    precedents: [".agent/fleet/usb/fleet_usb.py:26-30 — MEMBER_FILES and the LF rule for .sh"]
    research: { engine: none, sources: ["unavailable — local canon decides"] }
    reasoning: "A separate file can be read, tested and diffed by itself, and it gets the LF rule with no new code. A heredoc inside setup-unix.sh would hide it"
  - id: A-8
    stage: planning
    question: "Does import --no-test skip the probe?"
    resolution: autonomous
    class: two-way
    chosen: "Yes, with the admin check"
    source_tag: Local Canon
    precedents: [".agent/fleet/usb/fleet_usb.py:218-229 — --no-test skips the connection test"]
    research: { engine: none, sources: ["unavailable — local canon decides"] }
    reasoning: "--no-test means no SSH call to the member: no admin check and no probe. The TCP reachability check that picks the address (fleet_usb.py:194) still runs"
  - id: A-9
    stage: planning
    question: "setup-member.ps1:41 downloads and runs an installer with no check. Fix it here?"
    resolution: autonomous
    class: two-way
    chosen: "No. File the known issue FLEET-SETUP-MEMBER-UNVERIFIED-INSTALLERS at H2-3b"
    source_tag: Local Canon
    precedents: [".agent/fleet/setup-member.ps1:41-43", "docs/execution/plans/2026-11-04-fleet-agents/ — the plan that owns that file"]
    research: { engine: none, sources: ["unavailable — scope decision on local files"] }
    reasoning: "setup-member.ps1 is the agent kit, not the USB kit, and the D-2 ruling should inform its fix. A known issue keeps the gap visible"
  - id: A-10
    stage: planning
    question: "Fedora Workstation's default zone keeps high ports open. Does the kit close them, and does it close the source repo's issue?"
    resolution: autonomous
    class: two-way
    chosen: "Neither. In each target zone the kit adds its rich rules and removes only the stock ssh service; it leaves every other port and service as it found them, runs no --reload, and reports any other rule that opens port 22 (A-4). The source repo's known issue for the residue is closed in that repo"
    source_tag: Research-backed
    precedents: [".agent/fleet/usb/setup-unix.sh:54-63 — the kit touches only port 22 today"]
    research: { engine: native, sources: ["https://firewalld.org/documentation/man-pages/firewall-cmd.html — zones, services and --permanent; --reload loses runtime-only changes", "https://firewalld.org/documentation/concepts.html — separate runtime and permanent configurations"] }
    reasoning: "Closing a desktop's zone ports can break the human's own services, which the review did not ask for. A reload would also drop the human's runtime-only changes, so each change is made at runtime and with --permanent. The stock ssh service is the kit's own port, and the rich rules replace it. This repo cannot change the source repo's register"
  - id: A-11
    stage: planning
    question: "May the setup enable a Linux firewall that was off?"
    resolution: autonomous
    class: two-way
    chosen: "Yes, after its SSH rules are in place, unless the Listener check finds a non-loopback listener other than TCP 22; then it names each socket, prints the command that turns the firewall on (sudo ufw enable, or sudo systemctl enable --now firewalld) and stops before enabling, because the kit does not prove which traffic the firewall keeps. The human checks those services, runs that command at the screen and runs the setup again; the rerun finds the firewall active, so the Listener check does not run. The check runs only on this first enable, and the live check reads the ss output only for its form. For a stopped firewalld, the rules go in with firewall-offline-cmd (no --permanent; the service is removed with --zone=Z --remove-service-from-zone=ssh), then the listener check runs, then systemctl enable --now firewalld, then the runtime zones are resolved again, then the runtime and permanent checks"
    source_tag: Research-backed
    precedents: [".agent/fleet/usb/setup-unix.sh:54-63 — today's block acts only when ufw is active"]
    research: { engine: native, sources: ["https://manpages.ubuntu.com/manpages/noble/man8/ufw.8.html — enable applies the default deny for incoming", "https://firewalld.org/documentation/man-pages/firewall-cmd.html — firewall-cmd returns NOT_RUNNING (252) when the daemon is stopped", "https://firewalld.org/documentation/man-pages/firewall-offline-cmd.html — the client for a stopped daemon; --remove-service-from-zone is the zone form, and --remove-service is a lokkit option for the default zone", "https://firewalld.org/documentation/zone/connections-interfaces-and-sources.html — NetworkManager binds a connection's zone at runtime", "https://raw.githubusercontent.com/avahi/avahi/master/avahi-core/socket.c — the IPv4 mDNS socket binds UDP 5353 on the wildcard address", "https://documentation.ubuntu.com/security/security-features/network/firewall/ — ufw is available in Ubuntu but disabled by default", "https://man7.org/linux/man-pages/man8/ss.8.html — -l, -t, -u, -n and -H", "https://git.launchpad.net/ufw/plain/conf/before.rules — ufw keeps UDP 5353 open only to 224.0.0.251, so a port alone does not prove a service", "https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/public.xml — the services of the stock public zone", "https://raw.githubusercontent.com/firewalld/firewalld/main/config/services/dhcpv6-client.xml — UDP 546 only to fe80::/64", "https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/dmz.xml — a stock zone without dhcpv6-client"] }
    reasoning: "Finding 3 asks for the firewall. A default deny would cut off a service the human runs, and a port number alone does not prove that the firewall keeps a service's traffic (address, family and zone matter), so the setup stops on any listener but TCP 22. A desktop's mDNS or DHCP client socket stops it too. The stop guards only the change that the setup would make; once the human has turned the firewall on, those sockets are the human's accepted state, so a rerun and the live check pass with them, and the live check still fails a firewall that is not active. firewall-cmd cannot change a stopped daemon, so the offline client writes the permanent config first. The runtime zones are not known until the daemon runs, so they are resolved again after the start. Flagged to the human"
  - id: A-12
    stage: planning
    question: "In which order do the hardening steps run?"
    resolution: autonomous
    class: two-way
    chosen: "Guard, retire the old record (by name and by this machine's host key; a name clash stops), packages, the sudoers policy check, helper and sudoers, sshd running, firewall rules before enable, the key line, the key-auth check, password off with its checks, the CLI step, the fingerprint, the new record. Windows runs the guard, retires the old record the same way, then runs keys and the key-auth check before the marked block and the check before the restart"
    source_tag: Research-backed
    precedents: ["finding 3 — an order that cannot lock the admin out", ".agent/fleet/usb/setup-windows.ps1:86-94 — keys today come after the firewall"]
    research: { engine: native, sources: ["https://man.openbsd.org/sshd.8 — -t and -T", "https://www.freedesktop.org/software/systemd/man/latest/systemctl.html — try-reload-or-restart"] }
    reasoning: "Each step that can refuse a sign-in runs only after the hub's key path works, and each config change is checked before sshd uses it. The old record goes first, so a failed rerun leaves nothing for import to trust. Password off applies to every user of the member, so it is flagged to the human"
  - id: A-13
    stage: planning
    question: "Must the characterization and static-guard tests fail first?"
    resolution: autonomous
    class: two-way
    chosen: "No. AC-12 pins today's behavior, and AC-6 and AC-7 guard properties the kit likely has already (ASCII text, a 5.1 parse, no address or mail literal). Each is green on its first run; row 3 records that run, and the red checker requires them to pass, not fail"
    source_tag: Local Canon
    precedents: ["core/.agent/workflows/tdd-implementation.md — tests are the specification"]
    research: { engine: none, sources: ["unavailable — local canon decides"] }
    reasoning: "A characterization or guard test that fails first would mean the code is already wrong, and that would be a finding in itself. Its job is to fail when later rows change behavior they should keep. If one of them is red on its first run, row 3 stops and the plan records the defect"
  - id: A-14
    stage: planning
    question: "Which bash do the tests use on the hub?"
    resolution: autonomous
    class: two-way
    chosen: "Git for Windows' bash, found from the Git root by the locator in Named definitions, never WSL; missing bash fails on Windows; the 5.1 parse is skipped off Windows with a reason"
    source_tag: Local Canon
    precedents: ["the hub's Git for Windows install — the README's Git Bash step at .agent/fleet/install-usb/README.md:25", "the hub's Git for Windows install — git.exe is in cmd/ and ucrt64/bin/, bash.exe is in bin/ and usr/bin/, and there is no mingw64 folder"]
    research: { engine: native, sources: ["https://git-scm.com/docs/git — --exec-path prints the folder of the git programs"] }
    reasoning: "WSL's bash runs in another file system and may be absent or stopped. Git bash is already a hub requirement. A fixed parents[1] step from git.exe works for cmd/ but not for ucrt64/bin/ or mingw64/bin/, so the locator walks up to the Git root"
  - id: A-15
    stage: planning
    question: "Which Windows profiles does the SSH rule use, and does the setup change a network's category?"
    resolution: autonomous
    class: two-way
    chosen: "Domain and Private. A Public network on a physical adapter stops the setup, and so does no Private or Domain network on one. A Public network on another adapter, such as a Hyper-V or WSL switch or a host-only adapter, is printed and does not stop. The category is never changed"
    source_tag: Research-backed
    precedents: [".agent/fleet/usb/setup-windows.ps1:71-84 — today's rule on every profile", ".agent/fleet/usb/setup-windows.ps1:108-110 — the record's addresses already leave out vEthernet"]
    research: { engine: native, sources: ["https://learn.microsoft.com/en-us/powershell/module/netconnection/get-netconnectionprofile — NetworkCategory values and InterfaceIndex", "https://learn.microsoft.com/en-us/powershell/module/netadapter/get-netadapter — -Physical"] }
    reasoning: "Public is the profile Windows uses for untrusted networks, so answering there is the defect. A virtual switch can show as Public, and the SSH rule keeps port 22 closed on it, so stopping there would block a safe setup. Choosing the category is the human's call about the network"
  - id: A-16
    stage: planning
    question: "How is password sign-in turned off safely?"
    resolution: autonomous
    class: two-way
    chosen: "Unix: a key-auth check with sshd -T -C before any sshd config change, then the drop-in 01-fleet-usb.conf, sshd -t and sshd -T -C. Before it writes, the setup saves the old drop-in's bytes, owner and mode. A failure before the reload puts them back, or removes the new file when there was no old one, runs sshd -t, and makes no reload. A failed reload does the same restore and reloads once more. After a reload passes, a later failure keeps the drop-in. Windows: the same key-auth check with sshd.exe -T -C, then the marked block at the top of sshd_config and sshd.exe -T -C. A failure before the restart writes the old bytes back. A failed Restart-Service writes them back and restarts once more. After a restart passes, a later failure keeps the block"
    source_tag: Research-backed
    precedents: [".agent/fleet/usb/setup-unix.sh:42-90 — sshd setup on both systems", ".agent/fleet/usb/README.md:65-66 — a repeat run is safe"]
    research: { engine: native, sources: ["https://man.openbsd.org/sshd_config — the first value obtained wins; Include; AuthenticationMethods; AuthorizedKeysFile; StrictModes; AllowUsers and the other account filters", "https://man.openbsd.org/sshd.8 — -C with user, host, addr, laddr and lport; -T also runs the -t checks; from= in authorized_keys", "https://raw.githubusercontent.com/openssh/openssh-portable/master/misc.c — safe_path(), the strict-modes owner and mode rule", "https://www.openssh.com/txt/release-8.7 — ChallengeResponseAuthentication is an alias", "https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration — the config file"] }
    reasoning: "A drop-in that sorts first wins over the shipped ones and is one file to undo. The checks catch a config that sshd would refuse before it is used. A repeat run must not lose the last good drop-in, so the rollback restores it. After a reload the running sshd already uses the new file, so a restore with no reload would leave the file and sshd in disagreement. Password off with no working key path would lock the hub out, so the key-auth check comes first"
  - id: A-17
    stage: planning
    question: "Where does the image check get gpg and the key?"
    resolution: autonomous
    class: two-way
    chosen: "gpg from PATH, else usr/bin/gpg.exe under the Git root that Find-GitRoot finds by the Git root rule (Named definitions); the key from -KeyFile or the Ubuntu keyserver, in a temp GNUPGHOME; Probe-2 tests the fetch"
    source_tag: Local Canon
    precedents: [".agent/fleet/install-usb/README.md:25-36 — Git Bash's gpg, a private GNUPGHOME, the keyserver and fingerprint", "the hub's Git for Windows install — gpg.exe is in the Git root's usr/bin, and that root has no mingw64 folder"]
    research: { engine: native, sources: ["https://ubuntu.com/tutorials/how-to-verify-ubuntu — key and verify steps", "https://git-scm.com/docs/git — --exec-path"] }
    reasoning: "The README's manual steps already work on the hub, so the script does the same steps itself. The kit cannot call a Python test helper, so the rule has two implementations, the Python locator and Find-GitRoot. AC-19 and AC-28 test both on the same three layouts, so a drift between them fails a test"
  - id: A-18
    stage: planning
    question: "What does the setup do when the member's sudoers policy already lets the account keep or set variables?"
    resolution: autonomous
    class: two-way
    chosen: "Before it writes the sudoers file it captures LC_ALL=C sudo -l -U <user>, because sudo translates the headers and wraps long lines only on a terminal. It reads the three sections that sudo prints: Matching Defaults entries; Runas and Command-specific defaults; and User ... may run the following commands. It splits each Defaults line on commas that are outside double quotes and not after a backslash, and compares whole tokens, never substrings. It stops with no change, and names the line, on any of these. (1) In a general line: the flag !env_reset, the flag setenv, or an env_keep= or env_keep+= value with an entry that is *, BASH_ENV, ENV or PATH, that starts with LD_, DYLD_, APT_, PYTHON or PERL, or that ends in * and covers one of those names. (2) Any Runas and Command-specific line other than the kit's own Defaults! line, because sudo matches a Defaults! selector by path, directory, wildcard or alias, and the kit does not prove another line unrelated. (3) A SETENV: tag on a command line; NOSETENV: is another tag and passes. (4) Output with no known header and no not-allowed line. (5) On the second read, a last command entry that is not (root) with exactly the tags NOPASSWD and NOSETENV and the command /opt/fleet-admin/fleet-admin, because the last matching rule wins and a command of ALL implies SETENV without printing it. The tags are compared as a set, in any order, because sudo prints them in its own order, NOSETENV: NOPASSWD: (sudoers_format_cmndspec in fmtsudoers.c), and not in the file's order. The kit's own Defaults! line is compared token by token with double quotes and backslashes removed, because sudo prints a value with no space unquoted and with each colon escaped, so a rerun passes. An env_keep-= value passes, and so do stock env_keep names such as HOME, MAIL, LS_COLORS, LC_* and SSH_AUTH_SOCK. The line User ... is not allowed to run sudo passes this first read, but sudo then hides every Defaults line. So the setup reads the same output again right after install_sudoers, with the same rules, when the kit's rule makes sudo show those lines. Then, as the account, it runs LC_ALL=C sudo -n LD_PRELOAD=/nonexistent.so /opt/fleet-admin/fleet-admin no-such-verb, which must print sudo's not-allowed line for LD_PRELOAD. A stop on the second read or the probe removes the file that install_sudoers wrote. Rows 13 and 14 feed each member's real output through the parser and confirm the printed form"
    source_tag: Research-backed
    precedents: [".agent/fleet/usb/setup-unix.sh:105-116 — the sudoers block is checked with visudo before it is installed"]
    research: { engine: native, sources: ["https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudoers.man.in — SETENV lets -E turn env_reset off; env_keep and env_check; Defaults! lines follow the general ones, and a rule's tags follow both; the last matching rule wins; ALL implies SETENV", "https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/sudoers.c — update_defaults(SETDEF_CMND) runs before the lookup; with setenv off, -E is refused and each VAR=value is checked", "https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/lookup.c — the matching rule's SETENV or NOSETENV tag sets setenv after the Defaults lines", "https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/env.c — validate_env_vars refuses a variable outside env_check and env_keep, with the not-allowed line", "https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/gram.y — a command of ALL implies SETENV", "https://man7.org/linux/man-pages/man8/ld.so.8.html — LD_PRELOAD is ignored only in secure-execution mode, which sudo's root process is not in", "https://raw.githubusercontent.com/sudo-project/sudo/main/plugins/sudoers/display.c — the section headers, translated; the Defaults! and Defaults> forms; no wrap off a terminal; the not-allowed line that clears the Defaults output", "https://raw.githubusercontent.com/sudo-project/sudo/main/plugins/sudoers/fmtsudoers.c — sudoers_format_default quotes only a value with a space; other values take the SUDOERS_QUOTED escapes of parse.h; sudoers_format_cmndspec prints the SETENV or NOSETENV tag before the NOPASSWD or PASSWD tag", "https://raw.githubusercontent.com/sudo-project/sudo/main/plugins/sudoers/parse.h — SUDOERS_QUOTED holds the colon", "https://manpages.debian.org/bookworm/apt/apt.conf.5.en.html — APT_CONFIG"] }
    reasoning: "The kit cannot know why another rule keeps those variables, so it does not edit that rule. NOSETENV: and the kit's Defaults! line carry the clean environment in sudo itself; the checks stop wherever another line could undo them and the kit cannot prove it does not, and the probe asks sudo directly. A general env_keep line cannot reach the helper past the kit's own !env_keep, so that stop is stricter than the sudoers rule needs; it is kept because a bad general line tells the human to look at the policy, and it costs a stock machine nothing. A substring match would stop every rerun and many stock machines, so the match is on whole tokens. The stock samples are written from the sources and not from a live machine, so the live rows check them. The human fixes the policy and runs the setup again. Flagged to the human"
  - id: D-3
    stage: planning
    question: "How does PowerShell get onto new fleet members, which the human asked for on 2026-11-14?"
    resolution: human
    class: governance-value
    chosen: "A — USER_EXPLICIT 2026-11-14: A. The human first typed 'add PowerShell to the fleet requirments to be deployed on new members'; the coordinator proposed adding a step to this parked plan's setup-unix.sh that installs the newest stable PowerShell release at least 14 days old, checked against its SHA-256, with one more plan-review round, landing after row 0; the human typed 'A'"
    source_tag: Human-approved
    precedents: [".agent/fleet.json:4 — requires python, pwsh and claude", ".agent/fleet/fleet.py:1641-1643,1788-1789 — kit and agent jobs refuse with tool_missing:pwsh", ".agent/fleet/setup-member.ps1 — Windows members get pwsh there"]
    research: { engine: native, sources: ["https://learn.microsoft.com/en-us/powershell/scripting/install/alternate-install-methods — the Linux binary archive", "https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-macos — the macOS binary archive", "https://github.com/PowerShell/PowerShell/releases — release notes list each asset's SHA-256"] }
    reasoning: "What a member must run is a governance value of the fleet, so the human decides. The rule's day count and hash check are the ones the human accepted. The plan was approved and parked, so this amendment adds round 7 to the plan loop by the same typed A"
  - id: A-19
    stage: planning
    question: "Where does the PowerShell step install pwsh, and as whom?"
    resolution: autonomous
    class: two-way
    chosen: "As root, from the release tarball, into /opt/microsoft/powershell/<version> on Linux and /usr/local/microsoft/powershell/<version> on macOS, downloaded into <install root>/.dl-<pid>, unpacked with tar --no-same-owner -xzf \"$archive\" -C \"$stage\" into <install root>/<version>.new and then moved; the link is /usr/local/bin/pwsh on both systems. The install root and the bin dir must pass the Parent walk before any write, and the kit never takes over a folder that it did not make. A pwsh that is already present runs only as the account; a version 7 or later is left alone. Root runs only the pwsh that it installed and checked"
    source_tag: Research-backed
    precedents: [".agent/fleet/usb/setup-unix.sh — has_cli and install_cli find a tool for the account and skip what is present", "the Legion CI image (2026-11-14) — the same tarball, hash-checked, under /opt/microsoft/powershell"]
    research: { engine: native, sources: ["https://learn.microsoft.com/en-us/powershell/scripting/install/alternate-install-methods — /opt/microsoft/powershell/7 and a link to pwsh", "https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-macos — /usr/local/microsoft/powershell/7 and /usr/local/bin/pwsh"] }
    reasoning: "Microsoft's steps use those roots. A versioned folder, filled through a .new stage and linked last, means a failed run leaves no link, and a rerun replaces any stage or version folder that it left, so a rerun starts clean. /usr/local/bin keeps the link out of the package manager's /usr/bin and is the same path on both systems. --no-same-owner stops the archive's owner ids from landing on a root-owned tree. Leaving an existing pwsh 7 alone avoids fighting a package-managed install. A pwsh that the account can change is code that the account controls, so root must not run it; the account runs it, as has_cli does. Root writes and runs only under folders that no other user can change, so another user cannot swap a file between the check and the use; a /tmp-style folder or a bin dir that Homebrew gave to the account fails that, and the human decides"
  - id: A-20
    stage: planning
    question: "Where does the setup get the hash that it checks the download against?"
    resolution: autonomous
    class: two-way
    chosen: "prepare reads GitHub's releases list on the hub and writes pwsh-pin.txt; a release qualifies only when each of the four tarballs' asset digest equals the SHA-256 in that release's notes. The member reads the pin from the drive and checks the download with sha256sum or shasum -a 256"
    source_tag: Research-backed
    precedents: [".agent/fleet/usb/fleet_usb.py:66-89 — prepare writes the drive folder from the hub", ".agent/fleet/install-usb/README.md:23-40 — the image is checked before use"]
    research: { engine: native, sources: ["https://docs.github.com/en/rest/releases/releases — each release asset has a digest", "https://github.com/PowerShell/PowerShell/releases — the notes' SHA256 Hashes section"] }
    reasoning: "Two records that the release carries must agree, so a changed asset or a changed note alone is caught. The hub reaches GitHub; a member needs only the download. The pin is computed before any write, so a failed prepare leaves the drive as it was. A signed macOS PKG was weighed and not chosen: it adds a second code path for one system, and the hash check covers both. The drive copy is only as trusted as the drive (WP-U7)"
  - id: A-21
    stage: planning
    question: "Which PowerShell release does prepare pin?"
    resolution: autonomous
    class: two-way
    chosen: "The selection predicate: a release qualifies when it is neither draft nor prerelease, its tag is v<major>.<minor>.<patch>, and its published_at is at least 14 days before now; exactly 14 days qualifies. The qualifying releases of every page of the list (WP-U6p step 1) are ordered by version, compared as an integer triple, highest first. The pin is the first of them that passes A-20. This is the one place that states the predicate; WP-U6p, the Boundary Inventory and AC-32 refer to it by name"
    source_tag: Human-approved
    precedents: ["D-3 — the human accepted 'the newest stable PowerShell release that is at least 14 days old'"]
    research: { engine: none, sources: ["unavailable — the human's words decide; the integer compare follows from tags such as v7.10.0"] }
    reasoning: "A string compare puts 7.10.0 below 7.9.0. PowerShell ships several lines at once (7.4, 7.5, 7.6, 7.7), so the highest qualifying version is the newest line that has aged 14 days, which is what the human asked for"
  - id: A-22
    stage: planning
    question: "How does the setup, which runs as root, find the tools that it runs, when its caller's environment comes through sudo?"
    resolution: autonomous
    class: two-way
    chosen: "The clean start, the Root tool check and the launch form of the Root tool path definition: main re-executes the file under /usr/bin/env -i with an allow-list and /bin/bash -p, refuses a forged marker, fixes PATH to the Root tool path, then proves that each root_tools name resolves to a file in a folder of that path before any other external command. The launchers and the run lines name /usr/bin/sudo and /bin/bash -p. The account side keeps its own lookup through sudo -u \"$user\" -i"
    source_tag: Research-backed
    precedents: ["the Helper definition — #!/bin/bash -p and env -i with a fixed tool path, the same pattern for the helper", ".agent/fleet/usb/setup-unix.sh:1,9,15-21 — today's start, with no PATH line", ".agent/fleet/usb/Setup Mac.command:5 and Setup Linux.desktop:7 — today's bare sudo bash"]
    research: { engine: native, sources: ["https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html — -p: no BASH_ENV or ENV file, no functions from the environment, SHELLOPTS, BASHOPTS, CDPATH and GLOBIGNORE ignored", "https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files.html — BASH_ENV for a non-interactive shell", "https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudoers.man.in — env_reset, secure_path, and the bash functions and variables that sudo removes", "the hub's Git bash 5.3 — the sketch in WP-U6p ran with a hostile PATH folder and exported functions and no fake ran"] }
    reasoning: "sudo's env_reset removes exported functions and BASH_ENV, but with no secure_path the caller's PATH chooses which bash, curl, stat or tar runs as root, and macOS sudo keeps HOME. Walking each system folder adds nothing, because an account that can write /usr/bin already has root. A re-exec with an allow-list is simpler to prove than a list of variables to unset, and the -p check plus the allow-list turn a forged marker into a stop. The Root tool check makes a later regression, such as a function named after a tool, fail loudly. Absolute paths in the launchers keep a fake sudo or bash on the account's PATH from running first. Taking over package-manager folders was weighed and not chosen, as in A-19"
```

The human ruled D-1 and D-2 A on 2026-11-08, and D-3 A on 2026-11-14; rows 3a and 7a check the typed rulings of D-1
and D-2. No row picks an option for the human.
A-1 to A-22 passed the obviousness test. Each is two-way, so the human can reverse any of them at the plan gate, and
the ones a reader might want to change are flagged in User Review Required.

### D-1 — How does the hub get admin rights on a macOS or Linux member?

**Recommendation:** A — a root-owned helper with fixed verbs, a sudoers rule that allows only that helper with no
password, and a clean environment for the helper. The sudoers file holds the rule line, tagged `NOSETENV:`, and one
`Defaults!/opt/fleet-admin/fleet-admin env_reset, !env_keep, !env_check, secure_path=...` line, so sudo refuses `-E`
and any `VAR=value` on the command line, such as `LD_PRELOAD` before the helper's interpreter starts, and passes no
caller variable such as `APT_CONFIG` or `BASH_ENV`. The helper runs as `bash -p` and starts each tool with `env -i` and
an absolute path (see Named definitions, Helper). The hub keeps every admin step the kit's docs ask of it, and a
stolen hub key no longer gives a root shell. **Reversibility:** two-way (one file and one sudoers file).
**Ruling:** A, typed by the human on 2026-11-08 ("recoomendations for D-1 D-2 accepted", relayed by the coordinator).
Row 3a checks it before row 4. The round-3 changes made A stricter, not different (D-1 reasoning).
**Precedents:** `.agent/fleet/usb/setup-unix.sh:105-116` — today's `NOPASSWD: ALL` block;
`.agent/fleet/install-usb/README.md:116-125` — the admin steps the hub runs after setup. **Research:** native;
sudoers(5) — a command with no argument list allows any arguments, argument wildcards are unsafe, a command-specific
`Defaults!` line follows the general ones and a rule's tags follow both, `!env_keep` clears the kept list, and
`secure_path` replaces `PATH`; the sudo 1.9.15p5 source — `NOSETENV` refuses `-E` and `VAR=value`; ld.so(8) —
`LD_PRELOAD` works outside secure-execution mode; sudo's
`display.c` — the sections and forms that `sudo -l` prints; apt.conf(5) — `APT_CONFIG` names a config file that APT
reads first, and `DPkg::Pre-Invoke` runs shell commands; GTFOBins — `apt-get` and `dnf` under sudo with free arguments
give a root shell.

| Option | Source | Pros (vs. rec.) | Cons (vs. rec.) | Verdict |
|--------|--------|-----------------|-----------------|---------|
| A: helper with fixed verbs, one exact sudoers rule, a clean environment (recommended) | https://www.sudo.ws/docs/man/sudoers.man/ | — | — | ✅ |
| B: a second admin account with password sudo; the agent account gets no sudo | https://www.sudo.ws/docs/man/sudoers.man/ | No root path at all from the hub's key | Every admin step needs the human at the machine or a stored password; the install-usb steps can't run from the hub | ⚠️ |
| C: `Cmnd_Alias` rules with argument wildcards for `apt-get`, `systemctl` and `shutdown` | https://gtfobins.github.io/gtfobins/apt-get/ | No new file | Wildcards also match options, so `apt-get` gives a root shell; sudoers(5) warns against them | ❌ |
| D: password sudo for the agent account | https://www.sudo.ws/docs/man/sudoers.man/ | No new file | The hub has no password, so nothing admin works from it unless the password is stored | ❌ |
| E: keep `NOPASSWD: ALL` | `setup-unix.sh:107` | No change | A stolen hub key, or one bad agent step, is root on every member | ❌ |

The limits of A:

- **The sudoers policy.** The rule's `NOSETENV:` tag beats any `setenv` default, and the `Defaults!` line clears the
  kept and checked lists, so no caller variable reaches the helper's interpreter. A later rule for the helper with
  `SETENV:` or `ALL` (sudoers(5) implies `SETENV` for `ALL`) is the last match and wins. So the setup reads
  `LC_ALL=C sudo -l -U <user>` before and right after it writes the file, stops on a general line that keeps or sets
  variables, on any other runas or command-specific line, on `SETENV:`, or on a last entry that is not the kit's, and
  then checks that sudo refuses `LD_PRELOAD=` for the helper (A-18). A stop on the second read or the probe removes
  the file. The kit's own line and stock general lines pass, so a rerun goes through; rows 13 and 14 feed real output
  through the parser. The helper's own `env -i` start of each tool is the second layer. A sudoers policy that a later
  tool changes after setup is outside the kit's view; the admin check still fails `import` when a later `ALL` rule
  matches (Outcomes).
- **The helper's path.** The rule is only as safe as the path it names. An account that can write a parent folder can
  rename `/opt/fleet-admin` and put a script at the sudo path. So the folder must pass the Parent walk (Named
  definitions). The setup stops on a failed walk, and the helper repeats the walk and exits 3 (Helper). A
  member with a writable `/opt` stops at setup until the human fixes the mode.

Windows stays a full administrator under every option. Constrained Windows admin (JEA) is out of scope.

### D-2 — If either setup script keeps the CLI install step, how does the kit check what it installs?

**Recommendation:** A — download each official installer to a file, run it, then verify the installed binary
against the vendor's signature before the setup writes its record. Probe-1 confirms the signer names and keys first.
**Reversibility:** two-way. **Ruling:** A, typed by the human on 2026-11-08 ("recoomendations for D-1 D-2 accepted",
relayed by the coordinator). Row 7a checks it before row 8a. This brief applies if either setup script keeps the step.
**Precedents:** working-tree `setup-unix.sh:122-131` and `setup-windows.ps1:28-44` — the step with no check;
`.agent/fleet/install-usb/README.md:23-40` — the image is checked before use. **Research:** native; the Claude Code
setup docs — a signed release manifest and code-signed Windows and macOS binaries; the Codex releases page and
GitHub artifact attestations — what Probe-1 looks for on Codex.

| Option | Source | Pros (vs. rec.) | Cons (vs. rec.) | Verdict |
|--------|--------|-----------------|-----------------|---------|
| A: download, run, verify the binary (recommended) | https://code.claude.com/docs/en/setup | — | — | ✅ |
| B: drop the CLI step; the hub installs and verifies the CLIs over SSH later | the committed kit at HEAD | The kit stays an SSH-only tool, and the check runs from the hub | One more step per member; the same trust in the installer script | ⚠️ |
| C: pin each installer script's SHA-256 in the kit | — | Checks the script before it runs | The vendors change the scripts without notice, so every change breaks every setup until the kit is updated | ❌ |
| D: keep the step as it is | working tree | No work | A download piped into a shell, and nothing checks what ran | ❌ |

The limit of A: the installer script runs before any check, so A proves what was installed, not what ran. If
Probe-1 finds nothing to check for Codex, execution stops (stop condition 4), and B is the fallback for Codex.

---

## Research References

- The review findings, as the human directed them on 2026-11-07, restated in Goal
- `docs/execution/plans/2026-11-04-fleet-agents/implementation-plan.md`: the peer plan, its gate checker and Pester gate
- https://www.sudo.ws/docs/man/sudoers.man/ and https://www.sudo.ws/docs/man/visudo.man/: command rules, `-c -f`
- https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudoers.man.in: command-specific `Defaults!` lines follow the general ones, and a rule's tags follow both (`NOSETENV` beats a `setenv` default); `env_reset`, `env_keep` (a list that `!env_keep` clears), `secure_path` replaces `PATH`, and `SETENV` lets `-E` turn `env_reset` off; with no `secure_path`, sudo finds a bare command on the caller's `PATH` (A-22)
- https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/sudoers.c, https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/lookup.c, https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/env.c and https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/gram.y: the command Defaults apply before the rule's tags, the not-allowed line for a `VAR=value`, and `ALL` implying `SETENV`; https://man7.org/linux/man-pages/man8/ld.so.8.html: `LD_PRELOAD` is ignored only in secure-execution mode
- https://manpages.debian.org/bookworm/apt/apt.conf.5.en.html: `APT_CONFIG` names a config file that APT reads first, and `DPkg::Pre-Invoke` runs shell commands
- https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html: privileged mode (`-p`) reads no `BASH_ENV` or `ENV` file and imports no functions; the setup's clean start relies on it too (A-22)
- https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files.html: a non-interactive bash reads the file that `BASH_ENV` names, so the launch form starts `/bin/bash -p` (A-22)
- https://gtfobins.github.io/gtfobins/apt-get/ and https://gtfobins.github.io/gtfobins/dnf/: root shells from free arguments
- https://man.openbsd.org/sshd_config, https://man.openbsd.org/sshd.8 and https://man.openbsd.org/ssh_config: first value wins, `Include`, `-t`, `-T`, `from=`, client options
- https://www.openssh.com/txt/release-8.7 and https://www.openssh.com/txt/release-9.8: the alias, `sshd-session`
- https://www.rfc-editor.org/rfc/rfc4252, https://www.rfc-editor.org/rfc/rfc3927 and https://www.rfc-editor.org/rfc/rfc5737: the method list, link-local, test addresses
- https://manpages.ubuntu.com/manpages/noble/man8/ufw.8.html, https://firewalld.org/documentation/man-pages/firewalld.richlanguage.html and https://firewalld.org/documentation/man-pages/firewall-cmd.html: zones, `--permanent` against runtime, what `--reload` and `--runtime-to-permanent` do (the kit calls neither), `--query-service`, `--get-zone-of-interface`, the list options, and the `NOT_RUNNING` exit code 252
- https://firewalld.org/documentation/zone/connections-interfaces-and-sources.html and https://firewalld.org/documentation/concepts.html: NetworkManager binds a connection's zone at runtime; runtime and permanent configs are separate
- https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/public.xml, https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/drop.xml, https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/block.xml, https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/dmz.xml, https://raw.githubusercontent.com/firewalld/firewalld/main/config/services/dhcpv6-client.xml, https://git.launchpad.net/ufw/plain/conf/before.rules and https://git.launchpad.net/ufw/plain/conf/before6.rules: what each stock firewall keeps open, the `DROP` and `%%REJECT%%` targets, and UDP 546 only to `fe80::/64`; https://firewalld.org/2023/04/zone-priorities: a source can classify a packet before an interface
- https://man7.org/linux/man-pages/man8/ss.8.html, https://raw.githubusercontent.com/iproute2/iproute2/main/misc/ss.c and https://man7.org/linux/man-pages/man7/udp.7.html: the `ss` options and output forms, UDP has no listen state
- https://raw.githubusercontent.com/sudo-project/sudo/main/plugins/sudoers/display.c, https://raw.githubusercontent.com/sudo-project/sudo/main/plugins/sudoers/fmtsudoers.c and https://raw.githubusercontent.com/sudo-project/sudo/main/plugins/sudoers/parse.h: what `sudo -l` prints, how it quotes a value, and that it prints the `NOSETENV:` tag before `NOPASSWD:`
- https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudo.man.in: who may use `-U`; `listpw` in `sudoers.man.in` is why `sudo -n -l` works with a `NOPASSWD` rule
- https://raw.githubusercontent.com/openssh/openssh-portable/master/sshkey.c and https://raw.githubusercontent.com/openssh/openssh-portable/master/ssh-keygen.1: the `SHA256:` fingerprint (base64 of the SHA-256 of the key blob, with no `=` padding), which `ssh-keygen -l` prints by default
- https://raw.githubusercontent.com/openssh/openssh-portable/master/misc.c: `safe_path()`, the strict-modes rule; https://man.freebsd.org/cgi/man.cgi?query=stat&sektion=1&format=html: `stat` reports a link itself unless `-L` is given
- https://firewalld.org/documentation/man-pages/firewall-offline-cmd.html: the client for a stopped daemon, which writes the permanent config. Its zone form for a service removal is `--zone=Z --remove-service-from-zone=ssh`; its `--remove-service` is a lokkit option that acts on the default zone only, and the page lists no `--permanent`
- https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall-cmd.in, https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall/command.py and https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall/core/fw_zone.py: `--get-target` works only with `--permanent`; `--list-all` without it prints the runtime `target:` line (`print_zone_policy_info`) of the zone that the daemon loaded at its last start or reload (`get_config_with_settings_dict`)
- https://raw.githubusercontent.com/avahi/avahi/master/avahi-core/socket.c and https://documentation.ubuntu.com/security/security-features/network/firewall/: `avahi-daemon` binds UDP 5353 on the wildcard address; `ufw` is off on a stock Ubuntu install, so a first setup on a desktop stops at the Listener check
- https://www.freedesktop.org/software/systemd/man/latest/logind.conf.html and https://www.freedesktop.org/software/systemd/man/latest/systemctl.html
- https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule and https://learn.microsoft.com/en-us/powershell/module/netconnection/get-netconnectionprofile
- https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallrule, https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallportfilter, https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallservicefilter, https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallprofile and https://learn.microsoft.com/en-us/powershell/module/netadapter/get-netadapter: the active policy store, rule filters, profile state, physical adapters
- https://www.rfc-editor.org/rfc/rfc2544 and https://www.rfc-editor.org/rfc/rfc5771: the benchmark block and multicast block that the privacy scan allows
- https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration
- https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-authenticodesignature
- https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_requires and https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_character_encoding
- https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-process: `ParentProcessId`
- https://learn.microsoft.com/en-us/windows/win32/api/processenv/nf-processenv-needcurrentdirectoryforexepatha: `cmd.exe` searches `.;%PATH%` for a command unless `NoDefaultCurrentDirectoryInExePath` exists, so a drive-local `powershell.cmd` can run in place of Windows PowerShell (WP-U7)
- https://ubuntu.com/tutorials/how-to-verify-ubuntu and https://github.com/gpg/gnupg/blob/master/doc/DETAILS: the image check, `GOODSIG`, `VALIDSIG` (its last field is the primary-key fingerprint), `BADSIG`, `ERRSIG`, `EXPSIG`, `EXPKEYSIG`, `REVKEYSIG` and `NO_PUBKEY`
- https://git-scm.com/docs/git: `--exec-path`, the start of the Git bash locator
- https://code.claude.com/docs/en/setup, https://github.com/openai/codex/releases, https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations and https://cli.github.com/manual/gh_attestation_verify: Probe-1
- https://support.apple.com/en-us/102360: Developer ID signing on macOS
- https://pester.dev/docs/usage/mocking: mocks for the Windows cases
- https://learn.microsoft.com/en-us/powershell/scripting/install/alternate-install-methods and https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-macos: the binary archive on Linux and macOS, its folders and link (A-19)
- https://github.com/PowerShell/PowerShell/releases and https://docs.github.com/en/rest/releases/releases: the notes' SHA-256 list, each asset's `digest`, `draft`, `prerelease` and `published_at` (A-20, A-21)

## Validation stage contract

| Stage | Command | cwd | Scope | Blocking | Expected |
|---|---|---|---|---|---|
| Static | `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-07-usb-kit-hardening/task.md` | repo root | Task contract | Yes | Pass |
| Targeted | Verification Plan §2 | repo root | `test_fleet_usb.py`, the three Pester files | Yes | Pass |
| Regression | Verification Plan §3 | repo root | The four existing fleet test files | Yes | Pass |
| Package | Verification Plan §4 | repo root | `refcheck`, `sanitize --verify` against the baseline; MANIFEST entries; AC-to-test coverage; the privacy scan (AC-29) | Yes | No new failure; no privacy hit |
| Fresh full | Verification Plan §6 | repo root | `core/tools/tests`, `scripts/tests` | Yes | Pass |
| Runtime | Verification Plan §5 | repo root, on <hub-host>, with the drive folder and the members up | Live members | Yes, for AC-3, AC-23, AC-24, AC-25 | Pass, from the receipts named in each row |

Native shell: PowerShell, with Python 3.14 on <hub-host>. Input identity for evidence is the state id that
`check_package_gates.py --state` prints (AC-30): the SHA-256 over `git rev-parse HEAD`, the sorted pairs of path and
SHA-256 of the file bytes for every tracked-modified and every untracked file in the inventory, and `sys.version`.
A byte change in a file that is already modified changes the id, although `git status --porcelain` does not change.
H1-2 writes the id to `uk-state-tested.txt` before the full run, H1-6 records it as `tested_state`, and H1-6b
computes it again into `uk-state.txt` and passes that value to `--expected-state`. Intermediate evidence is not
reused: the final review follows one fresh full gate.
