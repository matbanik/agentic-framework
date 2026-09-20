# Framework gaps: evidence from Zorivest (2026-09-18)

**Source:** Zorivest (`P:/zorivest`), which adopted this framework. Most of the evidence comes from the SP-4 project (`2026-09-16-sp4-ai-review-stored-report-walking-skeleton`: MEU-578, MEU-581, MEU-586). The rest comes from the SP-2 and SP-3 closeouts that came before it.
**Audience:** maintainers of `P:/agentic-framework`.
**Scope:** only defects in the framework's templates, tools, skills and workflows, plus the adopter-sync problems they cause. Zorivest product defects are not included.

Every item below states what happened, the evidence (a file, commit or receipt), and what the framework should change. The items are in priority order: cost first, then how often the problem recurs.

Evidence paths without a prefix are relative to `P:/zorivest`. Receipts under `C:/Temp/zorivest/` are local to the Zorivest machine.

---

## 1. Gate and validator output

### 1.1 Gate output truncates the failures it exists to report  [high, recurring]
- **What happened.** The scoped MEU gate (`tools/validate_codebase.py --scope meu`) runs pyright and pytest across the whole repo and takes 38–42 minutes. On a failure it printed only the **first** pyright error (19 existed), plus pytest progress dots with no test ids. Getting the real failures took a separate 11-minute `pytest tests/unit` run. SP-3 had already recorded the same truncation and it was not fixed. SP-4 ran the gate six times.
- **Evidence.**
  - Reflection, Friction Log item 1: `docs/execution/reflections/2026-09-16-sp4-ai-review-stored-report-walking-skeleton-reflection.md`.
  - The Zorivest fix is commit `e2882142` (`fix(tooling): print full pyright/pytest failure detail from the MEU gate`), with 317 lines of tests in `tests/unit/test_validate_codebase_check_messages.py`.
- **Framework change.**
  - Any gate the framework ships or describes (`quality-gate` skill, `preflight.sh`, the gate contract in the docs) must print **every** failing diagnostic id and every `FAILED`/`ERROR` test id.
  - It must also say which checks ran repo-wide and which ran scoped.
  - Put this in the gate contract: "a failing check's output alone is enough to act on".

### 1.2 Closeout validator rules are missing from the templates  [high, recurring]
- **What happened.** `validate_closeout_artifacts.py` rejected the SP-4 handoff drafts four times. Each rejection was for a mechanical rule that `HANDOFF-TEMPLATE.md` does not state:
  - The exact heading `## Corrections Applied` is required.
  - Every Changed Files row needs its **own** `### Delta:` block, so a row cannot list several paths.
  - A table cell may not contain an escaped `\|`, because the splitter still counts it as a column.
  - Command cells may not contain `{`.
- **More rejections of the same kind in the review and reflection files:**
  - The round-2 canonical review table admits only that round's own `R2-F` ids. Carrying resolved R1 rows into it fails the check.
  - `review_churn` requires `findings_per_round`, which the template does not show.
  - The category vocabulary term is `weak_test`, but the template wording invites other spellings.
- **Evidence.**
  - Reflection, Friction Log item 1 ("Handoff structure").
  - Reflection, Workflow Signal Log item 10.
  - Patterns to DROP #2.
- **Framework change.**
  - Generate a "structural rules" section in each template from the validator's own rule table (single source), or have the validator print the template line each rule comes from.
  - Add a `--explain` mode that lists every rule.
  - Ship one known-good fixture per artifact type and test the validator against it, so a template edit that breaks the validator fails CI.

### 1.3 The review prompt's example block is never validated before dispatch  [medium]
- **What happened.** The H1-7 review prompt told the reviewer to carry resolved rows into the next round's canonical table, which the review-state validator rejects. Separately, `-OutputSchema` was not passed to the dispatch, so the reviewer's shape was not enforced from round 1. SP-3's RULE-1 had already asked for this.
- **Evidence.** Reflection, Rules Sampled row 5 ("Partial") and Patterns to ADD #4.
- **Framework change.**
  - `cli-dispatch` should run the review-state validator on the prompt's own canonical-block example before dispatching.
  - `Invoke-CodexDispatch.*` should refuse to run a review workflow without `-OutputSchema`, or default it.

