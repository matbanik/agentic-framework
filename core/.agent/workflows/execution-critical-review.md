---
description: Implementation-review-only critical review workflow. Reviews completed work handoffs for correctness, test rigor, and contract compliance.
---

# Execution Critical Review Workflow

Use this workflow to adversarially review **completed implementation work** that has produced handoff artifacts. This workflow produces findings only — it never fixes issues or reviews unstarted plans.

This is the workflow for prompts like:

- "Critically review the latest handoff"
- "Check if the claimed changes were actually completed"
- "Find regressions after a refactor"

// turbo-all
// NOTE: turbo-all sets SafeToAutoRun=true for non-destructive commands (rg, Get-Content, etc.).
// It does NOT override AGENTS.md §Commits: "Never auto-commit." Git commit/push still requires explicit user direction.

## Write Scope (Non-Negotiable)

This is a review-only workflow.

Allowed file writes:

- `.agent/context/handoffs/{plan-folder-name}-implementation-critical-review.md`

Forbidden file writes:

- all product code (`packages/`, `ui/`, `mcp-server/`)
- tests
- docs outside the canonical review handoff
- plan files
- existing work handoffs under review

If a finding suggests a fix, record it in the canonical review handoff and stop. Do not patch the repo. Use `/execution-corrections` for fixes.

---

## Role Sequence

1. `orchestrator` (scope + auto-discovery)
2. `tester` (evidence/verification commands)
3. `reviewer` (severity-ranked findings and verdict)

> `researcher` is optional only when external fact-checking is required.
> **No coder role.** This workflow produces findings only — never fixes. Use `/execution-corrections` to resolve findings.

---

## Auto-Discovery (No User Input Required)

The agent discovers the review target automatically.

### Discovery Steps

```powershell
# 1. Find recent execution plan folders FIRST
Get-ChildItem docs/execution/plans/ -Directory |
  Sort-Object LastWriteTime -Descending | Select-Object -First 5

# 2. Inspect the newest candidate plan's task state
Get-Content docs/execution/plans/<candidate>/task.md

# 3. Find most recent WORK handoffs (exclude review artifacts)
Get-ChildItem .agent/context/handoffs/*.md -Exclude README.md,TEMPLATE.md |
  Where-Object { $_.Name -notmatch '(critical-review|corrections|recheck)' } |
  Sort-Object LastWriteTime -Descending | Select-Object -First 10

# 4. Correlate handoffs to the candidate plan by date/slug
rg -n "<candidate-date>|<candidate-slug>|Create handoff:|Handoff Naming" \
  .agent/context/handoffs docs/execution/plans/<candidate>
```

### Mode Confirmation

Choose this workflow (implementation review) when:

1. Work handoff artifacts already exist for the target project
2. `task.md` shows implementation tasks are completed or in-progress
3. The user explicitly requested review of a completed handoff

If the plan is genuinely unstarted (no handoffs, all tasks pending), use `/plan-critical-review` instead.

### Correlation Rule

The agent must correlate the handoff and plan folder — not blindly pair the newest of each. Use the date prefix and slug to match.

### Project-Integrated Handoff Expansion (Required)

When the correlated plan folder represents a multi-MEU project, the latest handoff is only the **seed** — not the full review scope.

Expand the review to the full correlated handoff set when any of these are true:

1. `implementation-plan.md` has a `Handoff Naming` section with multiple handoff paths
2. `task.md` has multiple `Create handoff:` checklist items
3. The plan, reflection, or registry states that multiple MEUs were executed in the same project
4. Multiple same-date sequenced handoffs clearly belong to the correlated plan folder

When expansion triggers, required scope becomes:

- every handoff produced by that project
- the correlated `implementation-plan.md` and `task.md`
- shared project artifacts (`meu-status.yaml` SSOT, reflection, metrics)
- all changed files claimed across the full handoff set

### Scope Override

If the user provides explicit paths, use those instead of auto-discovery.

If the user provides one handoff path from a multi-MEU project but does not say `only`, expand to the full correlated handoff set.

### Canonical Review File Rule

Derive the review handoff path from the correlated execution plan folder:

- `.agent/context/handoffs/{plan-folder-name}-implementation-critical-review.md`

