---
name: Issue Triage
description: Record, query, verify, and manage known issues via the YAML SSOT. Use when discovering bugs, reviewing issue status, or preparing triage reports.
---

# Issue Triage Skill

Record and manage known issues in the project's YAML single source of truth (`.agent/context/known-issues.yaml`).

## When to Use

- **Discovered a bug or issue** during implementation → `add`
- **Need to check if an issue already exists** → `list --json` or `get`
- **Session end** → `verify` to flag stale issues, then §Distill and Close each one
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

## Distill and Close (the file is an inbox, not a knowledge base)

`known-issues.yaml` is an **inbox**. An entry is a reminder that something has not yet
been turned into a rule, a check, or a test — it is not the place knowledge lives. Left
alone, the file becomes an always-loaded novel: every session pays to read it, no session
acts on it, and the entries that matter are camouflaged by the ones that never will.

An issue is closed by **distilling** it, which means naming where the knowledge now lives:

| Outcome | What "distilled" means | Then |
|---|---|---|
| It became a rule | A line in `AGENTS.md`/`GUARDRAILS.md` or the relevant skill now prevents it — cite the `file:section` in the resolution note | set `status: resolved` |
| It became a check | A gate, test, or `--selftest` arm now fails on it, and that arm is *proven able to fail* (V5) — cite the command | set `status: resolved` |
| It became work | It is a real deliverable → route through `bucket`/`triage` into a MEU or plan | keep `open`; it now carries a plan id |
| It was never real | Reproduction attempt failed, or the condition is gone | `candidate` → `dismiss <ID>`; anything else → set `status: dismissed` with the reason |

There is no `set-status` subcommand: for a non-candidate issue, edit its `status` (and
resolution note) in `known-issues.yaml`, then `render` — the YAML is the SSOT and the
markdown is generated. `dismiss` only accepts an issue whose status is `candidate` and
refuses anything else, so it is not a shortcut for closing an open issue.

**A resolution note that only says "fixed" is not a distillation.** Name the artifact that
now carries the knowledge; if you cannot name one, the issue is not closed — the symptom
just stopped being visible.

`verify` (stale >30 days) is the trigger, not a nag: a stale entry means nobody has
decided which of the four rows above it belongs to. Do that at session end, when
`render` already runs — and keep the rendered `known-issues.md` under its <100-line
target, which is the observable that tells you distillation is actually happening.

**Session start reads the rendered digest, not the YAML.** If an entry needs to be read
every session to keep the work correct, that is the strongest possible signal it should
have been a rule in an always-loaded file instead — distill it and close it.

## Architecture

- **SSOT**: `.agent/context/known-issues.yaml`
- **Generated markdown**: `.agent/context/known-issues.md` (auto-generated, do NOT edit)
- **CLI entrypoint**: `tools/issue_triage.py`
- **Package**: `tools/issue_triage/` (model, query, render, verify, migrate, bucket, triage, discover)
- **Triage output**: `.agent/context/triage-output.yaml` (ephemeral, regenerate with `triage`)
