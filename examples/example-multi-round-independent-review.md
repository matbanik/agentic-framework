verdict: changes_required
findings_count: 11

# Independent Adversarial Review: Harness-Agnostic Governance Refactor

## Scope

Reviewed the complete 1,063-line uncompacted working-tree diff across 22 tracked files, both new canonical documents in full, and residual references in the live `AGENTS.md` / `GUARDRAILS.md` / `.agent/docs` / `.agent/workflows` / `.agent/skills` / `.agent/schemas` surface. This was a read-only review; no implementation files were changed.

## Findings by Severity

## High

### H1 — SIGN 3 independently authorizes execution in a `human`-gated profile

`GUARDRAILS.md:84-98` says either a direct human message **or** an external-reviewer artifact authorizes the plan→execution transition, without conditioning option (b) on `plan_to_exec_gate`. That contradicts `AGENTS.md:81-85` and `.agent/workflows/create-plan.md:296-304`, which require a new explicit human message after reviewer approval whenever `plan_to_exec_gate == human`. An agent following SIGN 3 can therefore enter execution under Claude Code, Cursor, headless `claude -p`, or UNKNOWN solely from the reviewer file.

**Concrete fix:** In SIGN 3, separate “trusted provenance” from “sufficient authorization.” State that a reviewer artifact authorizes execution only when `plan_to_exec_gate == reviewer-auto`; under `human`, it proves review approval but the transition still requires `USER_EXPLICIT`. Apply the qualification both at `GUARDRAILS.md:84-93` and in the summary bullets at `GUARDRAILS.md:95-98`.

### H2 — Single-row profile resolution is unsafe for the documented Claude-Code-inside-Antigravity topology

`.agent/docs/harness-profiles.md:17-23` resolves exactly one profile row. Yet the same document describes Claude Code as a plugin inside Antigravity (`.agent/docs/harness-profiles.md:50,52,63-65`). Choosing the Claude Code row yields `plan_to_exec_gate: human` but incorrectly says `injects_auto_approval: no`; choosing the Antigravity row captures injection risk but changes the gate to `reviewer-auto`, which can authorize execution where the Claude Code behavior must pause. The note “when in doubt, apply the stricter `yes`” only patches one flag and provides no deterministic composition rule.

**Concrete fix:** Resolve capabilities per layer/per flag rather than selecting one monolithic row. Define a driver profile and an optional host overlay, with conservative merge rules: gate = most restrictive (`human` wins), injection risk = `yes` if any layer says yes, dispatch = yes only if the driving layer actually exposes it, and shell/tools = the tools the active driver invokes. Include an explicit resolved example for “Claude Code driver inside Antigravity host” showing `plan_to_exec_gate: human` plus `injects_auto_approval: yes`.

### H3 — Correction workflows still direct agents into the exact Antigravity artifact path forbidden by SIGN 3

`.agent/workflows/plan-corrections.md:130-132` and `.agent/workflows/execution-corrections.md:155-157` imperatively require writing an Antigravity `implementation-plan.md` artifact and requesting approval. That conflicts with `GUARDRAILS.md:77-81` and `AGENTS.md:199`, which require plans to live only in the project folder and prohibit the artifact/review-policy trigger implicated in the auto-approval incident. These are live correction workflows, so the safety fix is bypassed precisely during review loops.

**Concrete fix:** Replace both artifact instructions with project-file updates in `docs/execution/plans/...` and direct-chat approval only when a genuine human gate applies. Explicitly prohibit `RequestFeedback:true` mirror artifacts and refer to `injects_auto_approval`, not Antigravity by name.

## Medium

### M1 — The operational fallback skill contradicts the canonical independent-reviewer chain

`.agent/docs/model-routing.md:42-54` defines Codex → Gemini for surface work → isolated headless Claude only when Gemini is inappropriate. `.agent/skills/cli-dispatch/SKILL.md:418-485` instead makes Claude the immediate Codex fallback, incorrectly calls Claude a “different vendor” at line 422, and gives no Gemini dispatch step. Its substitution matrix again calls Claude the automatic first fallback at `.agent/skills/cli-dispatch/SKILL.md:1077-1082`. This is not merely stale prose: these are the executable dispatch instructions consumed by plan and execution review loops.

