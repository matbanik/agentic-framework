# macOS Setup for Agentic Dispatch

> [!WARNING]
> **UNVERIFIED on hardware.** This document was authored from primary sources and
> issue trackers during planning/execution of the agentic-framework package
> refresh (2026-08-04 / 2026-08-05). It has **not** been run end-to-end on a
> physical macOS Tahoe machine in this project. Treat every claim as
> research-backed guidance pending a live smoke (see §Smoke checklist). Flip
> this banner only after a real hardware run produces receipt files.

This guide is the macOS companion to `AGENTS.md` §PRIORITY 0 and
`cli-dispatch/SKILL.md` §Cross-Platform Dispatch. Windows adopters can ignore it.

---

## 1. Install Codex CLI

Three supported paths (OpenAI Codex README, retrieved 2026-08-05):

```bash
# Homebrew cask (macOS)
brew install --cask codex

# npm global
npm install -g @openai/codex

# Standalone installer (macOS/Linux)
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

Prefer a path you can upgrade and version-pin. After install:

```bash
codex --version   # wrapper requires ≥ 0.145.0 by default
which codex
```

Sources:
- https://github.com/openai/codex (Quickstart / package-manager section)
- https://developers.openai.com/codex/concepts/sandboxing

---

## 2. Authentication

```bash
codex login          # interactive ChatGPT / API login
codex login status   # verify active credentials
codex doctor         # environment health
```

For non-interactive / CI-style child processes, set `CODEX_API_KEY` as a
**child-process override** only. Do **not** hand-edit `~/.codex/auth.json` —
that rule matches the packaged `cli-dispatch/SKILL.md` auth gate.

Sources:
- Packaged `cli-dispatch/SKILL.md` §Authentication & Detection (Local Canon)
- OpenAI Codex CLI auth flow (ChatGPT sign-in / API key)

---

## 3. `CODEX_HOME` footgun

Default home is `~/.codex`. Codex canonicalizes `$CODEX_HOME` and **errors if
the path does not exist** (`find_codex_home()` in `codex-rs/core/src/config.rs`).
When scripting:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_HOME"
```

Never point `CODEX_HOME` at a path you have not created.

Source: openai/codex `codex-rs/core/src/config.rs` (`find_codex_home` canonicalize-or-error behavior).

---

## 4. Sandbox model (Apple Seatbelt)

On macOS 12+, Codex enforces the sandbox with **Apple Seatbelt** via the
hard-coded helper `/usr/bin/sandbox-exec`
(`MACOS_PATH_TO_SEATBELT_EXECUTABLE`).

Framework wrapper mode → Codex sandbox mapping:

| Wrapper `-Mode` | Codex sandbox | Notes |
|-----------------|---------------|-------|
| `ReviewReadOnly` | `workspace-write` + `writable_roots` | Least privilege when Seatbelt is healthy |
| `ReviewWorkspace` | `workspace-write` + `writable_roots` | Broader in-workspace edits |
| `FullAccess` | `danger-full-access` | Requires `-FullAccessJustification` (≥ 20 chars) |

Probe denials before trusting a review run:

```bash
codex sandbox macos --log-denials -- sh -c 'echo ok'
# legacy alias: codex debug seatbelt …
```

Sources:
- https://developers.openai.com/codex/concepts/sandboxing
- openai/codex `docs/sandbox.md` (Seatbelt / `sandbox-exec`)

> `sandbox-exec` is Apple-private and has been deprecated since Sierra. Long-term
> uncertainty applies to any tool built on it; container isolation is the stronger
> boundary if the adopter needs it.

---

## 5. Receipts directory and `writable_roots`

There is no macOS analogue of `{{RECEIPTS_DIR}}`. Use:

```bash
export RECEIPTS_DIR="${RECEIPTS_DIR:-$HOME/.cache/{{PROJECT_NAME}}/receipts}"
mkdir -p "$RECEIPTS_DIR"
```

`workspace-write` covers the workspace cwd and `/tmp`. On macOS, `$TMPDIR` is a
**per-user** path under `/var/folders/...`, **not** `/tmp`. If receipts live under
`$HOME/.cache/...` (recommended), that path **must** be listed in
`writable_roots` or Seatbelt will deny the P0 receipt write.

Verify with Codex `/status` (interactive) or the sandbox probe writing a file
into `$RECEIPTS_DIR`.

Sources:
- https://developers.openai.com/codex/concepts/sandboxing (`writable_roots`)
- macOS `$TMPDIR` behavior (per-user `/var/folders`)

---

## 6. Protected paths

