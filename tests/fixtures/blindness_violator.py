"""A DELIBERATELY BROKEN re-deriver. Never imported by product code.

This exists so the blindness guard can be pointed at something that violates it.
A guard that has only ever seen compliant code is a guard nobody has tested, and
Task 2 shipped exactly such a guard -- it matched module names by exact string
and would have missed `google.genai.types` entirely. Its own vacuity test caught
it. That pattern is now policy.

`tests/test_blindness.py` asserts the guard FAILS on this file. If it ever
passes, the guard is broken, not this fixture.
"""

from __future__ import annotations

from typing import Any


def anchored_rederive(store: Any, conclusion_id: str, premises: dict[str, Any]) -> float | None:
    """The failure mode, written out plainly.

    It reads the original conclusion and echoes back what was already committed.
    Materiality scoring then compares the answer to itself, finds no change, and
    reports that nothing was harmed -- silently, and every time.
    """
    conclusion = store.get_conclusion(conclusion_id)
    if conclusion is None:
        return None
    return conclusion.committed_lead_days
