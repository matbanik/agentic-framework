# MANIFEST — Transferable Agentic Framework Package

This package was assembled by **copying** files out of the source repository into
`_transfer-out/agentic-framework/`, then running `scripts/sanitize.py` to replace every
project-specific identifier (the project slug, repo URL, root path, and receipts dir) with
`{{PLACEHOLDER}}` tokens. Content was otherwise unchanged — no file was moved or deleted.
Every entry below was verified to exist at copy time and its one-line purpose was derived by
reading the file's own header (H1 / frontmatter `description:` / opening paragraph) — not guessed.

> **Placeholders:** every file under `core/` contains tokens like `{{PROJECT_NAME}}`,
> `{{PROJECT_ROOT}}`, `{{RECEIPTS_DIR}}`, `{{REPO_URL}}`. Run `scripts/instantiate.py` (see
> `ADOPTION-GUIDE.md` Step 2) to fill them with your project's values before use.

---

## Package-root `.agent/` — registry-home template

Human decision Q1: this directory **templates** the registry home for adopters.
`core/.agent/` remains the in-package instruction copy. Both exist; neither
replaces the other. The template ships the twelve global classes with empty
`catalog`, `bindings`, and `pins`. A model bump is a live-registry edit, not a
recopy of this package. How to copy, fill, compile, and check: `.agent/INSTANTIATE.md`.

- `.agent/INSTANTIATE.md` — How an adopter copies this template to a drive-root or workspace-root home, fills catalog/bindings, compiles, and runs the checker. §6 is the bump procedure: shortlist, add-to-catalog and compile, rehearse, eval-gate an isolated candidate, edit one binding, recompile, sync, enforce.
- `.agent/model-registry.template.yaml` — Twelve global classes with contracts; catalog, bindings, and pins empty. No `forbid` or `eval_gate` values (those hold catalog ids / machine paths).
- `.agent/docs/model-classes.md` — Class list and the `resolve` paste-able dispatch contract. Names no snapshots.
- `.agent/schema/model-registry.v1.schema.json` — Same schema as the live registry.
- `.agent/tools/resolve_model.py` — Thin locate-and-forward wrapper. Swap in the real tool once this home is live.
- `.agent/tools/check_model_slugs.py` — Thin wrapper, same reason (the live implementation embeds catalog examples).
- `.agent/tools/ModelRegistry.psm1` — Slug-free copy. Exports `resolve <class> [-Harness x] [-AuthorVendor y]`; prints the bare slug; infers harness when a class binds exactly one; raises `ambiguous_harness` rather than guessing.

---

## 1. `core/` — root governance

- `core/AGENTS.md` — Full operating model for AI agents on {{PROJECT_NAME_TITLE}}: priority hierarchy (P0 environment stability → P1 quality gates → P2 task completion → P3 speed), role specs, workflows, TDD protocol, execution contract, and validation pipeline.
- `core/GUARDRAILS.md` — Non-negotiable safety SIGNs (plan approval gate, anti-premature-stop scope, system-message immunity) each derived from a real governance-failure incident.
- `core/CLAUDE.md` — Session-start pointer file that ensures Claude Code loads `AGENTS.md`/`GUARDRAILS.md` (internal) and `docs/AGENTS.md` (external contributors) before acting.

## 2. `core/.agent/docs/`

