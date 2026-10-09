---
name: CLI Dispatch
description: Route specialized tasks to external CLI agents — Codex (validation/images) through `Invoke-CodexDispatch.ps1`, headless Claude (creative writing/critical decisions/isolated worker) through `Invoke-ClaudeDispatch.ps1` — and collect results back to the orchestrator.
trigger: /cli-dispatch
---

# CLI Dispatch Workflow

> Tool names like `view_file`/`run_command` are capability placeholders — map to your harness's `read_tool`/`shell_tool` per `.agent/docs/harness-profiles.md`.

**Trigger:** `/cli-dispatch` or when the orchestrator identifies a task that benefits from a specialized agent.

**Orchestrator:** You — the primary driver (per `.agent/docs/harness-profiles.md`). **Harness-conditional:** the `coordinator` class resolves per harness from the live registry home you instantiate (see `.agent/INSTANTIATE.md`). You never leave; you dispatch and collect.

---

## Step 1 — Classify the Task

Determine which agent is best suited. Use this decision tree:

```
Is this a HIGH-STAKES DECISION requiring deep deliberation?
  (architecture, breaking changes, security, irreversible choices,
   trade-off arbitration with >2 viable paths, cross-cutting changes)
  → YES → Claude Code (`coordinator` class, effort at class ceiling)

Is this a validation/review task?
  → YES → Codex CLI (`independent_reviewer` class, reasoning=high)

Is this image generation?
  → YES → Codex CLI (`image_generator` class)

Is this data processing (OCR, PDF, large file, transcription)?
  → YES → in-harness subagent → {{PROJECT_NAME}}-builder (`builder` class); the harness reads PDFs and images natively

Is this creative writing / natural prose?
  → YES → Claude Code (the `creative_prose` class)

Is this headless isolated-worker / overnight / CI bulk work where
in-harness Task is unavailable or undesirable?
  → YES → headless Claude via `tools/Invoke-ClaudeDispatch.ps1 -ModelClass isolated_worker`
     (one spawn per worktree), or your harness's headless builder CLI wrapped per `cli-dispatch/SKILL.md`
     Prefer in-harness Task → {{PROJECT_NAME}}-builder when Task is available.
     Never route independent review to a builder (Codex chain only).

None of the above?
  → Handle directly as orchestrator (`coordinator` class — resolve per harness)
```

## Step 2 — Read the Skill

Read (your harness `read_tool`; e.g. `view_file {{PROJECT_ROOT}}\.agent\skills\cli-dispatch\SKILL.md`) `.agent/skills/cli-dispatch/SKILL.md`.

Follow the command template for the selected agent. Key rules:
- For Codex: Use the `Invoke-CodexDispatch.ps1` wrapper script (no `$null |` prefix needed).
- For Claude: Use the `Invoke-ClaudeDispatch.ps1` wrapper script. It feeds the prompt file on stdin (no stdin hang), passes `--output-format json`, and writes `status.json` with the `session_id`.
- Always suffix wrapper dispatches with `*> {{RECEIPTS_DIR}}/dispatch/<agent>-*.txt`.

## Step 3 — Prepare Environment

```powershell
New-Item -ItemType Directory -Force -Path {{RECEIPTS_DIR}}/dispatch
# Clear stale outputs
Remove-Item {{RECEIPTS_DIR}}/dispatch/*-output.* -Force -ErrorAction SilentlyContinue
```

## Step 4 — Construct the Prompt

Build the prompt with these elements:

1. **Context:** What files/code to review, what image to create, what data to process
2. **Task:** Clear, specific instruction
3. **Output format:** Where and how to deliver results
4. **Constraints:** Any restrictions (read-only, cost limits, turn limits)

### Prompt Templates

#### Validation (Codex)
```
You are the Codex validation agent for the {{PROJECT_NAME_TITLE}} project.
Review the following for correctness, completeness, and adherence to project standards.

Target: <FILE_OR_DIRECTORY_PATH>
Context: <WHAT_TO_LOOK_FOR>

Report your findings as:
- VERDICT: PASS or CHANGES_REQUIRED
- FINDINGS: numbered list (severity H/M/L)
- SUMMARY: one paragraph
```

#### Image Generation (Codex)
```
Use the built-in image_gen tool to generate: <DESCRIPTION>.
Save the result to <TARGET_PATH>.
Do NOT use code to draw the image — use the image_gen tool exclusively.
```

#### Creative Writing (Claude)
```
Write in a natural, human-like tone. Avoid bullet points, numbered lists,
and AI-typical phrasing like "certainly", "I'd be happy to", or "let me".
Write as if you are a skilled human writer.

Task: <DESCRIPTION>
Context: <BACKGROUND>
Audience: <WHO_WILL_READ_THIS>
Tone: <FORMAL/CASUAL/TECHNICAL/NARRATIVE>
Length: <APPROXIMATE_WORD_COUNT>
```

