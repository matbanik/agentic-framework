"""Tests for the install of the usage guard hook and its skill (MEU-979, AC-979.1 to .7).

The guard ``tools/usage_guard.py`` adds one ``PreToolUse`` group to the user
settings (``install --part hook``) and removes it again (``uninstall --part hook``).
No test reads or writes the real user settings or the real guard home. Each test
uses a scratch settings file, a scratch guard home and a scratch user home: an
autouse fixture points ``Path.home`` and the home variables to a scratch folder.
The modules are loaded by path in fixtures, so that a missing name fails each
test and not the collection.

The doc tests (``test_f2p_979_doc_*``) read ``.agent/skills/usage-guard/SKILL.md``
and ``MANIFEST.md``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "tools" / "usage_guard.py"
NOTIFY = REPO_ROOT / "tools" / "agent_notify.py"
HOOK = REPO_ROOT / "tools" / "usage_guard_hook.py"
SKILL = REPO_ROOT / ".agent" / "skills" / "usage-guard" / "SKILL.md"
MANIFEST = REPO_ROOT / "MANIFEST.md"

T0 = 1_800_000_000.0
BASE_PY = Path(getattr(sys, "_base_executable", sys.executable)).as_posix()
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# An example guard home for the hook checks. No test writes to it.
LIVE_HOME = "/opt/agent/usage-guard"
# The hook trusts the interpreter that runs it, so the example interpreter is this one.
LIVE_PY = BASE_PY
# The placeholders of the skill and the example values that the doc tests put in.
PY_WORD = "<python>"
HOME_WORD = "<guard-home>"
RECEIPTS_WORD = "{{RECEIPTS_DIR}}"
PLACEHOLDERS = {PY_WORD: LIVE_PY, HOME_WORD: LIVE_HOME, RECEIPTS_WORD: "/tmp/receipts"}
# The undo line of the skill. The uninstall takes the interpreter of the manifest.
LIVEH_UNDO = "<python> -I <guard-home>/usage_guard.py uninstall --part hook --home <guard-home>"
BACKUP_NAME = re.compile(r"settings-[0-9]{8}T[0-9]{6}Z-(?P<sha8>[0-9a-f]{8})\.json")

API_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)
HOOK_ENV_KEYS = (*API_KEYS, "CLAUDE_CODE_ENTRYPOINT")

SCHTASKS_STUB = '''
"""Recorded schtasks stub: one task, kept as XML in a folder."""
import json, sys
from pathlib import Path

here = Path(__file__).resolve().parent
argv = sys.argv[1:]
task = here / "task.xml"
with open(here / "sched.jsonl", "a", encoding="utf-8") as out:
    out.write(json.dumps(argv) + "\\n")
verb = argv[0].lower()
upper = [a.upper() for a in argv]
if argv[upper.index("/TN") + 1] != "ClaudeUsageGuard":
    sys.exit(1)
if verb == "/query":
    if not task.exists():
        sys.exit(1)
    sys.stdout.buffer.write(task.read_bytes().decode("utf-16").encode("ascii", "replace"))
    sys.exit(0)
if verb == "/create":
    if task.exists() and "/F" not in upper:
        sys.exit(1)
    task.write_bytes(Path(argv[upper.index("/XML") + 1]).read_bytes())
    sys.exit(0)
if verb == "/delete":
    if not task.exists() or "/F" not in upper:
        sys.exit(1)
    task.unlink()
    sys.exit(0)
sys.exit(1)
'''

FOREIGN_ENTRY = {"type": "command", "command": "echo foreign", "timeout": 5}
OTHER_HOME_ENTRY = {
    "type": "command",
    "command": "C:/other/python.exe",
    "args": ["-I", "-c", "pass", "--home", "C:/other/usage-guard"],
}

# Sample settings. Each one is installed and uninstalled to its exact bytes.
SAMPLES = {
    "empty": "{}\n",
    "two_space": (
        '{\n  "model": "opus",\n  "permissions": {\n'
        '    "allow": [\n      "Bash(ls)"\n    ]\n  }\n}\n'
    ),
    "stop_hook": (
        '{\n  "hooks": {\n    "Stop": [\n      {\n        "hooks": [\n'
        '          {\n            "type": "command",\n'
        '            "command": "echo stop"\n          }\n        ]\n'
        '      }\n    ]\n  },\n  "theme": "dark"\n}\n'
    ),
    "foreign_groups": json.dumps(
        {
            "env": {"A": "1"},
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [FOREIGN_ENTRY]},
                    {"matcher": "*", "hooks": [OTHER_HOME_ENTRY]},
                ]
            },
        },
        indent=2,
    )
    + "\n",
    "compact": '{"hooks": {}}',
    "four_space_empty_list": '{\n    "hooks": {\n        "PreToolUse": []\n    }\n}\n',
    "crlf": '{\r\n  "model": "opus",\r\n  "hooks": {\r\n    "Stop": []\r\n  }\r\n}\r\n',
}

INVALID = {
    "list_root": b"[]",
    "duplicate_top": b'{"a": 1, "a": 2}',
    "duplicate_nested": b'{"x": {"a": 1, "a": 2}}',
    "hooks_list": b'{"hooks": []}',
    "pre_object": b'{"hooks": {"PreToolUse": {}}}',
    "group_number": b'{"hooks": {"PreToolUse": [1]}}',
    "group_hooks_object": b'{"hooks": {"PreToolUse": [{"hooks": {}}]}}',
    "not_json": b"not json",
    "bom": b"\xef\xbb\xbf{}",
    "bad_utf8": b'{"a": "\xff"}',
    "nan": b'{"a": NaN}',
    "trailing_text": b"{} x",
}


# ── Harness ─────────────────────────────────────────────────────────────


def _load(name: str, path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """A module loaded from its path and entered in ``sys.modules``."""
    assert path.is_file(), path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def user_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A scratch user home: no test can reach the real user settings."""
    fake = tmp_path / "user home"
    fake.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake)
    for key in ("USERPROFILE", "HOME"):
        monkeypatch.setenv(key, str(fake))
    for key in ("AGENT_NOTIFY", "AGENT_NOTIFY_HOME", "AGENT_NOTIFY_DRY_RUN"):
        monkeypatch.delenv(key, raising=False)
    return fake