- `harness-profiles.md` — Capability-flag matrix (including `fresh_worker`) so governance docs/workflows behave correctly regardless of which agentic harness is driving the session, instead of hard-branching on harness name.
- `model-routing.md` — Canonical answer to "which capability class handles which task, and why" — class names only; snapshot bindings live in the live registry.
- `model-delegation.md` — Mechanical vs. correctness work-class taxonomy, plus the in-harness `{{PROJECT_NAME}}-builder` / `{{PROJECT_NAME}}-verifier` route (gated by `fresh_worker`).
- `context-compression.md` — Compression rules (verbosity tiers, delta-only diffs, cache boundaries) that all handoff/review/evidence artifacts must follow.
- `development-lifecycle.md` — Canonical source-of-truth for the end-to-end 9-phase development process from inspiration to committed code, including human-intervention points.
- `agentic-methodology.md` — Narrative companion to the lifecycle doc: the philosophy, economics, and design rationale behind the agentic development methodology.
- `artifact-naming.md` — Date-based naming convention reference for handoffs, reviews, and reflections (relocated out of AGENTS.md).
- `code-quality.md` — Tiered code-quality standards (Maximum vs. Balanced tiers) with detailed examples and forbidden patterns.
- `testing-strategy.md` — Test pyramid, fixtures, coverage targets, and E2E wave-activation rules.
- `emerging-standards.md` — Living registry of mandatory implementation standards discovered during development sessions, enforced during plan/execution critical review.
- `commands.md` — Operational reference: quick validation/dev/scaffold commands, skills index, MCP servers, and RTK usage.
- `issue-lifecycle-guide.md` — How issues are reported, tracked, triaged, planned, and resolved end-to-end, with human/AI handoff points.
- `triage-meu-loop.md` — Compact portable contract for the report → triage → MEU register → session-group → plan → reflect learning loop.
- `prompt-templates.md` — Copy-paste prompt templates for driving an agentic build session through an AI coding assistant.
- `natural-writing-guide.md` — Project-wide mandatory style guide for AI-generated prose to avoid "corporate mid" writing patterns.
- `claude-cli-fallback-lessons.md` — Lessons learned from using Claude CLI as a fallback reviewer when Codex CLI was rate-limited.
- `macos-setup.md` — macOS/Linux companion for P0 shell redirect, Codex CLI install, and cross-platform `Invoke-CodexDispatch.ps1` usage (research-backed; hardware smoke pending).
- `context-tool-decision-gate.md` — Decision gate for when orchestrators may invoke context/MCP tools during planning and execution (eligible-tool inventory + token-savings rules).
- `diagrams/development-lifecycle-overview.svg` — Visual diagram companion to `development-lifecycle.md`.

## 3. `core/.agent/workflows/`

- `README.md` — Slash-command → workflow-file → executor routing table (which workflows run inline vs. dispatch to an external reviewer vs. require a human gate).
- `create-plan.md` — Start-of-build-session workflow: discovers what's done, scopes a coherent project of related MEUs, and generates the implementation plan (auto-dispatches plan review at Step 5).
- `execution-session.md` — Structured Plan → Execute → Reflect workflow for daily build sessions, ensuring TDD discipline and handoff quality.
- `plan-critical-review.md` — Adversarial review of an unstarted execution plan before implementation begins; findings-only, never fixes issues.
- `execution-critical-review.md` — Adversarial review of completed implementation work/handoffs for correctness, test rigor, and contract compliance; findings-only.
- `validation-review.md` — Validation/adversarial-review workflow for the external reviewer (Codex): runs the full test suite, reviews code, issues a verdict.
- `plan-corrections.md` — Resolves `/plan-critical-review` findings by correcting plan documents, task contracts, and workflow docs — never production code.
- `execution-corrections.md` — Resolves `/execution-critical-review` findings by correcting production code, tests, and infrastructure — never plan documents.
- `tdd-implementation.md` — TDD-first implementation workflow: write tests first, implement to pass, hand off to the validation agent.
- `meu-handoff.md` — Defines the self-contained handoff artifact format for passing MEU-scoped work between implementation and validation agents.
- `orchestrated-delivery.md` — Canonical multi-role workflow (orchestrator → coder → tester → reviewer) for scoped implementation tasks.
- `delegated-plan-creation.md` — Delegates plan-generation steps of `/create-plan` to a CLI agent, then runs the review/correction loop from the orchestrator.
- `next-project.md` — Planning-only workflow that reviews the build plan, MEU registry, and dependency graph to recommend the next unblocked project.
- `cli-dispatch.md` — Routes specialized tasks (validation, creative writing, data processing) to external CLI agents and collects results back to the orchestrator.
- `pre-build-research.md` — Research-before-build workflow: scans external repos, extracts patterns, and produces AI instruction sets before implementing a feature.
- `inspiration-research.md` — Generates provider-tailored deep-research prompts (ChatGPT/Gemini/Claude) for a given topic for the human to run manually.
- `session-grouping.md` — Turns a body of work (review findings, a build-plan phase, recommendations) into registered MEUs bundled into one-project-per-session groupings.
- `session-meta-review.md` — Structured retrospective workflow over a session log to surface friction points and generate concrete improvement rules.
- `skill-optimize.md` — On-demand optimizer that proposes bounded, cross-vendor-judge-gated edits to a skill/workflow doc and stages them for human adoption.
- `issue-triage.md` — Reviews known issues, verifies reproducibility, classifies and buckets them into MEUs, and generates triage output feeding session-grouping/create-plan.

