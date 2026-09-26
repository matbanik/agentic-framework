---
date: "2026-09-26"
project: "governance-migration"
meus: []
status: "in_progress"
action_required: "VALIDATE_AND_APPROVE"
template_version: "2.2"
verbosity: "detailed"
plan_source: "docs/execution/plans/2026-09-26-governance-migration/implementation-plan.md"
agent: "implementing agent"
reviewer: "external-astra-reviewer; scoped implementation approved, release validation pending"
predecessor: "2026-09-26-source-project-governance-migration-proposal.md"
---

# Handoff: 2026-09-26-governance-migration

## Scope

Implemented the approved selective migration: M0 packaging, M1 durable evidence,
M2 instruction consolidation, M3 staged validation, and M5 local adoption verification.
M4 optional hooks/scanner and advanced snapshot/lease/reuse adapters remain follow-on.
No source-repository edits, commits, pushes or publication. The pre-existing planted pin
and working-context REVIEW-TEMPLATE are preserved. This is an implementation handoff,
not an independently approved release.

## Acceptance Criteria

| AC | Type | Description | Source | Test(s) | Status |
|---|---|---|---|---|---|
| AC-1 | regression | Read-only package verification and installed template resolution | Approved M0 | PackagingTests; refcheck/selftests | done; known pin release failure retained |
| AC-2 | contract | Durable observations and shared blocked-row predicate | Approved M1 | EvidenceTests; task/closeout selftests | done |
| AC-3 | instructions | Compact roots, current registry, rule-preservation mapping | Approved M2 | InstructionTests; skill validation; rule-preservation.md | implemented; independent semantic review pending |
| AC-4 | validation | Distinct static/targeted/fresh full and manual observations | Approved M3 | EvidenceTests; verdict schema positive/negative arms | done |
| AC-5 | adoption | Portable adopter fixtures and wrapper contracts | Approved M5 | AdoptionTests; adoption-contract cases; ledger/schema adapter selftests | local checks pass; native platforms and independent release review pending |

<!-- CACHE BOUNDARY -->

## Evidence

### FAIL_TO_PASS

| Check | Red observation | Green observation |
|---|---|---|
| Packaging verify/path aliases | 3 failures: verify mutated bytes, installed template alias missing, relative link wrong | Packaging regression tests pass |
| Evidence records | Missing implementation produced 16 assertion failures across 8 initial tests | 12 evidence tests pass, including the closeout CLI consumer |
| Root budgets/registry | AGENTS 449 lines >170; GUARDRAILS 133 >90; registry mismatch | AGENTS 86 lines/12,538 bytes; GUARDRAILS 41/3,647; headings match |
| Windows evidence paths | Backslash receipt reference incorrectly accepted | Decoded-string scratch detection rejects it |
| not_run | Null exit incorrectly rejected as executed-command evidence | Null exit + reason accepted; invented zero refused |
| History scoping | Live/prose slug gates treated maintainer history as installed instruction | Root history excluded; core/.agent context remains checked |
| Manual review observation | v2 schema rejected procedure/observer fields | Valid manual form accepted; missing observer/fabricated exit refused |
| Literal scan output | A real command/output mentioning TODO was mistaken for an unfilled field | Whole placeholder values refused; actual scan command and diagnostics accepted |

The broad run also found an existing schema-test fixture missing required intent fields.
The fixture was updated to the existing contract and explicit missing-intent negatives
were added. A reference selftest's synthetic path was corrected for newly classified
core-prefixed names; no assertion was weakened. The handoff integration initially parsed
the leading empty Markdown cell as its row ID; the actual split was corrected.

### Quality Gate Results

- Pytest: 25 passed, 30 subtests passed.
- Reference scan: required-dangling=0, unresolved=0, unclassified=0 (baseline: 3/73/4).
- Selftests: refcheck 16; sanitizer 12; instantiate 32; task 50; closeout 59; ledger 105.
- Schema adapter: 24 arms, zero failures; PowerShell encoding/parse/usage passed.
- Five adoption contract cases and five edited skill validators passed.
- Release sanitizer: exit 4, exactly the pre-existing planted model pin (also reported
  by the prose-name check). It is neither removed nor allowlisted.

### State and measurement limits