## 2. Plan and task templates

### 2.1 No census sweep at planning time  [high]
- **What happened.** Adding one table and one port broke **five** shipped census pins, and the plan named none of them:
  - `test_empty_v1_manifest.py`
  - `test_ports.py` (×3)
  - the protocol set in `tools/validate_codebase.py`
  - an apply-test helper
  
  All were found only by running suites. Each became a mid-execution amendment (EA-2 items 4–6 and 8, EA-3 items 1–3). The same pattern hit SP-3's engine census (`tests/tooling/test_app_db_engine_census.py`, fixed in commit `8457c44f`).
- **Evidence.**
  - Reflection RULE-1.
  - `docs/execution/plans/2026-09-16-sp4-ai-review-stored-report-walking-skeleton/implementation-plan.md`, Execution Amendments.
- **Framework change.**
  - Add a mandatory "Census sweep" block to `PLAN-TEMPLATE.md`: for each new table, port, route or repository, grep `tests/` and `tools/` for sets that pin all of them, and list the declared edits.
  - Have `lint_task_contract.py` require the block whenever the plan adds any of those.

### 2.2 RED rows have no type or lint gate  [medium]
- **What happened.** RED tests reached the MEU gate carrying 19 pyright errors (row 2) and a TS2717 conflict plus an unused variable (row 6). Fixing them after the hash receipt meant amendments and re-hashes (EA-2 item 7, EA-5).
- **Evidence.** Reflection RULE-2.
- **Framework change.** In `TASK-TEMPLATE.md`, the RED-row validation must run pyright and eslint/tsc over the files the row wrote **before** the hash receipt.

### 2.3 Named statements do not state NULL semantics  [medium]
- **What happened.** `OVERLAY_SINK_IDENTITY` said "equals its complete derived row" but not how NULL compares. The implementation used `=`, and `NOT (... AND created_by = ?)` dropped rows with a NULL `created_by`. The execution review found this as R1-F1 (high).
- **Evidence.** Reflection RULE-3; `.agent/context/handoffs/2026-09-16-sp4-ai-review-stored-report-walking-skeleton-implementation-critical-review.md`.
- **Framework change.** Add a FIC/plan checklist line: any named statement that compares database rows must state NULL semantics (IS vs =).

### 2.4 `pwsh -Command { … }` task cells cannot run from a bash harness  [medium, recurring]
- **What happened.** Validation cells written as `pwsh -NoProfile -Command { … }` are mangled when the outer shell is bash. That is Claude Code's Bash tool, and Zorivest's `pwsh-scriptblock-echoed` memory records it. SP-3 and SP-4 both had to extract every such cell to a `.ps1` file.
- **More friction from task and plan cells:**
  - Escaped `\|` in regex cells is ambiguous: the H2-3a extracted regexes lost their escapes and had to be repaired by hand.
  - Literal 64-hex hashes in plan command cells trip `detect-secrets` at commit. In commit `7f332cd5` this needed a trailing `# pragma: allowlist secret` on `implementation-plan.md:716`.
- **Framework change.**
  - `TASK-TEMPLATE.md` should require validation commands as script files (`.ps1`/`.sh`) referenced by path, or as one-line commands with no scriptblock.
  - `lint_task_contract.py` should flag `-Command {`, `\|` inside table cells, and bare 40/64-hex literals without a pragma.

### 2.5 H1-2 re-runs a gate that already passed  [low]
- **What happened.** H1-2 re-ran the full 40-minute MEU gate on a tree that rows 9 and 13 had already gated green. Nothing changed in between.
- **Evidence.** Reflection, Friction Log item 3.
- **Framework change.** Let H1-2 cite an earlier green gate receipt when `git diff` since that receipt is empty. The receipt should record the tree hash.

## 3. Delegation and concurrency

### 3.1 Heavy gates run next to other agents' test runs  [medium]
- **What happened.** Row 5's second gate run failed integration only because two background agents were running pytest and editing files in the same working tree. Run alone, integration passed (3,186 tests). The false failure cost a 40-minute re-run.
- **Evidence.** Reflection, Friction Log item 1 and Patterns to DROP #1.
- **Framework change.** The `subagent-delegation` and `quality-gate` skills should say: never run a gate while another lane writes to the same tree. Give background lanes a worktree (`isolation: worktree`), or serialize.

