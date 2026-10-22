"""Installer and template tests for the scheduled credits runs port (AC-J.3 … AC-J.5).

AC-J.3  ``scripts/instantiate.py`` substitutes ``.psm1``/``.psd1`` files and merges the
        hook fragment ``.claude/settings.hooks.json`` into ``.claude/settings.json``:
        additive, idempotent, prior entries first and unchanged.
AC-J.4  On any OS other than Windows the installer refuses the scheduler: it removes the
        Windows-only files, writes no ``credits_inbox.py`` hook entry, and ``--verify``
        checks that refusal.
AC-J.5  The start policy defaults to ``human-only``; the config ships both switches off;
        the task template, the workflows, the harness profile, ``ADOPTION-GUIDE.md`` and
        ``UPDATE-CHECKLIST.md`` carry the credits closeout and the adopter gate; the
        governance anchors that ``Register-CreditsRun.ps1`` requires are in the core
        files.

Each test loads the installer inside its body, so a missing function fails that test and
never errors the collection. Every tree the tests write is a temporary copy of ``core/``.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
INSTALLER = ROOT / "scripts" / "instantiate.py"
FRAGMENT = CORE / ".claude" / "settings.hooks.json"
CONFIG_TEMPLATE = CORE / ".agent" / "credits" / "config.json"
SKILL = CORE / ".agent" / "skills" / "claude-credits"
TASK_TEMPLATE = CORE / "templates" / "TASK-TEMPLATE.md"
WORKFLOWS = (
    CORE / ".agent" / "workflows" / "create-plan.md",
    CORE / ".agent" / "workflows" / "execution-session.md",
)
HARNESS = CORE / ".agent" / "docs" / "harness-profiles.md"
ADOPTION_GUIDE = ROOT / "ADOPTION-GUIDE.md"
UPDATE_CHECKLIST = ROOT / "UPDATE-CHECKLIST.md"

#: ADOPTION-GUIDE Step 2: package path -> adopter path.
COPY_MAP = (
    ("core/AGENTS.md", "AGENTS.md"),
    ("core/GUARDRAILS.md", "GUARDRAILS.md"),
    ("core/CLAUDE.md", "CLAUDE.md"),
    ("core/.agent", ".agent"),
    ("core/tools", "tools"),
    ("core/templates", ".agent/templates"),
    ("core/.claude/agents", ".claude/agents"),
    ("core/.claude/hooks", ".claude/hooks"),
    ("core/.claude/settings.hooks.json", ".claude/settings.hooks.json"),
)

INBOX_HOOK = ".claude/hooks/credits_inbox.py"
STOP_GATE = "tools/stop_gate.py"
WINDOWS_ONLY_MESSAGE = "REFUSED: scheduled credits runs are Windows-only"
POLICY_DEFAULT = "human-only"
POLICY_CHAT = "agent-on-user-chat"
TEMPLATE_CONFIG = {
    "ruling_enabled": False,
    "gate_wait_max_min": 0,
    "cache_ttl": "5m",
    "credits_start_policy": POLICY_DEFAULT,
}

# AC-H.8 order, mirrored in the framework template and workflows.
TREE_CALL = "credits_msg.py tree"
LAND_CALL = "executor_worktree.py land"
CAPTURE_CALL = "credits_msg.py landing --part product"
REMOVE_CALL = "executor_worktree.py remove"
RELEASED_DONE = "released:done"
SEAL_CALL = "credits_msg.py landing --part closeout"
HEADLESS_HEADING = "Scheduled headless run"

SCHEDULER_ROW_NAME = "headless `claude -p` under the credits scheduler"
SCHEDULER_FLAGS = {
    "stop_notify": "monitor",
    "plan_to_exec_gate": "human",
    "fresh_worker": "none",
    "mid_run_messages": "inbox-hook",
}
SCHEDULER_END_TURN = "gate-wait-then-exit"
ITALIC_NOTE_RE = re.compile(r"\*\([^)]*\)\*")
BACKTICKED_RE = re.compile(r"`([^`]+)`")
ANCHOR_RE = re.compile(r"@\{ File = '([^']+)'; Line = '((?:[^']|'')*)' \}")


# --- helpers ------------------------------------------------------------------------------


def _load_installer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("instantiate_under_test", INSTALLER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _copy_core(dest: Path) -> Path:
    """Copy the package into ``dest`` as ADOPTION-GUIDE Step 2 does."""
    for src_rel, dst_rel in COPY_MAP:
        src = ROOT / src_rel
        dst = dest / dst_rel
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return dest


def _values(root: Path, receipts: str = "C:/Temp/acme") -> dict[str, str]:
    return {
        "project_name": "acme",
        "project_root": str(root),
        "receipts_dir": receipts,
        "repo_url": "github.com/you/acme",
    }


def _entries(settings: dict[str, object]) -> list[tuple[str, str, str]]:
    """Each hook entry of a settings document as (event, matcher, command), in order."""
    out: list[tuple[str, str, str]] = []
    hooks = settings.get("hooks", {})
    assert isinstance(hooks, dict)
    for event, groups in hooks.items():
        for group in groups:
            for hook in group.get("hooks", []):
                out.append((event, group.get("matcher", ""), hook["command"]))
    return out


def _fragment() -> dict[str, object]:
    return json.loads(_text(FRAGMENT))


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _settings(root: Path) -> dict[str, object]:
    return json.loads(_text(root / ".claude" / "settings.json"))


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(INSTALLER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


def _cli_values(root: Path) -> list[str]:
    v = _values(root)
    return [
        "--root",
        str(root),
        "--project-name",
        v["project_name"],
        "--project-root",
        v["project_root"],
        "--receipts-dir",
        v["receipts_dir"],
        "--repo-url",
        v["repo_url"],
    ]


def _split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [c.strip() for c in cells[1:-1]]


def _heading_section(text: str, heading: str) -> str:
    match = re.search(rf"(?m)^(#+) {re.escape(heading)}[^\n]*\n", text)
    assert match is not None, f"no heading '{heading}'"
    level = len(match.group(1))
    rest = text[match.end() :]
    end = re.search(rf"(?m)^#{{1,{level}}} ", rest)
    return match.group(0) + (rest if end is None else rest[: end.start()])


def _assert_order(text: str, calls: tuple[str, ...], where: str) -> None:
    positions = []
    for call in calls:
        index = text.find(call)
        assert index >= 0, f"{where}: '{call}' is missing"
        positions.append(index)
    assert positions == sorted(positions), (
        f"{where}: the calls are out of order: "
        + ", ".join(f"{c}@{p}" for c, p in zip(calls, positions, strict=True))
    )


def _template_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in _text(TASK_TEMPLATE).splitlines():
        cells = _split_row(line) if line.startswith("| ") else []
        if cells and re.fullmatch(r"H\d-\d+[a-z]?", cells[0]):
            rows[cells[0]] = line
    return rows


def _flag_values() -> dict[str, frozenset[str] | None]:
    section = _heading_section(_text(HARNESS), "Capability flags (the contract)")
    flags: dict[str, frozenset[str] | None] = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = _split_row(line)
        parts = [p.strip() for p in cells[1].split("\\|")]
        if all(re.fullmatch(r"`[^`]+`", p) for p in parts):
            flags[cells[0].strip("`")] = frozenset(p.strip("`") for p in parts)
        else:
            flags[cells[0].strip("`")] = None
    return flags


def _profile_rows() -> tuple[list[str], list[list[str]]]:
    section = _heading_section(_text(HARNESS), "Harness profile table")
    lines = [ln for ln in section.splitlines() if ln.startswith("|")]
    header = [c.strip("`") for c in _split_row(lines[0])]
    return header, [_split_row(ln) for ln in lines[2:]]


def _governance_anchors() -> list[tuple[str, str]]:
    text = _text(SKILL / "Register-CreditsRun.ps1")
    block = re.search(r"(?ms)^\$script:GovernanceAnchors = @\((.*?)^\)", text)
    assert block is not None, "Register-CreditsRun.ps1 has no $script:GovernanceAnchors"
    anchors = [(f, line.replace("''", "'")) for f, line in ANCHOR_RE.findall(block.group(1))]
    assert len(anchors) == 4, anchors
    return anchors


@pytest.fixture
def adopter(tmp_path: Path) -> Path:
    return _copy_core(tmp_path / "acme")


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")


@pytest.fixture
def on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")


# --- AC-J.3: suffixes, prefixes and the hook merge -----------------------------------------


def test_module_suffixes_are_text() -> None:
    """AC-J.3: ``.psm1`` and ``.psd1`` are text files the installer substitutes."""
    inst = _load_installer()
    assert {".psm1", ".psd1"} <= inst.TEXT_SUFFIXES


@pytest.mark.parametrize(
    ("rel", "installed"),
    [
        (".claude/hooks/credits_inbox.py", True),
        (".claude/settings.hooks.json", True),
        (".claude/settings.json", False),
        (".claude/agents/acme-builder.md", True),
    ],
)
def test_hook_paths_are_framework_installed(rel: str, installed: bool) -> None:
    """AC-J.3: the hook script and the fragment are in the adopter inventory; the
    adopter's own ``settings.json`` is not."""
    inst = _load_installer()
    assert inst.is_framework_installed(Path(rel), in_place=False) is installed