The state hash below covers sorted relative paths and bytes in core/ and scripts/,
excluding __pycache__/.pytest_cache, plus ADOPTION-GUIDE, ADOPTION-QUESTIONS,
PROJECT-PROFILE-TEMPLATE and UPDATE-CHECKLIST. The input hash was identical before and
after the final run; generating this maintainer handoff does not change that set.
It is a local verification identity, not a shipped universal environment/snapshot adapter.
These records describe the migration run before the subsequent generic-name cleanup;
their state hash does not identify the current tree after that cleanup.

Both wrapper path-test snippets came directly from the shipped wrappers and ran without
starting a provider CLI. Windows/PowerShell measured repo and receipt prompts, _tmp names,
outside paths, wildcard output, prefix siblings, collisions and a junction escape.
Git Bash measured the POSIX wrapper path checks and nonzero exit propagation. Disposable
adoption tested Windows and POSIX-shaped roots with spaces and custom receipts, preserved
adopter-owned files, imports/budgets, manual full observations and stale-state refusal.
These are not native Linux/macOS, live provider, sandbox-helper, or actual instruction-loader
certification. Egress/no-MEU checks exercise instruction/profile contracts, not a live model's
compliance. No optional hook is claimed as enforced.

### Commands Executed

Each record preserves the actual invocation and decisive output. Reproduce individual
commands from the framework root using the local Python interpreter; live-registry checks
also used session-scoped AGENT_MODEL_REGISTRY_HOME. Scratch captures are not needed to
understand these outcomes. The external skill-validator path is a maintainer capability,
not an adopter dependency.

Tested state: `sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114`.