**Concrete fix:** Rewrite §6 and the rate-limit substitution matrix to implement the canonical chain exactly. Add the Gemini surface/depth eligibility decision before headless Claude, state that Claude is same-vendor for a Claude primary driver, require a fresh isolated context and a model different from the implementor where available, and reconcile the hard-stop condition with `.agent/docs/model-routing.md:53-54`.

### M2 — `can_dispatch_external_reviewer` is declared as consumed, but no consumer or no-dispatch fallback exists

`.agent/docs/harness-profiles.md:38,103` says `cli-dispatch/SKILL.md` consumes `can_dispatch_external_reviewer` and provides a no-dispatch fallback; UNKNOWN sets it to `no` at `.agent/docs/harness-profiles.md:56`. The skill never mentions the flag. Instead, `.agent/skills/cli-dispatch/SKILL.md:10` assumes the primary driver dispatches, while `.agent/skills/cli-dispatch/SKILL.md:1049-1071` says it “must not block” and routes through CLI/web options. Thus the UNKNOWN fail-safe cannot execute the promised behavior, and the profile’s consumption inventory is false.

**Concrete fix:** Add an entry gate to the skill: when the flag is `yes`, use the reviewer chain; when `no`, do not self-review or pretend dispatch occurred—emit the canonical human/external-review handoff and stop at a human decision gate. Update SIGN 1’s “unconditional dispatch” language to distinguish mandatory independent review from unavailable shell-dispatch capability.

### M3 — Several profile-table values violate the capability contract and cannot drive deterministic shell behavior

The `native_shell` contract permits only `powershell | bash | posix-sh` at `.agent/docs/harness-profiles.md:39`. The table supplies `OS-dependent` for Cursor and Gemini, `sandbox sh` for Codex, and two alternatives (`bash / posix-sh`) for headless Claude at `.agent/docs/harness-profiles.md:51-55`. The Codex row also uses `n/a` for flags whose declared value sets do not include it. Since `native_shell` selects the P0 redirect syntax, unresolved/non-enum values are operationally unsafe.

**Concrete fix:** Make every resolved profile contain one allowed value. Split OS-dependent rows into variants or add a mandatory resolution step that materializes one concrete value; map sandbox `sh` to `posix-sh`. Either add `n/a` to the contract with role-based applicability rules or give every row a valid conservative value.

### M4 — Live plan workflows and lifecycle guidance still hard-code the old human pause and Antigravity orchestrator

`.agent/workflows/delegated-plan-creation.md:30-35,221-223` still identifies the orchestrator as Antigravity, and `.agent/workflows/delegated-plan-creation.md:267-295` always reports to the user and forbids auto-continuation after approval. `.agent/docs/issue-lifecycle-guide.md:251-270` likewise always waits for human plan approval. `.agent/docs/agentic-methodology.md:198-201` still depicts planning as a human-approval HARD STOP. These paths do not preserve the prior Antigravity/`reviewer-auto` behavior and contradict the new canonical gate logic.

**Concrete fix:** Replace the named orchestrator with the `primary-driver` role and route every post-review transition through `plan_to_exec_gate`. Update the lifecycle diagram/prose to show the two flag outcomes rather than one unconditional human stop.

### M5 — Current, non-historical stale model choices remain in live governance artifacts

`.agent/schemas/reflection.v1.yaml:41-53` still hard-codes `antigravity`/`claude_code` environment branching and defaults the implementor to `antigravity-claude-opus-4-6-thinking`. `.agent/skills/cli-dispatch/tests/Test-OpenCodePoC.ps1:45` still selects `amazon-bedrock/openai.gpt-5.5`. The live lifecycle SVG contains two `GPT-5.5` labels at `.agent/docs/diagrams/development-lifecycle-overview.svg:1`. These are current defaults/test routes/rendered guidance, not historical incident annotations.

