"""Stop-gate hook — deterministic "definition of done" enforcement.

Purpose
-------
Agents exhibit a learned politeness/deference pattern: at a phase boundary
(implementation -> closeout, or H1 -> review -> H2) they offer the user an
"off-ramp" and end the turn before the approved plan's `task.md` is fully
checked off. Prose rules in `AGENTS.md` / the workflows *shift* that behaviour
but cannot guarantee it (it is a sampled RLHF prior). This script is the
deterministic backstop: wired as a harness **Stop hook**
(`.claude/settings.json`), it blocks the agent from ending its turn while the
active plan still has open task rows.

Arming and release (activation contract)
----------------------------------------
Stale ``status: "in_progress"`` plans are common (dozens exist), so status alone
cannot select the gated plan. A plan opts in explicitly:

- ``stop_gate: "armed"`` in the leading frontmatter, together with
  ``status: "in_progress"``, makes the file a candidate; the newest such file by
  mtime is the active plan. Files without the key are ignored regardless of
  status, so planning-phase and abandoned plans never wedge a session.
- ``stop_gate: "released:<reason>"`` with ``<reason>`` in ``round-cap``,
  ``reviewer-unavailable``, ``human-gate`` or ``handback`` records one of the
  four sanctioned stops (AGENTS.md §Execution Contract) in the durable file and
  lets the turn end; the reason is echoed to stderr.
- Any other value is treated as unarmed and a one-line warning goes to stderr.

Session ownership (concurrent sessions share one working tree)
--------------------------------------------------------------
A session is gated only by plans it owns: ``owned_plan_dirs`` reads the Stop
payload's ``transcript_path`` and collects the ``docs/execution/plans/<slug>/``
folders its file tools (Write, Edit, MultiEdit, NotebookEdit) wrote into. Reads,
searches and shell commands claim nothing, so one session's closeout rows never
block another session's stop. Without a ``transcript_path``, or when the
transcript cannot be read, selection stays repo-wide, the pre-ownership behaviour.
A plan edited only through shell commands is therefore not owned; plans are edited
with file tools in this repo.

Decision logic (harness-agnostic, unit-testable)
------------------------------------------------
- ``find_active_task_file`` -> the most-recently-modified armed (or released)
  ``in_progress`` ``task.md`` under ``docs/execution/plans/*/``, among the owned
  folders when ownership is known.
- ``count_open_rows`` -> the task-table rows whose **status cell** (the last
  table cell) is ``[ ]`` (not started) or ``[/]`` (in progress). The Status
  Legend is not matched because its open markers live in the *first* cell, and
  phase-divider rows have an empty status cell.
- ``evaluate`` -> ``(done, reason)``. ``done`` is True when there is no active
  plan, the active plan is released, or it has zero open rows.

Run-parameters plans (R§4.6, D-16)
----------------------------------
A Stop payload's session is first matched to a plan by ``discover``, from the two
binding copies: the task.md ``bound_sessions`` list and the authority store's
``sessions/<session>.json``. A plan both copies agree on is evaluated whatever the
mtime selection would pick; a disagreement (``tree_binding_missing``,
``binding_mismatch``, ``ambiguous_binding``, ``binding_lost``, ``store_missing``,
``store_unavailable``, ``binding_removed``, ``manual_downgrade``, ``handed_over``)
blocks and names itself. An unbound or pending session keeps today's selection. A
plan with a ``run-parameters/1`` grant then follows the grant rules: every acceptance
branch (``released:done``, all rows closed, a bound plan no longer ``in_progress``)
asks the DONE predicate ``plan_done`` (``run_parameters status --plan``), and a
``[B]`` row counts as closed only with its ``### B-<row>`` block. The other sanctioned
releases need no DONE check. On such a plan the loop-breaker logs
``emergency_release`` with the plan; legacy plans keep today's rules and log lines.

Hook plumbing (``main``) — payload contract
--------------------------------------------
``argv[0]`` is the repo root (the settings wiring passes ``"${CLAUDE_PROJECT_DIR}"``
because hooks run in the session's current directory, which may be a
subdirectory); with no argument the current directory is used. Stdin carries the
harness payload:

- empty stdin = diagnostic mode: evaluate, report on stderr, exit 0, never block
  (``uv run python tools/stop_gate.py`` stays usable by hand);
- non-empty stdin that is not a JSON object, lacks ``hook_event_name == "Stop"``,
  or lacks a string ``session_id`` -> fail open (exit 0, no stdout);
- a well-formed Stop payload -> on "not done" the hook emits
  ``{"decision": "block", "reason": ...}`` on stdout (Claude Code Stop-hook
  contract) and the agent must keep working.

A per-session block counter in the receipts dir (``{{PROJECT_NAME_UPPER}}_RECEIPTS``) breaks
runaway loops: after ``MAX_CONSECUTIVE_BLOCKS`` blocks the gate releases
(fail-open) so a genuinely stuck turn can still end. Diagnostics go to stderr
only; stdout carries the JSON verdict exclusively. When ``{{PROJECT_NAME_UPPER}}_HOOK_LOG``
names a file, every verdict (``block`` / ``release`` / ``allow``) appends one JSON
line there — the same durable evidence channel the PreToolUse hooks use, since
the counter itself is cleared on release and cannot serve as a receipt.

Allowed and released stops (never blocks, diagnostic runs or fail-open payloads)
are handed to the stop notifier, ``agent_notify.on_stop`` in the sibling
``tools/agent_notify.py``, loaded lazily. The hand-off is fail-open: an import
error or an exception from the notifier is recorded as one ``notify_error`` line
in ``{{PROJECT_NAME_UPPER}}_HOOK_LOG`` (when set) and the verdict, exit code and counter stay
exactly as they would be without it. The notifier writes only under its own
state directory.

This tool reports state; it never edits files.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

# After this many consecutive blocks for one session, release the gate so a
# genuinely-stuck turn is not wedged. Claude Code also self-caps at ~8 blocks;
# this is the explicit, harness-independent guard.
MAX_CONSECUTIVE_BLOCKS = 8

# Status-cell markers that mean "not finished".
_OPEN_MARKERS = {"[ ]", "[/]"}

# The sanctioned stops a plan may record in ``stop_gate: "released:<reason>"``.
# ``done`` is the DONE stop that a closed-out plan records at closeout.
RELEASE_REASONS = frozenset(
    {"round-cap", "reviewer-unavailable", "human-gate", "handback", "done"}
)
_ARMED = "armed"
_RELEASE_PREFIX = "released:"

_FRONTMATTER_STATUS = re.compile(
    r"^status:\s*[\"']?(?P<status>[A-Za-z_]+)", re.MULTILINE
)
_FRONTMATTER_STOP_GATE = re.compile(
    r"^stop_gate:\s*[\"']?(?P<value>[^\"'\r\n]*)", re.MULTILINE
)
_PLANS_DIR = "docs/execution/plans"
_PLANS_GLOB = f"{_PLANS_DIR}/*/task.md"

# The store's session-record states (``tools/run_parameters.py``), and the session ids
# that may name a record file.
_SESSION_STATES = frozenset({"pending", "active", "closed", "handed_over"})
_SAFE_SESSION = re.compile(r"[A-Za-z0-9_.-]+")

# File-writing tools and the input key that names the written path. A write through
# one of these inside a plan folder is what makes a session the plan's owner.
_WRITE_TOOLS = {
    "Write": "file_path",
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}


@dataclass(frozen=True)
class OpenRow:
    """A single unchecked task-table row, for the block reason."""

    ident: str
    marker: str


def _read_text(path: Path) -> str:
    """Read a file as UTF-8, tolerating a BOM. Returns '' on read error."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:  # pragma: no cover - defensive
        print(f"[stop_gate] could not read {path}: {exc}", file=sys.stderr)
        return ""


