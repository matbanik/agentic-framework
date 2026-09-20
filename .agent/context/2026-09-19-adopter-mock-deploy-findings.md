# Consuming-agent mock deploy findings (2026-09-19)

**Source:** first install of this package into a net-new repo `P:/fw-adopt-probe`, walked as a consuming Cursor agent through ADOPTION-GUIDE Steps 0–8 plus a Step 9 dry walk (plan + task write, no MEU implementation, no live review dispatch, no git commit).
**Audience:** maintainers of `P:/agentic-framework`.
**Companion evidence:** Zorivest adopter gaps in [2026-09-18-zorivest-evidence-framework-gaps.md](2026-09-18-zorivest-evidence-framework-gaps.md). This note is the *first-install* half of that picture.
**Friction log (frozen):** `P:/fw-adopt-probe/_probe/adopter-friction-log.md` (SHA-256 `1CCFC346…BE9D80`, IDs F001–F036). Method limitations: `P:/fw-adopt-probe/_probe/METHOD-AND-FREEZE.md`. Receipts: `C:/Temp/fw-adopt-probe/` (`RECEIPTS-INDEX.md`).

Every item below states what the consuming agent hit, the evidence, and what the framework should change. No patches were made to this package in this exercise.

---

## 1. Method

| | |
|---|---|
| Probe | `P:/fw-adopt-probe` — empty git repo + `hello.py` / `test_hello.py` |
| Receipts | `C:/Temp/fw-adopt-probe/` (local, outside repo) |
| Interview | canned Blocks A–F in `_probe/canned-interview.md` (Cursor / Windows / PowerShell / A10 workspace-root registry / D9 yes / E5 no paid dispatch) |
| Naive pass | Cursor Task subagent from this framework workspace, not a dedicated Cursor window on the probe. Custom Task subtypes therefore never loaded (F013). |
| How far | instantiate `--verify` 0; A10 registry copy **stopped**; MEU-1 `hello-greet` seeded; `docs/execution/plans/2026-09-19-hello-greet/{implementation-plan,task}.md` written; `lint_task_contract` OK 17 rows; three tool selftests 0; Git-bash `preflight.sh --phase build` exit 1 (`REFUSE: registry`); stop before `/plan-critical-review` |

Re-run in a window whose workspace *is* the probe before treating F013 (Task subtypes) or F032 (slash commands) as harness-absolute.

---

## 2. First-install findings

Priority: cost first, then how often a naive agent would hit it.

### 2.1 Workspace-root registry and instruction `.agent/` are the same path  [high, blocker]

- **What happened.** A10 fail-safe and ADOPTION-GUIDE Step 4 say: copy the package-root `.agent/` template onto a workspace-root `<project>/.agent/`. Step 2 already copied `core/.agent/` to that same path (docs, workflows, skills, context seeds). A whole-directory copy would delete the instruction tree. INSTANTIATE.md §2 lists *files* to copy; the guide says copy the *directory*. No merge procedure exists. The naive agent **stopped the overwrite** and left the catalog unfilled.
- **Evidence.** F014; receipt `C:/Temp/fw-adopt-probe/a10-collision-check.txt`; probe `.agent/` is the instruction copy (86 files); no `model-registry.yaml` in the project.
- **Could the agent have known the fix from shipped text?** No. Following both documents literally is the collision.
- **Framework change.** Pick one live layout and write it once: either (a) registry home is **never** `<project>/.agent/` when that tree already holds instructions, and A10 fail-safe becomes a **sibling** (`<project>/.agent-registry/`) or `AGENT_MODEL_REGISTRY_HOME`; or (b) Step 2 copies instructions to `.agent/` and Step 4 copies only the INSTANTIATE.md file list into named subpaths that do not wipe `docs/`/`workflows/`. The locate order in INSTANTIATE.md §1 must include the workspace-root home if that remains a supported choice — today it is **not a rung** (env file → `AGENT_MODEL_REGISTRY_HOME` → `%USERPROFILE%/.agent`).

### 2.2 An unfilled catalog cannot be completed without inventing snapshot ids  [high, blocker for registry]

