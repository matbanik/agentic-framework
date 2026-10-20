#!/usr/bin/env python3
"""Fail when a durable file cites the receipts folder more often than its baseline.

The P0 redirect pattern writes command output under the receipts folder
(``RECEIPTS_DIR``). The repository does not keep that folder, so a durable file that
cites a path inside it points a later reader at nothing. Evidence is pasted into the
artifact instead; a receipts path may appear only inside the command that produced the
output.

The receipts folder is every root ``durable_evidence.configured_roots`` names (the
``RECEIPTS_DIR`` environment value, else the installed root), in any slash direction,
and in any letter case when the root is a Windows path. The literal
``{{RECEIPTS_DIR}}`` slot also counts: a template that was copied without filling the
slot cites the folder just as much as a filled one does.

Classification:

* **Markup files** (``.md``, ``.yaml``, ``.yml``, ``.json``): a receipts path outside
  every fenced block and every inline code span is a finding. An inline span whose
  stripped content is one receipts-path token (it matches from its first character and
  has no whitespace) is also a finding. A span holding a command, and everything inside
  a fence, is exempt. Fences are backtick or tilde runs of three or more; the closing
  run uses the same character and is at least as long. Leading indentation is ignored
  so that fences nested in list items are recognized. A span may continue across the
  lines of one paragraph (consecutive non-blank lines), as CommonMark allows; a
  heading, a table row, a list item or a block-quote line starts a new paragraph.
* **Product source** (the ``PRODUCT_PREFIXES`` an adopter lists): every occurrence
  counts. The framework ships the list empty.

Accepted imprecision: a citation inside a ``text`` or ``diff`` fence, or written as a
``#`` comment inside a shell fence, is not counted.

The file set is ``git ls-files -co --exclude-standard``, so tracked files and untracked
files that are not ignored are scanned. ``tools/``, ``scripts/`` and ``tests/`` are
never scanned.

``--paths FILE [FILE ...]`` replaces that file set with the named files and does not
list the tree: the pre-commit hook passes the staged files and the closeout stages pass
their artifacts, so a draft another session left in the tree cannot fail either. A
relative path is taken from ``--root``. A file under the root is keyed by its
root-relative POSIX path, like the whole-tree mode; a file outside it is keyed by its
absolute POSIX path and so has no baseline. Paths the classification excludes and paths
that are not files are skipped. Lines are sorted by key.

Ratchet: ``tools/temp_citation_baseline.json`` maps repo-relative POSIX paths to finding
counts. A file fails when its count is above its baseline, or above 0 when it has no
key. A key whose file is missing is tolerated. ``--write-baseline`` records the current
non-zero counts, sorted by path.

Exit codes: 0 pass, 1 a file is above its baseline, 2 the baseline or ``git`` failed,
or ``--paths`` was combined with ``--write-baseline``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

if __package__ == "tools":
    from tools.durable_evidence import configured_roots
else:
    from durable_evidence import configured_roots

REPO_ROOT = Path(__file__).resolve().parent.parent

BASELINE_REL = "tools/temp_citation_baseline.json"

#: The unfilled template slot for the receipts folder.
RECEIPTS_SLOT = "{{RECEIPTS_DIR}}"

MARKUP_SUFFIXES = frozenset({".md", ".yaml", ".yml", ".json"})

EXCLUDED_PREFIXES = ("tools/", "scripts/", "tests/")

#: Product source directories, where every occurrence counts. Adopters list theirs.
PRODUCT_PREFIXES: tuple[str, ...] = ()

_FENCE_OPEN_RE = re.compile(r"^[ \t]*(?P<run>`{3,}|~{3,})(?P<rest>.*)$")

#: A line that stands alone: an ATX heading or a table row. A span never crosses it.
_SINGLE_LINE_BLOCK_RE = re.compile(r"^ {0,3}(?:#{1,6}(?:[ \t]|$)|\|)")

#: A line that starts a new paragraph: a list item or a block-quote line.
_BLOCK_START_RE = re.compile(r"^[ \t]*(?:[-*+](?:[ \t]|$)|\d{1,9}[.)](?:[ \t]|$)|>)")


def _root_pattern(root: str) -> str:
    """One configured root as a regex: any slash run between its parts.

    A Windows root (drive letter or UNC) matches in any letter case, as the file system
    does; a POSIX root matches its exact case.
    """
    parts = [re.escape(part) for part in re.split(r"[/\\]+", root.rstrip("/\\")) if part]
    body = r"[/\\]+".join(parts)
    if root.startswith(("/", "\\")) and not root.startswith("\\\\"):
        body = r"[/\\]+" + body
    windows = bool(re.match(r"^[A-Za-z]:|^\\\\", root))
    return f"(?i:{body})" if windows else body


def scratch_path_re(roots: Iterable[str] | None = None) -> re.Pattern[str]:
    """The receipts-folder pattern for ``roots`` (default: the configured roots).

    Roots that still hold a template slot are skipped, as ``scratch_reference`` skips
    them; the literal ``{{RECEIPTS_DIR}}`` slot is always part of the pattern.
    """
    chosen = configured_roots() if roots is None else tuple(roots)
    alternatives = [
        _root_pattern(root) for root in chosen if root and "{{" not in root
    ]
    alternatives.append(re.escape(RECEIPTS_SLOT))
    return re.compile("|".join(f"(?:{alt})" for alt in alternatives))


def _closes_fence(line: str, run: str) -> bool:
    """Return whether ``line`` closes a fence opened by ``run``.

    The closing run uses the opener's character, is at least as long, and is followed
    only by whitespace.
    """
    stripped = line.strip()
    char = run[0]
    length = len(stripped) - len(stripped.lstrip(char))
    return length >= len(run) and stripped == char * length


def _opens_fence(line: str) -> str | None:
    """Return the opening run when ``line`` opens a fence, else ``None``.

    A backtick opener whose info string holds a backtick is an inline span, not a fence.
    """
    match = _FENCE_OPEN_RE.match(line)
    if match is None:
        return None
    run = match.group("run")
    if run[0] == "`" and "`" in match.group("rest"):
        return None
    return run


def _is_scratch_token(content: str, pattern: re.Pattern[str]) -> bool:
    """Return whether a code span's stripped content is one receipts-path token."""
    stripped = content.strip()
    if not stripped or any(char.isspace() for char in stripped):
        return False
    return pattern.match(stripped) is not None


