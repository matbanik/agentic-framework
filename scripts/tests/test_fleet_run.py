"""AC-22 to AC-30 of the fleet MVP plan: manifests, snapshots, slots and run tasks."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from fleet_harness import ROOT, Hub, fleet, new_envelope, wait_until  # noqa: E402

MANIFEST_TEMPLATE = ROOT / "core" / ".agent" / "fleet.json.template"
GOOD = {"v": 1, "project": "demo", "requires": ["python"], "commands": {"test": [["python", "-V"]]}}
PYTHON = Path(sys.executable).as_posix()
RESULT_KEYS = {"state", "reason", "exit_code", "log", "tree", "duration_s"}
FIXTURE_NAME = "fixture"
FIXTURE_EMAIL = "1+fixture@users.noreply.github.com"


# AC-22: manifest validation


def filled_template() -> dict:
    return json.loads(MANIFEST_TEMPLATE.read_text(encoding="utf-8").replace("{{PROJECT_NAME}}", "demo"))


def test_ac22_the_filled_template_is_valid():
    assert fleet.validate_manifest(filled_template()) is None


def test_ac22_the_unfilled_template_is_refused():
    assert fleet.validate_manifest(json.loads(MANIFEST_TEMPLATE.read_text(encoding="utf-8"))) == "bad_manifest:project"


def test_ac22_a_good_manifest_is_accepted():
    assert fleet.validate_manifest(GOOD) is None


@pytest.mark.parametrize(
    "bad, code",
    [
        ({**GOOD, "extra": 1}, "bad_manifest:unknown_key:extra"),
        ({k: v for k, v in GOOD.items() if k != "requires"}, "bad_manifest:missing_key:requires"),
        ({**GOOD, "v": 2}, "bad_manifest:version"),
        ({**GOOD, "v": True}, "bad_manifest:version"),
        ({**GOOD, "project": "../x"}, "bad_manifest:project"),
        ({**GOOD, "project": 3}, "bad_manifest:project"),
        ({**GOOD, "project": "demo\n"}, "bad_manifest:project"),
        ({**GOOD, "requires": "python"}, "bad_manifest:requires"),
        ({**GOOD, "requires": ["cargo"]}, "bad_manifest:requires"),
        ({**GOOD, "requires": [1]}, "bad_manifest:requires"),
        ({**GOOD, "commands": {}}, "bad_manifest:commands"),
        ({**GOOD, "commands": []}, "bad_manifest:commands"),
        ({**GOOD, "commands": {"../x": [["python"]]}}, "bad_manifest:command_name"),
        ({**GOOD, "commands": {"test": []}}, "bad_manifest:argv"),
        ({**GOOD, "commands": {"test": "python -V"}}, "bad_manifest:argv"),
        ({**GOOD, "commands": {"test": ["python -V"]}}, "bad_manifest:argv"),
        ({**GOOD, "commands": {"test": [[]]}}, "bad_manifest:argv"),
        ({**GOOD, "commands": {"test": [["python", 3]]}}, "bad_manifest:argv"),
        ({**GOOD, "commands": {"test": [[""]]}}, "bad_manifest:argv"),
    ],
)
def test_ac22_bad_shapes_are_refused(bad, code):
    assert fleet.validate_manifest(bad) == code


@pytest.mark.parametrize("value", [None, [], "x", 3])
def test_ac22_a_manifest_must_be_an_object(value):
    assert fleet.validate_manifest(value) == "bad_manifest:not_object"


@pytest.mark.parametrize("name", sorted(fleet.FORBIDDEN_COMMANDS))
@pytest.mark.parametrize("form", ["{}", "{}.EXE", "C:/x/{}", "C:\\x\\{}.cmd"])
def test_ac22_forbidden_tools_are_refused_in_every_form(name, form):
    argv0 = form.format(name.upper() if form.endswith("EXE") else name)
    manifest = {**GOOD, "commands": {"test": [["python", "-V"], [argv0, "status"]]}}
    assert fleet.validate_manifest(manifest) == f"bad_manifest:forbidden_command:{name}"


def test_ac22_a_forbidden_word_as_a_later_argument_is_not_refused():
    # The check is on the first element only: the plan states it is not a boundary.
    assert fleet.validate_manifest({**GOOD, "commands": {"test": [["uv", "run", "git"]]}}) is None


# Fixtures and helpers for AC-23 to AC-30


def git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if check:
        assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout.strip()


def write_manifest(repo: Path, project: str, commands: dict) -> None:
    (repo / ".agent").mkdir(exist_ok=True)
    manifest = {"v": 1, "project": project, "requires": ["python"], "commands": commands}
    (repo / ".agent" / "fleet.json").write_text(json.dumps(manifest), encoding="utf-8")


def new_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", FIXTURE_NAME)
    git(path, "config", "user.email", FIXTURE_EMAIL)
    git(path, "config", "commit.gpgsign", "false")
    (path / ".gitignore").write_text("ignored.txt\ndeps/\n", encoding="utf-8")
    (path / "tracked.txt").write_text("committed\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "--no-verify", "-m", "first")
    return path


def writer(sentinel: Path) -> list[str]:
    """A manifest step that creates a sentinel file."""
    return [PYTHON, "-c", "import sys; open(sys.argv[1], 'w').close()", str(sentinel)]


def last_json(r: subprocess.CompletedProcess) -> dict:
    assert r.stdout.strip(), r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def blob_files(hub: Hub) -> list[str]:
    return sorted(p.name for p in (hub.hub_dir / "blobs").iterdir())


def run_task(hub: Hub, member: str, repo: Path, command: str, *extra: str, env: dict | None = None) -> dict:
    r = hub.cli("run", member, "--repo", str(repo), command, *extra, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return last_json(r)


def wait_task(hub: Hub, task: str, log: Path | None = None):
    args = ["wait", task, "--timeout", "90"] + (["--log", str(log)] if log else [])
    r = hub.cli(*args, timeout=120)
    return r.returncode, last_json(r)


def post_snapshot(hub: Hub, member: str, repo: Path, command: str = "test", project: str = "demo", **refs) -> str:
    """Post a run task directly, skipping the checks in the ``run`` verb."""
    task = fleet.new_id()
    snap, data = fleet.make_snapshot(repo, task)
    data = refs.pop("data", data)
    bundle = hashlib.sha256(data).hexdigest()
    fleet.api(hub.client(), "PUT", f"/v1/blobs/{bundle}", raw=data)
    env = new_envelope(
        "orchestrator", member, "run", id=task, task_id=task,
        body={"project": project, "command": command, "timeout_s": 60},
        refs={"commit": snap["commit"], "tree": snap["tree"], "bundle": bundle, **refs},
    )
    fleet.api(hub.client(), "POST", "/v1/tasks", env)
    return task


def wait_online(hub: Hub) -> None:
    """A starting member is offline until its first hello, and wait exits 5 for an offline member."""
    wait_until(lambda: hub.request("GET", "/v1/members", key=hub.client().key)[1]["members"][0]["online"], timeout=30)


@pytest.fixture(scope="module", autouse=True)
def global_identity(tmp_path_factory):
    """The global git identity for this module, in place before the module-scoped rig starts its member."""
    config = tmp_path_factory.mktemp("gitconfig") / "global"
    config.write_text(f"[user]\n\tname = {FIXTURE_NAME}\n\temail = {FIXTURE_EMAIL}\n", encoding="utf-8")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GIT_CONFIG_GLOBAL", str(config))
        yield


@pytest.fixture
def hub(tmp_path):
    h = Hub(tmp_path)
    h.start()
    yield h
    h.close()


@pytest.fixture(scope="module")
def rig(tmp_path_factory):
    """One hub and one running member, with a gh shim on the member's PATH that records any call."""
    tmp = tmp_path_factory.mktemp("rig")
    h = Hub(tmp)
    h.start()
    member = h.pair("alpha")
    shims = tmp / "shims"
    shims.mkdir()
    (shims / "gh.cmd").write_text('@echo called> "%~dp0called.txt"\n', encoding="ascii")
    member.start(env={"PATH": f"{shims};{os.environ['PATH']}"})
    wait_online(h)
    yield h, member, shims
    h.close()