- **What happened.** INSTANTIATE.md: empty `catalog` fails schema validation. F5 / A9 say bind classes. Human rule: do not paste another machine’s snapshots. The naive agent had no legal catalog source and no “toy bindings” fixture.
- **Evidence.** F015. `P:\.agent` exists on this machine and was correctly not copied.
- **Framework change.** Ship a **documented scratch catalog** (fake ids, clearly non-dispatchable) *or* an explicit “registry deferred” preflight skip with the same first-line contract as other checks. Do not use origin-machine `P:\.agent` as the Windows example (F003).

### 2.3 `Invoke-CodexDispatch.ps1` does not parse on Windows PowerShell 5.1  [high]

- **What happened.** ADOPTION-GUIDE Step 2a allows “PowerShell 5.1+ or pwsh”. A4d names the `.ps1` as canonical. `powershell.exe -File` on the instantiated wrapper: **ParserError** on UTF-8 em-dashes. `pwsh` 7.6.6 parses and exits 1 on missing PromptText (usage only; no live dispatch).
- **Evidence.** F021; `C:/Temp/fw-adopt-probe/codex-wrapper-help.txt`. Packaged and adopted files: **no UTF-8 BOM**, first bytes `5b 43 6d`, **10 em-dashes**. Same defect as Zorivest 4.2.
- **Could the agent have known?** No. The guide presents 5.1 as supported.
- **Framework change.** ASCII-only `.ps1` **or** UTF-8 BOM. Packaging test: every `.ps1` is ASCII or has a BOM. State in ADOPTION-GUIDE that the wrapper requires `pwsh` until that test exists.

### 2.4 Preflight registry check ignores the A10 home the adopter was told to use  [high]

- **What happened.** `bash tools/preflight.sh --phase build` (Git bash) failed: `registry home 'C:\Users\Mat/.agent' (from $USERPROFILE/.agent) does not exist`. `AGENT_MODEL_REGISTRY` and `AGENT_MODEL_REGISTRY_HOME` were unset (this session). Workspace-root `.agent/` is the instruction copy, not compiled JSON. `--phase build` still runs the registry check. Header promises first stdout line is `OK:`/`REFUSE:`; first line is the banner `preflight (phase=build)` (F025).
- **Evidence.** F023–F026; `C:/Temp/fw-adopt-probe/step9-preflight-gitbash.txt`.
- **Framework change.** Registry check must honour INSTANTIATE.md locate order **including** a project overlay / workspace-root compiled file. `--phase build` should skip registry if no dispatch this session, *or* say so. Fix the first-line contract. Ship `preflight.ps1` **or** name **which** `bash` on Windows (System32 WSL vs Git bash — F024: WSL reported `rg` FAIL and a Linux `$HOME/.agent`; Git bash reported `rg` PASS and `%USERPROFILE%/.agent`).

### 2.5 Templates are copied where the guide says, and read from where the workflows say  [high, recurring]

- **What happened.** Step 2: `core/templates/` → `<project>/.agent/templates/`. create-plan Step 4: read `docs/execution/plans/PLAN-TEMPLATE.md` and `TASK-TEMPLATE.md`. Review/handoff/reflection rows and create-plan §5 still name `.agent/context/handoffs/REVIEW-TEMPLATE.md`, `TEMPLATE.md`, and `docs/execution/reflections/TEMPLATE.md`. Those files are `HANDOFF-TEMPLATE.md` / `REVIEW-TEMPLATE.md` / `REFLECTION-TEMPLATE.md` under `.agent/templates/`.
- **Evidence.** F029, F033. Naive agent copied PLAN/TASK templates into `docs/execution/plans/` so the named paths existed (a guess).
- **Framework change.** One destination, named in ADOPTION-GUIDE **and** every workflow. Either copy templates to `docs/execution/plans/` and `.agent/context/handoffs/` under the old names, or change create-plan / TASK-TEMPLATE / delegated-plan-creation / development-lifecycle to `.agent/templates/`. MANIFEST already records the rename; the workflows were not updated.

### 2.6 Origin quality gate is still the registered D6  [high]

