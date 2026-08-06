---
name: Session Meta-Review
description: Structured retrospective skill for reviewing session MD files. Provides friction taxonomy, segment detection patterns, sequential thinking template, and web research query bank for continuous improvement of agent-human interactions.
---

# Session Meta-Review Skill

A structured analysis toolkit for reviewing session MD files to identify friction points and generate concrete improvement rules. Designed to be called by the `/session-meta-review` workflow.

## When to Use

- After any session that felt slow, confused, or required excessive back-and-forth
- After a Codex validation cycle with unusually high pass count (> 4 review passes)
- After a session where the human had to re-explain scope mid-execution
- As a weekly quality audit (run on the most recent 2–3 sessions)
- Any time you see `MODE_SWITCH: EXECUTION → PLANNING` in the middle of a task

---

## Segment Taxonomy

Every turn in a session belongs to one of these segment types:

| Type | Description | Detection Signal |
|------|-------------|-----------------|
| `HUMAN_PROMPT` | Human-authored instruction or feedback | Starts a new conversation turn |
| `AGENT_PLAN` | Agent entering PLANNING mode, writing implementation plan or task.md | `task_boundary(Mode=PLANNING)`, `notify_user(BlockedOnUser=true)` |
| `AGENT_TOOL_CALL` | Agent invoking a tool | Any tool call (write_to_file, run_command, browser_subagent, etc.) |
| `TOOL_OUTPUT` | Result returned from a tool | Tool result block |
| `AGENT_RESPONSE` | Agent's final conversational turn output | Narrative text at end of agent turn |
| `MODE_SWITCH` | Agent changing task mode | `task_boundary` call with mode change |
| `CLARIFICATION_REQUEST` | Agent asking the human a question | `notify_user` during active task |
| `RETRY` | Agent re-running same tool or approach | Repeated tool call with identical or near-identical args |

---

## Friction Taxonomy

Five categories with detection signals and mitigation strategies:

### 1. Prompt Clarity

| Signal | Severity | Mitigation |
|--------|----------|-----------|
| Human rephrased the same request 2+ times | Medium | Add "Clarify scope before Planning" rule |
| Scope changed mid-EXECUTION (new `HUMAN_PROMPT` that altered task) | High | Add pre-task clarification checklist to workflow |
| Implementation plan was rejected and required 2+ revisions | High | Add "State constraints upfront" example to workflow |
| Agent asked > 2 clarifying questions in one session | Medium | Compress questions; batch into one `notify_user` |

**Mitigation template:**
```
BEFORE: Agent immediately entered PLANNING without confirming scope.
AFTER:  Agent lists 3 assumptions and asks for confirmation in a single notify_user before planning.
```

---

### 2. Context Load

| Signal | Severity | Mitigation |
|--------|----------|-----------|
| Agent read > 10 files before first plan output | Medium | Apply file-read ordering heuristics |
| Agent re-read same file 2+ times in one session | Low | Cache key content in session notes or handoff |
| Agent used stale KI or old session note instead of current state | High | Add "Check KI freshness" step to prerequisites |
| Tool output was large and discarded without summarization | Low | Use output_to_file + targeted rg for large outputs |

**Mitigation template:**
```
BEFORE: Agent read 15 files sequentially before producing any output.
AFTER:  Agent reads skeleton files (AGENTS.md, current-focus.md) first, then targeted reads only.
```

---

### 3. Tool Efficiency

| Signal | Severity | Mitigation |
|--------|----------|-----------|
| Same tool called 3+ times with identical args | High | Add retry guard heuristic; use `status` check before retry |
| `run_command` failed and agent retried without diagnosing error | High | Require command_status read before retry |
| Agent used browser_subagent for static content readable via read_url_content | Low | Prefer read_url_content / read_url_content for static pages |
| Agent called tools sequentially that were independent (missing parallelism) | Low | Add "parallel independent tool calls" note to session notes |
| write_to_file used when multi_replace_file_content was sufficient | Low | Use targeted edits for files modified > 1× per session |

**Mitigation template:**
```
BEFORE: Agent called run_command 4× with same command after transient failure.
AFTER:  Agent reads command_status after 1 failure, diagnoses error, then retries with fix.
```

---

### 4. Verification Gaps

| Signal | Severity | Mitigation |
|--------|----------|-----------|
| Agent declared work complete without running validation command | High | Add pre-completion verification checklist |
| Handoff claim contradicted by `rg` output during review | High | Apply pre-handoff-review skill earlier |
| Agent ran validation BEFORE applying all fixes (stale evidence) | High | Use "evidence freshness MUST BE LAST" rule explicitly |
| Test counts in handoff did not match `pytest` output | Medium | Paste fresh output verbatim into handoff |
| No negative-path test for a new API route | Medium | Add error-mapping sweep to pre-handoff checklist |

**Mitigation template:**
```
BEFORE: Agent wrote "all tests passing" based on memory, not a fresh pytest run.
AFTER:  Agent runs pytest immediately before writing the handoff and pastes exact output.
```

---

### 5. Communication Quality

| Signal | Severity | Mitigation |
|--------|----------|-----------|
| Human had to ask "what did you change?" after a large batch of edits | Medium | Add diff summary to agent response for multi-file edits |
| Agent explanation was longer than the work it described | Low | Apply "one sentence per change" rule |
| Agent blocked on user for a decision that was already answered in AGENTS.md | Medium | Add "check AGENTS.md before notify_user" guard |
| Agent failed to surface a blocker until the end of a long execution chain | High | Surface blockers at the FIRST point of uncertainty |
| Human approved a plan then agent deviated from it without notification | High | Log mid-session deviations as inline `notify_user` calls |

