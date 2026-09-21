# Follow-up — the package gates fail at ed04b70, and `sanitize.py --verify` writes

Recorded 2026-09-21 while porting the review-ledger simplification from the reference adopter. This is a one-page follow-up, not a
plan: the port was judged on "no new gate failures" because the gates below already failed before
it, identically after it (receipts compared line by line with the `file:line` prefixes stripped).

This note deliberately names no tool path literally: the gates scan every markdown file for
`tools/...` commands, so a note that quoted the offending paths would itself become four new
"unclassified tool" sites and change the very summary it describes.

## What fails at `ed04b70`, before any change

| Gate | Exit | What it reports |
|---|---|---|
| `python3 scripts/sanitize.py --verify` | 3 | `UNRESOLVED` references from the packaged workflows and `core/AGENTS.md` to the four artifact templates under an agent-local templates directory that the package does not ship (the templates live under `core/templates/`), to an unshipped codebase validator, and from two 2026-09-19 plan docs to editor command directories; four `UNCLASSIFIED-TOOL` commands (a PowerShell preflight twin, the unshipped codebase validator, and two placeholder script names used as examples in prose) cited from `.agent/context/2026-09-19-adopter-findings-fix-proposal.md` and the terminal-preflight skill |
| `python3 scripts/refcheck.py` | 1 | `UNCLASSIFIED: 4` (the same four commands), `REQUIRED-DANGLING: 3`, `UNRESOLVED: 73` |

Run either gate to see the exact paths; they are listed in its own output, which is the receipt.

## The write

`scripts/sanitize.py --verify` is not read-only: on every run it rewrote three files under
`.agent/context/` and two 2026-09-19 plan docs in place, replacing the source project's name with
`{{PROJECT_NAME_TITLE}}` (33 lines). A gate that mutates the tree it verifies cannot be run before
`git add -A` without restoring those files first, and its exit code does not say that it wrote.
Proposed fix: make `--verify` a pure read (report the leak, exit 2, write nothing) and keep the
rewrite behind the default sanitize mode.

## Proposed repair, smallest first

1. `--verify` becomes read-only (above).
2. Point the template references at `core/templates/` (or add the adopter-facing copies the docs
   already promise) so the `UNRESOLVED` count drops to the plan-doc mentions of editor command
   directories, which are prose about an adopter's IDE and belong on the refcheck allowlist.
3. Classify the four tool commands in `refcheck.py`: `not-shipped` for the two placeholder names,
   `adopter-supplied` or `not-shipped` for the codebase validator and the PowerShell preflight twin.

Until this lands, a port from an adopter should be judged the way this one was: selftest green,
and no gate line present after the change that was absent before it.
