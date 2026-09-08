---
name: cli-dispatch
description: Multi-CLI dispatch skill for Codex (Invoke-CodexDispatch.ps1), Claude CLI, and Antigravity CLI (agy.exe). Enforces the Codex PowerShell wrapper and the verified native-Windows agy -p stdout capture path.
---

# CLI Dispatch Skill

## Overview

Route specialized work to the right external CLI:

| Agent | Binary | Primary use | Dispatch form |
|-------|--------|-------------|---------------|
| **Codex** | `codex` via `tools/Invoke-CodexDispatch.ps1` | Validation / review / image gen | Wrapper only — never bare `codex exec` |
| **Claude** | `claude` | Creative writing / critical decisions | Direct `claude -p` (see workflow) |
| **agy** | `%LOCALAPPDATA%\agy\bin\agy.exe` | Data processing / Gemini Flash tasks | Direct `agy -p` with stdout capture |

For Codex, the wrapper manages parameter validation, least-privilege sandboxing, artifact structure, token usage parsing, and exit code propagation.

---

## Authentication & Detection

### Auth Mechanism

- **Claude CLI** reads the `ANTHROPIC_API_KEY` environment variable.
- **Codex CLI** uses user login state. To verify active credentials, use `codex login status` or `codex doctor`.
- For automated / non-interactive Codex dispatches, the `CODEX_API_KEY` environment variable can be set as a child process override.
- **agy (Antigravity CLI)** uses interactive login once (`agy` TUI / auth flow). Headless `-p` then uses silent keyring auth. Verify with `agy --version` (require **≥ 1.1.1**; current verified: **1.1.5**).

### Detection

Before dispatching, check active authentication status **and** Codex CLI version:
```powershell
# Verify Codex auth status
codex login status

# Verify Codex CLI version (wrapper also enforces this fail-closed)
codex --version
# Required: ≥ 0.145.0 (Invoke-CodexDispatch.ps1 -MinCodexCliVersion default)

# Verify agy binary + version (need ≥ 1.1.1 for Windows stdout + no stdin hang)
& "$env:LOCALAPPDATA\agy\bin\agy.exe" --version

```

**Codex version gate (mandatory):** `tools/Invoke-CodexDispatch.ps1` probes
`codex --version` **before** the long `exec` and exits nonzero if the parsed
semver is below `-MinCodexCliVersion` (default `0.145.0`) or is unparseable.
Agents must not bypass with `-SkipCodexVersionCheck` except for fixture tests /
explicit human-approved emergency. Upgrade path: `npm install -g @openai/codex`.

Never manually parse, edit, or attempt to repair the `auth.json` file. All authentication status changes should be handled through `codex login` / `codex logout` or interactive `agy` auth.

---

## Sandbox & Permissions

To maintain a secure development environment, dispatches default to the least-privilege sandbox needed for the task.

The `-Mode` parameter maps to the Codex sandbox levels:

| Mode | Codex Sandbox | Description |
|------|---------------|-------------|
| `ReviewReadOnly` | `workspace-write` + `writable_roots=["{{RECEIPTS_DIR}}"]` | Least-privilege review mode **when the Windows sandbox helper is healthy**. Intended to allow workspace + `{{RECEIPTS_DIR}}` writes; product/plan edits stay forbidden by the review prompt. |
| `ReviewWorkspace`| `workspace-write` + `writable_roots=["{{RECEIPTS_DIR}}"]` | Same sandbox boundary as `ReviewReadOnly`; use when the task may need broader in-workspace edits beyond a review handoff. |
| `FullAccess` | `danger-full-access` | **Required default for Windows Codex reviews that run shell / pytest / vitest and write P0 receipts under `{{RECEIPTS_DIR}}/`.** Bypasses the Windows sandbox helper. Requires `-FullAccessJustification` (min 20 characters). Product/plan edits remain forbidden by the review workflow prompt. |

