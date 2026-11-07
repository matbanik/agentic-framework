---
project: "2026-11-03-fleet-mvp"
date: "2026-11-03"
source: "docs/proposals/2026-11-03-fleet-mvp-outline.md"
meus: []
run_parameters: "absent — run parameters are disabled in this repo (run_parameters.py status: policy_missing); Step 0 resolved manual"
status: "complete"
template_version: "2.4"
---

# Implementation Plan: Fleet MVP

> **Project**: `2026-11-03-fleet-mvp`
> **Build Plan Section(s)**: none. This framework package has no `docs/BUILD_PLAN.md` hub. The scope source is outline §3, phases P1 to P3.
> **Status**: `in_progress`

---

## Goal

<hub host> should be able to hand work to another machine on the LAN and get the result back, with the
least machinery that does not need rebuilding later.

<hub host> runs a small hub: one Python file over a SQLite file. Each member runs the same file: in a
terminal at its console, or on <member host> as a named scheduled task started over WinRM (D-5). The member polls the hub, runs tasks and posts results. Members never
accept connections. Code moves as git bundles. Authority is enforced by the hub from the first
version: only the orchestrator can start work, and no message can ask for a commit or a push.

The MVP is outline phases P1 to P3, and it is done when a <hub host> session can run av-kit's checks on
its uncommitted tree on <member host> and get back the exit code, the log and the tree id.

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning_and_execution
  eligible_tools: []
  decision: not_applicable
  eligibility_basis: "graphify-out/graph.json is absent. Headroom 0.24.0 is installed, but the payloads here are source code and exact evidence, which are bypass classes in core/.agent/docs/context-tool-decision-gate.md."
  human_message_reference: null
