# scripts/ — Placeholder tooling

Every file under `core/` in this package has had the originating project's identifiers
replaced with `{{PLACEHOLDER}}` tokens so the framework is project-neutral. These three
files do that substitution — in both directions.

| File | Who runs it | Direction |
|---|---|---|
| `placeholders.py` | neither (imported) | the shared rule table both scripts use |
| `sanitize.py` | the framework author | real strings → `{{PLACEHOLDER}}` |
| **`instantiate.py`** | **you, the adopter** | `{{PLACEHOLDER}}` → your project's values |

They stay in the transfer package. They are the **installer**, not framework content, so
do **not** copy `scripts/` into your adopting project.

---

## The placeholders

| Token | Meaning | Example value |
|---|---|---|
| `{{PROJECT_NAME}}` | project slug, lower-case (also used in `name_core`, `name:event`) | `acme` |
| `{{PROJECT_NAME_TITLE}}` | Title-case (derived from the slug unless overridden) | `Acme` |
| `{{PROJECT_NAME_UPPER}}` | UPPER-case (env-var prefixes like `NAME_HARNESS_PROFILE`) | `ACME` |
| `{{PROJECT_ROOT}}` | absolute path to the project root | `/home/you/acme` · `P:\acme` |
| `{{RECEIPTS_DIR}}` | where shell output is redirected (the P0 receipts dir) | `/tmp/acme` · `C:/Temp/acme` |
| `{{REPO_URL}}` | host/owner/repo, no scheme | `github.com/you/acme` |

---

## Adopter workflow — `instantiate.py`

**1. Write a values file** (`framework.vars`) with a plain text editor. Use forward slashes
on Windows to avoid backslash-escaping surprises:

```
PROJECT_NAME=acme
PROJECT_ROOT=C:/dev/acme
RECEIPTS_DIR=C:/Temp/acme
REPO_URL=github.com/you/acme
# optional — only if simple casing is wrong (e.g. an acronym or multi-word name):
# PROJECT_NAME_TITLE=ACME Corp
# PROJECT_NAME_UPPER=ACMECORP
```

**2. Dry-run first** — see every change, write nothing:

```
python scripts/instantiate.py --config framework.vars --dry-run
```

**3. Apply** — against this package, or against wherever you copied `core/` (`--root`):

```
python scripts/instantiate.py --config framework.vars                 # rewrite this package
python scripts/instantiate.py --root /path/to/your-project --config framework.vars
```

**4. Verify** — assert nothing was missed (exit code 2 if any `{{TOKEN}}` survives):

```
python scripts/instantiate.py --root /path/to/your-project --verify
```

Values may also be passed as flags (`--project-name`, `--project-root`, `--receipts-dir`,
`--repo-url`, `--project-name-title`, `--project-name-upper`); flags override the config file.
`TITLE`/`UPPER` are derived from the slug automatically when omitted.

> **Windows path tip:** prefer forward slashes in the config file. Backslash paths are
> preserved verbatim by the parser (it does no escape processing), but forward slashes are
> valid on Windows and sidestep any editor/shell that might mangle a lone `\a`, `\t`, etc.

---

## Author workflow — `sanitize.py`

You only need this to re-generate or audit the package. It rewrites real identifiers to
placeholders in place:

```
python scripts/sanitize.py --dry-run     # preview
python scripts/sanitize.py --verify       # apply, then assert 0 raw slugs remain
```

Both scripts skip `scripts/` itself (so the rule table is never rewritten), `.git`,
`node_modules`, `__pycache__`, and any non-text file. They are stdlib-only (Python 3.10+)
and idempotent — running twice changes nothing the second time.
