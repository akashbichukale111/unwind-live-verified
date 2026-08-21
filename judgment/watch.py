"""Watchers and the drift sentinel. Deterministic; no model call.

A WATCHER detects change. A SENTINEL detects SILENCE, and silence is the more
dangerous signal — a supplier who stops confirming lead times has not told you
anything, which is exactly why nobody notices. A premise that quietly stopped
being reaffirmed six months ago is still carrying every commitment built on it,
and nothing in the system has raised its hand.

WATCHERS ARE DORMANT
--------------------
One per live claim, and there are 1,146 of them in the demo corpus. They are
data, not processes: a dormant watcher costs a document, and waking one is an
event arriving on `claim.retracted`. This is where the agent count legitimately
becomes large, and it stays cheap precisely because none of them is running.

THE SENTINEL MAY DOWNGRADE CONFIDENCE. IT MAY NOT RETRACT.
----------------------------------------------------------
Silence is evidence that a premise is less certain than it was. It is NOT
evidence about what the value now is. A sentinel that could retract would be
inventing a new world state out of an absence of information, and the blast
radius would be real. So it lowers confidence — which feeds causal debt, and
raises the confidence floor that any future retraction of this claim must clear
— and stops there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from lib.config import Tier
from lib.schema import Claim, ClaimStatus
from lib.telemetry import tool_call_span

SENTINEL_ID = "drift-sentinel@0.3.0"

#: [ASSUMPTION] How long a premise may go unreaffirmed before silence counts.
#: Stated as data so it can be argued with per source kind later.
SILENCE_GRACE_DAYS = 120.0
SILENCE_SATURATION_DAYS = 540.0
#: The most confidence silence may remove. A premise never falls to zero on
#: silence alone -- absence of news is not news.
MAX_CONFIDENCE_DECAY = 0.35


class WatcherState(str, Enum):
    DORMANT = "dormant"
    WOKEN = "woken"
    #: The claim it watched is gone; the watcher is spent.
    RETIRED = "retired"


@dataclass
class Watcher:
    """One dormant watcher per live claim. Data, not a process."""

    claim_id: str
    canonical: str
    source_id: str
    #: The last time the source said anything about this claim at all.
    last_affirmed_at: datetime
    state: WatcherState = WatcherState.DORMANT
    woken_at: datetime | None = None
    woken_by: str | None = None

    def wake(self, at: datetime, by: str) -> Watcher:
        return Watcher(
            claim_id=self.claim_id,
            canonical=self.canonical,
            source_id=self.source_id,
            last_affirmed_at=self.last_affirmed_at,
            state=WatcherState.WOKEN,
            woken_at=at,
            woken_by=by,
        )


def arm_watchers(claims: list[Claim]) -> list[Watcher]:
    """One watcher per LIVE claim. Retracted claims need no watching."""
    with tool_call_span("arm_watchers", Tier.T0, claims=len(claims)) as span:
        watchers = [
            Watcher(
                claim_id=claim.claim_id,
                canonical=claim.canonical,
                source_id=claim.source_id,
                last_affirmed_at=claim.valid_from,
            )
            for claim in claims
            if claim.status is ClaimStatus.LIVE
        ]
        span.set_attribute("unwind.watchers_armed", len(watchers))
        return watchers


@dataclass
class DriftSignal:
    """Silence, quantified. Carries what it may do and what it may not."""

    claim_id: str
    canonical: str
    source_id: str
    days_silent: float
    confidence_before: float
    confidence_after: float
    reason: str
    #: Stated on every signal so the constraint travels with the data.
    may_retract: bool = False

    @property
    def decayed_by(self) -> float:
        return round(self.confidence_before - self.confidence_after, 4)


class SentinelOverreach(RuntimeError):
    """The sentinel was asked to retract. It cannot."""


def sentinel_sweep(
    claims: list[Claim], as_of: datetime, grace_days: float = SILENCE_GRACE_DAYS
) -> list[DriftSignal]:
    """Find premises nobody has reaffirmed, and downgrade their confidence.

    Returns signals; it does not mutate claims. The caller applies them, which
    keeps "what silence implies" separate from "what we did about it".
    """
    with tool_call_span("drift_sentinel", Tier.T1, claims=len(claims)) as span:
        signals: list[DriftSignal] = []
        for claim in sorted(claims, key=lambda c: c.claim_id):
            if claim.status is not ClaimStatus.LIVE:
                continue
            days_silent = (as_of - claim.valid_from).total_seconds() / 86400.0
            if days_silent <= grace_days:
                continue

            span_days = SILENCE_SATURATION_DAYS - grace_days
            severity = min(1.0, (days_silent - grace_days) / span_days)
            decay = MAX_CONFIDENCE_DECAY * severity
            after = round(max(0.05, claim.confidence - decay), 4)

            signals.append(
                DriftSignal(
                    claim_id=claim.claim_id,
                    canonical=claim.canonical,
                    source_id=claim.source_id,
                    days_silent=round(days_silent, 1),
                    confidence_before=claim.confidence,
                    confidence_after=after,
                    reason=(
                        f"{claim.source_id} has not reaffirmed {claim.canonical} in "
                        f"{days_silent:.0f} days. Confidence lowered "
                        f"{claim.confidence:.2f} → {after:.2f}. This says the premise "
                        "is less certain, NOT that its value has changed -- silence "
                        "is not a new fact and cannot retract anything."
                    ),
                )
            )
        span.set_attribute("unwind.drift_signals", len(signals))
        return signals


def apply_drift(claim: Claim, signal: DriftSignal) -> Claim:
    """Apply a confidence downgrade. Refuses anything that looks like a retraction."""
    if signal.may_retract:
        raise SentinelOverreach(
            f"A drift signal for {claim.claim_id} claimed retraction authority. "
            "The sentinel observes silence; it has no information about what the "
            "value now is, and acting on an absence would cascade a guess."
        )
    return claim.model_copy(update={"confidence": signal.confidence_after})


@dataclass
class SentinelReport:
    as_of: datetime
    signals: list[DriftSignal] = field(default_factory=list)
    watchers_armed: int = 0

    @property
    def quietest(self) -> DriftSignal | None:
        return max(self.signals, key=lambda s: s.days_silent, default=None)

    def to_json(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "watchers_armed": self.watchers_armed,
            "signals": len(self.signals),
            "total_confidence_removed": round(sum(s.decayed_by for s in self.signals), 4),
            "quietest_premise": (
                {
                    "claim_id": self.quietest.claim_id,
                    "canonical": self.quietest.canonical,
                    "days_silent": self.quietest.days_silent,
                    "confidence": [
                        self.quietest.confidence_before,
                        self.quietest.confidence_after,
                    ],
                }
                if self.quietest
                else None
            ),
            "note": "The sentinel may lower confidence. It may never retract.",
        }


def sweep(claims: list[Claim], as_of: datetime) -> SentinelReport:
    return SentinelReport(
        as_of=as_of,
        signals=sentinel_sweep(claims, as_of),
        watchers_armed=len(arm_watchers(claims)),
    )