**Concrete fix:** Move the reflection schema to capability/profile metadata and the canonical Opus 4.8 identifier, update executable test model IDs to GPT-5.6-sol where supported (or label a provider-availability probe explicitly historical), and regenerate the SVG from the corrected lifecycle source. Preserve the explicitly marked June-2026 Sonnet 4.6 history.

### M6 — The live surface still contains imperative Antigravity tool names without local capability framing

Mandatory workflows still say to execute literal `view_file` calls in `.agent/workflows/tdd-implementation.md:40,154,189,201-203`; `.agent/workflows/cli-dispatch.md:44,142` requires literal `view_file` and `run_command`; and `.agent/skills/terminal-preflight/SKILL.md:8,14,43` is written solely in terms of `run_command`. `AGENTS.md:28-41,135-140` also retains literal `run_command`/`view_file` imperatives outside a tool-substitution preamble. The global table in the new doc helps only after an agent knows to load and apply it; these live entry points do not consistently establish that context.

**Concrete fix:** Rewrite imperatives using `read_tool`/`shell_tool`/`end_turn_signal`, or add one mandatory capability-placeholder preamble to each entry document and point all literal examples to it. Add session-start profile resolution to `AGENTS.md` so unknown harnesses cannot reach mandatory workflows before learning the substitution rule.

## Low

### L1 — Canonical-doc cross-references to workflows/skills are not resolvable relative paths

`.agent/docs/harness-profiles.md:36,38,102-104` refers to bare `create-plan.md`, `cli-dispatch/SKILL.md`, and “completion” gates even though those targets are outside `.agent/docs`; `.agent/docs/model-routing.md:53-54` repeats the bare `cli-dispatch/SKILL.md` reference. The links to `harness-profiles.md`, `model-routing.md`, and `model-delegation.md` themselves resolve, but these workflow/skill references do not.

**Concrete fix:** Use real Markdown links: `../workflows/create-plan.md`, `../skills/cli-dispatch/SKILL.md`, and explicit paths for each completion consumer.

### L2 — The canonical role/tier taxonomy is internally ambiguous

`.agent/docs/model-routing.md:13,19-26` calls the design “four tiers + external review” but presents six routed rows; `.agent/docs/commands.md:81` and `.agent/docs/model-delegation.md:3` call a six-item list a four-tier stack. Separately, the `role` enum at `.agent/docs/harness-profiles.md:35` uses `primary-driver`/`host`, while the routing table uses `Coordinator`/`Builder`/`Router` without defining the mapping.

**Concrete fix:** Name the taxonomy consistently (for example, three internal model tiers plus external reviewer plus two execution modes) and add an explicit `role` → routing-tier mapping.

## Checks With No Finding

- The standalone rows preserve the two previously named gate behaviors: Claude Code maps to `human`, Antigravity maps to `reviewer-auto`, and UNKNOWN maps to `human` plus `injects_auto_approval: yes` (`.agent/docs/harness-profiles.md:50,52,56`). The defect is hybrid composition, not those individual row values.
- `AGENTS.md:81-85`, `GUARDRAILS.md:19,47-48`, and `.agent/workflows/create-plan.md:293-306` use the same `plan_to_exec_gate` flag names and values. SIGN 3 is the contradictory consumer identified in H1.
- The deletion budget is not violated by rule count: `AGENTS.md` is +9/-9; `GUARDRAILS.md` retains the same three SIGNs and the same three SIGN-3 layers while replacing/expanding existing carve-out text. Its +22/-14 line delta does not introduce a new independent rule.
- Explicitly historical Sonnet 4.6 references in `.agent/docs/agentic-methodology.md:238` and `.agent/docs/development-lifecycle.md:785-787` are correctly annotated and were not treated as stale current choices.

## Verdict

`changes_required` — the refactor has the right abstraction, and its basic named-row/UNKNOWN mappings are directionally correct, but the current working tree still contains an authorization contradiction, an unsafe hybrid-profile resolver, a live artifact-trigger path, and operational instructions that do not implement the canonical reviewer chain.

