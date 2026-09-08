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

- `.agent/INSTANTIATE.md` — How an adopter copies this template to a shared or workspace-root home, fills catalog/bindings, compiles, and runs the checker. §6 is the bump procedure: shortlist, add-to-catalog and compile, rehearse, eval-gate an isolated candidate, edit one binding, recompile, sync, enforce.
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
- `verification-principles.md` — When a check is evidence and when it only looks like evidence: 15 numbered principles (V1–V5, V13, V25, V30–V32, V41–V45), each distilled from a gate that reported success while the thing it guarded was broken. Numbering is deliberately non-contiguous and must stay stable — `GUARDRAILS.md` SIGN 1 cites **V4**, and `tools/Invoke-CodexDispatch.ps1` plus `tools/tests/Test-GetPhysicalPath.ps1` cite **V31**.
- `emerging-standards.md` — Living registry of mandatory implementation standards discovered during development sessions, enforced during plan/execution critical review.
- `commands.md` — Operational reference: quick validation/dev/scaffold commands, skills index, MCP servers, and RTK usage.
- `output-evidence-policy.md` — SSOT for command-output routing: the always-applicable receipt pattern + exact-evidence bypass list, plus the RTK `native`/`proxy`/`explicit bypass` classification that applies only when RTK is installed. Required companion to `AGENTS.md §PRIORITY 0`.
- `issue-lifecycle-guide.md` — How issues are reported, tracked, triaged, planned, and resolved end-to-end, with human/AI handoff points.
- `triage-meu-loop.md` — Compact portable contract for the report → triage → MEU register → session-group → plan → reflect learning loop.
- `prompt-templates.md` — Copy-paste prompt templates for driving an agentic build session through an AI coding assistant.
- `natural-writing-guide.md` — Project-wide mandatory style guide for AI-generated prose to avoid "corporate mid" writing patterns.
- `claude-cli-fallback-lessons.md` — CLI-mechanics lessons from a historical same-vendor fallback. **The practice itself is now PROHIBITED** (see the file's banner and `model-routing.md` §Independent-reviewer chain); retained for the flag/exit-code details the wrapper encapsulates.
- `macos-setup.md` — macOS/Linux companion for P0 shell redirect, Codex CLI install, and cross-platform dispatch. Verified on arm64 macOS 26.6 (Tahoe 25G72); `Invoke-CodexDispatch.sh` is canonical there and unreproduced blockers are marked CONTINGENCY.
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
- `cli-dispatch/tests/Test-CliDispatch.ps1` — Validation test suite exercising all CLI-dispatch routes (Codex validation, Codex image gen, data-processing agent, Claude creative writing). `-Test wrapper-contract` is the deterministic half: 31 arms against `Invoke-CodexDispatch.ps1` with no live Codex, including the review-loop gate, the dispatch-kind/timeout-floor arms, and four `-OutputSchema` arms that check three *separable* facts rather than restating `adapt_output_schema.py`'s own suite: that **no local copy of the adaptation has reappeared** in either wrapper (the drift that caused the defect), that the shared tool's selftest passes with a plausible arm count (a suite that ran zero arms also exits 0), and — through the real entry point with a fake `codex` that records its argv (V2) — that the file the CLI is actually **handed** is the adapted one and that the nulls are stripped back out of what it returns. Only that last pair can see a wrapper silently falling back to the unadapted schema, which is exactly what the deleted `catch { $apiSchemaPath = $canonicalSchema }` did on any error. It instantiates the tokenized wrapper into a temp tree and exercises *that*, because parsing the packaged file always fails on its `{{...}}` tokens and the old code returned on that failure — a test that cannot run is not a test (V4).
- `cli-dispatch/tests/Test-OpenCodePoC.ps1` — Proof-of-concept test suite validating OpenCode CLI as a dispatch target via Amazon Bedrock.
- `completion-preflight/SKILL.md` — Mandatory pre-flight checklist before any stop/summary/"complete" report, enforcing a deterministic re-read of `task.md` to prevent premature stop.
- `pre-handoff-review/SKILL.md` — Self-review checklist codifying 10 recurring failure patterns from prior critical reviews, run before declaring a MEU "ready for review."
- `terminal-preflight/SKILL.md` — Mandatory pre-flight checklist for terminal commands enforcing the redirect-to-file pattern to prevent shell buffer-saturation hangs.
- `quality-gate/SKILL.md` — Validation pipeline (type checks, lint, tests, anti-placeholder scan, evidence checks) supporting both phase-level and MEU-scoped runs.
- `git-workflow/SKILL.md` — Agent-safe git commit/push operations with SSH signing, avoiding interactive prompt hangs.
- `git-workflow/scripts/agent-commit.ps1` — Script wrapper for the git commit workflow: validates signing config, runs lint+tests, stages, commits, and pushes safely.
- `git-workflow/scripts/agent-commit.sh` — POSIX/macOS companion to the above, same contract and same two modes (legacy + exact-scope signed). Targets bash 3.2, the version Apple ships. Differs in two documented ways: it skips a lint/test gate whose tooling is absent (printing `SKIPPED`, never `passed`) and it exports `GIT_TERMINAL_PROMPT=0` so an HTTPS push fails instead of hanging. See the skill's Portability section.
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
- `known-issues-archive.md` — *Legacy* archive stub. Pre-SSOT resolved-issue history; retained read-only. Resolved issues now stay in `known-issues.yaml` and are rendered into `known-issues.md` by `tools/issue_triage.py render`.
- `meu-status.yaml` — Minimal valid MEU SSOT (one starter phase, zero MEUs).
- `meu-registry.md` — AUTOGEN `:registry` markers for `meu_status.py render`.
- `triage-output.EXAMPLE.yaml` — Shape of the ephemeral triage → grouping handoff.
- `grouping/README.md` — Where `/session-grouping` writes proposals.

## 5d. `core/tools/` — preflight + issue/MEU CLIs + Codex dispatch

**Issue → MEU learning loop (named capability):** the combination of `issue_triage*`, `meu_status*`, context seeds, `triage-meu-loop.md`, and the `/issue-triage` → `/session-grouping` → `/create-plan` workflows is the framework's **learning-from-mistakes engine** — defects become registered issues, bucket into MEUs, feed session grouping, and surface as design rules in reflections. See `ADOPTION-GUIDE.md` Step 4b.

- `tools/preflight.sh` — **Run this first, in any session that will dispatch or build.** Eight environment prerequisites as a command instead of as always-loaded caveats: `receipts` (`RECEIPTS_DIR` set, absolute, outside the repo, writable), `rg` (a *binary* on PATH — `type -t` catches the shell-function case, where a non-interactive subshell gets `rc=127` and every "no output means clean" sweep reads it as clean — and then **proven able to match a fixture**, V5), `python` (3.9+ with `pyyaml` + `jsonschema`), `registry` (the S2 order `AGENT_MODEL_REGISTRY` → `AGENT_MODEL_REGISTRY_HOME` → `$USERPROFILE|$HOME/.agent`, reporting *which* rung won and requiring the registry file, not just the directory), `git`, `codex` (present and ≥ 0.145.0, the same floor the wrapper enforces), `pwsh` (a **warning** on macOS/Linux where the `.sh` wrapper is canonical; a failure on Windows), and `sync` (a cloud-sync working copy is a second writer — A4c). `--phase build` skips the two dispatch checks and says so by name; `--only <name>` runs one. Exit `0`/`1`/`2`/`3` with the usual first-line marker; **`3` means the check itself could not run** (no `mktemp`), and a run where no check dispatched at all is `3`, never OK (V4). bash 3.2-safe on purpose: it is the one script an adopter runs *before* finding out their `/bin/bash` is old. Arms: `--selftest` (27 arms, 8 must-pass), each re-invoking the real entry point in a subprocess with a mutated environment (V2) and asserting *which* clause spoke — eight checks all exit 1, so an exit-code-only arm passes when the wrong rule fired.
- `tools/issue_triage.py` + `tools/issue_triage/` — Known-issues SSOT CLI (add/list/verify/render/bucket/triage/discover/promote/dismiss).
- `tools/meu_status.py` + `tools/meu_status/` — MEU SSOT CLI (list/next/get/stats/update/render) + `meu-status.schema.json`.
- `tools/Invoke-CodexDispatch.ps1` — Cross-platform PowerShell wrapper for Codex CLI independent-review dispatch (timeout, process-tree cleanup, receipt capture); documented in `cli-dispatch/SKILL.md`.
- `tools/Invoke-CodexDispatch.sh` — POSIX/bash companion with the same dispatch contract for macOS/Linux when `pwsh` is unavailable; see `macos-setup.md`.

> **⚠ Both wrappers now require exactly one of `-LoopId <id>` / `-NonReviewDispatch`** (`--LoopId` / `--NonReviewDispatch` in the `.sh`). Omitting both is exit 1 (`loop_id_required`) — **this breaks existing callers on purpose**, because a defaulted flag would make "the caller forgot" indistinguishable from "this is not a review". With `-LoopId`, `review_ledger.py evaluate` runs before model resolution or CLI launch; a refusal is **exit 9**, kept distinct from a dispatch failure (3) and bad arguments (1). `-GateOnly` checks the gate without dispatching. The choice lands in `status.json` as `loop_id` + `ledger_gate` (`permitted` / `bypassed-non-review`), so a bypass leaves a trace. Full contract and exit-code table: `cli-dispatch/SKILL.md` §The review-loop bound.

> **Dispatch kind and the timeout floor.** Both wrappers take the dispatch kind from the mode the ledger recorded at `begin` — read out of `evaluate`'s `mode=` field, not from a flag the caller retypes each round — and `execution` / `multi-handoff` carry a **2700s floor** over the `ReasoningEffort` default. The tier says how hard the model thinks; it says nothing about how much it has to read, and a `medium` execution review otherwise inherits 900s, dies mid-verdict, and still spends the round. `-Kind <kind>` / `--Kind <kind>` is an optional *assertion* over the same five names `review_ledger.py` accepts (`plan|execution|discovery|handoff|multi-handoff`): disagreeing with the loop is exit 1 (`kind_mismatch` — usually the dispatch is aimed at the wrong loop, and that loop's budget is what gets spent), and pairing it with `-NonReviewDispatch` is exit 1 (`kind_not_applicable`). An `evaluate` line with no `mode=` is exit **3** (`ledger_mode_unavailable`), not a guessed kind: the wrapper and the ledger ship as one pair. `status.json` records `dispatch_kind` + `timeout_floor_applied`.
- `tools/review_ledger.py` — Persistent state for a **bounded** independent-review loop (`begin`/`record`/`evaluate`/`grant`/`relieve`/`state`/`selftest`). Enforces four stops that prose cannot: round budget (plan 3 / execution 6 / discovery 2 / handoff 3 / multi-handoff 3 — the same five names the dispatch wrappers accept for `-Kind`), the mechanism-class stop (three blocking `control-defeat` findings sharing one `mechanism` slug — V30/V41), a separate tight cap on `review-scaffolding` findings (V43), and instrument drift (the verdict schema changing mid-loop). Also refuses a verdict whose `agent` equals the loop's `producer`. First stdout line is always `OK:`/`REFUSE:`/`FAIL-CLOSED:`/`USAGE:`; exit `0`/`1`/`3`/`2` respectively — **`3` is separate from `1` on purpose**, because "could not check" is not "checked and said no" (V5/V31). Requires `RECEIPTS_DIR` in the environment; there is deliberately **no default path**, so an unset variable fails closed instead of writing a ledger where the next invocation will not look. `evaluate`'s OK line carries `mode=<review_mode>` as part of its contract — the dispatch wrappers read the dispatch kind from it, an arm asserts the substring, and a wrapper paired with a ledger that omits it exits 3 rather than guessing. Arms: `selftest` (55 arms, 25 must-OK).
- `tools/tests/test_review_verdict_schema_v2.py` — 21 proof-of-failure arms for the v2 verdict schema (7 must-accept, 14 must-reject, including a v1 document being refused). Exit 3 if `jsonschema` is absent.
- `tools/validate_closeout_artifacts.py` — The closeout gate the H1/H2 rows in `TASK-TEMPLATE.md` call. Five modes, selected by argument shape: handoff structure + `plan_source` binding + AC coverage (`--handoff H --plan P`, or `--ac-coverage-only` / `--handoff-structure-only` alone), review-state receipt write (`--review F --review-state-only --output J`), approval read-back (`--review F --review-state-receipt J --approved-state-only`), and reflection completeness against the real template + `reflection.v1.yaml` (`--reflection F --reflection-template T --reflection-schema S`). **Approval is decided from the receipt on disk, and the receipt's digest is checked against the review file first (SIGN-10b)** — without the digest, editing the review to say `approved` after the receipt was written would pass, and "read from a receipt" would be a laundering step rather than a control. Round count comes from the `## Recheck` headings in the **one rolling review file**; an open finding blocks approval unless its Blocking cell explicitly says `no` (v2's blocking/severity split — an unfilled cell refuses). Exit `0`/`1`/`3`/`2` = OK / refused / could-not-check / usage, first stdout line `OK:`/`REFUSE:`/`FAIL-CLOSED:`/`USAGE:`. Arms: `--selftest` (59 arms, 19 must-OK).
- `tools/lint_task_contract.py` — Structural gate for a plan's Task Table, run by H2-4 and worth running the moment a plan is written. Locates columns by **header label**, so both the 10-column contract and the legacy 9-column form (no `builder_model`) are checked. Refuses: a Validation cell that is not a backticked command, unbalanced backticks/braces/parens, an unresolved `{single-brace}` authoring placeholder (distinct from a `{{DOUBLE_BRACE}}` instantiation token — conflating them makes every correct template row look broken), a bare `exit 0`, a swallowed exit code (`exit $code` with no `$code=` assignment, or no re-raise at all), a receipt path missing under `{{RECEIPTS_DIR}}`, a `context_strategy` outside `shared|compact_continue|isolated`, a non-`shared` row with no durable output, a `[B]` row with no linked follow-up, a `builder_model` that is a slug or `auto` rather than a capability class, duplicate row ids, and dependencies that are dangling or cyclic. **Rows it could not fully check are counted and named in the `OK:` line, and a table where *every* row was exempt is refused** — zero rows checked is a linter with nothing to lint, indistinguishable from a clean table unless it says so (V5). `--template-mode` allows the placeholder commands a template legitimately carries. Arms: `--selftest` (49 arms, 14 must-OK).
- `tools/adapt_output_schema.py` — The **one** implementation of the structured-output schema adaptation, called by both dispatch wrappers (`adapt` / `strip-nulls` / `selftest`). Two transforms, both forced by the endpoint rather than chosen: remove the composition/conditional keywords it rejects (`allOf`/`oneOf`/`not`/`if`/`then`/`else`) at **every** depth, and satisfy strict mode's "`required` names every property" rule by widening each optional property to accept `null` — then `strip-nulls` removes the `"key": null` the model consequently emits, keeping a pre-strip copy, so the result still validates against the *unmodified* shipped schema. `anyOf` is deliberately **kept**: the endpoint accepts it, and removing it would *widen* what the model may emit. Keys in name position (`properties`, `patternProperties`, `definitions`, `$defs`) are never treated as keywords, so a schema with a property literally named `if` survives. Exits `0`/`2`/`3` — there is deliberately **no exit 1**, because this tool decides nothing about a verdict. It exists because the logic was previously duplicated: three PowerShell functions in the `.ps1` that recursed and widened, against four lines of inline Python in the `.sh` that popped `allOf` from the document **root** and nothing else, so every schema-constrained review on macOS/Linux died on a `400` naming a keyword nested under `properties.findings.items` — invisible on the machine where the other copy was correct. Arms: `selftest` (24 arms, 2 must-OK + 4 must-survive), including the strip run over the **real** shipped v2 verdict schema, an arm that first proves that schema actually contains nested conditionals (V5), and arms that count remaining keywords with a **second, independent** traversal rather than the function under test.
- `tools/validate_json_schema.py` — Minimal `jsonschema` front end (`<document.json> <schema.json>`) used for the dispatch wrappers' post-validation. Exit `0` valid / `1` invalid / `2` usage / `3` could not check (no `jsonschema`, unreadable file). The `3` matters: an **absent** validator used to leave the wrapper with an empty `if` and no `else`, so "never checked" and "checked and passed" produced the same result and a verdict could be recorded having never been validated. Arms: `--selftest` (9 arms, 1 must-OK — a validator that refused everything would fail).
- `tools/__init__.py` — Package marker so `python tools/<cli>.py` imports resolve.

