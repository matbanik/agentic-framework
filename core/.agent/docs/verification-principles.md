# Verification Principles

> **What this file is.** Fifteen rules about when a check is evidence and when it only
> looks like evidence. Every one was extracted from a gate that reported success while the
> thing it guarded was broken — so each entry names the failure, not just the rule. Read it
> when you are *writing* a gate, *reviewing* someone else's, or deciding whether a green
> result means anything.
>
> **What this file is not.** A testing style guide, a checklist to paste into a plan, or a
> substitute for `GUARDRAILS.md`. GUARDRAILS says what you must not do; this says how to
> tell whether your evidence that you didn't is real.

**The numbering is non-contiguous on purpose.** These are V1–V5, V13, V25, V30–V32, and
V41–V45, carried over from a longer internal register with their original numbers intact.
The gaps are principles that were too specific to one codebase to be worth porting. Keeping
the numbers stable means a citation like "V4" means the same thing here as it did there, and
that older review comments referring to a number still resolve. **Do not renumber.** If you
add one, take the next free number and leave the gaps alone.

Two of these are load-bearing elsewhere in this package: **V4** is cited by
`GUARDRAILS.md` SIGN 1 (the read-only plan-local verifier carve-out), and **V31** is cited
by `tools/Invoke-CodexDispatch.ps1` and pinned by a regression test in
`tools/tests/Test-GetPhysicalPath.ps1`. Changing the meaning of either breaks a control.

---

## A. What counts as evidence

### V1 — Assert the value, not a proxy for it

Cardinality is not content. `COUNT(*)` matching before and after says nothing about whether
the rows are the same rows, or whether every field survived. A checksum over the wrong
column set, a row count, a file count, an exit code, a "no errors logged" — each is a
*correlate* of correctness that a broken operation can satisfy.

**The failure:** reviewers repeatedly accepted a row count as "the data is intact" across a
migration that silently blanked a column. The count was right the whole time.

**How to apply:** name the value the operation is supposed to produce, and assert *that*. If
asserting it directly is expensive, say in the plan that you are asserting a proxy and what
the proxy cannot catch. A documented proxy is a known gap; an undocumented one is a false
pass.

### V2 — Observe the operation, not the artifact

An artifact's existence rarely proves how it came to exist. A `prove-absent → assert-exists`
sequence is satisfied by anything that puts the name there — including a command that merely
re-labels something that already existed, or a retry that succeeded for an unrelated reason.

**The failure:** a gate written as "prove the image is absent, run the build, assert the
image exists" passed when the build had not run at all: a tag operation had created the name.