## Round 2
verdict: changes_required

### Per-Finding Resolution

| Finding | Resolution | File:line evidence |
|---|---|---|
| H1 — SIGN 3 authorized execution without the gate | **RESOLVED** | `GUARDRAILS.md:84-96` now separates trusted provenance from sufficient authorization and requires fresh `USER_EXPLICIT` approval when `plan_to_exec_gate == human`; the summary repeats that qualification at `GUARDRAILS.md:104-107`. This matches `AGENTS.md:81-85` and `.agent/workflows/create-plan.md:293-304`. |
| H2 — single-row profile unsafe for Claude Code inside Antigravity | **RESOLVED** | `.agent/docs/harness-profiles.md:14-37` now resolves driver and optional host layers per flag; `:29-36` defines conservative merge rules, and `:39-45` gives the required Claude-Code-driver + Antigravity-host result (`human` gate + injection risk `yes`). A separate residual role ambiguity is recorded as R2-N1 below. |
| H3 — correction workflows wrote the forbidden Antigravity artifact | **RESOLVED** | `.agent/workflows/plan-corrections.md:122-130` and `.agent/workflows/execution-corrections.md:147-155` now update only the project plan, explicitly prohibit `RequestFeedback:true` mirrors, and explain why correction work auto-proceeds. |
| M1 — CLI fallback contradicted the canonical reviewer chain | **PARTIAL** | The core correction is present: `.agent/skills/cli-dispatch/SKILL.md:438-449` implements Codex → Gemini for surface work → isolated headless Claude for deep work and correctly labels Claude same-vendor; `:1100-1108` updates the substitution matrix. The chain is still not operationally consistent end-to-end: the skill's exhaustion protocol says it “must not block” and contains no all-rungs-unavailable HARD STOP (`:1074-1108`), contrary to `.agent/docs/model-routing.md:49-64`. Live consumers also retain the old two-reviewer route: `.agent/workflows/execution-session.md:134-137` goes directly Codex → Claude, and `.agent/workflows/create-plan.md:415-421` summarizes execution review the same way; `.agent/workflows/create-plan.md:346-348` says “both” rate-limited despite listing three rungs at `:247-250`. |
| M2 — `can_dispatch_external_reviewer` had no consumer/fallback | **RESOLVED** | `.agent/skills/cli-dispatch/SKILL.md:199-217` now consumes the flag first, prohibits self-review/pretend dispatch, writes a manual-review prompt, and stops at a human gate when dispatch is unavailable. `GUARDRAILS.md:15-19` distinguishes mandatory independent review from shell-dispatch capability. |
| M3 — `native_shell` used non-enum/unresolved values | **RESOLVED** | The contract remains a three-value enum at `.agent/docs/harness-profiles.md:61`; `:80-89` now mandates resolving multi-valued/OS-dependent cells to one enum value before use and defines `n/a` role applicability. The Codex row is normalized to `posix-sh` at `:75`. |
| M4 — live workflows retained unconditional human pause / named orchestrator | **PARTIAL** | The cited surfaces were substantially corrected: `.agent/workflows/delegated-plan-creation.md:30-35,219-223,267-268,295` uses the primary-driver role and branches on `plan_to_exec_gate`; `.agent/docs/issue-lifecycle-guide.md:246-252` does the same; `.agent/docs/agentic-methodology.md:196-203` shows both gate outcomes. However the operational lifecycle source still requires an unconditional pre-review human stop at `.agent/docs/development-lifecycle.md:48,229-241`, repeats unconditional human plan approval at `:487-515`, and says humans trigger reviews/approve corrections at `:268-276,364-373`. That contradicts `GUARDRAILS.md:15-21`, create-plan §5, and the corrected correction workflows. The delegated report template also still says “Say start execution” unconditionally at `.agent/workflows/delegated-plan-creation.md:276-295`, even though the same section says `reviewer-auto` continues automatically. |
| M5 — stale current model choices in schema/tests/SVG | **PARTIAL** | The Bedrock test is now adequately labeled as an intentionally historical provider-availability probe at `.agent/skills/cli-dispatch/tests/Test-OpenCodePoC.ps1:257-261`. The accepted `count_session_tokens.py` deferral is explicitly explained and labeled at `.agent/schemas/reflection.v1.yaml:49-57`, so the deferral itself is not a failure. But the schema's name-only `environment` enum remains at `:39-43` without a capability-profile migration label, and the supposed SVG follow-up label is not present: `.agent/docs/diagrams/development-lifecycle-overview.svg:1` still contains two current-looking `GPT-5.5` labels (and the obsolete human-stop rendering) with no in-place follow-up annotation. The SVG deferral therefore is not adequately labeled in the working tree. |
| M6 — imperative Antigravity tool names lacked capability framing | **RESOLVED** | `AGENTS.md:134-140` now requires session-start profile resolution and globally defines literal tool names as capability placeholders. Entry-point framing is also present in `.agent/workflows/tdd-implementation.md:7,40-42`, `.agent/workflows/cli-dispatch.md:9,42-45,140-142`, and `.agent/skills/terminal-preflight/SKILL.md:8-16`. |
| L1 — canonical-doc relative paths were non-resolvable | **RESOLVED** | `.agent/docs/harness-profiles.md:131-138` now uses resolvable links to root governance files, workflows, and skills; `.agent/docs/model-routing.md:62-64` links to `../skills/cli-dispatch/SKILL.md`. |
| L2 — role/tier taxonomy was ambiguous | **PARTIAL** | `.agent/docs/model-routing.md:13-27` now defines “3 model tiers + external reviewer + 2 execution modes” and maps every harness role; `.agent/docs/model-delegation.md:1-5` adopts the same taxonomy. `.agent/docs/commands.md:79-81` still calls the six listed components a “four-tier model stack,” so the ambiguity survives in a live navigation document. |