> [!CAUTION]
> **Windows sandbox helper vs Temp access.** `ReviewReadOnly` / `ReviewWorkspace` still invoke Codex's Windows sandbox. On this host the helper commonly fails with `windows sandbox: helper_unknown_error: setup refresh had errors`, which blocks *all* shell tool use — including reads and `{{RECEIPTS_DIR}}` receipts — even though `writable_roots` lists Temp. When that happens (or whenever the review must produce Temp receipts), dispatch with `-Mode FullAccess` and a justification naming Temp/P0 receipts + sandbox-helper bypass. Do **not** treat `ReviewReadOnly` as sufficient for Temp on Windows.

### agy permissions (headless)

- Prefer persisted allow rules in `~/.gemini/antigravity-cli/settings.json`.
- Tools that still need interactive confirmation are **soft-denied** in `-p` mode (they do not hang on a prompt).
- Use `--dangerously-skip-permissions` only in a controlled workspace when the task must exercise tools without soft-denies.

## Artifact Layout & Retention

### Codex (wrapper)

The wrapper writes all outputs to a unique run directory: `{{RECEIPTS_DIR}}/dispatch/{dispatchId}/`.

#### Artifacts Generated

- `status.json`: Atomic run metadata (durations, exit code, redacted arguments, sizes).
- `final.md` or `final.json`: The final response from the agent.
- `stderr.txt`: Captured standard error diagnostics.
- `receipt.txt`: Text summary of the dispatch.
- `events.jsonl.gz`: Compressed event logs (only under `CompressOnSuccess` retention).

#### Retention Modes

- `CompressOnSuccess` (default): Compresses event logs to `.gz` on success and deletes the raw `.jsonl`.
- `Keep`: Retains all raw logs and diagnostics.
- `DeleteOnSuccess`: Deletes log and stderr files on successful execution, retaining only the status and final response.

### agy (direct stdout)

Write the redirected capture to a fixed receipt path (P0 redirect-to-file):

- `{{RECEIPTS_DIR}}/dispatch/agy-output.txt` — captured stdout/stderr from `*>`
- On hang/empty output: read `~/.gemini/antigravity-cli/log/cli-*.log` (latest) for MCP/auth stalls

---

## Stdin & Prompt Delivery

### Codex wrapper

To prevent command-line length limits on Windows (8191 characters), prompts must be supplied to the wrapper using one of:
1. `-PromptText`: For short, manual prompts.
2. `-PromptFile`: For large, generated prompts.

The wrapper automatically feeds the prompt content to Codex's stdin via the `-` argument, avoiding command-line truncation.

### agy (native Windows, ≥ 1.1.1)

Pass the prompt as a **CLI argument** to `-p` / `--print`. Do **not** pipe stdin (`$null |` is obsolete for agy ≥ 1.1.1 — that hang was fixed).

For long prompts that risk the Windows 8191 argv limit, write the prompt to a file and pass a short instruction that tells agy to read that file — still via `-p "<short prompt>"`, not via stdin.

### Invoking a CLI directly on macOS/Linux: close stdin

The wrappers already redirect stdin, so this does not apply to them. It applies when you
run a CLI agent yourself from a shell — a quick one-off, a script, a CI step:

```bash
# // turbo
codex exec --json -o "$OUT" - < "$PROMPT_FILE"      # prompt on stdin: fine, stdin ends at EOF

# // turbo
codex exec --json -o "$OUT" -p "short prompt" < /dev/null   # prompt in argv: close stdin
```

**Always give a non-interactive CLI either a real stdin that reaches EOF or `< /dev/null`.**
A CLI launched from an agent's shell inherits that shell's stdin, which never reaches EOF.
Anything the CLI decides to read — a confirmation, an auth code, a "press enter to
continue" — blocks forever on a descriptor no one will ever write to. There is no output
and no error; the dispatch simply never returns and the turn dies on timeout.

This is why the symptom looks like "the model is slow" rather than "the tool wants input",
and why the fix is a habit rather than a diagnosis: you cannot tell the two apart from the
outside, so close stdin every time and the failure mode stops existing. The Windows
equivalent is `< NUL`.

