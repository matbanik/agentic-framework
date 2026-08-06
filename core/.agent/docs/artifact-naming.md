# Artifact Naming & Instruction-Coverage Reference

> Relocated from AGENTS.md (2026-06-13 instruction-set-optimization slim).


## Artifact Naming Convention

> [!IMPORTANT]
> **Date-based naming (going forward).** All new handoffs and reflections use date-based naming. Legacy files (001–125) with sequence prefixes remain untouched. Do NOT use sequence numbers on new artifacts.

### Handoffs

```
{YYYY-MM-DD}-{project-slug}-handoff.md
```

- **Path**: `.agent/context/handoffs/`
- **Template**: `.agent/context/handoffs/TEMPLATE.md`
- **Same-day collision**: append MEU range suffix (e.g., `-ph4-ph7-handoff.md`) or letter (`-a`, `-b`)
- **Review files**: `{YYYY-MM-DD}-{project-slug}-plan-critical-review.md` or `-implementation-critical-review.md`

### Reflections

```
{YYYY-MM-DD}-{project-slug}-reflection.md
```

- **Path**: `docs/execution/reflections/`
- **Template**: `docs/execution/reflections/TEMPLATE.md`

### Template-First Rule (Mandatory)

> [!CAUTION]
> **Before creating ANY handoff, reflection, or review file, `view_file` its canonical template AND a recent peer exemplar.** Do NOT write artifacts from memory. This is not optional — it is a P1 quality gate.

Required `view_file` calls before artifact creation:

| Artifact | Template | Exemplar (most recent by date) |
|----------|----------|---------------------------------|
| **Handoff** | `view_file: .agent/context/handoffs/TEMPLATE.md` | `ls .agent/context/handoffs/ \| Sort-Object` → pick latest |
| **Reflection** | `view_file: docs/execution/reflections/TEMPLATE.md` | `ls docs/execution/reflections/ \| Sort-Object` → pick latest |
| **Plan review** | `view_file: .agent/context/handoffs/REVIEW-TEMPLATE.md` | Pick latest `*-plan-critical-review.md` |
| **Impl review** | `view_file: .agent/context/handoffs/REVIEW-TEMPLATE.md` | Pick latest `*-implementation-critical-review.md` |

**Enforcement:** `completion-preflight` §Closeout Artifact Quality Check validates structural markers. Non-compliant artifacts will force a rewrite. Read the template AND exemplar first to avoid rework.

> **Why the exemplar?** Templates show structure; exemplars show quality. Without an exemplar, agents fill templates with minimal content that is structurally valid but substantively empty. The exemplar provides the quality floor.

### Rationale (Research-backed)

Date-based naming is preferred for review artifacts because: (1) temporal context is the primary metadata for reviewers, (2) it eliminates global state dependency that causes naming collisions across agents/sessions, (3) the project slug already disambiguates same-day files. Sequential numbering adds no semantic value when the slug carries the ordering signal.


## Instruction Coverage Reflection

<!-- instruction_coverage_reflection: meta-prompt v1 -->
<!-- Placement: EOF recency zone (Liu et al.; Anthropic "queries at end" guidance) -->

At the end of every session, before yielding control, emit a single
fenced YAML block matching `.agent/schemas/reflection.v1.yaml`.

Rules:
- Mark a section `cited: true` only if you actually consulted that
  section's text to make a decision this session.
- Set `influence` honestly: 0 if you did not consider it, 1 if you
  read it but it did not change your output, 2 if it shaped output
  phrasing or structure, 3 if it determined a yes/no decision.
- Listing more than 5 entries in `decisive_rules` is a violation.
- Free-form `note` field is at most one sentence. Do not add fields
  not in the schema.
- Do not flatter the instruction set. If a section was useless,
  set influence: 0. If a rule was wrong, log it under `conflicts`.

Output exactly one ```yaml ... ``` block in the `## Instruction Coverage` section.
No prose around the YAML block itself. The reflection file MUST still follow
the full template structure from `docs/execution/reflections/TEMPLATE.md` —
the YAML block is section 7 of 7, not the entire file.
