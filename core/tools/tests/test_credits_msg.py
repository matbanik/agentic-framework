"""S1b run-side tool: ``tools/credits_msg.py`` (Component C).

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component C,
AC-C.3, AC-C.4 and AC-C.5; report R§4.3, R§4.6.4, R§4.6.5 and R§5.4;
acceptance matrix MX-13, MX-36, MX-39, MX-40, MX-45, MX-46 and MX-47, the
S1b main-tree parts).

The tests run the tool in a subprocess against a temp store, a temp config
and a temp git repository per test (AC-B.10). They fix this contract:

* ``python tools/credits_msg.py [--now-utc T] <verb> ...`` reads
  ``CREDITS_RUN_ID``, ``CREDITS_SEGMENT``, ``CREDITS_STATE_DB``,
  ``CREDITS_CONFIG`` and, for ``tree``, the optional ``CREDITS_BASE_COMMIT``.
  A missing required value or an unknown verb is a usage error (exit 2).
* stdout is one JSON object with ``result``, ``error`` and, for a verb that
  writes an outbox event, ``event_id`` = ``<run_id>-<event_seq>``. Exit codes
  are the store's: 0 changed or no_change, 2 usage, 3 refused, 9 crash.
* ``CREDITS_TEST_CRASH_AT=ack:<before_commit|after_commit>`` ends ``ack`` with
  exit 9 at that point.
* ``config.json`` has exactly ``ruling_enabled`` (bool), ``gate_wait_max_min``
  (int >= 0) and ``cache_ttl`` (``5m`` or ``1h``). Any other key or value, or
  a missing file, is ``config_invalid``.
* ``landing --part product --changed-files <file> --closeout <path>...`` is the
  main-tree capture; ``landing --part closeout`` is the seal. The S1b scope is
  the main tree: ``capture_main_mismatch`` (a worktree run) and
  ``base_carry_mismatch`` (needs D from chains) are S5.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from test_credits_state import (
    BOOT,
    REAL_DB_STATE_AT_IMPORT,
    ROOT,
    SESSION_B,
    Out,
    Store,
    at,
    child_env,
    dump,
    parse_out,
    real_db_state,
)

MSG_TOOL = ROOT / "tools" / "credits_msg.py"

CONFIG_DEFAULTS: dict[str, Any] = {
    "ruling_enabled": False,
    "gate_wait_max_min": 0,
    "cache_ttl": "5m",
    "credits_start_policy": "human-only",
}
STATUS_FILES = (
    ".agent/context/meu-status.yaml",
    ".agent/context/meu-registry.md",
    ".agent/context/current-focus.md",
)
PLAN_DIR = "docs/execution/plans/2026-10-15-fixture-plan/"
HANDOFF = ".agent/context/handoffs/2026-10-15-fixture-plan-handoff.md"
REFLECTION = "docs/execution/reflections/2026-10-15-fixture-plan-reflection.md"
CLOSEOUT = (PLAN_DIR, HANDOFF, REFLECTION)


def fetch(st: Store, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Return the rows of one query as dicts."""
    with contextlib.closing(sqlite3.connect(st.db)) as con:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute(sql, params)]


def git(repo: Path, *args: str) -> str:
    """Run one git command in ``repo`` and return its stripped stdout."""
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env({"GIT_CONFIG_NOSYSTEM": "1"}),
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"git {args}: {proc.stdout}{proc.stderr}"
    return proc.stdout.strip()


