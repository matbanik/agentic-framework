# Fleet MVP: instructions for agents

- A member's setup agent follows `.agent/fleet/bootstrap.md`, and nothing else in this folder.
- A <hub host> session uses the `fleet.py` verbs and reads their JSON output, not their printed text.
- Authority rules are enforced by the hub, not by this note: plan §Named definitions, `SEND_POLICY`.
- Never put a secret in a task, a brief or a manifest. Never read a member's `member.json`.
- Never set or unset `CLAUDE_CODE_ENTRYPOINT` or `CLAUDECODE`, and never switch the login slot from
  an agent session.