> **Adopter edits required:** `tools/issue_triage/model.py` → `VALID_COMPONENTS` (Block D8).
> Python deps: `pyyaml`, `jsonschema`. macOS/Linux adopters: read `macos-setup.md` before first dispatch.
> `bash tools/preflight.sh` proves both deps and the rest of the environment; prefer it to
> reading this paragraph and assuming, since the failure it prevents surfaces three steps
> later as an empty dispatch or a ledger written where nothing will look for it.
>
> **Before trusting the review loop, run its own gates and read the two numbers:**
> `python tools/review_ledger.py selftest` (55 arms — 25 of them must-OK, so a tool that
> refused everything would fail) and `python tools/tests/test_review_verdict_schema_v2.py`
> (21 arms, 7 accepted / 14 rejected). Both print the accepted/refused split rather than
> just a pass count, because a gate that fails everything satisfies every negative arm (V3).
>
> Same for the closeout gates: `python tools/validate_closeout_artifacts.py --selftest`
> (59 arms, 19 must-OK) and `python tools/lint_task_contract.py --selftest` (49 arms,
> 14 must-OK). Run the linter against your own plan too —
> `python tools/lint_task_contract.py --task docs/execution/plans/<slug>/task.md` — and
> **read the exempt counts in the `OK:` line**, not just the word OK: they are the rows
> the command checks did not reach.