def observe(repo: Path) -> dict:
    """Everything a snapshot must leave alone. The index is read first, because status can refresh it."""
    index = (repo / ".git" / "index").read_bytes()
    files = {}
    for path in sorted(repo.rglob("*")):
        if path.is_file() and ".git" not in path.relative_to(repo).parts:
            files[path.relative_to(repo).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "files": files,
        "index": index,
        "head": git(repo, "rev-parse", "HEAD"),
        "status": git(repo, "--no-optional-locks", "status", "--porcelain"),
        "branches": git(repo, "branch", "--list"),
        "worktrees": git(repo, "worktree", "list"),
        "refs": git(repo, "for-each-ref", "refs/fleet"),
    }


@pytest.fixture
def dirty(tmp_path) -> Path:
    """A repo with staged, unstaged, untracked and ignored changes, and a manifest."""
    repo = new_repo(tmp_path / "repo")
    write_manifest(repo, "demo", {"test": [[PYTHON, "-V"]]})
    (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    git(repo, "add", "staged.txt")
    (repo / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    (repo / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    return repo


# AC-23: the snapshot


def test_ac23_the_bundle_has_the_working_tree_and_not_the_ignored_file(hub, dirty, tmp_path):
    hub.pair("alpha")
    run = run_task(hub, "alpha", dirty, "test")
    reader = tmp_path / "reader"
    reader.mkdir()
    git(reader, "init", "-q")
    bundle = hub.hub_dir / "blobs" / run["bundle"]
    git(reader, "fetch", "-q", str(bundle), f"refs/fleet/snap/{run['task']}:refs/heads/snap")
    assert git(reader, "rev-parse", "snap^{tree}") == run["tree"]
    names = git(reader, "ls-tree", "-r", "--name-only", "snap").splitlines()
    assert {"staged.txt", "tracked.txt", "untracked.txt", ".agent/fleet.json"} <= set(names)
    assert "ignored.txt" not in names
    assert git(reader, "show", "snap:tracked.txt") == "unstaged"
    assert git(reader, "show", "snap:untracked.txt") == "untracked"
    assert git(reader, "log", "-1", "--format=%an", "snap") == FIXTURE_NAME


def test_ac23_an_ignored_manifest_still_travels_and_nothing_else_ignored_does(hub, dirty, tmp_path):
    (dirty / ".git" / "info" / "exclude").write_text(".agent/fleet.json\n", encoding="utf-8")
    assert git(dirty, "check-ignore", ".agent/fleet.json") == ".agent/fleet.json"
    hub.pair("alpha")
    before = observe(dirty)
    run = run_task(hub, "alpha", dirty, "test")
    assert observe(dirty) == before
    names = git(dirty, "ls-tree", "-r", "--name-only", run["tree"]).splitlines()
    assert ".agent/fleet.json" in names
    assert "ignored.txt" not in names


def test_ac23_the_commit_has_head_as_its_parent_and_is_unsigned(hub, dirty):
    hub.pair("alpha")
    head = git(dirty, "rev-parse", "HEAD")
    run = run_task(hub, "alpha", dirty, "test")
    assert git(dirty, "rev-parse", f"{run['commit']}^") == head
    assert "gpgsig" not in git(dirty, "cat-file", "commit", run["commit"])


def test_ac23_the_repo_is_unchanged(hub, dirty):
    hub.pair("alpha")
    before = observe(dirty)
    run_task(hub, "alpha", dirty, "test")
    assert observe(dirty) == before
    assert before["refs"] == ""


def test_ac23_oracle_the_comparison_catches_a_clobbered_file(dirty):
    before = observe(dirty)
    (dirty / "untracked.txt").write_text("clobbered\n", encoding="utf-8")
    after = observe(dirty)
    assert after["status"] == before["status"]
    assert after != before


def test_ac23_a_failed_bundle_leaves_no_fleet_ref(hub, dirty, tmp_path):
    hub.pair("alpha")
    blobs, rows = blob_files(hub), hub.rows()
    shims = tmp_path / "shims"
    shims.mkdir()
    (shims / "git.cmd").write_text(
        f'@echo off\nif "%1"=="bundle" exit /b 1\n"{shutil.which("git")}" %*\nexit /b %errorlevel%\n',
        encoding="ascii",
    )
    r = hub.cli("run", "alpha", "--repo", str(dirty), "test", env={"PATH": f"{shims};{os.environ['PATH']}"})
    assert (r.returncode, r.stderr.strip()) == (2, "git_failed:bundle")
    assert git(dirty, "for-each-ref", "refs/fleet") == ""
    assert (blob_files(hub), hub.rows()) == (blobs, rows)


def test_ac23_a_repo_with_no_head_is_refused(hub, tmp_path):
    hub.pair("alpha")
    repo = tmp_path / "empty"
    repo.mkdir()
    git(repo, "init", "-q")
    write_manifest(repo, "demo", {"test": [[PYTHON, "-V"]]})
    r = hub.cli("run", "alpha", "--repo", str(repo), "test")
    assert (r.returncode, r.stderr.strip()) == (2, "no_head")


def test_ac23_run_refuses_a_missing_or_bad_manifest(hub, dirty, tmp_path):
    hub.pair("alpha")
    plain = new_repo(tmp_path / "plain")
    r = hub.cli("run", "alpha", "--repo", str(plain), "test")
    assert (r.returncode, r.stderr.strip()) == (2, "no_manifest")
    write_manifest(dirty, "demo", {"test": [["git", "status"]]})
    r = hub.cli("run", "alpha", "--repo", str(dirty), "test")
    assert (r.returncode, r.stderr.strip()) == (2, "bad_manifest:forbidden_command:git")
    (dirty / ".agent" / "fleet.json").write_text("{", encoding="utf-8")
    r = hub.cli("run", "alpha", "--repo", str(dirty), "test")
    assert (r.returncode, r.stderr.strip()) == (2, "bad_manifest:bad_json")


def test_ac23_an_oversized_snapshot_is_refused(dirty, monkeypatch):
    monkeypatch.setattr(fleet, "MAX_BLOB_BYTES", 1)
    with pytest.raises(fleet.Refuse) as caught:
        fleet.make_snapshot(dirty, fleet.new_id())
    assert caught.value.code == "too_large"
    assert git(dirty, "for-each-ref", "refs/fleet") == ""


# AC-24: likely secrets


@pytest.mark.parametrize("name", [".env.local", "deploy.pem", "aws_credentials.txt", "sub/DEPLOY.PEM", ".env"])
def test_ac24_a_likely_secret_stops_the_run(hub, dirty, name):
    hub.pair("alpha")
    blobs, rows = blob_files(hub), hub.rows()
    (dirty / name).parent.mkdir(exist_ok=True)
    (dirty / name).write_text("x\n", encoding="utf-8")
    r = hub.cli("run", "alpha", "--repo", str(dirty), "test")
    assert (r.returncode, r.stderr.strip()) == (2, f"snapshot_secret_risk:{name}")
    assert (blob_files(hub), hub.rows()) == (blobs, rows)
    assert git(dirty, "for-each-ref", "refs/fleet") == ""


def test_ac24_an_ignored_secret_and_the_allowed_names_pass(hub, dirty):
    hub.pair("alpha")
    (dirty / ".env.example").write_text("x\n", encoding="utf-8")
    (dirty / "credentials.template").write_text("x\n", encoding="utf-8")
    (dirty / "deps").mkdir()
    (dirty / "deps" / "deploy.pem").write_text("x\n", encoding="utf-8")
    assert run_task(hub, "alpha", dirty, "test")["tree"]


def commit_secret(repo: Path, name: str = "deploy.pem") -> None:
    (repo / name).write_text("x\n", encoding="utf-8")
    git(repo, "add", "-f", name)
    git(repo, "commit", "-q", "--no-verify", "-m", f"add {name}")


def secret_staged_out_and_ignored(repo: Path) -> None:
    commit_secret(repo)
    git(repo, "rm", "-q", "--cached", "deploy.pem")
    (repo / ".gitignore").write_text("ignored.txt\ndeps/\ndeploy.pem\n", encoding="utf-8")


def secret_deleted_later(repo: Path) -> None:
    commit_secret(repo)
    git(repo, "rm", "-q", "deploy.pem")
    git(repo, "commit", "-q", "--no-verify", "-m", "delete it")


def secret_renamed_away(repo: Path) -> None:
    commit_secret(repo)
    git(repo, "mv", "deploy.pem", "deploy.txt")
    git(repo, "commit", "-q", "--no-verify", "-m", "rename it")


def secret_only_in_a_merge(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "side")
    (repo / "side.txt").write_text("side\n", encoding="utf-8")
    git(repo, "add", "side.txt")
    git(repo, "commit", "-q", "--no-verify", "-m", "side")
    git(repo, "checkout", "-q", "-")
    git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
    (repo / "deploy.pem").write_text("x\n", encoding="utf-8")
    git(repo, "add", "deploy.pem")
    git(repo, "commit", "-q", "--no-verify", "-m", "merge")
    git(repo, "rm", "-q", "deploy.pem")
    git(repo, "commit", "-q", "--no-verify", "-m", "delete it")


@pytest.mark.parametrize(
    "history",
    [secret_staged_out_and_ignored, secret_deleted_later, secret_renamed_away, secret_only_in_a_merge],
)
def test_ac24_a_secret_in_the_history_stops_the_run(hub, tmp_path, history):
    hub.pair("alpha")
    repo = new_repo(tmp_path / "repo")
    write_manifest(repo, "demo", {"test": [[PYTHON, "-V"]]})
    history(repo)
    assert "deploy.pem" not in git(repo, "ls-files").splitlines()
    blobs, rows = blob_files(hub), hub.rows()
    r = hub.cli("run", "alpha", "--repo", str(repo), "test")
    assert (r.returncode, r.stderr.strip()) == (2, "snapshot_secret_risk:deploy.pem")
    assert (blob_files(hub), hub.rows()) == (blobs, rows)
    assert git(repo, "for-each-ref", "refs/fleet") == ""


def test_ac24_an_exact_name_deep_in_the_history_stops_the_run(hub, tmp_path):
    hub.pair("alpha")
    repo = new_repo(tmp_path / "repo")
    commit_secret(repo, ".env")
    git(repo, "rm", "-q", ".env")
    git(repo, "commit", "-q", "--no-verify", "-m", "delete it")
    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    git(repo, "add", "later.txt")
    git(repo, "commit", "-q", "--no-verify", "-m", "later")
    write_manifest(repo, "demo", {"test": [[PYTHON, "-V"]]})
    r = hub.cli("run", "alpha", "--repo", str(repo), "test")
    assert (r.returncode, r.stderr) == (2, "snapshot_secret_risk:.env\n")


def test_ac24_the_history_scan_finds_a_root_commit_whatever_the_config_says(hub, tmp_path):
    hub.pair("alpha")
    repo = new_repo(tmp_path / "repo")
    git(repo, "config", "log.showRoot", "false")
    git(repo, "checkout", "-q", "--orphan", "fresh")
    commit_secret(repo)
    git(repo, "rm", "-q", "deploy.pem")
    git(repo, "commit", "-q", "--no-verify", "-m", "delete it")
    write_manifest(repo, "demo", {"test": [[PYTHON, "-V"]]})
    r = hub.cli("run", "alpha", "--repo", str(repo), "test")
    assert (r.returncode, r.stderr.strip()) == (2, "snapshot_secret_risk:deploy.pem")


def test_ac24_an_allowed_name_in_the_history_passes(hub, dirty):
    hub.pair("alpha")
    commit_secret(dirty, ".env.example")
    assert run_task(hub, "alpha", dirty, "test")["tree"]


def test_ac24_a_secret_on_a_branch_the_bundle_leaves_out_passes(hub, dirty):
    hub.pair("alpha")
    git(dirty, "checkout", "-q", "-b", "elsewhere")
    commit_secret(dirty)
    git(dirty, "checkout", "-q", "-")
    assert run_task(hub, "alpha", dirty, "test")["tree"]


# AC-25: end to end


def test_ac25_a_command_sees_uncommitted_files_and_its_log_comes_back(rig, tmp_path):
    hub, _, _ = rig
    repo = new_repo(tmp_path / "repo")
    marker = fleet.new_id()
    (repo / "marker.txt").write_text(marker, encoding="utf-8")
    write_manifest(repo, "e2e", {"show": [[PYTHON, "-c", "print(open('marker.txt').read())"]]})
    run = run_task(hub, "alpha", repo, "show")
    log = tmp_path / "out.log"
    code, result = wait_task(hub, run["task"], log)
    assert code == 0
    assert (result["state"], result["reason"], result["exit_code"]) == ("completed", None, 0)
    assert result["tree"] == run["tree"]
    assert marker in log.read_text(encoding="utf-8")
    assert result["log"] == hashlib.sha256(log.read_bytes()).hexdigest()
    assert result["duration_s"] >= 0


def test_ac25_a_nonzero_exit_fails_and_stops_at_that_argv(rig, tmp_path):
    hub, _, _ = rig
    repo = new_repo(tmp_path / "repo")
    first, after = tmp_path / "first", tmp_path / "after"
    write_manifest(
        repo, "e2e-fail",
        {"test": [writer(first), [PYTHON, "-c", "import sys; print('boom'); sys.exit(3)"], writer(after)]},
    )
    run = run_task(hub, "alpha", repo, "test")
    log = tmp_path / "out.log"
    code, result = wait_task(hub, run["task"], log)
    assert code == 1
    assert (result["state"], result["reason"], result["exit_code"]) == ("failed", "nonzero_exit", 3)
    assert "boom" in log.read_text(encoding="utf-8")
    assert first.exists()
    assert not after.exists()


def test_ac25_a_long_log_keeps_its_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "MAX_BLOB_BYTES", 4)
    path = tmp_path / "x.log"
    path.write_bytes(b"0123456789")
    assert fleet.log_tail(path) == b"6789"


def test_ac14_a_member_killed_during_a_run_reports_member_restarted(hub, tmp_path):
    member = hub.pair("alpha")
    member.start()
    repo = new_repo(tmp_path / "repo")
    write_manifest(repo, "killed", {"test": [[PYTHON, "-c", "import time; time.sleep(4)"]]})
    run = run_task(hub, "alpha", repo, "test")
    client = hub.client()
    wait_until(lambda: fleet.api(client, "GET", f"/v1/tasks/{run['task']}")["state"] == "working", timeout=30)
    member.stop()
    member.start()
    code, result = wait_task(hub, run["task"])
    assert code == 1
    assert (result["state"], result["reason"]) == ("failed", "member_restarted")


# AC-26: a refused task runs nothing


def assert_rejected(hub, task: str, reason: str, *sentinels: Path) -> None:
    code, result = wait_task(hub, task)
    assert code == 3, result
    assert (result["state"], result["reason"]) == ("rejected", reason)
    for sentinel in sentinels:
        assert not sentinel.exists()


def test_ac26_an_unknown_command(rig, tmp_path):
    hub, _, _ = rig
    repo = new_repo(tmp_path / "repo")
    sentinel = tmp_path / "s"
    write_manifest(repo, "r-unknown", {"test": [writer(sentinel)]})
    assert_rejected(hub, run_task(hub, "alpha", repo, "nope")["task"], "unknown_command", sentinel)


def test_ac26_a_snapshot_with_no_manifest(rig, tmp_path):
    hub, _, _ = rig
    repo = new_repo(tmp_path / "repo")
    assert_rejected(hub, post_snapshot(hub, "alpha", repo, project="r-none"), "no_manifest")


def test_ac26_a_bad_manifest_in_the_snapshot(rig, tmp_path):
    hub, _, _ = rig
    repo = new_repo(tmp_path / "repo")
    (repo / ".agent").mkdir()
    (repo / ".agent" / "fleet.json").write_text("{", encoding="utf-8")
    assert_rejected(hub, post_snapshot(hub, "alpha", repo, project="r-badjson"), "bad_manifest:bad_json")


def test_ac26_a_wrong_tree(rig, tmp_path):
    hub, _, _ = rig
    repo = new_repo(tmp_path / "repo")
    sentinel = tmp_path / "s"
    write_manifest(repo, "r-tree", {"test": [writer(sentinel)]})
    task = post_snapshot(hub, "alpha", repo, project="r-tree", tree="0" * 40)
    assert_rejected(hub, task, "tree_mismatch", sentinel)


def test_ac26_a_corrupt_bundle(rig, tmp_path):
    hub, _, _ = rig
    repo = new_repo(tmp_path / "repo")
    sentinel = tmp_path / "s"
    write_manifest(repo, "r-bundle", {"test": [writer(sentinel)]})
    task = post_snapshot(hub, "alpha", repo, project="r-bundle", data=b"not a bundle " + fleet.new_id().encode())
    assert_rejected(hub, task, "bundle_bad", sentinel)


def test_ac26_a_project_that_differs_from_the_slots_manifest(rig, tmp_path):
    hub, _, _ = rig
    repo = new_repo(tmp_path / "repo")
    sentinel = tmp_path / "s"
    write_manifest(repo, "r-real", {"test": [writer(sentinel)]})
    task = post_snapshot(hub, "alpha", repo, project="r-other")
    assert_rejected(hub, task, "project_mismatch", sentinel)


def test_ac26_an_absent_tool_runs_no_step(rig, tmp_path):
    hub, _, _ = rig
    repo = new_repo(tmp_path / "repo")
    sentinel = tmp_path / "s"
    write_manifest(repo, "r-tool", {"test": [writer(sentinel), ["no-such-tool-x", "-V"]]})
    task = run_task(hub, "alpha", repo, "test")["task"]
    assert_rejected(hub, task, "tool_missing:no-such-tool-x", sentinel)


def test_ac26_a_forbidden_tool_in_a_directly_posted_task_never_runs(rig, tmp_path):
    hub, _, shims = rig
    repo = new_repo(tmp_path / "repo")
    write_manifest(repo, "r-forbid", {"test": [["gh", "auth", "status"]]})
    task = post_snapshot(hub, "alpha", repo, project="r-forbid")
    assert_rejected(hub, task, "bad_manifest:forbidden_command:gh", shims / "called.txt")


def test_ac26_oracle_the_gh_shim_records_a_call(rig):
    _, _, shims = rig
    probe = shims.parent / "probe"
    probe.mkdir()
    shutil.copy(shims / "gh.cmd", probe / "gh.cmd")
    subprocess.run([str(probe / "gh.cmd")], check=True)
    assert (probe / "called.txt").exists()


# AC-27: blob integrity and access


def run_envelope(member: str, bundle: str) -> dict:
    return new_envelope(
        "orchestrator", member, "run",
        body={"project": "demo", "command": "test", "timeout_s": 60},
        refs={"commit": "a" * 40, "tree": "b" * 40, "bundle": bundle},
    )


def test_ac27_a_blob_round_trip(hub):
    data = b"some bytes"
    sha = hashlib.sha256(data).hexdigest()
    assert fleet.hub_request(hub.client(), "PUT", f"/v1/blobs/{sha}", raw=data)[0] == 200
    assert blob_files(hub) == [sha]
    assert fleet.hub_request(hub.client(), "GET", f"/v1/blobs/{sha}") == (200, data)
    assert fleet.hub_request(hub.client(), "PUT", f"/v1/blobs/{sha}", raw=data)[0] == 200
    assert blob_files(hub) == [sha]


def test_ac27_content_that_does_not_match_the_hash(hub):
    status, reply = fleet.hub_request(hub.client(), "PUT", f"/v1/blobs/{'a' * 64}", raw=b"other")
    assert (status, reply["error"]) == (422, "blob_hash_mismatch")
    assert blob_files(hub) == []


def test_ac27_an_oversized_blob(hub):
    # The header alone must refuse it: the test does not upload the limit.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    head = (
        f"PUT /v1/blobs/{'a' * 64} HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {hub.client().key}\r\n"
        f"Content-Length: {fleet.MAX_BLOB_BYTES + 1}\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", hub.port), 10) as raw, ctx.wrap_socket(raw) as tls:
        tls.sendall(head.encode("ascii"))
        reply = tls.recv(4096).decode("ascii", "replace")
    assert reply.split(" ")[1] == "413", reply
    assert blob_files(hub) == []


