#!/usr/bin/env python3
"""review_ledger.py -- persistent state for a bounded independent-review loop.

Why this exists
---------------
A recurrence threshold written in prose is not a threshold (verification-principles
V41). "Escalate on the third occurrence of this class of problem" is unenforceable
when nobody is counting, every round starts fresh, and the participant best placed to
notice the recurrence is the one whose work is being criticized. So the count lives on
disk, keyed by *mechanism* rather than kept as a tally (V25/V30), and the decision to
permit another round is made by this tool instead of by the agent that wants one.

Four stops, each with its own escape hatch
------------------------------------------
1. **Round budget** -- plan 3, execution 6, discovery 2. Relieved by ``grant``: a named
   human, a rationale of real length, one extra round.
2. **Mechanism-class stop** -- three *blocking* ``control-defeat`` findings sharing one
   ``mechanism`` slug means the mechanism is the defect, not the instance (V30).
   Relieved by ``relieve`` per mechanism -- deliberately NOT by raising the round
   budget, because bumping a global limit is how this stop gets defeated.
3. **Scaffolding stop** -- a loop bounded only by volume converges on its own
   instrumentation (V43). Blocking ``review-scaffolding`` findings are capped
   separately and tightly; hitting the cap ends the loop rather than buying a round.
4. **Instrument-drift stop** -- if the verdict schema changes mid-loop, earlier rounds
   were judged against different rules and the counts are not comparable. Refuse and
   make a human look.

Output contract
---------------
The **first line** of stdout is always one of ``OK:``, ``REFUSE:``, ``FAIL-CLOSED:``,
``USAGE:``, so a caller can branch on it without parsing. Exit codes match:

    0  OK           the operation succeeded / another round is permitted
    1  REFUSE       a policy stop fired. This is a decision, not an error.
    2  USAGE        bad invocation
    3  FAIL-CLOSED  the check could not be performed (missing dependency, unreadable
                    ledger, no receipts dir). Distinct from REFUSE on purpose: "could
                    not check" is not "checked and said no" (V5/V31).

Receipts directory
------------------
The ledger lives under ``$RECEIPTS_DIR/review-ledger/<loop_id>.json``. ``RECEIPTS_DIR``
must be set; there is no default, because a baked default is one machine's layout and
a ledger written somewhere the next invocation does not look is worse than no ledger.
See ``ADOPTION-QUESTIONS.md`` F3/F3b for how to choose the path -- notably that it must
be outside the repo, outside any cloud-sync tree, and durable if reviews span days.

Usage
-----
    review_ledger.py begin    --loop-id ID --review-mode MODE --producer AGENT
    review_ledger.py record   --loop-id ID --verdict-file FILE
    review_ledger.py evaluate --loop-id ID
    review_ledger.py grant    --loop-id ID --owner NAME --rationale TEXT
    review_ledger.py relieve  --loop-id ID --mechanism SLUG --owner NAME --rationale TEXT
    review_ledger.py state    --loop-id ID
    review_ledger.py selftest
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
from pathlib import Path

SCHEMA_VERSION = "review-ledger.v1"

#: Rounds permitted before a stop. A plan that needs a fourth round has a problem the
#: review loop is not going to solve; an execution review gets more because it is
#: checking against a spec that already passed its own loop.
ROUND_BUDGETS = {
    "plan": 3,
    "execution": 6,
    "discovery": 2,
    "handoff": 3,
    "multi-handoff": 3,
}

#: Blocking control-defeat findings sharing one mechanism before the mechanism-class
#: stop fires. Three, per V30: one is a bug, two is a coincidence, three means the
#: thing generating them is the defect.
MECHANISM_LIMIT = 3

#: Cumulative blocking ``review-scaffolding`` findings before the loop is declared to
#: be reviewing itself (V43). Tight on purpose -- a scaffolding finding in a late round
#: is a signal to stop, not a reason to spend another round.
SCAFFOLDING_CAP = 2

#: A rationale short enough to be typed without thinking is not a rationale. This is a
#: crude proxy for deliberation and it is deliberately crude: the alternative was no
#: check at all, and every observed bypass was a one-word justification.
MIN_RATIONALE = 20

LOOP_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
MECHANISM = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")

#: ---------------------------------------------------------------------------
#: THE ONE ALLOWLIST. Both ``save_ledger`` and ``load_ledger`` use these, and nothing
#: else may. A write path and a read path maintained separately drift toward each
#: other's blind spots (V42): the originating implementation bricked a live loop
#: because ``relieve`` wrote a ``mechanism_reliefs`` key its loader's allowlist did not
#: know -- the write succeeded, every subsequent read refused the file, and the state
#: was unrecoverable without hand-editing. Adding a field means adding it HERE, once.
#: ---------------------------------------------------------------------------
LEDGER_KEYS = (
    "schema_version",
    "loop_id",
    "review_mode",
    "round_budget",
    "producer",
    "opened",
    "instrument_digest",
    "rounds",
    "grants",
    "mechanism_reliefs",
)
ROUND_KEYS = ("round", "agent", "verdict", "date", "blocking", "findings")
FINDING_KEYS = ("id", "blocking", "subject", "finding_kind", "mechanism")
GRANT_KEYS = ("round", "owner", "rationale", "granted")
RELIEF_KEYS = ("mechanism", "owner", "rationale", "round")


class Refuse(Exception):
    """A policy stop. Exit 1."""


class FailClosed(Exception):
    """The check could not be performed. Exit 3."""


# ---------------------------------------------------------------------------
# Paths and persistence
# ---------------------------------------------------------------------------

def schema_path() -> Path:
    """The v2 verdict schema, resolved from this file rather than from cwd."""
    return (
        Path(__file__).resolve().parent.parent
        / ".agent"
        / "schemas"
        / "review-verdict.schema.v2.json"
    )


def ledger_dir() -> Path:
    receipts = os.environ.get("RECEIPTS_DIR")
    if not receipts:
        raise FailClosed(
            "RECEIPTS_DIR is not set, so there is nowhere to keep the ledger. There is "
            "no default on purpose: a baked path is one machine's layout, and a ledger "
            "written where the next invocation does not look is worse than none. Set it "
            "to an absolute directory outside the repo and outside any cloud-sync tree "
            "(see ADOPTION-QUESTIONS.md F3/F3b)."
        )
    return Path(receipts) / "review-ledger"


def ledger_path(loop_id: str) -> Path:
    return ledger_dir() / f"{loop_id}.json"


def _filter(record: dict, keys: tuple[str, ...], what: str) -> dict:
    """Project a record onto the allowlist, refusing unknown keys loudly.

    Refusing rather than dropping: a silently discarded field is a write that
    reported success and lost data. The caller sees the key name and the version.
    """
    unknown = sorted(set(record) - set(keys))
    if unknown:
        raise FailClosed(
            f"{what} contains key(s) not in the shared allowlist: {', '.join(unknown)}. "
            f"Add them to the {what.upper().replace(' ', '_')}_KEYS tuple in "
            "review_ledger.py -- one allowlist serves both the write and the read path "
            "(verification-principles V42)."
        )
    return {k: record[k] for k in keys if k in record}


def _write_atomic(path: Path, text: str) -> None:
    """Write via a sibling temp file and one rename; every OSError becomes exit 3.

    Two distinct failures were possible at this line and both were mis-reported.

    An unwritable ledger directory -- read-only volume, absent drive letter, denied
    permissions -- raised a bare ``OSError`` that escaped ``main``'s Refuse/FailClosed
    mapping entirely. Python printed a traceback and exited 1, and 1 is this tool's
    "the ledger refused this round". The dispatch wrappers therefore read a broken
    *installation* as a governance decision, which is the one reading that makes the
    operator stop instead of fixing their environment.

    And a write interrupted partway -- full disk, a kill during ``write_text`` --
    truncated the *existing* ledger in place, replacing the record of every earlier
    round with half a JSON document that ``load_ledger`` then refuses forever. A
    rename either happens or it does not, so the previous state survives a failed
    write; there is no window in which the ledger is neither the old one nor the new.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass  # best effort; the refusal below is the finding, not this cleanup
        raise FailClosed(
            f"could not write the ledger to {path}: {exc}. Exit 3, not 1: nothing was "
            "decided about this round. Check that RECEIPTS_DIR names a writable "
            f"directory that exists on this machine (currently "
            f"{os.environ.get('RECEIPTS_DIR', '<unset>')!r})."
        ) from exc


