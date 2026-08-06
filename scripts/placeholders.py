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


def derive_values(
    project_name: str,
    project_root: str,
    receipts_dir: str,
    repo_url: str,
    project_name_title: str | None = None,
    project_name_upper: str | None = None,
) -> dict[str, str]:
    """Build the full placeholder -> value map, deriving case variants when omitted.

    Raises ValueError if any required base value is blank.
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
    return {
        "{{PROJECT_NAME}}": project_name,
        "{{PROJECT_NAME_TITLE}}": (
            project_name_title or project_name.capitalize()
        ).strip(),
        "{{PROJECT_NAME_UPPER}}": (project_name_upper or project_name.upper()).strip(),
        "{{PROJECT_ROOT}}": project_root.strip(),
        "{{RECEIPTS_DIR}}": receipts_dir.strip(),
        "{{REPO_URL}}": repo_url.strip(),
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
