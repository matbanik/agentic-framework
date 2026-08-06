---
name: Issue Triage
description: Record, query, verify, and manage known issues via the YAML SSOT. Use when discovering bugs, reviewing issue status, or preparing triage reports.
---

# Issue Triage Skill

Record and manage known issues in the project's YAML single source of truth (`.agent/context/known-issues.yaml`).

## When to Use

- **Discovered a bug or issue** during implementation → `add`
- **Need to check if an issue already exists** → `list --json` or `get`
- **Session end** → `verify` to flag stale issues
- **After modifying the YAML** → `render` to regenerate `known-issues.md`

## Quick Reference

```bash
# Record a new issue
uv run python tools/issue_triage.py add \
  --id "ISSUE-ID" \
  --title "Short description" \
  --severity medium \
  --component api \
  --add-status open \
  --discovered 2026-06-25 \
  --root-cause "What causes it" \
  --blast-radius "What needs to change"

# Query
uv run python tools/issue_triage.py stats                          # Overview counts
uv run python tools/issue_triage.py list                           # All issues (human)
uv run python tools/issue_triage.py list --json                    # All issues (machine)
uv run python tools/issue_triage.py list --severity critical       # Filter by severity
uv run python tools/issue_triage.py list --component api --json    # Filter + JSON
uv run python tools/issue_triage.py get ISSUE-ID                   # Single issue details

# Maintenance
uv run python tools/issue_triage.py verify                         # Flag stale (>30d)
uv run python tools/issue_triage.py verify --deep                  # Deep verify: file checks, test coverage, updates last_checked
uv run python tools/issue_triage.py render                         # Regenerate markdown
uv run python tools/issue_triage.py render --check                 # Check for drift only
uv run python tools/issue_triage.py migrate [--dry-run]            # One-time MD→YAML migration (legacy adopters)

# Triage workflow tools
uv run python tools/issue_triage.py bucket                         # Group actionable issues into proposed MEU batches
uv run python tools/issue_triage.py triage                         # Generate ephemeral triage-output.yaml
uv run python tools/issue_triage.py triage --output PATH           # Generate to custom path

# Discovery pipeline
uv run python tools/issue_triage.py discover --dry-run             # Scan for TODO/FIXME/HACK (preview)
uv run python tools/issue_triage.py discover                       # Scan and persist candidates to YAML
uv run python tools/issue_triage.py discover --root /path/to/dir   # Scan specific directory
uv run python tools/issue_triage.py promote DISC-001               # Promote candidate → open
uv run python tools/issue_triage.py dismiss DISC-002               # Dismiss candidate → dismissed
uv run python tools/issue_triage.py render --include-candidates    # Render with candidate section
```

## ID Conventions

Use a short uppercase prefix matching the component or feature area.
**Adopters:** replace this table with your domain prefixes (see `ADOPTION-QUESTIONS` Block D8).

| Prefix | Area | Example |
|--------|------|---------|
| `GUI-` | UI / desktop | `GUI-AUTH-SESSION` |
| `API-` | HTTP / service boundary | `API-CASCADE-DELETE` |
| `CORE-` | Domain logic | `CORE-INVARIANT` |
| `INFRA-` | Persistence / platform | `INFRA-MIGRATION` |
| `CI-` | CI/CD | `CI-FLAKY-E2E` |
| `DOC-` | Documentation | `DOC-ONBOARDING` |

## Valid Enum Values

- **severity**: `critical`, `high`, `medium`, `low`
- **component**: defaults in `tools/issue_triage/model.py` → `VALID_COMPONENTS`
  (`core`, `infrastructure`, `api`, `ui`, `mcp-server`) — **edit that frozenset for your project**
- **status**: `open`, `in_progress`, `workaround`, `mitigated`, `resolved`, `candidate`, `dismissed`
- **category** (triage taxonomy): `MEU-NEW`, `MEU-EXPAND`, `PLAN-NEW`, `ARCH-DECISION`,
  `UPSTREAM`, `BLOCKED`, `WORKAROUND-OK`, `TECH-DEBT`, `CONFIGURATION`, `DOCUMENTATION`,
  `MONITORING`, `DEFER`, `CLOSE` (+ legacy `DESIGN-DECISION`)

## After Adding or Modifying Issues

Always regenerate the markdown and verify no drift:

```bash
uv run python tools/issue_triage.py render
uv run python tools/issue_triage.py render --check
```

## Architecture

- **SSOT**: `.agent/context/known-issues.yaml`
- **Generated markdown**: `.agent/context/known-issues.md` (auto-generated, do NOT edit)
- **CLI entrypoint**: `tools/issue_triage.py`
- **Package**: `tools/issue_triage/` (model, query, render, verify, migrate, bucket, triage, discover)
- **Triage output**: `.agent/context/triage-output.yaml` (ephemeral, regenerate with `triage`)
