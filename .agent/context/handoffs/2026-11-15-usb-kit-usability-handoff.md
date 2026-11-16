---
date: "2026-11-15"
project: "2026-11-15-usb-kit-usability"
meus: []
status: "in_progress"
action_required: "VALIDATE_AND_APPROVE"
template_version: "2.2"
verbosity: "standard"
plan_source: "docs/execution/plans/2026-11-15-usb-kit-usability/implementation-plan.md"
build_plan_section: "none"
agent: "implementing agent"
reviewer: "codex (cli-dispatch, execution mode, ledger loop exec-2026-11-15-usb-kit-usability)"
predecessor: "2026-11-15-usb-kit-usability-plan-critical-review.md"
---

# Handoff: 2026-11-15-usb-kit-usability-handoff

> **Status**: `in_progress` (implementation and verification done; the live rows wait for the human; awaiting the execution review)
> **Action Required**: `VALIDATE_AND_APPROVE`

---

## Scope

**MEU**: none (`meus: []`). The plan came straight from the human's test of the USB kit on real members.
**Build Plan Section**: none. This package has no `docs/BUILD_PLAN.md` hub (row 16).
**Predecessor**: the plan review, `.agent/context/handoffs/2026-11-15-usb-kit-usability-plan-critical-review.md`.
Round 3, the cap, returned `changes_required` (H13, H14, H15, L02). The human then typed "just fix them and
run exectution" (USER_EXPLICIT, 2026-11-15). The four findings were fixed in the plan, and execution started
without a fourth plan round, so this review also checks those fixes (`task.md`, Round-cap ruling).

The plan replaces `docs/execution/plans/2026-11-07-usb-kit-hardening/`, which was never executed and never
committed. No row read, edited or committed that folder. The scope is the human's ruling of 2026-11-15:
usability with full admin access, and no hardening.

**What changed:**

- **WP-K0, the plan-local checks.** `check_kit.py` (backup, gate baseline, `--red`, `--pytest`, `--gates`,
  `--privacy`, `--state`, `--live`, `hub`, `--selftest`) and `run_pester.ps1` live in the plan folder.
  `--selftest` proves that each mode can fail (57 of 57 cases). Row 1 saved the D-1 backup with its sha256 list.
- **WP-K1, the record always reaches the drive.** Both setup scripts write `members/<name>.json` on every exit
  path (ok, a failed step, an interrupt, a cancelled elevation), as checkpoints and then one final write. The
  record is v2: `run_id`, steps, tools and `delivery`. The Name rule is the same in bash and PowerShell.
  `read_record` reads v1 and v2. `import` reports a failed step and skips a record with no host key.
  The Windows User `Path` gets `%USERPROFILE%\.local\bin` once.
- **WP-K2, elevation on Ubuntu.** A dangling `/usr/bin/sudo` link is repaired with `pkexec update-alternatives
  --auto sudo` before the elevation chain. The chain then tries `sudo`, `sudo-rs` and `pkexec`, with `--for-user`
  and `--run-id`. The Account's commands run with `runuser` (Linux) or `sudo -u … -H` (macOS) and a clean
  environment. No launcher or guide runs the script with `sudo bash`.
- **WP-K3, the prerequisites.** Linux (apt, dnf), macOS (Homebrew as the Account, then `pwsh`) and Windows
  (winget for Git, Python 3.14 and PowerShell) install git, PowerShell, Python, uv, Claude Code and Codex, from
  a minimal `PATH`.
- **WP-K4, the record goes to the hub.** `fleet_usb.py prepare` makes and reuses a token file and writes
  `hub.txt`. `fleet_usb.py receive` takes `POST /v1/usb-record` on port 8771 and checks the token, the size and
  the record. Each member sends its record with `curl` to each URL in turn and stops at the first 200. The drive
  copy stays the fallback, with `delivery` `pending`, `sent` or `failed`.
- **WP-K5, RustDesk.** `prepare` reads the latest RustDesk release, checks it and downloads the six assets
  with their sha256 into `rustdesk/` and `rustdesk.txt`. Each member with a desktop installs RustDesk, waits for
  the service, sets the ID server and key (with a TOML fallback) and records its id. `import` sets a RustDesk
  password from a mode-600 file through ssh standard input and prints where the file is.