Corollary for background jobs: `&` does **not** close stdin. A backgrounded CLI without an
explicit redirect blocks the same way, and on some shells is stopped by `SIGTTIN` instead —
which looks identical from the caller's side.

---

## Web Search Integration

If a task requires web search (e.g. searching for API documentation, package versions, or online references), pass the `-UseSearch` switch to the wrapper.

- **`-UseSearch`**: Under the hood, this passes the `--search` switch to the Codex CLI. The older `--enable web_search` option is deprecated and has been retired.

---

## Codex Subagents

- Codex supports prompt-driven delegation and custom subagents using configuration settings.
- Use the interactive `/agent` command for subagent inspection.
- Subagents do NOT guarantee token savings (they often consume more tokens due to independent context loading). They are useful primarily for keeping noisy sub-tasks out of the coordinator's main context.
- The `--subagent` CLI flag is unsupported.
- **CSV Workflow**: The experimental `spawn_agents_on_csv` configuration allows spawning agent workers dynamically from a source CSV task sheet.
- **Subagent defaults when unset**:
  * `agents.max_threads` defaults to `6` concurrent open agent threads.
  * `agents.max_depth` defaults to `1`, allowing only the root thread to spawn direct children.
  * `agents.job_max_runtime_seconds` is optional; `spawn_agents_on_csv` falls back to `1800` seconds per worker when it is unset.

---

## Dispatch Templates

### Timeout / process-tree defaults

`Invoke-CodexDispatch.ps1` polls until `turn.completed`/`turn.failed` **and** a non-empty
`-o` final artifact, or until timeout:

| `ReasoningEffort` | Default `-TimeoutSec` |
|-------------------|----------------------:|
| `medium` | 900 (15m) |
| `high` | 1800 (30m) |
| `xhigh` | 2700 (45m) |
| `max` | 3600 (60m) |

Override with `-TimeoutSec <n>`. On timeout/hang the wrapper kills the **process tree**
(`taskkill /T`) so orphaned Codex/`node` children cannot keep writing after a failed
status. If a timeout happened before any terminal event, a short `-PostKillGraceSec`
(default 90) reparse can salvage a late `turn.completed` + final artifact.

#### Kind floor: the effort tier is not a size estimate

The table above answers "how hard should it think", which is a different question from
"how much does it have to read". A `medium` **execution** review inherits 900s, reads the
whole change plus its receipts, and dies mid-verdict — and the round is spent either way,
because the ledger counted a dispatch it permitted. So the kind carries a floor:

| Dispatch kind | Timeout floor | Effect |
|---|---:|---|
| `execution`, `multi-handoff` | 2700 (45m) | Raises a derived timeout below the floor |
| `plan`, `discovery`, `handoff` | — | Effort default stands |

- The kind is **read from the loop**, not from a flag: the wrapper takes the mode the
  ledger recorded at `begin`. `-Kind <kind>` is an optional *assertion*, and a `-Kind`
  that disagrees with the loop is exit 1 (`kind_mismatch`) — that disagreement usually
  means the dispatch is aimed at the wrong loop, whose budget is the one being spent.
- `-Kind` with `-NonReviewDispatch` is exit 1 (`kind_not_applicable`).
- An explicit `-TimeoutSec` below the floor is **honoured** — small execution reviews
  exist — but the wrapper says so on stdout, because a truncated verdict is
  indistinguishable from a reviewer that found nothing.
- The resolved kind and timeout are printed before the gate returns, so
  `-GateOnly` reports them without paying for a dispatch, and `status.json` records
  `dispatch_kind` + `timeout_floor_applied`.
- If the ledger's `evaluate` output does not name a mode, the wrapper exits **3**
  (`ledger_mode_unavailable`) rather than guessing a kind. The wrapper and
  `tools/review_ledger.py` ship as a pair; update them together.

### Receipts Authoritative (what the dispatcher owes the reviewer)

An execution review must not re-run the full suite to corroborate a receipt it was already
given — that is the reviewer-side rule, and it lives in
[`execution-critical-review.md`](../../workflows/execution-critical-review.md) §Receipts
Authoritative. The dispatching session's half of it:

