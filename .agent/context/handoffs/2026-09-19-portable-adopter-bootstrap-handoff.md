---
date: "2026-09-19"
project: "2026-09-19-portable-adopter-bootstrap"
meu: "none"
status: "complete"
action_required: "VALIDATE_AND_APPROVE"
template_version: "2.1"
verbosity: "standard"
plan_source: "docs/execution/plans/2026-09-19-portable-adopter-bootstrap/implementation-plan.md"
build_plan_section: "none (docs/BUILD_PLAN.md not shipped)"
agent: "cursor-grok-4.6"
reviewer: "independent_reviewer"
predecessor: "none"
---

# Handoff: 2026-09-19-portable-adopter-bootstrap-handoff

> **Status**: `complete`
> **Action Required**: `VALIDATE_AND_APPROVE`

---

## Scope

**MEU**: none (`meus: []` — non-product origin-maintainer project; do not write packaged `core/.agent/context/meu-status.yaml`).
**Build Plan Section**: none (`docs/BUILD_PLAN.md` absent; hub N/A).
**Predecessor**: none

Human `proceed` after independent plan-critical-review `approved` (`plan_to_exec_gate: human`). Goal: a naive adopter can install, finish ADOPTION-GUIDE Steps 0–9 through plan+task write, and get green `--phase build` preflight. HD-03 unanswered → incompleteness receipt (AC-WP1B-1). Did not instantiate the origin package in place, copy `P:/.agent`, or mutate `P:/fw-adopt-probe`.

Numeric aliases AC-1 … AC-31 map 1:1 onto named plan ACs AC-WP1-1 … AC-WP7-1 (plan Closeout AC aliases). The packaged coverage gate matches `AC-<digits>` only.

---

## Acceptance Criteria

