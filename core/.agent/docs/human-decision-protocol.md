# Human Decision Protocol

> **Scope:** every place a workflow would hand a decision or question to the human — plan
> Open Questions (`create-plan.md` §2B), reviewer human-decision items (§5b), the round-cap
> TL;DR (§5d), reviewer questions with no local-canon answer (§5e), triage architecture
> decisions (`issue-triage.md` Step 8), grouping §8 tables (`session-grouping.md`), execution-time
> forks where an acceptance criterion proves unreachable as written, and closeout.
> **It never loosens a hard gate.** Commit/push/merge/deploy, destructive data operations, the
> plan→execution transition under `plan_to_exec_gate: human`, and review round caps stay human
> stops regardless of how obvious the answer looks (`AGENTS.md`, `GUARDRAILS.md` SIGN 1–3).
> This protocol governs *what is presented* at a stop and *whether a question survives to one*
> — not whether the gate exists.

**Rule in one line:** a decision reaches the human only after a precedent sweep and web research
have been done, only if it is still genuinely theirs to make, and only as a Decision Brief that
leads with a recommendation. Everything else is decided by the agent and written down.

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

| Where prior decisions live | What to look for |
|---|---|
| `.agent/context/grouping/*.md` §8 "Open Decisions for the Human" | D1..Dn tables with options, recommendation, and the user's ruling |
| `docs/execution/plans/*/implementation-plan.md` "Decision Log" / "Open Questions" / "Protected Decisions" | Decision Options Tables, `Human-approved` and `Research-backed` outcomes |
| `docs/execution/reflections/*.md` "Decisions Log" | Autonomous decisions and their reasoning; whether a later review overturned them |
| `.agent/context/handoffs/*.md` | `Human-approved` tags, reviewer human-decision items and how they were closed |
| The project's ADR directory (e.g. `docs/adrs/`) | Architecture decision records (Considered Options / Decision Outcome) |
| `.agent/docs/emerging-standards.md`, `.agent/context/known-issues.yaml` | A standard or a triaged issue that already settles the question |
| `AGENTS.md`, `GUARDRAILS.md`, the plan's source build-plan section | Rules that make one option non-negotiable |
| Agent memory (harness-provided, if any) | Standing user rulings from earlier sessions |

Search with `rg` under the P0 receipt pattern (`AGENTS.md` §Windows Shell: every stream
redirected to the receipts directory, exit code captured before anything else; the sweep is
exact evidence, so it runs through `rtk proxy`). `rg` exits 1 on zero matches — that is the
legitimate empty-sweep result, not an error. Match the redirect syntax to the resolved
`native_shell`:

```bash
rtk proxy rg -n -i "Human-approved|Human-decision-required|Decision Options Table|Open Decisions" .agent/context docs/execution --glob '*.md' > {{RECEIPTS_DIR}}/precedent-sweep.txt 2>&1; code=$?; cat {{RECEIPTS_DIR}}/precedent-sweep.txt; exit $code
```

```powershell
rtk proxy rg -n -i "Human-approved|Human-decision-required|Decision Options Table|Open Decisions" .agent/context docs/execution --glob '*.md' *> {{RECEIPTS_DIR}}/precedent-sweep.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/precedent-sweep.txt; exit $code
```

Open a context/MCP tool for this sweep only when `context-tool-decision-gate.md` already makes
it eligible for the session.

**Output:** a Precedent row per hit — `path:line`, what was decided, who decided (`USER_EXPLICIT`
/ reviewer / agent), and whether it applies directly, by analogy, or contradicts the current
options. A sweep with zero hits is a legitimate result and is recorded as such.

---

## 3. Web research (any search beats none)

Research every decision that survives the sweep. Resolve the search surface once per session in
this order and record which rung you used (`harness-profiles.md` `web_search_tool`):

1. **A registered research MCP** (e.g. Pomera `pomera_web_search` with engine `tavily` for
   grounded answers or `exa` for neural / semantic recall) — preferred when present
   (`deep-research-prompting/SKILL.md`).
2. **Harness-native web search** — `WebSearch` (Claude Code), `search_web` (Antigravity), or the
   equivalent the harness exposes.
3. **Codex `--search`** via `cli-dispatch/SKILL.md` `-UseSearch`, when the driver has no search
   tool but can dispatch.
4. **None available** — say so in the brief (`research: unavailable — <reason>`), still present
   the precedent sweep, and never present the question bare. Absence of a search tool is a
   provenance stamp, not an exemption.

Run 2–3 queries per decision, one per angle:

| Angle | Query shape | Why |
|---|---|---|
| **Production practice** | "how do {domain tools / frameworks} handle {decision}" | What others actually shipped |
| **Standards / official docs** | "{standard, RFC, framework docs} {decision}" | A citable authority (counts as `Research-backed`) |
| **Recent AI-era approaches** | "{decision} agent / LLM {current year}" or "novel approach {decision}" | Newer patterns the human may not know about |

