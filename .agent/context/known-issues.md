# Known Issues — {{PROJECT_NAME_TITLE}}

> Auto-generated from `known-issues.yaml` by `tools/issue_triage.py render`.
> Do not edit manually. Run `uv run python tools/issue_triage.py render` to regenerate.

**Total: 13** — Active: 11 | Mitigated: 0 | Resolved: 0

## Active Issues

| Sev | ID | Title | Component | Status | Discovered |
|-----|-----|-------|-----------|--------|------------|
| 🟠 | `SANITIZE-VERIFY-AUTOGEN-DRIFT-UNDETECTED` | sanitize --verify reports no AUTOGEN drift against a registry whose SHA… | infrastructure | ⬜ open | 2026-10-08 |
| 🟡 | `CLI-DISPATCH-KIND-ARMS-LEDGER-BEGIN-ARGS` | wrapper-contract dispatch-kind arms fail because the fixture calls ledg… | infrastructure | ⬜ open | 2026-10-08 |
| 🟡 | `CLI-DISPATCH-NULL-STRIP-ARM-RED` | wrapper-contract null-strip arm finds nulls left in final.json | infrastructure | ⬜ open | 2026-10-08 |
| 🟡 | `SANITIZE-VERIFY-REGISTRY-HOME-UNDOCUMENTED` | sanitize --verify exits 3 unless the registry home variable is set, and… | infrastructure | ⬜ open | 2026-10-08 |
| 🟡 | `PACKAGE-ROOT-CONTEXT-LIVE-MODEL-SLUGS` | Root .agent/context handoffs and evidence notes carry 31 live model slu… | infrastructure | ⬜ open | 2026-10-08 |
| 🟡 | `SOURCE-PROJECT-CROSSREPO-TESTS-DRIFT` | Source-project tests that read this repo fail on five independent drifts | core | ⬜ open | 2026-10-08 |
| 🟢 | `DURABLE-EVIDENCE-SCRATCH-HANDOFF-FIXTURE` | Durable-evidence test fixture lacks a Decision Log, so a different refu… | infrastructure | ⬜ open | 2026-10-08 |
| 🟢 | `UPDATE-CHECKLIST-LEDGER-MOJIBAKE` | UPDATE-CHECKLIST.md divergence-ledger rows contain double-decoded chara… | infrastructure | ⬜ open | 2026-10-08 |
| 🟢 | `CHECKLIST-COUNTS-HAND-MAINTAINED` | UPDATE-CHECKLIST tool count and divergence ledger are maintained by hand | infrastructure | ⬜ open | 2026-10-08 |
| 🟢 | `HYPOTHESIS-DIR-NOT-GITIGNORED` | pytest creates an untracked .hypothesis/ directory at the repo root | infrastructure | ⬜ open | 2026-10-08 |
| 🟢 | `STRAY-GIT-WORKTREES` | Two stray git worktrees are registered against this repo | infrastructure | ⬜ open | 2026-10-08 |

---
*Managed by `tools/issue_triage.py`. See `known-issues.yaml` for full details including root cause, blast radius, and verification metadata.*
