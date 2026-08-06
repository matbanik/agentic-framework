# PROJECT PROFILE — <project name>

> Produced by the adopting agent in **Step 1** of `ADOPTION-GUIDE.md`, by interviewing the human
> with `ADOPTION-QUESTIONS.md`. Copy this to the adopting project's root as `PROJECT-PROFILE.md`.
>
> **Every workflow in this framework reads this file.** It is the single source of truth for
> "what kind of project is this, and what is this agent allowed to do?"
>
> Unanswered ⇒ use the fail-safe default. Never invent a permissive answer.

**Date:** <YYYY-MM-DD> · **Interviewed:** <human name/role> · **Status:** `draft | confirmed`

---

## A — Harness & Environment  → `harness-profiles.md`

| Flag | Value | Notes |
|---|---|---|
| Primary driver (A1) | | e.g. Claude Code / Cursor / Codex / Gemini / custom |
| Host layer, if embedded (A2) | | e.g. runs as a plugin inside an IDE |
| `injects_auto_approval` (A2) | `yes` \| `no` | **default `yes`** — assume injection risk |
| `can_dispatch_external_reviewer` (A3) | `yes` \| `no` | default `no` |
| `native_shell` (A4) | `powershell` \| `bash` \| `posix-sh` | default `posix-sh` |
| `read_tool` / `shell_tool` / `end_turn_signal` (A5) | | |
| Subagents + nesting depth (A6) | | |
| `context_compaction` (A7) | | `none` ⇒ ~50% checkpoint becomes a hand-back |
| `plan_to_exec_gate` (A8) | `human` \| `reviewer-auto` | **default `human`** |

> If driver + host are both present, apply the **per-flag merge**: gate = most restrictive;
> injection = `yes` if either; tools/shell = the driver's.

---

## B — Independent Review  → `model-routing.md`

| Item | Value |
|---|---|
| Reviewer rung 1 (different vendor from driver) (B1) | |
| Auth mode: **API key (metered)** or **subscription** (B2) | |
| Reviewer rung 2 / 3 (B3) | |
| Human reviewer + escalation path (B4) | |
| Round caps (B5) | plan: __ · execution: __ |

> **Never bends:** the agent that produced the work does not author its own `approved` verdict.
> If no reviewer is reachable → **stop and wait for a human.** Self-review is never the fallback.

---

## C — Data Sensitivity & Egress ⚠️

| Question | Answer |
|---|---|
| Regulated/privileged/confidential content? (C1) | `yes` \| `no` (**default `yes`**) |
| Legal basis to send to each external provider? (C2) | e.g. BAA / DPA / none |
| De-identification or redaction possible? (C3) | |
| If no egress permitted → review mode (C4) | `local-only` \| **`human-only`** |

**Decision:** external-CLI dispatch is `PERMITTED` / `PROHIBITED`.
*If PROHIBITED:* set `can_dispatch_external_reviewer: no` and name the human reviewer above.

---

## D — Domain Semantics  → `DOMAIN-MAPPING.md`

| Concept | This project's equivalent |
|---|---|
| Domain (D1) | software / legal / clinical / research / finance / other: ___ |
| Unit of work — the "MEU" (D2) | |
| Canonical source of truth — "Spec" (D3) | |
| What counts as **evidence** (D4) | |
| **Criteria-before-work** artifact (the FIC) (D5) | |
| Validation checks / commands (D6) | |
| Definition of done (D7) | |

---

## E — Irreversible Actions & Accountability

| Question | Answer |
|---|---|
| Irreversible / outward-facing actions (E1) | *(each of these gets a hard human gate)* |
| Harm potential (E2) | annoyance / financial / legal / physical |
| Regulatory regimes (E3) | e.g. HIPAA, GDPR, privilege, IRB, SEC |
| **Accountable human** who signs off (E4) | *(there must be one)* |
| Never-autonomous, regardless of approval (E5) | |

> Write E3 and E5 as new **SIGNs** in `GUARDRAILS.md` (honor the deletion budget).

---

## F — Artifacts, State & Tuning

| Item | Value |
|---|---|
| Plans / task lists (F1) | |
| Handoffs / reviews / reflections (F2) | |
| Temp/receipt output dir (F3) | |
| Version control + commit gate (F4) | |
| Models: coordinator / builder / router (F5) | |
| Cost constraints (F6) | metered / flat |

---

## Sign-off

- [ ] All blocks answered, or fail-safe defaults applied and marked.
- [ ] Every irreversible action (E1) has an explicit human gate.
- [ ] Reviewer chain configured **or** external dispatch disabled with a human reviewer named.
- [ ] Domain guardrails (E3/E5) written as SIGNs.

**Confirmed by:** <human> · **Date:** <YYYY-MM-DD>
