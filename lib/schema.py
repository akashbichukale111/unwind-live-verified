"""Typed models for every Firestore collection UNWIND writes.

Two things in here are load-bearing and were decided before any logic exists,
because retrofitting them is painful:

1. Temporal Truth (locked decision 1.1). A claim is never TRUE or FALSE. It is
   a value, at a time, under a context, from a source, with a confidence.
   `valid_from`, `invalidated_at` and `invalidation_reason` therefore exist on
   every claim from the first commit. The system says "the world changed", not
   "someone was wrong".

2. Retraction authority (locked decision 1.4). The entire input surface is
   attacker-controlled text. A forged retraction triggers a mass unwind of real
   commitments, so it is a weapon. `Claim.authority_scope` and `Source.authority`
   exist now even though Task 1 checks neither; Task 3 makes the check a
   deterministic function node, never a prompt.

Nothing in this module makes a model call or touches the network.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    def to_firestore(self) -> dict[str, Any]:
        """Plain dict for the Firestore client. Enums flatten to their values."""
        return self.model_dump(mode="json", exclude_none=False)


# ===========================================================================
# claims/{claim_id}
# ===========================================================================


class ClaimType(str, Enum):
    NUMERIC = "NUMERIC"
    TEMPORAL = "TEMPORAL"
    CONTRACTUAL = "CONTRACTUAL"
    REGULATORY = "REGULATORY"
    RELATIONAL = "RELATIONAL"


class ClaimStatus(str, Enum):
    LIVE = "live"
    RETRACTED = "retracted"
    TOMBSTONED = "tombstoned"


class FalsificationPredicate(_Base):
    """A machine-checkable statement of what would make this claim false.

    T1 evaluates this arithmetically with no model call. `op` is deliberately a
    tiny closed vocabulary: a predicate the arithmetic tier cannot evaluate is
    an UNRESOLVED, not a guess.
    """

    op: str = Field(description="One of: eq, neq, gt, gte, lt, lte, changed, unparseable")
    field: str = Field(description="Dotted path on the claim, usually 'value'")
    threshold: float | str | None = None
    unit: str | None = None
    #: Set when the predicate is not machine-checkable. Anything carrying this
    #: routes to UNRESOLVED rather than being defaulted to a safe answer (1.6).
    unresolvable_reason: str | None = None

    @property
    def machine_checkable(self) -> bool:
        return self.unresolvable_reason is None and self.op != "unparseable"


class Claim(_Base):
    claim_id: str
    type: ClaimType
    #: Normalised claim string, e.g. "supplier_K.lead_time_days".
    canonical: str
    value: float | str | bool | None
    unit: str | None = None

    source_id: str
    confidence: float = Field(ge=0.0, le=1.0)

    falsified_when: FalsificationPredicate

    #: Which agent asserted this claim, and at which version. Task 5 drops the
    #: reputation of agents whose extractions get overturned.
    extracted_by: str
    extracted_at: datetime

    # --- Temporal Truth (1.1) -------------------------------------------
    valid_from: datetime
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None

    # --- Retraction authority (1.4) --------------------------------------
    #: Source ids (or source kinds) with standing to retract this claim. A
    #: supplier email may falsify supplier lead time and nothing else.
    authority_scope: list[str] = Field(default_factory=list)

    status: ClaimStatus = ClaimStatus.LIVE
    #: Denormalised dependent count. Drives load-line thickness in the UI later.
    load_weight: int = 0

    @field_validator("authority_scope")
    @classmethod
    def _authority_scope_not_empty(cls, v: list[str]) -> list[str]:
        # An empty scope would mean "anyone may retract this", which is the
        # exact failure mode 1.4 exists to close.
        if not v:
            raise ValueError("authority_scope must name at least one source with standing")
        return v


# ===========================================================================
# conclusions/{conclusion_id}
# ===========================================================================


class ConclusionKind(str, Enum):
    QUOTE = "quote"
    ORDER = "order"
    PLAN = "plan"
    PROMISE = "promise"
    APPROVAL = "approval"
    PRICE = "price"
    # Long-dated instruments. Their validity runs 180-365 days, which is what
    # lets a decision still be governing months after its premise was set and
    # its effect left the building.
    STANDING_PRICE = "standing_price"
    FRAMEWORK_PROMISE = "framework_promise"
    LONG_LEAD_ORDER = "long_lead_order"


#: Kinds whose commercial validity is measured in quarters rather than weeks.
LONG_DATED_KINDS: frozenset[ConclusionKind] = frozenset(
    {
        ConclusionKind.STANDING_PRICE,
        ConclusionKind.FRAMEWORK_PROMISE,
        ConclusionKind.LONG_LEAD_ORDER,
    }
)


class ConclusionStatus(str, Enum):
    LIVE = "live"
    CORRECTED = "corrected"
    OBLIGATED = "obligated"
    SUPERSEDED = "superseded"
    #: First-class (1.6). Never hidden, never defaulted to safe.
    UNRESOLVED = "unresolved"
    #: CLOSED-OUT. The commitment already discharged -- delivery made, quote
    #: expired, flight ended -- BEFORE the premise moved. It was fulfilled under
    #: the old value, and a later change does not reach back to it. This is not
    #: a variant of "immaterial": immaterial means the buffer absorbed the shock,
    #: closed-out means the shock never applied. Conflating them would hide the
    #: reason 39 nodes in the demo corpus need no attention.
    CLOSED_OUT = "closed_out"


class Reversibility(str, Enum):
    """How an effect that already escaped can be undone.

    IDEMPOTENT   re-issuing the corrected artifact converges; no residue.
    COMPENSABLE  cannot be undone, but a synthesised compensation exists.
    IRREVERSIBLE money or trust already left; only a correction obligation remains.
    UNKNOWN      could not be determined -> UNRESOLVED, not assumed safe.
    """

    IDEMPOTENT = "idempotent"
    COMPENSABLE = "compensable"
    IRREVERSIBLE = "irreversible"
    UNKNOWN = "unknown"


class ExternalEffect(_Base):
    """Something that already escaped into the world: sent, signed, shipped, paid."""

    connector: str = Field(description="e.g. email, erp, ads, payments")
    op: str = Field(description="e.g. send_quote, issue_po, launch_flight, pay_invoice")
    ref: str = Field(description="External system reference id")
    reversibility: Reversibility
    occurred_at: datetime
    #: Present only when reversibility is COMPENSABLE or IRREVERSIBLE.
    amount_minor: int | None = Field(
        default=None, description="Money at stake, in minor units (cents)"
    )
    currency: str | None = None


class Conclusion(_Base):
    conclusion_id: str
    kind: ConclusionKind
    body: str
    #: Must be visibly OLD in the corpus. The point of UNWIND is that decisions
    #: keep operating long after the premise under them died.
    decided_at: datetime
    owner_principal: str

    #: The edge set. This is the thing no enterprise records today.
    premise_ids: list[str] = Field(default_factory=list)

    external_effects: list[ExternalEffect] = Field(default_factory=list)
    #: Whether the effect record is trustworthy. An empty `external_effects` with
    #: this True is a positive assertion that nothing left the building. With it
    #: False -- a connector that failed to sync, a system with no outbound log --
    #: escapement is UNKNOWABLE, and the lookup fails safe to ESCAPED. Treating an
    #: unescaped item as escaped costs a wasted check; the reverse costs a customer.
    effects_recorded: bool = True
    status: ConclusionStatus = ConclusionStatus.LIVE

    # --- fields the corpus needs so materiality is arithmetic, not vibes ----
    #: Lead time in days this conclusion committed downstream. Slack against the
    #: hub premise is `committed_lead_days - premise value`; T1 compares the
    #: delta to the slack with no model call.
    committed_lead_days: int | None = None
    #: When the commitment closes out (delivery made, quote expires, flight ends).
    #: A commitment that closed before the retraction cannot be harmed by it.
    closes_at: datetime | None = None
    #: Set when a conclusion is itself asserted as a premise for others.
    emits_claim_id: str | None = None

    @property
    def escaped(self) -> bool:
        return bool(self.external_effects)


# ===========================================================================
# reverse_index/{claim_id}/dependents/{conclusion_id}
# ===========================================================================


class ReverseEdge(_Base):
    """The edge that points backwards from a claim to what was built on it.

    T0 walks this and only this. No model, no arithmetic -- just traversal.
    """

    claim_id: str
    conclusion_id: str
    depth: int = Field(ge=1, description="Hops from the claim; 1 is a direct dependent")
    #: Drives load-line thickness in the UI later.
    weight: float = 1.0


# ===========================================================================
# obligations/{obligation_id}
# ===========================================================================


class ObligationStatus(str, Enum):
    RAISED = "raised"
    AWAITING_SIGNATURE = "awaiting_signature"
    SIGNED = "signed"
    DISCHARGED = "discharged"
    DECLINED = "declined"


class ResidualExposure(_Base):
    """A range, never a point estimate, and it carries its own assumptions.

    A point estimate of an unrecoverable loss is a fiction with a decimal place:
    it invites the reader to treat a modelling choice as a measurement. The
    range is bounded by what was actually recorded, and `unpriced_effects`
    reports how many effects carried no amount at all -- so a reader can see
    that the range is a floor rather than assuming it is a ceiling.
    """

    low: int = Field(description="Minor units (cents)")
    high: int = Field(description="Minor units (cents)")
    currency: str = "USD"
    assumptions: list[str] = Field(default_factory=list)
    #: Effects with no recorded amount. These are NOT priced into the range --
    #: inventing a figure for them would breach the no-invented-numbers rule.
    unpriced_effects: int = 0


class Obligation(_Base):
    obligation_id: str
    conclusion_id: str
    counterparties: list[str] = Field(default_factory=list)
    reversible_actions: list[str] = Field(default_factory=list)
    residual_exposure: ResidualExposure
    approver: str | None = None
    status: ObligationStatus = ObligationStatus.RAISED
    ruling_id: str | None = None


# ===========================================================================
# repairs/{repair_id}
# ===========================================================================


class PleaStance(str, Enum):
    """The four things an owner may argue. A closed set, not free text.

    An owner that could say anything would be a chat participant; an owner that
    must pick one of four is a party to a proceeding whose outcome can be
    tallied deterministically.
    """

    SURVIVE_UNCHANGED = "survive_unchanged"
    SURVIVE_AMENDED = "survive_amended"
    CONCEDE = "concede"
    #: Attacks the retraction rather than defending the commitment.
    DISPUTE_RETRACTION = "dispute_retraction"


class Plea(_Base):
    """A commitment owner arguing for its own conclusion in the repair court."""

    member_owner_id: str
    conclusion_id: str
    argument: str
    claimed_materiality: float | None = None
    stance: PleaStance = PleaStance.SURVIVE_UNCHANGED
    #: Citations to record. An empty list is what triggers the discount below --
    #: the brief requires unevidenced pleas to be discounted AUTOMATICALLY, so
    #: this is not advisory.
    evidence: list[str] = Field(default_factory=list)
    #: Set by the protocol, never by the owner: a party does not get to decide
    #: how much its own argument counts.
    discounted: bool = False
    weight: float = 1.0


class Challenge(_Base):
    challenger_owner_id: str
    target_owner_id: str
    argument: str
    #: Conflicting commitments contend for the same finite thing (reserved
    #: capacity, one delivery slot). Naming it makes allocation possible.
    contested_resource: str | None = None


class Ruling(_Base):
    arbiter_id: str
    decision: str
    rationale: str
    decided_at: datetime
    #: Above the cost threshold a ruling does not take effect on its own
    #: authority; it becomes a recommendation attached to a signature request.
    advisory: bool = False
    #: False when the protocol hit its turn cap or budget without settling, in
    #: which case the conservative default applied rather than a real ruling.
    converged: bool = True
    #: Owners whose commitment the ruling did not preserve, in ruling order.
    conceded_conclusion_ids: list[str] = Field(default_factory=list)


class Repair(_Base):
    repair_id: str
    claim_id: str
    #: The repair team is composed at runtime from a blast radius that did not
    #: exist a second earlier (ADK 2 dynamic pattern, locked decision 1.3).
    member_owner_ids: list[str] = Field(default_factory=list)
    pleas: list[Plea] = Field(default_factory=list)
    challenges: list[Challenge] = Field(default_factory=list)
    ruling: Ruling | None = None
    dissent: list[str] = Field(default_factory=list)


# ===========================================================================
# sources/{source_id}
# ===========================================================================


class SourceKind(str, Enum):
    SUPPLIER_EMAIL = "supplier_email"
    VENDOR_PDF = "vendor_pdf"
    ERP_FEED = "erp_feed"
    CONTRACT = "contract"
    REGULATORY_BULLETIN = "regulatory_bulletin"
    INTERNAL_SYSTEM = "internal_system"
    BROKER_EMAIL = "broker_email"


class FalsificationEvent(_Base):
    claim_id: str
    at: datetime
    note: str


class Source(_Base):
    source_id: str
    name: str
    kind: SourceKind
    #: 0..1. Task 5 drops this when a source is caught lying.
    load_rating: float = Field(ge=0.0, le=1.0, default=0.5)
    falsification_history: list[FalsificationEvent] = Field(default_factory=list)
    #: Canonical claim prefixes this source has standing over (1.4). A supplier
    #: email carries authority over its own lead time and nothing else.
    authority: list[str] = Field(default_factory=list)


# ===========================================================================
# agent_trust/{agent_id}
# ===========================================================================


class AutonomyTier(str, Enum):
    OBSERVE = "observe"
    PROPOSE = "propose"
    ACT_WITH_REVIEW = "act_with_review"
    ACT = "act"


class OverturnEvent(_Base):
    conclusion_id: str
    at: datetime
    overturned_by: str
    note: str


class AgentTrust(_Base):
    agent_id: str
    reputation: float = Field(ge=0.0, le=1.0, default=0.5)
    reliability: float = Field(ge=0.0, le=1.0, default=0.5)
    autonomy_tier: AutonomyTier = AutonomyTier.PROPOSE
    overturn_events: list[OverturnEvent] = Field(default_factory=list)


# ===========================================================================
# cascades/{cascade_id} and cascades/{cascade_id}/nodes/{conclusion_id}
#
# A cascade is a runtime EVENT with its own lifetime; the reverse index is a
# stable structural fact. Traversal depth is therefore written here and the
# reverse index is never mutated by a cascade -- otherwise the graph becomes
# unauditable and a later query cannot ask about one specific traversal.
# ===========================================================================


class CascadeStatus(str, Enum):
    REFUSED = "refused"  # authority gate said no. Recorded, not raised.
    #: The radius was mapped and scored, but the authorisation half of the gate
    #: withheld permission -- too large, too expensive, or uncorroborated. The
    #: analysis is complete and correct; nothing may leave the building.
    AWAITING_AUTHORISATION = "awaiting_authorisation"
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"


class AuthorityReason(str, Enum):
    """Why the gate allowed or refused. A closed vocabulary, not free text."""

    SOURCE_HAS_STANDING = "source_has_standing"
    SOURCE_IN_CLAIM_SCOPE = "source_in_claim_scope"
    NO_SUCH_SOURCE = "no_such_source"
    NO_SUCH_CLAIM = "no_such_claim"
    SOURCE_OUTSIDE_CLAIM_SCOPE = "source_outside_claim_scope"
    CLAIM_NOT_LIVE = "claim_not_live"


class AuthorityDecision(_Base):
    """The gate's verdict. A refusal is a RECORDED EVENT, never an exception.

    Task 3 puts one of these on screen, which it cannot do if the refusal path
    is a stack trace.
    """

    allowed: bool
    reason_code: AuthorityReason
    reason: str
    source_id: str
    claim_id: str
    checked_at: datetime
    #: The authority prefixes the source actually holds, recorded so a refusal
    #: can be read months later without re-resolving the source.
    source_authority: list[str] = Field(default_factory=list)
    claim_authority_scope: list[str] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class BudgetTier(str, Enum):
    """How deep an investigation the blast radius earns.

    LOW       T0 + T1 only, zero model calls
    MEDIUM    + re-derivation on the top-N by exposure      [T2, Task 3]
    HIGH      + full court arbitration                      [Task 4]
    CRITICAL  + mandatory human sign-off                    [Task 4]
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Budget(_Base):
    cost_cap_usd: float
    time_cap_seconds: float
    max_model_calls: int
    #: What the policy says the radius warrants, given what T0/T1 found.
    policy_tier: BudgetTier
    #: What actually ran. Diverges from policy_tier whenever the warranted tier
    #: is not built yet, and the divergence carries a stated reason.
    tier_reached: str
    stopped_reason: str | None = None
    rationale: list[str] = Field(default_factory=list)


