"""Metric definitions for UNWIND.

Defined before any scenario exists, deliberately. A metric invented after seeing
results is a metric chosen to flatter them.

Each metric declares which tier produces the behaviour it measures, so a
regression can be attributed to the deterministic spine or to the model rather
than to "the system".

FALSE_RETRACTION_RATE is the one that matters. Everything else describes how
good UNWIND is; that one describes how dangerous it is. A missed retraction
leaves a wrong decision operating, which is the status quo. A false retraction
un-sends a correct commitment to a real counterparty, which is worse than the
disease.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


@dataclass(frozen=True)
class MetricDef:
    key: str
    name: str
    direction: Direction
    tier: str
    unit: str
    definition: str
    #: Why this metric is worth its place. A metric without one gets deleted.
    why: str
    #: No target is asserted as achieved anywhere. Targets are goals, not results.
    target: str | None = None


METRICS: tuple[MetricDef, ...] = (
    MetricDef(
        key="blast_radius_recall",
        name="Blast-radius recall",
        direction=Direction.HIGHER_IS_BETTER,
        tier="T0",
        unit="ratio",
        definition=(
            "|found ∩ true| / |true|, where `true` is the transitive dependent set "
            "of the retracted claim in radius_truth.jsonl."
        ),
        why=(
            "A dependent that is never found is a decision that stays wrong and "
            "operating. This is the failure the whole product exists to prevent."
        ),
        target="1.0 — traversal is deterministic, so anything below 1.0 is a bug, not noise",
    ),
    MetricDef(
        key="blast_radius_precision",
        name="Blast-radius precision",
        direction=Direction.HIGHER_IS_BETTER,
        tier="T0",
        unit="ratio",
        definition="|found ∩ true| / |found|.",
        why=(
            "A radius that over-reaches drags unrelated commitments into a repair "
            "that should never have touched them."
        ),
        target="1.0 — same reason as recall",
    ),
    MetricDef(
        key="materiality_accuracy",
        name="Materiality accuracy",
        direction=Direction.HIGHER_IS_BETTER,
        tier="T1/T2",
        unit="ratio",
        definition=(
            "Agreement with ground-truth materiality over the radius, excluding "
            "conclusions correctly marked UNRESOLVED."
        ),
        why=(
            "Materiality is what turns a 2,000-node radius into a handful of things "
            "a human must look at. Getting it wrong in either direction destroys the "
            "value: too loose and nobody reads the output, too tight and the "
            "expensive ones slip through."
        ),
    ),
    MetricDef(
        key="false_retraction_rate",
        name="False-retraction rate",
        direction=Direction.LOWER_IS_BETTER,
        tier="T0/T1/T2",
        unit="ratio",
        definition=(
            "Fraction of unwind actions taken against conclusions that were NOT "
            "materially affected, plus any action taken on a retraction whose source "
            "lacked authority over the claim."
        ),
        why=(
            "THE METRIC THAT MATTERS. A false retraction reaches a counterparty and "
            "un-says something true. It is worse than a missed one, and the input "
            "surface is attacker-controlled text, so it is also the attack."
        ),
        target="0.0 — treated as a correctness property, not a rate to optimise",
    ),
    MetricDef(
        key="escapement_accuracy",
        name="Escapement accuracy",
        direction=Direction.HIGHER_IS_BETTER,
        tier="T0",
        unit="ratio",
        definition=(
            "Agreement on whether a conclusion produced an external effect before the retraction."
        ),
        why=(
            "Escapement decides which of the four regimes a conclusion lands in, and "
            "only one of those cells is an alert. Get it wrong and a correction "
            "obligation is either invented or skipped."
        ),
    ),
    MetricDef(
        key="human_escalation_precision",
        name="Human-escalation precision",
        direction=Direction.HIGHER_IS_BETTER,
        tier="T2",
        unit="ratio",
        definition=(
            "Of the conclusions routed to ASK_HUMAN, the fraction that genuinely "
            "required a human signature."
        ),
        why=(
            "Human attention is the scarcest resource in the loop. An escalation "
            "queue that is mostly noise gets ignored, and then the real one is "
            "ignored with it."
        ),
    ),
    MetricDef(
        key="unresolved_rate",
        name="Unresolved rate",
        direction=Direction.LOWER_IS_BETTER,
        tier="T1/T2",
        unit="ratio",
        definition="Fraction of the radius the system could not determine.",
        why=(
            "Tracked but NOT minimised at any cost. Driving this to zero by guessing "
            "is the failure mode; an honest UNRESOLVED is a correct output. Read it "
            "alongside false-retraction rate, never alone."
        ),
    ),
    MetricDef(
        key="cost_per_cascade",
        name="Cost per cascade",
        direction=Direction.LOWER_IS_BETTER,
        tier="T2",
        unit="usd",
        definition=(
            "Model spend for one full cascade, from claim retraction to the last "
            "regime assignment. T0/T1 contribute zero by construction."
        ),
        why=(
            "The tiering claim is only real if it shows up in the bill. If cost "
            "scales with radius size rather than with the material minority, the "
            "deterministic spine is not doing its job."
        ),
    ),
    MetricDef(
        key="time_to_obligation",
        name="Time to obligation",
        direction=Direction.LOWER_IS_BETTER,
        tier="T0/T1/T2",
        unit="seconds",
        definition=(
            "Wall-clock from `claim.retracted` publication to the first "
            "`obligation.raised` for that claim."
        ),
        why=(
            "The window between a premise dying and a counterparty being told is the "
            "period in which the damage compounds. It is the number an operator "
            "actually feels."
        ),
    ),
)

METRICS_BY_KEY: dict[str, MetricDef] = {m.key: m for m in METRICS}


@dataclass
class MetricResult:
    key: str
    value: float | None
    #: Populated when the metric could not be computed. Never silently zero.
    unavailable_reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        definition = METRICS_BY_KEY[self.key]
        return {
            "key": self.key,
            "name": definition.name,
            "tier": definition.tier,
            "unit": definition.unit,
            "direction": definition.direction.value,
            "value": self.value,
            "unavailable_reason": self.unavailable_reason,
            "detail": self.detail,
        }


def unavailable(keys: Sequence[str], reason: str) -> list[MetricResult]:
    """Mark metrics as not computed. Used until the scenarios exist."""
    return [MetricResult(key=k, value=None, unavailable_reason=reason) for k in keys]
