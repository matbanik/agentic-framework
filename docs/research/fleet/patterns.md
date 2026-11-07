# Fleet MVP: patterns

Read as reference, not adopted (outline D-1).

## Reference implementations

| Project | Read | Take | Leave |
|---|---|---|---|
| [Dobby](https://pypi.org/pypi/dobby-orchestrator/json) 0.2.0, MIT | README and dependency list, PyPI JSON | Hub on SQLite in WAL mode. Spokes register, heartbeat and poll. Results held on the hub | Eight runtime dependencies (aiohttp, Slack, MCP and others), dashboard, priority queue, scheduling. No stated Windows support |
| [agichan](https://github.com/slonana-labs/agichan) | README | One authority pinned at worker start. Workers read JSON, not printed text. One-time join code. Polling overhead of about 10 s at `--poll 5`. Workspace-level agent flags. The agent's `STATUS:` last line (for P4) | Relay and escrow. Linux x86-64 only |
| [GitHub self-hosted runners](https://docs.github.com/en/actions/reference/runners/self-hosted-runners) | Docs | Outbound polling only. No inbound ports. Resumes after a network drop | Everything else |

## Standards

- [A2A](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability): task state
  names and the Task, Message and Artifact split. Adopted as vocabulary only.
- [git-bundle](https://git-scm.com/docs/git-bundle): moves objects with no server on the far side.
- [git-commit-tree](https://git-scm.com/docs/git-commit-tree): makes a commit object from a tree
  without moving any ref or touching the index, which is what the snapshot needs.

## Standard-library cautions

- [`http.server`](https://docs.python.org/3/library/http.server.html) "is not recommended for
  production. It only implements basic security checks." The hub compensates with TLS, per-member
  keys, a LAN-scoped firewall rule, a body-size limit and a per-connection timeout. It is still only
  fit for a trusted LAN of a few machines, and exposing it to the internet is out of scope.
- [`ssl`](https://docs.python.org/3/library/ssl.html): `SSLContext.wrap_socket` performs the
  handshake on connect by default. On a listening socket that would run it in the accept loop, so
  one stalled client could block every other one. The hub uses `do_handshake_on_connect=False`, so
  the handshake runs in the handler thread.
- `SSLSocket.getpeercert(binary_form=True)` returns the DER certificate. Its SHA-256 is the pin,
  checked before any request is written.