```

## Handoff Set

`meus: []`, so there is one project handoff and one rolling review.

| Scope | Canonical path |
|---|---|
| Project handoff | `.agent/context/handoffs/2026-11-03-fleet-mvp-handoff.md` |
| Plan review | `.agent/context/handoffs/2026-11-03-fleet-mvp-plan-critical-review.md` |
| Rolling execution review | `.agent/context/handoffs/2026-11-03-fleet-mvp-implementation-critical-review.md` |

## Work Packages and Context Lifecycle

| ID | Work | depends_on | context_strategy | durable_outputs |
|---|---|---|---|---|
| WP-1 | Hub, store, pairing, member and `ping`, proved on localhost by tests | — | `shared` | `.agent/fleet/fleet.py`; `scripts/tests/test_fleet_hub.py` |
| WP-2 | Bootstrap template, firewall rule and <member host> as the first real member | WP-1 | `compact_continue` | `.agent/fleet/bootstrap.md`; `core/.agent/fleet.json.template`; `scripts/tests/test_fleet_bootstrap.py`; live receipts. After compaction, re-read `task.md` and these outputs |
| WP-3 | `run` tasks: manifest, snapshot, slot and results, then av-kit on <member host> | WP-2 | `compact_continue` | `scripts/tests/test_fleet_run.py`; live receipts. After compaction, re-read `task.md` and these outputs |

**Lane ownership: omitted.** This is a main-tree plan. The package repo is not instantiated: it has
no `.agent/credits/worktree.json`, so `executor_worktree.py` has no lane configuration here, and the
precedent plan `docs/execution/plans/2026-10-20-review-limits-parameters/` ran on the main tree.

---

## User Review Required

> [!IMPORTANT]
> **Run parameters:** `manual`. They are disabled in this repo (`policy_missing`). Execution starts
> only when the human says proceed after the plan is approved. The human said proceed on 2026-11-03 and authorized
> one commit: the plan files, on branch `fleet-mvp` (`PC`). No code is committed and nothing is pushed.
>
> **Review limits:** `repo` (no `review_limits` block). Plan loop 3 rounds, execution loop 6, from
> `core/.agent/review-limits.json`. The human then granted this plan loop 3 more rounds and 21,000,000 more
> tokens (6 rounds, 31,500,000 tokens), recorded with `review_ledger.py continue`.
>
> **The human ruled on D-4, what a `run` task is allowed to do: option A.** A `run`
> task is trusted project execution: the project's own code runs with the member user's files, login
> and network, as it would if you ran its tests by hand. The fleet can refuse `git`, agent CLIs and
> shells as a manifest's command, but it cannot stop that code from calling them or from using the
> network, and only a sandbox could. What the fleet promises is narrower than the rule's wording: no
> message can ask for a commit or a push, and the fleet never imports or lands anything a `run` task
> changes. Keeping GitHub out of reach rests on the member having no GitHub credentials, which is a
> setup fact the fleet does not enforce. The Decision Log has the options under D-4.
>
> **D-5 changes how the human rows run.** Every human step is a prepared script in
> `docs/execution/plans/2026-11-03-fleet-mvp/scripts/`. The human asks and the agent runs it. The one script that
> needs elevation opens its own elevated window through a UAC prompt, so the IDE stays as it is. <member host> is reached with `the local WinRM helper` over WinRM.
>
> **The human still does three things:**
> 1. Ask the agent to run `hub-firewall.ps1` and accept its UAC prompt (row 7). The agent's shell is
>    not elevated, and D-1 scoped the rule to the LAN.
> 2. Ask the agent to run each <member host> script (rows 8, 11 and 13).
> 3. Run `approve <member host> <code>` in a real terminal on <hub host> (row 8). `approve` requires a TTY
>    and the agent's shell has none. This check stays as it is.
>
> Execution stops at these rows and resumes when the human asks or reports them done.
>
> **One departure from the handoff rule is flagged.** The handoff says keys are created "by a human at
> each member's console". Under D-5, `pair` runs over WinRM at the human's request, so <member host>'s key is created
> by a script and not at the console. The key is still made on <member host>, is never printed, read or copied,
> and the human approval on <hub host> is unchanged. The human can reverse this by running `pair` at the console.
>
> **Two files land outside this repo, both untracked and left for the human to keep or delete:**
> `P:/av-kit/.agent/fleet.json` (AC-31) and the firewall records in `the local firewall records folder` (AC-20).
> Another session is active in av-kit. This plan adds one untracked file there and creates and
> deletes one temporary non-branch ref per run. It creates no branch or worktree.

---

## Proposed Changes

### Named definitions

Every set and limit used by more than one AC is defined here, once, as a module-level constant in
`.agent/fleet/fleet.py`. ACs refer to these names. A test imports the constant, so it never restates
the values.

| Name | Value |
|---|---|
| `ENVELOPE_VERSION` | `1` |
| `ENVELOPE_FIELDS` | `v, id, task_id, from, to, kind, created, body, refs, reply_to, requires_human, start_quote` |
| `TASK_STATES` | `submitted, working, input-required, completed, failed, canceled, rejected` (the A2A names, outline §2.3) |
| `TERMINAL_STATES` | `completed, failed, canceled, rejected` |
| `TRANSITIONS` | `submitted→working`, `working→completed`, `working→failed`, `working→rejected`. Every other pair is `bad_transition`. `input-required` and `canceled` are vocabulary only: nothing in the MVP produces them, and P4 and P5 open them by adding rows |
| `TASK_KINDS` | `ping, run, agent` |
| `SEND_POLICY` | `{orchestrator: {ping, run}, member: {}}`. `agent` joins at P4 (D-2). Members gain `run` at P6 (D-3) |
| `EXECUTORS` | `ping, run`. Must equal the union of the `SEND_POLICY` values |
| `RESERVED_NAMES` | `orchestrator, hub` |
| `NAME_RE` | `^[a-z0-9-]{1,32}$`, for member, project and command names |
| `OPEN_ROUTES` | `GET /bootstrap/fleet.py`, `GET /bootstrap/bootstrap.md`, `POST /v1/pair` |
| `ROUTES` | The closed route table in the Hub HTTP surface section below |
| `SECRET_VALUE_PATTERNS` | Regexes for `sk-ant-`, `ghp_`, `github_pat_`, `AKIA[0-9A-Z]{16}`, `-----BEGIN [A-Z ]*PRIVATE KEY` |
| `SECRET_PATH_PATTERNS` | Case-insensitive basename globs: `.env`, `.env.*`, `*.pem`, `*.key`, `*.pfx`, `*.p12`, `id_rsa*`, `id_ed25519*`, `*credentials*` |
| `SECRET_PATH_ALLOW` | `*.example`, `*.sample`, `*.template`, checked before `SECRET_PATH_PATTERNS` |
| `CAPABILITY_TOOLS` | `python, git, uv, node, npm, go, claude, codex, agent, agy` |
| `FORBIDDEN_COMMANDS` | `git, gh, claude, codex, agent, agy, cmd, powershell, pwsh, sh, bash`. Matched against each argv's first element: basename, no extension, case-insensitive |
| `FIREWALL_RULE` | Name `Fleet hub 8770`: inbound, allow, TCP 8770, remote `the-LAN-subnet`, Private profile. The Firewall checklist has the one command that creates it |
| `BOOTSTRAP_STOPS` | `install-agent-cli, run-pair, confirm-fingerprint, run-approve, firewall-rule`. Each appears in the template as `STOP FOR HUMAN: <id>` |
| `EXIT_CODES` | `0` completed or success, `1` task failed, `2` usage or refusal, `3` task rejected, `4` wait timed out, `5` member offline, `6` tools missing |
| Limits | `MAX_JSON_BYTES` 1 MiB, `MAX_BLOB_BYTES` 256 MiB, `MAX_PENDING` 8, `POLL_S` 5, `OFFLINE_AFTER_S` 30, `HANDLER_TIMEOUT_S` 30, `DEFAULT_PORT` 8770, `DEFAULT_RUN_TIMEOUT_S` 1800 |

**Refusal codes** are also defined once, in `REFUSALS`, as code → HTTP status:
- `400` `bad_json`, `unknown_field:<n>`, `missing_field:<n>`, `bad_field:<n>`, `bad_version`, `bad_name`
- `401` `unauthorized`, `not_approved`, `revoked`
- `403` `role_not_allowed`, `sender_not_allowed`, `from_mismatch`, `not_your_task`, `blob_not_yours`
- `404` `not_found`
- `409` `duplicate_id`, `name_taken`, `bad_transition`, `stale_session`
- `413` `too_large`
- `422` `unknown_kind`, `kind_not_enabled`, `secret_in_message`, `missing_blob`, `blob_hash_mismatch`, `bad_manifest:<reason>`, `unknown_member`
- `429` `pending_full`

CLI refusals exit `2`: `pin_mismatch`, `hub_unreachable`, `approve_requires_tty`, `bad_code`,
`no_manifest`, `bad_manifest:<reason>`, `no_head`, `snapshot_secret_risk:<path>`, `too_large`,
`openssl_missing`.

Task outcome reasons, in `body.reason` of the status message: `nonzero_exit`, `timeout`,
`member_restarted`, `unknown_command`, `no_manifest`, `bad_manifest:<reason>`, `project_mismatch`,
`tree_mismatch`, `bundle_bad`, `tool_missing:<n>`.

**Call chains.** Control ACs name one of these as their chain:

| Chain | Path |
|---|---|
| `C-HTTP` | `fleet.py hub` → `cmd_hub` → `HubHandler.do_GET/do_POST/do_PUT` → `dispatch` (the `ROUTES` lookup, authentication, role check) → the `route_*` function → `Store` |
| `C-CLI` | `fleet.py <verb>` → `main` → `cmd_<verb>` → `hub_request` (pin check, then the request) → `C-HTTP` |
| `C-MEMBER` | `fleet.py member` → `cmd_member` → `member_loop` → `execute_task` → `EXECUTORS[kind]` → `post_status` → `C-HTTP` |
| `C-LOCAL` | `fleet.py approve\|revoke` → `main` → `cmd_approve\|cmd_revoke` → `approve_member\|revoke_member` → `Store`. No HTTP route exists for these |

**Atomicity.** Every read-then-write in `Store` runs inside `Store.tx()`, which is one SQLite
`BEGIN IMMEDIATE` transaction on a per-request connection. That covers task submit, claim, status
post, pair, approve, revoke and project publish. Blob writes are made atomic by writing to a temporary
file, checking the hash, then `os.replace`.

### WP-1: Hub, store, pairing, member and `ping`

**What the file does.** One file with these verbs: `hub`, `approve`, `revoke`, `status`, `send`,
`wait`, `pair` and `member`. WP-2 adds `publish` and `check`. WP-3 adds `run`.

**State.** Everything lives under `FLEET_HOME`, which defaults to `~/.agent/fleet` on every machine.
`hub/` holds the certificate, its key, `orchestrator.key`, `hub.db`, `hub.json` (url, pin) and
`blobs/`. A member holds `member.json` (hub url, pin, name, key), mode-restricted where the OS
supports it. Nothing is written into the repo.

**Store.** One append-only table, `messages`, holds every envelope, including hub-written `member`
and `project` messages. Triggers abort any `UPDATE` or `DELETE` with `append_only`. A task's state is
its latest `status` message, or `submitted` if it has none. A member's approval state is its latest
`member` message. Two small tables are not audit history and are mutable by design:
`members(name, key_sha256, session, last_seen)` and `task_blobs(sha256, member)`.

**TLS and keys.** Always TLS, on localhost too, so there is one code path (A-10). The first `hub`
start creates a self-signed certificate with the `openssl` CLI (`shutil.which`, then the copy beside
git) and generates the orchestrator key. Binding defaults to `127.0.0.1`; the LAN takes an explicit
`--host`. Clients skip CA and hostname checks and compare the SHA-256 of the server's DER certificate
with the pin before writing any request. Every request sends `Authorization: Bearer <key>`. The hub
stores only `sha256(key)` and compares with `hmac.compare_digest`.

**Pairing.** On the member, `pair --hub URL --pin FP --name N` generates the key with
`secrets.token_urlsafe(32)`, writes it to `member.json` without printing it, posts it over the pinned
connection, and prints an approval code: the first 12 hex digits of `sha256(key)`. On <hub host>, a human
runs `approve <name> <code>`. The code must match the stored hash. `approve` and `revoke` require a
TTY on stdin and write to the database directly, so no HTTP route can approve anything. The TTY check
stops an agent running the command by accident. It is not a security boundary against a hostile
process running as the human on <hub host>, which is outside this threat model.

**Member loop.** One task at a time, on one thread. `hello` reports capabilities, gets a new session
id and fails any `working` task of this member with `member_restarted`. A new hello invalidates the
older session, whose next call gets `stale_session`, and that process exits. While idle, the member
polls `GET /v1/tasks/next` every `POLL_S`. If the member already has a `working` task, `next` returns
that task again, because a poll from an idle member means the claim response was lost. Otherwise it
claims the oldest `submitted` task. While a task runs, the member sends `POST /v1/heartbeat`. Network
errors are retried until the hub answers, so a result survives a Wi-Fi drop. A retried status post
carries the same message id and gets `already_recorded`.

Limitation, stated: if a member's terminal is closed while a task runs, the task's process can outlive
it on Windows. The restarted member reports `member_restarted` and does not look for that process. A
human closing a terminal mid-run should check for it before starting the next run.

**Hub HTTP surface (`ROUTES`).**

| Route | Who | Purpose |
|---|---|---|
| `GET /bootstrap/fleet.py`, `GET /bootstrap/bootstrap.md` | open | Non-secret files from a fixed dictionary, never a path join |
| `POST /v1/pair` | open | Register a pending member |
| `POST /v1/hello`, `POST /v1/heartbeat`, `GET /v1/tasks/next` | member | Presence and claim |
| `POST /v1/tasks/<id>/status` | member | Status and result, own tasks only |
| `POST /v1/tasks` | any key, then `SEND_POLICY` | Submit a task. A member reaches `SEND_POLICY` and gets `sender_not_allowed` |
| `GET /v1/tasks/<id>`, `GET /v1/members` | orchestrator | Status |
| `PUT /v1/projects/<name>` | orchestrator | Publish a manifest (WP-2) |
| `GET /v1/projects/<name>` | orchestrator, member | Read a manifest (WP-2) |
| `PUT /v1/blobs/<sha256>` | orchestrator, member | Upload (WP-3) |
| `GET /v1/blobs/<sha256>` | orchestrator; member only for blobs tied to its tasks | Download (WP-3) |

**`wait` output.** `status` and `wait` print JSON. `wait` writes the log to `--log PATH` when given,
and its last line is one JSON object with `task, state, reason, exit_code, tree, log, duration_s`.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `POST /v1/tasks`, `POST /v1/tasks/<id>/status` | `validate_envelope` | `ENVELOPE_FIELDS` all present; `v` equals `ENVELOPE_VERSION`; `id` and `task_id` are 32 hex; `from` equals the authenticated identity; `to` matches `NAME_RE`; `kind` from `TASK_KINDS` or `status`; `body` and `refs` are objects; `requires_human` is a bool; `start_quote` is a string or null; total size at most `MAX_JSON_BYTES` | Refuse: `unknown_field:<n>` |
| `POST /v1/pair` | `validate_pair` | `name` matches `NAME_RE` and is not in `RESERVED_NAMES`; `key_sha256` is 64 hex | Refuse: `unknown_field:<n>` |
| `POST /v1/hello` | `validate_hello` | `capabilities` keys are a subset of `CAPABILITY_TOOLS`, values are strings or null | Refuse: `unknown_field:<n>` |
| `member.json`, `hub.json` | `load_config` | Written only by this file; a missing or malformed file exits `2` | Ignored fields refused the same way |
| CLI arguments | `argparse` in `main` | Names match `NAME_RE`; the pin is 64 hex | `argparse` rejects unknown flags |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-1 | unit | `validate_envelope` accepts a complete envelope and refuses an extra field, a missing field, a wrong version and a wrong type. Observable: the returned code. | Human-approved (outline §2.3) | `{..., "x": 1}` → `unknown_field:x`; `v: 2` → `bad_version`; each `ENVELOPE_FIELDS` name removed in turn → `missing_field:<n>` |
| AC-2 | unit | `next_state_allowed` is total over `TASK_STATES` × `TASK_STATES`: the test walks every pair, and only `TRANSITIONS` pairs pass. An unknown state string fails closed. | Human-approved (outline §2.3) | `completed→working` refused; every pair out of `TERMINAL_STATES` refused; `"bogus"→working` refused |
| AC-3 | integration | The store is append-only. Observable: the row count of `messages` and the SQLite error. Chain: `C-HTTP` to `Store`. A status change adds exactly one row and changes none. | Human-approved (outline §2.7) | Direct `UPDATE` and `DELETE` on the hub's real database raise `append_only`; row bytes for earlier messages are unchanged after a full task |
| AC-4 | unit | Source rules, by AST and text over `fleet.py`: every import is in `sys.stdlib_module_names`; it parses at `feature_version=(3, 11)`; it has no drive-letter path; it does not contain `CLAUDE_CODE_ENTRYPOINT`, `CLAUDECODE` or `cswap`; the default home derives from `Path.home()`. | Human-approved (outline §2.8, A-6, handoff billing rule) | A copy of the source with `import requests` or `"P:/x"` added fails the same checker, so the check can fail |
| AC-5 | integration | A wrong pin stops the client before it writes anything. Observable: exit code, and every application byte a test TLS server reads after the handshake, whether or not they form a complete request. Chain: `C-CLI` at `hub_request`. | Human-approved (D-1) | With a wrong pin, `status` and `pair` each exit `2` with `pin_mismatch` and the server reads zero bytes. Oracle check: a test client that writes a fake key header and then checks the pin makes the same server read nonzero bytes, so the assertion can fail |
| AC-6 | integration | Authentication on every non-open route. Observable: HTTP status, code, and database bytes. Chain: `C-HTTP` at `dispatch`. | Human-approved (D-1) | No key, wrong key → `401 unauthorized`; pending member → `401 not_approved`; revoked member → `401 revoked`, with its previously valid key; the raw member key appears nowhere in `hub.db` bytes |
| AC-7 | integration | Pairing needs a human approval that matches the member's key. Observable: the latest `member` message, exit code, and the stdout and stderr of `pair`. Chain: `C-LOCAL`, and `C-HTTP` for `/v1/pair`. | Human-approved (D-1, A-13) | `approve` with stdin not a TTY exits `2` with `approve_requires_tty` and adds no row. A wrong code gives `bad_code` and no row. `POST /v1/approve` → `404`. Reused pending or approved name → `409 name_taken`; a revoked name may pair again. `orchestrator` and `../x` → `bad_name`. Pending at `MAX_PENDING` → `429 pending_full`. The raw key is absent from `pair`'s output |
| AC-8 | integration | The hub enforces `SEND_POLICY` and the closed `TASK_KINDS`. Observable: HTTP code and `messages` row count. Chain: `C-HTTP` to `route_post_task`. | Human-approved (D-2, D-3, outline §2.6) | Member key posting each of `ping, run, agent` → `403 sender_not_allowed`. Orchestrator `agent` → `422 kind_not_enabled`. `commit`, `push`, `merge`, `tag`, `release` → `422 unknown_kind`. `from` differing from the key's identity → `403 from_mismatch`. A task to an unapproved or unknown member → `422 unknown_member`. Each adds zero rows. A test asserts `EXECUTORS` equals the union of the `SEND_POLICY` values |
| AC-9 | integration | Walking skeleton (outline P1). Real `hub` and `member` subprocesses over TLS on localhost: `send local ping`, then `wait`, exits `0`, and its JSON carries the member's tool versions; `status` lists the member as online. Chain: `C-CLI`, `C-MEMBER`. | Human-approved (outline P1) | With the member stopped and the hub started with a short `--offline-after`, once that time has passed, `wait --timeout 5` exits `5` rather than `0` |
| AC-10 | integration | Claiming is atomic and a lost claim response is recoverable. Observable: count of `working` rows. Chain: `C-HTTP` to `route_next`, `Store.tx`. | Local Canon (A-6) | Eight concurrent `next` calls on one task yield one `working` row and the same task id each. A repeat `next` after a discarded response returns the same task and adds no row |
| AC-11 | integration | Status posts are owner-checked, transition-checked and idempotent. Observable: HTTP code and row count. Chain: `C-MEMBER` to `route_post_status`. | Human-approved (outline §2.7) | Member B posting on A's task → `403 not_your_task`. A second, different terminal status → `409 bad_transition`, no row. The same message id repeated → `200 already_recorded`, no row. A re-used id with different content → `409 duplicate_id` |
| AC-12 | integration | No secret value in a message. Observable: HTTP code and row count. Chain: `C-HTTP` to `validate_envelope` to `SECRET_VALUE_PATTERNS`. The tests build fake values by concatenation so the repo holds none. Limitation, stated: logs are stored as blobs and are not scanned. | Human-approved (outline §2.6) | Each pattern in `body`, `refs` and `start_quote` → `422 secret_in_message` with zero new rows and the value absent from `hub.db` bytes |
| AC-13 | integration | Offline delivery and restarts. A task sent while the member is off reaches it when it starts. Restarting the hub keeps the certificate fingerprint and all tasks. A member running a task while the hub restarts still lands its result. Chain: `C-MEMBER`, `C-HTTP`. | Research-backed (outline §2.2; GitHub runners) | `wait --timeout 1` on a task with an online but busy member exits `4`, not `0`. With the hub down, `status` exits `2` with `hub_unreachable` |
| AC-14 | integration | Member restart and stale sessions. Chain: `C-MEMBER` to `route_hello`. Observable: latest status message and exit code. | Local Canon (A-7) | Killing the member mid-task and starting it again gives `failed` with `member_restarted`. A second member process under one key makes the first process's next call return `409 stale_session`, and that process exits `2` |
| AC-15 | integration | Resource limits (`http.server` caution in `docs/research/fleet/patterns.md`). Chain: `C-HTTP`. | Research-backed | A raw TCP client that never does the TLS handshake does not stop a concurrent `ping` from finishing. A JSON body over `MAX_JSON_BYTES` → `413 too_large`, zero rows |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Envelope shape and state names | Human-approved | Outline §2.3 |
| Who may send what | Human-approved | D-2, D-3 → `SEND_POLICY` |
| TLS pin and per-member key | Human-approved | D-1 |
| How the key is created and approved | Local Canon | A-13: refines "typing the key" so no human handles a secret |
| TLS on localhost | Local Canon | A-10: one code path |
| Claim, redelivery and session rules | Local Canon | Consequence of A-6 and A-7: one member, short polling, foreground |
| Stdlib server hardening | Research-backed | `docs/research/fleet/patterns.md` |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/fleet.py` | new | The single-file hub, member and CLI |
| `scripts/tests/fleet_harness.py` | new | Starts a hub and members as subprocesses with a temporary `FLEET_HOME`; approves by calling `approve_member` directly, since the CLI needs a TTY |
| `scripts/tests/test_fleet_hub.py` | new | AC-1 to AC-15, each test named `test_acNN_*` |