def test_verify_finds_module_tokens_then_run_clears_them(
    adopter: Path, on_windows: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-J.3: ``--verify`` reports a token in a ``.psm1``/``.psd1``; ``run`` clears it."""
    inst = _load_installer()
    module = adopter / ".agent" / "skills" / "claude-credits" / "Probe.psm1"
    manifest = module.with_suffix(".psd1")
    module.write_text("$x = '{{RECEIPTS_DIR}}/credits'\n", encoding="utf-8")
    manifest.write_text("@{ Description = '{{PROJECT_NAME_TITLE}} credits' }\n", encoding="utf-8")
    assert inst.verify_only(adopter) == 2
    out = capsys.readouterr().out
    assert "Probe.psm1" in out and "Probe.psd1" in out, out
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    assert _text(module) == "$x = 'C:/Temp/acme/credits'\n"
    assert _text(manifest) == "@{ Description = 'Acme credits' }\n"


def test_merge_keeps_prior_entries_first_and_is_idempotent() -> None:
    """AC-J.3: prior PostToolUse and Stop entries survive two merges, in order, first."""
    inst = _load_installer()
    prior = {
        "model": "keep-me",
        "hooks": {
            "PostToolUse": [
                {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo post"}]}
            ],
            "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
        },
    }
    before = copy.deepcopy(prior)
    fragment = _fragment()
    once = inst.merge_hook_settings(prior, fragment)
    twice = inst.merge_hook_settings(once, fragment)
    assert prior == before, "merge_hook_settings mutated its input"
    assert twice == once
    assert once["model"] == "keep-me"
    prior_entries = _entries(before)
    for event in ("PostToolUse", "Stop"):
        got = [e for e in _entries(twice) if e[0] == event]
        want = [e for e in prior_entries if e[0] == event]
        assert got[: len(want)] == want, (event, got)
    merged = _entries(twice)
    for entry in _entries(fragment):
        assert merged.count(entry) == 1, entry


def test_merge_does_not_duplicate_an_entry_already_present() -> None:
    """AC-J.3: an entry is the same when event, matcher and command are the same."""
    inst = _load_installer()
    fragment = _fragment()
    event, matcher, command = next(e for e in _entries(fragment) if STOP_GATE in e[2])
    group: dict[str, object] = {"hooks": [{"type": "command", "command": command}]}
    if matcher:
        group["matcher"] = matcher
    merged = inst.merge_hook_settings({"hooks": {event: [group]}}, fragment)
    assert _entries(merged).count((event, matcher, command)) == 1


def test_fragment_holds_the_credits_entries() -> None:
    """AC-J.3: PostToolUse ``*`` and Stop run the inbox hook; Stop runs ``stop_gate.py``,
    all in the framework's ``python "${CLAUDE_PROJECT_DIR}/…"`` form."""
    entries = _entries(_fragment())
    prefix = 'python "${CLAUDE_PROJECT_DIR}/'
    assert all(cmd.startswith(prefix) for _e, _m, cmd in entries), entries
    assert ("PostToolUse", "*") in {(e, m) for e, m, c in entries if INBOX_HOOK in c}
    assert "Stop" in {e for e, _m, c in entries if INBOX_HOOK in c}
    stop_gate = [c for e, _m, c in entries if e == "Stop" and STOP_GATE in c]
    assert stop_gate == [f'{prefix}{STOP_GATE}" "${{CLAUDE_PROJECT_DIR}}"'], stop_gate
    # Run parameters (FS §3, D-45 A): the fourth entry is the ``commit_gate.py`` Bash hook.
    commit_gate = [(e, m) for e, m, c in entries if c == f'{prefix}.claude/hooks/commit_gate.py"']
    assert commit_gate == [("PreToolUse", "Bash")], entries
    assert len(entries) == 4, entries


def test_run_creates_settings_with_every_fragment_entry(adopter: Path, on_windows: None) -> None:
    """AC-J.3: ``run`` creates ``.claude/settings.json`` when absent."""
    inst = _load_installer()
    assert not (adopter / ".claude" / "settings.json").exists()
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    merged = _entries(_settings(adopter))
    for entry in _entries(_fragment()):
        assert entry in merged, entry


def test_second_run_gives_identical_settings_bytes(adopter: Path, on_windows: None) -> None:
    """AC-J.3: a second run gives identical bytes; prior entries are kept."""
    inst = _load_installer()
    settings = adopter / ".claude" / "settings.json"
    prior = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
    settings.write_text(json.dumps(prior, indent=2) + "\n", encoding="utf-8")
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    first = settings.read_bytes()
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    assert settings.read_bytes() == first
    assert _entries(_settings(adopter))[0] == ("Stop", "", "echo mine")


def test_invalid_settings_json_refuses_before_any_write(adopter: Path) -> None:
    """AC-J.3: an invalid ``settings.json`` → exit 2; the tree is unchanged."""
    settings = adopter / ".claude" / "settings.json"
    settings.write_text('{"hooks": [', encoding="utf-8")
    before = _snapshot(adopter)
    result = _cli(*_cli_values(adopter))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "settings.json" in result.stderr, result.stderr
    assert _snapshot(adopter) == before


def test_verify_reports_a_missing_hook_entry(
    adopter: Path, on_windows: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-J.3: ``--verify`` fails when a fragment entry is not in ``settings.json``."""
    inst = _load_installer()
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    assert inst.verify_only(adopter) == 0
    settings = _settings(adopter)
    hooks = settings["hooks"]
    assert isinstance(hooks, dict)
    hooks["Stop"] = [
        group
        for group in hooks["Stop"]
        if not any(STOP_GATE in h["command"] for h in group["hooks"])
    ]
    (adopter / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    capsys.readouterr()
    assert inst.verify_only(adopter) == 2
    assert "stop_gate.py" in capsys.readouterr().out


def _ask(settings: dict[str, object]) -> list[object]:
    """The ``permissions.ask`` list of a settings document (empty when absent)."""
    permissions = settings.get("permissions", {})
    assert isinstance(permissions, dict)
    ask = permissions.get("ask", [])
    assert isinstance(ask, list)
    return ask


def test_merge_adds_the_fragment_ask_rules_once_after_the_prior_rules() -> None:
    """Run parameters (D-19 A): the fragment's ``permissions.ask`` rules reach
    ``settings.json`` once, after the prior rules; the prior ``allow`` list is kept."""
    inst = _load_installer()
    prior: dict[str, object] = {
        "permissions": {"allow": ["Bash(ls *)"], "ask": ["Bash(echo mine)"]}
    }
    before = copy.deepcopy(prior)
    fragment = _fragment()
    rules = _ask(fragment)
    assert rules, "the fragment carries no ask rules"
    once = inst.merge_hook_settings(prior, fragment)
    twice = inst.merge_hook_settings(once, fragment)
    assert prior == before, "merge_hook_settings mutated its input"
    assert twice == once
    assert _ask(once) == ["Bash(echo mine)", *rules]
    permissions = once["permissions"]
    assert isinstance(permissions, dict)
    assert permissions["allow"] == ["Bash(ls *)"]


def test_run_installs_the_ask_rules_and_verify_reports_a_missing_one(
    adopter: Path, on_windows: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Run parameters (D-19 A): ``run`` writes every fragment ``ask`` rule; ``--verify``
    fails when one is missing."""
    inst = _load_installer()
    rules = _ask(_fragment())
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    settings = _settings(adopter)
    assert _ask(settings) == rules
    assert inst.verify_only(adopter) == 0
    permissions = settings["permissions"]
    assert isinstance(permissions, dict)
    permissions["ask"] = rules[1:]
    (adopter / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    capsys.readouterr()
    assert inst.verify_only(adopter) == 2
    assert f"missing ask rule {rules[0]}" in capsys.readouterr().out


def test_full_instantiation_of_core_verifies_clean(adopter: Path, on_windows: None) -> None:
    """AC-J.3: a copied ``core/`` instantiates to a tree that ``--verify`` passes, with the
    credits module substituted."""
    inst = _load_installer()
    module = adopter / ".agent" / "skills" / "claude-credits" / "CreditsRun.psm1"
    assert "{{PROJECT_NAME_UPPER}}" in _text(module)
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    assert inst.verify_only(adopter) == 0
    text = _text(module)
    assert "{{" not in text
    assert "Local\\ACMECredits-" in text


# --- AC-J.4: the non-Windows refusal --------------------------------------------------------


def test_linux_refuses_the_scheduler(
    adopter: Path, on_linux: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-J.4: ``sys.platform = "linux"`` → the refusal message, no inbox hook entry, and
    the Windows-only files removed; the portable files stay."""
    inst = _load_installer()
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    out = capsys.readouterr().out
    assert WINDOWS_ONLY_MESSAGE in out, out
    for rel in ("tools/credits_msg.py", INBOX_HOOK, ".agent/skills/claude-credits"):
        assert rel in out, (rel, out)
    commands = [c for _e, _m, c in _entries(_settings(adopter))]
    assert not [c for c in commands if "credits_inbox" in c], commands
    assert [c for c in commands if STOP_GATE in c], commands
    assert not (adopter / "tools" / "credits_msg.py").exists()
    assert not (adopter / INBOX_HOOK).exists()
    skill = adopter / ".agent" / "skills" / "claude-credits"
    assert sorted(p.name for p in skill.iterdir()) == ["probes"]
    for rel in ("tools/credits_state.py", STOP_GATE, "tools/executor_worktree.py"):
        assert (adopter / rel).is_file(), rel


def test_linux_verify_checks_the_refusal(
    adopter: Path, on_linux: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-J.4: ``--verify`` passes after the refusal and fails when a refused file or a
    refused hook entry is back."""
    inst = _load_installer()
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    assert inst.verify_only(adopter) == 0
    restored = adopter / "tools" / "credits_msg.py"
    restored.write_text("# restored\n", encoding="utf-8")
    capsys.readouterr()
    assert inst.verify_only(adopter) == 2
    assert "credits_msg.py" in capsys.readouterr().out
    restored.unlink()
    settings = _settings(adopter)
    hooks = settings["hooks"]
    assert isinstance(hooks, dict)
    hooks.setdefault("PostToolUse", []).append(
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": f'python "{INBOX_HOOK}"'}],
        }
    )
    (adopter / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    assert inst.verify_only(adopter) == 2


def test_windows_installs_the_scheduler(adopter: Path, on_windows: None) -> None:
    """AC-J.4: on ``win32`` every credits file and hook entry is installed."""
    inst = _load_installer()
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    assert (adopter / "tools" / "credits_msg.py").is_file()
    assert (adopter / INBOX_HOOK).is_file()
    assert (adopter / ".agent" / "skills" / "claude-credits" / "Start-CreditsRunTask.ps1").is_file()
    assert [c for _e, _m, c in _entries(_settings(adopter)) if "credits_inbox" in c]


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_dry_run_writes_nothing(
    adopter: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    """AC-J.4: a dry run removes nothing and writes no settings file."""
    inst = _load_installer()
    monkeypatch.setattr(sys, "platform", platform)
    before = _snapshot(adopter)
    assert inst.run(_values(adopter), dry_run=True, root=adopter) == 0
    assert _snapshot(adopter) == before


# --- AC-J.4 boundary: a network receipts directory ------------------------------------------


@pytest.mark.parametrize(
    ("path", "network"),
    [
        ("\\\\server\\share\\acme", True),
        ("//server/share/acme", True),
        ("C:/Temp/acme", False),
        ("/tmp/acme", False),
    ],
)
def test_is_network_path(path: str, network: bool) -> None:
    """AC-J.4: a UNC receipts directory is a network path; a local one is not."""
    inst = _load_installer()
    assert inst.is_network_path(path) is network


def test_run_refuses_a_network_receipts_dir_before_any_write(adopter: Path) -> None:
    """AC-J.4: the store must be local, so ``run`` refuses a network receipts directory."""
    inst = _load_installer()
    before = _snapshot(adopter)
    with pytest.raises(ValueError, match="network"):
        inst.run(_values(adopter, receipts="//server/share/acme"), dry_run=False, root=adopter)
    assert _snapshot(adopter) == before


def test_verify_refuses_a_network_receipts_dir(
    adopter: Path, on_windows: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-J.4: ``--verify`` refuses a network receipts directory, given or installed."""
    inst = _load_installer()
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    assert inst.verify_only(adopter) == 0
    assert inst.verify_only(adopter, receipts_dir="//server/share/acme") == 2
    register = adopter / ".agent" / "skills" / "claude-credits" / "Register-CreditsRun.ps1"
    text = _text(register)
    assert "'C:/Temp/acme/credits/state.db'" in text
    register.write_text(
        text.replace("'C:/Temp/acme/credits/state.db'", "'//server/share/acme/credits/state.db'"),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert inst.verify_only(adopter) == 2
    assert "network" in capsys.readouterr().out


# --- AC-J.5: the start policy and the config --------------------------------------------------


def test_package_config_ships_both_switches_off() -> None:
    """AC-J.5: the template config is exactly the four keys with both switches off."""
    assert json.loads(_text(CONFIG_TEMPLATE)) == TEMPLATE_CONFIG


def test_no_answer_keeps_human_only(adopter: Path, on_windows: None) -> None:
    """AC-J.5: an instantiation with no answer → human-only, both switches off."""
    inst = _load_installer()
    assert inst.run(_values(adopter), dry_run=False, root=adopter) == 0
    config = json.loads(_text(adopter / ".agent" / "credits" / "config.json"))
    assert config == TEMPLATE_CONFIG


def test_an_answer_is_written(adopter: Path, on_windows: None) -> None:
    """AC-J.5: ``credits_start_policy`` writes the answer and nothing else."""
    inst = _load_installer()
    assert (
        inst.run(_values(adopter), dry_run=False, root=adopter, credits_start_policy=POLICY_CHAT)
        == 0
    )
    config = json.loads(_text(adopter / ".agent" / "credits" / "config.json"))
    assert config == {**TEMPLATE_CONFIG, "credits_start_policy": POLICY_CHAT}


def test_config_file_answer_is_written(adopter: Path, tmp_path: Path) -> None:
    """AC-J.5: ``CREDITS_START_POLICY`` in the KEY=VALUE file is the same answer."""
    v = _values(adopter)
    vars_file = tmp_path / "framework.vars"
    vars_file.write_text(
        "".join(f"{k.upper()}={val}\n" for k, val in v.items())
        + f"CREDITS_START_POLICY={POLICY_CHAT}\n",
        encoding="utf-8",
    )
    result = _cli("--root", str(adopter), "--config", str(vars_file))
    assert result.returncode == 0, result.stdout + result.stderr
    config = json.loads(_text(adopter / ".agent" / "credits" / "config.json"))
    assert config["credits_start_policy"] == POLICY_CHAT


def test_an_invalid_answer_exits_2(adopter: Path) -> None:
    """AC-J.5: any other policy value → exit 2, the tree unchanged."""
    before = _snapshot(adopter)
    result = _cli(*_cli_values(adopter), "--credits-start-policy", "anyone")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "credits-start-policy" in result.stderr or "credits_start_policy" in result.stderr
    assert _snapshot(adopter) == before


def _load_credits_msg(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    tools = CORE / "tools"
    monkeypatch.syspath_prepend(str(tools))
    for name in ("credits_state", "credits_msg"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("credits_msg", tools / "credits_msg.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "credits_msg", module)
    spec.loader.exec_module(module)
    return module


def test_credits_msg_accepts_the_four_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-J.5: the framework ``credits_msg.load_config`` accepts exactly the four keys and
    refuses a fifth or an unknown policy."""
    msg = _load_credits_msg(monkeypatch)
    path = tmp_path / "config.json"
    monkeypatch.setenv("CREDITS_CONFIG", str(path))
    path.write_text(json.dumps(TEMPLATE_CONFIG), encoding="utf-8")
    assert msg.load_config() == TEMPLATE_CONFIG
    for bad in (
        {**TEMPLATE_CONFIG, "extra": 1},
        {k: v for k, v in TEMPLATE_CONFIG.items() if k != "credits_start_policy"},
        {**TEMPLATE_CONFIG, "credits_start_policy": "anyone"},
    ):
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(msg.cs.Refusal):
            msg.load_config()


def test_powershell_side_knows_the_policy() -> None:
    """AC-J.5: ``Read-CreditsConfig`` takes the fourth key and ``Start-CreditsRunTask``
    refuses ``agent-on-user-chat`` under ``human-only``."""
    register = _text(SKILL / "Register-CreditsRun.ps1")
    assert "'credits_start_policy'" in register
    start = _text(SKILL / "Start-CreditsRunTask.ps1")
    assert "credits_start_policy" in start
    assert POLICY_DEFAULT in start and POLICY_CHAT in start


# --- AC-J.5: the template, the workflows and the harness profile ------------------------------


def test_template_gains_rows_h2_3a_to_h2_3c() -> None:
    """AC-J.5: rows H2-3a, H2-3b and H2-3c follow H2-3 and precede H2-4."""
    names = list(_template_rows())
    for name in ("H2-3", "H2-3a", "H2-3b", "H2-3c", "H2-4", "H2-5"):
        assert name in names, (name, names)
    index = names.index("H2-3")
    assert names[index : index + 5] == ["H2-3", "H2-3a", "H2-3b", "H2-3c", "H2-4"], names


def test_template_h2_3c_splits_land_capture_remove() -> None:
    """AC-J.5: H2-3c runs land → product capture → remove, the capture only with
    ``CREDITS_RUN_ID``; an interactive run keeps land → remove."""
    row = _template_rows()["H2-3c"]
    _assert_order(row, (LAND_CALL, CAPTURE_CALL, REMOVE_CALL), "H2-3c")
    assert "CREDITS_RUN_ID" in row
    assert re.search(
        r"no `CREDITS_RUN_ID`|`CREDITS_RUN_ID` is not set|without `CREDITS_RUN_ID`", row
    ), row
    assert "{{RECEIPTS_DIR}}" in row
    assert "zorivest" not in row.lower()


def test_template_seal_row_follows_h2_5_after_released_done() -> None:
    """AC-J.5 (run parameters, M7_EDITS T-1): no H2-5a seal row; H2-6 writes
    ``released:done`` and the seal is a terminal step after it."""
    rows = _template_rows()
    assert "H2-5a" not in rows, list(rows)
    assert not [n for n in rows if SEAL_CALL in rows[n]], list(rows)
    assert RELEASED_DONE in rows["H2-6"]
    text = _text(TASK_TEMPLATE)
    terminal = text.find("**Terminal steps (not rows).**")
    assert terminal > text.find(rows["H2-6"]), "the terminal steps come before H2-6"
    paragraph = " ".join(text[terminal:].split("\n\n", 1)[0].split())
    _assert_order(paragraph, ("final --produce", SEAL_CALL), "terminal steps")
    assert "credits run" in paragraph, paragraph


def test_template_four_calls_in_order() -> None:
    """AC-J.5: across the template, land → capture → remove → seal."""
    _assert_order(
        _text(TASK_TEMPLATE),
        (LAND_CALL, CAPTURE_CALL, REMOVE_CALL, SEAL_CALL),
        "TASK-TEMPLATE.md",
    )


def test_template_stop_gate_comment_names_done() -> None:
    """AC-J.5: the template front matter documents ``stop_gate`` with ``done``."""
    first = next(
        (line for line in _text(TASK_TEMPLATE).splitlines() if line.startswith("stop_gate:")),
        None,
    )
    assert first is not None, "the template has no stop_gate front-matter line"
    reasons = re.search(r"released:<([^>]+)>", first)
    assert reasons is not None, first
    assert "done" in reasons.group(1).split("|"), first


def _headless_section(path: Path) -> str:
    return _heading_section(_text(path), HEADLESS_HEADING)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_section_orders_tree_capture_and_seal(path: Path) -> None:
    """AC-J.5: each workflow section calls ``tree`` at start, then the AC-H.8 order."""
    _assert_order(
        _headless_section(path),
        (TREE_CALL, LAND_CALL, CAPTURE_CALL, REMOVE_CALL, RELEASED_DONE, SEAL_CALL),
        path.name,
    )


def test_order_check_rejects_remove_before_capture() -> None:
    """AC-J.5: a template order with ``remove`` before ``--part product`` fails."""
    bad = f"{LAND_CALL} then {REMOVE_CALL} then {CAPTURE_CALL}"
    with pytest.raises(AssertionError):
        _assert_order(bad, (LAND_CALL, CAPTURE_CALL, REMOVE_CALL), "negative")


def test_order_check_rejects_seal_before_released_done() -> None:
    """AC-J.5: a seal before ``released:done`` fails."""
    with pytest.raises(AssertionError):
        _assert_order(f"{SEAL_CALL} then {RELEASED_DONE}", (RELEASED_DONE, SEAL_CALL), "negative")


def test_flag_table_defines_mid_run_messages() -> None:
    """AC-J.5: the flag table defines ``mid_run_messages`` and the ``monitor`` notify."""
    flags = _flag_values()
    assert flags.get("mid_run_messages") == frozenset({"inbox-hook", "none"})
    assert "monitor" in (flags.get("stop_notify") or frozenset())


def test_scheduler_profile_row() -> None:
    """AC-J.5: one scheduler row with the AC-H.3 values; every row has every column."""
    header, rows = _profile_rows()
    assert "mid_run_messages" in header, header
    assert all(len(row) == len(header) for row in rows), [len(r) for r in rows]
    matching = [row for row in rows if SCHEDULER_ROW_NAME in row[0]]
    assert len(matching) == 1, f"{len(matching)} scheduler rows"
    by_flag = dict(zip(header, matching[0], strict=True))
    flags = _flag_values()
    for flag, value in SCHEDULER_FLAGS.items():
        values = BACKTICKED_RE.findall(ITALIC_NOTE_RE.sub("", by_flag[flag]))
        assert values[:1] == [value], (flag, by_flag[flag])
        allowed = flags.get(flag)
        assert allowed is None or value in allowed, (flag, value)
    turn = next(cell for name, cell in by_flag.items() if "end_turn_signal" in name)
    assert SCHEDULER_END_TURN in turn


# --- AC-J.5: the adopter guide, the update checklist and the governance anchors ---------------


def test_adoption_guide_gates_the_switches() -> None:
    """AC-J.5: the guide marks the scheduler optional and Windows-only, tells the adopter to
    review the AGENTS.md and GUARDRAILS.md diffs before either switch, and copies the hooks."""
    text = _text(ADOPTION_GUIDE)
    section = _heading_section(text, "Scheduled credits runs")
    assert "optional" in section.lower()
    assert "Windows-only" in section
    for needle in ("ruling_enabled", "gate_wait_max_min", "AGENTS.md", "GUARDRAILS.md", "review"):
        assert needle in section, needle
    assert "credits_start_policy" in section
    for source in ("core/.claude/hooks", "core/.claude/settings.hooks.json"):
        assert source in text, source


def test_update_checklist_has_the_sync_rows() -> None:
    """AC-J.5: the checklist names the ported files and the four-key divergence."""
    text = _text(UPDATE_CHECKLIST)
    for needle in (
        "claude-credits",
        "credits_state.py",
        "credits_msg.py",
        "credits_inbox.py",
        "stop_gate.py",
        "executor_worktree.py",
        "Invoke-ClaudeDispatch.ps1",
        "Get-ClaudeDispatch.ps1",
        "settings.hooks.json",
        "credits_start_policy",
    ):
        assert needle in text, needle


@pytest.mark.parametrize("index", range(4))
def test_governance_anchor_is_in_its_core_file(index: int) -> None:
    """AC-J.5: each anchor that ``Register-CreditsRun.ps1`` requires is in its core file,
    so an adopter can turn a switch on after the review."""
    rel, line = _governance_anchors()[index]
    path = CORE / rel
    assert path.is_file(), rel
    assert line in _text(path), (rel, line)


def test_governance_markers_name_done_and_the_ruling() -> None:
    """AC-J.5: ``released:done`` is in the AGENTS.md DONE text; the bounded wait and the
    verified ruling frame are in AGENTS.md and GUARDRAILS.md."""
    agents = _text(CORE / "AGENTS.md")
    guardrails = _text(CORE / "GUARDRAILS.md")
    assert RELEASED_DONE in agents
    assert "gate-wait-then-exit" in agents
    assert "ruling (verified:" in guardrails


def test_installer_cli_lists_the_policy_flag() -> None:
    """AC-J.5: ``--help`` documents ``--credits-start-policy`` and its two values."""
    result = _cli("--help")
    assert result.returncode == 0, result.stderr
    assert "--credits-start-policy" in result.stdout
    assert POLICY_DEFAULT in result.stdout and POLICY_CHAT in result.stdout