class Cascade(_Base):
    cascade_id: str
    claim_id: str
    triggered_at: datetime
    triggered_by: str
    status: CascadeStatus
    budget: Budget | None = None
    tier_reached: str = "T0"
    authority: AuthorityDecision | None = None
    #: Denormalised so the collection is readable without walking the subcollection.
    radius_size: int = 0
    regime_counts: dict[str, int] = Field(default_factory=dict)
    model_calls: int = 0


class CascadeNode(_Base):
    """One conclusion, as this cascade found and scored it."""

    cascade_id: str
    conclusion_id: str
    depth: int
    #: Claim -> conclusion -> claim -> ... back to the retracted claim. Makes a
    #: verdict explainable without re-running the traversal.
    path: list[str] = Field(default_factory=list)
    regime: Regime
    #: None means the cascade declined to decide. Never coerced to False.
    materiality: bool | None = None
    escapement: bool = True
    reason_code: str = ""
    scored_by: str = ""
    scored_at: datetime | None = None
    unresolved_reason: str | None = None
    #: What the arithmetic actually used, kept so the verdict can be checked.
    slack_days: int | None = None
    shock_days: int | None = None


# ===========================================================================
# Causal debt -- the measure that exists on a normal day, when nothing broke
# ===========================================================================


class DebtFactor(str, Enum):
    UNCERTAIN = "uncertain"  # low-confidence premise
    STALE = "stale"  # premise has not been reaffirmed in a long time
    CONFLICTING = "conflicting"  # two live claims disagree about the same fact
    FRAGILE = "fragile"  # premise carries a lot of load


