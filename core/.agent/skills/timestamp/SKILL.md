---
name: "Completion Timestamp"
description: "Generate the canonical completion timestamp for workflow exit lines, handoffs, and reflections."
---

# Completion Timestamp Skill

Generate the project's canonical completion timestamp using the system clock and local timezone.

## Usage

Run the stamp script and use its output as the last line of your chat response, or embed it in handoffs/reflections:

```powershell
# // turbo
python .agent/skills/timestamp/scripts/stamp.py *> {{RECEIPTS_DIR}}/stamp.txt; Get-Content {{RECEIPTS_DIR}}/stamp.txt
```

## Output Format

```
🕐 Completed: YYYY-MM-DD HH:MM (TZ)
```

Example: `🕐 Completed: 2026-04-30 20:43 (EDT)`

## When to Use

- As the **very last line** of your chat response when a workflow requires a completion timestamp
- In handoff files (`🕐 YYYY-MM-DD HH:MM (TZ)`)
- In reflection files

## Why This Exists

Tool response `Created At` timestamps are UTC. Agents were incorrectly using them as local time, producing timestamps ~4 hours ahead of actual EDT. This script reads the system clock directly, eliminating the error.
