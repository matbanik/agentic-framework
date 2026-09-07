# Claude Code agent definitions

These files register Agent/Task subagents for in-harness delegation
(see `.agent/skills/subagent-delegation/SKILL.md`).

## After `instantiate.py`

1. Rename the files so the stem matches the instantiated `name:` frontmatter:
   - `{{PROJECT_NAME}}-builder.md` → `<your-slug>-builder.md`
   - `{{PROJECT_NAME}}-verifier.md` → `<your-slug>-verifier.md`
2. Confirm the Claude Code Agent/Task tool can address those names before flipping
   `fresh_worker` away from `none` in `harness-profiles.md`.
3. Keep the verifier `tools` allowlist free of `Write`/`Edit`. Pin `model:` by
   running `resolve_model.py sync` against the live registry home
   (`.agent/INSTANTIATE.md`); do not hardcode a snapshot in this package.

Directory presence alone does **not** authorize delegation. Cursor may also read
`.claude/agents/`; when both trees exist, `.cursor/` wins name conflicts on Cursor.
