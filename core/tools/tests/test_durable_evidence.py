"""Exercise evidence rejection and both consumer entry points without a provider."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]


def record(**changes):
    data = dict(schema_version="evidence.v1", check_id="AC-1-green", command="python -m unittest",
                cwd=".", scope="unit suite", phase="targeted", exit_code=0, result="pass",
                tested_state="tree-A", output="12 tests passed", fresh=True)
    data.update(changes)
    return "```json\n" + json.dumps(data) + "\n```\n"


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        file = TOOLS / "durable_evidence.py"
        if not file.exists():
            return
        spec = importlib.util.spec_from_file_location("durable_evidence", file)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def problems(self, text, **kwargs):
        self.assertTrue((TOOLS / "durable_evidence.py").exists(), "durable evidence implementation missing")
        return self.module.evidence_problems(text, scratch_roots=("/tmp/acme",), **kwargs)

    def test_survives_receipt_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "run.txt"
            receipt.write_text("12 tests passed")
            text = record(output=receipt.read_text())
            receipt.unlink()
            self.assertEqual(self.problems(text), [])

    def test_missing_and_malformed_records_refused(self):
        for text in ("See /tmp/acme/run.txt", "```json\n{invalid\n```", record(output=""),
                     record(exit_code=None), record(exit_code=True), record(output="TODO")):
            with self.subTest(text=text):
                self.assertTrue(self.problems(text))

    def test_exit_result_consistency_and_red(self):
        self.assertTrue(self.problems(record(exit_code=1)))
        self.assertEqual(self.problems(record(phase="red", result="fail", exit_code=1,
                                             output="FAIL test_missing_behavior: expected 3, got 0")), [])

    def test_real_placeholder_scan_output_is_not_an_unfilled_record(self):
        self.assertEqual(self.problems(record(command="python audit.py --pattern TODO",
                                             output="0 TODO markers found")), [])

    def test_full_gate_cannot_be_partial_reused_or_stale(self):
        for changes in ({}, {"phase": "full", "fresh": False},
                        {"phase": "full", "tested_state": "tree-B"}):
            with self.subTest(changes=changes):
                self.assertTrue(self.problems(record(**changes), require_full=True, expected_state="tree-A"))
        self.assertEqual(self.problems(record(phase="full"), require_full=True, expected_state="tree-A"), [])

    def test_scratch_command_allowed_but_output_citation_refused(self):
        self.assertEqual(self.problems(record(command="python check.py > /tmp/acme/raw.txt")), [])
        self.assertTrue(self.problems(record(output="See /tmp/acme/raw.txt")))
        self.assertEqual(self.problems(record(output="/tmp/acme-other/result is a product test value")), [])

    def test_manual_procedure_has_no_fabricated_exit(self):
        manual = record(command=None, procedure="Inspect each source citation against the approved text",
                        observer="named human reviewer", exit_code=None, phase="full")
        self.assertEqual(self.problems(manual, require_full=True, expected_state="tree-A"), [])
        self.assertTrue(self.problems(record(command=None, exit_code=None)))

    def test_not_run_distinguished_from_execution(self):
        self.assertEqual(self.problems(record(result="not_run", exit_code=None,
                          reason="Earlier blocking static check failed", output="Not executed")), [])
        self.assertTrue(self.problems(record(result="not_run", exit_code=0)))

    def test_windows_scratch_paths_are_checked_after_json_decoding(self):
        for output in (r"See C:\Temp\Acme\raw.txt", "See c:/temp/acme/raw.txt"):
            with self.subTest(output=output):
                self.assertTrue(self.module.evidence_problems(record(output=output),
                                scratch_roots=(r"C:\Temp\Acme",)))
        self.assertEqual(self.module.evidence_problems(record(output="C:/Temp/AcmeOther/ok"),
                         scratch_roots=(r"C:\Temp\Acme",)), [])

    def test_closeout_consumer_rejects_scratch_only_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "handoff.md"
            file.write_text("## Acceptance Criteria\n\n| AC | Status |\n|---|---|\n| AC-1 | done |\n\n"
                            "## Evidence\nSee /tmp/acme/receipt.txt\n", encoding="utf-8")
            command = [sys.executable, str(TOOLS / "validate_closeout_artifacts.py"),
                       "--handoff", str(file), "--handoff-structure-only"]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("no evidence.v1", result.stdout)
            file.write_text(file.read_text() + record(), encoding="utf-8")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_blocked_predicate_rejects_ticket_only_and_accepts_decision(self):
        self.problems(record())
        row = "| 1 | follow-up [decision](decision.md), B-1 | [B] |"
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / "task.md"
            (Path(tmp) / "decision.md").write_text("Choose review provider")
            text = row + "\n### B-1\nReason: human-decision\nDecision: [scope](decision.md) needs human selection.\n"
            self.assertEqual(self.module.blocked_evidence_problems(row, "1", text, task), [])
            self.assertTrue(self.module.blocked_evidence_problems(row, "1", row, task))
            self.assertTrue(self.module.blocked_evidence_problems(row.replace("decision.md", "missing.md"),
                                                                 "1", text, task))

    def test_external_block_requires_actual_command_exit_and_error(self):
        self.problems(record())
        row = "| AC-1 | follow-up [issue](https://example.org/issues/1), B-AC-1 | [B] |"
        text = row + "\n### B-AC-1\nReason: external-error\n" + record(result="blocked", exit_code=7, output="dependency unavailable")
        self.assertEqual(self.module.blocked_evidence_problems(row, "AC-1", text, Path("handoff.md")), [])
        self.assertTrue(self.module.blocked_evidence_problems(row, "AC-1", text.replace('"exit_code": 7', '"exit_code": 0'), Path("handoff.md")))


if __name__ == "__main__":
    unittest.main()
