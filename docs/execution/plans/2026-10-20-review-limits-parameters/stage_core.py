"""Stage an instantiated copy of core/ for the credits suites (plan review round 3).

The credits pytest and Pester suites read filled-in placeholders such as
{{RECEIPTS_DIR}}, so they fail in the raw template. This script copies the working
tree's core/ to a fresh STAGE folder, fills it with instantiate.py, and checks that no
placeholder is left. Run the credits suites from STAGE afterwards.
"""
import shutil
import subprocess
import sys
from pathlib import Path

STAGE = Path("C:/Temp/agentic-framework/rl-stage")
RECEIPTS = "C:/Temp/agentic-framework/receipts/rl-stage"


def main():
    repo = Path(__file__).resolve().parents[4]
    if STAGE.exists():
        shutil.rmtree(STAGE)
    shutil.copytree(repo / "core", STAGE,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".hypothesis"))
    Path(RECEIPTS).mkdir(parents=True, exist_ok=True)
    fill = [sys.executable, str(repo / "scripts/instantiate.py"), "--root", str(STAGE),
            "--project-name", "rlstage", "--project-root", STAGE.as_posix(),
            "--receipts-dir", RECEIPTS, "--repo-url", "https://example.invalid/rlstage.git"]
    for args in (fill, fill[:4] + ["--verify"]):
        code = subprocess.run(args).returncode
        if code:
            print("stage FAILED: %s exited %d" % (" ".join(args[1:4]), code))
            return code
    print("stage ready: %s" % STAGE.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
