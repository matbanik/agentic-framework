"""R1-F7: ``credits_msg.py locate --session <id> --quote <text>`` (R§4.6.3).

Execution review round 1, finding 7: the planned ``locate`` verb was missing
(implementation-plan "credits_msg.py CLI verbs"; report R§4.6.3: "The interactive
agent finds the uuid with ``credits_msg.py locate --session <id> --quote
"<text>"``. That helper only proposes. The hook checks everything again, so a wrong
pick fails closed.").

The contract these tests fix:

* ``locate`` is read only. It needs no ``CREDITS_*`` value, opens no store and
  writes nothing.
* The transcript is ``<claude dir>/projects/<slug>/<session>.jsonl``; the claude
  dir is ``CLAUDE_CONFIG_DIR``, else ``~/.claude`` (``USERPROFILE``, then ``HOME``),
  as ``credits_state.transcript_path``. The slug is the one folder that holds the
  session (``transcript_missing`` when none, ``transcript_ambiguous`` when two).
* A candidate is a typed human entry of the session (R§4.6.3 step 4:
  ``is_human_entry`` and ``is_typed_turn``) whose normalized full text equals the
  normalized quote (step 6). One candidate: exit 0 with ``user_message_uuid``,
  ``prompt_id``, ``timestamp`` and ``line``. None: ``not_found``. Two or more:
  ``ambiguous`` with every candidate. Each refusal is exit 3.
* A bad ``--session`` (not a key) or ``--quote`` (empty) is a usage error, exit 2.

Every test runs the real tool in a subprocess against a temp home. Do not skip,
only, or early-return (G36).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

from test_credits_msg import MSG_TOOL
from test_credits_state import (
    REAL_DB_STATE_AT_IMPORT,
    ROOT,
    Out,
    Store,
    child_env,
    parse_out,
    real_db_state,
)

SESSION = "0596bd59-5711-4906-abbf-24bcfe7a7cc5"
OTHER_SESSION = "cccccccc-0000-4000-8000-000000000003"
PROJECT = "D:/locate-fixture"
QUOTE = "D-17: A, keep the cap"


def slug(project_root: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", project_root)


class Transcript:
    """An orchestrator transcript (JSON lines) built record by record."""

    def __init__(self, path: Path, session: str = SESSION) -> None:
        self.path = path
        self.session = session
        self.records: list[str] = []
        self.last: str | None = None
        self.seconds = 0

    def _put(self, record: dict[str, Any]) -> None:
        self.records.append(json.dumps(record))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes("".join(f"{r}\n" for r in self.records).encode("utf-8"))

    def _stamp(self) -> str:
        self.seconds += 1
        return f"2026-10-17T10:00:{self.seconds:02d}.000Z"

    def user(
        self,
        text: str,
        *,
        drop: tuple[str, ...] = (),
        extra: dict[str, Any] | None = None,
        content: Any = None,
    ) -> dict[str, Any]:
        """A typed entry with every field of R§4.6.3 step 4 (the M-6 shape)."""
        record: dict[str, Any] = {
            "parentUuid": self.last,
            "isSidechain": False,
            "promptId": str(uuid.uuid4()),
            "type": "user",
            "message": {
                "role": "user",
                "content": content
                if content is not None
                else [{"type": "text", "text": text}],
            },
            "uuid": str(uuid.uuid4()),
            "timestamp": self._stamp(),
            "origin": {"kind": "human"},
            "promptSource": "sdk",
            "turnOrigin": "human",
            "userType": "external",
            "sessionId": self.session,
            "version": "2.1.296",
        }
        for key in drop:
            record.pop(key, None)
        record.update(extra or {})
        self.last = str(record["uuid"])
        self._put(record)
        return record

    def assistant(self, text: str) -> None:
        uid = str(uuid.uuid4())
        self._put(
            {
                "parentUuid": self.last,
                "isSidechain": False,
                "message": {
                    "role": "assistant",
                    "type": "message",
                    "content": [{"type": "text", "text": text}],
                },
                "type": "assistant",
                "uuid": uid,
                "timestamp": self._stamp(),
                "sessionId": self.session,
            }
        )
        self.last = uid

    def raw(self, line: str) -> None:
        self.records.append(line)
        self.path.write_bytes("".join(f"{r}\n" for r in self.records).encode("utf-8"))


def transcript_at(
    base: Path, session: str = SESSION, project: str = PROJECT
) -> Transcript:
    return Transcript(base / "projects" / slug(project) / f"{session}.jsonl", session)


def locate(
    home: Path,
    *args: str,
    extra: dict[str, str] | None = None,
    config_dir: Path | None = None,
) -> Out:
    """Run ``credits_msg.py locate`` with ``~`` at ``home`` and no ``CREDITS_*``."""
    env = child_env({"USERPROFILE": str(home), "HOME": str(home), **(extra or {})})
    env.pop("CLAUDE_CONFIG_DIR", None)
    if config_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(MSG_TOOL), "locate", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
        cwd=ROOT,
        check=False,
    )
    return parse_out(proc.returncode, proc.stdout, proc.stderr)


def find(home: Path, quote: str = QUOTE, session: str = SESSION, **kw: Any) -> Out:
    return locate(home, "--session", session, "--quote", quote, **kw)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


# --- found -----------------------------------------------------------------------------


def test_r1_f7_locate_proposes_the_one_typed_entry(home: Path) -> None:
    """One typed entry equals the quote: exit 0 with its uuid and promptId."""
    tr = transcript_at(home / ".claude")
    tr.user("start the run")
    tr.assistant(f"Waiting at the gate. {QUOTE}")
    entry = tr.user(QUOTE)
    tr.assistant("ok")
    out = find(home)
    assert out.code == 0 and out.result == "ok", out.show()
    assert out.payload is not None
    assert out.payload["verb"] == "locate"
    assert out.payload["session"] == SESSION
    assert out.payload["user_message_uuid"] == entry["uuid"]
    assert out.payload["prompt_id"] == entry["promptId"]
    assert out.payload["timestamp"] == entry["timestamp"]
    assert out.payload["line"] == 3
    assert Path(out.payload["transcript"]).resolve() == tr.path.resolve()


def test_r1_f7_locate_normalizes_both_texts(home: Path) -> None:
    """NFC, CRLF, trim and whitespace runs fold as the verifier's step 6."""
    tr = transcript_at(home / ".claude")
    entry = tr.user("D-17:\r\n  A,   keep the cap ")
    out = find(home, "  D-17: A, keep\tthe cap")
    assert out.code == 0, out.show()
    assert out.payload is not None and out.payload["user_message_uuid"] == entry["uuid"]


