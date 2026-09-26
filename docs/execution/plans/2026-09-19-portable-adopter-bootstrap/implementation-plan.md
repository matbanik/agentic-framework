---
project: "2026-09-19-portable-adopter-bootstrap"
date: "2026-09-19"
source: ".agent/context/2026-09-19-adopter-findings-fix-proposal.md"
meus: []
status: "approved"
template_version: "2.0"
---

# Implementation Plan: Portable adopter bootstrap and first-plan contract repair

> **Project**: `2026-09-19-portable-adopter-bootstrap`
> **Build Plan Section(s)**: none in this package (`docs/BUILD_PLAN.md` is not shipped). Contract source is the Astra proposal plus the mock-deploy findings it reviews.
> **Status**: `draft`

---

## Goal

A naive consuming agent can install this package into an empty repo, finish ADOPTION-GUIDE Steps 0–9 through plan+task write, and get a green `--phase build` preflight without inventing snapshot ids, overwriting the instruction tree, or guessing template/D6/dispatch paths.

Source of truth for *what* and *how*: `.agent/context/2026-09-19-adopter-findings-fix-proposal.md` (GPT-6 Astra high, 2026-09-19). Evidence: `.agent/context/2026-09-19-adopter-mock-deploy-findings.md` (F001–F036) and `.agent/context/2026-09-18-source-project-evidence-framework-gaps.md`. Reproduction fixture: `P:/fw-adopt-probe` (read-only).

This project does **not** execute until a human says proceed (`plan_to_exec_gate: human`).

The unexecuted draft `docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/` is **superseded**. Its create-plan.md-only ACs are absorbed into WP1 (egress), WP3 (templates/focus), WP4 (D3/D6), WP5 (forbidden command forms), and WP6 (PROFILE read). Do not run both plans.

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning
  eligible_tools: []
  decision: not_applicable
  eligibility_basis: "graphify-out/graph.json absent; graphify-out-research/graph.json absent; Headroom not installed. Scope is adoption docs, installer, preflight, templates, and lint — not architecture-graph reconnaissance."
  human_message_reference: null
