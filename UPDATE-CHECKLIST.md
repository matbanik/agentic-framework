# Update Checklist — Refreshing This Package From the Source Repo

Use this when the originating project's governance or subagent flows change and you
need `_transfer-out/agentic-framework/` to match again. The package is **not** critical
runtime data — prefer **delete outdated copies and re-copy**, then re-sanitize.

Last refreshed: **2026-09-07** (package-root `.agent/` registry-home template, class-based
routing, Codex dispatch resolves from the live registry, sanitize `--verify` slug gate;
then the merge pass — bounded review ledger, v2 verdict schema, the two closeout gates,
`refcheck.py`'s reference + tool-command gates, dispatch `-Kind` and the execution-review
timeout floor, `tools/preflight.sh`, and `output-evidence-policy.md` incl. the
`.rtk/filters.toml` trust boundary).

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

The only group whose source is the **live registry home** — wherever
`AGENT_MODEL_REGISTRY` / `AGENT_MODEL_REGISTRY_HOME` points on the maintainer's
machine — rather than the source repo. It is also the only group
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

`--verify` runs five gates and reports all of them before exiting, so one round of
fixes clears all five rather than discovering them one per run:

| Gate | Exit | Fails on |
|---|---|---|
| Source slug | 2 | The source project's name survives anywhere outside `placeholders.py` |
| Model slug | 3/4/5 | Registry unreachable / a tier-1 harness slug / AUTOGEN stamp drift |
| Prose model name | 6 | A versioned model name (`Opus N`, `GPT-N`) in instruction text. Allowed only in a wholesale-historical file or on a line that marks itself historical — "currently" does **not** count |
| Reference integrity | 7 | A packaged `.md` names a repo-relative path that is neither shipped nor MANIFEST-EXCLUDED. In an always-loaded file (`AGENTS.md`, `CLAUDE.md`, `GUARDRAILS.md`, `templates/*`) MANIFEST-EXCLUDED is **not** enough — see `scripts/refcheck.py` |
| Tool commands | 8 | A `tools/<name>` path a packaged doc tells the reader to **run** is neither shipped nor classified in `refcheck.py`'s `TOOL_CLASSES` (`registry-home` / `source-repo-only` / `adopter-supplied` / `not-shipped`). A stale classification — nothing references it any more, or the package now ships it — also fails. Separate from gate 7 because the reference gate only sees a path where a reference can *start*: a tool buried inside `rtk proxy uv run python tools/<name>.py --check` was invisible to it, which is how five absent tools shipped while refcheck reported 0 unresolved |

Run the two self-tests first. A clean gate is only evidence if the gate was shown able
to fail — both of these inject known-bad input and require it to be caught, and both
include a negative arm so a gate that fails *everything* is caught too:

```powershell
python scripts/refcheck.py --selftest   # 16 arms (7 must-pass); exit 0
python scripts/sanitize.py --selftest   # 12 arms; exit 0
```

`refcheck.py --selftest` covers both of its gates: reference arms, then tool-command
arms that assert **exit 8** specifically (an unclassified name mid-command, the same name
bare in prose, a classification the package now ships, a classification nothing references
any more) plus one must-pass arm naming a tool that really is shipped.

> **If gate 7 reports `STALE-EXEMPT`, do not just re-point it.** `refcheck.py`'s
> `NOT_A_PROMISE` exemptions are keyed by `file:line`, so inserting lines above one makes
> the gate fail on purpose — the point is that a human re-reads the exemption instead of
> letting it drift onto a different line that happens to name the same path. Re-read the
> line, confirm it is still the same citation, then update the key.

- [ ] `refcheck.py --selftest` and `sanitize.py --selftest` both exit 0
- [ ] `sanitize.py --verify` exits 0 (all five gates)
- [ ] The two closeout gates pass **and** report their must-OK counts:
      `python core/tools/validate_closeout_artifacts.py --selftest` (59 arms, 19 must-OK)
      and `python core/tools/lint_task_contract.py --selftest` (49 arms, 14 must-OK)
- [ ] `python core/tools/review_ledger.py selftest` (55 arms, 25 must-OK). One of those
      arms asserts `evaluate` still prints `mode=`; the dispatch wrappers read the dispatch
      kind from it, so a tidier print statement there breaks *them*, not the ledger
- [ ] `pwsh -NoProfile -File core/.agent/skills/cli-dispatch/tests/Test-CliDispatch.ps1 -Test wrapper-contract`
      → 31 arms, 0 fail, 0 skip. Needs `AGENT_MODEL_REGISTRY_HOME` (or `AGENT_MODEL_REGISTRY`)
      set, or it throws `registry_not_found` before any arm runs. A `SKIP` on the
      dispatch-kind arms is not a pass — it means `python` or `review_ledger.py` was
      missing from the temp tree and the timeout floor went unchecked
