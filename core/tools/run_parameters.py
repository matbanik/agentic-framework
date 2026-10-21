"""Run-parameters authority: verify, reserve and record the human's run-parameter grants.

Design: the run-parameters plan (B-2, AC-B.1 to AC-B.12).
Report: the run-parameters research report R§4.1 (the verifier V-A to V-11 and the
authority store), R§4.5 step 7 (index reconciliation), R§4.6 (sessions) and R§4.8 (activation).

Usage::

    python -m tools.run_parameters [--repo DIR] verify ACT --plan SLUG [--op OP]
    python -m tools.run_parameters [--repo DIR] reserve ACT --plan SLUG --op OP
    python -m tools.run_parameters [--repo DIR] init (--plan SLUG | --block FILE)
    python -m tools.run_parameters [--repo DIR] inspect (--plan SLUG | --block FILE)
    python -m tools.run_parameters [--repo DIR] status --json [--plan SLUG]
    python -m tools.run_parameters [--repo DIR] bind (--pending SLUG | --plan SLUG) --session ID
    python -m tools.run_parameters [--repo DIR] revoke --session ID --message UUID
    python -m tools.run_parameters [--repo DIR] unlock --expect TOKEN --session ID --message UUID
    python -m tools.run_parameters [--repo DIR] repair [--migrate] --session ID --message UUID
    python -m tools.run_parameters [--repo DIR] repair --final --plan SLUG
    python -m tools.run_parameters [--repo DIR] document --plan SLUG
    python -m tools.run_parameters [--repo DIR] resolve --plan SLUG
    python -m tools.run_parameters [--repo DIR] final --plan SLUG [--produce | --seal]
    python -m tools.run_parameters [--repo DIR] stop --plan SLUG
    python -m tools.run_parameters [--repo DIR] audit [--limit N]

Every verb prints one JSON object on stdout (EA-5). A refusal is
``{"result": "refused", "reason": <code>, "authorized": false, "failure": true}``; ``verify``
and ``reserve`` add ``"effective"`` with the fail-closed values (V-11). ``manual`` and
``legacy`` print ``result`` and ``reason`` equal to the code, ``authorized: false`` and
``failure: false``. Diagnostics go to stderr as one JSON object per line.

Exit codes:

- 0 — success: a verified act, a written transaction, a report.
- 1 — a refusal or a non-authorizing result.
- 2 — a usage error (argparse).
- 97 — an internal error, or a crash seam fired in a marked store.

Test seams (read only in a marked store, ``run-parameters.fixture=true`` in the common config):

- ``RUN_PARAMETERS_TEST_CRASH_AT`` — ``os._exit(97)`` after the named transaction or
  index-reconciliation step (``TXN_STEPS``, ``INDEX_STEPS``).
- ``RUN_PARAMETERS_TEST_LOCK_WAIT_S`` — the writer-lock wait in seconds (default ``LOCK_WAIT_S``).
- ``RUN_PARAMETERS_TEST_CLOCK`` — the clock, ``YYYY-MM-DDTHH:MM:SSZ``.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn, TypeVar, cast

import yaml

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_CRASH = 97

#: R§4.1 :249 — every refusal code, in rule precedence order.
REASON_CODES: tuple[str, ...] = (
    "disabled",
    "unsupported_harness",
    "capability",
    "schema",
    "legacy",
    "manual",
    "transcript_missing",
    "record",
    "chain",
    "no_offer",
    "duplicate_offer",
    "offer_schema",
    "digest",
    "consent",
    "binding",
    "not_granted",
    "scope",
    "store_missing",
    "store_mismatch",
    "store_malformed",
    "txn_pending",
    "stale_lock",
    "history_missing",
    "consumed",
    "revoked",
    "superseded",
    "expired",
)
#: The fourteen entry points (AC-B.3).
RP_VERBS: tuple[str, ...] = (
    "inspect",
    "verify",
    "reserve",
    "bind",
    "document",
    "revoke",
    "init",
    "status",
    "resolve",
    "final",
    "stop",
    "unlock",
    "repair",
    "audit",
)
ACTS: tuple[str, ...] = ("exec_commit", "exec_start", "finalize", "plan_commit")
#: V-6a — the run parameter that enables each act.
ENABLING: dict[str, str] = {
    "plan_commit": "commit_plan",
    "exec_start": "exec_after_plan",
    "exec_commit": "commit_exec",
    "finalize": "commit_exec",
}
#: V-A — the transcript adapter this build reads; any other value is ``unsupported_harness``.
TRANSCRIPT_ADAPTER = "claude-code"

POLICY = ".agent/run-parameters.policy.json"
#: The framework home of the run-parameters schemas, activation evidence and approved
#: governance lines.
RUN_PARAMETERS_HOME = ".agent/run-parameters"
#: The adopter's template folder (ADOPTION-GUIDE ``TEMPLATE_HOME``). A project with an
#: F1/F2 template-home override edits this constant.
TEMPLATE_HOME = ".agent/templates"
EVIDENCE = f"{RUN_PARAMETERS_HOME}/activation-evidence.json"
EVIDENCE_PHASES: tuple[str, ...] = ("b2", "b3", "b4", "b5", "b6", "b8")
EVIDENCE_REQUIRED = frozenset({"receipt", "sha256", "exit_code", "components"})
EVIDENCE_KEYS = EVIDENCE_REQUIRED | {"fixture"}
POLICY_KEYS = frozenset(
    {"policy_version", "components", "rulings", "capabilities", "ask_rules"}
)
CAPABILITY_VALUES = frozenset({"headless", "interactive", "off"})
#: R§4.8 (report :1327-1337) — the components the policy must list by digest (EA-34).
REQUIRED_COMPONENTS: tuple[str, ...] = (
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
    f"{TEMPLATE_HOME}/TASK-TEMPLATE.md",
    f"{TEMPLATE_HOME}/PLAN-TEMPLATE.md",
    ".agent/skills/claude-credits/schemas/credits-run.v1.json",
    ".agent/docs/human-decision-protocol.md",
    ".agent/schemas/reflection.v1.yaml",
    ".claude/settings.json",
    f"{RUN_PARAMETERS_HOME}/schemas/run-parameters-offer.v1.schema.json",
    f"{RUN_PARAMETERS_HOME}/schemas/authorization.v1.schema.json",
    f"{RUN_PARAMETERS_HOME}/governance/01-agents.diff",
    f"{RUN_PARAMETERS_HOME}/governance/02-guardrails.diff",
)
SETTINGS = ".claude/settings.json"
#: The hook that ``.claude/settings.json`` must wire in ``PreToolUse`` for Bash (EA-34).
COMMIT_GATE_HOOK = ".claude/hooks/commit_gate.py"
#: The governance-text validator; loaded from the digest-verified copy in the repository.
POLICY_VALIDATOR = "tools/validate_agent_files.py"
#: The D-20 ruling whose SIGN 3 (b) text is the approved one (row 0 ruled D-20 A; EA-36).
APPROVED_GOVERNANCE_D20 = "A"

STORE_SCHEMA = "run-parameters-store/1"
MARK_KEY = "run-parameters.fixture"
ANCHOR_KEY = "run-parameters.storeUuid"
WITNESS_SEQ_KEY = "run-parameters.witnessSeq"
WITNESS_DIGEST_KEY = "run-parameters.witnessDigest"
#: D-27 — the witness chain starts here; chain_n hashes chain_{n-1}, a newline and intent line n.
CHAIN_0 = "sha256:" + "0" * 64
BASE_INVENTORY: tuple[str, ...] = (
    "store.json",
    "txn.jsonl",
    "revocations.jsonl",
    "grants",
    "sessions",
    WITNESS_SEQ_KEY,
    WITNESS_DIGEST_KEY,
)

LOCK_WAIT_S = 60.0
LOCK_POLL_S = 0.05
#: Log a DEBUG line once a writer has waited 80 % of the limit.
LOCK_DEBUG_S = 48.0
SNAPSHOT_RETRIES = 3
SNAPSHOT_PAUSE_S = 0.1
IO_RETRIES = 50
IO_PAUSE_S = 0.02
MAX_PASSED_OVER = 4

CRASH_ENV = "RUN_PARAMETERS_TEST_CRASH_AT"
LOCK_WAIT_ENV = "RUN_PARAMETERS_TEST_LOCK_WAIT_S"
CLOCK_ENV = "RUN_PARAMETERS_TEST_CLOCK"
TXN_STEPS: tuple[str, ...] = (
    "after_data",
    "after_intent",
    "after_replace_1",
    "after_done",
)
INDEX_STEPS: tuple[str, ...] = (
    "index_lock",
    "index_copy",
    "index_before",
    "index_update",
    "index_after",
    "index_replace",
    "index_unlock",
)

SIGMA_KEYS: tuple[str, ...] = (
    "decisions",
    "commit_plan",
    "exec_after_plan",
    "commit_exec",
    "push",
)
BOOL_KEYS: tuple[str, ...] = ("commit_plan", "exec_after_plan", "commit_exec")
#: V-11 — what every refusal of ``verify`` and ``reserve`` reports as effective.
FAIL_CLOSED: dict[str, Any] = {
    "decisions": "human-all",
    "commit_plan": False,
    "exec_after_plan": False,
    "commit_exec": False,
    "push": "never",
}
#: human-all is tighter than hdp (V-6 inheritance order).
DECISION_RANK: dict[str, int] = {"human-all": 0, "hdp": 1}
OFFER_KEYS: tuple[str, ...] = (
    "schema",
    "project",
    "scope",
    "members",
    "expires",
    "decisions",
    "commit_plan",
    "exec_after_plan",
    "commit_exec",
    "push",
    "grants",
    "standing",
    "supersedes",
    "accept",
)
#: The offer key set of each offer schema. /2 adds ``review_limits``, the six keys of a plan's
#: block, so that a human-typed offer can loosen the repo's review limits (AC-13, AC-14);
#: a /1 offer keeps its fourteen keys and cannot carry it.
OFFER_SCHEMAS: dict[str, tuple[str, ...]] = {
    "run-parameters-offer/1": OFFER_KEYS,
    "run-parameters-offer/2": (*OFFER_KEYS[:-1], "review_limits", "accept"),
}
REVIEW_LIMITS_SCHEMA = "review-limits/1"
REVIEW_LIMITS_KEYS: tuple[str, ...] = (
    "schema",
    "plan_rounds",
    "execution_rounds",
    "plan_tokens",
    "execution_tokens",
    "basis",
)
REVIEW_LIMITS_BASES = frozenset({"repo", "tightened", "loosened"})
#: V-6 — the projection that the offer and the authorization must share.
PI_KEYS: tuple[str, ...] = (
    "project",
    "scope",
    "members",
    "expires",
    "grants",
    "standing",
    "supersedes",
)
ACCEPT_WORDS: tuple[str, ...] = ("proceed", "approved", "yes")
BLOCK_KEYS = frozenset(
    {
        "schema",
        "decisions",
        "commit_plan",
        "exec_after_plan",
        "commit_exec",
        "push",
        "tightened_from",
        "authorization",
    }
)
AUTH_KEYS = frozenset(
    {
        "schema",
        "source",
        "form",
        "project",
        "session",
        "message_uuid",
        "presentation_uuid",
        "offer_digest",
        "date",
        "response",
        "scope",
        "members",
        "expires",
        "grants",
        "standing",
        "supersedes",
    }
)
LEGACY_KEYS = AUTH_KEYS - {"form", "members", "expires"}
TIGHTENED_FROM = frozenset({"none", "grouping", "plan"})
OPEN_STATES = frozenset({"pending", "active"})

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SLUG_RE = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*")
GROUPING_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
PROJECT_RE = re.compile(r"[A-Z]:(/[^/\\]+)+|(/[^/\\]+)+")
BRANCH_RE = re.compile(
    r"(?!none$)(?!/)(?!.*//)(?!.*\.\.)[A-Za-z0-9._/-]+(?<!/)(?<!\.lock)"
)
REL_RE = re.compile(r"(?!/)(?![A-Za-z]:)(?!.*\\)(?!.*(^|/)\.\.(/|$)).+")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
ROOT_RE = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
TOKEN_RE = re.compile(r"[0-9a-f]{32}")
SAFE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
OFFER_LINE_RE = re.compile(r"  ([a-z_][a-z0-9_-]*): (.*)")
FLOW_KEY_RE = re.compile(r"[a-z_][a-z0-9_-]*")
TRAILING_COMMENT_RE = re.compile(r" +#.*")
REVOKE_RE = re.compile(r"revoke run_parameters ([0-9a-f-]{36})")
FOREIGN_SLUG_RE = re.compile(r"[^A-Za-z0-9]")
#: O-1a — a value may not start with a YAML indicator that this grammar does not read.
VALUE_INDICATORS = frozenset("&*!|>%@`")

T = TypeVar("T")


class Refusal(Exception):
    """A verifier or store rule failed; ``reason`` is the stdout code, ``detail`` goes to stderr."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class NonAuthorizing(Exception):
    """V-0 found a ``manual`` or ``legacy`` authorization: no failure, and no grant."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class GitError(RuntimeError):
    """A git command failed."""


def _log(event: str, **fields: object) -> None:
    """One JSON diagnostic line on stderr."""
    sys.stderr.write(
        json.dumps({"event": event, **fields}, sort_keys=True, default=str) + "\n"
    )


# -- git and the repository -----------------------------------------------------------------


def _git_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment without ``GIT_*`` variables (they redirect git), with no prompts or system config."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env.update(extra or {})
    return env


def _git_bytes(
    cwd: Path, *args: str, env: Mapping[str, str] | None = None, check: bool = True
) -> bytes:
    """Run git in ``cwd`` and return its raw stdout; raise ``GitError`` with stderr on failure."""
    proc = subprocess.run(  # noqa: S603 - fixed argv
        ["git", *args],
        cwd=cwd,
        env=_git_env(env),
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed in {cwd}: "
            + proc.stderr.decode("utf-8", errors="replace").strip()
        )
    return proc.stdout


def _git(
    cwd: Path, *args: str, env: Mapping[str, str] | None = None, check: bool = True
) -> str:
    """Run git in ``cwd`` and return its stdout as UTF-8 without the trailing newline."""
    return _git_bytes(cwd, *args, env=env, check=check).decode("utf-8").rstrip("\n")


def _git_feed(
    cwd: Path, data: bytes, *args: str, env: Mapping[str, str] | None = None
) -> str:
    """Run git in ``cwd`` with ``data`` on stdin; return stdout without the trailing newline."""
    proc = subprocess.run(  # noqa: S603 - fixed argv
        ["git", *args],
        cwd=cwd,
        env=_git_env(env),
        input=data,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed in {cwd}: "
            + proc.stderr.decode("utf-8", errors="replace").strip()
        )
    return proc.stdout.decode("utf-8").rstrip("\n")


def display_path(path: Path | str) -> str:
    """P-1's normalization: forward slashes, an upper-case drive letter, no trailing slash."""
    text = str(path).replace("\\", "/").rstrip("/")
    if re.match(r"^[a-z]:", text):
        text = text[0].upper() + text[1:]
    return text


def _read_config(top: Path, common: Path) -> dict[str, str]:
    """Every ``run-parameters.*`` key of the common config, by lower-case name."""
    out = _git(
        top,
        "config",
        "--file",
        str(common / "config"),
        "--get-regexp",
        r"^run-parameters\.",
        check=False,
    )
    values: dict[str, str] = {}
    for line in out.splitlines():
        key, _, value = line.partition(" ")
        if key:
            values[key.lower()] = value
    return values


@dataclass
class Repo:
    """One repository: its top level, its common dir, and the run-parameters keys of its config.

    ``main`` is the main working tree of the common dir (``top`` itself outside a linked
    worktree): a linked worktree reads its own carriers but the main tree's project folder
    and transcripts, since the human typed into the session of the main tree.
    """

    top: Path
    display: str
    common: Path
    main: Path
    main_display: str
    config: dict[str, str] = field(default_factory=lambda: {})

    @property
    def store(self) -> Path:
        """The authority store folder (R§4.1)."""
        return self.common / "run-parameters"

    @property
    def marked(self) -> bool:
        """Whether this is a fixture store (only a marked store reads the test seams)."""
        return self.get(MARK_KEY) == "true"

    def get(self, key: str) -> str | None:
        """A ``run-parameters.*`` config value, or None."""
        return self.config.get(key.lower())

    def refresh(self) -> None:
        """Re-read the config (after a write, and before each snapshot attempt)."""
        self.config = _read_config(self.top, self.common)

    def config_set(self, key: str, value: str) -> None:
        """Write one key to the common config with ``--file``, then re-read the config."""
        _git(self.top, "config", "--file", str(self.common / "config"), key, value)
        self.refresh()


def _open_repo(path: Path) -> Repo:
    """The repository that holds ``path``; a non-repository refuses ``disabled``."""
    try:
        out = _git(
            path,
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--git-common-dir",
        )
    except (GitError, OSError) as exc:
        raise Refusal("disabled", f"not_a_repository: {exc}") from exc
    lines = out.splitlines()
    if len(lines) != 2:
        raise Refusal("disabled", "not_a_repository")
    top, common = Path(lines[0]), Path(lines[1])
    main = _main_tree(top)
    return Repo(
        top=top,
        display=display_path(lines[0]),
        common=common,
        main=main,
        main_display=display_path(main),
        config=_read_config(top, common),
    )


def _main_tree(top: Path) -> Path:
    """The main working tree of ``top``'s repository; ``top`` unless it is a linked worktree.

    A linked worktree has a ``.git`` file; the first ``git worktree list --porcelain`` entry
    is the main tree. A bare main entry has no tree, so ``top`` stands.
    """
    if not (top / ".git").is_file():
        return top
    try:
        out = _git(top, "worktree", "list", "--porcelain")
    except (GitError, OSError) as exc:
        raise Refusal("disabled", f"worktree_list: {exc}") from exc
    first = out.split("\n\n", 1)[0].splitlines()
    if not first or not first[0].startswith("worktree ") or "bare" in first[1:]:
        return top
    return Path(first[0][len("worktree ") :])


# -- seams, the clock and durable file I/O --------------------------------------------------


def _now(repo: Repo | None) -> datetime:
    """The clock: the CLOCK seam in a marked store, else the real UTC time."""
    if repo is not None and repo.marked:
        raw = os.environ.get(CLOCK_ENV)
        if raw:
            if DATE_RE.fullmatch(raw):
                try:
                    return datetime.strptime(raw, TIMESTAMP_FORMAT).replace(tzinfo=UTC)
                except ValueError:
                    pass
            _log("clock_seam_invalid", value=raw)
    return datetime.now(UTC)


def _ts(repo: Repo | None) -> str:
    """The clock as a P-2 date."""
    return _now(repo).strftime(TIMESTAMP_FORMAT)


def _crash(repo: Repo, step: str) -> None:
    """The CRASH seam: in a marked store, exit 97 at once after the named step."""
    if repo.marked and os.environ.get(CRASH_ENV) == step:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(EXIT_CRASH)


def _lock_wait(repo: Repo) -> float:
    """The writer-lock wait: the LOCK_WAIT seam in a marked store, else ``LOCK_WAIT_S``."""
    if repo.marked:
        raw = os.environ.get(LOCK_WAIT_ENV)
        if raw:
            try:
                value = float(raw)
            except ValueError:
                _log("lock_wait_seam_invalid", value=raw)
            else:
                if value >= 0:
                    return value
    return LOCK_WAIT_S


def _retry_io(action: Callable[[], T]) -> T:
    """Run a file action, retrying a Windows sharing violation (PermissionError) briefly."""
    for attempt in range(IO_RETRIES):
        try:
            return action()
        except PermissionError:
            if attempt == IO_RETRIES - 1:
                raise
            time.sleep(IO_PAUSE_S)
    raise PermissionError("unreachable")


def _read_bytes(path: Path) -> bytes | None:
    """A file's bytes, or None when it does not exist."""
    try:
        return _retry_io(path.read_bytes)
    except (FileNotFoundError, NotADirectoryError):
        return None


def _read_text(path: Path) -> str | None:
    """A UTF-8 text file (a BOM is dropped), or None when it does not exist."""
    data = _read_bytes(path)
    if data is None:
        return None
    return data.decode("utf-8-sig", errors="replace")