### WP-2: Bootstrap template and <member host>

**Template.** `.agent/fleet/bootstrap.md` is agent-readable markdown, not an installer. It has a
common part (Windows filled; Linux and macOS as headings only) and a project part. The setup agent
gets one input: the pairing line printed by `hub`, with the hub URL, pin, and the SHA-256 of
`fleet.py` and of the template.

The steps, in order:
1. **`STOP FOR HUMAN: install-agent-cli`.** Install one agent CLI and sign in.
2. The agent fetches both files with `curl.exe -k`, and checks each hash against the pairing line.
   `-k` is safe here because the hash does the verifying and the files hold no secret.
3. The agent installs Python 3.11 or later and git if missing, and writes a report of what it did.
4. **`STOP FOR HUMAN: confirm-fingerprint`.** Compare the pin on both screens.
5. **`STOP FOR HUMAN: firewall-rule`.** On <hub host>, only if the rule is absent.
6. **`STOP FOR HUMAN: run-pair`.** Run `pair` in the human's own terminal. The agent never reads
   `member.json`.
7. **`STOP FOR HUMAN: run-approve`.** On <hub host>.
8. The agent runs `fleet.py check`. For a project, `check --project P` reads the published manifest
   and lists missing tools, and the agent installs them.
9. **Handshake.** A human starts `fleet.py member`; <hub host> sends `ping`; the agent's final report
   lists what it installed, versions, and what still needs a human.

It also has an update section (stop the member, re-fetch, re-check the hash, restart) that WP-3 uses.

