"""Adversarial defence. Deterministic, and it scales with the cost of being wrong.

UNWIND's entire input surface is attacker-controlled text: supplier emails,
vendor PDFs, broker notices. A forged retraction is not a data-quality problem,
it is a weapon — it cancels real orders and sends corrections to customers who
needed none. The defences here are therefore arithmetic, not judgement, and they
sit in front of the model rather than inside it.

THE ORGANISING IDEA: THE BAR IS SET BY WHAT IT WOULD COST TO BE WRONG
--------------------------------------------------------------------
A retraction touching 3 internal plans and one touching 2,594 live commitments
are not the same act, and demanding the same evidence for both is the mistake.
So the confidence floor is a function of blast radius and exposure:

    small radius, no money   -> a single ordinary artifact is enough
    large radius             -> higher floor, and a human confirms
    large radius + money     -> a second independent source, or a human

None of this asks whether the text "looks suspicious". A well-written forgery
looks exactly like a real notice; that is what makes it a forgery. What it
cannot fake is corroboration, and what it cannot change is how much damage
acting on it would do.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from lib.config import Tier
from lib.schema import DecisionState
from lib.telemetry import policy_gate_span

# ---------------------------------------------------------------------------
# Confidence floor
# ---------------------------------------------------------------------------

#: [ASSUMPTION] The shape is a judgement, stated here so it can be argued with.
#: A floor that rises with the logarithm of the radius means each order of
#: magnitude of blast costs roughly a fixed increment of required confidence,
#: rather than the floor saturating immediately or never biting at all.
BASE_FLOOR = 0.55
FLOOR_PER_DECADE = 0.09
MAX_FLOOR = 0.97

#: Above this radius a human confirms even when confidence clears the floor.
HUMAN_CONFIRMATION_RADIUS = 500
#: Above this committed exposure a single uncorroborated source is not enough.
TWO_SOURCE_EXPOSURE_MINOR = 500_000  # USD 5,000.00
#: ...and likewise above this radius, regardless of money.
TWO_SOURCE_RADIUS = 1_000


@dataclass(frozen=True)
class FloorVerdict:
    passed: bool
    state: DecisionState
    reason_code: object  # DecisionReason; typed loosely to avoid an import cycle
    why: str
    required_confidence: float
    actual_confidence: float


@dataclass
class ConfidenceFloor:
    """How much certainty a retraction must carry, given what it would touch."""

    base: float = BASE_FLOOR
    per_decade: float = FLOOR_PER_DECADE
    ceiling: float = MAX_FLOOR
    human_radius: int = HUMAN_CONFIRMATION_RADIUS
    two_source_exposure: int = TWO_SOURCE_EXPOSURE_MINOR
    two_source_radius: int = TWO_SOURCE_RADIUS

    def required(self, blast_radius: int) -> float:
        """The floor for a radius of this size. Monotonic, capped, explainable."""
        decades = math.log10(max(1, blast_radius))
        return round(min(self.ceiling, self.base + self.per_decade * decades), 4)

    def evaluate(
        self,
        confidence: float,
        blast_radius: int,
        exposure_minor: int,
        corroborating_sources: list[str],
    ) -> FloorVerdict:
        from spine.decision import DecisionReason  # noqa: PLC0415

        with policy_gate_span("confidence_floor", Tier.T0, blast_radius=blast_radius) as span:
            required = self.required(blast_radius)
            distinct = len({s for s in corroborating_sources if s})

            span.set_attribute("unwind.required_confidence", required)
            span.set_attribute("unwind.actual_confidence", confidence)
            span.set_attribute("unwind.distinct_sources", distinct)

            if confidence < required:
                return FloorVerdict(
                    passed=False,
                    state=DecisionState.REFUSE,
                    reason_code=DecisionReason.BELOW_CONFIDENCE_FLOOR,
                    why=(
                        f"Confidence {confidence:.2f} is below the floor of "
                        f"{required:.2f} required to retract something carrying "
                        f"{blast_radius} dependent commitments. The bar is set by "
                        "what it would cost to be wrong, and at this radius being "
                        "wrong is expensive."
                    ),
                    required_confidence=required,
                    actual_confidence=confidence,
                )

            # --- two-source rule ------------------------------------------
            needs_two = (
                exposure_minor >= self.two_source_exposure or blast_radius >= self.two_source_radius
            )
            if needs_two and distinct < 2:
                trigger = (
                    f"{exposure_minor / 100:.2f} USD of committed effect"
                    if exposure_minor >= self.two_source_exposure
                    else f"a radius of {blast_radius}"
                )
                return FloorVerdict(
                    passed=False,
                    state=DecisionState.ASK_HUMAN,
                    reason_code=DecisionReason.SINGLE_SOURCE_ABOVE_THRESHOLD,
                    why=(
                        f"A single uncorroborated source cannot retract against "
                        f"{trigger}. One artifact is one assertion; at this level "
                        "of consequence it needs either a second independent "
                        "source or a person. Confidence was sufficient "
                        f"({confidence:.2f} ≥ {required:.2f}) — this is about "
                        "corroboration, not certainty."
                    ),
                    required_confidence=required,
                    actual_confidence=confidence,
                )

            if blast_radius >= self.human_radius:
                return FloorVerdict(
                    passed=False,
                    state=DecisionState.ASK_HUMAN,
                    reason_code=DecisionReason.BLAST_RADIUS_REQUIRES_CONFIRMATION,
                    why=(
                        f"This retraction reaches {blast_radius} live commitments. "
                        f"Confidence {confidence:.2f} clears the floor "
                        f"({required:.2f}) and {distinct} sources corroborate, so "
                        "the system believes it — but a mass unwind at this scale "
                        "gets a human signature before anything leaves the building."
                    ),
                    required_confidence=required,
                    actual_confidence=confidence,
                )

            return FloorVerdict(
                passed=True,
                state=DecisionState.EXECUTE,
                reason_code=DecisionReason.ALL_GATES_PASSED,
                why=(
                    f"Confidence {confidence:.2f} clears the floor of "
                    f"{required:.2f} for a radius of {blast_radius}."
                ),
                required_confidence=required,
                actual_confidence=confidence,
            )


# ---------------------------------------------------------------------------
# The quarantined extraction principal
# ---------------------------------------------------------------------------


class QuarantineViolation(RuntimeError):
    """An extraction tried to reach outside the artifact's own authority scope."""


