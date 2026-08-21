"""A cartographer that CAN send. Deliberately broken; never imported by the app.

`tests/test_settle.py` points the no-send detector at this file and asserts it
fires. A guard nobody has ever seen fire is a guard nobody should trust -- Task
3 shipped two guards with the wrong breadth, and both were caught by exactly
this kind of fixture rather than by review.
"""

from __future__ import annotations

import smtplib
from typing import Any


class SendingCartographer:
    """Maps counterparties AND emails them. This is the failure being detected."""

    def map_and_notify(self, counterparties: list[str], body: str) -> Any:
        server = smtplib.SMTP("localhost")
        for who in counterparties:
            server.sendmail("unwind@example.com", who, body)
        return server.quit()
