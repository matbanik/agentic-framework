---
project: "{YYYY-MM-DD}-{project-slug}"
date: "{YYYY-MM-DD}"
source: "docs/build-plan/{section-reference}"
meus: ["{MEU-ID-1}", "{MEU-ID-2}"]
status: "draft"
template_version: "2.2"
---

# Implementation Plan: {Project Title}

> **Project**: `{YYYY-MM-DD}-{project-slug}`
> **Build Plan Section(s)**: {bp section reference(s)}
> **Status**: `draft` | `approved` | `changes_required`

---

## Goal

{Brief description of the problem, background context, and what the change accomplishes.}

## Context Tool Decision

Follow `.agent/docs/context-tool-decision-gate.md` before planning and re-evaluate before
execution. Persist the resolved record:

```yaml
context_tool_decision:
  phase: planning | execution | planning_and_execution
  eligible_tools: [graphify, graphify-research, headroom]
  decision: use | accepted_loss | not_applicable
  eligibility_basis: "{specific graph/payload/scope evidence}"
  human_message_reference: "{USER_EXPLICIT date/summary; null only for not_applicable}"
```

## Handoff Set

List every canonical review input before execution:

In the abstract naming rule, `{date}` means the concrete `{YYYY-MM-DD}` value, so the
product path is `{date}-{project-slug}-{MEU-ID}-handoff.md`.

| Scope | Canonical handoff |
|---|---|
| `{MEU-ID}` | `.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-{MEU-ID}-handoff.md` |

For a non-product plan with `meus: []`, replace the product rows with exactly one project handoff:
`.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-handoff.md`. The rolling project
review remains `.agent/context/handoffs/{project-folder}-implementation-critical-review.md`.

## Work Packages and Context Lifecycle

Every work row declares its dependency and context behavior. `context_strategy` is
exactly one of `shared|compact_continue|isolated`; `depends_on` is `—` or existing,
acyclic row IDs; and every non-`shared` row names a concrete durable output.

| ID | Work | depends_on | context_strategy | durable_outputs |
|---|---|---|---|---|
| WP-1 | {work} | — | `shared` | {repo path or receipt path} |
| WP-2 | {independent work} | WP-1 | `compact_continue` | {durable path; compact then re-read task and this output} |

Use `isolated` only when the resolved harness exposes an authorized fresh-worker
capability. Otherwise record and execute the row as `compact_continue`; metadata never
grants permission to spawn a worker.

Task tables in `task.md` may include an optional **`builder_model`** column (10-col
schema), whose values are **capability classes** — `builder`, `coordinator`, or
`verifier` — never model slugs and never `auto`. Which snapshot serves a class lives
in the live registry home you instantiate (see `.agent/INSTANTIATE.md`); resolve it
rather than pinning a value in a plan, so a model bump never reopens an approved plan.
`architecture_single_shot` is reserved for its own shape and is never a builder.
Legacy 9-column tables remain valid.

---

## User Review Required

> [!IMPORTANT]
> {Document anything that requires user review or feedback: breaking changes, significant design decisions, scope questions.}
>
> **This section is content for the review loop, NOT a cue to stop now.** Filling it in does NOT
> authorize ending your turn to "present the plan to the user" — the human sees *reviewed* plans,
> never raw drafts. After writing the plan, auto-dispatch `/plan-critical-review` (create-plan §5 /
> GUARDRAILS SIGN 1). The urge to pause here and ask "is this plan OK?" is the bug.

---

## Proposed Changes

### {Component/MEU Name}

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| {REST body\|MCP input\|UI form\|file import} | {Pydantic model\|Zod schema} | {enum/format/range rules} | {extra="forbid"\|exception} |

#### Acceptance Criteria

> **AC Type is mandatory (control C3).** Tag every AC `unit` or `integration`.
> - `unit` = satisfiable by a pure function / in-isolation assertion (a value object, a formatter, a parser).
> - `integration` = asserts runtime wiring: an API call, persistence, navigation, a message round-trip, a startup handshake, live data reaching a view.
>
> An `integration` AC is NOT done until proven by an integration/contract test — a unit test does **not** satisfy it (this is the "render-first, wire-later" skip class). If a single AC mixes both, split it.

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-1 | {unit\|integration} | {criterion} | {Spec\|Local Canon\|Research-backed\|Human-approved} | {what invalid input is rejected} |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| {behavior} | {Spec\|Local Canon\|Research-backed\|Human-approved} | {how resolved if under-specified} |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| {path} | {new\|modify\|delete} | {description} |

---

## Out of Scope

> **No-orphan-deferral rule (control C2).** Every item here is one of two kinds, and **each kind carries its own evidence requirement** in the *Basis* column — a row with an empty or hand-waved *Basis* is INVALID:
> 1. **Genuinely out of scope** — not part of this build-plan section's contract at all. *Basis* MUST cite the source proving the exclusion: a build-plan line reference (`docs/build-plan/{section} lines X–Y omit it`), an ADR, or a `Human-approved` decision. "Not needed", "unrelated", or a blank cell is NOT a basis — an unjustified out-of-scope claim is a SKIP wearing a costume. *Deferred-to MEU* cell = `—`.
> 2. **Deferred work** — in the contract but pushed to a later MEU. It is INVALID unless *Deferred-to MEU* names a MEU-ID **already scheduled** in the grouping / `meu-status.yaml`, and *Basis* states why it belongs later (dependency not yet built, sequencing). Phrases like "future MEU", "a wiring session", "screen-integration session" are forbidden targets — if no scheduled MEU owns it, either create that MEU (register it) or keep the work in scope. An unowned deferral is a SKIP, not a defer.
>
> Both kinds are now symmetric: `deferred` is gated by a scheduled MEU-ID, `out-of-scope` is gated by a source citation. Neither may rest on the agent's unsupported judgment.

