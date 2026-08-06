---
name: Git Workflow
description: Agent-safe git operations with SSH commit signing. Handles commit, push, and signing configuration to avoid interactive prompt hangs.
---

# Git Workflow Skill

## Commit Policy

> **Do NOT `git commit` or `git push` unless (a) the user explicitly directs it, or (b) it is a defined step in the approved plan/task.** Never auto-commit at the end of a correction cycle or verification pass.

> [!CAUTION]
> **NEVER use `--no-verify` without explicit human approval.**
> Bypassing pre-commit hooks defeats the safety net and pushes broken code to CI.
> If a pre-commit hook fails, **stop and fix the underlying issue** — do NOT bypass the hook.
> The only exception is if the user explicitly says "bypass the hooks" or "use --no-verify".

## The One Rule

> **Run the script. Don't improvise git commands.**
>
> ```powershell
> # // turbo
> pwsh -File .agent/skills/git-workflow/scripts/agent-commit.ps1 -Message "feat: description"
> ```
>
> The script validates signing config, stages, commits, pushes, and verifies — all in one command.
> If you skip the script, you WILL cause a hang.

**Agent invocation rules:**
- Set `WaitMsBeforeAsync` to **30000** (push can take 10-20s on large changesets)
- If the command goes to background anyway, do NOT poll `command_status` — run `git log --oneline -1` directly to verify
- Never issue more than one `command_status` check; if it shows no output, the command finished and output was lost — verify the result instead

## Script Usage

```powershell
# Basic commit + push to main
# // turbo
pwsh -File .agent/skills/git-workflow/scripts/agent-commit.ps1 -Message "feat: add new feature"

# With body text
# // turbo
pwsh -File .agent/skills/git-workflow/scripts/agent-commit.ps1 -Message "feat: add feature" -Body "Detailed description here"

# Push to a different branch
# // turbo
pwsh -File .agent/skills/git-workflow/scripts/agent-commit.ps1 -Message "fix: correct bug" -Branch "dev"

# Commit without pushing
# // turbo
pwsh -File .agent/skills/git-workflow/scripts/agent-commit.ps1 -Message "wip: save progress" -NoPush

# Skip tests for WIP commits
# // turbo
pwsh -File .agent/skills/git-workflow/scripts/agent-commit.ps1 -Message "wip: save progress" -SkipTests -NoPush
```

### Exact-Scope Signed Commit Mode

Use this mode for an approved packet in a dirty worktree or guarded clone. All
seven binding arguments are required, and `-NoPush` is mandatory because push
is a separate approved checkpoint:

```powershell
rtk proxy pwsh -NoProfile -File .agent/skills/git-workflow/scripts/agent-commit.ps1 `
  -RepositoryPath <guarded-repository> `
  -ScopeManifest <approved-manifest> `
  -ExpectedBase <approved-parent-sha> `
  -ExpectedTree <approved-tree-sha> `
  -ContentDescriptor <approved-content-descriptor.json> `
  -MessageFile <approved-message.txt> `
  -OutputState <checkpoint-state.json> `
  -NoPush *> {{RECEIPTS_DIR}}/exact-scope-commit.txt
```

This mode loads the approved base into a temporary index, stages only manifest
paths, rejects base/tree/message/signing-fingerprint drift, creates an
SSH-signed commit, verifies its signature and parent/tree, and records the
actual SHA. It then resets only the committed scope entries in the caller's
index; unrelated staged entries remain staged. It never pushes and must not be
invoked before the packet's direct human approval has been validated.

### What the Script Does (Do NOT Do These Manually)

1. ✅ Validates SSH signing config (fails fast if GPG would hang)
2. ✅ Checks remote URL format (warns on HTTPS)
3. ✅ Legacy mode stages all changes (`git add -A`); exact-scope mode stages only the approved manifest in an isolated index
4. ✅ Runs Ruff lint + unit tests (aborts on failure) — skip with `-SkipTests`
4c. ✅ Regenerates `openapi.committed.json` if stale (prevents CI drift failures)
5. ✅ Commits with `-m` flag (never opens editor)
6. ✅ Pushes to origin (unless `-Push $false`)
7. ✅ Verifies with `git log --oneline -1`

### Pre-Commit Mandatory Step: Session Digest

> [!CAUTION]
> **Before running the commit script**, generate a session digest in `.agent/context/sessions/`. This provides human-readable session memory that future agents and the user can reference. The commit script does NOT do this automatically — it's an agent-side responsibility.
>
> **This is a mandatory exit criterion** in both `/execution-session` and `/create-plan` workflows. Skipping it is a quality violation equivalent to skipping the reflection file.

**When required:** Every commit session that involves implementation work (MEU execution, ad-hoc fixes, infrastructure wiring, research with findings). Skip ONLY for trivial doc-only typo fixes that don't change project state.

**File location:** `.agent/context/sessions/{conversation-id}/digest.md`

> The conversation ID is available in the `<user_information>` block at the start of every conversation (field: `Conversation ID`).

**Template** (matches canonical exemplar from [fd11a3d4](../../context/sessions/fd11a3d4-d10a-4249-8cf4-271424e721dd/digest.md)):

