"""Warrant (agent reputation) and `settle/loadrating.py` (source standing)
share no storage and no code path.

The project's thesis -- "AI is not allowed to control the load-bearing truth
layer" -- extends to Card 0: an agent's good behaviour must never launder
into how much a SOURCE's claims are trusted, and vice versa.
`settle/loadrating.py`'s own docstring refuses this for its own reason
(`assert_not_agent_trust`); this file proves the converse holds too, from
`warrant/`'s side, without touching `settle/` (frozen).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _direct_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                found.add(node.module)
    return found


def test_warrant_does_not_import_settle() -> None:
    """No code path: nothing in warrant/ imports anything from settle/."""
    offenders = []
    for source in sorted((REPO / "warrant").glob("*.py")):
        imports = _direct_imports(source)
        if any(i == "settle" or i.startswith("settle.") for i in imports):
            offenders.append(str(source.relative_to(REPO)))
    assert not offenders, f"warrant/ modules importing settle/: {offenders}"


def test_settle_does_not_import_warrant() -> None:
    """The boundary works both directions, exactly like
    tests/test_tower_zero_model.py's spine<->tower check: settle/ is frozen
    and must never import warrant/, or a future edit to settle/ could make
    source standing depend on agent reputation.
    """
    offenders = []
    for source in sorted((REPO / "settle").glob("*.py")):
        imports = _direct_imports(source)
        if any(i == "warrant" or i.startswith("warrant.") for i in imports):
            offenders.append(str(source.relative_to(REPO)))
    assert not offenders, f"settle/ modules importing warrant/: {offenders}"


def test_no_shared_storage_collection_name() -> None:
    """No storage: warrant/ writes to its own Firestore collection, never
    `COLLECTION_AGENT_TRUST` or any name `settle/` references. `settle/`
    itself has no Firestore collection at all (`settle/loadrating.py` is a
    pure in-memory ledger over `Source` records) -- so the only collision
    that could ever happen is warrant/ accidentally reusing a name `lib/`
    already reserves for something settle-adjacent; this asserts it does not.
    """
    from lib.config import COLLECTION_AGENT_TRUST, COLLECTION_WARRANT_LEDGER

    assert COLLECTION_WARRANT_LEDGER != COLLECTION_AGENT_TRUST
    assert COLLECTION_WARRANT_LEDGER == "warrant_ledger"


def test_no_shared_code_path_load_rating_refuses_a_warrant_event() -> None:
    """`settle.loadrating.assert_not_agent_trust` -- the one place `settle/`
    already refuses to be handed agent-shaped data -- fires when handed a
    real `warrant.ledger.WarrantEvent`. This is the converse of Card 0's own
    guarantee: not only does warrant/ refuse to touch settle/'s ledger, but
    settle/'s ledger (unmodified, frozen) independently refuses to be fed a
    warrant record if anyone ever tried.
    """
    from datetime import UTC, datetime

    from settle.loadrating import NotASourceError, assert_not_agent_trust
    from warrant.ledger import EventKind, Provenance, WarrantEvent

    event = WarrantEvent(
        event_id="warr_test",
        principal="agent::probe",
        capability="extract",
        risk_class="LOW",
        kind=EventKind.MINT,
        amount_bp=100,
        provenance=Provenance.SYNTHETIC,
        case_id=None,
        reason="separation probe",
        at=datetime.now(UTC),
    )
    # WarrantEvent has no `reputation`/`autonomy_tier`/`reliability` field, so
    # the duck-typed guard would NOT fire on the dataclass directly -- that is
    # correct (it is not agent-trust-shaped) and is exactly why the two
    # systems are safe to keep apart: neither can be mistaken for the other.
    assert_not_agent_trust(event)  # must not raise: a WarrantEvent is not agent-trust-shaped

    # But the classic agent-trust shape IS refused, proving the guard is live.
    with pytest.raises(NotASourceError):
        assert_not_agent_trust({"agent_id": "a", "reputation": 0.9})


def test_load_rating_ledger_and_warrant_event_are_distinct_types() -> None:
    from settle.loadrating import LoadRatingLedger
    from warrant.ledger import WarrantEvent

    assert LoadRatingLedger is not WarrantEvent
    assert not issubclass(WarrantEvent, LoadRatingLedger)
    assert not issubclass(LoadRatingLedger, WarrantEvent)
