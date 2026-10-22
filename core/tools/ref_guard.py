"""The ``refs/heads/main`` guard: a git ``reference-transaction`` hook (MEU-784, design §5.1).

``python tools/ref_guard.py hook <phase>`` is the hook entry; git gives one
``<old> <new> <ref>`` line per update on stdin. Only ``prepared`` decides, and only
lines that name ``refs/heads/main`` count (``decide``):

1. a true no-op (``<old> == <new>``, both non-zero object ids) allows;
2. exactly one ``main`` line ``P -> C`` with an open publication intent allows: the last
   journal entry of a ``tools/commit_batch.py`` op is ``published``/``started`` and its
   evidence names this repository, ``refs/heads/main``, ``P``, ``C`` and the candidate ``C``;
3. everything else refuses with a reason that names ``tools/commit_batch.py``;
4. ``<git-common-dir>/lanes/HALT`` refuses even a matching publication.

The guard only reads files: it never takes ``store.lock`` (``commit_batch.py`` holds it
while git runs the hook) and keeps no state between calls. The one human escape is the
exact value ``off`` of the switch environment variable (``SWITCH``).

``install`` and ``uninstall`` manage the hook shim (design §9.2): a ``sh`` script that runs
the interpreter recorded at install time on this file, chains an existing hook moved to
``<hook>.local`` with the same stdin bytes and arguments, and refuses when either refuses.
Install sets ``gc.packRefs`` and ``maintenance.pack-refs.enabled`` to ``false`` so ``main``
stays a loose ref, and records the previous values in ``<git-common-dir>/lanes/ref-guard.json``.
Both hold the lanes registry lock, so they never interleave. It installs on Windows only,
where ``commit_batch.py`` is the publish route. A refusal
prints ``refused: <reason>`` and a detail line on stdout and exits 1.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

if __package__:
    from . import lanes, os_lease
    from . import run_parameters as rp
else:
    import lanes
    import os_lease
    import run_parameters as rp

MAIN = "refs/heads/main"
SWITCH = "{{PROJECT_NAME_UPPER}}_REF_GUARD"
HOOK_NAME = "reference-transaction"
LOCAL_SUFFIX = ".local"
INVENTORY_SCHEMA = "ref-guard/1"
INVENTORY_KEYS = frozenset(
    {
        "schema",
        "interpreter",
        "guard",
        "hook_path",
        "chained_local",
        "previous",
        "git_version",
        "installed",
    }
)
# Both keep ``main`` loose: ``gc`` and the maintenance ``pack-refs`` task (§10b N-1).
PREVIOUS_KEYS = ("gc.packRefs", "maintenance.pack-refs.enabled")
INTENT_FIELDS = ("repo", "ref", "ref_old", "ref_new", "op", "candidate")
# ``reference-transaction`` with symbolic-ref events, as the acceptance test pins.
MIN_GIT = (2, 46, 0)
# The shim carries this file name; it marks a hook as the guard's own.
SHIM_MARKER = "ref_guard.py"
EXIT_REFUSED = 1
EXIT_NOT_INSTALLED = 4
ROUTE = "tools/commit_batch.py"

_OID_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_VERSION_RE = re.compile(r"git version (\d+)\.(\d+)\.(\d+)")


class Refusal(Exception):
    """An install or uninstall refusal: ``refused: <reason>`` plus a detail line."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# The pure predicate
# ---------------------------------------------------------------------------


def _is_zero(value: str) -> bool:
    return set(value) == {"0"}


def _value_ok(value: str) -> bool:
    """An object id, or a symbolic value ``ref:<target>``."""
    if value.startswith("ref:"):
        target = value[len("ref:") :]
        return bool(target) and not any(ch.isspace() for ch in target)
    return _OID_RE.fullmatch(value) is not None


def _parse_line(line: str) -> tuple[str, str, str] | None:
    """``(old, new, ref)`` of one hook stdin line, or None when it is malformed."""
    parts = line.split(" ")
    if len(parts) != 3 or not all(parts):
        return None
    old, new, ref = parts
    if any(ch.isspace() for ch in ref):
        return None
    if not (_value_ok(old) and _value_ok(new)):
        return None
    return old, new, ref


def _plain(value: str) -> bool:
    """A non-zero object id: not symbolic, not zero."""
    return not value.startswith("ref:") and not _is_zero(value)


