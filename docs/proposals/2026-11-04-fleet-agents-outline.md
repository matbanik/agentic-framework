# Fleet agents: work order and decisions

Status: outline, 2026-11-04. It feeds `/create-plan`. Nothing here is built. Mat accepted all six
recommendations in section 4 on 2026-11-04 ("all recommendations are accepted"). Section 4 is the
second HDP pass, with a precedent sweep and web research for each decision.

Inputs: Mat's 2026-11-04 messages ("Once we have that confirmed you can proceed with the full
enhacments including retooling of the credit scripts for the fleet"), the fleet MVP plan's Decision
Log, and the credits and dispatch code. `2026-11-01-remote-hosts.md` is reference only.

## 1. The design in one paragraph

<hub host> sends a short `agent` task through the hub. The member starts the existing credits run as a
detached scheduled task and answers at once, so it keeps polling. Later short tasks ask for status,
pass a message, stop the run or resume it, and each one calls a script that already exists. If the
agent has a question, its run stops and says so. `fleet watch` on <hub host> wakes the orchestrator,
the orchestrator asks Mat, and Mat's words start the resume. The result comes back as a git bundle
into a non-branch ref, and it lands on <hub host> only on Mat's word.

## 2. Tested on <member host>, 2026-11-04

All of this ran under an S4U task, the way the member runs. None of it ran through a fleet task.

| Check | Result |
|---|---|
| Claude and Codex answer real calls with no sign-in on <member host> | Pass, from a WinRM shell and from S4U |
| <hub host>'s own logins afterwards | Unchanged |
| `claude -p --permission-mode acceptEdits` writes a file | Pass |
| `--max-budget-usd` on the subscription token | Enforced: `error_max_budget_usd`, exit 1. `total_cost_usd` is reported |
| `pwsh`, `uv`, `git`, `python` on the S4U path | All present |
| `codex exec --sandbox workspace-write`, default Windows sandbox | **File not written, and exit 0** ("read-only filesystem policy") |
| The same with `windows.sandbox="elevated"`, <hub host>'s setting | **File not written, and exit 0** (shell runner timed out twice) |
| The same with `windows.sandbox="unelevated"` | Pass |
| `codex doctor`, 0.166.0, default settings | Exit 0, and it reports `sandbox backend disabled` |

Three things follow. Codex's exit code can't be the success signal, so a run is judged by its final
status line and its evidence. `codex doctor` can't be the setup check either, so setup needs a real
write test. A member also needs a Codex sandbox setting that passes that test.

Not tested: `elevated` after its administrator setup (no setup step was run on <member host>), Codex login
refresh after about 8 days, a credits run under S4U, an Interactive-logon task on a machine with
nobody signed in as that user, the M-1 gate on a subscription token, and movement on the plan usage
meters.

## 3. Work order

| # | Builds | Done when |
|---|---|---|
| A1 | Scripted member setup: both CLIs, `pwsh`, `uv`, Codex's file store and sandbox setting, recorded CLI versions. `fleet status` reports them | A clean re-run changes nothing, reports both CLIs, and passes a real write test on each |
| A2 | Credits on a member: `launch.auth: subscription`, an S4U task route, the M-1 gate run per member, one install in the member's home, hooks at user level, the subprocess credential scrub | A credits run on <member host> finishes under the subscription token, started locally, and Mat sees plan usage move with no Console charge |
| A3 | The `agent` task kind: `start`, `status`, `message`, `stop`, `resume`. One slot per run, kept across resume. The hub requires Mat's quote on `start` and `resume`. `fleet watch` on <hub host> | From <hub host>, a run answers a `query` mid-run, stops on a question, and finishes after a resume |
| A4 | Codex through `Invoke-CodexDispatch.ps1`, resume between turns, one Codex job at a time per member. Remote Claude may call it (D-5) | The same job finishes on Codex, and a remote Claude run gets a Codex answer |
| A5 | Results: a temporary-index snapshot, a bundle to the hub, `refs/fleet/result/<run>` on <hub host>, then the slot is dropped | One result from each CLI lands on Mat's word |
| A6 | Rules and docs: `bootstrap.md` relabelled, the credits and dispatch skills updated, these rulings recorded | The tests and package gates pass |

