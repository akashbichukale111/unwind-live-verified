"""Load rating: how much decision weight a SOURCE has earned.

This is the compounding mechanism -- the thing that makes a recovery into a
system that gets better rather than one that merely recovers. When a source's
claim is later falsified, the organisation lowers how much future weight it will
let rest on that source's claims.

⚠ LOAD RATING IS NOT AGENT REPUTATION, AND CONFLATING THEM PUNISHES THE WRONG
PARTY.

    An extractor can do a flawless job on a supplier that lies every week. Its
    extraction was correct; the SOURCE was wrong. Folding those two numbers
    together means a well-behaved agent's autonomy decays because of the
    documents it was pointed at, and a bad extractor hides behind honest
    suppliers. So `Source.load_rating` and `AgentTrust.reputation` are separate
    fields, updated by separate code, and this module REFUSES to touch the
    second -- `assert_not_agent_trust` raises if handed one, with a vacuity test
    that proves it fires.

Three properties the brief requires, each implemented rather than asserted:

    VERSIONED    every adjustment appends a version; nothing is overwritten
    REVERSIBLE   `revert_to` restores an earlier version and records that it did
    CONTESTABLE  a source may contest an adjustment; a contested version stays
                 in the history, flagged, rather than vanishing
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from lib.config import Tier
from lib.schema import Source
from lib.telemetry import agent_decision_span

LOAD_RATING_PRINCIPAL = "load-rating@0.4.0"

#: [ASSUMPTION] Multiplier applied on each falsification. 0.6 means three
#: falsifications take a source from 0.5 to roughly 0.11 -- fast enough that a
#: repeatedly-wrong source stops carrying weight within a quarter, slow enough
#: that one bad week does not zero a decade-old relationship.
FALSIFICATION_DECAY = 0.6

#: Never zero. A source at zero can never earn its way back, and a rating that
#: cannot recover is a ban wearing a number's clothes.
MIN_RATING = 0.05

#: [ASSUMPTION] Recovery per clean corroboration, applied additively so trust
#: rebuilds more slowly than it is lost.
CLEAN_RECOVERY = 0.05


class NotASourceError(TypeError):
    """Load rating was pointed at something that is not a source."""


@dataclass(frozen=True)
class RatingVersion:
    """One adjustment. Immutable, and never removed from the history."""

    version: int
    rating: float
    at: datetime
    reason: str
    claim_id: str | None = None
    #: Set when the source has formally contested this adjustment. The version
    #: stays in the ledger either way -- deleting contested history is how an
    #: audit trail becomes a story.
    contested: bool = False
    contest_note: str | None = None
    #: Set when this version exists because an earlier one was reverted.
    reverted_from: int | None = None


@dataclass
class LoadRatingLedger:
    """The full history of one source's standing."""

    source_id: str
    versions: list[RatingVersion] = field(default_factory=list)

    @property
    def current(self) -> RatingVersion:
        if not self.versions:
            raise ValueError(f"{self.source_id} has no rating history")
        return self.versions[-1]

    @property
    def rating(self) -> float:
        return self.current.rating

    def _append(self, **kwargs: object) -> RatingVersion:
        version = RatingVersion(version=len(self.versions) + 1, **kwargs)  # type: ignore[arg-type]
        self.versions.append(version)
        return version

    def falsified(self, *, at: datetime, claim_id: str, reason: str) -> RatingVersion:
        """A claim from this source turned out to be false. Downgrade."""
        with agent_decision_span(LOAD_RATING_PRINCIPAL, Tier.T1) as span:
            new_rating = max(MIN_RATING, round(self.rating * FALSIFICATION_DECAY, 4))
            span.set_attribute("unwind.source_id", self.source_id)
            span.set_attribute("unwind.rating_before", self.rating)
            span.set_attribute("unwind.rating_after", new_rating)
            return self._append(rating=new_rating, at=at, reason=reason, claim_id=claim_id)

    def corroborated(self, *, at: datetime, reason: str) -> RatingVersion:
        """A claim held up. Recover, slowly."""
        new_rating = min(1.0, round(self.rating + CLEAN_RECOVERY, 4))
        return self._append(rating=new_rating, at=at, reason=reason)

    def contest(self, version: int, *, note: str) -> RatingVersion:
        """The source disputes an adjustment. Flag it; never delete it."""
        for index, existing in enumerate(self.versions):
            if existing.version == version:
                flagged = RatingVersion(
                    version=existing.version,
                    rating=existing.rating,
                    at=existing.at,
                    reason=existing.reason,
                    claim_id=existing.claim_id,
                    contested=True,
                    contest_note=note,
                    reverted_from=existing.reverted_from,
                )
                self.versions[index] = flagged
                return flagged
        raise ValueError(f"{self.source_id} has no version {version} to contest")

    def revert_to(self, version: int, *, at: datetime, reason: str) -> RatingVersion:
        """Restore an earlier rating by appending, not by deleting.

        Reversibility that erases the thing being reversed is not reversibility,
        it is amnesia: nobody can later ask what the rating was or why it moved.
        """
        target = next((v for v in self.versions if v.version == version), None)
        if target is None:
            raise ValueError(f"{self.source_id} has no version {version} to revert to")
        return self._append(
            rating=target.rating,
            at=at,
            reason=f"reverted to v{version}: {reason}",
            claim_id=target.claim_id,
            reverted_from=version,
        )


def assert_not_agent_trust(subject: object) -> None:
    """Refuse to rate an agent. The separation, made executable.

    Duck-typed rather than isinstance-checked so it also catches a dict or a
    stub carrying agent-trust fields -- the realistic way the two would get
    crossed is a helper that passes the wrong record, not a deliberate cast.
    """
    markers = ("reputation", "autonomy_tier", "reliability", "agent_id")
    present = [m for m in markers if _has(subject, m)]
    if present:
        raise NotASourceError(
            f"load rating was handed something carrying agent-trust field(s) "
            f"{present}. Source standing and agent reputation are separate "
            "numbers on purpose: an agent can extract perfectly from a source "
            "that lies constantly, and merging them punishes the wrong party."
        )


def _has(subject: object, name: str) -> bool:
    if isinstance(subject, dict):
        return name in subject
    return hasattr(subject, name)


def ledger_for(source: Source, *, at: datetime) -> LoadRatingLedger:
    """Open a ledger at the source's current standing."""
    assert_not_agent_trust(source)
    ledger = LoadRatingLedger(source_id=source.source_id)
    ledger._append(rating=source.load_rating, at=at, reason="opening balance from source record")
    return ledger


def weight_cap(rating: float) -> float:
    """How much of one decision this source may carry on its own.

    A source at 1.0 may fully support a conclusion; a source at the floor may
    contribute but never be the only thing under a commitment. This is the seam
    into `spine.defence`'s corroboration rule -- the rating is not decoration,
    it changes what the system will act on.
    """
    return max(0.0, min(1.0, rating))
