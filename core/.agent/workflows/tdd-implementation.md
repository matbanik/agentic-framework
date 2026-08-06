---
description: TDD-first implementation workflow for Opus 4.7 — write tests, implement, handoff to Codex for validation.
---

# TDD Implementation Workflow (Opus Agent)

> Tool names like `view_file`/`run_command` are capability placeholders — map to your harness's `read_tool`/`shell_tool` per `.agent/docs/harness-profiles.md`.

Use this workflow when implementing a Manageable Execution Unit (MEU). Opus is the **implementation agent** — writes tests first, implements to pass, and creates the handoff artifact for Codex validation.

## Prerequisites

- Read `AGENTS.md` for project config
- Read `.agent/context/meu-status.yaml` for MEU scope (see `.agent/skills/meu-status/SKILL.md`)
- Read `.agent/context/current-focus.md` for active phase
- Read `.agent/docs/emerging-standards.md` — verify applicable standards are covered. If the MEU involves MCP tools or GUI components, the matching standards are mandatory subtasks.

## Bug-Fix TDD Protocol

> [!IMPORTANT]
> **Bug reports trigger TDD, not direct code fixes.** When the user reports a defect (not a new feature), follow this protocol BEFORE touching any production code. See emerging standard **G19**.

1. **Reproduce:** Write a test that exercises the broken behavior. Assert what the *correct* behavior should be.
2. **Red:** Run the test — confirm it FAILS for the exact reason the bug exists (not a test setup issue).
3. **Fix:** Edit production code to make the test pass.
4. **Green:** Run the test — confirm it PASSES.
5. **Regression sweep:** `rg` for the same pattern in sibling files (e.g., if `getChangeColor()` ignored a prop, check all functions that receive that prop).

**Never skip from "user reports bug" → "edit production code."** The test IS the regression guard.

## Steps

### 0. Read task.md — Anchor Full Scope

// turbo

> [!IMPORTANT]
> **This step is mandatory.** It ensures the workflow tracks progress against the canonical task table — whether invoked standalone or from `/execution-session`.

Read the project `task.md` at `docs/execution/plans/{project-slug}/task.md`. If the user provided it as context, use that path. Otherwise, discover it from the `implementation-plan.md` YAML frontmatter or from `docs/execution/plans/` by date.

1. Read (your harness `read_tool`) the canonical task.md
2. Count `[ ]` items — this is the full work queue
3. Identify which MEU to start with (first `[ ]` task row, or user-specified MEU)
4. Note: Steps 1–8 below execute **per MEU**. After completing one MEU's cycle (through Step 8), return here to check for remaining `[ ]` items. If more MEUs remain in the task table, start the next MEU at Step 1.

### 1. Scope Lock

// turbo
Read the MEU definition from `.agent/context/meu-status.yaml` (query: `uv run python tools/meu_status.py get MEU-{N}`). Read the corresponding build plan section and any canonical local docs it references. Do NOT expand scope beyond the MEU boundary, but do implement the full documented contract.

If the spec is not specific enough to support concrete acceptance criteria without guesswork, stop here and return to PLANNING / `.agent/workflows/pre-build-research.md`. Do not start Red phase on unsourced assumptions.

### 2. Feature Intent Contract (FIC)

Write FIC inline in your session notes:
- **Intent statement**: What must be true when this MEU ships
- **Acceptance criteria**: Numbered, testable conditions (AC-1, AC-2, ...) with a source label for each: `Spec`, `Local Canon`, `Research-backed`, or `Human-approved`
- **Negative cases**: What must NOT happen
- **Boundary contract**: For write-adjacent MEUs, list each input boundary and its schema owner
- **Negative input cases**: Required classes — blank required strings, invalid enums, malformed format fields, non-positive/out-of-range numerics, unexpected/extra fields, create vs update parity
- **Test mapping**: Which test file/function proves each AC

`Best practice` is not a valid acceptance-criterion source unless it is backed by a cited local doc or web source.

### 3. Red Phase — Write Failing Tests

