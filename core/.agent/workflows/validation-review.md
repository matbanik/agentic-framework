---
description: Validation and adversarial review workflow for the Codex `independent_reviewer` — verify tests, review code, generate evidence bundle.
---

# Validation Review Workflow (Codex Agent)

Use this workflow when validating a completed MEU. Codex is the **validation agent** — runs full test suite, performs adversarial review, and issues a verdict.

## Prerequisites

- Read the MEU handoff artifact at `.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-handoff.md`
- Read ALL changed files listed in the handoff (full content, not just diffs)
- Read `docs/build-plan/testing-strategy.md` for test standards
- Read `.agent/roles/reviewer.md` for adversarial checklist

## Steps

> [!CAUTION]
> **Actor model.** This workflow has two actors:
> - **Orchestrator** (the implementing agent / primary driver — see `.agent/docs/harness-profiles.md`) — executes **Step 0 only**: constructs the prompt, dispatches to Codex CLI, reads output, incorporates findings.
> - **Codex CLI** (`independent_reviewer`, external agent) — executes **Steps 1–7**: runs tests, performs adversarial review, issues verdict.
>
> **Self-review prohibition.** If you wrote the code being reviewed, you are the orchestrator — STOP at Step 0. Do NOT execute Steps 1–7 yourself. See `AGENTS.md` §Execution Contract.

### 0. Dispatch to Codex CLI (ORCHESTRATOR ONLY)

> [!CAUTION]
> **This step is mandatory.** Do NOT skip it. Do NOT execute Steps 1–7 yourself.
> If Codex CLI is unavailable or rate-limited, follow `.agent/skills/cli-dispatch/SKILL.md` §Rate-Limit Fallback Protocol. Self-review is **never** an acceptable fallback.

**Pre-flight:**
1. Load `.agent/skills/cli-dispatch/SKILL.md` for dispatch mechanics
2. Clear stale output: `Remove-Item {{RECEIPTS_DIR}}/dispatch/validation -Recurse -ErrorAction SilentlyContinue`
3. Create dispatch dir: `New-Item -ItemType Directory -Force -Path {{RECEIPTS_DIR}}/dispatch`
4. **Open the review loop.** Once per body of work, not once per round — `begin` is
   idempotent-by-refusal, so a second call on an open loop tells you the loop already
   exists rather than resetting its round count:
   ```powershell
   $LOOP_ID = "validation-{project-slug}-{YYYY-MM-DD}"
   python tools/review_ledger.py begin `
     --loop-id $LOOP_ID `
     --review-mode execution `
     --producer "<the agent that wrote the code>"
   ```
   `--producer` is what makes the self-review prohibition above enforceable rather than
   advisory: `record` refuses a verdict whose author equals the producer.

**Dispatch command:** (effort per `cli-dispatch/SKILL.md` §Reviewer Effort Policy — `medium` for routine review, `high` for hard/risk-path; `max`/`xhigh` only for tagged deep sub-reviews)
```powershell
powershell -NoProfile -File tools/Invoke-CodexDispatch.ps1 `
  -Mode ReviewReadOnly `
  -LoopId $LOOP_ID `
  -Kind execution `
  -ReasoningEffort medium `
  -OutputSchema .agent/schemas/review-verdict.schema.v2.json `
  -DispatchId validation `
  -Force `
  -PromptText "<VALIDATION_PROMPT>"
