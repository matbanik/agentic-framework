#!/usr/bin/env python3
"""instantiate.py -- fill the framework's placeholders with YOUR project's values.

THIS is the script an adopting agent/team runs. After copying the framework into a new
project, run it once to replace every ``{{PLACEHOLDER}}`` token with concrete values.

What it replaces
----------------
    {{PROJECT_NAME}}         your project slug, lower-case      e.g. acme
    {{PROJECT_NAME_TITLE}}   Title-case (derived unless given)  e.g. Acme
    {{PROJECT_NAME_UPPER}}   UPPER-case (derived unless given)  e.g. ACME  (used in env vars)
    {{PROJECT_ROOT}}         absolute path to the project root  e.g. /home/you/acme  or  P:\acme
    {{RECEIPTS_DIR}}         where shell output is redirected   e.g. /tmp/acme  or  C:/Temp/acme
    {{REPO_URL}}             host/owner/repo (no scheme)        e.g. github.com/you/acme

Usage
-----
Provide values via flags, or a KEY=VALUE config file, or both (flags win):

    python scripts/instantiate.py \
        --project-name acme \
        --project-root /home/you/acme \
        --receipts-dir /tmp/acme \
        --repo-url github.com/you/acme

    # or, from a config file (KEY=VALUE lines; keys are the flag names upper-cased):
    python scripts/instantiate.py --config framework.vars

Always dry-run first:

    python scripts/instantiate.py --config framework.vars --dry-run
    python scripts/instantiate.py --config framework.vars            # apply
    python scripts/instantiate.py --verify                           # assert no {{TOKENS}} left

By default the script **refuses** to run without `--root` (the copied adopter
tree). `--in-place-package` is the only way to rewrite this transfer package;
the two flags together refuse. If you copied ``core/`` into your project first:

    python scripts/instantiate.py --root /path/to/your-project --config framework.vars

Config file example (framework.vars)
------------------------------------
    PROJECT_NAME=acme
    PROJECT_ROOT=/home/you/acme
    RECEIPTS_DIR=/tmp/acme
    REPO_URL=github.com/you/acme
    # optional overrides if simple casing is wrong (e.g. an acronym):
    # PROJECT_NAME_TITLE=ACME Corp
    # PROJECT_NAME_UPPER=ACMECORP
    # optional: who may start a scheduled credits run (default human-only):
    # CREDITS_START_POLICY=agent-on-user-chat

Scheduled credits runs (optional, Windows-only)
-----------------------------------------------
When the adopter tree holds ``.claude/settings.hooks.json``, the installer merges its hook
entries into ``.claude/settings.json``: additive, idempotent, prior entries first and
unchanged. An invalid ``settings.json`` is refused before any write. On any OS other
than Windows the installer refuses the scheduler: it removes the Windows-only files and
writes no ``credits_inbox.py`` hook entry; ``--verify`` checks that refusal. The receipts
directory must be local, because the credits store is SQLite in WAL mode: a UNC path is
refused. ``--credits-start-policy`` writes the answer into ``.agent/credits/config.json``.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import placeholders as ph  # noqa: E402

TEXT_SUFFIXES = {
    ".md",
    ".yaml",
    ".yml",
    ".ps1",
    ".py",
    ".txt",
    ".json",
    ".toml",
    ".cfg",
    ".ini",
    ".sh",
    ".ts",
    ".tsx",
    ".js",
    ".svg",
    ".html",
    ".css",
    ".psm1",
    ".psd1",
}
#: Directory names skipped at *any* depth: build artefacts and VCS metadata, none of which
#: an adopter edits or ships.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
#: Paths skipped only at the top level of the package, as relative POSIX prefixes.
#:
#: ``scripts/`` is the installer itself and is not copied into an adopter's project, so its
#: tokens must not be substituted. It used to live in SKIP_DIRS, which matched *any* path
#: component named ``scripts`` -- and the package ships
#: ``.agent/skills/git-workflow/scripts/agent-commit.{sh,ps1}``. Those two executables were
#: therefore installed with ``{{PROJECT_NAME}}`` still in them, in an allowed-signers path
#: and a temp-index filename, while ``--verify`` reported the tree clean: verify walks the
#: same traversal, so it never looked at the files it was supposed to be checking.
SKIP_TOP_LEVEL = {"scripts"}
#: Adopter-owned paths the installer must not rewrite even when they contain tokens.
ADOPTER_OWNED_NAMES = {"PROJECT-PROFILE.md"}
ADOPTER_OWNED_DIR_PREFIXES = ("_probe/",)
#: After ADOPTION-GUIDE copy, only these prefixes/files are framework-installed.
#: Everything else (user notes, app templates, docs the adopter already had) is
#: outside the inventory even if it contains ``{{PROJECT_NAME}}``.
ADOPTER_INSTALLED_PREFIXES = (
    ".agent/",
    "tools/",
    ".cursor/agents/",
    ".claude/agents/",
    ".claude/hooks/",
)
#: Single framework files below the root. The adopter's own ``.claude/settings.json``
#: is not one: the installer merges into it and never substitutes it.
ADOPTER_INSTALLED_FILES = {".claude/settings.hooks.json"}
ADOPTER_INSTALLED_ROOT_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    "GUARDRAILS.md",
    "MANIFEST.md",
}
#: ``--in-place-package`` rewrites the transfer package, not an adopter tree.
PACKAGE_INSTALLED_PREFIXES = ("core/", ".agent/")
PACKAGE_INSTALLED_ROOT_FILES = {
    "ADOPTION-GUIDE.md",
    "ADOPTION-QUESTIONS.md",
    "PROJECT-PROFILE-TEMPLATE.md",
    "README.md",
    "UPDATE-CHECKLIST.md",
    "MANIFEST.md",
}
#: Every ``{{PROJECT_NAME}}-<role>.md`` in these folders is renamed to ``<slug>-<role>.md``.
AGENT_DEF_FOLDERS = (".cursor/agents", ".claude/agents")
AGENT_DEF_PREFIX = "{{PROJECT_NAME}}-"
BOM = b"\xef\xbb\xbf"

CONFIG_KEYS = {
    "PROJECT_NAME": "project_name",
    "PROJECT_ROOT": "project_root",
    "RECEIPTS_DIR": "receipts_dir",
    "REPO_URL": "repo_url",
    "PROJECT_NAME_TITLE": "project_name_title",
    "PROJECT_NAME_UPPER": "project_name_upper",
    "CREDITS_START_POLICY": "credits_start_policy",
}

# --- scheduled credits runs ---------------------------------------------------------------
#: The hook fragment the package ships and the adopter settings file it merges into.
HOOK_FRAGMENT = ".claude/settings.hooks.json"
HOOK_SETTINGS = ".claude/settings.json"
CREDITS_CONFIG = ".agent/credits/config.json"
#: Who may start a scheduled run. ``human-only`` is the default the template ships.
CREDITS_START_POLICIES = ("human-only", "agent-on-user-chat")
#: The scheduler needs Task Scheduler, Job Objects and named mutexes. On any other OS
#: these files are removed; the store, the stop gate and the worktree helper stay.
WINDOWS_ONLY_MESSAGE = "REFUSED: scheduled credits runs are Windows-only"
WINDOWS_ONLY_FILES = (
    "tools/credits_msg.py",
    ".claude/hooks/credits_inbox.py",
    # The tests of the removed files, which would otherwise fail to import them.
    "tools/tests/test_credits_inbox.py",
    "tools/tests/test_credits_msg.py",
    "tools/tests/test_credits_port.py",
    "tools/tests/test_credits_ruling.py",
    "tools/tests/test_credits_stop_reminder.py",
    "tools/tests/test_credits_wait.py",
    "tools/tests/test_credits_authority.py",
    "tools/tests/test_credits_phases.py",
    "tools/tests/test_credits_r1_fixes_inbox.py",
    "tools/tests/test_credits_r1_fixes_locate.py",
    "tools/tests/test_credits_r1_fixes_tree.py",
    "tools/tests/ClaudeCredits.Manual.Tests.ps1",
    "tools/tests/ClaudeCredits.Wrapper.Tests.ps1",
    "tools/tests/CreditsChain.Tests.ps1",
    "tools/tests/CreditsLauncherEnv.Tests.ps1",
    "tools/tests/CreditsR1Fixes.KeyFile.Tests.ps1",
    "tools/tests/CreditsR1Fixes.Project.Tests.ps1",
    "tools/tests/CreditsR1Fixes.Watch.Tests.ps1",
    "tools/tests/CreditsR2Fixes.Register.Tests.ps1",
    "tools/tests/CreditsRuling.Tests.ps1",
    "tools/tests/CreditsRun.Job.Tests.ps1",
    "tools/tests/CreditsStopPath.Tests.ps1",
    "tools/tests/CreditsTaskReadback.Tests.ps1",
    "tools/tests/Get-CreditsRun.Settle.Tests.ps1",
    "tools/tests/Get-CreditsRun.Tests.ps1",
    "tools/tests/Register-CreditsRun.Tests.ps1",
    "tools/tests/Send-CreditsRunMessage.Tests.ps1",
    "tools/tests/Start-CreditsRun.Tests.ps1",
    "tools/tests/Start-CreditsRunTask.Tests.ps1",
    "tools/tests/Start-CreditsRunTask.Policy.Tests.ps1",
    "tools/tests/Watch-CreditsRuns.Tests.ps1",
    "tools/tests/Watch-CreditsRuns.Phase.Tests.ps1",
)
#: Run parameters list five of the files above in ``run_parameters.py``
#: ``REQUIRED_COMPONENTS``, so on any other OS they stay ``disabled`` (fail closed, the manual
#: workflow). Their tests build an activated fixture from those files, so they go too.
RUN_PARAMETERS_WINDOWS_ONLY = (
    "tools/tests/run_parameters_fixtures",
    "tools/tests/test_agent_commit.py",
    "tools/tests/test_commit_batch.py",
    "tools/tests/test_run_parameters.py",
    "tools/tests/test_run_parameters_r1_corrections.py",
    "tools/tests/test_run_parameters_r2_corrections.py",
    "tools/tests/test_stop_gate_run_parameters.py",
    "tools/tests/test_validate_agent_files_policy.py",
    "tools/tests/test_validate_closeout_stages.py",
    "tools/tests/test_worktree_layout.py",
)
#: The skill folder is removed except these children (the probes are portable Python).
WINDOWS_ONLY_DIR = ".agent/skills/claude-credits"
WINDOWS_ONLY_KEEP = ("probes",)
#: A hook command that holds this text is a Windows-only entry.
WINDOWS_ONLY_HOOK = "credits_inbox"
#: Where an installed tree records its receipts directory: the store path default.
RECEIPTS_PROBE_FILE = ".agent/skills/claude-credits/Register-CreditsRun.ps1"
RECEIPTS_PROBE_RE = re.compile(r"'([^'\n]*)/credits/state\.db'")


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def read_config(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE file. Blank lines and #-comments ignored."""
    out: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{lineno}: expected KEY=VALUE, got: {raw!r}")
        key, _, value = line.partition("=")
        key = key.strip().upper()
        if key not in CONFIG_KEYS:
            raise ValueError(f"{path}:{lineno}: unknown key {key!r}")
        out[CONFIG_KEYS[key]] = value.strip()
    return out


def iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        if parts and parts[0] in SKIP_TOP_LEVEL:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def is_adopter_owned(rel: Path) -> bool:
    posix = rel.as_posix()
    if rel.name in ADOPTER_OWNED_NAMES:
        return True
    if posix.startswith(ADOPTER_OWNED_DIR_PREFIXES) or "/_probe/" in f"/{posix}":
        return True
    return False


def is_framework_installed(rel: Path, *, in_place: bool) -> bool:
    posix = rel.as_posix()
    if in_place:
        prefixes = PACKAGE_INSTALLED_PREFIXES
        roots = PACKAGE_INSTALLED_ROOT_FILES
    else:
        prefixes = ADOPTER_INSTALLED_PREFIXES
        roots = ADOPTER_INSTALLED_ROOT_FILES
    if rel.name in roots and len(rel.parts) == 1:
        return True
    if not in_place and posix in ADOPTER_INSTALLED_FILES:
        return True
    return posix.startswith(prefixes)


def iter_owned_text_files(root: Path, *, in_place: bool = False):
    for path in iter_text_files(root):
        rel = path.relative_to(root)
        if is_adopter_owned(rel):
            continue
        if not is_framework_installed(rel, in_place=in_place):
            continue
        yield path


def planned_agent_renames(root: Path, slug: str) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for folder in AGENT_DEF_FOLDERS:
        agents = root / folder
        if not agents.is_dir():
            continue
        for src in sorted(agents.iterdir()):
            if not (src.is_file() and src.name.startswith(AGENT_DEF_PREFIX)):
                continue
            if src.suffix != ".md":
                continue
            role = src.name[len(AGENT_DEF_PREFIX) :]
            pairs.append((src, agents / f"{slug}-{role}"))
    return pairs


