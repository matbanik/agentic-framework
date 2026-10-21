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
| Receipts path / pwsh availability (A4b) | | Git for Windows bash on Windows |
| Cloud-sync working copy? (A4c) | `yes` \| `no` | **default `yes`** until the real path is checked |
| Canonical dispatcher (A4d) | `.ps1` \| `.sh` | `.ps1` on Windows, `.sh` on macOS/Linux |
| `read_tool` / `shell_tool` / `end_turn_signal` (A5) | | |
| Subagents + nesting depth (A6) | | |
| Standing policy against spawning? (A6b) | `yes` \| `no` | **default `yes`** — treat spawning as forbidden until confirmed |
| `context_compaction` (A7) | | `none` ⇒ ~50% checkpoint becomes a hand-back |
| `web_search_tool` | research MCP \| native \| `codex-search` \| `none` | surface for `human-decision-protocol.md` §3; `none` needs a reason (e.g. Block C forbids it) |
| `plan_to_exec_gate` (A8) | `human` \| `reviewer-auto` | **default `human`** |
| `stop_notify` (A1, F7) | `hook` \| `notify-config` \| `prose` \| `none` | derived from the driver (A1); **default `none`** until F7 = yes and Step 4d's `test-send` passed |
| Builder/verifier classes (A9) | | only if A6 is yes; bind in the A10 registry |
| Registry home + deferral (A10) | path \| `deferred` | default `<project>/.agent-registry/` via **session-scoped** `AGENT_MODEL_REGISTRY_HOME`; `deferred` forbids dispatch until compiled JSON exists |
| Instruction loader + capabilities (A11) | | Record root/nested/import order and byte limit; verify sandbox repo/receipt writes; hooks disabled until tested |

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
| Round caps (B5; `instantiate.py --round-caps`) | plan: __ · execution: __ |
| Token budgets on review loops (B5b; `instantiate.py --token-budgets`) | on / off |

> **B5/B5b** land in `.agent/review-limits.json`. `off` removes the review loops' token stop and
> also lifts the USD caps on scheduled credits runs (a manifest may then omit them; a cap it
> gives still binds, and the segment timeout still applies). Switching back to `on` stops an
> uncapped run at its next admission.

> **Never bends:** the agent that produced the work does not author its own `approved` verdict.
> If no reviewer is reachable → **stop and wait for a human.** Self-review is never the fallback.

---

## C — Data Sensitivity & Egress ⚠️

| Question | Answer |
|---|---|
| Regulated/privileged/confidential content? (C1) | `yes` \| `no` (**default `yes`**) |
| Legal basis to send to each external provider? (C2) | e.g. BAA / DPA / none |
| De-identification or redaction possible? (C3) | |
| If C3 = yes: what scans the payload, and is the scan run on the exact file that gets dispatched? (C3b) | **default: no dispatch** — an unverified redaction is an unredacted dispatch |
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
| Validation checks / commands (D6) | **D6_ADOPTER_ARGV:** executable + argv **or** documented manual procedure; cwd; scope; blocking; expected result; shell; receipt path. Example only: `python -m pytest test_hello.py`. Not a universal default. |
| Validation stages / identity (D6 continued) | Register static, targeted, full, optional runtime checks individually; include shared fixture/config scope, `evidence.v1` format, and state-identity procedure covering code/tests/config/environment/external inputs. Full must be fresh; reuse disabled without proven identity. Manual checks name observer/procedure. |
| Definition of done (D7) | |
| Issue component names / ID prefixes (D8) | |
| Issue → MEU → plan learning loop? (D9) | `yes` \| `no` (**default `yes`** for multi-session; `no` skips MEU seeds/tools) |

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
| Receipts must survive reboot? (F3b) | `survive` \| `run-only` (**default `survive`**) |
| Durable evidence promotion (F3b continued) | Both retention modes require command/exit/decisive output in F1/F2 artifacts before closeout. Scratch paths alone never prove completion. PROFILE C governs redaction/storage. |
| Version control + commit gate (F4) | |
| Models: coordinator / builder / router (F5) | |
| Cost constraints (F6) | metered / flat |
| Stop-notification email (F7) | `no` \| `yes`: events, inbox role, credential store (**default `no`**, `enabled: false`; never write the address here) |

---

## G — Run Parameters  → `create-plan.md` Step 0, `human-decision-protocol.md` §4a

The four plan defaults, and the rules that bind them. A session of the grouping carries them
on its `Run parameters:` line (`session-grouping.md`); a plan may only tighten them.
Run parameters activate on Windows only for now: they need the Windows-only credits files, so
on another OS the tools stay, `status` reports `disabled` and plans keep the manual workflow
(`ADOPTION-GUIDE.md` §Scheduled credits runs).

| Item | Value |
|---|---|
| Decisions (G1) | `hdp` \| `human-all` (**default `hdp`**: the agent runs the decision protocol; the M-list of §4a always reaches the human) |
| Commit the approved plan before execution (G2) | `true` \| `false` (**default `true`**: the `PC` row) |
| Start execution right after the approved plan (G3) | `true` \| `false` (**default `true`**) |
| Commit when execution completes (G4) | `true` \| `false` (**default `true`**: the `COMMIT` row). Push stays `never`; it is M-1. |
| Who may grant an authorization, and for how long (G5) | *(the E4 human; one plan, or one grouping session)* |
| Commit scope (G6) | branch, paths *(F4)* |
| Transcript adapter (G7) | `claude-code` \| `none` (**fail-safe `none`**: every act fails closed and the manual workflow stays). Set `TRANSCRIPT_ADAPTER` in `tools/run_parameters.py`. |
| Headless runs (G8) | `no` \| `yes`: the acts each may do (the policy's `capabilities`) (**default `no`**) |
| Resume, fork and revocation (G9) | *(who may resume or fork a stopped run; how a grant is revoked)* |
| Domain acts that extend the M-list (G10) | *(from E1 and E5; each becomes a §4a row)* |

> The policy `.agent/run-parameters.policy.json` starts as a copy of
> `.agent/run-parameters.policy.json.template`. The template's digests are placeholders, so
> `tools/run_parameters.py status` reports `disabled` until you compute the digests from the
> instantiated tree and record the activation evidence. Links: E1–E5, F4.

---

## Sign-off

- [ ] All blocks answered, or fail-safe defaults applied and marked.
- [ ] Every irreversible action (E1) has an explicit human gate.
- [ ] Reviewer chain configured **or** external dispatch disabled with a human reviewer named.
- [ ] Run parameters (G) answered, or the four defaults applied and marked.
- [ ] Domain guardrails (E3/E5) written as SIGNs.

**Confirmed by:** <human> · **Date:** <YYYY-MM-DD>