Write ALL tests FIRST in the appropriate `tests/unit/` file. Every AC must have at least one test. Include:
- Happy path tests
- Edge case tests (zero, negative, empty, overflow)
- Error condition tests

For write-adjacent MEUs, the Red phase MUST include negative input tests:
- Blank/empty required string → 422
- Invalid enum value → 422
- Non-positive numeric where positive required → 422
- Unexpected/extra fields → 422 (when `extra="forbid"`)
- Partial update bypassing create invariants → same validation error as create

> Handlers/services may NOT accept raw `dict` or `**kwargs` from external input unless those values have already passed boundary schema validation.

// turbo

> **P0 REMINDER:** Use the redirect-to-file pattern for this command.
> `pytest tests/unit/test_{module}.py -x --tb=short -v *> {{RECEIPTS_DIR}}/pytest.txt; Get-Content {{RECEIPTS_DIR}}/pytest.txt | Select-Object -Last 40`

Run tests to confirm they FAIL:
```bash
pytest tests/unit/test_{module}.py -x --tb=short -v
```

Save the failure output — you will include it in the handoff FAIL_TO_PASS table.

> **Test output compression**: When recording Red phase output, capture only the failing test names, assertion messages, and relevant stack frames. Do not record passing test details. Summarize passing tests as `{N} passed`. See `.agent/docs/context-compression.md §Test Output Compression`.

### 4. Green Phase — Implement

> ⚠️ **Test Immutability**: Once tests are written in Red phase, do NOT modify test assertions or expected values. If a test expectation is wrong, fix the *implementation*, not the *test*. Only test setup/fixture changes are allowed.

> [!CAUTION]
> **Scope Expansion Gate.** If the user requests features outside the approved plan scope during execution (e.g., "also add a delete tool" or "add a refresh button"), PAUSE and ask: "This is outside the current plan. Should I (a) update the plan first, (b) treat this as a separate ad-hoc fix, or (c) defer to a follow-up MEU?" Proceeding without updating plan artifacts causes handoff/review misalignment (ref: emerging-standards.md, 2026-03-19 session F14).

Write the minimum code to make all tests pass. Follow the build plan spec exactly — use the same function signatures, class names, and field names.

Do not invent new product behavior in code. If a gap appears during implementation, route it back to planning/research and update the FIC before continuing.

// turbo

> **P0 REMINDER:** Use the redirect-to-file pattern for this command.
> `pytest tests/unit/test_{module}.py -x --tb=short -v *> {{RECEIPTS_DIR}}/pytest.txt; Get-Content {{RECEIPTS_DIR}}/pytest.txt | Select-Object -Last 40`

Run tests to confirm they PASS:
```bash
pytest tests/unit/test_{module}.py -x --tb=short -v
```

> **Test output compression**: When recording Green phase output for the handoff, include only: (1) the summary line (`{N} passed`), (2) any remaining failures with their assertion messages. Do not include verbose output of passing tests. See `.agent/docs/context-compression.md §Test Output Compression`.

### 5. Quality Checks

// turbo
Run type checking and linting:
```bash
# Scope to touched packages (expand as phases grow):
# Phase 1+1A: packages/core/src/
# Phase 2+:   packages/core/src/ packages/infrastructure/src/
# Phase 4+:   packages/core/src/ packages/infrastructure/src/ packages/api/src/
# Phase 5+:   add mcp-server/ (tsc --noEmit, vitest, eslint)
pyright packages/core/src/    # ← adjust per active phase
ruff check packages/core/src/ # ← adjust per active phase
```

> [!CAUTION]
> **Anti-premature-stop checkpoint (Solution B).** Quality checks passing is a MILESTONE, not a stopping point. Do NOT summarize to user. Do NOT generate a completion report. Proceed directly to Step 6.

### 6. Full Test Suite

// turbo

> **P0 REMINDER:** Use the redirect-to-file pattern for this command.
> `pytest -x --tb=short -m "unit" *> {{RECEIPTS_DIR}}/pytest.txt; Get-Content {{RECEIPTS_DIR}}/pytest.txt | Select-Object -Last 40`

