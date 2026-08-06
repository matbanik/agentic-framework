---
name: Pre-Handoff Review
description: Self-review protocol addressing 10 recurring patterns from critical review analysis. Reduces average review passes from 4-11 to 3-5.
---

# Pre-Handoff Review Skill

A mandatory self-review checklist that codifies the 10 most common patterns found across 7 critical review handoffs (37+ review passes total). Run this protocol before declaring any MEU "ready for review."

## When to Use

- Before writing "implementation complete" in any handoff
- Before changing handoff status to `ready_for_review`
- After applying corrections from a `/plan-corrections` or `/execution-corrections` pass
- Before proposing commit messages

## Risk Tier (select before starting)

Determine the MEU's risk tier first. This controls which steps are required:

| Tier | MEU Type | Required Steps | Est. Time |
|------|----------|---------------|-----------|
| **Tier 1** | Entity/DTO/value object | Steps 1, 6, 7 only | ~10 min |
| **Tier 2** | Service/infrastructure/config | Steps 1, 5, 6, 7 | ~20 min |
| **Tier 3** | Route/API/MCP handler | All steps | ~35 min |

> If unsure, default to the higher tier.

## Protocol

### Step 0: Pre-Review Mechanical Self-Check (catch reviewer-bound findings first) — ALL TIERS

Run BEFORE dispatching to the external reviewer. The 2-week audit (2026-06-13) showed most paid review rounds churned on mechanical findings; catch them here instead of spending a paid reviewer round. This is a Sonnet 5 mechanical-class task (see `.agent/docs/model-delegation.md`).

1. **Single-source-of-truth counts** — any count restated across docs (element counts, test counts, tag counts) must trace to one authoritative source. `rg` the count across all docs and reconcile drift.
2. **Runnable-validation lint** — every validation command in `task.md`/handoff uses the `*> {{RECEIPTS_DIR}}/...; Get-Content` redirect pattern and a repo-root cwd; no markdown-escaped pipes (`\|`) inside command cells; no prose-only "verify X" placeholders.
3. **Claim-to-state grep** — for each AC marked done, `rg` the actual `file:line` for the behavior; if the handoff says "complete" while residual gaps exist, fix the wording before review.
4. **Boundary `Field(ge=0)` / strict-literal check** — for any external-input boundary, confirm explicit schema constraints (`Field(ge=0)`, enum/`Literal`, `extra="forbid"` / `.strict()`) AND a negative test exist.

### Step 1: Contract Verification (Patterns 1, 5) — ALL TIERS

For each AC in the handoff, verify it against actual code with **both** a test reference AND an implementation reference:

```powershell
# For each AC-N, map to:
# (a) A test name that asserts the behavior
rg -n "def test_<behavior>" tests/

# (b) An implementation file:line reference
rg -n "<specific-behavior-from-AC>" <target-file>
```

**Rule**: Grep-only evidence is insufficient. Each AC must map to a test assertion covering the behavior AND an implementation reference. If both "implementation complete" AND "known gaps" appear in the handoff, it is internally inconsistent — fix before submitting.

### Step 2: Test Coverage Audit (Patterns 4, 8) — TIER 3 ONLY

Verify tests actually exercise the claimed behaviors:

```powershell
# Check if any integration tests exist (not just unit tests with mocks)
rg -n "TestClient|create_app|raise_server_exceptions" tests/

# Verify stubs are behavioral, not structural
# Prohibited: __getattr__ that silently returns values
# Permitted: __getattr__ that raises AttributeError/NotImplementedError
rg -n "__getattr__" <stub-files>

# Check that error mapping tests exist
rg -n "NotFoundError|BusinessRuleError|ValueError" tests/
rg -n "404|409|422" tests/
```

**Live Probe Minimum** (canonical source: `meu-handoff.md` §Live Runtime Probe Requirements):
- [ ] Create → Get → List consistency test exists
- [ ] Duplicate rejection test exists
- [ ] Missing-entity error mapping test on all write paths
- [ ] Filter/pagination test with multiple entities
- [ ] No `__getattr__` returning values silently (explicit-error form permitted)

### Step 3: Fix Generalization (Pattern 6) — TIER 3

When fixing any issue, classify and bound the search:

```powershell
# 1. Categorize the fix
# 2. Search scope: same package + explicitly listed siblings in meu-registry
# 3. Maximum search depth: 2 hops from original file's package
# 4. Cross-package instances → log as follow-up, do NOT auto-fix

# Example: if you fixed error mapping in trades.py, check all route files in same package
rg -n "except (NotFoundError|BusinessRuleError|ValueError)" <same-package-route-files>

# Example: adapter exception sweep — if you fixed 401→BrokerCredentialError in one adapter,
# verify all adapters follow the canonical mapping (see exceptions.py docstrings):
rg -n "BrokerSyncError|BrokerCredentialError|401|403|5\d\d" packages/infrastructure/src/{{PROJECT_NAME}}_infra/adapters/
```

**Divergence declaration**: Before fixing a "similar location," classify it:
- **Same contract** → must fix
- **Spec-divergent contract** → allowed to differ (cite spec/ADR)
- **Unknown** → stop and route to planning, do not generalize

**Document in handoff**: "Checked N locations in {scope}. Fixed M instances. Skipped K (spec-divergent: {cite}). Verified 0 remaining unaddressed instances."

### Step 4: Cross-Reference Integrity (Pattern 7) — TIER 2+

If you changed an architectural pattern:

```powershell
# Search for old pattern across ALL canonical docs
rg -n -i "<old-pattern>" docs/build-plan/ docs/execution/ .agent/

# Common examples:
# - Changed token model: rg "HMAC|REST.*token|confirmation_token" docs/
# - Changed DI wiring: rg "NotImplementedError|stub|fake" packages/
# - Changed middleware order: rg "withMetrics.*withGuard|withGuard.*withMetrics" mcp-server/
```

**Rule**: All references must agree. Any stale reference is a MEDIUM finding during review.

### Step 5: Project Closeout (Patterns 2, 10) — TIER 2+

Verify project artifacts are complete AND correctly ordered:

- [ ] `task.md` items match actual completion state (no premature `[x]`)
- [ ] `BUILD_PLAN.md` SSOT drift check passes (`uv run python tools/meu_status.py render --check`)
- [ ] MEU status SSOT entries match handoff statuses (`uv run python tools/meu_status.py get MEU-{N}`)
- [ ] Reflection/metrics artifacts are NOT created until AFTER Codex validation
- [ ] All handoff paths listed in `implementation-plan.md` actually exist

```powershell
# Verify BUILD_PLAN.md consistency
rg -n "✅|🟡|📋" docs/BUILD_PLAN.md | head -20

# Verify meu-registry matches
# Verify MEU status matches
uv run python tools/meu_status.py get MEU-<N>
```

### Step 6: Error Mapping (Pattern 9) — TIER 3 ONLY

For API/MCP projects, verify exception-to-response mapping:

```powershell
# Check every route handler has exception mapping
rg -n "except" <all-route-files>

# Verify the correct HTTP status codes
rg -n "NotFoundError" <all-route-files>       # Should map to 404
rg -n "BusinessRuleError" <all-route-files>   # Should map to 409
rg -n "ValueError" <all-route-files>          # Should map to 422
```

**Rule**: Every write-adjacent route must map ALL domain exceptions AND at least one test must assert response body shape (not just status code). A missing mapping is a HIGH finding.

### Step 6b: Boundary Validation Audit (Pattern 11) — TIER 3

For MEUs touching external write boundaries:

1. **List every boundary touched** and cite the schema/validator used
2. **Prove rejection**: at least one negative test per invalid-input class (blank string, invalid enum, non-positive numeric, extra field)
3. **Create/update parity**: confirm no partial update path bypasses create-time invariants

```powershell
# Check for raw dict parameters in route handlers
rg -n "dict\[str, Any\]" <touched-route-files>

# Check for unvalidated kwargs reconstruction
rg -n "replace\(.*\*\*" <touched-service-files>
rg -n "\*\*{.*\*\*" <touched-service-files>
```

### Step 7: Evidence Freshness (Pattern 3) — ALL TIERS ⚠️ MUST BE LAST

> This step MUST be executed LAST, after ALL other steps (including fix generalization, cross-doc sweeps, and error mapping changes). Running it earlier creates the staleness it aims to prevent.

Re-run every validation command AFTER all fixes and record fresh output:

```powershell
# Python projects
uv run pytest tests/ --tb=no -q           # Record: "N passed, M skipped"
uv run pyright <touched-packages>          # Record: "0 errors"
uv run ruff check <touched-files>          # Record: "All checks passed!"

# TypeScript projects
npx vitest run                             # Record: "N tests, N passed"
npx tsc --noEmit                           # Record: "clean"
npx eslint src/ --max-warnings 0           # Record: "0 errors, 0 warnings"

# Full regression (for multi-MEU projects)
uv run pytest tests/ -v                    # Record total for handoff
```

**Evidence Command Manifest**: Record the EXACT commands used (verbatim, including all flags and scope), not just results. Reject evidence from cached/partial runs (`--lf`, `-k`, unit-only markers when integration should also run).

**Rule**: The handoff counts MUST match this fresh output. Any discrepancy is a LOW finding minimum during review.

## Checklist Summary

| # | Check | Tier | Pass Criteria |
|---|-------|------|---------------|
| 1 | AC-to-code match | ALL | Every AC maps to test name + implementation file:line |
| 2 | No scope overstatement | ALL | Conclusion consistent with residual risks |
| 3 | Integration tests exist | T3 | ≥1 full-stack test for route MEUs |
| 4 | Stubs behavioral | T3 | No silent-return `__getattr__`; error-raising form OK |
| 5 | Fix generalization | T3 | Divergence declaration table; bounded search scope |
| 6 | Cross-doc consistency | T2+ | 0 stale references in canonical docs |
| 7 | Project artifacts consistent | T2+ | task.md, BUILD_PLAN, registry all agree |
| 8 | Lifecycle ordering | T2+ | Reflection after Codex validation |
| 9 | Error mapping complete | T3 | All exceptions mapped + response body asserted |
| 10 | **Evidence freshness (LAST)** | ALL | Handoff counts = fresh output from final command run |

## Evidence of Effectiveness

This protocol was derived from analysis of:

| Project | Passes Before | Root Patterns |
|---------|--------------|---------------|
| domain-entities-ports | 1 | Lifecycle ordering, validate.ps1, evidence counts |
| commands-events-analytics | 1 | Missing defaults, test masking, float vs Decimal |
| rest-api-foundation | 11 | Stub inadequacy, error mapping, scope overstatement |
| settings-backup-foundation | 10 | KDF contract, SQLAlchemy wiring, missing tests |
| toolset-registry | 9 | Handle discard, confirmation dead code, doc contradiction |
| market-data-foundation | 5 | Port return types, DTO coverage, gate failures |

Average passes without protocol: **6.2**. Target with protocol: **3-5** (Tier 1: 1-2, Tier 2: 2-4, Tier 3: 3-5).
