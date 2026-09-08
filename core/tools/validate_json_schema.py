#!/usr/bin/env python3
"""validate_json_schema.py -- validate a JSON document against a JSON Schema file.

Why this ships
--------------
``Invoke-CodexDispatch.ps1`` calls this script unconditionally whenever ``-OutputSchema``
is supplied, as the post-run check that the model's structured output actually conforms.
It was not in the package, so every schema-constrained dispatch in an adopter's tree
ended in ``JSON Schema validation failed: python: can't open file
'.../tools/validate_json_schema.py'`` -- a *validation failure* message for a run whose
output was very likely fine. Two different facts wearing the same words is the exact
confusion this package's exit codes exist to prevent, so the check is now a real check.

The reference gate could not see the gap: ``refcheck.py --tools-only`` scans **markdown**
for ``tools/<name>`` commands, and this one is invoked from inside a ``.ps1``.

Usage
-----
    python tools/validate_json_schema.py <document.json> <schema.json>

Exit codes
----------
    0  the document validates
    1  the document does NOT validate (errors printed, most-shallow first)
    2  usage error (wrong argument count, unreadable/malformed file)
    3  the check could not run -- ``jsonschema`` is not installed

``3`` is deliberately separate from ``1``. "Checked and said no" and "never checked" are
different facts, and merging them is how a project comes to believe an unrun check passed.
The first stdout line is always ``OK:``/``REFUSE:``/``FAIL-CLOSED:``/``USAGE:`` so a
caller can ``grep -qx`` for it instead of parsing prose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

USAGE = "USAGE: validate_json_schema.py <document.json> <schema.json>"


def _load(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"USAGE: {label} not found: {path}")
        raise SystemExit(2)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"USAGE: {label} at {path} is unreadable or not valid JSON: {exc}")
        raise SystemExit(2)


def validate(document_path: Path, schema_path: Path) -> int:
    document = _load(document_path, "document")
    schema = _load(schema_path, "schema")

    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print(
            "FAIL-CLOSED: jsonschema is not installed, so the document was NOT checked. "
            "This is not a validation failure -- it is the absence of validation. "
            "Install with: pip install jsonschema"
        )
        return 3

    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda e: (len(list(e.path)), list(map(str, e.path))),
    )
    if not errors:
        print(f"OK: {document_path.name} validates against {schema_path.name}")
        return 0

    print(f"REFUSE: {len(errors)} schema violation(s) in {document_path.name}:")
    for err in errors:
        where = "/".join(str(p) for p in err.path) or "<root>"
        print(f"  {where}: {err.message}")
    return 1


def selftest() -> int:
    """Prove each exit code is reachable and that the detector can actually match.

    A validator that always says OK and a validator that always refuses both produce a
    clean-looking run against a valid document, so the suite asserts both directions plus
    the usage and could-not-check paths (V5).
    """
    import subprocess
    import tempfile

    arms: list[tuple[str, bool]] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        arms.append((label, ok))
        print(f"{'PASS' if ok else 'FAIL'} {label}{('  -- ' + detail) if detail else ''}")

    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "n": {"type": "integer"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    with tempfile.TemporaryDirectory(prefix="validate-json-schema-selftest-") as tmp:
        d = Path(tmp)
        (d / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
        (d / "good.json").write_text(json.dumps({"a": "x", "n": 1}), encoding="utf-8")
        (d / "bad-type.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
        (d / "bad-missing.json").write_text(json.dumps({"n": 1}), encoding="utf-8")
        (d / "bad-extra.json").write_text(
            json.dumps({"a": "x", "zzz": 1}), encoding="utf-8"
        )
        (d / "malformed.json").write_text("{not json", encoding="utf-8")

        def run(*argv: str, env_extra: dict[str, str] | None = None):
            import os

            env = dict(os.environ)
            if env_extra:
                env.update(env_extra)
            # V2: exercise the real entry point in a subprocess, not validate() directly.
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), *argv],
                capture_output=True,
                text=True,
                env=env,
            )
            return proc.returncode, (proc.stdout + proc.stderr)

        s = str(d / "schema.json")

        code, out = run(str(d / "good.json"), s)
        check("valid document -> 0 OK:", code == 0 and out.startswith("OK:"), f"exit={code}")

        for name, needle in (
            ("bad-type.json", "is not of type"),
            ("bad-missing.json", "required"),
            ("bad-extra.json", "Additional properties"),
        ):
            code, out = run(str(d / name), s)
            # V3: assert WHICH clause rejected, not merely that something did. An exit-1
            # arm alone passes when the wrong rule fires.
            check(
                f"{name} -> 1 REFUSE: ({needle})",
                code == 1 and out.startswith("REFUSE:") and needle in out,
                f"exit={code}",
            )

        code, out = run(str(d / "missing-file.json"), s)
        check("absent document -> 2 USAGE:", code == 2 and out.startswith("USAGE:"), f"exit={code}")

        code, out = run(str(d / "malformed.json"), s)
        check("malformed document -> 2 USAGE:", code == 2 and out.startswith("USAGE:"), f"exit={code}")

        code, out = run(str(d / "good.json"), str(d / "no-such-schema.json"))
        check("absent schema -> 2 USAGE:", code == 2 and out.startswith("USAGE:"), f"exit={code}")

        code, out = run(str(d / "good.json"))
        check("too few arguments -> 2 USAGE:", code == 2 and "USAGE:" in out, f"exit={code}")

        # The could-not-check path. A stub package directory shadowing `jsonschema` with a
        # module that raises ImportError is how an adopter without the dependency looks.
        stub = d / "stub"
        stub.mkdir()
        (stub / "jsonschema.py").write_text(
            "raise ImportError('selftest stub: jsonschema unavailable')\n", encoding="utf-8"
        )
        code, out = run(
            str(d / "good.json"), s, env_extra={"PYTHONPATH": str(stub)}
        )
        check(
            "jsonschema absent -> 3 FAIL-CLOSED: (not 1)",
            code == 3 and out.startswith("FAIL-CLOSED:"),
            f"exit={code}",
        )

    failures = sum(1 for _, ok in arms if not ok)
    must_ok = sum(1 for label, _ in arms if "-> 0 OK:" in label)
    print(
        f"\nRESULT: {len(arms)} arm(s), {failures} failure(s) "
        f"[{must_ok} must-OK arm, so a validator that refused everything would fail]"
    )
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if len(argv) == 1 and argv[0] == "--selftest":
        return selftest()
    if len(argv) != 2:
        print(USAGE)
        return 2
    return validate(Path(argv[0]), Path(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