def put(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def blob(repo: Path, rel: str) -> str:
    return git(repo, "hash-object", "--", rel)


def tree_paths(repo: Path, tree: str) -> set[str]:
    return set(git(repo, "ls-tree", "-r", "--name-only", tree).splitlines())


def index_digest(repo: Path) -> str:
    return hashlib.sha256((repo / ".git" / "index").read_bytes()).hexdigest()


def make_repo(repo: Path) -> str:
    """A small main tree with the three status files; return the base commit."""
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "commit.gpgsign", "false")
    put(repo, ".gitignore", "*.log\n")
    put(repo, "README.md", "fixture readme\n")
    put(repo, "src/a.py", "A = 1\n")
    put(repo, "src/c.py", "C = 3\n")
    put(repo, ".agent/context/known-issues.yaml", "issues: []\n")
    put(repo, ".agent/context/grouping/fixture-grouping.md", "# grouping\n")
    for rel in STATUS_FILES:
        put(repo, rel, f"status {rel}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return git(repo, "rev-parse", "HEAD")


@dataclass(frozen=True)
class Run:
    """One manual run with a bound segment, a temp config and a temp main tree."""

    st: Store
    run_id: str
    segment: str
    config: Path
    repo: Path
    base: str
    work: Path

    def env(
        self, extra: dict[str, str] | None = None, drop: str | None = None
    ) -> dict[str, str]:
        env = self.st.env(
            {
                "CREDITS_RUN_ID": self.run_id,
                "CREDITS_SEGMENT": self.segment,
                "CREDITS_STATE_DB": str(self.st.db),
                "CREDITS_CONFIG": str(self.config),
                **(extra or {}),
            }
        )
        if drop is not None:
            del env[drop]
        return env

    def msg(
        self,
        verb: str,
        *args: str,
        seconds: int = 0,
        extra: dict[str, str] | None = None,
        drop: str | None = None,
    ) -> Out:
        proc = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                str(MSG_TOOL),
                "--now-utc",
                at(seconds),
                verb,
                *args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env(self.env(extra, drop)),
            timeout=120,
            cwd=ROOT,
            check=False,
        )
        return parse_out(proc.returncode, proc.stdout, proc.stderr)

    def send(self, kind: str, body: str, seconds: int = 0) -> str:
        out = self.st.cli(
            "send", "--run-id", self.run_id, "--kind", kind, "--body", body, now=seconds
        )
        assert out.code == 0 and out.payload is not None, out.show()
        msg_id = out.payload.get("msg_id")
        assert isinstance(msg_id, str) and msg_id, out.show()
        return msg_id

    def events(self) -> list[dict[str, Any]]:
        return fetch(
            self.st,
            "SELECT event_seq, kind, semantic_key FROM outbox_events WHERE run_id = ? "
            "ORDER BY event_seq",
            (self.run_id,),
        )

    def message(self, msg_id: str) -> dict[str, Any]:
        found = fetch(self.st, "SELECT * FROM messages WHERE msg_id = ?", (msg_id,))
        assert len(found) == 1, found
        return found[0]

    def run_row(self) -> dict[str, Any]:
        found = fetch(self.st, "SELECT * FROM runs WHERE run_id = ?", (self.run_id,))
        assert len(found) == 1, found
        return found[0]

    def tree(self, seconds: int = 10, base: str | None = None) -> Out:
        extra = {"CREDITS_BASE_COMMIT": base} if base else None
        return self.msg("tree", str(self.repo), seconds=seconds, extra=extra)

    def capture(self, changed: list[str], seconds: int = 20) -> Out:
        listing = self.work / "changed-files.txt"
        listing.write_text("".join(f"{p}\n" for p in changed), encoding="utf-8")
        args = ["--part", "product", "--changed-files", str(listing)]
        for rel in CLOSEOUT:
            args += ["--closeout", rel]
        return self.msg("landing", *args, seconds=seconds)

    def seal(self, seconds: int = 30) -> Out:
        return self.msg("landing", "--part", "closeout", seconds=seconds)

    def landings(self, part: str) -> dict[str, dict[str, Any]]:
        rows = fetch(
            self.st,
            "SELECT path, blob, sealed_utc FROM landings WHERE run_id = ? AND part = ?",
            (self.run_id, part),
        )
        return {str(r["path"]): r for r in rows}

    def ref(self, name: str) -> str:
        return git(
            self.repo, "rev-parse", f"refs/credits/{self.run_id}/{name}^{{tree}}"
        )

    def has_ref(self, name: str) -> bool:
        proc = subprocess.run(
            [
                "git",
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/credits/{self.run_id}/{name}",
            ],
            cwd=self.repo,
            capture_output=True,
            env=child_env(),
            timeout=60,
            check=False,
        )
        return proc.returncode == 0