1. **Put the receipts in the prompt** — path, command, exit code, and the counts. A
   reviewer told only "tests pass" has nothing to read and will re-run the suite.
2. **Leave them readable.** Receipts live under `{{RECEIPTS_DIR}}`, which is what
   `ReviewReadOnly`/`ReviewWorkspace` list in `writable_roots`; on Windows the sandbox
   helper commonly blocks reads there anyway, which is the other reason `FullAccess` is
   the working default for reviews on this platform.
3. **Do not pre-emptively grant a bigger timeout instead.** If a review needs the suite
   re-run, the receipt was inadequate; fix the receipt.

For execution reviews with GUI E2E: prefer trusting a post-edit Playwright receipt over
re-launching Electron inside Codex (see `execution-critical-review.md`).

### Routine Code Review (Windows — FullAccess for Temp receipts)

```powershell
powershell -NoProfile -File tools/Invoke-CodexDispatch.ps1 `
  -LoopId review-core-index-2026-09-07 `
  -Mode FullAccess `
  -FullAccessJustification "Windows Codex review needs shell + {{RECEIPTS_DIR}} P0 receipts; sandbox helper blocks ReviewReadOnly" `
  -ReasoningEffort medium `
  -PromptText "Review the changes in packages/core/src/index.ts for potential logic errors."
```

### Structured Review Verdict (JSON Output)

```powershell
powershell -NoProfile -File tools/Invoke-CodexDispatch.ps1 `
  -LoopId review-core-index-2026-09-07 `
  -Kind execution `
  -Mode FullAccess `
  -FullAccessJustification "Windows Codex review needs shell + {{RECEIPTS_DIR}} P0 receipts; sandbox helper blocks ReviewReadOnly" `
  -ReasoningEffort high `
  -OutputSchema .agent/schemas/review-verdict.schema.v2.json `
  -PromptFile {{RECEIPTS_DIR}}/dispatch/review-prompt.txt
```

## The review-loop bound: `-LoopId` or `-NonReviewDispatch`

> [!IMPORTANT]
> **Both wrappers require exactly one of `-LoopId <id>` / `-NonReviewDispatch`.** There is
> no default, and omitting both is exit 1 (`loop_id_required`). This is deliberate: a review
> dispatch with no loop is an unbounded review loop, and if the flag had a default then "the
> caller forgot" and "this genuinely is not a review" would produce identical behaviour with
> no way to tell them apart afterwards.

With `-LoopId`, the wrapper runs `tools/review_ledger.py evaluate` **before** resolving a
model or launching the CLI — the cheapest moment to refuse a round is before it costs
anything. Open the loop once, then pass the same id every round:

```bash
export RECEIPTS_DIR=/absolute/path/outside/the/repo   # required; no default (F3/F3b)
python tools/review_ledger.py begin \
  --loop-id review-core-index-2026-09-07 \
  --review-mode execution \
  --producer builder-agent          # this agent may never author a verdict in this loop
```

After each dispatch, record the verdict so the next round is counted:

```bash
python tools/review_ledger.py record \
  --loop-id review-core-index-2026-09-07 \
  --verdict-file "$RECEIPTS_DIR/dispatch/<id>/final.json"
```

`-GateOnly` consults the ledger and exits without dispatching — use it to find out whether a
round is permitted before spending one.

**Wrapper exit codes for this gate:**

| Code | Meaning | What to do |
|---|---|---|
| `0` | A round is permitted (or `-GateOnly` and the gate passed) | Proceed |
| `1` | Neither flag given, both given, a malformed `-LoopId`, or a `-Kind` that contradicts the loop / accompanies `-NonReviewDispatch` | Fix the invocation. On `kind_mismatch`, check *which loop* you are dispatching against before changing the flag |
| `9` | **The ledger refused this round.** A decision, not an error | Apply the specific relief its message names, or escalate to a human |
| `3` | The gate could not be evaluated — no `python3`/`python`, `review_ledger.py` absent, or its output did not name the loop's mode (`ledger_mode_unavailable`) | Fix the tooling; the wrapper and the ledger are one pair. **Never read 3 as a pass**: "could not check" is not "checked and permitted" (V5/V31) |