Environment: 3.14.7 (tags/v3.14.7:823f032, Aug  5 2026, 10:51:32) [MSC v.1944 64 bit (AMD64)]; win32; pytest 9.1.1; jsonschema 4.26.0.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "pytest",
  "command": "C:\\Python314\\python.exe -X utf8 -m pytest scripts/tests core/tools/tests -q",
  "cwd": ".",
  "exit_code": 0,
  "output": "25 passed, 30 subtests passed in 14.60s",
  "scope": "complete framework pytest suites: scripts/tests and core/tools/tests; release checks reported separately",
  "phase": "full",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114",
  "fresh": true,
  "snapshot": false
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "refcheck",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/refcheck.py --all",
  "cwd": ".",
  "exit_code": 0,
  "output": "  REQUIRED-DANGLING:        0\n  UNRESOLVED:               0\n  UNCLASSIFIED:             0",
  "scope": "migration verification: refcheck",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "refcheck-selftest",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/refcheck.py --selftest",
  "cwd": ".",
  "exit_code": 0,
  "output": "BASE 0 pre-existing failure line(s) in the copy, exit 0\nPASS required-undisclosed     exit 1, new REQUIRED-DANGLING reported\nPASS required-disclosed-link  exit 1, new REQUIRED-DANGLING reported\nBASE 0 pre-existing tool failure line(s), exit 0\nRESULT: 16 arm(s) (7 must-pass), 0 failure(s)",
  "scope": "migration verification: refcheck-selftest",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "sanitize-selftest",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/sanitize.py --selftest",
  "cwd": ".",
  "exit_code": 0,
  "output": "RESULT: 12 arm(s), 0 failure(s)",
  "scope": "migration verification: sanitize-selftest",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "instantiate-selftest",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/instantiate.py --selftest",
  "cwd": ".",
  "exit_code": 0,
  "output": "RESULT: 32 arm(s), 0 failure(s) [32 passing this run; a validator that always raises cannot pass]",
  "scope": "migration verification: instantiate-selftest",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "task-selftest",
  "command": "C:\\Python314\\python.exe -X utf8 core/tools/lint_task_contract.py --selftest",
  "cwd": ".",
  "exit_code": 0,
  "output": "RESULT: 50 arm(s), 0 failure(s) [14 must-OK arms, so the linter is not refusing everything]",
  "scope": "migration verification: task-selftest",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "closeout-selftest",
  "command": "C:\\Python314\\python.exe -X utf8 core/tools/validate_closeout_artifacts.py --selftest",
  "cwd": ".",
  "exit_code": 0,
  "output": "RESULT: 59 arm(s), 0 failure(s) [19 must-OK arms, so the tool is not refusing everything]",
  "scope": "migration verification: closeout-selftest",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "ledger-selftest",
  "command": "C:\\Python314\\python.exe -X utf8 core/tools/review_ledger.py selftest",
  "cwd": ".",
  "exit_code": 0,
  "output": "RESULT: 105 arm(s), 0 failure(s) [53 must-OK arms, so the tool is not refusing everything]",
  "scope": "migration verification: ledger-selftest",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "task-template",
  "command": "C:\\Python314\\python.exe -X utf8 core/tools/lint_task_contract.py --task core/templates/TASK-TEMPLATE.md --template-mode",
  "cwd": ".",
  "exit_code": 0,
  "output": "OK: 18 row(s); 10-column table (with builder_model); 12 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 4 row(s) exempt (placeholder-command): 1, 2, H1-2, H1-7; 2 row(s) exempt (view_file): H1-5, H2-1",
  "scope": "migration verification: task-template",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "ps1-encoding",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/tests/test_ps1_encoding.py",
  "cwd": ".",
  "exit_code": 0,
  "output": "OK: 5 core/**/*.ps1 ASCII-or-BOM; wrapper parse-only + usage",
  "scope": "migration verification: ps1-encoding",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "adoption-wp1",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/tests/test_adoption_contract.py --case wp1",
  "cwd": ".",
  "exit_code": 0,
  "output": "OK: wp1 layout, locators, and EGRESS_PRECEDENCE",
  "scope": "migration verification: adoption-wp1",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "adoption-templates-installed",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/tests/test_adoption_contract.py --case templates-installed",
  "cwd": ".",
  "exit_code": 0,
  "output": "OK: TEMPLATE_HOME consumers",
  "scope": "migration verification: adoption-templates-installed",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "adoption-d9-no",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/tests/test_adoption_contract.py --case d9-no",
  "cwd": ".",
  "exit_code": 0,
  "output": "OK: D9_NO_BRANCH present",
  "scope": "migration verification: adoption-d9-no",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "adoption-d6",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/tests/test_adoption_contract.py --case d6",
  "cwd": ".",
  "exit_code": 0,
  "output": "OK: D6_ADOPTER_ARGV and no mcp-audit",
  "scope": "migration verification: adoption-d6",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "adoption-profile-permissions",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/tests/test_adoption_contract.py --case profile-permissions",
  "cwd": ".",
  "exit_code": 0,
  "output": "OK: profile slots and permission behavior",
  "scope": "migration verification: adoption-profile-permissions",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "skill-quality-gate",
  "command": "C:\\Python314\\python.exe -X utf8 C:/Users/Mat/.codex/skills/.system/skill-creator/scripts/quick_validate.py core/.agent/skills/quality-gate",
  "cwd": ".",
  "exit_code": 0,
  "output": "Skill is valid!",
  "scope": "migration verification: skill-quality-gate",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "skill-completion-preflight",
  "command": "C:\\Python314\\python.exe -X utf8 C:/Users/Mat/.codex/skills/.system/skill-creator/scripts/quick_validate.py core/.agent/skills/completion-preflight",
  "cwd": ".",
  "exit_code": 0,
  "output": "Skill is valid!",
  "scope": "migration verification: skill-completion-preflight",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "skill-pre-handoff-review",
  "command": "C:\\Python314\\python.exe -X utf8 C:/Users/Mat/.codex/skills/.system/skill-creator/scripts/quick_validate.py core/.agent/skills/pre-handoff-review",
  "cwd": ".",
  "exit_code": 0,
  "output": "Skill is valid!",
  "scope": "migration verification: skill-pre-handoff-review",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "skill-terminal-preflight",
  "command": "C:\\Python314\\python.exe -X utf8 C:/Users/Mat/.codex/skills/.system/skill-creator/scripts/quick_validate.py core/.agent/skills/terminal-preflight",
  "cwd": ".",
  "exit_code": 0,
  "output": "Skill is valid!",
  "scope": "migration verification: skill-terminal-preflight",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "skill-cli-dispatch",
  "command": "C:\\Python314\\python.exe -X utf8 C:/Users/Mat/.codex/skills/.system/skill-creator/scripts/quick_validate.py core/.agent/skills/cli-dispatch",
  "cwd": ".",
  "exit_code": 0,
  "output": "Skill is valid!",
  "scope": "migration verification: skill-cli-dispatch",
  "phase": "static",
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "release-sanitize",
  "command": "C:\\Python314\\python.exe -X utf8 scripts/sanitize.py --verify",
  "cwd": ".",
  "exit_code": 4,
  "output": "  VERIFY FAILED:   model-slug (tier-1): 1 hit(s):\n      core/AGENTS.md:86 claude-fable-5-1\n  VERIFY FAILED:   prose model name (tier-1): 1 hit(s):\n      core/AGENTS.md:86  claude-fable-5",
  "scope": "migration verification: release-sanitize",
  "phase": "static",
  "result": "fail",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "schema-adapter",
  "command": "python -X utf8 core/tools/adapt_output_schema.py selftest",
  "cwd": ".",
  "scope": "output schema adapter",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:7bdac4666aaadf1b8f330864dfbe940b17a87ef9785044177ba6965562e14114",
  "output": "RESULT: 24 arm(s), 0 failure(s) [2 must-OK + 4 must-survive, so neither a stripper that deletes everything nor one that deletes nothing can pass this suite]"
}
```

## Changed Files

| Area | Result |
|---|---|
| Root instructions / registry | Twelve root sections, compact guardrails/bootstrap, preservation ledger, corrected backlinks |
| Evidence tool / consumers | New evidence.v1 validator and shared blocker predicate in task/handoff gates |
| Templates / profile | Versions 2.2, staged D6 checks, durable F3b promotion, manual observations, complete review-state parse/approval sequence |
| TDD / quality / dispatch skills | One fresh final gate, source-neutral validation, capability-based sandbox choice, durable reviewer payload |
| Packaging / tests | Read-only sanitizer, history scope, template aliases, consumer/adoption regressions, valid intent fixtures |

Tracked files in the final diff:

- `ADOPTION-GUIDE.md`
- `ADOPTION-QUESTIONS.md`
- `PROJECT-PROFILE-TEMPLATE.md`
- `UPDATE-CHECKLIST.md`
- `core/.agent/docs/artifact-naming.md`
- `core/.agent/docs/commands.md`
- `core/.agent/docs/context-compression.md`
- `core/.agent/docs/development-lifecycle.md`
- `core/.agent/docs/emerging-standards.md`
- `core/.agent/docs/harness-profiles.md`
- `core/.agent/docs/macos-setup.md`
- `core/.agent/docs/model-routing.md`
- `core/.agent/docs/output-evidence-policy.md`
- `core/.agent/docs/testing-strategy.md`
- `core/.agent/schemas/reflection.v1.yaml`
- `core/.agent/schemas/registry.yaml`
- `core/.agent/schemas/review-verdict.schema.v2.json`
- `core/.agent/skills/cli-dispatch/SKILL.md`
- `core/.agent/skills/completion-preflight/SKILL.md`
- `core/.agent/skills/deep-research-prompting/SKILL.md`
- `core/.agent/skills/pre-handoff-review/SKILL.md`
- `core/.agent/skills/quality-gate/SKILL.md`
- `core/.agent/skills/terminal-preflight/SKILL.md`
- `core/.agent/workflows/create-plan.md`
- `core/.agent/workflows/execution-corrections.md`
- `core/.agent/workflows/execution-critical-review.md`
- `core/.agent/workflows/execution-session.md`
- `core/.agent/workflows/plan-corrections.md`
- `core/.agent/workflows/plan-critical-review.md`
- `core/.agent/workflows/session-grouping.md`
- `core/.agent/workflows/session-meta-review.md`
- `core/.agent/workflows/skill-optimize.md`
- `core/.agent/workflows/tdd-implementation.md`
- `core/AGENTS.md`
- `core/CLAUDE.md`
- `core/GUARDRAILS.md`
- `core/MANIFEST.md`
- `core/templates/HANDOFF-TEMPLATE.md`
- `core/templates/PLAN-TEMPLATE.md`
- `core/templates/REFLECTION-TEMPLATE.md`
- `core/templates/REVIEW-TEMPLATE.md`
- `core/templates/TASK-TEMPLATE.md`
- `core/tools/Invoke-CodexDispatch.ps1`
- `core/tools/lint_task_contract.py`
- `core/tools/tests/test_review_verdict_schema_v2.py`
- `core/tools/validate_closeout_artifacts.py`
- `scripts/README.md`
- `scripts/refcheck.py`
- `scripts/sanitize.py`

New implementation files: `core/tools/durable_evidence.py`,
`core/tools/tests/test_durable_evidence.py`, `scripts/tests/test_governance_migration.py`.
The maintainer plan/task/rule ledger, this handoff and release checklist are also new.

Key changes:

```diff
- if not dry_run:
+ if not dry_run and not verify:
```

```diff
- Receipt path alone serves as lasting proof.
+ Paste command/procedure, exit/result, tested state and decisive output in evidence.v1.
```

## Codex Validation Report

Implementor verification only. No independent reviewer was dispatched and no approved
verdict is claimed. Before release, follow the local release-review.md checklist; do not
mistake this handoff or passing tests for approval. Native platform and loader proof is
explicitly unmeasured. The preserved model pin blocks the release sanitizer.

## Corrections Applied (2026-09-26)

Reconciled duplicate full-run instructions, obsolete root backlinks/five-stop lists,
Windows FullAccess-by-default prose, and task-template approval checking that previously
omitted the required parsed state receipt. Corrected schema fixture intent fields and
extended manual observations without changing ledger intent/vendor/budget semantics.

## Deferred Items

M4 optional scanner/hooks/rule audits and advanced reuse mechanisms are the proposal's
explicit follow-on scope, not unfinished implementation disguised as blocked. Independent
release review, pin disposition, native Linux/macOS and live loader/provider probes remain
release conditions in `docs/execution/plans/2026-09-26-governance-migration/release-review.md`.

## History

| Event | Date | Agent | Detail |
|---|---|---|---|
| Execution authorized | 2026-09-26 | Human | Proposal approved; proceed with execution |
| Implemented and locally verified | 2026-09-26 | Implementor | M0–M3 and local M5 checks |
| Release review | pending | Independent reviewer | No verdict yet |


## Generic-name cleanup (2026-09-26)

Replaced the source identity with `source-project`, `Source Project`, or
`SOURCE_PROJECT`, renamed both source research documents, and updated their links,
the reference-check exception, schema identifier, and sanitizer fixture. Historical
source paths are now illustrative. Removed stale generated bytecode containing the
old identity. Git history and metadata were outside this working-tree cleanup.

The following implementor checks ran after the code changes. Tested state:
`sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d` (sorted relative paths and bytes, NUL-separated, using the
core/scripts and root-document scope defined above).

| Command | Exit | Decisive result |
|---|---|---|
| `rtk proxy python -X utf8 -m pytest scripts/tests core/tools/tests -q` | 0 | 25 passed, 30 subtests passed |
| `rtk proxy python -X utf8 scripts/refcheck.py --all` | 0 | Required-dangling=0, unresolved=0, unclassified=0 |
| `rtk proxy python -X utf8 scripts/sanitize.py --selftest` | 0 | 12 arms, 0 failures |
| `rtk proxy python -X utf8 scripts/instantiate.py --selftest` | 0 | 32 arms, 0 failures |

Additional local assertions passed for all six generic source forms, leakage
detection and idempotence. A case-insensitive byte/content and filename scan found
zero remaining old-identity matches outside Git metadata. Previous migration
evidence remains historical; independent release review is still pending.


## Scoped implementation review completed (2026-09-26)

The external `gpt-6-astra` reviewer at `high` approved the scoped migration in round 2,
with zero remaining findings. See the [canonical review and correction evidence](2026-09-26-governance-migration-implementation-critical-review.md).
The human's continued same-vendor exception was explicitly recorded; this was a separate
reviewer context, not cross-vendor review. The shared registry remained unchanged and the
exception ended at approval.

Corrections preserve legitimate null values through both dispatch wrappers, retain exact
raw-response backup bytes, distinguish the generic example identity from ordinary prose,
and require command exit codes. Full local verification: **36 tests and 36 subtests passed**;
all reference, packaging, task, closeout, ledger, adapter and PowerShell checks passed.
The actual release sanitizer reports zero raw source slugs and exits 4 only for the
pre-existing protected pin. The fresh input identity is
`sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c`.
Earlier evidence in this handoff remains historical; the correction section in the
canonical review contains fresh command/exit/output/state records.

Round 2's wrapper and child exits were both 0; its approved verdict validated and was
automatically recorded in the existing ledger, without manual recovery. The reviewer
independently confirmed the hash, passed focused checks and adversarial verdict probes,
and changed only the canonical review. No implementation changes followed that review.

This closes the implementation review, not release certification. Protected-pin disposition,
native Linux/macOS and loader validation remain explicit release conditions. No commit,
push, deployment or publication occurred.
