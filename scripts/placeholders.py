"""Shared placeholder <-> value substitution rules for the Agentic Delivery Framework.

This module is the single source of truth used by BOTH:
  - sanitize.py    (authoring tool: real project strings  ->  placeholder tokens)
  - instantiate.py (adopter tool:   placeholder tokens    ->  a new project's values)

Keeping the rules in one place guarantees the two directions can never drift apart.

Design notes
------------
* FORWARD rules are applied *in order*, longest / most-specific first, so that a path
  like ``C:/Temp/zorivest`` becomes ``{{RECEIPTS_DIR}}`` and is NOT later mangled into
  ``C:/Temp/{{PROJECT_NAME}}`` by the bare-word rule.
* No placeholder token contains the source word ``zorivest``, so a forward pass can
  never re-match its own output (the substitution is stable / idempotent).
* The six placeholder tokens are mutually non-overlapping as literal strings, so the
  reverse pass order does not matter; we still sort longest-first for safety.

The original project this framework was extracted from used the slug ``zorivest``.
That is the ONLY project-specific token hard-coded here, by necessity -- it is what we
are sanitizing away. Everything downstream is parameterized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The slug of the project the framework was extracted from. This is the one value we
# are erasing; it appears here only as the thing to search for.
SOURCE_SLUG = "zorivest"

# Canonical ordered list of placeholder tokens (longest first). Adopter-facing docs
# reference these exact spellings.
PLACEHOLDER_TOKENS = [
    "{{PROJECT_NAME_TITLE}}",
    "{{PROJECT_NAME_UPPER}}",
    "{{RECEIPTS_DIR}}",
    "{{PROJECT_ROOT}}",
    "{{PROJECT_NAME}}",
    "{{REPO_URL}}",
]


@dataclass(frozen=True)
class ForwardRule:
    """One real-string -> placeholder substitution.

    is_regex: interpret ``pattern`` as a regular expression (else a literal string).
    """

    is_regex: bool
    pattern: str
    placeholder: str


# ORDER MATTERS. Compound / pathed forms first; bare case-variants last.
FORWARD_RULES: list[ForwardRule] = [
    # 1. Repository URL (captures the owner too: github.com/<owner>/<slug>).
    ForwardRule(False, "github.com/matbanik/zorivest", "{{REPO_URL}}"),
    # 2. Receipts / redirect directory, both slash conventions, case-tolerant on C:/Temp.
    ForwardRule(True, r"[Cc]:[\\/][Tt]emp[\\/]zorivest", "{{RECEIPTS_DIR}}"),
    # 3. Project root on any drive, either slash. Drive letter is part of the root value.
    ForwardRule(True, r"[Pp]:[\\/]zorivest", "{{PROJECT_ROOT}}"),
    # 4-6. Bare word, case-sensitive so the three forms are independent and non-overlapping.
    ForwardRule(False, "ZORIVEST", "{{PROJECT_NAME_UPPER}}"),
    ForwardRule(False, "Zorivest", "{{PROJECT_NAME_TITLE}}"),
    ForwardRule(False, "zorivest", "{{PROJECT_NAME}}"),
]


def apply_forward(text: str) -> tuple[str, int]:
    """Replace real project strings with placeholder tokens.

    Returns (new_text, replacement_count). Safe to run repeatedly (idempotent):
    once a value is a placeholder it no longer matches any rule.
    """
    count = 0
    for rule in FORWARD_RULES:
        if rule.is_regex:
            text, n = re.subn(rule.pattern, rule.placeholder, text)
        else:
            n = text.count(rule.pattern)
            if n:
                text = text.replace(rule.pattern, rule.placeholder)
        count += n
    return text, count


#: Characters that are legal in an environment-variable name once upper-cased.
#: ``{{PROJECT_NAME_UPPER}}`` is substituted into identifiers such as
#: ``$env:{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR``, so it is not free text: a hyphen
#: there produces ``$env:MY-PROJECT_AUTHOR_VENDOR``, which PowerShell parses as a
#: subtraction and the whole wrapper stops parsing. Hyphenated project slugs are the
#: common case, so deriving this by ``.upper()`` alone shipped a dispatch wrapper that
#: could not run.
_ENV_IDENT_ILLEGAL = re.compile(r"[^A-Za-z0-9_]")
_ENV_IDENT_VALID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def env_identifier(name: str) -> str:
    """Upper-case ``name`` into a valid environment-variable identifier.

    Non-identifier characters collapse to ``_`` and a leading digit is prefixed,
    because the result is substituted into code, not into prose.
    """
    ident = _ENV_IDENT_ILLEGAL.sub("_", name.strip().upper())
    if ident and ident[0].isdigit():
        ident = "_" + ident
    return ident


#: Characters that cannot survive substitution into the *code positions* these values
#: land in. This is the same class of defect ``env_identifier`` fixed for
#: ``{{PROJECT_NAME_UPPER}}``, one token over: ``{{PROJECT_ROOT}}`` and
#: ``{{RECEIPTS_DIR}}`` are inserted into single-quoted PowerShell literals (e.g.
#: ``WorkingDirectory = '{{PROJECT_ROOT}}'``), double-quoted shell strings, and JSON
#: string values. An apostrophe closes the PowerShell literal early and the whole
#: dispatch wrapper stops parsing -- while ``instantiate.py`` and ``--verify`` both
#: return 0, because every token *was* substituted. There is no escaping that is
#: correct in all three destinations simultaneously, so the value is refused at the
#: point it is supplied, where the adopter can still choose a different directory.
_PATH_FORBIDDEN = {
    "'": "closes a single-quoted PowerShell literal early",
    '"': "closes a double-quoted shell/JSON string early",
    "`": "is PowerShell's escape character",
    "$": "interpolates in PowerShell and shell double quotes",
    ";": "terminates a statement in both shells",
    "|": "pipes in both shells",
    "&": "backgrounds or chains in both shells",
    "\n": "is a newline, which cannot appear inside a quoted literal at all",
    "\r": "is a carriage return, which cannot appear inside a quoted literal",
    "\t": "is a tab, which silently changes the value nobody can see",
}

#: ``{{PROJECT_NAME}}`` is not prose either. It becomes part of filenames
#: (``<name>-allowed-signers``, ``<name>-exact-index-<guid>``), env-var identifiers,
#: agent-file names and branch names, so it is held to what all of those accept.
_NAME_ALLOWED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _check_path_value(label: str, value: str) -> str:
    r"""Refuse a path value that cannot be substituted into code, and normalise ``\``.

    Backslashes are *converted* rather than refused: ``P:\my-project`` is the natural
    Windows spelling, forward slashes work everywhere PowerShell, bash and JSON read
    these paths, and this package's own examples are already written with them. A
    conversion that cannot change the meaning of the path is worth more than a refusal
    the adopter has to work around by hand.
    """
    for char, why in _PATH_FORBIDDEN.items():
        if char in value:
            shown = repr(char)
            raise ValueError(
                f"{label} contains {shown}, which {why}. This value is substituted "
                f"into executable code -- single-quoted PowerShell literals, "
                f"double-quoted shell strings and JSON strings -- so a character that "
                f"breaks any of those breaks the generated wrapper while instantiation "
                f"and --verify both report success. Choose a path without it."
            )
    return value.replace("\\", "/")


def derive_values(
    project_name: str,
    project_root: str,
    receipts_dir: str,
    repo_url: str,
    project_name_title: str | None = None,
    project_name_upper: str | None = None,
) -> dict[str, str]:
    """Build the full placeholder -> value map, deriving case variants when omitted.

    Raises ValueError if any required base value is blank, or if an explicitly
    supplied ``project_name_upper`` is not a valid environment-variable identifier.
    """
    for label, val in (
        ("project_name", project_name),
        ("project_root", project_root),
        ("receipts_dir", receipts_dir),
        ("repo_url", repo_url),
    ):
        if not val or not val.strip():
            raise ValueError(f"required value '{label}' is empty")

    project_name = project_name.strip()
    if not _NAME_ALLOWED.match(project_name):
        raise ValueError(
            f"project_name '{project_name}' must match {_NAME_ALLOWED.pattern}. It is "
            "not prose: it becomes part of generated filenames "
            "(<name>-allowed-signers, <name>-exact-index-<guid>), environment-variable "
            "identifiers, agent-file names and branch names. A space or a quote there "
            "produces files and commands nothing can address, and instantiation would "
            "still report every token substituted."
        )
    project_root = _check_path_value("project_root", project_root.strip())
    receipts_dir = _check_path_value("receipts_dir", receipts_dir.strip())
    repo_url = _check_path_value("repo_url", repo_url.strip())
    if project_name_title:
        # Title case is the one value that really is prose (headings, sentences), but it
        # still lands inside quoted strings, so the quote characters are refused here too.
        for char in ("'", '"', "`", "\n", "\r"):
            if char in project_name_title:
                raise ValueError(
                    f"project_name_title contains {char!r}, which breaks the quoted "
                    "strings it is substituted into."
                )
    if project_name_upper and project_name_upper.strip():
        upper = project_name_upper.strip()
        if not _ENV_IDENT_VALID.match(upper):
            # Refused rather than silently repaired: an override is a deliberate choice,
            # and quietly rewriting it would leave the adopter reading env-var names in
            # their own notes that do not match the ones the tools now export.
            raise ValueError(
                f"project_name_upper '{upper}' is not a valid environment-variable "
                "identifier ([A-Za-z_][A-Za-z0-9_]*). It is substituted into code such "
                "as $env:<UPPER>_AUTHOR_VENDOR, where a hyphen or space stops the "
                "dispatch wrapper from parsing at all."
            )
    else:
        upper = env_identifier(project_name)
    return {
        "{{PROJECT_NAME}}": project_name,
        "{{PROJECT_NAME_TITLE}}": (
            project_name_title or project_name.capitalize()
        ).strip(),
        "{{PROJECT_NAME_UPPER}}": upper,
        "{{PROJECT_ROOT}}": project_root,
        "{{RECEIPTS_DIR}}": receipts_dir,
        "{{REPO_URL}}": repo_url,
    }


def apply_reverse(text: str, values: dict[str, str]) -> tuple[str, int]:
    """Replace placeholder tokens with a new project's concrete values.

    Longest token first so no token is a prefix-collision hazard. Returns
    (new_text, replacement_count).
    """
    count = 0
    for token in PLACEHOLDER_TOKENS:  # already longest-first
        val = values.get(token)
        if val is None:
            continue
        n = text.count(token)
        if n:
            text = text.replace(token, val)
            count += n
    return text, count


def remaining_source_hits(text: str) -> int:
    """Case-insensitive count of any surviving raw source-slug occurrences.

    Used by sanitize.py --verify to prove zero leakage.
    """
    return len(re.findall(re.escape(SOURCE_SLUG), text, flags=re.IGNORECASE))