- [ ] The `-OutputSchema` arm reports `shipped=<n>` with **n > 0**, not just
      `dispatched=0`. It strips the composition/conditional keywords the structured-output
      endpoint rejects, and it runs over the real `review-verdict.schema.v2.json` on
      purpose: the shallow root-only strip it replaced passed every fixture and then
      returned `400 invalid_json_schema` on the first live dispatch, because v2 nested an
      `allOf` under `properties.findings.items`. If a future schema drops conditionals,
      `shipped=0` will fail this arm — retire it deliberately rather than letting it pass
      with nothing to strip
- [ ] `python core/tools/adapt_output_schema.py selftest` → 24 arms, 0 failures
      (**2 must-OK + 4 must-survive**). This is the *one* implementation of the schema
      adaptation; both dispatch wrappers call it and neither carries a copy. Read the
      must-survive count, not just OK: a stripper that deleted every key would satisfy
      every "keyword is gone" arm. The `Schema adaptation has one implementation` arm in
      `Test-CliDispatch.ps1` is what stops a local copy from growing back — if you are
      tempted to inline "just this one case" into a wrapper, that arm is the answer
- [ ] `python core/tools/validate_json_schema.py --selftest` → 9 arms, 0 failures
      (1 must-OK). The wrapper's post-validation calls it; an **absent** validator used to
      leave an empty `if` with no `else`, so "not checked" and "checked and passed" were
      the same outcome. It now exits 3
- [ ] `bash core/.agent/skills/git-workflow/scripts/agent-commit.sh --selftest` → 9 arms,
      0 failures (2 must-pass). Every arm asserts the **commit count**, not just the exit
      code, because a script that refused everything satisfies each negative arm and a
      script that committed anyway can still exit 1
- [ ] `python scripts/sanitize.py --selftest` → 12 arms, 0 failures. Six of those arms are
      the prose-name gate's discrimination proof: three spellings that shipped past it
      (`Fable 5` — a family absent from the pattern; `Opus-4.8` — a hyphen where it only
      allowed a space; a **bare** tier name used as a role, as in "Opus Agent") and three
      that must **not** trip it (the lowercase homographs — every tier name is also an
      ordinary English noun — a bare portal name an author sends a human to, and a
      capability class). Bare tiers are matched case-sensitively for exactly that reason,
      and the homograph fixture is **derived from the tier tuple**, so adding a tier
      extends that arm automatically and no literal lowercase slug sits in the source
- [ ] `bash core/tools/preflight.sh --selftest` → 27 arms, 0 failures, **8 must-pass**. Each
      arm re-invokes the script in a subprocess with a mutated environment, so a `bash` found
      only through the default PATH would break the PATH-stripping arms; that is why the
      harness resolves the interpreter absolutely. Read the must-pass number, not just the
      word OK — eight checks all exit 1, so a script that refused everything would satisfy
      every negative arm
- [ ] `bash core/tools/preflight.sh` from the package root exits **1** on `receipts`, and
      that is correct: the packaged default is the literal `{{RECEIPTS_DIR}}` token, so an
      uninstantiated tree must refuse. Re-run with `RECEIPTS_DIR=<abs path outside the repo>`
      to see the exit-0 path. If it ever exits 0 with `RECEIPTS_DIR` unset, the placeholder
      guard has been broken and adopters will get a literal `{{...}}` directory
- [ ] `python scripts/instantiate.py --selftest` → 22 arms, 0 failures (12 must-pass +
      10 must-refuse). This gate exists because `--verify` structurally cannot catch its
      failure class: `--verify` asks whether any `{{TOKEN}}` *remains*, and a token
      replaced with a value that is illegal **where it lands** leaves none. A hyphenated
      slug used to yield `$env:MY-PROJECT_AUTHOR_VENDOR` and an unparseable dispatch
      wrapper, with a clean `--verify` beside it. If you add a placeholder that is
      substituted into an identifier rather than into prose, add an arm here
- [ ] Dogfood the wrapper at least once per refresh, because no gate above executes the
      *instantiated* PowerShell. Copy `core/tools` + `core/.agent` to a temp root, run
      `instantiate.py --root <tmp>` with a **hyphenated** project name, then
      `[System.Management.Automation.Language.Parser]::ParseFile()` the result. Zero parse
      errors, or the package ships a wrapper adopters cannot run
- [ ] **Install acceptance — run every installed tool's own selftest from the temp root**,
      not just from this repo. Same temp tree as the step above; for each shipped tool,
      invoke its selftest with the working directory *inside* the installed tree:

      ```bash
      cd <tmp> && for t in tools/adapt_output_schema.py tools/review_ledger.py \
          tools/validate_json_schema.py; do python "$t" selftest; done
      cd <tmp> && python tools/lint_task_contract.py --selftest \
          && python tools/validate_closeout_artifacts.py --selftest \
          && bash tools/preflight.sh --selftest
      ```

      Every gate above this line runs from the **source** repo, where `scripts/` exists,
      the tree is not instantiated, and paths resolve relative to a layout adopters do not
      have. That is the specific blind spot three shipped defects came through: a helper
      resolved against the working directory instead of its own file, a skip-list entry
      that was right for `scripts/` at the source root and wrong for an installed subtree,
      and a tool absent from the copy set entirely. Each one passed every source-repo gate
      and failed on first use after install. A tool whose selftest cannot even *start* from
      the installed tree is a shipped-broken tool, and only this step can see it.

      Do **not** add `Test-CliDispatch.ps1 -Test wrapper-contract` to this loop. It is a
      *package* gate, and several of its arms assert that `{{...}}` tokens are still
      present and that a placeholder receipts dir is refused — both correctly false once
      the tree is instantiated. Expect 4 failures and 1 skip there and read them as the
      arms being inapplicable, not as a defect. Run that suite from the source repo.