**On <member host> (D-5)** the template is followed by <hub host>'s agent over WinRM, through the prepared scripts,
and no agent CLI is installed on <member host>, because the MVP has no `agent` tasks: `install-agent-cli` waits
for P4. The human's request to run a script is the stop for `firewall-rule` and `run-pair`, and `pair` itself
enforces the pin, which covers `confirm-fingerprint`. `run-approve` stays with the human in a real terminal.
The template itself keeps all five stops for a member set up at its console.

**`publish` and `check`.** `publish --repo PATH` stores `<repo>/.agent/fleet.json` in the hub.
`check [--project P]` prints the capability report and, given a project, the `requires` tools that
are missing, exiting `6` if any are.

#### Firewall checklist

`the local network notes (lines 145-149)` is the practice here. This plan does not touch the router, so no router
dump is needed. Reading firewall state needs no elevation, so the agent takes both records. Creating
the rule does, so it is a prepared script (D-5): the human asks, the agent runs `docs/execution/plans/2026-11-03-fleet-mvp/scripts/elevate-firewall.ps1`, the human accepts
the UAC prompt, and `docs/execution/plans/2026-11-03-fleet-mvp/scripts/hub-firewall.ps1` runs in that elevated window. Its one command is:

```powershell
New-NetFirewallRule -DisplayName 'Fleet hub 8770' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8770 -RemoteAddress the-LAN-subnet -Profile Private
```

To reverse it: `scripts/hub-firewall.ps1 -Remove`.

Each record holds `Get-NetFirewallProfile`; the rule with its address and port filters; and the state
of the Plex inbound rule and `FPS-SMB-In-TCP`. `check_live.py firewall-before` writes
`the local firewall record fleet-hub-rule-before`. `check_live.py firewall` writes
`the local firewall record fleet-hub-rule-after` and compares the two.

The agent then starts the hub in a background shell:
`python .agent/fleet/fleet.py hub --host the-hub-LAN-address`. It ends with that shell, so the human can also run it
in a separate terminal. If Windows offers its own firewall prompt for Python, cancel it, since the
rule already exists.

#### <member host> scripts (D-5)

Each runs on <member host> through `docs/execution/plans/2026-11-03-fleet-mvp/scripts/run_member.py`, which calls `the local WinRM helper` with
its default login, so no password appears in a script, an argument or a receipt. `pywinrm` is not in
<hub host>'s Python, so the call is `uv run --no-project --with pywinrm`, which installs nothing globally.
The WinRM user is `<member host>\<member user>`, whose profile is `C:\Users\<member user>`, so `pair` and `member` share one
`FLEET_HOME`. <member host>'s console user is a different account and its session is not touched.

