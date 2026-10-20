"""Build a disposable run-parameters fixture repository (R§4.8 "Fixtures", AC-B.12).

The builder writes only under a new, empty root that is not inside a git work tree:

    <root>/repo/          a git repository (branch ``main``, one commit) that holds the fixture
                          ``AGENTS.md`` and ``GUARDRAILS.md``, the components copied verbatim from
                          the working copy under test, the activation policy and evidence, the
                          fixture plan carriers and the fixture grouping file
    <root>/claude/        a ``CLAUDE_CONFIG_DIR`` whose ``projects/<slug>/<session>.jsonl``
                          transcript holds a presentation and the human acceptance
    <root>/receipts/      one fixture receipt per activation-evidence entry
    <root>/blocks/        pre-plan ``run_parameters`` block files (``inspect --block``)
    <root>/fixture.json   the manifest (profile, session, plans, paths)

The repository's common config carries ``run-parameters.fixture=true`` (the fixture mark):
only a marked store reads the test seams (``RUN_PARAMETERS_TEST_CRASH_AT``,
``RUN_PARAMETERS_TEST_LOCK_WAIT_S``, ``RUN_PARAMETERS_TEST_CLOCK``) and accepts evidence whose
entries say ``fixture: true``. ``build(..., mark=False)`` writes a production-shaped fixture:
no mark and no ``fixture`` key in the evidence.

A later phase extends the fixture with a ``phase_<tag>.py`` module in this folder that defines
``extend(fx)``; the builder runs every such module before it copies the components and computes
their digests.

CLI (the paid rows V-13 and V-16)::

    python -m tools.tests.run_parameters_fixtures.build_fixture --root <dir> --source <tree> --profile <name>

Exit 0 prints the manifest; exit 2 is a refused root, and nothing is written.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import importlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

PLAN = "2026-10-17-fixture-plan"
PLAN_B = "2026-10-17-fixture-plan-b"
GROUPING = "fixture-session-grouping"
RUN_PARAMETERS_HOME = ".agent/run-parameters"
POLICY = ".agent/run-parameters.policy.json"
EVIDENCE = f"{RUN_PARAMETERS_HOME}/activation-evidence.json"
# Components the fixture writes itself (phase B-5 and the B-7 seal). The raw framework ships
# only ``.claude/settings.hooks.json``, so a source without one is neither missing nor copied.
GENERATED: frozenset[str] = frozenset({".claude/settings.json"})
B2_COMPONENTS: tuple[str, ...] = (
    "tools/run_parameters.py",
    "tools/validate_closeout_artifacts.py",
    f"{RUN_PARAMETERS_HOME}/schemas/run-parameters-offer.v1.schema.json",
    f"{RUN_PARAMETERS_HOME}/schemas/authorization.v1.schema.json",
)
EVIDENCE_PHASES: tuple[str, ...] = ("b2", "b3", "b4", "b5", "b6", "b8")
PROFILES: tuple[str, ...] = ("test", "dry-run", "credits")
ACTS: tuple[str, ...] = ("exec_commit", "exec_start", "finalize", "plan_commit")
ASK_RULES: tuple[str, ...] = tuple(f"fixture-ask-rule-{n}" for n in range(1, 7))
FIXTURE_HEADER = "<!-- run-parameters fixture: written by tools/tests/run_parameters_fixtures/build_fixture.py -->"
FIXTURE_CLOCK = "2026-10-17T15:00:00Z"
FIXTURE_DATE = "2026-10-17T14:34:40Z"
RECORD_TS = "2026-10-17T14:34:40.000Z"
MARK_KEY = "run-parameters.fixture"
SLUG_RE = re.compile(r"[^A-Za-z0-9]")
SESSION_LABELS: dict[str, str] = {PLAN: "FX1", PLAN_B: "FX2"}


#: An installed component path and its location in a raw framework checkout: the framework
#: ships ``core/templates/``, which an adopter installs at ``.agent/templates/`` (TEMPLATE_HOME).
SOURCE_ALIASES: tuple[tuple[str, str], ...] = ((".agent/templates/", "templates/"),)


def source_path(source: Path, rel: str) -> Path:
    """``source / rel``, or its raw-framework location when only that one exists."""
    direct = source / rel
    if direct.is_file():
        return direct
    for installed, raw in SOURCE_ALIASES:
        if rel.startswith(installed):
            alias = source / (raw + rel[len(installed) :])
            if alias.is_file():
                return alias
    return direct


class FixtureRootError(Exception):
    """The root is not empty, or it lies inside a git work tree or git dir (CLI exit 2)."""


class _Auto:
    """Marker: take the parent uuid from the last record of the session."""


AUTO = _Auto()


def capabilities_for(d20: str) -> dict[str, str]:
    """The capability matrix that a D-20 ruling implies (R§4.8)."""
    if d20 == "A":
        return dict.fromkeys(ACTS, "headless")
    if d20 == "B":
        return {
            "exec_commit": "headless",
            "exec_start": "headless",
            "finalize": "interactive",
            "plan_commit": "interactive",
        }
    raise ValueError(f"unknown D-20 ruling: {d20!r}")


def git_env() -> dict[str, str]:
    """The process environment without ``GIT_*`` variables (they redirect git) and system config."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def git(cwd: Path, *args: str, check: bool = True) -> str:
    """Run git in ``cwd`` and return its stripped stdout; raise with stderr on failure."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=git_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def display_path(path: Path | str) -> str:
    """P-1's ASCII normalization: forward slashes, upper-case drive letter, no trailing slash."""
    text = str(path).replace("\\", "/").rstrip("/")
    if re.match(r"^[a-z]:", text):
        text = text[0].upper() + text[1:]
    return text