def write_config(path: Path, **values: Any) -> Path:
    """Write a temp ``config.json`` (never the live one)."""
    path.write_text(json.dumps({**CONFIG_DEFAULTS, **values}), encoding="utf-8")
    return path


@pytest.fixture
def run(tmp_path: Path) -> Run:
    st = Store(tmp_path / "store")
    st.root.mkdir()
    st.init()
    run_id = "c3-run"
    segment = "seg-c3-run"
    st.ok(
        "register_minimal",
        "--run-id",
        run_id,
        "--segment-id",
        segment,
        "--wrapper-pid",
        "6161",
        "--wrapper-created",
        at(-30),
        "--boot-id",
        BOOT,
        "--win-session",
        "1",
        "--job-name",
        "Local\\{{PROJECT_NAME_UPPER}}Credits-" + segment,
        "--expected-session-id",
        SESSION_B,
        now=0,
    )
    st.ok(
        "manual_identity", "--segment-id", segment, "--pid", "5151", "--created", at(0)
    )
    repo = tmp_path / "repo"
    base = make_repo(repo)
    work = tmp_path / "work"
    work.mkdir()
    return Run(
        st=st,
        run_id=run_id,
        segment=segment,
        config=write_config(tmp_path / "config.json"),
        repo=repo,
        base=base,
        work=work,
    )


# --- AC-C.3: the verbs, the environment and the config -----------------------------


@pytest.mark.parametrize("kind", ["info", "query"])
def test_ack_closes_an_info_or_query_and_writes_one_event(run: Run, kind: str) -> None:
    """AC-C.3: ack records the ack, closes the message as done and writes ack:<msg_id>."""
    msg_id = run.send(kind, "fixture body", 1)
    out = run.msg("ack", msg_id, "noted", seconds=2)
    assert out.code == 0 and out.result == "changed", out.show()
    events = run.events()
    assert [(e["kind"], e["semantic_key"]) for e in events] == [
        ("ack", f"ack:{msg_id}")
    ]
    assert out.payload is not None
    assert out.payload["event_id"] == f"{run.run_id}-{events[0]['event_seq']}"
    message = run.message(msg_id)
    assert message["acked_utc"] == at(2)
    assert message["closed_reason"] == "done"
    assert message["closed_utc"] == at(2)


def test_ack_of_a_stop_after_row_waits_for_applied(run: Run) -> None:
    """AC-C.3: a stop-after-row stays open after ack; applied closes it."""
    msg_id = run.send("stop-after-row", "finish the row, then end", 1)
    acked = run.msg("ack", msg_id, "will stop after this row", seconds=2)
    assert acked.code == 0 and acked.result == "changed", acked.show()
    assert run.message(msg_id)["closed_utc"] is None
    applied = run.msg("applied", msg_id, seconds=3)
    assert applied.code == 0 and applied.result == "changed", applied.show()
    message = run.message(msg_id)
    assert message["applied_utc"] == at(3)
    assert message["closed_reason"] == "applied"
    keys = [e["semantic_key"] for e in run.events()]
    assert keys == [f"ack:{msg_id}", f"applied:{msg_id}"]


def test_applied_on_an_info_is_refused(run: Run) -> None:
    """AC-C.3 negative: applied names a stop-after-row only."""
    msg_id = run.send("info", "fixture body", 1)
    out = run.msg("applied", msg_id, seconds=2)
    assert out.code == 3 and out.error == "kind_mismatch", out.show()
    assert run.events() == []


def test_ack_of_an_unknown_message_is_refused(run: Run) -> None:
    """AC-C.3 negative: an ack names a message of this run."""
    out = run.msg("ack", "msg-missing", "noted", seconds=2)
    assert out.code == 3 and out.error == "unknown_msg", out.show()
    assert run.events() == []


def test_report_writes_a_new_event_each_call(run: Run) -> None:
    """AC-C.3: each report has its own id, so two reports are two events."""
    first = run.msg("report", "row 4 done", seconds=1)
    second = run.msg("report", "row 4 done", seconds=2)
    assert first.code == 0 and second.code == 0, first.show() + second.show()
    assert first.payload is not None and second.payload is not None
    assert first.payload["event_id"] != second.payload["event_id"]
    assert [e["kind"] for e in run.events()] == ["report", "report"]