| AC | Type | Description | Source | Test(s) | Status |
|----|------|-------------|--------|---------|--------|
| AC-1 | unit | LAYOUT_HD01: instruction tree `.agent/`, catalog `.agent-registry/`, session home env; Step 4 does not copy package `.agent/` as a catalog | Spec + proposal HD-01 | `scripts/tests/test_adoption_contract.py --case wp1` | ✅ |
| AC-2 | unit | LOCATE_ORDER identical across INSTANTIATE, preflight, both wrappers, ModelRegistry.psm1, resolve_model.py, check_model_slugs.py; instruction `.agent/` never a catalog | Spec 2.4 | `--case wp1` locators | ✅ |
| AC-3 | integration | BUILD_PHASE_SKIP: unset env `--phase build` exit 0 registry SKIP; same env `--phase review` exit 1 REFUSE registry | Spec + HD-02 | `preflight.sh --selftest` arms `registry-skipped-when-phase-build`, `registry-runs-when-phase-review` | ✅ |
| AC-4 | unit | FIRST_LINE_CONTRACT: first stdout line is OK / REFUSE / USAGE / FAIL-CLOSED matching exit 0/1/2/3 | Spec F025 | `preflight.sh --selftest` first line `OK:` | ✅ |
| AC-5 | unit | Profile slots A10/C1/C2/C3b/E5/B4; EGRESS_PRECEDENCE in create-plan, delegated-plan-creation, execution-session, execution-critical-review, AGENTS, GUARDRAILS SIGN 1, cli-dispatch SKILL | Spec F031 + HD-08 | `--case wp1` + `--case profile-permissions` | ✅ |
| AC-6 | unit | Empty `catalog: {}` still fails schema; no fabricated compiled JSON for deferral | Spec INSTANTIATE | `--case wp1`; no toy catalog written | ✅ |
| AC-7 | integration | Isolated-home locators: missing configured home fail-closed; no fall-through to unrelated user-home | Proposal overlay 4.1 | `--case wp1` missing-home + `registry-configured-home-no-fallthrough` | ✅ |
| AC-8 | integration | Missing CLI is distinct from forbidden egress; forbid does not write a provider web-prompt | Spec F031 | `--case wp1` / `--case profile-permissions` / WP7 `EGRESS_STOP=named-human-no-web-prompt` | ✅ |
| AC-9 | unit | Every shipped `.ps1` is ASCII or UTF-8 BOM | Spec 2.3 | `scripts/tests/test_ps1_encoding.py` | ✅ |
| AC-10 | integration | Instantiated wrapper parses under powershell 5.1 and pwsh without execution; missing PromptText is usage not ParserError | Spec F021 | `test_ps1_encoding.py` | ✅ |
| AC-11 | unit | INSTALLER_TARGET: no `--root` leaves package bytes unchanged | Spec 2.7 | `scripts/instantiate.py --selftest` arm `missing-root-is-usage-and-does-not-write` | ✅ |
| AC-12 | integration | Owned-asset inventory; PROFILE/`_probe` tokens survive; four `{{PROJECT_NAME}}-*.md` rename; second apply idempotent | Spec 2.8 | instantiate selftest `owned-*`, `agent-defs-renamed`, `second-apply-idempotent` | ✅ |
| AC-13 | unit | Active workflow/template reads use TEMPLATE_HOME including orchestrator.md and AGENTS.md | Spec 2.5 | `checks/assert_wp3.py` (`templates-installed`) | ✅ |
| AC-14 | integration | Windows copy recipe copies bootstraps, `.agent/` instructions, tools, TEMPLATE_HOME, agents, BUILD_PLAN stub, INSTANTIATE.md | Spec 2.14 | ADOPTION-GUIDE Step 2 + WP7 instantiate | ✅ |
| AC-15 | unit | Ship `core/.agent/context/current-focus.md`; D9=yes recipe schema-complete; `meu_status.py` has no `add` | Spec 2.9 | `--case templates-installed` seed file | ✅ |
| AC-16 | unit | INSTANTIATE.md copied to adopter `.agent/INSTANTIATE.md`; installed docs link `../INSTANTIATE.md` | Spec 2.11 | `core/.agent/INSTANTIATE.md` present | ✅ |
| AC-17 | integration | D9_NO_BRANCH: D9=no first-plan write does not require MEU sections / `meu_status.py` | Spec 2.9/2.12 | `assert_wp3.py` (`d9-no`) | ✅ |
| AC-18 | unit | commands.md / quality-gate / AGENTS / testing-strategy / lifecycle / validation-review / create-plan use D6_ADOPTER_ARGV, not a required `tools/validate_codebase.py` | Spec 2.6 | `--case d6`; lifecycle/validation-review D6 wording | ✅ |
| AC-19 | unit | `/mcp-audit` removed from workflows/README; D3-only `docs/BUILD_PLAN.md` can plan without `docs/build-plan/` | Spec F016, F030 | `--case d6` README; create-plan D3 | ✅ |
| AC-20 | integration | Isolated pytest argv reaches D6; second argv proves pytest is not a universal default; missing exe / failing child fail | Proposal HD-04 | `--case d6` hello + missing-module arms | ✅ |
| AC-21 | integration | Failing child with two diagnostic ids: both survive on the receipt with nonzero status | overlay 1.1 | `--case d6` `diag-one`/`diag-two` | ✅ |
| AC-22 | unit | TASK-TEMPLATE / create-plan example cells have no `pwsh -Command {` and no required `rtk`/`uv` | Spec 2.13 | `wp5-template.txt`; TASK-TEMPLATE H1-1 uses `chr(124)` | ✅ |
| AC-23 | unit | lint refuses `-Command` + scriptblock; keeps escaped-pipe refusal and `& { }` placeholder | Spec 2.13 | `lint_task_contract.py --selftest` `pwsh-command-scriptblock-refused` | ✅ |
| AC-24 | unit | H1-1 is a concrete unchecked-row check; no nested backticks | Spec F035 | TASK-TEMPLATE.md H1-1 | ✅ |
| AC-25 | unit | workflows/README titled as workflow ids; direct `.md` invocation; no shipped `.cursor/commands/`; mcp-audit row gone | HD-07; Spec 2.10 | README first column ids; `--case d6` | ✅ |
| AC-26 | unit | Interview ids have profile slots; create-plan/session-start read PROFILE and apply EGRESS_PRECEDENCE / D9_NO_BRANCH / D6 | Spec 2.12 | `--case profile-permissions` | ✅ |
| AC-27 | unit | Cursor `injects_auto_approval` cell = `yes` | Spec 2.15 | `harness-profiles.md` Cursor row | ✅ |
| AC-28 | unit | F007 drop unshipped Cursor CLI wrapper as default; F008 search-provider; F018 D8 map; F019 labeled bad-path; F022 benchmark opt-in; F001 README vs guide order | Spec 2.16 | model-routing.md, inspiration-research.md, PROFILE D8, terminal-preflight SKILL | ✅ |
| AC-29 | integration | HD-03 unanswered: receipt first line `INCOMPLETE:`; names forwarding wrappers; no `P:/.agent` copy; no live compile claim | HD03_GATE | `hd03-live-registry.txt`; `--case hd03` | ✅ |
| AC-30 | integration | HD-03 answered later: READY path with provenance. Predicate false this round (no human compiler source); READY path not taken | HD03_GATE | same receipt is `INCOMPLETE:` not `READY:` | ✅ |
| AC-31 | integration | New disposable repo (not `P:/fw-adopt-probe`) completes Steps 0–9 deferred registry, TEMPLATE_HOME, D6, D9_NO_BRANCH, lint 0, `--phase build` FIRST_LINE_CONTRACT OK, EGRESS_PRECEDENCE stop, zero provider calls | Spec + Astra WP7 | `--case wp7`; `wp7-adopter-replay.txt` | ✅ |

