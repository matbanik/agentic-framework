#!/usr/bin/env python3
"""
Build Plan Validator
====================

Structural checks for the build plan written by ``/build-plan-authoring``: the hub
(``docs/BUILD_PLAN.md``) and the phase specs beside it (``docs/build-plan/``).

Nothing here knows what the phases are called or how many there are. Phase specs are
discovered by file name (``NN-name.md``, sub-phases ``NNx-name.md``), so the same checks
hold for any architecture.

Errors (exit 1) -- true of any plan:
  hub_exists        hub file and plan directory are present
  autogen_markers   an AUTOGEN region that is opened is also closed, once
  links             relative markdown links in the hub and plan files resolve
  phase_heading     an H1 of the form "Phase N" agrees with the file number
  build_order       the priority matrix has no duplicate order numbers
  meu_status_drift  rendered AUTOGEN regions match the SSOT (when the renderer is present)

Warnings (exit 0 unless --strict) -- conventions a plan may have reason to break:
  autogen_markers   hub carries no AUTOGEN regions at all
  reachability      a phase spec cannot be reached by links from the hub
  phase_ids         two phase specs share a number+suffix
  sections          a phase spec lacks a required-core heading (Goal, Exit Criteria)
  prerequisites     a phase spec has no "Prerequisites:" line, or lists a later phase
  build_order       gaps in the matrix order numbers
  unfilled          "[FILL: ...]" prompts left over from a template
  hub_size          hub longer than --hub-max-lines (off unless the flag is given)

Usage:
  python tools/validate_build_plan.py                 # run all checks
  python tools/validate_build_plan.py -v              # per-check progress
  python tools/validate_build_plan.py --json          # machine-readable
  python tools/validate_build_plan.py --strict        # warnings fail too
  python tools/validate_build_plan.py --hub docs/SPEC.md --plan-dir docs/spec
  python tools/validate_build_plan.py --selftest      # prove the checks accept and refuse

Exit: 0 passed / 1 failed / 2 usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

_REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_HUB = "docs/BUILD_PLAN.md"
DEFAULT_PLAN_DIR = "docs/build-plan"
MATRIX_NAME = "build-priority-matrix.md"
OVERVIEW_NUMBER = 0  # 00-*.md is the cross-phase overview, not a phase

# Required-core headings of a phase spec (matched case-insensitively, any heading level).
REQUIRED_PHASE_SECTIONS = ["Goal", "Exit Criteria"]

PHASE_FILE_RE = re.compile(r"^(\d{2})([a-z]?)-(.+)\.md$")
LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
AUTOGEN_RE = re.compile(r"<!--\s*(BEGIN|END)\s+AUTOGEN:([\w:-]+)\s*-->")
H1_PHASE_RE = re.compile(r"^# Phase (\d+)", re.MULTILINE)
PREREQ_RE = re.compile(r"Prerequisites?\*{0,2}:\s*(.+?)(?:\||\n|$)", re.IGNORECASE)
ORDER_RE = re.compile(r"^\|\s*\*\*(\d+[a-z]?)\*\*\s*\|", re.MULTILINE)
FILL_RE = re.compile(r"\[FILL:")
NEEDS_DECISION_RE = re.compile(r"\[NEEDS DECISION")


# ─── Data Structures ─────────────────────────────────────────────────────


@dataclass
class Issue:
    severity: str  # ERROR, WARNING
    check: str
    file: str
    message: str
    line: Optional[int] = None


@dataclass
class Config:
    root: Path
    hub: Path
    plan_dir: Path
    required_sections: list[str]
    hub_max_lines: Optional[int] = None
    check_drift: bool = True


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "WARNING"]

    def passed(self, strict: bool = False) -> bool:
        return not self.errors and not (strict and self.warnings)

    def add(self, severity: str, check: str, file: str, message: str,
            line: Optional[int] = None) -> None:
        self.issues.append(Issue(severity, check, file, message, line))


# ─── Helpers ──────────────────────────────────────────────────────────────


def _blank_code(content: str) -> str:
    """Blank fenced blocks, inline code spans and HTML comments (line count preserved).

    Checks should read real navigation and real prose, not example snippets, ASCII
    diagrams or template instructions.
    """
    out: list[str] = []
    in_fence = False
    for line in content.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else re.sub(r"`[^`\n]*`", "", line))
    text = "\n".join(out)
    return re.sub(
        r"<!--(?!\s*(?:BEGIN|END)\s+AUTOGEN).*?-->",
        lambda m: "\n" * m.group(0).count("\n"),
        text,
        flags=re.DOTALL,
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _line_of(content: str, pos: int) -> int:
    return content[:pos].count("\n") + 1


def _plan_files(cfg: Config) -> list[Path]:
    return sorted(cfg.plan_dir.glob("*.md")) if cfg.plan_dir.is_dir() else []


def _phase_specs(cfg: Config) -> list[tuple[Path, int, str]]:
    """(path, number, suffix) for every phase spec; the 00 overview is excluded."""
    specs = []
    for path in _plan_files(cfg):
        m = PHASE_FILE_RE.match(path.name)
        if m and int(m.group(1)) != OVERVIEW_NUMBER:
            specs.append((path, int(m.group(1)), m.group(2)))
    return specs


def _rel(cfg: Config, path: Path) -> str:
    try:
        return path.resolve().relative_to(cfg.root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _local_links(content: str) -> list[tuple[str, str, int]]:
    """(text, target-without-anchor, position) for links that point at local files."""
    links = []
    for m in LINK_RE.finditer(content):
        target = unquote(m.group(2).split("#")[0])
        if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            continue  # same-page anchor, or a URI scheme (https:, file:, mailto:)
        if "{" in target or "<" in target:
            continue  # unfilled placeholder, not a link yet
        links.append((m.group(1), target, m.start()))
    return links


# ─── Validators ───────────────────────────────────────────────────────────


def check_hub_exists(cfg: Config, result: ValidationResult) -> None:
    if not cfg.hub.is_file():
        result.add("ERROR", "hub_exists", _rel(cfg, cfg.hub), "Hub file missing")
    if not cfg.plan_dir.is_dir():
        result.add("ERROR", "hub_exists", _rel(cfg, cfg.plan_dir),
                   "Plan directory missing")
    result.stats["plan_files"] = len(_plan_files(cfg))
    result.stats["phase_specs"] = len(_phase_specs(cfg))


def check_autogen_markers(cfg: Config, result: ValidationResult) -> None:
    if not cfg.hub.is_file():
        return
    content = _read(cfg.hub)
    hub = _rel(cfg, cfg.hub)
    counts: dict[str, dict[str, int]] = {}
    for m in AUTOGEN_RE.finditer(content):
        counts.setdefault(m.group(2), {"BEGIN": 0, "END": 0})[m.group(1)] += 1
    result.stats["autogen_regions"] = len(counts)
    if not counts:
        result.add("WARNING", "autogen_markers", hub,
                   "No AUTOGEN regions; status cannot be rendered into the hub")
    for name, c in sorted(counts.items()):
        if c["BEGIN"] != 1 or c["END"] != 1:
            result.add("ERROR", "autogen_markers", hub,
                       f"AUTOGEN region '{name}' has {c['BEGIN']} BEGIN and "
                       f"{c['END']} END markers (expected one of each)")


def check_links(cfg: Config, result: ValidationResult) -> None:
    files = ([cfg.hub] if cfg.hub.is_file() else []) + _plan_files(cfg)
    checked = 0
    for path in files:
        content = _blank_code(_read(path))
        for text, target, pos in _local_links(content):
            checked += 1
            if not (path.parent / target).exists():
                result.add("ERROR", "links", _rel(cfg, path),
                           f"Broken link to '{target}' (text: '{text}')",
                           _line_of(content, pos))
    result.stats["links_checked"] = checked


def check_reachability(cfg: Config, result: ValidationResult) -> None:
    """Every phase spec should be reachable from the hub by following links."""
    if not cfg.hub.is_file():
        return
    plan_dir = cfg.plan_dir.resolve()
    seen: set[Path] = set()
    queue = [cfg.hub.resolve()]
    while queue:
        path = queue.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for _text, target, _pos in _local_links(_blank_code(_read(path))):
            nxt = (path.parent / target).resolve()
            if nxt.suffix == ".md" and nxt.parent == plan_dir and nxt not in seen:
                queue.append(nxt)
    for path, _num, _suffix in _phase_specs(cfg):
        if path.resolve() not in seen:
            result.add("WARNING", "reachability", _rel(cfg, path),
                       "Phase spec is not reachable from the hub")


def check_phase_ids(cfg: Config, result: ValidationResult) -> None:
    by_id: dict[str, list[str]] = {}
    for path, num, suffix in _phase_specs(cfg):
        by_id.setdefault(f"{num:02d}{suffix}", []).append(path.name)
    for phase_id, names in sorted(by_id.items()):
        if len(names) > 1:
            result.add("WARNING", "phase_ids", _rel(cfg, cfg.plan_dir),
                       f"Phase id {phase_id} is used by {len(names)} files: "
                       + ", ".join(names))


def check_phase_heading(cfg: Config, result: ValidationResult) -> None:
    for path, num, _suffix in _phase_specs(cfg):
        m = H1_PHASE_RE.search(_blank_code(_read(path)))
        if m and int(m.group(1)) != num:
            result.add("ERROR", "phase_heading", _rel(cfg, path),
                       f"File number ({num:02d}) does not match heading "
                       f"'Phase {m.group(1)}'")


def check_sections(cfg: Config, result: ValidationResult) -> None:
    for path, _num, _suffix in _phase_specs(cfg):
        headings = [h.strip().lower() for h in
                    re.findall(r"^#{1,6}\s+(.+)$", _blank_code(_read(path)), re.MULTILINE)]
        for section in cfg.required_sections:
            if not any(section.lower() in h for h in headings):
                result.add("WARNING", "sections", _rel(cfg, path),
                           f"No heading containing '{section}'")


def check_prerequisites(cfg: Config, result: ValidationResult) -> None:
    for path, num, suffix in _phase_specs(cfg):
        content = _blank_code(_read(path))
        m = PREREQ_RE.search(content)
        if not m:
            result.add("WARNING", "prerequisites", _rel(cfg, path),
                       "No 'Prerequisites:' line found")
            continue
        for _text, target, _pos in _local_links(m.group(1)):
            pm = PHASE_FILE_RE.match(Path(target).name)
            if pm and (int(pm.group(1)), pm.group(2)) > (num, suffix):
                result.add("WARNING", "prerequisites", _rel(cfg, path),
                           f"Prerequisite '{Path(target).name}' is a later phase",
                           _line_of(content, m.start()))


def check_build_order(cfg: Config, result: ValidationResult) -> None:
    matrix = cfg.plan_dir / MATRIX_NAME
    if not matrix.is_file():
        return
    orders = ORDER_RE.findall(_blank_code(_read(matrix)))
    result.stats["build_order_items"] = len(orders)
    seen: set[str] = set()
    for order in orders:
        if order in seen:
            result.add("ERROR", "build_order", _rel(cfg, matrix),
                       f"Duplicate build order number: {order}")
        seen.add(order)
    bases = {int(re.match(r"\d+", o).group(0)) for o in orders}  # type: ignore[union-attr]
    for i in range(1, max(bases, default=0) + 1):
        if i not in bases:
            result.add("WARNING", "build_order", _rel(cfg, matrix),
                       f"Missing build order number: {i}")


def check_unfilled(cfg: Config, result: ValidationResult) -> None:
    files = ([cfg.hub] if cfg.hub.is_file() else []) + _plan_files(cfg)
    needs_decision = 0
    for path in files:
        content = _blank_code(_read(path))
        needs_decision += len(NEEDS_DECISION_RE.findall(content))
        fills = len(FILL_RE.findall(content))
        if fills:
            result.add("WARNING", "unfilled", _rel(cfg, path),
                       f"{fills} '[FILL: ...]' template prompt(s) left")
    result.stats["needs_decision_markers"] = needs_decision


def check_hub_size(cfg: Config, result: ValidationResult) -> None:
    if not cfg.hub.is_file():
        return
    lines = _read(cfg.hub).count("\n") + 1
    result.stats["hub_lines"] = lines
    if cfg.hub_max_lines is not None and lines > cfg.hub_max_lines:
        result.add("WARNING", "hub_size", _rel(cfg, cfg.hub),
                   f"Hub has {lines} lines (--hub-max-lines {cfg.hub_max_lines}); "
                   "per-phase detail belongs in phase specs")


def check_meu_status_drift(cfg: Config, result: ValidationResult) -> None:
    """Rendered AUTOGEN regions match the SSOT. Skipped when there is nothing to compare."""
    if not cfg.check_drift or not result.stats.get("autogen_regions"):
        return
    if not (cfg.root / ".agent" / "context" / "meu-status.yaml").is_file():
        return
    if str(cfg.root) not in sys.path:
        sys.path.insert(0, str(cfg.root))
    try:
        from tools.meu_status.render import check_drift
    except ImportError:
        return  # renderer not installed (profile D9 = no)
    if check_drift() != 0:
        result.add("ERROR", "meu_status_drift", ".agent/context/meu-status.yaml",
                   "Rendered status is out of date; run "
                   "'python tools/meu_status.py render'")


CHECKS = [
    ("Hub and plan directory", check_hub_exists),
    ("AUTOGEN markers", check_autogen_markers),
    ("Links", check_links),
    ("Reachability from hub", check_reachability),
    ("Phase ids", check_phase_ids),
    ("Phase headings", check_phase_heading),
    ("Required sections", check_sections),
    ("Prerequisites", check_prerequisites),
    ("Build order", check_build_order),
    ("Unfilled template prompts", check_unfilled),
    ("Hub size", check_hub_size),
    ("MEU status drift", check_meu_status_drift),
]


# ─── Runner ───────────────────────────────────────────────────────────────


def run_validation(cfg: Config, verbose: bool = False) -> ValidationResult:
    result = ValidationResult()
    for name, check_fn in CHECKS:
        before = len(result.issues)
        check_fn(cfg, result)
        if verbose:
            new = len(result.issues) - before
            print(f"  {name}: {'OK' if new == 0 else f'{new} issue(s)'}")
    return result


def format_text_report(result: ValidationResult, strict: bool) -> str:
    lines = ["=" * 60, "  Build Plan Validation Report", "=" * 60, "", "Statistics:"]
    lines += [f"   {k}: {v}" for k, v in result.stats.items()]
    lines.append("")
    for label, issues in (("Error(s)", result.errors), ("Warning(s)", result.warnings)):
        if not issues:
            continue
        lines.append(f"{len(issues)} {label}:")
        for issue in issues:
            loc = f":{issue.line}" if issue.line else ""
            lines.append(f"   [{issue.check}] {issue.file}{loc}")
            lines.append(f"      {issue.message}")
        lines.append("")
    if result.passed(strict):
        lines.append(f"PASSED: 0 errors, {len(result.warnings)} warning(s).")
    else:
        lines.append(f"FAILED: {len(result.errors)} error(s), "
                     f"{len(result.warnings)} warning(s)"
                     + (" (--strict)." if strict else "."))
    return "\n".join(lines)


def format_json_report(result: ValidationResult, strict: bool) -> str:
    return json.dumps(
        {
            "passed": result.passed(strict),
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "stats": result.stats,
            "issues": [vars(i) for i in result.issues],
        },
        indent=2,
    )


# ─── Selftest ─────────────────────────────────────────────────────────────

_GOOD_HUB = """# Build Plan