```markdown
# Session Digest — {conversation-id}

**Date:** {YYYY-MM-DD}
**Project:** {project name} ({what was done — plan/implementation/research})
**Duration:** ~{N} hours

## Decisions Made

| # | Decision | Authority | Source |
|---|----------|-----------|--------|
| 1 | {what was decided} | {Human-approved / Codex-verified / Agent-decided} | {context} |

## Blockers & Open Questions

{list of unresolved items, or "None — all open questions resolved during session."}

## Test & Quality-Gate Outcomes

| Gate | Result | Notes |
|------|--------|-------|
| Codex review | {✅ Approved (R{N}) / ❌ Rejected} | {round count and reason} |
| pytest | {✅ pass / ⚠️ pre-existing failure} | {details} |
| tsc --noEmit | {✅ pass} | |
| npm run build | {✅ pass} | |
| Git commit | {✅ Committed} | {hash, file count, pushed/not pushed} |

## Files Changed

### New Files
- `path/to/new/file` — {description}

### Modified Files
- `path/to/modified/file` — {what changed}

## Provenance

- Conversation ID: `{conversation-id}`
- Transcript: `C:\Users\Mat\.gemini\antigravity-ide\brain\{conversation-id}\.system_generated\logs\transcript.jsonl`
```

**Rules:**
- One digest per conversation in its own subdirectory: `.agent/context/sessions/{conversation-id}/digest.md`
- Keep digests concise — max ~60 lines. This is a decision/outcome log, not a reflection
- Reference the full reflection for detailed analysis: `docs/execution/reflections/{date}-{slug}-reflection.md`
- The **Decisions Made** table is the most important section — it captures what was decided and by whom
- Always include **Provenance** with conversation ID and transcript path for traceability

### Pre-Commit Hook Failures

**Symptom**: `git commit` fails with `[WARNING] Unstaged files detected` or a hook exit code.

**Correct response — always:**
1. Read the hook output to identify the exact failure (lint, type error, test)
2. Fix the underlying issue in the affected file(s)
3. Re-run the commit — do NOT add `--no-verify`

**NEVER do this:**
```powershell
# ❌ Hides the error, pushes broken code to CI
git commit --no-verify -m "..."
```

**If the hook is genuinely misconfigured** (e.g., it blocks commits to main unconditionally),
call `notify_user` and ask the user if they want to bypass — never decide unilaterally.

### Lint Failures (Ruff)

**Symptom**: Quality Gate fails at lint step.

**Diagnosis**: Ruff errors include file:line:col and rule codes.

**Fix**:
```bash
uv run ruff check packages/ tests/ --fix   # auto-fix safe issues
uv run ruff check packages/ tests/         # verify remaining issues
```

## Agent Workflow Checklist

If you cannot use the script for any reason, copy this checklist and check off each step:

```
Git Commit Progress:
- [ ] Step 1: Check signing — `git config --global gpg.format` must be "ssh" (if gpgsign=true)
- [ ] Step 2: Check remote — `git remote get-url origin` (must be SSH, not HTTPS)
- [ ] Step 3: Status — `git status --short`
- [ ] Step 4: Stage — `git add -A`
- [ ] Step 5: Commit — `git commit -m "type: description"` (ALWAYS -m flag)
- [ ] Step 6: Push — `git push origin main`
- [ ] Step 7: Verify — `git log --oneline -1`
```

> [!CAUTION]
> **NEVER skip Step 1.** If `commit.gpgsign=true` and `gpg.format` is not `ssh`, the commit WILL hang waiting for GPG pinentry. Either fix the config or use `--no-gpg-sign`.

## Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Use |
|--------|-----|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `test:` | Adding/updating tests |
| `refactor:` | Code restructuring |
| `chore:` | Maintenance tasks |

Commit messages and bodies must not include AI attribution trailers or generated-by
statements. Do not add text such as `Co-Authored-By: Claude`, `Co-authored-by:
Claude`, `Generated with Claude`, or similar agent/vendor attribution.

## Commands That WILL Hang (Never Use)

```powershell
git commit              # Opens editor
git commit --amend      # Opens editor
git rebase -i HEAD~3    # Interactive — opens editor
git merge --no-ff branch # Opens editor for merge message
```

## Troubleshooting

### Commit hangs

```powershell
# Quick fix — bypass signing for one commit:
git commit --no-gpg-sign -m "feat: description"
```

### Push hangs

```powershell
# Check remote format:
git remote get-url origin
# Must be: git@github.com:user/repo.git (SSH)
# Fix:     git remote set-url origin git@github.com:USER/REPO.git
```

## One-Time Setup: SSH Signing

Only needed if SSH signing is not already configured. Check first:

```powershell
git config --global gpg.format
# If output is "ssh" → already configured, skip this section
```

### Setup Steps

```powershell
# 1. Generate dedicated signing key
# // turbo
ssh-keygen -t ed25519 -C "you@example.com" -f "$HOME/.ssh/id_ed25519_signing" -N ""

# 2. Configure git
git config --global gpg.format ssh
git config --global user.signingkey "$HOME/.ssh/id_ed25519_signing.pub"
git config --global commit.gpgsign true
git config --global tag.gpgsign true

# 3. Remove old GPG config
git config --global --unset gpg.program 2>$null

# 4. Display key for GitHub registration
Get-Content "$HOME/.ssh/id_ed25519_signing.pub"
```

Then add to GitHub → Settings → SSH and GPG keys → **New SSH key** → Key type: **Signing Key**.