```

`-OutputSchema` is not optional once the loop is bound: `record` validates the verdict
against that schema and refuses a free-text one, so a dispatch without it produces a
round the ledger cannot count.

`-LoopId` is mandatory here (the alternative, `-NonReviewDispatch`, is a bypass and is
recorded as one in `status.json`). The wrapper evaluates the ledger *before* it resolves
a model, so a closed loop refuses cheaply:

| Exit | Meaning |
|---|---|
| `0` | A round is permitted — dispatch proceeded |
| `1` | Neither `-LoopId` nor `-NonReviewDispatch`, both, a malformed id, or a `-Kind` that contradicts the loop — fix the invocation |
| `9` | **The ledger refused this round.** A decision, not an error — apply the relief its message names, or escalate to a human |
| `3` | The gate could not be evaluated — never read `3` as a pass |

`-Kind execution` matches the `--review-mode execution` this loop was opened with, and the
wrapper checks it against the ledger rather than trusting it — a `kind_mismatch` here means
the dispatch is aimed at a different loop, whose budget is the one about to be spent. It
also raises this dispatch's timeout to the 45-minute execution floor: `-ReasoningEffort
medium` alone derives 15 minutes, which a review that has to read a whole change plus its
receipts spends before writing a verdict, and the round is charged either way.

**Prompt must include:**
- Handoff path: `.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-handoff.md`
- Instructions to execute Steps 1–7 of this workflow
- List of changed files from the handoff
- Build plan spec reference
- Output format: the Evidence Bundle template from Step 7

**After Codex returns:**
1. Read `{{RECEIPTS_DIR}}/dispatch/validation/final.json` — with `-OutputSchema` set the
   wrapper writes `final.json`, not `final.md`; looking for the wrong name reads as an
   empty dispatch
2. Verify it is non-empty (empty = dispatch failure, retry or escalate)
3. Append the Codex output to the handoff as a `## Codex Validation Report` section
4. Add **Review Provenance** block (see Step 7)
5. **Record the round before acting on it.** The ledger counts rounds that were
   *recorded*, so a verdict acted on but never recorded is a round the budget never
   sees — which is how a bounded loop quietly becomes an unbounded one:
   ```powershell
   python tools/review_ledger.py record --loop-id $LOOP_ID `
     --verdict-file {{RECEIPTS_DIR}}/dispatch/validation/final.json
   ```
   The verdict file must validate against `.agent/schemas/review-verdict.schema.v2.json`.
   `record` refuses on a schema violation, on a self-review, and on a round the budget
   or a mechanism stop already blocked — and it checks *before* writing, so a refused
   round does not consume budget.
6. If the verdict is `changes_required`, fix the findings and re-dispatch — the gate on
   the next dispatch decides whether that is still permitted. Do **not** re-dispatch past
   an exit `9`; each stop has its own relief and they are not interchangeable:

   | Stop | Relief |
   |---|---|
   | `budget` — round budget exhausted | `grant --owner <named human> --rationale "<≥20 chars>"` buys **one** round |
   | `mechanism` — the same mechanism class keeps failing | `relieve --mechanism <class> --owner <named human> --rationale …`; a repeat mechanism failure means the fix is not in the findings |
   | `scaffolding` — findings are churning on test scaffolding | Stop reviewing; the work under review is not what is failing |
   | `instrument` — the instrument digest changed mid-loop | The reviewer's own tooling moved; re-baseline before continuing |

   `grant` **refuses while any non-`budget` stop is active**. That is deliberate: "just
   grant another round" is the single most likely way this control gets defeated, and a
   granted round would not have unblocked the loop anyway.

---

> **Steps 1–7 below are executed by Codex CLI, NOT by the orchestrator.**


### 1. Handoff Intake

Read the handoff artifact. Verify it contains:
- [ ] MEU identifier and scope
- [ ] FIC with acceptance criteria
- [ ] Changed files list
- [ ] Test files and assertion counts
- [ ] Commands executed with output
- [ ] Status is `ready_for_review` (not `blocked`)

If handoff is incomplete or status is `blocked`, stop and report.

### 2. Run Full Test Suite

// turbo
Run the complete test suite (not just new tests):
```bash
pytest -x --tb=long -v
```

// turbo
Run type checking (scope to touched packages per active phase):
```bash
# Phase 1+1A: packages/core/src/
# Phase 2+:   packages/core/src/ packages/infrastructure/src/
# Phase 4+:   packages/core/src/ packages/infrastructure/src/ packages/api/src/
# Phase 5+:   add mcp-server/ (use tsc --noEmit, vitest, eslint instead)
pyright packages/core/src/    # ← adjust per active phase
```

// turbo
Run linting:
```bash
# Same phase scope as above
ruff check packages/core/src/ # ← adjust per active phase
```

// turbo
**Phase 5+ only** — Run TypeScript/MCP validation:
```bash
# Skip this block for Phases 1–4
cd mcp-server && npx tsc --noEmit   # Type-check MCP server
npx vitest run                       # MCP tool tests
npx eslint src/ --max-warnings 0     # MCP linting
```

Record all output.

### 3. Adversarial Verification Checklist

> ⚠️ You are a **REVIEWER**, not a test author. Do NOT generate new test files or rewrite existing tests. Only report findings with `file:line` references.

For each item, record PASS or FAIL with evidence:

| # | Check | What To Look For |
|---|---|---|
| AV-1 | **Failing-then-passing proof** | A test existed (or was written) that FAILED before the change and PASSES after. If no such test exists, the "fix" is unproven. |
| AV-2 | **No bypass hacks** | No monkeypatching of test internals, no forced early exits (`return` before assertions), no mocked-out assertion functions. |
| AV-3 | **Changed paths exercised by assertions** | Changed code paths are not just executed — they are checked by explicit `assert` / `expect` statements. Code coverage alone is insufficient. |
| AV-4 | **No skipped/xfail masking** | Tests exist but are not blanket-marked `@pytest.mark.skip`, `xfail`, or `it.skip`. Any skip must have a documented reason. |
| AV-5 | **No unresolved placeholders** | No `TODO`, `FIXME`, `NotImplementedError`, `pass  # placeholder`, or skeleton stubs remain. |
| AV-6 | **Source-backed criteria** | Any behavior beyond explicit build-plan text is traceable to `Local Canon`, `Research-backed`, or `Human-approved` sources. Uncited "best practice" rules fail review. |
| AV-7 | **Boundary schema enforcement** | Every external write boundary has an explicit Pydantic/Zod schema. Unknown fields are rejected (or intentionally allowed with source-backed rationale). |
| AV-8 | **Create/update parity** | Create and update flows share invariant enforcement. No `replace(obj, **raw_input)` or `Model(**{**old, **kwargs})` without prior schema validation. |
| AV-9 | **Invalid input produces 4xx** | Malformed input produces controlled 422 responses, not downstream exceptions or deferred failures. |

