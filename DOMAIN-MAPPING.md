# Domain Mapping — Translating the Framework Beyond Code

> This framework was hardened on a software project, so its vocabulary is code-flavored
> (MEU, TDD, tests, lint). **The vocabulary is incidental. The discipline is not.**
>
> Underneath the jargon there are six domain-independent ideas:
>
> 1. **Decompose** work into units small enough to verify.
> 2. **Write the acceptance criteria BEFORE doing the work** (anti–post-hoc-rationalization).
> 3. **Produce evidence**, not assertions, that each unit is done.
> 4. **Have someone else check it** — never grade your own homework.
> 5. **Stop at a human** before anything irreversible.
> 6. **Keep durable state in files**, so a summary or a crash never loses it.
>
> Every one of those is *more* valuable in law, medicine, and research than it is in code,
> because the cost of a confident-but-wrong answer is higher.

---

## The core translation table

| Framework concept | Software | Legal | Clinical / Health | Scientific Research | Finance / Compliance |
|---|---|---|---|---|---|
| **MEU** (unit of work) | A module, endpoint, or feature slice | A contract clause; one cause of action; one memo issue | One clinical question; one differential; one care-plan element | One hypothesis, analysis, or literature-review section | One control, reconciliation, or filing item |
| **Canonical source of truth** ("Spec") | Build plan / product spec / API contract | Statute, regulation, controlling case law, the contract itself | Clinical guideline, protocol, formulary, label | Pre-registered protocol, prior literature, method standard | Regulation, accounting standard, internal policy |
| **FIC** (criteria written *before* work) | Test cases + acceptance criteria | **Elements to prove** + the authorities that govern each | **Decision criteria + red flags/contraindications** to check | **Pre-registered hypothesis + analysis plan** | Control objectives + assertions to test |
| **TDD "Red phase"** (fail first) | Write a failing test | List the elements you cannot yet support with authority | State the findings that would *change* the recommendation | State what result would **falsify** the hypothesis | State what would constitute a control failure |
| **Tests / evidence** | Passing test suite | Cited controlling authority, on point, verified as good law | Guideline-concordant reasoning + contraindications checked | Reproducible analysis + data provenance | Tie-out to source records; audit trail |
| **Quality gate** | `pytest`, type-check, lint | Citation validator (is it real? still good law? on point?), conflict check | Guideline checklist, interaction/allergy check, dose range | Assumption checks, reproducibility run, stats review | Reconciliation, variance thresholds, segregation of duties |
| **Regression test** (for a bug) | A test reproducing the bug, written first | The counter-argument that defeated you last time, now addressed | The missed red flag, now an explicit check | The confound that invalidated the last analysis | The control that failed, now tested |
| **Independent review** | Codex/GPT reviews Claude's code | Second attorney / opposing-counsel steel-man | Second clinician opinion; M&M review | Peer review; adversarial collaboration | Second-line review; internal audit |
| **In-harness subagent** (`fresh_worker` + builder/verifier) | Cursor `Task` / Claude Agent for mechanical rows | Junior associate drafts one clause against a fixed checklist | Scribe runs a structured checklist; clinician keeps judgment | RA runs a pre-registered analysis script | Analyst prepares a tie-out pack; reviewer keeps sign-off |
| **Known-issues → triage → MEU** | Bug/debt register → `/issue-triage` → MEU batches | Matter issues → elements buckets → work units | Safety events / gaps → care elements | Failed checks / confounds → study components | Control failures → remediation items |
| **Reflection design rules** | Next-session RULE-N into `/create-plan` | Lessons into next memo checklist | M&M learning into next protocol | Lab notebook rules into next pre-registration | Post-mortem controls into next workpaper |
| **Irreversible action** (human gate) | Commit, push, deploy, delete data | **Filing, sending client advice, executing a document** | **Any patient-facing recommendation or order** | **Submission, publication, releasing data** | **Executing a transaction, filing a report** |
| **Handoff** | Evidence bundle + changed files | Memo with authority table + open questions | Documented reasoning + evidence grade + uncertainties | Method + results + limitations | Workpaper with tie-outs |