### New Findings From Regression Check

| ID | Severity | Finding | File:line evidence |
|---|---|---|---|
| R2-N1 | Medium | The new layer model makes Antigravity a `host`, but gate consumers still use “Antigravity acting as orchestrator” as the sole `reviewer-auto` example. The resolver says the driver supplies `role` and tools, while a host only contributes gate/injection constraints; the Antigravity row is nevertheless `role: host` and its own driver is described as retired. There is therefore no defined primary-driver profile that realizes the documented `reviewer-auto` example. Clarify whether a legacy Antigravity driver has a separate profile or remove the unreachable example. | `.agent/docs/harness-profiles.md:14-37,70-78,99-104`; `AGENTS.md:83`; `.agent/workflows/create-plan.md:303-304` |
| R2-N2 | Low | SIGN 3's new prose says both approval forms “are out-of-band, agent-initiated, file-verifiable.” That describes the reviewer artifact, not a direct human chat message. The surrounding bullets preserve the correct gate, so this is not an authorization bypass, but the provenance test is internally false and should distinguish (a) from (b). | `GUARDRAILS.md:88-101` |

The regression sweep also found no whitespace errors (`git diff --check` clean) and no newly broken canonical relative link among the paths reviewed. The remaining lifecycle and fallback-chain contradictions are accounted for under M1/M4 rather than duplicated as new IDs.

### Overall Verdict

`changes_required` — H1, H2's current hybrid-safety case, H3, M2, M3, M6, and L1 are fixed. Approval is still blocked by operationally live contradictions: execution-review workflows do not implement the canonical reviewer chain or exhaustion gate (M1), the lifecycle source still mandates the obsolete unconditional human stop and correction approvals (M4), and the routing taxonomy still contradicts its navigation summary (L2). M5's accepted code deferral is labeled adequately, but the asserted SVG label is absent and the name-only schema enum is not explicitly covered by the follow-up. R2-N1 also leaves the documented `reviewer-auto` profile structurally ambiguous.

## Round 3
verdict: changes_required

### Per-Item Resolution

