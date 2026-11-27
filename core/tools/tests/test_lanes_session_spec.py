"""MEU-924 grouping spec keys: AC-924.1 to AC-924.5 (plan 2026-11-05-ao1-grouping-spec-scheduler).

Row 924-R writes these tests on the unchanged ``tools/lanes.py`` and
``session-grouping.md``, so they fail first (RED). Each test imports ``tools.lanes``
inside its body and reads the new names there, so an absent name fails the test and
the file still collects on the unchanged tree (G19). Do not skip, only, or
early-return (G36).

Design choices that row 924-G implements (the tests pin each one):

* ``parse_session_spec(block)`` takes the lines inside the ``yaml`` fence of a
  ``## Session Ownership`` section (the input of ``_parse_session_ownership``) and
  returns one frozen ``SessionSpec`` per session, in file order. Its fields are
  ``session``, ``tier``, ``owns``, ``after``, ``size``, ``review_effort``, ``vm``,
  ``e2e``, ``hold`` and ``planning``. ``owns`` and ``after`` are tuples of strings.
  ``hold`` is ``None`` or a frozen ``Hold`` with the fields ``kind`` and ``reason``.
* ``SESSION_OWNERSHIP_KEYS`` is ``tier``, ``owns`` and the seven spec keys in the
  order ``after``, ``size``, ``review_effort``, ``vm``, ``e2e``, ``hold``,
  ``planning``. The value sets are the tuples ``SIZE_VALUES``,
  ``REVIEW_EFFORT_VALUES``, ``HOLD_KINDS`` and ``PLANNING_VALUES``.
* The line forms (AO1-D15)::

      after:
        - <session id>
      after: []
      hold: null
      hold:
        kind: <external | human>
        reason: "<text>"
      vm: <true | false>

  An absent key takes its default: ``after`` ``()``, ``vm`` and ``e2e`` ``False``,
  ``size``, ``review_effort``, ``hold`` and ``planning`` ``None``.
* A wrong type, a value outside its set or a repeated key raises ``Refusal`` with
  the reason ``ownership_bad:<key>:<session>``; ``ownership-check --grouping``
  prints that reason and exits 1. An unknown key stays
  ``ownership_bad:extra_key:<key>``.
* ``_parse_session_ownership(block)`` is the projection
  ``(spec.session, spec.tier, list(spec.owns))`` of ``parse_session_spec(block)``.
* B2a of ``session-grouping.md`` (from ``**B2a. Session Ownership.**`` to ``**B3.``)
  shows the seven keys in its ``yaml`` template, has a key table with a ``Key`` and
  a ``Default`` column and one row per key, has a sentence that says none of the
  keys is required, and has a sentence that says ``orch.py simulate`` needs
  ``size``.

Framework port (AC-924.7): the tests that read the adopter's own grouping files
(the live part of AC-924.2 and all of AC-924.4) stay in the adopter. The other tests
read only their own fixtures, ``tools/lanes.py`` and
``.agent/workflows/session-grouping.md``, so the same file runs in the framework
(``core/``) and in a fresh adoption.
"""

from __future__ import annotations

import dataclasses
import importlib
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence

import pytest

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "tools" / "lanes.py"
SESSION_GROUPING = ROOT / ".agent" / "workflows" / "session-grouping.md"

OWNERSHIP_OK = "ownership_ok"
SPEC_KEYS = ("after", "size", "review_effort", "vm", "e2e", "hold", "planning")
ALL_KEYS = ("tier", "owns", *SPEC_KEYS)
SIZES = ("small", "small-to-medium", "medium", "medium-to-large", "large")
REVIEW_EFFORTS = ("class-default", "one-tier-up")
HOLD_KINDS = ("external", "human")
PLANNINGS = ("any-time", "early-refresh", "wait-at-r0")
SPEC_FIELDS = (
    "session",
    "tier",
    "owns",
    "after",
    "size",
    "review_effort",
    "vm",
    "e2e",
    "hold",
    "planning",
)

# Session A1 with every key at a value that is not its default.
FULL_A1 = (
    "    after:",
    "      - A2",
    "      - A3",
    "    size: medium-to-large",
    "    review_effort: one-tier-up",
    "    vm: true",
    "    e2e: false",
    "    hold:",
    "      kind: human",
    '      reason: "The user rules D-1 first."',
    "    planning: wait-at-r0",
)
# Session A2 with every key in its empty or false form.
FULL_A2 = (
    "    after: []",
    "    size: small",
    "    review_effort: class-default",
    "    vm: false",
    "    e2e: true",
    "    hold: null",
    "    planning: any-time",
)