`9` is kept distinct from `1` and `3` because "the loop is over" and "the tool broke" call for
opposite responses, and merging them is how a repo comes to believe a refused round was
merely a flaky failure worth retrying.

**Do not answer a `9` by re-running with `-NonReviewDispatch`.** That flag is recorded in
`status.json` as `ledger_gate: bypassed-non-review`, so the bypass is auditable — a receipt
marked that way whose prompt is plainly a review is the signal that a stop was routed around.
The reliefs that actually apply are named in the refusal text: `grant` for a round budget,
`relieve` for one mechanism, and for a scaffolding stop, ending the loop.

See [`.agent/docs/verification-principles.md`](../../docs/verification-principles.md) V41
(the count belongs on disk) and V43 (a loop bounded only by volume converges on its own
instrumentation) for why the stops are shaped this way.

### agy — Data Processing / Gemini Flash (stdout capture)

**Prerequisite:** `agy --version` ≥ `1.1.1` (verified path: `1.1.5`). Binary: `$env:LOCALAPPDATA\agy\bin\agy.exe`.

**Smoke test (expect exit 0 and stdout `PONG` in a few seconds):**

```powershell
New-Item -ItemType Directory -Force -Path {{RECEIPTS_DIR}}/dispatch | Out-Null
$agyPath = "$env:LOCALAPPDATA\agy\bin\agy.exe"
& $agyPath -p "Reply with exactly PONG" *> {{RECEIPTS_DIR}}/dispatch/agy-output.txt
$code = $LASTEXITCODE
Get-Content {{RECEIPTS_DIR}}/dispatch/agy-output.txt
exit $code
```

**Task dispatch (capture model response from stdout):**

```powershell
New-Item -ItemType Directory -Force -Path {{RECEIPTS_DIR}}/dispatch | Out-Null
$agyPath = "$env:LOCALAPPDATA\agy\bin\agy.exe"
$out = "{{RECEIPTS_DIR}}/dispatch/agy-output.txt"
Remove-Item $out -Force -ErrorAction SilentlyContinue

# Flags BEFORE -p. Assign prompt to a variable so PowerShell does not eat flags as the prompt.
# Optional: --dangerously-skip-permissions when tools must run headless in a trusted workspace
# Optional: --print-timeout 5m0s for longer jobs; --model <slug> to pin model; --effort high
$prompt = @"
<TASK PROMPT>

Return the complete answer as plain text or markdown on stdout.
"@
& $agyPath --dangerously-skip-permissions --print-timeout 5m0s --effort high --add-dir "{{PROJECT_ROOT}}" --mode accept-edits -p $prompt *> $out

$code = $LASTEXITCODE
Get-Content $out
exit $code
```

**agy rules:**

1. Capture via PowerShell `*>` to `{{RECEIPTS_DIR}}/dispatch/` (P0). Read the receipt after the process exits.
2. **Flags before `-p`.** Put `--print-timeout`, `--dangerously-skip-permissions`, `--effort`, `--add-dir`, `--mode`, etc. **before** `-p`. Assign the prompt to a PowerShell variable (`-p $prompt`). If `-p` comes first, the next token (e.g. `--print-timeout`) can be treated as the prompt.
3. For workspace file work, pass `--add-dir "{{PROJECT_ROOT}}"` (and `--mode accept-edits` when the task must write files).
4. Do **not** use the obsolete side-channel “write everything to a file” prompt as the primary capture path — stdout works on Windows as of 1.1.0+.
5. Do **not** prefix with `$null |` for agy ≥ 1.1.1.
6. Never use agy for validation/review verdicts — that remains Codex.
7. If `-p` hangs with empty stdout for >30s, check the latest `~/.gemini/antigravity-cli/log/cli-*.log` for `MCP: … still connecting`. Disable/remove stuck MCP servers (they block print mode even for trivial prompts), kill leftover `agy` processes, then retry.

