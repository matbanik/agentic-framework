---
description: "Generate 3 portal-ready deep research prompts (ChatGPT/Gemini/Claude) for a topic, grounded in fresh provider capability recon via Pomera MCP, saved to _inspiration/"
---

# Inspiration Research Workflow

Generate 3 deep research prompts — one per provider — each tailored to that provider's **currently
verified** portal capabilities. The human pastes each into the provider's native web portal.

**Procedure lives in `.agent/skills/deep-research-prompting/SKILL.md`.** Read it before Step 0.
This file is orchestration only; the skill owns the preflight gate, query bank, engine routing,
snapshot format, and prompt templates.

// turbo-all

## Input

```
/inspiration-research <topic description>
```

Example: `/inspiration-research CLI agentic coding tools with subscription support`

## Non-Negotiables

1. **Portal submission only.** The deliverable is paste-ready text for the web UI. Never substitute
   an API or CLI path — the portals carry capabilities those surfaces do not (SKILL §Prime Directive).
2. **Recon before writing.** Provider capabilities are verified by live search in Step 2, *before*
   any prompt is drafted. No prompt may assert a capability the recon did not confirm.
3. **Pomera MCP is the search surface.** Tavily and Exa route through Pomera. If Pomera is not
   working, **notify the human and stop** — do not silently fall back (SKILL §1).

---

## Steps

### Step 0: Pomera Preflight — HARD GATE

Run **SKILL §1** in full: `pomera_system{action:diagnose}` + one live `pomera_web_search` probe.

- **PASS** → continue to Step 1.
- **FAIL** → emit the SKILL §1 failure message and **end the turn**. This is a sanctioned
  turn-ender (human-decision gate). Do not proceed to Step 1, do not use native `WebSearch`
  unless the human explicitly waives the gate in a chat message.

### Step 1: Parse Topic & Create Directories

Derive a kebab-case slug (max 5 words) from the topic.

```powershell
# // turbo
$slug = "<topic-slug>"
New-Item -ItemType Directory -Force -Path "_inspiration/$slug" | Out-Null
New-Item -ItemType Directory -Force -Path "_inspiration/_capabilities" | Out-Null
```

Resolve today's date via `.agent/skills/timestamp/SKILL.md` — needed for snapshot TTL math and the
`verified:` stamps. Never use a remembered date.

### Step 2: Provider Capability Recon

For each of ChatGPT, Gemini, Claude:

1. Read `_inspiration/_capabilities/{provider}.md` if it exists.
2. Apply the **SKILL §4 TTL table** — missing/stale (> 14 days) → full recon; fresh (≤ 14 days) →
   one delta query.
3. Run the **SKILL §3 Query Bank** (R1–R3, plus R4/R5 only if model identity or a portal
   affordance is still ambiguous) through Pomera, routed per the **SKILL §2 Engine Routing Table**.
4. Write/refresh `_inspiration/_capabilities/{provider}.md` in the **SKILL §4 snapshot format**,
   including the `## Delta Since` section.

Answer three questions per provider (SKILL §3): **model identity**, **capability delta**,
**constraint delta**. Unresolved items are written as `unknown` — never inferred, never guessed
from API behavior.

> Snapshots are shared across all topics. A topic run inside the TTL window costs one delta query
> per provider, not a full sweep.

### Step 3: Topic Context Research

3–5 Pomera searches on the topic itself, routed per SKILL §2 (Tavily basic for recency, Exa neural
for niche practitioner material):

```
"<topic> best practices {YEAR}"
"<topic> community tools comparison"
"<topic> developer experience reviews"
```

Collect dated URLs — they populate the `## Context` block of every prompt.

### Step 4: Generate 3 Tailored Prompts

Build each file from the **SKILL §5 shared skeleton**, filling `{MODEL}`, `{CAPABILITIES}`,
`{CONSTRAINTS}`, `{PORTAL_STEPS}`, `{VERIFIED_DATE}` from that provider's Step 2 snapshot and
`{TOPIC_CONTEXT}` from Step 3. Apply the per-provider objective slant:

| File | Provider | Slant |
|---|---|---|
| `prompt-d1-chatgpt.md` | ChatGPT | Competition & breadth |
| `prompt-d2-gemini.md` | Gemini | Trends & communities |
| `prompt-d3-claude.md` | Claude | Strategy & differentiation |

Keep the three scopes **overlapping** — the overlap is what Step 7 triangulates.

### Step 5: Save & Verify

```
_inspiration/{topic-slug}/
├── prompt-d1-chatgpt.md
├── prompt-d2-gemini.md
└── prompt-d3-claude.md

_inspiration/_capabilities/
├── chatgpt.md
├── gemini.md
└── claude.md
```

Run the **SKILL §7 Pre-Save Checklist** against actual file state before presenting.

### Step 6: Present to User

```
## Research Prompts Generated — {topic}

Capability recon: {verified date} · {fresh|cached} per provider

| # | Provider | Model (verified) | Portal | File |
|---|----------|------------------|--------|------|
| D1 | ChatGPT | {model} | chatgpt.com → Deep Research | [prompt-d1-chatgpt.md](...) |
| D2 | Gemini  | {model} | gemini.google.com → Deep Research | [prompt-d2-gemini.md](...) |
| D3 | Claude  | {model} | claude.ai → Research mode | [prompt-d3-claude.md](...) |

New capabilities folded into prompts this run: {list, or "none since {date}"}

Run all 3 in parallel on their native portals. Save outputs back to
_inspiration/{topic-slug}/ as output-chatgpt.md, output-gemini.md, output-claude.md,
then ask for synthesis.
```

### Step 7: Triangulation Synthesis (on return)

Not part of the generation run — invoked when the human returns with outputs present in
`_inspiration/{topic-slug}/`. With ≥ 2 outputs, write `synthesis.md` using the
**SKILL §6 band table**: Consensus / Single-source (VERIFY) / Contradiction / Gap, every line
attributed to its provider(s).

---

## Error Handling

| Condition | Action |
|---|---|
| Pomera preflight fails | **Stop and notify** (Step 0). Never a silent fallback. |
| A provider's recon returns nothing usable | Write the snapshot with `confidence: contested` and `unknown` fields; say so in Step 6. Do not fabricate a model name. |
| Sources disagree on the current model | Record both in the snapshot, mark `confidence: contested`, and have the prompt name both. |
| Topic too broad | Ask the human to narrow scope before Step 2 — recon is wasted on an unstable topic. |
| A portal mode was renamed/removed | Capture it in the snapshot's `## Delta Since` as REMOVED and point `## Portal Setup` at the closest current mode. |

## Exit Criteria

- [ ] Step 0 preflight passed (or an explicit human waiver is recorded in the snapshots)
- [ ] 3 capability snapshots exist with `verified:` ≤ 14 days old
- [ ] 3 prompt files created in `_inspiration/{topic-slug}/`
- [ ] Each prompt names a specific verified model and carries `## Current Capabilities`,
      `## Portal Setup`, `## Context`, `## Required Output Structure`, `## Evidence Rules`
- [ ] SKILL §7 checklist run against actual file state
- [ ] Table presented with model + recon date per provider