Run the complete test suite to check for regressions:
```bash
pytest -x --tb=short -m "unit"
```

> [!CAUTION]
> **Anti-premature-stop checkpoint (Solution B).** "All tests green" is a MILESTONE, not a stopping point. You are NOT done. Do NOT summarize to user. Do NOT generate a completion report. Proceed directly to Step 6.5. There are ALWAYS more steps after this one.

### 6.5. Update task.md — Track Progress

> [!IMPORTANT]
> **This step is mandatory after each MEU's quality checks pass.** It keeps the canonical task tracker in sync and drives multi-MEU continuation.

1. Read (your harness `read_tool`) the canonical `task.md` at `docs/execution/plans/{project-slug}/task.md`
2. Update all task rows completed during this MEU's TDD cycle from `[ ]` to `[x]`
3. Count remaining `[ ]` items across ALL MEUs in the task table:
   - If `[ ]` items remain for **the current MEU** → continue fixing (do NOT proceed to handoff)
   - If `[ ]` items remain for **other MEUs** in scope → after completing Step 8 for this MEU, return to Step 0 §4 and start the next MEU's TDD cycle
   - If `[ ]` items remain that are **post-MEU deliverables** (BUILD_PLAN, registry, handoffs, reflection, metrics) → proceed to Step 6.7
   - If only `[x]` and `[B]` remain → proceed to Step 6.9

> **Source of truth**: Always update the PROJECT task.md (`docs/execution/plans/...`), never only an agent workspace copy.

### 6.7. Post-MEU Administrative Tasks (Solution C)

> [!IMPORTANT]
> **Execute these NOW — do not defer.** These are mandatory exit deliverables, not optional cleanup. The anti-premature-stop rule in AGENTS.md §Execution Contract explicitly names these tasks. Deferring them to a "dedicated closing step" is a known failure mode.

If all MEU-scoped implementation tasks are `[x]` (or `[B]`), execute the post-MEU deliverables from `task.md` in order:

1. **Update MEU status via SSOT** — `uv run python tools/meu_status.py update MEU-{N} approved` (auto-stamps date, regenerates labels)
2. **Render SSOT regions** — `uv run python tools/meu_status.py render` (regenerates BUILD_PLAN.md and meu-registry.md status tables from YAML)
3. **Update `.agent/context/current-focus.md`** — reflect new project state
4. **Run MEU gate** — `uv run python tools/validate_codebase.py --scope meu`
5. **Run full regression** — `uv run pytest tests/ -x --tb=short -v`
6. **OpenAPI drift check (G8)** — if any file in `packages/api/` was created or modified:
   ```powershell
   # Step 1: Detect drift
   uv run python tools/export_openapi.py --check openapi.committed.json *> {{RECEIPTS_DIR}}/openapi-check.txt
   Get-Content {{RECEIPTS_DIR}}/openapi-check.txt
   # → [OK] = skip Step 2
   # → [FAIL] = run Step 2:
   uv run python tools/export_openapi.py -o openapi.committed.json *> {{RECEIPTS_DIR}}/openapi-regen.txt
   Get-Content {{RECEIPTS_DIR}}/openapi-regen.txt
   ```
7. **Anti-placeholder scan** — `rg "TODO|FIXME|NotImplementedError" packages/`
8. **Audit BUILD_PLAN.md** for stale references
9. **Create reflection** — `docs/execution/reflections/{date}-{slug}-reflection.md`
   - **MUST** read (your harness `read_tool`) `docs/execution/reflections/TEMPLATE.md` before writing — Template-First Rule (AGENTS.md §436)
   - Follow the full 7-section structure: Friction Log → Quality Signals → Workflow Signals → Pattern Extraction → Design Rules → Next Day Outline → Efficiency Metrics → Instruction Coverage YAML
   - See `execution-session.md §5` for section descriptions. The YAML block is section 7 of 7 — not the entire file.
10. **Append metrics row** — `docs/execution/metrics.md`