def test_ac27_a_task_naming_an_absent_bundle(hub):
    hub.pair("alpha")
    before = hub.rows()
    status, reply = hub.request("POST", "/v1/tasks", run_envelope("alpha", "c" * 64), key=hub.client().key)
    assert (status, reply["error"]) == (422, "missing_blob")
    assert hub.rows() == before


@pytest.mark.parametrize(
    "body_over, refs_over, code",
    [
        ({"extra": 1}, {}, "unknown_field:extra"),
        ({"project": "../x"}, {}, "bad_field:project"),
        ({"command": "a b"}, {}, "bad_field:command"),
        ({"timeout_s": 0}, {}, "bad_field:timeout_s"),
        ({"timeout_s": 86401}, {}, "bad_field:timeout_s"),
        ({"timeout_s": True}, {}, "bad_field:timeout_s"),
        ({"timeout_s": 1.5}, {}, "bad_field:timeout_s"),
        ({}, {"extra": 1}, "unknown_field:extra"),
        ({}, {"commit": "xyz"}, "bad_field:commit"),
        ({}, {"tree": "a" * 39}, "bad_field:tree"),
        ({}, {"bundle": "../../hub.key"}, "bad_field:bundle"),
    ],
)
def test_ac27_a_run_task_with_a_bad_shape(hub, body_over, refs_over, code):
    hub.pair("alpha")
    data = b"bundle"
    sha = hashlib.sha256(data).hexdigest()
    fleet.api(hub.client(), "PUT", f"/v1/blobs/{sha}", raw=data)
    before = hub.rows()
    env = run_envelope("alpha", sha)
    env["body"].update(body_over)
    env["refs"].update(refs_over)
    status, reply = hub.request("POST", "/v1/tasks", env, key=hub.client().key)
    assert (status, reply["error"]) == (400, code)
    assert hub.rows() == before


