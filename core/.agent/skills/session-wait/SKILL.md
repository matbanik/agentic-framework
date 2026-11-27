---
name: session-wait
description: One wait script for a parked plan. A plan gives a list of named conditions. The script polls them as a background command, and its exit wakes the session that holds the plan. Covers the command forms, the conditions, the wait record, the wake path and the two rules.
---

# Session Wait Skill

`tools/session_wait.py` waits until a set of named conditions hold. A plan does not
write its own watcher script. The plan gives a list of named conditions, and this one
script polls them.

## The wake path

1. The session that holds the parked plan starts `wait` as a background command.
2. The script polls the conditions. It needs them to hold for a stable time.
3. The script stops with one token and one exit code. Its exit wakes that session.
4. The session reads the token, then runs `use` one time to change the record from
   `fired` to `used`. Thus a second watcher cannot start the same work.

## Command forms

```bash
uv run python tools/session_wait.py check --cond plan_done:<plan> --cond lanes_free
uv run python tools/session_wait.py wait --name <id> --plan <plan> --owner <session> \
    --cond <cond> --direction-session <session> --direction-message <uuid> \
    --direction-quote "<quote>"
uv run python tools/session_wait.py list
uv run python tools/session_wait.py use --name <id>
```

- `session_wait.py check` evaluates each condition one time. It prints `hold`, or
  `wait` and each reason why not. Exit 0 is hold and exit 1 is not. It does not sleep
  and it writes no file.
- `session_wait.py wait` checks at the start, then each 120 s. The conditions must
  hold for a stable 300 s. The cap is 72 hours. A check that does not hold starts the
  stable time again. The last line is `wait_ok <line>` with exit 0, or
  `wait_timeout last: <line>` with exit 5. A refusal is `wait_refused:<reason>` with
  exit 1. `--poll-s`, `--stable-s` and `--cap-s` change the three values.
- `session_wait.py list` shows each wait: the plan, the state, the owner, the
  runner (`alive` or `dead`), the conditions and the last check. `--json` gives the
  same data as JSON.
- `session_wait.py use` changes a `fired` record to `used` one time. A second `use`
  gives `use_refused:used`.

A usage error prints `usage_error:<reason>` and exits 2.

## The named conditions

The names are a closed set. An unknown name is a usage error.

| Condition | Holds when |
|---|---|
| `plan_done:<plan>` | Run-parameters shows `released:done`, the approved verdict exists, the completion preflight passes, and the plan's `task.md` on `main` shows `complete` and `released:done`. |
| `plan_idle:<plan>` | The plan's `task.md` status is not `in_progress`. |
| `lanes_free` | `tools/lanes.py list` shows no active, landing or bad card and no `HALT`. `--exempt <lane>:<ruling>` leaves out one lane and the check line prints it. `HALT` is never exempt. |
| `paths_clean:<path>[,<path>]` | `git status --porcelain` shows nothing under the paths. |
| `no_busy_run` | The credits store at `--credits-db` shows no busy run, no open segment and no claimed lane on the tree lane. `--credits-lane` sets another lane. |

A reader that fails or passes its time limit does not hold.

## The wait record

Each wait has one JSON record in `<git-common-dir>/session-wait/<name>.json`. The
record holds the plan, the conditions, the owner session, the process id, the state,
the last check and the reference to the user's typed direction: the session, the
message id and the quote. `wait` refuses to start with no direction reference.

The states are `armed`, `fired`, `used` and `timeout`. One kernel lease on
`<name>.lock` keeps one runner for each wait. A second `wait` on a live runner gives
`wait_refused:busy:<holder>`. A `wait` on a dead runner, or on a `timeout` record,
arms the wait again. The receipt is `<git-common-dir>/session-wait/<name>.log`, or the
file that `--receipt` names.

## Rules

1. A wake-up carries no authority. Row R0 with `tools/run_parameters.py verify` stays
   the only gate before the woken session starts work.
2. Make the context small before a long wait, so the woken session has space to work.
