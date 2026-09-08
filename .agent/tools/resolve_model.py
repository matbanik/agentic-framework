#!/usr/bin/env python3
"""Locate-and-forward wrapper for the registry resolver.

This file is a template pointer, not the implementation. The live
``resolve_model.py`` embeds catalog examples and day-one binding tables that
must not ride a delete-and-recopy package. After you instantiate a registry
home, either keep this wrapper so it forwards along the S2 locate order
(``AGENT_MODEL_REGISTRY``, then ``AGENT_MODEL_REGISTRY_HOME``, then
``%USERPROFILE%/.agent``)
or replace it with the real tool copied from a working registry.

If this file *is* the tool sitting in the located home, it refuses rather
than pretending to resolve. See ``../INSTANTIATE.md``.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def registry_homes() -> list[Path]:
    homes: list[Path] = []
    env = os.environ.get("AGENT_MODEL_REGISTRY")
    if env:
        path = Path(env)
        homes.append(
            path.parent if path.suffix.lower() in {".json", ".yaml", ".yml"} else path
        )
    # Shared / "drive-root" home: a single registry serving several projects on one
    # machine. Configured by env, never a baked drive letter -- a literal like
    # ``P:/.agent`` is one machine's layout and is meaningless on macOS/Linux, where
    # this package is equally supported. See ``.agent/INSTANTIATE.md`` S2.
    shared = os.environ.get("AGENT_MODEL_REGISTRY_HOME")
    if shared:
        homes.append(Path(shared))
    user = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if user:
        homes.append(Path(user) / ".agent")
    return homes


def locate_tool(name: str) -> Path:
    here = Path(__file__).resolve()
    for home in registry_homes():
        candidate = home / "tools" / name
        if not candidate.is_file():
            continue
        if candidate.resolve() == here:
            continue
        return candidate
    searched = ", ".join(str(h) for h in registry_homes()) or "(none)"
    # A fail-closed message that does not name the fix gets "fixed" by disabling
    # the gate. Say what was searched and which env var adds a home.
    sys.stderr.write(
        f"registry_not_found: no live {name} in the S2 locate order. "
        f"Searched: {searched}. Set AGENT_MODEL_REGISTRY to the compiled JSON "
        "file, or AGENT_MODEL_REGISTRY_HOME to the shared registry home. "
        "See INSTANTIATE.md section 1.\n"
    )
    sys.exit(1)


if __name__ == "__main__":
    target = locate_tool(Path(__file__).name)
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