def test_decision_opens_one_gate_and_a_second_is_refused(run: Run) -> None:
    """AC-C.3: decision opens a gate and writes a decision event; one open gate per run."""
    out = run.msg("decision", "D-1", "Which fixture option applies?", seconds=1)
    assert out.code == 0 and out.result == "changed", out.show()
    gates = fetch(
        run.st,
        "SELECT state, question, decision_id FROM gates WHERE run_id = ?",
        (run.run_id,),
    )
    assert gates == [
        {
            "state": "open",
            "question": "Which fixture option applies?",
            "decision_id": "D-1",
        }
    ]
    assert [e["kind"] for e in run.events()] == ["decision"]
    again = run.msg("decision", "D-2", "A second question", seconds=2)
    assert again.code == 3 and again.error == "gate_open", again.show()
    assert len(run.events()) == 1


def test_wait_is_disabled_when_gate_wait_max_min_is_zero(run: Run) -> None:
    """AC-C.3: with gate_wait_max_min 0, wait is refused and the gate is unchanged."""
    opened = run.msg("decision", "D-1", "Which fixture option applies?", seconds=1)
    assert opened.code == 0, opened.show()
    before = fetch(run.st, "SELECT * FROM gates WHERE run_id = ?", (run.run_id,))
    out = run.msg("wait", seconds=2)
    assert out.code == 3 and out.error == "wait_disabled", out.show()
    assert (
        fetch(run.st, "SELECT * FROM gates WHERE run_id = ?", (run.run_id,)) == before
    )


@pytest.mark.parametrize(
    "values",
    [
        {"extra_key": 1},
        {"ruling_enabled": "yes"},
        {"gate_wait_max_min": -1},
        {"gate_wait_max_min": 1.5},
        {"cache_ttl": "2h"},
    ],
    ids=["unknown-key", "bool-as-text", "negative-wait", "float-wait", "bad-ttl"],
)
def test_bad_config_is_refused(run: Run, values: dict[str, Any]) -> None:
    """AC-C.3 negative: an unknown key or a bad value → config_invalid."""
    write_config(run.config, **values)
    out = run.msg("wait", seconds=2)
    assert out.code == 3 and out.error == "config_invalid", out.show()


def test_missing_config_is_refused(run: Run) -> None:
    """AC-C.3 negative: a missing config file → config_invalid."""
    run.config.unlink()
    out = run.msg("wait", seconds=2)
    assert out.code == 3 and out.error == "config_invalid", out.show()


@pytest.mark.parametrize(
    "name", ["CREDITS_RUN_ID", "CREDITS_SEGMENT", "CREDITS_STATE_DB"]
)
def test_missing_environment_is_a_usage_error(run: Run, name: str) -> None:
    """AC-C.3 negative: each required CREDITS_* value is needed (exit 2)."""
    before = dump(run.st.db)
    out = run.msg("report", "row 4 done", seconds=1, drop=name)
    assert out.code == 2, out.show()
    assert dump(run.st.db) == before


def test_unknown_verb_is_a_usage_error(run: Run) -> None:
    """AC-C.3 negative: an unknown verb → exit 2 and no write."""
    before = dump(run.st.db)
    out = run.msg("sing", seconds=1)
    assert out.code == 2, out.show()
    assert dump(run.st.db) == before


# --- AC-C.4: idempotent events and the ack crash points ----------------------------


def test_mx_13_a_retried_ack_is_one_event_with_the_same_id(run: Run) -> None:
    """AC-C.4 / MX-13: the semantic key makes a retried ack no_change with the same event_id."""
    msg_id = run.send("info", "fixture body", 1)
    first = run.msg("ack", msg_id, "noted", seconds=2)
    second = run.msg("ack", msg_id, "noted again", seconds=3)
    assert first.code == 0 and first.result == "changed", first.show()
    assert second.code == 0 and second.result == "no_change", second.show()
    assert first.payload is not None and second.payload is not None
    assert second.payload["event_id"] == first.payload["event_id"]
    assert len(run.events()) == 1
    assert run.message(msg_id)["acked_utc"] == at(2)