### 4. Banned Pattern Scan

// turbo
Search for banned patterns in all changed files:
```bash
rg "TODO|FIXME|NotImplementedError|pass\s+#\s*placeholder" packages/ tests/
```

### 5. FIC Acceptance Criteria Verification

For each acceptance criterion in the FIC:
- Identify the test(s) that prove it
- Verify the test(s) contain explicit assertions (not just execution)
- Confirm all criteria are covered (no gaps)
- Confirm each criterion is traceable to `Spec`, `Local Canon`, `Research-backed`, or `Human-approved` source basis

### 6. Architecture Review

- [ ] No inner layer imports outer layer (Domain doesn't import Infrastructure)
- [ ] Function/class names match build plan spec exactly
- [ ] Enum values match spec exactly
- [ ] Error handling is explicit (no bare except, no swallowed exceptions)
- [ ] No unused imports or dead code

### 7. Generate Evidence Bundle

Create or append to the handoff artifact:

```markdown
## Codex Validation Report

**Date**: {YYYY-MM-DD}
**MEU**: {N} — {description}
**Verdict**: approved / changes_required

### Test Results
| Command | Result |
|---------|--------|
| `pytest -x --tb=long -v` | PASS (N tests) / FAIL (details) |
| `pyright` | PASS / FAIL (details) |
| `ruff check` | PASS / FAIL (details) |

### Adversarial Checklist
| Check | Result | Evidence |
|-------|--------|----------|
| AV-1 | PASS/FAIL | ... |
| AV-2 | PASS/FAIL | ... |
| AV-3 | PASS/FAIL | ... |
| AV-4 | PASS/FAIL | ... |
| AV-5 | PASS/FAIL | ... |
| AV-6 | PASS/FAIL | ... |

### Banned Patterns
- rg output: {results or "clean"}

### FIC Coverage
| Criterion | Test(s) | Verified |
|-----------|---------|----------|
| AC-1 | test_xxx | ✅/❌ |

### Findings (if any)
1. **[SEVERITY]** {file}:{line} — {description}

### Verdict Rationale
{Why approved or what must change}

### Verdict Confidence
- **Confidence**: HIGH / MEDIUM / LOW
- **Justification**: {1-2 sentences explaining WHY you believe this verdict is correct}
- If MEDIUM or LOW, flag for human review even if verdict is "approved"

### Review Provenance (REQUIRED — orchestrator fills this)
- **Reviewer**: Codex CLI (`independent_reviewer`)
- **Dispatch command**: `powershell -File tools/Invoke-CodexDispatch.ps1 -Mode ReviewReadOnly -LoopId {loop-id} -Kind execution -ReasoningEffort {effort} -DispatchId validation -PromptText ...`
- **Output file**: `{{RECEIPTS_DIR}}/dispatch/validation/final.json`
- **Log file**: `{{RECEIPTS_DIR}}/dispatch/validation/events.jsonl.gz` (or `events.jsonl`)
- **Timestamp**: {YYYY-MM-DD HH:MM TZ}
- **Output non-empty**: YES / NO (if NO, dispatch failed — do not accept)
- **Loop / round**: `{loop-id}` round `{n}` of `{budget}` — copy from `review_ledger.py state --loop-id {loop-id}`
- **Ledger gate**: `permitted` / `bypassed-non-review` — from `status.json`. `bypassed-non-review`
  on a validation review is a defect in the dispatch, not a provenance detail: the round
  was never counted.

> A validation report without Review Provenance is invalid. The orchestrator
> must NOT selectively summarize Codex findings — append verbatim or link
> the exact output artifact.
```

Validation continuity rule:

- keep Codex validation updates in the same MEU handoff file
- append a new dated `Codex Validation Report` section on each review cycle
- do not create separate validation, recheck, or critique files for the same MEU

This is a **control, not tidiness**. The rolling review file's `## Recheck` headings are
what `validate_closeout_artifacts.py` counts rounds from, so a per-round file resets the
count to 1 and defeats the cap without anyone deciding to. `review_ledger.py` counts
recorded rounds independently; if the two disagree, the higher number is the real one.

## Verdict Definitions

- **approved**: All checks pass, all AV items pass, all FIC criteria verified. MEU is complete.
- **changes_required**: List specific items that must be fixed. The implementer re-enters the TDD workflow to address findings, then re-submits for review. Use this verdict if the MEU depends on unsourced acceptance criteria or silent best-practice assumptions.

## Escalation

If more than 2 review cycles occur for the same MEU without resolution, escalate to human orchestrator with a summary of the disagreement.