## 4. `core/.agent/roles/`

- `coder.md` — Coder role: implement only the requested change, keep architecture boundaries intact, produce production-ready code with explicit error handling.
- `guardrail.md` — Optional guardrail role: final safety gate for risky changes involving security, data integrity, encryption, authentication, migrations, destructive operations.
- `orchestrator.md` — Orchestrator role: own one scoped project end-to-end, select the minimum role set, enforce sequencing, block completion until gates are satisfied.
- `researcher.md` — Optional researcher role: gather high-signal prior art and turn it into concrete implementation guidance before coding starts.
- `reviewer.md` — Reviewer role: findings-first adversarial review focused on defects, behavioral regressions, architecture violations, and testing blind spots.
- `tester.md` — Tester role: verify implementation matches requested behavior and identify regressions with reproducible test evidence.

## 5. `core/.agent/skills/`

- `README.md` — Explains the progressive-disclosure model for skills (loaded on demand, not at session start) and when to create a new SKILL.md.
- `cli-dispatch/SKILL.md` — Mechanics of routing tasks to the optimal external CLI agent (Codex/Claude/Gemini/OpenCode) based on task type; routing policy itself lives in `model-routing.md`.
- `cli-dispatch/tests/Test-CliDispatch.ps1` — Validation test suite exercising all CLI-dispatch routes (Codex validation, Codex image gen, data-processing agent, Claude creative writing).
- `cli-dispatch/tests/Test-OpenCodePoC.ps1` — Proof-of-concept test suite validating OpenCode CLI as a dispatch target via Amazon Bedrock.
- `completion-preflight/SKILL.md` — Mandatory pre-flight checklist before any stop/summary/"complete" report, enforcing a deterministic re-read of `task.md` to prevent premature stop.
- `pre-handoff-review/SKILL.md` — Self-review checklist codifying 10 recurring failure patterns from prior critical reviews, run before declaring a MEU "ready for review."
- `terminal-preflight/SKILL.md` — Mandatory pre-flight checklist for terminal commands enforcing the redirect-to-file pattern to prevent shell buffer-saturation hangs.
- `quality-gate/SKILL.md` — Validation pipeline (type checks, lint, tests, anti-placeholder scan, evidence checks) supporting both phase-level and MEU-scoped runs.
- `git-workflow/SKILL.md` — Agent-safe git commit/push operations with SSH signing, avoiding interactive prompt hangs.
- `git-workflow/scripts/agent-commit.ps1` — Script wrapper for the git commit workflow: validates signing config, runs lint+tests, stages, commits, and pushes safely.
- `timestamp/SKILL.md` — Generates the canonical completion timestamp for workflow exit lines, handoffs, and reflections.
- `timestamp/scripts/stamp.py` — Script that emits a completion timestamp in the project's canonical format using the system clock and local timezone.
- `skill-optimizer/SKILL.md` — Toolkit/contract for evolving an instruction doc via bounded edits gated by a cross-vendor LLM-judge over held-out evidence.
- `skill-optimizer/rubric-templates.md` — LLM-judge rubric consumed by the skill-optimizer validation gate; scores candidate-vs-baseline instructions pairwise per dimension.
- `session-meta-review/SKILL.md` — Structured analysis toolkit (friction taxonomy, segment-detection patterns, research query bank) for reviewing session logs.
- `subagent-delegation/SKILL.md` — In-harness subagent detection + delegation gate for Cursor (`.cursor/agents/`) and Claude Code (`.claude/agents/`). Resolves `fresh_worker` from the harness profile (never from directory presence), decides which `task.md` rows may be delegated, enforces never-delegate categories (correctness, review verdicts, commits, human gates), and feeds outcomes into the reflection loop.
- `subagent-delegation/verification-log.md` — Portable stub for the resolved-driver smoke + builder write-route probe. Adopters replace the placeholders with real receipt paths after a live probe; a `[B]` is never a pass.
- `issue-triage/SKILL.md` — Record/query/verify/bucket/triage known issues via `tools/issue_triage.py` and `.agent/context/known-issues.yaml`.
- `meu-status/SKILL.md` — Query/update/render MEU completion status via `tools/meu_status.py` and `.agent/context/meu-status.yaml`.
- `deep-research-prompting/SKILL.md` — Pomera MCP preflight gate, provider capability recon, and portal-ready deep-research prompt templates; driven by `/inspiration-research`. **Manual adopter edit required** if Pomera is not your search surface (see `ADOPTION-GUIDE.md` §Provider substitution).