- [ ] `python core/tools/lint_task_contract.py --task core/templates/TASK-TEMPLATE.md --template-mode`
      → OK, and the exempt rows named in that line are still only the placeholder-command
      and `view_file` rows (a new exemption means a row stopped being checked)
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
| `.agent/docs/model-routing.md` | scrub | Isolated-worker rungs rewritten to `claude -p` only; the 'not an independent-reviewer substitute' rule is kept. **Superseded 2026-09-07:** the same-vendor review rung is now removed outright, not relabelled — see §Independent-reviewer chain. Do not restore it from this row. |
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
| `.agent/skills/cli-dispatch/tests/Test-CliDispatch.ps1` | scrub | Cursor Agent auth/ask tests removed; `[ValidateSet]` narrowed; package adds `wrapper-contract` suite that exercises Invoke-CodexDispatch.ps1 without false-pass length checks on bare `codex exec`, plus the review-loop and dispatch-kind arms (which open real ledger loops in a temp `RECEIPTS_DIR`). |
| `tools/Invoke-CodexDispatch.ps1` / `.sh` | package-authored | `-Kind` / `--Kind` + the execution-review timeout floor are package additions with no live-source twin: the kind is read from the ledger's `mode=`, not from the flag, so the two wrappers and `review_ledger.py` move as one unit. Porting either wrapper alone will exit 3 (`ledger_mode_unavailable`) or silently drop the floor. |
| `tools/preflight.sh` | package-authored | No live-source twin. The source repo carried these facts as always-loaded prose caveats; the package turns them into eight checks with a `--selftest`. Ship it with the ┬ºEnvironment Pre-Flight section of `terminal-preflight/SKILL.md` and step 9 of `macos-setup.md` ┬ºAdopter smoke checklist ΓÇö the file alone is a script nobody is told to run. |
| `.agent/skills/terminal-preflight/SKILL.md` | authored | Package-only macOS/Linux note + link to `.agent/docs/macos-setup.md` after the `native_shell: powershell` paragraph ΓÇö no live-source twin (macos-setup is package-authored). Package also adds ┬ºEnvironment Pre-Flight (`tools/preflight.sh`, once per session ΓÇö explicitly *not* per command, which is what the rest of the skill governs). |
| `.agent/skills/subagent-delegation/SKILL.md` | scrub | In-harness-Task-vs-Cursor-Agent bridge subsection removed. The `fresh_worker` first-match blockquote and the four never-delegate categories are preserved. |
| `.agent/skills/issue-triage/SKILL.md` | authored | Generic ID prefixes, a `VALID_COMPONENTS` edit pointer, and the full category taxonomy replace {{PROJECT_NAME_TITLE}}-specific prefixes. Net +470 chars of adopter content. |
| `.agent/skills/meu-status/SKILL.md` | authored | {{PROJECT_NAME_TITLE}}-internal 'Round-5 out of scope' note replaced with adopter guidance on the canonical generated view and AUTOGEN markers. |
| `templates/PLAN-TEMPLATE.md` | scrub | `eligible_tools` drops Serena. |
| `templates/TASK-TEMPLATE.md` | scrub | `eligible_tools` drops Serena. |

-- 21 accepted divergence(s), all live --


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
- [ ] **No baked registry drive-root.** `python scripts/refcheck.py --token 'P:/.agent' --token 'P:\.agent'`
      → every hit is a **comment or a documented example**, never a line in a resolver's
      candidate list. (Do not scan for `P:/` alone: it matches `http://`.) The S2 order is
      `AGENT_MODEL_REGISTRY` → `AGENT_MODEL_REGISTRY_HOME` → `%USERPROFILE%/.agent`
      (`.agent/INSTANTIATE.md`); a literal like `P:/.agent` in a wrapper or test is one
      machine's layout — dead on macOS/Linux, and on another Windows box with that drive
      letter it silently reads someone else's registry. The slug gate does not catch this:
      a drive letter is not the source project's name.

---

## Suggested one-shot sync command pattern

Prefer a small local script (or the PowerShell copy loop used on 2026-07-22) that:

1. Copies the tables above with `Copy-Item -Force`
2. Writes the portable `verification-log.md` stub
3. Runs `sanitize.py --verify`
4. Renames `<source-slug>-*.md` agent files to `{{PROJECT_NAME}}-*.md`
5. Prints a file count + verify OK line into a receipt under the receipts dir

Do **not** commit from this checklist unless a human explicitly asks.