- **What happened.** After copy, `commands.md` and `quality-gate/SKILL.md` tell the adopter to run `uv run python tools/validate_codebase.py` against `packages/`. That file is not in the package (MANIFEST / UPDATE-CHECKLIST treat it as origin). `pytest tests/unit/`, `pyright packages/`, `ruff`, Graphify, `/mcp-audit`, Electron, `portfolio_balance.py` remain. Step 8 “no leftover pytest/ruff unless it applies” cannot be satisfied without a hunt across lifecycle prose. Naive agent guessed D6 = `pytest test_hello.py` and patched some files; Step 8 vocabulary box stayed **no**.
- **Evidence.** F004, F017, F020, F030, F034, F036. Packaged [core/.agent/docs/commands.md](../../core/.agent/docs/commands.md) L8 still says `output-evidence-policy.md` is MANIFEST-EXCLUDED (it is packaged — F016).
- **Framework change.** Registered validation argv in `commands.md` / quality-gate must be tools that **ship**, or a single `{{D6_GATE}}` token instantiate fills from PROJECT-PROFILE. Strike `/mcp-audit` from [core/.agent/workflows/README.md](../../core/.agent/workflows/README.md) (file is EXCLUDED). create-plan must not require `docs/build-plan/build-priority-matrix.md` when D3 is `docs/BUILD_PLAN.md`.

### 2.7 `instantiate.py` default target is the transfer package  [medium]

- **What happened.** `scripts/README.md` and the module docstring show `--dry-run` / `--verify` **without** `--root`. Default rewrites files next to the script (the package). ADOPTION-GUIDE always passes `--root <project>`. `cat > framework.vars` from the package cwd would write the vars file into the package.
- **Evidence.** F002. Probe used `--root P:/fw-adopt-probe` only because the coordinator prompt repeated the hard rule.
- **Framework change.** Refuse to run without `--root` unless `--in-place-package` is explicit. Examples in scripts/README.md must include `--root`.

### 2.8 Instantiate rewrites any text under `--root`, and does not rename agent files  [medium]

- **What happened.** Dry-run replaced tokens inside `_probe/adopter-friction-log.md` and `PROJECT-PROFILE.md` (adopter notes quoting `{{TOKEN}}`). After apply, `.cursor/agents/README.md` told the agent to rename `fw-adopt-probe-builder.md` → `<slug>-builder.md`, but the files on disk were still `{{PROJECT_NAME}}-builder.md` (content instantiated, **filenames** not).
- **Evidence.** F011, F012; `C:/Temp/fw-adopt-probe/rename-agents.txt`.
- **Framework change.** Exclude `_probe/`, `PROJECT-PROFILE.md`, and user notes from substitution; or only walk the copied core paths. Rename agent-def files as part of instantiate, or keep the README wording aligned with remaining filenames.

### 2.9 Required session files are not in the seed tree  [medium]

- **What happened.** create-plan / AGENTS.md require `.agent/context/current-focus.md`. Packaged context seeds do not include it. `meu_status.py` has no `add`; YAML comments point at `/session-grouping` or the CLI. session-grouping A4 says hand-edit. Naive agent created `current-focus.md` and hand-edited `meu-status.yaml`.
- **Evidence.** F027, F028.
- **Framework change.** Ship `current-focus.md` stub. Document `meu_status.py` as render/update-only; put the “hand-edit then render” rule in ADOPTION-GUIDE Step 4b, not only inside session-grouping.

### 2.10 Cursor slash table is documentation, not harness wiring  [medium]

- **What happened.** workflows/README lists `/create-plan` and ~17 other slash names. No `.cursor/commands/` (or `.claude/commands/`) is shipped. Naive agent followed the markdown by hand.
- **Evidence.** F032.
- **Framework change.** Ship command files for the driver named in A1, **or** retitle the table “workflow ids (not slash commands)” and say Cursor/Claude will not bind them until the adopter adds commands.

### 2.11 Relative INSTANTIATE links resolve to `P:/.agent` after copy  [medium]

- **What happened.** `harness-profiles.md` / `model-routing.md` link `../../../.agent/INSTANTIATE.md`. After Step 2 that is `<parent-of-project>/.agent/`, i.e. `P:/.agent` on this machine — origin layout, and the probe forbids writing there.
- **Evidence.** F005.
- **Framework change.** Link INSTANTIATE.md from a path that still works post-copy (package README / ADOPTION-GUIDE), or copy INSTANTIATE.md into the instruction tree at a stable relative location.

### 2.12 PROJECT-PROFILE is claimed SSOT and is not read  [medium]