def test_ac27_a_member_reads_only_blobs_tied_to_its_tasks(hub):
    alpha, beta = hub.pair("alpha"), hub.pair("beta")
    data = b"bundle"
    sha = hashlib.sha256(data).hexdigest()
    fleet.api(hub.client(), "PUT", f"/v1/blobs/{sha}", raw=data)
    status, reply = fleet.hub_request(alpha.client(), "GET", f"/v1/blobs/{sha}")
    assert (status, reply["error"]) == (403, "blob_not_yours")
    fleet.api(hub.client(), "POST", "/v1/tasks", run_envelope("alpha", sha))
    assert fleet.hub_request(alpha.client(), "GET", f"/v1/blobs/{sha}") == (200, data)
    status, reply = fleet.hub_request(beta.client(), "GET", f"/v1/blobs/{sha}")
    assert (status, reply["error"]) == (403, "blob_not_yours")


def test_ac27_a_member_may_upload_a_blob(hub):
    alpha = hub.pair("alpha")
    data = b"log"
    sha = hashlib.sha256(data).hexdigest()
    assert fleet.hub_request(alpha.client(), "PUT", f"/v1/blobs/{sha}", raw=data)[0] == 200


def test_ac27_blob_routes_need_a_key(hub):
    client = hub.client()
    client.key = None
    assert fleet.hub_request(client, "GET", f"/v1/blobs/{'a' * 64}")[0] == 401
    assert fleet.hub_request(client, "PUT", f"/v1/blobs/{'a' * 64}", raw=b"x")[0] == 401