### 3.2 A builder lane broke the no-git rule  [medium]
- **What happened.** The builder lane on row 8 ran `git stash`, which the lane contract forbids. The coordinator had to re-verify every RED hash.
- **Evidence.** Reflection, Workflow Signal Log item 12, row 8.
- **Framework change.**
  - The contract is prose only; enforce it. The `{{PROJECT_NAME}}-builder.md` template should deny git in its `tools` allowlist, or ship a PreToolUse hook that blocks `git` for builder or verifier lanes.
  - `.gitattributes` (item 4.3) matters here too, because a stash round-trip is also a line-ending round-trip.

### 3.3 Rate limits on delegated lanes  [low]
- **What happened.** The Fable lane hit a session rate limit mid-row (row 6) and was resumed with its context intact.
- **Framework change.** `subagent-delegation` should document resume-over-restart for rate-limited lanes. It should also require a lane to write its partial state (files written, receipt pending) before long steps.

### 3.4 `subagent-delegation/SKILL.md` alias list is stale  [low]
- **What happened.** During SP-4 the skill's alias list was flagged as stale against the capability-class routing that framework commit `49ad5f0` introduced. Line 18 still lists `model: sonnet|opus|haiku|inherit|<id>` under a `model-slug-ok` exemption, while the body routes by class (`builder`, correctness class). This was not re-verified line by line for this note.
- **Framework change.** Check the list against `.agent/docs/model-classes.md`. Point the frontmatter description at that doc, and let the slug checker own the alias list.

## 4. Adopter sync and tooling-test failures

Zorivest's `tests/tooling` suite had **12 failures** on 2026-09-17 (`C:/Temp/zorivest/tooling-fix-tooling-dir.txt`: 12 failed, 1036 passed). One was the engine census, fixed in Zorivest. The other 11 trace to framework packaging:

### 4.1 Registry lookup moved to an env var that adopters don't set  [high, 5 tests]
- **What happened.** A 2026-09-07 change moved registry resolution to `AGENT_MODEL_REGISTRY_HOME`. Nothing sets it on the adopter machine, and the `P:/.agent/ModelRegistry.psm1` copy is older than the one packaged at `.agent/tools/ModelRegistry.psm1`.
- **Failing tests.** All in `tests/tooling/test_framework_registry_template.py`:
  - `test_the_packaged_module_is_this_machines_module`
  - `test_an_instantiated_dispatch_resolves_through_the_adopters_registry`
  - `test_an_instantiated_dispatch_binds_the_adopters_overlay`
  - `test_a_dispatch_that_does_not_name_the_project_ignores_the_overlay`
  - `test_the_powershell_wrapper_accepts_the_same_env_var`
- **Framework change.**
  - `INSTANTIATE.md` and `UPDATE-CHECKLIST.md` should set or verify the env var.
  - The wrapper should fail loudly when the var is unset and name the fix.
  - Add a version stamp to `ModelRegistry.psm1`, and have `preflight.sh` compare the installed copy against the packaged one.

### 4.2 `Invoke-CodexDispatch.ps1` does not parse on Windows PowerShell 5.1  [high, 3 tests]
- **What happened.** `core/tools/Invoke-CodexDispatch.ps1` contains 10 em-dashes (for example the comments at L30, L124 and L289) and has **no UTF-8 BOM**; its first bytes are `5b 43 6d`. PowerShell 5.1 reads BOM-less files as the ANSI codepage, which breaks string parsing.
- **Failing tests.** All in `tests/tooling/test_framework_sanitize.py`:
  - `test_verify_reports_that_the_checker_ran_on_a_clean_tree`
  - `test_verify_exits_nonzero_on_a_planted_slug_in_core`
  - `test_verify_reports_autogen_drift_distinctly_from_a_tier1_slug`
- **Framework change.**
  - Replace the non-ASCII characters in `.ps1` files with ASCII, or save them with a BOM.
  - Add a packaging test that every `.ps1` is ASCII-only or has a BOM.