Even inside `writable_roots`, `.git` and `.codex` stay read-only. That means
`git commit` from inside a sandboxed agent may still need approval — which
aligns with this framework's never-auto-commit rule.

Source: openai/codex sandbox docs (protected paths).

---

## 7. Recommended review profile (`$CODEX_HOME/review.config.toml`)

As of Codex CLI **≥ 0.134**, profile-specific settings live in a **separate file**
`$CODEX_HOME/<profile-name>.config.toml` — not under `[profiles.<name>]` inside the
base `config.toml`. The wrapper targets Codex **≥ 0.145.0**, so use the separate-file
form. Project-local `.codex/config.toml` still cannot override profile selection /
`model_provider` at the user level.

Create `$CODEX_HOME/review.config.toml` (example):

```toml
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[sandbox_workspace_write]
writable_roots = ["/Users/YOU/.cache/{{PROJECT_NAME}}/receipts"]
network_access = false
```

Invoke with the profile name (file stem):

```bash
codex exec --profile review "…"
# Prefer --strict-config when proving the selected profile + writable root:
codex exec --strict-config --profile review "echo profile-smoke"
# or via the wrapper, which sets equivalent flags for -Mode Review*
```

Sources:
- https://developers.openai.com/codex/config-basic (profile files under `$CODEX_HOME`)
- https://developers.openai.com/codex/config-sample (`[sandbox_workspace_write] network_access`)
- https://developers.openai.com/codex/config-reference (`sandbox_workspace_write.network_access`)

---

## 8. Shell / P0 translation table

Install PowerShell 7 via the Homebrew **formula** (not the cask) **or** use the
POSIX wrapper (`tools/Invoke-CodexDispatch.sh`) and skip `pwsh` entirely for Codex
dispatch:

```bash
# Option A — PowerShell 7 (still useful for other Windows-authored examples):
# If an old cask is present:
brew uninstall --cask powershell
brew uninstall --cask powershell@preview   # if installed

brew install powershell   # formula — builds/links pwsh
pwsh --version

# Option B — no pwsh: use the bash companion (same dispatch contract):
chmod +x tools/Invoke-CodexDispatch.sh
tools/Invoke-CodexDispatch.sh --help
```

As of the research window (2026-08): Homebrew publishes a **`tahoe` arm64
bottle**; current stable formula track reports **7.6.x** and depends on
`dotnet`. Microsoft Learn lists **macOS 26 (Tahoe) x64 + Arm64** as supported
platforms for PowerShell 7.

| Windows / PowerShell form | macOS / Linux under `pwsh` | Native zsh/bash |
|---------------------------|----------------------------|-----------------|
| `*> {{RECEIPTS_DIR}}/out.txt` | `*> $env:RECEIPTS_DIR/out.txt` (inside `pwsh`) | `> "$RECEIPTS_DIR/out.txt" 2>&1` |
| `taskkill /T /F /PID $pid` | `Stop-Process -Id $pid -Force` (pwsh) or `pkill -TERM -P $pid` | `pkill -TERM -P $pid` / `kill -- -$pgid` |
| `Get-FileHash -Algorithm SHA256` | `Get-FileHash` (pwsh) or `shasum -a 256` | `shasum -a 256` |
| `cmd.exe /c …` | `/bin/sh -c '…'` | `/bin/sh -c '…'` |
| `Invoke-CodexDispatch.ps1` | `pwsh -File tools/Invoke-CodexDispatch.ps1 …` | `tools/Invoke-CodexDispatch.sh --Mode …` |

Sources:
- https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-macos
- https://github.com/MicrosoftDocs/PowerShell-Docs (alternate install / Homebrew formula)
- Homebrew `powershell` formula bottle metadata (tahoe arm64)

---

## 9. ⚠️ Blockers

### 9a. Homebrew PowerShell **cask** Gatekeeper deadline — **2026-09-01**

Homebrew is disabling casks that fail macOS Gatekeeper checks on
**2026-09-01**. The `powershell` / `powershell@preview` **casks** carry that
deprecation. Prefer the **formula** (`brew install powershell`) or a
Microsoft-signed `.pkg`. If you manually download a `.pkg`:

```bash
xattr -rd com.apple.quarantine /path/to/powershell.pkg
```

Sources:
- https://github.com/PowerShell/PowerShell/issues/26629
- https://github.com/Homebrew/brew/issues/20755 (Gatekeeper cask disable policy)
- https://github.com/Homebrew/homebrew-cask/pull/251326 (`powershell` cask → formula migration)

### 9b. openai/codex **#23802** — `_dyld_start` hang on Tahoe 26.4.1