@pytest.mark.parametrize("name", ["xyz", "A" * 64, "a" * 63, "..%2f..%2fhub.key"])
def test_ac27_a_non_hex_path(hub, name):
    assert fleet.hub_request(hub.client(), "GET", f"/v1/blobs/{name}")[0] == 404
    assert fleet.hub_request(hub.client(), "PUT", f"/v1/blobs/{name}", raw=b"x")[0] == 404
    assert blob_files(hub) == []


def test_ac27_an_absent_blob_is_not_found_for_the_orchestrator(hub):
    assert fleet.hub_request(hub.client(), "GET", f"/v1/blobs/{'a' * 64}")[0] == 404


# AC-28: slot properties


COMMITTER = (
    "import subprocess\n"
    "open('made.txt', 'w').close()\n"
    "subprocess.run(['git', 'add', '-A'], check=True)\n"
    "subprocess.run(['git', '-c', 'user.name=x', '-c', 'user.email=x@example.invalid', 'commit', '-q',"
    " '--no-verify', '--no-gpg-sign', '-m', 'made in the slot'], check=True)\n"
)


def slot_of(member, project: str) -> Path:
    return member.home / "slots" / project


def test_ac28_a_slot_has_no_remote_or_branch_and_is_cleaned(rig, tmp_path):
    hub, member, _ = rig
    repo = new_repo(tmp_path / "repo")
    seed = (
        "import os\n"
        "os.makedirs('deps', exist_ok=True)\n"
        "open('deps/kept.txt', 'w').close()\n"
        "open('stale.txt', 'w').close()\n"
    )
    write_manifest(repo, "slot", {"seed": [[PYTHON, "-c", seed]], "test": [[PYTHON, "-V"]]})
    assert wait_task(hub, run_task(hub, "alpha", repo, "seed")["task"])[0] == 0
    slot = slot_of(member, "slot")
    assert (slot / "stale.txt").exists()
    assert wait_task(hub, run_task(hub, "alpha", repo, "test")["task"])[0] == 0
    assert git(slot, "remote") == ""
    assert subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=slot, capture_output=True).returncode == 1
    # While HEAD is detached git prints a line for it, which names no branch.
    assert git(slot, "branch", "--list").startswith("* (HEAD detached")
    assert len(git(slot, "branch", "--list").splitlines()) == 1
    assert git(slot, "for-each-ref", "refs/heads") == ""
    assert not (slot / "stale.txt").exists()
    assert (slot / "deps" / "kept.txt").exists()


