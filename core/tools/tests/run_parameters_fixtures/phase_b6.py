"""B-6 fixture phase: the ``credits`` profile of B6-RUN (AC-F.3, EA-19, EA-20).

``build_fixture.build`` calls :func:`extend` before it copies the components. Under every
profile but ``credits`` it does nothing. Under ``credits`` it provisions the inputs of one
scheduled credits run whose manifest names both phases (``phases: [plan, exec]``):

* the fixture grouping file with a ``run_parameters:`` block (``schema: run-parameters/1`` and
  the four defaults) and no plan carriers: the builder's ``write_carrier`` calls are replaced
  on the instance, so the plan the run writes is the only ``task.md``;
* ``<root>/credits/brief.md``: the run brief, whose ``## Authorization`` section copies the
  accepted ``run_parameters`` block as one fenced ``yaml`` block (the start record that the
  launcher's first-start admission reads, V6-047);
* ``<root>/credits/block.yaml``: the same block as a pre-plan block file (``inspect --block``);
* ``<root>/credits/manifest.json``: a ``credits-run.v1`` manifest with ``phases`` and
  ``run_id``, whose launch paths are the fixture repository and the interpreter that built it.

The module imports nothing from ``tests`` at run time, so it loads the same way under pytest
and under the B6-RUN build (``python -m tools.tests.run_parameters_fixtures.build_fixture``, EA-16).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from tools.tests.run_parameters_fixtures.build_fixture import Fixture

PROFILE = "credits"
FOLDER = "credits"
RUN_ID = "fixture-b6-run"
PHASES: tuple[str, ...] = ("plan", "exec")
DEFAULTS: tuple[tuple[str, str], ...] = (
    ("schema", "run-parameters/1"),
    ("decisions", "hdp"),
    ("commit_plan", "true"),
    ("exec_after_plan", "true"),
    ("commit_exec", "true"),
    ("push", "never"),
)
ORCHESTRATOR = "00000000-0000-4000-8000-0000000000aa"


def _display(path: Path | str) -> str:
    """Forward slashes and an upper-case drive letter (P-1), as ``build_fixture.display_path``."""
    text = str(path).replace("\\", "/").rstrip("/")
    if len(text) > 1 and text[1] == ":":
        text = text[0].upper() + text[1:]
    return text


def grouping_text(header: str) -> str:
    """The fixture grouping file: one session whose ``run_parameters`` block holds the defaults."""
    block = "\n".join(f"  {key}: {value}" for key, value in DEFAULTS)
    return (
        f"{header}\n\n# Fixture session grouping\n\n"
        "### Session FX1 — B6-RUN sample plan\n\n"
        "Routing: fixture\n\n"
        f"```yaml\nrun_parameters:\n{block}\n```\n"
    )


def block_text(block: Mapping[str, Any]) -> str:
    """The pre-plan block file of ``inspect --block``, as ``Fixture.write_block_file`` writes it."""
    return yaml.safe_dump({"run_parameters": dict(block)}, sort_keys=False)


def brief_text(header: str, plan: str, block: Mapping[str, Any]) -> str:
    """The run brief: the task, then the ``## Authorization`` section with the block copy."""
    return "\n".join(
        [
            header,
            "",
            f"# Credits run brief: {plan}",
            "",
            "Plan the fixture project from Step 0 of `.agent/workflows/create-plan.md`, then",
            "execute it in the executor worktree. Every effect goes through",
            "`tools/run_parameters.py verify` and `reserve` first.",
            "",
            "## Authorization",
            "",
            "The run parameters the human accepted for this run, copied byte for byte:",
            "",
            "```yaml",
            block_text(block).rstrip("\n"),
            "```",
            "",
        ]
    )


def manifest_doc(fx: Fixture, brief: Path) -> dict[str, Any]:
    """The ``credits-run.v1`` manifest of the run (R§4.1) with ``phases`` (V6-044)."""
    repo = _display(fx.repo)
    return {
        "schema": "credits-run.v1",
        "run_id": RUN_ID,
        "kind": "exec",
        "project_root": repo,
        "plan_folder": f"docs/execution/plans/{fx.plan}/",
        "brief": _display(brief),
        "phases": list(PHASES),
        "launch": {
            "working_directory": repo,
            "claude_exe": "claude",
            "python_exe": _display(sys.executable),
            "permission_mode": "bypassPermissions",
            "model": "fixture-model",
            "effort": "high",
            "segment_cap_usd": 5.0,
            "timeout_sec": 3600,
        },
        "budget": {"run_cap_usd": 10.0},
        "messaging": {
            "orchestrator_sessions": [ORCHESTRATOR],
            "ruling_enabled": False,
            "gate_wait_max_min": 0,
        },
        "depends_on": [],
        "lane": f"tree:{repo}",
    }


def extend(fx: Fixture) -> None:
    """Provision the ``credits`` run inputs; a no-op under every other profile."""
    if fx.profile != PROFILE:
        return
    # The builder's module: ``__main__`` under the B6-RUN ``-m`` build, the package module under pytest.
    header = str(getattr(sys.modules[type(fx).__module__], "FIXTURE_HEADER"))
    folder = fx.root / FOLDER

    def write_carrier(block: Mapping[str, Any], **options: object) -> None:
        """Replace the builder's plan carriers: the grouping file, then the run's start inputs."""
        fx.grouping_path.parent.mkdir(parents=True, exist_ok=True)
        fx.grouping_path.write_bytes(grouping_text(header).encode("utf-8"))
        if options.get("plan", fx.plan) not in (None, fx.plan):
            return
        folder.mkdir(parents=True, exist_ok=True)
        brief = folder / "brief.md"
        brief.write_bytes(brief_text(header, fx.plan, block).encode("utf-8"))
        (folder / "block.yaml").write_bytes(block_text(block).encode("utf-8"))
        manifest = json.dumps(manifest_doc(fx, brief), indent=2) + "\n"
        (folder / "manifest.json").write_bytes(manifest.encode("utf-8"))

    setattr(fx, "write_carrier", write_carrier)