# AC-924.3: (case id, the A1 key lines, the key that the refusal names).
BAD_CASES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("after_bad_id", ("    after:", "      - bad id"), "after"),
    ("after_self", ("    after:", "      - A1"), "after"),
    ("after_duplicate", ("    after:", "      - A2", "      - A2"), "after"),
    ("after_scalar", ("    after: A2",), "after"),
    ("size_huge", ("    size: huge",), "size"),
    ("review_effort_max", ("    review_effort: max",), "review_effort"),
    ("vm_yes", ("    vm: yes",), "vm"),
    ("vm_1", ("    vm: 1",), "vm"),
    ("e2e_yes", ("    e2e: yes",), "e2e"),
    ("e2e_1", ("    e2e: 1",), "e2e"),
    ("hold_missing_reason", ("    hold:", "      kind: human"), "hold"),
    (
        "hold_empty_reason",
        ("    hold:", "      kind: human", '      reason: ""'),
        "hold",
    ),
    ("hold_kind_soft", ("    hold:", "      kind: soft", '      reason: "x"'), "hold"),
    (
        "hold_extra_key",
        ("    hold:", "      kind: human", '      reason: "x"', "      note: y"),
        "hold",
    ),
    ("hold_scalar", ("    hold: human",), "hold"),
    ("hold_missing_kind", ("    hold:", '      reason: "x"'), "hold"),
    (
        "hold_unquoted_reason",
        ("    hold:", "      kind: human", "      reason: plain words"),
        "hold",
    ),
    ("planning_later", ("    planning: later",), "planning"),
    ("repeated_key", ("    size: small", "    size: large"), "size"),
)

# AC-924.1: (key, value as written, parsed value) for each listed scalar value.
GOOD_VALUES: tuple[tuple[str, str, object], ...] = (
    *(("size", value, value) for value in SIZES),
    *(("review_effort", value, value) for value in REVIEW_EFFORTS),
    *(("planning", value, value) for value in PLANNINGS),
    ("vm", "true", True),
    ("vm", "false", False),
    ("e2e", "true", True),
    ("e2e", "false", False),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lanes() -> ModuleType:
    return importlib.import_module("tools.lanes")


def _text(path: Path) -> str:
    """The file's UTF-8 text with LF line ends."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _flat(text: str) -> str:
    """``text`` with every whitespace run made one space."""
    return " ".join(text.split())


def _sentences(text: str) -> list[str]:
    """The sentences of ``text`` (flattened, split after ``.``, ``!`` or ``?``)."""
    return re.split(r"(?<=[.!?])\s+(?=[A-Z`*(])", _flat(text))


def _between(text: str, start: str, end: str) -> str:
    """The text from the first line that starts with ``start`` up to the line ``end``."""
    lines = text.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(start))
    last = next(i for i in range(first + 1, len(lines)) if lines[i].startswith(end))
    return "\n".join(lines[first:last])


def _cells(row: str) -> list[str]:
    """The cells of a table row; an escaped ``\\|`` stays inside its cell."""
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", row.strip())[1:-1]]


def _session(
    session: str, tier: object, owns: Sequence[str], extra: Sequence[str] = ()
) -> list[str]:
    """The block lines of one session: ``tier``, ``owns``, then ``extra`` as written."""
    lines = [f"  {session}:", f"    tier: {tier}"]
    if owns:
        lines += ["    owns:", *(f"      - {entry}" for entry in owns)]
    else:
        lines.append("    owns: []")
    return lines + list(extra)


def _block(*sessions: list[str]) -> list[str]:
    """A Session Ownership block: ``sessions:`` and the session lines."""
    return ["sessions:", *(line for lines in sessions for line in lines)]


def _three(extra: Sequence[str]) -> list[str]:
    """A1 with ``extra``, then the plain sessions A2 and A3."""
    return _block(
        _session("A1", 1, ["tools/a.py"], extra),
        _session("A2", 2, ["docs/"]),
        _session("A3", 2, ["ui/"]),
    )


def _grouping(block: Sequence[str]) -> str:
    """A grouping file whose one ``## Session Ownership`` fence holds ``block``."""
    body = ["# Grouping", "", "## Session Ownership", "", "```yaml", *block, "```"]
    return "\n".join([*body, "", "## Session Progress", ""]) + "\n"


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``tools/lanes.py <args>`` with ``cwd``; never raises on exit."""
    return subprocess.run(
        [sys.executable, str(LANES), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )


def _lines(proc: subprocess.CompletedProcess[str]) -> list[str]:
    """The stdout lines with an optional ``refused: `` prefix removed."""
    return [line.removeprefix("refused: ").strip() for line in proc.stdout.splitlines()]


def _show(proc: subprocess.CompletedProcess[str]) -> str:
    return (
        f"exit={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr[-800:]!r}"
    )


def _check_grouping(tmp_path: Path, text: str) -> subprocess.CompletedProcess[str]:
    """``ownership-check --grouping`` on ``text`` in a new git repository."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", str(repo)],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    (repo / "grouping.md").write_text(text, encoding="utf-8", newline="\n")
    return _run(repo, "ownership-check", "--grouping", "grouping.md")


