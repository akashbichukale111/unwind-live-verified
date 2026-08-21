"""WARRANT MARKET: what an action costs, and what uncertainty adds to it.

THE IDEA, IN ONE PARAGRAPH
-----------------------------
An agent does not act because a policy says it may. It acts because it holds
warrant it earned, and the act SPENDS that warrant. `warrant/ledger.py`
already provides the ledger half of that: mint, spend-or-refuse, burn, decay,
a pure integer fold. What was missing is the PRICE half -- a deterministic
answer to "what does THIS action, proposed under THESE conditions, cost?"
This module is that answer.

Two independent inputs, multiplied, never blended into a score:

    cost_bp = BASE_COST[action_kind] * (1 + uncertainty_tax)

BASE COST is a property of the act. Reading a public page is not a
production mutation and must not price like one.

UNCERTAINTY TAX is a property of the situation the act is proposed in. This
is the part that is new. Every existing agent-authorization system prices
an action the same whether the agent is on firm ground or guessing. Here,
uncertainty is expensive:

    stale evidence          -> tax
    incomplete tool output  -> tax
    behavioural drift       -> tax
    model disagreement      -> tax
    risk-signal divergence  -> tax
    external state changed  -> tax

and the consequence is mechanical rather than advisory:

    MORE UNCERTAINTY -> HIGHER COST -> the same balance buys FEWER actions
                     -> the Gateway's `check_budget` refuses sooner
                     -> more work routes to verification and to a human.

An agent that is unsure literally cannot afford to act broadly. It must
either gather better evidence (cheapening the act) or escalate.

WHY THIS IS ARITHMETIC AND NOT A MODEL
------------------------------------------
The tax is computed here, in `warrant/`, which
`tests/test_warrant_zero_model.py` already proves imports no framework and
no model client by walking its import graph. That test now covers this
module for free. A language model may PROPOSE an action; it can never price
it, discount it, or argue the tax down, because the code that prices it
cannot call a model even if someone wanted it to.

[ASSUMPTION] Every constant below is a chosen, demo-legible number, stated
as chosen -- the same discipline `hyperion/risk.py`'s weight table and
`singularity/behavior.py`'s baselines already apply to themselves. They are
ordered to be defensible (a production mutation outranks an internal read by
two orders of magnitude), not measured from production traffic that does not
exist in this repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ActionKind(str, Enum):
    """The closed vocabulary of things an agent can propose to do.

    Closed on purpose. A planner -- including a language-model planner --
    may only select FROM this enum; it cannot invent an action kind, and an
    unknown string is rejected rather than priced at a default. That makes
    "the model proposed something nobody costed" unrepresentable instead of
    merely unlikely.
    """

    READ_PUBLIC = "READ_PUBLIC"
    READ_INTERNAL = "READ_INTERNAL"
    ANALYZE = "ANALYZE"
    WRITE_SANDBOX = "WRITE_SANDBOX"
    CREATE_TICKET = "CREATE_TICKET"
    CREATE_PR = "CREATE_PR"
    PRODUCTION_MUTATION = "PRODUCTION_MUTATION"
    SECRET_ACCESS = "SECRET_ACCESS"


#: [ASSUMPTION] Base price per action kind, in warrant basis points.
BASE_COST_BP: dict[ActionKind, int] = {
    ActionKind.READ_PUBLIC: 1,
    ActionKind.READ_INTERNAL: 10,
    ActionKind.ANALYZE: 5,
    ActionKind.WRITE_SANDBOX: 25,
    ActionKind.CREATE_TICKET: 50,
    ActionKind.CREATE_PR: 50,
    ActionKind.PRODUCTION_MUTATION: 200,
    ActionKind.SECRET_ACCESS: 500,
}

#: Action kinds that change something outside this process. Used by the
#: challenger and the human-gate policy; kept here so there is one
#: definition of "mutating" rather than a string search at each call site.
MUTATING_ACTIONS: frozenset[ActionKind] = frozenset(
    {
        ActionKind.WRITE_SANDBOX,
        ActionKind.CREATE_TICKET,
        ActionKind.CREATE_PR,
        ActionKind.PRODUCTION_MUTATION,
    }
)

#: Action kinds that require human concurrence before they may execute,
#: regardless of how much warrant the agent holds. Warrant is necessary, not
#: sufficient -- `warrant/DESIGN.md`'s double-consent rule.
REQUIRES_HUMAN: frozenset[ActionKind] = frozenset(
    {
        ActionKind.CREATE_PR,
        ActionKind.PRODUCTION_MUTATION,
        ActionKind.SECRET_ACCESS,
    }
)

# ---------------------------------------------------------------------------
# The uncertainty tax
# ---------------------------------------------------------------------------

#: [ASSUMPTION] Tax contribution per independent signal, in percentage points
#: of the base cost. Summed, then capped by `MAX_TAX_PCT`. Ordered
#: worst-first for readability only; the sum does not depend on order.
TAX_STALE_EVIDENCE_PCT = 40
TAX_INCOMPLETE_EVIDENCE_PCT = 35
TAX_MODEL_DISAGREEMENT_PCT = 60
TAX_EXTERNAL_STATE_CHANGED_PCT = 30
TAX_RISK_DIVERGENCE_PCT = 25

#: [ASSUMPTION] Consequence-band ladder. Deliberately the steepest single
#: contributor in the table: every other signal says "we are unsure about
#: this action", while this one says "we have WALKED THE GRAPH and know what
#: breaks". Measured consequence should outrank estimated uncertainty.
#: CALIBRATED, NOT GUESSED. The first values tried here (30/80/150) tipped a
#: mission that had legitimately earned its warrant into a challenge -- 163bp
#: requested against a 140bp balance -- so every default run ended CHALLENGED
#: and the execute/verify/settle path stopped being reachable at all. A tax
#: that blocks EVERY action is not a risk control, it is an outage.
#:
#: These values are set so that a HIGH band bites (a third again as
#: expensive) without by itself bankrupting an agent that has earned its
#: warrant, while SEVERE still can -- because a severe blast radius SHOULD
#: stop a mission and route it to a human.
#: `tests/test_consequence.py::test_both_outcomes_are_reachable` asserts both
#: paths remain live, so this calibration cannot silently drift into either
#: "never blocks" or "always blocks".
TAX_CONSEQUENCE_BAND_PCT: dict[str, int] = {
    "NONE": 0,
    "LOW": 0,
    "MODERATE": 15,
    "HIGH": 35,
    "SEVERE": 90,
}

#: [ASSUMPTION] Drift contributes on a band ladder rather than per-signal,
#: because `singularity/behavior.py` already folded its own signals into a
#: band and re-counting them here would double-charge the same evidence.
TAX_DRIFT_BAND_PCT: dict[str, int] = {
    "NORMAL": 0,
    "ELEVATED": 20,
    "DRIFT": 55,
    "CRITICAL": 120,
}

#: [ASSUMPTION] A ceiling exists so the tax can never make an action
#: infinitely expensive in a way that is indistinguishable from a hard
#: refusal. A refusal must come from the Gateway, with a reason code -- not
#: from a price nobody can pay. 300% is high enough that a maximally
#: uncertain READ_INTERNAL (10bp -> 40bp) still prices below a
#: CREATE_TICKET, which is the ordering that should survive.
MAX_TAX_PCT = 300

#: [ASSUMPTION] Evidence older than this contributes the staleness tax.
#: Matches `command_os/context_firewall.py`'s own staleness floor, quoted
#: rather than redefined, so the two cannot drift apart.
STALE_AFTER_SECONDS = 3600

#: [ASSUMPTION] Evidence coverage below this contributes the completeness tax.
MIN_COMPLETENESS = 0.75


@dataclass(frozen=True)
class UncertaintySignals:
    """Everything the tax is computed from. All measured or observed
    upstream -- never asserted by the agent being priced.

    `model_disagreement` is the one that makes the double-consent economy
    self-reinforcing: when the proposing model and the independent
    challenger disagree, the next action the mission proposes is more
    expensive, so a contested mission spends its authority down faster and
    reaches a human sooner.
    """

    evidence_age_seconds: float = 0.0
    evidence_completeness: float = 1.0
    drift_band: str = "NORMAL"
    model_disagreement: bool = False
    #: The band from `command_os/consequence.py`'s UNWIND RISK INDEX, computed
    #: by walking the REAL reverse index for the premises this action would
    #: change. This is the signal that makes the product's own thesis
    #: mechanical rather than editorial: an action whose blast radius contains
    #: consequences that already escaped is not merely *reported* as risky, it
    #: is literally more EXPENSIVE, so the same warrant balance buys fewer such
    #: actions and the Gateway refuses them sooner.
    consequence_band: str = "NONE"
    external_state_changed: bool = False
    risk_divergence: bool = False


@dataclass(frozen=True)
class UncertaintyAssessment:
    """The tax, with every contributing signal named.

    Never a bare percentage: `contributions` lists what fired and for how
    much, so an operator reading a refusal can see which piece of missing
    evidence made the action unaffordable -- and fix that, rather than
    asking for more warrant.
    """

    tax_pct: int
    contributions: list[str] = field(default_factory=list)
    capped: bool = False

    @property
    def multiplier(self) -> float:
        return 1.0 + (self.tax_pct / 100.0)


def assess_uncertainty(signals: UncertaintySignals) -> UncertaintyAssessment:
    """Fold observed signals into a tax percentage.

    Pure function. No clock (ages arrive pre-computed), no I/O, no random
    state, no model. The same signals always produce the same tax, which is
    what lets `scripts/` and tests re-derive a historical authorization
    decision exactly -- the same "rederive is bit-equal" property
    `fold_balance` establishes for balances.
    """
    total = 0
    contributions: list[str] = []

    consequence = (signals.consequence_band or "NONE").upper()
    consequence_pct = TAX_CONSEQUENCE_BAND_PCT.get(consequence, 0)
    if consequence_pct:
        total += consequence_pct
        contributions.append(
            f"consequence band {consequence} (real blast radius): +{consequence_pct}%"
        )

    band = (signals.drift_band or "NORMAL").upper()
    band_pct = TAX_DRIFT_BAND_PCT.get(band, 0)
    if band_pct:
        total += band_pct
        contributions.append(f"drift band {band}: +{band_pct}%")

    if signals.evidence_age_seconds > STALE_AFTER_SECONDS:
        total += TAX_STALE_EVIDENCE_PCT
        contributions.append(
            f"stale evidence ({signals.evidence_age_seconds:.0f}s > "
            f"{STALE_AFTER_SECONDS}s): +{TAX_STALE_EVIDENCE_PCT}%"
        )

    if signals.evidence_completeness < MIN_COMPLETENESS:
        total += TAX_INCOMPLETE_EVIDENCE_PCT
        contributions.append(
            f"incomplete evidence ({signals.evidence_completeness:.0%} < "
            f"{MIN_COMPLETENESS:.0%}): +{TAX_INCOMPLETE_EVIDENCE_PCT}%"
        )

    if signals.model_disagreement:
        total += TAX_MODEL_DISAGREEMENT_PCT
        contributions.append(f"independent challenger disagreed: +{TAX_MODEL_DISAGREEMENT_PCT}%")

    if signals.external_state_changed:
        total += TAX_EXTERNAL_STATE_CHANGED_PCT
        contributions.append(f"external state changed: +{TAX_EXTERNAL_STATE_CHANGED_PCT}%")

    if signals.risk_divergence:
        total += TAX_RISK_DIVERGENCE_PCT
        contributions.append(f"risk signals diverged: +{TAX_RISK_DIVERGENCE_PCT}%")

    capped = total > MAX_TAX_PCT
    if capped:
        contributions.append(f"capped at +{MAX_TAX_PCT}% (raw {total}%)")
        total = MAX_TAX_PCT

    return UncertaintyAssessment(tax_pct=total, contributions=contributions, capped=capped)


@dataclass(frozen=True)
class PricedAction:
    """One action, priced. Everything the Gateway and the audit record need."""

    action_kind: ActionKind
    base_bp: int
    tax_pct: int
    cost_bp: int
    contributions: list[str]
    requires_human: bool
    mutating: bool

    def as_record(self) -> dict[str, object]:
        return {
            "action_kind": self.action_kind.value,
            "base_bp": self.base_bp,
            "tax_pct": self.tax_pct,
            "cost_bp": self.cost_bp,
            "contributions": list(self.contributions),
            "requires_human": self.requires_human,
            "mutating": self.mutating,
        }


def price_action(action_kind: ActionKind, signals: UncertaintySignals) -> PricedAction:
    """`BASE_COST_BP[kind] * (1 + tax)`, rounded UP to the next basis point.

    Rounded up, never down: an action whose true price is 10.2bp costs 11bp.
    Rounding a price toward the agent's advantage is how a system slowly
    stops charging for uncertainty at all.
    """
    assessment = assess_uncertainty(signals)
    base = BASE_COST_BP[action_kind]
    # Integer ceiling division -- no float in the committed price, for the
    # same reason `fold_balance` refuses floating point.
    cost = -(-(base * (100 + assessment.tax_pct)) // 100)
    return PricedAction(
        action_kind=action_kind,
        base_bp=base,
        tax_pct=assessment.tax_pct,
        cost_bp=cost,
        contributions=list(assessment.contributions),
        requires_human=action_kind in REQUIRES_HUMAN,
        mutating=action_kind in MUTATING_ACTIONS,
    )


def parse_action_kind(raw: str) -> ActionKind:
    """Strict parse. An unrecognised action kind RAISES rather than defaulting.

    This is the tool boundary for a model-authored plan: a planner that
    hallucinates `"DELETE_EVERYTHING"` produces a rejected plan, not a
    cheaply-priced one. `fleet/planner.py` catches this and falls back to
    the deterministic planner rather than executing an unpriceable step.
    """
    try:
        return ActionKind(str(raw).strip().upper())
    except ValueError as exc:
        raise ValueError(
            f"{raw!r} is not a known ActionKind. The action vocabulary is closed: "
            f"{sorted(k.value for k in ActionKind)}"
        ) from exc


__all__ = [
    "BASE_COST_BP",
    "MAX_TAX_PCT",
    "MIN_COMPLETENESS",
    "MUTATING_ACTIONS",
    "REQUIRES_HUMAN",
    "STALE_AFTER_SECONDS",
    "TAX_CONSEQUENCE_BAND_PCT",
    "TAX_DRIFT_BAND_PCT",
    "ActionKind",
    "PricedAction",
    "UncertaintyAssessment",
    "UncertaintySignals",
    "assess_uncertainty",
    "parse_action_kind",
    "price_action",
]
