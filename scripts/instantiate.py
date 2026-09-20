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
"""

from __future__ import annotations

import argparse
import re
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
)
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
AGENT_DEF_ROLES = ("builder", "verifier")
AGENT_DEF_FOLDERS = (".cursor/agents", ".claude/agents")
BOM = b"\xef\xbb\xbf"

CONFIG_KEYS = {
    "PROJECT_NAME": "project_name",
    "PROJECT_ROOT": "project_root",
    "RECEIPTS_DIR": "receipts_dir",
    "REPO_URL": "repo_url",
    "PROJECT_NAME_TITLE": "project_name_title",
    "PROJECT_NAME_UPPER": "project_name_upper",
}


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
        for role in AGENT_DEF_ROLES:
            src = root / folder / f"{{{{PROJECT_NAME}}}}-{role}.md"
            dst = root / folder / f"{slug}-{role}.md"
            if src.is_file():
                pairs.append((src, dst))
            elif dst.is_file():
                continue
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


def verify_only(root: Path, *, in_place: bool = False) -> int:
    """Report any files that still contain placeholder tokens."""
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
    if offenders:
        print(f"VERIFY FAILED: {len(offenders)} file(s) still contain placeholders:")
        for rel, cnt in offenders:
            print(f"  {cnt:>4}  {rel}")
        return 2
    print("verify: OK (0 placeholder tokens remain)")
    return 0


def run(values: dict[str, str], dry_run: bool, root: Path, *, in_place: bool = False) -> int:
    mapping = ph.derive_values(**values)
    slug = mapping["{{PROJECT_NAME}}"]
    pairs = planned_agent_renames(root, slug)
    refuse_rename_collisions(pairs)

    print("Placeholder -> value:")
    for token in ph.PLACEHOLDER_TOKENS:
        print(f"  {token:<24} {mapping[token]}")
    print()

    total_files = changed_files = total_repl = 0
    planned: list[tuple[Path, str, bool, int]] = []
    for path in iter_owned_text_files(root, in_place=in_place):
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

    if not dry_run:
        for path, new_text, bom, _n in planned:
            write_text_preserve(path, new_text, bom)
        for src, dst in pairs:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.replace(dst)

    mode = "DRY-RUN (no files written)" if dry_run else "APPLIED"
    print("\n" + "=" * 60)
    print(f"  mode:          {mode}")
    print(f"  files scanned: {total_files}")
    print(f"  files changed: {changed_files}")
    print(f"  replacements:  {total_repl}")
    print(f"  renames:       {len(pairs)}")
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
            for role in AGENT_DEF_ROLES:
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
        return verify_only(root, in_place=args.in_place_package)

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
        return run(values, dry_run=args.dry_run, root=root, in_place=args.in_place_package)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