Mark each deliverable `[x]` in `task.md` as you complete it. Do NOT batch-mark — update after each item.

After all post-MEU tasks are `[x]`, proceed to Step 6.9.

### 6.9. Re-Read Gate (MANDATORY — Solution A)

> [!CAUTION]
> **This step CANNOT be skipped.** It is the structural enforcement of the anti-premature-stop rule. You must physically read (your harness `read_tool`) the file below before proceeding to Step 7.

1. **Read (your harness `read_tool`)** the canonical `task.md` at `docs/execution/plans/{project-slug}/task.md` — do this NOW
2. **Count** every `[ ]` item in the task table
3. **Decision gate:**
   - If `[ ]` count > 0 → **STOP HERE. Do NOT proceed to Step 7.** Return to the appropriate earlier step to complete remaining work.
   - If `[ ]` count = 0 (only `[x]` and `[B]` remain) → proceed to Step 7

> **Why this gate exists:** In 3 documented incidents, the agent passed quality checks, generated a summary, and stopped with 10–16 unchecked tasks remaining. This gate physically re-injects the task table into context and forces a count before any handoff or stop action.

### 7. Create Handoff Artifact

Create the handoff file at `.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-handoff.md` using the format from `.agent/workflows/meu-handoff.md`.

### 7.5. Instruction Coverage YAML (Mandatory)

> [!CAUTION]
> **This step is NOT optional.** Emit the Instruction Coverage YAML block BEFORE proceeding to Step 8. This is a numbered workflow step, not a suggestion — the same structural enforcement pattern as Steps 6.7 and 6.9.

1. Read (your harness `read_tool`) `.agent/schemas/reflection.v1.yaml` — the schema definition
2. Emit one fenced `yaml` block matching the schema, including:
   - `session.id` — the current conversation ID
   - `sections` — one entry per AGENTS.md H2 section with honest `cited`/`influence` scores
   - `loaded.workflows` — every workflow file read this session
   - `loaded.roles` — every role adopted this session
   - `loaded.skills` — every skill invoked this session
   - `decisive_rules` — max 5, format `P{0-3}:{rule-id}`
   - `conflicts` — any instruction conflicts encountered
3. Include the YAML block in the reflection file's `## Instruction Coverage` section
4. If the reflection file was already created in Step 6.7, update it now with the coverage YAML

> **Why this step exists:** The Instruction Coverage meta-prompt at AGENTS.md EOF is truncated by the system prompt loader when AGENTS.md exceeds ~24K characters. Without this numbered step, the coverage system is completely invisible to the agent. See investigation: `instruction-coverage-investigation.md`.

### 8. Save Session State

```
```

## Exit Criteria

1. All tests pass (Green)
2. No banned patterns in deliverables (TODO, FIXME, NotImplementedError)
3. Type checking passes (pyright)
4. Linting passes (ruff)
5. Handoff artifact created with evidence
7. **Re-read gate passed (Step 6.9)** — read (your harness `read_tool`) the canonical task.md was executed and confirmed zero `[ ]` items remain (or remaining items are `[B]` blocked with linked follow-up)
8. **Post-MEU deliverables completed (Step 6.7)** — all administrative tasks (BUILD_PLAN, registry, reflection, metrics) are `[x]` in the PROJECT task.md
9. **task.md fully updated** — all completed task rows marked `[x]` in `docs/execution/plans/{project-slug}/task.md`
10. **Instruction Coverage YAML emitted (Step 7.5)** — reflection file contains `schema: v1` YAML block with `sections`, `loaded`, and `decisive_rules` populated per `.agent/schemas/reflection.v1.yaml`

## Failure Protocol

If stuck for more than 2 iterations on a failing test, or if a spec gap is discovered mid-MEU:
1. Document what was attempted
2. Route the issue back to planning/research for a source-backed resolution
3. Mark MEU status as `blocked` in handoff if the issue still cannot be resolved
4. List the specific blocking issue or unresolved decision
5. Do NOT implement a workaround that violates the spec or silently narrows the contract
