"""The four-regime router, tested exhaustively.

The router is a total function over (MaterialityOutcome × bool). Its input space
is finite and small, so "exhaustively" means literally every cell -- there is no
excuse for sampling. This is the core novelty of the product; if it can be wrong
in one cell, the claim that it cannot hallucinate is worthless.
"""

from __future__ import annotations

import itertools

import pytest

from lib.schema import Regime
from spine.materiality import MaterialityOutcome
from spine.regimes import ALERT_REGIMES, REGIME_ACTION, route_regime

#: The complete input space. 4 outcomes x 2 escapement values = 8 cells.
ALL_INPUTS = list(itertools.product(list(MaterialityOutcome), [False, True]))

EXPECTED: dict[tuple[MaterialityOutcome, bool], Regime] = {
    # CLOSED-OUT is its own cell, in both escapement states. It is NOT a variant
    # of immaterial: immaterial means the buffer absorbed the shock, closed-out
    # means the shock never applied. An operator asking "why is this not on my
    # list" deserves the real answer, and they are different answers.
    (MaterialityOutcome.CLOSED_OUT, False): Regime.CLOSED_OUT,
    (MaterialityOutcome.CLOSED_OUT, True): Regime.CLOSED_OUT,
    (MaterialityOutcome.IMMATERIAL, False): Regime.IMMATERIAL_CONTAINED,
    (MaterialityOutcome.IMMATERIAL, True): Regime.IMMATERIAL_ESCAPED,
    (MaterialityOutcome.MATERIAL, False): Regime.MATERIAL_CONTAINED,
    (MaterialityOutcome.MATERIAL, True): Regime.MATERIAL_ESCAPED,
    # Both non-committal outcomes land in UNRESOLVED regardless of escapement.
    (MaterialityOutcome.PENDING_JUDGMENT, False): Regime.UNRESOLVED,
    (MaterialityOutcome.PENDING_JUDGMENT, True): Regime.UNRESOLVED,
    (MaterialityOutcome.UNRESOLVED, False): Regime.UNRESOLVED,
    (MaterialityOutcome.UNRESOLVED, True): Regime.UNRESOLVED,
}


def test_the_input_space_is_fully_enumerated() -> None:
    assert len(ALL_INPUTS) == 10  # 5 materiality outcomes x 2 escapement values
    assert set(ALL_INPUTS) == set(EXPECTED)


@pytest.mark.parametrize(("outcome", "escaped"), ALL_INPUTS)
def test_every_cell_routes_to_exactly_the_expected_regime(
    outcome: MaterialityOutcome, escaped: bool
) -> None:
    routing = route_regime(outcome, escaped)
    assert routing.regime is EXPECTED[(outcome, escaped)]
    assert routing.action == REGIME_ACTION[routing.regime]
    assert routing.reason, "every routing must carry a stated reason"
    assert routing.reason_code


def test_exactly_one_cell_is_an_alert() -> None:
    """The product claim, as a test: only material-and-escaped reaches anyone."""
    alerts = {
        (outcome, escaped)
        for outcome, escaped in ALL_INPUTS
        if route_regime(outcome, escaped).is_alert
    }
    assert alerts == {(MaterialityOutcome.MATERIAL, True)}
    assert ALERT_REGIMES == frozenset({Regime.MATERIAL_ESCAPED})


def test_pending_judgment_and_unresolved_stay_distinguishable() -> None:
    """Both are UNRESOLVED, but they mean different things and must stay apart.

    `pending_judgment` is work outstanding -- a later tier can still decide.
    `unresolved` is a genuine gap nothing in the system can close. Collapsing
    them would hide the difference between a backlog and a blind spot.
    """
    pending = route_regime(MaterialityOutcome.PENDING_JUDGMENT, True)
    unresolved = route_regime(MaterialityOutcome.UNRESOLVED, True)
    assert pending.regime is unresolved.regime is Regime.UNRESOLVED
    assert pending.reason_code == "pending_judgment"
    assert unresolved.reason_code == "unresolved"
    assert pending.reason_code != unresolved.reason_code


def test_router_is_pure_and_repeatable() -> None:
    """Same inputs, same answer. Every time, with no hidden state."""
    for outcome, escaped in ALL_INPUTS:
        first = route_regime(outcome, escaped)
        for _ in range(5):
            again = route_regime(outcome, escaped)
            assert again.regime is first.regime
            assert again.reason_code == first.reason_code


def test_closed_out_is_never_collapsed_into_immaterial() -> None:
    """Ruling 1.2: CLOSED-OUT is a named concept with its own reason code."""
    for escaped in (False, True):
        routing = route_regime(MaterialityOutcome.CLOSED_OUT, escaped)
        assert routing.regime is Regime.CLOSED_OUT
        assert routing.reason_code == "already_closed_out"
        assert not routing.is_alert
        assert "out of scope" in routing.reason


def test_unresolved_is_never_silently_treated_as_immaterial() -> None:
    """The failure mode 1.6 exists to prevent: defaulting an unknown to safe."""
    for outcome in (MaterialityOutcome.UNRESOLVED, MaterialityOutcome.PENDING_JUDGMENT):
        for escaped in (False, True):
            regime = route_regime(outcome, escaped).regime
            assert regime not in {
                Regime.IMMATERIAL_CONTAINED,
                Regime.IMMATERIAL_ESCAPED,
            }
