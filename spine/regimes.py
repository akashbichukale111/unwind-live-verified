"""The four-regime router. THE CORE NOVELTY, AND IT IS A RULE.

                    NOT ESCAPED              ESCAPED
    IMMATERIAL      dies silently, logged    dies silently, logged
    MATERIAL        corrected in place    →  CORRECTION OBLIGATION

Exactly one cell is an alert. That is the entire product claim: a retraction
touching thousands of decisions produces a handful of things a human must
actually do, and the reduction is computed rather than asserted.

THIS FUNCTION MUST NOT BE ABLE TO HALLUCINATE. It is a total function over a
three-valued materiality and a two-valued escapement, it makes no model call,
and `tests/test_regimes.py` enumerates every cell of its input space. If the
regime split could be argued out of its answer by a well-phrased email, the
novelty would be a liability instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.config import Tier
from lib.schema import Regime
from lib.telemetry import policy_gate_span
from spine.materiality import MaterialityOutcome

ROUTER_NAME = "four_regime_router"

#: What each regime means operationally. Carried into the cascade record so an
#: operator reading a node months later does not have to remember the matrix.
REGIME_ACTION: dict[Regime, str] = {
    Regime.IMMATERIAL_CONTAINED: "dies silently, logged",
    Regime.IMMATERIAL_ESCAPED: "dies silently, logged",
    Regime.MATERIAL_CONTAINED: "corrected in place",
    Regime.MATERIAL_ESCAPED: "CORRECTION OBLIGATION",
    Regime.UNRESOLVED: "displayed as UNRESOLVED, never defaulted to safe",
    Regime.CLOSED_OUT: "already discharged before the premise moved; nothing to do",
}

#: The only cell that reaches a human or a counterparty.
ALERT_REGIMES: frozenset[Regime] = frozenset({Regime.MATERIAL_ESCAPED})


@dataclass(frozen=True)
class RegimeRouting:
    regime: Regime
    action: str
    reason_code: str
    reason: str

    @property
    def is_alert(self) -> bool:
        return self.regime in ALERT_REGIMES


def route_regime(
    materiality: MaterialityOutcome, escaped: bool, unresolved_reason: str | None = None
) -> RegimeRouting:
    """Map (materiality, escapement) onto exactly one regime. Total, pure, fixed.

    The two non-committal materiality outcomes both land in UNRESOLVED, but they
    are NOT the same thing and the reason code keeps them apart:
    `pending_judgment` means a later tier can still decide; `unresolved` means
    nothing in the system can. Collapsing them would hide the difference between
    work outstanding and a genuine gap.
    """
    with policy_gate_span(ROUTER_NAME, Tier.T1) as span:
        routing = _route(materiality, escaped, unresolved_reason)
        span.set_attribute("unwind.regime", routing.regime.value)
        span.set_attribute("unwind.is_alert", routing.is_alert)
        span.set_attribute("unwind.reason_code", routing.reason_code)
        return routing


def _route(
    materiality: MaterialityOutcome, escaped: bool, unresolved_reason: str | None
) -> RegimeRouting:
    if materiality is MaterialityOutcome.PENDING_JUDGMENT:
        return RegimeRouting(
            Regime.UNRESOLVED,
            REGIME_ACTION[Regime.UNRESOLVED],
            "pending_judgment",
            unresolved_reason
            or "Materiality needs a reading rather than a computation. Awaiting T2.",
        )

    if materiality is MaterialityOutcome.UNRESOLVED:
        return RegimeRouting(
            Regime.UNRESOLVED,
            REGIME_ACTION[Regime.UNRESOLVED],
            "unresolved",
            unresolved_reason or "Materiality could not be determined and was not assumed.",
        )

    if materiality is MaterialityOutcome.CLOSED_OUT:
        return RegimeRouting(
            Regime.CLOSED_OUT,
            REGIME_ACTION[Regime.CLOSED_OUT],
            "already_closed_out",
            unresolved_reason
            or "This commitment discharged before the premise moved. It was "
            "fulfilled under the old value and the new one does not reach back "
            "to it -- so it is not unharmed, it is out of scope.",
        )

    if materiality is MaterialityOutcome.MATERIAL:
        if escaped:
            return RegimeRouting(
                Regime.MATERIAL_ESCAPED,
                REGIME_ACTION[Regime.MATERIAL_ESCAPED],
                "material_and_escaped",
                "Materially harmed, and the effect already left the building. "
                "It cannot be corrected quietly; somebody outside must be told.",
            )
        return RegimeRouting(
            Regime.MATERIAL_CONTAINED,
            REGIME_ACTION[Regime.MATERIAL_CONTAINED],
            "material_but_contained",
            "Materially harmed, but nothing has left the building. Correct it in "
            "place; no counterparty is involved.",
        )

    if escaped:
        return RegimeRouting(
            Regime.IMMATERIAL_ESCAPED,
            REGIME_ACTION[Regime.IMMATERIAL_ESCAPED],
            "immaterial_though_escaped",
            "The effect escaped, but the commitment holds enough buffer to absorb "
            "the move. Nothing is owed. Dies silently, logged.",
        )
    return RegimeRouting(
        Regime.IMMATERIAL_CONTAINED,
        REGIME_ACTION[Regime.IMMATERIAL_CONTAINED],
        "immaterial_and_contained",
        "Buffer absorbs the move and nothing left the building. Dies silently, logged.",
    )
