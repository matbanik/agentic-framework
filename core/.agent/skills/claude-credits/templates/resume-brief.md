# Resume brief: `<run-id>`, segment `<generation>`

<!--
The resume brief template (report section 5.3, step 3). The agent fills in each section for one
resume and saves the result next to the run's other briefs, for example
`{{RECEIPTS_DIR}}/credits/<run-id>-resume-<n>.md`. It then passes that path to
`Start-CreditsRunTask.ps1 -Resume -Brief <path>`, with `-ResumeMode session` (the default, D-4 A)
or `-ResumeMode fresh`. Take the facts from `Get-CreditsRun.ps1 <run-id>`, not from memory.
Delete this comment and every placeholder line before the start.
-->

Resume mode: `<session | fresh>`. Reason for the mode: `<why; a fresh session needs a reason>`.

## Base briefs

All earlier briefs of this run still apply. This brief adds to them and replaces nothing that it
does not name.

- `<path of the first brief>`
- `<path of each earlier resume brief, oldest first>`

For a fresh session (`-ResumeMode fresh`), the full base brief follows here, because the new
session has no memory of the earlier ones:

`<the full text of the base brief, fresh mode only>`

## What happened

- The class of the stop: `<class from Get-CreditsRun.ps1>`.
- The interval: from `<last heartbeat UTC>` to `<end UTC>`, segment `<segment id>`, dispatch
  `<dispatch id>`.
- The host events in that interval: `<reboot, sleep, logoff, or none found>`.

Background tasks from before the stop are gone. Their notices will never arrive. Do not wait
for them; start again any work that they did.

## The ruling

`<the human's ruling, quoted word for word, or: No ruling was needed.>`

## Messages

Every open message is pending in the new delivery generation. The hook delivers it after your
first tool call (section 4.6.4, step 8). Act on each one when it arrives.

An open `stop-after-row` message is closed as `superseded_by_resume` by this resume: the resume
is the newer instruction from the human. The closed messages are:

- `<msg_id> stop-after-row: closed as superseded_by_resume, or: none>`

Messages that were delivered before the stop stay in the session transcript. For a fresh
session, they are listed here, because the new session does not have that transcript:

- `<msg_id> <kind>: <body>, fresh mode only>`

## Start authority

The human's resume words, quoted word for word as the agent passed them in `-StartQuote`:
`<the words>`. For a resume that the human started from their own terminal, write: `Started by
the human from their terminal.`

1. Run `python tools/credits_msg.py authority --quote "<the words>"` before any other action
   (no `--quote` for a terminal start). Exit 0 is the human's authorization for this segment
   within the scope of the briefs (GUARDRAILS SIGN 3 (b)).
2. A refusal is a stop: write `stop_gate: "released:human-gate"` and end with
   `STOPPED:decision`.

## What to do

1. After the start authority check, re-read the active `task.md`, the review file and the
   handoff before any other action. Disk beats memory.
2. Move partial receipts aside with a `-pre-<class>` suffix (for example `gate.txt` becomes
   `gate-pre-<class>.txt`). Never delete them.
3. Never reset git. Do not use `git reset`, `git checkout -- <path>`, `git restore` or
   `git clean` on the work of this run.
4. Re-run the last unfinished gate from the start. A partial gate receipt is not evidence.
5. Continue with the first open row of `task.md`.

## The foreground rule

Never end a turn to wait. That ends the run.

Run long commands in the foreground with a Bash timeout. Never use `run_in_background`: a turn
that ends while a background task runs stops the segment (G-8).

## Final message

Write `stop_gate` in `task.md` before the final message. The final message ends with this
block, filled in (report section 7.3). Nothing follows its last line.

```text
Status: DONE | PARKED:approved | STOPPED:<class>
Run: <run-id> segment <n>   Dispatch: <dispatch-id>
Rows: <done>/<total>  [B]: <count>        (exec only)
Review: <round> <verdict> <path>
Messages: <received>/<acknowledged>/<applied>
Decisions for the human: <none | D-n: one line each>
Next: <one line>
🕐 Completed: <timestamp>
```

Only `DONE`, `PARKED:approved` and `STOPPED:<class>` are terminal. Use a class of the
monitor's class table (`SKILL.md` §Schedule).

## Blocked rows

A row is `[B]` only under `AGENTS.md` §Execution Contract:

- a reproduced external error, with the exact command and its decisive error lines;
- a missing dependency, credential or permission, with the same evidence; or
- a human-decision gate, with a `Decision:` line.

Each `[B]` row has its evidence block and a linked follow-up. A repeated implementation failure
is not a blocker: keep working on it, or stop at a human gate if a real decision is needed.
