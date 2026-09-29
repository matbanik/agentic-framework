---
description: Criteria-first implementation with Red/Green evidence and staged adopter validation.
---

# TDD Implementation Workflow

Read PROJECT-PROFILE, AGENTS §Testing & TDD Protocol, the canonical plan/task, and relevant emerging standards. Apply D6_ADOPTER_ARGV and D9_NO_BRANCH. Commands come from the installed command registry and use output-evidence-policy's native-shell receipt form. No Python product stack, RTK or MEU infrastructure is universal; the shipped framework validators themselves require Python 3.10+.

## 1. Lock scope and criteria

Read all task rows; work in dependency order. D9=yes resolves the unit through the MEU SSOT/build plan. D9=no uses the planned domain unit. Write the FIC to a durable plan or handoff: intent, numbered ACs with Spec/Local Canon/Research-backed/Human-approved sources, negative cases, boundary contracts and test/procedure mapping. No unsourced “best practice” behaviors or silent scope cuts.

For write boundaries cover blank input, malformed fields, invalid enums, ranges, extra fields and create/update parity as applicable. Expected errors come from the project's boundary contract, not a universal HTTP status or framework library.

## 2. Red: demonstrate the unmet behavior

For a bug, reproduce it before changing production code. Write behavior tests for ACs and negative cases at the correct unit/integration/contract level. Execute the D6 targeted command; save status immediately before reading its receipt. Confirm failure is the intended unmet behavior, not startup/import/collection failure. Paste exact command, exit and decisive failure into an evidence.v1 record and FAIL_TO_PASS table.

For non-software work, execute the predeclared falsification/acceptance procedure and record the observation, observer and result; do not fabricate a failing program.

## 3. Green: implement the contract

Implement complete behavior and error paths. Keep ACs/assertions stable; correct setup fixtures only when needed. A proven specification error requires a sourced amendment and independent review before assertions change. Incorporate authorized user scope changes into plan/task and review scope; ask only for unresolved choices.

Run cheap static checks, then the affected targeted tests. Preserve Green command/status/output. Search sibling implementations for the same bug class. A thin spec or repeated failures means return to research, not a silent workaround.

## 4. Refactor and validate scope

Refactor while maintaining behavior, then rerun affected static/targeted checks. Scope includes shared fixtures, configuration, contracts and generated inputs. Later stages blocked by an earlier failure are not_run with a reason. Coverage/runtime budgets and integration selection follow D6; no product prefixes, timeout constants or --scope flags are assumed.

Update completed implementation rows only with durable evidence. Do not mark unfinished code blocked. An external error, missing prerequisite or human decision needs the shared B-row evidence contract. An execution-time fork (an AC unreachable as written, two plausible implementations, a bound that must move) follows `.agent/docs/human-decision-protocol.md`: precedent sweep, web research, obviousness test — decide and log it in the MEU handoff when the test passes; otherwise hold the row `[B]` with a Decision Brief (recommendation first) as its `Decision:` line and keep working the other rows. Holding the row stages the brief; it is *presented* at the next sanctioned gate (the MEU handoff / closeout human-decision exit, `AGENTS.md` §Execution Contract), where the turn ends per protocol §5 — never by ending the turn mid-execution.

## 5. H1: prepare final review

Complete applicable SSOT/current-focus/generated-contract updates before the final gate. With D9=no, omit MEU commands. Do not mark a MEU approved before independent approval; use its actual pre-review state.

Run one fresh D6 full gate on the final review inputs after corrections. Record complete input identity and promote evidence into the handoff before dispatch. A targeted pass, cache hit or snapshot-only run is insufficient. Earlier full evidence may be retained only when it is the same fresh final run and identity is independently established; otherwise rerun.

Read the handoff template and latest peer, include every plan AC and observed Red/Green/full results, then validate handoff structure, AC coverage, blocked records and full evidence with the shipped validators. Re-read task.md: implementation/H1 rows must be resolved; review/H2 rows correctly remain pending.

## 6. Review and H2

Continue into execution-session's independent review/correction loop, respecting EGRESS_PRECEDENCE and ledger limits. The handoff exists first. Implementor verification is not independent approval. If fixes change validation inputs, rerun affected checks and a fresh full gate before re-review.

After approved review, finish reflection, honest Instruction Coverage YAML from the current registry/schema, metrics and commit-message preparation. Re-read task.md and apply completion-preflight. No auto-commit.

## Exit criteria and failure handling

DONE requires all task rows completed or validly blocked, independent approval and valid closeout artifacts. Other outcomes are review cap, reviewer unavailable or human decision; save exact state and the unresolved gate. Compaction continues the workflow. Document repeated failures and resolve their causes; complexity and time pressure alone never justify a blocked row.