class DebtContribution(_Base):
    """One premise's contribution to one conclusion's debt.

    Every contribution names its premise. A debt figure nobody can attribute is
    a number on a dashboard, not a measure.
    """

    conclusion_id: str
    claim_id: str
    claim_canonical: str
    factor: DebtFactor
    factor_value: float
    exposure: float
    irreversibility: float
    contribution: float
    explanation: str


class CausalDebtScore(_Base):
    as_of: datetime
    total: float
    conclusions_scored: int
    claims_implicated: int
    by_factor: dict[str, float] = Field(default_factory=dict)
    #: Heaviest premises first -- the fragility ranking, before anything breaks.
    top_claims: list[dict[str, Any]] = Field(default_factory=list)
    top_conclusions: list[dict[str, Any]] = Field(default_factory=list)


# ===========================================================================
# The five-state decision (locked decision 1.5). Schema-ready; Task 3 builds it.
# ===========================================================================


class DecisionState(str, Enum):
    EXECUTE = "execute"
    ASK_HUMAN = "ask_human"
    RETRY = "retry"
    DEFER = "defer"
    REFUSE = "refuse"


class StatedDecision(_Base):
    """Every state carries a WHY. A false retraction is worse than a missed one."""

    state: DecisionState
    why: str
    tier: str = Field(description="T0 | T1 | T2 -- which tier produced this")
    decided_at: datetime


