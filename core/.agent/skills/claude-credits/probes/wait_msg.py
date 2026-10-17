"""Block until a message lands in the inbox or the timeout passes. Prints only a status line.

The message itself is NOT printed here: the PostToolUse hook delivers it as additional
context when this command finishes. That keeps one delivery path for every message.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

inbox = Path(os.environ["PROBE_INBOX"])
limit = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
t0 = time.time()
while time.time() - t0 < limit:
    if any(inbox.glob("*.msg")):
        print(f"wait_msg: message_waiting after {time.time() - t0:.1f}s")
        raise SystemExit(0)
    time.sleep(1)
print(f"wait_msg: timeout after {limit:.0f}s, no message")