def _frontmatter_block(text: str) -> str | None:
    """Return the leading ``---`` ... ``---`` block, or None when there is none."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    return text[:end] if end != -1 else text


def frontmatter_status(text: str) -> str | None:
    """Return the front-matter ``status`` value, or None if absent.

    Only the leading ``---`` ... ``---`` block is considered, so a ``status:``
    appearing later in prose cannot be mistaken for the document status.
    """
    block = _frontmatter_block(text)
    if block is None:
        return None
    match = _FRONTMATTER_STATUS.search(block)
    return match.group("status").lower() if match else None


def frontmatter_stop_gate(text: str) -> str | None:
    """Return the front-matter ``stop_gate`` value (stripped), or None if absent."""
    block = _frontmatter_block(text)
    if block is None:
        return None
    match = _FRONTMATTER_STOP_GATE.search(block)
    return match.group("value").strip() if match else None


def release_reason(stop_gate_value: str | None) -> str | None:
    """Return the sanctioned release reason encoded in a ``stop_gate`` value, else None."""
    if not stop_gate_value or not stop_gate_value.startswith(_RELEASE_PREFIX):
        return None
    reason = stop_gate_value[len(_RELEASE_PREFIX) :].strip()
    return reason if reason in RELEASE_REASONS else None


def _status_cell(line: str) -> str | None:
    """Return the normalized status (last) cell of a markdown table row.

    Returns None for non-table lines, separator rows, and rows with an empty
    final cell (e.g. phase-divider rows).
    """
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    if not cells:
        return None
    last = cells[-1].strip().strip("`").strip()
    if not last or set(last) == {"-"}:  # empty cell or |---| separator
        return None
    return last


def count_open_rows(task_text: str) -> list[OpenRow]:
    """Return the task-table rows whose status cell is an open marker."""
    open_rows: list[OpenRow] = []
    for line in task_text.splitlines():
        marker = _status_cell(line)
        if marker not in _OPEN_MARKERS:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        ident = (
            cells[0] if cells and cells[0] else (cells[1] if len(cells) > 1 else "?")
        )
        open_rows.append(OpenRow(ident=ident.strip("`").strip(), marker=marker))
    return open_rows


def _is_gated(task_file: Path, text: str) -> bool:
    """True when the plan is ``in_progress`` and armed or released.

    An unrecognised ``stop_gate`` value is reported once on stderr and treated as
    unarmed, so a typo can never wedge or silently gate a session.
    """
    if frontmatter_status(text) != "in_progress":
        return False
    value = frontmatter_stop_gate(text)
    if value is None:
        return False
    if value == _ARMED or release_reason(value) is not None:
        return True
    print(
        f"[stop_gate] ignoring {task_file.as_posix()}: unknown stop_gate value "
        f'{value!r} (expected "armed" or "released:<'
        + "|".join(sorted(RELEASE_REASONS))
        + '>")',
        file=sys.stderr,
    )
    return False


def _path_key(path: Path) -> str:
    """Comparison key for a path: resolved, then case-folded where the OS is (Windows)."""
    return os.path.normcase(str(path.resolve()))


def _written_paths(entry: object) -> list[str]:
    """Return the file paths a transcript entry's file-tool ``tool_use`` blocks wrote."""
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return []
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    paths: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        key = _WRITE_TOOLS.get(str(block.get("name")))
        tool_input = block.get("input")
        if key is None or not isinstance(tool_input, dict):
            continue
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    return paths


