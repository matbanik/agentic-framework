# Output and Evidence Policy

This is the single authority for command-output routing. `AGENTS.md`, command guides,
templates, and skills reference this file instead of maintaining separate bypass lists.

The file has two layers, and only one of them is conditional:

| Layer | Applies |
|---|---|
| **Receipt discipline** (§Receipt pattern, §Exact-evidence bypass) | **Always.** Independent of any token-optimizer tool. |
| **RTK routing** (§RTK classification) | **Only when RTK is installed.** Adopters without RTK skip §RTK classification entirely — see §No-RTK adopters. |

An adopter who has never heard of RTK must still be able to satisfy
`AGENTS.md §PRIORITY 0` from this file. If you find a P0 row that cannot be
satisfied without RTK, that row is a defect — report it.

## Receipt pattern

Every command, on every route, obeys the same four beats:

1. Capture **every** stream to a file under `{{RECEIPTS_DIR}}/`. PowerShell: `*> file`.
   bash/posix: `> file 2>&1`. Always use forward slashes in cross-shell paths.
2. Save the exit status **immediately** after the process, before any other command
   (`$code=$LASTEXITCODE` / `code=$?`). Reading the receipt first clobbers it.
3. Read the receipt.
4. `exit $code` — propagate, never swallow.

Never pipe a long-running process into a filter: the filter's exit status replaces the
process's, and a saturated pipe can hang the session. Read the receipt after the
process finishes.

## Exact-evidence bypass

Whenever correctness depends on any of these classes, the **unfiltered receipt is the
canonical evidence**, and no summarizing/filtering layer may stand in for it:

- empty output or proof of zero matches;
- exact counts, exact order, or exact diffs;
- machine-readable JSON, schema, or another byte/field contract;
- security or authentication results;
- exit propagation or multi-command fail-fast behavior;
- optimization baseline measurements, benchmark inputs, or token/latency comparisons.

Read a compact view *separately*, after preserving the raw receipt. A filtered view or
a tee file is not canonical proof for a bypass class. **Never overwrite the raw receipt
with the compact view.**

This list is the reason the file exists, and it is tool-independent: it holds whether
your compact view comes from RTK, `head`, `Select-Object`, or a hand-written summary.

## Commands that may skip the receipt

Defined here and **only** here, because the skip list and the bypass list above are one
rule read from two ends, and they were previously maintained in two files that disagreed.

A command may run unredirected when **both** hold:

1. It cannot saturate a terminal — a bounded, near-instant read. In practice:
   `Get-Content` / `Test-Path` / `(Get-Content <file>).Count`, and a `rg` search whose
   output you are about to read yourself.
2. **Its result is not evidence for anything in §Exact-evidence bypass.**

Condition 2 is the one the old skip list omitted, and omitting it inverted the policy
for the single most receipt-critical command in the package. "`rg` searches" sat on a
blanket skip list, yet the most common reason to run `rg` in a gate is to prove **zero
matches** — the first bypass class. So the command whose whole contract was "no output
means clean" was exempted from having to keep the output that shows it ran at all. An
`rg` that exits `127` because it is a shell function in your profile prints nothing and
looks identical to a clean sweep (see `terminal-preflight/SKILL.md` §Environment
Pre-Flight).

So: an `rg` you are reading with your own eyes may skip the receipt. An `rg` whose
**absence of matches you intend to cite** — in a verdict, a gate, a closeout artifact —
is a bypass class and gets a receipt plus a propagated exit status like anything else.
Everything not covered by both conditions above, and every long-running command
(`pytest`, `vitest`, `pyright`, `ruff`, `npm`, `git`), uses §Receipt pattern.

## No-RTK adopters

If you have no token-optimizer tool, you are done after §Receipt pattern and
§Exact-evidence bypass. Concretely:

- Run the command directly, redirected, per §Receipt pattern.
- Treat **every** command as the `proxy` class below — unfiltered receipt is canonical.
- Skip the classification step; there is nothing to classify between.
- `AGENTS.md`'s "prefix with RTK" row reads as "use your verified compact route, if you
  have one" — with no such tool, the direct redirected command *is* the route.

```bash
pytest tests/ -x --tb=short -v > {{RECEIPTS_DIR}}/pytest.txt 2>&1; code=$?; tail -40 {{RECEIPTS_DIR}}/pytest.txt; exit $code
```

## RTK classification

