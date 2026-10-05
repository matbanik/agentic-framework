# Build Plan Patterns

> **Everything in this file is illustrative.** Nothing here is a requirement, a default, or a
> checklist. The requirements are in `.agent/workflows/build-plan-authoring.md`; this file shows
> how plans have been cut for different architectures so you can test your own cut against them.
>
> **Read it at Step 5 of that workflow, after you have derived your own phases.** If you are
> reading it before you have a block list, a dependency rule, and a candidate phase list of your
> own, stop and go back. Agents reliably copy the nearest example; a copied plan describes the
> example's system.

## 1. What carries over between projects

Across the plans this framework was extracted from, and the published practice in §6, three things
held regardless of architecture:

- **A slim hub, detailed spokes.** One short file states the architecture and indexes everything;
  the detail lives in one file per phase. Readers and agents load only the phase they are working on.
- **Dependency order as the build order.** Whatever the blocks are, the thing others stand on is
  specified and built first.
- **Status is generated.** Progress is rendered from one machine-readable source into the hub. It
  is never typed into a spec.

Phase names, phase counts, and which optional files exist did **not** carry over.

## 2. Phase decompositions, by architecture

Each sketch is a shape with the reasoning behind it. The names are placeholders for whatever your
project calls its own blocks.

### A. Layered application (ports and adapters, clean, onion)

Rule: inner layers never import outer ones.

```
01 core model        → 02 persistence → 03 use cases → 04 API → 05 UI → 06 packaging
07+ one phase per feature, each walking core → persistence → use cases → API → UI
```

Why this cut: the early layers are shared by every feature and are testable in isolation, so they
are built as foundation phases. Once one path reaches the UI, each new feature is a slice phase
that touches every layer in a single spec. The slice specs outnumber the layer specs many times
over in a mature plan.

Where it goes wrong: building every layer "complete" before anything runs end to end. The fix was
keeping the first pass through each layer thin.

### B. Data or processing pipeline

Rule: a stage reads only the previous stage's output contract.

```
01 contracts and one sample dataset → 02 thin run through every stage for one source
03+ one phase per source or per output product
0Nx hardening sub-phases (backfill, monitoring, cost) attached to the stage they harden
```

Why this cut: stage contracts are the thing everything depends on, so they come first. There is
almost no foundation beyond that; value arrives per source, so phases are slices from phase 2.

### C. Library, SDK, or CLI

Rule: the public surface depends on the internals; internals never depend on the surface.

```
01 public surface and error model (signatures, no behaviour) → 02 the one core capability
03+ one phase per capability → final: packaging, docs, compatibility policy
```

Why this cut: the public surface is the one-way door, so it is specified and reviewed before any
behaviour. Phases after that are slices by capability.

### D. Several services or a client plus a backend

Rule: services talk only through published interfaces.

```
01 interface contracts and a stub of each service → 02 one user journey across all services
03+ one phase per journey, or per service where a service is independently valuable
```

Why this cut: integration is the main risk, so the first real phase is a journey that crosses
every boundary, with stubs standing in for depth.

### E. Existing system (brownfield)

Rule: whatever the code enforces today, written down.

```
00 overview describing the system as it is → phases are changes, not components:
01 characterisation tests around the area to change → 02 first change → 03 next change …
```

Why this cut: re-specifying a working system produces a document nobody trusts. The plan records
only the deltas, each phase stating what it adds, modifies, or removes.

### F. Non-code project (documentation set, process or workflow package, research programme)

Rule: stated in terms of documents or artefacts — for example, "procedures cite the policy, never
the other way round".

```
01 vocabulary and governing rules → 02 one procedure end to end, including its evidence
03+ one phase per procedure or deliverable → final: adoption and maintenance path
```

Why this cut: the "blocks" are documents and the "tests" are review evidence, but the same
question orders the work: what does everything else cite?

### Reading across A–F

The same three moves appear with different weights: settle what everything depends on, prove one
thin path through all the blocks, then deliver by capability. Your project decides how much of
each. A plan with no foundation phases is normal. So is a plan with no slices, when the product is
a platform whose layers are themselves the deliverables.

## 3. Optional phase-spec sections, and the need each one served

Add a section when its need is present in the phase you are writing. Each was introduced in a real
plan in response to a specific failure.

