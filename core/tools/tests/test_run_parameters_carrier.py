"""Red tests for MEU-785 AC-785.18 (publish authority) and AC-785.20 (carrier reads).

AC-785.18: ``land publish --op ID [--grant | --human-directed --session S
--message-uuid U]``. With neither authority it refuses ``needs_human_publish``,
prints ``Commit the <slug> plan on main.``, exits 1 and holds no lease or lock
(a second process takes the lane, main-tree, registry and op leases at once).
With ``--grant`` or a matching human direction it publishes C on P with tree T.

AC-785.20: the land journal records L1 and the blob ids of the three carriers
(task.md, implementation-plan.md, the grouping file) at L1. One reader gives
the carrier bytes to ``run_parameters._load_carriers``; ``_grouping_sigma`` and
``commit_batch._direction_plans`` go through the same adapter (census over the
six ``_load_carriers`` call sites of ``run_parameters.py`` and the one of
``commit_batch.py``). ``_check_scope`` refuses ``scope_branch_mismatch`` when
the grant's ``scope.branch`` is not the packet branch, on every route; a carrier
that no longer matches the recorded bytes refuses ``carrier_mismatch``.

Fixture: a real temporary repository (``phase_b3.rig``) with a lane worktree on
``lane/<slug>`` claimed with the real ``claim`` verb, one lane commit and a land
op brought to ready with ``land prepare`` and a ``land-verdict/1`` file. Every
rig is built inside the test body, so a missing ``land`` verb fails at call.

Readings (recorded in the B-R2 evidence): ``reserve`` (no packet) stays allowed
under a ``lane/x`` grant and the refusal comes at the commit with a ``main``
packet; ``carrier_mismatch`` compares the lane worktree copy of a carrier with
the bytes recorded at ready; the adapter's name is not specified, so the census
finds it as the one module-level callee that both run_parameters readers share.
"""

from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import lane_worktree_config as lwc

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "tools" / "lanes.py"
RUN_PARAMETERS = ROOT / "tools" / "run_parameters.py"
COMMIT_BATCH = ROOT / "tools" / "commit_batch.py"
PLANS = "docs/execution/plans"
OP_ID = "op-land-carrier-1"
CLI_TIMEOUT_S = 180
GATE_LOCK = "{{PROJECT_NAME}}-gate.lock"
SESSION_ENV = "{{PROJECT_NAME_UPPER}}_SESSION"
LEASE_BODY = b'{"pid": 1, "argv": ["test_run_parameters_carrier.py"]}'
LANE_X = "lane/x"
LOAD_CARRIERS_CALLS_RP = 6
FS_READS = frozenset(
    {
        "_read_text",
        "_read_bytes",
        "read_text",
        "read_bytes",
        "open",
        "glob",
        "rglob",
        "iterdir",
    }
)
GATE_STUB = (
    '"""Fixture gate stub for the land carrier tests (AC-785.17 names no gate command)."""\n'
    "\n"
    "import sys\n"
    "\n"
    "sys.exit(0)\n"
)


@dataclass
class Land:
    """A land op at ready: the rig, the lane worktree, P, L0 and the integrated tree T."""

    rig: b3.Rig
    wt: Path
    l0: str
    p: str
    tree: str

    @property
    def slug(self) -> str:
        return self.rig.plan

    @property
    def repo(self) -> Path:
        return self.rig.repo

    def kept(self, name: str) -> str:
        """The OID of ``refs/lanes/<slug>/<op>/<name>``; empty when the ref is absent."""
        return self.rig.git(
            "rev-parse",
            "-q",
            "--verify",
            f"refs/lanes/{self.slug}/{OP_ID}/{name}",
            check=False,
        )


