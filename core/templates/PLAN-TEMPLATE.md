---
project: "{YYYY-MM-DD}-{project-slug}"
date: "{YYYY-MM-DD}"
source: "docs/build-plan/{section-reference}"
meus: ["{MEU-ID-1}", "{MEU-ID-2}"]
status: "draft"
template_version: "2.0"
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
schema). Cursor pins: `{composer-2.5-fast|cursor-grok-4.5-high-fast}`; Claude:
`{opus-5|sonnet-5}`; never `auto` / Fable 5 as builder. Legacy 9-column tables remain
valid.

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
rtk proxy pwsh -NoProfile -Command { $matches=@(Select-String -Path docs/BUILD_PLAN.md -Pattern '{project-slug}'); [pscustomobject]@{matches=$matches.Count; lines=@($matches.LineNumber)} | ConvertTo-Json -Depth 3 } *> {{RECEIPTS_DIR}}/build-plan-audit.json; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/build-plan-audit.json; exit $code
```

---

## Verification Plan

> [!IMPORTANT]
> Classify every command through
> [`.agent/docs/output-evidence-policy.md`](../../../.agent/docs/output-evidence-policy.md).
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

## Open Questions

> [!WARNING]
> {Any clarifying or design questions for the user that will impact the implementation.}
>
> **Research each one first (create-plan §2B) and present it as a Decision Options Table with a
> recommended option — never a bare question that stops the turn.** Only mark a question
> `Human-decision-required` (and route it through the §5 review loop's human-gate exit) when it is
> genuine product preference that research cannot resolve. An unresolved question is not, by itself,
> a reason to halt before dispatching review.

---

## Research References

- {link to research doc or ADR}
