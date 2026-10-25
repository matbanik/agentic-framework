"""The worktree config that the lane test fixtures seed on ``main``.

``tools/lanes.py`` reads the project's junction files from the ``junction_files``
key of ``.agent/credits/worktree.json`` (design D-P10, §5.4) and refuses
``worktree_bad:config`` when the file is missing. Every lane fixture repository
therefore carries this config. The junction list is the fixture project's list
(the same nine files as ``test_lanes.py`` ``FIXTURE_JUNCTION_FILES``); the other
keys are empty, so no worktree step copies env files, frozen dirs or linked trees,
and ``venv_build`` is never run.
"""

from __future__ import annotations

import json

FIXTURE_JUNCTION_FILES: tuple[str, ...] = (
    ".agent/context/known-issues.yaml",
    ".agent/context/meu-status.yaml",
    ".agent/context/meu-registry.md",
    ".agent/context/known-issues.md",
    "docs/BUILD_PLAN.md",
    ".agent/context/current-focus.md",
    "docs/execution/metrics.md",
    ".secrets.baseline",
    "tools/temp_citation_baseline.json",
)
WORKTREE_CONFIG = ".agent/credits/worktree.json"
WORKTREE_CONFIG_DATA: dict[str, object] = {
    "env_files": [],
    "frozen_dirs": [],
    "venv_build": None,
    "linked_trees": [],
    "junction_files": list(FIXTURE_JUNCTION_FILES),
}
WORKTREE_CONFIG_TEXT = json.dumps(WORKTREE_CONFIG_DATA) + "\n"
# The ``seed=`` mapping of ``phase_b3.rig``: the config as one seeded file.
SEED: dict[str, bytes] = {WORKTREE_CONFIG: WORKTREE_CONFIG_TEXT.encode("utf-8")}