def test_ac28_a_commit_made_in_the_slot_stays_there_and_is_dropped(rig, tmp_path):
    hub, member, _ = rig
    repo = new_repo(tmp_path / "repo")
    (repo / "committer.py").write_text(COMMITTER, encoding="utf-8")
    write_manifest(repo, "slot-commit", {"commit": [[PYTHON, "committer.py"]], "test": [[PYTHON, "-V"]]})
    head, refs = git(repo, "rev-parse", "HEAD"), git(repo, "for-each-ref")
    run = run_task(hub, "alpha", repo, "commit")
    assert wait_task(hub, run["task"])[0] == 0
    slot = slot_of(member, "slot-commit")
    made = git(slot, "rev-parse", "HEAD")
    assert git(slot, "log", "-1", "--format=%s") == "made in the slot"
    rows = [json.loads(row[-1]) for row in hub.store().dump_messages() if row[2] == run["task"]]
    body = [env for env in rows if env["kind"] == "status"][-1]["body"]
    assert set(body) == RESULT_KEYS
    assert (git(repo, "rev-parse", "HEAD"), git(repo, "for-each-ref")) == (head, refs)
    assert not (repo / "made.txt").exists()
    later = run_task(hub, "alpha", repo, "test")
    assert wait_task(hub, later["task"])[0] == 0
    assert git(slot, "rev-parse", "HEAD^{tree}") == later["tree"]
    assert made not in git(slot, "log", "--format=%H").splitlines()
    assert not (slot / "made.txt").exists()


