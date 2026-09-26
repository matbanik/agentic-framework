---
date: "2026-09-26"
status: implemented-pending-release-review
authorization: "Direct user instruction: proposal approved, proceed with execution"
---

# Governance migration implementation

Execute the approved [research proposal](../../../../.agent/context/2026-09-26-source-project-governance-migration-proposal.md), packages M0–M3 and M5. M4 hooks/citation scanner and advanced snapshot/lease reuse are explicitly follow-on. This plan records the approved scope; it does not claim independent review approval.

Preserve the pre-existing planted model pin in `core/AGENTS.md` and the untracked working-context review template. Do not modify the source repository, commit, push, deploy, or install hooks.

## Acceptance Criteria

| AC | Type | Criterion | Source | Negative |
|---|---|---|---|---|
| AC-1 | regression | Packaging verification is read-only and installed template links resolve | M0 | Raw source leak still fails verification without mutation |
| AC-2 | contract | Command/exit/output/state evidence survives receipt deletion; task and handoff use one blocked predicate | M1 | Missing output, exit, blocked proof, scratch-only proof fail |
| AC-3 | instructions | Root instructions fit budgets and preserve human, egress, independent review, profile and ledger gates | M2 | Missing section mappings or oversized instantiated roots fail |
| AC-4 | validation | Static, targeted and fresh full stages are distinct; manual validation supported | M3 | Partial, stale or snapshot-only full claims fail |
| AC-5 | adoption | Installer and representative adopter fixtures preserve portability and wrapper contracts | M5 | Nondefault roots, spaces, restricted egress and absent RTK covered; unsupported platform execution identified |

## Validation

Use standard-library unittest for new regression/contract cases; existing tool selftests and packaging gates; disposable adoption fixture checks; inspect shell syntax and run available wrapper tests. Preserve decisive output in the final handoff. A local self-check is not independent release approval. Record unavailable platform or external-review evidence explicitly.

## Rule preservation

Maintain `rule-preservation.md` beside this plan. Root rule consolidation must retain profile-controlled commands, artifact homes, review budgets, authorization provenance and no self-approval. Optional runtime hooks remain uninstalled and are not advertised as enforcement.
