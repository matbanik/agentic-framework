"""Issue Triage — TODO/FIXME/HACK discovery scanner.

Scans source files for TODO, FIXME, and HACK markers in comments.
Produces candidate findings for potential issue registration.
Pure Python — no external dependencies (pathlib + re).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# ─── Configuration ────────────────────────────────────────────────────────

# Patterns to scan for (case-insensitive match)
SCAN_PATTERNS = ("TODO", "FIXME", "HACK")

# Regex that matches any of the scan patterns
_PATTERN_RE = re.compile(
    r"\b(" + "|".join(SCAN_PATTERNS) + r")\b",
    re.IGNORECASE,
)

# Regex to extract issue IDs like TODO(MCP-ZODSTRIP) or FIXME[BUG-123]
_ISSUE_ID_RE = re.compile(
    r"\b(?:TODO|FIXME|HACK)\s*[\(\[]([A-Z][A-Z0-9_-]+[A-Z0-9])[\)\]]",
    re.IGNORECASE,
)

# Directories to exclude from scanning (both single-segment and multi-segment)
EXCLUDED_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        ".env",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".agent",
        ".hypothesis",
        ".kilo",
    }
)

# Multi-segment directory exclusions (use forward-slash normalized paths)
EXCLUDED_PATHS = frozenset(
    {
        "docs/execution",
    }
)

# Binary file extensions to skip
BINARY_EXTENSIONS = frozenset(
    {
        ".pyc",
        ".pyo",
        ".pyd",
        ".so",
        ".dll",
        ".exe",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".svg",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".rar",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".wasm",
        ".map",
        ".lock",
    }
)

# Component inference from path prefixes
_COMPONENT_PREFIXES: dict[str, str] = {
    "packages/core": "core",
    "packages/infrastructure": "infrastructure",
    "packages/api": "api",
    "packages/application": "core",
    "ui": "ui",
    "tools/mcp_server": "mcp-server",
    "tools": "infrastructure",
}

# Comment prefix patterns per file extension
# Lines must start with one of these (after whitespace) to be considered comments
_COMMENT_PREFIXES: dict[str, tuple[str, ...]] = {
    # Python, shell, YAML, TOML, etc.
    ".py": ("#",),
    ".sh": ("#",),
    ".bash": ("#",),
    ".yaml": ("#",),
    ".yml": ("#",),
    ".toml": ("#",),
    ".cfg": ("#",),
    ".ini": ("#", ";"),
    ".conf": ("#",),
    # JavaScript/TypeScript family
    ".js": ("//", "/*", "*"),
    ".jsx": ("//", "/*", "*"),
    ".ts": ("//", "/*", "*"),
    ".tsx": ("//", "/*", "*"),
    ".mjs": ("//", "/*", "*"),
    ".cjs": ("//", "/*", "*"),
    ".css": ("/*", "*"),
    ".scss": ("//", "/*", "*"),
    # C-family
    ".c": ("//", "/*", "*"),
    ".h": ("//", "/*", "*"),
    ".cpp": ("//", "/*", "*"),
    ".rs": ("//", "/*", "*"),
    ".go": ("//", "/*", "*"),
    ".java": ("//", "/*", "*"),
    # Markup
    ".html": ("<!--",),
    ".xml": ("<!--",),
    ".svg": ("<!--",),
    ".md": ("<!--",),
    # Other
    ".sql": ("--", "/*", "*"),
    ".lua": ("--",),
    ".rb": ("#",),
    ".r": ("#",),
    ".ps1": ("#",),
    ".bat": ("REM", "rem", "::"),
    ".cmd": ("REM", "rem", "::"),
    # Data formats with NO comment syntax
    ".json": (),
    ".csv": (),
}

# Valid source values for --source
VALID_SOURCES = frozenset({"todo"})


# ─── Scanner ──────────────────────────────────────────────────────────────


def scan_todos(
    root: Path,
    *,
    existing_issue_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Scan a directory tree for TODO/FIXME/HACK markers in comments.

    Args:
        root: Root directory to scan.
        existing_issue_ids: Known issue IDs for deduplication. Comments
            mentioning these IDs get a ``linked_issue_id`` field instead
            of being treated as new candidates.

    Returns:
        List of findings, each with:
          - file_path: str (relative to root)
          - line_number: int (1-indexed)
          - pattern: str ("TODO" | "FIXME" | "HACK")
          - raw_text: str (trimmed line content)
          - component: str (inferred from path)
          - linked_issue_id: str | None (if matching existing issue)
    """
    existing_ids = existing_issue_ids or set()
    findings: list[dict[str, Any]] = []

    for file_path in _walk_source_files(root, root):
        rel_path = file_path.relative_to(root)
        component = _infer_component(str(rel_path))
        comment_prefixes = _get_comment_prefixes(file_path.suffix.lower())

        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for line_num, line in enumerate(text.splitlines(), start=1):
            # Only scan comment lines — skip string literals and code
            if not _is_comment_line(line, comment_prefixes):
                continue

            match = _PATTERN_RE.search(line)
            if match:
                pattern = match.group(1).upper()
                linked_id = _extract_linked_id(line, existing_ids)
                findings.append(
                    {
                        "file_path": str(rel_path),
                        "line_number": line_num,
                        "pattern": pattern,
                        "raw_text": line.strip(),
                        "component": component,
                        "linked_issue_id": linked_id,
                    }
                )

    return findings