## 6. `core/.agent/schemas/`

- `reflection.v1.yaml` — Schema defining the YAML instruction-coverage block agents must emit at session end (field semantics, token budget).
- `review-verdict.schema.json` — **v1.** JSON Schema for structured independent-review verdict files (`approved` / `changes_required` + findings metadata); consumed by plan/execution critical-review workflows. Retained for loops already open against it.
- `review-verdict.schema.v2.json` — **v2, use this for new loops.** Adds the five fields a bounded loop needs in order to stop for the right reason: `loop_id` + `round` (the ledger keys its persisted counts on these — V41), `blocking` split off from `severity`, `subject` (`deliverable` / `committable-tooling` / `review-scaffolding` — V43), and `finding_kind` + `mechanism` (required together for `control-defeat`, so recurrence is counted by mechanism rather than by tally — V25/V30). Checklist rows gain `command` (required for pass/fail/partial: a row asserting an outcome with no command behind it is prose — V4) and `exit_code`. **Behaviour change from v1:** an approval may now carry non-blocking findings, and `changes_required` must name at least one blocking one. `schema_version` is a `const`, so a v1 document does not validate and `review_ledger.py` refuses it rather than coercing it. Arms: `tools/tests/test_review_verdict_schema_v2.py`.
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
- `scripts/instantiate.py` — **The adopter's tool.** Fills every `{{PLACEHOLDER}}` with your project's values from `--config`/flags. Supports `--root` (target your copied tree), `--dry-run`, `--verify`, and `--selftest`. `--verify` proves no token *remains*; it cannot prove a token was replaced with something **legal where it lands**. `{{PROJECT_NAME_UPPER}}` is substituted into identifiers such as `$env:{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR`, so a hyphenated slug once produced `$env:MY-PROJECT_AUTHOR_VENDOR` — PowerShell reads the hyphen as subtraction and the dispatch wrapper stopped parsing entirely, while `--verify` reported OK. The derivation now sanitizes to `[A-Za-z_][A-Za-z0-9_]*` and **refuses** (rather than silently repairs) an explicit `--project-name-upper` that is not a legal identifier. Arms: `--selftest` (22 arms, 12 must-pass + 10 must-refuse), including an end-to-end substitution into a real wrapper fragment, a quote-balance assertion on the *rendered* PowerShell line, and two arms that drive the **CLI** so a bad value has to be refused by the entry point with a non-zero status rather than only by the helper.
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
- `.agent/skills/rtk-optimize/` — **Decided against, not overlooked.** Folded into `.agent/docs/output-evidence-policy.md` instead. Its routing rules, command matrix, `rtk proxy`-for-exact-evidence rule, no-global-hook stance, and `pwsh`-vs-`powershell.exe` note are all in that file already — and that file opens by declaring itself the *single* authority for output routing, so a skill restating the same rules would create the second authority it exists to prevent. The one part with no twin there, the `.rtk/filters.toml` **trust boundary** (review → `trust` → `verify --require-all` → use; failure blocks use and rolls back), is now §RTK classification → *Project-local filters are a trust boundary*; it belongs beside the classification rules because it is what makes them trustworthy — an unreviewed filter decides what a receipt says. Re-port the skill only if you want RTK guidance progressively disclosed rather than linked from `AGENTS.md`, and if you do, delete the duplicated sections rather than letting two files answer one question.

