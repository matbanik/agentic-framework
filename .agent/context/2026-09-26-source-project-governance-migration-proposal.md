# Source Project governance changes: research and migration proposal

Date: 2026-09-26. Status: **proposal only; no framework implementation or merge performed**.

The recommended approach is a **selective contract merge**: port the smaller instruction structure, durable evidence rules, and staged validation contract into the framework's existing adoption system. Preserve framework-specific review governance and make runtime mechanisms optional, explicitly configured capabilities. A wholesale source refresh would overwrite improvements already present here.

## 1. Evidence boundary and repository state

Inspected Git history, current files, cross-repository diffs, and relevant official documentation. “Recent” primarily covers September 22–25, with the framework's September 18–23 changes checked for overlap. No model review was dispatched and no product tests were run for this research.

| Repository | Observed HEAD | State affecting this proposal |
|---|---|---|
| Source Project | `56eb71938c4a7298e4829031e8b3f57ea779fff8` | Latest committed instruction rewrite is present. Working tree also contains unfinished testing/tooling changes; these are identified separately below. |
| Framework | `59a42fb37a4f66ab0ecef3613a91bfb640c5c571` | Existing modified `core/AGENTS.md` contains a planted model pin; an untracked review template exists under the working context. Both were preserved. |

Useful existing framework research: [September 18 gap analysis](2026-09-18-source-project-evidence-framework-gaps.md) and [September 21 gate repair follow-up](2026-09-21-gate-repair-followup.md). These are historical leads; current findings below were checked against files or commands. For example, Source Project's current-focus note still says “Nothing committed,” but Git history establishes that the instruction rewrite was committed.

### Committed changes to port selectively

| Source commit | Date | Change | Portability decision |
|---|---|---|---|
| `13ba19b4` | Sep 22 | Scoped MEU gate, changed-file inputs, integration skip policy, fail-fast stages, opt-in advisory coverage | Port the contract through the adopter's validation configuration; do not copy the product gate command. |
| `a75fac86` | Sep 22 | Static → targeted → full validation ladder; controlled reuse; final handoff sequencing | Port the ladder and final fresh-run rule. Reuse requires a proven input-identity mechanism. |
| `22557e4c` | Sep 25 | Quiet-tree probe, snapshots, gate lease, read-set and tree-delta forms | Advanced optional adapter; not a universal prerequisite for every project. |
| `b01ddd0d` | Sep 25 | Shared predicate for accepted blocked-task evidence | Adapt into the framework's existing task/closeout validators. |
| `14ff57aa` | Sep 25 | Durable artifacts paste the command, exit code, and decisive output | Highest-value portable evidence change. Update all producers and consumers together. |
| `a6add434` | Sep 25 | Scratch-citation scanner and per-file baseline | Port after making roots and scan scope configurable; start new projects with an empty baseline. |
| `2586c44d` | Sep 25 | Four-stop taxonomy, armed stop gate, rule deletion ledger | Port semantics; ship/test hook adapters before claiming enforcement. |
| `a32f050b` | Sep 25 | Shorter AGENTS/GUARDRAILS, simpler CLAUDE bootstrap, registry updates, size tests | Rewrite the framework version against a rule-preservation ledger, keeping its adoption-specific rules. |

## 2. AGENTS.md and related instructions

### Size is a functional problem

Measured from the current working files, including checkout line endings:

| File | Source Project lines / bytes | Framework lines / bytes |
|---|---:|---:|
| AGENTS.md | 143 / 19,850 | 449 / 42,507 |
| GUARDRAILS.md | 48 / 6,319 | 133 / 13,074 |
| CLAUDE.md | 25 / 1,142 | 32 / 1,622 |

The rewrite commit reports Source Project AGENTS shrinking from 399 to 143 lines, 24 to 12 H2 sections, and 148 to 44 audited rules. Its new tests enforce 170 lines/20,000 bytes for AGENTS and 90 lines/8,000 bytes for GUARDRAILS. See [source budget tests](/P:/source-project/tests/tooling/test_instruction_budget.py:1).

