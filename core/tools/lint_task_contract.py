#!/usr/bin/env python3
"""lint_task_contract.py -- structural gate for a task.md Task Table.

The Task Table is the execution contract: each row names a command that decides
whether the row is done. Every check below exists because a row can look complete
while its command is incapable of failing -- a truncated cell, a swallowed exit
code, a receipt written where nobody will read it. Those rows report success
forever, and no amount of reading the table reveals it.

Usage:

  python tools/lint_task_contract.py --task docs/execution/plans/{slug}/task.md
  python tools/lint_task_contract.py --task templates/TASK-TEMPLATE.md --template-mode
  python tools/lint_task_contract.py --selftest

Exit codes, and the first line of output always names which:

  0  ``OK:``           every row satisfies the contract
  1  ``REFUSE:``       at least one row does not
  2  ``USAGE:``        the invocation is wrong
  3  ``FAIL-CLOSED:``  the check could not run

3 is distinct from 1 deliberately and everywhere. A missing file, an unparseable
table and a table with no rows all produce "no violations", and "no violations"
reads as a pass. The caller has to be able to tell "the gate said no" from "the
gate never spoke" (V5).

``--selftest`` proves each refusal can fire. A gate that cannot fail is not a gate,
and the only evidence that this one can is an input that makes it.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

CONTEXT_STRATEGIES = ("shared", "compact_continue", "isolated")
DEFAULT_BUILDER_CLASSES = ("builder", "coordinator", "verifier")
STATUSES = ("[ ]", "[/]", "[x]", "[B]")
NONE_MARKERS = ("—", "-", "–", "n/a", "none", "")

#: Header label -> canonical column key. Both the 10-column form and the legacy
#: 9-column form (no ``builder_model``) are valid, so columns are located by header
#: label rather than by position: a positional reader silently checks the wrong
#: cell on the other form, and reports OK for it.
HEADERS = {
    "#": "id",
    "task": "task",
    "owner": "owner",
    "deliverable": "deliverable",
    "validation": "validation",
    "depends on": "depends_on",
    "depends_on": "depends_on",
    "context strategy": "context_strategy",
    "context_strategy": "context_strategy",
    "durable outputs": "durable_outputs",
    "durable_outputs": "durable_outputs",
    "builder_model": "builder_model",
    "builder model": "builder_model",
    "status": "status",
}
REQUIRED_COLUMNS = (
    "id", "task", "owner", "deliverable", "validation",
    "depends_on", "context_strategy", "durable_outputs", "status",
)

TABLE_LINE = re.compile(r"^\|.*\|\s*$")
SEPARATOR = re.compile(r"^\|[\s:|-]+\|\s*$")
BACKTICKED = re.compile(r"`([^`]+)`")

#: The receipts token, assembled at runtime so it never appears literally in this file.
#:
#: instantiate.py replaces the literal token in every shipped file, and this module is
#: shipped -- so on any installed tree it rewrote this module's own *test fixtures* into
#: absolute paths and 23 of 44 selftest arms began testing a different string than the one
#: they were written for. The checks below still match the literal token; only the fixtures
#: and the refusal messages dodge substitution, because those are the places where the
#: literal is data rather than a default to be filled in.
RD_TOKEN = "{{" + "RECEIPTS_DIR" + "}}"
#: The receipts token and its siblings are *instantiation* tokens: instantiate.py
#: substitutes them, so they are not the plan author's to resolve and must not be
#: reported as unresolved. Only single-brace ``{plan-file}``-style tokens are
#: authoring placeholders. Conflating the two makes every correct row in the shipped
#: template look broken -- and the pressure then is to loosen the placeholder check
#: itself, which is the one that catches rows nobody can run.
INSTANTIATION_TOKEN = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")

#: A `{...}` group in *executable* position: PowerShell and shell both use braces, and a
#: blanket `\{[^}]*\}` cannot tell `{plan-file}` from `& { Write-Output ok }`. It rejected
#: real scriptblocks and the supported `${RECEIPTS_DIR}` spelling as "unresolved
#: placeholders" -- and the pressure from that is to loosen the placeholder check, which is
#: the one that catches rows nobody can run.
#:
#: The discriminator is deliberately syntactic rather than semantic, because a descriptive
#: placeholder can contain almost any word: a brace group is *code* if it sits directly
#: after a sigil that introduces one (`$` `@` `&` `%`), if its body opens with a variable,
#: or if it contains a statement separator. Everything else is prose for a human to fill in.
#: Widening this set is safe; narrowing it re-opens F12.
_BRACE_GROUP = re.compile(r"[$@&%]\s*\{[^{}]*\}|\{\s*\$[^{}]*\}|\{[^{}]*;[^{}]*\}")
#: An authoring placeholder: `{plan-file}`, `{exact command}`, `{approved | changes_required}`.
#: No statement separators, no leading sigil -- those are handled above.
PLACEHOLDER = re.compile(r"\{[^{};]{1,80}\}")

_RECEIPT_VARIANTS = (
    r"\{\{RECEIPTS_DIR\}\}",
    r"\$env:RECEIPTS_DIR",
    r"\$RECEIPTS_DIR",
    r"\$\{RECEIPTS_DIR\}",
)
RECEIPT_REF = re.compile("|".join(_RECEIPT_VARIANTS))

#: A redirect operator, for the "is output actually *routed* there" test below.
_REDIRECT_OP = (
    r"(?:\*>>?|\d?>>?|\|\s*(?:tee|Tee-Object|Out-File)\b[^|;]*?|-(?:FilePath|OutFile)\s+)"
)
#: The status capture, and the statements that consume a receipt. Order between these two
#: is the whole point -- see ``check_status_propagation``.
CAPTURE_STMT = re.compile(r"\$?code\s*=\s*\$(?:LASTEXITCODE\b|\?)")
READER_STMT = re.compile(r"\b(?:Get-Content|gc|cat|type)\b")


def receipt_ref_re() -> re.Pattern[str]:
    """Spellings that name the receipts root, token *or* instantiated absolute path."""
    variants = list(_RECEIPT_VARIANTS) + [re.escape(v) for v in receipts_dir_variants()]
    return re.compile("|".join(variants))


def receipt_redirect_re() -> re.Pattern[str]:
    """A receipts reference that output is actually redirected *into*.

    "The cell mentions RECEIPTS_DIR somewhere" was the entire durable-evidence test, so a
    command that only *read* a receipt, or named the directory in passing, satisfied the
    rule without ever writing one. A promise of evidence is not evidence.
    """
    variants = list(_RECEIPT_VARIANTS) + [re.escape(v) for v in receipts_dir_variants()]
    return re.compile(
        _REDIRECT_OP + r"\s*[\"']?(?:" + "|".join(variants) + r")", re.IGNORECASE
    )


def split_statements(cell: str) -> list[str]:
    """Top-level statements of a Validation cell, split on ``;`` and newlines.

    Quotes and brackets are tracked because a ``;`` inside a string or a scriptblock is not
    a statement boundary, and mistaking one for a boundary shifts every later statement's
    index -- which is exactly what the ordering check is built on.
    """
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    quote = ""
    for ch in cell:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            continue
        if ch in "{([":
            depth += 1
            buf.append(ch)
            continue
        if ch in "})]":
            depth = max(0, depth - 1)
            buf.append(ch)
            continue
        if depth == 0 and ch in ";\n":
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]
EXIT_CAPTURED = re.compile(r"exit\s+(\$code\b|\$LASTEXITCODE\b|\"\$code\"|\$\{code\}|\$\?)")
EXIT_LITERAL = re.compile(r"\bexit\s+0\b")
# A harness read, not a shell command. It produces no exit code and no receipt, so
# the redirect and exit-code checks below do not apply to it -- and saying so
# explicitly is better than the alternative, which is a blanket exemption for any
# command the linter fails to recognise.
VIEW_FILE = re.compile(r"^\s*view_file\s*:")


def authoring_placeholders(text: str) -> list[str]:
    """The ``{single-brace}`` tokens a plan author still has to fill in.

    Instantiation tokens are removed first (they are not the author's to resolve), then
    brace groups in executable position -- see ``_BRACE_GROUP``. What is left is prose.
    """
    stripped = INSTANTIATION_TOKEN.sub("", text)
    stripped = _BRACE_GROUP.sub("", stripped)
    return PLACEHOLDER.findall(stripped)


def receipts_dir_variants() -> list[str]:
    """Literal spellings of the configured receipts root, for an *instantiated* tree.

    After instantiation the template's receipts token is an absolute path, so a
    linter that only knows the token reported every correct row in the installed template
    as writing no receipt. The configured value is read from the environment because that
    is where every other tool in this package reads it, and both separators are accepted
    because the same tree is linted from PowerShell and from bash.
    """
    configured = os.environ.get("RECEIPTS_DIR", "").strip()
    if not configured:
        return []
    forms = {configured, configured.replace("\\", "/"), configured.replace("/", "\\")}
    return [f for f in forms if f]


class Refuse(Exception):
    """The check ran and the answer is no."""


class FailClosed(Exception):
    """The check could not run. Never report this as a pass."""


class Usage(Exception):
    """The invocation is wrong."""


class Row:
    __slots__ = ("line_no", "cells", "raw", "by_key")

    def __init__(self, line_no: int, cells: list[str], raw: str, by_key: dict[str, str]):
        self.line_no = line_no
        self.cells = cells
        self.raw = raw
        self.by_key = by_key

    def get(self, key: str) -> str:
        return self.by_key.get(key, "")

    @property
    def id(self) -> str:
        return self.get("id").strip("`* ")


def split_row(line: str) -> list[str]:
    """Markdown cells of one table row.

    Splits on unescaped ``|`` only. Splitting on every pipe would silently merge or
    shift cells in any row that legitimately escaped one, and a shifted row is
    checked against the wrong column.
    """
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") else body
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def find_table(text: str, path: str) -> tuple[dict[str, int], list[Row]]:
    lines = text.splitlines()
    header_idx = None
    mapping: dict[str, int] = {}

    for i, line in enumerate(lines):
        if not TABLE_LINE.match(line) or SEPARATOR.match(line):
            continue
        cells = split_row(line)
        keys = [HEADERS.get(c.strip().strip("*` ").lower()) for c in cells]
        if keys and keys[0] == "id" and "validation" in keys and "status" in keys:
            header_idx = i
            mapping = {k: n for n, k in enumerate(keys) if k}
            break

    if header_idx is None:
        raise FailClosed(
            f"no Task Table header row found in {path}. Expected a markdown table "
            f"beginning with '| # | Task | Owner | ... | Validation | ... | Status |'. "
            f"Without a header the columns cannot be located, and a linter that "
            f"guessed at positions would check the wrong cells and pass."
        )
    missing = [c for c in REQUIRED_COLUMNS if c not in mapping]
    if missing:
        raise Refuse(
            f"Task Table in {path} is missing required column(s): "
            f"{', '.join(missing)}. Legacy 9-column tables (no builder_model) are "
            f"valid; the other nine are not optional."
        )

    rows: list[Row] = []
    # Collected to the next heading, NOT to the first non-table line. TASK-TEMPLATE.md
    # puts the H1/H2 closeout rows in a *second, headerless* table further down the
    # same section, separated from the first by several paragraphs of prose. Stopping
    # at the first blank-then-prose boundary found 2 illustrative rows, skipped all 14
    # closeout rows, and reported OK -- the exact vacuous pass this tool exists to
    # prevent. Any heading ends the section, which keeps the 2-column Status Legend
    # table under `### Status Legend` out of the row set.
    for i in range(header_idx + 1, len(lines)):
        line = lines[i]
        if re.match(r"^#{1,6}\s", line):
            break
        if not TABLE_LINE.match(line):
            continue
        if SEPARATOR.match(line):
            continue
        cells = split_row(line)
        if all(c in ("", "...") for c in cells):
            continue
        # Phase dividers: empty id, a bolded label, and nothing else. They carry no
        # command, so linting them as rows would demand a receipt from a heading.
        if not cells[0].strip() and any("**" in c for c in cells):
            continue
        if all(c.strip() in ("", "...") for c in cells[1:]):
            continue
        by_key = {k: (cells[n] if n < len(cells) else "") for k, n in mapping.items()}
        rows.append(Row(i + 1, cells, line, by_key))

    if not rows:
        raise FailClosed(
            f"Task Table in {path} has a header but no data rows. Zero rows produce "
            f"zero violations, which is not a pass -- it is a check with nothing to "
            f"check (V5)."
        )
    return mapping, rows


# --------------------------------------------------------------------- row checks


def check_cell_count(row: Row, expected: int, path: str) -> None:
    if len(row.cells) == expected:
        return
    hint = ""
    if len(row.cells) > expected:
        hint = (
            " An unescaped '|' inside the Validation command is the usual cause: it "
            "ends the cell early and the rest of the command becomes new columns, so "
            "the command a reader copies is a truncated one that still looks whole."
        )
    raise Refuse(
        f"{path}:{row.line_no} row {row.id or '?'} has {len(row.cells)} cell(s), "
        f"expected {expected}.{hint}"
    )


def check_escaped_pipe(row: Row, path: str) -> None:
    """No ``\\|`` inside the Validation cell.

    Escaping the pipe keeps the markdown table intact, which is exactly the problem:
    the row renders correctly and the command inside it is not the command. Anyone
    copying it runs ``foo \\| bar``, which is not valid in any shell here. The fix is
    not better escaping -- it is to redirect to a receipt instead of piping.
    """
    if r"\|" in row.get("validation"):
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} escapes a pipe (\\|) inside the "
            f"Validation cell. The table renders, but the command as written is not "
            f"runnable -- a pasted '\\|' is a syntax error, not a pipe. Redirect to a "
            f"{RD_TOKEN} receipt and read it back instead of piping."
        )


def check_backticked(row: Row, path: str, template_mode: bool) -> list[str]:
    cell = row.get("validation")
    if not cell.strip() or cell.strip() in NONE_MARKERS:
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} has an empty Validation cell. A row "
            f"with no validation command is a row that cannot be proven done, and it "
            f"will be checked off on someone's judgement."
        )
    if cell.count("`") % 2:
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} has an odd number of backticks in its "
            f"Validation cell, so the inline-code span is unterminated. Everything "
            f"after the stray backtick renders as prose and reads as part of the "
            f"command."
        )
    commands = BACKTICKED.findall(cell)
    if not commands:
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} Validation is not in backticks: "
            f"{cell[:80]!r}. An unbackticked command is prose; markdown will reflow "
            f"it, and the exact-command requirement stops being checkable."
        )
    if not template_mode:
        unresolved = [p for c in commands for p in authoring_placeholders(c)]
        if unresolved:
            raise Refuse(
                f"{path}:{row.line_no} row {row.id} Validation still contains "
                f"unresolved placeholder(s): {', '.join(unresolved[:3])}. A "
                f"placeholder command cannot be run, so the row can only be closed "
                f"by assertion. Pass --template-mode only when linting the template "
                f"itself."
            )
    for cmd in commands:
        for open_c, close_c, name in (("{", "}", "brace"), ("(", ")", "paren")):
            if cmd.count(open_c) != cmd.count(close_c):
                raise Refuse(
                    f"{path}:{row.line_no} row {row.id} Validation has unbalanced "
                    f"{name}s: {cmd[:80]!r}. An unbalanced block means the command "
                    f"was truncated when the cell was edited."
                )
    return commands


def check_exit_and_receipt(
    row: Row, commands: list[str], path: str, template_mode: bool
) -> str | None:
    """Returns the name of the exemption used, or None if the row was fully checked.

    Exemptions are returned rather than swallowed so ``lint`` can report how many
    rows were not fully checked. A silent exemption is how a whole class of rows
    stops being linted without anyone deciding that: the gate stays green and the
    count of rows it actually inspected quietly falls.
    """
    if any(VIEW_FILE.match(c) for c in commands):
        return "view_file"  # a harness read; see VIEW_FILE
    if template_mode and all(
        PLACEHOLDER.fullmatch(INSTANTIATION_TOKEN.sub("", c).strip()) for c in commands
    ):
        # `{exact command}` stands in for the whole command, so there is no exit form
        # or redirect to check. Only reachable in template mode -- a real task.md
        # refuses on the placeholder itself before getting here.
        return "placeholder-command"
    cell = " ".join(commands)

    if EXIT_LITERAL.search(cell):
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} Validation ends in 'exit 0'. That "
            f"command reports success whatever it did, so the row can never fail and "
            f"the gate is decoration. Capture the real code "
            f"($code=$LASTEXITCODE) and 'exit $code'."
        )
    if not EXIT_CAPTURED.search(cell):
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} Validation never re-exits the "
            f"command's status. With a redirect in the pipeline the last statement's "
            f"code is what the caller sees, so a failing check exits 0 and the row "
            f"passes. Add '; $code=$LASTEXITCODE; ...; exit $code' (POSIX: "
            f"'code=$?; ...; exit $code')."
        )
    if re.search(r"exit\s+(\$code\b|\"\$code\"|\$\{code\})", cell) and not re.search(
        r"\$?code\s*=\s*\$(LASTEXITCODE|\?)", cell
    ):
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} Validation exits '$code' but never "
            f"assigns it. An unset variable expands to empty, PowerShell reads that "
            f"as 0, and the row passes on a failed check -- the most convincing form "
            f"of this bug, because the exit line looks correct."
        )
    ref_re = receipt_ref_re()
    if not ref_re.search(cell):
        if not receipts_dir_variants():
            # The token is gone and RECEIPTS_DIR is unset, so this cell may be routing to a
            # substituted absolute path this process cannot recognise. "No receipt" and "I
            # cannot see the receipt root" are different facts, and the second one is 3.
            raise FailClosed(
                f"{path}:{row.line_no} row {row.id} names no receipts reference, and "
                f"RECEIPTS_DIR is unset so an instantiated absolute receipt path cannot be "
                f"recognised either. On an installed tree the template's {RD_TOKEN} has "
                f"already been substituted, so this check needs the configured value: "
                f"export RECEIPTS_DIR (the same value instantiate.py was given) and "
                f"re-run. Refusing on this without it would be a guess."
            )
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} Validation writes no receipt under "
            f"{RD_TOKEN}. Output that is not redirected to a durable path a "
            f"reviewer can re-open is evidence only for the agent that saw it scroll "
            f"past, and '[x]' then rests on a claim rather than an artifact."
        )
    if not receipt_redirect_re().search(cell):
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} names the receipts root but never "
            f"redirects into it. Mentioning the path -- or only reading a receipt back -- "
            f"leaves the command's own output on a terminal nobody can re-open, which is "
            f"the state this rule exists to prevent. Add '*> {RD_TOKEN}/<name>.txt' "
            f"(POSIX: '> {RD_TOKEN}/<name>.txt 2>&1')."
        )
    if template_mode:
        return
    for match in ref_re.finditer(cell):
        tail = cell[match.end():match.end() + 2]
        if not tail.startswith(("/", "\\")):
            raise Refuse(
                f"{path}:{row.line_no} row {row.id} references the receipts dir but "
                f"not a path under it ({cell[match.start():match.start() + 40]!r}). A "
                f"bare reference writes to the directory itself or to a sibling of it."
            )
    check_status_propagation(row, cell, path)


def check_status_propagation(row: Row, cell: str, path: str) -> None:
    """The capture must be bound to the command whose status it claims to carry.

    Every check above searches the *combined text* of the cell, which is what let this
    through with a clean bill of health::

        false > "$RECEIPTS_DIR/check.txt" 2>&1; cat "$RECEIPTS_DIR/check.txt"; code=$?; exit $code

    There is a redirect, a capture, a read and an ``exit $code``, so an anywhere-search
    finds everything it is looking for. But ``code=$?`` runs after ``cat``, so it captures
    the *reader's* status: the row exits 0 while ``false`` failed. Presence of the right
    tokens is not the same as their being in the right order, and only the order makes the
    status propagate.
    """
    statements = split_statements(cell)
    redirect_re = receipt_redirect_re()
    i_redirect = next(
        (i for i, s in enumerate(statements) if redirect_re.search(s)), None
    )
    i_capture = next(
        (i for i, s in enumerate(statements) if CAPTURE_STMT.search(s)), None
    )
    if i_redirect is None or i_capture is None:
        return  # the earlier checks own those cases and have already spoken
    if i_capture in (i_redirect, i_redirect + 1):
        return
    between = [s for s in statements[i_redirect + 1:i_capture] if READER_STMT.search(s)]
    culprit = between[0] if between else statements[i_capture - 1]
    raise Refuse(
        f"{path}:{row.line_no} row {row.id} captures the exit status too late: the "
        f"capture in {statements[i_capture]!r} runs after {culprit!r}, so it records "
        f"*that* statement's status, not the checked command's. A reader like "
        f"'Get-Content' almost always succeeds, so the row exits 0 whatever the command "
        f"did. Capture immediately after the redirected command: "
        f"'<command> *> {RD_TOKEN}/x.txt; $code=$LASTEXITCODE; Get-Content "
        f"{RD_TOKEN}/x.txt; exit $code'."
    )


def check_enums(row: Row, path: str, builder_classes: tuple[str, ...], has_builder: bool) -> None:
    strategy = row.get("context_strategy").strip("`* ")
    if strategy not in CONTEXT_STRATEGIES:
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} has context_strategy {strategy!r}; "
            f"the enum is exactly {'|'.join(CONTEXT_STRATEGIES)}. 'delegate_to' is a "
            f"Task-cell annotation, not a strategy value."
        )
    durable = row.get("durable_outputs").strip("`* ")
    if strategy != "shared" and durable.lower() in NONE_MARKERS:
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} is {strategy!r} but names no durable "
            f"output. A row that compacts or isolates loses its context by design, so "
            f"without a durable path the work it did is unrecoverable afterwards."
        )

    status = row.get("status").strip("`* ")
    if status not in STATUSES:
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} has Status {status!r}; the legend is "
            f"{', '.join(STATUSES)}."
        )
    if status == "[B]":
        # [B] is the one status that closes a row without the work being done, so it
        # is the only one worth a machine check. Its own row id is stripped first --
        # 'H1-6' matches every ticket-shaped pattern, so leaving it in would make this
        # check structurally incapable of failing.
        haystack = row.raw.replace(f"| {row.id} |", "| |")
        if not re.search(r"\[[^\]]+\]\([^)]+\)|#\d+|\b[A-Z]{2,}-\d+\b", haystack):
            raise Refuse(
                f"{path}:{row.line_no} row {row.id} is [B] with no linked follow-up. "
                f"[B] is evidence-gated: a blocked row without a follow-up link is "
                f"indistinguishable from an abandoned one, and it tallies as closed."
            )

    if not has_builder:
        return
    model = row.get("builder_model").strip("`* ")
    if model.lower() in NONE_MARKERS:
        return
    if model not in builder_classes:
        raise Refuse(
            f"{path}:{row.line_no} row {row.id} has builder_model {model!r}, which is "
            f"not a capability class ({'|'.join(builder_classes)}). A model slug or "
            f"'auto' here pins the row to a snapshot that the live registry will move "
            f"out from under it -- name the class and let "
            f"Resolve-AgentModel -Class <class> -Harness <harness> -Project <root> "
            f"answer. Use --allowed-builder-classes if this project defines others."
        )


def check_dependencies(rows: list[Row], path: str, template_mode: bool) -> None:
    ids = {r.id for r in rows}
    graph: dict[str, list[str]] = {}
    for row in rows:
        cell = row.get("depends_on").strip("`* ")
        deps: list[str] = []
        if cell.lower() not in NONE_MARKERS:
            for part in re.split(r"[,;+]| and ", cell):
                dep = part.strip().strip("`* ")
                if not dep or dep.lower() in NONE_MARKERS:
                    continue
                if PLACEHOLDER.fullmatch(dep):
                    if template_mode:
                        continue
                    raise Refuse(
                        f"{path}:{row.line_no} row {row.id} depends on unresolved "
                        f"placeholder {dep!r}. An unresolved dependency orders nothing."
                    )
                if dep not in ids:
                    raise Refuse(
                        f"{path}:{row.line_no} row {row.id} depends on {dep!r}, which "
                        f"is not a row in this table. A dependency on a row that does "
                        f"not exist imposes no ordering while reading as though it does."
                    )
                deps.append(dep)
        graph[row.id] = deps

    # Explicit stack rather than recursion: a cycle is exactly the input that would
    # make a naive recursive walk blow the stack instead of reporting the cycle.
    WHITE, GREY, BLACK = 0, 1, 2
    color = {k: WHITE for k in graph}
    for start in graph:
        if color[start] != WHITE:
            continue
        stack = [(start, iter(graph[start]))]
        color[start] = GREY
        path_stack = [start]
        while stack:
            node, it = stack[-1]
            advanced = False
            for dep in it:
                if color.get(dep) == GREY:
                    cycle = path_stack[path_stack.index(dep):] + [dep]
                    raise Refuse(
                        f"{path} Task Table dependencies contain a cycle: "
                        f"{' -> '.join(cycle)}. A cycle has no valid execution order, "
                        f"so every row in it waits on itself and the pass deadlocks."
                    )
                if color.get(dep, BLACK) == WHITE:
                    color[dep] = GREY
                    stack.append((dep, iter(graph[dep])))
                    path_stack.append(dep)
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                path_stack.pop()


def check_unique_ids(rows: list[Row], path: str) -> None:
    seen: dict[str, int] = {}
    for row in rows:
        if not row.id:
            raise Refuse(
                f"{path}:{row.line_no} has a data row with an empty '#' cell. An "
                f"unnamed row cannot be depended on and cannot be cited as done."
            )
        if row.id in seen:
            raise Refuse(
                f"{path}:{row.line_no} row id {row.id!r} duplicates line "
                f"{seen[row.id]}. Two rows with one id make 'depends on {row.id}' "
                f"ambiguous, and checking one off reads as checking both."
            )
        seen[row.id] = row.line_no


# ------------------------------------------------------------------------ driver


def lint(path: str, template_mode: bool, builder_classes: tuple[str, ...]) -> list[str]:
    p = Path(path)
    if not p.exists():
        raise FailClosed(
            f"task file not found at {path}. This is not a pass: the linter had "
            f"nothing to read."
        )
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FailClosed(f"task file at {path} could not be read as UTF-8: {exc}")
    if not text.strip():
        raise Refuse(f"task file at {path} is empty.")

    mapping, rows = find_table(text, path)
    expected = max(mapping.values()) + 1
    has_builder = "builder_model" in mapping

    check_unique_ids(rows, path)
    exempt: dict[str, list[str]] = {}
    for row in rows:
        check_cell_count(row, expected, path)
        check_escaped_pipe(row, path)
        commands = check_backticked(row, path, template_mode)
        reason = check_exit_and_receipt(row, commands, path, template_mode)
        if reason:
            exempt.setdefault(reason, []).append(row.id)
        check_enums(row, path, builder_classes, has_builder)
    check_dependencies(rows, path, template_mode)

    fully_checked = len(rows) - sum(len(v) for v in exempt.values())
    if not fully_checked:
        raise Refuse(
            f"{path} Task Table has {len(rows)} row(s) and not one of them reached the "
            f"command checks — every row was exempt "
            f"({', '.join(f'{k}: {len(v)}' for k, v in sorted(exempt.items()))}). "
            f"Zero rows checked is not a pass; it is a linter with nothing to lint, "
            f"and it is indistinguishable from a clean table unless it refuses (V5)."
        )
    notes = [
        f"{len(rows)} row(s)",
        f"{expected}-column table ({'with' if has_builder else 'legacy, no'} builder_model)",
        f"{fully_checked} row(s) fully checked: backticked, exit-code re-raised, "
        f"receipt under RECEIPTS_DIR",
        "dependencies resolve and are acyclic",
    ]
    # Named in the OK line, not hidden. A reader has to be able to see which rows the
    # command checks did not reach, or "OK" overstates what was verified.
    for reason, ids in sorted(exempt.items()):
        notes.append(f"{len(ids)} row(s) exempt ({reason}): {', '.join(ids)}")
    return notes


# ---------------------------------------------------------------------- selftest

_HEADER = (
    "| # | Task | Owner | Deliverable | Validation | Depends on | "
    "Context strategy | Durable outputs | builder_model | Status |\n"
    "|---|---|---|---|---|---|---|---|---|---|\n"
)
_CMD = (
    "`rtk proxy uv run python tools/x.py *> " + RD_TOKEN + "/x.txt; "
    "$code=$LASTEXITCODE; Get-Content " + RD_TOKEN + "/x.txt; exit $code`"
)


def _row(
    rid="1", task="do the thing", owner="coder", deliverable="a file", validation=None,
    depends="—", strategy="shared", durable="receipt", model="`builder`", status="`[ ]`",
) -> str:
    validation = _CMD if validation is None else validation
    return (
        f"| {rid} | {task} | {owner} | {deliverable} | {validation} | {depends} | "
        f"{strategy} | {durable} | {model} | {status} |\n"
    )


def _doc(*rows: str, header: str = _HEADER) -> str:
    return "## Task Table\n\n" + header + "".join(rows) + "\n### Status Legend\n"


#: A receipts root no fixture names, so pinning it cannot accidentally satisfy a check that
#: was meant to refuse. Absolute and obviously synthetic: the arms that care about the
#: *configured* root spell it out themselves.
_SELFTEST_RECEIPTS_DIR = "/selftest-receipts-root-no-fixture-names"


def selftest() -> int:
    """Prove every refusal can fire, and that clean tables still pass.

    The must-OK count is printed alongside the total. A linter that refused every
    input would satisfy every negative arm below, and the negative arms are the easy
    ones to write -- so a run with zero must-OK arms is broken however green it
    looks (V5).
    """
    results: list[tuple[str, str, str]] = []
    tmp = Path(tempfile.mkdtemp(prefix="task-lint-selftest-"))
    counter = [0]
    parser = build_parser()

    def w(text: str) -> str:
        counter[0] += 1
        p = tmp / f"task{counter[0]}.md"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def arm(
        label: str,
        want: str,
        argv: list[str],
        must_say: str | None = None,
        receipts_dir: str | None = _SELFTEST_RECEIPTS_DIR,
    ) -> None:
        """One arm. ``must_say`` names the clause expected to reject the input.

        A non-zero exit says something refused, not that the clause under test
        refused (V3). Several fixtures below would trip two clauses if the ordering
        were wrong, and without a substring assertion an arm firing the wrong one is
        indistinguishable from a pass.

        ``RECEIPTS_DIR`` is pinned for every arm rather than inherited, because the
        receipts checks now consult it: a suite whose verdicts depend on the operator's
        shell passes on the author's machine and fails on an adopter's, which is the
        failure mode this whole round of fixes is about. Pass ``receipts_dir=None`` to
        assert the deliberately-unconfigured case.
        """
        buf = io.StringIO()
        saved = os.environ.get("RECEIPTS_DIR")
        if receipts_dir is None:
            os.environ.pop("RECEIPTS_DIR", None)
        else:
            os.environ["RECEIPTS_DIR"] = receipts_dir
        try:
            with redirect_stdout(buf):
                code = main(argv, parser=parser)
        except SystemExit as exc:
            code = int(exc.code or 0)
        finally:
            if saved is None:
                os.environ.pop("RECEIPTS_DIR", None)
            else:
                os.environ["RECEIPTS_DIR"] = saved
        out = buf.getvalue()
        got = {0: "0/OK", 1: "1/REFUSE", 2: "2/USAGE", 3: "3/FAIL-CLOSED"}.get(code, str(code))
        if got == want and must_say and must_say not in out:
            got = f"{want} but not for the expected reason: {out[:120]!r}"
        results.append((label, want, got))

    # -- must-OK arms -----------------------------------------------------------
    arm("clean-10-col-ok", "0/OK", ["--task", w(_doc(_row(), _row(rid="2", depends="1")))])
    legacy_header = (
        "| # | Task | Owner | Deliverable | Validation | Depends on | "
        "Context strategy | Durable outputs | Status |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
    )
    legacy_row = (
        f"| 1 | do it | coder | a file | {_CMD} | — | shared | receipt | `[ ]` |\n"
    )
    arm("legacy-9-col-ok", "0/OK", ["--task", w(_doc(legacy_row, header=legacy_header))])
    # Two rows on purpose: a table whose only row is exempt is refused by the
    # all-exempt rule below, so a single-row fixture would test the wrong thing.
    arm(
        "view-file-row-needs-no-receipt-ok",
        "0/OK",
        ["--task", w(_doc(
            _row(rid="1", validation="`view_file: templates/HANDOFF-TEMPLATE.md`"),
            _row(rid="2", depends="1"),
        ))],
    )
    arm(
        "posix-exit-form-ok",
        "0/OK",
        ["--task", w(_doc(_row(
            validation="`python tools/x.py > \"$RECEIPTS_DIR/x.txt\" 2>&1; code=$?; "
                       "cat \"$RECEIPTS_DIR/x.txt\"; exit $code`")))],
    )
    arm(
        "divider-and-ellipsis-rows-skipped-ok",
        "0/OK",
        ["--task", w(_doc(
            "| | **📋 Phase H1 — Pre-Review Closeout** | | | | | | | | |\n",
            _row(),
            "| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |\n",
        ))],
    )
    arm(
        "blocked-row-with-followup-ok",
        "0/OK",
        ["--task", w(_doc(_row(status="`[B]`", task="blocked on ISSUE-42, error in receipt")))],
    )
    arm(
        "template-mode-allows-placeholders-ok",
        "0/OK",
        ["--task", w(_doc(_row(
            validation="`rtk proxy uv run python tools/x.py --plan {plan-file} *> "
                       "" + RD_TOKEN + "/x.txt; $code=$LASTEXITCODE; exit $code`",
            depends="`{last-task-id}`"))), "--template-mode"],
    )
    arm(
        "non-shared-with-durable-output-ok",
        "0/OK",
        ["--task", w(_doc(_row(strategy="compact_continue", durable="`x.md`; compact then re-read")))],
    )

    # A headerless continuation table separated by prose -- TASK-TEMPLATE.md's shape.
    # The broken row is deliberately in the CONTINUATION table: with the old
    # stop-at-first-prose-line scan this file linted clean, because the 14 closeout
    # rows were never reached. An arm whose bad row sits in the first table would not
    # have caught that.
    continuation = _doc(
        _row(rid="1"),
        "\n`context_strategy` must be `shared|compact_continue|isolated`.\n\n"
        "> A blockquote paragraph between the two tables.\n\n",
        "| | **📋 Phase H1** | | | | | | | | |\n",
        _row(rid="H1-1", depends="1", validation=(
            "`python tools/x.py *> " + RD_TOKEN + "/x.txt; "
            "Get-Content " + RD_TOKEN + "/x.txt; exit 0`")),
    )
    arm(
        "continuation-table-rows-are-linted",
        "1/REFUSE",
        ["--task", w(continuation)],
        must_say="row H1-1 Validation ends in 'exit 0'",
    )
    arm(
        "status-legend-table-not-linted-ok",
        "0/OK",
        ["--task", w(_doc(_row()) + "\n| Symbol | Meaning |\n|---|---|\n| `[ ]` | Not started |\n")],
    )
    arm(
        "every-row-exempt-refused",
        "1/REFUSE",
        ["--task", w(_doc(
            _row(rid="1", validation="`{exact command}`"),
            _row(rid="2", validation="`{other command}`"),
        )), "--template-mode"],
        must_say="not one of them reached the command checks",
    )

    # -- structural refusals ----------------------------------------------------
    arm(
        "unescaped-pipe-splits-row-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(
            validation="`python tools/x.py | tee " + RD_TOKEN + "/x.txt; exit $LASTEXITCODE`")))],
        must_say="An unescaped '|' inside the Validation command",
    )
    arm(
        "escaped-pipe-in-cell-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(
            validation="`python tools/x.py \\| tee " + RD_TOKEN + "/x.txt; exit $LASTEXITCODE`")))],
        must_say="escapes a pipe",
    )
    arm(
        "unbackticked-command-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(validation="python tools/x.py then check the output")))],
        must_say="not in backticks",
    )
    arm(
        "odd-backticks-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(validation="`python tools/x.py; exit $code")))],
        must_say="odd number of backticks",
    )
    arm(
        "empty-validation-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(validation="—")))],
        must_say="empty Validation cell",
    )
    arm(
        "unbalanced-brace-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(
            validation="`rtk proxy pwsh -Command { python tools/x.py *> "
                       "" + RD_TOKEN + "/x.txt; exit $LASTEXITCODE`")))],
        must_say="unbalanced brace",
    )
    arm(
        "unresolved-placeholder-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(
            validation="`python tools/x.py --plan {plan-file} *> " + RD_TOKEN + "/x.txt; "
                       "$code=$LASTEXITCODE; exit $code`")))],
        must_say="unresolved placeholder",
    )
    arm(
        "duplicate-row-id-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(rid="1"), _row(rid="1")))],
        must_say="duplicates line",
    )

    # -- the gate-cannot-fail refusals ------------------------------------------
    arm(
        "exit-zero-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(
            validation="`python tools/x.py *> " + RD_TOKEN + "/x.txt; "
                       "Get-Content " + RD_TOKEN + "/x.txt; exit 0`")))],
        must_say="ends in 'exit 0'",
    )
    arm(
        "no-exit-code-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(
            validation="`python tools/x.py *> " + RD_TOKEN + "/x.txt; "
                       "Get-Content " + RD_TOKEN + "/x.txt`")))],
        must_say="never re-exits the command's status",
    )
    arm(
        "exit-code-never-assigned-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(
            validation="`python tools/x.py *> " + RD_TOKEN + "/x.txt; "
                       "Get-Content " + RD_TOKEN + "/x.txt; exit $code`")))],
        must_say="exits '$code' but never assigns it",
    )
    _no_receipt = _doc(_row(
        validation="`python tools/x.py; $code=$LASTEXITCODE; exit $code`"))
    arm(
        "no-receipt-refused",
        "1/REFUSE",
        ["--task", w(_no_receipt)],
        must_say="writes no receipt",
    )
    # The same fixture, with no configured receipts root. On an installed tree the token is
    # already an absolute path, so "I see no receipts reference" no longer implies "this row
    # writes no receipt" -- it may just be a path this process cannot recognise. Refusing
    # there would be a guess dressed as a verdict, so it is 3.
    arm(
        "no-receipt-without-configured-root-fails-closed",
        "3/FAIL-CLOSED",
        ["--task", w(_no_receipt)],
        must_say="RECEIPTS_DIR is unset",
        receipts_dir=None,
    )
    # F11: an *instantiated* row. The receipts token is gone, replaced by the absolute path
    # instantiate.py was given, and the linter has to accept it -- this is the shape of every
    # row in every adopter's installed template.
    arm(
        "instantiated-absolute-receipt-path-ok",
        "0/OK",
        ["--task", w(_doc(_row(
            validation=("`python tools/x.py *> /opt/receipts/x.txt; $code=$LASTEXITCODE; "
                        "Get-Content /opt/receipts/x.txt; exit $code`")),
            _row(rid="2", depends="1", validation=(
                "`python tools/y.py *> /opt/receipts/y.txt; $code=$LASTEXITCODE; "
                "Get-Content /opt/receipts/y.txt; exit $code`"))))],
        receipts_dir="/opt/receipts",
    )
    # F03, the exact reproduction from the independent review: every token the old
    # anywhere-search wanted is present, but `code=$?` runs after `cat`, so it records the
    # reader's status and the row exits 0 while the checked command failed.
    arm(
        "capture-after-reader-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(
            validation=("`false > $RECEIPTS_DIR/check.txt 2>&1; cat $RECEIPTS_DIR/check.txt; "
                        "code=$?; exit $code`"))))],
        must_say="captures the exit status too late",
    )
    # F03's other half: a cell that only *reads* a receipt. It named the receipts root, which
    # was the entire durable-evidence test, while writing nothing anyone could re-open.
    arm(
        "receipt-mentioned-but-not-written-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(
            validation=("`Get-Content $env:RECEIPTS_DIR/x.txt; $code=$LASTEXITCODE; "
                        "exit $code`"))))],
        must_say="never redirects into it",
    )
    # F12: PowerShell braces are not authoring placeholders. Both of these were refused as
    # "unresolved placeholder(s)" in a fully filled row, which pushes an author to weaken the
    # placeholder check -- the one clause here that catches rows nobody can run.
    arm(
        "scriptblock-is-not-a-placeholder-ok",
        "0/OK",
        ["--task", w(_doc(
            _row(validation=("`& { python tools/x.py } *> ${RECEIPTS_DIR}/x.txt; "
                             "$code=$LASTEXITCODE; Get-Content ${RECEIPTS_DIR}/x.txt; "
                             "exit $code`")),
            _row(rid="2", depends="1")))],
    )
    arm(
        "bare-receipts-dir-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(
            validation="`python tools/x.py *> " + RD_TOKEN + "; "
                       "$code=$LASTEXITCODE; exit $code`")))],
        must_say="not a path under it",
    )

    # -- enum / contract refusals -----------------------------------------------
    arm(
        "bad-context-strategy-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(strategy="fresh_worker")))],
        must_say="the enum is exactly",
    )
    arm(
        "non-shared-without-durable-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(strategy="isolated", durable="—")))],
        must_say="names no durable output",
    )
    arm(
        "bad-status-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(status="`done`")))],
        must_say="the legend is",
    )
    arm(
        "blocked-without-followup-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(status="`[B]`", task="ran out of time")))],
        must_say="[B] with no linked follow-up",
    )
    arm(
        "model-slug-as-builder-model-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(model="`some-vendor-model-4-5-20260101`")))],
        must_say="not a capability class",
    )
    arm(
        "auto-as-builder-model-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(model="`auto`")))],
        must_say="not a capability class",
    )
    arm(
        "custom-builder-class-accepted-ok",
        "0/OK",
        ["--task", w(_doc(_row(model="`researcher`"))),
         "--allowed-builder-classes", "builder,coordinator,verifier,researcher"],
    )
    arm(
        "dash-builder-model-ok",
        "0/OK",
        ["--task", w(_doc(_row(model="—")))],
    )

    # -- dependency refusals ----------------------------------------------------
    arm(
        "dependency-on-missing-row-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(rid="1", depends="H9-9")))],
        must_say="not a row in this table",
    )
    arm(
        "dependency-cycle-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(rid="1", depends="2"), _row(rid="2", depends="1")))],
        must_say="contain a cycle",
    )
    arm(
        "self-dependency-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(rid="1", depends="1")))],
        must_say="contain a cycle",
    )
    arm(
        "unresolved-dependency-placeholder-refused",
        "1/REFUSE",
        ["--task", w(_doc(_row(depends="`{last-task-id}`")))],
        must_say="depends on unresolved placeholder",
    )
    arm(
        "long-dependency-chain-ok",
        "0/OK",
        ["--task", w(_doc(
            _row(rid="1"), _row(rid="2", depends="1"), _row(rid="3", depends="1, 2"),
            _row(rid="4", depends="3"),
        ))],
    )

    # -- fail-closed arms -------------------------------------------------------
    arm(
        "missing-file-fails-closed",
        "3/FAIL-CLOSED",
        ["--task", str(tmp / "nope.md")],
        must_say="not found",
    )
    arm(
        "no-table-fails-closed",
        "3/FAIL-CLOSED",
        ["--task", w("# Task\n\nNo table here at all.\n")],
        must_say="no Task Table header row found",
    )
    arm(
        "header-only-fails-closed",
        "3/FAIL-CLOSED",
        ["--task", w(_doc())],
        must_say="header but no data rows",
    )
    arm(
        "empty-file-refused",
        "1/REFUSE",
        ["--task", w("   \n")],
        must_say="is empty",
    )
    missing_col = (
        "| # | Task | Owner | Deliverable | Validation | Status |\n"
        "|---|---|---|---|---|---|\n"
        f"| 1 | do it | coder | a file | {_CMD} | `[ ]` |\n"
    )
    arm(
        "missing-required-column-refused",
        "1/REFUSE",
        ["--task", w(_doc(header=missing_col))],
        must_say="missing required column",
    )

    # -- usage arms -------------------------------------------------------------
    arm("no-task-is-usage", "2/USAGE", [], must_say="requires --task")
    arm(
        "empty-builder-class-list-is-usage",
        "2/USAGE",
        ["--task", w(_doc(_row())), "--allowed-builder-classes", ""],
        must_say="at least one class",
    )

    failures = [r for r in results if r[1] != r[2]]
    must_ok = sum(1 for r in results if r[1] == "0/OK")
    for label, want, got in results:
        print(f"  {'ok  ' if want == got else 'FAIL'} {label} want={want} got={got}")
    print(
        f"\nRESULT: {len(results)} arm(s), {len(failures)} failure(s) "
        f"[{must_ok} must-OK arms, so the linter is not refusing everything]"
    )
    return 1 if failures else 0


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lint_task_contract.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--task", help="path to the task.md whose Task Table is linted")
    p.add_argument(
        "--template-mode",
        action="store_true",
        help="allow {placeholder} tokens; for linting TASK-TEMPLATE.md itself, never a real task.md",
    )
    p.add_argument(
        "--allowed-builder-classes",
        default=",".join(DEFAULT_BUILDER_CLASSES),
        help="comma-separated capability classes valid in builder_model",
    )
    p.add_argument("--output", help="write a JSON receipt of the result here")
    p.add_argument("--selftest", action="store_true", help="prove every refusal can fire")
    return p


def main(argv: list[str] | None = None, parser: argparse.ArgumentParser | None = None) -> int:
    parser = parser or build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.selftest:
        return selftest()

    result: dict[str, object] = {"task": args.task, "template_mode": args.template_mode}
    try:
        if not args.task:
            raise Usage("requires --task PATH (or --selftest).")
        classes = tuple(c.strip() for c in args.allowed_builder_classes.split(",") if c.strip())
        if not classes:
            raise Usage(
                "--allowed-builder-classes needs at least one class. An empty list "
                "would reject every builder_model value, which is a broken gate "
                "rather than a strict one."
            )
        notes = lint(args.task, args.template_mode, classes)
    except Refuse as exc:
        line, code = f"REFUSE: {exc}", 1
    except FailClosed as exc:
        line, code = f"FAIL-CLOSED: {exc}", 3
    except Usage as exc:
        line, code = f"USAGE: {exc}", 2
    else:
        line, code = "OK: " + "; ".join(notes), 0

    print(line)
    if args.output:
        result.update(exit_code=code, result=line)
        try:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            # Reported, and it cannot turn a refusal into a pass: the lint verdict
            # already stands. But it must not turn a refusal into a *success* either,
            # so a failed receipt write only ever raises the code.
            print(f"FAIL-CLOSED: lint verdict stands, but the receipt could not be written to {args.output}: {exc}")
            return max(code, 3)
    return code


if __name__ == "__main__":
    sys.exit(main())
