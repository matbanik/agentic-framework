# Human Decision Protocol

> **Scope:** every question, choice or decision for the human, in any form: an AskUserQuestion
> popup, a question in chat text, plan Open Questions (`create-plan.md` §2B), reviewer
> human-decision items (§5b), the round-cap TL;DR (§5e), reviewer questions with no local-canon
> answer (§5f), triage architecture decisions (`issue-triage.md` Step 8), grouping §8 tables
> (`session-grouping.md`), execution-time forks, closeout, research and side-quest sessions, and
> a subagent return that carries an open decision.
> **It never loosens a hard gate.** The hard gates of `AGENTS.md` and its authorization rules
> (§Authority and Approval, `GUARDRAILS.md` SIGN 1–3) set who can approve what. This protocol sets
> what the agent presents at a stop and whether a question gets to one.

**Rule in one line:** decide before you ask. A decision gets to the human only after the
precedent sweep (§2) and the research (§3), only when it is still the human's to make, and only
as a brief that starts with a recommendation. The agent decides the rest and writes it down.

---

## 1. Trigger

Run this protocol the moment you are about to write any of: "open question", "human decision
required", "needs your call", "which do you prefer", an options list without a recommendation, or
a `[B]` row with a `Decision:` line. Run it once per decision, not once per session; batch the
resulting briefs at the workflow's existing stop rather than inventing a new one.

---

## 2. Precedent sweep (codebase first)

Before any research, find where {{PROJECT_NAME_TITLE}} already made a decision of the same
*class* (same kind of trade-off, not the same feature). Read what was decided, by whom, and
whether it stuck.
If a prior ruling settles the decision, apply it and cite it. Then no research is necessary.

| Where prior decisions live | What to look for |
|---|---|
| `.agent/context/current-focus.md` | The current priority and the recent rulings of the user |
| `.agent/context/grouping/*.md` §8 "Open Decisions for the Human" | D1..Dn tables with options, recommendation, and the user's ruling |
| `docs/execution/plans/*/implementation-plan.md` "Decision Log" / "Open Questions" / "Protected Decisions" | Decision Options Tables, `Human-approved` and `Research-backed` outcomes |
| `docs/execution/reflections/*.md` "Decisions Log" | Autonomous decisions and their reasoning; whether a later review overturned them |
| `.agent/context/handoffs/*.md` | `Human-approved` tags, reviewer human-decision items and how they were closed |
| The project's ADR directory (e.g. `docs/adrs/`) | Architecture decision records (Considered Options / Decision Outcome) |
| `.agent/docs/emerging-standards.md`, `.agent/context/known-issues.yaml` | A standard or a triaged issue that already settles the question |
| `AGENTS.md`, `GUARDRAILS.md`, the plan's source build-plan section | Rules that make one option non-negotiable |
| Agent memory (harness-provided, if any) | Standing user rulings from earlier sessions |

---

## 3. Research

Research each open fact that can change the recommendation, before you decide or ask. Use again
a source that already settles the fact. A technical choice stays open until a source settles it.
A local measurement counts as research: git history, a test run or a simulation often decides
more than a web query. For a web search, use the search tool of the harness
(`harness-profiles.md` `web_search_tool`) and the `deep-research-prompting` skill.
If no search tool is available, write `research: unavailable — <reason>` in the Refs line, and
do the sweep all the same. Give each source with its one-line takeaway.

---

## 4. Synthesis and the obviousness test

Weigh the precedents and research against project constraints (architecture, existing patterns,
user workflows, reversibility, cost of a wrong default). Then apply the test. **The decision is
the agent's to make** — no stop, no question — when **all** of these hold:

1. **Convergence:** a precedent of the same class already decided it and nothing contradicts it,
   *or* the sources agree on one option.
2. **Two-way door:** the choice is reversible at ordinary cost (a config default, a naming
   choice, an internal structure, a UI arrangement) and is not on the hard-gate list.
