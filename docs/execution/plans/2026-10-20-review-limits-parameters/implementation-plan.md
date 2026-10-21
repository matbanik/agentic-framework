---
project: "2026-10-20-review-limits-parameters"
date: "2026-10-20"
source: "USER_EXPLICIT 2026-10-20 — setup option for token budgets, plan/execution parameters defaulting to the repo choice, round caps as setup parameters"
meus: []
run_parameters: "absent — run parameters are disabled in this repo (run_parameters.py status: policy_missing); Step 0 resolved manual"
status: "complete"
template_version: "2.3"
---

# Implementation Plan: Review limits as setup choices and plan parameters

> **Project**: `2026-10-20-review-limits-parameters`
> **Build Plan Section(s)**: none. This framework package has no `docs/BUILD_PLAN.md` hub (see the BUILD_PLAN.md Audit).
> **Status**: `draft`

---

## Goal

The review ledger ([core/tools/review_ledger.py](../../../../core/tools/review_ledger.py)) bounds every review
loop with two limits that are fixed in code:

- `ROUND_BUDGETS = {"plan": 3, "execution": 6, "discovery": 2, "handoff": 3, "multi-handoff": 3}`, with no override;
- `TOKEN_BUDGETS = {"plan": 10_500_000, "execution": 21_000_000, ...}`, with a `begin --token-budget N` override.

