"""The fleet agents plan's fleet.py and member_kit.py ACs, numbered as in the plan."""
from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import itertools
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from fleet_harness import FLEET_PY, Hub, fleet, new_envelope, wait_until  # noqa: E402
from test_fleet_hub import FAKE_SECRETS, FORBIDDEN_TEXT, source_problems  # noqa: E402
from test_fleet_bootstrap import TEMPLATE, template_problems  # noqa: E402

MEMBER_KIT = FLEET_PY.parent / "member_kit.py"
REPO = FLEET_PY.parents[2]


@pytest.fixture
def hub(tmp_path):
    h = Hub(tmp_path)
    h.start()
    yield h
    h.close()


def last_json(r) -> dict:
    return json.loads(r.stdout.strip().splitlines()[-1])


# AC-1: source rules, and pwsh as a reported capability


def test_ac01_member_kit_source_rules_hold():
    assert source_problems(MEMBER_KIT.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("line", ["import requests", "X = '" + FORBIDDEN_TEXT[1] + "'"])
def test_ac01_the_checker_fails_a_bad_copy(line):
    assert source_problems(MEMBER_KIT.read_text(encoding="utf-8") + "\n" + line + "\n")


def test_ac01_pwsh_is_a_capability_tool():
    assert "pwsh" in fleet.CAPABILITY_TOOLS


def test_ac01_a_member_hello_reports_pwsh(hub):
    member = hub.pair("local")
    member.start()

    def listed():
        rows = last_json(hub.cli("status"))["members"]
        return rows[0]["capabilities"] if rows and rows[0]["capabilities"] else None

    wait_until(listed, timeout=30)
    assert "pwsh" in listed()


# AC-14, AC-15: member_kit.py. Chain: C-KIT from main, as a child process with a temp FLEET_HOME, profile
# and CLAUDE_CONFIG_DIR. Negative installs use a stub instantiate, which is what lets --verify fail on demand.


FAKE_TOKEN = "fake-oauth-" + "a1b2c3d4" * 6
RUN_TASK = "\\Fleet\\Credits\\run-1"
MONITOR_TASK = "\\Fleet\\Credits\\Monitor"
PWSH_SHIM = '''import sys
from pathlib import Path
here = Path(__file__).parent
print((here / "tasks.txt").read_text(encoding="utf-8") if (here / "tasks.txt").exists() else "")
sys.exit(int((here / "tasks-exit.txt").read_text()) if (here / "tasks-exit.txt").exists() else 0)
'''
STUB_INSTANTIATE = '''import os, sys
sys.exit(int(os.environ.get("STUB_VERIFY_EXIT", "0")) if "--verify" in sys.argv else 0)
'''
STUB_GATE = '''import argparse, json, os, sys
from pathlib import Path
p = argparse.ArgumentParser()
for flag in ("--out", "--project", "--python", "--claude"):
    p.add_argument(flag)
args = p.parse_args()
Path(os.environ["STUB_RECORD"]).write_text(json.dumps({"env": sorted(os.environ), "scrub": os.environ.get("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"), "argv": sys.argv[1:]}), encoding="utf-8")
mode, token = os.environ["STUB_MODE"], os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
if mode == "die":
    sys.exit(1)
receipt = Path(args.out) / "gate-result.json"
receipt.write_text(json.dumps({"qualifying": True, "text": token if mode == "leak" else "clean"}), encoding="utf-8")
if mode == "leak-project":
    (Path(args.project) / "transcript.txt").write_text(token, encoding="utf-8")
if mode == "echo":
    print("stdout has " + token)
    print("stderr has " + token, file=sys.stderr)
print("GATE live PASS")
sys.exit(3 if mode == "fail" else 0)
'''


def tree_digest(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


def files_holding(root: Path, value: str) -> list[str]:
    return [p.as_posix() for p in root.rglob("*") if p.is_file() and value.encode() in p.read_bytes()]


class KitRig:
    """A slot and a member home, all in a temp folder, with shims for pwsh and claude first on PATH."""

    def __init__(self, base: Path):
        self.base = base
        self.home = base / "fleet-home"
        self.profile = base / "profile"
        self.config = base / "claude-config"
        self.bin = base / "bin"
        self.slot = base / "slot"
        self.record = base / "stub-record.json"
        for folder in (self.home, self.profile, self.config, self.bin):
            folder.mkdir(parents=True)
        (self.bin / "pwsh_shim.py").write_text(PWSH_SHIM, encoding="utf-8")
        (self.bin / "pwsh.cmd").write_text(f'@"{sys.executable}" "{self.bin / "pwsh_shim.py"}" %*\n', encoding="utf-8")
        (self.bin / "claude.cmd").write_text("@echo 1.0.0 (Claude Code)\n", encoding="utf-8")
        self.place(MEMBER_KIT, ".agent/fleet/member_kit.py")
        self.place_text("registry module\n", ".agent/tools/ModelRegistry.psm1")
        self.place_text("# tasks\n", ".agent/fleet/fleet-tasks.ps1")

    def place(self, source: Path, rel: str) -> None:
        target = self.slot / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def place_text(self, text: str, rel: str, root: Path | None = None) -> Path:
        target = (root or self.slot) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def stub_slot(self) -> "KitRig":
        self.place_text(STUB_INSTANTIATE, "scripts/instantiate.py")
        self.place_text("kit v2\n", "core/marker.txt")
        self.place_text("# hook\n", "core/.claude/hooks/credits_inbox.py")
        return self

    def real_slot(self) -> "KitRig":
        shutil.copytree(REPO / "core", self.slot / "core", ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("instantiate.py", "placeholders.py"):
            self.place(REPO / "scripts" / name, f"scripts/{name}")
        self.place(REPO / ".agent/fleet/fleet-tasks.ps1", ".agent/fleet/fleet-tasks.ps1")
        return self

    def old_kit(self) -> dict:
        self.place_text("kit v1\n", "marker.txt", self.home / "kit")
        return tree_digest(self.home / "kit")

    def stub_gate(self) -> "KitRig":
        self.place_text(STUB_GATE, "kit/.agent/skills/claude-credits/probes/run_gate.py", self.home)
        return self

    def token(self, text: str = FAKE_TOKEN) -> None:
        self.place_text(text, "credentials/claude-oauth-token", self.home)

    def tasks(self, *names: str, code: int = 0) -> None:
        (self.bin / "tasks.txt").write_text("\n".join(names), encoding="utf-8")
        (self.bin / "tasks-exit.txt").write_text(str(code), encoding="utf-8")

    def run(self, action: str, **env) -> subprocess.CompletedProcess:
        full = {
            **os.environ,
            "FLEET_HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.config),
            "USERPROFILE": str(self.profile), "HOME": str(self.profile),
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "STUB_RECORD": str(self.record),
            **env,
        }
        return subprocess.run(
            [sys.executable, str(self.slot / ".agent/fleet/member_kit.py"), action], cwd=self.slot, env=full,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )

    def settings(self) -> dict:
        return json.loads((self.config / "settings.json").read_text(encoding="utf-8"))


@pytest.fixture
def rig(tmp_path):
    return KitRig(tmp_path)


def load_member_kit():
    spec = importlib.util.spec_from_file_location("member_kit", MEMBER_KIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def real_user_settings() -> str | None:
    path = Path.home() / ".claude" / "settings.json"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """One real install: the real core/ and the real instantiate.py, over settings that hold other keys."""
    rig = KitRig(tmp_path_factory.mktemp("kit")).real_slot()
    rig.place_text(
        json.dumps({"theme": "dark", "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "other"}]}]}}),
        "settings.json", rig.config,
    )
    before = real_user_settings()
    rig.result = rig.run("install")
    rig.real_settings_unchanged = real_user_settings() == before
    assert rig.result.returncode == 0, rig.result.stdout + rig.result.stderr
    return rig


def test_ac14_install_fills_the_kit_for_this_member(installed):
    kit, home = installed.home / "kit", installed.home.as_posix()
    verify = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "instantiate.py"), "--root", str(kit), "--verify"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    start = (kit / ".agent/skills/claude-credits/Start-CreditsRun.ps1").read_text(encoding="utf-8")
    assert f"{home}/credentials/claude-oauth-token" in start
    assert f"{home}/receipts/credits/state.db" in start
    assert "{{" + "PROJECT_ROOT" + "}}" not in start
    assert json.loads((kit / ".agent/credits/config.json").read_text(encoding="utf-8"))["credits_start_policy"] == "agent-on-user-chat"
    assert "'\\Fleet\\Credits\\'" in (kit / ".agent/skills/claude-credits/CreditsRun.psm1").read_text(encoding="utf-8")
    assert not (installed.home / "kit-new").exists() and not (installed.home / "kit-old").exists()


def test_ac14_the_hook_merge_keeps_other_keys_and_adds_only_the_inbox_hook(installed):
    settings = installed.settings()
    assert settings["theme"] == "dark"
    assert settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == "other"
    added = [settings["hooks"]["PostToolUse"][1], settings["hooks"]["Stop"][0]]
    assert added[0]["matcher"] == "*"
    assert "matcher" not in added[1]
    for entry in added:
        words = shlex.split(entry["hooks"][0]["command"])
        assert len(words) == 2 and Path(words[1]).is_absolute() and Path(words[1]).is_file()
        assert Path(words[1]) == installed.home / "kit" / ".claude" / "hooks" / "credits_inbox.py"
    text = json.dumps(settings)
    assert "stop_gate" not in text and "commit_gate" not in text


def test_ac14_install_writes_the_lock_name_and_the_registry_module(installed):
    doc = json.loads((installed.home / "receipts/credits/launcher.env.json").read_text(encoding="utf-8"))
    assert doc["env"]["FLEET_CODEX_LOCK"] == (installed.home / "codex.lock").as_posix()
    assert (installed.profile / ".agent/tools/ModelRegistry.psm1").read_text(encoding="utf-8") == "registry module\n"


def test_ac14_the_real_user_settings_are_untouched(installed):
    assert installed.real_settings_unchanged


@pytest.mark.parametrize("task", [RUN_TASK, "\\Fleet\\Codex\\run-1"])
def test_ac14_a_running_run_task_refuses_and_keeps_the_kit(rig, task):
    rig.stub_slot()
    before = rig.old_kit()
    rig.tasks(MONITOR_TASK, task)
    r = rig.run("install")
    assert r.returncode != 0 and "run_active" in r.stderr
    assert tree_digest(rig.home / "kit") == before
    assert not (rig.config / "settings.json").exists()


def test_ac14_a_task_list_that_cannot_be_read_refuses(rig):
    rig.stub_slot()
    before = rig.old_kit()
    rig.tasks(code=1)
    r = rig.run("install")
    assert r.returncode != 0 and "run_active" in r.stderr
    assert tree_digest(rig.home / "kit") == before


def test_ac14_the_monitor_running_does_not_block(rig):
    rig.stub_slot().old_kit()
    rig.tasks(MONITOR_TASK)
    r = rig.run("install")
    assert r.returncode == 0, r.stderr
    assert (rig.home / "kit/marker.txt").read_text(encoding="utf-8") == "kit v2\n"


def test_ac14_a_retained_stopped_run_does_not_block_and_stays(rig):
    rig.stub_slot().old_kit()
    folder = rig.home / "agent" / "run-1"
    rig.place_text("{}", "manifest.json", folder)
    before = tree_digest(folder)
    r = rig.run("install")
    assert r.returncode == 0, r.stderr
    assert tree_digest(folder) == before


def test_ac14_a_failing_verify_keeps_the_old_kit(rig):
    rig.stub_slot()
    before = rig.old_kit()
    r = rig.run("install", STUB_VERIFY_EXIT="2")
    assert r.returncode != 0
    assert tree_digest(rig.home / "kit") == before
    assert not (rig.config / "settings.json").exists()


def test_ac14_a_held_file_gives_kit_busy_and_keeps_the_kit(rig):
    rig.stub_slot()
    before = rig.old_kit()
    with (rig.home / "kit/marker.txt").open("rb"):
        r = rig.run("install")
    assert r.returncode != 0 and "kit_busy" in r.stderr
    assert tree_digest(rig.home / "kit") == before
    assert not (rig.home / "kit-old").exists()


def test_ac14_a_failing_second_rename_restores_the_old_kit(rig, monkeypatch):
    before = rig.old_kit()
    rig.place_text("kit v2\n", "marker.txt", rig.home / "kit-new")
    member_kit = load_member_kit()
    real_rename = os.rename

    def rename(src, dst):
        if Path(src).name == "kit-new":
            raise PermissionError("held")
        real_rename(src, dst)

    monkeypatch.setattr(member_kit.os, "rename", rename)
    with pytest.raises(member_kit.KitRefusal, match="kit_busy"):
        member_kit.swap_kit(rig.home)
    assert tree_digest(rig.home / "kit") == before
    assert not (rig.home / "kit-old").exists()


def test_ac14_a_rerun_recovers_after_a_crash_between_the_renames(rig):
    rig.stub_slot()
    rig.place_text("kit v1\n", "marker.txt", rig.home / "kit-old")
    r = rig.run("install")
    assert r.returncode == 0, r.stderr
    assert (rig.home / "kit/marker.txt").read_text(encoding="utf-8") == "kit v2\n"
    assert not (rig.home / "kit-old").exists()


def test_ac14_a_second_install_adds_no_duplicate_hook(rig):
    rig.stub_slot()
    assert rig.run("install").returncode == 0
    first = rig.settings()
    r = rig.run("install")
    assert r.returncode == 0, r.stderr
    assert rig.settings() == first
    assert len(first["hooks"]["PostToolUse"]) == 1 and len(first["hooks"]["Stop"]) == 1


def test_ac14_a_second_install_keeps_other_launcher_env(rig):
    rig.stub_slot()
    rig.place_text(json.dumps({"env": {"OTHER": "x"}, "path_prepend": ["C:/tools"]}), "receipts/credits/launcher.env.json", rig.home)
    assert rig.run("install").returncode == 0
    doc = json.loads((rig.home / "receipts/credits/launcher.env.json").read_text(encoding="utf-8"))
    assert doc["env"]["OTHER"] == "x" and doc["path_prepend"] == ["C:/tools"] and "FLEET_CODEX_LOCK" in doc["env"]


@pytest.mark.parametrize("text", ["not json", "[]", '{"hooks": []}', '{"hooks": {"Stop": {}}}'])
def test_ac14_a_bad_settings_file_refuses_before_any_change(rig, text):
    rig.stub_slot()
    before = rig.old_kit()
    rig.place_text(text, "settings.json", rig.config)
    r = rig.run("install")
    assert r.returncode != 0 and "settings_invalid" in r.stderr
    assert tree_digest(rig.home / "kit") == before
    assert (rig.config / "settings.json").read_text(encoding="utf-8") == text


def test_ac14_the_task_script_is_copied(rig):
    rig.stub_slot()
    assert rig.run("install").returncode == 0
    assert (rig.home / "kit/fleet/fleet-tasks.ps1").read_text(encoding="utf-8") == "# tasks\n"


def test_ac14_a_slot_without_the_task_script_keeps_the_old_kit(rig):
    rig.stub_slot()
    (rig.slot / ".agent/fleet/fleet-tasks.ps1").unlink()
    before = rig.old_kit()
    r = rig.run("install")
    assert r.returncode != 0 and "tasks_missing" in r.stderr
    assert tree_digest(rig.home / "kit") == before
    assert not (rig.config / "settings.json").exists()


def test_ac14_the_tracked_manifest_names_both_commands():
    manifest = json.loads((REPO / ".agent" / "fleet.json").read_text(encoding="utf-8"))
    assert fleet.validate_manifest(manifest) is None
    assert manifest["commands"]["kit-install"] == [["python", ".agent/fleet/member_kit.py", "install"]]
    assert manifest["commands"]["kit-gate"] == [["python", ".agent/fleet/member_kit.py", "gate"]]


def test_ac15_a_clean_gate_runs_in_the_scheduled_environment_and_keeps_the_receipt(rig):
    rig.stub_gate().token()
    r = rig.run("gate", STUB_MODE="clean", ANTHROPIC_API_KEY="parent-key", ANTHROPIC_AUTH_TOKEN="parent-auth")
    assert r.returncode == 0, r.stdout + r.stderr
    record = json.loads(rig.record.read_text(encoding="utf-8"))
    assert "CLAUDE_CODE_OAUTH_TOKEN" in record["env"]
    assert record["scrub"] == "1"
    assert "ANTHROPIC_API_KEY" not in record["env"] and "ANTHROPIC_AUTH_TOKEN" not in record["env"]
    assert record["argv"][record["argv"].index("--project") + 1] == str(rig.home / "gate-project")
    assert record["argv"][record["argv"].index("--out") + 1] == str(rig.home / "receipts" / "gate")
    assert Path(record["argv"][record["argv"].index("--python") + 1]).samefile(sys.executable)
    assert record["argv"][record["argv"].index("--claude") + 1].lower().endswith("claude.cmd")
    assert json.loads((rig.home / "receipts/gate/gate-result.json").read_text(encoding="utf-8"))["qualifying"] is True
    assert "GATE live PASS" in r.stdout
    assert FAKE_TOKEN not in r.stdout + r.stderr


@pytest.mark.parametrize("text", [None, "", " \r\n"])
def test_ac15_a_missing_or_empty_token_file_refuses(rig, text):
    rig.stub_gate()
    if text is not None:
        rig.token(text)
    r = rig.run("gate", STUB_MODE="clean")
    assert r.returncode != 0 and "token_missing" in r.stderr
    assert not rig.record.exists()


@pytest.mark.parametrize("mode", ["leak", "leak-project"])
def test_ac15_a_leak_leaves_no_receipt_and_no_file_with_the_token(rig, mode):
    rig.stub_gate().token()
    r = rig.run("gate", STUB_MODE=mode)
    assert r.returncode != 0 and "gate_token_leak" in r.stderr
    assert not (rig.home / "receipts/gate/gate-result.json").exists()
    assert files_holding(rig.home, FAKE_TOKEN) == [(rig.home / "credentials/claude-oauth-token").as_posix()]


def test_ac15_an_echoed_token_is_redacted(rig):
    rig.stub_gate().token()
    r = rig.run("gate", STUB_MODE="echo")
    assert r.returncode == 0, r.stderr
    assert FAKE_TOKEN not in r.stdout + r.stderr
    assert "stdout has [redacted]" in r.stdout and "stderr has [redacted]" in r.stdout


def test_ac15_a_failing_gate_keeps_its_exit_code(rig):
    rig.stub_gate().token()
    assert rig.run("gate", STUB_MODE="fail").returncode == 3


def test_ac15_an_old_receipt_does_not_survive_a_new_gate(rig):
    rig.stub_gate().token()
    rig.place_text('{"qualifying": true}', "receipts/gate/gate-result.json", rig.home)
    r = rig.run("gate", STUB_MODE="die")
    assert r.returncode == 1
    assert not (rig.home / "receipts/gate/gate-result.json").exists()


def test_ac15_a_gate_with_no_kit_refuses(rig):
    rig.token()
    r = rig.run("gate", STUB_MODE="clean")
    assert r.returncode != 0 and "kit_missing" in r.stderr


# AC-41: the SUPER half of commit identity. Each test sets GIT_CONFIG_GLOBAL to its own file, so the test
# machine's config can't decide the result.


SNAP_NAME = "Fixture Person"
SNAP_EMAIL = "1+fixture@users.noreply.github.com"
SNAP_MANIFEST = {"v": 1, "project": "demo", "requires": ["python"], "commands": {"test": [["python", "-V"]]}}


def run_git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def commit_count(repo: Path) -> int:
    objects = run_git(repo, "cat-file", "--batch-all-objects", "--batch-check=%(objecttype)")
    return objects.split().count("commit")


def identity_state(repo: Path) -> tuple:
    return commit_count(repo), run_git(repo, "for-each-ref")


@pytest.fixture
def global_identity(tmp_path, monkeypatch):
    """Write this test's global git config. No argument leaves that value unset."""
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    path = tmp_path / "global-gitconfig"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(path))

    def write(name: str | None = None, email: str | None = None) -> None:
        lines = ["[user]"] + ([f"\tname = {name}"] if name else []) + ([f"\temail = {email}"] if email else [])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return write


@pytest.fixture
def snap_repo(tmp_path, global_identity):
    """A repo with one commit, a manifest and a dirty file. Its own user values are set by the test."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q")
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    (repo / ".agent").mkdir()
    (repo / ".agent" / "fleet.json").write_text(json.dumps(SNAP_MANIFEST), encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "-c", "user.name=first", "-c", "user.email=first@example.invalid", "commit", "-q", "--no-verify", "--no-gpg-sign", "-m", "first")
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
    return repo


def set_repo_identity(repo: Path, name: str | None, email: str | None) -> None:
    if name:
        run_git(repo, "config", "user.name", name)
    if email:
        run_git(repo, "config", "user.email", email)


def test_ac41_the_commit_carries_the_checked_identity(snap_repo, global_identity):
    global_identity(SNAP_NAME, SNAP_EMAIL)
    refs, _ = fleet.make_snapshot(snap_repo, fleet.new_id())
    assert run_git(snap_repo, "log", "-1", "--format=%an|%ae|%cn|%ce", refs["commit"]) == f"{SNAP_NAME}|{SNAP_EMAIL}|{SNAP_NAME}|{SNAP_EMAIL}"


def test_ac41_the_environment_can_not_change_the_commit(snap_repo, global_identity, monkeypatch):
    global_identity(SNAP_NAME, SNAP_EMAIL)
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "Someone Else")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "2+else@users.noreply.github.com")
    refs, _ = fleet.make_snapshot(snap_repo, fleet.new_id())
    assert run_git(snap_repo, "log", "-1", "--format=%an|%ae|%cn|%ce", refs["commit"]) == f"{SNAP_NAME}|{SNAP_EMAIL}|{SNAP_NAME}|{SNAP_EMAIL}"


def test_ac41_a_repo_value_equal_to_the_global_one_is_accepted(snap_repo, global_identity):
    global_identity(SNAP_NAME, SNAP_EMAIL)
    set_repo_identity(snap_repo, SNAP_NAME, SNAP_EMAIL)
    assert fleet.snapshot_identity(snap_repo) == (SNAP_NAME, SNAP_EMAIL)


def test_ac41_a_given_identity_is_used_as_it_is(snap_repo, global_identity):
    refs, _ = fleet.make_snapshot(snap_repo, fleet.new_id(), identity=(SNAP_NAME, SNAP_EMAIL))
    assert run_git(snap_repo, "log", "-1", "--format=%an|%ae", refs["commit"]) == f"{SNAP_NAME}|{SNAP_EMAIL}"


def test_ac41_the_run_route_carries_the_identity(hub, snap_repo, global_identity):
    global_identity(SNAP_NAME, SNAP_EMAIL)
    hub.pair("alpha")
    r = hub.cli("run", "alpha", "--repo", str(snap_repo), "test")
    assert r.returncode == 0, r.stdout + r.stderr
    run = last_json(r)
    bundle = hub.hub_dir / "blobs" / run["bundle"]
    reader = snap_repo.parent / "reader"
    reader.mkdir()
    run_git(reader, "init", "-q")
    run_git(reader, "fetch", "-q", str(bundle), f"refs/fleet/snap/{run['task']}:refs/heads/snap")
    assert run_git(reader, "log", "-1", "--format=%an|%ae|%cn|%ce", "snap") == f"{SNAP_NAME}|{SNAP_EMAIL}|{SNAP_NAME}|{SNAP_EMAIL}"


IDENTITY_REFUSALS = [
    pytest.param((None, None), (SNAP_NAME, SNAP_EMAIL), "identity_missing", id="no-global-with-repo-set"),
    pytest.param((None, None), (None, None), "identity_missing", id="no-value-anywhere"),
    pytest.param((SNAP_NAME, None), (None, SNAP_EMAIL), "identity_missing", id="no-global-address"),
    pytest.param((None, SNAP_EMAIL), (SNAP_NAME, None), "identity_missing", id="no-global-name"),
    pytest.param((SNAP_NAME, SNAP_EMAIL), (None, "2+other@users.noreply.github.com"), "identity_mismatch", id="repo-address-differs"),
    pytest.param((SNAP_NAME, SNAP_EMAIL), ("Other Name", None), "identity_mismatch", id="repo-name-differs"),
    pytest.param((SNAP_NAME, "person@example.invalid"), (None, None), "identity_mismatch", id="address-fails-suffix"),
]


@pytest.mark.parametrize("glob,local,code", IDENTITY_REFUSALS)
def test_ac41_make_snapshot_refuses_and_leaves_nothing(snap_repo, global_identity, glob, local, code):
    global_identity(*glob)
    set_repo_identity(snap_repo, *local)
    before = identity_state(snap_repo)
    with pytest.raises(fleet.Refuse) as e:
        fleet.make_snapshot(snap_repo, fleet.new_id())
    assert e.value.code == code
    assert identity_state(snap_repo) == before


@pytest.mark.parametrize("glob,local,code", IDENTITY_REFUSALS)
def test_ac41_the_run_route_refuses_and_sends_no_blob(hub, snap_repo, global_identity, glob, local, code):
    global_identity(*glob)
    set_repo_identity(snap_repo, *local)
    hub.pair("alpha")
    before = identity_state(snap_repo)
    r = hub.cli("run", "alpha", "--repo", str(snap_repo), "test")
    assert r.returncode == fleet.EXIT_CODES["refused"]
    assert r.stderr.strip() == code
    assert identity_state(snap_repo) == before
    assert not list((hub.hub_dir / "blobs").iterdir())


def test_ac41_an_empty_repo_still_gets_no_head(tmp_path, global_identity):
    global_identity(SNAP_NAME, SNAP_EMAIL)
    repo = tmp_path / "empty"
    repo.mkdir()
    run_git(repo, "init", "-q")
    with pytest.raises(fleet.Refuse) as e:
        fleet.make_snapshot(repo, fleet.new_id())
    assert e.value.code == "no_head"


def test_ac41_fleet_py_holds_no_fixed_identity_and_no_address():
    text = FLEET_PY.read_text(encoding="utf-8")
    assert "SNAPSHOT_IDENTITY" not in text
    assert re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text) == []
    assert fleet.SNAPSHOT_EMAIL_SUFFIX == "@users.noreply.github.com"


# AC-17 to AC-20: the hub's check on an agent task. Chain: C-AGENT-HUB, over HTTP to a real hub. Refusal tables loop
# inside one test, on one hub, because a hub per case costs seconds each.


BUNDLE = "c" * 64
AGENT_REFS = {"commit": "a" * 40, "tree": "b" * 40, "bundle": BUNDLE}
WORDS = "Start the row 12 test job."


def seed_agent_hub(h: Hub) -> None:
    h.pair("local")
    (h.hub_dir / "blobs" / BUNDLE).write_bytes(b"bundle")


@pytest.fixture(scope="module")
def agent_hub(tmp_path_factory):
    h = Hub(tmp_path_factory.mktemp("agent-hub"))
    h.start()
    seed_agent_hub(h)
    yield h
    h.close()


def agent_body(action: str, cli: str = "claude") -> dict:
    body = {"run": "run-1", "action": action}
    if action == "start":
        body.update(cli=cli, brief="Do the row.")
        if cli == "claude":
            body.update(segment_cap_usd=5, run_cap_usd=20)
    elif action == "resume":
        body["brief"] = "Mat's answer."
    elif action == "message":
        body.update(message_kind="query", text="Where are you?")
    return body


def agent_env(action: str, cli: str = "claude", drop: tuple = (), **fields) -> dict:
    """An agent task that passes the hub, changed by body fields and any `refs` or `start_quote` keyword."""
    envelope = {
        "refs": dict(AGENT_REFS) if action == "start" else {},
        "start_quote": WORDS if action in ("start", "resume") else None,
    }
    for name in tuple(envelope):
        if name in fields:
            envelope[name] = fields.pop(name)
    body = {**agent_body(action, cli), **fields}
    for name in drop:
        del body[name]
    return new_envelope("orchestrator", "local", "agent", body=body, **envelope)


def post_agent(h: Hub, env: dict) -> tuple:
    """The HTTP code, the refusal and the number of rows the post added."""
    before = h.rows()
    status, reply = h.request("POST", "/v1/tasks", env, key=h.client().key)
    return status, reply.get("error"), h.rows() - before


REFUSED_NOTHING = (200, None, 1)


def refused(code: str) -> tuple:
    return (422, code, 0)


def test_ac17_executors_match_the_send_policy():
    assert fleet.SEND_POLICY["orchestrator"] == {"ping", "run", "agent"}
    assert fleet.SEND_POLICY["member"] == frozenset()
    assert set(fleet.EXECUTORS) == set().union(*fleet.SEND_POLICY.values())


def test_ac17_kind_not_enabled_is_gone():
    assert "kind_not_enabled" not in fleet.REFUSALS
    assert "kind_not_enabled" not in FLEET_PY.read_text(encoding="utf-8")


def test_ac17_a_member_cannot_send_an_agent_task(hub):
    member = hub.pair("sender")
    hub.pair("local")
    before = hub.rows()
    status, reply = hub.request("POST", "/v1/tasks", agent_env("status"), key=member.key())
    assert (status, reply["error"]) == (403, "from_mismatch")
    env = {**agent_env("status"), "from": "sender"}
    status, reply = hub.request("POST", "/v1/tasks", env, key=member.key())
    assert (status, reply["error"]) == (403, "sender_not_allowed")
    assert hub.rows() == before


def test_ac17_the_orchestrator_can_send_every_action(agent_hub):
    assert set(fleet.AGENT_ACTIONS) == {"start", "status", "message", "stop", "resume", "collect", "drop"}
    for action in fleet.AGENT_ACTIONS:
        assert post_agent(agent_hub, agent_env(action)) == REFUSED_NOTHING, action


def test_ac17_stopped_has_its_exit_code():
    assert fleet.EXIT_CODES["stopped"] == 7
    assert len(set(fleet.EXIT_CODES.values())) == len(fleet.EXIT_CODES)


@pytest.mark.parametrize("code", ["quote_required", "quote_not_allowed", "unknown_action", "bad_agent_body", "message_kind_refused"])
def test_ac17_new_refusals_are_422(code):
    assert fleet.REFUSALS[code] == 422


def test_ac18_start_and_resume_need_mats_words(agent_hub):
    assert set(fleet.QUOTE_ACTIONS) == {"start", "resume"}
    for action in fleet.QUOTE_ACTIONS:
        for quote in (None, "", "   ", " \t\n"):
            assert post_agent(agent_hub, agent_env(action, start_quote=quote)) == refused("quote_required"), (action, quote)


def test_ac18_a_refused_start_never_reaches_the_member(hub):
    (hub.hub_dir / "blobs" / BUNDLE).write_bytes(b"bundle")
    client = hub.pair("local").hello()
    assert post_agent(hub, agent_env("start", start_quote=None)) == refused("quote_required")
    status, reply = fleet.hub_request(client, "GET", "/v1/tasks/next")
    assert (status, reply["task"]) == (200, None)


def test_ac18_other_actions_carry_no_quote(agent_hub):
    others = [a for a in fleet.AGENT_ACTIONS if a not in fleet.QUOTE_ACTIONS]
    assert others
    for action in others:
        for quote in (WORDS, "", "   "):
            assert post_agent(agent_hub, agent_env(action, start_quote=quote)) == refused("quote_not_allowed"), (action, quote)


def test_ac18_a_secret_shaped_quote_is_refused(agent_hub):
    for action in fleet.QUOTE_ACTIONS:
        env = agent_env(action, start_quote="sk-" + "ant-abcdef")
        assert post_agent(agent_hub, env) == refused("secret_in_message"), action


def test_ac18_the_quote_is_kept_exactly(agent_hub):
    env = agent_env("start", start_quote="  Mat's words, as typed. ")
    assert post_agent(agent_hub, env) == REFUSED_NOTHING
    with sqlite3.connect(agent_hub.db) as conn:
        stored = conn.execute("SELECT envelope FROM messages WHERE id=?", (env["id"],)).fetchall()
    assert [json.loads(e)["start_quote"] for e, in stored] == ["  Mat's words, as typed. "]


@pytest.mark.parametrize("action", ["exec", "", 5, None, ["start"]])
def test_ac19_an_unknown_action_is_refused(agent_hub, action):
    env = new_envelope("orchestrator", "local", "agent", body={"run": "run-1", "action": action})
    assert post_agent(agent_hub, env) == refused("unknown_action")


def test_ac19_no_action_is_refused(agent_hub):
    env = new_envelope("orchestrator", "local", "agent", body={"run": "run-1"})
    assert post_agent(agent_hub, env) == refused("unknown_action")


def test_ac19_extra_fields_are_refused(agent_hub):
    for action in fleet.AGENT_ACTIONS:
        for name in ("command", "other"):
            env = agent_env(action, **{name: "x"})
            assert post_agent(agent_hub, env) == refused(f"bad_agent_body:unknown_field:{name}"), (action, name)


def test_ac19_each_required_field_is_required(agent_hub):
    for action in fleet.AGENT_ACTIONS:
        for name in agent_body(action):
            if name == "action":
                continue
            env = agent_env(action, drop=(name,))
            assert post_agent(agent_hub, env) == refused(f"bad_agent_body:missing_field:{name}"), (action, name)


def test_ac19_each_action_lists_the_fields_of_the_plan():
    assert {a: set(f) for a, f in fleet.AGENT_BODY_FIELDS.items()} == {
        "start": {"run", "action", "cli", "brief"},
        "status": {"run", "action"},
        "message": {"run", "action", "message_kind", "text"},
        "stop": {"run", "action"},
        "resume": {"run", "action", "brief"},
        "collect": {"run", "action"},
        "drop": {"run", "action"},
    }


def test_ac19_a_bad_run_name_is_refused(agent_hub):
    for action in fleet.AGENT_ACTIONS:
        for run in ("Bad_Name", "../x", "", 5, None):
            assert post_agent(agent_hub, agent_env(action, run=run)) == refused("bad_agent_body:run"), (action, run)


def test_ac19_bad_start_values_are_refused(agent_hub):
    cases = {
        "cli": ["gemini", "", 5, None],
        "brief": ["", "   ", 5, None],
        "segment_cap_usd": [0, -1, True, "5", None, float("inf")],
        "run_cap_usd": [0, -1, True, "5", None, float("inf")],
        "timeout_sec": [0, -1, 1.5, True, "60", None],
        "model": ["", "  ", 5, None],
        "effort": ["extreme", "", 5, None],
        "allow_codex": ["yes", 1, None],
        "allowed_tools": ["Read", [5], {"Read": 1}, None],
    }
    for name, values in cases.items():
        for value in values:
            env = agent_env("start", **{name: value})
            assert post_agent(agent_hub, env) == refused(f"bad_agent_body:{name}"), (name, value)


def test_ac19_good_optional_fields_pass(agent_hub):
    env = agent_env("start", timeout_sec=600, model="fake-claude-model", effort="high", allowed_tools=["Read", "Edit"], allow_codex=True)
    assert post_agent(agent_hub, env) == REFUSED_NOTHING
    env = agent_env("start", "codex", timeout_sec=600, model="fake-codex-model", effort="high")
    assert post_agent(agent_hub, env) == REFUSED_NOTHING


def test_ac19_the_effort_values_are_the_credits_schemas():
    schema = json.loads((REPO / "core/.agent/skills/claude-credits/schemas/credits-run.v1.json").read_text(encoding="utf-8"))
    assert list(fleet.AGENT_EFFORTS) == schema["properties"]["launch"]["properties"]["effort"]["enum"]


@pytest.mark.parametrize("name,value", [("allowed_tools", ["Read"]), ("allow_codex", True), ("segment_cap_usd", 5), ("run_cap_usd", 20)])
def test_ac19_a_codex_start_refuses_the_claude_fields(agent_hub, name, value):
    env = agent_env("start", "codex", **{name: value})
    assert post_agent(agent_hub, env) == refused(f"bad_agent_body:unknown_field:{name}")


def test_ac19_start_refs_are_closed(agent_hub):
    missing = {k: v for k, v in AGENT_REFS.items() if k != "tree"}
    for refs in ({}, missing, {**AGENT_REFS, "extra": "x"}, {**AGENT_REFS, "commit": "short"}, {**AGENT_REFS, "bundle": "short"}, {**AGENT_REFS, "tree": 5}):
        assert post_agent(agent_hub, agent_env("start", refs=refs)) == refused("bad_agent_body:refs"), refs


def test_ac19_only_a_start_carries_refs(agent_hub):
    for action in fleet.AGENT_ACTIONS:
        if action != "start":
            assert post_agent(agent_hub, agent_env(action, refs=dict(AGENT_REFS))) == refused("bad_agent_body:refs"), action


def test_ac19_an_unknown_bundle_is_refused(agent_hub):
    env = agent_env("start", refs={**AGENT_REFS, "bundle": "d" * 64})
    assert post_agent(agent_hub, env) == refused("missing_blob")


def test_ac19_message_kinds_are_closed(agent_hub):
    assert set(fleet.AGENT_MESSAGE_KINDS) == {"info", "query", "stop-after-row"}
    for kind in fleet.AGENT_MESSAGE_KINDS:
        assert post_agent(agent_hub, agent_env("message", message_kind=kind)) == REFUSED_NOTHING, kind
    for kind in ("ruling", "other", "", 5):
        assert post_agent(agent_hub, agent_env("message", message_kind=kind)) == refused("message_kind_refused"), kind


@pytest.mark.parametrize("text", ["", "   ", 5, None])
def test_ac19_a_message_needs_text(agent_hub, text):
    assert post_agent(agent_hub, agent_env("message", text=text)) == refused("bad_agent_body:text")


def blob_grants(h: Hub) -> list:
    with sqlite3.connect(h.db) as conn:
        return conn.execute("SELECT sha256, member FROM task_blobs").fetchall()


def test_ac19_only_an_accepted_start_grants_the_bundle(hub):
    seed_agent_hub(hub)
    assert post_agent(hub, agent_env("start", start_quote=None)) == refused("quote_required")
    assert post_agent(hub, agent_env("status")) == REFUSED_NOTHING
    assert blob_grants(hub) == []
    assert post_agent(hub, agent_env("start")) == REFUSED_NOTHING
    assert blob_grants(hub) == [(BUNDLE, "local")]


def test_ac20_the_refused_entries():
    assert set(fleet.AGENT_SHELLS) == {"cmd", "powershell", "pwsh", "sh", "bash", "claude", "codex", "cs" + "wap"}
    entries = ["Bash", "Bash(*)", "Bash(:*)", "Bash()", "Bash(*:*)", "Bash(codex exec:*)", "Bash(pwsh -File x:*)"]
    entries += [f"Bash({shell}:*)" for shell in fleet.AGENT_SHELLS]
    entries += [f"Bash({shell} -c x:*)" for shell in fleet.AGENT_SHELLS]
    entries += ["Bash(PWSH:*)", "bash(pwsh:*)", "Bash( pwsh:*)", "Bash(C:/tools/pwsh.exe:*)", "Bash(bin\\sh.exe x:*)"]
    entries += ["PowerShell", "PowerShell(Get-Item:*)", "mcp__codex__exec", "Bash(python codex.py:*)"]
    for entry in entries:
        assert fleet.agent_tool_refused(entry), entry


@pytest.mark.parametrize("entry", ["Read", "Edit", "Write", "WebSearch", "Bash(python -m pytest:*)", "Bash(git status:*)", "mcp__sequential_thinking__sequentialthinking"])
def test_ac20_the_accepted_entries(entry):
    assert not fleet.agent_tool_refused(entry)


def test_ac20_the_hub_refuses_a_refused_entry(agent_hub):
    for entry in ("Bash", "Bash(*)", "Bash(pwsh:*)", "Bash(codex exec:*)", "PowerShell"):
        env = agent_env("start", allowed_tools=["Read", entry])
        assert post_agent(agent_hub, env) == refused("bad_agent_body:allowed_tools"), entry
    assert post_agent(agent_hub, agent_env("start", allowed_tools=["Read", "Bash(python -m pytest:*)"])) == REFUSED_NOTHING


# AC-21, AC-24 to AC-26: a Claude job on a member. Chain: C-AGENT-HUB and C-AGENT-MEMBER, with a real hub and member on
# localhost and a pwsh shim on PATH that records each script and argv, and answers as its config says.


AGENT_PWSH_SHIM = '''import json, os, sys
from pathlib import Path
home = Path(os.environ["FLEET_HOME"])
at = sys.argv.index("-File")
script, args = Path(sys.argv[at + 1]).name, sys.argv[at + 2:]
with open(home / "shim-calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps({"script": script, "args": args}) + "\\n")
config = home / "shim-config.json"
step = (json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}).get(script, {})
if "view" in step:
    folder = home / "receipts" / "credits" / "runs" / args[0]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "view.json").write_text(json.dumps(step["view"]), encoding="utf-8-sig")
if "out" in step:
    print(step["out"])
sys.exit(step.get("exit", 0))
'''
STUB_RECEIPT_CHECK = '''import json, os, sys
from pathlib import Path
with open(Path(os.environ["FLEET_HOME"]) / "gate-calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(0)
'''
TOKEN_MARKER = "fake-token-" + "e5f6a7b8" * 4
CREDITS_SCRIPTS = (
    "Register-CreditsRun.ps1", "Start-CreditsRunTask.ps1", "Get-CreditsRun.ps1", "Send-CreditsRunMessage.ps1", "Stop-CreditsRun.ps1",
)
SKILL_DIR = "kit/.agent/skills/claude-credits"
AGENT_NAME = "Fleet Tester"
AGENT_EMAIL = "1+tester@users.noreply.github.com"
RESUME_WORDS = "Use the second option."
RUN = "run-1"
CAPS = ("--segment-cap-usd", "5", "--run-cap-usd", "20")
BRIEF_TEXT = "Write the answer into answer.txt."


def stopped_view(**over) -> dict:
    view = {
        "run_id": RUN, "state": "stopped", "class": "decision", "final_status": "STOPPED:decision",
        "segments": [{"dispatch_id": "d-1", "expected_session_id": "sess-1", "finalized_utc": "2026-11-05T00:00:00Z"}],
        "outbox": [{"event_seq": 2, "kind": "ack", "semantic_key": "ack:m-1", "created_utc": "2026-11-05T00:00:00Z", "text": "row 1 of 2"}],
    }
    view.update(over)
    return view


class AgentRig:
    """A real hub and member, with the member's kit, gate receipt, token and tools as files a test can take away."""

    def __init__(self, hub: Hub, base: Path, write_identity):
        self.hub, self.base = hub, base
        self.member = hub.pair("alpha")
        self.home = self.member.home
        self.bin = base / "agent-bin"
        self.bin.mkdir()
        (self.bin / "pwsh_shim.py").write_text(AGENT_PWSH_SHIM, encoding="utf-8")
        self.place_pwsh()
        self.place_claude()
        self.place_codex()
        self.place_kit()
        self.place_gate()
        self.place_token()
        (self.home / "gate-project").mkdir()
        write_identity(AGENT_NAME, AGENT_EMAIL)
        self.repo = base / "job-repo"
        self.repo.mkdir()
        run_git(self.repo, "init", "-q")
        (self.repo / "tracked.txt").write_text("one\n", encoding="utf-8")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "-c", "user.name=first", "-c", "user.email=first@example.invalid", "commit", "-q", "--no-verify", "--no-gpg-sign", "-m", "first")
        (self.repo / "tracked.txt").write_text("two\n", encoding="utf-8")
        self.brief = base / "brief.md"
        self.brief.write_text(BRIEF_TEXT, encoding="utf-8")
        self.config = {}

    def place_pwsh(self) -> None:
        (self.bin / "pwsh.cmd").write_text(f'@"{sys.executable}" "{self.bin / "pwsh_shim.py"}" %*\n', encoding="utf-8")

    def place_claude(self) -> None:
        (self.bin / "claude.cmd").write_text("@echo 1.0.0 (Claude Code)\n", encoding="utf-8")

    def place_codex(self) -> None:
        (self.bin / "codex.cmd").write_text("@echo codex-cli 9.9.9\n", encoding="utf-8")

    def place_kit(self) -> None:
        (self.home / "kit" / "fleet").mkdir(parents=True)
        (self.home / "kit" / "fleet" / "fleet-tasks.ps1").write_text("# shim target\n", encoding="utf-8")
        skill = self.home / SKILL_DIR
        (skill / "probes").mkdir(parents=True)
        for name in CREDITS_SCRIPTS:
            (skill / name).write_text("# shim target\n", encoding="utf-8")
        (skill / "probes" / "run_gate.py").write_text(STUB_RECEIPT_CHECK, encoding="utf-8")

    def place_gate(self) -> None:
        (self.home / "receipts" / "gate").mkdir(parents=True, exist_ok=True)
        (self.home / "receipts" / "gate" / "gate-result.json").write_text("{}", encoding="utf-8")

    def place_token(self) -> None:
        (self.home / "credentials").mkdir(exist_ok=True)
        (self.home / "credentials" / "claude-oauth-token").write_text(TOKEN_MARKER, encoding="utf-8")

    def path_env(self) -> dict:
        """PATH has git and the shims, and no real pwsh or claude."""
        system = Path(os.environ["SystemRoot"]) / "System32"
        return {"PATH": os.pathsep.join([str(self.bin), str(Path(shutil.which("git")).parent), str(system)])}

    def run_member(self, **env) -> None:
        self.member.start(env={**self.path_env(), **env})

    def answers(self, script: str, **step) -> None:
        self.config[script] = step
        # Replaced whole, and retried, because the shim may be reading the old file.
        scratch = self.home / "shim-config.next"
        scratch.write_text(json.dumps(self.config), encoding="utf-8")

        def swapped() -> bool:
            try:
                os.replace(scratch, self.home / "shim-config.json")
            except PermissionError:
                return False
            return True

        wait_until(swapped)

    def calls(self) -> list[dict]:
        path = self.home / "shim-calls.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def agent(self, action: str, *args: str, run: str = RUN, timeout: float = 120):
        return self.hub.cli("agent", action, "alpha", run, *args, timeout=timeout)

    def start(self, *extra: str, run: str = RUN, quote: str = WORDS):
        return self.agent("start", "--repo", str(self.repo), "--brief", str(self.brief), "--quote", quote, *CAPS, *extra, run=run)

    def resume(self, *extra: str, run: str = RUN, quote: str = RESUME_WORDS):
        return self.agent("resume", "--brief", str(self.brief), "--quote", quote, *extra, run=run)

    def folder(self, run: str = RUN) -> Path:
        return self.home / "agent" / run

    def slot(self, run: str = RUN) -> Path:
        return self.folder(run) / "slot"

    def manifest(self, run: str = RUN) -> dict:
        return json.loads((self.folder(run) / "manifest.json").read_text(encoding="utf-8"))

    def task_md(self, run: str = RUN) -> Path:
        return self.slot(run) / ".fleet-run" / "task.md"

    def briefs(self, run: str = RUN) -> Path:
        return self.home / "receipts" / "fleet-briefs" / run

    def final_md(self, dispatch: str, text: str) -> None:
        folder = self.home / "receipts" / "dispatch" / dispatch
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "final.md").write_text(text, encoding="utf-8")


@pytest.fixture
def agent_rig(tmp_path, global_identity):
    h = Hub(tmp_path)
    h.start()
    yield AgentRig(h, tmp_path, global_identity)
    h.close()


@pytest.fixture
def running_rig(agent_rig):
    """A member online, with one Claude job started through the shim."""
    agent_rig.run_member()
    r = agent_rig.start()
    assert r.returncode == 0, r.stdout + r.stderr
    (agent_rig.home / "shim-calls.jsonl").unlink()
    return agent_rig


def test_ac21_the_cli_prints_the_member_status_and_exits_zero(agent_rig):
    agent_rig.run_member()
    r = agent_rig.start()
    assert r.returncode == 0, r.stdout + r.stderr
    result = last_json(r)
    assert (result["state"], result["run"], result["cli"]) == ("completed", RUN, "claude")
    assert result["slot"] == agent_rig.slot().as_posix()
    assert re.fullmatch(r"[0-9a-f]{32}", result["task"])


def test_ac21_register_then_start_with_the_exact_quote(agent_rig):
    agent_rig.run_member()
    words = "Start the row 12 test job, it's Mat's call."
    assert agent_rig.start(quote=words).returncode == 0
    calls = agent_rig.calls()
    assert [c["script"] for c in calls] == ["Register-CreditsRun.ps1", "Start-CreditsRunTask.ps1"]
    manifest_path, receipt = agent_rig.folder() / "manifest.json", agent_rig.home / "receipts" / "gate" / "gate-result.json"
    assert calls[0]["args"] == ["-Manifest", str(manifest_path), "-Receipt", str(receipt)]
    assert calls[1]["args"] == [
        "-RunId", RUN, "-StartedBy", "agent-on-user-chat", "-StartQuote", words, "-AcceptTimeoutMs", "30000", "-OutcomeTimeoutMs", "30000",
    ]


def test_ac21_the_manifest_holds_the_fields_of_step_4(agent_rig):
    agent_rig.run_member()
    assert agent_rig.start("--allowed-tool", "Bash(python tests.py:*)", "--model", "fake-claude-model", "--effort", "high", "--timeout-sec", "600").returncode == 0
    doc, slot = agent_rig.manifest(), agent_rig.slot().as_posix()
    kit = (agent_rig.home / "kit").as_posix()
    assert doc["schema"] == "credits-run.v1"
    assert (doc["run_id"], doc["kind"], doc["lane"], doc["depends_on"], doc["plan_folder"]) == (RUN, "exec", "fleet", [], ".fleet-run")
    assert doc["project_root"] == slot
    assert doc["brief"] == (agent_rig.briefs() / "brief-1.md").as_posix()
    assert doc["messaging"] == {"orchestrator_sessions": [], "ruling_enabled": False, "gate_wait_max_min": 0}
    assert doc["budget"] == {"run_cap_usd": 20}
    launch = doc["launch"]
    assert launch["working_directory"] == slot
    assert (launch["permission_mode"], launch["auth"]) == ("acceptEdits", "subscription")
    assert launch["gate_project"] == (agent_rig.home / "gate-project").as_posix()
    assert (launch["segment_cap_usd"], launch["timeout_sec"], launch["model"], launch["effort"]) == (5, 600, "fake-claude-model", "high")
    assert launch["claude_exe"].lower() == (agent_rig.bin / "claude.cmd").as_posix().lower()
    assert launch["python_exe"] == Path(sys.executable).as_posix()
    assert launch["allowed_tools"] == ["Write", "Edit", f"Bash(python {kit}/tools/credits_msg.py:*)", "Bash(python tests.py:*)"]


def test_ac21_a_start_with_no_options_has_defaults_the_schema_requires(agent_rig):
    agent_rig.run_member()
    assert agent_rig.start().returncode == 0
    launch = agent_rig.manifest()["launch"]
    assert (launch["effort"], launch["timeout_sec"]) == ("medium", fleet.DEFAULT_RUN_TIMEOUT_S)
    assert "model" not in launch
    assert "allow_codex" not in launch


def test_ac21_the_brief_has_the_header_then_the_orchestrators_text(agent_rig):
    agent_rig.run_member()
    assert agent_rig.start().returncode == 0
    text = (agent_rig.briefs() / "brief-1.md").read_text(encoding="utf-8")
    kit = (agent_rig.home / "kit").as_posix()
    assert f'python {kit}/tools/credits_msg.py authority --quote "{WORDS}"' in text
    assert f'python {kit}/tools/credits_msg.py ack <msg_id> "<reply>"' in text
    assert "[ORCHESTRATOR-MESSAGE" in text
    assert 'stop_gate: "released:human-gate"' in text
    assert "Status: STOPPED:decision" in text
    assert "Status: DONE" in text
    assert "uncommitted" in text
    assert text.index("authority --quote") < text.index(BRIEF_TEXT)
    assert text.rstrip().endswith(BRIEF_TEXT)
    assert "\\" not in text


def test_ac21_the_slot_holds_the_snapshot_and_no_remote(agent_rig):
    agent_rig.run_member()
    assert agent_rig.start().returncode == 0
    slot = agent_rig.slot()
    # The rig edits the file within a second of its commit, keeping its size, which a copied index with a new time misses.
    assert (slot / "tracked.txt").read_text(encoding="utf-8").replace("\r\n", "\n") == "two\n"
    assert run_git(slot, "remote") == ""
    assert ".fleet-run/" in (slot / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    assert run_git(slot, "status", "--porcelain") == ""
    assert (agent_rig.folder() / "base").read_text(encoding="utf-8").strip() == run_git(slot, "rev-parse", "HEAD")
    text = agent_rig.task_md().read_text(encoding="utf-8")
    assert 'stop_gate: "armed"' in text
    assert len(re.findall(r"(?m)^\|.*\[ \].*\|\s*$", text)) == 1
    assert not (agent_rig.home / "agent" / f"{RUN}.tmp").exists()


def test_ac21_the_prerequisites_refuse_in_their_listed_order(agent_rig):
    """Everything is taken away, then put back one at a time: each step shows the next reason, with the shim never called."""
    agent_rig.run_member()
    (agent_rig.bin / "pwsh.cmd").unlink()
    (agent_rig.bin / "claude.cmd").unlink()
    shutil.rmtree(agent_rig.home / "kit")
    shutil.rmtree(agent_rig.home / "receipts")
    shutil.rmtree(agent_rig.home / "credentials")
    walk = [
        ("tool_missing:pwsh", agent_rig.place_pwsh),
        ("kit_missing", agent_rig.place_kit),
        ("gate_missing", agent_rig.place_gate),
        ("token_missing", agent_rig.place_token),
        ("tool_missing:claude", agent_rig.place_claude),
    ]
    for reason, put_back in walk:
        r = agent_rig.start()
        assert (r.returncode, last_json(r)["reason"]) == (3, reason), r.stdout + r.stderr
        assert last_json(r)["state"] == "rejected"
        assert not agent_rig.folder().exists()
        put_back()
    assert agent_rig.calls() == []
    assert agent_rig.start().returncode == 0


def test_ac21_a_second_start_is_refused(agent_rig):
    agent_rig.run_member()
    assert agent_rig.start().returncode == 0
    before = len(agent_rig.calls())
    r = agent_rig.start()
    assert (r.returncode, last_json(r)["reason"]) == (3, "run_exists")
    assert len(agent_rig.calls()) == before


@pytest.mark.parametrize("script,exit_code,reason,count", [
    ("Register-CreditsRun.ps1", 3, "credits_refused:register:3", 1),
    ("Start-CreditsRunTask.ps1", 3, "credits_refused:start:3", 2),
    ("Start-CreditsRunTask.ps1", 1, "credits_refused:start:1", 2),
])
def test_ac21_a_refused_step_is_named_and_stops_the_rest(agent_rig, script, exit_code, reason, count):
    agent_rig.answers(script, exit=exit_code)
    agent_rig.run_member()
    r = agent_rig.start()
    assert (r.returncode, last_json(r)["reason"]) == (3, reason)
    assert len(agent_rig.calls()) == count


def test_ac21_an_accepted_pending_start_completes(agent_rig):
    agent_rig.answers("Start-CreditsRunTask.ps1", exit=4)
    agent_rig.run_member()
    r = agent_rig.start()
    assert (r.returncode, last_json(r)["state"]) == (0, "completed")


def test_ac21_no_quote_is_refused_before_any_upload(agent_rig):
    agent_rig.run_member()
    r = agent_rig.hub.cli("agent", "start", "alpha", RUN, "--repo", str(agent_rig.repo), "--brief", str(agent_rig.brief), *CAPS)
    assert r.returncode == 2
    assert "quote_required" in r.stderr
    assert agent_rig.calls() == []
    assert list((agent_rig.hub.hub_dir / "blobs").iterdir()) == []


def test_ac21_the_token_reaches_no_hub_row_or_task_output(agent_rig):
    agent_rig.run_member()
    r = agent_rig.start()
    assert r.returncode == 0
    assert TOKEN_MARKER not in r.stdout + r.stderr
    agent_rig.hub.stop()
    assert files_holding(agent_rig.hub.hub_dir, TOKEN_MARKER) == []
    assert files_holding(agent_rig.folder(), TOKEN_MARKER) == []
    assert files_holding(agent_rig.briefs(), TOKEN_MARKER) == []


def test_ac21_a_file_error_fails_the_task_and_the_member_lives(agent_rig):
    agent_rig.run_member()
    (agent_rig.home / "agent").write_text("in the way", encoding="utf-8")
    r = agent_rig.start()
    assert (r.returncode, last_json(r)["reason"]) == (1, "os_error")
    assert agent_rig.member.proc.poll() is None


# AC-24: status, message and stop.


def test_ac24_status_gives_the_normalized_view(running_rig):
    running_rig.answers("Get-CreditsRun.ps1", view=stopped_view())
    running_rig.final_md("d-1", "Which option?\nStatus: STOPPED:decision\n")
    r = running_rig.agent("status")
    assert r.returncode == 0, r.stdout + r.stderr
    result = last_json(r)
    assert (result["state"], result["run"], result["cli"]) == ("completed", RUN, "claude")
    assert (result["run_state"], result["stop_class"], result["final_status"], result["verified"]) == ("stopped", "decision", "STOPPED:decision", False)
    assert result["final_text"].startswith("Which option?")
    assert result["session_id"] == "sess-1"
    assert result["outbox"][0]["text"] == "row 1 of 2"
    assert running_rig.calls() == [{"script": "Get-CreditsRun.ps1", "args": [RUN, "-Export"]}]


def test_ac24_message_sends_the_kind_and_text(running_rig):
    running_rig.answers("Send-CreditsRunMessage.ps1", out=json.dumps({"result": "changed", "msg_id": "m-7"}))
    r = running_rig.agent("message", "--kind", "query", "--text", "Where are you?")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (last_json(r)["state"], last_json(r)["msg_id"]) == ("completed", "m-7")
    assert running_rig.calls() == [{"script": "Send-CreditsRunMessage.ps1", "args": ["-RunId", RUN, "-Kind", "query", "-Body", "Where are you?"]}]


def test_ac24_stop_stops_the_named_run(running_rig):
    running_rig.answers("Stop-CreditsRun.ps1", out=json.dumps({"result": "changed", "run_id": RUN, "state": "cancelled"}))
    r = running_rig.agent("stop")
    assert (r.returncode, last_json(r)["stop_result"]) == (0, "changed")
    assert running_rig.calls() == [{"script": "Stop-CreditsRun.ps1", "args": ["-RunId", RUN]}]


AGENT_LATER_ACTIONS = [
    pytest.param("Get-CreditsRun.ps1", "status", (), id="status"),
    pytest.param("Send-CreditsRunMessage.ps1", "message", ("--kind", "info", "--text", "note"), id="message"),
    pytest.param("Stop-CreditsRun.ps1", "stop", (), id="stop"),
]


@pytest.mark.parametrize("script,action,args", AGENT_LATER_ACTIONS)
def test_ac24_shim_exit_3_means_run_unknown(running_rig, script, action, args):
    running_rig.answers(script, exit=3)
    r = running_rig.agent(action, *args)
    assert (r.returncode, last_json(r)["reason"]) == (3, "run_unknown")


@pytest.mark.parametrize("script,action,args", AGENT_LATER_ACTIONS)
def test_ac24_no_run_folder_means_run_unknown_and_no_shim_call(running_rig, script, action, args):
    r = running_rig.agent(action, *args, run="other-run")
    assert (r.returncode, last_json(r)["reason"]) == (3, "run_unknown")
    assert running_rig.calls() == []


def test_ac24_a_named_message_refusal_is_not_called_unknown(running_rig):
    running_rig.answers("Send-CreditsRunMessage.ps1", exit=3, out=json.dumps({"result": "refused", "error": "body_too_long"}))
    r = running_rig.agent("message", "--kind", "info", "--text", "note")
    assert (r.returncode, last_json(r)["reason"]) == (3, "credits_refused:message:3")


def test_ac24_a_store_refusing_the_run_by_name_is_unknown(running_rig):
    running_rig.answers("Send-CreditsRunMessage.ps1", exit=3, out=json.dumps({"result": "refused", "error": "unknown_run"}))
    r = running_rig.agent("message", "--kind", "info", "--text", "note")
    assert last_json(r)["reason"] == "run_unknown"


def test_ac24_other_exits_name_the_step(running_rig):
    running_rig.answers("Get-CreditsRun.ps1", exit=9)
    r = running_rig.agent("status")
    assert (r.returncode, last_json(r)["reason"]) == (3, "credits_refused:status:9")


def test_ac24_a_view_that_can_not_be_read_rejects_and_the_member_lives(running_rig):
    running_rig.answers("Get-CreditsRun.ps1")
    folder = running_rig.home / "receipts" / "credits" / "runs" / RUN
    folder.mkdir(parents=True)
    (folder / "view.json").write_text("{not json", encoding="utf-8")
    r = running_rig.agent("status")
    assert (r.returncode, last_json(r)["reason"]) == (3, "credits_refused:status:view")
    assert running_rig.member.proc.poll() is None


# AC-25: resume.


def released(rig: AgentRig) -> None:
    rig.task_md().write_text(fleet.member_task_md("released:human-gate"), encoding="utf-8")


def test_ac25_resume_writes_the_next_brief_and_rearms_the_gate(running_rig):
    released(running_rig)
    (running_rig.slot() / "kept.txt").write_text("the job's work", encoding="utf-8")
    base = (running_rig.folder() / "base").read_bytes()
    head = run_git(running_rig.slot(), "rev-parse", "HEAD")
    r = running_rig.resume()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (last_json(r)["state"], last_json(r)["slot"]) == ("completed", running_rig.slot().as_posix())
    second = running_rig.briefs() / "brief-2.md"
    text = second.read_text(encoding="utf-8")
    assert f'authority --quote "{RESUME_WORDS}"' in text
    assert text.rstrip().endswith(BRIEF_TEXT)
    assert 'stop_gate: "armed"' in running_rig.task_md().read_text(encoding="utf-8")
    assert running_rig.calls() == [{"script": "Start-CreditsRunTask.ps1", "args": [
        "-RunId", RUN, "-Resume", "-Brief", str(second), "-ResumeMode", "session",
        "-StartedBy", "agent-on-user-chat", "-StartQuote", RESUME_WORDS,
        "-AcceptTimeoutMs", "30000", "-OutcomeTimeoutMs", "30000",
    ]}]
    assert (running_rig.slot() / "kept.txt").read_text(encoding="utf-8") == "the job's work"
    assert run_git(running_rig.slot(), "rev-parse", "HEAD") == head
    assert (running_rig.folder() / "base").read_bytes() == base


def test_ac25_resume_checks_the_retained_receipt_of_the_run(running_rig):
    assert running_rig.resume().returncode == 0
    argv = [json.loads(line) for line in (running_rig.home / "gate-calls.jsonl").read_text(encoding="utf-8").splitlines()]
    launch = running_rig.manifest()["launch"]
    retained = running_rig.home / "receipts" / "credits" / "receipts" / f"{RUN}.gate-result.json"
    assert argv == [[
        "--check-receipt", str(retained), "--project", running_rig.slot().as_posix(), "--python", launch["python_exe"],
        "--claude", launch["claude_exe"], "--gate-project", launch["gate_project"],
    ]]


def test_ac25_each_resume_takes_the_next_number(running_rig):
    assert running_rig.resume().returncode == 0
    assert running_rig.resume().returncode == 0
    assert sorted(p.name for p in running_rig.briefs().iterdir()) == ["brief-1.md", "brief-2.md", "brief-3.md"]


def test_ac25_a_refused_start_is_named(running_rig):
    running_rig.answers("Start-CreditsRunTask.ps1", exit=3)
    r = running_rig.resume()
    assert (r.returncode, last_json(r)["reason"]) == (3, "credits_refused:start:3")


def test_ac25_an_unknown_run_is_refused(running_rig):
    r = running_rig.resume(run="other-run")
    assert (r.returncode, last_json(r)["reason"]) == (3, "run_unknown")
    assert running_rig.calls() == []


def test_ac25_resume_needs_mats_words(running_rig):
    r = running_rig.hub.cli("agent", "resume", "alpha", RUN, "--brief", str(running_rig.brief))
    assert r.returncode == 2
    assert "quote_required" in r.stderr
    assert running_rig.calls() == []


def real_receipt(rig: AgentRig, monkeypatch, kit_revision: str | None = None) -> None:
    """The retained receipt a real check accepts, or with the given older kit revision."""
    probes = rig.home / SKILL_DIR / "probes"
    # The probes set sys.dont_write_bytecode on import; restore it so later tests are unaffected.
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    monkeypatch.syspath_prepend(str(probes))
    kit = importlib.import_module("kit")
    gate = importlib.import_module("run_gate")
    del sys.modules["kit"], sys.modules["run_gate"]
    project = rig.home / "gate-project"
    python = kit.resolve_python(sys.executable)
    receipt = rig.home / "receipts" / "credits" / "receipts" / f"{RUN}.gate-result.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        "qualifying": True, "mode": "live", "cli_version": "1.0.0",
        "cases": {cid: {"passed": True} for cid in gate.DEFAULT_CASES},
        "identity": {
            "project": project.as_posix(), "kit_dir": kit.KIT_DIR.as_posix(),
            "kit_revision": kit_revision or kit.kit_revision(), "python": python,
            "settings_sha256": {"settings.json": "fixture"}, "launch_profile": kit.launch_profile(project, python),
        },
    }), encoding="utf-8")