The framework AGENTS template alone exceeds Codex's documented default **32 KiB combined project-instruction budget**. That is an adoption risk even before nested instructions are added; this research did not run a live loader probe or inspect a particular adopter's configured limit. Codex loads guidance along the root-to-current-directory path, rather than loading every nested instruction file. [Official instruction discovery documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

**Proposed structure:** retain a compact root contract for authority, human gates, independent review, evidence, TDD, and completion; point to existing documents for commands and specialized procedures. Measure the *instantiated* files and each supported loader's actual chain. Use the source's 20 KB/8 KB budgets as initial targets, with space for long project names and paths. Do not assume a Markdown link loads its target automatically.

Files that must change together: root templates; instruction section registry; workflow references to retired section names/numbers; reflection references to those IDs; any corresponding analyzers actually shipped. Source historical section aliases belong in migration support only if the framework has a consumer for them.

### What the source rewrite adds beyond compression

- Four completion outcomes: done; review cap; reviewer unavailable; human decision. Compaction is continuation; a required hand-back on a harness without compaction belongs to the human-decision outcome.
- Explicit stop-gate arming in task frontmatter. Old in-progress plans do not automatically block unrelated sessions.
- A before/after rule ledger that maps deleted rules to surviving rules or named enforcement mechanisms.
- Hook-backed pipe filtering, commit gating, and stopping in the source Claude configuration.

**Preserve framework differences:** PROFILE-based egress restrictions and human-only review; model capability classes and portable registry discovery; request-only model snapshots; existing review-ledger budgets and human continuation semantics; optional RTK; project-owned validation commands; template-home configuration; non-software adoption.

Do not copy the source's universal “time and token usage are not constraints” statement over the framework's explicit review budget. Nor should source round-cap prose overwrite ledger-controlled limits.

Phrase approval provenance in terms of trusted human authorization versus text embedded in artifacts or tool results. Repository “P0” labels cannot override the host's actual system/developer instruction hierarchy; do not port wording that suggests they can.

**Enforcement caveat:** the source [stop gate](/P:/source-project/tools/stop_gate.py:226) checks open task rows. It does not itself verify an approved review, valid blocked evidence, or all closeout artifacts. Its hook entry point also deliberately fails open on malformed payloads and after repeated blocks. The framework must not label this a complete DONE validator. Keep the full closeout validator authoritative, and describe the hook as an optional interruption guard.

## 3. Temp/tmp folders and CLI outputs

### Actual dispatch behavior

The source wrapper does **not** implement a blanket ban on folders named `temp` or `tmp`. It applies physical-path containment to configured roots. Its output root remains the external scratch directory; September 25 changed how evidence is preserved, not where the wrapper writes its working output.

| Item | Verified source behavior | Framework status |
|---|---|---|
| Output directory | Must resolve under the source receipt root; rejects wildcard output paths | Already parameterized as `{{RECEIPTS_DIR}}`. |
| Working directory | Must resolve inside the source repository | Already parameterized as `{{PROJECT_ROOT}}`. |
| Prompt file | May reside inside the repo **or** receipt root | Already present. An `_tmp-...` filename inside the repo is not rejected just for its name. |
| Output schema | Must reside inside the repo | Already present. |
| Run directory | One dispatch ID; collisions refused unless Force; physical containment checked again before recursive replacement | Already present; retain and regression-test. |
| Prompt staging | Copies prompt into the run directory for stdin delivery; removes staged prompt after processing | Already present. This is not a guarantee that no sensitive prompt data enters CLI transcripts. |
| Outputs | Final Markdown/JSON, status, usage/error summaries, receipt, event stream, stderr | Already present. Retention may compress/delete raw logs after success. |
| “ReviewReadOnly” | Both review modes map to `workspace-write` plus the receipt writable root | Also true in the framework. The name does not imply OS-enforced repository read-only access. |

Source anchors: [path validation](/P:/source-project/tools/Invoke-CodexDispatch.ps1:494), [sandbox/run setup](/P:/source-project/tools/Invoke-CodexDispatch.ps1:635). Framework anchors: [containment](/P:/agentic-framework/core/tools/Invoke-CodexDispatch.ps1:719), [sandbox mapping](/P:/agentic-framework/core/tools/Invoke-CodexDispatch.ps1:860), [POSIX counterpart](/P:/agentic-framework/core/tools/Invoke-CodexDispatch.sh:642).

The open IDE path `_tmp-exec-review-r1-prompt.md` would fit the repository prompt-file rule **if it exists**; this pass did not find it in the file inventory. Its eventual reviewer output still needs preservation in a durable review artifact.

**Do not replace the framework wrappers with the source versions.** The source uses `-Kind execution-review`; the framework validates `plan|execution|discovery|handoff|multi-handoff` against its ledger. It also records usage before log retention, binds review intent, and uses a shipped schema adapter. Those are coupled contracts. Copying a source command example verbatim would fail here or lose controls.

Likewise, the source's recommendation to use FullAccess for Windows reviews describes its sandbox-helper failures. Adoption should probe the actual supported sandbox and required write roots, then use the least permissions that work within the project's authorization. A temp path alone is not a reason to turn sandboxing off.

Codex documents JSONL events, schema-constrained final output, and explicit output files. Those features support the wrapper design, but they do not provide the framework's verdict ledger or durable-evidence policy. [Official non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode)

### The important new rule: promote evidence before scratch disappears

Source Project now distinguishes:

1. **Working output:** raw redirected receipts and dispatch files, useful during the run.
2. **Durable record:** the exact command, its exit code, and decisive output pasted into a repository artifact.
3. **Verification:** an independent reviewer can inspect and rerun relevant checks; a pasted summary is not automatically proof of truth.

A scratch path alone is no longer lasting evidence. The source permits a scratch path in a durable artifact only as part of the command. This applies to handoffs, reviews, blocked rows, and lasting claims. See [source evidence policy](/P:/source-project/.agent/docs/artifact-naming.md:5).

For the framework, use the existing F3 receipt root and F1/F2 artifact-home choices. **Do not add another directory token merely to rename receipts.** Amend F3b: retaining raw receipts across reboot may still be useful, but durable evidence must survive removal of those receipts. For sensitive domains, promote redacted decisive excerpts and approved provenance under PROFILE C; storing raw secrets in Git is not the goal.

Suggested evidence-block contract, to be integrated into existing templates:

```yaml
check_id: AC-3-green
command: <exact executed command or script invocation>
cwd: <project-relative working directory>
scope: <explicit paths or suite>
phase: green
exit_code: 0
result: pass
tested_state: <commit plus dirty-tree fingerprint when needed>
output: |
  <decisive actual output, including failing IDs or passing summary>
```

This is a proposed shape, not an already supported schema. Missing output, skipped execution, and tool startup failure must remain distinguishable. Large binary evidence may live in an approved durable artifact store with stable identity and access instructions; the repository record still needs the decisive summary. No claim should depend only on a machine-local scratch link.

### Enforcement dependencies and limits

The source [citation scanner](/P:/source-project/tools/check_temp_citations.py:1) scans tracked and nonignored untracked files. Its per-file count ratchet tolerates old debt and rejects increases. However:

- Its regex recognizes one hardcoded Windows receipt prefix, not arbitrary `/tmp`, user cache directories, or configured roots.
- It excludes tooling/test trees and uses source-specific product prefixes.
- It exempts all fenced content; its own documentation acknowledges missed citations in text/diff fences.
- A per-file count baseline does not prove old findings disappeared; one can be replaced by another without increasing the count.

Port it as a configurable migration aid, not proof that every artifact is durable. Use configured scratch roots, native case/separator rules, and explicit durable-artifact scan scope. Add semantic template checks for evidence blocks. Never copy the source's populated baseline; use `{}` for new projects and an explicitly reviewed baseline only for existing projects.

The source [blocked-evidence predicate](/P:/source-project/tools/plan_validators/blocked_evidence.py:125) requires a linked `B-<row>` block with command/error fences or a linked decision. Its implementation checks a follow-up keyword rather than validating the target, and does not explicitly require an exit-code field. The portable version should enforce the proposed contract rather than promise more than the parser checks. Reuse one predicate from both framework task and closeout validation.

Keep test fixture temp space distinct from dispatch receipts and durable evidence. Pytest gives each `tmp_path` test its own directory, retains a limited number of runs by default, and clears an explicitly supplied `--basetemp` directory before use. Therefore never point `--basetemp` at a shared receipts/evidence root. [Pytest temporary-directory documentation](https://docs.pytest.org/en/stable/how-to/tmp_path.html)

## 4. TDD and testing: what changed and what did not

**Already shared:** acceptance criteria and source labels before implementation; failing bug reproduction before a production fix; Red → Green → refactor; no weakening assertions to obtain green; no silent skip/early-return guards; real behavior checks and reproducible failures. The tester-role files compare equal (Git no-index diff exit 0). The source root rewrite compresses this policy rather than replacing it.

**New committed validation behavior:**

| Stage | Purpose | Portable rule |
|---|---|---|
| Red | Prove the unmet behavior | Preserve the expected failure and its reason. A dependency/import/collection error is not automatically a valid Red. |
| Static | Cheap correction feedback | Run configured lint/types/contract checks before expensive suites. |
| Targeted | Validate affected behavior | Record selected tests and scope. Never present this as a full gate. |
| Full | Establish the final review baseline | Fresh run on the final review tree; paste decisive results. No cached or snapshot-only substitute. |
| Reuse | Avoid duplicate intermediate validation | Only with matching code, test, configuration, environment, and external-input identity; unavailable means rerun. |
| Snapshot / lease / tree delta | Protect validation from concurrent edits | Optional when the adopter implements equivalent isolation and identity checks. Fail or rerun when the reviewed inputs change. |

Source: [testing strategy](/P:/source-project/.agent/docs/testing-strategy.md:156) and [TDD post-MEU gate](/P:/source-project/.agent/workflows/tdd-implementation.md:170).

The source additionally makes coverage advisory/opt-in for the scoped gate, records later stages as `not_run` after a blocking failure, and skips integration where its touch-prefix policy permits. Translate these into project-owned scope and coverage choices; do not copy Python package prefixes or numeric coverage floors into unrelated projects. Changes to shared test configuration and fixtures must influence scope, not just changes to production folders.

**Reconcile before porting:** both trees still contain TDD reminder commands that read receipts without preserving the process exit code. The source TDD closeout also says to run a full regression after the MEU gate, while newer workflow guidance avoids repeated full runs. Make the command registry the executable authority and clarify one final fresh full gate. Do not perpetuate these conflicting examples.

Keep acceptance criteria stable during Green. If research proves an expectation itself is wrong, route through an explicit specification amendment and independent review before changing the test; do not force production code to satisfy a known-wrong assertion. This is a proposed clarification of the existing rule, not a reported September source change.

### Uncommitted work: observe, do not import as finished policy

Current Source Project diffs add a 120-second pytest hang guard, a 15-second slow-test budget with reasoned exemptions, JUnit timing analysis, and shorter configurable waits in test setup. The in-progress code refers to G40 / “Test Wait Budget,” but those sections were not present in the inspected instruction documents. Its Claude settings also have a pending permissions-ask deletion. Treat these as working-tree observations, not approved defaults or completed governance changes.

A future portable timing policy should distinguish deadlock protection from performance budgets; calibrate limits by environment; isolate test waits through injected clocks/configuration where behavior permits; and retain explicit real-timing integration coverage where needed. Do not export the source's 120/15-second values or exemption list without that work being finalized and verified.

## 5. Concrete template and adoption changes proposed

Keep the current placeholder installer for values it already owns. Put behavioral choices in the project profile rather than adding an independent configuration authority.

| Existing owner | Proposed addition or revision |
|---|---|
| PROFILE A / harness profiles | Record instruction discovery/budget, hook availability, shell, and verified sandbox write capabilities. Hooks remain disabled until tested. |
| PROFILE C / review routing | Apply egress/redaction policy to promoted evidence and reviewer input as well as code. Preserve human-only review. |
| PROFILE D6 | Register static, targeted, full, and optional runtime checks: argv or manual procedure, cwd, scope, blocking status, expected result, shell, evidence format. |
| PROFILE D / domain mapping | Software uses executable Red/Green; other domains use predeclared falsification/acceptance evidence and independent review. No artificial pytest requirement. |
| PROFILE F3/F3b | Distinguish receipt retention from durable evidence; prohibit scratch-only evidence after closeout. |
| Adoption guide | After substitution, resolve paths, verify instruction budgets, bind actual validation commands, exercise evidence promotion and a failing gate, then run a small adopter task. |
| Update checklist / manifest | Record source commit and each deliberate divergence; list every new mechanism, dependency, test, and supported harness. Replace blanket recopy advice for divergent files. |

### Proposed merge sequence

| Work package | Files / areas | Acceptance before proceeding |
|---|---|---|
| M0 — Packaging baseline | Existing sanitizer/reference checks, source/framework inventory, preservation of local edits | Verification is read-only; template-home aliases resolve; baseline failures are fixed or explicitly scoped with no new failures. |
| M1 — Durable evidence | Output-evidence policy, artifact naming, terminal preflight, dispatch skill, handoff/review/task templates, completion preflight, shared blocked-evidence predicate | An example closeout remains interpretable after its scratch directory is unavailable; missing exit/output and scratch-only evidence are rejected. |
| M2 — Instruction rewrite | AGENTS, GUARDRAILS, CLAUDE, section registry, workflow backlinks | All existing hard gates and adoption choices mapped to successors; byte budget passes after instantiation; no unsupported enforcement claims. |
| M3 — Validation contract | D6 profile/questions, testing strategy, TDD workflow, quality-gate skill, execution/review workflows, task template | Scoped/partial output cannot satisfy full validation; nonzero exits survive receipt reads; final review follows a fresh gate on the reviewed state. |
| M4 — Optional mechanisms | Configurable citation scanner, empty baseline, rule-budget audit, harness-specific hooks and fixtures | Demonstrate rejection cases and documented failure behavior. No source registry paths, source product prefixes, or source hook settings copied wholesale. |
| M5 — Adoption proof and release review | Adoption guide/checklist, manifest, adoption tests and representative fixture projects | Windows and POSIX adoption; shell/RTK variants; external and human-only review; software and manual validation. Independent review before release. |

M1–M3 are the first useful migration slice. M4 is an explicit follow-on if runtime enforcement is desired; M2 must retain prose obligations wherever a mechanism has not shipped. Snapshot/reuse/lease optimization is not needed to adopt the basic tiering contract.

### Minimum verification scenarios for implementation

1. Instantiate into a path with spaces and a nondefault receipt root; preserve unrelated project files and supplied choices.
2. Check instruction bytes after substitution and nested-loader composition; verify bootstrap/import targets exist.
3. Verify allowed prompt locations, output containment, symlink/junction escapes, run-ID collisions, and nonzero exit propagation on both wrappers.
4. Confirm framework ledger kind/intent/vendor/usage handling survives; record results before retention and preserve the final verdict durably.
5. Reject a scratch-only handoff, incomplete blocked block, malformed evidence, and partial gate presented as full; accept legitimate command redirects.
6. Demonstrate a real Red caused by missing behavior, Green after implementation, and a changed final input invalidating earlier full evidence.
7. Run a docs-only or non-software adoption without fabricated code tests; run an egress-forbidden adoption without external dispatch.
8. Verify optional hook arming and sanctioned release; show that a released/unarmed hook does not substitute for closeout approval.

These are proposed acceptance scenarios, not tests executed in this research pass.

## 6. Current packaging baseline and research checks

Executed from the framework root:

```powershell
rtk proxy python scripts/refcheck.py --all *> C:/Temp/agentic-framework-research/refcheck-before.txt
$code=$LASTEXITCODE
rtk proxy rg -n 'REQUIRED-DANGLING:|UNRESOLVED:|UNCLASSIFIED:' C:/Temp/agentic-framework-research/refcheck-before.txt
exit $code
```

Exit: **1**. Decisive output:

```text
REQUIRED-DANGLING:        3
UNRESOLVED:               73
UNCLASSIFIED:             4
```

These match the older gate-repair note and predate this proposal. The four unclassified sites concern an absent PowerShell preflight twin, a product validator, and two example scripts. Treat a clean deployment claim as unproven until repaired or deliberately classified.

The sanitizer's `--verify` path is still mutating: [current implementation](/P:/agentic-framework/scripts/sanitize.py:527) writes replacements whenever `dry_run` is false, before verification. I did not run it on this working tree. A future refresh must fix that behavior or evaluate a disposable copy. Likewise, line-count reduction alone is not proof that instruction semantics survived.

Other checks completed: commit-history inspection; source working-tree diff classification; byte/line measurements; tester-role equality; wrapper code inspection; current official-source retrieval. Dispatch, hook behavior, source test suites, and cross-platform execution were **not** exercised. Source test files were inspected as contracts, not reported as passing runs.

After writing this proposal, the reference checker returned the same exit 1 and the same 3/73/4 failure counts. All 15 local links resolved. Working-tree status showed only this new proposal in addition to the two pre-existing framework changes; framework templates and executable tooling were not edited.

## 7. External guidance and its limits

- **Instruction loading:** OpenAI documents the root-to-CWD discovery chain and a configurable 32 KiB default. This supports byte-budget tests; it does not establish any universal optimal instruction length. [OpenAI](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- **CLI output:** OpenAI documents separated progress/final output, JSONL mode, and output schemas. Durable evidence promotion remains a framework design decision. [OpenAI](https://learn.chatgpt.com/docs/non-interactive-mode)
- **Concise instructions and verification:** Anthropic recommends concise always-loaded guidance, on-demand skills for specialized material, and explicit ways to verify results. This supports the proposed split between root rules and detailed procedures; it does not prove Source Project's exact rule count is optimal. [Anthropic](https://code.claude.com/docs/en/best-practices)
- **Temporary test data:** Pytest's documented retention and cleanup behavior supports isolating fixture storage from audit evidence. [Pytest](https://docs.pytest.org/en/stable/how-to/tmp_path.html)

The migration recommendations combine those documented behaviors with the local diffs. No vendor claim is used to treat source-specific thresholds, model versions, hook guarantees, or sandbox bypasses as universal defaults.


Source identity and source-machine paths in this historical report have been generalized. Source paths are illustrative references, not live local links.