- **What happened.** ADOPTION-QUESTIONS, ADOPTION-GUIDE, and PROJECT-PROFILE-TEMPLATE say every workflow reads `PROJECT-PROFILE.md`. Grep of `core/` : **zero** matches. The template also omits A4b/c/d, A6b, A9, A10, C3b, D8, D9, F3b — questions the interview requires.
- **Evidence.** Maintainer overlay; probe `PROJECT-PROFILE.md` was written by the agent from the canned interview, not consumed by create-plan.
- **Framework change.** Either add a create-plan / session-start “read PROJECT-PROFILE.md” step and keep the template in lockstep with ADOPTION-QUESTIONS, or stop calling it SSOT and treat it as an interview dump.

### 2.13 Shipped task/plan examples still use `pwsh -Command {` and `rtk`/`uv`  [medium]

- **What happened.** TASK-TEMPLATE.md and create-plan discovery cells wrap work in `rtk proxy pwsh -NoProfile -Command { ... }`. lint_task_contract **accepts** scriptblocks (`scriptblock-is-not-a-placeholder-ok`). Nested backticks in the intended H1-1 unchecked-row probe split the table cell (F035); the naive agent weakened the command so lint would pass. Zorivest 2.4: those cells break under a bash outer harness.
- **Evidence.** F034, F035; [core/templates/TASK-TEMPLATE.md](../../core/templates/TASK-TEMPLATE.md) H1-1/H1-7/H2-3/H2-4/H2-5; lint selftest arm name.
- **Framework change.** Template validation cells: one-line commands or `.ps1`/`.sh` paths. Lint should **refuse** `-Command {` and `\|` in cells (Zorivest 2.4), not bless scriptblocks. H1-1 must be expressible without nested backticks.

### 2.14 Copy-step PowerShell footguns are undocumented  [low, first-session cost]

- **What happened.** `{ Copy-Item … } *> receipt` stringified the scriptblock and **did not copy** (exit 0). `Copy-Item -LiteralPath …\templates\*` treated `*` as a filename.
- **Evidence.** F009, F010; `C:/Temp/fw-adopt-probe/step2-copy.txt`.
- **Framework change.** ADOPTION-GUIDE Step 2: give a copy recipe that is a real command (robocopy / `Copy-Item` of the directory, not a scriptblock redirect, not `-LiteralPath` + wildcard).

### 2.15 Cursor `injects_auto_approval` cell vs A2 fail-safe  [low]

- **What happened.** Harness table: Cursor `injects_auto_approval: no`. A2 fail-safe and merge rule: **yes**. Naive agent set resolved profile to yes.
- **Evidence.** F006.
- **Framework change.** Align the Cursor row with A2, or tell Step 3 to prefer the interview over the cell and say so in the table footnote.

### 2.16 Other origin residue the naive agent logged and worked around

| ID | Residue | Guess |
|----|---------|-------|
| F007 | `Invoke-CursorAgentDispatch.ps1` named, MANIFEST-excluded | did not call it |
| F008 | Pomera hard-gate; no interview question for search provider | left origin contract |
| F018 | `issue_triage/discover.py` maps `packages/core` | kept D8 defaults |
| F019 | `terminal-preflight` anti-pattern path `<INVALID-BACKSLASH-TEMP-PATH>` | left as example |
| F022 | wrapper still names `.benchmark-work/context-provider/` and a Headroom schema | did not call them |
| F031 | create-plan Step 5 auto-dispatch vs probe E5 / `plan_to_exec_gate: human` | stopped after plan+task |

---

## 3. Zorivest overlay

