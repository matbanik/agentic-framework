#!/usr/bin/env python3
"""Land row 17's two results on the hub through fleet.py result, then drop each run on the member.

land  run fleet.py result for the Claude and the Codex run, and write each full diff to fa-live-result-<run>.diff
drop  once both diffs are shown to the human in chat: drop both runs, and record that

Every step's fleet output goes to fa-live-result.log. The evidence is fa-live-result.json. Addresses are not printed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
FLEET = ROOT / ".agent" / "fleet" / "fleet.py"
RECEIPTS = Path(os.environ.get("RECEIPTS_DIR") or "C:/Temp/agentic-framework/receipts")
EVIDENCE = RECEIPTS / "fa-live-result.json"
LOG = RECEIPTS / "fa-live-result.log"
MEMBER = os.environ.get("FLEET_MEMBER") or sys.exit("set FLEET_MEMBER to the member's fleet name")
RESULTS = (
    ("claude", "fa-row12b", RECEIPTS.parent / "fa-live-repo"),
    ("codex", "fa-row15", RECEIPTS.parent / "fa-live-codex-repo"),
)
# The human's words, as typed, that land row 17's results.
LANDING_WORD = "Land the row 17 test results."


def fleet(*args: str) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, str(FLEET), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"args": list(args), "exit": r.returncode, "stdout": r.stdout[-6000:], "stderr": r.stderr[-2000:]}) + "\n")
    return r


def last_json(r: subprocess.CompletedProcess) -> dict:
    lines = r.stdout.strip().splitlines()
    return json.loads(lines[-1]) if lines else {}


def evidence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else {}


def save(**fields) -> None:
    EVIDENCE.write_text(json.dumps({**evidence(), **fields}, indent=1), encoding="utf-8")


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise SystemExit(f"git {' '.join(args)} in {repo}: {r.stderr.strip()}")
    return r.stdout.strip()


def person(repo: Path, commit: str, fmt: str) -> dict:
    name, email = git(repo, "log", "-1", f"--format={fmt}", commit).split("\0")
    return {"name": name, "email": email}


def branches(repo: Path) -> list[str]:
    return git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads").splitlines()


def cmd_land() -> int:
    name, email = git(ROOT, "config", "--global", "user.name"), git(ROOT, "config", "--global", "user.email")
    before = {run: branches(repo) for _, run, repo in RESULTS}
    done = {r["run"]: r for r in evidence().get("results") or []}
    results = []
    for cli, run, repo in RESULTS:
        if run in done:
            results.append(done[run])
            print(f"{run}: landed before, kept")
            continue
        r = fleet("result", MEMBER, run, "--repo", str(repo))
        out = last_json(r) if r.stdout.strip() else {}
        if r.returncode:
            print(f"{run}: exit {r.returncode} {r.stderr.strip()} {out.get('reason')}")
            save(identity={"name": name, "email": email}, landing_word=LANDING_WORD, results=results)
            return r.returncode
        commit, base = out["commit"], out["base"]
        diff = RECEIPTS / f"fa-live-result-{run}.diff"
        diff.write_text(git(repo, "diff", base, commit) + "\n", encoding="utf-8")
        results.append({
            "cli": cli, "run": run, "repo": repo.as_posix(), "ref": out["ref"], "commit": commit, "base": base,
            "tree": git(repo, "rev-parse", f"{out['ref']}^{{tree}}"), "tree_expected": out["tree"],
            "author": person(repo, commit, "%an%x00%ae"), "committer": person(repo, commit, "%cn%x00%ce"),
            "diff_stat": out["diff_stat"], "diff_file": diff.as_posix(), "diff_shown": False, "dropped": False,
        })
        mine = results[-1]["author"] == results[-1]["committer"] == {"name": name, "email": email}
        print(f"{run} ({cli}): {out['ref']} = {commit}, tree {results[-1]['tree']}, author and committer are the hub's: {mine}")
        print(out["diff_stat"])
        print(f"diff: {diff.as_posix()}")
    after = {run: branches(repo) for _, run, repo in RESULTS}
    save(
        identity={"name": name, "email": email}, landing_word=LANDING_WORD, results=results,
        branches_before=evidence().get("branches_before") or before, branches_after=after,
    )
    return 0


def cmd_drop() -> int:
    t = evidence()
    code = 0
    for r in t.get("results") or []:
        r["diff_shown"] = True
        if r.get("dropped"):
            continue
        d = fleet("agent", "drop", MEMBER, r["run"])
        out = last_json(d) if d.stdout.strip() else {}
        r["dropped"] = d.returncode == 0 and out.get("dropped") is True
        print(f"{r['run']}: drop exit {d.returncode} {out.get('state')} {out.get('reason')}")
        code = code or d.returncode
    save(results=t.get("results") or [])
    return code


def main() -> int:
    steps = {"land": cmd_land, "drop": cmd_drop}
    if len(sys.argv) != 2 or sys.argv[1] not in steps:
        print(__doc__)
        return 2
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    return steps[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
