# Release review still required

The implementation is available in the working tree. This file is a local review checklist, not an approval verdict or an external-provider dispatch prompt.

Before publication, an independent reviewer should inspect the implementation handoff, rule-preservation ledger and diff against `59a42fb37a4f66ab0ecef3613a91bfb640c5c571`, keeping the two pre-existing user changes separate. Check AC-1 through AC-5, especially shared blocked-evidence parsing, manual review observations, preservation of egress/human/ledger gates, and legacy artifact migration.

The pre-existing `planted-pin` in `core/AGENTS.md` is intentionally unchanged and still fails the model-slug release gate. Its owner must decide its disposition; it was not removed or allowlisted to obtain a green result.

Run the actual native Linux/macOS adopter probes and instruction-loader/import checks before claiming those platforms certified. Current execution covers Windows, PowerShell, Git Bash and disposable Windows/POSIX-shaped substitution; wrapper path snippets run without a provider. Live provider dispatch, full sandbox behavior and native macOS/Linux execution have not been certified.

No optional M4 hook, scanner, citation baseline or snapshot/lease mechanism is installed. No Git commit, push or publication was performed. Independent release approval has not been claimed.