**Mitigation template:**
```
BEFORE: Agent completed 15 tool calls before telling the human about a blocking issue.
AFTER:  Agent surface blockers via notify_user at the first moment of ambiguity.
```

---

## Sequential Thinking Template

Pre-scaffolded 8-thought sequence for the `sequentialthinking` MCP. Adjust `totalThoughts` up if complexity warrants. Use `isRevision` freely.

```
Thought 1 (totalThoughts=8): What is the session's stated goal and what was actually delivered?
  Identify the gap (if any).

Thought 2: Review the Segment Table. Which segments have friction_signals attached?
  List their seq numbers and types.

Thought 3: For Prompt Clarity — was the human intent clear from the first HUMAN_PROMPT?
  Did the agent need to ask clarifying questions? How many HUMAN_PROMPT pivots occurred?

Thought 4: For Context Load — how many files were read before first meaningful output?
  Were any reads redundant or could they have been deferred?

Thought 5: For Tool Efficiency — identify any RETRY segments or sequential-instead-of-parallel patterns.
  Did any tool call produce Output that was not referenced in the next AGENT_RESPONSE?

Thought 6: For Verification Gaps — was validation run at the right moment?
  Were any claims made without corresponding file-state evidence?

Thought 7: For Communication Quality — did the agent surface blockers promptly?
  Were responses right-sized for the human's needs?

Thought 8 (synthesis): Rank findings by severity. For each High finding, propose a root cause
  and a single candidate mitigation rule. Mark any thought 3-7 findings that need external evidence.
```

Example invocation pattern:
```
sequentialthinking(
  thought = "...",
  thoughtNumber = 1,
  totalThoughts = 8,
  nextThoughtNeeded = true
)
```

---

## Web Research Query Bank

Mapped to friction categories. Use `search_web`.

| # | Category | Query Template |
|---|----------|---------------|
| Q1 | Prompt Clarity | `"agentic AI prompt clarity best practices scope confirmation"` |
| Q2 | Prompt Clarity | `"AI agent clarification questions upfront vs mid-task"` |
| Q3 | Context Load | `"AI agent file reading efficiency context window optimization"` |
| Q4 | Context Load | `"LLM context management session continuity agentic workflows"` |
| Q5 | Tool Efficiency | `"AI agent tool call retry patterns exponential backoff agentic"` |
| Q6 | Tool Efficiency | `"parallel tool calls LLM agentic efficiency patterns"` |
| Q7 | Verification Gaps | `"AI agent self-verification evidence freshness hallucination mitigation"` |
| Q8 | Verification Gaps | `"agentic TDD test coverage verification before handoff patterns"` |
| Q9 | Communication Quality | `"AI agent friction UX patterns human in the loop escalation"` |
| Q10 | Communication Quality | `"agentic AI blocker surfacing communication timing patterns"` |

**Selection rule**: Use Q1/Q2 for Prompt Clarity findings, Q3/Q4 for Context Load, etc. Run at most 2 queries per High finding. Skip web research for Low findings unless the agent is uncertain about the mitigation.

---

## Output Contract

### RULE Format

```
RULE-{N}: {one actionable behavior — present tense, imperative}
CATEGORY: {Prompt Clarity | Context Load | Tool Efficiency | Verification Gaps | Communication Quality}
SOURCE: {friction signal — cite segment seq numbers e.g. "seg-04, seg-07 (RETRY)"}
EVIDENCE: {URL title + URL, or "internal pattern only"}
EXAMPLE:
  BEFORE: {specific behavior that caused friction}
  AFTER:  {improved behavior}
```

### Reflection Appendix Format

When appending to a reflection file, add **after** the existing `## Next Session Design Rules` section:

```markdown
## Meta-Review Addendum — {YYYY-MM-DD}

*Generated by `/session-meta-review` workflow. External evidence validated via web research.*

### Additional Improvement Rules

{RULE-{N} blocks here}

### Friction Summary

| Category | Findings | Max Severity |
|----------|----------|-------------|
| Prompt Clarity | N | High/Med/Low |
| Context Load | N | High/Med/Low |
| Tool Efficiency | N | High/Med/Low |
| Verification Gaps | N | High/Med/Low |
| Communication Quality | N | High/Med/Low |
```

---

## Evidence of Design Basis

This skill was designed using:

| Source | Key Insight Applied |
|--------|---------------------|
| Smashing Magazine — Designing for Agentic AI UX (2026) | Intentional friction as speed bump; six UX lifecycle patterns |
| ByteByteGo — Top Agentic Workflow Patterns | Reflection pattern: observe → learn → adjust; self-improving loops |
| Tungsten Automation — Agentic AI Reflection Pattern | Self-RAG: targeted retrieval tied to reflection cycle |
| dev.to — Building Effective Prompt Engineering Strategies | Data-driven iteration from prod logs; meta-prompting for optimization |
| Lakera — Ultimate Guide to Prompt Engineering 2026 | Log analysis → scaffold patching; scaffolding pattern table |
| infoq — From Prompts to Production | DevEx framework: detect friction → remove bottlenecks systematically |
