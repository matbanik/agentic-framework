"""The campaign charter of an orchestrated run (MEU-929).

A charter is a YAML file that sets the limits of one campaign
(``.agent/schemas/campaign-charter.v1.json``). ``load`` reads and validates the file.
``check`` also verifies the typed line of the human that names the charter and its
sha256, the hash of each grouping, the expiry and the ceilings of the sessions. A
charter only tightens, and a check changes nothing.

Each refusal is a ``run_parameters.Refusal`` with the reason ``charter_bad:<reason>`` or
``charter_widens:<key>``. A charter of another version also writes one
``charter_refused`` record to stderr.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from jsonschema.validators import extend

if __package__:
    from . import run_parameters as rp
else:  # run as a script, or imported with tools/ on sys.path
    import run_parameters as rp

CHARTER_VERSION = "campaign-charter/1"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / ".agent"
    / "schemas"
    / "campaign-charter.v1.json"
)
#: The heading of the grouping progress section; this file needs no other orchestrator tool.
PROGRESS_HEADING = "## Session Progress"

_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+")


@dataclass(frozen=True)
class CharterLimits:
    """The verified limits of one charter; ``sha256`` is the digest of its bytes."""

    id: str
    sha256: str
    max_claude_workers: int
    max_codex_reviews: int
    restarts_per_hour: int
    resume_after_usage_limit: bool
    tier_b: Mapping[str, str]
    expires: str


def _is_int(_checker: object, value: object) -> bool:
    """A whole number; unlike the JSON Schema rule, ``1.0`` is not one."""
    return isinstance(value, int) and not isinstance(value, bool)


@functools.cache
def _validator() -> Any:
    """The validator of the charter schema."""
    checker = Draft202012Validator.TYPE_CHECKER.redefine("integer", _is_int)
    cls: Any = extend(Draft202012Validator, type_checker=checker)
    return cls(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _read(path: Path) -> bytes:
    """The bytes of ``path``.

    Raises:
        rp.Refusal: ``charter_bad:unreadable``.
    """
    try:
        return path.read_bytes()
    except (OSError, ValueError) as exc:
        raise rp.Refusal("charter_bad:unreadable", str(exc)) from exc


def _error_order(error: ValidationError) -> tuple[bool, list[str]]:
    """The order of the schema errors: the charter version first, then by path."""
    path = [str(part) for part in error.absolute_path]
    return path != ["charter"], path


def _pointer(error: ValidationError) -> str:
    """The JSON pointer of the value that ``error`` refuses."""
    parts = (str(part) for part in error.absolute_path)
    return "".join(f"/{p.replace('~', '~0').replace('/', '~1')}" for p in parts)


def _utc(value: str) -> datetime:
    """The UTC time of a charter ``expires`` value.

    Raises:
        rp.Refusal: ``charter_bad:schema:/expires`` for a text that is no date.
    """
    try:
        return datetime.strptime(value, rp.TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise rp.Refusal("charter_bad:schema:/expires", str(exc)) from exc


def _parse(data: bytes) -> dict[str, Any]:
    """The validated charter in ``data``.

    Raises:
        rp.Refusal: ``charter_bad:yaml``, ``charter_bad:schema:<json pointer>`` or
            ``charter_bad:backend_default_not_allowed``.
    """
    try:
        value: object = yaml.safe_load(data.decode("utf-8"))
        errors: list[ValidationError] = list(_validator().iter_errors(value))
    except (yaml.YAMLError, ValueError, RecursionError) as exc:
        raise rp.Refusal("charter_bad:yaml", str(exc)) from exc
    if errors:
        error = min(errors, key=_error_order)
        pointer = _pointer(error)
        if pointer == "/charter":
            seen: object = error.instance
            rp._log(
                "charter_refused",
                level="WARN",
                limit_name="charter",
                configured_value=CHARTER_VERSION,
                observed_value=seen if isinstance(seen, str) else type(seen).__name__,
                window="per call",
            )
        raise rp.Refusal(f"charter_bad:schema:{pointer}", error.message)
    charter = cast(dict[str, Any], value)
    try:  # a lone surrogate is a YAML escape that no file and no output can hold
        json.dumps(charter, ensure_ascii=False).encode("utf-8")
    except ValueError as exc:
        raise rp.Refusal("charter_bad:yaml", str(exc)) from exc
    _utc(charter["expires"])
    backends = charter["backends"]
    if backends["default"] not in backends["allowed"]:
        raise rp.Refusal("charter_bad:backend_default_not_allowed")
    return charter


def load(path: Path) -> dict[str, Any]:
    """The charter in the file ``path``, after the schema check.

    Raises:
        rp.Refusal: ``charter_bad:unreadable``, ``charter_bad:yaml``,
            ``charter_bad:schema:<json pointer>`` or
            ``charter_bad:backend_default_not_allowed``.
    """
    return _parse(_read(path))


def _without_progress(text: str) -> str:
    """``text`` without its ``## Session Progress`` section (AG-D7)."""
    kept: list[str] = []
    inside = False
    for line in _LINE_RE.findall(text):
        if line.startswith("## "):
            inside = line.strip() == PROGRESS_HEADING
        if not inside:
            kept.append(line)
    return "".join(kept)


