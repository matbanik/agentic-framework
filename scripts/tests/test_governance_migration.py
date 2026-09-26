"""Behavioral regressions for the approved governance migration."""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import re
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import refcheck
import sanitize
import placeholders


class PackagingTests(unittest.TestCase):
    def test_generic_prose_is_not_a_source_identity(self):
        prose = "The source project's name is configurable. Source project instructions follow."
        self.assertEqual(placeholders.remaining_source_hits(prose), 0)
        self.assertEqual(placeholders.apply_forward(prose), (prose, 0))

    def test_all_six_source_forms_convert_and_detect_without_prose_collision(self):
        forms = ['github.com/example/source-project', 'C:/Temp/source-project',
                 'P:/source-project', placeholders.SOURCE_UPPER,
                 placeholders.SOURCE_TITLE, placeholders.SOURCE_SLUG]
        tokens = ['{{REPO_URL}}', '{{RECEIPTS_DIR}}', '{{PROJECT_ROOT}}',
                  '{{PROJECT_NAME_UPPER}}', '{{PROJECT_NAME_TITLE}}', '{{PROJECT_NAME}}']
        for form, token in zip(forms, tokens):
            with self.subTest(form=form):
                self.assertEqual(placeholders.apply_forward(form), (token, 1))
                self.assertEqual(placeholders.apply_forward(token), (token, 0))
                self.assertEqual(placeholders.remaining_source_hits(form), 1)
                self.assertEqual(placeholders.remaining_source_hits(form.swapcase()), 1)
                self.assertEqual(placeholders.remaining_source_hits(token), 0)

    def test_verify_accepts_generic_prose_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'AGENTS.md'
            original = b"The source project's name is configurable.\r\n"
            file.write_bytes(original)
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(sanitize, 'package_root', return_value=root))
                for name in ('verify_model_slugs', 'verify_prose_model_names',
                             'verify_references', 'verify_tool_commands'):
                    stack.enter_context(patch.object(sanitize, name, return_value=0))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                self.assertEqual(sanitize.run(dry_run=False, verify=True), 0)
            self.assertEqual(file.read_bytes(), original)

    def test_verify_reports_source_leak_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "AGENTS.md"
            original = b"# source-project\r\nKeep this unchanged.\r\n"
            file.write_bytes(original)
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(sanitize, "package_root", return_value=root))
                for name in ("verify_model_slugs", "verify_prose_model_names",
                             "verify_references", "verify_tool_commands"):
                    stack.enter_context(patch.object(sanitize, name, return_value=0))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                code = sanitize.run(dry_run=False, verify=True)
            self.assertEqual(file.read_bytes(), original)
            self.assertEqual(code, 2)

    def test_adopted_template_alias_requires_shipped_target(self):
        reference = ".agent/templates/HANDOFF-TEMPLATE.md"
        target = "core/templates/HANDOFF-TEMPLATE.md"
        self.assertEqual(refcheck.resolve(reference, {target}), target)
        self.assertIsNone(refcheck.resolve(reference, set()))

    def test_template_links_resolve_in_installed_location(self):
        link = refcheck.normalize_link("../docs/output-evidence-policy.md",
                                       "core/templates/TASK-TEMPLATE.md")
        self.assertEqual(link, ".agent/docs/output-evidence-policy.md")
        self.assertEqual(refcheck.resolve(link, {"core/.agent/docs/output-evidence-policy.md"}),
                         "core/.agent/docs/output-evidence-policy.md")

    def test_unrelated_missing_tool_stays_unresolved(self):
        self.assertIsNone(refcheck.resolve("tools/not-a-real-gate.py", set()))

    def test_model_prose_gate_separates_history_from_shipped_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            historical = root / ".agent/context/research.md"
            historical.parent.mkdir(parents=True)
            historical.write_text("Reviewer: GPT-5.6-sol\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sanitize.verify_prose_model_names(root), 0)
            shipped = root / "core/.agent/context/current-focus.md"
            shipped.parent.mkdir(parents=True)
            shipped.write_text("Always use GPT-5.6-sol\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sanitize.verify_prose_model_names(root), 6)

    def test_live_slug_report_excludes_only_maintainer_history(self):
        checker = Mock()
        checker.RegistryError = RuntimeError
        history = dict(relative=".agent/context/research.md", line=1, match="historic-model")
        shipped = dict(relative="core/AGENTS.md", line=1, match="planted-model")
        for hits, expected in (([history], 0), ([history, shipped], 4)):
            with self.subTest(hits=hits), patch.object(sanitize, "load_checker", return_value=checker), contextlib.redirect_stdout(io.StringIO()):
                checker.check.return_value = dict(tier1=hits, errors=[], autogen_drift=[])
                self.assertEqual(sanitize.verify_model_slugs(ROOT), expected)


if __name__ == "__main__":
    unittest.main()
