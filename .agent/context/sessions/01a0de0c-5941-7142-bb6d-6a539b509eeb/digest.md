# Session Digest - governance migration

**Date:** 2026-09-26
**Project:** Agentic Delivery Framework - portable governance, evidence and adoption

## Decisions Made

| Decision | Authority | Source |
|---|---|---|
| Execute selective M0-M3 and local M5 migration | Human approved | Proposal approved; proceed with execution |
| Replace source identity in content and filenames with generic examples | Human directed | Naming-cleanup requests |
| Use a separate Astra review context at high reasoning | Human directed | CLI dispatch request |
| Permit same-vendor review for this loop until approved | Human granted | Continued exception; ended at round 2 approval |
| Organize changes into logical commits and push to GitHub | Human directed | Current commit/push request |
| Keep planted pin and working-context review-template copy local | Preserve pre-existing user fixtures | Migration plan and approved review |

## Test and Review Outcomes

- Full local suite: 36 tests and 36 subtests passed.
- Reference, sanitizer, instantiation, task, closeout, ledger, adapter and PowerShell checks passed.
- Astra round 2: approved, zero open findings; wrapper exit 0 and automatic ledger recording.
- Fixed null preservation/raw-byte backups, generic-title prose collision, and required command exit codes.
- Shared registry unchanged; no release, deployment or publication authorized by review.

## Commit Groups

1. Packaging checks, generic source identity and historical filename/link cleanup.
2. Durable evidence validation, blocked-row consumers and manual review output pipeline.
3. Compact governance instructions, adoption guidance, templates and staged testing.
4. Migration proposal, execution records, approved review and this digest.

Commit and push authorization is recorded here; final commit IDs and transport outcome are available in Git history and the session response.

## Blockers and Release Limits

- The pre-existing planted model pin stays only in the local working tree, outside the commit set.
- The pre-existing local review-template copy stays untracked.
- Native Linux/macOS and instruction-loader certification remain unmeasured release conditions.
- Optional M4 hooks/scanners and snapshot/lease tooling remain deferred.

## Files and Evidence

Changes span scripts/ packaging, core/tools/ validators and wrappers, core/ instruction/templates, root adoption guides, and migration history.
See [implementation handoff](../../handoffs/2026-09-26-governance-migration-handoff.md) and [approved review](../../handoffs/2026-09-26-governance-migration-implementation-critical-review.md).

## Provenance

- Conversation ID: `01a0de0c-5941-7142-bb6d-6a539b509eeb`
- Transcript: `C:/Users/Mat/.codex/sessions/2026/09/26/rollout-2026-09-26T10-09-06-01a0de0c-5941-7142-bb6d-6a539b509eeb.jsonl`