def test_ack_crash_before_commit_writes_nothing(run: Run) -> None:
    """AC-C.4: a crash before the commit leaves no event and no ack; the retry writes one."""
    msg_id = run.send("info", "fixture body", 1)
    crashed = run.msg(
        "ack",
        msg_id,
        "noted",
        seconds=2,
        extra={"CREDITS_TEST_CRASH_AT": "ack:before_commit"},
    )
    assert crashed.code == 9, crashed.show()
    assert run.events() == []
    assert run.message(msg_id)["acked_utc"] is None
    retry = run.msg("ack", msg_id, "noted", seconds=3)
    assert retry.code == 0 and retry.result == "changed", retry.show()
    assert len(run.events()) == 1


def test_ack_crash_after_commit_keeps_one_whole_event(run: Run) -> None:
    """AC-C.4: a crash after the commit keeps one whole event; the retry is no_change."""
    msg_id = run.send("info", "fixture body", 1)
    crashed = run.msg(
        "ack",
        msg_id,
        "noted",
        seconds=2,
        extra={"CREDITS_TEST_CRASH_AT": "ack:after_commit"},
    )
    assert crashed.code == 9, crashed.show()
    events = run.events()
    assert [(e["kind"], e["semantic_key"]) for e in events] == [
        ("ack", f"ack:{msg_id}")
    ]
    assert run.message(msg_id)["acked_utc"] == at(2)
    retry = run.msg("ack", msg_id, "noted", seconds=3)
    assert retry.code == 0 and retry.result == "no_change", retry.show()
    assert retry.payload is not None
    assert retry.payload["event_id"] == f"{run.run_id}-{events[0]['event_seq']}"


# --- AC-C.5: tree, capture and seal (main tree) ------------------------------------


def test_tree_without_a_base_pins_the_snapshot_start_tree(run: Run) -> None:
    """AC-C.5: tree records active_tree and pins S (tracked + untracked, not ignored)."""
    put(run.repo, "src/untracked.py", "U = 1\n")
    put(run.repo, "debug.log", "ignored\n")
    index_before = index_digest(run.repo)
    out = run.tree()
    assert out.code == 0 and out.result == "changed", out.show()
    row = run.run_row()
    assert Path(str(row["active_tree"])).resolve() == run.repo.resolve()
    start = str(row["start_tree"])
    assert git(run.repo, "cat-file", "-t", start) == "tree"
    assert run.ref("start") == start
    paths = tree_paths(run.repo, start)
    assert "src/untracked.py" in paths
    assert "src/a.py" in paths
    assert "debug.log" not in paths
    assert index_digest(run.repo) == index_before
    assert "src/untracked.py" not in git(run.repo, "ls-files").splitlines()


def test_tree_with_a_base_records_the_carry_manifest(run: Run) -> None:
    """AC-C.5: with CREDITS_BASE_COMMIT, a changed carried file is a successor input."""
    put(run.repo, STATUS_FILES[0], "status changed by the human\n")
    out = run.tree(base=run.base)
    assert out.code == 0 and out.result == "changed", out.show()
    seg = fetch(
        run.st,
        "SELECT carry_manifest_json FROM segments WHERE segment_id = ?",
        (run.segment,),
    )
    manifest = json.loads(str(seg[0]["carry_manifest_json"]))
    by_path = {str(entry["path"]): entry for entry in manifest}
    assert set(by_path) == set(STATUS_FILES)
    changed = by_path[STATUS_FILES[0]]
    assert changed["class"] == "successor_input"
    assert changed["blob"] == blob(run.repo, STATUS_FILES[0])
    for rel in STATUS_FILES[1:]:
        assert by_path[rel]["class"] == "equal_to_base"
        assert by_path[rel]["blob"] == blob(run.repo, rel)
    assert run.has_ref("start")


