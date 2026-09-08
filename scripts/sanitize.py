#!/usr/bin/env python3
"""sanitize.py -- replace real project strings with placeholder tokens.

This is the AUTHORING tool. It was used once to strip the originating project's
identifiers (the source slug recorded in ``placeholders.SOURCE_SLUG``, its repo URL,
its receipts dir, its root path) out of the framework files and replace them with
``{{PLACEHOLDER}}`` tokens. It ships in the package for transparency and so the
operation can be re-run or audited.

Adopters do NOT normally run this -- they run ``instantiate.py`` to fill the
placeholders in with their own values.

Usage
-----
    python scripts/sanitize.py --dry-run      # show what would change, touch nothing
    python scripts/sanitize.py                # apply in place
    python scripts/sanitize.py --verify       # after applying, assert zero raw
                                             # source slugs AND zero model slugs

The script targets the package root (its own parent's parent) and skips the
``scripts/`` directory (so it never rewrites the substitution rules themselves) and
anything that is not a UTF-8 text file.

``--verify`` also invokes ``check_model_slugs.py`` against this package so a
catalog snapshot cannot re-enter ``core/`` through the packaging path. The
checker is located via the S2 order (``AGENT_MODEL_REGISTRY`` → ``AGENT_MODEL_REGISTRY_HOME`` →
``%USERPROFILE%/.agent``). An unreachable registry is a named failure
(``registry_not_found``), never a silent pass. AUTOGEN drift is reported
separately from a tier-1 slug: both fail ``--verify``, but they are not the
same defect.

``--verify`` runs five gates, each with its own exit code so a red build says which
one objected, and every gate runs even after an earlier one fails:

===== ==========================================================================
``2`` a raw source slug survived the substitution
``3`` the model registry could not be reached -- never read as a pass
``4`` a tier-1 model slug is in the package; ``5`` AUTOGEN drift
``6`` a versioned model name in packaged instruction prose
``7`` a dangling reference (``refcheck.run_refcheck``)
``8`` a ``tools/<name>`` command path neither shipped nor classified
      (``refcheck.run_toolcheck``) -- the class the reference gate cannot see,
      because a path buried inside a command is not a span-initial reference
===== ==========================================================================
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any

# Allow running as a bare script (python scripts/sanitize.py) OR as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import placeholders as ph  # noqa: E402

# File suffixes we treat as editable text. Everything else is skipped.
TEXT_SUFFIXES = {
    ".md",
    ".yaml",
    ".yml",
    ".ps1",
    ".py",
    ".txt",
    ".json",
    ".toml",
    ".cfg",
    ".ini",
    ".sh",
    ".ts",
    ".tsx",
    ".js",
    ".svg",
    ".html",
    ".css",
}
# Directories never descended into.
SKIP_DIRS = {"scripts", ".git", "node_modules", "__pycache__", ".venv"}
# Single files that must not be placeholder-substituted. The package-root
# schema is a byte-copy of the live registry schema (AC-3.1); its `$id` URI
# contains SOURCE_SLUG as document identity. Rewriting it to
# `{{PROJECT_NAME}}` would break shipped==live, and leaving it in the walk
# makes `--verify` fail before the model-slug checker can run.
SKIP_FILES = frozenset({".agent/schema/model-registry.v1.schema.json"})


class RegistryUnavailable(RuntimeError):
    """The registry or its checker could not be reached.

    Named the same way as Zorivest's ``model_registry_client.RegistryUnavailable``:
    a verifier that reports success because it found nothing to check is worse
    than no verifier.
    """


def package_root() -> Path:
    """The agentic-framework/ directory (parent of this scripts/ folder)."""
    return Path(__file__).resolve().parent.parent


def iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if rel in SKIP_FILES:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def registry_homes(environ: dict[str, str] | None = None) -> list[Path]:
    """S2 locate order for the registry *home*, matching the package wrappers."""
    env = os.environ if environ is None else environ
    homes: list[Path] = []
    override = env.get("AGENT_MODEL_REGISTRY")
    if override:
        path = Path(override)
        homes.append(
            path.parent if path.suffix.lower() in {".json", ".yaml", ".yml"} else path
        )
    # Shared / "drive-root" home: a single registry serving several projects on one
    # machine. Configured by env, never a baked drive letter -- a literal like
    # ``P:/.agent`` is one machine's layout and is meaningless on macOS/Linux, where
    # this package is equally supported. See ``.agent/INSTANTIATE.md`` S2.
    shared = env.get("AGENT_MODEL_REGISTRY_HOME")
    if shared:
        homes.append(Path(shared))
    user = env.get("USERPROFILE") or env.get("HOME")
    if user:
        homes.append(Path(user) / ".agent")
    return homes


def locate_checker(environ: dict[str, str] | None = None) -> Path:
    """Return the live ``check_model_slugs.py``, skipping template wrappers."""
    for home in registry_homes(environ):
        candidate = home / "tools" / "check_model_slugs.py"
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # The package-root template is a locate-and-forward wrapper with no
        # check(); the live tool is the first file that actually scans.
        if "def check(" not in text:
            continue
        return candidate
    # A fail-closed message that does not say what to set gets "fixed" by disabling
    # the gate. Name the searched homes and the env vars that add one.
    searched = ", ".join(str(h) for h in registry_homes(environ)) or "(none)"
    raise RegistryUnavailable(
        "registry_not_found: no live check_model_slugs.py in the S2 locate order. "
        f"Searched: {searched}. Set AGENT_MODEL_REGISTRY to the compiled JSON file, "
        "or AGENT_MODEL_REGISTRY_HOME to the shared registry home. "
        "See .agent/INSTANTIATE.md section 1."
    )


def load_checker(environ: dict[str, str] | None = None) -> Any:
    path = locate_checker(environ)
    tools_dir = str(path.parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    spec = importlib.util.spec_from_file_location(
        "_sanitize_check_model_slugs", path
    )
    if spec is None or spec.loader is None:
        raise RegistryUnavailable(f"registry_not_found: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RegistryUnavailable(
            f"registry_not_found: cannot import {path}: {exc}"
        ) from exc
    if not callable(getattr(module, "check", None)):
        raise RegistryUnavailable(f"registry_not_found: {path} has no check()")
    return module


def verify_model_slugs(root: Path) -> int:
    """Run the checker; fail distinctly on slug vs AUTOGEN drift vs missing registry.

    AUTOGEN drift is a sanitizer failure (nonzero) because ``--verify`` is the
    authoring command for *this* package on the machine that stamped the four
    agent templates. Drift here means the shipped templates no longer match the
    registry ``--verify`` is using. Adopters do not run this script; they run
    ``instantiate.py`` and the copy → compile → sync → enforce sequence in
    INSTANTIATE.md §4. Reporting drift under the same heading as a tier-1
    slug would send the author looking for a pin that is not there.
    """
    try:
        checker = load_checker()
    except RegistryUnavailable as exc:
        print(f"  VERIFY FAILED:   {exc}")
        return 3

    registry_error = getattr(checker, "RegistryError", RuntimeError)
    try:
        report = checker.check(projects=[root], mode="enforce")
    except registry_error as exc:
        print(f"  VERIFY FAILED:   {exc}")
        return 3

    errors = report.get("errors") or []
    tier1 = report.get("tier1") or []
    drift = report.get("autogen_drift") or []

    if tier1:
        print(f"  VERIFY FAILED:   model-slug (tier-1): {len(tier1)} hit(s):")
        for hit in tier1:
            print(
                f"      {hit.get('relative')}:{hit.get('line')} {hit.get('match')}"
            )
    if drift:
        print(
            f"  VERIFY FAILED:   autogen_drift ({len(drift)}) "
            "— distinct from a tier-1 slug:"
        )
        for hit in drift:
            print(f"      {hit.get('relative')}: {hit.get('detail')}")
    if errors:
        print("  VERIFY FAILED:   checker errors:")
        for problem in errors:
            print(f"      {problem.get('code')}: {problem.get('detail')}")

    if tier1:
        return 4
    if drift:
        return 5
    if errors:
        return 3
    print("  model-slugs:     OK (tier1=0, autogen-drift=0)")
    return 0


#: Versioned model *names* in prose. The live slug checker treats these as warnings
#: and leaves the exit code alone, which is right for a product repo whose CHANGELOG
#: legitimately records which snapshot shipped when. It is wrong for this package:
#: every such name is a dated claim that reads as current instruction, and the
#: package's whole model-identity design is class-based for exactly that reason.
#: Here they are a hard failure, so a cleanup stays clean instead of decaying.
#:
#: Tool versions are deliberately not matched -- "Codex CLI 0.146.0" and "pwsh 7.5.4"
#: are reproducibility facts about a host, not routing decisions.
#:
#: Three things this pattern got wrong, each found by a name that shipped past it:
#:
#: * ``Fable`` was absent from the family list, so "Fable 5 for very-large single-shot
#:   architecture tasks" read as live routing instruction and ``--verify`` said OK. A
#:   family list is only as good as its completeness, so the tiers now live in one
#:   named constant rather than inline in the alternation.
#: * The separator was ``\s*``, so ``Opus-4.8`` -- a hyphen, the spelling a tokenizer
#:   note naturally uses -- slipped through while ``Opus 4.8`` was caught. Same claim,
#:   same decay, one character apart.
#: * A *bare* tier name with no version was unmatched, and that is the most durable
#:   form of the defect: "TDD Implementation Workflow (Opus Agent)" pins a vendor
#:   family as a role for as long as the file exists, and unlike a versioned name it
#:   never even looks stale. Bare names are matched case-SENSITIVELY, because every one
#:   of these four names is also an ordinary English noun and a case-insensitive bare
#:   match would sweep up prose that has nothing to do with routing. And only the Claude
#:   tiers get a bare match -- a bare "Gemini" or "ChatGPT" is a portal an author sends a
#:   human to (see ``inspiration-research.md``), not a model this package routes work to.
CLAUDE_TIERS = ("Opus", "Sonnet", "Haiku", "Fable")

#: The lowercase homographs, built from the tuple above rather than written out. Two
#: reasons, and the second is why it is here and not inline in the selftest: a literal
#: lowercase tier name in this file is itself a tier-1 slug, so spelling the fixture out
#: would make ``--verify`` fail on the gate that exists to keep it passing; and deriving
#: it means adding a tier to ``CLAUDE_TIERS`` automatically extends the false-positive
#: arm to cover it, instead of leaving the new name's homograph untested.
_TIER_HOMOGRAPHS = " ".join(tier.lower() for tier in CLAUDE_TIERS)

PROSE_MODEL_NAME = re.compile(
    r"\b(?:"
    r"(?:Claude[-\s]+)?(?:" + "|".join(CLAUDE_TIERS) + r")[-\s]*\d[\d.]*"
    r"|GPT[-\s]?\d[\w.-]*"
    r"|Gemini[-\s]*\d[\d.]*"
    r"|Grok[-\s]*\d[\d.]*"
    r")",
    re.IGNORECASE,
)

#: The bare-tier gate, kept separate from ``PROSE_MODEL_NAME`` because it is the one
#: rule that must NOT be case-insensitive. Merging them into a single pattern would
#: force one flag choice on both and reintroduce whichever gap the loser leaves.
PROSE_BARE_TIER = re.compile(r"\b(?:" + "|".join(CLAUDE_TIERS) + r")\b")

#: Files whose *whole content* is a dated record rather than live instruction: a
#: transcript of a past review, a maintainer's scrub log, an archive of a practice
#: that is now prohibited. Erasing the names there would destroy the record and the
#: explanation of why this package went class-based. Keep this list short; each
#: entry is a file the gate does not protect.
PROSE_NAME_ALLOWLIST = {
    "core/MANIFEST.md",
    "UPDATE-CHECKLIST.md",
    "core/.agent/docs/claude-cli-fallback-lessons.md",
    "examples/example-multi-round-independent-review.md",
}

#: A same-line marker that the name is being reported, not prescribed. Same-line
#: only, deliberately: a dated note carries its own marker, whereas a window would
#: let one "historical" heading launder every live instruction under it.
#:
#: Note what is NOT here: "currently". "Currently Opus N" is the exact failure mode
#: this gate exists for -- a live claim with a decay date and no owner.
HISTORICAL_MARKER = re.compile(
    r"historical|was named|as it was|at the time|superseded|no longer"
    r"|deprecated|PROHIBITED|archiv|~~",
    re.IGNORECASE,
)


def verify_prose_model_names(root: Path) -> int:
    """Fail on versioned model names in packaged instruction text (Gate 2)."""
    hits: list[tuple[str, int, str]] = []
    marked = 0
    for path in sorted(root.rglob("*.md")):
        if "__pycache__" in path.parts or ".git" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in PROSE_NAME_ALLOWLIST:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, line in enumerate(lines, start=1):
            found = list(PROSE_MODEL_NAME.finditer(line))
            # Bare tiers are searched only where a versioned name did not already
            # match, so "Claude Opus 5" is reported once as the name it is rather
            # than twice -- once whole and once as its own substring.
            spans = [m.span() for m in found]
            for bare in PROSE_BARE_TIER.finditer(line):
                if not any(s <= bare.start() < e for s, e in spans):
                    found.append(bare)
            if not found:
                continue
            if HISTORICAL_MARKER.search(line):
                marked += len(found)
                continue
            for match in found:
                hits.append((rel, line_no, match.group(0)))

    if hits:
        print(f"  VERIFY FAILED:   prose model name (tier-1): {len(hits)} hit(s):")
        for rel, line_no, text in hits:
            print(f"      {rel}:{line_no}  {text}")
        return 6
    print(f"  prose-names:     OK (0 live, {marked} marked historical)")
    return 0


def selftest_prose_model_names() -> int:
    """Prove Gate 2 can fail, and that it discriminates (V4/V5).

    Runs the real ``verify_prose_model_names`` against a throwaway tree rather than
    against a fixture string, so the arms exercise the same walk, the same allowlist
    and the same marker logic the package is gated by.
    """
    import contextlib
    import io
    import tempfile

    arms = [
        # (label, relative file, content, expect_failure)
        (
            "live-name-fails",
            "core/AGENTS.md",
            "Dispatch review to Codex GPT-5.6-sol at high effort.\n",
            True,
        ),
        (
            "marked-historical-passes",
            "core/AGENTS.md",
            "Historical: the reviewer was named GPT-5.6-sol at the time.\n",
            False,
        ),
        (
            "allowlisted-file-passes",
            "core/MANIFEST.md",
            "Dispatch review to Codex GPT-5.6-sol at high effort.\n",
            False,
        ),
        (
            "currently-is-not-a-marker",
            "core/AGENTS.md",
            "The reviewer is currently GPT-5.6-sol.\n",
            True,
        ),
        (
            "tool-version-is-not-a-model",
            "core/AGENTS.md",
            "Requires Codex CLI 0.146.0 and pwsh 7.5.4.\n",
            False,
        ),
        # The three spellings that shipped past this gate. Each is a separate arm
        # because each escaped for a different reason, and a single combined fixture
        # would go green again the moment one of the three regressed.
        (
            "fable-family-is-a-model",
            "core/AGENTS.md",
            "Use Fable 5 for very-large single-shot architecture tasks.\n",
            True,
        ),
        (
            "hyphenated-version-is-a-model",
            "core/AGENTS.md",
            "The Opus-4.8 tokenizer inflates ~20%.\n",
            True,
        ),
        # The separator clause on its own. The arm above cannot test it: `Opus-4.8`
        # is also a bare tier, so it stays flagged even with the separator broken --
        # the arm would pass for the wrong reason (V3). A non-Claude family has no
        # bare-tier backstop, so this one fails if and only if the separator is wrong.
        (
            "hyphenated-non-claude-version-is-a-model",
            "core/AGENTS.md",
            "Second opinion from Gemini-3 Pro.\n",
            True,
        ),
        (
            "bare-tier-as-a-role-is-a-model",
            "core/AGENTS.md",
            "# TDD Implementation Workflow (Opus Agent)\n",
            True,
        ),
        # ...and the directions a broader pattern could over-reach in. Without these
        # the gate could be "fixed" by matching everything, which is not a gate.
        (
            "lowercase-homographs-are-not-models",
            "core/AGENTS.md",
            f"Ordinary nouns, not routing decisions: {_TIER_HOMOGRAPHS}.\n",
            False,
        ),
        (
            "bare-portal-name-is-not-a-model",
            "core/AGENTS.md",
            "Paste the prompt into Gemini or ChatGPT and save the report.\n",
            False,
        ),
        (
            "capability-class-passes",
            "core/AGENTS.md",
            "Route to `architecture_single_shot`; review with `independent_reviewer`.\n",
            False,
        ),
    ]

    failures = 0
    for label, rel, content, expect_failure in arms:
        with tempfile.TemporaryDirectory(prefix="prose-selftest-") as tmp:
            target = Path(tmp) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = verify_prose_model_names(Path(tmp))
            failed = code != 0
            if failed == expect_failure:
                verdict = "flagged" if failed else "not flagged"
                print(f"PASS {label:<28} correctly {verdict}")
            else:
                print(
                    f"FAIL {label:<28} expected "
                    f"{'a failure' if expect_failure else 'no failure'}, got exit {code}"
                )
                failures += 1

    print(f"\nRESULT: {len(arms)} arm(s), {failures} failure(s)")
    return 6 if failures else 0


def verify_references(root: Path) -> int:
    """Run the reference-integrity gate as part of --verify (Gate 1).

    Imported rather than shelled out so a missing/broken refcheck.py is an import
    error here, not a silently skipped check.
    """
    try:
        import refcheck
    except ImportError as exc:
        print(f"  VERIFY FAILED:   refcheck unavailable: {exc}")
        return 7
    code, failures = refcheck.run_refcheck(refcheck.all_markdown(), report=False)
    if code:
        print(f"  VERIFY FAILED:   reference integrity: {len(failures)} failure(s):")
        for line in failures:
            print(f"      {line}")
        return 7
    print("  references:      OK (0 dangling)")
    return 0


def verify_tool_commands(root: Path) -> int:
    """Every ``tools/<name>`` a doc tells the reader to RUN is shipped or classified.

    Its own exit code (``8``) rather than reuse of ``7``: this gate catches what the
    reference gate structurally cannot see -- a tool path buried inside a command,
    which is how five absent tools shipped while refcheck reported 0 unresolved.
    Collapsing the two codes would hide which of them a red build came from.
    """
    try:
        import refcheck
    except ImportError as exc:
        print(f"  VERIFY FAILED:   refcheck unavailable: {exc}")
        return 8
    code, failures = refcheck.run_toolcheck(refcheck.all_markdown(), report=False)
    if code:
        print(f"  VERIFY FAILED:   tool commands: {len(failures)} failure(s):")
        for line in failures:
            print(f"      {line}")
        return 8
    print("  tool commands:   OK (every tools/ path shipped or classified)")
    return 0


def run(dry_run: bool, verify: bool) -> int:
    root = package_root()
    total_files = 0
    total_repl = 0
    changed_files = 0
    leaked: list[tuple[str, int]] = []

    for path in iter_text_files(root):
        total_files += 1
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"  skip (non-utf8): {path.relative_to(root)}")
            continue

        new_text, n = ph.apply_forward(original)
        rel = path.relative_to(root).as_posix()

        if n:
            changed_files += 1
            total_repl += n
            print(f"  {n:>4}  {rel}")
            if not dry_run:
                path.write_text(new_text, encoding="utf-8", newline="")

        if verify:
            check_text = new_text if not dry_run else original
            leftover = ph.remaining_source_hits(check_text)
            if leftover:
                leaked.append((rel, leftover))

    mode = "DRY-RUN (no files written)" if dry_run else "APPLIED"
    print("\n" + "=" * 60)
    print(f"  mode:            {mode}")
    print(f"  files scanned:   {total_files}")
    print(f"  files changed:   {changed_files}")
    print(f"  replacements:    {total_repl}")

    if verify:
        if leaked:
            print(
                f"  VERIFY FAILED:   {len(leaked)} file(s) still contain the raw slug:"
            )
            for rel, cnt in leaked:
                print(f"      {cnt:>4}  {rel}")
        else:
            print("  verify:          OK (0 raw slugs remain)")
        # Every gate runs even after one fails: a --verify that stopped at the first
        # failure would make each fix cost a full round-trip to discover the next.
        checker_code = verify_model_slugs(root)
        prose_code = verify_prose_model_names(root)
        ref_code = verify_references(root)
        tool_code = verify_tool_commands(root)
        print("=" * 60)
        if leaked:
            return 2
        return checker_code or prose_code or ref_code or tool_code
    print("=" * 60)
    return 0


def main() -> int:
    doc = __doc__ or ""
    parser = argparse.ArgumentParser(description=doc.splitlines()[0] if doc else "")
    parser.add_argument(
        "--dry-run", action="store_true", help="report changes without writing files"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="assert no raw source slug remains and no model slug in the "
        "package (exit 2 source leak, 3 registry unreachable, 4 tier-1 "
        "slug, 5 autogen_drift, 6 prose model name, 7 dangling reference, "
        "8 unclassified tools/ command)",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="prove the prose-model-name gate can fail and that it discriminates",
    )
    args = parser.parse_args()
    if args.selftest:
        return selftest_prose_model_names()
    return run(dry_run=args.dry_run, verify=args.verify)


if __name__ == "__main__":
    raise SystemExit(main())
