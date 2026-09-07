# Capability classes

Instruction files name a **class**, never a snapshot. The registry binds each
`(class, harness)` pair; a bump edits that binding and no caller. This document
is the class list for adopters of this package. It does not record which
snapshot any class resolves to on any machine.

Pair this with the registry home you instantiate from this directory (see
[`INSTANTIATE.md`](../INSTANTIATE.md)). Ask the resolver rather than copying a
value into prose.

## `resolve` — paste-able dispatch

`tools/ModelRegistry.psm1` exports
`resolve <class> [-Harness x] [-AuthorVendor y] [-Project p]`.
Adopters' command templates depend on it (`-m $(resolve independent_reviewer)`).
Classes that declare `vendor_distinct_from: author` still need `-AuthorVendor`
at call time — omitting it is `author_vendor_required`, not a silent assume:

```powershell
$ErrorActionPreference = 'Stop'
Import-Module <registry-home>/tools/ModelRegistry.psm1
codex exec -m $(resolve independent_reviewer -AuthorVendor xai -Project <project-root>)
```

The function prints the **bare slug** and nothing else, because the result lands
in an argv position: any decoration would become part of the model name the CLI
receives.

Two more lines of that shape carry weight. `$ErrorActionPreference = 'Stop'`
turns a failed resolve into a stopped command: under the default `Continue`,
the `$(...)` substitution yields an empty argument and the CLI launches on
whatever the account default happens to be. `-Project` names the repo whose
overlay governs the answer; without it the global catalog replies and the
project's floors, pins and vendor rules never enter the resolution.

Harness inference:

- If the class binds **exactly one** harness, `resolve` infers it.
- If the class binds **several** (or none), it raises `ambiguous_harness` rather
  than guessing. A silently wrong harness still resolves to a real snapshot, so
  the dispatch would succeed on the wrong surface and nothing downstream would
  notice. Pass `-Harness`. `coordinator` is the usual several-harness case:

```powershell
claude -p --model $(resolve coordinator -Harness claude-p -Project <project-root>)
```

`independent_reviewer` declares `vendor_distinct_from: author`. Omitting
`-AuthorVendor` on that class is `author_vendor_required`, not a silent assume.

The Python equivalent (same S2 locate order) is
`python <registry-home>/tools/resolve_model.py resolve <class> --harness <harness> --project <project-root>`.

## The twelve global classes

Overlay-only classes belong in a project's `.agent/model-registry.local.yaml`,
not here. An overlay may add classes and tighten constraints; it may never
loosen a global contract.

| Class | What it is for | Contract (capability, not identity) |
|---|---|---|
| `coordinator` | Orchestration, planning, architecture, synthesis, governance-doc edits, correctness-critical reasoning | `orchestration`, `deep_reasoning`, `agentic_exec`. Never bind this class to the architecture-reserved snapshot. |
| `builder` | Bulk implementation, mechanical edits, test scaffolding, file/log audits, doc sweeps | `agentic_exec`, `bulk_edit`. `price_ceiling_band: high` so both a cheap mechanical pin and a stronger pin can satisfy it. `inherit_allowed: false`. Same architecture-reserved forbid as `coordinator`. |
| `verifier` | Read-only validation of one `task.md` row | `extends: builder`. A separate class so it can diverge later without touching callers. |
| `router` | High-volume classification, triage, inventory, routing decisions | `classification`. `price_ceiling_band: low`. Not for real logic or multi-file reasoning. |
| `independent_reviewer` | Adversarial plan and code review | `code_review`, `agentic_exec`, `read_only_sandbox`. `vendor_distinct_from: author`. `auth_mode: chatgpt-plan`. Cross-vendor diversity is the point; the resolver will not guess the author vendor. |
| `checklist_validator` | Checklist-shaped validation with no risk path | `checklist_review`. `price_ceiling_band: low`. A cheap route, not a discount reviewer. |
| `surface_orchestrator` | Low-reasoning surface work | `surface_edit`. `scope: surface_only`. **Never** troubleshooting or deep-infra. |
| `isolated_worker` | Isolated-context bursts, one per worktree | `agentic_exec`. `not_a_reviewer: true`. Not a substitute for `independent_reviewer`. |
| `architecture_single_shot` | Very large one-shot architecture reasoning | `very_large_single_shot`. `invoke_only_on_explicit_human_direction: true`. Never a coordinator default and never a `builder_model` pin. |
| `translator_prose` | Long-form translation whose voice must survive | `long_form_prose`. `vendor_allow: [openai]`. `effort_floor: high`. `auth_mode: chatgpt-plan`. |
| `image_generator` | Image dispatch | `image_gen`. `auth_mode: chatgpt-plan`. The binding may carry `extra_args` the harness needs to enable generation. |
| `creative_prose` | Prose whose voice matters, and the second reader on it | `creative_prose`. `vendor_allow: [anthropic]`. Pin by *difference* from the drafter, not by recency. |

## Review chain (policy, not identity)

The implementing agent never authors its own `approved` verdict. The class's
declared `fallback_rungs` are the chain, in order:

1. `independent_reviewer` — primary. Cross-vendor; read-only sandbox.
2. `surface_orchestrator` — secondary, **surface-level work only**.
3. `coordinator` on `claude-p`, flagged when the author vendor matches — last
   resort, weaker diversity, never same-session self-review.

Rate-limit rungs *within* a binding (`fallbacks:`) are reported by the resolver
and never auto-selected, so a receipt always says which snapshot actually
answered.

## What this document must not do

- Name a snapshot, a harness alias, or a dollar figure. Those live in the
  catalog of the **live** registry home you instantiate.
- Copy another machine's bindings into this package. A bump is a live-registry
  edit, not a recopy of this tree.