| Script | Row | Does |
|---|---|---|
| `member-record.ps1` | 8 | Prints log-collector state, firewall profile state and inbound rule count. Runs before and after |
| `member-python.ps1` | 8 | If Python 3.11 or later is absent, installs it for this user from python.org with no elevation. `winget` is absent on <member host> |
| `member-pair.ps1` | 8 | Fetches both files, checks the hashes, runs `pair`, and prints only the approval code |
| `member-task.ps1` | 8, 11, 13 | Creates, starts, restarts, stops or removes the scheduled task `Fleet member`. The task has no trigger, so nothing starts at boot (A-7 stands) and it outlives the WinRM shell that starts it. `ACTION=Remove` reverses it. `run_member.py` passes values as `KEY=VALUE`, because the remote runner takes a file and no parameters |
| `member-update.ps1` | 11 | Re-fetches `fleet.py` and checks the hash |
| `member-tools.ps1` | 13 | Installs what `check --project av-kit` reports missing, for this user |

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `PUT /v1/projects/<name>` | `validate_manifest` | See AC-22 | Refuse: `bad_manifest:unknown_key:<n>` |
| `GET /bootstrap/*` | Fixed dictionary in `route_bootstrap` | Exactly two names; anything else `404` | n/a: no input body |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-16 | integration | Only `OPEN_ROUTES` work with no key. Observable: HTTP status for every `ROUTES` row. Chain: `C-HTTP` at `dispatch`. The test walks the `ROUTES` constant, so a new route cannot skip it. | Human-approved (D-1) | Every route not in `OPEN_ROUTES`, called with no key → `401`. A member calling an orchestrator-only route → `403 role_not_allowed` |
| AC-17 | integration | Bootstrap files match the pairing line. Observable: the SHA-256 of the bytes served and the hashes printed by `hub`. Chain: `C-HTTP` to `route_bootstrap`. | Local Canon (A-16) | `/bootstrap/../hub/hub.key`, `/bootstrap/hub.db` and `/bootstrap/orchestrator.key` → `404`, and no response contains the key file's bytes |
| AC-18 | integration | `publish` then `check --project` reports missing tools. Observable: exit code and JSON. Chain: `C-CLI` to `route_put_project`, `route_get_project`. Publishing is a new `project` message; the latest wins. | Human-approved (outline P2) | A manifest requiring a tool absent from the report → exit `6` naming it. An unknown project → `404`. An invalid manifest → `422 bad_manifest:<reason>` with no new row |
| AC-19 | unit | Template shape. Observable: the parsed file. Every `BOOTSTRAP_STOPS` id appears as `STOP FOR HUMAN: <id>`. The headings Windows, Linux and macOS exist, and the last two have no steps. `pair` and `approve` appear only after their stop lines. The file has no `P:` path. It has the sentence forbidding the agent from reading `member.json`. | Human-approved (outline P2) | A copy with one stop line removed fails the same checker |
| AC-20 | integration | Live, on <hub host>: `FIREWALL_RULE` exists, created by `hub-firewall.ps1` when the human asks (D-5). Observable: the before record (rule absent) and the after record that the checklist names. | Human-approved (D-1, `the local network notes (lines 145-149)`) | `check_live.py firewall` fails if the rule differs from `FIREWALL_RULE`, including remote address `Any` or a profile that includes Public; if more than one rule has that name; if the profile state differs from the before record; or if the Plex inbound rule or `FPS-SMB-In-TCP` is no longer enabled |
| AC-21 | integration | Live: <member host> (outline P2 done). <hub host>'s agent follows the template over WinRM with the D-5 scripts when the human asks, the human runs `approve`, and <hub host>'s `status` lists `<member host>` as approved and online with its capability report, and `send <member host> ping` then `wait` exits `0`. Observable: the JSON receipts, checked by `check_live.py member`. | Human-approved (outline P2) | From <member host>, `curl.exe -k https://the-hub-LAN-address:8770/v1/members` returns `401`. <member host>'s log-collector service state, firewall profile state and inbound rule count are equal before and after, from `member-record.ps1`, and the template opened no port |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Template form and human stops | Human-approved | Outline §3 "What each MVP phase should not grow into" |
| Fetching before trust exists | Local Canon | A-16: `curl -k` plus a hash from the pairing line |
| Firewall rule scope | Human-approved | D-1, `the local network notes (lines 145-149)` |
| Human steps as scripts, <member host> over WinRM | Human-approved | D-5 |
| Project part of the template | Local Canon | Handoff §5.1: manifest per project; A-5 and A-9 |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/fleet.py` | modify | `publish`, `check`, `route_bootstrap`, the pairing line |
| `.agent/fleet/bootstrap.md` | new | The template |
| `core/.agent/fleet.json.template` | new | The manifest template a project copies. AC-22's first test reads it, so it is written here |
| `scripts/tests/test_fleet_bootstrap.py` | new | AC-16 to AC-19 |
| `docs/execution/plans/2026-11-03-fleet-mvp/check_live.py` | new | Plan-local verifier for AC-20, AC-21 and AC-31. It reads, and writes only under `$env:RECEIPTS_DIR`, apart from the two firewall records the Firewall checklist names |
| `docs/execution/plans/2026-11-03-fleet-mvp/scripts/` | new | D-5: `hub-firewall.ps1`, `elevate-firewall.ps1`, `run_member.py` and the <member host> scripts. Plan-local |
| `the local firewall record fleet-hub-rule-before`, `the local firewall record fleet-hub-rule-after` | new, outside this repo | The firewall records |

### WP-3: `run` tasks

**Manifest.** `<repo>/.agent/fleet.json`, JSON because the file is stdlib-only (A-9):
`{"v": 1, "project": "<name>", "requires": ["<tool>"], "commands": {"<name>": [["argv", ...], ...]}}`.
A command is a list of argv lists that run in order and stop at the first failure. `run` names a
command, and no free argv crosses the wire (A-12), which also avoids shell quoting across operating
systems.

**Snapshot on <hub host>.** `run <member> --repo PATH <command> [--timeout N]`:
1. Copy the repo's index to a temporary file, and point `GIT_INDEX_FILE` at it.
2. `git add -A`, then `git add -f -- .agent/fleet.json`, because the slot reads the manifest from the
   snapshot even when the repo ignores it. No other ignored file travels. Then `git write-tree`, and
   refuse on any `SECRET_PATH_PATTERNS` match in the tree.
3. `git commit-tree -p HEAD` with a fixed `fleet` identity, unsigned.
4. Create `refs/fleet/snap/<task>`, run `git bundle create`, and delete the ref in `finally`.
5. Upload the bundle, then post the task with `refs: {commit, tree, bundle}`.

The real index, `HEAD`, working tree and branches are untouched. The only trace is dangling objects
that `git gc` collects. The bundle is full each time, which is cheap at av-kit's size (A-17).

**Slot on the member.** `FLEET_HOME/slots/<project>`, made with `git init`, never a clone, so there
is never a remote. Then:
1. Download the bundle, and check its hash.
2. `git fetch <bundle> refs/fleet/snap/<task>:refs/fleet/task/<task>`, `git checkout --force --detach`,
   `git clean -fd`. Ignored dependencies stay, so `setup` is not repeated each time.
3. Check that `HEAD^{tree}` equals `refs.tree`.
4. Read the slot's manifest, then check the project and the command name.
5. Resolve each argv's first element with `shutil.which`.
6. Run with no shell and the member's environment unchanged, merging stdout and stderr into a log
   file. A heartbeat thread runs from download to log upload, so a long checkout counts as online too.

A timeout kills the tree with `taskkill /T /F`. Linux and macOS members wait for P7, so the MVP has no
POSIX branch to leave untested. The log is uploaded, keeping the tail if it exceeds `MAX_BLOB_BYTES`. The
result carries `exit_code`, `log`, `tree` and `duration_s`.

**What `run` is allowed to do (D-4).** A `run` task is trusted project execution. The project's own
code runs with the member user's files, login and network access, as it would if run by hand. The
fleet does not sandbox it. The fleet does three things:

1. **It refuses a manifest that names a forbidden tool.** `validate_manifest` refuses
   `FORBIDDEN_COMMANDS` as any argv's first element, on `publish`, on `run` and again on the member
   before anything runs.
2. **It brings back only the result.** A `run` result is `exit_code`, `log`, `tree` and `duration_s`,
   and the fleet imports and lands nothing from it. A commit made in a slot stays there, and the next
   checkout drops it. Result bundles and landing come at P4, with their own gate.
3. **It gives a slot no remote.** The bootstrap also puts no GitHub credential or signing key on the
   member. That part is a setup rule the fleet does not check.

Limitation, stated: the first-argument check catches a manifest that names a forbidden tool. It is not
a security boundary. `uv run git` or a project's test can still call `git` or a signed-in agent CLI.
Such code can change anything the member user can write and reach anything that login or the network
allows, and the fleet neither prevents nor detects it. Only projects trusted on that machine belong in
a `run` task. Stopping this needs a sandbox, which is not in the MVP. D-2 still governs `agent` tasks:
no `agent` task exists in the MVP, and the check does not claim to replace that kind's own gate at P4.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| Manifest (`publish`, `run`, slot read) | `validate_manifest` | `v` is 1; `project` and command names match `NAME_RE`; `requires` is a subset of `CAPABILITY_TOOLS`; `commands` is non-empty, each a non-empty list of non-empty argv lists of strings; no argv's first element is in `FORBIDDEN_COMMANDS` | Refuse: `bad_manifest:unknown_key:<n>` |
| `run` task `body`, `refs` | `validate_run_task` | `body` is `{project, command, timeout_s}`; `timeout_s` is an integer from 1 to 86400; `refs` is `{commit, tree, bundle}`, 40 hex, 40 hex, 64 hex; `bundle` exists on the hub | Refuse: `unknown_field:<n>`, `bad_field:<n>`, `missing_blob` |
| `PUT /v1/blobs/<sha256>` | `route_put_blob` | Path is 64 hex; size at most `MAX_BLOB_BYTES`; content hash equals the path | Body is opaque bytes |
| Bundle on the member | `git bundle verify`, then the hash | The hash equals `refs.bundle`, and the tree equals `refs.tree` | n/a |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-22 | unit | `validate_manifest` accepts `core/.agent/fleet.json.template` once its placeholders are filled, and refuses bad shapes. Observable: the returned code. | Local Canon (A-9, A-12) | Extra key, `v: 2`, `project: "../x"`, empty `commands`, a string where argv belongs, and a `requires` tool outside `CAPABILITY_TOOLS` are each refused with `bad_manifest:<reason>`. Each `FORBIDDEN_COMMANDS` name is refused with `bad_manifest:forbidden_command:<n>`, also when written as `GIT.EXE` or `C:/x/git` |
| AC-23 | integration | The snapshot takes the working tree and leaves the repo alone. Observable: the tree inside the bundle; a path and SHA-256 listing of every file in the fixture outside `.git`, including ignored files; and `HEAD`, index file bytes, `git status --porcelain`, `git branch --list`, `git worktree list` and `git for-each-ref refs/fleet`. Chain: `C-CLI` to `cmd_run` to `make_snapshot`. | Research-backed (A-3; 2026-11-01 §5) | Fixture repo with staged, unstaged, untracked and ignored changes: the bundle has the first three and not the ignored file. A manifest the repo ignores still travels (D-8), and no other ignored file does. Every before-and-after observable is equal. Oracle check: overwriting an untracked file's content between the two listings leaves porcelain equal and makes the comparison fail, so it can catch a snapshot that clobbers a file. With `git bundle` forced to fail through a `PATH` shim, `refs/fleet` is still empty. A repo with no `HEAD` → `no_head` |
| AC-24 | integration | A likely secret file stops the run before anything leaves <hub host>. Observable: exit code, and the hub's blob count and row count. Chain: `C-CLI` to `make_snapshot`. | Human-approved (handoff "no secrets") | Each untracked `.env.local`, `deploy.pem`, `aws_credentials.txt` → exit `2` with `snapshot_secret_risk:<path>`, zero new blobs, zero new rows. `.env.example` is allowed by `SECRET_PATH_ALLOW` |
| AC-25 | integration | End to end on a fixture repo with a real hub and member (outline P3). Observable: `wait`'s JSON and the log. Chain: `C-CLI`, `C-MEMBER`. A command prints a marker read from an untracked file: state `completed`, exit code `0`, the log contains the marker, and `tree` equals the snapshot's tree. | Human-approved (outline P3) | A command exiting `3` → state `failed`, reason `nonzero_exit`, result `exit_code` `3`, and `wait` exits `1`. Execution stops at the first failing argv: a sentinel written by the next argv is absent |
| AC-26 | integration | A refused task runs nothing. Observable: state, reason and a sentinel file on the member. Chain: `C-MEMBER` to `execute_run`. | Local Canon (A-12) | An unknown command → `rejected`, `unknown_command`. A snapshot with no manifest → `no_manifest`. A wrong `refs.tree` → `tree_mismatch`. A corrupt bundle → `bundle_bad`. `project` differing from the slot's manifest → `project_mismatch`. A command whose tool is absent → `tool_missing:<n>`. A manifest naming a `FORBIDDEN_COMMANDS` tool, in a task the harness posts directly so `run`'s own check is skipped → `bad_manifest:forbidden_command:<n>`, with a `PATH` shim for that tool recording no call. `wait` exits `3` for each. No sentinel appears in any case |
| AC-27 | integration | Blob integrity and access. Observable: HTTP code and files in `blobs/`. Chain: `C-HTTP` to `route_put_blob`, `route_get_blob`, `route_post_task`. | Local Canon (outline §2.5) | Content not matching the path hash → `422 blob_hash_mismatch`, no file. Over `MAX_BLOB_BYTES` → `413 too_large`, no file. A task naming an absent bundle → `422 missing_blob`, no row. Member B fetching a bundle tied only to A's task → `403 blob_not_yours`. Non-hex path → `404` |
| AC-28 | integration | Slot properties. Observable: `git` output in the slot. Chain: `C-MEMBER` to `prepare_slot`. After a run: `git remote` is empty, `HEAD` is detached, `git branch --list` shows only the detached `HEAD` line and `refs/heads` is empty, a stale untracked file is removed, and an ignored dependency folder stays. | Human-approved (outline §2.5; `P:/av-kit/AGENTS.md:102`; D-4) | A test script run by an allowed command makes a commit in the slot. After the run, the status message's `body` keys are exactly the result keys and hold no bundle; <hub host>'s `HEAD` and refs are unchanged; and the next run's `HEAD^{tree}` equals its own `refs.tree`, with that commit absent from its history |
| AC-29 | integration | Timeout and heartbeats. Observable: state, reason, a sentinel, and `last_seen`. Chain: `C-MEMBER` to `execute_run`. | Local Canon (A-7) | A command that starts a child which writes a sentinel after 8 s, run with `--timeout 2`: state `failed`, reason `timeout`, sentinel absent after 10 s, so the child died too. During a run longer than `OFFLINE_AFTER_S` as set for the test, `status` still shows the member online |
| AC-30 | integration | The environment reaches child processes unchanged. Observable: a value printed by a manifest command. Chain: `C-MEMBER` to `execute_run`. | Human-approved (handoff billing rule) | A sentinel variable set on the member, and `CLAUDECODE` set to a test value in that member's environment, both appear unchanged in the child's output |
| AC-31 | integration | Live: av-kit on <member host> (outline P3 done). Observable: `wait`'s JSON receipts, checked by `check_live.py av-kit`. The manifest `P:/av-kit/.agent/fleet.json` is uncommitted, so a run that uses it proves that uncommitted files moved. It is ignored through av-kit's `.git/info/exclude` since another session added that line, and it travels under D-8. After `publish`, `member-tools.ps1` runs `check --project av-kit` and installs what it reports missing, and `status` must then show every `requires` tool with a version. Then `setup`, `check-py`, `check-ui` and `check-mcp`, using the registered commands in `P:/av-kit/.agent/docs/commands.md`. Each returns state, `exit_code`, log and `tree`. A nonzero exit is reported, not fixed: this AC is about the fleet, not av-kit being green. | Human-approved (outline P3; A-8) | `check_live.py avkit-tools` fails if a `requires` tool has no version on `<member host>`. `check_live.py av-kit` fails if a result is `rejected`, or lacks `exit_code`, `log` or `tree`; if `tree` differs from the snapshot's; if `git -C P:/av-kit for-each-ref refs/fleet` is non-empty; or if av-kit's branch or worktree list differs from the before record taken in the same row |
| AC-32 | integration | Package fit. `core/MANIFEST.md` lists the new files. `check_package_gates.py` finds no new `refcheck` or `sanitize --verify` failure against the row-0 baseline, and finds a `test_acNN_*` function for every AC except the live AC-20, AC-21 and AC-31, and this one. The full pytest gate passes. | Local Canon (`scripts/refcheck.py`, `scripts/sanitize.py`) | The checker run against a baseline with one line removed exits nonzero, so a new failure cannot slip through |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Snapshot method | Research-backed | A-3; 2026-11-01 §5; `git-commit-tree` docs |
| Slot form | Human-approved | Outline §3 P3 note: plain, detached, not a worktree. A-18 refines "clone" to `git init` plus a bundle fetch |
| Manifest format, named commands, forbidden first arguments | Local Canon | A-9, A-12, D-4 |
| Secret file refusal | Human-approved | Handoff "no secrets"; the patterns are planner-chosen and live in one constant |
| Result contents | Human-approved | Outline P3: exit code, log, tree id |
| Env handling | Human-approved | Handoff billing rule |
| What a `run` task may do | Human-approved | D-4, option A |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/fleet.py` | modify | `run`, `make_snapshot`, `prepare_slot`, `execute_run`, blob routes, `validate_manifest` |
| `core/MANIFEST.md` | modify | List `.agent/fleet/fleet.py`, `.agent/fleet/bootstrap.md` and `core/.agent/fleet.json.template` |
| `scripts/tests/test_fleet_run.py` | new | AC-22 to AC-30 |
| `docs/execution/plans/2026-11-03-fleet-mvp/check_package_gates.py` | new | Plan-local check for AC-32. It writes only under `$env:RECEIPTS_DIR` |
| `P:/av-kit/.agent/fleet.json` | new, outside this repo, uncommitted and excluded (D-7) | The av-kit manifest. Not committed. No branch |