def owned_plan_dirs(transcript: Path, repo_root: Path) -> set[Path] | None:
    """Return the plan folders this session wrote into, or None if the transcript is unreadable.

    Ownership is a file-tool write (``_WRITE_TOOLS``) inside
    ``docs/execution/plans/<slug>/`` recorded in the session's own transcript.
    Reads, searches and shell commands claim nothing, so a session that only
    inspected another session's plan is never gated by it. ``None`` tells the
    caller to fall back to repo-wide selection rather than disarm the gate.
    """
    try:
        lines = transcript.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"[stop_gate] transcript unreadable ({exc}) — gating repo-wide",
            file=sys.stderr,
        )
        return None

    plans_root = _path_key(repo_root / _PLANS_DIR)
    owned: set[Path] = set()
    for line in lines:
        # Cheap prefilter: most transcript lines carry no tool call at all.
        if '"tool_use"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        for raw_path in _written_paths(entry):
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = repo_root / candidate
            key = _path_key(candidate)
            prefix = plans_root + os.sep
            if not key.startswith(prefix):
                continue
            slug = key[len(prefix) :].split(os.sep, 1)[0]
            if slug:
                owned.add((repo_root / _PLANS_DIR / slug).resolve())
    return owned


def find_active_task_file(
    repo_root: Path, owned: set[Path] | None = None
) -> Path | None:
    """Return the most-recently-modified armed ``in_progress`` ``task.md``, or None.

    With ``owned`` (the session's plan folders, from ``owned_plan_dirs``) only those
    plans are candidates; ``None`` keeps repo-wide selection.
    """
    owned_keys = None if owned is None else {_path_key(p) for p in owned}
    candidates: list[tuple[float, Path]] = []
    for task_file in repo_root.glob(_PLANS_GLOB):
        if owned_keys is not None and _path_key(task_file.parent) not in owned_keys:
            continue
        if not _is_gated(task_file, _read_text(task_file)):
            continue
        try:
            candidates.append((task_file.stat().st_mtime, task_file))
        except OSError:  # pragma: no cover - defensive
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def evaluate(repo_root: Path, owned: set[Path] | None = None) -> tuple[bool, str]:
    """Decide whether the session may stop.

    Returns ``(done, reason)``. ``done`` is True when no armed in_progress plan
    exists (among ``owned`` when given), the active plan records a sanctioned
    release, or it has no open rows. ``reason`` is a concise, agent-facing message
    used when blocking.
    """
    done, reason = evaluate_detail(repo_root, owned)[:2]
    return done, reason