# AC-29: timeout and heartbeats


SPAWNER = (
    "import subprocess, sys\n"
    "code = 'import sys, time; time.sleep(8); open(sys.argv[1], \"w\").close()'\n"
    "subprocess.Popen([sys.executable, '-c', code, sys.argv[1]]).wait()\n"
)


def test_ac29_a_timeout_kills_the_whole_tree(rig, tmp_path):
    hub, _, _ = rig
    repo = new_repo(tmp_path / "repo")
    sentinel = tmp_path / "s"
    (repo / "spawner.py").write_text(SPAWNER, encoding="utf-8")
    write_manifest(repo, "timeout", {"test": [[PYTHON, "spawner.py", str(sentinel)]]})
    started = time.monotonic()
    run = run_task(hub, "alpha", repo, "test", "--timeout", "2")
    code, result = wait_task(hub, run["task"])
    assert code == 1
    assert (result["state"], result["reason"]) == ("failed", "timeout")
    assert result["log"] and result["tree"] == run["tree"]
    time.sleep(max(0, started + 10 - time.monotonic()))
    assert not sentinel.exists()


def test_ac29_oracle_the_child_writes_its_sentinel_when_not_killed(tmp_path):
    (tmp_path / "spawner.py").write_text(SPAWNER, encoding="utf-8")
    sentinel = tmp_path / "s"
    subprocess.run([sys.executable, "spawner.py", str(sentinel)], cwd=tmp_path, check=True, timeout=30)
    assert sentinel.exists()