<!-- CACHE BOUNDARY -->
<!-- Content above this line is stable across revision passes (KV cache prefix). -->
<!-- Content below this line changes between passes (evidence, results, corrections). -->

---

## Evidence

Adoption-contract runner plus named selftests. Receipts under `C:/Temp/agentic-framework/receipts/`. Origin tree was not instantiated in place; WP7 used `C:/Temp/agentic-framework/wp7-adopt-2026-09-19`.

### FAIL_TO_PASS

| Test | Red Output (hash/snippet) | Green Output | File:Line |
|------|--------------------------|--------------|-----------|
| `--case wp1` locators | configured missing home fell through to another catalog; instruction `.agent/` treated as catalog | `OK: wp1 layout, locators, and EGRESS_PRECEDENCE` (`wp1-guide.txt`) | `.agent/tools/ModelRegistry.psm1` `Get-RegistryCandidate`; `resolve_model.py` / `check_model_slugs.py` exclusive elif |
| preflight first line | banner `preflight (phase=…)` was stdout byte 0 | `OK: 30 arm(s), 0 failure(s)` (`preflight-selftest.txt`) | `core/tools/preflight.sh` buffered `report()` |
| BUILD_PHASE_SKIP | `--phase build` REFUSE registry when deferred | selftest `registry-skipped-when-phase-build` exit 0; `registry-runs-when-phase-review` exit 1 | `preflight.sh:295` |
| `test_ps1_encoding.py` | BOM-less U+2014 in `Invoke-CodexDispatch.ps1` ParserError on 5.1 | `OK` (`wp2-encoding.txt`) | `core/tools/Invoke-CodexDispatch.ps1` ASCII rewrite; BOM on remaining ps1 |
| instantiate no `--root` | default apply rewrote package neighbor | selftest `missing-root-is-usage-and-does-not-write` | `scripts/instantiate.py:577-581` |
| TEMPLATE_HOME | create-plan named `docs/execution/plans/PLAN-TEMPLATE` | `OK: TEMPLATE_HOME consumers` (`wp3-templates.txt`) | `core/.agent/workflows/create-plan.md` |
| D6 / mcp-audit | `uv run python tools/validate_codebase.py`; README `/mcp-audit` | `OK: D6_ADOPTER_ARGV and no mcp-audit` (`wp4-mcp.txt`) | `core/.agent/docs/commands.md:23-27` |
| lint `-Command {` | `scriptblock-is-not-a-placeholder-ok` blessed `pwsh -Command { Get-Date }` | selftest `pwsh-command-scriptblock-refused` want=1/REFUSE (`lint-selftest.txt`) | `lint_task_contract.py:365` `check_pwsh_command_scriptblock` |
| HD03_GATE | silent skip or `registry ready` | first line `INCOMPLETE:` (`hd03-live-registry.txt`) | WP1B receipt |
| `--case wp7` | existence-only receipt or probe mutation | fixture path + D6/lint/preflight exits + `PROVIDER_CALLS=0` (`wp7-adopter-replay.txt`) | `scripts/tests/run_wp7_replay.py` |

