#!/usr/bin/env python3
r"""adapt_output_schema.py -- the ONE implementation of the structured-output schema
adaptation, shared by both Codex dispatch wrappers.

Why this ships as a separate tool
---------------------------------
``codex exec --output-schema`` runs the structured-output endpoint in strict mode, which
rejects two things the shipped verdict schema legitimately contains:

1. JSON Schema's composition and conditional keywords (``allOf``, ``oneOf``, ``not``,
   ``if``, ``then``, ``else``) -- a 400 ``invalid_json_schema`` before the model is ever
   called.
2. Any optional property. At every object node ``required`` must name EVERY key in
   ``properties``, so a schema that models ``mechanism`` as conditionally required is
   refused outright ("Missing 'mechanism'").

Both adaptations are safe because the file handed to the API is a *generation aid*, not
the gate: the verdict is validated afterwards against the unmodified shipped schema by
``validate_json_schema.py``. The conditional requirements therefore still bind.

The adaptation used to be implemented twice -- once in PowerShell inside
``Invoke-CodexDispatch.ps1`` and once as a four-line inline heredoc inside
``Invoke-CodexDispatch.sh``. The two drifted, as duplicated logic does: the ``.ps1``
learned to recurse, to widen optionals and to strip the resulting nulls back out, and the
``.sh`` kept popping ``allOf`` from the root and nothing else. On POSIX that meant every
schema-constrained review died on a 400 naming a keyword nested under
``properties.findings.items`` -- a defect invisible on the maintainer's Windows machine,
where the other copy was correct. Two implementations of one rule is the defect; one
implementation both wrappers call is the fix, and it is why this is a Python file rather
than a third patch.

Verbs
-----
    adapt <shipped-schema.json> <api-schema.json>
        Write the API-acceptable adaptation of the shipped schema.

    strip-nulls <document.json> [--raw-copy <path>]
        Undo the nullable widening in a model's output: delete null-valued keys, in
        place, so the document matches the unmodified shipped schema again. With
        ``--raw-copy``, the pre-strip text is preserved there first -- a governance
        package must not rewrite a reviewer's output with no auditable copy of what it
        actually said. Nothing is written when there is nothing to strip.

    selftest
        Prove every clause above, in both directions, over the real shipped schema.

Exit codes
----------
    0  done (first stdout line begins ``OK:``)
    2  usage error (first line ``USAGE:``)
    3  the adaptation could not run -- unreadable, unparseable or unwritable input
       (first line ``FAIL-CLOSED:``)

There is deliberately no exit 1: this tool decides nothing about a verdict, so it has no
"said no" to report. A caller seeing 3 knows the schema it dispatches with is NOT the
adapted one, which is a different fact from "the model's answer was rejected".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

USAGE = (
    "USAGE: adapt_output_schema.py adapt <shipped-schema.json> <api-schema.json>\n"
    "       adapt_output_schema.py strip-nulls <document.json> [--raw-copy <path>]\n"
    "       adapt_output_schema.py selftest"
)

#: Keywords the structured-output endpoint refuses. ``anyOf`` is deliberately absent:
#: the endpoint accepts it, and removing it would *widen* what the model may emit --
#: turning a schema tightening into a schema loosening, silently.
REJECTED_KEYWORDS = ("allOf", "oneOf", "not", "if", "then", "else")

#: Containers whose keys are user-chosen NAMES rather than schema keywords. A schema
#: describing an object with a field literally called ``if`` or ``not`` must survive
#: intact; conflating the two positions would drop a real field from the contract, which
#: is worse than the 400 this tool prevents, because nothing would report it.
NAME_POSITION_KEYS = frozenset({"properties", "patternProperties", "definitions", "$defs"})


def strip_keywords(node: object, keys_are_names: bool = False) -> int:
    """Remove REJECTED_KEYWORDS wherever they appear as keywords. Returns the count.

    Recurses to every depth. A root-only strip is indistinguishable from a correct one
    until the schema nests a conditional, which is exactly how the POSIX wrapper shipped
    broken for as long as the verdict schema kept its ``allOf`` at the top.
    """
    if isinstance(node, list):
        return sum(strip_keywords(item) for item in node)
    if not isinstance(node, dict):
        return 0

    removed = 0
    if not keys_are_names:
        for keyword in REJECTED_KEYWORDS:
            if keyword in node:
                del node[keyword]
                removed += 1

    for name in list(node):
        child_names = (not keys_are_names) and name in NAME_POSITION_KEYS
        removed += strip_keywords(node[name], child_names)
    return removed


def widen_required(node: object, keys_are_names: bool = False) -> int:
    """Make every object node's ``required`` list all of its properties, nullably.

    An originally-optional property gains ``null`` in its permitted types, or is wrapped
    in ``anyOf`` when it has no plain ``type`` to widen (a ``$ref``, an enum-only node, a
    composite). Returns the number of properties that were optional.

    The consequence is that the model emits ``"mechanism": null`` rather than omitting the
    key -- which the shipped schema, still strict, would reject. ``strip-nulls`` undoes it
    on the way back. Keep the two together: widening here without stripping there turns a
    400 before the run into a validation refusal after it, which costs a whole review
    round instead of a second.
    """
    if isinstance(node, list):
        return sum(widen_required(item) for item in node)
    if not isinstance(node, dict):
        return 0

    widened = 0
    if not keys_are_names:
        props = node.get("properties")
        if isinstance(props, dict):
            all_names = list(props)
            current = node.get("required")
            already = set(current) if isinstance(current, list) else set()
            for name in all_names:
                if name in already:
                    continue
                prop = props[name]
                if not isinstance(prop, dict):
                    continue
                declared = prop.get("type")
                if isinstance(declared, str):
                    prop["type"] = [declared, "null"]
                elif isinstance(declared, list):
                    if "null" not in declared:
                        prop["type"] = list(declared) + ["null"]
                else:
                    props[name] = {"anyOf": [dict(prop), {"type": "null"}]}
                widened += 1
            node["required"] = all_names

    for name in list(node):
        child_names = (not keys_are_names) and name in NAME_POSITION_KEYS
        widened += widen_required(node[name], child_names)
    return widened


def strip_nulls(node: object) -> int:
    """Delete null-valued keys from a parsed document, at every depth. Returns the count.

    This only ever removes keys whose value is ``null``. ``false``, ``0`` and ``""`` are
    values and stay, so it cannot launder a real answer out of a verdict, and it cannot
    turn a populated field into a missing one.
    """
    if isinstance(node, list):
        return sum(strip_nulls(item) for item in node)
    if not isinstance(node, dict):
        return 0

    removed = 0
    for name in list(node):
        if node[name] is None:
            del node[name]
            removed += 1
        else:
            removed += strip_nulls(node[name])
    return removed


def cmd_adapt(src: Path, dst: Path) -> int:
    try:
        schema = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"FAIL-CLOSED: could not read the shipped schema at {src}: {exc}. No adapted "
            "schema was written, so the caller must dispatch with the unmodified file and "
            "expect the endpoint to reject it -- that is a different fact from a rejected "
            "verdict."
        )
        return 3

    removed = strip_keywords(schema)
    widened = widen_required(schema)

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"FAIL-CLOSED: could not write the adapted schema to {dst}: {exc}.")
        return 3

    print(
        f"OK: wrote {dst} ({removed} rejected keyword(s) removed at all depths, "
        f"{widened} optional key(s) made required-and-nullable)"
    )
    return 0


def cmd_strip_nulls(path: Path, raw_copy: Path | None) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"FAIL-CLOSED: could not read {path}: {exc}.")
        return 3
    if not text.strip():
        print(f"OK: {path.name} is empty; nothing to strip")
        return 0
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        print(
            f"FAIL-CLOSED: {path.name} is not valid JSON ({exc}), so the nullable widening "
            "was NOT undone. The file is left exactly as the model wrote it; schema "
            "post-validation is what decides whether it is usable."
        )
        return 3

    removed = strip_nulls(doc)
    if not removed:
        print(f"OK: no null-valued keys in {path.name}; left byte-identical")
        return 0

    try:
        if raw_copy is not None:
            raw_copy.parent.mkdir(parents=True, exist_ok=True)
            raw_copy.write_text(text, encoding="utf-8")
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"FAIL-CLOSED: could not rewrite {path}: {exc}.")
        return 3

    kept = f"; pre-strip copy kept at {raw_copy}" if raw_copy is not None else ""
    print(f"OK: removed {removed} null-valued key(s) from {path.name}{kept}")
    return 0


def _count_keywords(obj: object, keys_are_names: bool = False) -> int:
    """Count REJECTED_KEYWORDS in keyword position -- the detector the arms assert with.

    Deliberately a second, independent traversal: asserting with the same function under
    test would make "0 remaining" a tautology (V5).
    """
    if isinstance(obj, list):
        return sum(_count_keywords(i) for i in obj)
    if not isinstance(obj, dict):
        return 0
    n = 0 if keys_are_names else sum(1 for k in REJECTED_KEYWORDS if k in obj)
    for name, value in obj.items():
        n += _count_keywords(value, (not keys_are_names) and name in NAME_POSITION_KEYS)
    return n


def selftest() -> int:
    """Prove both adaptations, in both directions, through the real CLI (V2).

    Both halves need a false-positive arm as well as a true-positive one: a stripper that
    deletes everything and a widener that marks every key nullable would both make the 400
    go away and both destroy the contract, so the suite asserts what must SURVIVE as
    carefully as what must go.
    """
    import subprocess
    import tempfile

    arms: list[tuple[str, bool]] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        arms.append((label, ok))
        print(f"{'PASS' if ok else 'FAIL'} {label}{('  -- ' + detail) if detail else ''}")

    me = str(Path(__file__).resolve())

    def run(*argv: str) -> tuple[int, str]:
        proc = subprocess.run(
            [sys.executable, me, *argv], capture_output=True, text=True
        )
        return proc.returncode, (proc.stdout + proc.stderr)

    with tempfile.TemporaryDirectory(prefix="adapt-output-schema-selftest-") as tmp:
        d = Path(tmp)

        # A fixture shaped like the real thing: a conditional at the root AND one nested
        # under `properties.<x>.items`, a property literally NAMED `if`, an `anyOf` that
        # must survive, an already-required key that must not be widened, an optional key
        # with a plain type, and an optional key with no type at all.
        fixture = {
            "type": "object",
            "properties": {
                "if": {"type": "string"},
                "kept": {"type": "string"},
                "flavour": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "mechanism": {"type": "string"},
                            "ref": {"$ref": "#/$defs/thing"},
                        },
                        "required": ["id"],
                        "allOf": [{"required": ["mechanism"]}],
                    },
                },
            },
            "required": ["kept", "findings"],
            "allOf": [{"if": {"const": 1}, "then": {"required": ["if"]}}],
            "$defs": {"not": {"type": "integer"}},
        }
        src = d / "shipped.json"
        src.write_text(json.dumps(fixture), encoding="utf-8")
        out = d / "api.json"

        code, text = run("adapt", str(src), str(out))
        check("adapt-fixture -> 0 OK:", code == 0 and text.startswith("OK:"), f"exit={code}")
        got = json.loads(out.read_text(encoding="utf-8"))

        check(
            "no-rejected-keyword-at-any-depth",
            _count_keywords(got) == 0,
            f"remaining={_count_keywords(got)}",
        )
        # The specific one a root-only strip leaves behind. Without this, an arm counting
        # only totals still passes a wrapper that pops the root and stops.
        check(
            "nested-conditional-removed-not-just-root",
            "allOf" not in got["properties"]["findings"]["items"],
        )
        check(
            "keyword-named-property-survives",
            "if" in got["properties"] and "not" in got["$defs"],
            f"properties={sorted(got['properties'])}",
        )
        check("anyOf-preserved", "anyOf" in got["properties"]["flavour"])

        item = got["properties"]["findings"]["items"]
        check(
            "optional-key-required-and-nullable",
            item["required"] == ["id", "mechanism", "ref"]
            and item["properties"]["mechanism"]["type"] == ["string", "null"],
            f"required={item['required']}",
        )
        check(
            "typeless-optional-wrapped-in-anyOf",
            item["properties"]["ref"].get("anyOf")
            == [{"$ref": "#/$defs/thing"}, {"type": "null"}],
        )
        # The false-positive direction: a key that was ALREADY required must keep its
        # exact type. A widener that nullified everything would pass every arm above.
        check(
            "already-required-key-not-nullified",
            item["properties"]["id"]["type"] == "string"
            and got["properties"]["kept"]["type"] == "string",
        )
        check(
            "root-required-covers-every-property",
            got["required"] == list(got["properties"]),
            f"required={got['required']}",
        )

        # The real shipped schema -- the artifact that actually gets dispatched. This is
        # the arm the POSIX wrapper never had: its fixture-free equivalent is a live 400.
        shipped = Path(__file__).resolve().parent.parent / ".agent/schemas/review-verdict.schema.v2.json"
        if not shipped.is_file():
            check(f"shipped-verdict-schema-adapts[{shipped}]", False, "schema not found")
        else:
            real_out = d / "api-real.json"
            code, text = run("adapt", str(shipped), str(real_out))
            real = json.loads(real_out.read_text(encoding="utf-8"))
            finding = real["properties"]["findings"]["items"]
            check(
                "shipped-verdict-schema-adapts",
                code == 0
                and _count_keywords(real) == 0
                and "mechanism" in finding["required"]
                and "null" in finding["properties"]["mechanism"]["type"]
                and real["required"] == list(real["properties"]),
                f"exit={code} keywords_left={_count_keywords(real)}",
            )
            # ...and the shipped schema really does contain the shapes being adapted, or
            # the arm above proves nothing (V5).
            original = json.loads(shipped.read_text(encoding="utf-8"))
            check(
                "shipped-schema-actually-has-nested-conditionals",
                _count_keywords(original) >= 2
                and "allOf" in original["properties"]["findings"]["items"],
                f"keywords_found={_count_keywords(original)}",
            )

        # --- strip-nulls ---------------------------------------------------------------
        doc = {
            "verdict": "approved",
            "blocking": False,
            "round": 0,
            "summary": "",
            "mechanism": None,
            "findings": [
                {"id": "F01", "mechanism": None, "file_line": "a.py:1"},
                {"id": "F02", "mechanism": "swallowed-exit-code"},
            ],
        }
        target = d / "final.json"
        target.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        raw = d / "final.raw.json"
        before = target.read_text(encoding="utf-8")

        code, text = run("strip-nulls", str(target), "--raw-copy", str(raw))
        after = json.loads(target.read_text(encoding="utf-8"))
        check(
            "strip-nulls -> 0 OK: (2 keys)",
            code == 0 and "2 null-valued key(s)" in text,
            f"exit={code} {text.strip()}",
        )
        check(
            "null-keys-removed",
            "mechanism" not in after and "mechanism" not in after["findings"][0],
        )
        # The false-positive direction: falsey-but-present values are answers. Read with
        # `.get` on purpose -- a stripper that deletes them must FAIL this arm, not crash
        # the suite on a KeyError, because a crash is indistinguishable from a broken test.
        kept_findings = after.get("findings") or [{}, {}]
        check(
            "falsey-values-survive",
            after.get("blocking", "gone") is False
            and after.get("round", "gone") == 0
            and after.get("summary", "gone") == ""
            and kept_findings[-1].get("mechanism") == "swallowed-exit-code",
            f"kept={sorted(after)}",
        )
        check("raw-copy-preserves-pre-strip-text", raw.read_text(encoding="utf-8") == before)

        # Nothing to strip: no rewrite, and no raw copy left behind to imply one happened.
        clean = d / "clean.json"
        clean_text = '{"a": 1, "b": [false, 0]}'
        clean.write_text(clean_text, encoding="utf-8")
        clean_raw = d / "clean.raw.json"
        code, text = run("strip-nulls", str(clean), "--raw-copy", str(clean_raw))
        check(
            "no-nulls-leaves-file-byte-identical",
            code == 0
            and clean.read_text(encoding="utf-8") == clean_text
            and not clean_raw.exists(),
            f"exit={code}",
        )

        # --- the could-not-run paths, which must be 3 and never 0 -----------------------
        code, text = run("adapt", str(d / "absent.json"), str(d / "x.json"))
        check(
            "absent-schema -> 3 FAIL-CLOSED:",
            code == 3 and text.startswith("FAIL-CLOSED:"),
            f"exit={code}",
        )
        bad = d / "malformed.json"
        bad.write_text("{not json", encoding="utf-8")
        code, text = run("adapt", str(bad), str(d / "y.json"))
        check(
            "malformed-schema -> 3 FAIL-CLOSED:",
            code == 3 and text.startswith("FAIL-CLOSED:"),
            f"exit={code}",
        )
        code, text = run("strip-nulls", str(bad))
        check(
            "malformed-document -> 3 FAIL-CLOSED: (file untouched)",
            code == 3
            and text.startswith("FAIL-CLOSED:")
            and bad.read_text(encoding="utf-8") == "{not json",
            f"exit={code}",
        )
        # An unwritable destination: point the output *through* a regular file, so the
        # parent mkdir fails on every platform rather than depending on permissions.
        blocker = d / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        code, text = run("adapt", str(src), str(blocker / "sub" / "api.json"))
        check(
            "unwritable-destination -> 3 FAIL-CLOSED:",
            code == 3 and text.startswith("FAIL-CLOSED:"),
            f"exit={code}",
        )

        for argv, why in (
            ((), "no verb"),
            (("adapt", str(src)), "adapt with one path"),
            (("strip-nulls",), "strip-nulls with no path"),
            (("frobnicate", str(src)), "unknown verb"),
        ):
            code, text = run(*argv)
            check(
                f"usage[{why}] -> 2 USAGE:",
                code == 2 and text.startswith("USAGE:"),
                f"exit={code}",
            )

    failures = sum(1 for _, ok in arms if not ok)
    must_ok = sum(1 for label, _ in arms if "-> 0 OK:" in label)
    must_survive = sum(
        1
        for label, _ in arms
        if any(w in label for w in ("survives", "preserved", "not-nullified", "identical"))
    )
    print(
        f"\nRESULT: {len(arms)} arm(s), {failures} failure(s) "
        f"[{must_ok} must-OK + {must_survive} must-survive, so neither a stripper that "
        "deletes everything nor one that deletes nothing can pass this suite]"
    )
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if not argv:
        print(USAGE)
        return 2
    verb, rest = argv[0], argv[1:]

    if verb == "selftest" and not rest:
        return selftest()
    if verb == "adapt" and len(rest) == 2:
        return cmd_adapt(Path(rest[0]), Path(rest[1]))
    if verb == "strip-nulls":
        if len(rest) == 1:
            return cmd_strip_nulls(Path(rest[0]), None)
        if len(rest) == 3 and rest[1] == "--raw-copy":
            return cmd_strip_nulls(Path(rest[0]), Path(rest[2]))
    print(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
