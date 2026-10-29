---
description: "Generate 3 portal-ready deep research prompts (ChatGPT/Gemini/Claude) for a topic, grounded in fresh provider capability recon via Pomera MCP, saved to _inspiration/"
---

# Inspiration Research Workflow

// turbo-all

## Usage

```
/inspiration-research <topic description>
```

Example: `/inspiration-research CLI agentic coding tools with subscription support`

## Project Setting

| Setting | Value |
|---|---|
| `project_output_root` | `_inspiration/` |

## Procedure

Read `.agent/skills/deep-research-prompting/SKILL.md` and
follow its §Orchestration (Step 0–7) with the setting above. That skill owns the Pomera preflight
hard gate, the recon query bank, the capability snapshots (kept in the skill's `capabilities/`
directory) and the prompt templates.