- **WP-K6, docs and known issues.** `usb/README.md` gives the hub steps, the link to the human's ID-server guide
  (https://matbanik.info/hobbies/systems/posts/rustdesk-server-on-windows-without-docker/), the 8771 firewall
  line and the `bash` terminal lines. `bootstrap.md`, `install-usb/README.md` and `core/MANIFEST.md` match. Six
  known issues are filed through `issue_triage.py` and rendered.
- **WP-K7, the live rows (11a and 12 to 15)** change the hub or a real member. They wait for the human, and
  none of them ran (Deferred Items).

---

## Acceptance Criteria

| AC | Type | Description | Source | Test(s) | Status |
|----|------|-------------|--------|---------|--------|
| AC-1 | unit | `setup-unix.sh`, run as a file under bash with stub commands and `FLEET_ROOT` set, writes `members/<name>.json` on every exit path: all steps ok (exit 0, `ok` true, `fina … | Human-approved (2026-11-15: "nothing is being written back") | `scripts/tests/test_fleet_usb.py`: `test_ac01_all_steps_ok_writes_a_final_record_and_checkpoints`, `test_ac01_a_failed_step_ends_that_step_and_the_later_steps_still_run` and 3 more | ✅ |
| AC-2 | unit | `setup-windows.ps1 -LibraryOnly` with mocked commands: `Invoke-Setup` writes the record when every step is ok, when one step throws (that step `failed`, `ok` false, later … | Human-approved | `scripts/tests/SetupWindowsUsb.Tests.ps1`: 'AC-2: writes a final record with ok true when every step is ok', 'AC-2: a step that throws ends failed, ok is false and the later steps still run' and 8 more | ✅ |
| AC-3 | unit | The Name rule gives the same result in bash and PowerShell for `Lab_Mini07`, `--Lab PC__2--`, `___`, a 70-character name and `LAB-PC`, and each result matches `NAME`. | Local Canon (`fleet_usb.py:35`; the name fix made by hand on an earlier member) | `scripts/tests/test_fleet_usb.py`: `test_ac03_the_bash_name_rule` + `scripts/tests/SetupWindowsUsb.Tests.ps1`: 'AC-3: <raw> gives <want>, and the result matches NAME' | ✅ |
| AC-4 | unit | `read_record` accepts a valid v1 record, a valid v2 record, a v2 checkpoint (`final` false), and each `delivery` form (null, `pending`, `sent`, `failed`); refuses a v2 re … | Local Canon (`fleet_usb.py:92-120`) | `scripts/tests/test_fleet_usb.py`: `test_ac04_read_record_accepts`, `test_ac04_read_record_refuses` and 1 more | ✅ |
| AC-5 | unit | Windows PATH fix: `%USERPROFILE%\.local\bin` is in the User `Path` once after two runs, and a tool missing after its install ends `failed` with `not on PATH after install … | Human-approved (the PATH fix made by hand on an earlier member) | `scripts/tests/SetupWindowsUsb.Tests.ps1`: 'AC-5: %USERPROFILE%\.local\bin is in the User Path once after two runs', 'AC-5: a tool missing after its install ends failed with not on PATH after install, and no exception leaves Invoke-Setup' | ✅ |
| AC-6 | unit | `import` of a folder with one good v2 record (`delivery` `failed`, as an offline member leaves it) and one v2 record whose `host_key` step failed: prints the failed step … | Local Canon (`fleet_usb.py:162-201`) | `scripts/tests/test_fleet_usb.py`: `test_ac06_a_good_record_with_a_failed_delivery_imports_and_exits_0`, `test_ac06_a_record_without_a_host_key_is_reported_and_skipped` and 3 more | ✅ |
| AC-7 | unit | With stubs: no `sudo` on `PATH` but `sudo-rs` present → re-run through `sudo-rs` with `--for-user` and `--run-id`; a dangling `sudo` link → the repair runs before the cha … | Research-backed (Ubuntu sudo-rs docs; LP 2130973) | `scripts/tests/test_fleet_usb.py`: `test_ac07_without_sudo_the_script_reruns_through_sudo_rs`, `test_ac07_a_dangling_sudo_link_is_repaired_before_the_chain` and 9 more | ✅ |
| AC-8 | unit | As root, Account commands run with the Account environment: `runuser -u <account> -- env -i …` on Linux and `sudo -u <account> -H env -i …` on macOS, with the exact `PATH … | Research-backed | `scripts/tests/test_fleet_usb.py`: `test_ac08_on_linux_account_commands_run_with_runuser_and_the_account_environment`, `test_ac08_on_macos_account_commands_run_with_sudo_u_h_and_the_account_environment` and 3 more | ✅ |
| AC-9 | unit | Static: `Setup Linux.desktop`, `Setup Mac.command` and `usb/README.md` hold no `sudo bash`; each launcher runs the script with `bash`. | Human-approved (2026-11-15 sudo report) | `scripts/tests/test_fleet_usb.py`: `test_ac09_no_launcher_and_no_guide_runs_the_script_with_sudo_bash`, `test_ac09_each_launcher_runs_the_script_with_bash` | ✅ |
| AC-10 | unit | Linux with stubs, started from a minimal `PATH` (`/usr/bin:/bin` plus the stub folder): the apt branch installs the package list with the lock timeout; the dnf branch its … | Human-approved ("No powershell, git etc are being loaded") | `scripts/tests/test_fleet_usb.py`: `test_ac10_the_apt_branch_installs_the_package_list_with_the_lock_timeout`, `test_ac10_the_dnf_branch_installs_its_list` and 9 more | ✅ |
| AC-11 | unit | Windows with mocks: winget runs for the three ids; `0x8A15002B` counts as `ok`; no winget ends `packages` and `pwsh` `failed` with the App Installer detail; a tool that t … | Human-approved | `scripts/tests/SetupWindowsUsb.Tests.ps1`: 'AC-11: the step list puts packages after account and pwsh and uv before claude, and pwsh, uv, claude and codex need account', 'AC-11: winget installs Git.Git, Python.Python.3.14 and Microsoft.PowerShell with -e --silent and both agreement flags' and 10 more | ✅ |
| AC-12 | unit | macOS with stubs, from a minimal `PATH`: the order is `admin_rights`, `homebrew`, `pwsh`; `homebrew` runs as the Account; `pwsh` runs `brew install powershell` (no `--cas … | Research-backed (Homebrew install docs; `core/.agent/docs/macos-setup.md` §8) | `scripts/tests/test_fleet_usb.py`: `test_ac12_the_order_is_admin_rights_homebrew_pwsh`, `test_ac12_homebrew_runs_as_the_account_with_a_noninteractive_installer` and 6 more | ✅ |
| AC-13 | unit | `prepare` with a temp home: makes and reuses the token file, writes `hub.txt` with the `--hub-url` URLs or the computed ones, and never prints the token. | Human-approved (2026-11-15: "sending some kind of message that can reviewed on [the hub]") | `scripts/tests/test_fleet_usb.py`: `test_ac13_prepare_makes_the_token_file_and_hub_txt_with_the_given_urls`, `test_ac13_the_computed_urls_skip_loopback_and_link_local_addresses_and_keep_order` and 4 more | ✅ |
| AC-14 | integration | `receive` on an ephemeral port in a thread, with real HTTP requests: a valid record → 200, the file, and a summary line with its `run_id`; wrong token → 403; a 70 000-byt … | Human-approved | `scripts/tests/test_fleet_usb.py`: `test_ac14_a_valid_record_gets_200_a_file_and_a_summary_line_with_its_run_id`, `test_ac14_a_failed_run_is_summarised_with_its_failed_step_ids` and 12 more | ✅ |
| AC-15 | unit | The Unix and Windows send, with a stub `curl`: the drive copy holds `delivery` `pending` before the first POST; tries each URL in order and stops at the first 200; the PO … | Human-approved | `scripts/tests/test_fleet_usb.py`: `test_ac15_each_url_is_tried_in_order_and_the_send_stops_at_the_first_200`, `test_ac15_the_request_carries_the_token_header_the_timeouts_and_the_record_file` and 14 more + `scripts/tests/SetupWindowsUsb.Tests.ps1`: 'AC-15: each URL is tried in order and the send stops at the first 200', 'AC-15: the request carries the token header, the timeouts and the record file, and the token is never printed' and 13 more | ✅ |
| AC-16 | unit | `prepare` with a fixture release and fake downloads: picks the six assets by pattern, writes `rustdesk/` and `rustdesk.txt` with the sha256 lines, saves `fleet_rustdesk.j … | Human-approved (2026-11-15: "include rustdesk setup on each member that has GUI") | `scripts/tests/test_fleet_usb.py`: `test_ac16_prepare_picks_the_six_assets_by_pattern_and_writes_the_rustdesk_file`, `test_ac16_a_tag_with_a_v_gives_the_version_without_it` and 14 more | ✅ |
| AC-17 | unit | Windows `rustdesk` step with mocks: a sha256 mismatch → `failed`, no `msiexec`; a match → `msiexec /qn`, the Ready wait, `--config`, the TOML fallback when the read-back … | Research-backed (RustDesk client deployment docs; RustDesk 1.5.3 `src/core_main.rs`) | `scripts/tests/SetupWindowsUsb.Tests.ps1`: 'AC-17: a sha256 mismatch ends the step failed, naming sha256, and msiexec is never called', 'AC-17: an MSI that is missing from the drive ends the step failed, naming the file, and msiexec is never called' and 23 more | ✅ |
| AC-18 | unit | Unix `rustdesk` step with stubs: no desktop → `skipped`; deb via apt and rpm via dnf; the id from `--get-id` after the Ready wait; `session_type` from `loginctl`. Fresh M … | Research-backed (RustDesk 1.5.3 `privileges_scripts`, `src/platform/macos.rs`) | `scripts/tests/test_fleet_usb.py`: `test_ac18_with_no_desktop_the_step_is_skipped_and_nothing_is_installed`, `test_ac18_a_display_manager_that_is_active_counts_as_a_desktop` and 33 more | ✅ |
| AC-19 | unit | `import` with a fake SSH: makes the password file once (mode 600 on POSIX), reuses it on a second import, sends the password on the fake ssh's standard input, and the pas … | Human-approved | `scripts/tests/test_fleet_usb.py`: `test_ac19_import_makes_the_password_file_once_and_sends_the_password_on_standard_input`, `test_ac19_a_second_import_reuses_the_password_file` and 6 more | ✅ |
| AC-20 | unit | Docs: `usb/README.md` holds the guide URL, the `receive` and `import` lines, the 8771 firewall line and the `bash` terminal lines; `core/MANIFEST.md` names `receive` and … | Human-approved | `scripts/tests/test_fleet_usb.py`: `test_ac20_the_usb_readme_gives_the_hub_steps_and_the_guide_link`, `test_ac20_the_usb_readme_gives_the_firewall_line_for_port_8771` and 8 more | ✅ |
| AC-21 | unit | The six known issues are in `known-issues.yaml`, and `issue_triage.py render --check` passes on the pair. | Local Canon (old plan review findings 5 and 7) | `scripts/tests/test_fleet_usb.py`: `test_ac21_the_six_known_issues_are_in_the_yaml_once_each_and_open`, `test_ac21_the_markdown_lists_the_six_known_issues` and 1 more | ✅ |
| AC-22 | integration | Package gates: `check_kit.py --gates` passes (no new refcheck or sanitize failure, AC-to-test coverage, the Privacy scan). | Local Canon (`2026-11-04-fleet-agents` gates) | `check_kit.py --gates` (row 11b and H1-2), with `check_kit.py --selftest` | ✅ |
| AC-23 | integration | The new mini PC: set up from the drive, its record received over the network, imported with full access, tools present, RustDesk id set (live, row 12). | Human-approved ("I have nother mini pc we will test deployment") | `check_kit.py --live` (live row 12), with `check_kit.py --selftest` | ⏸ not run: human row 12 (`B-12` in `task.md`) |
| AC-24 | integration | The same mini PC, setup run again: `ok` true, no duplicate key line, the RustDesk password unchanged (row 13). | Local Canon (README: "repeating it changes nothing") | `check_kit.py --live` (live row 13), with `check_kit.py --selftest` | ⏸ not run: human row 13 (`B-13` in `task.md`) |
| AC-25 | integration | A member of the other OS family (Windows or Linux, whichever the mini PC is not), named by the human: AC-23's checks (row 14). | Human-approved (both families failed in the human's test) | `check_kit.py --live` (live row 14), with `check_kit.py --selftest` | ⏸ not run: human row 14 (`B-14` in `task.md`) |
| AC-26 | integration | A Mac: AC-23's checks (row 15). | Spec (the kit supports macOS) | `check_kit.py --live` (live row 15), with `check_kit.py --selftest` | ⏸ not run: human row 15 (`B-15` in `task.md`) |

<!-- CACHE BOUNDARY -->
<!-- Content above this line is stable across revision passes (KV cache prefix). -->
<!-- Content below this line changes between passes (evidence, results, corrections). -->

---

## Evidence

### FAIL_TO_PASS

Each row is the red receipt of one implementation row, taken before its change, and its green receipt,
taken after it. Each red receipt has its `check_kit.py --red` check, which needs a failing test for every AC
of the row (records below).

| Test | Red Output (hash/snippet) | Green Output | File:Line |
|------|--------------------------|--------------|-----------|
| `test_fleet_usb.py` AC-1, AC-3, AC-4 (row 2) | 14 failed, 9 passed in 29.17s (`dea2b218…`) | 23 passed in 32.18s (`33e7d8e5…`) | `scripts/tests/test_fleet_usb.py` |
| `SetupWindowsUsb.Tests.ps1` AC-2, AC-3, AC-5 (row 3) | Pester gate FAIL: Result=Failed Passed=0 Failed=17 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (`f783c4ef…`) | Pester gate PASS: Result=Passed Passed=82 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (`6c858ef9…`) | `scripts/tests/SetupWindowsUsb.Tests.ps1` |
| `test_fleet_usb.py` AC-6 (row 4) | 4 failed, 1 passed, 23 deselected in 0.28s (`2cdad5b2…`) | 28 passed in 30.01s (`be28eb4d…`) | `scripts/tests/test_fleet_usb.py` |
| `test_fleet_usb.py` AC-7 to AC-9 (row 5) | 17 failed, 3 passed, 28 deselected in 98.25s (0:01:38) (`3fe95865…`) | 48 passed in 127.60s (0:02:07) (`df57cc08…`) | `scripts/tests/test_fleet_usb.py` |
| `test_fleet_usb.py` AC-10, AC-12 (row 6) | 22 failed, 48 deselected in 164.68s (0:02:44) (`52893a70…`) | 70 passed in 370.42s (0:06:10) (`80b8bd3a…`) | `scripts/tests/test_fleet_usb.py` |
| `SetupWindowsUsb.Tests.ps1` AC-11 (row 7) | Pester gate FAIL: Result=Failed Passed=18 Failed=14 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (`dce0b15d…`) | Pester gate PASS: Result=Passed Passed=97 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (`98ff33b1…`) | `scripts/tests/SetupWindowsUsb.Tests.ps1` |
| `test_fleet_usb.py` AC-13, AC-14 (row 8) | 48 failed, 70 deselected in 1.66s (`14e7a5b6…`) | 118 passed in 361.19s (0:06:01) (`c3dce69d…`) | `scripts/tests/test_fleet_usb.py` |
| `test_fleet_usb.py` + Pester AC-15 (row 9) | 19 failed, 118 deselected in 103.90s (0:01:43) (`4de28df9…`); Pester gate FAIL: Result=Failed Passed=32 Failed=18 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (`4f5dc7a6…`) | 137 passed in 467.08s (0:07:47) (`6803fe29…`); Pester gate PASS: Result=Passed Passed=115 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (`4b2f1556…`) | `scripts/tests/` |
| `test_fleet_usb.py` AC-16, AC-19 (row 10) | 34 failed, 5 passed, 137 deselected in 1.57s (`50cfa9bc…`) | 176 passed in 461.98s (0:07:41) (`30cc790c…`) | `scripts/tests/test_fleet_usb.py` |
| `test_fleet_usb.py` AC-18 + Pester AC-17 (row 10a) | 40 failed, 176 deselected in 342.96s (0:05:42) (`daaa216b…`); Pester gate FAIL: Result=Failed Passed=49 Failed=26 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (`e6e6dffb…`) | 216 passed in 937.31s (0:15:37) (`c178b358…`); Pester gate PASS: Result=Passed Passed=140 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (`2ed662b8…`) | `scripts/tests/` |
| `test_fleet_usb.py` AC-20, AC-21 (row 11) | 10 failed, 3 passed, 216 deselected in 0.91s (`c5df61dd…`) | 270 passed in 978.50s (0:16:18) (`be045f46…`) | `scripts/tests/test_fleet_usb.py` |
| Review round 1 (EA-14): pytest AC-10, AC-18 + Pester AC-2 | 2 failed, 229 deselected in 23.15s (`0b236a99…`); Pester gate FAIL: Result=Failed Passed=75 Failed=1 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (`79f33778…`) | 1 failed, 271 passed in 1033.54s (0:17:13) (`1b82cca6…`); Pester gate PASS: Result=Passed Passed=76 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (`e8af1148…`) | `scripts/tests/` |
| Review round 1 (EA-14): `check_kit.py --selftest`, F-004 | selftest: 58 of 61 cases as expected (`a2fb8e0c…`) | selftest: 61 of 61 cases as expected (`9dc10d2a…`) | `check_kit.py` |

Row 11's green receipt is the last run of the whole `test_fleet_usb.py`; rows 11b and H1-2 ran it again
inside the larger runs. Row 10a's green is also the receipt for EA-9 (a setup-only change, see the points
below). The receipts are in `C:/Temp/agentic-framework/receipts/`; the observations below stand without them.

### Commands Executed

`$env:RECEIPTS_DIR` is `C:/Temp/agentic-framework/receipts`, `$env:AGENT_MODEL_REGISTRY_HOME` is `P:/.agent`
and `$env:PYTHONIOENCODING` is `utf-8` in every command. Each row ran from a PowerShell 7 row script that
holds the row's command as written. `<scratch>` is a scratch folder outside the repository. The `exit_code`
of a pytest or Pester receipt is the process exit; the `--pytest` check decides the targeted and full runs,
because the three excused tests (EA-2) make pytest exit 1.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row1-backup",
  "cwd": "P:/agentic-framework",
  "scope": "D-1 backup of the files the plan changes, with sha256 list",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "HEAD a73d6df2f, before any change",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --backup *> $env:RECEIPTS_DIR/uk2-backup.txt",
  "output": "backed up 4 files with their sha256 list (.agent/fleet/install-usb/README.md 3c097fe076f0; .agent/fleet/usb/README.md 99c6130716ea; .agent/fleet/usb/setup-unix.sh 815977863c07; .agent/fleet/usb/setup-windows.ps1 81495f0992d1); baseline.diff: 11993 bytes",
  "receipt_sha256": "09af427d0d4f8657d9efdad27f63a757cecfe09b7f99ed291b06d8702e62dbfe"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row1-gates-baseline",
  "cwd": "P:/agentic-framework",
  "scope": "refcheck and sanitize failure lines saved for comparison",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "HEAD a73d6df2f, before any change",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --baseline *> $env:RECEIPTS_DIR/uk2-gates-baseline.txt",
  "output": "refcheck: exit 1, 40 failure lines saved; sanitize: exit 2, 46 failure lines saved",
  "receipt_sha256": "9bc4fab753a34fea7f61031a11adc1670509805b08fffc0d273cf49ec4ff8312"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row1-pester-baseline",
  "cwd": "P:/agentic-framework",
  "scope": "both Pester files before any change",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "HEAD a73d6df2f, before any change",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupMember.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-pester-baseline.txt",
  "output": "Pester gate PASS: Result=Passed Passed=65 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "7eb62573fa5055f5f71307954606219c11cb13a41c47995042bd3e835877fc0c"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row1-full-pytest-baseline",
  "cwd": "P:/agentic-framework",
  "scope": "core/tools/tests + scripts/tests before any change; 3 failures (EA-2)",
  "phase": "static",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "HEAD a73d6df2f, before any change",
  "command": "python -m pytest core/tools/tests scripts/tests -q -rA *> $env:RECEIPTS_DIR/uk2-pytest-baseline.txt",
  "output": "3 failed, 4873 passed, 1 skipped, 66 warnings in 3575.89s (0:59:35)",
  "receipt_sha256": "b8c018d7fd420d1ada7ca22027391457609c7cdc916c5c89b6160bd66a654645"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row1-full-pytest-baseline-check",
  "cwd": "P:/agentic-framework",
  "scope": "the baseline judged by check_kit.py --pytest after EA-2: only the 3 excused tests fail",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "HEAD a73d6df2f, before any change",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --pytest $env:RECEIPTS_DIR/uk2-pytest-baseline.txt --exit 1 *> $env:RECEIPTS_DIR/uk2-pytest-baseline-check.txt",
  "output": "pytest gate PASS: exit 1; 3 failed, 4873 passed, 1 skipped, 66 warnings in 3575.89s (0:59:35)",
  "receipt_sha256": "788b85f141382150483ca825eb96e6044598624cd7e5d80992a31faeb48973c2"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row1-head-credits-two",
  "cwd": "P:/agentic-framework",
  "scope": "a clean git archive of HEAD fails the two credits tests the same way (EA-2)",
  "phase": "static",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "git archive of HEAD a73d6df2f, no worktree",
  "command": "git archive HEAD -o <scratch>/head.tar; tar -xf <scratch>/head.tar -C <scratch>/head-export; then, in <scratch>/head-export: python -m pytest scripts/tests/test_instantiate_credits_nonwin.py -q -rA *> $env:RECEIPTS_DIR/uk2-head-credits-two.txt",
  "output": "2 failed, 2 deselected in 77.65s (0:01:17)",
  "receipt_sha256": "3ab31157e49bd445ce1923981994983b42452302cdfbed59823856f382234219"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row1-selftest",
  "cwd": "P:/agentic-framework",
  "scope": "check_kit.py can fail: every mode, the excuse rules of EA-2 and the state rule of EA-13",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after EA-13",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --selftest *> $env:RECEIPTS_DIR/uk2-selftest-3.txt",
  "output": "selftest: 57 of 57 cases as expected",
  "receipt_sha256": "46d057c0605a68a5fdb1b18cb9b16e0cdf91e289ed6238d8a3b80398a2d009b7"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row2-red-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-1, AC-3, AC-4",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 2: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"ac01 or ac03 or ac04\" *> $env:RECEIPTS_DIR/uk2-red-k1u.txt",
  "output": "14 failed, 9 passed in 29.17s",
  "receipt_sha256": "dea2b2189398e083bd7a5bb3245c8b099acec24e5042858159c4c081029034d1"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row2-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-1, AC-3, AC-4: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 2: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k1u.txt --acs 1,3,4 *> $env:RECEIPTS_DIR/uk2-red-check-k1u.txt",
  "output": "red PASS: AC-1, AC-3, AC-4",
  "receipt_sha256": "0bcf79b8e6c7fbe509eefa29bd39e4d871a17e8e1db452cf883929ca398de00c"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row2-green-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-1, AC-3, AC-4, the whole of test_fleet_usb.py",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 2 (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rfE *> $env:RECEIPTS_DIR/uk2-k1u.txt",
  "output": "23 passed in 32.18s",
  "receipt_sha256": "33e7d8e5a72292eebb5f4e0e30879f910b9519dd777f7aa720776cfaf48a381c"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row3-red-pester",
  "cwd": "P:/agentic-framework",
  "scope": "AC-2, AC-3, AC-5",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 3: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-red-k1w-pester.txt",
  "output": "Pester gate FAIL: Result=Failed Passed=0 Failed=17 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "f783c4ef5191335857100578b3cad4e44b10882411bfbc1c22cd6dae80b754cc"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row3-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-2, AC-3, AC-5: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 3: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k1w-pester.txt --acs 2,3,5 *> $env:RECEIPTS_DIR/uk2-red-check-k1w.txt",
  "output": "red PASS: AC-2, AC-3, AC-5",
  "receipt_sha256": "e9fd39bbd444bee22a73b8ddfe4364e42b8f3b7aae7952be0a1f5d628717a9f3"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row3-green-pester",
  "cwd": "P:/agentic-framework",
  "scope": "AC-2, AC-3, AC-5, both Pester files",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 3 (HEAD a73d6df2f)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 scripts/tests/SetupMember.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-k1w-pester.txt",
  "output": "Pester gate PASS: Result=Passed Passed=82 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "6c858ef96a77b6ccf3a6b30ca4cbece15c890006cf275a73c7016c7715905149"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row4-red-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-6",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 4: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k ac06 *> $env:RECEIPTS_DIR/uk2-red-k1i.txt",
  "output": "4 failed, 1 passed, 23 deselected in 0.28s",
  "receipt_sha256": "2cdad5b22dfe7bc0dff5db47cfec51201532cf46661a66689065f7b2b7981a3f"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row4-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-6: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 4: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k1i.txt --acs 6 *> $env:RECEIPTS_DIR/uk2-red-check-k1i.txt",
  "output": "red PASS: AC-6",
  "receipt_sha256": "622e20f32ade323f3991072459cb067cdf75f23b4c57a230cd6dbfede3fd4b53"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row4-green-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-6, the whole of test_fleet_usb.py",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 4 (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rfE *> $env:RECEIPTS_DIR/uk2-k1i.txt",
  "output": "28 passed in 30.01s",
  "receipt_sha256": "be28eb4df35fa63bf903e82760e1712cd0441106abae2633d70a1c56c477186a"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row5-red-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-7 to AC-9",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 5: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"ac07 or ac08 or ac09\" *> $env:RECEIPTS_DIR/uk2-red-k2.txt",
  "output": "17 failed, 3 passed, 28 deselected in 98.25s (0:01:38)",
  "receipt_sha256": "3fe95865f31f3a0bb84b5c74839527bbfbcc1469fdcbbd0ddbc18d0864f1e9be"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row5-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-7 to AC-9: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 5: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k2.txt --acs 7,8,9 *> $env:RECEIPTS_DIR/uk2-red-check-k2.txt",
  "output": "red PASS: AC-7, AC-8, AC-9",
  "receipt_sha256": "d8509fb9c7bfb90ef3b16e776b230eb9cb39f4d7955c0176c2d37391da4957f5"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row5-green-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-7 to AC-9, the whole of test_fleet_usb.py",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 5 (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rfE *> $env:RECEIPTS_DIR/uk2-k2.txt",
  "output": "48 passed in 127.60s (0:02:07)",
  "receipt_sha256": "df57cc08e4cf6bc7424a1f2689bb2b64cde3da5082c02b65a1b8a3525153efbb"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row6-red-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-10, AC-12",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 6: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"ac10 or ac12\" *> $env:RECEIPTS_DIR/uk2-red-k3u.txt",
  "output": "22 failed, 48 deselected in 164.68s (0:02:44)",
  "receipt_sha256": "52893a70a077b33ba9dc00124def5f1b1460907859262602136f6c4f3c50d7aa"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row6-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-10, AC-12: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 6: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k3u.txt --acs 10,12 *> $env:RECEIPTS_DIR/uk2-red-check-k3u.txt",
  "output": "red PASS: AC-10, AC-12",
  "receipt_sha256": "44bf1f7fcf16f06d405402d722868a0372b3346c0592abce0600559b24e864b4"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row6-green-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-10, AC-12, the whole of test_fleet_usb.py",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 6 (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rfE *> $env:RECEIPTS_DIR/uk2-k3u.txt",
  "output": "70 passed in 370.42s (0:06:10)",
  "receipt_sha256": "80b8bd3a8375b5a54492f150e3d94a361efde8f62a9e350fce2766e5dcafd9ef"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row7-red-pester",
  "cwd": "P:/agentic-framework",
  "scope": "AC-11",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 7: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-red-k3w-pester.txt",
  "output": "Pester gate FAIL: Result=Failed Passed=18 Failed=14 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "dce0b15d5019ed2f5a7d5d17c5b99b52afafa9f3e2491d3ca825d1dfda98d6b7"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row7-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-11: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 7: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k3w-pester.txt --acs 11 *> $env:RECEIPTS_DIR/uk2-red-check-k3w.txt",
  "output": "red PASS: AC-11",
  "receipt_sha256": "ff5f585b27b9b92f5e022bf90d4474b523a746a7050b03274ff9c9a04cf8c362"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row7-green-pester",
  "cwd": "P:/agentic-framework",
  "scope": "AC-11, both Pester files",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 7 (HEAD a73d6df2f)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 scripts/tests/SetupMember.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-k3w-pester.txt",
  "output": "Pester gate PASS: Result=Passed Passed=97 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "98ff33b122e3797aa4dfd6f7016c2c00b1d193625ed90930895ef6184a3e1cd9"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row8-red-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-13, AC-14",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 8: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"ac13 or ac14\" *> $env:RECEIPTS_DIR/uk2-red-k4h.txt",
  "output": "48 failed, 70 deselected in 1.66s",
  "receipt_sha256": "14e7a5b6b0c418b30f0157ed5beda81545fec810e3fb887b3f5264ca41210681"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row8-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-13, AC-14: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 8: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k4h.txt --acs 13,14 *> $env:RECEIPTS_DIR/uk2-red-check-k4h.txt",
  "output": "red PASS: AC-13, AC-14",
  "receipt_sha256": "efcee8ae323b1d6a471a0ad1776cdcfcc42789870aee41478593958857def4a9"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row8-green-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-13, AC-14, the whole of test_fleet_usb.py",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 8 (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rfE *> $env:RECEIPTS_DIR/uk2-k4h.txt",
  "output": "118 passed in 361.19s (0:06:01)",
  "receipt_sha256": "c3dce69d74a1c9ef220c46ad057178fb14b196ba3673f0c4fdb6e02bbf4de349"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row9-red-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-15",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 9: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"ac15\" *> $env:RECEIPTS_DIR/uk2-red-k4m.txt",
  "output": "19 failed, 118 deselected in 103.90s (0:01:43)",
  "receipt_sha256": "4de28df9d6a9e0c61974b20fd31275c3ef1beb4e6f454bac946e2f298ac20c08"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row9-red-pester",
  "cwd": "P:/agentic-framework",
  "scope": "AC-15",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 9: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-red-k4m-pester.txt",
  "output": "Pester gate FAIL: Result=Failed Passed=32 Failed=18 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "4f5dc7a61a9276dd08069de4c4e9d0de31443e58dfe7ba07b2762f4bba7ff20c"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row9-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-15: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 9: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k4m.txt $env:RECEIPTS_DIR/uk2-red-k4m-pester.txt --acs 15 *> $env:RECEIPTS_DIR/uk2-red-check-k4m.txt",
  "output": "red PASS: AC-15",
  "receipt_sha256": "c063ccdf9116d75e3f7c285949e2dd8b0c3f5192fd198ef4e87b8f4b05ba6c9b"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row9-green-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-15, the whole of test_fleet_usb.py",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 9 (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rfE *> $env:RECEIPTS_DIR/uk2-k4m.txt",
  "output": "137 passed in 467.08s (0:07:47)",
  "receipt_sha256": "6803fe298c6b18da8ec11521545dcbd94b600d9e6d5db60aadb9de991a8954dd"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row9-green-pester",
  "cwd": "P:/agentic-framework",
  "scope": "AC-15, both Pester files",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 9 (HEAD a73d6df2f)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 scripts/tests/SetupMember.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-k4m-pester.txt",
  "output": "Pester gate PASS: Result=Passed Passed=115 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "4b2f15568cd95bd541ef6de77c7997a339beecd4df2832e5ae63845305ef30a3"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row10-red-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-16, AC-19",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 10: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"ac16 or ac19\" *> $env:RECEIPTS_DIR/uk2-red-k5h.txt",
  "output": "34 failed, 5 passed, 137 deselected in 1.57s",
  "receipt_sha256": "50cfa9bcba6da5b06c431d61a28e8099d51fcb5583b3edfedf8344c21e2a3bb6"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row10-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-16, AC-19: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 10: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k5h.txt --acs 16,19 *> $env:RECEIPTS_DIR/uk2-red-check-k5h.txt",
  "output": "red PASS: AC-16, AC-19",
  "receipt_sha256": "e89174565417d72c8bb2fda63eef64d1d74d61e100e27b4f6f411489fddfdd47"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row10-green-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-16, AC-19, the whole of test_fleet_usb.py",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 10 (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rfE *> $env:RECEIPTS_DIR/uk2-k5h.txt",
  "output": "176 passed in 461.98s (0:07:41)",
  "receipt_sha256": "30cc790c1bcde3e598140d38a4ce735a17455b1fea64aacd1339e3673bff052e"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row10a-red-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-17, AC-18",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 10a: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"ac18\" *> $env:RECEIPTS_DIR/uk2-red-k5m.txt",
  "output": "40 failed, 176 deselected in 342.96s (0:05:42)",
  "receipt_sha256": "daaa216bd9313633c13743f39e7ebc05b969dd97593d319a2ce3a0e150651020"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row10a-red-pester",
  "cwd": "P:/agentic-framework",
  "scope": "AC-17, AC-18",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 10a: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-red-k5m-pester.txt",
  "output": "Pester gate FAIL: Result=Failed Passed=49 Failed=26 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "e6e6dffb8f56f6a7f1b446c698e2a232a3a2c77a70091ce510269680716ca259"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row10a-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-17, AC-18: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 10a: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k5m.txt $env:RECEIPTS_DIR/uk2-red-k5m-pester.txt --acs 17,18 *> $env:RECEIPTS_DIR/uk2-red-check-k5m.txt",
  "output": "red PASS: AC-17, AC-18",
  "receipt_sha256": "e12f59eebe12c30058c5acff08e51d11c7de9234f0b8bb89cfb18b023ae2b954"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row10a-green-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-17, AC-18, the whole of test_fleet_usb.py",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 10a (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rfE *> $env:RECEIPTS_DIR/uk2-k5m.txt",
  "output": "216 passed in 937.31s (0:15:37)",
  "receipt_sha256": "c178b358cdf919cbc48b5fc113fd84cf057862d9e2ca40051f239e1c6851eca0"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row10a-green-pester",
  "cwd": "P:/agentic-framework",
  "scope": "AC-17, AC-18, both Pester files",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 10a (HEAD a73d6df2f)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 scripts/tests/SetupMember.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-k5m-pester.txt",
  "output": "Pester gate PASS: Result=Passed Passed=140 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "2ed662b8b85c3d7d5223f9a10c050b1549cbe2ecf81664cc046e4bb680e75aea"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row11-red-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-20, AC-21",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at row 11: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"ac20 or ac21\" *> $env:RECEIPTS_DIR/uk2-red-k6.txt",
  "output": "10 failed, 3 passed, 216 deselected in 0.91s",
  "receipt_sha256": "c5df61dd8b858bba0d18bef0f4109328900593f0d5b2ef4ff24b5adfe9620fb7"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row11-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "AC-20, AC-21: every new test of the row failed before the change",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at row 11: the row's tests written, its change not yet made (HEAD a73d6df2f)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-red-k6.txt --acs 20,21 *> $env:RECEIPTS_DIR/uk2-red-check-k6.txt",
  "output": "red PASS: AC-20, AC-21",
  "receipt_sha256": "0187f01d945326f9b9c58b31b215b94eab6ace39e7db8ebd8006ba2d88b1caeb"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row11-known-issues",
  "cwd": "P:/agentic-framework",
  "scope": "AC-21: the six known issues filed through issue_triage.py and rendered",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 11 (HEAD a73d6df2f)",
  "command": "python <scratch>/file_issues.py *> $env:RECEIPTS_DIR/uk2-k6-issues.txt (issue_triage.py add, render, render --check)",
  "output": "exit 0: render ... Rendered known-issues.md: 31 lines ; exit 0: render --check ... OK: known-issues.md is up-to-date",
  "receipt_sha256": "3aaf4d6d5b5a437d9ea84444b58e29d73dc7bd4fa236ba94ac161a02cb194a4d"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row11-green-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "AC-20, AC-21, test_fleet_usb.py + test_fleet_bootstrap.py",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after row 11 (HEAD a73d6df2f)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py scripts/tests/test_fleet_bootstrap.py -q -rfE *> $env:RECEIPTS_DIR/uk2-k6.txt",
  "output": "270 passed in 978.50s (0:16:18)",
  "receipt_sha256": "be045f46d101afc2a9ed7b14758e8adc4abfa957fbbb2f7f25f2db8c7687ab89"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row11b-targeted",
  "cwd": "P:/agentic-framework",
  "scope": "the six fleet test files, judged by check_kit.py --pytest (3 excused failures, EA-2, EA-10)",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after EA-13",
  "command": "python -m pytest scripts/tests/test_fleet_agent.py scripts/tests/test_fleet_hub.py scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_run.py scripts/tests/test_fleet_usb.py scripts/tests/test_instantiate_credits_nonwin.py -q -rA *> $env:RECEIPTS_DIR/uk2-targeted.txt; python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --pytest $env:RECEIPTS_DIR/uk2-targeted.txt --exit $code *> $env:RECEIPTS_DIR/uk2-targeted-check.txt",
  "output": "3 failed, 820 passed in 1462.00s (0:24:21); pytest gate PASS: exit 1; 3 failed, 820 passed in 1462.00s (0:24:21)",
  "receipt_sha256": "071356e84de9774d0245a98cdc059bffe5bede6f1a57ffecd7d2cf8b08ce85aa"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row16-build-plan",
  "cwd": "P:/agentic-framework",
  "scope": "this package has no docs/BUILD_PLAN.md",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after EA-13",
  "command": "python -c \"import pathlib,sys; sys.exit(0 if not pathlib.Path('docs/BUILD_PLAN.md').exists() else 1)\" *> $env:RECEIPTS_DIR/uk2-build-plan-audit.txt",
  "output": "exit 0, no output: docs/BUILD_PLAN.md does not exist",
  "receipt_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1fix-red-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14 F-002 and F-003: the two new tests fail before the fix",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at the H1-7 round 1 corrections: the three tests and four selftest cases written, the fixes not yet made",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"test_ac10_a_snap_pwsh_that_is_already_there or test_ac18_a_config_call_that_exits_nonzero\" *> $env:RECEIPTS_DIR/uk2-r1fix-red-pytest.txt",
  "output": "2 failed, 229 deselected in 23.15s",
  "receipt_sha256": "0b236a99dc4e801163f56ace1290a8721529904ab530fa64219cc408e0fbe774"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1fix-red-pester",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14 F-001: the new AC-2 Pester test fails before the fix",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at the H1-7 round 1 corrections: the three tests and four selftest cases written, the fixes not yet made",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-r1fix-red-pester.txt",
  "output": "Pester gate FAIL: Result=Failed Passed=75 Failed=1 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "79f33778733f93768b34b4ee6ac57853e0077510a960a7c1e9af7f5a054391f7"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1fix-red-check",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14: check_kit.py --red finds a failing test for AC-2, AC-10 and AC-18",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the H1-7 round 1 corrections: the three tests and four selftest cases written, the fixes not yet made",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --red $env:RECEIPTS_DIR/uk2-r1fix-red-pytest.txt $env:RECEIPTS_DIR/uk2-r1fix-red-pester.txt --acs 2,10,18 *> $env:RECEIPTS_DIR/uk2-r1fix-red-check.txt",
  "output": "red PASS: AC-2, AC-10, AC-18",
  "receipt_sha256": "d4826ea24235b3e9511100f90ad2523caafbed53b11f940f9ef896abb58c245f"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1fix-red-selftest",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14 F-004: the four new selftest cases, three of which fail before the fix",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at the H1-7 round 1 corrections: the three tests and four selftest cases written, the fixes not yet made",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --selftest *> $env:RECEIPTS_DIR/uk2-r1fix-red-selftest.txt",
  "output": "selftest: 58 of 61 cases as expected",
  "receipt_sha256": "a2fb8e0c0b31e018147d454992853c9334efd44cad378f47665300b0cfe1c239"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1fix-green-selftest",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14 F-004: every selftest case as expected",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after the H1-7 round 1 corrections (EA-14)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --selftest *> $env:RECEIPTS_DIR/uk2-r1fix-green-selftest.txt",
  "output": "selftest: 61 of 61 cases as expected",
  "receipt_sha256": "9dc10d2a8c0a9caa89f579abd7e6d146d3abe689d884ae07f73476b9a74918e5"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1fix-green-pester",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14 F-001: SetupWindowsUsb.Tests.ps1 after the fix",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after the H1-7 round 1 corrections (EA-14)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-r1fix-green-pester.txt",
  "output": "Pester gate PASS: Result=Passed Passed=76 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "e8af11480e7089814b5c65a0f97b18b17515400d5794a069dfb4c461fc0efcae"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1fix-green-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14 F-002 and F-003: test_fleet_usb.py and test_fleet_bootstrap.py after the fix",
  "phase": "green",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree after the H1-7 round 1 corrections (EA-14)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py scripts/tests/test_fleet_bootstrap.py -q -rA *> $env:RECEIPTS_DIR/uk2-r1fix-green-pytest.txt",
  "output": "1 failed, 271 passed in 1033.54s (0:17:13)",
  "receipt_sha256": "1b82cca6f7dba0e1045ee394ab8e041a71f2b41654fd07f508d4eea80a313e38"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1fix-green-ac21",
  "cwd": "P:/agentic-framework",
  "scope": "EA-15: the AC-21 tests after the known-issues render (another session's hand edit)",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree after the H1-7 round 1 corrections (EA-14)",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"test_ac21\" *> $env:RECEIPTS_DIR/uk2-r1fix-green-ac21.txt",
  "output": "3 passed, 228 deselected in 0.22s",
  "receipt_sha256": "e5fc1a76213062547aa6eda9521793be220336b813ccabbfbfb583d2aca69e36"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-full-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "Verification Plan §3: core/tools/tests + scripts/tests, judged by check_kit.py --pytest (the 3 excused failures of EA-2 must fail, every other test must pass)",
  "phase": "full",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "state e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8 (HEAD a73d6df2f327e977ca91d86a93c25c37fcfc2a7b, 17 changed paths)",
  "command": "python -m pytest core/tools/tests scripts/tests -q -rA *> $env:RECEIPTS_DIR/uk2-full-pytest.txt; python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --pytest $env:RECEIPTS_DIR/uk2-full-pytest.txt --exit $code *> $env:RECEIPTS_DIR/uk2-full-pytest-check.txt",
  "output": "3 failed, 5104 passed, 1 skipped, 66 warnings in 5002.86s (1:23:22); pytest gate PASS: exit 1; 3 failed, 5104 passed, 1 skipped, 66 warnings in 5002.86s (1:23:22)",
  "receipt_sha256": "506f33c78fdf9a721caf28197b8850958bd214f7345395cc50a50eec8f43ecd8",
  "fresh": true,
  "snapshot": false,
  "pytest_receipt_sha256": "9e52d7df7a7821c4de21c9bfd33fcfca44f8135717a9d822b13e7dd0dfddc9c6"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-pester",
  "cwd": "P:/agentic-framework",
  "scope": "Verification Plan §2: both Pester files",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "state e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8 (HEAD a73d6df2f327e977ca91d86a93c25c37fcfc2a7b, 17 changed paths)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1 scripts/tests/SetupMember.Tests.ps1 *> $env:RECEIPTS_DIR/uk2-pester.txt",
  "output": "Pester gate PASS: Result=Passed Passed=141 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0",
  "receipt_sha256": "f5a5a82e4a5bf61c9215199484e1d4ebde3ae81b02507ea7853532289de5335b"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-package-gates",
  "cwd": "P:/agentic-framework",
  "scope": "Verification Plan §4: refcheck and sanitize against the row 1 baseline, AC coverage, the Privacy scan",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "state e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8 (HEAD a73d6df2f327e977ca91d86a93c25c37fcfc2a7b, 17 changed paths)",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --gates *> $env:RECEIPTS_DIR/uk2-package-gates.txt",
  "output": "gates PASS",
  "receipt_sha256": "febec1bcbf7203b6f47e10aff50706ea07772e3aabe1b3e821867e79cde7d481"
}
```

### Quality Gate Results

```
full pytest (H1-2):  3 failed, 5104 passed, 1 skipped, 66 warnings in 5002.86s (1:23:22)
check_kit --pytest:  pytest gate PASS: exit 1; 3 failed, 5104 passed, 1 skipped, 66 warnings in 5002.86s (1:23:22)
targeted (row 11b):  3 failed, 820 passed in 1462.00s (0:24:21); pytest gate PASS: exit 1; 3 failed, 820 passed in 1462.00s (0:24:21)
Pester (H1-2):       Pester gate PASS: Result=Passed Passed=141 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0
package gates:       gates PASS
check_kit selftest:  61 of 61 cases as expected
task lint:           41 rows, 39 fully checked, 2 exempt (view_file)
privacy:             PASS, no hit
state (H1-2):        state e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8 (HEAD a73d6df2f327e977ca91d86a93c25c37fcfc2a7b, 17 changed paths)
```

### Gate failures that existed before this work, for the human

Row 1 saved the refcheck and sanitize failures of HEAD `a73d6df2f` (refcheck 40 lines, exit 1; sanitize 46
lines, exit 2), and `--gates` fails only on a line that is not in that baseline. None is in a file of this
package's code. By source file:

- `core/.agent/skills/deep-research-prompting/SKILL.md` (7 in each gate) and its d2-gemini template
  (sanitize, 1).
- Earlier fleet work: `2026-11-03-fleet-handoff.md` (1), the two `2026-11-04-fleet-agents` reviews (4 and 1),
  the `2026-11-04-fleet-agents` plan (1) and reflection (1), the proposals `2026-10-31-fleet-nodes.md` (5)
  and `2026-11-01-remote-hosts.md` (1), and the root tool scripts `_fw_sync`, `fleet` and `remote` (1 each).
- The superseded `2026-11-07-usb-kit-hardening` plan (6), task (4) and plan review (1). This plan leaves them
  as they are.
- `UPDATE-CHECKLIST.md` (sanitize, 1) and 4 sanitize lines that name no file.
- This plan's own `implementation-plan.md` (3) and `task.md` (2) at row 1: references to the two test files
  that row 2 and row 3 created, and to the AC-38 test as `file::test`. The files exist now.

---

## Changed Files

| File | Action | Lines | Summary |
|------|--------|-------|---------|
| `.agent/fleet/usb/setup-unix.sh` | modified | +1264 / -121 | WP-K1 to K5 on Linux and macOS: the v2 record on every exit path, the sudo repair and elevation chain, the Account environment, the prerequisites, the send to the hub, RustDesk |
| `.agent/fleet/usb/setup-windows.ps1` | modified | +949 / -85 | WP-K1, K3 to K5 on Windows: the v2 record, self-elevation with the record kept on a cancel, winget and the PATH fix, the send, RustDesk |
| `.agent/fleet/usb/fleet_usb.py` | modified | +654 / -22 | `prepare` (token, `hub.txt`, RustDesk release), `receive`, v2 `read_record`, `import` with the RustDesk password |
| `.agent/fleet/usb/Setup Windows.cmd` | modified | 1-7 | no up-front elevation; the script elevates itself |
| `.agent/fleet/usb/Setup Linux.desktop` | modified | 7 | `bash`, not `sudo bash` |
| `.agent/fleet/usb/Setup Mac.command` | modified | 1-8 | `bash`, not `sudo bash` |
| `.agent/fleet/usb/README.md` | modified | | the hub steps, the guide link, the 8771 line, `receive` and `import`, the terminal lines |
| `.agent/fleet/install-usb/README.md` | modified | 113-116 | the Linux steps install Claude Code and Codex; the `bash` line |
| `.agent/fleet/bootstrap.md` | modified | 58-59 | the `Fleet USB receive 8771` rule is separate from `Fleet hub 8770` |
| `core/MANIFEST.md` | modified | 40 | the kit entry names RustDesk, `receive` and the send |
| `.agent/context/known-issues.yaml`, `.agent/context/known-issues.md` | modified | | six new issues (AC-21), rendered |
| `scripts/tests/test_fleet_usb.py` | new | | 231 tests: AC-1, AC-3, AC-4, AC-6 to AC-10, AC-12 to AC-16, AC-18 to AC-21 |
| `scripts/tests/SetupWindowsUsb.Tests.ps1` | new | | 76 Pester tests: AC-2, AC-3, AC-5, AC-11, AC-15, AC-17 |
| `docs/execution/plans/2026-11-15-usb-kit-usability/` | new | | the plan, `task.md`, `check_kit.py`, `run_pester.ps1` |

Tracked files against `a73d6df2f`: 12 files changed, 3052 insertions(+), 265 deletions(-). The two test files and the plan folder are new and untracked, so they are not in that count.

```diff
--- a/.agent/fleet/usb/Setup Windows.cmd
+++ b/.agent/fleet/usb/Setup Windows.cmd
 @echo off
-rem Double-click to set up this Windows machine. It asks for administrator rights, then runs setup-windows.ps1
-rem from this drive and keeps the window open until a key is pressed.
-net session >nul 2>&1
-if errorlevel 1 (
-    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
-    exit /b
-)
+rem Double-click to set up this Windows machine. It runs setup-windows.ps1 from this drive in this window, signed in
+rem as the account the agent will use. The script asks for administrator rights itself, so the drive gets a record
+rem even when the prompt is cancelled. The window stays open until a key is pressed.
 powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-windows.ps1"
```

```diff
--- a/.agent/fleet/usb/Setup Mac.command
+++ b/.agent/fleet/usb/Setup Mac.command
 cd "$(dirname "$0")" || exit 1
-sudo bash ./setup-unix.sh
+bash ./setup-unix.sh
 status=$?
```

```diff
--- a/.agent/fleet/usb/setup-unix.sh (new function, WP-K2)
+++ b/.agent/fleet/usb/setup-unix.sh
+repair_sudo() {
+    local link="${FLEET_ROOT:-}/usr/bin/sudo" pkexec
+    [ "$os" = linux ] || return 0
+    if [ -L "$link" ] && [ ! -e "$link" ]; then
+        pkexec=$(find_tool pkexec) || return 0
+        command -v update-alternatives >/dev/null 2>&1 || return 0
+        say "/usr/bin/sudo is a link that points nowhere; repairing it with: pkexec update-alternatives --auto sudo"
+        "$pkexec" update-alternatives --auto sudo || say "the repair did not work; trying the other elevators"
+    fi
+    return 0
+}
```

```diff
--- a/.agent/fleet/usb/fleet_usb.py (EA-12)
+++ b/.agent/fleet/usb/fleet_usb.py
 class ReceiveServer(HTTPServer):
     def __init__(self, address: tuple[str, int], members: Path, token: str):
+        HTTPServer.__init__(self, address, ReceiveHandler)
```

```diff
--- a/.agent/fleet/usb/setup-windows.ps1 (EA-14, F-001)
+++ b/.agent/fleet/usb/setup-windows.ps1
         } elseif (-not (@($ctx.Steps | Where-Object { $_.status -eq 'failed' }).Count)) {
-            Add-Step $ctx 'elevate' 'failed' "elevation cancelled or failed: $reason"
+            $elevate = @($ctx.Steps | Where-Object { $_.step -eq 'elevate' }) | Select-Object -First 1
+            if ($elevate) {
+                $elevate.status = 'failed'
+                $elevate.detail = Format-Detail "the elevated run ended without a final record: $reason"
+            } else {
+                Add-Step $ctx 'elevate' 'failed' "elevation cancelled or failed: $reason"
+            }
         }
```

```diff
--- a/.agent/fleet/usb/setup-unix.sh (EA-14, F-002 and F-003)
+++ b/.agent/fleet/usb/setup-unix.sh
-    if has_cli pwsh || [ -x "$snap_pwsh" ]; then note "already installed"; return 0; fi
+    if [ -x "$snap_pwsh" ]; then
+        link_tool "$link" "$snap_pwsh" || [ -x "$link" ] || fail "$link exists and is not a link to pwsh; left alone"
+        note "already installed"
+        return 0
+    fi
+    if has_cli pwsh; then note "already installed"; return 0; fi
     ...
     rd_wait_ready || fail "service not ready"
-    run "$rd_bin" --config "host=$rd_host,key=$rd_key" || fail "rustdesk --config failed"
+    run "$rd_bin" --config "host=$rd_host,key=$rd_key" || say "rustdesk --config exited nonzero; the read-back decides"
```

```diff
--- a/core/MANIFEST.md
+++ b/core/MANIFEST.md
-- `.agent/fleet/usb/` — The USB drive kit that gives the hub machine an SSH admin connection to a new Windows, macOS or Linux machine. …
+- `.agent/fleet/usb/` — The USB drive kit that gives the hub machine an SSH admin connection to a new Windows, macOS or Linux machine, and RustDesk on each one that has a screen. … `fleet_usb.py receive` takes those records; `fleet_usb.py import` pins the host keys, writes `~/.ssh/fleet_config` and sets each RustDesk password. Holds no hosts or credentials.
```

---

## Codex Validation Report

### Points raised for the reviewer

1. **EA-2, a human gate waiver.** The row 1 baseline had two failures outside the plan's known list, in
   `scripts/tests/test_instantiate_credits_nonwin.py` (`test_no_retained_python_file_needs_a_removed_tool` and
   `test_retained_python_tests_collect`). A clean `git archive` of HEAD fails them the same way (record
   `row1-head-credits-two`). The human ruled "Excuse both for this plan" (Decision Log EA-2). `check_kit.py
   --pytest` excuses exactly three ids and still fails when an excused test passes or does not run. The sixth
   known issue, `FLEET-INSTALL-RETAINED-CREDITS-TESTS`, tracks them. Neither test changed.
2. **EA-9, a setup-only change to a Red-phase test.** `test_ac18_the_system_job_is_bootstrapped_before_the_first_id_call`
   now calls `mrd.persist()` before the run, so `--config` keeps the server and the TOML fallback does not run.
   Its assertions are unchanged. Please check that this is setup, not a weaker test (G36).
3. **EA-8, one changed assertion of AC-11.** The Windows step list that the AC-11 test asserts now has
   `rustdesk` before `host_key`, because AC-17 puts the new step there. No other assertion of AC-1 to AC-12
   changed.
4. **EA-10.** Row 11b's file list gained `scripts/tests/test_instantiate_credits_nonwin.py`, so the two
   excused tests run in the targeted check and are not reported as missing.
5. **EA-11.** The PC row (and COMMIT, at H2) is `[x]` and not `[x] n/a`, because the task linter's legend
   has no `n/a`. The row text and its receipt still say that no commit was directed.
6. **EA-12, the gate false positives.** The first row 11b `--gates` run failed on 10 reference lines and 4
   Privacy hits, none a real leak or a broken link. Four changes: the EA-2 references reworded; `ReceiveServer`
   calls `HTTPServer.__init__` directly (a Python built-in's name is a deny term of this hub); a fixture tag
   `1.4.1.999` in `RD_BAD_RELEASES`; and Privacy class 1 allows the one link-local test address `169.254.7.7`
   that two AC-13 tests need. Round 1 found the first form of this change (the whole link-local range) too broad;
   EA-14 (4) narrowed it.
7. **EA-13, the state id.** `--state` now leaves out this plan's `task.md`, whose row marks change after H1-2.
   Every other Files Modified path, `check_kit.py` and the plan included, stays in the id. The change came
   before H1-2.
8. **EA-14, the round 1 corrections.** Each finding has a new test, seen to fail first (FAIL_TO_PASS, records
   `r1fix-*`). F-001 (AC-2): when the elevated child checkpointed every step through `host_key` and then died,
   `setup-windows.ps1` now marks the existing `elevate` entry failed instead of adding a second one, which
   `read_record` refuses. F-002 (AC-10): `pwsh_linux` checks the snap PowerShell first and makes the
   `/usr/local/bin/pwsh` link when the snap is already there. F-003 (AC-18): a nonzero exit of
   `rustdesk --config` is reported, and the read-back and the TOML fallback decide (EA-8). Setup change: the
   `RD_PROGRAM` stub reads an optional `config_exit` file for its `--config` exit (default 0, so every earlier
   test sees the same stub). F-004: Privacy class 1 allows only `169.254.7.7`, and class 5 also reads each inbox
   record's `addresses`; `--selftest` gained four cases. H1-2 ran again on the corrected state.
   **EA-15:** the green run after EA-14 failed one AC-21 test because another session had added the issue
   `FLEET-DOCKER-CI-LANE-UNTRACKED` to `known-issues.yaml` and its row to `known-issues.md` by hand. A render
   changed only the totals line, and the AC-21 tests passed (record `r1fix-green-ac21`). That issue is not part of
   this plan.
   **EA-16:** H1-2 on the corrected state passed pytest and Pester and first failed `--gates`: this handoff named
   four files of the earlier gate failures in path form, and the EA-12 and EA-14 text quoted the whole
   link-local range as an address literal that the narrowed scan reports. Both were reworded. Neither file is in
   the state id, so only `--gates` ran again, and it passed.
9. **EA-1 and EA-3 to EA-7** are small choices where the plan is silent (see `task.md`, Execution Amendments).
   None narrows the plan. EA-3 lets `homebrew` need only `account`, so AC-12 can show Homebrew run as the
   Account on a test host whose port 22 is closed. The order stays `admin_rights`, `homebrew`, `pwsh`.
10. **Residual risks that the tests here cannot prove** (EA-7, EA-8): the real GitHub API and downloads, ssh
   quoting from a Windows hub to a Unix member, the real `rustdesk --config`, `--get-id` and `--password` on
   each system, launchd races, `msiexec`, and a real `apt-get` and `sudo-rs`. The live rows 12 to 15 check them.
11. **Privacy.** The framework repository is public. The handoff names members as `<member-1>` and the hub as
    `<hub-host>`, and the Privacy scan (classes 1 to 5) passes on every changed file.
12. **No commit or push.** The run direction grants neither. PC and COMMIT record that no commit was directed.

---

## Deferred Items

These rows are human-decision gates, not unfinished work. Each has its `B-<row>` block in `task.md`.

| Item | Reason | Deferred-to MEU (scheduled) | Follow-up |
|------|--------|-----------------------------|-----------|
| Row 11a, the hub: the RustDesk ID server, the `Fleet USB receive 8771` rule, `check_kit.py hub` | human-decision (the agent does not change the hub firewall, stop condition 3) | none: a human row of this plan | `B-11a` in `task.md` |
| Row 12, AC-23: the new mini PC, live | human-decision (real hardware) | none: a human row of this plan | `B-12` in `task.md` |
| Row 13, AC-24: the same mini PC, run again | human-decision; needs row 12 | none: a human row of this plan | `B-13` in `task.md` |
| Row 14, AC-25: a member of the other OS family | human-decision (the human names the machine) | none: a human row of this plan | `B-14` in `task.md` |
| Row 15, AC-26: a Mac | human-decision (the human grants the macOS permissions) | none: a human row of this plan | `B-15` in `task.md` |

---

## Decision Log

```yaml
decision_log:
  - id: EA-2
    stage: execution
    question: "The row 1 baseline had two failures outside the plan's known list, in test_instantiate_credits_nonwin.py, that a clean export of HEAD also has. Stop, or excuse them for this plan?"
    resolution: human
    class: governance-value
    chosen: "Excuse both for this plan: check_kit.py --pytest excuses exactly these two and the AC-38 test, and fails when one of them passes or does not run; known issue FLEET-INSTALL-RETAINED-CREDITS-TESTS tracks them"
    source_tag: Human-approved
    precedents: ["implementation-plan.md stop condition 2 - a new failure outside KNOWN_FAILURES stops the run", "FLEET-AC38-BILLING-LINE-PIN - the plan's first excused failure"]
    research: { engine: none, sources: ["uk2-head-credits-two.txt - git archive of HEAD fails the same two tests"] }
    reasoning: "A gate waiver belongs to the human. The failures come from commit fb00d40, outside this plan, so fixing them here would widen the scope; the excuse is exact and tracked"
    human_message_reference: "USER_EXPLICIT 2026-11-15, answer to the agent's question: 'Excuse both for this plan (Recommended)'"
  - id: EA-12
    stage: execution
    question: "The first row 11b --gates run failed on 10 reference lines and 4 Privacy hits that are no leak and no broken link. Change the files, the fixtures, or the scan?"
    resolution: autonomous
    class: two-way
    chosen: "Reword the references, call HTTPServer.__init__ directly, change one fixture tag, and allow the one link-local test address 169.254.7.7 in Privacy class 1 (narrowed from the whole link-local range by EA-14)"
    source_tag: Research-backed
    precedents: ["implementation-plan.md Privacy scan - its purpose is no data that names a machine", "EA-1 - the same kind of rewording, with no exception added"]
    research: { engine: none, sources: ["RFC 3927 - the whole link-local range is assigned by each host to itself and names no machine"] }
    reasoning: "Each hit was a false positive. Three changes keep the scan as strict as written; the class 1 change matches loopback, which the scan already allows, and the AC-13 tests need a real link-local value"
  - id: EA-13
    stage: execution
    question: "check_kit.py --state covers this plan's task.md, so marking an H1 row after H1-2 changes the state id and H1-6b can never pass. What changes?"
    resolution: autonomous
    class: two-way
    chosen: "Leave this plan's task.md, and only it, out of --state, with a --selftest case, before H1-2"
    source_tag: Local Canon
    precedents: ["implementation-plan.md Verification Plan - H1-6b reruns section 3 and 4 when the state id changed", "core/templates/HANDOFF-TEMPLATE.md - the full gate is bound to the inputs under test"]
    research: { engine: none, sources: [] }
    reasoning: "Row marks are no input of a test or a gate. Keeping the code, the tests, check_kit.py and the plan text in the id keeps the binding strict; the other choice, never marking rows until the end, breaks evidence-first completion"
  - id: EA-14
    stage: execution
    question: "The H1-7 round 1 review returned changes_required with F-001 and F-002 blocking and F-003 and F-004 non-blocking. Fix which, and how?"
    resolution: autonomous
    class: two-way
    chosen: "Fix all four, each with a test written first and seen to fail: replace the elevate entry in place (F-001), link a snap pwsh that is already there (F-002), report a nonzero --config exit and let the read-back decide (F-003), and narrow Privacy class 1 to 169.254.7.7 while class 5 reads record addresses (F-004)"
    source_tag: Local Canon
    precedents: ["AGENTS.md G36 - after Red only setup and fixtures change; the RD_PROGRAM config_exit knob is setup", "EA-8 - the read-back and the TOML fallback decide the RustDesk step"]
    research: { engine: none, sources: [] }
    reasoning: "Each finding names a real failure on a member or a scan gap. The fixes change behavior only on the paths the findings name, and no AC assertion changed"
  - id: EA-15
    stage: execution
    question: "During the green run another session added a known issue to known-issues.yaml and its row to known-issues.md by hand, so the AC-21 render check failed. Wait, edit by hand, or render?"
    resolution: autonomous
    class: two-way
    chosen: "Keep a copy of the markdown and run issue_triage.py render; only the totals line changed, and the other session's issue stays in both files"
    source_tag: Local Canon
    precedents: ["known-issues.md header - auto-generated from known-issues.yaml, never edited by hand"]
    research: { engine: none, sources: [] }
    reasoning: "The render is the file's own repair and loses nothing; the other session's issue is not part of this plan, and a commit of this plan must leave it out unless the human says otherwise"
  - id: EA-10
    stage: execution
    question: "Row 11b's check failed because the two excused credits tests were not in its file list. Add the file, or loosen the check?"
    resolution: autonomous
    class: two-way
    chosen: "Add scripts/tests/test_instantiate_credits_nonwin.py to row 11b's pytest list; the check stays as strict"
    source_tag: Local Canon
    precedents: ["EA-2 - an excused test that does not run fails the gate"]
    research: { engine: none, sources: [] }
    reasoning: "A looser check could hide a test that stops running; the full run of section 3 already holds the file"
  - id: EA-9
    stage: execution
    question: "An AC-18 test could not pass with any implementation of WP-K5, because its setup let the TOML fallback run. Change the setup or the assertion?"
    resolution: autonomous
    class: two-way
    chosen: "A setup-only change: the test calls mrd.persist() first; the assertions are unchanged and the fallback keeps its own test"
    source_tag: Local Canon
    precedents: ["AGENTS.md G36 - after Red only setup and fixtures change", "implementation-plan.md WP-K5 step 5 - the fallback restarts the service"]
    research: { engine: none, sources: [] }
    reasoning: "The assertion is the specification and stays; the setup was wrong for the case the test names"
```

---

## History

| Event | Date | Agent | Detail |
|-------|------|-------|--------|
| Created | 2026-11-15 | implementing agent | Rows 1-11, 11b and 16 done; H1-2 passed fresh; live rows wait for the human |
| Submitted for review | 2026-11-15 | implementing agent | Sent to codex, loop exec-2026-11-15-usb-kit-usability |
| Review round 1 | 2026-11-15 | codex | changes_required: F-001 and F-002 blocking, F-003 and F-004 non-blocking |
| Corrected | 2026-11-15 | implementing agent | EA-14: all four fixed test-first; H1-2 ran again on the new state; resubmitted as round 2 |
