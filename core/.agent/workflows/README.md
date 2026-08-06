# {{PROJECT_NAME_TITLE}} Workflows

> Relocated from AGENTS.md (2026-06-13 instruction-set-optimization slim): the Workflow Invocation table. Workflow files live in this directory.


<!-- Executor column: current_agent = orchestrator executes inline; external_reviewer = dispatch to the independent-reviewer chain (primary: codex_cli / Codex GPT-5.6-sol → Gemini 3.5 surface-only → headless `claude -p` last resort — full chain and vendor-diversity rationale in .agent/docs/model-routing.md); human_gate = requires human action -->

| Slash Command | Workflow File | Executor |
|---|---|---|
| `/create-plan` | `.agent/workflows/create-plan.md` | current_agent (auto-dispatches `/plan-critical-review` at Step 5 **and** `/execution-critical-review` at Step 6/§6a — a standalone run owns its own execution review) |
| `/delegated-plan-creation` | `.agent/workflows/delegated-plan-creation.md` | **claude_cli** (Fable 5 / Opus 4.8 — Fable 5 for very-large single-shot architecture tasks, Opus 4.8 (coordinator tier) otherwise; Sonnet 5 (builder tier) handles delegated bulk work — see `.agent/docs/model-routing.md`) for plan Steps 1-4; **orchestrator** handles the `external_reviewer` review loop (Step 5). Use when planning benefits from deeper reasoning or to preserve orchestrator context. |
| `/execution-session` | `.agent/workflows/execution-session.md` | current_agent (auto-dispatches `/execution-critical-review` at Step 4c) |
| `/orchestrated-delivery` | `.agent/workflows/orchestrated-delivery.md` | current_agent |
| `/pre-build-research` | `.agent/workflows/pre-build-research.md` | current_agent |
| `/tdd-implementation` | `.agent/workflows/tdd-implementation.md` | current_agent |
| `/validation-review` | `.agent/workflows/validation-review.md` | **external_reviewer** (primary `codex_cli`; full chain in `.agent/docs/model-routing.md`) — dispatch per Step 0, do NOT self-review |
| `/plan-critical-review` | `.agent/workflows/plan-critical-review.md` | **external_reviewer** (primary `codex_cli`; full chain in `.agent/docs/model-routing.md`) — dispatch per cli-dispatch SKILL.md (auto-dispatched by `/create-plan`) |
| `/execution-critical-review` | `.agent/workflows/execution-critical-review.md` | **external_reviewer** (primary `codex_cli`; full chain in `.agent/docs/model-routing.md`) — dispatch per cli-dispatch SKILL.md (auto-dispatched by `/execution-session` §4c **and** standalone `/create-plan` §6a) |
| `/plan-corrections` | `.agent/workflows/plan-corrections.md` | current_agent |
| `/execution-corrections` | `.agent/workflows/execution-corrections.md` | current_agent |
| `/meu-handoff` | `.agent/workflows/meu-handoff.md` | current_agent |
| `/mcp-audit` | `.agent/workflows/mcp-audit.md` | current_agent |
| `/issue-triage` | `.agent/workflows/issue-triage.md` | current_agent |
| `/next-project` | `.agent/workflows/next-project.md` | current_agent |
| `/session-grouping` | `.agent/workflows/session-grouping.md` | current_agent (PLANNING-only; findings/phase → MEUs → sessions; hands off to `/create-plan`; non-gating, no turn-ender) |
| `/inspiration-research` | `.agent/workflows/inspiration-research.md` | current_agent (procedure in `.agent/skills/deep-research-prompting/SKILL.md`; Step 0 Pomera MCP preflight is a HARD GATE — on failure notify the human and end the turn, never silently fall back to native search) |
| `/skill-optimize` | `.agent/workflows/skill-optimize.md` | current_agent (dispatches the cross-vendor judge per cli-dispatch; stages for human adoption — never auto-merges) |
| `/cli-dispatch` | `.agent/workflows/cli-dispatch.md` | current_agent (routes to Codex / Claude / agy per skill; independent review stays on the Codex chain) |