def refuse_rename_collisions(pairs: list[tuple[Path, Path]]) -> None:
    for src, dst in pairs:
        if dst.exists() and dst.resolve() != src.resolve():
            raise ValueError(
                f"refusing to rename {src.name} -> {dst.name}: destination exists "
                "(collision before any write)"
            )


def read_text_preserve(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(BOM)
    return raw.decode("utf-8-sig"), bom


def write_text_preserve(path: Path, text: str, bom: bool) -> None:
    data = text.encode("utf-8")
    if bom:
        data = BOM + data
    path.write_bytes(data)


def scheduler_supported() -> bool:
    """True when the scheduled credits runs can work on this OS (Windows only).

    Read at call time, so a test can set ``sys.platform``.
    """
    return sys.platform == "win32"


def is_network_path(path: str) -> bool:
    """True for a UNC path: ``\\\\server\\share`` or ``//server/share``.

    The credits store is SQLite in WAL mode, which needs a local file system. A mapped
    drive letter cannot be told apart from a local disk without a system call, so it is
    not refused here; ADOPTION-GUIDE.md tells the adopter to use a local disk.
    """
    return path.replace("\\", "/").startswith("//")


def _hook_entries(settings: dict[str, object], label: str) -> list[tuple[str, str, str]]:
    """Each hook entry of a settings document as (event, matcher, command), in order.

    Raises:
        ValueError: the ``hooks`` value does not have the Claude Code settings shape.
    """
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{label}: 'hooks' is not an object")
    out: list[tuple[str, str, str]] = []
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise ValueError(f"{label}: hooks.{event} is not a list")
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError(f"{label}: a hooks.{event} group is not an object")
            matcher = group.get("matcher", "")
            entries = group.get("hooks", [])
            if not isinstance(matcher, str) or not isinstance(entries, list):
                raise ValueError(f"{label}: a hooks.{event} group has a bad matcher or hooks")
            for hook in entries:
                if not isinstance(hook, dict):
                    raise ValueError(f"{label}: a hooks.{event} entry is not an object")
                command = hook.get("command")
                if isinstance(command, str):
                    out.append((event, matcher, command))
    return out


def merge_hook_settings(
    settings: dict[str, object], fragment: dict[str, object]
) -> dict[str, object]:
    """Return ``settings`` with each ``fragment`` hook entry added once.

    An entry is the same when its event, matcher and command are the same. The prior
    entries keep their order and come first; an entry already present is not added
    again, so a second merge returns an equal document. Neither input is changed.

    Raises:
        ValueError: either document does not have the Claude Code settings shape.
    """
    merged = copy.deepcopy(settings)
    present = set(_hook_entries(merged, HOOK_SETTINGS))
    _hook_entries(fragment, HOOK_FRAGMENT)
    hooks = merged.setdefault("hooks", {})
    assert isinstance(hooks, dict)  # checked by _hook_entries above
    fragment_hooks = fragment.get("hooks", {})
    assert isinstance(fragment_hooks, dict)
    for event, groups in fragment_hooks.items():
        for group in groups:
            matcher = group.get("matcher", "")
            fresh = [
                hook
                for hook in group.get("hooks", [])
                if (event, matcher, hook.get("command")) not in present
            ]
            if not fresh:
                continue
            new_group = {k: copy.deepcopy(v) for k, v in group.items() if k != "hooks"}
            new_group["hooks"] = copy.deepcopy(fresh)
            hooks.setdefault(event, []).append(new_group)
            present.update((event, matcher, hook.get("command")) for hook in fresh)
    return merged


def _portable_fragment(fragment: dict[str, object]) -> dict[str, object]:
    """The fragment without its Windows-only entries; empty groups and events dropped."""
    out = copy.deepcopy(fragment)
    hooks = out.get("hooks", {})
    if not isinstance(hooks, dict):
        return out
    for event in list(hooks):
        kept = []
        for group in hooks[event]:
            group["hooks"] = [
                hook
                for hook in group.get("hooks", [])
                if WINDOWS_ONLY_HOOK not in str(hook.get("command", ""))
            ]
            if group["hooks"]:
                kept.append(group)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    return out


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    """Parse a JSON file whose top level must be an object.

    Raises:
        ValueError: the file is not UTF-8, not JSON, or not an object.
    """
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}: not valid JSON ({exc})") from None
    if not isinstance(data, dict):
        raise ValueError(f"{label}: the top level is not a JSON object")
    return data


