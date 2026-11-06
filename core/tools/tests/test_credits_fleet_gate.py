"""The M-1 receipt on a fleet member (AC-11 of docs/execution/plans/2026-11-04-fleet-agents).

A member gates once, in a fixed empty folder, and each run works in its own slot. So the receipt's
project is that gate project, while its launch profile must still hold for the slot.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

PROBES = Path(__file__).resolve().parents[2] / ".agent" / "skills" / "claude-credits" / "probes"
CLI_VERSION = "2.1.296"
HOOKS = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}


def load_probe(name: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # The probes set sys.dont_write_bytecode on import; restore it so later tests are unaffected.
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    monkeypatch.syspath_prepend(str(PROBES))
    spec = importlib.util.spec_from_file_location(name, PROBES / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


class Rig:
    """A slot, a gate project, a user settings file and a good receipt for the gate project."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.kit = load_probe("kit", monkeypatch)
        self.gate = load_probe("run_gate", monkeypatch)
        monkeypatch.setattr(self.kit, "cli_version", lambda claude: CLI_VERSION)
        self.config_dir = tmp_path / "config"
        self.config_dir.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(self.config_dir))
        self.user_settings = self.config_dir / "settings.json"
        self.user_settings.write_text(json.dumps(HOOKS), encoding="utf-8")
        self.slot = tmp_path / "slot"
        self.slot.mkdir()
        self.gate_project = tmp_path / "gate-project"
        self.gate_project.mkdir()
        self.python = sys.executable
        python = self.kit.resolve_python(self.python)
        self.receipt = tmp_path / "gate-result.json"
        self.receipt.write_text(json.dumps({
            "qualifying": True,
            "mode": "live",
            "cli_version": CLI_VERSION,
            "cases": {cid: {"passed": True} for cid in self.gate.DEFAULT_CASES},
            "identity": {
                "project": self.gate_project.as_posix(),
                "kit_dir": self.kit.KIT_DIR.as_posix(),
                "kit_revision": self.kit.kit_revision(),
                "python": python,
                "settings_sha256": {"settings.json": "fixture"},
                "launch_profile": self.kit.launch_profile(self.gate_project, python),
            },
        }), encoding="utf-8")

    def check(self, project: Path | None = None, gate_project: Path | None = None) -> list[str]:
        return self.gate.check_receipt(
            self.receipt, project or self.slot, "claude", self.python,
            gate_project=self.gate_project if gate_project is None else gate_project,
        )


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    return Rig(tmp_path, monkeypatch)


def test_ac11_a_slot_can_use_the_receipt_of_its_gate_project(rig: Rig) -> None:
    assert rig.check() == []


def test_ac11_a_different_cli_version_is_rejected(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rig.kit, "cli_version", lambda claude: "2.1.297")
    assert any("cli_version" in line for line in rig.check())


def test_ac11_changed_user_hook_settings_are_rejected(rig: Rig) -> None:
    rig.user_settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    assert any("hook_settings.user" in line for line in rig.check())


def test_ac11_a_slot_with_a_settings_hook_is_rejected(rig: Rig) -> None:
    (rig.slot / ".claude").mkdir()
    (rig.slot / ".claude" / "settings.json").write_text(json.dumps(HOOKS), encoding="utf-8")
    assert any("hook_settings.project" in line for line in rig.check())


def test_ac11_a_slot_with_a_hook_free_settings_file_is_rejected(rig: Rig) -> None:
    (rig.slot / ".claude").mkdir()
    (rig.slot / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    assert any("hook_settings.project" in line for line in rig.check())


def test_ac11_a_slot_with_a_local_settings_file_is_rejected(rig: Rig) -> None:
    (rig.slot / ".claude").mkdir()
    (rig.slot / ".claude" / "settings.local.json").write_text("{}", encoding="utf-8")
    assert any("hook_settings.project_local" in line for line in rig.check())


def test_ac11_a_wrong_gate_project_is_rejected(rig: Rig, tmp_path: Path) -> None:
    other = tmp_path / "other-gate"
    other.mkdir()
    assert any(line.startswith("project ") for line in rig.check(gate_project=other))


def test_ac11_with_no_gate_project_the_receipt_must_name_the_slot(rig: Rig) -> None:
    bad = rig.gate.check_receipt(rig.receipt, rig.slot, "claude", rig.python)
    assert any(line.startswith("project ") for line in bad)


def test_ac11_with_no_gate_project_a_receipt_for_the_project_is_good(rig: Rig) -> None:
    assert rig.gate.check_receipt(rig.receipt, rig.gate_project, "claude", rig.python) == []


def run_main(rig: Rig, monkeypatch: pytest.MonkeyPatch, *extra: str) -> int:
    monkeypatch.setattr(sys, "argv", [
        "run_gate.py", "--check-receipt", str(rig.receipt), "--project", str(rig.slot),
        "--python", rig.python, "--claude", "claude", *extra,
    ])
    return rig.gate.main()


def test_ac11_the_command_line_takes_gate_project(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    assert run_main(rig, monkeypatch, "--gate-project", str(rig.gate_project)) == 0


def test_ac11_the_command_line_with_no_gate_project_rejects(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    assert run_main(rig, monkeypatch) == 1
