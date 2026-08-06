---
description: Handoff protocol between Opus (implementation) and Codex (validation) agents for MEU-scoped work.
---

# MEU Handoff Protocol

This document defines the handoff artifact format for passing work between agents. A handoff artifact must be **self-contained** — the receiving agent has no access to the sending agent's reasoning, context, or conversation history.

> **Target size**: 2,000–5,000 tokens per handoff. Reference files by path. Never inline full source code.
>
> **Multi-MEU sessions**: A project session produces one uniquely named handoff per
> MEU: `{date}-{project-slug}-{MEU-ID}-handoff.md`. Each handoff is validated independently.
> A non-product project with `meus: []` produces one project handoff at
> `{date}-{project-slug}-handoff.md`.
>
> **Project correlation rule**: In multi-MEU sessions, the correlated `docs/execution/plans/{YYYY-MM-DD}-{project-slug}/implementation-plan.md` and `task.md` must enumerate the full handoff set for the project. `/execution-critical-review` uses those artifacts to expand review scope from the seed handoff to all sibling handoffs produced by the plan.

## Handoff Artifact Location

```text
# Product MEU
.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-{MEU-ID}-handoff.md

# Non-product project (`meus: []`)
.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-handoff.md
```

Example: `.agent/context/handoffs/2026-04-25-pipeline-capabilities-MEU-101-handoff.md`

## Template

> **Start from** [`.agent/context/handoffs/TEMPLATE.md`](file:///{{PROJECT_ROOT}}/.agent/context/handoffs/TEMPLATE.md) (v2.1)
>
> Copy the template, fill all placeholder fields, and ensure:
> - YAML frontmatter `date`, `project`, `meu`, `status`, `action_required`, `verbosity` are populated
> - `action_required` is set to `VALIDATE_AND_APPROVE` for new handoffs
> - `verbosity` defaults to `standard` unless explicitly overridden
> - AC table has source labels for every criterion
> - `<!-- CACHE BOUNDARY -->` marker separates the stable prefix from variable content
> - Evidence section has FAIL_TO_PASS table and Commands Executed table
> - Codex Validation Report section is left blank for the reviewer

### Context Compression Rules (v2.1)

All handoffs must follow the compression rules defined in [`.agent/docs/context-compression.md`](file:///{{PROJECT_ROOT}}/.agent/docs/context-compression.md):

- **Test output**: Only failing test names, assertion messages, and relevant stack frames. Summarize passing tests as `{N} passed`.
- **Code sections**: Use unified diff blocks (` ```diff `) instead of full file contents.
- **Cache boundary**: Do not place dynamic content (timestamps, test results, quality gate numbers) above the `<!-- CACHE BOUNDARY -->` marker.
- **Verbosity**: Respect the `verbosity` YAML field. Default is `standard` (~2,000 tokens).

## Live Runtime Probe Requirements

> **Context**: In 5/7 reviewed projects, mock-based unit tests masked broken runtime behavior, causing 3-5 extra review passes per project. The rest-api-foundation project needed 11 passes largely because stubs silently violated contracts.

For any MEU that touches routes, handlers, or service wiring, the handoff MUST include live runtime evidence:

### Mandatory Probe Protocol

1. **Integration test with real stack**: Create at least one `create_app()` + `TestClient(raise_server_exceptions=False)` test that exercises the full stack _without_ dependency overrides.
2. **Minimum probe sequence** (for API work):
   - Create → Get → List consistency (entity actually persists)
   - Duplicate rejection (both dedup keys)
   - Missing-entity error mapping on all write paths
   - Filter/pagination with multiple entities
   - Owner-scoped listing (when applicable)
3. **State propagation check**: If the MEU changes auth/unlock/mode state, verify the state change propagates to all dependent guards (e.g., `app.state.db_unlocked` after unlock).

### Stub Quality Gate

Stubs used during development MUST honor the behavioral interface:

| Stub Method | Required Behavior |
|---|---|
| `save()` | Actually persists to in-memory store |
| `get()` | Returns persisted entity or `None` |
| `exists()` | Returns correct boolean based on store |
| `list_filtered()` | Actually filters by provided parameters |
| `get_for_owner()` | Filters by `owner_type` and `owner_id` |

**Prohibited patterns**:
- `__getattr__` that silently returns values (`None`, empty collections, no-op callables) for undefined methods
- `save()` that discards writes (creates false 201→404 inconsistency)
- `exists()` that always returns `False` (bypasses dedup checks)

**Permitted**: `__getattr__` that raises `AttributeError` or `NotImplementedError` with the method name is allowed (explicit-error form is safer than missing methods).

### Fix Generalization Scope

> This section is the canonical source for fix-generalization boundaries. Other documents reference this section.

Before applying a fix to "similar locations," classify each candidate:
- **Same contract** → must fix
- **Spec-divergent contract** → allowed to differ (cite spec/ADR)
- **Unknown** → stop and route to planning, do not generalize

**Search boundary**: same package + explicitly listed siblings in `.agent/context/meu-status.yaml`. Cross-package matches → log as follow-up item, do NOT auto-fix.

**Evidence in handoff**: "Checked N locations in {scope}. Fixed M. Skipped K (spec-divergent: {cite}). Verified 0 remaining unaddressed."

## Storage

Product handoffs are stored at
`.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-{MEU-ID}-handoff.md`.
Non-product `meus: []` projects use
`.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-handoff.md`.
The plan and task enumerate the complete set; these files are the source of truth for
cross-session continuity. The rolling project review remains
`.agent/context/handoffs/{plan-folder-name}-implementation-critical-review.md`.

## Status Transitions

```
ready_for_review  →  approved          (Codex validates, all checks pass)
ready_for_review  →  changes_required  (Codex finds issues)
changes_required  →  ready_for_review  (Opus fixes and resubmits)
blocked           →  ready_for_review  (Blocker resolved)
approved          →  (terminal)        (MEU complete, update via `tools/meu_status.py update`)
```

## Max Revision Cycles

Maximum 2 revision cycles (Opus→Codex→Opus→Codex) per MEU. After 2 cycles, escalate to human orchestrator with:
- Summary of disagreement
- Both agents' positions
- Recommended resolution
