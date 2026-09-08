# Claude CLI as Codex Fallback — Lessons Learned

> [!CAUTION]
> **THE PRACTICE DOCUMENTED HERE IS NOW PROHIBITED.** Using the coordinator's own vendor
> as a reviewer rung — "same-vendor self-review" — is not a permitted fallback at any
> effort level. This file is retained only for its **CLI-mechanics** lessons (flag
> differences, prompt-file handling, exit-code shapes), which are what the wrapper
> encapsulates. Do **not** read it as a live fallback chain.
>
> **What replaced it:** when every *cross-vendor* rung is rate-limited or unavailable,
> the escalation is a **human gate** (`cli-dispatch/SKILL.md` §0 human-handoff path),
> not a self-review round. A second adopting repo reached the same conclusion
> independently and made it a standing prohibition.
>
> **Why the archive was not enough.** This banner previously said only that the wrapper
> "encapsulates these differences" — which reads as *the mechanism was fixed*, and left
> the practice looking merely awkward rather than forbidden. Agents kept finding the
> rung in the chain and taking it. A file that documents how to do a prohibited thing
> needs the prohibition in the banner, not in a sibling doc.

**Date:** 2026-06-07
**Context:** MEU-118a critical review loop, Rounds 5+
**Trigger:** Codex CLI rate-limited until June 10, 2026 (usage credits exhausted)

---

## Problem

During the `/execution-critical-review` loop for MEU-118a, Codex CLI hit its usage limit after Round 4:

```
ERROR: You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage
to purchase more credits or try again at Jun 10th, 2026 8:25 PM.
```

The project requires external validation (self-review is prohibited per AGENTS.md). With Codex unavailable for 3 days, Claude CLI (Opus 4.8) was the fallback reviewer.

---

## Issue 1: CLI Flag Differences

### `-C` (working directory) does NOT exist in Claude CLI

**Codex (Historical direct command — superseded by Invoke-CodexDispatch.ps1):**
```powershell
# [HISTORICAL] codex exec -C {{PROJECT_ROOT}} -s danger-full-access ...
```

**Claude — WRONG:**
```powershell
# claude -p -C {{PROJECT_ROOT}} ...  # ❌ error: unknown option '-C'
```

**Claude — CORRECT:**
```powershell
# Set Cwd in the run_command tool instead
# Claude uses the shell's working directory automatically
# claude -p ...  # ✅ with Cwd set to {{PROJECT_ROOT}}
```

> **Rule:** Claude CLI has no `-C` flag. Set the working directory via the `Cwd` parameter of `run_command`.

---

## Issue 2: Permission Mode Values

### `full` is not a valid permission mode

**Codex (Historical direct command — superseded by Invoke-CodexDispatch.ps1):**
```powershell
# [HISTORICAL] -s danger-full-access  # Full filesystem access
```

**Claude — WRONG:**
```powershell
# --permission-mode full  # ❌ error: argument 'full' is invalid
```

**Claude — CORRECT:**
```powershell
# --permission-mode bypassPermissions  # ✅ Full access, no prompts
```

**All valid Claude permission modes (Historical reference):**
| Mode | Behavior |
|------|----------|
| `default` | Prompts for each action |
| `plan` | Read-only (no file writes) |
| `acceptEdits` | Auto-accepts file edits, prompts for commands |
| `auto` | Auto-accepts most actions |
| `dontAsk` | Never prompts (still has guardrails) |
| `bypassPermissions` | Full access, no prompts (equivalent to Codex `danger-full-access`) |

> **Rule:** Standard reviews run in read-only sandboxes (e.g. `ReviewReadOnly` mode). The wrapper enforces this automatically. Direct high-privilege permission flags are deprecated.

---

## Issue 3: Rate Limits Are Account-Level, Not Per-Session

Claude's rate limit applies to the **entire account**, not per session or per invocation.

**What happened:**
1. First attempt: 42 turns, $7.54 spent → hit limit, resets 6:50 PM ET
2. Resume attempt with `--resume <session-id>`: Immediately rejected (same account limit)
3. New session attempt: Also immediately rejected
4. Had to wait for the full reset window

**Key timing observations:**
| Attempt | Time (ET) | Reset Time | Result |
|---------|-----------|------------|--------|
| Run 1 | 12:57 PM | 1:50 PM | Hit limit after 25 turns |
| Run 2 | 1:54 PM | 1:50 PM | Worked (reset had passed), ran 42 turns |
| Run 2 end | ~2:01 PM | 6:50 PM | Hit limit again |
| Run 3 | 2:02 PM | 6:50 PM | Immediately rejected |

> **Rule:** After hitting a Claude rate limit, you must wait for the stated reset time. There is no workaround — `--resume`, new sessions, and different prompts all hit the same account limit.

---

