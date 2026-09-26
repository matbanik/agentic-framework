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


class InstructionTests(unittest.TestCase):
    def test_root_instruction_budgets_allow_adoption_headroom(self):
        for name, lines, size in (("AGENTS.md", 170, 20000), ("GUARDRAILS.md", 90, 8000)):
            with self.subTest(name=name):
                text = (ROOT / "core" / name).read_text(encoding="utf-8")
                text = text.replace("{{PROJECT_NAME_TITLE}}", "Representative Project With A Long Name")
                text = text.replace("{{PROJECT_ROOT}}", "/workspace/representative project with spaces")
                text = text.replace("{{RECEIPTS_DIR}}", "/var/tmp/representative project receipts")
                self.assertLessEqual(len(text.splitlines()), lines)
                self.assertLessEqual(len(text.encode("utf-8")), size)

    def test_registry_matches_root_headings(self):
        root = (ROOT / "core/AGENTS.md").read_text(encoding="utf-8")
        registry = (ROOT / "core/.agent/schemas/registry.yaml").read_text(encoding="utf-8")
        headings = re.findall(r"^## (.+)$", root, re.MULTILINE)
        registered = re.findall(r'^    heading: "(.+)"$', registry, re.MULTILINE)
        self.assertEqual(set(headings), set(registered))
        self.assertEqual(len(headings), len(registered))