def _write_durable(path: Path, data: bytes) -> None:
    """Write and fsync a file in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _replace(src: Path, dst: Path) -> None:
    """``os.replace`` with the sharing-violation retry."""
    _retry_io(lambda: os.replace(src, dst))


def _write_atomic(path: Path, data: bytes) -> None:
    """Write a sibling temp file, fsync it, and replace ``path`` with it."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    _write_durable(tmp, data)
    try:
        _replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _append_line(path: Path, line: str) -> None:
    """Append one line and fsync it (a JSONL log)."""

    def append() -> None:
        with path.open("ab") as handle:
            handle.write((line + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())

    _retry_io(append)


def _unlink(path: Path) -> None:
    """Remove a file if it exists, with the sharing-violation retry."""
    _retry_io(lambda: path.unlink(missing_ok=True))


def _rmtree(path: Path) -> None:
    """Remove a folder; a folder that a reader holds open is retried, then left for the next writer."""
    for _attempt in range(IO_RETRIES):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            time.sleep(IO_PAUSE_S)
        except FileNotFoundError:
            return
    _log("rmtree_deferred", path=str(path))


def _sha256(data: bytes) -> str:
    """The hex sha256 of bytes."""
    return hashlib.sha256(data).hexdigest()


def _digest(data: bytes) -> str:
    """``sha256:<hex>`` of bytes."""
    return "sha256:" + _sha256(data)


def _json_bytes(data: object) -> bytes:
    """A store JSON file: sorted keys, two-space indent, one trailing newline."""
    return (
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _json_line(data: object) -> str:
    """A JSONL line (no newline)."""
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _load_json(data: bytes) -> object:
    """Parse JSON bytes; raise ValueError on any defect."""
    return json.loads(data.decode("utf-8"))


# -- typed values (P-1 to P-5) --------------------------------------------------------------


def _match(pattern: re.Pattern[str], value: object) -> bool:
    """``value`` is a string that ``pattern`` matches in full."""
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _is_date(value: object) -> bool:
    """P-2: a calendar-valid ``YYYY-MM-DDTHH:MM:SSZ``."""
    if not _match(DATE_RE, value):
        return False
    try:
        datetime.strptime(cast(str, value), TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True


def _is_day(value: object) -> bool:
    """P-2: a calendar-valid ``YYYY-MM-DD``."""
    if not _match(DAY_RE, value):
        return False
    try:
        datetime.strptime(cast(str, value), "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _is_expires(value: object) -> bool:
    """``none`` or a calendar-valid day."""
    return value == "none" or _is_day(value)


def _is_supersedes(value: object) -> bool:
    """``none`` or a uuid."""
    return value == "none" or _match(UUID_RE, value)


def _is_int(value: object, minimum: int) -> bool:
    """An int (never a bool) of at least ``minimum``."""
    return type(value) is int and value >= minimum


def _scope_ok(value: object) -> bool:
    """P-3/P-4: exactly plan, grouping and branch, each in its normal form."""
    if not isinstance(value, dict):
        return False
    scope = cast(dict[str, object], value)
    if set(scope) != {"plan", "grouping", "branch"}:
        return False
    plan, grouping = scope["plan"], scope["grouping"]
    return (
        (plan == "none" or _match(SLUG_RE, plan))
        and (grouping == "none" or _match(GROUPING_RE, grouping))
        and _match(BRANCH_RE, scope["branch"])
    )


def _members_ok(value: object) -> bool:
    """Plan slugs, byte-sorted and unique."""
    if not isinstance(value, list):
        return False
    members = cast(list[object], value)
    if not all(_match(SLUG_RE, item) for item in members):
        return False
    names = cast(list[str], members)
    return names == sorted(names) and len(set(names)) == len(names)


def _grants_ok(value: object) -> bool:
    """P-5: a non-empty, byte-sorted, unique subset of the four acts."""
    if not isinstance(value, list) or not value:
        return False
    grants = cast(list[object], value)
    if not all(isinstance(item, str) and item in ACTS for item in grants):
        return False
    names = cast(list[str], grants)
    return names == sorted(names) and len(set(names)) == len(names)


def _standing_ok(values: Mapping[str, Any]) -> bool:
    """An invocation grant names one plan; a standing grant names a grouping and members."""
    scope = values["scope"]
    if values["standing"] is False:
        return (
            _match(SLUG_RE, scope["plan"])
            and values["members"] == []
            and values["expires"] == "none"
        )
    return (
        scope["plan"] == "none"
        and scope["grouping"] != "none"
        and len(values["members"]) >= 1
    )


# -- V-0 carriers ---------------------------------------------------------------------------

_BOOL_TAG = "tag:yaml.org,2002:bool"
_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader with no timestamps, only ``true``/``false`` booleans, and no duplicate keys."""

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Any, Any]:  # type: ignore[override]
        """Refuse a key that occurs twice in one mapping (a YAML loader keeps the last)."""
        seen: list[object] = []
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=True)  # pyright: ignore[reportUnknownMemberType]
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark
                )
            seen.append(key)
        return cast(dict[Any, Any], super().construct_mapping(node, deep=deep))  # pyright: ignore[reportUnknownMemberType]


_StrictLoader.yaml_implicit_resolvers = {
    first: [
        (tag, rx) for tag, rx in resolvers if tag not in (_BOOL_TAG, _TIMESTAMP_TAG)
    ]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_StrictLoader.add_implicit_resolver(
    _BOOL_TAG, re.compile(r"^(?:true|false)$"), list("tf")
)


def _strict_yaml(text: str) -> object:
    """Load YAML with ``_StrictLoader``; any defect refuses ``schema``."""
    try:
        return yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as exc:
        raise Refusal("schema", f"yaml: {exc}") from exc


def _frontmatter(text: str) -> dict[str, Any] | None:
    """The leading ``---`` block of a carrier, strictly loaded; None when there is none."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 3)
    if end < 0:
        return None
    data = _strict_yaml(text[4 : end + 1])
    if not isinstance(data, dict):
        raise Refusal("schema", "frontmatter_not_mapping")
    return cast(dict[str, Any], data)


def _check_authorization(value: object) -> str:
    """V-0: ``v1``, ``manual`` or ``legacy`` for an authorization reference; else refuse ``schema``."""
    if not isinstance(value, dict):
        raise Refusal("schema", "authorization_not_mapping")
    auth = cast(dict[str, Any], value)
    schema = auth.get("schema")
    if schema == "manual":
        if set(auth) != {"schema"}:
            raise Refusal("schema", "manual_extra_keys")
        return "manual"
    if schema == "authorization/1-legacy":
        ok = (
            set(auth) == LEGACY_KEYS
            and auth["source"] == "USER_EXPLICIT"
            and _match(PROJECT_RE, auth["project"])
            and all(
                _match(UUID_RE, auth[key])
                for key in ("session", "message_uuid", "presentation_uuid")
            )
            and _match(DIGEST_RE, auth["offer_digest"])
            and _is_date(auth["date"])
            and isinstance(auth["response"], str)
            and bool(auth["response"])
            and auth["scope"] == {"plan": "none", "grouping": "none", "branch": "none"}
            and auth["grants"] == ["ruling"]
            and auth["standing"] is False
            and _is_supersedes(auth["supersedes"])
        )
        if not ok:
            raise Refusal("schema", "legacy_shape")
        return "legacy"
    if schema != "authorization/1" or set(auth) != AUTH_KEYS:
        raise Refusal("schema", "authorization_keys")
    ok = (
        auth["source"] == "USER_EXPLICIT"
        and auth["form"] in ("reply", "self-contained")
        and _match(PROJECT_RE, auth["project"])
        and all(
            _match(UUID_RE, auth[key])
            for key in ("session", "message_uuid", "presentation_uuid")
        )
        and _match(DIGEST_RE, auth["offer_digest"])
        and _is_date(auth["date"])
        and isinstance(auth["response"], str)
        and bool(auth["response"])
        and _scope_ok(auth["scope"])
        and _members_ok(auth["members"])
        and _is_expires(auth["expires"])
        and isinstance(auth["grants"], list)
        and all(isinstance(item, str) for item in cast(list[object], auth["grants"]))
        and isinstance(auth["standing"], bool)
        and _is_supersedes(auth["supersedes"])
    )
    if not ok or not _standing_ok(auth):
        raise Refusal("schema", "authorization_shape")
    return "v1"


def _check_block(value: object) -> str:
    """V-0: the ``run_parameters`` block's exact keys and values; return the authorization kind."""
    if not isinstance(value, dict):
        raise Refusal("schema", "block_not_mapping")
    block = cast(dict[str, Any], value)
    if set(block) != BLOCK_KEYS:
        raise Refusal("schema", "block_keys")
    ok = (
        block["schema"] == "run-parameters/1"
        and isinstance(block["decisions"], str)
        and block["decisions"] in DECISION_RANK
        and all(isinstance(block[key], bool) for key in BOOL_KEYS)
        and block["push"] == "never"
        and isinstance(block["tightened_from"], str)
        and block["tightened_from"] in TIGHTENED_FROM
    )
    if not ok:
        raise Refusal("schema", "block_values")
    return _check_authorization(block["authorization"])


@dataclass
class Carriers:
    """The C2 carriers of one plan: the task.md and implementation-plan.md blocks."""

    plan: str
    task_path: Path
    task_meta: dict[str, Any]
    task_block: dict[str, Any]
    plan_block: dict[str, Any]

    @property
    def auth(self) -> dict[str, Any]:
        """The task block's authorization reference."""
        return cast(dict[str, Any], self.task_block["authorization"])

    @property
    def bound_sessions(self) -> list[str]:
        """The sessions the task records as bound (R§4.6)."""
        return cast(list[str], self.task_meta.get("bound_sessions") or [])


def _plan_dir(repo: Repo, plan: str) -> Path:
    """``docs/execution/plans/<plan>`` of the repository."""
    return repo.top / "docs" / "execution" / "plans" / plan


def _load_carriers(repo: Repo, plan: str) -> Carriers:
    """V-0 over the task block, then the plan block; manual and legacy raise ``NonAuthorizing``."""
    if not SLUG_RE.fullmatch(plan):
        raise Refusal("binding", "plan_slug")
    task_path = _plan_dir(repo, plan) / "task.md"
    text = _read_text(task_path)
    if text is None:
        raise Refusal("binding", "task_missing")
    meta = _frontmatter(text)
    if meta is None or "run_parameters" not in meta:
        raise NonAuthorizing("legacy")
    kind = _check_block(meta["run_parameters"])
    bound = meta.get("bound_sessions", [])
    if not isinstance(bound, list) or not all(
        isinstance(item, str) for item in cast(list[object], bound)
    ):
        raise Refusal("schema", "bound_sessions")
    if "store_seq" in meta and not _is_int(meta["store_seq"], 0):
        raise Refusal("schema", "store_seq")
    if kind != "v1":
        raise NonAuthorizing(kind)
    plan_text = _read_text(_plan_dir(repo, plan) / "implementation-plan.md")
    if plan_text is None:
        raise Refusal("binding", "plan_missing")
    plan_meta = _frontmatter(plan_text)
    if plan_meta is None or "run_parameters" not in plan_meta:
        raise Refusal("binding", "plan_block_missing")
    if _check_block(plan_meta["run_parameters"]) != "v1":
        raise Refusal("binding", "plan_block_kind")
    return Carriers(
        plan=plan,
        task_path=task_path,
        task_meta=meta,
        task_block=cast(dict[str, Any], meta["run_parameters"]),
        plan_block=cast(dict[str, Any], plan_meta["run_parameters"]),
    )


def _load_block_file(path: Path) -> dict[str, Any]:
    """A pre-plan block file ``{run_parameters: {...}}`` (``inspect --block``, ``init --block``)."""
    text = _read_text(path)
    if text is None:
        raise Refusal("schema", "block_file_missing")
    data = _strict_yaml(text)
    if not isinstance(data, dict) or set(cast(dict[str, Any], data)) != {
        "run_parameters"
    }:
        raise Refusal("schema", "block_file_shape")
    block = cast(dict[str, Any], data)["run_parameters"]
    _check_block(block)
    return cast(dict[str, Any], block)


# -- V-1 to V-3 transcript ------------------------------------------------------------------


@dataclass
class Transcript:
    """One session transcript: its raw lines and parsed records, indexed by uuid."""

    path: Path
    raw: list[str]
    records: list[dict[str, Any]]
    by_uuid: dict[str, list[int]]


def _config_dir() -> Path:
    """The Claude Code config folder (``CLAUDE_CONFIG_DIR``, else ``~/.claude``)."""
    raw = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(raw) if raw else Path.home() / ".claude"


def _transcript_path(repo: Repo, session: str) -> Path:
    """``<config>/projects/<slug of the main tree's display path>/<session>.jsonl`` (V-1)."""
    slug = FOREIGN_SLUG_RE.sub("-", repo.main_display)
    return _config_dir() / "projects" / slug / f"{session}.jsonl"


def _load_transcript(repo: Repo, session: str) -> Transcript:
    """V-1: the session's transcript in this project's folder only; missing → ``transcript_missing``."""
    if not SAFE_NAME_RE.fullmatch(session):
        raise Refusal("transcript_missing", "session_name")
    path = _transcript_path(repo, session)
    text = _read_text(path)
    if text is None:
        raise Refusal("transcript_missing", str(path))
    raw: list[str] = []
    records: list[dict[str, Any]] = []
    by_uuid: dict[str, list[int]] = {}
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        typed = cast(dict[str, Any], record)
        index = len(records)
        raw.append(line)
        records.append(typed)
        uid = typed.get("uuid")
        if isinstance(uid, str):
            by_uuid.setdefault(uid, []).append(index)
    return Transcript(path=path, raw=raw, records=records, by_uuid=by_uuid)


def _credits_state() -> ModuleType:
    """``tools/credits_state.py``, the owner of the typed-turn predicates (R§4.1 V-2, EA-62).

    ``tools.credits_state`` from the repository root (``commit_batch.py``, the tests);
    ``credits_state`` when ``tools/`` itself is on ``sys.path`` (``credits_msg.py``).
    """
    try:
        return importlib.import_module("tools.credits_state")
    except ModuleNotFoundError:
        return importlib.import_module("credits_state")


def _review_ledger() -> ModuleType:
    """``tools/review_ledger.py``, the one reader of the review limits and the ledgers (D-13).

    Imported the way ``_credits_state`` is: ``tools.review_ledger`` from the repository root,
    ``review_ledger`` when ``tools/`` is on ``sys.path`` (``begin`` runs this file by path).
    """
    try:
        return importlib.import_module("tools.review_ledger")
    except ModuleNotFoundError:
        return importlib.import_module("review_ledger")


def _is_windows() -> bool:
    """Whether this host is Windows, where the authority runs (a seam for the tests)."""
    return os.name == "nt"


def _typed_record(
    transcript: Transcript, uid: str, session: str
) -> tuple[str, dict[str, Any]]:
    """V-2: ``uid`` names exactly one typed human record of ``session``; else ``record``.

    The record passes ``is_human_entry`` and ``is_typed_turn`` (R§4.1 V-2): a string or
    text-only content, ``origin.kind: human`` and a typed turn, so a task notification or a
    hook frame never counts. V-2's own rejections follow: a sidechain, a parent outside
    the file, a uuid that occurs more than once.
    """
    hits = transcript.by_uuid.get(uid, [])
    if len(hits) != 1:
        raise Refusal("record", "uuid_count")
    record = transcript.records[hits[0]]
    cs = _credits_state()
    parent = record.get("parentUuid")
    ok = (
        cs.is_human_entry(record, session) is True
        and cs.is_typed_turn(record) is True
        and record.get("isSidechain") is False
        and (
            parent is None or (isinstance(parent, str) and parent in transcript.by_uuid)
        )
    )
    if not ok:
        raise Refusal("record", "not_a_typed_human_record")
    return transcript.raw[hits[0]], record


def _human_text(record: Mapping[str, Any]) -> str:
    """The text of a typed human record: its string, or its text blocks joined by a newline."""
    cs = _credits_state()
    text: object = cs.text_blocks(cs.message_content(dict(record)))
    if not isinstance(text, str):
        raise Refusal("record", "not_a_typed_human_record")
    return text


def _assistant_text(record: Mapping[str, Any]) -> str:
    """An assistant record's text blocks, joined with a newline."""
    message = record.get("message")
    content = (
        cast(dict[str, Any], message).get("content")
        if isinstance(message, dict)
        else None
    )
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in cast(list[object], content):
        if isinstance(block, dict):
            typed = cast(dict[str, Any], block)
            if typed.get("type") == "text" and isinstance(typed.get("text"), str):
                parts.append(cast(str, typed["text"]))
    return "\n".join(parts)


def _walk_to_presentation(
    transcript: Transcript, message: Mapping[str, Any], auth: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """V-3R: from the reply up its parents to the presentation; return it and the passed-over uuids."""
    session = auth["session"]
    passed: list[str] = []
    visited = {cast(str, message["uuid"])}
    parent = message.get("parentUuid")
    while True:
        if not isinstance(parent, str):
            raise Refusal("chain", "no_parent")
        hits = transcript.by_uuid.get(parent, [])
        if len(hits) != 1 or parent in visited:
            raise Refusal("chain", "parent_missing_duplicate_or_cycle")
        visited.add(parent)
        record = transcript.records[hits[0]]
        if record.get("sessionId") != session or record.get("isSidechain") is not False:
            raise Refusal("chain", "foreign_record")
        kind = record.get("type")
        if kind == "assistant":
            if parent != auth["presentation_uuid"]:
                raise Refusal("chain", "presentation_not_nearest")
            return record, passed
        if (
            kind == "system" and record.get("subtype") != "compact_boundary"
        ) or kind == "attachment":
            passed.append(parent)
            if len(passed) > MAX_PASSED_OVER:
                raise Refusal("chain", "too_many_passed_over")
            parent = record.get("parentUuid")
            continue
        raise Refusal("chain", f"record_type:{kind}")


# -- O-1 offers -----------------------------------------------------------------------------


def _fenced_blocks(lines: Sequence[str]) -> tuple[list[list[str]], list[str]]:
    """O-1f: column-0 ```` ``` ```` / ```` ```yaml ```` blocks closed by ```` ``` ````; an unclosed block counts."""
    blocks: list[list[str]] = []
    prose: list[str] = []
    current: list[str] | None = None
    for line in lines:
        if current is None:
            if line in ("```", "```yaml"):
                current = []
            else:
                prose.append(line)
        elif line == "```":
            blocks.append(current)
            current = None
        else:
            current.append(line)
    if current is not None:
        blocks.append(current)
    return blocks, prose


def _offer_payload(text: str, *, self_contained: bool) -> list[str]:
    """O-1f and V-3S: the payload lines of the one offer block in ``text``."""
    lines = text.split("\n")
    if self_contained and lines and lines[0].startswith("/"):
        lines = lines[1:]
    blocks, prose = _fenced_blocks(lines)
    offers = [
        block
        for block in blocks
        if block and block[0].startswith("run-parameters-offer")
    ]
    if not offers:
        raise Refusal("no_offer")
    if len(blocks) > 1:
        raise Refusal("duplicate_offer")
    if self_contained and any(line.strip() for line in prose):
        raise Refusal("offer_schema", "self_contained_prose")
    payload = offers[0]
    if any(line.startswith("```") for line in payload):
        raise Refusal("offer_schema", "backtick_line")
    return payload


class _ValueParser:
    """O-1a values on one line: quoted scalars, flow maps, flow lists and plain scalars.

    With ``ints``, a plain scalar of digits is an int (``review_limits``); a quoted one stays
    a string, so ``"3"`` is not a round count.
    """

    def __init__(self, text: str, *, ints: bool = False) -> None:
        self.text = text
        self.pos = 0
        self.ints = ints

    def fail(self, why: str) -> NoReturn:
        """Refuse the value."""
        raise Refusal("offer_schema", f"value: {why}: {self.text!r}")

    def peek(self) -> str:
        """The next character, or ``""`` at the end."""
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def spaces(self) -> None:
        """Skip spaces."""
        while self.peek() == " ":
            self.pos += 1

    def parse(self) -> object:
        """The whole value; only a `` #`` comment may follow it."""
        value = self.value(flow=False)
        rest = self.text[self.pos :]
        if rest and not TRAILING_COMMENT_RE.fullmatch(rest):
            self.fail("trailing text")
        return value

    def value(self, *, flow: bool) -> object:
        """One value at the current position."""
        char = self.peek()
        if not char:
            self.fail("empty")
        if char in VALUE_INDICATORS:
            self.fail("indicator")
        if char == '"':
            return self.double()
        if char == "'":
            return self.single()
        if char == "{":
            return self.mapping()
        if char == "[":
            return self.sequence()
        return self.plain(flow=flow)

    def double(self) -> str:
        """A double-quoted scalar; only ``\\"`` and ``\\\\`` escapes."""
        self.pos += 1
        out: list[str] = []
        while True:
            char = self.peek()
            if not char:
                self.fail("unclosed double quote")
            if char == "\\":
                nxt = self.text[self.pos + 1 : self.pos + 2]
                if nxt not in ('"', "\\"):
                    self.fail("escape")
                out.append(nxt)
                self.pos += 2
                continue
            self.pos += 1
            if char == '"':
                return "".join(out)
            out.append(char)

    def single(self) -> str:
        """A single-quoted scalar; ``''`` is a quote."""
        self.pos += 1
        out: list[str] = []
        while True:
            char = self.peek()
            if not char:
                self.fail("unclosed single quote")
            if char == "'":
                if self.text[self.pos + 1 : self.pos + 2] == "'":
                    out.append("'")
                    self.pos += 2
                    continue
                self.pos += 1
                return "".join(out)
            out.append(char)
            self.pos += 1

    def mapping(self) -> dict[str, object]:
        """A flow map ``{key: value, ...}``; keys are plain names, never repeated."""
        self.pos += 1
        out: dict[str, object] = {}
        self.spaces()
        if self.peek() == "}":
            self.pos += 1
            return out
        while True:
            self.spaces()
            match = FLOW_KEY_RE.match(self.text, self.pos)
            if match is None:
                self.fail("flow key")
            key = match.group(0)
            self.pos = match.end()
            if self.text[self.pos : self.pos + 2] != ": ":
                self.fail("flow key separator")
            self.pos += 2
            self.spaces()
            if key in out:
                self.fail("duplicate flow key")
            out[key] = self.value(flow=True)
            self.spaces()
            char = self.peek()
            self.pos += 1
            if char == "}":
                return out
            if char != ",":
                self.fail("flow map separator")

    def sequence(self) -> list[object]:
        """A flow list ``[a, b]``; ``[]`` is the empty list."""
        self.pos += 1
        out: list[object] = []
        self.spaces()
        if self.peek() == "]":
            self.pos += 1
            return out
        while True:
            self.spaces()
            out.append(self.value(flow=True))
            self.spaces()
            char = self.peek()
            self.pos += 1
            if char == "]":
                return out
            if char != ",":
                self.fail("flow list separator")

    def plain(self, *, flow: bool) -> object:
        """A plain scalar; it ends at `` #`` (and, in a flow, at ``,`` ``]`` ``}``)."""
        start = self.pos
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "#" and self.pos > start and self.text[self.pos - 1] == " ":
                self.pos -= 1
                break
            if flow and char in ",[]{}":
                break
            self.pos += 1
        token = self.text[start : self.pos].rstrip(" ")
        if not token or ": " in token or token.startswith("- ") or token.endswith(":"):
            self.fail("plain scalar")
        if token in ("true", "false"):
            return token == "true"
        if self.ints and token.isascii() and token.isdigit():
            return int(token)
        return token


def _review_limits_ok(value: object) -> bool:
    """The six keys of ``review_limits``: rounds an int >= 1; tokens also ``off``."""
    if not isinstance(value, dict):
        return False
    limits = cast(dict[str, Any], value)
    return (
        set(limits) == set(REVIEW_LIMITS_KEYS)
        and limits["schema"] == REVIEW_LIMITS_SCHEMA
        and all(_is_int(limits[key], 1) for key in ("plan_rounds", "execution_rounds"))
        and all(
            limits[key] == "off" or _is_int(limits[key], 1)
            for key in ("plan_tokens", "execution_tokens")
        )
        and isinstance(limits["basis"], str)
        and limits["basis"] in REVIEW_LIMITS_BASES
    )


def _offer_types_ok(values: Mapping[str, Any]) -> bool:
    """O-1a's typed check of the offer's keys, with the standing conditions."""
    return (
        isinstance(values["schema"], str)
        and values["schema"] in OFFER_SCHEMAS
        and ("review_limits" not in values or _review_limits_ok(values["review_limits"]))
        and _match(PROJECT_RE, values["project"])
        and _scope_ok(values["scope"])
        and _members_ok(values["members"])
        and _is_expires(values["expires"])
        and isinstance(values["decisions"], str)
        and values["decisions"] in DECISION_RANK
        and all(isinstance(values[key], bool) for key in (*BOOL_KEYS, "standing"))
        and values["push"] == "never"
        and _grants_ok(values["grants"])
        and _is_supersedes(values["supersedes"])
        and isinstance(values["accept"], str)
        and values["accept"] in ACCEPT_WORDS
        and _standing_ok(values)
    )


def _parse_offer(payload: Sequence[str]) -> dict[str, Any]:
    """O-1a: the payload grammar (one root, two-space keys, one-line values) and the typed check."""
    if not payload or payload[0] != "run-parameters-offer:":
        raise Refusal("offer_schema", "root")
    values: dict[str, Any] = {}
    for line in payload[1:]:
        if "\t" in line or line != line.rstrip():
            raise Refusal("offer_schema", "whitespace")
        match = OFFER_LINE_RE.fullmatch(line)
        if match is None:
            raise Refusal("offer_schema", f"line: {line!r}")
        key = match.group(1)
        if key in values:
            raise Refusal("offer_schema", f"duplicate key {key}")
        values[key] = _ValueParser(match.group(2), ints=key == "review_limits").parse()
    schema = values.get("schema")
    keys = OFFER_SCHEMAS.get(schema, OFFER_KEYS) if isinstance(schema, str) else OFFER_KEYS
    if set(values) != set(keys):
        raise Refusal("offer_schema", "keys")
    ordered = {key: values[key] for key in keys}
    if not _offer_types_ok(ordered):
        raise Refusal("offer_schema", "types")
    return ordered


def _offer_digest(payload: Sequence[str]) -> str:
    """O-3: sha256 of the payload lines joined with a newline (no trailing newline)."""
    return _digest("\n".join(payload).encode("utf-8"))


@dataclass
class Reference:
    """A verified authorization reference (V-1 to V-5): the offer it accepted and its chain."""

    auth: dict[str, Any]
    offer: dict[str, Any]
    payload: list[str]
    chain: list[str]


def _verify_reference(repo: Repo, auth: dict[str, Any]) -> Reference:
    """V-1 to V-5 and the offer/authorization projection (V-6)."""
    transcript = _load_transcript(repo, auth["session"])
    _raw, message = _typed_record(transcript, auth["message_uuid"], auth["session"])
    reply = _human_text(message)
    if auth["form"] == "reply":
        if auth["presentation_uuid"] == auth["message_uuid"]:
            raise Refusal("chain", "reply_names_itself")
        presentation, passed = _walk_to_presentation(transcript, message, auth)
        payload = _offer_payload(_assistant_text(presentation), self_contained=False)
        chain = [auth["presentation_uuid"], *reversed(passed), auth["message_uuid"]]
    else:
        if auth["presentation_uuid"] != auth["message_uuid"]:
            raise Refusal("chain", "self_contained_presentation")
        payload = _offer_payload(reply, self_contained=True)
        chain = [auth["message_uuid"]]
    offer = _parse_offer(payload)
    if _offer_digest(payload) != auth["offer_digest"]:
        raise Refusal("digest")
    if auth["response"] != reply:
        raise Refusal("consent", "response_not_verbatim")
    if auth["form"] == "reply" and reply.strip() != offer["accept"]:
        raise Refusal("consent", "not_the_accept_word")
    for key in PI_KEYS:
        if offer[key] != auth[key]:
            raise Refusal("binding", f"projection:{key}")
    if not _grants_ok(auth["grants"]):
        raise Refusal("binding", "grants")
    return Reference(auth=auth, offer=offer, payload=list(payload), chain=chain)


# -- V-A activation (R§4.8) -----------------------------------------------------------------


def capabilities_for(d20: str) -> dict[str, str]:
    """The capability matrix that a D-20 ruling allows: A all headless; B commits interactive."""
    if d20 == "A":
        return dict.fromkeys(ACTS, "headless")
    return {
        "exec_commit": "headless",
        "exec_start": "headless",
        "finalize": "interactive",
        "plan_commit": "interactive",
    }


def _policy_shape_ok(value: object) -> bool:
    """The policy's exact keys and types (an int version, hex digests, the four acts)."""
    if not isinstance(value, dict):
        return False
    policy = cast(dict[str, Any], value)
    if set(policy) != POLICY_KEYS:
        return False
    components, rulings = policy["components"], policy["rulings"]
    capabilities, rules = policy["capabilities"], policy["ask_rules"]
    return (
        _is_int(policy["policy_version"], 1)
        and isinstance(components, dict)
        and bool(components)
        and all(
            _match(REL_RE, key) and _match(HEX64_RE, item)
            for key, item in cast(dict[str, object], components).items()
        )
        and isinstance(rulings, dict)
        and set(cast(dict[str, object], rulings)) == {"d19", "d20"}
        and all(
            item in ("A", "B") for item in cast(dict[str, object], rulings).values()
        )
        and isinstance(capabilities, dict)
        and set(cast(dict[str, object], capabilities)) == set(ACTS)
        and all(
            isinstance(item, str) and item in CAPABILITY_VALUES
            for item in cast(dict[str, object], capabilities).values()
        )
        and isinstance(rules, list)
        and all(
            isinstance(item, str) and bool(item) for item in cast(list[object], rules)
        )
        and len(set(cast(list[str], rules))) == len(cast(list[str], rules))
    )


def _evidence_ok(repo: Repo, evidence: object, components: Mapping[str, str]) -> None:
    """The activation evidence: six phases, each a re-hashed exit-0 receipt over these components."""
    if not isinstance(evidence, dict) or set(cast(dict[str, object], evidence)) != set(
        EVIDENCE_PHASES
    ):
        raise Refusal("disabled", "evidence_schema")
    expected = {key: item for key, item in components.items() if key != EVIDENCE}
    for phase in EVIDENCE_PHASES:
        entry = cast(dict[str, object], evidence)[phase]
        if not isinstance(entry, dict):
            raise Refusal("disabled", f"evidence_schema:{phase}")
        typed = cast(dict[str, Any], entry)
        if not EVIDENCE_REQUIRED <= set(typed) <= EVIDENCE_KEYS:
            raise Refusal("disabled", f"evidence_schema:{phase}")
        receipt = typed["receipt"]
        if not isinstance(receipt, str) or not Path(receipt).is_absolute():
            raise Refusal("disabled", f"evidence_receipt:{phase}")
        data = _read_bytes(Path(receipt))
        if data is None or _sha256(data) != typed["sha256"]:
            raise Refusal("disabled", f"evidence_receipt:{phase}")
        if type(typed["exit_code"]) is not int or typed["exit_code"] != 0:
            raise Refusal("disabled", f"evidence_exit:{phase}")
        if typed["components"] != expected:
            raise Refusal("disabled", f"evidence_components:{phase}")
        if "fixture" in typed:
            if typed["fixture"] is not True:
                raise Refusal("disabled", f"evidence_schema:{phase}")
            if not repo.marked:
                raise Refusal("disabled", "fixture_evidence")


def _matches_bash(matcher: object) -> bool:
    """A ``PreToolUse`` matcher that selects the Bash tool (absent, ``""``, ``*`` or a regex)."""
    if matcher is None or matcher in ("", "*"):
        return True
    if not isinstance(matcher, str):
        return False
    try:
        return re.fullmatch(matcher, "Bash") is not None
    except re.error:
        return False


def _hook_wired(settings: Mapping[str, Any]) -> bool:
    """``settings.hooks.PreToolUse`` runs ``commit_gate.py`` as a command hook for Bash."""
    hooks = settings.get("hooks")
    entries = (
        cast(dict[str, Any], hooks).get("PreToolUse")
        if isinstance(hooks, dict)
        else None
    )
    if not isinstance(entries, list):
        return False
    for entry in cast(list[object], entries):
        if not isinstance(entry, dict):
            continue
        typed = cast(dict[str, Any], entry)
        if not _matches_bash(typed.get("matcher")) or not isinstance(
            typed.get("hooks"), list
        ):
            continue
        for hook in cast(list[object], typed["hooks"]):
            if not isinstance(hook, dict):
                continue
            command = cast(dict[str, Any], hook).get("command")
            if (
                cast(dict[str, Any], hook).get("type") == "command"
                and isinstance(command, str)
                and COMMIT_GATE_HOOK in command.replace("\\", "/")
            ):
                return True
    return False


def _ask_rules_ok(settings: Mapping[str, Any], rules: Sequence[str], d19: str) -> bool:
    """D-19 A: the policy's ``ask`` rules are non-empty and all in ``permissions.ask``.

    D-19 B has no approved settings shape, so it fails closed.
    """
    if d19 != "A" or not rules:
        return False
    permissions = settings.get("permissions")
    ask = (
        cast(dict[str, Any], permissions).get("ask")
        if isinstance(permissions, dict)
        else None
    )
    if not isinstance(ask, list):
        return False
    present = {item for item in cast(list[object], ask) if isinstance(item, str)}
    return all(rule in present for rule in rules)


def _governance_failure(top: Path) -> str | None:
    """The first failing check of the policy validator over ``top``, or None when it passes.

    The validator is loaded by path from ``top``, whose bytes the digest loop has verified;
    a validator that cannot be loaded or returns another shape is the failure ``load``.
    The text is checked against ``APPROVED_GOVERNANCE_D20`` whatever the policy's D-20
    ruling (EA-36): a D-20 B matrix is narrower than that text, so it fails safe.
    """
    path = top / POLICY_VALIDATOR
    spec = importlib.util.spec_from_file_location(
        "_run_parameters_policy_validator", path
    )
    if spec is None or spec.loader is None:
        return "load"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        check = getattr(module, "check_run_parameters_policy")
        failures: object = check(top, APPROVED_GOVERNANCE_D20)
    except Exception as exc:
        # Any load or call error leaves the governance text unproven.
        _log("policy_validator_error", detail=f"{type(exc).__name__}: {exc}")
        return "load"
    if not isinstance(failures, list):
        return "load"
    for failure in cast(list[object], failures):
        if isinstance(failure, tuple) and failure and isinstance(failure[0], str):
            return cast(str, failure[0])
        return "load"
    return None


def _activation(repo: Repo) -> dict[str, Any]:
    """V-A: the policy, its component digests, its evidence, its capability matrix, the hook
    settings and the governance text (R§4.8, EA-34)."""
    raw = _read_bytes(repo.top / POLICY)
    if raw is None:
        raise Refusal("disabled", "policy_missing")
    try:
        policy = _load_json(raw)
    except ValueError as exc:
        raise Refusal("disabled", "policy_schema") from exc
    if not _policy_shape_ok(policy):
        raise Refusal("disabled", "policy_schema")
    typed = cast(dict[str, Any], policy)
    components = cast(dict[str, str], typed["components"])
    if EVIDENCE not in components:
        raise Refusal("disabled", "policy_schema")
    for rel in sorted(components):
        data = _read_bytes(repo.top / rel)
        if data is None or _sha256(data) != components[rel]:
            raise Refusal("disabled", f"component_drift:{rel}")
    for rel in REQUIRED_COMPONENTS:
        if rel not in components:
            raise Refusal("disabled", f"component_missing:{rel}")
    evidence_raw = _read_bytes(repo.top / EVIDENCE)
    try:
        evidence = _load_json(evidence_raw or b"")
    except ValueError as exc:
        raise Refusal("disabled", "evidence_schema") from exc
    _evidence_ok(repo, evidence, components)
    rulings = cast(dict[str, str], typed["rulings"])
    allowed = capabilities_for(rulings["d20"])
    for act, value in cast(dict[str, str], typed["capabilities"]).items():
        if value not in (allowed[act], "off"):
            raise Refusal("disabled", "capability_matrix")
    try:
        settings = _load_json(_read_bytes(repo.top / SETTINGS) or b"")
    except ValueError as exc:
        raise Refusal("disabled", "hook_wiring") from exc
    if not isinstance(settings, dict) or not _hook_wired(
        cast(dict[str, Any], settings)
    ):
        raise Refusal("disabled", "hook_wiring")
    rules = cast(list[str], typed["ask_rules"])
    if not _ask_rules_ok(cast(dict[str, Any], settings), rules, rulings["d19"]):
        raise Refusal("disabled", "ask_rules")
    governance = _governance_failure(repo.top)
    if governance is not None:
        raise Refusal("disabled", f"governance_text:{governance}")
    return typed


def _gate(repo: Repo, act: str | None) -> dict[str, Any]:
    """V-A, then the adapter, then (for an act) its capability."""
    policy = _activation(repo)
    if TRANSCRIPT_ADAPTER != "claude-code":
        raise Refusal("unsupported_harness", TRANSCRIPT_ADAPTER)
    if act is not None and cast(dict[str, str], policy["capabilities"])[act] == "off":
        raise Refusal("capability", act)
    return policy


# -- V-6 inheritance, V-6a act, V-7 scope ---------------------------------------------------


def _sigma(values: Mapping[str, Any]) -> dict[str, Any]:
    """The five run parameters of a carrier or an offer."""
    return {key: values[key] for key in SIGMA_KEYS}


def _within(low: Mapping[str, Any], high: Mapping[str, Any]) -> bool:
    """``low`` is as tight as ``high`` or tighter (human-all < hdp, false < true)."""
    if DECISION_RANK[low["decisions"]] > DECISION_RANK[high["decisions"]]:
        return False
    return all(high[key] or not low[key] for key in BOOL_KEYS)


def _grouping_path(repo: Repo, grouping: str) -> Path:
    """``.agent/context/grouping/<grouping>.md``."""
    return repo.top / ".agent" / "context" / "grouping" / f"{grouping}.md"


def _grouping_sigma(
    repo: Repo, plan: str, auth: Mapping[str, Any]
) -> dict[str, Any] | None:
    """C1: the plan's ``Run parameters:`` line in its grouping section, or None when there is none."""
    grouping = cast(str, auth["scope"]["grouping"])
    if grouping == "none":
        return None
    text = _read_text(_grouping_path(repo, grouping))
    if text is None:
        return None
    return grouping_line_sigma(text, plan, auth)


def grouping_line_sigma(
    text: str, plan: str, auth: Mapping[str, Any]
) -> dict[str, Any] | None:
    """The run parameters of ``plan``'s ``Run parameters:`` line in a grouping file's text, or None."""
    heading = re.compile(rf"### Session \S+ — {re.escape(plan)}")
    inside = False
    found: str | None = None
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith("#"):
            if inside:
                break
            inside = heading.fullmatch(line) is not None
            continue
        if inside and line.startswith("Run parameters:"):
            if found is not None:
                raise Refusal("binding", "grouping_line_twice")
            found = line
    if found is None:
        return None
    pairs: dict[str, str] = {}
    for part in found[len("Run parameters:") :].strip().split(" · "):
        key, sep, value = part.partition("=")
        if not sep or key in pairs:
            raise Refusal("binding", "grouping_line_shape")
        pairs[key] = value
    if set(pairs) != {*SIGMA_KEYS, "authorization"}:
        raise Refusal("binding", "grouping_line_keys")
    if pairs["authorization"] != f"{str(auth['session'])[:8]}/{auth['message_uuid']}":
        raise Refusal("binding", "grouping_line_reference")
    if pairs["decisions"] not in DECISION_RANK or pairs["push"] != "never":
        raise Refusal("binding", "grouping_line_values")
    sigma: dict[str, Any] = {"decisions": pairs["decisions"], "push": "never"}
    for key in BOOL_KEYS:
        if pairs[key] not in ("true", "false"):
            raise Refusal("binding", "grouping_line_values")
        sigma[key] = pairs[key] == "true"
    return sigma


def _inherit(
    carriers: Carriers, offer: Mapping[str, Any], grouping: dict[str, Any] | None
) -> dict[str, Any]:
    """V-6: each carrier is within the offer and within the carrier above it; return Σtask."""
    if carriers.plan_block["authorization"] != carriers.auth:
        raise Refusal("binding", "plan_authorization")
    offered = _sigma(offer)
    plan = _sigma(carriers.plan_block)
    task = _sigma(carriers.task_block)
    present: dict[str, dict[str, Any]] = {"plan": plan}
    if grouping is not None:
        present["grouping"] = grouping
        if grouping != offered:
            raise Refusal("binding", "grouping_differs")
    for name, sigma in present.items():
        if not _within(sigma, offered):
            raise Refusal("binding", f"loosened:{name}")
    if not _within(task, offered) or not _within(task, plan):
        raise Refusal("binding", "loosened:task")
    if grouping is not None and not _within(plan, grouping):
        raise Refusal("binding", "loosened:plan")

    def recorded(
        name: str,
        sigma: Mapping[str, Any],
        block: Mapping[str, Any],
        above: tuple[str, ...],
    ) -> None:
        """A carrier that differs from the offer names a present carrier above it that equals it."""
        if sigma == offered:
            return
        source = block["tightened_from"]
        if source not in above or present.get(source) != offered:
            raise Refusal("binding", f"unrecorded_tightening:{name}")

    recorded("plan", plan, carriers.plan_block, ("grouping",))
    recorded("task", task, carriers.task_block, ("grouping", "plan"))
    return task


def _check_act(auth: Mapping[str, Any], act: str, effective: Mapping[str, Any]) -> None:
    """V-6a: the act is granted and its enabling parameter is true."""
    if act not in auth["grants"] or not effective[ENABLING[act]]:
        raise Refusal("not_granted", act)


def _check_scope(repo: Repo, auth: Mapping[str, Any], plan: str) -> None:
    """V-7: the plan is in scope, the project is the main tree, and the branch exists by bytes."""
    if auth["standing"]:
        in_scope = plan in auth["members"]
    else:
        in_scope = plan == auth["scope"]["plan"]
    if not in_scope:
        raise Refusal("scope", "plan")
    try:
        same = os.path.samefile(auth["project"], repo.main)
    except OSError:
        same = False
    if not same:
        raise Refusal("scope", "project")
    refs = _git_bytes(
        repo.top, "for-each-ref", "--format=%(refname)", "refs/heads/"
    ).split(b"\n")
    if ("refs/heads/" + cast(str, auth["scope"]["branch"])).encode("utf-8") not in refs:
        raise Refusal("scope", "branch")


@dataclass
class Verified:
    """The outcome of V-0 to V-7 for one plan."""

    plan: str
    reference: Reference
    effective: dict[str, Any]
    carriers: Carriers | None

    @property
    def mu(self) -> str:
        """The accepting message's uuid (the grant id)."""
        return cast(str, self.reference.auth["message_uuid"])


def _verify_plan(repo: Repo, plan: str, act: str | None) -> Verified:
    """V-0 to V-7 over the plan's carriers."""
    carriers = _load_carriers(repo, plan)
    reference = _verify_reference(repo, carriers.auth)
    grouping = _grouping_sigma(repo, plan, carriers.auth)
    effective = _inherit(carriers, reference.offer, grouping)
    if act is not None:
        _check_act(reference.auth, act, effective)
    _check_scope(repo, reference.auth, plan)
    return Verified(
        plan=plan, reference=reference, effective=effective, carriers=carriers
    )


def _verify_block(repo: Repo, block: dict[str, Any]) -> Verified:
    """V-0 to V-7 for a pre-plan block file: the offer is the only carrier."""
    kind = _check_block(block)
    if kind != "v1":
        raise NonAuthorizing(kind)
    auth = cast(dict[str, Any], block["authorization"])
    reference = _verify_reference(repo, auth)
    if not _within(_sigma(block), reference.offer):
        raise Refusal("binding", "loosened:block")
    plan = auth["scope"]["plan"]
    if auth["standing"]:
        plan = auth["members"][0]
    _check_scope(repo, auth, plan)
    return Verified(
        plan=plan, reference=reference, effective=_sigma(block), carriers=None
    )


# -- V-8 to V-10 the authority store --------------------------------------------------------


def _store_json_ok(value: object) -> bool:
    """store.json: the exact store schema."""
    if not isinstance(value, dict):
        return False
    meta = cast(dict[str, Any], value)
    if (
        set(meta) != {"schema", "repo_id", "inventory", "created"}
        or meta["schema"] != STORE_SCHEMA
    ):
        return False
    repo_id, inventory = meta["repo_id"], meta["inventory"]
    if not isinstance(repo_id, dict) or set(cast(dict[str, object], repo_id)) != {
        "roots",
        "common_dir",
        "store_uuid",
    }:
        return False
    ident = cast(dict[str, Any], repo_id)
    roots = ident["roots"]
    return (
        isinstance(roots, list)
        and bool(roots)
        and all(_match(ROOT_RE, item) for item in cast(list[object], roots))
        and len(set(cast(list[str], roots))) == len(cast(list[str], roots))
        and _match(PROJECT_RE, ident["common_dir"])
        and _match(UUID_RE, ident["store_uuid"])
        and isinstance(inventory, list)
        and bool(inventory)
        and all(_match(REL_RE, item) for item in cast(list[object], inventory))
        and len(set(cast(list[str], inventory))) == len(cast(list[str], inventory))
        and _is_date(meta["created"])
    )


def _txn_line_ok(value: object) -> bool:
    """One txn.jsonl line: an intent or a done record."""
    if not isinstance(value, dict):
        return False
    line = cast(dict[str, Any], value)
    if not (
        _is_int(line.get("seq"), 1)
        and _match(UUID_RE, line.get("txn"))
        and _is_date(line.get("ts"))
    ):
        return False
    if set(line) == {"seq", "txn", "done", "ts"}:
        return line["done"] is True
    if (
        set(line) != {"seq", "txn", "intent", "files", "ts"}
        or line["intent"] is not True
    ):
        return False
    files = line["files"]
    if not isinstance(files, list) or not files:
        return False
    for item in cast(list[object], files):
        if not isinstance(item, dict) or set(cast(dict[str, object], item)) != {
            "path",
            "digest",
        }:
            return False
        entry = cast(dict[str, object], item)
        if not (_match(REL_RE, entry["path"]) and _match(DIGEST_RE, entry["digest"])):
            return False
    return True


def _revocation_ok(value: object) -> bool:
    """One revocations.jsonl line."""
    if not isinstance(value, dict):
        return False
    line = cast(dict[str, Any], value)
    return (
        set(line)
        == {"revoked", "by_session", "by_message_uuid", "record_digest", "ts", "seq"}
        and _match(UUID_RE, line["revoked"])
        and isinstance(line["by_session"], str)
        and bool(line["by_session"])
        and _match(UUID_RE, line["by_message_uuid"])
        and _match(DIGEST_RE, line["record_digest"])
        and _is_date(line["ts"])
        and _is_int(line["seq"], 1)
    )


def _reservation_ok(value: object) -> bool:
    """One consumed entry ``{op_id, state, ts, seq}``."""
    if not isinstance(value, dict):
        return False
    entry = cast(dict[str, Any], value)
    return (
        set(entry) == {"op_id", "state", "ts", "seq"}
        and isinstance(entry["op_id"], str)
        and bool(entry["op_id"])
        and entry["state"] == "reserved"
        and _is_date(entry["ts"])
        and _is_int(entry["seq"], 1)
    )


def _grant_ok(value: object, stem: str) -> bool:
    """grants/<message_uuid>.json."""
    if not isinstance(value, dict):
        return False
    grant = cast(dict[str, Any], value)
    if set(grant) != {
        "message_uuid",
        "offer",
        "offer_digest",
        "chain",
        "consumed",
        "superseded_by",
    }:
        return False
    chain, consumed = grant["chain"], grant["consumed"]
    if not (
        grant["message_uuid"] == stem
        and _match(UUID_RE, stem)
        and isinstance(grant["offer"], dict)
        and _match(DIGEST_RE, grant["offer_digest"])
        and isinstance(chain, list)
        and bool(chain)
        and all(_match(UUID_RE, item) for item in cast(list[object], chain))
        and _is_supersedes(grant["superseded_by"])
        and isinstance(consumed, dict)
    ):
        return False
    for plan, acts in cast(dict[str, object], consumed).items():
        if not _match(SLUG_RE, plan) or not isinstance(acts, dict):
            return False
        for act, entry in cast(dict[str, object], acts).items():
            if act not in ACTS or not _reservation_ok(entry):
                return False
    return True


def _session_ok(value: object, stem: str) -> bool:
    """sessions/<session>.json."""
    if not isinstance(value, dict):
        return False
    record = cast(dict[str, Any], value)
    if (
        set(record) != {"session", "context", "plans", "store_seq"}
        or record["session"] != stem
    ):
        return False
    plans = record["plans"]
    if record["context"] not in ("headless", "interactive") or not _is_int(
        record["store_seq"], 0
    ):
        return False
    if not isinstance(plans, list):
        return False
    for item in cast(list[object], plans):
        if not isinstance(item, dict) or set(cast(dict[str, object], item)) != {
            "plan",
            "state",
            "ts",
        }:
            return False
        entry = cast(dict[str, Any], item)
        if not (
            _match(SLUG_RE, entry["plan"])
            and entry["state"] in ("pending", "active", "closed", "handed_over")
            and _is_date(entry["ts"])
        ):
            return False
    return True


def _final_ok(value: object, plan: str, n: int) -> bool:
    """A final receipt, minimally: its plan, its generation and a boolean ``sealed``."""
    if not isinstance(value, dict):
        return False
    receipt = cast(dict[str, Any], value)
    return (
        receipt.get("schema") == "final-receipt/1"
        and receipt.get("plan") == plan
        and receipt.get("generation") == n
        and isinstance(receipt.get("sealed"), bool)
    )


#: The side records of a final folder: ``<n>.failed.json`` (a refused produce, kept as
#: evidence only) and ``<n>.repair.json`` (the human-granted opening of generation n).
FINAL_SIDE_RE = re.compile(r"(\d+)\.(failed|repair)")


def _final_repair_ok(value: object, plan: str, n: int) -> bool:
    """A repair record: generation ``n`` of ``plan`` opened after the sealed ``n - 1``."""
    if not isinstance(value, dict):
        return False
    record = cast(dict[str, Any], value)
    return (
        set(record)
        == {"schema", "plan", "generation", "predecessor", "grant", "superseded", "ts"}
        and record["schema"] == "final-repair/1"
        and record["plan"] == plan
        and n >= 2
        and record["generation"] == n
        and record["predecessor"] == n - 1
        and _match(UUID_RE, record["grant"])
        and _match(UUID_RE, record["superseded"])
        and _is_date(record["ts"])
    )


@dataclass
class TxnLog:
    """txn.jsonl parsed: every line, the intents by txn id, and the done txn ids."""

    raw: bytes
    lines: list[dict[str, Any]]
    intents: dict[str, tuple[dict[str, Any], str]]
    done: set[str]

    @property
    def next_seq(self) -> int:
        """The next transaction's seq."""
        return max((int(line["seq"]) for line in self.lines), default=0) + 1

    @property
    def seq(self) -> int:
        """The store seq: the highest seq of a done transaction."""
        return max((int(self.intents[txn][0]["seq"]) for txn in self.done), default=0)

    def pending(self) -> list[tuple[dict[str, Any], str]]:
        """The intents with no done line, in seq order."""
        items = [entry for txn, entry in self.intents.items() if txn not in self.done]
        return sorted(items, key=lambda entry: int(entry[0]["seq"]))

    def done_entries(self) -> list[tuple[int, str]]:
        """``(seq, raw intent line)`` of every done transaction."""
        return [
            (int(self.intents[txn][0]["seq"]), self.intents[txn][1])
            for txn in self.done
        ]


def _parse_jsonl(
    data: bytes, what: str, check: Callable[[object], bool]
) -> list[tuple[dict[str, Any], str]]:
    """Parse a JSONL log: every line complete and valid, or refuse ``store_malformed``."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal("store_malformed", f"{what}:encoding") from exc
    if text and not text.endswith("\n"):
        raise Refusal("store_malformed", f"{what}:partial_line")
    out: list[tuple[dict[str, Any], str]] = []
    for raw in text.split("\n")[:-1] if text else []:
        try:
            value = json.loads(raw)
        except ValueError as exc:
            raise Refusal("store_malformed", f"{what}:line") from exc
        if not check(value):
            raise Refusal("store_malformed", f"{what}:schema")
        out.append((cast(dict[str, Any], value), raw))
    return out


def _txn_log(root: Path) -> TxnLog:
    """txn.jsonl parsed and cross-checked (a done line names an intent of the same seq)."""
    data = _read_bytes(root / "txn.jsonl") or b""
    lines = _parse_jsonl(data, "txn.jsonl", _txn_line_ok)
    intents: dict[str, tuple[dict[str, Any], str]] = {}
    done: set[str] = set()
    for line, raw in lines:
        txn = cast(str, line["txn"])
        if line.get("intent"):
            if txn in intents:
                raise Refusal("store_malformed", "txn.jsonl:duplicate_intent")
            intents[txn] = (line, raw)
        else:
            if (
                txn not in intents
                or txn in done
                or intents[txn][0]["seq"] != line["seq"]
            ):
                raise Refusal("store_malformed", "txn.jsonl:orphan_done")
            done.add(txn)
    return TxnLog(
        raw=data, lines=[line for line, _ in lines], intents=intents, done=done
    )


def _check_txn_data(root: Path, intent: Mapping[str, Any]) -> None:
    """A pending transaction's data files exist and match the intent's digests."""
    base = root / "txn" / cast(str, intent["txn"]) / "data"
    for item in cast(list[dict[str, str]], intent["files"]):
        data = _read_bytes(base / item["path"])
        if data is None or _digest(data) != item["digest"]:
            raise Refusal("store_malformed", f"txn_data:{item['path']}")


def _chain(entries: Sequence[tuple[int, str]]) -> str:
    """D-27: chain_n = sha256(chain_{n-1} + newline + intent line n), over the done seqs in order."""
    digest = CHAIN_0
    for _seq, raw in sorted(entries):
        digest = _digest((digest + "\n" + raw).encode("utf-8"))
    return digest


@dataclass
class Store:
    """One consistent read of the authority store."""

    root: Path
    meta: dict[str, Any]
    log: TxnLog
    revocations: list[dict[str, Any]]
    grants: dict[str, dict[str, Any]]
    sessions: dict[str, dict[str, Any]]
    finals: dict[str, list[tuple[int, dict[str, Any]]]]
    repairs: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)

    @property
    def inventory(self) -> list[str]:
        """The store's required files, folders and witness keys."""
        return cast(list[str], self.meta["inventory"])


def _identity(repo: Repo) -> dict[str, Any]:
    """V-8 store_missing and store_mismatch; return store.json."""
    root = repo.store
    if not root.is_dir():
        raise Refusal("store_missing", "no_folder")
    raw = _read_bytes(root / "store.json")
    if raw is None:
        raise Refusal("store_missing", "no_store_json")
    anchor = repo.get(ANCHOR_KEY)
    if not anchor:
        raise Refusal("store_missing", "no_anchor")
    try:
        meta = _load_json(raw)
    except ValueError as exc:
        raise Refusal("store_malformed", "store.json") from exc
    if not _store_json_ok(meta):
        raise Refusal("store_malformed", "store.json:schema")
    typed = cast(dict[str, Any], meta)
    ident = cast(dict[str, Any], typed["repo_id"])
    roots = set(
        _git(repo.top, "rev-list", "--max-parents=0", "--all", check=False).split()
    )
    if not set(cast(list[str], ident["roots"])) <= roots:
        raise Refusal("store_mismatch", "roots")
    try:
        same = os.path.samefile(ident["common_dir"], repo.common)
    except OSError:
        same = False
    if not same:
        raise Refusal("store_mismatch", "common_dir")
    if anchor != ident["store_uuid"]:
        raise Refusal("store_mismatch", "anchor")
    return typed


def _json_files(folder: Path) -> list[tuple[str, bytes]]:
    """``(stem, bytes)`` of every ``*.json`` file in a folder, sorted by name."""
    if not folder.is_dir():
        return []
    out: list[tuple[str, bytes]] = []
    for path in sorted(folder.glob("*.json")):
        data = _read_bytes(path)
        if data is not None:
            out.append((path.stem, data))
    return out


def _load_store(repo: Repo) -> Store:
    """V-8 store_missing, store_mismatch and store_malformed, in that order."""
    meta = _identity(repo)
    root = repo.store
    log = _txn_log(root)
    revocations = [
        line
        for line, _ in _parse_jsonl(
            _read_bytes(root / "revocations.jsonl") or b"",
            "revocations.jsonl",
            _revocation_ok,
        )
    ]
    grants: dict[str, dict[str, Any]] = {}
    for stem, data in _json_files(root / "grants"):
        try:
            grant = _load_json(data)
        except ValueError as exc:
            raise Refusal("store_malformed", f"grant:{stem}") from exc
        if not _grant_ok(grant, stem):
            raise Refusal("store_malformed", f"grant:{stem}")
        grants[stem] = cast(dict[str, Any], grant)
    sessions: dict[str, dict[str, Any]] = {}
    for stem, data in _json_files(root / "sessions"):
        try:
            record = _load_json(data)
        except ValueError as exc:
            raise Refusal("store_malformed", f"session:{stem}") from exc
        if not _session_ok(record, stem):
            raise Refusal("store_malformed", f"session:{stem}")
        sessions[stem] = cast(dict[str, Any], record)
    finals: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    repairs: dict[str, dict[int, dict[str, Any]]] = {}
    final_root = root / "final"
    if final_root.is_dir():
        for folder in sorted(path for path in final_root.iterdir() if path.is_dir()):
            for stem, data in _json_files(folder):
                side = FINAL_SIDE_RE.fullmatch(stem)
                if side is not None and side.group(2) == "failed":
                    continue
                if side is not None:
                    try:
                        record = _load_json(data)
                    except ValueError as exc:
                        raise Refusal(
                            "store_malformed", f"final:{folder.name}/{stem}"
                        ) from exc
                    n = int(side.group(1))
                    if not _final_repair_ok(record, folder.name, n):
                        raise Refusal("store_malformed", f"final:{folder.name}/{stem}")
                    repairs.setdefault(folder.name, {})[n] = cast(
                        dict[str, Any], record
                    )
                    continue
                if not stem.isdigit():
                    raise Refusal("store_malformed", f"final:{folder.name}/{stem}")
                try:
                    receipt = _load_json(data)
                except ValueError as exc:
                    raise Refusal(
                        "store_malformed", f"final:{folder.name}/{stem}"
                    ) from exc
                if not _final_ok(receipt, folder.name, int(stem)):
                    raise Refusal("store_malformed", f"final:{folder.name}/{stem}")
                finals.setdefault(folder.name, []).append(
                    (int(stem), cast(dict[str, Any], receipt))
                )
    for intent, _raw in log.pending():
        _check_txn_data(root, intent)
    return Store(
        root=root,
        meta=meta,
        log=log,
        revocations=revocations,
        grants=grants,
        sessions=sessions,
        finals=finals,
        repairs=repairs,
    )


def _check_history(
    repo: Repo, store: Store, verified: Verified | None, *, check_grant: bool
) -> dict[str, Any] | None:
    """V-8 history_missing: the inventory, the witness, the task's store seq, sessions and the grant."""
    for item in store.inventory:
        if item.startswith("run-parameters."):
            if repo.get(item) is None:
                raise Refusal("history_missing", f"config:{item}")
        elif not (store.root / item).exists():
            raise Refusal("history_missing", f"inventory:{item}")
    if repo.get(WITNESS_SEQ_KEY) != str(store.log.seq):
        raise Refusal("history_missing", "witness_seq")
    if repo.get(WITNESS_DIGEST_KEY) != _chain(store.log.done_entries()):
        raise Refusal("history_missing", "witness_digest")
    if verified is None:
        return None
    carriers = verified.carriers
    if carriers is not None:
        if int(carriers.task_meta.get("store_seq", 0)) > store.log.seq:
            raise Refusal("history_missing", "task_store_seq")
        for session in carriers.bound_sessions:
            if session not in store.sessions:
                raise Refusal("history_missing", f"session:{session}")
    grant = store.grants.get(verified.mu)
    if check_grant:
        if grant is None:
            raise Refusal("history_missing", "grant")
        if (
            grant["offer"] != verified.reference.offer
            or grant["offer_digest"] != verified.reference.auth["offer_digest"]
        ):
            raise Refusal("history_missing", "grant_offer")
    return grant


def _check_consumed(
    grant: Mapping[str, Any] | None, plan: str, act: str | None, op: str | None
) -> None:
    """V-8 consumed: another op (or no op) for an act this plan already reserved."""
    if grant is None or act is None:
        return
    entry = cast(dict[str, Any], grant["consumed"]).get(plan, {}).get(act)
    if entry is not None and (op is None or entry["op_id"] != op):
        raise Refusal("consumed", f"{plan}:{act}")


def _open_repair(store: Store, plan: str) -> dict[str, Any] | None:
    """The newest repair record whose generation has no sealed receipt yet, or None."""
    sealed = {
        n for n, receipt in store.finals.get(plan, []) if receipt["sealed"] is True
    }
    records = store.repairs.get(plan, {})
    opened = [n for n in records if n not in sealed]
    return records[max(opened)] if opened else None


def _finalize_superseder(store: Store, verified: Verified) -> bool:
    """The reference grants ``finalize`` and supersedes a grant the store holds."""
    auth = verified.reference.auth
    return "finalize" in auth["grants"] and auth["supersedes"] in store.grants


def _check_live(
    repo: Repo,
    store: Store,
    verified: Verified,
    grant: Mapping[str, Any] | None,
    *,
    repair: bool = False,
    finalize: bool = False,
) -> None:
    """V-9 revoked and superseded; V-10 expired (a sealed generation, or a standing date).

    ``repair`` is the final-receipt path (``init`` of a superseding ``finalize`` grant,
    ``final --produce`` and ``--seal``): an open repair record that names this grant lifts
    the superseded and sealed checks, and a ``finalize`` superseder may be recorded after the
    seal. ``finalize`` is a ``finalize`` op (``verify``, ``reserve``, the commit's reserved
    check): an open repair record lifts the sealed check for its new grant only, so the
    repaired generation can publish; the grant it supersedes stays superseded. Revocation
    and the standing date still apply.
    """
    mu = verified.mu
    if any(line["revoked"] == mu for line in store.revocations):
        raise Refusal("revoked", mu)
    opened = _open_repair(store, verified.plan) if repair or finalize else None
    if repair:
        named = opened is not None and mu in (opened["grant"], opened["superseded"])
    else:
        named = opened is not None and mu == opened["grant"]
    if grant is not None and grant["superseded_by"] != "none" and not named:
        raise Refusal("superseded", cast(str, grant["superseded_by"]))
    finals = store.finals.get(verified.plan, [])
    if (
        finals
        and max(finals, key=lambda item: item[0])[1]["sealed"] is True
        and not named
        and not (repair and _finalize_superseder(store, verified))
    ):
        raise Refusal("expired", "sealed_generation")
    auth = verified.reference.auth
    if auth["standing"] and auth["expires"] != "none":
        end = datetime.strptime(
            f"{auth['expires']}T23:59:59Z", TIMESTAMP_FORMAT
        ).replace(tzinfo=UTC)
        if _now(repo) > end:
            raise Refusal("expired", "standing_date")


def _store_checks(
    repo: Repo,
    verified: Verified,
    *,
    act: str | None,
    op: str | None,
    reader: bool,
    check_grant: bool = True,
    check_consumed: bool = True,
    repair: bool = False,
) -> tuple[Store, dict[str, Any] | None]:
    """V-8 to V-10 over one read of the store (a reader also refuses a pending transaction)."""
    store = _load_store(repo)
    if reader and store.log.pending():
        raise Refusal("txn_pending")
    grant = _check_history(repo, store, verified, check_grant=check_grant)
    if check_consumed:
        _check_consumed(grant, verified.plan, act, op)
    _check_live(repo, store, verified, grant, repair=repair, finalize=act == "finalize")
    return store, grant


def _snapshot(repo: Repo, read: Callable[[], T]) -> T:
    """A reader's consistent snapshot: txn.jsonl unchanged across the read, retried on a race."""
    log_path = repo.store / "txn.jsonl"
    for attempt in range(SNAPSHOT_RETRIES):
        last = attempt == SNAPSHOT_RETRIES - 1
        repo.refresh()
        before = _read_bytes(log_path)
        try:
            result = read()
        except Refusal as exc:
            if last or exc.reason not in (
                "txn_pending",
                "store_malformed",
                "history_missing",
            ):
                raise
            time.sleep(SNAPSHOT_PAUSE_S)
            continue
        if _read_bytes(log_path) == before or last:
            return result
        time.sleep(SNAPSHOT_PAUSE_S)
    raise Refusal("txn_pending", "snapshot")


# -- the writer lock and transactions -------------------------------------------------------


def _pid_start(pid: int) -> str | None:
    """A process's start time (``%.3f``); None when it has exited, ``"unknown"`` when unreadable."""
    import psutil  # noqa: PLC0415 - imported only by writers

    try:
        return f"{psutil.Process(pid).create_time():.3f}"
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return None
    except (psutil.AccessDenied, OSError):
        return "unknown"


def process_start_matches(start: str, given: str) -> bool:
    """Whether a read start time (``%.3f``) is the process that ``given`` names (EA-26).

    The credits store keeps a process start to the second (``segments.created``), so two
    numeric starts match when they differ by less than one second; other text must be equal.
    """
    try:
        return abs(float(start) - float(given)) < 1.0
    except ValueError:
        return start == given


def crash_point(repo: Path | Repo) -> str | None:
    """The CRASH seam value of a marked store, else None (the ``phase`` crash windows, EA-26)."""
    handle = _as_repo(repo)
    return os.environ.get(CRASH_ENV) if handle.marked else None


def _lock_body_ok(value: object) -> bool:
    """A store.lock body of the lock schema."""
    if not isinstance(value, dict):
        return False
    body = cast(dict[str, Any], value)
    return (
        set(body) == {"pid", "pid_start", "host", "session", "token", "ts"}
        and _is_int(body["pid"], 1)
        and all(
            isinstance(body[key], str) and bool(body[key])
            for key in ("pid_start", "host", "session")
        )
        and _match(TOKEN_RE, body["token"])
        and _is_date(body["ts"])
    )


def _read_lock(path: Path) -> dict[str, Any] | None:
    """The lock body, or None when the file is absent, empty, unreadable or not a lock body."""
    try:
        data = _read_bytes(path)
    except PermissionError:
        return None
    if not data:
        return None
    try:
        body = _load_json(data)
    except ValueError:
        return None
    return cast(dict[str, Any], body) if _lock_body_ok(body) else None


def _holder_dead(body: Mapping[str, Any]) -> bool:
    """The holder ran on this host and has exited (its pid is gone, or started at another time)."""
    if body["host"] != socket.gethostname():
        return False
    start = _pid_start(int(body["pid"]))
    return start is None or (start != "unknown" and start != body["pid_start"])


@contextlib.contextmanager
def _locked(repo: Repo, session: str) -> Iterator[str]:
    """Hold ``store.lock`` (O_EXCL); a dead holder or a wait past the limit refuses ``stale_lock``."""
    repo.store.mkdir(parents=True, exist_ok=True)
    lock = repo.store / "store.lock"
    token = uuid.uuid4().hex
    body = {
        "pid": os.getpid(),
        "pid_start": _pid_start(os.getpid()) or "unknown",
        "host": socket.gethostname(),
        "session": session or "unknown",
        "token": token,
        "ts": _ts(repo),
    }
    wait = _lock_wait(repo)
    started = time.monotonic()
    debugged = False
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    while True:
        try:
            fd = os.open(lock, flags, 0o644)
        except (FileExistsError, PermissionError):
            holder = _read_lock(lock)
            if holder is not None and _holder_dead(holder):
                raise Refusal("stale_lock", "holder_exited") from None
            observed = time.monotonic() - started
            if observed >= wait:
                _log(
                    "lock_wait_exceeded",
                    level="WARN",
                    limit_name="LOCK_WAIT_S",
                    configured=wait,
                    observed=round(observed, 3),
                    window="writer_lock",
                )
                raise Refusal("stale_lock", "wait_exceeded") from None
            if not debugged and observed >= wait * (LOCK_DEBUG_S / LOCK_WAIT_S):
                debugged = True
                _log(
                    "lock_wait_long",
                    level="DEBUG",
                    configured=wait,
                    observed=round(observed, 3),
                )
            time.sleep(LOCK_POLL_S)
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write((json.dumps(body, sort_keys=True) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        break
    try:
        yield token
    finally:
        current = _read_lock(lock)
        if current is not None and current["token"] == token:
            _unlink(lock)


@contextlib.contextmanager
def writer_lock(repo: Path, *, session: str) -> Iterator[str]:
    """The store's writer lock for the repository at ``repo``; yields the lock token."""
    with _locked(_open_repo(repo), session) as token:
        yield token


def _apply(repo: Repo, base: Path, intent: Mapping[str, Any], *, seams: bool) -> None:
    """Copy each data file to ``apply/`` and replace it into the store."""
    for index, item in enumerate(cast(list[dict[str, str]], intent["files"])):
        rel = item["path"]
        data = _read_bytes(base / "data" / rel)
        if data is None:
            raise Refusal("store_malformed", f"txn_data:{rel}")
        staged = base / "apply" / rel
        _write_durable(staged, data)
        target = repo.store / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _replace(staged, target)
        if seams and index == 0:
            _crash(repo, "after_replace_1")


def _finish(
    repo: Repo, log: TxnLog, intent: Mapping[str, Any], raw: str, *, seams: bool
) -> None:
    """Advance the witness to this transaction, append its done line, and remove its folder."""
    seq = int(intent["seq"])
    entries = [*log.done_entries(), (seq, raw)]
    repo.config_set(WITNESS_SEQ_KEY, str(seq))
    repo.config_set(WITNESS_DIGEST_KEY, _chain(entries))
    done = {"seq": seq, "txn": intent["txn"], "done": True, "ts": _ts(repo)}
    _append_line(repo.store / "txn.jsonl", _json_line(done))
    if seams:
        _crash(repo, "after_done")
    _rmtree(repo.store / "txn" / cast(str, intent["txn"]))


def _txn(repo: Repo, files: Mapping[str, bytes]) -> int:
    """One transaction: data, intent, replace, witness, done (R§4.1 V-8w); return its seq."""
    log = _txn_log(repo.store)
    seq = log.next_seq
    txn = str(uuid.uuid4())
    base = repo.store / "txn" / txn
    for rel, data in files.items():
        _write_durable(base / "data" / rel, data)
    _crash(repo, "after_data")
    intent: dict[str, Any] = {
        "seq": seq,
        "txn": txn,
        "intent": True,
        "files": [
            {"path": rel, "digest": _digest(data)}
            for rel, data in sorted(files.items())
        ],
        "ts": _ts(repo),
    }
    raw = _json_line(intent)
    _append_line(repo.store / "txn.jsonl", raw)
    _crash(repo, "after_intent")
    _apply(repo, base, intent, seams=True)
    _finish(repo, log, intent, raw, seams=True)
    return seq


def _recover(repo: Repo) -> None:
    """Under the lock: complete every pending transaction, then remove leftover txn folders."""
    root = repo.store
    if not (root / "txn.jsonl").exists():
        return
    log = _txn_log(root)
    for intent, raw in log.pending():
        _check_txn_data(root, intent)
        _apply(repo, root / "txn" / cast(str, intent["txn"]), intent, seams=False)
        _finish(repo, log, intent, raw, seams=False)
        _log("txn_recovered", seq=intent["seq"], txn=intent["txn"])
        log = _txn_log(root)
    folder = root / "txn"
    if folder.is_dir():
        for leftover in folder.iterdir():
            _rmtree(leftover)


def _with_inventory(
    store: Store, files: dict[str, bytes], added: Sequence[str]
) -> dict[str, bytes]:
    """Add store.json to a transaction when it creates files the inventory does not yet list."""
    return _with_meta_inventory(
        {**store.meta, "inventory": list(store.inventory)}, files, added
    )


def _edit_frontmatter(
    path: Path,
    *,
    store_seq: int | None = None,
    bound: Sequence[str] | None = None,
    stop_gate: str | None = None,
) -> None:
    """Text edits of a task.md frontmatter: ``store_seq``, ``bound_sessions`` and ``stop_gate``."""
    text = _read_text(path)
    if text is None:
        raise Refusal("binding", "task_missing")
    text = text.replace("\r\n", "\n")
    end = text.find("\n---\n", 3)
    if not text.startswith("---\n") or end < 0:
        raise Refusal("schema", "frontmatter")
    head = text[4:end].split("\n")
    rest = text[end + 1 :]
    if bound is not None:
        new = (
            ["bound_sessions:", *(f"- {item}" for item in bound)]
            if bound
            else ["bound_sessions: []"]
        )
        start = next(
            (i for i, line in enumerate(head) if line.startswith("bound_sessions:")),
            None,
        )
        if start is None:
            head.extend(new)
        else:
            stop = start + 1
            while stop < len(head) and (
                head[stop].startswith("- ") or head[stop].startswith("  - ")
            ):
                stop += 1
            head[start:stop] = new
    if store_seq is not None:
        line = f"store_seq: {store_seq}"
        at = next(
            (i for i, item in enumerate(head) if item.startswith("store_seq:")), None
        )
        if at is None:
            head.append(line)
        else:
            head[at] = line
    if stop_gate is not None:
        line = f'stop_gate: "{stop_gate}"'
        at = next(
            (i for i, item in enumerate(head) if item.startswith("stop_gate:")), None
        )
        if at is None:
            head.append(line)
        else:
            head[at] = line
    _write_atomic(path, ("---\n" + "\n".join(head) + "\n" + rest).encode("utf-8"))


# -- writers: bootstrap and grants ----------------------------------------------------------


def _bootstrap(repo: Repo) -> None:
    """Create the store under the lock: folders, the anchor, then store.json and revocations."""
    root = repo.store
    for name in ("txn", "grants", "sessions"):
        (root / name).mkdir(parents=True, exist_ok=True)
    log = root / "txn.jsonl"
    if not log.exists():
        _write_durable(log, b"")
    store_uuid = str(uuid.uuid4())
    repo.config_set(ANCHOR_KEY, store_uuid)
    roots = sorted(set(_git(repo.top, "rev-list", "--max-parents=0", "--all").split()))
    meta = {
        "schema": STORE_SCHEMA,
        "repo_id": {
            "roots": roots,
            "common_dir": display_path(repo.common),
            "store_uuid": store_uuid,
        },
        "inventory": sorted(BASE_INVENTORY),
        "created": _ts(repo),
    }
    _txn(repo, {"store.json": _json_bytes(meta), "revocations.jsonl": b""})
    _log("store_created", store_uuid=store_uuid, common_dir=display_path(repo.common))


def _new_grant(verified: Verified) -> dict[str, Any]:
    """A grant record for a verified reference, nothing consumed."""
    return {
        "message_uuid": verified.mu,
        "offer": verified.reference.offer,
        "offer_digest": verified.reference.auth["offer_digest"],
        "chain": verified.reference.chain,
        "consumed": {},
        "superseded_by": "none",
    }


def _initialize(repo: Repo, verified: Verified) -> tuple[int, dict[str, Any]]:
    """``init``: create the store if needed, then record the grant (and any supersession)."""
    with _locked(repo, cast(str, verified.reference.auth["session"])):
        if not (repo.store / "store.json").exists():
            _bootstrap(repo)
        _recover(repo)
        repo.refresh()
        store, grant = _store_checks(
            repo,
            verified,
            act=None,
            op=None,
            reader=True,
            check_grant=False,
            repair=True,
        )
        created = grant is None
        if grant is not None:
            _check_history(repo, store, verified, check_grant=True)
        else:
            files: dict[str, bytes] = {
                f"grants/{verified.mu}.json": _json_bytes(_new_grant(verified))
            }
            supersedes = cast(str, verified.reference.auth["supersedes"])
            older = store.grants.get(supersedes)
            if older is not None and older["superseded_by"] == "none":
                files[f"grants/{supersedes}.json"] = _json_bytes(
                    {**older, "superseded_by": verified.mu}
                )
            _txn(repo, _with_inventory(store, files, [f"grants/{verified.mu}.json"]))
        seq = _txn_log(repo.store).seq
    return EXIT_OK, {
        "result": "initialized",
        "authorized": False,
        "failure": False,
        "plan": verified.plan,
        "message_uuid": verified.mu,
        "created": created,
        "store_seq": seq,
    }


def _task_store_seq(carriers: Carriers, seq: int) -> None:
    """Raise the task's ``store_seq`` to ``seq`` (never lower it)."""
    current = carriers.task_meta.get("store_seq", 0)
    if not isinstance(current, int) or seq > current:
        _edit_frontmatter(carriers.task_path, store_seq=seq)


def _check_context(
    store: Store, plan: str, act: str, policy: Mapping[str, Any]
) -> None:
    """D-20: an ``interactive`` act refuses ``capability`` while a headless session holds the plan."""
    capabilities = policy.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return
    if cast(Mapping[str, Any], capabilities).get(act) != "interactive":
        return
    for record in store.sessions.values():
        if record.get("context") != "headless":
            continue
        for entry in cast(list[dict[str, Any]], record.get("plans", [])):
            if entry.get("plan") == plan and entry.get("state") in OPEN_STATES:
                raise Refusal("capability", f"headless:{record.get('session')}")


def _reserve(
    repo: Repo,
    verified: Verified,
    act: str,
    op: str,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """V-8w: record ``consumed[plan][act]`` for ``op``; the same op returns the existing entry."""
    store, _grant = _store_checks(repo, verified, act=act, op=op, reader=False)
    if policy is not None:
        _check_context(store, verified.plan, act, policy)
    with _locked(repo, cast(str, verified.reference.auth["session"])):
        _recover(repo)
        repo.refresh()
        _store, grant = _store_checks(repo, verified, act=act, op=op, reader=True)
        if policy is not None:
            _check_context(_store, verified.plan, act, policy)
        if grant is None:
            raise Refusal("history_missing", "grant")
        existing = (
            cast(dict[str, Any], grant["consumed"]).get(verified.plan, {}).get(act)
        )
        if existing is not None:
            entry = cast(dict[str, Any], existing)
        else:
            entry = {
                "op_id": op,
                "state": "reserved",
                "ts": _ts(repo),
                "seq": _txn_log(repo.store).next_seq,
            }
            consumed = json.loads(json.dumps(grant["consumed"]))
            consumed.setdefault(verified.plan, {})[act] = entry
            _txn(
                repo,
                {
                    f"grants/{verified.mu}.json": _json_bytes(
                        {**grant, "consumed": consumed}
                    )
                },
            )
    if verified.carriers is not None:
        _task_store_seq(verified.carriers, int(entry["seq"]))
    return entry


# -- sessions (R§4.6) -----------------------------------------------------------------------


def _plan_finished(repo: Repo, store: Store, plan: str) -> bool:
    """A plan is finished when its task status is ``complete`` and its last generation is sealed."""
    finals = store.finals.get(plan, [])
    if not finals or max(finals, key=lambda item: item[0])[1]["sealed"] is not True:
        return False
    text = _read_text(_plan_dir(repo, plan) / "task.md")
    if text is None:
        return False
    try:
        meta = _frontmatter(text)
    except Refusal:
        return False
    return meta is not None and meta.get("status") == "complete"


def _bind(
    repo: Repo, plan: str, session: str, *, active: bool, context: str | None = None
) -> tuple[int, dict[str, Any]]:
    """``bind``: one open plan per session; ``--plan`` hands the plan over from any other session.

    ``--context`` sets a new session record's context (``interactive`` when absent); a flag
    that differs from an existing record's context refuses ``binding`` and writes nothing.
    """
    if not SLUG_RE.fullmatch(plan):
        raise Refusal("binding", "plan_slug")
    if not SAFE_NAME_RE.fullmatch(session):
        raise Refusal("binding", "session_name")
    carriers = _load_carriers(repo, plan) if active else None
    with _locked(repo, session):
        _recover(repo)
        repo.refresh()
        store = _load_store(repo)
        _check_history(repo, store, None, check_grant=False)
        now = _ts(repo)
        existing = store.sessions.get(session)
        if (
            existing is not None
            and context is not None
            and existing.get("context") != context
        ):
            return EXIT_REFUSED, _refusal("binding", effective=False)
        record = json.loads(
            json.dumps(
                existing
                or {
                    "session": session,
                    "context": context or "interactive",
                    "plans": [],
                    "store_seq": 0,
                }
            )
        )
        plans = cast(list[dict[str, Any]], record["plans"])
        for entry in plans:
            if (
                entry["plan"] != plan
                and entry["state"] in OPEN_STATES
                and _plan_finished(repo, store, entry["plan"])
            ):
                entry["state"], entry["ts"] = "closed", now
        busy = [
            entry["plan"]
            for entry in plans
            if entry["plan"] != plan and entry["state"] in OPEN_STATES
        ]
        if busy:
            return EXIT_REFUSED, _refusal("session_busy", effective=False)
        state = "active" if active else "pending"
        mine = next((entry for entry in plans if entry["plan"] == plan), None)
        if mine is None:
            plans.append({"plan": plan, "state": state, "ts": now})
        elif not (mine["state"] == "active" and not active):
            mine["state"], mine["ts"] = state, now
        seq = _txn_log(repo.store).next_seq
        record["store_seq"] = seq
        files: dict[str, bytes] = {f"sessions/{session}.json": _json_bytes(record)}
        if active:
            for other, data in store.sessions.items():
                if other == session:
                    continue
                changed = json.loads(json.dumps(data))
                hit = False
                for entry in cast(list[dict[str, Any]], changed["plans"]):
                    if entry["plan"] == plan and entry["state"] in OPEN_STATES:
                        entry["state"], entry["ts"] = "handed_over", now
                        hit = True
                if hit:
                    files[f"sessions/{other}.json"] = _json_bytes(changed)
        seq = _txn(repo, _with_inventory(store, files, [f"sessions/{session}.json"]))
    if carriers is not None:
        bound = list(carriers.bound_sessions)
        if session not in bound:
            bound.append(session)
        current = carriers.task_meta.get("store_seq", 0)
        top = max(seq, current) if isinstance(current, int) else seq
        _edit_frontmatter(carriers.task_path, store_seq=top, bound=bound)
    return EXIT_OK, {
        "result": "bound",
        "authorized": False,
        "failure": False,
        "plan": plan,
        "session": session,
        "state": state,
        "store_seq": seq,
    }


# -- human-record verbs: revoke, unlock, repair ---------------------------------------------


def _human_record(repo: Repo, session: str, message: str) -> tuple[str, str]:
    """A typed human record of ``session`` in this project's transcript: (raw line, text)."""
    raw, record = _typed_record(_load_transcript(repo, session), message, session)
    return raw, _human_text(record)


def _audit(repo: Repo, event: str, **fields: object) -> None:
    """Append one line to ``audit.jsonl`` (outside the transactions: a log, not a fact)."""
    repo.store.mkdir(parents=True, exist_ok=True)
    _append_line(
        repo.store / "audit.jsonl",
        _json_line({"event": event, "ts": _ts(repo), **fields}),
    )


def _revoke(repo: Repo, session: str, message: str) -> tuple[int, dict[str, Any]]:
    """``revoke``: a typed human record ``revoke run_parameters <uuid>`` appends a revocation."""
    raw, text = _human_record(repo, session, message)
    match = REVOKE_RE.fullmatch(text.strip())
    if match is None or not UUID_RE.fullmatch(match.group(1)):
        raise Refusal("consent", "not_a_revocation")
    target = match.group(1)
    with _locked(repo, session):
        _recover(repo)
        repo.refresh()
        store = _load_store(repo)
        _check_history(repo, store, None, check_grant=False)
        prior = next(
            (line for line in store.revocations if line["revoked"] == target), None
        )
        if prior is not None:
            seq = int(prior["seq"])
        else:
            seq = _txn_log(repo.store).next_seq
            line = {
                "revoked": target,
                "by_session": session,
                "by_message_uuid": message,
                "record_digest": _digest(raw.encode("utf-8")),
                "ts": _ts(repo),
                "seq": seq,
            }
            data = (_read_bytes(repo.store / "revocations.jsonl") or b"") + (
                _json_line(line) + "\n"
            ).encode("utf-8")
            _txn(repo, {"revocations.jsonl": data})
    return EXIT_OK, {
        "result": "revoked",
        "authorized": False,
        "failure": False,
        "revoked": target,
        "seq": seq,
    }


def _unlock(
    repo: Repo, expect: str, session: str, message: str
) -> tuple[int, dict[str, Any]]:
    """``unlock``: remove a dead writer's lock only when its token is ``expect`` (AC-B.8)."""
    _human_record(repo, session, message)
    lock = repo.store / "store.lock"
    try:
        raw = _read_bytes(lock)
    except PermissionError:
        return EXIT_REFUSED, _refusal("unlock_conflict", effective=False)
    if raw is None:
        return EXIT_REFUSED, _refusal("no_lock", effective=False)
    body = _read_lock(lock)
    if body is None or body["token"] != expect:
        return EXIT_REFUSED, _refusal("token_mismatch", effective=False)
    if not _holder_dead(body):
        return EXIT_REFUSED, _refusal("lock_held", effective=False)
    moved = repo.store / f"store.lock.unlock-{uuid.uuid4().hex}"
    try:
        os.rename(lock, moved)
    except FileNotFoundError:
        return EXIT_REFUSED, _refusal("no_lock", effective=False)
    except PermissionError:
        return EXIT_REFUSED, _refusal("unlock_conflict", effective=False)
    taken = _read_lock(moved)
    if taken is None or taken["token"] != expect:
        try:
            os.rename(moved, lock)
        except OSError:
            _log("unlock_restore_failed", level="WARN", path=str(moved))
        return EXIT_REFUSED, _refusal("unlock_conflict", effective=False)
    _unlink(moved)
    _audit(repo, "unlock", token=expect, holder=body, session=session, message=message)
    return EXIT_OK, {
        "result": "unlocked",
        "authorized": False,
        "failure": False,
        "token": expect,
    }


def _salvage_jsonl(
    data: bytes, check: Callable[[object], bool]
) -> tuple[list[str], list[str]]:
    """Split a JSONL log into its valid lines and its defective ones (a partial last line included)."""
    text = data.decode("utf-8", errors="replace")
    good: list[str] = []
    bad: list[str] = []
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        try:
            ok = check(json.loads(raw))
        except ValueError:
            ok = False
        (good if ok else bad).append(raw)
    return good, bad


def _repair(
    repo: Repo, session: str, message: str, *, migrate: bool
) -> tuple[int, dict[str, Any]]:
    """``repair``: keep every fact; move defective bytes to ``audit/``; ``--migrate`` re-homes the store."""
    raw_record, _text = _human_record(repo, session, message)
    changes: list[str] = []
    with _locked(repo, session):
        root = repo.store
        audit_dir = (
            root
            / "audit"
            / f"{_now(repo).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        )
        log_raw = _read_bytes(root / "txn.jsonl") or b""
        good, bad = _salvage_jsonl(log_raw, _txn_line_ok)
        if bad:
            _write_durable(audit_dir / "txn.jsonl", log_raw)
            _write_atomic(
                root / "txn.jsonl",
                "".join(line + "\n" for line in good).encode("utf-8"),
            )
            changes.append("txn.jsonl")
        _recover(repo)
        repo.refresh()
        files: dict[str, bytes] = {}
        revocations_raw = _read_bytes(root / "revocations.jsonl")
        if revocations_raw is not None:
            good, bad = _salvage_jsonl(revocations_raw, _revocation_ok)
            if bad:
                _write_durable(audit_dir / "revocations.jsonl", revocations_raw)
                seq = _txn_log(root).next_seq
                known = {cast(str, json.loads(line)["revoked"]) for line in good}
                for line in bad:
                    found = re.search(r'"revoked"\s*:\s*"([0-9a-f-]{36})', line)
                    if (
                        found is None
                        or not UUID_RE.fullmatch(found.group(1))
                        or found.group(1) in known
                    ):
                        continue
                    known.add(found.group(1))
                    good.append(
                        _json_line(
                            {
                                "revoked": found.group(1),
                                "by_session": session,
                                "by_message_uuid": message,
                                "record_digest": _digest(raw_record.encode("utf-8")),
                                "ts": _ts(repo),
                                "seq": seq,
                            }
                        )
                    )
                files["revocations.jsonl"] = "".join(
                    line + "\n" for line in good
                ).encode("utf-8")
                changes.append("revocations.jsonl")
        if migrate:
            raw = _read_bytes(root / "store.json")
            try:
                meta = _load_json(raw or b"")
            except ValueError as exc:
                raise Refusal("store_malformed", "store.json") from exc
            if not _store_json_ok(meta):
                raise Refusal("store_malformed", "store.json:schema")
            typed = cast(dict[str, Any], meta)
            ident = dict(cast(dict[str, Any], typed["repo_id"]))
            roots = set(_git(repo.top, "rev-list", "--max-parents=0", "--all").split())
            if not set(cast(list[str], ident["roots"])) <= roots:
                raise Refusal("store_mismatch", "roots")
            ident["common_dir"] = display_path(repo.common)
            if repo.get(ANCHOR_KEY) is None:
                repo.config_set(ANCHOR_KEY, cast(str, ident["store_uuid"]))
            elif repo.get(ANCHOR_KEY) != ident["store_uuid"]:
                raise Refusal("store_mismatch", "anchor")
            files["store.json"] = _json_bytes({**typed, "repo_id": ident})
            changes.append("store.json")
        if files:
            _txn(repo, files)
        _audit(
            repo,
            "repair",
            session=session,
            message=message,
            migrate=migrate,
            changes=changes,
        )
    return EXIT_OK, {
        "result": "repaired",
        "authorized": False,
        "failure": False,
        "changes": changes,
    }


# -- AC-B.9 index reconciliation (R§4.5 step 7) ---------------------------------------------


def _index_entry(
    top: Path, path: str, env: Mapping[str, str] | None = None
) -> tuple[str, str] | None:
    """``(mode, blob)`` of a stage-0 index entry, or None."""
    out = _git(top, "ls-files", "-s", "--", path, env=env)
    for line in out.splitlines():
        meta, _, name = line.partition("\t")
        parts = meta.split()
        if name == path and len(parts) == 3 and parts[2] == "0":
            return parts[0], parts[1]
    return None


def _tree_entry(top: Path, commit: str, path: str) -> tuple[str, str] | None:
    """``(mode, blob)`` of ``path`` in ``commit``, or None."""
    out = _git(top, "ls-tree", commit, "--", path)
    for line in out.splitlines():
        meta, _, name = line.partition("\t")
        parts = meta.split()
        if name == path and len(parts) == 3:
            return parts[0], parts[2]
    return None


def _journal(
    path: Path, phase: str, status: str, seq: int, ts: str, evidence: Mapping[str, Any]
) -> None:
    """Append a journal entry to an op file, written atomically."""
    data = _read_bytes(path)
    op: dict[str, Any] = cast(dict[str, Any], _load_json(data)) if data else {}
    journal = cast(list[dict[str, Any]], op.setdefault("journal", []))
    journal.append(
        {
            "phase": phase,
            "status": status,
            "evidence": dict(evidence),
            "seq": max(seq, 1),
            "ts": ts,
        }
    )
    _write_atomic(path, _json_bytes(op))


def reconcile_index(
    repo: Path,
    *,
    plan: str,
    run_id: str,
    op: str,
    paths: Sequence[str],
    parent: str,
    commit: str,
) -> dict[str, Any]:
    """Move each path's index entry from ``parent`` to ``commit``; a foreign staged entry is kept.

    The work runs under the store's writer lock and git's ``index.lock``. Each substep
    (``INDEX_STEPS``) is a crash seam in a marked store. A rerun after a crash removes the
    ``index.lock`` that the journal shows this op took, and repeats every substep.
    """
    if (
        not SLUG_RE.fullmatch(plan)
        or not SAFE_NAME_RE.fullmatch(run_id)
        or not SAFE_NAME_RE.fullmatch(op)
    ):
        raise Refusal("binding", "reconcile_names")
    if not paths or not all(_match(REL_RE, item) for item in paths):
        raise Refusal("binding", "reconcile_paths")
    handle = _open_repo(repo)
    index = Path(
        _git(handle.top, "rev-parse", "--path-format=absolute", "--git-path", "index")
    )
    index_lock = index.with_name(index.name + ".lock")
    folder = handle.store / "ops" / plan / run_id / op
    op_file = folder / "op.json"
    work = folder / "index"
    with _locked(handle, f"reconcile_index:{run_id}"):
        seq = _txn_log(handle.store).seq if (handle.store / "txn.jsonl").exists() else 0
        prior = _read_bytes(op_file)
        if prior:
            journal = cast(
                list[dict[str, Any]],
                cast(dict[str, Any], _load_json(prior)).get("journal", []),
            )
            mine = [entry for entry in journal if entry["phase"] == "index_reconciled"]
            if mine and mine[-1]["status"] == "started" and index_lock.exists():
                _unlink(index_lock)
                _log("index_lock_recovered", path=str(index_lock), op=op)
        _journal(
            op_file,
            "index_reconciled",
            "started",
            seq,
            _ts(handle),
            {"paths": list(paths)},
        )
        try:
            fd = os.open(index_lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError as exc:
            raise Refusal("stale_lock", "index_lock_held") from exc
        os.close(fd)
        _crash(handle, "index_lock")
        work.mkdir(parents=True, exist_ok=True)
        work_index = work / "work.index"
        _write_durable(work_index, _read_bytes(index) or b"")
        _crash(handle, "index_copy")
        env = {"GIT_INDEX_FILE": str(work_index)}
        before = {path: _index_entry(handle.top, path, env) for path in paths}
        _write_atomic(
            work / "before.json",
            _json_bytes(
                {path: list(item) if item else None for path, item in before.items()}
            ),
        )
        _crash(handle, "index_before")
        results: dict[str, str] = {}
        for path in paths:
            old = _tree_entry(handle.top, parent, path)
            new = _tree_entry(handle.top, commit, path)
            current = before[path]
            current_blob = current[1] if current else None
            allowed = {old[1] if old else None, new[1] if new else None}
            if current_blob not in allowed:
                results[path] = f"foreign_staged:{current_blob}"
                continue
            if new is None:
                _git(handle.top, "update-index", "--force-remove", "--", path, env=env)
            else:
                _git(
                    handle.top,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"{new[0]},{new[1]},{path}",
                    env=env,
                )
            results[path] = "updated"
        _crash(handle, "index_update")
        after = {path: _index_entry(handle.top, path, env) for path in paths}
        _write_atomic(
            work / "after.json",
            _json_bytes(
                {path: list(item) if item else None for path, item in after.items()}
            ),
        )
        _crash(handle, "index_after")
        staged = index.with_name(index.name + f".rp-{uuid.uuid4().hex}")
        _write_durable(staged, _read_bytes(work_index) or b"")
        _replace(staged, index)
        _crash(handle, "index_replace")
        _unlink(index_lock)
        _crash(handle, "index_unlock")
        _journal(
            op_file, "index_reconciled", "done", seq, _ts(handle), {"paths": results}
        )
    return {
        "result": "reconciled",
        "plan": plan,
        "run_id": run_id,
        "op": op,
        "paths": results,
    }


# -- R§4.6 the final receipt: read set, snapshot, validators, audit, seal, repair -----------

#: The shared context files of the read set: another plan may change them after the seal,
#: so ``status`` checks their stored copies, not the live files (AC-D.4).
FINAL_SHARED: tuple[str, ...] = (
    ".agent/context/current-focus.md",
    f"{TEMPLATE_HOME}/HANDOFF-TEMPLATE.md",
    ".agent/context/known-issues.md",
    ".agent/context/known-issues.yaml",
    ".agent/schemas/reflection.v1.yaml",
    f"{TEMPLATE_HOME}/REFLECTION-TEMPLATE.md",
)
#: The metrics table: the read set holds only the plan's rows of it (a projection).
FINAL_METRICS = "docs/execution/metrics.md"
#: The execution-review round cap of a legacy task when the repository has no
#: ``.agent/review-limits.json`` (``create-plan.md`` Step 6, sanctioned stop 2). The final
#: audit takes its cap from ``audit_round_cap`` (AC-15).
EXEC_REVIEW_MAX_ROUNDS = 6
FINAL_SEAL_SCHEMA = "final-seal/1"
FINAL_FAILURE_SCHEMA = "final-failure/1"
#: Each validator process may run this long before it counts as failed.
VALIDATOR_TIMEOUT_S = 600.0
#: The exit code recorded for a validator that timed out.
VALIDATOR_TIMEOUT_EXIT = 124
#: The publication-audit results, the worst first: the audit reports the worst one.
AUDIT_ORDER: tuple[str, ...] = ("failed", "ambiguous", "audit_insufficient", "passed")
#: The acts whose reconciled ops published a commit of the run.
PUBLISHING_ACTS = frozenset({"exec_commit", "finalize"})
MEU_ID_RE = re.compile(r"MEU-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


def _as_repo(repo: Path | Repo) -> Repo:
    """A ``Repo`` for a path (the module API takes either)."""
    return repo if isinstance(repo, Repo) else _open_repo(Path(repo))


def _final_paths(plan: str) -> dict[str, str]:
    """The canonical closeout paths of ``plan``, relative to the repository."""
    folder = f"docs/execution/plans/{plan}"
    return {
        "plan": f"{folder}/implementation-plan.md",
        "task": f"{folder}/task.md",
        "handoff": f".agent/context/handoffs/{plan}-handoff.md",
        "review": f".agent/context/handoffs/{plan}-implementation-critical-review.md",
        "reflection": f"docs/execution/reflections/{plan}-reflection.md",
        "metrics": FINAL_METRICS,
        "handoff_template": f"{TEMPLATE_HOME}/HANDOFF-TEMPLATE.md",
        "reflection_template": f"{TEMPLATE_HOME}/REFLECTION-TEMPLATE.md",
        "reflection_schema": ".agent/schemas/reflection.v1.yaml",
        "known_issues": ".agent/context/known-issues.md",
        "known_issues_yaml": ".agent/context/known-issues.yaml",
        "current_focus": ".agent/context/current-focus.md",
    }


def _plan_grouping(repo: Repo, plan: str) -> str | None:
    """The grouping slug of the plan's authorization scope, or None (none, manual, legacy)."""
    try:
        carriers = _load_carriers(repo, plan)
    except NonAuthorizing:
        return None
    grouping = cast(str, carriers.auth["scope"]["grouping"])
    return None if grouping == "none" else grouping


def final_read_set(repo: Path | Repo, plan: str) -> list[dict[str, Any]]:
    """AC-D.4: every file the final receipt binds, as ``{path, shared, kind}``, sorted by path.

    Run-owned: every file of the plan folder, the handoff, the execution review, the
    reflection, and the plan's rows of the metrics table (``kind: projection``). Shared:
    the context files of ``FINAL_SHARED`` and the grouping file, when present. A missing
    run-owned file refuses ``binding``.
    """
    return _read_set(_as_repo(repo), plan, strict=True)


def _read_set(handle: Repo, plan: str, *, strict: bool) -> list[dict[str, Any]]:
    """The read set of ``plan``; ``strict`` refuses a missing run-owned file, else omits it."""
    if not SLUG_RE.fullmatch(plan):
        raise Refusal("binding", "plan_slug")
    folder = _plan_dir(handle, plan)
    if strict and not folder.is_dir():
        raise Refusal("binding", "read_set_missing:plan_folder")
    paths = _final_paths(plan)
    owned = [
        path.relative_to(handle.top).as_posix()
        for path in (sorted(folder.rglob("*")) if folder.is_dir() else [])
        if path.is_file()
    ]
    owned.extend(paths[key] for key in ("handoff", "review", "reflection"))
    owned.append(FINAL_METRICS)
    entries: list[dict[str, Any]] = []
    for rel in sorted(set(owned)):
        if not (handle.top / rel).is_file():
            if strict:
                raise Refusal("binding", f"read_set_missing:{rel}")
            continue
        kind = "projection" if rel == FINAL_METRICS else "file"
        entries.append({"path": rel, "shared": False, "kind": kind})
    shared = list(FINAL_SHARED)
    grouping = _plan_grouping(handle, plan)
    if grouping is not None:
        shared.append(
            _grouping_path(handle, grouping).relative_to(handle.top).as_posix()
        )
    for rel in shared:
        if (handle.top / rel).is_file():
            entries.append({"path": rel, "shared": True, "kind": "file"})
    return sorted(entries, key=lambda entry: cast(str, entry["path"]))


def _metrics_cells(line: str) -> list[str]:
    """The stripped cells of one Markdown table line."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _metrics_projection(data: bytes, plan: str) -> bytes:
    """The plan's rows of the metrics table: the lines with a cell equal to ``plan``."""
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    rows = [
        line.rstrip()
        for line in text.split("\n")
        if line.lstrip().startswith("|") and plan in _metrics_cells(line)
    ]
    return "\n".join(rows).encode("utf-8")


def _entry_bytes(top: Path, entry: Mapping[str, Any], plan: str) -> bytes | None:
    """The bytes a read-set entry binds (the projection for the metrics table), or None."""
    data = _read_bytes(top / cast(str, entry["path"]))
    if data is None:
        return None
    return _metrics_projection(data, plan) if entry["kind"] == "projection" else data


def _hash_entries(
    top: Path, entries: Sequence[Mapping[str, Any]], plan: str
) -> dict[str, str | None]:
    """``{path: sha256 or None}`` of the read-set entries under ``top``."""
    out: dict[str, str | None] = {}
    for entry in entries:
        data = _entry_bytes(top, entry, plan)
        out[cast(str, entry["path"])] = None if data is None else _sha256(data)
    return out


def _is_ancestor(top: Path, commit: str, tip: str) -> bool:
    """``commit`` is ``tip`` or an ancestor of it (a missing object is not)."""
    proc = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "merge-base", "--is-ancestor", commit, tip],
        cwd=top,
        env=_git_env(),
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def publication_audit(
    repo: Path | Repo, branch: str, publications: Sequence[Mapping[str, str]]
) -> dict[str, Any]:
    """R§4.6: prove each run publication ``{op, ref_old, ref_new}`` from the branch reflog.

    Each publication is ``passed`` (its update is in the reflog and the tip holds it),
    ``ambiguous`` (the update is in the reflog but the tip no longer holds it),
    ``audit_insufficient`` (no reflog entry proves it, though the tip holds it) or
    ``failed`` (no reflog entry and the tip does not hold it, or a malformed id). The
    result is the worst one; ``none`` when there is nothing to audit. On ``passed``,
    ``foreign_movement`` lists the reflog updates after the last publication.
    """
    handle = _as_repo(repo)
    out: dict[str, Any] = {
        "result": "none",
        "branch": branch,
        "publications": [],
        "foreign_movement": [],
    }
    if not publications:
        return out
    log = _read_text(handle.common / "logs" / "refs" / "heads" / branch)
    tip = _git(
        handle.top,
        "rev-parse",
        "--verify",
        "--quiet",
        f"refs/heads/{branch}^{{commit}}",
        check=False,
    )
    entries: list[dict[str, str]] = []
    for line in (log or "").splitlines():
        head, _, message = line.partition("\t")
        parts = head.split(" ")
        if (
            len(parts) >= 2
            and ROOT_RE.fullmatch(parts[0])
            and ROOT_RE.fullmatch(parts[1])
        ):
            entries.append({"old": parts[0], "new": parts[1], "message": message})
    last = -1
    results: list[dict[str, str]] = []
    for item in publications:
        old, new = str(item.get("ref_old", "")), str(item.get("ref_new", ""))
        if not (ROOT_RE.fullmatch(old) and ROOT_RE.fullmatch(new)):
            state = "failed"
        else:
            on_tip = bool(tip) and _is_ancestor(handle.top, new, tip)
            hits = [
                index
                for index, entry in enumerate(entries)
                if entry["old"] == old and entry["new"] == new
            ]
            if not hits:
                state = "audit_insufficient" if on_tip else "failed"
            elif not on_tip:
                state = "ambiguous"
            else:
                state = "passed"
                last = max(last, hits[-1])
        results.append(
            {
                "op": str(item.get("op", "none")),
                "ref_old": old,
                "ref_new": new,
                "result": state,
            }
        )
    out["publications"] = results
    out["result"] = min((entry["result"] for entry in results), key=AUDIT_ORDER.index)
    if out["result"] == "passed":
        out["foreign_movement"] = entries[last + 1 :]
    return out


def _snapshot_tree(top: Path, sources: Sequence[tuple[str, Path]]) -> str:
    """The git tree id of ``(path, file)`` pairs, built in a temporary index.

    The tree is a digest of the read set: its blobs are hashed, not written, so no object
    of it is kept in the repository (``write-tree --missing-ok``).
    """
    if not sources:
        raise Refusal("binding", "read_set_empty")
    listing = "".join(f"{path.as_posix()}\n" for _rel, path in sources)
    blobs = _git_feed(
        top, listing.encode("utf-8"), "hash-object", "--no-filters", "--stdin-paths"
    ).split("\n")
    if len(blobs) != len(sources):
        raise GitError("hash-object returned a different number of blobs")
    info = "".join(
        f"100644 {blob}\t{rel}\0"
        for (rel, _path), blob in zip(sources, blobs, strict=True)
    )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
        env = {"GIT_INDEX_FILE": str(Path(work) / "index")}
        _git_feed(
            top, info.encode("utf-8"), "update-index", "-z", "--index-info", env=env
        )
        return _git(top, "write-tree", "--missing-ok", env=env)


def _validator_run(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> int:
    """Run one validator process; its exit code (``VALIDATOR_TIMEOUT_EXIT`` on a timeout)."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            list(argv),
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            timeout=VALIDATOR_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _log(
            "validator_timeout",
            level="WARN",
            argv=list(argv),
            limit=VALIDATOR_TIMEOUT_S,
        )
        return VALIDATOR_TIMEOUT_EXIT
    if proc.returncode != 0:
        _log(
            "validator_failed",
            argv=list(argv),
            exit=proc.returncode,
            stdout=proc.stdout.decode("utf-8", errors="replace")[-4000:],
            stderr=proc.stderr.decode("utf-8", errors="replace")[-4000:],
        )
    return proc.returncode


def _validator(tool: Path, code: int, stage: str) -> dict[str, Any]:
    """One ``validators`` entry: the exit code, the tool and stage, and the tool's sha256."""
    data = _read_bytes(tool)
    if data is None:
        raise Refusal("binding", f"validator_missing:{tool.name}")
    return {"exit": code, "version": f"{tool.stem}/{stage}", "sha256": _sha256(data)}


def audit_round_cap(top: Path, plan: str) -> int:
    """The execution-review round cap of the final audit of ``plan`` (AC-15).

    The ``exec-<plan>`` ledger's ``rounds_allowed()`` (its base budget plus every continue
    grant) when the ledger exists. Without one, a task that carries ``review_limits`` is
    refused (the loop those limits bound was never opened); a legacy task takes the
    repository's ``rounds.execution``, else ``EXEC_REVIEW_MAX_ROUNDS``. A ledger or limits
    file that does not load is refused, never a fall back to the default.
    """
    ledger = _review_ledger()
    loop = f"exec-{plan}"
    try:
        path: Path | None = ledger.ledger_path(loop)
    except ledger.FailClosed:
        path = None
    if path is not None and path.exists():
        try:
            data = ledger.load_ledger(loop)
            mode = data.get("review_mode")
            cap = ledger.rounds_allowed(data)
        except (ledger.FailClosed, KeyError, TypeError, AttributeError) as exc:
            raise Refusal("binding", "exec_ledger_malformed") from exc
        if mode != "execution":
            raise Refusal("binding", "exec_ledger_mode")
        if not _is_int(cap, 1):
            raise Refusal("binding", "exec_ledger_malformed")
        return cast(int, cap)
    try:
        if ledger.load_plan_limits(top / _final_paths(plan)["task"]) is not None:
            raise Refusal("binding", "exec_ledger_missing")
        repo = ledger.load_repo_limits(top)
    except ledger.FailClosed as exc:
        raise Refusal("schema", "review_limits_malformed") from exc
    return cast(int, repo["rounds"]["execution"]) if repo else EXEC_REVIEW_MAX_ROUNDS


def run_stage_validators(
    top: Path,
    plan: str,
    snapshot: Path,
    *,
    grouping: str | None = None,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The final stage of the closeout validator and of the preflight, over ``snapshot``.

    ``snapshot`` holds a copy of the read set at the repository's relative paths. The
    closeout validator first writes the review-state receipt, then runs
    ``--stage final --for-produce`` (the audit and the receipt checks wait for the receipt);
    the preflight runs ``--stage final`` on the snapshot tree. ``manifest`` is the commit
    packet of the run's last publishing op (a ``commit_exec`` run). Returns
    ``{"closeout": {exit, version, sha256}, "preflight": {...}}``. Both closeout runs take
    the round cap of ``audit_round_cap``; a refused cap raises before any validator runs.
    """
    cap = str(audit_round_cap(top, plan))
    tools = Path(__file__).resolve().parent
    closeout_tool = tools / "validate_closeout_artifacts.py"
    preflight_tool = tools / "completion_preflight.py"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(tools.parent), env.get("PYTHONPATH", "")) if item
    )
    paths = {key: snapshot / rel for key, rel in _final_paths(plan).items()}
    work = snapshot / ".run-parameters"
    work.mkdir(parents=True, exist_ok=True)
    state = work / "review-state.json"
    python = [sys.executable, "-X", "utf8"]
    code = _validator_run(
        [
            *python,
            str(closeout_tool),
            "--review-state-only",
            "--review",
            str(paths["review"]),
            "--expected-review-mode",
            "execution",
            "--expected-target-plan",
            _final_paths(plan)["plan"],
            "--max-review-rounds",
            cap,
            "--output",
            str(state),
        ],
        snapshot,
        env,
    )
    if code == 0:
        argv = [
            *python,
            str(closeout_tool),
            "--stage",
            "final",
            "--for-produce",
            "--repo",
            str(top),
            "--plan-slug",
            plan,
            "--review-state-receipt",
            str(state),
            "--max-review-rounds",
            cap,
            "--expected-target-plan",
            _final_paths(plan)["plan"],
        ]
        for key in (
            "plan",
            "task",
            "handoff",
            "handoff_template",
            "review",
            "reflection",
            "reflection_template",
            "reflection_schema",
            "metrics",
            "known_issues",
            "known_issues_yaml",
            "current_focus",
        ):
            argv += [f"--{key.replace('_', '-')}", str(paths[key])]
        rows = (
            _metrics_projection(_read_bytes(paths["metrics"]) or b"", plan)
            .decode("utf-8")
            .split("\n")
        )
        cells = _metrics_cells(rows[0]) if rows and rows[0] else []
        if len(cells) >= 2:
            meus = MEU_ID_RE.findall(cells[1])
            argv += ["--date", cells[0], "--meu", meus[0] if meus else cells[1]]
        if grouping is not None:
            argv += [
                "--grouping",
                str(snapshot / ".agent" / "context" / "grouping" / f"{grouping}.md"),
            ]
        if manifest is not None:
            packet = work / "commit-manifest.json"
            _write_atomic(packet, _json_bytes(dict(manifest)))
            argv += ["--commit-manifest", str(packet)]
        code = _validator_run(argv, snapshot, env)
    preflight = _validator_run(
        [
            *python,
            str(preflight_tool),
            "--stage",
            "final",
            "--plan",
            f"docs/execution/plans/{plan}",
            "--tree",
            str(snapshot),
        ],
        snapshot,
        env,
    )
    return {
        "closeout": _validator(closeout_tool, code, "final"),
        "preflight": _validator(preflight_tool, preflight, "final"),
    }


def _validators_ok(value: object) -> bool:
    """The validators result has the receipt's shape and both exits are 0."""
    if not isinstance(value, dict):
        return False
    result = cast(dict[str, Any], value)
    if set(result) != {"closeout", "preflight"}:
        return False
    for item in result.values():
        if not isinstance(item, dict):
            return False
        entry = cast(dict[str, Any], item)
        if not (
            set(entry) == {"exit", "version", "sha256"}
            and _is_int(entry["exit"], 0)
            and isinstance(entry["version"], str)
            and bool(entry["version"])
            and _match(HEX64_RE, entry["sha256"])
            and entry["exit"] == 0
        ):
            return False
    return True


def _plan_ops(repo: Repo, plan: str) -> list[dict[str, Any]]:
    """The commit ops of ``store/ops/<plan>/``: ``{op, run_id, act, phase, commit, parent, ts}``.

    ``phase`` is the last phase journaled ``done`` (``index_reconciled`` is a sub-step, not a
    phase of the op), ``none`` before the first, and ``malformed`` for an unreadable file.
    A file with no identity (an index reconciliation alone) is not an op. A batch writes
    each packet as the sub-op ``<op>/<n>`` (``<run>/<op>/<n>/op.json``); the sub-ops follow
    in packet order, so the publications chain parent to commit.
    """
    folder = repo.store / "ops" / plan
    out: list[dict[str, Any]] = []
    if not folder.is_dir():
        return out
    found: list[tuple[tuple[str, str, int], Path, str, str]] = []
    for path in folder.glob("*/*/op.json"):
        run_id, op = path.parent.parent.name, path.parent.name
        found.append(((run_id, op, -1), path, run_id, op))
    for path in folder.glob("*/*/*/op.json"):
        number = path.parent.name
        if not (number.isascii() and number.isdigit()):
            continue
        run_id, batch = path.parent.parent.parent.name, path.parent.parent.name
        found.append(((run_id, batch, int(number)), path, run_id, f"{batch}/{number}"))
    for _, path, run_id, op in sorted(found, key=lambda item: item[0]):
        data = _read_bytes(path)
        try:
            record = _load_json(data or b"")
        except ValueError:
            record = None
        base = {
            "op": op,
            "run_id": run_id,
            "act": "unknown",
            "phase": "malformed",
            "commit": "none",
            "parent": "none",
            "ts": "none",
            "packet": None,
        }
        if not isinstance(record, dict):
            out.append(base)
            continue
        typed = cast(dict[str, Any], record)
        identity = typed.get("identity")
        if identity is None:
            continue
        journal = typed.get("journal")
        if not isinstance(identity, dict) or not isinstance(journal, list):
            out.append(base)
            continue
        ident = cast(dict[str, Any], identity)
        done = [
            cast(dict[str, Any], entry)
            for entry in cast(list[object], journal)
            if isinstance(entry, dict)
            and cast(dict[str, Any], entry).get("status") == "done"
            and cast(dict[str, Any], entry).get("phase") != "index_reconciled"
        ]
        last = done[-1] if done else None
        evidence = cast(dict[str, Any], last.get("evidence") or {}) if last else {}
        out.append(
            {
                **base,
                "op": str(ident.get("op", base["op"])),
                "run_id": str(ident.get("run_id", base["run_id"])),
                "act": str(ident.get("act", "unknown")),
                "phase": str(last["phase"]) if last else "none",
                "commit": str(evidence.get("commit", "none")),
                "parent": str(evidence.get("parent", "none")),
                "ts": str(last.get("ts", "none")) if last else "none",
                "packet": typed.get("packet"),
            }
        )
    return out


def _publications(ops: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The run's publications: its reconciled ``exec_commit`` and ``finalize`` ops."""
    return [
        {
            "op": str(op["op"]),
            "ref_old": str(op["parent"]),
            "ref_new": str(op["commit"]),
        }
        for op in ops
        if op["act"] in PUBLISHING_ACTS and op["phase"] == "reconciled"
    ]


def _public_ops(ops: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The ops without their packets (the report the closeout validator reads)."""
    return [{key: value for key, value in op.items() if key != "packet"} for op in ops]


def plan_report(repo: Path | Repo, plan: str) -> dict[str, Any]:
    """The closeout validator's view of a plan's authority: ``{grant, consumed, ops}``.

    ``grant`` is ``verified``, ``superseded``, ``revoked``, ``missing`` (no grant record),
    ``legacy`` (a manual or legacy carrier) or ``refused`` (V-0 to V-8 failed).
    """
    handle = _as_repo(repo)
    report: dict[str, Any] = {"grant": "missing", "consumed": {}, "ops": []}
    try:
        verified = _verify_plan(handle, plan, None)
    except NonAuthorizing:
        report["grant"] = "legacy"
        return report
    except Refusal as exc:
        _log("plan_report_refused", plan=plan, reason=exc.reason, detail=exc.detail)
        report["grant"] = "refused"
        return report
    try:
        store = _snapshot(handle, lambda: _load_store(handle))
        grant = _check_history(handle, store, verified, check_grant=False)
    except Refusal as exc:
        _log("plan_report_refused", plan=plan, reason=exc.reason, detail=exc.detail)
        report["grant"] = "refused"
        return report
    report["ops"] = _public_ops(_plan_ops(handle, plan))
    if grant is None:
        return report
    report["consumed"] = cast(dict[str, Any], grant["consumed"]).get(plan, {})
    if any(line["revoked"] == verified.mu for line in store.revocations):
        report["grant"] = "revoked"
    elif grant["superseded_by"] != "none":
        report["grant"] = "superseded"
    else:
        report["grant"] = "verified"
    return report


def plan_audit(repo: Path | Repo, plan: str) -> dict[str, Any]:
    """The closeout validator's view of a plan's publications and its final receipt."""
    handle = _as_repo(repo)
    status = _final_status(handle, plan)
    state = cast(str, status["generation_state"])
    branch = "main"
    try:
        branch = cast(str, _load_carriers(handle, plan).auth["scope"]["branch"])
    except NonAuthorizing:
        pass
    audit = publication_audit(
        handle,
        branch,
        _publications(_plan_ops(handle, plan)) if handle.store.is_dir() else [],
    )
    return {
        "publication_audit": audit,
        "receipt": state if state in ("current", "stale") else "missing",
    }


def _latest(store: Store, plan: str) -> tuple[int, dict[str, Any]] | None:
    """The plan's highest final generation, or None."""
    finals = store.finals.get(plan, [])
    return max(finals, key=lambda item: item[0]) if finals else None


def _target_generation(store: Store, plan: str) -> tuple[int, int | str]:
    """``(generation, predecessor)`` that ``final --produce`` writes next.

    No receipt: generation 1. An unsealed latest receipt: produced again. A sealed latest
    receipt: only a repair record of the next generation opens it, else ``expired``.
    """
    latest = _latest(store, plan)
    if latest is None:
        return 1, "none"
    n, receipt = latest
    if receipt["sealed"] is not True:
        return n, cast("int | str", receipt.get("predecessor", "none"))
    if n + 1 in store.repairs.get(plan, {}):
        return n + 1, n
    raise Refusal("expired", "sealed_generation")


def _receipt_path(plan: str, n: int) -> str:
    """The store path of generation ``n``'s receipt."""
    return f"final/{plan}/{n}.json"


def _shared_copy(plan: str, n: int, rel: str) -> str:
    """The store path of the copy of shared file ``rel`` that generation ``n`` binds."""
    return f"final/{plan}/{n}/{rel}"


def _record_failure(
    repo: Repo, verified: Verified, n: int, reason: str, detail: Mapping[str, Any]
) -> NoReturn:
    """Write ``<n>.failed.json`` (evidence only: the store loader skips it), then refuse."""
    with _locked(repo, cast(str, verified.reference.auth["session"])):
        _recover(repo)
        repo.refresh()
        _txn(
            repo,
            {
                f"final/{verified.plan}/{n}.failed.json": _json_bytes(
                    {
                        "schema": FINAL_FAILURE_SCHEMA,
                        "plan": verified.plan,
                        "generation": n,
                        "reason": reason,
                        "detail": dict(detail),
                        "ts": _ts(repo),
                    }
                )
            },
        )
    raise Refusal(reason, json.dumps(dict(detail), sort_keys=True, default=str))


def _differences(
    before: Mapping[str, str | None], after: Mapping[str, str | None]
) -> list[str]:
    """The paths whose hashes differ, or that one side lacks."""
    return sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
        or path not in before
        or path not in after
    )


def _produce(repo: Repo, plan: str) -> Outcome:
    """``final --produce``: validate a snapshot of the read set and write the receipt."""
    _gate(repo, None)
    try:
        verified = _verify_plan(repo, plan, None)
    except NonAuthorizing as exc:
        raise Refusal("legacy", exc.kind) from exc
    carriers = cast(Carriers, verified.carriers)
    store, _grant = _snapshot(
        repo,
        lambda: _store_checks(
            repo,
            verified,
            act=None,
            op=None,
            reader=True,
            check_consumed=False,
            repair=True,
        ),
    )
    n, predecessor = _target_generation(store, plan)
    entries = final_read_set(repo, plan)
    grouping = _plan_grouping(repo, plan)
    commit_exec = bool(verified.effective["commit_exec"])
    ops = _plan_ops(repo, plan) if commit_exec else []
    publishing = [
        op for op in ops if op["act"] in PUBLISHING_ACTS and op["phase"] == "reconciled"
    ]
    if commit_exec and not publishing:
        raise Refusal("binding", "no_publication")
    last_op = next(
        (op for op in reversed(publishing) if op["act"] == "finalize"), None
    ) or (publishing[-1] if publishing else None)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
        snapshot = Path(work) / "tree"
        sources: list[tuple[str, Path]] = []
        for entry in entries:
            rel = cast(str, entry["path"])
            data = _read_bytes(repo.top / rel)
            if data is None:
                raise Refusal("binding", f"read_set_missing:{rel}")
            _write_durable(snapshot / rel, data)
            if entry["kind"] == "projection":
                projected = Path(work) / "projection"
                _write_durable(projected, _metrics_projection(data, plan))
                sources.append((rel, projected))
            else:
                sources.append((rel, snapshot / rel))
        hashes = _hash_entries(snapshot, entries, plan)
        tree = _snapshot_tree(repo.top, sources)
        validators = run_stage_validators(
            repo.top,
            plan,
            snapshot,
            grouping=grouping,
            manifest=cast("Mapping[str, Any] | None", last_op["packet"])
            if last_op is not None and isinstance(last_op["packet"], dict)
            else None,
        )
    try:
        live_entries = final_read_set(repo, plan)
    except Refusal as exc:
        _record_failure(repo, verified, n, "snapshot_differs", {"read_set": exc.detail})
    live = _hash_entries(repo.top, live_entries, plan)
    changed = _differences(hashes, live)
    if changed:
        _record_failure(repo, verified, n, "snapshot_differs", {"paths": changed})
    if not _validators_ok(validators):
        _record_failure(
            repo, verified, n, "validators_failed", {"validators": validators}
        )
    publications = [
        {
            "op": str(op["op"]),
            "ref_old": str(op["parent"]),
            "ref_new": str(op["commit"]),
        }
        for op in publishing
    ]
    auth = verified.reference.auth
    branch = cast(str, auth["scope"]["branch"])
    audit = publication_audit(repo, branch, publications)
    with _locked(repo, cast(str, auth["session"])):
        _recover(repo)
        repo.refresh()
        store, _grant = _store_checks(
            repo,
            verified,
            act=None,
            op=None,
            reader=True,
            check_consumed=False,
            repair=True,
        )
        if _target_generation(store, plan) != (n, predecessor):
            raise Refusal("binding", "generation_moved")
        receipt = {
            "schema": "final-receipt/1",
            "plan": plan,
            "run_id": str(carriers.task_meta.get("run_id") or verified.mu),
            "repo_id": store.meta["repo_id"],
            "branch": branch,
            "generation": n,
            "mode": "committed" if commit_exec else "tree",
            "op": str(last_op["op"]) if last_op is not None else "none",
            "commit": str(last_op["commit"]) if last_op is not None else "none",
            "tree": tree,
            "read_set": [
                {"path": entry["path"], "sha256": hashes[cast(str, entry["path"])]}
                for entry in entries
            ],
            "validators": validators,
            "publication_audit": audit,
            "predecessor": predecessor,
            "sealed": False,
            "seal": "none",
            "ts": _ts(repo),
        }
        files: dict[str, bytes] = {_receipt_path(plan, n): _json_bytes(receipt)}
        for entry in entries:
            if entry["shared"]:
                rel = cast(str, entry["path"])
                data = _read_bytes(repo.top / rel)
                if data is None or _sha256(data) != hashes[rel]:
                    raise Refusal("snapshot_differs", f"shared:{rel}")
                files[_shared_copy(plan, n, rel)] = data
        seq = _txn(repo, _with_inventory(store, files, [_receipt_path(plan, n)]))
    _audit(repo, "final_produce", plan=plan, generation=n, tree=tree, seq=seq)
    return EXIT_OK, {
        "result": "produced",
        "authorized": False,
        "failure": False,
        "plan": plan,
        "generation": n,
        "predecessor": predecessor,
        "mode": receipt["mode"],
        "tree": tree,
        "store_seq": seq,
    }


def _seal(repo: Repo, plan: str) -> Outcome:
    """``final --seal``: the live read set still equals the latest receipt; seal it."""
    _gate(repo, None)
    try:
        verified = _verify_plan(repo, plan, None)
    except NonAuthorizing as exc:
        raise Refusal("legacy", exc.kind) from exc
    auth = verified.reference.auth
    with _locked(repo, cast(str, auth["session"])):
        _recover(repo)
        repo.refresh()
        store, _grant = _store_checks(
            repo,
            verified,
            act=None,
            op=None,
            reader=True,
            check_consumed=False,
            repair=True,
        )
        latest = _latest(store, plan)
        if latest is None:
            raise Refusal("no_receipt", plan)
        n, receipt = latest
        if receipt["sealed"] is True:
            raise Refusal("expired", "sealed_generation")
        bound = {
            cast(str, item["path"]): cast(str, item["sha256"])
            for item in cast(list[dict[str, Any]], receipt["read_set"])
        }
        live = _hash_entries(repo.top, final_read_set(repo, plan), plan)
        changed = _differences(bound, live)
        if changed:
            raise Refusal("snapshot_differs", ",".join(changed))
        receipt_bytes = _json_bytes(receipt)
        seal = {
            "schema": FINAL_SEAL_SCHEMA,
            "plan": plan,
            "generation": n,
            "receipt_sha256": _sha256(receipt_bytes),
            "ts": _ts(repo),
        }
        seal_path = f"final/{plan}/{n}.seal"
        seal_bytes = _json_bytes(seal)
        sealed = {
            **receipt,
            "sealed": True,
            "seal": {"path": seal_path, "sha256": _sha256(seal_bytes)},
        }
        seq = _txn(
            repo,
            _with_inventory(
                store,
                {seal_path: seal_bytes, _receipt_path(plan, n): _json_bytes(sealed)},
                [seal_path, _receipt_path(plan, n)],
            ),
        )
    _audit(repo, "final_seal", plan=plan, generation=n, seq=seq)
    return EXIT_OK, {
        "result": "sealed",
        "authorized": False,
        "failure": False,
        "plan": plan,
        "generation": n,
        "store_seq": seq,
    }


def _task_done(meta: Mapping[str, Any] | None) -> bool:
    """The task frontmatter says ``status: complete`` and ``stop_gate: released:done``."""
    return (
        meta is not None
        and meta.get("status") == "complete"
        and meta.get("stop_gate") == "released:done"
    )


def _final_status(repo: Repo, plan: str) -> dict[str, Any]:
    """R§4.6 ``status --plan``: whether the plan is done, and every reason it is not.

    A manual or legacy plan is done when its task says so. A granted plan also needs its
    grant intact and a current, sealed final receipt: the run-owned files equal the
    receipt, the stored copies of the shared files equal it, both validators passed, the
    seal file matches, and (committed mode) the publication audit passes again.
    """
    if not SLUG_RE.fullmatch(plan):
        raise Refusal("binding", "plan_slug")
    text = _read_text(_plan_dir(repo, plan) / "task.md")
    meta = _frontmatter(text) if text is not None else None
    out: dict[str, Any] = {
        "plan": plan,
        "kind": "grant",
        "done": False,
        "reasons": [],
        "generation_state": "missing",
        "generation": "none",
    }
    reasons = cast(list[str], out["reasons"])
    if not _task_done(meta):
        reasons.append("not_done")
    try:
        verified = _verify_plan(repo, plan, None)
    except NonAuthorizing:
        out["kind"] = "legacy"
        out["generation_state"] = "n/a"
        out["done"] = not reasons
        return out
    except Refusal as exc:
        reasons.append(exc.reason)
        return out
    try:
        store = _snapshot(repo, lambda: _load_store(repo))
        grant = _check_history(repo, store, verified, check_grant=True)
    except Refusal as exc:
        reasons.append(exc.reason)
        return out
    if any(line["revoked"] == verified.mu for line in store.revocations):
        reasons.append("revoked")
    finals = sorted(store.finals.get(plan, []), key=lambda item: item[0])
    sealed = [item for item in finals if item[1]["sealed"] is True]
    current = sealed[-1] if sealed else (finals[-1] if finals else None)
    if current is None:
        reasons.append("no_receipt")
        return out
    n, receipt = current
    out["generation"] = n
    out["generation_state"] = "current"
    if receipt["sealed"] is not True:
        reasons.append("unsealed")
    if _open_repair(store, plan) is not None:
        reasons.append("repair_open")
    entries = {
        cast(str, entry["path"]): entry for entry in _read_set(repo, plan, strict=False)
    }
    bound = {
        cast(str, item["path"]): cast(str, item["sha256"])
        for item in cast(list[dict[str, Any]], receipt["read_set"])
    }
    stale = False
    for rel, digest in bound.items():
        entry = entries.get(rel)
        if entry is not None and entry["shared"]:
            copy = _read_bytes(store.root / _shared_copy(plan, n, rel))
            if copy is None or _sha256(copy) != digest:
                reasons.append("history_missing")
            continue
        if entry is None:
            copy = _read_bytes(store.root / _shared_copy(plan, n, rel))
            if copy is not None:
                if _sha256(copy) != digest:
                    reasons.append("history_missing")
                continue
            stale = True
            continue
        data = _entry_bytes(repo.top, entry, plan)
        if data is None or _sha256(data) != digest:
            stale = True
    owned_now = {rel for rel, entry in entries.items() if not entry["shared"]}
    if owned_now - set(bound):
        stale = True
    if stale:
        reasons.append("stale_generation")
        out["generation_state"] = "stale"
    if not _validators_ok(receipt["validators"]):
        reasons.append("validators_failed")
    if receipt["sealed"] is True:
        seal = cast(dict[str, Any], receipt["seal"])
        seal_bytes = _read_bytes(store.root / cast(str, seal["path"]))
        if seal_bytes is None or _sha256(seal_bytes) != seal["sha256"]:
            reasons.append("history_missing")
    if receipt["mode"] == "committed":
        audit = publication_audit(
            repo, cast(str, receipt["branch"]), _publications(_plan_ops(repo, plan))
        )
        if audit["result"] != "passed":
            reasons.append(f"publication_{audit['result']}")
    if grant is None:
        reasons.append("history_missing")
    out["reasons"] = sorted(set(reasons), key=reasons.index)
    out["done"] = not out["reasons"]
    return out


def _repair_final(repo: Repo, plan: str) -> Outcome:
    """``repair --final --plan``: open the next generation after a sealed one.

    The run's grant must be superseded by a recorded, unrevoked, unsuperseded grant whose
    offer grants ``finalize`` and scopes this plan. The repair record names both grants, so
    ``final --produce`` and ``--seal`` accept the old reference for that generation only.
    """
    _gate(repo, None)
    if not SLUG_RE.fullmatch(plan):
        raise Refusal("binding", "plan_slug")
    try:
        carriers = _load_carriers(repo, plan)
    except NonAuthorizing as exc:
        raise Refusal("legacy", exc.kind) from exc
    mu = cast(str, carriers.auth["message_uuid"])
    with _locked(repo, cast(str, carriers.auth["session"])):
        _recover(repo)
        repo.refresh()
        store = _load_store(repo)
        _check_history(repo, store, None, check_grant=False)
        old = store.grants.get(mu)
        if old is None:
            raise Refusal("history_missing", "grant")
        newer_id = cast(str, old["superseded_by"])
        if newer_id == "none":
            raise Refusal("not_granted", "finalize:not_superseded")
        newer = store.grants.get(newer_id)
        if newer is None:
            raise Refusal("history_missing", f"grant:{newer_id}")
        if any(line["revoked"] == newer_id for line in store.revocations):
            raise Refusal("revoked", newer_id)
        if newer["superseded_by"] != "none":
            raise Refusal("superseded", cast(str, newer["superseded_by"]))
        offer = cast(dict[str, Any], newer["offer"])
        if "finalize" not in cast(list[str], offer["grants"]):
            raise Refusal("not_granted", "finalize")
        if offer["scope"]["plan"] != plan and plan not in cast(
            list[str], offer.get("members") or []
        ):
            raise Refusal("scope", "plan")
        latest = _latest(store, plan)
        if latest is None or latest[1]["sealed"] is not True:
            raise Refusal("not_granted", "generation_open")
        n = latest[0] + 1
        rel = f"final/{plan}/{n}.repair.json"
        prior = store.repairs.get(plan, {}).get(n)
        if prior is not None:
            if prior["grant"] != newer_id or prior["superseded"] != mu:
                raise Refusal("binding", "repair_conflict")
            seq = store.log.seq
        else:
            record = {
                "schema": "final-repair/1",
                "plan": plan,
                "generation": n,
                "predecessor": n - 1,
                "grant": newer_id,
                "superseded": mu,
                "ts": _ts(repo),
            }
            seq = _txn(repo, _with_inventory(store, {rel: _json_bytes(record)}, [rel]))
            _audit(
                repo,
                "repair_final",
                plan=plan,
                generation=n,
                grant=newer_id,
                superseded=mu,
                seq=seq,
            )
    return EXIT_OK, {
        "result": "repaired",
        "authorized": False,
        "failure": False,
        "plan": plan,
        "generation": n,
        "predecessor": n - 1,
        "grant": newer_id,
        "store_seq": seq,
    }


# -- R§4.4 the phase machine (WP-7) ---------------------------------------------------------

PHASE_NONTERMINALS: tuple[str, ...] = (
    "plan:active",
    "plan:approved",
    "plan:pc_done",
    "transition:prepared",
    "transition:admitted",
    "exec:active",
    "exec:finalizing",
)
PHASE_PARKED = "PARKED:approved"
PHASE_STOP_CAUSES: tuple[str, ...] = (
    "decision",
    "budget",
    "round_cap",
    "reviewer_unavailable",
    "human_stop",
    "no_record",
    "ambiguous",
)
PHASE_STATES: tuple[str, ...] = (
    *PHASE_NONTERMINALS,
    "DONE",
    PHASE_PARKED,
    *(f"STOPPED:{cause}" for cause in PHASE_STOP_CAUSES),
)
TAU_EVENTS: tuple[str, ...] = ("τ1", "τ2", "τ3", "τ4")
PHASE_EVENTS: tuple[str, ...] = (*(f"E{n}" for n in range(1, 19)), *TAU_EVENTS)
EVENT_PRIORITY: tuple[tuple[str, ...], ...] = (
    ("E5", "E10"),
    ("E18",),
    ("E6",),
    ("E11",),
    ("E2",),
    ("E1", "E3", "E4", "E7", "E8", "E12", "E13", "E14"),
    TAU_EVENTS,
)
PHASE_HUMAN_EVENTS = frozenset({"E15", "E16", "E17"})
PHASE_CRASH_RECOVERY: dict[str, str] = {
    "plan:active": "reenter_loop",
    "plan:approved": "recover_pending_op",
    "plan:pc_done": "reevaluate_tau2_tau3",
    "transition:prepared": "rerun_tau3_admit",
    "transition:admitted": "rerun_tau4",
    "exec:active": "resume_row",
    "exec:finalizing": "recover_pending_op",
}
PHASE_PARK_BEFORE_EXEC = frozenset(
    {"plan:approved", "plan:pc_done", "transition:prepared"}
)
PHASE_EXEC_BEGUN = frozenset({"transition:admitted", "exec:active", "exec:finalizing"})
LOOP_CAUSES = frozenset({"round_cap", "reviewer_unavailable"})
ADMISSION_REASONS = frozenset({"path_busy", "lease_held", "store_refused"})
RESOLUTIONS = frozenset({"rebuild", "discard"})
VERDICT_DIR = ".agent/context/handoffs/"
REMOVAL_EVENTS: tuple[str, ...] = ("worktree_removal_started", "worktree_removed")
NO_RECORD_IDLE_S = 600
PAYLOAD_INVALID = "payload_invalid"


def pick_event(events: Sequence[str]) -> str:
    """R§4.4 event priority: the one pending event a transaction takes.

    A human-invoked event (E15, E16, E17) is never pending with another, and E9 is never
    pending at all (the monitor writes it); either is a ``ValueError``.
    """
    pending = set(events)
    if not pending:
        raise ValueError("no pending event")
    unknown = pending - set(PHASE_EVENTS)
    if unknown:
        raise ValueError(f"unknown events: {sorted(unknown)}")
    if "E9" in pending:
        raise ValueError("E9 is written by the monitor, never pending")
    if pending & PHASE_HUMAN_EVENTS:
        if len(pending) > 1:
            raise ValueError("a human-invoked event is never pending with another")
        return next(iter(pending))
    for group in EVENT_PRIORITY:
        for event in group:
            if event in pending:
                return event
    raise ValueError(f"no priority for {sorted(pending)}")


def _fact(facts: Mapping[str, Any], name: str) -> bool:
    """A guard fact: true only when it is ``True`` (a missing fact is false)."""
    return facts.get(name) is True


def _text(value: object) -> bool:
    """A non-empty string."""
    return isinstance(value, str) and bool(value)


def _pending_fact(facts: Mapping[str, Any]) -> str:
    """The ``pending_op`` fact, ``none`` when it is absent or empty."""
    value = facts.get("pending_op")
    return value if isinstance(value, str) and value else "none"


def _phase_payload_ok(event: str, payload: Mapping[str, Any]) -> bool:
    """The R5-8 payload types of one event (a field the table does not use is not checked)."""
    if event == "E2":
        return payload.get("cause") in LOOP_CAUSES
    if event in ("E3", "E4"):
        if not _text(payload.get("op_id")):
            return False
        if event == "E3":
            return _match(ROOT_RE, payload.get("ref_new"))
        return all(
            key not in payload or _text(payload[key]) for key in ("phase", "reason")
        )
    if event in ("E5", "E10"):
        return _text(payload.get("code"))
    if event == "E6":
        return _is_int(payload.get("tokens"), 0)
    if event == "E7":
        return _text(payload.get("expected")) and _text(payload.get("found"))
    if event == "E8":
        return payload.get("reason") in ADMISSION_REASONS
    if event == "E11":
        return _is_int(payload.get("wait_elapsed"), 0) and (
            "brief" not in payload or _text(payload["brief"])
        )
    if event == "E12":
        return _text(payload.get("receipt"))
    if event == "E13":
        return _text(payload.get("receipt")) and _text(payload.get("seal"))
    if event == "E14":
        return _text(payload.get("receipt")) and _text(payload.get("reason"))
    if event in ("E15", "E16", "E17"):
        if not _text(payload.get("start_record")):
            return False
        if event == "E17":
            return _match(UUID_RE, payload.get("message_uuid"))
        if event == "E15":
            return all(
                key not in payload or _text(payload[key])
                for key in ("suspended", "pending_op", "resolution")
            )
        return True
    if event == "E18":
        return _text(payload.get("row")) and _match(
            UUID_RE, payload.get("message_uuid")
        )
    return True


def _phase_result(
    state: str,
    event: str,
    to: str,
    guard: str,
    last: Mapping[str, Any] | None,
    facts: Mapping[str, Any],
    *,
    suspended: str | None = None,
    pending_op: str | None = None,
    parked_by: str | None = None,
) -> dict[str, Any]:
    """One outcome; a ``STOPPED:*`` or ``PARKED:*`` successor carries what a resume needs.

    A stay in a terminal state keeps the stop's ``suspended``, ``pending_op`` and
    ``parked_by``, so the next event still reads them from the last record.
    """
    out: dict[str, Any] = {
        "event": event,
        "from": state,
        "to": to,
        "guard_result": guard,
    }
    if not to.startswith(("STOPPED:", "PARKED:")):
        return out
    if to == state and suspended is None:
        for key in ("suspended", "pending_op", "parked_by"):
            if last is not None and key in last:
                out[key] = last[key]
        return out
    out["suspended"] = suspended if suspended is not None else state
    out["pending_op"] = pending_op if pending_op is not None else _pending_fact(facts)
    if to == PHASE_PARKED:
        out["parked_by"] = parked_by if parked_by is not None else "authority"
    return out


def _phase_resume(
    state: str,
    payload: Mapping[str, Any],
    facts: Mapping[str, Any],
    last: Mapping[str, Any] | None,
) -> tuple[str, str, str | None]:
    """E15 on ``PARKED:approved`` or a ``STOPPED:*``: ``(to, guard_result, parked_by)``.

    A failed re-verification of authority (V-A to V-10) parks a stop whose ``suspended`` is
    before execution and stops (``STOPPED:decision``) one after it began (D-6 C).
    """
    target = last.get("suspended") if last is not None else None
    if target not in PHASE_NONTERMINALS:
        return state, "guard_failed:resume", None
    if "suspended" in payload and payload["suspended"] != target:
        return state, PAYLOAD_INVALID, None
    if state == PHASE_PARKED:
        if last is not None and last.get("parked_by") == "exec_after_plan":
            return state, "guard_failed:resume", None
        if not _fact(facts, "resume_valid"):
            return state, "guard_failed:resume", None
        if not _fact(facts, "authority_ok"):
            return state, "guard_failed:authority", None
        return cast(str, target), "passed", None
    resolution = payload.get("resolution")
    if state in ("STOPPED:no_record", "STOPPED:ambiguous"):
        if resolution is None:
            return state, "guard_failed:resolution", None
        if resolution not in RESOLUTIONS:
            return state, PAYLOAD_INVALID, None
    if not _fact(facts, "resume_valid"):
        return state, "guard_failed:resume", None
    if resolution == "discard" and state in ("STOPPED:no_record", "STOPPED:ambiguous"):
        return "STOPPED:decision", "passed", None
    if not _fact(facts, "authority_ok"):
        if target in PHASE_EXEC_BEGUN:
            return "STOPPED:decision", "guard_failed:authority", None
        return PHASE_PARKED, "guard_failed:authority", "authority"
    return cast(str, target), "passed", None


def _phase_fork(payload: Mapping[str, Any], facts: Mapping[str, Any]) -> None:
    """E16: a fresh ``<slug>-fork-<n>`` with verified authority, else ``fork_refused``."""
    plan, new_plan = facts.get("plan"), payload.get("new_plan")
    if not (
        isinstance(plan, str)
        and isinstance(new_plan, str)
        and re.fullmatch(rf"{re.escape(plan)}-fork-\d+", new_plan)
        and SLUG_RE.fullmatch(new_plan)
    ):
        raise Refusal("fork_refused", "new_plan")
    if not _match(SAFE_NAME_RE, payload.get("new_run_id")):
        raise Refusal("fork_refused", "new_run_id")
    if not _fact(facts, "fork_verified"):
        raise Refusal("fork_refused", "unverified")


def phase_step(
    last: Mapping[str, Any] | None,
    event: str,
    payload: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> dict[str, Any]:
    """R§4.4 one step of the transition table: the outcome of ``event`` after ``last``.

    The outcome holds ``event``, ``from``, ``to`` and ``guard_result``, and for a
    ``STOPPED:*`` or ``PARKED:*`` successor ``suspended``, ``pending_op`` (and ``parked_by``).
    A stay or an ``ignored`` pair has ``to == from``. E9 refuses ``monitor_only``; E15, E16
    and E17 on ``DONE`` refuse ``done``; E16 that fails refuses ``fork_refused``.
    """
    state = "plan:active" if last is None else str(last.get("to"))
    if state not in PHASE_STATES:
        raise Refusal("phase_state", state)
    if event not in PHASE_EVENTS:
        raise Refusal("schema", f"event:{event}")
    if event == "E9":
        raise Refusal("monitor_only", "E9")
    if state == "DONE" and event in PHASE_HUMAN_EVENTS:
        raise Refusal("done", event)

    def result(
        to: str,
        guard: str = "passed",
        *,
        suspended: str | None = None,
        pending_op: str | None = None,
        parked_by: str | None = None,
    ) -> dict[str, Any]:
        return _phase_result(
            state,
            event,
            to,
            guard,
            last,
            facts,
            suspended=suspended,
            pending_op=pending_op,
            parked_by=parked_by,
        )

    nonterminal = state in PHASE_NONTERMINALS
    terminal = state == PHASE_PARKED or state.startswith("STOPPED:")
    listed = (
        (nonterminal and event in ("E5", "E6", "E11", "E18"))
        or (event == "E10" and state in ("exec:active", "exec:finalizing"))
        or (event == "E2" and state in ("plan:active", "exec:active"))
        or (state, event)
        in {
            ("plan:active", "E1"),
            ("plan:approved", "τ1"),
            ("plan:approved", "E3"),
            ("plan:approved", "E4"),
            ("plan:pc_done", "τ2"),
            ("plan:pc_done", "τ3"),
            ("plan:pc_done", "E7"),
            ("transition:prepared", "τ3"),
            ("transition:prepared", "E7"),
            ("transition:prepared", "E8"),
            ("transition:admitted", "τ4"),
            ("transition:admitted", "E8"),
            ("exec:active", "E12"),
            ("exec:finalizing", "E13"),
            ("exec:finalizing", "E14"),
            (PHASE_PARKED, "E17"),
        }
        or (terminal and event in ("E15", "E16"))
    )
    if not listed:
        return result(state, "ignored")
    if not _phase_payload_ok(event, payload):
        return result(state, PAYLOAD_INVALID)

    if event in ("E5", "E10"):
        if state in PHASE_PARK_BEFORE_EXEC:
            return result(PHASE_PARKED, parked_by="authority")
        return result("STOPPED:decision")
    if event == "E6":
        return result("STOPPED:budget")
    if event == "E11":
        gate = facts.get("gate_wait_s")
        if _is_int(gate, 0) and cast(int, payload["wait_elapsed"]) >= cast(int, gate):
            return result("STOPPED:decision")
        return result(state, "guard_failed:wait")
    if event == "E18":
        if _fact(facts, "row_closed"):
            return result("STOPPED:human_stop")
        return result(state, "guard_failed:row")
    if event == "E2":
        return result(f"STOPPED:{payload['cause']}")
    if event == "E1":
        if not str(payload.get("verdict_path", "")).startswith(VERDICT_DIR) or not (
            _match(REL_RE, payload.get("verdict_path"))
        ):
            return result(state, PAYLOAD_INVALID)
        if _fact(facts, "verdict_ok"):
            return result("plan:approved")
        return result(state, "guard_failed:verdict")
    if event == "τ1":
        if not _fact(facts, "commit_plan"):
            return result("plan:pc_done")
        return result(state, "guard_failed:commit_plan")
    if event == "E3":
        op_id = cast(str, payload["op_id"])
        for name, guard in (
            ("commit_plan", "commit_plan"),
            ("pc_reserved", "reservation"),
            ("pc_reconciled", "reconciled"),
            ("ref_matches", "ref"),
        ):
            if not _fact(facts, name):
                return result(
                    "STOPPED:ambiguous", f"guard_failed:{guard}", pending_op=op_id
                )
        return result("plan:pc_done")
    if event == "E4":
        return result("STOPPED:decision", pending_op=cast(str, payload["op_id"]))
    if event == "τ2":
        if not _fact(facts, "exec_after_plan") and not _fact(facts, "e17_recorded"):
            return result(PHASE_PARKED, parked_by="exec_after_plan")
        return result(state, "guard_failed:exec_after_plan")
    if event == "τ3" and state == "plan:pc_done":
        eap = _fact(facts, "exec_after_plan")
        authority = (eap and _fact(facts, "exec_start_reserved")) or (
            not eap and _fact(facts, "e17_recorded")
        )
        if not authority:
            return result(PHASE_PARKED, "guard_failed:authority", parked_by="authority")
        if not _fact(facts, "base_matches"):
            return result(PHASE_PARKED, "guard_failed:base", parked_by="base")
        return result("transition:prepared")
    if event == "τ3":
        if all(_fact(facts, name) for name in ("lease", "path_free", "binding_active")):
            return result("transition:admitted")
        return result(PHASE_PARKED, "guard_failed:admission", parked_by="admission")
    if event == "E7":
        return result(PHASE_PARKED, parked_by="base")
    if event == "E8":
        if state == "transition:admitted":
            return result("STOPPED:ambiguous")
        return result(PHASE_PARKED, parked_by="admission")
    if event == "τ4":
        if _fact(facts, "worktree_proven"):
            return result("exec:active")
        return result("STOPPED:ambiguous", "guard_failed:worktree")
    if event == "E12":
        if _fact(facts, "readiness_ok"):
            return result("exec:finalizing")
        return result(state, "guard_failed:readiness")
    if event == "E13":
        if _fact(facts, "final_ok"):
            return result("DONE")
        return result("STOPPED:decision", "guard_failed:final")
    if event == "E14":
        return result("STOPPED:decision")
    if event == "E17":
        if (
            last is not None
            and last.get("parked_by") == "exec_after_plan"
            and _fact(facts, "start_valid")
        ):
            return result("plan:pc_done")
        return result(state, "guard_failed:start")
    if event == "E15":
        to, guard, parked_by = _phase_resume(state, payload, facts, last)
        if to == state:
            return result(state, guard)
        if to.startswith(("STOPPED:", "PARKED:")):
            return result(
                to,
                guard,
                suspended=cast(str, cast(Mapping[str, Any], last)["suspended"]),
                pending_op=str(cast(Mapping[str, Any], last).get("pending_op", "none")),
                parked_by=parked_by,
            )
        return result(to, guard)
    _phase_fork(payload, facts)
    return result("plan:active")


# -- R§4.4 the transition records in the authority store --------------------------------------


def _phase_rel(plan: str, run_id: str, name: str) -> str:
    """A store-relative path under ``ops/<plan>/<run_id>/``."""
    return f"ops/{plan}/{run_id}/{name}"


def _phase_names(plan: str, run_id: str) -> None:
    """The plan slug and run id of a phase record path."""
    if not SLUG_RE.fullmatch(plan):
        raise Refusal("binding", "plan_slug")
    if not SAFE_NAME_RE.fullmatch(run_id):
        raise Refusal("schema", "run_id")


def _read_records(repo: Repo, rel: str, key: str) -> list[dict[str, Any]]:
    """The ``{key: [...]}`` list of one ops file, numbered ``seq`` 1 to n; ``[]`` when absent."""
    data = _read_bytes(repo.store / rel)
    if data is None:
        return []
    try:
        doc = _load_json(data)
    except ValueError as exc:
        raise Refusal("store_malformed", rel) from exc
    items = cast(dict[str, Any], doc).get(key) if isinstance(doc, dict) else None
    if not isinstance(items, list):
        raise Refusal("store_malformed", rel)
    records = cast(list[object], items)
    for index, item in enumerate(records, start=1):
        if not isinstance(item, dict) or cast(dict[str, Any], item).get("seq") != index:
            raise Refusal("store_malformed", f"{rel}:{index}")
    return cast(list[dict[str, Any]], records)


def _phase_view(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``{state, seq}`` of the last record whose ``to`` differs from its ``from``."""
    for record in reversed(records):
        if record["to"] != record["from"]:
            return {"state": record["to"], "seq": record["seq"]}
    return {"state": "plan:active", "seq": 0}


def _phase_files(
    plan: str, run_id: str, records: Sequence[Mapping[str, Any]]
) -> dict[str, bytes]:
    """``transitions.json`` (the truth) and ``state.json`` (its view) of one run."""
    view = _phase_view(records)
    return {
        _phase_rel(plan, run_id, "transitions.json"): _json_bytes(
            {"transitions": list(records)}
        ),
        _phase_rel(plan, run_id, "state.json"): _json_bytes(
            {"plan": plan, "run_id": run_id, **view}
        ),
    }


def _with_meta_inventory(
    meta: Mapping[str, Any], files: dict[str, bytes], added: Sequence[str]
) -> dict[str, bytes]:
    """Add store.json to a transaction when it creates files the inventory does not yet list."""
    inventory = cast(list[str], meta["inventory"])
    missing = [rel for rel in added if rel not in inventory]
    if missing:
        files["store.json"] = _json_bytes(
            {**meta, "inventory": sorted({*inventory, *missing})}
        )
    return files


def _tau_stay(
    records: Sequence[Mapping[str, Any]], event: str
) -> dict[str, Any] | None:
    """The stay of ``event`` since the last entry: τ1 to τ4 run once per entry (R5-8)."""
    for record in reversed(records):
        if record["to"] != record["from"] or record["event"] in ("E15", "E17"):
            return None
        if record["event"] == event:
            return dict(record)
    return None


def _run_batches(repo: Repo, plan: str, run_id: str) -> dict[str, int | None]:
    """The batch records ``<run>/<op>/batch.json`` of this run: ``{op: count}`` (R2-F2).

    An unreadable record has the count ``None``: the batch stays pending, so its recovery
    meets the record's ``op_file`` stop instead of a silent ``none``.
    """
    folder = repo.store / "ops" / plan / run_id
    out: dict[str, int | None] = {}
    if not SAFE_NAME_RE.fullmatch(run_id) or not folder.is_dir():
        return out
    for path in sorted(folder.glob("*/batch.json")):
        try:
            record = cast(dict[str, Any], _load_json(_read_bytes(path) or b""))
            count = cast(dict[str, Any], record["identity"])["count"]
        except (ValueError, KeyError, TypeError):
            count = None
        out[path.parent.name] = count if _is_int(count, 1) else None
    return out


def _run_pending_op(repo: Repo, plan: str, run_id: str) -> str:
    """The last commit op of this run that is not ``reconciled``, else ``none``.

    A batch is one op (R§4.5: one reservation). Its sub-op ``<op>/<n>`` counts as the batch
    ``<op>``, the id the driver recovers, and the batch stays pending until as many sub-ops
    are reconciled as its record declares, so a crash between packets still names it (R2-F2).
    """
    open_ops: list[str] = []
    reconciled: dict[str, int] = {}
    for op in _plan_ops(repo, plan):
        if op["run_id"] != run_id:
            continue
        name = cast(str, op["op"])
        batch, _, number = name.rpartition("/")
        if batch and number.isascii() and number.isdigit():
            name = batch
            if op["phase"] == "reconciled":
                reconciled[batch] = reconciled.get(batch, 0) + 1
                continue
        elif op["phase"] == "reconciled":
            continue
        if name in open_ops:
            open_ops.remove(name)
        open_ops.append(name)
    for batch, count in _run_batches(repo, plan, run_id).items():
        if batch not in open_ops and (
            count is None or reconciled.get(batch, 0) < count
        ):
            open_ops.append(batch)
    return open_ops[-1] if open_ops else "none"


def _verdict_ok(repo: Repo, plan: str, path: object) -> bool:
    """E1: the verdict file exists under the handoffs folder, says ``approved``, for this plan."""
    if not (
        isinstance(path, str) and path.startswith(VERDICT_DIR) and _match(REL_RE, path)
    ):
        return False
    text = _read_text(repo.top / path)
    if text is None:
        return False
    try:
        meta = _frontmatter(text)
    except Refusal:
        return False
    return (
        meta is not None
        and meta.get("plan") == plan
        and meta.get("verdict") == "approved"
    )


def _row_closed(repo: Repo, plan: str, row: object) -> bool:
    """E18: the task row named ``row`` has a last cell of ``[x]`` or ``[B]``."""
    if not isinstance(row, str):
        return False
    text = _read_text(_plan_dir(repo, plan) / "task.md")
    if text is None:
        return False
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.startswith("|"):
            continue
        cells = [
            cell.strip().strip("`").strip()
            for cell in line.strip().strip("|").split("|")
        ]
        if cells and cells[0] == row and cells[-1].startswith(("[x]", "[B]")):
            return True
    return False


def _phase_effective(repo: Repo, plan: str) -> dict[str, Any]:
    """The plan's effective values (V-A, V-0 to V-7), ``{}`` when the plan does not verify."""
    try:
        _gate(repo, None)
        return _verify_plan(repo, plan, None).effective
    except (Refusal, NonAuthorizing):
        return {}


def _authority_ok(repo: Repo, plan: str) -> bool:
    """E15/E17: V-A to V-10 pass for the plan against the locked store."""
    try:
        _gate(repo, None)
        verified = _verify_plan(repo, plan, None)
        _store_checks(repo, verified, act=None, op=None, reader=True)
    except (Refusal, NonAuthorizing):
        return False
    return True


def _fork_target(repo: Repo, plan: str, payload: Mapping[str, Any]) -> Verified | None:
    """E16: the fork's verified carriers when its slug is fresh and its grant is recorded."""
    new_plan, new_run = payload.get("new_plan"), payload.get("new_run_id")
    if not (
        isinstance(new_plan, str)
        and re.fullmatch(rf"{re.escape(plan)}-fork-\d+", new_plan)
        and SLUG_RE.fullmatch(new_plan)
        and _match(SAFE_NAME_RE, new_run)
    ):
        return None
    folder = repo.store / "ops" / new_plan
    if folder.is_dir() and any(folder.glob("*/transitions.json")):
        return None
    try:
        _gate(repo, None)
        verified = _verify_plan(repo, new_plan, None)
        store = _load_store(repo)
    except (Refusal, NonAuthorizing):
        return None
    return verified if verified.mu in store.grants else None


def _phase_facts(
    repo: Repo,
    plan: str,
    run_id: str,
    event: str,
    payload: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The guard facts the engine owns; they override the caller's."""
    facts: dict[str, Any] = {
        "plan": plan,
        "pending_op": _run_pending_op(repo, plan, run_id),
    }
    if event == "E1":
        facts["verdict_ok"] = _verdict_ok(repo, plan, payload.get("verdict_path"))
    if event == "E18":
        facts["row_closed"] = _row_closed(repo, plan, payload.get("row"))
    if event in ("τ1", "τ2", "τ3", "E3"):
        effective = _phase_effective(repo, plan)
        facts["commit_plan"] = effective.get("commit_plan") is True
        facts["exec_after_plan"] = effective.get("exec_after_plan") is True
        facts["e17_recorded"] = any(
            record["event"] == "E17" and record["guard_result"] == "passed"
            for record in records
        )
    if event in ("E15", "E17"):
        facts["authority_ok"] = _authority_ok(repo, plan)
    if event == "E16":
        facts["fork_verified"] = _fork_target(repo, plan, payload) is not None
    return facts


def _phase_record(
    outcome: Mapping[str, Any],
    *,
    seq: int,
    from_seq: int,
    payload: Mapping[str, Any],
    op_id: str,
    ts: str,
    by: str,
) -> dict[str, Any]:
    """One transition record of the op schema (``$defs/transition``)."""
    record: dict[str, Any] = {
        "seq": seq,
        "from": outcome["from"],
        "from_seq": from_seq,
        "event": outcome["event"],
        "payload": dict(payload),
        "guard_result": outcome["guard_result"],
        "to": outcome["to"],
        "op_id": op_id,
        "ts": ts,
        "by": by,
    }
    for key in ("suspended", "pending_op", "parked_by"):
        if key in outcome:
            record[key] = outcome[key]
    return record


def _fork_files(
    repo: Repo, plan: str, payload: Mapping[str, Any], record: Mapping[str, Any]
) -> dict[str, bytes]:
    """E16: the fork's first record and, on a shared grant, the origin's consumed acts."""
    verified = _fork_target(repo, plan, payload)
    if verified is None:
        raise Refusal("fork_refused", "unverified")
    new_plan, new_run = cast(str, payload["new_plan"]), cast(str, payload["new_run_id"])
    files = _phase_files(new_plan, new_run, [record])
    grant = _load_store(repo).grants[verified.mu]
    consumed = cast(dict[str, dict[str, Any]], grant["consumed"])
    if plan in consumed:
        merged = {**consumed[plan], **consumed.get(new_plan, {})}
        if merged != consumed.get(new_plan):
            files[f"grants/{verified.mu}.json"] = _json_bytes(
                {**grant, "consumed": {**consumed, new_plan: merged}}
            )
    return files


def record_transition(
    repo: Path | Repo,
    *,
    plan: str,
    run_id: str,
    event: str,
    payload: Mapping[str, Any],
    by: str,
    facts: Mapping[str, Any] | None = None,
    from_seq: int | None = None,
    op_id: str = "none",
) -> dict[str, Any]:
    """R5-8: evaluate ``event`` against the last record and append one record, under the lock.

    A ``from_seq`` older than the last record is re-evaluated against the last record. A τ
    event that already stayed since the last entry is not appended again; its stay is
    returned. A passed E16 writes the fork's first record under ``ops/<new_plan>/`` and leaves
    the original's records unchanged.
    """
    handle = _as_repo(repo)
    _phase_names(plan, run_id)
    if not _text(by):
        raise Refusal("schema", "by")
    if op_id != "none" and not SAFE_NAME_RE.fullmatch(op_id):
        raise Refusal("schema", "op_id")
    try:
        data = cast(dict[str, Any], json.loads(json.dumps(dict(payload))))
    except (TypeError, ValueError) as exc:
        raise Refusal("schema", "payload") from exc
    given = dict(facts or {})
    with _locked(handle, by):
        _recover(handle)
        handle.refresh()
        meta = _identity(handle)
        rel = _phase_rel(plan, run_id, "transitions.json")
        records = _read_records(handle, rel, "transitions")
        last = records[-1] if records else None
        seq = int(last["seq"]) if last is not None else 0
        if from_seq is not None and from_seq != seq:
            _log(
                "phase_reevaluated",
                plan=plan,
                run_id=run_id,
                phase_event=event,
                from_seq=from_seq,
                seq=seq,
            )
        if event in TAU_EVENTS:
            repeat = _tau_stay(records, event)
            if repeat is not None:
                _log(
                    "phase_tau_once",
                    plan=plan,
                    run_id=run_id,
                    phase_event=event,
                    seq=repeat["seq"],
                )
                return repeat
        known = _phase_facts(handle, plan, run_id, event, data, records)
        outcome = phase_step(last, event, data, {**given, **known})
        _crash(handle, "phase_record")
        _crash(handle, f"phase_record@{outcome['from']}")
        ts = _ts(handle)
        if event == "E16":
            record = _phase_record(
                outcome,
                seq=1,
                from_seq=0,
                payload={
                    **data,
                    "forked_from": {"plan": plan, "run_id": run_id, "seq": seq},
                },
                op_id=op_id,
                ts=ts,
                by=by,
            )
            files = _fork_files(handle, plan, data, record)
        else:
            record = _phase_record(
                outcome,
                seq=seq + 1,
                from_seq=seq,
                payload=data,
                op_id=op_id,
                ts=ts,
                by=by,
            )
            files = _phase_files(plan, run_id, [*records, record])
        _txn(handle, _with_meta_inventory(meta, files, list(files)))
    _log(
        "phase_recorded",
        plan=plan,
        run_id=run_id,
        phase_event=event,
        to=record["to"],
        seq=record["seq"],
    )
    if event != "E16":
        _sync_credits_view(run_id, _phase_view([*records, record]))
    return record


def _sync_credits_view(run_id: str, view: Mapping[str, Any]) -> None:
    """R§4.4: write the credits store's derived view after the record, in this process.

    Only a credits run writes it: ``CREDITS_STATE_DB`` is set and ``CREDITS_RUN_ID`` names
    this run. The record is the truth, so a failed view write is logged and never fails the
    record; the monitor and the next record write the view again.
    """
    db = os.environ.get("CREDITS_STATE_DB")
    if not db or os.environ.get("CREDITS_RUN_ID") != run_id:
        return
    tool = Path(__file__).resolve().parent / "credits_state.py"
    argv = [
        sys.executable,
        "-X",
        "utf8",
        str(tool),
        "--db",
        db,
        "phase_sync",
        "--run-id",
        run_id,
        "--state",
        str(view["state"]),
        "--seq",
        str(view["seq"]),
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            argv, capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log("phase_view_sync_failed", run_id=run_id, error=str(exc))
        return
    if proc.returncode != 0:
        _log(
            "phase_view_sync_failed",
            run_id=run_id,
            exit_code=proc.returncode,
            output=(proc.stdout + proc.stderr).strip()[-400:],
        )


def phase_transitions(
    repo: Path | Repo, *, plan: str, run_id: str
) -> list[dict[str, Any]]:
    """The transition records of one run (``[]`` before the first)."""
    handle = _as_repo(repo)
    _phase_names(plan, run_id)
    return _read_records(
        handle, _phase_rel(plan, run_id, "transitions.json"), "transitions"
    )


def phase_state(repo: Path | Repo, *, plan: str, run_id: str) -> dict[str, Any]:
    """``{state, seq}`` of one run: the last entry, ``plan:active`` and ``0`` before one."""
    return _phase_view(phase_transitions(repo, plan=plan, run_id=run_id))


def record_removal(
    repo: Path | Repo,
    *,
    plan: str,
    run_id: str,
    event: str,
    path: str,
    manifest_digest: str,
    by: str,
    row: str,
) -> dict[str, Any]:
    """H2-3c: append a worktree removal record while the run is ``exec:active``, in order."""
    handle = _as_repo(repo)
    _phase_names(plan, run_id)
    if event not in REMOVAL_EVENTS:
        raise Refusal("schema", "removal_event")
    if not (
        _text(path) and _match(HEX64_RE, manifest_digest) and _text(by) and _text(row)
    ):
        raise Refusal("schema", "removal_fields")
    with _locked(handle, by):
        _recover(handle)
        handle.refresh()
        meta = _identity(handle)
        records = _read_records(
            handle, _phase_rel(plan, run_id, "transitions.json"), "transitions"
        )
        state = _phase_view(records)["state"]
        if state != "exec:active":
            raise Refusal("phase_state", state)
        rel = _phase_rel(plan, run_id, "removal.json")
        removals = _read_records(handle, rel, "removals")
        done = [cast(str, item["event"]) for item in removals]
        expected = [] if event == REMOVAL_EVENTS[0] else [REMOVAL_EVENTS[0]]
        if done != expected:
            raise Refusal("removal_order", f"{event}:after:{','.join(done) or 'none'}")
        record = {
            "seq": len(removals) + 1,
            "run_id": run_id,
            "event": event,
            "path": path,
            "manifest_digest": manifest_digest,
            "by": by,
            "row": row,
            "ts": _ts(handle),
        }
        files = {rel: _json_bytes({"removals": [*removals, record]})}
        _txn(handle, _with_meta_inventory(meta, files, [rel]))
    _log("worktree_removal_recorded", plan=plan, run_id=run_id, phase_event=event)
    return record


def phase_removals(
    repo: Path | Repo, *, plan: str, run_id: str
) -> list[dict[str, Any]]:
    """The removal records of one run (``[]`` before the first)."""
    handle = _as_repo(repo)
    _phase_names(plan, run_id)
    return _read_records(handle, _phase_rel(plan, run_id, "removal.json"), "removals")


def resume_state(repo: Path | Repo, *, plan: str, run_id: str) -> str:
    """The state a resume of one run returns to (AC-F.2).

    A nonterminal state is itself; a ``STOPPED:*`` or ``PARKED:*`` state is the last
    record's ``suspended``. ``DONE`` is immutable and refuses ``phase_done``.
    """
    records = phase_transitions(repo, plan=plan, run_id=run_id)
    state = cast(str, _phase_view(records)["state"])
    if state in PHASE_NONTERMINALS:
        return state
    if state == "DONE":
        raise Refusal("phase_done", f"{plan}/{run_id}")
    suspended = records[-1].get("suspended") if records else None
    if not isinstance(suspended, str) or suspended not in PHASE_NONTERMINALS:
        raise Refusal("phase_state", f"{state}:suspended:{suspended}")
    return suspended


def resume_facts(
    repo: Path | Repo, *, plan: str, run_id: str, state: str
) -> dict[str, bool]:
    """The store facts of the AC-F.2 resume check for one run in ``state``.

    One consistent read of the authority store after V-0 to V-7 (a refusal propagates):
    ``reservation_present`` (``plan:pc_done``: no plan commit is enabled, or its act is
    reserved; ``transition:prepared``: ``exec_start`` is reserved), ``binding_active`` (a
    session holds the plan ``active``), ``acts_unconsumed`` (``exec_commit`` is not
    reserved, or only by this run's open op) and ``removal_recorded``.
    """
    handle = _as_repo(repo)
    _phase_names(plan, run_id)
    if state not in PHASE_NONTERMINALS:
        raise Refusal("phase_state", state)
    verified = _verify_plan(handle, plan, None)

    def read() -> tuple[Store, dict[str, Any] | None]:
        return _store_checks(handle, verified, act=None, op=None, reader=True)

    store, grant = _snapshot(handle, read)
    consumed = cast(
        dict[str, dict[str, Any]],
        cast(dict[str, Any], (grant or {}).get("consumed", {})).get(plan, {}),
    )
    if state == "plan:pc_done":
        reserved = verified.effective.get("commit_plan") is not True or (
            "plan_commit" in consumed
        )
    elif state == "transition:prepared":
        reserved = "exec_start" in consumed
    else:
        reserved = True
    binding = any(
        entry.get("plan") == plan and entry.get("state") == "active"
        for record in store.sessions.values()
        for entry in cast(list[dict[str, Any]], record.get("plans", []))
    )
    commit = consumed.get("exec_commit")
    unconsumed = commit is None or commit.get("op_id") == _run_pending_op(
        handle, plan, run_id
    )
    return {
        "reservation_present": reserved,
        "binding_active": binding,
        "acts_unconsumed": unconsumed,
        "removal_recorded": bool(phase_removals(handle, plan=plan, run_id=run_id)),
    }


# -- the caller facts of ``credits_msg.py phase`` (EA-21, EA-22) ------------------------------


def authority_ok(repo: Path | Repo, plan: str) -> bool:
    """V-A to V-10 pass for the plan against the locked store (the E15/E17 fact)."""
    return _authority_ok(_as_repo(repo), plan)


def effective_values(repo: Path | Repo, plan: str) -> dict[str, Any]:
    """The plan's effective values (V-A, V-0 to V-7); ``{}`` when the plan does not verify."""
    return _phase_effective(_as_repo(repo), plan)


def plan_ops(repo: Path | Repo, plan: str) -> list[dict[str, Any]]:
    """The commit ops of one plan: ``{op, run_id, act, phase, commit, parent, ts, packet}``."""
    return _plan_ops(_as_repo(repo), plan)


def consumed_acts(repo: Path | Repo, plan: str) -> dict[str, dict[str, Any]]:
    """The grant's ``consumed[plan]`` entries, one consistent read after V-0 to V-7.

    A refusal propagates. A plan whose grant records nothing gives ``{}``.
    """
    handle = _as_repo(repo)
    verified = _verify_plan(handle, plan, None)

    def read() -> tuple[Store, dict[str, Any] | None]:
        return _store_checks(handle, verified, act=None, op=None, reader=True)

    _store, grant = _snapshot(handle, read)
    consumed = cast(dict[str, Any], (grant or {}).get("consumed", {}))
    return dict(cast(dict[str, dict[str, Any]], consumed.get(plan, {})))


def reserve_act(repo: Path | Repo, plan: str, act: str, op: str) -> dict[str, Any]:
    """``reserve <act> --plan <plan> --op <op>`` as a function; the same op is idempotent (V-8).

    A refusal propagates (``Refusal`` or ``NonAuthorizing``), as the verb's would.
    """
    if act not in ACTS:
        raise Refusal("schema", "act")
    if not SAFE_NAME_RE.fullmatch(op):
        raise Refusal("schema", "op_id")
    handle = _as_repo(repo)
    policy = _gate(handle, act)
    verified = _verify_plan(handle, plan, act)
    return _reserve(handle, verified, act, op, policy)


def typed_human_text(repo: Path | Repo, session: str, uid: str) -> str | None:
    """The text of the typed human record ``uid`` of ``session`` (V-1, V-2), else ``None``.

    The E17 ``start_valid`` fact: the transcript is this project's own, and ``uid`` names
    exactly one typed human record of that session. A missing transcript or any other
    record gives ``None``.
    """
    try:
        transcript = _load_transcript(_as_repo(repo), session)
        _raw, record = _typed_record(transcript, uid, session)
    except Refusal:
        return None
    return _human_text(record)


def _stop_no_record(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``stop --reason no_record``: the monitor's E9 record once the four conditions hold.

    Under the lock: the run's process is dead, its transcript has been idle for the
    no-record window, ``--expect-seq`` is the last record and the state is non-terminal.
    Then E9 is recorded (``STOPPED:no_record``, ``suspended: from``) and the task's
    ``stop_gate`` is released to the human gate.
    """
    plan, run_id = cast(str, args.plan), cast(str, args.run)
    _phase_names(plan, run_id)
    task = _plan_dir(repo, plan) / "task.md"
    with _locked(repo, "monitor"):
        _recover(repo)
        repo.refresh()
        meta = _identity(repo)
        rel = _phase_rel(plan, run_id, "transitions.json")
        records = _read_records(repo, rel, "transitions")
        last = records[-1] if records else None
        seq = int(last["seq"]) if last is not None else 0
        state = str(last["to"]) if last is not None else "plan:active"
        start = _pid_start(cast(int, args.pid))
        dead = start is None or (
            start != "unknown"
            and not process_start_matches(start, cast(str, args.pid_start))
        )
        try:
            mtime: float | None = Path(cast(str, args.transcript)).stat().st_mtime
        except OSError:
            mtime = None
        idle = mtime is not None and _now(repo).timestamp() - mtime >= NO_RECORD_IDLE_S
        failed = [
            name
            for name, ok in (
                ("pid_alive", dead),
                ("transcript_active", idle),
                ("seq_moved", args.expect_seq == seq),
                ("terminal", state in PHASE_NONTERMINALS),
            )
            if not ok
        ]
        if failed:
            raise Refusal("no_record_not_met", ",".join(failed))
        record = _phase_record(
            {
                "from": state,
                "event": "E9",
                "guard_result": "passed",
                "to": "STOPPED:no_record",
                "suspended": state,
                "pending_op": _run_pending_op(repo, plan, run_id),
            },
            seq=seq + 1,
            from_seq=seq,
            payload={
                "pid": args.pid,
                "pid_start": args.pid_start,
                "transcript": display_path(cast(str, args.transcript)),
            },
            op_id="none",
            ts=_ts(repo),
            by="monitor",
        )
        _crash(repo, "phase_record")
        files = _phase_files(plan, run_id, [*records, record])
        _txn(repo, _with_meta_inventory(meta, files, list(files)))
        _edit_frontmatter(task, stop_gate="released:human-gate")
    _log("phase_no_record", plan=plan, run_id=run_id, seq=record["seq"])
    return EXIT_OK, {
        "result": "stopped",
        "authorized": False,
        "failure": False,
        "plan": plan,
        "run": run_id,
        "state": "STOPPED:no_record",
        "seq": record["seq"],
    }


# -- the verbs ------------------------------------------------------------------------------


def _refusal(reason: str, *, effective: bool) -> dict[str, Any]:
    """The EA-5 refusal object (``verify`` and ``reserve`` add the fail-closed effective values)."""
    out: dict[str, Any] = {
        "result": "refused",
        "reason": reason,
        "authorized": False,
        "failure": True,
    }
    if effective:
        out["effective"] = dict(FAIL_CLOSED)
    return out


def _non_authorizing(kind: str) -> dict[str, Any]:
    """The EA-5 manual or legacy object."""
    return {"result": kind, "reason": kind, "authorized": False, "failure": False}


Outcome = tuple[int, dict[str, Any]]


def _cmd_verify(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``verify``: V-A to V-10; writes nothing."""
    act = cast(str, args.act)
    policy = _gate(repo, act)
    verified = _verify_plan(repo, cast(str, args.plan), act)
    op = cast("str | None", args.op)
    store, _grant = _snapshot(
        repo, lambda: _store_checks(repo, verified, act=act, op=op, reader=True)
    )
    _check_context(store, verified.plan, act, policy)
    return EXIT_OK, {
        "result": "verified",
        "authorized": True,
        "failure": False,
        "act": act,
        "plan": verified.plan,
        "op": op,
        "fixture": repo.marked,
        "effective": verified.effective,
    }


def _cmd_reserve(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``reserve``: verify, then record the reservation under the writer lock."""
    act = cast(str, args.act)
    policy = _gate(repo, act)
    verified = _verify_plan(repo, cast(str, args.plan), act)
    entry = _reserve(repo, verified, act, cast(str, args.op), policy)
    return EXIT_OK, {
        "result": "reserved",
        "authorized": True,
        "failure": False,
        "act": act,
        "plan": verified.plan,
        "op": args.op,
        "entry": entry,
        "fixture": repo.marked,
        "effective": verified.effective,
    }


def _target(repo: Repo, args: argparse.Namespace) -> Verified:
    """The verified ``--plan`` carriers or ``--block`` file of ``init`` and ``inspect``."""
    if args.block is not None:
        return _verify_block(repo, _load_block_file(Path(cast(str, args.block))))
    return _verify_plan(repo, cast(str, args.plan), None)


def _cmd_init(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``init``: V-A (no capability), V-0 to V-7, then the store and the grant."""
    _gate(repo, None)
    return _initialize(repo, _target(repo, args))


def _cmd_inspect(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``inspect``: a read-only report; a manual block answers before V-A."""
    if args.block is not None:
        kind = _check_block(_load_block_file(Path(cast(str, args.block))))
        if kind != "v1":
            return EXIT_OK, _non_authorizing(kind)
    policy = _gate(repo, None)
    verified = _target(repo, args)
    report: dict[str, Any] = {"store": "missing", "consumed": {}, "acts": {}}
    grant: dict[str, Any] | None = None
    if (repo.store / "store.json").exists():
        _store, grant = _snapshot(
            repo,
            lambda: _store_checks(
                repo, verified, act=None, op=None, reader=True, check_consumed=False
            ),
        )
        report["store"] = "present"
    consumed = (
        cast(dict[str, Any], grant["consumed"]).get(verified.plan, {}) if grant else {}
    )
    report["consumed"] = consumed
    capabilities = cast(dict[str, str], policy["capabilities"])
    for act in ACTS:
        if capabilities[act] == "off":
            state = "capability"
        elif (
            act not in verified.reference.auth["grants"]
            or not verified.effective[ENABLING[act]]
        ):
            state = "not_granted"
        elif act in consumed:
            state = "consumed"
        else:
            state = "available"
        report["acts"][act] = state
    return EXIT_OK, {
        "result": "inspected",
        "authorized": False,
        "failure": False,
        "plan": verified.plan,
        "message_uuid": verified.mu,
        "effective": verified.effective,
        "fixture": repo.marked,
        "report": report,
    }


def _cmd_limits_check(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``limits-check``: a plan's loosened ``review_limits`` against the typed offer (AC-13).

    Read-only. Passes only when the plan's grant verifies (V-A to V-7), the authorization
    is ``self-contained`` (the human typed the offer, so the human typed the limits), the
    store (when there is one) agrees with it, and the offer's ``review_limits`` equal the
    plan's block and the task's block (when the task carries one) key for key.
    """
    if not _is_windows():
        raise Refusal("disabled", "not_windows")
    _gate(repo, None)
    plan = cast(str, args.plan)
    verified = _verify_plan(repo, plan, None)
    if verified.reference.auth["form"] != "self-contained":
        raise Refusal("consent", "limits_need_self_contained")
    if (repo.store / "store.json").exists():
        _snapshot(
            repo,
            lambda: _store_checks(
                repo, verified, act=None, op=None, reader=True, check_consumed=False
            ),
        )
    offered = verified.reference.offer.get("review_limits")
    if offered is None:
        raise Refusal("binding", "review_limits_not_offered")
    ledger = _review_ledger()
    folder = _plan_dir(repo, verified.plan)
    try:
        block = ledger.load_plan_limits(folder / "implementation-plan.md")
        task = ledger.load_plan_limits(folder / "task.md")
    except ledger.FailClosed as exc:
        raise Refusal("schema", "review_limits_malformed") from exc
    if block is None:
        raise Refusal("binding", "review_limits_missing")
    if task is not None and task != block:
        raise Refusal("binding", "review_limits_task_differs")
    if offered != block:
        raise Refusal("binding", "review_limits_differs")
    return EXIT_OK, {
        "result": "limits_verified",
        "authorized": True,
        "failure": False,
        "plan": verified.plan,
        "message_uuid": verified.mu,
        "review_limits": block,
        "fixture": repo.marked,
    }


def _status(repo: Repo, plan: str | None) -> dict[str, Any]:
    """``status``: whether V-A passes, and why not; with ``plan``, whether it is done."""
    try:
        _gate(repo, None)
    except Refusal as exc:
        reason = exc.detail if exc.reason == "disabled" and exc.detail else exc.reason
        out: dict[str, Any] = {
            "result": "status",
            "enabled": False,
            "reason": reason,
            "fixture": repo.marked,
        }
        if plan is not None:
            out.update(
                {
                    "plan": plan,
                    "kind": "unknown",
                    "done": False,
                    "reasons": [exc.reason],
                    "generation_state": "missing",
                    "generation": "none",
                }
            )
        return out
    out = {
        "result": "status",
        "enabled": True,
        "reason": "ok",
        "fixture": repo.marked,
    }
    if plan is not None:
        out.update(_final_status(repo, plan))
    return out


def plan_status(repo: Path | Repo, plan: str) -> dict[str, Any]:
    """The DONE predicate (``status --plan`` as a function, for ``tools/stop_gate.py``).

    Never raises a refusal: a refused plan is not done, and the refusal is its reason.
    """
    try:
        handle = _as_repo(repo)
        return _status(handle, plan)
    except Refusal as exc:
        return {
            "result": "status",
            "enabled": False,
            "reason": exc.reason,
            "plan": plan,
            "kind": "unknown",
            "done": False,
            "reasons": [exc.reason],
            "generation_state": "missing",
            "generation": "none",
        }


def _cmd_status(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``status --json [--plan SLUG]``."""
    return EXIT_OK, _status(repo, cast("str | None", args.plan))


def _cmd_bind(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``bind --pending`` or ``bind --plan``."""
    _gate(repo, None)
    context = cast("str | None", args.context)
    if args.pending is not None:
        return _bind(
            repo,
            cast(str, args.pending),
            cast(str, args.session),
            active=False,
            context=context,
        )
    return _bind(
        repo,
        cast(str, args.plan),
        cast(str, args.session),
        active=True,
        context=context,
    )


def _cmd_revoke(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``revoke``."""
    _gate(repo, None)
    return _revoke(repo, cast(str, args.session), cast(str, args.message))


def _cmd_unlock(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``unlock`` (no V-A: it must work while the store is broken)."""
    if not TOKEN_RE.fullmatch(cast(str, args.expect)):
        raise Refusal("token_mismatch", "token_shape")
    return _unlock(
        repo, cast(str, args.expect), cast(str, args.session), cast(str, args.message)
    )


def _cmd_repair(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``repair`` (no V-A: it must work while the store is broken); ``repair --final``."""
    if args.final:
        return _repair_final(repo, cast(str, args.plan))
    return _repair(
        repo,
        cast(str, args.session),
        cast(str, args.message),
        migrate=bool(args.migrate),
    )


def _cmd_document(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``document``: the grouping ``Run parameters:`` line for a plan's task block."""
    _gate(repo, None)
    carriers = _load_carriers(repo, cast(str, args.plan))
    block, auth = carriers.task_block, carriers.auth
    values = " · ".join(
        f"{key}={str(block[key]).lower() if isinstance(block[key], bool) else block[key]}"
        for key in SIGMA_KEYS
    )
    line = f"Run parameters: {values} · authorization={str(auth['session'])[:8]}/{auth['message_uuid']}"
    return EXIT_OK, {
        "result": "documented",
        "authorized": False,
        "failure": False,
        "plan": carriers.plan,
        "line": line,
    }


def _cmd_resolve(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``resolve``: the effective run parameters of a plan after V-0 to V-7 (the store is not read)."""
    _gate(repo, None)
    verified = _verify_plan(repo, cast(str, args.plan), None)
    return EXIT_OK, {
        "result": "resolved",
        "authorized": False,
        "failure": False,
        "plan": verified.plan,
        "effective": verified.effective,
        "grants": verified.reference.auth["grants"],
    }


def _cmd_final(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``final``: list the plan's final-receipt generations; ``--produce`` or ``--seal`` one."""
    plan = cast(str, args.plan)
    if not SLUG_RE.fullmatch(plan):
        raise Refusal("binding", "plan_slug")
    if args.produce:
        return _produce(repo, plan)
    if args.seal:
        return _seal(repo, plan)
    store = _snapshot(repo, lambda: _load_store(repo))
    generations = [
        {"generation": n, "sealed": receipt["sealed"]}
        for n, receipt in sorted(store.finals.get(plan, []), key=lambda item: item[0])
    ]
    return EXIT_OK, {
        "result": "final",
        "authorized": False,
        "failure": False,
        "plan": plan,
        "generations": generations,
    }


def _cmd_stop(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``stop``: a plan's task ``status`` and ``stop_gate`` (read-only).

    ``stop --reason no_record`` is the monitor's E9 write (``_stop_no_record``).
    """
    if args.reason is not None:
        return _stop_no_record(repo, args)
    plan = cast(str, args.plan)
    if not SLUG_RE.fullmatch(plan):
        raise Refusal("binding", "plan_slug")
    text = _read_text(_plan_dir(repo, plan) / "task.md")
    if text is None:
        raise Refusal("binding", "task_missing")
    meta = _frontmatter(text) or {}
    return EXIT_OK, {
        "result": "stop",
        "authorized": False,
        "failure": False,
        "plan": plan,
        "status": meta.get("status"),
        "stop_gate": meta.get("stop_gate"),
    }


def _cmd_audit(repo: Repo, args: argparse.Namespace) -> Outcome:
    """``audit``: the last lines of ``audit.jsonl`` (read-only)."""
    text = _read_text(repo.store / "audit.jsonl") or ""
    entries: list[object] = []
    for line in text.splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except ValueError:
                entries.append({"unparsed": line})
    limit = cast(int, args.limit)
    return EXIT_OK, {
        "result": "audit",
        "authorized": False,
        "failure": False,
        "entries": entries[-limit:],
    }


# -- the closeout validator's view (AC-B.13) -------------------------------------------------


def check_block(value: object) -> str:
    """V-0 over a ``run_parameters`` block; return ``v1``, ``manual`` or ``legacy`` (else ``Refusal``)."""
    return _check_block(value)


def sigma_of(values: Mapping[str, Any]) -> dict[str, Any]:
    """The five run parameters of a carrier."""
    return _sigma(values)


def within(low: Mapping[str, Any], high: Mapping[str, Any]) -> bool:
    """``low`` is as tight as ``high`` or tighter."""
    return _within(low, high)


Handler = Callable[[Repo, argparse.Namespace], Outcome]
_EFFECTIVE_VERBS = frozenset({"verify", "reserve"})


def _parser() -> argparse.ArgumentParser:
    """The command line: a global ``--repo``, the fourteen verbs and ``limits-check``.

    ``limits-check`` stays out of ``RP_VERBS``: it serves ``review_ledger.py begin``, not
    the run-parameters acts.
    """
    parser = argparse.ArgumentParser(
        prog="run_parameters",
        description=__doc__.split("\n", 1)[0] if __doc__ else None,
    )
    parser.add_argument(
        "--repo", default=".", help="the repository (default: the current directory)"
    )
    verbs = parser.add_subparsers(dest="verb", required=True, metavar="VERB")

    def verb(name: str, handler: Handler, text: str) -> argparse.ArgumentParser:
        sub = verbs.add_parser(name, help=text, description=text)
        sub.set_defaults(handler=handler)
        return sub

    sub = verb("verify", _cmd_verify, "Verify one act for a plan; writes nothing.")
    sub.add_argument("act", choices=ACTS)
    sub.add_argument("--plan", required=True)
    sub.add_argument("--op")
    sub = verb("reserve", _cmd_reserve, "Verify one act and reserve it for an op.")
    sub.add_argument("act", choices=ACTS)
    sub.add_argument("--plan", required=True)
    sub.add_argument("--op", required=True)
    for name, handler, text in (
        ("init", _cmd_init, "Create the store if needed and record the grant."),
        (
            "inspect",
            _cmd_inspect,
            "Report a plan's or a block's grant; writes nothing.",
        ),
    ):
        sub = verb(name, handler, text)
        target = sub.add_mutually_exclusive_group(required=True)
        target.add_argument("--plan")
        target.add_argument("--block")
    sub = verb(
        "limits-check",
        _cmd_limits_check,
        "Verify that a plan's loosened review_limits are in the human-typed offer; "
        "writes nothing.",
    )
    sub.add_argument("--plan", required=True)
    sub = verb(
        "status", _cmd_status, "Report whether the run-parameters authority is enabled."
    )
    sub.add_argument("--json", action="store_true", help="print JSON (always on)")
    sub.add_argument("--plan", help="also report whether the plan is done")
    sub = verb("bind", _cmd_bind, "Bind a session to a plan (pending or active).")
    target = sub.add_mutually_exclusive_group(required=True)
    target.add_argument("--pending")
    target.add_argument("--plan")
    sub.add_argument("--session", required=True)
    sub.add_argument("--context", choices=("headless", "interactive"))
    for name, handler, text in (
        ("revoke", _cmd_revoke, "Revoke a grant from a typed human record."),
        (
            "repair",
            _cmd_repair,
            "Repair the store from a typed human record; keeps every fact.",
        ),
    ):
        sub = verb(name, handler, text)
        sub.add_argument("--session", required=name == "revoke")
        sub.add_argument("--message", required=name == "revoke")
        if name == "repair":
            sub.add_argument(
                "--migrate", action="store_true", help="re-home the store after a move"
            )
            sub.add_argument(
                "--final",
                action="store_true",
                help="open the next final generation under a superseding finalize grant",
            )
            sub.add_argument("--plan", help="the plan of --final")
    sub = verb("unlock", _cmd_unlock, "Remove a dead writer's lock with its token.")
    sub.add_argument("--expect", required=True)
    sub.add_argument("--session", required=True)
    sub.add_argument("--message", required=True)
    for name, handler, text in (
        (
            "document",
            _cmd_document,
            "Print the grouping Run parameters line of a plan.",
        ),
        ("resolve", _cmd_resolve, "Print a plan's effective run parameters."),
        ("stop", _cmd_stop, "Print a plan's task status and stop gate."),
    ):
        sub = verb(name, handler, text)
        sub.add_argument("--plan", required=True)
        if name == "stop":
            sub.add_argument("--run", help="the run of --reason")
            sub.add_argument("--reason", choices=("no_record",))
            sub.add_argument("--expect-seq", type=int)
            sub.add_argument("--pid", type=int)
            sub.add_argument("--pid-start")
            sub.add_argument("--transcript")
    sub = verb(
        "final",
        _cmd_final,
        "List a plan's final-receipt generations, or produce or seal the next one.",
    )
    sub.add_argument("--plan", required=True)
    step = sub.add_mutually_exclusive_group()
    step.add_argument(
        "--produce", action="store_true", help="validate and write a receipt"
    )
    step.add_argument("--seal", action="store_true", help="seal the latest receipt")
    sub = verb("audit", _cmd_audit, "Print the last audit lines.")
    sub.add_argument("--limit", type=int, default=50)
    return parser


def _emit(out: Mapping[str, Any]) -> None:
    """One JSON object on stdout."""
    sys.stdout.write(json.dumps(out, sort_keys=True, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line, run one verb, print one JSON object, return the exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    verb = cast(str, args.verb)
    if verb == "repair":
        if args.final and (args.plan is None or args.migrate):
            parser.error("repair --final needs --plan and takes no --migrate")
        if not args.final and (args.session is None or args.message is None):
            parser.error("repair needs --session and --message (or --final --plan)")
    if verb == "stop" and args.reason is not None:
        missing = [
            flag
            for flag, value in (
                ("--run", args.run),
                ("--expect-seq", args.expect_seq),
                ("--pid", args.pid),
                ("--pid-start", args.pid_start),
                ("--transcript", args.transcript),
            )
            if value is None
        ]
        if missing:
            parser.error(f"stop --reason needs {' '.join(missing)}")
    effective = verb in _EFFECTIVE_VERBS
    try:
        repo = _open_repo(Path(cast(str, args.repo)))
        code, out = cast(Handler, args.handler)(repo, args)
    except Refusal as exc:
        _log("refused", verb=verb, reason=exc.reason, detail=exc.detail)
        if verb == "status":
            _emit(
                {
                    "result": "status",
                    "enabled": False,
                    "reason": exc.detail or exc.reason,
                }
            )
            return EXIT_OK
        _emit(_refusal(exc.reason, effective=effective))
        return EXIT_REFUSED
    except NonAuthorizing as exc:
        _emit(_non_authorizing(exc.kind))
        return EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 - the last guard prints one JSON object
        _log("internal_error", verb=verb, error=repr(exc), trace=traceback.format_exc())
        _emit(
            {
                "result": "error",
                "reason": "internal",
                "authorized": False,
                "failure": True,
            }
        )
        return EXIT_CRASH
    _emit(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