def test_tree_refuses_a_moved_head(run: Run) -> None:
    """AC-C.5 negative: HEAD is not B → base_moved; no ref and no store change."""
    put(run.repo, "README.md", "moved\n")
    git(run.repo, "commit", "-q", "-am", "move head")
    before = dump(run.st.db)
    out = run.tree(base=run.base)
    assert out.code == 3 and out.error == "base_moved", out.show()
    assert dump(run.st.db) == before
    assert not run.has_ref("start")


def test_tree_refuses_a_changed_tracked_file(run: Run) -> None:
    """AC-C.5 negative: a tracked, not-carried path changed → base_content_mismatch:<paths>."""
    put(run.repo, "src/a.py", "A = 2\n")
    before = dump(run.st.db)
    out = run.tree(base=run.base)
    assert out.code == 3, out.show()
    assert str(out.error).startswith("base_content_mismatch:"), out.show()
    assert "src/a.py" in str(out.error)
    assert dump(run.st.db) == before
    assert not run.has_ref("start")


def test_landing_before_tree_is_refused(run: Run) -> None:
    """AC-C.5 negative: no start tree → no_start_tree and no rows."""
    out = run.capture(["src/a.py"])
    assert out.code == 3 and out.error == "no_start_tree", out.show()
    assert run.landings("product") == {}


def _product_change(run: Run) -> list[str]:
    """Modify a.py, add b.py, delete c.py, and write a closeout file in the plan folder."""
    put(run.repo, "src/a.py", "A = 2\n")
    put(run.repo, "src/b.py", "B = 2\n")
    (run.repo / "src" / "c.py").unlink()
    put(run.repo, f"{PLAN_DIR}task.md", "rows\n")
    return ["src/a.py", "src/b.py", "src/c.py"]


def test_capture_records_product_rows_and_pins_landed_and_capture(run: Run) -> None:
    """AC-C.5: the main-tree capture records each product path and pins L = C."""
    assert run.tree().code == 0
    changed = _product_change(run)
    out = run.capture(changed)
    assert out.code == 0 and out.result == "changed", out.show()
    rows = run.landings("product")
    assert set(rows) == set(changed)
    assert rows["src/a.py"]["blob"] == blob(run.repo, "src/a.py")
    assert rows["src/b.py"]["blob"] == blob(run.repo, "src/b.py")
    assert rows["src/c.py"]["blob"] == "deleted"
    row = run.run_row()
    assert row["landed_tree"] == row["capture_tree"]
    assert run.ref("landed") == row["landed_tree"]
    assert run.ref("capture") == row["capture_tree"]


@pytest.mark.parametrize(
    "listed",
    [["src/a.py", "src/c.py"], ["src/a.py", "src/b.py", "src/c.py", "README.md"]],
    ids=["omitted", "extra"],
)
def test_mx_40_inventory_mismatch_is_refused(run: Run, listed: list[str]) -> None:
    """AC-C.5 / MX-40: the handoff list must equal the S→L diff less the closeout set."""
    assert run.tree().code == 0
    _product_change(run)
    out = run.capture(listed)
    assert out.code == 3, out.show()
    assert str(out.error).startswith("capture_inventory_mismatch"), out.show()
    assert run.landings("product") == {}


def test_mx_39_h2_3_updates_are_product_rows_and_the_seal_passes(run: Run) -> None:
    """AC-C.5 / MX-39: the grouping and known-issues updates land as product rows."""
    assert run.tree().code == 0
    changed = _product_change(run)
    put(
        run.repo,
        ".agent/context/grouping/fixture-grouping.md",
        "# grouping\nrow done\n",
    )
    put(run.repo, ".agent/context/known-issues.yaml", "issues: [FIXTURE-1]\n")
    changed += [
        ".agent/context/grouping/fixture-grouping.md",
        ".agent/context/known-issues.yaml",
    ]
    out = run.capture(changed)
    assert out.code == 0, out.show()
    assert set(run.landings("product")) == set(changed)
    put(run.repo, HANDOFF, "handoff\n")
    put(run.repo, REFLECTION, "reflection\n")
    put(run.repo, f"{PLAN_DIR}task.md", "rows, all done\n")
    sealed = run.seal()
    assert sealed.code == 0 and sealed.result == "changed", sealed.show()
    closeout = run.landings("closeout")
    assert {HANDOFF, REFLECTION, f"{PLAN_DIR}task.md"} <= set(closeout)
    assert all(r["sealed_utc"] == at(30) for r in closeout.values())