def _raw_keys(block: Sequence[str]) -> dict[str, list[str]]:
    """The key names that each session of ``block`` writes at indent 4, in order."""
    out: dict[str, list[str]] = {}
    session: str | None = None
    for line in block:
        head = re.fullmatch(r"  ([A-Za-z0-9][A-Za-z0-9._-]*):\s*", line)
        if head is not None:
            session = str(head.group(1))
            out[session] = []
            continue
        key = re.fullmatch(r"    ([A-Za-z_][A-Za-z0-9_]*):.*", line)
        if key is not None and session is not None:
            out[session].append(key.group(1))
    return out


def _b2a(text: str) -> str:
    return _between(text, "**B2a. Session Ownership.**", "**B3.")


def _fence(section: str) -> list[str]:
    """The lines of the first ``yaml`` fence of ``section``."""
    lines = section.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "```yaml")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "```")
    return lines[start + 1 : end]


def _b2a_problems(text: str) -> list[str]:
    """What B2a of ``text`` (the whole ``session-grouping.md``) lacks; ``[]`` when complete."""
    problems: list[str] = []
    section = _b2a(text)
    try:
        template = _fence(section)
    except StopIteration:
        return ["no_template"]
    for key in SPEC_KEYS:
        if not any(re.match(rf" {{4}}{key}:", line) for line in template):
            problems.append(f"template_lacks:{key}")
    rows = [line for line in section.splitlines() if line.startswith("|")]
    header = next(
        (
            _cells(row)
            for row in rows
            if "Key" in _cells(row) and "Default" in _cells(row)
        ),
        None,
    )
    if header is None:
        problems.append("table_no_header")
        return problems
    at = header.index("Default")
    want_values: dict[str, tuple[str, ...]] = {
        "size": SIZES,
        "review_effort": REVIEW_EFFORTS,
        "vm": ("true", "false"),
        "e2e": ("true", "false"),
        "hold": HOLD_KINDS,
        "planning": PLANNINGS,
    }
    want_default = {
        "after": "`[]`",
        "vm": "`false`",
        "e2e": "`false`",
        "hold": "`null`",
    }
    for key in SPEC_KEYS:
        found = [row for row in rows if row.startswith(f"| `{key}` |")]
        if len(found) != 1:
            problems.append(f"table_lacks:{key}")
            continue
        cells = _cells(found[0])
        for value in want_values.get(key, ()):
            if f"`{value}`" not in found[0]:
                problems.append(f"table_value:{key}:{value}")
        default = cells[at] if at < len(cells) else ""
        if not default or (key in want_default and want_default[key] not in default):
            problems.append(f"table_default:{key}")
    sentences = _sentences(section)
    if not any(
        re.search(r"\bnone\b", s, re.IGNORECASE)
        and "required" in s.lower()
        and "keys" in s.lower()
        for s in sentences
    ):
        problems.append("no_optional_sentence")
    if not any("orch.py simulate" in s and "`size`" in s for s in sentences):
        problems.append("no_simulate_note")
    for token in ("## Session Ownership", "tools/lanes.py ownership-check --grouping"):
        if token not in section:
            problems.append(f"lacks:{token}")
    # The framework workflow has no `grouping_decisions` text (a project addition to section 8), so the port does not
    # check it.
    return problems


# ---------------------------------------------------------------------------
# AC-924.1: the seven optional keys
# ---------------------------------------------------------------------------


def test_ac_924_1_keys_and_value_sets() -> None:
    """AC-924.1: the key tuple and the four value sets, in the spec order."""
    lanes = _lanes()
    assert lanes.SESSION_OWNERSHIP_KEYS == ALL_KEYS
    assert lanes.SIZE_VALUES == SIZES
    assert lanes.REVIEW_EFFORT_VALUES == REVIEW_EFFORTS
    assert lanes.HOLD_KINDS == HOLD_KINDS
    assert lanes.PLANNING_VALUES == PLANNINGS