Example: `docs/execution/plans/2026-03-07-commands-events-analytics/` → `.agent/context/handoffs/2026-03-07-commands-events-analytics-implementation-critical-review.md`

If the canonical review file already exists, append a new dated section.

### {{PROJECT_NAME_TITLE}} Build-Plan Scope Rule

When the target artifact describes work on `docs/build-plan/`:

- Inspect `docs/build-plan/` only when:
  - the docs are the feature under review,
  - the handoff claims specific build-plan updates as evidence,
  - or a docs discrepancy appears to misstate delivered behavior, contracts, or test coverage.
- When in scope, inspect the **actual file state/changes** (not just handoff claims).
- If `git diff` is not sufficient, use direct file reads and explicitly say so.

---

## Workflow Steps

## Step 1: Discover and Scope the Review (Orchestrator)

Run the auto-discovery commands. Identify:

- **Primary review target**: the work handoff set correlated to the newest plan candidate
- **Seed handoff**: the most recent correlated work handoff
- **Secondary scope**: the execution plan folder whose date/slug matches
- **Claimed changes**: files changed, phrases renamed, sections removed/added, verification commands/results

---

## Step 2: Load Context and Evidence (Orchestrator + Tester)

Read:

1. Primary target artifact (seed handoff)
2. Correlated execution plan (`implementation-plan.md` and `task.md`)
3. Every sibling handoff identified from the correlated project
4. Claimed files from the full handoff set
5. Relevant related files likely to drift
6. Current diffs (`git diff`) for the claimed files when available
7. For {{PROJECT_NAME_TITLE}} build-plan sessions: actual changed `docs/build-plan/*` files

---

## Step 3: Run Critical Verification Sweeps (Tester)

Use fast, reproducible command checks. Prefer `rg`.

### Receipts Authoritative (do not re-run the suite to confirm a receipt)

> [!IMPORTANT]
> **A receipt that is present, complete, and matches the claim is the evidence. Do not
> re-run the full test suite to corroborate it.** The builder already paid for that run;
> repeating it inside the review buys no new information, and it is the single largest
> consumer of the review's timeout — a reviewer that spends 20 minutes re-running `tests/`
> and then times out has produced no verdict while still spending the round.

This is not permission to review on trust. Run a **targeted** command, and say in the
verdict's `checklist_results` which one and why, when the receipt is:

| Receipt state | What to do |
|---|---|
| Absent | Run the check yourself. A claim with no receipt is unverified, and "the builder says so" is not a `pass` row. |
| Truncated, or has no exit code | Re-run **that one command**, not the suite. |
| Self-contradictory (`0 failed` under a non-zero exit, a count that does not add up) | Re-run that one command; the contradiction itself is a finding. |
| For a command that is not the one the claim needs (a filtered subset presented as the whole suite, `--exitfirst`, a skipped file) | Finding. Name the gap; run the missing part if it is cheap. |
| Present, complete, consistent | **Read it. Do not re-run it.** Cite the receipt path in the checklist row. |

For GUI/E2E specifically: prefer a post-edit Playwright receipt over re-launching Electron
inside the reviewer — see the timeout note in `.agent/skills/cli-dispatch/SKILL.md`.

### Required Sweep Types

1. **Runtime / contract verification** — Does the delivered code satisfy the claimed API, UI, persistence, and round-trip behavior?
2. **Test rigor audit** — Do tests assert meaningful behavior, or do they trivially pass? (See IR-5)
3. **Negative-path / failure-path verification** — Tests and code cover rejected writes, missing data, invalid transitions?
4. **Claim verification** — Did the files/lines/behaviors mentioned in the handoff actually change?
5. **Cross-handoff consistency** — Shared totals, phase-gate claims, registry state consistent across the full project?
6. **Verification quality** — Are handoff checks strong enough?
7. **Evidence quality** — Commands/tests reproducible and auditable?
8. **Actual build-plan file changes** — When in scope, did claimed changes materially appear?
9. **Residual references / cross-file consistency** — Old names/phrases/slugs still present?

### Suggested Commands (Adapt Per Task)