def save_ledger(ledger: dict) -> None:
    validated = _filter(ledger, LEDGER_KEYS, "ledger")
    validated["rounds"] = [_filter(r, ROUND_KEYS, "round") for r in ledger.get("rounds", [])]
    for entry in validated["rounds"]:
        entry["findings"] = [
            _filter(f, FINDING_KEYS, "finding") for f in entry.get("findings", [])
        ]
    validated["grants"] = [_filter(g, GRANT_KEYS, "grant") for g in ledger.get("grants", [])]
    validated["mechanism_reliefs"] = [
        _filter(r, RELIEF_KEYS, "relief") for r in ledger.get("mechanism_reliefs", [])
    ]
    path = ledger_path(validated["loop_id"])
    _write_atomic(path, json.dumps(validated, indent=2) + "\n")


def load_ledger(loop_id: str) -> dict:
    path = ledger_path(loop_id)
    if not path.is_file():
        raise FailClosed(
            f"no ledger at {path}. Open the loop first: "
            f"review_ledger.py begin --loop-id {loop_id} --review-mode <mode> "
            "--producer <agent>"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailClosed(f"ledger at {path} is unreadable: {exc}") from exc
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise FailClosed(
            f"ledger at {path} declares schema_version "
            f"{raw.get('schema_version')!r}, this tool writes {SCHEMA_VERSION!r}. "
            "Refusing rather than guessing: the stops depend on field meanings."
        )
    # The same allowlist that wrote it. If this raises, the writer and reader have
    # drifted -- which is exactly the failure V42 names, surfaced instead of silent.
    ledger = _filter(raw, LEDGER_KEYS, "ledger")
    ledger["rounds"] = [_filter(r, ROUND_KEYS, "round") for r in raw.get("rounds", [])]
    for entry in ledger["rounds"]:
        entry["findings"] = [
            _filter(f, FINDING_KEYS, "finding") for f in entry.get("findings", [])
        ]
    ledger["grants"] = [_filter(g, GRANT_KEYS, "grant") for g in raw.get("grants", [])]
    ledger["mechanism_reliefs"] = [
        _filter(r, RELIEF_KEYS, "relief") for r in raw.get("mechanism_reliefs", [])
    ]
    return ledger


def instrument_digest() -> str:
    """SHA-256 of the verdict schema -- the rules rounds are judged against."""
    path = schema_path()
    if not path.is_file():
        raise FailClosed(
            f"verdict schema not found at {path}. A loop cannot be bounded against "
            "rules that are not present."
        )
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise FailClosed(
            f"the verdict schema at {path} exists but could not be read: {exc}. The "
            "digest binds the loop to the rules it is judged against, so a loop opened "
            "without one is unbounded in the only dimension that matters."
        ) from exc


# ---------------------------------------------------------------------------
# Stop evaluation -- the whole point of the tool
# ---------------------------------------------------------------------------

def mechanism_counts(ledger: dict) -> dict[str, int]:
    """Blocking control-defeat findings per mechanism, across all rounds.

    Counted by identity rather than by total (V25): the same mechanism recurring
    under four different finding IDs is one recurrence pattern, not four unrelated
    problems, and a per-round tally would never see it.
    """
    counts: dict[str, int] = {}
    for entry in ledger.get("rounds", []):
        for finding in entry.get("findings", []):
            if not finding.get("blocking"):
                continue
            if finding.get("finding_kind") != "control-defeat":
                continue
            slug = finding.get("mechanism")
            if slug:
                counts[slug] = counts.get(slug, 0) + 1
    return counts


def scaffolding_count(ledger: dict) -> int:
    return sum(
        1
        for entry in ledger.get("rounds", [])
        for finding in entry.get("findings", [])
        if finding.get("blocking") and finding.get("subject") == "review-scaffolding"
    )


def relieved_mechanisms(ledger: dict) -> set[str]:
    return {r["mechanism"] for r in ledger.get("mechanism_reliefs", [])}


def stops(ledger: dict) -> list[tuple[str, str]]:
    """Every reason the next round is refused, as ``(kind, message)`` pairs.

    Empty means the next round is permitted. ``kind`` is one of ``budget``,
    ``mechanism``, ``scaffolding``, ``instrument`` -- callers need it because the
    relief for each is different and applying the wrong one is the failure mode:
    ``grant`` refuses while any non-``budget`` stop is active, so "just grant another
    round" cannot become the standard response to a mechanism stop.

    All stops are evaluated, not just the first: a caller told about one stop fixes
    it, comes back, and discovers the next -- each discovery costing a round-trip.
    """
    reasons: list[tuple[str, str]] = []

    budget = ledger["round_budget"] + len(ledger.get("grants", []))
    used = len(ledger.get("rounds", []))
    if used >= budget:
        granted = len(ledger.get("grants", []))
        reasons.append(("budget",
            f"round budget exhausted: {used} round(s) used, budget "
            f"{ledger['round_budget']}"
            + (f" + {granted} grant(s)" if granted else "")
            + f". Escalate to a human, or have one authorize another round: grant "
            f"--loop-id {ledger['loop_id']} --owner <name> --rationale "
            f"\"<at least {MIN_RATIONALE} characters>\"."))

    relieved = relieved_mechanisms(ledger)
    for slug, count in sorted(mechanism_counts(ledger).items()):
        if count >= MECHANISM_LIMIT and slug not in relieved:
            reasons.append(("mechanism",
                f"mechanism-class stop: {count} blocking control-defeat finding(s) "
                f"share mechanism {slug!r}. The third instance of one class means the "
                "mechanism is the defect, not the instance (V30) -- redesign the "
                "mechanism rather than patching the instance. If that is genuinely "
                f"wrong here, relieve THIS mechanism: relieve --loop-id "
                f"{ledger['loop_id']} --mechanism {slug} --owner <name> --rationale "
                "<...>. Do not raise the round budget instead; a global bump defeats "
                "every mechanism stop at once."))

    scaffolding = scaffolding_count(ledger)
    if scaffolding > SCAFFOLDING_CAP:
        reasons.append(("scaffolding",
            f"scaffolding stop: {scaffolding} blocking finding(s) target the review "
            f"apparatus rather than the work (cap {SCAFFOLDING_CAP}). A loop bounded "
            "only by volume converges on its own instrumentation (V43). This cap has "
            "no grant: the correct response is to end the loop and take the "
            "scaffolding findings to a separate change."))

    current = instrument_digest()
    if ledger.get("instrument_digest") and ledger["instrument_digest"] != current:
        reasons.append(("instrument",
            "instrument-drift stop: the verdict schema changed mid-loop (opened at "
            f"{ledger['instrument_digest'][:12]}, now {current[:12]}). Earlier rounds "
            "were judged against different rules, so the counts above are not "
            "comparable. Close this loop and open a new one rather than continuing."))

    return reasons


def bullets(reasons: list[tuple[str, str]]) -> str:
    return "\n".join(f"  - [{kind}] {message}" for kind, message in reasons)


# ---------------------------------------------------------------------------
# Verdict loading
# ---------------------------------------------------------------------------

def load_verdict(path: Path) -> dict:
    if not path.is_file():
        raise FailClosed(f"verdict file not found: {path}")
    try:
        verdict = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailClosed(f"verdict file {path} is unreadable: {exc}") from exc

    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise FailClosed(
            "jsonschema is not installed, so the verdict could not be validated. "
            "Recording an unvalidated verdict would put unchecked data behind every "
            "stop this tool enforces (V5). Install with: pip install jsonschema"
        ) from exc

    try:
        schema = json.loads(schema_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailClosed(
            f"the verdict schema at {schema_path()} could not be read: {exc}. Exit 3: "
            "with no rules to judge against, the verdict was never validated, and an "
            "unvalidated verdict recorded as valid is worse than no record."
        ) from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(verdict), key=lambda e: list(e.path)
    )
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in errors[:4]
        )
        version = verdict.get("schema_version")
        hint = ""
        if version and version != "review-verdict.v2":
            hint = (
                f" The document declares {version!r}; this loop is registered at "
                "review-verdict.v2. A v1 verdict is refused rather than coerced -- v1 "
                "has no `blocking`, `subject`, or `mechanism`, so every stop here would "
                "silently read as zero."
            )
        raise Refuse(f"verdict does not validate against the v2 schema: {detail}.{hint}")
    return verdict


