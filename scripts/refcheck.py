#!/usr/bin/env python3
"""refcheck.py -- reference-integrity gate for this package.

Every repo-relative path named in a packaged Markdown file must resolve to a
**shipped** file, or be listed in ``core/MANIFEST.md`` under a "Deliberately
EXCLUDED" heading. "Absent" and "deliberately absent" are different states; only
the second is allowed, and it has to be written down.

This gate exists because its absence let a headline defect ship in the source
repo: packaged files referenced ``tools/Invoke-CodexDispatch.ps1`` and
``.agent/schemas/review-verdict.schema.json``, neither of which was in the
package. Nothing compared the *referenced* path set against the *shipped* path
set, so the framework documented a safety gate an adopter could not execute.

Two reference classes
---------------------
**Ordinary** references may be satisfied by MANIFEST-EXCLUDED. A skill doc that
mentions a skill this package does not ship is a documented gap: an adopter who
opens that doc reads the sentence, hits the MANIFEST, and learns the file is not
coming.

**Required** references may not. For files in ``REQUIRED_REFERENCE_FILES`` --
the always-loaded governance set and the templates every plan is cut from --
"EXCLUDED and documented" is still a broken link. Nobody reads AGENTS.md by
opening it and following its links; agents load it on every turn and act on it.
A mandatory instruction that points at a file the adopter does not have is a
control that cannot be executed, and the earlier version of this gate passed two
of exactly that shape because EXCLUDED absolved them.

Only paths written as inline code spans or Markdown link targets are considered.
Free prose is not scanned -- a path the docs merely *discuss* is not a promise,
and regexing prose produces false positives that train reviewers to ignore the
gate.

Usage
-----
    python scripts/refcheck.py                     # --all is the default
    python scripts/refcheck.py --required-only     # just the always-loaded set
    python scripts/refcheck.py --file core/AGENTS.md --file core/GUARDRAILS.md
    python scripts/refcheck.py --token Invoke-CursorAgentDispatch \
                               --allow core/MANIFEST.md
    python scripts/refcheck.py --backlink macos-setup.md
    python scripts/refcheck.py --tools-only        # just the tools/<name> gate
    python scripts/refcheck.py --selftest          # prove the gate can fail

A third class: tool commands
----------------------------
The two classes above only see paths written *as* a code span or link target. A
path buried inside a command -- ``uv run python tools/meu_status.py render`` -- is
neither, so nothing checked it, and five tools were invoked by packaged docs while
absent from the package with a full-scan refcheck reporting 0 unresolved. Telling a
reader to run a tool is a stronger promise than linking to it, and it was the one
form with no gate.

``run_toolcheck`` therefore scans whole lines for ``tools/<name>.<ext>`` and requires
each name to be either shipped or classified in ``TOOL_CLASSES`` with a reason.
Unclassified fails. So does a stale classification -- one nothing references any
more, or one for a tool the package has since started shipping -- because either
pre-authorises a future reference nobody reviewed.

Exit codes
----------
    0  no unresolved references (or, for --token, no hits outside --allow)
    1  at least one unresolved reference / disallowed token hit
    2  bad invocation
    3  --selftest could not demonstrate a failure (the gate is not a gate)
    8  an unclassified or stale ``tools/<name>`` command path

8 is distinct from 1 so a caller can tell which gate spoke: they live in one file
but fail for unrelated reasons and are fixed in different places.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
CORE = PKG_ROOT / "core"
MANIFEST = CORE / "MANIFEST.md"

#: A candidate is only treated as a path reference if it starts with one of these.
#: Everything else in a code span (a command, a flag, an enum value, a YAML key) is
#: ignored, which is what keeps the false-positive rate at zero.
ROOTS = (
    ".agent/",
    ".claude/",
    ".cursor/",
    "tools/",
    "templates/",
    "scripts/",
    "core/",
    "examples/",
    "docs/",
)

#: Files where a MANIFEST-EXCLUDED reference is STILL a failure. These are loaded
#: on every turn (governance) or copied into the adopter's repo as the shape of
#: every plan, handoff, and review (templates). A dangling link here is not a
#: documented gap, it is an instruction the adopter cannot follow.
#:
#: On-demand skill and workflow docs are deliberately NOT in this set: a reader
#: gets there by opening the file, which gives them the chance to notice the
#: MANIFEST note. Nobody "opens" AGENTS.md.
REQUIRED_REFERENCE_FILES = (
    "core/AGENTS.md",
    "core/CLAUDE.md",
    "core/GUARDRAILS.md",
    "core/templates/*.md",
)

#: In a required file, naming an absent path is fine *if the text says so where the
#: reader is looking*. This is the discrimination that matters: the defect is a
#: reference that reads as available, not the mention itself. AGENTS.md may say
#: "``.agent/docs/architecture.md`` is the conventional home and is **not shipped** --
#: create it if you want it" -- that is honest and useful. What it may not do is link
#: the path as if following it would work.
DISCLOSURE = re.compile(
    r"not shipped|not included|not packaged|does not ship|doesn't ship"
    r"|deliberately excluded|§?excluded|create it yourself|create it if"
    r"|if you want it|you will need to (?:write|create)|absent",
    re.IGNORECASE,
)

#: Lines above/below a reference that count as "where the reader is looking". Small
#: on purpose: a disclosure paragraph 200 lines away does not launder a link.
DISCLOSURE_WINDOW = 2

#: Files that write paths relative to the *live registry home* rather than to the
#: adopter's repo root or the package root. ``.agent/INSTANTIATE.md`` says
#: "``tools/ModelRegistry.psm1``" meaning ``<home>/tools/...``; the shipped template
#: of that home is the package-root ``.agent/``, so that is a third resolution root.
REGISTRY_HOME_DOCS = ("UPDATE-CHECKLIST.md",)

#: Exact paths the *adopter* creates and the package must not ship. Narrower than
#: RUNTIME_TREES (which is prefix-based) because each of these is one named file
#: whose absence is the design, not a whole tree of generated output.
ADOPTER_CREATED = frozenset(
    {
        ".agent/model-registry.local.yaml",
        ".agent/model-registry.yaml",
        ".agent/model-registry.json",
    }
)

#: Inline code spans: `...`  (single backtick, non-greedy, no newline)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
#: Markdown links: [text](target)
LINK = re.compile(r"\]\(([^)\s]+)\)")

#: MANIFEST §EXCLUDED bullets look like ``- `name` -- reason``.
#: A single bullet may list several paths (``, `a`, `b`, `c` — reason``); every
#: code span on the line is an exclusion name, not only the first.
EXCLUDED_BULLET = re.compile(r"^\s*[-*]\s+")

#: Directories/segments that never resolve to a file and are not meant to.
GLOB_TAILS = ("/**", "/*", "/…", "/...")

#: ``path.md:123`` / ``path.md:12-34`` / ``path.md:12,34`` citation suffixes.
LINE_CITATION = re.compile(r":\d+(?:[-,]\d+)*$")

#: A ``{{TOKEN}}`` occurrence, which ``resolve()`` matches by shape.
TOKEN_SPAN = re.compile(r"\{\{[A-Z_]+\}\}")

#: Characters that mark a *shape* rather than a literal path: single-brace and
#: angle-bracket placeholders (``{date}-{slug}-handoff.md``, ``<source-slug>.md``),
#: shell globs (``*.md``), brace expansions (``{a,b,c}.md``), and elisions.
SHAPE_MARKERS = ("{", "}", "<", ">", "*", "…", "...")

#: Trees whose *shipped* content is only seed/example state; everything else under
#: them is produced by the adopter's agent at runtime (handoffs, session digests,
#: triage output, reports). Referencing a path an adopter will create is correct --
#: shipping it would be wrong -- so an unresolved ref here is not a defect.
RUNTIME_TREES = (
    ".agent/context/",
    ".agent/reports/",
    # ``docs/`` was missing from ROOTS entirely, which is worse than being unchecked:
    # `docs/missing-policy.md` was not classified as adopter-created, it was not seen
    # at all, so the summary counted zero references on a line that named one. It is
    # in ROOTS now and lands here, because the package ships nothing under a top-level
    # ``docs/`` -- the plans, handoffs, reviews and reflections the lifecycle docs point
    # at are written by the adopter's agent, under names it chooses at runtime. The
    # distinction that matters is between "accounted for" and "invisible": a ``docs/``
    # path is now counted and reported, and if this package ever does ship one, the
    # OK branch above claims it before this line is reached.
    "docs/",
)

#: Code spans that look like a path but are not a promise that the path exists.
#: Keyed by ``file:line -> ref`` so an exemption cannot silently widen: if the line
#: moves, the gate fails again and a human re-reads it.
NOT_A_PROMISE = {
    ("core/.agent/workflows/plan-critical-review.md", 197, "tools/generate.go"): (
        "Cited *as* an example of a mid-path false positive the reviewer should "
        "expect from the sweep regex ('tui/tools/generate.go reported as "
        "tools/generate.go'). Naming it is the instruction, not a claim it exists."
    ),
    ("UPDATE-CHECKLIST.md", 367, "tools/validate_codebase.py"): (
        "A scrub-rationale row quoting what the SOURCE repo's warning named, as the "
        "reason that content was replaced by a portable lesson. It is a citation of "
        "another repo's file, not a path this package offers."
    ),
}

#: A ``tools/<name>.<ext>`` command path, wherever it appears on a line.
#:
#: Scanned over whole lines rather than code spans, unlike every other check here,
#: and that difference is the entire point. ``normalize()`` only considers a
#: candidate that *starts* with a ROOT prefix, so a path buried in a command --
#: ``rtk proxy uv run python tools/validate_closeout_artifacts.py --handoff ...`` --
#: was invisible to the reference gate. That is not a theoretical hole: five tools
#: were invoked by packaged docs while absent from the package, and a full-scan
#: refcheck reported 0 unresolved the whole time. An instruction to run a tool is a
#: stronger promise than a link to it, and it was the one form nothing checked.
#: Both separators are matched because both are *written*: this package documents
#: PowerShell and bash side by side, and a Windows-flavoured command line spells the
#: same instruction ``tools\validate_closeout_artifacts.py``. The classifier keyed on
#: the slash form only, so changing one character in a doc turned a checked promise
#: into an invisible one -- the gate reported 0 unclassified while the doc told the
#: reader to run a tool the package does not contain. Matches are normalised to the
#: slash form by :func:`tool_name` before anything is looked up, so the two spellings
#: cannot be classified differently.
TOOL_PATH = re.compile(
    r"(?<![\w.\\/-])((?:core[\\/])?tools[\\/][A-Za-z0-9_.-]+\.(?:py|ps1|psm1|sh))"
)


def tool_name(raw: str) -> str:
    """One canonical spelling for a ``tools/<name>`` match, whatever separator it used."""
    return raw.replace("\\", "/")

#: Why a ``tools/<name>`` named in the docs is not in the package. A name that is
#: neither shipped nor classified here FAILS the gate (exit 8) -- the default for an
#: unknown tool reference is "this is a defect", not "presumably fine". Getting a new
#: entry in requires writing down which of these four things it is, and that sentence
#: is the deliverable: it is what an adopter reads when the command does not run.
#:
#:   registry-home     ships in the live model-registry home, not the adopter's repo;
#:                     the doc's paths are relative to <registry-home>/
#:   source-repo-only  a tool of the ORIGINATING repo, cited as provenance. An adopter
#:                     is never expected to run it
#:   adopter-supplied  the adopter's own project tooling. The package names the
#:                     command because the gate is real; the implementation is theirs
#:                     because only they know their stack
#:   not-shipped       a genuine gap. MUST also appear under MANIFEST §Deliberately
#:                     EXCLUDED, so the adopter who follows the instruction finds out
#:                     why it will not run
TOOL_CLASS_KINDS = ("registry-home", "source-repo-only", "adopter-supplied", "not-shipped")
TOOL_CLASSES: dict[str, tuple[str, str]] = {
    "tools/ModelRegistry.psm1": (
        "registry-home",
        "The PowerShell resolver module, loaded from <registry-home>/tools/. "
        "INSTANTIATE.md and model-classes.md write registry-home-relative paths.",
    ),
    "tools/resolve_model.py": (
        "registry-home",
        "Thin Python front end to the same registry home; INSTANTIATE.md step 3.",
    ),
    "tools/check_model_slugs.py": (
        "registry-home",
        "Registry-home enforcement pass invoked as "
        "`--project <root> --enforce`; INSTANTIATE.md step 3.",
    ),
    "tools/_fw_refcheck.py": (
        "source-repo-only",
        "This very script under its name in the SOURCE repo. Both call sites say "
        "'(source repo)' / 'from source repo' -- an adopter runs scripts/refcheck.py.",
    ),
    "tools/_fw_hashdiff.py": (
        "source-repo-only",
        "Source-repo drift helper cited by UPDATE-CHECKLIST.md's release steps.",
    ),
    "tools/validate_codebase.py": (
        "adopter-supplied",
        "The adopter's MEU/phase validation gate. The framework fixes WHEN it runs "
        "(--scope meu during implementation, full at phase end); what it validates "
        "depends on their stack, so shipping a stub would make a real gate fake.",
    ),
    "tools/export_openapi.py": (
        "adopter-supplied",
        "OpenAPI drift check for repos with an API package. Only meaningful against "
        "the adopter's own routes; skipped with a recorded basis when absent.",
    ),
    "tools/Invoke-CursorAgentDispatch.ps1": (
        "not-shipped",
        "Cursor Agent CLI wrapper from the originating repo; MANIFEST.md documents "
        "the decision not to port it. Independent review stays on the Codex chain.",
    ),
    "tools/render_review_verdict.py": (
        "not-shipped",
        "Renders a verdict JSON into a markdown review file. A presentation "
        "convenience -- the verdict is already readable as final.json, which is what "
        "review_ledger.py records -- so the workflow names the fallback inline.",
    ),
    "tools/aggregate_reflections.py": (
        "not-shipped",
        "Rolls reflection YAML blocks into a corpus view. Useful once an adopter has "
        "a run of reflections; nothing in the review or closeout path depends on it.",
    ),
    "tools/append_action_log.py": (
        "not-shipped",
        "Appends a dated row to an action log. The workflow states the manual edit "
        "it replaces, so its absence costs a line of typing, not a control.",
    ),
}

#: Setup-time relocations the ADOPTION-GUIDE prescribes: the package ships one path,
#: the adopter's repo ends up with another, and the docs name the destination.
PATH_ALIASES = {
    ".agent/context/handoffs/TEMPLATE.md": "core/templates/HANDOFF-TEMPLATE.md",
    ".agent/context/handoffs/REVIEW-TEMPLATE.md": "core/templates/REVIEW-TEMPLATE.md",
}


def iter_shipped() -> set[str]:
    """Every shipped path, as POSIX strings relative to the package root."""
    shipped: set[str] = set()
    for path in PKG_ROOT.rglob("*"):
        if "__pycache__" in path.parts or ".git" in path.parts:
            continue
        shipped.add(path.relative_to(PKG_ROOT).as_posix())
    return shipped


def read_excluded() -> set[str]:
    """Names listed under MANIFEST §Deliberately EXCLUDED.

    Returned as bare strings exactly as written (``e2e-testing.md``,
    ``backend-startup``, ``scripts/verify_subagent_delegation.py``). Matching is done
    on the *last* path segment as well, because the docs reference
    ``.agent/workflows/e2e-testing.md`` while the MANIFEST lists ``e2e-testing.md``
    under a "**Workflows** (`.agent/workflows/`)" group heading.
    """
    if not MANIFEST.is_file():
        return set()
    excluded: set[str] = set()
    in_section = False
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = "EXCLUDED" in line
            continue
        if not in_section:
            continue
        if not EXCLUDED_BULLET.match(line):
            continue
        for raw in CODE_SPAN.findall(line):
            name = raw.strip().rstrip("/")
            if not name:
                continue
            excluded.add(name)
            excluded.add(name.rsplit("/", 1)[-1])
    return excluded


def required_files() -> set[str]:
    """Package-relative paths whose references may not be satisfied by EXCLUDED."""
    out: set[str] = set()
    for pattern in REQUIRED_REFERENCE_FILES:
        if "*" in pattern:
            parent, _, leaf = pattern.rpartition("/")
            out.update(
                p.relative_to(PKG_ROOT).as_posix()
                for p in (PKG_ROOT / parent).glob(leaf)
                if p.is_file()
            )
        elif (PKG_ROOT / pattern).is_file():
            out.add(pattern)
    return out


def normalize(ref: str) -> str | None:
    """Clean a raw candidate, or return None if it is not a path reference."""
    ref = ref.strip().strip("*_")
    # Strip a trailing sentence mark that got inside the span/link.
    ref = ref.rstrip(".,;:)")
    # Anchors and query strings are not part of the filesystem path.
    ref = ref.split("#", 1)[0].split("?", 1)[0]
    if not ref or ref.startswith(("http://", "https://", "mailto:")):
        return None
    # Docs sometimes write a leading ./ or a file:/// URI.
    if ref.startswith("./"):
        ref = ref[2:]
    if ref.startswith("file:///"):
        return None
    # A code span holding a whole command is not a path reference.
    if " " in ref:
        return None
    if not ref.startswith(ROOTS):
        return None
    # ``file.md:120-134`` cites a location *in* a file; the file itself must exist,
    # so drop the citation and check the path.
    ref = LINE_CITATION.sub("", ref)
    for tail in GLOB_TAILS:
        if ref.endswith(tail):
            ref = ref[: -len(tail)] + "/"
            break
    return ref or None


#: Suffixes that make a bare link target a *file* reference rather than a heading
#: anchor, an external shorthand, or prose in brackets.
LINK_SUFFIXES = (
    ".md", ".py", ".ps1", ".psm1", ".sh", ".json", ".yaml", ".yml", ".toml", ".txt",
)


def normalize_link(raw: str, referrer: str) -> str | None:
    """A *relative* link target, rewritten into the coordinate system code spans use.

    ``normalize()`` only keeps a candidate that starts with a ROOTS prefix, which is
    the right rule for a code span -- an unanchored word in backticks is usually a flag
    or an enum value, not a path. Applied to a markdown link it was silently wrong:
    ``[missing](missing-policy.md)`` and ``[x](../skills/foo/SKILL.md)`` are the most
    ordinary links a doc contains, they are the strongest form of promise this gate
    checks (a link invites the reader to follow it), and every one of them was dropped
    before it reached ``resolve()``. A copied package with a dangling relative link
    passed the reference scan reporting zero references found.

    The target is joined onto the referring document's directory and then, for a doc
    under ``core/``, the ``core/`` prefix is stripped -- so the result is spelled the way
    a code span in the same file would spell it. That matters more than it looks:
    every downstream classifier (``is_excluded``, ``RUNTIME_TREES``, ``ADOPTER_CREATED``,
    ``resolution_roots``) is written in that one coordinate system, and a second one
    would need a second copy of each.
    """
    ref = raw.strip().strip("*_").rstrip(".,;:)")
    ref = ref.split("#", 1)[0].split("?", 1)[0]
    if not ref or " " in ref:
        return None
    if ref.startswith(("http://", "https://", "mailto:", "file:///", "/")):
        return None
    if ref.startswith("./"):
        ref = ref[2:]
    if ref.startswith(ROOTS):
        return None  # normalize() owns the root-anchored spelling
    bare = LINE_CITATION.sub("", ref)
    if not (bare.endswith(LINK_SUFFIXES) or bare.endswith("/")):
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(referrer), bare))
    # A target that climbs *past* the package root was written from somewhere this
    # package is not: ``core/templates/TASK-TEMPLATE.md`` links
    # ``../../../.agent/docs/output-evidence-policy.md``, which is correct from
    # ``docs/execution/plans/<slug>/`` where the adopter's copy lives, and three levels
    # too high from where the template sits here. The remainder after the climb is what
    # the author meant -- a repo-root-relative path -- so that is what gets resolved.
    # Reading it any other way would report every template link as broken and teach the
    # next person to stop reading this gate's output.
    while joined.startswith("../"):
        joined = joined[3:]
    if bare.endswith("/"):
        joined += "/"
    if joined.startswith("core/"):
        joined = joined[len("core/"):]
    return joined or None


def is_shape(ref: str) -> bool:
    """True if *ref* is a filename *pattern*, not a literal path.

    ``{{TOKEN}}`` is removed first: those are sanitizer placeholders standing in for
    a real value, and ``resolve()`` matches them by shape against shipped files, so a
    ``{{TOKEN}}`` path that fails to resolve is a genuine defect and must not be
    excused here.
    """
    return any(m in TOKEN_SPAN.sub("", ref) for m in SHAPE_MARKERS)


def is_excluded(ref: str, excluded: set[str]) -> bool:
    """True if *ref* -- or any directory on its path -- is MANIFEST §EXCLUDED.

    Skills are excluded by directory name (``backend-startup``) while the docs cite
    the file inside them (``.agent/skills/backend-startup/SKILL.md``), so every
    segment is tested, not just the basename.
    """
    bare = ref.rstrip("/")
    if bare in excluded:
        return True
    return any(segment in excluded for segment in bare.split("/") if segment)


def resolution_roots(referrer: str) -> tuple[str, ...]:
    """Prefixes to try for a reference found in *referrer*, most specific first.

    Packaged ``core/**`` docs write paths as they will appear in the *adopter's* repo
    root (``.agent/docs/commands.md``), so those resolve under ``core/``. Package-root
    docs (README, ADOPTION-GUIDE) write ``core/...`` and ``scripts/...``, which resolve
    at the package root. Registry-home docs write paths relative to the live home,
    whose shipped template is the package-root ``.agent/``.
    """
    roots = ["core/", ""]
    if referrer.startswith(".agent/") or referrer in REGISTRY_HOME_DOCS:
        roots.append(".agent/")
    return tuple(roots)


def resolve(ref: str, shipped: set[str], referrer: str = "") -> str | None:
    """Return the shipped path that satisfies *ref*, or None."""
    directory = ref.endswith("/")
    bare = ref.rstrip("/")
    alias = PATH_ALIASES.get(bare)
    if alias is not None:
        return alias if alias in shipped else None
    for root in resolution_roots(referrer):
        candidate = f"{root}{bare}"
        if "{{" in candidate:
            # Placeholder in the path (e.g. {{PROJECT_NAME}}-builder.md) -- match by
            # shape rather than by literal string.
            pattern = re.escape(candidate)
            pattern = re.sub(r"\\\{\\\{[A-Z_]+\\\}\\\}", "[^/]+", pattern)
            regex = re.compile(f"^{pattern}$")
            hit = next((s for s in shipped if regex.match(s)), None)
            if hit:
                return hit
            continue
        if candidate in shipped:
            if directory and not (PKG_ROOT / candidate).is_dir():
                continue
            return candidate
    return None


def scan_refs(
    md_paths: list[Path],
) -> tuple[list[tuple[str, int, str]], dict[str, list[str]]]:
    """Return ([(package_rel_file, line_no, ref)], {file: lines}).

    The line text is returned alongside so ``discloses()`` can read the neighbourhood
    of a reference without re-reading every file.
    """
    found: list[tuple[str, int, str]] = []
    text_by_file: dict[str, list[str]] = {}
    for path in md_paths:
        rel = path.relative_to(PKG_ROOT).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        text_by_file[rel] = lines
        for line_no, line in enumerate(lines, start=1):
            for raw in CODE_SPAN.findall(line) + LINK.findall(line):
                ref = normalize(raw)
                if ref:
                    found.append((rel, line_no, ref))
            for raw in LINK.findall(line):
                ref = normalize_link(raw, rel)
                if ref:
                    found.append((rel, line_no, ref))
    return found, text_by_file


def discloses(lines: list[str], line_no: int) -> bool:
    """True if the text around *line_no* tells the reader the path is not shipped."""
    lo = max(0, line_no - 1 - DISCLOSURE_WINDOW)
    hi = min(len(lines), line_no + DISCLOSURE_WINDOW)
    return bool(DISCLOSURE.search(chr(10).join(lines[lo:hi])))


def is_markdown_link(lines: list[str], line_no: int, ref: str, referrer: str = "") -> bool:
    """True if *ref* appears on that line as a clickable ``](target)`` link.

    A link is a stronger promise than a code span: a code span names a path, a link
    invites the reader to follow it. Disclosure can excuse the first and not the
    second -- "not shipped" next to a live-looking link is a mixed signal, and the
    link is what a tool (or a hurried reader) acts on.
    """
    line = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
    return any(
        normalize(target) == ref or normalize_link(target, referrer) == ref
        for target in LINK.findall(line)
    )


def all_markdown() -> list[Path]:
    return sorted(
        p
        for p in PKG_ROOT.rglob("*.md")
        if "__pycache__" not in p.parts and ".git" not in p.parts
    )


def run_refcheck(md_paths: list[Path], *, report: bool = True) -> tuple[int, list[str]]:
    """Return (exit_code, failure_lines). ``report=False`` suppresses stdout."""
    shipped = iter_shipped()
    excluded = read_excluded()
    required = required_files()
    refs, text_by_file = scan_refs(md_paths)
    out: list[str] = []

    unresolved: list[tuple[str, int, str]] = []
    required_dangling: list[tuple[str, int, str, str]] = []
    counts = {
        "OK": 0,
        "EXCLUDED": 0,
        "RUNTIME": 0,
        "SHAPE": 0,
        "PROSE": 0,
        "DISCLOSED": 0,
        "ADOPTER": 0,
    }
    used_exemptions: set[tuple[str, int, str]] = set()
    for rel, line_no, ref in refs:
        lines = text_by_file[rel]
        if resolve(ref, shipped, rel):
            counts["OK"] += 1
        elif ref.rstrip("/") in ADOPTER_CREATED:
            counts["ADOPTER"] += 1
        elif is_excluded(ref, excluded):
            # The two-class rule. EXCLUDED absolves an on-demand doc outright. In an
            # always-loaded file it only absolves a reference the surrounding text
            # admits is absent, and never a clickable link.
            if rel not in required:
                counts["EXCLUDED"] += 1
            elif is_markdown_link(lines, line_no, ref, rel):
                required_dangling.append((rel, line_no, ref, "clickable link"))
            elif discloses(lines, line_no):
                counts["DISCLOSED"] += 1
            else:
                required_dangling.append((rel, line_no, ref, "no disclosure nearby"))
        elif ref.startswith(RUNTIME_TREES):
            counts["RUNTIME"] += 1
        elif is_shape(ref):
            counts["SHAPE"] += 1
        elif (rel, line_no, ref) in NOT_A_PROMISE:
            counts["PROSE"] += 1
            used_exemptions.add((rel, line_no, ref))
        else:
            unresolved.append((rel, line_no, ref))

    # A stale exemption is a hole in the gate: it would silently absolve a future
    # reference at the same coordinates. Only meaningful on a full scan.
    stale: list[tuple[str, int, str]] = []
    if len(md_paths) == len(all_markdown()):
        stale = sorted(set(NOT_A_PROMISE) - used_exemptions)
        for key in stale:
            out.append(
                f"STALE-EXEMPT {key[0]}:{key[1]}  ->  {key[2]}  (no longer present)"
            )

    for rel, line_no, ref, why in required_dangling:
        out.append(
            f"REQUIRED-DANGLING {rel}:{line_no}  ->  {ref}  "
            f"(EXCLUDED path in an always-loaded file, {why})"
        )
    for rel, line_no, ref in unresolved:
        out.append(f"UNRESOLVED  {rel}:{line_no}  ->  {ref}")

    out.append("")
    out.append("=" * 70)
    out.append(f"  markdown files scanned:   {len(md_paths)}")
    out.append(f"  always-loaded in scan:    {len(required & {p.relative_to(PKG_ROOT).as_posix() for p in md_paths})}")
    out.append(f"  path references found:    {len(refs)}")
    out.append(f"  resolved to shipped file: {counts['OK']}")
    out.append(f"  MANIFEST EXCLUDED:        {counts['EXCLUDED']}")
    out.append(f"  EXCLUDED + disclosed:     {counts['DISCLOSED']}")
    out.append(f"  adopter-created files:    {counts['ADOPTER']}")
    out.append(f"  runtime-created (trees):  {counts['RUNTIME']}")
    out.append(f"  filename pattern/shape:   {counts['SHAPE']}")
    out.append(f"  not-a-promise (exempt):   {counts['PROSE']}")
    out.append(f"  stale exemptions:         {len(stale)}")
    out.append(f"  REQUIRED-DANGLING:        {len(required_dangling)}")
    out.append(f"  UNRESOLVED:               {len(unresolved)}")
    out.append("=" * 70)

    if report:
        print("\n".join(out))
    code = 1 if (unresolved or stale or required_dangling) else 0
    failures = [
        line
        for line in out
        if line.startswith(("UNRESOLVED", "REQUIRED-DANGLING", "STALE-EXEMPT"))
    ]
    return code, failures


def tool_is_shipped(name: str, shipped: set[str]) -> bool:
    """True if this ``tools/<name>`` resolves to a file the package ships.

    Both roots are tried because the docs are written from two vantage points: a
    packaged doc under ``core/`` says ``tools/x.py`` meaning the adopter's repo root
    (``core/tools/x.py`` here), while a package-root doc means ``tools/x.py`` here.
    """
    candidates = {name, f"core/{name}"} if not name.startswith("core/") else {name}
    return any(c in shipped for c in candidates)


def run_toolcheck(md_paths: list[Path], *, report: bool = True) -> tuple[int, list[str]]:
    """Every ``tools/<name>`` a packaged doc tells the reader to RUN is classified.

    Returns (exit_code, failure_lines). ``8`` on an unclassified or stale name --
    a code of its own so a caller can tell this gate apart from the reference gate
    it shares a file with.
    """
    shipped = iter_shipped()
    full_scan = len(md_paths) == len(all_markdown())

    seen: dict[str, list[str]] = {}
    for path in md_paths:
        rel = path.relative_to(PKG_ROOT).as_posix()
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for raw in TOOL_PATH.findall(line):
                seen.setdefault(tool_name(raw), []).append(f"{rel}:{line_no}")

    out: list[str] = []
    counts = {"shipped": 0}
    unclassified: list[str] = []
    for name, sites in sorted(seen.items()):
        if tool_is_shipped(name, shipped):
            counts["shipped"] += 1
            continue
        entry = TOOL_CLASSES.get(name)
        if entry is None:
            unclassified.append(name)
            out.append(
                f"UNCLASSIFIED-TOOL  {name}  ({len(sites)} site(s), e.g. {sites[0]})"
            )
            continue
        kind, _reason = entry
        counts[kind] = counts.get(kind, 0) + 1

    # A classified name that nothing references any more, and a classification for a
    # tool the package has since started shipping, are both holes: each pre-authorises
    # a future reference nobody reviewed. Same discipline as STALE-EXEMPT above, and
    # only checkable on a full scan.
    stale: list[str] = []
    if full_scan:
        for name in sorted(TOOL_CLASSES):
            if name not in seen:
                stale.append(name)
                out.append(f"STALE-TOOL-CLASS   {name}  (classified, no longer referenced)")
            elif tool_is_shipped(name, shipped):
                stale.append(name)
                out.append(
                    f"STALE-TOOL-CLASS   {name}  (classified as "
                    f"{TOOL_CLASSES[name][0]}, but the package now ships it)"
                )
        bad_kind = sorted(n for n, (k, _) in TOOL_CLASSES.items() if k not in TOOL_CLASS_KINDS)
        for name in bad_kind:
            stale.append(name)
            out.append(
                f"STALE-TOOL-CLASS   {name}  (kind {TOOL_CLASSES[name][0]!r} is not "
                f"one of {', '.join(TOOL_CLASS_KINDS)})"
            )

    out.append("")
    out.append("=" * 70)
    out.append(f"  markdown files scanned:   {len(md_paths)}")
    out.append(f"  distinct tools/ commands: {len(seen)}")
    out.append(f"  shipped by this package:  {counts['shipped']}")
    for kind in TOOL_CLASS_KINDS:
        out.append(f"  {kind + ':':<25} {counts.get(kind, 0)}")
    out.append(f"  stale classifications:    {len(stale)}")
    out.append(f"  UNCLASSIFIED:             {len(unclassified)}")
    out.append("=" * 70)
    if report:
        print("\n".join(out))
    failures = [
        line for line in out if line.startswith(("UNCLASSIFIED-TOOL", "STALE-TOOL-CLASS"))
    ]
    return (8 if failures else 0), failures


def run_token(tokens: list[str], allow: list[str]) -> int:
    allowed = set(allow)
    hits: list[tuple[str, int, str, str]] = []
    for path in sorted(PKG_ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(PKG_ROOT).as_posix()
        lower = text.lower()
        if not any(t.lower() in lower for t in tokens):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for token in tokens:
                if token.lower() in line.lower():
                    hits.append((rel, line_no, token, line.strip()[:110]))

    disallowed = [h for h in hits if h[0] not in allowed]
    for rel, line_no, token, line in hits:
        mark = "OK  " if rel in allowed else "HIT "
        print(f"{mark}{rel}:{line_no}  [{token}]  {line}")

    print("\n" + "=" * 70)
    print(f"  tokens:          {tokens}")
    print(f"  allowed files:   {sorted(allowed) or '(none)'}")
    print(f"  total hits:      {len(hits)}")
    print(f"  DISALLOWED:      {len(disallowed)}")
    print("=" * 70)
    return 1 if disallowed else 0


def run_backlink(name: str) -> int:
    hits: list[tuple[str, int, str]] = []
    for path in all_markdown():
        rel = path.relative_to(PKG_ROOT).as_posix()
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if name in line:
                hits.append((rel, line_no, line.strip()[:110]))

    for rel, line_no, line in hits:
        print(f"{rel}:{line_no}  {line}")

    files = sorted({h[0] for h in hits})
    print("\n" + "=" * 70)
    print(f"  backlink target: {name}")
    print(f"  referencing files ({len(files)}):")
    for rel in files:
        print(f"    {rel}")
    print("=" * 70)
    return 0 if hits else 1


#: Marker line count for a selftest injection. The reference is put on its own line
#: with blank lines around it so the disclosure window sees only what we wrote --
#: otherwise whatever happens to sit at the end of AGENTS.md decides the verdict.
SELFTEST_PAD = "\n\n<!-- refcheck selftest -->\n\n"


def _selftest_arms(excluded_name: str) -> list[tuple[str, str, str, bool]]:
    """(label, injected markdown, expected failure class, expect_failure)."""
    return [
        # A path that exists nowhere and is in no list. The base case.
        (
            "ordinary-unresolved",
            "See `.agent/docs/no-such-file-xyz.md` for details.",
            "UNRESOLVED",
            True,
        ),
        # EXCLUDED, in an always-loaded file, presented as if available. This is the
        # class the source repo's gate passed twice -- the reason this file exists.
        (
            "required-undisclosed",
            f"Follow `.agent/workflows/{excluded_name}` before planning.",
            "REQUIRED-DANGLING",
            True,
        ),
        # Same path, as a clickable link, WITH a disclosure. Disclosure excuses a code
        # span; it must not excuse a link, because the link is what gets followed.
        (
            "required-disclosed-link",
            f"It is **not shipped**, but see "
            f"[the workflow](.agent/workflows/{excluded_name}).",
            "REQUIRED-DANGLING",
            True,
        ),
        # Same path, as a code span, WITH a disclosure. This one must PASS. A gate
        # that fails everything is not discriminating, it is just off (V4's mirror:
        # a check that cannot pass tells you as little as one that cannot fail).
        (
            "required-disclosed-span",
            f"`.agent/workflows/{excluded_name}` is **not shipped** -- write your own.",
            "REQUIRED-DANGLING",
            False,
        ),
        # A bare relative link -- the most ordinary link a doc contains, and the form
        # the root allowlist dropped before it reached the resolver. A copied package
        # carrying [missing](missing-policy.md) passed the scan reporting zero
        # references found, so this arm is the evidence that the extractor sees it now.
        (
            "bare-relative-link-unresolved",
            "See [the policy](no-such-sibling-xyz.md) first.",
            "UNRESOLVED",
            True,
        ),
        # The same shape, pointing at a sibling that really is shipped. Must PASS: a
        # relative-link rule that flagged every relative link would be worse than the
        # blind spot it replaced, because it would be noisy enough to get switched off.
        (
            "bare-relative-link-resolves",
            "See [the guardrails](GUARDRAILS.md) for the SIGNs.",
            "UNRESOLVED",
            False,
        ),
        # ``docs/`` was absent from ROOTS, so a docs/ path was not classified as
        # adopter-created -- it was not seen at all. It must now be *counted*, and
        # counted as adopter-created rather than as a defect, so this arm must PASS
        # while the summary line below proves the reference was actually extracted.
        (
            "docs-path-counted-not-unresolved",
            "Plans live under `docs/execution/plans/` in your repo.",
            "UNRESOLVED",
            False,
        ),
    ]


class _Mutation:
    """Reversible edits to the temp copy, so one arm cannot contaminate the next.

    The tool-gate arms need to touch more than one file (a stale classification is
    proved by removing a name from *every* doc that cites it), so they cannot use the
    single-victim write/restore the reference arms use.
    """

    def __init__(self, work: Path) -> None:
        self.work = work
        self.saved: dict[str, str | None] = {}

    def _save(self, rel: str) -> Path:
        path = self.work / rel
        if rel not in self.saved:
            self.saved[rel] = (
                path.read_text(encoding="utf-8") if path.is_file() else None
            )
        return path

    def append(self, rel: str, text: str) -> None:
        path = self._save(rel)
        path.write_text(
            (self.saved[rel] or "") + SELFTEST_PAD + text + "\n", encoding="utf-8"
        )

    def create(self, rel: str, text: str) -> None:
        path = self._save(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def replace_everywhere(self, token: str, replacement: str) -> None:
        for path in sorted(self.work.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            if token not in text:
                continue
            rel = path.relative_to(self.work).as_posix()
            self._save(rel)
            path.write_text(text.replace(token, replacement), encoding="utf-8")

    def restore(self) -> None:
        for rel, original in self.saved.items():
            path = self.work / rel
            if original is None:
                path.unlink()
            else:
                path.write_text(original, encoding="utf-8")
        self.saved.clear()


def _tool_selftest_arms(
    classified: str, shipped_tool: str
) -> list[tuple[str, Callable[[_Mutation], None], bool]]:
    """(label, mutation, expect_failure) for the ``tools/<name>`` gate.

    ``classified`` is a name in TOOL_CLASSES (therefore not shipped); ``shipped_tool``
    is a ``tools/<name>.py`` this package really ships.
    """
    return [
        # Buried mid-command, which is the whole reason this gate scans lines rather
        # than code spans. Five absent tools shipped this way while the reference gate
        # reported 0 unresolved, because `normalize()` only ever saw span-initial paths.
        (
            "unclassified-tool-mid-command",
            lambda m: m.append(
                "core/AGENTS.md",
                "Run `rtk proxy uv run python tools/no_such_tool_xyz42.py --check` "
                "before planning.",
            ),
            True,
        ),
        # Unclassified and unfenced. The same name has to fail in prose too, or a doc
        # could authorise a missing tool merely by not putting it in backticks.
        (
            "unclassified-tool-bare-prose",
            lambda m: m.append(
                "core/AGENTS.md", "The checker lives at tools/no_such_tool_xyz43.py."
            ),
            True,
        ),
        # The package starts shipping a name that is still classified as unshipped.
        # Benign-looking, and exactly how a classification table rots into a blanket
        # permit: the entry now excuses nothing and nobody re-reads it.
        (
            "classified-name-now-shipped",
            lambda m: m.create(f"core/{classified}", "# selftest placeholder\n"),
            True,
        ),
        # The last reference to a classified name goes away. The entry survives and
        # silently pre-authorises the next doc to cite a tool nobody re-reviewed.
        (
            "classification-no-longer-referenced",
            lambda m: m.replace_everywhere(classified, "tools/REMOVED-BY-SELFTEST"),
            True,
        ),
        # The same absent tool, spelled with a backslash. This package documents
        # PowerShell beside bash, so both separators are written -- and the classifier
        # keyed on the slash form only. Changing that one character made the promise
        # invisible: the gate reported 0 unclassified for `tools\missing_gate.py` and
        # exit 8 for the identical `tools/missing_gate.py`. Paired with the arm above
        # so the two spellings cannot drift apart again.
        (
            "unclassified-tool-backslash-command",
            lambda m: m.append(
                "core/AGENTS.md",
                "Run `python tools" + chr(92) + "no_such_tool_xyz44.py --check` first.",
            ),
            True,
        ),
        # And the shipped tool in backslash form must still PASS -- normalisation has to
        # work in both directions, or the fix above just moves the false negative into a
        # false positive that gets the gate switched off.
        (
            "shipped-tool-backslash-command-ok",
            lambda m: m.append(
                "core/AGENTS.md",
                "Run `python " + shipped_tool.replace("/", chr(92)) + " --help`.",
            ),
            False,
        ),
        # A command naming a tool the package really ships. This one must PASS: a gate
        # that flags every tools/ path is not discriminating, it is just off.
        (
            "shipped-tool-command-ok",
            lambda m: m.append(
                "core/AGENTS.md", f"Run `rtk proxy uv run python {shipped_tool} --help`."
            ),
            False,
        ),
    ]


def run_selftest() -> int:
    """Prove the gate can fail, per class (verification-principles V4/V5).

    A clean run is only evidence if the detector was shown able to detect. This
    copies the package to a temp tree, injects one known-bad (or known-good)
    reference at a time, and compares the failure lines against a **baseline** run
    of the untouched copy. Comparing against a baseline rather than against exit 0
    matters: the package can legitimately carry a known unresolved reference, and an
    arm that only checked ``exit == 1`` would then pass without detecting anything.
    """
    excluded = read_excluded()
    excluded_name = next(
        (n for n in sorted(excluded) if n.endswith(".md") and "/" not in n), None
    )
    if excluded_name is None:
        print("SELFTEST-FAIL: no MANIFEST-EXCLUDED .md name to build the arms from")
        return 3

    target = "core/AGENTS.md"
    arms = _selftest_arms(excluded_name)
    tmp = Path(tempfile.mkdtemp(prefix="refcheck-selftest-"))
    failures = 0
    try:
        work = tmp / "pkg"
        shutil.copytree(
            PKG_ROOT, work, ignore=shutil.ignore_patterns("__pycache__", ".git")
        )
        victim = work / target
        pristine = victim.read_text(encoding="utf-8")
        runner = [sys.executable, str(work / "scripts" / "refcheck.py"), "--all"]

        base = subprocess.run(runner, capture_output=True, text=True)
        baseline = {
            line
            for line in base.stdout.splitlines()
            if line.startswith(("UNRESOLVED", "REQUIRED-DANGLING", "STALE-EXEMPT"))
        }
        print(
            f"BASE {len(baseline)} pre-existing failure line(s) in the copy, "
            f"exit {base.returncode}"
        )
        # The reference arms below used to read only the diagnostic delta and never
        # ``proc.returncode``, which left the one mutation V5 names as fatal completely
        # uncovered: making the combined scan `return 1` unconditionally kept every
        # diagnostic line identical, so all arms still passed and --selftest still
        # exited 0 while the gate refused everything. The status is now asserted in
        # every arm, and the pristine copy is armed first -- because a must-pass arm
        # can only mean something if a clean tree is known to exit 0.
        #
        # Tied to the baseline rather than hardcoded to 0: a copy that legitimately
        # carries an unresolved reference must exit 1, and demanding 0 there would
        # report the package's own state as a selftest bug.
        want_base = 1 if baseline else 0
        if base.returncode == want_base:
            print(f"PASS {'pristine-copy-status':<24} exit {base.returncode} matches "
                  f"{len(baseline)} baseline line(s)")
        else:
            print(
                f"FAIL {'pristine-copy-status':<24} untouched copy exited "
                f"{base.returncode} with {len(baseline)} failure line(s); expected "
                f"{want_base}. A gate whose status does not follow its own findings "
                f"cannot make any arm below mean anything."
            )
            failures += 1

        # V5, applied to the must-PASS arms specifically. "No new failure" is the same
        # output whether the reference was examined and cleared or never extracted at
        # all -- which is exactly how `docs/missing-policy.md` and bare relative links
        # went unchecked while the summary reported zero references on lines that named
        # one. So the extraction is observed directly: inject three references of the
        # three previously-invisible shapes and require the found-count to rise by three.
        def found_count(stdout: str) -> int:
            for line in stdout.splitlines():
                if "path references found:" in line:
                    return int(line.rsplit(":", 1)[1])
            return -1

        base_found = found_count(base.stdout)
        victim.write_text(
            pristine
            + SELFTEST_PAD
            + "Plans live under `docs/execution/plans/` in your repo.\n\n"
            + "See [the guardrails](GUARDRAILS.md) and [nothing](no-such-xyz.md).\n",
            encoding="utf-8",
        )
        probe = subprocess.run(runner, capture_output=True, text=True)
        probe_found = found_count(probe.stdout)
        if base_found >= 0 and probe_found - base_found == 3:
            print(
                f"PASS {'previously-invisible-shapes-extracted':<24} "
                f"found {base_found} -> {probe_found}"
            )
        else:
            print(
                f"FAIL {'previously-invisible-shapes-extracted':<24} injected a docs/ "
                f"path, a resolving relative link and a dangling one; found-count went "
                f"{base_found} -> {probe_found}, expected +3. A must-pass arm over a "
                f"reference that was never extracted proves nothing."
            )
            failures += 1

        for label, injection, want, expect_failure in arms:
            victim.write_text(pristine + SELFTEST_PAD + injection + "\n", "utf-8")
            proc = subprocess.run(runner, capture_output=True, text=True)
            new = {
                line
                for line in proc.stdout.splitlines()
                if line.startswith(
                    ("UNRESOLVED", "REQUIRED-DANGLING", "STALE-EXEMPT")
                )
            } - baseline
            detected = [line for line in new if line.startswith(want)]
            want_code = 1 if (expect_failure or baseline) else 0
            if proc.returncode != want_code:
                print(
                    f"FAIL {label:<24} expected exit {want_code}, got "
                    f"{proc.returncode} ({sorted(new) or 'no new failures'})"
                )
                failures += 1
            elif expect_failure and detected:
                print(f"PASS {label:<24} exit {proc.returncode}, new {want} reported")
            elif expect_failure:
                print(
                    f"FAIL {label:<24} expected a new {want}; "
                    f"got {sorted(new) or 'no new failures'}"
                )
                failures += 1
            elif new:
                print(f"FAIL {label:<24} expected no new failure; got {sorted(new)}")
                failures += 1
            else:
                print(f"PASS {label:<24} exit {proc.returncode}, correctly not flagged")
        victim.write_text(pristine, encoding="utf-8")

        # ---- the tools/<name> gate --------------------------------------------
        # Exit code is asserted here, not just the failure line: the whole point of
        # 8 is that a caller can tell an unclassified tool command apart from an
        # unresolved reference, and both gates live in this one file.
        classified = next(
            (n for n, (kind, _) in sorted(TOOL_CLASSES.items()) if kind == "not-shipped"),
            None,
        )
        shipped_tool = next(
            (
                rel[len("core/") :]
                for rel in sorted(iter_shipped())
                if rel.startswith("core/tools/") and rel.endswith(".py")
            ),
            None,
        )
        if classified is None or shipped_tool is None:
            print(
                "SELFTEST-FAIL: need one not-shipped TOOL_CLASSES entry and one "
                f"shipped core/tools/*.py to build the tool arms "
                f"(got {classified!r}, {shipped_tool!r})"
            )
            return 3

        tool_arms = _tool_selftest_arms(classified, shipped_tool)
        tool_runner = [
            sys.executable, str(work / "scripts" / "refcheck.py"), "--tools-only"
        ]

        def tool_failures(proc: subprocess.CompletedProcess[str]) -> set[str]:
            return {
                line
                for line in proc.stdout.splitlines()
                if line.startswith(("UNCLASSIFIED-TOOL", "STALE-TOOL-CLASS"))
            }

        base_tools = subprocess.run(tool_runner, capture_output=True, text=True)
        tool_baseline = tool_failures(base_tools)
        print(
            f"\nBASE {len(tool_baseline)} pre-existing tool failure line(s), "
            f"exit {base_tools.returncode}"
        )

        mutation = _Mutation(work)
        for label, mutate, expect_failure in tool_arms:
            mutate(mutation)
            proc = subprocess.run(tool_runner, capture_output=True, text=True)
            new = tool_failures(proc) - tool_baseline
            mutation.restore()
            if expect_failure and new and proc.returncode == 8:
                print(f"PASS {label:<36} exit 8, {len(new)} new line(s)")
            elif expect_failure:
                print(
                    f"FAIL {label:<36} expected exit 8 with a new failure line; "
                    f"got exit {proc.returncode}, {sorted(new) or 'no new lines'}"
                )
                failures += 1
            # The expected code for a must-pass arm depends on the baseline: if the copy
            # already carries a tool failure, 8 is the honest code and demanding 0 would
            # make this arm report the package's pre-existing state as a selftest bug.
            elif new or proc.returncode != (8 if tool_baseline else 0):
                print(
                    f"FAIL {label:<36} expected a clean run; got exit "
                    f"{proc.returncode}, {sorted(new) or 'no new lines'}"
                )
                failures += 1
            else:
                print(f"PASS {label:<36} correctly not flagged")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # +2 for the two arms built inline rather than in an arm table: the pristine-copy
    # status check and the extraction-count check. Counting only the tables understated
    # the suite, and an arm nobody counts is an arm nobody misses when it disappears.
    total = len(arms) + len(tool_arms) + 2
    must_pass = (
        sum(1 for a in arms if not a[3]) + sum(1 for a in tool_arms if not a[2]) + 2
    )
    print(
        f"\nRESULT: {total} arm(s) ({must_pass} must-pass), {failures} failure(s)"
    )
    return 3 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--all", action="store_true", help="scan every packaged .md")
    parser.add_argument(
        "--required-only",
        action="store_true",
        help="scan only REQUIRED_REFERENCE_FILES (the always-loaded set)",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        metavar="PKG_REL",
        help="scan only this package-relative .md (repeatable)",
    )
    parser.add_argument(
        "--token",
        action="append",
        default=[],
        help="report every occurrence of this token package-wide (repeatable)",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="PKG_REL",
        help="file where --token hits are permitted (repeatable)",
    )
    parser.add_argument(
        "--tools-only",
        action="store_true",
        help="only check that every tools/<name> command path is shipped or classified",
    )
    parser.add_argument(
        "--backlink",
        default=None,
        help="list packaged .md files that reference this name",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="prove the gate can fail by injecting known-bad references",
    )
    args = parser.parse_args()

    modes = sum(
        bool(x)
        for x in (
            args.all,
            args.required_only,
            args.file,
            args.token,
            args.backlink,
            args.selftest,
            args.tools_only,
        )
    )
    if modes == 0:
        args.all = True
    elif modes > 1:
        print(
            "ERROR: --all / --required-only / --file / --token / --backlink / "
            "--tools-only / --selftest are mutually exclusive",
            file=sys.stderr,
        )
        return 2

    if args.selftest:
        return run_selftest()
    if args.token:
        return run_token(args.token, args.allow)
    if args.backlink:
        return run_backlink(args.backlink)

    if args.tools_only:
        return run_toolcheck(all_markdown())[0]

    if args.required_only:
        md_paths = sorted(PKG_ROOT / rel for rel in required_files())
    elif args.file:
        md_paths = []
        for rel in args.file:
            path = PKG_ROOT / rel
            if not path.is_file():
                print(f"ERROR: no such packaged file: {rel}", file=sys.stderr)
                return 2
            md_paths.append(path)
    else:
        md_paths = all_markdown()

    ref_code = run_refcheck(md_paths)[0]
    # Both gates always run, and the tool gate only runs on a full scan: its stale
    # check compares the classification table against the whole package, so a subset
    # scan would report every unreferenced-in-this-subset entry as stale.
    tool_code = run_toolcheck(all_markdown())[0] if md_paths == all_markdown() else 0
    return ref_code or tool_code


if __name__ == "__main__":
    raise SystemExit(main())
