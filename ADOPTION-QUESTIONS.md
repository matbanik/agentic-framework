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
| A4c | **Is the repo — or the receipts directory — inside a cloud-sync working copy?** (Google Drive, iCloud Drive, OneDrive, Dropbox). Answer per path; a repo on Drive with receipts on local disk is a different answer from both-on-Drive. | receipts location (A4b/F3); whether `git` operations need a local clone; the `</dev/null` and file-settling rules in `cli-dispatch/SKILL.md` | **`yes`** — assume sync until you have checked the *actual* path, not the shortcut you type |
| A4d | **Which dispatcher is canonical here** — one named script, chosen once? (`Invoke-CodexDispatch.ps1` on Windows; `Invoke-CodexDispatch.sh` on macOS/Linux; likewise `.ps1` vs `.sh` for `agent-commit`) | which leg gets exercised, and therefore which leg's bugs get found; see `macos-setup.md` §0.1 | the `.sh` on macOS/Linux, the `.ps1` on Windows — **and only one**, recorded in `PROJECT-PROFILE.md` |
| A5 | What are the harness's **read**, **run-command**, and **end-turn** primitives called? | `read_tool` / `shell_tool` / `end_turn_signal` substitution table | generic verbs |
| A6 | Does it support **assistant-addressable subagents** (a `Task`/Agent tool the *orchestrator* can call, not only user-invoked `/name` agents)? To what nesting depth? | `fresh_worker` in `harness-profiles.md` + `.agent/skills/subagent-delegation/SKILL.md` | **`none`** (every `isolated` row degrades to `compact_continue`; metadata is never permission to spawn) |
| A6b | **Is there a standing policy against spawning subagents** — in the user's global config, the project's `CLAUDE.md`/`AGENTS.md`, or a house rule — even though A6 says the capability exists? | a hard override on `fresh_worker`: capability present, use **forbidden**; every `isolated` row degrades to `compact_continue` exactly as if A6 were `none` | **`yes`** — treat spawning as forbidden until a human confirms otherwise |
| A7 | Does it support **transcript compaction**? | `context_compaction` | `none` |
| A8 | After an independent reviewer approves a plan, should execution **auto-continue**, or must a **human say go**? | `plan_to_exec_gate` | **`human`** |
| A9 | If A6 is yes: which **builder / verifier** capability classes should `task.md` `builder_model` name? Bind those classes in the registry from A10; shipped `.cursor/agents` / `.claude/agents` files are AUTOGEN templates, not hand-maintained pins. | `builder_model` column + AUTOGEN agent-def `model:` | keep work on the coordinator; do not invent `auto` |
| A10 | Where will the **live model-capability registry** live? Copy the package-root `.agent/` template to that shared or workspace-root home and fill `catalog` and `bindings` yourself. | live registry home; see `.agent/INSTANTIATE.md` | instantiate a workspace-root `.agent/` from this package's template. **Do not** copy another machine's filled registry |

> **Why A4c is not a trivia question.** A cloud-sync daemon is a second writer to your
> filesystem, and it does not know about your agent. Three things break, all of them
> intermittently — which is the worst way for them to break:
>
> - **A receipt read back before the daemon settles** yields a truncated or empty file, so a
>   gate reads "no output" and concludes the command produced none. That is a false pass
>   built on an unread artifact.
> - **`.git` inside a sync copy** can be mutated mid-operation by the daemon, and sync
>   conflict files (`foo (1).py`, `foo-conflicted.md`) appear as untracked additions that a
>   `git add -A` will happily commit.
> - **Path identity differs from what you type.** The shortcut, the `~` alias, and the real
>   on-disk path may be three different strings; a check that resolves one and a write that
>   resolves another will not agree. Verify with the resolved absolute path.
>
> The fix is placement, not cleverness: keep receipts on local disk, outside the repo, and
> outside any synced tree. Note that `/tmp` satisfies all three and is **wiped on reboot**,
> so it is fine for a run and wrong for anything you intend to keep.

> **Why A4d exists.** Shipping two legs of the same tool (`.ps1` and `.sh`) creates a
> maintenance trap: the leg you rarely run is the leg whose bugs survive. Choose one per
> platform, write it down, and let the other stay a documented alternative rather than a
> coin-flip. They are equivalent, not complementary — alternating between them is how a
> signing-config or path-resolution difference goes unnoticed for months.

---