| Item | Kind | Deferred-to MEU | Basis |
|------|------|-----------------|-------|
| {item} | {out-of-scope \| deferred} | {MEU-ID (must be scheduled) \| —} | {out-of-scope: build-plan line ref / ADR / Human-approved · deferred: dependency/sequencing reason} |

---

## BUILD_PLAN.md Audit

{This project does/does not modify build-plan sections. Validation:}

```powershell
Test-Path docs/BUILD_PLAN.md *> {{RECEIPTS_DIR}}/build-plan-audit.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/build-plan-audit.txt; exit $code
```

---

## Verification Plan

> [!IMPORTANT]
> Classify every command through
> [`.agent/docs/output-evidence-policy.md`](../docs/output-evidence-policy.md).
> Use a verified native RTK route for compact views and `rtk proxy` for exact evidence.

### 1. {Check Category}
```powershell
rtk proxy {exact runnable command} *> {{RECEIPTS_DIR}}/{receipt}.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/{receipt}.txt | Select-Object -Last {N}; exit $code
```

### 2. {Check Category}
```powershell
rtk proxy {exact runnable command} *> {{RECEIPTS_DIR}}/{receipt}.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/{receipt}.txt | Select-Object -Last {N}; exit $code
```

### N. OpenAPI Drift Check (if `packages/api/` was modified)

> [!IMPORTANT]
> **Required by G8** when any file in `packages/api/` is created or modified.
> Uses a two-step pattern: `--check` first (detect), then `-o` only on drift (regenerate).

```powershell
# Step 1: Detect drift
rtk proxy uv run python tools/export_openapi.py --check openapi.committed.json *> {{RECEIPTS_DIR}}/openapi-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/openapi-check.txt; exit $code

# Step 2: Regenerate ONLY if Step 1 reported [FAIL]
rtk proxy uv run python tools/export_openapi.py -o openapi.committed.json *> {{RECEIPTS_DIR}}/openapi-regen.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/openapi-regen.txt; exit $code
```

---

## Decision Log

> [!WARNING]
> {Every design decision the spec left open — the ones the planner resolved AND the ones that
> still need the human — per `.agent/docs/human-decision-protocol.md`.}
>
> **Precedent sweep and web research first (create-plan §2B), then the obviousness test.**
> A question that passes the test is decided here (`resolution: autonomous`, tagged `Local Canon`
> or `Research-backed`) with its reasoning — it is never asked. A question that fails it is a
> **Decision Brief**: recommendation first with why, then the alternatives compared against it
> (pros/cons relative, not free-standing), sources, reversibility, and the default if unanswered.
> Never a bare question that stops the turn. Only mark a brief `Human-decision-required` (and
> route it through the §5 review loop's human-gate exit) when it is a one-way door, a product
> preference, a source conflict, or a governance value. An unresolved brief is not, by itself, a
> reason to halt before dispatching review.

```yaml
decision_log:
  - id: D-1
    stage: planning
    question: "{one line}"
    resolution: autonomous | human
    class: two-way | one-way-door | product-preference | source-conflict | governance-value | externally-blocked
    chosen: "{option}"
    source_tag: Local Canon | Research-backed | Human-approved
    precedents: ["{path:line — what it decided}"]
    research: { engine: tavily | exa | native | codex-search | none, sources: ["{URL — takeaway}"] }
    reasoning: "{why this option; why the alternatives lost}"
    human_message_reference: "{USER_EXPLICIT YYYY-MM-DD '<quote>' — human-resolved entries only; omit otherwise}"
```

### D-{n} — {human-gated question}

**Recommendation:** {Option A} — {why it is the right call}. **Reversibility:** {two-way | one-way-door}. **Default if unanswered:** {option}.
**Precedents:** {path:line — what it decided}. **Research:** {engine}; {source — takeaway} (or `unavailable — <reason>`).

| Option | Source | Pros (vs. rec.) | Cons (vs. rec.) | Verdict |
|--------|--------|-----------------|-----------------|---------|
| {Option A} (recommended) | {precedent path:line / URL} | — | — | ✅ |
| {Option B} | {URL} | {what it does better than A} | {what it costs against A} | ⚠️ / ❌ |

---

## Research References

- {link to research doc or ADR}

## Validation stage contract

Bind checks to PROFILE D6: static, targeted, fresh full and optional runtime. Record argv
or manual procedure, cwd, selected scope (including shared fixtures/configuration), blocking
status, expected result, native shell and evidence.v1 output. Define how current input
identity is obtained independently for code/tests/config/environment/external inputs.
The final implementation review follows one fresh full gate; partial/cache/snapshot-only
output cannot satisfy it. Disable intermediate reuse until identity is implemented.
Non-software plans use actual acceptance observations. D9=no omits MEU tools/state updates.