def test_ac_924_1_spec_fields_and_frozen() -> None:
    """AC-924.1: ``SessionSpec`` and ``Hold`` are frozen dataclasses with the named fields."""
    lanes = _lanes()
    assert tuple(f.name for f in dataclasses.fields(lanes.SessionSpec)) == SPEC_FIELDS
    assert tuple(f.name for f in dataclasses.fields(lanes.Hold)) == ("kind", "reason")
    spec = lanes.parse_session_spec(_three(FULL_A1))[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.size = "large"
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.hold.kind = "external"


def test_ac_924_1_full_block_parses_every_key() -> None:
    """AC-924.1: every key at a set value, ``[]`` and ``null`` forms, in file order."""
    lanes = _lanes()
    block = _block(
        _session("A1", 1, ["tools/a.py"], FULL_A1),
        _session("A2", 2, [], FULL_A2),
        _session("A3", 2, ["docs/"]),
    )
    specs = lanes.parse_session_spec(block)
    assert [spec.session for spec in specs] == ["A1", "A2", "A3"]
    assert specs[0] == lanes.SessionSpec(
        session="A1",
        tier=1,
        owns=("tools/a.py",),
        after=("A2", "A3"),
        size="medium-to-large",
        review_effort="one-tier-up",
        vm=True,
        e2e=False,
        hold=lanes.Hold(kind="human", reason="The user rules D-1 first."),
        planning="wait-at-r0",
    )
    assert specs[1] == lanes.SessionSpec(
        session="A2",
        tier=2,
        owns=(),
        after=(),
        size="small",
        review_effort="class-default",
        vm=False,
        e2e=True,
        hold=None,
        planning="any-time",
    )


def test_ac_924_1_absent_keys_take_defaults() -> None:
    """AC-924.1: a session with only ``tier`` and ``owns`` gets every default."""
    lanes = _lanes()
    specs = lanes.parse_session_spec(_three(()))
    assert specs[2] == lanes.SessionSpec(
        session="A3",
        tier=2,
        owns=("ui/",),
        after=(),
        size=None,
        review_effort=None,
        vm=False,
        e2e=False,
        hold=None,
        planning=None,
    )
    assert isinstance(specs[2].after, tuple) and isinstance(specs[2].owns, tuple)


@pytest.mark.parametrize(
    ("key", "value", "parsed"),
    GOOD_VALUES,
    ids=[f"{key}_{value}" for key, value, _ in GOOD_VALUES],
)
def test_ac_924_1_each_listed_value_is_accepted(
    key: str, value: str, parsed: object
) -> None:
    """AC-924.1: each value of a value set parses to itself; ``true``/``false`` to bool."""
    lanes = _lanes()
    spec = lanes.parse_session_spec(_three((f"    {key}: {value}",)))[0]
    assert getattr(spec, key) == parsed
    assert type(getattr(spec, key)) is type(parsed)


@pytest.mark.parametrize("kind", HOLD_KINDS)
def test_ac_924_1_each_hold_kind_is_accepted(kind: str) -> None:
    """AC-924.1: ``hold`` with each kind and a double-quoted reason."""
    lanes = _lanes()
    extra = ("    hold:", f"      kind: {kind}", '      reason: "Waits on the X plan."')
    spec = lanes.parse_session_spec(_three(extra))[0]
    assert spec.hold == lanes.Hold(kind=kind, reason="Waits on the X plan.")


@pytest.mark.integration
def test_ac_924_1_cli_accepts_every_key(tmp_path: Path) -> None:
    """AC-924.1: ``ownership-check --grouping`` passes a block with every key."""
    block = _block(
        _session("A1", 1, ["tools/a.py"], FULL_A1),
        _session("A2", 2, ["tools/a.py"], FULL_A2),
        _session("A3", 2, ["docs/"]),
    )
    proc = _check_grouping(tmp_path, _grouping(block))
    assert proc.returncode == 0, _show(proc)
    assert OWNERSHIP_OK in _lines(proc), _show(proc)


@pytest.mark.integration
def test_ac_924_1_refuses_unknown_key(tmp_path: Path) -> None:
    """AC-924.1 negative: ``priority:`` after the seven keys → ``ownership_bad:extra_key:priority``."""
    lanes = _lanes()
    block = _three((*FULL_A1, "    priority: high"))
    with pytest.raises(lanes.Refusal) as caught:
        lanes.parse_session_spec(block)
    assert caught.value.reason == "ownership_bad:extra_key:priority"
    proc = _check_grouping(tmp_path, _grouping(block))
    assert proc.returncode == 1, _show(proc)
    assert "ownership_bad:extra_key:priority" in _lines(proc), _show(proc)


# ---------------------------------------------------------------------------
# AC-924.2: _parse_session_ownership is a projection
# ---------------------------------------------------------------------------


def test_ac_924_2_projection_matches_tier_owns() -> None:
    """AC-924.2: the tuples equal the projection; a new key and a bad tier → the old tier error."""
    lanes = _lanes()
    block = _block(_session("A1", 1, ["tools/"]), _session("A2", 2, ["docs/", "x.md"]))
    tuples = lanes._parse_session_ownership(block)
    assert tuples == [("A1", 1, ["tools/"]), ("A2", 2, ["docs/", "x.md"])]
    specs = lanes.parse_session_spec(block)
    assert tuples == [(spec.session, spec.tier, list(spec.owns)) for spec in specs]
    bad = ["sessions:", "  A1:", "    size: medium", "    tier: 0", "    owns: []"]
    with pytest.raises(lanes.Refusal) as caught:
        lanes._parse_session_ownership(bad)
    assert caught.value.reason == "ownership_bad:tier:A1"


def test_ac_924_2_new_keys_do_not_change_the_tuples() -> None:
    """AC-924.2: the same sessions with and without the seven keys give equal tuples."""
    lanes = _lanes()
    plain = _block(
        _session("A1", 1, ["tools/a.py"]),
        _session("A2", 2, ["tools/a.py"]),
        _session("A3", 2, ["docs/"]),
    )
    keyed = _block(
        _session("A1", 1, ["tools/a.py"], FULL_A1),
        _session("A2", 2, ["tools/a.py"], FULL_A2),
        _session("A3", 2, ["docs/"]),
    )
    assert lanes._parse_session_ownership(keyed) == lanes._parse_session_ownership(
        plain
    )


# ---------------------------------------------------------------------------
# AC-924.3: a bad value names the key and the session
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("extra", "key"),
    [(extra, key) for _, extra, key in BAD_CASES],
    ids=[case for case, _, _ in BAD_CASES],
)
def test_ac_924_3_bad_value_is_ownership_bad(
    tmp_path: Path, extra: tuple[str, ...], key: str
) -> None:
    """AC-924.3: a wrong type, an outside value or a repeated key → ``ownership_bad:<key>:A1``."""
    lanes = _lanes()
    block = _three(extra)
    with pytest.raises(lanes.Refusal) as caught:
        lanes.parse_session_spec(block)
    assert caught.value.reason == f"ownership_bad:{key}:A1"
    proc = _check_grouping(tmp_path, _grouping(block))
    assert proc.returncode == 1, _show(proc)
    assert f"ownership_bad:{key}:A1" in _lines(proc), _show(proc)


