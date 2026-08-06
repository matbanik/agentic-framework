# {{PROJECT_NAME_TITLE}} Commands & Operational Reference

> Relocated from AGENTS.md (2026-06-13 instruction-set-optimization slim). Operational reference: Quick Commands, Skills index, MCP Servers, Context & Docs, RTK.
>
> Command lines below show tool argv only. Route and capture them through the
> [RTK section below](#rtk-rust-token-killer---token-optimized-commands) and
> terminal preflight before execution.
> (`output-evidence-policy.md` is source-repo-only — see MANIFEST §EXCLUDED.)


## Quick Commands

> The following fenced block is an argv-only reference block. Route every selected
> argv through the canonical receipt policy before execution.

```bash
# Validation (current scaffold: Python-only)
uv run python tools/validate_codebase.py --scope meu  # MEU gate during active implementation
uv run python tools/validate_codebase.py              # Full phase gate after all phase MEUs complete
pytest tests/unit/                                    # Python unit tests
pyright packages/                                     # Python type check
ruff check packages/                                  # Python lint

# MEU Status SSOT
uv run python tools/meu_status.py list --status pending --unblocked  # Next unblocked work
uv run python tools/meu_status.py next                              # Top 5 unblocked MEUs
uv run python tools/meu_status.py stats                             # Summary counts
uv run python tools/meu_status.py update <row_key> <status>         # Update status
uv run python tools/meu_status.py render --check                    # CI drift gate

# Issue Triage (known-issues.yaml SSOT)
uv run python tools/issue_triage.py stats                            # Issue counts
uv run python tools/issue_triage.py list --json                      # All issues (machine)
uv run python tools/issue_triage.py list --severity critical         # Filter by severity
uv run python tools/issue_triage.py get <ISSUE-ID>                   # Single issue details
uv run python tools/issue_triage.py add --id <ID> --title <T> --severity <S> --component <C>  # Record new
uv run python tools/issue_triage.py verify                           # Flag stale (>30d)
uv run python tools/issue_triage.py verify --deep                    # Deep verify: file checks, test coverage
uv run python tools/issue_triage.py render                           # Regenerate markdown
uv run python tools/issue_triage.py bucket                           # Group issues into proposed MEU batches
uv run python tools/issue_triage.py triage                           # Generate triage-output.yaml
uv run python tools/issue_triage.py triage --output <PATH>           # Generate to custom path
uv run python tools/issue_triage.py discover --dry-run               # Scan for TODO/FIXME/HACK (preview)
uv run python tools/issue_triage.py discover                         # Scan and persist candidates
uv run python tools/issue_triage.py discover --root <DIR>            # Scan specific directory
uv run python tools/issue_triage.py promote <ID>                     # Promote candidate → open
uv run python tools/issue_triage.py dismiss <ID>                     # Dismiss candidate → dismissed
uv run python tools/issue_triage.py render --include-candidates      # Render with candidate section

# Development (current scaffold)
pytest --cov=packages/core --cov-report=term            # Coverage (advisory)

# Planned scaffold commands (run only after the package exists)
# uv run fastapi dev packages/api/src/{{PROJECT_NAME}}_api/main.py  # API
# npx tsc --noEmit                                          # TypeScript type check
# npx vitest run                                            # TypeScript unit tests
# npx eslint <ts-package>/src --max-warnings 0              # TypeScript lint
# npm run dev                                               # Electron UI
```


## Skills

| Skill | Path | Purpose |
|-------|------|---------|
| Git Workflow | `.agent/skills/git-workflow/SKILL.md` | Agent-safe git operations with SSH commit signing. Prevents interactive prompt hangs. |
| Codebase Quality Gate | `.agent/skills/quality-gate/SKILL.md` | Validation pipeline: type checks, linting, tests, anti-placeholder scans, evidence checks. Supports phase-level and MEU-scoped runs. |
| MEU Status SSOT | `.agent/skills/meu-status/SKILL.md` | Query, update, and render MEU completion status via the central YAML SSOT. Replaces manual edits to meu-registry.md and BUILD_PLAN.md status tables. |
| Pre-Handoff Review | `.agent/skills/pre-handoff-review/SKILL.md` | Self-review protocol addressing 10 recurring patterns from critical review analysis. Reduces average review passes from 4-11 to 3-5. |
| Terminal Pre-Flight | `.agent/skills/terminal-preflight/SKILL.md` | Mandatory pre-flight checklist for terminal commands. Enforces the redirect-to-file pattern to prevent PowerShell buffer saturation and session hangs. |
| Completion Pre-Flight | `.agent/skills/completion-preflight/SKILL.md` | Mandatory pre-flight checklist before stop/report events. Enforces task.md re-read gate and post-truncation recovery sequence to prevent premature stop. |
| Completion Timestamp | `.agent/skills/timestamp/SKILL.md` | Generate the canonical completion timestamp from the system clock using the skill's registered exact-receipt command; do NOT derive time from UTC tool response headers. |
| Issue Triage | `.agent/skills/issue-triage/SKILL.md` | Record, query, verify, and manage known issues via the YAML SSOT (`known-issues.yaml`). Use when discovering bugs or reviewing issue status. |
| Subagent Delegation | `.agent/skills/subagent-delegation/SKILL.md` | In-harness subagent detection + delegation gate (Cursor `.cursor/agents/`, Claude Code `.claude/agents/`). Resolves `fresh_worker`, routes eligible `task.md` rows to `{{PROJECT_NAME}}-builder`/`{{PROJECT_NAME}}-verifier`, and enforces the never-delegate categories. |
| CLI Dispatch | `.agent/skills/cli-dispatch/SKILL.md` | External CLI routing: Codex wrapper, Claude `-p`, agy `-p`. Independent review stays on the Codex chain. |
| Deep Research Prompting | `.agent/skills/deep-research-prompting/SKILL.md` | Portal-ready deep research prompt procedure: Pomera MCP preflight hard gate, provider capability recon query bank (Tavily/Exa routing), 14-day capability snapshots, D1/D2/D3 prompt templates, triangulation synthesis. Driven by `/inspiration-research`. |

## MCP Servers

| Server | Purpose | Verify With |
|--------|---------|-------------|
| `text-editor` | Hash-based conflict-safe editing | `get_text_file_contents` |
| `sequential-thinking` | Complex multi-step analysis | `sequentialthinking` |


## Context & Docs

- **How development works end-to-end** → `.agent/docs/development-lifecycle.md` — the 9-phase lifecycle (inspiration → committed code), human-intervention map, and infrastructure map. **Source of truth for the process.** Its narrative companion `.agent/docs/agentic-methodology.md` covers the *why* (philosophy, economics, design rationale). Read the lifecycle doc when onboarding to the workflow or when you need the full process map.
- **Harness capability profiles** → `.agent/docs/harness-profiles.md` — capability flags (`role`, `plan_to_exec_gate`, `injects_auto_approval`, `can_dispatch_external_reviewer`, `native_shell`, `read_tool`/`shell_tool`/`end_turn_signal`) per harness, plus the tool-name substitution table. Read when a workflow/skill branches on harness identity or a tool name looks Antigravity-specific.
- **Model & CLI routing** → `.agent/docs/model-routing.md` — the routed stack (3 model tiers — Coordinator/Builder/Router — + external reviewer + 2 execution modes), the independent-reviewer chain, and nesting/delegation rules. Canonical source for "which model does which task."
- Testing strategy → `.agent/docs/testing-strategy.md`
- Code quality examples → `.agent/docs/code-quality.md`
- **Emerging standards** → `.agent/docs/emerging-standards.md` — living checklist of MCP/GUI/API standards discovered during development. **Read before planning any MCP or GUI MEU.**
- Role specs → `.agent/roles/`
- Handoff template → `.agent/context/handoffs/TEMPLATE.md`
- Current focus → `.agent/context/current-focus.md`
- Known issues → `.agent/context/known-issues.yaml` (SSOT) / `.agent/context/known-issues.md` (generated)
- Full specification → `docs/BUILD_PLAN.md`


<!-- headroom:rtk-instructions -->
# RTK (Rust Token Killer) - Token-Optimized Commands

Prefix shell commands with RTK. Native filters provide compact views only after
command-matrix verification. Unsupported commands and exact evidence use
`rtk proxy`; pass-through-looking forms are not assumed safe. (The originating
repo's `output-evidence-policy.md` is the longer form of this section; it is
deliberately not ported — see MANIFEST §EXCLUDED.)

## Key Commands

> The following fenced block is an argv-only reference block for RTK subcommands.
> It is not executable receipt guidance.

```bash
# Git (59-80% savings)
rtk git status          rtk git diff            rtk git log

# Files & Search (60-75% savings)
rtk ls <path>           rtk read <file>         rtk grep <pattern>
rtk find <pattern>      rtk diff <file>

# Test (90-99% savings) — shows failures only
rtk pytest tests/       rtk cargo test          rtk test <cmd>

# Build & Lint (80-90% savings) — shows errors only
rtk tsc                 rtk lint                rtk cargo build
rtk prettier --check    rtk mypy                rtk ruff check

# Analysis (70-90% savings)
rtk err <cmd>           rtk log <file>          rtk json <file>
rtk summary <cmd>       rtk deps                rtk env

# GitHub (26-87% savings)
rtk gh pr view <n>      rtk gh run list         rtk gh issue list

# Infrastructure (85% savings)
rtk docker ps           rtk kubectl get         rtk docker logs <c>

# Package managers (70-90% savings)
rtk pip list            rtk pnpm install        rtk npm run <script>
```

## Rules
- In command chains, classify each segment and preserve the first failing exit code.
- For debugging, document the bypass reason and retain the P0 receipt.
- `rtk proxy <cmd>` is the canonical unfiltered route for exact evidence.
- On Windows, use PowerShell 7 (`pwsh`) for child scripts that require modern cmdlets
  such as `Get-FileHash`; `powershell.exe` is legacy compatibility only.
<!-- /headroom:rtk-instructions -->