@pytest.fixture
def ug(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The guard module, loaded from its path."""
    return _load("usage_guard", GUARD, monkeypatch)


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The hook module, loaded from its path."""
    return _load("usage_guard_hook", HOOK, monkeypatch)


class Rig:
    """A scratch guard home and a scratch settings file. Folder names hold a space."""

    def __init__(
        self, base: Path, ug: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.base = base
        self.ug = ug
        self.capsys = capsys
        self.home = base / "guard home"
        self.home.mkdir()
        self.cfg = base / "user cfg"
        self.cfg.mkdir()
        self.settings = self.cfg / "settings.json"
        self.settings.write_bytes(b"{}\n")
        self.bin = base / "stub bin"
        self.bin.mkdir()
        (self.bin / "schtasks_stub.py").write_text(SCHTASKS_STUB, encoding="utf-8")
        self.source = base / "source"
        self.source.mkdir()
        for path in (GUARD, NOTIFY, HOOK):
            (self.source / path.name).write_bytes(path.read_bytes())
        self.python = base / "py dir" / "python.exe"
        self.python.parent.mkdir()
        self.python.write_bytes(b"")
        self.python.with_name("pythonw.exe").write_bytes(b"")

    def deps(self, mod: ModuleType | None = None, **over: object) -> object:
        """The stubs of the rig, with the scratch settings file."""
        values: dict[str, object] = {
            "account_file": self.base / "claude.json",
            "projects": self.base / "projects",
            "notify_home": self.base / "notify home",
            "schtasks": (sys.executable, str(self.bin / "schtasks_stub.py")),
            "source": self.source,
            "settings": self.settings,
        }
        values.update(over)
        return (self.ug if mod is None else mod).Deps(**values)

    def run(
        self, *argv: str, deps: object = None, mod: ModuleType | None = None
    ) -> tuple[int, str]:
        """Call ``main`` of the guard with the home of the rig and a fixed clock."""
        self.capsys.readouterr()
        code = (self.ug if mod is None else mod).main(
            [*argv, "--home", str(self.home)],
            deps=self.deps(mod) if deps is None else deps,
            now=lambda: T0,
            sleep=lambda _s: None,
        )
        captured = self.capsys.readouterr()
        return code, captured.out + captured.err

    def install(self, *flags: str, python: str | None = None) -> tuple[int, str]:
        program = str(self.python) if python is None else python
        return self.run("install", "--part", "hook", "--python", program, *flags)

    def uninstall(self, *flags: str) -> tuple[int, str]:
        return self.run("uninstall", "--part", "hook", *flags)

    def status(self, deps: object = None) -> dict[str, object]:
        code, out = self.run("status", "--json", deps=deps)
        assert code == 0, out
        return json.loads(out)

    def files(self) -> dict[str, bytes]:
        return {
            p.relative_to(self.home).as_posix(): p.read_bytes()
            for p in sorted(self.home.rglob("*"))
            if p.is_file()
        }

    def backups(self) -> list[Path]:
        return sorted((self.home / "backup").glob("settings-*.json"))

    def doc(self) -> dict[str, object]:
        return json.loads(self.settings.read_bytes().decode("utf-8"))

    def entry(self, python: str | Path | None = None) -> dict[str, object]:
        program = self.python if python is None else python
        return self.ug.hook_entry(self.home, program)


@pytest.fixture
def rig(tmp_path: Path, ug: ModuleType, capsys: pytest.CaptureFixture[str]) -> Rig:
    return Rig(tmp_path, ug, capsys)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _groups(doc: dict[str, object]) -> list[dict[str, object]]:
    hooks = doc.get("hooks")
    assert isinstance(hooks, dict)
    groups = hooks.get("PreToolUse")
    assert isinstance(groups, list)
    return groups


def _ours(rig: Rig, doc: dict[str, object]) -> list[dict[str, object]]:
    """The entries of the rig's home in the settings."""
    hooks = doc.get("hooks")
    if not isinstance(hooks, dict):
        return []
    found = []
    for group in hooks.get("PreToolUse", []):
        for item in group.get("hooks", []):
            args = item.get("args")
            if isinstance(args, list) and args[-2:] == ["--home", rig.home.as_posix()]:
                found.append(item)
    return found


def _expected(text: str, entry: dict[str, object]) -> dict[str, object]:
    """The old settings with the one new group at the end."""
    doc = json.loads(text)
    hooks = doc.setdefault("hooks", {})
    hooks.setdefault("PreToolUse", []).append({"matcher": "*", "hooks": [entry]})
    return doc


def _pause(rig: Rig) -> Path:
    data = {
        "schema": "usage-guard-pause/1",
        "origin": "user",
        "started_at": T0 - 10,
        "end_at": T0 + 3600,
        "windows": [],
    }
    path = rig.home / "pause.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _only_backups(rig: Rig) -> bool:
    return all(name.startswith("backup/") for name in rig.files())


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in HOOK_ENV_KEYS}


def _launch(entry: dict[str, object]) -> subprocess.CompletedProcess[str]:
    """Run the hook entry of the settings as a process, with an empty tool call."""
    command = entry["command"]
    args = entry["args"]
    assert isinstance(command, str) and isinstance(args, list)
    return subprocess.run(
        [command, *[str(a) for a in args]],
        input="{}",
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
        creationflags=NO_WINDOW,
        check=False,
    )


# ── AC-979.1: the settings edit ─────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_f2p_979_01_install_adds_one_group(rig: Rig, name: str) -> None:
    text = SAMPLES[name]
    raw = text.encode("utf-8")
    rig.settings.write_bytes(raw)
    code, out = rig.install()
    assert code == 0, out
    assert "installed: hook" in out
    new = rig.settings.read_bytes()
    assert json.dumps(rig.doc()) == json.dumps(_expected(text, rig.entry()))
    assert _groups(rig.doc())[-1] == {"matcher": "*", "hooks": [rig.entry()]}
    if b"\r\n" in raw:
        assert new.count(b"\n") == new.count(b"\r\n")
    else:
        assert b"\r" not in new
    backups = rig.backups()
    assert len(backups) == 1
    match = BACKUP_NAME.fullmatch(backups[0].name)
    assert match is not None, backups[0].name
    assert match["sha8"] == _sha(raw)[:8]
    assert backups[0].read_bytes() == raw


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_f2p_979_01_second_install_changes_nothing(rig: Rig, name: str) -> None:
    rig.settings.write_bytes(SAMPLES[name].encode("utf-8"))
    assert rig.install()[0] == 0
    before = (rig.files(), rig.settings.read_bytes())
    code, out = rig.install()
    assert code == 0, out
    assert (rig.files(), rig.settings.read_bytes()) == before
    assert len(rig.backups()) == 1


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_f2p_979_01_uninstall_gives_the_old_bytes(rig: Rig, name: str) -> None:
    raw = SAMPLES[name].encode("utf-8")
    rig.settings.write_bytes(raw)
    assert rig.install()[0] == 0
    code, out = rig.uninstall()
    assert code == 0, out
    assert rig.settings.read_bytes() == raw
    assert _only_backups(rig)


@pytest.mark.parametrize("name", sorted(INVALID))
def test_f2p_979_01_invalid_settings_are_refused(rig: Rig, name: str) -> None:
    raw = INVALID[name]
    rig.settings.write_bytes(raw)
    code, out = rig.install()
    assert code == 1
    assert "settings_invalid" in out
    assert rig.settings.read_bytes() == raw
    assert rig.files() == {}
    code, out = rig.uninstall()
    assert code == 1
    assert "settings_invalid" in out
    assert rig.settings.read_bytes() == raw


def test_f2p_979_01_linked_settings_are_refused(rig: Rig) -> None:
    target = rig.cfg / "real.json"
    target.write_bytes(b"{}\n")
    rig.settings.unlink()
    os.symlink(target, rig.settings)
    code, out = rig.install()
    assert code == 1
    assert "settings_link" in out
    assert rig.settings.is_symlink()
    assert target.read_bytes() == b"{}\n"
    assert rig.files() == {}
    code, out = rig.uninstall()
    assert code == 1
    assert "settings_link" in out
    assert target.read_bytes() == b"{}\n"


def test_f2p_979_01_missing_settings_are_refused(rig: Rig) -> None:
    rig.settings.unlink()
    code, out = rig.install()
    assert code == 1
    assert "settings_missing" in out
    assert not rig.settings.exists()
    assert rig.files() == {}


def test_f2p_979_01_changed_settings_are_refused(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = b'{\n  "planted": true\n}\n'
    real = os.replace

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        real(src, dst)
        if Path(dst).parent == rig.home / "backup":
            rig.settings.write_bytes(planted)

    monkeypatch.setattr(os, "replace", spy)
    code, out = rig.install()
    monkeypatch.setattr(os, "replace", real)
    assert code == 1
    assert "settings_changed" in out
    assert rig.settings.read_bytes() == planted
    assert not (rig.home / "manifest.json").exists()
    assert not (rig.home / "usage_guard_hook.py").exists()
    assert _only_backups(rig)


def test_f2p_979_01_other_entry_of_this_home_is_refused(rig: Rig) -> None:
    assert rig.install()[0] == 0
    before = rig.settings.read_bytes()
    other = rig.base / "other py" / "python.exe"
    other.parent.mkdir()
    other.write_bytes(b"")
    code, out = rig.install(python=str(other))
    assert code == 1
    assert "hook_differs" in out
    assert rig.settings.read_bytes() == before


def test_f2p_979_01_foreign_hook_file_is_refused(rig: Rig) -> None:
    (rig.home / "usage_guard_hook.py").write_bytes(b"mine")
    code, out = rig.install()
    assert code == 1
    assert "file_foreign" in out
    assert rig.settings.read_bytes() == b"{}\n"
    assert rig.files() == {"usage_guard_hook.py": b"mine"}


# ── AC-979.2: the uninstall ─────────────────────────────────────────────


def test_f2p_979_02_uninstall_ends_a_pause(rig: Rig) -> None:
    assert rig.install()[0] == 0
    pause = _pause(rig)
    code, out = rig.uninstall()
    assert code == 0, out
    assert not pause.exists()


def test_f2p_979_02_uninstall_keeps_foreign_hooks(rig: Rig) -> None:
    rig.settings.write_bytes(SAMPLES["foreign_groups"].encode("utf-8"))
    assert rig.install()[0] == 0
    doc = rig.doc()
    _groups(doc)[-1]["hooks"] = [rig.entry(), FOREIGN_ENTRY]
    rig.settings.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    code, out = rig.uninstall()
    assert code == 0, out
    groups = _groups(rig.doc())
    assert groups == [
        {"matcher": "Bash", "hooks": [FOREIGN_ENTRY]},
        {"matcher": "*", "hooks": [OTHER_HOME_ENTRY]},
        {"matcher": "*", "hooks": [FOREIGN_ENTRY]},
    ]
    assert _ours(rig, rig.doc()) == []


def test_f2p_979_02_uninstall_says_uninstalled(rig: Rig) -> None:
    """The uninstall names the part. The framework has no enroll step to report."""
    assert rig.install()[0] == 0
    code, out = rig.uninstall()
    assert code == 0, out
    assert "uninstalled: hook" in out
    assert "enroll" not in out


def test_f2p_979_02_uninstall_without_an_entry_changes_nothing(rig: Rig) -> None:
    raw = SAMPLES["foreign_groups"].encode("utf-8")
    rig.settings.write_bytes(raw)
    code, out = rig.uninstall()
    assert code == 0, out
    assert rig.settings.read_bytes() == raw
    assert rig.files() == {}


def test_f2p_979_02_hook_part_alone_leaves_only_backups(rig: Rig) -> None:
    assert rig.install()[0] == 0
    names = set(rig.files())
    assert {"usage_guard.py", "agent_notify.py", "usage_guard_hook.py"} <= names
    assert "manifest.json" in names
    assert rig.uninstall()[0] == 0
    assert _only_backups(rig)
    assert len(rig.backups()) >= 1


def test_f2p_979_02_install_without_part_does_both(rig: Rig) -> None:
    code, out = rig.run("install", "--python", str(rig.python))
    assert code == 0, out
    assert "installed: task" in out and "installed: hook" in out
    data = json.loads((rig.home / "manifest.json").read_text(encoding="utf-8"))
    assert data["parts"] == ["task", "hook"]
    assert (rig.bin / "task.xml").exists()
    assert len(_ours(rig, rig.doc())) == 1
    code, out = rig.run("uninstall")
    assert code == 0, out
    assert rig.settings.read_bytes() == b"{}\n"
    assert not (rig.bin / "task.xml").exists()
    assert _only_backups(rig)


def test_f2p_979_02_task_uninstall_then_liveh_undo(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = SAMPLES["two_space"].encode("utf-8")
    rig.settings.write_bytes(raw)
    code, out = rig.run("install", "--python", str(rig.python))
    assert code == 0, out
    code, out = rig.run("uninstall", "--part", "task")
    assert code == 0, out
    data = json.loads((rig.home / "manifest.json").read_text(encoding="utf-8"))
    assert data["parts"] == ["hook"]
    assert len(_ours(rig, rig.doc())) == 1
    installed = _load("usage_guard", rig.home / "usage_guard.py", monkeypatch)
    argv: list[str] = [str(word) for word in LIVEH_UNDO.split()[3:]]
    assert argv[-1] == HOME_WORD
    argv[-1] = str(rig.home)
    rig.capsys.readouterr()
    code = installed.main(
        argv, deps=rig.deps(installed), now=lambda: T0, sleep=lambda _s: None
    )
    out = rig.capsys.readouterr().out
    assert code == 0, out
    assert rig.settings.read_bytes() == raw
    assert _only_backups(rig)


def test_f2p_979_02_hook_uninstall_first_keeps_the_task(rig: Rig) -> None:
    code, out = rig.run("install", "--python", str(rig.python))
    assert code == 0, out
    code, out = rig.uninstall()
    assert code == 0, out
    assert set(rig.files()) - {p for p in rig.files() if p.startswith("backup/")} == {
        "usage_guard.py",
        "agent_notify.py",
        "manifest.json",
    }
    data = json.loads((rig.home / "manifest.json").read_text(encoding="utf-8"))
    assert data["parts"] == ["task"]
    assert (rig.bin / "task.xml").exists()
    assert rig.status()["task"] == "ready"
    assert rig.settings.read_bytes() == b"{}\n"


# ── AC-979.3: the installed entry runs ──────────────────────────────────


@pytest.mark.parametrize(
    "script",
    [
        "present",
        "missing",
        "syntax",
        "raises",
        "exit_3",
    ],
)
def test_f2p_979_03_installed_entry_runs_and_exits_0(rig: Rig, script: str) -> None:
    code, out = rig.install(python=BASE_PY)
    assert code == 0, out
    found = _ours(rig, rig.doc())
    assert len(found) == 1
    target = rig.home / "usage_guard_hook.py"
    broken = {
        "syntax": b"def (\n",
        "raises": b"raise RuntimeError('broken')\n",
        "exit_3": b"import sys\nsys.exit(3)\n",
    }
    if script == "missing":
        target.unlink()
    elif script in broken:
        target.write_bytes(broken[script])
    proc = _launch(found[0])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


# ── AC-979.4: install writes only where it must ─────────────────────────


def _tree(root: Path, skip: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and skip not in p.parents
    }


def test_f2p_979_04_install_writes_only_home_and_settings(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = SAMPLES["stop_hook"].encode("utf-8")
    rig.settings.write_bytes(raw)
    before = _tree(rig.base, rig.home)
    real = os.replace
    seen: list[tuple[Path, bool]] = []

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        backed = any(p.read_bytes() == raw for p in rig.backups())
        seen.append((Path(dst), backed))
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    code, out = rig.install()
    monkeypatch.setattr(os, "replace", real)
    assert code == 0, out
    after = _tree(rig.base, rig.home)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed == {"user cfg/settings.json"}
    assert seen
    for dst, backed in seen:
        assert dst == rig.settings or rig.home in dst.parents, dst
        if dst == rig.settings:
            assert backed
    assert sum(1 for dst, _b in seen if dst == rig.settings) == 1


def test_f2p_979_04_failed_edit_keeps_the_settings(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = SAMPLES["two_space"].encode("utf-8")
    rig.settings.write_bytes(raw)
    real = os.replace

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst) == rig.settings:
            raise OSError("planted")
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    code, out = rig.install()
    monkeypatch.setattr(os, "replace", real)
    assert code == 1
    assert "install_write" in out
    assert rig.settings.read_bytes() == raw
    assert sorted(p.name for p in rig.cfg.iterdir()) == ["settings.json"]
    assert not (rig.home / "manifest.json").exists()
    assert _only_backups(rig)


def test_f2p_979_04_settings_option(rig: Rig) -> None:
    other = rig.cfg / "other settings.json"
    other.write_bytes(b"{}\n")
    deps = rig.deps(settings=None)
    code, out = rig.run(
        "install",
        "--part",
        "hook",
        "--python",
        str(rig.python),
        "--settings",
        str(other),
        deps=deps,
    )
    assert code == 0, out
    assert rig.settings.read_bytes() == b"{}\n"
    assert len(_ours(rig, json.loads(other.read_text(encoding="utf-8")))) == 1
    code, out = rig.run(
        "uninstall", "--part", "hook", "--settings", str(other), deps=deps
    )
    assert code == 0, out
    assert other.read_bytes() == b"{}\n"


def test_f2p_979_04_no_settings_path_is_refused(rig: Rig) -> None:
    code, out = rig.run(
        "install",
        "--part",
        "hook",
        "--python",
        str(rig.python),
        deps=rig.deps(settings=None),
    )
    assert code == 1
    assert "no_settings" in out
    assert rig.files() == {}


@pytest.mark.parametrize(
    "argv",
    [
        ["install", "--part", "both"],
        ["install", "--part", "hook", "--settings", "relative/settings.json"],
        ["uninstall", "--part", "hook", "--settings", "relative/settings.json"],
        ["install", "--part", "hook", "--setting", "C:/x.json"],
    ],
)
def test_f2p_979_04_bad_arguments_exit_2(rig: Rig, argv: list[str]) -> None:
    rig.deps()
    with pytest.raises(SystemExit) as caught:
        rig.ug.main([*argv, "--home", str(rig.home)], deps=rig.deps(), now=lambda: T0)
    assert caught.value.code == 2
    assert rig.files() == {}
    assert rig.settings.read_bytes() == b"{}\n"


def test_f2p_979_04_default_settings_path(rig: Rig, user_home: Path) -> None:
    rig.deps()
    settings = user_home / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_bytes(b"{}\n")
    rig.capsys.readouterr()
    argv = ["install", "--part", "hook", "--python", str(rig.python)]
    code = rig.ug.main(
        [*argv, "--home", str(rig.home)], now=lambda: T0, sleep=lambda _s: None
    )
    out = rig.capsys.readouterr().out
    assert code == 0, out
    doc = json.loads(settings.read_text(encoding="utf-8"))
    assert len(_ours(rig, doc)) == 1
    assert rig.settings.read_bytes() == b"{}\n"
    code = rig.ug.main(
        ["uninstall", "--part", "hook", "--home", str(rig.home)],
        now=lambda: T0,
        sleep=lambda _s: None,
    )
    assert code == 0
    assert settings.read_bytes() == b"{}\n"


# ── AC-979.5: the hook state in the status ──────────────────────────────


def test_f2p_979_05_hook_states(rig: Rig) -> None:
    assert rig.status()["hook"] == "absent"
    assert rig.install()[0] == 0
    assert rig.status()["hook"] == "installed"
    code, out = rig.run("status")
    assert code == 0
    assert "hook: installed" in out.splitlines()
    doc = rig.doc()
    doc["disableAllHooks"] = True
    rig.settings.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    assert rig.status()["hook"] == "disabled"


def test_f2p_979_05_changed_hook_file_is_drift(rig: Rig) -> None:
    assert rig.install()[0] == 0
    (rig.home / "usage_guard_hook.py").write_bytes(b"# changed\n")
    assert rig.status()["hook"] == "drift"


def test_f2p_979_05_lost_entry_is_drift(rig: Rig) -> None:
    assert rig.install()[0] == 0
    rig.settings.write_bytes(b"{}\n")
    assert rig.status()["hook"] == "drift"


def test_f2p_979_05_entry_without_install_is_drift(rig: Rig) -> None:
    doc = _expected("{}", rig.entry())
    rig.settings.write_text(json.dumps(doc), encoding="utf-8")
    assert rig.status()["hook"] == "drift"


def test_f2p_979_05_unknown_settings(rig: Rig) -> None:
    assert rig.status(deps=rig.deps(settings=None))["hook"] == "unknown"
    rig.settings.write_bytes(b"[")
    assert rig.status()["hook"] == "unknown"
    assert rig.files() == {}


def test_f2p_979_05_status_writes_nothing(rig: Rig) -> None:
    assert rig.install()[0] == 0
    before = (rig.files(), rig.settings.read_bytes())
    rig.status()
    rig.run("status")
    assert (rig.files(), rig.settings.read_bytes()) == before


def test_f2p_979_05_install_parts(ug: ModuleType) -> None:
    assert ug.INSTALL_PARTS == ("task", "hook")
    assert ug.Deps().settings is None


# ── The hook entry (unchanged from MEU-978) ─────────────────────────────


def test_p2p_979_hook_entry_exec_form(ug: ModuleType) -> None:
    home = Path("C:/x/guard home")
    entry = ug.hook_entry(home, Path("C:/py/python.exe"))
    assert entry == {
        "type": "command",
        "command": "C:/py/python.exe",
        "args": ["-I", "-S", "-c", ug.LAUNCHER, "--home", "C:/x/guard home"],
        "timeout": ug.HOOK_TIMEOUT_S,
    }
    assert ug.HOOK_TIMEOUT_S == ug.PAUSE_MAX_S


@pytest.mark.parametrize("script", [None, b"def (\n"])
def test_p2p_979_launcher_fails_open(
    ug: ModuleType, tmp_path: Path, script: bytes | None
) -> None:
    box = tmp_path / "box home"
    box.mkdir()
    if script is not None:
        (box / "usage_guard_hook.py").write_bytes(script)
    proc = _launch(ug.hook_entry(box, BASE_PY))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_f2p_979_skill_references_resolve() -> None:
    """Each path of the skill that starts with ``.agent/`` or ``tools/`` is a file.

    This is the reference rule of the package check, for the skill file only.
    """
    spans = re.findall(r"`([^`\n]+)`", _skill_text())
    refs = sorted(
        {s for s in spans if " " not in s and s.startswith((".agent/", "tools/"))}
    )
    assert ".agent/skills/usage-guard/SKILL.md" in refs
    missing = [ref for ref in refs if not (REPO_ROOT / ref).is_file()]
    assert missing == []


# ── AC-979.6: the skill ─────────────────────────────────────────────────


def _skill_text() -> str:
    assert SKILL.is_file(), SKILL
    return SKILL.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> list[str]:
    """The lines of one ``## `` section, without its heading."""
    lines = text.splitlines()
    assert heading in lines, heading
    start = lines.index(heading) + 1
    end = next(
        (i for i in range(start, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def _fenced(lines: list[str]) -> list[str]:
    """The lines inside the fenced code blocks."""
    inside = False
    found: list[str] = []
    for line in lines:
        if line.strip().startswith("```"):
            inside = not inside
            continue
        if inside:
            found.append(line)
    return found


def _shell_call(tool: str, command: str) -> dict[str, object]:
    return {"tool_name": tool, "tool_input": {"command": command}}


def _filled(command: str) -> str:
    """A command of the skill with the example values in place of the placeholders."""
    for word, value in PLACEHOLDERS.items():
        command = command.replace(word, value)
    return command


def test_f2p_979_doc_skill_frontmatter_and_requests() -> None:
    text = _skill_text()
    assert text.startswith("---\n")
    head = text.split("---\n")[1]
    assert "name: usage-guard" in head.splitlines()
    assert any(line.startswith("description: ") for line in head.splitlines())
    for request in ("show usage", "pause now", "resume", "is the guard healthy"):
        assert f'"{request}"' in text, request


def test_f2p_979_doc_skill_names_each_placeholder() -> None:
    text = _skill_text()
    for word in PLACEHOLDERS:
        assert f"`{word}`" in text, word
    commands = [line for line in _fenced(text.splitlines()) if "usage_guard" in line]
    assert commands
    for command in commands:
        assert PY_WORD in command and HOME_WORD in command, command


def test_f2p_979_doc_skill_rules() -> None:
    lines = _section(_skill_text(), "## Rules")

    def has(*words: str) -> bool:
        return any(all(w in line for w in words) for line in lines)

    assert has("pause file", "by hand")
    assert has("resume", "direct", "user")
    assert has("only", "percent", "age")


def test_f2p_979_doc_pass_forms_run_in_a_pause(hook: ModuleType) -> None:
    commands = [
        line
        for line in _fenced(_section(_skill_text(), "## Commands that run in a pause"))
        if "usage_guard.py" in line
    ]
    assert commands
    for command in commands:
        for tool in ("Bash", "PowerShell"):
            call = _shell_call(tool, _filled(command))
            assert hook.passes(call, LIVE_HOME), (tool, command)
    verbs: set[str] = set()
    for command in commands:
        verb = re.search(r"usage_guard\.py (\w+)", command)
        assert verb is not None, command
        verbs.add(verb[1])
    assert verbs == set(hook.GUARD_VERBS)
    assert any(c.endswith(" 2>&1") for c in commands)
    assert any(" *> " in c for c in commands)


def test_f2p_979_doc_skill_calls_pass(hook: ModuleType) -> None:
    text = _skill_text()
    assert hook.SKILL_FILE in text
    assert f"`{hook.SKILL_NAME}`" in text
    read = {"tool_name": "Read", "tool_input": {"file_path": SKILL.as_posix()}}
    assert hook.passes(read, LIVE_HOME)
    skill = {"tool_name": "Skill", "tool_input": {"skill": hook.SKILL_NAME}}
    assert hook.passes(skill, LIVE_HOME)


def test_f2p_979_doc_install_forms_never_pass(hook: ModuleType) -> None:
    text = _skill_text()
    forms = [
        line
        for line in _fenced(text.splitlines())
        if re.search(r"usage_guard\.py (install|uninstall)\b", line)
    ]
    assert any("install --part hook" in f for f in forms)
    assert any("uninstall --part hook" in f for f in forms)
    for form in forms:
        for tool in ("Bash", "PowerShell"):
            assert not hook.passes(_shell_call(tool, _filled(form)), LIVE_HOME), form


def test_f2p_979_doc_install_forms_name_python_and_home() -> None:
    forms = [
        line
        for line in _fenced(_skill_text().splitlines())
        if re.search(r"usage_guard\.py install\b", line)
    ]
    assert forms
    for form in forms:
        assert f"--python {PY_WORD}" in form, form
        assert f"--home {HOME_WORD}" in form, form


def test_f2p_979_doc_terminal_commands_and_undo(hook: ModuleType) -> None:
    text = _skill_text()
    terminal = _fenced(_section(text, "## Terminal commands"))
    for verb in ("status", "pause", "resume"):
        assert any(f"usage_guard.py {verb}" in line for line in terminal), verb
    for line in terminal:
        verb = re.search(r"usage_guard\.py (\w+)", line)
        if verb is not None and verb[1] in hook.GUARD_VERBS:
            assert hook.passes(_shell_call("PowerShell", _filled(line)), LIVE_HOME)
    undo = _fenced(_section(text, "## Undo"))
    assert LIVEH_UNDO in undo
    for state in ("installed", "absent", "drift", "disabled", "unknown"):
        assert f"`{state}`" in text, state


# ── AC-979.7: the package manifest ──────────────────────────────────────

MANIFEST_ROWS = {
    "no_skill_row": ("- `usage-guard/SKILL.md` — ",),
    "no_tool_row": ("- `tools/usage_guard.py` — ", "- `tools/usage_guard_hook.py` — "),
    "no_test_row": tuple(
        f"- `tools/tests/test_usage_guard_{name}.py` — "
        for name in ("reader", "hold", "install")
    ),
}


def _manifest_problems(text: str) -> list[str]:
    """The missing rows of the usage guard in ``MANIFEST.md``."""
    lines = text.splitlines()
    return [
        problem
        for problem, rows in MANIFEST_ROWS.items()
        if not all(any(line.startswith(row) for line in lines) for row in rows)
    ]


def test_f2p_979_doc_manifest_rows() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    assert _manifest_problems(text) == []
    without_skill = "\n".join(
        line for line in text.splitlines() if "`usage-guard/SKILL.md`" not in line
    )
    assert _manifest_problems(without_skill) == ["no_skill_row"]
    without_hook = text.replace("`tools/usage_guard_hook.py` — ", "`other.py` — ")
    assert _manifest_problems(without_hook) == ["no_tool_row"]
    without_test = text.replace("test_usage_guard_hold.py` — ", "other.py` — ")
    assert _manifest_problems(without_test) == ["no_test_row"]


# ── AC-979.8: the name census of the shipped files ──────────────────────

# The census looks for the name of the source project, the name of its owner, an
# email address and a drive path. The names are split, so that this file does not
# hold them.
SOURCE_NAME = "zori" + "vest"
OWNER_NAME = "mat" + "banik"
CENSUS_FILES = (GUARD, HOOK, SKILL)
CENSUS = (
    ("source project name", re.compile(SOURCE_NAME, re.IGNORECASE)),
    ("owner name", re.compile(OWNER_NAME, re.IGNORECASE)),
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("drive path", re.compile(r"\b[A-Za-z]:[\\/]")),
)


def _census(text: str) -> list[str]:
    """The labels of the census patterns that the text holds."""
    return [label for label, pattern in CENSUS if pattern.search(text)]


def test_f2p_979_census_shipped_files_are_clean() -> None:
    for path in CENSUS_FILES:
        assert path.is_file(), path
        lines = path.read_text(encoding="utf-8").splitlines()
        hits = [
            f"{number}:{label}"
            for number, line in enumerate(lines, 1)
            for label in _census(line)
        ]
        assert hits == [], (path.name, hits)


def test_f2p_979_census_fails_on_a_planted_name() -> None:
    text = _skill_text()
    assert _census(text) == []
    samples = {
        "source project name": SOURCE_NAME.capitalize(),
        "owner name": OWNER_NAME.upper(),
        "email address": "@".join(("someone", "example.org")),
        "drive path": "D" + ":\\work",
    }
    assert set(samples) == {label for label, _pattern in CENSUS}
    for label, sample in samples.items():
        assert _census(f"{text}\nplanted {sample} here\n") == [label], label


# ── R1 corrections: an unknown task state keeps the install (EA-8) ──────

R1_QUERY_STUB = '''
"""schtasks stub whose /Query fails in a planned way. Other verbs are recorded."""
import json, sys
from pathlib import Path

here = Path(__file__).resolve().parent
argv = sys.argv[1:]
with open(here / "sched.jsonl", "a", encoding="utf-8") as out:
    out.write(json.dumps(argv) + "\\n")
mode = (here / "query-mode.txt").read_text(encoding="utf-8").strip()
if argv[0].lower() != "/query":
    sys.exit(1)
if mode == "denied":
    sys.stderr.write("ERROR: Access is denied.\\r\\n")
    sys.exit(1)
if mode == "crash":
    import usage_guard_missing_dependency
if mode == "code_5":
    sys.exit(5)
if mode == "not_found":
    sys.stderr.write("ERROR: The system cannot find the file specified.\\r\\n")
    sys.exit(1)
sys.exit(1)
'''


def _r1_query_deps(rig: Rig, mode: str) -> object:
    """The deps of the rig with the planned query stub."""
    stub = rig.bin / "schtasks_query_stub.py"
    stub.write_text(R1_QUERY_STUB, encoding="utf-8")
    (rig.bin / "query-mode.txt").write_text(mode, encoding="utf-8")
    return rig.deps(schtasks=(sys.executable, str(stub)), which=lambda _n: None)


def _r1_verbs(rig: Rig) -> list[str]:
    path = rig.bin / "sched.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line)[0] for line in lines]


@pytest.mark.parametrize("mode", ["denied", "crash", "code_5"])
def test_r1_f3_failed_task_query_keeps_the_install(rig: Rig, mode: str) -> None:
    code, out = rig.run("install", "--part", "task", "--python", str(rig.python))
    assert code == 0, out
    assert (rig.bin / "task.xml").exists()
    before = rig.files()
    task_before = (rig.bin / "task.xml").read_bytes()
    deps = _r1_query_deps(rig, mode)
    code, out = rig.run(
        "uninstall", "--part", "task", "--python", str(rig.python), deps=deps
    )
    assert code == 1, out
    assert "task_query" in out
    assert "uninstalled" not in out
    assert rig.files() == before
    assert (rig.bin / "task.xml").read_bytes() == task_before
    assert "/Delete" not in _r1_verbs(rig)
    assert rig.status(deps=deps)["task"] == "unknown"


def test_r1_f3_not_found_query_is_a_confirmed_absence(rig: Rig) -> None:
    code, out = rig.run("install", "--part", "task", "--python", str(rig.python))
    assert code == 0, out
    (rig.bin / "task.xml").unlink()
    deps = _r1_query_deps(rig, "denied")
    code, out = rig.run(
        "uninstall", "--part", "task", "--python", str(rig.python), deps=deps
    )
    assert code == 1, out
    assert "manifest.json" in rig.files()
    deps = _r1_query_deps(rig, "not_found")
    assert rig.status(deps=deps)["task"] == "absent"
    code, out = rig.run(
        "uninstall", "--part", "task", "--python", str(rig.python), deps=deps
    )
    assert code == 0, out
    assert "uninstalled: task" in out
    assert "manifest.json" not in rig.files()