```powershell
# 1) Read the primary review artifact
Get-Content <primary-artifact>

# 2) Check for stale references
rg -n "<old-term>" <relevant-dirs>

# 3) Inspect diffs
git diff -- <claimed-files>

# 4) List changes
git status --short -- <scope-dirs>
```

---

## Step 4: Adversarial Review (Reviewer)

Use the reviewer role output contract. Report **findings first**.

### Reviewer Method — Effort + Generate→Verify (D4, 2026-06-13)

- **Effort:** default `medium` for routine/contract-bound review, `high` for hard adversarial passes (risk paths, contract surfaces, concurrency/security). Reserve `max`/`xhigh` for explicitly-tagged verifiable deep sub-reviews only — more reasoning is not monotonically better for judge tasks (arXiv:2508.06225). See `.agent/skills/cli-dispatch/SKILL.md` §Reviewer Effort Policy.
- **Generate → Verify split:** Pass 1 generates candidate findings optimized for recall — report everything, including low-confidence items, each tagged with confidence + severity; do NOT self-filter for importance at this stage. Pass 2 verifies each finding against file state, citing the exact `file:line`, the violated rubric/AC, and a concrete failure scenario; **drop any finding without verifiable evidence, then apply the Materiality Gate below before assigning final severity.** This counters the over-acceptance bias of LLM judges.
- **Cross-vendor minority-veto:** when both Codex and Claude review, run them independently on the same rubric; any evidence-backed High finding from EITHER vendor blocks (`changes_required`). Agreement on a clean pass approves.
- **Format independence:** enforce the deterministic YAML verdict via structured output + low verbosity; never raise effort to fix format drift.

### Intent Anchor (Required First Output)

Before generating any finding, write 1–2 sentences stating what this execution was supposed
to deliver for the user (from the plan objective and ACs). The verdict must answer **"does
the delivered work achieve this intent?"** first. Every blocking finding must name the AC,
plan requirement, or checklist item it violates — a finding that cannot cite its violated
contract is an observation, not a blocker.

### Materiality Gate (Required — Applied During Pass 2)

Pass 1 recall is unchanged — generate everything. Pass 2 assigns final severity through
this gate:

1. **Clerical findings are `Low` and never block.** Typos, count/label transpositions,
   stale numbers in prose, row-numbering or cross-reference drift, Markdown table syntax,
   and template-compliance gaps are clerical whenever an intelligent reader can trivially
   infer the correct value. State the correction in one line inside the finding and move
   on. Clerical findings may not be rated `Medium`/`High` and may not contribute to
   `changes_required`.
2. **Out-of-contract observations never block.** A requirement you believe *should* exist
   but that no AC, spec, or checklist item states goes into a short
   `Out-of-Contract Observations` list (≤ 5 items, one line each) — never into the
   Findings table as a blocker. Do not re-litigate decisions already approved during plan
   review.
3. **Respect the declared trust boundary.** Review adversarially *within* the FIC/plan's
   declared threat model. You may challenge the boundary itself at most once per review
   target, phrased as an explicit open question — never as a repeated blocking finding.
4. **No nearby-mutation escalation.** Once a finding on a surface is fixed, a later-round
   finding on that same surface must demonstrate a NEW, materially different failure of
   delivered behavior. A deeper variant of the same mutation/attack class (another
   delimiter, another encoding form, a deeper filesystem race) is not a new finding —
   record it once as residual risk and accept the declared boundary.
5. **Do not block on the review machinery.** Defects in validation predicates,
   closeout-check regexes, or the verification harness itself are non-blocking unless you
   demonstrate a concrete false-pass of a *material product defect* (show the exact input
   that false-passes).
6. **Spend the review budget on code, not on bookkeeping.** Rules 1–5 say how to *rate* a
   clerical finding once you have it; this one says do not go hunting for them. Bureaucratic
   defects — stale counts, template-section compliance, artifact naming, roll-up headers,
   provenance/amendment wording, cross-reference drift — are a byproduct you report if you
   trip over one, never a search target. Budget: **at most 3**, one line each, in
   `Out-of-Contract Observations`. Every remaining minute goes to runtime behavior, contract
   correctness, and test rigor. A round that returns only bookkeeping findings has not
   reviewed anything — it has proofread. A *substantive* defect is never clerical merely
   because it lives in a document: a claim that is factually false about code, a citation
   that its cited source does not support, or an absence claim measured by a search that did
   not cover the surface it claims empty all stay at full severity.

