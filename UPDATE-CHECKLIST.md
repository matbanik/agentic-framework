# Update Checklist — Refreshing This Package From the Source Repo

Use this when the originating project's governance or subagent flows change and you
need `_transfer-out/agentic-framework/` to match again. The package is **not** critical
runtime data — prefer **delete outdated copies and re-copy**, then re-sanitize.

Last refreshed: **2026-09-07** (package-root `.agent/` registry-home template, class-based
routing, Codex dispatch resolves from the live registry, sanitize `--verify` slug gate).

---

## When to refresh

Refresh if **any** of these land in the source repo:

| Trigger | Why it matters |
|---|---|
| `fresh_worker` / harness-profile row changes | Adopters branch on capability flags |
| `.agent/skills/subagent-delegation/**` changes | Delegation gate is the portable contract |
| `.cursor/agents/*` or `.claude/agents/*` changes | Builder/verifier guardrails. Shipped files are AUTOGEN templates |
| `TASK-TEMPLATE.md` / reflection template gain columns or `delegate_to` rules | Plan/task shape drift |
| `create-plan.md` / `execution-session.md` delegation steps change | Orchestrator behavior |
| New portable skill/workflow added under `.agent/` that is **not** product-specific | Package completeness |
| `GUARDRAILS.md` / `AGENTS.md` P0–P1 / SIGN changes | Safety surface |
| `tools/issue_triage/**` or `tools/meu_status/**` CLI/schema changes | Adopter loop executability |
| Issue taxonomy / category enums / triage workflow steps | Classification contract |
| `session-grouping.md` / `issue-triage.md` / `issue-lifecycle-guide.md` | MEU planning handoffs |
| Live registry `schema/`, `tools/ModelRegistry.psm1`, or the class contracts change | The package-root `.agent/` template must match the schema and module the live tools enforce |
| The bump procedure in the live registry's `README.md` changes | `.agent/INSTANTIATE.md` §6 is its portable twin |

Skip a full refresh for product-only work (UI, API, populated MEU registries, Electron E2E).
**Never** copy live `known-issues.yaml` / `meu-status.yaml` content — refresh **empty seeds** only.
**Never** recopy this package to bump a model. A bump is a live-registry edit plus
`resolve sync` for AUTOGEN-marked agent-definition files. See `.agent/INSTANTIATE.md`.

---

## Pre-flight

