---
name: agent-notify
description: Stop notifier (opt-in). Sends the human one short email each time an agent session stops (done, needs a decision, waits for approval or input, hard-stopped, or failed). Covers the settings home, the six CLI actions, the off switches, the privacy rules, first-time Gmail setup and the per-harness wiring.
---

# Agent Notify Skill

`tools/agent_notify.py` emails the human when a session stops, so nobody has to watch the
terminal. It is one standard-library module behind every harness. It never blocks a stop:
every failure is logged and swallowed. It is off until the adopter turns it on
(`ADOPTION-GUIDE.md` Step 4d).

## When it fires

Each stop gets one class: `done`, `decision`, `approval`, `waiting`, `blocked` or `error`.
The rules are the classifier table in the module (`classify_explain`). Do not restate them;
read them there.

- **Claude Code.** A stop-gate hook, if your project has one, can hand every allowed or
  released stop to `agent_notify.on_stop`. Without one, the `Stop` hook calls the `hook` action
  directly. The `Notification` hook (`permission_prompt|idle_prompt`) and the `StopFailure` hook
  call the `hook` action. The opt-in block is `.claude/settings.notify.example.json`; merge it
  into `.claude/settings.json`.
- **Prose signals.** For a stop without a structured gate field, the classifier reads the end of
  the last reply: the `Checkpoint saved for <slug>. Status: <s>.` line and the
  `🕐 Completed:` line of the workflow exit gates. Keep those two lines last
  (`execution-session.md` exit gate).
- A dispatched child session never emails: the CLI-dispatch wrappers set `AGENT_NOTIFY=off`.

## Settings files and lookup order

The notify home is the first that is set: the `--home` argument, `AGENT_NOTIFY_HOME`
(for example in `.claude/settings.json` `env`), `$AGENT_MODEL_REGISTRY_HOME/notify`,
`~/.agent/notify`. Config is merged key by key: built-in defaults, then `notify.json`, then
`notify.local.json`. An unknown key or a wrong type logs `config_invalid` and sends nothing.

```text
<home>/
  notify.json          committed defaults: no address, "enabled": false
  notify.local.json    this machine only (never commit): to, from, smtp.user, enabled
  notify.off           optional empty file: every email off
  state/               notify.log.jsonl, sent.jsonl, pending/, outbox/ (dry run)
```

The schema is `schema/notify.v1.schema.json` in the registry home.

## Actions

Run `python tools/agent_notify.py <action>`. Redirect each run into a receipt under
`{{RECEIPTS_DIR}}`, as for any other command; never run `setup` through a receipt (it reads a
hidden prompt).

| Action | Use |
|---|---|
| `hook` | Handle one harness hook payload (stdin for Claude and Cursor, last argument for Codex). Prints nothing, exits 0 |
| `deliver` | The detached worker that sends one pending file. Prints nothing, exits 0 |
| `send` | `send --class <class> --text <text>`: a manual send for a harness with no hook API |
| `test-send` | One real message of class `done`, subject suffix `(test)`; ignores `enabled`, the gap and dedupe. `--dry-run` writes `state/outbox/*.eml` instead |
| `setup` | `setup --user <sender address>`: reads the SMTP app password at a hidden prompt and stores it in the credential store |
| `status` | The resolved home, the merged config with addresses masked, `credential: present\|missing`, cap usage and the last 5 log lines |

## Turning it off

Three switches, each checked first and each writes nothing at all:

1. Create the empty file `notify.off` in the home (delete it to turn email back on).
2. Set the environment variable `AGENT_NOTIFY=off` for the session.
3. Set `"enabled": false` in `notify.local.json` (the committed default).

For a narrower cut, set `events.<event>` or `classes.<class>` to `false`. The limits
`min_gap_s`, `dedupe_window_s`, `hourly_cap`, `daily_cap` and `auth_backoff_s` skip a send and
log one line that names the limit.

## Privacy rules

- **The body holds** the project, working directory, branch, harness, the first 8 characters of
  the session ID, the class and gate reason, the task file and its open-row count, a redacted
  excerpt of the last reply (600 characters by default), the time and the log path. At most
  2048 bytes.
- **The body never holds** the transcript, the environment, a diff or the transcript path.
- Redaction removes auth headers, bearer tokens, key/value secrets, Google app passwords and long
  base64 or hex runs from the excerpt, the reason, the log, the ledger and pending files.
- Addresses appear only in the envelope and headers of a message actually sent. The log, the
  ledger, `status` and dry-run files mask them.
- The SMTP password is never in a file, a log, a receipt or a chat. Never ask the human to paste
  it into the conversation.

## First-time setup

The full steps, with the Gmail app password, are in the transfer package's
`.agent/INSTANTIATE.md` §5 (heading "Gmail app password"). In short:

1. **Create the Gmail app password** at `https://myaccount.google.com/apppasswords` (2-Step
   Verification must be on). Name it `agent-notify`; copy the 16-character password.
2. **Store it.** `python tools/agent_notify.py setup --user <sender address>`, then paste at the
   hidden prompt. Windows: Credential Manager, generic credential
   `agent-notify:smtp:<sender address>`. macOS and Linux: `keyring`. The env variable
   `AGENT_NOTIFY_SMTP_PASSWORD` is a CI-only fallback.
3. **Write `notify.local.json`** in the home with `to`, `from`, `smtp.user` and
   `"enabled": false`.
4. **Test.** `status` shows `credential: present`. Run `test-send --dry-run` and read the
   `.eml` in `state/outbox/`. Then run `test-send` and confirm the message arrived.
5. **Enable.** Set `"enabled": true` in `notify.local.json`, then wire your harness (below).
6. **Revoke or rotate.** Delete `agent-notify` on the App passwords page to revoke it. To rotate,
   create a new one and rerun `setup`.

## Harness wiring

| Harness | `stop_notify` | Wiring |
|---|---|---|
| Claude Code | `hook` | `Stop`, `Notification` and `StopFailure` hooks → `hook --harness claude` (`.claude/settings.notify.example.json`) |
| Codex CLI | `notify-config` | `notify = ["python", "<repo>/tools/agent_notify.py", "hook", "--harness", "codex"]` in `~/.codex/config.toml`; Codex passes the JSON as the last argument |
| Cursor | `hook` | A `stop` hook in `.cursor/hooks.json` running `python tools/agent_notify.py hook --harness cursor` |
| Prose-only driver | `prose` | Run `python tools/agent_notify.py send --class <class> --text "<one-line summary>"` before the harness's end-turn signal (for example `notify_user`) |
| headless `claude -p`, UNKNOWN | `none` | No email; the dispatch wrappers set `AGENT_NOTIFY=off` |

The flag is defined in `.agent/docs/harness-profiles.md`.

## Troubleshooting

- No email: run `status`. Read the last log lines for the skip reason (`credential_missing`,
  `config_invalid`, a limit name, `auth_failed`, `smtp_error`, `tls_error`, `timeout`).
- `auth_failed` starts a backoff (`auth_backoff_s`). Fix the password with `setup`, then
  `test-send`.