**How to apply:** assert on the operation's own output — its exit status *and* a
distinguishing fact only that operation could have produced (a fresh timestamp, a content
hash, a log line with the input's identity in it). "The file is there" is the weakest
possible form of "the thing ran".

### V3 — Assert *which* clause rejected, and run positives beside negatives

A non-zero exit tells you something refused, not that the thing you were testing refused.
A decoy that is rejected by an unrelated earlier validation looks exactly like a decoy that
was caught by the rule you are trying to prove.

**The failure:** a suite of negative fixtures all "worked" — exit code 1 every time — while
the specific clause under test was unreachable. A malformed field was tripping an earlier
parse check.

**How to apply:** assert on the identifying detail of the refusal (the error code, the
message, the failing field name), never just on non-zero. And always pair a negative arm
with a positive one that must pass: a gate that rejects everything is as broken as a gate
that rejects nothing, and only the paired arms tell them apart.

### V13 — A fluent answer is not evidence the tool ran

A model asked to inspect something will produce a plausible, well-organized, specific-looking
report whether or not its read succeeded. Fluency is generated at the same cost either way.

**The failure:** a dispatched reviewer returned a detailed critique of a file it had been
unable to open — the sandbox had denied the read, the CLI reported the denial on a stream
nobody captured, and the process **exited 0**. Every subsequent step treated the critique as
grounded.

**How to apply:** require the dispatched process to emit a machine-checkable receipt of the
read itself — a hash, a line count, a quoted anchor line — and check it in the caller, not
in the prompt. Treat exit 0 from a wrapper as "the wrapper finished", never as "the work
happened". See `.agent/skills/cli-dispatch/SKILL.md` for the receipt conventions this
package uses.

### V25 — A count is not a set

Three findings is not the same fact as three *distinct* findings, and "we fixed 3" is not
"the 3 we found are gone". Aggregates lose the identities you need in order to check
progress, and a loop that tracks totals will happily accept a fresh problem as evidence that
an old one was resolved.

**The failure:** a review loop counted blocking findings per round and cleared its counter
each round. The same defect recurred four times under four different descriptions, and no
round ever saw a repeat, because nothing compared identities.

**How to apply:** persist identities, not tallies. When a threshold matters, key it on
something stable enough to match across rounds (see V41).

---

## B. What counts as a gate

### V4 — A gate must be able to fail

A check that cannot produce a failing result is not a control. `echo "[OK] validated"` is
the pure form, but the common forms are subtler: a script whose only failure path is an
unhandled exception, a grep whose pattern cannot match its own fixture, a validation row in
a task contract that no command implements, a step whose non-zero exit is swallowed by a
`|| true` three lines later.

**The failure:** validation rows in task contracts were routinely marked complete on the
strength of commands that had no failing branch at all. Nobody had run them expecting a
refusal, so nobody noticed.

**How to apply:** before you trust a new gate, **make it fail on purpose once**, and keep
that arm. A self-test that constructs a violating input and asserts the gate rejects it is
the cheapest possible insurance, and it is the only thing that distinguishes a gate from a
decoration. This package's own reference and prose-name gates each ship such arms — including
a *negative* arm that must pass, because a gate that fails everything is equally broken.

`GUARDRAILS.md` SIGN 1 depends on this principle for its read-only-verifier carve-out:
running a plan-local verifier during planning is not entering execution, it is how a plan
proves its gates can fail. The corollary there is the important half — **if a verifier cannot
be run, delete it rather than strengthening its wording.** An unrunnable check is a zero
control that reads like a control, and prose refinement makes it look safer while proving
nothing.

### V5 — Zero matches is evidence only if the detector was proven able to match

"The scan found nothing" and "the scan did not run" produce identical output. So do "the
pattern is correct and the tree is clean" and "the pattern has a typo". So do "the tool is
installed" and "the tool is missing and the shell reported not-found on a discarded stream".

**The failure:** a repeated one. A search tool absent from `PATH`; a skip-list so broad it
excluded the files under audit; a nested template whose placeholders were never substituted,
so the detector searched for a literal token that could not appear. Each time, the reported
result was zero findings, and zero findings was read as clean.

**How to apply:** every detector runs against a fixture containing something it **must**
flag, in the same invocation, and a detector that does not flag its fixture fails the run.
Report the two numbers separately — "0 findings, 1 fixture matched" — so a reader can see
that the instrument was alive. This is also why a missing tool must exit with a *distinct*
status from a clean scan: see V31.

### V30 — The third instance of one defect class means the defect is the mechanism

One occurrence is a bug. Two is a coincidence worth noting. Three of the same *class* means
the thing generating them is the defect, and fixing the third instance is the wrong repair.

**The failure:** the same category of gate-bypass was patched individually eight times across
a review loop before anyone treated the pattern as the finding. The eight patches all held;
the ninth instance arrived anyway.

**How to apply:** classify findings by mechanism as you record them, and let the third
instance of a mechanism escalate to "redesign the mechanism", not "fix the instance". This
only works if the count survives the round — which is V41.

---

## C. Fail closed

### V31 — Resolving an identity to nothing must fail closed

When a lookup, path resolution, name derivation, or ID generation yields empty, the empty
value must be an error. Empty string is the most dangerous value in a program because it is
falsy, concatenates silently, and reads as "no constraint" to almost every consumer.

**The failure:** on macOS, `/tmp` is a symlink whose target is *relative* (`private/tmp`).
Taking the parent of `/tmp` returns the empty string; joining onto empty produced a path that
did not exist; and the wrapper reported the result as "the prompt file does not exist" for a
file that was plainly there. The diagnosis cost hours because the error named the wrong
thing. Separately, a "unique name" helper that fell through to a constant produced identical
names for every caller, silently collapsing distinct records into one.

**How to apply:** check for empty at the point of resolution and throw there, with a message
naming *what* failed to resolve. Never let an empty identity travel. Two consequences worth
stating on their own:

- **A missing tool or unreachable dependency is its own exit status**, distinct from both
  success and a legitimate failure. "Could not check" is not "checked and clean". This
  package's shell tooling reserves a separate exit code for exactly this.
- **A fail-closed message must name the fix.** A gate that refuses without saying which
  variable to set or which file to create gets "fixed" by disabling the gate. That is not a
  hypothetical; it is the normal outcome.

Pinned by `tools/tests/Test-GetPhysicalPath.ps1`, whose second arm covers this rule. Run it
before trusting path resolution on macOS.

### V32 — Budget the hazard, not the evidence

Caps and quotas must fall on the thing you want less of. A limit on fixtures, test files,
assertions, or documentation is a limit on evidence, and it converts "add a test" into a
cost. People respond rationally and stop adding tests.

**The failure:** a ceiling on total fixture count, introduced to control review scope, was
dropped once it became clear it punished the behaviour it was meant to encourage. Meanwhile
the actual hazard — unreviewed production surface — was uncapped.

**How to apply:** cap the hazard (unreviewed change, unbounded rounds, unapproved
irreversible actions) and leave evidence unbounded. The corollary: **a fixture nothing runs
is not coverage.** Uncapped evidence only helps if it executes, so an orphaned fixture is
worse than no fixture — it inflates the apparent safety margin.

---

## D. Loops and recurrence

### V41 — Recurrence thresholds cannot live in prose; the count belongs on disk

"Escalate on the third occurrence" written in a document is not a threshold. Nobody is
counting, each round starts fresh, and the participant best placed to notice the recurrence
is the one whose work is being criticized.

**The failure:** this is the reason a review ledger had to exist at all. Every prose-level
recurrence rule in the register was violated before the count was persisted, and none
afterwards.

**How to apply:** if a rule says "the Nth time", something must write the previous N−1 to a
file that outlives the round, keyed by mechanism (V30) rather than by count (V25). If you
cannot persist it, the rule is advice, and it should be written as advice so nobody relies on
it as a control.

### V42 — Re-validate persisted records; a write path and read path tested apart will disagree

Serialization and deserialization drift toward each other's blind spots. A writer that emits
a new field and a reader with a strict allowlist are each individually correct and jointly
fatal.

**The failure:** a ledger's relief operation wrote a key its loader's schema allowlist did
not know. The write succeeded; every subsequent read refused the file; the loop was bricked
mid-review and the state was unrecoverable without hand-editing.

**How to apply:** one schema definition, shared by both paths — not two that agree today. Add
a round-trip test that writes every record variant and reads it back, and make schema
evolution a place where the reader is updated first. If the reader must reject unknown keys,
it has to say which key and which version wrote it.

### V43 — A loop bounded only by volume converges on its own instrumentation

Give a reviewer a round budget and no notion of subject, and the findings drift from the
deliverable toward the scaffolding: the review prompt's wording, the ledger's schema, the
receipt file's naming, the gate script's error strings. Each finding is real. None of them
are the work.

**The failure:** several late rounds of a review loop were spent entirely on the review
apparatus, while the artifact under review sat unchanged and approved-in-substance.

**How to apply:** classify each finding by subject — the deliverable, the committable
tooling, or the review scaffolding — and cap scaffolding findings separately and tightly. A
scaffolding finding in a late round is a signal the loop should end, not a reason to spend
another round.

---

## E. Measurements decay

### V44 — A measurement of something that moves must carry its observation date and a re-derive command

Branch tips, line numbers, token counts, latency bands, installed tool versions, model
behaviour, and "current" anything are observations with a decay date. Written without one,
they read as permanent properties and are trusted long after they stopped being true.

**The failure:** documentation throughout the source register quoted measured figures — file
line numbers, timing bands, context costs — with no date and no way to re-take the
measurement. Readers could neither trust them nor check them, so they did both by turns.

**How to apply:** write the number, the date it was observed, and the command that would
produce it again. `"~2,100 tokens (measured 2026-07-11; re-derive: <command>)"`. Then a
reader who finds 2,700 knows the measurement drifted rather than that the document is wrong
— and knows what to re-run. The word **"currently"** is the tell: if you are reaching for it,
you are recording a measurement without a date. Either date it or state the invariant instead
of the snapshot.

### V45 — Assert after the last mutator, including formatters and pre-commit fixers

Anything that can rewrite bytes must run *before* the assertion that depends on those bytes.
Tools configured as "checks" frequently mutate: formatters with a write mode, linters with
`--fix`, code generators that regenerate on the way past, pre-commit hooks that stage repairs
and then report success.

**The failure:** a content hash was taken, then a hook reformatted the file while "checking"
it, and the hash comparison failed at a point far from the cause. The hook's own output said
it had passed.

**How to apply:** order the pipeline so every mutator finishes before the first hash, diff, or
size assertion — and be suspicious of any step whose name says "check". This package's commit
scripts are a live example: the OpenAPI step *regenerates and re-stages* a spec file inside
what is nominally the test phase, so any assertion about the tree must come after step 4, not
before it.

---

## Using this in a review

Two questions cover most of the value:

1. **"What would make this check fail?"** If the answer is "nothing", or takes more than a
   sentence, you have found a V4 problem. Ask for the failing arm.
2. **"How do we know the instrument was alive?"** Applied to any zero result — zero findings,
   zero diffs, zero errors. That is V5, and it is the single highest-yield question to ask
   about a green run.

Then, in order of how often they catch something: is the assertion the value or a proxy (V1)?
Does exit 0 prove the work happened or that the wrapper finished (V2, V13)? Does anything
empty travel instead of failing (V31)? Is a "currently" or an undated number doing load-bearing
work (V44)?

**Citing these.** Write the number: "this is a V5 problem — the detector has no fixture."
The numbers exist so that a review comment can be short and still unambiguous, and so the
same objection raised twice is recognizably the same objection (V25, V30).