## 5b. `core/.cursor/agents/` and `core/.claude/agents/` (in-harness subagents)

> Filenames keep the `{{PROJECT_NAME}}` token until `instantiate.py` + a rename step (see
> `ADOPTION-GUIDE.md` Step 2). Cursor and Claude Code register subtypes from the filename stem /
> frontmatter `name:`.

- `.cursor/agents/{{PROJECT_NAME}}-builder.md` — Mechanical-class executor for one `task.md` row. AUTOGEN template: `model:` is filled from the registry, not hand-maintained.
- `.cursor/agents/{{PROJECT_NAME}}-verifier.md` — Readonly validator for one `task.md` row (`readonly: true`). AUTOGEN template, same as builder.
- `.claude/agents/{{PROJECT_NAME}}-builder.md` — Same builder contract; AUTOGEN template for the Claude Code agents harness.
- `.claude/agents/{{PROJECT_NAME}}-verifier.md` — Same verifier contract; Claude Code `tools` allowlist (no Write/Edit). AUTOGEN template.
- `README.md` (each agents dir) — Rename-after-instantiate instructions.

## 5c. `core/.agent/context/` — empty seeds (not live product data)

> Copy these stubs into the adopting project. **Never** copy a populated product
> `known-issues.yaml` / `meu-status.yaml` from the source repo.

- `known-issues.yaml` — Empty issue SSOT (`version: 1`, `issues: []`).
- `known-issues.md` — Generated-view stub (regenerate via CLI).
- `known-issues-archive.md` — Archive stub.
- `meu-status.yaml` — Minimal valid MEU SSOT (one starter phase, zero MEUs).
- `meu-registry.md` — AUTOGEN `:registry` markers for `meu_status.py render`.
- `triage-output.EXAMPLE.yaml` — Shape of the ephemeral triage → grouping handoff.
- `grouping/README.md` — Where `/session-grouping` writes proposals.

## 5d. `core/tools/` — issue + MEU CLIs + Codex dispatch

**Issue → MEU learning loop (named capability):** the combination of `issue_triage*`, `meu_status*`, context seeds, `triage-meu-loop.md`, and the `/issue-triage` → `/session-grouping` → `/create-plan` workflows is the framework's **learning-from-mistakes engine** — defects become registered issues, bucket into MEUs, feed session grouping, and surface as design rules in reflections. See `ADOPTION-GUIDE.md` Step 4b.

- `tools/issue_triage.py` + `tools/issue_triage/` — Known-issues SSOT CLI (add/list/verify/render/bucket/triage/discover/promote/dismiss).
- `tools/meu_status.py` + `tools/meu_status/` — MEU SSOT CLI (list/next/get/stats/update/render) + `meu-status.schema.json`.
- `tools/Invoke-CodexDispatch.ps1` — Cross-platform PowerShell wrapper for Codex CLI independent-review dispatch (timeout, process-tree cleanup, receipt capture); documented in `cli-dispatch/SKILL.md`.
- `tools/Invoke-CodexDispatch.sh` — POSIX/bash companion with the same dispatch contract for macOS/Linux when `pwsh` is unavailable; see `macos-setup.md`.
- `tools/__init__.py` — Package marker so `python tools/<cli>.py` imports resolve.

> **Adopter edits required:** `tools/issue_triage/model.py` → `VALID_COMPONENTS` (Block D8).
> Python deps: `pyyaml`, `jsonschema`. macOS/Linux adopters: read `macos-setup.md` before first dispatch.

## 6. `core/.agent/schemas/`

- `reflection.v1.yaml` — Schema defining the YAML instruction-coverage block agents must emit at session end (field semantics, token budget).
- `review-verdict.schema.json` — JSON Schema for structured independent-review verdict files (`approved` / `changes_required` + findings metadata); consumed by plan/execution critical-review workflows.
- `registry.yaml` — Instruction registry: inventory of every AGENTS.md section with auto-derived IDs and P0–P3 priority classification for auto-prune heuristics.

## 7. `core/templates/`

