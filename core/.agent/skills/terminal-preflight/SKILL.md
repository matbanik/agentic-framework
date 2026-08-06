---
name: Terminal Pre-Flight
description: Mandatory pre-flight checklist for terminal commands. Enforces the redirect-to-file pattern to prevent PowerShell buffer saturation and session hangs.
---

# Terminal Command Pre-Flight

> Tool names like `view_file`/`run_command` are capability placeholders — map to your harness's `read_tool`/`shell_tool` per `.agent/docs/harness-profiles.md`. This skill keeps `run_command` as its concrete worked example (it is the Antigravity name for the `shell_tool` capability — `Bash` in Claude Code); substitute your harness's shell tool wherever `run_command` appears below.

**Trigger:** MUST be invoked before any `run_command` / terminal execution tool in an execution phase.

**Objective:** Prevent PowerShell buffer saturation and session hang by ensuring every command uses the redirect-to-file pattern.

Use [`.agent/docs/output-evidence-policy.md`](../../docs/output-evidence-policy.md) as
the single authority for RTK native/proxy classification and exact-evidence bypasses.

## Pre-Flight Checklist

Satisfy ALL before every `run_command`:

- [ ] **Redirect check**: command ends with an all-stream redirect — PowerShell `*> <file>` **or** bash `> <file> 2>&1`
- [ ] **Receipts dir**: output routed to `{{RECEIPTS_DIR}}/` — **always forward slashes** (valid in both PowerShell and the Bash tool; backslashes strip in bash → repo-root junk)
- [ ] **No-pipe check**: no `|` piping stdout of long-running process to a filter
- [ ] **Background flag**: if command may run >5s, use appropriate `WaitMsBeforeAsync`
- [ ] **Routing check**: verified native RTK for compact output; `rtk proxy` for
  unsupported commands and exact evidence
- [ ] **Exit check**: save `$LASTEXITCODE` before reading any receipt and propagate it

> These items are the single source of truth — they match `AGENTS.md §PRIORITY 0` exactly.

## SOP: Standard Operating Procedure

Follow this 4-step sequence for every terminal command:

### Step 1 — Declare

State the intent: "I need to run `<tool>` to verify `<what>`."

### Step 2 — Formulate

Build the command using the redirect pattern (forward-slash path in **both** forms):
```
# PowerShell:
<rtk-route> *> {{RECEIPTS_DIR}}/<name>.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/<name>.txt | Select-Object -Last <N>; exit $code
# bash (Claude Code Bash tool):
rtk proxy <command> > {{RECEIPTS_DIR}}/<name>.txt 2>&1; code=$?; tail -n <N> {{RECEIPTS_DIR}}/<name>.txt; exit $code
```

### Step 3 — Execute + Detach

Run the command with `run_command`. Set `WaitMsBeforeAsync` appropriately:
- Quick commands (rg, Get-Content): 3000–5000ms
- Test suites (pytest, vitest): 5000–10000ms

### Step 4 — Consume Artifact

Read the output file. Do NOT poll the terminal interactively. If the command was sent
to background, `command_status` may check liveness once; it never reads output.

## Per-Tool Command Table

Do not maintain a duplicate per-tool table. Classify commands through
`output-evidence-policy.md`; use `rtk proxy` whenever exact counts, order, diffs, JSON,
schema, security/authentication, exit propagation, or optimization baselines matter.

For a PowerShell child process that needs modern cmdlets such as `Get-FileHash`, use
PowerShell 7 via `pwsh`. `powershell.exe` is a legacy compatibility surface. The
`native_shell: powershell` flag still selects `*>` redirect syntax for both.

On macOS/Linux, resolve `native_shell` to `bash` or `posix-sh` for native shells, or
run the PowerShell wrapper under `pwsh` (Homebrew **formula**). Full install, Seatbelt,
receipts-dir, and Tahoe blockers: [`.agent/docs/macos-setup.md`](../../docs/macos-setup.md).

## Example Thought Process

```
Agent thinking:
"I need to run pytest to verify the Green phase.

Step 1 — Declare: I need to run pytest on tests/unit/test_calculator.py.
Step 2 — Formulate:
  rtk proxy uv run pytest tests/unit/test_calculator.py -x --tb=short -v *> {{RECEIPTS_DIR}}/pytest.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/pytest.txt | Select-Object -Last 40; exit $code
Step 3 — Execute: [run_command with WaitMsBeforeAsync=8000]
Step 4 — Consume: Read the output. 12 passed, 0 failed. Green phase confirmed."
```

## Anti-Patterns (Never Do These)

> The following fenced block is an anti-pattern reference block and is not executable
> guidance.

```powershell
# ❌ Direct execution without redirect
uv run pytest tests/ -x --tb=short -v

# ❌ Piping to a filter (hangs — the process keeps stdin open)
npx vitest run | Select-String "FAIL"
uv run pyright packages/ 2>&1 | findstr "Error"

# ❌ Backslash receipts path in the Bash tool — strips to `C:Temp{{PROJECT_NAME}}…` junk in the repo root
uv run pyright packages/ > <INVALID-BACKSLASH-TEMP-PATH> 2>&1
```

> Note: `> <file> 2>&1` is the **correct** redirect in bash — it is only an anti-pattern when piped to a filter or paired with a backslash path. In PowerShell, prefer `*>` (captures all six streams).

## When to Skip

This skill may be skipped ONLY for:
- `rg` searches (lightweight, no buffer risk)
- `Get-Content` / `Test-Path` (read-only, instant)
- `(Get-Content <file>).Count` (single-value output)

All other commands — especially pytest, vitest, pyright, ruff, npm, git — MUST use the redirect pattern.
