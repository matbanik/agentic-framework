---
name: quality-gate
description: Run the adopter's configured static, targeted and final full validation stages; preserve durable command or manual evidence and refuse partial completion claims.
---

# Quality gate

Read PROFILE D6, the registered commands, testing-strategy and output-evidence-policy before running checks. D6_ADOPTER_ARGV owns executable/argv or manual procedure, cwd, scope, blocking status, expected result, shell and input identity. No packaged product validator or universal --scope/--json flag exists.

## Procedure

1. Resolve affected code, tests, shared fixtures, configuration and generated inputs from the plan/diff. Select registered static checks first, then targeted behavior/contract checks.
2. Redirect every process stream to the configured receipt root; capture status immediately, inspect the receipt, propagate status. RTK is optional; exact evidence must remain unfiltered.
3. On blocking failure, fix and rerun affected checks. Record later unexecuted stages as not_run with a reason. An advisory warning is reported, not silently converted into a blocking check; an unexpected skip is investigated.
4. After all implementation and input-changing artifact updates, run a fresh full gate on the final review state. Compare complete input identity before/after. Changes, incomplete identity, cached output or snapshot-only execution cannot establish this final gate.
5. Paste evidence.v1 records into the durable handoff. Validate with tools/durable_evidence.py, using --require-full and independently obtained --expected-state for final review. Manual checks use observer/procedure and null exit_code, not invented commands.
6. Continue handoff → independent review → closeout. Green checks alone do not establish DONE. Reuse intermediate results only with implemented complete identity; no reuse adapter is shipped by default.

## Adopter choices

Coverage floors, integration selection, supported platforms, GUI/TUI runtime checks, security scans and timing budgets are registered in D6. Compile generated bundles before checks that consume them; validate mocks against real boundary schemas. A fixture's temp directory must never share a cleanup root with receipts or durable evidence.

For an external runtime/dependency blocker, record the actual failed command/nonzero exit/error plus a durable follow-up and row-bound blocker block. Unfinished code is not an external blocker. PROFILE C controls what evidence may be retained or sent to reviewers.
