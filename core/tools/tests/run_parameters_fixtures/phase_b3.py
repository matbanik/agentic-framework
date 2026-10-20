"""B-3 fixture phase: the commit-transaction components, the candidate root and a signing rig.

``build_fixture.build`` calls :func:`extend` before it copies the components, so every
fixture built after this module exists carries the five B-3 production files (EA-8 (l)) and
the activation digests cover them. :func:`rig` builds a fixture, configures SSH signing in
its repository, initializes the store and returns a :class:`Rig` with the driver runner, the
script runner, the packet builders and the readers of the op journal and of Git state.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.tests.run_parameters_fixtures.build_fixture import Fixture

B3_COMPONENTS = (
    "tools/commit_batch.py",
    ".agent/skills/git-workflow/scripts/agent-commit.ps1",
    ".claude/hooks/commit_gate.py",
    ".claude/hooks/_hook_common.py",
    "tools/executor_worktree.py",
)
CANDIDATE_ROOT_KEY = "run-parameters.candidateRoot"
CRASH = "RUN_PARAMETERS_TEST_CRASH_AT"
GRANT = "{{PROJECT_NAME_UPPER}}_COMMIT_GRANT"
CRASH_EXIT = 97
SCRIPT = ".agent/skills/git-workflow/scripts/agent-commit.ps1"
CANDIDATE_MANIFEST = "candidate-worktree.json"
JOURNAL_PHASES = (
    "prepared",
    "blobs_stored",
    "candidate_built",
    "candidate_verified",
    "published",
    "index_reconciled",
    "cleanup_done",
    "reconciled",
)
ACT_FOR_PHASE = {"plan": "plan_commit", "exec": "exec_commit", "finalize": "finalize"}
AUTHOR = {"name": "Fixture", "email": "fixture@example.invalid"}
SIGNER_PRINCIPALS = ("fixture@example.invalid", "signer@example.com")
TASK_CARRIER_PREFIX = "docs/execution/plans/"

Result = tuple[int, dict[str, Any], str]


def _display(path: Path) -> str:
    """Forward slashes and an upper-case drive letter (P-1), as ``build_fixture.display_path``."""
    text = str(path).replace("\\", "/").rstrip("/")
    if len(text) > 1 and text[1] == ":":
        text = text[0].upper() + text[1:]
    return text


def extend(fx: Fixture) -> None:
    """Add the B-3 components and point the candidate root inside the fixture root."""
    for rel in B3_COMPONENTS:
        if rel not in fx.components:
            fx.components.append(rel)
    fx.config_set(CANDIDATE_ROOT_KEY, _display(fx.root / "candidates"))


def last_json(stdout: str) -> dict[str, Any]:
    """The last stdout line that parses as a JSON object; an empty dict when there is none."""
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def blob_oid(data: bytes) -> str:
    """The SHA-1 object id Git gives a blob with these bytes."""
    return hashlib.sha1(
        b"blob %d\0" % len(data) + data, usedforsecurity=False
    ).hexdigest()


def make_key(root: Path, name: str) -> tuple[Path, str]:
    """An ed25519 key pair at ``<root>/keys/<name>``; returns the private key and its fingerprint."""
    keys = root / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    key = keys / name
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)],
        capture_output=True,
        check=True,
    )
    line = subprocess.run(
        ["ssh-keygen", "-lf", f"{key}.pub", "-E", "sha256"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    fingerprint = next(part for part in line.split() if part.startswith("SHA256:"))
    return key, fingerprint


def configure_signing(fx: Fixture, name: str = "signer") -> tuple[Path, str]:
    """SSH signing in the fixture repository (``commit.gpgsign`` stays false; the script signs)."""
    from tools.tests.run_parameters_fixtures import build_fixture as bf

    key, fingerprint = make_key(fx.root, name)
    public = Path(f"{key}.pub").read_text(encoding="utf-8").strip()
    allowed = fx.root / "keys" / "allowed_signers"
    allowed.write_bytes(
        f'{",".join(SIGNER_PRINCIPALS)} namespaces="git" {public}\n'.encode()
    )
    for item, value in (
        ("gpg.format", "ssh"),
        ("user.signingkey", _display(key)),
        ("gpg.ssh.allowedSignersFile", _display(allowed)),
    ):
        bf.git(fx.repo, "config", item, value)
    return key, fingerprint


@dataclass
class Rig:
    """A built, signed and initialized fixture with the B-3 runners and readers."""

    fx: Fixture
    key: Path
    fingerprint: str
    _packets: list[Path] = field(default_factory=list)

    # -- paths ---------------------------------------------------------------------------

    @property
    def repo(self) -> Path:
        return self.fx.repo

    @property
    def plan(self) -> str:
        return self.fx.plan

    @property
    def hooks(self) -> Path:
        """The fixture's ``core.hooksPath`` folder (shared by the repository and every candidate)."""
        return self.fx.root / "no-hooks"

    @property
    def candidate_root(self) -> Path:
        return self.fx.root / "candidates"

    def op_dir(
        self, op: str, run: str = "interactive", plan: str | None = None
    ) -> Path:
        return self.fx.store / "ops" / (plan or self.plan) / run / op

    # -- git -----------------------------------------------------------------------------

    def git(self, *args: str, check: bool = True, cwd: Path | None = None) -> str:
        from tools.tests.run_parameters_fixtures import build_fixture as bf

        return bf.git(cwd or self.repo, *args, check=check)

    def ref(self, branch: str = "main") -> str:
        """The OID of ``refs/heads/<branch>``; empty when the ref does not exist."""
        return self.git(
            "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False
        )

    def index(self) -> str:
        """``git ls-files -s`` of the caller's index (every stage)."""
        return self.git("ls-files", "-s")

    def index_entries(self, path: str) -> list[str]:
        """The ``ls-files -s`` lines of one path."""
        return [
            line for line in self.git("ls-files", "-s", "--", path).splitlines() if line
        ]

    def objects(self) -> set[str]:
        """Every object id in the object store, loose and packed."""
        text = self.git(
            "cat-file", "--batch-all-objects", "--batch-check=%(objectname)"
        )
        return {line for line in text.splitlines() if line}

    def loose_count(self) -> int:
        """The loose-object count of ``git count-objects -v``."""
        for line in self.git("count-objects", "-v").splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "count":
                return int(value.strip())
        raise AssertionError("git count-objects -v printed no count")

    def tree_entries(self, commit: str) -> dict[str, tuple[str, str]]:
        """``{path: (mode, blob oid)}`` of a commit's tree."""
        out: dict[str, tuple[str, str]] = {}
        for line in self.git("ls-tree", "-r", "--full-tree", commit).splitlines():
            meta, _, path = line.partition("\t")
            mode, _kind, oid = meta.split()
            out[path] = (mode, oid)
        return out

    def parents(self, commit: str) -> list[str]:
        return self.git("rev-list", "--parents", "-n", "1", commit).split()[1:]

    def message_bytes(self, commit: str) -> bytes:
        """The raw message bytes of a commit object (everything after the first empty line)."""
        raw = subprocess.run(
            ["git", "cat-file", "commit", commit],
            cwd=self.repo,
            capture_output=True,
            check=True,
        ).stdout
        return raw.split(b"\n\n", 1)[1]

    def reflog(self, branch: str = "main") -> list[tuple[str, str]]:
        """``(old, new)`` of every entry of the branch reflog file; empty when it does not exist."""
        path = self.fx.common_dir / "logs" / "refs" / "heads" / branch
        if not path.is_file():
            return []
        pairs: list[tuple[str, str]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                pairs.append((parts[0], parts[1]))
        return pairs

    def other_commit(self, parent: str | None = None, message: str = "other") -> str:
        """A commit object on ``parent`` (default: the branch tip) that no ref points to."""
        base = parent or self.ref()
        return self.git("commit-tree", f"{base}^{{tree}}", "-p", base, "-m", message)

    def seed(self, files: Mapping[str, bytes], message: str = "fixture: seed") -> str:
        """Write files with exact bytes, commit every change and return the new tip."""
        for rel, data in files.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.fx.commit(message)
        return self.ref()

    def worktree(self) -> dict[str, tuple[bytes, int]]:
        """Bytes and mtime of every working-tree file outside ``.git`` and the plan task carriers.

        ``run_parameters`` records ``store_seq`` in each plan's ``task.md`` on a reservation;
        that carrier write is its own, so the snapshot leaves the task carriers out.
        """
        out: dict[str, tuple[bytes, int]] = {}
        for folder, dirs, files in os.walk(self.repo):
            if Path(folder) == self.repo and ".git" in dirs:
                dirs.remove(".git")
            for name in files:
                path = Path(folder) / name
                rel = path.relative_to(self.repo).as_posix()
                if rel.startswith(TASK_CARRIER_PREFIX) and rel.endswith("/task.md"):
                    continue
                out[rel] = (path.read_bytes(), path.stat().st_mtime_ns)
        return out

    def install_hook(self, name: str, body: str) -> Path:
        """A POSIX-shell hook in the shared hooks folder (LF bytes; Git for Windows runs it with sh)."""
        self.hooks.mkdir(parents=True, exist_ok=True)
        path = self.hooks / name
        path.write_bytes(f"#!/bin/sh\n{body}\n".encode())
        return path

    # -- the store -------------------------------------------------------------------------

    def reserve(
        self, op: str, act: str = "exec_commit", plan: str | None = None
    ) -> None:
        code, out = self.fx.run("reserve", act, "--plan", plan or self.plan, "--op", op)
        assert (code, out.get("result")) == (0, "reserved"), out

    def bind(self, session: str | None = None) -> None:
        """Bind the plan to a session (pending, then active), as the B-2 session tests do."""
        target = session or self.fx.session
        for flag in ("--pending", "--plan"):
            code, out = self.fx.run("bind", flag, self.plan, "--session", target)
            assert code == 0, out

    def op_record(
        self, op: str, run: str = "interactive", plan: str | None = None
    ) -> dict[str, Any]:
        path = self.op_dir(op, run, plan) / "op.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), path
        return data

    def journal(
        self, op: str, run: str = "interactive", plan: str | None = None
    ) -> list[tuple[str, str]]:
        """``(phase, status)`` of every journal entry of an op, in order."""
        record = self.op_record(op, run, plan)
        return [(str(item["phase"]), str(item["status"])) for item in record["journal"]]

    def candidate_path(self, op: str, run: str = "interactive") -> Path:
        return Path(str(self.op_record(op, run)["candidate_path"]))

    def index_record(
        self, op: str, name: str, run: str = "interactive"
    ) -> dict[str, Any]:
        """``<op dir>/index/<name>.json`` (``before`` or ``after``)."""
        path = self.op_dir(op, run) / "index" / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), path
        return data

    def seal_plan(self, plan: str | None = None) -> Path:
        """A sealed ``final/<plan>/1.json``, written as the sealing writer would (the plan expires)."""
        from tools.tests.run_parameters_fixtures import build_fixture as bf

        target = plan or self.plan
        validator = {"exit": 0, "version": "fixture", "sha256": "a" * 64}
        receipt = {
            "schema": "final-receipt/1",
            "plan": target,
            "run_id": "fixture-run",
            "repo_id": {},
            "branch": "main",
            "generation": 1,
            "mode": "tree",
            "op": "none",
            "commit": "none",
            "tree": self.git("rev-parse", "HEAD^{tree}"),
            "read_set": [],
            "validators": {"closeout": validator, "preflight": validator},
            "publication_audit": {},
            "predecessor": "none",
            "sealed": True,
            "seal": {"path": f"final/{target}/1.seal", "sha256": "b" * 64},
            "ts": bf.FIXTURE_CLOCK,
        }
        path = self.fx.store / "final" / target / "1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(receipt, indent=2) + "\n").encode("utf-8"))
        return path

    # -- packets ---------------------------------------------------------------------------

    def packet(
        self,
        files: Mapping[str, bytes] | None = None,
        *,
        deletes: Iterable[str] = (),
        modes: Mapping[str, str] | None = None,
        message: str = "feat: fixture change\n",
        author: Mapping[str, str] | None = None,
        parent: str | None = None,
        plan: str | None = None,
        branch: str = "main",
        fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """A ``commit-packet/1`` on the branch tip (EA-8 (b))."""
        entries: list[dict[str, Any]] = [
            {
                "path": path,
                "mode": (modes or {}).get(path, "100644"),
                "data": base64.b64encode(data).decode("ascii"),
            }
            for path, data in (files or {"change.txt": b"change\n"}).items()
        ]
        entries += [{"path": path, "delete": True} for path in deletes]
        return {
            "schema": "commit-packet/1",
            "plan": plan or self.plan,
            "branch": branch,
            "parent": parent or self.ref(branch),
            "message": message,
            "author": dict(author or AUTHOR),
            "signing_fingerprint": fingerprint or self.fingerprint,
            "entries": entries,
        }

    def batch(
        self, packets: list[dict[str, Any]], count: int | None = None
    ) -> dict[str, Any]:
        """A ``commit-batch/1`` of packets (EA-8 (b))."""
        return {
            "schema": "commit-batch/1",
            "plan": self.plan,
            "branch": "main",
            "count": len(packets) if count is None else count,
            "packets": packets,
        }

    def write_packet(self, data: Mapping[str, Any]) -> Path:
        """A packet file under ``<root>/packets`` (deterministic bytes, so a rerun has the same digest)."""
        folder = self.fx.root / "packets"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"packet-{len(self._packets) + 1}.json"
        path.write_bytes(
            (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        self._packets.append(path)
        return path

    # -- runners ---------------------------------------------------------------------------

    def drive(self, *argv: str, env: Mapping[str, str | None] | None = None) -> Result:
        """``python -m tools.commit_batch --repo <repo> ...`` in a child process: (exit, JSON, output)."""
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.commit_batch",
                "--repo",
                str(self.repo),
                *argv,
            ],
            cwd=self.fx.source,
            env=self.fx.env(**dict(env or {})),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=110,
            check=False,
        )
        return proc.returncode, last_json(proc.stdout), proc.stdout + proc.stderr

    def commit(
        self,
        op: str,
        packet: Mapping[str, Any],
        *,
        phase: str = "exec",
        run: str | None = None,
        env: Mapping[str, str | None] | None = None,
    ) -> Result:
        """The grant route: write the packet and drive ``--phase <phase> --op <op>``."""
        argv = [
            "--phase",
            phase,
            "--op",
            op,
            "--packet",
            str(self.write_packet(packet)),
        ]
        if run is not None:
            argv += ["--run", run]
        return self.drive(*argv, env=env)

    def crash(self, op: str, packet: Mapping[str, Any], point: str) -> Result:
        """Drive with the crash seam at ``commit:<point>``; the child must exit 97."""
        res = self.commit(op, packet, env={CRASH: f"commit:{point}"})
        assert res[0] == CRASH_EXIT, res
        return res

    def human(
        self, uid: str, packet: Mapping[str, Any], session: str | None = None
    ) -> Result:
        """The human route: ``--human-directed --session <s> --message-uuid <u> --packet <file>``."""
        return self.drive(
            "--human-directed",
            "--session",
            session or self.fx.session,
            "--message-uuid",
            uid,
            "--packet",
            str(self.write_packet(packet)),
        )

    def script(
        self,
        *args: str,
        grant: str | None = None,
        env: Mapping[str, str | None] | None = None,
    ) -> Result:
        """The repository's ``agent-commit.ps1`` with ``-RepositoryPath``: (exit, last JSON line, output)."""
        extra: dict[str, str | None] = {"{{PROJECT_NAME_UPPER}}_PYTHON": sys.executable, GRANT: grant}
        extra.update(env or {})
        proc = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(self.repo / SCRIPT),
                "-RepositoryPath",
                str(self.repo),
                *args,
            ],
            cwd=self.repo,
            env=self.fx.env(**extra),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=110,
            check=False,
        )
        return proc.returncode, last_json(proc.stdout), proc.stdout + proc.stderr


def rig(
    root: Path,
    source: Path,
    *,
    seed: Mapping[str, bytes] | None = None,
    signer: str = "signer",
) -> Rig:
    """Build a fixture at ``root``, seed files, configure signing and initialize the store."""
    from tools.tests.run_parameters_fixtures import build_fixture as bf

    fx = bf.build(root, source)
    key, fingerprint = configure_signing(fx, signer)
    made = Rig(fx=fx, key=key, fingerprint=fingerprint)
    if seed:
        made.seed(seed)
    code, out = fx.run("init", "--plan", fx.plan)
    assert (code, out.get("result")) == (0, "initialized"), out
    return made
