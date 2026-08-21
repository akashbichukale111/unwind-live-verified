"""Control Tower (Card 2) -- supporting infrastructure for the write path.

Registry, identity, gateway, decision memory, durable runtime, observability.
This package provides the STORAGE AND ENFORCEMENT POINTS for Card 0
(WARRANT); it does not mint, burn, or decay a single unit of warrant itself --
`tower/schema.py:WarrantSlot` is a labelled, empty stub that a later prompt
fills in.

Nothing in this package is imported by `spine/`, `court/`, `judgment/` or
`settle/`, and `tests/test_tower_zero_model.py` walks its import graph the
same way `tests/test_zero_model.py` walks `spine/`'s: the tower's
deterministic authority path (registry lookups, the four gateway checks) must
never be able to reach a model client either.
"""

from __future__ import annotations