# ===========================================================================
# The four regimes (locked decision, brief section 0). A ROUTER, not a prompt.
# ===========================================================================


class Regime(str, Enum):
    """materiality x escapement. Exactly one cell is an alert.

    IMMATERIAL_CONTAINED  dies silently, logged
    IMMATERIAL_ESCAPED    dies silently, logged
    MATERIAL_CONTAINED    corrected in place
    MATERIAL_ESCAPED      -> CORRECTION OBLIGATION
    """

    IMMATERIAL_CONTAINED = "immaterial_contained"
    IMMATERIAL_ESCAPED = "immaterial_escaped"
    MATERIAL_CONTAINED = "material_contained"
    MATERIAL_ESCAPED = "material_escaped"
    #: Could not be determined. Displayed, never hidden (1.6).
    UNRESOLVED = "unresolved"
    #: Already discharged before the premise moved. Reported separately from the
    #: immaterial cells because the reason is different and an operator asking
    #: "why is this not on my list" deserves the real answer.
    CLOSED_OUT = "closed_out"


__all__ = [
    "LONG_DATED_KINDS",
    "AgentTrust",
    "AuthorityDecision",
    "AuthorityReason",
    "AutonomyTier",
    "Budget",
    "BudgetTier",
    "Cascade",
    "CascadeNode",
    "CascadeStatus",
    "CausalDebtScore",
    "Challenge",
    "DebtContribution",
    "DebtFactor",
    "Claim",
    "ClaimStatus",
    "ClaimType",
    "Conclusion",
    "ConclusionKind",
    "ConclusionStatus",
    "DecisionState",
    "ExternalEffect",
    "FalsificationEvent",
    "FalsificationPredicate",
    "Obligation",
    "ObligationStatus",
    "OverturnEvent",
    "Plea",
    "Regime",
    "Repair",
    "ResidualExposure",
    "ReverseEdge",
    "Reversibility",
    "Ruling",
    "Source",
    "SourceKind",
    "StatedDecision",
]
