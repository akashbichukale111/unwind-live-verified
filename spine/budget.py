"""The cascade budgeter -- a policy, not a limit.

The question is not "how much may we spend" but "how much investigation does
this blast radius deserve". Those are different, and only the second one scales:
a retraction that harms nothing should cost nothing, and a retraction that put
non-refundable money out the door should be allowed to cost real time and a
human's attention.

    LOW       T0 + T1 only, zero model calls
    MEDIUM    + re-derivation on the top-N by exposure       [T2, Task 3]
    HIGH      + full court arbitration                       [Task 4]
    CRITICAL  + mandatory human sign-off                     [Task 4]

WHY THE BUDGET IS DECIDED *AFTER* THE TRAVERSAL
-----------------------------------------------
Severity cannot be known before the radius is mapped, and mapping it is free --
T0 and T1 make no model call. So the free work always runs, and the budgeter
then decides whether the expensive work is warranted. Gating the free work would
save nothing and blind the decision.

Task 2 implements the whole policy and the LOW path only. When the policy asks
for more than exists, the cascade RECORDS the warranted tier and stops with a
stated reason. It does not silently do less and report success.
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.config import Tier
from lib.schema import Budget, BudgetTier
from lib.telemetry import policy_gate_span

#: Thresholds are stated so they can be argued with. [ASSUMPTION] Judgement, not
#: measurement.
HIGH_EXPOSURE_MINOR = 1_000_000  # USD 10,000.00 already out the door
MEDIUM_ALERT_COUNT = 1
HIGH_ALERT_COUNT = 10

TIER_BUDGETS: dict[BudgetTier, tuple[float, float, int]] = {
    # (cost_cap_usd, time_cap_seconds, max_model_calls)
    BudgetTier.LOW: (0.0, 30.0, 0),
    BudgetTier.MEDIUM: (0.50, 120.0, 200),
    BudgetTier.HIGH: (5.00, 600.0, 2_000),
    BudgetTier.CRITICAL: (20.00, 3_600.0, 5_000),
}

#: What Task 2 can actually execute. Everything above this records and stops.
IMPLEMENTED_TIER = BudgetTier.LOW
NOT_IMPLEMENTED_REASON = {
    BudgetTier.MEDIUM: (
        "Radius warrants MEDIUM: T2 re-derivation on the top-N by exposure. "
        "Not built -- that is Task 3. Stopping after T1 with the warranted tier "
        "recorded rather than reporting a complete investigation."
    ),
    BudgetTier.HIGH: (
        "Radius warrants HIGH: full court arbitration between commitment owners. "
        "Not built -- that is Task 4. Stopping after T1 with the warranted tier "
        "recorded."
    ),
    BudgetTier.CRITICAL: (
        "Radius warrants CRITICAL: irreversible effects already escaped, so a "
        "human signature is mandatory before any correction goes out. Not built "
        "-- that is Task 4. Stopping after T1 with the warranted tier recorded."
    ),
}


@dataclass(frozen=True)
class RadiusSeverity:
    """Everything the policy is allowed to look at. Facts, already computed."""

    radius_size: int
    alert_count: int  # MATERIAL_ESCAPED
    material_count: int
    unresolved_count: int
    total_money_minor: int
    max_irreversibility: float


def decide_budget(severity: RadiusSeverity) -> Budget:
    """Choose the warranted tier, and say what actually ran."""
    with policy_gate_span("cascade_budgeter", Tier.T1) as span:
        rationale: list[str] = []

        if severity.max_irreversibility >= 1.0 and severity.alert_count > 0:
            tier = BudgetTier.CRITICAL
            rationale.append(
                f"{severity.alert_count} correction obligation(s) involve an "
                "irreversible effect that already escaped."
            )
        elif (
            severity.total_money_minor >= HIGH_EXPOSURE_MINOR
            or severity.alert_count >= HIGH_ALERT_COUNT
        ):
            tier = BudgetTier.HIGH
            rationale.append(
                f"{severity.alert_count} correction obligation(s) and "
                f"{severity.total_money_minor / 100:.2f} USD of committed effect."
            )
        elif severity.alert_count >= MEDIUM_ALERT_COUNT or severity.unresolved_count > 0:
            tier = BudgetTier.MEDIUM
            rationale.append(
                f"{severity.alert_count} correction obligation(s) and "
                f"{severity.unresolved_count} node(s) this tier could not decide."
            )
        else:
            tier = BudgetTier.LOW
            rationale.append(
                "Nothing material escaped and nothing was left undecided. The "
                "deterministic tiers settled the whole radius."
            )

        rationale.append(
            f"Radius {severity.radius_size} nodes; {severity.material_count} "
            f"materially harmed; {severity.unresolved_count} unresolved."
        )

        cost_cap, time_cap, max_calls = TIER_BUDGETS[tier]
        stopped_reason = None if tier is IMPLEMENTED_TIER else NOT_IMPLEMENTED_REASON[tier]

        budget = Budget(
            cost_cap_usd=cost_cap,
            time_cap_seconds=time_cap,
            max_model_calls=max_calls,
            policy_tier=tier,
            # T1 is as far as anything gets in Task 2, by construction.
            tier_reached="T1",
            stopped_reason=stopped_reason,
            rationale=rationale,
        )
        span.set_attribute("unwind.policy_tier", tier.value)
        span.set_attribute("unwind.tier_reached", budget.tier_reached)
        return budget