- `HANDOFF-TEMPLATE.md` — Template (renamed from `.agent/context/handoffs/TEMPLATE.md`) for MEU implementation handoff artifacts, with YAML frontmatter (date, project, MEU, status, verbosity, plan source).
- `REVIEW-TEMPLATE.md` — Template (renamed from `.agent/context/handoffs/REVIEW-TEMPLATE.md`) for plan/handoff critical-review artifacts, with YAML frontmatter (verdict, findings count, requested verbosity).
- `PLAN-TEMPLATE.md` — Template (renamed from `docs/execution/plans/PLAN-TEMPLATE.md`) for `implementation-plan.md`, with YAML frontmatter (project, source, MEUs, status).
- `TASK-TEMPLATE.md` — Template (renamed from `docs/execution/plans/TASK-TEMPLATE.md`) for `task.md`. Supports legacy 9-column and 10-column tables (`builder_model` optional) plus optional `delegate_to: {{PROJECT_NAME}}-builder|{{PROJECT_NAME}}-verifier` prose in the Task cell.
- `REFLECTION-TEMPLATE.md` — Template (renamed from `docs/execution/reflections/TEMPLATE.md`) for the end-of-session meta-reflection artifact, including the delegation outcome question.
- `BUILD_PLAN-STUB.md` — Spec/build-plan stub with `meu-status` AUTOGEN markers (`:phase-tracker`, `:summary`). Copy to `docs/BUILD_PLAN.md` (or your D3 Spec path).

## 8. `examples/`

- `examples/example-multi-round-independent-review.md` — Worked example of the independent-review loop (renamed from `.agent/context/handoffs/2026-07-13-harness-agnostic-governance-critical-review.md`): a real adversarial review with a `changes_required` verdict and severity-ranked findings against a 22-file governance refactor diff.

## 9. `scripts/` — placeholder tooling (package root, not copied into your project)

- `scripts/placeholders.py` — Shared substitution rules: the single source of truth mapping real project strings ↔ `{{PLACEHOLDER}}` tokens, used by both scripts below so the two directions can never drift.
- `scripts/sanitize.py` — Authoring tool that produced this package: rewrites real project identifiers → placeholder tokens (`--dry-run`, `--verify`). Ships for transparency/audit; adopters normally don't run it.
- `scripts/instantiate.py` — **The adopter's tool.** Fills every `{{PLACEHOLDER}}` with your project's values from `--config`/flags. Supports `--root` (target your copied tree), `--dry-run`, and `--verify`.
- `scripts/README.md` — Usage for both scripts, the placeholder table, and the recommended adoption flow.

> These three files stay in the transfer package; they are the installer, not framework content, so they are **not** copied into the adopting project.

---

## Deliberately EXCLUDED ({{PROJECT_NAME_TITLE}}-specific — do not port)

**Workflows** (`.agent/workflows/`) — excluded because they encode {{PROJECT_NAME_TITLE}}'s specific product surfaces (Electron GUI, MCP server, GitHub-repo mirroring) rather than generic agentic process:
- `e2e-testing.md` — GUI E2E workflow tied to {{PROJECT_NAME_TITLE}}'s specific Electron/Playwright test harness (`ui/tests/e2e/`).
- `gui-integration-testing.md` — Integration-testing workflow specific to {{PROJECT_NAME_TITLE}}'s Electron GUI layer.
- `graphify.md` — Workflow for {{PROJECT_NAME_TITLE}}'s Graphify code-graph MCP tool, not a generic framework concern.
- `mcp-audit.md` — Audit workflow scoped to {{PROJECT_NAME_TITLE}}'s own MCP server toolset surface.
- `security-audit.md` — Security-audit workflow written against {{PROJECT_NAME_TITLE}}'s specific architecture and threat model.

**Skills** (`.agent/skills/`) — excluded because they operate on {{PROJECT_NAME_TITLE}}-specific infrastructure, tooling, or repo layout:
- `backend-startup` — Starts {{PROJECT_NAME_TITLE}}'s specific FastAPI/Electron backend stack.
- `ci-troubleshooting` — Debugs {{PROJECT_NAME_TITLE}}'s specific CI pipeline configuration.
- `e2e-testing` — {{PROJECT_NAME_TITLE}}'s Electron/Playwright E2E test harness skill.
- `graphify` — Operates {{PROJECT_NAME_TITLE}}'s Graphify code-graph MCP tool.
- `mcp-audit` — Audits {{PROJECT_NAME_TITLE}}'s own MCP server toolset.
- `mcp-rebuild` — Rebuilds {{PROJECT_NAME_TITLE}}'s MCP server specifically.
- `pre-push-contract-scan` — Scans {{PROJECT_NAME_TITLE}}'s specific API/contract surface before push.
- `public-repo-sync` — Syncs {{PROJECT_NAME_TITLE}}'s private repo state to its public GitHub mirror.
- `tui-e2e` — {{PROJECT_NAME_TITLE}}'s TUI PTY-harness E2E testing skill.
- `vm-harness` — Manages {{PROJECT_NAME_TITLE}}'s VM-based test/build harness.

