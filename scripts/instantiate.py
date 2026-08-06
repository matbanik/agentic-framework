#!/usr/bin/env python3
"""instantiate.py -- fill the framework's placeholders with YOUR project's values.

THIS is the script an adopting agent/team runs. After copying the framework into a new
project, run it once to replace every ``{{PLACEHOLDER}}`` token with concrete values.

What it replaces
----------------
    {{PROJECT_NAME}}         your project slug, lower-case      e.g. acme
    {{PROJECT_NAME_TITLE}}   Title-case (derived unless given)  e.g. Acme
    {{PROJECT_NAME_UPPER}}   UPPER-case (derived unless given)  e.g. ACME  (used in env vars)
    {{PROJECT_ROOT}}         absolute path to the project root  e.g. /home/you/acme  or  P:\acme
    {{RECEIPTS_DIR}}         where shell output is redirected   e.g. /tmp/acme  or  C:/Temp/acme
    {{REPO_URL}}             host/owner/repo (no scheme)        e.g. github.com/you/acme

Usage
-----
Provide values via flags, or a KEY=VALUE config file, or both (flags win):

    python scripts/instantiate.py \
        --project-name acme \
        --project-root /home/you/acme \
        --receipts-dir /tmp/acme \
        --repo-url github.com/you/acme

    # or, from a config file (KEY=VALUE lines; keys are the flag names upper-cased):
    python scripts/instantiate.py --config framework.vars

Always dry-run first:

    python scripts/instantiate.py --config framework.vars --dry-run
    python scripts/instantiate.py --config framework.vars            # apply
    python scripts/instantiate.py --verify                           # assert no {{TOKENS}} left

By default the script rewrites the framework files sitting next to it (the copy inside
this package). If you copied ``core/`` into your project first, point it there:

    python scripts/instantiate.py --root /path/to/your-project --config framework.vars

Config file example (framework.vars)
------------------------------------
    PROJECT_NAME=acme
    PROJECT_ROOT=/home/you/acme
    RECEIPTS_DIR=/tmp/acme
    REPO_URL=github.com/you/acme
    # optional overrides if simple casing is wrong (e.g. an acronym):
    # PROJECT_NAME_TITLE=ACME Corp
    # PROJECT_NAME_UPPER=ACMECORP
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import placeholders as ph  # noqa: E402

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
SKIP_DIRS = {"scripts", ".git", "node_modules", "__pycache__", ".venv"}

CONFIG_KEYS = {
    "PROJECT_NAME": "project_name",
    "PROJECT_ROOT": "project_root",
    "RECEIPTS_DIR": "receipts_dir",
    "REPO_URL": "repo_url",
    "PROJECT_NAME_TITLE": "project_name_title",
    "PROJECT_NAME_UPPER": "project_name_upper",
}


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def read_config(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE file. Blank lines and #-comments ignored."""
    out: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{lineno}: expected KEY=VALUE, got: {raw!r}")
        key, _, value = line.partition("=")
        key = key.strip().upper()
        if key not in CONFIG_KEYS:
            raise ValueError(f"{path}:{lineno}: unknown key {key!r}")
        out[CONFIG_KEYS[key]] = value.strip()
    return out


def iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def verify_only(root: Path) -> int:
    """Report any files that still contain placeholder tokens."""
    token_re = re.compile("|".join(re.escape(t) for t in ph.PLACEHOLDER_TOKENS))
    offenders: list[tuple[str, int]] = []
    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits = len(token_re.findall(text))
        if hits:
            offenders.append((path.relative_to(root).as_posix(), hits))
    if offenders:
        print(f"VERIFY FAILED: {len(offenders)} file(s) still contain placeholders:")
        for rel, cnt in offenders:
            print(f"  {cnt:>4}  {rel}")
        return 2
    print("verify: OK (0 placeholder tokens remain)")
    return 0


def run(values: dict[str, str], dry_run: bool, root: Path) -> int:
    mapping = ph.derive_values(**values)

    print("Placeholder -> value:")
    for token in ph.PLACEHOLDER_TOKENS:
        print(f"  {token:<24} {mapping[token]}")
    print()

    total_files = changed_files = total_repl = 0
    for path in iter_text_files(root):
        total_files += 1
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text, n = ph.apply_reverse(original, mapping)
        if n:
            changed_files += 1
            total_repl += n
            print(f"  {n:>4}  {path.relative_to(root).as_posix()}")
            if not dry_run:
                path.write_text(new_text, encoding="utf-8", newline="")

    mode = "DRY-RUN (no files written)" if dry_run else "APPLIED"
    print("\n" + "=" * 60)
    print(f"  mode:          {mode}")
    print(f"  files scanned: {total_files}")
    print(f"  files changed: {changed_files}")
    print(f"  replacements:  {total_repl}")
    print("=" * 60)
    if not dry_run:
        print("Next: re-run with --verify to confirm no placeholders remain.")
    return 0


def main() -> int:
    doc = __doc__ or ""
    parser = argparse.ArgumentParser(
        description=doc.splitlines()[0] if doc else "",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="directory to rewrite (default: this package); "
        "point at your copied framework tree",
    )
    parser.add_argument("--config", type=Path, help="KEY=VALUE file with the values")
    parser.add_argument("--project-name")
    parser.add_argument("--project-root")
    parser.add_argument("--receipts-dir")
    parser.add_argument("--repo-url")
    parser.add_argument("--project-name-title", help="override derived Title-case")
    parser.add_argument("--project-name-upper", help="override derived UPPER-case")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="only check that no placeholder tokens remain; exit 2 if any do",
    )
    args = parser.parse_args()
    root = args.root.resolve() if args.root else package_root()

    if args.verify:
        return verify_only(root)

    values: dict[str, str] = {}
    if args.config:
        values.update(read_config(args.config))
    # CLI flags override config-file values.
    for flag, key in (
        (args.project_name, "project_name"),
        (args.project_root, "project_root"),
        (args.receipts_dir, "receipts_dir"),
        (args.repo_url, "repo_url"),
        (args.project_name_title, "project_name_title"),
        (args.project_name_upper, "project_name_upper"),
    ):
        if flag is not None:
            values[key] = flag

    required = ("project_name", "project_root", "receipts_dir", "repo_url")
    missing = [k for k in required if not values.get(k)]
    if missing:
        parser.error(
            "missing required value(s): "
            + ", ".join(missing)
            + "  (supply via --config or the matching --flag)"
        )

    try:
        return run(values, dry_run=args.dry_run, root=root)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