def _run_length(line: str, start: int) -> int:
    """Return the length of the backtick run that starts at ``line[start]``."""
    end = start
    while end < len(line) and line[end] == "`":
        end += 1
    return end - start


def _closing_span(line: str, start: int, length: int) -> int:
    """Return the index of a backtick run of exactly ``length`` at or after ``start``.

    Returns -1 when the span is never closed on this line.
    """
    index = start
    while index < len(line):
        if line[index] != "`":
            index += 1
            continue
        run = _run_length(line, index)
        if run == length:
            return index
        index += run
    return -1


def _scan_markup_line(line: str, pattern: re.Pattern[str]) -> int:
    """Count findings in one paragraph (one or more lines) outside every fence."""
    findings = 0
    prose: list[str] = []
    index = 0
    while index < len(line):
        if line[index] != "`":
            next_tick = line.find("`", index)
            stop = len(line) if next_tick < 0 else next_tick
            prose.append(line[index:stop])
            index = stop
            continue
        length = _run_length(line, index)
        close = _closing_span(line, index + length, length)
        if close < 0:
            # An unmatched run is literal text (CommonMark), so what follows is prose.
            prose.append(line[index : index + length])
            index += length
            continue
        if _is_scratch_token(line[index + length : close], pattern):
            findings += 1
        prose.append(" ")
        index = close + length
    return findings + len(pattern.findall("".join(prose)))