def test_r1_f7_locate_reads_claude_config_dir_first(home: Path, tmp_path: Path) -> None:
    """CLAUDE_CONFIG_DIR replaces ~/.claude, as for the CLI and the verifier."""
    config = tmp_path / "config-dir"
    transcript_at(home / ".claude").user(QUOTE)
    entry = transcript_at(config).user(QUOTE)
    out = find(home, config_dir=config)
    assert out.code == 0, out.show()
    assert out.payload is not None and out.payload["user_message_uuid"] == entry["uuid"]


def test_r1_f7_locate_needs_no_store_and_writes_none(
    home: Path, tmp_path: Path
) -> None:
    """Read only: with a run's CREDITS_* values set, the store bytes stay the same."""
    st = Store(tmp_path / "store")
    st.root.mkdir()
    st.init()
    before = hashlib.sha256(st.db.read_bytes()).hexdigest()
    transcript_at(home / ".claude").user(QUOTE)
    out = find(
        home,
        extra={
            "CREDITS_RUN_ID": "run-x",
            "CREDITS_SEGMENT": "seg-x",
            "CREDITS_STATE_DB": str(st.db),
        },
    )
    assert out.code == 0, out.show()
    assert hashlib.sha256(st.db.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in st.root.iterdir()) == ["state.db"]


# --- not found -------------------------------------------------------------------------


def test_r1_f7_a_partial_quote_is_not_found(home: Path) -> None:
    """Step 6 needs equality: a substring of the entry does not match."""
    transcript_at(home / ".claude").user(QUOTE)
    out = find(home, "D-17: A")
    assert out.code == 3 and out.error == "not_found", out.show()


