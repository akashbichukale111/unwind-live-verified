"""The retraction-authority gate. Runs before anything else, decides everything.

UNWIND's entire input surface is attacker-controlled text: supplier emails,
vendor PDFs, broker notices. A forged retraction is not a data-quality problem,
it is a weapon -- accepting one cascades a mass unwind of thousands of real
commitments and sends corrections to real counterparties.

So the gate is deterministic. It compares the source's authority prefixes to the
claim's authority scope and returns allow or refuse. There is no model here and
there never can be: a prompt that can be argued with is not a gate.

A REFUSAL IS A RECORDED EVENT, NOT AN EXCEPTION. It returns an
`AuthorityDecision` with `allowed=False` and a closed-vocabulary reason code,
which is what lets Task 3 put a live refusal on screen with its reason named.
"""

from __future__ import annotations

from datetime import UTC, datetime

from lib.config import Tier
from lib.schema import AuthorityDecision, AuthorityReason, Claim, ClaimStatus, Source
from lib.telemetry import policy_gate_span

GATE_NAME = "retraction_authority"


def check_authority(
    source: Source | None,
    claim: Claim | None,
    source_id: str,
    claim_id: str,
    now: datetime | None = None,
) -> AuthorityDecision:
    """Decide whether `source` has standing to retract `claim`.

    Standing is granted two ways, and both are explicit:

    1. The claim's `authority_scope` names the source id outright.
    2. The source holds an authority prefix that the claim's canonical name
       starts with -- so `supplier_K.` covers `supplier_K.lead_time_days` and
       nothing else.

    Everything else refuses. Note the direction of the defaults: an unknown
    source, an unknown claim, or a claim that is already dead all refuse. There
    is no path through this function that allows on missing information.
    """
    checked_at = now or datetime.now(UTC)

    with policy_gate_span(GATE_NAME, Tier.T0, source_id=source_id, claim_id=claim_id) as span:
        if source is None:
            decision = AuthorityDecision(
                allowed=False,
                reason_code=AuthorityReason.NO_SUCH_SOURCE,
                reason=f"No source {source_id!r} is known, so it holds no authority over anything.",
                source_id=source_id,
                claim_id=claim_id,
                checked_at=checked_at,
            )
        elif claim is None:
            decision = AuthorityDecision(
                allowed=False,
                reason_code=AuthorityReason.NO_SUCH_CLAIM,
                reason=f"No claim {claim_id!r} exists to retract.",
                source_id=source_id,
                claim_id=claim_id,
                checked_at=checked_at,
                source_authority=list(source.authority),
            )
        elif claim.status is not ClaimStatus.LIVE:
            decision = AuthorityDecision(
                allowed=False,
                reason_code=AuthorityReason.CLAIM_NOT_LIVE,
                reason=(
                    f"Claim {claim_id!r} is {claim.status.value}, not live. "
                    "A claim that already died cannot be retracted again."
                ),
                source_id=source_id,
                claim_id=claim_id,
                checked_at=checked_at,
                source_authority=list(source.authority),
                claim_authority_scope=list(claim.authority_scope),
            )
        elif source_id in claim.authority_scope:
            decision = AuthorityDecision(
                allowed=True,
                reason_code=AuthorityReason.SOURCE_IN_CLAIM_SCOPE,
                reason=(
                    f"{source_id!r} is named directly in the authority scope of "
                    f"{claim.canonical!r}."
                ),
                source_id=source_id,
                claim_id=claim_id,
                checked_at=checked_at,
                source_authority=list(source.authority),
                claim_authority_scope=list(claim.authority_scope),
            )
        elif any(claim.canonical.startswith(prefix) for prefix in source.authority):
            matched = next(p for p in source.authority if claim.canonical.startswith(p))
            decision = AuthorityDecision(
                allowed=True,
                reason_code=AuthorityReason.SOURCE_HAS_STANDING,
                reason=(
                    f"{source_id!r} holds authority over {matched!r}, which covers "
                    f"{claim.canonical!r}."
                ),
                source_id=source_id,
                claim_id=claim_id,
                checked_at=checked_at,
                source_authority=list(source.authority),
                claim_authority_scope=list(claim.authority_scope),
            )
        else:
            decision = AuthorityDecision(
                allowed=False,
                reason_code=AuthorityReason.SOURCE_OUTSIDE_CLAIM_SCOPE,
                reason=(
                    f"{source_id!r} holds authority over {sorted(source.authority)!r} "
                    f"and is not named in the authority scope of {claim.canonical!r} "
                    f"({sorted(claim.authority_scope)!r}). It has no standing to "
                    "retract this claim."
                ),
                source_id=source_id,
                claim_id=claim_id,
                checked_at=checked_at,
                source_authority=list(source.authority),
                claim_authority_scope=list(claim.authority_scope),
            )

        span.set_attribute("unwind.authority_allowed", decision.allowed)
        span.set_attribute("unwind.authority_reason", decision.reason_code.value)
        return decision
