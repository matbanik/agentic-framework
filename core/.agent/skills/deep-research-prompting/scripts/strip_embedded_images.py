"""Decode the base64 images a portal export embeds in ``output-*.md``.

Gemini's portal export puts each figure in the report as a ``data:image`` URI,
either as a reference definition (``[image1]: <data:image/png;base64,...>``,
cited as ``![][image1]``) or inline (``![alt](data:image/png;base64,...)``). One
figure can be several hundred kilobytes of base64, which floods any agent that
reads the file and bloats git.

This script decodes every embedded image to ``{topic}/images/<provider>-<id>.<ext>``
(inline images take the id ``inline<n>``), points the link at that file and
rewrites the output in place; a Markdown link title is kept. The image bytes
are kept unchanged, so the step is lossless. Two figures never share a file:
when a name is already taken, by an earlier figure or by a different file in
``images/``, the next one gets ``-2``, ``-3`` and so on. A second run finds
nothing to do.

Every check runs before anything is written. A payload that is empty or does
not decode, or a ``data:image`` URI in a form the script does not convert,
leaves the file and the image folder untouched.

Usage::

    python strip_embedded_images.py <topic-dir> [<glob>]

``<glob>`` selects the output files (default ``output-*.md``), for a project
that names its portal outputs differently.

Exit codes: 0 every output file is clean; 1 a file has an image the script
could not convert (that file is unchanged); 2 bad invocation.
"""

from __future__ import annotations

import base64
import binascii
import itertools
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

IMAGES_DIR = "images"
OUTPUT_GLOB = "output-*.md"

_TITLE = r"(?P<title>[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^)\n]*\)))?"
REF_DEFINITION = re.compile(
    r"^(?P<lead>\[(?P<id>[^\]\n]+)\]:[ \t]*)"
    r"<?data:image/(?P<subtype>[\w.+-]+);base64,(?P<data>[^>\s]*)>?"
    + _TITLE
    + r"[ \t]*(?=\r?$)",
    re.MULTILINE,
)
INLINE_IMAGE = re.compile(
    r"!\[(?P<alt>[^\]\n]*)\]\(data:image/(?P<subtype>[\w.+-]+);base64,(?P<data>[^)\s]*)"
    + _TITLE
    + r"\)"
)
#: Any embedded image, converted or not; one outside every match fails the file.
EMBEDDED_URI = re.compile(r"data:image/[\w.+-]+;base64,", re.IGNORECASE)
SUBTYPE_EXTENSIONS = {"svg+xml": "svg"}
SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class _Found:
    start: int
    end: int
    stem: str
    extension: str
    payload: bytes
    prefix: str
    suffix: str


@dataclass(frozen=True)
class _Embedded:
    start: int
    end: int
    replacement: str
    target: Path
    payload: bytes


def _extension(subtype: str) -> str:
    subtype = subtype.lower()
    return SUBTYPE_EXTENSIONS.get(subtype, subtype.split("+", 1)[0])


def _provider(path: Path) -> str:
    stem = path.stem
    return stem[len("output-"):] if stem.startswith("output-") else stem


def _decode(data: str, label: str, path: Path) -> bytes:
    if not data:
        raise ValueError(f"{path.name}: {label}: empty base64 payload")
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{path.name}: {label}: malformed base64 payload ({exc})") from exc


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _scan(path: Path, text: str) -> list[_Found]:
    """Find and decode every embedded image, in text order; fail on any left over."""
    provider = _provider(path)
    found: list[_Found] = []
    for match in REF_DEFINITION.finditer(text):
        found.append(
            _Found(
                start=match.start(),
                end=match.end(),
                stem=f"{provider}-{SAFE_ID.sub('-', match['id'])}",
                extension=_extension(match["subtype"]),
                payload=_decode(match["data"], match["id"], path),
                prefix=f"{match['lead']}{IMAGES_DIR}/",
                suffix=match["title"] or "",
            )
        )
    for number, match in enumerate(INLINE_IMAGE.finditer(text), start=1):
        found.append(
            _Found(
                start=match.start(),
                end=match.end(),
                stem=f"{provider}-inline{number}",
                extension=_extension(match["subtype"]),
                payload=_decode(match["data"], f"inline image {number}", path),
                prefix=f"![{match['alt']}]({IMAGES_DIR}/",
                suffix=f"{match['title'] or ''})",
            )
        )
    for uri in EMBEDDED_URI.finditer(text):
        if not any(item.start <= uri.start() < item.end for item in found):
            raise ValueError(
                f"{path.name}: line {_line(text, uri.start())}: unhandled embedded image "
                "(not a Markdown image or reference definition)"
            )
    found.sort(key=lambda item: item.start)
    return found


def _allocate(images: Path, item: _Found, taken: set[str]) -> str:
    """Return a file name no other figure uses; an identical existing file is reused."""
    for number in itertools.count(1):
        name = f"{item.stem}{'' if number == 1 else f'-{number}'}.{item.extension}"
        existing = images / name
        free = not existing.exists() or (existing.is_file() and existing.read_bytes() == item.payload)
        if name.lower() not in taken and free:
            taken.add(name.lower())
            return name
    raise AssertionError("itertools.count is unbounded")


def _find_embedded(path: Path, text: str) -> list[_Embedded]:
    """Decode every embedded image and give each its own file, before anything is written."""
    images = path.parent / IMAGES_DIR
    taken: set[str] = set()
    embedded: list[_Embedded] = []
    for item in _scan(path, text):
        name = _allocate(images, item, taken)
        embedded.append(
            _Embedded(
                start=item.start,
                end=item.end,
                replacement=f"{item.prefix}{name}{item.suffix}",
                target=images / name,
                payload=item.payload,
            )
        )
    return embedded


def strip_file(path: Path) -> list[Path]:
    """Strip one output file in place; return the image files written, in text order.

    Raises ``ValueError`` naming the image when a payload is empty or does not
    decode, or when an embedded image is in a form the script does not convert;
    the file and the image folder are then left as they were.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        text = handle.read()
    embedded = _find_embedded(path, text)
    if not embedded:
        return []
    embedded[0].target.parent.mkdir(exist_ok=True)
    for item in embedded:
        item.target.write_bytes(item.payload)
    parts: list[str] = []
    cursor = 0
    for item in embedded:
        parts.append(text[cursor:item.start])
        parts.append(item.replacement)
        cursor = item.end
    parts.append(text[cursor:])
    staged = path.with_name(path.name + ".tmp")
    staged.write_text("".join(parts), encoding="utf-8", newline="")
    os.replace(staged, path)
    return [item.target for item in embedded]


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print("usage: strip_embedded_images.py <topic-dir> [<glob>]", file=sys.stderr)
        return 2
    topic = Path(argv[0])
    pattern = argv[1] if len(argv) == 2 else OUTPUT_GLOB
    if not topic.is_dir():
        print(f"not a directory: {topic}", file=sys.stderr)
        return 2
    failed = False
    for path in sorted(topic.glob(pattern)):
        try:
            written = strip_file(path)
        except ValueError as exc:
            print(f"FAIL {exc}", file=sys.stderr)
            failed = True
            continue
        print(f"{path.name}: {len(written)} image(s) -> {IMAGES_DIR}/")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
