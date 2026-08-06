# Issue → MEU → Plan Loop

> Portable contract for learning from mistakes: capture defects, triage into work units,
> group into sessions, plan, execute, reflect — then feed design rules and new issues back in.

```
REPORT / DISCOVER
       │
       ▼
 known-issues.yaml  (SSOT)     ◄── session discoveries, human reports, discover scanner
       │
       ▼
 /issue-triage                 verify → classify → enrich → bucket
       │
       ▼
 triage-output.yaml            ephemeral batches (archived / actionable / deferred)
       │
       ▼
 /session-grouping             register MEUs into meu-status.yaml + grouping proposal
       │
       ▼
 /create-plan                  applies prior reflection "Next Session Design Rules"
       │
       ▼
 execute → handoff → independent review
       │
       ▼
 reflection + /session-meta-review
       │
       ├──► Next Session Design Rules ──► next /create-plan
       └──► new/updated known-issues   ──► next /issue-triage
```

## End-to-end path (record → reconcile → plan)

This is the full cycle an adopter runs when work surfaces during implementation — not just
when filing a bug by hand.

### 1. DISCOVER — scan for untracked signals

During or after implementation, run the discovery scanner to find TODO/FIXME/HACK comments
that are not yet linked to a known issue:

```bash
uv run python tools/issue_triage.py discover --dry-run   # preview only
uv run python tools/issue_triage.py discover             # persist as candidate issues
```

New hits are written to `known-issues.yaml` with status **`candidate`** (hidden from the
default rendered view). IDs use the `DISC-` prefix.

### 2. Candidate → open or dismissed

Review candidates before they enter triage:

```bash
uv run python tools/issue_triage.py promote DISC-001   # candidate → open
uv run python tools/issue_triage.py dismiss DISC-002   # candidate → dismissed
uv run python tools/issue_triage.py render --include-candidates
```

Alternatively, record issues directly with `add` (human report path) — skip discover when
the defect is already understood.

### 3. `/issue-triage` — verify, classify, bucket

Invoke the **issue-triage** workflow (PLANNING-only). It reads the YAML SSOT, runs
`verify --deep`, classifies each active issue into the taxonomy (`MEU-NEW`, `MEU-EXPAND`,
`PLAN-NEW`, `ARCH-DECISION`, …), and produces ephemeral output:

```bash
uv run python tools/issue_triage.py bucket    # proposed MEU batches (preview)
uv run python tools/issue_triage.py triage    # writes triage-output.yaml
```

Human/coordinator gates apply for `ARCH-DECISION` and enrichment that needs judgment —
do not delegate those to a builder subagent.

### 4. `triage-output.yaml` → `/session-grouping`

The triage artifact hands off to **session-grouping**: pre-classified issues, enrichment
fields, and proposed MEU batches. Stage A registers new MEUs in `meu-status.yaml`; Stage B
builds a session-grouping proposal under `.agent/context/grouping/`.

Preferred input: `triage-output.yaml`. Fallback: read `known-issues.yaml` directly when
triage has not been run.

### 5. `/create-plan` — plan the next session

**create-plan** consumes the grouping proposal (or the next pending MEU band from the
registry). At Step 1 it scans handoffs, MEU stats, and the **most recent reflection**.

**Next Session Design Rules** (from the prior session's reflection, refined by
`/session-meta-review`) are applied here — they tune planning constraints, delegation
boundaries, and workflow habits before Step 4 writes `implementation-plan.md` + `task.md`.

### 6. Execute → reflect → feed back

After execution, handoff, and independent review, closeout writes a reflection whose
**Next Session Design Rules** section closes the loop:

| Output | Feeds |
|---|---|
| `Next Session Design Rules` (reflection) | Next `/create-plan` Step 1 |
| New or updated issues (`add`, `discover`, session findings) | Next `/issue-triage` or discover scan |
| MEU status updates | `meu_status.py` + registry render |

## Artifacts

| Artifact | Role | Edit? |
|---|---|---|
| `.agent/context/known-issues.yaml` | Issue SSOT | yes (or via CLI) |
| `.agent/context/known-issues.md` | Generated view | **no** — `issue_triage.py render` |
| `.agent/context/triage-output.yaml` | Triage → grouping handoff | regenerate via `triage` |
| `.agent/context/meu-status.yaml` | MEU SSOT | yes (or via CLI) |
| `.agent/context/meu-registry.md` | Generated MEU tables | **no** — `meu_status.py render` |
| `docs/BUILD_PLAN.md` (or Spec) | Phase tracker + summary AUTOGEN regions | markers only |
| reflections `Next Session Design Rules` | Learning feed into planning | yes at closeout |

## Skills & tools

- `.agent/skills/issue-triage/SKILL.md` → `tools/issue_triage.py`
  - Subcommands: `stats`, `list`, `get`, `add`, `verify`, `render`, `migrate`, `bucket`,
    `triage`, `discover`, `promote`, `dismiss`
- `.agent/skills/meu-status/SKILL.md` → `tools/meu_status.py`
- Workflows: `issue-triage.md`, `session-grouping.md`, `next-project.md`, `create-plan.md`, `session-meta-review.md`
- Narrative: `issue-lifecycle-guide.md`

## Adopter setup (minimum)

1. Copy `core/tools/` and the two skills into the project.
2. Copy empty `.agent/context/` seeds (not live product data).
3. Copy `templates/BUILD_PLAN-STUB.md` → your Spec/build-plan path with AUTOGEN markers.
4. Edit `tools/issue_triage/model.py` → `VALID_COMPONENTS` (and skill ID-prefix table) for your domain.
5. Install Python deps: `pyyaml`, `jsonschema`.
6. Smoke: `python tools/issue_triage.py stats` and `python tools/meu_status.py stats`.

## Never-delegate note

Triage classification that needs a human decision (`ARCH-DECISION`, enrichment answers) stays
on the coordinator / human gate — do not hand those to a builder subagent.