def _json_bytes(data: dict[str, object]) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _expected_fragment(root: Path) -> dict[str, object] | None:
    """The hook entries this OS must have, or None when the tree ships no fragment."""
    path = root / HOOK_FRAGMENT
    if not path.is_file():
        return None
    fragment = _load_json_object(path, HOOK_FRAGMENT)
    return fragment if scheduler_supported() else _portable_fragment(fragment)


def windows_only_present(root: Path) -> list[Path]:
    """The Windows-only paths that exist in ``root``: files, run-parameters tests and
    skill-folder children."""
    out = [root / rel for rel in WINDOWS_ONLY_FILES if (root / rel).is_file()]
    out.extend(root / rel for rel in RUN_PARAMETERS_WINDOWS_ONLY if (root / rel).exists())
    skill = root / WINDOWS_ONLY_DIR
    if skill.is_dir():
        out.extend(
            child for child in sorted(skill.iterdir()) if child.name not in WINDOWS_ONLY_KEEP
        )
    return out


class _CreditsPlan:
    """What ``run`` will do to the credits files, computed before any write."""

    def __init__(self) -> None:
        self.removals: list[Path] = []
        self.settings_bytes: bytes | None = None
        self.added_entries = 0
        self.config_bytes: bytes | None = None


def _plan_credits(root: Path, policy: str | None) -> _CreditsPlan:
    """Plan the hook merge, the non-Windows refusal and the start-policy answer.

    Raises:
        ValueError: an invalid ``settings.json``, fragment or ``config.json``, or a
            policy answer with no ``config.json`` to hold it.
    """
    plan = _CreditsPlan()
    if not scheduler_supported():
        plan.removals = windows_only_present(root)

    fragment = _expected_fragment(root)
    if fragment is not None:
        settings_path = root / HOOK_SETTINGS
        prior: dict[str, object] = {}
        if settings_path.exists():
            prior = _load_json_object(settings_path, HOOK_SETTINGS)
        merged = merge_hook_settings(prior, fragment)
        plan.added_entries = len(_hook_entries(merged, HOOK_SETTINGS)) - len(
            _hook_entries(prior, HOOK_SETTINGS)
        )
        if merged != prior or not settings_path.exists():
            plan.settings_bytes = _json_bytes(merged)

    if policy is not None:
        config_path = root / CREDITS_CONFIG
        if not config_path.is_file():
            raise ValueError(
                f"credits_start_policy needs {CREDITS_CONFIG}; copy core/.agent first"
            )
        config = _load_json_object(config_path, CREDITS_CONFIG)
        if config.get("credits_start_policy") != policy:
            config["credits_start_policy"] = policy
            plan.config_bytes = _json_bytes(config)
    return plan