3. **No product fork:** no materially different user-visible behaviors remain plausible.
4. **Not a governance number:** it does not introduce a novel threshold, limit, budget, or
   policy value (those keep the `development-lifecycle.md` "Threshold sign-off" gate).

When all four hold: decide, tag the criterion `Local Canon` or `Research-backed`, record the
decision as §6 tells you, and continue. Do not ask the human to confirm an obvious choice — that
is the over-clarification the calibration literature measures as a cost, and it is exactly what
this protocol exists to remove.

When any fails, the decision is human-gated. Classify it so the brief says why:

| Class | Failing test | Typical example |
|---|---|---|
| `one-way-door` | 2 | Schema migration that drops data, public API shape, licence/vendor lock-in |
| `product-preference` | 3 | Which of two coherent UX flows the owner wants |
| `source-conflict` | 1 | Local canon says X, official docs say Y, both current |
| `governance-value` | 4 | A new quota, cap, or retention window |
| `externally-blocked` | — | Needs a credential, purchase, or third-party answer |

---

## 4a. Mandatory-human criteria and the `decisions:` modes

The plan's `run_parameters.decisions` value (`create-plan.md` Step 0) selects one of two modes. A
plan without a `run_parameters` block uses `hdp`.

- **`hdp`** (default): check the M-list below **before** the §4 test. An M hit is human-gated
  whatever the obviousness test says, and it is logged with `mandatory: [M-n, …]`. A question
  with no M hit goes through the §4 test and is logged with `mandatory: none`.
- **`human-all`**: every *unresolved discretionary decision* in this protocol's scope (a
  question with two or more materially different plausible answers that the Planning Contract
  order does not settle) is human-gated. The precedent sweep and the research rung still run,
  and the brief still leads with a recommendation. Use it for an unfamiliar domain or a
  sensitive phase.

In both modes, implementation choices with one plausible answer, bookkeeping, and the
carrying-out of approved rows are not decisions. In a headless run, an M hit, or any brief under
`human-all`, is a `[B]` (c) row with the bounded gate wait (`.agent/skills/claude-credits/SKILL.md`),
then `STOPPED:decision` when no ruling arrives.