### Functionality-First Rule

Prioritize:

1. Runtime behavior and API/UI contract correctness
2. TDD/test rigor and negative-path coverage
3. Persistence and round-trip correctness
4. Handoff claim accuracy
5. Documentation consistency

Documentation-only discrepancies are non-blocking by default unless they misstate delivered behavior, falsely claim tests, hide missing work, or create unsafe instructions.

### Implementation Review Checklist (Required)

| # | Check | What To Look For |
|---|---|---|
| IR-1 | Live runtime evidence | Integration test without dependency overrides exists and was run |
| IR-2 | Stub behavioral compliance | Stubs honor save→get consistency, filter semantics, correct `exists()` returns |
| IR-3 | Error mapping completeness | Every write-adjacent route maps `NotFoundError → 404`, `BusinessRuleError → 409`, `ValueError → 422` AND tests assert response body shape |
| IR-4 | Fix generalization | When a finding was fixed, similar instances in other files/routes were also checked and fixed |
| IR-5 | Test rigor audit | Every test file in scope is audited for assertion strength. Each test rated 🟢 Strong / 🟡 Adequate / 🔴 Weak. Any 🔴 is `Medium` minimum |
| IR-6 | Boundary validation coverage | For every write surface: explicit schema exists, negative tests cover malformed input, unknown fields handled, create/update parity verified |
| IR-7 | Deferral & AC-coverage integrity (controls C2/C3/C4) | (a) **Orphan / disguised deferral** — any AC/feature deferred to a MEU that is NOT scheduled in `meu-status.yaml`/grouping (e.g. "future MEU", "wiring session") is `High`: it is a SKIP, not a defer. **Also flag the disguise:** contract work relabeled `out-of-scope` to dodge the MEU-ID gate — an `out-of-scope` row whose *Basis* is blank, or whose cited build-plan lines do NOT actually omit the item, is the same SKIP (`High`). Verify the citation against the real source, do not trust the label. **Substance vs. labeling:** the `High` rating is for genuinely missing or disguised work; when the deferral is substantively evidenced but the label, MEU-ID reference, or row format is wrong, that is clerical (`Low`) — name the correct reference and move on. (b) **AC coverage** — every AC-ID in the plan appears in the handoff AC table; a silently dropped AC is `High`. (c) **Lifecycle evidence** — every `integration`-type AC is proven by an integration/contract test, not a unit test; an `integration` AC backed only by a unit test is `Medium` minimum (the "render-first, wire-later" skip class). |

#### IR-5 Test Rigor Grading Criteria

| Rating | Definition | Example |
|--------|------------|---------|
| 🟢 Strong | Asserts specific values, exercises real behavior, tests positive and negative paths | `assert delta.days == 30` |
| 🟡 Adequate | Tests the right thing but uses weak assertions | `assert "key" in result` |
| 🔴 Weak | Trivially passes even if code is broken | `try: fn() except: assert dir.exists()` |

Common weakness patterns to flag:

- Try/except safety nets
- Asserting only key existence instead of values
- Patching private methods
- Testing only "not found" path without insert+get round-trip
- Missing boundary assertions
- Data format assertions checking existence not content

### Docs Review Checklist (Required when docs are in scope)

| # | Check | What To Look For |
|---|---|---|
| DR-1 | Claim-to-state match | Handoff says a change happened and file state proves it |
| DR-2 | Residual old terms | Old phrase/slug variants still present |
| DR-3 | Downstream references updated | Indexes, cross-links, and anchors updated |
| DR-4 | Verification robustness | Handoff checks would actually catch regressions |
| DR-5 | Evidence auditability | Commands/diffs are reproducible |
| DR-6 | Cross-reference integrity | Architectural changes consistent across canonical docs |
| DR-7 | Evidence freshness | Handoff-claimed counts match reproduced command output |
| DR-8 | Completion vs residual risk | If gaps acknowledged, conclusion must NOT say "all ACs met" |

