"""B-7 fixture phase: the R§4.8 components, the approved governance lines and the hook settings.

``build_fixture.build`` calls :func:`extend` before it copies the components. Under every
profile, :func:`extend`:

* appends to ``fx.components`` the R§4.8 components (report :1327-1337) that earlier phases did
  not add, so the policy the builder mints lists every component the activation check requires;
* writes ``AGENTS.md`` and ``GUARDRAILS.md`` as the fixture header followed by the approved
  after-lines of the R§7 ledger (the ``+`` lines of the approved governance diffs), so the policy
  validator passes on the fixture's governance text without the working copy's texts (EA-34);
* replaces ``fx.seal_activation`` on the instance. Its first call, the builder's, writes
  ``.claude/settings.json`` (the settings an earlier phase wrote, or ``{}``, plus the
  ``commit_gate.py`` ``PreToolUse`` hook and the policy's ``ask`` rules) and then runs the
  original seal, so the digests cover the written settings. A later call, by a test that edited
  the settings, keeps what the test wrote.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.tests.run_parameters_fixtures.build_fixture import Fixture

R48_COMPONENTS: tuple[str, ...] = (
    "tools/run_parameters.py",
    "tools/commit_batch.py",
    ".agent/skills/git-workflow/scripts/agent-commit.ps1",
    ".claude/hooks/commit_gate.py",
    ".claude/hooks/_hook_common.py",
    "tools/stop_gate.py",
    "tools/executor_worktree.py",
    "tools/validate_closeout_artifacts.py",
    "tools/completion_preflight.py",
    "tools/validate_agent_files.py",
    "tools/credits_state.py",
    "tools/credits_msg.py",
    ".agent/skills/claude-credits/Start-CreditsRun.ps1",
    ".agent/skills/claude-credits/Watch-CreditsRuns.ps1",
    ".agent/templates/TASK-TEMPLATE.md",
    ".agent/templates/PLAN-TEMPLATE.md",
    ".agent/skills/claude-credits/schemas/credits-run.v1.json",
    ".agent/docs/human-decision-protocol.md",
    ".agent/schemas/reflection.v1.yaml",
    ".claude/settings.json",
    ".agent/run-parameters/schemas/run-parameters-offer.v1.schema.json",
    ".agent/run-parameters/schemas/authorization.v1.schema.json",
    ".agent/run-parameters/governance/01-agents.diff",
    ".agent/run-parameters/governance/02-guardrails.diff",
    # MEU-784 AC-784.19: the lane tools.
    "tools/lanes.py",
    "tools/os_lease.py",
    "tools/ref_guard.py",
)
GOVERNANCE = ".agent/run-parameters/governance"
GOVERNANCE_DIFFS: dict[str, str] = {
    "AGENTS.md": "01-agents.diff",
    "GUARDRAILS.md": "02-guardrails.diff",
}
SETTINGS = ".claude/settings.json"
HOOK_COMMAND = 'python "${CLAUDE_PROJECT_DIR}/.claude/hooks/commit_gate.py"'


def diff_lines(text: str) -> tuple[list[str], list[str]]:
    """The removed and the added lines of a unified diff, in order, without their markers."""
    removed: list[str] = []
    added: list[str] = []
    for raw in text.split("\n"):
        if raw.startswith(("+++", "---")):
            continue
        if raw.startswith("-"):
            removed.append(raw[1:])
        elif raw.startswith("+"):
            added.append(raw[1:])
    return removed, added


def governance_text(header: str, name: str, lines: list[str]) -> str:
    """A fixture governance file: the header, a title, then the given lines as paragraphs."""
    body = "\n\n".join(lines)
    return f"{header}\n\n# Fixture {name}\n\n{body}\n"


def settings_doc(prior: bytes | None, ask_rules: tuple[str, ...]) -> dict[str, Any]:
    """The prior settings object (or ``{}``) plus the ``commit_gate`` hook and the ``ask`` rules."""
    doc: dict[str, Any] = {}
    if prior is not None:
        loaded = json.loads(prior.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"fixture {SETTINGS} is not a JSON object")
        doc = dict(loaded)
    permissions = dict(doc.get("permissions") or {})
    permissions["ask"] = list(ask_rules)
    doc["permissions"] = permissions
    doc["hooks"] = {
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": HOOK_COMMAND}]}
        ]
    }
    return doc


def extend(fx: Fixture) -> None:
    """Add the R§4.8 components, write the approved governance lines, wrap the seal."""
    # The builder's module: ``__main__`` under a ``-m`` build, the package module under pytest.
    builder = sys.modules[type(fx).__module__]
    header = str(getattr(builder, "FIXTURE_HEADER"))
    ask_rules = tuple(str(rule) for rule in getattr(builder, "ASK_RULES"))
    for rel in R48_COMPONENTS:
        if rel not in fx.components:
            fx.components.append(rel)
    for name, diff in GOVERNANCE_DIFFS.items():
        source = fx.source / GOVERNANCE / diff
        if not source.is_file():
            raise FileNotFoundError(f"approved governance diff missing: {source}")
        _, added = diff_lines(source.read_text(encoding="utf-8"))
        if not added:
            raise ValueError(f"approved governance diff adds no line: {source}")
        fx.write_text(name, governance_text(header, name, added))
    settings = fx.repo / SETTINGS
    prior = settings.read_bytes() if settings.is_file() else None
    original = fx.seal_activation
    sealed: list[bool] = []

    def seal_activation() -> None:
        """First call: write the hook settings, then seal; later calls: seal only."""
        if not sealed:
            sealed.append(True)
            doc = settings_doc(prior, ask_rules)
            fx.write_text(SETTINGS, json.dumps(doc, indent=2) + "\n")
        original()

    setattr(fx, "seal_activation", seal_activation)