def _matches(intent: Mapping[str, Any], old: str, new: str) -> bool:
    if not all(isinstance(intent.get(key), str) for key in INTENT_FIELDS):
        return False
    return (
        intent["ref"] == MAIN
        and intent["ref_old"] == old
        and intent["ref_new"] == new
        and intent["candidate"] == new
    )


def _refusal(old: str, new: str, why: str) -> str:
    return (
        f"main_protected: {MAIN} {old} -> {new}: {why}; "
        f"{MAIN} moves only through {ROUTE}"
    )


def decide(
    phase: str,
    lines: Sequence[str],
    intents: Sequence[Mapping[str, Any]],
    halt: bool,
    env: Mapping[str, str],
) -> str | None:
    """The guard's verdict on one transaction: None allows, a string is the refusal reason.

    ``lines`` are the raw stdin lines (no newline); ``intents`` are the evidence dicts of
    the open publications (``load_intents``); ``halt`` is whether ``lanes/HALT`` exists.
    Outside ``prepared`` the verdict is always None. The switch allows only at the exact
    value ``off``. A malformed line in ``prepared`` refuses ``stdin_bad`` even next to a
    valid main line. ``halt`` refuses publications to ``main`` only; other refs still move.
    """
    if phase != "prepared":
        return None
    if env.get(SWITCH) == "off":
        return None
    updates: list[tuple[str, str, str]] = []
    for line in lines:
        parsed = _parse_line(line)
        if parsed is None:
            return (
                f"stdin_bad: {line!r} is not '<old> <new> <ref>'; "
                f"{MAIN} moves only through {ROUTE}"
            )
        updates.append(parsed)
    main = [(old, new) for old, new, ref in updates if ref == MAIN]
    if not main:
        return None
    # Rule 1: a true no-op does not move main.
    if all(old == new and _plain(old) for old, new in main):
        return None
    if halt:
        return (
            "halt: lanes/HALT is present; "
            f"{MAIN} does not move until the human removes it ({ROUTE} publications included)"
        )
    if len(main) != 1:
        return _refusal(
            main[0][0], main[0][1], f"{len(main)} {MAIN} lines in one transaction"
        )
    old, new = main[0]
    if old.startswith("ref:") or new.startswith("ref:"):
        return _refusal(old, new, "a symbolic change")
    if _is_zero(new):
        return _refusal(old, new, "a deletion")
    if _is_zero(old):
        return _refusal(old, new, "a creation from the zero id")
    if not any(_matches(intent, old, new) for intent in intents):
        return _refusal(old, new, "no open publication intent")
    return None


# ---------------------------------------------------------------------------
# The intent lookup
# ---------------------------------------------------------------------------


def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _store(common: Path) -> Path:
    """The run-parameters store of ``common``, by the store's own path helper."""
    display = rp.display_path(common)
    return rp.Repo(
        top=common, display=display, common=common, main=common, main_display=display
    ).store


def _intent_of(path: Path, want: str) -> dict[str, str] | None:
    """The evidence of an open publication in one ``op.json``, or None."""
    try:
        record = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    journal = cast(dict[str, Any], record).get("journal")
    if not isinstance(journal, list) or not journal:
        return None
    last = cast(list[Any], journal)[-1]
    if not isinstance(last, dict):
        return None
    entry = cast(dict[str, Any], last)
    if entry.get("phase") != "published" or entry.get("status") != "started":
        return None
    evidence = entry.get("evidence")
    if not isinstance(evidence, dict):
        return None
    fields = cast(dict[str, Any], evidence)
    if not all(isinstance(fields.get(key), str) for key in INTENT_FIELDS):
        return None
    intent = {key: cast(str, fields[key]) for key in INTENT_FIELDS}
    if _path_key(intent["repo"]) != want:
        return None
    return intent


def load_intents(common_dir: Path) -> list[dict[str, str]]:
    """The open publication intents of the run-parameters store of ``common_dir``.

    Reads ``ops/<plan>/<run>/<op>/op.json`` and the batch sub-ops
    ``ops/<plan>/<run>/<op>/<n>/op.json`` read-only, with no lock. An op is kept only
    when its last journal entry is ``published``/``started`` with all six evidence
    fields as strings and ``repo`` equal to ``common_dir`` (resolved, normcased). An
    unreadable op file holds no intent. No store gives ``[]``.
    """
    common = Path(common_dir)
    ops = _store(common) / "ops"
    if not ops.is_dir():
        return []
    want = _path_key(common)
    paths = sorted([*ops.glob("*/*/*/op.json"), *ops.glob("*/*/*/*/op.json")])
    intents: list[dict[str, str]] = []
    for path in paths:
        intent = _intent_of(path, want)
        if intent is not None:
            intents.append(intent)
    return intents