def evaluate_detail(
    repo_root: Path, owned: set[Path] | None = None
) -> tuple[bool, str, str, int, str | None]:
    """Decide whether the session may stop, with the facts the stop notifier needs.

    Returns ``(done, reason, kind, open_rows, task_file)``; ``evaluate`` returns
    the first two. ``kind`` is ``no_active_plan``, ``released``, ``rows_complete``
    or ``open_rows``; ``open_rows`` counts the active plan's unchecked rows (0 when
    there is no active plan); ``task_file`` is the active ``task.md`` as a POSIX
    path, or None.
    """
    return _evaluate(repo_root, owned)[:5]


Verdict = tuple[bool, str, str, int, str | None, str | None, str | None]


def _load_authority() -> ModuleType:
    """The run-parameters authority (``tools/run_parameters.py``), under this module's package."""
    name = "tools.run_parameters" if __package__ == "tools" else "run_parameters"
    return importlib.import_module(name)


def plan_done(repo_root: Path, plan: str) -> tuple[bool, list[str]]:
    """The DONE predicate (``run_parameters status --plan``): ``(done, reasons)``; never raises.

    A failure to load or run the authority is a not-done verdict whose reason names the
    exception, so the gate fails closed on a grant plan.
    """
    try:
        out = _load_authority().plan_status(repo_root, plan)
    except Exception as exc:
        return False, [f"authority_error:{type(exc).__name__}"]
    reasons = out.get("reasons") if isinstance(out, dict) else None
    done = isinstance(out, dict) and out.get("done") is True
    return done, [str(item) for item in reasons] if isinstance(reasons, list) else []


def _frontmatter_data(text: str) -> dict[str, object] | None:
    """The leading frontmatter as YAML, or None when there is none or it does not parse."""
    block = _frontmatter_block(text.replace("\r\n", "\n"))
    if block is None:
        return None
    try:
        import yaml  # the project venv carries PyYAML; imported only for carrier plans

        data = yaml.safe_load(block[3:])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _block_kind(text: str) -> str | None:
    """The ``run_parameters`` block kind of a carrier: ``v1``, ``manual``, ``legacy`` or None.

    None means the frontmatter has no block (a plan from before run parameters). A block
    the authority cannot check, or an authority that cannot load, counts as ``v1`` so a
    damaged grant plan stays under the grant rules (fail closed).
    """
    block = _frontmatter_block(text)
    if block is None or "run_parameters:" not in block:
        return None
    data = _frontmatter_data(text)
    if data is None:
        return "v1"
    if "run_parameters" not in data:
        return None
    try:
        kind = _load_authority().check_block(data["run_parameters"])
    except Exception:
        return "v1"
    return kind if kind in ("v1", "manual", "legacy") else "v1"


def _git_common_dir(repo_root: Path) -> Path | None:
    """The repository's common dir (where the authority store lives), or None."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    return Path(out) if out else None


def _read_json(path: Path) -> object:
    """A JSON file's value; raises ``ValueError`` when it does not parse, ``OSError`` on I/O."""
    return json.loads(path.read_text(encoding="utf-8"))


def _session_entries(record: object) -> list[tuple[str, str]] | None:
    """The ``(plan, state)`` entries of a session record, or None when its shape is wrong."""
    if not isinstance(record, dict):
        return None
    plans = record.get("plans")
    if not isinstance(plans, list):
        return None
    entries: list[tuple[str, str]] = []
    for item in plans:
        if not isinstance(item, dict):
            return None
        plan, state = item.get("plan"), item.get("state")
        if not isinstance(plan, str) or state not in _SESSION_STATES:
            return None
        entries.append((plan, str(state)))
    return entries