| Finding | Resolution | File:line evidence |
|---|---|---|
| M1 — canonical three-rung reviewer chain and all-rungs HARD STOP | **PARTIAL** | The canonical route and terminal state are now correct in `.agent/docs/model-routing.md:45-64` and `.agent/skills/cli-dispatch/SKILL.md:1074-1082`; the detailed plan/execution consumers also enumerate all three rungs and the terminal stop at `.agent/workflows/create-plan.md:247-250,346-348,415-421` and `.agent/workflows/execution-session.md:134-138`. However live summaries still encode the retired two-reviewer model: `.agent/workflows/execution-session.md:47` says “Codex CLI (or Claude fallback),” `:67` says “Codex/Claude validation,” and `:153` says “both reviewers rate-limited”; `GUARDRAILS.md:17,50` likewise permits a pause when “both reviewers” are rate-limited. `.agent/docs/development-lifecycle.md:293-299` also jumps from a provider rate limit directly to manual web submission rather than first requiring the remaining CLI rungs. The all-rungs rule is therefore not consistent across every live consumer. |
| M4 — lifecycle/report gate behavior | **PARTIAL** | The lifecycle narrative now says review is auto-dispatched, corrections auto-proceed, and the post-approval transition branches on `plan_to_exec_gate` at `.agent/docs/development-lifecycle.md:229-270,364-376`; the delegated report is now correctly conditional at `.agent/workflows/delegated-plan-creation.md:267-296`. Two lifecycle diagrams remain contradictory: the top flow places the plan→execution gate inside Phase 4 *before* Phase 5 review (`.agent/docs/development-lifecycle.md:43-60`), although the prose says the branch occurs only after reviewer `approved` (`:241,256,270`); and the Human Intervention Summary places that conditional gate under “Always Human” (`:485-487`) while its table correctly says `reviewer-auto` auto-continues (`:515`). |
| M5 — intentionally deferred SVG/token-schema migrations are labeled in place | **RESOLVED** | `.agent/schemas/reflection.v1.yaml:39-43` explicitly identifies the name-based `environment` enum as compatibility-only and labels its capability-profile migration as a follow-up; `:49-57` preserves and labels the `count_session_tokens.py` follow-up. `.agent/docs/diagrams/development-lifecycle-overview.svg:1` now contains an in-place dated `FOLLOW-UP` comment stating that the rendered SVG is stale, naming both the GPT-5.5 and unconditional-human-stop defects, and pointing to regeneration from the corrected Mermaid source. The deferred regeneration/code change is adequately labeled and is not itself a failure. |
| L2 — role/tier taxonomy | **RESOLVED** | `.agent/docs/model-routing.md:13-27` consistently defines three model tiers, one external reviewer, and two execution modes, with an explicit harness-role mapping. `.agent/docs/commands.md:79-81` now uses the same taxonomy; the former “four-tier model stack” wording is gone. |
| R2-N1 — reachable `reviewer-auto` profile | **RESOLVED** | `.agent/docs/harness-profiles.md:74-75` now separates the current Antigravity host (`plan_to_exec_gate: n/a`) from a legacy Antigravity **driver** (`role: primary-driver`, `plan_to_exec_gate: reviewer-auto`), so a concrete driver profile now realizes the example. A contradictory note about that profile is recorded as R3-N1 below rather than reopening the structural-reachability finding. |
| R2-N2 — SIGN 3 provenance conflation | **RESOLVED** | `GUARDRAILS.md:84-96` separates trusted provenance from sufficient authorization, and `:98-108` now distinguishes why (a) direct human chat is trusted (`USER_EXPLICIT`) from why (b) the reviewer artifact is trusted (out-of-band, agent-dispatched, file-verifiable). The text no longer attributes the reviewer artifact's properties to the human message. |

### New Regression Findings