# ---------------------------------------------------------------------------
# Verbs
# ---------------------------------------------------------------------------

def cmd_begin(args) -> int:
    if not LOOP_ID.match(args.loop_id):
        raise Refuse(f"loop-id {args.loop_id!r} must match {LOOP_ID.pattern}")
    if args.review_mode not in ROUND_BUDGETS:
        raise Refuse(
            f"review-mode {args.review_mode!r} unknown; expected one of "
            f"{', '.join(sorted(ROUND_BUDGETS))}"
        )
    path = ledger_path(args.loop_id)
    if path.is_file():
        raise Refuse(
            f"a ledger already exists at {path}. Refusing to reopen: re-beginning a "
            "loop would reset the counts that are the only thing making its stops "
            "real. Use a new loop-id, or `state` to inspect this one."
        )
    ledger = {
        "schema_version": SCHEMA_VERSION,
        "loop_id": args.loop_id,
        "review_mode": args.review_mode,
        "round_budget": ROUND_BUDGETS[args.review_mode],
        "producer": args.producer,
        "opened": datetime.date.today().isoformat(),
        "instrument_digest": instrument_digest(),
        "rounds": [],
        "grants": [],
        "mechanism_reliefs": [],
    }
    save_ledger(ledger)
    print(
        f"OK: opened loop {args.loop_id!r} mode={args.review_mode} "
        f"budget={ledger['round_budget']} producer={args.producer!r}"
    )
    print(f"     ledger: {path}")
    return 0