def project_slug(display: str) -> str:
    """The transcript folder name of a project, as ``credits_state.transcript_path`` derives it."""
    return SLUG_RE.sub("-", display)


def sha256_file(path: Path) -> str:
    """The hex sha256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def offer_digest(lines: Sequence[str]) -> str:
    """O-3: sha256 of the payload lines joined with a newline, no trailing newline."""
    return "sha256:" + hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def render_value(value: object) -> str:
    """Render a typed offer value in the O-1a normal form (flow maps and flow lists)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Mapping):
        items = ", ".join(f"{key}: {render_value(item)}" for key, item in value.items())
        return "{" + items + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(render_value(item) for item in value) + "]"
    return str(value)


def offer_lines(values: Mapping[str, object]) -> list[str]:
    """The payload lines of an offer: the root line, then one two-space line per key."""
    return [
        "run-parameters-offer:",
        *(f"  {key}: {render_value(item)}" for key, item in values.items()),
    ]


def frontmatter(data: Mapping[str, object]) -> str:
    """A YAML frontmatter block in key order."""
    return (
        "---\n"
        + yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True)
        + "---\n"
    )


def check_root(root: Path) -> None:
    """Refuse a non-empty root and a root inside a git work tree or git dir."""
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise FixtureRootError(f"root is not an empty directory: {root}")
    probe = root
    while not probe.exists():
        if probe.parent == probe:
            raise FixtureRootError(f"root has no existing ancestor: {root}")
        probe = probe.parent
    for flag in ("--is-inside-work-tree", "--is-inside-git-dir"):
        proc = subprocess.run(
            ["git", "rev-parse", flag],
            cwd=probe,
            env=git_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip() == "true":
            raise FixtureRootError(
                f"root lies inside a git repository ({flag}): {root}"
            )


@contextlib.contextmanager
def patched_environ(env: Mapping[str, str]) -> Iterator[None]:
    """Replace ``os.environ`` with ``env`` for the block, then restore it."""
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def parse_output(text: str) -> dict[str, Any]:
    """The one JSON object a run_parameters.py verb prints; an empty dict for no output."""
    text = text.strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"run_parameters.py printed a non-object: {text[:200]}")
    return data


