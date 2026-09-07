# Cursor `Task` subagent definitions

These files register assistant-addressable `Task` subtypes for in-harness delegation
(see `.agent/skills/subagent-delegation/SKILL.md`).

## After `instantiate.py`

1. Rename the files so the stem matches the instantiated `name:` frontmatter:
   - `{{PROJECT_NAME}}-builder.md` → `<your-slug>-builder.md`
   - `{{PROJECT_NAME}}-verifier.md` → `<your-slug>-verifier.md`
2. Confirm the session's `Task` tool lists those subtypes before flipping
   `fresh_worker` away from `none` in `harness-profiles.md`.
3. Pin `model:` by running `resolve_model.py sync` against the live registry home
   (`.agent/INSTANTIATE.md`); do not hardcode a snapshot in this package.

Directory presence alone does **not** authorize delegation.