def _lanes(
    rig: b3.Rig, *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """``python tools/lanes.py <args>`` with the fixture environment and the rig's session."""
    return subprocess.run(
        [sys.executable, str(LANES), *args],
        cwd=str(cwd or rig.repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=rig.fx.env(**{SESSION_ENV: rig.fx.session}),
        timeout=CLI_TIMEOUT_S,
        check=False,
    )


def _refused(proc: subprocess.CompletedProcess[str], reason: str) -> None:
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert any(
        line.startswith(f"refused: {reason}") for line in proc.stdout.splitlines()
    ), (reason, proc.stdout, proc.stderr)


def _grant_branch(rig: b3.Rig, branch: str) -> None:
    """Replace the fixture grant with one whose ``scope.branch`` is ``branch`` (which exists)."""
    fx = rig.fx
    rig.git("branch", branch)
    newer = fx.present_and_accept(
        branch=branch, supersedes=str(fx.block["authorization"]["message_uuid"])
    )
    fx.write_carrier(newer)
    fx.commit(f"fixture: grant scoped to {branch}")
    code, out = fx.run("init", "--block", str(fx.write_block_file(newer, "branch")))
    assert code == 0, out
    fx.block = newer


def _ownership(task: bytes, slug: str) -> bytes:
    owns = (
        "src/lane/",
        f".agent/context/handoffs/{slug}-handoff.md",
        f".agent/context/handoffs/{slug}-implementation-critical-review.md",
    )
    block = (
        "\n## Lane Ownership\n\n```yaml\nowns:\n"
        + "".join(f"  - {item}\n" for item in owns)
        + "must_not_touch: []\n```\n"
    )
    return task + block.encode("utf-8")


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    """The land fields of an op record: the record, then each entry's identity and evidence."""
    merged: dict[str, Any] = {
        key: value for key, value in record.items() if key != "journal"
    }
    for item in record.get("journal", []):
        if not isinstance(item, dict):
            continue
        for part in ("identity", "evidence"):
            if isinstance(item.get(part), dict):
                merged.update(item[part])
    return merged


def _journal(rig: b3.Rig) -> dict[str, Any]:
    """The land journal ``<store>/ops/<plan>/<run>/<op>/op.json`` (the run folder by glob)."""
    found = sorted(rig.fx.store.glob(f"ops/*/*/{OP_ID}/op.json"))
    assert len(found) == 1, found
    data = json.loads(found[0].read_text(encoding="utf-8"))
    assert isinstance(data, dict), found[0]
    return _fields(data)


def _ready(tmp_path: Path, branch: str | None = None) -> Land:
    """Build the rig, claim the lane, commit its work, then prepare it and record the verdict."""
    rig = b3.rig(tmp_path / "fx", ROOT, seed=lwc.SEED)
    if branch is not None:
        _grant_branch(rig, branch)
    slug = rig.plan
    task_rel = f"{PLANS}/{slug}/task.md"
    rig.seed(
        {
            task_rel: _ownership((rig.repo / task_rel).read_bytes(), slug),
            "tools/validate_codebase.py": GATE_STUB.encode("utf-8"),
        },
        "fixture: the lane plan",
    )
    p = rig.ref()
    wt = tmp_path / "lane-wt"
    rig.git("worktree", "add", "-q", "-b", f"lane/{slug}", str(wt))
    claim = _lanes(
        rig,
        "claim",
        "--plan",
        f"{PLANS}/{slug}",
        "--worktree",
        str(wt),
        "--session",
        rig.fx.session,
        cwd=wt,
    )
    assert claim.returncode == 0, (claim.stdout, claim.stderr)
    review = f".agent/context/handoffs/{slug}-implementation-critical-review.md"
    files = {
        "src/lane/feature.py": '"""Lane fixture feature."""\n\nFEATURE = 1\n',
        f".agent/context/handoffs/{slug}-handoff.md": (
            "# Lane fixture handoff\n\n## Integration requests\n\n| Id | Request |\n|---|---|\n"
        ),
        review: "# Lane fixture review\n\nVerdict: approved\n",
    }
    for rel, text in files.items():
        path = wt / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    bf.git(wt, "add", "-A")
    bf.git(wt, "commit", "-q", "-m", "lane: fixture work")
    l0 = bf.git(wt, "rev-parse", "HEAD")
    message = rig.fx.root / "land-message.txt"
    message.write_bytes(b"feat(lane): land the fixture lane\n")
    prepared = _lanes(
        rig,
        "land",
        "prepare",
        "--worktree",
        str(wt),
        "--l0",
        l0,
        "--message-file",
        str(message),
        "--op",
        OP_ID,
    )
    journal = _journal(rig)
    tree = rig.git("rev-parse", f"{journal['T']}^{{tree}}")
    verdict = rig.fx.root / "land-verdict.json"
    verdict.write_bytes(
        json.dumps(
            {
                "schema": "land-verdict/1",
                "op": OP_ID,
                "tree": tree,
                "verdict": "approved",
                "review": review,
            }
        ).encode("utf-8")
    )
    ready = _lanes(rig, "land", "prepare", "--op", OP_ID, "--verdict", str(verdict))
    assert ready.returncode == 0, (prepared.stdout, ready.stdout, ready.stderr)
    return Land(rig=rig, wt=wt, l0=l0, p=p, tree=tree)


def _git_dir(path: Path) -> Path:
    return Path(bf.git(path, "rev-parse", "--absolute-git-dir"))


def test_publish_without_authority_refuses_and_holds_nothing(tmp_path: Path) -> None:
    """AC-785.18: no ``--grant`` and no human direction -> ``needs_human_publish``, no lease held."""
    land = _ready(tmp_path)
    proc = _lanes(land.rig, "land", "publish", "--op", OP_ID)
    _refused(proc, "needs_human_publish")
    expected = f"Commit the {land.slug} plan on main."
    assert expected in [line.strip() for line in proc.stdout.splitlines()], proc.stdout
    assert land.rig.ref() == land.p
    os_lease = importlib.import_module("tools.os_lease")
    lanes_dir = land.rig.fx.common_dir / "lanes"
    for path in (
        _git_dir(land.wt) / GATE_LOCK,
        _git_dir(land.repo) / GATE_LOCK,
        lanes_dir / "registry.lock",
        lanes_dir / "ops" / f"{OP_ID}.lease",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        lease = os_lease.acquire(path, wait_s=0, body=LEASE_BODY)
        os_lease.release(lease)


def test_publish_with_the_grant_lands_t_on_p(tmp_path: Path) -> None:
    """AC-785.18: ``--grant`` publishes C with parent P and tree T."""
    land = _ready(tmp_path)
    proc = _lanes(land.rig, "land", "publish", "--op", OP_ID, "--grant")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    published = land.rig.ref()
    assert published != land.p
    assert land.rig.parents(published) == [land.p]
    assert land.rig.git("rev-parse", f"{published}^{{tree}}") == land.tree


def test_publish_human_directed_lands_t_on_p(tmp_path: Path) -> None:
    """AC-785.18: a typed ``Commit the <slug> plan on main.`` direction publishes C."""
    land = _ready(tmp_path)
    land.rig.bind()
    uid = land.rig.fx.add_human(f"Commit the {land.slug} plan on main.")
    proc = _lanes(
        land.rig,
        "land",
        "publish",
        "--op",
        OP_ID,
        "--human-directed",
        "--session",
        land.rig.fx.session,
        "--message-uuid",
        uid,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    published = land.rig.ref()
    assert land.rig.parents(published) == [land.p]
    assert land.rig.git("rev-parse", f"{published}^{{tree}}") == land.tree


def test_journal_records_l1_and_the_carrier_blobs(tmp_path: Path) -> None:
    """AC-785.20: the journal holds L1 and the task, plan and grouping blob ids at L1."""
    land = _ready(tmp_path)
    journal = _journal(land.rig)
    assert journal["L1"] == land.kept("L1"), journal
    grouping = land.rig.fx.grouping_path.relative_to(land.repo).as_posix()
    carriers = {
        "task": f"{PLANS}/{land.slug}/task.md",
        "plan": f"{PLANS}/{land.slug}/implementation-plan.md",
        "grouping": grouping,
    }
    recorded = journal["carrier"]
    for key, rel in carriers.items():
        assert recorded[key] == land.rig.git("rev-parse", f"{journal['L1']}:{rel}"), key


def test_commit_batch_refuses_a_branch_scope_mismatch(tmp_path: Path) -> None:
    """AC-785.20: a grant scoped to ``lane/x`` cannot commit a ``main`` packet; ``main`` can."""
    rig = b3.rig(tmp_path / "mismatch", ROOT, seed=lwc.SEED)
    _grant_branch(rig, LANE_X)
    rig.reserve("op-scope-1")
    before = rig.ref()
    code, out, text = rig.commit("op-scope-1", rig.packet())
    assert (code, out.get("result"), out.get("reason")) == (
        1,
        "refused",
        "scope_branch_mismatch",
    ), text
    assert rig.ref() == before

    control = b3.rig(tmp_path / "control", ROOT, seed=lwc.SEED)
    control.reserve("op-scope-2")
    start = control.ref()
    code, out, text = control.commit("op-scope-2", control.packet())
    assert code == 0, text
    assert control.parents(control.ref()) == [start]


def test_land_publish_refuses_a_branch_scope_mismatch(tmp_path: Path) -> None:
    """AC-785.20: ``land publish --grant`` under a ``lane/x`` grant refuses before ``main`` moves."""
    land = _ready(tmp_path, branch=LANE_X)
    proc = _lanes(land.rig, "land", "publish", "--op", OP_ID, "--grant")
    _refused(proc, "scope_branch_mismatch")
    assert land.rig.ref() == land.p


def test_land_publish_refuses_a_carrier_mismatch(tmp_path: Path) -> None:
    """AC-785.20: a carrier changed after ready no longer matches the recorded bytes."""
    land = _ready(tmp_path)
    task = land.wt / PLANS / land.slug / "task.md"
    task.write_bytes(task.read_bytes() + b"\nEdited after ready.\n")
    proc = _lanes(land.rig, "land", "publish", "--op", OP_ID, "--grant")
    _refused(proc, "carrier_mismatch")
    assert land.rig.ref() == land.p


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    found = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, name
    return found[0]


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _callees(node: ast.AST) -> list[str]:
    return [
        name
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and (name := _callee(call)) is not None
    ]


def test_carrier_readers_share_one_adapter() -> None:
    """AC-785.20 census: the three carrier readers read no file directly and share one adapter."""
    rp_tree = ast.parse(RUN_PARAMETERS.read_text(encoding="utf-8"))
    cb_tree = ast.parse(COMMIT_BATCH.read_text(encoding="utf-8"))
    readers = {
        "_load_carriers": _function(rp_tree, "_load_carriers"),
        "_grouping_sigma": _function(rp_tree, "_grouping_sigma"),
        "_direction_plans": _function(cb_tree, "_direction_plans"),
    }
    direct = {
        name: sorted({call for call in _callees(node) if call in FS_READS})
        for name, node in readers.items()
    }
    assert direct == {name: [] for name in readers}, direct

    rp_defs = {
        node.name
        for node in rp_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    shared = (
        set(_callees(readers["_load_carriers"]))
        & set(_callees(readers["_grouping_sigma"]))
        & rp_defs
    )
    assert shared, (
        "no module-level adapter shared by _load_carriers and _grouping_sigma"
    )
    via = set(_callees(readers["_direction_plans"]))
    assert "_load_carriers" in via or shared & via, sorted(via)

    rp_calls = [name for name in _callees(rp_tree) if name == "_load_carriers"]
    assert len(rp_calls) == LOAD_CARRIERS_CALLS_RP, len(rp_calls)
    cb_calls = [name for name in _callees(cb_tree) if name == "_load_carriers"]
    in_direction = [
        name
        for name in _callees(readers["_direction_plans"])
        if name == "_load_carriers"
    ]
    assert len(cb_calls) == len(in_direction), (len(cb_calls), len(in_direction))