def scan_text(
    text: str, *, product_source: bool, pattern: re.Pattern[str] | None = None
) -> int:
    """Return the number of receipts-folder citations in ``text``.

    Args:
        text: File content.
        product_source: When true every occurrence counts; when false the markup rules
            in the module docstring apply.
        pattern: The receipts-folder pattern; ``scratch_path_re()`` when omitted.

    Returns:
        The finding count.

    Raises:
        TypeError: ``text`` is not a str.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a str")
    pattern = scratch_path_re() if pattern is None else pattern
    if product_source:
        return len(pattern.findall(text))
    findings = 0
    open_run: str | None = None
    paragraph: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if open_run is not None:
            if _closes_fence(line, open_run):
                open_run = None
            continue
        run = _opens_fence(line)
        if run is not None or not line.strip() or _SINGLE_LINE_BLOCK_RE.match(line):
            findings += _scan_markup_line("\n".join(paragraph), pattern)
            paragraph = []
            if run is not None:
                open_run = run
            elif line.strip():
                findings += _scan_markup_line(line, pattern)
            continue
        if _BLOCK_START_RE.match(line):
            findings += _scan_markup_line("\n".join(paragraph), pattern)
            paragraph = []
        paragraph.append(line)
    return findings + _scan_markup_line("\n".join(paragraph), pattern)


def _kind(rel: str) -> str | None:
    """Return ``"markup"``, ``"product"`` or ``None`` for a repo-relative POSIX path."""
    if rel.startswith(EXCLUDED_PREFIXES):
        return None
    if Path(rel).suffix.lower() in MARKUP_SUFFIXES:
        return "markup"
    if PRODUCT_PREFIXES and rel.startswith(PRODUCT_PREFIXES):
        return "product"
    return None


def _git_files(root: Path) -> list[str]:
    """Return tracked plus untracked non-ignored paths under ``root``."""
    proc = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed in {root}: {detail}")
    names = proc.stdout.decode("utf-8", errors="replace").split("\0")
    return sorted({name for name in names if name})


def eligible_files(root: Path) -> list[str]:
    """Return the sorted repo-relative paths the scanner reads under ``root``."""
    return [
        rel
        for rel in _git_files(root)
        if _kind(rel) is not None and (root / rel).is_file()
    ]


def current_counts(root: Path) -> dict[str, int]:
    """Return the non-zero finding count of every eligible file, sorted by path."""
    pattern = scratch_path_re()
    counts: dict[str, int] = {}
    for rel in eligible_files(root):
        text = (root / rel).read_bytes().decode("utf-8", errors="replace")
        found = scan_text(text, product_source=_kind(rel) == "product", pattern=pattern)
        if found:
            counts[rel] = found
    return counts


def _read_baseline(root: Path) -> dict[str, int]:
    """Return the committed baseline, or an empty map when the file is absent."""
    path = root / BASELINE_REL
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{BASELINE_REL} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not all(
        isinstance(key, str) and type(value) is int and value >= 0
        for key, value in data.items()
    ):
        raise ValueError(f"{BASELINE_REL} must map paths to non-negative integers")
    return data


def given_counts(root: Path, paths: Iterable[Path | str]) -> dict[str, int]:
    """Return the non-zero finding count of each given file, sorted by key.

    Args:
        root: Repository root. Relative ``paths`` are taken from it.
        paths: The files to read. The tree is not listed.

    Returns:
        A map from key to count. The key is the root-relative POSIX path for a file
        under ``root`` and the absolute POSIX path for any other file. Paths the
        classification excludes and paths that are not files are left out.

    Raises:
        ValueError: ``paths`` is one path instead of a list, or an entry is blank or
            is not a path.
    """
    if isinstance(paths, (str, Path)):
        raise ValueError(f"paths must be a list of file paths, got {paths!r}")
    pattern = scratch_path_re()
    base = Path(os.path.abspath(root))
    counts: dict[str, int] = {}
    for given in paths:
        if not isinstance(given, (str, Path)) or not str(given).strip():
            raise ValueError(f"--paths takes file paths, got {given!r}")
        path = Path(os.path.abspath(base / given))
        rel = (
            path.relative_to(base).as_posix()
            if path.is_relative_to(base)
            else path.as_posix()
        )
        if rel in counts or _kind(rel) is None or not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        counts[rel] = scan_text(
            text, product_source=_kind(rel) == "product", pattern=pattern
        )
    return {rel: counts[rel] for rel in sorted(counts) if counts[rel]}


def check(root: Path, paths: Iterable[Path | str] | None = None) -> list[str]:
    """Return one ``path: count > baseline`` line per file above its baseline.

    Args:
        root: Repository root; its baseline file is the ratchet.
        paths: When given, the only files read (see ``given_counts``). When ``None``
            the whole tree is read.

    Returns:
        The lines, sorted by path.
    """
    baseline = _read_baseline(root)
    counts = current_counts(root) if paths is None else given_counts(root, paths)
    return [
        f"{rel}: {count} > {baseline.get(rel, 0)}"
        for rel, count in counts.items()
        if count > baseline.get(rel, 0)
    ]


def write_baseline(root: Path) -> dict[str, int]:
    """Write the current non-zero counts to the baseline file and return them."""
    counts = dict(sorted(current_counts(root).items()))
    path = root / BASELINE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8", newline="\n")
    return counts


def main(argv: list[str] | None = None) -> int:
    """Run the check over the tree or over ``--paths``, or write the baseline."""
    parser = argparse.ArgumentParser(
        description="Fail when a durable file cites the receipts folder above its baseline."
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help=f"record the current non-zero counts in {BASELINE_REL}",
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        type=Path,
        metavar="FILE",
        help="check only these files and do not list the tree (relative to --root)",
    )
    args = parser.parse_args(argv)
    if args.paths is not None and args.write_baseline:
        parser.error("--paths cannot be combined with --write-baseline")
    root: Path = args.root.resolve()
    try:
        if args.write_baseline:
            counts = write_baseline(root)
            print(
                f"wrote {BASELINE_REL}: {len(counts)} files, {sum(counts.values())} findings"
            )
            return 0
        problems = check(root, paths=args.paths)
    except (RuntimeError, ValueError) as exc:
        print(f"temp citation check error: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem)
    if problems:
        print(
            f"temp citation check failed: {len(problems)} file(s) cite the receipts "
            "folder more than the baseline allows; paste the output instead of citing "
            "the path"
        )
        return 1
    print("temp citation check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
