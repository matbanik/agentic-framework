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

Five stops, one escape hatch
----------------------------
1. **Round budget** -- plan 3, execution 6, discovery 2.
2. **Mechanism-class stop** -- three *blocking* ``control-defeat`` findings sharing one
   ``mechanism`` slug means the mechanism is the defect, not the instance (V30). Lifted
   per mechanism, by name -- deliberately NOT by raising the round budget, because
   bumping a global limit is how this stop gets defeated.
3. **Scaffolding stop** -- a loop bounded only by volume converges on its own
   instrumentation (V43). Blocking ``review-scaffolding`` findings are capped
   separately and tightly.
4. **Instrument-drift stop** -- if the verdict schema changes mid-loop, earlier rounds
   were judged against different rules and the counts are not comparable.
5. **Token budget** (added 2026-09-21) -- ``TOKEN_BUDGETS`` per mode, overridable at
   ``begin --token-budget``. ``record --usage-receipt`` charges each round what its
   dispatch receipt says it cost; a receipt with no usage records the round
   ``unmeasured`` and charges nothing. The stop fires when what is spent plus what the
   *next* round is expected to cost (the last measured round) exceeds the budget -- so
   the loop stops before the overrunning round, not after it.

Every stop is lifted by the same act, ``continue``: a named human, a rationale of real
length, a timestamp, and a record of exactly which stops the act lifted. It is uncapped
(2026-09-21; it replaces ``grant``/``relieve``, which carried count caps). The stops
exist to keep an *unattended* loop from spending API budget forever; they never
overrule a person who is watching it.

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
Usage receipts (``record --usage-receipt``) are read from wherever the dispatch wrote them.

Usage
-----
    review_ledger.py begin    --loop-id ID --review-mode MODE --producer AGENT
                              --goal-anchor TEXT --ac-file PLAN [--vocabulary FILE] [--token-budget N]
    review_ledger.py record   --loop-id ID --verdict-file FILE [--usage-receipt FILE]
    review_ledger.py evaluate --loop-id ID [--payload PROMPT]
    review_ledger.py continue --loop-id ID [--rounds N] [--tokens T] [--relieve-mechanism SLUG]
                              --said TEXT --by WHO --at ISO8601
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

#: Tokens permitted before the token stop fires: 3,500,000 per base round, the rounded
#: mean of 17 measured review rounds in the originating adopter's estate (28 recorded,
#: 60,501,033 tokens, mean 3,558,884; measured 2026-09-21). Overridable per loop at
#: ``begin --token-budget``; lifted per loop by ``continue --tokens``. Re-measure for
#: your own estate; the number is a default, not a law.
TOKEN_BUDGETS = {
    "plan": 10_500_000,
    "execution": 21_000_000,
    "discovery": 7_000_000,
    "handoff": 10_500_000,
    "multi-handoff": 10_500_000,
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

#: Intent (added 2026-09-21). A loop is opened against one sentence of intent, the
#: ``goal_anchor``; every verdict must quote it inside its own ``intent_anchor``
#: (INTENT_BINDING: normalized containment) and say whether the intent was achieved.
#: A blocking finding must cite the acceptance criterion it violates, and the citable
#: set is read from the plan at ``begin --ac-file`` -- never typed by hand.
INTENT_VALUES = ("yes", "partial", "no")
AC_ID = re.compile(r"\bAC-\d+[a-z]?\b")

#: The closed mechanism vocabulary ``record`` enforces for ``control-defeat`` findings
#: (AU-RT-15): a defeat filed under a slug the catalogue does not know is refused, so four
#: paraphrases of one defeat cannot each start a fresh count. ``begin --vocabulary``
#: overrides the default per loop; the selftest points it at a throwaway catalogue.
VOCABULARY_PATH = (
    Path(__file__).resolve().parent.parent / ".agent" / "context" / "review-vocabulary.yaml"
)

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
    "token_budget",
    "goal_anchor",
    "ac_ids",
    "vocabulary_path",
)
ROUND_KEYS = (
    "round", "agent", "verdict", "date", "blocking", "findings",
    "usage", "unmeasured", "intent_achieved",
)
FINDING_KEYS = ("id", "blocking", "subject", "finding_kind", "mechanism", "violates")
#: A ``continue`` record. ``owner``/``granted`` carry ``--by``/``--at`` (upstream's names,
#: kept so a legacy grant still loads); ``rationale`` is legacy-only, ``said`` is the
#: continue's. ``lifted`` names the stops active when it was recorded and cleared by it.
GRANT_KEYS = (
    "round", "owner", "rationale", "granted",
    "said", "rounds", "tokens", "lifted", "scaffolding_acknowledged",
)
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


def rounds_allowed(ledger: dict) -> int:
    """Base round budget plus every round a continue bought (a legacy grant bought one)."""
    return ledger["round_budget"] + sum(
        g["rounds"] if "rounds" in g else 1 for g in ledger.get("grants", [])
    )


def read_usage(receipt: Path) -> int | None:
    """Total tokens in a dispatch receipt, or None when it carries no usage.

    Ported from v0 unchanged in *what it counts*, because ``TOKEN_BUDGETS`` was measured
    with it (row 1): for a ``.jsonl`` event stream, every integer under a ``usage`` key
    named input/output/cached_input/total_tokens is summed; for anything else, the
    first ``total_tokens: N``. None means the receipt says nothing about tokens, and the
    round is recorded unmeasured and charged nothing (AC-4). A receipt that does not
    exist is a different thing -- a path typo silently becoming "unmeasured" is the V5
    failure -- so that fails closed instead.
    """
    if not receipt.is_file():
        raise FailClosed(
            f"usage receipt not found: {receipt}. Exit 3: a missing receipt is not an "
            "unmeasured round. Pass no --usage-receipt if the dispatch produced none."
        )
    try:
        text = receipt.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise FailClosed(f"usage receipt {receipt} is unreadable: {exc}") from exc
    if receipt.suffix == ".jsonl":
        total = 0
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            block = event.get("usage") if isinstance(event, dict) else None
            for key in ("input_tokens", "output_tokens", "cached_input_tokens", "total_tokens"):
                if isinstance((block or {}).get(key), int):
                    total += block[key]
        return total or None
    found = re.search(r"total_tokens:\s*(\d+)", text)
    return int(found.group(1)) if found else None


def tokens_spent(ledger: dict) -> tuple[int, int, int]:
    """``(spent, reserve, budget)`` for the token stop.

    ``spent`` sums ``usage`` over measured rounds only: an unmeasured round is recorded
    as such and charged nothing, because charging it at any invented rate would fire the
    stop on a number nobody observed (AC-4). ``reserve`` is what the *next* round is
    expected to cost -- the most recent measured round's usage, or the budget's
    per-round share while nothing has been measured. ``budget`` is the loop's base
    budget plus every ``tokens`` a continue has granted.
    """
    measured = [
        r["usage"]
        for r in ledger.get("rounds", [])
        if isinstance(r.get("usage"), int) and not r.get("unmeasured")
    ]
    spent = sum(measured)
    base = ledger.get("token_budget") or TOKEN_BUDGETS[ledger["review_mode"]]
    budget = base + sum(g.get("tokens") or 0 for g in ledger.get("grants", []))
    reserve = measured[-1] if measured else base // ledger["round_budget"]
    return spent, reserve, budget