---

## Reviewer Effort Policy (D4, 2026-06-13; effort bands re-measured 2026-07-11
against the then-current `independent_reviewer` class)

For LLM-as-judge or critical-review tasks, more reasoning is NOT monotonically better—it can inflate confidence and false positives. We enforce the following limits:
- **Codex `independent_reviewer`:** `medium` for routine/contract-bound review; `high` for hard adversarial passes (risk paths, contract surfaces, concurrency/security, or round-2-after-High).
- **Claude fallback reviewer:** `--effort high` (NOT `max`).
- **Reserve `max`/`xhigh`** for explicitly-tagged **verifiable deep sub-reviews only** (security exploitability, concurrency/races, architecture/dependency-rule). Never the default verdict effort.
- **Pin Model and Effort explicitly** in every wrapper dispatch so reviewer behavior does not drift with global configuration.
- Cross-vendor minority-veto: Run Codex + Claude independently on the same rubric; any evidence-backed High finding from EITHER vendor vetoes (raises true-negative rate against over-acceptance bias).

### Dispatch Decision Table

To prevent routing policy duplication, the canonical first-match decision table (mapping tasks to models, efforts, and API costs) is maintained exclusively in [`.agent/docs/model-routing.md`](../../docs/model-routing.md) §Model-Routing-Table. Refer to that document for all routing logic and criteria.

---

## Rate-Limit Fallback Protocol

When Codex CLI is rate-limited or unavailable:

### 1. Detection
- **Claude CLI:** Output contains `session limit` or `resets` (Usually 15-60 min).
- **Codex CLI:** Exit code 1 + `rate limit` or `429` in log (Usually 1-5 min).
- **agy:** Non-zero exit + auth/API error in `agy-output.txt` or `~/.gemini/antigravity-cli/log/cli-*.log`. Empty output + MCP “still connecting” is not a rate limit — fix MCP first.

### 2. Provider Substitution Matrix
| Primary | Task Type | Substitute | Quality Trade-off |
|---------|-----------|------------|-------------------|
| Codex `independent_reviewer` | Validation review (surface-level) | **agy / Gemini** (surface only) or Gemini web | **First fallback for surface work.** Cross-vendor; NOT for deep-infra/troubleshooting reviews. |
| Codex `independent_reviewer` | Validation review (deep/infra) | **A different-vendor CLI you have configured** | Cross-vendor is the requirement. Run at high effort. |
| Codex `independent_reviewer` | Validation review | Same model family via web (manual) | Same family; no file access, requires manual copy-paste of results. Still cross-*context*, so it beats self-review. |
| Any | Validation review | ~~The coordinator's own vendor~~ | **PROHIBITED.** Not a rung. See §Same-vendor self-review below. |

#### Same-vendor self-review is PROHIBITED

The reviewer must not be the vendor that authored the work. There is no "last resort"
rung where the coordinator reviews itself at higher effort — that is not a weaker review,
it is a **different kind of thing** wearing a review's name, and it launders an
unreviewed artifact into one marked `approved`. When every cross-vendor rung is
unavailable, the escalation is the **human handoff path in §0**, which is a real terminal
state. Effort flags do not buy independence.

### 3. Fallback Steps
1. **Advance to the next eligible cross-vendor reviewer rung** (surface-only rungs stay surface-only).
2. **If all cross-vendor rungs are exhausted:** Save the prompt to a file at `{{RECEIPTS_DIR}}/dispatch/<provider>-web-prompt.md`.
3. **Present to user (HARD STOP):** Inform them all rungs are rate-limited and offer manually submitting to a web interface or setting a timer to retry.
4. **Collect results:** User pastes the web response into `{{RECEIPTS_DIR}}/dispatch/<provider>-web-response.md`.

### 4. Capability and Round-Cap Constraints
- **Capability / No-Dispatch check**: If `can_dispatch_external_reviewer == no`, write the complete reviewer prompt to `{{RECEIPTS_DIR}}/dispatch/<provider>-web-prompt.md`, report the manual external submission requirement as a human-decision gate, and stop. Never self-review or substitute a local approval verdict.
- **Round-cap behavior**: The plan review correction loop is capped at 3 rounds. When the cap is reached, it is a HARD STOP. Do NOT bypass the gate; present the current state to the user and wait for explicit human instructions.