def grouping_digest(text: str) -> str:
    """``sha256:<hex>`` of a grouping text without its ``## Session Progress`` section."""
    data = _without_progress(text).encode("utf-8")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _grouping_text(repo: rp.Repo, entry: Mapping[str, str]) -> str:
    """The hashed text of one charter grouping, after the hash check.

    The text has no ``## Session Progress`` section: the charter does not bind that
    section, so it can give no session and no ceiling.

    Raises:
        rp.Refusal: ``charter_bad:grouping_sha:<path>`` for a missing file, a file that
            is not UTF-8, or another hash.
    """
    path = entry["path"]
    try:
        text = (repo.top / path).read_bytes().decode("utf-8")
    except (OSError, ValueError) as exc:
        raise rp.Refusal(f"charter_bad:grouping_sha:{path}", str(exc)) from exc
    if grouping_digest(text) != entry["sha256"]:
        raise rp.Refusal(f"charter_bad:grouping_sha:{path}")
    return _without_progress(text)


def check(
    repo: Path | rp.Repo, path: Path, session: str, message: str
) -> CharterLimits:
    """The verified limits of the charter ``path`` (AC-929.1 to AC-929.5).

    ``repo`` is an ``_open_repo`` handle or a path in the repository. ``message`` is the
    uuid of the typed line in the transcript of ``session``. The order is: the schema, the
    typed line, the hash of each grouping, the expiry on the store clock, the ceilings.
    The charter bytes are read one time, so the typed sha256 is the digest of the bytes
    that give the limits. The check changes nothing.

    Raises:
        rp.Refusal: ``charter_bad:<reason>`` or ``charter_widens:<key>``.
    """
    handle = rp._as_repo(repo)
    data = _read(path)
    charter = _parse(data)
    rp.charter_authority(handle, session, message, path, data=data)
    groupings = {
        entry["path"]: _grouping_text(handle, entry) for entry in charter["groupings"]
    }
    if rp._now(handle) > _utc(charter["expires"]):
        raise rp.Refusal("charter_bad:expired", charter["expires"])
    rp.charter_allowance(handle, charter, groupings)
    concurrency = charter["concurrency"]
    quota = charter["quota"]
    return CharterLimits(
        id=charter["id"],
        sha256=f"sha256:{hashlib.sha256(data).hexdigest()}",
        max_claude_workers=concurrency["max_claude_workers"],
        max_codex_reviews=concurrency["max_codex_reviews"],
        restarts_per_hour=quota["restarts_per_hour"],
        resume_after_usage_limit=quota["resume_after_usage_limit"],
        tier_b=dict(charter["decisions"]["tier_b"]),
        expires=charter["expires"],
    )