def stops(ledger: dict) -> list[tuple[str, str]]:
    """Every reason the next round is refused, as ``(kind, message)`` pairs.

    Empty means the next round is permitted. ``kind`` is one of ``budget``, ``tokens``,
    ``mechanism``, ``scaffolding``, ``instrument`` -- callers need it because what lifts
    each is different: ``continue`` records which of them it actually lifted, so a round
    bought against a mechanism stop is visible as exactly that, not as a fix.

    All stops are evaluated, not just the first: a caller told about one stop fixes
    it, comes back, and discovers the next -- each discovery costing a round-trip.
    """
    reasons: list[tuple[str, str]] = []
    lift = (
        f"--said \"<at least {MIN_RATIONALE} characters>\" --by <name> --at <ISO-8601>"
    )

    allowed = rounds_allowed(ledger)
    used = len(ledger.get("rounds", []))
    if used >= allowed:
        bought = allowed - ledger["round_budget"]
        reasons.append(("budget",
            f"round budget exhausted: {used} round(s) used, {allowed} allowed (base "
            f"{ledger['round_budget']}"
            + (f" + {bought} bought by continue" if bought else "")
            + f"). A named human may continue: continue --loop-id {ledger['loop_id']} "
            f"--rounds 1 {lift}."))

    # TOKENS_STOP. Strictly greater: a loop holding exactly the tokens its next round
    # needs is permitted, and the selftest pins the boundary from both sides so a `>=`
    # cannot creep in.
    spent, reserve, token_budget = tokens_spent(ledger)
    if spent + reserve > token_budget:
        reasons.append(("tokens",
            f"tokens: {spent:,} spent + {reserve:,} reserved for the next round > "
            f"budget {token_budget:,}. The reserve is the last measured round's cost, so "
            "the loop stops before the round that would overrun, not after it. A named "
            f"human may continue: continue --loop-id {ledger['loop_id']} --tokens <extra> "
            f"{lift}."))

    relieved = relieved_mechanisms(ledger)
    for slug, count in sorted(mechanism_counts(ledger).items()):
        if count >= MECHANISM_LIMIT and slug not in relieved:
            reasons.append(("mechanism",
                f"mechanism-class stop: {count} blocking control-defeat finding(s) "
                f"share mechanism {slug!r}. The third instance of one class means the "
                "mechanism is the defect, not the instance (V30) -- redesign the "
                "mechanism rather than patching the instance. If that is genuinely "
                f"wrong here, a named human relieves THIS mechanism: continue --loop-id "
                f"{ledger['loop_id']} --relieve-mechanism {slug} {lift}. Other mechanisms "
                "stay stopped; a global bump would defeat every mechanism stop at once."))

    # Scaffolding findings recorded before the latest acknowledging continue no longer
    # count: the human saw them and chose to go on (CONTINUE_LIFTS).
    acknowledged = max(
        (g["round"] for g in ledger.get("grants", []) if g.get("scaffolding_acknowledged")),
        default=0,
    )
    scaffolding = sum(
        1
        for entry in ledger.get("rounds", [])
        if entry["round"] >= acknowledged
        for finding in entry.get("findings", [])
        if finding.get("blocking") and finding.get("subject") == "review-scaffolding"
    )
    if scaffolding > SCAFFOLDING_CAP:
        reasons.append(("scaffolding",
            f"scaffolding stop: {scaffolding} blocking finding(s) target the review "
            f"apparatus rather than the work (cap {SCAFFOLDING_CAP}). A loop bounded "
            "only by volume converges on its own instrumentation (V43). Take the "
            "scaffolding findings to a separate change, or a named human acknowledges "
            f"them and continues: continue --loop-id {ledger['loop_id']} --rounds 1 {lift}."))

    current = instrument_digest()
    if ledger.get("instrument_digest") and ledger["instrument_digest"] != current:
        reasons.append(("instrument",
            "instrument-drift stop: the verdict schema changed mid-loop (opened at "
            f"{ledger['instrument_digest'][:12]}, now {current[:12]}). Earlier rounds "
            "were judged against different rules, so the counts above are not "
            "comparable. Close this loop and open a new one, or a named human re-pins "
            f"the schema and continues: continue --loop-id {ledger['loop_id']} --rounds 1 "
            f"{lift}."))

    return reasons


def bullets(reasons: list[tuple[str, str]]) -> str:
    return "\n".join(f"  - [{kind}] {message}" for kind, message in reasons)


def stop_readout(ledger: dict) -> str:
    """STOP_READOUT -- the seven lines every REFUSE from ``evaluate``/``record`` ends with.

    Order is the contract, not decoration: intent first, because a refusal that opens
    with a count invites fixing the count; the exact ``continue`` command last, because
    the person reading it decides whether to run it. Between them, the state that
    decision needs -- latest ``intent_achieved``, the open blockers with what they
    violate, rounds, tokens, the mechanism tally.
    """
    rounds = ledger.get("rounds", [])
    latest = rounds[-1] if rounds else None
    achieved = latest.get("intent_achieved", "?") if latest else "no round recorded yet"
    blockers = [
        f"{f['id']} ({f.get('violates') or 'uncited'})"
        for f in (latest or {}).get("findings", [])
        if f.get("blocking")
    ]
    spent, reserve, token_budget = tokens_spent(ledger)
    relieved = relieved_mechanisms(ledger)
    tally = ", ".join(
        f"{slug}: {count}/{MECHANISM_LIMIT}" + (" relieved" if slug in relieved else "")
        for slug, count in sorted(mechanism_counts(ledger).items())
    ) or "none"

    active = {kind for kind, _ in stops(ledger)}
    flags: list[str] = []
    if "tokens" in active:
        flags.append(f"--tokens {spent + reserve - token_budget:,}".replace(",", "_"))
    if "mechanism" in active:
        stopped = [
            slug for slug, count in sorted(mechanism_counts(ledger).items())
            if count >= MECHANISM_LIMIT and slug not in relieved
        ]
        flags.append(f"--relieve-mechanism {stopped[0]}")
        if len(stopped) > 1:
            flags.append(f"(then one continue per remaining slug: {', '.join(stopped[1:])})")
    if "budget" in active or not flags:
        # The act itself lifts scaffolding and instrument, but a continue must buy
        # something; one round is the natural something. With nothing active this is
        # the template, not an instruction.
        flags.insert(0, "--rounds 1")
    command = (
        f"continue --loop-id {ledger['loop_id']} {' '.join(flags)} "
        f"--said \"<at least {MIN_RATIONALE} characters>\" --by <name> --at <ISO-8601>"
    )
    return "\n".join([
        f"  intent      {ledger.get('goal_anchor') or '(no goal registered)'}",
        f"  achieved    {achieved}",
        f"  blocking    {', '.join(blockers) or 'none'}",
        f"  rounds      {len(rounds)}/{rounds_allowed(ledger)}",
        f"  tokens      {spent:,}/{token_budget:,} (next round reserved at {reserve:,})",
        f"  mechanisms  {tally}",
        f"  continue    {command}" + ("" if active else "  (no stop active)"),
    ])


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