def cmd_record(args) -> int:
    ledger = load_ledger(args.loop_id)
    verdict = load_verdict(Path(args.verdict_file))

    if verdict["loop_id"] != args.loop_id:
        raise Refuse(
            f"verdict declares loop_id {verdict['loop_id']!r} but is being recorded "
            f"against {args.loop_id!r}. Refusing rather than filing it under the "
            "requested name: a verdict recorded in the wrong loop corrupts two "
            "counts at once."
        )

    # The mode is part of the loop's identity, not decoration. `record` checked loop_id,
    # producer and round but never this, so a schema-valid *plan* verdict -- an inspection
    # of a document, which may not have looked at a line of built code -- could be recorded
    # into an execution loop and pronounce it closeable. The two modes carry different round
    # budgets and different evidence obligations; accepting one for the other silently
    # substitutes the cheaper review for the one that was required.
    if verdict["review_mode"] != ledger["review_mode"]:
        raise Refuse(
            f"verdict declares review_mode {verdict['review_mode']!r} but this loop was "
            f"opened as {ledger['review_mode']!r}. A {verdict['review_mode']!r} review does "
            f"not discharge a {ledger['review_mode']!r} one, and recording it here would "
            f"let the loop close on evidence nobody asked for. Re-run the review in "
            f"{ledger['review_mode']!r} mode, or open a separate loop for the "
            f"{verdict['review_mode']!r} pass."
        )

    # The self-review prohibition. The one rule that never bends.
    if verdict["agent"] == ledger["producer"]:
        raise Refuse(
            f"agent {verdict['agent']!r} produced the work under review in this loop. "
            "The agent that produced the work never authors its own verdict. If no "
            "independent reviewer is reachable, the work stops and waits for a human "
            "-- self-review is not a fallback."
        )

    # Stops are checked BEFORE the round is written: a refused round must not consume
    # budget, or a caller could exhaust a loop by submitting invalid verdicts.
    blocked = stops(ledger)
    if blocked:
        raise Refuse("cannot record another round.\n" + bullets(blocked))

    expected = len(ledger["rounds"]) + 1
    if verdict["round"] != expected:
        raise Refuse(
            f"verdict claims round {verdict['round']} but the ledger's next round is "
            f"{expected}. The ledger is authoritative. A mismatch usually means a "
            "round was recorded elsewhere, or a verdict is being replayed."
        )

    findings = [
        {
            "id": f["id"],
            "blocking": f["blocking"],
            "subject": f["subject"],
            "finding_kind": f["finding_kind"],
            **({"mechanism": f["mechanism"]} if f.get("mechanism") else {}),
        }
        for f in verdict["findings"]
    ]
    ledger["rounds"].append(
        {
            "round": expected,
            "agent": verdict["agent"],
            "verdict": verdict["verdict"],
            "date": verdict["date"],
            "blocking": sum(1 for f in findings if f["blocking"]),
            "findings": findings,
        }
    )
    save_ledger(ledger)

    print(
        f"OK: recorded round {expected} verdict={verdict['verdict']} "
        f"agent={verdict['agent']!r} blocking={ledger['rounds'][-1]['blocking']}"
    )
    if verdict["verdict"] == "approved":
        print("     loop may close: approved with no blocking findings.")
    else:
        remaining = stops(ledger)
        if remaining:
            print("     next round is REFUSED:")
            print(bullets(remaining))
        else:
            budget = ledger["round_budget"] + len(ledger["grants"])
            print(
                f"     next round permitted ({len(ledger['rounds'])}/{budget} used)."
            )
    return 0


def cmd_evaluate(args) -> int:
    ledger = load_ledger(args.loop_id)
    blocked = stops(ledger)
    if blocked:
        raise Refuse("another round is not permitted.\n" + bullets(blocked))
    budget = ledger["round_budget"] + len(ledger["grants"])
    # `mode=` is part of this line's contract, not decoration: the dispatch wrappers read
    # it to resolve the dispatch kind (and with it the timeout floor) instead of trusting a
    # flag the caller retypes every round. Renaming or dropping it breaks them, so the
    # wrappers fail closed on its absence rather than assuming a kind.
    print(
        f"OK: round {len(ledger['rounds']) + 1} permitted "
        f"mode={ledger['review_mode']} "
        f"({len(ledger['rounds'])}/{budget} used, no stop active)"
    )
    return 0


def _check_rationale(owner: str, rationale: str) -> None:
    if not owner.strip():
        raise Refuse("--owner must name a person. An unattributed override is not one.")
    if len(rationale.strip()) < MIN_RATIONALE:
        raise Refuse(
            f"--rationale must be at least {MIN_RATIONALE} characters "
            f"(got {len(rationale.strip())}). Every observed bypass of this control was "
            "a one-word justification, so the length floor is the control."
        )