# ---------------------------------------------------------------------------
# The hook entry
# ---------------------------------------------------------------------------


def _common_dir(cwd: Path) -> Path:
    """The absolute git common dir of the repository git runs the hook in.

    The hook keeps git's own environment (``GIT_DIR`` names the repository).
    """
    proc = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=str(cwd),
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "git rev-parse --git-common-dir exited "
            f"{proc.returncode}: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return Path(proc.stdout.decode("utf-8", "surrogateescape").strip())


def _hook(phase: str, data: bytes, env: Mapping[str, str]) -> int:
    if phase != "prepared":
        return 0
    text = data.decode("utf-8", "surrogateescape")
    # git ends each line with LF; a Windows text pipe writes CRLF, so one trailing CR
    # per line is the line ending, not part of the ref name.
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    # The store and HALT matter only to main lines; a transaction without one is
    # decided on its lines alone, so the guard never opens the repository for it.
    names_main = any(
        (parsed := _parse_line(line)) is not None and parsed[2] == MAIN
        for line in lines
    )
    intents: list[dict[str, str]] = []
    halt = False
    if names_main and env.get(SWITCH) != "off":
        try:
            common = _common_dir(Path.cwd())
            halt = lanes._halted(common)
            intents = load_intents(common)
        except (OSError, RuntimeError) as exc:
            print(
                f"ref_guard refused: guard_error: {exc}; {MAIN} moves only through {ROUTE}",
                file=sys.stderr,
            )
            return EXIT_REFUSED
    reason = decide(phase, lines, intents, halt, env)
    if reason is None:
        return 0
    print(f"ref_guard refused: {reason}", file=sys.stderr)
    return EXIT_REFUSED


# ---------------------------------------------------------------------------
# The installer
# ---------------------------------------------------------------------------