**Applies only if RTK is installed.** Prefer a verified native subcommand such as
`rtk git status`, `rtk pytest`, `rtk read`, or `rtk grep`. RTK output is a compact
operator view; it is evidence only when the contract depends on summarized failures and
the command/filter pair has a passing command-matrix test.

Unsupported commands use `rtk proxy <command>`. Do not rely on pass-through-looking
forms such as `rtk uv ...`, `rtk npx ...`, or `rtk powershell ...`.

Before execution, classify the command as one of:

1. `native`: a command-matrix-tested RTK subcommand whose filtered semantics satisfy the
   evidence need;
2. `proxy`: unsupported command **or any exact-evidence bypass class**;
3. `explicit bypass`: debugging only, documented with the reason and still redirected.

An unclassified command fails preflight. If a native filter changes exit status, hides a
required failure, or reports an impossible state, preserve the receipt, switch to
`rtk proxy`, and add the case to the command-matrix tests.

```powershell
rtk proxy uv run pytest tests/tooling/test_contract.py -x --tb=short -v *> {{RECEIPTS_DIR}}/contract-raw.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/contract-raw.txt | Select-Object -Last 40; exit $code
```

> RTK's own redirect is **not** a substitute for §Receipt pattern. Where a hook rewrites
> commands, verify that it does not rewrite the P0 redirect — if it does, the receipt is
> filtered and no longer canonical for a bypass class.

### Project-local filters are a trust boundary

**Applies only if RTK is installed and your repo carries a `.rtk/filters.toml`.**

A project-local filter decides what a receipt says. That makes it part of the evidence
chain, not a convenience: a filter that drops a line is indistinguishable, downstream,
from a command that never printed it. Treat activating one as a code review.

Activate in this order, and only this order:

1. **Read the file.** It must contain narrow, project-local filters with inline tests and
   **no command, environment, or secret capture**. A filter that reads the environment is
   exfiltration wearing a formatter's clothes.
2. **Trust its current hash**, so the thing verified is the thing you just read.
3. **Verify every inline test** (`rtk verify --require-all`).
4. Only then use it.

```bash
rtk proxy rtk trust > {{RECEIPTS_DIR}}/rtk-activate.txt 2>&1; code=$?
[ "$code" -eq 0 ] || exit $code
rtk proxy rtk verify --require-all >> {{RECEIPTS_DIR}}/rtk-activate.txt 2>&1; code=$?
if [ "$code" -ne 0 ]; then rtk proxy rtk untrust >> {{RECEIPTS_DIR}}/rtk-activate.txt 2>&1; exit $code; fi
rtk proxy rtk trust --list >> {{RECEIPTS_DIR}}/rtk-activate.txt 2>&1; code=$?
cat {{RECEIPTS_DIR}}/rtk-activate.txt; exit $code
```

Trust **before** verify is the whole point, and it is a V5 problem rather than a style
preference: RTK skips *untrusted* project filters when verifying (observed through 0.42.x,
and the rule does not depend on the version). Verify-then-trust therefore prints a clean
result having tested nothing — a green line that means "zero filters checked". Read the
count in the verify output, not just its exit status.

A verification failure **blocks use** and requires immediate rollback (`rtk untrust`),
captured with its own receipt. Re-trust only after reviewing what changed in the filter
content — the hash moving is the signal, not the inconvenience.

Never use a CI environment override to step around the local trust boundary. An override
that makes an unreviewed filter usable has not solved a permissions problem; it has moved
the filter outside the one check that reads it.

## Windows shell selection

The harness flag `native_shell: powershell` selects PowerShell redirect syntax; it does
not require the legacy `powershell.exe` executable. Use PowerShell 7 (`pwsh`) for child
shells and scripts that need modern cmdlets such as `Get-FileHash`, reliable UTF-8
defaults, or current module behavior. Treat `powershell.exe` as a legacy compatibility
surface and use it only when a task explicitly tests Windows PowerShell compatibility.

Do not pin a local PowerShell 7 patch version in durable instructions. When availability
must be verified, use the exact receipt form:

```powershell
pwsh -NoProfile -Command '$PSVersionTable.PSVersion' *> {{RECEIPTS_DIR}}/pwsh-version.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/pwsh-version.txt; exit $code
```

On macOS/Linux, `.agent/docs/macos-setup.md` is the companion: `pwsh` may be installed
and still not be the canonical dispatch path.