def test_seal_before_capture_is_refused(run: Run) -> None:
    """AC-C.5 negative: the seal needs the product part."""
    assert run.tree().code == 0
    out = run.seal()
    assert out.code == 3 and out.error == "no_product_part", out.show()
    assert run.landings("closeout") == {}


def test_mx_36_a_product_file_changed_after_the_capture_is_refused(run: Run) -> None:
    """AC-C.5 / MX-36: a captured product file changed again → product_changed_after_land."""
    assert run.tree().code == 0
    assert run.capture(_product_change(run)).code == 0
    put(run.repo, "src/a.py", "A = 3\n")
    out = run.seal()
    assert out.code == 3, out.show()
    assert str(out.error) == "product_changed_after_land:src/a.py", out.show()
    assert run.landings("closeout") == {}


def test_mx_36_a_new_file_after_the_capture_is_refused(run: Run) -> None:
    """AC-C.5 / MX-36: a new path outside the closeout set → path_added_after_land."""
    assert run.tree().code == 0
    assert run.capture(_product_change(run)).code == 0
    put(run.repo, "src/late.py", "L = 1\n")
    out = run.seal()
    assert out.code == 3, out.show()
    assert str(out.error) == "path_added_after_land:src/late.py", out.show()
    assert run.landings("closeout") == {}


@pytest.mark.parametrize("change", ["reverted", "added-deleted", "deleted-recreated"])
def test_mx_46_seal_compares_every_product_row(run: Run, change: str) -> None:
    """AC-C.5 / MX-46: a revert to S, a deleted added file or a recreated deleted file."""
    assert run.tree().code == 0
    assert run.capture(_product_change(run)).code == 0
    if change == "reverted":
        put(run.repo, "src/a.py", "A = 1\n")
        path = "src/a.py"
    elif change == "added-deleted":
        (run.repo / "src" / "b.py").unlink()
        path = "src/b.py"
    else:
        put(run.repo, "src/c.py", "C = 3\n")
        path = "src/c.py"
    out = run.seal()
    assert out.code == 3, out.show()
    assert str(out.error) == f"product_changed_after_land:{path}", out.show()


def test_mx_45_a_commit_between_tree_and_capture_keeps_the_inventory_on_s(
    run: Run,
) -> None:
    """AC-C.5 / MX-45: the inventory is the diff from the pinned S, not from HEAD."""
    assert run.tree().code == 0
    start = str(run.run_row()["start_tree"])
    put(run.repo, "src/a.py", "A = 2\n")
    git(run.repo, "commit", "-q", "-am", "mid-run commit")
    put(run.repo, "src/b.py", "B = 2\n")
    out = run.capture(["src/a.py", "src/b.py"])
    assert out.code == 0, out.show()
    assert set(run.landings("product")) == {"src/a.py", "src/b.py"}
    assert run.ref("start") == start
    assert run.has_ref("landed") and run.has_ref("capture")
    assert run.seal().code == 0


def test_mx_47_an_unrelated_main_tree_edit_is_refused(run: Run) -> None:
    """AC-C.5 / MX-47: a human edit of an unrelated tracked path → path_added_after_land."""
    assert run.tree().code == 0
    assert run.capture(_product_change(run)).code == 0
    put(run.repo, "README.md", "edited by the human\n")
    out = run.seal()
    assert out.code == 3, out.show()
    assert str(out.error) == "path_added_after_land:README.md", out.show()


def test_closeout_part_takes_no_path_flags(run: Run) -> None:
    """AC-C.5 negative: --changed-files and --closeout belong to the product part only."""
    assert run.tree().code == 0
    out = run.msg("landing", "--part", "closeout", "--closeout", HANDOFF, seconds=30)
    assert out.code == 2, out.show()


def test_real_store_unchanged() -> None:
    """AC-B.10: no test of this file touched the real store."""
    assert real_db_state() == REAL_DB_STATE_AT_IMPORT