Cite the URL and the one-line takeaway per source. A vendor blog is evidence of practice; a
standard or official doc is evidence of authority; a paper is evidence of a novel approach —
label which.

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

When all four hold: decide, tag the criterion `Local Canon` or `Research-backed`, write the
Decision Log entry (§6), and continue. Do not ask the human to confirm an obvious choice — that
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

## 5. Decision Brief — how a human-gated decision is presented

One brief per decision, recommendation first, in this order:

```markdown
### D-{n}: {decision in one line}   [{class}] [{stage}]

**Recommendation:** {option} — {two or three sentences on why this is the right call here}.

**Why not the others**
| Option | Pros (vs. recommendation) | Cons (vs. recommendation) | Sources |
|---|---|---|---|
| ✅ {recommended} | — | — | {precedent path:line}, {URL} |
| ⚠️ {alternative A} | {what it does better} | {what it costs} | {URL} |
| ❌ {alternative B, incl. "status quo / do nothing" when real} | … | … | … |

**Precedent:** {what the project decided before on this class, or "none found"}.
**Research:** {engine used}; {one-line takeaway per source}. {or "unavailable — reason"}
**Reversibility / risk:** {one-way | two-way}; {what breaks if the choice is wrong}.
**If you do not answer:** {what the agent will do — usually "carry the recommendation as a guarded task row" or "hold the row [B]"}.
```

Rules:

- **Recommendation first, always.** A brief that opens with the options list, or ends with
  "let me know which you prefer", is malformed.
- **Pros and cons are relative.** Each alternative is compared against the recommendation and
  against the other alternatives — not listed as free-standing attributes.
- **Two to four options.** Include "do nothing / keep the status quo" whenever it is a real
  choice; never pad with straw options.
- **The reader decides from the brief alone.** No "I can research further if you want".
- **Batch at the existing stop.** Briefs are presented at the workflow's own human gate (plan
  `## Decision Log`, the §5d TL;DR, the triage Step 8 report, the grouping §8 table). Presenting
  them ends the turn per the harness `end_turn_signal`; do not poll or monitor for the reply.
- **Advisory, not authorizing.** A recommendation never substitutes for the human's explicit
  message where a hard gate applies (`GUARDRAILS.md` SIGN 3 (a)).

---

## 6. Recording — every decision leaves a trail

Every decision, autonomous or human-gated, gets one Decision Log entry:

```yaml
decision_log:
  - id: D-1
    stage: planning | plan-review | execution | closeout | triage | grouping
    question: "one line"
    resolution: autonomous | human
    class: two-way | one-way-door | product-preference | source-conflict | governance-value | externally-blocked
    chosen: "option"
    source_tag: Local Canon | Research-backed | Human-approved
    precedents: ["path:line — what it decided"]
    research:
      engine: tavily | exa | native | codex-search | none
      sources: ["URL — takeaway"]
    reasoning: "why this option; why the alternatives lost"
    human_message_reference: "USER_EXPLICIT YYYY-MM-DD '<quote>'"   # human-resolved only
```

Where it lives:

| Stage | Location |
|---|---|
| Planning | `implementation-plan.md` `## Decision Log` (replaces bare Open Questions; human-gated entries are the briefs, autonomous entries are the record) |
| Plan review / corrections | The rolling `-plan-critical-review.md` correction log, then folded into the plan's Decision Log |
| Execution | The MEU handoff's `## Decision Log` — a fenced `decision_log:` YAML block with the same entry shape, or exactly `None.` (`meu-handoff.md`, `.agent/templates/HANDOFF-TEMPLATE.md`) — and the `[B]` row's `Decision:` line when a row is held |
| Triage | The issue's `enrichment.decision_log` list in `known-issues.yaml` (`issue-triage.md` §3.5) — `enrichment` is the only per-issue field that survives `issue_triage.py triage` regenerating `triage-output.yaml`, so the log is never written to `triage-output.yaml` directly |
| Grouping | The grouping file's `## 8. Open Decisions` canonical table (`session-grouping.md` row 8): each D-row a brief, Resolution `autonomous` / `human` / `open`. Every row is carried into the consuming session's reflection with stage `grouping` — an open grouping question that was never ruled or recorded is silence too |
| Closeout | The reflection's `### Decisions Log` (under Execution Trace) — **every** autonomous decision of the session with its reasoning, so the human reads it after the fact and a later reviewer can contest it. This is the only place the human sees decisions the agent did not stop for; omitting it turns autonomy into silence. |

