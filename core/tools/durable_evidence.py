"""Portable durable-evidence contract shared by task and closeout validation.

JSON fences with schema_version=evidence.v1 carry actual observations. This checks
record structure and consistency, not whether the command was honestly executed.
The independent reviewer verifies the evidence and the configured state identity.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

VERSION = "evidence.v1"
PLACEHOLDER = re.compile(r"^\s*(?:TODO|TBD|XXX|<[^>]+>)\s*$|\{\{[^}]+\}\}")
LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")


def configured_roots() -> tuple[str, ...]:
    """The environment overrides the installed F3 root; neither names every /tmp."""
    return (os.environ.get("RECEIPTS_DIR", "{{RECEIPTS_DIR}}"),)


def scratch_reference(value: str, roots: tuple[str, ...]) -> bool:
    """Match root boundaries, respecting Windows separators and case rules."""
    for root in roots:
        if not root or "{{" in root:
            continue
        windows = bool(re.match(r"^[A-Za-z]:|^\\\\", root))
        normalized = value.replace("\\", "/") if windows else value
        prefix = root.replace("\\", "/").rstrip("/") if windows else root.rstrip("/")
        pattern = re.escape(prefix) + r"(?=$|[/\s`\"'<>)\],;:])"
        if re.search(pattern, normalized, re.IGNORECASE if windows else 0):
            return True
    return False


def fences(text: str):
    """Yield (info, body) for closed CommonMark-style backtick/tilde fences."""
    opening = None
    body: list[str] = []
    info = ""
    for line in text.splitlines():
        if opening is None:
            match = re.match(r"^ {0,3}(`{3,}|~{3,})([^`]*)$", line)
            if match:
                opening, info = match.group(1), match.group(2).strip().lower()
                body = []
        elif re.fullmatch(r" {0,3}" + re.escape(opening[0]) + "{" + str(len(opening)) + r",}\s*", line):
            yield info, "\n".join(body)
            opening = None
        else:
            body.append(line)


def records(text: str) -> tuple[list[dict], list[str]]:
    found = []
    errors = []
    for info, body in fences(text):
        if info != "json":
            continue
        try:
            data = json.loads(body)
        except ValueError:
            if VERSION in body:
                errors.append("malformed evidence JSON")
            continue
        if isinstance(data, dict) and data.get("schema_version") == VERSION:
            found.append(data)
    return found, errors


def _meaningful(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not PLACEHOLDER.search(value)


def _strings(value):
    """Inspect decoded strings, including nested extension fields."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def evidence_problems(text: str, *, scratch_roots: tuple[str, ...] | None = None,
                      require_full: bool = False, expected_state: str | None = None) -> list[str]:
    """Validate records; a final gate must be fresh, passing, full and state-bound."""
    roots = configured_roots() if scratch_roots is None else scratch_roots
    entries, errors = records(text)
    if not entries:
        return errors + ["no evidence.v1 record: paste command/procedure, status and decisive output"]
    ids = set()
    full = False
    for index, data in enumerate(entries, 1):
        issues = []
        for key in ("check_id", "cwd", "scope", "phase", "result", "tested_state", "output"):
            if not _meaningful(data.get(key)):
                issues.append(f"missing or placeholder {key}")
        ident = data.get("check_id")
        if isinstance(ident, str):
            if ident in ids:
                issues.append("duplicate check_id")
            ids.add(ident)
        manual = data.get("command") is None and _meaningful(data.get("procedure"))
        code = data.get("exit_code")
        if data.get("result") == "not_run":
            if "exit_code" not in data or code is not None or not _meaningful(data.get("reason")):
                issues.append("not_run needs null exit_code and a reason")
        elif manual:
            if not _meaningful(data.get("observer")) or "exit_code" not in data or code is not None:
                issues.append("manual evidence needs observer and null exit_code")
        elif not _meaningful(data.get("command")) or type(code) is not int:
            issues.append("command evidence needs command and integer exit_code")
        elif (data.get("result") == "pass" and code != 0) or (data.get("result") in ("fail", "blocked") and code == 0):
            issues.append("exit_code contradicts result")
        if data.get("result") not in ("pass", "fail", "blocked", "not_run"):
            issues.append("unknown result")
        if data.get("phase") not in ("red", "green", "static", "targeted", "full", "runtime", "manual"):
            issues.append("unknown phase")
        for key, value in data.items():
            if key == "command":
                continue
            if any(scratch_reference(item, roots) for item in _strings(value)):
                issues.append(f"scratch reference in {key}; preserve the observation here")
        is_full = data.get("phase") == "full" and data.get("result") == "pass"
        if is_full and require_full:
            if data.get("fresh") is not True or data.get("snapshot", False) is not False:
                issues.append("final full gate must be fresh and not a snapshot")
            if not expected_state or data.get("tested_state") != expected_state:
                issues.append("final full gate does not match expected_state")
        if is_full and not issues:
            full = True
        errors.extend(f"evidence {index}: {issue}" for issue in issues)
    if require_full and not full:
        errors.append("no fresh passing full gate for the expected review state")
    return errors


