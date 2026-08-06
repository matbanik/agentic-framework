# Skill-Optimizer LLM-Judge Rubric

> Consumed by the validation gate (`tools/skill_optimize/gate.py`). The gate
> **refuses to run** without a schema-valid rubric (AC-3.6) — there is no silent
> default. Each dimension carries its own source label (no bare "best practice").

The judge scores **candidate-vs-baseline** instructions for a single held-out
task digest, pairwise, in both presentation orders (the harness averages to cancel
position bias — arXiv:2406.07791). For each dimension the judge emits a preference
in `[-1, 1]` (positive = candidate better); the gate combines them by `weight`.

## Dimensions (default rubric)

| Dimension | Weight | What the judge compares | Source label |
|-----------|--------|-------------------------|--------------|
| `friction_reduction` | 0.35 | Would the candidate instructions have reduced the friction recorded in this task's reflection (re-asks, retries, scope churn)? | Local Canon (session-meta-review friction taxonomy) |
| `ac_coverage` | 0.25 | Does the candidate better cover the acceptance criteria / behaviors this task actually exercised? | Research-backed (held-out outcome labels; MT-Bench rubric-judge arXiv:2306.05685) |
| `instruction_clarity` | 0.20 | Is the candidate clearer / less ambiguous for an agent acting on it, without losing detail (no brevity-bias collapse)? | Research-backed (context-collapse / brevity bias arXiv:2510.04618) |
| `regression_risk` | 0.20 | Does the candidate avoid introducing contradictions or removing a rule this task relied on? | Local Canon (AGENTS.md deletion-budget philosophy) |

Weights sum to **1.0** (enforced by `Rubric` validation).

## Machine form (parsed by the gate)

```json
{
  "dimensions": [
    {"name": "friction_reduction", "weight": 0.35, "source_label": "Local Canon (friction taxonomy)", "scale": "[-1,1] candidate-vs-baseline"},
    {"name": "ac_coverage",        "weight": 0.25, "source_label": "Research-backed (arXiv:2306.05685)", "scale": "[-1,1] candidate-vs-baseline"},
    {"name": "instruction_clarity","weight": 0.20, "source_label": "Research-backed (arXiv:2510.04618)", "scale": "[-1,1] candidate-vs-baseline"},
    {"name": "regression_risk",    "weight": 0.20, "source_label": "Local Canon (deletion budget)", "scale": "[-1,1] candidate-vs-baseline"}
  ]
}
```

## Customizing

- Re-weight or add dimensions, but **weights must sum to ~1.0** and **every dimension needs a valid source label** (`Spec` | `Local Canon` | `Research-backed` | `Human-approved`).
- The accept-margin ε and the minimum sample-size floor `N_min` are **separate** tunable gate constants (Open Question Q4), not rubric fields.
