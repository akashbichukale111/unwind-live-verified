"""The four-turn negotiation protocol. Bounded proceedings, not a chat.

    1 NOTICE     the arbiter publishes the retraction, the affected commitment
                 and the re-derived alternative
    2 PLEA       each owner submits ONE structured argument
    3 CHALLENGE  owners may contest peers where commitments actually conflict
    4 RULING     written reasoning, with dissent recorded

⚠ TERMINATION IS STRUCTURAL, NOT EMERGENT. Three independent mechanisms, and
the first one alone is sufficient:

    1. THERE IS NO LOOP. `PHASES` is a fixed tuple of four callables executed
       in order, once each. The protocol contains no `while`, no recursion and
       no back-edge, so "runaway" is not a risk that is monitored -- it is a
       shape the code cannot take. A future edit that adds a loop has to delete
       an assertion to do it.
    2. COST BUDGET. Every model call is drawn from a ledger sized before the
       hearing opens. When it empties, the protocol stops and reports
       non-convergence.
    3. CONSERVATIVE DEFAULT. Non-convergence never means "carry on regardless":
       the commitment is treated as material and escalated. Failing open here
       would mean a hearing that ran out of budget silently exonerated
       everything it had not got to yet.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from court.arbiter import ArbiterOutcome, NeutralArbiter
from court.owners import CommitmentOwner
from court.team import RepairTeam
from judgment.model import T2Model
from lib.config import Tier
from lib.schema import Challenge, Plea, Repair
from lib.telemetry import agent_decision_span, policy_gate_span

#: Exactly four. Asserted below, so a fifth turn is a test failure rather than a
#: design drift nobody notices.
TURN_CAP = 4


#: [ASSUMPTION] Model calls a single repair may spend: one plea per owner, plus
#: one ruling, plus a small margin for a retry. Sized from the team, so a bigger
#: hearing gets a bigger budget but never an unbounded one.
def budget_for(team_size: int) -> int:
    return team_size + 3


class ProtocolError(RuntimeError):
    """The protocol was asked to do something its shape forbids."""


@dataclass
class Brief:
    """The notice as it concerns ONE commitment. What an owner is served with."""

    conclusion_id: str
    owner_id: str
    shock_days: int | None
    slack_days: int | None
    rederived_lead_days: int | None = None
    contested_resource: str | None = None


@dataclass
class Notice:
    """Turn 1. Published by the arbiter, to the whole team at once."""

    claim_id: str
    old_value: Any
    new_value: Any
    reason: str
    briefs: dict[str, Brief] = field(default_factory=dict)

    def brief_for(self, conclusion_id: str) -> Brief | None:
        return self.briefs.get(conclusion_id)


@dataclass
class CostLedger:
    """A budget that can only go down."""

    allowance: int
    spent: int = 0

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.allowance

    def draw(self, n: int = 1) -> bool:
        if self.spent + n > self.allowance:
            return False
        self.spent += n
        return True


@dataclass
class Proceedings:
    """Everything the hearing produced, including what it threw away."""

    repair: Repair
    team: RepairTeam
    outcome: ArbiterOutcome | None
    notice: Notice
    turns_used: int = 0
    converged: bool = True
    ledger: CostLedger = field(default_factory=lambda: CostLedger(allowance=0))

    @property
    def dissent(self) -> list[str]:
        return self.outcome.dissent if self.outcome else []

    @property
    def escalated(self) -> bool:
        return bool(self.outcome and self.outcome.escalated)


def run_repair(
    *,
    notice: Notice,
    team: RepairTeam,
    owners: list[CommitmentOwner],
    model: T2Model,
    now: datetime,
    arbiter: NeutralArbiter | None = None,
    total_exposure_minor: int = 0,
    assessor: str | None = None,
    rederiver: str | None = None,
) -> Proceedings:
    """Run all four turns, once, in order.

    The phases are data. `PHASES` is walked with a plain `for` over a fixed
    tuple -- the loop is over four known elements, not over a condition, which
    is what makes the bound structural.
    """
    team.require_live()
    arbiter = arbiter or NeutralArbiter()
    ledger = CostLedger(allowance=budget_for(team.size))
    repair = Repair(
        repair_id=team.repair_id,
        claim_id=notice.claim_id,
        member_owner_ids=team.owner_ids,
    )
    proceedings = Proceedings(repair=repair, team=team, outcome=None, notice=notice, ledger=ledger)

    state: dict[str, Any] = {
        "notice": notice,
        "owners": owners,
        "model": model,
        "now": now,
        "arbiter": arbiter,
        "total_exposure_minor": total_exposure_minor,
        "assessor": assessor,
        "rederiver": rederiver,
        "pleas": [],
        "challenges": [],
    }

    if len(PHASES) != TURN_CAP:
        raise ProtocolError(
            f"the protocol has {len(PHASES)} phases but the turn cap is {TURN_CAP}; "
            "the cap is not a suggestion and the two must not drift apart."
        )

    with policy_gate_span("four_turn_protocol", Tier.T2) as span:
        for index, (name, phase) in enumerate(PHASES, start=1):
            with agent_decision_span(f"court-turn-{index}-{name}", Tier.T2) as turn_span:
                phase(state, proceedings)
                proceedings.turns_used = index
                turn_span.set_attribute("unwind.turn", index)
                turn_span.set_attribute("unwind.budget_spent", ledger.spent)
        span.set_attribute("unwind.turns_used", proceedings.turns_used)
        span.set_attribute("unwind.converged", proceedings.converged)
        span.set_attribute("unwind.budget_allowance", ledger.allowance)
        span.set_attribute("unwind.budget_spent", ledger.spent)

    return proceedings


# --------------------------------------------------------------------------
# The four phases. Each takes (state, proceedings) and returns nothing; the
# signature is uniform so `PHASES` can be a tuple rather than a hand-written
# sequence of calls that could grow a fifth entry unnoticed.
# --------------------------------------------------------------------------


def _turn_notice(state: dict[str, Any], proceedings: Proceedings) -> None:
    """Turn 1. Publication is free -- no model, no budget drawn."""
    proceedings.repair.member_owner_ids = proceedings.team.owner_ids


def _turn_plea(state: dict[str, Any], proceedings: Proceedings) -> None:
    """Turn 2. One plea per owner, and the N owners plead IN PARALLEL.

    ⚠ THE PARALLELISM IS THE POINT, NOT AN OPTIMISATION. Owners are agent tools
    called by a parent that keeps the floor: it fans N of them out at once,
    waits, and then rules. Had they been sub-agents the parent would have handed
    over control at the first delegation and could not have done either half.
    That is the ADK 2 justification for this project, so it is executed rather
    than described -- `tests/test_court.py` asserts the pleas genuinely overlap
    in time.

    Budget is drawn BEFORE fan-out, so the cost bound holds regardless of how
    the futures interleave. Results are collected in submission order, so a
    parallel hearing and a serial one produce the same transcript.
    """
    notice: Notice = state["notice"]
    admitted: list[tuple[CommitmentOwner, Brief]] = []
    for owner in state["owners"]:
        brief = notice.brief_for(owner.conclusion_id)
        if brief is None:
            continue
        if not proceedings.ledger.draw():
            # Out of budget. Everything admitted still pleads; everything not
            # reached is handled by the conservative default.
            proceedings.converged = False
            break
        admitted.append((owner, brief))

    model = state["model"]
    if len(admitted) <= 1:
        pleas = [owner.plead(brief, model) for owner, brief in admitted]
    else:
        with ThreadPoolExecutor(max_workers=len(admitted)) as pool:
            futures = [pool.submit(owner.plead, brief, model) for owner, brief in admitted]
            pleas = [f.result() for f in futures]

    state["pleas"] = pleas
    proceedings.repair.pleas = pleas


def _turn_challenge(state: dict[str, Any], proceedings: Proceedings) -> None:
    """Turn 3. Only where two commitments contend for the same finite thing."""
    notice: Notice = state["notice"]
    pleas: list[Plea] = state["pleas"]
    owners: dict[str, CommitmentOwner] = {o.conclusion_id: o for o in state["owners"]}
    challenges: list[Challenge] = []

    by_resource: dict[str, list[Plea]] = {}
    for plea in pleas:
        brief = notice.brief_for(plea.conclusion_id)
        if brief and brief.contested_resource:
            by_resource.setdefault(brief.contested_resource, []).append(plea)

    for resource, contenders in sorted(by_resource.items()):
        if len(contenders) < 2:
            continue  # nothing is contended when only one party wants it
        for plea in contenders:
            owner = owners.get(plea.conclusion_id)
            if owner is None:
                continue
            for other in contenders:
                if other.conclusion_id == plea.conclusion_id:
                    continue
                challenge = owner.challenge(other, resource=resource)
                if challenge is not None:
                    challenges.append(challenge)

    state["challenges"] = challenges
    proceedings.repair.challenges = challenges


def _turn_ruling(state: dict[str, Any], proceedings: Proceedings) -> None:
    """Turn 4. The arbiter rules, or the conservative default does."""
    if not proceedings.ledger.draw():
        proceedings.converged = False

    outcome = state["arbiter"].rule(
        notice=state["notice"],
        pleas=state["pleas"],
        challenges=state["challenges"],
        owner_ids=proceedings.team.owner_ids,
        model=state["model"],
        now=state["now"],
        total_exposure_minor=state["total_exposure_minor"],
        converged=proceedings.converged,
        assessor=state["assessor"],
        rederiver=state["rederiver"],
    )
    proceedings.outcome = outcome
    proceedings.repair.ruling = outcome.ruling
    proceedings.repair.dissent = outcome.dissent


#: The whole protocol, as data. Four entries, asserted at run time.
PHASES: tuple[tuple[str, Callable[[dict[str, Any], Proceedings], None]], ...] = (
    ("notice", _turn_notice),
    ("plea", _turn_plea),
    ("challenge", _turn_challenge),
    ("ruling", _turn_ruling),
)