- [ ] Confirm source paths below still exist (names drift — fix the list, don't invent).
- [ ] Receipts go to `{{RECEIPTS_DIR}}/` (or your active `RECEIPTS_DIR`) with all-stream redirect.
- [ ] You will **overwrite** `core/` content; package-root docs (`README.md`, `ADOPTION-*`,
      `UPDATE-CHECKLIST.md`, `scripts/`) are edited by hand — do not blindly wipe them.

---

## File sync map (source → package)

### Always re-copy (governance core)

| Source | Destination |
|---|---|
| `AGENTS.md` | `core/AGENTS.md` |
| `GUARDRAILS.md` | `core/GUARDRAILS.md` |
| `CLAUDE.md` | `core/CLAUDE.md` |
| `.agent/docs/harness-profiles.md` | `core/.agent/docs/` |
| `.agent/docs/model-routing.md` | `core/.agent/docs/` |
| `.agent/docs/model-delegation.md` | `core/.agent/docs/` |
| `.agent/docs/context-compression.md` | `core/.agent/docs/` |
| `.agent/docs/development-lifecycle.md` | `core/.agent/docs/` |
| `.agent/docs/agentic-methodology.md` | `core/.agent/docs/` |
| `.agent/docs/artifact-naming.md` | `core/.agent/docs/` |
| `.agent/docs/code-quality.md` | `core/.agent/docs/` |
| `.agent/docs/testing-strategy.md` | `core/.agent/docs/` |
| `.agent/docs/emerging-standards.md` | `core/.agent/docs/` |
| `.agent/docs/commands.md` | `core/.agent/docs/` |
| `.agent/docs/issue-lifecycle-guide.md` | `core/.agent/docs/` |
| `.agent/docs/prompt-templates.md` | `core/.agent/docs/` |
| `.agent/docs/natural-writing-guide.md` | `core/.agent/docs/` |
| `.agent/docs/claude-cli-fallback-lessons.md` | `core/.agent/docs/` |
| `.agent/docs/macos-setup.md` | `core/.agent/docs/` | package-authored; hardware smoke pending |
| `.agent/docs/context-tool-decision-gate.md` | `core/.agent/docs/` | if present in source |
| `.agent/docs/triage-meu-loop.md` | `core/.agent/docs/` | issue→MEU learning loop diagram |
| `.agent/docs/diagrams/development-lifecycle-overview.svg` | `core/.agent/docs/diagrams/` | (if present) |

### Workflows / roles / schemas (re-copy the portable set)

| Source tree | Destination | Notes |
|---|---|---|
| `.agent/workflows/{README,create-plan,execution-session,plan-critical-review,execution-critical-review,validation-review,plan-corrections,execution-corrections,tdd-implementation,meu-handoff,orchestrated-delivery,delegated-plan-creation,next-project,cli-dispatch,pre-build-research,inspiration-research,session-grouping,session-meta-review,skill-optimize,issue-triage}.md` | `core/.agent/workflows/` | **Do not** copy product workflows (`e2e-testing`, `gui-integration-testing`, `graphify`, `mcp-audit`, `security-audit`) |
| `.agent/roles/*.md` | `core/.agent/roles/` | all six roles |
| `.agent/schemas/reflection.v1.yaml` | `core/.agent/schemas/` | |
| `.agent/schemas/review-verdict.schema.json` | `core/.agent/schemas/` | if present in source |
| `.agent/schemas/registry.yaml` | `core/.agent/schemas/` | if present |

### Skills (portable only)

| Source | Destination |
|---|---|
| `.agent/skills/README.md` | `core/.agent/skills/README.md` |
| `.agent/skills/cli-dispatch/**` | `core/.agent/skills/cli-dispatch/` |
| `.agent/skills/completion-preflight/SKILL.md` | same under `core/` |
| `.agent/skills/pre-handoff-review/SKILL.md` | same |
| `.agent/skills/terminal-preflight/SKILL.md` | same |
| `.agent/skills/quality-gate/SKILL.md` | same |
| `.agent/skills/git-workflow/**` | same |
| `.agent/skills/timestamp/**` | same |
| `.agent/skills/skill-optimizer/**` | same |
| `.agent/skills/session-meta-review/SKILL.md` | same |
| `.agent/skills/subagent-delegation/SKILL.md` | **required for subagent flows** |
| `.agent/skills/issue-triage/SKILL.md` | **required for issue→MEU loop** |
| `.agent/skills/meu-status/SKILL.md` | **required for issue→MEU loop** |
| `.agent/skills/deep-research-prompting/SKILL.md` | **required for `/inspiration-research`** (Pomera MCP — manual adopter edit if substituting) |

**After copy:** replace `subagent-delegation/verification-log.md` with the **portable stub**
(not the source repo's live probe receipts). Keep the stub's `{{RECEIPTS_DIR}}` tokens.

### Issue / MEU tools + seeds (required for learning-from-mistakes loop)

| Source | Destination |
|---|---|
| `tools/__init__.py` | `core/tools/__init__.py` |
| `tools/Invoke-CodexDispatch.ps1` | `core/tools/` | if present in source |
| `tools/Invoke-CodexDispatch.sh` | `core/tools/` | package-authored POSIX companion (no live-source twin) |
| `tools/issue_triage.py` + `tools/issue_triage/**` | `core/tools/` |
| `tools/meu_status.py` + `tools/meu_status/**` | `core/tools/` |
| _(package seeds, not live YAML)_ | `core/.agent/context/known-issues.yaml` (empty) |
| _(package seeds)_ | `core/.agent/context/meu-status.yaml` (starter phase only) |
| _(package)_ | `core/.agent/context/{known-issues.md,known-issues-archive.md,meu-registry.md,grouping/README.md,triage-output.EXAMPLE.yaml}` |
| _(package)_ | `core/.agent/docs/triage-meu-loop.md` |
| _(package)_ | `core/templates/BUILD_PLAN-STUB.md` |

Re-validate seeds after copy: `load()` both SSOTs from `core/` must succeed.

> **Full tools set:** the packaged `core/tools/` tree ships **19 files** (both CLIs + packages +
> `Invoke-CodexDispatch.ps1` + `__init__.py`). After copy, confirm count and no `__pycache__`.

### Subagent agent definitions (required for subagent flows)

| Source | Destination (temp name) | After sanitize |
|---|---|---|
| `.cursor/agents/<source-slug>-builder.md` | `core/.cursor/agents/<source-slug>-builder.md` | rename → `{{PROJECT_NAME}}-builder.md` |
| `.cursor/agents/<source-slug>-verifier.md` | `core/.cursor/agents/<source-slug>-verifier.md` | rename → `{{PROJECT_NAME}}-verifier.md` |
| `.claude/agents/<source-slug>-builder.md` | `core/.claude/agents/<source-slug>-builder.md` | rename → `{{PROJECT_NAME}}-builder.md` |
| `.claude/agents/<source-slug>-verifier.md` | `core/.claude/agents/<source-slug>-verifier.md` | rename → `{{PROJECT_NAME}}-verifier.md` |

Keep / refresh `core/.cursor/agents/README.md` and `core/.claude/agents/README.md`.

The shipped `.cursor/agents` / `.claude/agents` files are **AUTOGEN templates**
generated from a registry, not hand-maintained pins. Refresh when guardrail prose
changes. Do not recopy the package to move a `model:` value.

### Templates

| Source | Destination |
|---|---|
| `.agent/context/handoffs/TEMPLATE.md` | `core/templates/HANDOFF-TEMPLATE.md` |
| `.agent/context/handoffs/REVIEW-TEMPLATE.md` | `core/templates/REVIEW-TEMPLATE.md` |
| `docs/execution/plans/PLAN-TEMPLATE.md` | `core/templates/PLAN-TEMPLATE.md` |
| `docs/execution/plans/TASK-TEMPLATE.md` | `core/templates/TASK-TEMPLATE.md` |
| `docs/execution/reflections/TEMPLATE.md` | `core/templates/REFLECTION-TEMPLATE.md` |

### Package-root `.agent/` — registry-home template

The only group whose source is the **live registry home** (`P:/.agent`, or wherever
`AGENT_MODEL_REGISTRY` points) rather than the source repo. It is also the only group
that is not a blind re-copy: three of its six files are deliberately divergent, and
copying them would ship this machine's pins to an adopter.

| Source | Destination | Rule |
|---|---|---|
| `<registry home>/schema/model-registry.v1.schema.json` | `.agent/schema/` | **Re-copy.** Byte-identical — the template must validate against the same schema the live tools enforce. |
| `<registry home>/tools/ModelRegistry.psm1` | `.agent/tools/` | **Re-copy.** Byte-identical; the module is slug-free by construction (it reads compiled JSON and embeds nothing). |
| `<registry home>/model-registry.yaml` | `.agent/model-registry.template.yaml` | **Never a copy — hand-merge.** Carry across *new or changed class contracts only*. `catalog`, `bindings`, and `pins` stay empty; `forbid` and `eval_gate` are omitted entirely (they hold catalog ids and machine-local paths). |
| `<registry home>/README.md` §Bumping a binding | `.agent/INSTANTIATE.md` §6 | **Hand-maintained twin.** Same sequence, no snapshot ids, no machine paths. |
| — | `.agent/docs/model-classes.md` | **Hand-maintained.** Class list plus the `resolve` dispatch contract. Names no snapshots. |
| — | `.agent/tools/resolve_model.py`, `.agent/tools/check_model_slugs.py` | **Do not copy the live tools.** These are thin locate-and-forward wrappers on purpose; the live implementations carry catalog examples and day-one binding tables inside docstrings. |

Verify after touching this group — the package must carry **zero** slugs, which is
what makes `agentic-framework` the one repo with an allow-listed count of 0:

```powershell
rtk proxy python <registry home>/tools/check_model_slugs.py --project . --enforce --format json *> {{RECEIPTS_DIR}}/framework-slug-check.txt
```

A nonzero allow-listed count here means a snapshot id leaked into the package. Find it
and remove it; do not add a `raw_slug_allowlist` pattern to hide it.

---

## Sanitize + rename (mandatory)

```powershell
# from _transfer-out/agentic-framework/
rtk proxy python scripts/sanitize.py --verify *> {{RECEIPTS_DIR}}/agentic-framework-sanitize.txt
# capture $LASTEXITCODE before reading the receipt; must be 0

# rename agent files (source-slug filenames → placeholder filenames)
# <source-slug>-{builder,verifier}.md  →  {{PROJECT_NAME}}-{builder,verifier}.md
# under both core/.cursor/agents/ and core/.claude/agents/
```

- [ ] `sanitize.py --verify` reports **0 raw slugs**
- [ ] No agent filename still contains the source slug
- [ ] Spot-check: `harness-profiles.md` has `fresh_worker`; `model-delegation.md` links `subagent-delegation/SKILL.md`; `TASK-TEMPLATE.md` documents `builder_model` / `delegate_to`

---

## Package-root docs (edit by hand — do not overwrite blindly)

- [ ] `core/MANIFEST.md` — new/removed files, §5b AUTOGEN agent templates, package-root `.agent/`
- [ ] `README.md` — tree diagram matches on-disk layout (includes package-root `.agent/`)
- [ ] `ADOPTION-GUIDE.md` — copy paths for `.cursor/agents` / `.claude/agents`; `fresh_worker` steps; Step 4 points at `.agent/INSTANTIATE.md`
- [ ] `ADOPTION-QUESTIONS.md` — A6/A9 (or current lettering) cover assistant-addressable workers; registry instantiation points at `INSTANTIATE.md`
- [ ] `.agent/INSTANTIATE.md` — §6 bump sequence still matches the live registry's `README.md`; §2 copy table lists every template file; no snapshot ids
- [ ] `.agent/model-registry.template.yaml` — new/changed class contracts merged; `catalog`, `bindings`, `pins` still empty; no `forbid` / `eval_gate` values
- [ ] `.agent/docs/model-classes.md` — class list matches the template's classes
- [ ] `DOMAIN-MAPPING.md` — only if delegation vocabulary needs a domain note
- [ ] This file (`UPDATE-CHECKLIST.md`) — bump **Last refreshed** date + note what changed
- [ ] `examples/` — only if you intentionally refresh the worked review example

---

## Accepted divergences (scrub ledger)

After sanitize, some packaged files **intentionally differ** from source (product-specific paths
removed, adopter-facing prose added). Maintain the ledger so refreshers know what is scrub vs bug.

From the **source repo** (not the package):

```powershell
rtk proxy uv run python tools/_fw_hashdiff.py --ledger *> {{RECEIPTS_DIR}}/fw-ledger.txt
# capture $LASTEXITCODE before reading; paste or reconcile the table below
```

**Current ledger (2026-08-05 refresh, post R1 corrections):**

| File | Class | Why the package differs |
|---|---|---|
| `AGENTS.md` | scrub | `plan_to_exec_gate == human` harness list drops the Cursor Agent CLI example; the carve-out rule itself is preserved verbatim. |
| `.agent/docs/harness-profiles.md` | scrub | Cursor Agent CLI profile row removed ΓÇö the wrapper does not ship, so a resolvable row would point adopters at an absent tool. |
| `.agent/docs/model-routing.md` | scrub | Isolated-worker rungs rewritten to `claude -p` only; the 'not an independent-reviewer substitute' rule is kept. |
| `.agent/docs/commands.md` | scrub | Drops the ┬ºCursor Agent CLI smoke and ┬ºSerena server lifecycle sections and rewrites the CLI Dispatch row; the row itself is kept because the skill ships. |
| `.agent/docs/context-tool-decision-gate.md` | scrub | `eligible_tools` and the token-savings prose drop Serena (excluded MCP). |
| `.agent/docs/testing-strategy.md` | authored | The source's `QA-PYRIGHT-SCOPE-GAP` warning is a live product known-issue investigation (names `tools/validate_codebase.py`, a source line number, this repo's `packages/` layout, and a domain type). Replaced by a portable TIP carrying the transferable lesson: make the gate and the pre-commit hook agree on which trees they type-check, and write the scope down. |
| `.agent/workflows/README.md` | scrub | `/cli-dispatch` executor cell drops the Cursor Agent CLI route. |
| `.agent/workflows/create-plan.md` | scrub | Context-tool inventory drops Serena (2 mentions). |
| `.agent/workflows/execution-session.md` | scrub | Context-tool inventory drops Serena (1 mention). |
| `.agent/workflows/execution-critical-review.md` | scrub | ┬ºElectron / GUI E2E evidence routing removed ΓÇö product-specific, and the e2e-testing skill is in MANIFEST ┬ºEXCLUDED. |
| `.agent/workflows/cli-dispatch.md` | scrub | Cursor Agent CLI route removed; the decision-tree branch is re-pointed at 'your harness's headless builder CLI' and the review-stays-on-Codex rule kept. |
| `.agent/skills/README.md` | authored | Package-authored 'Packaged Skills' table lists exactly what ships, replacing the repo's product-specific planned-skills table. |
| `.agent/skills/cli-dispatch/SKILL.md` | scrub | Cursor Agent auth-gate paragraphs and route removed; Codex wrapper docs (timeout/process-tree defaults) taken from live source; package adds ┬ºCross-Platform Dispatch (pwsh / macos-setup link) with no live-source twin. |
| `.agent/skills/cli-dispatch/tests/Test-CliDispatch.ps1` | scrub | Cursor Agent auth/ask tests removed; `[ValidateSet]` narrowed; package adds `wrapper-contract` suite that exercises Invoke-CodexDispatch.ps1 without false-pass length checks on bare `codex exec`. |
| `.agent/skills/terminal-preflight/SKILL.md` | authored | Package-only macOS/Linux note + link to `.agent/docs/macos-setup.md` after the `native_shell: powershell` paragraph ΓÇö no live-source twin (macos-setup is package-authored). |
| `.agent/skills/subagent-delegation/SKILL.md` | scrub | In-harness-Task-vs-Cursor-Agent bridge subsection removed. The `fresh_worker` first-match blockquote and the four never-delegate categories are preserved. |
| `.agent/skills/issue-triage/SKILL.md` | authored | Generic ID prefixes, a `VALID_COMPONENTS` edit pointer, and the full category taxonomy replace {{PROJECT_NAME_TITLE}}-specific prefixes. Net +470 chars of adopter content. |
| `.agent/skills/meu-status/SKILL.md` | authored | {{PROJECT_NAME_TITLE}}-internal 'Round-5 out of scope' note replaced with adopter guidance on the canonical generated view and AUTOGEN markers. |
| `templates/PLAN-TEMPLATE.md` | scrub | `eligible_tools` drops Serena. |
| `templates/TASK-TEMPLATE.md` | scrub | `eligible_tools` drops Serena. |

-- 20 accepted divergence(s), all live --


Re-run `--ledger` after every refresh and update this table when the count or rows change.

---

## Explicitly do **not** copy

- Product workflows/skills listed in `MANIFEST.md` §Deliberately EXCLUDED
- `.agent/context/` **runtime** state (`current-focus`, populated `known-issues.yaml` /
  `meu-status.yaml` / `triage-output.yaml`, handoffs, archives with product history)
- `scripts/verify_subagent_delegation.py` and its pytest suite (source-repo activation tooling)
- Live `verification-log.md` probe receipts (use the portable stub)
- `docs/execution/plans/2026-*-subagent-delegation-*/` plans/reflections (history, not package content)

---

## Post-refresh smoke (adopter-shaped)

- [ ] `uv run python tools/_fw_refcheck.py --all` (from **source repo**) → **0 unresolved** references
- [ ] `python scripts/instantiate.py --config <vars> --dry-run` shows sensible substitutions
- [ ] Grep package for the source slug (case-insensitive) → only hits inside `scripts/placeholders.py`
- [ ] Open `core/.agent/skills/subagent-delegation/SKILL.md` — decision table still fail-closed when `fresh_worker` is unset
- [ ] Confirm never-delegate categories still name: correctness, review verdicts, commit/push, human gates
- [ ] `python tools/issue_triage.py stats` and `python tools/meu_status.py stats` succeed against **empty seeds** in `core/`
- [ ] No `__pycache__` under `core/tools/`

---

## Suggested one-shot sync command pattern

Prefer a small local script (or the PowerShell copy loop used on 2026-07-22) that:

1. Copies the tables above with `Copy-Item -Force`
2. Writes the portable `verification-log.md` stub
3. Runs `sanitize.py --verify`
4. Renames `<source-slug>-*.md` agent files to `{{PROJECT_NAME}}-*.md`
5. Prints a file count + verify OK line into a receipt under the receipts dir

Do **not** commit from this checklist unless a human explicitly asks.