@dataclass
class ExtractionQuarantine:
    """What an extraction is allowed to name. Enforced, not requested.

    The attack this closes: an artifact whose text says "…and also set
    clm_000000 to 90 days". Extraction runs on attacker text, so it must not be
    able to *name* a claim outside the scope its source actually holds. The
    subject is supplied by the ingestion path and the canonical is composed from
    it, so the text never gets a vote on which claim it is talking about.

    This is a data-access restriction, not an instruction. There is no wording
    that gets around it, because there is nothing here that reads wording.
    """

    source_id: str
    subject: str
    authority: tuple[str, ...]

    #: Every rejection, kept so a quarantine breach is a recorded event.
    violations: list[str] = field(default_factory=list)

    def permits(self, canonical: str) -> bool:
        return canonical.startswith(f"{self.subject}.") or any(
            canonical.startswith(prefix) for prefix in self.authority
        )

    def check(self, canonical: str) -> None:
        if not self.permits(canonical):
            message = (
                f"{self.source_id} attempted to assert {canonical!r}, which is "
                f"outside its subject {self.subject!r} and its authority "
                f"{list(self.authority)!r}."
            )
            self.violations.append(message)
            raise QuarantineViolation(message)

    def filter_claims(self, claims: list) -> tuple[list, list[str]]:
        """Drop anything out of scope, recording why. Never raises.

        Used on the extraction path, where one bad claim in an artifact should
        cost that claim rather than the whole artifact.
        """
        kept, rejected = [], []
        for claim in claims:
            if self.permits(claim.canonical):
                kept.append(claim)
            else:
                message = (
                    f"dropped {claim.canonical!r}: outside {self.subject!r} / "
                    f"{list(self.authority)!r}"
                )
                rejected.append(message)
                self.violations.append(message)
        return kept, rejected


# ---------------------------------------------------------------------------
# Injected-instruction detection
# ---------------------------------------------------------------------------
# NOT a defence. The defence is the quarantine above, which holds whether or not
# this spots anything. This exists so an operator can see that someone tried,
# and so the source's load rating can drop in Task 5.

_INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"ignore (?:all )?(?:your )?previous instructions", "instruction override"),
    (r"you are now (?:an? )?(?:admin|administrator|system)", "role escalation"),
    (r"disregard (?:the )?(?:above|prior|earlier)", "instruction override"),
    (r"\bsystem prompt\b", "prompt disclosure attempt"),
    (r"\bclm_\d{6}\b", "direct claim-id reference in free text"),
    (r"set .{0,40}\bto\b .{0,20}\bimmediately\b", "imperative mutation"),
)


@dataclass(frozen=True)
class InjectionSignal:
    pattern: str
    kind: str
    span: str


def scan_for_injection(text: str) -> list[InjectionSignal]:
    """Report injection attempts. Reporting only -- the quarantine is the defence.

    A detector treated as a defence is a defence that fails silently the first
    time somebody phrases it differently.
    """
    signals: list[InjectionSignal] = []
    for pattern, kind in _INJECTION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            signals.append(InjectionSignal(pattern=pattern, kind=kind, span=match.group(0)))
    return signals