# ---------------------------------------------------------------------------
# AC-924.5: session-grouping.md B2a
# ---------------------------------------------------------------------------


def test_ac_924_5_b2a_names_every_key() -> None:
    """AC-924.5: the template, the key table, "none required" and the ``simulate`` note."""
    problems = _b2a_problems(_text(SESSION_GROUPING))
    assert problems == [], problems


@pytest.mark.parametrize("form", ["template", "table"])
@pytest.mark.parametrize("key", SPEC_KEYS)
def test_ac_924_5_b2a_without_a_key_fails(key: str, form: str) -> None:
    """AC-924.5 negative: a copy of the file with one key removed has a problem for that key."""
    lines = _text(SESSION_GROUPING).splitlines()
    if form == "template":
        kept = [line for line in lines if not re.match(rf" {{4}}{key}:", line)]
        want = f"template_lacks:{key}"
    else:
        kept = [line for line in lines if not line.startswith(f"| `{key}` |")]
        want = f"table_lacks:{key}"
    assert len(kept) < len(lines), f"no {form} line for {key}"
    assert want in _b2a_problems("\n".join(kept) + "\n")


def test_ac_924_5_template_block_parses() -> None:
    """AC-924.5: the B2a template parses, and one of its sessions writes every key."""
    lanes = _lanes()
    template = _fence(_b2a(_text(SESSION_GROUPING)))
    specs = lanes.parse_session_spec(template)
    assert specs, template
    raw = _raw_keys(template)
    assert any(sorted(keys) == sorted(ALL_KEYS) for keys in raw.values()), raw