def cmd_grant(args) -> int:
    ledger = load_ledger(args.loop_id)
    _check_rationale(args.owner, args.rationale)

    # A grant buys one round against the *budget*. If a different stop is active, the
    # extra round is unusable and granting it only records a human's name against a
    # control they did not actually relieve. Refusing here is what keeps "grant another
    # round" from becoming the reflex answer to a mechanism or scaffolding stop -- the
    # single most likely way this whole tool gets defeated in practice.
    other = [(k, m) for k, m in stops(ledger) if k != "budget"]
    if other:
        raise Refuse(
            "a grant would not unblock this loop; a non-budget stop is active and each "
            "has its own relief.\n" + bullets(other)
        )

    ledger["grants"].append(
        {
            "round": len(ledger["rounds"]) + 1,
            "owner": args.owner,
            "rationale": args.rationale,
            "granted": datetime.date.today().isoformat(),
        }
    )
    save_ledger(ledger)
    budget = ledger["round_budget"] + len(ledger["grants"])
    print(
        f"OK: {args.owner} granted one extra round "
        f"(budget now {budget}, {len(ledger['rounds'])} used)"
    )
    print("     A grant relieves the round budget only. Mechanism and scaffolding")
    print("     stops are unaffected -- they need `relieve`, or ending the loop.")
    return 0


def cmd_relieve(args) -> int:
    ledger = load_ledger(args.loop_id)
    if not MECHANISM.match(args.mechanism):
        raise Refuse(f"--mechanism {args.mechanism!r} must match {MECHANISM.pattern}")
    _check_rationale(args.owner, args.rationale)
    counts = mechanism_counts(ledger)
    if args.mechanism not in counts:
        raise Refuse(
            f"mechanism {args.mechanism!r} has no blocking control-defeat findings in "
            "this loop, so there is nothing to relieve. Relieving an unseen mechanism "
            f"pre-authorizes a stop that has not fired. Seen: "
            f"{', '.join(sorted(counts)) or '(none)'}"
        )
    if args.mechanism in relieved_mechanisms(ledger):
        raise Refuse(f"mechanism {args.mechanism!r} is already relieved in this loop.")
    ledger["mechanism_reliefs"].append(
        {
            "mechanism": args.mechanism,
            "owner": args.owner,
            "rationale": args.rationale,
            "round": len(ledger["rounds"]) + 1,
        }
    )
    save_ledger(ledger)
    print(
        f"OK: {args.owner} relieved mechanism {args.mechanism!r} "
        f"({counts[args.mechanism]} finding(s) recorded)"
    )
    print("     Other mechanisms remain stopped. This is per-mechanism by design:")
    print("     raising a global limit would defeat every mechanism stop at once.")
    return 0


def cmd_state(args) -> int:
    ledger = load_ledger(args.loop_id)
    budget = ledger["round_budget"] + len(ledger["grants"])
    blocked = stops(ledger)
    print(f"OK: loop {ledger['loop_id']!r} mode={ledger['review_mode']}")
    print(f"     opened     {ledger['opened']}  producer={ledger['producer']!r}")
    print(f"     rounds     {len(ledger['rounds'])}/{budget}"
          f" (base {ledger['round_budget']} + {len(ledger['grants'])} grant(s))")
    for entry in ledger["rounds"]:
        print(
            f"       r{entry['round']} {entry['verdict']:<17} "
            f"agent={entry['agent']!r} blocking={entry['blocking']}"
        )
    counts = mechanism_counts(ledger)
    relieved = relieved_mechanisms(ledger)
    if counts:
        print("     mechanisms (blocking control-defeat):")
        for slug, count in sorted(counts.items()):
            mark = " [RELIEVED]" if slug in relieved else ""
            print(f"       {slug}: {count}/{MECHANISM_LIMIT}{mark}")
    print(f"     scaffolding {scaffolding_count(ledger)}/{SCAFFOLDING_CAP}")
    print(f"     instrument  {ledger.get('instrument_digest', '?')[:12]}")
    if blocked:
        print("     NEXT ROUND: refused")
        print(bullets(blocked))
    else:
        print("     NEXT ROUND: permitted")
    return 0


# ---------------------------------------------------------------------------
# selftest -- prove every REFUSE can fire, and that OK still happens
# ---------------------------------------------------------------------------

