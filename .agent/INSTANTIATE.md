# Instantiate a live registry home

This directory is a **template** of a model-capability registry home. It is a
sibling of `core/`, `scripts/`, and `README.md` in this package, analogous to a
drive-root `.agent/` on a machine that already has a live registry. It ships
**classes, not live snapshots**. Copying this folder into a project does not
give you bindings — you write those yourself, against the slugs your harnesses
actually accept.

`core/.agent/` remains the in-package instruction copy. Do not treat it as the
registry home and do not delete it.

## 1. Choose the live home

The resolver locates the compiled registry in this order (S2):

1. `AGENT_MODEL_REGISTRY` — a path to the compiled JSON **file**
2. `P:/.agent/model-registry.json` (drive-root convention)
3. `%USERPROFILE%/.agent/model-registry.json` (machines without `P:\`)

`AGENT_MODEL_REGISTRY` must name the file, not the directory holding it. A
directory passes the existence test, so the resolver returns it and the read
then fails with a `PermissionError` rather than a registry error. (The thin
wrappers in step 3 accept a directory when *locating the tools*; that is a
different lookup and does not extend to loading a registry.)

Pick **one** live home:

- **Drive-root** — `P:/.agent/` (or the equivalent on your drive) when several
  repos on the same machine should share one catalog and one bump.
- **workspace-root** — `<project>/.agent/` only if this project owns the
  catalog. Project overlays still live at `<project>/.agent/model-registry.local.yaml`
  even when the global home is on the drive.

Do not instantiate into `core/.agent/`. That tree is instruction content, and
this package's refresh cycle is delete-and-recopy: pin state that lands there
ships to the next adopter.

## 2. Copy the template, then fill it

```
schema/model-registry.v1.schema.json   →  <home>/schema/model-registry.v1.schema.json
model-registry.template.yaml           →  <home>/model-registry.yaml
docs/model-classes.md                  →  <home>/docs/model-classes.md
tools/ModelRegistry.psm1               →  <home>/tools/ModelRegistry.psm1
tools/resolve_model.py                 →  see step 3
tools/check_model_slugs.py             →  see step 3
INSTANTIATE.md                         →  keep as the how-to, or drop it
```

Rename is load-bearing: the live file is `model-registry.yaml`. The template
name exists so a checker can skip registry-shaped files without treating an
unfilled template as a live catalog.

Edit `<home>/model-registry.yaml`:

1. **`catalog`** — one entry per snapshot your harnesses accept. Required fields
   are in the schema (`vendor`, `harness_ids`, `price_band`, `capabilities`).
   Absolute `sources[]` URLs. Catalog ids must not contain `latest`.
2. **`classes.*.bindings`** — for each class you will dispatch, map each harness
   to a catalog id. Leave a class unbound on a harness you do not run; the
   resolver will say `unresolvable_on_harness` rather than substituting.
3. **`forbid`** — once the architecture-reserved snapshot is in the catalog, add
   its catalog id to `coordinator` and `builder` `contract.forbid`. The template
   omits `forbid` so it ships zero snapshot ids.
4. **`eval_gate`** — optional. Point at *your* proof, not another project's.
5. **`pins`** — add a `never_bump: true` pin only when you have a recorded
   baseline that must not move. The template ships `pins: {}`.
6. **`retired_slugs`** — dead pins you want the checker to fail on. Empty until
   you have one.
7. **`raw_slug_allowlist`** — history paths, not instruction. Add your registry
   home if the checker would otherwise scan your CHANGELOG.

The unfilled template does **not** pass schema validation: `catalog` requires
at least one entry. Fill, then validate.

## 3. Resolver and checker

`tools/ModelRegistry.psm1` in this template is the slug-free PowerShell
implementation (it reads compiled JSON; it does not embed snapshots). Copy it
as-is.

`tools/resolve_model.py` and `tools/check_model_slugs.py` here are **thin
wrappers**. The live implementations carry catalog examples and day-one binding
tables, and a delete-and-recopy of those files would ship someone else's pins
inside a docstring. After copy:

- If a live registry home already exists in the S2 order, the wrappers forward
  to it.
- If this *is* your live home, replace both wrappers with the real tools from a
  working registry (the files named the same under that home's `tools/`).

Do not paste snapshot ids into the wrappers to "make them self-contained."

## 4. Compile, then check

From the live home:

```powershell
python tools/resolve_model.py validate --write-compiled
python tools/resolve_model.py sync <your-project-root>
python tools/check_model_slugs.py --project <your-project-root> --enforce
```

`validate --write-compiled` emits `model-registry.json`. PowerShell
(`ConvertFrom-Json`) and Python (`json`) both read that file; do not hand-edit
it. `--check-compiled` fails if YAML and JSON drift.

**Run `sync` before you enforce, and run it after you have copied `core/` into
place — not against the staging tree.** The four AUTOGEN-marked agent
definitions under `core/.cursor/agents/` and `core/.claude/agents/` ship stamped
with the registry SHA of the machine that packaged them. Yours hashes
differently the moment you fill in your own catalog and bindings, so those four
files report `autogen_drift` until they are regenerated. That is an expected
consequence of the stamp, not a fault in your registry.

`sync` looks for `.cursor/agents/*.md` and `.claude/agents/*.md` **relative to
the root you give it**, so it only finds those files once they sit at your repo
root with `{{PROJECT_NAME}}` substituted — the copy step in
`ADOPTION-GUIDE.md`. In that layout `sync` rewrites all four and the drift count
goes to zero. Pointed at the un-copied package, `sync` reports `0 written, 0
skipped` and the drift survives — at `core/…` depth those files are never
discovered as candidates in the first place, so they are not "skipped" so much
as invisible to it.

So: copy `core/` into place, compile your registry, `sync`, then enforce. Do not
hand-edit the SHA to silence the warning — the stamp is what makes a stale
generated file detectable, so overwriting it by hand removes the only signal
that the file no longer matches the registry it claims.

The checker reports; it never rewrites. A slug in a live instruction file is a
Tier-1 failure. Versioned prose names warn and do not change the exit code.

## 5. Overlay (optional)

A project may add `.agent/model-registry.local.yaml` with `extends: global`.
It may add classes, tighten constraints, and add pins. It may not loosen a
global contract, redefine a slug, or introduce a slug the catalog does not
know. Tighten under `constraints:`, never under `contract:` — redefining a
binding is `overlay_redefines_binding`, not a tightening.

An overlay has two files, and only one of them is read at dispatch time:

| File | Written by | Read by |
|---|---|---|
| `model-registry.local.yaml` | you | `resolve_model.py`, the checker |
| `model-registry.local.json` | `sync` / `validate --overlay` | `ModelRegistry.psm1` |

The PowerShell leg has no YAML parser and no schema validator, so it reads the
compiled sibling and nothing else. `sync` stamps that sibling with the SHA of
the registry it was validated against, and the module refuses an overlay whose
stamp names a different registry (`overlay_not_validated`) or that was never
compiled at all (`overlay_not_compiled`). Both refusals are the point: an
overlay nothing validated is exactly the case the guard exists for.

```powershell
python tools/resolve_model.py validate --overlay <project>/.agent/model-registry.local.yaml --strict
python tools/resolve_model.py sync <project>          # compiles + stamps the sibling
python tools/check_model_slugs.py --project <project> --enforce
```

Editing the YAML and not re-running `sync` leaves the compiled sibling stale.
The checker reports that as `overlay_compiled_drift`; do not hand-edit the JSON
to silence it.

Every resolution that should honour the overlay must name the project —
`--project <project>` for the Python tool, `-Project <project>` for the module.
Both dispatch wrappers pass `{{PROJECT_ROOT}}` for you. A resolution without it
answers with global policy and no error, which is the failure mode worth
knowing about: nothing looks wrong.

## 6. Bumping a binding

Standing the registry up is a one-time act; bumping is the thing you will do
repeatedly, and it is the reason the indirection exists. A bump is an edit to
**one binding in your live registry**, plus a recompile and a sync. No caller
changes. If a bump seems to require editing an instruction file, that file has a
hardcoded slug — fix the file to resolve a class instead.

`bump_gate` in the template is `human`. Writing the binding and committing it are
both the human's; every other step below is delegable to an agent.

1. **Shortlist.** `resolve_model.py candidates <class> --harness <harness>` names
   the current binding and the newer catalog entries that satisfy the class
   contract. `--show-rejected` explains each exclusion, which is usually the more
   useful half — a snapshot rejected on `price_ceiling_band` or a missing
   capability is your contract working.
2. **Add the snapshot to `catalog` if it is absent, then compile.** Required:
   `vendor`, `harness_ids`, `price_band`, `capabilities`. Record `released`,
   `efforts`, `context`, `price_per_mtok`, and absolute `sources[]` URLs too — a
   price or a context cliff nobody can re-check will rot. Then run
   `resolve_model.py validate --strict --write-compiled`: the next step resolves
   its target against the **compiled** registry, so an entry that exists only in
   the YAML fails the rehearsal with `unknown_slug`. Adding a catalog entry is not
   a bump — nothing resolves differently until a binding moves — but it is a
   durable edit to both files, not a dry run.
3. **Rehearse.** `resolve_model.py rehearse-bump --class <class> --harness
   <harness> --to <catalog-id> --root <project> --report-blast-radius` moves the
   binding, syncs, hashes what changed, and reverts. It shows which AUTOGEN-marked
   files the real bump would rewrite. `--report-blast-radius` fails if a path
   outside the allowed set moved; the allowed set is the registry YAML, the
   compiled JSON, the AUTOGEN-marked files and any overlay artifacts `sync`
   discovers, all of which are supposed to change. The wider comparison covers
   files already tracked in git, so it is a strong signal rather than a proof.
   Repeat `--root` for each of your projects: the bare `--snapshot-autogen` flag
   falls back to the reference implementation's own hardcoded project list, which
   is not yours. Rehearsal refuses to run on a tree whose snapshot paths already
   differ from HEAD, because it could not then prove it restored them — and step 2
   just put you in that state, since adding the catalog entry and compiling leaves
   both registry files modified. A rehearsal straight afterwards stops with
   `snapshot_dirty`. Inspect the diff, confirm it is your catalog entry and nothing
   else, then pass `--ignore-unrelated-dirty`, which restores the bytes present at
   start rather than HEAD's. Use that flag because you made the dirt and looked at
   it, never reflexively.
4. **Run the class's `eval_gate`,** if it declares one, and keep the output — but
   not against the rehearsal. **Step 3 reverts before it returns**, so the old
   binding is live again by the time you read its report; running the gate here
   unmodified measures the old configuration while appearing to measure the new
   one. Build the candidate explicitly: copy your whole registry home — `tools/`
   and `schema/` included — to a scratch path that **does not already exist**, edit
   the one binding in the copy, compile with **the copy's own** `resolve_model.py`,
   and point `AGENT_MODEL_REGISTRY` at the resulting JSON for the duration of the
   gate. Two things are load-bearing here. The destination must be fresh: a
   recursive copy onto an existing directory nests the home *inside* it, and the
   compile on the next line then reads the stale top-level copy, so the gate
   silently measures your previous candidate. And the copy must include the script,
   because `--write-compiled` writes `model-registry.json` next to the script that
   runs, not next to the YAML that `--registry` names — running your live home's
   script against a scratch YAML would overwrite your live compiled artifact.
   Record the candidate's hash next to the gate output, and clear the environment
   variable afterwards.

   Classify the gate's whole invocation chain, not just its final command —
   resolution itself can inspect provenance. The PowerShell resolver validates a
   project's overlay against the registry in use and fails with
   `overlay_not_validated` when the two disagree, so a gate that merely *resolves* a
   model through a project that has an overlay already fails against a candidate,
   before any model runs. A candidate serves only a gate whose entire chain —
   resolver, wrapper, command — reads the registry and nothing stamped against it.
   Anything else needs one of two routes: copy the projects the gate touches
   alongside the candidate and `sync` those copies against it, or defer the gate
   until after step 7. After step *7*, not step 6: step 6 only compiles, and a
   project's overlay and AUTOGEN files stay stale until `sync` runs.

   If a deferred gate fails, roll back every artifact, not just the binding.
   Restoring the registry source alone leaves the compiled file — and every project
   you synced — still serving the rejected candidate, and the checker reports drift
   until you finish. Restore the source, recompile (step 6), re-sync every root you
   synced (step 7), then re-run the enforce command *and* a resolve, to confirm the
   old binding is what actually comes back.

   A declared `eval_gate` is a claim, not a guarantee: run it once against the
   *current* binding before you trust its verdict on a candidate — and run it
   **before step 2**, not here. Step 2 adds the catalog entry and recompiles, moving
   the registry hash while every project's overlay and generated files still record
   the old one; from that point a provenance-sensitive gate fails its precondition on
   the *current* binding too, and a clean step-3 rehearsal restores that
   unsynchronized state rather than a healthy one. Capture the baseline before you
   touch anything, or evaluate it against scratch copies you have explicitly synced,
   and keep that evidence separate from the candidate's.

   A failure is not by itself proof the reference is stale. Diagnose it, keeping two
   questions apart: *what must be fixed*, and *whether the bump has proof*. A
   parameter-binding rejection or an unresolvable path names an invalid *reference*;
   a test that runs and fails names a *defect* in the code under test; a missing
   interpreter, module, or credential names your *environment*; a provenance refusal
   names an unmet *precondition*, which is none of the other three. Only the first is
   fixed by correcting the reference — but **any** gate that did not run and pass
   leaves the bump without automated proof, whatever the cause, and these four are
   the common cases rather than an exhaustive list. A class with no gate at all has
   no proof either — a reason to be more careful, and to say so in the changelog
   rather than leave the absence implicit.
5. **Edit the binding** and bump `updated:`. An agent may prepare the diff; a human
   applies it.
6. **Compile.** `resolve_model.py validate --strict --write-compiled`. `--strict`
   adds the cross-reference checks a JSON Schema cannot express: forbidden ids,
   retired slugs, unresolvable harnesses. This form validates the **global**
   registry only — overlays are checked by `validate --overlay <file>`, or as a
   side effect of `sync` discovering a project's overlay in step 7.
7. **Sync, then enforce.** `resolve_model.py sync <your project roots>` restamps
   the AUTOGEN files with the new registry SHA; then
   `check_model_slugs.py --project <project> --enforce --per-project-exit`,
   repeating `--project` for each of your roots. Prefer that to `--all-projects`,
   which expands to the reference implementation's hardcoded list rather than the
   roots you just synced. Sync first — an unsynced AUTOGEN file correctly reports
   `autogen_drift`. The count that must be zero is **Tier-1 failures**; Tier-2
   prose names warn and never change the exit code. `sync` discovers agent
   definitions at `<root>/.cursor/agents/` and `<root>/.claude/agents/` only, so a
   repo that keeps them nested deeper is not a sync target and reports nothing
   written — while the checker still scans those depths. An AUTOGEN stamp records not
   the registry file's own hash but the SHA the compiled artifact *would* carry if
   generated from the current source, so a comment or formatting edit drifts
   nothing while any semantic change drifts every stamped file. Such files then
   drift on each bump with no command in this loop able to refresh them safely —
   pointing `sync` at the nested directory does reach them, but it also writes live
   snapshot ids into files that may be templates. Either keep AUTOGEN-marked files
   where `sync` can find them, or accept that they need their own refresh procedure
   and say so where someone will read it. When you accept outstanding drift, read
   the whole report rather than the headline counters. A zero Tier-1 count sits
   happily beside a malformed marker, so require `errors` 0, require the drift list
   to hold *exactly* the files you expected — no more and no fewer, since a removed
   marker shows up as a missing entry rather than an error — each with the
   stale-stamp code. Record that expected file set somewhere a reader can check it,
   and reconcile it in the same change whenever you deliberately add or remove a
   stamped file; otherwise no one can tell an approved inventory change from a lost
   marker. Even then you have not established that the files are intact: the checker
   reads the stamp, not the document around it, so a file whose frontmatter has
   become invalid still reports an ordinary stale stamp. Diff the affected files
   against a reviewed baseline before concluding they are merely stale.

   The opt-out roster needs the same treatment, and checking it for *additions* is
   not enough. An inline exemption suppresses every slug hit on its line, and
   `--print-optouts` shows only `path:line: token — reason`: no history, and
   suppressed hits rather than markers. An existing exemption can therefore be
   repurposed — its line rewritten from documentation into live routing instructions,
   keeping the same tokens, line number and reason — with every count and every
   printed roster entry unchanged. Save the JSON report before and after and diff it,
   and treat added, removed and *changed* exemptions alike. But do not stop at that
   diff: the report stores only the first 200 stripped characters of each line, so on
   a long line — a wide table row, say — a rewrite past that cutoff leaves the saved
   JSON byte-identical. The check that actually sees the whole line is the last one:
   for every exemption that survives, read its complete suppressed source line against
   your reviewed baseline and confirm the stated reason still describes what is
   written there.
8. **Retire the old slug** if it is now bound nowhere and should never return: add
   it to `retired_slugs` with a reason, then repeat steps 6–7. Tier 1 then fails on
   it anywhere in a live surface, which is how a rotted pin gets caught the next
   time someone copies an old command out of a handoff. Leave it alone if another
   harness still binds it — `retired_slugs` means dead, not superseded here.
9. **Record it, then a human commits.** Keep a changelog in your registry home:
   date, class(es) bumped, old → new, the registry SHA-256, the eval-gate output
   pasted verbatim with the candidate hash it ran against, and the allow-list count
   from step 7.

That last count is worth defining once, because it is the number people misread.
Allow-listed hits are slugs the checker found and deliberately did not fail on,
because they sit in records rather than live routing — plans, handoffs,
reflections, metrics, verdicts, fixtures, archives, the registry itself, and the
compiled artifacts it generates.

A change in the count is a **trigger to investigate, not a diagnosis**. It moves
when history grows, when a generated or compiled artifact is rewritten, when the
scan scope or token set changes, and when an allow-list pattern widens. The total
alone cannot tell you which, and none of those is safe to assume harmless — a
narrowed scan or a token set that stopped matching a vendor's new id shape *lowers*
the count while hiding live Tier-1 hits, which is the same defect as a widened
allow-list wearing a reassuring number. Diff the hit *identities* and their
exemption patterns — added and removed, not just the sum — against
`raw_slug_allowlist` and every `raw_slug_allowlist_extra`, and confirm the scan
still covers the files and token shapes you believe it does. Never widen the
allow-list to clear a Tier-1 failure: a live instruction file naming a slug is the
defect the checker exists to find.

`resolve_model.py equivalence` is not part of this loop. It checks a fixed table of
day-one cases, comparing the slug the resolver emits today against the slug your
pre-migration files named. Because it compares emitted *strings* rather than
catalog-binding identity, it is not a bump check in either direction — a bump onto a
different catalog entry that happens to emit the same harness slug still matches
every case. Run it when you suspect drift from what callers historically got.

## 7. What not to do

- Do not copy another machine's `model-registry.yaml` into this package and
  ship it. That is the failure human decision Q1 exists to prevent.
- Do not add model tokens to `scripts/placeholders.py`. Class names are stable
  across adopters; they need no substitution.
- Do not recopy this package to bump a model. A bump is a live-registry edit
  plus `resolve sync` for AUTOGEN-marked agent-definition files.