def test_ac25_a_receipt_from_an_older_kit_is_stale_through_the_real_check(agent_rig, monkeypatch):
    probes = agent_rig.home / SKILL_DIR / "probes"
    shutil.rmtree(probes)
    shutil.copytree(REPO / "core" / ".agent" / "skills" / "claude-credits" / "probes", probes, ignore=shutil.ignore_patterns("__pycache__"))
    config = agent_rig.base / "claude-config"
    config.mkdir()
    (config / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    agent_rig.run_member()
    assert agent_rig.start().returncode == 0

    # The control: the same check accepts the current revision, so only the revision makes the next one stale.
    real_receipt(agent_rig, monkeypatch)
    assert agent_rig.resume().returncode == 0, "a current receipt passes the real check"
    released(agent_rig)
    before_calls = len(agent_rig.calls())
    briefs_before = sorted(p.name for p in agent_rig.briefs().iterdir())

    real_receipt(agent_rig, monkeypatch, kit_revision="0" * 64)
    r = agent_rig.resume()
    assert (r.returncode, last_json(r)["reason"]) == (3, "receipt_stale")
    assert sorted(p.name for p in agent_rig.briefs().iterdir()) == briefs_before
    assert 'stop_gate: "released:human-gate"' in agent_rig.task_md().read_text(encoding="utf-8")
    assert len(agent_rig.calls()) == before_calls


def test_ac25_the_real_receipt_helper_leaves_the_bytecode_flag_as_it_was(agent_rig):
    probes = agent_rig.home / SKILL_DIR / "probes"
    shutil.rmtree(probes)
    shutil.copytree(REPO / "core" / ".agent" / "skills" / "claude-credits" / "probes", probes, ignore=shutil.ignore_patterns("__pycache__"))
    config = agent_rig.base / "claude-config"
    config.mkdir()
    before = sys.dont_write_bytecode
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("CLAUDE_CONFIG_DIR", str(config))
        real_receipt(agent_rig, mp)
    assert sys.dont_write_bytecode is before


def test_ac25_a_failed_check_is_stale(agent_rig):
    (agent_rig.home / SKILL_DIR / "probes" / "run_gate.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    agent_rig.run_member()
    assert agent_rig.start().returncode == 0
    r = agent_rig.resume()
    assert (r.returncode, last_json(r)["reason"]) == (3, "receipt_stale")


# AC-26: a secret in a job's output is withheld, and the member lives.


@pytest.mark.parametrize("where", ["final_text", "outbox"])
def test_ac26_output_holding_a_secret_is_withheld(running_rig, where):
    secret = FAKE_SECRETS[0] + "x" * 24
    if where == "final_text":
        running_rig.answers("Get-CreditsRun.ps1", view=stopped_view())
        running_rig.final_md("d-1", f"token {secret}\nStatus: DONE\n")
    else:
        view = stopped_view()
        view["outbox"][0]["text"] = f"token {secret}"
        running_rig.answers("Get-CreditsRun.ps1", view=view)
    r = running_rig.agent("status")
    assert r.returncode == 0, r.stdout + r.stderr
    result = last_json(r)
    assert (result["state"], result["reason"]) == ("completed", "output_withheld")
    assert "final_text" not in result and "outbox" not in result
    assert result["run_state"] == "stopped"
    assert secret.encode() not in running_rig.hub.db.read_bytes()
    assert running_rig.member.proc.poll() is None
    ping = last_json(running_rig.hub.cli("send", "alpha", "ping"))
    done = running_rig.hub.cli("wait", ping["task"], "--timeout", "30")
    assert (done.returncode, last_json(done)["state"]) == (0, "completed")


# AC-27: fleet watch wakes the orchestrator when a run stops being in progress.


def watch(rig: AgentRig, run: str = RUN, timeout: float = 120):
    return rig.hub.cli("watch", "alpha", run, "--poll", "0.1", timeout=timeout)


def test_ac27_a_done_run_exits_0(running_rig):
    running_rig.answers("Get-CreditsRun.ps1", view=stopped_view(state="done", **{"class": "done"}, final_status="DONE"))
    r = watch(running_rig)
    assert r.returncode == 0, r.stdout + r.stderr
    result = last_json(r)
    assert (result["state"], result["run"], result["run_state"], result["verified"]) == ("completed", RUN, "done", True)


def test_ac27_a_stopped_run_exits_7_with_its_class(running_rig):
    running_rig.answers("Get-CreditsRun.ps1", view=stopped_view())
    r = watch(running_rig)
    assert r.returncode == 7, r.stdout + r.stderr
    assert (last_json(r)["run_state"], last_json(r)["stop_class"]) == ("stopped", "decision")
    assert len(r.stdout.strip().splitlines()) == 1


def test_ac27_an_unknown_state_exits_1(running_rig):
    running_rig.answers("Get-CreditsRun.ps1", view=stopped_view(state="made_up_state"))
    r = watch(running_rig)
    assert (r.returncode, last_json(r)["run_state"]) == (1, "unknown")


def test_ac27_a_rejected_status_exits_3(running_rig):
    r = watch(running_rig, run="other-run")
    assert (r.returncode, last_json(r)["reason"]) == (3, "run_unknown")


def test_ac27_a_member_offline_exits_5(agent_rig):
    r = watch(agent_rig)
    assert r.returncode == 5, r.stdout + r.stderr
    assert last_json(r)["state"] == "submitted"


def test_ac27_a_member_lost_while_watching_exits_5(tmp_path, global_identity):
    hub = Hub(tmp_path, offline_after=1)
    hub.start()
    try:
        rig = AgentRig(hub, tmp_path, global_identity)
        rig.run_member()
        assert rig.start().returncode == 0
        rig.answers("Get-CreditsRun.ps1", view=stopped_view(state="running"))
        proc = subprocess.Popen(
            [sys.executable, str(FLEET_PY), "watch", "alpha", RUN, "--poll", "0.1"],
            env={**os.environ, "FLEET_HOME": str(hub.home)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        )
        wait_until(lambda: sum(c["script"] == "Get-CreditsRun.ps1" for c in rig.calls()) >= 2, timeout=60)
        rig.member.stop()
        assert proc.wait(60) == 5
    finally:
        if proc.poll() is None:
            proc.kill()
        hub.close()


def test_ac27_it_does_not_exit_while_the_run_is_running(running_rig):
    running_rig.answers("Get-CreditsRun.ps1", view=stopped_view(state="running"))
    proc = subprocess.Popen(
        [sys.executable, str(FLEET_PY), "watch", "alpha", RUN, "--poll", "0.1"],
        env={**os.environ, "FLEET_HOME": str(running_rig.hub.home)},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", stdin=subprocess.DEVNULL,
    )
    try:
        wait_until(lambda: sum(c["script"] == "Get-CreditsRun.ps1" for c in running_rig.calls()) >= 3, timeout=60)
        assert proc.poll() is None
        running_rig.answers("Get-CreditsRun.ps1", view=stopped_view())
        out, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 7, err
    assert len(out.strip().splitlines()) == 1
    assert json.loads(out)["stop_class"] == "decision"


def test_ac27_a_watch_keeps_the_plans_poll():
    args = fleet.build_parser().parse_args(["watch", "alpha", RUN])
    assert (fleet.WATCH_POLL_S, args.poll) == (60, 60)
    assert args.fn is fleet.cmd_watch


# AC-29, AC-30, AC-32: a Codex job on a member, through the same hub, member and shim.


TASKS_SCRIPT = "fleet-tasks.ps1"
CODEX_PREREQUISITES = {
    "tool_missing:pwsh": lambda rig: (rig.bin / "pwsh.cmd").unlink(),
    "tool_missing:codex": lambda rig: (rig.bin / "codex.cmd").unlink(),
    "kit_missing": lambda rig: (rig.home / "kit" / "fleet" / TASKS_SCRIPT).unlink(),
}


def start_codex(rig: AgentRig, *extra: str, run: str = RUN, quote: str = WORDS):
    return rig.agent("start", "--cli", "codex", "--repo", str(rig.repo), "--brief", str(rig.brief), "--quote", quote, *extra, run=run)


def codex_state(rig: AgentRig, running: bool = False, line: str | None = None, **over) -> None:
    rig.answers(TASKS_SCRIPT, out=json.dumps({"running": running, "status_line": line, **over}))


def task_calls(rig: AgentRig) -> list[list[str]]:
    return [c["args"] for c in rig.calls() if c["script"] == TASKS_SCRIPT]


def arg_after(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


@pytest.fixture
def codex_rig(agent_rig):
    """A member online, with one Codex job started through the shim."""
    agent_rig.run_member()
    r = start_codex(agent_rig)
    assert r.returncode == 0, r.stdout + r.stderr
    (agent_rig.home / "shim-calls.jsonl").unlink()
    return agent_rig


def test_ac29_a_start_goes_to_the_task_script_with_the_slot_and_the_first_brief(agent_rig):
    agent_rig.run_member()
    r = start_codex(agent_rig)
    assert r.returncode == 0, r.stdout + r.stderr
    result = last_json(r)
    assert (result["state"], result["run"], result["cli"]) == ("completed", RUN, "codex")
    assert result["slot"] == agent_rig.slot().as_posix()
    calls = agent_rig.calls()
    assert [c["script"] for c in calls] == [TASKS_SCRIPT]
    args = calls[0]["args"]
    assert (arg_after(args, "-Action"), arg_after(args, "-Run"), arg_after(args, "-DispatchId")) == ("CodexStart", RUN, f"{RUN}-1")
    assert Path(arg_after(args, "-Brief")) == agent_rig.briefs() / "brief-1.md"
    assert Path(arg_after(args, "-Slot")) == agent_rig.slot()
    assert "-ResumeDispatchId" not in args


def test_ac29_the_manifest_names_the_cli_and_keeps_the_options(agent_rig):
    agent_rig.run_member()
    assert start_codex(agent_rig, "--model", "gpt-test", "--effort", "high", "--timeout-sec", "600").returncode == 0
    doc = agent_rig.manifest()
    assert doc["cli"] == "codex"
    assert (doc["model"], doc["effort"], doc["timeout_sec"]) == ("gpt-test", "high", 600)
    assert "launch" not in doc


def test_ac29_the_slot_holds_the_snapshot_and_nothing_for_claude(agent_rig):
    agent_rig.run_member()
    assert start_codex(agent_rig).returncode == 0
    assert (agent_rig.slot() / "tracked.txt").read_text(encoding="utf-8") == "two\n"
    assert not (agent_rig.slot() / ".fleet-run").exists()
    assert len((agent_rig.folder() / "base").read_text(encoding="utf-8")) == 40
    assert not agent_rig.folder().with_name(f"{RUN}.tmp").exists()


def test_ac29_the_brief_has_the_header_without_the_claude_parts(agent_rig):
    agent_rig.run_member()
    assert start_codex(agent_rig, quote="Start the Codex job.").returncode == 0
    text = (agent_rig.briefs() / "brief-1.md").read_text(encoding="utf-8")
    assert 'Mat\'s words for this segment: "Start the Codex job."' in text
    assert BRIEF_TEXT in text
    assert "`Status: DONE`" in text and "`Status: STOPPED:decision`" in text
    assert "Leave your changes uncommitted." in text
    assert ".fleet-run" not in text and "credits_msg" not in text


def test_ac29_the_brief_keeps_a_full_access_job_to_its_folder_and_temp(agent_rig):
    agent_rig.run_member()
    assert start_codex(agent_rig).returncode == 0
    text = (agent_rig.briefs() / "brief-1.md").read_text(encoding="utf-8")
    assert fleet.CODEX_WRITE_SCOPE in text
    assert "Write only inside the current working folder and the system temp folder" in fleet.CODEX_WRITE_SCOPE
    assert text.index(fleet.CODEX_WRITE_SCOPE) < text.index(BRIEF_TEXT)


def test_ac29_a_codex_start_needs_no_gate_token_or_claude(agent_rig):
    (agent_rig.home / "receipts" / "gate" / "gate-result.json").unlink()
    (agent_rig.home / "credentials" / "claude-oauth-token").unlink()
    (agent_rig.bin / "claude.cmd").unlink()
    agent_rig.run_member()
    assert start_codex(agent_rig).returncode == 0


@pytest.mark.parametrize("reason", sorted(CODEX_PREREQUISITES))
def test_ac29_a_missing_prerequisite_is_named_and_nothing_runs(agent_rig, reason):
    CODEX_PREREQUISITES[reason](agent_rig)
    agent_rig.run_member()
    r = start_codex(agent_rig)
    assert r.returncode == 3, r.stdout + r.stderr
    assert last_json(r)["reason"] == reason
    assert agent_rig.calls() == []
    assert not agent_rig.folder().exists()


def test_ac29_a_second_start_is_run_exists(codex_rig):
    r = start_codex(codex_rig)
    assert (r.returncode, last_json(r)["reason"]) == (3, "run_exists")
    assert task_calls(codex_rig) == []


def test_ac29_a_task_script_failure_is_refused_with_its_exit(agent_rig):
    agent_rig.answers(TASKS_SCRIPT, exit=9)
    agent_rig.run_member()
    r = start_codex(agent_rig)
    assert (r.returncode, last_json(r)["reason"]) == (3, "credits_refused:CodexStart:9")


def test_ac29_message_is_refused_because_the_inbox_hook_is_claude_only(codex_rig):
    r = codex_rig.agent("message", "--kind", "query", "--text", "are you there?")
    assert (r.returncode, last_json(r)["reason"]) == (3, "codex_no_messages")
    assert codex_rig.calls() == []


def test_ac29_a_claude_run_still_takes_messages(running_rig):
    r = running_rig.agent("message", "--kind", "query", "--text", "are you there?")
    assert r.returncode == 0, r.stdout + r.stderr
    assert running_rig.calls()[0]["script"] == "Send-CreditsRunMessage.ps1"


def test_ac29_a_resume_names_the_prior_dispatch_and_writes_the_next_brief(codex_rig):
    codex_state(codex_rig, line="STOPPED:decision")
    r = codex_rig.resume()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (last_json(r)["cli"], last_json(r)["slot"]) == ("codex", codex_rig.slot().as_posix())
    assert [arg_after(a, "-Action") for a in task_calls(codex_rig)] == ["CodexState", "CodexStart"]
    args = task_calls(codex_rig)[1]
    assert arg_after(args, "-DispatchId") == f"{RUN}-2"
    assert arg_after(args, "-ResumeDispatchId") == f"{RUN}-1"
    assert Path(arg_after(args, "-Slot")) == codex_rig.slot()
    assert Path(arg_after(args, "-Brief")) == codex_rig.briefs() / "brief-2.md"
    text = (codex_rig.briefs() / "brief-2.md").read_text(encoding="utf-8")
    assert RESUME_WORDS in text and "credits_msg" not in text


def test_ac29_a_second_resume_names_the_one_before_it(codex_rig):
    codex_state(codex_rig, line="STOPPED:decision")
    assert codex_rig.resume().returncode == 0
    assert codex_rig.resume().returncode == 0
    args = task_calls(codex_rig)[-1]
    assert (arg_after(args, "-DispatchId"), arg_after(args, "-ResumeDispatchId")) == (f"{RUN}-3", f"{RUN}-2")


def test_ac29_a_resume_of_a_running_job_is_run_active_and_writes_nothing(codex_rig):
    codex_state(codex_rig, running=True)
    r = codex_rig.resume()
    assert (r.returncode, last_json(r)["reason"]) == (3, "run_active")
    assert [arg_after(a, "-Action") for a in task_calls(codex_rig)] == ["CodexState"]
    assert not (codex_rig.briefs() / "brief-2.md").exists()


def test_ac29_a_resume_needs_the_words(codex_rig):
    r = codex_rig.agent("resume", "--brief", str(codex_rig.brief))
    assert r.returncode == 2, r.stdout + r.stderr
    assert codex_rig.calls() == []


def test_ac29_stop_stops_the_task(codex_rig):
    r = codex_rig.agent("stop")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [arg_after(a, "-Action") for a in task_calls(codex_rig)] == ["CodexStop"]


def test_ac29_status_asks_about_the_latest_dispatch(codex_rig):
    codex_state(codex_rig, line="STOPPED:decision")
    codex_rig.resume()
    codex_rig.agent("status")
    args = task_calls(codex_rig)[-1]
    assert (arg_after(args, "-Action"), arg_after(args, "-DispatchId")) == ("CodexState", f"{RUN}-2")


def test_ac29_status_of_a_running_job(codex_rig):
    codex_state(codex_rig, running=True)
    result = last_json(codex_rig.agent("status"))
    assert (result["state"], result["cli"], result["run_state"], result["verified"]) == ("completed", "codex", "running", False)
    assert result["outbox"] == []


def test_ac29_status_of_a_finished_job_returns_its_final_message(codex_rig):
    codex_state(codex_rig, line="DONE")
    codex_rig.final_md(f"{RUN}-1", "Wrote it.\nStatus: DONE\n")
    result = last_json(codex_rig.agent("status"))
    assert (result["run_state"], result["final_status"], result["verified"]) == ("done", "DONE", False)
    assert result["final_text"].splitlines() == ["Wrote it.", "Status: DONE"]


def test_ac29_status_returns_the_session_the_wrapper_recorded(codex_rig):
    codex_state(codex_rig, line="DONE")
    codex_rig.final_md(f"{RUN}-1", "Status: DONE\n")
    status = codex_rig.home / "receipts" / "dispatch" / f"{RUN}-1" / "status.json"
    status.write_text(json.dumps({"session_id": "sess-9"}), encoding="utf-8")
    assert last_json(codex_rig.agent("status"))["session_id"] == "sess-9"


def test_ac29_a_busy_exit_is_reported_as_codex_job_busy(codex_rig):
    codex_state(codex_rig, task_result=fleet.CODEX_BUSY_EXIT)
    r = codex_rig.agent("status")
    assert (r.returncode, last_json(r)["reason"]) == (3, "codex_job_busy")
    assert fleet.CODEX_BUSY_EXIT == 11


def test_ac29_a_clean_exit_with_no_status_line_is_not_done(codex_rig):
    codex_state(codex_rig, task_result=0)
    codex_rig.final_md(f"{RUN}-1", "I think that went well.\n")
    result = last_json(codex_rig.agent("status"))
    assert (result["run_state"], result["stop_class"]) == ("stopped", "no_status_line")


def test_ac29_status_of_an_unknown_run_is_run_unknown(codex_rig):
    r = codex_rig.agent("status", run="other-run")
    assert (r.returncode, last_json(r)["reason"]) == (3, "run_unknown")


def test_ac29_a_secret_in_a_codex_job_is_withheld(codex_rig):
    secret = FAKE_SECRETS[0] + "x" * 24
    codex_state(codex_rig, line="DONE")
    codex_rig.final_md(f"{RUN}-1", f"token {secret}\nStatus: DONE\n")
    result = last_json(codex_rig.agent("status"))
    assert (result["state"], result["reason"], result["run_state"]) == ("completed", "output_withheld", "done")
    assert "final_text" not in result
    assert secret.encode() not in codex_rig.hub.db.read_bytes()


@pytest.mark.parametrize("line, code", [("DONE", 0), ("STOPPED:decision", 7), (None, 7)])
def test_ac29_watch_wakes_on_a_codex_job(codex_rig, line, code):
    codex_state(codex_rig, line=line)
    assert watch(codex_rig).returncode == code


CODEX_STOPPED = {"run_state": "stopped", "stop_class": "no_status_line", "final_status": None, "verified": False}


@pytest.mark.parametrize("state, expected", [
    ({"running": True, "status_line": None}, {"run_state": "running", "stop_class": None, "final_status": None, "verified": False}),
    ({"running": True, "status_line": "DONE"}, {"run_state": "running", "stop_class": None, "final_status": None, "verified": False}),
    ({"running": False, "status_line": "DONE"}, {"run_state": "done", "stop_class": None, "final_status": "DONE", "verified": False}),
    ({"running": False, "status_line": "STOPPED:decision"}, {"run_state": "stopped", "stop_class": "decision", "final_status": "STOPPED:decision", "verified": False}),
    ({"running": False, "status_line": "STOPPED:human_stop"}, {"run_state": "stopped", "stop_class": "human_stop", "final_status": "STOPPED:human_stop", "verified": False}),
])
def test_ac30_a_well_formed_state(state, expected):
    assert fleet.normalize_codex(state) == expected


@pytest.mark.parametrize("state", [
    {"running": False, "status_line": None},
    {"running": False, "status_line": None, "task_result": 0},
    {"running": False},
    {},
    {"running": "yes", "status_line": None},
    {"running": 1, "status_line": None},
    {"running": False, "status_line": ""},
    {"running": False, "status_line": "done"},
    {"running": False, "status_line": "Done"},
    {"running": False, "status_line": " DONE"},
    {"running": False, "status_line": "DONE "},
    {"running": False, "status_line": "DONE\n"},
    {"running": False, "status_line": "DONE!"},
    {"running": False, "status_line": "STOPPED:"},
    {"running": False, "status_line": "STOPPED"},
    {"running": False, "status_line": "STOPPED: decision"},
    {"running": False, "status_line": "STOPPED:Decision"},
    {"running": False, "status_line": "STOPPED:two words"},
    {"running": False, "status_line": "STOPPED:1st"},
    {"running": False, "status_line": "STOPPED:decision\nDONE"},
    {"running": False, "status_line": "STOPPED:" + "a" * 65},
    {"running": False, "status_line": 7},
    {"running": False, "status_line": ["DONE"]},
])
def test_ac30_anything_else_is_stopped_with_no_status_line(state):
    assert fleet.normalize_codex(state) == CODEX_STOPPED


def codex_rules(rig: AgentRig) -> list[str]:
    return [t for t in rig.manifest()["launch"]["allowed_tools"] if "codex" in t.lower()]


def test_ac32_without_the_flag_no_rule_mentions_codex(agent_rig):
    agent_rig.run_member()
    assert agent_rig.start().returncode == 0
    assert codex_rules(agent_rig) == []


def test_ac32_with_the_flag_exactly_the_two_rules(agent_rig):
    agent_rig.run_member()
    assert agent_rig.start("--allow-codex").returncode == 0
    wrapper = f"{(agent_rig.home / 'kit').as_posix()}/tools/Invoke-CodexDispatch.ps1"
    assert codex_rules(agent_rig) == [
        f"Bash(pwsh -NoProfile -File {wrapper} -Mode ReviewReadOnly:*)",
        f"Bash(pwsh -NoProfile -File {wrapper} -Mode ReviewWorkspace:*)",
    ]


def test_ac32_neither_rule_names_full_access_and_each_fits_the_credits_schema(agent_rig):
    agent_rig.run_member()
    assert agent_rig.start("--allow-codex").returncode == 0
    allowed = agent_rig.manifest()["launch"]["allowed_tools"]
    assert not any("FullAccess" in t for t in allowed)
    schema = json.loads((REPO / "core/.agent/skills/claude-credits/schemas/credits-run.v1.json").read_text(encoding="utf-8"))
    pattern = schema["properties"]["launch"]["properties"]["allowed_tools"]["items"]["pattern"]
    assert all(re.search(pattern, t) and "," not in t for t in allowed)


def test_ac32_the_flag_keeps_the_jobs_other_rules(agent_rig):
    agent_rig.run_member()
    assert agent_rig.start("--allow-codex", "--allowed-tool", "Bash(python step.py)").returncode == 0
    allowed = agent_rig.manifest()["launch"]["allowed_tools"]
    assert "Bash(python step.py)" in allowed and "Write" in allowed and len(codex_rules(agent_rig)) == 2


def test_ac32_forbidden_commands_are_unchanged():
    assert fleet.FORBIDDEN_COMMANDS == {"git", "gh", "claude", "codex", "agent", "agy", "cmd", "powershell", "pwsh", "sh", "bash"}


# AC-40: the installed kit accepts the member's layout. Real wrappers, real install, stub CLIs, fixture registry.


AC40_SESSION = "11111111-2222-3333-4444-555555555555"
AC40_RUN = "kit-run"
AC40_REGISTRY = {
    "schema_version": 1,
    "updated": "2026-01-01",
    "pins": {},
    "classes": {
        "isolated_worker": {"contract": {"effort_default": "medium"}, "bindings": {"codex-cli": {"slug": "fake-codex"}, "claude-p": {"slug": "fake-claude"}}},
        "independent_reviewer": {"contract": {"effort_default": "high"}, "bindings": {"codex-cli": {"slug": "fake-codex"}}},
    },
    "catalog": {
        "fake-codex": {"vendor": "openai", "harness_ids": {"codex-cli": {"medium": "fake-codex", "high": "fake-codex"}}, "efforts": ["medium", "high"]},
        "fake-claude": {"vendor": "anthropic", "harness_ids": {"claude-p": {"medium": "fake-claude", "high": "fake-claude"}}, "efforts": ["medium", "high"]},
    },
}
AC40_STUB = f"""import json, os, sys
cli, args = sys.argv[1], sys.argv[2:]
if "--version" in args:
    print("codex-cli 9.9.9" if cli == "codex" else "2.1.300 (Claude Code)")
    raise SystemExit(0)
sys.stdin.read()
with open(os.environ["STUB_CALLS"], "a", encoding="utf-8") as f:
    f.write(json.dumps({{"cli": cli, "cwd": os.getcwd(), "args": args}}) + "\\n")
if cli == "codex":
    with open(args[args.index("-o") + 1], "w", encoding="utf-8") as f:
        f.write("Wrote it.\\nStatus: DONE\\n")
    print(json.dumps({{"type": "thread.started", "thread_id": "{AC40_SESSION}"}}))
    print(json.dumps({{"type": "turn.completed"}}))
else:
    print(json.dumps({{"type": "result", "is_error": False, "result": "ok", "session_id": "{AC40_SESSION}", "total_cost_usd": 0.0}}))
"""


class KitLayout:
    """A real kit in a temp FLEET_HOME, reached with the real pwsh and stub CLIs."""

    def __init__(self, rig: KitRig):
        self.rig, self.home = rig, rig.home
        self.pwsh = shutil.which("pwsh")
        self.stubs = rig.base / "cli-stubs"
        self.stubs.mkdir()
        (self.stubs / "cli_stub.py").write_text(AC40_STUB, encoding="utf-8")
        for cli in ("codex", "claude"):
            (self.stubs / f"{cli}.cmd").write_text(f'@"{sys.executable}" "{self.stubs / "cli_stub.py"}" {cli} %*\n', encoding="utf-8")
        self.write_registry(rig.profile, AC40_REGISTRY)
        self.calls_file = rig.base / "cli-calls.jsonl"
        self.slot = self.home / "agent" / AC40_RUN / "slot"
        self.slot.mkdir(parents=True)
        (self.home / "agent" / AC40_RUN / "manifest.json").write_text(json.dumps({"cli": "codex", "run": AC40_RUN}), encoding="utf-8")
        self.brief = self.home / "receipts" / "fleet-briefs" / AC40_RUN / "brief-1.md"
        self.brief.parent.mkdir(parents=True, exist_ok=True)
        self.brief.write_text("the brief\n", encoding="utf-8")
        self.elsewhere = rig.base / "elsewhere"
        self.elsewhere.mkdir()
        (self.elsewhere / "brief.md").write_text("the brief\n", encoding="utf-8")
        self.numbers = itertools.count(1)

    def write_registry(self, profile: Path, registry: dict) -> None:
        (profile / ".agent").mkdir(parents=True, exist_ok=True)
        (profile / ".agent" / "model-registry.json").write_text(json.dumps(registry), encoding="utf-8")

    def env(self, profile: Path | None = None, **over) -> dict:
        """No variable leads to the home registry, and with no login in reach a CLI the stubs missed could not spend."""
        full = {k: v for k, v in os.environ.items() if k not in ("AGENT_MODEL_REGISTRY", "AGENT_MODEL_REGISTRY_HOME", "FLEET_CODEX_LOCK")}
        keep = [str(self.stubs), str(Path(self.pwsh).parent), str(Path(sys.executable).parent), str(Path(shutil.which("git")).parent), os.environ["SystemRoot"] + r"\System32"]
        profile = profile or self.rig.profile
        full.update({
            "PATH": os.pathsep.join(keep), "USERPROFILE": str(profile), "HOME": str(profile), "FLEET_HOME": str(self.home),
            "CODEX_HOME": str(self.rig.base / "no-codex-login"), "CLAUDE_CONFIG_DIR": str(self.rig.config), "STUB_CALLS": str(self.calls_file),
        })
        return {**full, **over}

    def script(self, rel: str, *args: str, cwd: Path | None = None, profile: Path | None = None, **env) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.pwsh, "-NoProfile", "-NonInteractive", "-File", str(self.home / "kit" / rel), *args],
            cwd=cwd or self.home, env=self.env(profile, **env), capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=180,
        )

    def dispatch(self) -> str:
        return f"kit-{next(self.numbers)}-{uuid.uuid4().hex[:8]}"

    def claude(self, *args: str, **kw) -> subprocess.CompletedProcess:
        return self.script("tools/Invoke-ClaudeDispatch.ps1", "-ModelClass", "isolated_worker", "-DispatchId", self.dispatch(), *args, **kw)

    def codex(self, *args: str, **kw) -> subprocess.CompletedProcess:
        return self.script("tools/Invoke-CodexDispatch.ps1", "-NonReviewDispatch", "-DispatchId", self.dispatch(), *args, **kw)

    def codex_run(self, dispatch: str, *args: str) -> subprocess.CompletedProcess:
        return self.script("fleet/fleet-tasks.ps1", "-Action", "CodexRun", "-Run", AC40_RUN, "-Brief", str(self.brief), "-Slot", str(self.slot), "-DispatchId", dispatch, *args)

    def calls(self) -> list[dict]:
        if not self.calls_file.exists():
            return []
        return [json.loads(line) for line in self.calls_file.read_text(encoding="utf-8").splitlines()]

    def clear_calls(self) -> None:
        self.calls_file.unlink(missing_ok=True)


def same_folder(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(Path(a).resolve()) == os.path.normcase(Path(b).resolve())


@pytest.fixture(scope="module")
def kit_layout(tmp_path_factory):
    rig = KitRig(tmp_path_factory.mktemp("kit-layout")).real_slot()
    rig.place(REPO / ".agent/tools/ModelRegistry.psm1", ".agent/tools/ModelRegistry.psm1")
    result = rig.run("install")
    assert result.returncode == 0, result.stdout + result.stderr
    return KitLayout(rig)


@pytest.fixture
def kit(kit_layout):
    kit_layout.clear_calls()
    return kit_layout


def test_ac40_claude_takes_a_brief_from_fleet_briefs_and_runs_in_the_slot(kit):
    r = kit.claude("-PromptFile", str(kit.brief), "-WorkingDirectory", str(kit.slot))
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c["cli"] for c in kit.calls()] == ["claude"]
    assert same_folder(kit.calls()[0]["cwd"], kit.slot)


def test_ac40_a_codex_start_then_a_resume_through_the_task_script(kit):
    first, second = kit.dispatch(), kit.dispatch()
    r = kit.codex_run(first)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = kit.calls()
    assert [c["cli"] for c in calls] == ["codex"]
    assert same_folder(calls[0]["args"][calls[0]["args"].index("-C") + 1], kit.slot)
    # P-4: the task script asks for FullAccess, and the real wrapper accepts its justification.
    assert calls[0]["args"][calls[0]["args"].index("-s") + 1] == "danger-full-access"
    assert (kit.home / "codex.lock").is_file()
    state = json.loads(kit.script("fleet/fleet-tasks.ps1", "-Action", "CodexState", "-Run", AC40_RUN, "-DispatchId", first).stdout)
    assert state["status_line"] == "DONE"
    status = json.loads((kit.home / "receipts" / "dispatch" / first / "status.json").read_text(encoding="utf-8-sig"))
    assert status["session_id"] == AC40_SESSION

    r = kit.codex_run(second, "-ResumeDispatchId", first)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = kit.calls()
    assert len(calls) == 2
    assert same_folder(calls[1]["cwd"], kit.slot)
    assert calls[1]["args"][calls[1]["args"].index("resume") + 1] == AC40_SESSION


def test_ac40_a_job_in_the_slot_can_ask_codex_with_a_prompt_file_in_that_slot(kit):
    prompt = kit.slot / "question.md"
    prompt.write_text("what does this do?\n", encoding="utf-8")
    for mode in ("ReviewReadOnly", "ReviewWorkspace"):
        kit.clear_calls()
        r = kit.codex("-Mode", mode, "-AuthorVendor", "anthropic", "-PromptFile", str(prompt), "-WorkingDirectory", str(kit.slot), cwd=kit.slot)
        assert r.returncode == 0, r.stdout + r.stderr
        calls = kit.calls()
        assert [c["cli"] for c in calls] == ["codex"]
        assert same_folder(calls[0]["args"][calls[0]["args"].index("-C") + 1], kit.slot)


def test_ac40_a_brief_outside_both_roots_is_refused_and_no_cli_runs(kit):
    outside = str(kit.elsewhere / "brief.md")
    claude = kit.claude("-PromptFile", outside, "-WorkingDirectory", str(kit.slot))
    codex = kit.codex("-ModelClass", "isolated_worker", "-Mode", "ReviewWorkspace", "-PromptFile", outside, "-WorkingDirectory", str(kit.slot))
    assert claude.returncode != 0 and "PromptFile must be under" in claude.stderr
    assert codex.returncode != 0 and "PromptFile must be under" in codex.stderr
    assert kit.calls() == []


def test_ac40_a_codex_working_directory_outside_the_home_is_refused(kit):
    r = kit.codex("-ModelClass", "isolated_worker", "-Mode", "ReviewWorkspace", "-PromptFile", str(kit.brief), "-WorkingDirectory", str(kit.elsewhere))
    assert r.returncode != 0
    assert kit.calls() == []


@pytest.mark.parametrize("launch", ["claude", "codex"])
def test_ac40_a_registry_without_the_binding_is_unresolvable_and_no_cli_runs(kit, launch):
    bare = kit.rig.base / f"bare-profile-{launch}"
    (bare / ".agent" / "tools").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(kit.rig.profile / ".agent" / "tools" / "ModelRegistry.psm1", bare / ".agent" / "tools" / "ModelRegistry.psm1")
    kit.write_registry(bare, {**AC40_REGISTRY, "classes": {"isolated_worker": {"contract": {"effort_default": "medium"}, "bindings": {"cursor-agent-cli": {"slug": "fake-codex"}}}}})
    if launch == "claude":
        r = kit.claude("-PromptFile", str(kit.brief), "-WorkingDirectory", str(kit.slot), profile=bare)
    else:
        r = kit.codex("-ModelClass", "isolated_worker", "-Mode", "ReviewWorkspace", "-PromptFile", str(kit.brief), "-WorkingDirectory", str(kit.slot), profile=bare)
    assert r.returncode != 0
    assert "unresolvable_on_harness" in r.stdout + r.stderr
    assert kit.calls() == []


def test_ac40_a_resume_on_the_default_class_is_still_refused(kit):
    first = kit.dispatch()
    assert kit.codex_run(first).returncode == 0
    kit.clear_calls()
    r = kit.codex("-Mode", "ReviewWorkspace", "-AuthorVendor", "anthropic", "-PromptFile", str(kit.brief), "-WorkingDirectory", str(kit.slot), "-ResumeDispatchId", first)
    assert r.returncode != 0
    assert "resume_refused_review_class" in r.stdout + r.stderr
    assert kit.calls() == []


def test_ac40_the_kit_holds_the_task_script(kit):
    assert (kit.home / "kit" / "fleet" / "fleet-tasks.ps1").is_file()


# AC-34 to AC-36: collect, result and drop. Chain: C-AGENT-MEMBER and cmd_result, with the rig's hub, member and shim,
# and the rig's repo as the orchestrator's.


DONE_VIEW = {"state": "done", "class": "done", "final_status": "DONE"}
ACTIVE_VIEWS = [
    pytest.param(stopped_view(state="running"), id="running"),
    pytest.param(stopped_view(state="made_up_state"), id="unknown"),
    pytest.param(stopped_view(state="cancelled", segments=[{"dispatch_id": "d-1", "expected_session_id": "sess-1"}]), id="cancelled-unfinished"),
]
OTHER_NAME = "Someone Else"
OTHER_EMAIL = "2+else@users.noreply.github.com"
JOB_IDENTITIES = [
    pytest.param({"GIT_AUTHOR_NAME": OTHER_NAME}, id="author-name"),
    pytest.param({"GIT_AUTHOR_EMAIL": OTHER_EMAIL}, id="author-address"),
    pytest.param({"GIT_COMMITTER_NAME": OTHER_NAME}, id="committer-name"),
    pytest.param({"GIT_COMMITTER_EMAIL": OTHER_EMAIL}, id="committer-address"),
]


def blobs(rig: AgentRig) -> set[str]:
    return {p.name for p in (rig.hub.hub_dir / "blobs").iterdir()}


def slot_state(rig: AgentRig) -> tuple:
    slot = rig.slot()
    return commit_count(slot), run_git(slot, "rev-parse", "HEAD"), (slot / ".git" / "index").read_bytes()


def job_commit(slot: Path, name: str, **env: str) -> str:
    """A commit made by the job in its slot, as the base's identity unless env says otherwise."""
    identity = {
        "GIT_AUTHOR_NAME": AGENT_NAME, "GIT_AUTHOR_EMAIL": AGENT_EMAIL,
        "GIT_COMMITTER_NAME": AGENT_NAME, "GIT_COMMITTER_EMAIL": AGENT_EMAIL,
    }
    (slot / name).write_text(f"{name}\n", encoding="utf-8")
    run_git(slot, "add", name)
    r = subprocess.run(
        ["git", "commit", "-q", "--no-verify", "--no-gpg-sign", "-m", name], cwd=slot,
        env={**os.environ, **identity, **env}, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return run_git(slot, "rev-parse", "HEAD")


def collect(rig: AgentRig, view: dict | None = None):
    rig.answers("Get-CreditsRun.ps1", view=view or stopped_view(**DONE_VIEW))
    return rig.agent("collect")


def collected(rig: AgentRig) -> dict:
    r = collect(rig)
    assert r.returncode == 0, r.stdout + r.stderr
    return last_json(r)


def read_bundle(rig: AgentRig, status: dict) -> Path:
    reader = rig.base / f"reader-{status['task'][:8]}"
    reader.mkdir()
    run_git(reader, "init", "-q")
    run_git(reader, "fetch", "-q", str(rig.hub.hub_dir / "blobs" / status["bundle"]), f"refs/fleet/snap/{status['task']}:refs/heads/snap")
    return reader


def assert_nothing_sent(rig: AgentRig, r, reason: str, before: tuple, sent: set) -> None:
    assert (r.returncode, last_json(r)["reason"]) == (3, reason)
    assert slot_state(rig) == before
    assert blobs(rig) == sent
    assert not (rig.folder() / "collected").exists()


def test_ac34_collect_bundles_the_slot_under_the_base_identity(running_rig):
    rig, slot = running_rig, running_rig.slot()
    (slot / "new.txt").write_text("new\n", encoding="utf-8")
    (slot / "tracked.txt").write_text("three\n", encoding="utf-8")
    head_and_index = slot_state(rig)[1:]
    status = collected(rig)
    assert (status["state"], status["run"], status["cli"]) == ("completed", RUN, "claude")
    base = (rig.folder() / "base").read_text(encoding="utf-8")
    assert status["base"] == base
    assert status["bundle"] in blobs(rig)
    reader = read_bundle(rig, status)
    assert run_git(reader, "rev-parse", "snap") == status["commit"]
    assert run_git(reader, "rev-parse", "snap^{tree}") == status["tree"]
    assert run_git(reader, "rev-parse", "snap^") == base
    assert (run_git(reader, "show", "snap:new.txt"), run_git(reader, "show", "snap:tracked.txt")) == ("new", "three")
    assert not [p for p in run_git(reader, "ls-tree", "-r", "--name-only", "snap").splitlines() if p.startswith(".fleet-run")]
    who = f"{AGENT_NAME}|{AGENT_EMAIL}|{AGENT_NAME}|{AGENT_EMAIL}"
    assert run_git(reader, "log", "-1", "--format=%an|%ae|%cn|%ce", "snap") == run_git(reader, "log", "-1", "--format=%an|%ae|%cn|%ce", base) == who
    assert slot_state(rig)[1:] == head_and_index
    assert json.loads((rig.folder() / "collected").read_text(encoding="utf-8"))["commit"] == status["commit"]


def test_ac34_a_job_commit_under_the_base_identity_is_collected(running_rig):
    job = job_commit(running_rig.slot(), "done.txt")
    status = collected(running_rig)
    reader = read_bundle(running_rig, status)
    assert run_git(reader, "rev-parse", "snap^") == job
    assert run_git(reader, "show", "snap:done.txt") == "done.txt"


def test_ac34_a_secret_named_file_is_refused_and_nothing_is_sent(running_rig):
    (running_rig.slot() / "deploy.pem").write_text("x\n", encoding="utf-8")
    before, sent = slot_state(running_rig), blobs(running_rig)
    assert_nothing_sent(running_rig, collect(running_rig), "snapshot_secret_risk:deploy.pem", before, sent)


@pytest.mark.parametrize("view", ACTIVE_VIEWS)
def test_ac34_an_active_run_is_not_collected(running_rig, view):
    (running_rig.slot() / "new.txt").write_text("new\n", encoding="utf-8")
    before, sent = slot_state(running_rig), blobs(running_rig)
    assert_nothing_sent(running_rig, collect(running_rig, view), "run_active", before, sent)


def test_ac34_a_base_whose_address_fails_the_suffix_is_refused(running_rig):
    rig, slot = running_rig, running_rig.slot()
    old = job_commit(
        slot, "old.txt",
        GIT_AUTHOR_NAME="fleet", GIT_AUTHOR_EMAIL="fleet@fleet.invalid", GIT_COMMITTER_NAME="fleet", GIT_COMMITTER_EMAIL="fleet@fleet.invalid",
    )
    (rig.folder() / "base").write_text(old, encoding="utf-8")
    before, sent = slot_state(rig), blobs(rig)
    assert_nothing_sent(rig, collect(rig), "identity_mismatch", before, sent)


@pytest.mark.parametrize("env", JOB_IDENTITIES)
def test_ac34_a_job_commit_under_another_identity_is_refused(running_rig, env):
    job_commit(running_rig.slot(), "job.txt", **env)
    before, sent = slot_state(running_rig), blobs(running_rig)
    assert_nothing_sent(running_rig, collect(running_rig), "identity_mismatch", before, sent)


@pytest.mark.parametrize("glob,local,code", IDENTITY_REFUSALS)
def test_ac34_a_start_in_a_repo_with_a_refused_identity_sends_nothing(agent_rig, global_identity, glob, local, code):
    global_identity(*glob)
    set_repo_identity(agent_rig.repo, *local)
    before = identity_state(agent_rig.repo)
    r = agent_rig.start()
    assert (r.returncode, r.stderr.strip()) == (2, code)
    assert identity_state(agent_rig.repo) == before
    assert blobs(agent_rig) == set()


def test_ac34_a_codex_run_is_collected_the_same_way(codex_rig):
    codex_state(codex_rig, line="DONE")
    (codex_rig.slot() / "answer.txt").write_text("west\n", encoding="utf-8")
    r = codex_rig.agent("collect")
    assert r.returncode == 0, r.stdout + r.stderr
    status = last_json(r)
    assert (status["state"], status["cli"]) == ("completed", "codex")
    assert run_git(read_bundle(codex_rig, status), "show", "snap:answer.txt") == "west"


def test_ac34_a_running_codex_run_is_not_collected(codex_rig):
    codex_state(codex_rig, running=True)
    before, sent = slot_state(codex_rig), blobs(codex_rig)
    assert_nothing_sent(codex_rig, codex_rig.agent("collect"), "run_active", before, sent)


# AC-35: fleet.py result, against the rig's repo.


def repo_heads(repo: Path) -> tuple:
    return run_git(repo, "for-each-ref", "refs/heads"), run_git(repo, "symbolic-ref", "HEAD"), run_git(repo, "rev-parse", "HEAD")


def fleet_refs(repo: Path) -> str:
    return run_git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/fleet")


def result(rig: AgentRig):
    return rig.hub.cli("result", "alpha", RUN, "--repo", str(rig.repo), timeout=120)


def land(rig: AgentRig, status: dict, identity: tuple = (AGENT_NAME, AGENT_EMAIL)) -> dict:
    return fleet.land_result(rig.hub.client(), rig.repo, RUN, status["task"], status, identity)


def test_ac35_a_result_lands_at_its_ref_with_no_branch(running_rig):
    rig = running_rig
    (rig.slot() / "new.txt").write_text("new\n", encoding="utf-8")
    rig.answers("Get-CreditsRun.ps1", view=stopped_view(**DONE_VIEW))
    heads, porcelain = repo_heads(rig.repo), run_git(rig.repo, "status", "--porcelain")
    r = result(rig)
    assert r.returncode == 0, r.stdout + r.stderr
    landed = last_json(r)
    assert (landed["run"], landed["ref"]) == (RUN, f"refs/fleet/result/{RUN}")
    assert fleet_refs(rig.repo) == f"refs/fleet/result/{RUN} {landed['commit']}"
    assert run_git(rig.repo, "rev-parse", f"{landed['commit']}^{{tree}}") == landed["tree"]
    assert landed["base"] == (rig.folder() / "base").read_text(encoding="utf-8")
    assert "new.txt" in landed["diff_stat"]
    assert repo_heads(rig.repo) == heads
    assert run_git(rig.repo, "status", "--porcelain") == porcelain


def test_ac35_an_existing_result_is_kept(running_rig):
    running_rig.answers("Get-CreditsRun.ps1", view=stopped_view(**DONE_VIEW))
    assert result(running_rig).returncode == 0
    refs, heads = fleet_refs(running_rig.repo), repo_heads(running_rig.repo)
    r = result(running_rig)
    assert (r.returncode, r.stderr.strip()) == (2, "result_exists")
    assert (fleet_refs(running_rig.repo), repo_heads(running_rig.repo)) == (refs, heads)


def test_ac35_a_ref_set_while_landing_is_kept(running_rig):
    status = collected(running_rig)
    land(running_rig, status)
    refs = fleet_refs(running_rig.repo)
    with pytest.raises(fleet.Refuse) as e:
        land(running_rig, status)
    assert e.value.code == "result_exists"
    assert fleet_refs(running_rig.repo) == refs


def test_ac35_a_tampered_blob_is_bundle_bad(running_rig):
    status = collected(running_rig)
    (running_rig.hub.hub_dir / "blobs" / status["bundle"]).write_bytes(b"tampered")
    heads = repo_heads(running_rig.repo)
    with pytest.raises(fleet.Refuse) as e:
        land(running_rig, status)
    assert e.value.code == "bundle_bad"
    assert (fleet_refs(running_rig.repo), repo_heads(running_rig.repo)) == ("", heads)


def test_ac35_a_blob_that_is_not_a_bundle_is_bundle_bad(running_rig):
    status = collected(running_rig)
    data = b"not a bundle"
    sha = hashlib.sha256(data).hexdigest()
    fleet.api(running_rig.hub.client(), "PUT", f"/v1/blobs/{sha}", raw=data)
    with pytest.raises(fleet.Refuse) as e:
        land(running_rig, {**status, "bundle": sha})
    assert e.value.code == "bundle_bad"
    assert fleet_refs(running_rig.repo) == ""


@pytest.mark.parametrize("field,value", [("commit", "x"), ("base", None), ("bundle", "c" * 64)])
def test_ac35_a_bad_status_field_is_bundle_bad(running_rig, field, value):
    status = collected(running_rig)
    with pytest.raises(fleet.Refuse) as e:
        land(running_rig, {**status, field: value})
    assert e.value.code == "bundle_bad"
    assert fleet_refs(running_rig.repo) == ""


def test_ac35_a_commit_other_than_the_bundles_is_bundle_bad(running_rig):
    status = collected(running_rig)
    with pytest.raises(fleet.Refuse) as e:
        land(running_rig, {**status, "commit": status["base"]})
    assert e.value.code == "bundle_bad"
    assert fleet_refs(running_rig.repo) == ""


def test_ac35_a_wrong_tree_is_tree_mismatch(running_rig):
    status = collected(running_rig)
    heads = repo_heads(running_rig.repo)
    with pytest.raises(fleet.Refuse) as e:
        land(running_rig, {**status, "tree": "0" * 40})
    assert e.value.code == "tree_mismatch"
    assert (fleet_refs(running_rig.repo), repo_heads(running_rig.repo)) == ("", heads)


def test_ac35_a_commit_under_another_identity_than_the_orchestrators_is_refused(running_rig, global_identity):
    running_rig.answers("Get-CreditsRun.ps1", view=stopped_view(**DONE_VIEW))
    global_identity(OTHER_NAME, OTHER_EMAIL)
    heads = repo_heads(running_rig.repo)
    r = result(running_rig)
    assert (r.returncode, r.stderr.strip()) == (2, "identity_mismatch")
    assert (fleet_refs(running_rig.repo), repo_heads(running_rig.repo)) == ("", heads)


@pytest.mark.parametrize("glob,local,code", IDENTITY_REFUSALS)
def test_ac35_a_repo_with_a_refused_identity_gets_no_result(agent_rig, global_identity, glob, local, code):
    global_identity(*glob)
    set_repo_identity(agent_rig.repo, *local)
    heads = repo_heads(agent_rig.repo)
    r = result(agent_rig)
    assert (r.returncode, r.stderr.strip()) == (2, code)
    assert (fleet_refs(agent_rig.repo), repo_heads(agent_rig.repo)) == ("", heads)


def test_ac35_a_rejected_collect_is_the_results_exit(running_rig):
    running_rig.answers("Get-CreditsRun.ps1", view=stopped_view(state="running"))
    r = result(running_rig)
    assert (r.returncode, last_json(r)["reason"]) == (3, "run_active")
    assert fleet_refs(running_rig.repo) == ""


def test_ac35_no_code_path_merges_pushes_or_checks_out_outside_a_slot():
    found = []
    for fn in ast.walk(ast.parse(FLEET_PY.read_text(encoding="utf-8"))):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "git":
                words = [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                found += [(fn.name, w) for w in words if w in ("push", "checkout") or w.startswith("merge")]
    assert found == [("fetch_snapshot", "checkout")]


def test_ac35_result_is_a_verb_with_a_repo():
    args = fleet.build_parser().parse_args(["result", "alpha", RUN, "--repo", "r"])
    assert (args.member, args.run, args.repo, args.fn) == ("alpha", RUN, "r", fleet.cmd_result)


# AC-36: drop.


def remove_call(rig: AgentRig) -> bool:
    return ["-Action", "Remove", "-Run", RUN] in task_calls(rig)


def test_ac36_a_run_not_collected_is_not_dropped(running_rig):
    running_rig.answers("Get-CreditsRun.ps1", view=stopped_view(**DONE_VIEW))
    r = running_rig.agent("drop")
    assert (r.returncode, last_json(r)["reason"]) == (3, "not_collected")
    assert running_rig.folder().is_dir() and running_rig.briefs().is_dir()
    assert not remove_call(running_rig)


@pytest.mark.parametrize("view", ACTIVE_VIEWS)
def test_ac36_an_active_run_is_not_dropped(running_rig, view):
    collected(running_rig)
    running_rig.answers("Get-CreditsRun.ps1", view=view)
    r = running_rig.agent("drop")
    assert (r.returncode, last_json(r)["reason"]) == (3, "run_active")
    assert running_rig.folder().is_dir() and running_rig.briefs().is_dir()
    assert not remove_call(running_rig)


def test_ac36_a_collected_run_is_dropped_and_its_credits_rows_stay(running_rig):
    collected(running_rig)
    r = running_rig.agent("drop")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (last_json(r)["state"], last_json(r)["dropped"]) == ("completed", True)
    assert remove_call(running_rig)
    assert not running_rig.folder().exists() and not running_rig.briefs().exists()
    assert (running_rig.home / "receipts" / "credits" / "runs" / RUN / "view.json").is_file()


def test_ac36_a_collected_codex_run_is_dropped(codex_rig):
    codex_state(codex_rig, line="DONE")
    assert codex_rig.agent("collect").returncode == 0
    r = codex_rig.agent("drop")
    assert r.returncode == 0, r.stdout + r.stderr
    assert remove_call(codex_rig)
    assert not codex_rig.folder().exists() and not codex_rig.briefs().exists()


# AC-38: the relabelled template, the two skills and the manifest


CREDITS_SKILL = REPO / "core" / ".agent" / "skills" / "claude-credits" / "SKILL.md"
DISPATCH_SKILL = REPO / "core" / ".agent" / "skills" / "cli-dispatch" / "SKILL.md"
CORE_MANIFEST = REPO / "core" / "MANIFEST.md"
D6_STOPS = {"browser-approval", "firewall-rule", "run-approve"}
CONSOLE_LOGIN_RULE = "A human creates each login at this machine's console"
# claude-credits SKILL.md lines 340-343, which no change may touch.
BILLING_RULE = (
    "8. Never set, unset or override `CLAUDE_CODE_ENTRYPOINT`, `CLAUDECODE` or related variables\n"
    "   to make a run look like Agent SDK usage, and never `cswap switch` to the API-key slot from\n"
    "   an agent session. Both misrepresent the run to billing, and the switch also breaks every\n"
    "   other open session. Never print or copy the key file's contents.\n"
)
MEMBER_ROUTE_TERMS = ("launch.auth", "subscription", "S4U", "gate_project", "CLAUDE_CODE_OAUTH_TOKEN", "credits_inbox.py")
DISPATCH_ROUTE_TERMS = (
    "FLEET_CODEX_LOCK", "CODEX_BUSY_EXIT", "codex_job_busy", "-CodexExecutable", "codex_executable_refused",
    "CODEX_MODEL_CLASS", "isolated_worker", "-NonReviewDispatch",
)
FLEET_MANIFEST_ENTRIES = (
    ".agent/fleet/member_kit.py", ".agent/fleet/setup-member.ps1", ".agent/fleet/fleet-tasks.ps1", ".agent/fleet.json",
)


def flat(text: str) -> str:
    return " ".join(text.split())


def section_text(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1) if match else ""


def skill_problems(credits: str, dispatch: str) -> list[str]:
    problems = [] if BILLING_RULE in credits.replace("\r\n", "\n") else ["the billing rule is not verbatim"]
    member = section_text(credits, "Fleet member route")
    problems += [f"the member route does not name {t}" for t in MEMBER_ROUTE_TERMS if t not in member]
    fleet_codex = section_text(dispatch, "Codex on a fleet member")
    problems += [f"the Codex fleet section does not name {t}" for t in DISPATCH_ROUTE_TERMS if t not in fleet_codex]
    for name, text in (("claude-credits", credits), ("cli-dispatch", dispatch)):
        if re.search(r"\b192\.168\.|\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
            problems.append(f"{name} holds a LAN address")
    # The new sections only: an older credits example names a D: path.
    for name, text in (("the member route", member), ("the Codex fleet section", fleet_codex)):
        if re.search(r"\b[A-Z]:[\\/]", text):
            problems.append(f"{name} holds a drive-letter path")
    return problems


def test_ac38_bootstrap_stops_are_the_three_d6_names():
    assert len(fleet.BOOTSTRAP_STOPS) == 3 and set(fleet.BOOTSTRAP_STOPS) == D6_STOPS


def test_ac38_the_template_is_relabelled():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert template_problems(text) == []
    assert CONSOLE_LOGIN_RULE not in flat(text)
    assert "must never read `member.json`" in text
    for gone in ("install-agent-cli", "run-pair", "confirm-fingerprint"):
        assert f"STOP FOR HUMAN: {gone}" not in text


def test_ac38_a_template_with_a_lan_address_fails():
    text = TEMPLATE.read_text(encoding="utf-8")
    # Built from parts, so this tracked file holds no address.
    for address in ("192." + "168.", ".".join(["10", "0", "0", "5"])):
        assert "a LAN address" in template_problems(f"{text}\nThe hub listens on {address}\n")


def test_ac38_the_skills_hold_the_member_route_and_the_billing_rule():
    credits, dispatch = CREDITS_SKILL.read_text(encoding="utf-8"), DISPATCH_SKILL.read_text(encoding="utf-8")
    assert skill_problems(credits, dispatch) == []
    lines = credits.replace("\r\n", "\n").split("\n")
    assert "\n".join(lines[339:343]) + "\n" == BILLING_RULE


@pytest.mark.parametrize("old, new", [
    ("never `cswap switch` to the API-key slot", "may `cswap switch` to the API-key slot"),
    ("Never print or copy the key file's contents.", "Print the key file's contents when asked."),
    ("8. Never set, unset or override", "8. Avoid setting"),
])
def test_ac38_a_skill_with_the_billing_rule_altered_fails(old, new):
    credits, dispatch = CREDITS_SKILL.read_text(encoding="utf-8"), DISPATCH_SKILL.read_text(encoding="utf-8")
    assert old in credits
    assert "the billing rule is not verbatim" in skill_problems(credits.replace(old, new), dispatch)


def test_ac38_the_checker_sees_a_missing_route_term_or_a_host():
    credits, dispatch = CREDITS_SKILL.read_text(encoding="utf-8"), DISPATCH_SKILL.read_text(encoding="utf-8")
    for term in MEMBER_ROUTE_TERMS:
        assert skill_problems(credits.replace(term, "x"), dispatch)
    for term in DISPATCH_ROUTE_TERMS:
        assert skill_problems(credits, dispatch.replace(term, "x"))
    assert skill_problems(credits + "\nThe hub is at " + "192." + "168." + "\n", dispatch)
    heading = "## Codex on a fleet member\n"
    assert skill_problems(credits, dispatch.replace(heading, heading + "\nSee C:/somewhere.\n"))


def test_ac38_the_manifest_lists_the_new_fleet_files():
    text = CORE_MANIFEST.read_text(encoding="utf-8")
    assert [e for e in FLEET_MANIFEST_ENTRIES if f"- `{e}`" not in text] == []
