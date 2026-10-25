"""MEU-785 AC-785.26: the simplicity census of ``tools/lanes.py`` — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.26 (design D:427, §10b "Simplicity": ``lanes.py`` stays glue around the existing
journal, publisher and lease; it adds no second transaction engine).

The census reads the source of ``tools/lanes.py`` with ``ast`` and finds:

- a journal writer of its own: a definition of one of the ``commit_batch.py`` journal
  writer names (``_append``, ``_start``, ``_effect``, ``_finish``), or a store into a
  ``"journal"`` key;
- an ``update-ref`` of ``refs/heads/main``: an argv (call, list or tuple) that holds the
  literal ``update-ref`` together with ``refs/heads/main``, ``main`` or an upper-case ref
  constant that spells ``MAIN``;
- a lease kernel: an import of ``msvcrt`` or ``fcntl``, a call of ``locking``, ``flock``,
  ``lockf``, ``LockFileEx`` or ``UnlockFileEx``, or a definition of the ``os_lease`` kernel
  names (``_lease_lock``, ``_lease_unlock``).

It also requires calls into ``commit_batch``, ``os_lease`` and ``run_parameters``. The
census proves itself on synthetic sources first, so a forbidden symbol in ``tools/lanes.py``
fails it. The op-file write and the ``commit_batch`` import belong to AC-785.11
(``test_lanes_journal.py``) and are not repeated here. Do not skip, only, or early-return
(G36).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "tools" / "lanes.py"
# The commit_batch.py journal writer (commit_batch.py `_append`, `_start`, `_effect`, `_finish`).
WRITER_NAMES = frozenset({"_append", "_start", "_effect", "_finish"})
KERNEL_MODULES = frozenset({"msvcrt", "fcntl"})
KERNEL_CALLS = frozenset({"locking", "flock", "lockf", "LockFileEx", "UnlockFileEx"})
KERNEL_DEFS = frozenset({"_lease_lock", "_lease_unlock"})
MAIN_REF = "refs/heads/main"
CALLED_MODULES = ("commit_batch", "os_lease", "run_parameters")


def _module_aliases(tree: ast.AST) -> dict[str, str]:
    """Local names bound to a module or to a name imported from one: ``{local: module}``.

    ``import tools.os_lease as lease`` gives ``{"lease": "os_lease"}``;
    ``from . import commit_batch as cb`` gives ``{"cb": "commit_batch"}``;
    ``from .run_parameters import verify`` gives ``{"verify": "run_parameters"}``.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[-1]
                aliases[alias.asname or base] = base
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[-1]
            for alias in node.names:
                if module in CALLED_MODULES:
                    aliases[alias.asname or alias.name] = module
                else:
                    aliases[alias.asname or alias.name] = alias.name
    return aliases


def _called_modules(source: str) -> set[str]:
    """The modules of ``CALLED_MODULES`` that ``source`` calls into."""
    tree = ast.parse(source)
    aliases = _module_aliases(tree)
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        target: str | None = None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            target = aliases.get(func.value.id)
        elif isinstance(func, ast.Name):
            target = aliases.get(func.id)
        if target in CALLED_MODULES:
            called.add(target)
    return called


def _spells_main(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value in (MAIN_REF, "main") or node.value.endswith(f" {MAIN_REF}")
    # A ref constant (``MAIN``, ``MAIN_REF``, ``ref_guard.MAIN``), not a path such as
    # ``main_tree``: the lane ref update runs git in the main tree.
    if isinstance(node, ast.Name):
        return node.id.isupper() and "MAIN" in node.id
    if isinstance(node, ast.Attribute):
        return node.attr.isupper() and "MAIN" in node.attr
    return False


def _argv_items(node: ast.AST) -> list[ast.AST] | None:
    if isinstance(node, ast.Call):
        return [*node.args, *(keyword.value for keyword in node.keywords)]
    if isinstance(node, (ast.List, ast.Tuple)):
        return list(node.elts)
    return None


def _census(source: str) -> list[str]:
    """Every forbidden construct in ``source``, as ``<kind>:<line>:<text>``."""
    tree = ast.parse(source)
    findings: list[str] = []

    def found(kind: str, node: ast.AST) -> None:
        text = ast.get_source_segment(source, node) or ""
        line = getattr(node, "lineno", 0)
        findings.append(f"{kind}:{line}:{text.splitlines()[0] if text else ''}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in WRITER_NAMES:
                found("journal_writer", node)
            if node.name in KERNEL_DEFS:
                found("lease_kernel", node)
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            key = node.slice
            if isinstance(key, ast.Constant) and key.value == "journal":
                found("journal_writer", node)
        elif isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in KERNEL_MODULES for alias in node.names):
                found("lease_kernel", node)
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in KERNEL_MODULES:
                found("lease_kernel", node)
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            if name in KERNEL_CALLS:
                found("lease_kernel", node)
        if isinstance(node, ast.Constant) and node.value == f"update-ref {MAIN_REF}":
            found("update_ref_main", node)
        items = _argv_items(node)
        if items is None:
            continue
        has_update_ref = any(
            isinstance(item, ast.Constant) and item.value == "update-ref"
            for item in items
        )
        if has_update_ref and any(_spells_main(item) for item in items):
            found("update_ref_main", node)
    return findings


def _kinds(source: str) -> set[str]:
    return {finding.split(":", 1)[0] for finding in _census(source)}


def test_lanes_is_glue_around_the_journal_publisher_and_lease() -> None:
    # The census finds each forbidden construct on a synthetic source.
    writer = "def _start(ctx, phase):\n    ctx.record['journal'] = []\n"
    assert _kinds(writer) == {"journal_writer"}, _census(writer)
    assert len(_census(writer)) == 2, _census(writer)
    update_main = (
        "MAIN_REF = 'refs/heads/main'\n"
        "def p(git, c, parent):\n"
        "    git('update-ref', MAIN_REF, c, parent)\n"
        "    argv = ['git', 'update-ref', 'refs/heads/main', c]\n"
        "    return 'update-ref refs/heads/main'\n"
    )
    assert _kinds(update_main) == {"update_ref_main"}, _census(update_main)
    assert len(_census(update_main)) == 3, _census(update_main)
    kernel = (
        "import msvcrt\n"
        "from fcntl import flock\n"
        "def _lease_lock(fd):\n"
        "    msvcrt.locking(fd, 1, 1)\n"
        "    flock(fd, 2)\n"
    )
    assert _kinds(kernel) == {"lease_kernel"}, _census(kernel)
    assert len(_census(kernel)) == 5, _census(kernel)
    # A lane ref update, a journal read and a lease through os_lease are glue, not findings.
    glue = (
        "from . import commit_batch\n"
        "from . import os_lease\n"
        "from . import run_parameters as rp\n"
        "def g(git, main_tree, slug, c, path):\n"
        "    git(main_tree, 'update-ref', f'refs/heads/lane/{slug}', c)\n"
        "    entries = commit_batch.load(path)['journal']\n"
        "    lease = os_lease.acquire(path, wait_s=0.0, body=b'')\n"
        "    rp.verify(path)\n"
        "    return entries, lease\n"
    )
    assert _census(glue) == [], _census(glue)
    assert _called_modules(glue) == set(CALLED_MODULES)
    assert _called_modules("import json\njson.dumps({})\n") == set()

    source = LANES.read_text(encoding="utf-8")
    assert _census(source) == [], "tools/lanes.py holds its own transaction machinery"
    missing = [name for name in CALLED_MODULES if name not in _called_modules(source)]
    assert missing == [], f"tools/lanes.py does not call {missing}"