def _parse_git_version(text: str) -> tuple[int, int, int]:
    """``(major, minor, patch)`` of ``git --version`` output.

    Raises:
        Refusal: ``git_version_bad`` when the text has no dotted version.
    """
    match = _VERSION_RE.search(text)
    if match is None:
        raise Refusal("git_version_bad", f"cannot read a git version from {text!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


# The variables that pick the system and global config files git reads.
_CONFIG_SCOPE_ENV = ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL")


def _hooks_env() -> dict[str, str]:
    """``rp._git_env`` that reads the system and global config as this process's git does.

    ``core.hooksPath`` can come from any config scope, so the hooks folder is found with
    the same system and global files that a git run from this environment uses (R1-F1).
    """
    env = rp._git_env()
    env.pop("GIT_CONFIG_NOSYSTEM", None)
    for key in _CONFIG_SCOPE_ENV:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _git(
    cwd: Path, *args: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=dict(env) if env is not None else rp._git_env(),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        raise Refusal("git_unavailable", str(exc)) from None


def _git_text(cwd: Path, *args: str) -> str:
    proc = _git(cwd, *args)
    if proc.returncode != 0:
        raise Refusal(
            "git_failed",
            f"git {' '.join(args)} exited {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}",
        )
    return proc.stdout.decode("utf-8", "surrogateescape").strip()


def _git_version(cwd: Path) -> tuple[int, int, int]:
    return _parse_git_version(_git_text(cwd, "--version"))


def _config_get(cwd: Path, common: Path, key: str) -> str | None:
    """A key of the repository config (``<common>/config``), or None when unset."""
    proc = _git(cwd, "config", "--file", str(common / "config"), "--get", key)
    if proc.returncode == 1:
        return None
    if proc.returncode != 0:
        raise Refusal(
            "config_unreadable",
            f"git config --get {key} exited {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}",
        )
    return proc.stdout.decode("utf-8", "surrogateescape").strip()


def _config_put(cwd: Path, common: Path, key: str, value: str | None) -> None:
    """Set ``key`` in the repository config, or unset it when ``value`` is None."""
    file = str(common / "config")
    if value is None:
        proc = _git(cwd, "config", "--file", file, "--unset", key)
        # 5: the key was not set, which is the wanted state.
        if proc.returncode in (0, 5):
            return
    else:
        proc = _git(cwd, "config", "--file", file, key, value)
        if proc.returncode == 0:
            return
    raise Refusal(
        "config_unwritable",
        f"git config {key} exited {proc.returncode}: "
        f"{proc.stderr.decode('utf-8', 'replace').strip()}",
    )


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    key = _path_key(path)
    for root in roots:
        base = _path_key(root)
        if key == base or key.startswith(base.rstrip(os.sep) + os.sep):
            return True
    return False


def _hooks_dir(top: Path, common: Path) -> Path:
    """The folder git runs hooks from, or a refusal when the guard cannot own it there.

    ``core.hooksPath`` is read from every scope git reads (system, global, repository).

    Raises:
        Refusal: ``hooks_path_unsupported`` for a ``core.hooksPath`` that is relative
            (it resolves in each worktree), outside the repository, or not a writable
            folder.
    """
    proc = _git(top, "config", "--get", "core.hooksPath", env=_hooks_env())
    if proc.returncode == 1:
        hooks = common / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        return hooks
    if proc.returncode != 0:
        raise Refusal(
            "config_unreadable", proc.stderr.decode("utf-8", "replace").strip()
        )
    raw = proc.stdout.decode("utf-8", "surrogateescape").strip()
    configured = Path(raw)
    if not configured.is_absolute():
        raise Refusal(
            "hooks_path_unsupported",
            f"core.hooksPath {raw!r} is relative, so each worktree runs its own folder; "
            "the human sets an absolute folder inside the repository or unsets it",
        )
    if not _inside(configured, (common, top)):
        raise Refusal(
            "hooks_path_unsupported",
            f"core.hooksPath {raw!r} is outside the repository; the guard does not "
            "install into a shared hooks folder",
        )
    if not configured.is_dir() or not os.access(configured, os.W_OK):
        raise Refusal(
            "hooks_path_unsupported", f"core.hooksPath {raw!r} is not a writable folder"
        )
    return configured


def _main_packed(common: Path) -> bool:
    """True when ``main`` is only in ``packed-refs`` (no loose ref file)."""
    if (common / "refs" / "heads" / "main").is_file():
        return False
    try:
        text = (common / "packed-refs").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False
    return any(line.split(" ")[-1] == MAIN for line in text.splitlines())


def _inventory_path(common: Path) -> Path:
    return lanes._lanes_dir(common) / lanes.GUARD_INVENTORY


def _load_inventory(common: Path) -> dict[str, Any] | None:
    """The install inventory, or None when there is none.

    Raises:
        Refusal: ``inventory_bad`` for a file that is not exactly the schema.
    """
    path = _inventory_path(common)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Refusal("inventory_bad", f"{path}: {exc}") from None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Refusal("inventory_bad", f"{path}: {exc}") from None
    if not isinstance(doc, dict) or set(cast(dict[str, Any], doc)) != INVENTORY_KEYS:
        raise Refusal("inventory_bad", f"{path}: keys must be {sorted(INVENTORY_KEYS)}")
    inv = cast(dict[str, Any], doc)
    previous = inv["previous"]
    ok = (
        inv["schema"] == INVENTORY_SCHEMA
        and all(
            isinstance(inv[key], str) and inv[key]
            for key in ("interpreter", "guard", "hook_path", "git_version", "installed")
        )
        and isinstance(inv["chained_local"], bool)
        and isinstance(previous, dict)
        and set(cast(dict[str, Any], previous)) == set(PREVIOUS_KEYS)
        and all(
            value is None or isinstance(value, str)
            for value in cast(dict[str, Any], previous).values()
        )
    )
    if not ok:
        raise Refusal(
            "inventory_bad", f"{path}: a field does not match {INVENTORY_SCHEMA}"
        )
    return inv


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _shim(interpreter: Path, guard: Path, local: Path) -> bytes:
    """The hook shim: run ``<hook>.local`` and the guard on the same stdin and argv."""
    run_guard = (
        f"{_sh_quote(interpreter.as_posix())} {_sh_quote(guard.as_posix())} hook"
    )
    text = (
        "#!/bin/sh\n"
        f"# The refs/heads/main guard, written by {SHIM_MARKER} install (MEU-784).\n"
        f"# Remove it with: python tools/{SHIM_MARKER} uninstall\n"
        f"local_hook={_sh_quote(local.as_posix())}\n"
        'if [ ! -e "$local_hook" ]; then\n'
        f'    exec {run_guard} "$@"\n'
        "fi\n"
        "input=$(mktemp) || exit 1\n"
        "trap 'rm -f \"$input\"' EXIT\n"
        'cat >"$input" || exit 1\n'
        '"$local_hook" "$@" <"$input"\n'
        "local_code=$?\n"
        f'{run_guard} "$@" <"$input"\n'
        "guard_code=$?\n"
        'if [ "$local_code" -ne 0 ]; then\n'
        '    exit "$local_code"\n'
        "fi\n"
        'exit "$guard_code"\n'
    )
    return text.encode("utf-8")


def _is_shim(path: Path) -> bool:
    try:
        return SHIM_MARKER.encode("utf-8") in path.read_bytes()
    except FileNotFoundError:
        return False


def _repo(cwd: Path) -> tuple[Path, Path]:
    try:
        return lanes._repo_dirs(cwd)
    except lanes.Refusal as exc:
        raise Refusal(exc.reason, exc.detail) from None


@contextlib.contextmanager
def _registry_lease(common: Path) -> Iterator[None]:
    """Hold the lanes registry lock, so one install or uninstall runs at a time (R1-F6).

    The hook entry never takes it (AC-784.14).

    Raises:
        Refusal: ``common_dir_unwritable`` or ``registry_busy``.
    """
    lanes_dir = lanes._lanes_dir(common)
    try:
        lanes_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Refusal(
            "common_dir_unwritable", f"cannot create {lanes_dir}: {exc}"
        ) from None
    try:
        lease = os_lease.acquire(
            lanes_dir / lanes.REGISTRY_LOCK,
            wait_s=lanes.REGISTRY_WAIT_S,
            body=lanes._lock_body(list(sys.argv)),
            poll_s=lanes.POLL_S,
        )
    except os_lease.Busy as busy:
        raise Refusal(
            "registry_busy", lanes._busy_detail(busy, lanes.REGISTRY_WAIT_S)
        ) from None
    except OSError as exc:
        raise Refusal(
            "common_dir_unwritable",
            f"cannot lock {lanes_dir / lanes.REGISTRY_LOCK}: {exc}",
        ) from None
    try:
        yield
    finally:
        os_lease.release(lease)


def _install(cwd: Path) -> int:
    if sys.platform != "win32":
        print(
            "not installed: no governed publish route "
            f"(the guard installs where {ROUTE} publishes, Windows only; design §9.2)"
        )
        return EXIT_NOT_INSTALLED
    version = _git_version(cwd)
    if version < MIN_GIT:
        raise Refusal(
            "git_too_old",
            f"git {'.'.join(map(str, version))} is below "
            f"{'.'.join(map(str, MIN_GIT))} (reference-transaction with symbolic-ref events)",
        )
    top, common = _repo(cwd)
    ref_format = _git_text(top, "rev-parse", "--show-ref-format")
    if ref_format != "files":
        raise Refusal(
            "reftable_unsupported",
            f"the ref backend is {ref_format!r}; the guard supports the files backend only",
        )
    hooks = _hooks_dir(top, common)
    with _registry_lease(common):
        return _install_hook(top, common, hooks, version)


def _install_hook(
    top: Path, common: Path, hooks: Path, version: tuple[int, int, int]
) -> int:
    """Write the shim, chain a foreign hook and set the config; the caller holds the lease."""
    if _main_packed(common):
        raise Refusal(
            "main_packed",
            f"{MAIN} is only in packed-refs. One-time human step: write the id of "
            f"`git rev-parse {MAIN}` and a newline to {(common / MAIN).as_posix()}, "
            "then run install again",
        )
    hook = hooks / HOOK_NAME
    local = hooks / f"{HOOK_NAME}{LOCAL_SUFFIX}"
    ours = _is_shim(hook)
    if not ours and local.exists():
        raise Refusal(
            "local_exists",
            f"{local.as_posix()} exists and {hook.as_posix()} is not the guard shim; "
            "the human merges or removes one of them",
        )
    existing = _load_inventory(common)
    if existing is not None:
        previous = cast(dict[str, str | None], existing["previous"])
        installed = cast(str, existing["installed"])
    else:
        previous = {key: _config_get(top, common, key) for key in PREVIOUS_KEYS}
        installed = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    interpreter = Path(sys.executable)
    guard = Path(__file__).resolve()
    undo: list[tuple[str, Any]] = []
    try:
        for key in PREVIOUS_KEYS:
            before = _config_get(top, common, key)
            _config_put(top, common, key, "false")
            undo.append(("config", (key, before)))
        if hook.exists() and not ours:
            os.replace(hook, local)
            undo.append(("move", (local, hook)))
        lanes._replace_atomically(hook, _shim(interpreter, guard, local))
        if not ours:
            undo.append(("shim", hook))
        os.chmod(hook, 0o755)
        inventory = {
            "schema": INVENTORY_SCHEMA,
            "interpreter": str(interpreter),
            "guard": str(guard),
            "hook_path": str(hook),
            "chained_local": local.exists(),
            "previous": previous,
            "git_version": ".".join(map(str, version)),
            "installed": installed,
        }
        target = _inventory_path(common)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(inventory, indent=2) + "\n").encode("utf-8")
        lanes._replace_atomically(target, data)
    except (OSError, Refusal) as exc:
        _undo(top, common, undo)
        if isinstance(exc, Refusal):
            raise
        raise Refusal("install_failed", str(exc)) from None
    print(f"installed: {hook.as_posix()} chained_local={str(local.exists()).lower()}")
    return 0


def _undo(top: Path, common: Path, undo: list[tuple[str, Any]]) -> None:
    """Best-effort rollback of a failed install, newest step first."""
    for kind, item in reversed(undo):
        try:
            if kind == "config":
                key, before = item
                _config_put(top, common, key, before)
            elif kind == "move":
                src, dst = item
                os.replace(src, dst)
            elif kind == "shim":
                Path(item).unlink(missing_ok=True)
        except (OSError, Refusal) as exc:
            print(f"rollback incomplete: {kind}: {exc}", file=sys.stderr)


def _uninstall(cwd: Path) -> int:
    top, common = _repo(cwd)
    with _registry_lease(common):
        return _uninstall_hook(top, common)


def _uninstall_hook(top: Path, common: Path) -> int:
    """Undo an install; the caller holds the lease.

    The steps run config, then hook, then inventory, so an uninstall that stops at
    any step leaves the inventory and a retry finishes it (R1-F5). A foreign hook with
    ``chained_local`` and no ``<hook>.local`` is the chained hook already put back.
    """
    inv = _load_inventory(common)
    if inv is None:
        print("not installed")
        return 0
    hook = Path(cast(str, inv["hook_path"]))
    local = hook.with_name(f"{HOOK_NAME}{LOCAL_SUFFIX}")
    restored = (
        hook.exists()
        and not _is_shim(hook)
        and cast(bool, inv["chained_local"])
        and not local.exists()
    )
    if hook.exists() and not _is_shim(hook) and not restored:
        raise Refusal(
            "hook_not_ours",
            f"{hook.as_posix()} is not the guard shim; the human restores the hooks folder",
        )
    previous = cast(dict[str, str | None], inv["previous"])
    for key in PREVIOUS_KEYS:
        _config_put(top, common, key, previous[key])
    if local.exists():
        os.replace(local, hook)
    elif not restored:
        hook.unlink(missing_ok=True)
    _inventory_path(common).unlink()
    print(f"uninstalled: {hook.as_posix()}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ref_guard.py",
        description="The refs/heads/main reference-transaction guard (MEU-784).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    hook = sub.add_parser("hook", help="the reference-transaction hook entry")
    hook.add_argument("phase")
    sub.add_parser("install", help="install the hook shim (Windows only)")
    sub.add_parser("uninstall", help="remove the shim and restore what install changed")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: bytes | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run one command; ``stdin`` and ``env`` default to the process's own."""
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    if args.command == "hook":
        data = stdin if stdin is not None else sys.stdin.buffer.read()
        return _hook(args.phase, data, env if env is not None else os.environ)
    try:
        if args.command == "install":
            return _install(Path.cwd())
        return _uninstall(Path.cwd())
    except Refusal as exc:
        print(f"refused: {exc.reason}")
        if exc.detail:
            print(exc.detail)
        return EXIT_REFUSED
    except OSError as exc:
        print("refused: io_error")
        print(str(exc))
        return EXIT_REFUSED


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
