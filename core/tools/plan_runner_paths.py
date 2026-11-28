"""Refuse a plan that runs a script from the receipts folder of another plan.

Usage::

    python tools/plan_runner_paths.py --receipts-root <root> --plan-dir <dir>

The tool reads ``task.md``, ``implementation-plan.md`` and each ``.md``, ``.sh``,
``.ps1``, ``.psm1`` and ``.py`` file under ``<dir>/artifacts/``.

A *runner path* is a path under ``<root>`` that ends in ``.ps1``, ``.psm1``, ``.sh``,
``.py``, ``.bat`` or ``.cmd``, or that has a path part that starts with ``repin``. A
runner path outside ``<root>/<plan slug>/`` is *foreign*. The plan slug is the name of
``<dir>``. ``RECEIPTS/`` stands for the plan's own folder.

Variables resolve from the forms ``$x='...'``, ``$x="..."`` and ``x=...``. Names match
without regard to case. The values are substituted again until no value changes. The
``.md`` files share one scope, so a value in ``implementation-plan.md`` resolves a use in
``task.md``. Each script file under ``artifacts/`` is a scope of its own. A name that a
scope assigns takes only the values of that scope; a name that it does not assign takes
the values of all the files. A line that assigns a name before its first use of the name
on that line uses only the values of that line; the ``$x`` target of ``$x='...'`` is not a
use, and a use in the value of the assignment reads the earlier value. A use of a name expands to each resolved
value of the name; the use is refused when one expanded path is a foreign runner path. A
name with no value stays as it is, so its use gives no refusal. A path whose plan folder part still holds a ``$`` after
the expansion (a name with no value, or ``$?`` or ``$1``) gives no refusal for the same
reason. Backslashes become ``/``; the root and the plan folder compare without regard
to case. The quoted and unquoted parts of one shell word, and the parts that a ``+``
joins, are checked as one path, so ``"$x"/run.py`` and ``$x + '/run.ps1'`` are checked.
``Join-Path`` of two parts (by position, or with ``-Path`` and ``-ChildPath``) is checked
as one path too.

Output: one ``runner_foreign:<file>:<line>:<path>`` line for each refusal and exit 1,
or ``runner_paths_ok files=<n>`` and exit 0. A bad invocation prints
``runner_paths_bad:<reason>`` and exits 2.
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

RUNNER_EXTS = (".ps1", ".psm1", ".sh", ".py", ".bat", ".cmd")
ARTIFACT_EXTS = frozenset({".md", ".sh", ".ps1", ".psm1", ".py"})
TOP_FILES = ("task.md", "implementation-plan.md")
OWN_MARK = "RECEIPTS/"
#: The most expanded forms of one token; more forms are cut in sorted order.
MAX_FORMS = 512
#: The most substitution passes over the variable table.
MAX_PASSES = 16

_PS_ASSIGN = re.compile(r"\$([A-Za-z_]\w*)\s*=\s*(?:'([^']*)'|\"([^\"]*)\")")
_SH_ASSIGN = re.compile(
    r"(?:^|(?<=[\s;(`&|{]))([A-Za-z_]\w*)=(?:'([^']*)'|\"([^\"]*)\"|([^\s;|&`'\")]+))"
)
_BRACED = re.compile(r"\$\{([A-Za-z_]\w*)\}")
_USE = re.compile(r"\$([A-Za-z_]\w*)")
_TOKEN_SPLIT = re.compile(r"[\s`;|<>(),=\[\]]+")
_QUOTES = re.compile(r"[\"']")
#: A ``+`` between two quoted or variable parts (``$x + '/run.ps1'``).
_CONCAT = re.compile(r"(?<=[\"'\w}])\s*\+\s*(?=[\"'$])")
#: One ``Join-Path`` part: a quoted text or a word with no space, quote or parenthesis.
_JOIN_ARG = r"(?!-)(\"[^\"]*\"|'[^']*'|[^\s()\"';|`]+)"
#: ``Join-Path <parent> <child>``, also with ``-Path`` and ``-ChildPath``.
_JOIN = re.compile(
    r"\bJoin-Path\s+(?:-Path\s+)?" + _JOIN_ARG + r"\s+(?:-ChildPath\s+)?" + _JOIN_ARG,
    re.IGNORECASE,
)
#: ``Join-Path -ChildPath <child> -Path <parent>``.
_JOIN_NAMED_REV = re.compile(
    r"\bJoin-Path\s+-ChildPath\s+" + _JOIN_ARG + r"\s+-Path\s+" + _JOIN_ARG,
    re.IGNORECASE,
)
_TRAIL = ".:,"


class BadInvocation(Exception):
    """A bad command line or plan folder; the message is the reason."""


class _Parser(argparse.ArgumentParser):
    """An argument parser that raises :class:`BadInvocation` instead of exiting."""

    def error(self, message: str) -> NoReturn:
        raise BadInvocation(message.replace(" ", "_"))


@dataclass(frozen=True)
class Refusal:
    """One foreign runner path at a file line."""

    file: str
    line: int
    path: str

    def render(self) -> str:
        """Return the output line of the refusal."""
        return f"runner_foreign:{self.file}:{self.line}:{self.path}"


def normalize(text: str) -> str:
    """Return ``text`` with ``\\`` as ``/`` and ``${x}`` as ``$x``."""
    return _BRACED.sub(r"$\1", text.replace("\\", "/"))


def plan_files(plan_dir: Path) -> list[Path]:
    """Return the files that the check reads, in a stable order.

    Raises:
        BadInvocation: the folder is missing or has no ``task.md``.
    """
    if not plan_dir.is_dir():
        raise BadInvocation("plan_dir_missing")
    if not (plan_dir / "task.md").is_file():
        raise BadInvocation("no_task_md")
    files = [plan_dir / name for name in TOP_FILES if (plan_dir / name).is_file()]
    artifacts = plan_dir / "artifacts"
    if artifacts.is_dir():
        files.extend(
            sorted(
                p
                for p in artifacts.rglob("*")
                if p.is_file() and p.suffix.lower() in ARTIFACT_EXTS
            )
        )
    return files


def read_lines(path: Path) -> list[str]:
    """Return the lines of ``path``, decoded as UTF-8 with replacement."""
    return path.read_bytes().decode("utf-8", "replace").splitlines()


@dataclass(frozen=True)
class Assignment:
    """One assignment on a line: the name (lower case), its span and its raw value.

    ``target`` is the start of the ``$name`` target of a PowerShell assignment, or -1
    for the ``name=`` form, whose target holds no ``$``.
    """

    name: str
    start: int
    end: int
    target: int
    value: str


def line_assignments(line: str) -> list[Assignment]:
    """Return each assignment of ``line``."""
    found: list[Assignment] = []
    for match in _PS_ASSIGN.finditer(line):
        value = match.group(2) if match.group(2) is not None else match.group(3)
        found.append(
            Assignment(
                match.group(1).lower(),
                match.start(),
                match.end(),
                match.start(),
                value or "",
            )
        )
    for match in _SH_ASSIGN.finditer(line):
        value = next((g for g in match.group(2, 3, 4) if g is not None), "")
        found.append(
            Assignment(match.group(1).lower(), match.start(), match.end(), -1, value)
        )
    return found


def collect_assignments(texts: Iterable[list[str]]) -> dict[str, set[str]]:
    """Return each variable name (lower case) with its set of raw values."""
    table: dict[str, set[str]] = {}
    for lines in texts:
        for raw in lines:
            for found in line_assignments(normalize(raw)):
                table.setdefault(found.name, set()).add(found.value)
    return table


def line_bindings(line: str) -> dict[str, set[str]]:
    """Return the raw values of each name that ``line`` assigns before its first use.

    An assignment takes effect at its end. The ``$name`` target of a PowerShell
    assignment is not a use. A use in the value of the first assignment of the name
    reads the earlier value, so that name takes no line value.
    """
    assigned = line_assignments(line)
    targets = {found.target for found in assigned if found.target >= 0}
    takes_effect: dict[str, int] = {}
    values: dict[str, set[str]] = {}
    for found in sorted(assigned, key=lambda a: a.start):
        takes_effect.setdefault(found.name, found.end)
        values.setdefault(found.name, set()).add(found.value)
    first_use: dict[str, int] = {}
    for match in _USE.finditer(line):
        if match.start() not in targets:
            first_use.setdefault(match.group(1).lower(), match.start())
    return {
        name: vals
        for name, vals in values.items()
        if first_use.get(name, len(line)) >= takes_effect[name]
    }


def expand(text: str, table: dict[str, set[str]]) -> list[str]:
    """Return each form of ``text`` with each known name replaced by each of its values."""
    names = [m.group(1).lower() for m in _USE.finditer(text)]
    known = sorted({n for n in names if table.get(n)})
    if not known:
        return [text]
    choices = [sorted(table[n]) for n in known]
    forms: list[str] = []
    for combo in itertools.islice(itertools.product(*choices), MAX_FORMS):
        values = dict(zip(known, combo, strict=True))

        def sub(match: re.Match[str], values: dict[str, str] = values) -> str:
            return values.get(match.group(1).lower(), match.group(0))

        forms.append(_USE.sub(sub, text))
    return sorted(set(forms))


def resolve(table: dict[str, set[str]]) -> dict[str, set[str]]:
    """Substitute the values into each other until no value changes."""
    current = {k: set(v) for k, v in table.items()}
    for _ in range(MAX_PASSES):
        changed = False
        nxt: dict[str, set[str]] = {}
        for name, values in current.items():
            others = {k: v for k, v in current.items() if k != name}
            out: set[str] = set()
            for value in values:
                out.update(expand(value, others))
            if len(out) > MAX_FORMS:
                out = set(sorted(out)[:MAX_FORMS])
            nxt[name] = out
            changed = changed or out != values
        current = nxt
        if not changed:
            break
    return current


def overlay(
    base: dict[str, set[str]], local: dict[str, set[str]]
) -> dict[str, set[str]]:
    """Return ``base`` with each name of ``local`` set to its own resolved values.

    ``base`` is already resolved. A name of ``local`` hides its values in ``base``; the
    other names of ``local`` and of ``base`` resolve it.
    """
    if not local:
        return base
    outer = {k: v for k, v in base.items() if k not in local}
    current = {k: set(v) for k, v in local.items()}
    for _ in range(MAX_PASSES):
        changed = False
        nxt: dict[str, set[str]] = {}
        for name, values in current.items():
            others = {**outer, **{k: v for k, v in current.items() if k != name}}
            out: set[str] = set()
            for value in values:
                out.update(expand(value, others))
            if len(out) > MAX_FORMS:
                out = set(sorted(out)[:MAX_FORMS])
            nxt[name] = out
            changed = changed or out != values
        current = nxt
        if not changed:
            break
    return {**outer, **current}


def scope_tables(
    files: Sequence[Path], texts: Sequence[list[str]]
) -> list[dict[str, set[str]]]:
    """Return the resolved variable table of each file.

    The ``.md`` files share one scope; each other file is a scope of its own.
    """
    base = resolve(collect_assignments(texts))
    docs = [t for p, t in zip(files, texts, strict=True) if p.suffix.lower() == ".md"]
    doc_table = overlay(base, collect_assignments(docs))
    tables: list[dict[str, set[str]]] = []
    for path, lines in zip(files, texts, strict=True):
        if path.suffix.lower() == ".md":
            tables.append(doc_table)
        else:
            tables.append(overlay(base, collect_assignments([lines])))
    return tables


def _joined(parent: str, child: str) -> str:
    """Return the two ``Join-Path`` parts as one path, without their quotes."""
    return (
        _QUOTES.sub("", parent).rstrip("/") + "/" + _QUOTES.sub("", child).lstrip("/")
    )


def join_paths(line: str) -> str:
    """Return ``line`` with each ``Join-Path`` of two parts written as one path."""
    line = _JOIN_NAMED_REV.sub(lambda m: _joined(m.group(2), m.group(1)), line)
    return _JOIN.sub(lambda m: _joined(m.group(1), m.group(2)), line)


def words(line: str) -> Iterator[str]:
    """Yield the words of ``line``; the quoted parts of one word are joined."""
    for token in _TOKEN_SPLIT.split(_CONCAT.sub("", join_paths(line))):
        word = _QUOTES.sub("", token)
        if word:
            yield word


class Classifier:
    """Decide whether a path is a foreign runner path."""

    def __init__(self, root: str, slug: str) -> None:
        self.root = normalize(root).rstrip("/")
        self._root_lower = self.root.lower() + "/"
        self._slug_lower = slug.lower()
        self._find = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(self._root_lower), re.IGNORECASE
        )

    def foreign_paths(self, token: str) -> Iterator[str]:
        """Yield each foreign runner path that starts inside ``token``."""
        for match in self._find.finditer(token):
            path = token[match.start() :].rstrip(_TRAIL)
            if self.is_foreign_runner(path):
                yield path

    def is_foreign_runner(self, path: str) -> bool:
        """Return True when ``path`` is a runner path outside the plan's own folder."""
        if not path.lower().startswith(self._root_lower):
            return False
        rel = path[len(self._root_lower) :]
        parts = [p for p in rel.split("/") if p]
        if not parts or parts[0].lower() == self._slug_lower:
            return False
        if "$" in parts[0]:
            # The plan folder holds a name with no value (also ``$?`` or ``$1``).
            return False
        last = parts[-1].lower()
        if last.endswith(RUNNER_EXTS):
            return True
        return any(p.lower().startswith("repin") for p in parts)


