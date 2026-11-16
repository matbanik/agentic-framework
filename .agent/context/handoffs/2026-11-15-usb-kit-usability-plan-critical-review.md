---
date: "2026-11-15"
review_mode: "plan"
target_plan: "docs/execution/plans/2026-11-15-usb-kit-usability"
verdict: "corrections_applied"
findings_count: 4
review_round: 3
template_version: "2.2"
requested_verbosity: "detailed"
agent: "Codex"
---

# Critical Review: 2026-11-15-usb-kit-usability

> **Review Mode**: `plan`
> **Verdict**: `changes_required`
> **Round**: 1 of 3

Executing this plan should make a fresh member usable from the USB kit: preserve an importable outcome even after failure, report it to the hub, install the requested tools, establish full SSH administration, and configure RustDesk for the hub's server. The current plan does not yet deliver that objective on all its specified paths.

## Scope

**Targets**: `docs/execution/plans/2026-11-15-usb-kit-usability/implementation-plan.md` and `docs/execution/plans/2026-11-15-usb-kit-usability/task.md`.

**Review Type**: unstarted plan review, including the on-disk kit, both READMEs, cited package docs and validators, and the peer fleet-agents plan's gate/Pester forms. In references below, **plan** means the target `implementation-plan.md`, and **task** means its sibling `task.md`.

**Checklist Applied**: PR-1 through PR-9 and applicable DR-1 through DR-8. The human's full-admin/usability ruling governs. No reduced privileges, installer provenance requirements, narrower firewall scope, hostile-LAN/member defenses, or objections to implementing-agent-authored checks are requested here. PC and COMMIT remain manual/n/a without human direction; nothing is pushed.

Only this review file was written in the repository. Review scratch and receipts are in `the review folder C:/Temp/zorivest/usb-kit-plan/uk2-review-r1/`. No setup script or fleet operational command was run, and no hub/member was contacted. No credential, private key, token or password file was opened.

## Findings

All findings are open. Confidence is stated in each Finding cell. H findings block because they cause a named delivery failure or a concrete false pass; L findings are clerical and do not block.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| H01 | High | yes | behavior | **High confidence. Canceled Windows elevation bypasses the record writer.** The unchanged double-click launcher tries `Start-Process -Verb RunAs` and exits its unelevated branch before calling the setup script. If the human cancels UAC, the new PowerShell `elevate` step and `finally` never execute. AC-2's library-only mock does not exercise that production path. Violates Record write, AC-2 and PR-8. | task.md:48; plan:218; `.agent/fleet/usb/Setup Windows.cmd:5` and :9; plan:480 | Include the Windows launcher in the change inventory and route denied/canceled elevation through a writer that runs without elevation. Test the launch path, not only `Invoke-Setup`. | open |
| H02 | High | yes | behavior | **High confidence. Exit-only persistence cannot preserve a user-terminated run.** The first durable record is deferred to EXIT/finally, and Send defers the final drive copy until after network attempts. Closing/terminating the setup process during a slow install or send leaves no current-run record; forced process termination cannot execute a finalizer. This is the human's in-scope user-stop case, not a hostile-member scenario. Violates Record write, Goal 1 and PR-4. | plan:148; plan:159; plan:243; plan:244 | Persist a valid incomplete/failed record once identity is known, checkpoint step progress atomically, and finalize it on normal exits and catchable cancellation. Test interruption during a step and send. State the unavoidable boundary before initialization rather than claiming finalizers run after forced termination. | open |
| H03 | High | yes | behavior | **High confidence. Offline fallback has incompatible `ok` contracts.** Record v2 permits `ok=true` only when no step failed, and AC-4 requires refusal of true beside a failed step. Send appends a failed `send` step to the drive copy, while AC-15 says send failure must not alter the setup exit result. Thus a successful setup with an unreachable hub either leaves a drive record AC-4 refuses, or changes success into failure. The extra `send` id is also outside the canonical Step list. Violates AC-4/AC-15 and PR-1/PR-9. | plan:132; plan:140; plan:159; plan:246; plan:336; task.md:54 | Define delivery status separately, or explicitly exclude delivery from the setup-success predicate and amend the reader and ACs together. Test an offline successful setup end to end through `read_record` and import. | open |
| H04 | High | yes | behavior | **High confidence. Fresh Mac PowerShell installation cannot complete as sequenced.** The Step list runs `pwsh` before `homebrew`, although `pwsh` needs Homebrew. Skipping the unmet dependency leaves PowerShell absent after Homebrew eventually succeeds. Independently, the prescribed `brew install --cask powershell` targets a removed cask; current Microsoft docs use the formula. AC-12 tests the failed-Homebrew skip, not successful fresh installation. Violates Goal 4, AC-12/AC-26 and PR-4. | plan:132; plan:135; plan:289; plan:300; task.md:51 | Move Homebrew before PowerShell, use the current formula or supported package route, and require a fresh-Mac success case that reaches `pwsh --version` in that run. See S1 and local canon `core/.agent/docs/macos-setup.md:237`. | open |
| H05 | High | yes | behavior | **High confidence. Unix account switching does not supply the freshly installed tools' PATH.** The prescribed Linux `runuser ... env HOME=...` and Mac `sudo -u ... -H` do not load the account's new shell environment. The plan rebuilds PATH only on Windows. On a fresh account, installers creating `.local/bin` cannot change the parent PATH; on a fresh Apple Silicon Mac, Homebrew also needs its prefix environment before the next bare `brew` command. Consequently the version commands and later Account commands cannot find installed tools in the same run. Violates Goal 4, AC-10/AC-12/AC-23 and PR-4. | plan:271; plan:284; plan:292; plan:439; task.md:51; `.agent/fleet/usb/setup-unix.sh:122` | Define an Account execution environment including the installation directories and Homebrew prefix, use it for installs and version discovery, and prove discovery from the actual SSH command environment too. Test from a minimal fresh PATH; installer profile edits alone are insufficient. See S2. | open |
| H06 | High | yes | behavior | **High confidence. The Mac RustDesk path copies an app but never starts the IPC server needed by its CLI.** Only Linux gets an explicit service enable/start. On a fresh Mac, copying the app does not launch it, create its running server, or install launchd jobs. The next config/id calls are IPC-backed; there is no existing service to restart and no pre-existing TOML id for the fallback. The deployment reference explicitly starts the server; AC-18 covers deb/rpm but no Mac lifecycle. Violates WP-K5, AC-26 and PR-8's producer/call-chain requirement. | plan:370; plan:374; plan:380; plan:398; task.md:56; task.md:63 | Specify the Mac executable path, launch/service bootstrap, correct Account config location, readiness and restart sequence before collecting the id or setting a password. Add a fresh-Mac stub case that fails if no server starts. See S3. | open |
| H07 | High | yes | behavior | **High confidence. SSH stdin does not keep the password off the member's command line.** Reading stdin into a shell variable and then invoking `rustdesk --password <pw>` expands that variable into the RustDesk process argument vector. AC-19 inspects the fake SSH arguments only, so it misses this leak on the member. D-5's storage location is sound, but its stated transport guarantee cannot hold with the prescribed invocation. Violates WP-K5's explicit no-member-command-line rule and PR-4/PR-8. | plan:385; plan:399; task.md:55 | Select a supported password-setting mechanism that consumes the secret without a child-process password argument, then test the remote child argument vector as well as SSH's. If the requirement must change, obtain an explicit ruling; do not describe variable expansion as stdin-only handling. RustDesk's actual CLI consumes `args[1]`; see S4. | open |
| H08 | High | yes | behavior | **High confidence. Row 5's green check requires a README change scheduled for row 11.** AC-9 scans both launchers and `usb/README.md` for absence of `sudo bash`. Row 5 implements the launchers/header and then runs the entire new pytest file, including AC-9. Its outputs omit the README, which still has `sudo bash` on disk; row 11 owns that edit. A faithful run stops at row 5 and cannot reach row 11. Violates PR-1/PR-4 and the declared row order. | plan:280; task.md:50; task.md:57; `.agent/fleet/usb/README.md:57` and :58 | Move the README launch-line edit into row 5, or split/defer the README assertion to its owning row while retaining launcher checks at row 5. | open |
| H09 | High | yes | control-defeat | **High confidence. `--red` accepts test setup failure as feature evidence.** `ERROR ...::test_acNN_...` includes pytest fixture/setup errors. For example, a fixture failing to load the new script/function can produce one such line per AC without invoking any setup behavior; the specified checker nevertheless passes. This is a concrete false pass for missing behavioral Red evidence, not a demand for stronger predicate formatting. Violates the no-collection/setup-error Red contract and PR-8. **mechanism: setup-error-counted-as-red** | plan:182; task.md:47; task.md:104; `core/AGENTS.md:37` | Reject collection/setup/teardown errors separately. Require assertion failures showing the intended unmet behavior, and add a selftest receipt containing per-test fixture errors that must be refused. Keep Pester block/container failures distinct from assertion failures too. | open |
| H10 | High | yes | control-defeat | **High confidence. The live rerun can pass without receiving the rerun.** After row 12 the inbox already contains a good record. In row 13, if setup aborts or send fails, receive can time out with zero new records. The validation imports the old inbox and checks its still-true `ok`, versions, unchanged password hash and key count. No predicate requires a new `run_id` or a record actually accepted in this receive session, so the missing rerun materially false-passes AC-24. Violates PR-8 and AC-24. | plan:321; plan:436; plan:439; task.md:60; task.md:61 | Bind each live row to the receiver's accepted count and new run id, and require the rerun id to differ from the fresh id. A timeout/zero-delivery session must fail that row even with a good old inbox record. Selftest this exact stale-inbox case. | open |
| H11 | High | yes | behavior | **High confidence. H1-6 explicitly promotes real member names into a public tracked handoff.** It requires receiver summary lines with “names only”; those are the actual member names used by prepare/receive/import, not placeholders. This violates the user's public-repository rule and also makes the later Privacy scan reject a correctly performed H1-6, because imported names are deny terms. Omitting addresses alone does not fix it. Violates the human's publication constraint and PR-1/DR-5. | task.md:71; plan:204; plan:208; task.md:86 | Redact live identities to consistent placeholders before promotion into the handoff/reflection/reviews. Preserve private raw receipts separately and keep durable pass/fail/run-identity evidence without publishing the machine names. | open |
| H12 | High | yes | control-defeat | **High confidence. Privacy scanning does not cover its publication promise.** The prescribed rules detect IPv4, email and a small dynamic deny list, but no literal user-path pattern or personal-name input. A new literal user home path can therefore be added to a scanned file and pass. Additionally, the scan inventory names the Files Modified table, plan folder, handoff and reflection, but H2-5's public commit also includes both reviews and H2-3's metrics row; those artifacts are omitted. A leak placed there is not inspected at all. Violates the human's public-repository constraint, AC-22 and PR-8. **mechanism: incomplete-publication-privacy-scan** | plan:204; plan:480; task.md:81; task.md:85; task.md:86 | Derive scan scope from every proposed public artifact, including reviews/metrics, and add detection for literal user paths plus relevant runtime personal identifiers without logging them. Add failing selftests for these classes and for a leak in each omitted artifact. Keep the explicitly allowed guide URL exception narrow. | open |
| L01 | Low | no | clerical | **High confidence. Step statuses are restated in the Record v2 definition.** PR-9 requires one named definition. | plan:128; plan:142 | Make Step the canonical status definition and reference it from Record v2. | open |
| L02 | Low | no | clerical | **High confidence. The run-id regex is restated at the argument boundary.** The spellings currently agree. | plan:139; plan:464 | Define Run id once and reference it in the record and argument rules. | open |
| L03 | Low | no | clerical | **High confidence. The elevator fallback exit-code set is repeated in AC-7.** The spellings currently agree. | plan:266; plan:278 | Name the WP-K2 fallback predicate and reference it from AC-7. | open |

