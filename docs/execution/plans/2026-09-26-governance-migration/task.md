# Governance migration task record

Authorization: proposal approved; user explicitly directed execution on 2026-09-26.

| # | Task | Status | Evidence |
|---|---|---|---|
| M0 | Repair packaging baseline with regression tests | implemented and verified | Read-only verify; refcheck 0 unresolved/dangling/unclassified; pre-existing pin remains a release failure |
| M1 | Add durable evidence and shared blocked-row validation; migrate producers | implemented and verified | Evidence/blocked/consumer tests, 50 task and 59 closeout self-test cases pass |
| M2 | Compact root instructions with rule preservation mapping | implemented and verified | AGENTS 86 lines / 12,538 bytes; GUARDRAILS 41 / 3,647; registry matches; rule-preservation.md |
| M3 | Register staged validation and final-state evidence in profile/workflows | implemented and verified | Partial/stale full records refused; command/manual observations supported; template versions 2.2 |
| M5 | Run adoption, portability and release checks; preserve final evidence | local verification complete; release review pending | Final handoff and release-review.md distinguish passing checks from the pin gate and unmeasured native platforms |

M4 optional hook/scanner and snapshot/lease tooling is outside this approved first slice. No commit or publication is planned.