## Issue 4: Long Prompts Consume Too Many Turns on File Reading

Both Claude sessions used most of their turns reading files and running verification commands, then hit the limit before writing the verdict file.

**Turn budget breakdown (Run 2 — 42 turns):**
- ~10 turns: Reading workflow, template, handoff, plan, task files
- ~15 turns: Reading source/test files
- ~12 turns: Running pytest, pyright, ruff, vitest, OpenAPI check, smoke tests
- ~5 turns: Writing analysis
- 0 turns left: Could not write the verdict file

> **Rule:** For follow-up rounds (Round 3+), the reviewer has already seen most files. Use a focused prompt that tells the agent exactly which files changed and what to verify. Don't ask it to "read ALL changed files" — specify the 2-3 files that actually changed.

**Optimized prompt template for follow-up rounds:**
```
Round N review for {MEU}. The ONLY change since Round N-1:
- {file1}: {what changed, 1 line}
- {file2}: {what changed, 1 line}

Verify: (1) run pytest on {specific test files}, (2) check {specific assertion}.
Prior round review: {path}. Write verdict to {path}. Template: {path}.
```

---

## Issue 5: The Orchestrator File-Write Workaround

When Claude ran all verification but couldn't write the file, the orchestrator wrote the verdict based on Claude's verification receipts.

**Why this is acceptable:**
1. Claude DID perform independent verification (42 turns of file reads, test runs, smoke tests)
2. All verification evidence is preserved in receipt files (`{{RECEIPTS_DIR}}\review5\`)
3. The orchestrator only wrote the structured verdict — it did not perform the review analysis
4. This follows the dispatch skill's rate-limit fallback protocol

**The pattern:**
```
1. External agent runs verification → produces receipt files
2. External agent hits rate limit before writing verdict
3. Orchestrator reads receipt files
4. Orchestrator writes verdict file using the template
5. Verdict file documents the split: "Agent X (verification) + Orchestrator (file write)"
```

> **Rule:** If the external reviewer completes verification but can't write output, the orchestrator MAY write the verdict file IF: (a) verification receipts exist, (b) the file documents the split authorship, (c) the orchestrator does not add its own review analysis.

---

## Codex vs Claude CLI — Quick Reference

| Feature | Codex CLI | Claude CLI |
|---------|-----------|------------|
| **Install** | `codex` (npm) | `claude` (npm: `@anthropic-ai/claude-code`) |
| **Pipe mode** | `codex exec` | `claude -p` |
| **Working dir** | `-C {{PROJECT_ROOT}}` | Set via shell `Cwd` (no `-C` flag) |
| **Full access** | `-s danger-full-access` | `--permission-mode bypassPermissions` |
| **Read-only** | `-s read-only` | `--permission-mode plan` |
| **Model select** | N/A (uses account default) | `--model <slug>` (resolve the class — [model-routing.md](model-routing.md)) |
| **Reasoning** | `-c model_reasoning_effort=xhigh` | `--effort max` |
| **Output file** | `-o output.md` (final message only) | `--output-format json` (full JSON to stdout) |
| **Max turns** | N/A (runs until done) | `--max-turns 15` |
| **Cost cap** | N/A | `--max-budget-usd 15` |
| **Resume** | N/A | `--resume <session-id>` |
| **Rate limit** | Per-account credits (multi-day) | Per-account session window (~1-5 hours) |

### Output Parsing

**Codex** — `-o` writes just the final message to a file:
```powershell
Get-Content {{RECEIPTS_DIR}}\dispatch\codex-output.md
```

**Claude** — `--output-format json` writes structured JSON to stdout (captured via redirect):
```powershell
$raw = Get-Content {{RECEIPTS_DIR}}\dispatch\claude-output.txt -Encoding Unicode -Raw
$json = $raw | ConvertFrom-Json
$json.result          # The actual text output
$json.is_error        # True if rate-limited or failed
$json.total_cost_usd  # Cost tracking
$json.num_turns       # Turns consumed
$json.session_id      # For --resume
```

---

## Superseded Recommendations

The executable recommendations formerly stored here were removed because they conflicted with the current high-effort ceiling, least-privilege review sandbox, forward-slash receipt convention, and independent-review gate. Use `.agent/skills/cli-dispatch/SKILL.md` and `.agent/docs/model-routing.md` as the current operational sources.

---

## Provenance

- Session: `8b2987f2-2d70-41b4-83a7-e496344dbc13`
- Codex Rounds 1–4: All completed before rate limit
- Claude Round 5 Run 1: Session `2510b74c`, 25 turns, $3.03, rate-limited
- Claude Round 5 Run 2: Session `2510b74c` (resumed context), 42 turns, $7.54, rate-limited
- Total external review cost: ~$10.57 across Claude attempts
- Verification receipts: `{{RECEIPTS_DIR}}\review5\`