| Id | Always human | Source |
| :- | :- | :- |
| M-1 | Push to any remote; **every** merge (shared or lane branch); tag; release; deploy. No parameter covers these. This restates `AGENTS.md` §Authority and Approval; it narrows nothing and adds nothing. | `AGENTS.md` §Authority and Approval |
| M-2 | Destructive data operations (`AGENTS.md` §Authority and Approval, unchanged: the rule has no disposable-data exemption and this list grants none); deletion of backups; secret or credential rotation; a change to who may read a secret. | `AGENTS.md` §Authority and Approval; this protocol's scope note |
| M-3 | **New policy**: a new or changed threshold, cap, budget, round cap or retention window; any edit to `AGENTS.md`, `GUARDRAILS.md`, a hook, `stop_gate.py`, `commit_gate.py`, the model registry or this protocol that changes what is allowed. A mechanical repair under existing policy (a broken path, a typo, a test that pins the current rule) is not an M-3 hit, and carrying out an approved plan row that makes an M-3 edit is not one either; deciding to make an edit the plan does not hold is. | §4 test 4 |
| M-4 | One-way doors not already in the approved plan: a schema migration that drops or rewrites data, a public API or MCP tool shape, a published or external contract (the public repo's docs, an interface a third party consumes), licence or vendor lock-in, and **any** external spend that the approved plan did not declare (a declared budget authorizes spend up to it; nothing authorizes spend outside it). | §4 class table (`one-way-door`) |
| M-5 | A user-visible product fork with no local canon **and** materially different plausible behaviours: palette, a surface split, a feature on or off, UX wording that changes meaning. A wording choice with one plausible reading is the agent's. | §4 class table (`product-preference`) |
| M-6 | A source conflict that the Planning Contract order (local canon, then primary sources) does not settle, and any conflict with a prior `USER_EXPLICIT` ruling. | §4 class table (`source-conflict`) |
| M-7 | A change to an existing test's assertion that no approved plan row specifically calls for (a row that names the test and the new assertion; a general "fix the tests" row is not one). The setup-and-fixture repair carve-out stays the agent's. | `AGENTS.md` §Testing & TDD Protocol |
| M-8 | A change to an approved plan's *acceptance or scope*: a new or dropped MEU (or work unit) or acceptance criterion, a moved session order, a reviewer finding adopted as new scope. Bookkeeping rows (a receipt, a status flip, an evidence row) and ordinary review corrections inside the approved acceptance criteria are not scope changes and never stop. | `AGENTS.md` §Planning Contract |
| M-9 | Review-loop exits that are already sanctioned stops: every round cap, the stagnation rule, every reviewer rung unavailable. The late-round materiality bar is the agent's judgement inside the loop, not a permission. | `AGENTS.md` §Execution Contract (review cap, reviewer unavailable) |
| M-10 | A required **human action**: a credential, a purchase, a third-party answer, a physical action (a VM console, an installer). A transient failure the plan authorizes the agent to retry (a flaky network call, a busy file) is not an M-10 hit. | §4 class table (`externally-blocked`) |
| M-11 | Waiving a **blocking** quality gate, test or review step: a skip, `xfail`, `--no-verify`, a waived external validation, a bypassed hook, a lowered floor that the gate enforces. Advisory floors (coverage, the security scans) stay advisory and are not M-11 hits. | `AGENTS.md` §Validation Pipeline, §Independent Review |
| M-12 | A new external disclosure: a push to a public repository, an email or issue to a third party, a published artifact, a message to another organization's session. | `AGENTS.md` §Authority and Approval |
| M-13 | Widening the agent's own permissions: a settings allow rule, a bypass flag, a sandbox or classifier exemption, a new MCP server, a new trusted remote. | the harness permission model (`harness-profiles.md`) |
| M-14 | Headless start, resume or fork authority: who may start a scheduled run, resume a stopped one, or fork it, and with which grants. | `GUARDRAILS.md` SIGN 3 (b) |

Everything else is the agent's to decide under §4, logged as `autonomous` with
`mandatory: none`. Six notes:

- The list gates *new decisions*, never the carrying-out of rows the human already approved. A
  plan row that edits `GUARDRAILS.md`, changes a test or rotates a credential was an M hit at
  planning time and is executed as approved.
- The list is a floor on top of every existing human-only gate; gates the list does not name
  stay in force (for example the model-routing rules,
  `model-routing.md`).
- M-3 covers edits to this list and to this protocol: they are human-approved, never
  autonomous, except a ruling that the human hands to the agent under §6.
- `human-all` adds every unresolved discretionary decision; there is no per-item mode table.
- Neither mode exempts anything: `human-all` never overrides a hard gate, and `hdp` still
  escalates every question that fails the obviousness test, M hit or not.
- An M hit names every matching item (`mandatory: [M-3, M-11]`), and the brief states each.

Outside the M-list and the failing tests, do not ask the human to confirm a choice the
obviousness test already settled: that is the over-clarification cost of §4, and it is the one
thing this section never adds.

---

## 5. Decision Brief — how a human-gated decision is presented

**Two outcomes.** The agent decides and states the decision in one line, or asks with a brief.
When the human must do something (M-10), the agent writes a short request: what, why, and what
the agent does in the meantime. A human action is not a choice, so the request has no options.

One brief per decision, in this form:

```markdown
### D-n: <the question in plain words>

**I recommend A: <what happens, in plain words>.** <Why: the decisive fact or precedent. The
concrete way that A can fail, and the undo cost.>

- B: <what happens, and what it costs compared with A.>

Refs: <precedent paths>, <sources>, <M-n>.
```

Rules:

- **Plain words.** The question, the options and the recommendation use plain words about
  outcomes. Internal ids (M-n, AC-n, MEU-n, SIGN n, EA-n) go only in the Refs line.
- **Recommendation first.** A reply of "yes" accepts the recommendation. Add an option only
  when it is a real choice. "Keep the status quo" is an option when it is real. A table is
  optional: use it when the options are different on more than one point.
- **The reader decides from the brief alone.** No "I can research further if you want".
- **Ask at plan time**, before the work, when the answer has the most value.
- **Without an answer**, the agent waits on that item and works on independent rows. The brief
  says what happens without an answer only when something else happens. A popup timeout is
  never an answer (issue anthropics/claude-code#73125, `GUARDRAILS.md` SIGN 3 (a)).
- **Batch at the existing stop.** Briefs are presented at the workflow's own human gate (plan
  `## Decision Log`, the §5e TL;DR, the triage Step 8 report, the grouping §8 table). Presenting
  them ends the turn per the harness `end_turn_signal`; do not poll or monitor for the reply
  (`gate-wait-then-exit` is the one bounded wait, defined in `harness-profiles.md`).
- **Advisory, not authorizing.** A recommendation never substitutes for the human's explicit
  message where a hard gate applies (`GUARDRAILS.md` SIGN 3 (a)).

---

## 5a. Expert pass — one review of a set of briefs

Before the human sees a set of briefs at a planned stop, the author gets one expert pass on the
set, in a fresh context. A reference to this step says "HDP §5a".

1. Send the set to the advisory peer reviewer (`peer_reviewer`) in a fresh context. Give the
   domain, the stage in three lines and the paths of the briefs and of the files that they cite.
   The packet template is `.agent/skills/expert-pass/SKILL.md`.
2. For each recommendation the reviewer answers three questions. Does it add work that the
   present stage does not need? Can it be done as written, at the present size? Can it be undone?
3. The reviewer checks that each named thing exists, and names a cheaper option when the brief
   lists none.
4. The result for each brief is one of four: holds, cut down, changed or widened, each with its
   evidence. "Holds" is a valid result.
5. The author checks each finding against the files. Then the author adopts it, or does not
   adopt it and gives the evidence.
6. One line goes above the set: `Expert pass (fresh context): <n> briefs. Holds: <ids>.
   Changed: <ids>. Not adopted: <ids>.` A brief gets its own line only in two cases: `Expert
   pass: changed from <X>: <reason>.` when the pass changed it, and `Expert pass: <result>, not
   adopted: <reason>.` when the author did not adopt the finding.

The pass is advice. It makes no ruling, writes no verdict file and adds no tool, hook, schema or
record field. It runs once for each set, in one round. `Expert pass: inline.` is for one
question during other work. `Expert pass: inline, not independent.` is for a run that cannot
start a fresh context. `Expert pass: not run: the human said to skip it.` is the only skip. A
request for a human action (M-10) gets no pass. The step names a role, and no model or effort.
There is no floor and no skip rule by set size.

## 6. Recording — every decision leaves a trail

Record each human ruling, and each consequential new choice or departure from precedent,
once, in the log of the stage that made it. A decision that applies an existing ruling gets
no new record. Each record is one Decision Log entry:

```yaml
decision_log:
  - id: D-1
    stage: planning | plan-review | execution | closeout | triage | grouping
    question: "one line"
    resolution: autonomous | human
    class: two-way | one-way-door | product-preference | source-conflict | governance-value | externally-blocked
    mandatory: [M-n, …] | none                  # §4a; omitted when the plan has no run_parameters block
    chosen: "option"
    source_tag: Local Canon | Research-backed | Human-approved
    precedents: ["path:line — what it decided"]
    research:
      engine: tavily | exa | native | codex-search | none
      sources: ["URL — takeaway"]
    reasoning: "why this option; why the alternatives lost"
    human_message_reference: "USER_EXPLICIT YYYY-MM-DD '<quote>'"   # human-resolved only
```

A brief written before any plan file exists (the Step 0 intake of `create-plan.md` or
`session-grouping.md`) uses `stage: planning` and lists its unruled items under
`open_decisions:`. There is no other stage value and no class alias.

Where it lives:

| Stage | Location |
|---|---|
| Planning | `implementation-plan.md` `## Decision Log` (replaces bare Open Questions; human-gated entries are the briefs, autonomous entries are the record) |
| Plan review / corrections | The rolling `-plan-critical-review.md` correction log, then folded into the plan's Decision Log |
| Execution | The MEU handoff's `## Decision Log` — a fenced `decision_log:` YAML block with the same entry shape, or exactly `None.` (`meu-handoff.md`, `.agent/templates/HANDOFF-TEMPLATE.md`) — and the `[B]` row's `Decision:` line when a row is held |
| Triage | The issue's `enrichment.decision_log` list in `known-issues.yaml` (`issue-triage.md` §3.5) — `enrichment` is the only per-issue field that survives `issue_triage.py triage` regenerating `triage-output.yaml`, so the log is never written to `triage-output.yaml` directly |
| Grouping | The grouping file's `## 8. Open Decisions` canonical table (`session-grouping.md` row 8): each D-row a brief, Resolution `autonomous` / `human` / `open`. The closeout reads each row with stage `grouping`. |
| Closeout | The reflection's `### Decisions Log` (under Execution Trace) is a short list. It holds the choices that the agent made without asking and that someone could want to reverse. Each entry is one line with a link to the full entry in the stage log. `None.` is valid. A human ruling, a grouping row or an applied ruling does not go on the list. |

`tools/validate_closeout_artifacts.py --reflection … --decision-source {plan} --decision-source
{handoff} [--decision-source {grouping-file}] [--decision-source known-issues.yaml --decision-issue ID]`
(task row H2-2) reads these records, and its messages cite this section. Each plan, handoff and
issue entry must state the question, the choice and the reasoning, and a `chosen` that still
starts with `pending` is refused. Two logs must give one decision the same stage. The reflection's
`### Decisions Log` is not compared with them: the check refuses only the template's example line
left in place, and `None.` is valid. A `decision_log:` is read only from a fenced ```yaml or
`~~~yaml` block, indented or not (a handoff's section is exactly `None.` or one such block, with
the template's instruction comment and closing rule allowed around it); the key in prose or in any
other fence is refused rather than skipped. A source is a grouping by its `## 8. Open Decisions`
heading, or by being the file the plan's frontmatter declares as `grouping_source`; a handoff is
known by its `plan_source` frontmatter or `handoff` filename; a plan is anything else. A block
outside the reader's bounded YAML grammar, a `decision_log:` nested under another key, and a
grouping table in an ad-hoc shape are refused rather than read as empty.
A decision that was made and written nowhere cannot be caught by a validator, so record it at the
moment of deciding, not at closeout.

A decision resolved autonomously in planning and later overturned by the human is recorded, not
deleted: append the ruling with `human_message_reference` and keep the original reasoning.

A ruling that the human hands to the agent for one brief set is the agent's ruling. Record it
with `resolution: autonomous` and the agent's own basis tag, never `Human-approved`, and keep the
entry's `mandatory:` list. The reasoning starts with `Handed to the agent: USER_EXPLICIT <date>
'<quote>'.`, and that quote meets the gate. An acceptance criterion that rests on the ruling
carries the same tag. The hand-over covers one set only, and only an item with no M hit or with
M-3, M-5, M-6 or M-8; every other item of §4a stays the human's. One line from the human
overturns it.

---

## 7. Basis

- **Local origin:** G24 (`emerging-standards.md` — a plan once listed bare open questions the
  user had to research by hand), generalised to every workflow stage on 2026-09-29.
- **Recommendation first:** MADR (https://adr.github.io/madr/). **Reversibility:** the one-way
  and two-way door test (https://fs.blog/reversible-irreversible-decisions/).
- **When to ask:** "Ask or Assume?" (arXiv 2603.26233): a calibrated agent asks less on clear
  tasks and asks on underspecified ones. A check against earlier answers removed 13 % of the
  questions (arXiv 2610.24411).