@pytest.mark.parametrize(
    "shape",
    [
        {"drop": ("turnOrigin",)},
        {"drop": ("promptId",)},
        {"extra": {"promptSource": "queued"}},
        {"extra": {"isMeta": True}},
        {"extra": {"isCompactSummary": True}},
        {"extra": {"origin": {"kind": "task-notification"}}},
        {"extra": {"sessionId": OTHER_SESSION}},
        {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": QUOTE}]},
    ],
    ids=[
        "no-turn-origin",
        "no-prompt-id",
        "queued-source",
        "meta",
        "compact-summary",
        "not-human",
        "other-session",
        "tool-result",
    ],
)
def test_r1_f7_an_entry_that_is_not_a_typed_human_turn_is_not_found(
    home: Path, shape: dict[str, Any]
) -> None:
    """Only a typed human entry of the session is a candidate (step 4)."""
    transcript_at(home / ".claude").user(QUOTE, **shape)
    out = find(home)
    assert out.code == 3 and out.error == "not_found", out.show()


def test_r1_f7_an_assistant_text_is_never_a_candidate(home: Path) -> None:
    """The quote inside an assistant record proposes nothing."""
    tr = transcript_at(home / ".claude")
    tr.user("start")
    tr.assistant(QUOTE)
    out = find(home)
    assert out.code == 3 and out.error == "not_found", out.show()


def test_r1_f7_a_missing_transcript_is_refused(home: Path) -> None:
    """No ``<session>.jsonl`` under any project folder: transcript_missing."""
    transcript_at(home / ".claude", session=OTHER_SESSION).user(QUOTE)
    out = find(home)
    assert out.code == 3 and out.error == "transcript_missing", out.show()


# --- ambiguous -------------------------------------------------------------------------


def test_r1_f7_two_equal_entries_are_ambiguous(home: Path) -> None:
    """Two typed entries with the same text: ambiguous, both listed, none picked."""
    tr = transcript_at(home / ".claude")
    first = tr.user(QUOTE)
    tr.assistant("noted")
    second = tr.user(QUOTE)
    out = find(home)
    assert out.code == 3 and out.error == "ambiguous", out.show()
    assert out.payload is not None
    assert [c["user_message_uuid"] for c in out.payload["candidates"]] == [
        first["uuid"],
        second["uuid"],
    ]
    assert "user_message_uuid" not in out.payload


def test_r1_f7_one_session_under_two_projects_is_ambiguous(home: Path) -> None:
    """The session file under two project folders: transcript_ambiguous."""
    transcript_at(home / ".claude").user(QUOTE)
    transcript_at(home / ".claude", project="D:/other-fixture").user(QUOTE)
    out = find(home)
    assert out.code == 3 and out.error == "transcript_ambiguous", out.show()


# --- bad input and bad data ------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--session", SESSION],
        ["--quote", QUOTE],
        ["--session", SESSION, "--quote", "   "],
        ["--session", SESSION, "--quote", ""],
        ["--session", "../" + SESSION, "--quote", QUOTE],
        ["--session", "a/b", "--quote", QUOTE],
        ["--session", "", "--quote", QUOTE],
        ["--session", SESSION, "--quote", "x" * 4001],
        ["--session", SESSION, "--quote", QUOTE, "extra"],
    ],
    ids=[
        "no-args",
        "no-quote",
        "no-session",
        "blank-quote",
        "empty-quote",
        "dotdot-session",
        "slash-session",
        "empty-session",
        "long-quote",
        "extra-arg",
    ],
)
def test_r1_f7_bad_input_is_a_usage_error(home: Path, args: list[str]) -> None:
    """Strict input: exit 2, usage, and no transcript read."""
    out = locate(home, *args)
    assert out.code == 2 and out.error == "usage", out.show()


def test_r1_f7_an_unknown_record_type_fails_closed(home: Path) -> None:
    """A line the verifier cannot read makes locate refuse, as the hook would."""
    tr = transcript_at(home / ".claude")
    tr.user(QUOTE)
    tr.raw(json.dumps({"type": "mystery", "uuid": str(uuid.uuid4())}))
    out = find(home)
    assert out.code == 3 and out.error == "transcript_unknown", out.show()


def test_real_store_unchanged() -> None:
    """AC-B.10 — no test here touched the real store."""
    assert real_db_state() == REAL_DB_STATE_AT_IMPORT
