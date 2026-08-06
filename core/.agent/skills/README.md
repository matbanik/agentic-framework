# Agent Skills — Progressive Disclosure

Skills are domain-specific instruction sets loaded on demand, not at session start.
This prevents context window bloat as the project scales.

## When to Create a Skill

Create a SKILL.md when:
- A workflow involves domain-specific patterns not in `AGENTS.md`
- Instructions exceed ~20 lines and apply to only one concern
- A task requires specialized tool usage

## Skill Format

```yaml
---
name: {skill-name}
description: {one-line description}
applies_to: [paths or concerns this skill covers]
---

{Markdown instructions, examples, and patterns}
```

## Loading Strategy

- Agents read `AGENTS.md` at session start (always)
- Skills are loaded only when the task touches the skill's concern
- The orchestrator role determines which skills to load during PLANNING mode

## Packaged Skills

| Skill | Applies To | Content |
|-------|-----------|---------|
| `issue-triage/SKILL.md` | `.agent/context/known-issues.yaml`, planning | Record/verify/bucket/triage issues → `triage-output.yaml` |
| `meu-status/SKILL.md` | `.agent/context/meu-status.yaml`, planning | MEU SSOT query/update/render |
| `subagent-delegation/SKILL.md` | workflows, `task.md` execution | `fresh_worker` gate + builder/verifier dispatch |
| `cli-dispatch/SKILL.md` | external reviewer / CLI agents | Route tasks to Codex/Claude/Gemini/OpenCode |
| `completion-preflight/SKILL.md` | end of turn / closeout | Re-read `task.md` before claiming done |
| `pre-handoff-review/SKILL.md` | pre-review | Self-check patterns before independent review |
| `terminal-preflight/SKILL.md` | any shell command | Redirect-to-file / no-pipe P0 checklist |
| `quality-gate/SKILL.md` | validation | Type/lint/test/anti-placeholder gates |
| `git-workflow/SKILL.md` | commits | Agent-safe git (human-gated) |
| `timestamp/SKILL.md` | closeout | Canonical completion timestamps |
| `skill-optimizer/SKILL.md` | instruction docs | Bounded cross-vendor-judge edits (human adopts) |
| `session-meta-review/SKILL.md` | reflections | Friction taxonomy → Next Session Design Rules |
| `deep-research-prompting/SKILL.md` | `/inspiration-research`, deep-research prompts | Pomera preflight gate, capability snapshots, D1/D2/D3 prompt templates |

See `.agent/docs/triage-meu-loop.md` for how `issue-triage` + `meu-status` feed planning.