> **Formerly excluded, now packaged (portable):** `output-evidence-policy.md`. It is the
> companion to `AGENTS.md §PRIORITY 0` and the SSOT for the exact-evidence bypass list,
> which is tool-independent. The shipped copy separates **receipt discipline** (always
> applies) from **RTK classification** (applies only if RTK is installed), so a no-RTK
> adopter still has an executable P0. Source-repo receipt paths are `{{RECEIPTS_DIR}}`.
> The shipped copy also carries a section with no source-skill twin — §RTK classification →
> *Project-local filters are a trust boundary* — because `.rtk/filters.toml` is arbitrary
> code that decides what a receipt says, and the package treats that as part of the
> evidence chain rather than a formatting preference.

**Subagent tooling (source-repo only — do not port as-is):**
- `scripts/verify_subagent_delegation.py` + `tests/tooling/test_verify_subagent_delegation.py` — structural gates used to activate delegation in the originating repo. Portable adopters use the skill + a live smoke receipt instead; re-port only if you want the same machine-check suite.
- Source `verification-log.md` probe receipts — replaced in this package by the portable stub.
- `tools/Invoke-CursorAgentDispatch.ps1` — Cursor Agent CLI orchestrated-dispatch wrapper used in the originating repo. **Deliberately not shipped.** Packaged `cli-dispatch` skill/workflow already scrub Cursor Agent dispatch; independent review stays on the Codex chain. Re-port only if the adopter runs Cursor Agent CLI as an isolated worker and accepts maintaining a second wrapper.

