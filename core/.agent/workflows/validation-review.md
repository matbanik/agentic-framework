---
description: Validation and adversarial review workflow for GPT-5.6 Sol Codex — verify tests, review code, generate evidence bundle.
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
> - **Codex CLI** (GPT-5.6 Sol, external agent) — executes **Steps 1–7**: runs tests, performs adversarial review, issues verdict.
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

**Dispatch command:** (effort per `cli-dispatch/SKILL.md` §Reviewer Effort Policy — `medium` for routine review, `high` for hard/risk-path; `max`/`xhigh` only for tagged deep sub-reviews)
```powershell
powershell -NoProfile -File tools/Invoke-CodexDispatch.ps1 `
  -Mode ReviewReadOnly `
  -ReasoningEffort medium `
  -DispatchId validation `
  -Force `
  -PromptText "<VALIDATION_PROMPT>"
```

**Prompt must include:**
- Handoff path: `.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-handoff.md`
- Instructions to execute Steps 1–7 of this workflow
- List of changed files from the handoff
- Build plan spec reference
- Output format: the Evidence Bundle template from Step 7

**After Codex returns:**
1. Read `{{RECEIPTS_DIR}}/dispatch/validation/final.md`
2. Verify it is non-empty (empty = dispatch failure, retry or escalate)
3. Append the Codex output to the handoff as a `## Codex Validation Report` section
4. Add **Review Provenance** block (see Step 7)
5. If verdict is `changes_required`, fix findings and re-dispatch

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
- **Reviewer**: Codex CLI / GPT-5.6 Sol
- **Dispatch command**: `powershell -File tools/Invoke-CodexDispatch.ps1 -Mode ReviewReadOnly -ReasoningEffort {effort} -DispatchId validation -PromptText ...`
- **Output file**: `{{RECEIPTS_DIR}}/dispatch/validation/final.md`
- **Log file**: `{{RECEIPTS_DIR}}/dispatch/validation/events.jsonl.gz` (or `events.jsonl`)
- **Timestamp**: {YYYY-MM-DD HH:MM TZ}
- **Output non-empty**: YES / NO (if NO, dispatch failed — do not accept)

> A validation report without Review Provenance is invalid. The orchestrator
> must NOT selectively summarize Codex findings — append verbatim or link
> the exact output artifact.
```

Validation continuity rule:

- keep Codex validation updates in the same MEU handoff file
- append a new dated `Codex Validation Report` section on each review cycle
- do not create separate validation, recheck, or critique files for the same MEU

## Verdict Definitions

- **approved**: All checks pass, all AV items pass, all FIC criteria verified. MEU is complete.
- **changes_required**: List specific items that must be fixed. Opus re-enters the TDD workflow to address findings, then re-submits for review. Use this verdict if the MEU depends on unsourced acceptance criteria or silent best-practice assumptions.

## Escalation

If more than 2 review cycles occur for the same MEU without resolution, escalate to human orchestrator with a summary of the disagreement.
