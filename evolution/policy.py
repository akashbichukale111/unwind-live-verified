"""The version policy, applied. Deterministic, and genuinely load-bearing.

WHY THIS MODULE HAS TO EXIST FOR THE LOOP TO BE REAL
-------------------------------------------------------
An evolution loop whose output is only prose has a measurement problem it
usually hides: with no model in the path, a changed instruction changes
nothing, so a baseline-vs-candidate comparison over a deterministic pipeline
returns two identical scores -- and a loop that reports an improvement there
is reporting one it did not measure.

This repository refuses that. An `AgentVersion` carries a `policy` as well as
an `instruction`, and this module is where the policy actually decides
something. A candidate that raises `min_evidence_completeness` from 0.5 to
0.7 produces a MEASURABLY different trajectory over the same evidence, with
no model involved at all, because `may_propose_external_effect` genuinely
returns a different answer and the mission genuinely takes a different path.

So the comparison in `evolution/promote.py` is honest in both modes:

  with a model     -- instruction AND policy differences are measured;
  with no model    -- policy differences are measured, and
                      `promote.py` states in the decision record that the
                      instruction delta was NOT exercised. It never scores an
                      unexercised instruction change as an improvement.

WHAT A POLICY IS NOT
-----------------------
A preference, never a permission. Every verdict below is advisory to the
PLANNER -- it narrows what the agent will propose. It is not, and never
substitutes for, `tower/gateway.py`, which independently authorises every
step regardless of what any policy said. A policy that said "yes" to
something the registry forbids changes nothing: the Gateway still refuses it.
That ordering is the whole reason it is safe to let an evolution loop write
policies at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evolution.schema import AgentVersion
from evolution.versions import SEED_POLICY


@dataclass(frozen=True)
class PolicyVerdict:
    """One policy decision, with the numbers it was made from attached.

    `reasons` is never empty for a refusal: a policy that narrows behaviour
    without saying why is indistinguishable from a bug.
    """

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    observed: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.allowed


def effective_policy(version: AgentVersion | None) -> dict[str, Any]:
    """The policy actually in force.

    Falls back to `SEED_POLICY` key by key, so a version written before a key
    existed behaves as the seed does for that key rather than as if the key
    were absent. A missing key must never read as "no limit".
    """
    policy = dict(SEED_POLICY)
    if version is not None:
        policy.update(version.policy or {})
    return policy


def may_propose_external_effect(
    version: AgentVersion | None,
    *,
    evidence_completeness: float,
    contradictions_unresolved: int,
    human_concurrence: bool,
) -> PolicyVerdict:
    """May this agent propose a step that changes something outside the process?

    Two independent clauses, both from the version's own policy:

      `min_evidence_completeness` -- an external effect proposed from thin
          evidence is the expensive mistake this whole repository exists to
          prevent, so coverage gates the proposal;
      `require_human_on_contradiction` -- acting on contested ground without
          a human is the other one.

    A human already in the loop satisfies the second clause: the point of the
    clause is that a person sees the contradiction, not that contradictions
    forbid action forever.
    """
    policy = effective_policy(version)
    minimum = float(policy.get("min_evidence_completeness", 0.5))
    require_human = bool(policy.get("require_human_on_contradiction", True))

    reasons: list[str] = []
    observed = {
        "evidence_completeness": round(float(evidence_completeness), 4),
        "min_evidence_completeness": minimum,
        "contradictions_unresolved": int(contradictions_unresolved),
        "require_human_on_contradiction": require_human,
        "human_concurrence": bool(human_concurrence),
        "policy_version": version.version_id if version else None,
    }

    if float(evidence_completeness) < minimum:
        reasons.append(
            f"evidence completeness {evidence_completeness:.2f} is below the "
            f"version's minimum {minimum:.2f}"
        )
    if require_human and int(contradictions_unresolved) > 0 and not human_concurrence:
        reasons.append(
            f"{int(contradictions_unresolved)} unresolved contradiction(s) and this "
            "version requires human concurrence before acting on contested evidence"
        )
    return PolicyVerdict(allowed=not reasons, reasons=reasons, observed=observed)


def plan_step_ceiling(version: AgentVersion | None) -> int:
    """The version's own plan-length preference, never above the hard cap.

    `fleet/planner.py:MAX_PLAN_STEPS` clamps regardless; this can only ever
    narrow further. A policy cannot widen a bound the planner enforces.
    """
    from fleet.planner import MAX_PLAN_STEPS

    policy = effective_policy(version)
    try:
        requested = int(policy.get("max_plan_steps", MAX_PLAN_STEPS))
    except (TypeError, ValueError):
        requested = MAX_PLAN_STEPS
    return max(1, min(MAX_PLAN_STEPS, requested))


def requires_verification_after_execute(version: AgentVersion | None) -> bool:
    policy = effective_policy(version)
    return bool(policy.get("verify_after_execute", True))


__all__ = [
    "PolicyVerdict",
    "effective_policy",
    "may_propose_external_effect",
    "plan_step_ceiling",
    "requires_verification_after_execute",
]