@dataclass
class Fixture:
    """One built fixture: paths, the transcript writer, the carriers and the verb runners."""

    root: Path
    source: Path
    profile: str
    mark: bool
    repo: Path
    config_dir: Path
    receipts: Path
    session: str
    plan: str = PLAN
    grouping: str = GROUPING
    components: list[str] = field(default_factory=lambda: list(B2_COMPONENTS))
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    rulings: dict[str, str] = field(default_factory=lambda: {"d19": "A", "d20": "A"})
    block: dict[str, Any] = field(default_factory=dict)
    _last: dict[str, str | None] = field(default_factory=dict)
    _grouping_lines: dict[str, str | None] = field(default_factory=dict)

    # -- paths ---------------------------------------------------------------------------

    @property
    def display(self) -> str:
        """The canonical display path of the fixture repository (P-1)."""
        return display_path(git(self.repo, "rev-parse", "--show-toplevel"))

    @property
    def common_dir(self) -> Path:
        """The repository's git common dir."""
        return self.repo / ".git"

    @property
    def store(self) -> Path:
        """The authority store folder (R§4.1)."""
        return self.common_dir / "run-parameters"

    @property
    def policy_path(self) -> Path:
        return self.repo / POLICY

    @property
    def evidence_path(self) -> Path:
        return self.repo / EVIDENCE

    @property
    def grouping_path(self) -> Path:
        return self.repo / ".agent" / "context" / "grouping" / f"{self.grouping}.md"

    @property
    def transcript(self) -> Path:
        """The transcript of the fixture session."""
        return self.transcript_path()

    def transcript_path(
        self, session: str | None = None, display: str | None = None
    ) -> Path:
        """``<config>/projects/<slug of display>/<session>.jsonl``."""
        slug = project_slug(display or self.display)
        return self.config_dir / "projects" / slug / f"{session or self.session}.jsonl"

    def plan_dir(self, plan: str | None = None) -> Path:
        return self.repo / "docs" / "execution" / "plans" / (plan or self.plan)

    def task_path(self, plan: str | None = None) -> Path:
        return self.plan_dir(plan) / "task.md"

    def plan_path(self, plan: str | None = None) -> Path:
        return self.plan_dir(plan) / "implementation-plan.md"

    def for_repo(self, repo: Path) -> Fixture:
        """A view of this fixture over another repository (a clone or a moved copy), in a new session."""
        return dataclasses.replace(
            self, repo=repo, session=str(uuid.uuid4()), _last={}, _grouping_lines={}
        )

    def write_text(self, relpath: str, text: str) -> Path:
        """Write a repository file with LF line ends."""
        path = self.repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    # -- transcript ----------------------------------------------------------------------

    def add_record(
        self,
        record: dict[str, Any],
        session: str | None = None,
        display: str | None = None,
    ) -> str:
        """Append one record to a session transcript; return its uuid."""
        session = session or self.session
        path = self.transcript_path(session, display)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        record_uuid = str(record.get("uuid", ""))
        if record_uuid:
            self._last[session] = record_uuid
        return record_uuid

    def _base(
        self, kind: str, parent: str | None | _Auto, session: str | None
    ) -> dict[str, Any]:
        session = session or self.session
        return {
            "type": kind,
            "uuid": str(uuid.uuid4()),
            "parentUuid": self._last.get(session)
            if isinstance(parent, _Auto)
            else parent,
            "sessionId": session,
            "isSidechain": False,
            "timestamp": RECORD_TS,
            "cwd": self.display,
            "version": "fixture",
        }

    def add_assistant(
        self,
        text: str,
        *,
        parent: str | None | _Auto = AUTO,
        session: str | None = None,
        **over: object,
    ) -> str:
        """An assistant record whose content is one text block."""
        record = self._base("assistant", parent, session)
        record["message"] = {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        }
        record.update(over)
        return self.add_record(record, session)

    def add_human(
        self,
        text: str,
        *,
        parent: str | None | _Auto = AUTO,
        session: str | None = None,
        **over: object,
    ) -> str:
        """A typed human record (passes ``is_human_entry`` and ``is_typed_turn``)."""
        record = self._base("user", parent, session)
        record.update(
            {
                "userType": "external",
                "origin": {"kind": "human"},
                "turnOrigin": "human",
                "promptSource": "typed",
                "promptId": str(uuid.uuid4()),
                "message": {"role": "user", "content": text},
            }
        )
        record.update(over)
        return self.add_record(record, session)

    def add_tool_result(
        self,
        text: str,
        *,
        parent: str | None | _Auto = AUTO,
        session: str | None = None,
    ) -> str:
        """A user record that carries a tool result."""
        record = self._base("user", parent, session)
        record.update(
            {
                "userType": "external",
                "origin": {"kind": "human"},
                "toolUseResult": {"stdout": text},
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_fixture",
                            "content": text,
                        }
                    ],
                },
            }
        )
        return self.add_record(record, session)

    def add_hook_frame(
        self,
        text: str,
        *,
        parent: str | None | _Auto = AUTO,
        session: str | None = None,
    ) -> str:
        """A ``isMeta`` user record, the shape of a hook frame."""
        return self.add_human(text, parent=parent, session=session, isMeta=True)

    def add_compact_summary(
        self,
        text: str,
        *,
        parent: str | None | _Auto = AUTO,
        session: str | None = None,
    ) -> str:
        """A user record flagged as a compact summary."""
        return self.add_human(
            text, parent=parent, session=session, isCompactSummary=True
        )

    def add_system(
        self,
        subtype: str = "informational",
        *,
        parent: str | None | _Auto = AUTO,
        session: str | None = None,
    ) -> str:
        """A system record (``compact_boundary`` for a compact boundary)."""
        record = self._base("system", parent, session)
        record.update({"subtype": subtype, "content": "", "level": "info"})
        return self.add_record(record, session)

    def add_attachment(
        self, *, parent: str | None | _Auto = AUTO, session: str | None = None
    ) -> str:
        """An attachment record."""
        record = self._base("attachment", parent, session)
        record["attachment"] = {"type": "fixture"}
        return self.add_record(record, session)

    # -- offers and blocks ---------------------------------------------------------------

    def offer(self, **over: object) -> dict[str, Any]:
        """The default offer values in key order; ``plan``, ``grouping`` and ``branch`` set the scope."""
        values: dict[str, Any] = {
            "schema": "run-parameters-offer/1",
            "project": self.display,
            "scope": {"plan": self.plan, "grouping": self.grouping, "branch": "main"},
            "members": [],
            "expires": "none",
            "decisions": "hdp",
            "commit_plan": True,
            "exec_after_plan": True,
            "commit_exec": True,
            "push": "never",
            "grants": list(ACTS),
            "standing": False,
            "supersedes": "none",
            "accept": "proceed",
        }
        scope = dict(values["scope"])
        for key in ("plan", "grouping", "branch"):
            if key in over:
                scope[key] = over.pop(key)
        values["scope"] = scope
        for key, item in over.items():
            if key not in values:
                raise KeyError(
                    f"unknown offer key {key!r}; pass raw lines for an invalid offer"
                )
            values[key] = item
        return values

    def standing_offer(
        self, members: Sequence[str], expires: str = "2026-12-31", **over: object
    ) -> dict[str, Any]:
        """A standing offer for the fixture grouping."""
        return self.offer(
            plan="none", members=sorted(members), expires=expires, standing=True, **over
        )

    @staticmethod
    def lines(values: Mapping[str, object]) -> list[str]:
        """The payload lines of ``values``."""
        return offer_lines(values)

    @staticmethod
    def digest(lines: Sequence[str]) -> str:
        """The O-3 digest of payload lines."""
        return offer_digest(lines)

    @staticmethod
    def offer_text(
        lines: Sequence[str],
        *,
        fence: str = "```yaml",
        close: str = "```",
        prose: str = "",
    ) -> str:
        """An assistant text that holds one fenced offer block."""
        intro = prose or "These are the run parameters for this plan."
        return "\n".join(
            [intro, "", fence, *lines, close, "", "Reply with the one acceptance word."]
        )

    def authorization(
        self,
        values: Mapping[str, Any],
        *,
        message_uuid: str,
        presentation_uuid: str,
        response: str,
        lines: Sequence[str] | None = None,
        session: str | None = None,
        form: str = "reply",
        date: str = FIXTURE_DATE,
    ) -> dict[str, Any]:
        """The ``authorization/1`` block that references one human record."""
        return {
            "schema": "authorization/1",
            "source": "USER_EXPLICIT",
            "form": form,
            "project": values["project"],
            "session": session or self.session,
            "message_uuid": message_uuid,
            "presentation_uuid": presentation_uuid,
            "offer_digest": offer_digest(
                lines if lines is not None else offer_lines(values)
            ),
            "date": date,
            "response": response,
            "scope": dict(values["scope"]),
            "members": list(values["members"]),
            "expires": values["expires"],
            "grants": list(values["grants"]),
            "standing": values["standing"],
            "supersedes": values["supersedes"],
        }

    @staticmethod
    def make_block(
        values: Mapping[str, Any],
        authorization: Mapping[str, Any],
        tightened_from: str = "none",
        **sigma: object,
    ) -> dict[str, Any]:
        """A ``run_parameters`` block carrying the offered values, or ``sigma`` overrides."""
        block: dict[str, Any] = {
            "schema": "run-parameters/1",
            "decisions": values["decisions"],
            "commit_plan": values["commit_plan"],
            "exec_after_plan": values["exec_after_plan"],
            "commit_exec": values["commit_exec"],
            "push": "never",
            "tightened_from": tightened_from,
            "authorization": dict(authorization),
        }
        block.update(sigma)
        return block

    def present_and_accept(
        self,
        word: str | None = None,
        *,
        values: Mapping[str, Any] | None = None,
        lines: Sequence[str] | None = None,
        session: str | None = None,
        **over: object,
    ) -> dict[str, Any]:
        """Write a presentation and a human reply; return the ``run_parameters`` block."""
        offered = dict(values) if values is not None else self.offer(**over)
        payload = list(lines) if lines is not None else offer_lines(offered)
        presentation = self.add_assistant(self.offer_text(payload), session=session)
        response = word if word is not None else str(offered["accept"])
        message = self.add_human(response, session=session)
        auth = self.authorization(
            offered,
            message_uuid=message,
            presentation_uuid=presentation,
            response=response,
            lines=payload,
            session=session,
        )
        return self.make_block(offered, auth)

    # -- carriers ------------------------------------------------------------------------

    def grouping_line(
        self, block: Mapping[str, Any], values: Mapping[str, object] | None = None
    ) -> str:
        """The C1 ``Run parameters:`` line of a grouping session (U+00B7 separators)."""
        sigma = dict(values) if values is not None else block
        auth = block["authorization"]

        def word(key: str) -> str:
            return render_value(sigma[key])

        return (
            f"Run parameters: decisions={word('decisions')} · commit_plan={word('commit_plan')}"
            f" · exec_after_plan={word('exec_after_plan')} · commit_exec={word('commit_exec')}"
            f" · push=never · authorization={str(auth['session'])[:8]}/{auth['message_uuid']}"
        )

    def render_grouping(self) -> None:
        """Rewrite the grouping file from the per-plan session lines."""
        out = [
            FIXTURE_HEADER,
            "",
            "# Fixture session grouping",
            "",
        ]
        plans = sorted(set(SESSION_LABELS) | set(self._grouping_lines))
        for index, plan in enumerate(plans, start=1):
            label = SESSION_LABELS.get(plan, f"FX{index}")
            out += [f"### Session {label} — {plan}", "", "Routing: fixture"]
            line = self._grouping_lines.get(plan)
            if line:
                out.append(line)
            out.append("")
        self.grouping_path.parent.mkdir(parents=True, exist_ok=True)
        self.grouping_path.write_bytes("\n".join(out).encode("utf-8"))

    def write_carrier(
        self,
        block: Mapping[str, Any],
        *,
        plan: str | None = None,
        task: bool = True,
        plan_md: bool = True,
        grouping_line: bool = True,
        task_block: Mapping[str, Any] | None = None,
        grouping_values: Mapping[str, object] | None = None,
        bound_sessions: Sequence[str] | None = None,
        store_seq: int | None = None,
        status: str = "in_progress",
    ) -> None:
        """Write the C2 task.md and implementation-plan.md blocks and the C1 grouping line."""
        plan = plan or self.plan
        if task:
            data: dict[str, Any] = {
                "status": status,
                "template_version": "2.4",
                "stop_gate": "armed",
                "run_parameters": dict(task_block if task_block is not None else block),
                "bound_sessions": list(bound_sessions or []),
            }
            if store_seq is not None:
                data["store_seq"] = store_seq
            body = f"\n# Task: {plan}\n\n| # | Task | Status |\n| :- | :- | :- |\n| 0 | fixture row | [ ] |\n"
            path = self.task_path(plan)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((frontmatter(data) + body).encode("utf-8"))
        if plan_md:
            data = {
                "plan": plan,
                "template_version": "2.3",
                "run_parameters": dict(block),
            }
            path = self.plan_path(plan)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                (frontmatter(data) + f"\n# Implementation plan: {plan}\n").encode(
                    "utf-8"
                )
            )
        auth = block.get("authorization", {})
        if grouping_line and isinstance(auth, Mapping) and "message_uuid" in auth:
            self._grouping_lines[plan] = self.grouping_line(block, grouping_values)
        else:
            self._grouping_lines[plan] = None
        self.render_grouping()

    def write_block_file(self, block: Mapping[str, Any], name: str = "block") -> Path:
        """A pre-plan ``run_parameters`` block file outside the repository (``inspect --block``)."""
        path = self.root / "blocks" / f"{name}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            yaml.safe_dump({"run_parameters": dict(block)}, sort_keys=False).encode(
                "utf-8"
            )
        )
        return path

    # -- activation ----------------------------------------------------------------------

    def component_digests(self) -> dict[str, str]:
        """sha256 of every component's current bytes in the fixture repository."""
        return {rel: sha256_file(self.repo / rel) for rel in self.components}

    def seal_activation(self) -> None:
        """Write the receipts, the activation evidence and, last, the policy (R§4.8)."""
        digests = self.component_digests()
        self.receipts.mkdir(parents=True, exist_ok=True)
        entries: dict[str, dict[str, Any]] = {}
        for phase in EVIDENCE_PHASES:
            if phase in self.evidence:
                entries[phase] = self.evidence[phase]
                continue
            receipt = self.receipts / f"{phase}.txt"
            receipt.write_bytes(f"fixture receipt {phase}: exit 0\n".encode())
            entry: dict[str, Any] = {
                "receipt": display_path(receipt),
                "sha256": sha256_file(receipt),
                "exit_code": 0,
                "components": dict(digests),
            }
            if self.mark:
                entry["fixture"] = True
            entries[phase] = entry
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_path.write_bytes(
            (json.dumps(entries, indent=2) + "\n").encode("utf-8")
        )
        self.write_policy()

    def write_policy(
        self,
        *,
        rulings: Mapping[str, str] | None = None,
        capabilities: Mapping[str, str] | None = None,
        policy_version: int = 1,
    ) -> Path:
        """Write ``.agent/run-parameters.policy.json`` over the current component bytes."""
        if rulings is not None:
            self.rulings = dict(rulings)
        components = self.component_digests()
        components[EVIDENCE] = sha256_file(self.evidence_path)
        policy = {
            "policy_version": policy_version,
            "components": dict(sorted(components.items())),
            "rulings": dict(self.rulings),
            "capabilities": dict(capabilities or capabilities_for(self.rulings["d20"])),
            "ask_rules": list(ASK_RULES),
        }
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy_path.write_bytes(
            (json.dumps(policy, indent=2) + "\n").encode("utf-8")
        )
        return self.policy_path

    # -- git and the store ---------------------------------------------------------------

    def commit(
        self, message: str = "fixture: update carriers", repo: Path | None = None
    ) -> None:
        """Commit every change in the repository."""
        target = repo or self.repo
        git(target, "add", "-A")
        git(target, "commit", "-q", "--allow-empty", "-m", message)

    def config_get(self, key: str, repo: Path | None = None) -> str | None:
        """Read a key from the common config with ``--file`` (the anchor's read-back form)."""
        common = (repo / ".git") if repo is not None else self.common_dir
        value = git(
            self.repo if repo is None else repo,
            "config",
            "--file",
            str(common / "config"),
            "--get",
            key,
            check=False,
        )
        return value or None

    def config_set(self, key: str, value: str, repo: Path | None = None) -> None:
        common = (repo / ".git") if repo is not None else self.common_dir
        git(
            self.repo if repo is None else repo,
            "config",
            "--file",
            str(common / "config"),
            key,
            value,
        )

    def config_unset(self, key: str, repo: Path | None = None) -> None:
        common = (repo / ".git") if repo is not None else self.common_dir
        git(
            self.repo if repo is None else repo,
            "config",
            "--file",
            str(common / "config"),
            "--unset",
            key,
            check=False,
        )

    def set_mark(self, repo: Path | None = None) -> None:
        """Mark a repository's store as a fixture store (the seams read only under this mark)."""
        self.config_set(MARK_KEY, "true", repo)

    def clone(self, name: str) -> Path:
        """``git clone`` the fixture repository to ``<root>/<name>``; copy its transcripts."""
        dest = self.root / name
        git(
            self.root,
            "clone",
            "--config",
            "core.autocrlf=false",
            "-q",
            str(self.repo),
            str(dest),
        )
        for key, value in (
            ("user.name", "Fixture"),
            ("user.email", "fixture@example.invalid"),
            ("commit.gpgsign", "false"),
            ("core.hooksPath", str(self.root / "no-hooks")),
        ):
            git(dest, "config", key, value)
        self.mirror_transcripts(dest)
        return dest

    def mirror_transcripts(self, repo: Path) -> None:
        """Copy every transcript of the fixture project into the project folder of ``repo``."""
        source = self.transcript_path().parent
        target = self.transcript_path(
            display=display_path(git(repo, "rev-parse", "--show-toplevel"))
        ).parent
        target.mkdir(parents=True, exist_ok=True)
        for path in source.glob("*.jsonl"):
            shutil.copyfile(path, target / path.name)

    def store_snapshot(self) -> dict[str, str]:
        """sha256 of every file under the store plus the witness and anchor config values."""
        out: dict[str, str] = {}
        if self.store.exists():
            for path in sorted(self.store.rglob("*")):
                if path.is_file():
                    out[path.relative_to(self.store).as_posix()] = sha256_file(path)
        for key in (
            "run-parameters.storeUuid",
            "run-parameters.witnessSeq",
            "run-parameters.witnessDigest",
        ):
            out[f"config:{key}"] = self.config_get(key) or ""
        return out

    def copy_store(self, dest: Path) -> None:
        """Copy the store folder to ``dest`` (a restore source or a copied store)."""
        shutil.copytree(self.store, dest)

    def restore_store(self, source: Path) -> None:
        """Replace the store folder with a copy taken earlier, at the same path."""
        shutil.rmtree(self.store)
        shutil.copytree(source, self.store)

    def txn_lines(self) -> list[dict[str, Any]]:
        """The parsed lines of ``txn.jsonl``."""
        path = self.store / "txn.jsonl"
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def read_json(self, relpath: str) -> dict[str, Any]:
        """A JSON file under the store."""
        data = json.loads((self.store / relpath).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{relpath} is not an object")
        return data

    def dead_pid(self) -> int:
        """The pid of a process that has exited."""
        proc = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603 - fixed argv
        proc.wait()
        return proc.pid

    # -- runners -------------------------------------------------------------------------

    def env(self, **extra: str | None) -> dict[str, str]:
        """The environment of a verb run: the fixture config dir and the fixture seams."""
        env = git_env()
        env.update(
            {
                "CLAUDE_CONFIG_DIR": str(self.config_dir),
                "RUN_PARAMETERS_TEST_LOCK_WAIT_S": "0.2",
                "RUN_PARAMETERS_TEST_CLOCK": FIXTURE_CLOCK,
                "PYTHONPATH": str(self.source),
            }
        )
        env.pop("RUN_PARAMETERS_TEST_CRASH_AT", None)
        for key, value in extra.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def run(
        self,
        *argv: str,
        repo: Path | None = None,
        env: Mapping[str, str | None] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Run ``tools.run_parameters.main`` in-process with ``--repo``; return (exit, JSON)."""
        module = importlib.import_module("tools.run_parameters")
        buffer = io.StringIO()
        with (
            patched_environ(self.env(**dict(env or {}))),
            contextlib.redirect_stdout(buffer),
        ):
            try:
                code = module.main(["--repo", str(repo or self.repo), *argv])
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 2
        return int(code), parse_output(buffer.getvalue())

    def command(self, *argv: str, repo: Path | None = None) -> list[str]:
        """The argv of a ``python -m tools.run_parameters`` subprocess."""
        return [
            sys.executable,
            "-m",
            "tools.run_parameters",
            "--repo",
            str(repo or self.repo),
            *argv,
        ]

    def run_subprocess(
        self,
        *argv: str,
        repo: Path | None = None,
        env: Mapping[str, str | None] | None = None,
        timeout: float = 120,
    ) -> tuple[int, dict[str, Any], str]:
        """Run a verb in a child process; return (exit, JSON, stderr)."""
        proc = subprocess.run(  # noqa: S603 - fixed argv
            self.command(*argv, repo=repo),
            cwd=self.source,
            env=self.env(**dict(env or {})),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
        out = parse_output(proc.stdout) if proc.stdout.strip().startswith("{") else {}
        return proc.returncode, out, proc.stderr

    def spawn(
        self, *argv: str, env: Mapping[str, str | None] | None = None
    ) -> subprocess.Popen[str]:
        """Start a verb in a child process without waiting (the concurrency tests)."""
        return subprocess.Popen(  # noqa: S603 - fixed argv
            self.command(*argv),
            cwd=self.source,
            env=self.env(**dict(env or {})),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def run_python(
        self,
        code: str,
        env: Mapping[str, str | None] | None = None,
        timeout: float = 120,
    ) -> subprocess.CompletedProcess[str]:
        """Run a Python snippet in a child process with the fixture environment."""
        return subprocess.run(  # noqa: S603 - fixed argv
            [sys.executable, "-c", code],
            cwd=self.source,
            env=self.env(**dict(env or {})),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )

    def manifest(self) -> dict[str, Any]:
        """The fixture manifest written to ``<root>/fixture.json``."""
        return {
            "schema": "run-parameters-fixture/1",
            "fixture": True,
            "profile": self.profile,
            "mark": self.mark,
            "repo": display_path(self.repo),
            "config_dir": display_path(self.config_dir),
            "receipts": display_path(self.receipts),
            "session": self.session,
            "plan": self.plan,
            "grouping": self.grouping,
            "transcript": display_path(self.transcript),
            "components": list(self.components),
        }


def _phase_modules() -> list[ModuleType]:
    """Every ``phase_<tag>.py`` module in this folder, in name order."""
    folder = Path(__file__).resolve().parent
    modules: list[ModuleType] = []
    for path in sorted(folder.glob("phase_*.py")):
        if __package__:
            modules.append(importlib.import_module(f"{__package__}.{path.stem}"))
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load fixture phase module {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def build(
    root: Path | str,
    source: Path | str,
    profile: str = "test",
    mark: bool = True,
    repo_name: str = "repo",
) -> Fixture:
    """Build a fixture under ``root`` from the working copy ``source``; see the module docstring."""
    root = Path(root).absolute()
    source = Path(source).absolute()
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILES}")
    check_root(root)
    missing = [
        rel for rel in B2_COMPONENTS if not source_path(source, rel).is_file()
    ]
    root.mkdir(parents=True, exist_ok=True)
    repo = root / repo_name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for key, value in (
        ("user.name", "Fixture"),
        ("user.email", "fixture@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
        ("core.hooksPath", str(root / "no-hooks")),
    ):
        git(repo, "config", key, value)
    fx = Fixture(
        root=root,
        source=source,
        profile=profile,
        mark=mark,
        repo=repo,
        config_dir=root / "claude",
        receipts=root / "receipts",
        session=str(uuid.uuid4()),
    )
    fx.write_text("AGENTS.md", f"{FIXTURE_HEADER}\n\n# Fixture AGENTS.md\n")
    fx.write_text("GUARDRAILS.md", f"{FIXTURE_HEADER}\n\n# Fixture GUARDRAILS.md\n")
    for module in _phase_modules():
        extend = getattr(module, "extend", None)
        if not callable(extend):
            raise ImportError(
                f"fixture phase module {module.__name__} defines no extend(fx)"
            )
        extend(fx)
    missing += [
        rel
        for rel in fx.components
        if rel not in B2_COMPONENTS
        and rel not in GENERATED
        and not source_path(source, rel).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            f"components missing from the working copy {source}: {missing}"
        )
    for rel in fx.components:
        if rel in GENERATED and not source_path(source, rel).is_file():
            continue
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path(source, rel), target)
    fx.add_system("informational")
    fx.add_human("Fixture session start: plan the fixture project.")
    fx.block = fx.present_and_accept()
    fx.write_carrier(fx.block)
    fx.write_carrier(fx.block, plan=PLAN_B, grouping_line=False)
    fx.seal_activation()
    fx.commit("fixture: initial tree")
    if mark:
        fx.set_mark()
    (root / "fixture.json").write_bytes(
        (json.dumps(fx.manifest(), indent=2) + "\n").encode("utf-8")
    )
    return fx


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: build a fixture for a paid row; exit 2 when the root is refused."""
    parser = argparse.ArgumentParser(
        prog="build_fixture", description="Build a run-parameters fixture repository."
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="a new, empty folder outside every git work tree",
    )
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="the working copy whose components are under test",
    )
    parser.add_argument(
        "--profile", required=True, choices=PROFILES, help="the fixture profile"
    )
    args = parser.parse_args(argv)
    try:
        fx = build(args.root, args.source, profile=args.profile)
    except FixtureRootError as exc:
        print(json.dumps({"result": "refused", "reason": str(exc)}))
        return 2
    print(json.dumps(fx.manifest(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
