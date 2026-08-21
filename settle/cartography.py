"""The counterparty cartographer: who was told what, and when.

READ-ONLY BY CONSTRUCTION. This module determines who holds a wrong belief that
this organisation put there. It does not tell them. That separation is not
fastidiousness:

    THE THING THAT DECIDES WHO TO CONTACT MUST NOT BE THE THING THAT CONTACTS
    THEM. A mapping bug then produces a wrong list a human reads and rejects,
    instead of a wrong email a customer receives.

So there is no send method here, no connector client, and no import that could
reach one. `tests/test_settle.py` walks this module's AST for any send-shaped
capability and fails if one appears -- with a vacuity fixture that has one, so
the check is known to fire.

Output is three columns, per counterparty:
    what they were told · when · what they must now be told
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from lib.config import Tier
from lib.schema import Conclusion
from lib.telemetry import agent_decision_span

CARTOGRAPHER_PRINCIPAL = "counterparty-cartographer@0.4.0"


@dataclass(frozen=True)
class Telling:
    """One thing one counterparty was told, and what replaces it."""

    counterparty: str
    told: str
    told_at: datetime
    must_now_be_told: str
    effect_ref: str
    connector: str


@dataclass
class CounterpartyMap:
    conclusion_id: str
    tellings: list[Telling] = field(default_factory=list)

    @property
    def counterparties(self) -> list[str]:
        """Distinct, ordered. One counterparty told twice is still one apology."""
        seen: dict[str, None] = {}
        for telling in self.tellings:
            seen.setdefault(telling.counterparty, None)
        return list(seen)

    def for_counterparty(self, name: str) -> list[Telling]:
        return [t for t in self.tellings if t.counterparty == name]


def counterparty_of(conclusion: Conclusion) -> str:
    """Who the other side of this COMMITMENT was.

    Derived from the commitment, not from the effect, and that is the whole
    correctness argument: one commitment was made to one counterparty, who may
    have been told about it through several channels. Deriving identity per
    effect instead would turn a customer who got both an email and an invoice
    into two customers, and the obligation would propose apologising to each of
    them separately.

    The corpus has no CRM, so the identity is derived deterministically from the
    commitment id. Where a real deployment has one, this function is the seam --
    and it is a lookup, not a guess.
    """
    return f"counterparty::{conclusion.conclusion_id}"


def map_counterparties(
    conclusion: Conclusion,
    *,
    old_summary: str,
    new_summary: str,
) -> CounterpartyMap:
    """Build the who-was-told-what map for one commitment.

    `old_summary` and `new_summary` are passed in rather than computed here: the
    cartographer's job is the mapping, and a module that also decided what the
    correction says would be two jobs with one failure mode.
    """
    with agent_decision_span(CARTOGRAPHER_PRINCIPAL, Tier.T0) as span:
        who = counterparty_of(conclusion)
        tellings = [
            Telling(
                counterparty=who,
                told=old_summary,
                told_at=effect.occurred_at,
                must_now_be_told=new_summary,
                effect_ref=effect.ref,
                connector=effect.connector,
            )
            for effect in conclusion.external_effects
        ]
        result = CounterpartyMap(conclusion_id=conclusion.conclusion_id, tellings=tellings)
        span.set_attribute("unwind.tellings", len(tellings))
        span.set_attribute("unwind.counterparties", len(result.counterparties))
        return result