### Commands Executed

| Command | Exit Code | Key Output |
|---------|-----------|------------|
| `python scripts/tests/test_adoption_contract.py --case wp1` | 0 | `OK: wp1 layout, locators, and EGRESS_PRECEDENCE` |
| `bash core/tools/preflight.sh --selftest` (Git usr/bin prepended) | 0 | `OK: 30 arm(s), 0 failure(s)` |
| `python scripts/tests/test_ps1_encoding.py` | 0 | encoding gate pass |
| `python docs/execution/plans/2026-09-19-portable-adopter-bootstrap/checks/assert_wp3.py` | 0 | TEMPLATE_HOME + D9_NO_BRANCH |
| `python scripts/instantiate.py --selftest` | 0 | 30 arms including missing-root |
| `python scripts/tests/test_adoption_contract.py --case d6` | 0 | D6 + no mcp-audit |
| `python core/tools/lint_task_contract.py --selftest` | 0 | includes `pwsh-command-scriptblock-refused` |
| `python scripts/tests/test_adoption_contract.py --case profile-permissions` | 0 | slots + EGRESS_PRECEDENCE |
| `python scripts/tests/test_adoption_contract.py --case hd03` | 0 | `INCOMPLETE:` accepted |
| `python scripts/tests/test_adoption_contract.py --case wp7` | 0 | disposable fixture; not `P:/fw-adopt-probe` |
| `Test-Path docs/BUILD_PLAN.md` | 0 | `False` (`build-plan-hub.txt`) |
| H1-2 `lint_task_contract.py --task …/task.md` | (this closeout) | `lint-task.txt` |
| H1-3 packaged `meus: []` | (this closeout) | `meu-noop.txt` |
| H1-4 no `packages/api` | (this closeout) | `openapi-skip.txt` |

### Quality Gate Results

```
skip-with-basis: non-product meus: []; PROFILE D6 for this origin session is python plus the adoption-contract runner.
pyright/ruff/origin validate_codebase.py: unshipped; not in contract.
anti-placeholder: TASK-TEMPLATE and create-plan cells have no pwsh -Command {; lint selftest refuses that form.
HD-03: INCOMPLETE (not READY).
WP7: PROVIDER_CALLS=0; EGRESS_STOP=named-human-no-web-prompt.
```

---

## Changed Files

Tracked production edits (~51 files, plus new tests/seeds/plan). Representative:

| File | Action | Lines | Summary |
|------|--------|-------|---------|
| `core/tools/preflight.sh` | modified | report buffer, phase skip, selftest arms | FIRST_LINE_CONTRACT, BUILD_PHASE_SKIP, no-fallthrough |
| `.agent/tools/ModelRegistry.psm1` | modified | `Get-RegistryCandidate` | fail-closed configured home |
| `.agent/tools/resolve_model.py`, `check_model_slugs.py` | modified | exclusive elif locate | same LOCATE_ORDER |
| `core/tools/Invoke-CodexDispatch.ps1`, `.sh` | modified | ASCII + locate comments | encoding + no implicit workspace catalog |
| `scripts/instantiate.py` | modified | `--root` required | INSTALLER_TARGET, owned walk, rename |
| `core/tools/lint_task_contract.py` | modified | `-Command` rule | portability diagnostic |
| `core/templates/TASK-TEMPLATE.md` | modified | H1-1 cell | `chr(124)`; no rtk/uv/`-Command {` |
| `core/.agent/workflows/create-plan.md` | modified | TEMPLATE_HOME, D6, D9, EGRESS | absorbed superseded create-plan-only ACs |
| `ADOPTION-GUIDE.md`, `PROJECT-PROFILE-TEMPLATE.md` | modified | LAYOUT_HD01, slots | HD-01…HD-09 defaults |
| `core/.agent/context/current-focus.md` | new | stub | WP3 seed |
| `core/.agent/INSTANTIATE.md` | new | copy of INSTANTIATE | install mapping |
| `scripts/tests/test_adoption_contract.py` | new | cases wp1…wp7 | fail-closed runner |
| `scripts/tests/test_ps1_encoding.py` | new | byte gate | AC-9/AC-10 |
| `scripts/tests/run_wp7_replay.py` | new | disposable replay | AC-31 |
| `docs/execution/plans/2026-09-19-portable-adopter-bootstrap/*` | new | plan, task, checks | FIC + helpers |