def scan(
    plan_dir: Path, files: Sequence[Path], texts: Sequence[list[str]], root: str
) -> list[Refusal]:
    """Return the refusals of the plan, in file and line order."""
    rules = Classifier(root, plan_dir.name)
    refusals: list[Refusal] = []
    tables = scope_tables(files, texts)
    for path, lines, scope in zip(files, texts, tables, strict=True):
        rel = path.relative_to(plan_dir).as_posix()
        for number, raw in enumerate(lines, start=1):
            line = normalize(raw)
            table = overlay(scope, line_bindings(line))
            seen: set[str] = set()
            for token in words(line):
                if token.startswith(OWN_MARK):
                    continue
                for form in expand(token, table):
                    for hit in rules.foreign_paths(form):
                        if hit not in seen:
                            seen.add(hit)
                            refusals.append(Refusal(rel, number, hit))
    return refusals


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse the command line.

    Raises:
        BadInvocation: an argument is missing or unknown.
    """
    parser = _Parser(prog="plan_runner_paths.py", add_help=False)
    parser.add_argument("--receipts-root")
    parser.add_argument("--plan-dir")
    args = parser.parse_args(list(argv))
    if not args.receipts_root:
        raise BadInvocation("no_receipts_root")
    if not args.plan_dir:
        raise BadInvocation("no_plan_dir")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check; return the exit code."""
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        plan_dir = Path(args.plan_dir).resolve()
        files = plan_files(plan_dir)
        texts = [read_lines(p) for p in files]
    except BadInvocation as exc:
        print(f"runner_paths_bad:{exc}")
        return 2
    except OSError as exc:
        print(f"runner_paths_bad:read_error:{type(exc).__name__}")
        return 2
    refusals = scan(plan_dir, files, texts, args.receipts_root)
    for refusal in refusals:
        print(refusal.render())
    if refusals:
        return 1
    print(f"runner_paths_ok files={len(files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