### Primary-source checks and attempted refutations

- **S1 — PowerShell on Mac:** current [Microsoft alternate installation instructions](https://learn.microsoft.com/en-us/powershell/scripting/install/alternate-install-methods) prescribe `brew install powershell`; the [current formula](https://raw.githubusercontent.com/Homebrew/homebrew-core/master/Formula/p/powershell.rb) exists, while the old cask endpoint returns 404. Local `core/.agent/docs/macos-setup.md:237` and :284 already document the migration. This confirms H04, rather than a speculative future deprecation.
- **S2 — Account PATH:** [runuser's documented non-login environment](https://manpages.ubuntu.com/manpages/resolute/man1/runuser.1.html) does not source a new login environment. [Homebrew post-install steps](https://docs.brew.sh/Installation#post-installation-steps) require `brew shellenv`; [uv's installer documentation](https://docs.astral.sh/uv/reference/installer/) describes profile modifications, which do not update the running parent shell. Windows' separate PATH rebuild does not refute the Unix failure in H05.
- **S3 — Mac RustDesk lifecycle:** the [deployment example](https://rustdesk.com/docs/en/self-host/client-deployment/) uses the app-bundle executable and starts `--server`. The [1.5.3 CLI source](https://raw.githubusercontent.com/rustdesk/rustdesk/1.5.3/src/core_main.rs), especially lines 425–456, delegates password/id operations to IPC. App copying and GUI permission grants do not themselves supply that producer. Mac launchd lifecycle code is present in the [platform implementation](https://raw.githubusercontent.com/rustdesk/rustdesk/1.5.3/src/platform/macos.rs).
- **S4 — Password arguments:** the same [1.5.3 CLI source](https://raw.githubusercontent.com/rustdesk/rustdesk/1.5.3/src/core_main.rs) reads the permanent password from `args[1]`. A shell variable protects the SSH invocation's arguments only; expansion still creates the member's RustDesk password argument. No password was generated or inspected in this review.
- **S5 — Termination:** [Windows process termination semantics](https://learn.microsoft.com/en-us/windows/win32/procthread/terminating-a-process) do not unwind a killed interpreter. [PowerShell's finally documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_try_catch_finally) does cover Ctrl+C; that narrower guarantee was considered and does not refute H02's forced-close/termination case.
- **Config syntax concern refuted:** although the overview docs emphasize encoded strings, [RustDesk 1.5.3's actual parser](https://raw.githubusercontent.com/rustdesk/rustdesk/1.5.3/src/custom_server.rs), lines 40–88, accepts a plain `host=...,key=...` string. The CLI calls this parser. No finding demands a different config encoding.
- **Assets checked:** all six patterns match actual [1.5.3 release asset names](https://github.com/rustdesk/rustdesk/releases/expanded_assets/1.5.3), including `-0.x86_64.rpm` and both DMG architectures. The MSI/deb/rpm names are not findings.
- **Prerequisite commands checked:** the [Python winget manifest](https://raw.githubusercontent.com/microsoft/winget-pkgs/master/manifests/p/Python/Python/3/14/3.14.0/Python.Python.3.14.installer.yaml) confirms `Python.Python.3.14` and PATH-prepend switches. Git and Microsoft PowerShell ids are established manifests. The [winget error definition](https://raw.githubusercontent.com/microsoft/winget-cli/master/src/AppInstallerSharedLib/Public/AppInstallerErrors.h) names `0x8A15002B` UPDATE_NOT_APPLICABLE, consistent with treating an already-current package as successful. [Microsoft's Linux instructions](https://learn.microsoft.com/en-us/powershell/scripting/install/alternate-install-methods) confirm snap and archive forms; archive installation must include dependencies/executable permissions, and a same-run check must verify the chosen route. [Claude's setup docs](https://code.claude.com/docs/en/setup), [Codex CLI docs](https://developers.openai.com/codex/cli/) and [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/) corroborate the specified installer commands. No installer provenance requirement is added.
- **Ubuntu chain checked:** `bash <script>` avoids reliance on a FAT executable bit; omitting `-E` avoids that compatibility issue. [pkexec](https://manpages.ubuntu.com/manpages/resolute/man1/pkexec.1.html) documents PKEXEC_UID and its environment reset. [`update-alternatives --auto`](https://manpages.ubuntu.com/manpages/resolute/man1/update-alternatives.1.html) restores the highest-priority installed alternative and associated links; it is suitable for the stated dangling-link case. The cited Launchpad page could not be fetched, so its precise bug narrative is not independently confirmed. No finding asks to switch a working sudo provider.

## Checklist Results

The manual procedure M1 was performed by Codex: read both complete targets with line numbers; trace each task/AC/definition through the current kit and cited docs; inspect the peer gate and its Pester wrapper; refute candidate failures against those sources; distinguish intentional human gates from agent dependencies. M1's observations are recorded in the findings and coverage tables below. It is a document/code review, not a live machine test.

### Plan review

| Check | Result | Command / procedure | Exit | Evidence |
|---|---|---|---|---|
| PR-1 Plan/task alignment | fail | M1; observer Codex | null | H03, H08 and H11 are incompatible behavior/order/publication instructions. |
| PR-2 Not-started confirmation | pass | M1; read-only status and artifact census | null | All 41 rows unstarted; no implementation handoff, new test files or plan checkers exist. The four kit edits are the declared human baseline. |
| PR-3 Task contract completeness | pass | `rtk proxy python -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-15-usb-kit-usability/task.md` | 0 | 41 rows, 39 command rows accepted, 2 source-read exemptions; dependencies resolve and are acyclic. |
| PR-4 Validation realism | fail | M1; existing Pester/pytest and parse checks below | null | H01–H10 identify paths that cannot deliver or validations that cannot prove the delivery. Current baseline has one existing pytest failure. |
| PR-5 Source-backed planning | pass | M1; primary-source comparisons S1–S5 and refutations | null | Every AC has a source label; erroneous technical choices are findings, not missing provenance labels. |
| PR-6 Handoff/corrections readiness | pass | M1 | null | One project handoff, rolling reviews, manual gate, plan cap 3 and execution cap 6 are explicit. Round-2 census requirement is not applicable yet. |
| PR-7 Scope discipline | pass | M1; Out of Scope and cited docs | null | All seven exclusions have substantive human/local bases; there are no unscheduled deferred MEUs. Hardening and server construction remain excluded as ruled. |
| PR-8 Reachability and totality | fail | M1; production launch/finalization/import traces and concrete negative cases | null | H01/H06 have missing production producers; H09/H10/H12 demonstrate materially false-passing checks. |
| PR-9 Single-statement discipline | partial | M1; repeated-literal comparison | null | H03 has a material conflicting predicate; L01–L03 identify agreeing repeated definitions. |

### Docs review

| Check | Result | Command / procedure | Exit | Evidence |
|---|---|---|---|---|
| DR-1 Claim-to-state match | pass | M1 | null | Plan claims draft/unstarted work, consistent with current state and the explicitly retained human edits. |
| DR-2 Residual old terms | pass | M1; source/doc comparison | null | Old `sudo bash` lines are identified and assigned an edit, with the timing defect reported as H08. No unowned rename is asserted. |
| DR-3 Downstream references | pass | M1; artifact census | null | READMEs, bootstrap and MANIFEST are assigned; UPDATE-CHECKLIST is substantively inapplicable to this package-authored change. |
| DR-4 Verification robustness | fail | M1 | null | H09/H10/H12 show false passes, H08 an unavoidable intermediate failure. |
| DR-5 Evidence auditability | fail | M1 | null | Exact commands and receipts exist in the plan, but H11 would promote unredacted identities into public evidence. |
| DR-6 Cross-reference integrity | fail | M1 | null | Mac PowerShell choice contradicts existing local canon; row 5/11 and Record/Send conflicts survive cross-checking. |
| DR-7 Evidence freshness | pass | M1; current read-only probes below | null | This review uses current files. No old test result is represented as this run's result; no new implementation test is claimed executed. |
| DR-8 Completion versus residual risk | n/a | — | — | No implementation completion is claimed. Live/human blocks and known issues are declared. |

### Complete coverage ledger

| Work package | ACs considered | Result / decisive coverage |
|---|---|---|
| WP-K0 | AC-22 plus all Red mappings | Backup-first protects the four files; planned executables are inventoried. H09 and H12 affect the checkers. Existing baseline stop is reproduced below. |
| WP-K1 | AC-1, AC-2, AC-3, AC-4, AC-5, AC-6 | H01/H02/H03 affect records. Name-rule examples, v1 compatibility intent, JSON escaping specification, Windows PATH de-duplication, failed-host-key skip and mixed import exit are explicitly specified. Quotes/backslashes/control characters are covered by AC-4; add non-ASCII to that fixture when implementing. |
| WP-K2 | AC-7, AC-8, AC-9 | Account resolution, non-executable FAT launch, fallback exits, parent run-id suppression and visudo fallback checked. H08 prevents the row-5 green gate. |
| WP-K3 | AC-10, AC-11, AC-12 | Package/winget ids and installers checked against sources; H04/H05 affect Mac and Unix discovery. No Python is needed for the member's initial send. |
| WP-K4 | AC-13, AC-14, AC-15 | Token reuse, computed/explicit URLs, five receive outcomes, atomic same-folder replacement, count and timeout are assigned. Windows uses curl.exe; Unix packages provide curl and missing curl has an explicit drive fallback. H03 affects offline output and H10 affects live receipt freshness. |
| WP-K5 | AC-16, AC-17, AC-18, AC-19 | Six real assets verified; config-string concern refuted. GUI rule/Wayland note considered. H06 affects fresh Mac startup and H07 defeats the explicit password constraint. |
| WP-K6 | AC-20, AC-21 | All named docs and four issue ids are assigned. Issue tool arguments select the correct YAML/Markdown pair. H08 affects doc-edit timing; H11/H12 affect public artifacts. |
| WP-K7 | AC-23, AC-24, AC-25, AC-26 | Fresh/rerun mini PC and other-family/Mac rows are present and human-gated; H10 affects the new-run oracle, H04–H07 affect tool/RustDesk delivery. No live check was executed in review. |

| Named definition | Independent assessment |
|---|---|
| Account | SUDO_USER/PKEXEC_UID/explicit-user precedence is sensible; per-user environment needs H05. Windows same-user elevation does not solve canceled-launch H01. |
| Name rule | Normalization, truncation and empty fallback satisfy NAME; both script halves get examples. |
| Step | Nonfatal/needs semantics are explicit. During implementation, catch a failure in the middle of a multi-command Bash function, followed by a successful command: conditional function calls disable errexit, so `set -e` alone is not the mechanism. AC-1 must test that case. |
| Step list | Mac dependency order is broken (H04); delivery needs a defined status placement (H03). Status duplication is L01. |
| Record v2 | v1 acceptance/new-version refusal and typed/null host fields are assigned. Offline send/success inconsistency is H03; run-id duplication is L02. |
| Record write | Atomic write and UTF-8/no-BOM requirements are sound; pre-entrypoint and terminated-run holes are H01/H02. |
| Hub file | Line parsing/token reuse/no evaluation are explicit; no new token threat model imposed. |
| RustDesk file | Six patterns, version and hash association checked against 1.5.3; no missing real asset was found. |
| Send | curl timeout/ordered URLs/no Python/fallback are specified. H02/H03 concern persistence timing and validity. |
| GUI rule | Linux graphical-target/display-manager detection and account session query are specified; unknown session is represented. Windows/Mac GUI policy is explicit. The Wayland limitation remains an acknowledged human-visible limitation, not an obligation to force X11. |
| Privacy scan | H11/H12 identify a producer conflict and missing artifact/input classes. |
| State id / validation stages | Planned checker exists in inventory, hashes HEAD and changed inventory inputs, and H1-6b recomputes identity rather than copying the handoff value. No fresh-full proof is claimed today. |

| Task rows reviewed | Assessment |
|---|---|
| PC | Manual/n/a unless authorized; no inferred commit/push grant. |
| 1 | Backup before kit edits is explicit. Pester wrapper works. Current pytest baseline is red, so stop condition 2 applies. |
| 2 | Record/JSON/name/v1-v2 tests assigned; H02/H03/H09 apply. |
| 3 | Windows PATH/library/record work assigned; H01/H02/H09 apply. |
| 4 | Mixed import summary, skip and exit behavior assigned; v1 retained. |
| 5 | Ubuntu elevation work is grounded; H08 blocks its green command. |
| 6 | H04/H05 prevent fresh Unix/Mac prerequisite delivery as written. |
| 7 | Three winget ids, missing-winget failure and refreshed Windows PATH specified. |
| 8 | Hub file and receiver modes/tests assigned; every five-case table row considered. |
| 9 | Both send halves assigned; H03 unresolved. |
| 10 | Asset/config caching and import password assigned; H07 unresolved. |
| 10a | GUI/member installation assigned; H06 omits Mac server lifecycle. |
| 11 | Docs and all four issue ids assigned to the correct issue pair; H08 exposes its late README edit. |
| 11a | Explicit human result; row 12 depends on it. Rule check must use the same Name/DisplayName property as the README creation line, and require an allowing rule on the declared Private profile; no narrower scope is requested. No actual new firewall line exists yet to contradict. |
| 11b | Deliberately independent of the human 11a result; offline tests can run before hub changes. |
| 12 | Depends on both 11a and 11b; prepare/receive/import/live values remain private. H10's same-session binding is also needed here. |
| 13 | Human rerun follows 12; H10 is its concrete stale-record false pass. |
| 14 | Other-family machine is an explicit human/missing-dependency gate, not a hidden agent prerequisite. |
| 15 | Mac is an explicit human gate with screen permissions; H04–H06 still require code fixes first. |
| 16 | BUILD_PLAN absence confirmed; its n/a check is appropriate. |
| H1-1, H1-2 | Numeric rows/human blocks and fresh suites/state identity considered. A valid B row is not silently treated as a live pass. |
| H1-3, H1-4, H1-5 | No-MEU/no-API claims match absent paths; handoff template exists and peer-read row is explicit. |
| H1-6 | Canonical handoff and evidence promotion assigned; H11 must be fixed. |
| H1-6a, H1-6b | AC coverage and independently recomputed state checks invoke real validators. |
| H1-7, H1-7a, H1-7b | Independent execution review, target-bound parsing, round cap and approval barrier are explicit. No implementing-agent-authored-check objection is made. |
| H2-1, H2-2 | Reflection template/schema and real validator exist. |
| H2-3, H2-3a, H2-3b, H2-3c | Metrics, grouping n/a, issue-pair consistency and main-tree n/a considered; H12 omits metrics from scan inventory. |
| H2-4, H2-5 | Final lint/privacy plus manifest/message are assigned; H11/H12 affect public closeout. Noreply identity rule and no attribution trailer are retained. |
| COMMIT, H2-6 | Commit remains n/a without human direction; final statuses/lint are assigned, with no push. |

### Decision Log assessment

| Decision | Assessment |
|---|---|
| D-1 | Sound: retain and back up the human's edits before changes; do not replace them with committed historical kit bytes. |
| D-2 | Sound within the ruling: independent stdlib HTTP receive avoids a fleet.py service prerequisite. Linux curl is a package dependency with an explicit missing-curl result, rather than universally assumed present. |
| D-3 | Sound as a declared limitation: stable RustDesk, session reporting and a known issue, without forcing a login change. |
| D-4 | Sound for the stated dangling alternative: bash launch, ordered elevators and auto repair are appropriate; no default-provider switch is requested. |
| D-5 | Hub-only storage/reuse is sound; the no-member-command-line transport claim fails (H07). |
| D-6 | Sound under the human's explicit plain-LAN/full-admin ruling; no TLS or additional trust-model finding. |

### Executed evidence

```json
{
  "schema_version": "evidence.v1",
  "check_id": "M1-wide-plan-review",
  "command": null,
  "procedure": "Read both complete target files with numbered lines; inspect the current kit, launchers, named docs and validators, peer plan and gate wrappers; trace every task row, named definition, WP and AC; compare current primary documentation and RustDesk 1.5.3 source; attempt the refutations recorded above.",
  "observer": "Codex",
  "cwd": ".",
  "scope": "41 task rows, WP-K0 through WP-K7, AC-1 through AC-26, named definitions, D-1 through D-6, PR/DR checklist",
  "phase": "manual",
  "exit_code": null,
  "result": "fail",
  "tested_state": "Unstarted target plan; four declared human kit edits; no implementation handoff or new checker/test files",
  "output": "12 blocking delivery/control findings and 3 nonblocking repeated-definition notes; no hardening findings. Referenced executables exist or are explicitly scheduled for creation."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "task-contract",
  "command": "rtk proxy python -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-15-usb-kit-usability/task.md *> C:/Temp/zorivest/usb-kit-plan/uk2-review-r1/task-lint.txt",
  "cwd": ".",
  "scope": "target task contract",
  "phase": "static",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "Current unedited target task.md",
  "output": "OK: 41 row(s); 10-column table (with builder_model); 39 row(s) fully checked; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "existing-pester",
  "command": "rtk proxy pwsh -NoProfile -Command '$env:TEMP=\"C:/Temp/zorivest/usb-kit-plan/uk2-review-r1\"; $env:TMP=$env:TEMP; & ./docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1 scripts/tests/SetupMember.Tests.ps1; exit $LASTEXITCODE' *> C:/Temp/zorivest/usb-kit-plan/uk2-review-r1/existing-pester.txt",
  "cwd": ".",
  "scope": "existing SetupMember Pester suite and unchanged peer wrapper selfchecks",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "Existing peer wrapper and existing suite; no new USB tests exist",
  "output": "Pester gate PASS: Result=Passed Passed=65 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0. Gate selfchecks also passed."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "existing-fleet-regression",
  "command": "rtk proxy pwsh -NoProfile -Command '$env:PYTHONDONTWRITEBYTECODE=\"1\"; $env:TEMP=\"C:/Temp/zorivest/usb-kit-plan/uk2-review-r1\"; $env:TMP=$env:TEMP; & P:/zorivest/.venv/Scripts/python.exe -X utf8 -m pytest scripts/tests/test_fleet_agent.py scripts/tests/test_fleet_bootstrap.py -q -p no:cacheprovider --basetemp C:/Temp/zorivest/usb-kit-plan/uk2-review-r1/pytest-temp; exit $LASTEXITCODE' *> C:/Temp/zorivest/usb-kit-plan/uk2-review-r1/existing-pytest.txt",
  "cwd": ".",
  "scope": "existing fleet agent and bootstrap tests",
  "phase": "targeted",
  "exit_code": 1,
  "result": "fail",
  "tested_state": "Existing code/tests; no implementation changes for this plan",
  "output": "1 failed, 322 passed in 297.71s. FAILED scripts/tests/test_fleet_agent.py::test_ac38_the_skills_hold_the_member_route_and_the_billing_rule at line 2546: lines[339:343] is a PowerShell example, not BILLING_RULE. This is a pre-existing fixed-line assertion failure; row 1's baseline stop condition applies."
}
```

The targeted baseline failure is **not** a new kit regression or an additional plan-design finding: the plan correctly stops on it. Execution must honor that stop and resolve it through the stated human gate, rather than quietly accepting it or changing the pin during kit work. The full core/scripts suite was not run in this review.

Parse-only observations: Git Bash located by walking upward from the installed Git executable; `bash -n` returned 0 for both current Unix shell files. The PowerShell AST parser reported `parse_errors=0` for the current Windows setup script. The default Python can import pytest. These observations establish available harness/parser prerequisites, not a claim that the not-yet-written USB tests pass or have valid Red evidence.

## Verdict

`changes_required` — resolve H01–H12 through `/plan-corrections`, keeping the human's four kit files untouched during plan correction. Reconcile the record/send contract, repair fresh-Mac and Unix tool delivery, make Windows denial and user-stop outcomes durable, select a password mechanism satisfying the stated argv constraint, correct row 5's order, bind live gates to newly received runs, and cover all public artifacts with redacted evidence and the promised Privacy scan. L01–L03 do not block.

No live hardware claim is made. In addition to the findings, execution currently faces the reproduced baseline stop. The next review remains in this same rolling file; the plan loop cap is 3 rounds. No correction, implementation, commit or push was performed by this review.

## Recheck (2026-11-15)

**Workflow:** `/plan-critical-review`, Round 2 of 3.
**Agent:** Codex.
**Current verdict:** `changes_required` (PR-6 procedural exception).

Executing this plan should preserve each member's setup outcome, deliver the requested tools and full SSH administration, and configure RustDesk for the hub. This round cannot determine whether the corrected plan delivers that objective: the required correction-census dispositions are absent, so the protocol stops the substantive review before severity assessment.

### Scope and prerequisite result

The targets remain `docs/execution/plans/2026-11-15-usb-kit-usability/implementation-plan.md` and its sibling `task.md`. The full-admin/usability ruling applies unchanged. PC and COMMIT are not authorized by this review; no execution, commit or push was performed.

`core/.agent/workflows/plan-critical-review.md:256` requires both an untruncated raw census and a correction log assigning every hit an `updated` or `confirmed-consistent` disposition. It explicitly says an undispositioned census is a pre-verdict procedural gate and to **"return `changes_required` naming only that, and do not review the corrected content this round"**. Lines 287–291 repeat that exception. `core/.agent/workflows/plan-corrections.md:191`–193 and :227–245 specify the census and correction-log producer.

### Procedural gate P01 — census has no per-hit disposition log

**Blocking:** yes. **Severity:** not rated (the workflow's procedural exception). **Confidence:** High. **Status:** open.

The resubmission lists the intended fixes, but names no census receipt or per-hit correction log. Neither target file contains a census/log reference. The rolling handoff ended at Round 1, with no Corrections Applied section or dispositions. Discovery found `the existing receipt C:/Temp/zorivest/usb-kit-plan/uk2-census-r2.txt` (25 nonblank hits) and `the existing receipt C:/Temp/zorivest/usb-kit-plan/uk2-census-r2b.txt` (8 nonblank hits). Both were read completely. They contain numbered text matches, without file-path qualification or a corresponding per-hit disposition log. The first includes earlier spellings of changed predicates. A targeted scan of the 26 top-level `uk2*` text/script files found no `confirmed-consistent`, `blast-radius census`, `census disposition` or `correction log` markers. The Round 2 scratch directory was empty on initial inspection.

**Failure caused:** the reviewer cannot audit which matching sites the corrector updated or confirmed, including the old/new semantic variants. PR-6 therefore prohibits accepting the correction submission for substantive re-review. This is not a claim that any of H01–H12 remains technically broken, and no new kit defect is asserted.

**Recommendation:** through `/plan-corrections`, name the raw, untruncated old/new census receipts and add a correction log assigning each `file:line` hit an `updated` or `confirmed-consistent` disposition, with semantic variants covered. Preserve Round 1. The current two match lists alone do not satisfy that requirement. Then resubmit for the remaining plan-review round; the cap is 3 unless the human changes it.

### Prior pass summary

| Prior findings | Round 2 result |
|---|---|
| H01–H12 | Fix verification deferred by PR-6; neither accepted nor rejected this round. |
| L01–L03 | Repeat-definition verification deferred by PR-6. |
| Declared baseline / known-failure gate changes | Not assessed this round; the earlier test result above remains historical Round 1 evidence. |

### Checklist Results

Procedure R2-P0, observer Codex: read the protocol, template and v1 schema; inspect both target files and the complete rolling handoff for correction-census/log references; discover and read both current `uk2-census-r2*` receipts in full; search the scoped correction artifacts for per-hit dispositions; inspect read-only git status and implementation-handoff existence; run the task-contract linter. No network or member operation was performed.

| Check | Result | Command / procedure | Exit | Evidence |
|---|---|---|---|---|
| PR-1 Plan/task alignment | n/a | — | — | Substantive review withheld at PR-6. |
| PR-2 Not-started confirmation | pass | R2-P0; `rtk git status --short` | null | Four declared human kit edits; target plans and review untracked; no project implementation handoff. Task header remains draft. |
| PR-3 Task contract completeness | pass | `rtk proxy python -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-15-usb-kit-usability/task.md` | 0 | 41 rows; 39 command rows checked; 2 source-read exemptions; dependencies resolve and are acyclic. |
| PR-4 Validation realism | n/a | — | — | Substantive review withheld at PR-6. |
| PR-5 Source-backed planning | n/a | — | — | Substantive review withheld at PR-6. |
| PR-6 Handoff/corrections readiness | fail | R2-P0 | null | P01: two raw match lists found; no named per-hit disposition log. |
| PR-7 Scope discipline | n/a | — | — | Substantive review withheld at PR-6. |
| PR-8 Reachability and totality | n/a | — | — | Substantive review withheld at PR-6. |
| PR-9 Single-statement discipline | n/a | — | — | Substantive review withheld at PR-6. |
| DR-1 Claim-to-state match | n/a | — | — | No current correction acceptance or implementation claim reviewed. |
| DR-2 Residual old terms | n/a | — | — | Substantive review withheld at PR-6. |
| DR-3 Downstream references | n/a | — | — | Substantive review withheld at PR-6. |
| DR-4 Verification robustness | n/a | — | — | Substantive review withheld at PR-6. |
| DR-5 Evidence auditability | fail | R2-P0 | null | Same procedural gate P01; correction dispositions cannot be audited. |
| DR-6 Cross-reference integrity | n/a | — | — | Substantive review withheld at PR-6. |
| DR-7 Evidence freshness | pass | R2-P0 and fresh linter run | null | Current precondition observations only; no historical test run represented as fresh. |
| DR-8 Completion versus residual risk | n/a | — | — | No implementation completion is claimed. |

```json
{
  "schema_version": "evidence.v1",
  "check_id": "R2-P0-correction-census-prerequisite",
  "command": null,
  "procedure": "Inspect the complete rolling review and both plan files for census/log references; read both uk2-census-r2 receipts completely; scan the 26 top-level uk2 text/script artifacts for disposition/log markers; inspect read-only status and project handoff existence.",
  "observer": "Codex",
  "cwd": ".",
  "scope": "Round 2 PR-6 precondition",
  "phase": "manual",
  "exit_code": null,
  "result": "fail",
  "tested_state": "Current unstarted plan resubmission; four declared human kit edits preserved",
  "output": "Two census match lists found (25 and 8 nonblank hits); no named correction log or per-hit dispositions. PR-6 stops substantive review."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "R2-task-contract",
  "command": "rtk proxy python -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-15-usb-kit-usability/task.md",
  "cwd": ".",
  "scope": "target task contract",
  "phase": "static",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "Current target task.md",
  "output": "OK: 41 row(s); 10-column table (with builder_model); 39 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"
}
```

### Verdict

`changes_required` — P01 only, under the mandatory PR-6 procedural exception. Supply the correction-census dispositions before the next substantive review. WP-K0–WP-K7, AC-1–AC-26, D-1–D-7, all task-row semantics and all Round 1 fixes remain unassessed in Round 2; this review does not assert full coverage. Only the canonical rolling verdict file was changed. No kit, fleet, test, plan or other documentation file was changed.

---

## Corrections Applied (2026-11-15, after Round 2)

> **Verdict**: `corrections_applied` (the planner's corrections; not a review verdict)
> **Corrector**: the planning session (Claude); the round 3 review stays with Codex.

### P01 — per-hit census dispositions

The census was run again on the final text of both plan files: one `rg -F -n` sweep per value form,
unfiltered, each into its own receipt, with an index of exit codes and hit counts. The receipts are
in the folder `C:/Temp/zorivest/usb-kit-plan/uk2-census-r3/` (index `00-index.txt`); the script is
`C:/Temp/zorivest/usb-kit-plan/uk2_census.py`. The per-hit log is `correction-log.md` in the same
folder. It names each file:line hit once per sweep, with `updated` or `confirmed-consistent` and the
reason. Semantic variants are declared per value (old, new and variant forms; the direction is in each
receipt name).

Blast-radius census: 22 values changed, 77 variants swept, 177 sites found, 5 updated, 172 confirmed consistent.

The five sites updated in this pass, after the census was read:

- `implementation-plan.md:172` — the PowerShell `CancelKeyPress` handler ended the step with status
  `interrupted`, which contradicts the Step definition (`ok`, `failed`, `skipped`). It now ends the
  running step `failed` with detail `interrupted`.
- `implementation-plan.md:352` (AC-2) — the same correction for `PipelineStoppedException`.
- `implementation-plan.md:351` (AC-1) — "with `interrupted`" became "with detail `interrupted`"
  (wording only; the meaning was already right).
- `implementation-plan.md:109-110` (the D-7 summary in User Review) — it named fewer places than the
  Decision Log's D-7. It now also names the ssh remote command string, the inbox and a log.
- `implementation-plan.md:686` (Verification §2) — the usb-only targeted run wrote
  `uk2-targeted.txt`, the receipt name of row 11b's fleet run. It now writes `uk2-verify-usb.txt`.

Hits confirmed consistent that a reader could take as stale:

- `-rfE` (10 hits): only on runs of `test_fleet_usb.py` (and `test_fleet_bootstrap.py` in row 11).
  Neither file holds the known failure, so pytest's own exit code is the right gate there. Every run
  that includes `test_fleet_agent.py` (rows 1, 11b and H1-2, Verification §3) goes through
  `check_kit.py --pytest <receipt> --exit $code`.
- `127` at lines 284 and 422: IP ranges (`127.0.0.0/8`), not elevator exit codes. The fallback codes
  are stated once, in WP-K2.
- `sudo bash`: the root re-run inside the elevator chain (WP-K2 step 2), the problem history
  (line 34), and AC-9's negative check. No launcher and no README line uses it.
- `--cask`: only in AC-12's negative "(no `--cask`)".
- `names only` (Out of Scope, the `agy` row): it means that the request names only the kit problems.
  It is not about closeout names.

### Round 1 findings — where each fix is (unchanged from the round 2 prompt)

H01 Windows elevation (WP-K1, AC-2, Files Modified, task row 3) · H02 checkpoints and the finalize
from the exit handler (Record write, AC-1, AC-4, AC-6) · H03 Delivery is not a step, and `ok` never
depends on it (AC-15, row 9) · H04 `homebrew` before `pwsh` on macOS (AC-12) · H05 the Account
environment and `tool_links` (AC-8, AC-10 to AC-12) · H06 the macOS launchd start and the Ready wait
(WP-K5 steps 3–5, AC-17, AC-18) · H07 D-7 (AC-19) · H08 row 5 changes the README launch lines ·
H09 `--red` refusals (WP-K0, `--selftest`) · H10 `live --receive` (WP-K7, rows 12–15, Verification §5)
· H11 placeholders in closeout files (WP-K7, H1-6) · H12 the Privacy scan scope and classes · L01–L03
one definition each for step status, run id and fallback codes · Baseline: KI
`FLEET-AC38-BILLING-LINE-PIN` and `check_kit.py --pytest` (five KIs: AC-21, row 11, H2-3b).

### Verdict

`corrections_applied` — ready for round 3 (the last round of the cap of 3).

---

## Recheck (2026-11-15)

**Workflow:** `/plan-critical-review`, Round 3 of 3 (final round).
**Agent:** Codex.
**Current verdict:** `changes_required`.

Executing this plan should preserve each member's setup outcome, return it to the hub, install the requested tools, establish full SSH administration and configure RustDesk. The corrected design addresses the original delivery failures, but the prescribed elevation/restart commands and the early send-interruption gate still prevent faithful execution on the paths below.

### Scope

Both complete target files were reviewed, against the current USB kit, both READMEs, named package docs/tools and the peer `2026-11-04-fleet-agents` gate and Pester wrapper. Below, **plan** means `docs/execution/plans/2026-11-15-usb-kit-usability/implementation-plan.md`; **task** means its sibling `task.md`.

The human's full-admin/usability ruling governs. No hardening requirement is added. This review grants no execution, commit or push. The superseded hardening plan was not a review target. Only this canonical rolling review file was changed in the repository; review scratch/source copies and test receipts are under `the review folder C:/Temp/zorivest/usb-kit-plan/uk2-review-r3/`. No setup script or fleet operational command was run; no hub, member or SSH host was contacted; no credential, key, token or password file was opened.

### Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| H13 | High | yes | behavior | **High confidence. Windows self-elevation loses argument boundaries for spaces.** `Start-Process -ArgumentList` joins its array with spaces; it does not preserve each element as one child argument. Substituting a script under `E:\Fleet Kit\setup-windows.ps1` into the prescribed unquoted `<self>` makes the elevated PowerShell receive `-File E:\Fleet ...`, so it cannot load the script. A Windows Account containing spaces similarly splits `<user>`. Accepting UAC then produces an elevation-failed record and skips setup, rather than installing the kit. Violates WP-K1 Windows elevation, AC-2 and PR-4. | plan:320; task:53; `.agent/fleet/usb/fleet_usb.py:36` | Specify a child command line with literal escaped quotes around the script path and Account value, and cover a space-containing drive folder/account at the child argument boundary. Keep the canceled-UAC fallback. | open |
| H14 | High | yes | behavior | **High confidence. Mac RustDesk restart bootstraps an already-loaded GUI job.** Step 3 bootouts only `system/com.carriez.RustDesk_service`, then unconditionally bootstraps the GUI agent whenever its domain exists. After a successful first setup, the distinct `gui/<uid>/com.carriez.RustDesk_server` registration still exists; repeating `bootstrap` fails instead of restarting it. Step 5 repeats the same sequence for a TOML fallback, so this can also fail within the first setup after step 3 already loaded the agent. Under Step failure handling, `rustdesk` becomes failed and the run's `ok` is false. Ignoring that bootstrap error instead would leave the existing server process running with its old in-memory configuration. Violates the restart prescription, the kit's repeat-run contract, AC-18/AC-26 and PR-4. | plan:500–504; plan:518; plan:540; task:61; `.agent/fleet/usb/README.md:65` | Specify lifecycle handling for the GUI job as well as the daemon: unload the existing job before bootstrap, or deliberately retain/restart it with a supported operation. Cover a second setup and the same-run fallback restart with a stub that refuses duplicate registration. | open |
| H15 | High | yes | behavior | **High confidence. Row 2's green gate requires the member Send scheduled for row 9.** AC-1 now includes a real file-run case in which stub `curl` terminates the script specifically during Send and the final drive record retains pending delivery. Row 2 requires AC-1 and then runs the entire new pytest file, but its implementation is WP-K1's record/runner work; row 9 owns adding Send to the setup scripts, after rows 3–8. The current Unix script has installer curl calls but no record POST. With row 2's scoped deliverable, the required send-time stub cannot be reached; omitting/skipping that case leaves AC-1 unproved, while writing the future Send early changes the declared row ownership/order. Violates PR-1/PR-4 and the task's green-before-next-row sequence. | plan:351; task:52; task:59; task:109; `.agent/fleet/usb/setup-unix.sh:126` | Assign the send-interruption portion of AC-1 to row 9 and add/run it there, retaining the record/step interruption cases in row 2; alternatively explicitly move the required Send implementation into the earlier row and reconcile row 9's Red contract. | open |
| L02 | Low | no | clerical | **High confidence. The run-id regex is still restated at the argument boundary.** The Run id definition and the argument table both spell out the same regex. This Round 1 note remains; it causes no behavioral ambiguity. Violates PR-9 only. | plan:144; plan:617 | Replace the boundary's regex literal with a reference to Run id. | open |

### Evidence and attempted refutations

- **H13:** [Microsoft's Start-Process documentation, ArgumentList and Example 7](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process#-argumentlist) explicitly describes joining the array and the need to include quote characters for arguments containing spaces. The initial CMD launch correctly quotes its path at plan:317; that does not quote the second, self-elevated launch. Neither target constrains the drive folder to a space-free path, and the existing Windows `USER` rule permits spaces. AC-2 mocks the child result without checking this serialization. This is a successful-UAC argument transport failure, materially different from H01's canceled-UAC/no-writer path. No elevation was attempted by this review.
- **H14:** the cited [1.5.3 agent plist](https://raw.githubusercontent.com/rustdesk/rustdesk/1.5.3/src/platform/privileges_scripts/agent.plist) and [daemon plist](https://raw.githubusercontent.com/rustdesk/rustdesk/1.5.3/src/platform/privileges_scripts/daemon.plist) define separate jobs. [RustDesk's Mac lifecycle source](https://raw.githubusercontent.com/rustdesk/rustdesk/1.5.3/src/platform/macos.rs) explicitly bootouts GUI/user agent registrations separately from the system daemon before bootstrapping them during its update lifecycle. Its `start_os_service` starts service IPC, not an implicit unload/reload of an existing GUI agent. The plan's sentence that the jobs are restarted states the desired outcome; the listed commands do not perform it. The fallback's reference to step 3 reproduces the same issue. AC-18's fresh-Mac stub requirement checks first registration only. This is an already-loaded-job failure introduced by the new sequence, distinct from H06's absent fresh-Mac producer. No Mac runtime result is claimed.
- **H15:** compared the whole Step/Record write/Send definitions, WP-K1, WP-K4, AC-1 and rows 2/9. The named definitions establish the eventual behavior, but do not assign Send implementation to row 2. AC-1 explicitly runs the script as a file with stub commands; mocking an entire Send function would not prove its stipulated curl-interruption case. The existing installer curl calls occur during steps, before finalization, and cannot substitute for interruption after finalization during Send. This is the new send-interruption subcase's dependency, not a recurrence of H08's README ordering defect, which is fixed.
- **Config syntax concern rejected:** [the 1.5.3 custom-server parser](https://raw.githubusercontent.com/rustdesk/rustdesk/1.5.3/src/custom_server.rs) accepts the plan's plain host/key string. No encoded-config requirement is added.
- **D-7 accepted:** [the 1.5.3 CLI](https://raw.githubusercontent.com/rustdesk/rustdesk/1.5.3/src/core_main.rs) consumes the password as its argument and sends it over IPC. The revised guarantee expressly permits that one member child argument. No additional host-key, token, installer or member/LAN threat model is imposed.
- **Baseline treatment accepted:** a fresh targeted run reproduced only the declared fixed-line assertion at `scripts/tests/test_fleet_agent.py:2546`. This review did not rerun the full pytest suite and does not promote the historical full-suite count to a fresh observation. The one-id gate, its refusal of errors/other failures and its fail-when-the-known-test-passes behavior are consistent with the declared KI/G36 boundary.

### PR-6 census audit

P01 is **fixed**. Read the census producer and index, all raw receipts, and the correction log in `the census folder C:/Temp/zorivest/usb-kit-plan/uk2-census-r3/`. Parsed its 77 declared old/new/semantic-variant literals without executing the producer, independently reran each literal's unfiltered `rg -F -n --` search on the two current targets, and compared complete line multisets with the stored raw receipts. Cross-file output order can vary; no content or exit-result mismatch remained after accounting for that ordering.

All **298 receipt hit occurrences** have exactly one disposition and a reason in their corresponding log section. They cover **177 unique file:line sites**, with **5 unique updated sites and 172 unique confirmed-consistent sites**, matching the correction summary. All 22 changed-value groups are declared. Zero-hit variants retain their receipts and confirmations. There are no truncated or undispositioned hits. The consistent-but-repeated boundary regex is L02 above; passing the census prerequisite does not erase that substantive observation.

### Prior Pass Summary

| Finding | Recheck result and current evidence |
|---|---|
| H01 | Fixed for canceled elevation: plan:316–327, AC-2 at :352, Files Modified at :640 and task:53 assign the unelevated launcher, Run id/Account handoff and parent finalization. H13 concerns a different successful-UAC failure. |
| H02 | Fixed persistence design: Record write at plan:163–175 checkpoints before elevation and after steps, finalizes catchable exits and declares forced-kill incompleteness; AC-1/2/4/6 at :351–356 cover it. H15 concerns scheduling the newly added Send-interruption subcase. |
| H03 | Fixed: Step list at plan:143 excludes Send; Delivery at :159–162 and Send at :205–211 leave `ok`/exit independent; AC-15 at :453 requires an offline importable success; task:59 agrees. |
| H04 | Fixed: plan:138–141, :403 and AC-12 at :416 put Homebrew before formula-based PowerShell. The current Homebrew formula documentation confirms the command. |
| H05 | Fixed environment specification: plan:176–194 defines Account environment and SSH Tool links; AC-8/10/12 and live checks at :587–595 use them, without assuming a login shell. |
| H06 | Fixed fresh startup prescription: plan:491–510 names both jobs, the app executable and Ready polling; AC-18 at :540 covers first bootstrap. H14 is the distinct already-loaded lifecycle defect. |
| H07 | Fixed by the expressly revised D-7 guarantee: plan:107–110, :524–534, AC-19 at :541 and Decision Log :786–796 agree. |
| H08 | Fixed: plan:386–388 and task:55 assign README launch-line edits to row 5. |
| H09 | Fixed: plan:240–251 rejects pytest setup/collection/teardown errors and Pester block/container failures, uses module imports and requires corresponding selftests at :264–271. The peer Pester summary exposes the required fields. |
| H10 | Fixed: plan:437–439 and :584–595 bind receipt count/name/run identity and distinguish reruns; task:65–68 and Verification :700–708 pass each row's receive receipt; selftest covers stale/zero/same-run cases. |
| H11 | Fixed: plan:597–599 and task:76 require placeholder identities in public closeout and keep raw receipts outside the repository. |
| H12 | Fixed prescribed scope/classes: plan:279–302 covers all proposed public artifacts, including both reviews and slug-specific metrics, with five classes and the exact guide exception; task:90 repeats the final scan. No further privacy threat model is added. |
| L01 | Fixed: Step owns the status enumeration at plan:132–136; Record v2 refers to it. |
| L02 | Still open, nonblocking: plan:617 repeats plan:144. |
| L03 | Fixed: fallback codes appear once as the elevator predicate at plan:373–376; AC-7 refers to that predicate. The other `127` hits are address ranges. |
| P01 | Fixed: complete receipt/disposition audit above; substantive review proceeded. |

### Wide coverage audit

Every named definition was checked: Account, Name rule, Step, Step list, Run id, Record v2, Delivery, Record write, Account environment, Tool links, Test root, Hub file, RustDesk file, Send and GUI rule (plan:119–214). The checkpoint/delivery/import boundaries agree. H13 affects Account transport, H14 the RustDesk lifecycle, H15 the timing of Send verification, and L02 the repeated Run id spelling.

| Work package / AC coverage | Assessment |
|---|---|
| WP-K0 / AC-22 | Backup before kit edits, temporary checker selftests, explicit gate baseline, single known-failure allowlist and public-output scan are assigned; checker creation precedes its callers. |
| WP-K1 / AC-1–AC-6 | Name normalization, v1 compatibility, v2 schema/checkpoints, Windows PATH and import failure summaries reviewed. H13 and H15 survive; original no-record/offline contradictions are corrected. |
| WP-K2 / AC-7–AC-9 | Bash launch on FAT/exFAT, Account selection, ordered elevators, fallback termination, dangling-link repair and visudo fallback are coherent. README work is now in the owning row. |
| WP-K3 / AC-10–AC-12 | Apt/dnf/winget routes, same-run discovery, snap-to-archive fallback, formula order and SSH tool reachability reviewed against current kit and Mac canon. No additional delivery finding. |
| WP-K4 / AC-13–AC-15 | Token reuse, URL selection, receive routing/status/count/timeout, atomic record replacement, independent delivery result and offline success agree. H15 affects when Send's interruption case runs. |
| WP-K5 / AC-16–AC-19 | Asset selection/reuse, install paths, GUI/session decisions, hash check, startup/readiness, config fallback, id discovery and hub-only password storage reviewed. H14 survives; narrowed password guarantee is sound. |
| WP-K6 / AC-20–AC-22 | README/manifest/bootstrap changes, explicit known-issues pair, five KIs and package/coverage/privacy gates agree. Unchanged bootstrap tests permit the planned Windows-section addition and retain empty Unix sections. |
| WP-K7 / AC-23–AC-26 | Each live row requires its own accepted record, full access and tool checks; fresh/rerun identities differ; key count/password hash are compared privately. Human/other-family/Mac availability gates and later-change reruns are explicit. These tests remain unexecuted. |

| Task row(s) | Assessment |
|---|---|
| PC | Explicit n/a without commit direction; no commit or push authorized. |
| 1 | Backup/checker/baseline ordering and exact full/Pester commands reviewed; known-id pytest gate is required. |
| 2 | H15: the full AC-1 send-interruption case depends on row 9. Other record/name/schema work has its tests. |
| 3 | H13: quoted child argument transport is missing; the canceled-child record behavior itself is fixed. |
| 4 | v2 summary/import follows reader work; AC-6 covers missing host key, offline delivery and checkpoint exit behavior. |
| 5 | Elevator/Account/launcher changes and README line edits precede AC-7/8/9's green run. |
| 6 | Unix prerequisites and Account/SSH environment assertions assigned to AC-10/12. |
| 7 | Windows winget/PATH behavior assigned to AC-11 and the copied Pester gate. |
| 8 | Hub prepare/receive and real temporary HTTP integration tests assigned to AC-13/14. |
| 9 | Send plus both platform AC-15 halves and offline end-to-end check assigned; H15 requires moving its additional interruption check here or moving implementation earlier. |
| 10 | Asset/config state and password transport/reuse tests assigned to AC-16/19. |
| 10a | Both platform RustDesk implementations/tests assigned; H14 affects the Mac sequence. |
| 11 | Docs, five issues and explicit issue-triage pair scheduled; bootstrap regression included. |
| 11a | Human server/firewall gate remains explicit; hub check emits no host/key value. |
| 11b | Known-failure-aware fleet pytest, both Pester suites and package gates precede live runs. |
| 12 | Requires 11a/11b, prepare, background receiver, current accepted identity, import and fresh live checks. |
| 13 | Requires fresh run, separate receiver/run id and private key-count/password-hash comparison. |
| 14 | Other-family human/missing-dependency gate has its own receipt and record binding. |
| 15 | Mac human/permission/missing-dependency gate has its own receipt; H14 can prevent its setup success. |
| 16 | BUILD_PLAN absence matches the current tree. |
| H1-1 | Numeric implementation-row completion scan considered together with evidence-gated B-row rules. |
| H1-2 | Fresh full/Pester/package checks, tested state and live-rerun-on-relevant-change rule are assigned. |
| H1-3 | No-MEU basis matches the absent local registry. |
| H1-4 | No-API basis matches the absent API package. |
| H1-5 | Handoff template exists; newest peer handoff is a source-read instruction. |
| H1-6 | Canonical handoff, red checks, private backup, tested state and placeholder-only identities assigned. |
| H1-6a | Existing AC coverage tool invoked with the real plan/handoff paths. |
| H1-6b | Existing durable-evidence tool receives a recomputed state; changed-state rerun is explicit. |
| H1-7 | Independent dispatch/corrections governed by execution-session and the named ledger; no implementing-agent-check objection. |
| H1-7a | Review parse binds mode, target, round cap and receipt to the canonical execution review. |
| H1-7b | Existing approval check consumes the matching review-state receipt; approval remains a separate gate. |
| H2-1 | Reflection template/schema source reads point to existing files. |
| H2-2 | Existing validator checks the new reflection against those sources. |
| H2-3 | Metrics append assigned; slug row existence checked. |
| H2-3a | Grouping n/a basis is explicit for this direct human request. |
| H2-3b | Five KI ids plus YAML/Markdown render consistency checked with the explicit pair. |
| H2-3c | Main-tree/no-credits basis explicit. |
| H2-4 | Final task lint and privacy scan cover reflection/metrics after creation. |
| H2-5 | Manifest/message and noreply identity check assigned; old plan excluded; no attribution trailer. |
| COMMIT | n/a without the human's commit direction; no push. |
| H2-6 | Final statuses and task lint assigned after closeout. |

All validation/prose tool paths were inventoried: 44 distinct referenced file paths were checked. The absent checker/wrapper, USB test files, execution handoff/review and reflection are explicitly scheduled outputs; absent BUILD_PLAN/MEU/worktree artifacts are stated n/a premises. No missing, unscheduled executable was found. Public docs, kit commands and template/schema files cited by those rows were read or checked at their named locations.

### Decision Log assessment

| Decision | Assessment |
|---|---|
| D-1 | Sound: back up and build on the human's four edits; retain their bytes during review. |
| D-2 | Sound: standalone stdlib HTTP receive avoids fleet-service/share setup. The reasoning's claim that curl exists before any install is stale wording; WP-K3 installs it and WP-K4 explicitly reports `no curl`, which govern behavior. |
| D-3 | Sound declared limitation: stable RustDesk, session reporting and the Wayland KI; no forced session change. |
| D-4 | Sound: bash entry and elevator fallback/repair avoid requiring a working default sudo link; no privilege reduction requested. |
| D-5 | Sound: password created/reused only on the hub and transported on SSH stdin. |
| D-6 | Sound under the human's plain-LAN/full-admin ruling. |
| D-7 | Sound revised interface guarantee: the one RustDesk child receives the member-side password argument; prohibited outputs/storage remain explicit. |

### Checklist Results

**Manual procedure R3-WIDE (observer: Codex; exit: null):** read both full numbered plans, all current kit entrypoints/READMEs, named local docs and closeout tools; compare peer gate/Pester forms; trace all 41 task rows, 15 Named definitions, eight WPs, 26 ACs and seven decisions; audit correction receipts/log against fresh literal searches; check cited primary sources; attempt the refutations above. No proposed checker or new USB test was represented as already implemented or passing.

| Check | Result | Command / procedure | Exit | Evidence |
|---|---|---|---|---|
| PR-1 Plan/task alignment | fail | R3-WIDE | null | H15: full AC-1 Send-interruption gate precedes the assigned Send implementation. |
| PR-2 Not-started confirmation | pass | R3-WIDE; `rtk git status --short` | 0 | Four declared human kit edits; plans/review untracked; no implementation handoff or new USB tests/checkers. |
| PR-3 Task contract completeness | pass | `rtk proxy python -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-15-usb-kit-usability/task.md` | 0 | 41 rows; 39 command rows checked; two source-read exemptions; dependencies resolve and are acyclic. |
| PR-4 Validation realism | fail | R3-WIDE | null | H13/H14 prescribed lifecycle commands fail on supported normal-use inputs; H15 cannot prove the full early AC as sequenced. |
| PR-5 Source-backed planning | pass | R3-WIDE | null | AC sources, human ruling and seven decisions are classified; no unsupported scope expansion demanded. |
| PR-6 Handoff/corrections readiness | pass | R3 census procedure above | 0 | 77 complete receipts; 298 occurrences/177 sites; every occurrence dispositioned with a reason. P01 fixed. |
| PR-7 Scope discipline | pass | R3-WIDE | null | Seven Out of Scope rows have human/local/research bases; no disguised or unscheduled contract deferral found. |
| PR-8 Reachability and totality | pass | R3-WIDE | null | Checkers have scheduled production callers and negative selftests; receive/live identity, error classifications and atomic file replacement are specified. Delivery defects are recorded under PR-1/4. |
| PR-9 Single-statement discipline | partial | R3-WIDE; repeated-literal searches | 0 | L02 remains; other two Round 1 repeat notes fixed. No conflicting live success/status definition found. |
| DR-1 Claim-to-state match | pass | R3-WIDE | null | Corrections exist in the plan text as mapped above; no implementation completion claim accepted. L02 is explicitly retained. |
| DR-2 Residual old terms | partial | R3-WIDE and census | 0 | L02's regex restatement and D-2's stale curl rationale remain nonblocking. |
| DR-3 Downstream references | pass | R3-WIDE / path inventory | null | Launchers, README, manifest, bootstrap and public closeout outputs assigned; no rename/move with an unassigned downstream consumer. |
| DR-4 Verification robustness | fail | R3-WIDE | null | H13's serialized child arguments, H14's loaded GUI job and H15's scheduled producer are not resolved by their current tests/row order. |
| DR-5 Evidence auditability | pass | R3-WIDE; census audit; commands below | null | Raw census/log cross-check, line evidence, primary links and actual exit/results are recorded. |
| DR-6 Cross-reference integrity | fail | R3-WIDE | null | H15's early AC ownership conflicts with row 9; otherwise peer/canonical gate forms align. |
| DR-7 Evidence freshness | pass | Fresh lint, Pester, known-failure and parse runs; R3-WIDE | null | Current observations distinguished from historical full-suite counts; no live result claimed. |
| DR-8 Completion versus residual risk | pass | R3-WIDE | null | Unstarted plan; hardware rows and open delivery failures remain explicit. |

```json
{
  "schema_version": "evidence.v1",
  "check_id": "R3-census-and-wide-review",
  "command": null,
  "procedure": "R3-WIDE and the PR-6 census audit described above: independently reproduce every declared literal sweep and compare complete receipt content and per-hit dispositions, then trace every target row/definition/WP/AC/decision against current files and cited sources.",
  "observer": "Codex",
  "cwd": ".",
  "scope": "Both complete target files; current kit; named docs/tools; peer gate forms; correction receipts/log",
  "phase": "manual",
  "exit_code": null,
  "result": "fail",
  "tested_state": "Unstarted plan with four declared human kit edits preserved",
  "output": "PR-6 passed: 77 variants, 298 receipt occurrences, 177 unique sites, 5 updated and 172 confirmed-consistent sites. Full review found H13-H15 and retained nonblocking L02."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "R3-task-contract",
  "command": "rtk proxy python -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-15-usb-kit-usability/task.md",
  "cwd": ".",
  "scope": "Target task structure",
  "phase": "static",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "Current unchanged task.md",
  "output": "OK: 41 rows; 39 command rows fully checked; dependencies resolve and are acyclic; source-read exemptions H1-5 and H2-1."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "R3-existing-pester",
  "command": "rtk proxy pwsh -NoProfile -File docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1 scripts/tests/SetupMember.Tests.ps1",
  "cwd": ".",
  "scope": "Existing suite and copied-wrapper source, with TEMP/TMP redirected into the review scratch folder and all output captured there",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "Existing peer wrapper and unchanged existing suite",
  "output": "Pester gate PASS: Result=Passed Passed=65 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0; gate selfchecks passed."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "R3-known-baseline-failure",
  "command": "rtk proxy P:/zorivest/.venv/Scripts/python.exe -X utf8 -m pytest scripts/tests/test_fleet_agent.py::test_ac38_the_skills_hold_the_member_route_and_the_billing_rule -q -rA -p no:cacheprovider --basetemp C:/Temp/zorivest/usb-kit-plan/uk2-review-r3/pytest-temp",
  "cwd": ".",
  "scope": "Only the declared known-failure id; bytecode disabled, temporary files/output kept in the review scratch folder",
  "phase": "targeted",
  "exit_code": 1,
  "result": "fail",
  "tested_state": "Existing unchanged fleet test and skill",
  "output": "1 failed in 0.25s: scripts/tests/test_fleet_agent.py:2546 compares lines[339:343] with BILLING_RULE; those positions contain a PowerShell example. This is the declared baseline issue, not a new finding."
}
```

Parse-only checks also passed: Git Bash `bash -n` for the current `setup-unix.sh` and `Setup Mac.command` returned 0; PowerShell AST parsing of the current Windows setup script reported zero errors. Those checks establish parser prerequisites only. New USB tests/checkers and member behavior remain unexecuted.

### Verdict

`changes_required` — H13, H14 and H15 block faithful execution; L02 does not. P01 and the original High findings' specific correction targets are verified as addressed, with the distinct new failures separated above. The final round has now been consumed: **3 of 3**. Do not start execution or another automatic plan-review round. Any correction phase follows `/plan-corrections`; a further review/advance requires the human to resolve the round-cap stop. No correction, implementation, commit or push was performed here.

🕐 Completed: 2026-11-15 12:19 (EST)

---

## Corrections Applied (2026-11-15, after Round 3)

**Corrector:** Claude (the planner). This section does not set `approved`.
**Human ruling at the round cap:** the human typed "just fix them and run exectution" (USER_EXPLICIT, 2026-11-15). Execution starts without a fourth plan round; the execution review (task row H1-7) reviews these fixes.

| Finding | Fix | Where |
|---|---|---|
| H13 | `Get-ElevatedArgs` returns one string, `-NoProfile -ExecutionPolicy Bypass -File "<self>" -RunId <id> -ForUser "<user>"`, with literal quotes around the script path and the Account; the "Elevated arguments" paragraph says why (`Start-Process` joins and does not quote). AC-2 adds a probe test: a temp folder whose name holds a space, the Account `Lab User`, an unelevated `Start-Process` on a probe script, both values received intact. Task row 3 names `Get-ElevatedArgs`. | plan WP-K1 "Windows elevation"; AC-2; task row 3 |
| H14 | Step 3 boots out `gui/<uid>/com.carriez.RustDesk_server` before its bootstrap, as it already did for the system daemon, and names the pair the **macOS restart**; step 5 refers to it. AC-18 adds a stub `launchctl` that fails `bootstrap` on a loaded label: a second setup run and a same-run TOML fallback both end `ok`, and every `bootstrap` follows a `bootout` of the same job. Task row 10a names the restart. | plan WP-K5 steps 3 and 5; AC-18; task row 10a |
| H15 | The interruption during the Send moved from AC-1 (row 2) to AC-15 (row 9, which writes the Send). AC-1 says so in one sentence. | plan AC-1, AC-15 |
| L02 | The argument boundary row says `--run-id` "matches the Run id definition"; the regex is now written once (the Run id definition). | plan Boundary Inventory |

**Stale-repeat sweep:** `rg -n` over both plan files for `SIGTERM`, `ArgumentList`, `Get-ElevatedArgs`, `bootstrap gui`, `bootout`, the run-id regex, `during the Send`, `jobs restarted` and the old array form `'-File',<self>`. The receipt is `uk2-r3fix-sweep.txt` in the scratch folder `C:/Temp/zorivest/usb-kit-plan/`. Every hit is one of the new texts above or the single Run id definition; the old array form and "jobs restarted" have no hit.

### Verdict

`corrections_applied` — H13, H14, H15 and L02 fixed. The plan loop is closed at the cap by the human's ruling; no fourth plan round runs.
