# Fleet MVP: scope

Date: 2026-11-03. Workflow: `core/.agent/workflows/pre-build-research.md`, at MVP size (outline A-1).
Source of truth for scope and rulings: `docs/proposals/2026-11-03-fleet-mvp-outline.md`.

## What is being built

One standard-library Python file. <hub host> runs it as a hub. Each member runs it as a member in a
terminal at its own console, polls the hub, runs tasks and posts results. The MVP is outline phases
P1 to P3.

## Done when

- P1: `ping` returns a member's tool versions over TLS on localhost.
- P2: <member host> is set up from the bootstrap template and appears in <hub host>'s status with a capability
  report.
- P3: a <hub host> session runs av-kit's checks on its uncommitted tree on <member host> and gets back the exit
  code, the log and the tree id.

## Local facts that shape the design

| Fact | Evidence | Consequence |
|---|---|---|
| <hub host>: <hub address>, Wi-Fi, Private profile, default inbound Block | the local network notes | One named inbound rule on <hub host>. Members need none |
| New firewall rules need elevation; the agent shell is not elevated | the local network notes; `IsInRole(Administrator)` returned False | A human creates the rule |
| <member host>: <member address>, runs the log collector | the local network notes | Nothing on <member host> opens a port or touches its firewall |
| av-kit: 1547 tracked files, 11.31 MiB pack | `git count-objects -vH`, 2026-11-03 | A full bundle per run is cheap enough |
| av-kit rule: no branch or worktree on <hub host> | `P:/av-kit/AGENTS.md:102` | Snapshots use a temporary non-branch ref; slots are plain clones |
| av-kit has 2 branches, 2 worktrees and another live session's untracked work today | `git branch`, `git worktree list`, `git status`, 2026-11-03 | Tests compare before and after; they never assume none exist |
| No tracked av-kit file matches the secret-path patterns | `git ls-files` sweep, 2026-11-03 | The filter should not block the first live run |
| Port 8770 is free on <hub host> | `Get-NetTCPConnection -LocalPort 8770`, count 0 | Default port, configurable |
| `openssl` is present through Git for Windows | `C:/Program Files/Git/usr/bin/openssl.exe` | The hub can create its certificate; stdlib `ssl` cannot create X.509 certificates |