---

## Cross-Platform Dispatch

Two Codex wrappers ship with the same contract:

| Wrapper | Host | When to use |
|---------|------|-------------|
| `tools/Invoke-CodexDispatch.ps1` | Windows (native); macOS/Linux under `pwsh` | Default when PowerShell 7 is available |
| `tools/Invoke-CodexDispatch.sh` | macOS/Linux bash | When `pwsh` is unavailable or you prefer POSIX |

Do not call bare `codex exec` for reviews — use one of the wrappers.

| Host | Shell for wrapper | Redirect form | Sandbox probe | Notes |
|------|-------------------|---------------|---------------|-------|
| Windows | `pwsh` (or Windows PowerShell for `*>` only) | `*> {{RECEIPTS_DIR}}/…` | Windows sandbox helper (see §Sandbox) | Prefer `pwsh` when the child needs modern cmdlets (`Get-FileHash`) |
| macOS | `pwsh` **or** `bash tools/Invoke-CodexDispatch.sh` | `*>` inside `pwsh`; native zsh/bash uses `> file 2>&1` | `codex sandbox macos --log-denials <cmd>` | See [`.agent/docs/macos-setup.md`](../../docs/macos-setup.md) for Tahoe / Gatekeeper / `#23802` preflight |
| Linux | `pwsh` **or** `bash tools/Invoke-CodexDispatch.sh` | same as macOS | platform sandbox mode for the host | Receipts dir must be in `writable_roots` |

**macOS/Linux — PowerShell wrapper** (exact-evidence class → unfiltered receipt):

```bash
# From the adopter repo root, under pwsh:
pwsh -NoProfile -File tools/Invoke-CodexDispatch.ps1 \
  -LoopId "$LOOP_ID" \
  -Mode ReviewReadOnly \
  -ReasoningEffort medium \
  -OutputSchema .agent/schemas/review-verdict.schema.v2.json \
  -PromptFile "$RECEIPTS_DIR/dispatch/review-prompt.txt" \
  > "$RECEIPTS_DIR/dispatch/review-run.txt" 2>&1
code=$?
tail -n 40 "$RECEIPTS_DIR/dispatch/review-run.txt"
exit $code
```

**macOS/Linux — POSIX wrapper** (no `pwsh` required):

```bash
chmod +x tools/Invoke-CodexDispatch.sh
tools/Invoke-CodexDispatch.sh \
  --LoopId "$LOOP_ID" \
  --Mode ReviewReadOnly \
  --ReasoningEffort medium \
  --OutputSchema .agent/schemas/review-verdict.schema.v2.json \
  --PromptFile "$RECEIPTS_DIR/dispatch/review-prompt.txt" \
  > "$RECEIPTS_DIR/dispatch/review-run.txt" 2>&1
code=$?
tail -n 40 "$RECEIPTS_DIR/dispatch/review-run.txt"
exit $code
```

> [!NOTE]
> `$code` here can be `9` — the ledger refused the round. Treat that as a terminal decision,
> not a retryable failure; see the exit-code table above. A retry loop that treats every
> non-zero code the same will hammer a closed loop forever.

Before the first real review on macOS, prove the receipts directory is writable inside the Seatbelt profile:

```bash
codex sandbox macos --log-denials -- sh -c "echo ok > \"$RECEIPTS_DIR/sandbox-probe.txt\""
```

> Full install, auth, `CODEX_HOME`, Seatbelt mapping, shell-translation table, and known
> blockers live in [`.agent/docs/macos-setup.md`](../../docs/macos-setup.md). Do not invent
> a second macOS contract here.

---

## Routing Policy

For details on model assignments and fallback reviewer rungs, refer to the canonical routing policy in [`.agent/docs/model-routing.md`](../../docs/model-routing.md).
