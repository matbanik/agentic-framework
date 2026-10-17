"""Shared configuration for the tool tests.

The tests import the tools as ``tools.<name>`` from the repository root, two
levels above this folder. ``AGENT_NOTIFY=off`` is the stop notifier's kill
switch (``tools/agent_notify.py``): every in-process ``stop_gate.main()`` call
and every subprocess that inherits the test environment then sends no email
and writes no notifier state. The notifier's own tests opt back in with
``monkeypatch.delenv`` and a temporary home. ``pytest_unconfigure`` restores
the parent's value.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_AGENT_NOTIFY_ENV = "AGENT_NOTIFY"
_saved_agent_notify: list[str | None] = []


def pytest_configure(config: pytest.Config) -> None:
    """Silence the stop notifier for the whole session."""
    _saved_agent_notify.append(os.environ.get(_AGENT_NOTIFY_ENV))
    os.environ[_AGENT_NOTIFY_ENV] = "off"


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore the parent's stop-notifier selection."""
    if not _saved_agent_notify:
        return
    previous = _saved_agent_notify.pop()
    if previous is None:
        os.environ.pop(_AGENT_NOTIFY_ENV, None)
    else:
        os.environ[_AGENT_NOTIFY_ENV] = previous