| Gap | First-install? | Notes |
|-----|----------------|-------|
| **4.1** registry env var | **Hit** | Unset env; locate skipped workspace-root; preflight demanded `%USERPROFILE%/.agent` (F003, F026). Wrapper loud-fail on unset was not reached (catalog never filled). INSTANTIATE Windows example is still `P:\.agent`. |
| **4.2** PS 5.1 / em-dash / no BOM | **Hit** | Identical bytes: `5b 43 6d`, 10 em-dashes, ParserError (F021). |
| **4.6** adopter tool drift | **Not reproduced** | Fresh copy from this package. Remains a mature-adopter / refresh problem (`sync --check`). |
| **1.1** gate truncates failures | **Not reproduced as a run** | `validate_codebase.py` is **not shipped**; it is still the registered command (2.6). Origin-only until D6 is replaced. |
| **1.2** closeout rules missing from templates | **Not reproduced** | No handoff written. Packaged `validate_closeout_artifacts.py` requires `## Acceptance Criteria` + `## Evidence` and derives reflection headings from the template — not the extra Zorivest mechanical rules (`### Delta:`, exact `## Corrections Applied`, `findings_per_round`). Those look like **adopter-side validator drift** (feeds 4.6) rather than this package’s first-install closeout. |
| **2.4** `pwsh -Command {` | **Hit in templates** | Still shipped; linter allows scriptblocks; naive agent avoided them by guessing (F035). |
| **2.1** census sweep | Not exercised | No new tables/ports. |
| **2.2** RED pyright | Not exercised | No RED row implementation. |
| **3.x** delegation / git-in-builder | **Not exercised** | `fresh_worker` effectively `none` in this session (F013). |
| **4.3** autogen drift / CRLF | **Not exercised** | No `resolve sync` (catalog unfilled). |
| **4.4** public-docs set | Authoring / refresh | Not a consuming-agent install step. |
| **4.5** slug checker scope | Not exercised | Checker not run `--enforce` on the probe. |
| **5.1** Electron `USERPROFILE` | Not exercised | No E2E. |
| **6** commit-hook friction | **Not exercised** | No commit (probe rule). |

---

## 4. Documentation blind spots

Rules a naive agent needed and did not get. Confirmations from the live walk are in parentheses.

1. **Two `.agent/` trees, one path.** Instruction copy vs registry home cannot share `<project>/.agent/` without a merge spec (2.1).
2. **Where templates live after copy** vs every `view_file` path in create-plan / TASK-TEMPLATE (2.5).
3. **How a Windows adopter runs `preflight.sh`:** which `bash`, that there is no `.ps1`, that `--phase build` still requires a live registry (2.4).
4. **`PROJECT-PROFILE.md` is not mechanically bound**; the template lags ADOPTION-QUESTIONS (2.12).
5. **Cursor has no shipped slash-command files**; `/create-plan` is a heading in a README (2.10).
6. **`validate_codebase.py` is origin-only**; D6 must replace it, and “grep for pytest/ruff” is not a sufficient translation procedure (2.6).
7. **`scripts/` stay in the transfer package** and `--root` is load-bearing; omitting it instantiates the package (2.7).
8. **Empty catalog is un-adoptable** without a scratch fixture or an explicit deferral (2.2).
9. **`meu_status.py` cannot register a MEU**; first `/create-plan` needs a hand-edit recipe in the adoption guide (2.9).
10. **`current-focus.md` is required and not seeded** (2.9).
11. **Agent-def filenames are not instantiated**; rename is a separate undocumented-until-README-in-agents-dir step, and that README is itself rewritten into a contradiction (2.8).
12. **Pomera is a hard gate** with no Block A–F question (F008).
13. **Copy recipe** must not use scriptblock `*>` or `-LiteralPath` wildcards (2.14).
14. **SIGN 1 vs `plan_to_exec_gate: human` vs “do not pay for review in a probe”** — three documents, three next actions after plan write (F031). Adopters need one sentence: *dispatch is mandatory unless C1/E5 forbids egress; then stop for the named human, and that stop is not SIGN 1.*

---

## 5. Suggested order (report only — do not patch in this exercise)

1. **2.1 + 2.2 + 2.4** — without these, no adopter gets a working registry or a green preflight. Align A10, locate order, INSTANTIATE copy list, and preflight.
2. **2.3 (Zorivest 4.2)** — PS 5.1 parse failure on the canonical dispatcher.
3. **2.5 + 2.9 + 2.7** — template paths, `current-focus.md` seed, instantiate `--root` required. These unblock create-plan without guesses.
4. **2.6** — registered D6 must be a shipped command; drop `/mcp-audit` and `packages/` from the default command card.
5. **2.13 (Zorivest 2.4)** — template cells and lint must agree; refuse scriptblocks.
6. **2.10, 2.12, 2.8, 2.11, 2.14–2.16** — slash commands, PROFILE SSOT, filename instantiate, link repair, copy recipe, remaining residue.
7. Zorivest **4.6** (`sync --check`) remains the mature-adopter follow-on; this mock did not age the tree.

Keep `P:/fw-adopt-probe` as the reproduction fixture. Do not add it as a submodule of this package.
