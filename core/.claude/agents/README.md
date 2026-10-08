# Claude Code agent definitions

These files register Agent/Task subagents for in-harness delegation
(see `.agent/skills/subagent-delegation/SKILL.md`).

## After `instantiate.py`

1. `instantiate.py --root <project>` rewrites file *contents* and **renames** the files so the stem matches the instantiated `name:` frontmatter:
   - `{{PROJECT_NAME}}-builder.md` → `<your-slug>-builder.md`
   - `{{PROJECT_NAME}}-verifier.md` → `<your-slug>-verifier.md`
   - `{{PROJECT_NAME}}-scout.md` → `<your-slug>-scout.md`
   - `{{PROJECT_NAME}}-peer_reviewer.md` → `<your-slug>-peer_reviewer.md`
   A destination collision refuses before any rename. A second apply is idempotent.
2. Confirm the Claude Code Agent/Task tool can address those names before flipping
   `fresh_worker` away from `none` in `harness-profiles.md`.
3. Keep the verifier, scout and peer_reviewer `tools` allowlists free of
   `Write`/`Edit`. Each file pins `effort:`; pin `model:` by
   running `resolve_model.py sync` against the live registry home
   (`.agent/INSTANTIATE.md`); do not hardcode a snapshot in this package.

Directory presence alone does **not** authorize delegation. The peer_reviewer is
advisory: it never writes a verdict file and never stands in for
`independent_reviewer`.
