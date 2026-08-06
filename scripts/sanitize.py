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
    python scripts/sanitize.py --verify       # after applying, assert zero raw slugs left

The script targets the package root (its own parent's parent) and skips the
``scripts/`` directory (so it never rewrites the substitution rules themselves) and
anything that is not a UTF-8 text file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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


def package_root() -> Path:
    """The agentic-framework/ directory (parent of this scripts/ folder)."""
    return Path(__file__).resolve().parent.parent


def iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


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
            return 2
        print("  verify:          OK (0 raw slugs remain)")
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
        help="assert no raw source slug remains (exit 2 on leak)",
    )
    args = parser.parse_args()
    return run(dry_run=args.dry_run, verify=args.verify)


if __name__ == "__main__":
    raise SystemExit(main())