### Stop conditions

Execution stops, and reports to the human with evidence, on any of these:

1. The row-0 baseline pytest gate is red.
2. A human row is reached (rows 7, 8, 11 and 13). Mark it `[B]` with a human gate and tell the human which script to ask for. A script that changes a machine runs only when the human asks.
3. A step on <member host> would touch the log collector, turn a firewall profile off or open a port.
4. `snapshot_secret_risk` fires on av-kit. Report the path. Do not widen `SECRET_PATH_ALLOW` to get past it without the human's word.
5. `refs/fleet`, a branch or a worktree in av-kit is left changed by this tool.
6. Anything would need a commit that lands work or moves a branch, a push, a secret in a message, a change to `CLAUDE_CODE_ENTRYPOINT` or `CLAUDECODE`, or `cswap`. The snapshot's own `git commit-tree` object is not such a commit: it moves no branch and is dropped when its temporary ref is deleted.
7. A design point turns out not to work on Windows and the fix would add a dependency or a second file. That needs a Decision Brief, not a quiet change.
8. The review caps of the ledger are reached.

---

## Out of Scope

| Item | Kind | Deferred-to MEU | Basis |
|------|------|-----------------|-------|
| `agent` tasks and adapters (P4) | out-of-scope | — | Human-approved: outline §3, "The MVP is P1 to P3", accepted USER_EXPLICIT 2026-11-03. The kind is in `TASK_KINDS` and refused today |
| Cursor and Antigravity adapters, follow-ups, Zorivest manifest (P5) | out-of-scope | — | Human-approved: outline §3 and D-2 |
| Member-to-member requests (P6) | out-of-scope | — | Human-approved: outline §3 and D-3. The hub refuses every member task |
| Autostart, Linux and macOS members (P7) | out-of-scope | — | Human-approved: outline §3 |
| Discovery, session injection, MCP pull tool, NATS, capability matcher, credits billing | out-of-scope | — | Human-approved: outline §3, "Deliberately left out of the MVP" |
| Dashboard, long polling, server-sent events | out-of-scope | — | Human-approved: outline §3, "What each MVP phase should not grow into" |
| Blob retention and cleanup | out-of-scope | — | Human-approved: the human's 2026-11-03 simplicity rule. At 11 MiB per run the store grows slowly and can be deleted by hand; revisit when disk use shows a need |
| Fixing the existing `refcheck` and `sanitize` failures | out-of-scope | — | Human-approved: outline §3 scope does not include them. The human's 2026-11-03 message makes the proposals with stale references "reference material". They are outside P1 to P3, and row 0's baseline records them. The final report lists them for the human |
| Result bundles from `run` tasks and landing on <hub host> | out-of-scope | — | Human-approved: outline P3 returns exit code, log and tree; outline P4 adds result bundles and landing |
| Exposing the hub beyond the LAN | out-of-scope | — | Human-approved: D-1 scopes the rule to the LAN |

---

## BUILD_PLAN.md Audit

This project does not modify build-plan sections, because this package has no `docs/BUILD_PLAN.md`
hub. Task row 16 proves the file is absent:

```powershell
python -c "import pathlib,sys; sys.exit(0 if not pathlib.Path('docs/BUILD_PLAN.md').exists() else 1)" *> $env:RECEIPTS_DIR/build-plan-audit.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/build-plan-audit.txt; exit $code
```

---

## Verification Plan

`$env:RECEIPTS_DIR` is `C:/Temp/agentic-framework/receipts`, and `$env:AGENT_MODEL_REGISTRY_HOME` is
`P:/.agent`. Set both before every row. These commands capture exact evidence, so they use no output
filter.

### 1. Baseline, row 0

Records the identity and the existing gate state. `refcheck` and `sanitize --verify` are already red
(see Out of Scope), so the blocking baseline is the pytest gate, and the other two are saved for
comparison.

```powershell
python -m pytest core/tools/tests scripts/tests -q -rfE *> $env:RECEIPTS_DIR/fleet-full-pytest-baseline.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fleet-full-pytest-baseline.txt -Tail 25; exit $code
```

### 2. Targeted tests

```powershell
python -m pytest scripts/tests/test_fleet_hub.py scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_run.py -q -rfE *> $env:RECEIPTS_DIR/fleet-targeted.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fleet-targeted.txt -Tail 25; exit $code
```

### 3. Package gates, compared with the baseline

```powershell
python docs/execution/plans/2026-11-03-fleet-mvp/check_package_gates.py *> $env:RECEIPTS_DIR/fleet-package-gates.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fleet-package-gates.txt -Tail 30; exit $code
```

### 4. Live checks, after the human rows

```powershell
python docs/execution/plans/2026-11-03-fleet-mvp/check_live.py member *> $env:RECEIPTS_DIR/fleet-live-<member host>.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fleet-live-<member host>.txt -Tail 30; exit $code
```

```powershell
python docs/execution/plans/2026-11-03-fleet-mvp/check_live.py avkit-tools *> $env:RECEIPTS_DIR/fleet-live-avkit-tools.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fleet-live-avkit-tools.txt -Tail 30; exit $code
```

```powershell
python docs/execution/plans/2026-11-03-fleet-mvp/check_live.py av-kit *> $env:RECEIPTS_DIR/fleet-live-avkit.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fleet-live-avkit.txt -Tail 30; exit $code
```

### 5. Fresh full gate, H1-2

```powershell
python -m pytest core/tools/tests scripts/tests -q -rfE *> $env:RECEIPTS_DIR/fleet-full-pytest.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fleet-full-pytest.txt -Tail 25; exit $code
```

---

## Decision Log

D-1 to D-9 are ruled. A-1 to A-8 are carried from outline §5, where their sources and precedents
are. A-9 onward were decided while planning.