---

## The source-label taxonomy (the most portable idea here)

The framework forbids **unsourced assertions**. Every acceptance criterion must be labeled:

| Label | Software | Legal | Health | Research |
|---|---|---|---|---|
| `Spec` | Explicit in the build plan | **Binding authority** (statute, controlling case, the contract) | Guideline/protocol/label directive | The pre-registered protocol |
| `Local Canon` | Another canonical project doc / ADR | Firm precedent, an approved template, prior filed position | Institutional policy, local formulary | Lab SOP, prior methods paper |
| `Research-backed` | Verified against official docs / primary sources | **Persuasive authority, secondary sources** — flagged as such | Literature, **with evidence grade attached** | Prior literature, cited |
| `Human-approved` | An explicit user decision | **Partner / attorney-of-record sign-off** | **Attending / licensed clinician sign-off** | **PI decision** |

> **"Best practice" alone is never an acceptable label.** In code that rule prevents sloppiness.
> In law it prevents **fabricated citations**. In medicine it prevents **confident hallucinated
> guidance**. This is the framework's single highest-value export — keep it verbatim.

---

## Per-domain guardrails to ADD (write these as new SIGNs in `GUARDRAILS.md`)

### Legal
- **Never send privileged/confidential material to an external model** without a documented basis (see Adoption Question C2). This can waive privilege.
- **Never present an uncited proposition as authority.** Every citation must be verified to exist, be on point, and still be good law. Hallucinated citations have produced real sanctions.
- **No unauthorized practice of law**: the agent drafts and analyzes; a licensed attorney advises. Never deliver legal advice directly to an end client.
- Run a **conflicts check** before substantive work.

### Clinical / Health
- **PHI never leaves the permitted boundary** (no external-CLI review of identifiable data absent a BAA). De-identify or use human-only review.
- **The agent never issues a patient-facing recommendation or order.** It prepares reasoning for a licensed clinician, who decides. This is an absolute prohibition (Adoption Question E5).
- **Always surface contraindications, interactions, and red flags** — including when they argue against the proposed course.
- Attach an **evidence grade** to every clinical claim. Ungraded assertion = defect.

### Scientific Research
- **Pre-register the hypothesis and analysis plan before looking at outcomes.** This is exactly the TDD Red phase, and it is what prevents p-hacking and HARKing.
- **Never modify the hypothesis to fit the result** — that is precisely the framework's "never modify the test to make it pass" rule, and it is a research-integrity violation.
- **Data provenance is mandatory**; analyses must be reproducible from raw inputs.
- Respect embargo / IRB / consent terms on any external egress.

### Finance / Compliance
- **No autonomous transactions.** Analysis and preparation only; execution is human-gated.
- Respect **MNPI / information barriers** — treat external model dispatch as disclosure.
- Every figure must **tie out** to a source record.

---

## What to rename when you port

Purely cosmetic, but it lowers friction for domain experts:

| Rename from | To (suggested) |
|---|---|
| MEU (Manageable Execution Unit) | Work Unit / Matter Item / Care Element / Study Component |
| TDD / tests-first | **Evidence-First** / Criteria-Before-Work |
| Red phase → Green phase | Criteria → Substantiation |
| Quality gate | Verification gate |
| `pytest` / `ruff` / `pyright` | Your Block-D6 validation checks |
| Build plan | Matter plan / Care plan / Study protocol / Control plan |
| Code review | Independent review |

**Do not rename** the safety machinery — `plan_to_exec_gate`, `injects_auto_approval`, the SIGNs,
the self-review prohibition, and the source labels. Those are the parts that actually keep the
agent honest, and renaming them invites drift.

---

## The one thing that does NOT port

The **P0 terminal/shell rules** (redirect-to-file, no-pipe, receipts directory) only matter if
your agent runs shell commands. If it doesn't, delete that section wholesale — but keep the
*principle* it encodes: **never let a long-running operation flood the agent's context.** In any
domain, dump bulk output to a file and read back only what you need.
