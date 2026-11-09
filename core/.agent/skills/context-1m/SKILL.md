---
name: context-1m
description: Turn the 1M context window on or off for every Claude Code session on this machine by adding or removing `"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"` under `env` in ~/.claude/settings.json. Use when the user says "/context-1m on|off|status", "turn 1M context on/off", "disable the 1M window", or asks which context window new sessions will get.
argument-hint: "[on|off|status]"
---

# context-1m

One switch, one file: `~/.claude/settings.json` → `env.CLAUDE_CODE_DISABLE_1M_CONTEXT`.

This skill is for Claude Code only. Other harnesses ignore the file. It is a **user-level**
skill: it changes a machine-wide setting, so it is installed in `~/.claude/skills/`, not in a
project. The install steps are in `ADOPTION-GUIDE.md` §1M context switch.

| Argument | Effect on the file | Result for new sessions |
|---|---|---|
| `on` | removes the key (and an `env` block left empty) | models that offer a native 1M window run with 1M; auto-compact moves up near the top of that window |
| `off` | sets `"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"` (creates the file if it is missing) | every model runs with the 200K window |
| `status` | nothing | prints the current state |

No argument → run `status` and ask which way to switch.

## Run

Write the output to a receipt file in the OS temp directory. Do not pipe it into a filter
(`.agent/skills/terminal-preflight/SKILL.md`).

```bash
python3 "$HOME/.claude/skills/context-1m/scripts/toggle_1m.py" <on|off|status> > "${TMPDIR:-/tmp}/context-1m.txt" 2>&1; code=$?; cat "${TMPDIR:-/tmp}/context-1m.txt"; exit $code
```

In Git Bash on Windows, use `python` where `python3` is absent.

```powershell
python "$HOME/.claude/skills/context-1m/scripts/toggle_1m.py" <on|off|status> *> "$env:TEMP/context-1m.txt"; $code=$LASTEXITCODE; Get-Content "$env:TEMP/context-1m.txt"; exit $code
```

Then report the printed line to the user verbatim.

Exit codes: `0` done, `2` the settings file is unreadable, is not JSON, or has an `env` value
that is not an object (the file is left unchanged). argparse exits `2` on a bad argument too.

## Facts to tell the user when relevant

- New sessions read the setting at start. Running sessions have been observed to pick it up
  live as well (observed 2026-10-07: three open sessions compacted within two minutes of a
  toggle). So switching `off` while sessions are above 200K forces an immediate compaction in
  each of them. Say so after every `on`/`off`.
- Before each change, the script copies the file to `settings.json.1m-backup` beside it. It
  rewrites the file with two-space indent (Claude Code's own format) and leaves every other key
  untouched.
- A per-session alternative that needs no file edit: `/autocompact <n>` (or
  `claude --autocompact <n>`) caps the window for that session only. A model that offers 1M only
  as an opt-in variant is switched with `/model` and the `[1m]` suffix, not with this setting.
- `CLAUDE_CODE_DISABLE_1M_CONTEXT` set in the shell environment overrides the settings file.
- A larger window costs more per turn once the context is past 200K. Turning it `on` does not
  change the plan's limits.
- Source: code.claude.com/docs/en/model-config §1M context and §Extended context environment
  variables.

## Do not

- Edit the file by hand or with `sed`. The script preserves the JSON, and other keys in the
  user's `env` block (for example `DISABLE_PROMPT_CACHING`) must survive.
- Touch a project `.claude/settings.json` or `settings.local.json` unless the user names it
  (`--settings <path>`).
- Toggle it from a scheduled or headless run. It changes every session on the machine,
  including sessions other people or lanes are running, so only the human asks for it.