def _remove(path: Path) -> None:
    """Remove a file or a whole folder; never follow a link into its target."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _credits_problems(root: Path, receipts_dir: str | None) -> list[str]:
    """The ``--verify`` findings for the credits install, one line each."""
    problems: list[str] = []
    if receipts_dir is not None and is_network_path(receipts_dir):
        problems.append(
            f"receipts dir {receipts_dir} is a network path; the credits store needs a local disk"
        )
    probe = root / RECEIPTS_PROBE_FILE
    if probe.is_file():
        found = RECEIPTS_PROBE_RE.search(read_text_preserve(probe)[0])
        if found and "{{" not in found.group(1) and is_network_path(found.group(1)):
            problems.append(
                f"{RECEIPTS_PROBE_FILE}: the installed receipts dir {found.group(1)} is a "
                "network path; the credits store needs a local disk"
            )

    if not scheduler_supported():
        for path in windows_only_present(root):
            rel = path.relative_to(root).as_posix()
            problems.append(f"{rel}: {WINDOWS_ONLY_MESSAGE}, but the file is present")

    try:
        fragment = _expected_fragment(root)
    except ValueError as exc:
        return problems + [str(exc)]
    settings_path = root / HOOK_SETTINGS
    if fragment is None and not settings_path.exists():
        return problems
    try:
        have = (
            _hook_entries(_load_json_object(settings_path, HOOK_SETTINGS), HOOK_SETTINGS)
            if settings_path.exists()
            else []
        )
    except ValueError as exc:
        return problems + [str(exc)]
    if fragment is not None:
        for event, matcher, command in _hook_entries(fragment, HOOK_FRAGMENT):
            if (event, matcher, command) not in have:
                problems.append(
                    f"{HOOK_SETTINGS}: missing hook entry {event} [{matcher or '-'}] {command}"
                )
    if not scheduler_supported():
        for event, matcher, command in have:
            if WINDOWS_ONLY_HOOK in command:
                problems.append(
                    f"{HOOK_SETTINGS}: {WINDOWS_ONLY_MESSAGE}, but {event} runs {command}"
                )
    return problems


def verify_only(
    root: Path, *, in_place: bool = False, receipts_dir: str | None = None
) -> int:
    """Report placeholder tokens left, and the credits install checks.

    For an adopter tree it also checks that each hook entry the fragment holds for this
    OS is in ``.claude/settings.json``, that the non-Windows refusal holds, and that the
    receipts directory (given, or installed in the store path) is not a network path.
    """
    token_re = re.compile("|".join(re.escape(t) for t in ph.PLACEHOLDER_TOKENS))
    offenders: list[tuple[str, int]] = []
    for path in iter_owned_text_files(root, in_place=in_place):
        try:
            text, _bom = read_text_preserve(path)
        except UnicodeDecodeError:
            continue
        hits = len(token_re.findall(text))
        if hits:
            offenders.append((path.relative_to(root).as_posix(), hits))
    leftover_token_names = [
        p.relative_to(root).as_posix()
        for p in iter_owned_text_files(root, in_place=in_place)
        if "{{PROJECT_NAME}}" in p.name
    ]
    if leftover_token_names:
        for rel in leftover_token_names:
            offenders.append((rel, 1))
    problems = [] if in_place else _credits_problems(root, receipts_dir)
    if offenders:
        print(f"VERIFY FAILED: {len(offenders)} file(s) still contain placeholders:")
        for rel, cnt in offenders:
            print(f"  {cnt:>4}  {rel}")
    if problems:
        print(f"VERIFY FAILED: {len(problems)} credits install problem(s):")
        for line in problems:
            print(f"  {line}")
    if offenders or problems:
        return 2
    print("verify: OK (0 placeholder tokens remain)")
    return 0


def run(
    values: dict[str, str],
    dry_run: bool,
    root: Path,
    *,
    in_place: bool = False,
    credits_start_policy: str | None = None,
) -> int:
    """Substitute the tokens, rename the agent files and install the credits pieces.

    ``credits_start_policy`` (or ``values["credits_start_policy"]`` from a config file;
    the argument wins) is written to ``.agent/credits/config.json``; None keeps the
    template answer. Every check runs before the first write.

    Raises:
        ValueError: a bad value, a rename collision, a network receipts directory, an
            unknown policy, or an invalid settings, fragment or config file.
    """
    values = dict(values)
    policy = values.pop("credits_start_policy", None)
    if credits_start_policy is not None:
        policy = credits_start_policy
    if policy is not None and policy not in CREDITS_START_POLICIES:
        raise ValueError(
            f"credits_start_policy {policy!r} is not one of {', '.join(CREDITS_START_POLICIES)}"
        )
    receipts = values.get("receipts_dir", "")
    if is_network_path(receipts):
        raise ValueError(
            f"receipts dir {receipts} is a network path; the credits store (SQLite WAL) "
            "needs a local disk"
        )
    mapping = ph.derive_values(**values)
    slug = mapping["{{PROJECT_NAME}}"]
    pairs = planned_agent_renames(root, slug)
    refuse_rename_collisions(pairs)
    credits = _CreditsPlan() if in_place else _plan_credits(root, policy)
    removed = set(credits.removals)

    print("Placeholder -> value:")
    for token in ph.PLACEHOLDER_TOKENS:
        print(f"  {token:<24} {mapping[token]}")
    print()

    total_files = changed_files = total_repl = 0
    planned: list[tuple[Path, str, bool, int]] = []
    for path in iter_owned_text_files(root, in_place=in_place):
        if path in removed or any(parent in removed for parent in path.parents):
            continue
        total_files += 1
        try:
            original, bom = read_text_preserve(path)
        except UnicodeDecodeError:
            continue
        new_text, n = ph.apply_reverse(original, mapping)
        if n:
            changed_files += 1
            total_repl += n
            print(f"  {n:>4}  {path.relative_to(root).as_posix()}")
            planned.append((path, new_text, bom, n))

    for src, dst in pairs:
        print(f"  rename {src.relative_to(root).as_posix()} -> {dst.name}")
    if credits.removals:
        print(f"\n{WINDOWS_ONLY_MESSAGE} (sys.platform is {sys.platform}); removing:")
        for path in credits.removals:
            print(f"  remove {path.relative_to(root).as_posix()}")
    if credits.settings_bytes is not None:
        print(f"  merge  {HOOK_FRAGMENT} -> {HOOK_SETTINGS} ({credits.added_entries} added)")
    if credits.config_bytes is not None:
        print(f"  write  {CREDITS_CONFIG} credits_start_policy={policy}")

    if not dry_run:
        for path, new_text, bom, _n in planned:
            write_text_preserve(path, new_text, bom)
        for src, dst in pairs:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.replace(dst)
        for path in credits.removals:
            _remove(path)
        if credits.settings_bytes is not None:
            settings_path = root / HOOK_SETTINGS
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_bytes(credits.settings_bytes)
        if credits.config_bytes is not None:
            (root / CREDITS_CONFIG).write_bytes(credits.config_bytes)

    mode = "DRY-RUN (no files written)" if dry_run else "APPLIED"
    print("\n" + "=" * 60)
    print(f"  mode:          {mode}")
    print(f"  files scanned: {total_files}")
    print(f"  files changed: {changed_files}")
    print(f"  replacements:  {total_repl}")
    print(f"  renames:       {len(pairs)}")
    print(f"  removed:       {len(credits.removals)} (Windows-only)")
    print(f"  hook entries:  {credits.added_entries} added")
    print("=" * 60)
    if not dry_run:
        print("Next: re-run with --verify to confirm no placeholders remain.")
    return 0


def selftest() -> int:
    """Prove the derived values are usable *as code*, not just non-empty.

    ``{{PROJECT_NAME_UPPER}}`` lands inside identifiers such as
    ``$env:{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR``. Deriving it with ``.upper()`` alone
    turned the hyphenated slug ``my-project`` into ``$env:MY-PROJECT_AUTHOR_VENDOR``,
    which PowerShell reads as subtraction -- the dispatch wrapper stopped parsing
    entirely, and nothing in this script's output said so, because every token *had*
    been substituted. ``--verify`` therefore cannot catch this class on its own: the
    end-to-end arm below substitutes into a real wrapper fragment and checks the
    result is a legal identifier.
    """
    import tempfile

    ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    arms: list[tuple[str, bool]] = []

    def check(label: str, ok: bool) -> None:
        arms.append((label, ok))
        print(f"{'PASS' if ok else 'FAIL'} {label}")

    # ``env_identifier`` is the repair function, so it is exercised directly and given the
    # pathological spellings -- including ones ``derive_values`` now refuses outright
    # (``a b``). Routing those through ``derive_values`` instead would have made this loop
    # a test of the *refusal*, silently dropping all coverage of the repair.
    for slug in ("acme", "my-project", "agentic-framework", "my.project", "a b", "2fast"):
        upper = ph.env_identifier(slug)
        check(f"upper-is-an-identifier[{slug}] -> {upper}", bool(ident.match(upper)))

    # ...and the wiring, so the arms above cannot pass while nothing calls the helper.
    check(
        "derive-routes-name-through-env-identifier",
        ph.derive_values("my-project", "/r", "/t", "h/o/r")["{{PROJECT_NAME_UPPER}}"]
        == ph.env_identifier("my-project")
        == "MY_PROJECT",
    )

    # A bad explicit override must be refused, not repaired.
    try:
        ph.derive_values("acme", "/r", "/t", "h/o/r", project_name_upper="BAD-NAME")
        check("bad-upper-override-refused", False)
    except ValueError:
        check("bad-upper-override-refused", True)
    try:
        got = ph.derive_values(
            "acme", "/r", "/t", "h/o/r", project_name_upper="ACME_CORP"
        )["{{PROJECT_NAME_UPPER}}"]
        check("good-upper-override-honoured", got == "ACME_CORP")
    except ValueError:
        check("good-upper-override-honoured", False)

    # ``{{PROJECT_ROOT}}`` and ``{{RECEIPTS_DIR}}`` land in code too -- single-quoted
    # PowerShell literals such as ``WorkingDirectory = '{{PROJECT_ROOT}}'``. An
    # apostrophe there closes the literal early and the wrapper stops parsing, while
    # this script and ``--verify`` both return 0 because every token *was* substituted.
    # Same class as the identifier arms above, one token over.
    for label, kwargs in (
        ("apostrophe-in-root", {"project_root": "/home/o'brien/proj"}),
        ("quote-in-receipts", {"receipts_dir": '/tmp/"x"'}),
        ("backtick-in-root", {"project_root": "/tmp/a`b"}),
        ("dollar-in-receipts", {"receipts_dir": "/tmp/$HOME"}),
        ("newline-in-root", {"project_root": "/tmp/a\nb"}),
        ("space-in-project-name", {"project_name": "my project"}),
        ("quote-in-project-name", {"project_name": "o'brien"}),
    ):
        base = {
            "project_name": "acme",
            "project_root": "/r",
            "receipts_dir": "/t",
            "repo_url": "h/o/r",
        }
        base.update(kwargs)
        try:
            ph.derive_values(**base)
            check(f"code-position-value-refused[{label}]", False)
        except ValueError:
            check(f"code-position-value-refused[{label}]", True)

    # The mirror: values that ARE supportable must still work, or the refusals above
    # are just a broken installer. A space in a *path* is ordinary on both platforms,
    # and a Windows path arrives with backslashes -- which are normalised, not refused.
    ok_values = ph.derive_values(
        "acme", r"P:\Program Files\acme", "C:/Temp/My Receipts", "github.com/you/acme"
    )
    check(
        f"space-in-path-accepted -> {ok_values['{{RECEIPTS_DIR}}']}",
        ok_values["{{RECEIPTS_DIR}}"] == "C:/Temp/My Receipts",
    )
    check(
        f"backslash-path-normalised -> {ok_values['{{PROJECT_ROOT}}']}",
        ok_values["{{PROJECT_ROOT}}"] == "P:/Program Files/acme",
    )

    # End-to-end: the real substitution over a real wrapper fragment.
    fragment = 'AUTHOR_VENDOR="${{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR:-}"\n'
    with tempfile.TemporaryDirectory(prefix="instantiate-selftest-") as tmp:
        target = Path(tmp) / "tools" / "wrapper.sh"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(fragment, encoding="utf-8")
        mapping = ph.derive_values("my-project", "/r", "/t", "h/o/r")
        new_text, n = ph.apply_reverse(target.read_text(encoding="utf-8"), mapping)
        check(
            f"wrapper-env-var-is-parseable -> {new_text.strip()}",
            n == 1 and "${MY_PROJECT_AUTHOR_VENDOR:-}" in new_text,
        )

        # The generated artifact, not just the value. This is the shape the packaged
        # dispatch wrapper really contains, and quote balance is exactly what an
        # apostrophe destroys -- so it is asserted on the output rather than inferred
        # from the input having been checked.
        ps_line = "    WorkingDirectory = '{{PROJECT_ROOT}}'\n"
        rendered, _ = ph.apply_reverse(
            ps_line, ph.derive_values("acme", "P:/Program Files/acme", "/t", "h/o/r")
        )
        check(
            f"ps-single-quoted-literal-stays-balanced -> {rendered.strip()}",
            rendered.count("'") == 2 and rendered.rstrip().endswith("'"),
        )

    # The installer CLI itself, because that is what an adopter runs. A bad value has to
    # be refused by the *entry point* with a non-zero status, not merely by the helper:
    # `run()` catches ValueError and routes it to parser.error, and nothing proved that
    # path existed.
    for label, root, want_in_stderr in (
        ("apostrophe", "/home/o'brien/proj", "single-quoted PowerShell"),
        ("newline", "/tmp/a\nb", "newline"),
    ):
        proc = subprocess.run(
            [
                sys.executable, str(Path(__file__).resolve()),
                "--project-name", "acme",
                "--project-root", root,
                "--receipts-dir", "/tmp/acme",
                "--repo-url", "github.com/you/acme",
                "--in-place-package",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )
        check(
            f"cli-refuses-{label}-with-exit-2 -> exit {proc.returncode}",
            proc.returncode == 2 and want_in_stderr in proc.stderr,
        )

    here = Path(__file__).resolve()
    sentinel = package_root() / "ADOPTION-GUIDE.md"
    before = sentinel.read_bytes()
    proc = subprocess.run(
        [
            sys.executable,
            str(here),
            "--project-name",
            "acme",
            "--project-root",
            "C:/dev/acme",
            "--receipts-dir",
            "C:/Temp/acme",
            "--repo-url",
            "github.com/you/acme",
        ],
        capture_output=True,
        text=True,
    )
    after = sentinel.read_bytes()
    check(
        "missing-root-is-usage-and-does-not-write",
        proc.returncode == 2
        and "--root is required" in (proc.stderr or "")
        and before == after,
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(here),
            "--root",
            str(package_root()),
            "--in-place-package",
            "--verify",
        ],
        capture_output=True,
        text=True,
    )
    check(
        "root-and-in-place-refused",
        proc.returncode == 2 and "mutually exclusive" in (proc.stderr or ""),
    )

    with tempfile.TemporaryDirectory(prefix="instantiate-owned-") as tmp:
        dest = Path(tmp) / "proj"
        dest.mkdir()
        (dest / "AGENTS.md").write_text("hello {{PROJECT_NAME}}\n", encoding="utf-8")
        (dest / "PROJECT-PROFILE.md").write_text(
            "keep {{PROJECT_NAME}}\n", encoding="utf-8"
        )
        probe = dest / "_probe" / "note.md"
        probe.parent.mkdir()
        probe.write_text("probe {{PROJECT_NAME}}\n", encoding="utf-8")
        (dest / "user-notes.md").write_text(
            "Preserve literal {{PROJECT_NAME}}\n", encoding="utf-8"
        )
        app_tmpl = dest / "app" / "template.md"
        app_tmpl.parent.mkdir()
        app_tmpl.write_text("app {{PROJECT_NAME}}\n", encoding="utf-8")
        for folder in AGENT_DEF_FOLDERS:
            agents = dest / folder
            agents.mkdir(parents=True)
            for role in ("builder", "verifier"):
                (agents / f"{{{{PROJECT_NAME}}}}-{role}.md").write_text(
                    f"name: {{{{PROJECT_NAME}}}}-{role}\n", encoding="utf-8"
                )
        apply_cmd = [
            sys.executable,
            str(here),
            "--root",
            str(dest),
            "--project-name",
            "acme",
            "--project-root",
            "C:/dev/acme",
            "--receipts-dir",
            "C:/Temp/acme",
            "--repo-url",
            "github.com/you/acme",
        ]
        proc = subprocess.run(apply_cmd, capture_output=True, text=True)
        profile = (dest / "PROJECT-PROFILE.md").read_text(encoding="utf-8")
        probe_t = probe.read_text(encoding="utf-8")
        agents_md = (dest / "AGENTS.md").read_text(encoding="utf-8")
        renamed = (dest / ".cursor/agents/acme-builder.md").is_file()
        token_left = (dest / ".cursor/agents/{{PROJECT_NAME}}-builder.md").exists()
        check(
            "owned-profile-tokens-survive",
            proc.returncode == 0 and "{{PROJECT_NAME}}" in profile,
        )
        check("owned-probe-tokens-survive", "{{PROJECT_NAME}}" in probe_t)
        notes = (dest / "user-notes.md").read_text(encoding="utf-8")
        app_t = app_tmpl.read_text(encoding="utf-8")
        check(
            "owned-user-notes-survive",
            proc.returncode == 0 and "{{PROJECT_NAME}}" in notes,
        )
        check(
            "owned-app-template-tokens-survive",
            "{{PROJECT_NAME}}" in app_t,
        )
        check(
            "owned-agents-substituted",
            "acme" in agents_md and "{{PROJECT_NAME}}" not in agents_md,
        )
        check("agent-defs-renamed", renamed and not token_left)
        proc2 = subprocess.run(apply_cmd, capture_output=True, text=True)
        check(
            "second-apply-idempotent",
            proc2.returncode == 0
            and (dest / ".cursor/agents/acme-builder.md").is_file()
            and not (dest / ".cursor/agents/{{PROJECT_NAME}}-builder.md").exists(),
        )
        collide = dest / ".claude/agents/{{PROJECT_NAME}}-builder.md"
        collide.write_text("stale tokenized name\n", encoding="utf-8")
        proc3 = subprocess.run(apply_cmd, capture_output=True, text=True)
        check(
            "rename-collision-refused",
            proc3.returncode == 2 and "collision" in (proc3.stderr or "").lower(),
        )

    failures = sum(1 for _, ok in arms if not ok)
    must_pass = sum(1 for _, ok in arms if ok)
    print(
        f"\nRESULT: {len(arms)} arm(s), {failures} failure(s) "
        f"[{must_pass} passing this run; a validator that always raises cannot pass]"
    )
    return 1 if failures else 0


def main() -> int:
    doc = __doc__ or ""
    parser = argparse.ArgumentParser(
        description=doc.splitlines()[0] if doc else "",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="adopter tree to rewrite (required unless --in-place-package)",
    )
    parser.add_argument(
        "--in-place-package",
        action="store_true",
        help="rewrite this transfer package (mutually exclusive with --root)",
    )
    parser.add_argument("--config", type=Path, help="KEY=VALUE file with the values")
    parser.add_argument("--project-name")
    parser.add_argument("--project-root")
    parser.add_argument("--receipts-dir")
    parser.add_argument("--repo-url")
    parser.add_argument("--project-name-title", help="override derived Title-case")
    parser.add_argument("--project-name-upper", help="override derived UPPER-case")
    parser.add_argument(
        "--credits-start-policy",
        choices=CREDITS_START_POLICIES,
        help="who may start a scheduled credits run: human-only (the default the "
        "template ships) or agent-on-user-chat; written to .agent/credits/config.json",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="only check that no placeholder tokens remain; exit 2 if any do",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="prove the derived values are legal identifiers where they land in code; "
        "--verify cannot see this class (every token IS substituted, just wrongly)",
    )
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    if args.in_place_package and args.root:
        parser.error("--root and --in-place-package are mutually exclusive")
    if not args.in_place_package and args.root is None:
        parser.error(
            "--root is required to rewrite an adopter tree. "
            "Pass --in-place-package only to rewrite this transfer package."
        )
    root = args.root.resolve() if args.root else package_root()
    if args.verify:
        return verify_only(
            root, in_place=args.in_place_package, receipts_dir=args.receipts_dir
        )

    values: dict[str, str] = {}
    if args.config:
        values.update(read_config(args.config))
    # CLI flags override config-file values.
    for flag, key in (
        (args.project_name, "project_name"),
        (args.project_root, "project_root"),
        (args.receipts_dir, "receipts_dir"),
        (args.repo_url, "repo_url"),
        (args.project_name_title, "project_name_title"),
        (args.project_name_upper, "project_name_upper"),
    ):
        if flag is not None:
            values[key] = flag

    required = ("project_name", "project_root", "receipts_dir", "repo_url")
    missing = [k for k in required if not values.get(k)]
    if missing:
        parser.error(
            "missing required value(s): "
            + ", ".join(missing)
            + "  (supply via --config or the matching --flag)"
        )

    try:
        return run(
            values,
            dry_run=args.dry_run,
            root=root,
            in_place=args.in_place_package,
            credits_start_policy=args.credits_start_policy,
        )
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
