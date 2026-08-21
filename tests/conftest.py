"""Test-session defaults.

Console span export is off during tests. It is not noise-reduction for its own
sake: the exporter writes to stdout from a background thread, and pytest closes
the captured stream at teardown, which surfaces as an unrelated `ValueError:
I/O operation on closed file` that would sit in the output looking like a bug.
"""

from __future__ import annotations

import os

os.environ.setdefault("UNWIND_OTEL_CONSOLE", "0")