def normalize_anchor(text: str) -> str:
    """INTENT_BINDING's normalization: NFC, casefold, one space per whitespace run, no
    leading/trailing whitespace, no terminal period. Strict enough that an anchor about
    other work cannot contain the goal by accident; loose enough that quoting it with
    different casing or line breaks still counts as quoting it."""
    import unicodedata

    folded = " ".join(unicodedata.normalize("NFC", text).casefold().split())
    return folded[:-1].rstrip() if folded.endswith(".") else folded


def load_ac_ids(path: Path) -> list[str]:
    """Every ``AC-<n>[a-z]`` the plan names, derived from the file -- never typed (AC-7)."""
    if not path.is_file():
        raise FailClosed(f"--ac-file not found: {path}. The citable AC set is read from the plan, so without it no blocker could ever be recorded.")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FailClosed(f"--ac-file {path} is unreadable: {exc}") from exc
    ids = sorted(set(AC_ID.findall(text)), key=lambda s: (len(s), s))
    if not ids:
        raise Refuse(
            f"--ac-file {path} names no AC-<n> identifiers. A loop with nothing to cite "
            "cannot record a blocker, so it is refused at begin rather than at round one."
        )
    return ids


def load_vocabulary(path: Path) -> set[str]:
    """The closed set of mechanism slugs (``mechanisms[].id``) from the catalogue."""
    if not path.is_file():
        raise FailClosed(f"vocabulary not found: {path}")
    try:
        import yaml
    except ImportError as exc:
        raise FailClosed(
            "PyYAML is not installed, so the mechanism vocabulary could not be read. "
            "Install with: pip install pyyaml"
        ) from exc
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FailClosed(f"vocabulary {path} is unreadable: {exc}") from exc
    slugs = {
        m.get("id")
        for m in (doc or {}).get("mechanisms", []) or []
        if isinstance(m, dict) and isinstance(m.get("id"), str)
    }
    if not slugs:
        raise FailClosed(f"vocabulary {path} lists no mechanisms[].id -- an empty closed set refuses every control-defeat")
    return slugs


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
    token_budget = getattr(args, "token_budget", None)
    if token_budget is None:
        token_budget = TOKEN_BUDGETS[args.review_mode]
    elif token_budget < 1:
        raise Refuse(f"--token-budget must be a positive integer (got {token_budget})")

    # Intent is registered at the door. A loop that never said what it was for cannot
    # have a verdict judged against it, and the citable AC set comes from the plan file.
    goal = (getattr(args, "goal_anchor", None) or "").strip()
    if len("".join(goal.split())) < MIN_RATIONALE:
        raise Refuse(
            f"--goal-anchor must be one sentence of intent with at least {MIN_RATIONALE} "
            f"non-whitespace characters (got {len(''.join(goal.split()))}); every verdict "
            "in this loop must quote it."
        )
    ac_file = getattr(args, "ac_file", None)
    if not ac_file:
        raise Refuse("--ac-file is required: the AC identifiers a blocker may cite are read from the plan, never typed.")
    ac_ids = load_ac_ids(Path(ac_file))
    vocabulary = Path(getattr(args, "vocabulary", None) or VOCABULARY_PATH)
    load_vocabulary(vocabulary)  # fail at begin, not at round one

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
        "token_budget": token_budget,
        "producer": args.producer,
        "opened": datetime.date.today().isoformat(),
        "instrument_digest": instrument_digest(),
        "rounds": [],
        "grants": [],
        "mechanism_reliefs": [],
        "goal_anchor": goal,
        "ac_ids": ac_ids,
        "vocabulary_path": str(vocabulary),
    }
    save_ledger(ledger)
    print(
        f"OK: opened loop {args.loop_id!r} mode={args.review_mode} "
        f"budget={ledger['round_budget']} tokens={token_budget:,} producer={args.producer!r}"
    )
    print(f"     intent: {goal}")
    print(f"     citable: {', '.join(ac_ids)}  vocabulary: {vocabulary}")
    print(f"     ledger: {path}")
    return 0