class AdoptionTests(unittest.TestCase):
    def test_full_copy_spaces_custom_roots_and_manual_evidence(self):
        import instantiate
        for style in ("windows", "posix"):
            with self.subTest(style=style), tempfile.TemporaryDirectory(prefix="governance adopt ") as tmp:
                dest = Path(tmp) / "project with spaces"
                dest.mkdir()
                for name in ("AGENTS.md", "GUARDRAILS.md", "CLAUDE.md", "MANIFEST.md"):
                    shutil.copy2(ROOT / "core" / name, dest / name)
                for source, target in ((".agent", ".agent"), ("tools", "tools"),
                                       ("templates", ".agent/templates")):
                    shutil.copytree(ROOT / "core" / source, dest / target, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("__pycache__"))
                profile = "C1: egress prohibited\nB4: named human\nD9: no\nD6: manual citation audit\n{{PROJECT_NAME}} owned\n"
                (dest / "PROJECT-PROFILE.md").write_text(profile)
                (dest / "user-notes.md").write_text("Keep {{PROJECT_NAME}}")
                receipt_root = (Path(tmp) / "working receipts").as_posix() if style == "windows" else "/var/tmp/custom receipt root"
                project_root = dest.as_posix() if style == "windows" else "/workspace/project with spaces"
                values = dict(project_name="adoption-probe", project_root=project_root,
                              receipts_dir=receipt_root, repo_url="example.org/team/project")
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(instantiate.run(values, False, dest), 0)
                    self.assertEqual(instantiate.verify_only(dest), 0)
                self.assertEqual((dest / "PROJECT-PROFILE.md").read_text(), profile)
                self.assertEqual((dest / "user-notes.md").read_text(), "Keep {{PROJECT_NAME}}")
                for name, budget in (("AGENTS.md", 20000), ("GUARDRAILS.md", 8000)):
                    self.assertLessEqual((dest / name).stat().st_size, budget)
                for name in ("AGENTS.md", "GUARDRAILS.md"):
                    self.assertIn("@" + name, (dest / "CLAUDE.md").read_text(encoding="utf-8"))
                payload = dict(schema_version="evidence.v1", check_id="manual-full", command=None,
                               procedure="Compare every citation against the approved manuscript",
                               observer="named human", cwd=".", scope="all manuscript citations",
                               phase="full", exit_code=None, result="pass", tested_state="manuscript-A",
                               output="All 8 citations match the approved sources", fresh=True)
                artifact = dest / "handoff.md"
                artifact.write_text("```json\n" + json.dumps(payload) + "\n```\n")
                command = [sys.executable, str(dest / "tools/durable_evidence.py"), str(artifact),
                           "--require-full", "--expected-state", "manuscript-A"]
                result = subprocess.run(command, capture_output=True, text=True, cwd=dest)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                result = subprocess.run(command[:-1] + ["manuscript-B"], capture_output=True, text=True, cwd=dest)
                self.assertEqual(result.returncode, 1)

    def test_powershell_wrapper_path_contract_without_provider(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell unavailable; Windows wrapper behavior not measured")
        source = (ROOT / "core/tools/Invoke-CodexDispatch.ps1").read_text(encoding="utf-8-sig")
        function = re.search(r"^function Get-PhysicalPath \{.*?^\}", source, re.MULTILINE | re.DOTALL).group()
        checks = source[source.index("# Validate OutputDir"):source.index("# Validate the opt-in standalone benchmark contract")]
        with tempfile.TemporaryDirectory(prefix="dispatch contract ") as tmp:
            base = Path(tmp)
            repo, receipts, outside = (base / n for n in ("project tmp", "custom receipts", "outside"))
            for directory in (repo, receipts, outside):
                directory.mkdir()
                (directory / "_tmp-prompt.md").write_text("fixture prompt")
                (directory / "schema.json").write_text("{}")
            script = base / "check.ps1"
            script.write_text(function + '\n$OutputDir=$env:MIG_OUTPUT; $WorkingDirectory=$env:MIG_CWD; '
                              '$PromptFile=$env:MIG_PROMPT; $OutputSchema=$env:MIG_SCHEMA; '
                              '$Mode="ReviewReadOnly"; $ApiKeyEnvVar=""\n' +
                              checks.replace("{{RECEIPTS_DIR}}", receipts.as_posix()).replace("{{PROJECT_ROOT}}", repo.as_posix()) +
                              '\nWrite-Output "PATHS-OK"; exit 0\n', encoding="utf-8")
            env = os.environ.copy()
            env.update(MIG_OUTPUT=str(receipts / "tmp"), MIG_CWD=str(repo),
                       MIG_PROMPT=str(repo / "_tmp-prompt.md"), MIG_SCHEMA=str(repo / "schema.json"))
            cases = [("repo prompt", {}, 0), ("receipt prompt", {"MIG_PROMPT": str(receipts / "_tmp-prompt.md")}, 0),
                     ("outside prompt", {"MIG_PROMPT": str(outside / "_tmp-prompt.md")}, 1),
                     ("outside cwd", {"MIG_CWD": str(outside)}, 1),
                     ("prefix sibling", {"MIG_OUTPUT": str(receipts) + "-other"}, 1),
                     ("outside schema", {"MIG_SCHEMA": str(receipts / "schema.json")}, 1),
                     ("wildcard output", {"MIG_OUTPUT": str(receipts / "*")}, 1)]
            for label, changes, expected in cases:
                with self.subTest(case=label):
                    result = subprocess.run([pwsh, "-NoProfile", "-File", str(script)],
                                            env=env | changes, capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                    if expected == 0:
                        self.assertIn("PATHS-OK", result.stdout)

            # Exercise the actual collision/physical-leaf code, without starting a CLI.
            setup = source[source.index("# 2. Directory Setup & Collision Handling"):
                           source.index("# 3. Create Files & Prepare Stdin Prompt")]
            collision = base / "collision.ps1"
            collision.write_text(function + '\n$canonicalOutputDir=Get-PhysicalPath $env:MIG_OUTPUT; '
                                 '$DispatchId="existing"; $Force=$false\n' + setup, encoding="utf-8")
            (receipts / "existing").mkdir()
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(collision)],
                                    env=env | {"MIG_OUTPUT": str(receipts)}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Collision error", result.stderr)

            if os.name == "nt":
                junction = receipts / "escape"
                create = base / "junction.ps1"
                create.write_text('New-Item -ItemType Junction -Path $env:MIG_LINK -Target $env:MIG_TARGET -ErrorAction Stop | Out-Null\n')
                result = subprocess.run([pwsh, "-NoProfile", "-File", str(create)], capture_output=True, text=True,
                                        env=env | {"MIG_LINK": str(junction), "MIG_TARGET": str(outside)})
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run([pwsh, "-NoProfile", "-File", str(script)],
                                        env=env | {"MIG_OUTPUT": str(junction)}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn("OutputDir must be under", result.stderr)

    def test_bash_wrapper_path_contract_without_provider(self):
        bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
        if not bash or not Path(bash).is_file():
            self.skipTest("Bash unavailable; POSIX wrapper snippets not measured")
        source = (ROOT / "core/tools/Invoke-CodexDispatch.sh").read_text()
        funcs = source[source.index("physical_path() {"):source.index("default_timeout() {")]
        checks = source[source.index('if [[ "$OUTPUT_DIR" == *"*"*'):source.index('if [[ "$BENCHMARK_ISOLATION" -eq 1 ]]; then', source.index('CANONICAL_PROMPT_FILE=""'))]
        with tempfile.TemporaryDirectory(prefix="bash dispatch ") as tmp:
            base = Path(tmp)
            repo, receipts, outside = (base / n for n in ("project tmp", "custom receipts", "outside"))
            for directory in (repo, receipts, outside):
                directory.mkdir()
                (directory / "_tmp-prompt.md").write_text("fixture")
            script = base / "probe.sh"
            script.write_text('set -e\ndie() { echo "$*" >&2; exit 1; }\npython3() { "$MIG_PYTHON" "$@"; }\n' + funcs +
                              '\nREPO_ROOT="$(physical_path "$MIG_REPO")"; RECEIPTS_ROOT="$(physical_path "$MIG_RECEIPTS")"\n'
                              'OUTPUT_DIR="$MIG_OUTPUT"; WORKING_DIRECTORY="$MIG_REPO"; PROMPT_FILE="$MIG_PROMPT"; '
                              'OUTPUT_SCHEMA=""; MODE=ReviewReadOnly; API_KEY_ENV_VAR=""\n' + checks +
                              '\necho PATHS-OK\n', encoding="utf-8")
            env = os.environ | {"MIG_PYTHON": Path(sys.executable).as_posix(), "MIG_REPO": repo.as_posix(),
                                "MIG_RECEIPTS": receipts.as_posix(), "MIG_OUTPUT": (receipts / "tmp").as_posix(),
                                "MIG_PROMPT": (repo / "_tmp-prompt.md").as_posix()}
            for label, changes, expected in (("repo", {}, 0),
                    ("receipt", {"MIG_PROMPT": (receipts / "_tmp-prompt.md").as_posix()}, 0),
                    ("outside", {"MIG_PROMPT": (outside / "_tmp-prompt.md").as_posix()}, 1),
                    ("prefix sibling", {"MIG_OUTPUT": receipts.as_posix() + "-other"}, 1)):
                with self.subTest(case=label):
                    result = subprocess.run([bash, str(script)], env=env | changes, capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_native_shell_receipt_read_preserves_nonzero_without_rtk(self):
        candidates = [("powershell", shutil.which("pwsh")),
                      ("bash", "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))]
        for kind, executable in candidates:
            with self.subTest(shell=kind):
                if not executable or not Path(executable).is_file():
                    continue
                with tempfile.TemporaryDirectory(prefix="exit receipt ") as tmp:
                    base = Path(tmp)
                    (base / "fail.py").write_text("import sys\nprint('decisive-failure')\nsys.exit(7)\n")
                    script = base / ("probe.ps1" if kind == "powershell" else "probe.sh")
                    if kind == "powershell":
                        body = "& $env:MIG_PYTHON fail.py *> receipt.txt; $code=$LASTEXITCODE; Get-Content receipt.txt; exit $code\n"
                        argv = [executable, "-NoProfile", "-File", str(script)]
                    else:
                        body = '"$MIG_PYTHON" fail.py > receipt.txt 2>&1; code=$?; cat receipt.txt; exit "$code"\n'
                        argv = [executable, str(script)]
                    script.write_text(body)
                    result = subprocess.run(argv, cwd=base, env=os.environ | {"MIG_PYTHON": Path(sys.executable).as_posix()},
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                    self.assertIn("decisive-failure", (base / "receipt.txt").read_text())


if __name__ == "__main__":
    unittest.main()