# ─── Helpers ──────────────────────────────────────────────────────────────


def _walk_source_files(directory: Path, scan_root: Path) -> list[Path]:
    """Walk directory tree, excluding configured paths and binary files.

    Args:
        directory: Current directory being iterated.
        scan_root: The original root of the scan (preserved across recursion
            for multi-segment exclusion checks).
    """
    results: list[Path] = []

    if not directory.is_dir():
        return results

    for item in sorted(directory.iterdir()):
        if item.is_dir():
            # Single-segment exclusion (name-only)
            if item.name in EXCLUDED_DIRS:
                continue
            # Multi-segment exclusion (relative to original scan root)
            try:
                rel = str(item.relative_to(scan_root)).replace("\\", "/")
            except ValueError:
                rel = item.name
            if rel in EXCLUDED_PATHS:
                continue
            results.extend(_walk_source_files(item, scan_root))
        elif item.is_file():
            if item.suffix.lower() in BINARY_EXTENSIONS:
                continue
            results.append(item)

    return results


def _infer_component(rel_path: str) -> str:
    """Infer component name from relative file path.

    Falls back to 'infrastructure' for paths that don't match any prefix,
    which is a valid component in the issue schema.
    """
    normalized = rel_path.replace("\\", "/")
    for prefix, component in _COMPONENT_PREFIXES.items():
        if normalized.startswith(prefix + "/") or normalized.startswith(prefix + "\\"):
            return component
    return "infrastructure"


def _get_comment_prefixes(extension: str) -> tuple[str, ...] | None:
    """Get comment prefix patterns for a file extension.

    Returns None for unknown extensions (conservative: scan all lines).
    Returns empty tuple for extensions with no comment syntax (e.g., JSON).
    """
    return _COMMENT_PREFIXES.get(extension)


def _is_comment_line(line: str, comment_prefixes: tuple[str, ...] | None) -> bool:
    """Check if a line contains a comment.

    If comment_prefixes is None (unknown file type), returns True (conservative).
    If comment_prefixes is empty (no comment syntax, e.g. JSON), returns False.
    Otherwise checks if the line starts with or contains a comment prefix.
    """
    if comment_prefixes is None:
        return True
    if not comment_prefixes:
        return False
    stripped = line.lstrip()
    # Check if line starts with a comment prefix (pure comment line)
    if any(stripped.startswith(prefix) for prefix in comment_prefixes):
        return True
    # Check for inline comments (e.g., `x = 1  # TODO: fix`)
    return any(
        f" {prefix}" in line or f"\t{prefix}" in line for prefix in comment_prefixes
    )


def _extract_linked_id(line: str, existing_ids: set[str]) -> str | None:
    """Extract linked issue ID from a TODO/FIXME comment if it matches known IDs."""
    match = _ISSUE_ID_RE.search(line)
    if match:
        candidate_id = match.group(1)
        if candidate_id in existing_ids:
            return candidate_id
    return None