```

## Handoff Set

Non-product (`meus: []`):

| Scope | Canonical path |
|---|---|
| Project handoff | `.agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-handoff.md` |
| Plan review (rolling) | `.agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-plan-critical-review.md` |
| Implementation review (rolling) | `.agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-implementation-critical-review.md` |

Do not register these MEU ids into packaged `core/.agent/context/meu-status.yaml` (that seed ships to adopters).

## Named predicates (single-statement rule)

Defined once. Every AC and task row that mentions them uses these names.

| Name | Definition |
|---|---|
| **LAYOUT_HD01** | Instruction/context/overlay live at `<project>/.agent/`. Project-owned catalog lives at `<project>/.agent-registry/`. Select that home with a **session-scoped** `AGENT_MODEL_REGISTRY_HOME` (not a user-wide persist of a project path). Shared user-home remains an explicit opt-in. Overlay stays `.agent/model-registry.local.yaml`. |
| **LOCATE_ORDER** | Compiled-file override `AGENT_MODEL_REGISTRY` → configured home `AGENT_MODEL_REGISTRY_HOME` → existing user-home fallback. No implicit “workspace `.agent/` is a catalog” rung. A configured home that is missing or lacks compiled JSON is fail-closed (no fall-through to user-home). An invalid explicit file override is fail-closed. |
| **FIRST_LINE_CONTRACT** | First stdout line of `preflight.sh` is exactly one of `OK:` / `REFUSE:` / `USAGE:` / `FAIL-CLOSED:` matching exit 0/1/2/3. Banner and per-check detail follow. |
| **BUILD_PHASE_SKIP** | `--phase build` SKIPs registry, codex, and pwsh. `--phase review` and `--phase all` check the registry. A deferred profile must not authorize dispatch, delegation, or model resolution. |
| **TEMPLATE_HOME** | Installed template sources are `.agent/templates/{PLAN,TASK,HANDOFF,REVIEW,REFLECTION}-TEMPLATE.md`. Artifact *output* paths stay F1/F2 (`docs/execution/plans/`, `.agent/context/handoffs/`, `docs/execution/reflections/`). |
| **INSTALLER_TARGET** | `instantiate.py` apply/dry-run/verify require `--root`. Mutually exclusive `--in-place-package` is the only way to rewrite the transfer package. `--project-root` is a substitution value, not a target. |
| **D6_ADOPTER_ARGV** | D6 is adopter-supplied exact argv/cwd/scope/success/shell/receipt recorded in PROJECT-PROFILE. No shipped `validate_codebase.py`, no `{{D6_GATE}}` token, no mandatory `uv`/`rtk`/`packages/`. |
| **EGRESS_PRECEDENCE** | External review dispatch is mandatory unless C1/C2/C3b or E5 forbids it; then stop for B4’s named human reviewer. That stop is **not** SIGN 1. Self-review remains prohibited. `plan_to_exec_gate: human` is a separate post-`approved` pause. Missing CLI (`can_dispatch_external_reviewer == no`) is **not** the same as forbidden egress: forbidden egress must not prepare a provider web-prompt or request manual external submission. |
| **D9_NO_BRANCH** | When PROFILE D9 is no, create-plan must not require MEU seeds/tools (`current-focus.md` MEU sections, `meu_status.py`, known-issues MEU coupling). When D9 is yes, missing required MEU assets refuse. |
| **HD03_GATE** | Live compile/sync/enforce is in-scope only after a human names an authorized working implementation and provenance. Until then WP1B’s deliverable is an explicit incompleteness receipt, not a fabricated compiler. |

## Work Packages and Context Lifecycle

| ID | Work | depends_on | context_strategy | durable_outputs |
|---|---|---|---|---|
| WP1 | LAYOUT_HD01, deferred registry, FIRST_LINE_CONTRACT, BUILD_PHASE_SKIP, LOCATE_ORDER fail-closed on locators, minimal profile slots, EGRESS_PRECEDENCE including cli-dispatch | — | `shared` | ADOPTION-GUIDE.md, INSTANTIATE.md, preflight.sh, ModelRegistry.psm1, resolve_model.py, check_model_slugs.py, cli-dispatch/SKILL.md, create-plan.md, execution-session.md |
| WP2 | ASCII-or-BOM `.ps1` packaging; PS 5.1 parse of instantiated wrapper | — | `compact_continue` | core/tools/Invoke-CodexDispatch.ps1 and other shipped `.ps1`; packaging test |
| WP3 | INSTALLER_TARGET, owned-asset walk+rename, TEMPLATE_HOME consumers including orchestrator.md, copy recipe, current-focus seed, D9_NO_BRANCH, INSTANTIATE.md install mapping | WP1 | `compact_continue` | scripts/instantiate.py, ADOPTION-GUIDE Step 2, core/templates/*, core/.agent/workflows/*, core/.agent/roles/orchestrator.md |
| WP4 | D6_ADOPTER_ARGV, D3-only spec hub, drop `/mcp-audit`, full-failure receipt contract | WP3 | `compact_continue` | commands.md, quality-gate/SKILL.md, create-plan.md D6/D3 rows |
| WP5 | Portable task cells; lint refuse `-Command` scriptblock; keep escaped-pipe refusal | WP4 | `compact_continue` | TASK-TEMPLATE.md, lint_task_contract.py |
| WP6 | Slash-id table, remaining profile consumers, F007/F008/F018/F019/F022/F001/F015 Cursor default | WP1, WP4 | `compact_continue` | workflows/README.md, harness-profiles.md, issue_triage, inspiration-research |
| WP1B | Live registry bootstrap **or** HD03_GATE incompleteness receipt | WP1, WP2, WP3 | `compact_continue` | C:/Temp/agentic-framework/receipts/hd03-live-registry.txt |
| WP7 | Disposable adopter replay of Steps 0–9 (no paid dispatch, no commit, do not mutate `P:/fw-adopt-probe`) | WP1–WP6 | `compact_continue` | new fixture under C:/Temp; receipts proving gates |

`isolated` is not used: this origin session has not proven adopter-window Task subtypes (findings F013). Cursor `fresh_worker` exists but is unverified here → `compact_continue`.

## User Review Required

> Filling this section does **not** stop the planner. Review is dispatched after the files land.

1. **HD-01…HD-09 are proposal-backed planned defaults**, pending `USER_EXPLICIT` proceed after plan review. They are not Human-approved solely because this session was asked to create the plan from the proposal (proposal §1 last paragraph). Override before execution if any default is wrong. Do not auto-move or delete an existing live `P:/.agent` catalog.
2. **HD-03 remains open.** WP1B must not extract `P:/.agent` tools without an explicit later instruction naming provenance.
3. Execution starts only on an explicit chat message after plan review (`plan_to_exec_gate: human`).
4. `P:/fw-adopt-probe` stays frozen. WP7 uses a **new** disposable directory.

## Proposal-backed defaults (pending USER_EXPLICIT proceed)

| id | Default this plan implements |
|---|---|
| HD-01 | LAYOUT_HD01 |
| HD-02 | Preflight deferral; no adopter-facing scratch catalog |
| HD-03 | Unresolved → HD03_GATE |
| HD-04 | D6_ADOPTER_ARGV |
| HD-05 | TEMPLATE_HOME |
| HD-06 | Name Git for Windows Bash; keep PS 5.1 after encoding gate; no `preflight.ps1` this round |
| HD-07 | Workflow ids + direct `.md` invocation; no shipped `.cursor/commands/` this round |
| HD-08 | EGRESS_PRECEDENCE |
| HD-09 | Add search-provider and D8 map questions; keep manual substitution + waiver |

**Rejected HD-01 alternative (steel-man recorded):** merge registry files into `.agent/` via an exact file list. Rejected because the live guide copies a directory, names collide, and there is no merge/refresh contract.

---

## Proposed Changes

### WP1 — Registry layout, deferred adoption, truthful preflight, egress

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `preflight.sh --phase` | argv parser in `core/tools/preflight.sh` | `all\|build\|review`; unknown → USAGE/exit 2 | extra flags fail closed |
| `AGENT_MODEL_REGISTRY` / `_HOME` | INSTANTIATE S2 + preflight `chk_registry` + `.agent/tools/ModelRegistry.psm1` `Resolve-RegistryPath` + `.agent/tools/resolve_model.py` + `check_model_slugs.py` | file vs directory distinction; YAML is not compiled JSON | invalid or missing configured home is fail-closed; no fall-through |
| PROJECT-PROFILE registry/deferral/egress fields | PROJECT-PROFILE-TEMPLATE.md slots A10, C1–C3b, E5, B4 | enumerated answers from ADOPTION-QUESTIONS | missing safety answers keep restrictive defaults |
| Review dispatch permission | EGRESS_PRECEDENCE in create-plan, delegated-plan-creation, execution-session, execution-critical-review, cli-dispatch/SKILL.md | C1/C2/C3b/E5 forbid vs missing CLI | forbidden egress must not write a provider web-prompt or request manual external submission |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-WP1-1 | unit | Docs and copy inventory implement LAYOUT_HD01; Step 4 does not copy package `.agent/` as a catalog onto the instruction tree | Proposal §1 HD-01; Spec findings 2.1 | Sentinel instruction/context bytes change when registry files are installed |
| AC-WP1-2 | unit | LOCATE_ORDER is identical in INSTANTIATE §1, preflight, both dispatch wrappers, `.agent/tools/ModelRegistry.psm1`, `.agent/tools/resolve_model.py`, and `.agent/tools/check_model_slugs.py`; workspace instruction `.agent/` is never selected as a catalog | Spec findings 2.4 / overlay 4.1 | Unset env + instruction `.agent/` present ⇒ catalog resolved there |
| AC-WP1-3 | integration | BUILD_PHASE_SKIP: isolated fixture, both registry env vars unset, `--phase build` exits 0 with registry SKIP; same env `--phase review` exits 1 REFUSE registry | Proposal §1 HD-02; Spec 2.2/2.4 | `--phase build` REFUSE registry when deferred |
| AC-WP1-4 | unit | FIRST_LINE_CONTRACT holds for pass, refuse, usage, fail-closed, help, selftest | Spec F025 | Banner is first stdout line |
| AC-WP1-5 | unit | Profile template has A10 home/deferral, C1/C2/C3b, E5, B4; create-plan, delegated-plan-creation, execution-session, execution-critical-review, AGENTS, GUARDRAILS SIGN 1, and cli-dispatch/SKILL.md state EGRESS_PRECEDENCE | Proposal §1 HD-08; Spec F031 | Treating C1 forbid as SIGN 1, or self-reviewing |
| AC-WP1-6 | unit | Empty `catalog: {}` still fails schema validation; no compiled JSON is fabricated for deferral | Spec INSTANTIATE empty-catalog rule | Deferred install writes a toy dispatchable catalog |
| AC-WP1-7 | integration | Isolated-home tests of the three locators (no compiler, provider execution denied): missing configured home fail-closed; no fall-through to an unrelated existing user-home; preflight and module agree | Proposal overlay 4.1 | `Resolve-RegistryPath` returns another machine’s catalog when `AGENT_MODEL_REGISTRY_HOME` is set but missing |
| AC-WP1-8 | integration | Missing CLI (`can_dispatch_external_reviewer == no`) is distinct from forbidden egress. Forbidden egress / unverified required redaction / prohibited spend / missing B4: stop for the named human and do not write a provider web-prompt or request manual external submission | Proposal §2.12 / F031 | cli-dispatch “no-dispatch” branch still prepares `<provider>-web-prompt.md` when C1/C2/C3b/E5 forbids egress |

**Control binding AC-WP1-3:** observable = first stdout line + exit code of `core/tools/preflight.sh`. Call chain = adopter/session invokes that script (ADOPTION-GUIDE Step 9 / commands.md) → `chk_registry` → phase skip vs fail. Negative oracle = `--phase build` with unset env prints `REFUSE:` for registry or exits 1 while other checks pass.

**Control binding AC-WP1-4:** observable = byte 0 of stdout vs exit. Call chain = `preflight.sh` `report`/`usage`/`fail_closed`. Negative oracle = first line is `preflight (phase=…)` while exit is 0 or 1.

**Control binding AC-WP1-7:** observable = locator exit + selected path (or refusal). Call chain = isolated home env → `Resolve-RegistryPath` / Python locators / `chk_registry`. Negative oracle = configured missing home selects an unrelated existing JSON. Runner: `python scripts/tests/test_adoption_contract.py --case wp1`.

**Control binding AC-WP1-8:** observable = no `<provider>-web-prompt.md` write + stop text names B4. Call chain = PROFILE C/E answers → create-plan / execution-session → cli-dispatch SKILL. Negative oracle = forbidden egress still writes the web-prompt fallback.

#### Spec Sufficiency

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Sibling registry vs merge-into-`.agent/` | Proposal-backed default | Proposal §1 HD-01 / LAYOUT_HD01 |
| Scratch catalog vs deferral | Proposal-backed default | Proposal §1 HD-02 deferral |
| Preflight first-line vs banner | Spec | preflight.sh header vs F025 |
| Egress vs SIGN 1 | Spec + proposal-backed default | ADOPTION-QUESTIONS C/E + Proposal §1 HD-08 |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| ADOPTION-GUIDE.md | modify | LAYOUT_HD01 copy; session env; deferral; Git Bash path; EGRESS_PRECEDENCE in Step 9 |
| ADOPTION-QUESTIONS.md | modify | A10 default = `.agent-registry/`; deferral answer |
| PROJECT-PROFILE-TEMPLATE.md | modify | A10, C3b, E5, B4, D9, F3b slots (minimal WP1 set) |
| .agent/INSTANTIATE.md | modify | copy inventory → `.agent-registry/`; LOCATE_ORDER fail-closed; no `P:\.agent` as the Windows first-install example |
| README.md, core/MANIFEST.md, UPDATE-CHECKLIST.md | modify | layout + copy list |
| core/tools/preflight.sh | modify | BUILD_PHASE_SKIP; FIRST_LINE_CONTRACT; skip names; agree with locators |
| core/tools/Invoke-CodexDispatch.ps1, Invoke-CodexDispatch.sh | modify | error text: selected home; no implicit workspace catalog |
| .agent/tools/ModelRegistry.psm1 | modify | LOCATE_ORDER fail-closed on missing configured home |
| .agent/tools/resolve_model.py, .agent/tools/check_model_slugs.py | modify | same fail-closed selection; no compiler body until HD-03 |
| scripts/tests/test_adoption_contract.py | new | fail-closed adoption cases (`wp1`, later WPs add cases) |
| core/.agent/workflows/create-plan.md | modify | EGRESS_PRECEDENCE (absorbs superseded plan AC-8) |
| core/.agent/workflows/delegated-plan-creation.md, execution-session.md, execution-critical-review.md | modify | same permission rule; stop for B4 when forbidden |
| core/.agent/skills/cli-dispatch/SKILL.md | modify | distinguish missing CLI from forbidden egress; no web-prompt on forbid |
| core/AGENTS.md, core/GUARDRAILS.md | modify | same precedence sentence |

---

### WP2 — PowerShell packaging encoding

#### Boundary Inventory

| Surface | Schema Owner | Extra-Field Policy |
|---------|-------------|-------------------|
| Shipped `*.ps1` bytes | packaging test (new) | non-ASCII without BOM refused |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-WP2-1 | unit | Every shipped `.ps1` is ASCII or begins with UTF-8 BOM | Spec 2.3 / Source Project 4.2 | Planted BOM-less em-dash file passes the gate |
| AC-WP2-2 | integration | Instantiated wrapper parses under `powershell.exe` (5.1) and `pwsh` without execution; missing PromptText reaches usage, not ParserError | Spec F021 | Current 10 em-dash wrapper still ParserError on 5.1 |

**Control binding AC-WP2-1:** observable = packaging-test exit. Call chain = UPDATE-CHECKLIST / test runner invoked from task row → scan `core/**/*.ps1`. Negative oracle = fixture with U+2014 and no BOM exits 0.

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| core/tools/Invoke-CodexDispatch.ps1 | modify | ASCII comments/messages |
| core/.agent/skills/git-workflow/scripts/agent-commit.ps1 | modify | same gate |
| core/.agent/skills/cli-dispatch/tests/Test-CliDispatch.ps1, Test-OpenCodePoC.ps1 | modify | same gate |
| UPDATE-CHECKLIST.md | modify | encoding/parser checks |
| scripts/tests/test_ps1_encoding.py | new | byte gate (or equivalent under scripts/tests/) |

---

### WP3 — Installer target, owned assets, templates, copy recipe, seeds

#### Boundary Inventory

| Surface | Schema Owner | Extra-Field Policy |
|---------|-------------|-------------------|
| `instantiate.py --root` / `--in-place-package` | scripts/instantiate.py | missing `--root` = usage before any write; both flags = refuse |
| Copy recipe (guide) | ADOPTION-GUIDE Step 2 | wildcard + `-LiteralPath` forbidden; conflicting dest refuses |
| Agent-def filenames | instantiate rename | collision refuses before partial write |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-WP3-1 | unit | INSTALLER_TARGET: no `--root` leaves package bytes unchanged | Spec 2.7 | Default apply rewrites `scripts/` neighbor |
| AC-WP3-2 | integration | Owned-asset inventory only; tokens in PROFILE/`_probe/`/user notes survive; four `{{PROJECT_NAME}}-*.md` agent defs rename to slug; second apply is idempotent | Spec 2.8 | Friction-log tokens substituted; filenames stay tokenized |
| AC-WP3-3 | unit | Every active workflow/template read uses TEMPLATE_HOME, including `core/.agent/roles/orchestrator.md` and `core/AGENTS.md`; old output-tree template paths are absent from active instructions | Spec 2.5; superseded plan AC-1/2 | create-plan still names `docs/execution/plans/PLAN-TEMPLATE.md` or `handoffs/REVIEW-TEMPLATE` |
| AC-WP3-4 | integration | Documented Windows copy recipe copies bootstraps, `.agent/` instructions, tools, TEMPLATE_HOME, agents, BUILD_PLAN stub, INSTANTIATE.md; spaces in paths; missing source nonzero | Spec 2.14 | Bare `{ Copy-Item }` scriptblock “succeeds” with no files |
| AC-WP3-5 | unit | Ship `core/.agent/context/current-focus.md`; D9=yes first-MEU recipe is schema-complete; `meu_status.py` documented as no `add` | Spec 2.9 | create-plan requires focus file that does not exist |
| AC-WP3-6 | unit | INSTANTIATE.md copied into adopter `.agent/INSTANTIATE.md`; installed docs link `../INSTANTIATE.md`; parent decoy `.agent/` does not satisfy | Spec 2.11 | `../../../.agent/INSTANTIATE.md` still present in installed docs |
| AC-WP3-7 | integration | D9_NO_BRANCH: PROFILE D9=no first-plan write does not require `current-focus.md` MEU sections, `meu_status.py`, or known-issues MEU coupling. D9=yes with those assets missing still refuses | Spec 2.9 / 2.12 | D9=no create-plan still invokes `tools/meu_status.py` unconditionally |

**Control binding AC-WP3-1:** observable = instantiate exit + hash of a package sentinel. Call chain = `python scripts/instantiate.py` (no `--root`) from package cwd. Negative oracle = exit 0 and sentinel changed.

**Control binding AC-WP3-3:** observable = rg/absence over named consumers. Call chain = `python scripts/tests/test_adoption_contract.py --case templates-installed` after WP3 edits. Negative oracle = current create-plan.md still contains `docs/execution/plans/PLAN-TEMPLATE` or `handoffs/REVIEW-TEMPLATE`.

**Control binding AC-WP3-7:** observable = create-plan D9 branch + runner `--case d9-no`. Call chain = PROFILE D9 → create-plan discovery. Negative oracle = D9=no still requires `meu_status.py`.

Absorbs superseded plan AC-1, AC-2, AC-5, AC-6 (template/focus/forbidden forms in create-plan.md), plus sister files that plan left out.

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| scripts/instantiate.py, scripts/README.md | modify | INSTALLER_TARGET; owned inventory; filename rename |
| ADOPTION-GUIDE.md Step 2 / 2a / 2b / 4b | modify | copy recipe; INSTANTIATE mapping; first-MEU recipe; D9=no omit-MEU path |
| core/.agent/workflows/create-plan.md | modify | TEMPLATE_HOME reads; PROFILE prerequisite; stub current-focus; D9_NO_BRANCH |
| core/.agent/workflows/delegated-plan-creation.md, tdd-implementation.md, plan-critical-review.md, execution-critical-review.md, execution-session.md, meu-handoff.md, orchestrated-delivery.md | modify | TEMPLATE_HOME |
| core/.agent/roles/orchestrator.md | modify | TEMPLATE_HOME handoff/review/plan reads |
| core/templates/TASK-TEMPLATE.md, PLAN-TEMPLATE.md | modify | TEMPLATE_HOME links (command-cell rewrite is WP5) |
| core/.agent/docs/commands.md, development-lifecycle.md, artifact-naming.md, context-compression.md | modify | template paths |
| core/.agent/skills/completion-preflight/SKILL.md | modify | template paths |
| core/.cursor/agents/README.md, core/.claude/agents/README.md | modify | rename is automatic |
| core/.agent/context/current-focus.md | new | stub |
| core/.agent/context/meu-status.yaml | modify | comment only (no `add`) |
| core/.agent/docs/harness-profiles.md, model-routing.md, model-delegation.md, core/AGENTS.md | modify | INSTANTIATE relative links; template paths |
| core/MANIFEST.md, UPDATE-CHECKLIST.md | modify | inventory |
| scripts/tests/test_adoption_contract.py | modify | add `templates-installed` and `d9-no` cases |

---

### WP4 — Adopter D6 / D3 registration

#### Boundary Inventory

| Surface | Schema Owner | Extra-Field Policy |
|---------|-------------|-------------------|
| D6 profile fields | PROJECT-PROFILE-TEMPLATE | executable + argv **or** documented manual procedure; cwd; scope; blocking; expected result; shell; receipt |
| create-plan discovery | D3 path from profile | extra spec trees only if registered |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-WP4-1 | unit | commands.md / quality-gate / AGENTS / testing-strategy / lifecycle / validation-review / create-plan refer to D6_ADOPTER_ARGV, not a required `tools/validate_codebase.py` | Spec 2.6 | Registered command is the unshipped origin gate |
| AC-WP4-2 | unit | `/mcp-audit` removed from workflows/README; output-evidence-policy is not labeled MANIFEST-EXCLUDED; D3-only `docs/BUILD_PLAN.md` can plan without `docs/build-plan/` | Spec F016, F030 | create-plan mandates build-priority-matrix.md |
| AC-WP4-3 | integration | Isolated minimal Python adopter registers `python -m pytest test_hello.py` and reaches D6; a second argv proves pytest is not a new universal default; missing exe / failing child fail | Proposal §1 HD-04 | Toy pytest becomes mandatory for all adopters |
| AC-WP4-4 | integration | Registered failing child with multiple diagnostic ids + FAILED/ERROR test ids: all ids survive on the receipt with nonzero status (overlay 1.1 contract, not a port of Source Project’s gate) | Spec overlay 1.1 | Compact display drops all but first error |

**Control binding AC-WP4-4:** observable = receipt file contents + child exit. Call chain = quality-gate skill / commands.md registered D6 invocation → P0 redirect. Negative oracle = receipt missing a planted second diagnostic id while exit is 0. Runner: `python scripts/tests/test_adoption_contract.py --case d6` (two argv fixtures, missing exe, failing child, no `validate_codebase.py`, no `/mcp-audit`).

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| PROJECT-PROFILE-TEMPLATE.md | modify | D3, D6, D8 fields |
| core/.agent/docs/commands.md | modify | D6 card; F016 |
| core/.agent/skills/quality-gate/SKILL.md | modify | adopter checks |
| core/.agent/docs/testing-strategy.md, development-lifecycle.md, core/AGENTS.md | modify | no origin packages/ gate |
| core/.agent/workflows/create-plan.md, validation-review.md, tdd-implementation.md | modify | D3/D6; GUI/OpenAPI skip if unshipped (superseded AC-3,4,7,9) |
| core/.agent/workflows/README.md | modify | drop mcp-audit |
| core/.agent/docs/output-evidence-policy.md | modify | full-failure receipt sentence |
| scripts/tests/test_adoption_contract.py | modify | add `d6` case |

---

### WP5 — Portable validation cells

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-WP5-1 | unit | Shipped TASK-TEMPLATE / create-plan example cells have no `pwsh -Command {` and no required `rtk`/`uv` | Spec 2.13 | Current H1-1 still uses `-Command {` |
| AC-WP5-2 | unit | lint refuses `-Command` + scriptblock with a portability diagnostic; keeps escaped-pipe refusal and legitimate `& { }` placeholder behavior | Spec 2.13; overlay 2.4 (pipe already refused) | `scriptblock-is-not-a-placeholder-ok` used to bless `pwsh -Command {` |
| AC-WP5-3 | unit | H1-1 is a concrete check (unchecked implementation rows fail; pending H1/H2 ignored); no nested backticks | Spec F035 | Ellipsis H1-1 or nested-backtick cell |

**Control binding AC-WP5-2:** observable = `lint_task_contract.py` refuse text + exit 1. Call chain = H2-4 / packaging test → linter. Negative oracle = fixture row with `pwsh -NoProfile -Command { Get-Date }` exits 0.

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| core/templates/TASK-TEMPLATE.md | modify | script-path / one-line cells |
| core/.agent/workflows/create-plan.md | modify | discovery/stamp examples |
| core/tools/lint_task_contract.py | modify | dedicated `-Command {` rule |
| core/tools/lint_task_contract.py selftest arms | modify | refuse + keep pipe arm |

---

### WP6 — Remaining interface residue

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-WP6-1 | unit | workflows/README titled as workflow ids; direct `.md` invocation; no claim `.cursor/commands/` shipped; mcp-audit row gone | Proposal §1 HD-07; Spec 2.10 | Table still reads as slash commands |
| AC-WP6-2 | unit | Every interview id including A4b/c/d, A6b, A9, A10, C3b, D8, D9, F3b has a profile slot; create-plan and session-start require reading PROFILE **and** applying EGRESS_PRECEDENCE / D9_NO_BRANCH / D6 from those answers (not a mere `PROJECT-PROFILE.md` mention) | Spec 2.12 | `rg PROJECT-PROFILE core/` still zero in executable workflows, or PROFILE is named then dispatch is unconditional |
| AC-WP6-3 | unit | Cursor `injects_auto_approval` cell = `yes` (safety default); merge rule unchanged | Spec 2.15 | Cell `no` overrides interview `yes` |
| AC-WP6-4 | unit | F007 drop unshipped Cursor CLI wrapper as default route; F008 search-provider question; F018 D8 prefix map; F019 labeled bad-path example; F022 benchmark mode documented opt-in; F001 README vs guide order aligned | Spec 2.16 | Pomera reached with no provider answer |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| core/.agent/workflows/README.md | modify | ids vs commands |
| PROJECT-PROFILE-TEMPLATE.md, ADOPTION-QUESTIONS.md, ADOPTION-GUIDE.md | modify | remaining slots; README Step 0 order |
| core/AGENTS.md, core/CLAUDE.md | modify | session-start PROFILE |
| core/.agent/docs/harness-profiles.md | modify | Cursor injection default |
| core/.agent/docs/model-routing.md | modify | F007 |
| core/.agent/workflows/inspiration-research.md, deep-research-prompting/SKILL.md | modify | F008 |
| core/tools/issue_triage/discover.py docs in guide Step 4b | modify | F018 (code map only when D8 says so; default remains until adopter customizes — document, do not silently change origin map in a way that breaks origin) |
| core/.agent/skills/terminal-preflight/SKILL.md | modify | F019 |
| core/tools/Invoke-CodexDispatch.ps1 usage text | modify | F022 documented |
| scripts/tests/test_adoption_contract.py | modify | add `profile-permissions` case (no egress, no paid dispatch, A6b, missing D6, nondefault D3, D9=no already in `d9-no`) |

F018 code change: prefer documenting the customization set this round; changing default prefixes is origin-breaking. AC is “adopter can name prefixes”; implementation is docs + a hook or clearly labeled constants, not a surprise remap of this repo.

---

### WP1B — Live registry bootstrap or HD03_GATE

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-WP1B-1 | integration | If HD-03 is unanswered: write incompleteness receipt whose first line is `INCOMPLETE:` and that names wrappers at `.agent/tools/resolve_model.py` and `check_model_slugs.py`; do not copy `P:/.agent` catalog; do not claim live compile or “registry ready” | Proposal §1 HD-03; HD03_GATE | Silent skip, nonempty junk receipt, or text that says “registry ready” |
| AC-WP1B-2 | integration | If HD-03 is answered in a later explicit message: compile/sync/enforce using that source in an isolated home with synthetic **non-dispatchable** test bindings; forwarding-only tree fails with missing-prerequisite; receipt first line is `READY:` plus provenance | Spec INSTANTIATE wrappers | Forwarding wrapper recurse-success |

**Control binding AC-WP1B-1:** observable = first line of `$env:RECEIPTS_DIR/hd03-live-registry.txt`. Call chain = `python scripts/tests/test_adoption_contract.py --case hd03`. Negative oracle = nonempty file without `INCOMPLETE:`/`READY:` markers, or containing `registry ready` while HD-03 is unanswered.

### WP7 — Disposable adopter acceptance

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-WP7-1 | integration | New empty repo (not `P:/fw-adopt-probe`) completes Steps 0–8 + Step 9 plan/task write with deferred registry, TEMPLATE_HOME, D6 from profile, D9_NO_BRANCH first-plan write, lint_task_contract 0, `--phase build` FIRST_LINE_CONTRACT OK, EGRESS_PRECEDENCE stop without provider call | Spec findings method + Astra WP7 | Mutating the frozen probe, treating no-dispatch stop as completed review, or a receipt that only exists/is nonempty |

**Control binding AC-WP7-1:** observable = runner exit + fixture path recorded in receipt. Call chain = `python scripts/tests/test_adoption_contract.py --case wp7`. Negative oracle = `P:/fw-adopt-probe` mutated; existence-only receipt; provider call recorded.

---

## Out of Scope

No `meu-status.yaml` product grouping in this origin tree, so nothing is `deferred` to a scheduled product MEU-ID. WP1B incompleteness is **in-scope** (HD03_GATE), not a deferral.

| Item | Kind | Deferred-to MEU | Basis |
|------|------|-----------------|-------|
| Source Project 4.6 hash sync / version-stamp adopter refresh | out-of-scope | — | Proposal §4; findings §5 item 7; not reproduced on first install |
| Source Project extra closeout rules (`### Delta:`, exact Corrections Applied, mandatory findings_per_round) | out-of-scope | — | Proposal §4; packaged validator does not require them; adopter-side drift |
| Ship `.cursor/commands/` / `.claude/commands/` adapters | out-of-scope | — | Proposal §1 HD-07; proposal §4 |
| Native `preflight.ps1` twin | out-of-scope | — | Proposal §1 HD-06; proposal §4 |
| Adopter-facing scratch/fake catalog | out-of-scope | — | Proposal §1 HD-02; proposal §4 |
| Universal `validate_codebase.py` port / `{{D6_GATE}}` token | out-of-scope | — | Proposal §1 HD-04; proposal §4 |
| Copy `P:/.agent` snapshots into the package | out-of-scope | — | Proposal §4; findings F003/F015 |
| Mutate or submodule `P:/fw-adopt-probe` | out-of-scope | — | Findings §5 last line; proposal §4 |
| Unexercised companion items (census, RED pyright, builder git, AUTOGEN CRLF, Electron USERPROFILE, commit hooks) | out-of-scope | — | Findings §3 “not exercised” |
| GUI / OpenAPI / Graphify as required adopter tools | out-of-scope | — | MANIFEST excluded; G8/G25 N/A (no `packages/api/`, no GUI MEU) |
| Execute superseded plan `2026-09-19-create-plan-adopter-path-fix` | out-of-scope | — | This plan Goal; proposal §4 scope; draft is create-plan.md only |
| Paid live review from a deferred adopter fixture | out-of-scope | — | HD-02 + EGRESS_PRECEDENCE; WP7 records the stop |

## BUILD_PLAN.md Audit

This package has no `docs/BUILD_PLAN.md`. Task row proves absence and records hub N/A.

```powershell
Test-Path docs/BUILD_PLAN.md *> C:/Temp/agentic-framework/receipts/build-plan-hub.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/build-plan-hub.txt; exit $code
```

(`Test-Path` exit 0 with `False` in the receipt is the skip basis.)

## Verification Plan

Receipts: `C:/Temp/agentic-framework/receipts/`. No `rtk`/`uv` in these commands (D6_ADOPTER_ARGV for this origin session: `python`).

### 1. Task contract
```powershell
python core/tools/lint_task_contract.py --task docs/execution/plans/2026-09-19-portable-adopter-bootstrap/task.md *> C:/Temp/agentic-framework/receipts/lint-task.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/lint-task.txt; exit $code
```

### 2. Preflight selftest (after WP1)
```powershell
bash core/tools/preflight.sh --selftest *> C:/Temp/agentic-framework/receipts/preflight-selftest.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/preflight-selftest.txt; exit $code
```

### 3. instantiate selftest (after WP3)
```powershell
python scripts/instantiate.py --selftest *> C:/Temp/agentic-framework/receipts/instantiate-selftest.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/instantiate-selftest.txt; exit $code
```

### 4. lint_task_contract selftest (after WP5)
```powershell
python core/tools/lint_task_contract.py --selftest *> C:/Temp/agentic-framework/receipts/lint-selftest.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/lint-selftest.txt; exit $code
```

### 5. OpenAPI
G8 N/A: no `packages/api/` in this package. Skip receipt only.

### 6. Adoption-contract runner (created in WP1; cases added per WP)

Exact invocations. Each case must refuse bogus/incomplete evidence (nonempty junk files, mere token mentions, missing installed templates, prohibited provider calls, missing/failing D6).

```powershell
python scripts/tests/test_adoption_contract.py --case wp1 *> C:/Temp/agentic-framework/receipts/adopt-wp1.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/adopt-wp1.txt; exit $code
python scripts/tests/test_adoption_contract.py --case templates-installed *> C:/Temp/agentic-framework/receipts/adopt-templates.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/adopt-templates.txt; exit $code
python scripts/tests/test_adoption_contract.py --case d9-no *> C:/Temp/agentic-framework/receipts/adopt-d9.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/adopt-d9.txt; exit $code
python scripts/tests/test_adoption_contract.py --case d6 *> C:/Temp/agentic-framework/receipts/adopt-d6.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/adopt-d6.txt; exit $code
python scripts/tests/test_adoption_contract.py --case profile-permissions *> C:/Temp/agentic-framework/receipts/adopt-profile.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/adopt-profile.txt; exit $code
python scripts/tests/test_adoption_contract.py --case hd03 *> C:/Temp/agentic-framework/receipts/adopt-hd03.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/adopt-hd03.txt; exit $code
python scripts/tests/test_adoption_contract.py --case wp7 *> C:/Temp/agentic-framework/receipts/adopt-wp7.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/adopt-wp7.txt; exit $code
```

`--case hd03` passes only when `$env:RECEIPTS_DIR/hd03-live-registry.txt` starts with `INCOMPLETE:` (unanswered HD-03) or `READY:` (answered HD-03 with provenance). Existence and size alone fail.

`--case wp7` passes only when the receipt names a disposable fixture that is not `P:/fw-adopt-probe`, records child statuses for D6/lint/preflight, records a D9_NO_BRANCH first-plan write, and records zero provider calls.

`--case templates-installed` requires `.agent/templates/{PLAN,TASK,REVIEW}-TEMPLATE.md` in create-plan.md and orchestrator.md, and refuses `docs/execution/plans/PLAN-TEMPLATE` and `handoffs/REVIEW-TEMPLATE`.

`--case profile-permissions` refuses a document that only mentions `PROJECT-PROFILE.md` then dispatches unconditionally. It requires EGRESS_PRECEDENCE behavior change for no-egress, unverified redaction, prohibited spend, missing B4, and missing CLI vs forbidden egress.

WP3 task row 6 runs both `templates-installed` and `d9-no` through `docs/execution/plans/2026-09-19-portable-adopter-bootstrap/checks/assert_wp3.py`.

### Closeout AC aliases

The packaged coverage gate matches `AC-<digits>` only. These aliases are 1:1 with the named ACs above and do not change the FIC.

| Alias | Named AC |
|-------|----------|
| AC-1 | AC-WP1-1 |
| AC-2 | AC-WP1-2 |
| AC-3 | AC-WP1-3 |
| AC-4 | AC-WP1-4 |
| AC-5 | AC-WP1-5 |
| AC-6 | AC-WP1-6 |
| AC-7 | AC-WP1-7 |
| AC-8 | AC-WP1-8 |
| AC-9 | AC-WP2-1 |
| AC-10 | AC-WP2-2 |
| AC-11 | AC-WP3-1 |
| AC-12 | AC-WP3-2 |
| AC-13 | AC-WP3-3 |
| AC-14 | AC-WP3-4 |
| AC-15 | AC-WP3-5 |
| AC-16 | AC-WP3-6 |
| AC-17 | AC-WP3-7 |
| AC-18 | AC-WP4-1 |
| AC-19 | AC-WP4-2 |
| AC-20 | AC-WP4-3 |
| AC-21 | AC-WP4-4 |
| AC-22 | AC-WP5-1 |
| AC-23 | AC-WP5-2 |
| AC-24 | AC-WP5-3 |
| AC-25 | AC-WP6-1 |
| AC-26 | AC-WP6-2 |
| AC-27 | AC-WP6-3 |
| AC-28 | AC-WP6-4 |
| AC-29 | AC-WP1B-1 |
| AC-30 | AC-WP1B-2 |
| AC-31 | AC-WP7-1 |

### 7. H1-7 two-stage closeout (plan-local helper; no braces in the task cell)
```powershell
python docs/execution/plans/2026-09-19-portable-adopter-bootstrap/checks/assert_exec_review_approved.py *> C:/Temp/agentic-framework/receipts/exec-review.txt; $code=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/exec-review.txt; exit $code
```

## Open Questions — Decision Options Table

| Question | Option | Source | Pros | Cons | Rec |
|----------|--------|--------|------|------|-----|
| HD-03 live compiler source | Keep documented external prerequisite; WP1B writes incompleteness receipt | `.agent/INSTANTIATE.md` wrappers §; proposal §5 item 1 | Honest first-install; no leaked pins | Live dispatch still blocked | ✅ this round |
| | Extract from `P:/.agent` now | Live machine registry | Unblocks compile | Imports another machine’s catalog/tools; findings F003/F015 forbid | ❌ |
| | Write a new compiler from guesses | none | Appears portable | Fabricates unavailable code; proposal forbids | ❌ |
| Supersede vs dual-execute create-plan-only draft | Absorb into this plan; do not execute the draft | this plan Goal; draft Out of Scope admitted sister files | One source of truth | Draft disk files remain until deleted by human | ✅ |
| | Execute draft first then this plan | draft is create-plan.md only | Smaller first PR | Double-edit create-plan.md; sister files still wrong | ❌ |

HD-03 is `Human-decision-required` only if the human wants live compile in *this* execution. Default is the ✅ option above.

## Research References

- `.agent/context/2026-09-19-adopter-findings-fix-proposal.md`
- `.agent/context/2026-09-19-adopter-mock-deploy-findings.md`
- `.agent/context/2026-09-18-source-project-evidence-framework-gaps.md`
- ADOPTION-GUIDE.md, ADOPTION-QUESTIONS.md, `.agent/INSTANTIATE.md`
- `docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/` (superseded)
- G19 (failing test first), G24 (decision tables), G28 (system messages ≠ approval)

## Stop conditions

- Do not edit production/docs listed above until this plan is independently reviewed and a human says proceed.
- Do not instantiate the origin package in place.
- Do not copy `P:/.agent`.
- Do not treat WP1B incompleteness as “registry ready”.
- Do not add `P:/fw-adopt-probe` as a submodule.

## TDD note (G19)

Every WP that changes a tool (`preflight.sh`, locators, `instantiate.py`, `lint_task_contract.py`, encoding gate, `scripts/tests/test_adoption_contract.py`) writes the failing fixture **before** the production edit. Doc-only ACs are proven by the named runner/rg/Test-Path receipts, which must fail on the current tree before the edit (negative oracles above).
