"""Stage an instantiated copy of core/ for the credits and dispatch suites.

The credits pytest and Pester suites read filled-in placeholders such as
{{RECEIPTS_DIR}}, so they fail in the raw template. This script copies the working
tree's core/ to a fresh STAGE folder, fills it with instantiate.py, and checks that no
placeholder is left. It then copies .agent/fleet/ into the stage, so AC-22 and AC-23 can
reach fleet.py next to a real classifier and a real export (A-12). Run the suites from
STAGE afterwards.
"""
import shutil
import subprocess
import sys
from pathlib import Path

STAGE = Path("C:/Temp/agentic-framework/fa-stage")
RECEIPTS = "C:/Temp/agentic-framework/receipts/fa-stage"
IGNORED = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".hypothesis")


def main():
    repo = Path(__file__).resolve().parents[4]
    if STAGE.exists():
        shutil.rmtree(STAGE)
    shutil.copytree(repo / "core", STAGE, ignore=IGNORED)
    Path(RECEIPTS).mkdir(parents=True, exist_ok=True)
    fill = [sys.executable, str(repo / "scripts/instantiate.py"), "--root", str(STAGE),
            "--project-name", "fastage", "--project-root", STAGE.as_posix(),
            "--receipts-dir", RECEIPTS, "--repo-url", "https://example.invalid/fastage.git"]
    for args in (fill, fill[:4] + ["--verify"]):
        code = subprocess.run(args).returncode
        if code:
            print("stage FAILED: %s exited %d" % (" ".join(args[1:4]), code))
            return code
    shutil.copytree(repo / ".agent/fleet", STAGE / ".agent/fleet", ignore=IGNORED, dirs_exist_ok=True)
    print("stage ready: %s" % STAGE.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
