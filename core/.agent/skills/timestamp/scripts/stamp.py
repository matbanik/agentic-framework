"""Emit a completion timestamp in the project's canonical format.

Usage:
    python .agent/skills/timestamp/scripts/stamp.py

Output:
    🕐 Completed: 2026-04-30 20:42 (EDT)
"""

import sys
import io
from datetime import datetime

# Force UTF-8 stdout on Windows (cp1252 can't encode emoji)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

now = datetime.now().astimezone()
tz_name = now.strftime("%Z")  # "Eastern Daylight Time" on Windows, "EDT" on Unix

# Windows gives long timezone names — abbreviate by taking capital letters
if len(tz_name) > 5:
    tz_name = "".join(c for c in tz_name if c.isupper())

print(f"\U0001f550 Completed: {now:%Y-%m-%d %H:%M} ({tz_name})")