| ID | Severity | Finding | File:line evidence |
|---|---|---|---|
| R3-N1 | Medium | The canonical profile note still assigns the impossible `host` + `reviewer-auto` tuple to “Antigravity-as-orchestrator.” The host row has no gate and the merge contract says the driver supplies the role/gate; only the new legacy-driver row realizes `reviewer-auto`. This can misroute the authorization branch despite the new row fixing R2-N1's reachability defect. Change the note to identify the legacy Antigravity **driver** (`primary-driver`, `reviewer-auto`), not the host. | `.agent/docs/harness-profiles.md:29-35,74-75,100-103` |
| R3-N2 | Medium | The lifecycle's main flow now relabels the old pre-review human node as `Plan→Exec Gate` without moving it: the gate still executes before the external-review phase. Its later “Always Human” placement independently contradicts the `reviewer-auto` branch. These diagrams are operational guidance and disagree with the corrected narrative and `create-plan.md` §5c. | `.agent/docs/development-lifecycle.md:43-60,229-241,485-487,515`; `.agent/workflows/create-plan.md:283-308` |

The regression sweep found no whitespace errors (`git diff --check` clean). The `plan_to_exec_gate` branch is otherwise aligned in `AGENTS.md:81-85`, `GUARDRAILS.md:84-108`, `.agent/workflows/create-plan.md:283-308`, `.agent/workflows/execution-session.md:47-49`, and the corrected delegated-plan report. The remaining reviewer-chain contradictions are accounted for under M1 rather than duplicated as a new ID.

### Overall Verdict

`changes_required` — M5, L2, R2-N1's structural reachability issue, and R2-N2 are resolved. Approval remains blocked because the three-rung/all-rungs contract is still contradicted by live `GUARDRAILS.md` and `execution-session.md` language (M1), the lifecycle diagrams still put a conditional post-review gate before review and under “Always Human” (M4/R3-N2), and the canonical profile note assigns `reviewer-auto` to a host row whose gate is explicitly `n/a` (R3-N1).

## Round 4
verdict: changes_required

### Per-Item Resolution

| Finding | Resolution | File:line evidence |
|---|---|---|
| M1 — canonical three-rung reviewer chain and all-rungs HARD STOP | **PARTIAL** | The Round-3 residual summaries are corrected: `.agent/workflows/execution-session.md:47,67,134-138,153` now names the canonical Codex → Gemini-surface → headless-Claude chain and the all-rungs terminal state; `GUARDRAILS.md:17,50` now says all reviewer rungs; and `.agent/docs/development-lifecycle.md:295-298` requires exhausting the chain before human/web escalation. No retired “both reviewers,” “Codex or Claude,” or “Codex/Claude validation” summary remains as a behavioral rule in the named consumers. However the executable fallback skill is internally contradictory: its new rule requires walking the chain in order and makes all-rungs exhaustion the HARD STOP (`.agent/skills/cli-dispatch/SKILL.md:1076-1082`), while the still-live numbered steps for a single provider rate limit immediately save a web prompt and recommend manual web submission, relegating cross-routing to optional “Option C” (`:1092-1103`). That procedure can still stop at the first provider instead of mandatorily trying eligible remaining rungs, so the every-live-consumer requirement is not met. |
| M4 / R3-N2 — lifecycle Mermaid gate placement and classification | **RESOLVED** | In the top Mermaid flow, Phase 5 contains reviewer dispatch and the approval loop (`.agent/docs/development-lifecycle.md:51-58`), then `E5[Plan Approved]` flows to the plan→exec gate at `:59`; the phase edges place Phase 5 before Phase 6 at `:100-102`. In the Human Intervention Summary, “Always Human” contains only build-plan authoring, threshold sign-off, commit scope, and push timing (`:485-490`); the conditional plan→exec gate is under “Sometimes Human” at `:492-499`, matching the conditional table rule at `:515`. |
| R3-N1 — impossible host + `reviewer-auto` tuple | **RESOLVED** | The profile table assigns the Antigravity host `plan_to_exec_gate: n/a` at `.agent/docs/harness-profiles.md:74` and assigns `reviewer-auto` only to the dormant legacy Antigravity `primary-driver` at `:75`. The explanatory note explicitly says a host never sets the gate and identifies the legacy Antigravity driver as the sole `reviewer-auto` profile (`:100-107`). This matches `AGENTS.md:83`, `GUARDRAILS.md:19`, and `.agent/workflows/create-plan.md:303-304`. |

