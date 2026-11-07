# Fleet MVP: decision

Build the minimal hub, as ruled by the human on 2026-11-03: "All 3 recommendations are accepted, proceed
with create plan".

- D-1, D-2 and D-3 are recorded in `docs/proposals/2026-11-03-fleet-mvp-outline.md` §5.
- The plan's Decision Log carries them forward, with every refinement made while planning:
  `docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md`.

Adopting Dobby or NATS, and using ssh, were rejected in outline D-1. Nothing read in P0 changes that.
Dobby's dependency list makes the case against adopting it stronger, because members would need all
of those dependencies installed.