**Enforced, not advisory.** `tools/validate_closeout_artifacts.py --reflection … --decision-source
{plan} --decision-source {handoff} [--decision-source {grouping-file}] [--decision-source
known-issues.yaml --decision-issue ID]` (task row H2-2) reconciles the reflection's
`### Decisions Log` with every decision recorded in the plan's `## Decision Log`, each handoff's
`## Decision Log`, the grouping's `## 8. Open Decisions` table (a source is a grouping by that
heading in its structure — a heading quoted inside a fence, ``` or `~~~` and each closed
only by its own marker, or an HTML comment is an example, not a signal, and the section
itself is located the same way — or by being the file the
plan's frontmatter declares as `grouping_source` — a relative
declaration resolves from the plan's project root, the nearest ancestor holding `.agent/`,
never from the working directory and never by suffix — and a plan that declares a real one
refuses to reconcile unless that very file is among the sources, whatever else the plan
quotes; a handoff is known by its `plan_source` frontmatter — a YAML null such as
`plan_source: null` or `~` is no value, exactly as `grouping_source: null` is no
declaration — or `handoff` filename, a plan is anything else, and a grouping that also
declares a `grouping_source`, carries a handoff's signals or records a `decision_log:` key
in any shape YAML can write one is refused rather than routed by whichever check ran
first), and the
closed issue's `enrichment.decision_log`: every recorded ID needs a reflection row with the
same stage, every row needs its question, chosen option and reasoning filled, an unfilled
template example is refused, and `None.` passes only when no source recorded a decision. A
`decision_log:` is read only from a fenced ```yaml or `~~~yaml` block, indented or not (a
handoff's section is exactly `None.` or one such block, with the template's instruction
comment and closing rule allowed around it); the key in prose or in any fence other than a
```diff/```patch excerpt is refused rather than skipped, and it is found wherever YAML can
put a key — at line start, under one or more `- ` sequence markers, inside a `{...}`/`[...]`
flow collection, plain or quoted — so no shape reads as zero decisions: a quoted root key
is read, a `decision_log:` nested under another key or inside a flow collection — with or
without a root key beside it — written as a sequence item, or written as a second root key
is refused rather than read as empty or last-wins (the words in a quoted scalar, a block
scalar or a comment are text, not keys), a key written twice in one block mapping of a
record is refused rather than read first-wins (duplicates inside a flow collection are
outside this walk; the bounded grammar bounds their shape), a
block outside the reader's bounded YAML grammar (one construct per line;
quoted scalars with YAML's escapes and flow collections with paired brackets and no empty
entry close on their line; one indentation level is a mapping or a sequence, never both;
nothing indents under a scalar value) is refused rather than read, a grouping table in an
ad-hoc shape is refused rather than ignored, and a `--decision-issue`
the file does not hold — or a known-issues file whose `issues:` is not the root key — is
refused rather than read as empty.
A decision that was made and written nowhere cannot be caught by a validator — that is why the
Decisions Log is written at the moment of deciding, not reconstructed at closeout.

A decision resolved autonomously in planning and later overturned by the human is recorded, not
deleted: append the ruling with `human_message_reference` and keep the original reasoning.

---

## 7. Anti-patterns

- Bare questions ("Should X be A or B?") with no precedent sweep, research, or recommendation.
- Asking the human to confirm a choice the obviousness test already settled.
- Deciding an irreversible or product-shaping question autonomously because the research
  "seemed clear".
- Listing pros and cons as free-standing bullets that never compare the options.
- Presenting a brief and then continuing to work on the assumption the human will agree
  (post-and-wait: present, end the turn).
- Skipping research because no search tool is configured instead of stamping `research:
  unavailable`.
- Omitting the reflection Decisions Log, so autonomous decisions leave no trail.

---

## 8. Research basis

- **Decision-memo practice** (recommendation first, 2–3 real alternatives including the status
  quo, pros/cons per option): policy-memo guides from Harvard Kennedy School / Shorenstein and
  Stanford; the same shape as MADR's *Considered Options → Pros and Cons → Decision Outcome*
  (https://adr.github.io/madr/).
- **Reversibility as the escalation axis:** Amazon's one-way / two-way door heuristic
  (https://fs.blog/reversible-irreversible-decisions/; thoughtbot on applying it to engineering
  decisions).
- **Ask-vs-act calibration in coding agents:** "Ask or Assume? Uncertainty-Aware
  Clarification-Seeking in Coding Agents" (arXiv 2603.26233) — calibrated agents conserve
  questions on simple tasks and ask on genuinely underspecified ones; Calibrate-Then-Act
  (arXiv 2602.16699); AgentAbstain (arXiv 2607.10059); ReDAct (arXiv 2604.07036); uncertainty
  decomposition for clarification (arXiv 2606.19559); Hedwig dynamic autonomy under local
  oversight (arXiv 2605.11495) — oversight tightens outside familiar territory and relaxes where
  trust is earned, which is what the precedent sweep operationalises.
- **HITL escalation triggers** (uncertainty, novelty, stakes): Galileo and Atlassian agent-design
  guides; arXiv 2609.24242, 2605.14830.
- **Local origin:** G24 (`emerging-standards.md` — a plan once listed bare open questions the
  user had to research by hand) generalised to every workflow stage on 2026-09-29.