def cmd_record(args) -> int:
    ledger = load_ledger(args.loop_id)

    def refusal(message: str) -> Refuse:
        # Every REFUSE from record ends with STOP_READOUT (AC-10).
        return Refuse(f"{message}\n{stop_readout(ledger)}")

    try:
        verdict = load_verdict(Path(args.verdict_file))
    except Refuse as exc:
        raise refusal(str(exc)) from None

    if verdict["loop_id"] != args.loop_id:
        raise refusal(
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
        raise refusal(
            f"verdict declares review_mode {verdict['review_mode']!r} but this loop was "
            f"opened as {ledger['review_mode']!r}. A {verdict['review_mode']!r} review does "
            f"not discharge a {ledger['review_mode']!r} one, and recording it here would "
            f"let the loop close on evidence nobody asked for. Re-run the review in "
            f"{ledger['review_mode']!r} mode, or open a separate loop for the "
            f"{verdict['review_mode']!r} pass."
        )

    # The self-review prohibition. The one rule that never bends.
    if verdict["agent"] == ledger["producer"]:
        raise refusal(
            f"agent {verdict['agent']!r} produced the work under review in this loop. "
            "The agent that produced the work never authors its own verdict. If no "
            "independent reviewer is reachable, the work stops and waits for a human "
            "-- self-review is not a fallback."
        )

    # INTENT_BINDING: the verdict must quote this loop's registered goal inside its own
    # intent_anchor. Containment after normalization is the strictest comparison that
    # is deterministic and needs no model; an anchor about other work cannot satisfy it.
    goal = ledger.get("goal_anchor")
    if not goal:
        raise FailClosed(
            f"loop {ledger['loop_id']!r} has no goal_anchor registered, so the verdict's "
            "intent cannot be checked. Open loops with begin --goal-anchor."
        )
    anchor = verdict["intent_anchor"]
    if normalize_anchor(goal) not in normalize_anchor(anchor):
        raise refusal(
            "intent-anchor-mismatch: the verdict does not name this loop's registered "
            f"goal.\n  registered goal: {goal!r}\n  offered anchor:  {anchor!r}"
        )
    achieved = verdict["intent_achieved"]
    blocking_count = sum(1 for f in verdict["findings"] if f.get("blocking"))
    if achieved == "yes" and blocking_count == 0 and verdict["verdict"] != "approved":
        raise refusal(
            f"intent_achieved is 'yes' with no blocking finding, yet the verdict is "
            f"{verdict['verdict']!r}. Achieved intent and nothing blocking is an approval; "
            "anything else is reluctance recorded as a defect."
        )
    if verdict["verdict"] == "approved" and achieved != "yes":
        raise refusal(
            f"verdict is 'approved' but intent_achieved is {achieved!r}. An approval "
            "asserts the intent was achieved; if it was not, the finding that says so is "
            "a blocker and the verdict is changes_required."
        )

    # A blocker cites the contract it violates, from the set the plan itself defines
    # (AC-7); a control-defeat names a mechanism the closed vocabulary knows (AU-RT-15).
    ac_ids = set(ledger.get("ac_ids") or [])
    vocabulary = load_vocabulary(Path(ledger.get("vocabulary_path") or VOCABULARY_PATH))
    for f in verdict["findings"]:
        if f.get("blocking"):
            cited = f.get("violates")
            if not cited:
                raise refusal(
                    f"blocking finding {f['id']!r} cites no violated contract (`violates`). "
                    "A finding that cannot cite its violated contract is an observation, "
                    f"not a blocker. Citable here: {', '.join(sorted(ac_ids)) or '(none)'}."
                )
            if cited not in ac_ids:
                raise refusal(
                    f"blocking finding {f['id']!r} cites {cited!r}, which is not in this "
                    f"loop's registered set: {', '.join(sorted(ac_ids)) or '(none)'}."
                )
        if f.get("finding_kind") == "control-defeat" and f.get("mechanism") not in vocabulary:
            raise refusal(
                f"finding {f['id']!r} names mechanism {f.get('mechanism')!r}, which the "
                f"closed vocabulary does not know ({ledger.get('vocabulary_path')}). Reuse "
                "the catalogued mechanism this defeat belongs to; add a mechanism to the "
                "catalogue only when the control itself is new (AU-RT-15)."
            )

    # Stops are checked BEFORE the round is written: a refused round must not consume
    # budget, or a caller could exhaust a loop by submitting invalid verdicts.
    blocked = stops(ledger)
    if blocked:
        raise refusal("cannot record another round.\n" + bullets(blocked))

    expected = len(ledger["rounds"]) + 1
    if verdict["round"] != expected:
        raise refusal(
            f"verdict claims round {verdict['round']} but the ledger's next round is "
            f"{expected}. The ledger is authoritative. A mismatch usually means a "
            "round was recorded elsewhere, or a verdict is being replayed."
        )

    # What the round cost, from the dispatch receipt. No receipt, or a receipt with no
    # usage in it, is an unmeasured round: recorded as such, charged nothing (AC-4).
    receipt = getattr(args, "usage_receipt", None)
    usage = read_usage(Path(receipt)) if receipt else None

    findings = [
        {
            "id": f["id"],
            "blocking": f["blocking"],
            "subject": f["subject"],
            "finding_kind": f["finding_kind"],
            **({"mechanism": f["mechanism"]} if f.get("mechanism") else {}),
            **({"violates": f["violates"]} if f.get("violates") else {}),
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
            "usage": usage,
            "unmeasured": usage is None,
            "intent_achieved": achieved,
        }
    )
    save_ledger(ledger)

    print(
        f"OK: recorded round {expected} verdict={verdict['verdict']} "
        f"agent={verdict['agent']!r} blocking={ledger['rounds'][-1]['blocking']} "
        f"intent_achieved={achieved} "
        f"usage={'unmeasured' if usage is None else format(usage, ',')}"
    )
    if verdict["verdict"] == "approved":
        print("     loop may close: approved with no blocking findings.")
    else:
        remaining = stops(ledger)
        if remaining:
            print("     next round is REFUSED:")
            print(bullets(remaining))
        else:
            print(
                f"     next round permitted ({len(ledger['rounds'])}/{rounds_allowed(ledger)} used)."
            )
    return 0


def cmd_evaluate(args) -> int:
    ledger = load_ledger(args.loop_id)

    # INTENT_BINDING before inference: a reviewer can only quote the registered goal if
    # the prompt carries it, so a payload that omits it is refused here, at zero cost,
    # rather than by `record` after a round has been paid for.
    payload = getattr(args, "payload", None)
    if payload:
        path = Path(payload)
        if not path.is_file():
            raise FailClosed(f"--payload not found: {path}")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise FailClosed(f"--payload {path} is unreadable: {exc}") from exc
        goal = ledger.get("goal_anchor")
        if not goal:
            raise FailClosed(
                f"loop {ledger['loop_id']!r} has no goal_anchor registered, so the payload "
                "cannot be checked. Open loops with begin --goal-anchor."
            )
        if normalize_anchor(goal) not in normalize_anchor(text):
            raise Refuse(
                "goal-anchor: the prompt does not contain this loop's registered goal, so "
                "no verdict it produces could quote it (INTENT_BINDING).\n"
                f"  registered goal: {goal!r}\n  payload: {path}\n" + stop_readout(ledger)
            )

    blocked = stops(ledger)
    if blocked:
        raise Refuse(
            "another round is not permitted.\n" + bullets(blocked) + "\n" + stop_readout(ledger)
        )
    budget = rounds_allowed(ledger)
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


def cmd_continue(args) -> int:
    """A named human continues the loop past whatever stopped it (CONTINUE_LIFTS).

    The one escape hatch, and it is uncapped: the stops exist to keep an *unattended*
    loop from spending API budget forever, not to overrule a person who is watching it.
    What the person pays is legibility -- a rationale of real length, their name, a
    timestamp -- and the record of exactly which stops the act lifted. ``budget`` lifts
    via ``--rounds``, ``tokens`` via ``--tokens``, ``mechanism`` via the named slug;
    ``scaffolding`` (acknowledged) and ``instrument`` (digest re-pinned) lift by the act
    itself. A stop this continue could not lift is recorded as still active and printed,
    so a round bought against a mechanism stop reads as exactly that.

    Structural mistakes -- buying nothing, a malformed timestamp -- are USAGE (exit 2),
    not REFUSE: nothing was decided about the loop.
    """
    ledger = load_ledger(args.loop_id)
    rounds = getattr(args, "rounds", 0) or 0
    tokens = getattr(args, "tokens", 0) or 0
    slug = getattr(args, "relieve_mechanism", None)
    said = getattr(args, "said", "") or ""
    by = getattr(args, "by", "") or ""
    at = getattr(args, "at", "") or ""

    if rounds < 0 or tokens < 0 or (rounds == 0 and tokens == 0 and not slug):
        print(
            "USAGE: continue must buy something -- --rounds N and/or --tokens T above "
            "zero, or --relieve-mechanism SLUG."
        )
        return 2
    try:
        datetime.datetime.fromisoformat(at)
    except ValueError:
        print(f"USAGE: --at must be an ISO-8601 timestamp (got {at!r}).")
        return 2
    if not by.strip():
        raise Refuse("--by must name a person. An unattributed override is not one.")
    substance = len("".join(said.split()))
    if substance < MIN_RATIONALE:
        raise Refuse(
            f"--said is the rationale for continuing and must carry at least "
            f"{MIN_RATIONALE} non-whitespace characters (got {substance}). Every observed "
            "bypass of this control was a one-word justification, so the length floor "
            "is the control."
        )
    if slug:
        if not MECHANISM.match(slug):
            raise Refuse(f"--relieve-mechanism {slug!r} must match {MECHANISM.pattern}")
        counts = mechanism_counts(ledger)
        if slug not in counts:
            raise Refuse(
                f"mechanism {slug!r} has no blocking control-defeat findings in this "
                "loop, so there is nothing to relieve. Relieving an unseen mechanism "
                f"pre-authorizes a stop that has not fired. Seen: "
                f"{', '.join(sorted(counts)) or '(none)'}"
            )
        if slug in relieved_mechanisms(ledger):
            raise Refuse(f"mechanism {slug!r} is already relieved in this loop.")

    active = {kind for kind, _ in stops(ledger)}
    at_round = len(ledger["rounds"]) + 1
    record = {
        "round": at_round,
        "owner": by,
        "granted": at,
        "said": said,
        "rounds": rounds,
        "tokens": tokens,
        "lifted": [],
        "scaffolding_acknowledged": "scaffolding" in active,
    }
    ledger["grants"].append(record)
    if slug:
        ledger["mechanism_reliefs"].append(
            {"mechanism": slug, "owner": by, "rationale": said, "round": at_round}
        )
    if "instrument" in active:
        ledger["instrument_digest"] = instrument_digest()
    remaining = stops(ledger)
    record["lifted"] = sorted(active - {kind for kind, _ in remaining})
    save_ledger(ledger)

    if record["lifted"]:
        outcome = f"lifted {', '.join(record['lifted'])}"
    elif active:
        outcome = "lifted nothing"
    else:
        outcome = "no stop was active"
    spent, _, token_budget = tokens_spent(ledger)
    print(
        f"OK: continue recorded by {by} at {at}: +{rounds} round(s), +{tokens:,} tokens"
        + (f", relieved {slug!r}" if slug else "")
        + f"; {outcome}"
    )
    print(
        f"     rounds {len(ledger['rounds'])}/{rounds_allowed(ledger)}  "
        f"tokens {spent:,}/{token_budget:,}"
    )
    if remaining:
        print("     still stopped -- this continue did not lift:")
        print(bullets(remaining))
    return 0


def cmd_state(args) -> int:
    ledger = load_ledger(args.loop_id)
    budget = rounds_allowed(ledger)
    blocked = stops(ledger)
    print(f"OK: loop {ledger['loop_id']!r} mode={ledger['review_mode']}")
    print(f"     intent     {ledger.get('goal_anchor') or '(no goal registered)'}")
    print(f"     opened     {ledger['opened']}  producer={ledger['producer']!r}")
    print(f"     rounds     {len(ledger['rounds'])}/{budget}"
          f" (base {ledger['round_budget']} + {budget - ledger['round_budget']} bought by "
          f"{len(ledger['grants'])} continue(s))")
    spent, reserve, token_budget = tokens_spent(ledger)
    print(f"     tokens     {spent:,}/{token_budget:,} spent, next round reserved at {reserve:,}")
    for entry in ledger["rounds"]:
        usage = entry.get("usage")
        print(
            f"       r{entry['round']} {entry['verdict']:<17} "
            f"agent={entry['agent']!r} blocking={entry['blocking']} "
            f"intent_achieved={entry.get('intent_achieved', '?')} "
            f"usage={'unmeasured' if usage is None or entry.get('unmeasured') else format(usage, ',')}"
        )
    counts = mechanism_counts(ledger)
    relieved = relieved_mechanisms(ledger)
    if counts:
        print("     mechanisms (blocking control-defeat):")
        for slug, count in sorted(counts.items()):
            mark = " [RELIEVED]" if slug in relieved else ""
            print(f"       {slug}: {count}/{MECHANISM_LIMIT}{mark}")
    acknowledged = [g["round"] for g in ledger["grants"] if g.get("scaffolding_acknowledged")]
    print(f"     scaffolding {scaffolding_count(ledger)}/{SCAFFOLDING_CAP}"
          + (f" (acknowledged by continue before r{max(acknowledged)})" if acknowledged else ""))
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

    # Every loop the selftest opens is registered against this intent, this plan and this
    # catalogue; `arm()` supplies them to every cmd_begin call so no arm can open a loop
    # that skipped the door.
    GOAL = "Bounded independent review of the example plan"
    begin_defaults: dict = {}

    def verdict_doc(loop, rnd, agent="reviewer-a", verdict="changes_required",
                    findings=None, mode="plan", intent_anchor=GOAL, intent_achieved=None):
        """``mode`` is a parameter, not a constant, and that is the point.

        It used to be hardcoded to ``"plan"`` while three of the four loops below were
        opened as ``execution``. Those arms passed -- ``record`` never compared the two
        -- so the suite's own fixtures asserted that a plan verdict belongs in an
        execution loop. A test that encodes the defect protects it: once ``record``
        started checking, the fixtures were the first thing that had to be corrected,
        which is how a hardcoded fixture value becomes a second copy of the contract.
        ``intent_achieved`` defaults to the value consistent with the verdict; the
        intent arms pass it explicitly.
        """
        doc = {
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
            "intent_achieved": intent_achieved or ("yes" if verdict == "approved" else "partial"),
            "findings": findings if findings is not None else [],
            "checklist_results": [
                {"check": "c", "result": "pass", "command": "true", "exit_code": 0,
                 "evidence": "e"}
            ],
        }
        if intent_anchor is not None:
            doc["intent_anchor"] = intent_anchor
        return doc

    def finding(fid, kind="behavior", mech=None, subject="deliverable", blocking=True,
                violates="AC-1"):
        f = {
            "id": fid, "severity": "High", "confidence": "High", "blocking": blocking,
            "subject": subject, "finding_kind": kind, "finding": "f",
            "file_line": "a.py:1", "recommendation": "r", "status": "open",
        }
        if mech:
            f["mechanism"] = mech
        if violates and blocking:
            f["violates"] = violates
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
        if fn is cmd_begin:
            kw = {**begin_defaults, **kw}
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

            def write_text(name, text):
                path = vdir / name
                path.write_text(text, encoding="utf-8")
                return str(path)

            # The plan every loop cites (three ACs, one with a letter suffix, one of them
            # mentioned twice so the derived set is a set) and the closed catalogue.
            plan_file = write_text(
                "example-plan.md",
                "# Example\n| AC-1 | x |\n| AC-2 | y |\n| AC-3a | z |\nAC-1 is cited twice.\n",
            )
            vocab_file = write_text(
                "vocabulary.yaml",
                "mechanisms:\n"
                "  - id: swallowed-exit-code\n"
                "  - id: detector-without-fixture\n"
                "  - id: verdict-to-state-transition\n",
            )
            begin_defaults.update(
                goal_anchor=GOAL, ac_file=plan_file, vocabulary=vocab_file
            )
            begin_cli = ["--goal-anchor", GOAL, "--ac-file", plan_file,
                         "--vocabulary", vocab_file]

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
            # `continue` is the one escape hatch. Nineteen non-whitespace characters is
            # the boundary AC-5 names, and the padding proves whitespace is not counted.
            arm("continue-short-said-refused", "REFUSE", cmd_continue, loop_id="loop-a",
                must_say="rationale", rounds=1, said="  regression  in  round  33  ",
                by="release-owner", at="2026-09-21T12:00:00")
            arm("continue-ok", "OK", cmd_continue, loop_id="loop-a",
                must_say="OK: continue", rounds=1,
                said="Reviewer found a real regression in round 3; one more round.",
                by="release-owner", at="2026-09-21T12:00:00")
            arm("evaluate-after-continue-ok", "OK", cmd_evaluate, loop_id="loop-a")

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
            # Two mechanisms per round, so relief can be shown to be per slug (AC-6).
            for i in (1, 2, 3):
                arm(f"mech-round-{i}", "OK", cmd_record, loop_id="loop-m",
                    verdict_file=write(f"m{i}.json", verdict_doc(
                        "loop-m", i, mode="execution", findings=[
                            finding(f"M{i}", kind="control-defeat",
                                    mech="swallowed-exit-code"),
                            finding(f"D{i}", kind="control-defeat",
                                    mech="detector-without-fixture"),
                        ])))
            # Note the state this arm runs against: loop-m is at 3 of 6 execution
            # rounds, so the budget stop is NOT active. The refusal has to come from
            # the mechanism clause or it proves nothing.
            arm("mechanism-stop-refused", "REFUSE", cmd_evaluate, loop_id="loop-m",
                must_say="[mechanism] mechanism-class stop")
            # Buying a round does not touch a mechanism stop. The record is written --
            # the human's act is real -- but the loop stays refused and the tool says so.
            arm("continue-rounds-does-not-clear-mechanism", "OK", cmd_continue,
                loop_id="loop-m", must_say="still stopped", rounds=1,
                said="Please just let the loop continue one more round.",
                by="release-owner", at="2026-09-21T12:00:00")
            arm("mechanism-still-stopped-after-rounds", "REFUSE", cmd_evaluate,
                loop_id="loop-m", must_say="[mechanism]")
            arm("continue-relieve-unseen-mechanism-refused", "REFUSE", cmd_continue,
                must_say="nothing to relieve", loop_id="loop-m",
                relieve_mechanism="never-happened",
                said="Pre-authorizing a stop that has not fired yet.",
                by="release-owner", at="2026-09-21T12:00:00")
            # AC-6: both mechanisms sit at the limit; relieving one leaves `evaluate`
            # refusing on the other, by name.
            arm("continue-relieve-swallowed-exit-code", "OK", cmd_continue,
                loop_id="loop-m", relieve_mechanism="swallowed-exit-code",
                said="Three instances were in vendored code excluded from scope.",
                by="release-owner", at="2026-09-21T12:00:00")
            arm("continue-relieves-named-mechanism-only", "REFUSE", cmd_evaluate,
                loop_id="loop-m", must_say="share mechanism 'detector-without-fixture'")
            arm("continue-relieve-second-mechanism", "OK", cmd_continue,
                loop_id="loop-m", relieve_mechanism="detector-without-fixture",
                must_say="lifted mechanism",
                said="The detector fixture landed in round 3; the class is closed.",
                by="release-owner", at="2026-09-21T12:00:00")
            arm("evaluate-after-relief-ok", "OK", cmd_evaluate, loop_id="loop-m")
            arm("continue-relieve-twice-refused", "REFUSE", cmd_continue,
                loop_id="loop-m", must_say="already relieved",
                relieve_mechanism="swallowed-exit-code",
                said="Trying the same relief a second time for no reason.",
                by="release-owner", at="2026-09-21T12:00:00")

            # --- scaffolding stop (cap 2; lifted only by continue, further down) --
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

            # --- continue lifts every stop class (CONTINUE_LIFTS, AC-5) --------
            # After the cli arms on purpose: `cli-refuse-is-1-REFUSE` needs loop-s still
            # refused, and this is what un-refuses it.
            arm("continue-lifts-scaffolding-stop", "OK", cmd_continue, loop_id="loop-s",
                must_say="lifted scaffolding", rounds=1,
                said="The three scaffolding findings are acknowledged and filed separately.",
                by="release-owner", at="2026-09-21T12:00:00")
            arm("evaluate-after-scaffolding-lift-ok", "OK", cmd_evaluate, loop_id="loop-s")
            results.append((
                "continue-records-lifted-stops",
                "['scaffolding']",
                str(load_ledger("loop-s")["grants"][-1]["lifted"]),
            ))
            arm("continue-lifts-instrument-stop", "OK", cmd_continue, loop_id="loop-n",
                must_say="lifted instrument", rounds=1,
                said="Schema digest re-pinned after a deliberate mid-loop schema fix.",
                by="release-owner", at="2026-09-21T12:00:00")
            arm("evaluate-after-instrument-lift-ok", "OK", cmd_evaluate, loop_id="loop-n")

            # Uncapped: the stops protect an unattended loop; they do not overrule a
            # person. Ten in a row, all OK, and the allowance is base 3 + 10.
            arm("begin-continue-loop", "OK", cmd_begin, loop_id="loop-c",
                review_mode="plan", producer="builder-x")
            outcomes = [
                run_verb(cmd_continue, loop_id="loop-c", rounds=1,
                         said=f"Continue number {n} of ten, proving there is no count cap.",
                         by="release-owner", at="2026-09-21T12:00:00")[0]
                for n in range(1, 11)
            ]
            results.append((
                "continue-ten-times-all-ok",
                "10 OK, allowed=13",
                f"{outcomes.count('OK')} OK, allowed={rounds_allowed(load_ledger('loop-c'))}",
            ))
            # Buying nothing and a malformed timestamp are usage errors, not decisions.
            results.append((
                "continue-zero-of-everything-is-usage-error",
                "2/USAGE",
                cli(["continue", "--loop-id", "loop-c", "--rounds", "0",
                     "--said", "A rationale long enough to pass the floor.",
                     "--by", "release-owner", "--at", "2026-09-21T12:00:00"]),
            ))
            results.append((
                "continue-bad-timestamp-is-usage-error",
                "2/USAGE",
                cli(["continue", "--loop-id", "loop-c", "--rounds", "1",
                     "--said", "A rationale long enough to pass the floor.",
                     "--by", "release-owner", "--at", "yesterday-ish"]),
            ))

            # --- token budget (TOKENS_STOP, AC-3 / AC-4) ---------------------
            # The oracle is the boundary itself. One measured round of 60 makes the
            # reserve for the next round another 60: a budget of 119 is over by one and
            # refused, a budget of 120 is exactly spent and permitted -- the clause is
            # `>`, and a `>=` would refuse a loop holding precisely what it needs.
            spent60 = write_text(
                "usage-60.jsonl",
                '{"type":"turn.completed","usage":{"input_tokens":40,"output_tokens":20}}\n',
            )
            arm("begin-token-loop-over", "OK", cmd_begin, loop_id="loop-t1",
                review_mode="plan", producer="builder-x", token_budget=119)
            arm("record-usage-charged", "OK", cmd_record, loop_id="loop-t1",
                must_say="usage=60", usage_receipt=spent60,
                verdict_file=write("t1.json", verdict_doc(
                    "loop-t1", 1, findings=[finding("T1")])))
            arm("tokens-stop-fires-over-budget", "REFUSE", cmd_evaluate, loop_id="loop-t1",
                must_say="[tokens] tokens: 60 spent + 60 reserved")
            arm("begin-token-loop-exact", "OK", cmd_begin, loop_id="loop-t2",
                review_mode="plan", producer="builder-x", token_budget=120)
            arm("record-usage-exact", "OK", cmd_record, loop_id="loop-t2",
                usage_receipt=spent60,
                verdict_file=write("t2.json", verdict_doc(
                    "loop-t2", 1, findings=[finding("T2")])))
            arm("tokens-stop-silent-under-budget", "OK", cmd_evaluate, loop_id="loop-t2")
            # One token moves the boundary, and `--rounds 0` proves tokens alone buy it.
            arm("continue-tokens-ok", "OK", cmd_continue, loop_id="loop-t1",
                must_say="lifted tokens", rounds=0, tokens=1,
                said="One more token, to prove the lift moves the boundary.",
                by="release-owner", at="2026-09-21T12:00:00")
            arm("tokens-stop-lifted-by-continue-tokens", "OK", cmd_evaluate,
                loop_id="loop-t1")

            # --- intent, citations, closed vocabulary (AC-7..AC-10, AU-RT-15) --
            # Registration at the door: no goal, no citable set, unknown catalogue.
            arm("begin-short-goal-refused", "REFUSE", cmd_begin, loop_id="loop-g",
                must_say="--goal-anchor", review_mode="plan", producer="builder-x",
                goal_anchor="too short")
            arm("begin-plan-without-acs-refused", "REFUSE", cmd_begin, loop_id="loop-g",
                must_say="names no AC", review_mode="plan", producer="builder-x",
                ac_file=write_text("no-acs.md", "# nothing to cite here\n"))
            arm("begin-missing-vocabulary-fails-closed", "FAIL-CLOSED", cmd_begin,
                loop_id="loop-g", must_say="vocabulary not found", review_mode="plan",
                producer="builder-x", vocabulary=str(vdir / "absent.yaml"))

            # Blockers cite the contract they violate, from the set the plan defines. The two
            # refusal arms run on their own loops: a mutant that neuters a guard would otherwise
            # record the refused verdict and derail every later arm on the shared loop, so the
            # mutation control could not tell "this guard's arm" from "everything downstream".
            arm("begin-violates-loop", "OK", cmd_begin, loop_id="loop-v",
                must_say="citable: AC-1, AC-2, AC-3a", review_mode="plan",
                producer="builder-x")
            arm("begin-no-violates-loop", "OK", cmd_begin, loop_id="loop-v0",
                review_mode="plan", producer="builder-x")
            arm("blocker-without-violates-refused", "REFUSE", cmd_record, loop_id="loop-v0",
                must_say="blocking finding 'V0' cites no violated contract",
                verdict_file=write("v0.json", verdict_doc(
                    "loop-v0", 1, findings=[finding("V0", violates=None)])))
            arm("begin-unknown-ac-loop", "OK", cmd_begin, loop_id="loop-v9",
                review_mode="plan", producer="builder-x")
            arm("blocker-violates-unknown-ac-refused", "REFUSE", cmd_record, loop_id="loop-v9",
                must_say="'V9' cites 'AC-99'",
                verdict_file=write("v9.json", verdict_doc(
                    "loop-v9", 1, findings=[finding("V9", violates="AC-99")])))
            registered = load_ledger("loop-v")["ac_ids"]
            accepted = [
                run_verb(cmd_record, loop_id="loop-v",
                         verdict_file=write(f"v-{ac}.json", verdict_doc(
                             "loop-v", i, findings=[finding(f"V{i}", violates=ac)])))[0]
                for i, ac in enumerate(registered, 1)
            ]
            results.append((
                "every-plan-ac-accepted-as-citation",
                "3/3 OK (AC-1, AC-2, AC-3a)",
                f"{accepted.count('OK')}/{len(registered)} OK ({', '.join(registered)})",
            ))
            arm("begin-nonblocker-loop", "OK", cmd_begin, loop_id="loop-nb",
                review_mode="plan", producer="builder-x")
            arm("non-blocker-without-violates-accepted", "OK", cmd_record, loop_id="loop-nb",
                verdict_file=write("nb.json", verdict_doc(
                    "loop-nb", 1, verdict="approved",
                    findings=[finding("NB1", blocking=False, violates=None)])))

            # A control-defeat names a mechanism the closed catalogue knows (AU-RT-15).
            arm("begin-unregistered-mechanism-loop", "OK", cmd_begin, loop_id="loop-vm0",
                review_mode="execution", producer="builder-x")
            arm("unregistered-mechanism-refused", "REFUSE", cmd_record, loop_id="loop-vm0",
                must_say="mechanism 'made-up-slug', which the closed vocabulary does not know",
                verdict_file=write("vm0.json", verdict_doc(
                    "loop-vm0", 1, mode="execution", findings=[finding(
                        "VM0", kind="control-defeat", mech="made-up-slug")])))
            arm("begin-vocabulary-loop", "OK", cmd_begin, loop_id="loop-vm",
                review_mode="execution", producer="builder-x")
            counted = [
                run_verb(cmd_record, loop_id="loop-vm",
                         verdict_file=write(f"vm{i}.json", verdict_doc(
                             "loop-vm", i, mode="execution", findings=[finding(
                                 f"VM{i}", kind="control-defeat",
                                 mech="verdict-to-state-transition")])))[0]
                for i in (1, 2, 3)
            ]
            results.append((
                "registered-mechanism-counted-to-limit",
                "3 OK, then REFUSE [mechanism]",
                f"{counted.count('OK')} OK, then "
                + (lambda s, t: f"{s} [mechanism]" if "[mechanism]" in t else f"{s} (not mechanism)")(
                    *run_verb(cmd_evaluate, loop_id="loop-vm")),
            ))

            # Intent: the verdict judges THIS loop's goal, and says whether it was met.
            arm("begin-intent-loop", "OK", cmd_begin, loop_id="loop-i",
                review_mode="plan", producer="builder-x")
            arm("missing-intent-field-refused", "REFUSE", cmd_record, loop_id="loop-i",
                must_say="'intent_anchor' is a required property",
                verdict_file=write("i-missing.json", verdict_doc(
                    "loop-i", 1, intent_anchor=None, findings=[finding("I0")])))
            # Own loop (see the violates arms above for why): the intent-consistency guard is
            # mutation-controlled, and a neutered guard would record this approval as round 1.
            arm("begin-intent-consistency-loop", "OK", cmd_begin, loop_id="loop-ia",
                review_mode="plan", producer="builder-x")
            arm("intent-yes-no-blockers-must-approve", "REFUSE", cmd_record, loop_id="loop-ia",
                must_say="intent_achieved",
                verdict_file=write("i-approved-no.json", verdict_doc(
                    "loop-ia", 1, verdict="approved", intent_achieved="no", findings=[])))
            arm("intent-yes-zero-blockers-changes-required-refused", "REFUSE", cmd_record,
                loop_id="loop-i",
                verdict_file=write("i-yes-cr.json", verdict_doc(
                    "loop-i", 1, verdict="changes_required", intent_achieved="yes",
                    findings=[])))
            # Schema-valid (32 characters, well over the floor) and about other work:
            # only the binding can refuse it, so a schema-only implementation fails here.
            _, mismatch_text = run_verb(cmd_record, loop_id="loop-i",
                verdict_file=write("i-other.json", verdict_doc(
                    "loop-i", 1, intent_anchor="Review database backup retention",
                    findings=[finding("I1")])))
            goal_at = mismatch_text.find(GOAL)
            anchor_at = mismatch_text.find("Review database backup retention")
            results.append((
                "intent-anchor-mismatch-refused",
                "intent-anchor-mismatch, goal named before anchor",
                ("intent-anchor-mismatch" if "intent-anchor-mismatch" in mismatch_text
                 else "other refusal")
                + (", goal named before anchor" if 0 <= goal_at < anchor_at
                   else f", order wrong (goal@{goal_at}, anchor@{anchor_at})"),
            ))
            arm("intent-anchor-normalized-match-accepted", "OK", cmd_record, loop_id="loop-i",
                verdict_file=write("i-norm.json", verdict_doc(
                    "loop-i", 1,
                    intent_anchor="As I read it:  " + GOAL.upper().replace(" ", "  ")
                                  + ".  Nothing beyond that was in scope.",
                    findings=[finding("I1")])))
            arm("intent-yes-with-cited-blocker-accepted", "OK", cmd_record, loop_id="loop-i",
                must_say="intent_achieved=yes",
                verdict_file=write("i-yes-blocker.json", verdict_doc(
                    "loop-i", 2, intent_achieved="yes",
                    findings=[finding("I2", kind="control-defeat",
                                      mech="swallowed-exit-code")])))

            # evaluate --payload: the prompt about to be dispatched must carry the goal
            # (INTENT_BINDING before inference, AC-11 (e)); a payload that does is silent.
            arm("payload-without-goal-refused", "REFUSE", cmd_evaluate, loop_id="loop-i",
                must_say="goal-anchor: the prompt does not contain",
                payload=write_text("payload-other.txt",
                                   "Please review database backup retention thoroughly.\n"))
            arm("payload-with-goal-ok", "OK", cmd_evaluate, loop_id="loop-i",
                payload=write_text("payload-goal.txt",
                                   f"Review prompt.\n\nIntent: {GOAL}.\n\nChecklist follows.\n"))
            arm("payload-missing-fails-closed", "FAIL-CLOSED", cmd_evaluate, loop_id="loop-i",
                must_say="--payload not found", payload=str(vdir / "no-such-prompt.txt"))

            # STOP_READOUT order, by index: intent is the first of the seven closing
            # lines and the continue command is the last. loop-vm is refused on its
            # mechanism stop at this point, which is why this arm sits here.
            _, readout_text = run_verb(cmd_evaluate, loop_id="loop-vm")
            tail = readout_text.splitlines()[-7:]
            results.append((
                "readout-order-intent-first-continue-last",
                "intent first, continue last",
                ("intent first" if tail and tail[0].strip().startswith("intent") else "wrong first")
                + ", "
                + ("continue last" if tail and tail[-1].strip().startswith("continue") else "wrong last"),
            ))

            # An unmeasured round is recorded as such, charged nothing, and visible in
            # `state` -- and a receipt path that does not exist is not "unmeasured", it is
            # a check that could not be performed.
            nousage = write_text("usage-none.jsonl", '{"type":"turn.completed"}\n')
            arm("begin-unmeasured-loop", "OK", cmd_begin, loop_id="loop-u",
                review_mode="plan", producer="builder-x", token_budget=119)
            arm("record-unmeasured", "OK", cmd_record, loop_id="loop-u",
                must_say="usage=unmeasured", usage_receipt=nousage,
                verdict_file=write("u1.json", verdict_doc(
                    "loop-u", 1, findings=[finding("U1")])))
            entry = load_ledger("loop-u")["rounds"][0]
            _, state_text = run_verb(cmd_state, loop_id="loop-u")
            results.append((
                "unmeasured-round-not-charged",
                "usage=None unmeasured=True spent=0 state=unmeasured evaluate=OK",
                f"usage={entry.get('usage')} unmeasured={entry.get('unmeasured')} "
                f"spent={tokens_spent(load_ledger('loop-u'))[0]} "
                f"state={'unmeasured' if 'usage=unmeasured' in state_text else 'silent'} "
                f"evaluate={run_verb(cmd_evaluate, loop_id='loop-u')[0]}",
            ))
            arm("missing-usage-receipt-fails-closed", "FAIL-CLOSED", cmd_record,
                loop_id="loop-u", must_say="usage receipt not found",
                usage_receipt=str(vdir / "nope.jsonl"),
                verdict_file=write("u2.json", verdict_doc(
                    "loop-u", 2, findings=[finding("U2")])))

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
                     "--producer", "builder-x", *begin_cli]),
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
    p.add_argument("--token-budget", type=int, default=None,
                   help="tokens the loop may spend (default: TOKEN_BUDGETS for the mode)")
    p.add_argument("--goal-anchor", required=True,
                   help="one sentence of intent every verdict in this loop must quote")
    p.add_argument("--ac-file", required=True, metavar="PLAN",
                   help="the plan whose AC-<n> identifiers a blocking finding may cite")
    p.add_argument("--vocabulary", default=None, metavar="FILE",
                   help=f"closed mechanism catalogue (default: {VOCABULARY_PATH})")
    p.set_defaults(func=cmd_begin)

    p = sub.add_parser("record", help="validate and record one round's verdict")
    p.add_argument("--loop-id", required=True)
    p.add_argument("--verdict-file", required=True)
    p.add_argument("--usage-receipt", default=None,
                   help="dispatch receipt (.jsonl events or text) the round's token usage is read from; "
                        "omit for an unmeasured round")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("evaluate", help="is another round permitted? (pre-dispatch check)")
    p.add_argument("--loop-id", required=True)
    p.add_argument("--payload", default=None, metavar="PROMPT",
                   help="the prompt about to be dispatched; refused if it omits the registered goal")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("continue",
                       help="a named human continues past every active stop (uncapped)")
    p.add_argument("--loop-id", required=True)
    p.add_argument("--rounds", type=int, default=0, help="extra rounds to allow")
    p.add_argument("--tokens", type=int, default=0, help="extra tokens to allow")
    p.add_argument("--relieve-mechanism", default=None, metavar="SLUG",
                   help="relieve this one mechanism stop (others stay stopped)")
    p.add_argument("--said", required=True,
                   help=f"the rationale, at least {MIN_RATIONALE} non-whitespace characters")
    p.add_argument("--by", required=True, help="the person continuing")
    p.add_argument("--at", required=True, help="when, ISO-8601")
    p.set_defaults(func=cmd_continue)

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
