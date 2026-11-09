"""Behavior tests for ``toggle_1m.py``: run the script as the skill does, on a temp file.

Every arm drives the real entry point through ``--settings`` so no test can touch the
user's own ``~/.claude/settings.json``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "toggle_1m.py"
KEY = "CLAUDE_CODE_DISABLE_1M_CONTEXT"


def run(settings: Path, action: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), action, "--settings", str(settings)],
        capture_output=True, text=True, check=False,
    )


def write(path: Path, data: object) -> str:
    text = json.dumps(data, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_off_sets_key_and_keeps_every_other_key(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    original = write(settings, {"model": "x", "env": {"DISABLE_PROMPT_CACHING": "1"}})

    result = run(settings, "off")

    assert result.returncode == 0, result.stderr
    assert read(settings) == {"model": "x", "env": {"DISABLE_PROMPT_CACHING": "1", KEY: "1"}}
    backup = tmp_path / "settings.json.1m-backup"
    assert backup.read_text(encoding="utf-8") == original
    assert "on -> off" in result.stdout


def test_on_removes_key_and_drops_env_left_empty(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    write(settings, {"model": "x", "env": {KEY: "1"}})

    result = run(settings, "on")

    assert result.returncode == 0, result.stderr
    assert read(settings) == {"model": "x"}


def test_on_keeps_env_that_still_has_other_keys(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    write(settings, {"env": {KEY: "1", "OTHER": "y"}})

    assert run(settings, "on").returncode == 0
    assert read(settings) == {"env": {"OTHER": "y"}}


def test_status_reports_and_changes_nothing(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    original = write(settings, {"env": {KEY: "1"}})

    result = run(settings, "status")

    assert result.returncode == 0
    assert "1M context: off" in result.stdout
    assert settings.read_text(encoding="utf-8") == original
    assert not (tmp_path / "settings.json.1m-backup").exists()


def test_same_state_is_a_no_op_without_backup(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    original = write(settings, {"env": {KEY: "1"}})

    result = run(settings, "off")

    assert result.returncode == 0
    assert "already off" in result.stdout
    assert settings.read_text(encoding="utf-8") == original
    assert not (tmp_path / "settings.json.1m-backup").exists()


def test_missing_file_reads_on_and_off_creates_it(tmp_path: Path) -> None:
    settings = tmp_path / "sub" / "settings.json"

    status = run(settings, "status")
    assert status.returncode == 0
    assert "1M context: on" in status.stdout
    assert not settings.exists()

    assert run(settings, "on").returncode == 0
    assert not settings.exists()

    result = run(settings, "off")
    assert result.returncode == 0, result.stderr
    assert read(settings) == {"env": {KEY: "1"}}
    assert "file created" in result.stdout


def test_invalid_json_exits_2_and_leaves_file(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{not json", encoding="utf-8")

    result = run(settings, "off")

    assert result.returncode == 2
    assert "not valid JSON" in result.stderr
    assert settings.read_text(encoding="utf-8") == "{not json"


def test_env_not_an_object_exits_2_and_leaves_file(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    original = write(settings, {"env": ["oops"]})

    result = run(settings, "off")

    assert result.returncode == 2
    assert "'env' exists but is not an object" in result.stderr
    assert settings.read_text(encoding="utf-8") == original
    assert not (tmp_path / "settings.json.1m-backup").exists()