Left out: Cursor and Antigravity, member-to-member tasks (outline P6), Linux and macOS, autostart
after a reboot, live rulings during a run, mail from a member, and a separate low-privilege account
for agent runs. Live rulings stay out because the hook checks a ruling against a transcript that is
on <hub host> (`2026-11-01-remote-hosts.md:89-92`), and mail would put a mail password on the member.

Codex has no mid-run messages. The inbox hook is Claude-only, so Codex hears from the orchestrator
only between turns.

## 4. Decisions

Each brief went through a precedent sweep, and the receipts are kept locally. Web research used
Pomera search (Tavily and Exa), then the primary pages directly. Sources are labelled as authority
(official docs), practice (blogs, repositories, issue reports) or novel (papers).

### D-1: How a member gets its logins   [source-conflict] [planning]   mandatory: [M-2, M-6]

**Recommendation: keep the route just tested, and record it as a ruling for Mat's own account on
Mat's own machines only.** Mat approves in a browser on <hub host>. A script stores the result over WinRM
in a file only that user can read, and nothing goes through the hub. Claude's token goes to the
`claude` process through `-LaunchHook`, with `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` so Bash commands
and hooks don't inherit it. Codex gets a new login per machine, never a copy of <hub host>'s. The
credential script stays local and out of the public template.

| Option | Pros (vs. recommendation) | Cons (vs. recommendation) | Sources |
|---|---|---|---|
| ✅ Issue on <hub host>, store on the member | — | — | §2; Claude Code authentication and env-var docs; Codex authentication docs |
| ⚠️ Codex device-code login run on the member | The Codex credential never crosses the LAN, and it's OpenAI's preferred headless route | Beta, needs a ChatGPT security setting turned on, and is untested over WinRM. Claude still needs the token route, so two flows instead of one | Codex authentication docs |
| ⚠️ Sign in at each member's console, the current rule | Nothing crosses the network, and logins use the OS store | Needs a person at every machine, which Mat ruled out. S4U probably can't read the OS store (untested) | `2026-11-01-remote-hosts.md:330` |
| ⚠️ API keys on members | Anthropic's terms explicitly allow provisioning keys, and they're easy to reuse and cancel | Billed per token rather than the subscriptions Mat wants used. A stored key silently overrides the token | Anthropic legal page |

