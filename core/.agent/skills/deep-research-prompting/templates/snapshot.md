---
provider: {chatgpt | gemini | claude}
verified: {YYYY-MM-DD — the day the searches ran, from the system clock}
source: pomera/tavily+exa
confidence: {high | mixed | contested}
picker_label: {model name exactly as the portal picker shows it, or unknown}
api_id: {API model id from a vendor page, or unknown}
catalog: {optional model-registry entry key; a cross-check, never a source}
sources:
  - {URL — each one has a raw dump under sources/{verified}/ whose url: matches}
---

# {Provider} — Deep Research Capability Snapshot

## Model
{picker label and the engine behind deep research, each with a quoted vendor sentence and its
URL; an engine the vendor does not name is written as unverified}

**Prompt-writer consequence:** {what the prompt says about the model, or that it says nothing}

## Portal Affordances
- {affordance} — {one line on why it matters for prompt design} [source URL]

## Constraints
- {plan gate / quota / runtime / source limit} [source URL]

## Delta Since {previous verified date}
- ADDED: {…}
- CHANGED: {…}
- REMOVED: {…}
- (or `First snapshot.`)

## Prompt Implications
- {imperative sentence telling the prompt writer what to do differently}
