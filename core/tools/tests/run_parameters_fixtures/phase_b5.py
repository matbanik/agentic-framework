"""B-5 fixture phase: the ``dry-run`` profile of B5-DRY (AC-E.6, EA-16, EA-17).

``build_fixture.build`` calls :func:`extend` before it copies the components. Under every
profile but ``dry-run`` it does nothing, so the pytest fixtures keep their B-2/B-3 shape. Under
``dry-run`` it provisions the repository a ``claude -p '/create-plan brief.md'`` session plans
in (V-13):

* the planning documents the session reads (the workflow, the decision protocol, the harness
  profiles and both plan templates), copied verbatim from the working copy;
* a fixture ``.claude/commands/create-plan.md`` that runs the workflow on the brief, and a
  fixture ``.claude/settings.json`` whose only allow rules are the ``run_parameters.py
  inspect`` and ``resolve`` commands on the interpreter that built the fixture;
* the fixture grouping file with a ``run_parameters:`` block (``schema: run-parameters/1`` and
  the four defaults) and no plan carriers: the builder's ``write_carrier`` calls are replaced
  on the instance, so the plan the session writes is the only ``task.md`` (``plan_written=1``);
* the Step 0 record of the accepted offer (EA-17): the builder's transcript holds the offer and
  the human's ``proceed``, so the replacement writes that acceptance's ``run_parameters`` block
  as a pre-plan block file (``inspect --block``) and the offered payload as one fenced block.
  The session copies the first into both plan files and shows the second in its §5c reply.

The module imports nothing from ``tests`` at run time, so it loads the same way under pytest
and under the V-13 build (``python -m tools.tests.run_parameters_fixtures.build_fixture``, EA-16).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from tools.tests.run_parameters_fixtures.build_fixture import Fixture

PROFILE = "dry-run"
DOCS: tuple[str, ...] = (
    ".agent/workflows/create-plan.md",
    ".agent/docs/human-decision-protocol.md",
    ".agent/docs/harness-profiles.md",
    ".agent/templates/TASK-TEMPLATE.md",
    ".agent/templates/PLAN-TEMPLATE.md",
)
COMMAND = ".claude/commands/create-plan.md"
SETTINGS = ".claude/settings.json"
TOOL = "tools/run_parameters.py"
VERBS: tuple[str, ...] = ("inspect", "resolve")
BLOCK_FILE = ".agent/context/run-parameters-dry-run.yaml"
OFFER_FILE = ".agent/context/run-parameters-dry-run-offer.md"
DEFAULTS: tuple[tuple[str, str], ...] = (
    ("schema", "run-parameters/1"),
    ("decisions", "hdp"),
    ("commit_plan", "true"),
    ("exec_after_plan", "true"),
    ("commit_exec", "true"),
    ("push", "never"),
)
COMMAND_TEXT = """---
description: Plan a project from a brief (fixture copy of the /create-plan workflow)
---

Follow `.agent/workflows/create-plan.md` from Step 0 for the plan brief `$ARGUMENTS`. The brief
states the run's limits; where it narrows the workflow, the brief wins.
"""


def _display(path: Path | str) -> str:
    """Forward slashes and an upper-case drive letter (P-1), as ``build_fixture.display_path``."""
    text = str(path).replace("\\", "/").rstrip("/")
    if len(text) > 1 and text[1] == ":":
        text = text[0].upper() + text[1:]
    return text


def allow_rules(python: str | None = None) -> list[str]:
    """The ``Bash(...)`` allow rules of the fixture settings: one per verb, on ``python``."""
    interpreter = _display(python or sys.executable)
    return [f"Bash({interpreter} -X utf8 {TOOL} {verb}:*)" for verb in VERBS]


def grouping_text(header: str) -> str:
    """The fixture grouping file: one session whose ``run_parameters`` block holds the defaults."""
    block = "\n".join(f"  {key}: {value}" for key, value in DEFAULTS)
    return (
        f"{header}\n\n# Fixture session grouping\n\n"
        "### Session FX1 — B5-DRY sample plan\n\n"
        "Routing: fixture\n\n"
        f"```yaml\nrun_parameters:\n{block}\n```\n"
    )


def block_text(block: Mapping[str, Any]) -> str:
    """The pre-plan block file of ``inspect --block``, as ``Fixture.write_block_file`` writes it."""
    return yaml.safe_dump({"run_parameters": dict(block)}, sort_keys=False)


def offer_text(header: str, lines: Sequence[str]) -> str:
    """The accepted offer's payload as the one fenced block of a Markdown file."""
    return "\n".join(
        [
            header,
            "",
            "The run parameters offer the human accepted in the fixture session (B5-DRY).",
            "",
            "```yaml",
            *lines,
            "```",
            "",
        ]
    )


def extend(fx: Fixture) -> None:
    """Provision the ``dry-run`` repository; a no-op under every other profile."""
    if fx.profile != PROFILE:
        return
    # The builder's module: ``__main__`` under a ``-m`` build, the package module under pytest.
    source_path = getattr(sys.modules[type(fx).__module__], "source_path")
    missing = [rel for rel in DOCS if not source_path(fx.source, rel).is_file()]
    if missing:
        raise FileNotFoundError(
            f"dry-run documents missing from the working copy {fx.source}: {missing}"
        )
    for rel in DOCS:
        target = fx.repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_path(fx.source, rel).read_bytes())
    fx.write_text(COMMAND, COMMAND_TEXT)
    settings = {"permissions": {"allow": allow_rules()}}
    fx.write_text(SETTINGS, json.dumps(settings, indent=2) + "\n")
    # The builder's module: ``__main__`` under the V-13 ``-m`` build, the package module under pytest.
    header = str(getattr(sys.modules[type(fx).__module__], "FIXTURE_HEADER"))

    def write_carrier(block: Mapping[str, Any], **options: object) -> None:
        """Replace the builder's plan carriers: the grouping file, then the main plan's acceptance."""
        fx.grouping_path.parent.mkdir(parents=True, exist_ok=True)
        fx.grouping_path.write_bytes(grouping_text(header).encode("utf-8"))
        if options.get("plan", fx.plan) != fx.plan:
            return
        lines = fx.lines(fx.offer())
        authorization = block.get("authorization")
        digest = (
            authorization.get("offer_digest")
            if isinstance(authorization, Mapping)
            else None
        )
        if digest != fx.digest(lines):
            raise ValueError("the dry-run block does not reference the default offer")
        fx.write_text(BLOCK_FILE, block_text(block))
        fx.write_text(OFFER_FILE, offer_text(header, lines))

    setattr(fx, "write_carrier", write_carrier)