## Block B — Independent Review
*(Configures: the reviewer chain + the self-review prohibition. This is the framework's core quality mechanism — an agent grading its own homework is the failure mode it exists to prevent.)*

| # | Question | Configures | Fail-safe default |
|---|---|---|---|
| B1 | Is a **second, different-vendor agent** available to review the driver's work? Which? (e.g. Codex/GPT if the driver is Claude, or vice-versa) | reviewer chain rung 1 | none → escalate to B4 |
| B2 | **If a reviewer CLI is available:** is it authenticated by **API key (metered, costs money per call)** or **subscription (flat)**? | the billing-notification protocol; how aggressively to delegate | assume **API key** (warn before every dispatch) |
| B3 | Is a **third** reviewer available as a fallback (e.g. Gemini), and is it suitable only for *surface-level* work? | reviewer chain rungs 2–3 | none |
| B3b | **Does each fallback rung fail by a different mechanism than the rung above it?** Name the mechanism each rung depends on: the CLI binary, the auth/credential store, the network egress path, the vendor's API. | whether the chain is a real chain or one rung wearing three hats | assume **not diverse** — collapse the chain to one rung plus B4's human, rather than counting rungs that die together |
| B4 | **If NO automated independent reviewer exists:** who is the **human reviewer**, and what is the escalation path? | the no-dispatch fallback | **A human MUST review.** Self-review is never a fallback. |
| B5 | How many review rounds before escalating to a human? | round caps (default: plan 3, execution 6) | 3 / 6 |

> ⚠️ **The one rule that never bends:** the agent that produced the work never authors its own
> `approved` verdict. If B1–B4 all fail, the work **stops and waits for a human** — it does not
> self-approve.

> **On B3b — vendor diversity is not mechanism diversity.** Two reviewers from two different
> vendors, both dispatched by the same wrapper through the same shell, sharing one egress
> path, are one reviewer for availability purposes: an expired credential, a wrapper
> regression, a proxy change, or a corporate egress block takes out both at once. That is the
> moment the chain is supposed to help, and the moment it does not.
>
> Count rungs by *what has to be working*, not by whose model answers. A chain of
> `CLI-A → CLI-B → named human` has two mechanisms; `CLI-A → CLI-B` via one wrapper has one.
> A rung that cannot fail independently is not a fallback, it is a second name for the first
> rung — and believing you have three when you have one is worse than knowing you have one,
> because it is the belief that stops you from arranging a human.

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
| C3b | If C3 = yes: **what scans the payload, and is the scan run on the exact file that gets dispatched?** Name the detector, and name the arm that proves it can still match (a fixture containing a known-sensitive string it must flag). | the pre-dispatch verification step; the detector's proof-of-failure arm | **no dispatch** — an unverified redaction is an unredacted dispatch |
| C4 | If no external egress is permitted: use **local-only review** (a second local model / a fresh isolated same-vendor context) or **human-only review**. Which? | the reviewer chain replacement | **human-only** |

> **On C3b — scan the payload, not the repo.** The natural move is to grep the working tree
> for sensitive patterns and, finding none, dispatch. That check answers a different question
> than the one that matters. What leaves the machine is one assembled prompt: a file the
> wrapper built from selected diffs, quoted file excerpts, error output, conversation
> summary, and possibly environment values. A clean tree says nothing about that file's
> contents, and a redaction applied to the tree may simply not be in the copy that was
> assembled first.
>
> So the scan runs **on the payload file, after it is written and before the dispatch call**,
> and a non-empty result blocks the dispatch rather than warning about it. Keep the payload
> for the receipt: the artifact you can re-scan afterwards is the only evidence of what was
> actually sent.
>
> And a detector that matches nothing is not evidence of a clean payload unless that detector
> has been shown able to match. Keep one fixture holding a string it must flag, and run it in
> the same invocation. Zero findings from an unproven detector and zero findings from a
> working one are the same output and opposite facts.

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
| F3 | Where may the agent write **temp/receipt files** (command output)? Must satisfy all four: **absolute** path · **outside the repo** · **outside any cloud-sync tree** (A4c) · **created before the first command that redirects into it**. | the P0 redirect directory; `{{RECEIPTS_DIR}}` | a temp dir outside the repo |
| F3b | Do receipts need to **survive a reboot** (post-hoc audit, a review spanning days) or only the run? | whether `/tmp` is acceptable, or a durable local directory is required | **survive** — `/tmp` is wiped on reboot, so use a durable local path and prune it deliberately |
| F4 | Is there **version control**? Which? | the commit gate | assume git; never auto-commit |
| F5 | Which **snapshots** will you put in your registry catalog for coordinator / builder / router classes? | `model-routing.md` names classes; the catalog binds them (see `.agent/INSTANTIATE.md`) | one snapshot for every class if that is all you have |
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
