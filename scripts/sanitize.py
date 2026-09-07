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
checker is located via the S2 order (``AGENT_MODEL_REGISTRY`` → ``P:/.agent`` →
``%USERPROFILE%/.agent``). An unreachable registry is a named failure
(``registry_not_found``), never a silent pass. AUTOGEN drift is reported
separately from a tier-1 slug: both fail ``--verify``, but they are not the
same defect.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
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
    homes.append(Path("P:/.agent"))
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
    raise RegistryUnavailable(
        "registry_not_found: no live check_model_slugs.py in the S2 locate order"
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
        checker_code = verify_model_slugs(root)
        print("=" * 60)
        if leaked:
            return 2
        return checker_code
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
        "slug, 5 autogen_drift)",
    )
    args = parser.parse_args()
    return run(dry_run=args.dry_run, verify=args.verify)


if __name__ == "__main__":
    raise SystemExit(main())