```yaml
decision_log:
  - id: D-1
    stage: planning
    question: "How do members and <hub host> talk?"
    resolution: human
    class: one-way-door
    chosen: "Minimal stdlib hub on <hub host> that members poll; TLS with a pinned self-signed certificate; one key per member; one named, reversible, LAN-scoped inbound rule on <hub host>"
    source_tag: Human-approved
    precedents: ["docs/proposals/2026-11-03-fleet-mvp-outline.md §5 D-1"]
    research: { engine: tavily, sources: ["outline §5 D-1 and §6"] }
    reasoning: "Smallest thing that meets the brief; see the outline for the options compared"
    human_message_reference: "USER_EXPLICIT 2026-11-03 'All 3 recommendations are accepted, proceed with create plan'"
  - id: D-2
    stage: planning
    question: "Who may start an agent job, with what permissions and billing?"
    resolution: human
    class: governance-value
    chosen: "Orchestrator only, with the human's words as start_quote; workspace-level permissions; the member's own login; Cursor and agy wait until P5. In this plan: the kind is refused with kind_not_enabled"
    source_tag: Human-approved
    precedents: ["docs/proposals/2026-11-03-fleet-mvp-outline.md §5 D-2"]
    research: { engine: tavily, sources: ["outline §5 D-2"] }
    reasoning: "See the outline"
    human_message_reference: "USER_EXPLICIT 2026-11-03 'All 3 recommendations are accepted, proceed with create plan'"
  - id: D-3
    stage: planning
    question: "What may one member ask another to do?"
    resolution: human
    class: governance-value
    chosen: "run tasks only, through the hub, at P6. Until then the hub refuses every task a member sends"
    source_tag: Human-approved
    precedents: ["docs/proposals/2026-11-03-fleet-mvp-outline.md §5 D-3"]
    research: { engine: tavily, sources: ["outline §5 D-3"] }
    reasoning: "See the outline"
    human_message_reference: "USER_EXPLICIT 2026-11-03 'All 3 recommendations are accepted, proceed with create plan'"
  - id: D-4
    stage: planning
    question: "A run task runs project code on a member. How strictly must it obey 'a message never authorizes a commit or push'?"
    resolution: human
    class: governance-value
    chosen: "A"
    options:
      A: "Treat a run as trusted project execution with the member user's files, login and network. Refuse git, agent CLIs and shells as a manifest's commands. The fleet imports and lands nothing from a run. It does not stop project code from using what that user can reach. No new machinery"
      B: "A, plus commands come only from a manifest the human publishes at a terminal, so an agent session cannot add one. One more human step per manifest change. Project code can still call the same tools, so it gains little"
      C: "Sandbox the member's runs. The only option that stops project code, but it needs a container or restricted user, which breaks the one-file, stdlib MVP"
    source_tag: Human-approved
    precedents: ["handoff §3 — a message never authorizes a commit, push, merge, tag, release", "docs/proposals/2026-11-03-fleet-mvp-outline.md §2.6", "plan review round 1, F-001"]
    research: { engine: none, sources: [] }
    reasoning: "The rule's aim is that work reaches the human's repos only from <hub host>, on the human's word. Under option A the fleet is never that route, and the member holds no GitHub credential. Running a project's tests means running its code, so no check on the message can bind what that code does. The review asked for a ruling because this is narrower than the rule's wording"
    human_message_reference: "USER_EXPLICIT 2026-11-03 'both decision recommendations are accepted'"
  - id: D-5
    stage: execution
    question: "How do the human rows run, and how is <member host> reached?"
    resolution: human
    class: two-way
    chosen: "Each human step is a prepared script that the agent runs when the human asks, and hub-firewall.ps1, the one that needs elevation, runs in its own elevated window through a UAC prompt. <member host> is reached over WinRM with the local WinRM helper. No agent CLI on <member host> until P4. pair runs over WinRM. approve stays with the human in a real terminal. The member runs as one named, triggerless scheduled task"
    source_tag: Human-approved
    precedents: ["the local network notes (lines 145-149) — named, reversible changes on <member host>", "plan A-7 — no autostart", "handoff §3 — keys created by a human at the console: pair over WinRM departs from this, flagged in User Review Required"]
    research: { engine: none, sources: ["C:/Temp/agentic-framework/receipts/<member host>-probe.txt — read-only WinRM probe of <member host>"] }
    reasoning: "The human replaced the console steps with scripts the agent runs on request. A process started in a WinRM shell dies with it, so the member needs one named task. A task with no trigger keeps A-7. The WinRM user and the console user differ, so pair and member both run as the WinRM user. A window reload does not elevate Cursor, and a real elevated relaunch would end every other Cursor session, so the human chose the UAC prompt"
    human_message_reference: "USER_EXPLICIT 2026-11-03 'check [the local ops folder] on how to access <member host> with winrm / rather than commands prepare script to be run in elevated prompt. I will elevat the IDE and ask you to run them for me.'; USER_EXPLICIT 2026-11-04 'yes use the UAC prompt for hub-firewall.ps1'"
  - id: D-6
    stage: execution
    question: "The row-0 baseline was red in two tests about the Linux install's copy of the lane tests, which this plan had not touched. Stop, or fix them first?"
    resolution: human
    class: two-way
    chosen: "Fix them first, then re-confirm with a full run. RUN_PARAMETERS_WINDOWS_ONLY in scripts/instantiate.py gains the 17 lane and run-parameter test files that import a fixture the non-Windows install removes, and the identity-create test moves from test_lane_route_instructions.py to the Windows-only test_credits_phases.py"
    source_tag: Human-approved
    precedents: ["plan stop condition 1"]
    research: { engine: none, sources: ["C:/Temp/agentic-framework/receipts/fleet-first-baseline/", "C:/Temp/agentic-framework/receipts/fleet-full-pytest-baseline.txt"] }
    reasoning: "The rerun ended 4044 passed, 1 skipped. The cost is stated: those lane and run-parameter tests no longer ship to non-Windows installs. These three files are outside the plan's list and stay uncommitted"
    human_message_reference: "USER_EXPLICIT 2026-11-03 answer 'Fix them first' to the red baseline question"
  - id: D-7
    stage: execution
    question: "Another av-kit session excluded P:/av-kit/.agent/fleet.json from its RC1 commit until the human decides. What happens to the file?"
    resolution: human
    class: product-preference
    chosen: "Keep it local and leave that exclude line through RC1. Commit it as its own small av-kit commit once fleet.py is committed here, on the human's separate word"
    source_tag: Human-approved
    precedents: ["docs/proposals/2026-11-03-fleet-mvp-outline.md:259 — each project's manifest lives in its repo", "this plan, 'Two files land outside this repo' — left for the human to keep or delete"]
    research: { engine: tavily, sources: ["https://git-scm.com/docs/gitignore/2.9.5 — info/exclude is for files specific to one user's workflow", "https://gitbybit.com/gitopedia/best-practices/atomic-commits — commit unrelated changes separately", "https://blog.vincentqiao.com/en/posts/claude-code-settings-intro — shared config is committed, personal overrides are not"] }
    reasoning: "The design puts the manifest in the repo, but today it serves a tool that is not committed and has nothing to do with RC1. Committing it in RC1 mixes unrelated work; deleting it stops av-kit running on the fleet"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all accepted'"
  - id: D-8
    stage: execution
    question: "The first row 14 runs were rejected with no_manifest because av-kit ignored its manifest. Should the snapshot carry an ignored manifest?"
    resolution: human
    class: two-way
    mandatory: [M-8]
    chosen: "Yes: after add -A, make_snapshot force-adds .agent/fleet.json by exact path to its temporary index. No other ignored file travels"
    source_tag: Human-approved
    precedents: ["AC-23 — ignored files stay out of the snapshot; this is a narrow exception"]
    research: { engine: tavily, sources: ["https://github.com/superfly/flyctl/issues/2245 — quotes Docker's docs that an ignored Dockerfile is still sent because the daemon needs it; flyctl left it out and failed the same way"] }
    reasoning: "The member cannot run without the manifest. Refusing at run would force the exclude line out, which risks the file entering the RC1 commit. Sending the manifest in the task needs more code and a <member host> update. The change was made before the ruling and reported to the human"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all accepted'"
  - id: D-9
    stage: execution
    question: "D-8 changed fleet.py after row 11. When do <member host> and the hub get the updated file?"
    resolution: human
    class: two-way
    mandatory: [M-10]
    chosen: "Once, at closeout, after the execution review settles the file, by repeating row 11's sequence. Row 14 repeats then only if a review correction changed fleet.py after its receipts"
    source_tag: Human-approved
    precedents: ["task.md row 11", "plan stop condition 2"]
    research: { engine: none, sources: [] }
    reasoning: "D-8 runs only on <hub host>, so <member host> behaves the same until then, and the review may change the file again"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all accepted'"
  - id: A-1-to-A-8
    stage: planning
    question: "Research depth, headless runs, bundles, no ssh, file locations, stack, foreground terminal, phase order"
    resolution: autonomous
    class: two-way
    chosen: "As in outline §5, except where A-9 and A-11 refine A-5"
    source_tag: Local Canon
    precedents: ["docs/proposals/2026-11-03-fleet-mvp-outline.md §5 decision_log"]
    research: { engine: none, sources: [] }
    reasoning: "The human accepted the outline without reversing any of them"
  - id: A-9
    stage: planning
    question: "Manifest format: YAML as outline A-5 said, or JSON?"
    resolution: autonomous
    class: two-way
    chosen: "JSON, at <repo>/.agent/fleet.json"
    source_tag: Local Canon
    precedents: ["core/.agent/review-limits.json — a repo policy file in JSON", "outline A-6 — stdlib only"]
    research: { engine: none, sources: [] }
    reasoning: "The standard library has no YAML parser, and a dependency would break one-file stdlib. tomllib reads only, and JSON is all this file needs"
  - id: A-10
    stage: planning
    question: "Plain HTTP on localhost in P1 as the outline implied, or TLS from the start?"
    resolution: autonomous
    class: two-way
    chosen: "TLS always"
    source_tag: Local Canon
    precedents: ["outline §5 D-1 — TLS is in from P2"]
    research: { engine: none, sources: [] }
    reasoning: "Two connection paths are more code than one, and the plain path would get no use after P1"
  - id: A-11
    stage: planning
    question: "Where does state live on <hub host>: P:/.agent as A-5 said, or ~/.agent/fleet?"
    resolution: autonomous
    class: two-way
    chosen: "FLEET_HOME, default ~/.agent/fleet, on every machine. <hub host> runs fleet.py from this repo"
    source_tag: Local Canon
    precedents: ["outline §2.8 — no P: anywhere; member home is ~/.agent"]
    research: { engine: none, sources: [] }
    reasoning: "One rule for every machine, and outline §2.8 outranks a location detail in A-5"
  - id: A-12
    stage: planning
    question: "Does run take free argv or a command name?"
    resolution: autonomous
    class: two-way
    chosen: "A command name from the manifest in the snapshot"
    source_tag: Research-backed
    precedents: ["handoff §5.1 — per-project manifest of checks"]
    research: { engine: none, sources: ["2026-11-01-remote-hosts.md §5 — quoting across shells was a recorded problem"] }
    reasoning: "No shell quoting across operating systems, and what ran is in the snapshot's own manifest. Free argv can be added later without changing the envelope"
  - id: A-13
    stage: planning
    question: "How does the key get to the member and the hub?"
    resolution: autonomous
    class: two-way
    chosen: "The member generates it (at the console, or over WinRM on <member host> under D-5) and sends it over the pinned connection. A human approves on <hub host> with a short code derived from it"
    source_tag: Research-backed
    precedents: ["outline §3 P2 — a human types the key; the agent never sees it"]
    research: { engine: none, sources: ["agichan README — one-time join code", "outline §6 Hosted AO — pairing by pinned fingerprint"] }
    reasoning: "Refines the outline: no human carries a secret between machines, and the human step is still the approval. member.json is readable by the same user, so an agent could read it if it disobeyed. The template forbids it, and it is stated as a limitation"
  - id: A-14
    stage: planning
    question: "Pairing in P2 as the outline listed, or in WP-1?"
    resolution: autonomous
    class: two-way
    chosen: "WP-1, so P1's localhost skeleton uses the same pairing, key and TLS path as <member host>"
    source_tag: Local Canon
    precedents: ["outline §2 — each phase adds and none replaces"]
    research: { engine: none, sources: [] }
    reasoning: "A P1 without keys would be code that P2 replaces"
  - id: A-15
    stage: planning
    question: "How is the certificate made, when stdlib ssl cannot create X.509?"
    resolution: autonomous
    class: two-way
    chosen: "The openssl CLI, found by shutil.which and then beside git, on the hub only. Refuse with openssl_missing"
    source_tag: Research-backed
    precedents: ["outline §6 — Hosted AO's pinned self-signed certificate"]
    research: { engine: native, sources: ["https://docs.python.org/3/library/ssl.html — loads certificates, has no creation API"] }
    reasoning: "Git for Windows ships openssl, and the hub already requires git. Members do not need it"
  - id: A-16
    stage: planning
    question: "How does a new member fetch fleet.py before it has a pin?"
    resolution: autonomous
    class: two-way
    chosen: "curl.exe -k over the hub's open bootstrap routes, verified by SHA-256 hashes in the pairing line"
    source_tag: Local Canon
    precedents: ["outline §3 P2 — trust on first use, as ssh does with host keys"]
    research: { engine: none, sources: [] }
    reasoning: "The hash from the human's own screen verifies the file, so TLS trust is not needed for this step. The files hold no secret. curl ships with Windows 10 and later, Linux and macOS"
  - id: A-17
    stage: planning
    question: "Full bundle per run, or incremental?"
    resolution: autonomous
    class: two-way
    chosen: "Full"
    source_tag: Local Canon
    precedents: ["docs/research/fleet/scope.md — av-kit pack is 11.31 MiB"]
    research: { engine: none, sources: [] }
    reasoning: "Incremental needs the hub to track what each member has. Nothing in the envelope stops adding it later"
  - id: A-18
    stage: planning
    question: "Slot made by git clone as outline §3 said, or git init plus fetch?"
    resolution: autonomous
    class: two-way
    chosen: "git init plus a fetch from the bundle"
    source_tag: Research-backed
    precedents: ["outline §2.5 — no member has origin"]
    research: { engine: native, sources: ["https://git-scm.com/docs/git-bundle — a bundle can be fetched from directly"] }
    reasoning: "A clone creates an origin remote that would then need removing"
  - id: A-19
    stage: planning
    question: "Default port?"
    resolution: autonomous
    class: two-way
    chosen: "8770, configurable with --port"
    source_tag: Local Canon
    precedents: ["outline D-1 precedent — port 8766 + configurable"]
    research: { engine: none, sources: [] }
    reasoning: "Free on <hub host>, and in the same range as the existing precedent"
  - id: A-20
    stage: planning
    question: "How can the plan gate on refcheck and sanitize, when both are already red?"
    resolution: autonomous
    class: two-way
    chosen: "Compare failures with a row-0 baseline and block on any new line"
    source_tag: Local Canon
    precedents: ["C:/Temp/agentic-framework/fleet-plan/refcheck-baseline.txt and sanitize-baseline.txt — both red before any fleet code exists"]
    research: { engine: none, sources: [] }
    reasoning: "Requiring green would pull in unrelated repairs. Skipping them would let new breaks through. The red baseline is reported to the human"
```

