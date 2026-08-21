"""HYPERION -- the immune layer over Card 2's Gateway.

Not a second authority path: `hyperion/guard.py:evaluate_with_hyperion` calls
`tower.gateway.evaluate_gateway` UNCHANGED and adds a deterministic risk score
plus a durable, append-only log on top of the SAME decision every other
caller already gets. See `hyperion/DESIGN.md` for the full invariant, threat
model, and an honest accounting of what is built versus what is architecture
only.
"""

from __future__ import annotations
