---
name: Codebase Quality Gate
description: Validation pipeline for {{PROJECT_NAME_TITLE}} monorepo. Runs type checks, linting, tests, anti-placeholder scans, and evidence checks. Supports phase-level and MEU-scoped runs.
---

# Codebase Quality Gate Skill

## Overview

The quality gate validates code correctness across the {{PROJECT_NAME_TITLE}} monorepo. It runs via Python (cross-platform) and supports two scoping levels.

## Commands

```bash
# Full phase gate — run when ALL MEUs in a phase are complete
uv run python tools/validate_codebase.py

# MEU-scoped gate — run after each individual MEU implementation
uv run python tools/validate_codebase.py --scope meu

# Scoped to specific files
uv run python tools/validate_codebase.py --scope meu --files packages/core/src/{{PROJECT_NAME}}_core/domain/portfolio_balance.py

# Machine-readable output for agent parsing
uv run python tools/validate_codebase.py --json
```

## When to Run

| Trigger | Scope | Command |
|---------|-------|---------|
| After each code change | MEU | `--scope meu` |
| After completing all MEUs in a phase | Phase | (default, no flag) |
| Before `git commit` | Phase | (default) |
| During Codex validation | Phase | `--json` for structured output |

## Check Categories

### Blocking (must pass)

| # | Check | Tool | Fail = |
|---|-------|------|--------|
| 1 | Python type check | `pyright` | Type error in domain/infra/api |
| 2 | Python lint | `ruff` | Style or logic violation |
| 3 | Python unit tests | `pytest -m unit` | Failing test |
| 4 | TypeScript type check | `tsc --noEmit` | Type error in UI/MCP |
| 5 | TypeScript lint | `eslint` | Lint violation |
| 6 | TypeScript unit tests | `vitest` | Failing test |
| 7 | Anti-placeholder scan | `rg TODO\|FIXME\|NotImplementedError` | Unresolved placeholder (lines with `# noqa: placeholder` excluded) |
| 8 | Anti-deferral scan | `rg pass.*placeholder\|raise NotImplementedError` | Deferred implementation |
| 9 | GUI-API seam tests | `pytest tests/integration/test_gui_api_seams.py` | Field mismatch, schema gap, response format bug |
| 10 | OpenAPI spec drift | `uv run python tools/export_openapi.py --check openapi.committed.json` | API route changed without regenerating committed spec |
| 11 | Boundary validation audit | Multi-pattern scan (see below) | Write-adjacent input lacks boundary schema enforcement |

#### Check 11 — Boundary Validation Audit Patterns

Run all four patterns against touched route and service files. Any match requires investigation:

```powershell
# 11a: Raw dict params in route handlers
rg -n "dict\[str, Any\]" <touched-route-files>

# 11b: Unvalidated reconstruction (replace or __dict__ update)
rg -n "replace\(.*\*\*|__dict__.*update" <touched-service-files>

# 11c: Missing extra="forbid" on request models
rg -n "class.*Request.*BaseModel" <touched-route-files>
# Then verify each match has extra="forbid"

# 11d: kwargs bypass from external input
rg -n "\*\*kwargs|\*\*{" <touched-service-files>
```

### Advisory (non-blocking)

| # | Check | Tool | Purpose |
|---|-------|------|---------|
| A1 | Coverage report | `pytest --cov` | Track test coverage |
| A2 | Security scan | `bandit` | Surface risky patterns |
| A3 | Evidence bundle | Handoff field check | Ensure handoff completeness |

## Agent Integration

### Reading Results

When using `--json`, output structure:
```json
{
  "summary": {
    "passed": true,
    "blocking_passed": 8,
    "blocking_failed": 0,
    "advisory_count": 3,
    "skipped_count": 0,
    "total_duration_s": 12.5
  },
  "checks": [
    {"name": "...", "passed": true, "blocking": true, "duration_s": 2.1, "message": ""}
  ]
}
```

### Interpreting Failures

1. **Blocking failure** → Fix before proceeding. Do NOT mark `task.md` items as `[x]`.
2. **Advisory warning** → Note in handoff but do not block progress.
3. **Skipped check** → Phase not yet scaffolded (e.g., no TypeScript dirs). Normal.

### Phase Gate vs MEU Gate

- **MEU gate**: Run after each MEU. Use `--scope meu`. Some later-phase checks may fail — that's expected.
- **Phase gate**: Run only when ALL MEUs in the phase are done. Must pass completely.

### GUI-Phase Gates (Phase 6+)

When working on `ui/` code, the following additional checks apply:

| # | Check | Command | When |
|---|-------|---------|------|
| G1 | Electron build | `cd ui && npm run build` | **Every** source change to `ui/src/main/` or `ui/src/preload/` |
| G2 | E2E smoke (when wave is active) | `cd ui && npm run build && npx playwright test` | After completing a wave gate MEU |

> [!IMPORTANT]
> **Electron build is mandatory.** Playwright E2E tests launch the compiled `out/main/index.js`, not source files.
> Source changes to `ui/src/main/` are invisible to E2E until `npm run build` runs.
> The stale-bundle bug (4 review passes, 2026-03-18) was caused by omitting this step.

### Mock-Contract Validation

When reviewing or writing unit tests that mock API responses, verify TS interfaces match the actual Python API models. See [testing-strategy.md §Mock-Contract Validation Rule](../../docs/build-plan/testing-strategy.md) for details.