## Build Phases

| Phase | Name | Spec |
|-------|------|------|
| 1 | Core | [01-core](build-plan/01-core.md) |
| 2 | Edge | [02-edge](build-plan/02-edge.md) |

<!-- BEGIN AUTOGEN:meu-status:phase-tracker -->
<!-- END AUTOGEN:meu-status:phase-tracker -->

[Matrix](build-plan/build-priority-matrix.md)
"""

_GOOD_SPEC = """# Phase {n}: {name}

> Part of [BUILD_PLAN.md](../BUILD_PLAN.md) | Prerequisites: {prereq} | Outputs: things

## Goal

One outcome.

## Exit Criteria

| # | Criterion | Proven by |
|---|-----------|-----------|
| 1 | It works | a command |
"""

_GOOD_MATRIX = """# Build Priority Matrix

| Order | Unit |
|-------|------|
| **1** | a |
| **2** | b |
"""


def _write_plan(root: Path, **overrides: str) -> None:
    files = {
        "docs/BUILD_PLAN.md": _GOOD_HUB,
        "docs/build-plan/01-core.md": _GOOD_SPEC.format(n=1, name="Core", prereq="None"),
        "docs/build-plan/02-edge.md": _GOOD_SPEC.format(
            n=2, name="Edge", prereq="[Phase 1](01-core.md)"),
        "docs/build-plan/build-priority-matrix.md": _GOOD_MATRIX,
    }
    files.update(overrides)
    for rel, text in files.items():
        if text is None:
            continue
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def selftest() -> int:
    """Each arm builds a plan in a temp dir and states what the validator must say.

    Both directions are covered: a validator that refused everything would fail the
    must-OK arms, one that accepted everything would fail the must-refuse arms.
    """
    spec2 = _GOOD_SPEC.format(n=2, name="Edge", prereq="[Phase 1](01-core.md)")
    spec1 = _GOOD_SPEC.format(n=1, name="Core", prereq="None")
    # (name, overrides, strict, expect_pass, check expected among issues or None)
    arms = [
        ("valid plan", {}, False, True, None),
        ("valid plan under --strict", {}, True, True, None),
        ("link inside code fence ignored",
         {"docs/build-plan/01-core.md": spec1 + "\n```\n[x](missing.md)\n```\n"},
         True, True, None),
        ("no AUTOGEN regions is a warning",
         {"docs/BUILD_PLAN.md": re.sub(r"<!--.*?-->\n", "", _GOOD_HUB)},
         False, True, "autogen_markers"),
        ("unfilled prompt is a warning",
         {"docs/build-plan/01-core.md": spec1 + "\n[FILL: more]\n"},
         False, True, "unfilled"),
        ("missing Goal is a warning",
         {"docs/build-plan/01-core.md": spec1.replace("## Goal", "## Intent")},
         False, True, "sections"),
        ("orphan spec is a warning",
         {"docs/build-plan/03-lost.md": _GOOD_SPEC.format(n=3, name="Lost", prereq="None")},
         False, True, "reachability"),
        ("forward prerequisite is a warning",
         {"docs/build-plan/01-core.md":
          _GOOD_SPEC.format(n=1, name="Core", prereq="[Phase 2](02-edge.md)")},
         False, True, "prerequisites"),
        ("warning fails under --strict",
         {"docs/build-plan/01-core.md": spec1 + "\n[FILL: more]\n"},
         True, False, "unfilled"),
        ("broken link in spec",
         {"docs/build-plan/02-edge.md": spec2 + "\n[gone](09-gone.md)\n"},
         False, False, "links"),
        ("broken link in hub",
         {"docs/BUILD_PLAN.md": _GOOD_HUB + "\n[gone](build-plan/09-gone.md)\n"},
         False, False, "links"),
        ("unclosed AUTOGEN region",
         {"docs/BUILD_PLAN.md": _GOOD_HUB.replace(
             "<!-- END AUTOGEN:meu-status:phase-tracker -->\n", "")},
         False, False, "autogen_markers"),
        ("heading number disagrees with file",
         {"docs/build-plan/02-edge.md": spec2.replace("# Phase 2", "# Phase 7")},
         False, False, "phase_heading"),
        ("duplicate phase id is a warning",
         {"docs/build-plan/02-other.md": spec2,
          "docs/BUILD_PLAN.md": _GOOD_HUB + "\n[o](build-plan/02-other.md)\n"},
         False, True, "phase_ids"),
        ("duplicate build order",
         {"docs/build-plan/build-priority-matrix.md": _GOOD_MATRIX + "| **2** | c |\n"},
         False, False, "build_order"),
    ]
    failures = 0
    accepted = refused = 0
    for name, overrides, strict, expect_pass, expect_check in arms:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_plan(root, **overrides)
            cfg = Config(root, root / DEFAULT_HUB, root / DEFAULT_PLAN_DIR,
                         list(REQUIRED_PHASE_SECTIONS), check_drift=False)
            result = run_validation(cfg)
        got_pass = result.passed(strict)
        checks = {i.check for i in result.issues}
        ok = got_pass == expect_pass and (
            (expect_check in checks) if expect_check else not result.issues)
        accepted += got_pass
        refused += not got_pass
        if not ok:
            failures += 1
            print(f"SELFTEST-FAIL: {name}: passed={got_pass} "
                  f"(expected {expect_pass}), checks={sorted(checks)}")
    must_ok = sum(1 for a in arms if a[3])
    print(f"selftest: {len(arms)} arms, {must_ok} must-OK / {len(arms) - must_ok} "
          f"must-refuse; observed {accepted} accepted / {refused} refused; "
          f"{failures} failure(s)")
    return 1 if failures else 0


# ─── CLI ──────────────────────────────────────────────────────────────────


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Validate build plan structure and cross-references.")
    parser.add_argument("--root", default=str(_REPO_ROOT),
                        help="Project root (default: parent of tools/)")
    parser.add_argument("--hub", default=DEFAULT_HUB,
                        help=f"Hub file, relative to root (default: {DEFAULT_HUB})")
    parser.add_argument("--plan-dir", default=DEFAULT_PLAN_DIR,
                        help=f"Phase spec directory (default: {DEFAULT_PLAN_DIR})")
    parser.add_argument("--require-section", action="append", metavar="HEADING",
                        help="Heading every phase spec should have (repeatable; "
                             f"default: {', '.join(REQUIRED_PHASE_SECTIONS)})")
    parser.add_argument("--hub-max-lines", type=int, metavar="N",
                        help="Warn when the hub exceeds N lines (off by default)")
    parser.add_argument("--no-drift", action="store_true",
                        help="Skip the MEU status drift check")
    parser.add_argument("--strict", action="store_true", help="Warnings fail too")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show per-check progress")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--selftest", action="store_true",
                        help="Run the built-in accept/refuse arms and exit")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    root = Path(args.root).resolve()
    cfg = Config(
        root=root,
        hub=root / args.hub,
        plan_dir=root / args.plan_dir,
        required_sections=args.require_section or list(REQUIRED_PHASE_SECTIONS),
        hub_max_lines=args.hub_max_lines,
        check_drift=not args.no_drift,
    )
    if args.verbose and not args.json:
        print(f"Hub:      {cfg.hub}\nPlan dir: {cfg.plan_dir}\n")

    result = run_validation(cfg, verbose=args.verbose and not args.json)
    print(format_json_report(result, args.strict) if args.json
          else "\n" + format_text_report(result, args.strict))
    return 0 if result.passed(args.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