def test_ac29_a_failed_tree_kill_is_written_to_the_log(tmp_path, monkeypatch):
    def denied(argv, **_):
        assert argv[0] == "taskkill"
        return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"ERROR: Access denied.\r\n")

    monkeypatch.setattr(fleet.subprocess, "run", denied)
    log = tmp_path / "run.log"
    step = [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(60)"]
    code, reason = fleet.run_steps([step], tmp_path, log, 5)
    assert reason == "timeout" and code != 0
    text = log.read_text(encoding="utf-8")
    assert "started" in text
    assert "taskkill exit 1" in text and "may survive" in text and "ERROR: Access denied." in text


def test_ac29_a_clean_tree_kill_adds_nothing_to_the_log(tmp_path):
    log = tmp_path / "run.log"
    step = [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(60)"]
    assert fleet.run_steps([step], tmp_path, log, 5)[1] == "timeout"
    assert "taskkill" not in log.read_text(encoding="utf-8")


def test_ac29_a_member_stays_online_during_a_long_run(tmp_path):
    hub = Hub(tmp_path, offline_after=2)
    hub.start()
    try:
        member = hub.pair("alpha")
        member.start()
        repo = new_repo(tmp_path / "repo")
        write_manifest(repo, "long", {"test": [[PYTHON, "-c", "import time; time.sleep(6)"]]})
        run = run_task(hub, "alpha", repo, "test")
        client = hub.client()
        path = f"/v1/tasks/{run['task']}"
        wait_until(lambda: fleet.api(client, "GET", path)["state"] == "working", timeout=30)
        seen = []
        while True:
            info = fleet.api(client, "GET", path)
            if info["state"] in fleet.TERMINAL_STATES:
                break
            seen.append(info["member_online"])
            time.sleep(0.25)
        assert info["state"] == "completed"
        assert len(seen) >= 8
        assert all(seen)
    finally:
        hub.close()


# AC-30: the environment


def test_ac30_the_environment_reaches_the_child_unchanged(hub, tmp_path):
    member = hub.pair("alpha")
    member.start(env={"FLEET_TEST_SENTINEL": "sentinel-value", "CLAUDECODE": "test-value"})
    wait_online(hub)
    repo = new_repo(tmp_path / "repo")
    show = "import os; print(os.environ['FLEET_TEST_SENTINEL'], os.environ['CLAUDECODE'])"
    write_manifest(repo, "env", {"test": [[PYTHON, "-c", show]]})
    log = tmp_path / "out.log"
    assert wait_task(hub, run_task(hub, "alpha", repo, "test")["task"], log)[0] == 0
    assert "sentinel-value test-value" in log.read_text(encoding="utf-8")
