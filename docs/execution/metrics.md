# Execution metrics

Columns: Date, MEU(s), Tool Calls, Time to First Green, Tests Added, Codex Findings, Handoff Score (X/7), Rule Adherence (%), Prompt→Commit (min), Notes.

## Finding Categories

Controlled vocabulary for `review_churn.finding_categories`: claim_to_state_drift, count_reconciliation, weak_test, boundary_validation, stale_reference, fix_generalization_miss, effort_mismatch, source_label_missing, self_review_violation, placeholder_or_deferral, scope_creep, back_compat_break, provenance_error, overthinking, contract_drift, other.

| Date | MEU(s) | Tool Calls | Time to First Green | Tests Added | Codex Findings | Handoff Score | Rule Adherence | Prompt→Commit (min) | Notes |
|------|--------|------------|---------------------|-------------|----------------|---------------|----------------|---------------------|-------|
| 2026-09-19 | MEU-1 create-plan-adopter-path-fix | ~250 | AC oracles green after WP-1 | 0 | 1 blocking then 0 | 6/7 | 90% | n/a (draft only) | Docs-only create-plan.md align; execution review 2 rounds |
| 2026-09-19 | none (portable-adopter-bootstrap) | hundreds | wp1 locators green | adoption-contract + encoding + instantiate arms | R1 R2 then R5 accepted_risk | 7/7 | 90% | n/a (draft only) | Portable adopter bootstrap; exec review 4 rounds (r4 frontmatter) |
