"""B-8 fixture phase: the worktree layout (AC-G.1 to AC-G.4, EA-28).

``build_fixture.build`` calls :func:`extend` before it copies the components. B-8 changes no
fixture repository: ``tools/executor_worktree.py`` is already a B-3 component
(``phase_b3.B3_COMPONENTS``), and the B-8 tests build their own temp repositories with the
worktree parent patched (``test_worktree_layout.py``). So :func:`extend` does nothing under
every profile, and the module exists so the B-8 phase has its fixture entry. It also holds
the two directory-link helpers the B-8 tests use (the source keeps them in its codebase
validator, which the framework does not ship).

The module imports nothing from ``tests`` at run time, so it loads the same way under pytest
and under a ``python -m tools.tests.run_parameters_fixtures.build_fixture`` build (EA-16).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.tests.run_parameters_fixtures.build_fixture import Fixture


def extend(fx: Fixture) -> None:
    """B-8 adds no fixture profile and no component: a no-op under every profile."""
    del fx


def _make_dir_link(link: Path, target: Path) -> None:
    """A directory junction on Windows, a directory symlink elsewhere."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def _drop_dir_link(path: Path) -> None:
    """Remove a directory link itself, never what it points at."""
    if sys.platform == "win32" and os.path.isjunction(path):
        os.rmdir(path)
    else:
        os.unlink(path)