def _grant_revoked(store: Path, plan: str) -> bool:
    """Whether a grant that covers ``plan`` has a ``revoke`` line in ``revocations.jsonl``."""
    revoked: set[str] = set()
    try:
        lines = (store / "revocations.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("revoked"), str):
            revoked.add(value["revoked"])
    grants = store / "grants"
    if not revoked or not grants.is_dir():
        return False
    for path in sorted(grants.glob("*.json")):
        try:
            grant = _read_json(path)
        except (OSError, ValueError):
            continue
        offer = grant.get("offer") if isinstance(grant, dict) else None
        if not isinstance(offer, dict):
            continue
        scope = offer.get("scope")
        members = offer.get("members")
        covers = (isinstance(scope, dict) and scope.get("plan") == plan) or (
            isinstance(members, list) and plan in members
        )
        if covers and path.stem in revoked:
            return True
    return False


def _tree_plans(repo_root: Path, session: str) -> tuple[list[str], bool]:
    """The plans whose task.md ``bound_sessions`` lists ``session``, and whether any carrier exists.

    A carrier is a task.md whose frontmatter names ``run_parameters`` or ``bound_sessions``;
    with none in the repository, discovery needs no store read (every plan is legacy).
    """
    plans: list[str] = []
    carriers = False
    for task_file in sorted(repo_root.glob(_PLANS_GLOB)):
        block = _frontmatter_block(_read_text(task_file))
        if block is None or (
            "run_parameters:" not in block and "bound_sessions:" not in block
        ):
            continue
        carriers = True
        data = _frontmatter_data(_read_text(task_file))
        bound = data.get("bound_sessions") if data is not None else None
        if isinstance(bound, list) and session in bound:
            plans.append(task_file.parent.name)
    return plans, carriers


def discover(repo_root: Path, session: str) -> tuple[str, str | None]:
    """Find the plan a session stops on from both binding copies (R§4.6, D-16).

    The tree copy is each task.md ``bound_sessions`` list; the store copy is
    ``<common-dir>/run-parameters/sessions/<session>.json``. Returns ``(outcome, plan)``:
    ``bound`` (both copies agree on an active binding), ``pending`` (a pending store entry),
    ``today`` (no binding: today's selection), or a disagreement outcome from
    ``DISAGREEMENTS`` that blocks the stop.
    """
    tree, carriers = _tree_plans(repo_root, session)
    if not carriers:
        return "today", None
    if len(tree) > 1:
        return "ambiguous_binding", ",".join(tree)
    common = _git_common_dir(repo_root)
    store = common / "run-parameters" if common is not None else None
    entries: list[tuple[str, str]] | None = []
    record_found = False
    if store is not None and store.is_dir() and _SAFE_SESSION.fullmatch(session):
        path = store / "sessions" / f"{session}.json"
        if path.exists():
            record_found = True
            try:
                entries = _session_entries(_read_json(path))
            except (OSError, ValueError):
                entries = None
    if not tree:
        if entries is None:
            return "store_unavailable", None
        for state in ("active", "pending"):
            hit = next((plan for plan, st in entries if st == state), None)
            if hit is not None:
                return ("tree_binding_missing" if state == "active" else "pending"), hit
        return "today", None
    plan = tree[0]
    if store is None or not store.is_dir():
        return "store_missing", plan
    if entries is None:
        return "store_unavailable", plan
    if not record_found:
        return "binding_lost", plan
    states = [st for name, st in entries if name == plan]
    if "pending" in states:
        return "pending", plan
    if "active" in states:
        kind = _block_kind(_read_text(repo_root / _PLANS_DIR / plan / "task.md"))
        if kind in (None, "legacy"):
            return "binding_removed", plan
        if kind == "manual":
            if _grant_revoked(store, plan):
                return "today", None
            return "manual_downgrade", plan
        return "bound", plan
    if "handed_over" in states:
        return "handed_over", plan
    if any(st in ("pending", "active") for _, st in entries):
        return "binding_mismatch", plan
    if "closed" in states:
        return "today", None
    return "binding_lost", plan


def _grant_open_rows(text: str) -> list[OpenRow]:
    """Open rows on a grant plan: ``[ ]``/``[/]``, and ``[B]`` rows without a ``### B-<row>`` block."""
    rows = count_open_rows(text)
    for line in text.splitlines():
        if _status_cell(line) != "[B]":
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        ident = (cells[0] if cells and cells[0] else "?").strip("`").strip()
        heading = re.compile(rf"^###\s+B-{re.escape(ident)}\s*$", re.MULTILINE)
        if not heading.search(text):
            rows.append(
                OpenRow(ident=f"{ident} ([B] without ### B-{ident})", marker="[B]")
            )
    return rows


def _not_done(
    label: str, plan: str, rel: str, reasons: list[str], rows: int
) -> Verdict:
    detail = ", ".join(reasons) or "unknown"
    return (
        False,
        f"DONE not reached ({label}) for run-parameters plan {plan} in {rel}: "
        f"run_parameters status --plan {plan} reports [{detail}]. Finish the closeout "
        "(handoff, the approved execution review, reflection and metrics, then "
        "run_parameters final --produce/--seal) before ending the turn on DONE, or "
        'record another sanctioned stop with stop_gate: "released:<reason>".',
        label,
        rows,
        rel,
        None,
        plan,
    )


def _evaluate_grant(task_file: Path, text: str, plan: str, repo_root: Path) -> Verdict:
    """The grant rules (AC-D.1): every acceptance branch runs ``plan_done`` exactly once."""
    rel = task_file.as_posix()
    value = frontmatter_stop_gate(text)
    released = release_reason(value)
    rows = _grant_open_rows(text)
    if frontmatter_status(text) != "in_progress":
        done, reasons = plan_done(repo_root, plan)
        if done:
            return (
                True,
                f"Run-parameters plan {plan} is done ({rel}) — stop allowed.",
                "rows_complete",
                0,
                rel,
                None,
                plan,
            )
        return _not_done("no_active_task", plan, rel, reasons, len(rows))
    if released is not None and released != "done":
        return (
            True,
            f"stop_gate released:{released} recorded in {rel} — stop allowed.",
            "released",
            len(rows),
            rel,
            released,
            plan,
        )
    if released == "done":
        done, reasons = plan_done(repo_root, plan)
        if done:
            return (
                True,
                f"stop_gate released:done recorded in {rel} and the final receipt is "
                "sealed — stop allowed.",
                "released",
                len(rows),
                rel,
                "done",
                plan,
            )
        return _not_done("not_done", plan, rel, reasons, len(rows))
    if rows:
        verdict = _open_rows_verdict(rows, rel)
        return (*verdict[:6], plan)
    done, reasons = plan_done(repo_root, plan)
    if done:
        return (
            True,
            f"All task rows complete in {rel} and the final receipt is sealed — "
            "stop allowed.",
            "rows_complete",
            0,
            rel,
            None,
            plan,
        )
    return _not_done("not_done", plan, rel, reasons, 0)


def _open_rows_verdict(
    open_rows: list[OpenRow], rel: str
) -> tuple[bool, str, str, int, str | None, str | None]:
    sample = ", ".join(row.ident for row in open_rows[:6])
    more = "" if len(open_rows) <= 6 else f" (+{len(open_rows) - 6} more)"
    reason = (
        f"DONE not reached: {len(open_rows)} unchecked row(s) in {rel} "
        f"[{sample}{more}]. This is an approved-plan closeout in progress, not a "
        "stopping point. Re-read that task.md, finish the open rows in order "
        "(handoff -> dispatch /execution-critical-review -> reflection/metrics), "
        "and only end the turn on one of the four sanctioned stops "
        "(AGENTS.md §Execution Contract): DONE, review round cap, all reviewer "
        "rungs unavailable, or a human-decision gate (which includes the "
        "save-state hand-back on a harness with context_compaction: none). "
        'Record the stop by setting stop_gate: "released:<reason>" in task.md. '
        "An off-ramp like 'shall I continue, or do this in a separate session?' "
        "is a violation, not a courtesy."
    )
    return False, reason, "open_rows", len(open_rows), rel, None


def _evaluate(
    repo_root: Path, owned: set[Path] | None = None, session: str | None = None
) -> Verdict:
    """``evaluate_detail`` plus the parsed ``released:<reason>`` and the grant plan for ``main``.

    With ``session``, discovery runs first: a bound plan is evaluated by the grant rules
    whatever today's selection would pick, and a disagreement blocks. Otherwise today's
    selection runs, and a selected plan with a ``v1`` block follows the grant rules.
    """
    if session is not None:
        outcome, bound = discover(repo_root, session)
        if outcome == "bound" and bound is not None:
            task_file = repo_root / _PLANS_DIR / bound / "task.md"
            return _evaluate_grant(task_file, _read_text(task_file), bound, repo_root)
        if outcome not in ("today", "pending"):
            return (
                False,
                f"run-parameters binding {outcome} for session {session} "
                f"(plan {bound or 'unknown'}): the task.md bound_sessions copy and the "
                "store's sessions record disagree, so the gate cannot tell which plan "
                "this stop belongs to. Repair the binding (run_parameters bind / repair) "
                "or hand the plan over with run_parameters bind --plan; do not edit "
                "either copy by hand.",
                "binding",
                0,
                None,
                None,
                bound,
            )
    active = find_active_task_file(repo_root, owned)
    if active is None:
        if owned is not None:
            return (
                True,
                "No armed in_progress plan is owned by this session (none written "
                "by its file tools) — stop allowed.",
                "no_active_plan",
                0,
                None,
                None,
                None,
            )
        return (
            True,
            'No in_progress plan is armed (stop_gate: "armed") — stop allowed.',
            "no_active_plan",
            0,
            None,
            None,
            None,
        )

    text = _read_text(active)
    if _block_kind(text) == "v1":
        return _evaluate_grant(active, text, active.parent.name, repo_root)
    rel = active.as_posix()
    released = release_reason(frontmatter_stop_gate(text))
    open_rows = count_open_rows(text)
    if released is not None:
        return (
            True,
            f"stop_gate released:{released} recorded in {rel} — stop allowed.",
            "released",
            len(open_rows),
            rel,
            released,
            None,
        )

    if not open_rows:
        return (
            True,
            f"All task rows complete in {rel} — stop allowed.",
            "rows_complete",
            0,
            rel,
            None,
            None,
        )
    return (*_open_rows_verdict(open_rows, rel), None)


def _receipts_dir() -> Path:
    """Return the receipts directory, creating it if needed."""
    default = r"{{RECEIPTS_DIR}}" if os.name == "nt" else "/tmp/{{PROJECT_NAME}}"
    receipts = Path(os.environ.get("{{PROJECT_NAME_UPPER}}_RECEIPTS", default))
    try:
        receipts.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover - defensive
        return Path(".")
    return receipts


def _counter_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id) or "default"
    return _receipts_dir() / f"stop_gate_{safe}.count"