### Severity Guidance

- `Critical`: Dangerous instructions/security regressions
- `High`: Incorrect contracts, false implementation claims, broken runtime behavior
- `Medium`: Weak tests, verification quality, portability issues
- `Low`: Auditability, wording, minor evidence gaps, all clerical findings (Materiality Gate #1)

### Verdict Rule (Blocking Threshold)

`changes_required` requires at least one evidence-backed `High`/`Critical` finding in
Functionality-First priorities 1–4 (runtime behavior, contract correctness, test rigor,
persistence/round-trip, or a false implementation claim). Clerical, formatting, template,
or meta-validation findings alone — at any count — produce `approved` with correction
notes, not `changes_required`.

When approving with correction notes, record the surviving clerical/observation items in
the structured `findings` array with `blocking: false` — **do not** move them into
`summary` prose to make the array empty. `review-verdict.schema.v2.json` requires only
that no *blocking* finding survives an `approved` verdict; v1's "empty findings to
approve" rule is gone, because it forced reviewers to either suppress real observations
or withhold an approval the work had earned. A real observation belongs in `findings`
where it has an `id`, a `file_line`, and a `status` the next round can close.

Conversely, never choose `changes_required` merely to have a place to list non-blocking
notes: the schema refuses a `changes_required` verdict that names no blocking finding,
so that manoeuvre now fails validation in `review_ledger.py record` rather than
consuming a round.

---

## Step 5: Write or Update the Canonical Review Handoff (Required Exit Gate)

Write to: `.agent/context/handoffs/{plan-folder-name}-implementation-critical-review.md`

If that file already exists, append a new dated review update section — as a
`## Recheck ({YYYY-MM-DD})` heading, matching `REVIEW-TEMPLATE.md`.

> [!CAUTION]
> **One rolling file per body of work. The heading is the round counter.**
> `validate_closeout_artifacts.py` counts rounds as `1 + the number of "## Recheck"
> headings in this one file`, and that count is what it compares against the cap. So:
> - A **new file per round** (`…-review-r2.md`, `…-recheck.md`, `…-review-final.md`)
>   resets the count to 1 and defeats the cap without anyone deciding to. This is the
>   most available way to get an unbounded loop, and it looks like tidy file naming.
> - A recheck appended under a heading that is not `## Recheck` is not counted either.
> - `review_ledger.py` counts independently, from recorded rounds. The two counters are
>   deliberately separate: the ledger binds the dispatch, the file binds the artifact. If
>   they disagree, the **higher** number is the true round count — a disagreement means a
>   round went unrecorded or a file went unappended, and neither is a reason to keep going.

The workflow is incomplete until the canonical review handoff exists and is readable.

> **Start from** [`.agent/context/handoffs/REVIEW-TEMPLATE.md`](file:///{{PROJECT_ROOT}}/.agent/context/handoffs/REVIEW-TEMPLATE.md) (v2.1)
>
> **Verbosity control**: Set `requested_verbosity` in the review YAML frontmatter. See `.agent/docs/context-compression.md §Verbosity Tiers`.

Fill the template sections:
- `Findings` table with severity-ranked findings and file:line references
- `Checklist Results` with IR/DR check outcomes
- `Verdict` with explicit `approved` or `changes_required`

### Required Review Handoff Content

1. Scope reviewed (including correlation rationale and expanded handoff set)
2. Commands executed
3. Findings with file/line references
4. Explicit verdict (`approved` or `changes_required`)
5. Concrete follow-up actions
6. If not the first pass, a dated update heading

---

## Pre-Edit Guard

Before any file edit:

1. derive the canonical review handoff path for implementation review mode
2. verify the intended edit target exactly matches that canonical handoff path

If the target path is anything else, abort the edit and continue in findings-only mode.

---

## Step 6: Save Session Memory (Optional but Recommended)


- what was reviewed
- key findings
- whether fixes should be applied via `/execution-corrections`

---

## Step 7: Completion Timestamp (Mandatory Exit Gate)

> [!IMPORTANT]
> **Context-rot guard.** Re-read this workflow file before proceeding.
> If you are resuming after context truncation, this step will not exist in your context unless you re-read.

The **very last line** of the agent's chat response must be the timestamp skill output, copied verbatim.

This is a hard exit requirement for every `/execution-critical-review` response, including short rechecks.

Required sequence:

1. Re-read this workflow file to confirm all prior steps are complete.
2. Invoke the timestamp skill by reading `.agent/skills/timestamp/SKILL.md`.
3. Run the stamp script with the Windows redirect-to-file pattern:

```powershell
# // turbo
python .agent/skills/timestamp/scripts/stamp.py *> {{RECEIPTS_DIR}}/stamp.txt
```

4. Read `{{RECEIPTS_DIR}}/stamp.txt` with the file viewer.
5. Copy the file's single output line verbatim as the final chat line.

No text, bullets, caveats, or sign-off may appear after the timestamp line.

Compressed variant for rechecks:

```text
Recheck appended to <canonical-review-path>. Verdict: <approved|changes_required>. Key evidence: <one sentence>.
🕐 Completed: YYYY-MM-DD HH:MM (TZ)
```

The compressed variant still requires invoking the timestamp skill and copying its real output verbatim for the last line.

---

## Hard Rules

1. **Never fix issues during this workflow.** This workflow produces findings only. Use `/execution-corrections` to resolve findings.
2. **Do not approve based on phrase-only grep checks** when heading renames or link anchors are involved.
3. **Do not treat the handoff as source of truth**; treat file state + diffs as source of truth.
4. **Do not bury findings behind summaries**; findings come first.
5. **For implementation reviews, do not elevate documentation drift above broken behavior or weak tests.**
6. **When a correlated project produced multiple MEU handoffs, load all of them.** The newest is only the discovery seed.
7. **Never review a review.** Auto-discovery excludes `*critical-review*`, `*-corrections*`, `*-recheck*` handoffs.
8. **When implementation-review findings require changes, route the fix phase through `/execution-corrections`.**
9. **One rolling review file per target.** Keep implementation-review updates in the same `-implementation-critical-review.md` file.
10. **When test files are in review scope, audit every test for assertion strength (IR-5).**
11. **A weak or misleading test is `Medium` minimum when it can allow broken behavior to pass green.**
12. **Do not return a final response until the canonical review handoff has been created or updated successfully.**
13. **Do not modify any file unless the Pre-Edit Guard resolves to the canonical review handoff path.**
14. **Never block on clerical findings.** Apply the Materiality Gate: `changes_required` requires at least one evidence-backed `High`/`Critical` behavioral/contract finding (see Verdict Rule).
15. **Hold the execution's intent as the review target.** The question is "does the delivered work achieve the plan's objective?", not "is every artifact formality satisfied?" — and never escalate a fixed surface with a deeper variant of the same mutation class.

---

## Done Checklist

- [ ] No product files were modified
- [ ] Canonical review handoff was created or updated
- [ ] Review mode was correctly identified as `implementation`
- [ ] Verdict is explicit (`approved` or `changes_required`)
- [ ] Final user response includes the canonical review handoff path

---

## Output Contract

Return to the user:

- Auto-discovered targets (what was reviewed, correlation rationale)
- Findings (severity-ranked, file/line references)
- Open questions / assumptions
- Review verdict (`changes_required` or `approved`)
- Residual risk statement
- Path to the created or updated canonical review handoff

---

## Orchestration Flow

This workflow is part of a four-workflow orchestration cycle:

1. `/create-plan` → plan new work
2. `/plan-critical-review` → review a new plan before implementation
3. `/execution-critical-review` → review completed implementation work (this workflow)
4. `/execution-corrections` → resolve implementation-review findings

When to switch:

- Use `/plan-critical-review` for reviewing unstarted plans (not this workflow).
- Use `/execution-corrections` if the verdict is `changes_required` and the user wants fixes applied.
- Use `/create-plan` for new feature implementation.

## HARD STOP

> [!CAUTION]
> **Do NOT autonomously chain into `/execution-corrections` or any other workflow after completing this review.** You MUST stop here and report the canonical review handoff path to the user. The user decides what happens next.

**Workflow complete.** Report the handoff path and wait for user direction.