#### Critical Decision (`coordinator` class)
```
You are performing a critical review that requires deep, extended reasoning.
Think carefully before answering. Do NOT rush to a conclusion.

Context:
<FULL_CONTEXT — code, architecture, constraints, prior decisions>

Decision required:
<SPECIFIC_QUESTION_OR_TRADE_OFF>

Your analysis MUST include:
1. CONFIDENCE: State Low/Medium/High with explicit reasoning
2. OPTIONS: Enumerate ALL viable paths with pros, cons, and hidden risks
3. SECOND-ORDER EFFECTS: What breaks, degrades, or becomes harder 6 months from now?
4. RECOMMENDATION: Your pick with explicit justification citing the analysis above
5. UNCERTAINTY: Flag anything you are unsure about — do NOT guess or fill gaps
6. DISSENTING VIEW: Steel-man the strongest argument against your recommendation

Output format: structured markdown with ## sections.
```

## Step 5 — Dispatch

Execute the command using your harness's `shell_tool` (e.g. `run_command`) with appropriate `WaitMsBeforeAsync`:

| Agent | Typical Duration | WaitMsBeforeAsync |
|-------|-----------------|-------------------|
| Claude (critical decision) | 10s-2 min | 120000 (2 min, send to background) |
| Codex (validation) | 2-10 min | 300000 (5 min, send to background) |
| Codex (image gen) | 1-3 min | 120000 (2 min, send to background) |
| Claude (creative writing) | 5-30s | 60000 (1 min) |

## Step 6 — Collect Results

After the task completes, read the output:

### Codex (wrapper output)
```powershell
Get-Content {{RECEIPTS_DIR}}/dispatch/{dispatchId}/final.md
# Or if structured JSON:
# Get-Content {{RECEIPTS_DIR}}/dispatch/{dispatchId}/final.json
# Get-Content {{RECEIPTS_DIR}}/dispatch/{dispatchId}/status.json
```

### Claude — Creative Writing or Critical Decision (wrapper output)
```powershell
pwsh -NoProfile -File tools/Invoke-ClaudeDispatch.ps1 -ModelClass creative_prose `
  -DispatchId writing-1 -PromptFile {{RECEIPTS_DIR}}/dispatch/writing-prompt.txt `
  *> {{RECEIPTS_DIR}}/dispatch/claude-writing-1.txt
Get-Content {{RECEIPTS_DIR}}/dispatch/writing-1/final.md      # The actual text/analysis
$status = Get-Content {{RECEIPTS_DIR}}/dispatch/writing-1/status.json -Raw | ConvertFrom-Json
$status.session_id   # Read by -ResumeDispatchId / -ForkDispatchId for a follow-up
$status.model        # Verify correct model was used
```

## Step 7 — Report to User

Present the results to the user with:
1. **Agent used** and model
2. **Result summary** (extracted from output)
3. **Cost** (if available from Claude JSON)
4. **Duration** (from timestamps / status.json)
5. **Full output link** (file path for details)

## Step 8 — Follow-Up (Optional)

If the user wants changes or continuation:
- **Codex:** Execute a new wrapper run with the follow-up prompt, referencing the previous output files for context.
- **Claude:** a new wrapper run with `-ResumeDispatchId <previous dispatch ID>` and a new `-DispatchId`, so the follow-up continues that exact session (see the skill's §Resume and Fork). Never continue "the most recent conversation" in the directory: on a shared tree it may belong to another lane.

---

## Error Recovery

| Failure | Action |
|---------|--------|
| CLI not found | Report installation path, suggest install |
| Timeout | Kill task, report timeout, offer retry with wrapper timeout parameter |
| API error (Codex/Claude) | Parse error message, check auth, report to user |
| Cost exceeded (Claude) | Report `max-budget-usd` hit, offer higher budget |

---

## Anti-Patterns

- ❌ **Never use Codex for creative writing** — it is routed here for validation and image generation, not natural prose
- ❌ **Never use Claude for image generation** — no image_gen tool
- ❌ **Never use `coordinator` for routine reviews** — wasteful at the class's price band; orchestrator handles these
- ❌ **Never use `creative_prose` for critical decisions** — `coordinator` has better judgment and adaptive thinking
- ❌ **Never invoke codex exec directly** — always use `Invoke-CodexDispatch.ps1` wrapper
- ❌ **Never use a builder-tier CLI for independent review verdicts** — Codex chain only (self-review prohibition)
- ❌ **Never launch the Claude CLI directly** — always use `Invoke-ClaudeDispatch.ps1` wrapper (it feeds stdin and records the session)
- ❌ **Never forget `*>` redirect** — causes PowerShell buffer saturation
- ❌ **Never use `codex exec --search`** — search is a top-level option
- ❌ **Never skip effort at the class ceiling on critical decisions** — default effort underutilizes the coordinator class's thinking capacity