def _read_counter(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def _write_counter(path: Path, value: int) -> None:
    try:
        path.write_text(str(value), encoding="utf-8")
    except OSError:  # pragma: no cover - defensive
        pass


def _clear_counter(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _append_log(
    session_id: str, decision: str, blocks: int, plan: str | None = None
) -> None:
    """Append one JSON line to ``{{PROJECT_NAME_UPPER}}_HOOK_LOG`` when set; never raises.

    Fail-open by design: the log is evidence for the smoke receipt, and a write
    failure must never change the verdict or wedge the turn. ``plan`` (a run-parameters
    plan) adds a ``plan`` field; legacy lines keep their four fields.
    """
    fields: dict[str, object] = {
        "hook": "stop_gate",
        "session_id": session_id,
        "decision": decision,
        "blocks": blocks,
    }
    if plan is not None:
        fields["plan"] = plan
    _append_log_line(fields)


def _append_log_line(fields: dict[str, object]) -> None:
    """Append ``fields`` as one JSON line to ``{{PROJECT_NAME_UPPER}}_HOOK_LOG`` when set; never raises."""
    target = os.environ.get("{{PROJECT_NAME_UPPER}}_HOOK_LOG")
    if not target:
        return
    line = json.dumps(fields)
    try:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


_NOTIFIER_MODULE = "agent_notify"


def _load_notifier() -> ModuleType:
    """Return the sibling ``agent_notify`` module, loading it from its file on first use.

    A module already in ``sys.modules`` is reused; a ``None`` entry there means the
    import is disabled and raises ``ImportError``, as the import system does. The
    module is registered before it runs so its dataclasses can resolve their module.
    """
    if _NOTIFIER_MODULE in sys.modules:
        cached = sys.modules[_NOTIFIER_MODULE]
        if cached is None:
            raise ImportError(f"{_NOTIFIER_MODULE} is disabled in sys.modules")
        return cached
    path = Path(__file__).with_name(f"{_NOTIFIER_MODULE}.py")
    spec = importlib.util.spec_from_file_location(_NOTIFIER_MODULE, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {_NOTIFIER_MODULE} from {path.as_posix()}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_NOTIFIER_MODULE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_NOTIFIER_MODULE, None)
        raise
    return module


def _notify(
    payload: dict[str, object],
    decision: str,
    reason: str,
    kind: str,
    open_rows: int,
    task_file: str | None,
    release_reason: str | None,
) -> None:
    """Hand an allowed or released stop to ``agent_notify.on_stop``; never raises.

    Fail-open: any error is recorded as one ``notify_error`` gate-log line and
    otherwise ignored, so the gate's verdict, exit code and counter never depend
    on the notifier.
    """
    try:
        notifier = _load_notifier()
        notifier.on_stop(
            payload,
            decision,
            reason,
            kind,
            open_rows,
            task_file,
            release_reason=release_reason,
        )
    except Exception as exc:
        _append_log_line(
            {
                "hook": "stop_gate",
                "session_id": payload.get("session_id"),
                "decision": "notify_error",
                "error": type(exc).__name__,
            }
        )
        print(
            f"[stop_gate] notifier failed ({type(exc).__name__}) — ignored",
            file=sys.stderr,
        )


def _session_id(raw: str) -> str | None:
    """Return the Stop payload's ``session_id``, or None when the payload is not one.

    None means fail open: the caller exits 0 without a verdict. Only a JSON object
    with ``hook_event_name == "Stop"`` and a string ``session_id`` is a Stop payload.
    """
    try:
        payload = json.loads(raw)
    except ValueError:
        print("[stop_gate] stdin is not JSON — failing open", file=sys.stderr)
        return None
    if not isinstance(payload, dict):
        print(
            "[stop_gate] payload is not a JSON object — failing open", file=sys.stderr
        )
        return None
    if payload.get("hook_event_name") != "Stop":
        print("[stop_gate] payload is not a Stop event — failing open", file=sys.stderr)
        return None
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        print("[stop_gate] payload has no session_id — failing open", file=sys.stderr)
        return None
    return session_id


def _transcript_path(raw: str) -> Path | None:
    """Return the Stop payload's ``transcript_path``, or None when absent.

    Called only after ``_session_id`` accepted the payload. None means repo-wide
    selection (the pre-ownership behaviour), never "allow".
    """
    try:
        payload = json.loads(raw)
    except ValueError:  # pragma: no cover - _session_id already parsed it
        return None
    value = payload.get("transcript_path") if isinstance(payload, dict) else None
    return Path(value) if isinstance(value, str) and value else None


def _payload(raw: str) -> dict[str, object]:
    """Return the Stop payload object for the notifier; ``{}`` if it cannot be parsed.

    Called only after ``_session_id`` accepted the payload.
    """
    try:
        payload = json.loads(raw)
    except ValueError:  # pragma: no cover - _session_id already parsed it
        return {}
    return payload if isinstance(payload, dict) else {}


def main(argv: list[str] | None = None) -> int:
    """Hook entrypoint. Returns process exit code (always 0; verdict via stdout)."""
    argv = argv if argv is not None else sys.argv[1:]
    repo_root = Path(argv[0]).resolve() if argv else Path.cwd()

    raw = sys.stdin.read()
    if not raw.strip():
        # Diagnostic mode (run by hand): report, never block, touch no counter.
        done, reason = evaluate(repo_root)
        state = "stop allowed" if done else "would block"
        print(f"[stop_gate] diagnostic ({state}): {reason}", file=sys.stderr)
        return 0

    session_id = _session_id(raw)
    if session_id is None:
        return 0  # fail open: no stdout => stop allowed

    counter_file = _counter_path(session_id)
    transcript = _transcript_path(raw)
    owned = None if transcript is None else owned_plan_dirs(transcript, repo_root)
    done, reason, kind, open_rows, task_file, released, plan = _evaluate(
        repo_root, owned, session_id
    )

    if done:
        _clear_counter(counter_file)
        _append_log(session_id, "allow", 0)
        _notify(_payload(raw), "allow", reason, kind, open_rows, task_file, released)
        print(f"[stop_gate] {reason}", file=sys.stderr)
        return 0  # no stdout => stop allowed

    blocks = _read_counter(counter_file) + 1
    if blocks > MAX_CONSECUTIVE_BLOCKS:
        _clear_counter(counter_file)
        if plan is None:
            _append_log(session_id, "release", blocks)
        else:
            # A run-parameters plan: the loop-breaker is a non-DONE emergency release.
            _append_log(session_id, "emergency_release", blocks, plan)
        _notify(_payload(raw), "release", reason, kind, open_rows, task_file, released)
        print(
            f"[stop_gate] emergency release after {MAX_CONSECUTIVE_BLOCKS} blocks "
            f"(loop-breaker); the plan is not done — review manually.",
            file=sys.stderr,
        )
        return 0  # fail-open: never wedge a stuck turn

    _write_counter(counter_file, blocks)
    _append_log(session_id, "block", blocks)
    print(json.dumps({"decision": "block", "reason": reason}))  # stdout = verdict
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