def cmd_selftest(_args) -> int:
    """Drive the real verbs against a throwaway RECEIPTS_DIR.

    Arms exercise the actual command functions, not a reimplementation, so a stop that
    is unreachable through the CLI shows up here. The must-OK arms matter as much as
    the must-REFUSE ones: a ledger that refuses everything satisfies every negative
    arm and is useless (V3).
    """
    import contextlib
    import io
    import tempfile

    def verdict_doc(loop, rnd, agent="reviewer-a", verdict="changes_required",
                    findings=None, mode="plan"):
        """``mode`` is a parameter, not a constant, and that is the point.

        It used to be hardcoded to ``"plan"`` while three of the four loops below were
        opened as ``execution``. Those arms passed -- ``record`` never compared the two
        -- so the suite's own fixtures asserted that a plan verdict belongs in an
        execution loop. A test that encodes the defect protects it: once ``record``
        started checking, the fixtures were the first thing that had to be corrected,
        which is how a hardcoded fixture value becomes a second copy of the contract.
        """
        return {
            "schema_version": "review-verdict.v2",
            "date": "2026-09-07",
            "review_mode": mode,
            "loop_id": loop,
            "round": rnd,
            "target_plan": "docs/execution/plans/example.md",
            "agent": agent,
            "requested_verbosity": "standard",
            "verdict": verdict,
            "summary": "s",
            "findings": findings if findings is not None else [],
            "checklist_results": [
                {"check": "c", "result": "pass", "command": "true", "exit_code": 0,
                 "evidence": "e"}
            ],
        }

    def finding(fid, kind="behavior", mech=None, subject="deliverable", blocking=True):
        f = {
            "id": fid, "severity": "High", "confidence": "High", "blocking": blocking,
            "subject": subject, "finding_kind": kind, "finding": "f",
            "file_line": "a.py:1", "recommendation": "r", "status": "open",
        }
        if mech:
            f["mechanism"] = mech
        return f

    results: list[tuple[str, str, str]] = []  # label, want, got

    def run_verb(fn, **kw):
        """Invoke a verb, returning ('OK'|'REFUSE'|'FAIL-CLOSED', text)."""
        args = argparse.Namespace(**kw)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                fn(args)
            return "OK", buf.getvalue()
        except Refuse as exc:
            return "REFUSE", str(exc)
        except FailClosed as exc:
            return "FAIL-CLOSED", str(exc)

    def arm(label, want, fn, must_say=None, **kw):
        """One arm. ``must_say`` is not optional decoration.

        A non-zero result tells you something refused, not that the thing under test
        refused (V3). Several of these arms construct a ledger state that would trip
        two or three stops if the logic were sloppy, and without a substring assertion
        an arm that fires the *wrong* stop is indistinguishable from a pass. So the
        negative arms name the clause they expect to reject them.
        """
        got, text = run_verb(fn, **kw)
        if got == want and must_say and must_say not in text:
            got = f"{want} but not for the expected reason: {text[:90]!r}"
        results.append((label, want, got))

    with tempfile.TemporaryDirectory(prefix="review-ledger-selftest-") as tmp:
        previous = os.environ.get("RECEIPTS_DIR")
        os.environ["RECEIPTS_DIR"] = tmp
        try:
            vdir = Path(tmp) / "verdicts"
            vdir.mkdir()

            def write(name, doc):
                path = vdir / name
                path.write_text(json.dumps(doc), encoding="utf-8")
                return str(path)

            # --- begin -------------------------------------------------------
            arm("begin-ok", "OK", cmd_begin,
                loop_id="loop-a", review_mode="plan", producer="builder-x")
            arm("begin-duplicate-refused", "REFUSE", cmd_begin,
                must_say="already exists",
                loop_id="loop-a", review_mode="plan", producer="builder-x")
            arm("begin-bad-mode-refused", "REFUSE", cmd_begin,
                must_say="review-mode",
                loop_id="loop-b", review_mode="vibes", producer="builder-x")
            arm("begin-bad-loop-id-refused", "REFUSE", cmd_begin,
                must_say="loop-id",
                loop_id="Loop C!", review_mode="plan", producer="builder-x")

            # --- record ------------------------------------------------------
            arm("record-ok", "OK", cmd_record, loop_id="loop-a",
                verdict_file=write("r1.json", verdict_doc(
                    "loop-a", 1, findings=[finding("F1")])))
            arm("self-review-refused", "REFUSE", cmd_record, loop_id="loop-a",
                must_say="produced the work under review",
                verdict_file=write("self.json", verdict_doc(
                    "loop-a", 2, agent="builder-x", findings=[finding("F2")])))
            arm("wrong-loop-id-refused", "REFUSE", cmd_record, loop_id="loop-a",
                must_say="declares loop_id",
                verdict_file=write("wrong.json", verdict_doc(
                    "loop-z", 2, findings=[finding("F2")])))
            arm("round-number-drift-refused", "REFUSE", cmd_record, loop_id="loop-a",
                must_say="claims round 5",
                verdict_file=write("skip.json", verdict_doc(
                    "loop-a", 5, findings=[finding("F2")])))
            arm("v1-verdict-refused", "REFUSE", cmd_record, loop_id="loop-a",
                must_say="review-verdict.v1",
                verdict_file=write("v1.json", {
                    "schema_version": "review-verdict.v1", "date": "2026-09-07",
                    "review_mode": "plan", "target_plan": "p", "agent": "reviewer-a",
                    "requested_verbosity": "standard", "verdict": "approved",
                    "summary": "s", "findings": [], "checklist_results": []}))
            arm("unparseable-verdict-fails-closed", "FAIL-CLOSED", cmd_record,
                loop_id="loop-a", verdict_file=str(vdir / "does-not-exist.json"))

            # --- round budget (plan = 3) -------------------------------------
            arm("record-r2", "OK", cmd_record, loop_id="loop-a",
                verdict_file=write("r2.json", verdict_doc(
                    "loop-a", 2, findings=[finding("F2")])))
            arm("record-r3", "OK", cmd_record, loop_id="loop-a",
                verdict_file=write("r3.json", verdict_doc(
                    "loop-a", 3, findings=[finding("F3")])))
            arm("budget-exhausted-refused", "REFUSE", cmd_evaluate, loop_id="loop-a",
                must_say="[budget] round budget exhausted")
            arm("grant-short-rationale-refused", "REFUSE", cmd_grant, loop_id="loop-a",
                must_say="--rationale must be at least",
                owner="release-owner", rationale="fine")
            arm("grant-ok", "OK", cmd_grant, loop_id="loop-a", owner="release-owner",
                rationale="Reviewer found a real regression in round 3; one more round.")
            arm("evaluate-after-grant-ok", "OK", cmd_evaluate, loop_id="loop-a")

            # --- mechanism-class stop ----------------------------------------
            arm("begin-mech-loop", "OK", cmd_begin,
                loop_id="loop-m", review_mode="execution", producer="builder-x")
            # The dispatch wrappers read `mode=` out of the evaluate line to resolve the
            # dispatch kind, and with it the execution-review timeout floor. Asserting the
            # substring here is what makes that a contract: without this arm a tidier
            # print statement would break the wrappers, not this tool, and the symptom
            # would be a review silently reverting to the 15-minute default.
            arm("evaluate-names-mode-for-wrappers", "OK", cmd_evaluate, loop_id="loop-m",
                must_say="mode=execution")
            for i in (1, 2, 3):
                arm(f"mech-round-{i}", "OK", cmd_record, loop_id="loop-m",
                    verdict_file=write(f"m{i}.json", verdict_doc(
                        "loop-m", i, mode="execution", findings=[finding(
                            f"M{i}", kind="control-defeat",
                            mech="swallowed-exit-code")])))
            # Note the state this arm runs against: loop-m is at 3 of 6 execution
            # rounds, so the budget stop is NOT active. The refusal has to come from
            # the mechanism clause or it proves nothing.
            arm("mechanism-stop-refused", "REFUSE", cmd_evaluate, loop_id="loop-m",
                must_say="[mechanism] mechanism-class stop")
            arm("grant-does-not-clear-mechanism", "REFUSE", cmd_grant, loop_id="loop-m",
                must_say="a grant would not unblock this loop",
                owner="release-owner", rationale="Please just let the loop continue one more round.")
            arm("relieve-unseen-mechanism-refused", "REFUSE", cmd_relieve,
                must_say="nothing to relieve",
                loop_id="loop-m", mechanism="never-happened", owner="release-owner",
                rationale="Pre-authorizing a stop that has not fired yet.")
            arm("relieve-ok", "OK", cmd_relieve, loop_id="loop-m",
                mechanism="swallowed-exit-code", owner="release-owner",
                rationale="Three instances were in vendored code excluded from scope.")
            arm("evaluate-after-relief-ok", "OK", cmd_evaluate, loop_id="loop-m")
            arm("relieve-twice-refused", "REFUSE", cmd_relieve, loop_id="loop-m",
                must_say="already relieved",
                mechanism="swallowed-exit-code", owner="release-owner",
                rationale="Trying the same relief a second time for no reason.")

            # --- scaffolding stop (cap 2, no grant clears it) -----------------
            arm("begin-scaffold-loop", "OK", cmd_begin,
                loop_id="loop-s", review_mode="execution", producer="builder-x")
            for i in (1, 2, 3):
                arm(f"scaffold-round-{i}", "OK", cmd_record, loop_id="loop-s",
                    verdict_file=write(f"s{i}.json", verdict_doc(
                        "loop-s", i, mode="execution", findings=[finding(
                            f"S{i}", subject="review-scaffolding")])))
            # Also 3 of 6 execution rounds: the budget stop is not available to
            # accidentally satisfy this arm.
            arm("scaffolding-stop-refused", "REFUSE", cmd_evaluate, loop_id="loop-s",
                must_say="[scaffolding] scaffolding stop")
            arm("grant-does-not-clear-scaffolding", "REFUSE", cmd_grant,
                must_say="[scaffolding]",
                loop_id="loop-s", owner="release-owner",
                rationale="The scaffolding findings are genuinely worth another round.")

            # --- non-blocking findings must NOT trip the stops ---------------
            arm("begin-nonblocking-loop", "OK", cmd_begin,
                loop_id="loop-n", review_mode="execution", producer="builder-x")
            for i in (1, 2, 3):
                arm(f"nonblocking-round-{i}", "OK", cmd_record, loop_id="loop-n",
                    verdict_file=write(f"n{i}.json", verdict_doc(
                        "loop-n", i, mode="execution", verdict="approved", findings=[finding(
                            f"N{i}", kind="control-defeat", mech="swallowed-exit-code",
                            subject="review-scaffolding", blocking=False)])))
            arm("nonblocking-does-not-stop", "OK", cmd_evaluate, loop_id="loop-n")

            # --- the verdict's mode must match the loop's ---------------------
            # A plan review inspects a document; an execution review inspects built
            # code. `record` checked loop_id, producer and round but not this, so a
            # schema-valid plan verdict could be filed into an execution loop and
            # pronounce it closeable on evidence that never touched the code. Both
            # directions are wrong, so both are armed.
            arm("begin-mode-loop", "OK", cmd_begin,
                loop_id="loop-x", review_mode="execution", producer="builder-x")
            arm("plan-verdict-into-execution-loop-refused", "REFUSE", cmd_record,
                must_say="does not discharge",
                loop_id="loop-x",
                verdict_file=write("xplan.json", verdict_doc(
                    "loop-x", 1, mode="plan", findings=[finding("X1")])))
            arm("execution-verdict-into-plan-loop-refused", "REFUSE", cmd_record,
                must_say="does not discharge",
                loop_id="loop-a",
                verdict_file=write("aexec.json", verdict_doc(
                    "loop-a", 4, mode="execution", findings=[finding("A4")])))
            # The refusal message is a claim; the round count is the fact. A `record`
            # that refused *after* writing would satisfy both arms above.
            results.append((
                "refused-verdict-not-recorded",
                "0 rounds",
                f"{len(load_ledger('loop-x')['rounds'])} rounds",
            ))
            arm("matching-mode-verdict-ok", "OK", cmd_record, loop_id="loop-x",
                verdict_file=write("xexec.json", verdict_doc(
                    "loop-x", 1, mode="execution", findings=[finding("X1")])))

            # --- instrument drift -------------------------------------------
            drifted = load_ledger("loop-n")
            drifted["instrument_digest"] = "0" * 64
            save_ledger(drifted)
            arm("instrument-drift-refused", "REFUSE", cmd_evaluate, loop_id="loop-n",
                must_say="[instrument] instrument-drift stop")

            # --- state is readable throughout -------------------------------
            arm("state-ok", "OK", cmd_state, loop_id="loop-a")

            # --- V42 round-trip: every record variant survives write -> read --
            # loop-m carries the awkward one: a mechanism_reliefs entry. That exact key
            # is what bricked the originating ledger, so the arm targets it directly.
            ledger = load_ledger("loop-m")
            source = json.dumps(ledger, sort_keys=True)
            save_ledger(ledger)
            reread = json.dumps(load_ledger("loop-m"), sort_keys=True)
            results.append((
                "v42-roundtrip-relief-survives",
                "identical",
                "identical" if source == reread else "MUTATED",
            ))

            # --- an unknown key must fail closed, not be silently dropped ----
            bad = load_ledger("loop-a")
            bad["surprise_field"] = 1
            try:
                save_ledger(bad)
                got = "OK"
            except FailClosed:
                got = "FAIL-CLOSED"
            results.append(("v42-unknown-key-fails-closed", "FAIL-CLOSED", got))

            # --- the real entry point: exit codes AND first-line prefixes -----
            # Every arm above calls a verb function directly, which bypasses main()'s
            # exception-to-exit-code mapping completely. Callers branch on the exit
            # status and the first line, so those are what has to be observed rather
            # than inferred from the functions' behaviour (V2). A mapping that had
            # REFUSE exiting 0 would pass all 40 arms above.
            def cli(argv):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(
                    io.StringIO()
                ):
                    code = main(argv)
                first = (buf.getvalue().splitlines() or [""])[0]
                return f"{code}/{first.split(':', 1)[0]}"

            for label, want, argv in [
                ("cli-ok-is-0-OK", "0/OK", ["state", "--loop-id", "loop-a"]),
                ("cli-refuse-is-1-REFUSE", "1/REFUSE", ["evaluate", "--loop-id", "loop-s"]),
                ("cli-failclosed-is-3", "3/FAIL-CLOSED", ["state", "--loop-id", "absent"]),
                ("cli-usage-is-2-USAGE", "2/USAGE", ["nonsense-verb"]),
                ("cli-missing-required-arg-is-2", "2/USAGE", ["record", "--loop-id", "x"]),
            ]:
                results.append((label, want, cli(argv)))

            # --- an unwritable ledger destination is 3, not a traceback -------
            # RECEIPTS_DIR pointed *through* a regular file, so mkdir cannot create the
            # ledger directory on any platform. The OSError used to escape main()'s
            # mapping and exit 1 with a traceback, and 1 is this tool's "the ledger
            # refused this round" -- a broken install reading as a governance decision.
            # Observed through main() rather than the verb, because the exit code IS the
            # finding here (V2).
            blocker = Path(tmp) / "not-a-directory"
            blocker.write_text("", encoding="utf-8")
            os.environ["RECEIPTS_DIR"] = str(blocker / "nested")
            results.append((
                "unwritable-ledger-is-3-not-1",
                "3/FAIL-CLOSED",
                cli(["begin", "--loop-id", "loop-w", "--review-mode", "plan",
                     "--producer", "builder-x"]),
            ))
            os.environ["RECEIPTS_DIR"] = tmp

            # --- a truncated ledger must not be produced by a failed write ----
            # The old writer opened the real path and truncated it, so an interrupted
            # write destroyed the record of every earlier round. The temp-file-and-rename
            # is only worth having if nothing is left behind when the rename never
            # happens, which is what this observes.
            leftovers = sorted(p.name for p in ledger_dir().glob("*.tmp"))
            results.append((
                "no-temp-files-left-behind",
                "none",
                ", ".join(leftovers) if leftovers else "none",
            ))

            # --- RECEIPTS_DIR unset must fail closed, never default ----------
            del os.environ["RECEIPTS_DIR"]
            status, text = run_verb(cmd_state, loop_id="loop-a")
            results.append((
                "no-receipts-dir-fails-closed",
                "FAIL-CLOSED",
                status if "RECEIPTS_DIR is not set" in text else f"{status} (wrong reason)",
            ))
        finally:
            if previous is None:
                os.environ.pop("RECEIPTS_DIR", None)
            else:
                os.environ["RECEIPTS_DIR"] = previous

    failures = 0
    ok_arms = sum(1 for _, want, _ in results if want == "OK")
    for label, want, got in results:
        if want == got:
            print(f"PASS {label:<38} {got}")
        else:
            failures += 1
            print(f"FAIL {label:<38} want={want} got={got}")

    print(
        f"\nRESULT: {len(results)} arm(s), {failures} failure(s) "
        f"[{ok_arms} must-OK arms, so the tool is not refusing everything]"
    )
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    doc = __doc__ or ""
    parser = argparse.ArgumentParser(
        prog="review_ledger.py",
        description=doc.splitlines()[0] if doc else "",
    )
    sub = parser.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("begin", help="open a loop and fix its budget")
    p.add_argument("--loop-id", required=True)
    p.add_argument("--review-mode", required=True,
                   choices=sorted(ROUND_BUDGETS))
    p.add_argument("--producer", required=True,
                   help="the agent that produced the work; it may not author a verdict")
    p.set_defaults(func=cmd_begin)

    p = sub.add_parser("record", help="validate and record one round's verdict")
    p.add_argument("--loop-id", required=True)
    p.add_argument("--verdict-file", required=True)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("evaluate", help="is another round permitted? (pre-dispatch check)")
    p.add_argument("--loop-id", required=True)
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("grant", help="a named human authorizes one extra round")
    p.add_argument("--loop-id", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--rationale", required=True)
    p.set_defaults(func=cmd_grant)

    p = sub.add_parser("relieve", help="a named human relieves ONE mechanism stop")
    p.add_argument("--loop-id", required=True)
    p.add_argument("--mechanism", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--rationale", required=True)
    p.set_defaults(func=cmd_relieve)

    p = sub.add_parser("state", help="print counts and active stops")
    p.add_argument("--loop-id", required=True)
    p.set_defaults(func=cmd_state)

    p = sub.add_parser("selftest", help="prove every stop can fire")
    p.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse already wrote its message; emit the contract's first line too so a
        # caller branching on the prefix is not left guessing.
        print("USAGE: see review_ledger.py --help")
        return 2
    try:
        return args.func(args)
    except Refuse as exc:
        print(f"REFUSE: {exc}")
        return 1
    except FailClosed as exc:
        print(f"FAIL-CLOSED: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