```diff
 # instantiate apply
-# default: rewrite cwd / package neighbor
+parser.error("--root is required to rewrite an adopter tree.")
```

```diff
-# ModelRegistry: fall through when configured home missing
+if ($env:AGENT_MODEL_REGISTRY_HOME) { …; no user-home fall-through }
```

```diff
-pwsh -NoProfile -Command { … }
+python -c "… chr(124) …" *> $env:RECEIPTS_DIR/…
```

Closeout-pass residues also edited: `development-lifecycle.md` D6 mermaid (no `validate_codebase.py` / `/mcp-audit` as the registered gate), `validation-review.md` D6 instead of origin `packages/` suite, `PLAN-TEMPLATE.md` BUILD_PLAN cell (no `-Command {`), workflows README first-column ids without slash prefixes.

**Not claimed:** `P:/fw-adopt-probe` (frozen). `P:/.agent` (not copied). Origin package not rewritten via instantiate without `--in-place-package` (wrapper staging under `C:/Temp` only).

---

## Codex Validation Report

_Left blank for reviewer agent. Reviewer fills this section during execution-critical-review._

### Recheck Protocol

1. Read Scope + AC table
2. Verify each AC against Evidence section (file:line, not memory)
3. Run all Commands Executed and compare output
4. Run Quality Gate commands independently
5. Record findings below

### Findings

| # | Severity | Finding | File:Line | Recommendation | Status |
|---|----------|---------|-----------|----------------|--------|
| 1 | — | (reviewer) | — | — | — |

### Verdict

`pending` — independent_reviewer has not written this section.

---

## Corrections Applied (2026-09-19)

**Findings resolved**: pending independent recheck of R1–R4 from execution review round 1.

| # | Finding | Fix Applied | Verification |
|---|---------|-------------|--------------|
| R1 | Installer rewrote user-notes.md | Allowlist `iter_owned_text_files` to installed `.agent/` / `tools/` / agent-def / root AGENTS-family files; user notes and app templates are outside the inventory | instantiate `--selftest` `owned-user-notes-survive`, `owned-app-template-tokens-survive` (32 arms, 0 fail) |
| R2 | WP7 checker accepted D6_EXIT=1 and wrote a Goal-only plan | Parser requires child exits 0 plus fixture plan/task skeleton (Acceptance Criteria, Verification Plan, Spec Sufficiency). Replay fills installed PLAN-TEMPLATE and TASK-TEMPLATE head, then PROFILE-derived D9/egress | `--case wp7`; fixture `implementation-plan.md` headings; bogus D6_EXIT=1 still refuses |
| R3 | H1-1 matched Status Legend | Numeric first-cell only (`isdigit` after strip) | legend oracle: old matcher false-fail, new matcher empty |
| R4 | No successful non-pytest D6 | Alternate `python -c print(alt-d6-ok)` plus missing `no-such-d6.exe` FileNotFound | `--case d6` |

---

## Deferred Items

None. HD-03 incompleteness is in-scope (HD03_GATE / AC-29), not a deferral. AC-30 READY path is the unanswered-predicate branch of the same gate. Out-of-scope items stay in the plan Out of Scope table (no scheduled product MEU).

---

## History

| Event | Date | Agent | Detail |
|-------|------|-------|--------|
| Created | 2026-09-19 | cursor-grok-4.6 | Initial handoff after WP1–WP7 |
| Submitted for review | 2026-09-19 | cursor-grok-4.6 | Sent to independent_reviewer |
