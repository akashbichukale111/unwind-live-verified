"""Mission Media Lab: one mission state, three Google AI modalities.

PRESENTATION LAYER ONLY. Nothing in this package writes to Firestore, the
warrant ledger, the registry or decision memory, and nothing in `tower/`,
`warrant/` or `hyperion/` imports it -- `tests/test_media.py` proves both
directions by import-graph walk. Delete this package and every authority
test still passes; that is what makes it a presentation layer rather than a
second source of truth.

See `media/grounding.py` for the shared brief all three modalities read, and
`media/adapters.py` for the three adapters and their fail-closed contract.
"""

from media.adapters import (
    MediaResult,
    MediaStatus,
    generate_replay,
    generate_signal,
    media_status,
    synthesize_mission,
)
from media.grounding import MissionBrief, build_brief, load_brief

__all__ = [
    "MediaResult",
    "MediaStatus",
    "MissionBrief",
    "build_brief",
    "generate_replay",
    "generate_signal",
    "load_brief",
    "media_status",
    "synthesize_mission",
]