### New Regression Findings

| ID | Severity | Finding | File:line evidence |
|---|---|---|---|
| R4-N1 | Low | The lifecycle reintroduces the taxonomy contradiction that prior rounds treated as resolved: a newly added canonical-source note calls the routing model a “four-tier stack,” while the canonical document expressly defines “3 model tiers + external reviewer + 2 execution modes.” The lifecycle sentence even says it must not contradict the canonical source. Replace “four-tier stack” with the canonical taxonomy. | `.agent/docs/development-lifecycle.md:768`; `.agent/docs/model-routing.md:13-20` |

The regression sweep found no whitespace errors (`git diff --check` clean). Apart from M1's contradictory detailed fallback sequence and R4-N1, no new authorization, gate-placement, host/driver, or reviewer-chain contradiction was found in `AGENTS.md`, `GUARDRAILS.md`, `create-plan.md`, `execution-session.md`, `harness-profiles.md`, `model-routing.md`, `cli-dispatch/SKILL.md`, or the lifecycle diagrams. The repo-wide residual phrase scan found `.agent/workflows/execution-critical-review.md:204` using “both Codex and Claude” only for the optional case where both reviewers actually run under a minority-veto rule; it does not redefine the fallback chain or all-rungs stop condition.

### Overall Verdict

`changes_required` — M4/R3-N2 and R3-N1 are resolved, and the specifically named Round-3 M1 summaries are corrected. Approval remains blocked because the operational fallback steps in `cli-dispatch/SKILL.md` still permit first-provider web escalation instead of mandating the canonical remaining rungs. The low-severity “four-tier stack” regression should be corrected in the same pass.

## Round 5
verdict: approved

### Per-Item Resolution

| Finding | Resolution | File:line evidence |
|---|---|---|
| M1 — fallback steps allowed first-provider web escalation | **RESOLVED** | `.agent/skills/cli-dispatch/SKILL.md:1076-1082` establishes the ordered chain and makes all-rungs exhaustion a human-decision HARD STOP; `:1094-1102` explicitly says the order is mandatory, forbids a single provider from jumping to web, and requires the next eligible rung first; `:1103-1110` permits web/human submission only after every rung is rate-limited or unavailable and explicitly forbids self-review. The provider matrix at `:1118-1120` preserves Gemini for surface work and isolated headless Claude for deep/infra work before the manual-web terminal option. |
| R4-N1 — lifecycle used “four-tier stack” | **RESOLVED** | `.agent/docs/development-lifecycle.md:768` now uses the canonical “3 model tiers + external reviewer + 2 execution modes” taxonomy, matching `.agent/docs/model-routing.md:13-20`. The stale phrase is absent from the live governance surface. |

### Regression Check

No new contradiction was introduced by either edit. The reviewer-chain/all-rungs rule remains aligned across `.agent/docs/model-routing.md:45-64`, `.agent/workflows/create-plan.md:247-250,346-348,415-421`, `.agent/workflows/execution-session.md:134-138,153`, `GUARDRAILS.md:17,50`, and `.agent/docs/development-lifecycle.md:293-299`. The `plan_to_exec_gate` branch remains consistent across `AGENTS.md:81-85`, `GUARDRAILS.md:19-29,84-108`, `.agent/docs/harness-profiles.md:29-45,74-75,100-107`, and `.agent/workflows/create-plan.md:280-308`: reviewer approval auto-continues only for `reviewer-auto`; `human` requires fresh `USER_EXPLICIT` approval. No path permits same-session self-review. `git diff --check` is clean.

### Overall Verdict

`approved` — both Round-4 residuals are resolved, the two edits introduce no regression, and the working-tree governance refactor is globally consistent on the independent-reviewer chain, all-rungs exhaustion behavior, and capability-flag-controlled plan→execution gate.