### 4.3 Autogen agent-file checks are fragile  [medium, 2 tests]
- **What happened.**
  - `test_drift_is_clean_on_the_real_tree` expects exactly four generated agent files. Zorivest added a fifth, `.cursor/agents/zorivest-opus.md`, deliberately marked "not autogenerated", and the drift check still counts it.
  - `test_sync_is_idempotent_on_the_real_tree` failed on a CRLF checkout and cleared after the sync rewrote the files as LF. That left five line-ending-only modified files in the Zorivest status, which had to be excluded from every commit.
  - The framework `.gitattributes` pins `eol=lf` for `*.sh` only.
- **Framework change.**
  - The drift check should honour the "not autogenerated" marker instead of a fixed count.
  - Pin `eol=lf` (or make the sync EOL-agnostic) for the generated `.claude/agents/*.md`, `.cursor/agents/*.md` and generated JSON.

### 4.4 Public-docs set is hard-coded  [low, 1 test]
- **What happened.** `test_requires_exact_public_doc_filename_set` fails because a README and an INSTALL were added to the renderer without updating the expected set. SP-3's authoring runbook also landed in an auto-publishing folder, and nobody decided whether it should be public.
- **Framework change.** Replace the fixed set and `REFERENCE_GUIDE_COUNT` with a manifest file, so adding a public doc is one deliberate edit. The check should print the command that lists the actual set.

### 4.5 Slug checker narrowed to root-level agent files  [low]
- **What happened.** `check_model_slugs.py` now inspects only root-level agent files, so templates under `core/` are skipped. This may be deliberate, but it isn't documented.
- **Framework change.** Document the scope in the checker's docstring and `model-classes.md`, or restore template coverage behind a flag.

### 4.6 Adopter tool copies drift from the framework  [medium]
- **What happened.** Zorivest's `tools/issue_triage.py` crashed on `--help` on a cp1252 console (U+2192 in a help string). The framework's `core/tools/issue_triage.py` already had the `stream.reconfigure(encoding="utf-8", errors="replace")` fix at L389–393, but the adopter copy had never received it. Zorivest re-fixed it independently in `e2882142`. `validate_closeout_artifacts.py` also differs between the two trees.
- **Framework change.**
  - Ship a `sync --check` (or add it to `preflight.sh`) that hashes each adopted tool against the framework version and reports drift.
  - Record the framework version each tool was copied from in a header line.

## 5. E2E harness (Electron, Windows)

### 5.1 Redirecting `USERPROFILE` aborts Electron on Windows  [medium]
- **What happened.** The walking-skeleton E2E died at `electron.launch` with exit `0x80000003` and no output. A six-way environment reproduction outside Playwright isolated it: redirecting `USERPROFILE` alone aborts the Electron main process (EA-6). The fix redirects `LOCALAPPDATA`, `APPDATA`, `HOME` and the app's `ZORIVEST_CONFIG_DIR` to a temp tree and leaves `USERPROFILE` real (`ui/tests/e2e/explore-sample-walking-skeleton.spec.ts` L135; plan `E2E_REAL_LAUNCH` and EA-6).
- **Framework change.** The `e2e-testing` guidance should say: never redirect `USERPROFILE`/`HOME` to isolate an Electron app on Windows; use the app's data-dir override. It should also keep the "isolate one env variable per run" diagnosis recipe (reflection, Patterns to KEEP #1).

## 6. Commit-time hook friction (recurring in every closeout)

- `ruff-format` rewrites files as a pre-commit hook. That changes the receipt hash of hash-locked RED test files (AST-equal, byte-different). SP-3 and SP-4 commit 1 both hit it.
- `detect-secrets` flags fake hashes and tokens in fixtures and plan command cells. Every occurrence needs an inline pragma: SP-4 commits `3b045592` and `7f332cd5`, and earlier the CC7, CC14 and SP-1 closeouts.
- **Framework change.**
  - `git-workflow/SKILL.md` §Commit Policy should state the retry protocol: re-stage after a rewriting hook; add a pragma at every fake-secret occurrence.
  - RED-hash receipts should hash the **ruff-formatted** file, or the RED row should run `ruff format` before hashing.

---

## Suggested order
1. Items 4.1, 4.2 and 4.6: they break every adopter's tooling suite or CLI today.
2. Items 1.1 and 1.2: highest recurring cost per project.
3. Items 2.1, 2.2 and 2.4: template and lint changes that remove classes of amendments.
4. The rest.