**Precedent:** `2026-11-01-remote-hosts.md:330` says "Set up by you at the console, never copied".
Mat already accepted one departure from that class of rule: plan D-5 pairs over WinRM
(`docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md:652-659`). Plan D-2 (`:615-622`)
says "the member's own login", and this route gives each member its own login, issued from <hub host>.
GitHub credentials stay off members (`:84`, `:447`), and this ruling doesn't touch that. The credits
skill forbids setting billing variables "to make a run look like Agent SDK usage" (`SKILL.md:340-343`).
`CLAUDE_CODE_OAUTH_TOKEN` doesn't do that, because `claude auth status` reports it as `oauth_token`,
but the ruling should name it because the two are close.
**Research:**
- [Claude Code authentication](https://code.claude.com/docs/en/authentication) (authority): `setup-token` is meant to be set "wherever you want to authenticate", for CI and scripts with no browser login.
- [Claude Code legal page](https://code.claude.com/docs/en/legal-and-compliance) (authority): developers "may not collect, store, or intermediate Claude.ai credentials or session tokens", but this doesn't prevent "an end user from signing in to the unmodified Claude Code binary with their own Claude subscription". Limits "assume ordinary, individual usage", and enforcement may come "without prior notice". My reading is that the ban targets products serving other people, not one person's own machines. The page doesn't address this case directly.
- [Claude Code env vars](https://code.claude.com/docs/en/env-vars) (authority): the scrub removes credentials from Bash, hooks and stdio MCP servers, and should be "one layer alongside narrow permission rules".
- [Codex authentication](https://learn.chatgpt.com/docs/auth) (authority): copying cached credentials to a headless machine is documented, with "Treat `~/.codex/auth.json` like a password".
- [Codex CI/CD authentication](https://learn.chatgpt.com/docs/auth/ci-cd-auth) (authority): one `auth.json` per runner or serialized stream.
- [NVIDIA AI Red Team](https://developer.nvidia.com/blog/practical-security-guidance-for-sandboxing-agentic-workflows-and-managing-execution-risk/) and [Ken Muse](https://www.kenmuse.com/blog/when-ai-agent-escapes-securing-dev-environment/) (practice): secrets should be short-lived, revocable and out of the agent's reach. This route falls short of that, and neither login offers a better form today.

**Reversibility / risk:** the route is two-way, but a leak may not be. Anything running on the member
as that user can read both files, including a prompt-injected agent, and the scrub only clears the
environment, not the file. Reports say `setup-token` has no list or revoke command
([48373](https://github.com/anthropics/claude-code/issues/48373),
[57400](https://github.com/anthropics/claude-code/issues/57400)), and the console route is
unconfirmed, so a leaked token may be hard to cancel. Both machines share one plan's limits. If
Anthropic reads its terms more strictly than I do, the consequence falls on Mat's account.
**If you do not answer:** A1 and A2 stay held, and the test credentials stay on <member host> until
`fleet_auth.py remove` runs.

### D-2: What runs a Claude job on a member   [governance-value] [planning]   mandatory: [M-3, M-7]

**Recommendation: the credits engine itself, on the subscription token.** Add `launch.auth`, an S4U
task route and one home install per member. Mid-run messages, `stop-after-row`, stop classes, caps,
resume and fork then all carry over. The key route stays the default, so <hub host> is unchanged. Budget
caps still apply, because §2 shows `--max-budget-usd` works on the token. A2's acceptance includes
Mat checking that plan usage moved and Console balance didn't, which is the only direct billing proof.

| Option | Pros (vs. recommendation) | Cons (vs. recommendation) | Sources |
|---|---|---|---|
| ✅ Credits engine, subscription, S4U | — | — | `core/.agent/skills/claude-credits/SKILL.md`; Agent SDK plan article |
| ⚠️ Dispatch wrappers only | Far less change: no store, gate or hooks | No mid-run messages or stop classes. It rebuilds what Mat asked to reuse | `cli-dispatch/SKILL.md:104-117` |
| ⚠️ Credits' no-task route, as a child of the member | No scheduled task or receipt | A member restart kills the run, and the M-1 gate is skipped | `Invoke-ClaudeCredits.ps1:187-191` |
| ❌ Console API key on members | The credits path as it is today, and Max plans now include monthly API credits | Needs a key on each machine, and spend beyond the included credits bills separately | `SKILL.md:18-24`; Agent SDK plan article |

**Precedent:** plan D-2 (`implementation-plan.md:615-622`) and outline
`2026-11-03-fleet-mvp-outline.md:147-148` already say "the member's own login", and that API key mode
waits for a declared budget. `2026-11-01-remote-hosts.md:45-60` proposed `launch.auth` with the same
launcher. Its line 58 says USD caps don't apply to a subscription run, and §2 shows
`--max-budget-usd` does. `Register-CreditsRun.Tests.ps1:268` and `CreditsTaskReadback.Tests.ps1:18,60`
pin `Interactive` logon. The aim is to keep those for the key route and add tests for the member
route, and the plan names any assertion that must change.
**Research:**
- [Use the Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) (authority): as of October 7, 2026, signed in with a plan, "the Claude Agent SDK and `claude -p` still draw from your subscription limits". A June 15 change was paused, so this rule has already moved once.
- [Task Scheduler security contexts](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks) (authority): S4U tasks need the Logon as Batch privilege, which administrators have by default.
- [Microsoft Q&A](https://learn.microsoft.com/en-ie/answers/questions/6053779/windows-11-home-s4u-scheduled-tasks-and-batch-logo) (weak, AI-generated answer): S4U can't reach network resources. §2 shows model calls work, so read this as shares and other authenticated resources.
- [harness-remote](https://github.com/giuliastro/harness-remote), [codewhale fleet](https://github.com/hmbown/codewhale/blob/3c84e7609df20157fefada577b1088fbeb7ae06a/docs/FLEET.md) and [open-tag](https://github.com/fancyboi999/open-tag/blob/main/ARCHITECTURE.md) (practice): keep the native CLI session and put a thin start, status, stop and resume layer around it.

**Reversibility / risk:** two-way, because the key route stays the default. The M-1 receipt is bound
to the CLI version, so an auto-update on a member blocks new runs until the gate runs again. The plan
handles this with a gate step, not a waiver. Whether the gate passes on a token is untested, and A2
stops if it doesn't. If Anthropic moves `claude -p` off plan limits later, the member route stops
being cheap, and the key route is still there.
**If you do not answer:** A2 stays held.

### D-3: Who starts and resumes, and what happens on a question   [governance-value] [planning]   mandatory: [M-14]

**Recommendation: only the orchestrator, only on Mat's chat words, and a question stops the run.**
Members get `credits_start_policy: agent-on-user-chat` in their own config, and <hub host> stays
`human-only`. The hub refuses `start` or `resume` with no quote, and the run checks the quote with
`credits_msg.py authority`. On a question the run ends `STOPPED:decision`, `fleet watch` wakes the
orchestrator, and it asks Mat. Mat's answer goes in a resume brief, in the same session and slot.

| Option | Pros (vs. recommendation) | Cons (vs. recommendation) | Sources |
|---|---|---|---|
| ✅ Orchestrator, Mat's quote, stop and resume | — | — | Plan D-2; open-tag |
| ⚠️ The run waits at a live gate for a ruling | Keeps the session running, with no restart cost | The ruling check needs a transcript on <hub host>, so it needs new machinery. A waiting run also holds a slot | `2026-11-01-remote-hosts.md:89-92`; `create-plan.md:809-816` |
| ❌ `human-only`, typed at a terminal | No agent can start anything | Mat would have to type on the member, or the orchestrator could never start a run | `core/.agent/credits/config.json:5` |

**Precedent:** plan D-2 (`implementation-plan.md:615-622`) and outline
`2026-11-03-fleet-mvp-outline.md:143-144,158,163`, accepted by Mat, already say orchestrator only with
Mat's quote. Line 164 records the open issue that a start source can't be verified. Zorivest has
already run a credits job as `agent-on-user-chat` with a quote. `2026-11-01-remote-hosts.md:374-375`
recommends the same policy, and `2026-10-31-fleet-nodes.md:253,660` wanted authority taken from the
node's own transcript, which a member doesn't have. Nothing checks the quote yet, because `agent`
tasks are still refused.
**Research:**
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) (authority for that framework): a pause saves state and resumes by thread id. Work re-runs on resume, so side effects must be safe to repeat.
- [open-tag](https://github.com/fancyboi999/open-tag/blob/main/ARCHITECTURE.md) (practice): stop the process and wake it with a saved session id, which is this design.
- [Ken Muse](https://www.kenmuse.com/blog/when-ai-agent-escapes-securing-dev-environment/) (practice): a person sees the plan and can revoke. These searches turned up no standard for carrying a person's authority across machines.

**Reversibility / risk:** two-way, as a config value and a hub check. A quote shows only what the
orchestrator recorded, so this check is only as trustworthy as the orchestrator. A resumed step must
tolerate having partly run.
**If you do not answer:** A3 stays held.

### D-4: Permissions inside a member's run   [governance-value] [planning]   mandatory: [M-13]

**Recommendation: no full bypass, as already ruled. Claude runs `acceptEdits` with a per-run
`--allowedTools` list. Codex runs `workspace-write` with `unelevated`, except that A1 tries `elevated`
setup once per member and uses it if a real write test passes under S4U.** `elevated` is worth one
try because it's the only mode with denied read paths and stronger network isolation, and §2's failure
came with no setup step run. Success is judged by evidence, never by exit code, and A1 records each
member's Codex version.

| Option | Pros (vs. recommendation) | Cons (vs. recommendation) | Sources |
|---|---|---|---|
| ✅ `acceptEdits` plus list; Codex best mode that passes | — | — | §2; Claude permission modes; Codex Windows docs |
| ⚠️ Claude `dontAsk` plus list | Anthropic's documented mode for "Locked-down CI and scripts". `rm`, `mv` and `sed` must also be listed. Credits already accepts it | Untested on a member and stalls more often. Those commands only reach the disposable slot, so the gain is small | Claude permission modes; `credits-run.v1.json:24` |
| ⚠️ `bypassPermissions` for workflow runs, as credits suggests | Full plan and execution runs won't stall on a denied tool | Anthropic says isolated environments "without internet access" only. An injected agent can do anything that user can, and both logins are readable | `SKILL.md:295`; Claude permission modes |
| ⚠️ Codex `unelevated` only, no `elevated` try | One setting, nothing to attempt | Stays on what OpenAI calls a "legacy fallback", with no denied read paths | Codex Windows docs |

**Precedent:** outline `2026-11-03-fleet-mvp-outline.md:145-151`, accepted, says workspace permissions
and no full bypass. `SKILL.md:295` recommends `bypassPermissions` for workflow runs on <hub host>, which
already goes against Anthropic's isolation advice. This keeps that out of unattended members. Bounded
jobs come first, since a full `/execution-session` will stall until its list is built.
**Research:**
- [Claude permission modes](https://code.claude.com/docs/en/permission-modes) (authority): covers the four modes above. `auto` runs a classifier and "doesn't stop the run" on repeated blocks, which doesn't fit stop-and-ask, and credits doesn't accept it.
- [Codex Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox.md) (authority): `elevated` "Requires administrator-approved setup". `unelevated` "Has weaker network isolation" and "doesn't support denied read paths". Neither covers scheduled or service use.
- [openai/codex 34961](https://github.com/openai/codex/issues/34961) (practice): the same exit-0, no-file symptom, open, with no maintainer reply. One commenter fixed it with `unelevated`. Another has no unattended run yet without a signed-in session, so the `elevated` try may fail.
- [openai/codex 46515](https://github.com/openai/codex/issues/46515) (practice): an auto-update broke non-admin Windows setups, hence recording versions.
- [OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Secure_Coding_with_AI_Cheat_Sheet.html) and [Willison](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) (practice): an agent with private data, untrusted content and outside access is the dangerous mix, and a member run has all three.

**Reversibility / risk:** two-way, though changing the launch profile means re-running the M-1 gate.
Runs that need many commands may stall on the list, and a stall stops the run with `STOPPED:decision`,
which is the safe way to fail. Under `unelevated`, assume a Codex run can read the Claude token file.
**If you do not answer:** A3 and A4 stay held.

### D-5: May a remote Claude call Codex   [governance-value] [planning]   mandatory: [M-13]

**Recommendation: yes, through `Invoke-CodexDispatch.ps1` only, in its two review modes, one job at
a time, and when the brief asks for it.** Its allow rule leaves out `FullAccess`, and a Codex job
started this way can't start another. It's on request and not a default gate, because the evidence
that Codex improves Claude's work is mixed. `FORBIDDEN_COMMANDS` stays as it is, because it governs
`run` manifests.

| Option | Pros (vs. recommendation) | Cons (vs. recommendation) | Sources |
|---|---|---|---|
| ✅ Yes, wrapper only, review modes, serialized, on request | — | — | `cli-dispatch/SKILL.md:14`; Codex CI/CD docs |
| ⚠️ No; review on <hub host> after the result returns | One less path, no second login in play during a run, and <hub host>'s sandbox is stronger | Reviews wait for the result, <hub host> does the work, and the answer to Mat's original question becomes no | §2 |
| ❌ Bare `codex exec` from the run | Nothing to build | Breaks the wrapper-only rule, with no evidence or job limit, and reports warn of recursion and token burn | `cli-dispatch/SKILL.md:14`; codex-bridge |

**Precedent:** `2026-11-01-remote-hosts.md:169-170` planned "the independent review on the host
through Codex". The fleet plan and outline say nothing on this. The wrapper's review modes both use
`workspace-write` with a receipts root (`Invoke-CodexDispatch.ps1:1153-1159`), so this depends on D-4's
Codex setting.
**Research:**
- [arXiv 2607.21656](https://arxiv.org/html/2607.21656) (novel, read in excerpt, older models): Claude reviewing Codex raised the pass rate from 71.6% to 89.7%, while Codex reviewing Claude lowered it from 91.4% to 82.8%. The authors say the design can't fully separate direction from the baseline gap.
- [Codex CI/CD authentication](https://learn.chatgpt.com/docs/auth/ci-cd-auth) (authority): don't share `auth.json` across concurrent jobs, hence one at a time.
- [OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Secure_Coding_with_AI_Cheat_Sheet.html) (practice): treat one agent's output as untrusted, and don't let sub-agents inherit full permissions.
- [codex-bridge](https://github.com/Sateezg/codex-bridge) and a [Reddit report](https://www.reddit.com/r/ClaudeCode/comments/1uasmo8/i_wired_claude_code_and_codex_to_check_each) (practice): Claude shelling out to Codex on a subscription works, but unguarded calls risk recursion and token burn.

**Reversibility / risk:** two-way, by removing one allow rule. Use counts against the same ChatGPT plan
as <hub host>. A Codex job that runs during a Claude run also waits for or blocks orchestrator-started Codex
work on that member.
**If you do not answer:** A4 builds Codex as a task only, and remote Claude can't call it.

### D-6: What setup publishes, and what stays a human step   [governance-value] [planning]   mandatory: [M-3, M-6, M-12]

**Recommendation: track a setup script with no hosts or credentials, keep the rest local, and keep
one typed `approve` line per new machine.** The WinRM connection and the credential script stay local.
`bootstrap.md` is relabelled so the human steps are browser approvals, the UAC prompt on the first
machine, and `approve`. This keeps one more step than Mat's "Human should be only needing to login",
so that conflict is Mat's to settle. I'd keep it because it costs one line per machine, in the same
sitting as the sign-in, and it's the one thing stopping an agent from adding a machine to the fleet.
The two parts can be ruled separately.

| Option | Pros (vs. recommendation) | Cons (vs. recommendation) | Sources |
|---|---|---|---|
| ✅ Tracked script; local connection and credentials; typed `approve` | — | — | Plan D-13, D-15, AC-7 |
| ⚠️ An agent runs `approve` | Matches Mat's words exactly, with no typed step | An agent could admit a machine that then receives work. Removes a tested guard and changes AC-7 | `fleet.py` `approve`; `implementation-plan.md:258` |
| ⚠️ A pre-approved single-use join key | No typed line per machine, and it's how Tailscale scripts this | New code and a new secret, for a fleet of a few machines. A leaked key admits a machine | Tailscale device approval |
| ⚠️ Keep all scripts local | Nothing new to publish or maintain | Every new machine starts from an inaccurate template | `bootstrap.md` |

**Precedent:** the plan requires a real terminal for `approve`, and "no HTTP route can approve
anything" (`implementation-plan.md:95,154,203`, AC-7 at `:258`). Reflection lines 98 and 100 record D-13
and D-15, which keep addresses and local inputs out of tracked files. Plan D-5 prepared scripts for
elevation. `2026-11-03-fleet-mvp-outline.md:78` said setup was not an installer script, and Mat
objected on 2026-11-04.
**Research:** this search was thin, with three enrollment sources and none on a fleet this small.
- [Tailscale device approval](https://tailscale.com/kb/1099/device-approval) (authority for that product): an admin approves each device, or generates a key that auto-approves.
- [GitHub self-hosted runners](https://docs.github.com/en/actions/reference/runners/self-hosted-runners) (authority for that product): registration through a scoped token.
- [kubelet-csr-approver](https://github.com/postfinance/kubelet-csr-approver) (practice): automatic approval after configured checks.
- [Claude Code legal page](https://code.claude.com/docs/en/legal-and-compliance) (authority): the storage limit on developers is why the credential script isn't offered in a public template.

Automated enrollment is normal when a scoped credential backs it, so typed approval is stricter than
some practice.
**Reversibility / risk:** publishing is one-way once pushed, and pushing still needs Mat's word.
`approve` is two-way, and can be loosened later if the line proves annoying.
**If you do not answer:** the scripts stay local, `bootstrap.md` is only relabelled, and `approve`
stays as it is.