**Symptom:** any `codex` subcommand (including `--version` / `--help`) hangs
forever. `sample` shows 100% of samples in `_dyld_start`; **zero bytes** to
stdout/stderr. Reported on macOS **26.4.1 (Tahoe, build 25E253)** arm64 with
Homebrew cask builds (reproduced on 0.130.0 / 0.132.0 in the original report;
related Gatekeeper / cask reports continue under nearby issues).

**Failed workarounds** (do not burn hours re-trying these as first moves):

| Tried | Result |
|-------|--------|
| `pkill` / kill-and-retry | Hang returns |
| `xattr -d com.apple.quarantine` | Often insufficient on Tahoe (launch-block may persist beyond the xattr) |
| `brew upgrade` alone | May not clear inode/CDHash-keyed blocks |
| `DYLD_USE_CLOSURES=0` | Env var removed in macOS 26 |
| `DYLD_SHARED_REGION=avoid` | Does not reach `main()` |

**Preflight:**

```bash
# Must return promptly with a version string. If it hangs >5s with no output,
# you are in #23802 / Tahoe Gatekeeper territory — stop and switch install path.
codex --version
```

**Fallbacks when the cask binary hangs:**

1. `npm install -g @openai/codex` and re-test `--version`
2. Standalone `curl -fsSL https://chatgpt.com/codex/install.sh | sh`
3. GitHub release tarball for `aarch64-apple-darwin` / `x86_64-apple-darwin`
4. Copy the binary to a **new path** (new inode) and invoke that copy — reported
   workaround class for Tahoe inode-keyed launch-block caches
5. Container isolation if host Gatekeeper remains hostile

Sources:
- https://github.com/openai/codex/issues/23802
- https://github.com/openai/codex/issues/17447 (related Homebrew-cask + Gatekeeper `_dyld_start` report)

---

## 10. Adopter smoke checklist

Run in order. Stop on the first failure and fix before continuing.

1. `uname -m && sw_vers` — record arch + macOS version (note if Tahoe 26.x).
2. Either `brew install powershell` (formula) → `pwsh --version`, **or** skip pwsh and use `tools/Invoke-CodexDispatch.sh`.
3. Install Codex via preferred path → `codex --version` returns in <5s.
4. `codex login status` (or `codex doctor`) — auth healthy.
5. `mkdir -p "$HOME/.cache/{{PROJECT_NAME}}/receipts"` and export `RECEIPTS_DIR`.
6. Add that path to `writable_roots` under `[sandbox_workspace_write]` in `$CODEX_HOME/review.config.toml` (same file as §7 — not a nested `[profiles.review.*]` table).
7. `codex sandbox macos --log-denials -- sh -c "echo ok > \"$RECEIPTS_DIR/sandbox-probe.txt\""`.
8. Confirm `sandbox-probe.txt` exists.
9. From the adopter repo root, run a real wrapper smoke (**pick one**):

```powershell
# Option A — pwsh
pwsh -NoProfile -File tools/Invoke-CodexDispatch.ps1 `
  -Mode ReviewReadOnly `
  -ReasoningEffort medium `
  -OutputSchema .agent/schemas/review-verdict.schema.json `
  -PromptFile "$env:RECEIPTS_DIR/dispatch/smoke-prompt.txt" `
  *> "$env:RECEIPTS_DIR/dispatch/smoke-run.txt"
$code = $LASTEXITCODE
Get-Content "$env:RECEIPTS_DIR/dispatch/smoke-run.txt" | Select-Object -Last 40
exit $code
```

```bash
# Option B — POSIX (no pwsh)
chmod +x tools/Invoke-CodexDispatch.sh
tools/Invoke-CodexDispatch.sh \
  --Mode ReviewReadOnly \
  --ReasoningEffort medium \
  --OutputSchema .agent/schemas/review-verdict.schema.json \
  --PromptFile "$RECEIPTS_DIR/dispatch/smoke-prompt.txt" \
  > "$RECEIPTS_DIR/dispatch/smoke-run.txt" 2>&1
code=$?
tail -n 40 "$RECEIPTS_DIR/dispatch/smoke-run.txt"
exit $code
```

10. Keep the smoke receipts; they are the hardware-validation evidence that
    clears the UNVERIFIED banner at the top of this file.

---

## Cross-references

- `AGENTS.md` §PRIORITY 0 — `native_shell` resolution and redirect forms
- `.agent/docs/harness-profiles.md` — shell-capability / harness flags
- `.agent/skills/terminal-preflight/SKILL.md` — non-Windows redirect checklist
- `.agent/skills/cli-dispatch/SKILL.md` §Cross-Platform Dispatch
- `ADOPTION-GUIDE.md` — platform-selection step before the first shell command
