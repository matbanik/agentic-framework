#!/usr/bin/env python3
"""Locate-and-forward wrapper for the registry resolver.

This file is a template pointer, not the implementation. The live
``resolve_model.py`` embeds catalog examples and day-one binding tables that
must not ride a delete-and-recopy package. After you instantiate a registry
home, either keep this wrapper so it forwards along the S2 locate order
(``AGENT_MODEL_REGISTRY``, then ``P:/.agent``, then ``%USERPROFILE%/.agent``)
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
    homes.append(Path("P:/.agent"))
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
    sys.stderr.write(
        "registry_not_found: no live "
        f"{name} in the S2 locate order. See INSTANTIATE.md.\n"
    )
    sys.exit(1)


if __name__ == "__main__":
    target = locate_tool(Path(__file__).name)
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