> **Formerly excluded, now packaged (portable):** `issue-triage` and `meu-status` skills +
> `tools/issue_triage*` / `tools/meu_status*` + empty context seeds. Live product YAML content
> remains excluded.

**Docs** (`.agent/docs/`) — excluded because they describe {{PROJECT_NAME_TITLE}}'s specific product architecture and domain, not portable process:
- `architecture.md` — {{PROJECT_NAME_TITLE}}'s hybrid-monorepo layer/package scaffold and dependency rules.
- `domain-model.md` — {{PROJECT_NAME_TITLE}}'s trading-domain entity/value-object model.
- `feature-triage-quant-tui.md` — Feature triage notes for {{PROJECT_NAME_TITLE}}'s quant TUI initiative.
- `graphify.md` — Reference doc for {{PROJECT_NAME_TITLE}}'s Graphify code-graph tool.
- `gui-standards-enforcement.md` — GUI coding standards specific to {{PROJECT_NAME_TITLE}}'s Electron UI.
- `antigravity-mode-map.md` — Mode-mapping reference tied to the Antigravity harness as used in this specific repo's setup.
- `output-evidence-policy.md` — RTK routing / exact-evidence policy tied to this repo's shell tooling receipts.

**Subagent tooling (source-repo only — do not port as-is):**
- `scripts/verify_subagent_delegation.py` + `tests/tooling/test_verify_subagent_delegation.py` — structural gates used to activate delegation in the originating repo. Portable adopters use the skill + a live smoke receipt instead; re-port only if you want the same machine-check suite.
- Source `verification-log.md` probe receipts — replaced in this package by the portable stub.
- `tools/Invoke-CursorAgentDispatch.ps1` — Cursor Agent CLI orchestrated-dispatch wrapper used in the originating repo. **Deliberately not shipped.** Packaged `cli-dispatch` skill/workflow already scrub Cursor Agent dispatch; independent review stays on the Codex chain. Re-port only if the adopter runs Cursor Agent CLI as an isolated worker and accepts maintaining a second wrapper.

**Planned / source-repo-only automation named by packaged docs (referenced, not shipped):**
- `.agent/skills/session-digest`, `.agent/skills/execution-tldr`, `.agent/skills/advisor-consult` — the session-digest / TL;DR / advisor-consult automation named in `development-lifecycle.md` §Phase 9 and §Governance Files. **Planned** in the originating repo, not built; the lifecycle doc's own NOTE says so. Adopters run those steps manually until they build them.
- `.agent/schemas/decision_log.schema.json`, `.agent/schemas/validation_review.schema.json`, `.agent/docs/decision-authority.md` — same planned-automation set. The two schemas that *are* shipped and enforced are `reflection.v1.yaml` and `review-verdict.schema.json`.
- `tools/skill_optimize/` (incl. `gate.py`) — the deterministic harvest/propose/gate/buffer/stage toolkit behind `/skill-optimize`. The packaged `skill-optimizer/SKILL.md` + `rubric-templates.md` document the contract (edit format, judge rubric, LEARNED-region and human-adoption-is-terminal rules) because those are the transferable part; the toolkit itself is repo-shaped. **`/skill-optimize` is doc-only for adopters** until they implement it.

> These are the reference-integrity gate's raison d'être: a packaged doc naming a path
> that does not ship is only acceptable if the absence is *written down here*. Run
> `tools/_fw_refcheck.py --all` (source repo) to prove no undocumented dangling reference
> exists — that check is what would have caught the 2026-07-22 `Invoke-CodexDispatch.ps1` gap.

**Issue/MEU runtime state (source-repo only):**
- Populated `.agent/context/known-issues.yaml`, `meu-status.yaml`, `triage-output.yaml`, archives, grouping proposals — product history. Package ships **empty seeds** only.
- `tests/tools/test_issue_triage*.py` / `test_meu_status*.py` — optional; re-port if you want the same golden fixtures.
