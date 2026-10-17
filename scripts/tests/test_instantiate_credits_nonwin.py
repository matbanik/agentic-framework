"""R1-F9 (execution review round 1): a non-Windows install keeps no test of a removed tool.

AC-J.4 removes the Windows-only files when the OS is not Windows. A test that stays in
``tools/tests/`` and imports, opens or runs one of the removed files then fails in the
adopter tree: round 1 found ``tools/tests/test_credits_authority.py`` kept while
``tools/credits_msg.py`` was removed.

These tests install a temporary copy of ``core/`` with ``sys.platform = "linux"`` and
check the tree that stays:

* no retained Python test or hook imports a removed module or names a removed file;
* no retained Pester test names a removed file outside a comment;
* the retained Python tests collect with no error;
* the files that round 1 named are removed, and ``--verify`` passes.

The helpers come from ``test_instantiate_credits.py`` (read only, never changed here).
"""

from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

HELPERS_FILE = Path(__file__).with_name("test_instantiate_credits.py")
#: The adopter folders whose files must not need a removed tool.
SCANNED_DIRS = ("tools/tests", ".claude/hooks")
#: Retained tests that round 1 and its follow-up search found importing a removed tool.
ROUND_1_FILES = (
    "tools/tests/test_credits_authority.py",
    "tools/tests/CreditsLauncherEnv.Tests.ps1",
    "tools/tests/CreditsTaskReadback.Tests.ps1",
)
PS_BLOCK_COMMENT = re.compile(r"<#.*?#>", re.DOTALL)
PS_NAME_SEPARATORS = ("/", "\\", "'", '"', " ")


def _helpers() -> ModuleType:
    """Load the installer test helpers (``_copy_core``, ``_load_installer``, ``_values``)."""
    spec = importlib.util.spec_from_file_location("instantiate_credits_helpers", HELPERS_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _files(root: Path) -> set[str]:
    """Every file below ``root`` as a POSIX path relative to it, without byte-code."""
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


class _Install:
    """A non-Windows install of a ``core/`` copy and what it removed."""

    def __init__(self, root: Path, removed: set[str]) -> None:
        self.root = root
        self.removed = removed
        self.names = {Path(rel).name for rel in removed}
        self.modules = {Path(rel).stem for rel in removed if rel.endswith(".py")}

    def retained(self, suffix: str) -> list[Path]:
        """The retained files with ``suffix`` in the scanned folders."""
        out: list[Path] = []
        for rel in SCANNED_DIRS:
            folder = self.root / rel
            if folder.is_dir():
                out.extend(
                    p
                    for p in sorted(folder.rglob(f"*{suffix}"))
                    if "__pycache__" not in p.parts
                )
        return out


@pytest.fixture
def linux_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Install:
    helpers = _helpers()
    root = helpers._copy_core(tmp_path / "acme")
    before = _files(root)
    monkeypatch.setattr(sys, "platform", "linux")
    inst = helpers._load_installer()
    assert inst.run(helpers._values(root), dry_run=False, root=root) == 0
    assert inst.verify_only(root) == 0
    removed = before - _files(root)
    assert "tools/credits_msg.py" in removed, sorted(removed)
    return _Install(root, removed)


def _python_needs(path: Path, install: _Install) -> list[str]:
    """The imports and path strings in ``path`` that point at a removed file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits.extend(
                f"import {a.name}" for a in node.names if a.name.split(".")[-1] in install.modules
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[-1] in install.modules:
                hits.append(f"from {node.module} import")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            last = node.value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            if last in install.names:
                hits.append(f"line {node.lineno}: {node.value!r}")
    return hits


def _powershell_needs(path: Path, install: _Install) -> list[str]:
    """The code lines (comments left out) in ``path`` that name a removed file."""
    text = PS_BLOCK_COMMENT.sub("", path.read_text(encoding="utf-8-sig"))
    hits: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        code = line.strip()
        if not code or code.startswith("#"):
            continue
        for name in install.names:
            if any(f"{sep}{name}" in code for sep in PS_NAME_SEPARATORS):
                hits.append(f"line {number}: {name}")
    return hits


def test_round_1_files_are_removed(linux_install: _Install) -> None:
    """R1-F9: the retained tests that need ``credits_msg.py`` or the skill folder go too."""
    for rel in ROUND_1_FILES:
        assert rel in linux_install.removed, rel
        assert not (linux_install.root / rel).exists(), rel


def test_no_retained_python_file_needs_a_removed_tool(linux_install: _Install) -> None:
    """R1-F9: no retained Python test or hook imports or names a removed file."""
    found = {
        p.relative_to(linux_install.root).as_posix(): hits
        for p in linux_install.retained(".py")
        if (hits := _python_needs(p, linux_install))
    }
    assert found == {}, found


def test_no_retained_pester_file_needs_a_removed_tool(linux_install: _Install) -> None:
    """R1-F9: no retained Pester test names a removed file outside a comment."""
    found = {
        p.relative_to(linux_install.root).as_posix(): hits
        for p in linux_install.retained(".ps1")
        if (hits := _powershell_needs(p, linux_install))
    }
    assert found == {}, found


def test_retained_python_tests_collect(linux_install: _Install, tmp_path: Path) -> None:
    """R1-F9: the retained Python tests import cleanly (no test imports a removed test)."""
    tests = [str(p) for p in sorted((linux_install.root / "tools" / "tests").glob("test_*.py"))]
    assert tests
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp={tmp_path / 'collect'}",
            *tests,
        ],
        cwd=linux_install.root,
        text=True,
        capture_output=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, (result.stdout[-4000:], result.stderr[-2000:])