def _durable_link(target: str, artifact: Path) -> bool:
    if scratch_reference(target, configured_roots()):
        return False
    url = urlsplit(target)
    if url.scheme in ("http", "https"):
        return bool(url.netloc and url.path.strip("/"))
    if url.scheme or not url.path or target.startswith(("/", "\\")):
        return False
    decoded = Path(unquote(url.path))
    # Paths may be relative to the artifact or the project root.
    candidates = (artifact.parent / decoded, Path.cwd() / decoded)
    return any(p.is_file() and not scratch_reference(str(p.resolve()), configured_roots()) for p in candidates)


def blocked_evidence_problems(row: str, row_id: str, text: str, artifact: Path) -> list[str]:
    """Require a real follow-up target plus a row-bound blocker or decision record."""
    errors = []
    followup = re.search(r"follow[- ]?up\s*:?\s*(\[[^\]]+\]\([^)]+\))", row, re.IGNORECASE)
    if not followup or not any(_durable_link(t, artifact) for t in LINK.findall(followup.group(1))):
        errors.append("[B] with no linked follow-up (existing file or issue URL required)")
    ident = "B-" + row_id
    if not re.search(r"(?<![\w-])" + re.escape(ident) + r"(?![\w-])", row):
        errors.append(f"row must cite {ident}")
    # Ignore headings inside code fences, including quoted bogus B-blocks.
    selected = []
    active = False
    fence = None
    for line in text.splitlines():
        if fence:
            if active:
                selected.append(line)
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                fence = None
            continue
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if opening:
            fence = opening.group(1)
        elif re.match(r"^ {0,3}#{1,3}\s", line):
            if active:
                break
            active = line.strip() == f"### {ident}"
            continue
        if active:
            selected.append(line)
    block = "\n".join(selected)
    if not block.strip():
        return errors + [f"missing ### {ident} evidence block"]
    reason = re.search(r"^Reason:\s*(external-error|missing-dependency|human-decision)\s*$", block, re.MULTILINE)
    if not reason:
        return errors + ["block needs Reason: external-error, missing-dependency or human-decision"]
    if reason.group(1) == "human-decision":
        decision = re.search(r"^Decision:\s*(.+)$", block, re.MULTILINE)
        if not decision or not any(_durable_link(t, artifact) for t in LINK.findall(decision.group(1))):
            errors.append("human decision needs Decision: and a durable decision link")
    else:
        errors.extend(evidence_problems(block))
        entries, _ = records(block)
        if not any(_meaningful(d.get("command")) and type(d.get("exit_code")) is int
                   and d["exit_code"] != 0 and d.get("result") in ("fail", "blocked") for d in entries):
            errors.append("external blocker needs a failed command and decisive error output")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--require-full", action="store_true")
    parser.add_argument("--expected-state")
    args = parser.parse_args()
    if args.require_full and not args.expected_state:
        parser.error("--require-full needs --expected-state from the project's identity check")
    try:
        errors = evidence_problems(args.artifact.read_text(encoding="utf-8-sig"),
                                   require_full=args.require_full, expected_state=args.expected_state)
    except (OSError, UnicodeError) as exc:
        print(f"FAIL-CLOSED: {exc}")
        return 3
    print("REFUSE: " + "; ".join(errors) if errors else "OK: durable evidence records")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