**Planned / source-repo-only automation named by packaged docs (referenced, not shipped):**
- `.agent/skills/session-digest`, `.agent/skills/execution-tldr`, `.agent/skills/advisor-consult` — the session-digest / TL;DR / advisor-consult automation named in `development-lifecycle.md` §Phase 9 and §Governance Files. **Planned** in the originating repo, not built; the lifecycle doc's own NOTE says so. Adopters run those steps manually until they build them.
- `.agent/schemas/decision_log.schema.json`, `.agent/schemas/validation_review.schema.json`, `.agent/docs/decision-authority.md` — same planned-automation set. The schemas that *are* shipped and enforced are `reflection.v1.yaml`, `review-verdict.schema.json` (v1), and `review-verdict.schema.v2.json` (v2, enforced by `tools/review_ledger.py record`).
- `tools/render_review_verdict.py` — renders a verdict `final.json` into the rolling review markdown. Named by `delegated-plan-creation.md` §5a/§5c, which now states the manual fallback inline. A **presentation** convenience only: `review_ledger.py record` reads `final.json` directly and the round cap is enforced at dispatch time, so nothing decides anything from the rendering. The rolling review file itself is still required — write it from `REVIEW-TEMPLATE.md` by hand.
- `tools/aggregate_reflections.py` — rolls the reflection corpus into a dated `.agent/reports/coverage_*.md`. Named by `session-meta-review.md` §Step 6 (the ≥5-reflection cadence gate), which now says to skip that step with a recorded basis until it exists. Not shipped because the section-id vocabulary it aggregates is the adopter's own; a stub would emit real-looking numbers about nothing. Steps 1–5 of the meta-review are unaffected.
- `tools/append_action_log.py` — appends one disposition row to `.agent/reports/action-log.md`. Named by `session-meta-review.md` §Step 6, which now gives the exact table header and column order. Its absence costs a line of typing, not a control: the **row** is the requirement, and a cadence run is still incomplete without one per surfaced recommendation.
- `tools/skill_optimize/` (incl. `gate.py`) — the deterministic harvest/propose/gate/buffer/stage toolkit behind `/skill-optimize`. The packaged `skill-optimizer/SKILL.md` + `rubric-templates.md` document the contract (edit format, judge rubric, LEARNED-region and human-adoption-is-terminal rules) because those are the transferable part; the toolkit itself is repo-shaped. **`/skill-optimize` is doc-only for adopters** until they implement it.

> These are the reference-integrity gate's raison d'être: a packaged doc naming a path
> that does not ship is only acceptable if the absence is *written down here*. Run
> `tools/_fw_refcheck.py --all` (source repo) to prove no undocumented dangling reference
> exists — that check is what would have caught the 2026-07-22 `Invoke-CodexDispatch.ps1` gap.
>
> **A dangling *reference* and a dangling *command* are different defects.** The reference
> gate only sees a path where a reference can start — so a tool path buried inside
> `rtk proxy uv run python tools/<name>.py --check` was invisible to it, and five absent tools
> shipped that way while the gate reported 0 unresolved. The tool gate (exit `8`) scans
> whole lines for `tools/<name>` command paths and requires each one to be shipped or
> classified; an unknown name fails, so the default answer for a tool nobody wrote down is
> "defect", not "probably fine". Both gates run inside `sanitize.py --verify`.

**Issue/MEU runtime state (source-repo only):**
- Populated `.agent/context/known-issues.yaml`, `meu-status.yaml`, `triage-output.yaml`, archives, grouping proposals — product history. Package ships **empty seeds** only.
- `tests/tools/test_issue_triage*.py` / `test_meu_status*.py` — optional; re-port if you want the same golden fixtures.