D-1 to D-9 are ruled. D-5 to D-9 were added during execution, after plan approval, and the execution
review covers them. A-9 to A-20 passed the obviousness test. Each one is two-way, so the human can reverse any of them
at the plan gate.

---

## Research References

- `docs/proposals/2026-11-03-fleet-mvp-outline.md`, rulings and sources
- `docs/research/fleet/scope.md`, `patterns.md`, `decision.md`, `ai-instructions.md`
- `docs/proposals/2026-11-01-remote-hosts.md` §5, reference only: snapshot method
- `the local network notes (lines 145-149)`: firewall practice
- `P:/av-kit/AGENTS.md:102`: no branches or worktrees
- `P:/av-kit/.agent/docs/commands.md`: registered checks
- https://docs.python.org/3/library/http.server.html: not for production; `ThreadingHTTPServer`
- https://docs.python.org/3/library/ssl.html: `do_handshake_on_connect`, `getpeercert(binary_form=True)`
- https://git-scm.com/docs/git-bundle and https://git-scm.com/docs/git-commit-tree
- https://pypi.org/pypi/dobby-orchestrator/json and https://github.com/slonana-labs/agichan: reference designs

## Validation stage contract

| Stage | Command | cwd | Scope | Blocking | Expected |
|---|---|---|---|---|---|
| Static | `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-03-fleet-mvp/task.md` | repo root | Task contract | Yes | Pass |
| Targeted | Verification Plan §2 | repo root | The three fleet test files | Yes | Pass |
| Package | Verification Plan §3 | repo root | `refcheck`, `sanitize --verify` against the baseline; AC-to-test coverage | Yes | No new failure |
| Fresh full | Verification Plan §5 | repo root | `core/tools/tests`, `scripts/tests` | Yes | Pass |
| Runtime | Verification Plan §4 | repo root, on <hub host>, with hub and member running | Live <member host> and av-kit | Yes, for AC-20, AC-21, AC-31 | Pass, from the receipts named in each row |

Native shell: PowerShell, with Python 3.14 on <hub host>. Input identity for evidence is the SHA-256 of
`git rev-parse HEAD`, `git status --porcelain` and `sys.version`, computed independently at H1-6b.
Intermediate evidence is not reused: the final review follows one fresh full gate.
