# Adoption Questions — Answer These FIRST

> **You are an AI agent adopting this framework into a new project.** Do not copy a single
> file until you have answers to Blocks A–D. Each question configures a specific,
> named part of the framework — the "Configures" line tells you exactly what.
>
> **Rules for you, the adopting agent:**
> - **Ask the human. Do not guess.** A wrong answer here silently disables a safety gate.
> - If an answer is unknown, use the **fail-safe default** shown. Never invent a permissive one.
> - Some blocks are conditional — skip them only when the trigger says so.
> - Record the answers in `PROJECT-PROFILE.md` at the adopting project's root. That file
>   becomes the single source of truth every workflow reads.

---

## Block A — Harness & Environment
*(Configures: `harness-profiles.md` — the capability profile. Without this, every gate misfires.)*

| # | Question | Configures | Fail-safe default |
|---|---|---|---|
| A1 | Which agentic harness is the **primary driver** (the agent doing discovery, analysis, and execution)? e.g. Claude Code, Cursor, Codex CLI, Gemini, Copilot, a custom SDK loop | `role: primary-driver`; the profile row | `UNKNOWN` row |
| A2 | Is the driver **embedded inside a host** (an IDE/platform) that can inject messages into the conversation — e.g. an auto-approve or "review policy" feature? | `injects_auto_approval` → GUARDRAILS SIGN 3 | **`yes`** (assume injection risk) |
| A3 | Can the driver **run shell commands / spawn subprocesses**? | `can_dispatch_external_reviewer` | `no` |
| A4 | OS and shell? (Windows+PowerShell / macOS+zsh / Linux+bash / sandboxed sh) | `native_shell` + the redirect-to-file rule | `posix-sh` |
| A4b | **Platform shell contract:** target OS · where receipt files live (absolute path, created before first command) · is **`pwsh` available** on macOS/Linux (needed for `Invoke-CodexDispatch.ps1` and Windows-style examples)? | P0 redirect form in every registered command; `{{RECEIPTS_DIR}}` in `instantiate.py`; see `core/.agent/docs/macos-setup.md` | receipts under a temp dir **outside** the repo; assume **`pwsh` not installed`** on macOS/Linux until confirmed |
| A5 | What are the harness's **read**, **run-command**, and **end-turn** primitives called? | `read_tool` / `shell_tool` / `end_turn_signal` substitution table | generic verbs |
| A6 | Does it support **assistant-addressable subagents** (a `Task`/Agent tool the *orchestrator* can call, not only user-invoked `/name` agents)? To what nesting depth? | `fresh_worker` in `harness-profiles.md` + `.agent/skills/subagent-delegation/SKILL.md` | **`none`** (every `isolated` row degrades to `compact_continue`; metadata is never permission to spawn) |
| A7 | Does it support **transcript compaction**? | `context_compaction` | `none` |
| A8 | After an independent reviewer approves a plan, should execution **auto-continue**, or must a **human say go**? | `plan_to_exec_gate` | **`human`** |
| A9 | If A6 is yes: which **builder / verifier** model pins should the planner use? (Cursor-style: fast builder + optional stronger builder; Claude-style: Sonnet/Opus.) | `builder_model` column on `task.md` + agent-def `model:` frontmatter | keep work on the coordinator; do not invent `auto` |

---

## Block B — Independent Review
*(Configures: the reviewer chain + the self-review prohibition. This is the framework's core quality mechanism — an agent grading its own homework is the failure mode it exists to prevent.)*

| # | Question | Configures | Fail-safe default |
|---|---|---|---|
| B1 | Is a **second, different-vendor agent** available to review the driver's work? Which? (e.g. Codex/GPT if the driver is Claude, or vice-versa) | reviewer chain rung 1 | none → escalate to B4 |
| B2 | **If a reviewer CLI is available:** is it authenticated by **API key (metered, costs money per call)** or **subscription (flat)**? | the billing-notification protocol; how aggressively to delegate | assume **API key** (warn before every dispatch) |
| B3 | Is a **third** reviewer available as a fallback (e.g. Gemini), and is it suitable only for *surface-level* work? | reviewer chain rungs 2–3 | none |
| B4 | **If NO automated independent reviewer exists:** who is the **human reviewer**, and what is the escalation path? | the no-dispatch fallback | **A human MUST review.** Self-review is never a fallback. |
| B5 | How many review rounds before escalating to a human? | round caps (default: plan 3, execution 6) | 3 / 6 |

> ⚠️ **The one rule that never bends:** the agent that produced the work never authors its own
> `approved` verdict. If B1–B4 all fail, the work **stops and waits for a human** — it does not
> self-approve.

---

## Block C — Data Sensitivity & Egress ⚠️ **ASK THIS EVEN IF IT SEEMS OBVIOUS**
*(Configures: whether the external-reviewer step is legal/permissible at all.)*

**Why this block exists:** The independent-review step **transmits your work product to a
third-party model provider.** In a coding project that is usually harmless. In other domains it
can be a serious breach:

- **Legal** — may waive attorney–client privilege or breach a confidentiality duty.
- **Health** — sending PHI to an external API can be a HIPAA/GDPR violation absent a BAA/DPA.
- **Research** — may break embargo, IRB/consent terms, or export-control rules.
- **Business** — may leak trade secrets or MNPI.

| # | Question | Configures | Fail-safe default |
|---|---|---|---|
| C1 | Does the work product contain **regulated, privileged, or confidential** data? (PHI, PII, privileged communications, MNPI, classified, embargoed, human-subjects data) | whether external dispatch is allowed at all | **`yes`** |
| C2 | If yes: is there a **legal basis** to send it to each external provider (BAA / DPA / vendor approval / de-identification)? | which reviewer rungs are permitted | **none permitted** |
| C3 | Can the content be **de-identified or redacted** before review, so an external reviewer sees only a safe abstraction? | a redaction step before dispatch | require redaction |
| C4 | If no external egress is permitted: use **local-only review** (a second local model / a fresh isolated same-vendor context) or **human-only review**. Which? | the reviewer chain replacement | **human-only** |

> **If C1 = yes and C2 = none:** disable external-CLI dispatch entirely. Set
> `can_dispatch_external_reviewer: no` and route review to a human. The framework still works —
> the self-review prohibition is satisfied by a *human* reviewer. **Never** silently fall back to
> self-review because dispatch was blocked.

---

## Block D — Domain Semantics (the generalization)
*(Configures: what "unit of work", "evidence", "tests-first", and "done" mean here. See `DOMAIN-MAPPING.md` for worked translations.)*

| # | Question | Configures | Fail-safe default |
|---|---|---|---|
| D1 | What is the **domain**? (software / legal / clinical / research / finance / policy / ops / writing) | which mapping row in `DOMAIN-MAPPING.md` to apply | ask |
| D2 | What is the **atomic unit of work** (this framework's "MEU")? *A code module? A contract clause? A differential diagnosis? A literature-review section? A filing item?* | MEU decomposition, `task.md` rows | ask |
| D3 | What is the **canonical source of truth** the work must conform to? *Spec/build-plan? Statute + case law + the contract? Clinical guideline/protocol? Pre-registered protocol + prior literature?* | the "Spec" source label; the Spec Sufficiency Gate | ask |
| D4 | What counts as **evidence** that a unit is correctly done? *Passing tests? Cited controlling authority? Guideline-concordant reasoning + contraindication check? A reproducible analysis with data provenance?* | the evidence bundle; "no completion without evidence" | ask |
| D5 | What is the **criteria-before-work** artifact (the "tests-first" analogue)? *Test cases? Elements to prove? Decision criteria + red flags? Pre-registered hypothesis + analysis plan?* | the FIC (Feature Intent Contract) | ask |
| D6 | What are the **validation checks** — the commands or procedures that produce evidence? *pytest/lint/typecheck? Citation + authority validator? Guideline checklist? Assumption checks + reproducibility run?* | the quality gate | ask |
| D7 | What is the **definition of done**? | Exit Criteria | ask |
| D8 | What are your **issue component** names and **ID prefixes** for known-issues? *(software: core/api/ui; legal: memo/filing/research; clinical: guideline/order/note)* | `tools/issue_triage/model.py` → `VALID_COMPONENTS` + issue-triage skill prefix table | keep shipped defaults until you replace them |
| D9 | Do you want the **issue → MEU → plan** learning loop (`/issue-triage` → `/session-grouping` → `/create-plan` + reflection design rules)? | copy `tools/issue_triage*`, `tools/meu_status*`, context seeds; see `triage-meu-loop.md` | **yes** for multi-session work; skip only for one-off tasks |

---

## Block E — Irreversible Actions & Accountability
*(Configures: the human approval gates. Get this wrong and an agent does something it cannot undo.)*

| # | Question | Configures | Fail-safe default |
|---|---|---|---|
| E1 | Which actions are **irreversible or externally visible**? *Commit/push/deploy/delete? Filing with a court? Sending advice to a client? A patient-facing recommendation? Publishing/submitting? Sending email to a third party? Moving money?* | the mandatory human-approval list | treat **every** outward-facing action as gated |
| E2 | What is the **harm potential** of an error? (annoyance → financial loss → legal exposure → physical harm) | review depth; model tier; whether to escalate effort | assume high |
| E3 | Which **regulatory/ethical regimes** apply? (HIPAA, GDPR, privilege/UPL, IRB, SEC/FINRA, export control) | domain guardrails (new SIGNs) | ask |
| E4 | Who is the **accountable human** who must sign off? (engineer / attorney of record / licensed clinician / PI / compliance officer) | the approver identity in every gate | ask — there must be one |
| E5 | What must the agent **never do autonomously**, regardless of approval? *(e.g. give legal or medical advice directly to an end user; execute a trade; contact a patient)* | absolute prohibitions (new SIGNs) | ask |

---

## Block F — Artifacts, State & Process Tuning
*(Configures: where durable state lives — the precondition that makes compaction and session-resume safe.)*

| # | Question | Configures | Fail-safe default |
|---|---|---|---|
| F1 | Where do **plans and task lists** live? | plan folder path | `docs/execution/plans/` |
| F2 | Where do **handoffs, reviews, reflections** live? | artifact paths + naming | `.agent/context/handoffs/` |
| F3 | Where may the agent write **temp/receipt files** (command output)? | the P0 redirect directory | a temp dir outside the repo |
| F4 | Is there **version control**? Which? | the commit gate | assume git; never auto-commit |
| F5 | Which **models** are available for coordinator / builder / router tiers? | `model-routing.md` | single model for all |
| F6 | Any **cost constraints**? (metered API vs flat subscription) | how aggressively to delegate to subagents | assume metered |

---

## After you have the answers

1. Write `PROJECT-PROFILE.md` at the adopting project's root, recording every answer above.
2. Follow `ADOPTION-GUIDE.md` step by step — it tells you which files to copy, what to
   parameterize, and what to delete.
3. Use `DOMAIN-MAPPING.md` to translate the coding vocabulary (MEU, TDD, tests, lint) into
   your domain's equivalents.

**The single most common adoption failure** is copying the files without answering Block C and
Block E — which yields an agent that cheerfully ships irreversible actions and emails privileged
content to a third-party model. Answer them.
