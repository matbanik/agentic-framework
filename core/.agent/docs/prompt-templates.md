# Prompt Templates for Agentic Build Plan Execution

> Copy, fill in the blanks, and paste into your AI agent IDE.

---

## Start a Build Session

```
Use /create-plan to scope the next project.
```

The `/create-plan` workflow reads handoffs, meu-registry, and build-plan files to automatically scope and plan the next project. No manual prompt drafting needed.

---

## Validate a Completed MEU (Codex)

```
Read AGENTS.md.
Read the handoff at .agent/context/handoffs/{SEQ}-{date}-{slug}-bp{NN}s{X.Y}.md.
Read ALL changed files listed in the handoff.

Use /validation-review workflow to validate the MEU.
```

---

## Resume Interrupted Work

```
Read .agent/context/current-focus.md.
Read .agent/context/known-issues.md.
Check .agent/context/handoffs/ for the most recent handoff.

Resume work on {brief description of what was in progress}.
```

---

## Research Before Building

```
Use /pre-build-research workflow.
Topic: {what you need to understand before coding}.
Focus on: {specific patterns, libraries, or constraints}.
```

---

## Tips

- **Use `/create-plan` to start.** It replaces manual prompt drafting — the agent discovers what's done and scopes the next project automatically.
- **Reference the workflow.** The `/tdd-implementation` and `/validation-review` slash commands trigger the full step-by-step process.
- **Always read context first.** The agent performs better when it reads `current-focus.md` and `known-issues.md` before coding.
