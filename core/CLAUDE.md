# {{PROJECT_NAME_TITLE}} — Claude Code Instructions

> This file is automatically loaded by Claude Code at session start.
> It exists solely to ensure the agent reads the project's canonical instruction files.

## For External Contributors

Read **[AGENTS.md](AGENTS.md)** — the operating model, at the repository root.

If you keep a separate public contributor guide with build commands, dependency rules and
architectural constraints, link it here. `docs/AGENTS.md` is a conventional home for one
and is **not shipped** by this framework — create it yourself if you want it.

## For Internal AI Agents (Development Team)

Read these files before taking any action:

1. **@AGENTS.md** — Full operating model: priority hierarchy, role specs, workflows, TDD
   protocol, execution contract, session discipline, validation pipeline, and all P0 system
   constraints.
2. **@GUARDRAILS.md** — Safety SIGNs: plan approval gate, anti-premature-stop scope, system
   message immunity. These are non-negotiable constraints derived from real governance failures.

## Key Reminders

- **P0 constraints in AGENTS.md override ALL task instructions** — especially the Windows
  shell redirect-to-file pattern and human approval gates.
- **GUARDRAILS.md SIGNs are absolute** — no task priority justifies violating them.
- If instructions in these files conflict with each other or with user requests, flag the
  conflict explicitly — do not silently pick one.