| Section | The need it served |
|---------|-------------------|
| Product contract (user-visible behaviour, states, errors) | Builders implemented the mechanism but guessed the behaviour |
| Locked design decisions (decision · source label · why) | The same choice was reopened in every session |
| Open decisions, each with a recommended default | Work stalled waiting for answers that had an obvious default |
| Boundary input contract (every external input, its validation, its failure mode) | Validation was added at one entry point and missed at another |
| Cross-block wiring checklist | Each block's work was done and the feature still was not connected |
| Findings → work-unit traceability | Review findings were lost between the review and the plan |
| Test plan (levels, fixtures, what must fail before it passes) | Tests were written after the code and proved nothing |
| Execution order / session hint | The spec's reading order was not a workable build order |
| Deferred remainder, with reasons and destinations | Cut scope silently disappeared |
| "Must not" list | A builder helpfully broadened the change |
| Sources | A criterion's authority could not be traced |
| Dated addenda and supersession notes | A rewritten spec broke references from plans already executed against it |

## 4. Optional reference files

Only `build-priority-matrix.md` is required. The rest are a menu.

| File | Worth having when |
|------|-------------------|
| `00-overview.md` | There are more than a few phases and newcomers need the map before any single spec |
| Domain / data model reference | Several phases share entities and keep redefining them |
| Input index, output index | The product has many user or machine inputs and each needs a consistent validation story |
| Interface or action index (API routes, commands, UI actions, tools) | The same capability is exposed through more than one surface and they drift |
| Dependency manifest | Third-party dependencies are introduced by phase and install order matters |
| Testing strategy | Test levels, fixtures, or environments are shared across phases |
| Risk or friction inventory (a pre-mortem) | The project has known hard parts worth naming before they are hit |

A reference file that no phase spec links to is a candidate for deletion.

## 5. Hub variations

Two hubs built on the same framework ended up differing, and both worked:

- One led with a **design thesis** and a **locked decisions** table (topic · decision · owning
  phase), tracked **open tensions between sources**, and listed each inspiration file with the
  intent still owed to it. It suited a project whose main risk was scope and product judgement.
- The other led with a **quick start**, a table of **canonical ports and addresses**, and the
  **validation command**. It suited a project with many moving runtime parts and many contributors.

Both kept the hub short by moving per-unit detail out to generated registries and phase specs.

## 6. Sources

Research-backed claims in this file and in the workflow trace to these. Labels follow the
framework's source taxonomy; the takeaway is the part that was used.

| Source | Type | Takeaway used |
|--------|------|---------------|
| arc42 documentation, <https://arc42.org/documentation>; INNOQ introduction, <https://www.innoq.com/en/blog/2022/08/brief-introduction-to-arc42> | template standard | A fixed place for each kind of information; every section optional; an empty compartment is fine |
| M. Hompus, arc42 practical series, <https://blog.hompus.nl/2026/02/01/arc42-practical-series> | practitioner | "Write the smallest amount of documentation that prevents expensive misunderstandings"; start with goals, constraints, context |
| A. Osmani, "How to write a good spec for AI agents", <https://addyosmani.com/blog/good-spec> | practitioner | Just enough spec; split large work; explicit boundaries; feed the agent one piece at a time |
| SurePrompts, "Spec-Driven AI Coding", <https://sureprompts.com/blog/spec-driven-ai-coding> | practitioner | Irreducible core of a spec: goal, verifiable acceptance criteria, out of scope |
| Spec Kit / OpenSpec / BMAD comparisons, <https://aicodingpatterns.com/en/patterns/openspec-vs-spec-kit-vs-bmad>, <https://intent-driven.dev/knowledge/spec-kit-vs-openspec>, <https://ranthebuilder.cloud/blog/i-tested-three-spec-driven-ai-tools-here-s-my-honest-take> | tool comparison | Project-wide non-negotiables inherited by every spec; mark unknowns instead of guessing; delta specs for existing systems; ceremony a team will not sustain is worth less than a file it keeps current |
| M. Jovanović, "Vertical Slice Architecture vs Clean Architecture", <https://milanjovanovic.tech/blog/vertical-slice-vs-clean-architecture> | practitioner | Layers and slices are a fit question; hybrids are common |
| Data Science PM, "Vertical vs Horizontal Slicing", <https://www.datascience-pm.com/vertical-vs-horizontal-slicing-data-science-deliverables/> | practitioner | A thin horizontal base, then vertical slices; technical dependencies set the order |
| "The Few-shot Dilemma: Over-prompting Large Language Models", <https://arxiv.org/pdf/2509.13196> | research paper | More examples can degrade results; this is why §2 is short, varied, and read late |
| AI Tools Guidebook, "Too Many Examples Overwhelm the Prompt", <https://aitoolsguidebook.com/en/articles/too-many-examples-overwhelm/> | practitioner | Models imitate the surface of the nearest example; state the task first, keep examples for shape |