An adopter cannot pick either limit at setup. The profile question B5 ("How many review rounds
before escalating to a human?") is asked, but its answer goes nowhere in code. A plan cannot
carry its own limits. A token budget cannot be turned off: a null or 0 `token_budget` falls back
to the default (`tokens_spent`: `ledger.get("token_budget") or TOKEN_BUDGETS[...]`).

This change has five parts:

1. **Setup choice.** A new repo file, `.agent/review-limits.json`, holds the round cap and token budget
   for each review mode, plus a `token_budgets: "on" | "off"` switch. `scripts/instantiate.py` writes it from two
   new flags, `--round-caps` and `--token-budgets`. The shipped values equal today's constants,
   so an adopter who answers nothing gets today's behavior.
2. **Plan parameter.** `create-plan` Step 0 copies the repo's values for the plan and execution
   modes into a `review_limits` frontmatter block in `implementation-plan.md` and `task.md`. A plan may
   tighten these values freely. It may loosen them past the repo values only through a value the human typed into a verified
   offer: a `form: self-contained` authorization, whose offer is the human's own message (D-2, Human-approved; AC-13).
3. **Ledger.** `review_ledger.py begin` resolves limits in this order: repo file, then the plan block read from
   `--ac-file`, then explicit flags. The explicit flags only tighten. The ledger records where each limit came
   from, and it represents "off" explicitly.
4. **Final audit and prose.** The final audit checks the execution round cap the ledger actually
   allowed, including rounds bought through `continue`, not a hard-coded 6. Workflow prose stops
   stating fixed caps and names the source of the limit.
5. **Credits USD caps follow the switch.** Under `token_budgets: "off"`, a scheduled credits run may
   omit its USD caps (`launch.segment_cap_usd`, `budget.run_cap_usd`, `chain.chain_cap_usd`). An uncapped
   segment is launched with no `--max-budget-usd`. Under `"on"`, or with no repo file, the caps stay
   required, as today. The segment timeout and the human-only resume still bound every run (D-1, Human-approved).

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning_and_execution
  eligible_tools: []
  decision: not_applicable
  eligibility_basis: "graphify-out/graph.json absent; Headroom not installed; the change set is a bounded list of named files located by grep."
  human_message_reference: null
```

## Handoff Set

| Scope | Canonical handoff |
|---|---|
| project (`meus: []`) | `.agent/context/handoffs/2026-10-20-review-limits-parameters-handoff.md` |

The rolling project review is
`.agent/context/handoffs/2026-10-20-review-limits-parameters-implementation-critical-review.md`.
The plan review is `.agent/context/handoffs/2026-10-20-review-limits-parameters-plan-critical-review.md`.

## Work Packages and Context Lifecycle

| ID | Work | depends_on | context_strategy | durable_outputs |
|---|---|---|---|---|
| WP-1 | Repo file plus instantiate flags (AC-1–AC-4) | — | `shared` | `core/.agent/review-limits.json`, `scripts/instantiate.py`, `scripts/tests/test_instantiate_review_limits.py` |
| WP-2 | Ledger resolution, "off", provenance, tighten-only flags (AC-5–AC-12) | WP-1 | `compact_continue` | `core/tools/review_ledger.py` (selftest arms), `core/tools/tests/test_review_limits.py` |
| WP-3 | Loosening verification and the final-audit cap (AC-13–AC-16) | WP-2 | `compact_continue` | `core/tools/run_parameters.py`, offer schema, `core/tools/tests/test_review_limits_audit.py` |
| WP-4 | Templates, workflows, profile and prose (AC-17–AC-20) | WP-3 | `compact_continue` | the template, workflow and profile files listed under Files Modified |

| WP-5 | Credits USD caps follow `token_budgets` (AC-21 (a)–(g)) | WP-2 | `compact_continue` | `core/tools/credits_state.py`, `core/.agent/skills/claude-credits/schemas/credits-run.v1.json`, `core/.agent/skills/claude-credits/Start-CreditsRun.ps1`, `core/.agent/skills/claude-credits/SKILL.md`, `core/tools/tests/test_credits_uncapped.py`, the Pester tests listed under Files Modified |

WP-5 depends on WP-2 because it reads the repo file through WP-2's `load_repo_limits`. It runs after WP-4 in the task order.

`isolated` is not used: no fresh-worker capability is authorized for this plan.

---

## User Review Required

> [!IMPORTANT]
> 1. **Behavior change: `begin --token-budget` only tightens.** Today, `begin --token-budget N` may
>    *raise* a loop's budget above the default. After this change an explicit flag may only tighten the
>    limit it resolves against. Raising a limit goes through `continue` (a named human at stop time) or a
>    verified plan block (D-2). No shipped workflow passes `--token-budget` today (grep of `core/**/*.md`
>    found no caller), so no shipped path breaks.
> 2. **Token budgets "off" also lifts the credits USD caps (D-1, resolved).** You answered "1. limit should be
>    off as well". Under `token_budgets: "off"`, a scheduled credits run may omit its USD caps, and an uncapped
>    segment runs with no `--max-budget-usd`, so no dollar ceiling stops it. The segment `timeout_sec`, the
>    Task Scheduler limit and the human-only resume still bound it. A cap that the manifest does give is still
>    honored (D-11). Switching the repo back to `"on"` stops an uncapped run at its next admission (AC-21 (c)).
> 3. **Loosening is Windows-only and needs run parameters.** It depends on `run_parameters.py`, which
>    is disabled in this repo (`policy_missing`) and off Windows. A loosening plan block there is refused
>    (fail-closed). Tightening and the repo defaults work everywhere.
>
> This section is content for the review loop, not a cue to stop now.
>
> **Run parameters (v2.3):** `manual`. `run_parameters.py status` returns `{"enabled": false, "reason":
> "policy_missing"}`, so Step 0 resolved manually: `decisions: hdp`, `commit_plan: false`,
> `exec_after_plan: false`, `commit_exec: false`, `push: never`, `authorization: {schema: manual}`.
> Because the authorization is manual, this plan carries no `run_parameters` block (a manual block
> is non-authorizing and would only add carriers to keep equal). Execution needs the human to say proceed.

---

## Proposed Changes

### Shared contract: the review-limits shapes

**Repo file** `.agent/review-limits.json` (shipped at `core/.agent/review-limits.json`):

```json
{
  "schema": "review-limits/1",
  "token_budgets": "on",
  "rounds": {"plan": 3, "execution": 6, "discovery": 2, "handoff": 3, "multi-handoff": 3},
  "tokens": {"plan": 10500000, "execution": 21000000, "discovery": 7000000,
             "handoff": 10500000, "multi-handoff": 10500000}
}
```

- The keys are exactly `schema`, `token_budgets`, `rounds` and `tokens`.
- `rounds` and `tokens` each hold exactly the five `ROUND_BUDGETS` modes, and each value is an integer ≥ 1.
- `token_budgets` is `"on"` or `"off"`. Under `"off"` the `tokens` map stays present and valid, so a later switch back to
  `"on"` needs no re-entry.

**Plan block**, written at create-plan Step 0 into both `implementation-plan.md` and `task.md`
frontmatter. The two blocks must be equal:

```yaml
review_limits:
  schema: review-limits/1
  plan_rounds: 3
  execution_rounds: 6
  plan_tokens: 10500000        # or: off
  execution_tokens: 21000000   # or: off
  basis: repo                  # repo | tightened | loosened
```

- **Values.** The values are concrete. Step 0 resolves the repo file and writes the numbers, never the word `repo`
  (D-4).
- **Strict format.** The ledger is stdlib-only. It reads this block with a strict line parser:
  - the block is the `review_limits:` key followed by exactly these six keys at two-space indent;
  - each value is a plain scalar, an integer ≥ 1 or `off` (token keys only);
  - a trailing `# comment` is allowed;
  - anything else fails closed, with exit 3.
- **Basis.** `basis` describes the relation to the repo file when the plan was written:
  - `repo` means the values are equal to the repo file;
  - `tightened` means every value is ≤ the repo value, with `off` counting as the loosest;
  - `loosened` means at least one value exceeds the repo value.
- **Ordering.** For tighten and loosen, a number is tighter than `off`. A repo `token_budgets: "off"`
  paired with a numeric plan value is a tightening.

**Ledger additions.** `LEDGER_KEYS` gains `limits_source`:

```json
{"repo": "<sha256 of .agent/review-limits.json> | constants", "plan": "<path> | null",
 "flags": ["round_budget", "token_budget"]}
```

- `limits_source` names what set the limits.
- `token_budget` may now be the string `"off"`.
- **Exit codes** follow `review_ledger.py main()`: 1 is a ledger refusal, 3 is fail-closed and 2 is a usage error. Exit 9 belongs to the dispatch wrappers, which map a refused ledger call to 9. `begin` treats any nonzero `limits-check` result as a refusal and exits 1.
- Ledgers written before this change have no `limits_source`. They still load, and `state` prints `limits: (pre-review-limits ledger)`.

**Credits manifests under `token_budgets: "off"`** (WP-5):

- **Read only when needed.** `credits_state.py` reads `<project_root>/.agent/review-limits.json` only when a
  manifest omits a cap, at `register` and again at each admission. It reads the file through
  `review_ledger.load_repo_limits(root)` (D-13), which returns the parsed file, or `None` when the file is
  absent, and raises on a malformed file. A manifest that carries all three caps never depends on the file.
- **Optional caps.** Under `"off"`, any of `launch.segment_cap_usd`, `budget.run_cap_usd` and
  `chain.chain_cap_usd` may be omitted. The `budget` object stays required and may be `{}`. A cap that is
  present is still checked by `_positive` and still bounds the run (D-11).
- **Uncapped admission.** `verb_admit` builds its rooms from the caps that are present. With no room, it
  admits with `reservation_usd: 0` and `uncapped: true`, and `FLOOR_USD` does not apply.
  `Start-CreditsRun.ps1` then passes `-MaxBudgetUsd 0` to `Invoke-ClaudeCredits.ps1`, which adds no
  `--max-budget-usd` (`Invoke-ClaudeCredits.ps1:272`). It never omits the argument, because the omitted
  default is $2.
- **Refusal codes.** `manifest_invalid` names an omitted cap under `"on"`. `review_limits_invalid` covers a
  malformed repo file. `caps_required` rejects the admission of an uncapped run after the repo is back at `"on"`.
- **Scope.** Only the repo switch matters here. A plan block's `execution_tokens: off` bounds one review loop
  and has no effect on credits runs.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `.agent/review-limits.json` | `review_ledger.py` `load_repo_limits()` (stdlib) | exact keys; five modes per map; ints ≥ 1; `token_budgets` ∈ {on, off} | extra or missing key: exit 3 (fail-closed) |
| `review_limits` frontmatter block | `review_ledger.py` `load_plan_limits()` (stdlib line parser) | six keys; ints ≥ 1 or `off` for token keys; `basis` ∈ {repo, tightened, loosened}; `basis` must match the computed relation | extra, missing or duplicate key, or a non-scalar value: exit 3 |
| `begin --round-budget N` / `--token-budget N\|off` | `review_ledger.py` argparse + `cmd_begin` | int ≥ 1 or `off`; must not exceed the resolved limit | looser than the resolved limit: exit 1 (ledger refusal; the dispatch wrapper maps it to 9) |
| `instantiate.py --round-caps` / `--token-budgets` and config keys `ROUND_CAPS` / `TOKEN_BUDGETS` | `scripts/instantiate.py` | `mode=N[,mode=N]`, modes from the five, N ≥ 1; `on\|off` | unknown mode, duplicate mode, N < 1 or a non-integer: usage error, exit 2, nothing written |
| Offer key `review_limits` | `run_parameters.py` offer parser plus the offer schema | same six keys as the plan block | the offer key set must equal `OFFER_KEYS`, extended in a new offer schema version; a /1 offer is unchanged and cannot loosen |
| Credits manifest caps `launch.segment_cap_usd`, `budget.run_cap_usd`, `chain.chain_cap_usd` | `credits_state.py` `load_manifest` and `parse_chain` (the authority); `credits-run.v1.json` lists them as optional properties | a number > 0 when present; may be omitted only when the project's `.agent/review-limits.json` has `token_budgets: "off"` | omitted under `"on"` or with no repo file: `manifest_invalid`; a malformed repo file: `review_limits_invalid`; other keys keep `additionalProperties: false` and the exact `CHAIN_KEYS` rule, with `chain_cap_usd` the one optional chain key |
| `run_parameters.py limits-check --plan <slug>` | `run_parameters.py` | the task's authorization is `authorization/1` with `form: self-contained`, so the offer, and with it every limit value, is text the human typed; the plan block must equal that offer's `review_limits` | disabled, off Windows, manual or legacy authorization, `form: reply` (the offer text is the assistant's), or a mismatch: nonzero, and `begin` exits 1 |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-1 | unit | `core/.agent/review-limits.json` ships with `token_budgets: "on"`, and its `rounds` and `tokens` equal today's `ROUND_BUDGETS` and `TOKEN_BUDGETS`. A test asserts the equality against the constants, so the two cannot drift. | Spec (USER_EXPLICIT "defaults that are already present") | Changing one constant, or one file value, makes the test fail. |
| AC-2 | integration | `instantiate.py --round-caps plan=4,execution=8 --token-budgets off` writes those values into the adopted `.agent/review-limits.json` and leaves every other mode at its shipped value. The plan line prints `write .agent/review-limits.json rounds=plan:4,execution:8 token_budgets=off`. The same values from a `--config` file (`ROUND_CAPS=plan=4,execution=8`, `TOKEN_BUDGETS=off`) give the same bytes, and a flag beats the config value, as `--credits-start-policy` does. | Spec; Local Canon (`instantiate.py` `--credits-start-policy`, lines 639–718) | `--round-caps plan=0`, `plan=x`, `bogus=3`, `plan=3,plan=4` and `--token-budgets maybe` each exit 2 and write nothing (the tree hash is unchanged). |
| AC-3 | integration | An instantiate run with neither flag leaves `.agent/review-limits.json` byte-identical to the shipped file. | Local Canon | — (the positive identity check is the oracle) |
| AC-4 | unit | `--verify` (read-only) reports a review-limits file that fails `load_repo_limits` as a verify failure. | Local Canon (`--verify` read-only contract) | A file with an extra key, or with `rounds.plan: 0`, fails verify. |
| AC-5 | integration | `begin` with no plan block, no flags and a valid repo file opens the loop with the repo values. The `OK: opened` line adds `source=repo:<sha12>`. `limits_source.repo` is the file's sha256. | Spec | A repo file with `rounds.execution: 9` yields `budget=9` (this proves the value is read, not the constant). |
| AC-6 | integration | When `.agent/review-limits.json` is absent, `begin` uses the constants, prints `source=constants (no .agent/review-limits.json)`, and sets `limits_source.repo` to `"constants"`. When the file is present but malformed, `begin` fails closed with exit 3. | Local Canon (fail-closed: exit 3) | A malformed file must not silently fall back to the constants. |
| AC-7 | integration | For `--review-mode plan` and `execution`, `begin` reads the `review_limits` block from the `--ac-file` frontmatter. A block at `basis: repo` or `tightened` sets the loop's limits, and `limits_source.plan` names the file. Other modes ignore the block. | Spec (USER_EXPLICIT "parameter on plan and execution") | A block whose `basis: tightened` does not match the computed relation (a value is looser than the repo) exits 3. A malformed block exits 3. |
| AC-8 | integration | When the `--ac-file` has a sibling `task.md` that carries a `review_limits` block, the two blocks must be equal. | Local Canon (run-parameters carrier equality) | Unequal blocks exit 1 with `review_limits differs between implementation-plan.md and task.md`. |
| AC-9 | integration | `--round-budget N` and `--token-budget N\|off` apply after the plan block and only tighten: a value ≤ the resolved value is accepted, and `limits_source.flags` lists the flag. | Human-approved (D-2: tighten freely) | A flag looser than the resolved value exits 1, and the refusal names the resolved value and its source. `--token-budget off` against a numeric resolved budget exits 1. |
| AC-10 | unit | A token budget of `off` is stored as `"off"`, and then: `stops()` emits no `tokens` stop, however much usage is recorded; `state` prints `tokens     off (N spent, not budgeted)`; `continue --tokens T` on an "off" loop exits 1 (`token budget is off for this loop; nothing to lift`); the reserve computation never divides by `round_budget` with an "off" base. | Spec ("option to not include token budgets") | Selftest arms: an "off" loop with usage of 10^12 has no tokens stop; a numeric budget of 1 still fires the stop; `continue --tokens 5` on an "off" loop exits 1; `token_budget: 0` or `null` in a hand-edited ledger exits 3 instead of falling back to the default. |
| AC-11 | unit | The `round_budget` stop, the mechanism stop, the scaffolding stop and the instrument stop are unchanged whatever the token setting is. All 105 existing selftest arms still pass, and a new selftest arm per AC-5–AC-10 brings the count to ≥ 115. | Local Canon | The existing boundary arms stay green: `spent + reserve > budget` is strict, and so is `used >= allowed`. |
| AC-12 | unit | A ledger written before this change (no `limits_source`, integer `token_budget`) loads, evaluates and continues exactly as before. | Local Canon (no reset of in-flight loops) | A fixture ledger from before the change must produce the same `stops()` output before and after the change. |
| AC-13 | integration | A plan block with `basis: loosened` is accepted by `begin` only when `run_parameters.py limits-check --plan <slug>` exits 0. That requires all three: the task's authorization is `authorization/1` and verifies against the transcript; it has `form: self-contained`, so the offer's `review_limits` values are in the human's own typed message (in `form: reply`, `_verify_reference` takes the offer from the assistant's presentation and a bare accept word suffices, which is not human provenance for a limit value, per D-2); the offer's `review_limits` equals the block. | Human-approved (USER_EXPLICIT 2026-10-20 "1. yes": loosen only when the value is in an offer the human typed) | `limits-check` refuses, and `begin` exits 1, for each case: run parameters disabled (`policy_missing`); not Windows; `{schema: manual}`; a legacy authorization; a `form: reply` authorization whose assistant-presented offer carries the loosened `review_limits` and whose human reply is the bare accept word; an offer whose `review_limits` differs by one value; an offer without the key. Positive cases: a self-contained /2 offer typed by the human with `execution_rounds: 9` passes, and so does one with `execution_tokens: off`. |
| AC-14 | unit | The offer gains the key `review_limits` under a new offer schema version. The offer parser accepts both versions, and `_offer_types_ok` checks the six-key shape. A /1 offer cannot carry the key. | Local Canon (`OFFER_KEYS` exact-set rule) | A /1 offer that carries `review_limits` is refused as `schema`. A /2 offer with `plan_rounds: "3"` (a string) is refused. |
| AC-15 | integration | The final audit's execution round cap comes from one resolver, `audit_round_cap(plan)`, in this order: (a) when the execution ledger `exec-<slug>` exists, its `rounds_allowed()`: the base set at `begin` (already resolved, and verified by `limits-check` if loosened) plus the rounds bought through `continue`; a ledger that is malformed, or whose `review_mode` is not `execution`, fails closed; (b) when the task carries a `review_limits` block but no execution ledger exists, the audit refuses (`exec_ledger_missing`), because a plan written under this change runs its execution review through the ledger, and a missing ledger is missing state, not a reason to read an unverified block; (c) only for a legacy task with no `review_limits` block and no ledger, the repo file's `rounds.execution` through `load_repo_limits` (the reader `begin` uses), and 6 when the file is absent. The task's `review_limits.execution_rounds` is never a cap on its own. `EXEC_REVIEW_MAX_ROUNDS` is no longer passed directly to `--max-review-rounds`. | Local Canon (latent bug: run_parameters.py:3425, 3746, 3767 at e667fb6); review round 1, F-002 | Fixtures: (1) an execution ledger with base 6 and a 1-round continue, plus an approved review at round 7: the audit fails before the change and passes after it; (2) the same review against a ledger with no grant fails; (3) a valid /1 grant, no ledger, a task block with `execution_rounds: 7` and a round-7 approval: refused `exec_ledger_missing` (the unauthorized-fallback path is closed); (4) a malformed ledger: fail-closed; (5) a ledger whose `review_mode` is `plan`: fail-closed; (6) a legacy task with no block and no ledger, with the repo file at its shipped 6: the cap is 6, and with the file absent: 6. |
| AC-16 | unit | `limits-check` is read-only: it writes nothing to the authority store or to the plan files. | Local Canon (verify verbs are read-only) | The store and the plan-file hashes are equal before and after a run that passes and a run that refuses. |
| AC-17 | integration | `create-plan.md` Step 0 tells the planner to read `.agent/review-limits.json` (or the constants note when absent) and write the `review_limits` block with `basis` into both carriers. Every operative fixed-cap statement in `FIXED_CAP_INVENTORY` (below the table) is replaced by text that names the source of the limit (`review_limits` or `.agent/review-limits.json`); the text may give the shipped value as "default 3" or "default 6". | Spec; review round 1, F-003 | The task row checks the bounded inventory, not a regex: every inventory phrase is absent from its file, and every inventory file contains `review_limits` or `review-limits.json`. The same check run against each file's `git show HEAD:<path>` text must fail, which proves the oracle catches the live forms (`round cap (3)`, `round cap (6)`, `execution = 6`, `(≤3 rounds)` and the rest). Round counts outside the inventory are not operative caps and are not checked. |
| AC-18 | unit | `PLAN-TEMPLATE.md` (to 2.4) and `TASK-TEMPLATE.md` (to 2.5) carry the optional `review_limits` block with a one-line note on its source and basis. The H1-7a/H1-7b `{configured-cap}` placeholder names `review_ledger.py state --loop-id exec-<slug>` as the source. A template without the block keeps the earlier rules (absent block = repo limits). | Local Canon (template version bumps per optional block, v2.3/v2.4 precedent) | `lint_task_contract.py` and `validate_closeout_artifacts.py` selftests still pass. A task with no block still lints clean. |
| AC-19 | unit | `ADOPTION-QUESTIONS.md` B5 names `--round-caps`, and a new B5b ("Should review loops also stop on a token budget?", default: on) names `--token-budgets`. `PROJECT-PROFILE-TEMPLATE.md` gains a B5b row. Both say that "off" also lifts the USD caps on scheduled credits runs, that the segment timeout still applies, and that switching back to "on" stops an uncapped run at its next admission (D-1). | Spec; Human-approved (D-1) | Grep finds `--round-caps`, `--token-budgets`, `B5b`, `USD` and `credits` in both files. |
| AC-20 | unit | `MANIFEST.md` lists `.agent/review-limits.json`, and its `review_ledger.py` entry names the resolution order. `core/.agent/workflows/execution-session.md:182–205` says where `ROUND_BUDGETS`/`TOKEN_BUDGETS` now come from. | Local Canon | `scripts/refcheck.py` reports 0 unresolved references. |
| AC-21 | integration | Credits USD caps follow `token_budgets` (WP-5), in seven parts: (a) `register` (`load_manifest`, `parse_chain`) under a repo `token_budgets: "off"` accepts a manifest that omits `launch.segment_cap_usd`, `budget.run_cap_usd`, `chain.chain_cap_usd`, or any mix of them, and stores NULL for each omitted cap. The `Manifest` caps become `float \| None`. (b) `verb_admit` builds its rooms only from the caps that are present: the segment cap, the run cap less the run spend, and the chain room. With no room it admits with `reservation_usd: 0` and `uncapped: true`, and the `FLOOR_USD` check is skipped. With at least one room, the reservation is the smallest room, and the floor applies as today. (c) At each admission of a run with any NULL cap, `verb_admit` re-reads the repo file. Under `"on"`, or with the file absent, it rejects with `caps_required`, and a malformed file rejects with `review_limits_invalid`. A first start becomes `failed` with a `start_refused` notice, and a resume becomes `stopped` with a `resume_refused` notice. (d) `finalize_segment` for an uncapped segment whose cost is not trusted books an exposure of 0, keeps `cost_known` 0, and does not raise. A trusted cost is recorded as today. (e) `chain_room` returns `None` when no run of the chain holds a chain cap. `verb_chain_candidates` then reports `chain_room_usd: null`, and `ready` ignores the floor. The existing whole-block equality in `register` keeps a chain from mixing capped and uncapped blocks. (f) `Start-CreditsRun.ps1` passes `-MaxBudgetUsd 0` when the admission says `uncapped: true`, so the claude argv has no `--max-budget-usd`. A capped admission still passes the reservation. `credits-run.v1.json` no longer lists the three caps as `required` and keeps their properties, and `Register-CreditsRun.ps1` accepts a manifest without them. (g) The claude-credits `SKILL.md` §Schedule says that the caps are optional only under `token_budgets: "off"`, and what bounds an uncapped run. Run in the instantiated stage, the credits pytest and every Pester suite pass outright, as they do at row 0, the new and changed tests pass, and the existing fixtures are unchanged. The manual runner's $2 default is not touched. | Human-approved (D-1, USER_EXPLICIT 2026-10-20 "1. limit should be off as well"; D-11, D-12); Local Canon (`Invoke-ClaudeCredits.ps1:272`: 0 means no cap; an omitted value means $2); review round 3, F-008, F-009; review round 4, F-008, F-010; review round 5, F-013 | (a) Under `"on"`, and with no repo file, an omitted cap is refused `manifest_invalid`, and the message names the cap and that `token_budgets` is on. A malformed repo file refuses `review_limits_invalid`. Under `"off"`, a present cap of 0 is still refused by `_positive`. A manifest with all three caps registers with no repo file, as today. (b) An uncapped run with 10^6 USD of recorded spend is admitted. A run with only `run_cap_usd: 200` and 197 spent is refused `budget_floor`. A run with only `segment_cap_usd: 40` reserves 40. (c) A run registered under `"off"`, with the file then set to `"on"`: its first start fails `caps_required`; with the file deleted: `caps_required`; a stopped run's resume is refused and stays `stopped`. A capped run is admitted whatever the file says. (d) An uncapped segment finalized with `total: None` has one exposure row with `exposed_usd` 0, and `run_spend` still returns. A capped segment's exposure still equals its reservation. (e) A chain whose blocks have no cap and whose predicates hold is `ready` with 10^6 USD spent. A second run whose chain block adds a cap is refused `chain_conflict`. A capped chain with room below `FLOOR_USD` is still not ready. (f) Pester: the uncapped case has no `--max-budget-usd` in the argv, and the capped test at `Start-CreditsRun.Tests.ps1:283` passes in the stage, where it also passes at baseline. `Register-CreditsRun.Tests.ps1`: the schema still names every key and keeps `additionalProperties: false`, and a manifest without caps passes the PowerShell schema check, which leaves the condition to `credits_state.py`. (g) In the stage, the credits pytest exits 0, and `run_pester.ps1` passes on every Pester suite. An interrupted pytest run exits 2 and cannot pass. `run_pester.ps1` refuses an assertion failure, a discovery failure, a `BeforeAll` failure, an `AfterAll` failure, a file with no test, and a requested path, such as a missing `Start-CreditsRun.Tests.ps1` beside a passing `Register-CreditsRun.Tests.ps1`, that yields no test file (its self-check). A grep of `SKILL.md` finds `token_budgets` and `review-limits.json`. |

**`FIXED_CAP_INVENTORY`.** These are the operative fixed-cap statements on the tree at HEAD `d698342`, found by grep of the five files. The AC-17 task row runs `check_ac17.py` in this plan folder, which checks exactly these substrings. It is a bounded inventory check: it proves these statements are gone and that each file names the limit source somewhere, not that every replacement sentence attributes its source, so the WP-4 editor also reads each replaced statement in place (review round 2, F-006).

| File | Phrases (exact substrings) |
|---|---|
| `core/.agent/workflows/create-plan.md` | `Plan review round cap: 3 rounds` · `reaches 3 rounds` · `Plan review reached 3 rounds without approval` · `Round cap reached (3 rounds)` · `round cap (6)` · `Round cap: 6 rounds` |
| `core/.agent/workflows/execution-session.md` | `3-round cap` · `execution = 6` |
| `core/.agent/workflows/delegated-plan-creation.md` | `round cap (3)` · `the cap of 3` · `is 3 rounds` · `If 3 rounds without approval` |
| `core/.agent/skills/cli-dispatch/SKILL.md` | `capped at 3 rounds` |
| `core/.agent/docs/development-lifecycle.md` | `(≤3 rounds)` · `(≤6 rounds)` · `max 3 rounds` · `max 6 rounds` · `≤3 rounds, agent loops` · `≤6 rounds, agent loops` · `3 non-approved rounds` · `6 non-approved rounds` · `7th autonomous round` (lines 302, 397, 399; added after review round 2, F-006) |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Which limits become setup choices | Spec | Rounds for plan and execution (USER_EXPLICIT) and the token switch (USER_EXPLICIT). The file also holds the other three modes so that one resolver serves all five (D-3). |
| Default values | Spec | Today's constants (USER_EXPLICIT "defaults that are already present"). |
| A plan looser than the setup | Human-approved | Allowed only through a verified, human-typed offer: `form: self-contained`, never `form: reply` (D-2, AC-13). |
| What "off" means | Spec | No token stop for the loop. The round, mechanism, scaffolding and instrument stops are unchanged (AC-10, AC-11). |
| USD caps | Human-approved | `token_budgets: "off"` also lets a credits manifest omit its USD caps, and present caps still bind (D-1, D-11, AC-21 (a)–(g)). |
| Where the plan parameter lives | Local Canon | A separate `review_limits` block rather than a key inside `run_parameters` (D-5). |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `core/.agent/review-limits.json` | new | The shipped defaults (AC-1). |
| `core/tools/review_ledger.py` | modify | `load_repo_limits`, `load_plan_limits`, the resolution in `cmd_begin`, `--round-budget`, `--token-budget N\|off`, `limits_source`, the "off" handling in `tokens_spent`/`stops`/`state`/`continue`, the strict 0/null refusal, and the selftest arms (AC-5–AC-13). |
| `core/tools/run_parameters.py` | modify | The `limits-check` verb; the offer schema version with `review_limits`; the final-audit cap from the ledger (AC-13–AC-16). |
| `core/.agent/run-parameters/schemas/*offer*` | new or modify | The new offer schema version that carries `review_limits` (AC-14). |
| `scripts/instantiate.py` | modify | `--round-caps`, `--token-budgets`, the config keys, the plan line, the `--verify` check, and selftest checks (AC-2–AC-4). |
| `core/tools/tests/test_review_limits.py` | new | Ledger resolution, tightening, "off" and legacy ledgers (AC-5–AC-12). |
| `core/tools/tests/test_review_limits_audit.py` | new | `limits-check` refusals and the final-audit cap (AC-13–AC-16), using the `run_parameters_fixtures` patterns. |
| `scripts/tests/test_instantiate_review_limits.py` | new | The instantiate flags, config, refusals and identity (AC-1–AC-4). |
| `core/.agent/workflows/create-plan.md` | modify | Step 0 limits resolution; §5e and lines ~656/661 prose (AC-17). |
| `core/.agent/workflows/execution-session.md` | modify | The `begin` line comment and the stop/continue text at 182–205 (AC-17, AC-20). |
| `core/.agent/workflows/delegated-plan-creation.md` | modify | Lines 37, 253, 335, 349: the cap prose (AC-17). Line 247: the `begin` example gains the required `--goal-anchor` and `--ac-file` (review round 1, F-004). |
| `core/.agent/workflows/validation-review.md` | modify | Line 40 `begin`: notes that the limits come from the repo file (AC-17). |
| `core/.agent/skills/cli-dispatch/SKILL.md` | modify | Line 401: the cap prose (AC-17). Line 309: the `begin` example gains the required `--goal-anchor` and `--ac-file` (review round 1, F-004). |
| `core/.agent/docs/development-lifecycle.md` | modify | Lines 56, 75, 293, 391, 938 and 940, edited only where the text states a fixed cap rather than a default (AC-17). |
| `core/templates/PLAN-TEMPLATE.md`, `core/templates/TASK-TEMPLATE.md` | modify | The `review_limits` block, the version bumps and the `{configured-cap}` source (AC-18). |
| `ADOPTION-QUESTIONS.md`, `PROJECT-PROFILE-TEMPLATE.md` | modify | B5 and B5b (AC-19). |
| `core/MANIFEST.md` | modify | File listing and ledger entry (AC-20). |
| `core/tools/credits_state.py` | modify | Optional caps in `Manifest`, `load_manifest` and `parse_chain`, the repo-switch read, the uncapped admission, the `caps_required` re-check, the 0 exposure and the `None` chain room (AC-21 (a)–(e)). |
| `core/.agent/skills/claude-credits/schemas/credits-run.v1.json` | modify | The three caps leave `required` (AC-21 (f)). |
| `core/.agent/skills/claude-credits/Start-CreditsRun.ps1` | modify | `-MaxBudgetUsd 0` on an uncapped admission, and the admitted log line names `uncapped` (AC-21 (f)). |
| `core/.agent/skills/claude-credits/SKILL.md` | modify | §Schedule: the caps are optional under `"off"` (AC-21 (g)). |
| `core/tools/tests/test_credits_uncapped.py` | new | AC-21 (a)–(e), built on the `test_credits_state.py` fixtures. |
| `core/tools/tests/Start-CreditsRun.Tests.ps1`, `core/tools/tests/Register-CreditsRun.Tests.ps1` | modify | The uncapped argv case and the optional-cap schema case (AC-21 (f)). |

`core/AGENTS.md:55` ("initial defaults: plan 3, execution 6") stays as it is. It is still true
once the defaults move to the repo file, and it is a context line in the approved governance
diff `01-agents.diff`, so `validate_agent_files.py --policy run-parameters` is unaffected.

---

## Out of Scope

| Item | Kind | Deferred-to MEU | Basis |
|------|------|-----------------|-------|
| The manual runner's `-MaxBudgetUsd` default of 2 (`Invoke-ClaudeCredits.ps1:78`) | out-of-scope | — | A human starts a manual run from a terminal and passes the cap. D-1 covers the scheduled credits runs, which are unattended. |
| Letting a plan block's `execution_tokens: off` lift credits caps | out-of-scope | — | D-1 ties the credits caps to the repo setup choice. A plan block bounds one review loop. |
| Review limits on the grouping line (`session-grouping.md:114`) | out-of-scope | — | USER_EXPLICIT 2026-10-20 names "the repo" and "plan and execution" only. The grouping line format is unchanged. |
| Plan-level limits for the discovery, handoff and multi-handoff modes | out-of-scope | — | USER_EXPLICIT 2026-10-20 names plan and execution. Those modes still read the repo file and the flags (AC-5, AC-9). |
| Changing `MECHANISM_LIMIT` or `SCAFFOLDING_CAP` | out-of-scope | — | USER_EXPLICIT 2026-10-20 names rounds and token budgets only. |
| Redrawing `core/.agent/docs/diagrams/development-lifecycle-overview.svg` | out-of-scope | — | It shows the shipped defaults, which stay true (AC-1). USER_EXPLICIT scope is code and setup, not diagrams. |
| Pinning `.agent/review-limits.json` in the run-parameters policy | out-of-scope | — | D-6: the file is adopter configuration that the human edits. Pinning it would turn run parameters off on every cap change. |

---

## BUILD_PLAN.md Audit

This project modifies no build-plan section. This framework package has no `docs/BUILD_PLAN.md`
hub. The check below is expected to print `False`, and it is recorded as N/A:

```powershell
Test-Path docs/BUILD_PLAN.md *> $env:RECEIPTS_DIR/build-plan-audit.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/build-plan-audit.txt; exit $code
```

---

## Verification Plan

> [!IMPORTANT]
> Receipts go to `$env:RECEIPTS_DIR` (session value `C:/Temp/agentic-framework/receipts`). This
> repo has no `rtk` or `uv`; the commands call `python` directly, as the 2026-09-19 precedent does.
> Every command also runs with `$env:AGENT_MODEL_REGISTRY_HOME = 'P:/.agent'`, the model
> registry location (`core/.agent/INSTANTIATE.md` §1). Without it, the wrapper Pester suites
> fail with `registry_not_found`. The Python that runs the tests must have `psutil` (the
> credits `run_parameters` paths import it, `credits_msg.py:2042`); without it, 17 staged
> credits tests fail before any change. Row 0 refuses to start without `psutil`, and records
> both values and the `psutil` version with the input identity.

### 1. Static

```powershell
python -m pyflakes core/tools/review_ledger.py core/tools/run_parameters.py core/tools/credits_state.py scripts/instantiate.py *> $env:RECEIPTS_DIR/rl-static.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/rl-static.txt; exit $code
```

If `pyflakes` is not installed, run `python -m py_compile` over the same four files instead, and record the substitution.

### 2. Targeted

```powershell
python core/tools/review_ledger.py selftest *> $env:RECEIPTS_DIR/rl-ledger-selftest.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/rl-ledger-selftest.txt | Select-Object -Last 15; exit $code
python -m pytest core/tools/tests/test_review_limits.py core/tools/tests/test_review_limits_audit.py core/tools/tests/test_credits_uncapped.py scripts/tests/test_instantiate_review_limits.py -q *> $env:RECEIPTS_DIR/rl-targeted.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/rl-targeted.txt | Select-Object -Last 20; exit $code
python scripts/instantiate.py --selftest *> $env:RECEIPTS_DIR/rl-instantiate-selftest.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/rl-instantiate-selftest.txt | Select-Object -Last 15; exit $code
```

### 3. Fresh full

```powershell
python -m pytest core/tools/tests scripts/tests -q -rfE *> $env:RECEIPTS_DIR/rl-full-pytest.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/rl-full-pytest.txt -Tail 25; exit $code
python scripts/refcheck.py *> $env:RECEIPTS_DIR/rl-refcheck.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/rl-refcheck.txt | Select-Object -Last 15; exit $code
Push-Location core; python tools/validate_agent_files.py --policy run-parameters *> $env:RECEIPTS_DIR/rl-policy.txt; $code=$LASTEXITCODE; Pop-Location; Get-Content $env:RECEIPTS_DIR/rl-policy.txt | Select-Object -Last 15; exit $code
python core/tools/lint_task_contract.py --task docs/execution/plans/2026-10-20-review-limits-parameters/task.md *> $env:RECEIPTS_DIR/rl-task-lint.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/rl-task-lint.txt; exit $code
```

The credits pytest and every Pester suite (AC-21 (f), (g)) run in an instantiated stage. They
read filled-in placeholders such as `{{RECEIPTS_DIR}}`, so in the raw `core/` some of them fail
before any change. `stage_core.py` in this plan folder copies the working tree's `core/` to
`C:/Temp/agentic-framework/rl-stage`, fills it with `instantiate.py`, and checks that no placeholder is left.

Every gate is plain pass or fail, and no failure is excused (review round 4, F-008, F-010):

- **pytest:** the gate is pytest's own exit status, kept in `$code` straight after the run and
  never overwritten. Only 0 passes. An interrupted run or a collection error exits 2, and a
  selection with no test exits 5, so neither can pass.
- **Pester:** `run_pester.ps1` passes only when `Result` is `Passed`, at least one test passed,
  no test, block or container failed, and every requested path exists and yields at least one
  discovered test file. Pester skips a missing path and passes the rest (round 5, F-013). A discovery failure (round 3) and a failed `AfterAll`
  (round 4) both report `FailedCount` 0, which is why that count alone is not trusted. Before the
  real run, the script proves on temporary probe files that it refuses an assertion failure, a
  discovery failure, a `BeforeAll` failure, an `AfterAll` failure, a file with no test, a missing
  file beside a passing file, and a directory with no test file beside a passing file, and that
  it passes a passing directory named in other letter case (Pester reports the on-disk case).

```powershell
python docs/execution/plans/2026-10-20-review-limits-parameters/stage_core.py *> $env:RECEIPTS_DIR/rl-stage.txt; $code=$LASTEXITCODE; if ($code -ne 0) { Get-Content $env:RECEIPTS_DIR/rl-stage.txt -Tail 10; exit $code }; Push-Location C:/Temp/agentic-framework/rl-stage; python -m pytest tools/tests -k credits -q -rfE *> $env:RECEIPTS_DIR/rl-credits-stage.txt; $code=$LASTEXITCODE; Pop-Location; Get-Content $env:RECEIPTS_DIR/rl-credits-stage.txt -Tail 25; exit $code
pwsh -NoProfile -File docs/execution/plans/2026-10-20-review-limits-parameters/run_pester.ps1 C:/Temp/agentic-framework/rl-stage/tools/tests *> $env:RECEIPTS_DIR/rl-pester.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/rl-pester.txt -Tail 20; exit $code
```

- **Baseline first.** Before the first edit, row 0 checks that `psutil` imports, then runs the
  full pytest, the staged credits pytest and the staged Pester gate once on the unchanged tree,
  keeping `rl-full-pytest-baseline.txt`, `rl-credits-stage-baseline.txt` and
  `rl-pester-baseline.txt`. Each must pass. If one fails, row 0 fails and execution stops for
  the human: a gate that is red before the change cannot show what the change broke.
- **Input identity.** Identity is `git rev-parse HEAD` plus `git status --porcelain` plus
  `python --version`, captured into the handoff at each stage.

### 4. AC grep checks (AC-17, AC-19, AC-20, AC-21 (g))

The task rows encode these as Python one-liners in the 2026-09-19 style.

---

## Decision Log

```yaml
decision_log:
  - id: D-1
    stage: planning
    question: "Does token budgets 'off' also turn off the USD caps on scheduled credits runs?"
    resolution: human
    class: governance-value
    chosen: "Yes. Under token_budgets: off, a scheduled credits manifest may omit its USD caps, and an uncapped segment runs with no --max-budget-usd. Under on, or with no repo file, the caps stay required."
    source_tag: Human-approved
    precedents: ["Invoke-ClaudeCredits.ps1:272 — MaxBudgetUsd 0 already means no cap for the manual runner", "credits_state.py runs.segment_cap_usd and run_cap_usd — nullable columns; manual runs already store NULL"]
    research: { engine: none, sources: ["none: internal governance question"] }
    reasoning: "The human chose one switch for no budgets. The segment timeout, the Task Scheduler limit and the human-only resume still bound an unattended run, and the repo file is read again at each admission, so switching back on takes effect."
    human_message_reference: "USER_EXPLICIT 2026-10-20 '1. limit should be off as well'"
  - id: D-2
    stage: planning
    question: "May a plan be less strict than the setup choice?"
    resolution: human
    class: governance-value
    chosen: "Yes, only when the value is in a human-typed offer and the bound authorization verifies it; otherwise tighten-only."
    source_tag: Human-approved
    precedents: ["core/tools/run_parameters.py _within — tighten-only inheritance grouping → plan → task"]
    research: { engine: none, sources: ["none: internal governance question"] }
    reasoning: "The human chose this. It follows M-3: a looser cap is a policy change, so the human makes it."
    human_message_reference: "USER_EXPLICIT 2026-10-20 '1. yes'"
  - id: D-3
    stage: planning
    question: "Where does the setup choice live, and what does it hold?"
    resolution: autonomous
    class: two-way
    chosen: ".agent/review-limits.json with all five modes plus the token_budgets switch"
    source_tag: Local Canon
    precedents: ["scripts/instantiate.py:163 CREDITS_CONFIG = '.agent/credits/config.json' — setup answers land in a JSON file under .agent/", "review_ledger.py ROUND_BUDGETS — the five modes share one resolver"]
    research: { engine: none, sources: ["none: internal design question"] }
    reasoning: "Holding all five modes means one resolver serves them all and adds no special case. A key inside run-parameters.policy.json would tie the limits to a Windows-only, pinned file."
  - id: D-4
    stage: planning
    question: "Does the plan block store 'repo' or concrete numbers?"
    resolution: autonomous
    class: two-way
    chosen: "Concrete numbers plus a basis field"
    source_tag: Local Canon
    precedents: ["create-plan.md Step 0 — the run_parameters block stores resolved values, never a reference"]
    research: { engine: none, sources: ["none"] }
    reasoning: "A plan that a reviewer approved must not change limits when someone later edits the repo file. The basis field keeps the relation auditable."
  - id: D-5
    stage: planning
    question: "Is the plan parameter a key inside run_parameters, or a sibling block?"
    resolution: autonomous
    class: two-way
    chosen: "A sibling review_limits block. Only loosening goes through run_parameters (limits-check)."
    source_tag: Local Canon
    precedents: ["run_parameters.py _check_block — BLOCK_KEYS is an exact set and the block is Windows-only and disabled under policy_missing", "review_ledger.py — stdlib-only, reads the plan via --ac-file already"]
    research: { engine: none, sources: ["none"] }
    reasoning: "With a sibling block, the repo defaults and tightening work on every platform and in this repo, where run parameters are disabled. Putting the key inside run_parameters would make the feature disappear wherever run parameters are off. It would also force a run-parameters/2 block, a grouping-line change and a migration of every carrier."
  - id: D-6
    stage: planning
    question: "Pin .agent/review-limits.json in the run-parameters policy?"
    resolution: autonomous
    class: two-way
    chosen: "No. The ledger records the file's sha256 in limits_source instead."
    source_tag: Local Canon
    precedents: ["core/.agent/run-parameters.policy.json.template — pins tool components, not adopter configuration such as .agent/credits/config.json"]
    research: { engine: none, sources: ["none"] }
    reasoning: "Pinning would turn run parameters off whenever the human changed a cap. Recording the digest in the ledger keeps each loop auditable without that cost."
  - id: D-7
    stage: planning
    question: "How is 'off' represented, and what lifts it?"
    resolution: autonomous
    class: two-way
    chosen: "The string 'off' in the ledger and the plan block. 0 or null is refused (exit 3). continue --tokens on an 'off' loop is refused."
    source_tag: Local Canon
    precedents: ["review_ledger.py tokens_spent — the `or` fallback makes 0 or null mean 'default', so a sentinel number cannot mean off"]
    research: { engine: none, sources: ["none"] }
    reasoning: "An explicit word cannot be confused with a missing value. Refusing 0 or null closes the silent fallback."
  - id: D-8
    stage: planning
    question: "Where does the final audit get its execution round cap?"
    resolution: autonomous
    class: two-way
    chosen: "The ledger's rounds_allowed() for exec-<slug>. A missing ledger under a task with a review_limits block is refused. Only a legacy task with no block uses the repo file, then 6. The task block is never a cap on its own."
    source_tag: Local Canon
    precedents: ["run_parameters.py:3425 EXEC_REVIEW_MAX_ROUNDS = 6 passed at 3746/3767 (e667fb6) — ignores rounds a human bought with continue"]
    research: { engine: none, sources: ["none"] }
    reasoning: "The ledger is the record of what the human allowed, and its base was resolved and verified at begin. A fixed 6 fails an audit that a human-approved continue made legitimate. Falling back to the unverified task block would let a plan loosen its own audit cap without passing limits-check (review round 1, F-002)."
  - id: D-9
    stage: planning
    question: "Behavior off Windows, or with run parameters disabled?"
    resolution: autonomous
    class: two-way
    chosen: "Repo defaults and tightening work. A loosened block is refused (fail-closed)."
    source_tag: Local Canon
    precedents: ["run_parameters.py status — enabled:false makes every authorizing path unavailable"]
    research: { engine: none, sources: ["none"] }
    reasoning: "D-2 requires verification. Where nothing can verify, the only safe answer is the stricter limit."
  - id: D-10
    stage: planning
    question: "Does this plan itself carry a run_parameters block?"
    resolution: autonomous
    class: two-way
    chosen: "No. The authorization is manual, so the block is omitted."
    source_tag: Local Canon
    precedents: ["docs/execution/plans/2026-09-26-governance-migration — no block; user directed execution in chat"]
    research: { engine: none, sources: ["none"] }
    reasoning: "A manual block authorizes nothing. Omitting it keeps the earlier rules: the human says proceed, and nothing is committed."
  - id: D-11
    stage: planning
    question: "Under token_budgets: off, does a cap that the manifest gives still bind, and does switching back on reach a registered run?"
    resolution: autonomous
    class: two-way
    chosen: "A present cap still binds. Each admission of a run with a NULL cap re-reads the repo file, and under on it rejects with caps_required."
    source_tag: Local Canon
    precedents: ["credits_state.py verb_admit — a rejected first start fails with start_refused and a rejected resume stops with resume_refused"]
    research: { engine: none, sources: ["none: internal design question"] }
    reasoning: "Off removes the requirement, not a limit the human wrote. Reading the switch only at register would let a run registered under off stay uncapped after the human turned budgets back on."
  - id: D-12
    stage: planning
    question: "What exposure does an uncapped segment with an unknown cost book?"
    resolution: autonomous
    class: two-way
    chosen: "An exposure of 0 with cost_known 0."
    source_tag: Local Canon
    precedents: ["credits_state.py finalize_segment — the exposure equals the reservation; exposures.exposed_usd is NOT NULL"]
    research: { engine: none, sources: ["none"] }
    reasoning: "The reservation of an uncapped segment is 0, so the existing rule already gives 0. cost_known 0 keeps the unknown cost visible to the operator, and no cap reads the exposure."
  - id: D-13
    stage: planning
    question: "How does credits_state.py read the repo switch?"
    resolution: autonomous
    class: two-way
    chosen: "Through review_ledger.load_repo_limits(root), imported from the same tools folder when a cap is omitted."
    source_tag: Local Canon
    precedents: ["CreditsRun.psm1:34 — credits_state.py runs from <repo>/tools, beside review_ledger.py", "review_ledger.py — stdlib-only, with no import-time side effects"]
    research: { engine: none, sources: ["none"] }
    reasoning: "One reader means one definition of a valid file. Both modules stay stdlib-only, and a capped manifest never imports the ledger."
```

### D-1 — Should token budgets "off" also turn off the USD caps on credits runs?

**Resolved by the human:** USER_EXPLICIT 2026-10-20 "1. limit should be off as well".
- **What it means:** under `token_budgets: "off"`, a scheduled credits manifest may omit its USD caps, and an
  uncapped segment runs with no `--max-budget-usd`. A cap that the manifest gives still binds (D-11).
- **What still bounds a run:** the segment `timeout_sec`, the Task Scheduler limit and the human-only resume.
- **Reversibility:** two-way. Setting the repo back to `"on"` stops an uncapped run at its next admission (AC-21 (c)).

**Precedents:**
- `Invoke-ClaudeCredits.ps1:272`: `-MaxBudgetUsd 0` already means no cap.
- `credits_state.py`: the `runs` cap columns are nullable, and manual runs already store NULL.

**Research:** none (an internal governance question).

| Option | Source | Pros | Cons | Verdict |
|--------|--------|------|------|---------|
| `token_budgets: off` also lets credits manifests omit the USD caps (chosen) | the human | One switch for "no budgets", as asked | No dollar ceiling on an uncapped unattended run; the timeouts remain | ✅ |
| Keep the USD caps independent | earlier plan default | Keeps a spend ceiling | Not what the human chose | ❌ |
| A separate setup switch for the USD caps | — | Explicit | A governance surface the human did not ask for | ❌ |

---

## Research References

- None external: this is an internal governance change. The precedents are cited in the Decision Log.

## Validation stage contract

- **Static:** pyflakes (or py_compile).
- **Targeted:** the ledger selftest, the four new test files and the instantiate selftest.
- **Fresh full:** all pytest under `core/tools/tests` and `scripts/tests`, refcheck, the run-parameters
  policy check, the task lint, and the staged credits pytest and Pester gates. The working directory is the repo root, except the policy check, which runs from `core/`, and the staged pytest, which runs from the stage.
- **Blocking:** every stage blocks, and no failure is excused. Row 0 proves that the unchanged tree passes the same
  gates, so any failure after a change is the change's.
- **Input identity:** HEAD plus porcelain status plus the Python version, captured at each stage.
- **Final review:** the final implementation review follows one fresh full run, and intermediate reuse is disabled.
- **MEU tools:** D9: no MEU tools; `meus: []` is a no-op for the MEU state.
